"""托盘图标与菜单。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon(size: int = 64) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2f7cf6"))
    r = size * 0.16
    p.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), r, r)
    p.setPen(QColor("#ffffff"))
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(int(size * 0.55))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "译")
    p.end()
    return QIcon(pix)


class Tray(QSystemTrayIcon):
    capture_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, hotkey_text: str) -> None:
        super().__init__(make_icon())
        self.setToolTip("截屏翻译")
        self._menu = QMenu()
        self._act_capture = QAction(f"截屏翻译\t{hotkey_text}", self._menu)
        self._act_settings = QAction("设置…", self._menu)
        self._act_quit = QAction("退出", self._menu)
        self._menu.addAction(self._act_capture)
        self._menu.addSeparator()
        self._menu.addAction(self._act_settings)
        self._menu.addSeparator()
        self._menu.addAction(self._act_quit)

        self._act_capture.triggered.connect(self.capture_requested)
        self._act_settings.triggered.connect(self.settings_requested)
        self._act_quit.triggered.connect(self.quit_requested)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.capture_requested.emit()

    def set_hotkey_text(self, text: str) -> None:
        self._act_capture.setText(f"截屏翻译\t{text}")
