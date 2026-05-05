# Telegram Price Monitoring + Stories Automation — Full Technical Description

## 1. Project Purpose

A daily automation pipeline that:
1. Reads today's messages from 2–3 competitor Telegram channels.
2. Extracts prices for a fixed list of 12 products.
3. Calculates the owner's prices (competitor lowest − 500 RUB).
4. Generates 3 story images (1080 × 1920) from background templates.
5. Sends the updated price text, story images, and a run report to the owner via Telegram.
6. Stores price history in SQLite for change tracking.

---

## 2. Business Logic

### 2.1 Monitored Products (canonical names)

| ID  | Canonical Name        | Category |
|-----|-----------------------|----------|
| 1   | iPhone Pro 256 GB     | iPhone   |
| 2   | iPhone Pro 512 GB     | iPhone   |
| 3   | iPhone Pro 1 TB       | iPhone   |
| 4   | iPhone Pro Max 256 GB | iPhone   |
| 5   | iPhone Pro Max 512 GB | iPhone   |
| 6   | iPhone Pro Max 1 TB   | iPhone   |
| 7   | iPhone Air            | iPhone   |
| 8   | MacBook Neo           | Other    |
| 9   | AirPods Pro 3         | Other    |
| 10  | Whoop 5.0 Peak        | Other    |
| 11  | PS5                   | Other    |
| 12  | Apple Watch S11       | Other    |

### 2.2 Pricing Rule

```
calculated_price = min(competitor_prices_today) − 500 RUB
```

- If no competitor price is found for a product today → keep the previous price from the database unchanged.
- If the new calculated price differs from the last stored price by **more than 3,000 RUB** → flag it in the report (highlighted line in the Telegram message).
- Prices are always stored as integers (RUB, no kopecks).

### 2.3 Price List Template

The owner's price list is a fixed-format text block. Only the `{key}` placeholders are replaced on each run. The template is stored in `config.yaml` and contains emojis and formatting exactly as the owner wants it published.

```
Any tech in stock at a great price 🔥

iPhone
• Pro 256 GB — {iphone_pro_256} RUB
• Pro 512 GB — {iphone_pro_512} RUB
• Pro 1 TB — {iphone_pro_1tb} RUB
• Pro Max 256 GB — {iphone_pro_max_256} RUB
• Pro Max 512 GB — {iphone_pro_max_512} RUB
• Pro Max 1 TB — {iphone_pro_max_1tb} RUB
• Air — {iphone_air} RUB
• eSIM price ↑ +500 RUB

Other
• MacBook Neo — {macbook_neo} RUB
• AirPods Pro 3 — {airpods_pro_3} RUB
• Whoop 5.0 Peak — {whoop_50} RUB
• PS5 — {ps5} RUB
• Apple Watch S11 — {apple_watch_s11} RUB

All items are original, but stock is limited!
Delivery in Moscow within 2 hours
To order, message me: @svyat_001
```

Template keys map 1-to-1 to `product.template_key` in the database. Any product without a price today gets the last known price, or the literal `—` if no price has ever been found.

### 2.4 Report Format

The run report sent to the owner in Telegram:

```
📊 Run Report — 2026-05-04 09:00

✅ Found prices: 10 / 12
❌ Missing: iPhone Air, Whoop 5.0 Peak

Channel: @channel_one — OK
Channel: @channel_two — OK
Channel: @channel_three — UNAVAILABLE ⚠️

Price changes:
• iPhone Pro 256 GB: 94,000 → 91,500 (−2,500)
• iPhone Pro Max 512 GB: 110,000 → 106,000 (−4,000) ⚠️ LARGE CHANGE
• MacBook Neo: 145,000 → 145,000 (no change)

Errors: none
```

Large-change flag (`⚠️ LARGE CHANGE`) triggers when `|new − old| > 3000`.

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Scheduler (cron)                      │
│                  triggers main.py daily at HH:MM             │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Orchestrator  src/main.py                                   │
│  1. fetcher   → raw messages from channels                   │
│  2. parser    → normalized text per message                  │
│  3. matcher   → product matches + extracted prices           │
│  4. pricing   → calculate new prices, detect changes         │
│  5. report    → build report text                            │
│  6. story     → generate 3 story images                      │
│  7. sender    → deliver everything to Telegram               │
│  8. db        → persist prices + run log                     │
└──────────────────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
     Telethon         SQLite         Pillow
  (read channels)  (prices.db)   (story images)
