#!/bin/sh
set -e

mkdir -p data logs output ready_images backgrounds

# ── Cloud Run startup: pull persistent files from GCS ──────────────────────────
# GCS is mounted READ-ONLY at /app/gcs_data.
# SQLite cannot run on GCS FUSE (no POSIX locking), so all runtime files live on
# local disk. We copy them from GCS on startup and sync the DB back on shutdown.
if [ -n "$PORT" ] && [ -d "/app/gcs_data" ]; then
    [ -f "/app/gcs_data/userbot.session" ] \
        && cp /app/gcs_data/userbot.session data/userbot.session \
        && echo "✓ session copied from GCS"

    [ -f "/app/gcs_data/prices.db" ] \
        && cp /app/gcs_data/prices.db data/prices.db \
        && echo "✓ DB copied from GCS"

    if [ -d "/app/gcs_data/ready_images" ]; then
        cp /app/gcs_data/ready_images/*.png ready_images/ 2>/dev/null && \
            echo "✓ story images copied from GCS" || true
    fi
fi
# ── End Cloud Run startup block ─────────────────────────────────────────────────

# Guard: Telethon session must exist before the bot can read any channel.
# Create it once locally: python scripts/create_session.py
if [ ! -f "data/userbot.session" ]; then
    echo ""
    echo "ERROR: data/userbot.session not found."
    echo ""
    echo "  Create it first (run outside Docker, on the host):"
    echo "    pip install telethon python-dotenv pyyaml"
    echo "    python scripts/create_session.py"
    echo ""
    exit 1
fi

# Initialise DB schema + seed products/channels from config.yaml (idempotent)
python scripts/init_db.py

# ── Cloud Run: health server + graceful DB-sync on shutdown ────────────────────
if [ -n "$PORT" ]; then
    # Cloud Run requires the container to serve HTTP on $PORT for health checks.
    python3 -c "
import http.server, os
class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *a): pass
http.server.HTTPServer(('', int(os.environ['PORT'])), _H).serve_forever()
" &

    # On SIGTERM (Cloud Run graceful shutdown) sync the DB back to GCS so the
    # next revision starts with up-to-date price history.
    _sync_db() {
        [ -f "data/prices.db" ] || return 0
        echo "Syncing DB to GCS..."
        TOKEN=$(curl -sf \
            -H "Metadata-Flavor: Google" \
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
            | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) || return 0
        curl -sf -X POST \
            -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/octet-stream" \
            --data-binary @data/prices.db \
            "https://storage.googleapis.com/upload/storage/v1/b/price-monitor-bot-data-gentle/o?uploadType=media&name=prices.db" \
            > /dev/null && echo "✓ DB synced to GCS" || echo "WARNING: DB sync failed"
    }

    python -m src.bot &
    BOT_PID=$!
    trap '_sync_db; kill "$BOT_PID" 2>/dev/null; wait "$BOT_PID"; exit 0' TERM INT
    wait "$BOT_PID"
else
    # ── Local Docker: run bot directly as PID 1 ────────────────────────────────
    exec python -m src.bot
fi
