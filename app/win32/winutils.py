"""零散的 Win32 窗口/光标操作。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11

user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.SetFocus.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.SetWindowLongW.restype = wintypes.LONG
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def get_cursor_pos() -> tuple[int, int]:
    """物理像素坐标。进程是 Per-Monitor V2 感知时才是真实物理像素。"""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return (int(pt.x), int(pt.y))


def set_foreground(hwnd: int) -> None:
    """尽最大努力把窗口提到前台并给焦点（对抗前台锁定）。"""
    try:
        fg = user32.GetForegroundWindow()
        if fg and fg != hwnd:
            tid_fg = user32.GetWindowThreadProcessId(fg, None)
            tid_me = kernel32.GetCurrentThreadId()
            attached = False
            if tid_fg and tid_fg != tid_me:
                attached = bool(user32.AttachThreadInput(tid_me, tid_fg, True))
            try:
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(tid_me, tid_fg, False)
        else:
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def place_physical(hwnd: int, x: int, y: int, w: int, h: int, show: bool = True) -> None:
    """用物理像素精确摆放窗口，避开 Qt 逻辑坐标的取整误差。"""
    flags = SWP_NOACTIVATE | (SWP_SHOWWINDOW if show else 0)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), int(w), int(h), flags)


def bring_to_front(hwnd: int) -> None:
    """后台进程把窗口提到最前：先临时置顶再取消置顶。

    单纯 SetForegroundWindow 会被 Windows 的前台锁定拦掉；置顶是纯 z-order 操作，
    不受限制，抬起来之后再交还焦点。
    """
    try:
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
        user32.SetWindowPos(
            hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
        )
    except Exception:
        pass
    set_foreground(hwnd)


def make_tool_window(hwnd: int) -> None:
    """不在任务栏/Alt-Tab 中出现。"""
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
    except Exception:
        pass


def exclude_from_capture(hwnd: int) -> bool:
    """让窗口不出现在他人的截图/录屏里（Win10 2004+）。"""
    try:
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 单实例唤醒：第二个进程通过命名事件通知第一个进程“打开设置”。
# 比 FindWindow 可靠——隐藏窗口的标题在 Qt 里不一定会写到原生窗口上。
# ---------------------------------------------------------------------------

EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0

kernel32.CreateEventW.argtypes = [
    ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR
]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def create_signal_event(name: str) -> int:
    """创建（或打开）自动重置事件，返回句柄；失败返回 0。"""
    try:
        return int(kernel32.CreateEventW(None, False, False, name) or 0)
    except Exception:
        return 0


def signal_event(name: str) -> bool:
    """由第二个实例调用：唤醒已运行的实例。"""
    try:
        handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
        if not handle:
            return False
        try:
            return bool(kernel32.SetEvent(handle))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def wait_event(handle: int, timeout_ms: int = 0) -> bool:
    return bool(handle) and kernel32.WaitForSingleObject(handle, timeout_ms) == WAIT_OBJECT_0


def close_handle(handle: int) -> None:
    try:
        if handle:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
