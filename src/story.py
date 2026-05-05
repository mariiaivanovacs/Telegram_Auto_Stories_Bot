import logging
import random
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

STORY_W = 1080
STORY_H = 1920

_BG_EXTS = {".jpg", ".jpeg", ".png"}


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_stories(
    price_results: list[dict],
    story_cfg,
    output_dir: str = "output/stories",
    backgrounds_dir: str = "backgrounds",
    date_str: str | None = None,
) -> list[str]:
    """
    Generate 3 story images from background templates.

    Args:
        price_results:   output of pricing.calculate_prices() — needs category, display_name
        story_cfg:       StorySettings dataclass from config
        output_dir:      where to save PNGs
        backgrounds_dir: folder containing background images
        date_str:        YYYYMMDD string for filename (defaults to today)

    Returns:
        list of absolute paths to the 3 generated PNG files
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    backgrounds = _pick_backgrounds(backgrounds_dir, story_cfg.background_selection)
    lines = _build_lines(price_results)

    paths: list[str] = []
    for i, bg_path in enumerate(backgrounds, start=1):
        out_path = Path(output_dir) / f"story_{i}_{date_str}.png"
        try:
            _render(bg_path, lines, story_cfg, out_path)
            paths.append(str(out_path))
            logger.info("Story %d saved: %s", i, out_path)
        except Exception as e:
            logger.error("Story %d failed: %s", i, e, exc_info=True)

    if not paths:
        raise RuntimeError("All 3 story renders failed — check logs")
    return paths


# ── Background selection ───────────────────────────────────────────────────────

def _pick_backgrounds(dir_path: str, selection: str) -> list[str]:
    files = sorted(
        str(f) for f in Path(dir_path).iterdir() if f.suffix.lower() in _BG_EXTS
    )
    if not files:
        raise FileNotFoundError(f"No background images in {dir_path}/")

    if selection == "random":
        if len(files) >= 3:
            return random.sample(files, 3)
        return [random.choice(files) for _ in range(3)]

    # sequential
    return [files[i % len(files)] for i in range(3)]


# ── Per-image render ───────────────────────────────────────────────────────────

def _render(bg_path: str, lines: list[dict], cfg, out_path: Path) -> None:
    img = Image.open(bg_path).convert("RGB")
    img = _resize_crop(img, STORY_W, STORY_H)
    img = img.filter(ImageFilter.GaussianBlur(radius=cfg.blur_radius))

    overlay = Image.new("RGBA", (STORY_W, STORY_H), (0, 0, 0, cfg.darken_alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    img = _draw_content(img, lines, cfg)
    img.convert("RGB").save(out_path, "PNG", optimize=True)


def _resize_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    ow, oh = img.size
    scale = max(w / ow, h / oh)
    nw, nh = int(ow * scale), int(oh * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


# ── Content drawing ────────────────────────────────────────────────────────────

def _draw_content(img: Image.Image, lines: list[dict], cfg) -> Image.Image:
    fs_title = cfg.font_size_title
    fs_body = cfg.font_size_body
    fs_price = cfg.font_size_price
    lh = cfg.line_height

    font_title = _font(cfg.font_path, fs_title)
    font_body = _font(cfg.font_path, fs_body)
    font_price = _font(cfg.font_path, fs_price)

    line_heights = {
        "header":   int(fs_title * lh),
        "category": int(fs_body  * lh),
        "price":    int(fs_price * lh),
        "footer":   int(fs_body  * lh),
        "spacer":   int(fs_body  * lh // 2),
    }

    total_h = sum(line_heights.get(ln["type"], 0) for ln in lines)
    panel_w = STORY_W - 2 * cfg.padding_x
    panel_h = total_h + 2 * cfg.padding_y
    px0 = cfg.padding_x
    py0 = (STORY_H - panel_h) // 2
    px1 = STORY_W - cfg.padding_x
    py1 = py0 + panel_h

    # Guard: panel must fit inside canvas
    if py0 < 40:
        py0 = 40
        py1 = py0 + panel_h

    # Draw semi-transparent panel
    panel_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel_layer)
    panel_color = tuple(cfg.panel_color) if not isinstance(cfg.panel_color, tuple) else cfg.panel_color
    _rounded_rect(pd, (px0, py0, px1, py1), cfg.panel_corner_radius, panel_color)
    img = Image.alpha_composite(img, panel_layer)

    draw = ImageDraw.Draw(img)
    text_x = px0 + cfg.padding_x // 2
    y = py0 + cfg.padding_y

    for ln in lines:
        ltype = ln["type"]
        text = ln["text"]

        if ltype == "spacer" or not text:
            y += line_heights.get("spacer", 20)
            continue

        font, color = _style(ltype, font_title, font_body, font_price, cfg.accent_color)

        # Measure and shrink text that overflows the panel
        max_w = panel_w - cfg.padding_x
        actual_w = _text_width(draw, text, font)
        if actual_w > max_w and actual_w > 0:
            ratio = max_w / actual_w
            shrunk_size = max(14, int(_font_size(font) * ratio))
            font = _font(cfg.font_path, shrunk_size)

        # 1-px drop shadow
        draw.text((text_x + 1, y + 1), text, font=font, fill=(0, 0, 0, 150))
        draw.text((text_x, y), text, font=font, fill=color)

        y += line_heights.get(ltype, int(fs_body * lh))

    return img


def _style(ltype: str, ft, fb, fp, accent: str):
    if ltype == "header":
        return ft, "#FFFFFF"
    if ltype == "category":
        return fb, accent
    if ltype == "price":
        return fp, "#FFFFFF"
    return fb, "#CCCCCC"  # footer


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default(size=size)


def _font_size(font) -> int:
    try:
        return font.size
    except AttributeError:
        return 16


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        return 0


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, r: int, fill) -> None:
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.ellipse([x0, y0, x0 + 2 * r, y0 + 2 * r], fill=fill)
    draw.ellipse([x1 - 2 * r, y0, x1, y0 + 2 * r], fill=fill)
    draw.ellipse([x0, y1 - 2 * r, x0 + 2 * r, y1], fill=fill)
    draw.ellipse([x1 - 2 * r, y1 - 2 * r, x1, y1], fill=fill)


# ── Price lines builder ────────────────────────────────────────────────────────

def _build_lines(price_results: list[dict]) -> list[dict]:
    lines: list[dict] = [
        {"type": "header", "text": "Any tech in stock at a great price"},
        {"type": "spacer", "text": ""},
    ]

    # Group by category, preserving original order
    seen_cats: list[str] = []
    by_cat: dict[str, list[dict]] = {}
    for r in price_results:
        cat = r.get("category", "Other")
        if cat not in by_cat:
            seen_cats.append(cat)
            by_cat[cat] = []
        by_cat[cat].append(r)

    for cat in seen_cats:
        lines.append({"type": "category", "text": cat})
        for r in by_cat[cat]:
            name = r.get("display_name") or r.get("canonical_name", "")
            price = r.get("calculated_price")
            price_str = f"{price:,}".replace(",", " ") + " RUB" if price is not None else "—"
            lines.append({"type": "price", "text": f"• {name} — {price_str}"})
        lines.append({"type": "spacer", "text": ""})

    lines += [
        {"type": "footer", "text": "Original items, limited stock"},
        {"type": "footer", "text": "Moscow delivery in 2 hours"},
        {"type": "footer", "text": "Order: @svyat_001"},
    ]
    return lines
