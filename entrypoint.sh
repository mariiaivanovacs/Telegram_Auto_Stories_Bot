#!/bin/sh
set -e

# Ensure runtime directories exist (relevant when volumes are mounted empty)
mkdir -p data logs output ready_images

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

# Start admin bot (keeps container alive; daily scheduler runs inside it)
exec python -m src.bot
