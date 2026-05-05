# Phased Plan — bot_auto_competition Refactor

Reference: `new_architecture.md` for structure decisions.

---

## Decisions locked (from clarifications)

| Question | Decision |
|---|---|
| Cloud Run region | europe-west1, timezone Europe/Moscow |
| Admin auth | Password-based via `/admin` command + ADMIN_PASSWORD in .env |
| Channels persistence | DB is source of truth; config.yaml seeds initial channels but never overwrites is_active |
| Report format | Excel (.xlsx) via openpyxl — sent as Telegram document |
| Report trigger | Button in admin panel only (not automatic) |
| Manage Prices | New section — admin edits current_price per product; pipeline reads these |

---

## Status

| Phase | Status |
|---|---|
| 1 — Admin panel + Russian commands | ✅ Done |
| 2 — Competition report Excel | ✅ Done |
| 3 — Image management (complete) | ✅ Done |
| 4 — Channel management | ✅ Done (implemented in Phase 1) |
| 5 — Docker production deployment | ✅ Done |
| Scheduler — daily at 09:00 Moscow | ✅ Done |

---

---

## Phase 1 — Fix Admin Panel + Russian Commands
**Time: ~2–3 hours**
**Goal: correct, complete admin interface with all 4 functions, all text in Russian**

### Steps

**1. Split `src/bot.py` → `src/bot/` package**

Create the folder and files:
```
src/bot/__init__.py        ← empty
src/bot/auth.py            ← move _is_admin() + admin guard decorator
src/bot/keyboards.py       ← move all InlineKeyboardMarkup definitions here
src/bot/scheduler.py       ← move APScheduler setup
src/bot/app.py             ← Application build + run_polling() + set_my_commands()
src/bot/handlers/
    __init__.py
    admin.py               ← /start, /ping, /add_admin, /status, /prices
    pipeline.py            ← /run, run_now, threaded pipeline, progress cb
    images.py              ← manage_images flow (existing code, moved here)
    channels.py            ← stub: list channels from DB (read-only for now)
    report.py              ← stub: "отчёт будет в фазе 2"
```

Hint: move code file by file, not all at once. Start with `auth.py` (smallest, no deps), then `keyboards.py`, then handlers. Update `entrypoint.sh` import path: `python -m src.bot.app` instead of `python -m src.bot`.

**2. Register commands in Russian**

In `app.py`, call on startup:
```python
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("run",    "запустить пайплайн вручную"),
        BotCommand("status", "статус последнего запуска"),
        BotCommand("prices", "текущие цены по всем товарам"),
        BotCommand("ping",   "проверка доступности бота"),
    ])

app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
```

**3. Redesign /start keyboard**

Replace current keyboard in `keyboards.py`:
```python
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Запустить пайплайн", callback_data="run_now")],
        [
            InlineKeyboardButton("🖼 Управление фото",   callback_data="manage_images"),
            InlineKeyboardButton("📡 Каналы",            callback_data="manage_channels"),
        ],
        [
            InlineKeyboardButton("📊 Экспорт отчёта",   callback_data="export_report"),
            InlineKeyboardButton("💰 Текущие цены",      callback_data="show_prices"),
        ],
        [
            InlineKeyboardButton("📋 Статус",            callback_data="show_status"),
        ],
    ])
```

**4. Wire callbacks**

In `handlers/admin.py` register all callback_data values. For channels and report — stubs that reply "coming soon" in Russian until Phase 2–3.

**5. Update tests**

`tests/test_bot.py` will need import path updates: `from src.bot.handlers.admin import ...` etc.

### Done when
- `/start` shows 6 buttons, all Russian
- Telegram command menu shows Russian descriptions
- All existing functions still work
- Tests pass

---

## Phase 2 — Competition Report Export
**Time: ~2–3 hours**
**Goal: admin presses button, gets a formatted report + optional CSV**

### Steps

**1. Add `competition_report()` to `src/report.py`**

