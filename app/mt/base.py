"""翻译引擎抽象。"""

from __future__ import annotations

from typing import Protocol


class TranslationError(Exception):
    """可直接展示给用户的翻译错误。"""


class Translator(Protocol):
    name: str

    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str: ...
