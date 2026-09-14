"""The autonomous steward runner (plan-steward 5.1-5.4, S-29/S-65/S-67).

The model may write only declared stage files below one cache run directory.
This module owns every ledger write made from those files.
"""

from __future__ import annotations

import fcntl
import io
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from ruamel.yaml import YAML

from . import (
    batch,
    cases,
    gitops,
    intents,
    invocation,
    ledger_ops,
    settings,
    statements,
    steward_prompt,
    user_model,
    verbs,
    worker,
)
from .ledger import discover_buckets
from .records import Record, RecordError
from .primitives import chrono
from .primitives import fsops


@dataclass
class RunResult:
    status: str
    run_id: str | None = None
    decided: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    calls: int = 0
    refused: int = 0


_ALLOWED_TOOLS = "Read,Grep,Glob,Write,Edit"
_DISALLOWED_TOOLS = "Bash,NotebookEdit,Task,WebFetch,WebSearch"
_RECONSIDER_OBSERVATION_RE = re.compile(
    r"^- obs-[0-9a-f]{8} (\S+) \S+ (statement|dependency-moved):.*?\(ref: ([^)]+)\)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class _QueuedProposal:
    record: Record
    proposal_path: Path


def cache_dir(home: Path | str | None = None) -> Path:
    return worker.cache_dir(home)


def steward_dir(home: Path | str) -> Path:
    path = cache_dir(home) / "steward"
    path.mkdir(parents=True, exist_ok=True)
    return path


def journal_path(home: Path | str) -> Path:
    return steward_dir(home) / "journal.jsonl"


def _journal(home: Path | str, entry: dict) -> None:
    path = journal_path(home)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n", fsync=True)


def _read_yaml(path: Path) -> dict | list:
    try:
        value = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- one repair turn receives the exact parse error
        raise ValueError(f"{path.name}: unreadable YAML -- {exc}") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError(f"{path.name}: expected a mapping or list")
    return value


def _dump_yaml(path: Path, data: dict | list) -> None:
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    buf = io.StringIO()
    yaml.dump(data, buf)
    fsops.atomic_write(path, buf.getvalue(), fsync=True)


def _eligible_proposals(home: Path) -> list[tuple[ledger_ops.QueueEntry, dict]]:
    entries: list[ledger_ops.QueueEntry] = []
    for bucket in discover_buckets(home):
        entries.extend(ledger_ops.queue(bucket))
    entries.sort(
        key=lambda entry: (
            chrono.to_dt(entry.record.created_at)
            or datetime.fromtimestamp(0, tz=timezone.utc),
            entry.record.id,
        )
    )
    out: list[tuple[ledger_ops.QueueEntry, dict]] = []
    for entry in entries:
        if ledger_ops.is_unanalyzed(entry):
            continue
        proposal = ledger_ops.read_proposal(entry.proposal_path)
        proposal = dict(proposal)
        proposal["id"] = entry.record.id
        out.append((entry, proposal))
    return out


def _reconsider_proposals(home: Path) -> tuple[list[tuple[_QueuedProposal, dict]], dict[str, str]]:
    all_cases = cases.list_cases(home, only_ok=True)
    superseded = {row.get("supersedes") for row in all_cases if row.get("supersedes")}
    selected: list[tuple[_QueuedProposal, dict]] = []
    predecessors: dict[str, str] = {}
    seen: set[str] = set()
    for row in all_cases:
        case_id = row.get("case")
        if not isinstance(case_id, str) or case_id in superseded:
            continue
        try:
            view = cases.show(home, case_id, evidence_only=False)
        except cases.CaseError:
            continue
        dependencies = view.sections.get("Dependencies", "")
        observations = view.sections.get("Later observations", "")
        matches = [
            match
            for match in _RECONSIDER_OBSERVATION_RE.finditer(observations)
            if match.group(3) in dependencies
        ]
        if not matches:
            continue
        for rid in row.get("records") or []:
            if rid in seen:
                continue
            try:
                record_path = ledger_ops.find_record_path(home, rid)
                record = Record.from_path(record_path)
            except (ledger_ops.LedgerOpsError, RecordError, OSError):
                continue
            seen.add(rid)
            predecessors[rid] = case_id
            selected.append(
                (
                    _QueuedProposal(record, Path("reconsider") / f"{rid}.yaml"),
                    {
                        "id": rid,
                        "card": {
                            "headline": "A dependency of the prior decision changed.",
                            "unresolved": "Re-decide against the new statement or dependency observation.",
                        },
                        "recommendation": "reconsider",
                    },
                )
            )
    return selected, predecessors


def _validate_declared_stage(stage: Path) -> None:
    allowed_names = set(steward_prompt.OUTPUT_CONTRACT)
    allowed_files = {name for name in allowed_names if "*" not in name}
    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
        rel = path.relative_to(stage).as_posix()
        declared = rel in allowed_files or (
            rel.startswith("cases/") and rel.endswith(".yaml") and "cases/*.yaml" in allowed_names
        ) or (
            rel.startswith("sheets/") and rel.endswith(".yaml") and "sheets/*.yaml" in allowed_names
        )
        if not declared:
            raise ValueError(f"undeclared stage file: {rel}")
        _read_yaml(path)
    case_files = sorted((stage / "cases").glob("*.yaml")) if (stage / "cases").is_dir() else []
    sheet_files = sorted((stage / "sheets").glob("*.yaml")) if (stage / "sheets").is_dir() else []
    if not case_files:
        raise ValueError("cases/*.yaml: at least one decision case is required")
    if {p.stem for p in case_files} != {p.stem for p in sheet_files}:
        raise ValueError("cases/*.yaml and sheets/*.yaml must have matching stems")
    for sheet_path in sheet_files:
        raw = _read_yaml(sheet_path)
        if not isinstance(raw, dict):
            raise ValueError(f"{sheet_path.name}: sheet must be a mapping")
        raw = dict(raw)
        # The model cannot know the case id that cases.record will assign.
        # Validate the otherwise exact owner schema with that one runner-owned
        # value absent, then validate it again with home= after substitution.
        if raw.get("case") == "$CASE_ID":
            raw.pop("case")
        validation_path = stage.parent / f".validate-{uuid.uuid4().hex}.yaml"
        try:
            _dump_yaml(validation_path, raw)
            batch.load_sheet(validation_path)
        except batch.BatchError as exc:
            raise ValueError(str(exc)) from exc
        finally:
            validation_path.unlink(missing_ok=True)


def _session_spec(
    home: Path, run_dir: Path, prompt: str, *, label: str
) -> invocation.SessionSpec:
    timeout_value, _source = settings.resolve_setting(
        home, settings.by_name("steward.timeout_secs")
    )
    timeout = cast(int | float | str, timeout_value)
    containment = invocation.containment_for(
        "steward",
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=_DISALLOWED_TOOLS,
        stage_dir=run_dir,
    )
    return invocation.SessionSpec(
        surface="steward",
        prompt=prompt,
        cwd=run_dir,
        timeout=float(timeout),
        containment=containment,
        log=lambda message: _journal(home, {"ts": chrono.now_iso(), "status": "model-log", "message": message}),
        label=label,
    )


def _repair_spec(spec: invocation.SessionSpec, error: str) -> invocation.SessionSpec:
    return invocation.SessionSpec(
        surface=spec.surface,
        prompt=(
            spec.prompt
            + "\n\n=== repair ===\nThe declared stage files failed validation once. "
            + "Repair them in place and do nothing else. Error: "
            + error
        ),
        cwd=spec.cwd,
        timeout=spec.timeout,
        containment=spec.containment,
        log=spec.log,
        label=f"{spec.label}-repair",
    )


def _prepare_sheet(path: Path, case_id: str) -> batch.Sheet:
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}: sheet must be a mapping")
    raw = dict(raw)
    raw["case"] = case_id
    items = raw.get("items")
    if isinstance(items, list):
        cooked = []
        for item in items:
            if not isinstance(item, dict):
                cooked.append(item)
                continue
            item = dict(item)
            verb = item.get("verb")
            if verb in batch.PERMITTED_KEYS and "by" in batch.PERMITTED_KEYS[verb]:
                item["by"] = "steward"
            cooked.append(item)
        raw["items"] = cooked
    _dump_yaml(path, raw)
    return batch.load_sheet(path)


