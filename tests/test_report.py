import pytest
from src.report import build_price_list, build_report


# ── Helpers ────────────────────────────────────────────────────────────────────

def result(key, canonical, price, old=None, delta=0, large=False, kept=False, competitor=None, channel=None):
    return {
        "db_id": 1,
        "template_key": key,
        "canonical_name": canonical,
        "display_name": canonical,
        "category": "iPhone",
        "old_price": old,
        "competitor_price": competitor,
        "source_channel": channel,
        "calculated_price": price,
        "price_delta": delta,
        "is_large_change": large,
        "price_kept": kept,
    }


TEMPLATE = (
    "Any tech 🔥\n"
    "• Pro 256 GB — {iphone_pro_256} RUB\n"
    "• MacBook Neo — {macbook_neo} RUB\n"
)


# ── build_price_list ───────────────────────────────────────────────────────────

def test_price_list_fills_placeholder():
    results = [result("iphone_pro_256", "iPhone Pro 256 GB", 84500)]
    text = build_price_list(results, "Pro 256 — {iphone_pro_256} RUB")
    assert "84 500" in text


def test_price_list_missing_shows_dash():
    results = [result("iphone_pro_256", "iPhone Pro 256 GB", None, kept=True)]
    text = build_price_list(results, "Pro 256 — {iphone_pro_256} RUB")
    assert "—" in text


def test_price_list_multiple_placeholders():
    results = [
        result("iphone_pro_256", "iPhone Pro 256 GB", 84500),
        result("macbook_neo", "MacBook Neo", 142000),
    ]
    text = build_price_list(results, TEMPLATE)
    assert "84 500" in text
    assert "142 000" in text


def test_price_list_large_number_formatted():
    results = [result("iphone_pro_256", "A", 142000)]
    text = build_price_list(results, "{iphone_pro_256}")
    assert "142 000" in text


def test_price_list_unknown_key_returns_template():
    results = [result("other_key", "Other", 50000)]
    template = "Price: {iphone_pro_256}"
    text = build_price_list(results, template)
    assert text == template  # key missing → original template returned unchanged


# ── build_report — header ──────────────────────────────────────────────────────

def test_report_contains_timestamp():
    report = build_report([], [], [], "2026-05-04T09:00:12", [])
    assert "2026-05-04 09:00" in report


def test_report_found_count():
    results = [
        result("p1", "Product A", 84500, old=84000, delta=500),
        result("p2", "Product B", None, kept=True),
    ]
    report = build_report(results, [], ["@ch1"], "2026-05-04T09:00:00", [])
    assert "1 / 2" in report


def test_report_all_found():
    results = [result("p1", "A", 84500, old=84000)]
    report = build_report(results, [], ["@ch1"], "2026-05-04T09:00:00", [])
    assert "1 / 1" in report


# ── build_report — missing products ───────────────────────────────────────────

def test_report_missing_listed_by_name():
    results = [result("p1", "iPhone Pro 256 GB", None, kept=True)]
    report = build_report(results, [], ["@ch"], "2026-05-04T09:00:00", [])
    assert "iPhone Pro 256 GB" in report
    assert "Missing" in report


def test_report_no_missing_line_when_all_found():
    results = [result("p1", "A", 84500, old=84000)]
    report = build_report(results, [], ["@ch"], "2026-05-04T09:00:00", [])
    assert "Missing" not in report


# ── build_report — channels ────────────────────────────────────────────────────

def test_report_channel_ok():
    report = build_report([], [], ["@ch1"], "2026-05-04T09:00:00", [])
    assert "@ch1 — OK" in report


def test_report_channel_unavailable():
    report = build_report([], ["@ch_bad"], ["@ch_bad"], "2026-05-04T09:00:00", [])
    assert "UNAVAILABLE" in report


def test_report_mixed_channel_status():
    report = build_report([], ["@bad"], ["@good", "@bad"], "2026-05-04T09:00:00", [])
    assert "@good — OK" in report
    assert "@bad — UNAVAILABLE" in report


# ── build_report — price changes ──────────────────────────────────────────────

def test_report_price_decrease():
    results = [result("p1", "Product A", 81500, old=90000, delta=-8500)]
    report = build_report(results, [], ["@ch"], "2026-05-04T09:00:00", [])
    assert "90 000" in report
    assert "81 500" in report
    assert "−" in report or "-" in report


def test_report_no_change():
    results = [result("p1", "Product A", 84500, old=84500, delta=0)]
    report = build_report(results, [], ["@ch"], "2026-05-04T09:00:00", [])
    assert "no change" in report


def test_report_large_change_flag():
    results = [result("p1", "Product A", 81500, old=90000, delta=-8500, large=True)]
    report = build_report(results, [], ["@ch"], "2026-05-04T09:00:00", [])
    assert "LARGE CHANGE" in report


def test_report_small_change_no_flag():
    results = [result("p1", "Product A", 84500, old=84000, delta=500, large=False)]
    report = build_report(results, [], ["@ch"], "2026-05-04T09:00:00", [])
    assert "LARGE CHANGE" not in report


def test_report_first_run_no_old_price():
    results = [result("p1", "Product A", 84500, old=None, delta=0)]
    report = build_report(results, [], ["@ch"], "2026-05-04T09:00:00", [])
    assert "first run" in report


# ── build_report — errors ─────────────────────────────────────────────────────

def test_report_no_errors():
    report = build_report([], [], [], "2026-05-04T09:00:00", [])
    assert "Errors: none" in report


def test_report_with_error():
    report = build_report([], [], [], "2026-05-04T09:00:00", ["channel timeout on @ch1"])
    assert "channel timeout on @ch1" in report
    assert "Errors: none" not in report


def test_report_multiple_errors():
    report = build_report([], [], [], "2026-05-04T09:00:00", ["err1", "err2"])
    assert "err1" in report
    assert "err2" in report
