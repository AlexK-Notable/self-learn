"""``self-learn batch`` — apply a decision sheet in one locked run
(U-verbs §3.3/§4.4). The review skill's apply path; no review session
ever hand-writes another bash script (S-54).

Public surface:

    load_sheet(path, *, home=None) -> Sheet  # BAT1: validated WHOLE, or raises
    classify(home, item, *, actor="human", hook_activation=False) -> bool
        # True iff already-applied (§3.3b); the two keyword-only params
        # matter only for a route item resolving to `hook` (fold r1, F4)
    run(home, items, *, no_push=False, actor="human",
        hook_activation=False) -> BatchResult
    dry_run(home, items, *, actor="human",
            hook_activation=False) -> DryRunResult
    write_receipt(home, result, sheet_name, *, no_push=False) -> dict | None

``run`` holds the sentinel ONCE (the owning hold), dispatches each item to
the SAME ``verbs.*`` function the CLI dispatches to (``no_push=True``,
inside that verb's own ``_ledger_write`` span), classifies
already-applied items as a STATE READ and skips them without calling the
verb, stops on the first ledger-level failure (5/6/7), flushes exactly
once through ``cli._mutating_epilogue`` (§3.3c — the ONE remaining call
site), and pushes once at the end. ``actor``/``hook_activation`` (O-2b,
13 §7.4) are set by the overseer's own runner call, never by sheet text
or a CLI flag — see :func:`_dispatch`'s own docstring for exactly what
each does. ``write_receipt`` (O-2b) is the case-receipt extraction: the
block ``cli._cmd_batch`` used to build inline, now a plain function any
caller (the CLI, or O-3's own runner) can call after ``run`` returns.
"""

from __future__ import annotations

import hashlib
import sys
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import cases, execution_evidence, gitops, intents, sentinel, verbs
from .cases import CASE_ID_RE
from .compilers import CompileError
from .ledger_ops import (
    DEFERRED_ONLY,
    LIVE_STATUSES,
    REOPENABLE_STATUSES,
    RESOLVABLE_STATUSES,
    ROUTED_ONLY,
    LedgerOpsError,
    ProposalError,
    RecordNotFound,
    SheetLineRefusal,
    StatusRefusal,
    find_record_path,
)
from .records import (
    RECORD_ID_RE,
    MutationError,
    Record,
    RecordError,
    ValidationError as RecordValidationError,
    build_covered_by,
    is_replacement,
)

__all__ = [
    "PERMITTED_KEYS",
    "PERMITTED_VERBS",
    "REFUSAL_KINDS",
    "REFUSED_HOOK_DESTINATION",
    "BatchError",
    "BatchContinuation",
    "BookkeepingHalt",
    "BatchResult",
    "DryRunItem",
    "DryRunResult",
    "ItemResult",
    "Sheet",
    "SheetItem",
    "UnreadableRecord",
    "classify",
    "decision_code",
    "dry_run",
    "load_sheet",
    "refusal_kind",
    "run",
    "write_receipt",
]

#: U-verbs §4.4 — the 16 permitted verbs (15 Phase-1 plus U4's `revise`)
#: and the item keys each accepts beyond ``id``/``verb``. Phase 2 is NOT
#: in this build (PH1: a Phase-1 module names no Phase-2 symbol) — a
#: sheet naming a Phase-2 verb is refused the same as any other unknown
#: verb, exit 64.
#:
#: U3 (S-54 as amended / 02-schema.md §3a.1 rule 5): ``by`` is added to
#: every STATUS-changing (resolution) verb's set -- ``route`` already
#: had it, ``revise`` (U4) already carries it -- widened here to
#: ``reject``/``defer``/``undefer``/``reopen``/``graduate``/
#: ``supersede``/``rehome``/``rescope``. The six ANNOTATION verbs
#: (``note``, ``confirm-recurrence``, ``dismiss-suspect``,
#: ``confirm-held``, ``link-contradicts``, ``followup-done``) never
#: change a record's status and stay as they were -- 02-schema.md's
#: ``by`` line (§1) is about who RESOLVED a record, not who annotated
#: one. Fold r1 (F3): the other eight verbs (`verbs.reject` et al.)
#: now DO take a ``by`` parameter too and validate it against the same
#: ``verbs.ROUTING_BY_VALUES`` closed set `route`/`revise` already
#: enforce (`load_sheet` validates every item's `by` up front, so a
#: bad value is refused before item 1 like any other malformed key,
#: not at dispatch) -- but `Record.set_routing` (records.py:479-487)
#: still REQUIRES ``{routed_at, destination, by}`` together and is
#: read as "this record was ROUTED" by ~15 call sites across
#: compilers.py/selfcheck.py/report.py/reachability.py/verbs.py/
#: batch.py itself, so repurposing it for a reject/defer's bare ``by``
#: would misreport every one of those. Its durable home is the commit
#: body instead: each of the eight now writes ``By: <actor>`` as its
#: own final paragraph of the ledger commit (git trailer semantics) --
#: not `Record.set_routing`, and not `resolve_record`'s `note` (a
#: schema change S-54 did not authorize; gate-u3-r1.md F3(c)).
PERMITTED_KEYS: dict[str, frozenset[str]] = {
    "route": frozenset(
        {
            "dest", "collapse", "by", "follow_up", "unblocks_on",
            "follow_up_note", "allow_empty_glob", "note",
        }
    ),
    "reject": frozenset({"note", "by"}),
    "defer": frozenset({"until", "note", "by"}),
    "undefer": frozenset({"note", "by"}),
    "reopen": frozenset({"note", "by"}),
    # S-67: `retire`'s own key set requires `covered_by` (REQUIRED_KEYS,
    # below — refused before item 1 runs, like `supersede`'s `new_id`).
    # `graduate` stays the alias's key set, `covered_by` now OPTIONAL —
    # a pre-rename sheet (no `covered_by` at all) still applies.
    "retire": frozenset({"covered_by", "note", "by"}),
    "graduate": frozenset({"covered_by", "note", "by"}),
    "supersede": frozenset({"new_id", "note", "by"}),
    "rehome": frozenset({"to", "note", "by"}),
    "rescope": frozenset({"to", "note", "by"}),
    "note": frozenset({"append", "key"}),
    "confirm-recurrence": frozenset({"event", "tolerate", "note"}),
    "dismiss-suspect": frozenset({"event", "why", "note"}),
    "confirm-held": frozenset({"note"}),
    "link-contradicts": frozenset({"target", "note"}),
    "followup-done": frozenset({"note"}),
    # U4 (revise) -- S-54 as amended, 2026-09-13: "the one verb this
    # build adds to the sheet grammar, and PERMITTED_KEYS gains it
    # together with the by: key" (03-decisions.md S-54). Dispatch
    # wiring (`_dispatch`/`classify`/`_STATUS_GATE`) is U3's own
    # (lane so-batch, this build).
    "revise": frozenset({"section", "text", "because", "by"}),
}
PERMITTED_VERBS = frozenset(PERMITTED_KEYS)
#: Verbs that are only a second spelling of another verb (S-67:
#: `graduate` is `retire`'s pre-rename alias). Still accepted on a sheet;
#: named here, in the module that owns the alias, so a reader that lists
#: the verbs for a model (`steward_prompt._sheet_verb_lines`) can leave
#: the second spelling out without spelling it itself.
SHEET_VERB_ALIASES = frozenset({"graduate"})

#: The subset of each verb's permitted keys that must actually be PRESENT
#: on a sheet item -- caught at BAT1's whole-sheet validation, same as an
#: unknown key or a malformed id (nothing runs). Every other permitted
#: key is optional (defer's ``until`` falls back to the default +30
#: days; ``route``'s ``dest`` falls back to the proposal sibling; etc).
#: ``route``'s ``dest`` is deliberately NOT required (code gate r2,
#: MAJ-r2-1): §4.4's own example sheet carries a dest-less
#: ``{verb: route, collapse: merge-...}`` line, and §4.4's permitted-key
#: rule is "exactly the keys that verb's CLI accepts" -- the CLI's
#: ``--dest`` is optional. `classify`'s own ``if f.get("dest") is None:
#: return False`` (below) already closes the N7 gap this once tried to
#: close by requiring the key: a dest-less route item against an
#: ALREADY-routed record is never silently marked already-applied --
#: it reaches the verb at dispatch and refuses there, naming the actual
#: status.
REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "retire": frozenset({"covered_by"}),
    "supersede": frozenset({"new_id"}),
    "rehome": frozenset({"to"}),
    "rescope": frozenset({"to"}),
    "note": frozenset({"append"}),
    "confirm-recurrence": frozenset({"event"}),
    "dismiss-suspect": frozenset({"event", "why"}),
    "link-contradicts": frozenset({"target"}),
    # U4 (revise): `because` is required unlike every other verb's
    # optional `note` -- it plays `note`'s exact role (commit body) for
    # this verb and has no optional counterpart, so it is never absent.
    "revise": frozenset({"section", "text", "because"}),
}

#: S-29 / Y-17: never accepted inside a sheet, by name — a hook route
#: replays examples and writes an executable, and host registration is a
#: disclosed-consent event; neither rides a bulk apply.
REFUSED_VERBS_LITERAL = frozenset(
    {
        "teach", "import", "mine", "worker", "push", "sentinel",
        "recompile", "init", "proposal validate",
    }
)
REFUSED_HOOK_DESTINATION = "hook"


def _hook_refused_detail(record_id: str) -> str:
    """Fold r1 (F8): the ONE S-29 refusal sentence both `_dispatch`
    (the real run) and `dry_run` (the preview) show for a hook route at
    any non-overseer actor — a single definition so the two copies can
    never drift (gate-o2b-r1.md F8 measured them byte-identical today
    but only one of the two carried a test pinning its text)."""
    return (
        f"{record_id}: a hook route is refused inside a batch (S-29) — "
        "route it by hand"
    )


#: S-71 (`03-decisions.md`; the table is `02-schema.md` §3a): the closed set
#: of refusal KINDS. Every failed item carries exactly one, decided by
#: :func:`refusal_kind` from the exception type at the raise site — never by
#: reading the refusal's text.
REFUSAL_KINDS = frozenset(
    {
        "git", "target-busy", "status", "destination-unavailable",
        "needs-person", "bad-line", "secret-record", "unclassified",
    }
)

#: The same kinds, most severe first — the steward's action precedence
#: (S-71). Used where ONE item carries several refusals at once (a route
#: preview reports every failed preflight, not only the first) and still
#: needs a single kind.
_KIND_PRECEDENCE = (
    "secret-record", "git", "target-busy", "needs-person", "unclassified",
    "bad-line", "destination-unavailable", "status",
)


def _typed_kind(exc: BaseException) -> str | None:
    """The kind ONE exception's own type names, or ``None`` when its type
    names none. Most specific first."""
    if isinstance(exc, verbs.SecretRefusal):
        # S-68: a hit in the record itself is refused and never parked; a
        # hit only in the line's own text is the line's mistake.
        return "secret-record" if exc.where == "record" else "bad-line"
    if isinstance(exc, verbs.DirtyTargetError):
        return "needs-person" if exc.cause == "region" else "target-busy"
    if isinstance(exc, gitops.GitOpsError):  # HalfWrittenError, LedgerStoppedError
        return "git"
    if isinstance(exc, verbs.NeedsPerson):
        return "needs-person"
    if isinstance(exc, verbs.DestinationUnavailable):
        return "destination-unavailable"
    if isinstance(exc, (verbs.SheetLineError, SheetLineRefusal)):
        return "bad-line"
    if isinstance(exc, ProposalError):
        return "needs-person"
    if isinstance(exc, (StatusRefusal, RecordNotFound)):
        return "status"
    return None


