"""Lock a permanent sibling sidecar on local NTFS, leaving the data fd borrowed."""

from __future__ import annotations

import contextlib
import errno
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from .locks import Lease, _held_locks, _Purpose

if sys.platform != "win32":
    raise NotImplementedError("native Windows locking requires Windows")

import msvcrt

import pywintypes
import win32con
import win32file
from portalocker import LockFlags
from portalocker.exceptions import AlreadyLocked, LockException
from portalocker.portalocker import Win32Locker


def _shared_fd(path: str, flags: int) -> int:
    access = win32con.GENERIC_READ
    if flags & os.O_RDWR:
        access |= win32con.GENERIC_WRITE
    elif flags & os.O_WRONLY:
        access = win32con.GENERIC_WRITE
    sharing = win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE
    creation = win32con.CREATE_ALWAYS if flags & os.O_TRUNC else win32con.OPEN_ALWAYS
    try:
        handle = win32file.CreateFile(path, access, sharing, None, creation,
                                      win32con.FILE_ATTRIBUTE_NORMAL, None)
    except pywintypes.error as exc:
        raise OSError(None, exc.strerror, path, exc.winerror) from exc
    try:
        fd = msvcrt.open_osfhandle(int(handle), flags | os.O_NOINHERIT)
    except BaseException:
        handle.Close()
        raise
    handle.Detach()  # The CRT now owns the handle.
    return fd


def open_lock(path: Path, *, purpose: _Purpose) -> IO[Any]:
    if purpose == "private":
        return open(path, "r+b", buffering=0, opener=_shared_fd)
    if purpose == "probe":
        return open(path, "rb", buffering=0, opener=_shared_fd)
    if purpose == "truncate":
        return open(path, "w", encoding="utf-8", opener=_shared_fd)
    if purpose == "append":
        return open(path, "a", encoding="utf-8", opener=_shared_fd)
    if purpose == "append-read":
        return open(path, "a+", encoding="utf-8", opener=_shared_fd)
    raise ValueError(f"unknown lock purpose {purpose!r}")


def acquire(fd: int, *, path: Path, wait: float | None, poll: float = 0.02,
            close_scoped: bool = False) -> Lease:
    deadline = None if wait is None else time.monotonic()
    locker = Win32Locker()
    sibling = path.with_name(path.name + ".lck")
    sidecar = open_lock(sibling, purpose="private")
    os.set_inheritable(sidecar.fileno(), True)

    def release(_fd: int) -> None:
        if sidecar.closed:
            return
        try:
            locker.unlock(sidecar)
        except LockException as exc:
            raise OSError(f"unlock {sibling}: {exc}") from None
        finally:
            sidecar.close()

    try:
        while True:
            try:
                locker.lock(sidecar, LockFlags.EXCLUSIVE | LockFlags.NON_BLOCKING)
                return Lease(fd, release)
            except AlreadyLocked as exc:
                if deadline is not None and time.monotonic() >= deadline:
                    raise BlockingIOError(errno.EWOULDBLOCK, "lock held", sibling) from exc
                time.sleep(poll)
            except LockException as exc:
                raise OSError(f"lock {sibling}: {exc}") from exc
    except BaseException:
        sidecar.close()
        raise


def acquire_ledger_target(fd: int) -> Lease:
    target = Path(win32file.GetFinalPathNameByHandle(msvcrt.get_osfhandle(fd), 0))
    return acquire(fd, path=target, wait=None)


def unlock(fd: int) -> None:
    """Without a lease there is no owned sidecar to release."""


def held_here(path: Path) -> bool:
    return str(path) in _held_locks


@contextlib.contextmanager
def repo_section(path: Path, timeout: float, wedged_by: str, *,
                 timeout_error: type[Exception]) -> Iterator[None]:
    key = str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_lock(path, purpose="private") as metadata:
        try:
            lease = acquire(metadata.fileno(), path=path, wait=timeout)
        except BlockingIOError:
            raise timeout_error(
                f"{wedged_by} lock {path} still held after "
                f"{timeout:g}s — another self-learn producer "
                f"(worker/miner/verb) is wedged mid-{wedged_by}"
            ) from None
        with lease:
            _held_locks.add(key)
            try:
                with contextlib.suppress(OSError):
                    metadata.write(f"{os.getpid()}\n".encode("ascii"))
                    metadata.truncate()
                    metadata.flush()
                yield
            finally:
                _held_locks.discard(key)


def retire_if_idle(path: Path) -> bool:
    return True
