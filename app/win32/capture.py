"""屏幕截取（GDI BitBlt → QImage）。

为什么不用 mss：需要在 Per-Monitor V2 感知下精确控制物理像素坐标，
并且要能一次抓一块任意物理矩形（包括负坐标）。自己用 ctypes 调 GDI 最直接。

后续如果要支持硬件加速内容（视频/游戏），可在这个模块里加 DXGI / WGC 后端，
对外接口保持 `grab_rect()` 不变。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtGui import QImage

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0

BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


# ---- 显式声明 64 位下会被截断的句柄返回值 ----
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL


def grab_rect(x: int, y: int, w: int, h: int) -> QImage | None:
    """抓取虚拟桌面上的物理矩形，返回 Format_RGB32 的 QImage（已深拷贝）。

    失败返回 None（例如 RDP 会话、受保护内容）。
    """
    if w <= 0 or h <= 0:
        return None

    hdc_screen = user32.GetDC(None)
    if not hdc_screen:
        return None

    hdc_mem = None
    hbmp = None
    old_obj = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        if not hdc_mem:
            return None

        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h  # 负数 = 自上而下
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_mem, ctypes.byref(bi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
        )
        if not hbmp or not bits:
            return None

        old_obj = gdi32.SelectObject(hdc_mem, hbmp)

        ok = gdi32.BitBlt(
            hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY | CAPTUREBLT
        )
        if not ok:
            return None

        buf = ctypes.string_at(bits, w * h * 4)
        # BITMAP 是 BGRA，且小端序下与 Format_RGB32(ARGB32) 内存布局一致。
        img = QImage(buf, w, h, w * 4, QImage.Format.Format_RGB32)
        return img.copy()  # 脱离 ctypes 缓冲区
    except Exception:
        return None
    finally:
        if hdc_mem:
            if old_obj:
                gdi32.SelectObject(hdc_mem, old_obj)
            if hbmp:
                gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)


def grab_monitor(mon) -> QImage | None:
    return grab_rect(mon.x, mon.y, mon.w, mon.h)
