"""Private lock interface. Importing a caller does not load a kernel backend."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal

_Purpose = Literal["truncate", "append", "append-read", "private", "probe"]
_held_locks: set[str] = set()


class Lease:
    """A held lock on a borrowed fd. Only a successful unlock consumes it."""

    def __init__(self, fd: int, unlock: Callable[[int], None] | None) -> None:
        self._fd = fd
        self._unlock = unlock

    def release(self) -> None:
        if self._unlock is not None:
            self._unlock(self._fd)
            self._unlock = None

    def __enter__(self) -> Lease:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.release()


def _backend():
    if os.name == "nt":
        from . import _locks_windows

        return _locks_windows
    from . import _locks_posix

    return _locks_posix


def open_lock(path: Path, *, purpose: _Purpose) -> IO[Any]:
    return _backend().open_lock(path, purpose=purpose)


def acquire(fd: int, *, path: Path, wait: float | None, poll: float = 0.02,
            close_scoped: bool = False) -> Lease:
    # Windows uses the path to locate the sidecar. POSIX locks the borrowed fd.
    if os.name == "nt":
        return _backend().acquire(fd, path=path, wait=wait, poll=poll, close_scoped=close_scoped)
    return _backend().acquire(fd, wait=wait, poll=poll, close_scoped=close_scoped)


def acquire_ledger_target(fd: int) -> Lease:
    """Tracked telemetry append inside ledger_write."""
    if os.name == "nt":
        return _backend().acquire_ledger_target(fd)
    return _backend().acquire(fd, wait=None)


def release_open(fd: int, lease: Lease | None) -> None:
    if lease is None:
        _backend().unlock(fd)
    else:
        lease.release()


@contextmanager
def repo_section(path: Path, timeout: float, wedged_by: str, *,
                 timeout_error: type[Exception]) -> Iterator[None]:
    with _backend().repo_section(path, timeout, wedged_by, timeout_error=timeout_error):
        yield


def held_here(path: Path) -> bool:
    return _backend().held_here(path)


def retire_if_idle(path: Path) -> bool:
    return _backend().retire_if_idle(path)


def can_retire_idle() -> bool:
    return os.name != "nt"
