"""The judged-uuid store: which transcript moments the session miner has
already judged (new-miner plan §3.1, "fork de-duplication").

A resumed or forked session file copies earlier entries with their ``uuid``,
and a miner that reads the copy as new counts the same moment twice. The
store holds, for every session whose output has landed:

1. the uuid of each typed turn in its judged lines;
2. the uuid of each assistant text entry in its judged lines;
3. every uuid a landed item cited (evidence, steps, verification, incident
   cost, a rule check's situation) -- what stops a fork re-landing a
   parent's moment, whatever kind of entry it was.

``Spine.moment_uuids`` gives (1) and (2), ``check.landed_uuids`` all three.
The spine shows a typed turn whose uuid is here as already mined, and the
checker drops evidence that resolves to one as ``already-judged``.

The store is a small SQLite file in the cache,
``<cache>/miner/judged-uuids.sqlite``: one table, ``judged(uuid TEXT
PRIMARY KEY, first_judged TEXT)``, the date as ``YYYY-MM-DD``. Rules:

- rows are added only by an explicit :meth:`JudgedUuids.add` (``INSERT OR
  IGNORE``: a moment keeps the date it was first judged), which the engine
  calls after a session's output has landed (in preview, never); reading
  adds nothing. A run's spines and checks read :meth:`JudgedUuids.snapshot`,
  taken once before the run, not the store itself (each lookup on the store
  opens the file);
- :meth:`JudgedUuids.prune` is one ``DELETE`` of the rows judged more than
  :data:`KEEP_DAYS` days ago; the engine calls it once per run (Claude Code
  removes transcripts well before that);
- every call opens its own connection and closes it before returning, so a
  connection is never shared between threads; each write is one
  transaction.

The file is the cache, not the ledger: a missing file is an empty store, and
an unreadable one reads as empty. The worst a lost store costs is one fork
judged again. Two ways a read can fail are told apart (R2, 2026-10-19):

- ``locked``: another process held the file past the busy timeout. The file
  is fine; this read saw nothing, and the next one will.
- ``damaged``: the file is not a readable store (not SQLite, or a corrupt
  image). :meth:`JudgedUuids.rebuild` moves it aside and the store starts
  empty; a locked file is never rebuilt.

Reads open the file read-write (never creating it). A read-only connection
cannot roll back the hot journal a crash in the middle of :meth:`add`
leaves behind, and fails ("attempt to write a readonly database"); read
-write, SQLite rolls the journal back and the read sees every row the last
finished write left (measured 2026-10-19).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

__all__ = ["KEEP_DAMAGED", "KEEP_DAYS", "STORE_NAME", "JudgedUuids", "is_lock_timeout", "prune_damaged", "store_path"]

STORE_NAME = "judged-uuids.sqlite"
#: Rows judged more than this many days ago are pruned.
KEEP_DAYS = 120
#: Damaged stores moved aside (:meth:`JudgedUuids.rebuild`) that are kept,
#: newest first; older ones are deleted.
KEEP_DAMAGED = 3

_SCHEMA = "CREATE TABLE IF NOT EXISTS judged (uuid TEXT PRIMARY KEY, first_judged TEXT NOT NULL)"


def is_lock_timeout(exc: BaseException) -> bool:
    """True when ``exc`` is SQLite giving up on a lock another connection
    holds (``database is locked``, or a busy table) -- never a sign that
    the file is damaged."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def store_path(cache_dir: Path | str) -> Path:
    """``<cache>/miner/judged-uuids.sqlite`` for a ledger's cache directory
    (``worker.cache_dir(home)``)."""
    return Path(cache_dir) / "miner" / STORE_NAME


