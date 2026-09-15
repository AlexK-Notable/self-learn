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
        self.home: Path | None = None
        self.cue = "routine"
        self.message: str | None = None
        self.ids: list[str] = []

    def __enter__(self) -> "_DeferredNotice":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.message is not None:
            assert self.home is not None
            notify.send(self.home, self.cue, self.message, self.ids)


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
) -> str:
    refused = refused or []
    hooks = hooks or []
    selected_text = ", ".join(selected) if selected else "none"
    refusal_lines = [f"- {line}" for line in refused] or ["- none"]
    hook_lines = [f"- {line}" for line in hooks] or ["- none"]
    model_lines = [f"- {line}" for line in (user_model_lines or [])] or ["- none"]
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
        "", "## Hooks", *hook_lines, "", "## User model", *model_lines, "",
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
    user_model_lines: list[str] | None = None,
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
        hooks_end = next(
            (i for i in range(hooks_at, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        bare_none = next(
            (i for i in range(hooks_at, hooks_end) if lines[i].strip() == "- none"),
            None,
        )
        if bare_none is not None:
            lines.pop(bare_none)
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


def _unfinished_manifest(home: Path) -> dict[str, Any] | None:
    unfinished = [
        row for row in _committed_overseer_manifests(home)
        if row.get("status") != "complete"
    ]
    if len(unfinished) > 1:
        raise OverseerError("more than one unfinished overseer manifest")
    return unfinished[0] if unfinished else None


def has_unfinished_work(home: Path | str) -> bool:
    """Whether committed Git truth contains an unfinished overseer recipe."""
    return _unfinished_manifest(Path(home)) is not None


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
        "start_head": gitops.head_sha(home),
        "started": started,
        "date": started[:10],
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


def _write_manifest_truth(
    home: Path,
    manifest: dict[str, Any],
    *,
    report_text: str,
    complete: bool,
) -> tuple[Path, Path]:
    path = execution_evidence.manifest_path(home, manifest["run_id"])
    # Preserve a compound verb's in-commit proof if it advanced this file.
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(current.get("ledger_effects"), list):
            manifest["ledger_effects"] = current["ledger_effects"]
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    manifest["status"] = "complete" if complete else "unfinished"
    report_path = home / "overseer" / f"{manifest['date']}-report.md"
    latest = home / "overseer" / "latest-report.md"
    questions_path = home / "overseer" / "open-questions.yaml"
    paths = [path, report_path, latest]
    if complete:
        paths.append(questions_path)
    with intents.ledger_write(home):
        intent = intents.begin(
            home, "overseer-run-finalize", paths,
            f"self-learn: overseer finalize {manifest['run_id']}",
        )
        for target in paths:
            intents.add_step(intent, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(path, _manifest_text(manifest), fsync=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        fsops.atomic_write(report_path, report_text, fsync=True)
        fsops.atomic_write(latest, report_text, fsync=True)
        if complete:
            fsops.atomic_write(
                questions_path, _yaml_text(manifest["questions"]), fsync=True
            )
        intents.complete(intent)
        gitops.stage_and_commit(home, paths, intent.commit_subject, None)
        intents.finish(intent)
    return report_path, latest


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
    terminal = [
        item for item in receipted.values()
        if item.state in ("refused", "stopped")
    ]
    if terminal:
        # A committed refusal is itself the durable disposition. In
        # particular, never retry U5's refused reference reconsideration.
        # The recipe remains unfinished so the report continues to expose
        # the obligation, but no ledger leg is attempted again.
        result = batch.BatchResult(
            items=[receipted[n] for n in sorted(receipted)],
            stopped_at=next(
                (item.n for item in terminal if item.state == "stopped"), None
            ),
            process_code=max(item.rc for item in terminal),
            case=case_id, sheet_sha=effective.sheet_sha, actor="overseer",
        )
        return result, {"state": "preserved", "pushed": None}, effective
    completed = _receipt_completed(home, case_id, recipe)
    completed = _mutation_proven_completed(
        home, manifest, case_id, recipe, completed
    )
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
                    hook_lines.append(
                        f"{item_result.id}: {item_result.detail or item_result.state}"
                    )
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

    decision = _worst_code(codes, any_applied=application_count > 0)
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
    try:
        text = _finalize_model_report(
            stage / "report.md", date=cast(str, manifest["date"]), run_id=run_id,
            model=cast(str, manifest["model"]), selected=selected,
            population_count=int(manifest.get("population_count") or 0),
            excluded=excluded, model_calls=model_calls,
            guard=int(manifest.get("guard") or 0), refusals=refusals,
            hooks=hook_lines,
            user_model_lines=user_model_lines,
        )
        report_path, latest = _write_manifest_truth(
            home, manifest, report_text=text, complete=not halted
        )
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
            user_model_lines=user_model_lines,
        )
        try:
            report_path, latest = _write_manifest_truth(
                home, manifest, report_text=partial_text, complete=False
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
        unfinished = _unfinished_manifest(home)
        if unfinished is not None:
            return _execute_manifest(
                home, unfinished, boundary_no_push=boundary_no_push
            )
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
            model_updates = _model_updates(stage / "user-model-delta.yaml")
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
