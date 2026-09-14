"""``self-learn batch`` — apply a decision sheet in one locked run
(U-verbs §3.3/§4.4). The review skill's apply path; no review session
ever hand-writes another bash script (S-54).

Public surface:

    load_sheet(path, *, home=None) -> Sheet  # BAT1: validated WHOLE, or raises
    classify(home, item) -> bool             # True iff already-applied (§3.3b)
    run(home, items, *, dry_run=False, no_push=False) -> BatchResult

``run`` holds the sentinel ONCE (the owning hold), dispatches each item to
the SAME ``verbs.*`` function the CLI dispatches to (``no_push=True``,
inside that verb's own ``_ledger_write`` span), classifies
already-applied items as a STATE READ and skips them without calling the
verb, stops on the first ledger-level failure (5/6/7), flushes exactly
once through ``cli._mutating_epilogue`` (§3.3c — the ONE remaining call
site), and pushes once at the end.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML

from . import cases, gitops, intents, sentinel, verbs
from .cases import CASE_ID_RE
from .compilers import CompileError
from .ledger_ops import (
    DEFERRED_ONLY,
    LIVE_STATUSES,
    REOPENABLE_STATUSES,
    RESOLVABLE_STATUSES,
    ROUTED_ONLY,
    LedgerOpsError,
    find_record_path,
)
from .records import RECORD_ID_RE, MutationError, Record, RecordError

__all__ = [
    "PERMITTED_KEYS",
    "PERMITTED_VERBS",
    "REFUSED_HOOK_DESTINATION",
    "BatchError",
    "BatchResult",
    "DryRunItem",
    "DryRunResult",
    "ItemResult",
    "Sheet",
    "SheetItem",
    "classify",
    "decision_code",
    "dry_run",
    "load_sheet",
    "run",
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
    "graduate": frozenset({"note", "by"}),
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
        self, iterable=(), *, case: str | None = None, sheet_sha: str | None = None
    ) -> None:
        super().__init__(iterable)
        self.case = case
        self.sheet_sha = sheet_sha


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
    state: str = "applied"  # applied | already-applied | refused | stopped | not-attempted
    detail: str | None = None


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
    sheet_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
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
    return Sheet(items, case=case, sheet_sha=sheet_sha)


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


def classify(home: Path, item: SheetItem) -> bool:
    """True iff *item* is ALREADY-APPLIED (§3.3b) — a STATE READ, never
    a parse of a refusal message. An unresolvable record id is never
    already-applied — it surfaces as the item's own refusal at dispatch."""
    try:
        path = find_record_path(home, item.id)
    except LedgerOpsError:
        return False
    record = Record.from_path(path)
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
    if verb == "graduate":
        return record.status == "superseded" and record.superseded_by == "canon"
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


#: U5 fold r1 (F1): the ONLY verbs `_dispatch` ever forwards
#: `reconsider_case` to — one set, consulted by BOTH
#: `_reconsider_case_for` (below) and `dry_run`'s own status-gate
#: preview, so the two can never drift apart again. Before this fix
#: `_reconsider_case_for` decided purely on the RECORD's status, never
#: the VERB — `dry_run` previewed `would-apply` for `revise`/`rescope`/
#: `rehome` against a routed record under a valid reconsider case even
#: though `_dispatch` never forwards `reconsider_case` to any of the
#: three (they gained no such parameter) and the real run refused.
_RECONSIDER_FORWARDING_VERBS = frozenset({"reject", "defer", "graduate", "supersede"})


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


