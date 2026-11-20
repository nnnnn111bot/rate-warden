"""生成 assets/rate_warden.ico（纯 Pillow，无外部素材）。

用法：
    python assets/make_icon.py

设计：深色圆底 + 一圈脉冲环 + 中央「RW」字样。
输出 16/32/48/64/128/256 六个尺寸的多帧 .ico。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "rate_warden.ico"
SIZES = [16, 32, 48, 64, 128, 256]

BG = (18, 22, 28, 255)        # 近黑的深底
RING = (255, 122, 61, 255)    # 橙色脉冲环
FG = (240, 244, 248, 255)     # 近白的字


def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """尽量用系统字体，找不到就退回 Pillow 内置位图字体。"""
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw(size: int) -> Image.Image:
    scale = 8  # 先大画再缩小，边缘更干净
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = big * 0.06
    d.ellipse([pad, pad, big - pad, big - pad], fill=BG)

    # 脉冲环：三个同心圆环，模拟「心跳」的扩散
    cx = cy = big / 2
    for i, (r_frac, width_frac, alpha) in enumerate(
        ((0.40, 0.055, 255), (0.31, 0.038, 170), (0.23, 0.026, 110))
    ):
        r = big * r_frac
        w = max(1, int(big * width_frac))
        color = RING[:3] + (alpha,)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)

    # 中央「RW」
    text = "RW"
    font = _font(int(big * 0.30))
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(
        (cx - tw / 2 - box[0], cy - th / 2 - box[1]),
        text,
        font=font,
        fill=FG,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    try:
        frames = [_draw(s) for s in SIZES]
    except ImportError:
        print("需要 Pillow： python -m pip install --user Pillow")
        return 2

    # 关键：保存前把 base 图换成最大尺寸，确保 ico 里真的含 256x256 帧；
    # PyInstaller / Windows 资源管理器默认取最大帧作图标。
    base = frames[-1]
    base.save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[:-1],
    )
    with Image.open(OUT) as check:
        got = sorted(check.info.get("sizes", []))
    print(f"已生成 {OUT}，内含帧: {got}")
    if len(got) < len(SIZES):
        print("警告：帧数不足，请检查 Pillow 版本")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
