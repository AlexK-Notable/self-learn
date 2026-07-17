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

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path

from self_learn.hosts import HostsError, load_hosts, skill_dir_for
from self_learn.records import Record

from . import ledger
from .doctrine import read_doctrine
from .engine.base import BlockStart, FileChanged, PaneContext, PaneEngine, PaneEvent, Result, TextDelta, ToolUse
from .engine.sdk import DEFAULT_FALLBACK_MODEL, SdkPaneEngine
from .env import EnvConfig
from .ledger import RefreshHub
from .rendering import render_markdown
from .runner import VerbRunner
from .sse import AppEventHub

__all__ = [
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
    "build_pane_context",
    "build_pane_manager",
    "compose_first_message",
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


def build_pane_context(
    home: Path,
    record_id: str,
    *,
    read_doctrine_fn: Callable[[], str] = read_doctrine,
) -> PaneContext:
    """Assembles one Iterate session's :class:`PaneContext` from
    ``ledger.py`` reads (09 §4.2). ``read_doctrine_fn`` defaults to the
    real compiled-doctrine reader (tests inject one pointed at a
    tmp-rooted compiled path — see ``doctrine.py``'s own test suite for
    the established pattern: real tracked sources, redirected compiled
    output)."""
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
    error_message: str | None = None
    cap_hit: bool = False


@dataclass(frozen=True)
class PaneSnapshot:
    """A read-only rendering view — ``routes.py``'s ONLY window into pane
    state (never mutate through it). ``result_turns`` is always ``None``:
    the engine seam's :class:`~self_learn_ui.engine.base.Result` carries
    ``status``/``cost_usd``/``error`` only — no turn count field, despite
    09 §4.2's "cost footer ... plus turn count" and 10 §1's SSE row
    listing a ``turns`` field on ``pane_result``. That is a real gap
    between the already-merged engine seam (U5, off-limits to this
    track) and the spec; rather than reach into engine internals to add
    it, this field renders structurally absent — consistent with the
    SAME cost-honesty rule ("render what is reported, never invent a
    number") extended to turns. Flagged as a build finding, not patched
    around."""

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
    ) -> None:
        self._engine_factory = engine_factory
        self._context_builder = context_builder
        self._app_hub = app_hub
        self._refresh_hub = refresh_hub
        self._runner = runner
        self._live: _Live | None = None
        # 09 §4.3: "a scan hit badges the item 'scan-blocked' until a
        # re-validate exits 0" — this outlives the pane session itself
        # (surviving `q` close / a later plain Detail reload), so it is
        # NOT cleared when `_live` is discarded.
        self._validate_results: dict[str, tuple[int, str]] = {}

    @property
    def active_record_id(self) -> str | None:
        return self._live.record_id if self._live else None

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
            result_turns=None,  # see PaneSnapshot's docstring — seam gap
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
            live.cap_hit = bool(event.error) and _is_cap_hit(event.status)
            live.error_message = event.error
            live.state = STATE_ENDED if event.error else STATE_AWAITING_INPUT
            await self._app_hub.publish(
                {"type": "pane_result", "status": event.status, "cost": event.cost_usd, "turns": None}
            )
            if event.error is None:
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

    def context_builder(record_id: str) -> PaneContext:
        return build_pane_context(env.self_learn_home, record_id)

    return PaneManager(
        engine_factory=engine_factory,
        context_builder=context_builder,
        app_hub=app_hub,
        refresh_hub=refresh_hub,
        runner=runner,
    )
