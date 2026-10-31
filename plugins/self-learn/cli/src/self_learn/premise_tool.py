"""The steward's read-only ``premise_probe`` tool (premise-check design,
unit U5; decision row S-NEXT-u5-probe-tool, assigned at landing).

The steward decides a lesson that rests on a fact about the machine, and
writes the ``premises`` a lesson will be checked by. It has no Bash
(``steward._DISALLOWED_TOOLS``), so it could neither see what a probe would
answer nor look at a premise while deciding. This module gives it one tool,
served as ``mcp__premises__premise_probe`` through
``SessionSpec.mcp_toolset`` (the mechanism the session miner's tools use),
that runs the SAME probes the nightly sweep runs, through the same
module and the same runner (:mod:`premises`): same catalog, same refusals,
same 5-second bound, same scrubbed environment. It adds no probe, no
command and no power of its own.

**Two ways to call it.**

- ``probe``: one probe of the catalog, with an optional ``holds_if`` and
  ``match``. It answers with the value the code sees now (the value
  itself only when it is short and passes the secret scan, always its
  hash), how the claim reads against it, and the baseline the runner
  would record if the premise were written now. A probe whose first
  value already contradicts its claim says so here, which is the
  disagreement the steward would otherwise learn about the next night
  (design D10).
- ``lesson`` (and optionally ``premise``): a placed lesson's recorded
  premises, each probed now and judged against its stored baseline: the
  verdict the sweep would reach, minus the sweep's two-day debounce. A
  lesson with no premises says whether none were recorded yet or the
  list is the explicit empty one.

**Read-only by construction.** Nothing here writes the ledger, the cache
or the stage, takes a lock, or calls a model. The only system access is
the probe runner's: ``systemctl show``, ``pacman -Q`` and ``git cat-file
blob`` as argv lists, and file reads that never follow a credential path.
A call's arguments are checked by the tool's JSON Schema and again by
:func:`premises.validate_premises`, the function that validates a premise
on a record, so the tool accepts exactly the probes a record would.

**Placement premises (unit U8).** ``@reach``, ``@writable`` and
``@intact`` are derived by code from a lesson's placement, never written.
U8 builds that derivation; this tool shows its answer when it is handed
one: ``build_toolset(home, placement=<reader>)``, where the reader takes
``(home, record)`` and returns one :class:`PlacementReading` for each of
the lesson's placement premises. Without a reader (this build), a lesson
call says that placement checks are not available to the tool and a
``premise`` of ``@reach``/``@writable``/``@intact`` is refused with the
same reason; nothing is invented.

**A handler never blocks the session's event loop**: the probes run in a
worker thread (``asyncio.to_thread``), as ``McpTool`` requires. One call
runs at most three probes of five seconds each, inside the seam's
60-second bound.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace as dataclass_replace
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import ledger_ops, premises
from .invocation.contract import McpTool, McpToolset, ToolReply
from .premises import Observation, PremiseCheck, ProbeEnv
from .records import Record, RecordError
from .scan import redact

__all__ = [
    "PLACEMENT_VERDICTS",
    "PremiseProbeTool",
    "PlacementReader",
    "PlacementReading",
    "QUALIFIED_NAME",
    "SERVER",
    "TOOL_DEFINITION",
    "TOOL_NAME",
    "build_toolset",
]

_log = logging.getLogger(__name__)

#: The server's name, and so the middle of the tool's name as the model
#: sees it: ``mcp__premises__premise_probe``.
SERVER = "premises"
TOOL_NAME = "premise_probe"
QUALIFIED_NAME = f"mcp__{SERVER}__{TOOL_NAME}"

#: What a placement reading may say (02 §3a.10.3 as drafted): the check
#: passes, it fails, or it could not be measured. ``unavailable`` is never a
#: failure, the same fail-closed rule as a probe's.
PLACEMENT_VERDICTS = frozenset({"holds", "moved", "unavailable"})

_LESSON_ID = r"^lrn-[0-9a-f]{8}$"
_PREMISE_ID = r"^(p[1-4]|@reach|@writable|@intact)$"
_ARG_KEYS = frozenset({"probe", "holds_if", "match", "lesson", "premise"})


@dataclass(frozen=True)
class PlacementReading:
    """One placement premise of one lesson, read now: ``premise_id`` is
    ``@reach``, ``@writable`` or ``@intact``; ``verdict`` one of
    :data:`PLACEMENT_VERDICTS`; ``detail`` one line saying why."""

    premise_id: str
    verdict: str
    detail: str


#: ``reader(home, record) -> readings``: U8's derivation of a lesson's
#: placement premises. It must be read-only like everything here.
PlacementReader = Callable[[Path, Record], Sequence[PlacementReading]]


# ------------------------------------------------------------- the schema

#: The union of every field any probe kind takes, by type. The probe kind
#: decides which are allowed together (`premises.validate_probe`, which
#: names the fields a kind does not take); a field outside this list is
#: refused by the schema before the handler runs. `test_premise_tool.py`
#: pins that this union equals the catalog's own field table, so adding a
#: probe field there without it here fails a test.
_PROBE_PROPERTIES: dict[str, Any] = {
    "kind": {"type": "string", "enum": sorted(premises.PROBE_KINDS)},
    "path": {"type": "string", "maxLength": 512},
    "repo": {"type": "string", "maxLength": 512},
    "contains": {"type": "string", "maxLength": 200},
    "line": {"type": "string", "maxLength": 200},
    "lines": {"type": ["string", "integer"]},
    "key": {"type": ["string", "array"], "maxItems": 16},
    "scope": {"type": "string", "enum": ["user", "system"]},
    "unit": {"type": "string", "maxLength": 210},
    "property": {"type": "string", "maxLength": 64},
    "name": {"type": "string", "maxLength": 128},
    "ref": {"type": "string", "maxLength": 40},
}

_DESCRIPTION = (
    "Run one of the premise probes now, read-only, and see what the nightly "
    "sweep would see. Use it to check a probe before you write it into a "
    "`premises` line, and to look at a placed lesson's premises while you "
    "decide it. It runs only the closed catalog below, with the same "
    "refusals and the same 5-second bound as the sweep; it never starts, "
    "stops or changes anything, and it never returns a file's text (a key "
    "probe may show the one short value it reads).\n"
    "Call it one of two ways, never both.\n"
    "(1) `probe`, with optional `holds_if` and `match`: the answer is the "
    "value seen now (the value itself only when it is short and not "
    "secret-like, always its hash), whether `holds_if`/`match` reads the "
    "claim as holding, and the baseline the runner would record if the "
    "premise were written now. `contradicts-claim` there means the first "
    "value already says the claim is false.\n"
    "(2) `lesson` (an lrn id), optionally with `premise` (p1..p4): that "
    "lesson's recorded premises, each probed now and judged against its "
    "stored baseline. Verdicts: holds, moved, unavailable (the probe could "
    "not read its target: never a change, and never a confirmation), "
    "no-baseline, no-probe (a behaviour premise: written down, never "
    "probed).\n"
    "Probe kinds and their fields: path {path} (exists, type, symlink "
    "target); file-match {path, and exactly one of contains | line | "
    "lines} (a literal anywhere, a whole line, or the hash of lines "
    "'A' or 'A-B'; a literal, not a regular expression); json-key / "
    "yaml-key / toml-key {path, key} (key: dotted, or a list); "
    "systemd-show {scope: user|system, unit, property} (`systemctl show "
    "--value`; an unbound or unset property reads as an empty value); "
    "package {name} (`pacman -Q`: the version, or not-installed); "
    "which {name}; git-file {repo, path, and one of contains | line | "
    "lines} (the file at HEAD); ledger {ref: lrn-xxxxxxxx, "
    "lrn-xxxxxxxx#follow_up, or stmt-xxxxxxxx}. Paths are absolute or "
    "start with ~/; credential and key locations are refused."
)

TOOL_DEFINITION: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": _DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            "probe": {
                "type": "object",
                "properties": _PROBE_PROPERTIES,
                "required": ["kind"],
                "additionalProperties": False,
            },
            "holds_if": {
                "type": "string",
                "enum": sorted(premises.HOLDS_IF_VALUES),
                "description": "with `probe` only: how the premise reads the value",
            },
            "match": {
                "type": "string",
                "maxLength": 200,
                "description": "with `probe` and a `holds_if` other than changed: the operand",
            },
            "lesson": {"type": "string", "pattern": _LESSON_ID},
            "premise": {"type": "string", "pattern": _PREMISE_ID},
        },
        "additionalProperties": False,
    },
}


# ------------------------------------------------------------ the formats


def _one_line(text: object, limit: int = 200) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _probe_text(probe: object) -> str:
    try:
        return json.dumps(probe, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))
    except (TypeError, ValueError):
        return "(unprintable probe)"


def _value_text(obs: Observation) -> str:
    """The value as a person reads it: the value itself when the runner
    kept a display string, ``(empty)`` for the empty value (what
    ``systemctl show --value`` prints for an unset property), else a note
    that only the hash is comparable."""
    if obs.shown:
        return json.dumps(obs.shown, ensure_ascii=False)
    if obs.value_sha == premises.value_sha(""):
        return "(empty)"
    return "(not shown: long, several lines or secret-like; compare by value_sha)"


def _claim_text(obs: Observation, premise: dict) -> str:
    holds_if = premise.get("holds_if") or premises.HOLDS_IF_DEFAULT
    rule = holds_if if holds_if == premises.HOLDS_IF_DEFAULT else f"{holds_if} {premise.get('match')!r}"
    if obs.claim == premises.CLAIM_UNJUDGED:
        if holds_if == premises.HOLDS_IF_DEFAULT:
            return "unjudged (holds_if changed holds while the value stays what it was recorded as)"
        return "unjudged"
    return f"{obs.claim} (holds_if {rule})"


def _observation_lines(obs: Observation, premise: dict) -> list[str]:
    if obs.state != premises.OBS_OK:
        return [
            "state: unavailable",
            f"reason: {_one_line(obs.reason)}",
            "No baseline can be recorded from this, and the sweep reads it as neither "
            "changed nor unchanged. Fix the probe, or write the premise with probe: null.",
        ]
    lines = [
        "state: ok",
        f"value: {_value_text(obs)}",
        f"value_sha: {obs.value_sha}",
        f"observed_at: {obs.observed_at}",
        f"claim: {_claim_text(obs, premise)}",
    ]
    try:
        lines.append(f"baseline if written now: {premises.make_baseline(obs)['state']}")
    except premises.PremiseError:  # an ok observation always has a hash; belt only
        pass
    return lines


def _baseline_text(baseline: dict | None) -> str:
    if not baseline:
        return "none recorded"
    shown = baseline.get("shown")
    if shown:
        value = json.dumps(shown, ensure_ascii=False)
    elif baseline.get("value_sha") == premises.value_sha(""):
        value = "(empty)"
    else:
        value = "(not shown)"
    return (
        f"{baseline.get('state')}, value {value}, value_sha {baseline.get('value_sha')}, "
        f"observed {baseline.get('observed_at')}"
    )


def _check_lines(check: PremiseCheck, premise: dict) -> list[str]:
    lines = [f"{check.premise_id}: {_one_line(check.claim)}"]
    probe = premise.get("probe")
    if probe is None:
        lines.append("  probe: none (a behaviour premise: written down, never probed)")
        lines.append(f"  verdict: {check.verdict}")
        return lines
    holds_if = premise.get("holds_if") or premises.HOLDS_IF_DEFAULT
    lines.append(f"  probe: {_probe_text(probe)}")
    rule = holds_if if holds_if == premises.HOLDS_IF_DEFAULT else f"{holds_if} {premise.get('match')!r}"
    lines.append(f"  holds_if: {rule}; on_change: {check.on_change}")
    lines.append(f"  verdict: {check.verdict}")
    lines.append(f"  baseline: {_baseline_text(check.baseline)}")
    obs = check.observation
    if obs is None:  # a premise with a probe always has one; belt only
        lines.append("  now: no observation")
    elif obs.state != premises.OBS_OK:
        lines.append(f"  now: unavailable ({_one_line(obs.reason)}), at {obs.observed_at}")
    else:
        lines.append(
            f"  now: value {_value_text(obs)}, value_sha {obs.value_sha}, observed {obs.observed_at}"
        )
    return lines


class _OnePremise:
    """Just enough of a record for :func:`premises.check_record` to run
    ONE premise, so asking about ``p2`` does not probe ``p1`` and ``p3``."""

    def __init__(self, record_id: str, premise: dict) -> None:
        self.id = record_id
        self.premises = [premise]


# -------------------------------------------------------------- the tool


class PremiseProbeTool:
    """The handler behind ``premise_probe``. *home* is the ledger (where a
    ``lesson`` call reads and where ``ledger`` probes read); *env* is the
    probe environment (tests inject a fake command runner and a scratch
    home; ``None`` is the real one); *placement* is U8's reader, or
    ``None``."""

    def __init__(
        self,
        home: Path,
        *,
        env: ProbeEnv | None = None,
        placement: PlacementReader | None = None,
    ) -> None:
        self.home = Path(home)
        self._env = env
        self._placement = placement
        self._validator = Draft202012Validator(TOOL_DEFINITION["input_schema"])

    def probe_env(self) -> ProbeEnv:
        """The environment a call runs its probes in: always bound to this
        tool's ledger, whatever an injected environment says."""
        base = self._env if self._env is not None else ProbeEnv()
        return dataclass_replace(base, ledger_home=self.home)

    def tool(self) -> McpTool:
        async def handler(args: dict[str, Any]) -> ToolReply:
            return await asyncio.to_thread(self.dispatch, args)

        return McpTool(
            TOOL_DEFINITION["name"],
            TOOL_DEFINITION["description"],
            TOOL_DEFINITION["input_schema"],
            handler,
            read_only=True,
        )

    def toolset(self) -> McpToolset:
        return McpToolset(SERVER, (self.tool(),))

    # -- one call -------------------------------------------------------

    def dispatch(self, args: dict[str, Any]) -> ToolReply:
        """Answer one call: text the model reads. A mistake the model can
        correct (a bad probe, an unknown lesson) is an error reply naming
        it; an unexpected failure names only its type."""
        error = next(self._validator.iter_errors(args), None)
        if error is not None:
            field = ".".join(str(part) for part in error.absolute_path) or "arguments"
            return ToolReply(
                redact(_one_line(f"invalid arguments for {TOOL_NAME}: {field}: {error.message}", 600))[0],
                is_error=True,
            )
        try:
            text = self._answer(args)
        except _Refused as exc:
            return ToolReply(redact(_one_line(str(exc), 600))[0], is_error=True)
        except Exception as exc:  # noqa: BLE001 -- a tool never takes a session down
            _log.error("%s failed unexpectedly (%s)", TOOL_NAME, type(exc).__name__)
            return ToolReply(f"{TOOL_NAME}: failed ({type(exc).__name__})", is_error=True)
        return ToolReply(redact(text)[0])

    def _answer(self, args: dict[str, Any]) -> str:
        unknown = sorted(set(args) - _ARG_KEYS)
        if unknown:  # the schema forbids it; kept so a loosened schema stays safe
            raise _Refused(f"unknown arguments: {unknown}")
        has_probe, has_lesson = "probe" in args, "lesson" in args
        if has_probe == has_lesson:
            raise _Refused("give exactly one of `probe` (a probe to run) or `lesson` (a lesson to look at)")
        if has_probe:
            if "premise" in args:
                raise _Refused("`premise` goes with `lesson`, not with `probe`")
            return self._probe_answer(args)
        if "holds_if" in args or "match" in args:
            raise _Refused("`holds_if` and `match` go with `probe`, not with `lesson`")
        return self._lesson_answer(str(args["lesson"]), args.get("premise"))

    def _probe_answer(self, args: dict[str, Any]) -> str:
        # The throwaway premise a record would hold: its validation is THE
        # validation (kind, fields, credential paths, holds_if/match rules,
        # version syntax), so this tool accepts exactly what a record would.
        premise: dict[str, Any] = {
            "id": "p1", "claim": "probe check", "probe": args["probe"],
        }
        for key in ("holds_if", "match"):
            if key in args:
                premise[key] = args[key]
        try:
            premises.validate_premises([premise])
        except premises.PremiseError as exc:
            raise _Refused(f"not a valid probe: {exc}") from None
        obs = premises.observe(premise, self.probe_env())
        assert obs is not None  # a premise with a probe always observes
        lines = [f"probe: {_probe_text(args['probe'])}", *_observation_lines(obs, premise)]
        return "\n".join(lines)

    def _lesson_answer(self, lesson: str, wanted: str | None) -> str:
        # The schema's `$` also matches before a trailing newline; the
        # handler does not.
        if re.fullmatch(r"lrn-[0-9a-f]{8}", lesson) is None:
            raise _Refused(f"not a lesson id: {lesson!r}")
        record = self._load(lesson)
        header = f"lesson {record.id} [{record.status}]"
        routing = record.routing or {}
        if routing.get("destination"):
            header += f" placed: {routing['destination']}"
        asked_placement = wanted is not None and wanted.startswith("@")
        # A placement premise is asked for by name, or shown with the whole
        # lesson; a written premise's id asks for that one alone.
        placement = [] if wanted is not None and not asked_placement else self._placement_lines(record, wanted)
        if asked_placement:
            return "\n".join([header, *placement])
        written = record.premises
        if written is None:
            body = ["premises: none recorded yet (the backfill has not reached this lesson)"]
        elif not written:
            body = ["premises: [] (decided: this lesson rests on no fact about the machine)"]
        else:
            selected = [p for p in written if wanted is None or p.get("id") == wanted]
            if not selected:
                known = [str(p.get("id")) for p in written]
                raise _Refused(f"{record.id} has no premise {wanted}; it has {known}")
            body = [f"premises: {len(written)} recorded" + (f", showing {wanted}" if wanted else "")]
            env = self.probe_env()
            for premise in selected:
                for check in premises.check_record(_OnePremise(record.id, premise), env):
                    body.extend(_check_lines(check, premise))
        return "\n".join([header, *body, *placement])

    def _load(self, lesson: str) -> Record:
        try:
            path = ledger_ops.find_record_path(self.home, lesson)
        except ledger_ops.RecordNotFound:
            raise _Refused(f"no lesson {lesson} in the ledger (pending or resolved)") from None
        except (ledger_ops.LedgerOpsError, OSError) as exc:
            raise _Refused(f"cannot look for {lesson} ({type(exc).__name__})") from None
        try:
            return Record.from_path(path)
        except (RecordError, OSError, UnicodeDecodeError, ValueError) as exc:
            raise _Refused(f"cannot read {lesson} ({type(exc).__name__})") from None

    def _placement_lines(self, record: Record, wanted: str | None) -> list[str]:
        """The lesson's placement premises, from U8's reader. With none
        (this build) say so; never invent a reading."""
        if self._placement is None:
            if wanted is not None:
                raise _Refused(
                    f"{wanted} is a placement premise, and placement checks are not "
                    "available to this tool in this build"
                )
            return ["placement premises (@reach, @writable, @intact): not available to this tool in this build"]
        try:
            readings = list(self._placement(self.home, record))
        except Exception as exc:  # noqa: BLE001 -- a reader's failure is its own answer
            _log.error("placement reader failed (%s)", type(exc).__name__)
            return [f"placement premises: could not be read ({type(exc).__name__})"]
        out: list[str] = []
        for reading in readings:
            if wanted is not None and reading.premise_id != wanted:
                continue
            verdict = reading.verdict if reading.verdict in PLACEMENT_VERDICTS else "unavailable"
            out.append(f"{reading.premise_id}: {verdict} ({_one_line(reading.detail)})")
        if wanted is not None and not out:
            raise _Refused(f"{record.id} has no placement premise {wanted}")
        return out or ["placement premises: none apply to this lesson"]


class _Refused(Exception):
    """A call the model can correct; its message is the reply."""


def build_toolset(
    home: Path,
    *,
    env: ProbeEnv | None = None,
    placement: PlacementReader | None = None,
) -> McpToolset:
    """The steward session's own tool: one server, one read-only tool."""
    return PremiseProbeTool(home, env=env, placement=placement).toolset()