def _dispatch(home: Path, item: SheetItem, *, case: str | None = None) -> ItemResult:
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
    naming which check failed — no separate refusal lives here."""
    verb = item.verb
    f = item.fields
    try:
        if verb == "route":
            if _resolved_route_dest(home, find_record_path(home, item.id), item) == (
                REFUSED_HOOK_DESTINATION, None,
            ):
                raise verbs.VerbError(
                    f"{item.id}: a hook route is refused inside a batch "
                    "(S-29) — route it by hand"
                )
            follow_up = None
            if f.get("follow_up") is not None:
                follow_up = {"action": f["follow_up"]}
                if f.get("unblocks_on") is not None:
                    follow_up["unblocks_on"] = f["unblocks_on"]
                if f.get("follow_up_note") is not None:
                    follow_up["note"] = f["follow_up_note"]
            result = verbs.route(
                home, item.id, dest=f.get("dest"), by=f.get("by"),
                note=f.get("note"), no_push=True, follow_up=follow_up,
                collapse=f.get("collapse"),
                allow_empty_glob=bool(f.get("allow_empty_glob", False)),
            )
        elif verb == "reject":
            result = verbs.reject(
                home, item.id, note=f.get("note"), by=f.get("by"), no_push=True,
                reconsider_case=_reconsider_case_for(home, item.id, case, verb),
            )
        elif verb == "defer":
            until = f.get("until")
            result = verbs.defer(
                home, item.id, until=until, note=f.get("note"), by=f.get("by"),
                no_push=True,
                reconsider_case=_reconsider_case_for(home, item.id, case, verb),
            )
        elif verb == "undefer":
            result = verbs.undefer(
                home, item.id, note=f.get("note"), by=f.get("by"), no_push=True
            )
        elif verb == "reopen":
            result = verbs.reopen(
                home, item.id, note=f.get("note"), by=f.get("by"), no_push=True
            )
        elif verb == "graduate":
            result = verbs.graduate(
                home, item.id, note=f.get("note"), by=f.get("by"), no_push=True,
                reconsider_case=_reconsider_case_for(home, item.id, case, verb),
            )
        elif verb == "supersede":
            result = verbs.supersede(
                home, item.id, f["new_id"], note=f.get("note"), by=f.get("by"),
                no_push=True,
                reconsider_case=_reconsider_case_for(home, item.id, case, verb),
            )
        elif verb == "rehome":
            result = verbs.rehome(
                home, item.id, to=f["to"], note=f.get("note"), by=f.get("by"),
                no_push=True,
            )
        elif verb == "rescope":
            result = verbs.rescope(
                home, item.id, to=f["to"], note=f.get("note"), by=f.get("by"),
                no_push=True,
            )
        elif verb == "note":
            result = verbs.note(
                home, item.id, append=f["append"], key=f.get("key"),
                no_push=True,
            )
        elif verb == "confirm-recurrence":
            result = verbs.confirm_recurrence(
                home, item.id, event_ref=f["event"],
                tolerate=bool(f.get("tolerate", False)), note=f.get("note"),
                no_push=True,
            )
        elif verb == "dismiss-suspect":
            result = verbs.dismiss_suspect(
                home, item.id, event_ref=f["event"], why=f["why"],
                note=f.get("note"), no_push=True,
            )
        elif verb == "confirm-held":
            result = verbs.confirm_held(home, item.id, note=f.get("note"), no_push=True)
        elif verb == "link-contradicts":
            result = verbs.link_contradicts(
                home, item.id, f["target"], note=f.get("note"), no_push=True
            )
        elif verb == "followup-done":
            result = verbs.followup_done(home, item.id, note=f.get("note"), no_push=True)
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
                because=f["because"], by=f.get("by"), no_push=True,
            )
        else:  # pragma: no cover — load_sheet already gated the verb set
            raise AssertionError(f"unreachable: unpermitted verb {verb!r}")
    except verbs.VerbError as exc:  # incl. SecretRefusal
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=exc.exit_code,
                           state="refused", detail=str(exc))
    except LedgerOpsError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=64,
                           state="refused", detail=str(exc))
    except CompileError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=1,
                           state="refused", detail=str(exc))
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
                           state="refused", detail=str(exc))
    except gitops.HalfWrittenError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb,
                           rc=gitops.EXIT_HALF_WRITTEN, state="refused",
                           detail=str(exc))
    except gitops.GitOpsError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb,
                           rc=gitops.EXIT_GIT_FAILED, state="refused",
                           detail=str(exc))
    return ItemResult(
        n=item.n, id=item.id, verb=verb, rc=0, sha=result.commit_sha,
        state="applied",
    )


#: A pre-mutation ledger-level failure — nothing written, safe to retry
#: (§3.3: "the ledger is unsafe to keep writing into").
_STOP_CODES = frozenset({5, 6, 7})


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
    "reopen": REOPENABLE_STATUSES,
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

    @property
    def ok(self) -> bool:
        return not any(i.state == "would-refuse" for i in self.items)

    def to_json(self) -> dict:
        return {
            "items": [
                {
                    "n": i.n, "id": i.id, "verb": i.verb, "state": i.state,
                    "detail": i.detail, "route_preview": i.route_preview,
                }
                for i in self.items
            ],
            "hook_items": self.hook_items,
            "case": self.case,
            "sheet_sha": self.sheet_sha,
            "ok": self.ok,
        }


def dry_run(home: Path | str, items: list[SheetItem]) -> DryRunResult:
    """BAT9: writes nothing at all — ledger AND hosts. For a `route`
    item this is EXACTLY `route --dry-run`'s own payload, called as a
    function (the delegation leg) — no second preflight implementation.
    Every other verb reports its own status precondition
    (:data:`_STATUS_GATE`) with nothing written. `hook_items` names the
    sheet-level prerequisite the two hand scripts (§2.4) had to sequence
    by hand: a route item whose resolved destination is `hook`."""
    home = Path(home)
    sheet_case = getattr(items, "case", None)
    result = DryRunResult(
        case=sheet_case,
        sheet_sha=getattr(items, "sheet_sha", None),
    )
    for item in items:
        if classify(home, item):
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
                               state="would-refuse", detail=str(exc))
                )
                continue
            resolved = _resolved_route_dest(home, path, item)
            if resolved is not None and resolved[0] == REFUSED_HOOK_DESTINATION:
                result.hook_items.append(item.id)
            dr = verbs.route_dry_run(home, item.id, dest=item.fields.get("dest"))
            state = "would-refuse" if dr.would_refuse else "would-apply"
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb, state=state,
                           detail="; ".join(dr.would_refuse) or None,
                           route_preview=dr.to_json())
            )
            continue
        try:
            path = find_record_path(home, item.id)
        except LedgerOpsError as exc:
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb,
                           state="would-refuse", detail=str(exc))
            )
            continue
        if item.verb in ("rehome", "rescope"):
            try:
                verbs._resolve_move_target(home, item.fields["to"])
            except verbs.VerbError as exc:
                result.items.append(
                    DryRunItem(n=item.n, id=item.id, verb=item.verb,
                               state="would-refuse", detail=str(exc))
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
            result.items.append(
                DryRunItem(n=item.n, id=item.id, verb=item.verb,
                           state="would-refuse",
                           detail=f"record {item.id} is {record.status!r}")
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
) -> BatchResult:
    """Apply *items* in one locked run (§4.4's procedure): ONE owning
    sentinel hold → heartbeat → per item, classify (skip if
    already-applied) or dispatch → stop on the first 5/6/7 → flush
    exactly once through ``cli._mutating_epilogue`` (§3.3c, the seventh
    and last call site) → one push unless ``no_push`` → release."""
    # Lazy import: `cli` imports THIS module for `_cmd_batch`, so a
    # module-level import here would be circular. `_mutating_epilogue`
    # is only ever needed once execution actually reaches this point.
    from . import cli as cli_mod

    home = Path(home)
    # U3: `items` is a `Sheet` when it came from `load_sheet`; a plain
    # `list[SheetItem]` (every pre-existing caller, incl. U4's own
    # `test_revise_then_route_sheet_applies_both`) has no `.case` and
    # gets `None` here, exactly today's behaviour.
    case = getattr(items, "case", None)
    sheet_sha = getattr(items, "sheet_sha", None)
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
        )
    result = BatchResult(
        case=case,
        sheet_sha=sheet_sha,
        recovered_rolled_forward=list(recovered.rolled_forward),
        recovered_restored=list(recovered.restored),
    )
    push_exit: int | None = None
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        for idx, item in enumerate(items):
            if classify(home, item):
                result.items.append(
                    ItemResult(n=item.n, id=item.id, verb=item.verb, rc=0,
                               state="already-applied")
                )
                continue
            item_result = _dispatch(home, item, case=case)
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
            result.items.append(item_result)
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
        cli_mod._mutating_epilogue(home, no_push=True)
        if not no_push:
            push = verbs.push_pending(home)
            result.pushed = True
            if not push.ok:
                push_exit = push.exit_code
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
