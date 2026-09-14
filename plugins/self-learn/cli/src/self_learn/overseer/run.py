"""O-3 — the weekly two-invocation overseer runner.

The model can read and write only ``worker.stage/overseer``.  This module
validates that stage and owns every ledger write through the existing case,
batch, observation, intent, and git seams.

The user-model delta write leg is deferred to O-3b (``overseer user-model
delta leg``), which will mirror the steward implementation after U10 merges.
An examine-only run spools no telemetry of its own; every applied sheet uses
``batch.run``'s existing mutating epilogue.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML, YAMLError

from .. import batch, cases, conditions, config, gitops, intents, invocation, provider, scan, settings, user_model, verbs, worker
from ..ledger import resolve_home
from ..primitives import chrono, fsops
from . import population as population_mod

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
    """Run a refusal notification only after the enclosing ledger lock exits."""

    def __init__(self) -> None:
        self.message: str | None = None
        self.ids: list[str] = []

    def __enter__(self) -> "_DeferredNotice":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.message is not None:
            worker._notify_with_ids(self.message, self.ids)


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
Write report.md, findings.yaml, questions.yaml, and either sheet.yaml or paired
case-<name>.yaml plus sheet-<name>.yaml files. One successor case must supersede each parked
case you decide. The runner alone records cases and applies sheets. Never run a verb.
findings.yaml is {{findings: [{{case, kind: examined|dependency-moved, text, ref?}}]}}.
questions.yaml contains structured ids and affected case ids only, no free text.
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
    _write_stage(stage, stage / "health.yaml", _yaml_text({"facts": [asdict(item) for item in conditions.feed(home)]}))


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
    reason: str | None = None,
) -> str:
    refused = refused or []
    hooks = hooks or []
    selected_text = ", ".join(selected) if selected else "none"
    refusal_lines = [f"- {line}" for line in refused] or ["- none"]
    hook_lines = [f"- {line}" for line in hooks] or ["- none"]
    if reason:
        refusal_lines = [f"- {reason}", *refusal_lines]
    lines = [
        f"# Overseer report — {date}   run {run_id}   actor overseer   model {model}", "",
        f"## Examined ({len(selected)} of {population_count} cases this week, chosen by the overseer; why these, why it stopped)",
        f"- Cases: {selected_text}",
        f"- {excluded} cases excluded: freeze hash mismatch",
        f"- Model calls this run: {model_calls} of the runaway guard {guard}", "",
        "## Decided in the user's stead", f"- parked items decided: {parked_decided}",
        *( [f"- Dry-run preview: {preview_sheets} sheet(s); {parked_decided} would apply; {preview_refused} would refuse"] if preview_sheets is not None and preview_refused is not None else []),
        "", "## Hooks", *hook_lines, "", "## User model",
        "- not examined this run (the user-model delta leg lands in a later unit)", "",
        "## Catalogue health", "- see health.yaml", "", "## Questions for you", "- none", "",
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


def _finalize_model_report(
    path: Path, *, date: str, run_id: str, model: str, selected: tuple[str, ...],
    population_count: int, excluded: int, model_calls: int, guard: int,
    refusals: list[str], hooks: list[str] | None = None,
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
    refused_at = next(i for i, line in enumerate(lines) if line.startswith("## Refused / could not do")) + 1
    if refusals:
        lines[refused_at:refused_at] = [f"- {item}" for item in refusals]
    if hooks:
        hooks_at = next(i for i, line in enumerate(lines) if line.startswith("## Hooks")) + 1
        lines[hooks_at:hooks_at] = [f"- {item}" for item in hooks]
    user_model_at = next(i for i, line in enumerate(lines) if line.startswith("## User model")) + 1
    next_heading = next(
        (i for i in range(user_model_at, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    lines[user_model_at:next_heading] = [
        "- not examined this run (the user-model delta leg lands in a later unit)"
    ]
    if len(lines) > 60:
        owned = set(facts)
        owned.add("- not examined this run (the user-model delta leg lands in a later unit)")
        owned.update(f"- {item}" for item in refusals)
        owned.update(f"- {item}" for item in hooks or [])
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


def _write_report_only(stage: Path, text: str) -> Path:
    path = stage / "report.final.md"
    _write_stage(stage, path, text)
    return path


def _write_run_truth(
    home: Path, intent: intents.Intent, *, coverage_path: Path, coverage_text: str | None,
    report_text: str, questions: dict[str, Any], date: str,
) -> tuple[Path, Path]:
    overseer_dir = home / "overseer"
    report_path = overseer_dir / f"{date}-report.md"
    latest = overseer_dir / "latest-report.md"
    questions_path = overseer_dir / "open-questions.yaml"
    for path in (report_path, latest, questions_path):
        intents.add_step(intent, path)
    overseer_dir.mkdir(parents=True, exist_ok=True)
    if coverage_text is not None:
        fsops.atomic_write(coverage_path, coverage_text, fsync=True)
    fsops.atomic_write(report_path, report_text, fsync=True)
    fsops.atomic_write(latest, report_text, fsync=True)
    fsops.atomic_write(questions_path, _yaml_text(questions), fsync=True)
    return report_path, latest


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
    return [(None, sheet)] if sheet.is_file() else []


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
    return batch.load_sheet(path, home=home)


def _worst_code(codes: list[int], *, any_applied: bool) -> int:
    for code in (7, 4, 3):
        if code in codes:
            return code
    if 8 in codes or (any_applied and any(code in (1, 6) for code in codes)):
        return EXIT_PARTIAL
    if 6 in codes:
        return 6
    return 1 if 1 in codes else 0


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
    turns_a = int(getattr(outcome_a, "turns", 0) or 0)
    if not outcome_a.ok:
        state = "timed-out" if outcome_a.failure == "timeout" else "refused"
        _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": state, "phase": "a"})
        return RunResult(state, EXIT_REFUSED, run_id, turns_a, excluded=excluded)
    if turns_a >= guard:
        text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=(), population_count=len(week_rows), excluded=excluded, model_calls=turns_a, guard=guard, reason=f"runaway guard reached after phase A at {turns_a} calls; phase B was not started")
        report_path = _write_report_only(stage, text)
        _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "runaway", "phase": "a", "turns": turns_a})
        return RunResult("runaway", EXIT_REFUSED, run_id, turns_a, excluded=excluded, report=str(report_path))

    try:
        selection = _yaml_mapping(stage / "selection.yaml")
        selected = _selected_ids(selection, {row["case"] for row in week_rows})
        _validate_initial(stage / "initial-views.yaml", selected)
    except (OverseerError, population_mod.CoverageError) as exc:
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
        turns_b = int(getattr(outcome_b, "turns", 0) or 0)
        model_calls = turns_a + turns_b
        if not outcome_b.ok or model_calls >= guard:
            state = "runaway" if model_calls >= guard else ("timed-out" if outcome_b.failure == "timeout" else "refused")
            reason = f"runaway guard reached after phase B at {model_calls} calls; phase B output was not applied" if state == "runaway" else f"phase B {state}; no phase B output was applied"
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, reason=reason)
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                stored, _ = _write_run_truth(home, intent, coverage_path=coverage_path, coverage_text=None, report_text=text, questions={"questions": []}, date=started[:10])
                intents.complete(intent)
                gitops.stage_and_commit(home, [coverage_path, stored, home / "overseer" / "latest-report.md", home / "overseer" / "open-questions.yaml"], intent.commit_subject, None)
                intents.finish(intent)
                report_path = stored
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": state, "phase": "b", "turns": model_calls})
            return RunResult(state, EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        required = [stage / name for name in ("report.md", "findings.yaml", "questions.yaml")]
        missing = [path.name for path in required if not path.is_file()]
        pairs = _sheet_pairs(stage)
        if not pairs:
            missing.append("sheet.yaml")
        secret_files = _secret_files(stage)

        if not missing and not secret_files:
            try:
                _validate_model_report(stage / "report.md")
            except OverseerError as exc:
                text = _report_text(
                    date=started[:10], run_id=run_id, model=str(model), selected=selected,
                    population_count=len(week_rows), excluded=excluded,
                    model_calls=model_calls, guard=guard, reason=str(exc),
                )
                report_path = _write_report_only(stage, text)
                if not dry_run and intent is not None:
                    if coverage_before is None:
                        coverage_path.unlink(missing_ok=True)
                        try:
                            coverage_path.parent.rmdir()
                        except OSError:
                            pass
                    else:
                        fsops.atomic_write(coverage_path, coverage_before, fsync=True)
                    intents.finish(intent)
                _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "refused", "reason": str(exc)[:300]})
                return RunResult("refused", EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        if secret_files:
            names = ", ".join(secret_files)
            reason = f"secret-hit {names}"
            text = _report_text(
                date=started[:10], run_id=run_id, model=str(model), selected=selected,
                population_count=len(week_rows), excluded=excluded,
                model_calls=model_calls, guard=guard,
                reason=f"secret scan refused staged file(s): {names}",
            )
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                intents.complete(intent)
                gitops.stage_and_commit(
                    home, [coverage_path], intent.commit_subject, None
                )
                intents.finish(intent)
            deferred_notice.message = f"overseer refused: {reason}"
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
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, reason=refusal_reason)
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                stored, _ = _write_run_truth(home, intent, coverage_path=coverage_path, coverage_text=None, report_text=text, questions={"questions": []}, date=started[:10])
                intents.complete(intent)
                gitops.stage_and_commit(home, [coverage_path, stored, home / "overseer" / "latest-report.md", home / "overseer" / "open-questions.yaml"], intent.commit_subject, None)
                intents.finish(intent)
                report_path = stored
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "refused", "reason": refusal_reason})
            return RunResult("refused", EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        try:
            # Raw model output is rejected before the first successor case
            # or sheet can change the ledger.  Runner-owned additions below
            # truncate model prose rather than turning a landed decision into
            # a late refusal.
            questions = _questions(stage / "questions.yaml")
            findings = _validate_findings(_yaml_mapping(stage / "findings.yaml"), selected)
            prepared: list[tuple[Path | None, Path, batch.Sheet]] = []
            preview_apply = 0
            preview_refused = 0
            seen_predecessors: set[str] = set()
            for case_file, sheet_file in pairs:
                if case_file is not None:
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
                    raise OverseerError("sheet.yaml: a non-empty decision sheet needs a paired successor case")
                preview = batch.dry_run(home, sheet, actor="overseer", hook_activation=config.hook_activation_enabled(home))
                preview_apply += sum(item.state == "would-apply" for item in preview.items)
                preview_refused += sum(item.state == "would-refuse" for item in preview.items)
                prepared.append((case_file, sheet_file, sheet))
        except (OverseerError, batch.BatchError) as exc:
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, reason=str(exc))
            report_path = _write_report_only(stage, text)
            if not dry_run and intent is not None:
                stored, _ = _write_run_truth(home, intent, coverage_path=coverage_path, coverage_text=None, report_text=text, questions={"questions": []}, date=started[:10])
                intents.complete(intent)
                gitops.stage_and_commit(home, [coverage_path, stored, home / "overseer" / "latest-report.md", home / "overseer" / "open-questions.yaml"], intent.commit_subject, None)
                intents.finish(intent)
                report_path = stored
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "refused", "reason": str(exc)[:300]})
            return RunResult("refused", EXIT_REFUSED, run_id, model_calls, selected, excluded, report=str(report_path))

        if dry_run:
            text = _report_text(date=started[:10], run_id=run_id, model=str(model), selected=selected, population_count=len(week_rows), excluded=excluded, model_calls=model_calls, guard=guard, parked_decided=preview_apply, preview_sheets=len(pairs), preview_refused=preview_refused)
            report_path = _write_report_only(stage, text)
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "dry-run", "model_calls": model_calls})
            return RunResult("dry-run", EXIT_OK, run_id, model_calls, selected, excluded, report=str(report_path))

        assert intent is not None
        codes: list[int] = []
        refusals: list[str] = []
        hook_lines: list[str] = []
        application_count = 0
        decided_ids: list[str] = []
        gate = config.hook_activation_enabled(home)
        try:
            for case_file, sheet_file, loaded in prepared:
                effective = loaded
                if case_file is not None:
                    successor = cases.record(home, case_file, actor="overseer")
                    decided_ids.append(successor)
                    raw = _yaml_mapping(sheet_file)
                    raw["case"] = successor
                    effective_path = stage / f"effective-{sheet_file.name}"
                    _write_stage(stage, effective_path, _yaml_text(raw))
                    effective = batch.load_sheet(effective_path, home=home)
                    batch.dry_run(home, effective, actor="overseer", hook_activation=gate)
                result = batch.run(home, effective, no_push=True, actor="overseer", hook_activation=gate)
                codes.append(result.process_code)
                application_count += result.summary.get("applied", 0)
                for item in result.items:
                    if item.state in ("refused", "stopped") and item.detail:
                        refusals.append(item.detail)
                for sheet_item, item_result in zip(effective, result.items, strict=True):
                    if sheet_item.verb == "route" and sheet_item.fields.get("dest") == "hook":
                        hook_lines.append(f"{item_result.id}: {item_result.detail or item_result.state}")
                receipt_error: Exception | None = None
                try:
                    receipt = batch.write_receipt(home, result, sheet_file.name, no_push=True)
                except Exception as exc:
                    # The batch already changed the ledger.  Retry the
                    # idempotent receipt before the run's partial handler
                    # records the late failure, so an earned application is
                    # never silently orphaned.
                    receipt = batch.write_receipt(home, result, sheet_file.name, no_push=True)
                    receipt_error = exc
                _journal(home, {
                    "at": chrono.now_iso(), "run": run_id, "status": "sheet",
                    "sheet": sheet_file.name, "sheet_sha": result.sheet_sha,
                    "stopped": result.summary["stopped"], "code": result.process_code,
                    "receipt": receipt, "items": result.to_json()["items"],
                })
                if receipt_error is not None:
                    raise receipt_error

            for finding in findings:
                case_id = cast(str, finding.get("case"))
                kind = cast(str, finding.get("kind"))
                cases.observe(home, case_id, kind, text=str(finding.get("text") or "examined"), by="overseer", ref=finding.get("ref"))

            decision = _worst_code(codes, any_applied=application_count > 0)
            status_name = "partial" if decision == EXIT_PARTIAL else ("refused" if decision else "applied")
            text = _finalize_model_report(
                stage / "report.md", date=started[:10], run_id=run_id, model=str(model),
                selected=selected, population_count=len(week_rows), excluded=excluded,
                model_calls=model_calls, guard=guard, refusals=refusals, hooks=hook_lines,
            )
            report_path, latest = _write_run_truth(home, intent, coverage_path=coverage_path, coverage_text=None, report_text=text, questions=questions, date=started[:10])
            intents.complete(intent)
            gitops.stage_and_commit(home, [coverage_path, report_path, latest, home / "overseer" / "open-questions.yaml"], intent.commit_subject, None)
            intents.finish(intent)
        except Exception as exc:
            reason = f"run ended early: {exc}"
            partial_text = _report_text(
                date=started[:10], run_id=run_id, model=str(model), selected=selected,
                population_count=len(week_rows), excluded=excluded,
                model_calls=model_calls, guard=guard, parked_decided=application_count,
                refused=refusals, hooks=hook_lines, reason=reason,
            )
            stored: Path | None = None
            try:
                stored, _latest = _write_run_truth(
                    home, intent, coverage_path=coverage_path, coverage_text=None,
                    report_text=partial_text, questions=questions, date=started[:10],
                )
                intents.complete(intent)
                gitops.stage_and_commit(
                    home, [coverage_path, stored, home / "overseer" / "latest-report.md", home / "overseer" / "open-questions.yaml"],
                    intent.commit_subject, None,
                )
                intents.finish(intent)
            except Exception as handler_exc:
                _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "partial-handler-error", "reason": str(handler_exc)[:300]})
                try:
                    intents.finish(intent)
                except Exception:
                    pass
            _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "partial", "reason": reason[:300]})
            return RunResult("partial", EXIT_PARTIAL, run_id, model_calls, selected, excluded, application_count, len(refusals), str(stored) if stored is not None else None)

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
                _journal(home, {"at": chrono.now_iso(), "run": run_id, "status": "push-report-error", "reason": str(exc)[:300]})
    worker._notify_with_ids(f"overseer {status_name}: {len(selected)} examined", [*selected, *decided_ids])
    journal_entry: dict[str, Any] = {"at": chrono.now_iso(), "run": run_id, "status": status_name, "code": decision, "model_calls": model_calls}
    if push_failure is not None:
        journal_entry["push"] = push_failure
    _journal(home, journal_entry)
    return RunResult(status_name, decision, run_id, model_calls, selected, excluded, application_count, len(refusals), str(report_path))
