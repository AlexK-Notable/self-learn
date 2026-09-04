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
from .compilers import _iso, compile_managed_text
from .hosts import HostsError, load_hosts
from .ledger import discover_buckets
from .ledger_ops import open_followups
from .reachability import reachability_rows
from .records import Record, RecordError
from .refread import resolve_ref_target
from .telemetry import read_events

__all__ = [
    "COMPOSITION_CAUTION_ADVISORY",
    "COMPOSITION_GROWTH_PP_ADVISORY",
    "COMPOSITION_SHARE_ADVISORY",
    "DESCRIPTION_SOFT_MAX_WORDS",
    "GROWTH_ALARM_WORDS_PER_30D",
    "REFERENCE_READ_RATE_STATES",
    "SESSION_BASELINE_WORDS_ADVISORY",
    "TOKENS_PER_WORD_EST",
    "context_budget",
    "gather",
    "ledger_metrics",
    "recurrence_suspects",
    "reference_read_verdict",
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
        if any(d.get("ref") == nonce for d in record.dismissed_suspects):
            continue  # dismissed as a matcher false-positive (U-dismiss)
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


def _instrument_state(_home: Path) -> str:
    """U-readref §6.3: ``ok`` | ``script-missing`` | ``not-registered`` |
    ``settings-unparseable``, derived from the same two inspectable facts
    ``selfcheck._check_hooks`` already reads for every ``self-learn-*``
    hook — reused here (deferred import: same-module-family reuse, the
    convention ``worker.py`` already uses for ``claude_runtime_dir``),
    never re-derived. An unparseable settings.json is its OWN state
    (`selfcheck.py:690-692`'s rule: "a broken settings.json must FAIL
    loudly, not read as 'nothing registered'") — collapsing it into
    ``not-registered`` would name the wrong remedy. ``_home`` is unused
    (pyright/code-gate cleanup): `claude_runtime_dir()` resolves off
    ``SELF_LEARN_CLAUDE_DIR``/HOME alone, never the ledger home -- kept,
    underscore-prefixed, rather than dropped, since the one call site
    below and a test helper (test_refread.py's `_instrument_state_for`)
    both thread it positionally and dropping it would ripple beyond this
    unit's diff for no behavior change."""
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
        # pyright cleanup (code gate r1): narrow inside the comprehension
        # via the walrus so `ts_values` types as `list[str]`, not
        # `list[Unknown | None]` -- `max()` below is unsound on the
        # latter (a `None` in the list has no total order against `str`).
        ts_values = [
            ts for e in target_events if isinstance((ts := e.get("ts")), str)
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


# ------------------------------------------------------- U-cap: context budget
#
# The report-only context budget (spec: docs/specs/self-learn/drafts/
# u-cap-context-budget-spec.md). Four signals — budget/crowding/composition/
# growth — plus two conditional read-rate/arrival verdicts, landing under
# ONE top-level `report --json` key, `context_budget`. §4.0's rules bind
# every signal here: `severity` is ALWAYS the literal "informational";
# nothing here ever refuses a route, changes an exit code, or sets a field
# any caller reads as a refusal. Every block carries a measured/unmeasured
# tally and an all-blind form — `*_measured == 0` => totals `null` AND
# `flagged: null` (never `0` / never `false`).

#: PLACEHOLDER, calibrated against the 2026-08-22 host measurement so the
#: report's figures stay directly comparable to the research table (6,545 w
#: -> ~8,700 tok). NOT a tokenizer: this unit adds no dependency (the CLI's
#: only runtime dep is ruamel.yaml).
TOKENS_PER_WORD_EST = 1.33

#: PLACEHOLDER — the measured per-session BASELINE is ~6,454 w (user +
#: skill descriptions), 2026-08-23, one host. Deliberately just above it, so
#: a healthy baseline is quiet and real growth trips it. Compared against
#: `session_baseline_words`, never against a sum of hosts no session loads.
SESSION_BASELINE_WORDS_ADVISORY = 7000

#: PLACEHOLDER. The user CLAUDE.md measured 77% managed on 2026-08-22 and
#: trips this immediately — which is correct and is the point: it is
#: report-only.
COMPOSITION_SHARE_ADVISORY = 0.50

#: PLACEHOLDER. 10 percentage points of today's file added inside one 30d
#: window. No prior series exists to calibrate against; revisit once the
#: first three windows of real data have run.
COMPOSITION_GROWTH_PP_ADVISORY = 10.0

#: PLACEHOLDER. The conservatism tax is directional evidence, not a
#: measured magnitude for this shelf: an anti-hallucination instruction
#: cost one model 89.0% -> 72.0% literal extraction (arXiv:2601.02023)
#: while barely moving another. Nobody has measured what a shelf of N
#: cautions compounds to, so this number flags a composition worth LOOKING
#: at, never one worth refusing.
COMPOSITION_CAUTION_ADVISORY = 0.75

#: PLACEHOLDER — ~11.5%/30d against the 6,545 w measured baseline, i.e. a
#: linear doubling in ~9 months. One host, one measurement, 2026-08-22.
GROWTH_ALARM_WORDS_PER_30D = 750

#: PLACEHOLDER. Live distribution, 45 skills in the session index,
#: re-measured 2026-08-23: ~3,099 w total, mean ~69 w; the scaffold's own
#: output ~76 w; long tail hypr-doctor 206, firecrawl-monitor 188,
#: bitwarden-cli 161, home-network 129, firecrawl-build 104,
#: agentic-engineering 98. 80 sits just above the scaffold and the mean, so
#: it flags the tail, not the norm.
DESCRIPTION_SOFT_MAX_WORDS = 80

#: PLACEHOLDER — the retired over-cap OR-in's own number (`verbs.py`'s
#: `_COFIRE_CROWDED_THRESHOLD`), carried forward as a report-only trip
#: point.
_COFIRE_MAX_FANIN_ADVISORY = 5

#: U-cap §4.5: the closed read-rate state ladder, in evaluation order.
_REFERENCE_WHY = {
    "not-instrumented": (
        "read rate UNKNOWN — the refread hook is not registered, so "
        "routing here trades a measured cost for an unmeasured one."
    ),
    "none-enumerable": (
        "read rate UNKNOWN — no reference targets are enumerable, so "
        "routing here trades a measured cost for an unmeasured one."
    ),
    "never-observed": (
        "read rate UNKNOWN — no reference-read event has ever been "
        "observed, so routing here trades a measured cost for an "
        "unmeasured one."
    ),
    "partly-cold": (
        "some reference targets have zero reads — part of this shelf may "
        "be coverage that isn't."
    ),
    "ok": "every known reference target has been read at least once.",
}
#: Exported so a test can assert the mapping covers every state, and so a
#: new state cannot silently ship with no sentence (T8.7).
REFERENCE_READ_RATE_STATES = frozenset(_REFERENCE_WHY)


def _words(text: str) -> int:
    """The ONE word count in this unit — whitespace split, matching
    ``compilers.compile_managed_text``'s ``len(e.split())`` exactly
    (compilers.py:304) so a managed share is a ratio of like to like."""
    return len(text.split())


def _tokens_est(words: int) -> int:
    return round(words * TOKENS_PER_WORD_EST)


def _extract_skill_description(text: str) -> tuple[str | None, str | None]:
    """U-cap §4.2: two-tier description extraction. Tier 1 is
    ``compilers._safe_load_leading_mapping`` (the real YAML answer, the
    same loader behind ``has_paths_key`` — no new frontmatter parser).
    Tier 2 is a pinned LENIENT fallback for the 4 live skills whose
    description contains ``": "`` and so cannot parse as a plain YAML
    scalar (§2.11): from the leading ``---`` block, the ``description:``
    line plus its indented continuation lines, whitespace-joined. Returns
    ``(description, "strict"|"lenient")`` or ``(None, None)`` when neither
    tier produces a description."""
    from .compilers import _safe_load_leading_mapping

    loaded = _safe_load_leading_mapping(text)
    if loaded is not None:
        desc = loaded.get("description")
        if isinstance(desc, str) and desc.strip():
            return desc, "strict"

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    end = None
    for i, ln in enumerate(lines[1:], start=1):
        if ln.strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return None, None
    desc_lines: list[str] = []
    capturing = False
    for ln in lines[1:end]:
        if not capturing:
            m = re.match(r"^description:\s*(.*)$", ln)
            if m is None:
                continue
            capturing = True
            first = m.group(1).strip()
            if first:
                desc_lines.append(first)
            continue
        if ln.startswith((" ", "\t")) and ln.strip():
            desc_lines.append(ln.strip())
        else:
            break
    if not desc_lines:
        return None, None
    return " ".join(desc_lines), "lenient"


def _resolve_user_claude_md_row(home: Path) -> dict:
    """The `user-claude-md` internal working row (shared by budget,
    composition, crowding and rules_cofire): resolves EXACTLY as
    `surface_fill` does, then reads + compiles, degrading to a named
    `state` on any failure — never propagating (one broken surface must
    not blank the whole report, §4.2's degradation rule).

    u-cap code gate r1, MAJOR 1: threads `user_claude_md=` explicitly
    (surface_fill's OWN param, unused by this call site before) rather
    than falling through to `_resolve_target`'s raw
    `verbs.DEFAULT_USER_CLAUDE_MD` (`~/.claude/CLAUDE.md`, HOME-driven,
    unsandboxed). The value comes from `selfcheck.claude_runtime_dir()`
    -- the SAME `SELF_LEARN_CLAUDE_DIR`-or-`~/.claude` resolution every
    other `~/.claude`-rooted consumer in this codebase already uses, and
    the CLI test suite's conftest.py ALREADY sets `SELF_LEARN_CLAUDE_DIR`
    to a per-test tmp dir for every test (`cli/tests/conftest.py`'s
    `_worker_test_defaults`, unmodified) -- so this makes the whole
    session-skill-index/user-claude-md read path hermetic suite-wide
    with NO new env var and NO conftest.py edit. (conftest.py carries a
    SEPARATE unit's armor/tripwire pins -- U-sdka's `_AR1_SANCTIONED_
    PIN_LINES` and U-sdkw's whole-file `_ARMOR_SHAS` -- that a new
    global default there would trip; reusing the existing knob avoids
    that file entirely.) Production behavior is unchanged: with
    SELF_LEARN_CLAUDE_DIR unset, `claude_runtime_dir()` returns the real
    `~/.claude`, byte-identical to today."""
    from .compilers import CompileError
    from .selfcheck import claude_runtime_dir
    from .verbs import _resolve_target
    from .verbs import VerbError

    try:
        spec = _resolve_target(
            home, home, "user", "claude-md", None,
            user_claude_md=claude_runtime_dir() / "CLAUDE.md",
            check_dirty=False,
        )
    except VerbError:
        return {
            "state": "not-registered", "target": None, "text": None,
            "records": None, "section": None, "spec": None,
        }
    target = spec.target
    if not target.is_file():
        return {
            "state": "absent", "target": target, "text": None,
            "records": None, "section": None, "spec": spec,
        }
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {
            "state": "unreadable", "target": target, "text": None,
            "records": None, "section": None, "spec": spec,
        }
    from .verbs import _compile_set

    records = _compile_set(home, spec)
    try:
        section = compile_managed_text(text, records)
    except CompileError:
        return {
            "state": "corrupt-markers", "target": target, "text": text,
            "records": records, "section": None, "spec": spec,
        }
    return {
        "state": "ok", "target": target, "text": text, "records": records,
        "section": section, "spec": spec,
    }


def _resolve_project_rows(home: Path) -> list[dict]:
    """Internal working rows for every REGISTERED project host
    (`hosts.load_hosts(home).projects`, §4.2.1's per-session view). An
    entry whose path fails `hosts.host_path_problem` (moved, not a git
    repo, or IS the ledger home) is a `not-registered` row with every
    numeric field null — never omitted (T2.5): an omitted row is
    indistinguishable from a clean one."""
    from .compilers import CompileError
    from .hosts import HostsError, host_mode, host_path_problem, load_hosts, slug_for
    from .verbs import TargetSpec, _compile_set

    try:
        hosts = load_hosts(home)
    except HostsError:
        return []

    rows: list[dict] = []
    for project in hosts.projects:
        key = slug_for(project)[-8:]
        problem = host_path_problem(home, project, "project")
        if problem is not None:
            rows.append({
                "key": key, "state": "not-registered", "target": None,
                "text": None, "records": None, "section": None, "spec": None,
            })
            continue
        host_repo = Path(project).expanduser().resolve()
        target = host_repo / "CLAUDE.md"
        spec = TargetSpec(
            "claude-md", "project", home, target, host_repo,
            mode=host_mode(home, host_repo),
        )
        if not target.is_file():
            rows.append({
                "key": key, "state": "absent", "target": target,
                "text": None, "records": None, "section": None, "spec": spec,
            })
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            rows.append({
                "key": key, "state": "unreadable", "target": target,
                "text": None, "records": None, "section": None, "spec": spec,
            })
            continue
        records = _compile_set(home, spec)
        try:
            section = compile_managed_text(text, records)
        except CompileError:
            rows.append({
                "key": key, "state": "corrupt-markers", "target": target,
                "text": text, "records": records, "section": None,
                "spec": spec,
            })
            continue
        rows.append({
            "key": key, "state": "ok", "target": target, "text": text,
            "records": records, "section": section, "spec": spec,
        })
    return rows


#: The session skill index — `~/.claude/skills/*/SKILL.md` (§2.11); NEVER
#: `skills_root` (the route-target repo, 12 of 45 entries on this host).
#: Resolved via `selfcheck.claude_runtime_dir()` (code gate r1 MAJOR 1
#: fold) -- `SELF_LEARN_CLAUDE_DIR` when set, else the real `~/.claude` --
#: so tests sandbox it the same way every other `~/.claude`-rooted
#: consumer in this codebase already is, off the SAME env var
#: `cli/tests/conftest.py` already sets globally for every test.
_SKILL_INDEX_KEY = "~/.claude/skills"


def _skill_description_row(home: Path) -> dict:
    """U-cap §4.2's `skill-descriptions` row: one row summing every
    description's word count across the session skill index, resolved +
    deduped on the resolved path (symlinks; §2.11). Two-tier extraction
    per skill (`_extract_skill_description`); only a skill that fails
    BOTH tiers is `skills_unreadable` (never a `skills` entry, and it sets
    the block's `totals_are_lower_bound`, never the lenient count alone).

    u-cap code gate r1, MAJOR 1: `index_dir` used to be a bare
    `Path("~/.claude/skills").expanduser()` -- HOME-driven, unsandboxed
    by any test fixture. Resolved off `selfcheck.claude_runtime_dir()`
    now, same reasoning as `_resolve_user_claude_md_row` above (SEE that
    docstring for why conftest.py itself is not the fix site)."""
    from .selfcheck import claude_runtime_dir

    index_dir = claude_runtime_dir() / "skills"
    if not index_dir.is_dir():
        return {
            "surface": "skill-descriptions", "key": _SKILL_INDEX_KEY,
            "load_class": "unconditional", "state": "absent",
            "file_words": None, "file_tokens_est": None,
            "managed_words": None, "managed_entries": None,
            "managed_share": None, "flagged": False,
            "skills": [], "skills_total": 0, "skills_strict": 0,
            "skills_lenient": 0, "skills_unreadable": 0,
        }

    try:
        entries = sorted(index_dir.iterdir())
    except OSError:
        # u-cap code gate r1, MAJOR 3: an unenumerable (e.g. chmod 000)
        # index dir must NOT fall through to the "ok" return below with
        # file_words summed over zero entries -- that reads as a measured
        # 0-word surface (contributes 0 to session_baseline_words,
        # `flagged` reads clean) when the true state is "we could not see
        # this surface at all". Sec 4.0.4: unmeasurable is never zero.
        # Mirrors the `not index_dir.is_dir()` branch above (state
        # "absent"): this is the same shape for a different cause.
        return {
            "surface": "skill-descriptions", "key": _SKILL_INDEX_KEY,
            "load_class": "unconditional", "state": "unreadable",
            "file_words": None, "file_tokens_est": None,
            "managed_words": None, "managed_entries": None,
            "managed_share": None, "flagged": False,
            "skills": [], "skills_total": 0, "skills_strict": 0,
            "skills_lenient": 0, "skills_unreadable": 0,
        }

    seen: set[Path] = set()
    skills: list[dict] = []
    strict = lenient = unreadable = 0
    for entry in entries:
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            resolved = skill_md.resolve()
        except OSError:
            resolved = skill_md
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            text = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        desc, tier = _extract_skill_description(text)
        if desc is None:
            unreadable += 1
            continue
        words = _words(desc)
        if tier == "strict":
            strict += 1
        else:
            lenient += 1
        skills.append({
            "name": entry.name,
            "description_words": words,
            "description_tokens_est": _tokens_est(words),
            "over_soft_max": words > DESCRIPTION_SOFT_MAX_WORDS,
            "extraction": tier,
        })

    skills.sort(key=lambda s: (-s["description_words"], s["name"]))
    file_words = sum(s["description_words"] for s in skills)
    return {
        "surface": "skill-descriptions", "key": _SKILL_INDEX_KEY,
        "load_class": "unconditional", "state": "ok",
        "file_words": file_words, "file_tokens_est": _tokens_est(file_words),
        "managed_words": None, "managed_entries": None, "managed_share": None,
        "flagged": False,
        "skills": skills, "skills_total": len(skills) + unreadable,
        "skills_strict": strict, "skills_lenient": lenient,
        "skills_unreadable": unreadable,
    }


def _one_unpathed_row(scope_label: str, stem: str, topic_file: Path) -> dict:
    key = f"{scope_label}:{stem}"
    # u-cap code gate r1, NIT N6: the row's `state` enum names "absent"
    # (spec sec 4.2) distinctly from "unreadable" -- a topic file that has
    # since been removed (the co-firing scan that names this stem raced a
    # deletion) is a different fact than one that exists but cannot be
    # read/decoded. Checked BEFORE the read, same convention as
    # `_resolve_user_claude_md_row`/`_resolve_project_rows` above.
    if not topic_file.is_file():
        return {
            "surface": "unpathed-rules", "key": key,
            "load_class": "unconditional", "state": "absent",
            "file_words": None, "file_tokens_est": None,
            "managed_words": None, "managed_entries": None,
            "managed_share": None, "flagged": False,
        }
    try:
        text = topic_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {
            "surface": "unpathed-rules", "key": key,
            "load_class": "unconditional", "state": "unreadable",
            "file_words": None, "file_tokens_est": None,
            "managed_words": None, "managed_entries": None,
            "managed_share": None, "flagged": False,
        }
    words = _words(text)
    return {
        "surface": "unpathed-rules", "key": key,
        "load_class": "unconditional", "state": "ok",
        "file_words": words, "file_tokens_est": _tokens_est(words),
        "managed_words": None, "managed_entries": None,
        "managed_share": None, "flagged": False,
    }


def _unpathed_rules_rows(
    user_row: dict, project_rows: list[dict]
) -> list[dict]:
    """U-cap §4.2's `unpathed-rules` rows — one per stem in
    `_rules_cofire(rules_dir)["unpathed"]`, per resolvable rules dir."""
    from .verbs import _project_rules_dir, _rules_cofire, _user_rules_dir

    rows: list[dict] = []
    user_target = user_row.get("target")
    if user_target is not None:
        rules_dir = _user_rules_dir(user_target)
        cofire = _rules_cofire(rules_dir if rules_dir.is_dir() else None)
        for stem in cofire["unpathed"]:
            rows.append(_one_unpathed_row("user", stem, rules_dir / f"{stem}.md"))
    for prow in project_rows:
        spec = prow.get("spec")
        if spec is None:
            continue
        rules_dir = _project_rules_dir(spec.host_path)
        cofire = _rules_cofire(rules_dir if rules_dir.is_dir() else None)
        for stem in cofire["unpathed"]:
            rows.append(
                _one_unpathed_row(prow["key"], stem, rules_dir / f"{stem}.md")
            )
    return rows


def _budget_signal(home: Path) -> tuple[dict, dict, list[dict]]:
    """U-cap §4.2: the `budget` signal. Returns `(signal, user_row_internal,
    project_rows_internal)` — the internal working rows are reused by
    `composition`/`crowding`/`conditional.rules_cofire` so every signal
    reads the SAME resolved target/compile set, never a second resolution
    that could disagree (T4.9's word-count-parity rule, generalized)."""
    user_internal = _resolve_user_claude_md_row(home)
    project_internal = _resolve_project_rows(home)
    skill_row = _skill_description_row(home)
    unpathed_rows = _unpathed_rules_rows(user_internal, project_internal)

    def _claude_md_row(surface_name: str, key: str, internal: dict) -> dict:
        if internal["state"] != "ok":
            return {
                "surface": surface_name, "key": key,
                "load_class": "unconditional", "state": internal["state"],
                "file_words": None, "file_tokens_est": None,
                "managed_words": None, "managed_entries": None,
                "managed_share": None, "flagged": False,
            }
        section = internal["section"]
        file_words = _words(internal["text"])
        managed_share = (
            round(section.word_count / file_words, 3) if file_words else None
        )
        return {
            "surface": surface_name, "key": key,
            "load_class": "unconditional", "state": "ok",
            "file_words": file_words,
            "file_tokens_est": _tokens_est(file_words),
            "managed_words": section.word_count,
            "managed_entries": section.entry_count,
            "managed_share": managed_share, "flagged": False,
        }

    user_row = _claude_md_row("user-claude-md", "~/.claude/CLAUDE.md", user_internal)
    project_rows = [
        _claude_md_row("project-claude-md", p["key"], p) for p in project_internal
    ]

    surfaces = [user_row, *project_rows, skill_row, *unpathed_rows]
    surfaces_total = len(surfaces)
    surfaces_measured = sum(1 for r in surfaces if r["state"] == "ok")
    surfaces_unmeasured = surfaces_total - surfaces_measured
    totals_are_lower_bound = (
        surfaces_unmeasured > 0 or skill_row.get("skills_unreadable", 0) > 0
    )

    baseline_ok = [
        r for r in (user_row, skill_row, *unpathed_rows) if r["state"] == "ok"
    ]
    ok_project = [r for r in project_rows if r["state"] == "ok"]

    if surfaces_measured == 0:
        session_baseline_words = None
        session_baseline_tokens_est = None
        largest_project_words = None
        largest_project_key = None
        session_max_words = None
        session_max_tokens_est = None
        all_hosts_words = None
        flagged: bool | None = None
    else:
        session_baseline_words = sum(r["file_words"] for r in baseline_ok)
        session_baseline_tokens_est = _tokens_est(session_baseline_words)
        if ok_project:
            largest = max(ok_project, key=lambda r: r["file_words"])
            largest_project_words = largest["file_words"]
            largest_project_key = largest["key"]
        else:
            largest_project_words = None
            largest_project_key = None
        session_max_words = session_baseline_words + (largest_project_words or 0)
        session_max_tokens_est = _tokens_est(session_max_words)
        all_hosts_words = session_baseline_words + sum(
            r["file_words"] for r in ok_project
        )
        flagged = session_baseline_words >= SESSION_BASELINE_WORDS_ADVISORY

    if flagged:
        candidates = [r for r in (user_row, skill_row, *unpathed_rows) if r["state"] == "ok"]
        if candidates:
            max(candidates, key=lambda r: r["file_words"])["flagged"] = True

    signal = {
        "severity": "informational",
        "window_days": _REFERENCE_WINDOW_DAYS,
        "surfaces": surfaces,
        "session_baseline_words": session_baseline_words,
        "session_baseline_tokens_est": session_baseline_tokens_est,
        "largest_project_words": largest_project_words,
        "largest_project_key": largest_project_key,
        "session_max_words": session_max_words,
        "session_max_tokens_est": session_max_tokens_est,
        "project_rows_total": len(project_internal),
        "all_hosts_words": all_hosts_words,
        "surfaces_total": surfaces_total,
        "surfaces_measured": surfaces_measured,
        "surfaces_unmeasured": surfaces_unmeasured,
        "totals_are_lower_bound": totals_are_lower_bound,
        "flagged": flagged,
    }
    return signal, user_internal, project_internal


def _composition_signal(
    today: date, user_internal: dict, project_internal: list[dict]
) -> dict:
    """U-cap §4.4: the `composition` signal — managed-share drift,
    reconstructed by recompiling the section from the SUBSET of the
    compile set routed before `window_start` (the same pure
    `compile_managed_text`, no second parser)."""
    window_start_iso = str(today - timedelta(days=_REFERENCE_WINDOW_DAYS))

    def _one(surface_name: str, key: str, internal: dict) -> dict:
        if internal["state"] != "ok":
            return {
                "surface": surface_name, "key": key, "state": internal["state"],
                "managed_share": None, "managed_words": None,
                "managed_words_30d_ago": None, "managed_words_delta_30d": None,
                "managed_share_growth_30d_pp": None,
                "managed_share_30d_ago": None, "kind_mix": None,
                "caution_share": None, "flagged": False, "flagged_by": [],
            }
        records = internal["records"]
        section = internal["section"]
        file_words = _words(internal["text"])
        managed_words = section.word_count
        managed_share = (
            round(managed_words / file_words, 3) if file_words else None
        )

        past_set = [
            r for r in records
            if _iso((r.routing or {}).get("routed_at") or "") < window_start_iso
        ]
        managed_words_30d_ago = compile_managed_text("", past_set).word_count
        managed_words_delta_30d = managed_words - managed_words_30d_ago
        managed_share_growth_30d_pp = (
            round(100 * managed_words_delta_30d / file_words, 1)
            if file_words
            else None
        )

        from .records import KINDS

        kinds: Counter = Counter()
        for r in records:
            k = r.kind
            kinds[k if k in KINDS else "unclassified"] += 1
        kind_mix = {
            "anti-pattern": kinds.get("anti-pattern", 0),
            "surface-rule": kinds.get("surface-rule", 0),
            "reasoning-pattern": kinds.get("reasoning-pattern", 0),
            "unclassified": kinds.get("unclassified", 0),
        }
        behavior_total = (
            kind_mix["anti-pattern"]
            + kind_mix["surface-rule"]
            + kind_mix["reasoning-pattern"]
        )
        caution_share = (
            round(kind_mix["anti-pattern"] / behavior_total, 3)
            if behavior_total
            else None
        )

        flagged_by: list[str] = []
        if managed_share is not None and managed_share >= COMPOSITION_SHARE_ADVISORY:
            flagged_by.append("share")
        if (
            managed_share_growth_30d_pp is not None
            and managed_share_growth_30d_pp >= COMPOSITION_GROWTH_PP_ADVISORY
        ):
            flagged_by.append("growth")
        if caution_share is not None and caution_share >= COMPOSITION_CAUTION_ADVISORY:
            flagged_by.append("caution")

        return {
            "surface": surface_name, "key": key, "state": "ok",
            "managed_share": managed_share, "managed_words": managed_words,
            "managed_words_30d_ago": managed_words_30d_ago,
            "managed_words_delta_30d": managed_words_delta_30d,
            "managed_share_growth_30d_pp": managed_share_growth_30d_pp,
            "managed_share_30d_ago": None,
            "kind_mix": kind_mix, "caution_share": caution_share,
            "flagged": bool(flagged_by), "flagged_by": flagged_by,
        }

    surfaces = [_one("user-claude-md", "~/.claude/CLAUDE.md", user_internal)]
    surfaces.extend(
        _one("project-claude-md", p["key"], p) for p in project_internal
    )

    surfaces_total = len(surfaces)
    surfaces_measured = sum(1 for r in surfaces if r["state"] == "ok")
    surfaces_unmeasured = surfaces_total - surfaces_measured
    flagged = None if surfaces_measured == 0 else any(r["flagged"] for r in surfaces)

    return {
        "severity": "informational",
        "window_days": _REFERENCE_WINDOW_DAYS,
        "window_start": window_start_iso,
        "past_is_lower_bound": True,
        "surfaces": surfaces,
        "surfaces_total": surfaces_total,
        "surfaces_measured": surfaces_measured,
        "surfaces_unmeasured": surfaces_unmeasured,
        "flagged": flagged,
    }


def _crowding_signal(
    home: Path, user_internal: dict, project_internal: list[dict]
) -> dict:
    """U-cap §4.3: report-only near-duplicate pairs, scored by
    `worker.pair_similarity` (deferred import: import-safe without the
    optional SDK extra, the same posture worker.py's OWN deferred-import
    callers already rely on) over doc frequencies drawn from the GLOBAL
    pool `cluster_candidates` uses — never the compile set alone (B3's
    degeneracy: a 2-doc corpus makes every shared token's idf collapse to
    `log(1) == 0`)."""
    from .ledger import discover_buckets
    from .ledger_ops import queue
    from .worker import CANDIDATE_SCORE_FLOOR, _tokens, pair_similarity

    pool: list[tuple[str, set]] = []
    for bucket in discover_buckets(home):
        for entry in queue(bucket, include_deferred=True):
            pool.append((entry.record.id, _tokens(record_title_safe(entry.record))))
        resolved_dir = bucket.path / "resolved"
        if not resolved_dir.is_dir():
            continue
        for path in sorted(resolved_dir.glob("lrn-*.md")):
            try:
                routed = Record.from_path(path)
            except (RecordError, OSError, UnicodeDecodeError, YAMLError):
                continue
            if routed.status != "routed":
                continue
            pool.append((routed.id, _tokens(record_title_safe(routed))))

    n_docs = len(pool)
    doc_freq: dict[str, int] = {}
    tokens_by_id: dict[str, set] = {}
    for rid, toks in pool:
        tokens_by_id[rid] = toks
        for t in toks:
            doc_freq[t] = doc_freq.get(t, 0) + 1

    def _score(records: list) -> tuple[str, list, int | None, int]:
        ids = [r.id for r in records]
        if len(ids) < 2:
            return "too-few-entries", [], None, len(ids)
        pairs = []
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                ta = tokens_by_id.get(a, set())
                tb = tokens_by_id.get(b, set())
                score = pair_similarity(ta, tb, doc_freq, n_docs)
                if score >= CANDIDATE_SCORE_FLOOR:
                    pairs.append({"a": a, "b": b, "score": round(score, 3)})
        pairs.sort(key=lambda p: (-p["score"], p["a"], p["b"]))
        return "ok", pairs[:5], len(pairs), len(ids)

    surfaces: list[dict] = []

    def _one(surface_name: str, key: str, internal: dict) -> None:
        if internal["state"] != "ok" or internal.get("records") is None:
            surfaces.append({
                "surface": surface_name, "key": key, "state": internal["state"],
                "entries_considered": None, "pairs": [], "pairs_total": None,
                "flagged": False,
            })
            return
        state, pairs, pairs_total, considered = _score(internal["records"])
        surfaces.append({
            "surface": surface_name, "key": key, "state": state,
            "entries_considered": considered, "pairs": pairs,
            "pairs_total": pairs_total,
            "flagged": bool(pairs_total) if pairs_total is not None else False,
        })

    _one("user-claude-md", "~/.claude/CLAUDE.md", user_internal)
    for prow in project_internal:
        _one("project-claude-md", prow["key"], prow)

    surfaces_total = len(surfaces)
    surfaces_measured = sum(
        1 for r in surfaces if r["state"] in ("ok", "too-few-entries")
    )
    surfaces_unmeasured = surfaces_total - surfaces_measured
    flagged = None if surfaces_measured == 0 else any(r["flagged"] for r in surfaces)

    return {
        "severity": "informational",
        "score_floor": CANDIDATE_SCORE_FLOOR,
        "source": "worker.pair_similarity",
        "corpus": "global-pool",
        "corpus_docs": n_docs,
        "surfaces": surfaces,
        "surfaces_total": surfaces_total,
        "surfaces_measured": surfaces_measured,
        "surfaces_unmeasured": surfaces_unmeasured,
        "flagged": flagged,
    }


def record_title_safe(record) -> str:
    """`ledger_ops.record_title`, imported where the crowding signal needs
    it — a tiny wrapper so the deferred-import block above stays a flat
    list of names (record_title lives in `ledger_ops`, not `worker`)."""
    from .ledger_ops import record_title

    return record_title(record)


def _current_skill_description_words(home: Path, name: str) -> int | None:
    """The word count of skill `name`'s CURRENT description, or `None`
    when the skill/its SKILL.md/its description is unresolvable — §5.2's
    dedup rule reads THIS, never the description text captured at route
    time (a route only ever names the skill; the description may have
    been hand-edited since)."""
    from .hosts import HostsError, load_hosts, skill_dir_for

    try:
        hosts = load_hosts(home)
        skill_dir = skill_dir_for(hosts, name)
    except HostsError:
        return None
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    desc, _tier = _extract_skill_description(text)
    if desc is None:
        return None
    return _words(desc)


def _growth_signal(home: Path, today: date, budget: dict, composition: dict) -> dict:
    """U-cap §4.4.3: the growth-rate alarm — the SAME reconstruction
    technique, aggregated across Class A, plus the `new-skill` charging
    door (§5.2) the old cap treated as free. Only BASELINE surfaces
    contribute (§4.2.1): a project host's growth is not a cost every
    session pays."""
    window_start_iso = str(today - timedelta(days=_REFERENCE_WINDOW_DAYS))

    user_comp_row = next(
        (r for r in composition["surfaces"] if r["surface"] == "user-claude-md"),
        None,
    )
    if user_comp_row is not None and user_comp_row["state"] == "ok":
        managed_words_added_30d = user_comp_row["managed_words_delta_30d"]
        managed_measured = True
    else:
        managed_words_added_30d = None
        managed_measured = False

    new_skill_routes_30d = 0
    distinct_skills: dict[str, bool] = {}
    desc_words_sum = 0
    any_skill_unreadable = False
    for record in _walk_records(home):
        if record.status != "routed" or record.superseded_by is not None:
            continue
        routing = record.routing or {}
        if routing.get("destination") != "new-skill":
            continue
        if _iso(routing.get("routed_at") or "") < window_start_iso:
            continue
        new_skill_routes_30d += 1
        name = routing.get("new_skill")
        if not name or name in distinct_skills:
            continue
        distinct_skills[name] = True
        words = _current_skill_description_words(home, name)
        if words is None:
            any_skill_unreadable = True
        else:
            desc_words_sum += words

    new_skill_description_words_added_30d = desc_words_sum if distinct_skills else 0

    if managed_measured:
        always_on_words_added_30d = (
            managed_words_added_30d + new_skill_description_words_added_30d
        )
    else:
        always_on_words_added_30d = None

    session_baseline_words = budget["session_baseline_words"]
    if (
        always_on_words_added_30d is not None
        and always_on_words_added_30d > 0
        and session_baseline_words is not None
    ):
        doubling_days_est = round(
            30 * session_baseline_words / always_on_words_added_30d, 1
        )
    else:
        doubling_days_est = None

    flagged = (
        always_on_words_added_30d is not None
        and always_on_words_added_30d >= GROWTH_ALARM_WORDS_PER_30D
    )

    return {
        "severity": "informational",
        "window_days": _REFERENCE_WINDOW_DAYS,
        "window_start": window_start_iso,
        "past_is_lower_bound": True,
        "managed_words_added_30d": managed_words_added_30d,
        "new_skill_routes_30d": new_skill_routes_30d,
        "new_skill_description_words_added_30d": new_skill_description_words_added_30d,
        "always_on_words_added_30d": always_on_words_added_30d,
        "session_baseline_words": session_baseline_words,
        "doubling_days_est": doubling_days_est,
        "threshold_words_per_30d": GROWTH_ALARM_WORDS_PER_30D,
        "flagged": bool(flagged),
        "totals_are_lower_bound": bool(any_skill_unreadable or not managed_measured),
    }


def reference_read_verdict(
    home: Path | str, today: date, *, flush_state: str = "not-attempted"
) -> dict:
    """U-cap §4.5: one call to :func:`_reference_shelf`, reduced to the
    verdict on whether `reference` is a safe overflow target RIGHT NOW.
    Reads nothing else; derives no count of its own."""
    shelf = _reference_shelf(home, today, flush_state=flush_state)
    if not shelf["instrumented"]:
        state, safe = "not-instrumented", None
    elif shelf["enumeration_state"] == "none-enumerable":
        state, safe = "none-enumerable", None
    elif shelf["observation_start"] is None:
        # U-cap plan v2 §2 (M-A) / code-gate r1 fold MINOR m1: no
        # `reference-read` event has ever been recorded anywhere in the
        # tracked plane. Within this `instrumented`/enumerable region,
        # "every target zero-read" (`targets_zero_read == targets_total`)
        # can ONLY hold when `observation_start is None`: any event with a
        # valid timestamp anywhere in the ledger makes `observation_start`
        # non-None, and that event's own target always lands in `rows`
        # with `reads_all_time >= 1` (every `events_by_target` key is
        # folded into `rows`, merged or newly created, above). So this
        # branch subsumes what used to be a separate `no-reads-observed`
        # state (removed: it could never be reached once this branch
        # ran first) — the JSON contract now emits `never-observed`
        # where it once emitted `no-reads-observed`. Distinct meaning
        # from a genuine "observed and came back cold": observation
        # never started at all. `safe_overflow: None` (unknown, not
        # "unsafe").
        state, safe = "never-observed", None
    elif shelf["targets_zero_read"]:
        state, safe = "partly-cold", False
    else:
        state, safe = "ok", True

    return {
        "source": "reference_shelf",
        "read_rate_state": state,
        "safe_overflow": safe,
        "counts_are_lower_bound": shelf["flush_state"] != "ok",
        "targets_total": shelf["targets_total"],
        "targets_zero_read": shelf["targets_zero_read"],
        "records_on_zero_read_targets": shelf["records_on_zero_read_targets"],
        "reads_30d_total": shelf["reads_30d_total"],
        "why": _REFERENCE_WHY[state],
        "severity": "informational",
    }


def _rules_cofire_signal(
    home: Path, user_internal: dict, project_internal: list[dict]
) -> dict:
    """U-cap §4.6: consumes `_rules_cofire` (U-glob, shipped) unchanged;
    only the CONSEQUENCE changes — the retired escalation-into-the-old-
    threshold OR-in becomes its own report-only `crowded` field per scope."""
    from .verbs import _project_rules_dir, _rules_cofire, _user_rules_dir

    scopes: list[dict] = []

    def _one(scope_label: str, key: str, rules_dir: Path | None) -> None:
        if rules_dir is None:
            scopes.append({
                "scope": scope_label, "key": key, "state": "absent",
                "topics": [], "unpathed": [], "pairs": [], "max_fanin": 0,
                "max_fanin_is_upper_bound": True, "crowded": False,
            })
            return
        exists = rules_dir.is_dir()
        cofire = _rules_cofire(rules_dir if exists else None)
        scopes.append({
            "scope": scope_label, "key": key,
            "state": "ok" if exists else "absent",
            "topics": cofire["topics"], "unpathed": cofire["unpathed"],
            "pairs": cofire["pairs"], "max_fanin": cofire["max_fanin"],
            "max_fanin_is_upper_bound": True,
            "crowded": cofire["max_fanin"] > _COFIRE_MAX_FANIN_ADVISORY,
        })

    user_target = user_internal.get("target")
    _one(
        "user", "~/.claude/rules",
        _user_rules_dir(user_target) if user_target is not None else None,
    )
    for prow in project_internal:
        spec = prow.get("spec")
        if spec is None:
            continue
        _one("project", prow["key"], _project_rules_dir(spec.host_path))

    scopes_total = len(scopes)
    scopes_measured = sum(1 for s in scopes if s["state"] in ("ok", "absent"))
    scopes_unmeasured = scopes_total - scopes_measured
    flagged = None if scopes_measured == 0 else any(s["crowded"] for s in scopes)

    return {
        "severity": "informational",
        "threshold_max_fanin": _COFIRE_MAX_FANIN_ADVISORY,
        "scopes": scopes,
        "scopes_total": scopes_total,
        "scopes_measured": scopes_measured,
        "scopes_unmeasured": scopes_unmeasured,
        "flagged": flagged,
    }


def context_budget(
    home: Path | str, today: date, *, flush_state: str = "not-attempted"
) -> dict:
    """U-cap §4: the report-only context budget. Four signals — `budget`,
    `crowding`, `composition`, `growth` — plus `conditional.reference` /
    `conditional.rules_cofire`. Every block's `severity` is the literal
    `"informational"`; nothing here refuses, gates, or changes an exit
    code (§4.0.1)."""
    home = Path(home)
    budget, user_internal, project_internal = _budget_signal(home)
    composition = _composition_signal(today, user_internal, project_internal)
    crowding = _crowding_signal(home, user_internal, project_internal)
    growth = _growth_signal(home, today, budget, composition)

    return {
        "generated_for": str(today),
        "tokens_per_word_est": TOKENS_PER_WORD_EST,
        "budget": budget,
        "crowding": crowding,
        "composition": composition,
        "growth": growth,
        "conditional": {
            "reference": reference_read_verdict(home, today, flush_state=flush_state),
            "rules_cofire": _rules_cofire_signal(home, user_internal, project_internal),
        },
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

    checked: int | None = len(rows)
    reachable_n = sum(1 for r in rows if r.state == "reachable")
    unreachable_n = sum(1 for r in rows if r.state == "unreachable")
    unmeasurable_n: int | None = sum(1 for r in rows if r.state == "unmeasurable")

    by_destination: dict[str, dict] = {
        key: {"reachable": 0, "unreachable": 0, "unmeasurable": 0}
        for key in _SURFACE_REACH_KEYS
    }
    for r in rows:
        by_destination[_surface_variant_key(r)][r.state] += 1

    # §6 rule 2: nulling is PER FACET, never blanket, for THIS gate
    # (`claude_dir_usable`/`settings_usable`). `unparseable_records` and
    # `rows` always render regardless of instrument state.
    #
    # Fold r1 / M-F3 m2 (orchestrator ruling — "null only what's
    # unmeasured, keep what the instrument measured"): the original
    # build added a THIRD gate here keyed on `instrument_state ==
    # "settings-absent"` that blanket-nulled `checked`/`unmeasurable`
    # and every `by_destination` value for that state. That gate's
    # premise does not hold against the actual reachability predicates:
    # `_rp_hook` has an explicit `instrument.state == "settings-absent"`
    # branch returning a confident `unreachable/no-registrations`
    # (reachability.py:562), and `_rp_skill` (shared by `skill-md` and
    # `new-skill` via `_verdict_for`) has no settings-absent special
    # case at all — it falls through on empty `enabled_plugins`/
    # `skill_overrides` to a confident `unreachable/not-indexed` (or a
    # real `reachable` via a personal skill symlink). Verified directly
    # against the running predicates (source read of both functions,
    # plus two throwaway probe scripts exercising `_rp_skill`/
    # `reachability_rows` under a constructed settings-absent
    # `Instrument`): every one of `_SETTINGS_DEPENDENT_KEYS`
    # (`skill-md`, `new-skill`, `hook`) gets a genuine, non-null verdict
    # when settings.json is merely absent — settings-absent measures
    # everything, it just usually measures "unreachable" because
    # nothing can register without settings.json content. Nulling those
    # facets for that state was the exact "blanks facets that were
    # measured" bug B-15 exists to fix, just for three keys instead of
    # six. The settings-absent gate is removed; only the two REAL
    # per-facet gates below (keyed on `claude_dir_usable`/
    # `settings_usable`, which stay True for settings-absent by design
    # per test_instrument_four_states) still null anything, and now
    # `checked`/`unmeasurable` are wired into the first of those —
    # they are corpus-wide aggregates over `_SETTINGS_DEPENDENT_KEYS`
    # rows among others, so when that gate fires (settings-unparseable,
    # or claude-dir-absent) the totals are a sum over partial facets
    # and must be null too, not a concrete count that reads as
    # "measured, and empty".
    if not claude_dir_usable or not settings_usable:
        checked = None
        unmeasurable_n = None
        for key in _SETTINGS_DEPENDENT_KEYS:
            by_destination[key] = {"reachable": None, "unreachable": None, "unmeasurable": None}
    # Fold r2 / M-F3 MINOR 1 (orchestrator ruling): a facet is nulled here
    # when ANY row aggregated into it is unmeasurable, because a partial
    # total lies — the same rule the fold above applies to the top-level
    # counts. The measured project-scope claude-md rows stay visible per
    # record in `rows`, not in this facet total.
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
    # U-dismiss §7c: flat rows across EVERY record regardless of status —
    # collected in the per-record loop below, immediately after
    # `Record.from_path` and before any status branching, so a dismissal
    # survives the target record later being superseded (§7c's load-
    # bearing placement; see the comment at the collection site).
    suspects_dismissed: list[dict] = []
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
                    # U-dismiss §7c: BEFORE the status branching below —
                    # the dismissal plane must outlive the rule it was
                    # made against (superseded records keep their file
                    # here; this is what makes T-DISMISSALS-SURVIVE-
                    # SUPERSEDE hold).
                    for entry in record.dismissed_suspects:
                        suspects_dismissed.append(
                            {
                                "id": record.id,
                                "ref": entry.get("ref"),
                                "ts": entry.get("ts"),
                                "dismissed_at": entry.get("dismissed_at"),
                                "basis": entry.get("basis"),
                                "why": entry.get("why"),
                            }
                        )
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
                            "dismissed_suspects": len(record.dismissed_suspects),
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
        "suspects_dismissed": suspects_dismissed,
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
        "context_budget": context_budget(home, today, flush_state=flush_state),
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

    # u-cap code gate r1, MAJOR 4: `render_text` never consumed
    # `context_budget` at all (a `self-learn report` without --json
    # showed none of this unit). Sec 4.0.1 names a text-render line a
    # PERMITTED effect of a signal; this block is that line, covering the
    # obligations the gate named unimplemented: sec 4.0.5 (a total
    # computed while surfaces_unmeasured > 0 is a lower bound, and the
    # text must say so, not just the JSON), sec 4.2 (name the lenient
    # skill-description extraction count when non-zero, so a reader knows
    # which arithmetic produced the figure), sec 4.2.1 (`all_hosts_words`
    # is a diagnostic ONLY and must be labelled "not a session cost", never
    # presented as something compared against), sec 4.4.1
    # (`past_is_lower_bound` is an emitted field, not a comment -- print it
    # whenever a reconstructed delta is non-null, on both composition's
    # and growth's halves of the SAME reconstruction technique).
    cb = facts.get("context_budget")
    if cb is not None:
        lines.append("")
        lines.append(f"Context budget ({cb['generated_for']}):")
        budget = cb["budget"]
        if budget["flagged"] is None:
            # tri-state: null is NOT an all-clear (sec 4.0.3/4.2.2) --
            # must read distinctly from both "flagged" and "not flagged".
            lines.append(
                "  budget: could not measure — no baseline surface was "
                "readable this session"
            )
        else:
            flag = " [flagged]" if budget["flagged"] else ""
            lower = (
                " (lower bound — some surfaces unmeasured)"
                if budget["totals_are_lower_bound"]
                else ""
            )
            lines.append(
                f"  session baseline: {budget['session_baseline_words']} words "
                f"(~{budget['session_baseline_tokens_est']} tokens est)"
                f"{lower}{flag}"
            )
            if budget["largest_project_key"] is not None:
                lines.append(
                    f"  worst single session (baseline + largest project "
                    f"{budget['largest_project_key']}): "
                    f"{budget['session_max_words']} words "
                    f"(~{budget['session_max_tokens_est']} tokens est)"
                )
            if budget["all_hosts_words"] is not None:
                lines.append(
                    f"  all registered project hosts summed: "
                    f"{budget['all_hosts_words']} words "
                    "(diagnostic — not a session cost)"
                )
            skill_row = next(
                (r for r in budget["surfaces"] if r["surface"] == "skill-descriptions"),
                None,
            )
            if skill_row is not None and skill_row.get("skills_lenient"):
                lines.append(
                    f"  skill-descriptions: {skill_row['skills_lenient']} of "
                    f"{skill_row['skills_total']} description(s) extracted "
                    "via the lenient fallback"
                )

        composition = cb["composition"]
        comp_rows = [r for r in composition["surfaces"] if r["state"] == "ok"]
        if comp_rows:
            lines.append("  composition (managed share of always-on files):")
            for row in comp_rows:
                delta = row["managed_words_delta_30d"]
                flag = " [flagged]" if row["flagged"] else ""
                delta_part = ""
                if delta is not None:
                    lower = (
                        " — lower bound (reconstructed past under-counts "
                        "retired records)"
                        if composition["past_is_lower_bound"]
                        else ""
                    )
                    delta_part = f", +{delta} managed words/30d{lower}"
                lines.append(
                    f"    {row['key']}: {_pct(row['managed_share'])} managed"
                    f"{delta_part}{flag}"
                )

        growth = cb["growth"]
        if growth["always_on_words_added_30d"] is not None:
            notes = []
            if growth["past_is_lower_bound"]:
                notes.append(
                    "lower bound — reconstructed past under-counts retired records"
                )
            if growth["totals_are_lower_bound"]:
                notes.append("some surfaces unmeasured")
            note = f" ({'; '.join(notes)})" if notes else ""
            doubling = (
                f", doubling in ~{growth['doubling_days_est']}d"
                if growth["doubling_days_est"] is not None
                else ""
            )
            flag = " [flagged]" if growth["flagged"] else ""
            lines.append(
                f"  growth: +{growth['always_on_words_added_30d']} always-on "
                f"words/30d{note}{doubling}{flag}"
            )

    sr = facts.get("surface_reach")
    if sr is not None:
        lines.append("")
        # Fold r1 / M-F3 BLOCKER: `sr["checked"]`/`sr["unmeasurable"]` are
        # `None` whenever the per-facet gate in `_surface_reach` fires
        # (settings-unparseable, claude-dir-absent) — interpolating them
        # raw used to print the literal string "None" into the
        # human-facing report ("None record(s) checked"). Guard both.
        checked_txt = (
            "NOT MEASURED"
            if sr["checked"] is None
            else f"{sr['checked']} record(s) checked"
        )
        # Fold r2 / M-F3 NIT 1: `unmeasurable_txt`'s "NOT MEASURED" arm is
        # unreachable today (checked/unmeasurable are nulled together with
        # reachable/unreachable, so the branch below always takes the
        # top-level NOT MEASURED path first) — kept as defence in depth
        # against a future change decoupling the two.
        unmeasurable_txt = (
            "NOT MEASURED" if sr["unmeasurable"] is None else str(sr["unmeasurable"])
        )
        lines.append(f"Surface reach ({checked_txt}, instrument: {sr['instrument_state']}):")
        if sr["reachable"] is None or sr["unreachable"] is None:
            lines.append(
                "  NOT MEASURED (top-level reachable/unreachable) — a depended-on "
                f"facet is unusable (claude_dir_usable={sr['claude_dir_usable']}, "
                f"settings_usable={sr['settings_usable']})"
            )
        else:
            lines.append(
                f"  {sr['reachable']} reachable, {sr['unreachable']} unreachable, "
                f"{unmeasurable_txt} unmeasurable"
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