def _sheet_without_case(sheet_path: Path) -> batch.Sheet:
    raw = _read_yaml(sheet_path)
    if not isinstance(raw, dict):
        raise ValueError(f"{sheet_path.name}: sheet must be a mapping")
    raw = dict(raw)
    raw.pop("case", None)
    validation_path = sheet_path.parent.parent / f".preview-{uuid.uuid4().hex}.yaml"
    try:
        _dump_yaml(validation_path, raw)
        return batch.load_sheet(validation_path)
    finally:
        validation_path.unlink(missing_ok=True)


def _forced_parking_reason(home: Path, sheet_path: Path) -> str | None:
    """Return the policy reason that prevents this sheet from dispatching."""
    raw = _read_yaml(sheet_path)
    if not isinstance(raw, dict):
        return None
    for item in raw.get("items") or []:
        if isinstance(item, dict) and item.get("verb") == "route" and item.get("dest") == "hook":
            return "hook"
    preview = batch.dry_run(home, _sheet_without_case(sheet_path), actor="steward")
    for item in preview.items:
        route = item.route_preview or {}
        if item.verb != "route" or route.get("mode") != "plain":
            continue
        host_value, target_value = route.get("host"), route.get("target")
        if not isinstance(host_value, str) or not isinstance(target_value, str):
            continue
        host, target = Path(host_value), Path(target_value)
        try:
            rel = target.resolve().relative_to(host.resolve())
        except ValueError:
            continue
        if gitops.is_tracked(host, rel):
            return "always-loaded-user-scope"
    return None


