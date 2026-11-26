"""The flock operations shared by CLI writers, probes and cache retirement."""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from .locks import Lease, _held_locks, _Purpose


def open_lock(path: Path, *, purpose: _Purpose) -> IO[Any]:
    if purpose == "truncate":
        return open(path, "w", encoding="utf-8")
    if purpose == "append":
        return open(path, "a", encoding="utf-8")
    if purpose == "append-read":
        return open(path, "a+", encoding="utf-8")
    if purpose == "private":
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        mode = "r+b"
    elif purpose == "probe":
        fd = os.open(str(path), os.O_RDONLY | os.O_CREAT)
        mode = "rb"
    else:
        raise ValueError(f"unknown lock purpose {purpose!r}")
    try:
        return os.fdopen(fd, mode, buffering=0)
    except BaseException:
        os.close(fd)
        raise


def unlock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)


def _try_until(fd: int, deadline: float, poll: float) -> None:
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll)


def acquire(fd: int, *, wait: float | None, poll: float = 0.02,
            close_scoped: bool = False) -> Lease:
    if wait is None:
        fcntl.flock(fd, fcntl.LOCK_EX)
    else:
        _try_until(fd, time.monotonic() + wait, poll)
    return Lease(fd, None if close_scoped else unlock)


def held_here(path: Path) -> bool:
    return str(path) in _held_locks


@contextlib.contextmanager
def repo_section(path: Path, timeout: float, wedged_by: str, *,
                 timeout_error: type[Exception]) -> Iterator[None]:
    key = str(path)
    if key in _held_locks:  # already ours — nesting must not self-deadlock
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open_lock(path, purpose="truncate")
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_until(fh.fileno(), deadline, 0.02)
            except BlockingIOError:
                raise timeout_error(
                    f"{wedged_by} lock {path} still held after "
                    f"{timeout:g}s — another self-learn producer "
                    f"(worker/miner/verb) is wedged mid-{wedged_by}"
                ) from None
            # S-99: `cache_gc.prune` may unlink an idle lock file.
            # A lock taken on a file that was unlinked after we opened it
            # excludes nobody (the next opener creates a fresh file), so
            # confirm the file we hold is still the one at `path`, and
            # start over on a fresh one if not.
            try:
                same = os.fstat(fh.fileno()).st_ino == os.stat(path).st_ino
            except OSError:
                same = False
            if same:
                break
            fh.close()
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = open_lock(path, purpose="truncate")
        lease = Lease(fh.fileno(), unlock)
        _held_locks.add(key)
        try:
            with contextlib.suppress(OSError):
                fh.write(f"{os.getpid()}\n")
                fh.flush()
            yield
        finally:
            _held_locks.discard(key)
            lease.release()
    finally:
        fh.close()


def retire_if_idle(path: Path) -> bool:
    """Unlink the lock file at *path* iff this process can take its flock
    right now and the locked file is still the one at *path*.
    ``gitops._flock_lock`` re-checks the same thing after it locks, so a
    process that opened the old file just before the unlink retries on a
    fresh one instead of holding a lock nobody else can see."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # held (EWOULDBLOCK) or unlockable: not ours to remove
            return False
        try:
            if os.stat(path).st_ino != os.fstat(fd).st_ino:
                return False
            os.unlink(path)
            return True
        except OSError:
            return False
    finally:
        os.close(fd)  # closing drops the flock
