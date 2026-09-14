"""O-1 — the overseer's blind population listing, coverage nudges, and
coverage record (`03-decisions.md` S-66; `02-schema.md` §3a.2's blind
view; `13-hosting-and-separation.md` §3's `<ledger>/overseer/` subtree;
`misc/audit-2026-09-02/steward-design/plan-overseer-2026-09-12.md` §O-1,
§4.1, §4.5; the stratum count is `folds/fold-j0-r1.md` F2, superseding
this plan's own older seven-name list).

The overseer chooses which of the week's cases to examine and how many;
this module renders the population BLIND (no verbs, no outcomes) so the
choice is made from evidence, not from the steward's own conclusion, and
keeps a persisted coverage record so "uninspected" stays distinguishable
from "healthy" week to week. Nothing here rations: no sample size, no
reserve, no upper bound on how many cases it examines (user decision D5,
`03-decisions.md` S-66).

Pure module — no ledger writes. `coverage.yaml` is written by the
overseer's RUNNER (O-3) inside its own `intents.ledger_write` span; this
module only computes the dict (`coverage_update`) and renders/loads its
YAML text (`render_coverage`/`load_coverage`).

**Spec/brief disagreement, recorded rather than resolved (common-builder-
rules.md: "the spec wins; do not resolve it yourself")**: the builder
brief (build-o1.md §`coverage_update`) asks this function to carry "the
model's stated reason for the selection and for stopping" in the
returned dict. `02-schema.md` §3a.1 item 2 states plainly: "`coverage.yaml`
and `open-questions.yaml` carry no free text at all (structured records
only)". This module follows the spec: `coverage_update` never copies
`why_these`/`why_stopped` prose out of `selection_yaml` into the returned
dict. The plan's own report template (§4.2) already carries "why these,
why it stopped" in the *report's* "Examined" section header — that prose
belongs to O-3's report-writing, not to this structured record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import cases as cases_mod
from ..ledger import discover_buckets
from ..ledger_ops import LedgerOpsError, bucket_project_path, find_record_path, record_title
from ..primitives import chrono
from ..primitives import fsops
from ..primitives.yamlio import rt_yaml
from ..records import Record, RecordError
from ..report import recurrence_suspects
from .. import telemetry
from .. import user_model as user_model_mod

__all__ = [
    "OUTCOMES",
    "SCOPE_KINDS",
    "BlindCase",
    "BlindRecordRef",
    "coverage_update",
    "load_coverage",
    "nudges",
    "population",
    "render_coverage",
    "render_population",
    "stratum_key",
    "write_blind_views",
]

#: The nine case outcomes, `02-schema.md` §3a.2 frontmatter closed set.
OUTCOMES = (
    "route", "reject", "defer", "retire", "replaced",
    "rehome", "revise", "no-action", "parked",
)

#: The three scope kinds a record's own `scope` property carries
#: (`records.py`'s `_validate_scope`: "user" | "project" | "skill:<name>",
#: bucketed to its kind here) — `folds/fold-j0-r1.md` F2: nine outcomes ×
#: three scopes = 27 coverage cells.
SCOPE_KINDS = ("user", "project", "skill")

_SCOPE_LINE_RE = re.compile(r"^- scope:\s*(.*)$", re.MULTILINE)


def stratum_key(outcome: str, scope_kind: str) -> str:
    """The coverage record's own key for one (outcome, scope) cell."""
    return f"{outcome}/{scope_kind}"


# ------------------------------------------------------------ data shapes


@dataclass(frozen=True)
class BlindRecordRef:
    """One record cited by a case, blind: an id and its headline (the
    first line of its Trigger/Fact section — `ledger_ops.record_title`),
    never its scope, status, or body."""

    id: str
    headline: str

    def to_dict(self) -> dict:
        return {"id": self.id, "headline": self.headline}


@dataclass(frozen=True)
class BlindCase:
    """One line of the blind population listing (build-o1.md §Code):
    `case, opened_at, records (ids + headlines), scope, kind` — NOT
    `outcome`, NOT section 3 (Decision), NOT receipts. `scope` here is
    the case's OWN free-text scope (section 1's `- scope:` line, part of
    the blind view's allowed sections) — a human-readable label for the
    overseer's listing, distinct from the per-record `scope` KIND used
    to bucket the coverage stratum (`_record_scope_kind`, coverage-only,
    never rendered in this listing)."""

    case: str
    opened_at: str | None
    records: tuple[BlindRecordRef, ...]
    scope: str | None
    kind: str | None

    def to_dict(self) -> dict:
        return {
            "case": self.case,
            "opened_at": self.opened_at,
            "records": [r.to_dict() for r in self.records],
            "scope": self.scope,
            "kind": self.kind,
        }