def refusal_kind(exc: BaseException | None, *, rc: int, state: str) -> str:
    """S-71: the ONE place a refusal is given its kind (the table lives here
    and nowhere else). A ``stopped`` item, or any ledger stop code
    (5/6/7), is ``git``. Otherwise the exception is read by TYPE: the
    exception itself first, then the exception it was raised from
    (``raise … from exc``), and so on — because most verbs re-raise the
    ledger's typed refusal as a plain :class:`verbs.VerbError` for the CLI's
    exit code, and the type that says what happened is the one underneath.
    A raise site no type names is ``unclassified``: that parks, it is never
    silent."""
    if state == "stopped" or rc in _STOP_CODES:
        return "git"
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        kind = _typed_kind(current)
        if kind is not None:
            return kind
        current = current.__cause__
    return "unclassified"


def _most_severe_kind(kinds) -> str:
    """One kind for an item that carries several (see
    :data:`_KIND_PRECEDENCE`)."""
    present = set(kinds)
    for kind in _KIND_PRECEDENCE:
        if kind in present:
            return kind
    return "unclassified"


def _preview_kind(errors) -> str:
    """The kind a ``would-refuse`` preview item carries: each refusal the
    preview found is classified exactly as the real run would classify it
    (a refused item, not a stop), and the most severe wins."""
    return _most_severe_kind(
        refusal_kind(exc, rc=1, state="refused") for exc in errors
    )


class BatchError(Exception):
    """Whole-sheet validation failure (BAT1) — exit 64, nothing runs."""


@dataclass(frozen=True)
class SheetItem:
    n: int
    id: str
    verb: str
    fields: dict


class Sheet(list):
    """``list[SheetItem]`` carrying the sheet's own top-level ``case:``
    key (S-54 as amended, 02-schema.md §3a.1 rule 5, U3) as ``.case`` --
    what :func:`load_sheet` returns in place of a bare list, so every
    existing ``for item in items`` / ``run(home, items, ...)`` /
    ``dry_run(home, items)`` caller needs NO change (``Sheet`` IS a
    ``list``, so ``batch.run(env2.home, items, no_push=True)`` — the
    shape U4's own carried test (`test_revise_then_route_sheet_applies_
    both`) already uses — keeps working unchanged). :func:`run` and
    :func:`dry_run` read ``getattr(items, "case", None)`` to populate
    their own result's ``case`` field without a new required
    parameter -- a caller that hands either function a plain
    ``list[SheetItem]`` (as every existing test still may) simply gets
    ``case=None``, exactly today's behaviour.

    Fold r1 (F1, N4): also carries ``.sheet_sha`` -- a short sha256 of
    the sheet's own raw bytes, computed once by :func:`load_sheet` --
    the identity `cases.receipt` keys a receipt line on (F1's ruling:
    "a receipt line's key is (sheet sha256 short, item index)", never
    the sheet's bare filename, which two differently-named-but-same-
    named sheets against one case could collide on). Kept as a second
    attribute on the same ``list`` subclass rather than a new required
    parameter, for the identical reason ``.case`` is: every existing
    plain-``list[SheetItem]`` caller gets ``sheet_sha=None`` and is
    unaffected. N4 (named, not fixed): a caller that turns a ``Sheet``
    into a plain ``list`` (``list(sheet)``, a slice, a comprehension)
    silently loses both attributes -- today's only caller is
    `cli._cmd_batch`, which never does that (grepped across `cli/src`,
    `ui/src`, `scripts`)."""

    def __init__(
        self,
        iterable=(),
        *,
        case: str | None = None,
        sheet_sha: str | None = None,
        sheet_digest: str | None = None,
    ) -> None:
        super().__init__(iterable)
        self.case = case
        self.sheet_sha = sheet_sha
        self.sheet_digest = sheet_digest


@dataclass
class ItemResult:
    n: int
    id: str
    verb: str
    rc: int
    sha: str | None = None
    #: U3: ``not-attempted`` joins the set -- one sheet item, after a
    #: mid-sheet STOP, that `run` never dispatched at all (02-schema.md
    #: §3a.1 rule 5 / §3a.2 §5's own tail format;
    #: `commands/review.md` "a sheet item after a stop point is
    #: reported with `state: not-attempted` rather than being silently
    #: dropped from the output"). Fold r1 (F9): ``stopped`` also joins
    #: the set -- 02-schema.md §3a.2 §5 names a receipt state the
    #: executor never emitted ("applied | already-applied | refused |
    #: stopped"); `run` now sets it on the ONE item whose rc actually
    #: triggered the mid-sheet STOP (rc in 5/6/7), in place of the
    #: generic ``refused`` `_dispatch` gives every non-stopping refusal
    #: -- the receipt line for that item now reads ``stopped (exit N)``
    #: instead of being indistinguishable from an ordinary refusal.
    state: str = "applied"  # applied | already-applied | unresolved-host | refused | stopped | not-attempted
    detail: str | None = None
    #: S-67 fold r1: verb warnings survive the sheet adapter just as
    #: commit/detail facts do. Additive and empty for every existing item.
    warnings: list[str] = field(default_factory=list)
    #: Trusted provenance for an established outcome whose source matters
    #: on recovery (for example, a host result established by recompile).
    evidence: str | None = None
    #: S-71: the refusal's kind (:data:`REFUSAL_KINDS`, from
    #: :func:`refusal_kind`), set only when the item failed; ``None`` for an
    #: applied, already-applied or not-attempted item.
    kind: str | None = None


@dataclass(frozen=True)
class BatchContinuation:
    """Trusted committed prefix for one immutable case/sheet pair.

    A completed item with ``evidence is None`` came from an existing
    committed Application line. A completed item carrying ``evidence`` was
    reconstructed from mutation/host proof and is checkpointed before the
    next item. ``state="unresolved-host"`` instead names a ledger-proven host
    obligation in ``detail``; it is receipted and halts the dependent tail.
    """

    run_id: str
    case_id: str
    sheet_digest: str
    completed: Mapping[int, ItemResult]


class BookkeepingHalt(Exception):
    """An opted-in durability checkpoint failed after an item outcome."""

    def __init__(
        self,
        message: str,
        result: "BatchResult",
        untouched_tail: list[SheetItem],
    ) -> None:
        super().__init__(message)
        self.result = result
        self.untouched_tail = untouched_tail


@dataclass
class BatchResult:
    items: list[ItemResult] = field(default_factory=list)
    stopped_at: int | None = None
    flush_sha: str | None = None
    pushed: bool = False
    process_code: int = 0
    #: U3 (S-54 as amended, S-65): the sheet's own top-level ``case:``
    #: key, threaded through from :class:`Sheet` unchanged -- ``None``
    #: for a sheet that names no case (old sheets parse and run exactly
    #: as before) or when *items* is a plain ``list[SheetItem]`` rather
    #: than a :class:`Sheet`. `cli._cmd_batch` reads this to decide
    #: whether to call `cases.receipt` after this run's own locked
    #: section has closed.
    case: str | None = None
    #: Fold r1 (F1, N4): the sheet's own ``.sheet_sha``, threaded
    #: through from :class:`Sheet` the same way ``case`` is -- ``None``
    #: for a plain ``list[SheetItem]`` caller. `cli._cmd_batch` reads
    #: this to key the receipt call's identity (F1).
    sheet_sha: str | None = None
    #: S-62 (§7.2a.5(3)): the sheet-level preflight's own recovery
    #: outcome — "a batch item's outcome rides the --json envelope"
    #: means the WHOLE run's, here, since this recovery runs before
    #: any item, not per-item.
    recovered_rolled_forward: list[str] = field(default_factory=list)
    recovered_restored: list[str] = field(default_factory=list)
    #: §7.2a.5(5): the STOP refusal's own message, when the sheet-level
    #: preflight refuses the whole sheet before any item runs — a batch
    #: that returns 6 must still say WHICH intent and why, the same as
    #: every other surface's refusal; `process_code == 6` with this
    #: `None` never happens together.
    stop_message: str | None = None
    #: Fold r1 (F2): who ran this sheet -- always present (`"human"` by
    #: default, since every pre-O-2b caller, the CLI included, passes
    #: no `actor`), threaded straight from `run`'s own validated
    #: `actor=` parameter. The ONE ledger surface that already knew
    #: this (the `By: <actor>` commit trailer, on the eight
    #: commit-trailer verbs only) still exists unchanged; this is the
    #: field a `--json`/receipt READER can consult without parsing a
    #: git log.
    actor: str = "human"
    #: Internal receipt-owner state. These original ordinals already have
    #: committed Application lines and are omitted from later prefix writes.
    #: It is intentionally absent from ``to_json`` and every CLI envelope.
    preserved_receipt_items: set[int] = field(default_factory=set, repr=False)

    @property
    def summary(self) -> dict:
        applied = sum(1 for i in self.items if i.state == "applied")
        already = sum(1 for i in self.items if i.state == "already-applied")
        refused = sum(1 for i in self.items if i.state == "refused")
        # Fold r1 (F9): counted separately from `refused` for the same
        # reason `not_attempted` already is -- the one item whose rc
        # actually stopped the sheet is a distinct fact from an
        # ordinary per-verb refusal.
        stopped = sum(1 for i in self.items if i.state == "stopped")
        # U3: counted separately so `applied + already_applied + refused
        # + stopped + not_attempted == total` always holds -- folding
        # these into `refused` would misreport an item `run` never even
        # dispatched (or the one that stopped it) as an ordinary
        # per-verb refusal.
        not_attempted = sum(1 for i in self.items if i.state == "not-attempted")
        return {
            "applied": applied,
            "already_applied": already,
            "refused": refused,
            "stopped": stopped,
            "not_attempted": not_attempted,
            "total": len(self.items),
        }

    def to_json(self) -> dict:
        return {
            "summary": self.summary,
            "items": [
                {
                    "n": i.n, "id": i.id, "verb": i.verb, "rc": i.rc,
                    "sha": i.sha, "state": i.state, "detail": i.detail,
                    "warnings": list(i.warnings),
                    **({"evidence": i.evidence} if i.evidence is not None else {}),
                    **({"kind": i.kind} if i.kind is not None else {}),
                }
                for i in self.items
            ],
            "stopped_at": self.stopped_at,
            "case": self.case,
            "sheet_sha": self.sheet_sha,
            "pushed": self.pushed,
            "process_code": self.process_code,
            "recovered_rolled_forward": self.recovered_rolled_forward,
            "recovered_restored": self.recovered_restored,
            "stop_message": self.stop_message,
            "actor": self.actor,
        }


#: The sheet's own known top-level keys (U3, S-54 as amended): ``case``
#: joins ``version``/``items``. Anything else -- ``actor:`` included --
#: is refused before item 1, the same as an unknown ITEM key
#: (02-schema.md §3a.1: "An unknown top-level key — including a
#: hand-written `actor:` — is refused before item 1 runs, the same way
#: an unknown item key is refused today"). NOTE: the plan draft this
#: build was cut from (`plan-steward-2026-09-12.md:399`) says the
#: opposite -- "unknown top-level keys stay ignored so older sheets
#: still parse" -- but the spec is later and wins (common-builder-
#: rules.md); see this build's report for both quotes side by side.
#: Older sheets (no `case:`, no other extra key) parse unchanged either
#: way -- this refusal only ever fires on a NEW unknown key.
_KNOWN_TOP_LEVEL_KEYS = frozenset({"version", "items", "case"})