```

### Component Responsibilities

| Module        | Role                                                             |
|---------------|------------------------------------------------------------------|
| `fetcher.py`  | Open Telethon session, read today's messages per channel         |
| `parser.py`   | Normalize text, transliterate Russian, tokenize                  |
| `matcher.py`  | Match product aliases, extract RUB prices via regex              |
| `pricing.py`  | Apply pricing rule, compare to history, flag large changes       |
| `report.py`   | Assemble report text and formatted price list                    |
| `story.py`    | Render 3 story images from backgrounds + price list              |
| `sender.py`   | Send via Bot API (text + images) and userbot (stories)           |
| `bot.py`      | Long-running bot: admin commands, inline trigger button, polling |
| `db.py`       | All SQLite reads/writes — never called directly from logic       |
| `config.py`   | Load `.env` + `config.yaml`, expose typed Settings dataclass     |
| `main.py`     | Pipeline entry point — called by cron and by bot trigger         |

---

## 4. Database Architecture (SQLite)

File: `data/prices.db`

### 4.1 Table: `products`

```sql
CREATE TABLE products (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT    NOT NULL UNIQUE,  -- "iPhone Pro 256 GB"
    template_key   TEXT    NOT NULL UNIQUE,  -- "iphone_pro_256"
    category       TEXT    NOT NULL,         -- "iPhone" | "Other"
    display_name   TEXT    NOT NULL,         -- "Pro 256 GB" (used in story rendering)
    current_price  INTEGER,                  -- latest calculated price, NULL if unknown
    previous_price INTEGER,
    updated_at     TEXT                      -- ISO-8601 timestamp of last price update
);
```

Seeded on first run from `config.yaml`. Never deleted — only updated.

### 4.2 Table: `runs`

```sql
CREATE TABLE runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT    NOT NULL,
    finished_at      TEXT,
    status           TEXT    NOT NULL DEFAULT 'running',  -- running|success|partial|failed
    products_found   INTEGER DEFAULT 0,
    products_missing INTEGER DEFAULT 0,
    errors           TEXT                                 -- JSON array of error strings
);
```

### 4.3 Table: `channels`

```sql
CREATE TABLE channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,  -- "@handle" or numeric channel ID
    display_name    TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    last_fetch_at   TEXT,
    last_message_id INTEGER DEFAULT 0         -- used for incremental fetch on retry
);
```

Populated from `config.yaml` on startup via upsert.

### 4.4 Table: `admins`

```sql
CREATE TABLE admins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,   -- Telegram user ID
    username    TEXT,                      -- @handle (informational, may be NULL)
    added_by    INTEGER,                   -- telegram_id of the admin who granted access
    added_at    TEXT NOT NULL              -- ISO-8601
);
```

Seeded with `TELEGRAM_ADMIN_ID` from `.env` on first run (`init_db.py`). All bot commands check this table before executing. `/add_admin` inserts a new row; the caller must already be in the table.

**Admin DB quick-reference** (useful for debugging via `sqlite3 data/prices.db`):

```sql
-- List all admins
SELECT telegram_id, username, added_at FROM admins;

-- Add admin manually (bypass bot)
INSERT INTO admins (telegram_id, username, added_by, added_at)
VALUES (123456789, '@handle', NULL, datetime('now'));

-- Remove admin
DELETE FROM admins WHERE telegram_id = 123456789;

-- See last 5 runs
SELECT id, started_at, status, products_found, products_missing FROM runs ORDER BY id DESC LIMIT 5;

-- See current prices
SELECT canonical_name, current_price, updated_at FROM products ORDER BY category, id;
```

### 4.4 Table: `raw_messages`

```sql
CREATE TABLE raw_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL REFERENCES channels(id),
    message_id   INTEGER NOT NULL,
    message_text TEXT,
    message_date TEXT    NOT NULL,
    run_id       INTEGER REFERENCES runs(id),
    processed    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(channel_id, message_id)
);
```

Stores only messages fetched today. UNIQUE constraint prevents reprocessing on retry runs.

### 4.5 Table: `price_history`

```sql
CREATE TABLE price_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id),
    product_id       INTEGER NOT NULL REFERENCES products(id),
    competitor_price INTEGER,              -- lowest found today; NULL if not found
    source_channel   TEXT,                -- "@handle" where the lowest price came from
    calculated_price INTEGER,             -- competitor_price - 500
    price_delta      INTEGER,             -- calculated_price - previous products.current_price
    is_large_change  INTEGER DEFAULT 0,   -- 1 if |price_delta| > 3000
    price_kept       INTEGER DEFAULT 0,   -- 1 if no price found today, kept old value
    created_at       TEXT    NOT NULL
);
```

One row per product per run. Written even when price is unchanged (audit trail).

### Entity Relationships

```
runs ──< price_history >── products
runs ──< raw_messages  >── channels
channels ──< raw_messages
```

### Key Queries

**Current price table:**
```sql
SELECT canonical_name, current_price, updated_at
FROM products ORDER BY category, id;
```

**Products with large changes in last successful run:**
```sql
SELECT p.canonical_name, ph.price_delta
FROM price_history ph
JOIN products p ON p.id = ph.product_id
WHERE ph.run_id = (SELECT MAX(id) FROM runs WHERE status IN ('success','partial'))
  AND ph.is_large_change = 1;
