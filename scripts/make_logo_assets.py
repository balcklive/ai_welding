"""一次性脚本：把 data/logo.png 加工成前端 logo 资源。

产物（public/）：
- logo.png      完整图（含"三维互联"文字），黑底转透明
- logo-mark.png 只裁圆形图标（去掉文字），方形 256x256，黑底转透明，作 favicon / 侧边栏
用法：uv run --with pillow python scripts/make_logo_assets.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "logo.png"
OUT = ROOT / "public"
OUT.mkdir(exist_ok=True)


def black_to_transparent(img: Image.Image) -> Image.Image:
    """近黑像素转透明（按最大通道亮度做 alpha），保留彩色与白色文字。"""
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            lum = max(r, g, b)
            if lum <= 18:
                px[x, y] = (r, g, b, 0)
            elif lum < 70:  # 边缘半透明过渡，防白边/硬边
                px[x, y] = (r, g, b, int((lum - 18) / (70 - 18) * 255))
    return img


def colored_bbox(img: Image.Image):
    """彩色像素（通道差异明显）的外接框——用于定位圆形图标、排除白色文字。"""
    px = img.convert("RGB").load()
    w, h = img.size
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if max(r, g, b) - min(r, g, b) > 40:
                xs.append(x)
                ys.append(y)
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


full = Image.open(SRC)

# 完整 logo
black_to_transparent(full).save(OUT / "logo.png")

# 圆形图标：裁彩色外接框 → 补成正方形 → 缩到 256
l, t, r, b = colored_bbox(full)
side = max(r - l, b - t)
cx, cy = (l + r) // 2, (t + b) // 2
half = side // 2 + 6  # 留 6px 边距
box = (cx - half, cy - half, cx + half, cy + half)
mark = full.crop(box)
side = mark.size[0]
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(mark, (0, 0))
black_to_transparent(square.resize((256, 256), Image.LANCZOS)).save(OUT / "logo-mark.png")
print("bbox:", (l, t, r, b), "->", OUT / "logo.png", OUT / "logo-mark.png")
