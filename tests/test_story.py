import pytest
from pathlib import Path
from PIL import Image

from src.config import StorySettings
from src.story import generate_stories, _resize_crop, _build_lines, _pick_backgrounds


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