```

**Price history for one product (last 30 runs):**
```sql
SELECT ph.created_at, ph.competitor_price, ph.calculated_price, ph.is_large_change
FROM price_history ph
WHERE ph.product_id = ?
ORDER BY ph.created_at DESC LIMIT 30;
```

---

## 5. Message Processing Pipeline

### 5.1 Fetch Stage (`fetcher.py`)

1. Open `TelegramClient` using `API_ID`, `API_HASH`, session at `data/userbot.session`.
2. For each active channel in `channels` table:
   - Call `client.get_messages(channel, limit=100)` and filter to today's date.
   - Upsert each message into `raw_messages` (UNIQUE on `channel_id + message_id` prevents duplicates on retry).
   - On `ChannelPrivateError` or `FloodWaitError`: log error, mark channel unavailable for this run, continue to next channel.
3. Return list of `raw_messages` rows for the parse stage.

### 5.2 Parse Stage (`parser.py`)

Transform each raw message text into a normalized string ready for product matching:

```
raw text → lowercase → transliterate Cyrillic brands → normalize whitespace → normalized text
```

**Cyrillic-to-Latin transliteration map (brand/product terms only):**

> All product-matching regexes and alias comparisons run on the **post-transliteration** text. This means a message containing only Cyrillic (`Айфон Про 256 — 84500 руб`) is normalized to `iphone pro 256 — 84500 rub` before any matching happens, so the same regex covers both Latin and Cyrillic input with no duplicated logic.

| Cyrillic input                    | Latin output |
|-----------------------------------|--------------|
| айфон / айфона / айфоны           | iphone       |
| про                               | pro          |
| макс                              | max          |
| мак / макбук / макбука            | macbook      |
| аирподс / аирпадс                 | airpods      |
| эпл / эппл / апл                  | apple        |
| вотч / вотча                      | watch        |
| пс / приставка                    | ps           |
| гб / гигабайт                     | gb           |
| тб / терабайт                     | tb           |
| руб / рублей / р. / рубля         | rub          |
| тыс / тысяч / тысячи / к (suffix) | 000          |
| с (as in "серия/series" before NN)| s            |

**Normalization steps (in order):**
1. `text.lower()`
2. Strip HTML/Markdown (`<b>`, `**`, `__`, etc.) and Telegram formatting entities.
3. Apply transliteration replacements (word-boundary-aware regex, longest match first).
4. Normalize `к`-shorthand: `85к` → `85000`, `85.5к` → `85500`.
5. Collapse multiple spaces and newlines to a single space.
6. Remove zero-width characters and soft hyphens (`​`, `­`).

Output: a normalized single-line string per message, plus a list of line-segments (split on original `\n`) for per-line matching.

### 5.3 Match Stage (`matcher.py`)

Uses a **two-pass approach** to handle different message formats:

**Pass 1 — Line-segment scan (handles "product: price" per line):**
For each line-segment in the normalized message:
1. Test each product's `regex` + `aliases` against the segment.
2. If a product matches, extract the price token from within ± 60 characters of the match.
3. Price token regex: `(\d[\d\s,]*)\\s*(?:rub|р\\.?|₽|руб\\.?)`
4. Handle shorthand: `85к` → `85000`, `85.5к` → `85500`.
5. Apply `exclude_if_contains` — if the matched segment also contains any excluded keyword, skip this match.

**Pass 2 — Full-message fallback (handles dense price lists as one blob):**
If Pass 1 found fewer than 3 products across all messages from a channel, run a full-text scan treating the entire message as a list. Useful for channels that post one long price list without clear line breaks.

**Match output per product (after all messages from all channels are processed):**
```python
{
    "product_id": 1,
    "canonical_name": "iPhone Pro 256 GB",
    "prices_found": [85000, 84500, 86000],  # all prices, all channels
    "source_channels": ["@ch1", "@ch1", "@ch2"],
    "min_price": 84500,
    "min_price_channel": "@ch1"
}
```

Products with no match at all get `min_price = None`.

### 5.4 Pricing Stage (`pricing.py`)

For each of the 12 products:

1. Read `current_price` (last known) from `products` table.
2. If `min_price` was found today:
   - `calculated = min_price - config.pricing.discount` (500)
   - `delta = calculated - (current_price or 0)`
   - `is_large_change = abs(delta) > config.pricing.large_change_threshold` (3000)
   - Update `products.current_price = calculated`, `products.previous_price = old`
   - Write row to `price_history` with `price_kept = 0`
3. If no price found today:
   - Leave `products.current_price` unchanged
   - Write row to `price_history` with `competitor_price = NULL`, `price_kept = 1`

---

## 6. Story Image Generation (`story.py`)

### 6.1 Inputs

- `backgrounds/` folder: any `.jpg` or `.png` files.
- Selection mode: `config.story.background_selection: random | sequential`.
- If fewer than 3 files exist, reuse with varied blur/overlay parameters.
- One-time download from Google Drive available via `scripts/download_backgrounds.py`.

### 6.2 Per-Image Rendering Pipeline

```
Load image
  → Resize/crop to 1080 × 1920
      (scale so shorter side fills target; center-crop longer side; no stretching)
  → Apply Gaussian blur (radius = config.story.blur_radius, default: 8)
  → Darken overlay (RGBA black at config.story.darken_alpha/255, default: 120)
  → Draw rounded semi-transparent panel behind text
  → Render price list text inside panel
  → Save PNG to output/stories/story_{n}_{YYYYMMDD}.png
