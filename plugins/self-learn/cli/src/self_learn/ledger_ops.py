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

from . import hosts as hosts_mod
from .ledger import Bucket, discover_buckets, home_state, home_state_message
from .normalize import sha_anchor
from .records import RECORD_ID_RE, Record, RecordError
from .skill_scaffold import SkillScaffoldError, validate_skill_name

__all__ = [
    "DEFAULT_DEFER_DAYS",
    "LedgerOpsError",
    "ProposalError",
    "PROPOSAL_DESTINATIONS",
    "QueueEntry",
    "TRACE_FLAGS",
    "TRACE_FS_VERDICTS",
    "TRACE_OUTCOMES",
    "TRACE_RECOMMENDATIONS",
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
    "rehome_record",
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

#: u-schema-decision-trace §3.1 Schema-1: the `gates` mapping's closed key
#: set — every key required, no others admitted (D1). Not exported: it is
#: Schema-1's structural spine, not one of the four Set-F/R/O/V constants
#: (§3.3, §6-D2).
TRACE_GATE_KEYS = ("g0", "t1", "t2", "t3", "t3a", "t4", "tn", "e1", "outcome")

#: Set-F (§3.2): the closed decision-trace flag set. Eight values;
#: `pathed-unbuilt` is required by r2 §1.6's PATHED transition rule even
#: though r2 §1.2 omits it — resolved in favour of the rule that has to
#: run (§8-C1). Tests iterate this tuple; they never hardcode a copy.
TRACE_FLAGS = (
    "near-cluster",
    "cluster-indeterminate",
    "evidence-gap",
    "rehome-suggested",
    "no-cheap-surface",
    "scope-mismatch",
    "consider-local",
    "pathed-unbuilt",
)

#: Set-R (§3.3): the `recommendation` enum.
TRACE_RECOMMENDATIONS = ("route", "reject", "defer", "graduate")

#: Set-O (§3.3): the `gates.outcome` enum. Defined HERE, not in the future
#: `gates.py` (U-table) — the validator needs the set before that module
#: exists; U-table imports TRACE_OUTCOMES rather than redefining `CLS`
#: (§8-O1).
TRACE_OUTCOMES = (
    "HOOK",
    "ALWAYS",
    "PATHED",
    "SKILL",
    "DEMAND",
    "NEW_SKILL",
    "REJECT",
    "DEFER",
    "GRADUATE",
)

#: Set-V (§3.3): the `*.fs.verdict` enum.
TRACE_FS_VERDICTS = ("SILENT", "COSTLY", "LOUD_CHEAP", "INDETERMINATE")

#: §3.4: the quote-containment floor, measured on the FLATTENED quote (not
#: raw length — E5's whitespace twin pins this). Calibrated on `"no error"`
#: (8 chars), the shortest marker in r2 §3's silence lexicon (§6-D6).
_QUOTE_MIN_CHARS = 8

#: X3 / C4 (§3.1a, §3.4a): the literal `roster_sha` value the T3
#: degradation path writes when no roster composer exists yet.
ROSTER_UNAVAILABLE = "unavailable"

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


#: FW-31/Y-22 lint block: enum, never a numeric score (counted-not-modeled,
#: worker-ecology §4.3; routing-doctrine.md lint subsection is the source
#: of judgment for these three fields).
_LINT_TRIGGER_RECOGNIZABLE_VALUES = ("yes", "partial", "no")


def _validate_lint(data: dict) -> None:
    """02 §1 / FW-31 optional ``lint:`` block (behavior records only —
    knowledge records have no firing moment to recognize). Symmetric with
    :func:`_validate_hook_extension`: absence is always valid; presence is
    shape-checked field by field and any malformed field is a
    :class:`ProposalError`. ``trigger_recognizable`` is an enum,
    ``why_present`` a bool, ``sharpening`` an optional non-empty string —
    never a numeric/confidence score (14 §6; worker-ecology §4.3)."""
    lint = data.get("lint")
    if lint is None:
        return
    if not isinstance(lint, dict):
        raise ProposalError("lint must be a mapping")
    trigger = lint.get("trigger_recognizable")
    if trigger not in _LINT_TRIGGER_RECOGNIZABLE_VALUES:
        raise ProposalError(
            "lint.trigger_recognizable must be one of "
            f"{list(_LINT_TRIGGER_RECOGNIZABLE_VALUES)}, got {trigger!r}"
        )
    why_present = lint.get("why_present")
    if not isinstance(why_present, bool):
        raise ProposalError(f"lint.why_present must be a bool, got {why_present!r}")
    sharpening = lint.get("sharpening")
    if sharpening is not None and (
        not isinstance(sharpening, str) or not sharpening.strip()
    ):
        raise ProposalError("lint.sharpening must be non-empty text when present")


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
    # key=repr (S6): YAML mapping keys need not be strings — a `hook:`
    # block with 2+ unknown keys of mutually incomparable types (e.g.
    # `{1: x, zzz: y}`) makes bare `sorted()` raise `TypeError`, which is
    # neither `ProposalError` nor `LedgerOpsError` and escapes every
    # caller's `except ProposalError` (FW-63). `repr()` is total on any
    # object and stable enough for a deterministic error message; the
    # sort order itself carries no semantic meaning here.
    unknown = sorted(set(hook) - set(_HOOK_KEYS), key=repr)
    if unknown:
        raise ProposalError(f"unknown hook key(s) {unknown} — allowed: {list(_HOOK_KEYS)}")
    # Paired with `unknown` above: currently safe (both operands are
    # `str`-only, drawn from `_HOOK_KEYS`), but the pairing invites the
    # same bug if this ever sorts a set with a non-`str` operand — same
    # `key=repr` fix applied defensively.
    missing = sorted(set(_HOOK_KEYS) - set(hook), key=repr)
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


# --------------------------------------------------- decision trace (§3)


def _flatten_quote(text: str) -> str:
    """§3.4's COMPARISON normalization (never `normalize.normalize_body`,
    which HASHES and is line-based by design): collapse every run of
    whitespace, including newlines, to a single space, then strip. A quote
    copied out of a wrapped record body and re-wrapped by the model must
    still be found — a validator that refuses honest evidence is worse
    than none. Local to this module; not exported (§6-D4)."""
    return re.sub(r"\s+", " ", text).strip()


def _translate_glob_segment(seg: str) -> str:
    """One `/`-delimited, non-`**` segment → its regex piece. `*` → any run
    of non-separator chars, `?` → one non-separator char, `[...]` → a
    passed-through character class (only a leading `!` negates; a leading
    `^` is a literal member and is actively escaped to `\\^`, because
    Python's `re` negates on `^` unaided — §3.4a), an unbalanced `[` → an
    escaped literal, never an exception; everything else `re.escape`d.

    The class BODY is also sanitized before being passed through (code
    gate F1/F2, r3 delta): a literal backslash is escaped so a body
    ending in `\\` cannot leave the class unterminated (a *balanced*
    glob class whose body ends in `\\` — `[a\\]` — would otherwise emit
    an unterminated `re` class and `re.compile` would raise something
    that is not a :class:`ProposalError`, which is exactly the escape S6
    forbids), and `&`/`~`/`|` are escaped because `re` has announced
    those will gain set-operation meaning inside a class — both are
    plain literal members to `glob`/`fnmatch`, so leaving them unescaped
    is the false-refusal direction (F2) this section exists to avoid."""
    out: list[str] = []
    i, n = 0, len(seg)
    while i < n:
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and seg[j] == "!":
                j += 1
            if j < n and seg[j] == "]":
                j += 1
            while j < n and seg[j] != "]":
                j += 1
            if j >= n:
                # Unbalanced `[` — an escaped literal, never an exception.
                out.append(re.escape("["))
                i += 1
                continue
            stuff = seg[i + 1 : j]
            stuff = stuff.replace("\\", "\\\\")
            stuff = re.sub(r"([&~|])", r"\\\1", stuff)
            if stuff.startswith("!"):
                stuff = "^" + stuff[1:]
            elif stuff.startswith("^") or stuff.startswith("["):
                stuff = "\\" + stuff
            out.append(f"[{stuff}]")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


@lru_cache(maxsize=256)
def _compile_glob_pattern_cached(pattern: str) -> tuple[re.Pattern[str] | None, str | None]:
    """§3.4a's hand-rolled `**`-aware translator — `re` only, never
    `fnmatch`/`glob` (S3/S4/D10/D11; both stdlib alternatives that would
    get this right, `glob.translate`/`PurePath.full_match`, are Python
    3.13-only and this project's floor is 3.11). A `**` segment becomes
    `(?:[^/]+/)*` (zero or more levels) when non-final — which already
    supplies its own trailing separator, so none is emitted after it — and
    `.*` when final.

    Consecutive `**` segments are collapsed to one BEFORE translation, the
    way the oracle (`glob.translate`) does it. This is language-preserving
    — `(?:X)*(?:X)*` matches exactly what `(?:X)*` matches (Kleene-star
    idempotence) — but not backtracking-cost-preserving: left uncollapsed,
    `re` explores every way of splitting a span across N adjacent
    `(?:[^/]+/)*` groups before concluding a non-match, which is
    exponential in N. Measured (FW-57): 12 consecutive `**` segments
    against a 24-segment non-matching path took ~40s uncollapsed vs. ~2µs
    through `glob.translate`; collapsed here, the same call is
    microseconds. Scoped narrowly to the inter-segment case — the
    analogous intra-segment blowup (`*a*a*a…*` against a long non-matching
    string) is NOT touched, because `glob.translate` is equally slow on
    that pattern shape (measured, not assumed): it is not a divergence
    from the oracle, so it is not this function's bug to fix.

    Memoized, including the failure case (both returned, never raised —
    see `_compile_glob_pattern` below): the `re.Pattern` CONSTRUCTION runs
    on the eligibility hot path (S4) and is what this caches. It does
    NOT make `_glob_match` itself fast on repeat calls: `.match()` runs
    fresh every time regardless of the cache, so a pattern whose match is
    itself slow (the intra-segment blowup this docstring declines to fix,
    above) stays exactly as slow on every call — measured, three
    identical `_glob_match` calls against such a pattern: 0.516s / 0.495s
    / 0.491s, not the ~0s a reader could assume "memoized" promises.
    Before this fix, an `lru_cache`d function that raises was not
    memoized even on the COMPILE side of the raising path —
    `cache_info()` after N identical failing calls previously read
    `hits=0, misses=N, currsize=0`, so a broken pattern on one record was
    re-translated on every `list` for every record, every time. `re.error`
    is caught here (code gate F1, r3 delta) — not because
    `_translate_glob_segment`'s own sanitizing is known to still be
    incomplete, but because S6 must hold for ANY future defect in this
    translator, not just the one measured today: a malformed trace on
    somebody else's record must never traceback `self-learn list` with
    something other than ProposalError."""
    segments = pattern.split("/")
    collapsed: list[str] = []
    for seg in segments:
        if seg == "**" and collapsed and collapsed[-1] == "**":
            continue
        collapsed.append(seg)
    segments = collapsed
    n = len(segments)
    pieces: list[tuple[str, bool]] = []  # (regex, already_supplies_sep)
    for idx, seg in enumerate(segments):
        if seg == "**":
            if idx == n - 1:
                pieces.append((".*", False))
            else:
                pieces.append(("(?:[^/]+/)*", True))
        else:
            pieces.append((_translate_glob_segment(seg), False))
    parts: list[str] = []
    for idx, (piece, _supplies) in enumerate(pieces):
        if idx > 0 and not pieces[idx - 1][1]:
            parts.append("/")
        parts.append(piece)
    try:
        return re.compile(f"(?s:{''.join(parts)})\\Z"), None
    except re.error as exc:
        return None, str(exc)


def _compile_glob_pattern(pattern: str) -> re.Pattern[str]:
    """Thin raising wrapper over :func:`_compile_glob_pattern_cached` (see
    its docstring for the translation rules and the `**`-collapsing fix).
    Kept as a separate, un-memoized function so the `raise` — needed for
    the public `ProposalError`-only contract (S6) — never sits inside the
    `lru_cache`d call and defeats memoization on the failure path."""
    compiled, error = _compile_glob_pattern_cached(pattern)
    if error is not None:
        raise ProposalError(f"rules_paths pattern {pattern!r} is not translatable: {error}")
    # `_compile_glob_pattern_cached` always pairs a non-None `compiled`
    # with a None `error` — the type checker can't see that correlation
    # through the tuple return, so this is the narrowing, not a runtime
    # possibility.
    assert compiled is not None
    return compiled


def _glob_match(path: str, pattern: str) -> bool:
    """§3.4a: a PURE string relation — no filesystem, no `root_dir`, no cwd
    — measured equivalent to `glob.glob(pattern, root_dir=…,
    recursive=True, include_hidden=True)` over files (not directories)
    across 13 patterns, 0 mismatches (F1b). Deliberately does NOT inherit
    `glob`'s absolute-path `root_dir`-ignoring fail-open (§8-O6)."""
    return _compile_glob_pattern(pattern).match(path) is not None


def _check_evidence(
    evidence,
    path: str,
    *,
    required: bool,
    quote_source: str,
    record_text: str | None,
) -> None:
    """One `evidence` leaf (§3.1 Schema-1a): null/absent iff not required;
    otherwise a non-empty string whose flattened form is at least
    `_QUOTE_MIN_CHARS` long (measured on both required and optional
    fields — the floor is a shape rule, not a required-ness rule). `""` is
    never valid — only `None` encodes "absent" (§3.4). RECORD-sourced
    quotes are containment-checked against `record_text` when supplied;
    TARGET-sourced quotes are shape-only in this unit (§3.7 item 1)."""
    if evidence is None:
        if required:
            raise ProposalError(f"{path} is required here and is missing")
        return
    if not isinstance(evidence, str) or not evidence:
        raise ProposalError(f"{path} must be non-empty text or null, got {evidence!r}")
    flattened = _flatten_quote(evidence)
    if len(flattened) < _QUOTE_MIN_CHARS:
        raise ProposalError(
            f"{path} is shorter than the _QUOTE_MIN_CHARS ({_QUOTE_MIN_CHARS}) "
            f"floor once flattened: {evidence!r}"
        )
    if quote_source == "RECORD" and record_text is not None:
        if flattened not in _flatten_quote(record_text):
            raise ProposalError(
                f"{path} is not contained in the record it claims to quote: "
                f"{evidence!r}"
            )


def _mapping(value, path: str) -> dict:
    """Type-check-before-index (S6): every level of the trace is verified
    a mapping before anything is read out of it, so a malformed shape
    raises :class:`ProposalError` and never a bare `TypeError`/`KeyError`
    (A7) — `proposal_info` catches only `ProposalError` and `queue()`
    catches nothing at all."""
    if not isinstance(value, dict):
        raise ProposalError(f"{path} must be a mapping, got {value!r}")
    return value


def _check_fs_verdict(
    fs: dict, path: str, record_text: str | None
) -> None:
    """Shared by `t3a.fs` and `t4.fs`: verdict in the closed Set-V, evidence
    required unless the verdict is `INDETERMINATE` (D3)."""
    verdict = fs.get("verdict")
    if verdict not in TRACE_FS_VERDICTS:
        raise ProposalError(
            f"{path}.verdict must be one of {list(TRACE_FS_VERDICTS)}, "
            f"got {verdict!r}"
        )
    _check_evidence(
        fs.get("evidence"),
        f"{path}.evidence",
        required=(verdict != "INDETERMINATE"),
        quote_source="RECORD",
        record_text=record_text,
    )


def _validate_gates(data: dict, *, record_text: str | None = None) -> None:
    """u-schema-decision-trace §3: the decision trace — `gates`, `flags`,
    `recommendation` — validated together (D3: X3 couples the flag set to
    a gate answer, so splitting them invites a caller that runs one and
    not the others). Absent-is-valid throughout (S1): every one of the
    three top-level keys may be omitted, independently or together.

    Containment (§3.4) runs iff `record_text` is supplied — this function
    performs NO filesystem I/O itself (S4); callers decide whether/what to
    load. Raises only :class:`ProposalError`, on every input including
    malformed ones (S6) — never mutates `data` (C3)."""

    # ---- flags (Set-F, §3.2) -------------------------------------------
    flags = data.get("flags")
    if flags is not None:
        if not isinstance(flags, list):
            raise ProposalError(f"flags must be a list, got {flags!r}")
        for flag in flags:
            if not isinstance(flag, str) or flag not in TRACE_FLAGS:
                raise ProposalError(
                    f"flag {flag!r} is outside the closed set {list(TRACE_FLAGS)}"
                )
        if len(set(flags)) != len(flags):
            raise ProposalError(f"flags must not contain duplicates: {flags!r}")

    # ---- recommendation (Set-R, §3.3) ----------------------------------
    recommendation = data.get("recommendation")
    if recommendation is not None and recommendation not in TRACE_RECOMMENDATIONS:
        raise ProposalError(
            f"recommendation must be one of {list(TRACE_RECOMMENDATIONS)}, "
            f"got {recommendation!r}"
        )

    # ---- gates (Schema-1, §3.1) -----------------------------------------
    gates = data.get("gates")
    if gates is None:
        return
    if not isinstance(gates, dict):
        raise ProposalError(f"gates must be a mapping, got {gates!r}")
    gate_keys = set(gates)
    # key=repr (S6): YAML mapping keys need not be strings — a `gates:`
    # block with 2+ unknown keys of mutually incomparable types (e.g.
    # `{1: x, zzz: y}`) makes bare `sorted()` raise `TypeError`, which is
    # neither `ProposalError` nor `LedgerOpsError` and escapes every
    # caller's `except ProposalError` (FW-63: `self-learn list` tracebacks
    # for every record, not just the malformed one). `repr()` is total on
    # any object and stable enough for a deterministic error message; the
    # sort order itself carries no semantic meaning here.
    unknown = sorted(gate_keys - set(TRACE_GATE_KEYS), key=repr)
    if unknown:
        raise ProposalError(
            f"gates has unknown key(s) {unknown} — allowed: {list(TRACE_GATE_KEYS)}"
        )
    # Paired with `unknown` above: currently safe (both operands are
    # `str`-only, drawn from `TRACE_GATE_KEYS`), but the pairing invites
    # the same bug if this ever sorts a set with a non-`str` operand —
    # same `key=repr` fix applied defensively.
    missing = sorted(set(TRACE_GATE_KEYS) - gate_keys, key=repr)
    if missing:
        raise ProposalError(
            f"gates is missing key(s) {missing} — required: {list(TRACE_GATE_KEYS)}"
        )

    # -- g0 ---------------------------------------------------------------
    g0 = _mapping(gates["g0"], "gates.g0")
    for leg in ("reject", "defer"):
        leg_path = f"gates.g0.{leg}"
        node = _mapping(g0.get(leg), leg_path)
        answer = node.get("answer")
        if answer not in ("yes", "no"):
            raise ProposalError(
                f"{leg_path}.answer must be 'yes' or 'no', got {answer!r}"
            )
        _check_evidence(
            node.get("evidence"),
            f"{leg_path}.evidence",
            required=(answer == "yes"),
            quote_source="RECORD",
            record_text=record_text,
        )
    canon_path = "gates.g0.canon"
    canon = _mapping(g0.get("canon"), canon_path)
    canon_answer = canon.get("answer")
    if canon_answer not in ("yes", "no"):
        raise ProposalError(
            f"{canon_path}.answer must be 'yes' or 'no', got {canon_answer!r}"
        )
    _check_evidence(
        canon.get("evidence"),
        f"{canon_path}.evidence",
        required=(canon_answer == "yes"),
        quote_source="TARGET",
        record_text=record_text,
    )
    canon_target = canon.get("target")
    if canon_answer == "yes" and (
        not isinstance(canon_target, str) or not canon_target
    ):
        raise ProposalError(
            f"{canon_path}.target must be non-empty text when answer is yes"
        )

    # -- t1 -----------------------------------------------------------
    t1 = _mapping(gates["t1"], "gates.t1")
    attempted = t1.get("attempted")
    if not isinstance(attempted, bool):
        raise ProposalError(
            f"gates.t1.attempted must be a bool, got {attempted!r}"
        )

    fs_shaped_path = "gates.t1.field_shaped"
    field_shaped = _mapping(t1.get("field_shaped"), fs_shaped_path)
    fs_answer = field_shaped.get("answer")
    if fs_answer not in ("yes", "no"):
        raise ProposalError(
            f"{fs_shaped_path}.answer must be 'yes' or 'no', got {fs_answer!r}"
        )
    _check_evidence(
        field_shaped.get("evidence"),
        f"{fs_shaped_path}.evidence",
        required=True,  # required BOTH ways (§3.1 Schema-1a)
        quote_source="RECORD",
        record_text=record_text,
    )

    sep_path = "gates.t1.separable"
    separable = _mapping(t1.get("separable"), sep_path)
    sep_answer = separable.get("answer")
    if sep_answer not in ("yes", "no", None):
        raise ProposalError(
            f"{sep_path}.answer must be 'yes', 'no' or null, got {sep_answer!r}"
        )
    _check_evidence(
        separable.get("evidence"),
        f"{sep_path}.evidence",
        required=False,
        quote_source="RECORD",
        record_text=record_text,
    )

    cb_path = "gates.t1.cost_bearing"
    cost_bearing = _mapping(t1.get("cost_bearing"), cb_path)
    cb_answer = cost_bearing.get("answer")
    if cb_answer not in ("yes", "no", None):
        raise ProposalError(
            f"{cb_path}.answer must be 'yes', 'no' or null, got {cb_answer!r}"
        )
    _check_evidence(
        cost_bearing.get("evidence"),
        f"{cb_path}.evidence",
        required=(cb_answer == "yes"),
        quote_source="RECORD",
        record_text=record_text,
    )

    # -- t2 -----------------------------------------------------------
    t2_path = "gates.t2"
    t2 = _mapping(gates["t2"], t2_path)
    t2_answer = t2.get("answer")
    if t2_answer not in ("yes", "no"):
        raise ProposalError(
            f"{t2_path}.answer must be 'yes' or 'no', got {t2_answer!r}"
        )
    _check_evidence(
        t2.get("evidence"),
        f"{t2_path}.evidence",
        required=True,  # required BOTH ways (§3.1 Schema-1a)
        quote_source="RECORD",
        record_text=record_text,
    )
    match_path_value = t2.get("match_path")
    if t2_answer == "yes":
        if not isinstance(match_path_value, str) or not match_path_value:
            raise ProposalError(
                f"{t2_path}.match_path must be non-empty text when answer is yes"
            )
        # X1: the t2 positive control — match_path's whole semantic
        # content is "a path the proposed globs actually match", so
        # requiring rules_paths is a shape requirement of the trace
        # (§3.1, X1), and the check must never pass vacuously (F2).
        rules_paths = data.get("rules_paths")
        if (
            not isinstance(rules_paths, list)
            or not rules_paths
            or any(not isinstance(p, str) or not p for p in rules_paths)
        ):
            raise ProposalError(
                f"{t2_path}.answer is 'yes' but rules_paths is missing/empty "
                "— match_path cannot be checked against zero globs (X1)"
            )
        if not any(_glob_match(match_path_value, p) for p in rules_paths):
            raise ProposalError(
                f"{t2_path}.match_path {match_path_value!r} matches none of "
                f"rules_paths {rules_paths!r} (X1)"
            )

    # -- t3 -----------------------------------------------------------
    t3_path = "gates.t3"
    t3 = _mapping(gates["t3"], t3_path)
    t3_answer = t3.get("answer")
    if t3_answer not in ("yes", "no"):
        raise ProposalError(
            f"{t3_path}.answer must be 'yes' or 'no', got {t3_answer!r}"
        )
    owner = t3.get("owner")
    if t3_answer == "yes":
        if not isinstance(owner, str) or not owner:
            raise ProposalError(
                f"{t3_path}.owner must be non-empty text when answer is yes"
            )
    elif owner is not None:
        raise ProposalError(f"{t3_path}.owner must be null when answer is no")
    scan_terms = t3.get("scan_terms")
    if t3_answer == "no":
        if (
            not isinstance(scan_terms, list)
            or not scan_terms
            or any(not isinstance(s, str) or not s for s in scan_terms)
        ):
            raise ProposalError(
                f"{t3_path}.scan_terms must be a non-empty list of "
                "non-empty text when answer is no"
            )
    elif scan_terms is not None:
        raise ProposalError(
            f"{t3_path}.scan_terms must be null when answer is yes"
        )
    roster_sha = t3.get("roster_sha")
    if roster_sha != ROSTER_UNAVAILABLE and not (
        isinstance(roster_sha, str) and SHA_ANCHOR_RE.match(roster_sha)
    ):
        raise ProposalError(
            f"{t3_path}.roster_sha must match sha256:<12hex> or be "
            f"{ROSTER_UNAVAILABLE!r}, got {roster_sha!r}"
        )
    if roster_sha == ROSTER_UNAVAILABLE:
        # X3 — roster honesty: a missing roster cannot support a "yes"
        # judgment, and the admission must be visible on the card.
        if t3_answer != "no":
            raise ProposalError(
                f"{t3_path}.roster_sha is {ROSTER_UNAVAILABLE!r} but answer "
                f"is {t3_answer!r} — a missing roster cannot support a "
                "'yes' judgment (X3)"
            )
        if not flags or "evidence-gap" not in flags:
            raise ProposalError(
                f"{t3_path}.roster_sha is {ROSTER_UNAVAILABLE!r} — flags "
                "must include 'evidence-gap' to admit the degraded roster "
                "(X3)"
            )

    # -- t3a ------------------------------------------------------------
    t3a_path = "gates.t3a"
    t3a_raw = gates["t3a"]
    if t3_answer == "yes":
        if t3a_raw is None:
            raise ProposalError(
                f"{t3a_path} must be non-null when gates.t3.answer is 'yes'"
            )
    elif t3a_raw is not None:
        raise ProposalError(
            f"{t3a_path} must be null when gates.t3.answer is 'no'"
        )
    if t3a_raw is not None:
        t3a = _mapping(t3a_raw, t3a_path)
        dbr_path = f"{t3a_path}.depth_behind_rule"
        dbr = _mapping(t3a.get("depth_behind_rule"), dbr_path)
        dbr_answer = dbr.get("answer")
        if dbr_answer not in ("yes", "no"):
            raise ProposalError(
                f"{dbr_path}.answer must be 'yes' or 'no', got {dbr_answer!r}"
            )
        _check_evidence(
            dbr.get("evidence"),
            f"{dbr_path}.evidence",
            required=(dbr_answer == "yes"),
            quote_source="TARGET",
            record_text=record_text,
        )
        dbr_target = dbr.get("target")
        if dbr_answer == "yes" and (
            not isinstance(dbr_target, str) or not dbr_target
        ):
            raise ProposalError(
                f"{dbr_path}.target must be non-empty text when answer is yes"
            )
        _check_fs_verdict(
            _mapping(t3a.get("fs"), f"{t3a_path}.fs"),
            f"{t3a_path}.fs",
            record_text,
        )

    # -- tn (validated before t4: t4's presence rule reads tn.answer) ---
    tn_path = "gates.tn"
    tn = _mapping(gates["tn"], tn_path)
    tn_answer = tn.get("answer")
    if tn_answer not in ("yes", "no", "indeterminate"):
        raise ProposalError(
            f"{tn_path}.answer must be 'yes', 'no' or 'indeterminate', "
            f"got {tn_answer!r}"
        )
    terms = tn.get("terms")
    if not isinstance(terms, list) or any(
        not isinstance(t, str) or not t for t in terms
    ):
        raise ProposalError(
            f"{tn_path}.terms must be a list of non-empty text (may be empty)"
        )
    members = tn.get("members")
    if not isinstance(members, list) or any(
        not isinstance(m, str) or not RECORD_ID_RE.match(m) for m in members
    ):
        raise ProposalError(
            f"{tn_path}.members must be a list of record ids matching "
            f"{RECORD_ID_RE.pattern}"
        )
    n_members = len(members)
    if tn_answer == "yes" and n_members < 2:
        raise ProposalError(
            f"{tn_path}.members must have ≥2 entries when answer is "
            f"'yes', got {n_members}"
        )
    if tn_answer == "no" and n_members > 1:
        raise ProposalError(
            f"{tn_path}.members must have ≤1 entry when answer is "
            f"'no', got {n_members}"
        )
    proposed_name = tn.get("proposed_name")
    if tn_answer == "yes":
        if not isinstance(proposed_name, str) or not proposed_name:
            raise ProposalError(
                f"{tn_path}.proposed_name is required when answer is yes"
            )
        try:
            validate_skill_name(proposed_name)
        except SkillScaffoldError as exc:
            raise ProposalError(
                f"{tn_path}.proposed_name {proposed_name!r}: {exc}"
            ) from exc
    elif proposed_name is not None:
        raise ProposalError(
            f"{tn_path}.proposed_name must be null unless answer is 'yes'"
        )

    # -- t4 -----------------------------------------------------------
    t4_path = "gates.t4"
    t4_raw = gates["t4"]
    tn_is_yes = tn_answer == "yes"
    if t2_answer == "yes" or tn_is_yes:
        if t4_raw is not None:
            raise ProposalError(
                f"{t4_path} must be null when t2.answer is 'yes' or "
                "tn.answer is 'yes'"
            )
    elif t2_answer == "no" and t3_answer == "no" and not tn_is_yes:
        if t4_raw is None:
            raise ProposalError(
                f"{t4_path} must be non-null when t2 and t3 both answered "
                "'no' and tn did not answer 'yes'"
            )
    # else: t3.answer == "yes" (t2 == "no", tn != "yes") — scope-free
    # residual (§6-D5): t4 is free either way, the scope this validator
    # does not have decides which table row actually applies.
    if t4_raw is not None:
        t4 = _mapping(t4_raw, t4_path)
        dbr_path = f"{t4_path}.depth_behind_rule"
        dbr = _mapping(t4.get("depth_behind_rule"), dbr_path)
        dbr_answer = dbr.get("answer")
        if dbr_answer not in ("yes", "no"):
            raise ProposalError(
                f"{dbr_path}.answer must be 'yes' or 'no', got {dbr_answer!r}"
            )
        _check_evidence(
            dbr.get("evidence"),
            f"{dbr_path}.evidence",
            required=(dbr_answer == "yes"),
            quote_source="TARGET",
            record_text=record_text,
        )
        dbr_target = dbr.get("target")
        if dbr_answer == "yes" and (
            not isinstance(dbr_target, str) or not dbr_target
        ):
            raise ProposalError(
                f"{dbr_path}.target must be non-empty text when answer is yes"
            )

        cm_path = f"{t4_path}.conduct_mode"
        cm = _mapping(t4.get("conduct_mode"), cm_path)
        cm_answer = cm.get("answer")
        if cm_answer not in ("yes", "no"):
            raise ProposalError(
                f"{cm_path}.answer must be 'yes' or 'no', got {cm_answer!r}"
            )
        _check_evidence(
            cm.get("evidence"),
            f"{cm_path}.evidence",
            required=(cm_answer == "yes"),
            quote_source="RECORD",
            record_text=record_text,
        )
        _check_fs_verdict(
            _mapping(t4.get("fs"), f"{t4_path}.fs"),
            f"{t4_path}.fs",
            record_text,
        )

    # -- e1 -----------------------------------------------------------
    e1_path = "gates.e1"
    e1 = _mapping(gates["e1"], e1_path)
    sightings = e1.get("sightings")
    if (
        not isinstance(sightings, int)
        or isinstance(sightings, bool)
        or sightings < 1
    ):
        raise ProposalError(
            f"{e1_path}.sightings must be an int ≥ 1, got {sightings!r}"
        )
    post_demand = e1.get("post_demand_recurrence")
    if not isinstance(post_demand, bool):
        raise ProposalError(
            f"{e1_path}.post_demand_recurrence must be a bool, got {post_demand!r}"
        )

    # -- outcome --------------------------------------------------------
    outcome = gates.get("outcome")
    if outcome not in TRACE_OUTCOMES:
        raise ProposalError(
            f"gates.outcome must be one of {list(TRACE_OUTCOMES)}, got {outcome!r}"
        )


def validate_proposal(data: dict, *, record_text: str | None = None) -> None:
    """02 §1 single-record proposal schema (incl. the M3 hook-destination
    extension), plus the optional u-schema-decision-trace (§3): `gates`,
    `flags`, `recommendation`. ``record_text`` is keyword-only with a
    ``None`` default (S2 — every existing positional call site,
    ``validate_proposal(data)``, keeps working verbatim) and is used ONLY
    to containment-check RECORD-sourced trace quotes (§3.4); when omitted,
    trace shape/enums/required-ness still validate but containment does
    not run (§3.5). Raises :class:`ProposalError`."""
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
    _validate_rules_fields(data)
    _validate_lint(data)
    _validate_card(data)
    _validate_gates(data, record_text=record_text)


def _validate_rules_fields(data: dict) -> None:
    """A2 §4.3: the ``variant``/``rules_topic``/``rules_paths`` proposal
    fields — optional, validated only when present (P-A6: a
    variant-absent proposal validates unchanged). ``variant`` is
    meaningful only on a ``claude-md`` destination (R-2: rules/local are
    a SCOPE PARAMETERIZATION of claude-md, never a fifth destination)."""
    variant = data.get("variant")
    if variant is None:
        return
    if variant not in ("rules", "local"):
        raise ProposalError(
            f"variant must be 'rules' or 'local', got {variant!r}"
        )
    if data.get("destination") != "claude-md":
        raise ProposalError(
            "variant only applies to a claude-md destination (R-2: rules "
            "is a scope parameterization of claude-md, not a new "
            "destination)"
        )
    rules_topic = data.get("rules_topic")
    rules_paths = data.get("rules_paths")
    if variant == "rules":
        if not isinstance(rules_topic, str) or not rules_topic:
            raise ProposalError(
                "variant: rules needs a non-empty rules_topic (kebab slug)"
            )
        try:
            validate_skill_name(rules_topic)
        except SkillScaffoldError as exc:
            # Y-9 (A2 §4.1/§4.3): "rules topic", never "new-skill name" —
            # the same wording discipline as _parse_dest's rules branch.
            raise ProposalError(
                f"rules topic {rules_topic!r} must be kebab-case "
                "([a-z0-9-], starting alphanumeric) — it names the "
                "rules file"
            ) from exc
    else:  # variant == "local"
        if rules_topic is not None or rules_paths is not None:
            raise ProposalError(
                "variant: local takes no rules_topic and no rules_paths "
                "— a personal project file has no topic and no globs"
            )
    if rules_paths is not None:
        # Deep glob validation (zero-match, per pattern) is route-time
        # only (§5) — the target tree is not known at `proposal
        # validate`; this checks shape only.
        if not isinstance(rules_paths, list) or not rules_paths or any(
            not isinstance(p, str) or not p for p in rules_paths
        ):
            raise ProposalError(
                "rules_paths must be a non-empty list of non-empty glob "
                "strings"
            )


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
    """Validate + write ``proposals/lrn-<id>.yaml`` beside the record.

    §3.5: the record is resolved BEFORE validating, so a trace carrying
    ``gates:`` gets its RECORD-sourced quotes containment-checked against
    ``Record.from_path(record_path).to_text()`` (frontmatter + body, not
    just body — E4). The ``data.get("gates") is not None`` guard is
    load-bearing for cost, not correctness: it keeps the ruamel re-dump
    off the path for every trace-less proposal, which today is all of
    them (M2/M3 are the mutations that catch a weakened guard)."""
    record_path = find_record_path(home, record_id)
    record_text = (
        Record.from_path(record_path).to_text()
        if data.get("gates") is not None
        else None
    )
    validate_proposal(data, record_text=record_text)
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
    variant: str | None = None,
    rules_topic: str | None = None,
    rules_paths: list[str] | None = None,
    allow_empty_glob: bool = False,
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
        # dict[str, object]: the block mixes str/dict/list values below
        # (follow_up/hook are dicts, rules_paths is a list) — a narrower
        # inferred type makes every one of those a pyright error.
        routing: dict[str, object] = {
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
        if variant is not None:
            # A2 §4.3: the claude-md scope parameterization. Absent ⇒
            # today's routing block, byte-identical (P-A6).
            routing["variant"] = variant
            if rules_topic is not None:
                routing["rules_topic"] = rules_topic
            if rules_paths is not None:
                routing["rules_paths"] = list(rules_paths)
            if allow_empty_glob:
                # A2 §5.1 test obligation §13 item 3: the --allow-empty-
                # glob bypass, recorded so a later reader knows the rule
                # was routed unverified.
                routing["allow_empty_glob"] = True
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


def rehome_record(
    home: Path, record_id: str, target_bucket: Path, project_path: Path
) -> list[Path]:
    """File-op half of ``rehome`` (02 §2 verb pin): one ``git mv`` of the
    PENDING record file into *target_bucket*'s ``pending/`` — the record's
    bytes are untouched (a re-home is a filing move, never a substance
    edit) — plus the pinned sweep of its source-bucket proposal siblings
    (``lrn-<id>.{yaml,diff}`` AND any ``merge-*.yaml`` naming it — the
    resolution sweep's own shape, :func:`remove_proposal_siblings`).

    The target bucket's ``{pending,resolved,proposals}/`` dirs are created
    when absent and its ``meta.yaml`` stamped from *project_path* (the
    hosts.yaml entry — 13 §3; hosts.yaml stays the only registration
    authority, this op registers nothing). The destination-collision check
    runs HERE too, BEFORE any dir/meta creation (belt — the verb has
    already refused before taking the lock): a duplicated id is corruption
    to surface, never to merge into. Returns the exact touched-path list;
    deletions among them are pre-staged (git mv/rm) or were untracked."""
    path = find_record_path(home, record_id, statuses=("pending",))
    source_bucket = path.parent.parent
    for sub in ("pending", "resolved"):
        if (target_bucket / sub / path.name).exists():
            raise LedgerOpsError(
                f"record {record_id} already exists in {target_bucket} — a "
                "duplicated id is corruption to surface, never to merge "
                "into; inspect both files by hand"
            )
    meta = ensure_project_meta(target_bucket, project_path)
    for sub in ("pending", "resolved", "proposals"):
        (target_bucket / sub).mkdir(parents=True, exist_ok=True)
    dest_path = target_bucket / "pending" / path.name
    if _is_tracked(home, path):
        _git_ok(home, "mv", str(path), str(dest_path))
    else:
        path.rename(dest_path)
    touched: list[Path] = [path, dest_path, meta]
    touched.extend(remove_proposal_siblings(home, source_bucket, record_id))
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
        # 09 §5 unreadable-record row (FW-18): the skip set is EVERY
        # read/parse failure class, not RecordError alone — an I/O error
        # (vanished mid-scan, permissions), undecodable bytes, or a ruamel
        # YAML parse error must never crash a status/list walk. It is
        # excluded-and-surfaced exactly like a schema-invalid record, and
        # counted through `unparseable_pending` → `status --json`'s
        # `unreadable` field.
        except (RecordError, OSError, UnicodeDecodeError, YAMLError):
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
        # §3.5: entry.record is already in memory (queue() loaded it) — no
        # new I/O (S4). This is the site that makes containment
        # unavoidable: a fabricated quote makes the proposal
        # schema-invalid → proposal_fresh: False → is_unanalyzed: True →
        # the worker re-analyzes it (E7).
        record_text = (
            entry.record.to_text() if data.get("gates") is not None else None
        )
        validate_proposal(data, record_text=record_text)
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


def _bucket_host_registered(hosts: hosts_mod.Hosts, bucket: Bucket) -> bool:
    """09 §11 Y-2/Y-11 predicate (built at 10 U0): project scope is
    registered iff the bucket's OWN recorded path (its ``meta.yaml``) is a
    registered project host; skill/user scope is registered iff a skills
    root is registered at all (both compile through it — doc 13 §2)."""
    if bucket.scope == "project":
        recorded = bucket_project_path(bucket.path)
        if recorded is None:
            return False
        return hosts_mod.is_project_host(hosts, recorded)
    return hosts.skills_root is not None


def list_items(
    home: Path, *, include_deferred: bool = False, now: datetime | None = None
) -> list[dict]:
    """`list --json` items in the pinned shape (08 §1 `--json`-stubs pin,
    G-3 hardening + the 2026-07-17 G-3-surface-substrate fields included),
    oldest first."""
    now = _now(now)
    hosts = hosts_mod.load_hosts(home)
    entries: list[tuple[Bucket, QueueEntry]] = []
    for bucket in discover_buckets(home):
        entries.extend(
            (bucket, e) for e in queue(bucket, include_deferred=include_deferred, now=now)
        )
    entries.sort(key=lambda be: _sort_key(be[1]))
    items = []
    for bucket, entry in entries:
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
                "bucket": bucket.name,
                "host_registered": _bucket_host_registered(hosts, bucket),
                "source": record.source,
            }
        )
    return items


def status_infos(home: Path, *, now: datetime | None = None) -> list[dict]:
    """`status --json` bucket rows: pending/oldest computed over the queue
    (deferred excluded from all counts, 02 §2); ``unanalyzed`` = the shared
    eligibility count; ``unreadable`` = the count of pending files that
    fail to read or parse (09 §5 FW-18), sourced from the SAME
    :func:`unparseable_pending` skip computation `list`/`status` already
    warn on — never a second definition."""
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
                "unreadable": len(unparseable_pending(bucket)),
            }
        )
    return infos
