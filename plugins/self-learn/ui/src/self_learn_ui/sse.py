"""sse.py — ``GET /events`` (10 §1 "SSE protocol" row): the pinned
envelope types, JSON-encoded, one ``type`` field each. Client
(``app.js``) is an ``EventSource``; reconnect is automatic
(browser-native) plus the 09 §5 10s poll fallback (app.js-side).

Two upstream sources merge into one outgoing stream:

- :class:`self_learn_ui.ledger.RefreshHub` (U2) — file-watcher-driven
  ``refresh`` envelopes, re-emitted here as
  ``{"type": "refresh", "scope": ...}``.
- :class:`AppEventHub` (this module) — everything else: ``applying``
  (wrapped around each verb-runner call — 09 §3: "further resolution
  submissions are disabled with a visible 'applying…' state"),
  ``bulk_progress`` (the bulk-graduate loop), ``banner`` (resolved-
  elsewhere / bucket-clear). Deliberately envelope-agnostic — a future
  U6 publishing ``pane_delta``/``pane_block``/``pane_tool``/``pane_result``
  needs zero changes here.

Unknown envelope types are ignored client-side (10 §1); this module
never filters — it is a pure relay.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from .ledger import RefreshEvent, RefreshHub

__all__ = [
    "AppEventHub",
    "envelope_applying",
    "envelope_banner",
    "envelope_bulk_progress",
    "envelope_refresh",
    "event_stream",
    "format_sse",
]


def envelope_refresh(scope: str) -> dict:
    return {"type": "refresh", "scope": scope}


def envelope_applying(verb: str, record_id: str, state: str) -> dict:
    """``state`` ∈ ``start`` | ``done`` | ``error`` (10 §1)."""
    return {"type": "applying", "verb": verb, "id": record_id, "state": state}


def envelope_bulk_progress(done: int, total: int, failed_id: str | None = None) -> dict:
    return {"type": "bulk_progress", "done": done, "total": total, "failed_id": failed_id}


def envelope_banner(text: str) -> dict:
    return {"type": "banner", "text": text}


def format_sse(envelope: dict) -> str:
    """One SSE ``data:`` frame, JSON-encoded — the wire format every
    envelope helper above feeds into."""
    return f"data: {json.dumps(envelope)}\n\n"


class AppEventHub:
    """Generic async pub/sub for non-refresh envelopes. Same
    subscribe/unsubscribe/publish shape as
    :class:`self_learn_ui.ledger.RefreshHub` (deliberately parallel, not
    shared — RefreshHub is U2's file-watcher-specific type; this one
    carries arbitrary envelope dicts)."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> "asyncio.Queue[dict]":
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[dict]") -> None:
        self._subscribers.discard(q)

    async def publish(self, envelope: dict) -> None:
        for q in list(self._subscribers):
            await q.put(envelope)

    def publish_nowait(self, envelope: dict) -> None:
        for q in list(self._subscribers):
            q.put_nowait(envelope)


async def event_stream(
    refresh_hub: RefreshHub, app_hub: AppEventHub
) -> AsyncIterator[str]:
    """Merge both hubs into one client-facing SSE text stream for the
    duration of one connection. Unsubscribes both on disconnect
    (``GeneratorExit`` via the ``finally``, e.g. a client navigating away
    or the server shutting down)."""
    refresh_q = refresh_hub.subscribe()
    app_q = app_hub.subscribe()
    pending: set[asyncio.Task] = {
        asyncio.ensure_future(refresh_q.get()),
        asyncio.ensure_future(app_q.get()),
    }
    try:
        while True:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                result = task.result()
                if isinstance(result, RefreshEvent):
                    yield format_sse(envelope_refresh(result.scope))
                    pending.add(asyncio.ensure_future(refresh_q.get()))
                else:
                    yield format_sse(result)
                    pending.add(asyncio.ensure_future(app_q.get()))
    finally:
        for task in pending:
            task.cancel()
        refresh_hub.unsubscribe(refresh_q)
        app_hub.unsubscribe(app_q)
