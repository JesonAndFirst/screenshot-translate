"""OCR + 翻译流水线（跑在 QThreadPool 里，绝不阻塞 UI 线程）。"""

from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from app.core.grouping import blocks_to_text, lines_to_blocks
from app.ocr.base import OcrEngine, OcrError
from app.ocr.rapidocr_engine import RapidOcrEngine
from app.mt.base import TranslationError, Translator

log = logging.getLogger(__name__)

CHUNK_SIZE = 3000  # 单次翻译的最大字符数


class JobSignals(QObject):
    ocr_done = Signal(int, list)      # job_id, [段落文本]
    finished = Signal(int, str)       # job_id, 译文
    failed = Signal(int, str, str)    # job_id, stage, 用户可见的错误


def _split_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for para in text.split("\n\n"):
        if cur and cur + len(para) > size:
            chunks.append("\n\n".join(buf))
            buf, cur = [], 0
        buf.append(para)
        cur += len(para) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


class TranslateJob(QRunnable):
    def __init__(
        self,
        job_id: int,
        image: QImage,
        ocr_engine: OcrEngine,
        translator: Translator,
        target_lang: str,
        is_current: Callable[[int], bool],
        signals: JobSignals,
    ) -> None:
        super().__init__()
        self.job_id = job_id
        self.image = image
        self.ocr = ocr_engine
        self.translator = translator
        self.target_lang = target_lang
        self.is_current = is_current
        self.signals = signals
        self.setAutoDelete(True)

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D401 (Qt 接口)
        t0 = time.perf_counter()
        try:
            result = self.ocr.recognize(self.image)
        except OcrError as exc:
            self.signals.failed.emit(self.job_id, "ocr", str(exc))
            return
        except Exception as exc:  # 兜底，避免线程崩溃
            log.exception("OCR 失败")
            self.signals.failed.emit(self.job_id, "ocr", f"文字识别失败：{exc}")
            return

        t_ocr = time.perf_counter() - t0
        if not self.is_current(self.job_id):
            return

        if not result.lines:
            self.signals.failed.emit(self.job_id, "ocr", "没有识别到文字，试试框大一点")
            return

        blocks = lines_to_blocks(
            [
                {"text": l.text, "x0": l.x0, "y0": l.y0, "x1": l.x1, "y1": l.y1,
                 "score": l.score}
                for l in result.lines
            ]
        )
        text = blocks_to_text(blocks).strip()
        if not text:
            self.signals.failed.emit(self.job_id, "ocr", "没有识别到文字，试试框大一点")
            return

        self.signals.ocr_done.emit(self.job_id, [b.text for b in blocks])

        t1 = time.perf_counter()
        try:
            parts = [self.translator.translate(c, self.target_lang) for c in _split_chunks(text)]
        except TranslationError as exc:
            self.signals.failed.emit(self.job_id, "translate", str(exc))
            return
        except Exception as exc:
            log.exception("翻译失败")
            self.signals.failed.emit(self.job_id, "translate", f"翻译失败：{exc}")
            return

        if not self.is_current(self.job_id):
            return

        log.info(
            "job %s 完成：OCR %.2fs / 翻译 %.2fs / %d 行 %d 字",
            self.job_id, t_ocr, time.perf_counter() - t1,
            len(result.lines), len(text),
        )
        self.signals.finished.emit(self.job_id, "\n\n".join(parts).strip())


class TranslateTextJob(QRunnable):
    """只重跑翻译（复用已经识别出来的原文）。"""

    def __init__(
        self,
        job_id: int,
        text: str,
        translator: Translator,
        target_lang: str,
        is_current: Callable[[int], bool],
        signals: JobSignals,
    ) -> None:
        super().__init__()
        self.job_id = job_id
        self.text = text
        self.translator = translator
        self.target_lang = target_lang
        self.is_current = is_current
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            parts = [
                self.translator.translate(c, self.target_lang)
                for c in _split_chunks(self.text)
            ]
        except TranslationError as exc:
            self.signals.failed.emit(self.job_id, "translate", str(exc))
            return
        except Exception as exc:
            log.exception("翻译失败")
            self.signals.failed.emit(self.job_id, "translate", f"翻译失败：{exc}")
            return

        if not self.is_current(self.job_id):
            return
        self.signals.finished.emit(self.job_id, "\n\n".join(parts).strip())
