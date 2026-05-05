import logging
import random
import re
import copy
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

logger = logging.getLogger(__name__)

STORY_W = 1080
STORY_H = 1920

_BG_EXTS = {".jpg", ".jpeg", ".png"}
_SAMPLE_TEXT_PRICE_KEYS = [
    "iphone_pro_256",
    "iphone_pro_512",
    "iphone_pro_1tb",
    "iphone_pro_max_256",
    "iphone_pro_max_512",
    "iphone_pro_max_1tb",
    "iphone_air",
    "macbook_neo",
    "airpods_pro_3",
    "whoop_50",
    "ps5",
    "apple_watch_s11",
]
_EMOJI_TEXT_REPLACEMENTS = {
    "🔥": "🔥",
    "📱": "📱",
    "💻": "💻",
    "🎧": "🎧",
    "💪": "💪",
    "🎮": "🎮",
    "⌚": "⌚",
    "⚡️": "⚡️",
    "⚡": "⚡",
    "🚚": "🚚",
    "〽️": "〽️",
    "〽": "〽",
}
_USERNAME_RE = re.compile(r'@\w[\w.]*')
_PRICE_TEXT_RE = re.compile(r'(?:\d[\d\s]*|—)\s*рублей', re.IGNORECASE)
_EMOJI_IMAGE_CACHE: dict[tuple[str, int], Image.Image | None] = {}

# ── Story design presets ───────────────────────────────────────────────────────
# Each dict supplies panel fill/outline, text colours, stroke, and spacing.
# Design 1: dark minimalist (current). Design 2: light/white panels, black text.
# Design 3: same as 2 with a different font (Avenir/serif).
_DESIGNS: dict[int, dict] = {
    1: {
        "title_panel":    (0, 0, 0, 0),
        "title_outline":  (0, 0, 0, 0),
        "card_panel":     (0, 0, 0, 115),
        "card_outline":   (255, 255, 255, 22),
        "body_text_c":    (245, 245, 245, 255),
        "header_text_c":  (200, 200, 200, 255),
        "username_text_c":(100, 190, 255, 255),
        "stroke_w":       3,
        "stroke_c":       (0, 0, 0, 210),
        "line_gap":       9,
        "pad_y":          20,
        "pad_y_title":    24,
        "font_override":  None,
        "bold_body":      False,
    },
    2: {
        "title_panel":    (255, 255, 255, 200),
        "title_outline":  (220, 220, 220, 70),
        "card_panel":     (255, 255, 255, 210),
        "card_outline":   (200, 200, 200, 60),
        "body_text_c":    (20, 20, 20, 255),
        "header_text_c":  (60, 60, 60, 255),
        "username_text_c":(30, 100, 210, 255),
        "stroke_w":       0,
        "stroke_c":       (0, 0, 0, 0),
        "line_gap":       13,
        "pad_y":          12,
        "pad_y_title":    14,
        "font_override":  None,
        "content_width":  True,   # panel hugs text width instead of spanning full row
    },
    3: {
        "title_panel":    (255, 255, 255, 200),
        "title_outline":  (220, 220, 220, 70),
        "card_panel":     (255, 255, 255, 210),
        "card_outline":   (200, 200, 200, 60),
        "body_text_c":    (20, 20, 20, 255),
        "header_text_c":  (60, 60, 60, 255),
        "username_text_c":(30, 100, 210, 255),
        "stroke_w":       0,
        "stroke_c":       (0, 0, 0, 0),
        "line_gap":       13,
        "pad_y":          12,
        "pad_y_title":    14,
        "font_override":  "avenir_or_serif",
        "content_width":  True,
    },
}


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_stories(
    price_results: list[dict],
    story_cfg,
    output_dir: str = "output/stories",
    backgrounds_dir: str = "ready_images",
    sample_text_path: str = "assets/sample_text.txt",
    date_str: str | None = None,
    design: int = 1,
) -> list[str]:
    """Generate 3 story images with 4 text sections over ready background images."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    backgrounds = _pick_backgrounds(backgrounds_dir, story_cfg.background_selection)
    text = _build_sample_story_text(price_results, sample_text_path)

    paths: list[str] = []
    for i, bg_path in enumerate(backgrounds, start=1):
        out_path = Path(output_dir) / f"story_{i}_{date_str}.png"
        try:
            background = Image.open(bg_path).convert("RGBA")
            text_layer = _render_story_text_layer(text, story_cfg, design=design)
            img = Image.alpha_composite(background, text_layer)
            img.convert("RGB").save(out_path, "PNG", optimize=True)
            paths.append(str(out_path))
            logger.info("Story %d saved: %s", i, out_path)
        except Exception as e:
            logger.error("Story %d failed: %s", i, e, exc_info=True)

    if not paths:
        raise RuntimeError("All 3 story renders failed — check logs")
    return paths


def generate_price_text_stories_from_ready(
    price_results: list[dict],
    story_cfg,
    ready_paths: list[str],
    output_dir: str = "output/step_3_stories",
    sample_text_path: str = "assets/sample_text.txt",
    date_str: str | None = None,
    font_paths: list[str | None] | None = None,
    design: int = 1,
) -> list[str]:
    """
    Like generate_price_text_stories but uses pre-processed images from ready_images/.

    Args:
        ready_paths: paths already cropped, enhanced, and darkened — background processing skipped
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    text = _build_sample_story_text(price_results, sample_text_path)

    paths: list[str] = []
    for i, bg_path in enumerate(ready_paths, start=1):
        out_path = Path(output_dir) / f"step_3_story_{i}_{date_str}.png"
        try:
            render_cfg = _story_cfg_with_font(story_cfg, _font_path_for_index(font_paths, i))
            background = Image.open(bg_path).convert("RGBA")
            text_layer = _render_story_text_layer(text, render_cfg, design=design)
            img = Image.alpha_composite(background, text_layer)
            img.convert("RGB").save(out_path, "PNG", optimize=True)
            paths.append(str(out_path))
            logger.info("Story from ready %d saved: %s", i, out_path)
        except Exception as e:
            logger.error("Story from ready %d failed: %s", i, e, exc_info=True)

    if not paths:
        raise RuntimeError("All renders from ready images failed — check logs")
    return paths


