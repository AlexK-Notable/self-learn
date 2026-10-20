"""The judged-uuid store: which transcript moments the session miner has
already judged (new-miner plan §3.1, "fork de-duplication").

A resumed or forked session file copies earlier entries with their ``uuid``,
and a miner that reads the copy as new counts the same moment twice. The
store holds ``{uuid: first-judged date}`` for the typed turns and assistant
text entries of every session whose output has landed, in
``<cache>/miner/judged-uuids.json``. The spine shows a typed turn whose uuid
is here as already mined, and the checker drops evidence that resolves to
one as ``already-judged``.

Rules:

- entries are added only by an explicit :meth:`JudgedUuids.add`, which the
  engine calls after a session's output has landed (in preview, never);
  loading, reading and saving add nothing;
- :meth:`JudgedUuids.prune` removes entries judged more than
  :data:`KEEP_DAYS` days ago; the engine calls it once per run (Claude Code
  removes transcripts well before that);
- :meth:`JudgedUuids.save` writes with ``fsops.atomic_write``, so a crash
  leaves the old file or the new one, never half of either.

The file is the cache, not the ledger: a missing or unreadable file reads as
an empty store (``damaged`` says which), and the worst a lost store costs is
one fork judged again.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from ..primitives import fsops

__all__ = ["KEEP_DAYS", "STORE_NAME", "JudgedUuids", "store_path"]

STORE_NAME = "judged-uuids.json"
#: Entries older than this many days are pruned.
KEEP_DAYS = 120


def store_path(cache_dir: Path | str) -> Path:
    """``<cache>/miner/judged-uuids.json`` for a ledger's cache directory
    (``worker.cache_dir(home)``)."""
    return Path(cache_dir) / "miner" / STORE_NAME


class JudgedUuids:
    """``{uuid: first-judged date}``, read from and written to ``path``."""

    def __init__(self, path: Path | str, entries: dict[str, date] | None = None, *, damaged: bool = False) -> None:
        self.path = Path(path)
        self._entries: dict[str, date] = dict(entries or {})
        #: True when the file existed but could not be read as a store.
        self.damaged = damaged

    @classmethod
    def load(cls, path: Path | str) -> "JudgedUuids":
        """The store at ``path``; empty when the file is missing. A file that
        is not a JSON object of ``uuid: "YYYY-MM-DD"`` reads as empty and
        ``damaged``; single malformed entries are skipped."""
        p = Path(path)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(p)
        except (OSError, ValueError, UnicodeDecodeError):
            return cls(p, damaged=True)
        if not isinstance(raw, dict):
            return cls(p, damaged=True)
        entries: dict[str, date] = {}
        for uid, when in raw.items():
            if not isinstance(uid, str) or not uid or not isinstance(when, str):
                continue
            try:
                entries[uid] = date.fromisoformat(when)
            except ValueError:
                continue
        return cls(p, entries)

    def __contains__(self, uid: object) -> bool:
        return isinstance(uid, str) and uid in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def judged_on(self, uid: str) -> date | None:
        return self._entries.get(uid)

    def snapshot(self) -> frozenset[str]:
        """The uuids judged so far: what a run's spines and checks read,
        fixed before any session of the run lands."""
        return frozenset(self._entries)

    def add(self, uids: Iterable[str], on: date) -> int:
        """Record ``uids`` as judged ``on`` (an existing entry keeps its
        earlier date); returns how many were new. The only way in."""
        added = 0
        for uid in uids:
            if not isinstance(uid, str) or not uid:
                continue
            old = self._entries.get(uid)
            if old is None:
                added += 1
                self._entries[uid] = on
            elif on < old:
                self._entries[uid] = on
        return added

    def prune(self, today: date) -> int:
        """Remove entries judged more than :data:`KEEP_DAYS` days before
        ``today``; returns how many went."""
        cutoff = today - timedelta(days=KEEP_DAYS)
        stale = [uid for uid, when in self._entries.items() if when < cutoff]
        for uid in stale:
            del self._entries[uid]
        return len(stale)

    def save(self) -> None:
        """Write the store atomically (``fsops.atomic_write``)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({uid: when.isoformat() for uid, when in sorted(self._entries.items())}, indent=0)
        fsops.atomic_write(self.path, body + "\n")
