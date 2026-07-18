"""prefetch.py — the U16/Y-19 next-record prefetch cache (queue-walk
item 1; survey ``docs/specs/self-learn/research/2026-07-18-ux-enhancement-
survey.md`` §2 Q2 P2b, shortlisted #1).

While a user reads record N's Detail page, ``routes.py`` schedules a
background task that reads (never a model turn — CLI reads + a plain
Python dataclass, no ``claude -p``) and caches record N+1's Detail
bundle, so the post-confirm ``HX-Redirect`` queue-walk hop can skip the
subprocess-read stall on arrival.

Single-slot by design: the queue-walk only ever has ONE live "next"
candidate (record N+1 while N is on screen) — a dict keyed by id would
carry entries nothing will ever ask for again, and the queue-walk always
resolves records in order, so nothing benefits from remembering more
than the one most recently warmed id.

CRITICAL staleness rule (never relaxed): a cached entry is valid ONLY
while its stamped generation still equals the CURRENT generation of the
:class:`self_learn_ui.ledger.RefreshHub` it was stamped against. Every
refresh the hub ever publishes — a watchfiles-detected file change OR a
completed verb, regardless of scope, regardless of which record the verb
touched — bumps that generation (see ``RefreshHub``'s docstring for why
this must be GLOBAL rather than per-record: 09 §2.3's surface-fill datum
makes routing record X change what a rendering of unrelated record Y
should show). A generation mismatch is treated as an ordinary cache miss
— :func:`DetailPrefetchCache.get` returns ``None`` and clears the stale
entry, the caller falls through to a fresh read. There is no code path
that can serve a stale entry: a `get` either returns a bundle read after
the currently-observed generation, or it returns nothing.

Ephemeral by construction, same posture as the pane proposal slot and
the scan-blocked badge map (09 §3 / §11 Y-14): in-memory only, cleared
implicitly on process restart or idle-exit. The worst case of a lost
warm entry is one ordinary cache miss — never a correctness issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

__all__ = ["DetailPrefetchCache"]

T = TypeVar("T")


@dataclass(frozen=True)
class _Entry(Generic[T]):
    key: str
    generation: int
    value: T


class DetailPrefetchCache(Generic[T]):
    """Holds at most one warmed entry, generation-gated. Generic over the
    cached value's type so this module carries no dependency on
    ``routes.py``'s ``DetailReadBundle`` shape."""

    def __init__(self) -> None:
        self._entry: _Entry[T] | None = None

    def get(self, key: str, generation: int) -> T | None:
        """``None`` on a miss OR a stale hit — the caller never has to
        ask which; both mean "read fresh". A KEY mismatch leaves any
        held entry untouched (it may still be a perfectly valid warm
        copy of a DIFFERENT record — a lookup for one key must never
        evict another key's live entry). A GENERATION mismatch on a
        matching key drops the entry immediately, so it can never be
        misread by a later lookup at its own (now-stale) generation."""
        entry = self._entry
        if entry is None or entry.key != key:
            return None
        if entry.generation != generation:
            self._entry = None
            return None
        return entry.value

    def put(self, key: str, generation: int, value: T) -> None:
        self._entry = _Entry(key=key, generation=generation, value=value)

    def clear(self) -> None:
        self._entry = None

    def peek_generation(self, key: str) -> int | None:
        """Test/debug hook: the stamped generation of the currently held
        entry for *key*, or ``None`` if nothing is held for it. Never
        used by production code — production code only ever calls
        :meth:`get`."""
        entry = self._entry
        if entry is None or entry.key != key:
            return None
        return entry.generation