def load_sheet(path: Path | str, *, home: Path | str | None = None) -> Sheet:
    """Parse + validate a sheet WHOLE (BAT1): an unknown verb, an unknown
    item key, an unknown TOP-LEVEL key, a malformed id, a malformed
    ``case:`` id, a ``case:`` naming no case that EXISTS (fold r1, F2 --
    only when *home* is given), a ``by:`` value outside
    ``verbs.ROUTING_BY_VALUES`` (fold r1, F3), or ``version != 1``
    raises — nothing runs. Returns a :class:`Sheet` (a
    ``list[SheetItem]`` subclass carrying the sheet's own ``case`` and
    ``sheet_sha`` as attributes) -- every existing ``list[SheetItem]``
    caller is unaffected (see :class:`Sheet`'s own docstring).

    *home* is optional and keyword-only (fold r1): every pre-existing
    caller (every test file, plus this module's own carried tests) calls
    ``load_sheet(path)`` and gets exactly today's behaviour -- the
    case-EXISTENCE check below only runs when a caller can name a home
    to check it against. `cli._cmd_batch` is the one caller that does
    (F2's ruling: "a case id that does not exist is refused at
    load_sheet time, before item 1 (usage, 64), so it can never fail
    after a commit" -- the receipt call can then assume the case it was
    given exists)."""
    path = Path(path)
    yaml = YAML(typ="safe")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BatchError(f"batch: cannot read {path}: {exc}") from exc
    # Fold r1 (F1, N4): a short content-addressed identity for this
    # sheet -- the key `cases.receipt` dedupes a receipt line on, never
    # the bare filename (two differently-run sheets sharing a basename
    # would otherwise collide, and a re-run of the SAME sheet must key
    # identically even if the CLI's `args.sheet` path differs, e.g. a
    # relative vs. absolute invocation).
    sheet_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    sheet_sha = sheet_digest[:8]
    try:
        data = yaml.load(text)
    except Exception as exc:  # noqa: BLE001 — any YAML parse failure is a sheet error
        raise BatchError(f"batch {path}: unreadable YAML — {exc}") from exc
    if not isinstance(data, dict):
        raise BatchError(f"batch {path}: sheet must be a mapping")
    unknown_top = set(data) - _KNOWN_TOP_LEVEL_KEYS
    if unknown_top:
        raise BatchError(
            f"batch {path}: unknown top-level key(s): {sorted(unknown_top)}"
        )
    if data.get("version") != 1:
        raise BatchError(
            f"batch {path}: version must be 1, got {data.get('version')!r}"
        )
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise BatchError(f"batch {path}: items must be a non-empty list")
    case = data.get("case")
    if case is not None and (not isinstance(case, str) or not CASE_ID_RE.match(case)):
        raise BatchError(f"batch {path}: malformed case id: {case!r}")
    if case is not None and home is not None:
        try:
            cases._case_path_for_id(Path(home), case)
        except cases.CaseError as exc:
            raise BatchError(f"batch {path}: {exc}") from exc

    items: list[SheetItem] = []
    for n, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise BatchError(f"batch {path}: item {n} must be a mapping")
        rid = raw.get("id")
        if not isinstance(rid, str) or not RECORD_ID_RE.match(rid):
            raise BatchError(f"batch {path}: item {n} has a malformed id: {rid!r}")
        verb = raw.get("verb")
        if not isinstance(verb, str) or (
            verb in REFUSED_VERBS_LITERAL or verb.startswith("host ")
        ):
            raise BatchError(
                f"batch {path}: item {n} verb {verb!r} is refused inside a "
                "sheet — not a record resolution, or disclosed-consent "
                "registration (S-29/Y-17); sequence it by hand"
            )
        if verb not in PERMITTED_VERBS:
            raise BatchError(
                f"batch {path}: item {n} has an unknown/unpermitted verb: {verb!r}"
            )
        allowed_keys = PERMITTED_KEYS[verb] | {"id", "verb"}
        unknown = set(raw) - allowed_keys
        if unknown:
            raise BatchError(
                f"batch {path}: item {n} ({verb}) has unknown key(s): "
                f"{sorted(unknown)}"
            )
        missing = {
            k for k in REQUIRED_KEYS.get(verb, frozenset())
            if raw.get(k) in (None, "")
        }
        if missing:
            raise BatchError(
                f"batch {path}: item {n} ({verb}) is missing required "
                f"key(s): {sorted(missing)}"
            )
        # Fold r1 (F3): `by`, where permitted, is validated against the
        # SAME closed set `route`/`revise` already enforce at dispatch --
        # a sheet naming `by: bogus` on ANY resolution verb is refused
        # BEFORE item 1, exactly like a malformed id or an unknown key,
        # never silently accepted and dropped at dispatch (gate-u3-r1.md
        # F3's own measurement: "reject by=bogus rc = 0 (applied; the
        # value is discarded)" -- closed here).
        by_val = raw.get("by")
        if by_val is not None and by_val not in verbs.ROUTING_BY_VALUES:
            raise BatchError(
                f"batch {path}: item {n} ({verb}) has by={by_val!r}, must "
                f"be one of {sorted(verbs.ROUTING_BY_VALUES)}"
            )
        fields = {k: v for k, v in raw.items() if k not in ("id", "verb")}
        items.append(SheetItem(n=n, id=rid, verb=verb, fields=fields))
    return Sheet(
        items, case=case, sheet_sha=sheet_sha, sheet_digest=sheet_digest
    )


def _resolved_route_dest(home: Path, path: Path, item: SheetItem):
    """The (destination, ref_name) a ``route`` item resolves to — the
    SAME resolver ``route`` itself calls, over the SAME proposal sibling
    when the item names no explicit ``dest`` — used by both the
    hook-destination sheet-level check and the already-applied
    classifier. ``None`` when it cannot be resolved (a missing/invalid
    proposal with no explicit ``dest`` — the item's own business, left
    to redden at dispatch)."""
    bucket_dir = path.parent.parent
    dest = item.fields.get("dest")
    try:
        resolved = verbs._resolve_destination(bucket_dir, item.id, dest)
    except Exception:  # noqa: BLE001 — any resolution failure: unknown here
        return None
    return resolved.destination, resolved.ref_name


def _hook_activation_registered(record: Record) -> bool | None:
    """Fold r1 (F4): what the record's OWN LAST ``hook-activated``
    history entry says about registration -- ``True`` (a full
    activation: registered + activation-checked), ``False`` (F1's
    delegated/placed-only note -- the ONE marker durably distinguishing
    the two on the ledger, since a history entry carries only ``event``/
    ``note``), or ``None`` (no ``hook-activated`` entry at all -- never
    activated, successfully or not, e.g. after F5's undo)."""
    entries = [h for h in (record.history or []) if h.get("event") == "hook-activated"]
    if not entries:
        return None
    note = entries[-1].get("note") or ""
    return "delegated" not in note


class UnreadableRecord(verbs.NeedsPerson):
    """S-71 §8.2: the item's record file exists but does not read back
    as a record. :func:`classify` raises this instead of letting the
    parse error escape :func:`run` / :func:`dry_run` and end the whole
    sheet; both turn it into that item's own refused (would-refuse)
    line, kind ``needs-person``, and the sheet continues. Only a person
    can repair the file."""


#: What a record read raises when the file is not a readable record --
#: the same tuple ``ledger_ops`` uses when it scans record files. Not a
#: catch-all: anything else still escapes.
_UNREADABLE_RECORD_ERRORS = (RecordError, OSError, UnicodeDecodeError, YAMLError)


def classify(
    home: Path, item: SheetItem, *, actor: str = "human",
    hook_activation: bool = False,
) -> bool:
    """True iff *item* is ALREADY-APPLIED (§3.3b) — a STATE READ, never
    a parse of a refusal message. An unresolvable record id is never
    already-applied — it surfaces as the item's own refusal at dispatch.
    A record file that exists but does not read back raises
    :class:`UnreadableRecord` (S-71 §8.2).

    ``actor``/``hook_activation`` (fold r1, F4): read ONLY for a
    ``route`` item resolving to the ``hook`` destination under
    ``actor == "overseer"`` -- every other verb, and every OTHER actor
    (including the default), is byte-unchanged by these two parameters;
    see the ``route`` branch below for what they change."""
    try:
        path = find_record_path(home, item.id)
    except LedgerOpsError:
        return False
    try:
        record = Record.from_path(path)
    except _UNREADABLE_RECORD_ERRORS as exc:
        raise UnreadableRecord(
            f"record file {path} cannot be read as a record — a person must "
            f"repair it by hand: {exc}"
        ) from exc
    verb = item.verb
    f = item.fields

    if verb == "route":
        if record.status != "routed":
            return False
        # `dest` is OPTIONAL on a route sheet item (code gate r2,
        # MAJ-r2-1 -- §4.4's own example sheet carries a dest-less
        # `{verb: route, collapse: merge-...}` line). But already-
        # applied is decided ONLY against a destination the sheet
        # itself named, never a guess: a dest-less item against an
        # ALREADY-routed record gets the SAME treatment §3.3b gives any
        # other unresolvable comparison -- not already-applied, so it
        # reaches the verb at dispatch and refuses there naming the
        # actual state, never a silent skip (code gate r1 N7). A
        # dest-less item against a PENDING record still classifies
        # False here (status != "routed" above) and applies normally,
        # resolving its destination from the proposal sibling exactly
        # as `route` itself would without `--dest`.
        if f.get("dest") is None:
            return False
        resolved = _resolved_route_dest(home, path, item)
        if resolved is None:
            return False
        want_dest, want_ref = resolved
        routing = record.routing or {}
        if routing.get("destination") != want_dest:
            return False
        if want_dest == REFUSED_HOOK_DESTINATION and actor == "overseer":
            # Fold r1 (F4): the route leg landed (status/destination
            # already matched above), but for the OVERSEER's own path
            # "already applied" also means the ACTIVATION leg matches
            # the CURRENT gate -- a failed or never-attempted
            # activation, or one parked under a gate that has since
            # flipped, is NOT already-applied: `_dispatch` re-attempts
            # the activation leg only (the route leg is skipped there,
            # since `verbs.route` itself would refuse a second attempt
            # against an already-routed record).
            registered = _hook_activation_registered(record)
            if registered is None:
                return False
            # Orchestrator residual after the fold (merge fdab290): a
            # FULLY registered hook is complete whatever the CURRENT
            # gate says -- the gate governs whether a re-run may
            # register, never whether a registered hook should be
            # re-placed as "delegated" (that would write a false
            # placed-only note over a live registration on every
            # re-run once the human switches the gate off; the human's
            # rollback is `hook deactivate`, not the gate). A placed-only
            # hook is at the gate's state only while the gate is off.
            return registered or not hook_activation
        if want_dest == "reference" and want_ref is not None:
            return routing.get("reference_file") == want_ref
        return True
    if verb == "reject":
        return record.status == "rejected"
    if verb == "defer":
        if record.status != "deferred":
            return False
        until = f.get("until")
        if until is not None:
            return str(record.deferred_until) == str(until)
        du = record.deferred_until
        if du is None:
            return False
        try:
            return date.fromisoformat(str(du)) >= datetime.now(timezone.utc).date()
        except ValueError:
            return False
    if verb == "undefer":
        return record.status == "pending" and (record.deferred_count or 0) >= 1
    if verb == "reopen":
        if record.status != "pending":
            return False
        return any(h.get("event") == "resolution" for h in record.history)
    if verb == "retire":
        # S-67: `covered_by` is REQUIRED (REQUIRED_KEYS), so `f["covered_by"]`
        # is always present by the time classify reaches here -- already-
        # applied iff the record is superseded by EXACTLY that surface (a
        # second run naming a DIFFERENT surface is not "already applied";
        # it reaches `_dispatch` and `verbs.retire` refuses it there, same
        # precedent as a dest-less `route` against an already-routed
        # record above).
        if record.status != "superseded":
            return False
        try:
            surface = build_covered_by(f["covered_by"])
        except RecordValidationError:
            return False  # malformed sheet value: not this function's refusal
        return record.superseded_by == surface
    if verb == "graduate":
        # S-67: the alias. A sheet item naming `covered_by` is already-
        # applied under the SAME rule `retire` uses; one that omits it
        # (the pre-rename shape) is already-applied iff the record
        # carries the legacy literal.
        if record.status != "superseded":
            return False
        covered_by = f.get("covered_by")
        if covered_by is None:
            return record.superseded_by == "canon"
        try:
            surface = build_covered_by(covered_by)
        except RecordValidationError:
            return False
        return record.superseded_by == surface
    if verb == "supersede":
        return (
            record.status == "superseded"
            and record.superseded_by == f["new_id"]
        )
    if verb in ("rehome", "rescope"):
        to = f["to"]
        try:
            _target_scope, target_bucket, _project_path = verbs._resolve_move_target(
                home, to
            )
        except verbs.VerbError:
            return False
        return path.parent.parent == target_bucket
    if verb == "note":
        key = f.get("key")
        if key is None:
            # a human `note` has no key — never derivable from state
            # (§3.3b row 10: the one verb whose effect is not derivable
            # from record state), so it is NEVER already-applied.
            return False
        return record.note_has_key(key)
    if verb == "confirm-recurrence":
        event = f["event"]
        return any(r.get("ref") == event for r in record.recurrences)
    if verb == "dismiss-suspect":
        event = f["event"]
        return any(d.get("ref") == event for d in record.dismissed_suspects)
    if verb == "confirm-held":
        return record.last_confirmed is not None
    if verb == "link-contradicts":
        target = f["target"]
        return target in record.contradicts
    if verb == "followup-done":
        return record.follow_up is None and record.follow_up_done is not None
    if verb == "revise":
        # U3 (carried from the U4 gate, gate-u4-r1.md F5): `revise` was
        # added to PERMITTED_VERBS by U4 without a `classify` branch, so
        # this line WAS reachable for a `revise` item until now. Status
        # first: `verbs.revise` admits only LIVE_STATUSES (pending/
        # deferred; `records.DRAFT_STATUSES` — the same two values under
        # a different module's name), so a revise item against anything
        # else is never "already applied" here -- it reaches `_dispatch`
        # and refuses there, naming the real status, same precedent as
        # `rehome`/`rescope` above. Otherwise: already-applied iff the
        # named section's text already matches -- the SAME
        # `new_body == record.body` comparison `verbs.revise` itself
        # uses to refuse "nothing to revise" (verbs.py:8093-8097) — so a
        # second run of an already-applied revise sheet classifies
        # already-applied (S-54's idempotence guarantee) instead of
        # reaching `verbs.revise` and getting THAT refusal instead.
        if record.status not in LIVE_STATUSES:
            return False
        try:
            new_body = verbs._revise_body(record, f["section"], f["text"])
        except verbs.VerbError:
            return False
        return new_body == record.body
    return False  # pragma: no cover — unreachable: every PERMITTED_VERBS
    # member has its own branch above (revise included, U3) — load_sheet
    # already gated the verb set to PERMITTED_VERBS, so no OTHER value
    # can reach this function at all.


