"""Background pre-analysis worker (T13/T14, 08 §7.1 pins; 11's M2 riders).

Kick-driven, never scheduled (E-5): `teach` (without --route) and
`import` end by calling :func:`kick`. Kick mechanics, pinned:

1. ``touch worker.dirty``;
2. under ``flock -n worker.spawn.lock`` (two racing kicks serialize; the
   loser exits absorbed): if ``worker.window`` names a LIVE pid → exit
   (the open window absorbs the kick); else ``setsid``-spawn
   ``self-learn worker run --coalesce`` and write the child pid to
   ``worker.window``. A dead pid in ``worker.window`` = closed window
   (reboot/kill safe).

``--coalesce`` sleeps ``SELF_LEARN_COALESCE_SECS`` (default 600; tests
set ~0), then takes ``worker.lock`` (blocking), removes ``worker.window``
and runs. ``worker.dirty`` is deleted AFTER enumeration, so a kick
landing mid-run re-marks it; at run end, if it exists again, ONE
follow-on window is spawned.

The run sequence and every file it touches are pinned in 08 §7.1
("Worker run sequence" row). The model pass writes PROPOSALS ONLY
(S-5/E-18): the ``--allowedTools`` value carries no Bash and no Edit —
with shell access the write restriction would be void. The CLI stamps
``record_sha`` into every valid proposal (models cannot compute hashes).

11's rider carried here: recurrence-SUSPECT detection is deterministic
CLI machinery (token overlap + origin match against resolved routed
records), spooled as telemetry events — the machine never writes a
record; confirmation is the human ``confirm-recurrence`` verb.

Test hook: ``SELF_LEARN_WORKER_AUTOKICK=0`` makes :func:`kick` a logged
no-op — the test suite sets it globally (conftest) so unrelated
teach/import tests never spawn detached processes; worker tests opt back
in (``monkeypatch.delenv``) or drive :func:`run` directly. The SAME
switch also gates the run-end follow-on window inside :func:`run` (see
:func:`_autokick_disabled` — incident 2026-08-09: it did not, until a
test's leftover batch drove a real, self-respawning detached chain).
Tests exercising the follow-on's spawn DECISION (batch cap, backoff
counter, mid-run-kick re-trigger) must both mock ``_spawn_window`` AND
``monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK")`` — same convention as
:func:`kick` tests — so the mock is what's asserted on, never a real
process.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import sentinel, telemetry
from .compilers import BEGIN_MARKER, END_MARKER
from .hosts import Hosts, HostsError, load_hosts, skill_dir_for
from .ledger import discover_buckets, resolve_home
from .ledger_ops import bucket_project_path
from .scan import scan as secret_scan
from .ledger_ops import (
    ROSTER_UNAVAILABLE,
    TRACE_FS_VERDICTS,
    ProposalError,
    _dump_yaml,
    is_unanalyzed,
    queue,
    read_proposal,
    record_title,
    stamp_proposal,
    validate_merge_proposal,
    validate_proposal,
)
from .normalize import sha_anchor
from .records import Record, RecordError

__all__ = [
    "ALLOWED_TOOLS",
    "CANDIDATE_CAP",
    "CANDIDATE_SCORE_FLOOR",
    "Candidate",
    "DEFAULT_COALESCE_SECS",
    "DEFAULT_WORKER_MODEL",
    "DISALLOWED_TOOLS",
    "FOLLOWON_DEPTH_CEILING",
    "FOLLOWON_DEPTH_ENV",
    "FOLLOWON_FAILURE_CAP",
    "REPAIR_TIMEOUT_SECS",
    "Roster",
    "RunResult",
    "TRACE_CONDITIONALS",
    "batch_cap",
    "build_argv",
    "cache_dir",
    "canon_excerpt",
    "cluster_candidates",
    "compose_batch_prompt",
    "compose_record_block",
    "compose_single_prompt",
    "invoke_timeout_secs",
    "kick",
    "package_skill_refs",
    "path_roster",
    "repair_timeout_secs",
    "run",
    "skill_roster",
    "write_permission_rules",
    "write_repair_settings_file",
    "write_settings_file",
]

DEFAULT_COALESCE_SECS = 600
DEFAULT_WORKER_MODEL = "claude-sonnet-5"
BATCH_CAP = 15
#: U-repair §3.9 — 900s (the pre-U-repair default) is a coin flip against
#: the measured maximum (857s live, 745s replayed, both at batch 15);
#: 1800s is ~2.1x that measurement. Env-overridable via
#: SELF_LEARN_INVOKE_TIMEOUT_SECS (:func:`invoke_timeout_secs`).
INVOKE_TIMEOUT_SECS = 30 * 60
#: U-repair §3.9 — the repair round's own timeout: a bounded mechanical
#: edit over a SUBSET of the batch, with none of the doctrine/roster/
#: candidate reading the first round does. Env-overridable via
#: SELF_LEARN_REPAIR_TIMEOUT_SECS (:func:`repair_timeout_secs`).
REPAIR_TIMEOUT_SECS = 10 * 60
#: U-repair §3.10 — pinned (an edit, not config — the ESCALATE_* precedent
#: below): two consecutive failed runs means FOUR model attempts (each run
#: now carries a repair round) produced nothing; beyond that the chain is
#: burning quota on a systemic defect and the staleness alarm is the
#: correct surface, not more retries.
FOLLOWON_FAILURE_CAP = 2
EVENTS_CAP_BYTES = 1_000_000
LOG_CAP_BYTES = 1_000_000

#: Escalation thresholds (08 §7.1 — v1 constants; changing them is an edit
#: to the pin, not a config file).
ESCALATE_PENDING = 5
ESCALATE_OLDEST_DAYS = 7
ESCALATE_DEBOUNCE_SECS = 24 * 60 * 60

#: Recurrence-suspect similarity threshold (11 §2.2 rider; deterministic).
SUSPECT_JACCARD = 0.6

#: U-composer §3.3 — cluster-candidate floor and rank cap, both measured
#: 2026-08-06 against a copy of the live ledger (35 pending × 31
#: routed-resolved). Floor 0.20: 6/35 pending records keep a candidate (8
#: rows total), all six top-1 pairs human-verified genuine subject
#: matches. Cap 5: the largest observed candidate list at the floor was
#: well under the cap on that corpus; A6 pins the cap as independently
#: load-bearing (a fixture with ≥6 qualifying candidates must still cut
#: at exactly 5). A bare literal in the comparison below would not carry
#: this provenance for a later reader — campaign §5's own rule.
CANDIDATE_SCORE_FLOOR = 0.20
CANDIDATE_CAP = 5


def package_skill_refs() -> Path:
    """The skill's references dir, resolved relative to THIS package
    (doc 13 T-H3: doctrine/rubric/registry ship with the product beside
    the skill — never via any home; this also pre-clears the step-2
    product-repo extraction). src/self_learn/worker.py → parents[3] is
    ``plugins/self-learn``."""
    return Path(__file__).resolve().parents[3] / "skills" / "self-learn" / "references"


# --------------------------------------------------- U-composer: the shared
# ----------------------------------------------------- prompt composer (§3)
#
# Five ingredients, one module, two prompt forms (spec §3.1): the skill
# roster (T3, §3.2), cluster candidates (T-N, §3.3), the absolute-path
# roster (§3.4), the record text, and the candidate-target canon excerpt
# (already shipped as :func:`canon_excerpt`). ``analyst.py`` imports the
# public names below rather than re-deriving them (§3.1 — the single-
# definition rule this project pays to keep).


@dataclass(frozen=True)
class Roster:
    """The T3 skill roster composed for one worker/analyst run (§3.2).
    ``sha`` is what the model is told to echo back (X3/§3.6); it covers
    the rendered TEXT, never paths or mtimes (§3.2's own rule)."""

    text: str  # the rendered block the model sees, verbatim
    sha: str  # sha_anchor(text) — or ledger_ops.ROSTER_UNAVAILABLE
    routable: int  # entries under the registered skills root
    visible_only: int  # entries visible but not routable (§3.2)


@dataclass(frozen=True)
class Candidate:
    """One T-N cluster candidate (§3.3): a pending or routed-resolved
    record whose trigger-title IDF-cosine score against the record being
    analyzed clears :data:`CANDIDATE_SCORE_FLOOR`."""

    record_id: str
    status: str  # "pending" | "routed"
    score: float
    title: str


def _flatten_ws(text: str) -> str:
    """Collapse every run of whitespace (including newlines) to one
    space, then strip — the same normalization
    :func:`ledger_ops._flatten_quote` performs for containment, kept
    local here because it is not exported from that module (§6-D4 there
    pins it non-exported; the roster/candidate renderers need the same
    shape for their own, unrelated reason — one-line descriptions and
    titles — so it is redefined here rather than reaching into another
    module's private helper)."""
    return " ".join(text.split())


def _truncate(text: str, cap: int) -> str:
    """Flatten to one line, then cap at ``cap`` characters with a
    trailing ``…`` when the flattened text is longer (§3.2/§3.3)."""
    flat = _flatten_ws(text)
    if len(flat) > cap:
        return flat[:cap].rstrip() + "…"
    return flat


def _parse_skill_frontmatter(text: str) -> tuple[str | None, str | None, bool]:
    """Parse a ``SKILL.md``'s leading ``---``-delimited frontmatter block
    with the SAFE ruamel loader (§3.2 — never a line-based grab: 11 of 43
    live descriptions are YAML block scalars, and a line grab returns the
    literal ``"|"`` for every one of them). Returns
    ``(name, description, parsed_ok)`` — ``name``/``description`` are
    ``None`` when absent or non-string; ``parsed_ok`` is ``False`` on ANY
    parse failure (A3: the caller must still render a row, never drop
    one)."""
    from ruamel.yaml import YAML

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, None, False
    try:
        close = lines[1:].index("---") + 1
    except ValueError:
        return None, None, False
    fm_text = "\n".join(lines[1:close])
    try:
        data = YAML(typ="safe").load(fm_text)
    except Exception:  # noqa: BLE001 — S6: never crash a roster build on any parser defect
        return None, None, False
    if not isinstance(data, dict):
        return None, None, False
    name = data.get("name")
    name = name if isinstance(name, str) and name.strip() else None
    desc = data.get("description")
    desc = desc if isinstance(desc, str) else None
    return name, desc, True


def skill_roster(home: Path) -> Roster:
    """Ingredient 1 — the T3 skill roster (§3.2).

    Sources, in order: (a) ``hosts.skills_root/plugins/*/skills/*/SKILL.md``
    (the same shape :func:`hosts.skill_dir_for` resolves one skill
    against); (b) ``<claude_dir>/skills/*/SKILL.md``, where ``claude_dir``
    is :func:`selfcheck.claude_runtime_dir` — imported LAZILY, matching
    the precedent at this module's own :func:`canon_excerpt` (``selfcheck``
    imports ``verbs``; this module must never gain a module-scope edge to
    either).

    Deduped by :meth:`Path.resolve` (realpath) — never a naive union
    (measured 2026-08-06: naive 53, realpath union 43 on this host, every
    root skill double-listed through a ``~/.claude/skills`` symlink).
    Routability is part of each entry, not a footnote: an entry is
    ``[routable]`` iff its realpath is reachable through source (a);
    otherwise ``[visible only — not under the registered skills root]`` —
    a route to it would raise ``HostsError`` at route time
    (``hosts.py:551-566``). An entry whose frontmatter will not parse is
    STILL rendered — ``(frontmatter unparseable)`` — never dropped: a
    dropped skill is an invisible hole in the roster T3 is judged
    against, and this fires on ~5% of this host's roster on day one
    (two live ``ScannerError``s on an unquoted ``: `` inside a plain
    scalar)."""
    from .selfcheck import claude_runtime_dir

    home = Path(home)
    try:
        hosts = load_hosts(home)
    except HostsError:
        hosts = Hosts()

    routable_paths: set[Path] = set()
    if hosts.skills_root is not None:
        for candidate in hosts.skills_root.glob("plugins/*/skills/*/SKILL.md"):
            if candidate.is_file():
                try:
                    routable_paths.add(candidate.resolve())
                except OSError:
                    continue

    claude_dir = claude_runtime_dir()
    try:
        visible_candidates = list(claude_dir.glob("skills/*/SKILL.md"))
    except OSError:
        visible_candidates = []

    all_resolved: dict[Path, None] = {}  # dict as an order-preserving set
    for candidate in [*routable_paths, *visible_candidates]:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        all_resolved.setdefault(resolved, None)

    rows: list[tuple[str, str]] = []  # (sort_key, rendered_line)
    routable_count = 0
    visible_only_count = 0
    for resolved in all_resolved:
        is_routable = resolved in routable_paths
        marker = (
            "[routable]"
            if is_routable
            else "[visible only — not under the registered skills root]"
        )
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            name = resolved.parent.name
            rows.append((name, f"- {name} {marker} (frontmatter unparseable)"))
        else:
            name, desc, ok = _parse_skill_frontmatter(text)
            if name is None:
                name = resolved.parent.name
            if ok:
                rows.append((name, f"- {name} {marker}: {_truncate(desc or '', 200)}"))
            else:
                rows.append((name, f"- {name} {marker} (frontmatter unparseable)"))
        if is_routable:
            routable_count += 1
        else:
            visible_only_count += 1

    if not rows:
        text = (
            "(skill roster unavailable — no registered skills root and no "
            "readable user skills dir)"
        )
        return Roster(text=text, sha=ROSTER_UNAVAILABLE, routable=0, visible_only=0)

    # Gate NOTE 7: name-only sort left ties (two routable skills
    # sharing a frontmatter `name:`) broken by insertion order, which
    # `routable_paths`'s SET iteration makes hash-seed-dependent —
    # measured 2 different roster shas across PYTHONHASHSEED 1..6 for
    # the same on-disk roster. `rendered_line` is real content, never
    # order-dependent — sorting on the full (name, rendered_line) pair
    # makes tie-breaking deterministic regardless of iteration order.
    rows.sort(key=lambda pair: (pair[0], pair[1]))
    text = "\n".join(line for _, line in rows)
    return Roster(
        text=text,
        sha=sha_anchor(text),
        routable=routable_count,
        visible_only=visible_only_count,
    )


def _render_candidates(candidates: list) -> str:
    if not candidates:
        return "(no cluster candidates above the 0.20 floor)"
    return "\n".join(
        f"- {c.record_id} [{c.status}] ({c.score:.2f}): {_truncate(c.title, 120)}"
        for c in candidates
    )


def cluster_candidates(home: Path, batch: list) -> dict:
    """Ingredient 2 — T-N cluster candidates (§3.3): IDF-cosine over
    trigger-title tokens, pinned algorithm (r2's suggested extension of
    ``_recurrence_suspects`` was measured and rejected — Jaccard ≥
    :data:`SUSPECT_JACCARD` is always-empty on the live corpus; a raw
    shared-token count is a queue dump; see the spec's §3.3 table).

    Pool = every pending record in every bucket (including deferred —
    T-N is a ranking, not a queue-eligibility computation) plus every
    resolved record with ``status == "routed"``. Returns
    ``{record_id: [Candidate, ...]}`` for every record in ``batch``,
    ranked desc by score, ties broken by record id ascending (A7),
    floored at :data:`CANDIDATE_SCORE_FLOOR` and capped at
    :data:`CANDIDATE_CAP` (A6). Deliberately does NOT touch
    ``_recurrence_suspects`` (§3.3, builder decision 6): a second,
    read-only consumer of the shared :func:`_tokens`, never a shared
    threshold — the two calibrations are unrelated."""
    home = Path(home)
    pool: list[tuple[str, str, str, set]] = []  # (id, status, title, tokens)
    for bucket in discover_buckets(home):
        for entry in queue(bucket, include_deferred=True):
            title = record_title(entry.record)
            pool.append((entry.record.id, "pending", title, _tokens(title)))
        resolved_dir = bucket.path / "resolved"
        if not resolved_dir.is_dir():
            continue
        for path in sorted(resolved_dir.glob("lrn-*.md")):
            try:
                routed = Record.from_path(path)
            except RecordError:
                continue
            if routed.status != "routed":
                continue
            title = record_title(routed)
            pool.append((routed.id, "routed", title, _tokens(title)))

    n = len(pool)
    doc_freq: dict[str, int] = {}
    for _id, _status, _title, toks in pool:
        for t in toks:
            doc_freq[t] = doc_freq.get(t, 0) + 1

    def idf(term: str) -> float:
        d = doc_freq.get(term, 0)
        if d <= 0 or n <= 0:
            return 0.0
        return math.log(n / d)

    def sum_idf(toks: set) -> float:
        return sum(idf(t) for t in toks)

    result: dict[str, list] = {}
    for entry in batch:
        rid = entry.record.id
        a_title = record_title(entry.record)
        a_toks = _tokens(a_title)
        a_sum = sum_idf(a_toks)
        scored: list[tuple[float, str, str, str]] = []
        for other_id, other_status, other_title, b_toks in pool:
            if other_id == rid:
                continue
            shared = a_toks & b_toks
            if not shared:
                continue
            b_sum = sum_idf(b_toks)
            denom = math.sqrt(a_sum * b_sum) if a_sum > 0 and b_sum > 0 else 0.0
            if denom <= 0:
                continue
            score = sum(idf(t) for t in shared) / denom
            if score >= CANDIDATE_SCORE_FLOOR:
                scored.append((score, other_id, other_status, other_title))
        scored.sort(key=lambda row: (-row[0], row[1]))
        top = scored[:CANDIDATE_CAP]
        result[rid] = [
            Candidate(record_id=oid, status=ostatus, score=sc, title=otitle)
            for sc, oid, ostatus, otitle in top
        ]
    return result


def path_roster(home: Path, entry) -> str:
    """Ingredient 3 — the absolute-path roster (§3.4): pure path
    arithmetic, never :func:`verbs._resolve_target` (that resolver runs
    registry gates and dirty checks and would make prompt assembly fail
    on a dirty host repo — A10). Every unresolvable slot renders an
    explicit sentinel naming the reason; no slot is ever omitted.

    Project scope's sentinel (gate FOLD 5) names ONE of two genuinely
    different reasons, keyed off ``entry.bucket_dir`` itself: a real
    per-project bucket whose ``meta.yaml`` is actually missing renders
    "(… project bucket has no meta.yaml)"; `analyst.analyze`'s own
    ``_unresolved-scope`` degrade path (no ``project_path`` reached
    :func:`bucket_dir_for_scope` at all — there was no bucket to check)
    renders "(… record not yet persisted; project path not supplied)"
    instead — never the first message for the second cause."""
    home = Path(home)
    record = entry.record
    scope = record.scope
    bucket_dir = entry.bucket_dir

    try:
        hosts = load_hosts(home)
    except HostsError:
        hosts = Hosts()
    skills_root = hosts.skills_root

    host_repo: Path | None = None
    host_repo_sentinel = "(no host repo at this scope)"
    # Gate FOLD 5: two DIFFERENT failure modes used to share one message.
    # A bucket whose meta.yaml is genuinely missing (a real per-project
    # bucket dir exists, e.g. mid-repair or first-ever write racing this
    # read) and a bucket that was never resolved AT ALL (the analyst's
    # one-shot path degraded to `analyst.py`'s `_unresolved-scope`
    # sentinel because no `project_path` reached `bucket_dir_for_scope`)
    # are not the same fact, and only the first one is actually "the
    # bucket has no meta.yaml" — the second has no bucket to check.
    project_unresolved_reason = "project bucket has no meta.yaml"
    if scope == "project":
        if bucket_dir.name == "_unresolved-scope":
            project_unresolved_reason = (
                "record not yet persisted; project path not supplied"
            )
        else:
            host_repo = bucket_project_path(bucket_dir)
        if host_repo is None:
            host_repo_sentinel = f"({project_unresolved_reason})"
    elif scope == "user":
        host_repo_sentinel = "(user scope has no host repo)"
    else:  # skill:<name>
        host_repo_sentinel = "(skill scope has no host repo — see skills root)"

    lines = [
        f"ledger home        : {home}",
        f"bucket             : {bucket_dir}",
        f"record file        : {entry.path}",
        f"proposals dir      : {bucket_dir / 'proposals'}",
        (
            f"skills root        : {skills_root}"
            if skills_root is not None
            else "skills root        : (none registered)"
        ),
        (
            f"host repo          : {host_repo}"
            if host_repo is not None
            else f"host repo          : {host_repo_sentinel}"
        ),
    ]

    # ALWAYS target (D1's table: skill-root CLAUDE.md | host CLAUDE.md |
    # ~/.claude/CLAUDE.md — the SAME literal :func:`canon_excerpt` already
    # uses for the user-scope leg, not re-derived from verbs.py).
    if scope.startswith("skill:"):
        if skills_root is not None:
            lines.append(f"ALWAYS target      : {skills_root / 'CLAUDE.md'}")
        else:
            lines.append(
                "ALWAYS target      : (unresolvable — no registered skills root)"
            )
    elif scope == "project":
        if host_repo is not None:
            lines.append(f"ALWAYS target      : {host_repo / 'CLAUDE.md'}")
        else:
            lines.append(
                f"ALWAYS target      : (unresolvable — {project_unresolved_reason})"
            )
    else:
        lines.append(
            f"ALWAYS target      : {Path('~/.claude/CLAUDE.md').expanduser()}"
        )

    # PATHED rules dir — skill scope has NO routable surface (P-A13,
    # R-SCOPE); the sentinel names that explicitly, matching D1's table.
    if scope.startswith("skill:"):
        lines.append("PATHED rules dir   : (unavailable at skill scope — P-A13)")
    elif scope == "project":
        if host_repo is not None:
            lines.append(f"PATHED rules dir   : {host_repo / '.claude' / 'rules'}")
        else:
            lines.append(
                f"PATHED rules dir   : (unresolvable — {project_unresolved_reason})"
            )
    else:
        user_claude_md = Path("~/.claude/CLAUDE.md").expanduser()
        lines.append(f"PATHED rules dir   : {user_claude_md.parent / 'rules'}")

    # DEMAND target — user scope has NO routable surface (S-23), the
    # standing rule, not a transitional one.
    if scope.startswith("skill:"):
        name = scope.partition(":")[2]
        if skills_root is None:
            lines.append(
                "DEMAND target      : (unresolvable — no registered skills root)"
            )
        else:
            try:
                skill_dir = skill_dir_for(hosts, name)
            except HostsError:
                lines.append(
                    f"DEMAND target      : (unresolvable — no skill named {name!r} "
                    "under skills root)"
                )
            else:
                lines.append(
                    f"DEMAND target      : {skill_dir / 'references' / 'LEARNINGS.md'}"
                )
    elif scope == "project":
        if host_repo is not None:
            lines.append(
                f"DEMAND target      : {host_repo / 'references' / 'LEARNINGS.md'}"
            )
        else:
            lines.append(
                f"DEMAND target      : (unresolvable — {project_unresolved_reason})"
            )
    else:
        lines.append("DEMAND target      : (unavailable at user scope — S-23)")

    return "\n".join(lines)


def compose_record_block(home: Path, entry, *, roster: Roster, candidates: list) -> str:
    """The ONE per-record block, shared verbatim by both prompt forms
    (§3.1/A11): record text (``Record.to_text()``, never
    ``entry.path.read_text()`` — §3.5, the two differ whenever ruamel
    re-renders frontmatter, and containment checks the FORMER), the T-N
    candidate block, the absolute-path roster, and the existing
    candidate-target canon excerpt."""
    home = Path(home)
    return (
        f"--- record {entry.record.id} ---\n"
        f"bucket: {entry.bucket_dir}\n"
        f"record file: {entry.path}\n"
        f"{entry.record.to_text()}\n"
        f"--- cluster candidates (T-N) ---\n"
        f"{_render_candidates(candidates)}\n"
        f"--- path roster ---\n"
        f"{path_roster(home, entry)}\n"
        f"--- candidate target canon excerpt ---\n"
        f"{_canon_excerpt(home, entry)}\n"
    )


def cache_dir() -> Path:
    """Per-ledger-home cache namespace (doc 13 §6, H-4):
    ``${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(home)[:8]>/`` —
    a future second home (06's team ledger) is a config away. Resolves
    the home itself via :func:`ledger.resolve_home` (cheap env read).

    Migration shim from the OLD un-namespaced path
    (``…/claude-skills/self-learn`` — the name embeds the host the cache
    no longer belongs to): see :func:`_migrate_cache`."""
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    digest = hashlib.sha256(str(resolve_home()).encode("utf-8")).hexdigest()[:8]
    new = base / "self-learn" / f"home-{digest}"
    new.mkdir(parents=True, exist_ok=True)
    _migrate_cache(base / "claude-skills" / "self-learn", new)
    return new


#: Written only after a COMPLETE migration — its absence means "retry".
MIGRATION_MARKER = ".migrated-from-claude-skills"

#: Live processes hold these (flock / pid window); moving them out from
#: under a running worker or miner is how you get two of them. They are
#: regenerable per-machine state, so they are left behind deliberately.
_MIGRATION_SKIP = ("worker.lock", "worker.spawn.lock", "worker.window")


def _migrate_cache(old: Path, new: Path) -> None:
    """Move the pre-doc-13 cache state into the home-namespaced dir
    (doc 13 §6). Idempotent and RETRIED until it completes: the marker is
    written only after a full clean pass, so a partial move (disk full,
    permissions, a file vanishing mid-move) is re-attempted on the next
    call instead of leaving the rest orphaned in the old path forever
    (audit 2026-07-16 MINOR 9: the shim ran once, only when the new dir
    did not exist, and swallowed every failure with `except: pass`).

    Lock/window files are deliberately NOT moved (:data:`_MIGRATION_SKIP`)
    — a LIVE worker or miner may hold them, and moving a flock'd file out
    from under it lets a second run start; they are regenerable. Every
    move and every failure is logged; nothing here is ever fatal (cache
    state is never load-bearing truth).

    Logging goes through :func:`_log_to` rather than :func:`log`: this
    runs INSIDE :func:`cache_dir`, and ``log`` resolves the cache dir —
    which would recurse until the marker exists.
    """
    if (new / MIGRATION_MARKER).exists() or not old.is_dir():
        return
    moved: list[str] = []
    failed: list[str] = []
    left: list[str] = []
    for entry in sorted(old.iterdir()):
        if entry.name in _MIGRATION_SKIP:
            left.append(entry.name)
            continue
        target = new / entry.name
        if target.exists():
            left.append(entry.name)  # newer state already here — never clobber
            continue
        try:
            shutil.move(str(entry), str(target))
            moved.append(entry.name)
        except (OSError, shutil.Error) as exc:
            failed.append(f"{entry.name} ({exc})")
    if moved or failed:
        _log_to(
            new / "worker.log",
            f"cache migration {old} → {new}: moved {moved or 'nothing'}; "
            f"left {left or 'nothing'}; FAILED {failed or 'nothing'}",
        )
    if failed:
        _log_to(
            new / "worker.log",
            "cache migration incomplete — will retry on the next run",
        )
        return
    try:
        (new / MIGRATION_MARKER).write_text(
            f"{_now_iso()} migrated from {old}\n", encoding="utf-8"
        )
    except OSError as exc:
        _log_to(
            new / "worker.log",
            f"cache migration: marker write failed ({exc}) — will retry",
        )


def _p(name: str) -> Path:
    return cache_dir() / name


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_to(path: Path, message: str) -> None:
    """Append one timestamped line to an EXPLICIT log path (capped ~1 MB).
    The migration shim needs this: it runs inside :func:`cache_dir`, so it
    cannot use :func:`log`, which resolves the cache dir to find its."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_now_iso()} {message}\n")
    except OSError:
        return  # a log we cannot write is never worth failing a run over
    _truncate_oldest(path, LOG_CAP_BYTES)


def log(message: str) -> None:
    """Append one timestamped line to worker.log (capped ~1 MB)."""
    _log_to(_p("worker.log"), message)


def _truncate_oldest(path: Path, cap: int) -> None:
    try:
        if path.stat().st_size <= cap:
            return
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        keep: list[str] = []
        size = 0
        for line in reversed(lines):
            size += len(line.encode("utf-8"))
            if size > cap:
                break
            keep.append(line)
        path.write_text("".join(reversed(keep)), encoding="utf-8")
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def coalesce_secs() -> float:
    raw = os.environ.get("SELF_LEARN_COALESCE_SECS")
    if not raw:
        return float(DEFAULT_COALESCE_SECS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_COALESCE_SECS)


def worker_model() -> str:
    return os.environ.get("SELF_LEARN_WORKER_MODEL") or DEFAULT_WORKER_MODEL


def batch_cap() -> int:
    return BATCH_CAP


def _timeout_secs(env_var: str, default: float) -> float:
    """Shared reader for the two env-overridable invocation timeouts
    (§3.9). Differs from :func:`coalesce_secs` in ONE way, deliberately:
    a value <= 0 or unparseable falls back to the default rather than
    being clamped to 0 — a zero coalesce is meaningful, but a zero
    ``subprocess.run(timeout=...)`` expires instantly and would kill
    every run (E4)."""
    raw = os.environ.get(env_var)
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return value if value > 0 else float(default)


def invoke_timeout_secs() -> float:
    """The batch invocation's timeout (§3.9), default
    :data:`INVOKE_TIMEOUT_SECS`, env-overridable via
    ``SELF_LEARN_INVOKE_TIMEOUT_SECS``."""
    return _timeout_secs("SELF_LEARN_INVOKE_TIMEOUT_SECS", INVOKE_TIMEOUT_SECS)


def repair_timeout_secs() -> float:
    """The repair round's timeout (§3.9), default
    :data:`REPAIR_TIMEOUT_SECS`, env-overridable via
    ``SELF_LEARN_REPAIR_TIMEOUT_SECS``."""
    return _timeout_secs("SELF_LEARN_REPAIR_TIMEOUT_SECS", REPAIR_TIMEOUT_SECS)


#: Read-only tool grant — Write is deliberately ABSENT here: path-scoped
#: Write rules ride the settings file (write_permission_rules); the live
#: CLI's --allowedTools cannot express path scopes (verified at T13 per
#: the pin's own instruction: the flag syntax was adjusted, the PROPERTY
#: is unchanged — no Bash, no Edit, Write only under proposals/).
ALLOWED_TOOLS = "Read,Grep,Glob"
DISALLOWED_TOOLS = "Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch"


def write_permission_rules(home: Path) -> list[str]:
    """The pinned Write scopes on the doc-13 ledger layout, in
    settings-file rule syntax — verified against the LIVE CLI (T13-start
    check, 2026-07-15): file-write scoping rides the ``Edit(...)`` rule
    FAMILY (it governs Write too); ``Write(path)`` rules match nothing.
    `//` = filesystem-absolute, gitignore ** semantics. The Edit TOOL
    itself stays in DISALLOWED_TOOLS. The scopes point at LEDGER
    proposals dirs ONLY — never at any host repo (H-3: no autonomous
    process writes canon)."""
    home = Path(home)
    return [
        f"Edit(/{home}/skills/**/proposals/**)",
        f"Edit(/{home}/projects/**/proposals/**)",
        f"Edit(/{home}/user/proposals/**)",
    ]


def write_settings_file(home: Path) -> Path:
    """Per-run settings file carrying the Write scope (E-18: this file +
    DISALLOWED_TOOLS IS the append-only guarantee)."""
    path = _p("worker.settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": write_permission_rules(home),
                    "defaultMode": "default",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def write_repair_settings_file(home: Path, paths: list[Path]) -> Path:
    """§3.7 — the repair round's NARROWED settings file: one EXACT-PATH
    ``Edit(...)`` rule per member of the repair set ``E``, sorted — never
    a glob. This is the structural half of "the repair round must not
    enlarge the blast radius" (§2, FW-84): the CLI itself refuses writes
    outside the assigned set — true because this file pins
    ``defaultMode: "default"`` below; without that key the scopes were
    decorative (see the next paragraph).

    Verified against the live CLI (2.1.226) as a builder obligation
    (§3.7), not assumed: a scratch home, the worker's real argv shape
    (``--allowedTools Read,Grep,Glob --disallowedTools
    ...,Edit,...``, Edit granted ONLY via this settings file), one
    exact-path rule for a target file — a sibling file in the SAME
    directory, granted no rule of its own, was refused; the granted
    target was editable. (This host's OWN interactive
    ``~/.claude/settings.json`` sets ``permissions.defaultMode:
    bypassPermissions``, which — same as it did for the batch-invocation
    globs until ``defaultMode`` was pinned there too — voids any
    settings-file scope that omits the key; the probe
    above set ``defaultMode: "default"`` in the probe's OWN ``--settings``
    file to exercise real enforcement, since a CLI-supplied settings file
    takes precedence over the user's global one. See the build report.)"""
    home = Path(home)
    path = _p("worker.repair.settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    rules = [f"Edit(/{p})" for p in sorted(paths)]
    path.write_text(
        json.dumps(
            {"permissions": {"allow": rules, "defaultMode": "default"}},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def build_argv(home: Path, settings_path: Path) -> list[str]:
    """The prompt is deliberately NOT in argv (audit 2026-07-15, shared
    with the miner's B1): Linux caps one argv element at 128 KiB, and a
    full batch — 15 records × (record + canon excerpt) + doctrine +
    registry — plausibly exceeds it. The prompt rides stdin instead.

    ``--strict-mcp-config`` (U-repair §3.11): the analyst needs no MCP
    server, and without the flag it inherits the user's, paying startup
    cost and side effects for tools ``--allowedTools`` will not let it
    call anyway. Verified against the live CLI (2.1.226, §9-X1): accepted
    with no ``--mcp-config`` present, rc 0, no diagnostic. ``--bare`` was
    considered and refused (§3.11, §7.1) — its own help text states OAuth
    and keychain are never read under it, and the unattended worker has
    no ``ANTHROPIC_API_KEY``. Both invocations share this ONE builder
    (F2) — they differ only at ``--settings``."""
    return [
        "claude",
        "-p",
        "--model",
        worker_model(),
        "--allowedTools",
        ALLOWED_TOOLS,
        "--disallowedTools",
        DISALLOWED_TOOLS,
        "--settings",
        str(settings_path),
        "--strict-mcp-config",
    ]


# ------------------------------------------------------------------- kick


#: Env var carrying an invoking verb's ``--no-push`` to the worker it
#: spawns (audit 2026-07-16 BLOCKER 3).
NO_PUSH_ENV = "SELF_LEARN_NO_PUSH"


def no_push_requested() -> bool:
    """True iff this process was told not to push.

    THE PROCESS-BOUNDARY READER, and nothing else. A spawn is detached, so
    a parent's flag can only reach a child as inherited environment; the
    child reads it ONCE here, at its dispatch surface, and from there it
    travels as an ordinary parameter (audit 2026-07-16 BLOCKER D: when
    no-push lived only in the ambient environment, `reject --no-push`
    spawned a miner that never had the var set and published the whole
    branch — an ambient policy that simply was not there).

    SEMANTICS, deliberately narrow: ``--no-push`` means *this invocation
    and anything it spawns* does not push. It is "not now", NOT "never" — a
    later independent worker, miner, or timer run may still publish the
    commit; ``--no-push`` keeps a record local for the moment, and nothing
    in the ledger promises permanence. To keep something out of the remote
    for good, it must not be committed to a pushed branch at all."""
    return os.environ.get(NO_PUSH_ENV) == "1"


def _autokick_disabled() -> bool:
    """True iff ``SELF_LEARN_WORKER_AUTOKICK=0`` — the shared kill-switch
    for ANY code path that would auto-spawn a detached ``worker run
    --coalesce`` window, not just an explicit :func:`kick`. Read fresh
    (never cached) so a test's `monkeypatch.setenv`/`delenv` takes effect
    immediately.

    Incident 2026-08-09: before this helper existed, only :func:`kick`
    checked the env var — the run-end follow-on (see :func:`run`) called
    `_open_window` directly and was NOT gated by it at all. A suite test
    exercising `worker.run()` with a leftover/backlog batch (AUTOKICK=0
    ambient from the conftest default, `_spawn_window` never mocked)
    spawned a REAL detached `worker run --coalesce` chain that respawned
    generation after generation, each run's own follow-on re-triggering
    the next — invisible to the AUTOKICK=0 the test believed had disabled
    all auto-spawning. That orphaned chain (peak 4,617 notify-send +
    6,508 wrapper shells, each a G-3 notifier riding the same leak) ran
    39.3 hours and exhausted the user-scope dbus-broker's file
    descriptors, killing the desktop session."""
    return os.environ.get("SELF_LEARN_WORKER_AUTOKICK") == "0"


def _followon_progress(home: Path, eligible_before: int) -> bool:
    """D2 (incident 2026-08-09) — True iff a FRESH re-enumeration shows
    the eligible set genuinely shrank since `eligible_before` was
    captured at THIS run's own start. `status in ("ok", "idle")` alone is
    NOT proof of progress: it only means a proposal file was written,
    never that the record it names actually left the pending queue — a
    batch that keeps re-reporting "ok" while the same records stay
    un-landed (a pathological fixture, or a future bug) chains forever,
    invisible to the failure cap (which only counts `status == "failed"`
    runs).

    Called ONLY from the run-end follow-on decision, itself outside the
    run lock (see the comment there) — every commit this run made is
    already applied by the time this re-scans, so the comparison is
    against the ledger's true post-run state, not a stale snapshot.

    CARDINALITY, NOT IDENTITY (code gate 2026-08-09, MAJOR 3, ratified
    keep-as-built): this compares COUNTS (`eligible_after < eligible_
    before`), never WHICH records those counts name. Supply that arrives
    and leaves within the same run without changing the net count — a
    record set going {A,B} -> {B,C} (A resolved, C newly landed mid-run),
    or a mid-run kick landing during what started as an idle run with a
    still-empty eligible set at both ends — reads as "no progress" and
    the follow-on will NOT spawn. This is deliberate, not an oversight:
    identity tracking would need to diff record ID SETS, not just their
    sizes, adding real complexity to a safety-critical decision for a
    case that only costs LATENCY, never correctness — the arrived work
    is never lost, only left for the next independent kick (an explicit
    kick is unaffected either way: it is never gated by this function at
    all, and always covers it). Conservative is the right default in the
    aftermath of a 39.3h incident caused by the opposite failure mode
    (spawning too eagerly); revisit only on deliberate, ratified
    request — see the routing note accompanying this comment."""
    fresh_batch, fresh_leftovers, _total_pending, _per_bucket = _enumerate(home)
    eligible_after = len(fresh_batch) + fresh_leftovers
    return eligible_after < eligible_before


#: D3 (incident 2026-08-09) — the follow-on chain's absolute depth
#: ceiling: belt-and-braces that holds even if D2's progress reasoning
#: above is ever wrong. 8 generations at BATCH_CAP=15/generation drains
#: up to 120 backlogged records — comfortably above any plausible
#: real backlog (measured live: 21 pending / 19 eligible drains in ~2
#: generations) — while bounding worst case to a handful of processes,
#: never an unbounded chain.
FOLLOWON_DEPTH_CEILING = 8

#: Threaded through a spawned child's env (2026-08-09): each real
#: `_spawn_window` call increments this from the PARENT's own value (0 if
#: absent — an explicit `kick()` from a human/teach/import/miner shell
#: never carries one, so it always starts a fresh chain at depth 1,
#: exactly right: E7's "an explicit kick is a fresh mandate" applies here
#: too). Only a CHAIN of automatic follow-on spawns, each inheriting the
#: previous one's incremented env, ever approaches the ceiling.
FOLLOWON_DEPTH_ENV = "SELF_LEARN_FOLLOWON_DEPTH"


def _spawn_window(home: Path, *, no_push: bool = False) -> int:
    """setsid-spawn a coalescing run; returns the child pid, or the
    negative sentinel ``-1`` iff D3's chain-depth ceiling refuses to
    spawn (see :data:`FOLLOWON_DEPTH_CEILING`). Split out so tests can
    monkeypatch spawning without faking flocks.

    ``no_push`` rides the child's ENV (BLOCKER 3): the spawn is detached
    (``start_new_session=True``), so the parent's flag reaches it only as
    inherited environment — and without it, ``teach --no-push`` published
    the very record the user said keep local, via the worker teach itself
    kicked (worker run-end ``git push`` publishes the WHOLE branch).

    D3 (incident 2026-08-09): the child's own follow-on chain depth rides
    the SAME env-copy mechanism — read from THIS process's own
    environment (0 if absent) and written back incremented, so a CHAIN
    of automatic follow-on spawns accumulates a visible depth the
    ceiling can act on, while an explicit `kick()` (never carrying the
    var in a fresh human/teach/import/miner shell) always starts a new
    chain at depth 1."""
    try:
        depth = int(os.environ.get(FOLLOWON_DEPTH_ENV, "0"))
    except ValueError:
        depth = 0
    if depth >= FOLLOWON_DEPTH_CEILING:
        log(
            f"run: follow-on chain-depth ceiling reached ({depth} >= "
            f"{FOLLOWON_DEPTH_CEILING}) — refusing to spawn a successor; "
            "`self-learn worker kick` retries"
        )
        return -1
    log_path = _p("worker.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if no_push:
        env[NO_PUSH_ENV] = "1"
    env[FOLLOWON_DEPTH_ENV] = str(depth + 1)
    with open(log_path, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "self_learn.cli", "worker", "run", "--coalesce"],
            cwd=str(home),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    return proc.pid


def _open_window(home: Path, *, no_push: bool = False) -> str:
    """Lock-guarded window opener, shared by :func:`kick` and the
    run-end follow-on (audit 2026-07-15: the follow-on previously
    bypassed the spawn lock and could double-spawn against a mid-run
    kick). Returns ``spawned`` | ``absorbed-window`` | ``absorbed-race``
    | ``depth-limited`` (D3, 2026-08-09: `_spawn_window` refused under
    the chain-depth ceiling — nothing was actually spawned, so no pid is
    recorded to `worker.window`).

    ``no_push`` propagates to a spawned child (BLOCKER 3). An ABSORBED kick
    inherits the already-running window's policy — correct: absorption
    means an existing run already covers this work, and a run that was
    allowed to push is not retroactively muzzled."""
    with open(_p("worker.spawn.lock"), "w", encoding="utf-8") as lock_fh:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "absorbed-race"  # the racing opener's spawn covers us
        try:
            window = _p("worker.window")
            if window.is_file():
                try:
                    pid = int(window.read_text(encoding="utf-8").strip())
                except ValueError:
                    pid = -1
                if pid > 0 and _pid_alive(pid):
                    return "absorbed-window"
            pid = _spawn_window(home, no_push=no_push)
            if pid <= 0:
                return "depth-limited"  # already logged by _spawn_window
            window.write_text(str(pid), encoding="utf-8")
            log(f"window opened (pid {pid})")
            return "spawned"
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def kick(home: Path | str, *, no_push: bool = False) -> str:
    """The pinned kick. Returns the outcome (for logs/tests):
    ``spawned`` | ``absorbed-window`` | ``absorbed-race`` | ``disabled``
    | ``depth-limited`` (D3 — vanishingly unlikely for an explicit kick,
    since a fresh human/teach/import/miner shell never carries a
    follow-on depth; see :func:`_spawn_window`).

    ``no_push`` binds the spawned worker to the caller's ``--no-push``
    (BLOCKER 3) — see :func:`no_push_requested` for the exact semantics."""
    if _autokick_disabled():
        return "disabled"
    home = Path(home)
    cache_dir().mkdir(parents=True, exist_ok=True)
    _p("worker.dirty").touch()
    # E7 (§3.10): an explicit kick — human, UI, teach/import, the miner —
    # is a fresh mandate; it must never be refused by a stale backoff
    # counter, and BEFORE _open_window so a suppressed follow-on's own
    # counter state can never leak into this decision.
    _reset_failure_count()
    return _open_window(home, no_push=no_push)


# -------------------------------------------------------------------- run


@dataclass
class RunResult:
    status: str  # "ok" | "idle" | "failed"
    proposed: list[str] = field(default_factory=list)
    merge_proposed: list[str] = field(default_factory=list)
    invalid_deleted: list[str] = field(default_factory=list)
    orphans_swept: list[str] = field(default_factory=list)
    buckets: list[str] = field(default_factory=list)  # received proposals
    valid_landed: int = 0  # step-6 success basis, BEFORE step-5 filtering
    eligible: int = 0
    leftovers: int = 0  # eligible beyond the batch cap (follow-on covers)
    suspects: int = 0
    escalated: bool = False
    followon: bool = False
    #: Every ledger path this run wrote or deleted — the surgical staging
    #: set for the run-end commit (H-5: producers commit their own writes).
    touched: list[Path] = field(default_factory=list)
    commit_sha: str | None = None
    #: True iff this run's commit landed — the push's gate. Distinct from
    #: ``commit_sha is not None`` only in intent: it answers "is there
    #: anything to publish?", which is the question the caller asks OUTSIDE
    #: the lock (round 7: the commit moved inside `_harvest`'s lock, the
    #: push must not follow it in).
    committed: bool = False
    #: U-repair Obs-1 (§3.12) — additive only, no existing field changes
    #: type or meaning beyond `invalid_deleted`'s widening (below).
    repair_attempted: bool = False
    repair_eligible: int = 0
    repair_cleared: int = 0
    #: Rule-F's leave-entirely-alone set (§3.8) — proposal NAMES, never
    #: in `proposed`/`valid_landed`/`touched`, but counted toward
    #: `status` (D7).
    foreign_left: list[str] = field(default_factory=list)


def _enumerate(home: Path) -> tuple[list, int, int, list[dict]]:
    """(batch, leftovers, total pending, per-bucket counts). Same queue
    computation as `list` — deferred hidden; oldest first with the SAME
    sort key as `list` (audit 2026-07-15: str-sort diverged on mixed
    timestamp representations); batch cap 15 — leftovers keep
    ``worker.dirty`` set for a follow-on window (pinned)."""
    from .ledger_ops import _sort_key  # THE shared ordering

    needing = []
    total_pending = 0
    per_bucket: list[dict] = []
    for bucket in discover_buckets(home):
        entries = queue(bucket)
        if entries:
            per_bucket.append({"bucket": bucket.name, "pending": len(entries)})
        total_pending += len(entries)
        for entry in entries:
            if is_unanalyzed(entry):
                needing.append(entry)
    needing.sort(key=_sort_key)
    batch = needing[: batch_cap()]
    return batch, len(needing) - len(batch), total_pending, per_bucket


def _digest(home: Path, limit: int = 20) -> str:
    """Rejected-proposal digest — CLI-built negative exemplars (pinned):
    last `limit` rejected records ordered by resolving-commit AUTHOR
    DATE, newest first (audit 2026-07-15: topo order diverges from
    author-date order under rebase-based autosync, so the rows are
    sorted explicitly; the grep is line-anchored so a Revert subject
    quoting the message does not re-list an undone rejection)."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(home),
            "log",
            "--grep",
            "^self-learn: reject ",
            "--format=%ad%x09%s",
            "--date=iso-strict",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return "(no rejected-proposal history available)"
    rows = sorted(
        (row.split("\t", 1) for row in proc.stdout.splitlines() if "\t" in row),
        key=lambda pair: pair[0],
        reverse=True,  # author date, newest first (pinned)
    )
    lines: list[str] = []
    seen: set[str] = set()
    for _ad, subject in rows:
        parts = subject.split()
        rid = next((p for p in parts if p.startswith("lrn-")), None)
        if rid is None or rid in seen:
            continue
        seen.add(rid)
        title, note = None, None
        for bucket in discover_buckets(home):
            path = bucket.path / "resolved" / f"{rid}.md"
            if path.is_file():
                try:
                    record = Record.from_path(path)
                    title = record_title(record)
                    note = record.resolution_note
                except RecordError:
                    pass
                break
        if title is None:
            continue  # not a resolvable reject here — never inject noise
        entry = f"- {rid}: {title}"
        if note:
            entry += f" — rejected because: {note}"
        entry += f" [{subject}]"
        lines.append(entry)
        if len(lines) >= limit:
            break
    if not lines:
        return "(no rejected proposals yet)"
    return "\n".join(lines)


def canon_excerpt(home: Path, record: Record, bucket_dir: Path) -> str:
    """The candidate target's managed section ± 20 lines, or the whole
    file when < 200 lines (pinned prompt ingredient). Targets resolve
    through the hosts registry now (doc 13): skill scope → the skills
    root's SKILL.md; project scope → the bucket's meta-recorded host
    CLAUDE.md; user scope → the real user CLAUDE.md.

    The ONE implementation of this rule (FW-48/U-marker-ui, 2026-08-02):
    the review pane (``ui/src/self_learn_ui/pane.py``'s
    ``target_canon_excerpt``) imports and delegates to this function
    rather than re-declaring it. A hand-copied second implementation is
    exactly how the pane drifted onto a marker literal the compiler
    never wrote — see
    ``docs/specs/self-learn/drafts/u-marker-excerpt-case-spec.md`` §5."""
    scope = record.scope
    target: Path | None = None
    if scope.startswith("skill:"):
        try:
            target = skill_dir_for(
                load_hosts(home), scope.partition(":")[2]
            ) / "SKILL.md"
        except HostsError:
            return "(skill target unresolvable — no registered skills root)"
    elif scope == "project":
        host = bucket_project_path(bucket_dir)
        if host is None:
            return "(project target unresolvable — bucket has no meta.yaml)"
        target = Path(host) / "CLAUDE.md"
    else:  # user
        target = Path("~/.claude/CLAUDE.md").expanduser()
    if not target.is_file():
        return f"(target {target.name} does not exist yet)"
    lines = target.read_text(encoding="utf-8").splitlines()
    if len(lines) < 200:
        return "\n".join(lines)
    begin = next(
        (i for i, ln in enumerate(lines) if BEGIN_MARKER in ln), None
    )
    end = next((i for i, ln in enumerate(lines) if END_MARKER in ln), None)
    if begin is None or end is None:
        return "\n".join(lines[:60]) + "\n… (truncated)"
    lo, hi = max(0, begin - 20), min(len(lines), end + 21)
    return "\n".join(lines[lo:hi])


def _canon_excerpt(home: Path, entry) -> str:
    """``compose_record_block``'s own call shape: a ``queue()``-yielded
    ``QueueEntry`` (``.record``/``.bucket_dir``), not a bare
    :class:`~self_learn.records.Record`. Thin wrapper around the shared
    :func:`canon_excerpt` — kept so this module's existing call site and
    test suite (``test_worker.py``) need no signature change."""
    return canon_excerpt(home, entry.record, entry.bucket_dir)


#: U-repair Set-C (§3.1) — the trace-writing contract, harvested from the
#: shipped validator and rendered imperatively for a producer. A1 pins
#: each Set-C member's token(s) on BOTH sides: this constant and the
#: validator's own refusal message — a validator rewording and a
#: checklist deletion each redden, in opposite directions. Interpolated
#: into `b1` (`_PROMPT_TEMPLATE`), `b2` (`_REPAIR_PROMPT_TEMPLATE`) and
#: `b3` (`_SINGLE_PROMPT_TEMPLATE`) — ONE definition, three producers
#: (§3.2). `C4` is the trap: it is the only place a null answer is legal,
#: and it is the one the shipped exemplar used to display.
TRACE_CONDITIONALS = """the decision-trace conditional checklist — restated from the validator's
own rules (Set-C), not a second validator. The validator's refusal
reports only the FIRST problem it finds in a file; check EVERY line
below against the WHOLE proposal before you finish writing it, not just
the one line a refusal named.

- gates.g0.reject.evidence and gates.g0.defer.evidence are each required
  only when that same leg's own answer is "yes" — a RECORD-sourced quote.
- gates.g0.canon.target must be non-empty text, and gates.g0.canon.evidence
  a TARGET-sourced quote, both required only when gates.g0.canon.answer is
  "yes".
- gates.t1.field_shaped.answer is "yes" or "no" — NEVER null — and its
  evidence is required on BOTH branches.
- gates.t1.cost_bearing.answer (and gates.t1.separable.answer, the same
  rule) may be "yes", "no", or null — THE ONLY gates where null is a legal
  answer; cost_bearing's evidence is required only when its own answer is
  "yes".
- gates.t2.match_path must be non-empty text, required only when
  gates.t2.answer is "yes"; on that branch rules_paths must be a non-empty
  list of non-empty globs and match_path must match at least one of them.
- gates.t3.scan_terms must be null when gates.t3.answer is "yes", and a
  non-empty list of non-empty strings when it is "no" — mirror-image
  required-ness, never both populated, never both empty.
- gates.t3a.depth_behind_rule.target must be non-empty text, required only
  when gates.t3a.depth_behind_rule.answer is "yes" (gates.t3a itself
  exists only when gates.t3.answer is "yes" — null otherwise).
- gates.t4.depth_behind_rule.target must be non-empty text, required only
  when gates.t4.depth_behind_rule.answer is "yes".
- gates.t4.conduct_mode.answer is "yes" or "no" — NEVER null — its
  evidence required only when "yes".
- gates.t4.fs.verdict (same rule at gates.t3a.fs.verdict) is one of
  SILENT, COSTLY, LOUD_CHEAP, INDETERMINATE — NEVER null; INDETERMINATE
  IS the "I did not determine this" value, so write it explicitly rather
  than null. evidence is required unless the verdict is INDETERMINATE.
- gates.tn.members must have >= 2 entries when gates.tn.answer is "yes"
  and <= 1 when "no"; gates.tn.proposed_name is required only when "yes",
  null otherwise.
- gates.e1.sightings must be an int >= 1 (a bool is never accepted here).
- gates.outcome must equal exactly what the gate procedure's own table
  derives from your own answers above it — never hand-picked, and never
  changed to make a conditional requirement go away.
- every RECORD-sourced evidence quote must be a verbatim span actually
  contained in the record — a paraphrase is refused, whether it reads
  close or not.
- gates, flags, and recommendation are each REQUIRED top-level keys on
  every proposal — write flags: [] explicitly when there are none; never
  omit any of the three.
"""

_PROMPT_TEMPLATE = """You are the self-learn routing analyst worker. For EACH pending record
below, write one proposal file at
<bucket>/proposals/lrn-<id>.yaml (the bucket path is given
per record). Follow the routing doctrine exactly — including §5 (the
proposal schema; NEVER emit record_sha), §8 (write every card section
the registry requires; the registry follows the doctrine below), §9
(the proposal-time lint) and §10 (the destination-bounded contradiction
check). You may also propose an optional `contradicts:` list (record ids
or canon anchors) when a lesson conflicts with an entry in the
destination section shown in the candidate-target excerpt below.

Every proposal MUST also carry the decision trace (§5, S-26 — mandatory,
not optional): write `gates:`, `flags:`, and `recommendation:` on EVERY
proposal, exactly as §5's schema and worked example show. `flags: []` is
written explicitly when there are none — never omitted. A proposal
missing any of the three is deleted unread; nothing is landed without it.

After the per-record pass: if two or more of THESE pending records in the
SAME bucket are the same lesson, additionally write ONE merge proposal at
<bucket>/proposals/merge-<8 lowercase hex>.yaml with keys:
cluster_id, records (the lrn ids), suggested_survivor, rationale, model,
analyzed_at. Do not emit record_shas — the CLI stamps them.
cluster_id MUST equal the merge-<8 hex> token of the filename itself
(file merge-a1b2c3d4.yaml → cluster_id: merge-a1b2c3d4) — never a
descriptive slug: the validator deletes ids that don't match the
merge-<8 hex> pattern, and a pattern-valid id that differs from the
filename token is dead on arrival at route --collapse.

=== SKILL ROSTER (T3) ===
roster sha: {roster_sha}
{roster_text}

Never re-propose the classes below (recently rejected):
{digest}

=== ROUTING DOCTRINE ===
{doctrine}

=== CARD SECTION REGISTRY ===
{registry}

=== DECISION-TRACE CONDITIONAL CHECKLIST ===
{trace_conditionals}

=== PENDING RECORDS ===
{records}
"""

#: The analyst's one-record form (§3.5) — the doctrine rides
#: ``--append-system-prompt`` there, so this prompt never interpolates it
#: a second time. Still states the gate-output contract (§3.5/A12 fourth
#: leg's own tokens) and the roster once, inline.
_SINGLE_PROMPT_TEMPLATE = """Choose the routing destination for the lesson record below, following the
routing doctrine in your system prompt (narrowest-surface bias). Reply
with ONLY a YAML mapping — no prose, no explanation outside it — and
follow §5's full output contract, INCLUDING the mandatory decision trace:
write `gates:`, `flags:`, and `recommendation:` on this proposal, exactly
as §5's worked example shows. `flags: []` when there are none.

destination: <one of skill-md | claude-md | reference | new-skill | hook>
alternates: [<zero or more others from the same list>]
rationale: <one sentence>
# claude-md only, optional (A2 §3): a rules topic file, or a personal
# per-project file — omit all three for plain claude-md.
variant: <rules | local, omit for plain claude-md>
rules_topic: <kebab-slug topic — required iff variant is rules>
rules_paths: [<glob>, ...]  # optional; omit for an unpathed rule
gates: <the full decision trace — §5>
flags: []
recommendation: <route | reject | defer | graduate>

=== SKILL ROSTER (T3) ===
roster sha: {roster_sha}
{roster_text}

{trace_conditionals}

{record_block}"""

#: U-repair §3.6 — the repair prompt. Carries ONLY: the form-repair
#: framing (Set-P/Set-Q, §3.5, stated in the model's own second person),
#: `TRACE_CONDITIONALS` (`b2` — the SAME constant object `A1` pins), the
#: explicit "only the FIRST problem" statement, and — per eligible file,
#: interpolated by :func:`_compose_repair_prompt` — its absolute path,
#: its current contents, its exact refusal line, and its record's
#: `to_text()`. It carries NONE of the routing doctrine, the skill
#: roster, the cluster candidates, the rejected-proposal digest, or the
#: card-section registry (B13) — those are re-judgment materials a form
#: repair must not see (BD2).
_REPAIR_PROMPT_TEMPLATE = """You are the self-learn routing analyst worker's REPAIR pass. This is a
FORM REPAIR, not a re-analysis: every file listed below already carries a
judgment from the first pass. Do not change that judgment: do not change
any gate answer, verdict, owner, proposed name, sightings count, or
already_canon value that was already legal before this repair — above
all, never flip an answer from "yes" to "no" (or the reverse) to make a
conditional requirement go away. That is not a form fix; it silently
rewrites a judgment you were not asked to re-make. You may only: add a
conditionally-required field that is absent; replace a null or
out-of-enum value with a legal member of its closed set; null a field the
schema forbids at its sibling's current answer; replace a paraphrased
RECORD quote with a verbatim span of the record shown below. Modify
only the files listed below — no other path.

The validator that refused each file below reports only the FIRST
problem it finds in it — check EVERY line of the checklist below against
the WHOLE file before you finish, not just the one line the refusal
named.

{trace_conditionals}

{files}
"""


def _doctrine_and_registry_text() -> tuple[str, str]:
    # PACKAGE-relative (doc 13 T-H3): doctrine + registry ship with the
    # product beside the skill — never resolved through any home.
    doctrine_path = package_skill_refs() / "routing-doctrine.md"
    registry_path = package_skill_refs() / "card-sections.yaml"
    doctrine = (
        doctrine_path.read_text(encoding="utf-8")
        if doctrine_path.is_file()
        else "(doctrine missing — propose conservatively)"
    )
    registry = (
        registry_path.read_text(encoding="utf-8")
        if registry_path.is_file()
        else "(registry missing — headline/impact/discuss)"
    )
    return doctrine, registry


def compose_batch_prompt(home: Path, batch: list) -> tuple[str, Roster]:
    """The M2 worker's prompt (replaces the old ``_compose_prompt``):
    everything it composed before — the rejected-proposal digest, the
    doctrine and the card registry, and per-record text/bucket/record
    path/canon excerpt — plus the roster once per prompt (its sha stated
    verbatim, §3.6) and, per record, the T-N candidate block and the
    absolute-path roster (§3.5). Returns the composed prompt AND the
    :class:`Roster` used, so the caller that later validates model output
    can compare ``gates.t3.roster_sha`` against the roster actually
    composed for THIS run."""
    home = Path(home)
    doctrine, registry = _doctrine_and_registry_text()
    roster = skill_roster(home)
    candidates_by_id = cluster_candidates(home, batch)
    blocks = [
        compose_record_block(
            home, entry, roster=roster, candidates=candidates_by_id.get(entry.record.id, [])
        )
        for entry in batch
    ]
    prompt = _PROMPT_TEMPLATE.format(
        digest=_digest(home),
        doctrine=doctrine,
        registry=registry,
        roster_sha=roster.sha,
        roster_text=roster.text,
        trace_conditionals=TRACE_CONDITIONALS,
        records="\n".join(blocks),
    )
    return prompt, roster


def compose_single_prompt(home: Path, entry) -> tuple[str, Roster]:
    """The analyst's one-record prompt form (§3.5): the same
    :func:`compose_record_block` block A11 requires byte-identical to the
    worker's, with the roster inline (the analyst never sees the digest,
    the doctrine, or the card registry here — those ride
    ``--append-system-prompt`` and the doctrine's own §8 pointer)."""
    home = Path(home)
    roster = skill_roster(home)
    candidates = cluster_candidates(home, [entry]).get(entry.record.id, [])
    block = compose_record_block(home, entry, roster=roster, candidates=candidates)
    prompt = _SINGLE_PROMPT_TEMPLATE.format(
        roster_sha=roster.sha,
        roster_text=roster.text,
        trace_conditionals=TRACE_CONDITIONALS,
        record_block=block,
    )
    return prompt, roster


def _compose_repair_prompt(home: Path, eligible: dict[Path, str]) -> str:
    """§3.6 — assembles the repair prompt from `_REPAIR_PROMPT_TEMPLATE`
    and, per member of ``eligible`` (path -> its S4 refusal message,
    byte-identical to what `S8` would log — B5), its absolute path,
    current contents, refusal line, and record `to_text()`. Deliberately
    does NOT call :func:`compose_record_block` or interpolate
    `_PROMPT_TEMPLATE` (B13) — reusing either would smuggle the routing
    materials a form repair must not see back in."""
    home = Path(home)
    blocks: list[str] = []
    for path in sorted(eligible):
        refusal = eligible[path]
        contents = path.read_text(encoding="utf-8")
        record_text = "(record unreadable)"
        rpath = path.parent.parent / "pending" / f"{path.stem}.md"
        if rpath.is_file():
            try:
                record_text = Record.from_path(rpath).to_text()
            except RecordError:
                pass
        blocks.append(
            f"--- file {path} ---\n"
            f"refusal: {refusal}\n"
            f"--- current contents ---\n"
            f"{contents}\n"
            f"--- record ---\n"
            f"{record_text}\n"
        )
    return _REPAIR_PROMPT_TEMPLATE.format(
        trace_conditionals=TRACE_CONDITIONALS,
        files="\n".join(blocks),
    )


def _proposal_snapshot(home: Path) -> dict[Path, str]:
    """Recursive over proposals/ (audit 2026-07-15: the Write glob is
    recursive, so a model writing proposals/sub/x.yml must be SEEN — an
    unseen file would be silently autosync-published)."""
    snap: dict[Path, str] = {}
    for bucket in discover_buckets(home):
        pdir = bucket.path / "proposals"
        if not pdir.is_dir():
            continue
        for path in pdir.rglob("*"):
            if not path.is_file():
                continue
            try:
                snap[path] = sha_anchor(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                snap[path] = "unreadable"
    return snap


def _written_since(home: Path, snap: dict[Path, str]) -> list[Path]:
    out = []
    for path, digest in _proposal_snapshot(home).items():
        if snap.get(path) != digest:
            out.append(path)
    return sorted(out)


# ---------------------------------------------- U-repair: Set-E (§3.4)


def _repairable(message: str) -> str:
    """Set-E's refusal-TEXT rules (§3.4), `E-1`..`E-3`. Stays text-only
    (NOTE E, delta-2 gate): the two PROVENANCE rules, `E-4` (batch
    membership) and `E-5` (unstamped), are PATH predicates evaluated at
    the `S5` call site alongside this function's result — there is
    deliberately no composed ``_eligible(path)`` helper."""
    if not message.startswith("gates."):
        return "INELIGIBLE"
    if "roster_sha" in message:
        return "INELIGIBLE"
    if "Table-1 derives" in message:
        return "INELIGIBLE"
    return "ELIGIBLE"


# ---------------------------------------------- U-repair: Set-J (§3.5)

#: Set-J (§3.5) — the pinned judgment fields, `id -> dotted json-path ->
#: key path tuple`. `J1` is every `answer` under `gates`; `J2` is the two
#: `fs.verdict` legs; `J3` is `t3.owner` / `tn.proposed_name` /
#: `e1.sightings` / `e1.post_demand_recurrence`; `J4` is `already_canon`.
_SETJ_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gates.g0.reject.answer", ("gates", "g0", "reject", "answer")),
    ("gates.g0.defer.answer", ("gates", "g0", "defer", "answer")),
    ("gates.g0.canon.answer", ("gates", "g0", "canon", "answer")),
    ("gates.t1.field_shaped.answer", ("gates", "t1", "field_shaped", "answer")),
    ("gates.t1.separable.answer", ("gates", "t1", "separable", "answer")),
    ("gates.t1.cost_bearing.answer", ("gates", "t1", "cost_bearing", "answer")),
    ("gates.t2.answer", ("gates", "t2", "answer")),
    ("gates.t3.answer", ("gates", "t3", "answer")),
    (
        "gates.t3a.depth_behind_rule.answer",
        ("gates", "t3a", "depth_behind_rule", "answer"),
    ),
    (
        "gates.t4.depth_behind_rule.answer",
        ("gates", "t4", "depth_behind_rule", "answer"),
    ),
    ("gates.t4.conduct_mode.answer", ("gates", "t4", "conduct_mode", "answer")),
    ("gates.tn.answer", ("gates", "tn", "answer")),
    ("gates.t3a.fs.verdict", ("gates", "t3a", "fs", "verdict")),
    ("gates.t4.fs.verdict", ("gates", "t4", "fs", "verdict")),
    ("gates.t3.owner", ("gates", "t3", "owner")),
    ("gates.tn.proposed_name", ("gates", "tn", "proposed_name")),
    ("gates.e1.sightings", ("gates", "e1", "sightings")),
    ("gates.e1.post_demand_recurrence", ("gates", "e1", "post_demand_recurrence")),
    ("already_canon", ("already_canon",)),
)

_SETJ_YESNO_PATHS = frozenset(
    p
    for p, _ in _SETJ_FIELDS
    if p
    not in (
        "gates.tn.answer",
        "gates.t3a.fs.verdict",
        "gates.t4.fs.verdict",
        "gates.t3.owner",
        "gates.tn.proposed_name",
        "gates.e1.sightings",
        "gates.e1.post_demand_recurrence",
        "already_canon",
    )
)


def _get_path(data: object, keys: tuple[str, ...]) -> object:
    node = data
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _setj_already_legal(json_path: str, value: object) -> bool:
    """§3.5 Set-J — was ``value`` already a LEGAL value for this field
    BEFORE any repair touched it? "A field whose pre-repair value was
    ABSENT, NULL, or OUT-OF-ENUM is not pinned" (§3.5) — those three are
    treated uniformly here: ``None`` is never already-legal for ANY
    Set-J field, even `t1.separable`/`t1.cost_bearing`, whose OWN schema
    accepts null as a legal answer (`C4`) — the general Set-J rule calls
    out "null" as its own excluded state, not a per-field lookup, so
    supplying one of those two from null is `P1`/`P2` like everything
    else, never a pinned judgment."""
    if value is None:
        return False
    if json_path in _SETJ_YESNO_PATHS:
        return value in ("yes", "no")
    if json_path == "gates.tn.answer":
        return value in ("yes", "no", "indeterminate")
    if json_path in ("gates.t3a.fs.verdict", "gates.t4.fs.verdict"):
        return value in TRACE_FS_VERDICTS
    if json_path in ("gates.t3.owner", "gates.tn.proposed_name"):
        return isinstance(value, str) and bool(value)
    if json_path == "gates.e1.sightings":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1
    if json_path == "gates.e1.post_demand_recurrence":
        return isinstance(value, bool)
    if json_path == "already_canon":
        return isinstance(value, bool)
    return False


def _setj_violation(pre_text: str, post_text: str) -> str | None:
    """§3.5 Set-Q, structurally: compare a repaired file's Set-J fields
    against its pre-repair bytes. Returns the ``refuse`` reason for the
    FIRST field that moved off an already-legal value, or ``None``. An
    unparseable pre/post text is never a Set-J finding of its own — S8's
    ordinary validation already refuses an unparseable file (S6: this
    function itself never raises)."""
    from ruamel.yaml import YAML

    loader = YAML(typ="safe")
    try:
        old_data = loader.load(pre_text)
        new_data = loader.load(post_text)
    except Exception:  # noqa: BLE001 — S6
        return None
    if not isinstance(old_data, dict) or not isinstance(new_data, dict):
        return None
    for json_path, keys in _SETJ_FIELDS:
        old_value = _get_path(old_data, keys)
        if not _setj_already_legal(json_path, old_value):
            continue
        new_value = _get_path(new_data, keys)
        if new_value != old_value:
            return (
                f"repair changed a settled judgment ({json_path} "
                f"{old_value!r} → {new_value!r})"
            )
    return None


def _git_rm_or_unlink(home: Path, path: Path, result: "RunResult | None" = None) -> None:
    """Unlink now; the deletion is STAGED AND COMMITTED at run end by
    :func:`_commit_run`, never here.

    The 2026-07-15 letter-adjustment to the §7.1 orphan-sweep row was
    right that a background process must not park a deletion in the index
    for a racing verb's whole-index commit to swallow — but its second
    half ("autosync's `add -A` commits the deletion on its next cycle")
    died with the watcher (doc 13 H-5; audit 2026-07-16 MAJOR 3), leaving
    the worker's deletions committed by nobody. Both concerns hold at
    once: delete during the run, then stage surgically and commit ONCE at
    run end — the index carries this run's paths only for the moment it
    takes to commit them."""
    path.unlink(missing_ok=True)
    if result is not None:
        result.touched.append(path)


def _tracked(home: Path, path: Path) -> bool:
    from . import gitops

    return (
        gitops._git(  # noqa: SLF001 — same module family
            home, "ls-files", "--error-unmatch", "--", str(path)
        ).returncode
        == 0
    )


def _commit_run(home: Path, result: RunResult, *, no_push: bool = False) -> None:
    """H-5 (doc 13 §5): the worker commits its OWN writes at run end —
    validated proposals, and its deletions (invalid model output, orphan
    and invalidated-merge sweeps) — with the pinned subject
    ``self-learn: worker <n> proposal(s)``, then a best-effort push behind
    the has_remote guard.

    Audit 2026-07-16 MAJOR 3: nobody committed the worker's proposals once
    H-5 removed the watcher, so machine B re-analyzed every record from
    scratch and a re-clone destroyed the analysis. Staging stays SURGICAL
    (this run's paths only — never ``add -A``): a deleted path is staged
    only when git tracks it, an existing path only when it is one this run
    wrote. Git trouble is logged, never fatal — proposals are regenerable.

    BLOCKER 4 (2026-07-16): this is one of the two BACKGROUND committers M3
    added to the ledger — Popen-detached, kicked by every teach/import, so
    it fires while foreground verbs are mid-``git mv``. The stage→commit
    runs inside the repo's commit lock, and the commit carries its own
    pathspec.

    Round 7: the lock is taken by :func:`_commit_locked`, and ``run`` takes
    it EARLIER still (in :func:`_harvest`, before ``_validate_written``
    deletes anything) — re-entrantly, so this entry point keeps working
    standalone. The push stays outside every lock.

    BLOCKER 3: the push honors :func:`no_push_requested` — the invoking
    verb's ``--no-push`` binds the worker IT spawned, or ``teach --no-push``
    keeps a record local only until the worker it kicked publishes the whole
    branch a second later."""
    if not _commit_locked(home, result):
        return
    _push_run(home, no_push=no_push)


def _commit_locked(home: Path, result: RunResult) -> bool:
    """Stage → commit this run's paths. Takes the lock (re-entrant: `run`
    already holds it). True iff a commit landed.

    Staging stays SURGICAL (this run's paths only — never ``add -A``): a
    deleted path is staged only when git tracks it, an existing path only
    when it is one this run wrote. Audit 2026-07-16 MAJOR 3: nobody
    committed the worker's proposals once H-5 removed the watcher, so
    machine B re-analyzed every record from scratch and a re-clone
    destroyed the analysis. Git trouble is logged, never fatal — proposals
    are regenerable."""
    from . import gitops

    if not result.touched:
        return False
    stage: list[str] = []
    for path in dict.fromkeys(result.touched):  # de-dup, order-stable
        if path.exists() or _tracked(home, path):
            stage.append(str(path))
    if not stage:
        return False
    # BLOCKER B: EVERY GitOpsError is caught, including the one raised by
    # ACQUIRING the lock (a timeout) and by a git call that blew its own
    # timeout. This is a detached, Popen'd process: an escaping exception
    # is a stack dump into worker.log and a dead run, for a condition —
    # "another producer is committing right now" — that is not even an
    # error. Proposals are regenerable; the next run redoes this.
    try:
        with gitops.commit_lock(home):
            proc = gitops._git(home, "add", "--", *stage)  # noqa: SLF001
            if proc.returncode != 0:
                log(f"run: staging failed ({(proc.stderr or proc.stdout).strip()})")
                return False
            # Scoped to THIS run's paths: an index-wide --quiet would answer
            # about someone else's staged work (pathspec discipline).
            if (
                gitops._git(  # noqa: SLF001
                    home, "diff", "--cached", "--quiet", "--", *stage
                ).returncode
                == 0
            ):
                return False  # nothing changed (byte-identical re-stamp)
            n = result.valid_landed
            result.commit_sha = gitops.commit(
                home,
                f"self-learn: worker {n} proposal{'s' if n != 1 else ''}",
                paths=stage,
            )
    except gitops.GitOpsError as exc:
        log(f"run: commit failed ({exc}) — proposals left uncommitted")
        return False
    return True


def _push_run(home: Path, *, no_push: bool) -> None:
    """The push — OUTSIDE every lock (it touches no index — see the gitops
    module docstring for the re-scope) and outside the commit's try: a push
    failure must never look like a commit failure."""
    from . import gitops

    if no_push:
        log("run: push skipped — --no-push in effect")
        return
    try:
        push = gitops.push_if_remote(home)
    except gitops.GitOpsError as exc:
        # BLOCKER B: this is a DETACHED process. A traceback here goes to
        # worker.log and kills the run; the proposals are committed and a
        # later run republishes them.
        log(f"run: push errored ({exc}) — commit kept locally")
        return
    if not push.ok:
        log(f"run: push failed ({push.detail}) — commit kept locally")


def _cache_clear(name: str) -> None:
    """Delete one of the worker's CACHE flag files.

    A one-line helper for a one-line operation, and it earns that: the
    lock-invariant check (tests/test_lock_invariant.py) reads a bare
    ``.unlink()`` in ``run`` as a repo mutation and cannot tell
    ``$XDG_CACHE_HOME/.../worker.window`` from a ledger record — and it is
    right not to guess. Naming the cache writes makes ``run``'s remaining
    filesystem mutations exactly the ones that touch the LEDGER, which is
    what the invariant is about. The code now says which files it means."""
    _p(name).unlink(missing_ok=True)


# ------------------------------------------- U-repair §3.10: the backoff


def _read_failure_count() -> int:
    """``cache_dir()/worker.failures`` — one decimal integer, the count
    of CONSECUTIVE failed runs. Unreadable/garbage is read as 0 and
    logged once; a cache file must never wedge the worker."""
    try:
        raw = _p("worker.failures").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return 0
    try:
        return int(raw)
    except ValueError:
        log(f"run: worker.failures is unreadable ({raw!r}) — treated as 0")
        return 0


def _write_failure_count(n: int) -> None:
    path = _p("worker.failures")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(n), encoding="utf-8")


def _increment_failure_count() -> None:
    _write_failure_count(_read_failure_count() + 1)


def _reset_failure_count() -> None:
    """Delete the counter file — an `ok`/`idle` run's own reset, and
    :func:`kick`'s (E7: an explicit human kick is a fresh mandate and
    must never be refused by a backoff counter)."""
    _p("worker.failures").unlink(missing_ok=True)


def _harvest(
    home: Path,
    written: list[Path],
    roster: Roster | None = None,
    *,
    refuse: dict[Path, str] | None = None,
) -> RunResult:
    """Validate + sweep + commit, as ONE locked section (audit 2026-07-16
    round 7 — the invariant: no ledger mutation may precede its lock).

    A lock failure is LOGGED, never raised: this runs in a Popen-detached
    process where an escaping exception is a stack dump into worker.log and
    a dead run (BLOCKER B), for a condition — "another producer is
    committing right now" — that is not an error. Because the lock is taken
    BEFORE the first mutation, refusing here costs nothing: the model's
    output stays on disk untouched and the next run validates it.

    ``roster`` (U-composer §3.6) is the :class:`Roster` composed for THIS
    run's prompt — threaded through so :func:`_validate_written` can check
    the roster-sha honesty legs against the roster the model actually saw,
    not a freshly recomposed one. ``refuse`` (U-repair §3.5/S8) is S5's
    forced-refusal map (Set-J pin violations, V-set rewrites) — a path in
    it is refused UNCONDITIONALLY, even if its content would otherwise now
    validate."""
    from . import gitops

    try:
        with gitops.commit_lock(home):
            result = _validate_written(home, written, roster, refuse=refuse)
            _still_pending(home, result)
            result.committed = _commit_locked(home, result)
            return result
    except gitops.GitOpsError as exc:
        log(f"run: could not take the ledger lock ({exc}) — nothing swept")
        return RunResult(status="failed")


def _bucket_name(home: Path, path: Path) -> str | None:
    for bucket in discover_buckets(home):
        try:
            path.relative_to(bucket.path)
        except ValueError:
            continue
        return bucket.name
    return None


def _roster_sha_dishonest(data: dict, roster: Roster) -> str | None:
    """§3.6's two legs, shared by the worker and (in spirit — the analyst
    runs its own copy against ``AnalystError``) the one-shot analyst.
    Returns a refusal message, or ``None`` when the claimed
    ``gates.t3.roster_sha`` is honest against ``roster`` — the Roster
    actually composed for THIS run. Never raises: `gates`/`t3` may be
    absent or malformed on a proposal that will be refused for other
    reasons first; this function degrades to "nothing to check" rather
    than crashing the caller's loop (S6's discipline, applied here even
    though this is not `_validate_gates` itself)."""
    gates = data.get("gates")
    if not isinstance(gates, dict):
        return None
    t3 = gates.get("t3")
    if not isinstance(t3, dict):
        return None
    claimed = t3.get("roster_sha")
    if claimed == ROSTER_UNAVAILABLE:
        # Leg B — no false degradation: `unavailable` is legal only when
        # the composer ITSELF returned ROSTER_UNAVAILABLE for this run.
        if roster.sha != ROSTER_UNAVAILABLE:
            return (
                f"gates.t3.roster_sha claims {ROSTER_UNAVAILABLE!r} but this "
                f"run's roster WAS composed (real sha {roster.sha!r}) — a "
                "model that never reads a good roster cannot claim it was "
                "unavailable (X3 Leg B)"
            )
        return None
    if isinstance(claimed, str) and claimed != roster.sha:
        # Leg A — no fabricated sha: a well-shaped sha that is not THIS
        # run's roster sha is refused, whether or not it happens to look
        # legitimate.
        return (
            f"gates.t3.roster_sha {claimed!r} does not match this run's "
            f"composed roster sha {roster.sha!r} (X3 Leg A)"
        )
    return None


@dataclass
class _Verdict:
    """One path's outcome from :func:`_check_proposal_file` — S4's dry
    pass and S8's real pass both build these (B1: one definition)."""

    error: str | None  # None iff valid; else the ProposalError message
    phi: bool  # Rule-F's F-a AND F-b (§3.5's Φ) — REGARDLESS of hook
    record_sha_matches: bool  # F-b alone (E-5 needs this on INVALID files too)
    is_hook: bool
    is_merge: bool
    name: str
    bucket: str | None
    #: The prepared merge document (record_shas resolved in memory),
    #: ready to write — populated ONLY for a schema-valid merge proposal;
    #: `None` in every other case. A non-merge success needs nothing
    #: carried forward: `stamp_proposal` re-reads the file itself.
    merge_data: dict | None = None


def _check_proposal_file(
    home: Path,
    path: Path,
    roster: Roster | None,
    refuse: dict[Path, str],
) -> _Verdict:
    """THE per-file check (§3.3, B1: one definition, not two) — S4's dry
    pass and S8's real pass both call this SAME function. It is PURE: it
    reads and validates, and NEVER writes, stamps, dumps or deletes
    anything itself. That is not merely a convention here — it is what
    makes the lock invariant provable by source (tests/
    test_lock_invariant.py): this function is reachable from an UNLOCKED
    caller (S4, before the model's repair invocation even runs) and a
    LOCKED one (S8, via `_harvest`'s `commit_lock`), and a static analysis
    cannot see that a runtime flag would have skipped a write on the
    unlocked path — so the write must not exist in this function's body
    AT ALL. Every actual mutation (`_dump_yaml`, `stamp_proposal`,
    `_git_rm_or_unlink`) lives in :func:`_validate_written` instead, which
    only `_harvest` ever calls.

    Per-file order is normative (§3.8): naming-contract check -> secret
    scan -> read_proposal -> refusal-map override (``refuse``, §3.5) ->
    resolve the pending record -> validate_proposal (+ roster-sha honesty)
    -> Rule-F. A path in ``refuse`` is refused UNCONDITIONALLY at that
    point, even when its post-repair content would otherwise now
    validate (§3.5's Set-Q enforcement — a forced refusal is a verdict,
    not a hint to validate harder).

    Rule-F (§3.8): ``phi`` is F-a (validation + roster-sha honesty
    accepted it) AND F-b (``record_sha_matches``) — computed REGARDLESS
    of destination, because Φ's S4/S5 partition membership (§3.5) must
    include `destination: hook` proposals on the same terms as anything
    else. The hook carve-out is applied by the CALLER's stamp-or-leave
    branch, never here (`D6(iii)`)."""
    name = path.stem
    is_merge = name.startswith("merge-")
    expected_shape = (
        path.parent.name == "proposals"
        and path.suffix == ".yaml"
        and (name.startswith("lrn-") or is_merge)
    )
    error: str | None = None
    phi = False
    record_sha_matches = False
    is_hook = False
    merge_data: dict | None = None
    bucket = _bucket_name(home, path)
    try:
        if not expected_shape:
            raise ProposalError(
                "unexpected artifact outside the proposal naming contract"
            )
        hits = secret_scan(path.read_text(encoding="utf-8"))
        if hits:
            raise ProposalError(
                f"secret scan hit ({hits[0].rule}) — never published"
            )
        data = read_proposal(path)
        if path in refuse:
            raise ProposalError(refuse[path])
        if is_merge:
            # Members/record_shas are resolved IN MEMORY and
            # validate_merge_proposal runs unconditionally (§3.3) — only
            # the eventual `_dump_yaml` write (the caller's job) is a
            # real mutation.
            shas = {}
            for rid in data.get("records") or []:
                rpath = path.parent.parent / "pending" / f"{rid}.md"
                if not rpath.is_file():
                    raise ProposalError(f"merge member {rid} not pending")
                shas[rid] = sha_anchor(Record.from_path(rpath).body)
            data["record_shas"] = shas
            validate_merge_proposal(data)
            merge_data = data
        else:
            # F1/N1 (§3.7): rpath resolves FIRST — the swap — so the
            # record it names can supply record_text= AND scope= to
            # the SAME validate_proposal call below.
            rpath = path.parent.parent / "pending" / f"{name}.md"
            if not rpath.is_file():
                raise ProposalError(f"no pending record for {name}")
            pending_record = Record.from_path(rpath)
            # F-b, computed BEFORE validate_proposal so E-5 can see it
            # even on an INVALID file (the copy-the-line-you-found shape,
            # §3.8 BLOCKER 1).
            record_sha_matches = data.get("record_sha") == sha_anchor(
                pending_record.body
            )
            is_hook = data.get("destination") == "hook"
            validate_proposal(
                data,
                record_text=pending_record.to_text(),
                scope=pending_record.scope,
            )
            if roster is not None:
                dishonest = _roster_sha_dishonest(data, roster)
                if dishonest is not None:
                    raise ProposalError(dishonest)
            # F-a is satisfied: we are past validation + roster-sha
            # honesty without raising.
            phi = record_sha_matches
    except Exception as exc:  # noqa: BLE001 — unattended: caller deletes + logs (S6)
        error = str(exc)
    return _Verdict(
        error=error,
        phi=phi,
        record_sha_matches=record_sha_matches,
        is_hook=is_hook,
        is_merge=is_merge,
        name=name,
        bucket=bucket,
        merge_data=merge_data,
    )


def _dry_check_batch(
    home: Path, written1: list[Path], roster: Roster | None
) -> dict[Path, _Verdict]:
    """Seq-1 S4 — classify every path in ``written1`` with the SAME
    per-file check S8 performs, mutating NOTHING on disk (B1) — trivially
    true here, since :func:`_check_proposal_file` never mutates at all."""
    return {
        path: _check_proposal_file(home, path, roster, {})
        for path in written1
    }


def _validate_written(
    home: Path,
    written: list[Path],
    roster: Roster | None = None,
    *,
    refuse: dict[Path, str] | None = None,
) -> RunResult:
    """Run-sequence step 8 (§3.3): validate + stamp + delete, for REAL —
    schema-invalid worker output is DELETED and logged (unattended
    policy — the attended `proposal validate` verb reports-never-deletes);
    valid proposals get record_sha stamped by the CLI, overwriting
    anything the model wrote. Classifies every path via
    :func:`_check_proposal_file` — the SAME function :func:`_dry_check_batch`
    (S4) calls (B1) — and is the ONLY place that turns a verdict into an
    actual write, stamp, or delete; only :func:`_harvest` calls this
    function, always under `commit_lock`.

    ``refuse`` (§3.5, S5's output) forces a deletion regardless of what
    S8's own re-validation would conclude — the Set-J pin and the V-set
    rewrite rule are both expressed this way (§3.3: "every deletion this
    unit adds is expressed as an entry in `refuse`")."""
    refuse = refuse or {}
    result = RunResult(status="failed")
    for path in written:
        verdict = _check_proposal_file(home, path, roster, refuse)
        if verdict.error is not None:
            log(f"run: invalid worker output {path.name} deleted ({verdict.error})")
            result.invalid_deleted.append(path.name)
            _git_rm_or_unlink(home, path, result)
            continue
        if verdict.phi and not verdict.is_hook:
            # Rule-F: leave entirely alone (§3.8) — the hook carve-out
            # (D9) is the one destination that never takes this branch,
            # because `stamp_proposal` is the only guard against
            # model-authored `script:` bytes (P9).
            result.foreign_left.append(verdict.name)
            log(
                f"run: proposal {path.name} carries a matching "
                "record_sha — another producer wrote it; left untouched"
            )
            continue
        try:
            if verdict.is_merge:
                assert verdict.merge_data is not None
                _dump_yaml(verdict.merge_data, path)  # same writer as stamping
                result.merge_proposed.append(verdict.merge_data["cluster_id"])
                result.touched.append(path)
            else:
                stamp_proposal(home, verdict.name)
                result.proposed.append(verdict.name)
                result.touched.append(path)
            if verdict.bucket and verdict.bucket not in result.buckets:
                result.buckets.append(verdict.bucket)
        except Exception as exc:  # noqa: BLE001 — unattended: delete + log (S6)
            log(f"run: invalid worker output {path.name} deleted ({exc})")
            result.invalid_deleted.append(path.name)
            _git_rm_or_unlink(home, path, result)
    result.valid_landed = len(result.proposed) + len(result.merge_proposed)
    return result


def _still_pending(home: Path, result: RunResult) -> None:
    """Run-sequence step 5: drop resolved-mid-run ids from the event and
    sweep orphan proposals (no matching pending record → git rm)."""
    result.proposed = [
        rid
        for rid in result.proposed
        if any(
            (b.path / "pending" / f"{rid}.md").is_file()
            for b in discover_buckets(home)
        )
    ]
    for bucket in discover_buckets(home):
        pdir = bucket.path / "proposals"
        if not pdir.is_dir():
            continue
        for path in sorted(pdir.glob("lrn-*.yaml")):
            if not (bucket.path / "pending" / f"{path.stem}.md").is_file():
                log(f"run: orphan proposal {path.name} swept")
                result.orphans_swept.append(path.name)
                _git_rm_or_unlink(home, path, result)
        for path in sorted(pdir.glob("merge-*.yaml")):
            try:
                members = read_proposal(path).get("records", [])
            except Exception:  # noqa: BLE001
                members = []
            if not members or not all(
                (bucket.path / "pending" / f"{rid}.md").is_file()
                for rid in members
            ):
                log(f"run: invalidated merge proposal {path.name} swept")
                result.orphans_swept.append(path.name)
                _git_rm_or_unlink(home, path, result)


# ------------------------------------------- recurrence suspects (11 §2.2)


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(
        c.lower() if c.isalnum() else " " for c in text
    ).split() if len(t) > 2}


def _recurrence_suspects(home: Path, batch: list) -> int:
    """Deterministic detection: a NEW pending capture whose title overlaps
    an already-ROUTED lesson's (``title-token-overlap``, Jaccard ≥
    :data:`SUSPECT_JACCARD`). Suspects are telemetry events — the machine
    never writes the record; `confirm-recurrence` is the human's.

    FW-49 (2026-08-02): this used to also compute an ``origin-match``
    basis (``pending.evidence`` origins intersecting ``routed.evidence``
    origins) — removed because it is PROVABLY, PERMANENTLY unreachable,
    not merely rare, for two independent reasons: (1) every mined
    candidate is checked against :func:`import_common.existing_origins`
    — the GLOBAL set of every ``evidence.origin`` across every record,
    every status, every bucket — before it is allowed to land or fold
    (`miner.py` `_reconcile_and_land`), so a freshly-landed pending
    record's origins are by construction always disjoint from every
    other record's; (2) independently, `teach`-authored pending records
    never populate an ``origin`` key on their evidence entries at all
    (they carry ``session``/``quote``, not ``origin`` — see `teach.py`),
    so ``p_origins`` was unconditionally empty for that whole source
    class regardless of (1). Confirmed by running this function against
    a full copy of the live ledger (35 pending × 31 routed, same-bucket
    pairs only): 0 hits, with or without the origin branch. Kept
    ``title-token-overlap`` as the sole live basis rather than widening
    it — tried full-section-body tokens as a broader signal and measured
    it *lower* the one near-miss pair's Jaccard (0.571 title → 0.33
    body; longer text dilutes overlap), and that near-miss
    (`lrn-4323466d` vs `lrn-5d0c592a`) is a deliberate `--supersedes`
    refinement, not a recurrence, so it is correctly silent, not a false
    negative to chase.

    Dedupe key is ``(record, origin)`` — the SAME shape the miner's
    crossover/backfill use (`miner.py` `_raise_recurrence_suspect`,
    `_event_seen`), deliberately: this producer's ``origin`` is always a
    pending record id (``lrn-…``) and the miner's is always a transcript
    ref (``transcript:<session>#L<line>``), disjoint value spaces by
    construction — so the two producers can never emit a byte-identical
    duplicate row for the two of them to collide on, and that is
    intentional, not an oversight: a title-overlap suspect's evidence
    IS the new pending record, a fire-violated suspect's evidence IS the
    transcript line, and those are two different, independently
    confirmable observations even when they concern the same underlying
    incident."""
    already = {
        (e.get("record"), e.get("origin"))
        for e in telemetry.read_events(home)
        if e.get("kind") == "recurrence-suspect"
    }
    count = 0
    for entry in batch:
        pending = entry.record
        p_tokens = _tokens(record_title(pending))
        resolved_dir = entry.bucket_dir / "resolved"
        if not resolved_dir.is_dir():
            continue
        for path in sorted(resolved_dir.glob("lrn-*.md")):
            try:
                routed = Record.from_path(path)
            except RecordError:
                continue
            if routed.status != "routed":
                continue
            r_tokens = _tokens(record_title(routed))
            union = p_tokens | r_tokens
            if not union or len(p_tokens & r_tokens) / len(union) < SUSPECT_JACCARD:
                continue
            if (routed.id, pending.id) in already:
                continue
            telemetry.spool_quiet(
                "recurrence-suspect",
                record=routed.id,
                origin=pending.id,
                basis="title-token-overlap",
            )
            count += 1
    return count


# ------------------------------------------------- events + notifications


def append_event(event: str, record_ids: list[str], aggregate: dict) -> None:
    path = _p("events.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "ts": _now_iso(),
            "event": event,
            "record_ids": record_ids,
            "aggregate": aggregate,
        },
        separators=(",", ":"),
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    _truncate_oldest(path, EVENTS_CAP_BYTES)


def render_notification(n: int, buckets: list[str], total: int, scopes: int) -> str:
    """THE pinned template (08 §7.1 Notification-rendering row)."""
    s1 = "s" if n != 1 else ""
    s2 = "s" if scopes != 1 else ""
    return (
        f"self-learn: {n} new proposal{s1} for {', '.join(buckets)}. "
        f"{total} pending across {scopes} scope{s2} — /self-learn:review"
    )


def _notifications_suppressed() -> bool:
    """True iff ``SELF_LEARN_NO_NOTIFY=1`` — the EXPLICIT kill switch for
    BOTH notify transports (:func:`_notify`, :func:`_notify_with_ids`).

    Incident 2026-08-09: both functions resolve their helper via PATH,
    which on a dev machine finds the REAL deployed ``~/bin`` scripts
    regardless of whether the CALLING process is a sandboxed/dev/test
    worker run — so any such run notified the operator's REAL desktop
    (measured: fixture proposal lrn-10000000 notified repeatedly from an
    agent worktree).

    NOT keyed on ``SELF_LEARN_HOME`` (the tempting "dev/test redirects
    it" signal) — verified against BOTH deployed production invocation
    paths: ``systemd/self-learn-miner.service`` and
    ``systemd/self-learn-ui.service`` each pin
    ``Environment=SELF_LEARN_HOME=%h/.self-learn`` explicitly (systemd
    does not inherit the shell's env, B-1 doc 13 §7.1). SELF_LEARN_HOME
    is therefore ALWAYS set in real, live, production runs too — keying
    on "set" would silently kill live notifications forever. The test
    suite's conftest.py sets THIS explicit var globally (mirroring
    ``SELF_LEARN_WORKER_AUTOKICK``'s own convention) so every test is
    silent by default; a harness that wants the shimmed transport
    exercised opts back out via ``monkeypatch.delenv``."""
    return os.environ.get("SELF_LEARN_NO_NOTIFY") == "1"


def _notify(message: str) -> None:
    """notify-send when available, stderr otherwise — failure never fails
    a run (headless/SSH has no DBus). No -A/action flags anywhere, so no
    wait to bound (user CLAUDE.md swaync rule applies to -A only).

    ``SELF_LEARN_NO_NOTIFY=1`` is a hard no-op (see
    :func:`_notifications_suppressed`), checked before even probing
    PATH."""
    if _notifications_suppressed():
        return
    try:
        if shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", "self-learn", message],
                capture_output=True,
                timeout=10,
            )
            return
    except Exception:  # noqa: BLE001
        pass
    print(message, file=sys.stderr)


def _notify_with_ids(message: str, ids: list[str]) -> None:
    """G-3 emission point (10 U8; 09 §3 "Notifications" / 08 §7.1
    "Notification rendering" pointer): the ids-bearing (proposals)
    notification's transport swaps from a direct ``notify-send`` call to
    a DETACHED spawn of the pinned companion script, with the pinned
    argv (10 §1 "Companion scripts" row) —

        self-learn-notify --line "<message>" --ids <csv-of-record-ids>

    resolved via PATH (the ``~/bin`` deploy surface). Template, payload,
    and the events.jsonl line are untouched by this swap — ``message``
    is still exactly ``render_notification``'s output and ``ids`` is
    still exactly the ids ``append_event`` already logged; only the
    transport changes.

    Never waited on: one process per notification, and the worker must
    never block on swaync/the click-action listener (self-learn-notify
    itself blocks on ``notify-send --wait`` until the notification is
    acted on or expires — that latency must never become the worker's).
    Helper absent (partial/headless deploy, or PATH resolution/spawn
    failure) degrades to the M2 direct-notify-send path (:func:`_notify`),
    logged once — the same graceful-degradation posture 09 §5 pins for
    "swaync absent / action unsupported".

    ``SELF_LEARN_NO_NOTIFY=1`` is a hard no-op (see
    :func:`_notifications_suppressed`), checked FIRST — before even
    probing PATH — so a suppressed call never spawns anything (real OR
    shimmed) and never falls through to the (also-suppressed) fallback."""
    if _notifications_suppressed():
        return
    helper = shutil.which("self-learn-notify")
    if not helper:
        log("notify: self-learn-notify not on PATH — falling back to direct notify-send")
        _notify(message)
        return
    try:
        subprocess.Popen(
            [helper, "--line", message, "--ids", ",".join(ids)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        log("notify: failed to spawn self-learn-notify — falling back to direct notify-send")
        _notify(message)


def _oldest_pending_days(home: Path) -> int:
    oldest = 0
    now = datetime.now(timezone.utc)
    for bucket in discover_buckets(home):
        for entry in queue(bucket):
            created = str(entry.record.created_at)[:10]
            try:
                then = datetime.fromisoformat(created).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            oldest = max(oldest, (now - then).days)
    return oldest


def _maybe_escalate(home: Path, total_pending: int, per_bucket: list[dict]) -> bool:
    """Worker-run-end-only escalation, debounced 24 h (pinned)."""
    oldest = _oldest_pending_days(home)
    if total_pending < ESCALATE_PENDING and oldest <= ESCALATE_OLDEST_DAYS:
        return False
    marker = _p("worker.last-escalated")
    try:
        if time.time() - marker.stat().st_mtime < ESCALATE_DEBOUNCE_SECS:
            return False
    except FileNotFoundError:
        pass
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    append_event(
        "escalation", [], {"pending": total_pending, "buckets": per_bucket}
    )
    _notify(
        f"self-learn: backlog needs attention — {total_pending} pending, "
        f"oldest {oldest}d — /self-learn:review"
    )
    log(f"escalation: pending={total_pending} oldest={oldest}d")
    return True


# ------------------------------------------------ fast status (T15 pin)

#: Staleness predicate constant (08 §7.1): last-run older than this (or
#: missing = infinitely old) with un-analyzed supply present ⇒ alarm.
STALE_AFTER_SECS = 3 * 24 * 60 * 60


def last_run_iso() -> str | None:
    """`status --json` amendment (08 §7.1): iso8601 | null (never ran on
    this machine)."""
    try:
        mtime = _p("worker.last-run").stat().st_mtime
    except FileNotFoundError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def fast_status(home: Path | str) -> dict:
    """`status --json --fast` (08 §7.1 SessionStart pin): a pending/-only
    frontmatter scan — no git, no network, no resolved/ walk (follow-up
    counts deliberately excluded), <500 ms warm on 100 records. Queue
    semantics are THE same rules as `list` (deferred hidden), computed
    here once so the bash hook never reimplements them."""
    from ruamel.yaml import YAML  # local: keep module import cost flat

    yaml = YAML(typ="safe")
    home = Path(home)
    now = datetime.now(timezone.utc)
    buckets_out: list[dict] = []
    total = 0
    unanalyzed_total = 0
    oldest_all = 0

    for bucket in discover_buckets(home):
        pending = 0
        unanalyzed = 0
        oldest = None
        for path in bucket.pending_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # 09 §5 FW-18 crash-prevention: UnicodeDecodeError is a
                # ValueError, not an OSError — undecodable bytes would
                # otherwise crash the --fast scan. The --fast path still
                # OMITS the `unreadable` count (this is skip-not-count).
                continue
            lines = text.split("\n")
            if not lines or lines[0] != "---":
                continue
            try:
                close = lines[1:].index("---") + 1
                fm = yaml.load("\n".join(lines[1:close]))
            except Exception:  # noqa: BLE001 — unparseable: not queued
                continue
            if not isinstance(fm, dict):
                continue
            until = fm.get("deferred_until")
            if until is not None:
                try:
                    until_d = datetime.fromisoformat(str(until)[:10]).replace(
                        tzinfo=timezone.utc
                    )
                    if until_d > now:
                        continue  # hidden — same rule as the queue
                except ValueError:
                    pass
            pending += 1
            created = str(fm.get("created_at", ""))[:10]
            try:
                age = (
                    now
                    - datetime.fromisoformat(created).replace(tzinfo=timezone.utc)
                ).days
                oldest = age if oldest is None else max(oldest, age)
            except ValueError:
                age = None
            body = "\n".join(lines[close + 1 :])
            ppath = bucket.path / "proposals" / f"{fm.get('id')}.yaml"
            fresh = False
            if ppath.is_file():
                try:
                    pdata = yaml.load(ppath.read_text(encoding="utf-8"))
                    # SAME predicate as is_unanalyzed: hash match AND
                    # schema validity (audit 2026-07-15: a sha-intact but
                    # schema-broken proposal must not suppress the alarm).
                    if (
                        isinstance(pdata, dict)
                        and pdata.get("record_sha") == sha_anchor(body)
                    ):
                        validate_proposal(dict(pdata), record_text=text)
                        fresh = True
                except Exception:  # noqa: BLE001
                    fresh = False
            if not fresh:
                unanalyzed += 1
        if pending:
            buckets_out.append(
                {
                    "bucket": bucket.name,
                    "scope": bucket.scope,
                    "pending": pending,
                    "unanalyzed": unanalyzed,
                    "oldest_days": oldest,
                }
            )
        total += pending
        unanalyzed_total += unanalyzed
        if oldest is not None:
            oldest_all = max(oldest_all, oldest)

    last_run = last_run_iso()
    stale = False
    if unanalyzed_total >= 1:
        try:
            age_secs = time.time() - _p("worker.last-run").stat().st_mtime
        except FileNotFoundError:
            age_secs = float("inf")  # missing = infinitely old (pinned)
        stale = age_secs > STALE_AFTER_SECS
    return {
        "buckets": buckets_out,
        "total_pending": total,
        "unanalyzed_total": unanalyzed_total,
        "oldest_days": oldest_all,
        "worker_last_run": last_run,
        "staleness_alarm": stale,
        "escalate": total >= ESCALATE_PENDING
        or oldest_all > ESCALATE_OLDEST_DAYS,
    }


# --------------------------------------------------------------- the run


def _invoke_claude(
    argv: list[str], prompt: str, timeout: float, home: Path, *, label: str
) -> None:
    """One model invocation — round 1 (``label=""``) or the repair round
    (``label="repair "``), same exception handling shape as this project
    shipped before U-repair; the label prefix is what distinguishes their
    log lines (§3.12). Never raises — an invocation failure is logged and
    the run continues (round 1's valid output, if any, must still land;
    B7)."""
    try:
        proc = subprocess.run(
            argv,
            cwd=str(home),
            input=prompt,  # stdin — argv caps at 128 KiB (audit)
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            log(
                f"run: {label}claude exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout)[:400]}"
            )
    except FileNotFoundError:
        log(f"run: {label}claude CLI not found on PATH")
    except subprocess.TimeoutExpired:
        log(f"run: {label}claude timed out after {timeout:g}s")
    except OSError as exc:
        log(f"run: {label}claude invocation failed ({exc})")


def run(
    home: Path | str, *, coalesce: bool = False, no_push: bool | None = None
) -> RunResult:
    """``no_push=None`` reads the process boundary once
    (:func:`no_push_requested`) and then threads the answer as a parameter
    — BLOCKER D: the policy is data, not ambience."""
    home = Path(home)
    if no_push is None:
        no_push = no_push_requested()
    cache_dir().mkdir(parents=True, exist_ok=True)
    if coalesce:
        time.sleep(coalesce_secs())

    with open(_p("worker.lock"), "w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)  # blocking (pinned)
        # Self-hold the sentinel for the rest of the run. There is no
        # sync-first step any more (audit 2026-07-16 MINOR 10): it looked
        # for `<home>/bin/claude-skills-sync`, which the LEDGER home will
        # never contain — doc 13 H-5 gives the ledger no watcher at all,
        # so every run logged "skipped" forever. The sentinel hold remains
        # (it pauses the HOST repos' autosync during the canon-adjacent
        # window) with the same discipline as the verbs:
        # skip-if-held-by-other, release iff owned; a crashed run goes
        # stale at the 2 h TTL.
        _cache_clear("worker.window")
        hold = sentinel.hold()
        sentinel.heartbeat()
        try:
            batch, leftovers, total_pending, per_bucket = _enumerate(home)
            if leftovers == 0:
                _cache_clear("worker.dirty")  # AFTER enumeration
            else:
                # pinned: leftovers keep worker.dirty set → follow-on window
                _p("worker.dirty").touch()
                log(f"run: {leftovers} eligible beyond the batch cap — "
                    "dirty kept for a follow-on window")

            suspects = _recurrence_suspects(home, batch)

            if not batch:
                _p("worker.last-run").touch()
                log(f"run: idle (0 eligible, {total_pending} pending)")
                result = RunResult(status="idle", eligible=0, suspects=suspects)
            else:
                repairs_enabled = os.environ.get("SELF_LEARN_REPAIR") != "0"
                prompt, roster = compose_batch_prompt(home, batch)
                snap0 = _proposal_snapshot(home)  # S1
                argv = build_argv(home, write_settings_file(home))
                _invoke_claude(argv, prompt, invoke_timeout_secs(), home, label="")  # S2
                # S6 (moved here, §3.3): re-assert the sentinel hold after
                # the invocation. A CONCURRENT short holder (e.g. the
                # miner's landing phase) may have created-then-RELEASED
                # the sentinel we joined, deleting autosync cover mid-run
                # (audit 2026-07-15: owner/joiner race). heartbeat()
                # returns False on a missing file and never resurrects:
                # re-assert the hold before validation. Re-asserted AGAIN
                # after the repair invocation below (G8) — strictly safer.
                if not sentinel.heartbeat():
                    hold = sentinel.hold()
                    sentinel.heartbeat()

                written1 = _written_since(home, snap0)  # S3
                batch_ids = {entry.record.id for entry in batch}
                repair_attempted = False
                repair_eligible_paths: dict[Path, str] = {}
                refuse: dict[Path, str] = {}

                if not repairs_enabled:
                    log("run: repair round disabled (SELF_LEARN_REPAIR=0)")
                else:
                    verdicts = _dry_check_batch(home, written1, roster)  # S4
                    n_refused = sum(1 for v in verdicts.values() if v.error is not None)
                    # S5's E — Set-E's text rules (E-1..E-3) AND the two
                    # provenance rules (E-4 batch membership, E-5 unstamped).
                    repair_eligible_paths = {
                        p: v.error
                        for p, v in verdicts.items()
                        if v.error is not None
                        and _repairable(v.error) == "ELIGIBLE"
                        and p.stem in batch_ids  # E-4
                        and not v.record_sha_matches  # E-5
                    }
                    n_eligible = len(repair_eligible_paths)
                    n_ineligible = n_refused - n_eligible
                    log(
                        f"run: repair round — {n_refused} refused, "
                        f"{n_eligible} eligible, {n_ineligible} not repairable"
                    )
                    if not repair_eligible_paths:
                        log("run: repair round skipped (no eligible refusals)")
                    else:
                        repair_attempted = True
                        pre = {
                            p: p.read_text(encoding="utf-8")
                            for p in repair_eligible_paths
                        }
                        snap1 = _proposal_snapshot(home)
                        repair_prompt = _compose_repair_prompt(
                            home, repair_eligible_paths
                        )
                        repair_settings = write_repair_settings_file(
                            home, list(repair_eligible_paths)
                        )
                        repair_argv = build_argv(home, repair_settings)
                        _invoke_claude(
                            repair_argv,
                            repair_prompt,
                            repair_timeout_secs(),
                            home,
                            label="repair ",
                        )
                        # G8: re-assert again after the LAST invocation.
                        if not sentinel.heartbeat():
                            hold = sentinel.hold()
                            sentinel.heartbeat()

                        touched2 = set(_written_since(home, snap1))
                        written1_set = set(written1)
                        phi_at_s4 = {p for p in written1_set if verdicts[p].phi}
                        v_at_s4 = {
                            p
                            for p in written1_set
                            if verdicts[p].error is None and p not in phi_at_s4
                        }
                        # A-set (= E): the Set-J pin.
                        for p in repair_eligible_paths:
                            if p not in touched2:
                                continue
                            violation = _setj_violation(
                                pre[p], p.read_text(encoding="utf-8")
                            )
                            if violation is not None:
                                refuse[p] = violation
                        # V-set: valid-at-S4-and-not-foreign, rewritten
                        # during the repair window.
                        for p in v_at_s4:
                            if p in touched2:
                                refuse[p] = (
                                    "repair rewrote a proposal that had "
                                    "already validated"
                                )
                        # O-set (touched2 minus A/Φ/V) is intentionally
                        # NOT refused here — Rule-F applies fresh at S8
                        # (§3.5's own O-set rule; D4).

                written = _written_since(home, snap0)  # S7 — both rounds
                # [first mutation → commit] under ONE lock (audit
                # 2026-07-16 round 7, THE invariant). `_validate_written`
                # DELETES schema-invalid model output and sweeps orphaned
                # and invalidated-merge proposals — deletions of TRACKED
                # files, i.e. exactly the worktree mutation a racing `pull
                # --rebase --autostash` stashes and restores into a
                # conflict. They used to run here, unlocked, and be
                # committed by `_commit_run`'s separate lock later; the
                # window between the two was the hazard. Both model
                # invocations stay OUTSIDE the lock — they take minutes
                # and write only their own new (untracked) files.
                #
                # The lock is taken here rather than inside `_commit_run`
                # so the section is CONTINUOUS; `_commit_run` takes it
                # again re-entrantly, which is why it can still be called
                # on its own (the miner's and the tests' path).
                result = _harvest(home, written, roster, refuse=refuse)  # S8
                result.eligible = len(batch)
                result.leftovers = leftovers
                result.suspects = suspects
                result.repair_attempted = repair_attempted
                result.repair_eligible = len(repair_eligible_paths)
                if repair_attempted:
                    cleared = sum(
                        1
                        for p in repair_eligible_paths
                        if p.stem in result.proposed
                    )
                    result.repair_cleared = cleared
                    log(
                        f"run: repair round: {cleared} of "
                        f"{len(repair_eligible_paths)} refusals cleared"
                    )

                # Step 6 (audit fix), WIDENED (§3.12, D7): success is
                # decided on what LANDED valid PLUS what Rule-F left
                # foreign — a foreign file is fresh by the shipped
                # predicate (the queue moved), so a run whose only
                # outcome was a fresh valid proposal must not report
                # failure. `foreign_left` members stay OUT of
                # proposed/valid_landed/touched regardless — the worker
                # never claims authorship of bytes it did not write.
                if result.valid_landed + len(result.foreign_left):
                    result.status = "ok"
                    _p("worker.last-run").touch()
                    # Merge proposals COUNT as proposals for the event +
                    # notification (a merge card is a reviewable
                    # proposal); cluster ids ride record_ids so the
                    # deep-link contract has a target.
                    ids = result.proposed + result.merge_proposed
                    n = len(result.proposed) + len(result.merge_proposed)
                    aggregate = {"pending": total_pending, "buckets": per_bucket}
                    if ids:
                        append_event("proposals", ids, aggregate)
                        _notify_with_ids(
                            render_notification(
                                n,
                                sorted(result.buckets) or ["(unknown)"],
                                total_pending,
                                len(per_bucket),
                            ),
                            ids,
                        )
                    log(
                        f"run: ok — {len(result.proposed)} proposal(s), "
                        f"{len(result.merge_proposed)} merge, "
                        f"{len(result.invalid_deleted)} invalid deleted"
                    )
                else:
                    result.status = "failed"
                    log(
                        f"run: FAILED — {len(batch)} eligible, 0 valid "
                        "proposals (last-run not touched; staleness alarm "
                        "is the detector)"
                    )

            # H-5: the producer commits its own writes (proposals +
            # sweeps) — done inside `_harvest`'s lock above, because the
            # sweeps are mutations and the lock must precede them (round
            # 7). The PUSH is what is left to do, and it belongs out here:
            # outside the lock, because it touches no index.
            if result.committed:
                _push_run(home, no_push=no_push)

            result.escalated = _maybe_escalate(home, total_pending, per_bucket)

            # Worker runs are kick-chained from teach/import — still the
            # human-triggered class (11 §4.2): flush the spool.
            # push=not no_push_requested() (BLOCKER 3): flush defaults to
            # push=True, so a --no-push teach's own kicked worker published
            # the whole branch here — including the record the user asked to
            # keep local. The flush still COMMITS (H-5); only the push waits.
            try:
                telemetry.flush(home, push=not no_push)
            except telemetry.TelemetryError as exc:
                log(f"run: telemetry flush refused ({exc})")
        finally:
            hold.release()
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    # §3.10 — the backoff counter, updated at the run-end site (BD7: NOT
    # inside `_open_window`, which `kick` shares — a human kick must
    # never be refused by this counter).
    if result.status == "failed":
        _increment_failure_count()
    elif result.status in ("ok", "idle"):
        _reset_failure_count()

    # Follow-on OUTSIDE the run lock and through the spawn lock (audit
    # 2026-07-15: the old direct spawn bypassed kick's serialization and
    # could double-spawn against a mid-run kick).
    #
    # THREE independent gates, each alone sufficient to suppress (incident
    # 2026-08-09: a real detached `worker run --coalesce` chain respawned
    # for 39.3h, fd-exhausting the user-scope dbus-broker). Order is
    # deliberate:
    #
    #   1. the failure-cap suppression (existing, U-repair §3.10) — its
    #      own log line is a live-mode product signal that must fire
    #      regardless of anything below, so it is checked first,
    #      unconditionally;
    #   2. D2 — PROGRESS (live AND sandboxed; NOT sandbox-specific): an
    #      "ok"/"idle" status only proves a proposal FILE was written,
    #      never that the ELIGIBLE SET shrank. A batch that keeps
    #      reporting "ok" while leaving the same records un-landed (e.g.
    #      a fixture — or a bug — that rewrites the same proposal every
    #      invocation) chains forever, structurally invisible to the
    #      failure cap above (which only counts "failed" runs). Skipped
    #      for `status == "failed"`: that path is the failure cap's own
    #      job, unchanged, and a failed run's eligible set is expected
    #      not to shrink on its first (sub-cap) attempts;
    #   3. `_autokick_disabled()` — the sandboxed/test kill switch,
    #      checked LAST, only once progress and the cap both say a real
    #      successor would be legitimate.
    #
    # `_spawn_window` carries its own belt-and-braces absolute
    # chain-depth ceiling (`SELF_LEARN_FOLLOWON_DEPTH`) threaded through
    # the child's env — a backstop that holds even if the reasoning above
    # is ever wrong.
    if _p("worker.dirty").is_file():
        failures = _read_failure_count()
        eligible_before = len(batch) + leftovers
        if failures >= FOLLOWON_FAILURE_CAP:
            log(
                "run: follow-on suppressed after "
                f"{failures} consecutive failed runs — "
                "`self-learn worker kick` retries"
            )
            result.followon = False
        elif result.status != "failed" and not _followon_progress(
            home, eligible_before
        ):
            log(
                "run: follow-on suppressed — no progress on the eligible "
                f"set ({eligible_before} still eligible after an "
                f"'{result.status}' run); `self-learn worker kick` retries"
            )
            result.followon = False
        elif _autokick_disabled():
            log("run: follow-on window: disabled")
            result.followon = False
        else:
            # The follow-on inherits THIS run's no-push policy (BLOCKER
            # 3): otherwise the muzzled worker's own successor would
            # push instead.
            outcome = _open_window(home, no_push=no_push)
            log(f"run: follow-on window: {outcome}")
            result.followon = outcome == "spawned"
    return result
