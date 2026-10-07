"""The session miner's output contract (U4, spec 02-schema.md "Session miner
output (miner-output/1)").

Three documents, one module, no I/O beyond :func:`load_run`:

- the **model output** (``miner-output-model/1``) -- what the model writes as
  its whole final message: small, line numbers and quotes only, nothing code
  can fill in itself;
- the **checked output** (``miner-output/1``) -- what code makes of it after
  the engine's checks: every pointer a full transcript ref (``refs.Ref``),
  every quote with a verdict, every dropped unit listed with its reason;
- the **run record** (``miner-shadow-run/1``) -- one per shadow run.

The validators are hand-written (the CLI carries no ``jsonschema``
dependency). Each returns a list of messages, empty when the document is
valid, and every message starts with the path of the offending field
(``lessons[0].evidence[1].quote: longer than 400``). A message never echoes a
value of the document: a model's text is not safe to print, and a key name
the model invented is echoed only when it is a plain identifier.
:func:`model_output_json_schema` builds, from the same constants, the JSON
Schema document the model's instructions show; it is not used to validate.

Enums come from their owners and are never retyped here: ``records.TYPES``,
``records.KINDS``, ``records.GENERALITIES``, ``refs.ROLES``, ``refs.VERDICTS``.

Two helpers define what a *typed turn* is, once, so the engine's spine and
the comparison harness cannot drift: :func:`has_typed_turn_marker`,
:func:`typed_turn_lines`, :func:`turn_of`.
"""

from __future__ import annotations

import bisect
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .. import records, refs

__all__ = [
    "BASES",
    "CHECKED_CONTRACT",
    "COST_TEXT_MAX",
    "Checked",
    "ContractError",
    "DROP_DETAIL_MAX",
    "DROP_REASONS",
    "EVIDENCE_VERDICTS",
    "HOW_MAX",
    "LESSON_ID_PATTERN",
    "MAX_EVIDENCE",
    "MAX_LESSONS",
    "MAX_RULE_CHECKS",
    "MAX_SIGHTINGS",
    "MAX_SIGHTING_EVIDENCE",
    "MAX_STEPS",
    "MIN_STEPS",
    "MODEL_CONTRACT",
    "MODES",
    "NOT_RUN_REASONS",
    "OUTCOMES",
    "OUT_STATUSES",
    "QUOTE_MAX",
    "RECORD_ID_PATTERN",
    "RUN_CONTRACT",
    "RUN_STATUSES",
    "Run",
    "SEARCH_MODES",
    "SCOPE_PATTERN",
    "SESSION_STATUSES",
    "SHAPES",
    "SKIP_REASONS",
    "STEP_WHAT_MAX",
    "SUBAGENT_CAUSES",
    "SUBAGENT_PATTERN",
    "TEXT_MAX",
    "WHY_DURABLE_MAX",
    "has_typed_turn_marker",
    "load_run",
    "model_output_json_schema",
    "turn_of",
    "typed_turn_lines",
    "validate_checked_output",
    "validate_model_output",
    "validate_run",
]

MODEL_CONTRACT = "miner-output-model/1"
CHECKED_CONTRACT = "miner-output/1"
RUN_CONTRACT = "miner-shadow-run/1"

#: The rubric's four lesson shapes.
SHAPES: tuple[str, ...] = ("correction", "verified-gotcha", "standing-preference", "repeated-friction")
#: Which party failed when a subagent was involved.
SUBAGENT_CAUSES: tuple[str, ...] = ("bad-brief", "left-brief", "unchecked-report")
#: A rule check's three outcomes (the ledger's ``fire`` vocabulary).
OUTCOMES: tuple[str, ...] = ("suspected-compliance", "suspected-violation", "cannot-tell")
#: Why the engine's checks removed a unit; closed. Each is defined by one step
#: of the spec's checks on everything the model returns.
DROP_REASONS: tuple[str, ...] = (
    "over-count",
    "line-unresolved",
    "out-of-range",
    "quote-stitched",
    "quote-not-found",
    "already-judged",
    "duplicate",
    "no-evidence",
    "no-user-evidence",
    "verification-unchecked",
    "incident-cost-unresolved",
    "steps-unresolved",
    "unknown-record",
    "not-flagged",
    "bad-output",
)
#: A quote's verdict once it is kept: the four ``refs.check_quote`` outcomes
#: that keep a ref (``stitched``, ``other_session`` and ``not_found`` drop it).
EVIDENCE_VERDICTS: tuple[str, ...] = tuple(
    v for v in refs.VERDICTS if v not in ("stitched", "other_session", "not_found")
)
MODES: tuple[str, ...] = ("testset", "night")
OUT_STATUSES: tuple[str, ...] = ("ok", "bad-output", "failed")
SEARCH_MODES: tuple[str, ...] = ("hybrid", "lexical-only")
#: How a flag matched a stretch.
BASES: tuple[str, ...] = ("lexical", "lexical+meaning")
RUN_STATUSES: tuple[str, ...] = ("ok", "stopped-ceiling", "failed", "dry-run", "activated")
SESSION_STATUSES: tuple[str, ...] = ("called", "skipped", "not-run")
#: Why a session was skipped (the run record's ``skipped`` reasons) ...
SKIP_REASONS: tuple[str, ...] = ("no-marker", "no-typed-turns", "nothing-new", "halted")
#: ... and why one was planned but not run.
NOT_RUN_REASONS: tuple[str, ...] = ("spend-ceiling",)

