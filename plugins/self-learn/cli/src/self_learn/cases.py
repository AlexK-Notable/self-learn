"""Decision-case store (U2, `02-schema.md` §3a.2, S-65).

Every steward/overseer decision (and a human's own manual case) is one
file, ``<ledger>/cases/<yyyy-mm>/case-<8hex>.md``: YAML frontmatter plus
six fixed Markdown sections. Sections 1-4 (Identity and scope, Evidence,
Decision, Dependencies) are frozen at commit — their exact text is hashed
into the frontmatter's ``decided_sha256``, and every later read or append
re-verifies that hash and refuses on mismatch. Sections 5 (Application)
and 6 (Later observations) are append-only.

Public surface:

    record(home, stage_file, *, actor) -> str                # case id
    show(home, case_id, *, evidence_only=True) -> CaseView
    list_cases(home, **filters) -> list[dict]                 # only_ok=False
    rebuild_index(cache_dir, home) -> Path
    receipt(home, case_id, batch_result) -> str                # case id
    observe(home, case_id, kind, *, text, by, ref=None,
            to=None, covering=None, entries=None, outcome=None,
            via=None) -> str                                  # obs id

Every writer opens :func:`self_learn.intents.ledger_write` before its
first mutation and stages+commits inside that same span (S-62 §7.2a.5(1),
mirroring ``verbs._ledger_write`` / ``verbs._commit_ledger``). Directory
creation (``cases/`` and its ``<yyyy-mm>/`` month subdir) happens INSIDE
that same locked write, on demand, never refusing — U1 widened
``ledger._LAYOUT`` to include ``cases`` for a fresh ``init``, but no write
path has created it on an EXISTING home yet (U1 gate hand-off); this
module is that first write path.

**Stage-file schema** (this module's own design — the spec fixes the
CASE FILE's shape, not the CLI's input format for ``case record``):

    kind: resolution | maintenance | parked | reconsider
    trigger: nightly | reconsider | maiden | human | weekly
    outcome: route | reject | defer | retire | replaced | rehome |
             revise | no-action | parked
    records: [lrn-...]                 # at least one
    scope: <free text>
    question: <one sentence>
    run_id: <string or omitted>        # null for a human case
    supersedes: <case-... or omitted>
    parked_for: overseer               # only when kind: parked
    parked_reason: <closed set>        # only when kind: parked
    evidence:
      - {ref: <reference grammar>, quote: <verbatim text>}
      - ...                            # at least one
    decision:
      verb: <text>
      covered_by: <text>               # retire only
      because: <the deciding reason>
      confidence: settled | provisional
      what_would_change: [<bullet>, ...]
    dependencies:
      statements: [stmt-...]
      user_model: [um-...@r...]
      conditions: [cond:...]
      capabilities: [...]

``actor`` is passed as its own keyword (never read from the stage file)
because it is the write-side attribution the CALLER is answerable for —
mirroring every other verb's ``by:``/``actor`` split between the sheet
item and the caller's own identity.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from . import gitops, intents, sentinel, user_model
from .ledger import discover_buckets
from .ledger_ops import LedgerOpsError, find_record_path
from .primitives import chrono, fsops
from .primitives.yamlio import rt_yaml
from .records import Record, RecordError
from .scan import format_refusal
from .scan import scan as secret_scan

__all__ = [
    "ACTORS",
    "KINDS",
    "TRIGGERS",
    "OUTCOMES",
    "PARKED_REASONS",
    "OBSERVE_KINDS",
    "PRESENTED_OUTCOMES",
    "COVERING_VALUES",
    "VIA_VALUES",
    "CASE_ID_RE",
    "CaseError",
    "CaseUsageError",
    "CaseView",
    "record",
    "require_reconsider_case",
    "show",
    "list_cases",
    "rebuild_index",
    "receipt",
    "observe",
]

# --------------------------------------------------------------- vocab

#: 02-schema.md §3a.2 frontmatter, `actor` — closed set, no alias. A case's
#: actor is the tighter 3-name subset of `verbs.ROUTING_BY_VALUES`
#: (`{human, analyst, agent, steward, overseer}`, widened by U1): a case
#: is decided by a human or one of the two delegated decision-makers,
#: never by `analyst`/`agent` directly (those write PROPOSALS, not
#: decisions — §3a.1 rule 5 names the wider 5-name list for attribution
#: FIELDS generally; this module pins the narrower set the spec's own
#: case-frontmatter comment gives literally: "human | steward | overseer").
ACTORS = frozenset({"human", "steward", "overseer"})

KINDS = frozenset({"resolution", "maintenance", "parked", "reconsider"})
TRIGGERS = frozenset({"nightly", "reconsider", "maiden", "human", "weekly"})
OUTCOMES = frozenset(
    {
        "route", "reject", "defer", "retire", "replaced", "rehome",
        "revise", "no-action", "parked",
    }
)
PARKED_REASONS = frozenset(
    {
        "hook", "always-loaded-user-scope", "broad-removal",
        "authority-unclear", "scope-conflict", "plain-host-committed-file",
        # 02-schema §3a (S-68, 2026-09-19): written by a RUNNER, never
        # chosen by the steward's model -- a record whose decision reached
        # `runs.attempt_cap` attempts without ever being decided. It asks
        # the overseer the same thing every parked case does (decide the
        # lesson itself) with the recorded failure reason as its evidence:
        # what stopped the steward was the machinery, not the merits.
        "attempts-exhausted",
    }
)
CONFIDENCE_VALUES = frozenset({"settled", "provisional"})
OBSERVE_KINDS = frozenset(
    {
        "examined", "presented", "statement", "corrected",
        "dependency-moved", "reconsider-queued", "abandoned",
    }
)
PRESENTED_OUTCOMES = frozenset({"agreed", "corrected", "noted"})
COVERING_VALUES = frozenset({"decision", "dependencies", "all"})
#: D-g / N4: `via` on a `presented` observation's closed set (02-schema.md
#: §3a.2's YAML example). Gate r2 S5 (settled ruling 3): REQUIRED, not
#: merely a member of this set when given — see the check in `observe`.
VIA_VALUES = frozenset({"overseer-conversation", "review-ui", "teach", "cli"})

CASE_ID_RE = re.compile(r"^case-[0-9a-f]{8}$")
_RECORD_ID_RE = re.compile(r"^lrn-[0-9a-f]{8}$")

_SECTION_ORDER = (
    "Identity and scope",
    "Evidence",
    "Decision",
    "Dependencies",
    "Application",
    "Later observations",
)
#: The exact separator this module always writes between the frozen span
#: (sections 1-4) and section 5. Both `record` (write) and every reader
#: (`_split_frozen`) use this ONE literal — the freeze hash is defined as
#: "the text before this marker", nothing fancier.
_FROZEN_MARKER = "\n\n## Application\n"

_DELIM = "---"
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


class CaseError(Exception):
    """A case verb refused before committing (02 §3a.2)."""

    exit_code = 1


class CaseUsageError(CaseError):
    """Malformed invocation / unknown case id — sysexits EX_USAGE, like
    every other surface's unknown-id refusal (`commands/review.md`:
    "An unknown record id is 64 (usage), not 1.")."""

    exit_code = 64


# ------------------------------------------------------------- helpers


def _cases_root(home: Path) -> Path:
    return home / "cases"


def _month_dir(home: Path, opened_at: str) -> Path:
    return _cases_root(home) / opened_at[:7]  # "2026-09-13T..." -> "2026-09"


def _ensure_case_dirs(home: Path, opened_at: str) -> Path:
    """Create `cases/` and its month subdir if missing — inside the
    caller's already-open locked write, never refusing (U1 gate
    hand-off: no write path has done this yet on an existing home)."""
    month = _month_dir(home, opened_at)
    month.mkdir(parents=True, exist_ok=True)
    return month


def _case_path_for_id(home: Path, case_id: str) -> Path:
    if not CASE_ID_RE.match(case_id):
        raise CaseUsageError(f"case: malformed case id {case_id!r}")
    matches = sorted(_cases_root(home).glob(f"*/{case_id}.md"))
    if not matches:
        raise CaseUsageError(f"case: no such case {case_id}")
    if len(matches) > 1:  # pragma: no cover — defensive; ids are unique
        raise CaseError(
            f"case: {case_id} found at more than one path: {matches}"
        )
    return matches[0]


def _committed_case_for_id(home: Path, case_id: str) -> tuple[Path, str] | None:
    """Return a case from ``HEAD`` without consulting the rebuildable index."""
    if CASE_ID_RE.fullmatch(case_id) is None:
        raise CaseUsageError(f"case: malformed case id {case_id!r}")
    listing = gitops._git(  # noqa: SLF001 — committed case truth query
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases"
    ).stdout.splitlines()
    suffix = f"/{case_id}.md"
    matches = [
        rel
        for rel in listing
        if rel.startswith("cases/") and rel.endswith(suffix)
    ]
    if len(matches) > 1:
        raise CaseError(f"case: {case_id} found at more than one committed path: {matches}")
    if not matches:
        return None
    relpath = matches[0]
    content = gitops._git(  # noqa: SLF001 — committed case truth query
        home, "show", f"HEAD:{relpath}"
    ).stdout
    return home / relpath, content


def _yaml() -> YAML:
    return rt_yaml(preserve_quotes=True, width=4096, default_flow_style=False)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise CaseError("case: file is not frontmatter + body — malformed")
    fm = _yaml().load(m.group(1))
    return dict(fm or {}), m.group(2)


def _render_frontmatter(fm: dict) -> str:
    buf = io.StringIO()
    _yaml().dump(fm, buf)
    return f"{_DELIM}\n{buf.getvalue()}{_DELIM}\n"


def _locate_headings(body: str) -> list[tuple[str, re.Match]]:
    """Find the six known headings, in `_SECTION_ORDER`, POSITIONALLY
    (D-i): heading *i+1* is searched for starting at the END of heading
    *i*'s own `## Heading\\n` line, never by a bare scan for the first
    occurrence of a string anywhere in the body. A `## Evidence` line
    embedded inside an EARLIER section's own free text can still be
    found by the search for the next heading in order — the defense
    against that is `_refuse_headings` at write time, which keeps a
    heading-shaped line out of free text in the first place; this
    function's job is to refuse a body that is missing or misorders any
    of the six, rather than silently mis-assign content to the wrong
    key the way a `finditer`-into-a-dict approach would (B3/S4)."""
    matches: list[tuple[str, re.Match]] = []
    cursor = 0
    for heading in _SECTION_ORDER:
        pat = re.compile(r"^## " + re.escape(heading) + r"\n", re.MULTILINE)
        m = pat.search(body, cursor)
        if m is None:
            raise CaseError(
                f"case: missing or out-of-order section '## {heading}' — malformed"
            )
        matches.append((heading, m))
        cursor = m.end()
    # Astra r2 finding 1 / gate r2 S1: the positional search above only
    # proves the six known headings occur, in order — it says nothing
    # about a SEVENTH `^## ` line anywhere else in the body (before the
    # first heading, wedged between two known ones by a field that
    # itself starts with a heading-shaped line, or after the last).
    # `_refuse_headings` keeps that out of free text at write time, but
    # readers must not rely on writers alone: count every `^## ` line in
    # the whole body and refuse unless it is exactly six, so a
    # bypassed-writer or hand-edited file is refused by every reader
    # with a clear error rather than silently parsed around the extra
    # heading.
    total = len(_HEADING_LINE_RE.findall(body))
    if total != 6:
        raise CaseError(
            f"case: body has {total} '## ' heading lines, expected exactly "
            "6 — malformed"
        )
    return matches


def _split_frozen(body: str) -> tuple[str, str]:
    """(frozen sections 1-4 text, rest) split at the START of the fifth
    known heading, '## Application' — located POSITIONALLY via
    :func:`_locate_headings` (D-i), never by a bare string search for
    the `_FROZEN_MARKER` literal, which a `because`/`quote`/... field
    containing that exact text could spoof (S4: a case committed
    successfully but became permanently unreadable on every later read)."""
    matches = _locate_headings(body)
    app_start = matches[4][1].start()  # index 4 == "Application", the 5th heading
    # `app_start` is the position of the "#" in "## Application"; the
    # module always writes exactly "\n\n## Application\n" between
    # sections, so `app_start - 2` is where the frozen span (sections
    # 1-4) ends, matching `_FROZEN_MARKER`'s own literal byte-for-byte.
    return body[: app_start - 2], body[app_start - 2 :]


def _hash_frozen(frozen_text: str) -> str:
    return hashlib.sha256(frozen_text.encode("utf-8")).hexdigest()


def _fmt_list(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]"


def _parse_bracket_list(line: str) -> list[str]:
    """`- statements: [stmt-a, stmt-b]` -> ["stmt-a", "stmt-b"]; `[]` -> []."""
    start = line.find("[")
    end = line.rfind("]")
    if start == -1 or end == -1:
        return []
    inner = line[start + 1 : end].strip()
    if not inner:
        return []
    return [tok.strip() for tok in inner.split(",") if tok.strip()]


def _scan_or_refuse(texts: list[str]) -> None:
    for text in texts:
        hits = secret_scan(text)
        if hits:
            raise CaseError(format_refusal(hits))


#: D-i / B3 / S4 / Astra 1: any line that LOOKS like a section heading
#: inside a free-text field is refused outright at write time — never
#: escaped, never silently accepted — the same secret-scan-style refusal
#: `_scan_or_refuse` uses. This is what keeps `_parse_sections`/
#: `_split_frozen`'s positional heading search meaningful: a heading
#: line can never reach disk from a free-text field in the first place.
_HEADING_LINE_RE = re.compile(r"^## ", re.MULTILINE)


def _refuse_headings(texts: list[str]) -> None:
    for text in texts:
        if text and _HEADING_LINE_RE.search(text):
            raise CaseError(
                "case: a free-text field contains a '## ' heading-shaped line — "
                "refused (heading injection, D-i)"
            )


def _new_case_id(home: Path) -> str:
    for _ in range(64):
        candidate = "case-" + uuid.uuid4().hex[:8]
        if not list(_cases_root(home).glob(f"*/{candidate}.md")):
            return candidate
    raise CaseError("case: could not allocate a unique case id")  # pragma: no cover


# ------------------------------------------------------------- render


def _render_identity(records: list[str], scope: str, question: str, trigger: str) -> str:
    return (
        f"## Identity and scope\n"
        f"- records: {', '.join(records)}\n"
        f"- scope: {scope}\n"
        f"- question: {question}\n"
        f"- trigger: {trigger}\n"
    )


def _render_evidence(items: list[dict]) -> str:
    lines = ["## Evidence"]
    for item in items:
        lines.append(f"- {item['ref']} — {item['quote']}")
    return "\n".join(lines) + "\n"


def _render_decision(decision: dict) -> str:
    lines = ["## Decision"]
    if decision.get("verb") is not None:
        lines.append(f"- verb: {decision['verb']}")
    if decision.get("covered_by") is not None:
        lines.append(f"- covered_by: {decision['covered_by']}")
    lines.append(f"- because: {decision['because']}")
    lines.append(f"- confidence: {decision['confidence']}")
    wwc = decision.get("what_would_change") or []
    if wwc:
        lines.append("")
        lines.append("What would change this decision:")
        for bullet in wwc:
            lines.append(f"- {bullet}")
    return "\n".join(lines) + "\n"


def _render_dependencies(deps: dict) -> str:
    return (
        "## Dependencies\n"
        f"- statements: {_fmt_list(deps.get('statements') or [])}\n"
        f"- user_model: {_fmt_list(deps.get('user_model') or [])}\n"
        f"- conditions: {_fmt_list(deps.get('conditions') or [])}\n"
        f"- capabilities: {_fmt_list(deps.get('capabilities') or [])}\n"
    )


def _render_frozen(records: list[str], scope: str, question: str, trigger: str,
                    evidence: list[dict], decision: dict, deps: dict) -> str:
    return (
        _render_identity(records, scope, question, trigger)
        + "\n"
        + _render_evidence(evidence)
        + "\n"
        + _render_decision(decision)
        + "\n"
        + _render_dependencies(deps).rstrip("\n")
    )


def _parse_sections(body: str) -> dict[str, str]:
    """heading -> its content text (without the '## Heading' line
    itself), for exactly the six known fixed headings, in `_SECTION_ORDER`
    (D-i). Uses :func:`_locate_headings`'s POSITIONAL search — each
    heading's content runs from the end of its own heading line to the
    START of the NEXT heading's match (found by the ordered search, not
    by a dict keyed on heading NAME, which is what let a second
    occurrence of the same heading name silently overwrite the first —
    B3)."""
    matches = _locate_headings(body)
    out: dict[str, str] = {}
    for i, (heading, m) in enumerate(matches):
        start = m.end()
        end = matches[i + 1][1].start() if i + 1 < len(matches) else len(body)
        out[heading] = body[start:end].rstrip("\n")
    return out


# --------------------------------------------------------------- record


def record(
    home: Path | str,
    stage_file: Path | str,
    *,
    actor: str,
    reserved_id: str | None = None,
) -> str:
    """Validate a stage file's six parts + closed sets, assign the id,
    secret-scan every free-text field, compute the freeze hash, write,
    commit. Returns the new case id."""
    home = Path(home)
    stage = Path(stage_file)
    if actor not in ACTORS:
        raise CaseUsageError(f"case record: actor must be one of {sorted(ACTORS)}, got {actor!r}")
    if reserved_id is not None and CASE_ID_RE.fullmatch(reserved_id) is None:
        raise CaseUsageError(f"case record: malformed reserved id: {reserved_id!r}")
    try:
        text = stage.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaseUsageError(f"case record: cannot read {stage}: {exc}") from exc
    data = YAML(typ="safe").load(text)
    if not isinstance(data, dict):
        raise CaseUsageError(f"case record: {stage} must be a mapping")

    kind = data.get("kind")
    if kind not in KINDS:
        raise CaseUsageError(f"case record: kind must be one of {sorted(KINDS)}, got {kind!r}")
    trigger = data.get("trigger")
    if trigger not in TRIGGERS:
        raise CaseUsageError(f"case record: trigger must be one of {sorted(TRIGGERS)}, got {trigger!r}")
    outcome = data.get("outcome")
    if outcome not in OUTCOMES:
        raise CaseUsageError(f"case record: outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")
    records_field = data.get("records")
    if not isinstance(records_field, list) or not records_field or not all(
        isinstance(r, str) and _RECORD_ID_RE.match(r) for r in records_field
    ):
        raise CaseUsageError("case record: records must be a non-empty list of lrn-... ids")
    scope = data.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        raise CaseUsageError("case record: scope is required")
    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        raise CaseUsageError("case record: question is required")

    supersedes = data.get("supersedes")
    if supersedes is not None and not CASE_ID_RE.match(str(supersedes)):
        raise CaseUsageError(f"case record: supersedes malformed: {supersedes!r}")

    parked_for = data.get("parked_for")
    parked_reason = data.get("parked_reason")
    if kind == "parked":
        if parked_for != "overseer":
            raise CaseError(
                "case record: a parked case's parked_for is always 'overseer' "
                "(the steward never parks for a human)"
            )
        if parked_reason not in PARKED_REASONS:
            raise CaseUsageError(
                f"case record: parked_reason must be one of {sorted(PARKED_REASONS)}, "
                f"got {parked_reason!r}"
            )
        if outcome != "parked":
            raise CaseError("case record: kind: parked requires outcome: parked")
    else:
        if parked_for is not None or parked_reason is not None:
            raise CaseUsageError(
                "case record: parked_for/parked_reason are only set when kind: parked"
            )

    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise CaseUsageError("case record: evidence must be a non-empty list")
    for item in evidence:
        if not isinstance(item, dict) or not item.get("ref") or not item.get("quote"):
            raise CaseUsageError("case record: every evidence item needs ref + quote")

    decision = data.get("decision")
    if not isinstance(decision, dict) or not decision.get("because"):
        raise CaseUsageError("case record: decision.because is required")
    confidence = decision.get("confidence")
    if confidence not in CONFIDENCE_VALUES:
        raise CaseUsageError(
            f"case record: decision.confidence must be one of {sorted(CONFIDENCE_VALUES)}, "
            f"got {confidence!r}"
        )
    what_would_change = decision.get("what_would_change") or []
    if not isinstance(what_would_change, list):
        raise CaseUsageError("case record: decision.what_would_change must be a list")

    deps = data.get("dependencies") or {}
    if not isinstance(deps, dict):
        raise CaseUsageError("case record: dependencies must be a mapping")
    for key in ("statements", "user_model", "conditions", "capabilities"):
        val = deps.get(key) or []
        if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
            raise CaseUsageError(f"case record: dependencies.{key} must be a list of strings")

    # Secret scan EVERY free-text field BEFORE any write (02 §3a.2:
    # "secret-scan every free-text field with scan.scan"; B2: the
    # original scan missed `scope`, `decision.verb`, `decision.
    # covered_by`, every evidence `ref`, and the dependency strings).
    # Scans the STAGE's inputs, never the rendered file — the rendered
    # frontmatter carries `decided_sha256`, a 64-char hex string that
    # would trip the scanner's own high-entropy-hex rule (>=48 chars) if
    # it were ever fed back through this same scan.
    free_texts = [scope, question, str(decision.get("because"))]
    if decision.get("verb") is not None:
        free_texts.append(str(decision["verb"]))
    if decision.get("covered_by") is not None:
        free_texts.append(str(decision["covered_by"]))
    free_texts += [str(b) for b in what_would_change]
    for item in evidence:
        free_texts.append(str(item.get("ref", "")))
        free_texts.append(str(item.get("quote", "")))
    for key in ("statements", "user_model", "conditions", "capabilities"):
        free_texts += [str(v) for v in (deps.get(key) or [])]
    # Gate r2 S6: `run_id` reaches the committed frontmatter unscanned —
    # an identifier string like every other one B2 already covers
    # (`evidence[].ref`, the dependency id lists).
    if data.get("run_id") is not None:
        free_texts.append(str(data["run_id"]))
    _scan_or_refuse(free_texts)
    # D-i / B3 / S4: refuse a heading-shaped line in ANY of the same
    # free-text fields, before it can ever be rendered into the file.
    _refuse_headings(free_texts)

    opened_at = chrono.now_iso()
    case_id = reserved_id or _new_case_id(home)

    frozen_text = _render_frozen(records_field, scope, question, trigger, evidence, decision, deps)
    decided_sha256 = _hash_frozen(frozen_text)

    fm: dict[str, Any] = {
        "case": case_id,
        "opened_at": opened_at,
        "actor": actor,
        "run_id": data.get("run_id"),
        "records": list(records_field),
        "kind": kind,
        "trigger": trigger,
        "outcome": outcome,
        "supersedes": supersedes,
        "superseded_by": None,
        "parked_for": parked_for,
        "parked_reason": parked_reason,
        "decided_sha256": decided_sha256,
        "presented": [],
    }

    body = (
        frozen_text
        + _FROZEN_MARKER.rstrip("\n")
        + "\n(none)\n\n## Later observations\n(none)\n"
    )
    file_text = _render_frontmatter(fm) + body

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            if reserved_id is not None:
                committed = _committed_case_for_id(home, reserved_id)
                if committed is not None:
                    existing_path, existing_text = committed
                    try:
                        worktree_text = existing_path.read_text(encoding="utf-8")
                    except OSError as exc:
                        raise CaseError(
                            f"case record: committed reserved case {reserved_id} "
                            f"is unavailable in the worktree: {exc}"
                        ) from exc
                    if worktree_text != existing_text:
                        raise CaseError(
                            f"case record: reserved case {reserved_id} has "
                            "uncommitted incompatible content"
                        )
                    existing_fm, existing_body = _split_frontmatter(existing_text)
                    existing_frozen, _ = _split_frozen(existing_body)
                    same = (
                        existing_fm.get("case") == case_id
                        and existing_fm.get("kind") == kind
                        and existing_fm.get("actor") == actor
                        and existing_fm.get("run_id") == data.get("run_id")
                        and existing_fm.get("trigger") == trigger
                        and existing_fm.get("outcome") == outcome
                        and existing_fm.get("supersedes") == supersedes
                        and existing_fm.get("parked_for") == parked_for
                        and existing_fm.get("parked_reason") == parked_reason
                        and existing_fm.get("decided_sha256") == decided_sha256
                        and _hash_frozen(existing_frozen) == decided_sha256
                    )
                    if same:
                        return case_id
                    raise CaseError(
                        f"case record: reserved id collision for {reserved_id}"
                    )
                uncommitted_matches = sorted(
                    _cases_root(home).glob(f"*/{reserved_id}.md")
                )
                if uncommitted_matches:
                    raise CaseError(
                        f"case record: reserved id collision for {reserved_id} "
                        "outside committed truth"
                    )
            month = _ensure_case_dirs(home, opened_at)
            path = month / f"{case_id}.md"

            # Astra 9 / item 7: validate the predecessor BEFORE writing
            # anything — a refused `supersedes` (unknown id, tampered
            # predecessor, already superseded) used to leave a complete,
            # valid-hash new case file on disk with no commit ever
            # landing for it (a readable phantom case). Nothing is
            # written until every check below has passed.
            supersedes_path: Path | None = None
            sup_fm: dict | None = None
            sup_body: str | None = None
            if supersedes is not None:
                supersedes_path = _case_path_for_id(home, str(supersedes))
                sup_text = supersedes_path.read_text(encoding="utf-8")
                sup_fm, sup_body = _split_frontmatter(sup_text)
                frozen_sup, _rest_sup = _split_frozen(sup_body)
                if _hash_frozen(frozen_sup) != sup_fm.get("decided_sha256"):
                    raise CaseError(
                        f"case record: supersedes {supersedes} failed its "
                        "freeze-hash check — refusing to chain a successor "
                        "onto a tampered case"
                    )
                if sup_fm.get("superseded_by"):
                    raise CaseError(
                        f"case record: {supersedes} is already superseded by "
                        f"{sup_fm['superseded_by']}"
                    )

            message = f"self-learn: case record {case_id} ({outcome})"

            # Gate r2 S2: a successor + predecessor publication is a
            # second two-file writer, same family as `observe`'s above —
            # bracket it with an intent (opened before the FIRST
            # mutation) so a crash between the two writes rolls the
            # whole transaction forward or back on the next
            # `ledger_write` acquisition, never leaving a successor
            # without its predecessor link (Astra 9's crash leg).
            publication_paths = [path]
            if supersedes_path is not None:
                publication_paths.append(supersedes_path)
            intent = intents.begin(
                home,
                "case-record-supersedes" if supersedes_path is not None else "case-record",
                publication_paths,
                message,
            )

            fsops.atomic_write(path, file_text, fsync=True)
            touched = [path]

            if supersedes_path is not None:
                assert sup_fm is not None and sup_body is not None
                sup_fm["superseded_by"] = case_id
                fsops.atomic_write(
                    supersedes_path, _render_frontmatter(sup_fm) + sup_body, fsync=True
                )
                touched.append(supersedes_path)

            intents.complete(intent)

            sha = gitops.stage_and_commit(home, touched, message, question)
            if sha is None:  # pragma: no cover — never allow_empty here
                raise CaseError("case record: internal — commit produced nothing")
            # Gate r2 S3: `_update_index` is now always a full rebuild
            # (no incremental upsert of a single row) — a second call
            # keyed on `supersedes` would rebuild the exact same index
            # from the exact same on-disk files a second time for no
            # reason; one call after the commit covers both the new
            # case and its predecessor's `superseded_by` flip.
            intents.finish(intent)
            _update_index(home, case_id)
    finally:
        hold.release()

    return case_id


# ------------------------------------------------------------ reconsider


def require_reconsider_case(
    home: Path | str, case_id: str, record_id: str
) -> tuple[dict, dict]:
    """U5's one shared check (`build-u5.md`): used by both
    :func:`self_learn.verbs.reconsider` and the ``reconsider_case``
    widening `reject`/`defer`/`graduate`/`supersede` each gain — every
    raise here is a :class:`CaseError`, which every verb call site wraps
    into a :class:`self_learn.verbs.VerbError` before any lock is taken.

    *case_id* must name an EXISTING case whose ``kind`` is
    ``"reconsider"`` and whose ``supersedes`` names a SECOND existing
    case that itself covers *record_id* (``record_id in
    predecessor.records``); both files must still pass their own
    freeze-hash check.

    This function does **not** write ``superseded_by`` on the
    predecessor — :func:`record` (this module's own case-creation verb)
    already does that, atomically, at the moment the reconsider case
    itself is created (the ``supersedes`` handling above, `record`
    lines ~590-639: predecessor read, freeze-checked, and flipped in the
    SAME commit as the new case). By the time a ``reconsider`` case
    exists at all, its predecessor is therefore already marked — a
    second write through `record`'s own path is refused outright (a
    case is superseded once). What this function checks is that the
    link `record` wrote is the one THIS case actually claims
    (``predecessor.superseded_by == case_id``) — a defensive read, not
    a second writer.

    Returns ``(case_frontmatter, predecessor_frontmatter)`` — the caller
    (``verbs.reconsider``) decides whether ``case_frontmatter["outcome"]``
    is applicable to the record's current status; the callers widening a
    resolution verb only need the existence/kind/coverage checks this
    function already performed to raise."""
    home = Path(home)
    case_path = _case_path_for_id(home, case_id)
    case_text = case_path.read_text(encoding="utf-8")
    case_fm, case_body = _split_frontmatter(case_text)
    frozen, _rest = _split_frozen(case_body)
    if _hash_frozen(frozen) != case_fm.get("decided_sha256"):
        raise CaseError(
            f"reconsider: {case_id} failed its freeze-hash check — "
            "refusing to act on a tampered case"
        )
    if case_fm.get("kind") != "reconsider":
        raise CaseError(
            f"reconsider: {case_id} is kind {case_fm.get('kind')!r}, not "
            "'reconsider' — no case"
        )
    supersedes = case_fm.get("supersedes")
    if not supersedes:
        raise CaseError(
            f"reconsider: {case_id} names no predecessor case (supersedes "
            "is unset) — no case"
        )
    old_path = _case_path_for_id(home, str(supersedes))
    old_text = old_path.read_text(encoding="utf-8")
    old_fm, old_body = _split_frontmatter(old_text)
    old_frozen, _old_rest = _split_frozen(old_body)
    if _hash_frozen(old_frozen) != old_fm.get("decided_sha256"):
        raise CaseError(
            f"reconsider: {supersedes} failed its freeze-hash check — "
            "refusing to act on a tampered predecessor case"
        )
    if record_id not in (old_fm.get("records") or []):
        raise CaseError(
            f"reconsider: {supersedes} does not cover {record_id} — wrong "
            "record"
        )
    if old_fm.get("superseded_by") != case_id:
        raise CaseError(
            f"reconsider: {supersedes}'s superseded_by is "
            f"{old_fm.get('superseded_by')!r}, not {case_id!r} — the "
            "predecessor link is broken or was superseded by a different "
            "case"
        )
    return case_fm, old_fm


# ----------------------------------------------------------------- show


@dataclass
class CaseView:
    case_id: str
    evidence_only: bool
    frontmatter: dict = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)

    def to_text(self) -> str:
        # N6: print which view this is — `to_json()` already carries
        # `evidence_only`; the human-readable text used not to say so.
        view_name = "evidence-only (blind)" if self.evidence_only else "full"
        lines = [f"case: {self.case_id}", f"  view: {view_name}"]
        for key in (
            "opened_at", "actor", "run_id", "records", "kind", "trigger",
            "outcome", "supersedes", "superseded_by", "parked_for",
            "parked_reason", "presented",
        ):
            if key in self.frontmatter:
                lines.append(f"  {key}: {self.frontmatter[key]}")
        for heading in _SECTION_ORDER:
            if heading in self.sections:
                lines.append("")
                lines.append(f"## {heading}")
                lines.append(self.sections[heading])
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "case": self.case_id,
            "evidence_only": self.evidence_only,
            "frontmatter": self.frontmatter,
            "sections": self.sections,
        }


#: D-h: the blind view is an ALLOWLIST, not a denylist — the prior
#: denylist (`outcome`/`superseded_by`/`parked_for`/`parked_reason`)
#: let every OTHER frontmatter key leak through, `presented` included.
#: `scope` is not an actual frontmatter key — it is section-1 body
#: text — so it is not listed here; this allowlist is exactly
#: `{case, opened_at, actor, kind, records, supersedes}`, narrower than
#: §3a.2's own four-field denylist (which would also keep `run_id`,
#: `trigger`, `presented`, `decided_sha256`). Gate r2 N3: this drift was
#: resolved by amending 02-schema.md's blind-frontmatter-key sentence
#: to match this allowlist (dropping `scope` from that sentence too,
#: with a parenthetical noting `scope` is section 1's own body text and
#: stays visible), rather than left as an unresolved report note.
_BLIND_FRONTMATTER_ALLOW = frozenset(
    {"case", "opened_at", "actor", "kind", "records", "supersedes"}
)
_BLIND_SECTIONS = ("Identity and scope", "Evidence", "Dependencies")


def show(home: Path | str, case_id: str, *, evidence_only: bool = True) -> CaseView:
    """Two views (§3a.2). This module's OWN keyword default
    (`evidence_only=True`) is the BLIND view; `self-learn case show`
    with no flag is the FULL view (the CLI's own `args.evidence_only`
    argparse default is `False` — see `cli._add_case_parser`). The blind
    view is an allowlist (D-h): frontmatter `case, opened_at, actor,
    kind, records, supersedes` only, sections 1/2/4 only.
    `evidence_only=False` is the full view, everything. Re-verifies the
    freeze hash before returning either view; refuses on mismatch."""
    home = Path(home)
    path = _case_path_for_id(home, case_id)
    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)
    frozen_text, _rest = _split_frozen(body)
    if _hash_frozen(frozen_text) != fm.get("decided_sha256"):
        raise CaseError(
            f"case show: {case_id} failed its freeze-hash check — sections "
            "1-4 were tampered with or the commit is corrupt; refusing to show it"
        )
    sections = _parse_sections(body)

    if evidence_only:
        fm_view = {k: v for k, v in fm.items() if k in _BLIND_FRONTMATTER_ALLOW}
        sections_view = {h: sections[h] for h in _BLIND_SECTIONS if h in sections}
    else:
        fm_view = dict(fm)
        sections_view = dict(sections)

    return CaseView(case_id=case_id, evidence_only=evidence_only, frontmatter=fm_view, sections=sections_view)


# ------------------------------------------------------------- index


def _index_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / "cases" / "index.json"


def _record_scope_and_bucket(home: Path, record_id: str) -> tuple[str | None, str | None]:
    """O-1 fold r1 (`scope_kind` on the index row): the FIRST cited
    record's controlled `scope` ("user" | "project" | "skill:<name>"),
    bucketed to one of the three coverage-stratum kinds
    (`folds/fold-j0-r1.md` F2), plus the NAME of the bucket the record
    was found in (`ledger.discover_buckets`, matched by the record
    file's own parent-of-parent directory — the same layout
    `find_record_path` walks: ``<bucket.path>/<status>/<id>.md``).

    Read ONCE, here, at index-build time — never re-derived downstream
    (`overseer.population.coverage_update` no longer takes `home` or
    looks up records itself) — so a record deleted AFTER this row was
    cached does not erase the classification a stale-but-not-rebuilt
    index row already carries. `(None, None)` on any failure (record
    missing, corrupt, unreadable): the same "one bad record must never
    hide the whole population" degrade this function's caller already
    uses for `dependency_refs`/`provisional`, never a raise."""
    try:
        path = find_record_path(home, record_id)
        record = Record.from_path(path)
        scope = record.scope
        kind = "skill" if isinstance(scope, str) and scope.startswith("skill:") else scope
        bucket_name = None
        for bucket in discover_buckets(home):
            if path.parent.parent == bucket.path:
                bucket_name = bucket.name
                break
        return kind, bucket_name
    except (LedgerOpsError, RecordError, OSError, UnicodeDecodeError):
        return None, None


def _index_row(path: Path, home: Path) -> dict:
    """One case file -> one index row. S6: the freeze hash is ALWAYS
    re-verified here — the overseer "samples from it and never rereads
    the catalogue" (§3a.2), so a tampered case must never reach that
    surface silently. A hash mismatch (or a structurally malformed body
    — `_parse_sections`/`_split_frozen` can themselves refuse, D-i)
    degrades to `frozen_ok: false` with whatever frontmatter could still
    be read, rather than raising: ONE corrupt case must never hide the
    whole population from `rebuild_index` (exclude-with-flag, per the
    brief's own choice).

    O-1 fold r1: also carries `scope_kind` (user | skill | project,
    `folds/fold-j0-r1.md` F2) and `record_bucket` — both read ONCE here
    from the case's FIRST cited record (`_record_scope_and_bucket`),
    `None` when that record is unreadable. Not yet named in
    `02-schema.md`'s own index-field list (that list predates this
    fold); `overseer.population.coverage_update` depends on
    `scope_kind` and refuses a row that lacks it rather than guessing.

    Gate r2 S4 / Astra 11: the original catch was
    `except CaseError` only — a case whose YAML itself will not parse
    (`_split_frontmatter`'s `_yaml().load(...)`) raised a bare
    `ruamel.yaml` error PAST this function, killing the whole rebuild —
    exactly the population-hiding failure S6/`frozen_ok` exists to
    avoid, just from a different cause. Widened to catch `YAMLError`
    too, and the fallback row's `case` is the FILENAME STEM (not
    `fm.get("case")`, which is `None` whenever the frontmatter itself
    never parsed) so `_serialize_index`'s sort never sees a `None`.
    `path.read_text` is INSIDE the same `try` (not hoisted above it): a
    non-UTF-8 case file or a lost-file race would otherwise raise past
    this function exactly like the YAML case above — the same
    population-hiding failure, just from `UnicodeDecodeError`/`OSError`
    instead of a YAML one."""
    fm: dict = {}
    sections: dict[str, str] = {}
    frozen_ok = False
    try:
        text = path.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(text)
        frozen_text, _rest = _split_frozen(body)
        if _hash_frozen(frozen_text) == fm.get("decided_sha256"):
            sections = _parse_sections(body)
            frozen_ok = True
    except (CaseError, YAMLError, OSError, UnicodeDecodeError):
        pass

    deps_text = sections.get("Dependencies", "")
    dependency_refs: list[str] = []
    for line in deps_text.splitlines():
        line = line.strip()
        if line.startswith("- statements:") or line.startswith("- user_model:") \
                or line.startswith("- conditions:") or line.startswith("- capabilities:"):
            dependency_refs.extend(_parse_bracket_list(line))
    presented = fm.get("presented") or []
    provisional = fm.get("actor") != "human" and not any(
        p.get("covering") in ("decision", "all") for p in presented
    )
    last_obs_at = None
    for line in sections.get("Later observations", "").splitlines():
        m = re.match(r"^- obs-[0-9a-f]{8} (\S+) ", line.strip())
        if m:
            last_obs_at = m.group(1)
    records_list = list(fm.get("records") or [])
    scope_kind, record_bucket = (
        _record_scope_and_bucket(home, records_list[0]) if records_list else (None, None)
    )
    return {
        "case": fm.get("case") or path.stem,
        "opened_at": fm.get("opened_at"),
        "actor": fm.get("actor"),
        "kind": fm.get("kind"),
        "trigger": fm.get("trigger"),
        "outcome": fm.get("outcome"),
        "records": records_list,
        "supersedes": fm.get("supersedes"),
        "superseded_by": fm.get("superseded_by"),
        "parked_for": fm.get("parked_for"),
        "parked_reason": fm.get("parked_reason"),
        "provisional": provisional,
        "presented_count": len(presented),
        "dependency_refs": dependency_refs,
        "last_observation_at": last_obs_at,
        "frozen_ok": frozen_ok,
        "scope_kind": scope_kind,
        "record_bucket": record_bucket,
    }


def _serialize_index(rows: list[dict]) -> str:
    # Gate r2 S4: `_index_row` now always fills `case` (filename stem on
    # a parse failure), but this sort stays defensive against a `None`
    # regardless — a `TypeError` here would hide the whole population
    # exactly like the bug this item fixes.
    rows_sorted = sorted(rows, key=lambda r: r.get("case") or "")
    return json.dumps({"cases": rows_sorted}, indent=2, sort_keys=True) + "\n"


def _load_index(cache_dir: Path) -> list[dict]:
    path = _index_path(cache_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def _write_index(cache_dir: Path, rows: list[dict]) -> Path:
    path = _index_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, _serialize_index(rows), fsync=True)
    return path


@contextlib.contextmanager
def _index_lock(cache_dir: Path):
    """Astra 6 / item 5: `_update_index` and `rebuild_index` both
    read-modify-write the SAME cache file (`_load_index` then
    `_write_index`); without mutual exclusion, two concurrent writers
    can race and one's upsert is lost. A blocking `flock` on a lockfile
    beside the index — the cache dir's own lock, `worker.py`'s
    established pattern, and NEVER `gitops.commit_lock`: this index is
    `NOT_REPO_TRUTH`, never the ledger."""
    cache_dir = Path(cache_dir)
    lock_path = _index_path(cache_dir).parent / "index.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _update_index(home: Path, case_id: str) -> Path:
    """Called after every write (§1.8: "the CLI updates it incrementally
    after each write") — cache-only, `NOT_REPO_TRUTH`: even though every
    call site (`record`, `receipt`, `observe`) happens to run textually
    inside that writer's own `ledger_write` span, the index file itself
    is never part of the ledger's git-tracked truth.

    Gate r2 S3: this used to be a true incremental upsert (replace only
    *case_id*'s own row, keep every other cached row as-is) — which
    silently PROPAGATES a stale row AND erases `_index_is_stale`'s own
    staleness signal: rewriting the file gives it a newer mtime than
    every case file on disk, so the next writer's upsert sees the index
    as fresh and never rebuilds it. `test_e_rebuild_equals_incremental_
    byte_for_byte` already proves incremental and full-rebuild are the
    SAME pure function of file content, byte for byte, and case counts
    are small — so this now simply delegates to :func:`rebuild_index`
    (under the SAME `_index_lock`, via that call), rebuilding the whole
    index every time rather than trying to reason about which rows are
    still fresh. `case_id` is kept as a parameter for every call site's
    unchanged signature; the rebuild does not use it."""
    from . import worker

    cache_dir = worker.cache_dir(home)
    return rebuild_index(cache_dir, home)


def rebuild_index(cache_dir: Path | str, home: Path | str) -> Path:
    """Rebuild `<cache>/cases/index.json` from the case files on disk,
    under the cache-dir `_index_lock` (item 5) — cache-only
    (`NOT_REPO_TRUTH`), never the ledger lock. Atomic (tmp + replace) via
    `_write_index`/`fsops.atomic_write`."""
    home = Path(home)
    cache_dir = Path(cache_dir)
    with _index_lock(cache_dir):
        rows = [_index_row(p, home) for p in sorted(_cases_root(home).glob("*/case-*.md"))]
        return _write_index(cache_dir, rows)


def _index_is_stale(cache_dir: Path, home: Path) -> bool:
    """Astra 6 / item 5: the index is stale — and must be rebuilt before
    being trusted — when it is absent, OR any case file on disk is newer
    than the index file (a write landed without going through this
    module's own incremental upsert, e.g. a restored/copied ledger), OR
    the case-file count on disk differs from the row count in the index
    (a write or a deletion the incremental path never saw), OR any
    cached row lacks `scope_kind` (O-1 fold r1: a cache written by code
    from before this fold has the RIGHT mtime and the RIGHT row count —
    neither check above catches it — so a missing key, not merely a
    `None` value, is its own staleness signal; otherwise a pre-fold
    cache would leave `overseer.population.coverage_update` refusing
    every row forever)."""
    index_file = _index_path(cache_dir)
    if not index_file.exists():
        return True
    case_files = sorted(_cases_root(home).glob("*/case-*.md"))
    index_mtime = index_file.stat().st_mtime
    if any(p.stat().st_mtime > index_mtime for p in case_files):
        return True
    rows = _load_index(cache_dir)
    if len(rows) != len(case_files):
        return True
    if any("scope_kind" not in row for row in rows):
        return True
    return False


def list_cases(
    home: Path | str,
    *,
    since: str | None = None,
    provisional: bool | None = None,
    parked_for: str | None = None,
    parked_reason: str | None = None,
    record_id: str | None = None,
    only_ok: bool = False,
) -> list[dict]:
    """Query the index (rebuilding it first when stale — item 5 — not
    only when it is missing; every writer also keeps it current via
    incremental upserts). `only_ok`: S6 — when true, excludes rows whose
    freeze hash failed re-verification (`frozen_ok: false`); every row
    always CARRIES `frozen_ok` regardless."""
    from . import worker

    home = Path(home)
    cache_dir = worker.cache_dir(home)
    if _index_is_stale(cache_dir, home):
        rebuild_index(cache_dir, home)
    rows = _load_index(cache_dir)
    if only_ok:
        rows = [r for r in rows if r.get("frozen_ok", True)]
    if since is not None:
        rows = [r for r in rows if (r.get("opened_at") or "") >= since]
    if provisional is not None:
        rows = [r for r in rows if bool(r.get("provisional")) == provisional]
    if parked_for is not None:
        rows = [r for r in rows if r.get("parked_for") == parked_for]
    if parked_reason is not None:
        rows = [r for r in rows if r.get("parked_reason") == parked_reason]
    if record_id is not None:
        rows = [r for r in rows if record_id in (r.get("records") or [])]
    return sorted(rows, key=lambda r: r["case"])


# -------------------------------------------------------------- receipt

#: Fold r1 (F1): a receipt line's KEY is ``(sheet sha256 short, item
#: index)`` -- parsed back out of the rendered line text itself, since
#: the Application section is the only place a prior run's identity
#: survives (there is no second, structured store). ``item=0`` is F8's
#: whole-sheet-refusal shape (a sheet the preflight stopped before any
#: item ever dispatched). A line with no parseable key (hand-written
#: text, or a receipt predating this format) has nothing to match and
#: is preserved verbatim by :func:`_merge_receipt_lines` below -- never
#: dropped.
_RECEIPT_ITEM_KEY_RE = re.compile(r"sheet=\S*#([0-9a-f]{6,64}) item=(\d+) ")
_RECEIPT_REFUSAL_KEY_RE = re.compile(r"sheet=\S*#([0-9a-f]{6,64}) refused before item 1:")


def _receipt_line_key(line: str) -> tuple[str, int] | None:
    m = _RECEIPT_ITEM_KEY_RE.search(line)
    if m is not None:
        return (m.group(1), int(m.group(2)))
    m = _RECEIPT_REFUSAL_KEY_RE.search(line)
    if m is not None:
        return (m.group(1), 0)
    return None


def _merge_receipt_lines(
    existing_lines: list[str], new_by_key: dict[tuple[str, int], str]
) -> list[str]:
    """F1: receipts are keyed, never appended blindly. A key already
    present among *existing_lines* gets the NEW rendering in its OLD
    position (a re-run of the SAME sheet — same ``sheet_sha`` — REPLACES
    that item's line, whatever its previous state was: this is what
    makes a pre-applied item's missing line reappear, a refused item's
    re-run stop duplicating, and a failed receipt's retry repair the
    gap, all the SAME mechanism). A key not yet present is appended, in
    item order — which is also what makes "a different sheet against
    the same case adds its own block" true: every line from a
    differently-CONTENTED sheet carries a different ``sheet_sha``, so
    none of them match an existing key and they land together at the
    end. A line whose key cannot be parsed (pre-fold-r1 text, or a
    hand-edit) is preserved exactly, never dropped."""
    out: list[str] = []
    seen: set[tuple[str, int]] = set()
    for ln in existing_lines:
        key = _receipt_line_key(ln)
        if key is not None and key in new_by_key:
            out.append(new_by_key[key])
            seen.add(key)
        else:
            out.append(ln)
    for key in sorted(new_by_key, key=lambda k: k[1]):
        if key not in seen:
            out.append(new_by_key[key])
    return out


def receipt(home: Path | str, case_id: str, batch_result: dict) -> str:
    """Append (fold r1: MERGE — see :func:`_merge_receipt_lines`) the
    Application section from a batch result (§3a.2 section 5) — one
    line per sheet item, including `already-applied` and `not-attempted`
    for items after `stopped_at`, plus a `stopped` line for the one item
    that actually halted the sheet. Never edits the frozen sections 1-4;
    refuses if they were tampered with. N1: no `by` parameter — §3a.2's
    section-5 line format carries no actor, so this never stored it
    (probe confirmed `by` never reached the file); the dead parameter is
    gone.

    *batch_result* shape (`batch.run()`'s own `to_json()["items"]`/
    `.summary` shape, threaded straight through by `cli._cmd_batch`):

        {"sheet": "01.yaml", "sheet_sha": "<8-hex, optional>",
         "at": "<iso, optional>", "stopped_at": <int|None>,
         "code": <int, only used if stopped_at>, "stop_message": "<str,
         optional — F8's whole-sheet-refusal reason>",
         "items": [{"n": 1, "id": "lrn-...", "verb": "reject",
                     "state": "applied", "rc": 0}, ...]}

    ``sheet_sha`` defaults to a hash of the bare ``sheet`` name when
    absent (every pre-existing direct caller — this module's own test
    suite included) so the keying below always has an identity to work
    with. Fold r1 (F8): ``items: []`` (or absent) renders ONE line
    instead of none — the whole-sheet-refusal shape, keyed ``(sheet_sha,
    0)`` — rather than silently writing nothing, which the OLD zero-item
    path did (and which then hit a dead "commit produced nothing" guard
    the moment nothing had genuinely changed; gate-u3-r1.md F8/probe5).
    Otherwise: every item with ``n <= stopped_at`` (or every item, when
    ``stopped_at`` is None) renders from its own `state`/`rc`; every item
    with ``n > stopped_at`` renders `not-attempted (stopped_at=N, code C)`
    regardless of any state field present — the tail loop that does this
    is exactly what mutation check (d) pins."""
    home = Path(home)
    path = _case_path_for_id(home, case_id)

    at = batch_result.get("at") or chrono.now_iso()
    sheet = batch_result.get("sheet", "")
    sheet_sha = batch_result.get("sheet_sha") or hashlib.sha256(
        sheet.encode("utf-8")
    ).hexdigest()[:8]
    stopped_at = batch_result.get("stopped_at")
    code = batch_result.get("code")
    items = sorted(batch_result.get("items") or [], key=lambda it: it["n"])

    new_by_key: dict[tuple[str, int], str] = {}
    if not items:
        # F8: the sheet-level preflight refused the WHOLE sheet before
        # item 1 ever dispatched — section 5 still gets a line for it,
        # keyed (sheet_sha, 0).
        reason = batch_result.get("stop_message") or (
            f"refused before item 1 (code {code})"
            if code is not None else "refused before item 1"
        )
        new_by_key[(sheet_sha, 0)] = (
            f"- {at} sheet={sheet}#{sheet_sha} refused before item 1: {reason}"
        )
    else:
        for item in items:
            n = item["n"]
            rid = item["id"]
            verb = item["verb"]
            key = (sheet_sha, n)
            if stopped_at is not None and n > stopped_at:
                new_by_key[key] = (
                    f"- {at} sheet={sheet}#{sheet_sha} item={n} {rid} {verb} → "
                    f"not-attempted (stopped_at={stopped_at}, code {code})"
                )
            else:
                state = item.get("state", "applied")
                rc = item.get("rc", 0)
                warnings = item.get("warnings") or []
                warning_suffix = (
                    f"; warnings: {' | '.join(str(warning) for warning in warnings)}"
                    if warnings else ""
                )
                evidence = item.get("evidence")
                evidence_suffix = (
                    f"; evidence: {evidence}" if evidence is not None else ""
                )
                if state == "unresolved-host":
                    detail = item.get("detail")
                    new_by_key[key] = (
                        f"- {at} sheet={sheet}#{sheet_sha} item={n} {rid} {verb} → "
                        f"unresolved-host: {detail}{warning_suffix}{evidence_suffix}"
                    )
                else:
                    new_by_key[key] = (
                        f"- {at} sheet={sheet}#{sheet_sha} item={n} {rid} {verb} → "
                        f"{state} (exit {rc}){warning_suffix}{evidence_suffix}"
                    )
    new_lines = list(new_by_key.values())

    # B2 (item 2): scan every rendered line before it can reach the
    # committed file — receipt previously scanned nothing at all.
    _scan_or_refuse(new_lines)
    # Gate r2 S1: `record`/`observe` already refuse a heading-shaped
    # line in their own free text (D-i) — `receipt` scanned its lines
    # but never refused one, so a batch-result `verb` containing
    # `"\n\n## Later observations\n..."` could forge an append-only
    # entry. Refused the same way, before anything is written.
    _refuse_headings(new_lines)

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            text = path.read_text(encoding="utf-8")
            fm, body = _split_frontmatter(text)
            frozen_text, _rest = _split_frozen(body)
            if _hash_frozen(frozen_text) != fm.get("decided_sha256"):
                raise CaseError(
                    f"case receipt: {case_id} failed its freeze-hash check — refusing to append"
                )
            sections = _parse_sections(body)
            existing = sections.get("Application", "").strip()
            existing = "" if existing == "(none)" else existing
            existing_lines = [ln for ln in existing.splitlines() if ln.strip()]
            # F1: replace by (sheet_sha, n) key, never append blindly.
            merged_lines = _merge_receipt_lines(existing_lines, new_by_key)
            merged = "\n".join(merged_lines)
            new_body = _rebuild_body(frozen_text, merged or "(none)", sections.get("Later observations", "(none)"))
            new_text = _render_frontmatter(fm) + new_body
            if new_text == text:
                return case_id
            message = f"self-learn: case receipt {case_id} (sheet={sheet})"
            intent = intents.begin(home, "case-receipt", [path], message)
            fsops.atomic_write(path, new_text, fsync=True)
            intents.complete(intent)
            sha = gitops.stage_and_commit(home, [path], message, None)
            if sha is None:  # pragma: no cover — never allow_empty here
                raise CaseError("case receipt: internal — commit produced nothing")
            intents.finish(intent)
            _update_index(home, case_id)
    finally:
        hold.release()
    return case_id


def _rebuild_body(frozen_text: str, application_text: str, later_text: str) -> str:
    later_text = later_text.strip() or "(none)"
    return (
        frozen_text
        + _FROZEN_MARKER.rstrip("\n")
        + "\n"
        + application_text
        + "\n\n## Later observations\n"
        + later_text
        + "\n"
    )


# -------------------------------------------------------------- observe


def _new_obs_id(existing_text: str) -> str:
    for _ in range(64):
        candidate = "obs-" + uuid.uuid4().hex[:8]
        if candidate not in existing_text:
            return candidate
    raise CaseError("case observe: could not allocate a unique observation id")  # pragma: no cover


def observe(
    home: Path | str,
    case_id: str,
    kind: str,
    *,
    text: str,
    by: str,
    ref: str | None = None,
    to: str | None = None,
    covering: str | None = None,
    entries: list[str] | None = None,
    outcome: str | None = None,
    via: str | None = None,
    reserved_id: str | None = None,
) -> str:
    """Append one Later-observations entry (§3a.2 section 6). A
    `presented` observation ALSO writes the frontmatter `presented` entry
    (never a separate flag) and flips every id in `entries`. B1 (item 1):
    every id in `entries` is validated (`user_model._validate_seen`)
    BEFORE anything is written anywhere — raising on the first invalid
    id leaves neither file touched. Gate r2 S2: the case file is then
    written FIRST, then the user-model flip (`user_model._apply_seen`)
    — both writes bracketed by `intents.begin`/`complete`/`finish`
    exactly as `verbs._execute_route`'s collapse path brackets its own
    multi-file writes, inside this same held lock. A CRASH between the
    two writes (after the case file lands, before the user-model flip)
    is recoverable on the next `ledger_write` acquisition: `intents.
    recover` either rolls the transaction all the way forward (both
    files verified at their final content -> one commit) or restores it
    all the way back (both files returned to their pre-observe content)
    — never a flip stranded without its presentation, and never a
    presentation stranded without its flip. The case file's write plus
    the user-model flip land in ONE commit either way
    (`gitops.stage_and_commit(home, touched, ...)`, `touched` naming
    both paths when entries is non-empty).

    D-g: a `presented` observation is refused unless `to == "human"`;
    `via` is required and must be one of `VIA_VALUES` (N4, gate r2 S5).

    A `statement`/`dependency-moved` observation whose `ref` names one of
    the case's own section-4 dependencies is, per §3a.2, supposed to
    mechanically enqueue a `trigger: reconsider` case for the steward's
    next run (`<cache>/steward/reconsider-queue.jsonl`). That queue is
    U5's build (out of scope here per the U2 brief: "no reconsider"); the
    observation itself is recorded correctly, the enqueue side effect is
    NOT implemented — see the `# U5:` marker below."""
    home = Path(home)
    if kind not in OBSERVE_KINDS:
        raise CaseUsageError(f"case observe: kind must be one of {sorted(OBSERVE_KINDS)}, got {kind!r}")
    if by not in ACTORS:
        raise CaseUsageError(f"case observe: by must be one of {sorted(ACTORS)}, got {by!r}")
    if reserved_id is not None and re.fullmatch(r"obs-[0-9a-f]{8}", reserved_id) is None:
        raise CaseUsageError(
            f"case observe: malformed reserved observation id: {reserved_id!r}"
        )
    entries = list(entries or [])

    if kind == "presented":
        if to is None or covering is None or outcome is None:
            raise CaseUsageError("case observe --kind presented needs --to, --covering, --outcome")
        if to != "human":
            raise CaseError(
                f"case observe: a presented observation must be to='human', got {to!r} (D-g)"
            )
        if covering not in COVERING_VALUES:
            raise CaseUsageError(f"case observe: covering must be one of {sorted(COVERING_VALUES)}, got {covering!r}")
        if outcome not in PRESENTED_OUTCOMES:
            raise CaseUsageError(f"case observe: outcome must be one of {sorted(PRESENTED_OUTCOMES)}, got {outcome!r}")
        # Gate r2 S5 (settled ruling 3): `via` is REQUIRED on a
        # `presented` observation, not merely a member of the closed set
        # when given — `cli.py`'s `--via` stays optional at the argparse
        # layer (conditional-on-`--kind` requirement isn't expressible
        # there), so this is where it is actually enforced, the same way
        # `to`/`covering`/`outcome` are.
        if via is None or via not in VIA_VALUES:
            raise CaseUsageError(f"case observe: via is required on a presented observation and must be one of {sorted(VIA_VALUES)}, got {via!r}")
    elif outcome is not None:
        # N5: a presented-outcome value on any other kind used to be
        # silently discarded (the check above lived only inside the
        # `if kind == "presented":` branch, with no else refusal).
        raise CaseUsageError(
            f"case observe: outcome is only accepted when kind='presented', not {kind!r}"
        )

    # B2 (item 2): scan `text` AND `ref` — the original scanned `text`
    # only. D-i / B3 / S4: refuse a heading-shaped line in either.
    free_texts = [text] + ([ref] if ref is not None else [])
    _scan_or_refuse(free_texts)
    _refuse_headings(free_texts)

    hold = sentinel.hold()
    sentinel.heartbeat()
    try:
        with intents.ledger_write(home) as recovered:
            intents.announce_recovered(recovered)
            path = _case_path_for_id(home, case_id)
            content = path.read_text(encoding="utf-8")
            fm, body = _split_frontmatter(content)
            frozen_text, _rest = _split_frozen(body)
            if _hash_frozen(frozen_text) != fm.get("decided_sha256"):
                raise CaseError(
                    f"case observe: {case_id} failed its freeze-hash check — refusing to append"
                )
            sections = _parse_sections(body)
            at = chrono.now_iso()
            obs_id = reserved_id or _new_obs_id(content)

            expected_suffix = f"{by} {kind}: {text}"
            if ref is not None:
                expected_suffix += f" (ref: {ref})"
            if reserved_id is not None:
                committed = _committed_case_for_id(home, case_id)
                if committed is None:  # pragma: no cover — path lookup above found it
                    raise CaseError(
                        f"case observe: {case_id} is absent from committed truth"
                    )
                committed_path, committed_text = committed
                if committed_path != path:
                    raise CaseError(
                        f"case observe: committed path mismatch for {case_id}"
                    )
                _, committed_body = _split_frontmatter(committed_text)
                committed_sections = _parse_sections(committed_body)
                reserved_lines = [
                    line
                    for line in committed_sections.get(
                        "Later observations", ""
                    ).splitlines()
                    if line.startswith(f"- {obs_id} ")
                ]
                if len(reserved_lines) > 1:
                    raise CaseError(
                        f"case observe: reserved observation id collision for {obs_id}"
                    )
                if reserved_lines:
                    remainder = reserved_lines[0][len(f"- {obs_id} "):]
                    _timestamp, separator, actual_suffix = remainder.partition(" ")
                    if separator and actual_suffix == expected_suffix:
                        if content != committed_text:
                            raise CaseError(
                                f"case observe: reserved observation {obs_id} "
                                "has uncommitted incompatible content"
                            )
                        return obs_id
                    raise CaseError(
                        f"case observe: reserved observation id collision for {obs_id}"
                    )
                if f"- {obs_id} " in sections.get("Later observations", ""):
                    raise CaseError(
                        f"case observe: reserved observation id collision for {obs_id} "
                        "outside committed truth"
                    )

            line = f"- {obs_id} {at} {by} {kind}: {text}"
            if ref is not None:
                line += f" (ref: {ref})"
            existing_obs = sections.get("Later observations", "").strip()
            existing_obs = "" if existing_obs == "(none)" else existing_obs
            merged_obs = "\n".join(x for x in (existing_obs, line) if x)

            new_body = _rebuild_body(
                frozen_text,
                (sections.get("Application", "(none)").strip() or "(none)"),
                merged_obs,
            )

            touched = [path]
            if kind == "presented":
                presented_list = list(fm.get("presented") or [])
                presented_list.append(
                    {
                        "id": obs_id,
                        "at": at,
                        "to": to,
                        "covering": covering,
                        "entries": list(entries),
                        "outcome": outcome,
                        "via": via,
                    }
                )
                fm = dict(fm)
                fm["presented"] = presented_list

            # B1 (item 1): validate EVERY named entry, inside this SAME
            # lock span, BEFORE anything is written — raises on the
            # FIRST invalid/unknown/ineligible id with NEITHER file
            # touched. `_validate_seen` performs no writes.
            um_fm = um_containers = um_targets = None
            if kind == "presented" and entries:
                um_fm, um_containers, um_targets = user_model._validate_seen(home, entries)

            # Gate r2 S2: bracket the (up to) two-file publication with
            # an intent, opened before the FIRST mutation below, so a
            # crash between the case write and the user-model flip is
            # recoverable rather than stranding one half.
            intent_paths = [path]
            um_path: Path | None = None
            if kind == "presented" and entries:
                um_path = user_model._doc_path(home)
                intent_paths.append(um_path)
            message = f"self-learn: case observe {case_id} ({kind})"
            intent = intents.begin(
                home,
                "case-observe-presented" if len(intent_paths) > 1 else "case-observe",
                intent_paths,
                message,
            )

            # The case file is written FIRST (settled ordering) — then
            # the user-model flip, using the already-validated targets.
            fsops.atomic_write(path, _render_frontmatter(fm) + new_body, fsync=True)

            if kind == "presented" and entries:
                assert um_fm is not None and um_containers is not None and um_targets is not None
                written_um_path = user_model._apply_seen(home, um_fm, um_containers, um_targets)
                touched.append(written_um_path)

            # All writes have now landed — ordinary observations and the
            # presented two-file form use the same publication discipline.
            intents.complete(intent)

            # U5: a `statement`/`dependency-moved` observation whose `ref`
            # names a section-4 dependency should enqueue this case for
            # the steward's next `reconsider` run here. Deferred — see
            # docstring.

            sha = gitops.stage_and_commit(home, touched, message, text)
            if sha is None:  # pragma: no cover
                raise CaseError("case observe: internal — commit produced nothing")
            intents.finish(intent)
            _update_index(home, case_id)
    finally:
        hold.release()
    return obs_id
