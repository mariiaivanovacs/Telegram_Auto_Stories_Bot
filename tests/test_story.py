import pytest
from pathlib import Path
from PIL import Image

from src.config import StorySettings
from src.story import (
    generate_price_text_stories,
    generate_photo_previews,
    generate_stories,
    _build_lines,
    _build_sample_story_text,
    _build_story_sections,
    _enhance_photo,
    _pick_backgrounds,
    _resize_crop,
    _sanitize_story_text,
    _split_line_segments,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def bg_dir(tmp_path):
    """Three solid-colour 400×600 backgrounds."""
    d = tmp_path / "backgrounds"
    d.mkdir()
    for i, colour in enumerate([(200, 100, 50), (50, 150, 200), (100, 200, 80)]):
        img = Image.new("RGB", (400, 600), color=colour)
        img.save(d / f"bg_{i}.jpg")
    return d


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def cfg():
    return StorySettings(font_path="")  # empty path → falls back to default font


@pytest.fixture
def price_results():
    return [
        {"template_key": "iphone_pro_256", "canonical_name": "iPhone Pro 256 GB",
         "display_name": "Pro 256 GB", "category": "iPhone",
         "calculated_price": 84500, "price_kept": False},
        {"template_key": "iphone_pro_max_256", "canonical_name": "iPhone Pro Max 256 GB",
         "display_name": "Pro Max 256 GB", "category": "iPhone",
         "calculated_price": 94500, "price_kept": False},
        {"template_key": "macbook_neo", "canonical_name": "MacBook Neo",
         "display_name": "MacBook Neo", "category": "Other",
         "calculated_price": 141500, "price_kept": False},
        {"template_key": "ps5", "canonical_name": "PS5",
         "display_name": "PS5", "category": "Other",
         "calculated_price": None, "price_kept": True},
    ]


# ── _resize_crop ───────────────────────────────────────────────────────────────

def test_resize_crop_correct_size():
    img = Image.new("RGB", (800, 600))
    result = _resize_crop(img, 1080, 1920)
    assert result.size == (1080, 1920)


def test_resize_crop_portrait_input():
    img = Image.new("RGB", (500, 1000))
    result = _resize_crop(img, 1080, 1920)
    assert result.size == (1080, 1920)


def test_resize_crop_already_correct_ratio():
    img = Image.new("RGB", (1080, 1920))
    result = _resize_crop(img, 1080, 1920)
    assert result.size == (1080, 1920)


def test_resize_crop_wide_input():
    img = Image.new("RGB", (3000, 400))
    result = _resize_crop(img, 1080, 1920)
    assert result.size == (1080, 1920)


# ── _build_lines ───────────────────────────────────────────────────────────────

def test_build_lines_has_header(price_results):
    lines = _build_lines(price_results)
    headers = [l for l in lines if l["type"] == "header"]
    assert len(headers) == 1


def test_build_lines_has_price_entries(price_results):
    lines = _build_lines(price_results)
    price_lines = [l for l in lines if l["type"] == "price"]
    assert len(price_lines) == 4  # all 4 products


def test_build_lines_missing_price_shows_dash(price_results):
    lines = _build_lines(price_results)
    ps5_line = next(l for l in lines if "PS5" in l.get("text", ""))
    assert "—" in ps5_line["text"]


def test_build_lines_category_headers(price_results):
    lines = _build_lines(price_results)
    cats = [l["text"] for l in lines if l["type"] == "category"]
    assert "iPhone" in cats
    assert "Other" in cats


def test_build_lines_has_footer(price_results):
    lines = _build_lines(price_results)
    footers = [l for l in lines if l["type"] == "footer"]
    assert len(footers) >= 2


# ── _pick_backgrounds ──────────────────────────────────────────────────────────

def test_pick_backgrounds_returns_3(bg_dir):
    paths = _pick_backgrounds(str(bg_dir), "random")
    assert len(paths) == 3


def test_pick_backgrounds_sequential(bg_dir):
    paths = _pick_backgrounds(str(bg_dir), "sequential")
    assert len(paths) == 3
    # With 3 files, sequential should return each file once
    assert len(set(paths)) == 3


def test_pick_backgrounds_fewer_than_3_fills_up(tmp_path):
    d = tmp_path / "bgs"
    d.mkdir()
    Image.new("RGB", (100, 200)).save(d / "only.jpg")
    paths = _pick_backgrounds(str(d), "random")
    assert len(paths) == 3


def test_pick_backgrounds_no_files_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        _pick_backgrounds(str(empty), "random")


# ── generate_stories ──────────────────────────────────────────────────────────

def test_generates_3_files(bg_dir, out_dir, cfg, price_results):
    paths = generate_stories(
        price_results, cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    assert len(paths) == 3


def test_output_files_exist(bg_dir, out_dir, cfg, price_results):
    paths = generate_stories(
        price_results, cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    for p in paths:
        assert Path(p).exists(), f"Missing: {p}"


def test_output_dimensions(bg_dir, out_dir, cfg, price_results):
    paths = generate_stories(
        price_results, cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    for p in paths:
        img = Image.open(p)
        assert img.size == (1080, 1920), f"Wrong size in {p}: {img.size}"


def test_output_filenames(bg_dir, out_dir, cfg, price_results):
    paths = generate_stories(
        price_results, cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    names = [Path(p).name for p in paths]
    assert "story_1_20260504.png" in names
    assert "story_2_20260504.png" in names
    assert "story_3_20260504.png" in names


def test_empty_price_results_still_renders(bg_dir, out_dir, cfg):
    paths = generate_stories(
        [], cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    assert len(paths) == 3
    for p in paths:
        img = Image.open(p)
        assert img.size == (1080, 1920)


# ── generate_photo_previews ───────────────────────────────────────────────────

def test_photo_previews_generate_3_files(bg_dir, out_dir, cfg):
    paths = generate_photo_previews(
        cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    assert len(paths) == 3


def test_photo_previews_output_dimensions(bg_dir, out_dir, cfg):
    paths = generate_photo_previews(
        cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    for p in paths:
        img = Image.open(p)
        assert img.size == (1080, 1920)


def test_photo_previews_filenames(bg_dir, out_dir, cfg):
    paths = generate_photo_previews(
        cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        date_str="20260504",
    )
    names = [Path(p).name for p in paths]
    assert "photo_preview_1_20260504.png" in names
    assert "photo_preview_2_20260504.png" in names
    assert "photo_preview_3_20260504.png" in names


def test_enhance_photo_changes_pixels():
    img = Image.new("RGB", (20, 20), color=(120, 80, 40))
    enhanced = _enhance_photo(img)
    assert enhanced.getpixel((0, 0)) != img.getpixel((0, 0))


# ── generate_price_text_stories ───────────────────────────────────────────────

def test_sample_story_text_replaces_prices(tmp_path, price_results):
    template = tmp_path / "sample_text.txt"
    template.write_text("Pro — ХХХ ₽\nMax — ХХХ ₽", encoding="utf-8")
    text = _build_sample_story_text(price_results, str(template))
    assert "ХХХ рублей" in text
    assert "рублей" in text


def test_sample_story_text_accepts_sample_txt_fallback(tmp_path, price_results):
    template = tmp_path / "sample_text.txt"
    template.write_text("Pro — ХХХ ₽", encoding="utf-8")
    text = _build_sample_story_text(price_results, str(tmp_path / "sample.txt"))
    assert "ХХХ рублей" in text


def test_sanitize_story_text_removes_unrenderable_markers():
    text = _sanitize_story_text("📱 iPhone\n* Pro 256 ГБ — 84 500 ₽\n⚡️ В наличии")
    assert "📱" not in text
    assert "*" not in text
    assert "84 500 ₽" in text
    assert "iPhone" in text
    assert "В наличии" in text


def test_split_line_segments_keeps_emoji_clusters_and_username():
    segments = _split_line_segments("⚡️ В наличии у @svyat_001")
    assert ("emoji", "⚡️") in segments
    assert ("username", "@svyat_001") in segments


def test_split_line_segments_marks_prices_for_regular_weight():
    segments = _split_line_segments("Pro 256 ГБ — 84 500 рублей")
    assert ("price", "84 500 рублей") in segments


def test_build_story_sections_groups_content():
    text = (
        "Любая техника в наличии по выгодной цене\n"
        "iPhone\n"
        "Pro 256 ГБ — 84 500 ₽\n"
        "Pro 512 ГБ — 120 000 ₽"
    )
    sections = _build_story_sections(text)
    assert sections[0]["kind"] == "title"
    assert len(sections) >= 2
    assert sections[1]["title"] == "iPhone"
    assert sections[1]["kind"] == "section"
    assert any("Pro 256" in line for line in sections[1]["lines"])


def test_price_text_stories_generate_3_files(bg_dir, out_dir, cfg, price_results, tmp_path):
    template = tmp_path / "sample_text.txt"
    template.write_text("Любая техника\nPro — ХХХ ₽", encoding="utf-8")
    paths = generate_price_text_stories(
        price_results,
        cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        sample_text_path=str(template),
        date_str="20260504",
    )
    assert len(paths) == 3


def test_price_text_stories_output_dimensions(bg_dir, out_dir, cfg, price_results, tmp_path):
    template = tmp_path / "sample_text.txt"
    template.write_text("Любая техника\nPro — ХХХ ₽", encoding="utf-8")
    paths = generate_price_text_stories(
        price_results,
        cfg,
        output_dir=str(out_dir),
        backgrounds_dir=str(bg_dir),
        sample_text_path=str(template),
        date_str="20260504",
    )
    for p in paths:
        img = Image.open(p)
        assert img.size == (1080, 1920)