```

### 6.3 Panel Dimensions

| Parameter       | Config key                    | Default |
|-----------------|-------------------------------|---------|
| Horizontal pad  | `story.padding_x`             | 60 px   |
| Vertical pad    | `story.padding_y`             | 48 px   |
| Panel width     | `1080 - 2 * padding_x`        | 960 px  |
| Panel height    | auto from text content        | —       |
| Panel color     | `story.panel_color` (RGBA)    | `(0,0,0,160)` |
| Corner radius   | `story.panel_corner_radius`   | 24 px   |
| Vertical pos    | vertically centered           | —       |

### 6.4 Text Rendering

| Element          | Config key              | Default                |
|------------------|-------------------------|------------------------|
| Font file        | `story.font_path`       | `assets/Inter-SemiBold.ttf` |
| Title font size  | `story.font_size_title` | 42 px                  |
| Body font size   | `story.font_size_body`  | 34 px                  |
| Price font size  | `story.font_size_price` | 38 px                  |
| Line height      | `story.line_height`     | 1.5                    |
| Text color       | hardcoded                | `#FFFFFF` + 1px shadow |
| Category headers | `story.accent_color`    | `#F5A623`              |

**Overflow guard:** After drawing all lines, verify each line's pixel width with `ImageDraw.textlength()`. If any line exceeds panel width, reduce font sizes by 2 px and re-render. Max 3 iterations; on the 4th, truncate with `…`.

---

## 7. Telegram Delivery (`sender.py`)

### 7.1 Notification Bot (Bot API)

Used for sending the report, price list text, and story images to the owner.

- Library: raw `httpx` POST calls to Bot API (no heavy framework dependency).
- Target: `TELEGRAM_ADMIN_ID` from `.env`.
- Sequence:
  1. Send formatted price list as a text message.
  2. Send run report as a text message.
  3. `sendPhoto` × 3 with the story image files.
- On Bot API failure: log ERROR, do not crash the run.

### 7.2 Userbot Story Posting (Telethon)

Used for posting stories to the owner's own Telegram account.

- Reuses the same `data/userbot.session` as the fetcher.
- Method: upload each image via `client.upload_file()`, then call `stories.SendStoryRequest` (raw MTProto).
- **Fallback:** if story posting raises any exception, send images as regular photos via Bot API and log `STORY_POSTING_FAILED`.

### 7.3 Error Notifications

The following events trigger an immediate plain-text alert to all admins in the `admins` table:

- A channel is unavailable during fetch.
- Zero prices found across all channels for the run.
- Story generation failure.
- Any unhandled exception in `main.py`.

### 7.4 Admin Bot — Commands and Trigger Button (`bot.py`)

`bot.py` is a **long-running process** using `python-telegram-bot` with `Application.run_polling()`. It runs alongside the cron scheduler inside the same Docker container (started in `entrypoint.sh` as a background process before `crond -f`).

