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
from typing import Any, cast

from . import domain, invocation, sentinel, settings, telemetry
from .primitives import chrono, truncate
from .compilers import BEGIN_MARKER, END_MARKER
from .corroborate import MISMATCH, NO_EVIDENCE, RunEvidence
from .hosts import Hosts, HostsError, ancestors_of, load_hosts, skill_dir_for, unregistered_ancestor_dirs
from .ledger import discover_buckets, resolve_home
from .ledger_ops import bucket_project_path
from .scan import scan as secret_scan
from .ledger_ops import (
    ROSTER_UNAVAILABLE,
    TRACE_FS_VERDICTS,
    ProposalError,
    _dump_yaml,
    find_record_path,
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
    "ANCESTOR_DEPTH_CAP",
    "CANDIDATE_CAP",
    "CANDIDATE_SCORE_FLOOR",
    "CANON_BYTES_PER_FILE",
    "CANON_BYTES_PER_RECORD",
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
    "cache_dir",
    "canon_blocks",
    "cluster_candidates",
    "compose_batch_prompt",
    "compose_record_block",
    "compose_single_prompt",
    "invoke_timeout_secs",
    "kick",
    "package_skill_refs",
    "pair_similarity",
    "path_roster",
    "repair_timeout_secs",
    "run",
    "skill_roster",
    "stage_dir",
    "stage_permission_rules",
    "stage_reset",
    "staged_paths",
    "write_permission_rules",
]

DEFAULT_COALESCE_SECS = 600
DEFAULT_WORKER_MODEL = "claude-sonnet-5"
BATCH_CAP = 15
#: U-ancestry §5.2 BR-3 — the already-canon scan's byte budget. Chosen
#: from §3.4's measured surfaces: 32768 covers 8 of 9 hosts' whole
#: CLAUDE.md untouched (`~/.config` truncates from 72,467 B); the ancestor
#: depth cap's live max is 1; the per-record total's worst case rises from
#: 24,328 B (today's excerpt) to 65,536 B.
CANON_BYTES_PER_FILE = 32768
ANCESTOR_DEPTH_CAP = 2
CANON_BYTES_PER_RECORD = 65536
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


def pair_similarity(
    tokens_a: set, tokens_b: set, doc_freq: dict[str, int], n_docs: int
) -> float:
    """IDF-cosine similarity between two token sets over a shared corpus
    (§4.3.2, U-cap) — factored out of :func:`cluster_candidates`'s former
    ``idf``/``sum_idf`` closures so there is exactly ONE IDF-cosine
    definition in the codebase; the context-budget crowding signal
    (``report.py``) calls this directly rather than reimplementing it.

    ``doc_freq``/``n_docs`` describe the CORPUS the IDF weights are drawn
    from — deliberately a parameter, never re-derived here, so a caller
    can score a pair against a corpus wider than its own two members (a
    2-document corpus makes every shared token's ``idf`` collapse to
    ``log(1) == 0``, the degeneracy §4.3.2 documents). Returns ``0.0``
    when the two sets share no tokens, or when either side's IDF mass is
    zero (nothing in the corpus to weight by) — never a ``ZeroDivisionError``."""

    def idf(term: str) -> float:
        d = doc_freq.get(term, 0)
        if d <= 0 or n_docs <= 0:
            return 0.0
        return math.log(n_docs / d)

    shared = tokens_a & tokens_b
    if not shared:
        return 0.0
    a_sum = sum(idf(t) for t in tokens_a)
    b_sum = sum(idf(t) for t in tokens_b)
    denom = math.sqrt(a_sum * b_sum) if a_sum > 0 and b_sum > 0 else 0.0
    if denom <= 0:
        return 0.0
    return sum(idf(t) for t in shared) / denom


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

    result: dict[str, list] = {}
    for entry in batch:
        rid = entry.record.id
        a_title = record_title(entry.record)
        a_toks = _tokens(a_title)
        scored: list[tuple[float, str, str, str]] = []
        for other_id, other_status, other_title, b_toks in pool:
            if other_id == rid:
                continue
            if not (a_toks & b_toks):
                continue
            score = pair_similarity(a_toks, b_toks, doc_freq, n)
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


def compose_record_block(
    home: Path,
    entry,
    *,
    roster: Roster,
    candidates: list,
    bytes_sink: list[int] | None = None,
    log_bytes: bool = True,
) -> str:
    """The ONE per-record block, shared verbatim by both prompt forms
    (§3.1/A11): record text (``Record.to_text()``, never
    ``entry.path.read_text()`` — §3.5, the two differ whenever ruamel
    re-renders frontmatter, and containment checks the FORMER), the T-N
    candidate block, the absolute-path roster, and the canon blocks
    (U-ancestry §6.2 — own host, registered ancestors, references).

    ``bytes_sink`` is an OPTIONAL side-channel accumulator (BR-2): when a
    caller passes a list, this record's realised ``canon_bytes`` is
    appended to it, so :func:`compose_batch_prompt` can log the batch
    total without re-deriving it. Never affects the returned text (A11's
    byte-identity contract is untouched by an unset default).

    ``log_bytes`` passes straight through to :func:`canon_blocks` — see
    its docstring: LG7 forbids the analyst's single-record path from
    ever writing to `worker.log`, so `compose_single_prompt` passes
    False here while `compose_batch_prompt` leaves the True default."""
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
        f"{_canon_excerpt(home, entry, bytes_sink=bytes_sink, log_bytes=log_bytes)}\n"
    )


def cache_dir(home: Path | str | None = None) -> Path:
    """Per-ledger-home cache namespace (doc 13 §6, H-4):
    ``${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(home)[:8]>/`` —
    a future second home (06's team ledger) is a config away. ``home``
    defaults to :func:`ledger.resolve_home` (cheap env read) when
    omitted, so every existing bare call is unchanged (M-P, sprint 1
    audit A14/A13: a caller that already holds an explicit ``home`` can
    now pass it through instead of this namespace silently tracking the
    ambient ``SELF_LEARN_HOME`` even when it differs from that home).

    Migration shim from the OLD un-namespaced path
    (``…/claude-skills/self-learn`` — the name embeds the host the cache
    no longer belongs to): see :func:`_migrate_cache`.

    M-P fold r1 (F3): an explicit ``home`` is ``.expanduser()``'d before
    hashing, the same normalization :func:`ledger.resolve_home` already
    applies to the ambient path -- otherwise ``cache_dir(Path("~/x"))``
    and ``cache_dir(Path.home() / "x")`` (the SAME directory) hashed to
    two different namespaces.

    M-P fold r1 (F2), restated in fold r2 (M1: names/call-shapes, not
    line numbers, which rot; N2: the actual rule, not the old
    approximation of it) -- six call sites stay DELIBERATELY bare (call
    this with no ``home``): :func:`kick`'s and :func:`run`'s own
    ``cache_dir().mkdir(parents=True, exist_ok=True)`` prologues, and
    four operator-facing message strings shaped
    ``f"... see the event log in {cache_dir()}"`` (two inside
    :func:`kick`/:func:`run` in this module, two inside
    :mod:`miner`'s ``_invoke_reader``).

    The rule is NOT "an intra-function split is worse than
    consistent-bare" -- fold r1's F1 fix deliberately makes exactly that
    split inside :func:`miner.maybe_kick` (its heartbeat check now
    threads `home` while the SAME function's ``miner_dir()``-backed
    staleness/lock checks stay bare), and that fix is correct. The real
    rule: pair each READ with its WRITER -- thread `home` wherever the
    writer that produced the file already did, and leave a function
    uniformly bare only when its OWN file namespace is itself bare by
    design. Applied here: :func:`_p` is itself confirmed bare (no
    ``home`` parameter at all) and is the writer for every
    lock/log/stage/window file `kick`/`run` touch -- threading
    ``cache_dir`` alone at the prologue would pair that ONE read with a
    DIFFERENT (home-namespaced) writer than every ``_p(...)`` call
    beside it, which already agrees with ITS bare writer. The four
    message strings must name the directory :mod:`invocation_sdk.events`
    actually wrote its event log to, and that module's own event-log
    path helpers are themselves confirmed bare, by design (see their
    docstrings) -- so threading `home` into just the STRING would point
    the operator at a directory the event log was never actually written
    under: the same pair-with-the-writer rule, applied the other way."""
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache).expanduser() if cache else Path("~/.cache").expanduser()
    resolved_home = Path(home).expanduser() if home is not None else resolve_home()
    digest = hashlib.sha256(str(resolved_home).encode("utf-8")).hexdigest()[:8]
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
    return chrono.now_iso()


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
    """Facade over :func:`self_learn.primitives.truncate.truncate_oldest`
    -- kept as its own name/def (never inlined or renamed):
    ``tests/test_lock_invariant.py`` enumerates ``worker._truncate_oldest``
    by name in its ``NOT_REPO_TRUTH`` exemption table (M-J, plan v2 SS2)."""
    truncate.truncate_oldest(path, cap)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def coalesce_secs(home: Path | str | None = None) -> float:
    """U-settings Phase 1: resolves through the registry's ``worker.
    coalesce_secs`` entry (config.yaml `worker.coalesce_secs` > env >
    :data:`DEFAULT_COALESCE_SECS` -- U-flip 2026-09-01, S-58: config
    wins) rather than reading
    ``SELF_LEARN_COALESCE_SECS`` directly — `home` defaults to
    :func:`resolve_home` so every existing zero-arg call site (this
    module's own :func:`run`, and the tests that call it bare) is
    unaffected."""
    value, _source = settings.resolve_setting(
        home if home is not None else resolve_home(), settings.by_name("worker.coalesce_secs")
    )
    return cast(float, value)


def worker_model() -> str:
    return os.environ.get("SELF_LEARN_WORKER_MODEL") or DEFAULT_WORKER_MODEL


def batch_cap() -> int:
    return BATCH_CAP


