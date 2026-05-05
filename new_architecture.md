# New Architecture — bot_auto_competition

---

## 1. What's Good (Keep As-Is)

The pipeline core is clean, well-tested, and should not be touched:

| Module | Role |
|---|---|
| `config.py` | Settings loader — solid |
| `db.py` | All SQL in one place — good |
| `lock.py` | File-based concurrency lock — works fine |
| `main.py` | Pipeline orchestration — logic is correct |
| `fetcher.py` | Telethon channel reading — clean |
| `parser.py` | Russian↔Latin normalization — well-tested |
| `matcher.py` | Product regex matching + price extraction — solid |
| `pricing.py` | Discount rule + large-change detection — pure, testable |
| `story.py` | Pillow image rendering — complex but encapsulated |
| `sender.py` | Bot API + userbot delivery — works |
| `tests/` | 166+ tests — keep and extend for new features |

---

## 2. Current Problems

### Problem 1 — `bot.py` is a 450-line monolith
One file handles: admin auth guard, `/start` + 6 commands, 4 inline button flows, pipeline threading, progress callbacks, and APScheduler setup. It's impossible to navigate or extend without touching unrelated code.

### Problem 2 — Admin panel is incomplete and in English
- `/start` shows only pipeline triggers and step-testing buttons — not the 4 actual admin workflows
- BotCommand descriptions shown in Telegram are in English (should be Russian)
- "Manage channels" doesn't exist in the UI
- "Export report" doesn't exist at all

### Problem 3 — No competition report
`report.py` only builds a per-run status message. There's no way to answer "for each product, which channel had what price today, and where are we cheaper?" — the data is all in `price_history` but never surfaced.

### Problem 4 — Cloud Run not accounted for
- SQLite (`data/prices.db`), Telethon session (`data/userbot.session`), and `backgrounds/` must survive container restarts — no persistence strategy exists
- APScheduler lives inside the bot process — if Cloud Run scales to 0, the daily schedule dies
- No `cloudbuild.yaml` for automated deploys

---

## 3. Proposed Structure

Only `src/bot.py` is split into a package. Everything else stays exactly where it is.

```
src/
├── config.py           ← unchanged
├── db.py               ← minor additions: channel CRUD + competition report query
├── lock.py             ← unchanged
├── main.py             ← unchanged logic, import paths updated
├── fetcher.py          ← unchanged
├── parser.py           ← unchanged
├── matcher.py          ← unchanged
├── pricing.py          ← unchanged
├── report.py           ← add competition_report() function
├── story.py            ← unchanged
├── sender.py           ← unchanged
│
└── bot/                ← replaces bot.py (single file → package)
    ├── __init__.py
    ├── app.py          ← Application setup, run_polling(), registers commands on startup
    ├── auth.py         ← admin check decorator (extracted from bot.py)
    ├── keyboards.py    ← all InlineKeyboardMarkup layouts in one place
    ├── scheduler.py    ← APScheduler setup, isolated from handlers
    └── handlers/
        ├── __init__.py
        ├── admin.py    ← /start, /ping, /add_admin, /status, /prices
        ├── pipeline.py ← /run, run_now button, threaded execution, progress callbacks
        ├── images.py   ← manage_images flow (list, preview, delete, upload)
        ├── channels.py ← manage_channels flow (list, add, toggle active) [NEW]
        └── report.py   ← export_report flow (last run + history) [NEW]
```

### Why split bot.py this way?
- `auth.py` — imported by all handlers, never mixed with business logic
- `keyboards.py` — all button layouts in one file → easy to edit text/layout without hunting through handlers
- `scheduler.py` — isolated so it can later be replaced with a Cloud Scheduler HTTP trigger without touching handlers
- Each handler file = one admin workflow = one person can own it

---

## 4. Redesigned Admin Panel

### /start keyboard (all Russian, all 4 workflows)
```
🤖 Панель управления

[▶️ Запустить пайплайн]

[🖼 Управление фото]    [📡 Каналы]
[📊 Экспорт отчёта]    [💰 Текущие цены]

[📋 Статус]             [ℹ️ Помощь]
```

### Registered BotCommand list (Russian, shown in Telegram menu)
```
/run     — запустить пайплайн вручную
/status  — статус последнего запуска
/prices  — текущие цены по всем товарам
/ping    — проверка доступности бота
```
Registered via `set_my_commands()` in `app.py` on startup — not hardcoded in command descriptions.

---

## 5. Competition Report (New Feature)

Answers: "For today's run, which channel had which price, and where is our price better?"

### Data source
Already in DB: `price_history` table has `competitor_price`, `source_channel`, `calculated_price`, `run_id`, `product_id`.

### Format (Telegram message)
```
📊 Отчёт о конкурентах — 06.05.2026

iPhone Pro 256:
  @channel1 — 94 500 ₽
  @channel2 — 96 000 ₽
  Наша цена  — 94 000 ₽ ✅ дешевле

iPhone Pro Max 512:
  @channel1 — 112 000 ₽ (нет данных от других)
  Наша цена  — 111 500 ₽ ✅ дешевле

iPhone Air:
  Цена не найдена ❌
```

### Optional: CSV export
Same data as `.csv` file sent as Telegram document attachment.

---

## 6. Cloud Run Deployment Architecture

### Persistence problem and solution

Three paths must survive restarts:

| Path | What | Solution |
|---|---|---|
| `data/prices.db` | SQLite database | GCS bucket, mounted as volume |
| `data/userbot.session` | Telethon auth state | Same GCS bucket |
| `backgrounds/` | Story background images | Separate GCS bucket (read-only) |

Cloud Run supports GCS volume mounts natively (GA since 2024). No code changes needed — paths stay the same.

### Scheduler strategy
**Keep APScheduler** (least change). Set `min-instances: 1` so the container never scales to zero and the schedule keeps running.

If reliability becomes a problem later: replace APScheduler with a Cloud Scheduler job that POSTs to `/run` on the bot service — add one HTTP handler, remove the scheduler module.

### Deployment flow (after git push)
```
git push main
   ↓
Cloud Build trigger (cloudbuild.yaml)
   ↓
docker build → push to Artifact Registry
   ↓
gcloud run deploy (rolling update, zero downtime)
```

### Files to add for Cloud Run
```
cloudbuild.yaml        ← build + push + deploy in one trigger
service.yaml           ← Cloud Run service definition with volume mounts
.dockerignore          ← exclude data/, logs/, output/, venv/ from image
```

### Important: session file bootstrap
The `data/userbot.session` file must be created once locally (`scripts/create_session.py`) then uploaded to the GCS bucket manually before first deploy. Cloud Run cannot do interactive auth.

---

## 7. What Does NOT Change

- All pipeline logic (`fetcher`, `parser`, `matcher`, `pricing`, `story`, `sender`)
- Database schema — 8 tables are fine
- `config.yaml` format — products, channels, pricing, schedule all stay
- `.env` secrets format
- `scripts/` utilities
- `tests/` structure (import paths will update when bot.py splits)
- `Dockerfile` — minor: add `.dockerignore`, no logic changes
- `entrypoint.sh` — unchanged
- `requirements.txt` — no new dependencies needed
