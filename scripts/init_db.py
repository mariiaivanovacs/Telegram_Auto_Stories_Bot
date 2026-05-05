"""
One-time (and idempotent) database initialisation.
Safe to re-run: uses CREATE TABLE IF NOT EXISTS + upserts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
import src.db as db


def main():
    settings = get_settings()
    db.init(settings)
    print(f"✓ Database ready at {db.DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
