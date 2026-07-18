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

**Concurrency design note.** ``start``/``send`` AWAIT their engine turn to
completion within the calling coroutine — the same convention
``routes.py``'s ``action_confirm`` already uses for ``runner.run()`` —
rather than spawning a background ``asyncio.Task``. This is safe for a
REAL concurrent Esc-interrupt: every ASGI request already runs as its own
task, so a concurrent ``POST .../pane/interrupt`` reaches
``SdkPaneEngine.interrupt()`` while this module's ``_drain`` loop is
mid-``async for``, and the interrupt escalation ladder (``engine/sdk.py``)
unwinds the in-flight turn from there — no extra task bookkeeping needed
here. The ``pane_*`` SSE pushes made DURING the drain already give a live
browser tab the token-by-token feel; the POST response is simply the
final state once the turn ends. Genuine concurrent-interrupt TIMING is a
T-E live-trial concern (10 §2) — this module's own test suite exercises
the interrupt/close/serialization call sequencing, not real-time overlap.

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
    engine: PaneEngine
    state: str = STATE_STARTING
    blocks: list[TranscriptBlock] = field(default_factory=list)
    current_kind: str | None = None
    current_text: str = ""
    result_status: str | None = None
    result_cost_usd: float | None = None
    result_turns: int | None = None
    error_message: str | None = None
    cap_hit: bool = False


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
        not-yet-ended session (a double Iterate is a no-op, not a second
        engine); ``"started"`` otherwise — including the retry path (an
        ENDED session for the same record is cleared and restarted)."""
        if self._live is not None:
            if self._live.record_id != record_id:
                if not force:
                    return "armed"
                await self._teardown_live()
            elif self._live.state != STATE_ENDED:
                return "resumed"
            else:
                self._live = None

        ctx = self._context_builder(record_id)
        engine = self._engine_factory()
        live = _Live(record_id=record_id, engine=engine, state=STATE_STARTING)
        self._live = live
        try:
            await self._drain(live, engine.start(ctx))
        except Exception as exc:  # noqa: BLE001 - a pane-visible error, not a 500
            live.error_message = str(exc)
            live.state = STATE_ENDED
        if live.state == STATE_ENDED:
            self._proposal_slot.clear_for_session(live.record_id)
        return "started"

    async def send(self, record_id: str, text: str) -> str:
        """A follow-up turn on the already-open session (09 §4.2: "the
        SDK client is multi-turn in-place"). ``"not-live"`` when no
        session is open for this record, OR the record's session already
        ENDED (error/cap-hit — 09 §5's "r to continue in a FRESH
        session": an ended session is not continuable by ``send``, only
        by ``start``'s retry path) — routes.py renders accordingly,
        never a 500 from calling ``send`` on a torn-down engine."""
        if (
            self._live is None
            or self._live.record_id != record_id
            or self._live.state == STATE_ENDED
        ):
            return "not-live"
        live = self._live
        live.state = STATE_STREAMING
        try:
            await self._drain(live, live.engine.send(text))
        except Exception as exc:  # noqa: BLE001
            live.error_message = str(exc)
            live.state = STATE_ENDED
        if live.state == STATE_ENDED:
            self._proposal_slot.clear_for_session(live.record_id)
        return "sent"

    async def interrupt(self, record_id: str) -> bool:
        """``Esc`` (09 §2.4/§4.2). A no-op (returns ``False``) when no
        session is live for this record; otherwise proxies straight to
        the engine's own interrupt ladder (``engine/sdk.py``) — never
        discards the transcript (09 §4.2: "interrupting never discards
        file changes already written")."""
        if self._live is None or self._live.record_id != record_id:
            return False
        self._live.state = STATE_INTERRUPTING
        await self._live.engine.interrupt()
        return True

    async def close(self, record_id: str) -> bool:
        """``q`` (09 §2.4): ends the session and DISCARDS the transcript
        (09 §4.2: "closing the split discards it — outcomes live in
        files"). The validate badge (if any) is NOT cleared here — it is
        ledger/scan state, not transcript state."""
        if self._live is None or self._live.record_id != record_id:
            return False
        await self._live.engine.close()
        self._live = None
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

    async def _teardown_live(self) -> None:
        if self._live is None:
            return
        live, self._live = self._live, None
        await live.engine.interrupt()
        await live.engine.close()
        # Y-13 clear-set: teardown ends the proposing session (interrupt
        # via verb dispatch, or a forced start on another item).
        self._proposal_slot.clear_for_session(live.record_id)

    # ------------------------------------------------------------- draining

    async def _drain(self, live: _Live, events: AsyncIterator[PaneEvent]) -> None:
        live.state = STATE_STREAMING
        async for event in events:
            await self._handle_event(live, event)
        if live.state != STATE_ENDED:
            live.state = STATE_AWAITING_INPUT

    async def _finalize_current(self, live: _Live) -> None:
        if live.current_kind is None:
            return
        html = render_markdown(live.current_text)
        live.blocks.append(TranscriptBlock(kind="text", html=html))
        await self._app_hub.publish({"type": "pane_block", "html": html})
        live.current_kind = None
        live.current_text = ""

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
            live.state = STATE_ENDED if event.error else STATE_AWAITING_INPUT
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
            if event.error is None and parse_bucket_session_key(live.record_id) is None:
                # Bucket sessions write nothing (09 §4.5) — no validate
                # obligation; record sessions keep the 08 §7.1 pin.
                await self._post_session_validate(live.record_id)

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
