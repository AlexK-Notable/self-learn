"""O-3 — the weekly two-invocation overseer runner.

The model can read and write only ``worker.stage/overseer``.  This module
validates that stage and owns every ledger write through the existing case,
batch, observation, intent, and git seams.

Before applying phase B, it commits U14's execution manifest.  Restarts
discover that Git-owned recipe before phase A, reconstruct proven prefixes,
and continue the immutable sheets under their reserved successor case ids.

The O-3b user-model delta leg mirrors the steward's per-operation manifest
checkpointing and delegates every actual entry mutation to ``user_model``.
An examine-only run spools no telemetry of its own; every applied sheet uses
``batch.run``'s existing mutating epilogue.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML, YAMLError

from .. import batch, cases, conditions, config, execution_evidence, gitops, intents, invocation, provider, scan, settings, user_model, verbs, worker
from ..ledger import resolve_home
from ..ledger_ops import DEFAULT_DEFER_DAYS, LedgerOpsError, find_record_path
from ..primitives import chrono, fsops
from ..records import Record, build_covered_by
from . import health, notify, population as population_mod

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_STOPPED = gitops.EXIT_GIT_FAILED
EXIT_PARTIAL = 8
_REPORT_SECTIONS = (
    "Examined",
    "Decided in the user's stead",
    "Hooks",
    "User model",
    "Catalogue health",
    "Questions for you",
    "Refused / could not do",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LEGACY_RETIRE_ALIAS = "grad" + "uate"

#: 02-schema §3a: `failure_detail` is at most 2,000 characters, truncated
#: with a trailing ellipsis, and secret-scanned on write.  Same literals and
#: same semantics as the steward's (`steward.py`), deliberately: S-68 asks
#: for one vocabulary across both runners, not a second one.
_FAILURE_DETAIL_MAX = 2000
_REDACTED_DETAIL = "<redacted: secret-scan>"
_NO_PROGRESS_DETAIL = (
    "the attempt ran and moved no sheet item, maintenance operation or "
    "recipe of this run toward a terminal value"
)
#: A committed disposition nothing will re-drive.  `refused` is a judgment on
#: the merits (ruling 1); `applied` / `already-applied` landed.  `stopped`
#: (rc 5/6/7) and `not-attempted` are deliberately NOT here — those are the
#: retryable states A4 exists for.
_TERMINAL_ITEM_STATES = frozenset({"applied", "already-applied", "refused"})
#: 02-schema §3a: "A ledger stop keeps riding the run record's own numeric
#: halt code (5, 6, 7, 8); a code is never folded into this field." These are
#: the codes that ride `halt_code`; `failure` never carries one, and never
#: carries a literal outside §3a's closed set either.
_LEDGER_HALT_CODES = frozenset({3, 4, 5, 6, 7, 8})


def _failure_detail(text: object) -> str | None:
    """The message the transport or the validator actually returned.

    02-schema §3a: bounded at :data:`_FAILURE_DETAIL_MAX`, secret-scanned on
    write, and a scan hit REDACTS rather than suppresses — a trace is never
    suppressed by its own content, because a failure whose reason lives only
    in the git-ignored cache journal is the state this field exists to end.
    Newlines are folded to spaces so one committed field stays one readable
    line, and a leading ``#`` is stripped so the note can never present a
    heading-shaped line.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    if scan.scan(raw):
        return _REDACTED_DETAIL
    flat = " ".join(raw.split()).lstrip("#").strip()
    if not flat:
        return None
    if len(flat) > _FAILURE_DETAIL_MAX:
        return flat[: _FAILURE_DETAIL_MAX - 1] + "…"
    return flat


def _turns(outcome: Any, guard: int) -> tuple[int, bool]:
    """A10: the runaway guard fails CLOSED.  Returns (count, reported).

    ``int(getattr(outcome, "turns", 0) or 0)`` read a missing, ``None`` or
    non-integer turn count as ZERO — the one value that can never trip the
    guard.  A count we cannot read is treated as being AT the bound instead:
    the guard exists to stop a runaway, and "the session did not say how many
    turns it took" is exactly the shape a runaway can present.

    ``reported`` is False for such a count, so the refusal can say that the
    session reported no count rather than claiming an observed runaway.  It
    matters because a failed attempt is now retried and, at
    ``runs.attempt_cap``, becomes a question put to the user: that question
    has to name the real reason.  ``invocation.Outcome`` carries no ``turns``
    attribute at all and ``invocation_sdk``'s ``SdkOutcome.turns`` is
    ``int | None``, so both shapes reach here in practice.
    """
    value = getattr(outcome, "turns", None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return guard, False
    return value, True


@dataclass(frozen=True)
class RunResult:
    status: str
    code: int
    run: str
    model_calls: int = 0
    examined: tuple[str, ...] = ()
    excluded: int = 0
    applied: int = 0
    refused: int = 0
    report: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["examined"] = list(self.examined)
        return data


class OverseerError(Exception):
    """A fail-closed stage or output-contract refusal."""


class _DeferredNotice:
    """Run notifications only after the enclosing ledger lock exits.

    A queue, not a single slot: one failed attempt can both refuse for a
    reason of its own and be the attempt that closes the week out, and the
    user needs to be told both things.
    """

    def __init__(self) -> None:
        self.home: Path | None = None
        self.cue = "routine"
        self.message: str | None = None
        self.ids: list[str] = []
        self.queued: list[tuple[str, str, list[str]]] = []

    def add(self, home: Path, cue: str, message: str, ids: list[str]) -> None:
        self.home = home
        self.queued.append((cue, message, list(ids)))

    def __enter__(self) -> "_DeferredNotice":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        pending = list(self.queued)
        if self.message is not None:
            pending.insert(0, (self.cue, self.message, list(self.ids)))
        for cue, message, ids in pending:
            assert self.home is not None
            notify.send(self.home, cue, message, ids)


def journal_path(home: Path | str) -> Path:
    return worker.cache_dir(home) / "overseer.journal"


def _journal(home: Path, entry: dict[str, Any]) -> None:
    """Append one compact JSON object to the cache-only run journal."""
    path = journal_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    worker._truncate_oldest(path, worker.LOG_CAP_BYTES)


def read_journal(home: Path | str, *, limit: int = 20) -> list[dict[str, Any]]:
    try:
        lines = journal_path(home).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def status(home: Path | str | None = None) -> dict[str, Any]:
    resolved = Path(home) if home is not None else resolve_home()
    rows = read_journal(resolved)
    coverage = population_mod.load_coverage(resolved / "overseer" / "coverage.yaml")
    return {
        "last": rows[-1] if rows else None,
        "last_run_at": coverage.get("last_run_at"),
        "last_examined_at": coverage.get("last_examined_at"),
    }


def last_run_iso_from_cache(resolved_cache_dir: Path) -> str | None:
    marker = resolved_cache_dir / "overseer" / "overseer.last-run"
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def last_run_iso(home: Path | str | None = None) -> str | None:
    resolved = Path(home) if home is not None else resolve_home()
    cached = last_run_iso_from_cache(worker.cache_dir(resolved))
    if cached is not None:
        return cached
    return cast(str | None, status(resolved).get("last_run_at"))


def _write_last_run_marker(home: Path, value: str) -> None:
    marker = worker.cache_dir(home) / "overseer" / "overseer.last-run"
    marker.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(marker, value.rstrip() + "\n", fsync=False)


def report(home: Path | str | None = None, *, date: str | None = None) -> str:
    resolved = Path(home) if home is not None else resolve_home()
    if date is not None and not _DATE_RE.fullmatch(date):
        raise OverseerError(f"overseer report: malformed date {date!r}; expected YYYY-MM-DD")
    path = resolved / "overseer" / (f"{date}-report.md" if date else "latest-report.md")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OverseerError(f"overseer report: cannot read {path.name}: {exc}") from exc


def _yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, YAMLError) as exc:
        raise OverseerError(f"{path.name}: cannot parse: {exc}") from exc
    if not isinstance(data, dict):
        raise OverseerError(f"{path.name}: expected a mapping")
    return data


def _selected_ids(selection: dict[str, Any], available: set[str]) -> tuple[str, ...]:
    # coverage_update owns the strict unknown-key validation.  This read
    # additionally refuses duplicate, malformed, or non-population ids.
    population_mod.coverage_update(None, selection, [], [])
    ids: list[str] = []
    for entry in selection.get("cases") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise OverseerError("selection.yaml: every case entry needs exactly one string id")
        case_id = entry["id"]
        if case_id not in available:
            raise OverseerError(f"selection.yaml: unknown case {case_id}")
        if case_id in ids:
            raise OverseerError(f"selection.yaml: duplicate case {case_id}")
        ids.append(case_id)
    return tuple(ids)


def _validate_initial(path: Path, selected: tuple[str, ...]) -> None:
    data = _yaml_mapping(path)
    entries = data.get("cases")
    if not isinstance(entries, list):
        raise OverseerError("initial-views.yaml: cases must be a list")
    allowed = {"id", "what_i_would_do", "why", "what_evidence_decides_it", "confidence"}
    found: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != allowed:
            raise OverseerError(f"initial-views.yaml: every entry needs exactly {sorted(allowed)!r}")
        if not all(isinstance(entry.get(key), str) and entry[key].strip() for key in allowed):
            raise OverseerError("initial-views.yaml: every entry field must be non-empty text")
        if entry["confidence"] not in ("clear", "close-call"):
            raise OverseerError("initial-views.yaml: confidence must be clear or close-call")
        if entry["id"] in found:
            raise OverseerError(f"initial-views.yaml: duplicate case {entry['id']}")
        found.add(entry["id"])
    unexpected = sorted(found - set(selected))
    if unexpected:
        raise OverseerError(f"initial-views.yaml: unselected case(s) {unexpected!r}")
    missing = [case_id for case_id in selected if case_id not in found]
    if missing:
        raise OverseerError(f"initial-views.yaml: missing selected case(s) {missing!r}")


def _stage_files(stage: Path) -> list[Path]:
    root = stage.resolve()
    files: list[Path] = []
    for path in sorted(stage.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if root != resolved and root not in resolved.parents:
            raise OverseerError(f"stage scope: {path.name} resolves outside overseer stage")
        files.append(path)
    return files


def _secret_files(stage: Path) -> list[str]:
    names: list[str] = []
    for path in _stage_files(stage):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            names.append(path.relative_to(stage).as_posix())
            continue
        if scan.scan(text):
            names.append(path.relative_to(stage).as_posix())
    return names


def _write_stage(stage_dir: Path, path: Path, text: str) -> None:
    """Write only beneath the overseer's exclusive stage directory."""
    root = stage_dir.resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise OverseerError(f"stage scope: {path.name} resolves outside overseer stage")
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, text)


def _yaml_text(data: Any) -> str:
    import io

    stream = io.StringIO()
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.dump(data, stream)
    return stream.getvalue()


def _phase_a_prompt(stage: Path, count: int, excluded: int) -> str:
    return f"""You are the self-learn overseer, examining decisions independently.
Binding rules: provisional is bookkeeping; silence is not agreement; evidence is never authority.
Read only this stage. Use Read, Grep, and Glob; write only beneath {stage}.
The blind population has {count} cases. {excluded} cases excluded: freeze hash mismatch.
Do not seek or infer the steward's outcome, verb, decision, receipts, or rationale.
Read population.txt, nudges.yaml, and blind/*.md. Choose any number of cases; there is no sample cap.
Write selection.yaml with only cases: [{{id: case-...}}], why_these, and why_stopped.
Write initial-views.yaml with cases, one per selected id, carrying id, what_i_would_do, why,
what_evidence_decides_it, and confidence (clear or close-call).
"""


def _phase_b_prompt(stage: Path, selected: tuple[str, ...], parked: tuple[str, ...]) -> str:
    return f"""You are the self-learn overseer. The evidence-first view is complete.
You may now read the steward rationale and full decided account in full/*.md.
Read selection.yaml, initial-views.yaml, every parked/*.md, user-model.yaml, and health.yaml.
Selected cases: {', '.join(selected) if selected else 'none'}.
Parked cases (the entire queue, never truncated): {', '.join(parked) if parked else 'none'}.
A parked case whose parked_reason is attempts-exhausted means the steward's machinery failed three
times, not that the lesson is doubtful: decide that lesson yourself, using the recorded failure
reason as evidence, and note that such a case may point at a record another route has since
resolved -- say so and move on rather than treating it as an error.
Write report.md, findings.yaml, questions.yaml, user-model-delta.yaml, and either sheet.yaml or paired
case-<name>.yaml plus sheet-<name>.yaml files. One successor case must supersede each parked
case you decide. The runner alone records cases and applies sheets. Never run a verb.
findings.yaml is {{findings: [{{case, kind: examined|dependency-moved, text, ref?}}]}}.
questions.yaml contains structured ids and affected case ids only, no free text.
user-model-delta.yaml is {{updates: [...]}}. Each update is either
{{action: add, container, title, because, source: system-reading, ref, held_since?, conditions?, statements?, basis?}}
or {{action: lapse, id, changed_condition?|contrary?|consolidated_into?}}. Adds are provisional
system readings only. A lapse must name exactly one changed condition, contrary item, or consolidation.
report.md is under 57 lines before the runner adds three factual lines and has these headings,
in this exact order: Examined; Decided in the user's stead; Hooks; User model;
Catalogue health; Questions for you; Refused / could not do. Use ``- none`` for an empty section.
"""


def _invoke(home: Path, stage: Path, prompt: str, timeout: float, label: str, run_id: str):
    containment = invocation.containment_for(
        "overseer",
        allowed_tools="Read,Grep,Glob,Write",
        disallowed_tools="Bash",
        stage_dir=worker.stage_dir(),
        enforce=worker._enforce_scope(),
    )
    return invocation.write_session(
        invocation.SessionSpec(
            surface="overseer",
            prompt=prompt,
            cwd=stage,
            timeout=timeout,
            containment=containment,
            log=lambda message: _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "model-log", "phase": label, "message": message[:300]}),
            label=label,
            doctrine=None,
            # U4b (2026-09-19): `cwd` is this week's cache stage -- where
            # the session runs and writes -- and holds no `config.yaml`.
            # The seam reads its settings from THIS field instead.
            ledger_home=home,
        )
    )