# Count and length limits (the spec's section on the model output).
MAX_LESSONS = 10
MAX_SIGHTINGS = 20
MAX_RULE_CHECKS = 8
MAX_EVIDENCE = 4
MAX_SIGHTING_EVIDENCE = 3
MIN_STEPS = 2
MAX_STEPS = 6
QUOTE_MAX = 400
TEXT_MAX = 1000
STEP_WHAT_MAX = 300
HOW_MAX = 300
COST_TEXT_MAX = 300
WHY_DURABLE_MAX = 300
DROP_DETAIL_MAX = 200

#: The ledger's own record-id rule, reused (``records.RECORD_ID_RE``).
RECORD_ID_PATTERN = records.RECORD_ID_RE.pattern
SUBAGENT_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
LESSON_ID_PATTERN = r"^L(10|[1-9])$"
SCOPE_PATTERN = r"^(user|project|skill:.+)$"

_SUBAGENT_RE = re.compile(SUBAGENT_PATTERN)
_LESSON_ID_RE = re.compile(LESSON_ID_PATTERN)
_RECORD_ID_RE = records.RECORD_ID_RE
#: A drop's ``item`` is a path into the model output: ``output``, ``L2``,
#: ``L2.evidence[1]``, ``sightings[3].evidence[0]``, ``rule_checks[0]``.
_DROP_ITEM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?)*$")
_PLAIN_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")

Run = dict[str, Any]
Checked = dict[str, Any]


class ContractError(ValueError):
    """A run folder (or one of its files) that fails its contract. ``errors``
    holds every message, each naming the file and the path inside it."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors[:5]))


# --------------------------------------------------------- validator helpers


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _idx(path: str, i: int) -> str:
    return f"{path}[{i}]"


class _V:
    """Collects messages; every check returns whether the value was usable."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, path: str, msg: str) -> None:
        self.errors.append(f"{path or '$'}: {msg}")

    def obj(
        self,
        path: str,
        v: object,
        required: Sequence[str],
        optional: Sequence[str] = (),
    ) -> dict[str, Any] | None:
        if not isinstance(v, dict):
            self.err(path, "not an object")
            return None
        for k in required:
            if k not in v:
                self.err(_join(path, k), "missing")
        known = set(required) | set(optional)
        unknown = [k for k in v if k not in known]
        for k in sorted(unknown, key=str):
            if isinstance(k, str) and _PLAIN_KEY_RE.match(k):
                self.err(_join(path, k), "unknown key")
            else:
                self.err(path, "unknown key (not a plain identifier)")
        return v

    def string(self, path: str, v: object, lo: int, hi: int, *, nullable: bool = False) -> bool:
        if v is None and nullable:
            return True
        if not isinstance(v, str):
            self.err(path, "not a string" if not nullable else "not a string or null")
            return False
        if len(v) > hi:
            self.err(path, f"longer than {hi}")
            return False
        if len(v) < lo:
            self.err(path, f"shorter than {lo}")
            return False
        return True

    def integer(
        self, path: str, v: object, *, lo: int | None = None, nullable: bool = False
    ) -> bool:
        if v is None and nullable:
            return True
        if not _is_int(v):
            self.err(path, "not an integer" if not nullable else "not an integer or null")
            return False
        assert isinstance(v, int)
        if lo is not None and v < lo:
            self.err(path, f"less than {lo}")
            return False
        return True

    def number(self, path: str, v: object, *, nullable: bool = False) -> bool:
        if v is None and nullable:
            return True
        if not _is_number(v):
            self.err(path, "not a number" if not nullable else "not a number or null")
            return False
        assert isinstance(v, (int, float))
        if v < 0:
            self.err(path, "negative")
            return False
        return True

    def boolean(self, path: str, v: object) -> bool:
        if not isinstance(v, bool):
            self.err(path, "not a boolean")
            return False
        return True

    def enum(self, path: str, v: object, allowed: Sequence[str], *, nullable: bool = False) -> bool:
        if v is None and nullable:
            return True
        if not isinstance(v, str) or v not in allowed:
            self.err(path, "not one of the allowed values")
            return False
        return True

    def matches(self, path: str, v: object, rx: re.Pattern[str]) -> bool:
        if not isinstance(v, str) or not rx.match(v):
            self.err(path, "does not match the required pattern")
            return False
        return True

    def array(self, path: str, v: object, lo: int, hi: int | None) -> list[Any] | None:
        if not isinstance(v, list):
            self.err(path, "not an array")
            return None
        if hi is not None and len(v) > hi:
            self.err(path, f"more than {hi} items")
        if len(v) < lo:
            self.err(path, f"fewer than {lo} items")
        return v

    def const(self, path: str, v: object, expected: str) -> bool:
        if v != expected:
            self.err(path, f"must be {expected!r}")
            return False
        return True

    def iso(self, path: str, v: object, *, nullable: bool = False) -> bool:
        if v is None and nullable:
            return True
        if not isinstance(v, str):
            self.err(path, "not a string" if not nullable else "not a string or null")
            return False
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            self.err(path, "not an ISO-8601 timestamp")
            return False
        return True

    def counter(self, path: str, v: object, keys: Sequence[str]) -> bool:
        """``{reason: int >= 0}`` with every key in the closed set."""
        if not isinstance(v, dict):
            self.err(path, "not an object")
            return False
        ok = True
        for k, n in v.items():
            if not isinstance(k, str) or k not in keys:
                self.err(path, "key not in the closed set")
                ok = False
            elif not self.integer(_join(path, k), n, lo=0):
                ok = False
        return ok