**All commands are guarded** — every handler checks `db.is_admin(update.effective_user.id)` before executing. Non-admins get a silent ignore or a generic "not authorized" reply.

**Commands:**

| Command              | Action                                                               |
|----------------------|----------------------------------------------------------------------|
| `/start`             | Shows admin menu with inline keyboard "▶️ Run Scraper Now"           |
| `/run`               | Triggers the full pipeline immediately (same as pressing the button) |
| `/status`            | Shows last run summary (status, found/missing, timestamp)            |
| `/prices`            | Shows current price table for all 12 products                        |
| `/add_admin <id>`    | Adds Telegram user ID to `admins` table; caller must be admin        |

**Trigger button flow:**

```
Admin sends /start
  → Bot replies:
      "Admin panel
       Last run: 2026-05-04 09:00 ✅"
      [▶️ Run Scraper Now]

Admin presses button
  → Bot edits message: "⏳ Running pipeline..."
  → Bot sets a run_lock (file: data/.run_lock) to prevent concurrent execution
  → Bot calls run_pipeline() in a thread (same logic as main.py)
  → On complete: Bot sends report + price list + 3 story images
  → Bot removes run_lock
  → If pipeline already running: Bot replies "⚠️ A run is already in progress"
```

**Concurrency lock:** A file `data/.run_lock` is created at pipeline start and deleted on finish (or on unhandled exception). Both `bot.py` and `main.py` (cron) check for this file before starting. If the lock exists and is older than 30 minutes, it is considered stale and removed automatically.

---

## 8. Configuration

### 8.1 `.env` (secrets — never commit)

```env
# From my.telegram.org
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

# From @BotFather
TELEGRAM_BOT_TOKEN=123456789:AABBCCDDeeffgghhiijjkk

# Owner's Telegram user ID (receives reports and images)
TELEGRAM_ADMIN_ID=987654321

# Phone number for interactive session creation (used once by create_session.py)
TELEGRAM_PHONE=+79001234567
```

### 8.2 `config.yaml` (business settings — safe to commit)