def _timeout_secs(env_var: str, default: float) -> float:
    """Env-only reader for :func:`miner.reader_timeout_secs` (§3.9): a
    value <= 0 or unparseable falls back to the default rather than
    being clamped to 0 — a zero coalesce is meaningful (see
    :func:`coalesce_secs`), but a zero ``subprocess.run(timeout=...)``
    expires instantly and would kill every run (E4).

    U-settings Phase 1: :func:`invoke_timeout_secs` and :func:`repair_
    timeout_secs` below no longer call this — they resolve through the
    settings registry, which gives them a config.yaml rung this helper
    does not have. This function stays env-only DELIBERATELY: `miner.
    reader_timeout_secs()` calling through it is a pinned build decision
    (``test_u_fw100.py::test_shares_worker_helper_not_a_reimplementation``
    monkeypatches this exact function) — see `settings.py`'s registry
    comment at ``miner.transcripts_dir`` for why that setting was left
    out of Phase 1's registry rather than reopening it."""
    raw = os.environ.get(env_var)
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return value if value > 0 else float(default)


def invoke_timeout_secs(home: Path | str | None = None) -> float:
    """The batch invocation's timeout (§3.9): resolves through the
    registry's ``worker.invoke_timeout_secs`` entry (config.yaml
    `worker.invoke_timeout_secs` > env > :data:`INVOKE_TIMEOUT_SECS` --
    U-flip 2026-09-01, S-58: config wins). `home`
    defaults to :func:`resolve_home`, so every existing zero-arg call
    site is unaffected."""
    value, _source = settings.resolve_setting(
        home if home is not None else resolve_home(), settings.by_name("worker.invoke_timeout_secs")
    )
    return cast(float, value)


def repair_timeout_secs(home: Path | str | None = None) -> float:
    """The repair round's timeout (§3.9): resolves through the
    registry's ``worker.repair_timeout_secs`` entry (config.yaml
    `worker.repair_timeout_secs` > env > :data:`REPAIR_TIMEOUT_SECS` --
    U-flip 2026-09-01, S-58: config wins). `home`
    defaults to :func:`resolve_home`, so every existing zero-arg call
    site is unaffected."""
    value, _source = settings.resolve_setting(
        home if home is not None else resolve_home(), settings.by_name("worker.repair_timeout_secs")
    )
    return cast(float, value)


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
    process writes canon).

    U-attrib (GR-c): kept, unchanged and exported — used only by the
    ``SELF_LEARN_STAGE=0`` fallback (§3.7). The batch invocation's own
    grant is :func:`stage_permission_rules` now; this function is what
    the fallback reverts to."""
    home = Path(home)
    return [
        f"Edit(/{home}/skills/**/proposals/**)",
        f"Edit(/{home}/projects/**/proposals/**)",
        f"Edit(/{home}/user/proposals/**)",
    ]


# ---------------------------------------------- U-attrib: Stage-1 (§3.1)
#
# The exclusive namespace: only the model writes it (via the batch/repair
# invocations' Write grant), only the worker reads it. Flat, cleared at
# the top of every run, per-ledger-home (it lives under cache_dir()).


def stage_dir() -> Path:
    """``ST-a`` — the stage: ``cache_dir()/worker.stage/``. Outside every
    git repo, per-ledger-home, never committed, never read by any surface
    but the worker."""
    return _p("worker.stage")


def stage_reset(home: Path) -> None:
    """``ST-c`` — cleared at the top of every run: remove and recreate
    empty. Nothing persists between runs; a crashed run's litter is
    removed by the NEXT run's clear, not swept later. ``home`` is unused
    directly (:func:`cache_dir` resolves the ledger home itself, doc 13
    H-4) — kept as a parameter to match the spec's call shape and this
    module's own convention (e.g. :func:`stage_permission_rules`, below —
    FW-117 deleted the other example this docstring used to cite,
    :func:`write_repair_settings_file`, a dead write nothing read)."""
    del home
    path = stage_dir()
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def staged_paths() -> list[Path]:
    """``ST-b`` — the stage is flat: every file directly in it, sorted.
    This is the model's output BY CONSTRUCTION — never a recursive walk
    (a staged file in a subdirectory is litter, ``ST-f``)."""
    stage = stage_dir()
    if not stage.is_dir():
        return []
    return sorted(p for p in stage.iterdir() if p.is_file())


def stage_permission_rules(home: Path) -> list[str]:
    """``GR-b`` — the batch invocation's allow list is EXACTLY this one
    rule. ``home`` is unused (same reasoning as :func:`stage_reset`) but
    kept for signature symmetry with :func:`write_permission_rules`."""
    del home
    return [f"Edit(/{stage_dir()}/**)"]


def _stage_enabled() -> bool:
    """``SELF_LEARN_STAGE=0`` — the namespace switch (§3.7)."""
    return os.environ.get("SELF_LEARN_STAGE") != "0"


def _enforce_scope() -> bool:
    """``SELF_LEARN_ENFORCE_SCOPE=0`` — the enforcement switch (§3.7):
    omits ``defaultMode`` from both the batch and repair rounds'
    containment (``invocation.containment_for(..., enforce=...)``), i.e.
    the exact shape the shipped code wrote before ``GR-a``'s hotfix, back
    when both rounds still rendered an on-disk settings file (batch's,
    ``worker.write_settings_file``, deleted by U-cleanup-B §8.1; repair's,
    ``worker.write_repair_settings_file``, deleted by FW-117 — neither
    round writes a settings file to disk any more, the charter is the
    sole authority for both, `A-2`)."""
    return os.environ.get("SELF_LEARN_ENFORCE_SCOPE") != "0"


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


def _autokick_disabled(home: Path | str | None = None) -> bool:
    """True iff the ``worker.autokick`` setting resolves to `False`
    (config.yaml `worker.autokick: false` — U-flip 2026-09-01, S-58 —
    or env `SELF_LEARN_WORKER_AUTOKICK=0`) — the shared kill-switch for
    ANY code path that would auto-spawn a detached ``worker run
    --coalesce`` window, not just an explicit :func:`kick`. Resolved
    fresh on every call, never cached (:func:`settings.resolve_setting`'s
    own discipline) — a test's `monkeypatch.setenv`/`delenv` takes
    effect immediately, as does :func:`serve._worker_autokick_disabled`'s
    mid-process assertion, but the LATTER no longer rides the plain env
    rung: under config-wins a bare env write can be outranked by a
    saved `worker.autokick: true`, so that mechanism was moved to
    :func:`settings.override` (review Blocker, 2026-09-01) — a THIRD
    rung this function's own :func:`settings.resolve_setting` checks
    ABOVE config.yaml, precisely so a running process's own assertion
    about itself can never be defeated by a saved policy.

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
    value, _source = settings.resolve_setting(
        home if home is not None else resolve_home(), settings.by_name("worker.autokick")
    )
    return not value


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


def _followon_depth() -> int:
    """THIS process's own follow-on chain depth (0 if absent — an
    explicit `kick()` from a fresh human/teach/import/miner shell never
    carries the var). Split out (fold NIT 2) so :func:`_ceiling_refused`
    reads the exact same value :func:`_open_window`'s pre-spawn peek and
    :func:`_spawn_window`'s own internal check both need."""
    try:
        return int(os.environ.get(FOLLOWON_DEPTH_ENV, "0"))
    except ValueError:
        return 0


def _ceiling_refused() -> bool:
    """D3's belt-and-braces chain-depth ceiling (:data:`FOLLOWON_DEPTH_
    CEILING`), split out of `_spawn_window` (fold NIT 2, audit
    2026-09-02) so `_open_window` can check it BEFORE ever writing the
    "spawning" marker: writing the marker ahead of a refusal that was
    already certain served no purpose and opened a needless gap — a
    SIGKILL landing between that write and `_spawn_window`'s own
    (redundant) ceiling check would otherwise strand an un-clearable
    marker with no child anywhere, reclaimed only after
    :data:`SPAWN_MARKER_DEADLINE_SECS`.
    `_spawn_window` still calls this itself too (below), so a call
    straight to `_spawn_window` — armor-pinned
    `test_d3_depth_ceiling_refuses_a_real_spawn` calls it directly, in
    isolation, unedited — keeps refusing before `Popen`, logged, exactly
    as before this split."""
    depth = _followon_depth()
    if depth >= FOLLOWON_DEPTH_CEILING:
        log(
            f"run: follow-on chain-depth ceiling reached ({depth} >= "
            f"{FOLLOWON_DEPTH_CEILING}) — refusing to spawn a successor; "
            "`self-learn worker kick` retries"
        )
        return True
    return False


