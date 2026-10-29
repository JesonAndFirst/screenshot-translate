"""显示器枚举与 Qt 屏幕绑定。

坐标系约定（全项目统一）：
    物理像素 = Win32 原生坐标，可能是负数（副屏在主屏左侧/上方）。
    逻辑像素 = Qt 的 device-independent 坐标，随 DPI 缩放。

内部计算一律用物理像素；只有"画到 Qt 窗口"和"摆放 Qt 窗口"时才转成逻辑像素。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

from PySide6.QtGui import QGuiApplication, QScreen

user32 = ctypes.WinDLL("user32", use_last_error=True)

MONITORINFOF_PRIMARY = 0x00000001
MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTOPRIMARY = 1


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)


@dataclass
class Monitor:
    """一块物理显示器。"""

    hmon: int
    device: str  # 形如 \\.\DISPLAY1
    x: int
    y: int
    w: int
    h: int
    work: tuple[int, int, int, int]  # 工作区（不含任务栏），物理像素
    primary: bool
    screen: QScreen | None = None
    dpr: float = 1.0
    # 由冻结层窗口在 show 之后回填：该屏在 Qt 逻辑坐标里的矩形，以及 逻辑/物理 比例。
    # 用窗口自身的 geometry 反推，比依赖 QScreen 的虚拟桌面布局更可靠。
    logical_rect: object = None
    scale: float | None = None
    extra: dict = field(default_factory=dict)

    # ---- 便捷访问 ----
    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def __str__(self) -> str:
        return f"{self.device} ({self.w}x{self.h} @ {self.x},{self.y})"


def _normalize_device(name: str) -> str:
    n = (name or "").strip().lower()
    if n.startswith("\\\\.\\"):
        n = n[4:]
    elif n.startswith("\\\\.\\"):
        n = n[4:]
    return n.replace("\\", "")


def enum_monitors() -> list[Monitor]:
    """枚举当前所有显示器（物理像素）。每次截图前重新调用，不做缓存。"""
    result: list[Monitor] = []

    def _callback(hmon, hdc, lprc, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return True
        r = info.rcMonitor
        wk = info.rcWork
        result.append(
            Monitor(
                hmon=int(hmon) if hmon else 0,
                device=info.szDevice,
                x=r.left,
                y=r.top,
                w=r.right - r.left,
                h=r.bottom - r.top,
                work=(wk.left, wk.top, wk.right - wk.left, wk.bottom - wk.top),
                primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
            )
        )
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_callback), 0)
    result.sort(key=lambda m: (not m.primary, m.x, m.y))
    return result


def monitor_from_point(x: int, y: int) -> int:
    pt = wintypes.POINT(x, y)
    hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONULL)
    return int(hmon) if hmon else 0


def _match_by_geometry(mon: Monitor, screens: list[QScreen]) -> QScreen | None:
    """设备名对不上时，用"物理矩形 ≈ Qt 逻辑矩形 × dpr"来兜底匹配。"""
    best = None
    best_err = None
    for s in screens:
        dpr = s.devicePixelRatio() or 1.0
        g = s.geometry()
        err = (
            abs(g.x() * dpr - mon.x)
            + abs(g.y() * dpr - mon.y)
            + abs(g.width() * dpr - mon.w)
            + abs(g.height() * dpr - mon.h)
        )
        if best_err is None or err < best_err:
            best, best_err = s, err
    if best is not None and best_err is not None and best_err < 8:
        return best
    return None


def bind_qt_screens(monitors: list[Monitor]) -> list[Monitor]:
    """把 Win32 显示器与 QScreen 关联起来，并填入 dpr。"""
    screens = list(QGuiApplication.screens())
    by_name = {}
    for s in screens:
        by_name.setdefault(_normalize_device(s.name()), s)

    used: set[int] = set()
    for m in monitors:
        s = by_name.get(_normalize_device(m.device))
        if s is None or id(s) in used:
            s = _match_by_geometry(m, [x for x in screens if id(x) not in used])
        if s is not None:
            m.screen = s
            m.dpr = float(s.devicePixelRatio() or 1.0)
            used.add(id(s))
    return monitors


def virtual_rect(monitors: list[Monitor]) -> tuple[int, int, int, int]:
    if not monitors:
        return (0, 0, 0, 0)
    x0 = min(m.x for m in monitors)
    y0 = min(m.y for m in monitors)
    x1 = max(m.right for m in monitors)
    y1 = max(m.bottom for m in monitors)
    return (x0, y0, x1 - x0, y1 - y0)