def _classify_or_refuse(
    home: Path, item: SheetItem, *, actor: str, hook_activation: bool
) -> tuple[bool, ItemResult | None]:
    """:func:`classify`, or -- when the item's record file does not read
    back (S-71 §8.2) -- ``(False, <that item's refused result>)``, so the
    caller receipts it and moves on to the next item."""
    try:
        applied = classify(home, item, actor=actor, hook_activation=hook_activation)
    except UnreadableRecord as exc:
        return False, ItemResult(
            n=item.n, id=item.id, verb=item.verb, rc=exc.exit_code,
            state="refused", detail=str(exc),
            kind=refusal_kind(exc, rc=exc.exit_code, state="refused"),
        )
    return applied, None


#: U5 fold r1 (F1): the ONLY verbs `_dispatch` ever forwards
#: `reconsider_case` to — one set, consulted by BOTH
#: `_reconsider_case_for` (below) and `dry_run`'s own status-gate
#: preview, so the two can never drift apart again. Before this fix
#: `_reconsider_case_for` decided purely on the RECORD's status, never
#: the VERB — `dry_run` previewed `would-apply` for `revise`/`rescope`/
#: `rehome` against a routed record under a valid reconsider case even
#: though `_dispatch` never forwards `reconsider_case` to any of the
#: three (they gained no such parameter) and the real run refused.
_RECONSIDER_FORWARDING_VERBS = frozenset(
    {"reject", "defer", "retire", "graduate", "supersede"}
)


def _reconsider_case_for(
    home: Path, record_id: str, case: str | None, verb: str
) -> str | None:
    """U5: forward the sheet's own top-level ``case:`` into a resolution
    verb's ``reconsider_case`` ONLY when it could genuinely apply —
    *verb* is one of :data:`_RECONSIDER_FORWARDING_VERBS` (fold r1,
    F1) AND the record's CURRENT status (read fresh, before dispatch)
    is ``routed`` AND *case* actually validates as a ``kind:
    reconsider`` case over THIS record (:func:`cases.
    require_reconsider_case`, pre-checked here, read-only). A record
    not currently ``routed`` never needs the widening at all:
    `reject`/`defer`'s own unwidened gate already admits
    `pending`/`deferred` on its own, and `graduate`/`supersede`'s
    admits `routed` UNCONDITIONALLY regardless of any case — ``None``
    changes nothing about what any of the four verbs do next in either
    case. A verb outside the forwarding set (`revise`/`rescope`/
    `rehome`/…) never gained a `reconsider_case` parameter at all —
    forwarding one to `_dispatch`'s own branch for it would be a
    ``TypeError``, not a refusal, so this returns ``None`` before ever
    reading the record.

    This is a STRICTER pre-check than a literal "pass `case` through
    unconditionally" would be, and deliberately so: a sheet's top-level
    ``case:`` threads receipts to that case's Application section
    (S-65) independent of its ``kind`` — an ordinary ``kind:
    resolution`` case (U3's own shape, and the everyday hand-weave
    graduate/supersede of an already-routed record) would otherwise
    trip a resolution verb's reconsider-only refusal for a record the
    case was never about, for reasons that have nothing to do with U5.
    A genuinely WRONG reconsider case over a routed record still
    refuses either way: `reject`/`defer` fall back to their ordinary
    unwidened "record ... is 'routed'" refusal (the verb never learns a
    case was even in play) rather than the more specific "wrong kind /
    wrong record" wording `_reconsider_case_check` would have produced
    — reported here, not silently matched, since `build-u5.md` does not
    test this edge and this repo has no sheet combining a non-reconsider
    case with an already-routed record's item either way."""
    if verb not in _RECONSIDER_FORWARDING_VERBS:
        return None
    if case is None:
        return None
    try:
        record = Record.from_path(find_record_path(home, record_id))
    except (LedgerOpsError, RecordError, OSError):
        return None
    if record.status != "routed":
        return None
    try:
        cases.require_reconsider_case(home, case, record_id)
    except cases.CaseError:
        return None
    return case


def _dispatch_hook_activation(
    home: Path,
    item: SheetItem,
    *,
    actor: str,
    hook_activation: bool,
    route_result: "verbs.VerbResult | None",
) -> "ItemResult":
    """Fold r1 (F4, F5, F9): the activation leg of an overseer hook
    route, factored out of :func:`_dispatch` (pyright's own complexity
    limit flagged `_dispatch` once this logic was inlined there too).

    *route_result* is the FRESH route's own :class:`verbs.VerbResult`
    when this call just landed a NEW route commit, or ``None`` when the
    record was ALREADY routed to ``hook`` and only the activation leg
    is being re-attempted (F4 — `verbs.route` itself would refuse a
    second attempt against an already-routed record, so `_dispatch`'s
    route branch never calls it in that shape).

    Any exception from the activation call — not only
    :class:`verbs.VerbError` — refuses THIS item rather than escaping
    :func:`run` (F5); the runtime undo, if any, has already run inside
    :func:`hook_activation.activate` itself by the time this catches
    it. On success, F9: both commits' worth of post-notes ride the ONE
    item result when *route_result* is given — route's own (the
    exact-bytes preview and manual-steps text a human reviewing this
    route sees today) alongside hook_activate's; route's own commit sha
    rides `detail` since :class:`ItemResult` has only one `sha` slot
    and hook_activate's is the more RECENT of the two commits."""
    verb = item.verb
    f = item.fields
    try:
        hook_result = verbs.hook_activate(
            home, item.id, register=hook_activation, no_push=True,
            by=(f.get("by") or actor),
        )
    except Exception as exc:  # noqa: BLE001 — F5: nothing escapes `run`
        if route_result is None:
            detail = (
                f"{item.id}: already routed; the activation re-attempt "
                f"failed — {exc}"
            )
        else:
            detail = (
                f"{item.id}: routed (commit {route_result.commit_sha}) "
                f"but activation failed — {exc}"
            )
        return ItemResult(
            n=item.n, id=item.id, verb=verb, rc=1, state="refused",
            sha=route_result.commit_sha if route_result is not None else None,
            detail=detail,
            warnings=(list(route_result.warnings) if route_result is not None else []),
            kind=refusal_kind(exc, rc=1, state="refused"),
        )
    if route_result is None:
        notes = list(hook_result.post_notes)
        detail = "already routed — re-attempting activation only" + (
            "; " + "; ".join(notes) if notes else ""
        )
    else:
        notes = list(route_result.post_notes) + list(hook_result.post_notes)
        detail = f"route commit {route_result.commit_sha}" + (
            "; " + "; ".join(notes) if notes else ""
        )
    return ItemResult(
        n=item.n, id=item.id, verb=verb, rc=0,
        sha=hook_result.commit_sha, state="applied", detail=detail,
        warnings=(
            (list(route_result.warnings) if route_result is not None else [])
            + list(hook_result.warnings)
        ),
    )


def _dispatch_retire_or_graduate(
    home: Path,
    item: SheetItem,
    f: dict,
    actor: str,
    case: str | None,
    verb: str,
    execution: execution_evidence.ExecutionRef | None,
) -> "verbs.VerbResult":
    """S-67 (U13): the ``retire``/``graduate`` leg of :func:`_dispatch`,
    factored out for the SAME reason :func:`_dispatch_hook_activation`
    already was (its own docstring: "pyright's own complexity limit
    flagged ``_dispatch`` once this logic was inlined there too") — a
    plain two-branch ``elif verb == "retire": ... elif verb ==
    "graduate": ...`` split, and even a single merged ``elif verb in
    (...)"`` branch with an inline ternary, both measured to push
    ``_dispatch`` itself over pyright's per-function CFG complexity
    ceiling ("Code is too complex to analyze",
    ``reportGeneralTypeIssues``); only moving the branch OUT into its
    own function cleared it.

    *verb* is ``"retire"`` or ``"graduate"`` — the caller's own ``elif``
    guard already narrowed it, so this trusts it rather than re-
    checking. ``retire``'s ``covered_by`` is REQUIRED (``REQUIRED_KEYS``
    — ``f["covered_by"]`` is always present here); ``graduate``'s stays
    OPTIONAL (``f.get("covered_by")``, the alias's own legacy-canon path
    when omitted) — kept as two separate calls (not one polymorphic
    ``retire_fn = ... if ... else ...`` picking between the two
    functions) so each call site's own ``covered_by`` keeps its own
    correctly-narrowed static type: a shared variable typed ``str |
    None`` fed to :func:`verbs.retire`'s required, non-optional
    ``covered_by: str`` is itself a fresh pyright error
    (``reportArgumentType`` — measured while fixing the complexity
    error above; the FIRST attempt at this extraction hit exactly this)."""
    if verb == "retire":
        return verbs.retire(
            home, item.id, covered_by=f["covered_by"],
            note=f.get("note"), by=(f.get("by") or actor),
            no_push=True,
            reconsider_case=_reconsider_case_for(home, item.id, case, verb),
            execution=execution,
        )
    return verbs.graduate(
        home, item.id, covered_by=f.get("covered_by"),
        note=f.get("note"), by=(f.get("by") or actor),
        no_push=True,
        reconsider_case=_reconsider_case_for(home, item.id, case, verb),
        execution=execution,
    )