New function signature:
```python
def competition_report(run_id: int | None = None) -> tuple[str, list[dict]]:
    """
    Returns (formatted_text, rows_for_csv).
    If run_id is None, uses the latest finished run.
    """
```

Query to add to `src/db.py`:
```python
def get_competition_data(run_id: int) -> list[sqlite3.Row]:
    # SELECT ph.*, p.display_name, c.display_name as channel_name
    # FROM price_history ph
    # JOIN products p ON p.id = ph.product_id
    # LEFT JOIN channels c ON c.username = ph.source_channel
    # WHERE ph.run_id = ?
    # ORDER BY p.category, p.display_name
```

Group by product: show each channel's price, our calculated price, and a ✅/❌ indicator.

**2. Add `bot/handlers/report.py`**

```
Callback: export_report
  ↓
Reply keyboard:
  [📊 Последний запуск]  [📅 Выбрать дату (последние 7)]
  [⬅️ Назад]

User picks run
  ↓
Send formatted text (always)
Send CSV as document (InlineKeyboard option: [📎 Скачать CSV])
```

CSV generation: use Python's built-in `csv` module, send via `bot.send_document(io.BytesIO(...))`.

**3. Add test: `tests/test_report.py`**

Add test for `competition_report()` with fixture data in `price_history`.

### Done when
- "Экспорт отчёта" button opens sub-menu
- Last run report sent as Telegram message
- CSV available as document attachment

---

## Phase 3 — Image Management (Complete)
**Time: ~2 hours**
**Goal: admin can list, preview, and delete background images via bot**

### Steps

**1. Extend `bot/handlers/images.py`**

Current state: `manage_images` button exists but is incomplete.

Flows to implement:
```
manage_images
  ↓
Show: "В папке N изображений"
[👁 Листать превью]  [📤 Загрузить новое]  [⬅️ Назад]

Листать превью:
  → paginated list (5 per page)
  → each: thumbnail + filename
  → [🗑 Удалить] button per image (confirm → delete file)
  → [◀ Пред] [▶ След] pagination

Загрузить новое:
  → ConversationHandler: "Отправьте фото или документ (.jpg/.png)"
  → On receive: save to backgrounds/ with timestamp name
  → Reply: "✅ Добавлено: IMG_XXXXXXXXXX.jpg"
```

Hint: use `ConversationHandler` from `python-telegram-bot` for the upload flow. Sending previews uses `bot.send_photo(file_path)` — no DB needed, operate directly on `backgrounds/` directory.

**2. No DB changes needed** — images are filesystem-only.

### Done when
- Admin can see all background filenames + previews
- Admin can delete an image (with confirmation)
- Admin can upload a new image via chat

---

## Phase 4 — Channel Management
**Time: ~1–2 hours**
**Goal: admin can add/disable channels via bot without editing config.yaml**

### Steps

**1. Add to `src/db.py`**

```python
def add_channel(username: str, display_name: str) -> int: ...
def toggle_channel(channel_id: int) -> bool: ...  # returns new is_active state
def list_channels_full() -> list[sqlite3.Row]: ...  # all channels, active + inactive
```

**2. `bot/handlers/channels.py`**

```
manage_channels
  ↓
List all channels with status:
  @channel1 — ✅ активен   [⏸ Отключить]
  @channel2 — ✅ активен   [⏸ Отключить]
  @channel3 — ⏸ отключён  [▶️ Включить]

[➕ Добавить канал]  [⬅️ Назад]

Добавить канал:
  → ConversationHandler: "Введите @username канала"
  → "Введите название для отображения"
  → db.add_channel(username, display_name)
  → Reply: "✅ Канал добавлен и активен"
```

**Important note to document**: channels added via bot go to the DB only. If config.yaml also has that channel, it will be re-seeded on restart (upsert by username = no duplicate). Channels in config.yaml cannot be deleted via bot — they come back on restart. Document this limitation in README.

### Done when
- "Каналы" button shows all channels with status
- Admin can toggle active/inactive per channel
- Admin can add a new channel via conversation

---

