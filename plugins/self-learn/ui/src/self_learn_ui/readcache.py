"""readcache.py -- one shared, short-lived cache of the pages' CLI reads
(speed batch 2).

Home, Health and a bucket page each ran ``report --json`` (about 1.8 s) and
``status --json`` (about 1.4 s) afresh, one after another. This module is the
one place those reads are remembered between pages, under four rules:

* **Keyed on ledger state.** An entry is served only while the state it was
  read under still equals the current state: the refresh hub's generation
  (every watcher event and every finished verb bumps it, so a write made
  through this UI invalidates at once) plus the ledger's git HEAD (a commit
  made by anything else shows even before the watcher reports it). A state
  mismatch is an ordinary miss; the old entry is dropped.
* **Short expiry.** Even with an unchanged state an entry lives at most
  ``ttl`` seconds (30 by default), because some reads also carry facts from
  the cache directory (job heartbeats) that the ledger state does not cover.
  A key with ``ttl=0`` is never stored: it only shares a read in flight.
* **A failed read is never kept.** What counts as failed is the caller's
  ``keep`` test (default: ``value.ok``); a failure is still handed to every
  request that was waiting on that same read, and the next request reads again.
* **One read in flight per key and state.** A second request that needs the
  same read while it runs waits for it instead of starting another one.

Callers get an independent copy of a cached value, so a page that edits what
it was given cannot change what the next page sees. Thread-based on purpose:
the sync routes run in a worker thread pool, and async code calls in through
``asyncio.to_thread``.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["ReadCache", "READ_TTL_SECS", "head_signature"]

#: How long an unchanged-state read may be reused, in seconds. Matches the
#: header's jobs-line and inbox-count caches (routes._JOBS_LINE_TTL_SECS).
READ_TTL_SECS = 30.0


def head_signature(home: Path) -> str | None:
    """The ledger's git HEAD, read from the files (no subprocess): the
    commit id HEAD names, or HEAD's own text when it is detached or its ref
    cannot be found. ``None`` when *home* is not a git repository."""
    try:
        git_dir = Path(home) / ".git"
        if git_dir.is_file():  # a worktree/submodule pointer
            text = git_dir.read_text().strip()
            if text.startswith("gitdir:"):
                git_dir = (Path(home) / text.split(":", 1)[1].strip()).resolve()
        head = (git_dir / "HEAD").read_text().strip()
    except OSError:
        return None
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    try:
        return (git_dir / ref).read_text().strip()
    except OSError:
        pass
    try:  # a packed ref
        for line in (git_dir / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        pass
    return head


@dataclass
class _Entry:
    state: Hashable
    stamp: float
    value: Any


class ReadCache:
    def __init__(self, ttl: float = READ_TTL_SECS, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[Hashable, _Entry] = {}
        self._inflight: dict[tuple[Hashable, Hashable], Future] = {}

    def get(
        self,
        key: Hashable,
        state: Hashable,
        produce: Callable[[], Any],
        *,
        keep: Callable[[Any], bool] | None = None,
        ttl: float | None = None,
    ) -> Any:
        """The value for *key* at ledger *state*: a live cached copy, the
        result of a read already in flight, or the result of ``produce()``."""
        limit = self.ttl if ttl is None else ttl
        worth_keeping = keep if keep is not None else _is_ok
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.state != state:
                del self._entries[key]
                entry = None
            if entry is not None and self._clock() - entry.stamp >= limit:
                del self._entries[key]
                entry = None
            if entry is not None:
                return copy.deepcopy(entry.value)
            flight_key = (key, state)
            future = self._inflight.get(flight_key)
            owner = future is None
            if owner:
                future = self._inflight[flight_key] = Future()
        if not owner:
            return copy.deepcopy(future.result())
        try:
            value = produce()
        except BaseException as exc:
            with self._lock:
                self._inflight.pop(flight_key, None)
            future.set_exception(exc)
            raise
        with self._lock:
            self._inflight.pop(flight_key, None)
            if limit > 0 and worth_keeping(value):
                self._entries[key] = _Entry(state, self._clock(), copy.deepcopy(value))
        future.set_result(value)
        return copy.deepcopy(value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _is_ok(value: Any) -> bool:
    return bool(getattr(value, "ok", False))