# ------------------------------------------------------- record lookups


def _scope_kind(scope: str) -> str:
    """A record's controlled `scope` property ("user" | "project" |
    "skill:<name>") bucketed to its coverage-stratum kind."""
    return "skill" if scope.startswith("skill:") else scope


def _record_ref(home: Path, record_id: str) -> BlindRecordRef:
    """(id, headline) for one cited record — id-only, no scope/status/
    body. Degrades to an empty headline rather than raising: one
    deleted/corrupt record must never hide the whole case listing (the
    same discipline `cases._index_row` and `miner._find_record` already
    use for this exact class of failure)."""
    try:
        path = find_record_path(home, record_id)
        record = Record.from_path(path)
    except (LedgerOpsError, RecordError, OSError, UnicodeDecodeError):
        return BlindRecordRef(id=record_id, headline="")
    return BlindRecordRef(id=record_id, headline=record_title(record))


def _record_scope_kind(home: Path, record_id: str) -> str | None:
    """The FIRST record's scope kind, for the coverage stratum only —
    never rendered in the blind listing. `None` when the record cannot
    be read; the caller falls back to the case's own free-text scope."""
    try:
        path = find_record_path(home, record_id)
        record = Record.from_path(path)
    except (LedgerOpsError, RecordError, OSError, UnicodeDecodeError):
        return None
    return _scope_kind(record.scope)


def _scope_text_from_view(sections: dict[str, str]) -> str | None:
    """Parse the `- scope: <text>` line out of the blind view's own
    "Identity and scope" section body (`cases._render_identity`'s
    format) — this is section-1 body text, allowed in the blind view
    (`02-schema.md` §3a.2, amended 2026-09-14)."""
    body = sections.get("Identity and scope", "")
    m = _SCOPE_LINE_RE.search(body)
    return m.group(1).strip() if m else None


def _scope_kind_from_text(text: str | None) -> str:
    """Best-effort classification of a case's own free-text scope into
    one of the three coverage-stratum kinds, used ONLY when the
    underlying record can't be read (`_record_scope_kind` returned
    `None`) — never crashes, never produces a fourth key. `project` is
    the default: the stage schema's own worked example
    (`test_cases.py::STAGE_BASE`) writes scope as a path-shaped string
    ("project:~/.config"), and a case whose scope text is unclassifiable
    is far more likely to be project-shaped free text than a skill or
    user one-word label."""
    t = (text or "").strip()
    if t.startswith("skill:"):
        return "skill"
    if t == "user" or t.startswith("user:") or t.startswith("user "):
        return "user"
    return "project"


# ------------------------------------------------------------- population


def population(home: Path | str, since: str) -> list[BlindCase]:
    """The week's cases, BLIND: via `cases.list_cases` for the case set
    (`case, opened_at, kind, records[]`), plus the blind view
    (`cases.show(..., evidence_only=True)`) for each case's own free-text
    `scope` (section 1 body, in the blind view's allowed sections) — the
    stratum (outcome × scope-kind) is NOT computed here and NEVER
    rendered: it exists only for `coverage_update`, downstream, once the
    outcome is no longer being withheld.

    A case whose freeze hash failed re-verification (`frozen_ok: false`
    in the index row) still appears in the listing (S6: "one corrupt
    case must never hide the whole population") but with `scope: None` —
    its section text cannot be trusted without a successful re-hash, and
    `cases.show` refuses to return it."""
    home = Path(home)
    rows = cases_mod.list_cases(home, since=since)
    out: list[BlindCase] = []
    for row in rows:
        case_id = row["case"]
        try:
            view = cases_mod.show(home, case_id, evidence_only=True)
            scope_text = _scope_text_from_view(view.sections)
        except cases_mod.CaseError:
            scope_text = None
        refs = tuple(_record_ref(home, rid) for rid in (row.get("records") or []))
        out.append(
            BlindCase(
                case=case_id,
                opened_at=row.get("opened_at"),
                records=refs,
                scope=scope_text,
                kind=row.get("kind"),
            )
        )
    return out


