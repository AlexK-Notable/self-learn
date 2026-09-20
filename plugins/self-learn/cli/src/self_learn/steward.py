"""The autonomous steward runner (plan-steward 5.1-5.4, S-29/S-65/S-67).

The model may write only declared stage files below one cache run directory.
This module owns every ledger write made from those files.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from ruamel.yaml import YAML

from . import (
    batch,
    cases,
    execution_evidence,
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
from .scan import format_refusal
from .scan import scan as secret_scan


@dataclass
class RunResult:
    status: str
    run_id: str | None = None
    decided: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    calls: int = 0
    refused: int = 0
    unfinished: list[str] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)


_ALLOWED_TOOLS = "Read,Grep,Glob,Write,Edit"
_DISALLOWED_TOOLS = "Bash,NotebookEdit,Task,WebFetch,WebSearch"
_RECONSIDER_OBSERVATION_RE = re.compile(
    r"^- (obs-[0-9a-f]{8}) (\S+) \S+ (statement|dependency-moved):.*?\(ref: ([^)]+)\)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class _QueuedProposal:
    record: Record
    proposal_path: Path
    predecessor: str | None = None
    observation_id: str | None = None


_CASE_OUTCOMES = (
    "route",
    "reject",
    "defer",
    "retire",
    "replaced",
    "rehome",
    "revise",
    "no-action",
    "parked",
)
_CASE_SCOPES = ("user", "project", "skill")
_TERMINAL_DISPOSITIONS = frozenset({"applied", "parked", "refused", "abandoned"})
_SUCCESS_RECEIPT_STATES = frozenset({"applied", "already-applied"})


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


def _yaml_text(data: dict | list) -> str:
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    buf = io.StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def _coverage_empty() -> dict[str, int]:
    return {
        f"{outcome}:{scope}": 0
        for outcome in _CASE_OUTCOMES
        for scope in _CASE_SCOPES
    }


def _scope_bucket(value: object) -> str:
    text = str(value or "")
    if text == "user" or text.startswith("user:"):
        return "user"
    if text == "project" or text.startswith("project:"):
        return "project"
    return "skill"


def _manifest_paths_at_head(home: Path) -> list[str]:
    proc = gitops._git(  # noqa: SLF001 -- committed-tree discovery seam
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs"
    )
    if proc.returncode != 0:
        return []
    return [
        line
        for line in proc.stdout.splitlines()
        if line.startswith("cases/runs/") and line.endswith(".json")
    ]


def committed_manifests(home: Path | str) -> list[dict]:
    """Read delegated-run state only from committed Git objects."""
    resolved = Path(home)
    manifests: list[dict] = []
    for rel in _manifest_paths_at_head(resolved):
        run_id = Path(rel).stem
        try:
            manifest = execution_evidence.read_manifest(resolved, run_id, at="HEAD")
        except (execution_evidence.ExecutionEvidenceError, gitops.GitOpsError):
            continue
        if manifest.get("actor") == "steward":
            manifests.append(manifest)
    return sorted(manifests, key=lambda row: str(row.get("started_at") or ""))


def _dirty_truth_paths(home: Path) -> list[str]:
    return gitops.dirty_paths(home, ".")


def _publish_manifest(home: Path, manifest: dict, *, reason: str) -> str:
    """Intent-protect and commit one immutable-identity manifest revision."""
    run_id = str(manifest.get("run_id") or "")
    path = execution_evidence.manifest_path(home, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    subject = f"self-learn: steward manifest {run_id} ({reason})"
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        dirty = _dirty_truth_paths(home)
        if dirty:
            raise gitops.GitOpsError(
                "steward refuses unexplained dirty ledger paths before manifest "
                f"publication: {dirty}"
            )
        try:
            if path.read_text(encoding="utf-8") == text:
                return gitops.head_sha(home)
        except OSError:
            pass
        intent = intents.begin(home, "steward-manifest", [path], subject)
        fsops.atomic_write(path, text, fsync=True)
        intents.complete(intent)
        sha = gitops.stage_and_commit(home, [path], subject, reason)
        if sha is None:  # pragma: no cover -- byte equality returned above
            raise gitops.GitOpsError("steward manifest commit produced nothing")
        intents.finish(intent)
        return sha


def _update_manifest(home: Path, run_id: str, *, reason: str, update) -> dict:
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    update(manifest)
    _publish_manifest(home, manifest, reason=reason)
    return manifest


def _project_manifest(home: Path, manifest: dict) -> Path:
    """Rebuild cache display state from committed truth; never the reverse."""
    run_id = str(manifest["run_id"])
    run_dir = steward_dir(home) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    projection = dict(manifest)
    projection["NOT_REPO_TRUTH"] = {
        "value": True,
        "disposition": (
            "projection rebuilt from committed cases/runs manifest; never recovery authority"
        ),
    }
    _write_json(run_dir / "run.json", projection)
    return run_dir


def _completed_manifest_time(home: Path) -> str | None:
    values = [
        str(row.get("completed_at"))
        for row in committed_manifests(home)
        if row.get("status") == "complete" and row.get("completed_at")
    ]
    return max(values) if values else None


def _input_identity(home: Path, path: Path, record_id: str, proposal: dict) -> dict:
    try:
        rel = path.resolve().relative_to(home.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"proposal path is outside the ledger: {path}") from exc
    blob = gitops._git(home, "rev-parse", f"HEAD:{rel}")  # noqa: SLF001
    if blob.returncode != 0 or not blob.stdout.strip():
        raise ValueError(f"proposal input is not committed: {rel}")
    version = blob.stdout.strip()
    return {
        "path": rel,
        "blob": version,
        "version": version,
        "record": record_id,
        "proposal": proposal,
    }


def _terminal_versions(home: Path) -> set[tuple[str, str]]:
    terminal: set[tuple[str, str]] = set()
    for manifest in committed_manifests(home):
        for packet in manifest.get("packets") or []:
            if not isinstance(packet, dict):
                continue
            for rid, disposition in (packet.get("dispositions") or {}).items():
                if not isinstance(disposition, dict):
                    continue
                if disposition.get("state") in _TERMINAL_DISPOSITIONS:
                    version = disposition.get("input_version")
                    if isinstance(rid, str) and isinstance(version, str):
                        terminal.add((rid, version))
    return terminal


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
    terminal = _terminal_versions(home)
    out: list[tuple[ledger_ops.QueueEntry, dict]] = []
    for entry in entries:
        if ledger_ops.is_unanalyzed(entry):
            continue
        proposal = ledger_ops.read_proposal(entry.proposal_path)
        proposal = dict(proposal)
        proposal["id"] = entry.record.id
        try:
            identity = _input_identity(
                home, entry.proposal_path, entry.record.id, proposal
            )
        except ValueError:
            continue
        if (entry.record.id, identity["version"]) in terminal:
            continue
        out.append((entry, proposal))
    return out


def _reconsider_proposals(home: Path) -> tuple[list[tuple[_QueuedProposal, dict]], dict[str, str]]:
    all_cases = cases.list_cases(home, only_ok=True)
    superseded = {row.get("supersedes") for row in all_cases if row.get("supersedes")}
    selected: list[tuple[_QueuedProposal, dict]] = []
    predecessors: dict[str, str] = {}
    seen: set[str] = set()
    consumed_observations = {
        str(observation)
        for manifest in committed_manifests(home)
        for observation in (manifest.get("reconsider_observations") or [])
    }
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
            if match.group(1) not in consumed_observations
            and match.group(4) in dependencies
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
                    _QueuedProposal(
                        record,
                        Path("reconsider") / f"{rid}.yaml",
                        predecessor=case_id,
                        observation_id=matches[-1].group(1),
                    ),
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
            return "plain-host-committed-file"
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
        insert_at = next(
            (
                index
                for index, existing_item in enumerate(raw["items"])
                if isinstance(existing_item, dict)
                and existing_item.get("id") == item.get("id")
                and existing_item.get("verb") == "route"
            ),
            len(raw["items"]),
        )
        raw["items"] = [
            *raw["items"][:insert_at],
            item,
            *raw["items"][insert_at:],
        ]
        _dump_yaml(sheet_path, raw)


def _validate_and_prepare_stage(stage: Path, selected_ids: set[str] | None = None) -> None:
    _incorporate_revisions(stage)
    _validate_declared_stage(stage)
    if selected_ids is not None:
        covered: list[str] = []
        for case_path in sorted((stage / "cases").glob("*.yaml")):
            data = _read_yaml(case_path)
            if isinstance(data, dict):
                covered.extend(str(rid) for rid in (data.get("records") or []))
        if sorted(covered) != sorted(selected_ids):
            raise ValueError(
                "decision cases must cover every selected record exactly once: "
                f"selected={sorted(selected_ids)}, covered={sorted(covered)}"
            )


def _new_case_id() -> str:
    return "case-" + uuid.uuid4().hex[:8]


def _prepared_recipe(
    home: Path,
    stage: Path,
    manifest: dict,
    packet: dict,
) -> None:
    """Freeze validated case/sheet/maintenance instructions before phase A."""
    run_id = str(manifest["run_id"])
    predecessors = packet.get("predecessors") or {}
    recipes = manifest.setdefault("cases", {})
    packet_case_ids: list[str] = []
    prepared_texts: list[str] = []
    for case_path in sorted((stage / "cases").glob("*.yaml")):
        stem = case_path.stem
        sheet_path = stage / "sheets" / f"{stem}.yaml"
        case_data = _read_yaml(case_path)
        if not isinstance(case_data, dict):
            raise ValueError(f"{case_path.name}: case must be a mapping")
        case_data = dict(case_data)
        case_data["run_id"] = run_id
        predecessor_ids = {
            predecessors[rid]
            for rid in case_data.get("records") or []
            if rid in predecessors
        }
        if len(predecessor_ids) > 1:
            raise ValueError(
                f"{case_path.name}: records span more than one predecessor case"
            )
        if predecessor_ids and not case_data.get("supersedes"):
            case_data["supersedes"] = next(iter(predecessor_ids))
        parking_reason = _forced_parking_reason(home, sheet_path)
        if parking_reason is not None:
            case_data["kind"] = "parked"
            case_data["outcome"] = "parked"
            case_data["parked_for"] = "overseer"
            case_data["parked_reason"] = parking_reason
        case_text = _yaml_text(case_data)
        fsops.atomic_write(case_path, case_text, fsync=True)
        case_id = _new_case_id()
        sheet = _prepare_sheet(sheet_path, case_id)
        sheet_text = sheet_path.read_text(encoding="utf-8")
        prepared_texts.extend([case_text, sheet_text])
        recipes[case_id] = {
            "case": case_text,
            "sheet": sheet_text,
            "sheet_name": sheet_path.name,
            "sheet_sha": sheet.sheet_sha,
            "sheet_digest": sheet.sheet_digest,
            "items": [
                {"n": item.n, "id": item.id, "verb": item.verb}
                for item in sheet
            ],
            "maintenance": [],
            "dispositions": [],
            "packet": packet["index"],
            "phase": "prepared",
            "parking_reason": parking_reason,
        }
        packet_case_ids.append(case_id)

    maintenance: list[dict] = []
    for kind, filename in (
        ("statement", "statements.yaml"),
        ("model", "model-updates.yaml"),
        ("parked-case", "parked.yaml"),
    ):
        for item in _stage_entries(stage / filename):
            payload = dict(item)
            prepared_texts.append(_yaml_text(payload))
            ordinal = len(maintenance) + 1
            identity_bytes = json.dumps(
                {
                    "packet": packet["index"],
                    "ordinal": ordinal,
                    "kind": kind,
                    "payload": payload,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            operation = {
                "id": "op-" + hashlib.sha256(identity_bytes).hexdigest()[:12],
                "kind": kind,
                "payload": payload,
                "state": "pending",
                "baseline": None,
                "result": None,
            }
            if kind == "parked-case":
                operation["reserved_case_id"] = _new_case_id()
            maintenance.append(operation)

    hits = [hit for text in prepared_texts for hit in secret_scan(text)]
    if hits:
        raise ValueError(format_refusal(hits))
    packet["case_ids"] = packet_case_ids
    packet["maintenance"] = maintenance
    packet["phase"] = "prepared"
    packet["failure"] = None
    packet["bound"] = None
    packet["dispositions"] = packet.get("dispositions") or {}


_RECEIPT_RE = re.compile(
    r"sheet=.*#(?P<sheet>[0-9a-f]{8}) item=(?P<item>[1-9][0-9]*).*?→ "
    r"(?P<state>[a-z-]+)(?: \(exit (?P<rc>-?[0-9]+)\))?"
)


def _committed_receipts(home: Path, case_id: str, sheet_sha: str) -> dict[int, batch.ItemResult]:
    try:
        view = cases.show(home, case_id, evidence_only=False)
    except cases.CaseError:
        return {}
    out: dict[int, batch.ItemResult] = {}
    for match in _RECEIPT_RE.finditer(view.sections.get("Application", "")):
        if match.group("sheet") != sheet_sha:
            continue
        n = int(match.group("item"))
        state = match.group("state")
        if state not in _SUCCESS_RECEIPT_STATES:
            continue
        # The caller validates the id/verb against the immutable sheet.
        out[n] = batch.ItemResult(
            n=n,
            id="lrn-00000000",
            verb="unknown",
            rc=int(match.group("rc") or 0),
            state=state,
        )
    return out


def _verify_mutation_commit(
    home: Path, sha: str, ref: execution_evidence.ExecutionRef, item: batch.SheetItem
) -> bool:
    """Require the candidate commit to contain the referenced record effect."""
    proc = gitops._git(  # noqa: SLF001 -- committed-effect verification
        home, "diff-tree", "--no-commit-id", "--name-only", "-r", sha
    )
    paths = [line for line in proc.stdout.splitlines() if line.endswith(f"{ref.record_id}.md")]
    if not paths:
        return False
    expected_status = {
        "route": "routed",
        "reject": "rejected",
        "defer": "deferred",
        "reopen": "pending",
        "undefer": "pending",
        "retire": "superseded",
        "supersede": "superseded",
    }.get(ref.verb)
    for rel in reversed(paths):
        shown = gitops._git(home, "show", f"{sha}:{rel}")  # noqa: SLF001
        if shown.returncode != 0:
            continue
        try:
            record = Record.from_text(shown.stdout)
        except RecordError:
            continue
        if expected_status is not None and record.status != expected_status:
            continue
        if item.verb == "route" and (record.routing or {}).get("destination") != item.fields.get("dest"):
            continue
        if item.verb in {"rehome", "rescope"} and record.scope != item.fields.get("to"):
            continue
        if item.verb == "retire" and record.superseded_by != f"covered_by:{item.fields.get('covered_by')}":
            continue
        if item.verb == "supersede" and record.superseded_by != item.fields.get("new_id"):
            continue
        if item.verb == "revise" and str(item.fields.get("text") or "") not in record.body:
            continue
        return True
    return False


def _recovered_items(
    home: Path,
    manifest: dict,
    case_id: str,
    recipe: dict,
    sheet: batch.Sheet,
) -> dict[int, batch.ItemResult]:
    completed = _committed_receipts(home, case_id, str(recipe["sheet_sha"]))
    by_n = {item.n: item for item in sheet}
    for n, item_result in list(completed.items()):
        item = by_n.get(n)
        if item is None:
            completed.pop(n, None)
            continue
        item_result.id = item.id
        item_result.verb = item.verb
    for item in sheet:
        if item.n in completed:
            continue
        ref = execution_evidence.ExecutionRef(
            run_id=str(manifest["run_id"]),
            case_id=case_id,
            sheet_sha=str(recipe["sheet_sha"]),
            sheet_digest=str(recipe["sheet_digest"]),
            item=item.n,
            record_id=item.id,
            verb=item.verb,
            actor="steward",
        )
        execution_evidence.validate_manifest_ref(manifest, ref)
        sha = execution_evidence.find_mutation_commit(
            home, ref, after=str(manifest["start_head"]), at="HEAD"
        )
        if sha is None:
            try:
                sha = execution_evidence.find_compound_proof_commit(
                    home, ref, after=str(manifest["start_head"]), at="HEAD"
                )
            except execution_evidence.ExecutionEvidenceError:
                sha = None
        if sha is None or not _verify_mutation_commit(home, sha, ref, item):
            continue
        if item.verb in {"route", "rehome", "rescope"}:
            host = verbs.recompile(home, no_push=True)
            skipped = [entry for entry in host.entries if entry.skipped]
            if skipped:
                first = skipped[0]
                completed[item.n] = batch.ItemResult(
                    n=item.n,
                    id=item.id,
                    verb=item.verb,
                    rc=1,
                    sha=sha,
                    state="unresolved-host",
                    detail=f"{first.target}: {first.skipped}",
                    evidence="ledger mutation proven; host result established by recompile",
                )
            else:
                completed[item.n] = batch.ItemResult(
                    n=item.n,
                    id=item.id,
                    verb=item.verb,
                    rc=0,
                    sha=sha,
                    state="applied",
                    evidence="ledger mutation and host result established by recompile",
                )
        else:
            completed[item.n] = batch.ItemResult(
                n=item.n,
                id=item.id,
                verb=item.verb,
                rc=0,
                sha=sha,
                state="applied",
                evidence=f"ledger mutation proven by commit {sha}",
            )
    return completed


def _write_recipe_stage(run_dir: Path, packet_index: int, case_id: str, recipe: dict) -> tuple[Path, Path]:
    stage = run_dir / "steward" / f"packet-{packet_index:04d}"
    case_path = stage / "cases" / f"{case_id}.yaml"
    sheet_path = stage / "sheets" / str(recipe["sheet_name"])
    case_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(case_path, str(recipe["case"]), fsync=True)
    fsops.atomic_write(sheet_path, str(recipe["sheet"]), fsync=True)
    return case_path, sheet_path


def _model_entries(home: Path) -> list[dict]:
    shown = user_model.show(home)
    return [
        {**entry, "container": container}
        for container, entries in (shown.get("containers") or {}).items()
        for entry in entries
    ]


def _maintenance_result(home: Path, operation: dict) -> dict | None:
    """Recognize an owner commit that landed before its manifest result."""
    payload = dict(operation["payload"])
    if operation["kind"] == "statement":
        source = payload.get("source")
        ref = source.get("message_ref") if isinstance(source, dict) else None
        matches = [
            row for row in statements.list_statements(home)
            if row.get("verbatim") == payload.get("verbatim")
            and row.get("source", {}).get("message_ref") == ref
        ]
        if len(matches) == 1:
            return {"state": "applied", "id": matches[0]["id"], "recovered": True}
        if len(matches) > 1:
            return {"state": "refused", "error": "ambiguous statement addition"}
    elif operation["kind"] == "model":
        action = payload.get("action", "add")
        if action == "add":
            baseline = set(operation.get("baseline") or [])
            matches = [
                row for row in _model_entries(home)
                if row.get("id") not in baseline
                and all(row.get(key) == value for key, value in payload.items()
                        if key not in {"action", "by", "held_since"})
            ]
            if len(matches) == 1:
                return {"state": "applied", "id": matches[0]["id"], "recovered": True}
            if len(matches) > 1:
                return {"state": "refused", "error": "ambiguous user-model addition"}
        elif action == "lapse":
            match = next((row for row in _model_entries(home) if row.get("id") == payload.get("id")), None)
            if match is not None and match.get("status") == "LAPSED":
                return {"state": "applied", "id": payload.get("id"), "recovered": True}
    elif operation["kind"] == "parked-case":
        reserved = operation.get("reserved_case_id")
        if any(row.get("case") == reserved for row in cases.list_cases(home, only_ok=True)):
            return {"state": "applied", "id": reserved, "recovered": True}
    return None


def _maintain_manifest(home: Path, run_id: str, packet_index: int) -> tuple[int, bool]:
    """Run committed maintenance operations, checkpointing each result."""
    refused = 0
    while True:
        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
        packet = manifest["packets"][packet_index - 1]
        operation = next(
            (row for row in packet.get("maintenance") or [] if row.get("state") not in {"applied", "refused"}),
            None,
        )
        if operation is None:
            return refused, False
        if operation["state"] == "pending":
            baseline = None
            if operation["kind"] == "model" and operation["payload"].get("action", "add") == "add":
                baseline = [row["id"] for row in _model_entries(home)]
            operation_id = operation["id"]
            _update_manifest(
                home, run_id, reason=f"maintenance start {operation_id}",
                update=lambda current, op_id=operation_id, value=baseline: next(
                    op for op in current["packets"][packet_index - 1]["maintenance"]
                    if op["id"] == op_id
                ).update(state="started", baseline=value),
            )
            continue
        recovered = _maintenance_result(home, operation)
        try:
            if recovered is None:
                payload = dict(operation["payload"])
                if operation["kind"] == "statement":
                    source = payload.get("source")
                    if not isinstance(source, dict):
                        raise statements.StatementUsageError("statement add: source must be a mapping")
                    ref = source.get("message_ref")
                    if not isinstance(ref, str) or not (
                        ref.startswith("transcript:") or ref.startswith("conversation:")
                    ):
                        raise statements.StatementUsageError(
                            "statement add: source.message_ref must be transcript:<session>#L<n> or conversation:<obs-id>"
                        )
                    recovered = {
                        "state": "applied",
                        "id": statements.add(home, verbatim=payload.get("verbatim", ""), source=source,
                            recorded_by="steward", answers=payload.get("answers"), scope=payload.get("scope"),
                            uncertainty=payload.get("uncertainty"), amends=payload.get("amends")),
                    }
                elif operation["kind"] == "model":
                    action = payload.pop("action", "add")
                    payload.pop("by", None)
                    if action == "add":
                        if payload.get("source") != "system-reading":
                            raise user_model.UserModelError(
                                "steward model updates may add provisional system readings only"
                            )
                        recovered = {"state": "applied", "id": user_model.add_entry(home, by="steward", **payload)}
                    elif action == "lapse":
                        entry_id = payload.pop("id", "")
                        user_model.lapse_entry(home, entry_id, by="steward", **payload)
                        recovered = {"state": "applied", "id": entry_id}
                    else:
                        raise user_model.UserModelUsageError(f"model-updates.yaml: unknown action {action!r}")
                else:
                    payload.update(kind="parked", outcome="parked", parked_for="overseer", run_id=run_id)
                    run_dir = _project_manifest(home, manifest)
                    stage_path = run_dir / f"maintenance-{operation['id']}.yaml"
                    _dump_yaml(stage_path, payload)
                    recovered = {
                        "state": "applied",
                        "id": cases.record(home, stage_path, actor="steward", reserved_id=operation["reserved_case_id"]),
                    }
        except intents.LedgerStoppedError as exc:
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                "status": "stopped", "error": str(exc)})
            return refused, True
        except (statements.StatementError, user_model.UserModelError, cases.CaseError, TypeError, ValueError) as exc:
            refused += 1
            recovered = {"state": "refused", "error": str(exc)}
            status = {"statement": "statement-refused", "model": "model-update-refused"}.get(
                operation["kind"], "parked-case-refused"
            )
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": status, "error": str(exc)})
        operation_id = operation["id"]
        assert recovered is not None
        _update_manifest(
            home, run_id, reason=f"maintenance result {operation_id}",
            update=lambda current, op_id=operation_id, result=recovered: next(
                op for op in current["packets"][packet_index - 1]["maintenance"]
                if op["id"] == op_id
            ).update(state=result["state"], result=result),
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


def _reconcile_runs(home: Path) -> list[dict]:
    """Discover and project unfinished work solely from committed manifests."""
    manifests = committed_manifests(home)
    for manifest in manifests:
        _project_manifest(home, manifest)
    manifest_run_ids = {row["run_id"] for row in manifests}
    for row in cases.list_cases(home, only_ok=True):
        if row.get("actor") != "steward":
            continue
        run_id = row.get("run_id")
        if run_id and run_id not in manifest_run_ids:
            _journal(home, {
                "ts": chrono.now_iso(), "status": "evidence-gap", "case": row.get("case"),
                "run_id": run_id, "error": "legacy steward case has no committed run manifest",
            })
    return [row for row in manifests if row.get("status") != "complete"]


def _apply_packet(home: Path, run_id: str, packet_index: int) -> tuple[list[str], int, int | None]:
    """Continue one prepared packet using its immutable committed recipes."""
    decided: list[str] = []
    refused = 0
    halt_code: int | None = None
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    dirty = _dirty_truth_paths(home)
    if dirty:
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dirty-refused",
            "paths": dirty, "error": "unexplained ledger paths refuse continuation"})
        return [], 0, 8
    run_dir = _project_manifest(home, manifest)
    packet = manifest["packets"][packet_index - 1]
    inputs = {row["record"]: row["version"] for row in packet["inputs"]}
    for case_id in packet.get("case_ids") or []:
        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
        recipe = manifest["cases"][case_id]
        if recipe.get("phase") in {"complete", "parked", "refused"}:
            continue
        case_path, sheet_path = _write_recipe_stage(run_dir, packet_index, case_id, recipe)
        case_data = _read_yaml(case_path)
        try:
            cases.record(home, case_path, actor="steward", reserved_id=case_id)
        except cases.CaseError as exc:
            refused_records = case_data.get("records") if isinstance(case_data, dict) else None
            refused += max(1, len(refused_records) if isinstance(refused_records, list) else 1)
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "refused",
                "stage_file": case_path.name, "error": str(exc)})
            _update_manifest(home, run_id, reason=f"case {case_id} refused", update=lambda current: (
                current["cases"][case_id].update(phase="refused", error=str(exc)),
                current["packets"][packet_index - 1]["dispositions"].update({
                    rid: {"state": "refused", "input_version": inputs[rid], "reason": str(exc)}
                    for rid in (refused_records or [])
                }),
            ))
            continue
        if isinstance(case_data, dict) and case_data.get("kind") == "reconsider":
            for rid in case_data.get("records") or []:
                verbs.reconsider(home, rid, case=case_id, by="steward", no_push=True)
        items = batch.load_sheet(sheet_path, home=home)
        if recipe.get("parking_reason") is not None:
            result = batch.BatchResult(
                items=[
                    batch.ItemResult(
                        n=item.n,
                        id=item.id,
                        verb=item.verb,
                        rc=0,
                        state="parked",
                        detail=f"parked for overseer: {recipe['parking_reason']}",
                    )
                    for item in items
                ],
                process_code=0,
                case=case_id,
                sheet_sha=items.sheet_sha,
                actor="steward",
            )
            receipt = batch.write_receipt(home, result, str(recipe["sheet_name"]), no_push=True, prefix=True)
            phase = "parked" if receipt and receipt.get("state") == "ok" else "unfinished"
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
                batch.write_receipt(home, result, str(recipe["sheet_name"]), no_push=True, prefix=True)
                phase = "refused"
            else:
                dirty = _dirty_truth_paths(home)
                if dirty:
                    _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                        "status": "dirty-refused", "paths": dirty,
                        "error": "unexplained ledger paths before batch dispatch"})
                    return list(dict.fromkeys(decided)), refused, 8
                continuation = batch.BatchContinuation(
                    run_id=run_id, case_id=case_id, sheet_digest=str(recipe["sheet_digest"]),
                    completed=_recovered_items(home, manifest, case_id, recipe, items),
                )
                checkpoint = lambda partial, name=str(recipe["sheet_name"]): batch.write_receipt(
                    home, partial, name, no_push=True, prefix=True
                )
                try:
                    result = batch.run(home, items, no_push=True, actor="steward",
                        continuation=continuation, checkpoint=checkpoint)
                    if result.items and all(
                        item.n in result.preserved_receipt_items for item in result.items
                    ):
                        receipt = {"state": "ok", "pushed": None}
                    else:
                        receipt = batch.write_receipt(
                            home, result, str(recipe["sheet_name"]), no_push=True, prefix=True
                        )
                    phase = "complete" if receipt and receipt.get("state") == "ok" else "unfinished"
                except batch.BookkeepingHalt as exc:
                    result = exc.result
                    phase = "unfinished"
                    halt_code = result.process_code or 8
        failed = [item for item in result.items if item.state in {"refused", "stopped", "not-attempted", "unresolved-host"}]
        refused += len(failed)
        successful = {item.id for item in result.items if item.state in _SUCCESS_RECEIPT_STATES}
        parked = recipe.get("parking_reason") is not None
        if not parked and phase == "complete":
            decided.extend(rid for rid in successful if all(
                item.id != rid or item.state in _SUCCESS_RECEIPT_STATES for item in result.items
            ))
        case_records = list(case_data.get("records") or []) if isinstance(case_data, dict) else []
        disposition_state = "parked" if parked else "applied" if phase == "complete" and not failed else "refused" if phase == "refused" else "unfinished"
        result_json = result.to_json()
        try:
            _update_manifest(home, run_id, reason=f"case {case_id} {disposition_state}", update=lambda current: (
                current["cases"][case_id].update(phase=phase, result=result_json),
                current["packets"][packet_index - 1]["dispositions"].update({
                    rid: {"state": disposition_state, "input_version": inputs[rid], "case": case_id}
                    for rid in case_records
                }),
            ))
        except gitops.GitOpsError as exc:
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dirty-refused",
                "paths": _dirty_truth_paths(home), "error": str(exc)})
            return list(dict.fromkeys(decided)), refused, 8
        if result.process_code in {5, 6, 7, 8} or result.stopped_at is not None or halt_code is not None:
            halt_code = result.process_code or halt_code or 8
            break
    return list(dict.fromkeys(decided)), refused, halt_code


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
        unfinished_runs = _reconcile_runs(home)
        reconsider, _reconsider_successors = _reconsider_proposals(home)
        reconsider_ids = {entry.record.id for entry, _proposal in reconsider}
        eligible = reconsider + [
            row for row in _eligible_proposals(home) if row[0].record.id not in reconsider_ids
        ]
        if not unfinished_runs and not eligible:
            result = RunResult("idle")
            _journal(home, {"ts": chrono.now_iso(), "status": result.status})
            return result

        # A19/A22 (S-68): this run has taken ownership — every hold
        # (`stopped`, `disabled`, a lock another process holds, nothing
        # eligible) has already returned above. The attempt is recorded
        # HERE, before anything that can raise, so the scheduler's
        # cooldown arms even for a run that then makes zero model calls or
        # dies. Before this, a run that failed before its first commit
        # left `last_attempt_at` untouched and was due again on the very
        # next 60-second tick. A dry run writes no attempt: it is a
        # rehearsal, and must not suppress the real run behind it.
        if not dry_run:
            _journal(home, {"ts": chrono.now_iso(), "status": "attempt-start"})

        packet_size_value, _source = settings.resolve_setting(
            home, settings.by_name("steward.packet_size")
        )
        max_turns_value, _source = settings.resolve_setting(
            home, settings.by_name("sdk.max_turns.steward")
        )
        packet_size = cast(int | str, packet_size_value)
        max_turns = cast(int | str, max_turns_value)
        if unfinished_runs:
            manifest = unfinished_runs[0]
            run_id = str(manifest["run_id"])
            run_dir = _project_manifest(home, manifest)
        else:
            run_id = "run-" + uuid.uuid4().hex[:12]
            run_dir = steward_dir(home) / "runs" / run_id
            run_dir.mkdir(parents=True)
            packet_count = math.ceil(len(eligible) / int(packet_size))
            packet_rows = []
            observations: list[str] = []
            for packet_index, start in enumerate(range(0, len(eligible), int(packet_size)), start=1):
                rows = eligible[start : start + int(packet_size)]
                inputs = []
                predecessors: dict[str, str] = {}
                for entry, proposal in rows:
                    if isinstance(entry, _QueuedProposal):
                        version = f"observation:{entry.observation_id}"
                        inputs.append({"path": entry.proposal_path.as_posix(), "blob": version,
                            "version": version, "record": entry.record.id, "proposal": proposal})
                        if entry.predecessor:
                            predecessors[entry.record.id] = entry.predecessor
                        if entry.observation_id:
                            observations.append(entry.observation_id)
                    else:
                        inputs.append(_input_identity(home, entry.proposal_path, entry.record.id, proposal))
                packet_rows.append({
                    "index": packet_index, "inputs": inputs, "records": [row["record"] for row in inputs],
                    "predecessors": predecessors, "phase": "pending", "attempts": [],
                    "repair_remaining": 1, "case_ids": [], "maintenance": [],
                    "dispositions": {}, "bound": None, "failure": None,
                })
            manifest = {
                "version": 1, "actor": "steward", "run_id": run_id,
                "started_at": chrono.now_iso(), "last_attempt_at": None,
                "completed_at": None, "status": "running", "outcome": None,
                "start_head": gitops.head_sha(home), "cases": {}, "packets": packet_rows,
                "inputs": [row for packet in packet_rows for row in packet["inputs"]],
                "reconsider_observations": observations, "coverage": _coverage_empty(),
                "ledger_effects": [],
            }
            if not dry_run:
                _publish_manifest(home, manifest, reason="selected inputs")
                manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
            run_record = dict(manifest)
            run_record["NOT_REPO_TRUTH"] = {
                "value": True,
                "disposition": "projection only; committed cases/runs manifest is recovery authority",
            }
            _write_json(run_dir / "run.json", run_record)
        result = RunResult("dry-run" if dry_run else "applied", run_id=run_id)
        halt_code: int | None = None
        packet_count = len(manifest["packets"])
        for packet_index in range(1, packet_count + 1):
            if not dry_run:
                manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
            packet_record = manifest["packets"][packet_index - 1]
            if packet_record.get("phase") in {"complete", "refused", "unfinished"}:
                continue
            proposals = [row["proposal"] for row in packet_record["inputs"]]
            stage = run_dir / "steward" / f"packet-{packet_index:04d}"
            stage.mkdir(parents=True, exist_ok=True)
            if packet_record.get("phase") not in {"prepared", "applying", "maintenance"}:
                context = steward_prompt.RunContext(
                    run_id=run_id, stage_dir=stage, packet_index=packet_index,
                    packet_count=packet_count, last_run_at=_completed_manifest_time(home),
                    verbs_the_runner_executes=("case record", "batch --dry-run", "batch", "case receipt",
                        "user-model", "statement add", "reconsider"),
                )
                prompt = steward_prompt.assemble(home, cache_dir(home), context, proposals)
                fsops.atomic_write(run_dir / f"packet-{packet_index:04d}.md", prompt.text, fsync=True)
                spec = _session_spec(home, run_dir, prompt.text, label=f"steward-{run_id}-{packet_index}")
                started = time.monotonic()
                if not dry_run:
                    _update_manifest(home, run_id, reason=f"packet {packet_index} invocation", update=lambda current: (
                        current.update(last_attempt_at=chrono.now_iso()),
                        current["packets"][packet_index - 1].update(phase="invoking"),
                    ))
                outcome = invocation.write_session(spec)
                duration = float(time.monotonic() - started)
                result.calls += 1
                attempt = {"kind": "decision", "turns": getattr(outcome, "turns", None),
                    "failure": outcome.failure, "duration_secs": duration}
                packet_record.setdefault("attempts", []).append(attempt)
                packet_record["duration_secs"] = duration
                if not outcome.ok or (
                    getattr(outcome, "turns", None) is not None
                    and getattr(outcome, "turns") >= int(max_turns)
                ):
                    packet_record["bound"] = "turns" if outcome.ok else outcome.failure or "invocation"
                    packet_record["phase"] = "unfinished"
                    packet_record["failure"] = packet_record["bound"]
                    for row in packet_record["inputs"]:
                        packet_record["dispositions"][row["record"]] = {
                            "state": "unfinished", "input_version": row["version"],
                            "reason": packet_record["bound"],
                        }
                    if not dry_run:
                        _publish_manifest(home, manifest if manifest["packets"][packet_index - 1] is packet_record else execution_evidence.read_manifest(home, run_id, at="HEAD"), reason=f"packet {packet_index} unfinished")
                        # Reapply the local outcome when invocation-start was committed first.
                        _update_manifest(home, run_id, reason=f"packet {packet_index} bound", update=lambda current: current["packets"][packet_index - 1].update(packet_record))
                    continue
                try:
                    _validate_and_prepare_stage(stage, set(packet_record["records"]))
                except ValueError as first_error:
                    if packet_record.get("repair_remaining", 0) <= 0:
                        second_error = first_error
                    else:
                        packet_record["repair_remaining"] = 0
                        if not dry_run:
                            _update_manifest(home, run_id, reason=f"packet {packet_index} repair allowance", update=lambda current: current["packets"][packet_index - 1].update(repair_remaining=0))
                        repair_started = time.monotonic()
                        repair = invocation.write_session(_repair_spec(spec, str(first_error)))
                        result.calls += 1
                        packet_record["attempts"].append({"kind": "repair", "failure": repair.failure,
                            "duration_secs": float(time.monotonic() - repair_started)})
                        try:
                            if not repair.ok:
                                raise ValueError(repair.detail or repair.failure or "repair invocation failed")
                            _validate_and_prepare_stage(stage, set(packet_record["records"]))
                            second_error = None
                        except ValueError as exc:
                            second_error = exc
                    if second_error is not None:
                        packet_record.update(phase="unfinished", bound="schema-repair", error=str(second_error))
                        for row in packet_record["inputs"]:
                            packet_record["dispositions"][row["record"]] = {
                                "state": "unfinished", "input_version": row["version"], "reason": str(second_error)}
                        if not dry_run:
                            _update_manifest(home, run_id, reason=f"packet {packet_index} schema unfinished", update=lambda current: current["packets"][packet_index - 1].update(packet_record))
                        continue
                if dry_run:
                    packet_record["phase"] = "complete"
                    continue
                manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
                manifest_packet = manifest["packets"][packet_index - 1]
                manifest_packet.update(packet_record)
                try:
                    _prepared_recipe(home, stage, manifest, manifest_packet)
                except ValueError as exc:
                    if "secret scan:" not in str(exc):
                        raise
                    refused_dispositions = {
                        row["record"]: {"state": "refused", "input_version": row["version"],
                            "reason": str(exc)}
                        for row in manifest_packet["inputs"]
                    }
                    _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                        "status": "refused", "error": str(exc)})
                    _update_manifest(home, run_id, reason=f"packet {packet_index} secret refusal",
                        update=lambda current: current["packets"][packet_index - 1].update(
                            phase="refused", failure=str(exc), dispositions=refused_dispositions))
                    continue
                _publish_manifest(home, manifest, reason=f"packet {packet_index} prepared recipe")
            if dry_run:
                continue
            packet_decided, packet_refused, packet_halt = _apply_packet(home, run_id, packet_index)
            result.decided.extend(packet_decided)
            result.refused += packet_refused
            if packet_halt is not None:
                halt_code = packet_halt
                break
            maintenance_refused, maintenance_halt = _maintain_manifest(home, run_id, packet_index)
            result.refused += maintenance_refused
            if maintenance_halt:
                halt_code = gitops.EXIT_GIT_FAILED
                break
            _update_manifest(home, run_id, reason=f"packet {packet_index} complete", update=lambda current: current["packets"][packet_index - 1].update(phase="complete"))

        if dry_run:
            run_record = dict(manifest)
            run_record["packets"] = manifest["packets"]
            run_record["status"] = "dry-run"
            run_record["coverage"] = _coverage_empty()
            run_record["NOT_REPO_TRUTH"] = {"value": True, "disposition": "dry-run cache projection only"}
            _write_json(run_dir / "run.json", run_record)
            return result

        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
        dirty = _dirty_truth_paths(home)
        if dirty:
            result.status = "partial"
            result.unfinished = [
                row["record"] for packet in manifest["packets"]
                for row in packet["inputs"]
                if row["record"] not in packet.get("dispositions", {})
                or packet["dispositions"][row["record"]].get("state") == "unfinished"
            ]
            _project_manifest(home, manifest)
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dirty-refused",
                "paths": dirty, "unfinished": result.unfinished})
            return result
        dispositions = [value for packet in manifest["packets"] for value in packet.get("dispositions", {}).values()]
        applied_ids = [rid for packet in manifest["packets"] for rid, value in packet.get("dispositions", {}).items() if value.get("state") == "applied"]
        result.decided = list(dict.fromkeys(applied_ids))
        result.unfinished = [
            row["record"] for packet in manifest["packets"] for row in packet["inputs"]
            if row["record"] not in packet.get("dispositions", {})
            or packet["dispositions"][row["record"]].get("state") == "unfinished"
        ]
        maintenance_refused_total = sum(
            1 for packet in manifest["packets"] for op in packet.get("maintenance", []) if op.get("state") == "refused"
        )
        result.refused = sum(1 for value in dispositions if value.get("state") == "refused") + maintenance_refused_total
        coverage = _coverage_empty()
        for recipe in manifest.get("cases", {}).values():
            case_data = YAML(typ="safe").load(recipe["case"])
            if isinstance(case_data, dict):
                key = f"{case_data.get('outcome')}:{_scope_bucket(case_data.get('scope'))}"
                if key in coverage:
                    coverage[key] += 1
        result.coverage = coverage
        has_applied = bool(result.decided)
        has_unfinished = bool(result.unfinished) or halt_code is not None
        has_refused = result.refused > 0
        if halt_code == gitops.EXIT_GIT_FAILED:
            result.status = "partial" if has_applied else "stopped"
        elif has_unfinished or (has_applied and has_refused):
            result.status = "partial"
        elif has_refused:
            result.status = "refused"
        else:
            result.status = "applied"
        complete = not has_unfinished and all(packet.get("phase") in {"complete", "refused"} for packet in manifest["packets"])
        finished = chrono.now_iso()
        if halt_code == gitops.EXIT_GIT_FAILED:
            _project_manifest(home, manifest)
            _journal(home, {"ts": finished, "run_id": run_id, "status": result.status,
                "stopped": True, "decided": len(result.decided), "unfinished": result.unfinished})
            return result
        _update_manifest(home, run_id, reason="run complete" if complete else "run partial", update=lambda current: current.update(
            status="complete" if complete else "unfinished", outcome=result.status,
            completed_at=finished if complete else None, coverage=coverage,
            decided=result.decided, refused=result.refused, unfinished=result.unfinished,
        ))
        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
        _project_manifest(home, manifest)
        if complete:
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
                "unfinished": result.unfinished,
                "coverage": result.coverage,
            },
        )
        return result