def _scope_ok(scope: object) -> bool:
    """The ledger's own rule (``records._validate_scope``), not a copy."""
    try:
        records._validate_scope(scope)  # pyright: ignore[reportPrivateUsage]
    except records.ValidationError:
        return False
    return True


# ------------------------------------------------------------ model output


def _point(v: _V, path: str, d: object, extra: Sequence[str] = ()) -> dict[str, Any] | None:
    """A model-output pointer: ``line`` plus an optional ``subagent``, plus
    the ``extra`` keys the caller checks itself."""
    o = v.obj(path, d, ("line", *extra), ("subagent",))
    if o is None:
        return None
    v.integer(_join(path, "line"), o.get("line"), lo=1)
    if "subagent" in o:
        v.matches(_join(path, "subagent"), o["subagent"], _SUBAGENT_RE)
    return o


def _quoted_point(v: _V, path: str, d: object, extra: Sequence[str] = ()) -> dict[str, Any] | None:
    o = _point(v, path, d, ("quote", *extra))
    if o is not None:
        v.string(_join(path, "quote"), o.get("quote"), 1, QUOTE_MAX)
    return o


def _model_lesson(v: _V, path: str, d: object) -> str | None:
    keys = (
        "id", "shape", "scope", "type", "kind", "trigger", "instruction", "fact", "context",
        "evidence", "steps", "verification", "incident_cost", "generality", "why_durable",
        "subagent_cause",
    )
    o = v.obj(path, d, keys)
    if o is None:
        return None
    lid = o.get("id")
    id_ok = v.matches(_join(path, "id"), lid, _LESSON_ID_RE)
    v.enum(_join(path, "shape"), o.get("shape"), SHAPES)
    if not _scope_ok(o.get("scope")):
        v.err(_join(path, "scope"), "not user, project or skill:<name>")
    type_ok = v.enum(_join(path, "type"), o.get("type"), sorted(records.TYPES))
    v.enum(_join(path, "kind"), o.get("kind"), sorted(records.KINDS))
    if type_ok:
        if o["type"] == "behavior":
            v.string(_join(path, "trigger"), o.get("trigger"), 1, TEXT_MAX)
            v.string(_join(path, "instruction"), o.get("instruction"), 1, TEXT_MAX)
            for k in ("fact", "context"):
                if o.get(k) is not None:
                    v.err(_join(path, k), "must be null for a behavior lesson")
        else:
            v.string(_join(path, "fact"), o.get("fact"), 1, TEXT_MAX)
            v.string(_join(path, "context"), o.get("context"), 1, TEXT_MAX, nullable=True)
            for k in ("trigger", "instruction"):
                if o.get(k) is not None:
                    v.err(_join(path, k), "must be null for a knowledge lesson")
    ev = v.array(_join(path, "evidence"), o.get("evidence"), 1, MAX_EVIDENCE)
    for i, e in enumerate(ev or []):
        _quoted_point(v, _idx(_join(path, "evidence"), i), e)
    steps = o.get("steps")
    if isinstance(steps, list):
        if len(steps) != 0 and not MIN_STEPS <= len(steps) <= MAX_STEPS:
            v.err(_join(path, "steps"), f"must hold 0 or {MIN_STEPS}..{MAX_STEPS} items")
    else:
        v.err(_join(path, "steps"), "not an array")
        steps = []
    for i, s in enumerate(steps):
        sp = _idx(_join(path, "steps"), i)
        so = _point(v, sp, s, ("what",))
        if so is not None:
            v.string(_join(sp, "what"), so.get("what"), 1, STEP_WHAT_MAX)
    ver = o.get("verification")
    if ver is not None:
        vo = _quoted_point(v, _join(path, "verification"), ver, ("how",))
        if vo is not None:
            v.string(_join(path, "verification.how"), vo.get("how"), 1, HOW_MAX)
    cost = o.get("incident_cost")
    if cost is not None:
        co = _point(v, _join(path, "incident_cost"), cost, ("text",))
        if co is not None:
            v.string(_join(path, "incident_cost.text"), co.get("text"), 1, COST_TEXT_MAX)
    v.enum(_join(path, "generality"), o.get("generality"), sorted(records.GENERALITIES))
    v.string(_join(path, "why_durable"), o.get("why_durable"), 1, WHY_DURABLE_MAX)
    v.enum(_join(path, "subagent_cause"), o.get("subagent_cause"), SUBAGENT_CAUSES, nullable=True)
    return lid if id_ok and isinstance(lid, str) else None