def _spawn_window(home: Path, *, no_push: bool = False) -> int:
    """setsid-spawn a coalescing run; returns the child pid, or the
    negative sentinel ``-1`` iff D3's chain-depth ceiling refuses to
    spawn (see :data:`FOLLOWON_DEPTH_CEILING`, :func:`_ceiling_refused`).
    Split out so tests can monkeypatch spawning without faking flocks.

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
    depth = _followon_depth()
    if _ceiling_refused():
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


#: C17 (audit 2026-09-02): `_open_window` used to spawn the child (below)
#: and write its pid to `worker.window` only afterwards — a crash (or the
#: whole process getting SIGKILLed) in that gap left no window on disk at
#: all, so a later kick saw nothing live and spawned a SECOND worker
#: alongside the detached first one. This sentinel is written into
#: `worker.window` durably, BEFORE the spawn, so a crash in the gap still
#: leaves proof on disk that an attempt was underway; a later kick reads
#: a fresh one as "absorbed-race" rather than "nothing is running".
_SPAWN_MARKER = "spawning"

#: How long a "spawning" marker may sit before :func:`_spawn_marker_
#: stale` reclaims it. Fold r3 (audit 2026-09-02 gate r2 MINOR 1):
#: earlier revisions of this comment said the child clears
#: `worker.window` only after ITS OWN `coalesce_secs(home)` sleep ends
#: and it takes `worker.lock` — true before fold r2, false since:
#: `run()` now calls `_register_running_pid()` (proven ordered ahead of
#: both by `test_run_registers_the_pid_before_the_coalesce_sleep_and_
#: the_lock`) as one of its first acts, durably rewriting `worker.window`
#: with the child's own real pid BEFORE either the sleep or the lock —
#: so a live, coalescing child no longer holds a bare marker for the
#: length of its own sleep; it holds one, at most, for the time between
#: `Popen` returning (parent side) and this registration write landing
#: (child side).
#:
#: What this deadline actually bounds now: a crash strictly between
#: `Popen` returning and the child's registration write — interpreter
#: start, importing `self_learn.cli` (the whole CLI surface), and one
#: `_write_window_durable` call. That is normally well under a second;
#: 30s is a deliberately generous multiple of it (a cold page cache, a
#: loaded/throttled host, a slow disk under `_write_window_durable`'s
#: fsync calls) while staying startup-scale, not the ~600s-plus a
#: `coalesce_secs(home)`-derived deadline (the pre-fold-r3 formula) would
#: have allowed for the same crash window. `coalesce_secs(home)` is
#: dropped from the formula entirely: the child can no longer
#: legitimately hold a bare marker for anything coalesce-scale, so
#: adding it back would only widen the double-spawn window this deadline
#: exists to close, for no live case it protects.
SPAWN_MARKER_DEADLINE_SECS = 30.0


def _write_window_durable(window: Path, text: str) -> None:
    """Temp + rename + fsync (C17). `Path.write_text` alone is neither
    atomic (a reader mid-write could see a partial file) nor durable (the
    bytes can still be sitting in the page cache, not on disk, when a
    crash hits) — exactly the two properties the spawn marker needs,
    since its whole job is to survive the crash a plain write would not.
    `os.replace` gives the atomicity; the two `fsync` calls (the temp
    file's data, then the directory entry the rename produced) give the
    durability.

    Fold NIT 1: any failure between creating the temp file and the
    rename (disk full mid-write, a permission error) unlinks the temp
    file before re-raising — a failed write must not leave
    ``.worker.window.<pid>.tmp`` litter behind for a later run to trip
    over."""
    window.parent.mkdir(parents=True, exist_ok=True)
    tmp = window.parent / f".{window.name}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, window)  # same filesystem — atomic
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(window.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)  # the rename itself, durable too
    finally:
        os.close(dir_fd)


def _spawn_marker_stale(window: Path) -> bool:
    """A marker older than :data:`SPAWN_MARKER_DEADLINE_SECS` is an
    abandoned attempt, not a live one — reclaimable by the next kick.
    Missing entirely (raced away, or never existed) counts as stale too:
    there is nothing left to absorb against.

    Fold r3: no longer takes `home` — the deadline used to be
    `coalesce_secs(home) + margin` (see :data:`SPAWN_MARKER_DEADLINE_
    SECS`'s comment for why that formula is gone, not just shrunk), so
    `home` was the only reason this function needed it.

    Fold NIT 3 (residual, disclosed): age is `mtime`-based, so a
    backwards wall-clock step makes a marker un-stale-able for the size
    of the step. Fold r2's MINOR 1 fix (:func:`_register_running_pid`, a
    spawned child durably rewriting `worker.window` with its own pid
    before its coalesce sleep and before `worker.lock`) bounds how much
    this can matter in practice: once a child has registered, THIS
    function is never consulted for it again (the marker string is gone,
    replaced by a real pid `_pid_alive` judges directly, clock-
    independent) — the exposure a backwards step can extend is only the
    child-startup window a crash-before-registration marker sits in."""
    try:
        age = time.time() - window.stat().st_mtime
    except OSError:
        return True
    return age >= SPAWN_MARKER_DEADLINE_SECS


def _register_running_pid() -> None:
    """Fold r2 MINOR 1 (audit 2026-09-02 gate, unblocked by the
    coordinator once `tests/test_lock_invariant.py`'s `NOT_REPO_TRUTH`
    carried this function's own entry): called from :func:`run`,
    preceded only by argument normalization (`home = Path(home)`,
    resolving `no_push`) and `cache_dir().mkdir(...)` — which this
    function's own write depends on, `worker.window` living inside that
    directory — and BEFORE anything else: the coalesce sleep and
    `worker.lock` both come strictly after (proven ordered by
    `test_run_registers_the_pid_before_the_coalesce_sleep_and_the_lock`
    in `tests/test_worker_spawn_handshake.py`, fold r3). Durably
    (:func:`_write_window_durable`) overwrites
    `worker.window` with THIS process's own, now-real, pid, replacing
    whatever was there (typically the parent's "spawning" marker,
    written by `_open_window` just before `_spawn_window`'s `Popen`
    launched this very process).

    Bounds the marker's real remaining exposure to child STARTUP
    (interpreter + import time — milliseconds), not the full
    `coalesce_secs(home)` sleep that follows: a marker is otherwise only
    judged by `_spawn_marker_stale`'s deadline heuristic, and a kick
    landing after that deadline but before this registration point would
    reclaim the window and spawn a SECOND worker while the first is
    still alive and merely asleep (serialized by `worker.lock` once both
    reach it, but still a second real process — C17's double-spawn in a
    new shape). Once THIS write lands, a later kick sees a genuine,
    `_pid_alive`-checkable pid instead — correct for the process's ENTIRE
    remaining life, not just until a fixed deadline.

    Cache-only (`worker.window`, XDG cache, never a repo path) — see the
    `NOT_REPO_TRUTH` entry naming this function specifically (not the
    path-parametric `_write_window_durable`, which would exempt any
    future caller unscrutinized).

    Fold r4 (integration find, gate on the merged tree): registration is
    BEST-EFFORT — an `OSError` out of `_write_window_durable` (disk
    full, a permission error, or — measured live — the armor-pinned
    `test_attrib.py::test_in8_interrupted_install_is_recovered_not_
    stalled_forever` part (e) monkeypatching `os.replace` — globally at
    the time, scoped to the install copy on 2026-09-04 — to simulate a
    crash mid-install-copy, which this function's own write shared) must
    NEVER abort the whole
    `run()`. If the child never registers, the window keeps whatever the
    parent wrote, exactly as before fold r2 (`fb34978`): in the common
    case the parent has already rewritten the marker with the child's
    real pid microseconds after `Popen`, so a later kick reads a live
    pid and reports `absorbed-window` — no deadline exposure at all;
    only if the parent died between its marker write and that rewrite
    does the "spawning" marker stand (fresh → `absorbed-race`, older
    than `SPAWN_MARKER_DEADLINE_SECS` → reclaimed); and once this child
    reaches `worker.lock` it clears the window itself. A crash mid-write
    leaves no temp-file litter (`_write_window_durable`'s own
    `except BaseException: tmp.unlink(...); raise`). Not a new failure
    mode. Logged, not silent, so the skip is visible in `worker.log`."""
    try:
        _write_window_durable(_p("worker.window"), str(os.getpid()))
    except OSError as exc:
        log(
            f"pid registration skipped: {exc}; the window keeps what the parent "
            "wrote (a real pid, or a marker the deadline reclaims)"
        )


def _open_window(home: Path, *, no_push: bool = False) -> str:
    """Lock-guarded window opener, shared by :func:`kick` and the
    run-end follow-on (audit 2026-07-15: the follow-on previously
    bypassed the spawn lock and could double-spawn against a mid-run
    kick). Returns ``spawned`` | ``absorbed-window`` | ``absorbed-race``
    | ``depth-limited`` (D3, 2026-08-09: `_spawn_window` refused under
    the chain-depth ceiling — nothing was actually spawned, so no pid is
    recorded to `worker.window`).

    C17: before ever calling :func:`_spawn_window`, `worker.window` is
    durably (:func:`_write_window_durable`) set to :data:`_SPAWN_MARKER`
    — after EVERY refusal check this function makes (the live-window
    absorption check just above, AND — fold NIT 2 — the D3 chain-depth
    ceiling via :func:`_ceiling_refused`, checked here too so a certain
    refusal never gets a marker written ahead of it), and before the
    spawn. A non-spawn outcome (depth-limited, or fold MAJOR 1: any
    exception out of `_spawn_window` itself — a failed `Popen`, ENOSPC on
    its log open, a missing interpreter) removes the marker again and
    (for the exception case) re-raises; a real spawn rewrites it with the
    pid, same as before. A later kick that finds a fresh marker (no
    crash, or a crash too recent to trust) reports ``absorbed-race`` —
    the same vocabulary as a held flock, since both mean "someone else's
    spawn already covers this kick" — and reclaims a stale one
    (:func:`_spawn_marker_stale`) instead.

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
                raw = window.read_text(encoding="utf-8").strip()
                if raw == _SPAWN_MARKER:
                    if not _spawn_marker_stale(window):
                        return "absorbed-race"  # a spawn is (or just was) in flight
                    # else: stale — an abandoned attempt; reclaim below.
                else:
                    try:
                        pid = int(raw)
                    except ValueError:
                        pid = -1
                    if pid > 0 and _pid_alive(pid):
                        return "absorbed-window"
            if _ceiling_refused():
                # fold NIT 2: certain refusal, already logged above — the
                # marker must never be written ahead of a refusal we
                # already know is coming.
                return "depth-limited"
            _write_window_durable(window, _SPAWN_MARKER)  # C17: before the spawn
            try:
                pid = _spawn_window(home, no_push=no_push)
            except BaseException:
                # fold MAJOR 1: an exception out of _spawn_window (a
                # failed Popen, ENOSPC on its log open, a missing
                # interpreter) is a non-spawn outcome exactly like a
                # ceiling refusal — nothing was actually spawned, so the
                # marker must not survive it either, or every later kick
                # absorbs (SPAWN_MARKER_DEADLINE_SECS) against a child
                # that never existed.
                window.unlink(missing_ok=True)
                raise
            if pid <= 0:
                window.unlink(missing_ok=True)  # non-spawn outcome — no marker left
                return "depth-limited"  # already logged by _spawn_window's own (redundant) check
            _write_window_durable(window, str(pid))
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
    if _autokick_disabled(home):
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
    #: U-attrib Obs-2 (§3.8) — additive only, no existing field changes
    #: type or meaning (`touched`'s TYPE discipline is a structural fix,
    #: `_stage_discard`, not a meaning change).
    staged_written: int = 0  # size of S3's staged1 (round 1 alone)
    #: Destination NAMES `Install-1` declined this run — never installed,
    #: never stamped, never deleted, never counted toward
    #: `proposed`/`valid_landed`/`touched`.
    not_installed: list[str] = field(default_factory=list)
    foreign_seen: int = 0  # size of S7's `foreign` set


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
    quoting the message does not re-list an undone rejection).

    M-G: a LOCAL, read-only git call — bounded like every other one
    (``gitops.GIT_LOCAL_TIMEOUT``) via the shared primitive instead of a
    bare, unbounded ``subprocess.run``. A wedged git degrades this digest
    the same way a real failure already does (``returncode != 0``): the
    reader gets no negative exemplars this run, not a hung worker."""
    from . import gitops
    from .primitives import procs

    try:
        proc = procs.run_bounded(
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
            timeout=gitops.GIT_LOCAL_TIMEOUT,
        )
    except procs.BoundedTimeout:
        return "(no rejected-proposal history available)"
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


#: U-ancestry §6.2 item 2 — the label an ancestor's block carries.
_ANCESTOR_LABEL = "(inherited — loads in every session under this host)"
#: U-ancestry §6.2 item 3 — the label every references/ block carries,
#: verbatim (SCAN3). A references file is on the DEMAND shelf, reached by
#: a pointer, never loaded — so a hit there is never eligible for
#: `g0.canon` (CARD4).
_REFERENCE_LABEL = "(captured, NOT loaded — pointer-reached; not eligible for g0.canon)"

#: U-ancestry §6.2 clause (1) — the managed-marker window each side, the
#: SAME ±20-line convention `canon_excerpt` used for its own window
#: (superseded by SCAN1's whole-file read; the window survives ONLY as
#: the always-retained reservation inside the over-cap truncation path —
#: SCAN8, the re-homed u-marker criterion B).
_MARKER_WINDOW_LINES = 20


def _locate_markers(lines: list[str]) -> tuple[int | None, int | None]:
    """The imported-marker search (u-marker §2's import rule, unchanged):
    the exact `BEGIN_MARKER`/`END_MARKER` strings the compiler writes,
    matched CASE-SENSITIVELY — a case-variant the compiler never wrote is
    not a managed region (SCAN8)."""
    begin = next((i for i, ln in enumerate(lines) if BEGIN_MARKER in ln), None)
    end = next((i for i, ln in enumerate(lines) if END_MARKER in ln), None)
    return begin, end


def _retain_ordered(text: str, cap: int) -> tuple[str, int]:
    """U-ancestry §6.2's ORDERED truncation priority for one file's whole
    text, applied only when it exceeds `cap` bytes: (1) the managed
    region ± `_MARKER_WINDOW_LINES` lines, located case-sensitively and
    RESERVED FIRST — always retained, whatever its offset in the file;
    (2) head fill; (3) tail fill, their budgets computed from whatever
    the reservation leaves. When the markers cannot be located, (1) is
    empty and the block is head-and-tail fill only, marked as such.
    Every dropped span is marked in the returned text — a truncated block
    never silently looks whole.

    Returns ``(retained_text, dropped_bytes)``; ``dropped_bytes == 0``
    and ``retained_text == text`` when the file is already under the
    cap (SCAN1: the whole file, unmodified)."""
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text, 0

    lines = text.splitlines()
    begin_idx, end_idx = _locate_markers(lines)
    m_lo: int
    m_hi: int
    if begin_idx is not None and end_idx is not None and end_idx >= begin_idx:
        has_marker = True
        m_lo = max(0, begin_idx - _MARKER_WINDOW_LINES)
        m_hi = min(len(lines), end_idx + _MARKER_WINDOW_LINES + 1)
    else:
        # Dead values: every downstream use of m_lo/m_hi is gated on
        # has_marker being True, so these are never actually read — 0
        # keeps the type plain `int` (never `int | None`) rather than
        # threading an Optional through several more lines/loops below.
        has_marker = False
        m_lo = m_hi = 0

    reserved_lines = lines[m_lo:m_hi] if has_marker else []
    reserved_bytes = len("\n".join(reserved_lines).encode("utf-8"))
    remaining = max(0, cap - reserved_bytes)
    head_budget = remaining // 2
    tail_budget = remaining - head_budget

    head_limit = m_lo if has_marker else len(lines)
    tail_floor = m_hi if has_marker else 0

    head_end = 0
    used = 0
    while head_end < head_limit:
        nxt = used + len(lines[head_end].encode("utf-8")) + 1
        if nxt > head_budget:
            break
        used = nxt
        head_end += 1

    tail_start = len(lines)
    used = 0
    while tail_start > tail_floor and tail_start - 1 >= head_end:
        nxt = used + len(lines[tail_start - 1].encode("utf-8")) + 1
        if nxt > tail_budget:
            break
        used = nxt
        tail_start -= 1

    head_lines = lines[:head_end]
    tail_lines = lines[tail_start:] if tail_start > head_end else []

    def _span_bytes(lo: int, hi: int) -> int:
        return len("\n".join(lines[lo:hi]).encode("utf-8")) if hi > lo else 0

    gap1_hi = m_lo if has_marker else tail_start
    dropped1 = _span_bytes(head_end, max(head_end, gap1_hi))
    dropped2 = _span_bytes(m_hi, max(m_hi, tail_start)) if has_marker else 0

    out: list[str] = list(head_lines)
    if dropped1 > 0:
        out.append(f"… ({dropped1} B truncated)")
    if has_marker:
        out.extend(reserved_lines)
        if dropped2 > 0:
            out.append(f"… ({dropped2} B truncated)")
    else:
        out.append("(no managed section located in this file — head/tail fill only)")
    out.extend(tail_lines)
    return "\n".join(out), dropped1 + dropped2


def _canon_block(path: Path, *, cap: int, label: str | None) -> tuple[str, int]:
    """One ``### <path> (...)`` block (U-ancestry §6.2): missing/unreadable
    is an explicit sentinel line, never omission (the `path_roster`
    "no slot is ever omitted" discipline); otherwise the whole file, capped
    per :func:`_retain_ordered`. Returns ``(block_text, retained_bytes)`` —
    the byte count BR-2 logs and BR-1 budgets against."""
    if not path.is_file():
        return f"### {path} — target does not exist yet", 0
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return f"### {path} — not valid UTF-8, not read ({exc})", 0
    except OSError as exc:
        return f"### {path} — unreadable, not read ({exc})", 0

    original_bytes = len(text.encode("utf-8"))
    retained_text, dropped = _retain_ordered(text, cap)
    retained_bytes = len(retained_text.encode("utf-8"))
    if dropped:
        header = f"### {path} ({retained_bytes} B, truncated from {original_bytes} B)"
    else:
        header = f"### {path} ({retained_bytes} B)"
    if label:
        header = f"{header} {label}"
    return f"{header}\n{retained_text}", retained_bytes


def canon_blocks(
    home: Path,
    record: Record,
    bucket_dir: Path,
    *,
    bytes_sink: list[int] | None = None,
    log_bytes: bool = True,
) -> str:
    """U-ancestry §6.2 — the analyst's whole canon ingredient for one
    record, replacing the old ``canon_excerpt`` (which returned exactly
    one anonymous marker-window excerpt): a set of LABELLED blocks —

    1. **own host** — the record's own candidate target, WHOLE, capped
       per :data:`CANON_BYTES_PER_FILE` (SCAN1 — this supersedes the old
       ``<200 lines`` / ``markers ±20`` / ``first-60`` three-way branch;
       `u-marker-excerpt-case-spec.md` §3 criterion A's `A3` leg is
       superseded, `A0`/`A1`/`A2` are preserved and re-asserted against
       the whole-file contract). Skill scope → the skills root's
       SKILL.md; project scope → the bucket's meta-recorded host
       CLAUDE.md; user scope → the real user CLAUDE.md — the SAME target
       resolution `canon_excerpt` used.
    2. **ancestors** — project scope only, one block per registered
       ancestor (:func:`self_learn.hosts.ancestors_of`), nearest-first,
       up to :data:`ANCESTOR_DEPTH_CAP`, labelled `inherited` (ANC1/ANC2).
       An unregistered ancestor with a `CLAUDE.md` gets a PATH-ONLY line
       — its bytes are never read (ANC5).
    3. **references** — sorted, capped, labelled `captured, NOT loaded`
       (SCAN2/SCAN3): project → `<host>/references/**/*.md`; skill →
       `<skill_dir>/references/**/*.md`; user → no block at all (S-23).

    Nothing outside `hosts.canon_read_roots`' project family is ever read
    (SCAN4) — no `docs/`, no bare `<host>/*.md`, no `CLAUDE.local.md`.

    BR-1's per-record cap (:data:`CANON_BYTES_PER_RECORD`) drops
    references blocks LAST-FIRST when the total exceeds it; BR-2 logs
    `canon_bytes=<n>` for this record via :func:`log` — a cap that fires
    is a logged fact, never an exception (SCAN5). ``log_bytes`` defaults
    to True (the direct-call and worker-batch shape); the ANALYST'S
    single-record path (`compose_single_prompt`) passes False — LG7
    (`test_lg7_analyst_invocation_never_grows_worker_or_miner_log`, a
    pre-existing pinned invariant) refuses `worker.log`/`miner.log`
    growth from ANY code the analyst surface reaches, and this function
    is shared between that surface and the worker's own.

    The ONE implementation of this rule (FW-48/U-marker-ui, 2026-08-02,
    carried forward by U-ancestry): the review pane
    (``ui/src/self_learn_ui/pane.py``'s ``target_canon_excerpt``) imports
    and delegates to this function rather than re-declaring it (ANC6)."""
    home = Path(home)
    scope = record.scope
    try:
        hosts = load_hosts(home)
    except HostsError:
        hosts = Hosts()

    #: (block_text, retained_bytes, droppable) — `droppable` marks a
    #: references/ block as eligible for BR-1's last-first drop.
    blocks: list[tuple[str, int, bool]] = []

    if scope.startswith("skill:"):
        try:
            skill_dir = skill_dir_for(hosts, scope.partition(":")[2])
        except HostsError:
            if bytes_sink is not None:
                bytes_sink.append(0)
            return "(skill target unresolvable — no registered skills root)"
        text, size = _canon_block(skill_dir / "SKILL.md", cap=CANON_BYTES_PER_FILE, label=None)
        blocks.append((text, size, False))
        for ref in sorted((skill_dir / "references").glob("**/*.md")):
            t, s = _canon_block(ref, cap=CANON_BYTES_PER_FILE, label=_REFERENCE_LABEL)
            blocks.append((t, s, True))
    elif scope == "project":
        host_raw = bucket_project_path(bucket_dir)
        if host_raw is None:
            if bytes_sink is not None:
                bytes_sink.append(0)
            return "(project target unresolvable — bucket has no meta.yaml)"
        host = Path(host_raw)
        text, size = _canon_block(host / "CLAUDE.md", cap=CANON_BYTES_PER_FILE, label=None)
        blocks.append((text, size, False))
        for ancestor in ancestors_of(hosts, host)[:ANCESTOR_DEPTH_CAP]:
            t, s = _canon_block(
                ancestor / "CLAUDE.md", cap=CANON_BYTES_PER_FILE, label=_ANCESTOR_LABEL
            )
            blocks.append((t, s, False))
        for unreg in unregistered_ancestor_dirs(hosts, host):
            blocks.append(
                (f"### (unregistered ancestor with a CLAUDE.md: {unreg}) — not read", 0, False)
            )
        for ref in sorted((host / "references").glob("**/*.md")):
            t, s = _canon_block(ref, cap=CANON_BYTES_PER_FILE, label=_REFERENCE_LABEL)
            blocks.append((t, s, True))
    else:  # user — no references block at all (S-23: no user references dir)
        target = Path("~/.claude/CLAUDE.md").expanduser()
        text, size = _canon_block(target, cap=CANON_BYTES_PER_FILE, label=None)
        blocks.append((text, size, False))

    # BR-1: per-record byte budget. Drop droppable (references) blocks
    # LAST-FIRST until the total fits, or nothing droppable is left —
    # a cap that fires is LOGGED (BR-2 below), never enforced by raising.
    total = sum(size for _, size, _ in blocks)
    dropped_bytes = 0
    if total > CANON_BYTES_PER_RECORD:
        kept = list(blocks)
        i = len(kept) - 1
        while total > CANON_BYTES_PER_RECORD and i >= 0:
            _, size, droppable = kept[i]
            if droppable:
                dropped_bytes += size
                total -= size
                del kept[i]
            i -= 1
        blocks = kept

    canon_bytes = sum(size for _, size, _ in blocks)
    if bytes_sink is not None:
        bytes_sink.append(canon_bytes)
    if log_bytes:
        log(
            f"canon_bytes record={record.id} scope={scope} bytes={canon_bytes} "
            f"dropped_record_cap={dropped_bytes}"
        )
    return "\n\n".join(text for text, _, _ in blocks)


def _canon_excerpt(
    home: Path, entry, *, bytes_sink: list[int] | None = None, log_bytes: bool = True
) -> str:
    """``compose_record_block``'s own call shape: a ``queue()``-yielded
    ``QueueEntry`` (``.record``/``.bucket_dir``), not a bare
    :class:`~self_learn.records.Record`. Thin wrapper around
    :func:`canon_blocks` — kept so this module's existing call site and
    test suite (``test_worker.py``) need no signature change."""
    return canon_blocks(
        home, entry.record, entry.bucket_dir, bytes_sink=bytes_sink, log_bytes=log_bytes
    )


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
{stage_dir}/lrn-<id>.yaml. Follow the routing doctrine exactly — including §5 (the
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
{stage_dir}/merge-<8 lowercase hex>.yaml with keys:
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
    batch_canon_bytes: list[int] = []
    blocks = [
        compose_record_block(
            home,
            entry,
            roster=roster,
            candidates=candidates_by_id.get(entry.record.id, []),
            bytes_sink=batch_canon_bytes,
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
        stage_dir=stage_dir(),
    )
    # BR-2: the batch total, logged once per composed batch.
    log(
        f"canon_bytes batch records={len(batch)} "
        f"bytes_total={sum(batch_canon_bytes)}"
    )
    return prompt, roster


def compose_single_prompt(home: Path, entry) -> tuple[str, Roster]:
    """The analyst's one-record prompt form (§3.5): the same
    :func:`compose_record_block` block A11 requires byte-identical to the
    worker's, with the roster inline (the analyst never sees the digest,
    the doctrine, or the card registry here — those ride
    ``--append-system-prompt`` and the doctrine's own §8 pointer).

    Deliberately does NOT log a `canon_bytes` line (LG7, a pre-existing
    pinned invariant: `analyst.analyze` — the only caller of this
    function — must never grow `worker.log`/`miner.log`; this is a
    different surface from the worker's own batch loop, which DOES log
    via :func:`compose_batch_prompt`)."""
    home = Path(home)
    roster = skill_roster(home)
    candidates = cluster_candidates(home, [entry]).get(entry.record.id, [])
    block = compose_record_block(
        home, entry, roster=roster, candidates=candidates, log_bytes=False
    )
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
        # U-attrib: `path` is now a STAGED path (flat, ST-b) — its record
        # is no longer findable via `path.parent.parent` (that trick only
        # worked when the file lived inside `<bucket>/proposals/`).
        # Resolved by record id instead, across every bucket, exactly as
        # `stamp_proposal` resolves its own destination (AD7).
        try:
            rpath: Path | None = find_record_path(home, path.stem, statuses=("pending",))
        except Exception:  # noqa: BLE001 — S6: never crash prompt assembly
            rpath = None
        if rpath is not None and rpath.is_file():
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
    staged_or_written: list[Path],
    batch: list,
    roster: Roster | None = None,
    *,
    refuse: dict[Path, str] | None = None,
    foreign: list[Path] | None = None,
    snap0: dict[Path, str] | None = None,
    stage_on: bool = True,
) -> RunResult:
    """Validate + sweep + commit, as ONE locked section (audit 2026-07-16
    round 7 — the invariant: no ledger mutation may precede its lock).
    Still the only locked section, still the only mutation site (§3.3 S8).

    A lock failure is LOGGED, never raised: this runs in a Popen-detached
    process where an escaping exception is a stack dump into worker.log and
    a dead run (BLOCKER B), for a condition — "another producer is
    committing right now" — that is not an error. Because the lock is taken
    BEFORE the first mutation, refusing here costs nothing: the model's
    output stays on disk untouched and the next run validates it.

    ``roster`` (U-composer §3.6) is the :class:`Roster` composed for THIS
    run's prompt — threaded through so validation can check the
    roster-sha honesty legs against the roster the model actually saw,
    not a freshly recomposed one. ``refuse`` (U-repair §3.5/S8) is S5's
    forced-refusal map (Set-J pin violations, V-set rewrites) — a path in
    it is refused UNCONDITIONALLY, even if its content would otherwise now
    validate.

    U-attrib: ``stage_on`` (§3.7) selects between :func:`_validate_written`
    (the two-pass Install-1 shape — ``staged_or_written`` is `staged`,
    ``foreign``/``snap0`` carry S7's exclusion set and Install-1's
    baseline, ``batch`` resolves destinations) and
    :func:`_validate_written_legacy` (``SELF_LEARN_STAGE=0`` — today's
    single-pass shape, ``staged_or_written`` is `written`; `batch`,
    `foreign`, `snap0` are unused there)."""
    from . import gitops

    try:
        with gitops.commit_lock(home):
            if stage_on:
                result = _validate_written(
                    home,
                    staged_or_written,
                    batch,
                    roster,
                    refuse=refuse,
                    foreign=foreign,
                    snap0=snap0,
                )
            else:
                result = _validate_written_legacy(
                    home, staged_or_written, roster, refuse=refuse
                )
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
    #: U-attrib (ST-e): the destination-resolved path this staged file
    #: would land at, or ``None`` when it is litter (no batch entry names
    #: it). ``None`` for a pass-2 (foreign) verdict is impossible — the
    #: caller always passes the ledger path itself as `dest` there, since
    #: a foreign file is already AT its destination.
    dest: Path | None = None
    #: The prepared merge document (record_shas resolved in memory),
    #: ready to write — populated ONLY for a schema-valid merge proposal;
    #: `None` in every other case. A non-merge success needs nothing
    #: carried forward: `stamp_proposal` re-reads the file itself.
    merge_data: dict | None = None


def _resolve_destination(path: Path, batch_by_id: dict[str, Path]) -> Path | None:
    """``ST-e`` — the destination resolver, run by the CALLER (§3.3) so
    it can be threaded into :func:`_check_proposal_file` as ``dest``. For
    a staged ``lrn-<id>.yaml`` the destination is the bucket of the batch
    entry whose ``record.id == <id>``; for a staged ``merge-<hex>.yaml``
    it is the bucket of its FIRST member record, read from the staged
    file's ``records:`` list. Either shape returns ``None`` (no
    destination — model litter) when the id/first-member is not a batch
    entry, or the merge's ``records:`` is empty/unresolvable/unparseable.
    Never raises (S6): an unparseable staged file simply has no resolved
    destination here — :func:`_check_proposal_file`'s OWN `read_proposal`
    call reports the real parse error first, since resolution always runs
    after it in the per-file order."""
    name = path.stem
    if name.startswith("merge-"):
        try:
            data = read_proposal(path)
        except Exception:  # noqa: BLE001 — S6
            return None
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list) or not records:
            return None
        first = records[0]
        if not isinstance(first, str):
            return None
        bucket_dir = batch_by_id.get(first)
        if bucket_dir is None:
            return None
        return bucket_dir / "proposals" / path.name
    bucket_dir = batch_by_id.get(name)
    if bucket_dir is None:
        return None
    return bucket_dir / "proposals" / path.name


def _batch_by_id(batch: list) -> dict[str, Path]:
    """``ST-e``'s lookup table: batch record id -> its bucket dir."""
    return {entry.record.id: entry.bucket_dir for entry in batch}


def _check_proposal_file(
    home: Path,
    path: Path,
    roster: Roster | None,
    refuse: dict[Path, str],
    dest: Path | None,
) -> _Verdict:
    """THE per-file check (§3.3, B1: one definition, not two) — S4's dry
    pass and both of S8's passes all call this SAME function. It is PURE:
    it reads and validates, and NEVER writes, stamps, dumps or deletes
    anything itself. That is not merely a convention here — it is what
    makes the lock invariant provable by source (tests/
    test_lock_invariant.py): this function is reachable from an UNLOCKED
    caller (S4, before the model's repair invocation even runs) and a
    LOCKED one (S8, via `_harvest`'s `commit_lock`), and a static analysis
    cannot see that a runtime flag would have skipped a write on the
    unlocked path — so the write must not exist in this function's body
    AT ALL. Every actual mutation lives in :func:`_validate_written` (or
    its legacy twin) instead, which only `_harvest` ever calls.

    ``dest`` (U-attrib, ST-e) is resolved by the CALLER — for a staged
    path it is :func:`_resolve_destination`'s result (``None`` iff
    litter); for a FOREIGN (already-in-the-ledger) path, or under
    ``SELF_LEARN_STAGE=0``, the caller passes the path itself, since
    those files are already at their destination and nothing relocates.

    Per-file order is normative (§3.8): naming-contract check -> secret
    scan -> read_proposal -> refusal-map override (``refuse``, §3.5) ->
    destination check (``dest is None`` -> litter, ST-e) -> resolve the
    pending record (via ``dest``) -> validate_proposal (+ roster-sha
    honesty) -> Rule-F. A path in ``refuse`` is refused UNCONDITIONALLY
    at that point, even when its post-repair content would otherwise now
    validate (§3.5's Set-Q enforcement — a forced refusal is a verdict,
    not a hint to validate harder).

    Rule-F (§3.8): ``phi`` is F-a (validation + roster-sha honesty
    accepted it) AND F-b (``record_sha_matches``) — computed REGARDLESS
    of destination (hook or not). Under U-attrib `phi` no longer governs
    installation for a STAGED path at all (`IN9` — the shipped `Φ` skip
    is removed from pass 1); it is read only by pass 2's `Rule-Fp`, and
    the hook carve-out governs stamp-or-leave there too (`CP7`), never
    here."""
    name = path.stem
    is_merge = name.startswith("merge-")
    expected_shape = (
        (path.parent == stage_dir() or path.parent.name == "proposals")
        and path.suffix == ".yaml"
        and (name.startswith("lrn-") or is_merge)
    )
    error: str | None = None
    phi = False
    record_sha_matches = False
    is_hook = False
    merge_data: dict | None = None
    bucket = _bucket_name(home, dest) if dest is not None else None
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
        if dest is None:
            # ST-e: no batch entry names this id (lrn-) / first member
            # (merge) — model litter, refused before any further
            # resolution is attempted (RT5: E-4 survives as this litter
            # rule, never a provenance rule).
            raise ProposalError(f"no batch record for {name}")
        if is_merge:
            # Members/record_shas are resolved IN MEMORY and
            # validate_merge_proposal runs unconditionally (§3.3) — only
            # the eventual install write (the caller's job) is a real
            # mutation. Members resolve against `dest`'s bucket — the ONE
            # bucket this merge lands in (ST-e).
            shas = {}
            for rid in data.get("records") or []:
                rpath = dest.parent.parent / "pending" / f"{rid}.md"
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
            rpath = dest.parent.parent / "pending" / f"{name}.md"
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
        dest=dest,
        merge_data=merge_data,
    )


def _dry_check_batch(
    home: Path,
    staged1: list[Path],
    roster: Roster | None,
    dest_map: dict[Path, Path | None],
) -> dict[Path, _Verdict]:
    """Seq-1 S4 — classify every path in ``staged1`` with the SAME
    per-file check S8 performs, mutating NOTHING on disk (B1) — trivially
    true here, since :func:`_check_proposal_file` never mutates at all.
    ``dest_map`` carries each path's ST-e-resolved destination (or, under
    ``SELF_LEARN_STAGE=0``, the path itself — the caller builds it either
    way; see :func:`run`)."""
    return {
        path: _check_proposal_file(home, path, roster, {}, dest_map.get(path))
        for path in staged1
    }


# -------------------------------------------------- U-attrib: Install-1
#
# When bytes may move into the ledger (§3.4). Applies inside
# :func:`_validate_written`'s pass 1, per staged path, after that path's
# verdict is `error is None`.


class _InstallStampError(Exception):
    """Raised by :func:`_install_staged` when the atomic copy landed but
    `stamp_proposal` then raised (§3.4's two-step, AD7) — the install
    journal entry stays (it was written BEFORE the copy) so the NEXT
    run's `I-c` can resume it."""


def _install_journal_path() -> Path:
    return _p("worker.install-journal")


def _read_install_journal() -> dict[Path, str]:
    """`IJ` (§3.4) — one ``(destination, digest)`` pair per line. Read
    ONLY here, inside S8's pass 1 (never at S1 — r2's BLOCKER 1, folded).
    A corrupt line is skipped, never fatal (S6)."""
    entries: dict[Path, str] = {}
    try:
        text = _install_journal_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            entries[Path(row["dest"])] = row["digest"]
        except Exception:  # noqa: BLE001 — S6: a corrupt line is never fatal
            continue
    return entries


def _write_install_journal(entries: dict[Path, str]) -> None:
    """Rewrites the whole journal from ``entries`` — called after EVERY
    individual add/remove inside pass 1 (never batched, never truncated
    in bulk — r2's MAJOR 1, folded): the file on disk is always the
    caller's current in-memory state, so a kill between two per-file
    steps leaves exactly the entries that were true at that instant."""
    path = _install_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"dest": str(dest), "digest": digest})
        for dest, digest in entries.items()
    ]
    text = "\n".join(lines)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _dest_state(dest: Path) -> tuple[str | None, bool]:
    """Install-1's raw inputs for one destination, read fresh under the
    lock: ``(current sha-anchor digest, or None if dest is absent;
    whether dest carries a non-null record_sha key)``."""
    try:
        text = dest.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None, False
    from ruamel.yaml import YAML

    try:
        data = YAML(typ="safe").load(text)
    except Exception:  # noqa: BLE001 — S6
        data = None
    has_sha = isinstance(data, dict) and data.get("record_sha") is not None
    return sha_anchor(text), has_sha


