"""全局热键（RegisterHotKey）。

不用键盘钩子：RegisterHotKey 由系统分发，无需管理员权限，也不容易被安全软件误判。
代价是不能用 Win+* 这类系统保留组合。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_VK_SPECIAL = {
    "PRINTSCREEN": 0x2C,
    "PRTSC": 0x2C,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "SPACE": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}

_MOD_NAMES = {"CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
              "ALT": MOD_ALT, "SHIFT": MOD_SHIFT, "WIN": MOD_WIN}


class HotkeyError(Exception):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Alt+Q' → (modifiers, virtual-key code)。"""
    parts = [p.strip() for p in (text or "").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("热键为空")

    mods = 0
    key_part = parts[-1]
    for p in parts[:-1]:
        m = _MOD_NAMES.get(p.upper())
        if m is None:
            raise HotkeyError(f"无法识别的修饰键：{p}")
        mods |= m

    k = key_part.upper()
    if k in _VK_SPECIAL:
        vk = _VK_SPECIAL[k]
    elif len(k) == 1 and (k.isalnum()):
        vk = ord(k)
    elif k.startswith("F") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        vk = 0x70 + int(k[1:]) - 1
    else:
        raise HotkeyError(f"无法识别的按键：{key_part}")

    return mods | MOD_NOREPEAT, vk


class _HotkeyHost(QWidget):
    """隐藏窗口，专门接收 WM_HOTKEY。"""

    triggered = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("ScreenshotTranslateHotkeyHost")
        self.resize(0, 0)

    def nativeEvent(self, event_type, message):  # noqa: N802 (Qt 命名)
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.triggered.emit()
                return True, 0
        except Exception:
            pass
        return False, 0


class HotkeyManager(QObject):
    activated = Signal()
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._host = _HotkeyHost()
        self._host.triggered.connect(self.activated)
        self._host_id = int(self._host.winId())  # 强制创建原生窗口
        self._registered = False
        self._text = ""

    @property
    def current(self) -> str:
        return self._text

    def register(self, text: str) -> bool:
        self.unregister()
        try:
            mods, vk = parse_hotkey(text)
        except HotkeyError as exc:
            self.failed.emit(str(exc))
            return False

        ok = bool(user32.RegisterHotKey(self._host_id, 1, mods, vk))
        if not ok:
            err = ctypes.get_last_error()
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                self.failed.emit(f"热键 {text} 已被其他程序占用，请换一个")
            else:
                self.failed.emit(f"注册热键 {text} 失败（错误码 {err}）")
            return False

        self._registered = True
        self._text = text
        return True

    def unregister(self) -> None:
        if self._registered:
            try:
                user32.UnregisterHotKey(self._host_id, 1)
            except Exception:
                pass
            self._registered = False

    def close(self) -> None:
        self.unregister()
        try:
            self._host.deleteLater()
        except Exception:
            pass
