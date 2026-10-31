"""Removing cache directories and lock files that belong to nothing
(S-99).

``${XDG_CACHE_HOME:-~/.cache}/self-learn`` holds two kinds of entry that
can outlive what they were made for:

- ``home-<sha256(home path)[:8]>/`` -- one per ledger home (doc 13 §6).
  The name is a one-way hash, so by itself it cannot say which home it
  belonged to. :func:`record_home` therefore writes the home's path into
  ``<dir>/.home`` the first time ``worker.cache_dir`` creates or touches
  the directory, and :func:`prune` reads it back: a directory whose
  recorded home no longer exists, and whose files have not changed for a
  week, is removed.
- ``host-<slug>.commit.lock`` -- the commit lock of a plain host
  (``gitops.host_lock_path``). A lock file is only a rendezvous point, so
  one that nobody holds and nobody has taken for a month is removed (one
  under a ``/tmp`` host path, a day).

What it never removes:

- the cache of a home that exists, or of a home the caller names in
  ``keep_homes`` (the serving daemon passes its own);
- a ``home-*`` directory with no ``.home`` record, or whose record does not
  hash to the directory's own name (it cannot be attributed, so it is
  counted and left alone);
- anything with a file changed inside the idle window (a drive that is
  only unmounted for a few days keeps its cache);
- a lock file somebody holds, or any entry that is not one of the two
  shapes above (``autosync-pause.lock`` and the landing state are not
  ours to judge).

Everything here is cache: never a repo's truth, never load-bearing state.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .ledger import resolve_home
from .primitives import fsops

__all__ = [
    "HOME_POINTER",
    "HOME_MIN_IDLE_SECS",
    "LOCK_MIN_IDLE_SECS",
    "TMP_LOCK_MIN_IDLE_SECS",
    "PruneResult",
    "cache_root",
    "home_digest",
    "prune",
    "read_home_pointer",
    "record_home",
]

#: The file inside a ``home-<digest>`` directory that names its home.
HOME_POINTER = ".home"

#: How long an orphaned home cache must sit untouched before it goes.
HOME_MIN_IDLE_SECS = 7 * 86400
#: How long an unheld host lock file must sit untouched before it goes.
LOCK_MIN_IDLE_SECS = 30 * 86400
#: Same, for a lock whose host path is under ``/tmp`` (test and scratch
#: hosts: the slug of ``/tmp/x`` begins ``-tmp-``).
TMP_LOCK_MIN_IDLE_SECS = 86400

_HOME_DIR_RE = re.compile(r"home-([0-9a-f]{8})")
_LOCK_FILE_RE = re.compile(r"host-.+\.commit\.lock")


@dataclass
class PruneResult:
    """What one :func:`prune` pass did (or, with ``dry_run``, would do)."""

    removed_homes: list[str] = field(default_factory=list)
    removed_locks: list[str] = field(default_factory=list)
    #: ``home-*`` directories left alone because they carry no usable
    #: ``.home`` record.
    unattributed: int = 0
    #: Orphaned directories / unheld locks left because they are too recent.
    too_recent: int = 0
    errors: list[str] = field(default_factory=list)


def cache_root() -> Path:
    """``${XDG_CACHE_HOME:-~/.cache}/self-learn``, with no side effects."""
    raw = os.environ.get("XDG_CACHE_HOME")
    base = Path(raw).expanduser() if raw else Path("~/.cache").expanduser()
    return base / "self-learn"


def home_digest(home: Path | str) -> str:
    """The 8-hex-digit namespace key ``worker.cache_dir`` uses."""
    return hashlib.sha256(str(Path(home).expanduser()).encode("utf-8")).hexdigest()[:8]


def record_home(cache: Path, home: Path | str) -> None:
    """Write *home* into ``cache/.home`` unless it is already there. Never
    raises: a cache directory that cannot be annotated is merely one the
    pruner will not touch."""
    try:
        want = str(Path(home).expanduser())
        pointer = cache / HOME_POINTER
        try:
            if pointer.read_text(encoding="utf-8").strip() == want:
                return
        except OSError:
            pass
        fsops.atomic_write(pointer, want + "\n")
    except OSError:
        pass


def read_home_pointer(cache: Path) -> Path | None:
    """The home recorded in ``cache/.home``, or ``None`` when there is no
    usable record (missing, unreadable, empty, or not an absolute path)."""
    try:
        text = (cache / HOME_POINTER).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not text or "\n" in text or "\0" in text or not os.path.isabs(text):
        return None
    return Path(text)


def _gone(path: Path) -> bool:
    """True only when *path* is positively absent. Any other failure to
    look (permissions, I/O) reads as "may still exist"."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return False


def _newest_mtime(directory: Path) -> float:
    """Newest modification time of *directory* and everything under it
    (symlinks are not followed)."""
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        for name in [dirpath, *(os.path.join(dirpath, n) for n in (*dirnames, *filenames))]:
            try:
                newest = max(newest, os.lstat(name).st_mtime)
            except OSError:
                continue
    return newest


def _prune_homes(
    root: Path, keep: set[str], now: float, dry_run: bool, out: PruneResult
) -> None:
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return
    for name in names:
        match = _HOME_DIR_RE.fullmatch(name)
        if not match:
            continue
        directory = root / name
        if directory.is_symlink() or not directory.is_dir():
            continue
        if match.group(1) in keep:
            continue
        home = read_home_pointer(directory)
        if home is None or home_digest(home) != match.group(1):
            out.unattributed += 1
            continue
        if not _gone(home):
            continue
        if now - _newest_mtime(directory) < HOME_MIN_IDLE_SECS:
            out.too_recent += 1
            continue
        if not dry_run:
            try:
                shutil.rmtree(directory)
            except OSError as exc:
                out.errors.append(f"{name}: {exc}")
                continue
        out.removed_homes.append(name)


def _remove_if_unheld(path: Path) -> bool:
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


def _prune_locks(root: Path, now: float, dry_run: bool, out: PruneResult) -> None:
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return
    for name in names:
        if not _LOCK_FILE_RE.fullmatch(name):
            continue
        path = root / name
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if not os.path.isfile(path) or path.is_symlink():
            continue
        limit = TMP_LOCK_MIN_IDLE_SECS if name.startswith("host--tmp-") else LOCK_MIN_IDLE_SECS
        if now - st.st_mtime < limit:
            out.too_recent += 1
            continue
        if dry_run:
            out.removed_locks.append(name)
        elif _remove_if_unheld(path):
            out.removed_locks.append(name)


def prune(
    *,
    root: Path | None = None,
    keep_homes: Iterable[Path | str] = (),
    now: float | None = None,
    dry_run: bool = False,
) -> PruneResult:
    """One pass over the cache root. The ambient ``SELF_LEARN_HOME`` is
    always kept, on top of *keep_homes*. Never raises."""
    result = PruneResult()
    try:
        base = root if root is not None else cache_root()
        stamp = now if now is not None else time.time()
        keep = {home_digest(h) for h in keep_homes}
        keep.add(home_digest(resolve_home()))
        _prune_homes(base, keep, stamp, dry_run, result)
        _prune_locks(base, stamp, dry_run, result)
    except Exception as exc:  # noqa: BLE001 -- housekeeping must never break its caller
        result.errors.append(f"{type(exc).__name__}: {exc}")
    return result
