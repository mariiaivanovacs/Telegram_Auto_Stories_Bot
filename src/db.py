import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("data/prices.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT    NOT NULL UNIQUE,
    template_key   TEXT    NOT NULL UNIQUE,
    category       TEXT    NOT NULL,
    display_name   TEXT    NOT NULL,
    default_price  INTEGER,
    current_price  INTEGER,
    previous_price INTEGER,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS product_default_prices (
    product_id    INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    default_price INTEGER,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_prices (
    product_id      INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    current_price   INTEGER,
    previous_price  INTEGER,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT    NOT NULL,
    finished_at      TEXT,
    status           TEXT    NOT NULL DEFAULT 'running',
    products_found   INTEGER DEFAULT 0,
    products_missing INTEGER DEFAULT 0,
    errors           TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    display_name    TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    last_fetch_at   TEXT,
    last_message_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS admins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    username    TEXT,
    added_by    INTEGER,
    added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL REFERENCES channels(id),
    message_id   INTEGER NOT NULL,
    message_text TEXT,
    message_date TEXT    NOT NULL,
    run_id       INTEGER REFERENCES runs(id),
    processed    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(channel_id, message_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id),
    product_id       INTEGER NOT NULL REFERENCES products(id),
    competitor_price INTEGER,
    source_channel   TEXT,
    calculated_price INTEGER,
    price_delta      INTEGER,
    is_large_change  INTEGER DEFAULT 0,
    price_kept       INTEGER DEFAULT 0,
    created_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_price_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    proposed_price  INTEGER NOT NULL,
    old_price       INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    resolved_at     TEXT,
    resolved_by     INTEGER,
    manual_price    INTEGER,
    manual_requested_by INTEGER,
    manual_requested_at TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_waits (
    run_id      INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    chat_id     INTEGER NOT NULL,
    step        TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'waiting',
    created_at  TEXT    NOT NULL,
    resumed_at  TEXT
);
"""


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Init ───────────────────────────────────────────────────────────────────────

def init(settings) -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)

        for p in settings.products:
            conn.execute("""
                INSERT INTO products (canonical_name, template_key, category, display_name, default_price, current_price)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_key) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    category = excluded.category,
                    display_name = excluded.display_name,
                    default_price = excluded.default_price,
                    current_price = COALESCE(products.current_price, excluded.current_price)
            """, (p.canonical, p.id, p.category, p.display_name, p.default_price, p.default_price))
            product_id = conn.execute(
                "SELECT id FROM products WHERE template_key = ?", (p.id,)
            ).fetchone()["id"]
            conn.execute("""
                INSERT INTO product_default_prices (product_id, default_price, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    default_price = excluded.default_price,
                    updated_at = excluded.updated_at
            """, (product_id, p.default_price, _now()))
            conn.execute("""
                INSERT INTO product_prices (product_id, current_price, previous_price, updated_at)
                VALUES (?, ?, NULL, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    current_price = COALESCE(product_prices.current_price, excluded.current_price),
                    updated_at = COALESCE(product_prices.updated_at, excluded.updated_at)
            """, (product_id, p.default_price, _now()))

        for c in settings.channels:
            username = _normalize_channel_username(c.username)
            conn.execute("""
                INSERT INTO channels (username, display_name)
                VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET display_name = excluded.display_name
            """, (username, c.display_name))

        for a in settings.admins:
            conn.execute("""
                INSERT INTO admins (telegram_id, username, added_at)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username
            """, (a.telegram_id, a.username, _now()))

        conn.execute("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('pricing_discount', ?, ?)
            ON CONFLICT(key) DO NOTHING
        """, (str(settings.pricing.discount), _now()))

    logger.info("Database initialised at %s", DB_PATH)


def _migrate(conn: sqlite3.Connection) -> None:
    product_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(products)").fetchall()
    }
    if "default_price" not in product_cols:
        conn.execute("ALTER TABLE products ADD COLUMN default_price INTEGER")
        product_cols.add("default_price")
    if "current_price" not in product_cols:
        conn.execute("ALTER TABLE products ADD COLUMN current_price INTEGER")
        product_cols.add("current_price")
    if "previous_price" not in product_cols:
        conn.execute("ALTER TABLE products ADD COLUMN previous_price INTEGER")
        product_cols.add("previous_price")
    if "updated_at" not in product_cols:
        conn.execute("ALTER TABLE products ADD COLUMN updated_at TEXT")

    conn.execute("""
        INSERT INTO product_default_prices (product_id, default_price, updated_at)
        SELECT id, default_price, COALESCE(updated_at, ?)
        FROM products
        WHERE id NOT IN (SELECT product_id FROM product_default_prices)
    """, (_now(),))
    conn.execute("""
        INSERT INTO product_prices (product_id, current_price, previous_price, updated_at)
        SELECT id, COALESCE(current_price, default_price), previous_price, COALESCE(updated_at, ?)
        FROM products
        WHERE id NOT IN (SELECT product_id FROM product_prices)
    """, (_now(),))
    pending_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(pending_price_changes)").fetchall()
    }
    if "manual_requested_by" not in pending_cols:
        conn.execute("ALTER TABLE pending_price_changes ADD COLUMN manual_requested_by INTEGER")
    if "manual_requested_at" not in pending_cols:
        conn.execute("ALTER TABLE pending_price_changes ADD COLUMN manual_requested_at TEXT")
    _migrate_channel_usernames(conn)


def _migrate_channel_usernames(conn: sqlite3.Connection) -> None:
    rows = conn.execute("""
        SELECT id, username, display_name, is_active, last_fetch_at, last_message_id
        FROM channels
        ORDER BY id
    """).fetchall()
    by_normalized: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        normalized = _normalize_channel_username(row["username"])
        if not normalized:
            continue
        by_normalized.setdefault(normalized, []).append(row)

    for normalized, group in by_normalized.items():
        keep = min(group, key=lambda row: row["id"])
        duplicates = [row for row in group if row["id"] != keep["id"]]
        display_name = next((row["display_name"] for row in group if row["display_name"]), "")
        is_active = 1 if any(row["is_active"] for row in group) else 0
        last_fetch_at = max(
            [row["last_fetch_at"] for row in group if row["last_fetch_at"]],
            default=keep["last_fetch_at"],
        )
        last_message_id = max(row["last_message_id"] or 0 for row in group)

        for duplicate in duplicates:
            conn.execute("""
                UPDATE OR IGNORE raw_messages
                SET channel_id = ?
                WHERE channel_id = ?
            """, (keep["id"], duplicate["id"]))
            conn.execute("DELETE FROM raw_messages WHERE channel_id = ?", (duplicate["id"],))
            conn.execute("DELETE FROM channels WHERE id = ?", (duplicate["id"],))

        conn.execute("""
            UPDATE channels
            SET username = ?, display_name = ?, is_active = ?,
                last_fetch_at = ?, last_message_id = ?
            WHERE id = ?
        """, (
            normalized,
            display_name,
            is_active,
            last_fetch_at,
            last_message_id,
            keep["id"],
        ))


# ── Admins ─────────────────────────────────────────────────────────────────────

def is_admin(telegram_id: int) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM admins WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row is not None


def add_admin(telegram_id: int, username: str, added_by: int) -> bool:
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO admins (telegram_id, username, added_by, added_at) VALUES (?, ?, ?, ?)",
                (telegram_id, username, added_by, _now()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_all_admins() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT telegram_id, username, added_at FROM admins"
        ).fetchall()
        return [dict(r) for r in rows]


def remove_admin(telegram_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM admins WHERE telegram_id = ?", (telegram_id,))
        return cur.rowcount > 0


# ── Runtime settings ───────────────────────────────────────────────────────────

def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default
    except sqlite3.OperationalError:
        return default


def set_setting(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (key, value, _now()))


def get_pricing_discount(default: int = 500) -> int:
    raw = get_setting("pricing_discount", str(default))
    try:
        return int(raw or default)
    except ValueError:
        return default


def set_pricing_discount(value: int) -> None:
    set_setting("pricing_discount", str(value))


def get_max_posts(default: int = 10) -> int:
    raw = get_setting("max_posts_per_channel", str(default))
    try:
        return max(1, min(30, int(raw or default)))
    except ValueError:
        return default


def set_max_posts(value: int) -> None:
    set_setting("max_posts_per_channel", str(max(1, min(30, value))))


def get_schedule_weekday(default: str = "mon") -> str:
    return get_setting("schedule_weekday", default) or default


def get_schedule_time(default: str = "09:00") -> str:
    return get_setting("schedule_time", default) or default


def set_schedule_weekday(value: str) -> None:
    set_setting("schedule_weekday", value)


def set_schedule_time(value: str) -> None:
    set_setting("schedule_time", value)


def get_story_design(default: int = 1) -> int:
    raw = get_setting("story_design", str(default))
    try:
        return max(1, min(3, int(raw or default)))
    except ValueError:
        return default


def set_story_design(value: int) -> None:
    set_setting("story_design", str(max(1, min(3, value))))


# ── Runs ───────────────────────────────────────────────────────────────────────

def create_run() -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')", (_now(),)
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, found: int, missing: int, errors: list[str]) -> None:
    with _conn() as conn:
        conn.execute("""
            UPDATE runs
            SET finished_at = ?, status = ?, products_found = ?, products_missing = ?, errors = ?
            WHERE id = ?
        """, (_now(), status, found, missing, json.dumps(errors), run_id))


def mark_run_waiting(run_id: int, status: str = "awaiting_approval") -> None:
    with _conn() as conn:
        conn.execute("""
            UPDATE runs
            SET status = ?, finished_at = NULL
            WHERE id = ?
        """, (status, run_id))


def get_last_run() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE status IN ('success','partial') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def create_pipeline_wait(run_id: int, chat_id: int, step: str) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO pipeline_waits (run_id, chat_id, step, status, created_at)
            VALUES (?, ?, ?, 'waiting', ?)
            ON CONFLICT(run_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                step = excluded.step,
                status = 'waiting',
                resumed_at = NULL
        """, (run_id, chat_id, step, _now()))


def get_waiting_pipeline_for_run(run_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("""
            SELECT * FROM pipeline_waits
            WHERE run_id = ? AND status = 'waiting'
        """, (run_id,)).fetchone()
        return dict(row) if row else None


def get_latest_waiting_pipeline() -> dict | None:
    with _conn() as conn:
        row = conn.execute("""
            SELECT pw.*, r.status AS run_status
            FROM pipeline_waits pw
            JOIN runs r ON r.id = pw.run_id
            WHERE pw.status = 'waiting'
              AND r.status = 'awaiting_approval'
            ORDER BY pw.created_at DESC
            LIMIT 1
        """).fetchone()
        return dict(row) if row else None


def resolve_pipeline_wait(run_id: int) -> None:
    with _conn() as conn:
        conn.execute("""
            UPDATE pipeline_waits
            SET status = 'resumed', resumed_at = ?
            WHERE run_id = ? AND status = 'waiting'
        """, (_now(), run_id))


# ── Channels ───────────────────────────────────────────────────────────────────

def get_channel_id(username: str) -> int | None:
    username = _normalize_channel_username(username)
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM channels WHERE username = ?", (username,)
        ).fetchone()
        return row["id"] if row else None


def get_active_channels() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT id, username, display_name, is_active, last_fetch_at, last_message_id
            FROM channels
            WHERE is_active = 1
            ORDER BY id
        """).fetchall()
        return [dict(r) for r in rows]


def get_all_channels() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT id, username, display_name, is_active, last_fetch_at, last_message_id
            FROM channels
            ORDER BY is_active DESC, id
        """).fetchall()
        return [dict(r) for r in rows]


def has_active_channels() -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM channels WHERE is_active = 1 LIMIT 1"
        ).fetchone()
        return row is not None


def upsert_channel(username: str, display_name: str = "") -> dict:
    username = _normalize_channel_username(username)
    display_name = display_name.strip()
    if not username:
        raise ValueError("Channel username cannot be empty")
    with _conn() as conn:
        conn.execute("""
            INSERT INTO channels (username, display_name, is_active)
            VALUES (?, ?, 1)
            ON CONFLICT(username) DO UPDATE SET
                display_name = excluded.display_name,
                is_active = 1
        """, (username, display_name))
        row = conn.execute(
            "SELECT * FROM channels WHERE username = ?", (username,)
        ).fetchone()
        return dict(row)


def update_channel(
    channel_id: int,
    username: str | None = None,
    display_name: str | None = None,
) -> dict | None:
    existing = get_channel_by_id(channel_id)
    if not existing:
        return None
    new_username = (
        _normalize_channel_username(username)
        if username is not None
        else existing["username"]
    )
    new_display = display_name.strip() if display_name is not None else (existing["display_name"] or "")
    if not new_username:
        raise ValueError("Channel username cannot be empty")

    with _conn() as conn:
        conn.execute("""
            UPDATE channels
            SET username = ?, display_name = ?
            WHERE id = ?
        """, (new_username, new_display, channel_id))
        row = conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None


def toggle_channel(channel_id: int) -> dict | None:
    channel = get_channel_by_id(channel_id)
    if not channel:
        return None
    new_active = 0 if channel["is_active"] else 1
    with _conn() as conn:
        conn.execute("UPDATE channels SET is_active = ? WHERE id = ?", (new_active, channel_id))
    channel["is_active"] = new_active
    return channel


def deactivate_channel(identifier: str) -> dict | None:
    channel = get_channel_by_identifier(identifier)
    if not channel:
        return None
    with _conn() as conn:
        conn.execute("UPDATE channels SET is_active = 0 WHERE id = ?", (channel["id"],))
    channel["is_active"] = 0
    return channel


def get_channel_by_id(channel_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None


def get_channel_by_identifier(identifier: str) -> dict | None:
    identifier = identifier.strip()
    if not identifier:
        return None
    with _conn() as conn:
        if identifier.isdigit():
            row = conn.execute(
                "SELECT * FROM channels WHERE id = ?", (int(identifier),)
            ).fetchone()
        else:
            username = _normalize_channel_username(identifier)
            row = conn.execute(
                "SELECT * FROM channels WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None


def _normalize_channel_username(username: str) -> str:
    return username.strip().lstrip("@")


# ── Messages ───────────────────────────────────────────────────────────────────

def upsert_message(channel_id: int, message_id: int, text: str, date: str, run_id: int) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO raw_messages (channel_id, message_id, message_text, message_date, run_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, message_id) DO UPDATE SET
                message_text = excluded.message_text,
                message_date = excluded.message_date,
                run_id = excluded.run_id
        """, (channel_id, message_id, text, date, run_id))