def _clean_stale_install_temps(home: Path) -> None:
    """AD8: any ``.install-*.tmp`` found in a destination directory at
    the start of pass 1 is removed first, so a crashed run leaves no
    accumulating litter. These are NEVER `_still_pending`'s orphan-sweep
    globs (`lrn-*.yaml`/`merge-*.yaml`) and never git-tracked — a plain
    unlink under the already-open lock is the whole of it."""
    for bucket in discover_buckets(home):
        pdir = bucket.path / "proposals"
        if not pdir.is_dir():
            continue
        for tmp in pdir.glob(".install-*.tmp"):
            tmp.unlink(missing_ok=True)


def _install_staged(
    home: Path, verdict: _Verdict, staged_path: Path, journal: dict[Path, str]
) -> None:
    """Install-1's ATOMIC copy (AD8, reversed-in-r4): a temp beside the
    destination, then `os.replace` — then, for a plain proposal, the
    CLI's own `stamp_proposal` (AD7's two-step). The journal entry is
    WRITTEN BEFORE the copy and removed only after the stamp succeeds (or
    immediately for a merge, which has no separate stamp step): the
    digest is of the COMPLETE INTENDED bytes, so a crash at any point
    between the write and the removal always leaves a state `I-c` can
    recognize on the next run — there is no third state (§3.4)."""
    dest = verdict.dest
    assert dest is not None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".install-{verdict.name}.tmp"
    if verdict.is_merge:
        assert verdict.merge_data is not None
        _dump_yaml(verdict.merge_data, tmp)  # same writer U-repair already uses
    else:
        tmp.write_text(staged_path.read_text(encoding="utf-8"), encoding="utf-8")
    digest = sha_anchor(tmp.read_text(encoding="utf-8"))
    journal[dest] = digest
    _write_install_journal(journal)
    os.replace(tmp, dest)  # same filesystem — atomic (AD8)
    if not verdict.is_merge:
        try:
            stamp_proposal(home, verdict.name)
        except Exception as exc:  # noqa: BLE001 — S6: journaled, never fatal
            raise _InstallStampError(str(exc)) from exc
    del journal[dest]
    _write_install_journal(journal)