def _dispatch(
    home: Path,
    item: SheetItem,
    *,
    case: str | None = None,
    actor: str = "human",
    hook_activation: bool = False,
    execution: execution_evidence.ExecutionRef | None = None,
) -> ItemResult:
    """Call the SAME ``verbs.*`` function the CLI calls, with
    ``no_push=True``, inside that verb's own ``_ledger_write`` span,
    catching the SAME exception set ``cli._cmd_verb`` catches and mapping
    it to the SAME integer.

    ``case`` (U5): the sheet's own top-level ``case:`` (``run``/
    ``dry_run`` pass ``items.case``) — threaded into
    ``reject``/``defer``/``graduate``/``supersede``'s own
    ``reconsider_case`` via :func:`_reconsider_case_for`, which decides
    PER ITEM whether forwarding it could matter. A ``kind: reconsider``
    case naming a wrong record, or one whose ``kind`` is not
    ``reconsider`` at all, refuses inside the verb itself
    (:func:`self_learn.verbs._reconsider_case_check`) with a message
    naming which check failed — no separate refusal lives here.

    ``actor``/``hook_activation`` (O-2b, 13 §7.4): *actor* is validated
    once, up front, by :func:`run`/:func:`dry_run` — never here — and
    serves two roles on every item this function dispatches: (1) it is
    the default ``by`` for any item whose sheet text names none, on the
    EIGHT resolution verbs that write a ``By: <actor>`` git commit
    trailer (reject/defer/undefer/reopen/graduate/supersede/rehome/
    rescope) — every existing caller passes no ``actor`` and gets the
    unwidened default ``"human"``, so a by-less item on one of those
    eight now carries ``By: human`` where it carried nothing before
    (build-o2b.md's own line: "it is the default `by` for every item
    that names none" — see this build's report for the carried test
    this widens); ``route``/``revise`` never join this EIGHT-verb
    trailer widening — their own ``by`` parameter feeds a DIFFERENT
    mechanism (``route``'s resolves ``Record.set_routing``'s schema
    field via its own dest-is-not-None heuristic; ``revise``'s rides
    the proposal's ``revised_by`` stamp; neither ever writes the commit
    trailer this widening is about) — but fold r1 (F3, ruling 6) gives
    each its OWN narrower actor default at its own call site below:
    ``by = f.get("by") or (actor if actor != "human" else None)`` —
    a default-``"human"`` caller keeps each verb's existing heuristic
    byte-for-byte; a non-human runner is named; (2) it is the ONE
    condition (``actor == "overseer"``) under which a ``route`` item
    resolving to the ``hook`` destination is not refused outright
    (S-29) — the sheet text itself can never request either value
    (``actor``/``activate`` stay unknown ITEM keys; a top-level
    ``actor:`` stays a refused unknown top-level key, both unchanged by
    this build). Fold r1 (F4): a hook-dest item under ``actor==
    "overseer"`` reaching this function with the record ALREADY routed
    to ``hook`` (``classify`` decided the route leg landed but the
    activation leg does not match the CURRENT gate) skips the route
    leg entirely and only re-attempts activation, through the same
    idempotent :func:`verbs.hook_activate`. Fold r1 (F5): either
    activation call (fresh-route or re-attempt) is wrapped broadly —
    any exception, not only :class:`verbs.VerbError` — so nothing ever
    escapes :func:`run`; the runtime undo (if any) has already run
    inside :func:`hook_activation.activate` itself by the time this
    catches it."""
    verb = item.verb
    f = item.fields
    try:
        if verb == "route":
            route_path = find_record_path(home, item.id)
            resolved = _resolved_route_dest(home, route_path, item)
            is_hook_dest = resolved == (REFUSED_HOOK_DESTINATION, None)
            if is_hook_dest and actor != "overseer":
                raise verbs.VerbError(_hook_refused_detail(item.id))
            if is_hook_dest and actor == "overseer":
                # Fold r1 (F4): a hook-dest item reaches HERE, under
                # `actor="overseer"`, in one of two shapes -- a fresh
                # route (record still `pending`, falls through below)
                # or a RETRY (`classify` already decided the record is
                # already routed to `hook` but the activation leg does
                # not match the current gate: a failed attempt, or one
                # parked under a gate that has since flipped). The
                # second shape must never call `verbs.route` again --
                # it would refuse against an already-routed record --
                # so it is detected here and only the activation leg
                # (through the SAME idempotent `verbs.hook_activate` —
                # a placed symlink is re-verified, not re-placed) runs,
                # via `_dispatch_hook_activation`.
                pre_record = Record.from_path(route_path)
                already_routed_to_hook = (
                    pre_record.status == "routed"
                    and (pre_record.routing or {}).get("destination")
                    == REFUSED_HOOK_DESTINATION
                )
                if already_routed_to_hook:
                    return _dispatch_hook_activation(
                        home, item, actor=actor, hook_activation=hook_activation,
                        route_result=None,
                    )
            follow_up = None
            if f.get("follow_up") is not None:
                follow_up = {"action": f["follow_up"]}
                if f.get("unblocks_on") is not None:
                    follow_up["unblocks_on"] = f["unblocks_on"]
                if f.get("follow_up_note") is not None:
                    follow_up["note"] = f["follow_up_note"]
            result = verbs.route(
                home, item.id,
                dest=f.get("dest"),
                # Fold r1 (F3, ruling 6): the actor is the default `by`
                # here TOO, but only for a non-human caller -- a
                # default-`"human"` run keeps `route`'s own
                # dest-is-not-None heuristic byte-for-byte (S-29's
                # `resolved_by` fallback below still decides it), since
                # `route`/`revise` are the two verbs excluded from the
                # EIGHT-verb widening above (their own `by` feeds a
                # DIFFERENT mechanism — `Record.set_routing`'s schema
                # field, never the commit trailer).
                by=(f.get("by") or (actor if actor != "human" else None)),
                note=f.get("note"), no_push=True, follow_up=follow_up,
                collapse=f.get("collapse"),
                allow_empty_glob=bool(f.get("allow_empty_glob", False)),
                execution=execution,
            )
            if is_hook_dest and actor == "overseer":
                # 13 §7.4 "The path" — the overseer's own runner call is
                # the ONE caller that carries a hook route through to
                # activation: route's own commit above is unchanged from
                # the human path (the script it commits is identical
                # either way); `_dispatch_hook_activation` runs the SAME
                # `hook_activation` module O-2a built, inside
                # `verbs.hook_activate`'s own lock/handoff/undo, and
                # (F5) wraps any failure so it refuses THIS item rather
                # than escaping `run` — route's own commit stands
                # (exactly the state a human's own two-step sequence —
                # route now, `hook activate` later — already leaves it
                # in) either way.
                return _dispatch_hook_activation(
                    home, item, actor=actor, hook_activation=hook_activation,
                    route_result=result,
                )
        elif verb == "reject":
            result = verbs.reject(
                home, item.id, note=f.get("note"), by=(f.get("by") or actor),
                no_push=True,
                reconsider_case=_reconsider_case_for(home, item.id, case, verb),
                execution=execution,
            )
        elif verb == "defer":
            until = f.get("until")
            result = verbs.defer(
                home, item.id, until=until, note=f.get("note"),
                by=(f.get("by") or actor),
                no_push=True,
                reconsider_case=_reconsider_case_for(home, item.id, case, verb),
                execution=execution,
            )
        elif verb == "undefer":
            result = verbs.undefer(
                home, item.id, note=f.get("note"), by=(f.get("by") or actor),
                no_push=True,
                execution=execution,
            )
        elif verb == "reopen":
            result = verbs.reopen(
                home, item.id, note=f.get("note"), by=(f.get("by") or actor),
                no_push=True,
                execution=execution,
            )
        elif verb in ("retire", "graduate"):
            # S-67 (U13): pulled out to `_dispatch_retire_or_graduate`
            # (below) -- a straight two-branch elif split here (one
            # `retire`, one `graduate`, mirroring every other verb's own
            # branch) pushed `_dispatch` itself over pyright's CFG
            # complexity ceiling (measured: "Code is too complex to
            # analyze" reportGeneralTypeIssues); MERGING the two
            # branches into one `elif verb in (...)` with an inline
            # ternary was not enough on its own -- the node count that
            # trips the ceiling is per-FUNCTION, so only moving the
            # branch OUT of `_dispatch` entirely (a real subroutine, not
            # a same-function merge) actually clears it.
            result = _dispatch_retire_or_graduate(
                home, item, f, actor, case, verb, execution
            )
        elif verb == "supersede":
            result = verbs.supersede(
                home, item.id, f["new_id"], note=f.get("note"),
                by=(f.get("by") or actor),
                no_push=True,
                reconsider_case=_reconsider_case_for(home, item.id, case, verb),
                execution=execution,
            )
        elif verb == "rehome":
            result = verbs.rehome(
                home, item.id, to=f["to"], note=f.get("note"),
                by=(f.get("by") or actor),
                no_push=True,
                execution=execution,
            )
        elif verb == "rescope":
            result = verbs.rescope(
                home, item.id, to=f["to"], note=f.get("note"),
                by=(f.get("by") or actor),
                no_push=True,
                execution=execution,
            )
        elif verb == "note":
            result = verbs.note(
                home, item.id, append=f["append"], key=f.get("key"),
                no_push=True,
                execution=execution,
            )
        elif verb == "confirm-recurrence":
            result = verbs.confirm_recurrence(
                home, item.id, event_ref=f["event"],
                tolerate=bool(f.get("tolerate", False)), note=f.get("note"),
                no_push=True,
                execution=execution,
            )
        elif verb == "dismiss-suspect":
            result = verbs.dismiss_suspect(
                home, item.id, event_ref=f["event"], why=f["why"],
                note=f.get("note"), no_push=True,
                execution=execution,
            )
        elif verb == "confirm-held":
            result = verbs.confirm_held(
                home, item.id, note=f.get("note"), no_push=True,
                execution=execution,
            )
        elif verb == "link-contradicts":
            result = verbs.link_contradicts(
                home, item.id, f["target"], note=f.get("note"), no_push=True,
                execution=execution,
            )
        elif verb == "followup-done":
            result = verbs.followup_done(
                home, item.id, note=f.get("note"), no_push=True,
                execution=execution,
            )
        elif verb == "revise":
            # U3 (carried from the U4 gate): U4 added `revise` to
            # PERMITTED_VERBS/PERMITTED_KEYS/REQUIRED_KEYS but this
            # ladder had no branch for it, so a sheet naming `revise`
            # crashed HERE on the `else: raise AssertionError` below --
            # a mid-sheet abort (whatever ran before it stayed
            # committed), not a per-item refusal. `because` is
            # REQUIRED (batch.REQUIRED_KEYS["revise"]) so `f["because"]`
            # is always present by the time `run`/`_dispatch` reach it.
            result = verbs.revise(
                home, item.id, section=f["section"], text=f["text"],
                because=f["because"],
                # Fold r1 (F3, ruling 6): same non-human-only actor
                # default `route` gets above -- `revise`'s own `by`
                # rides the proposal's `revised_by` stamp, not a commit
                # trailer, but the SAME "default-human is unchanged,
                # a non-human runner is named" rule applies to it.
                by=(f.get("by") or (actor if actor != "human" else None)),
                no_push=True,
                execution=execution,
            )
        else:  # pragma: no cover — load_sheet already gated the verb set
            raise AssertionError(f"unreachable: unpermitted verb {verb!r}")
    except verbs.VerbError as exc:  # incl. SecretRefusal
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=exc.exit_code,
                           state="refused", detail=str(exc),
                           kind=refusal_kind(exc, rc=exc.exit_code, state="refused"))
    except LedgerOpsError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=64,
                           state="refused", detail=str(exc),
                           kind=refusal_kind(exc, rc=64, state="refused"))
    except CompileError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=1,
                           state="refused", detail=str(exc),
                           kind=refusal_kind(exc, rc=1, state="refused"))
    except MutationError as exc:
        # U5 fold r1 (F2 leg i): a resolution verb's own write-once
        # field collision (`resolve_record`'s `resolution_note`, e.g.
        # `graduate --note` over an already-routed record that already
        # carries one — pre-existing at base, unrelated to this diff)
        # used to propagate a bare `records.MutationError` out of
        # `batch.run` entirely, aborting the WHOLE sheet mid-run —
        # whatever landed before this item stayed committed, the rest
        # got no receipt (the exact mid-sheet-abort shape U4 closed for
        # other exception types, `batch.py`'s own comment above the
        # `revise` branch). A per-item refusal instead, same rc as
        # `CompileError`'s — the record itself is provably untouched
        # (the raise happens before any `record.write`, gate probe Q1).
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=1,
                           state="refused", detail=str(exc),
                           kind=refusal_kind(exc, rc=1, state="refused"))
    except gitops.HalfWrittenError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb,
                           rc=gitops.EXIT_HALF_WRITTEN, state="refused",
                           detail=str(exc),
                           kind=refusal_kind(
                               exc, rc=gitops.EXIT_HALF_WRITTEN, state="refused"
                           ))
    except gitops.GitOpsError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb,
                           rc=gitops.EXIT_GIT_FAILED, state="refused",
                           detail=str(exc),
                           kind=refusal_kind(
                               exc, rc=gitops.EXIT_GIT_FAILED, state="refused"
                           ))
    return ItemResult(
        n=item.n, id=item.id, verb=verb, rc=0, sha=result.commit_sha,
        state="applied", warnings=list(result.warnings),
    )


