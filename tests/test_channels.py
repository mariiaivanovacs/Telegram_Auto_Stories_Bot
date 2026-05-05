import sqlite3
from types import SimpleNamespace

import src.db as db
import src.lock as lock
import src.main as main
from src.fetcher import _is_relevant_message


def settings_with_channels(*channels):
    return SimpleNamespace(
        products=[],
        channels=list(channels),
        admins=[],
        pricing=SimpleNamespace(discount=500),
    )


def channel(username, display_name=""):
    return SimpleNamespace(username=username.strip().lstrip("@"), display_name=display_name)


def test_init_seeds_active_channels_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "prices.db")

    db.init(settings_with_channels(channel("@one", "One"), channel("two", "Two")))

    channels = db.get_active_channels()
    assert [ch["username"] for ch in channels] == ["one", "two"]
    assert channels[0]["display_name"] == "One"


def test_upsert_channel_adds_and_reactivates(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "prices.db")
    db.init(settings_with_channels())

    added = db.upsert_channel("@new_channel", "New Channel")
    db.deactivate_channel("new_channel")
    reactivated = db.upsert_channel("new_channel", "Updated Name")

    assert added["username"] == "new_channel"
    assert reactivated["id"] == added["id"]
    assert reactivated["display_name"] == "Updated Name"
    assert db.has_active_channels() is True


def test_update_channel_changes_username_and_display_name(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "prices.db")
    db.init(settings_with_channels(channel("old_channel", "Old")))

    existing = db.get_channel_by_identifier("old_channel")
    updated = db.update_channel(existing["id"], username="@new_channel", display_name="New")

    assert updated["username"] == "new_channel"
    assert updated["display_name"] == "New"
    assert db.get_channel_id("new_channel") == existing["id"]


def test_deactivate_channel_removes_from_active_list(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "prices.db")
    db.init(settings_with_channels(channel("one", "One")))

    removed = db.deactivate_channel("one")

    assert removed["username"] == "one"
    assert db.get_active_channels() == []
    assert db.has_active_channels() is False
    assert db.get_all_channels()[0]["is_active"] == 0


def test_run_pipeline_stops_before_fetch_when_no_active_channels(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "prices.db")
    monkeypatch.setattr(lock, "PATH", tmp_path / ".run_lock")
    monkeypatch.setattr(main, "get_settings", lambda: settings_with_channels())
    messages = []

    main.run_pipeline(progress_cb=messages.append)

    assert any("активных каналов" in msg for msg in messages)
    assert db.get_last_run() is None


def test_channel_migration_merges_at_prefixed_duplicates(tmp_path, monkeypatch):
    db_path = tmp_path / "prices.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init(settings_with_channels(channel("adsapple", "ADS KZN")))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO channels (username, display_name, is_active) VALUES (?, ?, 1)",
            ("@adsapple", "ADS KZN"),
        )
        conn.commit()
    finally:
        conn.close()

    db.init(settings_with_channels(channel("adsapple", "ADS KZN")))

    channels = db.get_active_channels()
    assert len(channels) == 1
    assert channels[0]["username"] == "adsapple"


def test_fetch_filter_skips_old_iphone_generations():
    assert _is_relevant_message("iPhone 14 Pro Max 256 — 75 000 руб") is False
    assert _is_relevant_message("Айфон 13 — 45 000 руб") is False


def test_fetch_filter_keeps_iphone_17_and_other_targets():
    assert _is_relevant_message("iPhone 17 Pro 256 — 99 990 руб") is True
    assert _is_relevant_message("iPhone 14 Pro и MacBook Neo — 142 000 руб") is True