```yaml
channels:
  - username: "@channel_one"
    display_name: "Channel One"
  - username: "@channel_two"
    display_name: "Channel Two"
  - username: "@channel_three"
    display_name: "Channel Three"

pricing:
  discount: 500
  large_change_threshold: 3000

schedule:
  run_time: "09:00"        # 24h format, in the timezone below
  timezone: "Europe/Moscow"

story:
  blur_radius: 8
  darken_alpha: 120
  panel_color: [0, 0, 0, 160]
  panel_corner_radius: 24
  padding_x: 60
  padding_y: 48
  font_path: "assets/Inter-SemiBold.ttf"
  font_size_title: 42
  font_size_body: 34
  font_size_price: 38
  line_height: 1.5
  accent_color: "#F5A623"
  background_selection: "random"

price_list_template: |
  Any tech in stock at a great price 🔥

  iPhone
  • Pro 256 GB — {iphone_pro_256} RUB
  ...

products:
  - id: iphone_pro_256
    canonical: "iPhone Pro 256 GB"
    category: "iPhone"
    display_name: "Pro 256 GB"
    aliases:
      - "iphone pro 256"
      - "iphone 17 pro 256"
      - "17 pro 256 gb"
      - "pro 256 gb"
      - "pro 256"
      - "айфон про 256"
    regex: "(?:iphone\\s*)?(?:1[56789]\\s*)?pro\\s*256\\s*(?:gb|г[бб])?"
    exclude_if_contains: ["max", "plus"]

  - id: iphone_pro_512
    canonical: "iPhone Pro 512 GB"
    category: "iPhone"
    display_name: "Pro 512 GB"
    aliases: ["iphone pro 512", "pro 512 gb", "pro 512", "айфон про 512"]
    regex: "(?:iphone\\s*)?(?:1[56789]\\s*)?pro\\s*512\\s*(?:gb|г[бб])?"
    exclude_if_contains: ["max", "plus"]

  - id: iphone_pro_1tb
    canonical: "iPhone Pro 1 TB"
    category: "iPhone"
    display_name: "Pro 1 TB"
    aliases: ["iphone pro 1tb", "pro 1tb", "pro 1 tb", "айфон про 1тб"]
    regex: "(?:iphone\\s*)?(?:1[56789]\\s*)?pro\\s*1\\s*(?:tb|т[бб])"
    exclude_if_contains: ["max"]

  - id: iphone_pro_max_256
    canonical: "iPhone Pro Max 256 GB"
    category: "iPhone"
    display_name: "Pro Max 256 GB"
    aliases: ["iphone pro max 256", "pro max 256", "max 256", "айфон про макс 256"]
    regex: "(?:iphone\\s*)?(?:1[56789]\\s*)?pro\\s*max\\s*256\\s*(?:gb|г[бб])?"
    exclude_if_contains: []

  - id: iphone_pro_max_512
    canonical: "iPhone Pro Max 512 GB"
    category: "iPhone"
    display_name: "Pro Max 512 GB"
    aliases: ["pro max 512", "max 512", "айфон про макс 512"]
    regex: "(?:iphone\\s*)?(?:1[56789]\\s*)?pro\\s*max\\s*512\\s*(?:gb|г[бб])?"
    exclude_if_contains: []

  - id: iphone_pro_max_1tb
    canonical: "iPhone Pro Max 1 TB"
    category: "iPhone"
    display_name: "Pro Max 1 TB"
    aliases: ["pro max 1tb", "max 1tb", "айфон про макс 1тб"]
    regex: "(?:iphone\\s*)?(?:1[56789]\\s*)?pro\\s*max\\s*1\\s*(?:tb|т[бб])"
    exclude_if_contains: []

  - id: iphone_air
    canonical: "iPhone Air"
    category: "iPhone"
    display_name: "Air"
    aliases: ["iphone air", "айфон аир"]
    regex: "iphone\\s*air"
    exclude_if_contains: []

  - id: macbook_neo
    canonical: "MacBook Neo"
    category: "Other"
    display_name: "MacBook Neo"
    aliases: ["macbook neo", "мак нео", "макбук нео"]
    regex: "macbook\\s*neo"
    exclude_if_contains: []

  - id: airpods_pro_3
    canonical: "AirPods Pro 3"
    category: "Other"
    display_name: "AirPods Pro 3"
    aliases: ["airpods pro 3", "airpods pro3", "аирподс про 3"]
    regex: "airpods\\s*pro\\s*3"
    exclude_if_contains: []

  - id: whoop_50
    canonical: "Whoop 5.0 Peak"
    category: "Other"
    display_name: "Whoop 5.0 Peak"
    aliases: ["whoop 5.0", "whoop 5", "whoop 5.0 peak", "whoop peak"]
    regex: "whoop\\s*5(?:\\.0)?(?:\\s*peak)?"
    exclude_if_contains: []

  - id: ps5
    canonical: "PS5"
    category: "Other"
    display_name: "PS5"
    aliases: ["ps5", "playstation 5", "плейстейшн 5", "пс5", "пс 5"]
    regex: "ps\\s*5|playstation\\s*5"
    exclude_if_contains: []

  - id: apple_watch_s11
    canonical: "Apple Watch S11"
    category: "Other"
    display_name: "Apple Watch S11"
    aliases: ["apple watch s11", "watch s11", "watch series 11", "эпл вотч с11"]
    regex: "(?:apple\\s*)?watch\\s*s(?:eries\\s*)?11"
    exclude_if_contains: []

# Seed admins — telegram_id values added to admins table on first init_db run
admins:
  - telegram_id: 987654321   # replace with real owner ID
    username: "@owner_handle"
```

---

## 9. Project Directory Structure

```
bot_auto_competition/
├── .env                          # secrets (gitignored)
├── .env.example
├── .gitignore
├── config.yaml                   # business config (safe to commit)
├── config.example.yaml
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
├── README.md
│
├── assets/
│   └── Inter-SemiBold.ttf        # font for story rendering (include in repo)
│
├── backgrounds/                  # background images (add manually or via script)
│   ├── bg_01.jpg
│   ├── bg_02.jpg
│   └── bg_03.jpg
│
├── data/                         # gitignored — runtime data
│   ├── prices.db
│   └── userbot.session           # Telethon session — NEVER commit
│
├── logs/                         # gitignored
│   └── app.log
│
├── output/                       # gitignored — generated per run
│   ├── stories/
│   └── reports/
│
├── scripts/
│   ├── init_db.py                # create tables + seed products from config
│   ├── create_session.py         # one-time interactive Telethon auth
│   └── download_backgrounds.py  # one-time Google Drive download
│
├── src/
│   ├── __init__.py
│   ├── main.py                   # pipeline entry point (cron + bot trigger)
│   ├── config.py                 # Settings dataclass, loads .env + config.yaml
│   ├── db.py                     # all SQLite operations
│   ├── fetcher.py                # Telethon channel reading
│   ├── parser.py                 # text normalization + transliteration
│   ├── matcher.py                # product matching + price extraction
│   ├── pricing.py                # pricing rule + change detection
│   ├── report.py                 # report + price list text assembly
│   ├── story.py                  # Pillow story image rendering
│   ├── sender.py                 # Bot API + userbot delivery
│   └── bot.py                    # long-running admin bot (commands + trigger button)
│
└── tests/
    ├── test_parser.py
    ├── test_matcher.py
    ├── test_pricing.py
    └── fixtures/
        └── sample_messages.txt   # sample channel messages for unit tests
```

