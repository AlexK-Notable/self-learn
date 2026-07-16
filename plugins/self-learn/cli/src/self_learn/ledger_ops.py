"""Ledger file operations and queue semantics (T3).

Scope: the FILE-OP halves of the resolution verbs plus queue computation.
Commit/push/sentinel live in T7, which wraps these ops and stages exactly
the returned touched paths (08 §1 Resolution-verbs pin: never ``-A``).

Staging contract for callers (T7): every path this module deletes is either
``git rm``-ed / ``git mv``-ed (deletion already staged) or was untracked
(nothing to stage), so staging = ``git add -- <touched paths that still
exist>``. The returned list is exact and exhaustive either way.

The two single-definition functions (08 §1 ``--json``-stubs pin, §7.1
worker-run-sequence step 2 / P2-4):

- :func:`queue` — THE queue computation: pending records minus
  future-``deferred_until`` (membership is computed, never read off
  ``status`` — 02 §2). ``include_deferred=True`` returns the superset.
- :func:`is_unanalyzed` — THE eligibility predicate: pending, non-deferred,
  and lacking a schema-valid proposal, or proposal ``record_sha`` ≠ the
  current normalized-body hash (content identity, never mtime).

``list``/``status``/the M2 worker all call these; no second definitions.
"""

from __future__ import annotations

import io
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .ledger import Bucket, discover_buckets, home_state, home_state_message
from .normalize import sha_anchor
from .records import RECORD_ID_RE, Record, RecordError

__all__ = [
    "DEFAULT_DEFER_DAYS",
    "LedgerOpsError",
    "ProposalError",
    "PROPOSAL_DESTINATIONS",
    "QueueEntry",
    "bucket_dir_for_scope",
    "bucket_project_path",
    "create_record",
    "ensure_project_meta",
    "defer_record",
    "find_record_path",
    "is_unanalyzed",
    "list_items",
    "proposal_info",
    "queue",
    "read_proposal",
    "record_title",
    "resolve_record",
    "stamp_proposal",
    "status_infos",
    "supersede_record",
    "unparseable_pending",
    "validate_merge_proposal",
    "validate_proposal",
    "write_proposal",
]

#: 02 §1's destination enum, verbatim (list --json surfaces it as-is).
PROPOSAL_DESTINATIONS = ("skill-md", "claude-md", "reference", "new-skill", "hook")

#: Statuses a record may resolve INTO (02 §2; deferral is not a resolution).
RESOLUTION_STATUSES = frozenset({"routed", "rejected", "superseded"})

DEFAULT_DEFER_DAYS = 30  # 02 §2: defer default +30 days

MERGE_ID_RE = re.compile(r"^merge-[0-9a-f]{8}$")
SHA_ANCHOR_RE = re.compile(r"^sha256:[0-9a-f]{12}$")

_SECONDS_PER_DAY = 86400
_TITLE_SECTION = {"behavior": "Trigger", "knowledge": "Fact"}
_HEADING_RE = re.compile(r"^## +(.+?)\s*$")


class LedgerOpsError(Exception):
    """A ledger file operation could not be performed."""


class ProposalError(LedgerOpsError):
    """A proposal sibling is unparseable or violates the 02 §1 schema."""


# --------------------------------------------------------------------- yaml


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _load_yaml_map(path: Path) -> dict:
    try:
        data = _yaml().load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ProposalError(f"unparseable YAML at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProposalError(f"{path} is not a YAML mapping")
    return data


def _dump_yaml(data: dict, path: Path) -> None:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


# ---------------------------------------------------------------------- git


def _git(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(home), *args], capture_output=True, text=True
    )


def _git_ok(home: Path, *args: str) -> None:
    proc = _git(home, *args)
    if proc.returncode != 0:
        raise LedgerOpsError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")


def _is_tracked(home: Path, path: Path) -> bool:
    return _git(home, "ls-files", "--error-unmatch", "--", str(path)).returncode == 0


def _remove_file(home: Path, path: Path) -> bool:
    """``git rm --ignore-unmatch`` + fs remove (the file may be untracked
    mid-review — 08 §1 Proposal-lifecycle pin). True iff the file existed."""
    if not path.exists():
        return False
    _git(home, "rm", "-f", "-q", "--ignore-unmatch", "--", str(path))
    if path.exists():  # untracked (or no git repo): git rm left it in place
        path.unlink()
    return True


