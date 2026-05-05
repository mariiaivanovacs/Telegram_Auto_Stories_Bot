from src.bot.handlers.pipeline import (
    _format_large_change_confirmation,
    _format_matched_line_calculations,
    _parse_price_input,
)


def test_parse_price_input_accepts_plain_number():
    assert _parse_price_input("99990") == 99990


def test_parse_price_input_accepts_spaces_and_ruble_sign():
    assert _parse_price_input("99 990 ₽") == 99990


def test_parse_price_input_returns_none_without_digits():
    assert _parse_price_input("price") is None


def test_large_change_confirmation_includes_source_and_quote():
    result = {
        "canonical_name": "iPhone Pro 256 GB",
        "source_channel": "adsapple",
        "competitor_price": 99990,
        "old_price": 94500,
        "calculated_price": 99490,
        "price_delta": 4990,
    }
    match = {
        "matched_lines": [
            {
                "channel": "adsapple",
                "original_text": "iPhone 17 Pro 256 GB - 99 990 ₽",
                "text": "iphone 17 pro 256 gb - 99 990 rub",
                "price": 99990,
            }
        ]
    }
    text = _format_large_change_confirmation(result, match)
    assert "@adsapple" in text
    assert '"iPhone 17 Pro 256 GB - 99 990 ₽"' in text


def test_matched_line_calculations_grouped_by_channel():
    match_results = {
        "p1": {
            "matched_lines": [
                {"channel": "adsapple", "original_text": "Line A", "text": "line a", "price": 100000},
                {"channel": "adsapple", "original_text": "Line B", "text": "line b", "price": 101000},
                {"channel": "otherchan", "original_text": "Line C", "text": "line c", "price": 102000},
            ]
        }
    }
    lines = _format_matched_line_calculations(match_results, 500)
    assert lines[0] == "@adsapple"
    assert lines[1].startswith("1. Line A")
    assert lines[2].startswith("2. Line B")
    assert "@otherchan" in lines
