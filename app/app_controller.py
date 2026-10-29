"""应用控制器：把热键、截屏、选区、OCR、翻译、卡片串起来。"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QPoint, QRect, QThreadPool, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from app.config import Config
from app.core.pipeline import JobSignals, TranslateJob, TranslateTextJob
from app.mt.llm import LlmTranslator
from app.ocr.rapidocr_engine import RapidOcrEngine
from app.ui.hint import HintWindow
from app.ui.overlay import OverlayController
from app.ui.result_card import ResultCard
from app.ui.settings import SettingsDialog
from app.ui.tray import Tray
from app.win32.capture import grab_monitor, grab_rect
from app.win32.hotkey import HotkeyManager
from app.win32.monitors import Monitor, bind_qt_screens, enum_monitors
from app.win32.winutils import (
    bring_to_front,
    close_handle,
    create_signal_event,
    wait_event,
)
log = logging.getLogger(__name__)

# 第二个实例通过这个命名事件唤醒已运行的实例（打开设置）
SIGNAL_EVENT_NAME = "Local\\ScreenshotTranslate_ShowSettings"


class AppController(QObject):
    def __init__(self, app: QApplication, cfg: Config) -> None:
        super().__init__()
        self.app = app
        self.cfg = cfg
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(2)

        self.ocr = RapidOcrEngine()
        self.signals = JobSignals()
        self.signals.ocr_done.connect(self._on_ocr_done)
        self.signals.finished.connect(self._on_finished)
        self.signals.failed.connect(self._on_failed)

        self.overlay = OverlayController()
        self.overlay.selected.connect(self._on_selected)
        self.overlay.cancelled.connect(self._on_overlay_cancelled)

        self.card = ResultCard(cfg.theme, cfg.card_width)
        self.card.copy_requested.connect(self._copy)
        self.card.retry_requested.connect(self._retry)

        self.tray = Tray(cfg.hotkey)
        self.hotkey = HotkeyManager()

        self._capturing = False
        self._job_id = 0
        self._images: dict[int, QImage] = {}
        self._monitors: list[Monitor] = []
        self._last_image: QImage | None = None
        self._last_source = ""
        self._translation = ""
        self._settings: SettingsDialog | None = None

    # ------------------------------------------------------------------
    def start(self) -> None:
        self.tray.capture_requested.connect(self.request_capture)
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.quit_requested.connect(self.quit)
        self.tray.show()

        self.hotkey.activated.connect(lambda: QTimer.singleShot(0, self.request_capture))
        self.hotkey.failed.connect(self._on_hotkey_failed)
        ok = self.hotkey.register(self.cfg.hotkey)
        if not ok:
            log.warning("热键注册失败：%s", self.cfg.hotkey)

        # 第二个实例（再次双击 exe）会 SetEvent，这里轮询后弹出设置
        self._signal_event = create_signal_event(SIGNAL_EVENT_NAME)
        self._signal_timer = QTimer(self)
        self._signal_timer.setInterval(500)
        self._signal_timer.timeout.connect(self._poll_signal)
        if self._signal_event:
            self._signal_timer.start()

        threading.Thread(target=self.ocr.warmup, daemon=True).start()

        # 没配 Key 就直接把设置窗口弹出来——顺便让用户看到“图标在哪”的说明
        if not self.cfg.api_key:
            QTimer.singleShot(600, self.open_settings)
        else:
            QTimer.singleShot(2500, self._maybe_show_tray_hint)

    # ------------------------------------------------------------------
    def _maybe_show_tray_hint(self) -> None:
        """托盘图标没显示出来时，用自绘小窗告诉用户怎么用（只提示一次）。"""
        if self.cfg.tray_hint_shown:
            return
        try:
            if not self.tray.geometry().isNull():
                return  # 图标正常显示，不需要提示
        except Exception:
            pass

        log.info("托盘图标不可见，显示一次启动提示")
        self.cfg.tray_hint_shown = True
        self.cfg.save()
        self._hint = HintWindow(self.cfg.theme)
        self._hint.settings_requested.connect(self.open_settings)
        self._hint.show_near_tray()
        QTimer.singleShot(12000, self._hint.close)

    # ------------------------------------------------------------------
    def _poll_signal(self) -> None:
        if wait_event(self._signal_event, 0):
            log.info("收到第二个实例的唤醒信号，打开设置")
            self.open_settings()

    # ------------------------------------------------------------------
    def _on_hotkey_failed(self, message: str) -> None:
        log.error(message)
        try:
            self.tray.showMessage("截屏翻译", message, self.tray.icon(), 6000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def request_capture(self) -> None:
        if self._capturing or self._settings is not None:
            return
        self._capturing = True
        try:
            self.card.hide()
            QApplication.processEvents()

            monitors = bind_qt_screens(enum_monitors())
            images: dict[int, QImage] = {}
            ordered: list[Monitor] = []
            for mon in monitors:
                img = grab_monitor(mon)
                if img is None or img.isNull():
                    log.warning("抓取失败：%s", mon)
                    continue
                images[id(mon)] = img
                ordered.append(mon)

            if not ordered:
                self.tray.showMessage(
                    "截屏翻译", "无法截取屏幕（可能是受保护内容或远程桌面）",
                    self.tray.icon(), 5000,
                )
                self._capturing = False
                return

            self._images = images
            self._monitors = ordered
            started = self.overlay.start(ordered, [images[id(m)] for m in ordered])
            if not started:
                self._capturing = False
            log.info("开始截图：%d 块屏幕", len(ordered))
        except Exception:
            log.exception("截图失败")
            self._capturing = False

    # ------------------------------------------------------------------
    def _on_overlay_cancelled(self) -> None:
        self._capturing = False
        log.info("已取消截图")

    def _on_selected(self, rect: QRect, mon: Monitor) -> None:
        self._capturing = False
        crop = self._compose_crop(rect)
        if crop is None or crop.isNull():
            self.tray.showMessage("截屏翻译", "选区无效", self.tray.icon(), 3000)
            return

        self._last_image = crop
        self._last_source = ""
        self._translation = ""

        self.card.present(rect, mon)
        self.card.set_thumbnail(QPixmap.fromImage(crop))
        QTimer.singleShot(0, lambda: self._start_ocr(crop))

    def _compose_crop(self, rect: QRect) -> QImage | None:
        """按选区把各块屏的冻结图拼成一张图（选区可以跨屏）。"""
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        crop = QImage(rect.size(), QImage.Format.Format_RGB32)
        crop.fill(0xFF000000)
        painter = QPainter(crop)
        painted = False
        for mon in self._monitors:
            inter = rect.intersected(QRect(mon.x, mon.y, mon.w, mon.h))
            if inter.isEmpty():
                continue
            src = self._images.get(id(mon))
            if src is None or src.isNull():
                continue
            sub = src.copy(
                inter.x() - mon.x, inter.y() - mon.y, inter.width(), inter.height()
            )
            if sub.isNull():
                continue
            painter.drawImage(inter.x() - rect.x(), inter.y() - rect.y(), sub)
            painted = True
        painter.end()
        return crop if painted else None

    # ------------------------------------------------------------------
    def _start_ocr(self, image: QImage) -> None:
        self._job_id += 1
        job = TranslateJob(
            self._job_id,
            image,
            self.ocr,
            LlmTranslator(self.cfg),
            self.cfg.target_lang,
            self._is_current,
            self.signals,
        )
        self.pool.start(job)

    def _is_current(self, job_id: int) -> bool:
        return job_id == self._job_id

    # ------------------------------------------------------------------
    def _on_ocr_done(self, job_id: int, paragraphs: list) -> None:
        if job_id != self._job_id:
            return
        self._last_source = "\n\n".join(paragraphs)
        self.card.set_source(self._last_source)
        self.card.set_status("翻译中…")

    def _on_finished(self, job_id: int, text: str) -> None:
        if job_id != self._job_id:
            return
        self._translation = text
        self.card.set_translation(text)
        if self.cfg.copy_on_finish:
            self._copy(silent=True)

    def _on_failed(self, job_id: int, stage: str, message: str) -> None:
        if job_id != self._job_id:
            return
        log.warning("任务失败 [%s]：%s", stage, message)
        self.card.set_error(message)

    # ------------------------------------------------------------------
    def _copy(self, silent: bool = False) -> None:
        if not self._translation:
            return
        QGuiApplication.clipboard().setText(self._translation)
        self.card.set_status("已复制")
        if not silent:
            log.info("已复制译文")

    def _retry(self) -> None:
        if self._last_image is None:
            return
        self._job_id += 1
        jid = self._job_id
        self.card.set_status("翻译中…")
        if self._last_source:
            job = TranslateTextJob(
                jid, self._last_source, LlmTranslator(self.cfg),
                self.cfg.target_lang, self._is_current, self.signals,
            )
        else:
            job = TranslateJob(
                jid, self._last_image, self.ocr, LlmTranslator(self.cfg),
                self.cfg.target_lang, self._is_current, self.signals,
            )
        self.pool.start(job)

    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        if self._settings is not None:
            self._settings.raise_()
            self._settings.activateWindow()
            try:
                bring_to_front(int(self._settings.winId()))
            except Exception:
                pass
            return
        dlg = SettingsDialog(self.cfg)
        dlg.saved.connect(self._on_settings_saved)
        dlg.finished.connect(self._on_settings_closed)
        dlg.quit_requested.connect(self.quit)
        self._settings = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        # 后台进程直接 show 会被前台窗口盖住，抬到最前
        try:
            bring_to_front(int(dlg.winId()))
        except Exception:
            pass

    def _on_settings_closed(self, _result: int) -> None:
        self._settings = None

    def _on_settings_saved(self) -> None:
        self.card.apply_theme(self.cfg.theme)
        self.tray.set_hotkey_text(self.cfg.hotkey)
        old = self.hotkey.current
        if old and old != self.cfg.hotkey:
            if not self.hotkey.register(self.cfg.hotkey):
                # 回滚到旧热键，并同步回配置
                self.hotkey.register(old)
                self.cfg.hotkey = old
                self.cfg.save()
                self.tray.set_hotkey_text(old)

    # ------------------------------------------------------------------
    def quit(self) -> None:
        if getattr(self, "_quitting", False):
            return
        self._quitting = True
        try:
            self._signal_timer.stop()
        except Exception:
            pass
        try:
            if self._signal_event:
                close_handle(self._signal_event)
        except Exception:
            pass
        try:
            self.hotkey.close()
        except Exception:
            pass
        try:
            self.card.hide()
            self.card.deleteLater()
        except Exception:
            pass
        self.pool.clear()
        self.app.quit()