def _make_parked_case(case_path: Path, reason: str) -> None:
    raw = _read_yaml(case_path)
    if not isinstance(raw, dict):
        raise ValueError(f"{case_path.name}: case must be a mapping")
    raw = dict(raw)
    raw["kind"] = "parked"
    raw["outcome"] = "parked"
    raw["parked_for"] = "overseer"
    raw["parked_reason"] = reason
    _dump_yaml(case_path, raw)


def _stage_entries(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    raw = _read_yaml(path)
    values: object = raw
    if isinstance(raw, dict):
        for key in ("items", "entries", "updates"):
            if key in raw:
                values = raw[key]
                break
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise ValueError(f"{path.name}: expected a list of mapping entries")
    return [dict(item) for item in values]


def _incorporate_revisions(stage: Path) -> None:
    """Put declared revisions into their owning case sheet before validation."""
    for revision in _stage_entries(stage / "revisions.yaml"):
        sheet_name = revision.pop("sheet", revision.pop("case", None))
        if not isinstance(sheet_name, str):
            raise ValueError("revisions.yaml: every entry needs sheet or case")
        if not sheet_name.endswith(".yaml"):
            sheet_name += ".yaml"
        sheet_path = stage / "sheets" / sheet_name
        raw = _read_yaml(sheet_path)
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise ValueError(f"revisions.yaml: {sheet_name} is not a decision sheet")
        item = dict(revision)
        item["verb"] = "revise"
        item["by"] = "steward"
        raw = dict(raw)
        existing = [entry for entry in raw["items"] if isinstance(entry, dict)]
        if item in existing:
            continue
        raw["items"] = [*raw["items"], item]
        _dump_yaml(sheet_path, raw)


def _validate_and_prepare_stage(stage: Path) -> None:
    _incorporate_revisions(stage)
    _validate_declared_stage(stage)


def _maintain_stage(home: Path, stage: Path, run_record: dict) -> int:
    """Apply only the four declared maintenance stage files."""
    refused = 0

    for item in _stage_entries(stage / "statements.yaml"):
        try:
            source = item.get("source")
            message_ref = source.get("message_ref") if isinstance(source, dict) else None
            if not isinstance(message_ref, str) or not (
                message_ref.startswith("transcript:") or message_ref.startswith("conversation:")
            ):
                raise statements.StatementUsageError(
                    "statement add: source.message_ref must be transcript:<session>#L<n> "
                    "or conversation:<obs-id>"
                )
            assert isinstance(source, dict)
            statements.add(
                home,
                verbatim=item.get("verbatim", ""),
                source=source,
                recorded_by="steward",
                answers=item.get("answers"),
                scope=item.get("scope"),
                uncertainty=item.get("uncertainty"),
                amends=item.get("amends"),
            )
        except (statements.StatementError, TypeError, ValueError) as exc:
            refused += 1
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_record.get("run_id"), "status": "statement-refused", "error": str(exc)})

    for item in _stage_entries(stage / "model-updates.yaml"):
        action = item.pop("action", "add")
        item.pop("by", None)
        try:
            if action == "add":
                if item.get("source") != "system-reading":
                    raise user_model.UserModelError(
                        "steward model updates may add provisional system readings only"
                    )
                user_model.add_entry(home, by="steward", **item)
            elif action == "lapse":
                entry_id = item.pop("id", "")
                user_model.lapse_entry(home, entry_id, by="steward", **item)
            else:
                raise user_model.UserModelUsageError(
                    f"model-updates.yaml: unknown action {action!r}"
                )
        except (user_model.UserModelError, TypeError, ValueError) as exc:
            refused += 1
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_record.get("run_id"), "status": "model-update-refused", "error": str(exc)})

    for index, item in enumerate(_stage_entries(stage / "parked.yaml"), start=1):
        item["kind"] = "parked"
        item["outcome"] = "parked"
        item["parked_for"] = "overseer"
        parked_path = stage.parent / f"parked-case-{index:04d}.yaml"
        _dump_yaml(parked_path, item)
        try:
            cases.record(home, parked_path, actor="steward")
        except cases.CaseError as exc:
            refused += 1
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_record.get("run_id"), "status": "parked-case-refused", "error": str(exc)})
    return refused