## Phase 5 — Cloud Run Deployment
**Time: ~1–2 hours**
**Goal: running on Google Cloud Run with persistent GCS-backed storage**

### Steps

**1. Create `.dockerignore`**
```
data/
logs/
output/
venv/
__pycache__/
*.session
*.pyc
.env
```

**2. Create `cloudbuild.yaml`**
```yaml
substitutions:
  _REGION: europe-west1
  _SERVICE: auto-competition-bot

steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -t
      - europe-docker.pkg.dev/$PROJECT_ID/bots/$_SERVICE:$COMMIT_SHA
      - .

  - name: gcr.io/cloud-builders/docker
    args:
      - push
      - europe-docker.pkg.dev/$PROJECT_ID/bots/$_SERVICE:$COMMIT_SHA

  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - deploy
      - $_SERVICE
      - --image=europe-docker.pkg.dev/$PROJECT_ID/bots/$_SERVICE:$COMMIT_SHA
      - --region=$_REGION
      - --min-instances=1
      - --max-instances=1
      - --memory=512Mi
      - --set-env-vars=TZ=Europe/Moscow
```

**3. Create GCS buckets**
```bash
gsutil mb gs://YOUR_PROJECT-bot-data
gsutil mb gs://YOUR_PROJECT-bot-backgrounds
```

Upload session file + existing DB to data bucket:
```bash
gsutil cp data/userbot.session gs://YOUR_PROJECT-bot-data/
gsutil cp data/prices.db       gs://YOUR_PROJECT-bot-data/   # if exists
gsutil cp -r backgrounds/      gs://YOUR_PROJECT-bot-backgrounds/
```

**4. Create `service.yaml`** (Cloud Run service definition with volume mounts)
```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: auto-competition-bot
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "1"
        autoscaling.knative.dev/maxScale: "1"
    spec:
      volumes:
        - name: data-volume
          csi:
            driver: gcsfuse.run.googleapis.com
            volumeAttributes:
              bucketName: YOUR_PROJECT-bot-data
        - name: bg-volume
          csi:
            driver: gcsfuse.run.googleapis.com
            volumeAttributes:
              bucketName: YOUR_PROJECT-bot-backgrounds
              readOnly: "true"
      containers:
        - image: europe-docker.pkg.dev/YOUR_PROJECT/bots/auto-competition-bot:latest
          volumeMounts:
            - name: data-volume
              mountPath: /app/data
            - name: bg-volume
              mountPath: /app/backgrounds
          env:
            - name: TZ
              value: Europe/Moscow
          envFrom:
            - secretRef:
                name: bot-secrets   # store .env values as Cloud Run secret
```

**5. First manual deploy**
```bash
gcloud run services replace service.yaml --region=europe-west1
```

**6. Set up Cloud Build trigger**

In Google Cloud Console → Cloud Build → Triggers:
- Source: your GitHub repo, branch: `main`
- Config: `cloudbuild.yaml`

After this: `git push` → automated build + deploy.

**7. Secrets**

Store `.env` values as Google Cloud Secret Manager secrets, reference them in `service.yaml` instead of an env file.

```bash
gcloud secrets create TELEGRAM_BOT_TOKEN --data-file=- <<< "your-token"
# repeat for each secret
```

### Done when
- `git push main` triggers Cloud Build
- Container starts, mounts GCS volumes, DB and session file accessible
- Bot responds, daily schedule runs at 09:00 Moscow time
- Logs visible in Cloud Logging

---

## Summary Table

| Phase | Scope | Est. Time | Requires previous? |
|---|---|---|---|
| 1 | Admin panel + Russian commands | 2–3h | No |
| 2 | Competition report | 2–3h | Phase 1 (handler stub) |
| 3 | Image management (complete) | 2h | Phase 1 |
| 4 | Channel management | 1–2h | Phase 1 |
| 5 | Cloud Run deployment | 1–2h | Phase 1 (cleaner imports) |

Phases 2, 3, 4 are independent of each other — can be done in any order after Phase 1.
Phase 5 can be done anytime after Phase 1, doesn't need 2–4.
