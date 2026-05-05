import pytest
from src.config import ProductConfig
from src.matcher import match_products, _extract_price
from src.parser import normalize


# ── Helpers ────────────────────────────────────────────────────────────────────

def msg(channel: str, text: str) -> dict:
    norm, segs = normalize(text)
    return {"channel_username": channel, "normalized_text": norm, "segments": segs}


# ── Minimal product fixtures ───────────────────────────────────────────────────

PRO_256 = ProductConfig(
    id="iphone_pro_256", canonical="iPhone 17 Pro 256 GB", category="iPhone",
    display_name="17 Pro 256 GB",
    aliases=["iphone 17 pro 256", "17 iphone pro 256", "17 pro 256 gb", "17 pro 256gb",
             "айфон 17 про 256", "17 айфон про 256"],
    regex=r"(?=.*\b17\b)(?=.*\bpro\b)(?=.*\b256\s*(?:gb)?\b)",
    exclude_if_contains=["max", "plus"],
)

PRO_MAX_256 = ProductConfig(
    id="iphone_pro_max_256", canonical="iPhone 17 Pro Max 256 GB", category="iPhone",
    display_name="17 Pro Max 256 GB",
    aliases=["iphone 17 pro max 256", "17 iphone pro max 256", "17 pro max 256 gb",
             "17 pro max 256gb", "айфон 17 про макс 256", "17 айфон про макс 256"],
    regex=r"(?=.*\b17\b)(?=.*\bpro\b)(?=.*\bmax\b)(?=.*\b256\s*(?:gb)?\b)",
    exclude_if_contains=[],
)

PRO_1TB = ProductConfig(
    id="iphone_pro_1tb", canonical="iPhone 17 Pro 1 TB", category="iPhone",
    display_name="17 Pro 1 TB",
    aliases=["iphone 17 pro 1tb", "iphone 17 pro 1 tb", "17 pro 1tb",
             "17 pro 1 tb", "айфон 17 про 1тб"],
    regex=r"(?=.*\b17\b)(?=.*\bpro\b)(?=.*\b1\s*tb\b)",
    exclude_if_contains=["max"],
)

MACBOOK_NEO = ProductConfig(
    id="macbook_neo", canonical="MacBook Neo", category="Other",
    display_name="MacBook Neo",
    aliases=["macbook neo", "mac neo", "мак нео", "макбук нео"],
    regex=r"macbook\s*neo",
    exclude_if_contains=[],
)

AIRPODS_PRO_3 = ProductConfig(
    id="airpods_pro_3", canonical="AirPods Pro 3", category="Other",
    display_name="AirPods Pro 3",
    aliases=["airpods pro 3", "airpods pro3", "pods pro 3", "аирподс про 3"],
    regex=r"airpods\s*pro\s*3",
    exclude_if_contains=[],
)

PS5 = ProductConfig(
    id="ps5", canonical="PS5", category="Other",
    display_name="PS5",
    aliases=["ps5", "playstation 5", "playstation5", "пс5", "пс 5", "плейстейшн 5"],
    regex=r"ps\s*5|playstation\s*5",
    exclude_if_contains=[],
)

WATCH_S11 = ProductConfig(
    id="apple_watch_s11", canonical="Apple Watch S11", category="Other",
    display_name="Apple Watch S11",
    aliases=["apple watch s11", "watch s11", "watch series 11", "эпл вотч с11"],
    regex=r"(?:apple\s*)?watch\s*s(?:eries\s*)?11",
    exclude_if_contains=[],
)

WHOOP = ProductConfig(
    id="whoop_50", canonical="Whoop 5.0 Peak", category="Other",
    display_name="Whoop 5.0 Peak",
    aliases=["whoop 5.0 peak", "whoop 5.0", "whoop 5", "whoop peak"],
    regex=r"whoop\s*5(?:\.0)?(?:\s*peak)?",
    exclude_if_contains=[],
)