def generate_price_text_stories(
    price_results: list[dict],
    story_cfg,
    output_dir: str = "output/step_3_stories",
    backgrounds_dir: str = "backgrounds",
    sample_text_path: str = "assets/sample_text.txt",
    date_str: str | None = None,
    font_paths: list[str | None] | None = None,
    design: int = 1,
) -> list[str]:
    """Generate 3 edited story images with the sample text and calculated prices."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    backgrounds = _pick_backgrounds(backgrounds_dir, story_cfg.background_selection)
    text = _build_sample_story_text(price_results, sample_text_path)

    paths: list[str] = []
    for i, bg_path in enumerate(backgrounds, start=1):
        out_path = Path(output_dir) / f"step_3_story_{i}_{date_str}.png"
        try:
            render_cfg = _story_cfg_with_font(story_cfg, _font_path_for_index(font_paths, i))
            _render_price_text_story(bg_path, text, render_cfg, out_path, design=design)
            paths.append(str(out_path))
            logger.info("Step 3 story %d saved: %s", i, out_path)
        except Exception as e:
            logger.error("Step 3 story %d failed: %s", i, e, exc_info=True)

    if not paths:
        raise RuntimeError("All 3 step 3 story renders failed — check logs")
    return paths


def _font_path_for_index(font_paths: list[str | None] | None, index: int) -> str | None:
    if not font_paths or index > len(font_paths):
        return None
    return font_paths[index - 1]


def _story_cfg_with_font(story_cfg, font_path: str | None):
    if not font_path:
        return story_cfg
    cfg = copy.copy(story_cfg)
    cfg.font_path = font_path
    return cfg


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


def _render_photo_preview(bg_path: str, out_path: Path) -> None:
    img = Image.open(bg_path).convert("RGB")
    img = _resize_crop(img, STORY_W, STORY_H)
    img = _enhance_photo(img)
    img.save(out_path, "PNG", optimize=True)


def _render_price_text_story(bg_path: str, text: str, cfg, out_path: Path, design: int = 1) -> None:
    background = _prepare_story_background(bg_path)
    text_layer = _render_story_text_layer(text, cfg, design=design)
    img = Image.alpha_composite(background, text_layer)
    img.convert("RGB").save(out_path, "PNG", optimize=True)


def _prepare_story_background(bg_path: str) -> Image.Image:
    """Image-prep layer: crop, enhance, darken, and return an RGBA canvas."""
    img = Image.open(bg_path).convert("RGB")
    img = _resize_crop(img, STORY_W, STORY_H)
    img = _enhance_photo(img).convert("RGBA")
    return Image.alpha_composite(
        img,
        Image.new("RGBA", (STORY_W, STORY_H), (0, 0, 0, 42)),
    )


def _render_story_text_layer(text: str, cfg, design: int = 1) -> Image.Image:
    """
    Text/layout layer boundary.

    The current renderer is a Pillow implementation so the bot keeps working
    with the existing dependency set. This function is the planned swap point for
    an HTML/CSS browser renderer or Pango/Cairo renderer when those runtimes are
    added; image preparation stays in Pillow either way.
    """
    layer = Image.new("RGBA", (STORY_W, STORY_H), (0, 0, 0, 0))
    return _draw_sample_text_lines(layer, text, cfg, design=design)


def _enhance_photo(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Color(img).enhance(1.06)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.12)
    img = ImageEnhance.Brightness(img).enhance(0.92)
    return img


def _resize_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    ow, oh = img.size
    scale = max(w / ow, h / oh)
    nw, nh = int(ow * scale), int(oh * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))



def _draw_sample_text_lines(img: Image.Image, text: str, cfg, design: int = 1) -> Image.Image:
    draw = ImageDraw.Draw(img)
    sections = _build_story_sections(_sanitize_story_text(text))
    design_spec = _DESIGNS.get(design, _DESIGNS[1])
    base_font = getattr(cfg, "font_path", "")
    font_path = _resolve_design_font(design_spec, base_font)

    rendered_sections = []
    max_total_h = STORY_H - 160
    bold_body = design_spec.get("bold_body", True)

    for title_size in range(56, 33, -2):
        section_title_font = _font(font_path, title_size, bold=True)
        section_body_font = _font(font_path, max(30, title_size - 12), bold=bold_body)
        candidate = _prepare_render_sections(
            sections, draw, section_title_font, section_body_font, font_path, design_spec,
        )
        total_h = _sections_total_height(candidate)
        if total_h <= max_total_h:
            rendered_sections = candidate
            break
    if not rendered_sections:
        section_title_font = _font(font_path, 32, bold=True)
        section_body_font = _font(font_path, 26, bold=bold_body)
        rendered_sections = _prepare_render_sections(
            sections, draw, section_title_font, section_body_font, font_path, design_spec,
        )
        total_h = _sections_total_height(rendered_sections)

    y = max(60, (STORY_H - total_h) // 2)
    for section in rendered_sections:
        img = _draw_story_section(img, y, section)
        y += section["height"] + section["gap_after"]
    return img


def _wrap_sample_text(text: str, draw: ImageDraw.ImageDraw, font, max_w: int) -> list[str]:
    wrapped: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            wrapped.append("")
            continue
        if _text_width(draw, line, font) <= max_w:
            wrapped.append(line)
            continue

        current = ""
        for word in line.split():
            candidate = word if not current else f"{current} {word}"
            if _text_width(draw, candidate, font) <= max_w:
                current = candidate
            else:
                if current:
                    wrapped.append(current)
                current = word
        if current:
            wrapped.append(current)
    return wrapped


def _build_story_sections(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines()]
    non_empty = [line for line in lines if line]
    if not non_empty:
        return []

    # Section 1: Title (first line)
    title = non_empty[0]
    
    # Sections 2-4: Split by section headers (iPhone, Девайсы/Devices, Контакты/Contact)
    section_headers = {"iphone", "девайсы", "devices", "контакты", "contact", "order"}
    current_section = None
    sections_dict: dict[str, list[str]] = {"title": [title]}
    
    for line in non_empty[1:]:
        low = line.lower()
        if low in section_headers:
            current_section = low if low in {"девайсы", "контакты"} else "iphone" if "iphone" in low else "devices" if "devices" in low else "contact"
            if current_section not in sections_dict:
                sections_dict[current_section] = []
        elif current_section and line:
            sections_dict[current_section].append(line)
    
    # Build sections list with 4 distinct panels
    sections = [{"title": None, "lines": sections_dict["title"], "kind": "title"}]
    if "iphone" in sections_dict and sections_dict["iphone"]:
        sections.append({"title": "iPhone", "lines": sections_dict["iphone"], "kind": "iphone"})
    if "девайсы" in sections_dict and sections_dict["девайсы"]:
        sections.append({"title": "Девайсы", "lines": sections_dict["девайсы"], "kind": "devices"})
    elif "devices" in sections_dict and sections_dict["devices"]:
        sections.append({"title": "Devices", "lines": sections_dict["devices"], "kind": "devices"})
    if "контакты" in sections_dict and sections_dict["контакты"]:
        sections.append({"title": "Контакты", "lines": sections_dict["контакты"], "kind": "contacts"})
    elif "contact" in sections_dict and sections_dict["contact"]:
        sections.append({"title": "Contact", "lines": sections_dict["contact"], "kind": "contacts"})
    
    return sections


def _prepare_render_sections(
    sections: list[dict],
    draw: ImageDraw.ImageDraw,
    title_font,
    body_font,
    font_path: str = "",
    design_spec: dict | None = None,
) -> list[dict]:
    spec = design_spec or _DESIGNS[1]
    prepared: list[dict] = []
    for section in sections:
        is_title = section["kind"] == "title"
        font = title_font if is_title else body_font
        regular_font = _font(_regular_font_path(font_path), _font_size(font), bold=False)
        bold_body = spec.get("bold_body", True)
        header_font = _font(font_path, max(24, _font_size(body_font) - 7), bold=bold_body)
        pad_x = 36 if is_title else 32
        pad_y = spec["pad_y_title"] if is_title else spec["pad_y"]
        margin_x = 40
        max_w = STORY_W - 2 * margin_x - 2 * pad_x
        line_gap = spec["line_gap"]
        wrapped_lines: list[str] = []
        if section.get("title"):
            wrapped_lines.extend(_wrap_sample_text(section["title"], draw, header_font, max_w))
        for line in section["lines"]:
            wrapped = _wrap_sample_text(line, draw, font, max_w)
            wrapped_lines.extend(wrapped or [""])
        body_lines = [line for line in wrapped_lines if line]
        title_count = 1 if section.get("title") and body_lines else 0
        line_h = int(_font_size(font) * (1.12 if is_title else 1.08))
        header_h = int(_font_size(header_font) * 1.05)
        content_h = 0
        for idx, line in enumerate(body_lines):
            content_h += header_h if idx < title_count else line_h
        content_h += max(0, len(body_lines) - 1) * line_gap
        height = content_h + 2 * pad_y

        # Panel width: full-row or content-aware (hug text) per design
        full_panel_w = STORY_W - 2 * margin_x
        if spec.get("content_width"):
            line_widths = [
                _text_width(draw, line, header_font if idx < title_count else font)
                for idx, line in enumerate(body_lines)
            ] if body_lines else [200]
            max_text_w = max(line_widths) if line_widths else 200
            panel_width = min(full_panel_w, max(300, max_text_w + 2 * pad_x + 16))
        else:
            panel_width = full_panel_w

        # Design-specific panel + text styling embedded into each section dict
        if is_title:
            fill    = spec["title_panel"]
            outline = spec["title_outline"]
            stroke_w = spec["stroke_w"]
            stroke_c = spec["stroke_c"]
        else:
            fill    = spec["card_panel"]
            outline = spec["card_outline"]
            stroke_w = 0
            stroke_c = (0, 0, 0, 0)

        prepared.append({
            "kind": section["kind"],
            "font": font,
            "regular_font": regular_font,
            "header_font": header_font,
            "title_count": title_count,
            "lines": body_lines,
            "line_height": line_h,
            "header_height": header_h,
            "line_gap": line_gap,
            "pad_x": pad_x,
            "pad_y": pad_y,
            "margin_x": margin_x,
            "height": height,
            "radius": 34 if is_title else 30,
            "gap_after": 18 if is_title else 14,
            "align": "center" if is_title else "left",
            "min_width": 760 if is_title else (720 if section["kind"] in {"iphone", "devices"} else 620),
            "panel_width": panel_width,
            # design fields
            "fill": fill,
            "outline": outline,
            "body_text_c":     spec["body_text_c"],
            "header_text_c":   spec["header_text_c"],
            "username_text_c": spec["username_text_c"],
            "stroke_w": stroke_w,
            "stroke_c": stroke_c,
        })
    return prepared


def _sections_total_height(sections: list[dict]) -> int:
    if not sections:
        return 0
    return sum(section["height"] + section["gap_after"] for section in sections) - sections[-1]["gap_after"]


def _draw_story_section(img: Image.Image, y: int, section: dict) -> Image.Image:
    draw = ImageDraw.Draw(img)
    panel_w = section.get("panel_width", STORY_W - 2 * section["margin_x"])
    x0 = (STORY_W - panel_w) // 2
    x1 = x0 + panel_w
    y1 = y + section["height"]

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    fill   = section.get("fill",    _section_palette(section["kind"])[0])
    outline = section.get("outline", _section_palette(section["kind"])[1])
    layer_draw.rounded_rectangle((x0, y, x1, y1), radius=section["radius"], fill=fill, outline=outline, width=2)
    img = Image.alpha_composite(img, layer)

    draw = ImageDraw.Draw(img)
    text_y = y + section["pad_y"] - 2
    for idx, line in enumerate(section["lines"]):
        is_section_title = idx < section.get("title_count", 0)
        _draw_rich_line(img, x0, x1, text_y, line, section, is_section_title=is_section_title)
        text_y += section["header_height"] if is_section_title else section["line_height"]
        if idx < len(section["lines"]) - 1:
            text_y += section["line_gap"]
    return img


def _section_palette(kind: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    if kind == "title":
        return (0, 0, 0, 0), (0, 0, 0, 0)  # no panel — white text on raw background
    return (0, 0, 0, 115), (255, 255, 255, 22)  # dark frosted glass



def _resolve_design_font(spec: dict, base_font_path: str) -> str:
    override = spec.get("font_override")
    if not override:
        return base_font_path
    if override == "avenir_or_serif":
        candidates = [
            "/System/Library/Fonts/Avenir Next.ttc",
            "/System/Library/Fonts/Avenir.ttc",
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ]
        for p in candidates:
            if Path(p).exists():
                return p
    return base_font_path


def _font(path: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        path,
        # macOS
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFNSRounded.ttf",
        "/System/Library/Fonts/SFCompact.ttf",
        "/System/Library/Fonts/SFPro.ttf",
        "/System/Library/Fonts/SF.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf" if bold else "",
        "/System/Library/Fonts/Supplemental/Arial Unicode Bold.ttf" if bold else "",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        # Linux / Docker — Cyrillic-capable (fonts-noto-core, fonts-dejavu-core)
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default(size=size)


def _regular_font_path(path: str) -> str:
    if not path:
        return ""
    candidates = [
        path.replace("SemiBold", "Regular"),
        path.replace("Semibold", "Regular"),
        path.replace("SEMIBOLD", "REGULAR"),
        path.replace("Bold", "Regular"),
        path.replace("BOLD", "REGULAR"),
        path.replace("Medium", "Regular"),
        path.replace("MEDIUM", "REGULAR"),
    ]
    for candidate in candidates:
        if candidate != path and Path(candidate).exists():
            return candidate
    return ""


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


def _rich_text_width(draw: ImageDraw.ImageDraw, line: str, section: dict, is_section_title: bool = False) -> int:
    segments = _split_line_segments(line)
    total = 0
    for seg_type, seg_text in segments:
        if seg_type == "emoji":
            total += _emoji_width(seg_text, section, is_section_title=is_section_title)
        else:
            font = _segment_font(section, seg_type, is_section_title=is_section_title)
            total += _text_width(draw, seg_text, font)
    return total


def _draw_rich_line(
    img: Image.Image,
    x0: int,
    x1: int,
    y: int,
    line: str,
    section: dict,
    is_section_title: bool = False,
) -> None:
    draw = ImageDraw.Draw(img)
    segments = _split_line_segments(line)
    total_w = _rich_text_width(draw, line, section, is_section_title=is_section_title)
    if section["align"] == "left":
        x = x0 + section["pad_x"]
    else:
        x = x0 + ((x1 - x0) - total_w) // 2
    underline_runs: list[tuple[int, int, int]] = []
    for seg_type, seg_text in segments:
        if seg_type == "emoji":
            emoji_img = _emoji_image(seg_text, _segment_size(section, is_section_title=is_section_title))
            if emoji_img is None:
                seg_w = 0
            else:
                img.alpha_composite(emoji_img, (int(x), int(y)))
                seg_w = emoji_img.width
        else:
            font = _segment_font(section, seg_type, is_section_title=is_section_title)
            if seg_type == "username":
                color = section.get("username_text_c") or _segment_color("username")
            elif is_section_title:
                color = section.get("header_text_c") or _segment_color("text", section["kind"], True)
            else:
                color = section.get("body_text_c") or _segment_color("text", section["kind"])
            stroke_w = section.get("stroke_w", 0)
            stroke_c = section.get("stroke_c", (0, 0, 0, 0))
            draw.text((x, y), seg_text, font=font, fill=color, stroke_width=stroke_w, stroke_fill=stroke_c)
            seg_w = _text_width(draw, seg_text, font)
        # if seg_type == "username":
        #     underline_runs.append((x, x + seg_w, y + section["line_height"] - 6))
        x += seg_w
    for ux0, ux1, uy in underline_runs:
        draw.line((ux0, uy, ux1, uy), fill=(49, 99, 255, 255), width=2)


def _split_line_segments(line: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    i = 0
    text_buf: list[str] = []

    def flush_text() -> None:
        if text_buf:
            segments.extend(_split_price_segments("".join(text_buf)))
            text_buf.clear()

    while i < len(line):
        username_match = _USERNAME_RE.match(line, i)
        if username_match:
            flush_text()
            segments.append(("username", username_match.group(0)))
            i = username_match.end()
            continue

        emoji_cluster = _take_emoji_cluster(line, i)
        if emoji_cluster:
            flush_text()
            segments.append(("emoji", emoji_cluster))
            i += len(emoji_cluster)
            continue

        text_buf.append(line[i])
        i += 1

    flush_text()
    return segments or [("text", line)]


def _split_price_segments(text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    pos = 0
    for match in _PRICE_TEXT_RE.finditer(text):
        if match.start() > pos:
            segments.append(("text", text[pos:match.start()]))
        segments.append(("price", match.group(0)))
        pos = match.end()
    if pos < len(text):
        segments.append(("text", text[pos:]))
    return segments


def _take_emoji_cluster(text: str, start: int) -> str:
    if start >= len(text) or not _is_emoji_char(text[start]):
        return ""
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ord(ch) in {0xFE0E, 0xFE0F}:
            i += 1
            continue
        if ord(ch) == 0x200D and i + 1 < len(text) and _is_emoji_char(text[i + 1]):
            i += 2
            continue
        break
    return text[start:i]


def _is_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2300 <= cp <= 0x23FF
        or cp == 0x303D
    )


def _segment_size(section: dict, is_section_title: bool = False) -> int:
    base = section["header_font"] if is_section_title else section["font"]
    return _font_size(base)


def _emoji_width(text: str, section: dict, is_section_title: bool = False) -> int:
    img = _emoji_image(text, _segment_size(section, is_section_title=is_section_title))
    return img.width if img is not None else 0


def _emoji_image(text: str, size: int) -> Image.Image | None:
    key = (text, size)
    if key not in _EMOJI_IMAGE_CACHE:
        _EMOJI_IMAGE_CACHE[key] = _render_emoji_with_font(text, size)
    cached = _EMOJI_IMAGE_CACHE[key]
    return cached.copy() if cached is not None else None


def _emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    candidates = [
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/Library/Fonts/Apple Color Emoji.ttc",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto-emoji/NotoColorEmoji.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return None


def _render_emoji_with_font(text: str, size: int) -> Image.Image | None:
    font = _emoji_font(size)
    if font is None:
        return None
    canvas = size * 3
    tmp = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    d.text((0, 0), text, font=font, fill=(255, 255, 255, 255), embedded_color=True)
    bbox = tmp.getbbox()
    if not bbox:
        return None
    return tmp.crop(bbox)


def _segment_font(section: dict, seg_type: str, is_section_title: bool = False):
    if is_section_title:
        return section["header_font"]
    if seg_type == "price":
        return section.get("regular_font") or section["font"]
    return section["font"]


def _segment_color(seg_type: str, kind: str = "", is_section_title: bool = False):
    if seg_type == "username":
        return (100, 190, 255, 255)
    if is_section_title:
        return (200, 200, 200, 255)  # slightly subdued for section headers inside cards
    return (245, 245, 245, 255)  # white for all body text



def _build_sample_story_text(price_results: list[dict], sample_text_path: str) -> str:
    template = _resolve_sample_text_path(sample_text_path).read_text(encoding="utf-8")
    values: dict[str, str] = {
        r["template_key"]: _story_price(r.get("calculated_price"))
        for r in price_results
        if r.get("template_key")
    }
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), "— рублей"), template)


def _story_price(value: int | None) -> str:
    if value is None:
        return "— рублей"
    return f"{value:,}".replace(",", " ") + " рублей"


def _resolve_sample_text_path(sample_text_path: str) -> Path:
    path = Path(sample_text_path)
    if path.exists():
        return path
    if path.name == "sample.txt":
        fallback = path.with_name("sample_text.txt")
        if fallback.exists():
            return fallback
    if path.name == "sample_text.txt":
        fallback = path.with_name("sample.txt")
        if fallback.exists():
            return fallback
    raise FileNotFoundError(f"Sample text file not found: {sample_text_path}")


def _sanitize_story_text(text: str) -> str:
    # Remove emoji entries from the dictionary mappings
    for src in _EMOJI_TEXT_REPLACEMENTS.keys():
        text = text.replace(src, "")
    # Remove asterisks used for bullet points
    text = text.replace("*", "")
    # Remove other common emoji variations and variation selectors
    text = text.replace("\uFE0F", "")  # Variation Selector-16
    text = text.replace("\uFE0E", "")  # Variation Selector-15
    text = text.replace("\u200D", "")  # Zero-width joiner
    cleaned_lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(cleaned_lines)