---

## 10. Technical Stack

| Layer        | Technology                           | Reason                                            |
|--------------|--------------------------------------|---------------------------------------------------|
| Language     | Python 3.11+                         | Best ecosystem for this task; fastest to build    |
| TG reading   | Telethon 1.x                         | MTProto userbot — reads any public channel        |
| TG sending   | httpx + Bot API                      | Simple, reliable, no heavy framework needed       |
| Image gen    | Pillow (PIL) 10+                     | Lightweight; no headless browser required         |
| Storage      | SQLite via `sqlite3` stdlib          | Zero infrastructure; sufficient for daily MVP     |
| Config       | PyYAML + python-dotenv + dataclasses | Typed settings; secrets isolated in `.env`        |
| Scheduling   | cron inside Docker                   | Proven, simple, no extra dependencies             |
| Container    | Docker + Docker Compose              | Reproducible deployment; easy restart             |
| Logging      | Python `logging` + RotatingFileHandler | Rotating logs, no external service needed       |

### `requirements.txt`

```
telethon==1.36.0
Pillow==10.4.0
PyYAML==6.0.2
python-dotenv==1.0.1
httpx==0.27.0
pydantic==2.7.0
pytz==2024.1
```

---

## 11. Automation and Scheduling

### `docker-compose.yml`

```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./output:/app/output
      - ./backgrounds:/app/backgrounds
    env_file:
      - .env
    environment:
      - TZ=Europe/Moscow
```

### `Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
```

### `entrypoint.sh`

```bash
#!/bin/sh
python scripts/init_db.py

# Write crontab from config run_time
RUN_TIME=$(python -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['schedule']['run_time'])")
HOUR=$(echo $RUN_TIME | cut -d: -f1)
MINUTE=$(echo $RUN_TIME | cut -d: -f2)

echo "$MINUTE $HOUR * * * cd /app && python -m src.main >> /app/logs/cron.log 2>&1" | crontab -

# Start admin bot in background, then start cron in foreground
python -m src.bot &
crond -f
```

### Manual trigger

```bash
# Via shell
docker compose exec bot python -m src.main

# Via Telegram bot
# Send /run or press "▶️ Run Scraper Now" button after /start
```

---

## 12. Logging Strategy

All logs → `logs/app.log` via `RotatingFileHandler` (5 MB max × 5 backups).

| Level      | Used for                                                           |
|------------|--------------------------------------------------------------------|
| `DEBUG`    | Raw message text, regex match attempts                             |
| `INFO`     | Run start/end, products found, prices calculated, images generated |
| `WARNING`  | Price not found today (kept old), channel returned 0 messages      |
| `ERROR`    | Channel unavailable, Telegram send failure, image gen failure      |
| `CRITICAL` | Unhandled exception, database write failure                        |

Every run ends with a structured summary line:
```
INFO [2026-05-04 09:00:34] RUN COMPLETE | found=10/12 | missing=iPhone Air,Whoop 5.0 Peak | duration=34.2s
```

---

## 13. Error Handling

| Scenario                               | Behavior                                                         |
|----------------------------------------|------------------------------------------------------------------|
| Channel unavailable (private/banned)   | Log ERROR, mark unavailable in run, notify admin, continue       |
| `FloodWaitError` from Telegram         | Sleep the required wait time, retry once, then skip channel      |
| 0 products found across all channels   | Log CRITICAL, send Telegram alert, write `failed` run to DB      |
| Price extraction returns no match      | Keep previous price, set `price_kept=1` in `price_history`       |
| Image generation failure               | Log ERROR, send report + price text without images, notify admin  |
| Story posting fails (userbot)          | Log ERROR, send images as regular photos via Bot API             |
| DB write failure                       | Log CRITICAL, continue pipeline (report is still sent)           |
| Unhandled exception in `main.py`       | Log CRITICAL with traceback, send admin notification, exit 1     |

---

## 14. One-Time Setup Sequence

```bash
# 1. Clone repo and copy config
cp .env.example .env           # fill in credentials
cp config.example.yaml config.yaml  # adjust channels / schedule

