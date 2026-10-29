"""物理像素 ↔ Qt 逻辑像素 的换算。

核心假设（Qt 在 Windows 上成立）：每块 QScreen 的逻辑矩形尺寸 = 物理尺寸 / dpr。
因此用"窗口实际尺寸 / 显示器物理尺寸"作为比例，比直接读 dpr 更稳，
能自动吸收 Qt 的取整误差。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF

from app.win32.monitors import Monitor


def scale_for(mon: Monitor) -> float:
    """逻辑像素 / 物理像素。"""
    if mon.scale:
        return mon.scale
    if mon.screen is not None:
        g = mon.screen.geometry()
        if g.width() > 0 and mon.w > 0:
            return g.width() / mon.w
    return 1.0 / (mon.dpr or 1.0)


def _logical_rect(mon: Monitor) -> QRect:
    if mon.logical_rect is not None:
        return QRect(mon.logical_rect)
    if mon.screen is not None:
        return mon.screen.geometry()
    return QRect(0, 0, mon.w, mon.h)


def to_logical_point(px: float, py: float, mon: Monitor) -> QPointF:
    s = scale_for(mon)
    g = _logical_rect(mon)
    return QPointF(g.x() + (px - mon.x) * s, g.y() + (py - mon.y) * s)


def to_logical_rect(rect: QRect, mon: Monitor) -> QRectF:
    s = scale_for(mon)
    g = _logical_rect(mon)
    return QRectF(
        g.x() + (rect.x() - mon.x) * s,
        g.y() + (rect.y() - mon.y) * s,
        rect.width() * s,
        rect.height() * s,
    )


def to_physical_point(lp: QPointF, mon: Monitor) -> QPointF:
    s = scale_for(mon) or 1.0
    g = _logical_rect(mon)
    return QPointF(mon.x + (lp.x() - g.x()) / s, mon.y + (lp.y() - g.y()) / s)


def monitor_at(monitors: list[Monitor], px: int, py: int) -> Monitor | None:
    for m in monitors:
        if m.contains(px, py):
            return m
    # 落在两屏之间的空隙：取最近的一块
    if not monitors:
        return None
    return min(
        monitors,
        key=lambda m: (max(m.x - px, 0, px - m.right) ** 2
                       + max(m.y - py, 0, py - m.bottom) ** 2),
    )


def intersection(a: QRect, b: QRect) -> QRect:
    return a.intersected(b)


def clamp_rect(rect: QRect, bounds: QRect) -> QRect:
    """把矩形挪进 bounds（尺寸超了就贴边，不强行缩小）。"""
    x = rect.x()
    y = rect.y()
    if x + rect.width() > bounds.right():
        x = bounds.right() - rect.width()
    if y + rect.height() > bounds.bottom():
        y = bounds.bottom() - rect.height()
    x = max(x, bounds.x())
    y = max(y, bounds.y())
    return QRect(x, y, rect.width(), rect.height())


__all__ = [
    "scale_for",
    "to_logical_point",
    "to_logical_rect",
    "to_physical_point",
    "monitor_at",
    "intersection",
    "clamp_rect",
    "QPoint",
]
