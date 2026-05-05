"""
Smoke tests: verify every module imports cleanly and exposes its public API.
No network, no DB, no Telegram credentials required.
"""
import importlib

import pytest


MODULES = [
    "src.config",
    "src.db",
    "src.parser",
    "src.matcher",
    "src.pricing",
    "src.report",
    "src.story",
    "src.lock",
    "src.fetcher",
    "src.sender",
    "src.bot",
    "src.main",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    mod = importlib.import_module(module)
    assert mod is not None


# ── Public API surface checks ──────────────────────────────────────────────────

def test_config_get_settings_callable():
    from src.config import get_settings
    assert callable(get_settings)


def test_parser_normalize_callable():
    from src.parser import normalize
    assert callable(normalize)
    text, segs = normalize("iPhone Pro 256 — 84500 rub")
    assert isinstance(text, str)
    assert isinstance(segs, list)


def test_matcher_match_products_callable():
    from src.matcher import match_products
    assert callable(match_products)


def test_pricing_calculate_prices_callable():
    from src.pricing import calculate_prices
    assert callable(calculate_prices)


def test_report_build_price_list_callable():
    from src.report import build_price_list, build_report
    assert callable(build_price_list)
    assert callable(build_report)


def test_story_generate_stories_callable():
    from src.story import generate_stories
    assert callable(generate_stories)


def test_lock_api():
    from src.lock import acquire, release, is_locked
    assert callable(acquire)
    assert callable(release)
    assert callable(is_locked)


def test_db_api():
    import src.db as db
    assert callable(db.init)
    assert callable(db.create_run)
    assert callable(db.finish_run)
    assert callable(db.get_last_run)
    assert callable(db.get_all_products)
    assert callable(db.update_product_price)
    assert callable(db.write_price_history)
    assert callable(db.is_admin)
    assert callable(db.add_admin)


def test_sender_api():
    from src.sender import send_all, notify_admin
    assert callable(send_all)
    assert callable(notify_admin)


def test_fetcher_api():
    from src.fetcher import fetch_messages
    assert callable(fetch_messages)


def test_bot_run_bot_callable():
    from src.bot import run_bot
    assert callable(run_bot)


def test_main_run_pipeline_callable():
    from src.main import run_pipeline
    assert callable(run_pipeline)
