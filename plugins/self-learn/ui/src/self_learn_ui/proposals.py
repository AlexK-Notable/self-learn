"""proposals.py — the pane verb-proposal machinery (09 §4.5 / §11 Y-13,
as reworked 2026-07-17; 10 §1 "Pane proposal tool" row; task U12).

Three pieces, all server-side:

- :class:`VerbProposal` — one validated proposal's frozen fields. Verb,
  record id, destination, date, and note are SERVER-validated before the
  instance exists; the note is agent prose (rendered under an explicit
  label, capped at intake — never display-truncated, so the note the
  human reads is byte-identical to the ``--note`` the confirm executes).
- :class:`ProposalSlot` — the surface's FIRST server-held armed-state
  precursor (09 §4.5's dated acknowledgment: the standing arm machine is
  stateless server-side; this one cannot be). ONE in-memory slot,
  never persisted (a server restart clears it by construction), with
  the pinned clear-set wired by its owners: human confirm · human
  dismiss · the proposing session ending for any reason · the record
  leaving pending · restart. Page navigation does NOT clear it — any
  in-scope render re-renders the waiting bar from this slot.
- :func:`make_propose_handler` — the ``propose_verb`` tool's server-side
  handler for ONE pane session. The engine (``engine/sdk.py``) wraps it
  in an in-process SDK MCP server (``self-learn-surface``); everything
  the tool does — validation, slot occupancy, the SSE ``pane_proposal``
  push — happens in THIS process. Its entire effect is rendering
  consent to the human: the runner is invoked only by the human's
  confirm POST (09 §4.3 "no path to EXECUTE").

**Refuse-not-replace** (09 §4.5): while the slot is occupied — waiting
OR armed — further proposals refuse. A replace rule would let the bar's
content change between the human's read and their keystroke.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from self_learn.hosts import HostsError, load_hosts, slug_for
from self_learn.ledger_ops import record_title

from . import ledger

__all__ = [
    "NOTE_MAX_CHARS",
    "PROPOSABLE_VERBS",
    "PROPOSAL_TOOL_NAME",
    "PROPOSAL_SERVER_NAME",
    "PROPOSAL_TOOL_QUALIFIED_NAME",
    "ProposalSlot",
    "SessionScope",
    "TOOL_ACCEPTED_MESSAGE",
    "VerbProposal",
    "make_propose_handler",
    "validate_proposal",
]

#: 09 §4.5's CLOSED verb list. Extending it is a dated spec edit, never a
#: code-only change (10 §4 judgment row). `host add` is excluded by
#: Y-11's no-agent-path pin; collapse and the telemetry verbs by dated
#: v1 decision. `rehome` joined 2026-07-18 (feedback round 3 item 3;
#: §11 Y-18) — Y-11 holds because only already-registered targets are
#: nameable: the agent widens no read scope and mints no write target.
PROPOSABLE_VERBS = frozenset({"route", "reject", "defer", "graduate", "rehome"})

#: 10 §1: the in-process SDK MCP server name and the single tool it
#: exposes. The fully-qualified form is what the charter callback's
#: allow-rule matches EXACTLY.
PROPOSAL_SERVER_NAME = "self-learn-surface"
PROPOSAL_TOOL_NAME = "propose_verb"
PROPOSAL_TOOL_QUALIFIED_NAME = f"mcp__{PROPOSAL_SERVER_NAME}__{PROPOSAL_TOOL_NAME}"

#: 09 §4.5 (delta R4): the note is capped at INTAKE — refused, never
#: display-truncated — so the displayed note equals the executed note.
NOTE_MAX_CHARS = 200

#: The tool's honest, immediate return (09 §4.5).
TOOL_ACCEPTED_MESSAGE = (
    "rendered — the human decides; you will not be notified of a cancel."
)

#: 09 §4.5's dest validation clause (delta R9→F9): the full 02 §1
#: surface forms. Refuse only on PARSE failure; structural validity
#: (e.g. a hook dest without stored script bytes) stays the verb's to
#: enforce, its refusal rendering verbatim.
#: ``\Z`` anchors, never ``$`` (code review F8: Python ``$`` matches
#: before a trailing newline — a dest with an invisible trailing byte
#: would validate and render indistinguishably from the clean form).
#: A2 §4.2 (the UI-side twin of the CLI's ``_parse_dest``, ``verbs.py:
#: 404``): ``claude-md:local`` / ``claude-md:rules:<topic>`` added
#: alongside plain ``claude-md`` — these two parsers MUST move together
#: (§4.2's sync obligation) or a proposal carrying the new forms fails
#: UI validation while the CLI accepts the same string.
_DEST_RE = re.compile(
    r"\A(skill-md|claude-md(:local|:rules:[a-z0-9][a-z0-9-]*)?"
    r"|reference(:.+)?|new-skill:.+|hook)\Z"
)

_RECORD_ID_RE = re.compile(r"\Alrn-[0-9a-f]{8}\Z")

_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

#: Review F9: dest's parameterized suffixes are agent-authored text
#: rendered in the bar's server-truth position — intake-capped like the
#: note (parse validity stays the verb's; this is a register/layout cap).
DEST_MAX_CHARS = 100


@dataclass(frozen=True)
class SessionScope:
    """What ONE pane session may propose against (09 §4.5 validation):
    a record session may name only its own record; a bucket session may
    name any pending record in its own bucket."""

    kind: str  # "record" | "bucket"
    session_key: str  # PaneManager's session key (record id, or "bucket:<scope>/<name>")
    record_id: str | None = None  # record sessions only
    bucket_dir: Path | None = None  # bucket sessions only
    bucket_scope: str | None = None
    bucket_name: str | None = None


@dataclass(frozen=True)
class VerbProposal:
    """One validated, slot-occupying proposal. ``armed`` is the ONLY
    mutable-by-replacement field (waiting <-> armed transitions go
    through :class:`ProposalSlot`)."""

    verb: str
    record_id: str
    bucket_scope: str
    bucket_name: str
    session_key: str
    #: The record's Y-9 human line (the CLI's own ``record_title``
    #: derivation, imported — P2-4), captured at validation so the bar
    #: LEADS with it and the id renders as trailing metadata (review F2).
    title: str = ""
    dest: str | None = None
    note: str | None = None
    until: str | None = None
    #: rehome only (09 §4.5 as amended 2026-07-18 / §11 Y-18): the
    #: RESOLVED registered-project path — a server-truth bar field, the
    #: hosts.yaml path the handler resolved, never the agent's raw
    #: string. The confirm rebuilds argv from it.
    to: str | None = None
    armed: bool = False
    #: Server nonce (review F5): arm/confirm/disarm/dismiss POSTs must
    #: echo it, so a clear-then-reoccupy between the human's read and
    #: their keystroke can never act on a proposal they haven't seen.
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(8))

    @property
    def to_basename(self) -> str:
        """Y-18 fold F7: the bar's ⟨name⟩ is the registered path's
        BASENAME (slugs are unreadable); when two registered projects
        share a basename the trailing resolved path disambiguates."""
        return Path(self.to).name if self.to else ""


class ProposalSlot:
    """The single server-held pending proposal (09 §4.5). In-memory
    only; every mutation is a whole-object swap, no partial state."""

    def __init__(self) -> None:
        self._current: VerbProposal | None = None

    @property
    def current(self) -> VerbProposal | None:
        return self._current

    def occupy(self, proposal: VerbProposal) -> bool:
        """False (refuse-not-replace) when already occupied."""
        if self._current is not None:
            return False
        self._current = proposal
        return True

    def _matches(self, record_id: str, nonce: str | None) -> bool:
        """Identity match for a human POST (review F5): record AND nonce —
        a clear-then-reoccupy mints a new nonce, so a keystroke aimed at
        the OLD proposal takes the stale path, never the new content."""
        return (
            self._current is not None
            and self._current.record_id == record_id
            and (nonce is None or self._current.nonce == nonce)
        )

    def arm(self, record_id: str, nonce: str | None = None) -> VerbProposal | None:
        """Arm the waiting proposal for ``record_id``; None when the slot
        holds nothing matching (a stale POST — render unarmed)."""
        if not self._matches(record_id, nonce):
            return None
        assert self._current is not None
        self._current = replace(self._current, armed=True)
        return self._current

    def disarm(self, record_id: str, nonce: str | None = None) -> VerbProposal | None:
        """Back to WAITING — never cleared (09 §4.5: disarm returns the
        bar to waiting; dismissal is the explicit clear)."""
        if not self._matches(record_id, nonce):
            return None
        assert self._current is not None
        self._current = replace(self._current, armed=False)
        return self._current

    def clear(self) -> None:
        self._current = None

    def clear_for_record(self, record_id: str) -> bool:
        """Clear-set member: the record left pending (resolved
        elsewhere, or a confirm just resolved it)."""
        if self._current is not None and self._current.record_id == record_id:
            self._current = None
            return True
        return False

    def clear_for_session(self, session_key: str) -> bool:
        """Clear-set member: the proposing session ended (any reason)."""
        if self._current is not None and self._current.session_key == session_key:
            self._current = None
            return True
        return False


def _refuse(reason: str) -> str:
    return f"proposal refused: {reason}"


def _registered_project_for(home: Path, to: str) -> Path | None:
    """Resolve ``to`` (a registered project's path or its bucket slug —
    the ``host rebind`` naming precedent) against hosts.yaml, the CLI's
    own registration authority. None when nothing registered matches."""
    try:
        hosts = load_hosts(home)
    except HostsError:
        return None
    candidate = Path(to).expanduser()
    for project in hosts.projects:
        registered = Path(project).expanduser()
        if slug_for(registered) == to or registered.resolve() == candidate.resolve():
            return registered.resolve()
    return None


def validate_proposal(
    home: Path,
    scope: SessionScope,
    args: dict[str, Any],
) -> VerbProposal | str:
    """The 09 §4.5 / 10 §1 validation chain, in pinned order. Returns a
    :class:`VerbProposal` or a refusal string for the agent (it can
    correct itself or ask the human). Nothing renders on refusal."""
    # Empty strings are ABSENT (T-B(6) live finding, 2026-07-17: under
    # the SDK's dict-of-types schema shorthand the model filled optional
    # params with "" — the schema is now a real JSON Schema with only
    # verb/record_id required, and this normalization is the belt so a
    # ""-filling model never turns a valid route into a refusal).
    args = {k: (None if v == "" else v) for k, v in args.items()}

    verb = args.get("verb")
    if not isinstance(verb, str) or verb not in PROPOSABLE_VERBS:
        allowed = ", ".join(sorted(PROPOSABLE_VERBS))
        return _refuse(
            f"verb {verb!r} is not proposable — the closed list is: {allowed}. "
            "Registering projects (host add) and cluster collapses are not "
            "proposable at all; ask the human to do those directly."
        )

    record_id = args.get("record_id")
    if not isinstance(record_id, str) or not _RECORD_ID_RE.match(record_id):
        return _refuse(f"record_id {record_id!r} is not a valid lrn-<8 hex> id")

    if scope.kind == "record":
        if record_id != scope.record_id:
            return _refuse(
                f"this session is bound to {scope.record_id} and may only "
                "propose on that record"
            )
    location = ledger.locate_record(home, record_id)
    if location is None:
        return _refuse(f"{record_id} is not a pending record")
    # Review F1: "resolves to a PENDING record" means STATUS, not mere
    # existence — locate_record also finds resolved/ records, and a
    # consent bar must never advertise an impossible action.
    record = ledger.read_record(location.path)
    if record is None or record.status not in ("pending", "deferred"):
        return _refuse(f"{record_id} is not a pending record (already resolved?)")
    if scope.kind == "bucket":
        assert scope.bucket_dir is not None
        if Path(location.bucket_dir).resolve() != Path(scope.bucket_dir).resolve():
            return _refuse(
                f"{record_id} is outside this bucket — a bucket session may "
                "only propose on its own bucket's pending records"
            )

    dest = args.get("dest")
    if dest is not None:
        if verb != "route":
            return _refuse("dest only applies to route proposals")
        if not isinstance(dest, str) or not _DEST_RE.match(dest):
            return _refuse(
                f"dest {dest!r} does not parse — accepted forms: skill-md, "
                "claude-md, claude-md:local, claude-md:rules:<topic>, "
                "reference, reference:<file>, new-skill:<name>, hook"
            )
        if len(dest) > DEST_MAX_CHARS:
            return _refuse(
                f"dest is {len(dest)} characters — the cap is {DEST_MAX_CHARS}"
            )
        # 09 §4.5 as amended 2026-07-18 (feedback round 2 item 3): scope
        # validity joins parse validity at intake — the CLI's own rules
        # (the route verb's _resolve_target: skill-md needs skill:<name>
        # scope; reference needs skill or project). A scope-impossible
        # dest must never reach the human as an armable proposal; other
        # structural validity (e.g. a hook dest without stored script
        # bytes) stays the verb's to enforce.
        dest_base = dest.partition(":")[0]
        if dest_base == "skill-md" and location.scope != "skill":
            alternates = (
                "claude-md or reference[:file]"
                if location.scope == "project"
                else "claude-md"
            )
            return _refuse(
                "skill-md only exists for skill-scoped lessons; this record "
                f"is {location.scope}-scoped — use {alternates}"
            )
        if dest_base == "reference" and location.scope not in ("skill", "project"):
            return _refuse(
                "reference files live with a skill or project; this record "
                f"is {location.scope}-scoped — use claude-md"
            )

    # 09 §4.5 as amended 2026-07-18 (feedback round 3 item 3; §11 Y-18,
    # the round-2 teach-the-agent-at-proposal-time precedent): `to` only
    # applies to rehome and is validated AT INTAKE against the
    # registered-project set (hosts.yaml, the CLI's own authority) — an
    # armable-but-impossible proposal never renders. The stored target
    # is the RESOLVED hosts.yaml path (server truth), never the agent's
    # raw string.
    to = args.get("to")
    resolved_to: str | None = None
    if to is not None and verb != "rehome":
        return _refuse("to only applies to rehome proposals")
    if verb == "rehome":
        if not isinstance(to, str) or not to:
            return _refuse(
                "rehome needs to — the registered project to move this "
                "lesson to (path or bucket slug)"
            )
        # U-verbs MOVE9: the CLI-side source-scope restriction (M1,
        # project-only) is gone — `_move` now accepts any live-status
        # source scope. Only the TARGET stays narrowed to a registered
        # project: the UI's `rehome` proposal is deliberately still
        # project-only on the DESTINATION side (a `to` naming a skill or
        # `user` is not this proposal's grammar at all — `rescope`, not
        # proposable, is the verb for that).
        #
        # §4.1 KEEPS the target narrowing even though `--to`'s CLI/verb
        # grammar widened: `to == "user"` or `to.startswith("skill:")`
        # is refused BEFORE the registered-project lookup, with the
        # named reason — a scope change is a human decision, never an
        # agent-authored one, so the model is told to say it in
        # `rationale` and let the human type it instead of proposing it.
        if to == "user" or to.startswith("skill:"):
            return _refuse(
                "a scope change is a human verb — say it in `rationale` "
                "and let the human type it"
            )
        target = _registered_project_for(home, to)
        if target is None:
            return _refuse(
                f"to {to!r} is not a registered project — the human can "
                "register it first (the Register control / `self-learn "
                "host add <path>`); tell them, never propose an "
                "unregistered target"
            )
        if slug_for(target) == location.bucket_name:
            return _refuse(
                f"{record_id} already lives in the {target.name} project "
                "— nothing to move"
            )
        resolved_to = str(target)

    until = args.get("until")
    if until is not None:
        if verb != "defer":
            return _refuse("until only applies to defer proposals")
        if not isinstance(until, str) or not _ISO_DATE_RE.match(until):
            return _refuse(f"until {until!r} is not an ISO date (YYYY-MM-DD)")
        try:
            date.fromisoformat(until)
        except ValueError:
            return _refuse(f"until {until!r} is not a real calendar date")

    note = args.get("note")
    if note is not None:
        if not isinstance(note, str):
            return _refuse("note must be a string")
        if len(note) > NOTE_MAX_CHARS:
            return _refuse(
                f"note is {len(note)} characters — the cap is {NOTE_MAX_CHARS}. "
                "Shorten it; it is shown to the human verbatim and executed "
                "byte-identically."
            )

    return VerbProposal(
        verb=verb,
        record_id=record_id,
        bucket_scope=location.scope,
        bucket_name=location.bucket_name,
        session_key=scope.session_key,
        title=record_title(record),
        dest=dest,
        note=note,
        until=until,
        to=resolved_to,
    )


def make_propose_handler(
    *,
    home: Path,
    scope: SessionScope,
    slot: ProposalSlot,
    publish: Callable[[dict], Awaitable[None]],
) -> Callable[[dict[str, Any]], Awaitable[str]]:
    """Bind ONE session's ``propose_verb`` handler. The engine exposes it
    as the in-process MCP tool; every call lands here, in server code.

    Returns the string handed back to the agent — either
    :data:`TOOL_ACCEPTED_MESSAGE` or a refusal."""

    async def handle(args: dict[str, Any]) -> str:
        result = validate_proposal(home, scope, args)
        if isinstance(result, str):
            return result
        if not slot.occupy(result):
            return _refuse(
                "a proposal is already awaiting the human — it must be "
                "confirmed or dismissed before another can render"
            )
        # 10 §1 SSE row: scope-gated client-side; the envelope carries the
        # record id AND its bucket so a Bucket page can match without a
        # record->bucket lookup of its own. Content never rides the
        # envelope — the bar region re-fetches server-rendered.
        await publish(
            {
                "type": "pane_proposal",
                "record_id": result.record_id,
                "bucket": result.bucket_name,
            }
        )
        return TOOL_ACCEPTED_MESSAGE

    return handle