def _batch_result_from_json(data: dict) -> batch.BatchResult:
    return batch.BatchResult(
        items=[batch.ItemResult(**item) for item in data.get("items", [])],
        stopped_at=data.get("stopped_at"),
        pushed=bool(data.get("pushed", False)),
        process_code=int(data.get("process_code", 0)),
        case=data.get("case"),
        sheet_sha=data.get("sheet_sha"),
        recovered_rolled_forward=list(data.get("recovered_rolled_forward") or []),
        recovered_restored=list(data.get("recovered_restored") or []),
        stop_message=data.get("stop_message"),
        actor=data.get("actor") or "steward",
    )


def _preview_is_clean_for_sequence(preview: batch.DryRunResult, items: batch.Sheet) -> bool:
    """Account for a sanctioned [reopen, verb] sheet's sequential state change."""
    if preview.ok:
        return True
    reopened: set[str] = set()
    for shown, item in zip(preview.items, items, strict=True):
        if item.verb == "reopen" and shown.state != "would-refuse":
            reopened.add(item.id)
            continue
        if shown.state == "would-refuse" and item.id not in reopened:
            return False
    return True


def _reconcile_runs(home: Path) -> dict[str, str]:
    """Finish B->C receipts and mark A->B cases abandoned before selection."""
    successors: dict[str, str] = {}
    runs = steward_dir(home) / "runs"
    if not runs.is_dir():
        return successors
    for record_path in sorted(runs.glob("*/run.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        changed = False
        for result_ref in record.get("batch_results") or []:
            if result_ref.get("receipt"):
                continue
            result_path = record_path.parent / str(result_ref.get("path", ""))
            if not result_path.is_file():
                continue
            result = _batch_result_from_json(json.loads(result_path.read_text(encoding="utf-8")))
            batch.write_receipt(
                home, result, str(result_ref.get("sheet") or result_path.name), no_push=True
            )
            result_ref["receipt"] = True
            changed = True

        if record.get("status") == "case-recorded":
            case_id = record.get("active_case")
            if isinstance(case_id, str):
                rows = [r for r in cases.list_cases(home, only_ok=True) if r.get("case") == case_id]
                if rows:
                    text = f"steward abandoned: run {record.get('run_id')} crashed before apply"
                    cases.observe(home, case_id, "abandoned", text=text, by="steward")
                    for rid in rows[0].get("records") or []:
                        successors[str(rid)] = case_id
                    record["status"] = "abandoned-reconciled"
                    changed = True
        elif record.get("status") == "batch-applied" and all(
            ref.get("receipt") for ref in (record.get("batch_results") or [])
        ):
            record["status"] = "receipted-reconciled"
            changed = True
        elif record.get("status") == "maintenance-complete":
            decided: list[str] = []
            refused = 0
            for result_ref in record.get("batch_results") or []:
                result_path = record_path.parent / str(result_ref.get("path", ""))
                if not result_path.is_file():
                    continue
                result = _batch_result_from_json(
                    json.loads(result_path.read_text(encoding="utf-8"))
                )
                decided.extend(
                    item.id
                    for item in result.items
                    if item.state in ("applied", "already-applied", "parked")
                )
                refused += sum(
                    1
                    for item in result.items
                    if item.state in ("refused", "stopped", "not-attempted")
                )
            finished = chrono.now_iso()
            record["status"] = "partial" if refused and decided else "refused" if refused else "applied"
            record["finished_at"] = finished
            record["last_run_at"] = finished
            record["last_run_outcome"] = record["status"]
            record["decided"] = list(dict.fromkeys(decided))
            record["refused"] = refused
            record["cases_since_overseer"] = cases_since_overseer(home)
            fsops.atomic_write(
                steward_dir(home) / "steward.last-run", finished + "\n", fsync=True
            )
            changed = True
        if changed:
            record["reconciled_at"] = chrono.now_iso()
            _write_json(record_path, record)
    return successors


def _apply_packet(
    home: Path,
    run_dir: Path,
    stage: Path,
    record: dict,
    successors: dict[str, str],
) -> tuple[list[str], int]:
    decided: list[str] = []
    refused = 0
    case_ids = record.setdefault("case_ids", {})
    for case_path in sorted((stage / "cases").glob("*.yaml")):
        stem = case_path.stem
        sheet_path = stage / "sheets" / f"{stem}.yaml"
        parking_reason = _forced_parking_reason(home, sheet_path)
        if parking_reason is not None:
            _make_parked_case(case_path, parking_reason)
        case_data = _read_yaml(case_path)
        if isinstance(case_data, dict):
            predecessor_ids = {
                successors[rid]
                for rid in case_data.get("records") or []
                if rid in successors
            }
            if len(predecessor_ids) == 1 and not case_data.get("supersedes"):
                case_data = dict(case_data)
                case_data["supersedes"] = predecessor_ids.pop()
                _dump_yaml(case_path, case_data)
        try:
            case_id = cases.record(home, case_path, actor="steward")
        except cases.CaseError as exc:
            case_records = case_data.get("records") if isinstance(case_data, dict) else None
            refused += max(1, len(case_records) if isinstance(case_records, list) else 1)
            _journal(
                home,
                {
                    "ts": chrono.now_iso(),
                    "run_id": record.get("run_id"),
                    "status": "refused",
                    "stage_file": case_path.name,
                    "error": str(exc),
                },
            )
            continue
        case_ids[stem] = case_id
        record["status"] = "case-recorded"
        record["active_case"] = case_id
        record["active_sheet"] = sheet_path.name
        _write_json(run_dir / "run.json", record)
        if isinstance(case_data, dict) and case_data.get("kind") == "reconsider":
            for rid in case_data.get("records") or []:
                verbs.reconsider(home, rid, case=case_id, by="steward", no_push=True)

        _prepare_sheet(sheet_path, case_id)
        # Re-load with the real home only after the runner substituted the
        # newly committed case id.
        items = batch.load_sheet(sheet_path, home=home)
        if parking_reason is not None:
            result = batch.BatchResult(
                items=[
                    batch.ItemResult(
                        n=item.n,
                        id=item.id,
                        verb=item.verb,
                        rc=0,
                        state="parked",
                        detail=f"parked for overseer: {parking_reason}",
                    )
                    for item in items
                ],
                process_code=0,
                case=case_id,
                sheet_sha=items.sheet_sha,
                actor="steward",
            )
        else:
            preview = batch.dry_run(home, items, actor="steward")
            if not _preview_is_clean_for_sequence(preview, items):
                result = batch.BatchResult(
                    items=[
                        batch.ItemResult(
                            n=item.n,
                            id=item.id,
                            verb=item.verb,
                            rc=1,
                            state="refused",
                            detail=item.detail,
                        )
                        for item in preview.items
                    ],
                    process_code=1,
                    case=case_id,
                    sheet_sha=items.sheet_sha,
                    actor="steward",
                )
            else:
                result = batch.run(home, items, no_push=True, actor="steward")
        result_path = run_dir / f"batch-result-{len(record.setdefault('batch_results', [])) + 1}.json"
        _write_json(result_path, result.to_json())
        record["batch_results"].append(
            {"path": result_path.name, "sheet": sheet_path.name, "receipt": False}
        )
        record["status"] = "batch-applied"
        _write_json(run_dir / "run.json", record)
        batch.write_receipt(home, result, sheet_path.name, no_push=True)
        record["batch_results"][-1]["receipt"] = True
        record["status"] = "receipted"
        _write_json(run_dir / "run.json", record)
        applied = list(
            dict.fromkeys(
                i.id
                for i in result.items
                if i.state in ("applied", "already-applied", "parked")
            )
        )
        decided.extend(applied)
        for rid in applied:
            successors.pop(rid, None)
        refused += sum(1 for i in result.items if i.state in ("refused", "stopped", "not-attempted"))
    return decided, refused


def last_run_iso_from_cache(resolved_cache_dir: Path) -> str | None:
    """Read the one cached marker without creating or migrating its directory."""
    marker = resolved_cache_dir / "steward" / "steward.last-run"
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def last_run_iso(home: Path | str | None = None) -> str | None:
    resolved = Path(home) if home is not None else None
    return last_run_iso_from_cache(cache_dir(resolved))


def cases_since_overseer(home: Path | str) -> int:
    """Count steward cases opened after the overseer's last completed run."""
    home = Path(home)
    cutoff: datetime | None = None
    coverage = home / "overseer" / "coverage.yaml"
    try:
        data = _read_yaml(coverage)
        value = data.get("last_run_at") if isinstance(data, dict) else None
        if isinstance(value, str):
            cutoff = chrono.to_dt(value)
    except (OSError, ValueError):
        cutoff = None
    count = 0
    for row in cases.list_cases(home, only_ok=True):
        if row.get("actor") != "steward":
            continue
        opened = chrono.to_dt(row.get("opened_at"))
        if cutoff is None or (opened is not None and opened > cutoff):
            count += 1
    return count


def run(home: Path | str, *, dry_run: bool = False) -> RunResult:
    home = Path(home)
    recovered = intents.recover(home)
    if recovered.stopped:
        result = RunResult("stopped", stopped=list(recovered.stopped))
        _journal(
            home,
            {"ts": chrono.now_iso(), "status": result.status, "stopped": result.stopped},
        )
        return result

    enabled, _source = settings.resolve_setting(home, settings.by_name("steward.enabled"))
    if not dry_run and not enabled:
        result = RunResult("disabled")
        _journal(home, {"ts": chrono.now_iso(), "status": result.status})
        return result

    lock_path = cache_dir(home) / "steward.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as lock_fh:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result = RunResult("idle")
            _journal(home, {"ts": chrono.now_iso(), "status": "idle", "reason": "already running"})
            return result
        successors = _reconcile_runs(home)
        reconsider, reconsider_successors = _reconsider_proposals(home)
        successors.update(reconsider_successors)
        reconsider_ids = {entry.record.id for entry, _proposal in reconsider}
        eligible = reconsider + [
            row for row in _eligible_proposals(home) if row[0].record.id not in reconsider_ids
        ]
        if not eligible:
            result = RunResult("idle")
            _journal(home, {"ts": chrono.now_iso(), "status": result.status})
            return result

        packet_size_value, _source = settings.resolve_setting(
            home, settings.by_name("steward.packet_size")
        )
        max_turns_value, _source = settings.resolve_setting(
            home, settings.by_name("sdk.max_turns.steward")
        )
        packet_size = cast(int | str, packet_size_value)
        max_turns = cast(int | str, max_turns_value)
        run_id = "run-" + uuid.uuid4().hex[:12]
        run_dir = steward_dir(home) / "runs" / run_id
        run_dir.mkdir(parents=True)
        packet_count = math.ceil(len(eligible) / int(packet_size))
        run_record: dict = {
            "run_id": run_id,
            "started_at": chrono.now_iso(),
            "status": "running",
            "NOT_REPO_TRUTH": {
                "value": True,
                "disposition": "cache recovery ledger; cases and git commits remain truth",
            },
            "packets": [],
            "case_ids": {},
            "batch_results": [],
        }
        _write_json(run_dir / "run.json", run_record)
        result = RunResult("dry-run" if dry_run else "applied", run_id=run_id)

        for packet_index, start in enumerate(range(0, len(eligible), int(packet_size)), start=1):
            rows = eligible[start : start + int(packet_size)]
            proposals = [proposal for _entry, proposal in rows]
            stage = run_dir / "steward" / f"packet-{packet_index:04d}"
            stage.mkdir(parents=True)
            context = steward_prompt.RunContext(
                run_id=run_id,
                stage_dir=stage,
                packet_index=packet_index,
                packet_count=packet_count,
                last_run_at=last_run_iso(home),
                verbs_the_runner_executes=(
                    "case record", "batch --dry-run", "batch", "case receipt",
                    "user-model", "statement add", "reconsider",
                ),
            )
            packet = steward_prompt.assemble(home, cache_dir(home), context, proposals)
            fsops.atomic_write(run_dir / f"packet-{packet_index:04d}.md", packet.text, fsync=True)
            spec = _session_spec(
                home,
                run_dir,
                packet.text,
                label=f"steward-{run_id}-{packet_index}",
            )
            outcome = invocation.write_session(spec)
            result.calls += 1
            packet_record = {
                "index": packet_index,
                "records": [entry.record.id for entry, _proposal in rows],
                "turns": getattr(outcome, "turns", None),
                "failure": outcome.failure,
                "bound": None,
            }
            run_record["packets"].append(packet_record)
            _write_json(run_dir / "run.json", run_record)
            if not outcome.ok:
                packet_record["bound"] = outcome.failure or "invocation"
                result.status = "partial"
                break
            outcome_turns = getattr(outcome, "turns", None)
            if outcome_turns is not None and outcome_turns >= int(max_turns):
                packet_record["bound"] = "turns"
                result.status = "partial"
                _write_json(run_dir / "run.json", run_record)
                break
            try:
                _validate_and_prepare_stage(stage)
            except ValueError as first_error:
                repair = invocation.write_session(_repair_spec(spec, str(first_error)))
                result.calls += 1
                try:
                    if not repair.ok:
                        raise ValueError(repair.detail or repair.failure or "repair invocation failed")
                    _validate_and_prepare_stage(stage)
                except ValueError as second_error:
                    packet_record["bound"] = "schema-repair"
                    packet_record["error"] = str(second_error)
                    result.status = "partial"
                    _write_json(run_dir / "run.json", run_record)
                    break
            if dry_run:
                continue
            packet_decided, packet_refused = _apply_packet(
                home, run_dir, stage, run_record, successors
            )
            result.decided.extend(packet_decided)
            result.refused += packet_refused
            run_record["status"] = "maintenance-started"
            _write_json(run_dir / "run.json", run_record)
            maintenance_refused = _maintain_stage(home, stage, run_record)
            result.refused += maintenance_refused
            packet_refused += maintenance_refused
            run_record["status"] = "maintenance-complete"
            _write_json(run_dir / "run.json", run_record)
            if packet_refused:
                result.status = "partial" if result.decided else "refused"

        run_record["status"] = result.status
        run_record["finished_at"] = chrono.now_iso()
        run_record["last_run_at"] = run_record["finished_at"]
        run_record["last_run_outcome"] = result.status
        run_record["cases_since_overseer"] = cases_since_overseer(home)
        run_record["decided"] = list(result.decided)
        run_record["refused"] = result.refused
        _write_json(run_dir / "run.json", run_record)
        finished = run_record["finished_at"]
        fsops.atomic_write(steward_dir(home) / "steward.last-run", finished + "\n", fsync=True)
        _journal(
            home,
            {
                "ts": finished,
                "run_id": run_id,
                "status": result.status,
                "calls": result.calls,
                "decided": len(result.decided),
                "refused": result.refused,
            },
        )
        return result
