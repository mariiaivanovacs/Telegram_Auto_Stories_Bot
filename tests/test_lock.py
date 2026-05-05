import os
import time

import pytest

import src.lock as lock


@pytest.fixture(autouse=True)
def isolated_lock(tmp_path, monkeypatch):
    """Redirect the lock file to a temp directory for every test."""
    p = tmp_path / ".run_lock"
    monkeypatch.setattr(lock, "PATH", p)
    yield p
    if p.exists():
        p.unlink()


# ── acquire ────────────────────────────────────────────────────────────────────

def test_acquire_returns_true_when_no_lock(isolated_lock):
    assert lock.acquire() is True


def test_acquire_creates_lock_file(isolated_lock):
    lock.acquire()
    assert isolated_lock.exists()


def test_acquire_writes_timestamp(isolated_lock):
    lock.acquire()
    content = isolated_lock.read_text()
    assert "T" in content or "-" in content  # ISO-8601 contains T or dashes


def test_acquire_returns_false_when_already_locked(isolated_lock):
    assert lock.acquire() is True
    assert lock.acquire() is False


def test_acquire_does_not_overwrite_fresh_lock(isolated_lock):
    lock.acquire()
    first_content = isolated_lock.read_text()
    lock.acquire()  # should fail silently
    assert isolated_lock.read_text() == first_content


# ── release ────────────────────────────────────────────────────────────────────

def test_release_removes_lock_file(isolated_lock):
    lock.acquire()
    lock.release()
    assert not isolated_lock.exists()


def test_release_is_idempotent(isolated_lock):
    lock.release()  # no file — should not raise
    lock.release()  # again — should not raise


def test_release_allows_reacquire(isolated_lock):
    lock.acquire()
    lock.release()
    assert lock.acquire() is True


# ── is_locked ──────────────────────────────────────────────────────────────────

def test_is_locked_false_when_no_file(isolated_lock):
    assert lock.is_locked() is False


def test_is_locked_true_after_acquire(isolated_lock):
    lock.acquire()
    assert lock.is_locked() is True


def test_is_locked_false_after_release(isolated_lock):
    lock.acquire()
    lock.release()
    assert lock.is_locked() is False


# ── stale lock handling ────────────────────────────────────────────────────────

def _make_stale(path, age_seconds: int = 31 * 60) -> None:
    """Write a lock file and backdate its mtime to simulate a stale lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stale")
    old_time = time.time() - age_seconds
    os.utime(path, (old_time, old_time))


def test_is_locked_false_for_stale_lock(isolated_lock):
    _make_stale(isolated_lock)
    assert lock.is_locked() is False


def test_acquire_removes_stale_lock_and_succeeds(isolated_lock):
    _make_stale(isolated_lock)
    result = lock.acquire()
    assert result is True
    assert isolated_lock.exists()
    # Content should now be fresh (not "stale")
    assert isolated_lock.read_text() != "stale"


def test_acquire_respects_fresh_lock(isolated_lock):
    # A lock just 1 second old — not stale
    _make_stale(isolated_lock, age_seconds=1)
    assert lock.acquire() is False


def test_stale_threshold_boundary(isolated_lock, monkeypatch):
    monkeypatch.setattr(lock, "STALE_SECONDS", 60)
    _make_stale(isolated_lock, age_seconds=61)
    assert lock.acquire() is True


# ── concurrent-use simulation ──────────────────────────────────────────────────

def test_acquire_release_cycle(isolated_lock):
    for _ in range(3):
        assert lock.acquire() is True
        assert lock.is_locked() is True
        lock.release()
        assert lock.is_locked() is False