def validate_model_output(obj: object) -> list[str]:
    """Messages for every rule ``obj`` breaks; empty means valid."""
    v = _V()
    o = v.obj("", obj, ("contract", "lessons", "sightings", "rule_checks"))
    if o is None:
        return v.errors
    v.const("contract", o.get("contract"), MODEL_CONTRACT)
    seen: set[str] = set()
    lessons = v.array("lessons", o.get("lessons"), 0, MAX_LESSONS)
    for i, lesson in enumerate(lessons or []):
        lid = _model_lesson(v, _idx("lessons", i), lesson)
        if lid is not None:
            if lid in seen:
                v.err(_join(_idx("lessons", i), "id"), "duplicate id")
            seen.add(lid)
    sightings = v.array("sightings", o.get("sightings"), 0, MAX_SIGHTINGS)
    for i, s in enumerate(sightings or []):
        sp = _idx("sightings", i)
        so = v.obj(sp, s, ("record", "evidence"))
        if so is None:
            continue
        v.matches(_join(sp, "record"), so.get("record"), _RECORD_ID_RE)
        ev = v.array(_join(sp, "evidence"), so.get("evidence"), 1, MAX_SIGHTING_EVIDENCE)
        for j, e in enumerate(ev or []):
            _quoted_point(v, _idx(_join(sp, "evidence"), j), e)
    checks = v.array("rule_checks", o.get("rule_checks"), 0, MAX_RULE_CHECKS)
    for i, c in enumerate(checks or []):
        cp = _idx("rule_checks", i)
        co = v.obj(cp, c, ("record", "outcome", "situation", "action"))
        if co is None:
            continue
        v.matches(_join(cp, "record"), co.get("record"), _RECORD_ID_RE)
        v.enum(_join(cp, "outcome"), co.get("outcome"), OUTCOMES)
        _point(v, _join(cp, "situation"), co.get("situation"))
        if co.get("action") is not None:
            _point(v, _join(cp, "action"), co.get("action"))
    return v.errors


# ------------------------------------------------------------ checked output


def _ref_dict(v: _V, path: str, d: object) -> None:
    o = v.obj(
        path,
        d,
        ("session", "project_dir", "line", "uuid", "entry_ts", "cwd", "role"),
        ("subagent_file",),
    )
    if o is None:
        return
    v.string(_join(path, "session"), o.get("session"), 1, 10_000)
    v.string(_join(path, "project_dir"), o.get("project_dir"), 1, 10_000)
    v.integer(_join(path, "line"), o.get("line"), lo=1)
    for k in ("uuid", "entry_ts", "cwd"):
        v.string(_join(path, k), o.get(k), 0, 100_000, nullable=True)
    v.enum(_join(path, "role"), o.get("role"), refs.ROLES)
    if "subagent_file" in o:
        v.string(_join(path, "subagent_file"), o["subagent_file"], 1, 10_000)


def _pointer(v: _V, path: str, d: object, extra: Sequence[str] = ()) -> dict[str, Any] | None:
    o = v.obj(path, d, ("ref", "turn", *extra))
    if o is None:
        return None
    _ref_dict(v, _join(path, "ref"), o.get("ref"))
    v.integer(_join(path, "turn"), o.get("turn"), lo=0, nullable=True)
    return o


def _evidence(v: _V, path: str, d: object, extra: Sequence[str] = ()) -> dict[str, Any] | None:
    o = _pointer(v, path, d, ("quote", "verdict", "corrected_from", *extra))
    if o is None:
        return None
    v.string(_join(path, "quote"), o.get("quote"), 1, QUOTE_MAX)
    v.enum(_join(path, "verdict"), o.get("verdict"), EVIDENCE_VERDICTS)
    v.integer(_join(path, "corrected_from"), o.get("corrected_from"), lo=1, nullable=True)
    return o


