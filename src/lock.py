"""
Run-lock: prevents concurrent pipeline executions within the same process.
Uses a threading.Lock so it is released automatically on process exit —
no stale lock files, no 30-minute timeouts.
"""
import threading

_lock = threading.Lock()


def acquire() -> bool:
    """Returns True if the lock was obtained, False if a run is already active."""
    return _lock.acquire(blocking=False)


def release() -> None:
    try:
        _lock.release()
    except RuntimeError:
        pass  # already released, nothing to do


def is_locked() -> bool:
    acquired = _lock.acquire(blocking=False)
    if acquired:
        _lock.release()
        return False
    return True