def render_population(population_cases: list[BlindCase]) -> str:
    """One line per case — `case, opened_at, records (ids and
    headlines), scope, kind` and nothing else (plan §O-1)."""
    lines = []
    for bc in population_cases:
        records_text = ", ".join(f"{r.id} ({r.headline})" if r.headline else r.id for r in bc.records)
        lines.append(
            f"{bc.case}  opened={bc.opened_at}  scope={bc.scope}  kind={bc.kind}  "
            f"records=[{records_text}]"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def write_blind_views(
    home: Path | str, stage_dir: Path | str, population_cases: list[BlindCase]
) -> dict[str, list[str]]:
    """One blind evidence-view file per case of the week (parked cases
    included — the population is not filtered by kind), via
    `cases.show(..., evidence_only=True)`, rendered with `CaseView`'s own
    `to_text()` (never a second renderer for the same allowlisted view).
    Returns `{"written": [case ids], "skipped": [case ids]}` — a case
    whose freeze hash fails re-verification is skipped, not crashed on
    (same S6 discipline as `population`); the runner (O-3) decides what
    a non-empty `skipped` list means for that week's run."""
    home = Path(home)
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    skipped: list[str] = []
    for bc in population_cases:
        try:
            view = cases_mod.show(home, bc.case, evidence_only=True)
        except cases_mod.CaseError:
            skipped.append(bc.case)
            continue
        path = stage_dir / f"{bc.case}.md"
        fsops.atomic_write(path, view.to_text() + "\n")
        written.append(bc.case)
    return {"written": written, "skipped": skipped}


# ------------------------------------------------------------------ nudges


def _stratum_nudges(coverage: dict) -> list[dict]:
    """Strata not examined for the longest time first (plan §4.5): sort
    by `last_examined_at` ascending, `None` (never examined) first, tied
    entries broken by the stratum key for a deterministic order."""
    strata = (coverage or {}).get("strata") or {}
    rows = []
    for key, entry in strata.items():
        rows.append((key, entry.get("last_examined_at")))

    def _sort_key(item):
        key, last = item
        dt = chrono.to_dt(last) if last else None
        # `None` sorts first: pair a boolean (False < True) with the
        # datetime so a never-examined stratum always precedes a
        # dated one, and dated ones sort ascending (oldest first).
        return (dt is not None, dt or datetime.min.replace(tzinfo=timezone.utc), key)

    rows.sort(key=_sort_key)
    return [{"kind": "stratum", "key": key, "last_examined_at": last} for key, last in rows]


def _recurrence_nudges(home: Path) -> list[dict]:
    """Recurrence suspects with basis (`report.recurrence_suspects`,
    `11-telemetry-and-lifecycle.md` §2.2) — a pass-through, never a
    re-derivation (`report.py:234`'s own docstring)."""
    try:
        rows = recurrence_suspects(home)
    except Exception:
        return []
    return [
        {"kind": "recurrence-suspect", "id": r["id"], "nonce": r["nonce"], "basis": r.get("basis")}
        for r in rows
    ]


def _always_loaded_zero_fire_nudges(home: Path, week: str) -> list[dict]:
    """Always-loaded lessons (routed, `scope: user` — the ones compiled
    into `~/.claude/CLAUDE.md`'s managed section, in context on every
    turn) with zero `fire` telemetry events since *week*. Best-effort:
    any read failure (missing bucket, unreadable telemetry) degrades to
    `[]`, never a crash — this is an information-only nudge (plan §4.5,
    "information, never forced draws")."""
    try:
        fired_ids: set[str] = set()
        for event in telemetry.read_events(home):
            if event.get("kind") != "fire":
                continue
            ts = event.get("ts")
            if isinstance(ts, str) and ts < week:
                continue
            rid = event.get("record")
            if isinstance(rid, str):
                fired_ids.add(rid)

        always_loaded: list[str] = []
        for bucket in discover_buckets(home):
            if bucket.scope != "user":
                continue
            resolved_dir = bucket.path / "resolved"
            if not resolved_dir.is_dir():
                continue
            for path in sorted(resolved_dir.glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                except (RecordError, OSError, UnicodeDecodeError):
                    continue
                if record.status == "routed":
                    always_loaded.append(record.id)
    except Exception:
        return []
    return [
        {"kind": "always-loaded-zero-fire", "id": rid}
        for rid in always_loaded
        if rid not in fired_ids
    ]


def _untouched_system_reading_nudges(home: Path) -> list[dict]:
    """System readings (`user_model.py` containers B/C — "System readings
    the user has seen" / "…, provisional", `02-schema.md` around line
    1035) whose `um-…` id appears in no case's `Dependencies` section
    (`dependency_refs[]` on the index row) — i.e. no examination has ever
    cited it. This is a documented best-effort proxy for "no examination
    has touched it": the index does not distinguish an examining
    overseer run from any other case that happens to depend on the same
    reading, so a reading cited by a steward's ordinary resolution case
    also counts as touched here."""
    try:
        doc = user_model_mod.show(home)
        containers = doc.get("containers") or {}
        readings = [*(containers.get("B") or []), *(containers.get("C") or [])]
        if not readings:
            return []
        cited: set[str] = set()
        for row in cases_mod.list_cases(home):
            for ref in row.get("dependency_refs") or []:
                if isinstance(ref, str) and ref.startswith("um-"):
                    cited.add(ref)
        return [
            {"kind": "system-reading-untouched", "id": e["id"]}
            for e in readings
            if e.get("id") not in cited
        ]
    except Exception:
        return []


def _worktree_bucket_nudges(home: Path) -> list[dict]:
    """Worktree-bucket captures (plan §2.4): a project bucket whose
    recorded path (`meta.yaml`) resolves under a `.claude/worktrees/`
    scratch directory rather than its enclosing main checkout — a
    known mis-homing exposure while FW-162 (worktree-to-parent-host
    resolution) is still open. This module always computes the list;
    whether the runner ACTS on it while FW-162 is open is the runner's
    (O-3's) gate, not this pure module's."""
    try:
        out = []
        for bucket in discover_buckets(home):
            if bucket.scope != "project":
                continue
            path = bucket_project_path(bucket.path)
            if path is not None and "/.claude/worktrees/" in path.as_posix():
                out.append({"kind": "worktree-bucket", "bucket": bucket.name, "path": str(path)})
        return out
    except Exception:
        return []


def nudges(home: Path | str, coverage: dict, week: str) -> list[dict]:
    """Coverage nudges — information only, NEVER forced draws (plan
    §4.5). Order: strata not examined for the longest time first, then
    recurrence suspects, always-loaded zero-fire lessons, untouched
    system readings, and worktree-bucket captures (build-o1.md §Code's
    own listed order)."""
    home = Path(home)
    out: list[dict] = []
    out.extend(_stratum_nudges(coverage))
    out.extend(_recurrence_nudges(home))
    out.extend(_always_loaded_zero_fire_nudges(home, week))
    out.extend(_untouched_system_reading_nudges(home))
    out.extend(_worktree_bucket_nudges(home))
    return out


# --------------------------------------------------------------- coverage


def _empty_strata() -> dict[str, dict]:
    return {
        stratum_key(outcome, scope): {
            "outcome": outcome,
            "scope": scope,
            "cumulative_count": 0,
            "last_examined_at": None,
            "status": "empty",
        }
        for outcome in OUTCOMES
        for scope in SCOPE_KINDS
    }


def _empty_coverage() -> dict:
    return {"strata": _empty_strata(), "nudges_offered": [], "nudges_taken": []}


def load_coverage(path: Path | str) -> dict:
    """Read `coverage.yaml`; a missing file is the empty structure (every
    stratum `empty`, zero cumulative counts), never `None` — O-3's first
    run has nothing to merge against yet."""
    path = Path(path)
    if not path.exists():
        return _empty_coverage()
    y = rt_yaml(default_flow_style=False)
    with path.open("r", encoding="utf-8") as fh:
        data = y.load(fh) or {}
    strata = dict(data.get("strata") or {})
    # Fill in any cell the file doesn't (yet) carry — a hand-edited or
    # older-shaped file must never make `coverage_update` produce fewer
    # than the 27 fixed keys.
    for key, default in _empty_strata().items():
        strata.setdefault(key, default)
    return {
        "strata": strata,
        "nudges_offered": list(data.get("nudges_offered") or []),
        "nudges_taken": list(data.get("nudges_taken") or []),
    }


def render_coverage(data: dict) -> str:
    """`coverage.yaml`'s text — structured records only, no free text
    (`02-schema.md` §3a.1 item 2). Strata are emitted in the fixed
    outcome-then-scope order (`_empty_strata`'s own iteration), never a
    dict's insertion order, so the file's diff each week is the actual
    change, not key reordering."""
    ordered = {
        "strata": {key: data.get("strata", {}).get(key, default) for key, default in _empty_strata().items()},
        "nudges_offered": list(data.get("nudges_offered") or []),
        "nudges_taken": list(data.get("nudges_taken") or []),
    }
    y = rt_yaml(default_flow_style=False)
    import io

    buf = io.StringIO()
    y.dump(ordered, buf)
    return buf.getvalue()


def _stratum_for_case(home: Path, row: dict) -> str:
    """The stratum key for one FULL case row (carries `outcome`, unlike
    the blind listing's `BlindCase`) — never trusts a `stratum` key a
    model might have written into `selection.yaml` (test 3): always
    recomputed from the row's own `outcome` plus the first cited
    record's scope kind, falling back to the case's own free-text scope
    only when the record can't be read."""
    outcome = row.get("outcome")
    if outcome not in OUTCOMES:
        # An unrecognized/missing outcome (a malformed row, a case kind
        # this coverage record doesn't track) never crashes the merge
        # and never grows a 28th stratum — dropped from accounting,
        # same "degrade, don't hide the rest" discipline as `_index_row`.
        return ""
    records = row.get("records") or []
    scope_kind = None
    if records:
        scope_kind = _record_scope_kind(home, records[0])
    if scope_kind is None:
        scope_kind = _scope_kind_from_text(row.get("scope"))
    return stratum_key(outcome, scope_kind)


def coverage_update(
    previous: dict | None,
    selection_yaml: dict,
    cases: list[dict],
    *,
    now: datetime | None = None,
    home: Path | str | None = None,
) -> dict:
    """Compute the next `coverage.yaml` dict from the PREVIOUS record,
    the model's `selection.yaml` (only its list of chosen case ids is
    trusted — `test 3`), and *cases*: the FULL (non-blind) case index
    rows for the week's population (`cases.list_cases`'s own shape,
    carrying `outcome`) — the blind `BlindCase` list from `population()`
    deliberately does not carry `outcome`, so it cannot answer this
    function's question.

    Per stratum: `last_examined_at` and `cumulative_count` are MERGED,
    never overwritten — a stratum with no examined case this run keeps
    whatever the previous record already had (test 5). A stratum with
    zero members in THIS WEEK'S population is recorded `empty`, not
    dropped (test 4); one with members but none of them selected is
    `unexamined`; one with an examined case is `examined`, its
    cumulative count incremented by the number of examined cases in that
    cell this run and its `last_examined_at` set to *now*.

    `home` resolves each case's record scope for stratum bucketing
    (`_stratum_for_case`); omit it only when every row's own `scope`
    text is enough (falls back to `_scope_kind_from_text`, degrading
    gracefully — see that function's docstring).

    Per the module docstring's recorded spec/brief disagreement, this
    function does NOT copy `selection_yaml`'s `why_these`/`why_stopped`
    prose into the returned dict — `02-schema.md` §3a.1 item 2 rules
    `coverage.yaml` "no free text at all"."""
    now_dt = now or datetime.now(timezone.utc)
    now_iso = chrono.now_iso(now_dt)
    prev = previous if previous is not None else _empty_coverage()
    prev_strata = dict(prev.get("strata") or {})
    for key, default in _empty_strata().items():
        prev_strata.setdefault(key, default)

    selected_ids = {
        c.get("id") if isinstance(c, dict) else c
        for c in (selection_yaml.get("cases") or [])
    }
    selected_ids.discard(None)

    home_path = Path(home) if home is not None else None
    members_by_stratum: dict[str, list[dict]] = {key: [] for key in prev_strata}
    for row in cases:
        key = _stratum_for_case(home_path, row) if home_path is not None else ""
        if not key or key not in members_by_stratum:
            continue
        members_by_stratum[key].append(row)

    new_strata: dict[str, dict] = {}
    for key, prev_entry in prev_strata.items():
        outcome, _, scope = key.partition("/")
        members = members_by_stratum.get(key, [])
        examined = [m for m in members if m.get("case") in selected_ids]
        if examined:
            new_strata[key] = {
                "outcome": outcome,
                "scope": scope,
                "cumulative_count": int(prev_entry.get("cumulative_count") or 0) + len(examined),
                "last_examined_at": now_iso,
                "status": "examined",
            }
        elif members:
            new_strata[key] = {
                "outcome": outcome,
                "scope": scope,
                "cumulative_count": int(prev_entry.get("cumulative_count") or 0),
                "last_examined_at": prev_entry.get("last_examined_at"),
                "status": "unexamined",
            }
        else:
            new_strata[key] = {
                "outcome": outcome,
                "scope": scope,
                "cumulative_count": int(prev_entry.get("cumulative_count") or 0),
                "last_examined_at": prev_entry.get("last_examined_at"),
                "status": "empty",
            }

    offered = list(selection_yaml.get("nudges_offered") or [])
    taken = []
    for nudge in offered:
        if not isinstance(nudge, dict):
            continue
        if nudge.get("kind") == "stratum":
            nudge_key = nudge.get("key")
            if isinstance(nudge_key, str) and new_strata.get(nudge_key, {}).get("status") == "examined":
                taken.append(nudge)
        elif nudge.get("id") in {
            rid
            for row in cases
            if row.get("case") in selected_ids
            for rid in (row.get("records") or [])
        }:
            taken.append(nudge)

    return {"strata": new_strata, "nudges_offered": offered, "nudges_taken": taken}
