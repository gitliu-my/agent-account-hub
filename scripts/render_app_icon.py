from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"
ICONSET_DIR = ASSETS_DIR / "AgentAccountHub.iconset"
MASTER_PNG = ASSETS_DIR / "AgentAccountHub.png"
ICNS_PATH = ASSETS_DIR / "AgentAccountHub.icns"


def hex_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4)) + (alpha,)


def diagonal_gradient(size: tuple[int, int], start: str, end: str) -> Image.Image:
    width, height = size
    gradient_x = Image.linear_gradient("L").resize((width, height))
    gradient_y = ImageOps.flip(Image.linear_gradient("L").rotate(90, expand=True).resize((width, height)))
    mask = Image.blend(gradient_x, gradient_y, 0.5)
    low = Image.new("RGBA", size, hex_rgba(start))
    high = Image.new("RGBA", size, hex_rgba(end))
    return Image.composite(high, low, mask)


def rounded_rect_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def add_shadow(
    base: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    offset: tuple[int, int],
    color: tuple[int, int, int, int],
    blur: int,
) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    x0, y0, x1, y1 = box
    ox, oy = offset
    draw.rounded_rectangle((x0 + ox, y0 + oy, x1 + ox, y1 + oy), radius=radius, fill=color)
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow)


def add_orbital_glow(base: Image.Image, center: tuple[int, int], color: str, radius: int, alpha: int) -> None:
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx, cy = center
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=hex_rgba(color, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius // 2))
    base.alpha_composite(glow)


def draw_chip(
    base: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    fill: str,
    outline_alpha: int,
) -> None:
    add_shadow(base, box, radius, (0, 12), (8, 16, 28, 48), 20)
    chip = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(chip)
    draw.rounded_rectangle(box, radius=radius, fill=hex_rgba(fill), outline=(255, 255, 255, outline_alpha), width=3)

    x0, y0, x1, y1 = box
    draw.ellipse((x0 + 24, y0 + 28, x0 + 48, y0 + 52), fill=(255, 255, 255, 238))
    draw.rounded_rectangle((x0 + 60, y0 + 28, x0 + 118, y0 + 40), radius=6, fill=(255, 255, 255, 232))
    draw.rounded_rectangle((x0 + 60, y0 + 49, x0 + 100, y0 + 59), radius=5, fill=(255, 255, 255, 120))
    base.alpha_composite(chip)


def build_master_icon(size: int = 1024) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    shell = diagonal_gradient((880, 880), "#F6FAFF", "#DCE7F6")
    shell_mask = rounded_rect_mask((880, 880), 204)
    canvas.paste(shell, (72, 72), shell_mask)

    shell_overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(shell_overlay)
    overlay_draw.rounded_rectangle((72, 72, 952, 952), radius=204, outline=(255, 255, 255, 172), width=4)
    canvas.alpha_composite(shell_overlay)

    add_orbital_glow(canvas, (268, 290), "#FFB255", 250, 44)
    add_orbital_glow(canvas, (766, 748), "#8EAEF6", 250, 42)

    add_shadow(canvas, (274, 274, 750, 750), 238, (0, 26), (16, 26, 40, 72), 34)

    hub = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    hub_draw = ImageDraw.Draw(hub)
    hub_draw.ellipse((274, 274, 750, 750), fill=hex_rgba("#101723"), outline=(255, 255, 255, 18), width=4)
    hub_draw.ellipse((394, 394, 630, 630), fill=hex_rgba("#162133"), outline=(255, 255, 255, 28), width=4)
    canvas.alpha_composite(hub)

    arc_glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    arc_glow_draw = ImageDraw.Draw(arc_glow)
    arc_glow_draw.arc((342, 342, 682, 682), start=180, end=270, fill=hex_rgba("#FF9845", 118), width=86)
    arc_glow_draw.arc((342, 342, 682, 682), start=0, end=90, fill=hex_rgba("#7DA4F2", 112), width=86)
    arc_glow = arc_glow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(arc_glow)

    arcs = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    arc_draw = ImageDraw.Draw(arcs)
    arc_draw.arc((342, 342, 682, 682), start=180, end=270, fill=hex_rgba("#FF8D3F"), width=52)
    arc_draw.arc((342, 342, 682, 682), start=270, end=360, fill=(255, 255, 255, 28), width=52)
    arc_draw.arc((342, 342, 682, 682), start=0, end=90, fill=hex_rgba("#6E93E8"), width=52)
    arc_draw.arc((342, 342, 682, 682), start=90, end=180, fill=(255, 255, 255, 28), width=52)
    canvas.alpha_composite(arcs)

    core = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    core_draw = ImageDraw.Draw(core)
    core_draw.ellipse((450, 488, 498, 536), fill=hex_rgba("#FF9145"))
    core_draw.ellipse((526, 488, 574, 536), fill=hex_rgba("#769BED"))
    core_draw.rounded_rectangle((492, 504, 532, 520), radius=8, fill=(255, 255, 255, 240))
    core_draw.ellipse((498, 418, 526, 446), fill=(255, 255, 255, 238))
    core_draw.rounded_rectangle((505, 442, 519, 487), radius=7, fill=(255, 255, 255, 230))
    canvas.alpha_composite(core)

    draw_chip(canvas, (182, 360, 302, 448), 30, "#FF9647", 82)
    draw_chip(canvas, (722, 578, 842, 666), 30, "#6F89C0", 72)

    sheen = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sheen_draw = ImageDraw.Draw(sheen)
    sheen_draw.rounded_rectangle((72, 72, 952, 952), radius=204, fill=(255, 255, 255, 0))
    sheen_mask = Image.new("L", canvas.size, 0)
    sheen_mask_draw = ImageDraw.Draw(sheen_mask)
    sheen_mask_draw.rounded_rectangle((72, 72, 952, 952), radius=204, fill=255)
    band = diagonal_gradient(canvas.size, "#FFFFFF", "#E5EEF8")
    band.putalpha(ImageChops.multiply(sheen_mask, Image.new("L", canvas.size, 42)))
    band = band.filter(ImageFilter.GaussianBlur(26))
    canvas.alpha_composite(band)

    return canvas


def build_assets() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)

    master = build_master_icon(1024)
    master.save(MASTER_PNG)

    icon_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, target_size in icon_sizes.items():
        resized = master.resize((target_size, target_size), Image.Resampling.LANCZOS)
        resized.save(ICONSET_DIR / name)

    master.save(ICNS_PATH)


if __name__ == "__main__":
    build_assets()
