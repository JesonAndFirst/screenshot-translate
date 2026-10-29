"""进程 DPI 感知。

必须在创建任何窗口（尤其是 QApplication）之前调用，否则 Win32 返回的是
被系统缩放过的"虚拟"坐标，截图也会是模糊的放大图。
"""

from __future__ import annotations

import ctypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

_MODE = "none"


def enable_per_monitor_dpi_v2() -> str:
    """按 Per-Monitor V2 → Per-Monitor → System 的顺序降级设置 DPI 感知。

    返回实际生效的模式，便于日志与排错。
    """
    global _MODE
    try:
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_int
        if fn(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            _MODE = "per-monitor-v2"
            return _MODE
    except Exception:
        pass

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        if shcore.SetProcessDpiAwareness(2) == 0:
            _MODE = "per-monitor"
            return _MODE
    except Exception:
        pass

    try:
        if user32.SetProcessDPIAware():
            _MODE = "system"
            return _MODE
    except Exception:
        pass

    _MODE = "none"
    return _MODE


def current_mode() -> str:
    return _MODE


def is_dpi_aware() -> bool:
    return _MODE != "none"