def _checked_lesson(v: _V, path: str, d: object) -> str | None:
    if not isinstance(d, dict):
        v.err(path, "not an object")
        return None
    # The key set and the text fields follow the model-output rules exactly:
    # validate them through the same function on a copy whose pointer fields
    # are valid stand-ins, then check the pointer fields in their checked
    # shape. A key that is absent stays absent in the copy, so it is reported
    # once, as missing.
    stand_in = dict(d)
    for key, value in (
        ("evidence", [{"line": 1, "quote": "x"}]),
        ("steps", []),
        ("verification", None),
        ("incident_cost", None),
    ):
        if key in stand_in:
            stand_in[key] = value
    scratch = _V()
    lid = _model_lesson(scratch, path, stand_in)
    v.errors.extend(scratch.errors)
    if "evidence" in d:
        ev = v.array(_join(path, "evidence"), d["evidence"], 1, MAX_EVIDENCE)
        for i, e in enumerate(ev or []):
            _evidence(v, _idx(_join(path, "evidence"), i), e)
    if "steps" in d:
        steps = d["steps"]
        if isinstance(steps, list):
            if len(steps) != 0 and not MIN_STEPS <= len(steps) <= MAX_STEPS:
                v.err(_join(path, "steps"), f"must hold 0 or {MIN_STEPS}..{MAX_STEPS} items")
        else:
            v.err(_join(path, "steps"), "not an array")
            steps = []
        for i, s in enumerate(steps):
            sp = _idx(_join(path, "steps"), i)
            so = _pointer(v, sp, s, ("what",))
            if so is not None:
                v.string(_join(sp, "what"), so.get("what"), 1, STEP_WHAT_MAX)
    if d.get("verification") is not None:
        vp = _join(path, "verification")
        vo = _evidence(v, vp, d["verification"], ("how",))
        if vo is not None:
            v.string(_join(vp, "how"), vo.get("how"), 1, HOW_MAX)
    if d.get("incident_cost") is not None:
        cp = _join(path, "incident_cost")
        co = _pointer(v, cp, d["incident_cost"], ("text",))
        if co is not None:
            v.string(_join(cp, "text"), co.get("text"), 1, COST_TEXT_MAX)
    return lid


def validate_checked_output(obj: object) -> list[str]:
    """Messages for every rule ``obj`` breaks; empty means valid."""
    v = _V()
    o = v.obj(
        "",
        obj,
        (
            "contract", "run_id", "mode", "model", "method_version", "session", "status",
            "lessons", "sightings", "rule_checks", "drops", "redactions",
        ),
    )
    if o is None:
        return v.errors
    v.const("contract", o.get("contract"), CHECKED_CONTRACT)
    v.string("run_id", o.get("run_id"), 1, 200)
    v.enum("mode", o.get("mode"), MODES)
    v.string("model", o.get("model"), 1, 200)
    v.string("method_version", o.get("method_version"), 1, 200)
    status_ok = v.enum("status", o.get("status"), OUT_STATUSES)
    v.integer("redactions", o.get("redactions"), lo=0)

    s = v.obj(
        "session",
        o.get("session"),
        (
            "id", "project_dir", "file", "judged", "typed_turns", "spine_tokens_est",
            "over_budget", "search_mode", "flags",
        ),
    )
    if s is not None:
        v.string("session.id", s.get("id"), 1, 200)
        v.string("session.project_dir", s.get("project_dir"), 1, 10_000)
        v.string("session.file", s.get("file"), 1, 10_000)
        j = v.obj("session.judged", s.get("judged"), ("first_line", "last_line", "first_turn", "last_turn"))
        if j is not None:
            a = v.integer("session.judged.first_line", j.get("first_line"), lo=1)
            b = v.integer("session.judged.last_line", j.get("last_line"), lo=1)
            if a and b and j["last_line"] < j["first_line"]:
                v.err("session.judged.last_line", "before first_line")
            v.integer("session.judged.first_turn", j.get("first_turn"), lo=0, nullable=True)
            v.integer("session.judged.last_turn", j.get("last_turn"), lo=0, nullable=True)
        v.integer("session.typed_turns", s.get("typed_turns"), lo=0)
        v.integer("session.spine_tokens_est", s.get("spine_tokens_est"), lo=0)
        v.boolean("session.over_budget", s.get("over_budget"))
        v.enum("session.search_mode", s.get("search_mode"), SEARCH_MODES)
        flags = v.array("session.flags", s.get("flags"), 0, None)
        for i, f in enumerate(flags or []):
            fp = _idx("session.flags", i)
            fo = v.obj(fp, f, ("record", "turn", "basis"))
            if fo is not None:
                v.matches(_join(fp, "record"), fo.get("record"), _RECORD_ID_RE)
                v.integer(_join(fp, "turn"), fo.get("turn"), lo=0)
                v.enum(_join(fp, "basis"), fo.get("basis"), BASES)

    seen: set[str] = set()
    lessons = v.array("lessons", o.get("lessons"), 0, MAX_LESSONS)
    for i, lesson in enumerate(lessons or []):
        lid = _checked_lesson(v, _idx("lessons", i), lesson)
        if lid is not None:
            if lid in seen:
                v.err(_join(_idx("lessons", i), "id"), "duplicate id")
            seen.add(lid)
    sightings = v.array("sightings", o.get("sightings"), 0, MAX_SIGHTINGS)
    for i, sg in enumerate(sightings or []):
        sp = _idx("sightings", i)
        so = v.obj(sp, sg, ("record", "evidence"))
        if so is None:
            continue
        v.matches(_join(sp, "record"), so.get("record"), _RECORD_ID_RE)
        ev = v.array(_join(sp, "evidence"), so.get("evidence"), 1, MAX_SIGHTING_EVIDENCE)
        for j2, e in enumerate(ev or []):
            _evidence(v, _idx(_join(sp, "evidence"), j2), e)
    checks = v.array("rule_checks", o.get("rule_checks"), 0, MAX_RULE_CHECKS)
    for i, c in enumerate(checks or []):
        cp = _idx("rule_checks", i)
        co = v.obj(cp, c, ("record", "outcome", "situation", "action"))
        if co is None:
            continue
        v.matches(_join(cp, "record"), co.get("record"), _RECORD_ID_RE)
        v.enum(_join(cp, "outcome"), co.get("outcome"), OUTCOMES)
        _pointer(v, _join(cp, "situation"), co.get("situation"))
        if co.get("action") is not None:
            _pointer(v, _join(cp, "action"), co["action"])
    drops = v.array("drops", o.get("drops"), 0, None)
    for i, dr in enumerate(drops or []):
        dp = _idx("drops", i)
        do = v.obj(dp, dr, ("item", "reason", "detail"))
        if do is None:
            continue
        if v.string(_join(dp, "item"), do.get("item"), 1, 80):
            v.matches(_join(dp, "item"), do["item"], _DROP_ITEM_RE)
        v.enum(_join(dp, "reason"), do.get("reason"), DROP_REASONS)
        v.string(_join(dp, "detail"), do.get("detail"), 0, DROP_DETAIL_MAX)
    if status_ok and o["status"] != "ok":
        for k in ("lessons", "sightings", "rule_checks"):
            if isinstance(o.get(k), list) and o[k]:
                v.err(k, "must be empty unless the status is ok")
    return v.errors