def get_messages_for_run(run_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT
                rm.message_id,
                rm.message_text,
                rm.message_date,
                c.username AS channel_username
            FROM raw_messages rm
            JOIN channels c ON c.id = rm.channel_id
            WHERE rm.run_id = ?
            ORDER BY c.username, rm.message_date DESC
        """, (run_id,)).fetchall()
        return [dict(r) for r in rows]


# ── Products ───────────────────────────────────────────────────────────────────

def get_all_products() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT
                p.id,
                p.canonical_name,
                p.template_key,
                p.category,
                p.display_name,
                dp.default_price,
                pp.current_price,
                pp.previous_price,
                pp.updated_at
            FROM products p
            LEFT JOIN product_default_prices dp ON dp.product_id = p.id
            LEFT JOIN product_prices pp ON pp.product_id = p.id
            ORDER BY p.category, p.id
        """).fetchall()
        return [dict(r) for r in rows]


def update_product_price(product_id: int, new_price: int) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO product_prices (product_id, current_price, previous_price, updated_at)
            VALUES (?, ?, NULL, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                previous_price = product_prices.current_price,
                current_price = excluded.current_price,
                updated_at = excluded.updated_at
        """, (product_id, new_price, _now()))
        conn.execute("""
            UPDATE products
            SET previous_price = current_price, current_price = ?, updated_at = ?
            WHERE id = ?
        """, (new_price, _now(), product_id))


def get_product_by_identifier(identifier: str) -> dict | None:
    key = identifier.strip().lower()
    with _conn() as conn:
        row = conn.execute("""
            SELECT
                p.id,
                p.canonical_name,
                p.template_key,
                p.category,
                p.display_name,
                dp.default_price,
                pp.current_price,
                pp.previous_price,
                pp.updated_at
            FROM products p
            LEFT JOIN product_default_prices dp ON dp.product_id = p.id
            LEFT JOIN product_prices pp ON pp.product_id = p.id
            WHERE lower(p.template_key) = ?
               OR lower(p.canonical_name) = ?
               OR lower(p.display_name) = ?
            LIMIT 1
        """, (key, key, key)).fetchone()
        return dict(row) if row else None


def get_product_by_id(product_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("""
            SELECT p.id, p.canonical_name, p.template_key, p.category, p.display_name,
                   dp.default_price, pp.current_price, pp.previous_price, pp.updated_at
            FROM products p
            LEFT JOIN product_default_prices dp ON dp.product_id = p.id
            LEFT JOIN product_prices pp ON pp.product_id = p.id
            WHERE p.id = ?
        """, (product_id,)).fetchone()
        return dict(row) if row else None


def get_price_history_30d() -> list[dict]:
    """All price history entries from the last 30 days, newest first."""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT
                r.started_at,
                r.id          AS run_id,
                p.display_name,
                p.canonical_name,
                p.category,
                ph.competitor_price,
                ph.source_channel,
                ph.calculated_price,
                ph.price_delta,
                ph.is_large_change,
                ph.price_kept
            FROM price_history ph
            JOIN products p ON p.id = ph.product_id
            JOIN runs     r ON r.id = ph.run_id
            WHERE r.started_at >= datetime('now', '-30 days')
              AND r.status != 'running'
            ORDER BY r.started_at DESC, p.category, p.display_name
        """).fetchall()
        return [dict(r) for r in rows]


