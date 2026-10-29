"""主题色。"""

from __future__ import annotations

import winreg

DARK = {
    "bg": "#1f2023",
    "bg_soft": "#2a2c31",
    "bg_hover": "#34373d",
    "border": "#3a3d44",
    "text": "#eceef2",
    "text_sub": "#9aa1ad",
    "accent": "#4c9aff",
    "accent_text": "#ffffff",
    "thumb_bg": "#141517",
    "error": "#ff6b6b",
}

LIGHT = {
    "bg": "#ffffff",
    "bg_soft": "#f4f5f7",
    "bg_hover": "#e9ebef",
    "border": "#e3e5e9",
    "text": "#1b1d21",
    "text_sub": "#6b7280",
    "accent": "#2f7cf6",
    "accent_text": "#ffffff",
    "thumb_bg": "#eceef2",
    "error": "#d93025",
}


def system_uses_dark() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as k:
            value, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return int(value) == 0
    except Exception:
        return True


def resolve(theme: str) -> dict:
    if theme == "dark":
        return DARK
    if theme == "light":
        return LIGHT
    return DARK if system_uses_dark() else LIGHT


def is_dark(theme: str) -> bool:
    return resolve(theme) is DARK
