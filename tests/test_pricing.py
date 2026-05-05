import pytest
from src.pricing import calculate_prices


def product(template_key, canonical, current_price=None, db_id=1, category="iPhone", display_name=None):
    return {
        "id": db_id,
        "template_key": template_key,
        "canonical_name": canonical,
        "display_name": display_name or canonical,
        "category": category,
        "current_price": current_price,
        "previous_price": None,
    }


def match(min_price, channel="@ch"):
    return {"min_price": min_price, "source_channel": channel, "all_prices": [min_price] if min_price else []}


def match_prices(prices, channel="@ch"):
    return {
        "min_price": min(prices) if prices else None,
        "average_price": round(sum(prices) / len(prices)) if prices else None,
        "source_channel": channel,
        "all_prices": prices,
    }


# ── Discount rule ──────────────────────────────────────────────────────────────

def test_calculated_price_is_competitor_minus_discount():
    products = [product("p1", "Product A", current_price=84000)]
    results = calculate_prices({"p1": match(85000)}, products, discount=500)
    assert results[0]["calculated_price"] == 84500


def test_custom_discount():
    products = [product("p1", "Product A", current_price=0)]
    results = calculate_prices({"p1": match(90000)}, products, discount=1000)
    assert results[0]["calculated_price"] == 89000


def test_uses_min_competitor_price_for_color_variants():
    products = [product("p1", "Product A", current_price=0)]
    results = calculate_prices({"p1": match_prices([99990, 99990, 106990])}, products, discount=500)
    assert results[0]["competitor_price"] == 99990
    assert results[0]["calculated_price"] == 99490


def test_price_not_found_keeps_old():
    products = [product("p1", "Product A", current_price=84000)]
    results = calculate_prices({"p1": match(None)}, products)
    r = results[0]
    assert r["price_kept"] is True
    assert r["calculated_price"] == 84000
    assert r["competitor_price"] is None


def test_price_not_found_old_also_none():
    products = [product("p1", "Product A", current_price=None)]
    results = calculate_prices({"p1": match(None)}, products)
    r = results[0]
    assert r["price_kept"] is True
    assert r["calculated_price"] is None


def test_no_match_key_treated_as_not_found():
    products = [product("p1", "Product A", current_price=84000)]
    results = calculate_prices({}, products)
    assert results[0]["price_kept"] is True
    assert results[0]["calculated_price"] == 84000


# ── Delta calculation ──────────────────────────────────────────────────────────

def test_delta_positive_when_price_rises():
    products = [product("p1", "A", current_price=80000)]
    results = calculate_prices({"p1": match(85000)}, products)
    assert results[0]["price_delta"] == 4500  # 84500 - 80000


def test_delta_negative_when_price_falls():
    products = [product("p1", "A", current_price=90000)]
    results = calculate_prices({"p1": match(82000)}, products)
    assert results[0]["price_delta"] == -8500  # 81500 - 90000


def test_delta_zero_first_run():
    products = [product("p1", "A", current_price=None)]
    results = calculate_prices({"p1": match(85000)}, products)
    assert results[0]["price_delta"] == 0


def test_delta_zero_no_change():
    products = [product("p1", "A", current_price=84500)]
    results = calculate_prices({"p1": match(85000)}, products)
    assert results[0]["price_delta"] == 0


# ── Large change flag ──────────────────────────────────────────────────────────

def test_large_change_flagged():
    products = [product("p1", "A", current_price=90000)]
    results = calculate_prices({"p1": match(82000)}, products, large_change_threshold=3000)
    assert results[0]["is_large_change"] is True  # |−8500| > 3000


def test_small_change_not_flagged():
    products = [product("p1", "A", current_price=84000)]
    results = calculate_prices({"p1": match(85000)}, products, large_change_threshold=3000)
    assert results[0]["is_large_change"] is False  # |500| < 3000


def test_exactly_threshold_not_flagged():
    products = [product("p1", "A", current_price=81500)]
    results = calculate_prices({"p1": match(85000)}, products, large_change_threshold=3000)
    assert results[0]["is_large_change"] is False  # |3000| not > 3000


def test_just_above_threshold_flagged():
    products = [product("p1", "A", current_price=81499)]
    results = calculate_prices({"p1": match(85000)}, products, large_change_threshold=3000)
    assert results[0]["is_large_change"] is True  # |3001| > 3000


def test_large_change_up_also_flagged():
    products = [product("p1", "A", current_price=80000)]
    results = calculate_prices({"p1": match(90000)}, products, large_change_threshold=3000)
    assert results[0]["is_large_change"] is True  # |+9000| > 3000


# ── Output fields ──────────────────────────────────────────────────────────────

def test_source_channel_preserved():
    products = [product("p1", "A", current_price=0)]
    results = calculate_prices({"p1": match(85000, "@mychannel")}, products)
    assert results[0]["source_channel"] == "@mychannel"


def test_source_channel_none_when_kept():
    products = [product("p1", "A", current_price=84000)]
    results = calculate_prices({"p1": match(None)}, products)
    assert results[0]["source_channel"] is None


def test_category_and_display_name_passed_through():
    products = [product("p1", "iPhone Pro 256 GB", category="iPhone", display_name="Pro 256 GB")]
    results = calculate_prices({"p1": match(85000)}, products)
    assert results[0]["category"] == "iPhone"
    assert results[0]["display_name"] == "Pro 256 GB"


def test_result_order_matches_products_order():
    products = [
        product("b", "Product B", current_price=None, db_id=2),
        product("a", "Product A", current_price=None, db_id=1),
    ]
    results = calculate_prices({"a": match(85000), "b": match(90000)}, products)
    assert results[0]["template_key"] == "b"
    assert results[1]["template_key"] == "a"


# ── Multiple products ──────────────────────────────────────────────────────────

def test_multiple_products_mixed():
    products = [
        product("p1", "Product A", current_price=84000, db_id=1),
        product("p2", "Product B", current_price=90000, db_id=2),
        product("p3", "Product C", current_price=50000, db_id=3),
    ]
    match_results = {
        "p1": match(85000),
        "p2": match(None),
        # p3 not in results at all
    }
    results = calculate_prices(match_results, products)
    assert results[0]["calculated_price"] == 84500
    assert results[0]["price_kept"] is False
    assert results[1]["price_kept"] is True
    assert results[2]["price_kept"] is True
