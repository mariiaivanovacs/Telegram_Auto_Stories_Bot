# Setup and Run Guide

Follow these steps from a fresh machine. Total time: ~25–30 minutes.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python --version` to check |
| Docker + Docker Compose | 24+ | Docker Desktop works |
| Telegram account | any | The account that will *read* competitor channels |
| @BotFather bot token | — | For sending results and admin commands |

---

## 2. Get Telegram API Credentials

1. Open [my.telegram.org](https://my.telegram.org) in a browser.
2. Log in with the phone number of the account that will read competitor channels.
3. Click **API development tools**.
4. Create a new application (any name, any platform).
5. Copy **App api_id** (a number) and **App api_hash** (a hex string).

Keep the browser tab open — you will need these values in step 4.

---

## 3. Create a Bot via @BotFather

1. Open Telegram, start a chat with `@BotFather`.
2. Send `/newbot` and follow the prompts (choose any name and username).
3. Copy the **bot token** shown at the end (format: `123456789:AABBCCDDeeffgg...`).
4. Find your own Telegram user ID:
   - Start a chat with `@userinfobot` and send any message.
   - Copy the **Id** value shown — this is your `TELEGRAM_ADMIN_ID`.

---

## 4. Clone the Repo and Fill in Credentials

```bash
git clone <repo-url>
cd bot_auto_competition

cp .env.example .env
cp config.example.yaml config.yaml
```

Open `.env` and fill in every value:

```env
TELEGRAM_API_ID=12345678          # from my.telegram.org
TELEGRAM_API_HASH=abcdef1234...   # from my.telegram.org
TELEGRAM_BOT_TOKEN=123456789:AA.. # from @BotFather
TELEGRAM_ADMIN_ID=987654321       # your Telegram user ID
TELEGRAM_PHONE=+79001234567       # phone number for the Telegram account above
```

Open `config.yaml` and adjust the channels section:

```yaml
channels:
  - username: "@real_channel_one"
    display_name: "Channel One"
  - username: "@real_channel_two"
    display_name: "Channel Two"
```

Also check `schedule.run_time` (default `09:00`) and `schedule.timezone` (default `Europe/Moscow`).

---

## 5. Create the Telethon Session

This step is done **once** on the machine that will run Docker. The session file is saved
to `data/userbot.session` and persists via the volume mount.

```bash
pip install telethon python-dotenv PyYAML
python scripts/create_session.py
```

The script will prompt for:
1. Your phone number (if not in `.env`) — enter with country code: `+79001234567`
2. The confirmation code Telegram sends to your account

On success: `Session saved to data/userbot.session`

---

## 6. Add Background Images

Background images go in the `backgrounds/` folder (JPEG or PNG, any size — they are
automatically cropped to 1080×1920).

**Option A — manual:** copy 3 `.jpg` or `.png` files into `backgrounds/`.

**Option B — download script** (if backgrounds are hosted on Google Drive):

```bash
python scripts/download_backgrounds.py
```

If `backgrounds/` is empty when stories are generated, the pipeline will fail with
`FileNotFoundError`. At least one image is required.

---

## 7. Start with Docker Compose

```bash
docker compose up -d
```

This will:
1. Build the image (first time only, ~2–3 minutes).
2. Run `scripts/init_db.py` — creates `data/prices.db` with all tables and product rows.
3. Write the crontab entry from `config.yaml` → `schedule.run_time`.
4. Start the admin bot in the background.
5. Start `crond` (keeps the container alive and triggers daily runs).

Check that the container is running:

```bash
docker compose ps
```

View live logs:

```bash
docker compose exec bot tail -f logs/app.log
```

---

## 8. Verify the First Run

**Trigger manually** (instead of waiting for the cron):

```bash
docker compose exec bot python -m src.main
```

Or send `/run` to your bot on Telegram (you must be in the `admins` table, which is
seeded automatically from `TELEGRAM_ADMIN_ID` on the first init).

A successful run will:

1. Log `── Run #1 started ──` in `logs/app.log`.
2. Fetch messages from configured channels.
3. Generate 3 PNG files in `output/stories/`.
4. Send a price list text + run report + 3 story images to you on Telegram.
5. Log `RUN COMPLETE | found=N/12 | ...` at the end.

---

## 9. Bot Commands Reference

All commands require the sender to be in the `admins` table. Non-admins are silently
ignored.

| Command | Effect |
|---|---|
| `/start` | Show admin panel with "▶️ Run Scraper Now" button |
| `/run` | Trigger the full pipeline immediately |
| `/status` | Show last run: timestamp, status, found/missing count |
| `/prices` | Show current prices for all 12 products |
| `/add_admin <user_id>` | Grant admin access to a Telegram user ID |

---

## 10. Troubleshooting

### Session expired / auth error

The userbot session occasionally expires (Telegram logs it out after long inactivity or
from a new device).

**Fix:** stop the container, re-run `create_session.py`, restart.

```bash
docker compose down
python scripts/create_session.py
docker compose up -d
```

### FloodWaitError in logs

Telegram is rate-limiting the account. The fetcher sleeps automatically and retries once.
If it happens every run, reduce the number of channels or spread reads over multiple
accounts.

### 0 prices found

Likely causes:
- Competitor channel changed its message format — update `aliases` and `regex` in
  `config.yaml` for the affected products, then `docker compose restart bot`.
- Channel is private or the userbot was not subscribed — join the channel from the
  Telegram account whose session is in `data/userbot.session`.
- Check `logs/app.log` for `WARNING: Channel ... 0 messages`.

### Story generation fails

- Check `backgrounds/` — at least one image must be present.
- Check `assets/Inter-SemiBold.ttf` — the font must exist; the story module falls back
  to Pillow's built-in font if not found, but the fallback may look poor.
- Run `python -m pytest tests/test_story.py -v` to verify image rendering works locally.

### Bot not responding

- Confirm `TELEGRAM_BOT_TOKEN` is correct in `.env`.
- Check `logs/app.log` for `Admin bot polling started`.
- Make sure the container is running: `docker compose ps`.

### Adding a new product model

1. Add a new block under `products:` in `config.yaml` (follow the existing format).
2. Update the `price_list_template:` in `config.yaml` with the new placeholder.
3. Restart: `docker compose restart bot`.
4. The DB will be updated on the next container start via `init_db.py`.

### Viewing the database directly

```bash
docker compose exec bot sqlite3 data/prices.db
```

Useful queries:

```sql
-- Current prices
SELECT canonical_name, current_price, updated_at FROM products;

-- Last 5 runs
SELECT id, started_at, status, products_found, products_missing FROM runs ORDER BY id DESC LIMIT 5;

-- List admins
SELECT telegram_id, username, added_at FROM admins;
```
