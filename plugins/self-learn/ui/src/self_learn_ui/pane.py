"""pane.py — the Iterate session manager (task U6; 09 §2.4/§4.2/§3 P1-4,
10 §3 U6 row). Owns the ONE live pane session server-wide:

- a fresh :class:`~self_learn_ui.engine.base.PaneEngine` per Iterate,
- the lifecycle state machine (idle -> starting -> streaming ->
  awaiting-input -> [interrupting] -> ended),
- the first-user-message composition (record body + proposal/diff if
  present + target canon excerpt, delegating to ``self_learn.worker``'s
  own excerpt rule — see :func:`target_canon_excerpt`),
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
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from self_learn.records import Record
from self_learn.worker import cache_dir, canon_excerpt

from . import ledger
from .doctrine import read_doctrine
from .engine.base import BlockStart, FileChanged, PaneContext, PaneEngine, PaneEvent, Result, TextDelta, ToolUse
from .engine.sdk import DEFAULT_FALLBACK_MODEL, SdkPaneEngine
from .env import EnvConfig
from .ledger import RefreshHub
from .models import destination_label, parse_variant_qualifier
from .proposals import PROPOSAL_TOOL_QUALIFIED_NAME, ProposalSlot, SessionScope, VerbProposal, make_propose_handler
from .rendering import render_markdown
from .runner import VerbRunner
from .sse import AppEventHub
from .store import PaneTranscriptStore, StoredSnapshot

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


# ------------------------------------------------------- Y-28 / U22 resume
#
# Durable pane/Iterate transcripts with resume (09 §11 Y-28, 10 §3 U22).
# Tier 1 (render-resume, always on) mirrors finalized TranscriptBlocks to
# a cache-local JSONL via store.PaneTranscriptStore at the three pinned
# append points below. Tier 2 (context-resume) rides the resolved SDK's
# session_store/resume capability (engine/sdk.py) when a prior session's
# sdk_session_id was captured; Tier 1.5 (first_message reinjection) is
# the fallback when it was not (e.g. the session never reached a Result,
# so the SDK never reported one).

#: Y-28 §4e's three-clause resumable predicate excludes these — a
#: session that ended in error/cap-hit is Tier-2-ineligible even though
#: the record itself may still be pending (the live send() guard,
#: pane.py:663-668, enforces this in-process; this constant is the
#: same rule surviving a restart via the sidecar's terminal_status).
_NON_RESUMABLE_TERMINAL_STATUSES = frozenset({"error", "cap-hit"})

#: Tier-2 Resume's first query on the reconnected session (09/10's
#: cost-honesty posture: never invent what the human said — this is
#: plainly an engine-turn nudge, not a human message, and is never
#: rendered to the human as if they typed it; the transcript view shows
#: only the AGENT's response blocks, same as every other turn).
_RESUME_NUDGE_MESSAGE = (
    "(the human just resumed this conversation after a pause — the "
    "restored session already carries the full prior context; wait for "
    "their next instruction, or briefly acknowledge you're ready to "
    "continue if that feels natural. Do not repeat the earlier analysis "
    "unless asked.)"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html_tags(html: str) -> str:
    """A naive tag stripper for Tier-1.5 reinjection (§1's fallback):
    the persisted blocks are server-rendered markdown->HTML
    (rendering.py, XSS-safe), not attacker input, so this is a plain
    textual approximation for the model's context — never re-parsed as
    markup anywhere."""
    return _HTML_TAG_RE.sub("", html).strip()


def _compose_reinjected_first_message(stored: StoredSnapshot, original_first_message: str) -> str:
    """Tier 1.5 (§1's fallback / §8's "reinjection sends the transcript
    once as first_message context"): the persisted transcript, textually
    flattened, prefixed onto the SAME first_message the session would
    otherwise have opened with (record body / bucket context) — so the
    fresh engine gets both "what was already discussed" and "what this
    session is about"."""
    lines = ["=== PRIOR CONVERSATION (persisted — reinjected as context) ==="]
    for block in stored.blocks:
        if block.kind == "text" and block.html:
            lines.append(_strip_html_tags(block.html))
        elif block.kind == "tool":
            target = f" -> {block.tool_target}" if block.tool_target else ""
            lines.append(f"[tool used: {block.tool_name}{target}]")
    if stored.truncated:
        lines.append("(earlier turns not persisted — size cap)")
    lines.append("=== END PRIOR CONVERSATION ===")
    lines.append(original_first_message)
    return "\n\n".join(lines)


def _relative_time(iso: str | None) -> str | None:
    """A plain-words relative time ("2h ago") for the collapsed
    prior-conversation card (§5) — never the raw ISO timestamp (Y-9)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    now = datetime.now(dt.tzinfo) if dt.tzinfo is not None else datetime.now()
    seconds = max((now - dt).total_seconds(), 0)
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours // 24)
    return f"{days}d ago"


def _terminal_status_words(terminal_status: str | None) -> str | None:
    """The plain-words register for a persisted ``terminal_status``
    (§5/Y-9) — NEVER engine vocabulary (never the raw ``error_during_
    execution``/``error_max_turns`` subtype string). ``None`` when
    *terminal_status* isn't a known terminal-error class (a clean/absent
    result has no override here — the caller decides what to show
    instead). The ONE map both the idle card's
    :meth:`PaneManager._lifecycle_words` and the View footer's
    :meth:`PaneManager.view_snapshot` read from — never a second one."""
    if terminal_status == "error":
        return "hit an error"
    if terminal_status == "cap-hit":
        return "stopped early"
    return None


# ------------------------------------------------- target canon excerpt
#
# FW-48/U-marker-ui (2026-08-02): this module used to hand-copy
# self_learn.worker._canon_excerpt's body (resolution-by-scope,
# <200-line whole-file passthrough, else ±20 lines around the compiler's
# managed-section markers) on the stated belief that the worker function
# was private and worker-batch shaped, so this package "cannot import
# it". That was never true of the RULE — only of the one function's
# QueueEntry-shaped signature — and the hand-copy independently
# retyped the marker literal wrong (uppercase, no comment syntax; the
# compiler has only ever written the lowercase HTML-comment pair,
# self_learn.compilers.BEGIN_MARKER/END_MARKER). A second reader
# retyping the same needle and getting it wrong the same way is the
# CLI-side worker fix's own diagnosis of how it drifted there (see
# docs/specs/self-learn/drafts/u-marker-excerpt-case-spec.md §2) — the
# duplication was the defect, not just the string. The worker now
# exposes the rule as a public, record/bucket_dir-shaped function
# (self_learn.worker.canon_excerpt); this module imports and delegates
# to it instead of maintaining a second copy.


def target_canon_excerpt(home: Path, record: Record, bucket_dir: Path) -> str:
    """The candidate target's managed section ± 20 lines, or the whole
    file when under 200 lines — the SAME function the worker's own
    routing-analyst prompt uses (see module section docstring above);
    this is a direct delegation, not a second implementation."""
    return canon_excerpt(home, record, bucket_dir)


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


# ------------------------------------------------------- post-turn summary
#
# U21 (feedback round 5 item 7 / 10 §3 U21 row): the result footer's one
# plain-words line, built from two named sources ONLY (gate m7 / 09 §2.1
# holds — the server derives nothing new): the drain's own FileChanged
# events (never a diff/read/git — see :func:`_classify_file_fact`), and
# the propose_verb ToolUse + slot-placement composite (gate R5's
# current-turn attribution — see :meth:`PaneManager._compose_turn_summary`).


def _record_stem(record_id: str) -> str:
    """Mirrors ``engine/charter.py``'s own stem derivation exactly (that
    module is a one-way import for pane.py — SDK/charter internals stay
    behind the engine seam per 09 §4.1 — so the ``lrn-`` convention is
    reproduced here by filename, not imported)."""
    return record_id if record_id.startswith("lrn-") else f"lrn-{record_id}"


def _classify_file_fact(record_id: str, path: str) -> str:
    """One ``FileChanged.path`` (engine/base.py:73), classified relative
    to *record_id*'s own charter write-targets: the record's own pending
    file, a proposal sibling (yaml or diff), or anything else — shown
    shortened (its last two path segments; no diffing, no file reads,
    no git — this is filename classification only)."""
    stem = _record_stem(record_id)
    name = Path(path).name
    if name == f"{stem}.md":
        return "the lesson text"
    if name in (f"{stem}.yaml", f"{stem}.diff"):
        return "the proposal"
    parts = Path(path).parts
    return "/".join(parts[-2:]) if len(parts) >= 2 else name


def _join_facts(phrases: list[str]) -> str:
    if not phrases:
        return "nothing"
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def _compose_file_facts(record_id: str, paths: list[str]) -> str:
    """The dedup + classify + join pipeline (09 §2.1: the drain's own
    events are the ONLY source) — "nothing" when *paths* is empty."""
    seen_paths: list[str] = []
    for p in paths:
        if p not in seen_paths:
            seen_paths.append(p)
    phrases: list[str] = []
    for p in seen_paths:
        phrase = _classify_file_fact(record_id, p)
        if phrase not in phrases:
            phrases.append(phrase)
    return _join_facts(phrases)


def _proposal_clause(proposal: VerbProposal) -> str:
    """The verb, plus its destination glossed via ``models.destination_label``
    (F5-9's single-source resolver, reused — never a second map) when the
    proposal carries one (dest applies to ``route`` proposals only —
    proposals.py's own validation). A1: threads ``proposal.bucket_scope``
    through so a ``claude-md`` proposal glosses to the record's actual
    scope-resolved label (e.g. "Skills repo instructions"), not the
    scope-blind default. A2 §11: ``proposal.dest`` is the pane's ONLY
    variant signal (``claude-md:rules:<topic>`` / ``claude-md:local`` —
    the same qualified string ``_DEST_RE`` validated at intake), decoded
    via :func:`parse_variant_qualifier` so a pane-proposed rules route
    glosses as "User rule — subagents", never the plain scope-only label
    a variant-blind caller would show."""
    if proposal.dest:
        dest_base = proposal.dest.partition(":")[0]
        variant, rules_topic = parse_variant_qualifier(proposal.dest)
        gloss = destination_label(dest_base, proposal.bucket_scope, variant, rules_topic)
        return f"{proposal.verb} to {gloss}"
    return proposal.verb


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
    #: U21: THIS turn's own FileChanged.path targets, dedup-appended in
    #: arrival order — reset at every drain entry (per-turn, like the
    #: latches above; never accumulates across turns).
    turn_file_paths: list[str] = field(default_factory=list)
    #: U21 gate R5 signal (a): THIS turn's drain saw a propose_verb
    #: ToolUse. Reset at every drain entry.
    turn_saw_propose_tooluse: bool = False
    #: U21 gate R5's edge pin: the proposal slot's occupant nonce (or
    #: None if empty) captured the FIRST time this turn's propose_verb
    #: ToolUse lands — BEFORE the handler (which runs after the ToolUse
    #: event is yielded) has a chance to occupy/refuse. Compared against
    #: the slot's occupant at pane_result: unchanged means this turn's
    #: call never placed anything (refused-by-occupancy, or never ran) —
    #: a prior turn's still-waiting proposal must never misattribute to
    #: this turn's summary (the exact R5 disaster). Reset at every drain
    #: entry.
    turn_propose_nonce_before: str | None = None
    #: The composed post-turn summary line (U21), set once at this
    #: turn's Result event — persists on the live session exactly like
    #: result_status/cost/turns (rendered by the SAME footer block,
    #: 09 §2.1: server derives nothing new at render time).
    turn_summary: str | None = None
    #: U22 (Y-28): this session was claimed via resume(), not start() —
    #: _run_first_turn reads this to call store.continue_existing()
    #: (append to the SAME file) instead of store.start_new() (archive +
    #: fresh header).
    is_resume: bool = False
    #: U22: resume()'s pre-built PaneContext (resume_session_id set for
    #: Tier 2, or a reinjected first_message for Tier 1.5) —
    #: _run_first_turn uses this in place of calling context_builder
    #: again when set.
    resume_ctx_override: PaneContext | None = None
    #: U22: "resumed" (Tier 2 SDK-resume) | "reinjected" (Tier 1.5) |
    #: None (an ordinary fresh session) — the honest lifecycle line
    #: (§5) reads this; never claims a tier that did not actually fire.
    resumed_note: str | None = None


@dataclass(frozen=True)
class PaneSnapshot:
    """A read-only rendering view — ``routes.py``'s ONLY window into pane
    state (never mutate through it). ``result_turns`` is the engine-
    reported turn count from :class:`~self_learn_ui.engine.base.Result`
    (``num_turns``), ``None`` only when the engine reports none — the
    footer renders it verbatim (09 §4.2's "cost footer … plus turn
    count", 10 §1's SSE ``turns`` pin). The interim-review seam gap
    (Result once lacked a turn field) was closed 2026-07-17. ``turn_summary``
    (U21) is the post-iterate change-summary line — part of the SAME
    footer block as ``result_status``; ``None`` before any Result has
    landed for this session."""

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
    turn_summary: str | None
    #: U22 (Y-28 §5): whether ANY transcript is persisted for this
    #: session key, regardless of resumability — drives the idle
    #: region's collapsed prior-conversation card vs the bare prompt.
    has_persisted_transcript: bool = False
    #: U22: the §4e three-clause predicate — gates the Resume control.
    #: Always ``False`` on a LIVE snapshot (resume is an idle-only
    #: action) and on a view-only snapshot.
    resumable: bool = False
    #: U22: the card's block-count fact — ``None`` when nothing persisted.
    persisted_block_count: int | None = None
    #: U22: the card's plain-words relative time ("2h ago") — Y-9, never
    #: a raw ISO timestamp.
    persisted_relative_time: str | None = None
    #: U22: the card's plain-words state — "waiting for you" | "finished"
    #: | "stopped early" | "hit an error" — NEVER engine vocabulary
    #: (Y-9; §5's exact register).
    persisted_lifecycle_words: str | None = None
    #: U22: the honest per-tier annotation under a LIVE resumed/
    #: reinjected/view-only session (§5) — "(resumed — earlier turns
    #: restored)" / "(continued — earlier turns re-read as context)" /
    #: "(view only)" / "(record resolved — view only)". ``None`` under
    #: an ordinary fresh live session.
    lifecycle_note: str | None = None
    #: U22: a read-only reconstruction from disk (the View control) —
    #: the template hides Send/Interrupt/Close-that-discards in favor
    #: of a single non-destructive Back control.
    view_only: bool = False


def _idle_snapshot(
    record_id: str,
    validate: tuple[int, str] | None,
    *,
    has_persisted_transcript: bool = False,
    resumable: bool = False,
    persisted_block_count: int | None = None,
    persisted_relative_time: str | None = None,
    persisted_lifecycle_words: str | None = None,
) -> PaneSnapshot:
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
        turn_summary=None,
        has_persisted_transcript=has_persisted_transcript,
        resumable=resumable,
        persisted_block_count=persisted_block_count,
        persisted_relative_time=persisted_relative_time,
        persisted_lifecycle_words=persisted_lifecycle_words,
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
        store: PaneTranscriptStore | None = None,
        home: Path | None = None,
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
        # U22 (Y-28): the Tier-1 render-event store. `None` keeps every
        # pre-U22 test/construction working exactly as before — every
        # store-touching branch below is `if self._store is not None`.
        self._store = store
        # U22: `home` powers the §4e resumable predicate's ledger checks
        # (record status + bucket_dir match) — `None` disables the
        # predicate safely (resumable always reads False, never raises).
        self._home = home
        # U22: Y-28 §6 says "opportunistic ... at manager construction" —
        # but pruning needs the store's resolved dir (cache_dir() in
        # production), and resolving THAT eagerly right here would touch
        # the real cache dir at build_pane_manager()/create_app() time
        # for every caller, including every test that constructs an app
        # but never actually opens a pane (a regression against 10 §0
        # rules 7/8). Deferred to the first REAL store touch instead
        # (see :meth:`_maybe_prune_once`, called from :meth:`snapshot`) —
        # "opportunistic" is satisfied by "at the first opportunity a
        # pane is actually rendered," not literally at `__init__`.
        self._pruned_once = False

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
        self._maybe_prune_once()
        validate = self._validate_results.get(record_id)
        if self._live is None or self._live.record_id != record_id:
            return self._idle_snapshot_with_persistence(record_id, validate)
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
            turn_summary=live.turn_summary,
            has_persisted_transcript=self._store is not None,
            resumable=False,  # U22: resume is an idle-only action
            lifecycle_note=self._lifecycle_note_for(live),
        )

    def validate_state(self, record_id: str) -> tuple[int, str] | None:
        return self._validate_results.get(record_id)

    # ------------------------------------------------------- U22 (Y-28)

    def _maybe_prune_once(self) -> None:
        """Y-28 §6's "opportunistic ... at manager construction," honored
        at the first REAL store touch instead of literally at
        ``__init__`` (see the constructor's comment) — one prune per
        manager lifetime from this call site; :meth:`close`/
        :meth:`_teardown_live` additionally prune on EVERY teardown per
        the spec's other clause."""
        if self._store is not None and not self._pruned_once:
            self._pruned_once = True
            self._store.prune()

    def _lifecycle_note_for(self, live: "_Live") -> str | None:
        if live.resumed_note == "resumed":
            return "(resumed — earlier turns restored)"
        if live.resumed_note == "reinjected":
            return "(continued — earlier turns re-read as context)"
        return None

    def _idle_snapshot_with_persistence(
        self, record_id: str, validate: tuple[int, str] | None
    ) -> PaneSnapshot:
        if self._store is None:
            return _idle_snapshot(record_id, validate)
        stored = self._store.read_snapshot(record_id)
        if stored is None:
            return _idle_snapshot(record_id, validate)
        resumable = self._is_resumable(record_id, stored)
        return _idle_snapshot(
            record_id,
            validate,
            has_persisted_transcript=True,
            resumable=resumable,
            persisted_block_count=len(stored.blocks),
            persisted_relative_time=_relative_time(stored.updated_at),
            persisted_lifecycle_words=self._lifecycle_words(stored, resumable),
        )

    def _lifecycle_words(self, stored: StoredSnapshot, resumable: bool) -> str:
        """§5's exact plain-words register — NEVER engine vocabulary."""
        words = _terminal_status_words(stored.terminal_status)
        if words is not None:
            return words
        if resumable:
            return "waiting for you"
        return "finished"

    def _is_resumable(self, session_key: str, stored: StoredSnapshot) -> bool:
        """§4e's three-clause predicate, ALL required: status
        pending/deferred (or the bucket still exists, for a bucket
        session — buckets have no "status"), the record's CURRENT
        ``bucket_dir`` resolved-equals the recorded one (a rehome
        invalidates), and the sidecar's ``terminal_status`` is not
        error/cap-hit (survives a restart, unlike the live ``send()``
        guard alone)."""
        if stored.terminal_status in _NON_RESUMABLE_TERMINAL_STATUSES:
            return False
        if not stored.bucket_dir or self._home is None:
            return False
        try:
            recorded_dir = Path(stored.bucket_dir).resolve()
        except OSError:
            return False
        parsed = parse_bucket_session_key(session_key)
        if parsed is not None:
            scope, name = parsed
            bucket = next(
                (b for b in ledger.discover_buckets(self._home) if b.scope == scope and b.name == name),
                None,
            )
            return bucket is not None and Path(bucket.path).resolve() == recorded_dir
        location = ledger.locate_record(self._home, session_key)
        if location is None:
            return False
        record = ledger.read_record(location.path)
        if record is None or record.status not in ("pending", "deferred"):
            return False
        return Path(location.bucket_dir).resolve() == recorded_dir

    def view_snapshot(self, record_id: str) -> PaneSnapshot | None:
        """The View control (§5): a read-only reconstruction straight
        from the store, independent of any live session. ``None`` when
        nothing is persisted (the route degrades to the idle region)."""
        self._maybe_prune_once()
        if self._store is None:
            return None
        stored = self._store.read_snapshot(record_id)
        if stored is None:
            return None
        blocks = tuple(
            TranscriptBlock(kind=b.kind, html=b.html, tool_name=b.tool_name, tool_target=b.tool_target)
            for b in stored.blocks
        )
        result = stored.result
        note = "(earlier turns unreadable)" if stored.corrupt else "(view only)"
        if stored.truncated:
            note = "(earlier turns not persisted — size cap)"
        # Fold 1 (blind gate, 2026-07-19): view_snapshot sets
        # error_message=None to suppress the live Retry control (view-only
        # has nothing to retry) — but that left an errored/cap-hit stored
        # result falling through to pane.html's plain result-footer
        # branch, which renders result_status VERBATIM. That branch has
        # no Y-9 filter of its own (unlike the card, which always reads
        # through _lifecycle_words), so the raw engine subtype
        # (error_during_execution / error_max_turns) leaked to the human.
        # Same map the card uses (_terminal_status_words) — never a
        # second one — overrides the footer's status text for exactly
        # the terminal-error case; a clean/absent result is untouched.
        terminal_words = _terminal_status_words(stored.terminal_status)
        result_status = (
            f"(this session {terminal_words})"
            if terminal_words is not None
            else (result.status if result else None)
        )
        return PaneSnapshot(
            record_id=record_id,
            state=STATE_ENDED,
            blocks=blocks,
            current_kind=None,
            current_html=None,
            result_status=result_status,
            result_cost_usd=result.cost_usd if result else None,
            result_turns=result.turns if result else None,
            error_message=None,
            cap_hit=False,
            validate_exit_code=None,
            validate_stderr=None,
            turn_summary=None,
            has_persisted_transcript=True,
            resumable=False,
            persisted_block_count=len(stored.blocks),
            persisted_relative_time=_relative_time(stored.updated_at),
            persisted_lifecycle_words=None,
            lifecycle_note=note,
            view_only=True,
        )

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
        join deterministically via :meth:`wait_for_turn`.

        U22 (Y-28 §6): this is ALWAYS a fresh session — if a transcript
        was already persisted for ``record_id``, :meth:`_run_first_turn`
        archives it (``store.start_new``) before the new header is
        written, so "Start fresh" (the idle card's control) is simply
        this same method."""
        claim = await self._claim_live_slot(record_id, force=force)
        if isinstance(claim, str):
            return claim
        live = claim
        live.drain_task = asyncio.create_task(self._run_first_turn(live))
        return "started"

    async def resume(self, record_id: str, *, force: bool = False) -> str:
        """U22 (Y-28 §1/§4/§5's Resume control): reopen a
        persisted-but-not-live session, continuing the SAME transcript
        file (never archived — contrast :meth:`start`). Same
        one-live-session outcomes as :meth:`start` (``"armed"``/
        ``"resumed"``); ``"not-resumable"`` when no store is wired or
        the §4e predicate fails — server-side defense in depth beneath
        the UI's own gating (the control only renders when the idle
        snapshot already agreed).

        Tries Tier 2 (SDK-resume) when the persisted sidecar carries a
        captured ``sdk_session_id``; falls back to Tier 1.5 (first-
        message reinjection) otherwise — EITHER WAY this dispatches one
        real background first turn (like :meth:`start`), because a
        silent reconnect-with-no-turn has no seam on the pinned
        ``PaneEngine`` API (10 §1) and the reinjection tier has no
        other way to "say" anything to the model at all. §8's cost
        note ("Resume pays the history re-send for continuity") is
        exactly this turn's cost."""
        if self._store is None:
            return "not-resumable"
        stored = self._store.read_snapshot(record_id)
        if stored is None or not self._is_resumable(record_id, stored):
            return "not-resumable"
        claim = await self._claim_live_slot(record_id, force=force)
        if isinstance(claim, str):
            return claim
        live = claim
        live.is_resume = True
        base_ctx = self._context_builder(record_id)
        if stored.sdk_session_id:
            live.resume_ctx_override = replace(
                base_ctx,
                resume_session_id=stored.sdk_session_id,
                first_message=_RESUME_NUDGE_MESSAGE,
            )
            live.resumed_note = "resumed"
        else:
            live.resume_ctx_override = replace(
                base_ctx,
                first_message=_compose_reinjected_first_message(stored, base_ctx.first_message),
            )
            live.resumed_note = "reinjected"
        live.drain_task = asyncio.create_task(self._run_first_turn(live))
        return "started"

    async def _claim_live_slot(self, record_id: str, *, force: bool) -> "_Live | str":
        """The one-live-session guard shared by :meth:`start` and
        :meth:`resume` (Y-15/F5's synchronous-claim discipline, U22
        fold): returns ``"armed"``/``"resumed"`` per the existing rules,
        or a freshly-claimed, slot-assigned :class:`_Live` ready for its
        caller to attach a ``drain_task`` to."""
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
        return live

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
        """``q`` (09 §2.4). U22 (Y-28 §4c) reworks this from a hard
        discard to a PARK-TO-DISK: every finalized block is already on
        disk (§0's durability model — this method writes nothing new
        except the trailing in-flight block, a nicety); the live
        in-memory ``_Live`` is still torn down exactly as before (the
        engine closes, the slot clears) so a subsequent Detail render
        collapses to the idle region, now showing the collapsed
        prior-conversation card (§5) instead of the bare prompt. The
        validate badge (if any) is NOT cleared here — it is ledger/scan
        state, not transcript state."""
        if self._live is None or self._live.record_id != record_id:
            return False
        live, self._live = self._live, None
        await self._dispose_drain(live)
        self._flush_trailing_inflight(live)
        if live.engine is not None:
            await live.engine.close()
        # Y-13 clear-set: the proposing session ended (`q`).
        self._proposal_slot.clear_for_session(record_id)
        if self._store is not None:
            self._store.prune()
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
        # U22 (Y-28 §0/§4b/§4d/§4f): every FINALIZED block is already on
        # disk; this captures only a trailing IN-FLIGHT block so a
        # restart/idle-park/verb-teardown loses nothing that was
        # actually streamed. Never the durability mechanism — a nicety.
        self._flush_trailing_inflight(live)
        if live.engine is not None:
            await live.engine.interrupt()
            await live.engine.close()
        # Y-13 clear-set: teardown ends the proposing session (interrupt
        # via verb dispatch, or a forced start on another item).
        self._proposal_slot.clear_for_session(live.record_id)
        if self._store is not None:
            self._store.prune()

    def _flush_trailing_inflight(self, live: _Live) -> None:
        """Y-28 §0's teardown-time capture: append the trailing
        in-flight TEXT block (if any) — tool blocks are never left
        in-flight (``_handle_event``'s ToolUse leg finalizes any pending
        text block first, then appends the tool block atomically, so
        ``current_kind`` is only ever ``"text"`` mid-stream). A no-op
        when there is no store or nothing in flight yet (an in-flight
        block with zero deltas so far renders "" — nothing worth
        persisting)."""
        if self._store is None or live.current_kind != "text" or not live.current_text:
            return
        html = render_markdown(live.current_text)
        self._store.append_block(live.record_id, kind="text", html=html)

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
                # order-independent). U22: resume() pre-builds its own
                # ctx (resume_session_id set, or first_message
                # reinjected) — use it in place of a fresh
                # context_builder call when present.
                ctx = live.resume_ctx_override if live.resume_ctx_override is not None else self._context_builder(live.record_id)
                if self._store is not None:
                    if live.is_resume:
                        # Y-28 §4/§6: Resume continues the SAME file —
                        # never archived, never a fresh header.
                        self._store.continue_existing(live.record_id)
                    else:
                        # Y-28 §6: start()/"Start fresh" — archive any
                        # existing history, then a fresh header.
                        self._store.start_new(
                            live.record_id,
                            record_id_or_bucket=live.record_id,
                            bucket_dir=str(ctx.bucket_root),
                        )
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
        # U21 per-turn reset (same convention as the latches above): THIS
        # turn's own file-change/propose-attribution state, never
        # accumulated across turns — turn_summary itself is NOT reset
        # here (it persists like result_status until the NEXT Result
        # overwrites it, so a mid-turn re-render still shows the prior
        # turn's summary rather than blanking it).
        live.turn_file_paths = []
        live.turn_saw_propose_tooluse = False
        live.turn_propose_nonce_before = None
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
        # U22 (Y-28 §1): the FIRST of the three pinned append points —
        # incremental append, flush()ed at write (§0's durability
        # model). Placed AFTER the in-memory mutation above for the
        # exact same reordering reason as the publish below (FW-18 fix
        # 2): a store write is not a suspension point in this runtime
        # (plain sync file I/O), but keeping it beside the in-memory
        # mutation — both before the only await in this method — keeps
        # "the block is finalized" a single atomic-looking step.
        if self._store is not None:
            self._store.append_block(live.record_id, kind="text", html=html)
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
            # U22 (Y-28 §1): the SECOND pinned append point.
            if self._store is not None:
                self._store.append_block(
                    live.record_id, kind="tool", tool_name=event.name, tool_target=event.target
                )
            await self._app_hub.publish({"type": "pane_tool", "name": event.name, "target": event.target})
            if event.name == PROPOSAL_TOOL_QUALIFIED_NAME and not live.turn_saw_propose_tooluse:
                # U21 gate R5's edge pin: capture the slot's occupant
                # BEFORE the handler (invoked by the SDK between this
                # event and the tool's result) can occupy/refuse it —
                # only on the FIRST such ToolUse this turn, so a retried
                # call after an in-turn refusal keeps the true
                # before-this-turn baseline.
                live.turn_saw_propose_tooluse = True
                current = self._proposal_slot.current
                live.turn_propose_nonce_before = current.nonce if current is not None else None
        elif isinstance(event, FileChanged):
            # Task brief / 09 §2.4/§4.3: mid-session file_changed ->
            # re-render push ONLY, never validation.
            self._refresh_hub.force_refresh(f"record:{live.record_id}")
            if event.path not in live.turn_file_paths:
                live.turn_file_paths.append(event.path)
        elif isinstance(event, Result):
            await self._finalize_current(live)
            live.result_status = event.status
            live.result_cost_usd = event.cost_usd
            live.result_turns = event.turns
            live.cap_hit = bool(event.error) and _is_cap_hit(event.status)
            live.error_message = event.error
            # U22 (Y-28 §1): the THIRD pinned append point — the
            # terminal Result footer, plus the captured session_id
            # (Tier 2's later resume target) and the terminal_status
            # the §4e predicate reads back after a restart.
            if self._store is not None:
                self._store.append_result(
                    live.record_id,
                    status=event.status,
                    cost_usd=event.cost_usd,
                    turns=event.turns,
                    error=event.error,
                    cap_hit=live.cap_hit,
                    session_id=event.session_id,
                )
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
            # U21: composed AT pane_result, before any clear_for_session
            # below could clear the very proposal this turn just placed
            # (gate m7's "at pane_result" pin — the slot read below must
            # see this turn's own placement, not its own aftermath).
            live.turn_summary = self._compose_turn_summary(live)
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

    def _compose_turn_summary(self, live: _Live) -> str:
        """U21's post-iterate change-summary line (10 §3 U21 row). File
        facts come from THIS turn's own accumulated FileChanged paths
        (:func:`_compose_file_facts` — 09 §2.1: no diffing, no reads, no
        git). The proposal clause appends iff BOTH gate R5 signals hold:
        (a) this turn's drain saw a propose_verb ToolUse
        (``live.turn_saw_propose_tooluse``), AND (b) the slot's CURRENT
        occupant was placed by THIS session (matched by ``session_key``
        — the SAME identity ``clear_for_session`` uses; a bucket
        session's proposal names a pending RECORD elsewhere in the
        bucket, so ``record_id`` is the wrong key there, session_key is
        the one field both session kinds share with ``live.record_id``),
        is WAITING (never armed), and whose nonce differs from the one
        captured when the ToolUse landed (``live.turn_propose_nonce_before``)
        — i.e. the slot actually changed during this turn, not merely
        still holding a prior turn's still-waiting proposal that this
        turn's call was refused against (the R5 edge case)."""
        facts = _compose_file_facts(live.record_id, live.turn_file_paths)
        proposal_clause: str | None = None
        if live.turn_saw_propose_tooluse:
            current = self._proposal_slot.current
            if (
                current is not None
                and current.session_key == live.record_id
                and not current.armed
                and current.nonce != live.turn_propose_nonce_before
            ):
                proposal_clause = _proposal_clause(current)
        line = f"This turn changed: {facts}"
        if proposal_clause:
            line += f", and proposed: {proposal_clause}"
        return line + "."

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

    # U22 (Y-28 §2/§7): the store lives under the SAME cache_dir()
    # namespace as ui-token/uilog — "the store imports only
    # self_learn.worker.cache_dir, an existing public seam" (§7's
    # verify-at-build pin). Tier 1's render-event mirror and Tier 2's
    # SDK session mirror are separate subdirectories (store.py's module
    # docstring — never the same artifact). Both are LAZY (cache_dir()
    # is a zero-arg callable here, not called yet) — this function runs
    # at create_app() time for every app instance, including tests that
    # never open a pane; resolving cache_dir() (which unconditionally
    # `mkdir`s its own base dir, pinned cli-package behavior) eagerly
    # here would touch the real cache dir for all of them.
    store = PaneTranscriptStore(lambda: cache_dir() / "panes")

    def engine_factory() -> PaneEngine:
        return SdkPaneEngine(
            model=env.pane_model,
            fallback_model=DEFAULT_FALLBACK_MODEL,
            max_turns=env.pane_max_turns,
            max_budget_usd=env.pane_budget_usd,
            sdk_session_store_root=cache_dir() / "panes" / "sdk-sessions",
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
        store=store,
        home=env.self_learn_home,
    )
