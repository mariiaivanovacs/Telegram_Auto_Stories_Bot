"""
Run-lock: prevents concurrent pipeline executions.
Uses a file marker so duplicate bot processes do not run the pipeline at the
same time. Stale lock files are ignored after timeout.
"""
from datetime import datetime, timezone
from pathlib import Path
import time

PATH = Path("data/.run_lock")
_CANCEL_PATH = Path("data/.run_cancel")
STALE_SECONDS = 30 * 60


def acquire() -> bool:
    """Returns True if the lock was obtained, False if a run is already active."""
    if PATH.exists():
        age = time.time() - PATH.stat().st_mtime
        if age <= STALE_SECONDS:
            return False
        PATH.unlink(missing_ok=True)

    _CANCEL_PATH.unlink(missing_ok=True)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return True


def release() -> None:
    PATH.unlink(missing_ok=True)
    _CANCEL_PATH.unlink(missing_ok=True)


def cancel() -> bool:
    """Signal the running pipeline to stop. Returns False if nothing is running."""
    if not is_locked():
        return False
    _CANCEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CANCEL_PATH.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return True


def is_cancelled() -> bool:
    return _CANCEL_PATH.exists()


def refresh() -> None:
    """Keep a long-running active lock from being treated as stale."""
    if PATH.exists():
        PATH.touch()


def is_locked() -> bool:
    if not PATH.exists():
        return False

    age = time.time() - PATH.stat().st_mtime
    if age > STALE_SECONDS:
        PATH.unlink(missing_ok=True)
        return False
    return True