def _full_inputs(home: Path, stage: Path, selected: tuple[str, ...], parked_rows: list[dict[str, Any]]) -> None:
    full_dir = stage / "full"
    parked_dir = stage / "parked"
    full_dir.mkdir(parents=True, exist_ok=True)
    parked_dir.mkdir(parents=True, exist_ok=True)
    for case_id in selected:
        _write_stage(stage, full_dir / f"{case_id}.md", cases.show(home, case_id, evidence_only=False).to_text() + "\n")
    for row in parked_rows:
        case_id = row["case"]
        _write_stage(stage, parked_dir / f"{case_id}.md", cases.show(home, case_id, evidence_only=False).to_text() + "\n")
    _write_stage(stage, stage / "user-model.yaml", _yaml_text(user_model.show(home)))
    _write_stage(
        stage,
        stage / "health.yaml",
        _yaml_text(
            {
                "facts": [asdict(item) for item in conditions.feed(home)],
                "catalogue_health": health.gather(home),
            }
        ),
    )


def _questions(path: Path) -> dict[str, Any]:
    data = _yaml_mapping(path)
    if set(data) != {"questions"} or not isinstance(data["questions"], list):
        raise OverseerError("questions.yaml: expected only a questions list")
    if len(data["questions"]) > 3:
        raise OverseerError("questions.yaml: at most three questions are permitted")
    clean = []
    for item in data["questions"]:
        if not isinstance(item, dict) or set(item) - {"id", "cases"}:
            raise OverseerError("questions.yaml: each entry permits only id and cases")
        if not isinstance(item.get("id"), str) or not isinstance(item.get("cases", []), list):
            raise OverseerError("questions.yaml: each entry needs a string id and cases list")
        clean.append({"id": item["id"], "cases": list(item.get("cases") or [])})
    return {"questions": clean}


def _report_text(
    *, date: str, run_id: str, model: str, selected: tuple[str, ...], population_count: int,
    excluded: int, model_calls: int, guard: int, parked_decided: int = 0,
    preview_sheets: int | None = None, preview_refused: int | None = None,
    refused: list[str] | None = None, hooks: list[str] | None = None,
    reason: str | None = None, user_model_lines: list[str] | None = None,
    questions: list[str] | None = None,
) -> str:
    refused = refused or []
    hooks = hooks or []
    question_lines = [f"- {line}" for line in (questions or [])] or ["- none"]
    selected_text = ", ".join(selected) if selected else "none"
    # The run-level reason and the per-item refusals share one list, so a refused
    # run never reads "- <reason>" followed by "- none" (observed by hand 2026-09-14).
    refusal_lines = [f"- {line}" for line in ([reason] if reason else []) + refused] or ["- none"]
    hook_lines = [f"- {line}" for line in hooks] or ["- none"]
    model_lines = [f"- {line}" for line in (user_model_lines or [])] or ["- none"]
    lines = [
        f"# Overseer report — {date}   run {run_id}   actor overseer   model {model}", "",
        f"## Examined ({len(selected)} of {population_count} cases this week, chosen by the overseer; why these, why it stopped)",
        f"- Cases: {selected_text}",
        f"- {excluded} cases excluded: freeze hash mismatch",
        f"- Model calls this run: {model_calls} of the runaway guard {guard}", "",
        "## Decided in the user's stead", f"- parked items decided: {parked_decided}",
        *( [f"- Dry-run preview: {preview_sheets} sheet(s); {parked_decided} would apply; {preview_refused} would refuse"] if preview_sheets is not None and preview_refused is not None else []),
        "", "## Hooks", *hook_lines, "", "## User model", *model_lines, "",
        "## Catalogue health", "- see health.yaml", "",
        "## Questions for you", *question_lines, "",
        "## Refused / could not do", *refusal_lines,
    ]
    return "\n".join(lines) + "\n"


