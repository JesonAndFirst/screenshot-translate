"""RapidOCR（onnxruntime 后端）封装。

性能取舍（实测 i5-9400，1100×240 选区）：
  * 默认配置 limit_type=min/736 会把宽图放大到 3000+ 像素宽，检测耗时 ~2.4s；
    改成 max/2048 + 自己控制预缩放后降到 ~0.6s。
  * onnxruntime 线程数 6 → 3，反而更快（小模型线程竞争严重）。
  * 小图放大到长边 ~1600 再识别，小字号界面文字的召回明显更好。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from app.config import APP_DIR, resource_dir
from app.ocr.base import OcrError, OcrLine, OcrResult

TARGET_SIDE = 1600     # 检测网络的输入长边（同时也是小图放大的上限）
DET_LIMIT = TARGET_SIDE


def model_dir() -> Path:
    """优先用随 exe 打包的模型（离线可用），否则用用户目录（首次自动下载）。"""
    bundled = resource_dir() / "models"
    try:
        if bundled.is_dir() and any(bundled.glob("*.onnx")):
            return bundled
    except Exception:
        pass
    return APP_DIR / "models"


def qimage_to_bgr(image: QImage) -> np.ndarray:
    """QImage → HxWx3 的 BGR ndarray（RapidOCR/OpenCV 约定）。"""
    img = image.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        raise OcrError("图像为空")
    buf = bytes(img.constBits())
    arr = np.frombuffer(buf, dtype=np.uint8)
    expected = img.sizeInBytes()
    if arr.size < expected:
        raise OcrError("图像数据不完整")
    arr = arr[:expected].reshape(h, img.bytesPerLine())[:, : w * 3].reshape(h, w, 3)
    return np.ascontiguousarray(arr[:, :, ::-1])


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.RLock()
        self._init_error: str | None = None

    # ------------------------------------------------------------------
    def _ensure(self):
        with self._lock:
            if self._engine is not None:
                return self._engine
            if self._init_error:
                raise OcrError(self._init_error)
            try:
                from rapidocr import RapidOCR
            except Exception as exc:  # pragma: no cover - 依赖缺失
                self._init_error = (
                    "未安装 OCR 引擎 rapidocr。\n请执行：pip install rapidocr onnxruntime"
                )
                raise OcrError(self._init_error) from exc

            models = model_dir()
            try:
                models.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            params = {
                "Global.log_level": "error",
                "Global.model_root_dir": str(models),
                "Det.limit_type": "max",
                "Det.limit_side_len": DET_LIMIT,
                # 关键：默认 batch=6 时，同批次里最长的那行会把整批 padding 到它的宽度，
                # 一条长句就能把 6 行识别拖到 1.2s；改成 1 行一算实测快 2.5 倍。
                "Rec.rec_batch_num": 1,
                "EngineConfig.onnxruntime.intra_op_num_threads": 3,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
            try:
                self._engine = RapidOCR(params=params)
            except Exception as exc:
                self._init_error = f"OCR 引擎初始化失败：{exc}"
                raise OcrError(self._init_error) from exc
            return self._engine

    def warmup(self) -> None:
        """后台预热：加载模型 + 跑一次空图，避免首次截图卡 2–3 秒。"""
        try:
            img = QImage(320, 120, QImage.Format.Format_RGB32)
            img.fill(0xFFFFFFFF)
            self.recognize(img)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def recognize(self, image: QImage) -> OcrResult:
        t0 = time.perf_counter()
        # 尺寸归一化交给检测网络自己做（limit_type=max / 1600），
        # 它返回的坐标已经映射回原图，不需要再换算。
        result = self._run(image, scale=1.0)
        result.elapsed = time.perf_counter() - t0
        result.engine = self.name
        return result

    def _run(self, image: QImage, scale: float) -> OcrResult:
        engine = self._ensure()
        arr = qimage_to_bgr(image)
        with self._lock:
            raw = engine(arr)
        return self._parse(raw, scale)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse(raw, scale: float) -> OcrResult:
        out = OcrResult()
        if raw is None:
            return out

        boxes = getattr(raw, "boxes", None)
        txts = getattr(raw, "txts", None)
        scores = getattr(raw, "scores", None)

        # 兼容 v2 的 (list[[box, text, score]], elapse) 返回
        if txts is None and isinstance(raw, tuple) and raw:
            for item in raw[0] or []:
                try:
                    pts = list(item[0])
                    text = str(item[1])
                    score = float(item[2])
                except Exception:
                    continue
                if not text.strip():
                    continue
                xs = [float(p[0]) for p in pts]
                ys = [float(p[1]) for p in pts]
                out.lines.append(
                    OcrLine(text, min(xs) * scale, min(ys) * scale,
                            max(xs) * scale, max(ys) * scale, score)
                )
            return out

        if boxes is None or txts is None:
            return out

        for i, text in enumerate(list(txts)):
            try:
                pts = list(boxes[i])
                xs = [float(p[0]) for p in pts]
                ys = [float(p[1]) for p in pts]
                score = float(scores[i]) if scores is not None else 0.0
            except Exception:
                continue
            if not str(text).strip():
                continue
            out.lines.append(
                OcrLine(str(text), min(xs) * scale, min(ys) * scale,
                        max(xs) * scale, max(ys) * scale, score)
            )
        return out