def _stage_discard(path: Path) -> None:
    """Unlink a staged (cache) file that never landed — a decline, a
    litter file, or one already consumed by a successful install. NEVER
    appended to `result.touched` (Obs-2's `OB3` type leg): a cache path
    must never be staged into a ledger commit."""
    path.unlink(missing_ok=True)


def _validate_written(
    home: Path,
    staged: list[Path],
    batch: list,
    roster: Roster | None = None,
    *,
    refuse: dict[Path, str] | None = None,
    foreign: list[Path] | None = None,
    snap0: dict[Path, str] | None = None,
) -> RunResult:
    """Run-sequence step 8 (§3.3), U-attrib shape: TWO passes, in order.

    Pass 1 — the model's output (``staged``): per file, `Install-1`
    decides whether the validated staged proposal may move into the
    ledger (`I-a`/`I-b`/`I-c`); a decline never deletes anything and is
    counted in `result.not_installed`, never in `proposed`/`touched`.

    Pass 2 — `Rule-Fp`, foreign progress (§3.3): for EVERY member of
    ``foreign`` (paths some other producer wrote or changed in the ledger
    during the window), compute the verdict READ-ONLY and, if Rule-F
    holds, record it in `result.foreign_left` — independent of whether
    pass 1 declined anything for the same record (`RT7`). Nothing in
    pass 2 installs, stamps, counts toward `proposed`/`valid_landed`, or
    appends to `touched` — its ONE carve-out is the secret scan, which
    still deletes a foreign hit (`U-repair` `D3`'s ratified ranking).

    Only :func:`_harvest` calls this function, always under
    `commit_lock`."""
    refuse = refuse or {}
    foreign = foreign or []
    snap0 = snap0 or {}
    result = RunResult(status="failed")
    result.staged_written = len(staged)
    batch_by_id = _batch_by_id(batch)

    _clean_stale_install_temps(home)
    journal = _read_install_journal()

    for path in staged:
        dest = _resolve_destination(path, batch_by_id)
        verdict = _check_proposal_file(home, path, roster, refuse, dest)
        if verdict.error is not None:
            log(f"run: invalid worker output {path.name} deleted ({verdict.error})")
            result.invalid_deleted.append(path.name)
            _stage_discard(path)
            continue
        dest = verdict.dest
        assert dest is not None
        current_digest, has_record_sha = _dest_state(dest)
        present = current_digest is not None
        i_a = not present
        i_b = (
            present
            and dest in snap0
            and snap0[dest] == current_digest
            and has_record_sha
        )
        entry_digest = journal.get(dest)
        i_c = entry_digest is not None and (not present or current_digest == entry_digest)
        if i_a or i_b or i_c:
            if entry_digest is not None:
                # IN8(b): a live IJ entry for this destination means a
                # PRIOR run's install was interrupted after the journal
                # write but before the entry was cleared (§3.4) — this
                # run is resuming it via I-c, not performing a fresh
                # install. The line is distinct from the two failure
                # lines below (which log an interruption THIS run hit).
                log(f"run: resuming interrupted install of {verdict.name} (journal)")
            try:
                _install_staged(home, verdict, path, journal)
            except _InstallStampError as exc:
                log(
                    f"run: {verdict.name} installed but not stamped "
                    f"({exc}) — journaled for the next run"
                )
                _stage_discard(path)
                continue
            except OSError as exc:
                log(
                    f"run: {path.name} install interrupted ({exc}) — "
                    "journaled for the next run"
                )
                _stage_discard(path)
                continue
            if verdict.is_merge:
                assert verdict.merge_data is not None
                result.merge_proposed.append(verdict.merge_data["cluster_id"])
            else:
                result.proposed.append(verdict.name)
            result.touched.append(dest)
            if verdict.bucket and verdict.bucket not in result.buckets:
                result.buckets.append(verdict.bucket)
            _stage_discard(path)
        else:
            if entry_digest is not None:
                # stale (§3.4): another producer took this path over
                # since our interrupted install — drop the orphaned entry.
                del journal[dest]
                _write_install_journal(journal)
            if present and dest in snap0 and snap0[dest] == current_digest and not has_record_sha:
                log(
                    f"run: staged proposal {path.name} not installed — "
                    "destination is an unstamped draft this run did not write"
                )
            else:
                log(
                    f"run: staged proposal {path.name} not installed — "
                    "destination changed during the window"
                )
            result.not_installed.append(dest.name)
            _stage_discard(path)

    result.valid_landed = len(result.proposed) + len(result.merge_proposed)

    seen_names = set(result.proposed) | set(result.merge_proposed)
    for path in foreign:
        verdict = _check_proposal_file(home, path, roster, refuse, path)
        if verdict.error is not None:
            if "secret scan hit" in verdict.error:
                log(f"run: invalid worker output {path.name} deleted ({verdict.error})")
                result.invalid_deleted.append(path.name)
                _git_rm_or_unlink(home, path, result)
            continue
        if verdict.name in seen_names:
            continue
        if verdict.phi:
            result.foreign_left.append(verdict.name)
            seen_names.add(verdict.name)
            log(
                f"run: proposal {path.name} carries a matching "
                "record_sha — another producer wrote it; left untouched"
            )
    result.foreign_seen = len(foreign)
    return result


