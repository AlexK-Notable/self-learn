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
only)" (amended 2026-09-24: an ask's `text` and `why` in
`open-questions.yaml` are free text now; `coverage.yaml` still carries
none). This module follows the spec: `coverage_update` never copies
`why_these`/`why_stopped` prose out of `selection_yaml` into the returned
dict — those two fields are the ONLY free text `selection.yaml` (the
model's own file, not `coverage.yaml`) is allowed to carry
(`_SELECTION_ALLOWED_KEYS`, O-1 fold r1 / gate ruling B2). The plan's own
report template (§4.2) already carries "why these, why it stopped" in the
*report's* "Examined" section header — that prose belongs to O-3's
report-writing, not to this structured record.

**O-1 fold r1** (gate findings B1, B2, B3, S1-S6, N1-N4): `home` is gone
from `coverage_update`'s signature — `cases._index_row` now computes and
caches each row's `scope_kind` (and `record_bucket`) once, at
index-build time, from the case's first cited record
(`cases._record_scope_and_bucket`); this module trusts that field as
given and refuses (`CoverageError`) rather than guess when it is
missing. `nudges_offered`/`nudges_taken` are validated per kind and never
read from the model's `selection.yaml` — the RUNNER passes through
whatever `nudges()` itself returned (gap 3 / B2).
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
    "CoverageError",
    "PopulationError",
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


class PopulationError(Exception):
    """This module refuses invalid INPUT (never a missing/corrupt case,
    which always degrades — S6). Never raised for ledger content itself:
    `overseer/**` truth is written by the runner (O-3), not here."""


class CoverageError(PopulationError):
    """`coverage_update`/`render_coverage` refuse: an unknown key in the
    model's `selection.yaml` (B2), a case row that cannot be classified
    into a stratum (B1/S1 — no guessed default), or an unknown top-level
    key in a coverage dict about to be rendered (N2)."""


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
    overseer's listing, distinct from the per-record `scope_kind` used
    to bucket the coverage stratum (`cases._index_row`'s own field,
    coverage-only, never rendered in this listing)."""

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


def _scope_text_from_view(sections: dict[str, str]) -> str | None:
    """Parse the `- scope: <text>` line out of the blind view's own
    "Identity and scope" section body (`cases._render_identity`'s
    format) — this is section-1 body text, allowed in the blind view
    (`02-schema.md` §3a.2, amended 2026-09-14)."""
    body = sections.get("Identity and scope", "")
    m = _SCOPE_LINE_RE.search(body)
    return m.group(1).strip() if m else None


# ------------------------------------------------------------- population


def population(home: Path | str, since: str) -> list[BlindCase]:
    """The week's cases, BLIND: via `cases.list_cases` for the case set
    (`case, opened_at, kind, records[]`), plus the blind view
    (`cases.show(..., evidence_only=True)`) for each case's own free-text
    `scope` (section 1 body, in the blind view's allowed sections) — the
    stratum (outcome × scope-kind) is NOT computed here and NEVER
    rendered: it exists only for `coverage_update`, downstream, once the
    outcome is no longer being withheld.

    Only freeze-verified index rows are consumed (`only_ok=True`, O-3
    carried item 2). The runner separately compares the full and verified
    index counts and reports how many were excluded, so a corrupt case is
    visible as a count but its untrusted fields never enter this view."""
    home = Path(home)
    rows = cases_mod.list_cases(home, since=since, only_ok=True)
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
    a non-empty `skipped` list means for that week's run.

    N1: refuses when `stage_dir` resolves inside `home` — this module's
    advertised "no ledger write" property must be intrinsic to it, not a
    property only of callers that happen to point it elsewhere. Gate
    finding: "`write_blind_views` trusts its `stage_dir` ... no check
    that the path is outside `home`"; the fold brief's own wording
    ("refuses a `stage_dir` outside the run's stage root") names no
    stage-root parameter this function has to compare against, so this
    implements the gate's concrete mechanism instead — both lines
    recorded here per common-builder-rules.md, not resolved silently."""
    home = Path(home).resolve()
    stage_dir = Path(stage_dir).resolve()
    if stage_dir == home or home in stage_dir.parents:
        raise PopulationError(
            f"write_blind_views: refusing to stage inside the ledger home ({home}); "
            f"stage_dir was {stage_dir}"
        )
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
        for row in cases_mod.list_cases(home, only_ok=True):
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
    (O-3's) gate, not this pure module's.

    O-1 fold r1 / S3: carries `id: <bucket name>` (the fold brief's own
    wording) so `coverage_update` can record it as TAKEN the same
    uniform way as every other nudge kind — matched against an examined
    case's `record_bucket` (`cases._index_row`'s own field: the bucket
    the case's first cited record physically lives in). `bucket` stays,
    unchanged, for anything already reading it."""
    try:
        out = []
        for bucket in discover_buckets(home):
            if bucket.scope != "project":
                continue
            path = bucket_project_path(bucket.path)
            if path is not None and "/.claude/worktrees/" in path.as_posix():
                out.append(
                    {"kind": "worktree-bucket", "id": bucket.name, "bucket": bucket.name, "path": str(path)}
                )
        return out
    except Exception:
        return []


def nudges(home: Path | str, coverage: dict, week: str) -> list[dict]:
    """Coverage nudges — information only, NEVER forced draws (plan
    §4.5). Order: strata not examined for the longest time first, then
    recurrence suspects, always-loaded zero-fire lessons, untouched
    system readings, and worktree-bucket captures (build-o1.md §Code's
    own listed order). The runner (O-3) passes this list's own return
    value through to `coverage_update`'s `offered` parameter, never the
    model's own copy of it (B2 / gap 3)."""
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
    return {
        "last_run_at": None,
        "last_examined_at": None,
        "strata": _empty_strata(),
        "nudges_offered": [],
        "nudges_taken": [],
        "examined_count": 0,
        "population_count": 0,
    }


#: N2/N3: the coverage dict's own top-level shape — `render_coverage`
#: refuses anything outside this set (B2's discipline extended to the
#: dict's own keys, not just to a nudge entry's fields).
_COVERAGE_ALLOWED_KEYS = frozenset(
    {
        "last_run_at", "last_examined_at", "strata", "nudges_offered",
        "nudges_taken", "examined_count", "population_count",
    }
)


def load_coverage(path: Path | str) -> dict:
    """Read `coverage.yaml`; a missing file is the empty structure (every
    stratum `empty`, zero cumulative counts), never `None` — O-3's first
    run has nothing to merge against yet. `examined_count`/
    `population_count` (N3, added this fold) default to 0 when the file
    predates them — a hand-edited or older-shaped file must never make
    this raise."""
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
        "last_run_at": data.get("last_run_at"),
        "last_examined_at": data.get("last_examined_at"),
        "strata": strata,
        "nudges_offered": list(data.get("nudges_offered") or []),
        "nudges_taken": list(data.get("nudges_taken") or []),
        "examined_count": int(data.get("examined_count") or 0),
        "population_count": int(data.get("population_count") or 0),
    }


def render_coverage(data: dict) -> str:
    """`coverage.yaml`'s text — structured records only, no free text
    (`02-schema.md` §3a.1 item 2). Strata are emitted in the fixed
    outcome-then-scope order (`_empty_strata`'s own iteration), never a
    dict's insertion order, so the file's diff each week is the actual
    change, not key reordering.

    N2: raises `CoverageError` on any top-level key this module does not
    know — the prior behaviour silently DROPPED an unrecognized key
    (`render_coverage` rebuilt the mapping from exactly three names),
    which is indistinguishable, at the call site, from "nothing extra
    was ever there" — consistent with B2's refuse-don't-drop discipline
    for a nudge entry's own fields."""
    unknown = set(data) - _COVERAGE_ALLOWED_KEYS
    if unknown:
        raise CoverageError(f"render_coverage: unknown key(s) {sorted(unknown)!r}")
    ordered = {
        "last_run_at": data.get("last_run_at"),
        "last_examined_at": data.get("last_examined_at"),
        "strata": {key: data.get("strata", {}).get(key, default) for key, default in _empty_strata().items()},
        "nudges_offered": list(data.get("nudges_offered") or []),
        "nudges_taken": list(data.get("nudges_taken") or []),
        "examined_count": int(data.get("examined_count") or 0),
        "population_count": int(data.get("population_count") or 0),
    }
    y = rt_yaml(default_flow_style=False)
    import io

    buf = io.StringIO()
    y.dump(ordered, buf)
    return buf.getvalue()


#: B2 / O-1 fold r1: `selection.yaml`'s own top-level shape. The model's
#: file contributes ONLY the case ids it chose plus its stated reasons
#: for choosing and for stopping — `why_these`/`why_stopped` are the two
#: free-text fields `02-schema.md` §3a.1 item 2 allows on THIS file
#: (never on `coverage.yaml` itself; `coverage_update` never copies
#: either one into its returned dict).
_SELECTION_ALLOWED_KEYS = frozenset({"cases", "why_these", "why_stopped"})
#: One selected case's own entry: an id, nothing else — never a
#: `stratum` (or any other) key the model might supply to steer
#: classification (test 3 / gate check (b)).
_SELECTION_CASE_ALLOWED_KEYS = frozenset({"id"})


def _validate_selection_yaml(selection_yaml: dict) -> None:
    unknown = set(selection_yaml) - _SELECTION_ALLOWED_KEYS
    if unknown:
        raise CoverageError(f"selection.yaml: unknown key(s) {sorted(unknown)!r}")
    for entry in selection_yaml.get("cases") or []:
        if not isinstance(entry, dict):
            continue
        extra = set(entry) - _SELECTION_CASE_ALLOWED_KEYS
        if extra:
            raise CoverageError(
                f"selection.yaml: case entry has unknown key(s) {sorted(extra)!r}"
            )


#: B2 / gap 3: the five nudge kinds `nudges()` ever emits, and the exact
#: field set each one's own emitter writes (`_stratum_nudges`,
#: `_recurrence_nudges`, `_always_loaded_zero_fire_nudges`,
#: `_untouched_system_reading_nudges`, `_worktree_bucket_nudges`) —
#: `_sanitize_offered` drops anything outside a KNOWN kind's own shape,
#: so an entry that arrives with an invented extra field (gate probe F's
#: `why_i_skipped_it`) never reaches `render_coverage`'s output even if
#: it rode in on an otherwise-legitimate `kind`.
_NUDGE_KIND_FIELDS: dict[str, frozenset[str]] = {
    "stratum": frozenset({"kind", "key", "last_examined_at"}),
    "recurrence-suspect": frozenset({"kind", "id", "nonce", "basis"}),
    "always-loaded-zero-fire": frozenset({"kind", "id"}),
    "system-reading-untouched": frozenset({"kind", "id"}),
    "worktree-bucket": frozenset({"kind", "id", "bucket", "path"}),
}


def _sanitize_offered(offered: list[dict] | None) -> list[dict]:
    """`offered` is meant to be exactly what `nudges()` returned — the
    runner passes it through, never the model's own file (B2 / gap 3:
    the ORIGINAL bug read `nudges_offered` back out of `selection_yaml`,
    trusting the party being audited). This still re-validates
    defensively, per kind, dropping: a non-dict entry; an entry whose
    `kind` is not one of the five known values; and any field on an
    otherwise-known entry that isn't part of THAT kind's own shape."""
    out = []
    for nudge in offered or []:
        if not isinstance(nudge, dict):
            continue
        kind = nudge.get("kind")
        allowed = _NUDGE_KIND_FIELDS.get(kind) if isinstance(kind, str) else None
        if allowed is None:
            continue
        out.append({k: v for k, v in nudge.items() if k in allowed})
    return out


def _forward_only(prev_iso: str | None, now_iso: str, now_dt: datetime) -> str:
    """S2: `last_examined_at` moves FORWARD only. A `None` previous is
    older than anything (the stratum was never examined before);
    otherwise the later of the two timestamps wins — a replay, a re-run
    of a stored selection, or a clock-skewed run must never make a
    just-examined stratum sort as if it were the stalest (`nudges`'s own
    ordering reads this field literally)."""
    if not prev_iso:
        return now_iso
    prev_dt = chrono.to_dt(prev_iso)
    if prev_dt is None:
        return now_iso
    return now_iso if now_dt >= prev_dt else prev_iso


def _case_stratum_key(row: dict) -> str | None:
    """The stratum key for one FULL case row (carries `outcome`, unlike
    the blind listing's `BlindCase`), or `None` when the row is not a
    stratum MEMBER at all this run:

    - S6: a row with `superseded_by` set is not a member of any stratum
      — its successor (a separate row, `supersedes: <this case>`)
      carries the lineage under the SUCCESSOR's own outcome. `parked/
      <scope>` is therefore the CURRENT backlog of undecided parked
      cases, never a history of every case ever parked.
    - an unrecognized/missing `outcome` (a malformed row) is dropped,
      same "degrade, don't hide the rest" discipline `cases._index_row`
      itself already uses.

    `scope_kind` is trusted AS GIVEN on the row (O-1 fold r1:
    `cases._index_row` computes it once, from the case's first cited
    record, at index-build time — this function never looks anything up
    itself and never falls back to a guess): a row whose outcome IS
    valid but whose `scope_kind` is missing, or not one of the three
    known kinds, raises `CoverageError` naming the case — filing it
    under a guessed stratum is exactly the silent miscount B1/S1
    found."""
    if row.get("superseded_by"):
        return None
    outcome = row.get("outcome")
    if outcome not in OUTCOMES:
        return None
    scope_kind = row.get("scope_kind")
    if scope_kind not in SCOPE_KINDS:
        raise CoverageError(
            f"coverage_update: case {row.get('case')!r} has no usable scope_kind "
            f"({scope_kind!r}) — refusing to file it under a guessed stratum"
        )
    return stratum_key(outcome, scope_kind)


def coverage_update(
    previous: dict | None,
    selection_yaml: dict,
    cases: list[dict],
    offered: list[dict],
    *,
    now: datetime | None = None,
) -> dict:
    """Compute the next `coverage.yaml` dict from the PREVIOUS record,
    the model's `selection.yaml` (only its list of chosen case ids is
    trusted; `why_these`/`why_stopped` are the only other keys it may
    carry, and neither reaches this function's return value — see the
    module docstring), *cases*: the FULL (non-blind) case index rows for
    the week's population (`cases.list_cases`'s own shape, carrying
    `outcome` and `scope_kind` — the blind `BlindCase` list from
    `population()` deliberately carries neither, so it cannot answer
    this function's question), and *offered*: the list `nudges()`
    itself returned this run (the runner passes it through — B2 / gap
    3, never the model's own copy).

    Per stratum: `last_examined_at` and `cumulative_count` are MERGED,
    never overwritten — a stratum with no examined case this run keeps
    whatever the previous record already had (test 5), and
    `last_examined_at` only ever moves FORWARD (S2, `_forward_only`). A
    stratum with zero members in THIS WEEK'S population is recorded
    `empty`, not dropped (test 4); one with members but none of them
    selected is `unexamined`; one with an examined case is `examined`,
    its cumulative count incremented by the number of examined cases in
    that cell this run.

    Raises `CoverageError` when `selection_yaml` carries an unknown key
    (top-level or on one case entry — B2) or when a case row cannot be
    classified into a stratum (`_case_stratum_key` — B1/S1): a degrade
    is not defensible for a ledger-truth artifact whose whole purpose is
    telling "uninspected" apart from "healthy"."""
    _validate_selection_yaml(selection_yaml)

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

    members_by_stratum: dict[str, list[dict]] = {key: [] for key in prev_strata}
    for row in cases:
        key = _case_stratum_key(row)
        if key is None or key not in members_by_stratum:
            continue
        members_by_stratum[key].append(row)

    new_strata: dict[str, dict] = {}
    for key, prev_entry in prev_strata.items():
        outcome, _, scope = key.partition("/")
        members = members_by_stratum.get(key, [])
        examined = [m for m in members if m.get("case") in selected_ids]
        prev_last = prev_entry.get("last_examined_at")
        if examined:
            new_strata[key] = {
                "outcome": outcome,
                "scope": scope,
                "cumulative_count": int(prev_entry.get("cumulative_count") or 0) + len(examined),
                "last_examined_at": _forward_only(prev_last, now_iso, now_dt),
                "status": "examined",
            }
        elif members:
            new_strata[key] = {
                "outcome": outcome,
                "scope": scope,
                "cumulative_count": int(prev_entry.get("cumulative_count") or 0),
                "last_examined_at": prev_last,
                "status": "unexamined",
            }
        else:
            new_strata[key] = {
                "outcome": outcome,
                "scope": scope,
                "cumulative_count": int(prev_entry.get("cumulative_count") or 0),
                "last_examined_at": prev_last,
                "status": "empty",
            }

    offered_valid = _sanitize_offered(offered)

    examined_rows = [row for row in cases if row.get("case") in selected_ids]
    examined_record_ids = {rid for row in examined_rows for rid in (row.get("records") or [])}
    examined_dependency_refs = {
        ref for row in examined_rows for ref in (row.get("dependency_refs") or [])
    }
    examined_buckets = {
        row.get("record_bucket") for row in examined_rows if row.get("record_bucket")
    }

    taken: list[dict] = []
    for nudge in offered_valid:
        kind = nudge.get("kind")
        if kind == "stratum":
            nudge_key = nudge.get("key")
            if isinstance(nudge_key, str) and new_strata.get(nudge_key, {}).get("status") == "examined":
                taken.append(nudge)
        elif kind in ("recurrence-suspect", "always-loaded-zero-fire"):
            if nudge.get("id") in examined_record_ids:
                taken.append(nudge)
        elif kind == "system-reading-untouched":
            if nudge.get("id") in examined_dependency_refs:
                taken.append(nudge)
        elif kind == "worktree-bucket":
            if nudge.get("id") in examined_buckets:
                taken.append(nudge)

    population_ids = {row.get("case") for row in cases}
    previous_last_run = prev.get("last_run_at")
    previous_last_examined = prev.get("last_examined_at")
    selected_count = len(selected_ids & population_ids)
    return {
        "last_run_at": _forward_only(previous_last_run, now_iso, now_dt),
        "last_examined_at": (
            _forward_only(previous_last_examined, now_iso, now_dt)
            if selected_count
            else previous_last_examined
        ),
        "strata": new_strata,
        "nudges_offered": offered_valid,
        "nudges_taken": taken,
        "examined_count": selected_count,
        "population_count": len(cases),
    }
