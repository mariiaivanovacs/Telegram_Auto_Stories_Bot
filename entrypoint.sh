#!/bin/sh
set -e

# Initialise DB (idempotent)
python scripts/init_db.py

# Start admin bot in foreground (keeps container alive; scheduler runs inside it)
exec python -m src.bot
