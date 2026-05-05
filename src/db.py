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
    manual_price    INTEGER
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

        for c in settings.channels:
            conn.execute("""
                INSERT INTO channels (username, display_name)
                VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET display_name = excluded.display_name
            """, (c.username, c.display_name))

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


def get_last_run() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE status IN ('success','partial') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# ── Channels ───────────────────────────────────────────────────────────────────

def get_channel_id(username: str) -> int | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM channels WHERE username = ?", (username,)
        ).fetchone()
        return row["id"] if row else None


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
        rows = conn.execute(
            "SELECT * FROM products ORDER BY category, id"
        ).fetchall()
        return [dict(r) for r in rows]


def update_product_price(product_id: int, new_price: int) -> None:
    with _conn() as conn:
        conn.execute("""
            UPDATE products
            SET previous_price = current_price, current_price = ?, updated_at = ?
            WHERE id = ?
        """, (new_price, _now(), product_id))


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


def resolve_pending_price_change(
    change_id: int,
    status: str,
    resolved_by: int,
    manual_price: int | None = None,
) -> None:
    with _conn() as conn:
        conn.execute("""
            UPDATE pending_price_changes
            SET status = ?, resolved_at = ?, resolved_by = ?, manual_price = ?
            WHERE id = ?
        """, (status, _now(), resolved_by, manual_price, change_id))


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