#: A ledger-level failure that stops the sheet (§3.3: "the ledger is unsafe
#: to keep writing into"). 5 (no ledger home) and 6 (git failed before any
#: mutation) wrote nothing. 7 (`gitops.EXIT_HALF_WRITTEN`) left a write
#: uncommitted; a later attempt is safe only because every ledger write
#: first runs intent recovery (`intents.ledger_write`, S-62), which rolls
#: that write forward, restores it, or stops.
_STOP_CODES = frozenset({5, 6, 7})

# These verbs can return only after a ledger commit and one or more host
# effects. Their owner-returned result must be receipted before a dependent
# item starts; a mutation trailer proves only the ledger leg.
_HOST_OUTCOME_VERBS = frozenset({"route", "reject", "retire", "graduate", "supersede"})


def _validate_continuation(
    items: list[SheetItem], continuation: BatchContinuation
) -> tuple[str, str, str]:
    case = getattr(items, "case", None)
    sheet_sha = getattr(items, "sheet_sha", None)
    sheet_digest = getattr(items, "sheet_digest", None)
    if case != continuation.case_id:
        raise BatchError("batch continuation case id does not match the sheet")
    if sheet_digest != continuation.sheet_digest:
        raise BatchError("batch continuation full sheet digest does not match the sheet")
    if not isinstance(sheet_sha, str):
        raise BatchError("batch continuation requires the original short sheet sha")
    by_n = {item.n: item for item in items}
    for n, completed in continuation.completed.items():
        item = by_n.get(n)
        if item is None:
            raise BatchError(f"batch continuation names unknown original item {n}")
        if (completed.n, completed.id, completed.verb) != (item.n, item.id, item.verb):
            raise BatchError(f"batch continuation item {n} does not match the sheet")
        successful = completed.state in {"applied", "already-applied"} and completed.rc == 0
        unresolved_host = (
            completed.state == "unresolved-host"
            and isinstance(completed.detail, str)
            and bool(completed.detail.strip())
        )
        if not successful and not unresolved_host:
            raise BatchError(
                f"batch continuation item {n} is neither a proven completion "
                "nor a named unresolved host obligation"
            )
    # ExecutionRef applies its strict run/case/digest validation before item 1.
    if items:
        first = items[0]
        execution_evidence.ExecutionRef(
            run_id=continuation.run_id,
            case_id=continuation.case_id,
            sheet_sha=sheet_sha,
            sheet_digest=continuation.sheet_digest,
            item=first.n,
            record_id=first.id,
            verb=first.verb,
            actor="steward",
        )
    return continuation.case_id, sheet_sha, continuation.sheet_digest


def _checkpoint_or_halt(
    checkpoint: Callable[[BatchResult], dict | None],
    result: BatchResult,
    tail: list[SheetItem],
) -> None:
    try:
        outcome = checkpoint(result)
    except Exception as exc:  # noqa: BLE001 — durability owner failures halt uniformly
        result.process_code = decision_code(result.items)
        raise BookkeepingHalt(
            f"ordered receipt checkpoint raised: {exc}", result, tail
        ) from exc
    if outcome is None or outcome.get("state") != "ok":
        result.process_code = decision_code(result.items)
        reason = "ordered receipt checkpoint returned no result"
        if isinstance(outcome, dict) and outcome.get("reason"):
            reason = f"ordered receipt checkpoint failed: {outcome['reason']}"
        raise BookkeepingHalt(reason, result, tail)
    result.preserved_receipt_items.update(item.n for item in result.items)


def _record_ledger_stop(
    result: BatchResult,
    item: SheetItem,
    tail: list[SheetItem],
    exc: intents.LedgerStoppedError,
) -> None:
    """Convert a continuation-span STOP to the ordinary stopped-item shape."""
    result.recovered_rolled_forward.extend(exc.result.rolled_forward)
    result.recovered_restored.extend(exc.result.restored)
    result.stop_message = str(exc)
    result.stopped_at = item.n
    result.items.append(
        ItemResult(
            n=item.n,
            id=item.id,
            verb=item.verb,
            rc=gitops.EXIT_GIT_FAILED,
            state="stopped",
            detail=str(exc),
            kind=refusal_kind(exc, rc=gitops.EXIT_GIT_FAILED, state="stopped"),
        )
    )
    for remaining in tail:
        result.items.append(
            ItemResult(
                n=remaining.n,
                id=remaining.id,
                verb=remaining.verb,
                rc=-1,
                state="not-attempted",
            )
        )


def decision_code(results: list[ItemResult]) -> int:
    """§3.3a's decision procedure — a PROCEDURE, never a raw ``max()``.

    1. a ledger-level failure occurred (an item returned 3, 4 or 7) →
       the WORST of those three, under ``7 > 4 > 3`` — UNCHANGED by
       S-62;
    2. an item returned 6 →  6 if NOTHING in the sheet committed, else
       8 — the S-62 amendment (13 §5, amending this row's own rule 3):
       a mid-sheet 6 (a live intent STOP, checked at each item's own
       lock) must not override commits that already landed the same
       way 7/3/4 legitimately do, or the sheet's own exit code would
       claim "nothing was written" (6's ratified meaning) over a sheet
       that plainly wrote something;
    3. every item applied or already-applied → 0;
    4. ≥1 refusal AND ≥1 commit landed → 8 (EXIT_BATCH_PARTIAL);
    5. ≥1 refusal, ZERO commits → 1 — `1`'s ratified meaning (refused,
       nothing written) is never emitted after a write."""
    landed = any(r.state == "applied" for r in results)
    ledger_level_high = [r.rc for r in results if r.rc in (3, 4, 7)]
    if ledger_level_high:
        for code in (7, 4, 3):
            if code in ledger_level_high:
                return code
    if any(r.rc == 6 for r in results):
        return 8 if landed else 6
    # Fold r1 (F9): a `stopped` item (rc 5/6/7, the one that actually
    # halted the sheet) counts as a refusal here too -- an rc=5 stop
    # with nothing landed must still decide 1 ("refused, nothing
    # written"), not 0, now that `run` gives that item `state=
    # "stopped"` instead of the generic `"refused"` every other
    # per-verb refusal gets.
    refused = any(r.state in ("refused", "stopped") for r in results)
    if not refused:
        return 0
    if landed:
        return 8
    return 1


#: Status precondition each non-`route` verb needs — mirrors the guard
#: vocabulary each verb itself consults (§3.1), so `--dry-run` can name a
#: status refusal without calling the verb or writing anything. `note`
#: and `link-contradicts` take no status gate (any status).
_STATUS_GATE: dict[str, frozenset[str]] = {
    "reject": LIVE_STATUSES,
    "defer": LIVE_STATUSES,
    "undefer": DEFERRED_ONLY,
    # S-67: mirrors `verbs._REOPEN_ADMITTED_STATUSES` — the status half
    # of `reopen`'s widened admission. The REPLACED-vs-RETIRED distinction
    # (a record-id `superseded_by` stays refused) is not a status-set
    # question and is previewed separately below, in `dry_run` itself.
    "reopen": REOPENABLE_STATUSES | frozenset({"superseded"}),
    "retire": RESOLVABLE_STATUSES,
    "graduate": RESOLVABLE_STATUSES,
    "supersede": RESOLVABLE_STATUSES,
    "rehome": LIVE_STATUSES,
    "rescope": LIVE_STATUSES,
    "confirm-recurrence": ROUTED_ONLY,
    "dismiss-suspect": ROUTED_ONLY,
    "confirm-held": ROUTED_ONLY,
    "followup-done": ROUTED_ONLY,
    # U3 (carried from the U4 gate): `verbs.revise` admits only
    # LIVE_STATUSES (`records.DRAFT_STATUSES` under this module's own
    # import name -- the same two values, pending/deferred) — without
    # this entry `dry_run`'s generic status-gate check (below) fell
    # through to `gate is None` and reported "would-apply" for a
    # revise item against a routed/rejected/superseded record.
    "revise": LIVE_STATUSES,
}


@dataclass
class DryRunItem:
    n: int
    id: str
    verb: str
    state: str  # "already-applied" | "would-apply" | "would-refuse"
    detail: str | None = None
    route_preview: dict | None = None
    #: S-71: the refusal's kind, set only on a ``would-refuse`` item — the
    #: kind the real run would give the same refusal.
    kind: str | None = None


@dataclass
class DryRunResult:
    items: list[DryRunItem] = field(default_factory=list)
    hook_items: list[str] = field(default_factory=list)
    #: U3: the sheet's own top-level `case:`, same as `BatchResult.case`
    #: -- a `--dry-run` preview names the case it WOULD receipt into,
    #: same as it names every other would-happen detail.
    case: str | None = None
    #: Fold r1: the sheet's own `.sheet_sha`, same as `BatchResult.
    #: sheet_sha` -- `None` for a plain `list[SheetItem]` caller.
    sheet_sha: str | None = None
    #: Fold r1 (F2): same field, same default, as `BatchResult.actor` --
    #: a preview names the actor it would run as, same as it names
    #: every other would-happen detail.
    actor: str = "human"

    @property
    def ok(self) -> bool:
        return not any(i.state == "would-refuse" for i in self.items)

    def to_json(self) -> dict:
        return {
            "items": [
                {
                    "n": i.n, "id": i.id, "verb": i.verb, "state": i.state,
                    "detail": i.detail, "route_preview": i.route_preview,
                    **({"kind": i.kind} if i.kind is not None else {}),
                }
                for i in self.items
            ],
            "hook_items": self.hook_items,
            "case": self.case,
            "sheet_sha": self.sheet_sha,
            "ok": self.ok,
            "actor": self.actor,
        }


