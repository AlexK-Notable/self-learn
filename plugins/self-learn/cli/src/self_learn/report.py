"""``self-learn report`` — the facts layer, v1 (11 §5).

v1 walks record files and tracked telemetry directly; the SQLite index
becomes the engine at M2 (the one deliberate divergence from "report
always builds the index", pinned in 11 §5). Everything here is derived,
regenerated on every run, and committed nowhere.

Honesty pins carried from 11 §4.3/§5:

- **Capture rate is bounded, never measured.** The declined-offer count
  is model-emitted best-effort, so it is a LOWER bound on true declines —
  which makes the computed capture rate an optimistic CEILING. Both
  labels are printed; neither number is presented as a measurement.
- **No-observed-fires is a candidate list, not "dead weight"** — fire
  observation doesn't exist until the M2 miner, so v1 prints the routed
  rules with their ages and says observation hasn't started, rather than
  implying silence means uselessness.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ruamel.yaml.error import YAMLError

from . import gitops
from .hosts import HostsError, load_hosts
from .ledger import discover_buckets
from .ledger_ops import open_followups
from .reachability import reachability_rows
from .records import Record, RecordError
from .refread import resolve_ref_target
from .telemetry import read_events

__all__ = [
    "gather",
    "ledger_metrics",
    "recurrence_suspects",
    "render_json",
    "render_text",
    "supply_mix",
]

#: U-readref §6.2-1: 30d rolling, matching the unit already in this file
#: (`ledger_metrics`'s `pending_over_30d_pct`).
_REFERENCE_WINDOW_DAYS = 30

#: NIT 4 (code gate r1): recovers a project-scope EVENT-ONLY row's
#: readable slug from the ledger's own `projects/<slug>` bucket dir name
#: — the digest is the last 8 hex chars of `slug_for`'s own construction
#: (hosts.py:104-106), so a bucket dir ending `-<digest>` is a match, not
#: a reversal. Genuinely unresolvable (the bucket dir has since been
#: pruned/rebound) is a distinct, real case — render_text renders it as
#: an explicit ABSENT marker, never a silent omission.
_PROJECT_BUCKET_DIGEST_RE = re.compile(r"-([0-9a-f]{8})$")


def _days_since(value, today: date) -> int | None:
    if value is None:
        return None
    text = str(value)[:10]
    try:
        then = date.fromisoformat(text)
    except ValueError:
        return None
    return (today - then).days


def _walk_records(home: Path):
    """(record) for every parseable pending/resolved record file."""
    for bucket in discover_buckets(home):
        for sub in ("pending", "resolved"):
            directory = bucket.path / sub
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("lrn-*.md")):
                try:
                    yield Record.from_path(path)
                # 09 §5 FW-18: skip EVERY read/parse failure class, not
                # RecordError alone — an undecodable/vanished/YAML-broken
                # file must never crash the full `status --json` path (its
                # supply_mix/metrics walk feeds the surface the unreadable
                # count rides on).
                except (RecordError, OSError, UnicodeDecodeError, YAMLError):
                    continue


def supply_mix(home: Path | str) -> dict[str, int]:
    """08 §8.1 O-3-revisit row: counts of pending+resolved records by
    ``source`` — where lessons actually come from (04 §Success-metrics'
    supply-mix input). Ledger-only, no git, no state files."""
    counts: Counter = Counter(r.source for r in _walk_records(Path(home)))
    return dict(counts)


#: Resolution-verb commit subjects (02 §2 pinned formats). Every lrn-id in
#: a matching subject resolved in that commit — collapse losers ride the
#: route subject's "supersedes …" suffix, so extracting ALL ids is the
#: honest read.
_RESOLUTION_SUBJECT_RE = re.compile(
    r"^self-learn: (?:route|reject|graduate|supersede) "
)
_LRN_ID_RE = re.compile(r"lrn-[0-9a-f]{8}")


def _utc_date(ts: str) -> str:
    """``%aI`` carries the author's LOCAL offset, but every other date in
    the triage metric (created_at, routed_at, today) is UTC — normalize
    before truncating, or the calendar day disagrees for a few hours
    around UTC midnight and the median walks (caught live 2026-07-17
    ~01:00Z: median 14.5 where the hand-count says 15.0)."""
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return ts[:10]


def _resolution_dates(home: Path) -> dict[str, str]:
    """record id → the UTC date (YYYY-MM-DD) of its FIRST resolution
    commit, from the ledger's own history (02 §2: git is the who/when for
    non-routed resolutions). Empty on a history-less repo."""
    try:
        proc = gitops._git(  # noqa: SLF001 — same module family
            home, "log", "--format=%aI%x09%s"
        )
    except gitops.GitOpsError:
        return {}
    if proc.returncode != 0:
        return {}
    dates: dict[str, str] = {}
    # log is newest-first: walk reversed so the FIRST (oldest) resolution
    # wins — a later metadata commit must not restate the triage moment.
    for line in reversed(proc.stdout.splitlines()):
        ts, _, subject = line.partition("\t")
        if not _RESOLUTION_SUBJECT_RE.match(subject):
            continue
        for rid in _LRN_ID_RE.findall(subject):
            dates.setdefault(rid, _utc_date(ts))
    return dates


def ledger_metrics(home: Path | str, *, today: date | None = None) -> dict:
    """The 04 §Success-metrics counters (T19) — counted, never modeled;
    computed from the ledger + git on demand, no state files:

    - ``time_to_triage_median_days``: median days a RESOLVED lesson sat
      pending (created_at → routed_at, or the resolution commit's author
      date for reject/graduate/supersede). None when nothing resolved —
      no data is "n/a", never a confident zero.
    - ``pending_over_30d_pct`` / ``pending_total``: queue health — % of
      status-pending records older than 30 days (the ha-note failure
      signature was 100%; sustained >50% means P3–P5 failed).
    - ``routed_and_corrected``: routed lessons later CORRECTIVELY
      superseded — excludes ``superseded_by: canon`` graduations, which
      are successes (04; blind adjudication 2026-07-12).
    """
    home = Path(home)
    today = today if today is not None else datetime.now(timezone.utc).date()
    resolution_dates: dict[str, str] | None = None  # lazy: git only if needed

    triage_days: list[int] = []
    pending_ages: list[int] = []
    corrected = 0
    for record in _walk_records(home):
        if record.status == "pending":
            age = _days_since(record.created_at, today)
            if age is not None:
                pending_ages.append(age)
            continue
        if record.routing is not None and record.superseded_by is not None:
            if record.superseded_by != "canon":
                corrected += 1
        if record.status in ("routed", "rejected", "superseded"):
            resolved_on = None
            if record.routing is not None:
                resolved_on = (record.routing or {}).get("routed_at")
            if resolved_on is None:
                if resolution_dates is None:
                    resolution_dates = _resolution_dates(home)
                resolved_on = resolution_dates.get(record.id)
            if resolved_on is None:
                continue  # unattributable (pre-history import): skip, honest
            created_age = _days_since(record.created_at, today)
            resolved_age = _days_since(str(resolved_on)[:10], today)
            if created_age is None or resolved_age is None:
                continue
            triage_days.append(created_age - resolved_age)

    over_30 = sum(1 for age in pending_ages if age > 30)
    return {
        "time_to_triage_median_days": (
            float(statistics.median(triage_days)) if triage_days else None
        ),
        "pending_total": len(pending_ages),
        "pending_over_30d_pct": (
            round(100.0 * over_30 / len(pending_ages), 1)
            if pending_ages
            else None
        ),
        "routed_and_corrected": corrected,
    }


def recurrence_suspects(home: Path | str) -> list[dict]:
    """09 §11 Y-4 (10 U0 substrate): unconfirmed recurrence-suspect
    telemetry against currently-``routed`` records — rows ``{id, nonce,
    seen_at, basis}``, ts-ordered (``read_events`` order).

    This EXPOSES the M2 deterministic detection
    (``worker._recurrence_suspects``, which spools the events in the first
    place) — it never re-derives suspicion. All this does is filter the
    tracked plane down to "still open": the target record is still
    ``routed`` (a superseded/rejected target's suspects are moot — 11
    §2.2 confirms against LIVE routed coverage, same rule
    ``confirm_recurrence`` enforces) and the event's nonce has not already
    been copied into that record's ``recurrences[].ref`` (confirmed —
    double-listing would overstate recurrence pressure, the exact thing
    ``confirm_recurrence`` itself refuses)."""
    home = Path(home)
    routed: dict[str, Record] = {
        r.id: r for r in _walk_records(home) if r.status == "routed"
    }
    rows: list[dict] = []
    for event in read_events(home):
        if event.get("kind") != "recurrence-suspect":
            continue
        nonce = event.get("nonce")
        record_id = event.get("record")
        # Telemetry lines are untrusted input (11 §4.2: any process may
        # spool one) — a malformed/hand-edited line (wrong-typed or
        # missing ``record``/``nonce``) is skipped, never a crash.
        if not isinstance(record_id, str) or not isinstance(nonce, str):
            continue
        record = routed.get(record_id)
        if record is None:
            continue
        if any(r.get("ref") == nonce for r in record.recurrences):
            continue  # already confirmed
        # `basis` says WHY this suspect was raised, and the four producers
        # mean very different things by it: `fire-violated` is the model
        # reporting that it broke this routed rule, while `miner-match`,
        # `origin-match` and `title-token-overlap` are text-similarity
        # heuristics. That distinction is most of the evidence a human has
        # when choosing revise / escalate / tolerate / retire, and it was
        # spooled into telemetry and then dropped right here — the
        # producer recorded its reason and no consumer could ever see it.
        # Passed through verbatim, never interpreted: this function
        # exposes the detection, it does not re-derive it, so a basis
        # value added by a future producer arrives without changes here.
        rows.append(
            {
                "id": record.id,
                "nonce": nonce,
                "seen_at": event.get("ts"),
                "basis": event.get("basis"),
            }
        )
    return rows


def _instrument_state(home: Path) -> str:
    """U-readref §6.3: ``ok`` | ``script-missing`` | ``not-registered`` |
    ``settings-unparseable``, derived from the same two inspectable facts
    ``selfcheck._check_hooks`` already reads for every ``self-learn-*``
    hook — reused here (deferred import: same-module-family reuse, the
    convention ``worker.py`` already uses for ``claude_runtime_dir``),
    never re-derived. An unparseable settings.json is its OWN state
    (`selfcheck.py:690-692`'s rule: "a broken settings.json must FAIL
    loudly, not read as 'nothing registered'") — collapsing it into
    ``not-registered`` would name the wrong remedy."""
    from .selfcheck import _registered_hook_commands, claude_runtime_dir

    claude_dir = claude_runtime_dir()
    script = claude_dir / "hooks" / "self-learn-refread.sh"
    if not (script.is_file() and os.access(script, os.X_OK)):
        return "script-missing"

    commands, problem = _registered_hook_commands(claude_dir / "settings.json")
    if problem is not None:
        return "settings-unparseable"
    for cmd in commands:
        if Path(cmd).name == "self-learn-refread.sh":
            return "ok"
    return "not-registered"


def _reference_shelf(
    home: Path,
    today: date,
    *,
    flush_state: str = "not-attempted",
    window_days: int = _REFERENCE_WINDOW_DAYS,
) -> dict:
    """U-readref §6: the ``reference_shelf`` facts block.

    Target enumeration is LEDGER-driven (every target of a live
    reference-routed record), then union'd with any target that has a
    ``reference-read`` event but no live record (§6.2-4) — the union is
    what lets §6.4's rule hold: a target is omitted only if it does not
    exist. ``instrumented``/``flush_state`` gate whether the READ-derived
    fields are trustworthy (§6.3/§6.7) without ever hiding the shelf's
    CONTENTS: ``targets``/``records``/``targets_total`` render regardless
    of instrument health (§6.3's own rule)."""
    from .selfcheck import _reference_target_for  # deferred: same-family reuse

    instrument_state = _instrument_state(home)
    instrumented = instrument_state == "ok"

    events_by_target: dict[str, list[dict]] = {}
    all_ts: list[str] = []
    for event in read_events(home):
        if event.get("kind") != "reference-read":
            continue
        ref_target = event.get("ref_target")
        if not isinstance(ref_target, str):
            continue  # malformed/hand-edited line (T3.6) — skipped, no crash
        events_by_target.setdefault(ref_target, []).append(event)
        ts = event.get("ts")
        if isinstance(ts, str):
            all_ts.append(ts)
    # §6.2-7: the EARLIEST reference-read event in the whole tracked
    # plane, or None — never `today`, never a proxy for the install date.
    # Computed unconditionally (independent of current instrument health:
    # historical events outlive a since-broken hook).
    observation_start = min(all_ts) if all_ts else None

    rows: dict[str, dict] = {}
    unresolvable_records = 0
    unresolvable_record_ids: list[str] = []
    # NIT 4: digest -> readable project bucket dir name, built from the
    # SAME `discover_buckets` walk below (no second pass) — covers every
    # project bucket on disk, not only ones with a matching live record,
    # so an event-only row (no live record) can still recover its slug.
    project_slugs: dict[str, str] = {}

    for bucket in discover_buckets(home):
        if bucket.scope == "project":
            m = _PROJECT_BUCKET_DIGEST_RE.search(bucket.name)
            if m:
                project_slugs[m.group(1)] = bucket.name
        for sub in ("pending", "resolved"):
            directory = bucket.path / sub
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                except (RecordError, OSError, UnicodeDecodeError, YAMLError):
                    continue
                if record.status != "routed" or record.superseded_by is not None:
                    continue  # §6.2-4: LIVE reference-routed records only
                routing = record.routing or {}
                if routing.get("destination") != "reference":
                    continue
                target_path = _reference_target_for(home, bucket, record)
                target = (
                    resolve_ref_target(home, target_path)
                    if target_path is not None
                    else None
                )
                if target is None:
                    # unresolvable-via-hosts.yaml, or a user-scope record
                    # (S-23 (2) — expected, live, never silently dropped)
                    unresolvable_records += 1
                    unresolvable_record_ids.append(record.id)
                    continue
                row = rows.get(target.key)
                if row is None:
                    row = {
                        "ref_target": target.key,
                        "scope": target.scope,
                        "bucket": target.bucket,
                        # Amendment B / §6.4: the readable project slug,
                        # for render_text only — identity in the EVENT
                        # stays digest-only (§5.2.1, unchanged). None for
                        # skill scope, which is already readable (its
                        # bucket IS the plain skill name).
                        "bucket_readable": (
                            bucket.name if target.scope == "project" else None
                        ),
                        "records": 0,
                    }
                    rows[target.key] = row
                row["records"] += 1

    for key, target_events in events_by_target.items():
        if key in rows:
            continue
        # §4.1.2/§10.1's no-re-split rule: `scope`/`bucket` come from the
        # EVENT's own fields (spooled verbatim off a real RefTarget at
        # emit time — §5.2's payload table), never by re-parsing `key`.
        # There is no abs_path here to hand back to `resolve_ref_target`
        # (this target has no live record), so the event is the only
        # other place those two components legitimately live.
        sample = target_events[0]
        sample_scope = sample.get("scope")
        sample_bucket = sample.get("bucket")
        scope_val = sample_scope if isinstance(sample_scope, str) else ""
        bucket_val = sample_bucket if isinstance(sample_bucket, str) else ""
        # NIT 4 (code gate r1): Amendment B binds EVERY project-scope
        # row, not only ones reached through a live record. The digest
        # (`bucket_val`) is recoverable from the ledger's OWN bucket dir
        # name via `project_slugs` — a lookup, never a re-split of `key`
        # and never a reversal of the digest itself. `None` here means
        # genuinely unresolvable (the bucket dir has since been
        # pruned/rebound) — render_text renders that as an explicit
        # ABSENT marker, never a silent omission.
        rows[key] = {
            "ref_target": key,
            "scope": scope_val,
            "bucket": bucket_val,
            "bucket_readable": (
                project_slugs.get(bucket_val) if scope_val == "project" else None
            ),
            "records": 0,
        }

    for key, row in rows.items():
        target_events = events_by_target.get(key, [])
        reads_all_time = len(target_events)
        in_window = []
        for event in target_events:
            age = _days_since(event.get("ts"), today)
            if age is not None and 0 <= age <= window_days:
                in_window.append(event)
        reads_30d = len(in_window)
        read_sessions_30d = len({e.get("session") for e in in_window})
        subagent_reads_30d = sum(1 for e in in_window if e.get("subagent") is True)
        ts_values = [
            e.get("ts") for e in target_events if isinstance(e.get("ts"), str)
        ]
        row.update(
            {
                "reads_all_time": reads_all_time,
                "reads_30d": reads_30d,
                "read_sessions_30d": read_sessions_30d,
                "subagent_reads_30d": subagent_reads_30d,
                # §6.2-3: zero_read is computed on ALL-TIME, not the
                # window — a file read once 60d ago is COLD, not unread.
                "last_read": max(ts_values) if ts_values else None,
                "zero_read": reads_all_time == 0,
            }
        )

    # §6.2-5: zero-read first, then ascending read_sessions_30d, then
    # ref_target — computed from the REAL values, before any nulling
    # below (nulling only replaces what is SHOWN, never the order).
    ordered = sorted(
        rows.values(),
        key=lambda r: (
            0 if r["zero_read"] else 1,
            r["read_sessions_30d"],
            r["ref_target"],
        ),
    )

    targets_total = len(ordered)
    # §6.6: zero enumerable targets is its own condition, never a quiet
    # all-clear — targets_zero_read/records_on_zero_read_targets go null.
    enumeration_state = "ok" if targets_total else "none-enumerable"
    targets_zero_read = sum(1 for r in ordered if r["zero_read"])
    records_on_zero_read_targets = sum(
        r["records"] for r in ordered if r["zero_read"]
    )
    reads_30d_total = sum(r["reads_30d"] for r in ordered)

    if enumeration_state == "none-enumerable":
        targets_zero_read = None
        records_on_zero_read_targets = None

    # §6.3: not-instrumented is a distinct state, NEVER zero — every
    # read-derived field renders null, never 0. targets/records/
    # targets_total are untouched: the shelf's CONTENTS are known
    # regardless of whether reads are observable.
    if not instrumented:
        for row in ordered:
            for field in (
                "reads_all_time",
                "reads_30d",
                "read_sessions_30d",
                "subagent_reads_30d",
                "last_read",
                "zero_read",
            ):
                row[field] = None
        reads_30d_total = None
        targets_zero_read = None
        records_on_zero_read_targets = None

    window_start = today - timedelta(days=window_days)

    return {
        "instrumented": instrumented,
        "instrument_state": instrument_state,
        "flush_state": flush_state,
        "enumeration_state": enumeration_state,
        "unresolvable_records": unresolvable_records,
        "unresolvable_record_ids": unresolvable_record_ids,
        "window_days": window_days,
        "window_start": str(window_start),
        "observation_start": observation_start,
        "targets_total": targets_total,
        "targets_zero_read": targets_zero_read,
        "records_on_zero_read_targets": records_on_zero_read_targets,
        "reads_30d_total": reads_30d_total,
        "targets": ordered,
    }


#: §6 rule 5 (Q3 RULED): the `by_destination` keys, ALWAYS present
#: (including zero-count ones) — the three `claude-md` shapes come from
#: two different predicates (RP-CMD vs RP-RULES) with disjoint reason
#: sets and disjoint remedies, so a merged `claude-md` count is the one
#: number that cannot tell them apart.
_SURFACE_REACH_KEYS = (
    "skill-md",
    "new-skill",
    "claude-md",
    "claude-md:local",
    "claude-md:rules",
    "hook",
)

#: §5.5: the destinations whose predicate reads the SETTINGS facet (RP-
#: SKILL, RP-HOOK — both `skill-md`/`new-skill` share RP-SKILL). RP-CMD
#: and RP-RULES read no settings collection at all (§4.4a, §5.5's table).
_SETTINGS_DEPENDENT_KEYS = ("skill-md", "new-skill", "hook")

_SURFACE_STATE_ORDER = {"unreachable": 0, "unmeasurable": 1, "reachable": 2}


def _surface_variant_key(verdict) -> str:
    """§6 rule 5: group `claude-md` by `Verdict.variant` — a group-by over
    the list :func:`~self_learn.reachability.reachability_rows` already
    returned, never a new computation (§4.3)."""
    if verdict.destination == "claude-md":
        if verdict.variant == "rules":
            return "claude-md:rules"
        if verdict.variant == "local":
            return "claude-md:local"
        return "claude-md"
    return verdict.destination


def _elide_surface_target(target: str | None, *, home: Path, skills_root) -> str | None:
    """§6 rule 6: elide the skills root and the ledger home to
    `<skills-root>` / `<home>` placeholders — this repo (and its reports)
    are quotable and public; a display-string substitution, not a
    reachability recomputation."""
    if target is None:
        return None
    text = target
    if skills_root is not None:
        root_str = str(skills_root)
        if text.startswith(root_str):
            return "<skills-root>" + text[len(root_str) :]
    home_str = str(home)
    if text.startswith(home_str):
        return "<home>" + text[len(home_str) :]
    return text


def _surface_reach(home: Path, claude_dir: Path) -> dict:
    """U-pointer §6: the `surface_reach` facts block — the SAME verdict
    list :func:`selfcheck._check_surface` renders as a PASS/FAIL row,
    rendered here a second way. Per §4.3 this function may not re-derive,
    re-probe, or recompute any field: it calls
    :func:`~self_learn.reachability.reachability_rows` exactly once and
    counts/groups/orders over what it returned (plus the domain facts
    attached to that return — see `reachability.py`'s module docstring
    for why those live there instead of a second read of `settings.json`
    or a second `Record.from_path` walk here)."""
    user_claude_md = claude_dir / "CLAUDE.md"
    rows = reachability_rows(home, claude_dir, user_claude_md=user_claude_md)

    claude_dir_usable = getattr(rows, "claude_dir_usable", True)
    settings_usable = getattr(rows, "settings_usable", True)
    instrument_state = getattr(rows, "instrument_state", "ok")
    unparseable_records = getattr(rows, "unparseable_records", 0)

    checked = len(rows)
    reachable_n = sum(1 for r in rows if r.state == "reachable")
    unreachable_n = sum(1 for r in rows if r.state == "unreachable")
    unmeasurable_n = sum(1 for r in rows if r.state == "unmeasurable")

    by_destination: dict[str, dict] = {
        key: {"reachable": 0, "unreachable": 0, "unmeasurable": 0}
        for key in _SURFACE_REACH_KEYS
    }
    for r in rows:
        by_destination[_surface_variant_key(r)][r.state] += 1

    # §6 rule 2: nulling is PER FACET, never blanket. `checked`,
    # `unmeasurable`, `unparseable_records` and `rows` always render.
    if not claude_dir_usable or not settings_usable:
        for key in _SETTINGS_DEPENDENT_KEYS:
            by_destination[key] = {"reachable": None, "unreachable": None, "unmeasurable": None}
    if not claude_dir_usable:
        for key in ("claude-md", "claude-md:local", "claude-md:rules"):
            by_destination[key] = {"reachable": None, "unreachable": None, "unmeasurable": None}

    top_reachable: int | None = reachable_n
    top_unreachable: int | None = unreachable_n
    if not claude_dir_usable or not settings_usable:
        top_reachable = None
        top_unreachable = None

    try:
        skills_root = load_hosts(home).skills_root
    except HostsError:
        skills_root = None

    # §6 rule 1: unreachable first, then unmeasurable, then reachable;
    # within a state, by destination then record_id.
    ordered = sorted(
        rows, key=lambda r: (_SURFACE_STATE_ORDER[r.state], r.destination, r.record_id)
    )
    rows_out = [
        {
            "record_id": r.record_id,
            "bucket": r.bucket,
            "scope": r.scope,
            "destination": r.destination,
            "variant": r.variant,
            "target": _elide_surface_target(r.target, home=home, skills_root=skills_root),
            "state": r.state,
            "reason": r.reason,
            "detail": r.detail,
        }
        for r in ordered
    ]

    return {
        "instrument_state": instrument_state,
        "claude_dir_usable": claude_dir_usable,
        "settings_usable": settings_usable,
        "checked": checked,
        "reachable": top_reachable,
        "unreachable": top_unreachable,
        "unmeasurable": unmeasurable_n,
        "unparseable_records": unparseable_records,
        "by_destination": by_destination,
        "rows": rows_out,
    }


def gather(
    home: Path | str,
    *,
    today: date | None = None,
    flush_state: str = "not-attempted",
    claude_dir: Path | None = None,
) -> dict:
    """Walk every bucket + the tracked telemetry plane into one facts map.

    ``flush_state`` (U-readref §6.7/§10.2) is PASSED IN by the caller —
    ``gather`` cannot observe whether ITS caller flushed the spool first,
    and inferring the outcome by inspecting the spool here would be wrong:
    a concurrent session appending between a real flush and this walk
    would make a perfectly healthy run look ``refused``. The default,
    ``"not-attempted"``, is deliberately not ``"ok"`` — every test that
    calls ``gather()`` directly without flushing gets the honest value.

    ``claude_dir`` (U-pointer §6 rule 7) is PASSED IN too, same reasoning
    as ``flush_state``: it defaults to :func:`selfcheck.claude_runtime_dir`
    (deferred import, same-module-family reuse convention as
    ``_instrument_state`` above) but is never RE-derived inside
    ``_surface_reach`` — a function that silently reached for the
    operator's real ``~/.claude`` from inside a sandboxed test would aim
    the check at the wrong machine."""
    home = Path(home)
    today = today if today is not None else datetime.now(timezone.utc).date()
    if claude_dir is None:
        from .selfcheck import claude_runtime_dir  # deferred: same-family reuse

        claude_dir = claude_runtime_dir()

    buckets: list[dict] = []
    destinations: Counter = Counter()
    routed_ever = 0  # any record that carries a routing block
    superseded_after_routing = 0
    graduated = 0
    rejected = 0
    routed_live = []  # currently-routed rules (the attention-tax payers)
    deferred: list[dict] = []
    # Doc 12 T-M5: mined supply (source: session) tracked per decision
    # class — the accept rate below is THE metric that decides the
    # miner's fate (and, per class, the autonomy ladder's evidence).
    mined: Counter = Counter()

    for bucket in discover_buckets(home):
        counts = Counter()
        for sub in ("pending", "resolved"):
            directory = bucket.path / sub
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("lrn-*.md")):
                try:
                    record = Record.from_path(path)
                # 09 §5 FW-18: same widened skip set as _walk_records.
                except (RecordError, OSError, UnicodeDecodeError, YAMLError):
                    continue
                counts[record.status] += 1
                if record.source == "session":
                    if record.status == "superseded":
                        if record.superseded_by == "canon":
                            mined["graduated"] += 1
                        elif record.routing is not None:
                            # accepted (routed), later replaced — stays in
                            # the accept-rate numerator+denominator
                            mined["routed"] += 1
                        else:
                            mined["superseded_unrouted"] += 1
                    else:
                        mined[record.status] += 1
                if record.routing is not None:
                    routed_ever += 1
                if record.status == "routed":
                    destinations[(record.routing or {}).get("destination")] += 1
                    routed_live.append(
                        {
                            "id": record.id,
                            "bucket": bucket.name,
                            "routed_days_ago": _days_since(
                                (record.routing or {}).get("routed_at"), today
                            ),
                            "last_confirmed": (
                                str(record.last_confirmed)
                                if record.last_confirmed is not None
                                else None
                            ),
                            "recurrences": len(record.recurrences),
                        }
                    )
                elif record.status == "rejected":
                    rejected += 1
                elif record.status == "superseded":
                    if record.superseded_by == "canon":
                        graduated += 1
                    elif record.routing is not None:
                        superseded_after_routing += 1
                elif record.status == "deferred":
                    deferred.append(
                        {
                            "id": record.id,
                            "bucket": bucket.name,
                            "until": str(record.deferred_until),
                            # positive = past due; filled below
                            "overdue_days": None,
                        }
                    )
        buckets.append(
            {"bucket": bucket.name, "scope": bucket.scope, "counts": dict(counts)}
        )

    for entry in deferred:  # positive = past due
        entry["overdue_days"] = _days_since(entry["until"], today)

    events = read_events(home)
    kinds: Counter = Counter(e.get("kind") for e in events)
    decline_reasons: Counter = Counter(
        (e.get("reason") if isinstance(e.get("reason"), str) else "unspecified")
        for e in events
        if e.get("kind") == "offer-declined"
    )
    captures = kinds.get("capture", 0)
    declined = kinds.get("offer-declined", 0)
    capture_ceiling = (
        captures / (captures + declined) if (captures + declined) else None
    )

    supersede_rate = (
        superseded_after_routing / routed_ever if routed_ever else None
    )

    mined_adjudicated = (
        mined["routed"] + mined["graduated"] + mined["rejected"]
    )
    mined_accept_rate = (
        (mined["routed"] + mined["graduated"]) / mined_adjudicated
        if mined_adjudicated
        else None  # honesty: measured over adjudicated cards only
    )

    return {
        "generated": str(today),
        "buckets": buckets,
        "destinations": dict(destinations),
        "routed_live": sorted(
            routed_live, key=lambda r: -(r["routed_days_ago"] or 0)
        ),
        "routed_ever": routed_ever,
        "superseded_after_routing": superseded_after_routing,
        "supersede_rate": supersede_rate,
        "graduated": graduated,
        "rejected": rejected,
        "open_followups": open_followups(home),
        "recurrence_suspects": recurrence_suspects(home),
        "deferred": deferred,
        "mined": {
            "pending": mined["pending"],
            "deferred": mined["deferred"],
            "routed": mined["routed"],
            "graduated": mined["graduated"],
            "rejected": mined["rejected"],
            "superseded_unrouted": mined["superseded_unrouted"],
            "adjudicated": mined_adjudicated,
            "accept_rate": mined_accept_rate,
        },
        "telemetry": {
            "events_by_kind": dict(kinds),
            "decline_reasons": dict(decline_reasons),
            "captures": captures,
            "declined_logged": declined,
            "capture_rate_ceiling": capture_ceiling,
        },
        "reference_shelf": _reference_shelf(home, today, flush_state=flush_state),
        "surface_reach": _surface_reach(home, claude_dir),
    }


def render_json(facts: dict) -> str:
    return json.dumps(facts)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100)}%"


