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
    list_cases(home, **filters) -> list[dict]
    rebuild_index(cache_dir, home) -> Path
    receipt(home, case_id, batch_result, *, by) -> str        # obs id? -> commit sha
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

import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from . import gitops, intents, sentinel, user_model
from .primitives import chrono, fsops
from .primitives.yamlio import rt_yaml
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
    "CASE_ID_RE",
    "CaseError",
    "CaseUsageError",
    "CaseView",
    "record",
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
        "authority-unclear", "scope-conflict",
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


def _split_frozen(body: str) -> tuple[str, str]:
    """(frozen sections 1-4 text, rest) split on the one marker this
    module ever writes between them."""
    idx = body.find(_FROZEN_MARKER)
    if idx == -1:
        raise CaseError("case: file has no '## Application' section — malformed")
    return body[:idx], body[idx + 2 :]  # rest keeps its own leading "## Application..."


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
    itself), for the six known fixed headings, in file order."""
    pattern = re.compile(r"^## (" + "|".join(re.escape(h) for h in _SECTION_ORDER) + r")\n", re.MULTILINE)
    matches = list(pattern.finditer(body))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[m.group(1)] = body[start:end].rstrip("\n")
    return out


# --------------------------------------------------------------- record


def record(home: Path | str, stage_file: Path | str, *, actor: str) -> str:
    """Validate a stage file's six parts + closed sets, assign the id,
    secret-scan every free-text field, compute the freeze hash, write,
    commit. Returns the new case id."""
    home = Path(home)
    stage = Path(stage_file)
    if actor not in ACTORS:
        raise CaseUsageError(f"case record: actor must be one of {sorted(ACTORS)}, got {actor!r}")
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

    # Secret scan every free-text field BEFORE any write (02 §3a.2:
    # "secret-scan every free-text field with scan.scan"). Scans the
    # STAGE's inputs, never the rendered file — the rendered frontmatter
    # carries `decided_sha256`, a 64-char hex string that would trip the
    # scanner's own high-entropy-hex rule (>=48 chars) if it were ever
    # fed back through this same scan.
    free_texts = [question, str(decision.get("because"))]
    free_texts += [str(b) for b in what_would_change]
    free_texts += [str(item.get("quote", "")) for item in evidence]
    _scan_or_refuse(free_texts)

    opened_at = chrono.now_iso()
    case_id = _new_case_id(home)

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
            month = _ensure_case_dirs(home, opened_at)
            path = month / f"{case_id}.md"
            fsops.atomic_write(path, file_text, fsync=True)
            touched = [path]

            supersedes_path: Path | None = None
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
                sup_fm["superseded_by"] = case_id
                fsops.atomic_write(
                    supersedes_path, _render_frontmatter(sup_fm) + sup_body, fsync=True
                )
                touched.append(supersedes_path)

            message = f"self-learn: case record {case_id} ({outcome})"
            sha = gitops.stage_and_commit(home, touched, message, question)
            if sha is None:  # pragma: no cover — never allow_empty here
                raise CaseError("case record: internal — commit produced nothing")
            _update_index(home, case_id)
            if supersedes_path is not None:
                _update_index(home, str(supersedes))
    finally:
        hold.release()

    return case_id


# ----------------------------------------------------------------- show


@dataclass
class CaseView:
    case_id: str
    evidence_only: bool
    frontmatter: dict = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)

    def to_text(self) -> str:
        lines = [f"case: {self.case_id}"]
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


_BLIND_FRONTMATTER_DROPS = frozenset({"outcome", "superseded_by", "parked_for", "parked_reason"})
_BLIND_SECTIONS = ("Identity and scope", "Evidence", "Dependencies")


def show(home: Path | str, case_id: str, *, evidence_only: bool = True) -> CaseView:
    """Two views (§3a.2): the evidence-only view is blind by default —
    frontmatter without outcome/superseded_by/parked_for/parked_reason,
    sections 1/2/4 only. `evidence_only=False` is the full view,
    everything. Re-verifies the freeze hash before returning either
    view; refuses on mismatch."""
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
        fm_view = {k: v for k, v in fm.items() if k not in _BLIND_FRONTMATTER_DROPS}
        sections_view = {h: sections[h] for h in _BLIND_SECTIONS if h in sections}
    else:
        fm_view = dict(fm)
        sections_view = dict(sections)

    return CaseView(case_id=case_id, evidence_only=evidence_only, frontmatter=fm_view, sections=sections_view)


# ------------------------------------------------------------- index


def _index_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / "cases" / "index.json"


def _index_row(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)
    sections = _parse_sections(body)
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
    return {
        "case": fm.get("case"),
        "opened_at": fm.get("opened_at"),
        "actor": fm.get("actor"),
        "kind": fm.get("kind"),
        "trigger": fm.get("trigger"),
        "outcome": fm.get("outcome"),
        "records": list(fm.get("records") or []),
        "supersedes": fm.get("supersedes"),
        "superseded_by": fm.get("superseded_by"),
        "parked_for": fm.get("parked_for"),
        "parked_reason": fm.get("parked_reason"),
        "provisional": provisional,
        "presented_count": len(presented),
        "dependency_refs": dependency_refs,
        "last_observation_at": last_obs_at,
    }


def _serialize_index(rows: list[dict]) -> str:
    rows_sorted = sorted(rows, key=lambda r: r["case"])
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


def _update_index(home: Path, case_id: str) -> Path:
    """Incremental upsert (§1.8: "the CLI updates it incrementally after
    each write") — cache-only, `NOT_REPO_TRUTH`, never inside the ledger
    lock. Recomputes the row from the FILE it just wrote (never from
    in-memory state) so this path and :func:`rebuild_index` are the same
    pure function of file content, byte for byte."""
    from . import worker

    cache_dir = worker.cache_dir(home)
    rows = [r for r in _load_index(cache_dir) if r["case"] != case_id]
    path = _case_path_for_id(home, case_id)
    rows.append(_index_row(path))
    return _write_index(cache_dir, rows)


def rebuild_index(cache_dir: Path | str, home: Path | str) -> Path:
    """Rebuild `<cache>/cases/index.json` from the case files on disk.
    Cache-only (`NOT_REPO_TRUTH`) — never touches the ledger lock."""
    home = Path(home)
    rows = [_index_row(p) for p in sorted(_cases_root(home).glob("*/case-*.md"))]
    return _write_index(Path(cache_dir), rows)


def list_cases(
    home: Path | str,
    *,
    since: str | None = None,
    provisional: bool | None = None,
    parked_for: str | None = None,
    parked_reason: str | None = None,
    record_id: str | None = None,
) -> list[dict]:
    """Query the index (rebuilding it first if it does not exist yet —
    every writer keeps it current afterward via incremental upserts)."""
    from . import worker

    home = Path(home)
    cache_dir = worker.cache_dir(home)
    if not _index_path(cache_dir).exists():
        rebuild_index(cache_dir, home)
    rows = _load_index(cache_dir)
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


def receipt(home: Path | str, case_id: str, batch_result: dict, *, by: str = "human") -> str:
    """Append the Application section from a batch result (§3a.2 section
    5) — one line per sheet item, including `not-attempted` for items
    after `stopped_at`. Never edits the frozen sections 1-4; refuses if
    they were tampered with.

    *batch_result* shape (this module's own contract for U2 — U3 wires
    the real `batch.run()` producer; see this module's own docstring):

        {"sheet": "01.yaml", "at": "<iso, optional>",
         "stopped_at": <int|None>, "code": <int, only used if stopped_at>,
         "items": [{"n": 1, "id": "lrn-...", "verb": "reject",
                     "state": "applied", "rc": 0}, ...]}

    Every item with ``n <= stopped_at`` (or every item, when
    ``stopped_at`` is None) renders from its own `state`/`rc`; every item
    with ``n > stopped_at`` renders `not-attempted (stopped_at=N, code C)`
    regardless of any state field present — the tail loop that does this
    is exactly what mutation check (d) pins."""
    home = Path(home)
    path = _case_path_for_id(home, case_id)

    at = batch_result.get("at") or chrono.now_iso()
    sheet = batch_result.get("sheet", "")
    stopped_at = batch_result.get("stopped_at")
    code = batch_result.get("code")
    items = sorted(batch_result.get("items") or [], key=lambda it: it["n"])

    lines: list[str] = []
    for item in items:
        n = item["n"]
        rid = item["id"]
        verb = item["verb"]
        if stopped_at is not None and n > stopped_at:
            lines.append(
                f"- {at} sheet={sheet} item={n} {rid} {verb} → "
                f"not-attempted (stopped_at={stopped_at}, code {code})"
            )
        else:
            state = item.get("state", "applied")
            rc = item.get("rc", 0)
            lines.append(f"- {at} sheet={sheet} item={n} {rid} {verb} → {state} (exit {rc})")
    new_text = "\n".join(lines)

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
            merged = "\n".join(x for x in (existing, new_text) if x)
            new_body = _rebuild_body(frozen_text, merged or "(none)", sections.get("Later observations", "(none)"))
            fsops.atomic_write(path, _render_frontmatter(fm) + new_body, fsync=True)
            message = f"self-learn: case receipt {case_id} (sheet={sheet})"
            sha = gitops.stage_and_commit(home, [path], message, None)
            if sha is None:  # pragma: no cover
                raise CaseError("case receipt: internal — commit produced nothing")
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
) -> str:
    """Append one Later-observations entry (§3a.2 section 6). A
    `presented` observation ALSO writes the frontmatter `presented` entry
    (never a separate flag) and calls `user_model.mark_seen` for every id
    in `entries`, BEFORE the case file's own write — `mark_seen` is a
    self-contained mini-verb with its own lock span and its own commit
    (a nested, pass-through acquire of the same ledger lock, so nothing
    else can interleave), so an observation naming an unknown or
    ineligible entry id refuses before the case file is ever touched;
    the case file and user-model.md land as two separate commits inside
    one held lock, not one shared commit.

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
    entries = list(entries or [])

    if kind == "presented":
        if to is None or covering is None or outcome is None:
            raise CaseUsageError("case observe --kind presented needs --to, --covering, --outcome")
        if covering not in COVERING_VALUES:
            raise CaseUsageError(f"case observe: covering must be one of {sorted(COVERING_VALUES)}, got {covering!r}")
        if outcome not in PRESENTED_OUTCOMES:
            raise CaseUsageError(f"case observe: outcome must be one of {sorted(PRESENTED_OUTCOMES)}, got {outcome!r}")

    _scan_or_refuse([text])

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
            obs_id = _new_obs_id(content)

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

            # `mark_seen` is its own self-contained mini-verb (own lock
            # span, own commit — see its docstring): called BEFORE this
            # observation's own write/commit so an unknown/ineligible
            # entry id refuses here without ever touching the case file.
            # This is a nested acquire of the SAME lock (safe, pass-
            # through per `intents.ledger_write`), so nothing else can
            # interleave between the two commits even though they land
            # separately.
            if kind == "presented":
                for entry_id in entries:
                    user_model.mark_seen(home, entry_id)

            fsops.atomic_write(path, _render_frontmatter(fm) + new_body, fsync=True)

            # U5: a `statement`/`dependency-moved` observation whose `ref`
            # names a section-4 dependency should enqueue this case for
            # the steward's next `reconsider` run here. Deferred — see
            # docstring.

            message = f"self-learn: case observe {case_id} ({kind})"
            sha = gitops.stage_and_commit(home, touched, message, text)
            if sha is None:  # pragma: no cover
                raise CaseError("case observe: internal — commit produced nothing")
            _update_index(home, case_id)
    finally:
        hold.release()
    return obs_id
