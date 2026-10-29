"""冻结层 + 区域选择。

设计要点
--------
* 每块显示器一个窗口，窗口几何 = 该屏物理矩形。这样每块屏的 DPR 天然正确，
  不会出现"一个窗口横跨多屏导致内容被整体缩放"的问题。
* 所有选区坐标都是**物理像素**，鼠标位置直接取 Win32 GetCursorPos，
  完全不依赖 Qt 的虚拟桌面逻辑坐标，跨屏也不会有偏差。
* 窗口内部把物理坐标按 "窗口宽 / 显示器物理宽" 缩放，不假设 dpr 的整数性。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QWidget

from app.core.geometry import monitor_at
from app.win32.monitors import Monitor
from app.win32.winutils import get_cursor_pos, place_physical, set_foreground

log = logging.getLogger(__name__)

MIN_SIZE = 6  # 物理像素；小于此视为误触
ACCENT = QColor(76, 154, 255)
DIM = QColor(0, 0, 0, 110)
ZOOM = 8


class SelectionModel(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._start = QPoint()
        self._cur = QPoint()
        self.active = False

    def begin(self, x: int, y: int) -> None:
        self.active = True
        self._start = QPoint(x, y)
        self._cur = QPoint(x, y)
        self.changed.emit()

    def update(self, x: int, y: int) -> None:
        if not self.active:
            return
        self._cur = QPoint(x, y)
        self.changed.emit()

    def end(self) -> None:
        self.active = False
        self.changed.emit()

    def reset(self) -> None:
        self.active = False
        self._start = QPoint()
        self._cur = QPoint()
        self.changed.emit()

    def rect(self) -> QRect:
        return QRect(self._start, self._cur).normalized()

    def valid(self) -> bool:
        r = self.rect()
        return r.width() >= MIN_SIZE and r.height() >= MIN_SIZE


class OverlayWindow(QWidget):
    def __init__(self, mon: Monitor, image: QImage, model: SelectionModel,
                 controller: "OverlayController") -> None:
        super().__init__(None)
        self.mon = mon
        self.image = image
        self.model = model
        self.controller = controller
        self.cursor_pos = QPointF(-1000, -1000)
        self.show_hint = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        if mon.screen is not None:
            try:
                self.setScreen(mon.screen)
            except Exception:
                pass
        self.setGeometry(self._initial_geometry())

    # ------------------------------------------------------------------
    def _initial_geometry(self) -> QRect:
        if self.mon.screen is not None:
            return self.mon.screen.geometry()
        return QRect(0, 0, self.mon.w, self.mon.h)

    def apply_physical_geometry(self) -> None:
        """show() 之后用物理像素精确校正位置，避免取整造成 1px 缝隙。"""
        place_physical(
            int(self.winId()), self.mon.x, self.mon.y, self.mon.w, self.mon.h, show=True
        )
        self.sync_logical()

    def sync_logical(self) -> None:
        """把窗口在 Qt 逻辑坐标里的矩形回填给 Monitor，供结果卡定位使用。"""
        try:
            self.mon.logical_rect = QRect(self.geometry())
            if self.mon.w:
                self.mon.scale = self.width() / self.mon.w
        except Exception:
            pass

    # ------------------------------------------------------------------
    @property
    def scale(self) -> float:
        return self.width() / self.mon.w if self.mon.w else 1.0

    def to_local(self, r: QRect) -> QRectF:
        s = self.scale
        return QRectF(
            (r.x() - self.mon.x) * s,
            (r.y() - self.mon.y) * s,
            r.width() * s,
            r.height() * s,
        )

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # 1) 冻结画面
        p.drawImage(self.rect(), self.image)

        # 2) 压暗选区以外的区域
        sel = self.model.rect() if self.model.active or self.model.valid() else QRect()
        sel_local = self.to_local(sel) if not sel.isNull() else QRectF()
        p.save()
        if sel_local.isNull():
            p.fillRect(self.rect(), DIM)
        else:
            region = QRegion(self.rect()).subtracted(QRegion(sel_local.toRect()))
            p.setClipRegion(region)
            p.fillRect(self.rect(), DIM)
        p.restore()

        # 3) 选区边框
        if not sel_local.isNull():
            p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawRect(sel_local.adjusted(-0.5, -0.5, 0.5, 0.5))
            p.setPen(QPen(ACCENT, 1))
            p.drawRect(sel_local)
            self._draw_size_label(p, sel, sel_local)

        # 4) 放大镜
        self._draw_magnifier(p)

        # 5) 底部提示
        if self.show_hint and not self.model.active:
            self._draw_hint(p)

        p.end()

    # ------------------------------------------------------------------
    def _draw_size_label(self, p: QPainter, sel: QRect, sel_local: QRectF) -> None:
        text = f"{sel.width()} × {sel.height()}"
        font = QFont("Microsoft YaHei UI", 9)
        p.setFont(font)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 12
        h = fm.height() + 6
        x = sel_local.left()
        y = sel_local.top() - h - 4
        if y < 2:
            y = sel_local.top() + 4
        x = max(2.0, min(x, self.width() - w - 2))
        box = QRectF(x, y, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(QColor(255, 255, 255))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_hint(self, p: QPainter) -> None:
        text = "拖动框选要翻译的区域    右键 / Esc 取消"
        font = QFont("Microsoft YaHei UI", 10)
        p.setFont(font)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 28
        h = fm.height() + 14
        box = QRectF((self.width() - w) / 2, self.height() - h - 48, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 165))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QColor(235, 238, 242))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.setBrush(Qt.BrushStyle.NoBrush)

    # ------------------------------------------------------------------
    def _draw_magnifier(self, p: QPainter) -> None:
        cx, cy = self.cursor_pos.x(), self.cursor_pos.y()
        if cx < 0 or cy < 0 or cx > self.width() or cy > self.height():
            return

        s = self.scale or 1.0
        # 光标在本屏物理坐标
        px = self.mon.x + cx / s
        py = self.mon.y + cy / s
        # 取源图上的物理像素区域
        sample_w = 18
        sample_h = 13
        sx = int(px - self.mon.x) - sample_w // 2
        sy = int(py - self.mon.y) - sample_h // 2
        src = self.image.copy(sx, sy, sample_w, sample_h)
        if src.isNull():
            return

        box_w, box_h = 144.0, 104.0
        gap = 22.0
        bx = cx + gap
        by = cy + gap
        if bx + box_w > self.width() - 8:
            bx = cx - gap - box_w
        if by + box_h > self.height() - 8:
            by = cy - gap - box_h
        bx = max(8.0, bx)
        by = max(8.0, by)
        target = QRectF(bx, by, box_w, box_h)

        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(target, src)
        p.setPen(QPen(QColor(0, 0, 0, 200), 1))
        p.drawRect(target)

        # 中心十字
        cxm = target.center().x()
        cym = target.center().y()
        p.setPen(QPen(ACCENT, 1))
        p.drawLine(QPointF(cxm, target.top() + 2), QPointF(cxm, target.bottom() - 2))
        p.drawLine(QPointF(target.left() + 2, cym), QPointF(target.right() - 2, cym))

        # 取色 + 坐标
        color = QColor(src.pixel(sample_w // 2, sample_h // 2))
        info = f"#{color.red():02X}{color.green():02X}{color.blue():02X}   {int(px)}, {int(py)}"
        p.setFont(QFont("Consolas", 9))
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(info) + 14
        th = fm.height() + 6
        tbox = QRectF(bx, by + box_h + 4, max(tw, box_w), th)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        p.drawRoundedRect(tbox, 3, 3)
        p.setPen(QColor(255, 255, 255))
        p.drawText(tbox, Qt.AlignmentFlag.AlignCenter, info)
        p.restore()

    # ------------------------------------------------------------------
    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            x, y = get_cursor_pos()
            self.controller.on_press(x, y)
            e.accept()
        elif e.button() == Qt.MouseButton.RightButton:
            self.controller.cancel()
            e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        x, y = get_cursor_pos()
        self.controller.on_move(x, y)
        e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            x, y = get_cursor_pos()
            self.controller.on_release(x, y)
            e.accept()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.controller.cancel()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.controller.confirm()
        e.accept()


class OverlayController(QObject):
    selected = Signal(object, object)   # QRect(物理), Monitor
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.model = SelectionModel()
        self.model.changed.connect(self._on_changed)
        self.monitors: list[Monitor] = []
        self.windows: list[OverlayWindow] = []
        self._done = False
        self._cursor = (0, 0)

    # ------------------------------------------------------------------
    def start(self, monitors: list[Monitor], images: list[QImage]) -> bool:
        self._done = False
        self.model.reset()
        self.monitors = monitors
        self.windows = []

        for mon, img in zip(monitors, images):
            if img is None or img.isNull():
                continue
            w = OverlayWindow(mon, img, self.model, self)
            self.windows.append(w)

        if not self.windows:
            return False

        for w in self.windows:
            w.show()
            w.apply_physical_geometry()
            w.raise_()

        self._cursor = get_cursor_pos()
        focus = self._window_for(*self._cursor) or self.windows[0]
        focus.show_hint = True
        focus.activateWindow()
        focus.setFocus()
        focus.grabKeyboard()
        try:
            set_foreground(int(focus.winId()))
        except Exception:
            pass
        return True

    # ------------------------------------------------------------------
    def _window_for(self, x: int, y: int) -> OverlayWindow | None:
        for w in self.windows:
            if w.mon.contains(x, y):
                return w
        return None

    def _update_all(self) -> None:
        for w in self.windows:
            w.cursor_pos = self._cursor_local(w)
            w.update()

    def _cursor_local(self, w: OverlayWindow) -> QPointF:
        s = w.scale or 1.0
        return QPointF((self._cursor[0] - w.mon.x) * s, (self._cursor[1] - w.mon.y) * s)

    def _on_changed(self) -> None:
        self._update_all()

    # ------------------------------------------------------------------
    def on_press(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        self.model.begin(x, y)

    def on_move(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        if self.model.active:
            self.model.update(x, y)
        else:
            self._update_all()

    def on_release(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        if self._done:
            return
        if not self.model.active:
            return
        self.model.update(x, y)
        self.model.end()
        self._finish(force=False)

    def confirm(self) -> None:
        if self._done:
            return
        self._finish(force=True)

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._teardown()
        self.cancelled.emit()

    # ------------------------------------------------------------------
    def _finish(self, force: bool) -> None:
        if self._done:
            return
        rect = self.model.rect()
        if not force and (rect.width() < MIN_SIZE or rect.height() < MIN_SIZE):
            self.cancel()
            return
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            self.cancel()
            return

        mon = monitor_at(self.monitors, rect.center().x(), rect.center().y())
        if mon is not None:
            for w in self.windows:
                if w.mon is mon:
                    w.sync_logical()
                    break
        self._done = True
        self._teardown()
        if mon is None:
            self.cancelled.emit()
            return
        self.selected.emit(rect, mon)

    def _teardown(self) -> None:
        for w in self.windows:
            try:
                w.releaseKeyboard()
            except Exception:
                pass
            w.hide()
            w.deleteLater()
        self.windows = []