def _validate_written_legacy(
    home: Path,
    written: list[Path],
    roster: Roster | None = None,
    *,
    refuse: dict[Path, str] | None = None,
) -> RunResult:
    """``SELF_LEARN_STAGE=0`` (§3.7): today's single-pass behaviour,
    BYTE-IDENTICAL to the pre-U-attrib shape — every changed ledger
    proposal is attributed to the model (`_written_since`'s pre-U-attrib
    meaning), `dest` is the path itself (nothing relocates, `Install-1`
    is never consulted), and Rule-F applies inline exactly as `U-repair`
    shipped it. Only :func:`_harvest` calls this function, always under
    `commit_lock`."""
    refuse = refuse or {}
    result = RunResult(status="failed")
    for path in written:
        verdict = _check_proposal_file(home, path, roster, refuse, path)
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


def _notifications_suppressed(home: Path | str | None = None) -> bool:
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
    exercised opts back out via ``monkeypatch.delenv``.

    U-settings Phase 1: resolves through the registry's ``worker.
    no_notify`` entry (config.yaml `worker.no_notify` > env > `False` --
    U-flip 2026-09-01, S-58: config wins) rather than reading the env
    var directly. ``home`` defaults to :func:`resolve_home` when omitted
    (M-P, sprint 1 audit A14/A13) — the two callers below still call
    this bare (neither threads a `home`; neither writes a config.yaml),
    so their behaviour is unchanged; a future caller that DOES hold an
    explicit `home` can now pass it through instead of racing the
    ambient `SELF_LEARN_HOME`.

    M-P fold r1 (F3): an explicit `home` is `.expanduser()`'d before use,
    matching :func:`resolve_home`'s own normalization -- `config_path`
    never expands `~` on its own, so an unexpanded `home` would silently
    miss `config.yaml` entirely."""
    resolved_home = Path(home).expanduser() if home is not None else resolve_home()
    value, _source = settings.resolve_setting(resolved_home, settings.by_name("worker.no_notify"))
    return bool(value)


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
    # M-B: full-timestamp floor via domain.record_age_days — the old
    # ``str(created_at)[:10]`` truncation dropped the record's real
    # time-of-day before subtracting, which is exactly the A1 divergence
    # from ``list --json``/``status --json``'s ages (both already used the
    # full timestamp).
    oldest = 0
    now = datetime.now(timezone.utc)
    for bucket in discover_buckets(home):
        for entry in queue(bucket):
            oldest = max(oldest, domain.record_age_days(entry.record, now))
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
        chrono.ISO_FORMAT
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
            # M-B: domain.is_queued is THE membership rule (mapping form —
            # this scan never loads a full Record) — a lapsed deferral
            # (``deferred_until`` in the past) is queued, same as
            # ``list``/``status`` already compute via ``ledger_ops.queue``.
            if not domain.is_queued(fm, now):
                continue  # hidden or non-draft — same rule as the queue
            pending += 1
            # Full-timestamp floor (domain.record_age_days) — the old
            # ``str(created_at)[:10]`` truncation here was the A1
            # divergence from ``list --json``/``status --json``'s ages.
            age = domain.record_age_days(fm, now)
            oldest = age if oldest is None else max(oldest, age)
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
    prompt: str, timeout: float, home: Path, *,
    label: str,
    containment: invocation.Containment | None = None,
    charter_denials: list[dict[str, Any]] | None = None,
    evidence: RunEvidence | None = None,
) -> None:
    """One model invocation — round 1 (``label=""``) or the repair round
    (``label="repair "``), same exception handling shape as this project
    shipped before U-repair; the label prefix is what distinguishes their
    log lines (§3.12). Never raises — an invocation failure is logged and
    the run continues (round 1's valid output, if any, must still land;
    B7).

    U-seam §3.9.1: the transport itself now lives behind the invocation
    seam (``invocation.write_session``) — this function's job is to
    describe THIS call as a ``SessionSpec`` and hand it over.
    U-cleanup §7: the worker carries no doctrine (``doctrine=None``,
    §2.3.1 measured) — its routing doctrine rides the PROMPT
    (:func:`compose_batch_prompt`), not a system-prompt append.
    ``containment`` is data only (``HY4`` — it enforces nothing); when
    omitted (only `test_repair.py::test_e1` does, per ``B-4``),
    :data:`invocation.DEGRADED_WORKER_CONTAINMENT` stands in — ``run()``
    itself always passes an explicit one (``W-a``).

    FW-107: ``charter_denials``, when given, is a caller-owned list this
    call EXTENDS with this invocation's charter-sourced denials
    (``outcome.denials`` entries with ``source == "charter"``) — an
    additive side channel, not a return-value change, because
    `test_invocation.py::test_wr1_invoke_claude_signature_and_never_
    raises` and several `test_worker_contract.py` call sites pin this
    function returning ``None`` unconditionally (no ``return``
    statement below); every existing call site that omits the new
    keyword-only parameter keeps that exact contract. ``run()``'s batch
    loop is the one caller that passes it, to carry a denial count from
    this invocation's outcome to its own run-summary log line without
    otherwise touching what this function returns.

    U-corrob: ``evidence``, when given, is a caller-owned
    :class:`~self_learn.corroborate.RunEvidence` this call feeds via
    :meth:`~self_learn.corroborate.RunEvidence.observe` — the same
    caller-owned-accumulator shape as ``charter_denials`` above, and for
    the same reason: this function's always-returns-``None`` contract
    does not move. Only ``run()``'s round-1 call passes it (`§5.8` — the
    repair round is excluded)."""
    spec = invocation.SessionSpec(
        surface="worker-repair" if label == "repair " else "worker",
        prompt=prompt,
        cwd=home,
        timeout=timeout,
        containment=containment or invocation.DEGRADED_WORKER_CONTAINMENT,
        log=log,
        label=label,
        doctrine=None,
    )
    outcome = invocation.write_session(spec)
    if charter_denials is not None:
        charter_denials.extend(
            d for d in getattr(outcome, "denials", ()) if d.get("source") == "charter"
        )
    if evidence is not None:
        evidence.observe(outcome)


def run(
    home: Path | str, *, coalesce: bool = False, no_push: bool | None = None
) -> RunResult:
    """``no_push=None`` reads the process boundary once
    (:func:`no_push_requested`) and then threads the answer as a parameter
    — BLOCKER D: the policy is data, not ambience.

    M-2 (review 2026-09-01): :func:`coalesce_secs`, :func:`invoke_
    timeout_secs`, and :func:`repair_timeout_secs` are all called with
    this SAME ``home`` below, not bare — each is optional-`home` and
    silently falls back to :func:`resolve_home` when omitted, so a bare
    call still "worked" pre-flip, but under config-wins it could read a
    DIFFERENT config.yaml than the rest of this very run whenever
    ``resolve_home()`` and this call's ``home`` disagree (measured: 99.0
    vs. home-A's 11.0). One run must read one policy file."""
    home = Path(home)
    if no_push is None:
        no_push = no_push_requested()
    cache_dir().mkdir(parents=True, exist_ok=True)
    _register_running_pid()  # fold r2 MINOR 1: bound the marker's life to child startup
    if coalesce:
        time.sleep(coalesce_secs(home))

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
                stage_on = _stage_enabled()  # §3.7
                # U-settings Phase 1 (config.yaml `worker.repair` > env >
                # True -- U-flip 2026-09-01, S-58: config wins). A garbage
                # value at either rung warns on stderr and falls through;
                # the eventual fallback is True, same net outcome the old
                # `!= "0"` env check gave any non-"0" value.
                repairs_enabled, _repair_source = settings.resolve_setting(
                    home, settings.by_name("worker.repair")
                )
                # FW-107: accumulates this run's charter-sourced denials
                # (both rounds feed it) so a fully-denied run can be told
                # apart from a wrote-nothing one in the FAILED summary
                # below, without perturbing `_invoke_claude`'s pinned
                # always-returns-`None` contract.
                charter_denials: list[dict[str, Any]] = []
                # U-corrob: round-1 corroboration evidence, constructed
                # only when the stage IS this round's filesystem
                # instrument (`§5.8` excludes the repair round; under
                # `SELF_LEARN_STAGE=0` the original `_written_since` diff
                # is still the authority and there is nothing to
                # corroborate against).
                evidence = RunEvidence(stage_dir(), flat=True) if stage_on else None
                if stage_on:
                    stage_reset(home)  # S1 (ST-c) — before composing the prompt
                else:
                    log("run: stage disabled (SELF_LEARN_STAGE=0)")
                prompt, roster = compose_batch_prompt(home, batch)
                snap0 = _proposal_snapshot(home)  # S1 — Install-1's baseline now
                _invoke_claude(
                    prompt, invoke_timeout_secs(home), home, label="",
                    containment=invocation.containment_for(
                        "worker",
                        allowed_tools=ALLOWED_TOOLS,
                        disallowed_tools=DISALLOWED_TOOLS,
                        home=home,
                        stage_dir=stage_dir(),
                        stage_on=stage_on,
                        enforce=_enforce_scope(),
                    ),
                    charter_denials=charter_denials,
                    evidence=evidence,
                )  # S2
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

                # S3 — replaced (§3.3): the model's round-1 output BY
                # CONSTRUCTION is the stage's contents, not an inference
                # over what changed in the ledger. Under the switch,
                # today's `_written_since` reading survives verbatim.
                batch_by_id = _batch_by_id(batch)
                if stage_on:
                    staged1 = staged_paths()
                    log(f"run: stage — {len(staged1)} file(s) written by the model")
                    # U-corrob: at most one of the two verdict lines,
                    # plus the OUTSIDE line independently (`COR4`/`COR5`;
                    # both gated internally by `RunEvidence`'s own
                    # seen/failure/events_present rule — a failed or
                    # eventless round-1 invocation prints neither).
                    if evidence is not None:
                        fs_count = len(staged1)
                        tag = evidence.verdict(fs_count)
                        if tag == NO_EVIDENCE:
                            log(
                                "run: corroboration — no tool events "
                                f"recorded ({fs_count} file(s) on disk)"
                            )
                        elif tag == MISMATCH:
                            log(
                                "run: corroboration MISMATCH — stage has "
                                f"{fs_count} file(s), model reported "
                                f"{len(evidence.inside)} accepted write(s) "
                                "(filesystem is authority)"
                            )
                        outside = evidence.outside_paths()
                        if outside:
                            log(
                                f"run: {len(outside)} accepted write(s) "
                                "reported OUTSIDE the stage (filesystem is "
                                f"authority; see the event log in {cache_dir()})"
                            )
                    dest_map1: dict[Path, Path | None] = {
                        p: _resolve_destination(p, batch_by_id) for p in staged1
                    }
                else:
                    staged1 = _written_since(home, snap0)
                    dest_map1 = {p: p for p in staged1}
                repair_attempted = False
                repair_eligible_paths: dict[Path, str] = {}
                refuse: dict[Path, str] = {}

                if not repairs_enabled:
                    # M-3 (review 2026-09-01): report the ACTUAL source
                    # that resolved `repairs_enabled` to False, not a
                    # hardcoded env spelling -- since the flip, that
                    # source is at least as often `config:worker.repair`
                    # as it is `env:SELF_LEARN_REPAIR`, and a log line
                    # that always names the env var misattributes every
                    # config-driven disable.
                    log(f"run: repair round disabled ({_repair_source})")
                else:
                    verdicts = _dry_check_batch(home, staged1, roster, dest_map1)  # S4
                    n_refused = sum(1 for v in verdicts.values() if v.error is not None)
                    # S5's E — Set-E's text rules (E-1..E-3) ONLY (RT4/RT5:
                    # the two old provenance rules — E-4 batch membership,
                    # E-5 unstamped — are retired from this filter. E-4
                    # survives as ST-e's litter rule, already reflected in
                    # `verdicts` (a non-batch id's error does not start
                    # with "gates." and so `_repairable` already excludes
                    # it); E-5's insight re-sites into `Install-1`'s I-b.
                    repair_eligible_paths = {
                        p: v.error
                        for p, v in verdicts.items()
                        if v.error is not None and _repairable(v.error) == "ELIGIBLE"
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
                        repair_prompt = _compose_repair_prompt(
                            home, repair_eligible_paths
                        )
                        # FW-117 (2026-08-28): `write_repair_settings_file`
                        # used to be called here, writing a real settings
                        # file to `worker.repair.settings.json` -- a dead
                        # write nothing ever read (`options_kwargs()`
                        # passes `settings=None` unconditionally, `A-2`;
                        # the cli-era `--settings <path>` reader is gone
                        # with `CliBackend`). Deleted outright, not
                        # guarded: the containment passed to
                        # `_invoke_claude` below (`write_exact=`) is the
                        # SAME data this call used to render to disk, and
                        # is what the charter actually enforces.
                        # Pre-declared (not just branch-assigned): the
                        # two blocks below are gated by the SAME
                        # `stage_on` value both times, so exactly one of
                        # these is ever read — but pyright's flow
                        # analysis cannot link two separate `if
                        # stage_on:` checks, and flags the unread
                        # variable as possibly-unbound without this.
                        snap1_stage: dict[Path, str] = {}
                        snap1: dict[Path, str] = {}
                        if stage_on:
                            # Snapshot the WHOLE stage's content, not only
                            # E — GR-d's grant is exact-path, but this is
                            # the defense-in-depth leg (G6): the V-set
                            # rule must still catch a repair that reaches
                            # a SIBLING staged file even if that grant
                            # were ever loosened, so "what changed" cannot
                            # be scoped to E alone.
                            snap1_stage = {
                                p: p.read_text(encoding="utf-8")
                                for p in staged1
                                if p.exists()
                            }
                        else:
                            snap1 = _proposal_snapshot(home)
                        _invoke_claude(
                            repair_prompt,
                            repair_timeout_secs(home),
                            home,
                            label="repair ",
                            containment=invocation.containment_for(
                                "worker-repair",
                                allowed_tools=ALLOWED_TOOLS,
                                disallowed_tools=DISALLOWED_TOOLS,
                                write_exact=tuple(
                                    str(p) for p in repair_eligible_paths
                                ),
                                enforce=_enforce_scope(),
                            ),
                            charter_denials=charter_denials,
                        )
                        # G8: re-assert again after the LAST invocation.
                        if not sentinel.heartbeat():
                            hold = sentinel.hold()
                            sentinel.heartbeat()

                        if stage_on:
                            # GR-d grants ONE exact-path Edit rule per
                            # member of E, over the STAGE — checked
                            # directly against the pre-repair snapshot
                            # rather than a ledger-wide scan (CP10, §5
                            # lead (c)): a repair-deleted staged path
                            # (in E) must not crash `run()`.
                            touched2: set[Path] = set()
                            for p in staged1:
                                if not p.exists():
                                    if p in repair_eligible_paths:
                                        log(
                                            f"run: repair round: {p.name} "
                                            "disappeared during repair — "
                                            "record stays pending"
                                        )
                                    continue
                                if p not in snap1_stage or p.read_text(encoding="utf-8") != snap1_stage[p]:
                                    touched2.add(p)
                            staged1_set = set(staged1)
                            # RT2: Φ leaves S5's partition entirely — every
                            # member of staged1 is the model's own output
                            # (nothing foreign can ever be in the stage),
                            # so the V-set is simply every valid one.
                            v_at_s4 = {
                                p for p in staged1_set if verdicts[p].error is None
                            }
                        else:
                            touched2 = set(_written_since(home, snap1))
                            written1_set = set(staged1)
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

                # S7 — replaced (§3.3): TWO sets now, both rounds' output.
                if stage_on:
                    staged = staged_paths()
                    foreign = _written_since(home, snap0)
                    if foreign:
                        log(
                            f"run: {len(foreign)} ledger proposal(s) changed "
                            "during the window — not this run's writes"
                        )
                else:
                    staged = _written_since(home, snap0)  # "written" — both rounds
                    foreign = []
                # [first mutation → commit] under ONE lock (audit
                # 2026-07-16 round 7, THE invariant). Validation DELETES
                # schema-invalid model output and sweeps orphaned and
                # invalidated-merge proposals — deletions of TRACKED
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
                result = _harvest(  # S8
                    home,
                    staged,
                    batch,
                    roster,
                    refuse=refuse,
                    foreign=foreign,
                    snap0=snap0,
                    stage_on=stage_on,
                )
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
                    # FW-107: a fully-denied run (every write attempt
                    # refused by the charter) used to be byte-identical
                    # to a run that wrote nothing at all in this log --
                    # both landed only the line above. Additive line,
                    # only when this run actually saw a charter denial;
                    # the FAILED line itself is unchanged (`test_repair.
                    # py::test_h3_...` pins it verbatim). N-2 (gate r1):
                    # the file reference is locatable -- no `run_id` is
                    # in scope here (`_drive` never returns one), so the
                    # glob is paired with the resolved cache dir instead.
                    if charter_denials:
                        log(
                            f"run: {len(charter_denials)} charter "
                            "denial(s) this run — see "
                            f"worker*.tool-events.*.jsonl in {cache_dir()}"
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
        elif _autokick_disabled(home):
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