# 2. Add background images to backgrounds/ (or run download script)
python scripts/download_backgrounds.py

# 3. Create Telethon session (interactive, phone + code)
python scripts/create_session.py
# → saves data/userbot.session

# 4. Build and start
docker compose up -d
```

`data/userbot.session` must exist before the container starts. After creation it persists via the `./data:/app/data` volume mount.

---

## 15. Admin Interface

No web UI. Administration happens via the Telegram bot and the server CLI.

### 15.1 Telegram Bot Commands

All commands are restricted to users in the `admins` table. Non-admins are silently ignored.

| Command              | What it does                                                         |
|----------------------|----------------------------------------------------------------------|
| `/start`             | Shows admin panel with "▶️ Run Scraper Now" inline button            |
| `/run`               | Triggers the full pipeline immediately                               |
| `/status`            | Shows last run: timestamp, status, found/missing count, errors       |
| `/prices`            | Shows current price table for all 12 products                        |
| `/add_admin <id>`    | Grants admin access to a Telegram user ID; caller must be admin      |

### 15.2 Server CLI

| Task                    | Command                                                         |
|-------------------------|-----------------------------------------------------------------|
| Manual pipeline run     | `docker compose exec bot python -m src.main`                    |
| View live logs          | `docker compose exec bot tail -f logs/app.log`                  |
| Restart bot             | `docker compose restart bot`                                    |
| Change config           | Edit `config.yaml` → `docker compose restart bot`               |

### 15.3 Database Admin Reference

Connect: `sqlite3 data/prices.db`

```sql
-- Current prices
SELECT canonical_name, current_price, previous_price, updated_at FROM products;

-- Last 10 runs
SELECT id, started_at, status, products_found, products_missing FROM runs ORDER BY id DESC LIMIT 10;

-- Price history for a specific product (replace 1 with product id)
SELECT r.started_at, ph.competitor_price, ph.calculated_price, ph.price_delta, ph.is_large_change
FROM price_history ph JOIN runs r ON r.id = ph.run_id
WHERE ph.product_id = 1 ORDER BY ph.created_at DESC LIMIT 30;

-- List admins
SELECT telegram_id, username, added_at FROM admins;

-- Manually add admin
INSERT INTO admins (telegram_id, username, added_by, added_at)
VALUES (123456789, '@handle', NULL, datetime('now'));

-- Remove admin
DELETE FROM admins WHERE telegram_id = 123456789;

-- Messages fetched in last run
SELECT c.username, COUNT(*) as msg_count
FROM raw_messages rm JOIN channels c ON c.id = rm.channel_id
WHERE rm.run_id = (SELECT MAX(id) FROM runs)
GROUP BY c.username;
```



---

## 16. Risks and Limitations

| Risk                                    | Likelihood | Impact | Mitigation                                              |
|-----------------------------------------|------------|--------|---------------------------------------------------------|
| Telegram changes story MTProto API      | Medium     | Medium | Fallback: send as photos; monitor Telethon releases     |
| Channel changes message format          | High       | Medium | Alias dict + regex in `config.yaml`, easy to update     |
| New iPhone model number (e.g. 18)       | High       | Medium | Regex `1[56789]` — extend to `1[56789\|8]` when needed  |
| Telethon session expires or gets banned | Low        | High   | Keep session alive; monitor logs for auth errors        |
| Google Drive backgrounds unavailable    | Low        | Low    | Bundle 3 default backgrounds in repo as fallback        |
| `FloodWaitError` on channel fetch       | Medium     | Low    | Sleep + retry logic in `fetcher.py`                     |
| Story text overflow / unreadable        | Medium     | Medium | Overflow guard with font-size reduction in `story.py`   |

---

## 17. Deliverables Checklist (from TZ)

| TZ Requirement                | Covered by                                                |
|-------------------------------|-----------------------------------------------------------|
| GitHub repository             | Root of repo                                              |
| Run instructions              | `README.md` + Section 14 above                            |
| `.env.example`                | `.env.example`                                            |
| `config.example.yaml`         | `config.example.yaml`                                     |
| 3 story images                | `output/stories/` after each run                          |
| Updated price text            | Sent to Telegram + saved to `output/reports/`             |
| Run report                    | Sent to Telegram + saved to `output/reports/`             |
| Architecture description      | This document                                             |
| Risks and limitations         | Section 16 above                                          |
| Demo video                    | Record manually; link in `README.md`                      |