def dry_run(
    home: Path | str,
    items: list[SheetItem],
    *,
    actor: str = "human",
    hook_activation: bool = False,
) -> DryRunResult:
    """BAT9: writes nothing at all — ledger AND hosts (O-2b: this
    includes the runtime directory — a hook item's preview below never
    calls :func:`self_learn.hook_activation.activate`, only labels what
    :func:`_dispatch` WOULD do). For a `route` item this is EXACTLY
    `route --dry-run`'s own payload, called as a function (the
    delegation leg) — no second preflight implementation. Every other
    verb reports its own status precondition (:data:`_STATUS_GATE`)
    with nothing written. `hook_items` names the sheet-level
    prerequisite the two hand scripts (§2.4) had to sequence by hand: a
    route item whose resolved destination is `hook` — populated
    unconditionally, regardless of *actor*, exactly as before this
    build (`test_bat6_refuses_hook_routes`'s own dry-run leg pins this
    at the default ``actor="human"``).

    ``actor``/``hook_activation`` (O-2b, 13 §7.4): same two keyword-only
    parameters :func:`run` takes, previewing the SAME per-actor
    decision `_dispatch` would make for a hook item WITHOUT touching
    anything — refused (``actor != "overseer"``), placed only
    (``actor == "overseer"`` and the gate is ``False``), or activated
    (``actor == "overseer"`` and the gate is ``True``)."""
    if actor not in verbs.ROUTING_BY_VALUES:
        raise BatchError(
            f"batch: actor={actor!r} must be one of "
            f"{sorted(verbs.ROUTING_BY_VALUES)}"
        )
    home = Path(home)
    sheet_case = getattr(items, "case", None)
    result = DryRunResult(
        case=sheet_case,
        sheet_sha=getattr(items, "sheet_sha", None),
        actor=actor,
    )
    for item in items:
        applied, unreadable = _classify_or_refuse(
            home, item, actor=actor, hook_activation=hook_activation
        )
        if unreadable is not None:
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb,
                           state="would-refuse", detail=unreadable.detail,
                           kind=unreadable.kind)
            )
            continue
        if applied:
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb,
                           state="already-applied")
            )
            continue
        if item.verb == "route":
            try:
                path = find_record_path(home, item.id)
            except LedgerOpsError as exc:
                result.items.append(
                    DryRunItem(n=item.n, id=item.id, verb=item.verb,
                               state="would-refuse", detail=str(exc),
                               kind=_preview_kind([exc]))
                )
                continue
            resolved = _resolved_route_dest(home, path, item)
            is_hook_dest = resolved is not None and resolved[0] == REFUSED_HOOK_DESTINATION
            if is_hook_dest:
                result.hook_items.append(item.id)
                if actor != "overseer":
                    # Fold r1 (F8): the SAME shared sentence `_dispatch`
                    # raises for real — previewed here, nothing touched,
                    # never a second hand-copied literal to drift. S-71:
                    # the kind is the one `_dispatch`'s plain `VerbError`
                    # gets.
                    hook_detail = _hook_refused_detail(item.id)
                    result.items.append(
                        DryRunItem(
                            n=item.n, id=item.id, verb=item.verb,
                            state="would-refuse",
                            detail=hook_detail,
                            kind=_preview_kind([verbs.VerbError(hook_detail)]),
                        )
                    )
                    continue
                # actor == "overseer": preview the SAME two-tier outcome
                # `_dispatch` would apply — "placed only" (gate false)
                # or "activated" (gate true) — after route's own
                # preflight (`route_dry_run`) still clears, and without
                # ever calling `hook_activation.activate` (BAT9: a dry
                # run writes nothing at all, ledger AND hosts).
                dr = verbs.route_dry_run(home, item.id, dest=item.fields.get("dest"))
                if dr.would_refuse:
                    result.items.append(
                        DryRunItem(
                            n=item.n, id=item.id, verb=item.verb,
                            state="would-refuse",
                            detail="; ".join(dr.would_refuse),
                            route_preview=dr.to_json(),
                            kind=_preview_kind(dr.refusal_errors),
                        )
                    )
                    continue
                label = "activated" if hook_activation else "placed only"
                result.items.append(
                    DryRunItem(
                        n=item.n, id=item.id, verb=item.verb, state="would-apply",
                        detail=f"overseer path: route, then hook {label}",
                        route_preview=dr.to_json(),
                    )
                )
                continue
            dr = verbs.route_dry_run(home, item.id, dest=item.fields.get("dest"))
            state = "would-refuse" if dr.would_refuse else "would-apply"
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb, state=state,
                           detail="; ".join(dr.would_refuse) or None,
                           route_preview=dr.to_json(),
                           kind=(_preview_kind(dr.refusal_errors)
                                 if dr.would_refuse else None))
            )
            continue
        try:
            path = find_record_path(home, item.id)
        except LedgerOpsError as exc:
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb,
                           state="would-refuse", detail=str(exc),
                           kind=_preview_kind([exc]))
            )
            continue
        if item.verb in ("rehome", "rescope"):
            try:
                verbs._resolve_move_target(home, item.fields["to"])
            except verbs.VerbError as exc:
                result.items.append(
                    DryRunItem(n=item.n, id=item.id, verb=item.verb,
                               state="would-refuse", detail=str(exc),
                               kind=_preview_kind([exc]))
                )
                continue
        record = Record.from_path(path)
        gate = _STATUS_GATE.get(item.verb)
        if (
            gate is not None and record.status not in gate
            # U5: the same per-item widening `_dispatch` would apply at
            # apply time — a validated `kind: reconsider` case over a
            # routed record's item previews `would-apply`, not a stale
            # `would-refuse` naming a status the real run would admit.
            and _reconsider_case_for(home, item.id, sheet_case, item.verb) is None
        ):
            status_detail = f"record {item.id} is {record.status!r}"
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb,
                           state="would-refuse",
                           detail=status_detail,
                           kind=_preview_kind([StatusRefusal(
                               status_detail, record_id=item.id,
                               current_status=record.status, allowed=gate,
                           )]))
            )
            continue
        # S-67: `_STATUS_GATE["reopen"]` admits `superseded` for BOTH a
        # retirement and a replacement — the same distinction
        # `verbs.reopen` itself draws one level down, once the record is
        # in hand, previewed here rather than left to look like
        # `would-apply` and then refuse for real.
        if (
            item.verb == "reopen"
            and record.status == "superseded"
            and is_replacement(record.superseded_by)
        ):
            reopen_detail = (
                f"record {item.id} is superseded by a replacement "
                f"({record.superseded_by}) — use reconsider"
            )
            result.items.append(
                DryRunItem(
                    n=item.n, id=item.id, verb=item.verb,
                    state="would-refuse",
                    detail=reopen_detail,
                    kind=_preview_kind([verbs.SheetLineError(reopen_detail)]),
                )
            )
            continue
        result.items.append(
            DryRunItem(n=item.n, id=item.id, verb=item.verb, state="would-apply")
        )
    return result


