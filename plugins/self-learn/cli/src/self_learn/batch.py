"""``self-learn batch`` — apply a decision sheet in one locked run
(U-verbs §3.3/§4.4). The review skill's apply path; no review session
ever hand-writes another bash script (S-54).

Public surface:

    load_sheet(path) -> list[SheetItem]      # BAT1: validated WHOLE, or raises
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

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML

from . import gitops, sentinel, verbs
from .chezmoi import ChezmoiAbort, ChezmoiError
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
from .records import RECORD_ID_RE, Record

__all__ = [
    "PERMITTED_KEYS",
    "PERMITTED_VERBS",
    "REFUSED_HOOK_DESTINATION",
    "BatchError",
    "BatchResult",
    "DryRunItem",
    "DryRunResult",
    "ItemResult",
    "SheetItem",
    "classify",
    "decision_code",
    "dry_run",
    "load_sheet",
    "run",
]

#: U-verbs §4.4 — the 15 Phase-1 permitted verbs and the item keys each
#: accepts beyond ``id``/``verb``. Phase 2 is NOT in this build (PH1: a
#: Phase-1 module names no Phase-2 symbol) — a sheet naming a Phase-2
#: verb is refused the same as any other unknown verb, exit 64.
PERMITTED_KEYS: dict[str, frozenset[str]] = {
    "route": frozenset(
        {
            "dest", "collapse", "by", "follow_up", "unblocks_on",
            "follow_up_note", "allow_empty_glob", "note",
        }
    ),
    "reject": frozenset({"note"}),
    "defer": frozenset({"until", "note"}),
    "undefer": frozenset({"note"}),
    "reopen": frozenset({"note"}),
    "graduate": frozenset({"note"}),
    "supersede": frozenset({"new_id", "note"}),
    "rehome": frozenset({"to", "note"}),
    "rescope": frozenset({"to", "note"}),
    "note": frozenset({"append", "key"}),
    "confirm-recurrence": frozenset({"event", "tolerate", "note"}),
    "dismiss-suspect": frozenset({"event", "why", "note"}),
    "confirm-held": frozenset({"note"}),
    "link-contradicts": frozenset({"target", "note"}),
    "followup-done": frozenset({"note"}),
}
PERMITTED_VERBS = frozenset(PERMITTED_KEYS)

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


@dataclass
class ItemResult:
    n: int
    id: str
    verb: str
    rc: int
    sha: str | None = None
    state: str = "applied"  # applied | already-applied | refused | stopped
    detail: str | None = None


@dataclass
class BatchResult:
    items: list[ItemResult] = field(default_factory=list)
    stopped_at: int | None = None
    flush_sha: str | None = None
    pushed: bool = False
    process_code: int = 0

    @property
    def summary(self) -> dict:
        applied = sum(1 for i in self.items if i.state == "applied")
        already = sum(1 for i in self.items if i.state == "already-applied")
        refused = sum(1 for i in self.items if i.state == "refused")
        return {
            "applied": applied,
            "already_applied": already,
            "refused": refused,
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
            "pushed": self.pushed,
            "process_code": self.process_code,
        }


def load_sheet(path: Path | str) -> list[SheetItem]:
    """Parse + validate a sheet WHOLE (BAT1): an unknown verb, an unknown
    item key, a malformed id, or ``version != 1`` raises — nothing runs."""
    path = Path(path)
    yaml = YAML(typ="safe")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BatchError(f"batch: cannot read {path}: {exc}") from exc
    try:
        data = yaml.load(text)
    except Exception as exc:  # noqa: BLE001 — any YAML parse failure is a sheet error
        raise BatchError(f"batch {path}: unreadable YAML — {exc}") from exc
    if not isinstance(data, dict):
        raise BatchError(f"batch {path}: sheet must be a mapping")
    if data.get("version") != 1:
        raise BatchError(
            f"batch {path}: version must be 1, got {data.get('version')!r}"
        )
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise BatchError(f"batch {path}: items must be a non-empty list")

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
        fields = {k: v for k, v in raw.items() if k not in ("id", "verb")}
        items.append(SheetItem(n=n, id=rid, verb=verb, fields=fields))
    return items


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
        if f.get("dest") is None:
            # No explicit --dest on the sheet line: the ORIGINAL
            # resolution came from the proposal sibling, which a
            # successful route already SWEEPS (remove_proposal_siblings)
            # -- so re-resolving it on a re-run would spuriously refuse
            # with NoProposalError, not "already applied". A routed
            # status is itself sufficient here: there is no further
            # destination to cross-check against.
            return True
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
            and record.superseded_by == f.get("new_id")
        )
    if verb in ("rehome", "rescope"):
        to = f.get("to")
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
        event = f.get("event")
        return any(r.get("ref") == event for r in record.recurrences)
    if verb == "dismiss-suspect":
        event = f.get("event")
        return any(d.get("ref") == event for d in record.dismissed_suspects)
    if verb == "confirm-held":
        return record.last_confirmed is not None
    if verb == "link-contradicts":
        target = f.get("target")
        return target in record.contradicts
    if verb == "followup-done":
        return record.follow_up is None and record.follow_up_done is not None
    return False  # pragma: no cover — unreachable: load_sheet already gated the verb


def _dispatch(home: Path, item: SheetItem) -> ItemResult:
    """Call the SAME ``verbs.*`` function the CLI calls, with
    ``no_push=True``, inside that verb's own ``_ledger_write`` span,
    catching the SAME exception set ``cli._cmd_verb`` catches and mapping
    it to the SAME integer."""
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
            result = verbs.reject(home, item.id, note=f.get("note"), no_push=True)
        elif verb == "defer":
            until = f.get("until")
            result = verbs.defer(
                home, item.id, until=until, note=f.get("note"), no_push=True
            )
        elif verb == "undefer":
            result = verbs.undefer(home, item.id, note=f.get("note"), no_push=True)
        elif verb == "reopen":
            result = verbs.reopen(home, item.id, note=f.get("note"), no_push=True)
        elif verb == "graduate":
            result = verbs.graduate(home, item.id, note=f.get("note"), no_push=True)
        elif verb == "supersede":
            result = verbs.supersede(
                home, item.id, f.get("new_id"), note=f.get("note"), no_push=True
            )
        elif verb == "rehome":
            result = verbs.rehome(
                home, item.id, to=f.get("to"), note=f.get("note"), no_push=True
            )
        elif verb == "rescope":
            result = verbs.rescope(
                home, item.id, to=f.get("to"), note=f.get("note"), no_push=True
            )
        elif verb == "note":
            result = verbs.note(
                home, item.id, append=f.get("append"), key=f.get("key"),
                no_push=True,
            )
        elif verb == "confirm-recurrence":
            result = verbs.confirm_recurrence(
                home, item.id, event_ref=f.get("event"),
                tolerate=bool(f.get("tolerate", False)), note=f.get("note"),
                no_push=True,
            )
        elif verb == "dismiss-suspect":
            result = verbs.dismiss_suspect(
                home, item.id, event_ref=f.get("event"), why=f.get("why"),
                note=f.get("note"), no_push=True,
            )
        elif verb == "confirm-held":
            result = verbs.confirm_held(home, item.id, note=f.get("note"), no_push=True)
        elif verb == "link-contradicts":
            result = verbs.link_contradicts(
                home, item.id, f.get("target"), note=f.get("note"), no_push=True
            )
        elif verb == "followup-done":
            result = verbs.followup_done(home, item.id, note=f.get("note"), no_push=True)
        else:  # pragma: no cover — load_sheet already gated the verb set
            raise AssertionError(f"unreachable: unpermitted verb {verb!r}")
    except verbs.VerbError as exc:  # incl. SecretRefusal
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=exc.exit_code,
                           state="refused", detail=str(exc))
    except LedgerOpsError as exc:
        return ItemResult(n=item.n, id=item.id, verb=verb, rc=64,
                           state="refused", detail=str(exc))
    except (CompileError, ChezmoiAbort, ChezmoiError) as exc:
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

    1. a ledger-level failure occurred (an item returned 3, 4, 6 or 7) →
       the WORST of those four, under ``7 > 4 > 3 > 6``;
    2. every item applied or already-applied → 0;
    3. ≥1 refusal AND ≥1 commit landed → 8 (EXIT_BATCH_PARTIAL);
    4. ≥1 refusal, ZERO commits → 1 — `1`'s ratified meaning (refused,
       nothing written) is never emitted after a write."""
    ledger_level = [r.rc for r in results if r.rc in (3, 4, 6, 7)]
    if ledger_level:
        for code in (7, 4, 3, 6):
            if code in ledger_level:
                return code
    landed = any(r.state == "applied" for r in results)
    refused = any(r.state == "refused" for r in results)
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
    result = DryRunResult()
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
                verbs._resolve_move_target(home, item.fields.get("to"))
            except verbs.VerbError as exc:
                result.items.append(
                    DryRunItem(n=item.n, id=item.id, verb=item.verb,
                               state="would-refuse", detail=str(exc))
                )
                continue
        record = Record.from_path(path)
        gate = _STATUS_GATE.get(item.verb)
        if gate is not None and record.status not in gate:
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
    result = BatchResult()
    push_exit: int | None = None
    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        for item in items:
            if classify(home, item):
                result.items.append(
                    ItemResult(n=item.n, id=item.id, verb=item.verb, rc=0,
                               state="already-applied")
                )
                continue
            item_result = _dispatch(home, item)
            result.items.append(item_result)
            sentinel.heartbeat()
            if item_result.rc in _STOP_CODES:
                result.stopped_at = item.n
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
