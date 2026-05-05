import pytest
from src.parser import normalize


# ── Basic normalisation ────────────────────────────────────────────────────────

def test_lowercase():
    text, _ = normalize("iPhone PRO 256 GB")
    assert text == "iphone pro 256 gb"


def test_empty_input():
    text, segs = normalize("")
    assert text == ""
    assert segs == []


def test_whitespace_collapsed():
    text, _ = normalize("iphone   pro  256")
    assert "  " not in text


def test_zero_width_removed():
    text, _ = normalize("iPhone​Pro")
    assert "​" not in text


def test_soft_hyphen_removed():
    text, _ = normalize("iphone­pro")
    assert "­" not in text


def test_html_stripped():
    text, _ = normalize("<b>iPhone Pro 256</b> — 85000 руб")
    assert "<b>" not in text
    assert "iphone" in text


def test_markdown_bold_stripped():
    text, _ = normalize("**iPhone Pro 256** 85000 rub")
    assert "**" not in text
    assert "iphone" in text


def test_segments_split_on_newlines():
    _, segs = normalize("iPhone Pro 256 — 85000\nMacBook Neo — 142000")
    assert len(segs) == 2


def test_segments_empty_lines_skipped():
    _, segs = normalize("line one\n\n\nline two")
    assert len(segs) == 2


# ── k-shorthand ────────────────────────────────────────────────────────────────

def test_k_integer():
    text, _ = normalize("85к")
    assert "85000" in text


def test_k_decimal():
    text, _ = normalize("18.5к")
    assert "18500" in text


def test_k_with_comma():
    text, _ = normalize("18,5к")
    assert "18500" in text


def test_k_large():
    text, _ = normalize("143к")
    assert "143000" in text


# ── Russian → Latin transliteration ───────────────────────────────────────────

def test_iphone_base():
    text, _ = normalize("Айфон")
    assert "iphone" in text


def test_iphone_genitive():
    text, _ = normalize("айфона про 256")
    assert "iphone" in text


def test_iphone_plural():
    text, _ = normalize("айфоны про")
    assert "iphone" in text


def test_pro():
    text, _ = normalize("айфон Про 256")
    assert "pro" in text


def test_max():
    text, _ = normalize("Айфон Про Макс 256")
    assert "max" in text


def test_macbook():
    text, _ = normalize("Макбук Нео 142000")
    assert "macbook" in text


def test_airpods():
    text, _ = normalize("Аирподс Про 3")
    assert "airpods" in text


def test_airpods_variant():
    text, _ = normalize("аирпадс про 3")
    assert "airpods" in text


def test_apple():
    text, _ = normalize("Эпл Вотч С11")
    assert "apple" in text


def test_watch():
    text, _ = normalize("вотч с11")
    assert "watch" in text


def test_series_cyrillic_s():
    text, _ = normalize("Watch С11")
    assert "s11" in text


def test_gb_cyrillic():
    text, _ = normalize("256 ГБ")
    assert "gb" in text


def test_tb_cyrillic():
    text, _ = normalize("1 ТБ")
    assert "tb" in text


def test_rub_full():
    text, _ = normalize("85000 рублей")
    assert "rub" in text


def test_rub_short():
    text, _ = normalize("85000 руб")
    assert "rub" in text


def test_rub_r():
    text, _ = normalize("85000р")
    assert "rub" in text


def test_ps_cyrillic():
    text, _ = normalize("ПС5 47000")
    assert "ps" in text


def test_playstation_cyrillic():
    text, _ = normalize("плейстейшн 5")
    assert "playstation" in text


# ── Full sentence round-trip ───────────────────────────────────────────────────

def test_full_russian_sentence():
    text, segs = normalize("Айфон Про 256 — 84500 руб")
    assert "iphone" in text
    assert "pro" in text
    assert "256" in text
    assert "84500" in text
    assert "rub" in text
    assert len(segs) == 1


def test_full_k_sentence():
    text, _ = normalize("17 Pro Max 256 96к")
    assert "96000" in text


def test_uppercase_preserved_as_lowercase():
    text, _ = normalize("IPHONE PRO 256 GB 85000 RUB")
    assert text == "iphone pro 256 gb 85000 rub"
