# Implementation Phases

Each phase ends with a clear done-condition. Phases 7 and 8 are mandatory before delivery.

---

## Phase 1 — Project Scaffold + Config + Database

**Goal:** Runnable skeleton with all infrastructure in place. No business logic yet.

**Deliverables:**
- Full directory tree created
- `.env.example`, `config.example.yaml`, `config.yaml` (with all 12 products, aliases, regexes)
- `.gitignore` (covers `.env`, `data/`, `logs/`, `output/`, `*.session`)
- `requirements.txt`
- `src/config.py` — loads `.env` + `config.yaml`, exposes typed `Settings` dataclass
- `src/db.py` — creates all 5 tables, upserts channels + products + seed admins
- `scripts/init_db.py` — runs `db.init()`, safe to re-run
- `scripts/create_session.py` — interactive Telethon session setup
- `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`

**Done when:**
```bash
python scripts/init_db.py   # exits 0, creates data/prices.db
python -c "from src.config import get_settings; print(get_settings())"  # prints Settings object
```

---

## Phase 2 — Message Fetching, Parsing, Matching

**Goal:** Given real Telegram channels, produce a `{product_id: min_price}` dict.

**Deliverables:**
- `src/fetcher.py` — Telethon channel reading, today's messages, upsert to `raw_messages`
- `src/parser.py` — full normalization pipeline (lowercase, transliterate RU→EN, strip markup, k-shorthand)
- `src/matcher.py` — two-pass product matcher + price extractor
- `tests/fixtures/sample_messages.txt` — 10+ realistic sample messages in both RU and EN formats
- `tests/test_parser.py` — covers transliteration, k-shorthand, HTML stripping
- `tests/test_matcher.py` — covers all 12 products, RU aliases, `exclude_if_contains`, no-match case

**Done when:**
```bash
python -m pytest tests/test_parser.py tests/test_matcher.py -v  # all pass
python -c "
from src.config import get_settings
from src.fetcher import fetch_messages
from src.parser import normalize
from src.matcher import match_products
# runs without error (may need real session)
"
```

---

## Phase 3 — Pricing Logic + Report Generation

**Goal:** Given a match dict, produce updated DB prices and formatted report + price list text.

**Deliverables:**
- `src/pricing.py` — applies discount rule, detects large changes, writes `price_history`, updates `products`
- `src/report.py` — builds report text and filled price list template
- `tests/test_pricing.py` — covers: price found, price not found (keep old), large change flag, first-run (no previous price)

**Done when:**
```bash
python -m pytest tests/test_pricing.py -v  # all pass
```
Manual check: run pipeline stub with mock prices, verify `products.current_price` updated in DB and report text is correctly formatted.

---

## Phase 4 — Story Image Generation

**Goal:** Given 3 background images and the current price list, produce 3 story PNGs.

**Deliverables:**
- `src/story.py` — full Pillow pipeline: resize/crop, blur, darken, panel, text, overflow guard
- `assets/Inter-SemiBold.ttf` — font file bundled in repo
- At least 1 default background in `backgrounds/` as fallback
- `scripts/download_backgrounds.py` — downloads from Google Drive into `backgrounds/`

**Done when:**
Three story images appear in `output/stories/` with:
- Correct 1080×1920 dimensions
- Readable text (no overflow, no clipping)
- Semi-transparent panel behind text
- All 12 products listed with prices

---

## Phase 5 — Telegram Delivery + Admin Bot

**Goal:** Full pipeline sends results to Telegram; admin can trigger runs and manage access via bot.

**Deliverables:**
- `src/sender.py` — Bot API: send price list text, report, 3 story images; Telethon userbot: post stories; fallback on failure
- `src/bot.py` — `python-telegram-bot` polling bot with: `/start` (trigger button), `/run`, `/status`, `/prices`, `/add_admin`; run-lock mechanism (`data/.run_lock`)
- `entrypoint.sh` updated — starts `bot.py` in background before cron

**Done when:**
- Bot responds to `/start` with inline button
- Pressing button triggers pipeline and sends results
- `/add_admin 123456789` adds new admin row to DB
- Non-admin message is ignored

---

## Phase 6 — Full Orchestration + End-to-End Run

**Goal:** `docker compose up -d` runs the complete system reliably.

**Deliverables:**
- `src/main.py` — orchestrator wiring all modules; top-level error handling; run-lock checks; structured log summary line
- `entrypoint.sh` finalized — init DB, write crontab from config, start bot, start cron
- Full end-to-end manual run via `docker compose exec bot python -m src.main`

**Done when:**
A full run from cold Docker start:
1. Fetches messages from channels
2. Finds prices for at least some products
3. Generates 3 story images in `output/stories/`
4. Sends price list + report + images to `TELEGRAM_ADMIN_ID`
5. Writes a `price_history` row for each product
6. Logs structured summary line in `logs/app.log`

---

## Phase 7 — Testing (MANDATORY)

**Goal:** Verify all logic paths work correctly without a live Telegram account.

**Deliverables:**
- `tests/test_parser.py` — complete coverage of all transliteration cases and edge cases
- `tests/test_matcher.py` — all 12 products matched from RU and EN sample messages; exclusion rules work; no false positives
- `tests/test_pricing.py` — all pricing scenarios: found/not-found/large-change/first-run
- `tests/test_report.py` — template filling, missing product fallback (`—`), large-change flag in text
- `tests/test_story.py` — story renders without exception, output file exists, correct dimensions
- `tests/fixtures/sample_messages.txt` — realistic channel messages covering all products in multiple formats

**Done when:**
```bash
python -m pytest tests/ -v --tb=short   # all tests pass, 0 failures
```

---

## Phase 8 — Instructions (MANDATORY)

**Goal:** Anyone can set up and run the system from zero using `instruction.md` alone.

**Deliverables:**
- `instruction.md` covering:
  1. Prerequisites (Python 3.11, Docker, Telegram account, Bot token)
  2. Getting Telegram API credentials from my.telegram.org
  3. Creating a bot via @BotFather
  4. Cloning repo and filling `.env` and `config.yaml`
  5. Running `create_session.py` to authenticate the userbot
  6. Adding backgrounds (manual or via `download_backgrounds.py`)
  7. Starting with Docker Compose
  8. Verifying the first run
  9. Bot commands reference
  10. Troubleshooting: session expired, flood wait, no prices found, story generation fails
- `README.md` — short project overview + link to `instruction.md` + link to demo video

**Done when:**
A person who has never seen the codebase can follow `instruction.md` and get a successful run within 30 minutes.
