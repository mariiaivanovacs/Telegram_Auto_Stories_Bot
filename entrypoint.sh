#!/bin/sh
set -e

# Ensure runtime directories exist (relevant when volumes are mounted empty)
mkdir -p data logs output ready_images

# On Cloud Run, GCS is mounted at /app/gcs_data (read-only source of truth).
# SQLite cannot run on GCS FUSE (no POSIX file locking), so we keep the DB on
# local disk and only pull the session file from GCS at startup.
if [ -n "$PORT" ] && [ -d "/app/gcs_data" ]; then
    if [ -f "/app/gcs_data/userbot.session" ]; then
        cp /app/gcs_data/userbot.session data/userbot.session
        echo "Session copied from GCS to local data/"
    fi
fi

# Guard: Telethon session must be created before starting the bot.
# Run this once on the host before `docker compose up`:
#   python scripts/create_session.py
if [ ! -f "data/userbot.session" ]; then
    echo "ERROR: data/userbot.session not found."
    echo "Create it first by running on the host (outside Docker):"
    echo "  python scripts/create_session.py"
    exit 1
fi

# Initialise DB schema + seed products/channels from config.yaml (idempotent)
python scripts/init_db.py

# Cloud Run requires the container to serve HTTP on $PORT.
# When running locally (docker compose), PORT is not set, so this block is skipped.
if [ -n "$PORT" ]; then
    python3 -c "
import http.server, threading, os
class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *a): pass
http.server.HTTPServer(('', int(os.environ['PORT'])), _H).serve_forever()
" &
fi

# Start admin bot (keeps container alive; daily scheduler runs inside it)
exec python -m src.bot