class JudgedUuids:
    """``{uuid: first-judged date}`` in the SQLite file at ``path``."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        #: True when the file exists but is not a readable store.
        self.damaged = False
        #: True when a read gave up on a lock another process held.
        self.locked = False
        #: Seconds a connection waits on another's lock before giving up.
        self.timeout = 5.0

    @classmethod
    def load(cls, path: Path | str) -> "JudgedUuids":
        """The store at ``path``, with ``damaged`` set when the file exists
        but is not a readable store, and ``locked`` when the read gave up on
        a lock. Writes nothing of its own (a crash's hot journal is rolled
        back by SQLite, module docstring)."""
        store = cls(path)
        if store.path.exists():
            store._safe_read("SELECT count(*) FROM judged")
        return store

    # ---- connections: one per call, closed before it returns

    def _read(self, sql: str, args: tuple = ()) -> list[tuple]:
        """Rows of a read; none when the file does not exist yet."""
        if not self.path.exists():
            return []
        # read-write, never create: a read-only connection cannot roll back
        # a crash's hot journal and would read nothing (module docstring)
        uri = self.path.resolve().as_uri() + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=self.timeout)) as db:
            try:
                return db.execute(sql, args).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc):
                    return []
                raise

    def _safe_read(self, sql: str, args: tuple = ()) -> list[tuple]:
        """:meth:`_read`, with a failure read as no rows: ``locked`` when
        the read gave up on a lock, else ``damaged``."""
        try:
            return self._read(sql, args)
        except sqlite3.Error as exc:
            if is_lock_timeout(exc):
                self.locked = True
            else:
                self.damaged = True
            return []

    def _write(self, sql: str, rows: list[tuple]) -> int:
        """Run ``sql`` once per row, in one transaction; how many rows changed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(self.path), timeout=self.timeout)) as db:
            with db:  # one transaction
                db.execute(_SCHEMA)
                before = db.total_changes
                db.executemany(sql, rows)
                return db.total_changes - before

    # ---- reads

    def __contains__(self, uid: object) -> bool:
        if not isinstance(uid, str):
            return False
        return bool(self._safe_read("SELECT 1 FROM judged WHERE uuid = ?", (uid,)))

    def __len__(self) -> int:
        rows = self._safe_read("SELECT count(*) FROM judged")
        return int(rows[0][0]) if rows else 0

    def judged_on(self, uid: str) -> date | None:
        rows = self._safe_read("SELECT first_judged FROM judged WHERE uuid = ?", (uid,))
        return date.fromisoformat(rows[0][0]) if rows else None

    def snapshot(self) -> frozenset[str]:
        """Every uuid judged so far: what a run's spines and checks read,
        fixed before any session of the run lands."""
        return frozenset(r[0] for r in self._safe_read("SELECT uuid FROM judged"))

    # ---- writes

    def rebuild(self, now: datetime | None = None) -> Path | None:
        """Move a damaged store aside (``<name>.damaged-<UTC time>``, with
        its journal) so the next write starts an empty one; returns where it
        went, or None when there was nothing to move. Only for ``damaged``:
        a ``locked`` store is a good file someone else is using, and is
        never moved."""
        if self.locked or not self.damaged or not self.path.exists():
            return None
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        aside = self.path.with_name(f"{self.path.name}.damaged-{stamp}")
        os.replace(self.path, aside)
        journal = self.path.with_name(self.path.name + "-journal")
        if journal.exists():
            os.replace(journal, aside.with_name(aside.name + "-journal"))
        self.damaged = False
        return aside

    def add(self, uids: Iterable[str], on: date) -> int:
        """Record ``uids`` as judged ``on`` (``INSERT OR IGNORE``: an existing
        row keeps its date); returns how many were new. The only way in."""
        rows = sorted({(u, on.isoformat()) for u in uids if isinstance(u, str) and u})
        if not rows:
            return 0
        return self._write("INSERT OR IGNORE INTO judged (uuid, first_judged) VALUES (?, ?)", rows)

    def prune(self, today: date) -> int:
        """Delete the rows judged more than :data:`KEEP_DAYS` days before
        ``today``, in one statement; returns how many went."""
        if not self.path.exists():
            return 0
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
        return self._write("DELETE FROM judged WHERE first_judged < ?", [(cutoff,)])


def prune_damaged(path: Path | str, *, keep: int = KEEP_DAMAGED) -> int:
    """Delete all but the ``keep`` newest damaged stores moved aside next to
    ``path`` (``<name>.damaged-<UTC time>``, with their journals); returns
    how many went. The name's time sorts them."""
    path = Path(path)
    asides = sorted(
        (p for p in path.parent.glob(f"{path.name}.damaged-*") if not p.name.endswith("-journal")),
        key=lambda p: p.name, reverse=True,
    )
    gone = 0
    for aside in asides[keep:]:
        aside.unlink(missing_ok=True)
        aside.with_name(aside.name + "-journal").unlink(missing_ok=True)
        gone += 1
    return gone
