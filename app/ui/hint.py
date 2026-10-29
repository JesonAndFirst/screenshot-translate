"""启动提示气泡。

为什么不用托盘气泡/QMessageBox：
  * 这台机器上任务栏通知区域不是标准 Explorer 的（没有 explorer.exe 进程），
    Shell_NotifyIcon 的图标不显示，托盘气泡也就没有了锚点；
  * QMessageBox 是普通窗口，后台进程弹出来容易被前台窗口盖住。
自绘一个无边框置顶小窗，最可控。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui import theme as theme_mod


class HintWindow(QWidget):
    settings_requested = Signal()

    WIDTH = 320

    def __init__(self, theme: str = "auto") -> None:
        super().__init__(None)
        self.c = theme_mod.resolve(theme)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(self.WIDTH)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)

        title = QLabel("截屏翻译已在后台运行")
        title.setObjectName("hintTitle")
        root.addWidget(title)

        body = QLabel(
            "按 Alt+Q 框选屏幕即可翻译。\n"
            "任务栏里找不到「译」图标？双击 exe 可以打开设置。"
        )
        body.setObjectName("hintBody")
        body.setWordWrap(True)
        root.addWidget(body)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_settings = QPushButton("打开设置")
        btn_settings.setObjectName("hintPrimary")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_settings.clicked.connect(self._on_settings)
        btn_close = QPushButton("知道了")
        btn_close.setObjectName("hintGhost")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.close)
        row.addWidget(btn_settings)
        row.addWidget(btn_close)
        row.addStretch(1)
        root.addLayout(row)

        c = self.c
        self.setStyleSheet(
            f"""
            QLabel#hintTitle {{ color: {c['text']}; font-size: 10.5pt; font-weight: 600; }}
            QLabel#hintBody  {{ color: {c['text_sub']}; font-size: 9.5pt; }}
            QPushButton#hintPrimary {{
                background: {c['accent']}; color: {c['accent_text']};
                border: none; border-radius: 7px; padding: 5px 12px; font-size: 9.5pt;
            }}
            QPushButton#hintGhost {{
                background: transparent; color: {c['text_sub']};
                border: 1px solid {c['border']}; border-radius: 7px;
                padding: 5px 12px; font-size: 9.5pt;
            }}
            QPushButton#hintGhost:hover {{ background: {c['bg_hover']}; color: {c['text']}; }}
            """
        )

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.fillPath(path, QColor(self.c["bg"]))
        p.setPen(QColor(self.c["border"]))
        p.drawPath(path)
        p.end()

    def _on_settings(self) -> None:
        self.close()
        self.settings_requested.emit()

    # ------------------------------------------------------------------
    def show_near_tray(self) -> None:
        """贴在任务栏右下角上方。"""
        self.adjustSize()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = geo.right() - self.width() - 12
            y = geo.bottom() - self.height() - 12
            self.move(x, y)
        self.show()
        self.raise_()