def render_text(facts: dict) -> str:
    lines: list[str] = [f"self-learn report — {facts['generated']}"]

    lines.append("")
    lines.append("Lessons by bucket:")
    for b in facts["buckets"]:
        counts = b["counts"]
        if not counts:
            continue
        parts = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
        lines.append(f"  {b['bucket']} ({b['scope']}): {parts}")
    if facts["destinations"]:
        parts = ", ".join(
            f"{n} → {dest}" for dest, n in sorted(facts["destinations"].items())
        )
        lines.append(f"  live routed rules by destination: {parts}")

    lines.append("")
    lines.append(
        f"Iteration: {facts['routed_ever']} routed ever · "
        f"{facts['superseded_after_routing']} later replaced "
        f"(supersede rate {_pct(facts['supersede_rate'])}) · "
        f"{facts['graduated']} graduated into authored canon · "
        f"{facts['rejected']} rejected"
    )

    mined = facts.get("mined") or {}
    if any(mined.get(k) for k in ("pending", "routed", "graduated", "rejected")):
        lines.append("")
        lines.append(
            f"Mined supply (transcript miner): {mined['pending']} pending · "
            f"{mined['routed']} routed · {mined['graduated']} graduated · "
            f"{mined['rejected']} rejected — accept rate "
            f"{_pct(mined['accept_rate'])} (adjudicated cards only)"
        )

    followups = facts["open_followups"]
    lines.append("")
    if followups:
        lines.append(f"Open follow-ups ({len(followups)}) — planned upgrades:")
        for fu in followups:
            gate = f" (unblocks on {fu['unblocks_on']})" if fu["unblocks_on"] else ""
            lines.append(f"  {fu['id']} [{fu['bucket']}]: {fu['action']}{gate}")
    else:
        lines.append("Open follow-ups: none")

    deferred = facts["deferred"]
    if deferred:
        lines.append("")
        lines.append(f"Deferred ({len(deferred)}):")
        for d in deferred:
            overdue = d.get("overdue_days")
            when = (
                f"due {abs(overdue)}d ago — will resurface in review"
                if isinstance(overdue, int) and overdue > 0
                else f"until {d['until']}"
            )
            lines.append(f"  {d['id']} [{d['bucket']}]: {when}")

    t = facts["telemetry"]
    lines.append("")
    lines.append("Offer ledger (11 §4.3 — the declined count is a LOWER bound;")
    lines.append("logging a decline is model discipline, so the capture rate")
    lines.append("below is an optimistic CEILING, not a measurement):")
    lines.append(
        f"  {t['captures']} captured · ≥{t['declined_logged']} declined (logged)"
        f" · capture rate ≤ {_pct(t['capture_rate_ceiling'])}"
    )
    if t["decline_reasons"]:
        parts = ", ".join(
            f"{n}× {reason}" for reason, n in sorted(t["decline_reasons"].items())
        )
        lines.append(f"  decline reasons: {parts}")
    if t["events_by_kind"]:
        parts = ", ".join(
            f"{n} {kind}" for kind, n in sorted(t["events_by_kind"].items())
        )
        lines.append(f"  telemetry events on file: {parts}")
    else:
        lines.append("  no telemetry on file yet")

    routed_live = facts["routed_live"]
    if routed_live:
        lines.append("")
        lines.append(
            "Routed rules with no observed activity — NOT dead weight: fire"
        )
        lines.append(
            "observation starts with the M2 miner, and a silently-working"
        )
        lines.append("rule fires without a trace. Candidates for a human")
        lines.append("still-good? check (confirm-held lands at M2):")
        for r in routed_live:
            age = (
                f"routed {r['routed_days_ago']}d ago"
                if r["routed_days_ago"] is not None
                else "routing date unknown"
            )
            confirmed = (
                f", last confirmed {r['last_confirmed']}"
                if r["last_confirmed"]
                else ", never confirmed since"
            )
            lines.append(f"  {r['id']} [{r['bucket']}]: {age}{confirmed}")

    rs = facts.get("reference_shelf")
    if rs is not None:
        lines.append("")
        lines.append(
            f"Reference shelf ({rs['window_days']}d window, "
            f"{rs['targets_total']} target(s) known):"
        )
        if not rs["instrumented"]:
            lines.append(
                f"  NOT INSTRUMENTED ({rs['instrument_state']}) — every "
                "read-derived count below is ABSENT, never zero (an "
                "un-instrumented shelf must never look like an unread one)"
            )
        if rs["flush_state"] != "ok":
            lines.append(
                f"  flush_state: {rs['flush_state']} — the counts below "
                "are a LOWER BOUND, not a full count"
            )
        if rs["enumeration_state"] == "none-enumerable":
            lines.append(
                "  NO ENUMERABLE TARGETS — targets_zero_read / "
                "records_on_zero_read_targets: ABSENT (nothing was "
                "enumerable, not a clean shelf)"
            )
        if rs["unresolvable_records"]:
            lines.append(
                f"  {rs['unresolvable_records']} reference-routed "
                "record(s) unresolvable to any target: "
                + ", ".join(rs["unresolvable_record_ids"])
            )
        for row in rs["targets"]:
            label = row["ref_target"]
            if row["scope"] == "project":
                # Amendment B / §6.4: EVERY project-scope row, not only
                # ones with a live record — the readable slug rendered
                # BESIDE the digest key (report output is ephemeral,
                # never committed/synced; identity in the EVENT stays
                # digest-only, §5.2.1 unchanged). NIT 4: when the slug is
                # genuinely unresolvable (the bucket dir has since been
                # pruned/rebound), that is named explicitly — never a
                # silent omission of the parenthetical.
                if row.get("bucket_readable"):
                    label = f"{label} ({row['bucket_readable']})"
                else:
                    label = f"{label} (slug: ABSENT)"
            if rs["instrumented"]:
                if row["zero_read"]:
                    reads = "ZERO READS"
                else:
                    reads = (
                        f"{row['reads_all_time']} read(s) all-time, "
                        f"{row['read_sessions_30d']} session(s)/"
                        f"{rs['window_days']}d"
                    )
            else:
                reads = "reads: ABSENT (not instrumented)"
            lines.append(f"  {label}: {row['records']} record(s) — {reads}")

    sr = facts.get("surface_reach")
    if sr is not None:
        lines.append("")
        lines.append(
            f"Surface reach ({sr['checked']} record(s) checked, instrument: "
            f"{sr['instrument_state']}):"
        )
        if sr["reachable"] is None or sr["unreachable"] is None:
            lines.append(
                "  NOT MEASURED (top-level reachable/unreachable) — a depended-on "
                f"facet is unusable (claude_dir_usable={sr['claude_dir_usable']}, "
                f"settings_usable={sr['settings_usable']})"
            )
        else:
            lines.append(
                f"  {sr['reachable']} reachable, {sr['unreachable']} unreachable, "
                f"{sr['unmeasurable']} unmeasurable"
            )
        if sr["unparseable_records"]:
            lines.append(
                f"  {sr['unparseable_records']} resolved record(s) skipped — "
                "unparseable"
            )
        for key, counts in sr["by_destination"].items():
            if counts["reachable"] is None:
                lines.append(f"  {key}: NOT MEASURED")
            else:
                lines.append(
                    f"  {key}: {counts['reachable']} reachable, "
                    f"{counts['unreachable']} unreachable, "
                    f"{counts['unmeasurable']} unmeasurable"
                )
        for row in sr["rows"]:
            lines.append(
                f"  {row['record_id']} [{row['destination']}"
                f"{':' + row['variant'] if row['variant'] else ''}]: "
                f"{row['state']} ({row['reason']}) — {row['detail']}"
            )

    return "\n".join(lines)