# --------------------------------------------------------------- run record


def validate_run(obj: object) -> list[str]:
    """Messages for every rule ``obj`` breaks; empty means valid."""
    v = _V()
    o = v.obj(
        "",
        obj,
        (
            "contract", "run_id", "mode", "started_at", "finished_at", "model", "method_version",
            "settings", "testset", "status", "search_mode", "sessions", "totals",
        ),
    )
    if o is None:
        return v.errors
    v.const("contract", o.get("contract"), RUN_CONTRACT)
    v.string("run_id", o.get("run_id"), 1, 200)
    v.enum("mode", o.get("mode"), MODES)
    v.iso("started_at", o.get("started_at"))
    v.iso("finished_at", o.get("finished_at"), nullable=True)
    v.string("model", o.get("model"), 1, 200)
    v.string("method_version", o.get("method_version"), 1, 200)
    st = v.obj("settings", o.get("settings"), ("parallel", "spine_tokens", "max_usd"))
    if st is not None:
        v.integer("settings.parallel", st.get("parallel"), lo=1)
        v.integer("settings.spine_tokens", st.get("spine_tokens"), lo=1)
        v.number("settings.max_usd", st.get("max_usd"))
    ts = o.get("testset")
    if ts is not None:
        tso = v.obj("testset", ts, ("dir", "manifest_sha256"))
        if tso is not None:
            v.string("testset.dir", tso.get("dir"), 1, 10_000)
            v.matches("testset.manifest_sha256", tso.get("manifest_sha256"), re.compile(r"^[0-9a-f]{64}$"))
    v.enum("status", o.get("status"), RUN_STATUSES)
    v.enum("search_mode", o.get("search_mode"), SEARCH_MODES)

    called = not_run = 0
    skipped: dict[str, int] = {}
    sessions = v.array("sessions", o.get("sessions"), 0, None)
    for i, s in enumerate(sessions or []):
        sp = _idx("sessions", i)
        so = v.obj(
            sp,
            s,
            (
                "session", "file", "status", "reason", "out_status", "attempts", "failure_class",
                "cost_usd", "turns", "claude_session_id", "usage_first_response", "usage_session",
                "charter_denials", "duration_secs",
            ),
        )
        if so is None:
            continue
        v.string(_join(sp, "session"), so.get("session"), 1, 200)
        v.string(_join(sp, "file"), so.get("file"), 1, 10_000)
        status_ok = v.enum(_join(sp, "status"), so.get("status"), SESSION_STATUSES)
        v.string(_join(sp, "reason"), so.get("reason"), 1, 200, nullable=True)
        v.enum(_join(sp, "out_status"), so.get("out_status"), OUT_STATUSES, nullable=True)
        v.integer(_join(sp, "attempts"), so.get("attempts"), lo=0)
        v.string(_join(sp, "failure_class"), so.get("failure_class"), 1, 200, nullable=True)
        v.number(_join(sp, "cost_usd"), so.get("cost_usd"), nullable=True)
        v.integer(_join(sp, "turns"), so.get("turns"), lo=0, nullable=True)
        v.string(_join(sp, "claude_session_id"), so.get("claude_session_id"), 1, 200, nullable=True)
        for k in ("usage_first_response", "usage_session"):
            if so.get(k) is not None and not isinstance(so[k], dict):
                v.err(_join(sp, k), "not an object or null")
        v.integer(_join(sp, "charter_denials"), so.get("charter_denials"), lo=0)
        v.number(_join(sp, "duration_secs"), so.get("duration_secs"))
        if not status_ok:
            continue
        st_name = so["status"]
        if st_name == "called":
            called += 1
            if so.get("reason") is not None:
                v.err(_join(sp, "reason"), "must be null for a called session")
            if so.get("out_status") is None:
                v.err(_join(sp, "out_status"), "a called session needs an out_status")
        else:
            if so.get("out_status") is not None:
                v.err(_join(sp, "out_status"), "must be null unless the session was called")
            allowed = SKIP_REASONS if st_name == "skipped" else NOT_RUN_REASONS
            if v.enum(_join(sp, "reason"), so.get("reason"), allowed):
                if st_name == "skipped":
                    skipped[so["reason"]] = skipped.get(so["reason"], 0) + 1
            if st_name == "not-run":
                not_run += 1

    t = v.obj(
        "totals",
        o.get("totals"),
        ("called", "skipped", "not_run", "cost_usd", "lessons", "sightings", "rule_checks", "drops"),
    )
    if t is not None:
        if v.integer("totals.called", t.get("called"), lo=0) and t["called"] != called:
            v.err("totals.called", "does not equal the number of called sessions")
        if v.counter("totals.skipped", t.get("skipped"), SKIP_REASONS):
            if {k: n for k, n in t["skipped"].items() if n} != skipped:
                v.err("totals.skipped", "does not equal the skipped sessions by reason")
        if v.integer("totals.not_run", t.get("not_run"), lo=0) and t["not_run"] != not_run:
            v.err("totals.not_run", "does not equal the number of not-run sessions")
        v.number("totals.cost_usd", t.get("cost_usd"))
        for k in ("lessons", "sightings", "rule_checks"):
            v.integer(_join("totals", k), t.get(k), lo=0)
        v.counter("totals.drops", t.get("drops"), DROP_REASONS)
    return v.errors


