"""生成 exe 图标（蓝色圆角方块 + 译）。

用法：python packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SIZE = 256
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> int:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角底 + 轻微渐变（上浅下深）
    radius = int(SIZE * 0.22)
    for y in range(SIZE):
        t = y / SIZE
        color = (
            int(74 + (44 - 74) * t),
            int(150 + (110 - 150) * t),
            int(255 + (235 - 255) * t),
            255,
        )
        draw.line([(0, y), (SIZE, y)], fill=color)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)
    img.putalpha(mask)

    font = pick_font(int(SIZE * 0.56))
    text = "译"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((SIZE - tw) / 2 - bbox[0], (SIZE - th) / 2 - bbox[1] - SIZE * 0.02),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )

    out = HERE / "app.ico"
    img.save(
        out,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("written:", out, out.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
