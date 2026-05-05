import sqlite3
from types import SimpleNamespace

import src.db as db


def settings_with_products(*products):
    return SimpleNamespace(
        products=list(products),
        channels=[],
        admins=[],
        pricing=SimpleNamespace(discount=500),
    )


def product(key, canonical, default_price):
    return SimpleNamespace(
        id=key,
        canonical=canonical,
        category="iPhone",
        display_name=canonical,
        default_price=default_price,
    )


def rows(path, table):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def test_init_stores_defaults_and_live_prices_in_dedicated_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 99490)))

    defaults = rows(db_path, "product_default_prices")
    live_prices = rows(db_path, "product_prices")
    products = db.get_all_products()

    assert defaults[0]["default_price"] == 99490
    assert live_prices[0]["current_price"] == 99490
    assert products[0]["default_price"] == 99490
    assert products[0]["current_price"] == 99490


def test_update_product_price_updates_live_table_without_changing_default(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 99490)))

    item = db.get_product_by_identifier("iphone_pro_256")
    db.update_product_price(item["id"], 101000)

    products = db.get_all_products()
    defaults = rows(db_path, "product_default_prices")
    live_prices = rows(db_path, "product_prices")

    assert products[0]["default_price"] == 99490
    assert products[0]["current_price"] == 101000
    assert defaults[0]["default_price"] == 99490
    assert live_prices[0]["current_price"] == 101000
    assert live_prices[0]["previous_price"] == 99490


def test_reset_product_price_restores_default(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 99490)))

    item = db.get_product_by_identifier("iPhone Pro 256")
    db.update_product_price(item["id"], 101000)
    reset_to = db.reset_product_price(item["id"])

    products = db.get_all_products()
    assert reset_to == 99490
    assert products[0]["current_price"] == 99490
    assert products[0]["previous_price"] == 101000


def test_reseed_changes_default_without_overwriting_manual_live_price(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 99490)))
    item = db.get_product_by_identifier("iphone_pro_256")
    db.update_product_price(item["id"], 101000)

    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 97990)))

    products = db.get_all_products()
    assert products[0]["default_price"] == 97990
    assert products[0]["current_price"] == 101000


def test_pending_price_change_can_be_marked_for_manual_and_fetched(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 99490)))

    item = db.get_product_by_identifier("iphone_pro_256")
    change_id = db.create_pending_price_change(1, item["id"], 101000, 99490)
    db.mark_pending_price_change_for_manual(change_id, admin_id=777)

    change = db.get_pending_manual_price_change_for_admin(777)
    assert change is not None
    assert change["id"] == change_id
    assert change["status"] == "awaiting_manual"


def test_pipeline_wait_tracks_step_3_until_pending_changes_resolved(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 99490)))

    run_id = db.create_run()
    item = db.get_product_by_identifier("iphone_pro_256")
    change_id = db.create_pending_price_change(run_id, item["id"], 95000, 99490)
    db.mark_run_waiting(run_id)
    db.create_pipeline_wait(run_id, chat_id=12345, step="step_3")

    wait = db.get_waiting_pipeline_for_run(run_id)
    assert wait["chat_id"] == 12345
    assert db.count_unresolved_price_changes_for_run(run_id) == 1

    db.resolve_pending_price_change(change_id, "approved", resolved_by=777)
    assert db.count_unresolved_price_changes_for_run(run_id) == 0

    db.resolve_pipeline_wait(run_id)
    assert db.get_waiting_pipeline_for_run(run_id) is None


def test_preserved_price_change_counts_as_resolved(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init(settings_with_products(product("iphone_pro_256", "iPhone Pro 256", 99490)))

    run_id = db.create_run()
    item = db.get_product_by_identifier("iphone_pro_256")
    change_id = db.create_pending_price_change(run_id, item["id"], 95000, 99490)

    assert db.count_unresolved_price_changes_for_run(run_id) == 1
    db.resolve_pending_price_change(change_id, "preserved", resolved_by=777)
    assert db.count_unresolved_price_changes_for_run(run_id) == 0