# ------------------------------------------------------------- run folders


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ContractError([f"{label}: missing"]) from None
    except (OSError, UnicodeDecodeError):
        raise ContractError([f"{label}: unreadable"]) from None
    except json.JSONDecodeError as exc:
        raise ContractError([f"{label}: not valid JSON ({exc.msg} at line {exc.lineno})"]) from None


def load_run(run_dir: Path | str) -> tuple[Run, dict[str, Checked]]:
    """Read and validate a run folder: ``run.json`` and every ``out/*.json``.

    Returns ``(run record, {session id: checked output})``. Raises
    :class:`ContractError` naming the file and the path of every error. Beyond
    each document's own shape, the folder must agree with itself: one out file
    per called session and no other, each out file's run id, mode and status
    equal to the run record's, and the totals equal to what the files hold."""
    base = Path(run_dir)
    run = _read_json(base / "run.json", "run.json")
    errs = [f"run.json: {m}" for m in validate_run(run)]
    if errs:
        raise ContractError(errs)
    outs: dict[str, Checked] = {}
    out_dir = base / "out"
    for p in sorted(out_dir.glob("*.json")) if out_dir.is_dir() else []:
        label = f"out/{p.name}"
        obj = _read_json(p, label)
        errs.extend(f"{label}: {m}" for m in validate_checked_output(obj))
        if errs:
            continue
        if obj["session"]["id"] != p.stem:
            errs.append(f"{label}: session.id does not match the file name")
            continue
        outs[p.stem] = obj
    if errs:
        raise ContractError(errs)

    by_session = {s["session"]: s for s in run["sessions"]}
    called = {sid for sid, s in by_session.items() if s["status"] == "called"}
    for sid in sorted(called - set(outs)):
        errs.append(f"out/{sid}.json: missing for a called session")
    for sid in sorted(set(outs) - called):
        errs.append(f"out/{sid}.json: present for a session that was not called")
    for sid, out in sorted(outs.items()):
        label = f"out/{sid}.json"
        if out["run_id"] != run["run_id"]:
            errs.append(f"{label}: run_id differs from run.json")
        if out["mode"] != run["mode"]:
            errs.append(f"{label}: mode differs from run.json")
        entry = by_session.get(sid)
        if entry is not None and entry["out_status"] != out["status"]:
            errs.append(f"{label}: status differs from run.json out_status")
    if errs:
        raise ContractError(errs)

    totals = run["totals"]
    for k in ("lessons", "sightings", "rule_checks"):
        if totals[k] != sum(len(o[k]) for o in outs.values()):
            errs.append(f"run.json: totals.{k} does not equal the out files")
    drops: dict[str, int] = {}
    for o in outs.values():
        for d in o["drops"]:
            drops[d["reason"]] = drops.get(d["reason"], 0) + 1
    if {k: n for k, n in totals["drops"].items() if n} != drops:
        errs.append("run.json: totals.drops does not equal the out files")
    if errs:
        raise ContractError(errs)
    return run, outs


# ---------------------------------------------------------- typed turns (D7)


def has_typed_turn_marker(entries: Sequence[dict[str, Any] | None]) -> bool:
    """True when some ``user`` row carries Claude Code's typed-turn marker: an
    ``origin`` object or a ``promptSource`` key. ``entries`` holds one slot per
    physical line of a transcript (``None`` for a line that is not a JSON
    object)."""
    for e in entries:
        if isinstance(e, dict) and e.get("type") == "user":
            if isinstance(e.get("origin"), dict) or "promptSource" in e:
                return True
    return False


