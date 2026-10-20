"""Checks on everything the session miner's model returns, before anything
is kept (new-miner plan §3.5; the old U4 spec §5.8 it amends).

Input: the model's final message and the :class:`spine.Spine` it was given.
Output: a checked document, ``miner-output/1`` (``mining.contract``), in which
every pointer is a full transcript ref (``refs.Ref``) and every quote carries
a verdict. Each failed check drops the smallest unit it concerns and records
``{item, reason, detail}``; ``detail`` never holds transcript or quote text.

The steps, in order:

1. **Parse.** One surrounding ```` ```json ```` fence is stripped; the text
   must be one JSON object. Items beyond a count limit are dropped as
   ``over-count``, the first ones kept; then the document must pass
   ``contract.validate_model_output``. Any failure: status ``bad-output``,
   nothing kept.
2. **Resolve** each pointer against the file the spine was built from: the
   entry at the cited line gives its ``uuid``, and ``refs.resolve`` is asked
   for that uuid at that line, so the ref lands on the judged file or an
   identical copy. An entry without a uuid is kept only when the ref's
   project folder is the judged file's. A line past the file's end, or a
   failed resolve: ``line-unresolved``. Roles come from the file, never from
   the model.
3. **Range.** A main-session pointer past the judged range's end:
   ``out-of-range``. A lesson or sighting needs an evidence item inside the
   range, a rule check's situation must be inside it. A subagent pointer is
   inside only when its subagent was launched in a new stretch.
4. **Quotes.** First against the redacted text the model was shown (exact,
   then folded), then ``refs.check_quote`` against the raw file: ``nearby``
   and ``elsewhere_in_file`` move the ref (``corrected_from`` keeps the cited
   line) and the moved ref must still pass step 3; ``stitched`` and
   ``not_found`` drop the item. A kept quote that holds a ``[redacted:``
   placeholder keeps its ref but is stored as :data:`QUOTE_WITHHELD`, and is
   counted (:attr:`CheckResult.quote_redacted`): the steward re-checks
   stored quotes against the raw transcript, where a placeholder never
   matches.
5. **Moments already judged.** Evidence and a rule check's situation whose
   uuid is in the judged-uuid store: ``already-judged``. A second evidence
   item of one lesson or sighting at the same moment: ``duplicate``.
6. **Whole items.** No evidence left: ``no-evidence``. A correction or a
   standing preference with no evidence the person typed (role ``user``;
   an agent-written turn is role ``agent``): ``no-user-evidence``. A
   Trigger, Instruction or Fact of more than one non-empty line:
   ``multi-line-loaded-text`` (only that lesson). A failed verification
   becomes null (``verification-unchecked``); an unresolved incident cost
   null (``incident-cost-unresolved``); fewer than two resolvable steps
   leave none (``steps-unresolved``). A sighting or rule check naming a
   record that is not known: ``unknown-record``; a rule check for a record
   not flagged on the spine: ``not-flagged``.
7. **Turns.** A main-session ref gets the number of typed turns at or
   before it; a subagent ref its launch's, when linked.
8. **Secrets.** Every free-text field passes ``scan.redact``; hits are
   redacted in place and counted in ``redactions``.

This module reads transcripts only; it writes nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Container, Sequence

from .. import refs
from ..scan import redact
from . import contract
from .spine import Spine

__all__ = [
    "CheckResult",
    "CheckerError",
    "QUOTE_WITHHELD",
    "REDACTION_MARK",
    "USER_SHAPES",
    "check_output",
    "empty_output",
    "quote_withheld",
]

#: What a stored quote reads when the model's quote held a redaction
#: placeholder (plan §3.5): the ref is kept, the text is not. The engine
#: stores no quote for such an evidence item when it lands the lesson.
QUOTE_WITHHELD = "[quote withheld: it held a redaction placeholder]"
#: How ``scan.redact`` marks what it took out.
REDACTION_MARK = "[redacted:"
#: Lesson shapes that are the person's own words: their evidence must hold a
#: turn the person typed.
USER_SHAPES: tuple[str, ...] = ("correction", "standing-preference")

_FENCE = re.compile(r"\A\s*```(?:json)?[ \t]*\n(.*?)\n?```\s*\Z", re.S)
_KEEP = ("exact", "normalised")
_MOVED = ("nearby", "elsewhere_in_file")


class CheckerError(RuntimeError):
    """The checker built a document that fails its own contract: a defect
    in this module, never in the model's output."""