def get_competition_report_data(run_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT
                p.display_name,
                p.category,
                ph.competitor_price,
                ph.source_channel,
                ph.calculated_price,
                ph.price_delta,
                ph.is_large_change,
                ph.price_kept,
                r.started_at
            FROM price_history ph
            JOIN products p ON p.id = ph.product_id
            JOIN runs r ON r.id = ph.run_id
            WHERE ph.run_id = ?
            ORDER BY p.category, p.display_name
        """, (run_id,)).fetchall()
        return [dict(r) for r in rows]


def reset_product_price(product_id: int) -> int | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT default_price FROM product_default_prices WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if not row:
            return None
        default_price = row["default_price"]
        conn.execute("""
            INSERT INTO product_prices (product_id, current_price, previous_price, updated_at)
            VALUES (?, ?, NULL, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                previous_price = product_prices.current_price,
                current_price = excluded.current_price,
                updated_at = excluded.updated_at
        """, (product_id, default_price, _now()))
        conn.execute("""
            UPDATE products
            SET previous_price = current_price, current_price = ?, updated_at = ?
            WHERE id = ?
        """, (default_price, _now(), product_id))
        return default_price


def create_pending_price_change(
    run_id: int,
    product_id: int,
    proposed_price: int,
    old_price: int | None,
) -> int:
    with _conn() as conn:
        cur = conn.execute("""
            INSERT INTO pending_price_changes (
                run_id, product_id, proposed_price, old_price, created_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (run_id, product_id, proposed_price, old_price, _now()))
        return cur.lastrowid


def get_pending_price_change(change_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("""
            SELECT ppc.*, p.canonical_name
            FROM pending_price_changes ppc
            JOIN products p ON p.id = ppc.product_id
            WHERE ppc.id = ?
        """, (change_id,)).fetchone()
        return dict(row) if row else None


def get_price_changes_for_run(run_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT ppc.*, p.canonical_name
            FROM pending_price_changes ppc
            JOIN products p ON p.id = ppc.product_id
            WHERE ppc.run_id = ?
            ORDER BY ppc.id
        """, (run_id,)).fetchall()
        return [dict(row) for row in rows]


def get_unresolved_price_changes_for_run(run_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT ppc.*, p.canonical_name
            FROM pending_price_changes ppc
            JOIN products p ON p.id = ppc.product_id
            WHERE ppc.run_id = ?
              AND ppc.status IN ('pending', 'awaiting_manual')
            ORDER BY ppc.id
        """, (run_id,)).fetchall()
        return [dict(row) for row in rows]


def count_unresolved_price_changes_for_run(run_id: int) -> int:
    with _conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS n
            FROM pending_price_changes
            WHERE run_id = ?
              AND status IN ('pending', 'awaiting_manual')
        """, (run_id,)).fetchone()
        return int(row["n"] if row else 0)


def resolve_pending_price_change(
    change_id: int,
    status: str,
    resolved_by: int,
    manual_price: int | None = None,
) -> None:
    with _conn() as conn:
        conn.execute("""
            UPDATE pending_price_changes
            SET status = ?, resolved_at = ?, resolved_by = ?, manual_price = ?,
                manual_requested_by = NULL, manual_requested_at = NULL
            WHERE id = ?
        """, (status, _now(), resolved_by, manual_price, change_id))


def mark_pending_price_change_for_manual(change_id: int, admin_id: int) -> None:
    with _conn() as conn:
        conn.execute("""
            UPDATE pending_price_changes
            SET status = 'awaiting_manual',
                manual_requested_by = ?,
                manual_requested_at = ?
            WHERE id = ? AND status IN ('pending', 'awaiting_manual')
        """, (admin_id, _now(), change_id))


def get_pending_manual_price_change_for_admin(admin_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("""
            SELECT ppc.*, p.canonical_name
            FROM pending_price_changes ppc
            JOIN products p ON p.id = ppc.product_id
            WHERE ppc.status = 'awaiting_manual'
              AND ppc.manual_requested_by = ?
            ORDER BY ppc.manual_requested_at DESC, ppc.id DESC
            LIMIT 1
        """, (admin_id,)).fetchone()
        return dict(row) if row else None


# ── Price history ──────────────────────────────────────────────────────────────

def write_price_history(
    run_id: int,
    product_id: int,
    competitor_price: int | None,
    source_channel: str | None,
    calculated_price: int | None,
    price_delta: int | None,
    is_large_change: bool,
    price_kept: bool,
) -> None:
    with _conn() as conn:
        conn.execute("""
            INSERT INTO price_history (
                run_id, product_id, competitor_price, source_channel,
                calculated_price, price_delta, is_large_change, price_kept, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, product_id, competitor_price, source_channel,
            calculated_price, price_delta,
            int(is_large_change), int(price_kept), _now(),
        ))