def typed_turn_lines(entries: Sequence[dict[str, Any] | None]) -> list[int]:
    """The 1-based physical lines of the typed turns: entries whose
    ``refs.role_of`` is ``user`` and whose entry text is not blank. ``entries``
    keeps one slot per line (``None`` for a non-object line), so a line number
    is the slot's position plus one. This is the one definition of ``T<k>``."""
    lines: list[int] = []
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict) or refs.role_of(e) != "user":
            continue
        if refs._raw_text(e).strip():  # pyright: ignore[reportPrivateUsage]
            lines.append(i)
    return lines


def turn_of(typed_lines: Sequence[int], line: int) -> int:
    """How many typed turns sit at or before ``line``: 0 before the first."""
    return bisect.bisect_right(typed_lines, line)


# -------------------------------------------------------------- JSON Schema


def _s(lo: int, hi: int, *, nullable: bool = False) -> dict[str, Any]:
    return {"type": ["string", "null"] if nullable else "string", "minLength": lo, "maxLength": hi}


def _point_schema(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    props: dict[str, Any] = {
        "line": {"type": "integer", "minimum": 1},
        "subagent": {"type": "string", "pattern": SUBAGENT_PATTERN},
    }
    props.update(extra or {})
    return {
        "type": "object",
        "properties": props,
        "required": ["line", *(extra or {})],
        "additionalProperties": False,
    }


def _lesson_schema() -> dict[str, Any]:
    quoted = _point_schema({"quote": _s(1, QUOTE_MAX)})
    props: dict[str, Any] = {
        "id": {"type": "string", "pattern": LESSON_ID_PATTERN},
        "shape": {"enum": list(SHAPES)},
        "scope": {"type": "string", "pattern": SCOPE_PATTERN},
        "type": {"enum": sorted(records.TYPES)},
        "kind": {"enum": sorted(records.KINDS)},
        "trigger": _s(1, TEXT_MAX, nullable=True),
        "instruction": _s(1, TEXT_MAX, nullable=True),
        "fact": _s(1, TEXT_MAX, nullable=True),
        "context": _s(1, TEXT_MAX, nullable=True),
        "evidence": {"type": "array", "items": quoted, "minItems": 1, "maxItems": MAX_EVIDENCE},
        "steps": {
            "type": "array",
            "items": _point_schema({"what": _s(1, STEP_WHAT_MAX)}),
            "maxItems": MAX_STEPS,
            "description": f"empty, or {MIN_STEPS} to {MAX_STEPS} steps in the order the events happened",
        },
        "verification": {
            "anyOf": [{"type": "null"}, _point_schema({"quote": _s(1, QUOTE_MAX), "how": _s(1, HOW_MAX)})]
        },
        "incident_cost": {"anyOf": [{"type": "null"}, _point_schema({"text": _s(1, COST_TEXT_MAX)})]},
        "generality": {"enum": sorted(records.GENERALITIES)},
        "why_durable": _s(1, WHY_DURABLE_MAX),
        "subagent_cause": {"enum": [*SUBAGENT_CAUSES, None]},
    }
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
        "allOf": [
            {
                "if": {"properties": {"type": {"const": "behavior"}}, "required": ["type"]},
                "then": {
                    "properties": {
                        "trigger": {"type": "string"},
                        "instruction": {"type": "string"},
                        "fact": {"type": "null"},
                        "context": {"type": "null"},
                    }
                },
            },
            {
                "if": {"properties": {"type": {"const": "knowledge"}}, "required": ["type"]},
                "then": {
                    "properties": {
                        "trigger": {"type": "null"},
                        "instruction": {"type": "null"},
                        "fact": {"type": "string"},
                    }
                },
            },
        ],
    }


def model_output_json_schema() -> dict[str, Any]:
    """A JSON Schema (draft 2020-12) document for the model output, built from
    the constants above. Shown to the model in its instructions; the
    validators do not use it. Serialise with ``json.dumps(..., sort_keys=True)``
    for the stable form."""
    quoted = _point_schema({"quote": _s(1, QUOTE_MAX)})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": MODEL_CONTRACT,
        "type": "object",
        "properties": {
            "contract": {"const": MODEL_CONTRACT},
            "lessons": {"type": "array", "items": _lesson_schema(), "maxItems": MAX_LESSONS},
            "sightings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record": {"type": "string", "pattern": RECORD_ID_PATTERN},
                        "evidence": {
                            "type": "array",
                            "items": quoted,
                            "minItems": 1,
                            "maxItems": MAX_SIGHTING_EVIDENCE,
                        },
                    },
                    "required": ["record", "evidence"],
                    "additionalProperties": False,
                },
                "maxItems": MAX_SIGHTINGS,
            },
            "rule_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record": {"type": "string", "pattern": RECORD_ID_PATTERN},
                        "outcome": {"enum": list(OUTCOMES)},
                        "situation": _point_schema(),
                        "action": {"anyOf": [{"type": "null"}, _point_schema()]},
                    },
                    "required": ["record", "outcome", "situation", "action"],
                    "additionalProperties": False,
                },
                "maxItems": MAX_RULE_CHECKS,
            },
        },
        "required": ["contract", "lessons", "sightings", "rule_checks"],
        "additionalProperties": False,
    }