def run(
    home: Path | str,
    items: list[SheetItem],
    *,
    no_push: bool = False,
    actor: str = "human",
    hook_activation: bool = False,
    continuation: BatchContinuation | None = None,
    checkpoint: Callable[[BatchResult], dict | None] | None = None,
) -> BatchResult:
    """Apply *items* in one locked run (§4.4's procedure): ONE owning
    sentinel hold → heartbeat → per item, classify (skip if
    already-applied) or dispatch → stop on the first 5/6/7 → flush
    exactly once through ``cli._mutating_epilogue`` (§3.3c, the seventh
    and last call site) → one push unless ``no_push`` → release.

    ``actor``/``hook_activation`` (O-2b, 13 §7.4 "The path"): two
    keyword-only parameters ONLY the overseer's own runner call (O-3)
    sets — the CLI `batch` verb never exposes either as a flag, and
    sheet text can never set them (``actor``/``activate`` stay unknown
    ITEM keys; a top-level ``actor:`` stays a refused unknown top-level
    key). *actor* is validated here, before item 1, against the SAME
    closed set every sheet item's own ``by:`` already validates against
    (:data:`verbs.ROUTING_BY_VALUES`) — a bad value refuses the WHOLE
    run before any lock is taken, the same shape :func:`load_sheet`'s
    own BAT1 validation uses. Both are threaded to :func:`_dispatch` for
    every item: *actor* is the default ``by`` for an item naming none,
    on the EIGHT commit-trailer verbs only (route/revise excluded —
    see :func:`_dispatch`'s own docstring for why), and the ONE
    condition (``actor == "overseer"``) under which a hook route is not
    refused outright — *hook_activation* is read only on that path,
    forwarded to ``verbs.hook_activate``'s own ``register`` keyword
    (default ``True`` there — the human path, and every OTHER caller of
    this function, are unaffected)."""
    if actor not in verbs.ROUTING_BY_VALUES:
        raise BatchError(
            f"batch: actor={actor!r} must be one of "
            f"{sorted(verbs.ROUTING_BY_VALUES)}"
        )
    # Lazy import: `cli` imports THIS module for `_cmd_batch`, so a
    # module-level import here would be circular. `_mutating_epilogue`
    # is only ever needed once execution actually reaches this point.
    from . import cli as cli_mod

    home = Path(home)
    flush_epilogue = lambda: cli_mod._mutating_epilogue(home, no_push=True)
    # U3: `items` is a `Sheet` when it came from `load_sheet`; a plain
    # `list[SheetItem]` (every pre-existing caller, incl. U4's own
    # `test_revise_then_route_sheet_applies_both`) has no `.case` and
    # gets `None` here, exactly today's behaviour.
    case = getattr(items, "case", None)
    sheet_sha = getattr(items, "sheet_sha", None)
    sheet_digest = getattr(items, "sheet_digest", None)
    if continuation is not None:
        case, sheet_sha, sheet_digest = _validate_continuation(items, continuation)
        if checkpoint is None:
            raise BatchError(
                "batch continuation requires an ordered receipt checkpoint"
            )
        checkpoint_required = True
    else:
        checkpoint_required = False
    # S-62 (13 §5): the sheet-level check, once, before item 1 — a
    # pre-existing STOP refuses the WHOLE sheet before anything lands,
    # the same way a sheet-invalid (64) or home-gate (5) refusal does.
    # `with intents.ledger_write(home): pass` runs recovery (if this is
    # the outermost acquisition in-process) and raises before yielding
    # on a STOP; a clean pass silently heals whatever it could and
    # changes nothing else about the run below. Each item's own verb
    # still runs its own check at its own lock — this is the backstop
    # for a STOP that appears MID-sheet (§7.2a.5(4)), not a replacement
    # for it.
    try:
        with intents.ledger_write(home) as recovered:
            pass
    except intents.LedgerStoppedError as exc:
        # §7.2a.5(5): the message names the offending intent — a 6 with
        # no message would say "refused" without saying WHICH intent or
        # why, unlike every other surface's refusal.
        return BatchResult(
            case=case,
            sheet_sha=sheet_sha,
            process_code=gitops.EXIT_GIT_FAILED,
            recovered_rolled_forward=list(exc.result.rolled_forward),
            recovered_restored=list(exc.result.restored),
            stop_message=str(exc),
            actor=actor,
        )
    result = BatchResult(
        case=case,
        sheet_sha=sheet_sha,
        recovered_rolled_forward=list(recovered.rolled_forward),
        recovered_restored=list(recovered.restored),
        actor=actor,
        preserved_receipt_items={
            n
            for n, completed in (continuation.completed.items() if continuation else [])
            if completed.evidence is None and completed.state != "unresolved-host"
        },
    )
    push_exit: int | None = None
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        for idx, item in enumerate(items):
            if continuation is not None and item.n in continuation.completed:
                completed = continuation.completed[item.n]
                result.items.append(
                    ItemResult(
                        n=completed.n,
                        id=completed.id,
                        verb=completed.verb,
                        rc=completed.rc,
                        sha=completed.sha,
                        state=completed.state,
                        detail=completed.detail,
                        warnings=list(completed.warnings),
                        evidence=completed.evidence,
                    )
                )
                # A recovered ledger-only completion carries explicit
                # reconstruction evidence. Its Application line must land
                # before a dependent item starts. Entries reconstructed from
                # an existing committed receipt omit ``evidence`` and need no
                # redundant checkpoint.
                if completed.state == "unresolved-host":
                    assert checkpoint is not None
                    _checkpoint_or_halt(
                        checkpoint, result, list(items[idx + 1:])
                    )
                    result.process_code = decision_code(result.items)
                    raise BookkeepingHalt(
                        f"unresolved host obligation for item {item.n}: "
                        f"{completed.detail}",
                        result,
                        list(items[idx + 1:]),
                    )
                if completed.evidence is not None:
                    assert checkpoint is not None
                    _checkpoint_or_halt(
                        checkpoint, result, list(items[idx + 1:])
                    )
                continue
            already_applied = False
            unreadable: ItemResult | None = None
            if continuation is not None:
                # Bind present-state classification and its ordered receipt to
                # one ledger span. Otherwise a manual/intervening edit could
                # make a dirty working file look like a committed no-op.
                try:
                    with intents.ledger_write(home) as item_recovered:
                        intents.announce_recovered(item_recovered)
                        result.recovered_rolled_forward.extend(
                            item_recovered.rolled_forward
                        )
                        result.recovered_restored.extend(item_recovered.restored)
                        try:
                            item_path = find_record_path(home, item.id)
                        except LedgerOpsError:
                            item_path = None
                        dirty = (
                            gitops.dirty_paths(home, item_path)
                            if item_path is not None
                            else []
                        )
                        if dirty:
                            raise BookkeepingHalt(
                                "batch continuation refuses uncommitted record "
                                f"state before item {item.n}: {dirty}",
                                result,
                                list(items[idx:]),
                            )
                        already_applied, unreadable = _classify_or_refuse(
                            home,
                            item,
                            actor=actor,
                            hook_activation=hook_activation,
                        )
                        if unreadable is not None:
                            # S-71 §8.2: receipted like any other refusal,
                            # inside the same span, before the next item.
                            result.items.append(unreadable)
                            assert checkpoint is not None
                            _checkpoint_or_halt(
                                checkpoint, result, list(items[idx + 1:])
                            )
                        if already_applied:
                            result.items.append(
                                ItemResult(
                                    n=item.n,
                                    id=item.id,
                                    verb=item.verb,
                                    rc=0,
                                    state="already-applied",
                                )
                            )
                            assert checkpoint is not None
                            _checkpoint_or_halt(
                                checkpoint, result, list(items[idx + 1:])
                            )
                except intents.LedgerStoppedError as exc:
                    _record_ledger_stop(result, item, list(items[idx + 1:]), exc)
                    break
            else:
                already_applied, unreadable = _classify_or_refuse(
                    home, item, actor=actor, hook_activation=hook_activation
                )
                if unreadable is not None:
                    result.items.append(unreadable)
            if unreadable is not None:
                continue
            if already_applied:
                if continuation is None:
                    result.items.append(
                        ItemResult(n=item.n, id=item.id, verb=item.verb, rc=0,
                                   state="already-applied")
                    )
                continue
            dispatch_span = (
                intents.ledger_write(home)
                if continuation is not None
                else nullcontext(None)
            )
            try:
                with dispatch_span as dispatch_recovered:
                    if continuation is not None:
                        assert dispatch_recovered is not None
                        intents.announce_recovered(dispatch_recovered)
                        result.recovered_rolled_forward.extend(
                            dispatch_recovered.rolled_forward
                        )
                        result.recovered_restored.extend(
                            dispatch_recovered.restored
                        )
                        try:
                            item_path = find_record_path(home, item.id)
                        except LedgerOpsError:
                            item_path = None
                        dirty = (
                            gitops.dirty_paths(home, item_path)
                            if item_path is not None
                            else []
                        )
                        if dirty:
                            raise BookkeepingHalt(
                                "batch continuation refuses uncommitted record "
                                f"state before item {item.n}: {dirty}",
                                result,
                                list(items[idx:]),
                            )
                    head_before = (
                        gitops.head_sha(home) if continuation is not None else None
                    )
                    execution = None
                    if continuation is not None:
                        assert case is not None and sheet_sha is not None
                        execution = execution_evidence.ExecutionRef(
                            run_id=continuation.run_id,
                            case_id=case,
                            sheet_sha=sheet_sha,
                            sheet_digest=continuation.sheet_digest,
                            item=item.n,
                            record_id=item.id,
                            verb=item.verb,
                            actor=actor,
                        )
                    item_result = _dispatch(
                        home,
                        item,
                        case=case,
                        actor=actor,
                        hook_activation=hook_activation,
                        execution=execution,
                    )
                    # Read HEAD right after the dispatch, before anything
                    # else can move it: the evidence line below and the
                    # host-outcome halt further down both turn on whether
                    # this ONE dispatch committed anything.
                    no_mutation = (
                        head_before == gitops.head_sha(home)
                        if checkpoint_required
                        else False
                    )
                    if continuation is not None and item.verb in _HOST_OUTCOME_VERBS:
                        item_result.evidence = (
                            f"host result returned by {item.verb}"
                            if item_result.rc == 0
                            else f"refused by {item.verb} before its ledger commit; nothing written"
                            if no_mutation
                            else f"host failure returned by {item.verb}"
                        )
                    if item_result.rc in _STOP_CODES:
                        # Fold r1 (F9): this is the ONE item whose rc actually
                        # halted the sheet -- 02-schema.md §3a.2 §5 names
                        # `stopped` as its own receipt state, distinct from an
                        # ordinary per-verb `refused`; `_dispatch` cannot know
                        # at dispatch time whether ITS OWN refusal is the one
                        # that stops the sheet, so `run` (the only place that
                        # DOES know) overrides here, before the item ever joins
                        # `result.items`.
                        item_result.state = "stopped"
                        item_result.kind = refusal_kind(
                            None, rc=item_result.rc, state="stopped"
                        )
                    result.items.append(item_result)
                    if checkpoint_required:
                        assert checkpoint is not None
                        if (
                            no_mutation
                            or item_result.rc != 0
                            or item.verb in _HOST_OUTCOME_VERBS
                        ):
                            _checkpoint_or_halt(
                                checkpoint, result, list(items[idx + 1:])
                            )
                        # A host-outcome verb that failed AFTER its ledger
                        # leg committed leaves a real half-state (the ledger
                        # says routed, the host file may not), and only a
                        # runner can report that obligation -- so the sheet
                        # halts. One that failed with HEAD still where it was
                        # wrote nothing at all: every one of these five verbs
                        # commits the ledger before it touches a host file
                        # (`_execute_route`, `reject`, `_retire_impl`,
                        # `supersede`), so an unchanged HEAD proves the host
                        # was never reached. That is an ordinary refusal, and
                        # it is already receipted above; the rest of the sheet
                        # runs. (The steward's first real run, 2026-09-21,
                        # lost five prepared cases to a halt over a route
                        # that had refused at preflight.)
                        if (
                            item.verb in _HOST_OUTCOME_VERBS
                            and item_result.rc != 0
                            and not no_mutation
                        ):
                            result.process_code = decision_code(result.items)
                            raise BookkeepingHalt(
                                f"host outcome failed for item {item.n} ({item.verb}) "
                                "after its ledger commit landed",
                                result,
                                list(items[idx + 1:]),
                            )
            except intents.LedgerStoppedError as exc:
                _record_ledger_stop(result, item, list(items[idx + 1:]), exc)
                break
            sentinel.heartbeat()
            if item_result.rc in _STOP_CODES:
                result.stopped_at = item.n
                # U3 (02-schema.md §3a.1 rule 5 / §3a.2 §5; plan
                # `plan-steward-2026-09-12.md:401-404`): the WHOLE
                # sheet rides the result, not just what ran -- one
                # `not-attempted` `ItemResult` per item this stop left
                # undispatched, so a `--json` consumer (and
                # `cases.receipt`'s own tail loop, `cases.py:1002-1006`,
                # which keys off `n > stopped_at` regardless of any
                # `state` a caller supplies) has a line for every sheet
                # item rather than a silently truncated list. `rc=-1`
                # is a sentinel never used by a real verb outcome
                # (`decision_code` only inspects `rc in (3, 4, 6, 7)`,
                # so it cannot change the sheet's own process_code).
                for remaining in items[idx + 1:]:
                    result.items.append(
                        ItemResult(
                            n=remaining.n, id=remaining.id, verb=remaining.verb,
                            rc=-1, state="not-attempted",
                        )
                    )
                break
        # 11 §4.2's flush — the ONE place that rule is written; `batch`
        # is call site #7 of `cli._mutating_epilogue` (§3.3c). Inside the
        # hold, before the push, always `no_push=True`: the batch owns
        # the single push, so the flush's own commit rides it rather
        # than publishing itself.
        flush_epilogue()
        if not no_push:
            push = verbs.push_pending(home)
            result.pushed = True
            if not push.ok:
                push_exit = push.exit_code
    except BookkeepingHalt:
        flush_epilogue()
        raise
    finally:
        hold.release()
    result.process_code = decision_code(result.items)
    if push_exit is not None:
        # §8: "push failed after the batch's commits" (3) / "rebase
        # conflict after the batch's commits" (4) — discovered AFTER
        # every item's own code, so it outranks the item-derived
        # decision the same way it does for a single verb.
        result.process_code = push_exit
    return result


def write_receipt(
    home: Path | str,
    result: BatchResult,
    sheet_name: str,
    *,
    no_push: bool = False,
    prefix: bool = False,
) -> dict | None:
    """O-2b: the case-receipt block moved verbatim out of
    ``cli._cmd_batch`` — a SECOND, non-nested ``intents.ledger_write``
    acquisition (``cases.receipt`` opens its own; ``run``'s own locked
    section is already closed by the time a caller has a
    :class:`BatchResult` to hand this), so this is a plain function, not
    a continuation of ``run``'s own lock span. ``None`` when *result*
    names no case (``result.case is None`` — every sheet with no
    top-level ``case:`` key, unchanged from before this move: nothing
    receipted, nothing printed). Otherwise returns exactly the dict
    ``cli._cmd_batch`` used to build inline and rides in the ``--json``
    envelope's ``"receipt"`` key: ``{"state": "ok", "pushed": bool |
    None}`` on success, ``{"state": "failed", "reason": str(exc)}`` on a
    ``cases.CaseError``/``gitops.GitOpsError`` — the SAME breadth the
    original inline ``except`` clause caught (``GitOpsError`` is the
    shared base of ``HalfWrittenError``/``intents.LedgerStoppedError``
    too). A receipt failure prints to stderr here, unconditionally
    (json or text mode — matching the original call site, which printed
    before either output branch), and NEVER raises: the batch's own
    ``process_code`` is already decided by the time a caller reaches
    this, and a bookkeeping append failing afterward must never rewrite
    it (F2, `03-decisions.md` S-54 as amended). *no_push* mirrors the
    sheet's own ``--no-push``: the receipt's own commit is pushed
    separately, strictly AFTER ``run``'s single push already returned,
    under the same rule. A direct call from a non-CLI caller (O-3's own
    runner) writes the SAME Application section `cases.receipt` always
    has — this function has no CLI-specific behaviour left in it.

    ``prefix=True`` is the delegated continuation form. It omits ordinals
    already known to have committed Application lines, and after each
    successful checkpoint :func:`run` marks that prefix as preserved. Thus a
    later checkpoint submits only missing or legitimately advanced keys and
    never refreshes an earlier receipt line's timestamp."""
    if result.case is None:
        return None
    home = Path(home)
    # F1: EVERY item rides the receipt, including `already-applied` —
    # `cases.receipt` is idempotent BY KEY now (a re-run of the SAME
    # sheet REPLACES a key's line rather than appending), so the OLD
    # "exclude already-applied, skip the call once nothing remains"
    # filter — the CLI's own former (broken) idempotence mechanism,
    # gate-u3-r1.md F1 — is gone; the real one lives in `cases.receipt`
    # itself now.
    batch_result = {
        "sheet": sheet_name,
        "sheet_sha": result.sheet_sha,
        "stopped_at": result.stopped_at,
        "code": result.process_code,
        "stop_message": result.stop_message,
        "items": [
            item
            for item in result.to_json()["items"]
            if not prefix or item["n"] not in result.preserved_receipt_items
        ],
        # Fold r1 (F2): threaded through for future readers -- `cases.
        # receipt` reads only the keys named in its own docstring and
        # ignores this one, so the section-5 line format is unchanged.
        "actor": result.actor,
        "prefix": prefix,
    }
    if prefix and result.items and not batch_result["items"]:
        # Every ordinal already carries its committed Application line (the
        # ordered checkpoint receipted each one as it landed), so the final
        # prefix receipt has nothing to append. Returning here matters: an
        # empty item list is also the shape `cases.receipt` renders as a
        # whole-sheet "refused before item 1" line, and a completed sheet
        # must never gain that line (observed by hand 2026-09-14, O-3).
        return {"state": "ok", "pushed": None}
    try:
        cases.receipt(home, result.case, batch_result)
    except (cases.CaseError, gitops.GitOpsError) as exc:
        # F2: a receipt failure is a bookkeeping append failing AFTER
        # the batch's own decision already landed — it must NEVER
        # rewrite the batch's own documented exit code (S-54: "1 is
        # emitted only when nothing landed"; by the time this can fail,
        # the batch has already decided its own code).
        print(f"self-learn batch: case receipt: {exc}", file=sys.stderr)
        return {"state": "failed", "reason": str(exc)}
    pushed = None
    if not no_push:
        # F6: the receipt's own commit rides OUTSIDE `run`'s single
        # push — it lands strictly AFTER that push already returned, so
        # it is never published by it. Publish it under the SAME
        # `--no-push` rule the sheet's own commits already followed.
        # `push_pending` takes no sentinel/lock of its own (read-only
        # w.r.t. records — the same call `run` itself makes).
        pushed = verbs.push_pending(home).ok
    return {"state": "ok", "pushed": pushed}
