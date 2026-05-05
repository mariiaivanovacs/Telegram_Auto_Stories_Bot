# Telegram Price Monitor + Story Bot

Monitors competitor Telegram channels daily, extracts prices for 12 iPhone/tech products,
calculates the owner's prices (competitor min − 500 RUB), generates 3 story images, and
delivers everything via Telegram.

## What it does

1. Reads today's messages from 2–3 competitor channels (Telethon userbot).
2. Extracts prices via regex + Russian↔English transliteration matching.
3. Calculates prices: `competitor_min − 500 RUB`.
4. Generates 3 story images (1080×1920) from background photos.
5. Sends price list text + run report + story images to the owner's Telegram.
6. Stores price history in SQLite for change tracking.
7. Flags large price changes (> 3 000 RUB) in the report.

## Monitored products

iPhone Pro 256/512/1TB, iPhone Pro Max 256/512/1TB, iPhone Air,
MacBook Neo, AirPods Pro 3, Whoop 5.0 Peak, PS5, Apple Watch S11.

## Tech stack

Python 3.11 · Telethon · python-telegram-bot · Pillow · SQLite · Docker + cron

## Quick start

See **[instruction.md](instruction.md)** for the full setup guide (prerequisites →
credentials → session → Docker → first run → troubleshooting).

## Project structure

```
src/
  main.py      — pipeline orchestrator (fetch → match → price → report → story → send)
  fetcher.py   — Telethon channel reading
  parser.py    — Russian/English text normalisation
  matcher.py   — product matching + price extraction
  pricing.py   — discount rule + large-change detection
  report.py    — report text + price list builder
  story.py     — Pillow story image renderer
  sender.py    — Bot API delivery + userbot story posting
  bot.py       — long-running admin bot (commands + inline trigger button)
  db.py        — all SQLite operations
  config.py    — settings loader (.env + config.yaml)
  lock.py      — run-lock to prevent concurrent pipeline executions

tests/         — 166 tests, all passing (pytest)
scripts/       — init_db.py, create_session.py, download_backgrounds.py
```

## Admin bot commands

`/start` · `/run` · `/status` · `/prices` · `/add_admin <id>`

All commands are restricted to users in the `admins` database table.

## Demo

*Link to demo video — record and add here.*