@dataclass(frozen=True)
class CheckResult:
    """``checked`` is the ``miner-output/1`` document; ``quote_redacted``
    counts quotes stored as :data:`QUOTE_WITHHELD` (the run record's
    ``quote-redacted``)."""

    checked: dict[str, Any]
    quote_redacted: int


def quote_withheld(quote: object) -> bool:
    """True for a stored quote whose text was withheld (:data:`QUOTE_WITHHELD`)."""
    return quote == QUOTE_WITHHELD


def _session_info(spine: Spine, search_mode: str) -> dict[str, Any]:
    s = spine.session
    return {
        "id": s.session_id,
        "project_dir": s.project_dir,
        "file": s.file,
        "judged": {
            "first_line": spine.first_line,
            "last_line": spine.last_line,
            "first_turn": spine.first_turn,
            "last_turn": spine.last_turn,
        },
        "typed_turns": len(spine.typed_lines),
        "spine_tokens_est": spine.tokens_est,
        "over_budget": spine.over_budget,
        "search_mode": search_mode,
        "flags": [{"record": f.record, "turn": f.turn, "basis": f.basis} for f in spine.flags],
    }


def empty_output(
    spine: Spine,
    status: str,
    *,
    run_id: str,
    model: str,
    method_version: str,
    search_mode: str = "lexical-only",
    mode: str = "night",
    drops: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """A checked document with nothing kept: for ``bad-output`` here, and
    for a ``failed`` call in the engine."""
    return {
        "contract": contract.CHECKED_CONTRACT,
        "run_id": run_id,
        "mode": mode,
        "model": model,
        "method_version": method_version,
        "session": _session_info(spine, search_mode),
        "status": status,
        "lessons": [],
        "sightings": [],
        "rule_checks": [],
        "drops": list(drops),
        "redactions": 0,
    }


# ------------------------------------------------------------------ step 1


def _parse(text: str) -> tuple[Any, str | None]:
    m = _FENCE.match(text)
    body = m.group(1) if m else text
    try:
        return json.loads(body), None
    except (ValueError, RecursionError):
        return None, "the final message is not JSON"


def _over_count(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Cut every list past its count limit, first items kept; the drops."""
    drops: list[dict[str, Any]] = []

    def cut(container: dict[str, Any], key: str, limit: int, path: str) -> None:
        v = container.get(key)
        if isinstance(v, list) and len(v) > limit:
            for i in range(limit, len(v)):
                drops.append(_drop(f"{path}[{i}]", "over-count", f"more than {limit}"))
            container[key] = v[:limit]

    cut(obj, "lessons", contract.MAX_LESSONS, "lessons")
    cut(obj, "sightings", contract.MAX_SIGHTINGS, "sightings")
    cut(obj, "rule_checks", contract.MAX_RULE_CHECKS, "rule_checks")
    for i, lesson in enumerate(obj.get("lessons") or []):
        if isinstance(lesson, dict):
            lid = lesson.get("id")
            base = lid if isinstance(lid, str) and re.fullmatch(contract.LESSON_ID_PATTERN, lid) else f"lessons[{i}]"
            cut(lesson, "evidence", contract.MAX_EVIDENCE, f"{base}.evidence")
            cut(lesson, "steps", contract.MAX_STEPS, f"{base}.steps")
    for i, s in enumerate(obj.get("sightings") or []):
        if isinstance(s, dict):
            cut(s, "evidence", contract.MAX_SIGHTING_EVIDENCE, f"sightings[{i}].evidence")
    return drops


def _drop(item: str, reason: str, detail: str = "") -> dict[str, Any]:
    return {"item": item, "reason": reason, "detail": detail[: contract.DROP_DETAIL_MAX]}


# -------------------------------------------------------------- steps 2-8


class _Fail(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail


class _Checker:
    def __init__(
        self,
        spine: Spine,
        roots: Sequence[Path | str] | None,
        judged_uuids: Container[str],
        known_records: Container[str],
    ) -> None:
        self.spine = spine
        self.roots = [Path(r).expanduser() for r in roots] if roots is not None else refs.transcript_roots()
        self.judged_uuids = judged_uuids
        self.known = known_records
        self.flagged = {f.record for f in spine.flags}
        self.drops: list[dict[str, Any]] = []
        self.redactions = 0
        self.quote_redacted = 0

    # ---- helpers

    def text(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        out, hits = redact(value)
        self.redactions += len(hits)
        return out

    def drop(self, item: str, reason: str, detail: str = "") -> None:
        self.drops.append(_drop(item, reason, detail))

    def _subagent_id(self, ref: refs.Ref) -> str | None:
        if ref.subagent_file is None:
            return None
        name = Path(ref.subagent_file).name
        return name[len("agent-") : -len(".jsonl")] if name.startswith("agent-") else None

    def inside(self, ref: refs.Ref) -> bool:
        if ref.subagent_file is None:
            return self.spine.first_line <= ref.line <= self.spine.last_line
        launch = self.spine.subagents.get(self._subagent_id(ref) or "")
        return launch is not None and self.spine.stretch_new[self.spine.stretch_of(launch)]

    def turn(self, ref: refs.Ref) -> int | None:
        if ref.subagent_file is None:
            return contract.turn_of(self.spine.typed_lines, ref.line)
        launch = self.spine.subagents.get(self._subagent_id(ref) or "")
        return None if launch is None else contract.turn_of(self.spine.typed_lines, launch)

    def judged(self, ref: refs.Ref) -> bool:
        return ref.uuid is not None and ref.uuid in self.judged_uuids

    # ---- step 2 and 3

    def resolve(self, point: dict[str, Any]) -> refs.Ref:
        """The ref a model pointer names, or :class:`_Fail`."""
        line = point["line"]
        sub = point.get("subagent")
        session = self.spine.session
        if sub is None:
            lines: Sequence[str] = session.lines
            path = session.path
            subagent_file = None
        else:
            subagent_file = f"subagents/agent-{sub}.jsonl"
            path = session.path.parent / session.session_id / subagent_file
            if sub not in self.spine.subagents or not path.is_file():
                raise _Fail("line-unresolved", "no such subagent log")
            lines = refs._lines(path)  # pyright: ignore[reportPrivateUsage]
        if line > len(lines):
            raise _Fail("line-unresolved", f"line {line} is past the file's end ({len(lines)} lines)")
        entry = refs._entry(lines[line - 1])  # pyright: ignore[reportPrivateUsage]
        if entry is None:
            raise _Fail("line-unresolved", f"line {line} is not a JSON object")
        uid = entry.get("uuid")
        uid = uid if isinstance(uid, str) else None
        try:
            ref = refs.resolve(session.session_id, line, uuid=uid, subagent_file=subagent_file, roots=self.roots)
        except (refs.RefError, OSError):
            raise _Fail("line-unresolved", f"line {line} does not resolve") from None
        if uid is None and ref.project_dir != session.project_dir:
            raise _Fail("line-unresolved", f"line {line} has no uuid and resolves to another folder")
        self.after_end(ref)
        return ref

    def after_end(self, ref: refs.Ref) -> None:
        if ref.subagent_file is None and ref.line > self.spine.last_line:
            raise _Fail("out-of-range", f"line {ref.line} is past the judged range's end (L{self.spine.last_line})")

    def pointer(self, point: dict[str, Any]) -> dict[str, Any]:
        ref = self.resolve(point)
        return {"ref": ref.to_dict(), "turn": self.turn(ref)}

    # ---- step 4 and 5

    def quoted(self, point: dict[str, Any], *, moments: bool = True) -> tuple[dict[str, Any], refs.Ref]:
        """A checked evidence item and its ref, or :class:`_Fail`."""
        ref = self.resolve(point)
        if moments and self.judged(ref):
            raise _Fail("already-judged", f"line {ref.line} was judged in an earlier run")
        quote: str = point["quote"]
        shown = refs.entry_text(ref, roots=self.roots)
        corrected_from = None
        if quote in shown:
            verdict = "exact"
        elif refs.fold(quote) and refs.fold(quote) in refs.fold(shown):
            verdict = "normalised"
        else:
            v = refs.check_quote(ref, quote, roots=self.roots, other_session_cap=0)
            if v.outcome in _KEEP:
                verdict = v.outcome
            elif v.outcome in _MOVED:
                verdict, corrected_from = v.outcome, ref.line
                ref = v.ref
                self.after_end(ref)
                if moments and self.judged(ref):
                    raise _Fail("already-judged", f"line {ref.line} was judged in an earlier run")
            elif v.outcome == "stitched":
                raise _Fail("quote-stitched", v.detail)
            else:
                raise _Fail("quote-not-found", f"line {ref.line}")
        stored = self.text(quote)
        if REDACTION_MARK in stored:
            stored = QUOTE_WITHHELD
            self.quote_redacted += 1
        return (
            {
                "ref": ref.to_dict(),
                "turn": self.turn(ref),
                "quote": stored,
                "verdict": verdict,
                "corrected_from": corrected_from,
            },
            ref,
        )

    def evidence(self, base: str, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[refs.Ref]]:
        kept: list[dict[str, Any]] = []
        kept_refs: list[refs.Ref] = []
        for j, point in enumerate(items):
            path = f"{base}.evidence[{j}]"
            try:
                item, ref = self.quoted(point)
            except _Fail as f:
                self.drop(path, f.reason, f.detail)
                continue
            if any(refs.same_moment(ref, r) for r in kept_refs):
                self.drop(path, "duplicate", f"line {ref.line} is the same moment as an earlier item")
                continue
            kept.append(item)
            kept_refs.append(ref)
        return kept, kept_refs

    def whole(self, base: str, kept_refs: list[refs.Ref]) -> bool:
        if not kept_refs:
            self.drop(base, "no-evidence", "no evidence item survived its checks")
            return False
        if not any(self.inside(r) for r in kept_refs):
            self.drop(base, "out-of-range", "no evidence inside the judged range")
            return False
        return True

    # ---- the three item kinds

    def lesson(self, lesson: dict[str, Any]) -> dict[str, Any] | None:
        lid: str = lesson["id"]
        for key in ("trigger", "instruction", "fact"):
            value = lesson.get(key)
            if isinstance(value, str) and sum(1 for ln in value.splitlines() if ln.strip()) > 1:
                self.drop(lid, "multi-line-loaded-text", f"{key} has more than one line")
                return None
        evidence, ev_refs = self.evidence(lid, lesson["evidence"])
        if not self.whole(lid, ev_refs):
            return None
        if lesson["shape"] in USER_SHAPES and not any(r.role == "user" for r in ev_refs):
            self.drop(lid, "no-user-evidence", f"a {lesson['shape']} needs a turn the person typed")
            return None

        verification = None
        ver = lesson.get("verification")
        if ver is not None:
            try:
                verification, _ref = self.quoted(ver, moments=False)
                verification["how"] = self.text(ver["how"])
            except _Fail as f:
                self.drop(f"{lid}.verification", "verification-unchecked", f.reason)

        incident_cost = None
        cost = lesson.get("incident_cost")
        if cost is not None:
            try:
                incident_cost = self.pointer(cost)
                incident_cost["text"] = self.text(cost["text"])
            except _Fail as f:
                self.drop(f"{lid}.incident_cost", "incident-cost-unresolved", f.reason)

        steps: list[dict[str, Any]] = []
        for i, step in enumerate(lesson["steps"]):
            try:
                p = self.pointer(step)
            except _Fail as f:
                self.drop(f"{lid}.steps[{i}]", f.reason, f.detail)
                continue
            p["what"] = self.text(step["what"])
            steps.append(p)
        if lesson["steps"] and len(steps) < contract.MIN_STEPS:
            self.drop(f"{lid}.steps", "steps-unresolved", f"{len(steps)} of {len(lesson['steps'])} steps resolved")
            steps = []

        out = dict(lesson)
        for key in ("trigger", "instruction", "fact", "context", "why_durable"):
            out[key] = self.text(lesson.get(key))
        out.update(evidence=evidence, steps=steps, verification=verification, incident_cost=incident_cost)
        return out

    def sighting(self, i: int, s: dict[str, Any]) -> dict[str, Any] | None:
        base = f"sightings[{i}]"
        if s["record"] not in self.known:
            self.drop(base, "unknown-record", "the record is not in the ledger")
            return None
        evidence, ev_refs = self.evidence(base, s["evidence"])
        if not self.whole(base, ev_refs):
            return None
        return {"record": s["record"], "evidence": evidence}

    def rule_check(self, i: int, c: dict[str, Any]) -> dict[str, Any] | None:
        base = f"rule_checks[{i}]"
        if c["record"] not in self.known:
            self.drop(base, "unknown-record", "the record is not in the ledger")
            return None
        if c["record"] not in self.flagged:
            self.drop(base, "not-flagged", "the record was not flagged on the spine")
            return None
        try:
            ref = self.resolve(c["situation"])
            if not self.inside(ref):
                raise _Fail("out-of-range", "the situation is outside the judged range")
            if self.judged(ref):
                raise _Fail("already-judged", f"line {ref.line} was judged in an earlier run")
        except _Fail as f:
            self.drop(base, f.reason, f.detail)
            return None
        action = None
        if c.get("action") is not None:
            try:
                action = self.pointer(c["action"])
            except _Fail as f:
                self.drop(f"{base}.action", f.reason, f.detail)
        return {
            "record": c["record"],
            "outcome": c["outcome"],
            "situation": {"ref": ref.to_dict(), "turn": self.turn(ref)},
            "action": action,
        }


def check_output(
    text: str,
    spine: Spine,
    *,
    run_id: str,
    model: str,
    method_version: str,
    roots: Sequence[Path | str] | None = None,
    judged_uuids: Container[str] = frozenset(),
    known_records: Container[str] = frozenset(),
    search_mode: str = "lexical-only",
    mode: str = "night",
) -> CheckResult:
    """Turn the model's final message ``text`` for ``spine`` into checked
    output (module docstring, steps 1-8). ``roots`` are the transcript roots
    refs resolve against (the registry's when omitted); ``judged_uuids`` the
    judged-uuid store as it stood before this run; ``known_records`` the
    ledger's record ids. Reads only; never adds to the judged-uuid store."""
    meta = {"run_id": run_id, "model": model, "method_version": method_version, "search_mode": search_mode, "mode": mode}
    obj, problem = _parse(text)
    if problem is None and not isinstance(obj, dict):
        problem = "the final message is not a JSON object"
    over: list[dict[str, Any]] = []
    if problem is None:
        assert isinstance(obj, dict)
        over = _over_count(obj)
        errors = contract.validate_model_output(obj)
        if errors:
            # validator messages are not stored: they can name the model's own keys
            problem = f"{len(errors)} contract error{'s' if len(errors) != 1 else ''}"
    if problem is not None:
        return CheckResult(
            empty_output(spine, "bad-output", drops=[_drop("output", "bad-output", problem)], **meta), 0
        )
    assert isinstance(obj, dict)

    ck = _Checker(spine, roots, judged_uuids, known_records)
    ck.drops.extend(over)
    lessons = [x for x in (ck.lesson(lesson) for lesson in obj["lessons"]) if x is not None]
    sightings = [x for x in (ck.sighting(i, s) for i, s in enumerate(obj["sightings"])) if x is not None]
    checks = [x for x in (ck.rule_check(i, c) for i, c in enumerate(obj["rule_checks"])) if x is not None]
    checked = empty_output(spine, "ok", drops=ck.drops, **meta)
    checked.update(lessons=lessons, sightings=sightings, rule_checks=checks, redactions=ck.redactions)
    errors = contract.validate_checked_output(checked)
    if errors:
        raise CheckerError("; ".join(errors[:5]))
    return CheckResult(checked, ck.quote_redacted)