# --------------------------------------------------------------------- time


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_dt(value) -> datetime | None:
    """Lenient timestamp coercion: ruamel hands back datetime/date for plain
    ISO scalars, str otherwise. None / unparseable → None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ts_str(value) -> str | None:
    """Render a frontmatter timestamp for JSON output."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _age_days(created_at, now: datetime) -> int:
    dt = _to_dt(created_at)
    if dt is None:
        return 0
    return max(0, int((now - dt).total_seconds() // _SECONDS_PER_DAY))


def _deferred_hidden(record: Record, now: datetime) -> bool:
    """THE membership rule's deferral half: hidden iff ``deferred_until`` is
    in the future (status may still say deferred — computed, 02 §2)."""
    until = _to_dt(record.deferred_until)
    return until is not None and until > now


# ---------------------------------------------------------- bucket routing


def bucket_dir_for_scope(
    home: Path, scope: str, *, project_path: Path | None = None
) -> Path:
    """Map a record scope to its bucket dir (doc 13 §3 layout):
    ``skill:<name>`` → ``<home>/skills/<name>`` — but the name is
    validity-gated against the registered skills-root HOST first (H-3:
    capture may be open, but a skill bucket that no host skill backs is a
    typo, not a bucket); ``user`` → ``<home>/user``; ``project`` →
    ``<home>/projects/<slug_for(project_path)>`` (the path is REQUIRED —
    project buckets are per-project now, doc 13 §0 point 2)."""
    from .hosts import HostsError, load_hosts, skill_dir_for, slug_for

    if scope == "user":
        return home / "user"
    if scope == "project":
        if project_path is None:
            raise LedgerOpsError(
                "project scope needs a project_path — per-project buckets "
                "(doc 13 §3) cannot be resolved without the project's path"
            )
        return home / "projects" / slug_for(project_path)
    if isinstance(scope, str) and scope.startswith("skill:"):
        name = scope[len("skill:") :]
        try:
            skill_dir_for(load_hosts(home), name)  # validity gate only
        except HostsError as exc:
            raise LedgerOpsError(str(exc)) from exc
        return home / "skills" / name
    raise LedgerOpsError(
        f"scope must be skill:<name>, project, or user, got {scope!r}"
    )


def ensure_project_meta(bucket_dir: Path, project_path: Path | str) -> Path:
    """Write ``meta.yaml`` ({"path": <resolved project path>}) beside a
    project bucket on first creation (doc 13 §3: the slug alone is lossy).
    Existing meta is never rewritten — but a MISMATCH is refused, never
    silently accepted (audit 2026-07-16 BLOCKER 1): if the bucket already
    claims a different project, this caller's records would compile into
    that other project's canon. Two paths can only meet here through a
    slug collision or a hand-edit, and both are bugs, not routine.
    Re-pointing a bucket at a moved repo is ``host rebind``'s job.
    Returns the meta path."""
    bucket_dir.mkdir(parents=True, exist_ok=True)
    meta = bucket_dir / "meta.yaml"
    wanted = Path(project_path).expanduser().resolve()
    if not meta.is_file():
        _dump_yaml({"path": str(wanted)}, meta)
        return meta
    recorded = bucket_project_path(bucket_dir)
    if recorded is None:
        raise LedgerOpsError(
            f"{meta} is unreadable or has no path — a project bucket "
            "without its recorded path cannot be trusted to compile "
            "anywhere (doc 13 §3); repair it or re-capture"
        )
    if Path(recorded).expanduser().resolve() != wanted:
        raise LedgerOpsError(
            f"project bucket {bucket_dir} belongs to {recorded}, not "
            f"{wanted} — refusing to file this project's records in "
            "another project's bucket (they would compile into ITS "
            "CLAUDE.md); if that repo MOVED, run `self-learn host rebind "
            f"{recorded} {wanted}`"
        )
    return meta


def bucket_project_path(bucket_dir: Path) -> Path | None:
    """Read a project bucket's recorded absolute path from its
    ``meta.yaml`` (None when missing/unparseable — callers refuse)."""
    meta = Path(bucket_dir) / "meta.yaml"
    if not meta.is_file():
        return None
    try:
        data = _load_yaml_map(meta)
    except ProposalError:
        return None
    value = data.get("path")
    return Path(value) if isinstance(value, str) and value else None


def require_writable_home(home: Path | str) -> Path:
    """The WRITE-surface home gate (audit 2026-07-16 BLOCKER 11): refuse
    BEFORE writing anything when the home is missing or is not a git repo.

    Without it, ``teach`` into a nonexistent home happily created the
    bucket dirs, wrote the record, and THEN failed its commit ("record
    written but uncommitted") — leaving the lesson in an untracked
    directory that nothing will ever push, in a home the user probably
    did not mean. A missing bucket dir inside a VALID home is different
    and still auto-creates: that is ordinary."""
    state = home_state(home)
    if state in ("missing", "not-a-repo"):
        raise LedgerOpsError(home_state_message(state, home))
    return Path(home)


def create_record(
    home: Path, record: Record, *, project_path: Path | None = None
) -> Path:
    """Write a Record into its bucket's ``pending/``, creating bucket dirs
    on demand. Project-scoped records need ``project_path`` and get a
    ``meta.yaml`` written beside the bucket on first creation (doc 13 §3).
    Returns the created path."""
    require_writable_home(home)  # nothing is written into a broken home
    bucket_dir = bucket_dir_for_scope(home, record.scope, project_path=project_path)
    if record.scope == "project":
        ensure_project_meta(bucket_dir, project_path)
    pending = bucket_dir / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    path = pending / f"{record.id}.md"
    if path.exists() or (bucket_dir / "resolved" / f"{record.id}.md").exists():
        raise LedgerOpsError(f"record {record.id} already exists in {bucket_dir}")
    record.write(path)
    return path


def find_record_path(
    home: Path, record_id: str, statuses: tuple[str, ...] = ("pending", "resolved")
) -> Path:
    """Locate ``lrn-<id>.md`` across every bucket (pending first)."""
    if not RECORD_ID_RE.match(record_id or ""):
        raise LedgerOpsError(f"not a record id: {record_id!r}")
    for sub in statuses:
        for bucket in discover_buckets(home):
            p = bucket.path / sub / f"{record_id}.md"
            if p.is_file():
                return p
    raise LedgerOpsError(f"record {record_id} not found under {home}")


# ----------------------------------------------------------- proposal I/O


def _proposal_path(bucket_dir: Path, record_id: str) -> Path:
    return bucket_dir / "proposals" / f"{record_id}.yaml"


def read_proposal(path: Path) -> dict:
    """Parse a proposal sibling (no schema validation — see
    :func:`validate_proposal`)."""
    return _load_yaml_map(path)


def _validate_card(data: dict) -> None:
    """02 §1 `card:` map — human-facing review sections. Optional; shape
    only (mapping of non-empty str → non-empty str). The section SET is
    governed by the skill's card-sections.yaml registry, deliberately
    not enforced here: required-section strictness is revisited at T13."""
    card = data.get("card")
    if card is None:
        return
    if not isinstance(card, dict) or not card:
        raise ProposalError("card must be a non-empty mapping of sections")
    for key, text in card.items():
        if not isinstance(key, str) or not key.strip():
            raise ProposalError("card section keys must be non-empty strings")
        if not isinstance(text, str) or not text.strip():
            raise ProposalError(f"card section {key!r} must be non-empty text")


#: 08 §4 replay row: 2–3 allow + 2–3 deny examples per hook proposal.
_HOOK_EXAMPLES_MIN, _HOOK_EXAMPLES_MAX = 2, 3
_HOOK_KEYS = ("tools", "path_regex", "deny_message")


@lru_cache(maxsize=256)
def _ere_problem(pattern: str) -> str | None:
    """Memoized :func:`hook_compiler.validate_ere` — validation runs on
    every eligibility computation (``list``/``status --fast`` freshness),
    and each uncached check is a grep subprocess."""
    from .hook_compiler import validate_ere

    return validate_ere(pattern)


def _validate_hook_extension(data: dict) -> None:
    """02 §1 hook-destination extension (M3): ``hook:`` structured compile
    input + analyst-authored replay ``examples``; ``script`` is optional
    at validation — the CLI stamps it (:func:`stamp_proposal`), the model's
    emitted value is never trusted with executable bytes."""
    from .hook_compiler import GUARDABLE_TOOLS

    dest = data.get("destination")
    present = [k for k in ("hook", "examples", "script") if data.get(k) is not None]
    if dest != "hook":
        if present:
            raise ProposalError(
                f"{'/'.join(present)} only belong on a destination: hook "
                f"proposal, got destination {dest!r}"
            )
        return

    hook = data.get("hook")
    if not isinstance(hook, dict):
        raise ProposalError(
            "a hook proposal carries the structured compile input — "
            "hook: {tools, path_regex, deny_message} (02 §1 hook extension)"
        )
    unknown = sorted(set(hook) - set(_HOOK_KEYS))
    if unknown:
        raise ProposalError(f"unknown hook key(s) {unknown} — allowed: {list(_HOOK_KEYS)}")
    missing = sorted(set(_HOOK_KEYS) - set(hook))
    if missing:
        raise ProposalError(f"hook block missing {missing}")
    tools = hook.get("tools")
    if (
        not isinstance(tools, list)
        or not tools
        or any(t not in GUARDABLE_TOOLS for t in tools)
        or len(set(tools)) != len(tools)
    ):
        raise ProposalError(
            f"hook.tools must be a non-empty duplicate-free list from "
            f"{list(GUARDABLE_TOOLS)}, got {tools!r}"
        )
    regex = hook.get("path_regex")
    if not isinstance(regex, str) or not regex.strip():
        raise ProposalError("hook.path_regex must be non-empty text")
    problem = _ere_problem(regex)
    if problem is not None:
        raise ProposalError(f"hook.path_regex is not a valid ERE regex: {problem}")
    deny = hook.get("deny_message")
    if not isinstance(deny, str) or not deny.strip() or "\n" in deny:
        raise ProposalError(
            "hook.deny_message must be non-empty and one line (the pinned "
            "deny is a ONE-line stderr message, 08 §8.1)"
        )

    examples = data.get("examples")
    if not isinstance(examples, dict) or set(examples) != {"allow", "deny"}:
        raise ProposalError(
            "a hook proposal carries replay examples: "
            "examples: {allow: […], deny: […]} (M3-12)"
        )
    for verdict in ("allow", "deny"):
        cases = examples[verdict]
        if (
            not isinstance(cases, list)
            or not _HOOK_EXAMPLES_MIN <= len(cases) <= _HOOK_EXAMPLES_MAX
        ):
            raise ProposalError(
                f"examples.{verdict} must list {_HOOK_EXAMPLES_MIN}–"
                f"{_HOOK_EXAMPLES_MAX} example inputs (08 §4 replay row)"
            )
        for i, case in enumerate(cases):
            if (
                not isinstance(case, dict)
                or not isinstance(case.get("tool_input"), dict)
                or case.get("tool_name") not in tools
            ):
                raise ProposalError(
                    f"examples.{verdict}[{i}] must be "
                    "{tool_name: <one of hook.tools>, tool_input: {…}} — an "
                    "example naming an unguarded tool_name is vacuous (the "
                    "guard allows unguarded tools by design)"
                )

    script = data.get("script")
    if script is not None and (
        not isinstance(script, str) or not script.startswith("#!")
    ):
        raise ProposalError(
            "script must be the full shebang'd guard text (CLI-stamped; "
            "leave it out and run `self-learn proposal validate`)"
        )


def validate_proposal(data: dict) -> None:
    """02 §1 single-record proposal schema (incl. the M3 hook-destination
    extension). Raises :class:`ProposalError`."""
    if not isinstance(data, dict):
        raise ProposalError("proposal is not a mapping")
    dest = data.get("destination")
    if dest not in PROPOSAL_DESTINATIONS:
        raise ProposalError(
            f"destination must be one of {list(PROPOSAL_DESTINATIONS)}, got {dest!r}"
        )
    _validate_hook_extension(data)
    for key in ("rationale", "model"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProposalError(f"proposal needs non-empty {key}")
    if data.get("analyzed_at") is None:
        raise ProposalError("proposal needs analyzed_at")
    alternates = data.get("alternates")
    if alternates is not None:
        if not isinstance(alternates, list) or any(
            a not in PROPOSAL_DESTINATIONS for a in alternates
        ):
            raise ProposalError(
                f"alternates must be a list from {list(PROPOSAL_DESTINATIONS)}"
            )
    canon = data.get("already_canon")
    if canon is not None and not isinstance(canon, bool):
        raise ProposalError(f"already_canon must be a bool, got {canon!r}")
    reason = data.get("already_canon_reason")
    if reason is not None and not isinstance(reason, str):
        raise ProposalError("already_canon_reason must be text")
    sha = data.get("record_sha")
    if sha is not None and not (isinstance(sha, str) and SHA_ANCHOR_RE.match(sha)):
        raise ProposalError(f"record_sha must match sha256:<12 hex>, got {sha!r}")
    contradicts = data.get("contradicts")
    if contradicts is not None:
        # 11 §2.4/§8: structured field, never parsed out of rationale prose
        # (the already_canon precedent). Targets: record ids or canon
        # anchors; the human applies them via `link contradicts`.
        if (
            not isinstance(contradicts, list)
            or not contradicts
            or any(not isinstance(t, str) or not t.strip() for t in contradicts)
        ):
            raise ProposalError(
                "contradicts must be a non-empty list of record ids / "
                "canon anchors (11 §2.4)"
            )
    _validate_card(data)


def validate_merge_proposal(data: dict) -> None:
    """02 §1 merge-proposal schema. Raises :class:`ProposalError`."""
    if not isinstance(data, dict):
        raise ProposalError("merge proposal is not a mapping")
    cid = data.get("cluster_id")
    if not (isinstance(cid, str) and MERGE_ID_RE.match(cid)):
        raise ProposalError(f"cluster_id must match merge-<8 hex>, got {cid!r}")
    records = data.get("records")
    if (
        not isinstance(records, list)
        or len(records) < 2
        or any(not (isinstance(r, str) and RECORD_ID_RE.match(r)) for r in records)
    ):
        raise ProposalError("records must list ≥2 record ids")
    survivor = data.get("suggested_survivor")
    if survivor not in records:
        raise ProposalError(f"suggested_survivor {survivor!r} not in records")
    for key in ("rationale", "model"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProposalError(f"merge proposal needs non-empty {key}")
    if data.get("analyzed_at") is None:
        raise ProposalError("merge proposal needs analyzed_at")
    shas = data.get("record_shas")
    if not isinstance(shas, dict) or set(shas) != set(records):
        raise ProposalError("record_shas must map exactly the records listed")
    for rid, sha in shas.items():
        if not (isinstance(sha, str) and SHA_ANCHOR_RE.match(sha)):
            raise ProposalError(f"record_shas[{rid}] must match sha256:<12 hex>")
    _validate_card(data)  # collapse cards carry human-facing sections too


def write_proposal(home: Path, record_id: str, data: dict) -> Path:
    """Validate + write ``proposals/lrn-<id>.yaml`` beside the record."""
    validate_proposal(data)
    record_path = find_record_path(home, record_id)
    path = _proposal_path(record_path.parent.parent, record_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _dump_yaml(data, path)
    return path


def stamp_proposal(home: Path, record_id: str) -> Path:
    """Overwrite the proposal's ``record_sha`` with the sha-anchor of the
    record's CURRENT normalized body (T2's single normalization fn) — the
    CLI stamps, the model's emitted value is never trusted (08 §7.1).

    Hook proposals get a second stamp on the same principle (M2-21
    applied to executable bytes): ``script`` is GENERATED here from the
    structured compile input (``hook:`` block + the record's Trigger),
    overwriting anything the model wrote. Both attended validation
    (``proposal validate``) and the worker's run-sequence step (4) flow
    through this one function, so no path ships model-authored script
    text. Hand-tuning a guard = edit the hook block, re-validate; the
    route verb then applies the stamped bytes VERBATIM (M3-2)."""
    record_path = find_record_path(home, record_id)
    record = Record.from_path(record_path)
    path = _proposal_path(record_path.parent.parent, record_id)
    if not path.is_file():
        raise ProposalError(f"no proposal sibling for {record_id} at {path}")
    data = _load_yaml_map(path)
    data["record_sha"] = sha_anchor(record.body)
    if data.get("destination") == "hook":
        data["script"] = _generate_hook_script(record, data)
    _dump_yaml(data, path)
    return path


def _generate_hook_script(record: Record, data: dict) -> str:
    """The CLI-owned script generation for a hook proposal: structured
    input in, deterministic bash out (hook_compiler). The Trigger's first
    line seeds the M3-6 slug — hook routes therefore require a behavior
    record (a guard's firing condition IS the trigger, doctrine §6)."""
    from .hook_compiler import HookCompileError, generate_script

    if record.type != "behavior":
        raise ProposalError(
            f"hook destination needs a behavior record with a ## Trigger — "
            f"{record.id} is type {record.type!r}"
        )
    hook = data.get("hook")
    if not isinstance(hook, dict):
        raise ProposalError(
            f"proposal for {record.id} has destination hook but no hook "
            "block — nothing to compile (02 §1 hook extension)"
        )
    trigger = record_title(record)
    try:
        return generate_script(
            record.id,
            trigger,
            list(hook.get("tools") or []),
            str(hook.get("path_regex") or ""),
            str(hook.get("deny_message") or ""),
        )
    except HookCompileError as exc:
        raise ProposalError(str(exc)) from exc


def remove_proposal_siblings(home: Path, bucket_dir: Path, record_id: str) -> list[Path]:
    """08 §1 Proposal-lifecycle pin: at resolution, remove the record's own
    ``lrn-<id>.{yaml,diff}`` AND every ``merge-*.yaml`` whose ``records``
    list names it (a partial cluster is invalid). Returns removed paths."""
    pdir = bucket_dir / "proposals"
    removed: list[Path] = []
    for path in (pdir / f"{record_id}.yaml", pdir / f"{record_id}.diff"):
        if _remove_file(home, path):
            removed.append(path)
    if pdir.is_dir():
        for path in sorted(pdir.glob("merge-*.yaml")):
            try:
                data = _load_yaml_map(path)
            except ProposalError:
                continue  # unparseable → cannot name the id; worker policy owns it
            records = data.get("records")
            if isinstance(records, list) and record_id in records:
                if _remove_file(home, path):
                    removed.append(path)
    return removed


# ----------------------------------------------------- mutation operations


def resolve_record(
    home: Path,
    record_id: str,
    new_status: str,
    *,
    destination: str | None = None,
    by: str = "human",
    routed_at: str | None = None,
    superseded_by: str | None = None,
    note: str | None = None,
    follow_up: dict | None = None,
    reference_file: str | None = None,
    hook: dict | None = None,
    new_skill: str | None = None,
) -> list[Path]:
    """File-op half of a resolution: update frontmatter via T2's mutation
    API, ``git mv`` pending→resolved (fs move when untracked), and remove
    proposal siblings. Returns the exact touched-path list; deletions among
    them are pre-staged (git mv/rm) or were untracked.

    A record already in ``resolved/`` (corrective supersession of a routed
    lesson, 02 §2) is updated in place — no move."""
    if new_status not in RESOLUTION_STATUSES:
        raise LedgerOpsError(
            f"resolution status must be one of {sorted(RESOLUTION_STATUSES)}, "
            f"got {new_status!r} (defer via defer_record)"
        )
    if new_status == "routed" and not destination:
        raise LedgerOpsError("routing needs a destination")
    if new_status == "superseded" and superseded_by is None:
        raise LedgerOpsError(
            "supersession needs superseded_by (<record-id> or 'canon')"
        )

    if follow_up is not None and new_status != "routed":
        raise LedgerOpsError(
            "a follow-up rides the routing block (11 §2.1) — routed only"
        )
    if hook is not None and (new_status != "routed" or destination != "hook"):
        raise LedgerOpsError(
            "routing.hook rides a hook routing only (08 §8.1 apply pin)"
        )
    if new_skill is not None and (
        new_status != "routed" or destination != "new-skill"
    ):
        raise LedgerOpsError(
            "routing.new_skill rides a new-skill routing only (08 §8.1)"
        )
    if destination == "new-skill" and new_skill is None:
        raise LedgerOpsError(
            "a new-skill routing must name the skill (routing.new_skill) — "
            "recompile and the drift check read it to find the target"
        )
    path = find_record_path(home, record_id)
    record = Record.from_path(path)
    if new_status == "routed":
        routing = {
            "routed_at": routed_at if routed_at is not None else _now_iso(),
            "destination": destination,
            "by": by,
        }
        if reference_file is not None:
            # WHICH references file this landed in (audit 2026-07-16
            # BLOCKER 2): ``destination: reference`` alone is lossy, and
            # recompile / the drift check cannot repair a file they cannot
            # name. Absent on old records ⇒ the default LEARNINGS.md.
            routing["reference_file"] = reference_file
        if follow_up is not None:
            routing["follow_up"] = dict(follow_up)
        if hook is not None:
            # The APPROVED compile artifacts (M3-2): the exact script
            # bytes + their host-relative path, so drift checks and
            # `recompile` can re-apply what the human saw — never
            # regenerate from changed inputs.
            routing["hook"] = dict(hook)
        if new_skill is not None:
            routing["new_skill"] = new_skill
        record.set_routing(routing)
    if superseded_by is not None:
        record.set_superseded_by(superseded_by)
    record.set_status(new_status)
    if note is not None:
        record.set_resolution_note(note)

    bucket_dir = path.parent.parent
    touched: list[Path] = []
    if path.parent.name == "pending":
        resolved_dir = bucket_dir / "resolved"
        resolved_dir.mkdir(parents=True, exist_ok=True)
        dest_path = resolved_dir / path.name
        if _is_tracked(home, path):
            _git_ok(home, "mv", str(path), str(dest_path))
        else:
            path.rename(dest_path)
        touched.append(path)
    else:
        dest_path = path
    record.write(dest_path)
    touched.append(dest_path)
    touched.extend(remove_proposal_siblings(home, bucket_dir, record_id))
    return touched


def supersede_record(
    home: Path, old_id: str, superseded_by: str, *, note: str | None = None
) -> list[Path]:
    """Mark the old record superseded_by=<new-id|'canon'> and move it to
    ``resolved/`` (``'canon'`` = graduation, 02 §2)."""
    return resolve_record(
        home, old_id, "superseded", superseded_by=superseded_by, note=note
    )


def open_followups(home: Path) -> list[dict]:
    """Every OPEN follow-up (11 §2.1): resolved records whose routing block
    still carries ``follow_up``. Walks ``resolved/`` only — follow-ups ride
    routing, so pending records can never have one. NOT part of
    ``status --json --fast`` (that path is pinned pending/-only, 08 §7.1)."""
    out: list[dict] = []
    for bucket in discover_buckets(home):
        resolved = bucket.path / "resolved"
        if not resolved.is_dir():
            continue
        for path in sorted(resolved.glob("lrn-*.md")):
            try:
                record = Record.from_path(path)
            except RecordError:
                continue
            fu = record.follow_up
            # status gate (audit 2026-07-15): a superseded/graduated record
            # may still CARRY the block, but its lifecycle ended — the
            # successor owns any surviving upgrade plan.
            if fu is None or record.status != "routed":
                continue
            out.append(
                {
                    "id": record.id,
                    "bucket": bucket.name,
                    "action": fu.get("action"),
                    "unblocks_on": fu.get("unblocks_on"),
                    "note": fu.get("note"),
                    "routed_at": _ts_str((record.routing or {}).get("routed_at")),
                }
            )
    return out


def defer_record(home: Path, record_id: str, until=None) -> list[Path]:
    """Set deferral metadata in place — the record STAYS in ``pending/``;
    queue membership is computed from ``deferred_until`` (02 §2)."""
    path = find_record_path(home, record_id, statuses=("pending",))
    record = Record.from_path(path)
    if until is None:
        until = (
            datetime.now(timezone.utc) + timedelta(days=DEFAULT_DEFER_DAYS)
        ).strftime("%Y-%m-%d")
    elif isinstance(until, (datetime, date)):
        until = until.strftime("%Y-%m-%d")
    else:
        until = str(until)
    record.set_status("deferred")
    record.set_deferred_until(until)
    record.set_deferred_count((record.deferred_count or 0) + 1)
    record.write(path)
    return [path]


# ------------------------------------------------- queue + eligibility (THE)


@dataclass(frozen=True)
class QueueEntry:
    """One pending record on disk."""

    path: Path
    record: Record

    @property
    def bucket_dir(self) -> Path:
        return self.path.parent.parent

    @property
    def proposal_path(self) -> Path:
        return _proposal_path(self.bucket_dir, self.record.id)


def _load_pending(bucket: Bucket) -> tuple[list[QueueEntry], list[Path]]:
    good: list[QueueEntry] = []
    bad: list[Path] = []
    for path in bucket.pending_files():
        try:
            good.append(QueueEntry(path=path, record=Record.from_path(path)))
        except RecordError:
            bad.append(path)
    return good, bad


def queue(
    bucket: Bucket, *, include_deferred: bool = False, now: datetime | None = None
) -> list[QueueEntry]:
    """THE queue computation (02 §2, 08 §7.1 step 2): pending records minus
    future-``deferred_until``. ``include_deferred=True`` = the superset.
    Unparseable pending files are excluded (see :func:`unparseable_pending`)."""
    now = _now(now)
    entries, _bad = _load_pending(bucket)
    if include_deferred:
        return entries
    return [e for e in entries if not _deferred_hidden(e.record, now)]


def unparseable_pending(bucket: Bucket) -> list[Path]:
    """Pending files that fail record parsing — excluded from the queue;
    surfaced so CLI layers can warn instead of hiding corruption."""
    return _load_pending(bucket)[1]


def proposal_info(entry: QueueEntry) -> dict:
    """Proposal-sibling facts for one record: existence, freshness
    (CLI-computed hash match via the shared normalization fn), and the
    surfaced ``destination``/``already_canon`` fields (null/false when the
    sibling is absent; destination null when it is unparseable)."""
    info = {
        "has_proposal": False,
        "proposal_fresh": False,
        "destination": None,
        "already_canon": False,
    }
    path = entry.proposal_path
    if not path.is_file():
        return info
    info["has_proposal"] = True
    try:
        data = _load_yaml_map(path)
    except ProposalError:
        return info
    dest = data.get("destination")
    info["destination"] = dest if dest in PROPOSAL_DESTINATIONS else None
    info["already_canon"] = data.get("already_canon") is True
    try:
        validate_proposal(data)
    except ProposalError:
        return info  # schema-invalid: never fresh (08 §7.1 step 2)
    info["proposal_fresh"] = data.get("record_sha") == sha_anchor(entry.record.body)
    return info


def is_unanalyzed(entry: QueueEntry, *, now: datetime | None = None) -> bool:
    """THE eligibility predicate (08 §7.1 run-sequence step 2 / P2-4):
    pending, non-deferred, AND (no proposal file, or schema-invalid /
    unparseable proposal, or ``record_sha`` ≠ current normalized-body hash).
    ``list``/``status``/the worker all call this — never a second definition."""
    if _deferred_hidden(entry.record, _now(now)):
        return False
    return not proposal_info(entry)["proposal_fresh"]


# -------------------------------------------------------- CLI-facing views


def record_title(record: Record) -> str:
    """First line of the Trigger (behavior) / Fact (knowledge) section."""
    want = _TITLE_SECTION.get(record.type)
    in_section = False
    for line in record.body.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            in_section = m.group(1).strip() == want
            continue
        if in_section and line.strip():
            return line.strip()
    return ""


def _sort_key(entry: QueueEntry):
    dt = _to_dt(entry.record.created_at)
    return (dt or datetime.fromtimestamp(0, tz=timezone.utc), entry.record.id)


def list_items(
    home: Path, *, include_deferred: bool = False, now: datetime | None = None
) -> list[dict]:
    """`list --json` items in the pinned shape (08 §1 `--json`-stubs pin,
    G-3 hardening included), oldest first."""
    now = _now(now)
    entries: list[QueueEntry] = []
    for bucket in discover_buckets(home):
        entries.extend(queue(bucket, include_deferred=include_deferred, now=now))
    entries.sort(key=_sort_key)
    items = []
    for entry in entries:
        record = entry.record
        info = proposal_info(entry)
        items.append(
            {
                "id": record.id,
                "type": record.type,
                "scope": record.scope,
                "kind": record.kind,
                "status": record.status,
                "created_at": _ts_str(record.created_at),
                "age_days": _age_days(record.created_at, now),
                "deferred_until": _ts_str(record.deferred_until),
                "sightings": record.sightings,
                "has_proposal": info["has_proposal"],
                "title": record_title(record),
                "proposal_fresh": info["proposal_fresh"],
                "destination": info["destination"],
                "already_canon": info["already_canon"],
            }
        )
    return items


def status_infos(home: Path, *, now: datetime | None = None) -> list[dict]:
    """`status --json` bucket rows: pending/oldest computed over the queue
    (deferred excluded from all counts, 02 §2); ``unanalyzed`` = the shared
    eligibility count."""
    now = _now(now)
    infos = []
    for bucket in discover_buckets(home):
        entries = queue(bucket, now=now)
        ages = [_age_days(e.record.created_at, now) for e in entries]
        infos.append(
            {
                "bucket": bucket.name,
                "scope": bucket.scope,
                "pending": len(entries),
                "oldest_days": max(ages) if ages else None,
                "unanalyzed": sum(1 for e in entries if is_unanalyzed(e, now=now)),
            }
        )
    return infos
