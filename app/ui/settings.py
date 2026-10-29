"""设置对话框。"""

from __future__ import annotations

import copy
import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import Config
from app.mt.base import TranslationError
from app.mt.llm import LlmTranslator
from app.ui import theme as theme_mod
from app.win32.hotkey import HotkeyError, parse_hotkey

log = logging.getLogger(__name__)

LANGUAGES = ["中文", "English", "日本語", "한국어", "Français", "Deutsch", "Русский"]


class _TestThread(QThread):
    ok = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:
        try:
            text = LlmTranslator(self.cfg).translate(
                "Save changes before closing?", self.cfg.target_lang
            )
            self.ok.emit(text)
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            self.failed.emit(f"测试失败：{exc}")


class SettingsDialog(QDialog):
    saved = Signal()
    quit_requested = Signal()

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._test_thread: _TestThread | None = None
        self.setWindowTitle("截屏翻译 · 设置")
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        # 后台程序弹窗可能被前台窗口盖住，置顶保证用户一定看得到
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._build()
        self._load()
        self._apply_style()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.hotkey_edit = QKeySequenceEdit(QKeySequence("Alt+Q"))
        self.hotkey_edit.setMaximumSequenceLength(1)
        form.addRow("截图热键", self.hotkey_edit)

        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("https://api.deepseek.com/v1")
        form.addRow("API 地址", self.base_edit)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-…")
        form.addRow("API Key", self.key_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("deepseek-chat")
        form.addRow("模型", self.model_edit)

        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        self.lang_combo.addItems(LANGUAGES)
        form.addRow("翻译为", self.lang_combo)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", "auto")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        form.addRow("主题", self.theme_combo)

        self.autostart_check = QCheckBox("开机自动启动")
        form.addRow("", self.autostart_check)

        root.addLayout(form)

        self.hint = QLabel(
            "程序在托盘后台运行：按 Alt+Q 截图。若任务栏右下角看不到「译」图标，"
            "点 ^ 展开后把它拖到任务栏；找不到图标时，再双击一次 exe 也能打开本窗口。"
        )
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(20)
        root.addWidget(self.status)

        bottom = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._on_test)
        bottom.addWidget(self.test_btn)

        self.quit_btn = QPushButton("退出程序")
        self.quit_btn.setToolTip("没有托盘图标时，可以从这里退出")
        self.quit_btn.clicked.connect(self._on_quit)
        bottom.addWidget(self.quit_btn)
        bottom.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    def _apply_style(self) -> None:
        c = theme_mod.resolve(self.cfg.theme)
        self.setStyleSheet(
            f"""
            QDialog {{ background: {c['bg']}; }}
            QLabel {{ color: {c['text']}; font-size: 10pt; }}
            QLineEdit, QComboBox, QKeySequenceEdit {{
                background: {c['bg_soft']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 5px 8px; font-size: 10pt; min-height: 18px;
            }}
            QLineEdit:focus, QComboBox:focus, QKeySequenceEdit:focus {{
                border: 1px solid {c['accent']};
            }}
            QComboBox QAbstractItemView {{
                background: {c['bg_soft']}; color: {c['text']};
                selection-background-color: {c['accent']};
            }}
            QCheckBox {{ color: {c['text']}; font-size: 10pt; }}
            QLabel#hint {{ color: {c['text_sub']}; font-size: 9pt; }}
            QPushButton {{
                background: {c['bg_soft']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 6px 16px; font-size: 10pt;
            }}
            QPushButton:hover {{ background: {c['bg_hover']}; }}
            QPushButton:default {{
                background: {c['accent']}; color: {c['accent_text']}; border: none;
            }}
            """
        )

    # ------------------------------------------------------------------
    def _load(self) -> None:
        cfg = self.cfg
        self.hotkey_edit.setKeySequence(QKeySequence(cfg.hotkey))
        self.base_edit.setText(cfg.api_base)
        self.key_edit.setText(cfg.api_key)
        self.model_edit.setText(cfg.model)
        idx = self.lang_combo.findText(cfg.target_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        else:
            self.lang_combo.setCurrentText(cfg.target_lang)
        ti = self.theme_combo.findData(cfg.theme)
        self.theme_combo.setCurrentIndex(max(0, ti))
        self.autostart_check.setChecked(cfg.autostart)

    def _collect(self) -> Config:
        cfg = copy.copy(self.cfg)
        seq = self.hotkey_edit.keySequence().toString()
        cfg.hotkey = seq or self.cfg.hotkey
        cfg.api_base = self.base_edit.text().strip()
        cfg.api_key = self.key_edit.text().strip()
        cfg.model = self.model_edit.text().strip()
        cfg.target_lang = self.lang_combo.currentText().strip() or "中文"
        cfg.theme = self.theme_combo.currentData()
        cfg.autostart = self.autostart_check.isChecked()
        return cfg

    def _validate(self, cfg: Config) -> str | None:
        try:
            mods, _ = parse_hotkey(cfg.hotkey)
        except HotkeyError as exc:
            return f"热键无效：{exc}"
        if not (mods & 0x0F):
            return "热键必须带 Ctrl / Alt / Shift 修饰键"
        if not cfg.api_base:
            return "请填写 API 地址"
        if not cfg.model:
            return "请填写模型名"
        return None

    def _on_save(self) -> None:
        cfg = self._collect()
        err = self._validate(cfg)
        if err:
            self._show_status(err, error=True)
            return

        for field in ("hotkey", "api_base", "api_key", "model", "target_lang", "theme", "autostart"):
            setattr(self.cfg, field, getattr(cfg, field))
        if not self.cfg.save():
            self._show_status("配置保存失败，请检查目录权限", error=True)
            return
        self.saved.emit()
        self.accept()

    def _on_quit(self) -> None:
        self.quit_requested.emit()

    def _on_test(self) -> None:
        cfg = self._collect()
        err = self._validate(cfg)
        if err:
            self._show_status(err, error=True)
            return
        if not cfg.api_key:
            self._show_status("请先填写 API Key", error=True)
            return

        self.test_btn.setEnabled(False)
        self._show_status("正在测试…")
        self._test_thread = _TestThread(cfg)
        self._test_thread.ok.connect(self._on_test_ok)
        self._test_thread.failed.connect(self._on_test_failed)
        self._test_thread.finished.connect(lambda: self.test_btn.setEnabled(True))
        self._test_thread.start()

    def _on_test_ok(self, text: str) -> None:
        self._show_status(f"连接正常，返回示例：{text[:60]}", error=False)

    def _on_test_failed(self, message: str) -> None:
        self._show_status(message, error=True)

    def _show_status(self, text: str, error: bool = False) -> None:
        c = theme_mod.resolve(self.cfg.theme)
        self.status.setStyleSheet(f"color: {c['error'] if error else c['text_sub']};")
        self.status.setText(text)

    def closeEvent(self, e) -> None:  # noqa: N802
        if self._test_thread is not None and self._test_thread.isRunning():
            self._test_thread.quit()
            self._test_thread.wait(1500)
        super().closeEvent(e)
