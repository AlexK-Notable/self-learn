"""pane.py — the Iterate session manager (task U6; 09 §2.4/§4.2/§3 P1-4,
10 §3 U6 row). Owns the ONE live pane session server-wide:

- a fresh :class:`~self_learn_ui.engine.base.PaneEngine` per Iterate,
- the lifecycle state machine (idle -> starting -> streaming ->
  awaiting-input -> [interrupting] -> ended),
- the first-user-message composition (record body + proposal/diff if
  present + target canon excerpt, mirroring ``self_learn.worker``'s own
  excerpt rule — see :func:`target_canon_excerpt`),
- publishing the four ``pane_*`` SSE envelope types through the existing
  :class:`~self_learn_ui.sse.AppEventHub` (plain dicts — zero ``sse.py``
  changes, per that module's own docstring: "a future U6 publishing
  pane_delta/pane_block/pane_tool/pane_result needs zero changes here"),
- the post-session ``self-learn proposal validate <id>`` call through the
  :class:`~self_learn_ui.runner.VerbRunner` seam, exit-code discriminated
  (0/1/2), never parsing stderr for logic — only displaying it verbatim.

**Concurrency design note (09 §4.2 "Start is non-blocking" — §11 Y-15,
feedback round 2 item 1).** ``start()`` claims the live slot
synchronously (no ``await`` between guard and assignment — the
one-live-session invariant never depends on request-arrival luck) and
returns immediately; engine construction, context building, and the
first turn's drain all run in a background ``asyncio.Task``
(:meth:`PaneManager._run_first_turn`). The ``pane_*`` SSE envelopes are
the transport for first-turn content; the start POST's response is the
starting-state markup those handlers target. Completion — clean or
error — lands via the ``pane_result`` push (the client re-fetches the
panel GET; the drain wrapper's exception leg publishes ``pane_result``
too, so the swap fires on every completion path). Drain-task hygiene
(Y-15/F3): every teardown path cancels-or-awaits the task BEFORE a
successor can claim the slot, and a drain whose ``_Live`` is no longer
manager-current publishes nothing and clears nothing (the identity
guard). ``send()`` keeps the ORIGINAL awaited-in-request convention —
its POST response renders the post-turn state (Y-15/F6: send's
authoritative-swap semantics untouched) — but dispatches an engine turn
ONLY at awaiting-input (Y-15/F2: one in-flight turn per session, ever —
including the post-Result validate window, which stays INSIDE the turn:
the drain tail runs the validate and parks at awaiting-input only after
it completes).
Esc during the pre-connect window latches ``interrupt_requested``; the
drain honors the latch at its first post-connect boundary and a
never-connected turn parks ENDED without starting (Y-15/F4).

**One live session server-wide.** :class:`PaneManager` holds at most one
in-flight session; ``start()`` on a DIFFERENT record while one is live
returns ``"armed"`` (09 §2.4: "armed prompt to interrupt current first")
rather than silently switching. :meth:`PaneManager.interrupt_active_session`
is the ONE hook the verb-dispatch call sites (``routes.py``'s
``action_confirm``/``graduate_bulk``) await BEFORE running a resolution
verb on a record under active iteration (09 §3 P1-4 / P3-8's
resolved-elsewhere-implies-interrupt rule) — wired directly in
``routes.py`` (owned by this same track), so no ``runner.py`` change is
needed for that half of the wiring.

**App wiring.** :func:`build_pane_manager` is the ONE function the app
factory (``app.py``, off-limits to this track) needs to call — see the
docstring on that function for the exact one-line wiring to report at
merge.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from self_learn.hosts import HostsError, load_hosts, skill_dir_for
from self_learn.records import Record

from . import ledger
from .doctrine import read_doctrine
from .engine.base import BlockStart, FileChanged, PaneContext, PaneEngine, PaneEvent, Result, TextDelta, ToolUse
from .engine.sdk import DEFAULT_FALLBACK_MODEL, SdkPaneEngine
from .env import EnvConfig
from .ledger import RefreshHub
from .proposals import ProposalSlot, SessionScope, make_propose_handler
from .rendering import render_markdown
from .runner import VerbRunner
from .sse import AppEventHub

__all__ = [
    "BUCKET_CONTEXT_ROW_CAP",
    "PANE_STATES",
    "STATE_AWAITING_INPUT",
    "STATE_ENDED",
    "STATE_IDLE",
    "STATE_INTERRUPTING",
    "STATE_STARTING",
    "STATE_STREAMING",
    "PaneManager",
    "PaneSnapshot",
    "TranscriptBlock",
    "bucket_session_key",
    "build_bucket_pane_context",
    "build_pane_context",
    "build_pane_manager",
    "compose_bucket_message",
    "compose_first_message",
    "parse_bucket_session_key",
    "target_canon_excerpt",
]

# --------------------------------------------------------------- lifecycle

STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_STREAMING = "streaming"
STATE_AWAITING_INPUT = "awaiting-input"
STATE_INTERRUPTING = "interrupting"
STATE_ENDED = "ended"

PANE_STATES = (
    STATE_IDLE,
    STATE_STARTING,
    STATE_STREAMING,
    STATE_AWAITING_INPUT,
    STATE_INTERRUPTING,
    STATE_ENDED,
)

#: States in which an in-flight turn plausibly exists — the states in
#: which Esc-interrupt is meaningful (09 §2.4: "Esc with the pane focused
#: interrupts the stream"; an idle/ended pane has nothing to interrupt).
INTERRUPTIBLE_STATES = frozenset({STATE_STARTING, STATE_STREAMING, STATE_INTERRUPTING})

#: 09 §5: "Budget/turn-cap errors render as 'cap hit — r to continue in a
#: fresh session'". The Agent SDK's own docs pin ``error_max_budget_usd``
#: for the budget cap (claude_agent_sdk.types.ClaudeAgentOptions.max_budget_usd
#: docstring); ``error_max_turns`` is the documented sibling for the turn
#: cap. The ``startswith`` fallback below covers a future SDK variant
#: without silently swallowing an unrelated ``error_*`` status as a cap.
_CAP_HIT_STATUSES = frozenset({"error_max_turns", "error_max_budget_usd"})


def _is_cap_hit(status: str) -> bool:
    return status in _CAP_HIT_STATUSES or status.startswith("error_max_")


CAP_HIT_MESSAGE = "cap hit — r to continue in a fresh session"


# ------------------------------------------------- target canon excerpt
#
# Mirrors self_learn.worker._canon_excerpt EXACTLY (08 §7 / 09 §4.2's
# pin: "target canon excerpt (the same excerpt rule as the worker prompt
# pin)"). That function is private to the cli package and worker-batch
# shaped (it takes a WorkItem-like `entry`, not a bare Record); this
# module cannot import it, so the rule — resolution-by-scope, <200-line
# whole-file passthrough, else ±20 lines around the SELF-LEARN markers —
# is reproduced here against the same three public building blocks the
# worker itself uses (self_learn.hosts.load_hosts/skill_dir_for,
# ledger.project_path_for).

_EXCERPT_LINE_THRESHOLD = 200
_EXCERPT_CONTEXT_LINES = 20
_BEGIN_MARKER = "SELF-LEARN:BEGIN"
_END_MARKER = "SELF-LEARN:END"


def _resolve_canon_target(home: Path, record: Record, bucket_dir: Path) -> tuple[Path | None, str | None]:
    """Returns ``(target_path, None)`` or ``(None, message)`` — the same
    three-way branch (skill / project / user) as the worker's own
    resolution, verbatim."""
    scope = record.scope
    if scope.startswith("skill:"):
        try:
            return skill_dir_for(load_hosts(home), scope.partition(":")[2]) / "SKILL.md", None
        except HostsError:
            return None, "(skill target unresolvable — no registered skills root)"
    if scope == "project":
        host = ledger.project_path_for(bucket_dir)
        if host is None:
            return None, "(project target unresolvable — bucket has no meta.yaml)"
        return Path(host) / "CLAUDE.md", None
    # user scope — Y-2: excerpt-only, never a pane READ target; reading it
    # here is server-side prompt composition, not the model's own tool
    # access, and is exactly what the worker's own prompt builder does.
    return Path("~/.claude/CLAUDE.md").expanduser(), None


def target_canon_excerpt(home: Path, record: Record, bucket_dir: Path) -> str:
    """The candidate target's managed section ± 20 lines, or the whole
    file when under 200 lines (the worker's pinned prompt ingredient,
    mirrored — see module section docstring above)."""
    target, message = _resolve_canon_target(home, record, bucket_dir)
    if message is not None:
        return message
    assert target is not None
    if not target.is_file():
        return f"(target {target.name} does not exist yet)"
    lines = target.read_text(encoding="utf-8").splitlines()
    if len(lines) < _EXCERPT_LINE_THRESHOLD:
        return "\n".join(lines)
    begin = next((i for i, ln in enumerate(lines) if _BEGIN_MARKER in ln), None)
    end = next((i for i, ln in enumerate(lines) if _END_MARKER in ln), None)
    if begin is None or end is None:
        return "\n".join(lines[:60]) + "\n… (truncated)"
    lo, hi = max(0, begin - _EXCERPT_CONTEXT_LINES), min(len(lines), end + _EXCERPT_CONTEXT_LINES + 1)
    return "\n".join(lines[lo:hi])


def compose_first_message(
    *,
    home: Path,
    location: ledger.RecordLocation,
    record: Record,
    proposal: dict | None,
    diff_text: str | None,
    proposal_raw_text: str | None,
) -> str:
    """09 §4.2's per-item context, assembled into the SDK session's first
    user message: record body, proposal + diff if present, target canon
    excerpt. Never rides in the system prompt (that's the compiled
    doctrine, byte-stable across sessions — see :func:`build_pane_context`)."""
    parts = [
        f"=== PENDING RECORD {record.id} ===",
        f"status: {record.status}\nscope: {record.scope}\nsource: {record.source}",
        record.body,
    ]
    if proposal is not None:
        parts.append("=== EXISTING PROPOSAL ===")
        parts.append(
            proposal_raw_text
            if proposal_raw_text is not None
            # Defensive fallback only — production callers
            # (build_pane_context) always supply proposal_raw_text
            # alongside proposal together (both come from the same
            # sibling-file read). Not yaml.safe_dump: a ruamel-parsed
            # proposal dict (self_learn.ledger_ops.read_proposal) is
            # CommentedMap/CommentedSeq-typed, which pyyaml's SafeDumper
            # cannot represent (exact-type representer lookup, not
            # isinstance) — str() is always safe.
            else str(proposal)
        )
        if diff_text:
            parts.append("=== PROPOSAL DIFF ===")
            parts.append(diff_text)
    else:
        parts.append("(no proposal yet — analyze this record from scratch)")
    parts.append("=== CANDIDATE TARGET CANON EXCERPT ===")
    parts.append(target_canon_excerpt(home, record, location.bucket_dir))
    return "\n\n".join(parts)


def _record_propose_handler(
    home: Path,
    record_id: str,
    slot: ProposalSlot | None,
    publish: "Callable[[dict], Awaitable[None]] | None",
) -> "Callable[[dict[str, Any]], Awaitable[str]] | None":
    if slot is None or publish is None:
        return None
    scope = SessionScope(kind="record", session_key=record_id, record_id=record_id)
    return make_propose_handler(home=home, scope=scope, slot=slot, publish=publish)


def build_pane_context(
    home: Path,
    record_id: str,
    *,
    read_doctrine_fn: Callable[[], str] = read_doctrine,
    slot: ProposalSlot | None = None,
    publish: "Callable[[dict], Awaitable[None]] | None" = None,
) -> PaneContext:
    """Assembles one Iterate session's :class:`PaneContext` from
    ``ledger.py`` reads (09 §4.2). ``read_doctrine_fn`` defaults to the
    real compiled-doctrine reader (tests inject one pointed at a
    tmp-rooted compiled path — see ``doctrine.py``'s own test suite for
    the established pattern: real tracked sources, redirected compiled
    output). ``slot``/``publish`` (Y-13) wire the session's
    ``propose_verb`` handler; both-or-neither — without them the session
    simply has no proposal tool (the pre-Y-13 shape, kept for tests)."""
    location = ledger.locate_record(home, record_id)
    if location is None:
        raise LookupError(f"pane: record {record_id} not found under {home}")
    record = ledger.read_record(location.path)
    if record is None:
        raise LookupError(f"pane: record {record_id} unparseable at {location.path}")
    proposal, _err = ledger.read_proposal_raw(location.bucket_dir, record_id)
    diff_text = ledger.read_diff(location.bucket_dir, record_id)
    proposal_raw_text = ledger.read_proposal_text(location.bucket_dir, record_id)
    first_message = compose_first_message(
        home=home,
        location=location,
        record=record,
        proposal=proposal,
        diff_text=diff_text,
        proposal_raw_text=proposal_raw_text,
    )
    return PaneContext(
        record_id=record_id,
        bucket_root=location.bucket_dir,
        self_learn_home=home,
        system_prompt=read_doctrine_fn(),
        first_message=first_message,
        session_kind="record",
        propose_handler=_record_propose_handler(home, record_id, slot, publish),
    )


# ------------------------------------------------- bucket pane (Y-13)

#: 09 §11 Y-13 decision 5: the bucket first message caps its record list
#: at 50 rows with an HONEST truncation line — never a silent cut.
BUCKET_CONTEXT_ROW_CAP = 50

_BUCKET_KEY_PREFIX = "bucket:"


def bucket_session_key(scope: str, name: str) -> str:
    """The PaneManager session key for a bucket pane — a synthetic key in
    the same keyspace as record ids (one manager, one live session across
    BOTH variants — 09 §4.2 as amended)."""
    return f"{_BUCKET_KEY_PREFIX}{scope}/{name}"


def parse_bucket_session_key(key: str) -> tuple[str, str] | None:
    """``("<scope>", "<name>")`` when *key* is a bucket session key, else
    ``None`` (it's a plain record id)."""
    if not key.startswith(_BUCKET_KEY_PREFIX):
        return None
    scope, sep, name = key[len(_BUCKET_KEY_PREFIX):].partition("/")
    if not sep or not scope or not name:
        return None
    return scope, name


def compose_bucket_message(
    scope: str,
    name: str,
    items: list[dict],
    clusters: list[dict],
    *,
    host_registered: bool = True,
    row_cap: int = BUCKET_CONTEXT_ROW_CAP,
) -> str:
    """The bucket session's first user message (09 §11 Y-13 decision 5):
    bucket summary + grouped pending rows — leading human line first
    (Y-9: the ``list --json`` title derivation), id as trailing metadata,
    destination, freshness, deferred/cluster tags — capped with an honest
    truncation line. Ambiguity about which record an instruction means is
    the agent's clarifying question, never a guess (doctrine §8; the
    surface-model prose carries that instruction)."""
    lines = [
        f"=== BUCKET {name} (scope: {scope}) ===",
        f"pending records: {len(items)}"
        + ("" if host_registered else " · host NOT registered (no canon writes possible yet)"),
    ]
    for item in items[:row_cap]:
        title = item.get("title") or "(untitled record)"
        dest = item.get("destination") or "no analysis yet"
        fresh = "fresh" if item.get("proposal_fresh") else (
            "stale" if item.get("has_proposal") else "unanalyzed"
        )
        tags = [f"id={item.get('id')}", f"destination={dest}", fresh]
        if item.get("deferred_until"):
            tags.append(f"deferred until {item['deferred_until']}")
        if item.get("source") == "session":
            tags.append("mined")
        lines.append(f"- {title}  [{', '.join(tags)}]")
    if len(items) > row_cap:
        lines.append(
            f"(list truncated: showing {row_cap} of {len(items)} pending "
            "records — ask the human, or ask for a specific record id)"
        )
    for cluster in clusters:
        lines.append(
            f"- cluster {cluster.get('cluster_id')}: "
            f"{len(cluster.get('members', []) or [])} similar records, "
            f"suggested survivor {cluster.get('suggested_survivor')}"
        )
    return "\n".join(lines)


def build_bucket_pane_context(
    home: Path,
    scope: str,
    name: str,
    *,
    read_doctrine_fn: Callable[[], str] = read_doctrine,
    slot: ProposalSlot | None = None,
    publish: "Callable[[dict], Awaitable[None]] | None" = None,
) -> PaneContext:
    """The bucket pane's :class:`PaneContext` (09 §2.2/§4.5): bucket
    first-message context, ``session_kind="bucket"`` (zero write
    allowance — the charter variant), and a bucket-scoped
    ``propose_verb`` handler."""
    bucket = next(
        (b for b in ledger.discover_buckets(home) if b.scope == scope and b.name == name),
        None,
    )
    if bucket is None:
        raise LookupError(f"pane: bucket {scope}/{name} not found under {home}")
    list_read = ledger.list_items(home, include_deferred=True)
    items = [
        item for item in (list_read.data or []) if item.get("bucket") == name
    ] if list_read.ok else []
    clusters = ledger.read_clusters(bucket.path)
    host_registered = bool(items[0].get("host_registered", True)) if items else True

    key = bucket_session_key(scope, name)
    handler = None
    if slot is not None and publish is not None:
        session_scope = SessionScope(
            kind="bucket",
            session_key=key,
            bucket_dir=bucket.path,
            bucket_scope=scope,
            bucket_name=name,
        )
        handler = make_propose_handler(
            home=home, scope=session_scope, slot=slot, publish=publish
        )

    return PaneContext(
        record_id=key,
        bucket_root=bucket.path,
        self_learn_home=home,
        system_prompt=read_doctrine_fn(),
        first_message=compose_bucket_message(
            scope, name, items, clusters, host_registered=host_registered
        ),
        session_kind="bucket",
        propose_handler=handler,
    )


# ---------------------------------------------------------------- transcript


@dataclass(frozen=True)
class TranscriptBlock:
    """One finalized transcript entry — a typeset text block (markdown ->
    HTML, ``html=False`` per rendering.py) or a standalone tool-use line."""

    kind: str  # "text" | "tool"
    html: str | None = None
    tool_name: str | None = None
    tool_target: str | None = None


@dataclass
class _Live:
    record_id: str
    #: None only during the STARTING window — the background first-turn
    #: task constructs the engine AFTER the synchronous slot claim
    #: (09 §4.2 Y-15/F5: nothing slow runs between guard and assignment).
    engine: PaneEngine | None = None
    state: str = STATE_STARTING
    blocks: list[TranscriptBlock] = field(default_factory=list)
    current_kind: str | None = None
    current_text: str = ""
    result_status: str | None = None
    result_cost_usd: float | None = None
    result_turns: int | None = None
    error_message: str | None = None
    cap_hit: bool = False
    #: The background first-turn drain (Y-15). None once disposed, and
    #: always None for a session whose first turn ran to completion —
    #: dispose happens through _dispose_drain on every teardown path.
    drain_task: asyncio.Task | None = None
    #: Y-15/F4 latch: Esc arrived while the turn was starting/streaming.
    #: The drain honors it at its first post-connect boundary; a turn
    #: that never connected parks ENDED without starting.
    interrupt_requested: bool = False
    #: The drain already replayed the latched interrupt to the engine —
    #: one replay per turn (engine interrupt is idempotent, delta R4).
    interrupt_replayed: bool = False
    #: The CURRENT turn ended with a clean Result (review MAJOR-1): the
    #: drain tail runs the post-session validate and only THEN parks at
    #: awaiting-input — the validate window stays inside the turn, so
    #: send() can never dispatch into it. Reset at every drain entry.
    turn_had_clean_result: bool = False


@dataclass(frozen=True)
class PaneSnapshot:
    """A read-only rendering view — ``routes.py``'s ONLY window into pane
    state (never mutate through it). ``result_turns`` is the engine-
    reported turn count from :class:`~self_learn_ui.engine.base.Result`
    (``num_turns``), ``None`` only when the engine reports none — the
    footer renders it verbatim (09 §4.2's "cost footer … plus turn
    count", 10 §1's SSE ``turns`` pin). The interim-review seam gap
    (Result once lacked a turn field) was closed 2026-07-17."""

    record_id: str
    state: str
    blocks: tuple[TranscriptBlock, ...]
    current_kind: str | None
    current_html: str | None
    result_status: str | None
    result_cost_usd: float | None
    result_turns: int | None
    error_message: str | None
    cap_hit: bool
    validate_exit_code: int | None
    validate_stderr: str | None


def _idle_snapshot(record_id: str, validate: tuple[int, str] | None) -> PaneSnapshot:
    return PaneSnapshot(
        record_id=record_id,
        state=STATE_IDLE,
        blocks=(),
        current_kind=None,
        current_html=None,
        result_status=None,
        result_cost_usd=None,
        result_turns=None,
        error_message=None,
        cap_hit=False,
        validate_exit_code=validate[0] if validate else None,
        validate_stderr=validate[1] if validate else None,
    )


class PaneManager:
    """The server-wide pane session manager (one live session at a
    time). See module docstring for the concurrency design and the
    verb-dispatch interrupt-first contract."""

    def __init__(
        self,
        *,
        engine_factory: Callable[[], PaneEngine],
        context_builder: Callable[[str], PaneContext],
        app_hub: AppEventHub,
        refresh_hub: RefreshHub,
        runner: VerbRunner,
        proposal_slot: ProposalSlot | None = None,
    ) -> None:
        self._engine_factory = engine_factory
        self._context_builder = context_builder
        self._app_hub = app_hub
        self._refresh_hub = refresh_hub
        self._runner = runner
        # Y-13 (09 §4.5): the server-held single proposal slot. Owned
        # here because its clear-set is session-coupled ("the proposing
        # session ending for any reason" clears it). Optional so pre-Y-13
        # test constructions keep working; routes fall back to a slot of
        # their own absence-tolerantly via `proposal_slot` property.
        self._proposal_slot = proposal_slot if proposal_slot is not None else ProposalSlot()
        self._live: _Live | None = None
        # 09 §4.3: "a scan hit badges the item 'scan-blocked' until a
        # re-validate exits 0" — this outlives the pane session itself
        # (surviving `q` close / a later plain Detail reload), so it is
        # NOT cleared when `_live` is discarded.
        self._validate_results: dict[str, tuple[int, str]] = {}

    @property
    def active_record_id(self) -> str | None:
        return self._live.record_id if self._live else None

    @property
    def proposal_slot(self) -> ProposalSlot:
        return self._proposal_slot

    def snapshot(self, record_id: str) -> PaneSnapshot:
        """Always returns a snapshot (never ``None``) — ``state`` is
        :data:`STATE_IDLE` when there is no live session for this record
        (whether or not one ever ran); routes.py decides whether to
        render the split from ``state != STATE_IDLE``."""
        validate = self._validate_results.get(record_id)
        if self._live is None or self._live.record_id != record_id:
            return _idle_snapshot(record_id, validate)
        live = self._live
        current_html: str | None = None
        if live.current_kind is not None:
            # 09 §5's per-block fallback: an in-flight block with no
            # text yet renders "" here — the template shows an activity
            # indicator instead (never a raised error over a slow/coarse
            # engine).
            current_html = render_markdown(live.current_text) if live.current_text else ""
        return PaneSnapshot(
            record_id=record_id,
            state=live.state,
            blocks=tuple(live.blocks),
            current_kind=live.current_kind,
            current_html=current_html,
            result_status=live.result_status,
            result_cost_usd=live.result_cost_usd,
            result_turns=live.result_turns,
            error_message=live.error_message,
            cap_hit=live.cap_hit,
            validate_exit_code=validate[0] if validate else None,
            validate_stderr=validate[1] if validate else None,
        )

    def validate_state(self, record_id: str) -> tuple[int, str] | None:
        return self._validate_results.get(record_id)

    # ----------------------------------------------------------- lifecycle

    async def start(self, record_id: str, *, force: bool = False) -> str:
        """Fresh session per Iterate (09 §4.2). Returns ``"armed"`` when a
        DIFFERENT record is live and ``force`` is false (09 §2.4's armed
        prompt); ``"resumed"`` when the SAME record already has a live,
        not-yet-ended session (a double Iterate — including one landing
        DURING the background first turn — is a no-op, not a second
        engine; 09 §4.2 Y-15's turn-serialization pin); ``"started"``
        otherwise — including the retry path (an ENDED session for the
        same record is cleared and restarted).

        Y-15: returns as soon as the session exists. The slot claim is
        synchronous — no ``await`` between the guard and the assignment
        (F5) — and the first turn drains in a background task; callers
        render the STARTING snapshot and the SSE stream fills it. Tests
        join deterministically via :meth:`wait_for_turn`."""
        while self._live is not None:
            if self._live.record_id != record_id:
                if not force:
                    return "armed"
                await self._teardown_live()
                continue  # re-run the guard after the await (F5)
            if self._live.state != STATE_ENDED:
                return "resumed"
            old, self._live = self._live, None
            # r-retry same-key window (Y-15/F3 + review MINOR-1): the
            # predecessor's drain is disposed AND its engine closed
            # BEFORE the successor claims — a late clear can never wipe
            # the new session's slot, and no SDK/CLI child leaks per
            # retry (an errored/cap-hit session's engine was never
            # closed by its own turn). The loop re-runs the guard after
            # these awaits (F5); a same-key ENDED claimant landing in
            # this window is cleared too, never armed against its own
            # record (review NIT-1).
            await self._dispose_drain(old)
            if old.engine is not None:
                await old.engine.close()

        live = _Live(record_id=record_id)
        self._live = live  # synchronous with the guard above (F5)
        live.drain_task = asyncio.create_task(self._run_first_turn(live))
        return "started"

    async def wait_for_turn(self) -> None:
        """Deterministic join on the in-flight background first turn —
        the test seam Y-15's FakeEngine suites use (and nothing else:
        production callers never await this; the start POST returns
        pre-drain by design)."""
        live = self._live
        task = live.drain_task if live is not None else None
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def send(self, record_id: str, text: str) -> str:
        """A follow-up turn on the already-open session (09 §4.2: "the
        SDK client is multi-turn in-place"). ``"not-live"`` when no
        session is open for this record, OR the record's session already
        ENDED (error/cap-hit — 09 §5's "r to continue in a FRESH
        session": an ended session is not continuable by ``send``, only
        by ``start``'s retry path); ``"busy"`` while a turn is already
        in flight (Y-15/F2's NEW obligation: an engine turn dispatches
        ONLY at awaiting-input — mid-turn the route simply re-renders
        the current split, never a concurrent second drain). Routes
        render the snapshot for every outcome — never a 500 from
        calling ``send`` on a torn-down engine."""
        if (
            self._live is None
            or self._live.record_id != record_id
            or self._live.state == STATE_ENDED
        ):
            return "not-live"
        live = self._live
        if live.state != STATE_AWAITING_INPUT or live.engine is None:
            return "busy"
        live.state = STATE_STREAMING
        try:
            await self._drain(live, live.engine.send(text))
        except Exception as exc:  # noqa: BLE001
            live.error_message = str(exc)
            live.state = STATE_ENDED
        if live.state == STATE_ENDED and self._live is live:
            self._proposal_slot.clear_for_session(live.record_id)
        return "sent"

    async def interrupt(self, record_id: str) -> bool:
        """``Esc`` (09 §2.4/§4.2). A no-op (returns ``False``) when no
        session is live for this record; otherwise proxies straight to
        the engine's own interrupt ladder (``engine/sdk.py``) — never
        discards the transcript (09 §4.2: "interrupting never discards
        file changes already written").

        Y-15/F4: an in-flight turn additionally latches
        ``interrupt_requested`` — the pre-connect window's engine call
        (or absence of an engine entirely) may be a silent no-op, so the
        background drain re-delivers the interrupt at its first
        post-connect boundary, and a turn that never connects parks
        ENDED without starting (:meth:`_run_first_turn`)."""
        if self._live is None or self._live.record_id != record_id:
            return False
        live = self._live
        if live.state in INTERRUPTIBLE_STATES:
            live.interrupt_requested = True
            live.state = STATE_INTERRUPTING
        if live.engine is not None:
            await live.engine.interrupt()
        return True

    async def close(self, record_id: str) -> bool:
        """``q`` (09 §2.4): ends the session and DISCARDS the transcript
        (09 §4.2: "closing the split discards it — outcomes live in
        files"). The validate badge (if any) is NOT cleared here — it is
        ledger/scan state, not transcript state."""
        if self._live is None or self._live.record_id != record_id:
            return False
        live, self._live = self._live, None
        await self._dispose_drain(live)
        if live.engine is not None:
            await live.engine.close()
        # Y-13 clear-set: the proposing session ended (`q`).
        self._proposal_slot.clear_for_session(record_id)
        return True

    async def interrupt_active_session(self, record_id: str) -> bool:
        """09 §3 P1-4 / P3-8: the ONE hook a resolution-verb dispatch site
        awaits BEFORE running its verb on ``record_id`` — "resolving an
        under-iteration record interrupts FIRST at verb dispatch." A
        no-op (``False``) when no session is live for this record. Tears
        the session down entirely (not just interrupts) — the verb it
        unblocks is about to ``git mv``/``git rm`` the exact files this
        session held write permission on (P3-7's resurrection vector), so
        leaving it "awaiting-input" against files about to disappear
        would be worse than closing it."""
        if self._live is None or self._live.record_id != record_id:
            return False
        await self._teardown_live()
        return True

    def has_interruptible_session(self) -> bool:
        """Y-14 idle-predicate leg (09 §3): an agent mid-turn
        (starting/streaming/interrupting) is work-in-flight and blocks
        idle exit; a parked (awaiting-input/ended) session does NOT —
        it is torn down by :meth:`teardown_parked` instead."""
        return self._live is not None and self._live.state in INTERRUPTIBLE_STATES

    async def teardown_parked(self) -> bool:
        """Tear down a parked (non-INTERRUPTIBLE) live session through
        the standard teardown — clearing the proposal slot via the
        Y-13 clear-set — and report whether one existed. The idle
        monitor calls this and then DEFERS its exit decision (delta
        R1: teardown awaits engine calls, so teardown and signal never
        share a step). Engine ``interrupt()``/``close()`` are
        idempotent against already-ended sessions (delta R4 — pinned
        by test)."""
        if self._live is None or self._live.state in INTERRUPTIBLE_STATES:
            return False
        await self._teardown_live()
        return True

    async def shutdown(self) -> None:
        """App-shutdown teardown (``app.py``'s lifespan ``finally``;
        review MINOR-2): pre-Y-15 an in-flight turn lived inside a
        request uvicorn's graceful shutdown waited for — the background
        drain does not, so the lifespan tears the live session down
        explicitly (drain cancelled-or-awaited, engine closed, slot
        cleared) instead of leaking a free-floating task."""
        await self._teardown_live()

    async def _teardown_live(self) -> None:
        if self._live is None:
            return
        live, self._live = self._live, None
        # Y-15/F3: the drain task dies BEFORE the engine teardown and
        # before any successor can claim the slot.
        await self._dispose_drain(live)
        if live.engine is not None:
            await live.engine.interrupt()
            await live.engine.close()
        # Y-13 clear-set: teardown ends the proposing session (interrupt
        # via verb dispatch, or a forced start on another item).
        self._proposal_slot.clear_for_session(live.record_id)

    async def _dispose_drain(self, live: _Live) -> None:
        """Cancel-or-await *live*'s background drain task (Y-15/F3's
        first half). Runs on every teardown path; by the time it
        returns, the task cannot run again — the identity guard in
        :meth:`_drain`/:meth:`_run_first_turn` is the belt for a callee
        that swallows the cancellation, not the primary mechanism."""
        task, live.drain_task = live.drain_task, None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------- draining

    async def _run_first_turn(self, live: _Live) -> None:
        """The background first turn (09 §4.2 Y-15): engine construction,
        context build, and the drain — everything slower than the slot
        claim. The exception leg publishes ``pane_result`` so the
        client's completion swap fires on EVERY completion path (F1 —
        at-least-once; the swap is idempotent, delta R2)."""
        try:
            if live.interrupt_requested:
                # Esc landed before the turn ever connected (F4's
                # pre-connect window): park ENDED without starting —
                # nothing streamed, so nothing is discarded.
                live.error_message = "interrupted before the conversation started — r starts a fresh one"
                live.state = STATE_ENDED
                if self._live is live:
                    await self._app_hub.publish(
                        {"type": "pane_result", "status": "interrupted", "cost": None, "turns": None}
                    )
            else:
                # Context before engine — the factory/builder pair is a
                # closure convention shared with the test harnesses
                # (build_pane_manager's production closures are
                # order-independent).
                ctx = self._context_builder(live.record_id)
                live.engine = self._engine_factory()
                await self._drain(live, live.engine.start(ctx))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a pane-visible error, not a crash
            live.error_message = str(exc)
            live.state = STATE_ENDED
            if self._live is live:
                await self._app_hub.publish(
                    {"type": "pane_result", "status": "error", "cost": None, "turns": None}
                )
        if live.state == STATE_ENDED and self._live is live:
            # Y-13 clear-set, anchored at drain completion (Y-15: the
            # moment that used to coincide with the POST return).
            self._proposal_slot.clear_for_session(live.record_id)

    async def _drain(self, live: _Live, events: AsyncIterator[PaneEvent]) -> None:
        if live.state != STATE_INTERRUPTING:
            live.state = STATE_STREAMING
        live.turn_had_clean_result = False
        # Per-turn latch reset (delta residual on the MAJOR-1 fold): an
        # Esc latched during a PREVIOUS turn's validate window — which
        # the tail parks without clearing — must never replay into THIS
        # turn's first event, interrupting the turn the user just asked
        # for. Safe: there is no suspension point between the wrapper's
        # pre-connect latch check (or send()'s awaiting-input guard) and
        # this entry, so no legitimate Esc is erased; any Esc after
        # entry latches afresh.
        live.interrupt_requested = False
        live.interrupt_replayed = False
        async for event in events:
            if self._live is not live:
                # Identity guard (Y-15/F3): an orphaned drain publishes
                # nothing and clears nothing.
                return
            if live.interrupt_requested and not live.interrupt_replayed:
                # F4: first post-connect boundary — re-deliver the Esc
                # that may have no-op'd pre-connect (idempotent, R4).
                live.interrupt_replayed = True
                assert live.engine is not None
                await live.engine.interrupt()
            await self._handle_event(live, event)
        if live.state == STATE_ENDED:
            return
        # Review MAJOR-1: the post-session validate runs INSIDE the turn
        # — the state parks at awaiting-input only after it completes,
        # so send() ("busy" outside awaiting-input) can never dispatch a
        # second engine turn into the validate window (F2's "ONE
        # in-flight turn per session, ever", now including this tail).
        # The pane_result push already went out at the Result event (R2
        # at-least-once); the validate badge lands one refresh later via
        # _post_session_validate's own force_refresh — the accepted
        # two-step render. Bucket sessions write nothing (09 §4.5), so
        # they owe no validate; record sessions keep the 08 §7.1 pin.
        if (
            live.turn_had_clean_result
            and self._live is live
            and parse_bucket_session_key(live.record_id) is None
        ):
            await self._post_session_validate(live.record_id)
        live.state = STATE_AWAITING_INPUT

    async def _finalize_current(self, live: _Live) -> None:
        if live.current_kind is None:
            return
        html = render_markdown(live.current_text)
        # Mutate the transcript state to its CONSISTENT post-finalize shape
        # (block appended, current-block cleared) BEFORE the publish await —
        # the `await` below is a suspension point, and a snapshot() taken in
        # that window (a panel GET: the pane_result completion swap re-fetch,
        # a mid-drain reload) would otherwise see the block BOTH finalized in
        # `blocks` AND still in-flight as `current_html`, typesetting it
        # twice (FW-18 fix 2 — the SSE pane_block duplication bug).
        live.blocks.append(TranscriptBlock(kind="text", html=html))
        live.current_kind = None
        live.current_text = ""
        await self._app_hub.publish({"type": "pane_block", "html": html})

    async def _handle_event(self, live: _Live, event: PaneEvent) -> None:
        if isinstance(event, BlockStart):
            await self._finalize_current(live)
            live.current_kind = event.kind
            live.current_text = ""
        elif isinstance(event, TextDelta):
            live.current_text += event.text
            await self._app_hub.publish({"type": "pane_delta", "text": event.text})
        elif isinstance(event, ToolUse):
            # Chronological ordering: a tool_use content block gets its
            # own stream-level boundary in the real SDK transport (it
            # always follows a content_block_start of its own), so a
            # pending text block finalizes here too — never left to
            # render AFTER a tool line that actually happened later.
            await self._finalize_current(live)
            live.blocks.append(TranscriptBlock(kind="tool", tool_name=event.name, tool_target=event.target))
            await self._app_hub.publish({"type": "pane_tool", "name": event.name, "target": event.target})
        elif isinstance(event, FileChanged):
            # Task brief / 09 §2.4/§4.3: mid-session file_changed ->
            # re-render push ONLY, never validation.
            self._refresh_hub.force_refresh(f"record:{live.record_id}")
        elif isinstance(event, Result):
            await self._finalize_current(live)
            live.result_status = event.status
            live.result_cost_usd = event.cost_usd
            live.result_turns = event.turns
            live.cap_hit = bool(event.error) and _is_cap_hit(event.status)
            live.error_message = event.error
            if event.error:
                live.state = STATE_ENDED
            else:
                # Review MAJOR-1: a clean Result does NOT park the
                # session here — the state stays streaming through the
                # drain tail's validate; awaiting-input is the tail's
                # last act.
                live.turn_had_clean_result = True
            if self._live is not live:
                # Identity guard (Y-15/F3): _finalize_current awaited
                # above, so a teardown may have interleaved — an
                # orphaned drain clears nothing and publishes nothing.
                return
            if live.state == STATE_ENDED:
                # Y-13 clear-set: error/cap results END the proposing
                # session (a clean result leaves it awaiting-input — the
                # human reviews the waiting bar while the session lives).
                self._proposal_slot.clear_for_session(live.record_id)
            await self._app_hub.publish(
                {
                    "type": "pane_result",
                    "status": event.status,
                    "cost": event.cost_usd,
                    "turns": event.turns,
                }
            )

    async def _post_session_validate(self, record_id: str) -> None:
        """09 §4.3 / task brief: on session end, ``self-learn proposal
        validate <id>`` THROUGH THE RUNNER SEAM, exit-code discriminated —
        never stderr parsing (the exit code is the only signal branched
        on; stderr is displayed verbatim, never inspected)."""
        result = await self._runner.run(["proposal", "validate", record_id])
        self._validate_results[record_id] = (result.exit_code, result.stderr)
        # 0 -> stamped fresh: the record_sha the record now carries makes
        # `list --json .proposal_fresh` true on the NEXT read — a plain
        # refresh push is what turns that into a visible badge flip,
        # exactly the existing refresh_hub mechanism every other mutation
        # already uses (no new field needed for the 0 case).
        self._refresh_hub.force_refresh(f"record:{record_id}")


# ------------------------------------------------------------- app wiring


def build_pane_manager(
    *,
    env: EnvConfig,
    runner: VerbRunner,
    app_hub: AppEventHub,
    refresh_hub: RefreshHub,
) -> PaneManager:
    """The ONE function the app factory (``app.py``) calls to wire the
    pane session manager onto ``app.state`` — this track does not touch
    ``app.py`` itself (owned by a concurrent track); the orchestrator
    applies this ONE line inside ``create_app()``, after ``app_hub`` and
    ``refresh_hub`` are constructed and ``runner``/``env`` are in scope::

        app.state.pane_manager = pane.build_pane_manager(
            env=env, runner=runner, app_hub=app_hub, refresh_hub=refresh_hub
        )

    (plus ``from . import pane`` at the top of ``app.py``). Every pane
    route in ``routes.py`` reads ``request.app.state.pane_manager`` via
    ``getattr(..., None)`` and degrades to a 503 when absent, so the app
    keeps working (minus Iterate) even before this line lands."""

    def engine_factory() -> PaneEngine:
        return SdkPaneEngine(
            model=env.pane_model,
            fallback_model=DEFAULT_FALLBACK_MODEL,
            max_turns=env.pane_max_turns,
            max_budget_usd=env.pane_budget_usd,
        )

    slot = ProposalSlot()

    def context_builder(session_key: str) -> PaneContext:
        parsed = parse_bucket_session_key(session_key)
        if parsed is not None:
            scope, name = parsed
            return build_bucket_pane_context(
                env.self_learn_home, scope, name, slot=slot, publish=app_hub.publish
            )
        return build_pane_context(
            env.self_learn_home, session_key, slot=slot, publish=app_hub.publish
        )

    return PaneManager(
        engine_factory=engine_factory,
        context_builder=context_builder,
        app_hub=app_hub,
        refresh_hub=refresh_hub,
        runner=runner,
        proposal_slot=slot,
    )
