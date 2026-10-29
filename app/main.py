"""应用入口。"""

from __future__ import annotations

import ctypes
import logging
import logging.handlers
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.app_controller import SIGNAL_EVENT_NAME, AppController
from app.config import APP_DIR, APP_NAME, LOG_DIR, Config
from app.ui.tray import make_icon
from app.win32.winutils import signal_event

log = logging.getLogger("app")

_MUTEX = None


def _single_instance() -> bool:
    global _MUTEX
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ctypes.set_last_error(0)
    _MUTEX = kernel32.CreateMutexW(None, False, "Local\\ScreenshotTranslate_Single")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def _setup_logging(debug: bool) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_DIR / "app.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass  # 没有日志目录也要能跑

    try:
        if debug or (sys.stdout is not None and sys.stdout.isatty()):
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            root.addHandler(sh)
    except Exception:
        pass


def _excepthook(exc_type, exc, tb) -> None:
    log.error("未捕获的异常", exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def _selftest() -> int:
    """`--selftest`：截一块屏幕做 OCR，用于验证打包后的 exe 是否完整。"""
    import time

    from app.ocr.rapidocr_engine import RapidOcrEngine, model_dir
    from app.win32.capture import grab_monitor
    from app.win32.monitors import enum_monitors

    report: list[str] = [f"frozen={getattr(sys, 'frozen', False)}"]
    ok = False
    try:
        mons = enum_monitors()
        report.append(f"monitors={len(mons)}")
        mon = next((m for m in mons if m.primary), mons[0])
        report.append(f"monitor={mon.device} {mon.w}x{mon.h}")
        img = grab_monitor(mon)
        if img is None or img.isNull():
            report.append("capture=FAILED")
        else:
            report.append(f"capture={img.width()}x{img.height()}")
            w = min(1200, img.width())
            h = min(400, img.height())
            crop = img.copy((img.width() - w) // 2, (img.height() - h) // 2, w, h)
            engine = RapidOcrEngine()
            t0 = time.perf_counter()
            res = engine.recognize(crop)
            dt = time.perf_counter() - t0
            report.append(f"models={model_dir()}")
            report.append(f"ocr={len(res.lines)} lines / {dt:.2f}s")
            for line in res.lines[:5]:
                report.append("  " + line.text[:40])
            ok = bool(res.lines)
    except Exception as exc:  # noqa: BLE001
        report.append(f"ERROR {type(exc).__name__}: {exc}")
        log.exception("自检失败")

    text = "\n".join(report)
    log.info("SELFTEST\n%s", text)
    try:
        (APP_DIR / "selftest.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass
    if sys.stdout:
        print(text)
        sys.stdout.flush()
    return 0 if ok else 2


def main() -> int:
    debug = "--debug" in sys.argv
    _setup_logging(debug)
    sys.excepthook = _excepthook

    if "--selftest" in sys.argv:
        return _selftest()

    if not _single_instance():
        if signal_event(SIGNAL_EVENT_NAME):
            log.info("已通知正在运行的实例打开设置")
        else:
            log.info("已有一个实例在运行，退出")
        return 0

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("截屏翻译")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_icon(128))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("系统托盘不可用")

    cfg = Config.load()
    log.info("配置：%s", cfg._path)
    log.info("热键：%s / 模型：%s / 目标语言：%s",
             cfg.hotkey, cfg.model, cfg.target_lang)

    controller = AppController(app, cfg)
    app.aboutToQuit.connect(controller.quit)
    controller.start()

    return app.exec()
