"""结果悬浮卡片。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.geometry import to_logical_rect
from app.ui import theme as theme_mod
from app.win32.monitors import Monitor
from app.win32.winutils import exclude_from_capture

log = logging.getLogger(__name__)


class ResultCard(QWidget):
    copy_requested = Signal()
    retry_requested = Signal()
    closed = Signal()

    def __init__(self, theme: str = "auto", width: int = 440) -> None:
        super().__init__(None)
        self._theme_name = theme
        self.c = theme_mod.resolve(theme)
        self._drag_from: QPoint | None = None
        self._has_translation = False
        self._anchor: tuple[QRect, Monitor] | None = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFixedWidth(int(width))

        self._build()
        self._apply_style()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        # 标题栏
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setObjectName("dot")
        self._title = QLabel("截屏翻译")
        self._title.setObjectName("title")
        title_row.addWidget(self._dot)
        title_row.addWidget(self._title)
        title_row.addStretch(1)
        self._close_btn = QToolButton()
        self._close_btn.setText("✕")
        self._close_btn.setObjectName("close")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._on_close)
        title_row.addWidget(self._close_btn)
        outer.addLayout(title_row)

        # 缩略图
        self._thumb = QLabel()
        self._thumb.setObjectName("thumb")
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._thumb.setFixedHeight(0)
        outer.addWidget(self._thumb)

        # 原文
        self._source = QLabel()
        self._source.setObjectName("source")
        self._source.setWordWrap(True)
        self._source.setTextFormat(Qt.TextFormat.PlainText)
        self._source.setVisible(False)
        outer.addWidget(self._source)

        self._sep = QFrame()
        self._sep.setObjectName("sep")
        self._sep.setFrameShape(QFrame.Shape.NoFrame)
        self._sep.setFixedHeight(1)
        self._sep.setVisible(False)
        outer.addWidget(self._sep)

        # 译文
        self._target = QLabel()
        self._target.setObjectName("target")
        self._target.setWordWrap(True)
        self._target.setTextFormat(Qt.TextFormat.PlainText)
        self._target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._target.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._target)
        self._scroll.setVisible(False)
        outer.addWidget(self._scroll)

        # 底部
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._copy_btn = QPushButton("复制译文")
        self._copy_btn.setObjectName("primary")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self.copy_requested)
        self._retry_btn = QPushButton("重译")
        self._retry_btn.setObjectName("ghost")
        self._retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry_btn.clicked.connect(self.retry_requested)
        self._status = QLabel("")
        self._status.setObjectName("status")
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self._copy_btn)
        bottom.addWidget(self._retry_btn)
        bottom.addStretch(1)
        bottom.addWidget(self._status)
        outer.addLayout(bottom)

        self._copy_btn.setVisible(False)
        self._retry_btn.setVisible(False)

    # ------------------------------------------------------------------
    def _apply_style(self) -> None:
        c = self.c
        self.setStyleSheet(
            f"""
            QLabel#title {{ color: {c['text_sub']}; font-size: 10pt; }}
            QLabel#dot   {{ color: {c['accent']}; font-size: 8pt; }}
            QLabel#source {{ color: {c['text_sub']}; font-size: 10pt; }}
            QLabel#target {{ color: {c['text']}; font-size: 11pt; }}
            QLabel#status {{ color: {c['text_sub']}; font-size: 9pt; }}
            QLabel#thumb  {{ background: {c['thumb_bg']}; border-radius: 8px; }}
            QFrame#sep {{ background: {c['border']}; border: none; }}
            QToolButton#close {{
                color: {c['text_sub']}; background: transparent; border: none;
                font-size: 11pt; padding: 2px 4px; border-radius: 6px;
            }}
            QToolButton#close:hover {{ background: {c['bg_hover']}; color: {c['text']}; }}
            QPushButton#primary {{
                background: {c['accent']}; color: {c['accent_text']};
                border: none; border-radius: 8px; padding: 6px 14px; font-size: 10pt;
            }}
            QPushButton#primary:hover {{ background: {c['accent']}; }}
            QPushButton#ghost {{
                background: transparent; color: {c['text_sub']};
                border: 1px solid {c['border']}; border-radius: 8px;
                padding: 5px 12px; font-size: 10pt;
            }}
            QPushButton#ghost:hover {{ background: {c['bg_hover']}; color: {c['text']}; }}
            QScrollArea#scroll {{ background: transparent; border: none; }}
            QScrollArea#scroll > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {c['border']}; border-radius: 4px; min-height: 24px;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
            """
        )

    def apply_theme(self, theme: str) -> None:
        self._theme_name = theme
        self.c = theme_mod.resolve(theme)
        self._apply_style()
        self.update()

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

    # ------------------------------------------------------------------
    def present(self, sel_phys: QRect, mon: Monitor) -> None:
        self._thumb.setFixedHeight(0)
        self._thumb.clear()
        self._source.setVisible(False)
        self._sep.setVisible(False)
        self._scroll.setVisible(False)
        self._copy_btn.setVisible(False)
        self._retry_btn.setVisible(False)
        self._status.setText("")
        self._has_translation = False
        self._anchor = (sel_phys, mon)

        self._target.setText("")
        self._target.setVisible(True)
        self.set_status("识别中…")

        self._relayout()
        self.show()
        self.raise_()
        try:
            exclude_from_capture(int(self.winId()))
        except Exception:
            pass

    def _relayout(self) -> None:
        """按内容重算高度，并重新贴到选区旁边（内容可能让卡片长高）。"""
        lay = self.layout()
        if lay is not None:
            lay.activate()
            h = max(lay.sizeHint().height(), lay.minimumSize().height())
            self.setFixedHeight(int(h))
        if self._anchor is not None:
            self._place(*self._anchor)

    def _place(self, sel_phys: QRect, mon: Monitor) -> None:
        if mon.screen is None:
            self.move(40, 40)
            return
        avail = mon.screen.availableGeometry()
        sel = to_logical_rect(sel_phys, mon)
        w, h = self.width(), self.height()
        margin = 12

        x = sel.right() + margin
        if x + w > avail.right() - 6:
            x = sel.left() - w - margin
        if x < avail.left() + 6:
            x = avail.left() + 6

        y = sel.bottom() + margin
        if y + h > avail.bottom() - 6:
            y = sel.top() - h - margin
        if y < avail.top() + 6:
            y = avail.top() + 6
        # 太高时贴着屏幕底边，别让按钮跑到屏幕外
        if y + h > avail.bottom() - 6:
            y = max(avail.top() + 6, avail.bottom() - h - 6)

        self.move(int(x), int(y))

    # ------------------------------------------------------------------
    def set_status(self, text: str, error: bool = False) -> None:
        self._status.setText(text)
        color = self.c["error"] if error else self.c["text_sub"]
        self._status.setStyleSheet(f"color: {color};")

    def set_thumbnail(self, pix: QPixmap) -> None:
        if pix.isNull():
            return
        max_w = self.width() - 32
        max_h = 120
        scaled = pix.scaled(
            max_w, max_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb.setPixmap(scaled)
        self._thumb.setFixedHeight(scaled.height())
        self._thumb.setVisible(True)
        self._relayout()

    def set_source(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        shown = text if len(text) <= 240 else text[:240].rstrip() + "…"
        self._source.setText(shown)
        self._source.setVisible(True)
        self._sep.setVisible(True)
        self._relayout()

    def set_translation(self, text: str) -> None:
        self._target.setText(text.strip())
        self._has_translation = True
        self._show_target()
        self._copy_btn.setVisible(True)
        self._retry_btn.setVisible(True)
        self.set_status("")
        self._relayout()

    def set_error(self, message: str) -> None:
        self._target.setText(message)
        self._has_translation = False
        self._target.setVisible(True)
        self._scroll.setVisible(False)
        self._copy_btn.setVisible(False)
        self._retry_btn.setVisible(True)
        self.set_status("失败", error=True)
        self._relayout()

    def _show_target(self) -> None:
        """译文放进滚动区，高度按内容自适应，最多占屏幕 45%。"""
        self._target.setVisible(True)
        self._scroll.setVisible(True)
        inner_w = max(120, self.width() - 40)
        content_h = self._target.heightForWidth(inner_w)
        if content_h <= 0:
            content_h = self._target.sizeHint().height()
        screen = self.screen()
        avail_h = screen.availableGeometry().height() if screen else 800
        max_h = int(avail_h * 0.45)
        self._scroll.setFixedHeight(int(min(max(content_h, 28), max_h)))

    # ------------------------------------------------------------------
    def closeEvent(self, e) -> None:  # noqa: N802
        e.ignore()
        self.hide()

    def _on_close(self) -> None:
        self.hide()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            e.accept()
            return
        if e.key() == Qt.Key.Key_C and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._has_translation:
                self.copy_requested.emit()
                e.accept()
                return
        super().keyPressEvent(e)

    # ---- 拖动 ----
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_from is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_from)
            e.accept()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag_from = None
        e.accept()
