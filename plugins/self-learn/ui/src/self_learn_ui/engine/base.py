"""The ``PaneEngine`` seam (10 §1's "Engine event protocol" row, verbatim):

    ``PaneEngine.start(ctx) -> AsyncIterator[PaneEvent]``
    ``PaneEvent = block_start(kind) | text_delta(str) | tool_use(name, target)
                | file_changed(path) | result(status, cost_usd|None, error|None)``
    ``send(str)``, ``interrupt()``, ``close()``.

The UI (tracks C/E) imports ONLY this module — SDK message parsing lives
entirely inside :mod:`self_learn_ui.engine.sdk` (09 §4.1: "the UI renders
events; it never reaches around the engine to the transport"). Both the
real ``sdk`` engine and this module's :class:`FakeEngine` satisfy the same
seam, so downstream UI code (and tests) never need to know which one is
wired in.

``start()`` and ``send()`` are async-generator methods: each call opens one
"turn" and yields that turn's events, ending after a :class:`Result` (09
§4.2: "the SDK client is multi-turn in-place" — a follow-up ``send()``
after a turn's ``Result`` starts the next turn's iterator on the same
underlying session).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BlockStart",
    "FakeEngine",
    "FileChanged",
    "PaneContext",
    "PaneEngine",
    "PaneEvent",
    "Result",
    "TextDelta",
    "ToolUse",
]


@dataclass(frozen=True)
class BlockStart:
    """A new content block began (``kind`` e.g. ``"text"``, ``"thinking"``,
    ``"tool_use"`` — the raw Anthropic content-block type). The UI uses this
    as a re-render boundary for the block that just finished (09 §4.1)."""

    kind: str


@dataclass(frozen=True)
class TextDelta:
    """An incremental chunk of the block currently streaming."""

    text: str


@dataclass(frozen=True)
class ToolUse:
    """The agent invoked a tool. ``target`` is the tool's file-path
    argument when it has one (Edit/Write/Read/...), else ``None``."""

    name: str
    target: str | None


@dataclass(frozen=True)
class FileChanged:
    """A file the pane agent wrote actually changed on disk — the signal
    the split view's live-record/diff pane (09 §2.4) re-renders on."""

    path: str


@dataclass(frozen=True)
class Result:
    """The turn ended. ``status`` is the engine's own status string
    (verbatim — 09's cost-honesty rule: never invent or reinterpret it).
    ``cost_usd`` is ``None`` when the engine reports none (subscription
    auth may report zero/absent — render what is reported). ``error`` is
    ``None`` on a clean result. ``turns`` is the engine-reported turn
    count (``ResultMessage.num_turns``) — ``None`` only when the engine
    genuinely reports none; the footer renders it verbatim (09 §4.2's
    "cost footer … plus turn count", 10 §1 SSE ``turns`` pin)."""

    status: str
    cost_usd: float | None
    error: str | None
    turns: int | None = None


#: The sum type both engines emit (10 §1). A plain ``Union`` — not a
#: further wrapper class — so callers pattern-match with ``isinstance``.
PaneEvent = BlockStart | TextDelta | ToolUse | FileChanged | Result


@dataclass(frozen=True)
class PaneContext:
    """Everything one Iterate session needs, assembled by the caller
    (track C's U6) before ``start()``. The engine never reads ledger
    files itself — 10 §1: "the UI imports only this module; SDK message
    parsing lives entirely inside the sdk engine" cuts both ways: the
    engine does no ledger reading either, it only spends what it's given.

    ``self_learn_home`` and ``bucket_root`` are resolved, absolute paths
    (the charter canonicalizes again internally — belt and braces, never
    trust a caller's resolution alone for a permission boundary).

    Y-13 additions (09 §4.5): ``session_kind`` selects the charter
    variant — ``"bucket"`` sessions hold zero write allowance (09 §4.3
    as amended; ``record_id`` then carries the manager's synthetic
    session key, not a record). ``propose_handler`` is the server-side
    ``propose_verb`` handler (:func:`self_learn_ui.proposals.
    make_propose_handler`) — ``None`` disables the proposal tool
    entirely (no MCP server is configured at all in that case).
    """

    record_id: str
    bucket_root: Path
    self_learn_home: Path
    system_prompt: str
    first_message: str
    session_kind: str = "record"
    propose_handler: "Callable[[dict[str, Any]], Awaitable[str]] | None" = None


class PaneEngine(ABC):
    """The seam. See module docstring for the exact pinned shape."""

    @abstractmethod
    def start(self, ctx: PaneContext) -> AsyncIterator[PaneEvent]:
        """Open a fresh session for *ctx* and stream its first turn's events."""
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator function

    @abstractmethod
    def send(self, text: str) -> AsyncIterator[PaneEvent]:
        """Send a follow-up user turn on the already-open session."""
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator function

    @abstractmethod
    async def interrupt(self) -> None:
        """Interrupt the in-flight turn, if any. A no-op when no turn is
        in flight (never started, or the last turn already ended) —
        10 §3's U5 test bullet pins this exact case."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Tear down the session. Idempotent."""
        raise NotImplementedError


class FakeEngine(PaneEngine):
    """A scripted-playback :class:`PaneEngine` for downstream UI tests
    (10 §3 U5: "plus a FakeEngine implementation for downstream UI
    tests"). Construct with one event list per turn; ``start()`` plays
    the first, each ``send()`` plays the next. Records everything sent
    and every ``interrupt()``/``close()`` call so a consuming test can
    assert on engine-facing behavior without a real (or fake-CLI) SDK
    session anywhere in the loop.
    """

    def __init__(self, turns: Iterable[Iterable[PaneEvent]] = ()) -> None:
        self._turns: list[list[PaneEvent]] = [list(turn) for turn in turns]
        self._next_turn = 0
        self.sent: list[str] = []
        self.interrupt_calls = 0
        self.close_calls = 0
        self.started = False
        self.closed = False
        self.contexts: list[PaneContext] = []

    def _next(self) -> list[PaneEvent]:
        if self._next_turn >= len(self._turns):
            return []
        turn = self._turns[self._next_turn]
        self._next_turn += 1
        return turn

    async def start(self, ctx: PaneContext) -> AsyncIterator[PaneEvent]:
        self.started = True
        self.contexts.append(ctx)
        for event in self._next():
            yield event

    async def send(self, text: str) -> AsyncIterator[PaneEvent]:
        self.sent.append(text)
        for event in self._next():
            yield event

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True
