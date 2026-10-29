"""把 OCR 的"行"整理成可翻译的"段落"。

OCR 输出是逐行的框；直接逐行翻译会把句子切碎、术语不一致。
这里做两件事：① 同一行的多个框按 x 拼起来；② 相邻行按对齐/间距合并成段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_UNIT_ONLY = re.compile(r"^[\d\s.,:%+\-×x/()\[\]{}<>~!?=*#@&|\\\"'`^_]+$")


@dataclass
class Box:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 0.0

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Row:
    boxes: list[Box] = field(default_factory=list)
    text: str = ""
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class Block:
    rows: list[Row]

    @property
    def text(self) -> str:
        return "\n".join(r.text for r in self.rows)

    @property
    def x0(self) -> float:
        return min(r.x0 for r in self.rows)


def _is_cjk(ch: str) -> bool:
    return bool(_CJK.match(ch))


def _join_row(boxes: list[Box]) -> str:
    boxes = sorted(boxes, key=lambda b: b.x0)
    out = boxes[0].text.strip()
    prev = boxes[0]
    for b in boxes[1:]:
        t = b.text.strip()
        if not t:
            continue
        gap = b.x0 - prev.x1
        height = min(prev.h or 1.0, b.h or 1.0)
        left_ch = out[-1] if out else ""
        right_ch = t[0] if t else ""
        if gap > 0.35 * height and not (_is_cjk(left_ch) or _is_cjk(right_ch)):
            out += " "
        elif gap > 0.9 * height:
            out += " "
        out += t
        prev = b
    return out.strip()


def build_rows(boxes: list[Box]) -> list[Row]:
    boxes = [b for b in boxes if b.text.strip()]
    if not boxes:
        return []

    rows: list[Row] = []
    for b in sorted(boxes, key=lambda b: b.cy):
        target = None
        for r in rows:
            inter = min(r.y1, b.y1) - max(r.y0, b.y0)
            min_h = min(r.h, b.h)
            if min_h > 0 and inter / min_h >= 0.5:
                target = r
                break
        if target is None:
            rows.append(Row([b], y0=b.y0, y1=b.y1, x0=b.x0, x1=b.x1))
        else:
            target.boxes.append(b)
            target.y0 = min(target.y0, b.y0)
            target.y1 = max(target.y1, b.y1)
            target.x0 = min(target.x0, b.x0)
            target.x1 = max(target.x1, b.x1)

    for r in rows:
        r.text = _join_row(r.boxes)
        if r.boxes:
            hs = sorted(b.h for b in r.boxes)
            r.y0 = min(b.y0 for b in r.boxes)
            r.y1 = max(b.y1 for b in r.boxes)

    rows = [r for r in rows if r.text]
    rows.sort(key=lambda r: (round(r.y0, 1), r.x0))
    return rows


def _overlap_ratio(a: Row, b: Row) -> float:
    inter = min(a.x1, b.x1) - max(a.x0, b.x0)
    denom = min(a.x1 - a.x0, b.x1 - b.x0) or 1.0
    return max(0.0, inter) / denom


def build_blocks(rows: list[Row]) -> list[Block]:
    blocks: list[Block] = []
    for r in rows:
        if not blocks:
            blocks.append(Block([r]))
            continue
        cur = blocks[-1]
        last = cur.rows[-1]
        h = max(last.h, r.h, 1.0)
        gap = r.y0 - last.y1
        same_size = 0.7 <= (last.h or 1) / (r.h or 1) <= 1.45
        if (
            -0.4 * h <= gap <= 1.05 * h
            and _overlap_ratio(last, r) >= 0.45
            and same_size
        ):
            cur.rows.append(r)
        else:
            blocks.append(Block([r]))
    return blocks


def lines_to_blocks(items: list[dict]) -> list[Block]:
    """items: [{'text','x0','y0','x1','y1','score'}] → 段落列表。"""
    boxes = [
        Box(
            text=str(i.get("text", "")),
            x0=float(i["x0"]), y0=float(i["y0"]),
            x1=float(i["x1"]), y1=float(i["y1"]),
            score=float(i.get("score", 0.0)),
        )
        for i in items
        if i.get("text")
    ]
    return build_blocks(build_rows(boxes))


def blocks_to_text(blocks: list[Block], sep: str = "\n\n") -> str:
    return sep.join(b.text.strip() for b in blocks if b.text.strip())