ALL_PRODUCTS = [PRO_256, PRO_MAX_256, PRO_1TB, MACBOOK_NEO, AIRPODS_PRO_3, PS5, WATCH_S11, WHOOP]


# ── _extract_price ─────────────────────────────────────────────────────────────

def test_price_explicit_rub():
    assert _extract_price("85000 rub") == 85000

def test_price_explicit_r():
    assert _extract_price("85000 р.") == 85000

def test_price_with_spaces():
    assert _extract_price("85 000 rub") == 85000

def test_price_with_dot_thousands():
    assert _extract_price("iPhone 17 Pro 256GB Blue - 99.990₽") == 99990

def test_price_after_colon():
    assert _extract_price("Цена: 35.000₽") == 35000

def test_price_bare_5digit():
    assert _extract_price("pro 256 84500") == 84500

def test_price_after_k_expansion():
    # normalize() already converts "85к" → "85000" before matcher sees it
    assert _extract_price("pro 256 85000") == 85000

def test_price_none_no_number():
    assert _extract_price("iPhone Pro 256 GB in stock") is None

def test_price_none_too_small():
    assert _extract_price("version 256") is None  # 256 < 1000, filtered out


# ── iphone_pro_256 matching ────────────────────────────────────────────────────

def test_pro256_english_rub():
    r = match_products([msg("@ch", "iPhone 17 Pro 256 GB — 84500 rub")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 84500

def test_pro256_russian():
    r = match_products([msg("@ch", "Айфон 17 Про 256 — 84500 руб")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 84500

def test_pro256_k_shorthand():
    r = match_products([msg("@ch", "17 Pro 256GB 85к")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 85000

def test_pro256_uppercase():
    r = match_products([msg("@ch", "IPHONE 17 PRO 256 GB 85000 RUB")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 85000

def test_pro256_no_currency():
    r = match_products([msg("@ch", "iphone 17 pro 256gb 84800")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 84800

def test_pro256_with_spaces_in_price():
    r = match_products([msg("@ch", "iPhone 17 Pro 256 GB — 84 500 руб")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 84500

def test_pro256_adsapple_dot_price():
    r = match_products([msg("@ch", "iPhone 17 Pro 256GB Blue - 99.990₽")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 99990


# ── Exclusion guard ────────────────────────────────────────────────────────────

def test_pro_max_256_does_not_match_pro_256():
    r = match_products([msg("@ch", "iPhone 17 Pro Max 256 GB — 95000 rub")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] is None

def test_pro_max_256_does_match_pro_max():
    r = match_products([msg("@ch", "iPhone 17 Pro Max 256 GB — 95000 rub")], [PRO_MAX_256])
    assert r["iphone_pro_max_256"]["min_price"] == 95000


# ── Min price across channels ──────────────────────────────────────────────────

def test_min_price_selected():
    messages = [
        msg("@ch1", "iphone 17 pro 256 87000 rub"),
        msg("@ch2", "iphone 17 pro 256 85000 rub"),
        msg("@ch3", "iphone 17 pro 256 86000 rub"),
    ]
    r = match_products(messages, [PRO_256])
    assert r["iphone_pro_256"]["min_price"] == 85000
    assert r["iphone_pro_256"]["source_channel"] == "@ch2"

def test_all_prices_collected():
    messages = [
        msg("@ch1", "17 pro 256 84000 rub"),
        msg("@ch2", "17 pro 256 85000 rub"),
    ]
    r = match_products(messages, [PRO_256])
    assert sorted(r["iphone_pro_256"]["all_prices"]) == [84000, 85000]


# ── No match ──────────────────────────────────────────────────────────────────

def test_no_match_returns_none():
    r = match_products([msg("@ch", "random message without products")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] is None

def test_no_price_returns_none():
    r = match_products([msg("@ch", "iPhone 17 Pro 256 available in stock")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] is None


def test_iphone_without_17_does_not_match():
    r = match_products([msg("@ch", "iPhone Pro 256 GB — 84500 rub")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] is None


def test_iphone_16_does_not_match():
    r = match_products([msg("@ch", "iPhone 16 Pro 256 GB — 74500 rub")], [PRO_256])
    assert r["iphone_pro_256"]["min_price"] is None


# ── Other products ─────────────────────────────────────────────────────────────

def test_macbook_neo_english():
    r = match_products([msg("@ch", "MacBook Neo — 142000 rub")], [MACBOOK_NEO])
    assert r["macbook_neo"]["min_price"] == 142000

def test_macbook_neo_russian():
    r = match_products([msg("@ch", "Макбук Нео 141 000 руб")], [MACBOOK_NEO])
    assert r["macbook_neo"]["min_price"] == 141000

def test_macbook_neo_k():
    r = match_products([msg("@ch", "MacBook Neo 143к")], [MACBOOK_NEO])
    assert r["macbook_neo"]["min_price"] == 143000

def test_airpods_pro3():
    r = match_products([msg("@ch", "AirPods Pro3 18500 rub")], [AIRPODS_PRO_3])
    assert r["airpods_pro_3"]["min_price"] == 18500

def test_airpods_pro_3_russian():
    r = match_products([msg("@ch", "Аирподс Про 3 — 17900 руб")], [AIRPODS_PRO_3])
    assert r["airpods_pro_3"]["min_price"] == 17900

def test_ps5_english():
    r = match_products([msg("@ch", "PS5 — 46000 rub")], [PS5])
    assert r["ps5"]["min_price"] == 46000

def test_ps5_russian():
    r = match_products([msg("@ch", "ПС5 47000 рублей")], [PS5])
    assert r["ps5"]["min_price"] == 47000

def test_ps5_playstation():
    r = match_products([msg("@ch", "PlayStation 5 — 46500 rub")], [PS5])
    assert r["ps5"]["min_price"] == 46500

def test_watch_s11_english():
    r = match_products([msg("@ch", "Apple Watch S11 — 38000 rub")], [WATCH_S11])
    assert r["apple_watch_s11"]["min_price"] == 38000

def test_watch_s11_cyrillic_s():
    r = match_products([msg("@ch", "Watch С11 — 37500 руб")], [WATCH_S11])
    assert r["apple_watch_s11"]["min_price"] == 37500

def test_watch_series_11():
    r = match_products([msg("@ch", "Apple Watch Series 11 38500 rub")], [WATCH_S11])
    assert r["apple_watch_s11"]["min_price"] == 38500

def test_whoop():
    r = match_products([msg("@ch", "Whoop 5.0 Peak 34000 rub")], [WHOOP])
    assert r["whoop_50"]["min_price"] == 34000

def test_pro_1tb():
    r = match_products([msg("@ch", "iPhone 17 Pro 1 TB — 104000 rub")], [PRO_1TB])
    assert r["iphone_pro_1tb"]["min_price"] == 104000

def test_pro_1tb_not_matched_by_max():
    r = match_products([msg("@ch", "iPhone 17 Pro Max 1 TB — 117000 rub")], [PRO_1TB])
    assert r["iphone_pro_1tb"]["min_price"] is None


# ── Multi-product message ──────────────────────────────────────────────────────

def test_full_price_list_message():
    text = (
        "iPhone 17 Pro 256 GB — 84500 rub\n"
        "iPhone 17 Pro Max 256 GB — 95000 rub\n"
        "MacBook Neo — 142000 rub\n"
        "PS5 — 46000 rub\n"
        "Apple Watch S11 — 38000 rub\n"
    )
    r = match_products([msg("@ch", text)], ALL_PRODUCTS)
    assert r["iphone_pro_256"]["min_price"] == 84500
    assert r["iphone_pro_max_256"]["min_price"] == 95000
    assert r["macbook_neo"]["min_price"] == 142000
    assert r["ps5"]["min_price"] == 46000
    assert r["apple_watch_s11"]["min_price"] == 38000
