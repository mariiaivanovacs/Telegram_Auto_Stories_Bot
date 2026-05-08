# Telegram Price Monitor + Story Bot

Monitors competitor Telegram channels daily, extracts prices for 12 iPhone/tech products,
calculates the owner's prices (competitor min − 500 ₽), generates story images, and
delivers everything via Telegram. All steps require admin confirmation before publishing.


Задеплоено: https://django-stripe-149209962521.us-central1.run.app
демо: https://drive.google.com/file/d/1YpG2IR7zFZfLVgscTxA6CgY6B8flnFlb/view?usp=sharing
---

## What it does

1. Reads today's messages from competitor channels via Telethon userbot.
2. Extracts prices using regex + Russian↔English transliteration matching.
3. Calculates prices: `competitor_min − 500 ₽`.
4. Flags large price changes (> 3 000 ₽) for manual admin review before applying.
5. Generates story images (1080×1920) from background photos using Pillow.
6. Sends price list + report + story images to the admin's Telegram.
7. Stores full price history in SQLite.

The pipeline is triggered manually by the admin bot or runs automatically once a day
at 09:00 Moscow time.

---

## Monitored products

iPhone Pro 256/512/1TB · iPhone Pro Max 256/512/1TB · iPhone Air ·
MacBook Neo · AirPods Pro 3 · Whoop 5.0 Peak · PS5 · Apple Watch S11

---

## Tech stack

| Layer | Library |
|---|---|
| Telegram bot | python-telegram-bot 21 |
| Userbot (channel reading) | Telethon 1.36 |
| Image generation | Pillow 10 |
| Scheduler | APScheduler 3 (cron, `Europe/Moscow`) |
| Database | SQLite via stdlib `sqlite3` |
| Config | PyYAML + python-dotenv |
| Reports | openpyxl (Excel) |
| Container | Docker + docker-compose |

---

## Project structure

```
src/
  main.py          pipeline orchestrator (fetch → match → price → story → send)
  fetcher.py       Telethon channel reader
  parser.py        text normalisation, transliteration
  matcher.py       product matching + price extraction (regex)
  pricing.py       discount rule + large-change detection
  report.py        report text + Excel builder
  story.py         Pillow story renderer
  sender.py        Bot API delivery
  ready_images.py  background → ready_images/ processing
  db.py            all SQLite operations
  config.py        settings loader (.env + config.yaml)
  lock.py          run-lock (prevents concurrent pipeline executions)

  bot/
    app.py         Application setup, handler wiring, polling start
    auth.py        admin guard (is_admin, /admin password conv)
    keyboards.py   all InlineKeyboardMarkup definitions
    scheduler.py   APScheduler daily cron setup/reschedule/teardown
    handlers/
      admin.py     /start, /ping, /status, main menu
      pipeline.py  /run, run_now, price approval flow
      images.py    background gallery, upload, delete
      channels.py  channel list + toggle + add
      prices.py    manual price editor
      report.py    Excel report generation + download
      settings.py  daily run time + max-posts-per-channel settings

scripts/
  init_db.py             DB schema init (idempotent, run by entrypoint)
  create_session.py      one-time interactive Telethon login → data/userbot.session
  download_backgrounds.py helper to bulk-download backgrounds

tests/                   pytest suite (unit + integration)
backgrounds/             source background photos (.JPG)
ready_images/            processed story images (generated, not committed)
data/                    prices.db + userbot.session (not committed)
logs/                    app.log (not committed)
assets/                  fonts + sample text
```

---

## First-time deployment (Docker on a VPS)

### Prerequisites
- Docker + docker-compose installed on the server
- Python 3.11+ available **locally** (for the one-time session step)

### Steps

```bash
# 1. Clone and configure
git clone <your-repo> && cd bot_auto_competition
cp .env.example .env          # fill in all values
cp config.example.yaml config.yaml  # set channels, products, admins

# 2. Create the Telethon userbot session (interactive, run once locally or on the server)
pip install telethon python-dotenv pyyaml
python scripts/create_session.py
# → saves data/userbot.session

# 3. Upload backgrounds (if not committed)
# copy your .JPG files into backgrounds/

# 4. Build and start
docker compose up -d --build

# 5. Verify
docker compose logs -f
```

### Updating

```bash
git pull
docker compose up -d --build
```

### Environment variables (`.env`)

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` | From https://my.telegram.org |
| `TELEGRAM_API_HASH` | From https://my.telegram.org |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_ADMIN_ID` | Your Telegram user ID |
| `TELEGRAM_PHONE` | Phone number for userbot session |
| `ADMIN_PASSWORD` | Password for `/admin` command |

---

## Admin bot

Send `/start` to get the main menu. All buttons and commands are restricted to users
in the `admins` database table.

| Action | How |
|---|---|
| Run pipeline | ▶️ Запустить пайплайн button or `/run` |
| See last run status | 📋 Статус or `/status` |
| Manage background images | 🖼 Управление фото |
| Manage competitor channels | 📡 Каналы |
| Edit current prices | 💰 Управление ценами |
| Download Excel report | 📊 Экспорт отчёта |
| Change daily run time | ⚙️ Настройки |
| Approve/reject large price changes | inline buttons during pipeline run |
| Add another admin | `/admin` → enter password |

---

## Known limitations

See [architecture.md](architecture.md) (Russian) for a detailed breakdown of design
decisions and limitations — including why AI, automatic scraping, and auto-posting
are intentionally not implemented.