def _validate_model_report(path: Path) -> list[str]:
    """Refuse malformed raw model output before any decision is applied."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) > 60:
        raise OverseerError("report.md: exceeds the 60-line limit")
    headings = [line[3:].partition(" (")[0] for line in lines if line.startswith("## ")]
    if headings != list(_REPORT_SECTIONS):
        raise OverseerError("report.md: section headings are missing or out of order")
    return lines


def _drop_bare_none(lines: list[str], section_start: int) -> None:
    """Remove the model's ``- none`` placeholder from a section the runner has
    just written its own lines into (observed by hand 2026-09-14: "- Model calls
    this run: …" followed by "- none")."""
    section_end = next(
        (i for i in range(section_start, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    bare_none = next(
        (i for i in range(section_start, section_end) if lines[i].strip() == "- none"),
        None,
    )
    if bare_none is not None:
        lines.pop(bare_none)


def _finalize_model_report(
    path: Path, *, date: str, run_id: str, model: str, selected: tuple[str, ...],
    population_count: int, excluded: int, model_calls: int, guard: int,
    refusals: list[str], hooks: list[str] | None = None,
    user_model_lines: list[str] | None = None,
    questions: list[str] | None = None,
) -> str:
    lines = _validate_model_report(path)
    lines[0] = f"# Overseer report — {date}   run {run_id}   actor overseer   model {model}"
    examined_at = next(i for i, line in enumerate(lines) if line.startswith("## Examined")) + 1
    facts = [
        f"- Cases examined: {', '.join(selected) if selected else 'none'} ({len(selected)} of {population_count})",
        f"- {excluded} cases excluded: freeze hash mismatch",
        f"- Model calls this run: {model_calls} of the runaway guard {guard}",
    ]
    lines[examined_at:examined_at] = facts
    _drop_bare_none(lines, examined_at)
    refused_at = next(i for i, line in enumerate(lines) if line.startswith("## Refused / could not do")) + 1
    if refusals:
        lines[refused_at:refused_at] = [f"- {item}" for item in refusals]
        _drop_bare_none(lines, refused_at)
    if hooks:
        hooks_at = next(i for i, line in enumerate(lines) if line.startswith("## Hooks")) + 1
        lines[hooks_at:hooks_at] = [f"- {item}" for item in hooks]
        _drop_bare_none(lines, hooks_at)
    if questions:
        # S-68 ruling 2's equivalent for the overseer's own stuck work. The
        # runner's question joins the model's own, never replaces them.
        questions_at = next(
            i for i, line in enumerate(lines) if line.startswith("## Questions for you")
        ) + 1
        lines[questions_at:questions_at] = [f"- {item}" for item in questions]
        _drop_bare_none(lines, questions_at)
    user_model_at = next(i for i, line in enumerate(lines) if line.startswith("## User model")) + 1
    next_heading = next(
        (i for i in range(user_model_at, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    if user_model_lines:
        replacement = [f"- {item}" for item in user_model_lines]
    else:
        existing = [line for line in lines[user_model_at:next_heading] if line.strip()]
        replacement = existing or ["- none"]
    lines[user_model_at:next_heading] = replacement
    if len(lines) > 60:
        owned = set(facts)
        owned.update(f"- {item}" for item in user_model_lines or [])
        owned.update(f"- {item}" for item in refusals)
        owned.update(f"- {item}" for item in hooks or [])
        owned.update(f"- {item}" for item in questions or [])
        needed = len(lines) - 60 + 1  # reserve the truncation marker itself
        omitted = 0
        for index in range(len(lines) - 1, 0, -1):
            line = lines[index]
            if line.startswith("## ") or line in owned:
                continue
            lines.pop(index)
            omitted += 1
            if omitted == needed:
                break
        lines.append(f"- model report truncated: {omitted} model lines omitted")
    return "\n".join(lines) + "\n"


def _record_push_failure(home: Path, report_path: Path, latest: Path, failure: str) -> None:
    """Commit the post-boundary push outcome without leaving report files dirty."""
    lines = report_path.read_text(encoding="utf-8").splitlines()
    lines.insert(1, f"- {failure}")
    updated = "\n".join(lines) + "\n"
    with intents.ledger_write(home):
        intent = intents.begin(
            home, "overseer-push-failure", [report_path, latest],
            f"self-learn: overseer push failure {failure}",
        )
        intents.add_step(intent, report_path)
        intents.add_step(intent, latest)
        fsops.atomic_write(report_path, updated, fsync=True)
        fsops.atomic_write(latest, updated, fsync=True)
        intents.complete(intent)
        gitops.stage_and_commit(home, [report_path, latest], intent.commit_subject, None)
        intents.finish(intent)


def _validate_findings(data: dict[str, Any], selected: tuple[str, ...]) -> list[dict[str, Any]]:
    findings = data.get("findings")
    if set(data) != {"findings"} or not isinstance(findings, list):
        raise OverseerError("findings.yaml: expected only a findings list")
    clean: list[dict[str, Any]] = []
    examined: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) - {"case", "kind", "text", "ref"}:
            raise OverseerError("findings.yaml: each entry permits case, kind, text, and ref only")
        case_id = finding.get("case")
        kind = finding.get("kind")
        if case_id not in selected or kind not in ("examined", "dependency-moved"):
            raise OverseerError(f"findings.yaml: refused finding for {case_id!r} kind {kind!r}")
        if not isinstance(finding.get("text"), str) or not finding["text"].strip():
            raise OverseerError("findings.yaml: every finding needs non-empty text")
        if kind == "dependency-moved" and not isinstance(finding.get("ref"), str):
            raise OverseerError("findings.yaml: dependency-moved requires ref")
        if kind == "examined":
            examined.add(case_id)
        clean.append(dict(finding))
    missing = [case_id for case_id in selected if case_id not in examined]
    if missing:
        raise OverseerError(f"findings.yaml: missing examined finding(s) {missing!r}")
    return clean


def _validate_successor(path: Path, parked: set[str]) -> None:
    data = _yaml_mapping(path)
    required = {"kind", "trigger", "outcome", "records", "scope", "question", "evidence", "decision", "supersedes"}
    missing = sorted(required - set(data))
    if missing:
        raise OverseerError(f"{path.name}: missing successor field(s) {missing!r}")
    if data.get("supersedes") not in parked:
        raise OverseerError(f"{path.name}: supersedes must name a verified parked case")
    if data.get("kind") == "parked" or data.get("outcome") == "parked":
        raise OverseerError(f"{path.name}: a decision successor cannot remain parked")


def _validate_maintenance_case(path: Path) -> None:
    """A9 / O-7.3: the case paired with a CASELESS sheet is a catalogue
    change, not a decision on a delegated question, so its `kind` must be
    `maintenance`.

    The caseless half of O-7.3 ("refuse a catalogue-change sheet lacking a
    top-level case") shipped; this is the half `build-lane-b.md:24-31`
    recorded as not built, because changing the general successor validator
    crossed that lane's ownership boundary. A caseless sheet supersedes
    nothing — there is no parked predecessor for it to decide — so
    :func:`_validate_successor`'s `supersedes` rule cannot apply to it, and
    without a rule of its own the pairing had no validator at all.
    """
    data = _yaml_mapping(path)
    required = {"kind", "trigger", "outcome", "records", "scope", "question", "evidence", "decision"}
    missing = sorted(required - set(data))
    if missing:
        raise OverseerError(f"{path.name}: missing case field(s) {missing!r}")
    if data.get("kind") != "maintenance":
        raise OverseerError(
            f"{path.name}: a caseless sheet's paired case must be "
            f"kind: maintenance, not {data.get('kind')!r}"
        )
    if data.get("outcome") == "parked" or data.get("supersedes") is not None:
        raise OverseerError(
            f"{path.name}: a maintenance case supersedes no parked case and "
            "cannot remain parked"
        )


def _write_report_only(stage: Path, text: str) -> Path:
    path = stage / "report.final.md"
    _write_stage(stage, path, text)
    return path


def _first_line(path: Path) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.readline()
    except (OSError, UnicodeDecodeError):
        return ""


def _dated_report_path(home: Path, date: str, run_id: str) -> Path:
    """B4: a second report on the same UTC day never overwrites the first.

    A run always reuses its OWN dated report — a resume publishes the same
    run's final text over its partial one, which is the same document —
    and any OTHER run of that day takes the next free `-2`, `-3`, … name.
    `overseer report --date` keeps answering with the day's first report;
    `latest-report.md` is the canonical newest one either way.
    """
    directory = home / "overseer"
    marker = f"run {run_id}"
    first = directory / f"{date}-report.md"
    if not first.is_file() or marker in _first_line(first):
        return first
    for n in range(2, 100):
        candidate = directory / f"{date}-report-{n}.md"
        if not candidate.is_file() or marker in _first_line(candidate):
            return candidate
    raise OverseerError(f"overseer report: too many reports already exist for {date}")


def _commit_failed_attempt(
    home: Path,
    intent: intents.Intent | None,
    *,
    coverage_path: Path | None,
    coverage_before: bytes | None,
    report_text: str | None,
    date: str,
    run_id: str,
    week: str,
    started: str,
    attempt: int,
    cap: int,
    kind: str,
    detail: str | None,
    closed_text: str | None,
    write_note: bool = True,
) -> Path:
    """One commit for one failed attempt: its report, its failure note and,
    when the cap was reached, the close-out note.

    A15: the trace is committed, so a lost week is visible in the ledger
    rather than only in the cache stage the next run wipes.  A5: coverage
    is restored to the bytes this attempt found, because the second model
    call's output never validated — the week was not examined and
    `last_run_at` must not say it was.  A14: `open-questions.yaml` is not
    among the paths at all, so last week's questions survive untouched.

    *intent* is the run's own intent when the failure happened inside the
    run's ledger-write span, and ``None`` for a failure of the FIRST model
    call, which happens before any `intents.begin` — that case opens its
    own span here.
    """
    note = _note_path(home, week, started, run_id)
    closed = failures_dir(home, week) / "closed.md"
    report_path = (
        None if report_text is None else _dated_report_path(home, date, run_id)
    )
    latest = home / "overseer" / "latest-report.md"
    # A close-out that a LATER run writes counts nothing of its own
    # (02-schema §3a), so it leaves no attempt note — only the close-out.
    paths = [note] if write_note else []
    if closed_text is not None:
        paths.append(closed)
    if report_path is not None:
        paths.extend([report_path, latest])
    subject = f"self-learn: overseer attempt {attempt} failed ({kind})"
    # `intents.ledger_write` is re-entrant: a pass-through when the caller
    # already holds the span, and the outermost acquisition for a failure of
    # the FIRST model call, which happens before any `intents.begin`. Written
    # flat on purpose — a closure here would be its own lock-invariant node.
    with intents.ledger_write(home):
        owner = intent if intent is not None else intents.begin(
            home, "overseer-attempt-failed", paths, subject
        )
        # A5, under the lock with every other ledger write of this span: the
        # coverage bytes this attempt found are put back. The second model
        # call's output never validated, so the week was not examined and
        # `last_run_at` must not claim it was.
        if coverage_path is not None:
            if coverage_before is None:
                coverage_path.unlink(missing_ok=True)
            else:
                fsops.atomic_write(coverage_path, coverage_before, fsync=True)
        note.parent.mkdir(parents=True, exist_ok=True)
        for target in paths:
            intents.add_step(owner, target)
        if write_note:
            fsops.atomic_write(
                note,
                _note_text(
                    week=week, run_id=run_id, started=started, attempt=attempt,
                    cap=cap, kind=kind, detail=detail,
                ),
                fsync=True,
            )
        if closed_text is not None:
            fsops.atomic_write(closed, closed_text, fsync=True)
        if report_path is not None and report_text is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(report_path, report_text, fsync=True)
            fsops.atomic_write(latest, report_text, fsync=True)
        intents.complete(owner)
        gitops.stage_and_commit(home, paths, owner.commit_subject, None)
        intents.finish(owner)
    return report_path if report_path is not None else note


def _sheet_pairs(stage: Path) -> list[tuple[Path | None, Path]]:
    paired = []
    for sheet in sorted(stage.glob("sheet-*.yaml")):
        paired.append((stage / sheet.name.replace("sheet-", "case-", 1), sheet))
    if paired:
        for case_file, _sheet in paired:
            if case_file is None or not case_file.is_file():
                raise OverseerError(f"{case_file.name}: missing successor case paired with sheet")
        return paired
    sheet = stage / "sheet.yaml"
    if not sheet.is_file():
        return []
    # A9: `sheet-<name>.yaml` pairs with `case-<name>.yaml`, so the caseless
    # form pairs with `case.yaml` — the pairing this function never looked
    # for.  Without it a non-empty `sheet.yaml` could only ever be refused,
    # which made O-7.3's "or whose case is not a `kind: maintenance` case"
    # half unenforceable rather than merely unenforced.
    case = stage / "case.yaml"
    return [(case if case.is_file() else None, sheet)]


def _load_sheet_allow_empty(path: Path, home: Path) -> batch.Sheet | None:
    """The overseer contract permits ``items: []`` to mean no decisions."""
    data = _yaml_mapping(path)
    if data.get("items") == []:
        unknown = set(data) - {"version", "items", "case"}
        if unknown or data.get("version") != 1 or data.get("case") is not None:
            raise OverseerError(
                f"{path.name}: an empty sheet permits only version: 1 and items: []"
            )
        return None
    close_calls: dict[int, bool] = {}
    for index, item in enumerate(data.get("items") or [], start=1):
        if not isinstance(item, dict):
            continue
        value = item.pop("close_call", False)
        if not isinstance(value, bool):
            raise OverseerError(f"{path.name}: item {index} close_call must be boolean")
        close_calls[index] = value
    fsops.atomic_write(path, _yaml_text(data), fsync=False)
    sheet = batch.load_sheet(path, home=home)
    cast(Any, sheet).close_calls = close_calls
    return sheet


def _worst_code(codes: list[int], *, any_applied: bool) -> int:
    for code in (7, 4, 3):
        if code in codes:
            return code
    if 8 in codes or (any_applied and any(code in (1, 6) for code in codes)):
        return EXIT_PARTIAL
    if 6 in codes:
        return 6
    return 1 if 1 in codes else 0


def _manifest_text(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _model_updates(path: Path) -> list[dict[str, Any]]:
    data = _yaml_mapping(path)
    if set(data) != {"updates"} or not isinstance(data["updates"], list):
        raise OverseerError("user-model-delta.yaml: expected only an updates list")
    updates: list[dict[str, Any]] = []
    for index, value in enumerate(data["updates"], start=1):
        if isinstance(value, dict):
            updates.append(dict(value))
        else:
            updates.append({"_malformed": value, "_ordinal": index})
    return updates


def _model_operation(payload: dict[str, Any], *, ordinal: int) -> dict[str, Any]:
    identity = json.dumps(
        {"ordinal": ordinal, "kind": "model", "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "id": "op-" + hashlib.sha256(identity).hexdigest()[:12],
        "kind": "model",
        "payload": dict(payload),
        "state": "pending",
        "baseline": None,
        "result": None,
    }


def _model_entries(home: Path) -> list[dict[str, Any]]:
    shown = user_model.show(home)
    return [
        {**entry, "container": container}
        for container, entries in (shown.get("containers") or {}).items()
        for entry in entries
    ]


def _model_result(home: Path, operation: dict[str, Any]) -> dict[str, Any] | None:
    payload = dict(operation["payload"])
    action = payload.get("action", "add")
    if action == "add":
        baseline = set(operation.get("baseline") or [])
        matches = [
            row for row in _model_entries(home)
            if row.get("id") not in baseline
            and all(
                row.get(key) == value
                for key, value in payload.items()
                if key not in {"action", "by", "held_since"}
            )
        ]
        if len(matches) == 1:
            return {"state": "applied", "id": matches[0]["id"], "recovered": True}
        if len(matches) > 1:
            return {"state": "refused", "error": "ambiguous user-model addition"}
    elif action in {"lapse", "retire"}:
        target = payload.get("id") or payload.get("target")
        match = next((row for row in _model_entries(home) if row.get("id") == target), None)
        if match is not None and match.get("status") == "LAPSED":
            return {"state": "applied", "id": target, "recovered": True}
    return None


def _publish_manifest_revision(home: Path, manifest: dict[str, Any], *, reason: str) -> None:
    path = execution_evidence.manifest_path(home, cast(str, manifest["run_id"]))
    subject = f"self-learn: overseer manifest {manifest['run_id']} ({reason})"
    with intents.ledger_write(home):
        intent = intents.begin(home, "overseer-manifest", [path], subject)
        fsops.atomic_write(path, _manifest_text(manifest), fsync=True)
        intents.complete(intent)
        gitops.stage_and_commit(home, [path], subject, reason)
        intents.finish(intent)


def _update_manifest(home: Path, run_id: str, *, reason: str, update) -> dict[str, Any]:
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    update(manifest)
    _publish_manifest_revision(home, manifest, reason=reason)
    return manifest


def _maintain_manifest(
    home: Path, run_id: str
) -> tuple[int, int, bool, list[str]]:
    """Apply committed user-model operations one at a time and checkpoint each."""
    applied = 0
    refused = 0
    lines: list[str] = []
    while True:
        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
        operation = next(
            (
                row for row in manifest.get("maintenance") or []
                if row.get("state") not in {"applied", "refused"}
            ),
            None,
        )
        if operation is None:
            return applied, refused, False, lines
        operation_id = cast(str, operation["id"])
        if operation["state"] == "pending":
            baseline = None
            if operation["payload"].get("action", "add") == "add":
                baseline = [row["id"] for row in _model_entries(home)]
            _update_manifest(
                home,
                run_id,
                reason=f"maintenance start {operation_id}",
                update=lambda current, op_id=operation_id, value=baseline: next(
                    row for row in current["maintenance"] if row["id"] == op_id
                ).update(state="started", baseline=value),
            )
            continue
        outcome = _model_result(home, operation)
        try:
            if outcome is None:
                payload = dict(operation["payload"])
                if "_malformed" in payload:
                    raise user_model.UserModelUsageError(
                        "user-model-delta.yaml: each update must be a mapping"
                    )
                action = payload.pop("action", "add")
                payload.pop("by", None)
                if action == "add":
                    if payload.get("source") != "system-reading":
                        raise user_model.UserModelError(
                            "overseer refused a non-system-reading source"
                        )
                    entry_id = user_model.add_entry(home, by="overseer", **payload)
                elif action in {"lapse", "retire"}:
                    entry_id = cast(str, payload.pop("id", payload.pop("target", "")))
                    user_model.lapse_entry(home, entry_id, by="overseer", **payload)
                else:
                    raise user_model.UserModelUsageError(
                        f"user-model-delta.yaml: unknown action {action!r}"
                    )
                outcome = {"state": "applied", "id": entry_id}
        except intents.LedgerStoppedError as exc:
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "stopped", "reason": str(exc)[:300]})
            return applied, refused, True, lines
        except (user_model.UserModelError, TypeError, ValueError) as exc:
            refused += 1
            outcome = {"state": "refused", "error": str(exc)}
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "model-update-refused", "reason": str(exc)[:300]})
        else:
            applied += 1
        assert outcome is not None
        _update_manifest(
            home,
            run_id,
            reason=f"maintenance result {operation_id}",
            update=lambda current, op_id=operation_id, result=outcome: next(
                row for row in current["maintenance"] if row["id"] == op_id
            ).update(state=result["state"], result=result),
        )
        if outcome["state"] == "applied":
            lines.append(f"{outcome['id']}: {operation['payload'].get('action', 'add')} applied")
        else:
            lines.append(f"{operation_id}: refused — {outcome['error']}")


def _committed_overseer_manifests(home: Path) -> list[dict[str, Any]]:
    """Read overseer recipes from committed Git truth, never the cache/index."""
    rows = gitops._git(  # noqa: SLF001 -- committed discovery seam
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs"
    ).stdout.splitlines()
    found: list[dict[str, Any]] = []
    for relpath in rows:
        if not relpath.startswith("cases/runs/") or not relpath.endswith(".json"):
            continue
        run_id = Path(relpath).stem
        try:
            manifest = execution_evidence.read_manifest(home, run_id)
        except (execution_evidence.ExecutionEvidenceError, gitops.GitOpsError):
            continue
        if manifest.get("version") == 1 and manifest.get("actor") == "overseer":
            found.append(manifest)
    return found


#: A committed overseer run record a later run must never pick up again.
#: `closed` joins `complete` under S-68 ruling 2: a week the runner closed at
#: `runs.attempt_cap` is finished business — without this, the closed record
#: would be resumed on every two-hour tick for ever, which is the stall the
#: close-out exists to end, one level up.
_TERMINAL_RUN_STATUSES = frozenset({"complete", "closed"})


def _unfinished_manifest(home: Path) -> dict[str, Any] | None:
    unfinished = [
        row for row in _committed_overseer_manifests(home)
        if row.get("status") not in _TERMINAL_RUN_STATUSES
    ]
    if len(unfinished) > 1:
        raise OverseerError("more than one unfinished overseer manifest")
    return unfinished[0] if unfinished else None


def has_unfinished_work(home: Path | str) -> bool:
    """Whether committed Git truth contains an unfinished overseer recipe."""
    return _unfinished_manifest(Path(home)) is not None


#: The shipped timer's calendar, and the boundary that opens an overseer
#: WEEK: Sunday 04:15 local (`systemd/self-learn-overseer.timer`). Defined
#: here, not in `serve`, because the runner's own same-week guard and the
#: scheduler's catch-up rule must read one definition (`serve` imports
#: these; nothing here imports `serve`).
WEEK_WEEKDAY, WEEK_HOUR, WEEK_MINUTE = 6, 4, 15


def week_boundary(now: float) -> float:
    """The most recent Sunday 04:15 local at or before ``now`` — the
    boundary that opened the week ``now`` falls in (S-68, THE OVERSEER'S
    WEEK). Only the most recent boundary defines the current week: after a
    longer outage, older undone weeks are subsumed by one catch-up run
    rather than replayed one per week."""
    local = time.localtime(now)
    days_since = (local.tm_wday - WEEK_WEEKDAY) % 7
    fields = (WEEK_HOUR, WEEK_MINUTE, 0, 0, 0, -1)
    target = time.mktime(
        (local.tm_year, local.tm_mon, local.tm_mday - days_since) + fields
    )
    if target > now:
        # `now` is earlier in the day than 04:15 on a Sunday: step a whole
        # week back through `mktime` (never by 7*86400, which is an hour
        # wrong across a DST change).
        target = time.mktime(
            (local.tm_year, local.tm_mon, local.tm_mday - days_since - 7) + fields
        )
    return target


def _coverage_last_run_at(home: Path) -> str | None:
    value = population_mod.load_coverage(home / "overseer" / "coverage.yaml").get(
        "last_run_at"
    )
    return value if isinstance(value, str) and value else None


def previous_run_exists(home: Path | str) -> bool:
    """Whether the overseer has ever completed a run here — coverage's
    `last_run_at` is not null. The catch-up rule (A16) applies only once
    this is true (orchestrator ruling 2026-09-19): an overseer that has
    never run stays on the plain calendar rule, so turning
    `overseer.enabled` on midweek cannot start an unattended first run."""
    return _coverage_last_run_at(Path(home)) is not None


def _iso_epoch(value: str) -> float | None:
    """`None` when the stamp does not parse — `chrono.to_dt` is lenient and
    never raises, it just answers `None`."""
    parsed = chrono.to_dt(value)
    return None if parsed is None else parsed.timestamp()


def week_key(boundary_epoch: float) -> str:
    """S-68: "A week is identified on the run record by the local date of
    the Sunday 04:15 boundary that opened it." One spelling, used by the
    run record's `week` field, by the failure-note directory, and by every
    reader of either."""
    return time.strftime("%Y-%m-%d", time.localtime(boundary_epoch))


def _manifest_week(manifest: dict[str, Any]) -> str | None:
    """A run record's week, from its own `week` field or — for a record
    written before S-68 — derived from the boundary its `started` stamp
    falls in. Never invented: an unreadable stamp answers `None`."""
    recorded = manifest.get("week")
    if isinstance(recorded, str) and _DATE_RE.fullmatch(recorded):
        return recorded
    started = manifest.get("started")
    if not isinstance(started, str):
        return None
    epoch = _iso_epoch(started)
    return None if epoch is None else week_key(week_boundary(epoch))


def failures_dir(home: Path | str, week: str) -> Path:
    """Where one week's committed failure notes live (A15)."""
    return Path(home) / "overseer" / "failures" / week


def _committed_failure_notes(home: Path, week: str) -> list[str]:
    """The week's failure notes as COMMITTED git truth (S-68: "attempts are
    counted from committed evidence ... never from the cache alone"). A
    worktree copy is not evidence; an uncommitted note counts nothing."""
    try:
        rows = gitops._git(  # noqa: SLF001 -- committed discovery seam
            home, "ls-tree", "-r", "--name-only", "HEAD",
            "--", f"overseer/failures/{week}",
        ).stdout.splitlines()
    except gitops.GitOpsError:
        return []
    # `closed.md` is the close-out's own note, not an attempt: counting it
    # would inflate the week by one the moment the close-out lands.
    return [
        row for row in rows
        if row.endswith(".md") and not row.endswith("/closed.md")
    ]


def attempt_cap(home: Path | str) -> int:
    value, _source = settings.resolve_setting(
        Path(home), settings.by_name("runs.attempt_cap")
    )
    return int(cast(int, value))


def _run_record_for_week(home: Path, week: str) -> dict[str, Any] | None:
    """The committed overseer run record belonging to ``week``, if any."""
    for manifest in _committed_overseer_manifests(home):
        if _manifest_week(manifest) == week:
            return manifest
    return None


def _record_attempts(manifest: dict[str, Any] | None) -> int:
    """02-schema §3a: the explicit `attempt_count`, or — for a record
    written before that rule — one attempt for the record's existence,
    never an invented number."""
    if manifest is None:
        return 0
    value = manifest.get("attempt_count")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 1


def week_attempts(home: Path | str, week: str) -> int:
    """How many attempts this week has had, from committed evidence only.

    The two sources are DISJOINT by construction, so they sum exactly. An
    attempt either fails before `_prepare_manifest` — no run record exists
    or is touched, and it commits a failure note — or it reaches
    `_prepare_manifest`, which opens the week's run record with
    `attempt_count: 1` and carries its reason in the record's own
    `failure` / `failure_detail` fields instead of a note. Every later
    attempt is a resume, and a resume only ever increments the record.

    Known gap, stated rather than papered over: an attempt SIGKILLed before
    it has committed anything at all leaves neither, so it counts nothing
    and the cap is reached one attempt later. Closing it would cost a
    commit at the start of every run, including the ones that succeed.
    """
    resolved = Path(home)
    return len(_committed_failure_notes(resolved, week)) + _record_attempts(
        _run_record_for_week(resolved, week)
    )


def week_closed(home: Path | str, week: str) -> bool:
    """Whether the runner has already written this week's close-out
    (02-schema §3a: `status: closed` with `outcome: attempts-exhausted`)."""
    record = _run_record_for_week(Path(home), week)
    if record is not None and record.get("status") == "closed":
        return True
    return (failures_dir(home, week) / "closed.md").is_file()


def week_done(home: Path | str, boundary_epoch: float) -> bool:
    """Whether the overseer week that opened at ``boundary_epoch`` is DONE
    (S-68): a run for that week completed, or its attempts reached the
    cap. Read from committed evidence only — the cache is a projection any
    restart can lose.

    The evidence is a completed run — coverage's `last_run_at` at or after
    the boundary, or a committed overseer run record that started at or
    after it and is `complete` — or, since U3, a week whose attempts
    reached `runs.attempt_cap`: counted from the committed failure notes
    plus the committed run record, and recorded on that record as
    `status: closed` / `outcome: attempts-exhausted`.

    This answer HOLDS the scheduler, so `overseer.run` must perform a
    pending close-out BEFORE it consults this — otherwise a week that
    reached the cap but whose close-out write failed would be held for
    ever with its question never written (the S-68 shape, one level up).

    An unreadable timestamp never claims the week is done: the safe
    direction is to attempt the work, which the attempt cap bounds."""
    resolved = Path(home)
    last_run_at = _coverage_last_run_at(resolved)
    if last_run_at is not None:
        epoch = _iso_epoch(last_run_at)
        if epoch is not None and epoch >= boundary_epoch:
            return True
    key = week_key(boundary_epoch)
    for manifest in _committed_overseer_manifests(resolved):
        status_name = manifest.get("status")
        if status_name == "closed" and _manifest_week(manifest) == key:
            return True
        if status_name != "complete":
            continue
        started = manifest.get("started")
        if not isinstance(started, str):
            continue
        epoch = _iso_epoch(started)
        if epoch is not None and epoch >= boundary_epoch:
            return True
    return week_attempts(resolved, key) >= attempt_cap(resolved)


# ------------------------------------- failure notes and close-out (S-68)
#
# Deliberately module-level, never closures inside `run`: `overseer/run.py`
# has no blanket `NOT_REPO_TRUTH` entry, so the lock-invariant walker walks
# every committed write here, and a nested closure becomes its own unlocked
# node.  Each of these either takes `intents.ledger_write` itself or is
# handed an intent opened under one by its caller.


def _note_path(home: Path, week: str, started: str, run_id: str) -> Path:
    """One file per failed attempt, named so two attempts of the same week
    can never collide: the attempt's own start stamp plus its run id."""
    stamp = started.replace(":", "-")
    return failures_dir(home, week) / f"{stamp}-{run_id}.md"


def _note_text(
    *, week: str, run_id: str, started: str, attempt: int, cap: int,
    kind: str, detail: str | None,
) -> str:
    """A15's short dated failure note, carrying the REAL reason.

    A committed reason of `exit` alone is what made the 2026-09-14 outage
    unreadable from the ledger, so the kind and the message the transport
    or the validator actually returned are both here.
    """
    return "\n".join([
        f"# Overseer attempt failed — {started[:10]}   week {week}   "
        f"run {run_id}   attempt {attempt} of {cap}",
        "",
        f"- failure: {kind}",
        f"- detail: {detail or 'no detail was returned'}",
        f"- at: {started}",
    ]) + "\n"


def _failure_kind_text(manifest: dict[str, Any]) -> str:
    """One display string for the close-out's evidence.

    `failure` when §3a's closed set has a literal for it; otherwise the
    numeric halt code the ledger stop rides, spelled out as prose — the
    code is never folded INTO `failure`, but the close-out's question has
    to be able to say what stopped the run.
    """
    failure = manifest.get("failure")
    if isinstance(failure, str) and failure:
        return failure
    code = manifest.get("halt_code")
    if isinstance(code, int) and not isinstance(code, bool):
        return f"ledger halt, exit {code}"
    return "no-progress"


def _decided_clause(applied: int) -> str:
    """What this run actually did, rather than a blanket "nothing was
    decided" — earlier sheets of the SAME run may have applied before a
    later one stuck, and saying otherwise in the close-out is a false
    statement in the one place the user is asked to act on it."""
    if applied <= 0:
        return "nothing of this week was decided"
    noun = "item" if applied == 1 else "items"
    return (
        f"{applied} {noun} of this run applied before it stuck; the rest was "
        "not decided"
    )


def _closed_note_text(
    *, week: str, attempts: int, kind: str, detail: str | None,
    unfinished: list[str], applied: int = 0,
) -> str:
    """The committed close-out note.  02-schema §3a: "The overseer's own
    abandonment has no lesson of its own to park: its durable obligation is
    a committed close-out note and the question its report puts to the
    user." This is the first half; :func:`_close_out_questions` is the
    second."""
    lines = [
        f"# Overseer week closed — {week}   attempts-exhausted",
        "",
        f"- attempts: {attempts}",
        f"- failure: {kind}",
        f"- detail: {detail or 'no detail was returned'}",
        f"- applied: {applied}",
        f"- the next week's run may start; {_decided_clause(applied)}",
    ]
    lines.extend(f"- unfinished: {item}" for item in unfinished)
    return "\n".join(lines) + "\n"


def _short(text: str | None, limit: int = 200) -> str:
    flat = " ".join(str(text or "").split())
    if not flat:
        return "no detail was returned"
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _close_out_questions(
    *, week: str, attempts: int, kind: str, detail: str | None,
    unfinished: list[str], applied: int = 0,
) -> list[str]:
    """Ruling 2's equivalent for the overseer's own stuck work: "a question
    put to the user in its report".

    It is a plain report line, not a row in `open-questions.yaml`: that
    index is keyed by `um-<4hex>@r<n>` propositions and
    `conversation.open_questions` resolves every row through
    `_entry_and_revision`, so a runner-written id there would make
    `overseer open` raise.  `conversation._question_block` prints the whole
    section verbatim, so the line is displayed either way.
    """
    tail = f" Unfinished: {', '.join(unfinished)}." if unfinished else ""
    return [
        f"the week that opened {week} was closed after {attempts} failed "
        f"attempts ({kind}: {_short(detail)}); {_decided_clause(applied)}, "
        f"and the machinery, not the merits, is what stopped it.{tail} "
        "Should these be looked at by hand, or left to the next week's run?"
    ]


def _close_out_if_exhausted(
    home: Path, *, week: str, attempts: int, cap: int, kind: str,
    detail: str | None, unfinished: list[str] | None = None,
) -> tuple[str | None, list[str]]:
    """Ruling 2, for an attempt that failed before any run record existed.

    Answers (close-out note text, question lines) — ``(None, [])`` while the
    week still has attempts left, or when a previous run already wrote this
    week's close-out (it is idempotent and retried, and counts nothing of
    its own, so a close-out whose write failed is simply re-attempted).
    """
    if attempts < cap or week_closed(home, week):
        return None, []
    units = list(unfinished or [])
    return (
        _closed_note_text(
            week=week, attempts=attempts, kind=kind, detail=detail,
            unfinished=units,
        ),
        _close_out_questions(
            week=week, attempts=attempts, kind=kind, detail=detail,
            unfinished=units,
        ),
    )


def _last_failure(home: Path, week: str) -> tuple[str, str | None]:
    """The kind and detail of the week's most recent committed failure —
    the evidence the close-out's question cites."""
    notes = sorted(_committed_failure_notes(home, week))
    if not notes:
        return "unknown", None
    try:
        text = gitops._git(home, "show", f"HEAD:{notes[-1]}").stdout  # noqa: SLF001
    except gitops.GitOpsError:
        return "unknown", None
    kind = "unknown"
    detail: str | None = None
    for line in text.splitlines():
        if line.startswith("- failure: "):
            kind = line.removeprefix("- failure: ").strip() or "unknown"
        elif line.startswith("- detail: "):
            detail = line.removeprefix("- detail: ").strip() or None
    return kind, detail


def _close_out_pending_week(
    home: Path, *, run_id: str, week: str, attempts: int, cap: int
) -> RunResult:
    """Write a close-out the cap already earned but no run has written yet.

    This is a HOLD, not an attempt: it takes ownership of nothing, makes no
    model call and increments no count (02-schema §3a — "a close-out ... is
    retried by the next run, is idempotent ... and increments no count of
    its own").
    """
    kind, detail = _last_failure(home, week)
    # Nothing of this run landed — it took ownership of nothing and made no
    # model call — so `applied` is 0 and FW-85's producer space gives
    # `EXIT_REFUSED`, the same rule `_execute_manifest`'s close-out follows.
    closed_text = _closed_note_text(
        week=week, attempts=attempts, kind=kind, detail=detail, unfinished=[],
        applied=0,
    )
    questions = _close_out_questions(
        week=week, attempts=attempts, kind=kind, detail=detail, unfinished=[],
        applied=0,
    )
    started = chrono.now_iso()
    text = _report_text(
        date=started[:10], run_id=run_id, model="none", selected=(),
        population_count=0, excluded=0, model_calls=0,
        guard=0, questions=questions,
        reason=(
            f"the week that opened {week} reached the attempt cap ({attempts} "
            f"of {cap}); it is closed and nothing was decided"
        ),
    )
    report_path = _commit_failed_attempt(
        home, None, coverage_path=None, coverage_before=None,
        report_text=text, date=started[:10], run_id=run_id, week=week,
        started=started, attempt=attempts, cap=cap, kind=kind, detail=detail,
        closed_text=closed_text, write_note=False,
    )
    _notify_week_closed(home, week, attempts, kind, [run_id])
    _journal(home, {
        "at": chrono.now_iso(), "run": run_id, "status": "week-closed",
        "week": week, "attempts": attempts, "failure": kind,
    })
    return RunResult(
        "closed", EXIT_REFUSED, run_id, 0, (), 0, 0, 1, str(report_path)
    )


def _commit_phase_a_failure(
    home: Path, *, dry_run: bool, week: str, attempt: int, cap: int,
    run_id: str, started: str, kind: str, detail: str | None,
    model: str, population_count: int, excluded: int, model_calls: int,
    guard: int, reason: str,
) -> Path | None:
    """The committed trace for a failure BEFORE the run's own ledger-write
    span exists — a failed first model call, a runaway after it, an invalid
    selection (A15).  Returns the published report path, or ``None``.

    These paths published no report before and still do not, EXCEPT when
    this attempt is the one that reaches the cap: the close-out's question
    has to land in `latest-report.md`, because that is the only file
    `overseer open` reads it from.  A dry run writes nothing at all.
    """
    if dry_run:
        return None
    closed_text, questions = _close_out_if_exhausted(
        home, week=week, attempts=attempt, cap=cap, kind=kind, detail=detail,
    )
    report_text = None
    if closed_text is not None:
        report_text = _report_text(
            date=started[:10], run_id=run_id, model=model, selected=(),
            population_count=population_count, excluded=excluded,
            model_calls=model_calls, guard=guard, reason=reason,
            questions=questions,
        )
    published = _commit_failed_attempt(
        home, None, coverage_path=None, coverage_before=None,
        report_text=report_text, date=started[:10], run_id=run_id, week=week,
        started=started, attempt=attempt, cap=cap, kind=kind, detail=detail,
        closed_text=closed_text,
    )
    if closed_text is None:
        return None
    _notify_week_closed(home, week, attempt, kind, [run_id])
    return published


def _progress_signature(manifest: dict[str, Any]) -> dict[str, int]:
    """S-68 PROGRESS, as a per-unit rank the caller can compare.

    A key absent from the "before" reading counts as 0, so a unit that did
    not exist at the start of the attempt and exists now IS progress. This
    is deliberately not "HEAD moved": reading it that way gets this exact
    stall wrong, because the overseer moves HEAD on every single run — it
    rewrites and commits its report each time.
    """
    signature: dict[str, int] = {}
    for case_id, recipe in (manifest.get("cases") or {}).items():
        states = {
            int(row["n"]): str(row.get("state") or "")
            for row in recipe.get("dispositions") or []
            if isinstance(row, dict) and isinstance(row.get("n"), int)
        }
        for row in recipe.get("items") or []:
            n = int(row["n"])
            state = states.get(n)
            # `not-attempted` ranks 0, exactly like having no disposition at
            # all: it is the record of something that did NOT happen. Ranking
            # it 1 made the first resume of a sheet frozen behind a committed
            # refusal read as progress, because the runner had newly written
            # down that item 2 was never dispatched. Naming a non-event is
            # not movement toward a terminal value.
            signature[f"item:{case_id}:{n}"] = (
                2 if state in _TERMINAL_ITEM_STATES
                else 0 if state in (None, "not-attempted")
                else 1
            )
    for operation in manifest.get("maintenance") or []:
        signature[f"maintenance:{operation.get('id')}"] = (
            2 if operation.get("state") in {"applied", "refused"} else 1
        )
    return signature


def _made_progress(before: dict[str, int], after: dict[str, int]) -> bool:
    return any(value > before.get(key, 0) for key, value in after.items())


def _week_closed_summary(week: str, attempts: int, kind: str) -> str:
    return (
        f"self-learn overseer: the week that opened {week} was closed after "
        f"{attempts} failed attempts ({kind}); its report carries the "
        "question, and the next week's run may start"
    )


def _notify_week_closed(
    home: Path, week: str, attempts: int, kind: str, ids: list[str]
) -> None:
    """Ruling 2's "the user is notified", ONCE per closed week, through the
    shipped helper unchanged — this module never calls `notify-send`."""
    try:
        notify.send(home, "routine", _week_closed_summary(week, attempts, kind), ids)
    except Exception as exc:  # noqa: BLE001 -- a notification never fails a run
        _journal(home, {
            "at": chrono.now_iso(), "run": ids[0] if ids else week,
            "status": "notify-failed", "reason": str(exc)[:300],
        })


def _queue_week_closed(
    deferred: "_DeferredNotice", home: Path, week: str, attempts: int,
    kind: str, ids: list[str],
) -> None:
    """The same notification, from inside the run's ledger lock: queued so
    it fires only after the lock exits (a notification must never be sent
    while the commit lock is held)."""
    deferred.add(home, "routine", _week_closed_summary(week, attempts, kind), ids)


def _scan_manifest_or_refuse(manifest: dict[str, Any]) -> None:
    """Scan prepared free text while excluding code-owned content hashes."""
    hits: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and key not in {
            "sheet_sha", "sheet_digest", "start_head", "prepared_head"
        }:
            if scan.scan(value):
                hits.append(key or "value")

    visit(manifest)
    if hits:
        raise OverseerError(
            "prepared manifest secret scan refused field(s): "
            + ", ".join(sorted(set(hits)))
        )


def _reserved_case_id(existing: set[str]) -> str:
    for _ in range(64):
        candidate = "case-" + uuid.uuid4().hex[:8]
        if candidate not in existing:
            return candidate
    raise OverseerError("could not reserve a successor case id")


def _prepare_manifest(
    home: Path,
    stage: Path,
    *,
    run_id: str,
    started: str,
    model: str,
    selected: tuple[str, ...],
    population_count: int,
    excluded: int,
    model_calls: int,
    guard: int,
    coverage_text: str,
    questions: dict[str, Any],
    findings: list[dict[str, Any]],
    prepared: list[tuple[Path | None, Path, batch.Sheet]],
    model_updates: list[dict[str, Any]] | tuple[()] = (),
) -> dict[str, Any]:
    existing = {row["case"] for row in cases.list_cases(home, only_ok=True)}
    recipes: dict[str, Any] = {}
    order: list[str] = []
    for case_file, sheet_file, loaded in prepared:
        if case_file is None:
            continue
        case_id = _reserved_case_id(existing | set(recipes))
        case_data = _yaml_mapping(case_file)
        case_data["run_id"] = run_id
        case_text = _yaml_text(case_data)
        sheet_data = _yaml_mapping(sheet_file)
        sheet_data["case"] = case_id
        for item in sheet_data.get("items") or []:
            if item.get("verb") == "defer" and item.get("until") is None:
                item["until"] = (
                    datetime.now(timezone.utc) + timedelta(days=DEFAULT_DEFER_DAYS)
                ).date().isoformat()
        sheet_text = _yaml_text(sheet_data)
        effective_path = stage / f"effective-{sheet_file.name}"
        _write_stage(stage, effective_path, sheet_text)
        effective = batch.load_sheet(effective_path)
        assert effective.sheet_sha is not None and effective.sheet_digest is not None
        recipes[case_id] = {
            "case_name": case_file.name,
            "case_text": case_text,
            "sheet_name": sheet_file.name,
            "sheet": sheet_text,
            "sheet_sha": effective.sheet_sha,
            "sheet_digest": effective.sheet_digest,
            "items": [
                {
                    "n": item.n,
                    "id": item.id,
                    "verb": item.verb,
                    "close_call": bool(getattr(loaded, "close_calls", {}).get(item.n, False)),
                }
                for item in effective
            ],
            "maintenance": [],
            "dispositions": [],
        }
        order.append(case_id)
    manifest: dict[str, Any] = {
        "version": 1,
        "run_id": run_id,
        "actor": "overseer",
        "status": "unfinished",
        "outcome": None,
        "start_head": gitops.head_sha(home),
        "started": started,
        "date": started[:10],
        # 02-schema §3a, the attempt-counting fields. This record is opened
        # by the attempt that produced it, so its count starts at 1: every
        # earlier attempt of the same week failed before this point and left
        # a committed failure note instead (see `week_attempts`).
        "week": week_key(week_boundary(time.time())),
        "attempt_count": 1,
        "last_attempt_at": started,
        "progress_at": None,
        "failure": None,
        "failure_detail": None,
        "model": model,
        "selected": list(selected),
        "population_count": population_count,
        "excluded": excluded,
        "model_calls": model_calls,
        "guard": guard,
        "coverage": coverage_text,
        "inputs": [],
        "reconsider_observations": [],
        "report": (stage / "report.md").read_text(encoding="utf-8"),
        "questions": questions,
        "findings": findings,
        "case_order": order,
        "cases": recipes,
        "ledger_effects": [],
        "remaining": order,
        "maintenance": [
            _model_operation(payload, ordinal=index)
            for index, payload in enumerate(model_updates, start=1)
        ],
    }
    _scan_manifest_or_refuse(manifest)
    return manifest


def _publish_manifest(
    home: Path, intent: intents.Intent, manifest: dict[str, Any], coverage_path: Path
) -> Path:
    path = execution_evidence.manifest_path(home, cast(str, manifest["run_id"]))
    intents.add_step(intent, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, _manifest_text(manifest), fsync=True)
    intents.complete(intent)
    gitops.stage_and_commit(
        home, [coverage_path, path], intent.commit_subject, None
    )
    intents.finish(intent)
    return path


_RECEIPT_RESULT_RE = re.compile(
    r"sheet=\S*#(?P<sha>[0-9a-f]{6,64}) item=(?P<n>\d+) "
    r"(?P<id>lrn-[0-9a-f]{8}) (?P<verb>[a-z][a-z0-9-]*) → "
    r"(?P<state>applied|already-applied|refused|stopped) \(exit (?P<rc>-?\d+)\)"
)


def _receipt_results(
    home: Path, case_id: str, recipe: dict[str, Any]
) -> dict[int, batch.ItemResult]:
    try:
        application = cases.show(home, case_id, evidence_only=False).sections["Application"]
    except cases.CaseError:
        return {}
    expected = {int(row["n"]): row for row in recipe["items"]}
    results: dict[int, batch.ItemResult] = {}
    for line in application.splitlines():
        match = _RECEIPT_RESULT_RE.search(line)
        if match is None or match.group("sha") != recipe["sheet_sha"]:
            continue
        n = int(match.group("n"))
        row = expected.get(n)
        if row is None or row["id"] != match.group("id") or row["verb"] != match.group("verb"):
            raise OverseerError(f"committed receipt identity mismatch for {case_id} item {n}")
        results[n] = batch.ItemResult(
            n=n, id=row["id"], verb=row["verb"], rc=int(match.group("rc")),
            state=match.group("state"),
        )
    return results


def _receipt_completed(
    home: Path, case_id: str, recipe: dict[str, Any]
) -> dict[int, batch.ItemResult]:
    return {
        n: item for n, item in _receipt_results(home, case_id, recipe).items()
        if item.state in ("applied", "already-applied") and item.rc == 0
    }


def _manifest_introduction(home: Path, run_id: str) -> str:
    relpath = execution_evidence.manifest_path(home, run_id).relative_to(home.resolve())
    commits = gitops._git(  # noqa: SLF001 -- first committed recipe boundary
        home, "log", "--diff-filter=A", "--format=%H", "--reverse", "--", str(relpath)
    ).stdout.splitlines()
    if not commits:
        raise OverseerError(f"unfinished run {run_id} has no committed prepared boundary")
    return commits[0]


def _record_at_commit(
    home: Path, sha: str, record_id: str
) -> tuple[Path, Record] | None:
    paths = gitops._git(  # noqa: SLF001 -- immutable candidate content
        home, "ls-tree", "-r", "--name-only", sha, "--", "skills"
    ).stdout.splitlines()
    matches = [path for path in paths if Path(path).name == f"{record_id}.md"]
    if len(matches) != 1:
        return None
    text = gitops._git(home, "show", f"{sha}:{matches[0]}").stdout  # noqa: SLF001
    try:
        return Path(matches[0]), Record.from_text(text)
    except Exception:
        return None


def _candidate_establishes(
    home: Path, committed: tuple[Path, Record] | None, item: dict[str, Any]
) -> bool:
    if committed is None:
        return item["verb"] in {"supersede", "rehome", "rescope"}
    path, record = committed
    verb = item["verb"]
    if verb == "route":
        routing = record.routing or {}
        return record.status == "routed" and (
            item.get("dest") is None
            or routing.get("destination") == item.get("dest")
        )
    if verb == "reject":
        return record.status == "rejected"
    if verb == "defer":
        return record.status == "deferred" and str(record.deferred_until) == str(
            item.get("until")
        )
    if verb in {"undefer", "reopen"}:
        return record.status == "pending"
    if verb == "retire":
        return (
            record.status == "superseded"
            and record.superseded_by == build_covered_by(cast(str, item["covered_by"]))
        )
    if verb == _LEGACY_RETIRE_ALIAS:
        covered_by = item.get("covered_by")
        expected = "canon" if covered_by is None else build_covered_by(cast(str, covered_by))
        return record.status == "superseded" and record.superseded_by == expected
    if verb == "supersede":
        return (
            record.status == "superseded"
            and record.superseded_by == item.get("new_id")
        )
    if verb == "revise":
        return cast(str, item.get("text") or "") in record.body
    if verb == "note":
        key = item.get("key")
        return key is not None and record.note_has_key(cast(str, key))
    if verb == "confirm-held":
        return record.last_confirmed is not None
    if verb == "confirm-recurrence":
        return any(row.get("ref") == item.get("event") for row in record.recurrences)
    if verb == "dismiss-suspect":
        return any(row.get("ref") == item.get("event") for row in record.dismissed_suspects)
    if verb == "link-contradicts":
        return item.get("target") in record.contradicts
    if verb == "followup-done":
        return record.follow_up is None and record.follow_up_done is not None
    if verb in {"rehome", "rescope"}:
        try:
            _scope, bucket, _project = verbs._resolve_move_target(
                home, cast(str, item["to"])
            )
        except verbs.VerbError:
            return False
        return path.parent.parent == bucket.relative_to(home)
    return False


def _mutation_proven_completed(
    home: Path,
    manifest: dict[str, Any],
    case_id: str,
    recipe: dict[str, Any],
    existing: dict[int, batch.ItemResult],
) -> dict[int, batch.ItemResult]:
    """Recover unreceipted committed ledger effects without replaying them."""
    completed = dict(existing)
    after = _manifest_introduction(home, cast(str, manifest["run_id"]))
    for row in recipe["items"]:
        n = int(row["n"])
        if n in completed:
            continue
        ref = execution_evidence.ExecutionRef(
            run_id=manifest["run_id"], case_id=case_id,
            sheet_sha=recipe["sheet_sha"], sheet_digest=recipe["sheet_digest"],
            item=n, record_id=row["id"], verb=row["verb"], actor="overseer",
        )
        fields = YAML(typ="safe").load(recipe["sheet"])["items"][n - 1]
        if fields.get("collapse"):
            sha = execution_evidence.find_compound_proof_commit(
                home, ref, after=after
            )
        else:
            sha = execution_evidence.find_mutation_commit(home, ref, after=after)
        if sha is None:
            continue
        # The canonical trailer/compound lookup is necessary but not enough:
        # require the candidate to have changed this record and require the
        # current ledger to classify the exact original item as established.
        changed = gitops._git(  # noqa: SLF001 -- candidate content verification
            home, "diff-tree", "--no-commit-id", "--name-only", "-r", sha
        ).stdout.splitlines()
        if not any(row["id"] in path for path in changed):
            raise OverseerError(
                f"mutation proof {sha[:8]} did not change {row['id']}"
            )
        if not _candidate_establishes(
            home, _record_at_commit(home, sha, row["id"]), fields
        ):
            raise OverseerError(
                f"mutation proof {sha[:8]} does not establish original item {n}"
            )
        evidence = "ledger mutation verified against original item"
        if row["verb"] in batch._HOST_OUTCOME_VERBS:  # noqa: SLF001 -- shared executor contract
            recomp = verbs.recompile(home, no_push=True)
            refused = [
                f"{entry.target}: {entry.skipped}"
                for entry in recomp.entries if entry.skipped
            ]
            if refused:
                completed[n] = batch.ItemResult(
                    n=n, id=row["id"], verb=row["verb"], rc=1,
                    state="unresolved-host", detail="; ".join(refused),
                )
                continue
            evidence = "host result established by recompile"
        completed[n] = batch.ItemResult(
            n=n, id=row["id"], verb=row["verb"], rc=0, sha=sha,
            state="applied", evidence=evidence,
        )
    return completed


def _observation_id(run_id: str, index: int) -> str:
    return "obs-" + hashlib.sha256(f"{run_id}:{index}".encode()).hexdigest()[:8]


#: The run-record fields the finalize write OWNS (A17). Everything else on
#: the record is whatever HEAD already says, so the publish can never carry
#: a stale in-memory copy back over committed truth.
_FINALIZE_OWNED_FIELDS = (
    "cases", "remaining", "attempt_count", "last_attempt_at", "progress_at",
    "failure", "failure_detail", "halt_code", "week", "outcome",
)


def _finalized_record(
    home: Path, manifest: dict[str, Any], *, status_name: str
) -> dict[str, Any]:
    """A17: re-read the run record from HEAD and change NAMED fields, the
    way the steward's `_update_manifest` does, instead of publishing the
    in-memory copy wholesale.

    The old write republished everything this process happened to hold and
    guarded exactly one key (`ledger_effects`) by re-reading the WORKTREE
    copy, swallowing read errors. It is the same family as the steward's
    stale re-save (A2): one missing key away from erasing committed proof.
    """
    try:
        current = execution_evidence.read_manifest(
            home, cast(str, manifest["run_id"]), at="HEAD"
        )
    except (execution_evidence.ExecutionEvidenceError, gitops.GitOpsError):
        # No committed boundary yet: the in-memory copy IS the only truth.
        current = dict(manifest)
    for field in _FINALIZE_OWNED_FIELDS:
        if field in manifest:
            current[field] = manifest[field]
    current["status"] = status_name
    return current


def _write_manifest_truth(
    home: Path,
    manifest: dict[str, Any],
    *,
    report_text: str,
    complete: bool,
    closed: bool = False,
    week: str | None = None,
    closed_text: str | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    path = execution_evidence.manifest_path(home, manifest["run_id"])
    record = _finalized_record(
        home, manifest,
        status_name="closed" if closed else ("complete" if complete else "unfinished"),
    )
    report_path = _dated_report_path(
        home, cast(str, manifest["date"]), cast(str, manifest["run_id"])
    )
    latest = home / "overseer" / "latest-report.md"
    questions_path = home / "overseer" / "open-questions.yaml"
    paths = [path, report_path, latest]
    if complete:
        paths.append(questions_path)
    closed_note = (
        failures_dir(home, week) / "closed.md"
        if closed_text is not None and week is not None
        else None
    )
    if closed_note is not None:
        paths.append(closed_note)
    with intents.ledger_write(home):
        intent = intents.begin(
            home, "overseer-run-finalize", paths,
            f"self-learn: overseer finalize {manifest['run_id']}",
        )
        for target in paths:
            intents.add_step(intent, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(path, _manifest_text(record), fsync=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(report_path, report_text, fsync=True)
        fsops.atomic_write(latest, report_text, fsync=True)
        if closed_note is not None and closed_text is not None:
            closed_note.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(closed_note, closed_text, fsync=True)
        if complete:
            # A14: only a COMPLETED run publishes questions. No failure path
            # reaches this write, so a failed attempt can never blank last
            # week's open questions.
            fsops.atomic_write(
                questions_path, _yaml_text(record["questions"]), fsync=True
            )
        intents.complete(intent)
        gitops.stage_and_commit(home, paths, intent.commit_subject, None)
        intents.finish(intent)
    return record, report_path, latest


def _run_manifest_sheet(
    home: Path,
    stage: Path,
    manifest: dict[str, Any],
    case_id: str,
    recipe: dict[str, Any],
    *,
    gate: bool,
) -> tuple[batch.BatchResult, dict | None, batch.Sheet]:
    case_path = stage / cast(str, recipe["case_name"])
    sheet_path = stage / f"effective-{recipe['sheet_name']}"
    _write_stage(stage, case_path, cast(str, recipe["case_text"]))
    _write_stage(stage, sheet_path, cast(str, recipe["sheet"]))
    successor = cases.record(
        home, case_path, actor="overseer", reserved_id=case_id
    )
    if successor != case_id:
        raise OverseerError(
            f"reserved successor {case_id} returned unexpected id {successor}"
        )
    effective = batch.load_sheet(sheet_path, home=home)
    if (
        effective.sheet_sha != recipe["sheet_sha"]
        or effective.sheet_digest != recipe["sheet_digest"]
    ):
        raise OverseerError(f"committed sheet identity changed for {case_id}")
    receipted = _receipt_results(home, case_id, recipe)
    # A4 (S-68 ruling 1). Retryability follows the failure's KIND, never the
    # word the receipt happens to carry:
    #
    #   * a receipted `refused` item is a judgment on the merits and is
    #     FINAL — it is never dispatched again (in particular, never retry
    #     U5's refused reference reconsideration);
    #   * a receipted `stopped` item is a stop code 5/6/7, which `batch.py`
    #     itself calls "a pre-mutation ledger-level failure — nothing
    #     written, safe to retry", and the never-attempted tail of the sheet
    #     was never dispatched at all. Both are left OUT of
    #     `continuation.completed`, so `batch.run` re-classifies and
    #     re-dispatches them; S-54's guarantee (a second run of an applied
    #     sheet applies 0 items) is what makes that safe.
    #
    # Before this, `stopped` sat beside `refused` here, so ONE transient
    # exit 6 left the item never retried and the run never finished — the
    # stall reproduced on a scratch ledger 2026-09-19.
    refused_final = {
        n: item for n, item in receipted.items() if item.state == "refused"
    }
    completed = _receipt_completed(home, case_id, recipe)
    completed = _mutation_proven_completed(
        home, manifest, case_id, recipe, completed
    )
    expected = {int(row["n"]) for row in recipe["items"]}
    if refused_final:
        # A committed refusal is the durable disposition, so no ledger leg
        # of this sheet is attempted again. That necessarily freezes what
        # sits behind it: `batch._validate_continuation` accepts only "a
        # proven completion" or "a named unresolved host obligation" in
        # `continuation.completed`, so a refused item cannot be carried
        # past, and driving the sheet again would re-dispatch the refusal.
        # Items the refusal left undispatched therefore stay "not
        # attempted" — named here rather than dropped, so A12's
        # expected-key check below keeps the run unfinished and S-68's
        # attempt cap turns a sheet nobody can finish into a question put
        # to the user instead of a silent loss.
        rows = {int(row["n"]): row for row in recipe["items"]}
        items = [receipted[n] for n in sorted(receipted)]
        items.extend(
            batch.ItemResult(
                n=n, id=cast(str, rows[n]["id"]), verb=cast(str, rows[n]["verb"]),
                rc=-1, state="not-attempted",
            )
            for n in sorted(expected - set(receipted))
        )
        result = batch.BatchResult(
            items=items,
            process_code=max(item.rc for item in refused_final.values()),
            case=case_id, sheet_sha=effective.sheet_sha, actor="overseer",
        )
        return result, {"state": "preserved", "pushed": None}, effective
    continuation = batch.BatchContinuation(
        run_id=cast(str, manifest["run_id"]), case_id=case_id,
        sheet_digest=cast(str, recipe["sheet_digest"]), completed=completed,
    )

    def checkpoint(partial: batch.BatchResult) -> dict | None:
        return batch.write_receipt(
            home, partial, cast(str, recipe["sheet_name"]),
            no_push=True, prefix=True,
        )

    try:
        result = batch.run(
            home, effective, no_push=True, actor="overseer",
            hook_activation=gate, continuation=continuation,
            checkpoint=checkpoint,
        )
        receipt = batch.write_receipt(
            home, result, cast(str, recipe["sheet_name"]),
            no_push=True, prefix=True,
        )
    except batch.BookkeepingHalt as exc:
        result = exc.result
        receipt = batch.write_receipt(
            home, result, cast(str, recipe["sheet_name"]),
            no_push=True, prefix=True,
        )
        raise batch.BookkeepingHalt(str(exc), result, exc.untouched_tail) from None
    return result, receipt, effective


def _always_loaded_user_scope(home: Path, record_id: str) -> bool:
    try:
        record = Record.from_path(find_record_path(home, record_id))
    except (LedgerOpsError, OSError, ValueError):
        return False
    if record.scope != "user":
        return False
    routing = record.routing or {}
    if routing.get("destination") == "claude-md":
        return True
    covered = record.superseded_by or ""
    return covered.startswith("covered_by:claude-md:") or covered.startswith(
        "covered_by:output-style:"
    )


def _execute_manifest(
    home: Path,
    manifest: dict[str, Any],
    *,
    boundary_no_push: bool,
) -> RunResult:
    """Resume one committed recipe and finalize only after every sheet."""
    run_id = cast(str, manifest["run_id"])
    selected = tuple(cast(list[str], manifest.get("selected") or []))
    excluded = int(manifest.get("excluded") or 0)
    model_calls = int(manifest.get("model_calls") or 0)
    stage = worker.stage_dir() / "overseer"
    worker.stage_reset(home)
    stage.mkdir(parents=True, exist_ok=True)
    _write_stage(stage, stage / "report.md", cast(str, manifest["report"]))
    recipes = cast(dict[str, dict[str, Any]], manifest["cases"])
    order = cast(list[str], manifest["case_order"])
    codes: list[int] = []
    refusals: list[str] = []
    hook_lines: list[str] = []
    user_model_lines: list[str] = []
    cue_outcomes: list[dict[str, Any]] = []
    hook_ids: list[str] = []
    notice_ids: list[str] = []
    application_count = 0
    halted = False
    halt_reason: str | None = None
    gate = config.hook_activation_enabled(home)
    # S-68. The PROGRESS reading is taken from the record as it stands at
    # HEAD at the START of this attempt; the count is committed evidence and
    # was already incremented by the caller, so a resume-time exception that
    # recurs identically still walks the cap up to the close-out.
    before = _progress_signature(manifest)
    week = _manifest_week(manifest) or week_key(week_boundary(time.time()))
    cap = attempt_cap(home)
    attempts = week_attempts(home, week)

    for position, case_id in enumerate(order):
        recipe = recipes[case_id]
        try:
            result, receipt, effective = _run_manifest_sheet(
                home, stage, manifest, case_id, recipe, gate=gate
            )
        except batch.BookkeepingHalt as exc:
            result = exc.result
            receipt = {"state": "halted", "reason": str(exc)}
            effective_path = stage / f"effective-{recipe['sheet_name']}"
            effective = batch.load_sheet(effective_path, home=home)
            halted = True
            halt_reason = str(exc)
        except Exception as exc:
            halted = True
            halt_reason = f"run ended early: {exc}"
            manifest["remaining"] = order[position:]
            break
        codes.append(result.process_code)
        recipe["dispositions"] = [
            {
                "n": item.n,
                "state": item.state,
                **({"detail": item.detail} if item.detail else {}),
            }
            for item in result.items
        ]
        application_count += result.summary.get("applied", 0)
        for item in result.items:
            if item.state in ("refused", "stopped", "unresolved-host") and item.detail:
                refusals.append(item.detail)
        by_n = {item.n: item for item in result.items}
        for sheet_item in effective:
            item_result = by_n.get(sheet_item.n)
            recipe_item = next(
                (row for row in recipe["items"] if row["n"] == sheet_item.n),
                {},
            )
            if item_result is not None and item_result.state in {"applied", "already-applied"}:
                notice_ids.append(item_result.id)
                hook_activated = bool(
                    gate
                    and sheet_item.verb == "route"
                    and sheet_item.fields.get("dest") == "hook"
                )
                if hook_activated:
                    hook_ids.append(item_result.id)
                cue_outcomes.append(
                    {
                        "verb": sheet_item.verb,
                        "hook_activated": hook_activated,
                        "always_loaded_user_scope": bool(
                            sheet_item.verb
                            in {"route", "retire", "supersede", _LEGACY_RETIRE_ALIAS}
                            and _always_loaded_user_scope(home, item_result.id)
                        ),
                        "close_call": bool(recipe_item.get("close_call")),
                    }
                )
            if sheet_item.verb == "route" and sheet_item.fields.get("dest") == "hook":
                if item_result is not None:
                    detail = item_result.detail or item_result.state
                    if detail.startswith(f"{item_result.id}:"):
                        # O-2b's activation message already leads with the id.
                        hook_lines.append(detail)
                    else:
                        hook_lines.append(f"{item_result.id}: {detail}")
        _journal(home, {
            "at": chrono.now_iso(), "run": run_id, "status": "sheet",
            "sheet": recipe["sheet_name"], "sheet_sha": result.sheet_sha,
            "stopped": result.summary["stopped"], "code": result.process_code,
            "receipt": receipt, "items": result.to_json()["items"],
        })
        terminal = (
            result.stop_message is not None
            or result.stopped_at is not None
            or result.process_code in (5, 6, 7, 8)
        )
        if terminal:
            halted = True
            halt_reason = halt_reason or result.stop_message or (
                f"sheet {recipe['sheet_name']} stopped with exit {result.process_code}"
            )
        # A12: completion is checked against every expected original
        # `(sheet_sha, item)` key (02-schema §3a: "A partially receipted
        # sheet ... remains unfinished"), never against "the batch did not
        # halt". A sheet whose later items were never dispatched now stays
        # unfinished and names them, instead of being stamped complete over
        # a tail nobody will ever apply and nobody was ever told about.
        unattempted = sorted(
            {int(row["n"]) for row in recipe["items"]}
            - {item.n for item in result.items if item.state != "not-attempted"}
        )
        if unattempted:
            missing = ", ".join(str(n) for n in unattempted)
            halted = True
            halt_reason = halt_reason or (
                f"{recipe['sheet_name']}: item(s) {missing} not attempted"
            )
            refusals.append(f"{recipe['sheet_name']}: item(s) {missing} not attempted")
        if halted:
            manifest["remaining"] = order[position:]
            break
        manifest["remaining"] = order[position + 1:]

    if not halted:
        _new_applied, _new_refused, maintenance_halted, _new_lines = (
            _maintain_manifest(home, run_id)
        )
        if maintenance_halted:
            halted = True
            halt_reason = "user-model maintenance stopped by a ledger intent"
            manifest["remaining"] = ["user-model maintenance"]
        refreshed = execution_evidence.read_manifest(home, run_id, at="HEAD")
        refreshed["cases"] = manifest["cases"]
        refreshed["remaining"] = manifest["remaining"]
        manifest = refreshed
        maintenance = cast(list[dict[str, Any]], manifest.get("maintenance") or [])
        application_count += sum(row.get("state") == "applied" for row in maintenance)
        maintenance_refused = sum(row.get("state") == "refused" for row in maintenance)
        user_model_lines = []
        for row in maintenance:
            result = row.get("result") or {}
            action = row.get("payload", {}).get("action", "add")
            if row.get("state") == "applied":
                user_model_lines.append(f"{result.get('id')}: {action} applied")
            elif row.get("state") == "refused":
                user_model_lines.append(
                    f"{row.get('id')}: refused — {result.get('error', 'unknown refusal')}"
                )
        if maintenance_refused:
            codes.append(EXIT_REFUSED)
            refusals.extend(line for line in user_model_lines if "refused" in line)

    if not halted:
        try:
            for index, finding in enumerate(cast(list[dict[str, Any]], manifest["findings"]), start=1):
                cases.observe(
                    home, cast(str, finding["case"]), cast(str, finding["kind"]),
                    text=cast(str, finding.get("text") or "examined"), by="overseer",
                    ref=finding.get("ref"), reserved_id=_observation_id(run_id, index),
                )
        except Exception as exc:
            halted = True
            halt_reason = f"run ended early: {exc}"
            manifest["remaining"] = ["observations/questions/report finalization"]

    item_code = _worst_code(codes, any_applied=application_count > 0)
    decision = item_code
    if halted:
        decision = EXIT_PARTIAL
        remaining = ", ".join(cast(list[str], manifest.get("remaining") or []))
        reason = halt_reason or "committed work remains unfinished"
        refusals.append(
            f"{reason}; remaining committed obligation(s): {remaining or 'finalization'}"
        )
        status_name = "partial"
    else:
        status_name = "partial" if decision == EXIT_PARTIAL else (
            "refused" if decision else "applied"
        )

    # S-68's generic guard. An attempt that ran and moved NOTHING toward a
    # terminal value is a failed attempt and counts exactly like one that
    # raised, so a trap nobody has thought of still closes out after
    # `runs.attempt_cap` instead of spinning for ever, one commit a run.
    progressed = _made_progress(before, _progress_signature(manifest))
    if progressed:
        manifest["progress_at"] = chrono.now_iso()
    if halted:
        # 02-schema §3a's CLOSED set for `failure`, and nothing else: the
        # literals the runner already writes, plus `no-progress`. A ledger
        # stop is not one of them — it "keeps riding the run record's own
        # numeric halt code (5, 6, 7, 8); a code is never folded into this
        # field" — so the code goes in `halt_code` and `failure` stays null
        # for a halt that DID move something. An earlier draft invented
        # `halted` here, which is a second vocabulary §3a forbids.
        manifest["halt_code"] = item_code if item_code in _LEDGER_HALT_CODES else None
        manifest["failure_detail"] = _failure_detail(
            f"{_NO_PROGRESS_DETAIL}; last reason: {halt_reason}"
            if halt_reason and not progressed
            else (halt_reason or _NO_PROGRESS_DETAIL)
        )
        manifest["failure"] = None if progressed else "no-progress"

    # Ruling 2. At the cap the run CLOSES — so the next week's run can
    # start — each stuck item becomes a question put to the user in the
    # report, and one notification fires. The count is committed evidence,
    # taken at the start of this attempt, so an exception that recurs
    # identically on every two-hour resume still gets here.
    closed = False
    questions: list[str] = []
    closed_text: str | None = None
    if halted and attempts >= cap:
        closed = True
        unfinished_units = list(cast(list[str], manifest.get("remaining") or []))
        for recipe in recipes.values():
            settled = {
                int(row["n"]) for row in recipe.get("dispositions") or []
                if isinstance(row, dict) and row.get("state") in _TERMINAL_ITEM_STATES
            }
            unfinished_units.extend(
                f"{recipe['sheet_name']} item {row['n']} ({row['verb']} {row['id']})"
                for row in recipe.get("items") or []
                if int(row["n"]) not in settled
            )
        kind = _failure_kind_text(manifest)
        detail = manifest.get("failure_detail")
        questions = _close_out_questions(
            week=week, attempts=attempts, kind=kind,
            detail=cast(str | None, detail), unfinished=unfinished_units,
            applied=application_count,
        )
        closed_text = _closed_note_text(
            week=week, attempts=attempts, kind=kind,
            detail=cast(str | None, detail), unfinished=unfinished_units,
            applied=application_count,
        )
        manifest["outcome"] = "attempts-exhausted"
        status_name = "closed"
        # FW-85's producer space, the same rule the steward already follows
        # for a run that abandoned units: `1` when nothing of this run
        # landed ("refused, nothing written"), `8` (`EXIT_BATCH_PARTIAL`,
        # "the ledger DID change") when something did. Both close-out paths
        # go through this rule, so they cannot drift apart.
        decision = EXIT_PARTIAL if application_count else EXIT_REFUSED
        _journal(home, {
            "at": chrono.now_iso(), "run": run_id, "status": "week-closed",
            "week": week, "attempts": attempts, "failure": kind,
            "applied": application_count,
        })
    try:
        text = _finalize_model_report(
            stage / "report.md", date=cast(str, manifest["date"]), run_id=run_id,
            model=cast(str, manifest["model"]), selected=selected,
            population_count=int(manifest.get("population_count") or 0),
            excluded=excluded, model_calls=model_calls,
            guard=int(manifest.get("guard") or 0), refusals=refusals,
            hooks=hook_lines,
            user_model_lines=user_model_lines,
            questions=questions,
        )
        manifest, report_path, latest = _write_manifest_truth(
            home, manifest, report_text=text, complete=not halted, closed=closed,
            week=week, closed_text=closed_text,
        )
        if closed:
            _notify_week_closed(home, week, attempts, _failure_kind_text(manifest), [run_id])
        if not halted:
            completed_at = status(home).get("last_run_at") or chrono.now_iso()
            _write_last_run_marker(home, cast(str, completed_at))
    except Exception as exc:
        # The committed recipe is the restart point after any late failure.
        # Never let report/finalization bookkeeping turn already-landed
        # ledger decisions into an escaping exception or a false refusal.
        halted = True
        decision = EXIT_PARTIAL
        status_name = "partial"
        reason = f"run ended early: {exc}"
        manifest["remaining"] = list(manifest.get("remaining") or []) + [
            "observations/questions/report finalization"
        ]
        partial_text = _report_text(
            date=cast(str, manifest["date"]), run_id=run_id,
            model=cast(str, manifest["model"]), selected=selected,
            population_count=int(manifest.get("population_count") or 0),
            excluded=excluded, model_calls=model_calls,
            guard=int(manifest.get("guard") or 0),
            parked_decided=application_count, refused=refusals,
            hooks=hook_lines, reason=reason,
            user_model_lines=user_model_lines, questions=questions,
        )
        try:
            manifest, report_path, latest = _write_manifest_truth(
                home, manifest, report_text=partial_text, complete=False,
                closed=closed, week=week, closed_text=closed_text,
            )
            if closed:
                _notify_week_closed(
                    home, week, attempts, _failure_kind_text(manifest), [run_id],
                )
        except Exception as handler_exc:
            _journal(home, {
                "at": chrono.now_iso(), "run": run_id,
                "status": "partial-handler-error",
                "reason": str(handler_exc)[:300],
            })
            _journal(home, {
                "at": chrono.now_iso(), "run": run_id,
                "status": "partial", "reason": reason[:300],
            })
            return RunResult(
                "partial", EXIT_PARTIAL, run_id, model_calls, selected,
                excluded, application_count, len(refusals), None,
            )

    push_failure: str | None = None
    if not boundary_no_push:
        push = verbs.push_pending(home)
        if not push.ok:
            decision = push.exit_code
            push_failure = f"push: failed ({push.exit_code})"
            try:
                _record_push_failure(home, report_path, latest, push_failure)
            except Exception as exc:
                status_name = "partial"
                _journal(home, {
                    "at": chrono.now_iso(), "run": run_id,
                    "status": "push-report-error", "reason": str(exc)[:300],
                })
    threshold, _source = settings.resolve_setting(
        home, settings.by_name("overseer.broad_removal_threshold")
    )
    cue = notify.classify(
        cue_outcomes, broad_removal_threshold=cast(int, threshold)
    )
    if not closed:
        # Ruling 2: at the cap "the user is notified" — once. A closing run
        # has already sent the close-out notification, which says strictly
        # more than the ordinary per-run cue would; sending both is two
        # notifications for one event.
        notify.send(
            home,
            cue,
            f"overseer {status_name}: {len(selected)} examined",
            list(dict.fromkeys([*hook_ids, *notice_ids])) or [run_id],
        )
    journal_entry: dict[str, Any] = {
        "at": chrono.now_iso(), "run": run_id, "status": status_name,
        "code": decision, "model_calls": model_calls,
    }
    if push_failure is not None:
        journal_entry["push"] = push_failure
    _journal(home, journal_entry)
    return RunResult(
        status_name, decision, run_id, model_calls, selected, excluded,
        application_count, len(refusals), str(report_path),
    )


def run(home: Path | str | None = None, *, dry_run: bool = False, no_push: bool | None = None) -> RunResult:
    home = Path(home) if home is not None else resolve_home()
    run_id = uuid.uuid4().hex[:8]
    started = chrono.now_iso()
    recovered = intents.recover(home)
    if recovered.stopped:
        _journal(home, {"at": started, "run": run_id, "status": "stopped", "reason": "; ".join(recovered.stopped)[:300]})
        return RunResult("stopped", EXIT_STOPPED, run_id)

    boundary_no_push = worker.no_push_requested() if no_push is None else no_push
    enabled, _enabled_source = settings.resolve_setting(home, settings.by_name("overseer.enabled"))
    if not enabled and not dry_run:
        _journal(home, {"at": started, "run": run_id, "status": "disabled"})
        return RunResult("disabled", EXIT_OK, run_id)
    if not dry_run:
        # B10 (S-68, `13-hosting-and-separation.md` §5): the same-week
        # guard lives HERE, in the runner, not in the scheduler — so the
        # `serve` job, a hand-typed `overseer run`, and the systemd timer
        # (if a human ever enables it) cannot between them run one week
        # twice. Committed unfinished work is still due regardless of the
        # calendar, so it is checked first.
        #
        # A19: deciding ownership reads git, and a raise here would leave
        # no journal line at all — so the cooldown would never arm and the
        # job would be re-entered on the next tick. The attempt is
        # recorded before the exception leaves.
        try:
            boundary = week_boundary(time.time())
            week = week_key(boundary)
            cap = attempt_cap(home)
            unfinished = _unfinished_manifest(home)
            attempts_before = week_attempts(home, week)
            pending_close_out = (
                unfinished is None
                and attempts_before >= cap
                and not week_closed(home, week)
            )
            held = unfinished is None and not pending_close_out and week_done(
                home, boundary
            )
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised unchanged
            _journal(home, {
                "at": chrono.now_iso(), "run": run_id, "status": "attempt-start",
                "reason": f"ownership check failed: {exc}"[:300],
            })
            raise
        if pending_close_out:
            # The close-out is checked BEFORE `held`, and deliberately so:
            # a week at the cap makes `week_done` true, so a close-out whose
            # write failed (or a process killed between the cap and the
            # write) would otherwise be held for ever with its question
            # never written — the exact shape S-68 exists to end, one level
            # up. It counts nothing of its own and is idempotent.
            return _close_out_pending_week(
                home, run_id=run_id, week=week, attempts=attempts_before, cap=cap,
            )
        if held:
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "held-week-done"})
            return RunResult("held-week-done", EXIT_OK, run_id)
        if unfinished is not None:
            # 02-schema §3a: `attempt_count` increments ONCE at the START of
            # every attempt, committed BEFORE anything that can fail, "so an
            # attempt that makes zero calls, raises, or is killed still
            # counts". A resume-time exception that recurs identically every
            # two hours therefore reaches the cap on its own.
            _journal(home, {
                "at": chrono.now_iso(), "run": run_id,
                "status": "attempt-start", "resume": str(unfinished.get("run_id") or ""),
            })
            resume_id = cast(str, unfinished["run_id"])
            resume_week = _manifest_week(unfinished) or week
            unfinished = _update_manifest(
                home, resume_id,
                reason=f"attempt {_record_attempts(unfinished) + 1}",
                update=lambda current: current.update(
                    attempt_count=_record_attempts(current) + 1,
                    last_attempt_at=chrono.now_iso(),
                    week=current.get("week") or resume_week,
                ),
            )
            return _execute_manifest(
                home, unfinished, boundary_no_push=boundary_no_push
            )
        # A19: every attempt arms the cooldown, including one that then
        # makes zero model calls or raises. This is the first line the run
        # writes after it has taken ownership and before anything that can
        # fail; the first journal line used to be `population`, several
        # git and stage calls later.
        _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "attempt-start"})
    else:
        boundary = week_boundary(time.time())
        week = week_key(boundary)
        cap = attempt_cap(home)
        attempts_before = week_attempts(home, week)
    attempt = attempts_before + 1
    timeout, _ = settings.resolve_setting(home, settings.by_name("overseer.timeout_secs"))
    guard, _ = settings.resolve_setting(home, settings.by_name("overseer.max_model_calls"))
    model = provider.model_for("overseer", home=home)
    guard = cast(int, guard)
    timeout_seconds = cast(float, timeout)

    worker.stage_reset(home)
    stage = worker.stage_dir() / "overseer"
    stage.mkdir(parents=True, exist_ok=True)
    coverage_path = home / "overseer" / "coverage.yaml"
    previous = population_mod.load_coverage(coverage_path)
    since = previous.get("last_run_at") or chrono.now_iso(datetime.now(timezone.utc) - timedelta(days=7))
    all_week = cases.list_cases(home, since=since)
    week_rows = cases.list_cases(home, since=since, only_ok=True)
    excluded = sum(1 for row in all_week if not row.get("frozen_ok", True))
    blind = population_mod.population(home, since)
    offered = population_mod.nudges(home, previous, since)
    _write_stage(stage, stage / "population.txt", population_mod.render_population(blind) + f"{excluded} cases excluded: freeze hash mismatch\n")
    population_mod.write_blind_views(home, stage / "blind", blind)
    _write_stage(stage, stage / "nudges.yaml", _yaml_text({"nudges": offered}))
    prompt_a = _phase_a_prompt(stage, len(blind), excluded)
    _write_stage(stage, stage / "prompt-a.md", prompt_a)
    _journal(home, {"at": started, "run": run_id, "status": "population", "count": len(blind), "excluded": excluded})

    outcome_a = _invoke(home, stage, prompt_a, timeout_seconds, "phase-a", run_id)
    turns_a, turns_a_reported = _turns(outcome_a, guard)
    # A15: a failure of the FIRST model call leaves a committed trace with
    # its real reason. It happens before any `intents.begin` here, so the
    # note opens its own `intents.ledger_write` span. A dry run writes
    # none — a rehearsal must not suppress the real run behind it.
    if not outcome_a.ok:
        state = "timed-out" if outcome_a.failure == "timeout" else "refused"
        kind = outcome_a.failure or "invocation"
        detail = _failure_detail(outcome_a.detail)
        reason = f"phase A {state}; no phase A output was used"
        _commit_phase_a_failure(
            home, dry_run=dry_run, week=week, attempt=attempt, cap=cap,
            run_id=run_id, started=started, kind=kind, detail=detail,
            model=str(model), population_count=len(week_rows), excluded=excluded,
            model_calls=turns_a, guard=guard, reason=reason,
        )
        _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": state, "phase": "a", "reason": (detail or kind)[:300]})
        return RunResult(state, EXIT_REFUSED, run_id, turns_a, excluded=excluded)
    if turns_a >= guard:
        observed = (
            f"runaway guard reached after phase A at {turns_a} calls"
            if turns_a_reported
            else "phase A reported no turn count; the runaway guard fails closed"
        )
        reason = f"{observed}; phase B was not started"
        detail = _failure_detail(reason)
        published = _commit_phase_a_failure(
            home, dry_run=dry_run, week=week, attempt=attempt, cap=cap,
            run_id=run_id, started=started, kind="turns", detail=detail,
            model=str(model), population_count=len(week_rows), excluded=excluded,
            model_calls=turns_a, guard=guard, reason=reason,
        )
        report_path = published or _write_report_only(
            stage,
            _report_text(date=started[:10], run_id=run_id, model=str(model), selected=(), population_count=len(week_rows), excluded=excluded, model_calls=turns_a, guard=guard, reason=reason),
        )
        _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "runaway", "phase": "a", "turns": turns_a})
        return RunResult("runaway", EXIT_REFUSED, run_id, turns_a, excluded=excluded, report=str(report_path))

    try:
        selection = _yaml_mapping(stage / "selection.yaml")
        selected = _selected_ids(selection, {row["case"] for row in week_rows})
        _validate_initial(stage / "initial-views.yaml", selected)
    except (OverseerError, population_mod.CoverageError) as exc:
        detail = _failure_detail(exc)
        _commit_phase_a_failure(
            home, dry_run=dry_run, week=week, attempt=attempt, cap=cap,
            run_id=run_id, started=started, kind="schema-repair", detail=detail,
            model=str(model), population_count=len(week_rows), excluded=excluded,
            model_calls=turns_a, guard=guard, reason=str(exc),
        )
        _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "a-incomplete", "reason": str(exc)[:300]})
        return RunResult("refused", EXIT_REFUSED, run_id, turns_a, excluded=excluded)

    now_dt = datetime.now(timezone.utc)
    coverage = population_mod.coverage_update(previous, selection, week_rows, offered, now=now_dt)
    coverage_text = population_mod.render_coverage(coverage)
    coverage_before: bytes | None = None
    intent: intents.Intent | None = None
    lock_context = intents.ledger_write(home)
    with _DeferredNotice() as deferred_notice, lock_context:
        if not dry_run:
            coverage_before = coverage_path.read_bytes() if coverage_path.is_file() else None
            intent = intents.begin(home, "overseer-run", [coverage_path], f"self-learn: overseer run {started[:10]}")
            coverage_path.parent.mkdir(parents=True, exist_ok=True)
            fsops.atomic_write(coverage_path, coverage_text, fsync=True)
        # The staged copy is what dry runs expose.  The authoritative copy
        # above is deliberately present before parked intake on real runs.
        _write_stage(stage, stage / "coverage.yaml", coverage_text)

        # This read is deliberately after coverage was written.  It is the
        # whole verified parked queue; no count or prompt budget truncates it.
        parked_rows = [
            row for row in cases.list_cases(home, parked_for="overseer", only_ok=True)
            if not row.get("superseded_by")
        ]
        _full_inputs(home, stage, selected, parked_rows)
        prompt_b = _phase_b_prompt(stage, selected, tuple(row["case"] for row in parked_rows))
        _write_stage(stage, stage / "prompt-b.md", prompt_b)
        outcome_b = _invoke(home, stage, prompt_b, timeout_seconds, "phase-b", run_id)
        turns_b, turns_b_reported = _turns(outcome_b, guard)
        model_calls = turns_a + turns_b
        if not outcome_b.ok or model_calls >= guard:
            state = "runaway" if model_calls >= guard else ("timed-out" if outcome_b.failure == "timeout" else "refused")
            if state == "runaway":
                reason = (
                    f"runaway guard reached after phase B at {model_calls} calls"
                    if turns_b_reported
                    else "phase B reported no turn count; the runaway guard fails closed"
                ) + "; phase B output was not applied"
                kind = "turns"
            else:
                reason = f"phase B {state}; no phase B output was applied"
                kind = outcome_b.failure or "invocation"
            detail = _failure_detail(f"{reason} ({outcome_b.detail})" if outcome_b.detail else reason)
            closed_text, close_questions = (None, [])
            if not dry_run:
                closed_text, close_questions = _close_out_if_exhausted(
                    home, week=week, attempts=attempt, cap=cap, kind=kind, detail=detail,
                )
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, reason=reason, questions=close_questions)
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                report_path = _commit_failed_attempt(
                    home, intent, coverage_path=coverage_path,
                    coverage_before=coverage_before, report_text=text,
                    date=started[:10], run_id=run_id, week=week, started=started,
                    attempt=attempt, cap=cap, kind=kind, detail=detail,
                    closed_text=closed_text,
                )
                if closed_text is not None:
                    _queue_week_closed(deferred_notice, home, week, attempt, kind, [run_id])
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": state, "phase": "b", "turns": model_calls})
            return RunResult(state, EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        required = [
            stage / name for name in (
                "report.md", "findings.yaml", "questions.yaml", "user-model-delta.yaml"
            )
        ]
        missing = [path.name for path in required if not path.is_file()]
        pairs = _sheet_pairs(stage)
        if not pairs:
            missing.append("sheet.yaml")
        secret_files = _secret_files(stage)

        if not missing and not secret_files:
            try:
                _validate_model_report(stage / "report.md")
            except OverseerError as exc:
                # A staged-output schema failure: retryable per ruling 1, so
                # it commits its trace (A15) and counts. The report stays in
                # the stage — this path never published one and still does
                # not; what is durable is the failure note.
                detail = _failure_detail(exc)
                closed_text, close_questions = (None, [])
                if not dry_run:
                    closed_text, close_questions = _close_out_if_exhausted(
                        home, week=week, attempts=attempt, cap=cap,
                        kind="schema-repair", detail=detail,
                    )
                text = _report_text(
                    date=started[:10], run_id=run_id, model=str(model), selected=selected,
                    population_count=len(week_rows), excluded=excluded,
                    model_calls=model_calls, guard=guard, reason=str(exc),
                    questions=close_questions,
                )
                report_path = _write_report_only(stage, text)
                if not dry_run and intent is not None:
                    # Published only when this attempt closed the week: the
                    # question has to reach `latest-report.md`, the one file
                    # `overseer open` reads it from.
                    published = _commit_failed_attempt(
                        home, intent, coverage_path=coverage_path,
                        coverage_before=coverage_before,
                        report_text=text if closed_text is not None else None,
                        date=started[:10], run_id=run_id, week=week,
                        started=started, attempt=attempt, cap=cap,
                        kind="schema-repair", detail=detail,
                        closed_text=closed_text,
                    )
                    if closed_text is not None:
                        report_path = published
                        _queue_week_closed(
                            deferred_notice, home, week, attempt,
                            "schema-repair", [run_id],
                        )
                _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "refused", "reason": str(exc)[:300]})
                return RunResult("refused", EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        if secret_files:
            names = ", ".join(secret_files)
            reason = f"secret-hit {names}"
            # S-68: a secret-scan hit is refused OUTRIGHT and never parked
            # (`01-architecture.md` §3.3a — a floor that stops a write cannot
            # also queue that write for later). It is still a failed attempt
            # of this week: it commits its trace and counts, so a model that
            # keeps emitting secrets reaches the cap and the user is asked,
            # instead of the week retrying for ever. The staged names are the
            # note's detail; the scanned TEXT never leaves the stage.
            detail = _failure_detail(f"secret scan refused staged file(s): {names}")
            closed_text, close_questions = (None, [])
            if not dry_run:
                closed_text, close_questions = _close_out_if_exhausted(
                    home, week=week, attempts=attempt, cap=cap,
                    kind="secret-scan", detail=detail,
                )
            text = _report_text(
                date=started[:10], run_id=run_id, model=str(model), selected=selected,
                population_count=len(week_rows), excluded=excluded,
                model_calls=model_calls, guard=guard,
                reason=f"secret scan refused staged file(s): {names}",
                questions=close_questions,
            )
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                # A5: coverage is restored, not committed. The second model
                # call's output never validated, so the week was NOT examined
                # and `last_run_at` must not claim it was.
                published = _commit_failed_attempt(
                    home, intent, coverage_path=coverage_path,
                    coverage_before=coverage_before,
                    report_text=text if closed_text is not None else None,
                    date=started[:10], run_id=run_id, week=week,
                    started=started, attempt=attempt, cap=cap,
                    kind="secret-scan", detail=detail, closed_text=closed_text,
                )
                if closed_text is not None:
                    report_path = published
                    _queue_week_closed(
                        deferred_notice, home, week, attempt, "secret-scan", [run_id]
                    )
            deferred_notice.home = home
            deferred_notice.cue = "routine"
            deferred_notice.message = f"overseer refused: {reason}"
            deferred_notice.ids = [run_id]
            _journal(home, {
                "at": chrono.now_iso(), "run": run_id,
                "status": "refused", "reason": reason,
            })
            return RunResult(
                "refused", EXIT_REFUSED, run_id, model_calls, selected,
                excluded, report=str(report_path),
            )

        refusal_reason = None
        if missing:
            refusal_reason = f"phase B incomplete: missing {', '.join(missing)}"

        if refusal_reason:
            detail = _failure_detail(refusal_reason)
            closed_text, close_questions = (None, [])
            if not dry_run:
                closed_text, close_questions = _close_out_if_exhausted(
                    home, week=week, attempts=attempt, cap=cap,
                    kind="schema-repair", detail=detail,
                )
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, reason=refusal_reason, questions=close_questions)
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                report_path = _commit_failed_attempt(
                    home, intent, coverage_path=coverage_path,
                    coverage_before=coverage_before, report_text=text,
                    date=started[:10], run_id=run_id, week=week, started=started,
                    attempt=attempt, cap=cap, kind="schema-repair",
                    detail=detail, closed_text=closed_text,
                )
                if closed_text is not None:
                    _queue_week_closed(
                        deferred_notice, home, week, attempt, "schema-repair", [run_id]
                    )
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "refused", "reason": refusal_reason})
            return RunResult("refused", EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        try:
            # Raw model output is rejected before the first successor case
            # or sheet can change the ledger.  Runner-owned additions below
            # truncate model prose rather than turning a landed decision into
            # a late refusal.
            questions = _questions(stage / "questions.yaml")
            findings = _validate_findings(_yaml_mapping(stage / "findings.yaml"), selected)
            model_updates = _model_updates(stage / "user-model-delta.yaml")
            prepared: list[tuple[Path | None, Path, batch.Sheet]] = []
            preview_apply = 0
            preview_refused = 0
            seen_predecessors: set[str] = set()
            for case_file, sheet_file in pairs:
                if case_file is not None and case_file.name == "case.yaml":
                    # A9: the caseless sheet's pair is catalogue maintenance;
                    # it supersedes nothing, so the successor rules below
                    # cannot apply to it and it has rules of its own.
                    _validate_maintenance_case(case_file)
                elif case_file is not None:
                    _validate_successor(case_file, {row["case"] for row in parked_rows})
                    predecessor = str(_yaml_mapping(case_file)["supersedes"])
                    if predecessor in seen_predecessors:
                        raise OverseerError(f"{case_file.name}: duplicate successor for {predecessor}")
                    seen_predecessors.add(predecessor)
                sheet = _load_sheet_allow_empty(sheet_file, home)
                if sheet is None:
                    if case_file is not None:
                        raise OverseerError(f"{sheet_file.name}: a successor case needs a non-empty sheet")
                    continue
                if case_file is None:
                    raise OverseerError(
                        "sheet.yaml: a non-empty catalogue-change sheet needs a "
                        "paired successor case in case.yaml, and that case must "
                        "be kind: maintenance"
                    )
                preview = batch.dry_run(home, sheet, actor="overseer", hook_activation=config.hook_activation_enabled(home))
                preview_apply += sum(item.state == "would-apply" for item in preview.items)
                preview_refused += sum(item.state == "would-refuse" for item in preview.items)
                prepared.append((case_file, sheet_file, sheet))
        except (OverseerError, batch.BatchError) as exc:
            detail = _failure_detail(exc)
            closed_text, close_questions = (None, [])
            if not dry_run:
                closed_text, close_questions = _close_out_if_exhausted(
                    home, week=week, attempts=attempt, cap=cap,
                    kind="schema-repair", detail=detail,
                )
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, reason=str(exc), questions=close_questions)
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                report_path = _commit_failed_attempt(
                    home, intent, coverage_path=coverage_path,
                    coverage_before=coverage_before, report_text=text,
                    date=started[:10], run_id=run_id, week=week, started=started,
                    attempt=attempt, cap=cap, kind="schema-repair",
                    detail=detail, closed_text=closed_text,
                )
                if closed_text is not None:
                    _queue_week_closed(
                        deferred_notice, home, week, attempt, "schema-repair", [run_id]
                    )
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "refused", "reason": str(exc)[:300]})
            return RunResult("refused", EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        if dry_run:
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, parked_decided=preview_apply, preview_sheets=len(pairs), preview_refused=preview_refused)
            report_path = _write_report_only(stage, text)
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "dry-run", "model_calls": model_calls})
            return RunResult("dry-run", EXIT_OK, run_id, model_calls, selected, excluded, report=str(report_path))

        assert intent is not None
        manifest = _prepare_manifest(
            home, stage, run_id=run_id, started=started, model=str(model),
            selected=selected, population_count=len(week_rows), excluded=excluded,
            model_calls=model_calls, guard=guard, coverage_text=coverage_text,
            questions=questions, findings=findings, prepared=prepared,
            model_updates=model_updates,
        )
        _publish_manifest(home, intent, manifest, coverage_path)

    return _execute_manifest(
        home, manifest, boundary_no_push=boundary_no_push
    )
