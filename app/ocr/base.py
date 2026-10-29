"""OCR 抽象层。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PySide6.QtGui import QImage


@dataclass
class OcrLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 0.0


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    elapsed: float = 0.0
    engine: str = ""

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    @property
    def mean_score(self) -> float:
        if not self.lines:
            return 0.0
        return sum(l.score for l in self.lines) / len(self.lines)


class OcrEngine(Protocol):
    name: str

    def recognize(self, image: QImage) -> OcrResult: ...


class OcrError(Exception):
    pass
