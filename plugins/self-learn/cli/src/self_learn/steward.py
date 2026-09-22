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
import shutil
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
    conditions,
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
from .overseer import notify as overseer_notify
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
    #: S-68 ruling 2: the records this run closed out at `runs.attempt_cap`,
    #: each carrying a parked successor case the overseer will decide.
    abandoned: list[str] = field(default_factory=list)
    #: The non-record units a close-out DROPPED — a case recipe left in a
    #: non-terminal phase, or a maintenance operation never settled. A packet
    #: can reach the cap with every input already disposed and still be open
    #: because of one of these; the close-out then stamps it `abandoned` with
    #: zero abandoned RECORDS, which used to leave the run reporting
    #: `applied` and exit 0 over work that was silently dropped.
    abandoned_units: list[str] = field(default_factory=list)
    #: The short cause when this run could NOT write its close-out, `None`
    #: when there was nothing to close or it landed. A close-out is retried
    #: without a count, so nothing caps it; this field, the text line, the
    #: `--json` envelope and one notification per distinct cause are what
    #: keep a permanently failing close-out from becoming a silent loop.
    close_out_error: str | None = None
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

#: A case recipe nothing will ever re-drive — exactly the set
#: :func:`_apply_packet` skips when it resumes a packet.
_TERMINAL_CASE_PHASES = frozenset({"complete", "parked", "refused"})
#: A packet a later run must never pick up again (A20/A21, S-68). `complete`
#: is in here, which is precisely why it is now stamped ONLY when every one
#: of the packet's units is itself terminal: before that gate, a failed
#: receipt write stamped the packet `complete` over a case left `unfinished`,
#: later runs skipped it, and the run stayed unfinished forever.
_TERMINAL_PACKET_PHASES = frozenset({"complete", "refused", "abandoned"})
#: Phases meaning "the model has already produced this packet's frozen
#: recipe". Resuming one of these re-drives the ledger work with NO model
#: call; any other phase (`pending`, `invoking` from a killed run,
#: `unfinished` from a failed one) gets a fresh session.
_MODEL_DONE_PHASES = frozenset({"prepared", "applying", "maintenance"})
#: Ordered so a comparison can answer S-68's PROGRESS question — "did this
#: unit move TOWARD a terminal value", never "did HEAD move".
_PACKET_PHASE_RANK = {
    "pending": 0, "invoking": 0, "unfinished": 0,
    "prepared": 1, "applying": 2, "maintenance": 3,
    "complete": 4, "refused": 4, "abandoned": 4,
}
#: 02-schema §3a: `failure_detail` is at most 2,000 characters, truncated
#: with a trailing ellipsis, and secret-scanned on write.
_FAILURE_DETAIL_MAX = 2000
_REDACTED_DETAIL = "<redacted: secret-scan>"
#: 02-schema §3a: two `parked_reason` values are written by a RUNNER and
#: are never the model's to choose -- `plain-host-committed-file`, which
#: `_forced_parking_reason` assigns AFTER the model's output is validated,
#: and `attempts-exhausted`, which only the close-out writes. A model that
#: wrote either would be telling the overseer "the machinery stopped me,
#: decide this yourself" about a decision it had in fact made, and
#: `cases.record` cannot tell the two writers apart -- it is the verb the
#: runner itself calls. So the check belongs here, on the model's own
#: staged output, where its remedy is the ordinary one repair turn.
#: ONE set, shared with the brief that tells the model not to write them
#: (`steward_prompt._render_output_contract`).
_RUNNER_ONLY_PARKED_REASONS = steward_prompt.RUNNER_ONLY_PARKED_REASONS
#: ... and the reasons the model MAY park a lesson with: every other one.
_MODEL_PARKED_REASONS = cases.PARKED_REASONS - _RUNNER_ONLY_PARKED_REASONS
_NO_PROGRESS_DETAIL = (
    "the attempt ran and moved no disposition, case phase, packet phase or "
    "maintenance state of this packet toward a terminal value"
)


def _failure_detail(text: object) -> str | None:
    """The message the transport or the validator actually returned.

    02-schema §3a: bounded at :data:`_FAILURE_DETAIL_MAX`, secret-scanned
    on write, and a scan hit REDACTS rather than suppresses — "a trace is
    never suppressed by its own content, because a failure whose reason
    lives only in the git-ignored cache journal is the state this field
    exists to end" (A23: the 2026-09-14 outage committed `exit` and kept
    the API's own sentence in the cache). Newlines are folded to spaces so
    one committed field stays one readable line and can never present a
    heading-shaped line to `cases.record`'s free-text checks.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    if secret_scan(raw):
        return _REDACTED_DETAIL
    # A leading '#' would render as a heading-shaped line in the parked
    # case the close-out writes from this text, which `cases.record`
    # refuses outright -- and a refused close-out is the very state S-68
    # exists to end.
    flat = " ".join(raw.split()).lstrip("#").strip()
    if not flat:
        return None
    if len(flat) > _FAILURE_DETAIL_MAX:
        return flat[: _FAILURE_DETAIL_MAX - 1] + "…"
    return flat


def _attempt_count(packet: dict) -> int:
    """How many attempts this packet has had (02-schema §3a).

    "A run record written before this rule has no `attempt_count`, and one
    is never invented for it: its count is DERIVED from the evidence the
    record already carries — for a steward packet, the number of rows of
    kind `decision` in that packet's own `attempts` list." The run left
    stuck on 2026-09-14 is exactly that shape.
    """
    value = packet.get("attempt_count")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return sum(
        1
        for row in packet.get("attempts") or []
        if isinstance(row, dict) and row.get("kind") == "decision"
    )


def _non_terminal_records(packet: dict) -> list[str]:
    dispositions = packet.get("dispositions") or {}
    return [
        row["record"]
        for row in packet.get("inputs") or []
        if (dispositions.get(row["record"]) or {}).get("state") not in _TERMINAL_DISPOSITIONS
    ]


def _packet_units_terminal(manifest: dict, packet: dict) -> bool:
    """A20/A21: every input disposed, every case recipe finished, every
    maintenance operation settled. Anything less and the packet is NOT
    stamped `complete`, so the next run re-drives it (the receipt write is
    idempotent by `(sheet_sha, item)` key, so re-driving it is safe)."""
    dispositions = packet.get("dispositions") or {}
    for row in packet.get("inputs") or []:
        if (dispositions.get(row["record"]) or {}).get("state") not in _TERMINAL_DISPOSITIONS:
            return False
    recipes = manifest.get("cases") or {}
    for case_id in packet.get("case_ids") or []:
        if (recipes.get(case_id) or {}).get("phase") not in _TERMINAL_CASE_PHASES:
            return False
    for operation in packet.get("maintenance") or []:
        if operation.get("state") not in {"applied", "refused"}:
            return False
    return True


def _progress_signature(manifest: dict, packet_index: int) -> dict[str, int]:
    """S-68 PROGRESS, as a per-unit rank the caller can compare.

    A key absent from the "before" reading counts as 0, so a unit that did
    not exist at the start of the attempt and exists now IS progress. This
    is deliberately not "HEAD moved": the steward's stall leaves HEAD
    perfectly still (a byte-identical publish returns early) while the
    overseer's moves it on every run.
    """
    packet = manifest["packets"][packet_index - 1]
    recipes = manifest.get("cases") or {}
    signature = {"packet": _PACKET_PHASE_RANK.get(str(packet.get("phase")), 0)}
    for record_id, value in (packet.get("dispositions") or {}).items():
        state = (value or {}).get("state") if isinstance(value, dict) else None
        signature[f"disposition:{record_id}"] = 2 if state in _TERMINAL_DISPOSITIONS else 1
    for case_id in packet.get("case_ids") or []:
        phase = (recipes.get(case_id) or {}).get("phase")
        signature[f"case:{case_id}"] = 2 if phase in _TERMINAL_CASE_PHASES else 1
    for operation in packet.get("maintenance") or []:
        state = operation.get("state")
        signature[f"maintenance:{operation.get('id')}"] = (
            2 if state in {"applied", "refused"} else 1
        )
    return signature


def _made_progress(before: dict[str, int], after: dict[str, int]) -> bool:
    return any(value > before.get(key, 0) for key, value in after.items())


def _reattempt_packet(packet: dict) -> None:
    """S-68 ruling 1: a later run re-attempts a bound packet "as a FRESH
    attempt with its OWN single repair turn". The reset is committed with
    the attempt-start increment, so a crash cannot leave a packet claiming
    a repair turn it already spent. Dispositions that already reached a
    terminal state are KEPT — only the unfinished ones are cleared."""
    packet.update(
        phase="invoking",
        bound=None,
        failure=None,
        failure_detail=None,
        repair_remaining=1,
    )
    packet.pop("error", None)
    dispositions = packet.get("dispositions") or {}
    packet["dispositions"] = {
        record_id: value
        for record_id, value in dispositions.items()
        if isinstance(value, dict) and value.get("state") in _TERMINAL_DISPOSITIONS
    }


def _start_attempt(
    manifest: dict, packet_index: int, *, attempt: int, at: str, fresh: bool
) -> None:
    """02-schema §3a: `attempt_count` increments ONCE at the START of every
    attempt, committed with `last_attempt_at` BEFORE the first model call,
    "so an attempt that makes zero calls, raises, or is killed still
    counts". The run-level stamp is what `serve._steward_is_due` reads."""
    manifest["last_attempt_at"] = at
    packet = manifest["packets"][packet_index - 1]
    packet["attempt_count"] = attempt
    packet["last_attempt_at"] = at
    if fresh:
        _reattempt_packet(packet)


def _record_failure(
    manifest: dict,
    packet_index: int,
    *,
    attempts: list,
    phase: str,
    failure: str,
    detail: str | None,
    duration: float | None,
    dispositions: dict,
    error: str | None = None,
) -> None:
    """A2: every failure path changes NAMED fields on the record just read
    from HEAD. The publish it replaces wrote a whole pre-invocation copy
    back over HEAD, which rewound `last_attempt_at` to null and made the
    scheduler think the run was due again on the very next tick."""
    packet = manifest["packets"][packet_index - 1]
    packet["attempts"] = list(attempts)
    packet["phase"] = phase
    packet["bound"] = failure
    packet["failure"] = failure
    packet["failure_detail"] = detail
    if duration is not None:
        packet["duration_secs"] = duration
    if error is not None:
        packet["error"] = error
    packet.setdefault("dispositions", {}).update(dispositions)


def _finish_packet_attempt(
    manifest: dict, packet_index: int, *, terminal: bool, progressed: bool, at: str
) -> None:
    """Close one attempt on the record: stamp `progress_at`, stamp
    `complete` only when every unit of the packet is terminal (A20/A21),
    and otherwise record S-68's generic guard — an attempt that ran and
    moved nothing is a failed attempt, so a trap nobody thought of still
    reaches the cap instead of spinning."""
    packet = manifest["packets"][packet_index - 1]
    if progressed:
        packet["progress_at"] = at
    if terminal:
        packet["phase"] = "complete"
        return
    if progressed:
        return
    packet["failure"] = "no-progress"
    packet["failure_detail"] = _NO_PROGRESS_DETAIL
    dispositions = packet.setdefault("dispositions", {})
    for row in packet.get("inputs") or []:
        record_id = row["record"]
        value = dispositions.get(record_id)
        if isinstance(value, dict) and value.get("state") in _TERMINAL_DISPOSITIONS:
            continue
        updated = dict(value) if isinstance(value, dict) else {}
        updated.update(
            state="unfinished", input_version=row["version"], reason="no-progress"
        )
        dispositions[record_id] = updated


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
    for case_path in case_files:
        case_data = _read_yaml(case_path)
        if not isinstance(case_data, dict):
            continue
        reason = case_data.get("parked_reason")
        if reason in _RUNNER_ONLY_PARKED_REASONS:
            # Validated on what the MODEL wrote: `_forced_parking_reason`
            # assigns `plain-host-committed-file` later, in
            # `_prepared_recipe`, and is untouched by this.
            raise ValueError(
                f"{case_path.name}: parked_reason {reason!r} is written by the "
                "runner, never chosen here -- park with the reason that names "
                "the values question this case raises for the overseer"
            )
        # A case the model parks is honoured by `_prepared_recipe` (its
        # sheet is recorded, never applied), so what makes it a parked
        # case is checked HERE, where the remedy is the one repair turn --
        # `cases.record` would refuse the same things only at apply time.
        parks = case_data.get("kind") == "parked"
        if parks and reason not in _MODEL_PARKED_REASONS:
            raise ValueError(
                f"{case_path.name}: a parked case needs parked_reason, one of "
                f"{sorted(_MODEL_PARKED_REASONS)}; got {reason!r}"
            )
        if not parks and (reason is not None or case_data.get("parked_for") is not None):
            raise ValueError(
                f"{case_path.name}: parked_reason/parked_for are only for a case "
                "whose kind is parked"
            )
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
    # Only now that every sheet has passed its own shape check (so a
    # malformed sheet gets `load_sheet`'s precise error, not this one):
    for case_path in case_files:
        case_data = _read_yaml(case_path)
        if not isinstance(case_data, dict):
            continue
        # Every lesson a case covers needs its own item on that case's
        # sheet. The runner dispositions every lesson of a finished case
        # `applied`, so a lesson with no item was recorded as handled with
        # nothing done to it (seen in the real run of 2026-09-19: a
        # two-lesson case, one item).
        sheet_data = _read_yaml(stage / "sheets" / case_path.name)
        items = sheet_data.get("items") if isinstance(sheet_data, dict) else None
        item_ids = {
            item.get("id") for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        }
        without_item = [
            str(rid) for rid in (case_data.get("records") or []) if rid not in item_ids
        ]
        if without_item:
            raise ValueError(
                f"{case_path.name}: every lesson in a case needs its own item in "
                f"sheets/{case_path.name}; no item for {without_item}"
            )


def _session_spec(
    home: Path, run_dir: Path, prompt: str, *, label: str, lessons: int = 1
) -> invocation.SessionSpec:
    timeout_value, _source = settings.resolve_setting(
        home, settings.by_name("steward.timeout_secs")
    )
    timeout = cast(int | float | str, timeout_value)
    per_lesson_value, _source = settings.resolve_setting(
        home, settings.by_name("steward.turns_per_lesson")
    )
    per_lesson = int(cast(int | str, per_lesson_value))
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
        # U4b (2026-09-19): `cwd` is the packet's stage directory --
        # where the session runs and the only place it may write -- and
        # carries no `config.yaml`. The seam reads its settings (the
        # Claude Code binary, the model, the turn bound, the spend
        # bound, the provider, the backend) from THIS field instead.
        ledger_home=home,
        # The turn limit grows with the batch: `steward.turns_per_lesson`
        # for each lesson in it (the user's instruction, 2026-09-19). It
        # stops a runaway session; it is never a reason to discard one
        # that finished.
        max_turns=per_lesson * max(lessons, 1),
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
        # Carried, not re-derived: a field-by-field rebuild that dropped
        # this would send the repair round -- the SECOND call of the
        # same packet -- back to the SDK's bundled binary (U4b).
        ledger_home=spec.ledger_home,
        # Carried for the same reason: dropped, the repair round would
        # fall back to the per-surface limit instead of the batch's own.
        max_turns=spec.max_turns,
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
        if parking_reason is None and case_data.get("kind") == "parked":
            # The MODEL parked this case (method section 12): it could not
            # decide alone. Until 2026-09-20 only the runner's own two
            # checks above set a parking reason, so a case the model
            # parked was recorded as a question for the overseer AND had
            # its sheet applied in the same run. Its sheet now takes the
            # path every parked case takes: each item is receipted
            # `parked`, nothing is dispatched, and the lesson stays
            # pending for the overseer. The sheet is the model's
            # tentative answer, on record and not acted on. The reason
            # was checked by `_validate_declared_stage`. When the runner's
            # own check fires too (a hook route), its reason wins: that is
            # the one the overseer's hook intake sorts on.
            parking_reason = str(case_data.get("parked_reason"))
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


# ------------------------------------------- close-out (S-68 ruling 2)
#
# Deliberately module-level functions, not closures inside `run`: the lock
# invariant's walker treats a nested closure as its own node, and these
# reach the ledger only through the lock-owning `cases.record` /
# `cases.observe` verbs and `_update_manifest`.


def _packet_line_span(text: str, packet_index: int) -> tuple[int, int]:
    """The 1-based line span of one packet object inside the committed
    manifest, for the `#L<a>-<b>` half of the parked case's evidence
    reference. This module writes that file itself
    (`json.dumps(..., indent=2, sort_keys=True)`), so a packet object
    always opens on a line of exactly four spaces and a brace."""
    lines = text.splitlines()
    inside = False
    seen = 0
    start: int | None = None
    for number, line in enumerate(lines, start=1):
        if not inside:
            if line.strip() == '"packets": [':
                inside = True
            continue
        if line.startswith("  ]"):
            break
        if line.startswith("    {"):
            seen += 1
            start = number
        elif line.startswith("    }") and start is not None:
            if seen == packet_index:
                return start, number
            start = None
    return 1, max(1, len(lines))


def _record_scope(home: Path, record_id: str) -> str:
    """The abandoned record's own scope, for the parked case's section 1."""
    try:
        path = ledger_ops.find_record_path(home, record_id)
        scope = Record.from_text(path.read_text(encoding="utf-8")).scope
    except (ledger_ops.LedgerOpsError, RecordError, OSError):
        return "unknown"
    return str(scope or "unknown")


def _successor_case_for(home: Path, run_id: str, record_id: str) -> str | None:
    """02-schema §3a: "a successor that already exists is reused, never
    duplicated". Looked up from committed cases rather than matched on
    content, because the evidence reference names HEAD and HEAD moves."""
    for row in cases.list_cases(
        home, only_ok=True, record_id=record_id, parked_reason="attempts-exhausted"
    ):
        if row.get("actor") != "steward" or list(row.get("records") or []) != [record_id]:
            continue
        case_id = str(row.get("case") or "")
        try:
            view = cases.show(home, case_id, evidence_only=False)
        except cases.CaseError:
            continue
        if view.frontmatter.get("run_id") == run_id:
            return case_id
    return None


def _observe_abandonment(home: Path, case_id: str, record_id: str, successor: str) -> None:
    """When the abandoned item already belongs to a case, §3a.2 section 6
    gets an `abandoned` later observation naming the successor. The
    reserved id and the fixed text make a retry idempotent."""
    reserved = "obs-" + hashlib.sha256(
        f"{case_id}:{record_id}:{successor}".encode("utf-8")
    ).hexdigest()[:8]
    cases.observe(
        home,
        case_id,
        "abandoned",
        text=(
            f"{record_id} reached the steward's attempt cap without being "
            f"decided; parked for the overseer as {successor}"
        ),
        by="steward",
        reserved_id=reserved,
    )


class CloseOutIncomplete(Exception):
    """A close-out that could not give every waiting record its successor.

    Raised AFTER whatever did land has been committed, so the next run
    retries only the remainder (S-68 / 02-schema §3a: retried, idempotent,
    and counting nothing of its own).
    """


def _short_cause(exc: BaseException) -> str:
    """One bounded line naming a failure, stable enough across runs to be
    the key the once-per-distinct-cause notification dedupes on."""
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text if len(text) <= 240 else text[:239] + "…"


def _close_out_hold_path(home: Path) -> Path:
    return steward_dir(home) / "close-out-hold.json"


def _read_close_out_hold(home: Path) -> str | None:
    """The cause the user was last told about. Cache-side on purpose: it
    governs only whether to repeat a notification, never what the ledger
    says, and losing it costs one duplicate notification, not a lesson."""
    try:
        data = json.loads(_close_out_hold_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cause = data.get("cause") if isinstance(data, dict) else None
    return cause if isinstance(cause, str) else None


def _write_close_out_hold(home: Path, cause: str | None) -> None:
    path = _close_out_hold_path(home)
    if cause is None:
        path.unlink(missing_ok=True)
        return
    _write_json(path, {
        "NOT_REPO_TRUTH": {
            "value": True,
            "disposition": (
                "XDG cache: the last close-out cause the user was notified "
                "about; never recovery authority"
            ),
        },
        "cause": cause,
        "at": chrono.now_iso(),
    })


def _records_waiting_for_close_out(
    home: Path, run_id: str, attempt_cap: int
) -> list[str]:
    """Every record a failing close-out is holding, for the notification."""
    try:
        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    except Exception:  # noqa: BLE001 -- a count for a message, never a decision
        return []
    waiting: list[str] = []
    for packet in manifest.get("packets") or []:
        if packet.get("phase") in _TERMINAL_PACKET_PHASES:
            continue
        if _attempt_count(packet) < attempt_cap:
            continue
        waiting.extend(_non_terminal_records(packet))
    return list(dict.fromkeys(waiting))


def _notify_close_out_failure(
    home: Path, run_id: str, waiting: list[str], cause: str
) -> None:
    """Once per DISTINCT cause. A close-out is retried with no count of its
    own, so a deterministic failure would otherwise repeat forever with a
    git-ignored cache line as its only trace -- the silent loop S-68
    exists to end, one step further on."""
    summary = (
        f"self-learn steward: run {run_id} cannot close itself out — "
        f"{len(waiting)} lesson(s) are waiting for a parked case and the "
        f"write keeps failing: {cause}"
    )
    try:
        overseer_notify.send(home, "routine", summary, list(waiting))
    except Exception as exc:  # noqa: BLE001 -- a notification never fails a run
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
            "status": "notify-failed", "error": _short_cause(exc)})


def _dropped_units(manifest: dict, packet: dict) -> list[str]:
    """The packet's non-record units a close-out would abandon: a case recipe
    still in a non-terminal phase, and a maintenance operation never settled.

    `_packet_units_terminal` already counts these as reasons a packet is not
    complete; this names them, so a close-out that drops one can say so
    instead of stamping `abandoned` with nothing to show.

    A case left `unfinished` because the ledger kept refusing one of its
    records is not dropped: that record is what the close-out parks, and
    its successor case names this one (`_observe_abandonment`). Only a
    non-terminal case none of whose records the close-out will park -- its
    records all decided, the recipe itself never finished -- is a unit with
    nothing to show for it.
    """
    recipes = manifest.get("cases") or {}
    waiting = set(_non_terminal_records(packet))
    dispositions = packet.get("dispositions") or {}
    owned: dict[str, list[str]] = {}
    for record_id, row in dispositions.items():
        if isinstance(row, dict) and isinstance(row.get("case"), str):
            owned.setdefault(row["case"], []).append(record_id)
    dropped = [
        f"case {case_id} ({(recipes.get(case_id) or {}).get('phase') or 'unknown'})"
        for case_id in packet.get("case_ids") or []
        if (recipes.get(case_id) or {}).get("phase") not in _TERMINAL_CASE_PHASES
        and not any(record_id in waiting for record_id in owned.get(case_id, []))
    ]
    dropped.extend(
        f"maintenance {operation.get('id')} ({operation.get('state') or 'pending'})"
        for operation in packet.get("maintenance") or []
        if operation.get("state") not in {"applied", "refused"}
    )
    return dropped


def _apply_close_out(
    manifest: dict,
    packet_index: int,
    *,
    dispositions: dict,
    kind: str,
    detail: str,
    complete: bool,
    dropped: list[str] | None = None,
) -> None:
    packet = manifest["packets"][packet_index - 1]
    packet["failure"] = kind
    packet["failure_detail"] = detail
    packet.setdefault("dispositions", {}).update(dispositions)
    if dropped:
        packet["abandoned_units"] = list(dropped)
    if complete:
        packet["phase"] = "abandoned"


def _ledger_refusals(manifest: dict, packet: dict, record_id: str) -> list[str]:
    """The ledger's own words for why this record's sheet items did not
    apply, read from the case results the packet's attempts committed
    (`_apply_packet` stores every `BatchResult` on its case recipe)."""
    out: list[str] = []
    recipes = manifest.get("cases") or {}
    for case_id in packet.get("case_ids") or []:
        result = (recipes.get(case_id) or {}).get("result") or {}
        for item in result.get("items") or []:
            if not isinstance(item, dict) or item.get("id") != record_id:
                continue
            if item.get("state") in _SUCCESS_RECEIPT_STATES:
                continue
            text = str(item.get("detail") or item.get("state") or "").strip()
            if not text:
                continue
            line = f"{item.get('verb')} {record_id}: {text[:240]}"
            if line not in out:
                out.append(line)
    return out


def _close_out_detail(manifest: dict, packet: dict, record_id: str, detail: str) -> str:
    """S-68 ruling 2: the parked case carries the REAL failure reason. When
    a packet reached the cap as `no-progress` because the ledger refused
    the same sheet item every night, the real reason is the ledger's
    refusal text, not the generic guard sentence."""
    refusals = _ledger_refusals(manifest, packet, record_id)
    if not refusals:
        return detail
    return f"{detail}; the ledger refused: " + "; ".join(refusals)


def _close_out_packet(home: Path, run_id: str, packet_index: int) -> list[str]:
    """Close one exhausted packet: a parked case per undecided record, the
    `abandoned` disposition naming it, and the packet phase.

    Ruling 2, and 02-schema §3a's shape for it. The packet becomes
    `abandoned` — and so the run can complete and a NEW run can start —
    only once every abandoned item's `successor_case` actually exists, so
    a close-out whose ledger write fails is simply retried by the next
    run, with no count of its own.
    """
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    packet = manifest["packets"][packet_index - 1]
    attempts = _attempt_count(packet)
    kind = str(packet.get("failure") or packet.get("bound") or "no-progress")
    detail = str(packet.get("failure_detail") or kind)
    versions = {row["record"]: row["version"] for row in packet.get("inputs") or []}
    relative = f"cases/runs/{run_id}.json"
    committed = gitops._git(home, "show", f"HEAD:{relative}")  # noqa: SLF001
    first, last = _packet_line_span(committed.stdout, packet_index)
    reference = f"ledger@{gitops.head_sha(home)}:{relative}#L{first}-{last}"
    run_dir = _project_manifest(home, manifest)
    dispositions: dict[str, dict] = {}
    closed: list[str] = []
    errors: list[str] = []
    waiting = _non_terminal_records(packet)
    dropped = _dropped_units(manifest, packet)
    for record_id in waiting:
        record_detail = _close_out_detail(manifest, packet, record_id, detail)
        try:
            successor = _close_out_record(
                home, run_dir, run_id, packet, packet_index, record_id,
                attempts=attempts, kind=kind, detail=record_detail, reference=reference,
            )
        except Exception as exc:  # noqa: BLE001 -- one record never blocks the rest
            # Per-record, so a single unwritable parked case cannot hold
            # every OTHER lesson of the same packet hostage for ever.
            errors.append(f"{record_id}: {_short_cause(exc)}")
            continue
        dispositions[record_id] = {
            "state": "abandoned",
            "input_version": versions.get(record_id),
            "attempts": attempts,
            "reason": record_detail,
            "successor_case": successor,
        }
        closed.append(record_id)
    _journal(home, {
        "ts": chrono.now_iso(), "run_id": run_id, "status": "abandoned",
        "packet": packet_index, "attempts": attempts, "failure": kind,
        "records": closed, "units": dropped, "errors": errors,
    })
    complete = not errors
    if dispositions or complete:
        # Whatever landed is committed even when part of the packet did
        # not, so the next run retries only the remainder. The packet
        # becomes `abandoned` only when every waiting record has its
        # `successor_case` (02-schema §3a).
        _update_manifest(
            home, run_id, reason=f"packet {packet_index} abandoned",
            update=lambda current: _apply_close_out(
                current, packet_index, dispositions=dispositions, kind=kind,
                detail=detail, complete=complete, dropped=dropped,
            ),
        )
    if errors:
        raise CloseOutIncomplete(
            f"packet {packet_index}: {len(errors)} of {len(waiting)} record(s) "
            f"could not be parked — " + "; ".join(errors)
        )
    return closed


def _close_out_record(
    home: Path,
    run_dir: Path,
    run_id: str,
    packet: dict,
    packet_index: int,
    record_id: str,
    *,
    attempts: int,
    kind: str,
    detail: str,
    reference: str,
) -> str:
    """Reuse or write one record's parked successor case, and name it on
    the case the record already belonged to. Returns the successor id."""
    successor = _successor_case_for(home, run_id, record_id)
    if successor is None:
        stage_path = run_dir / f"close-out-{packet_index:04d}-{record_id}.yaml"
        ledger_refused = "; the ledger refused: " in detail
        if ledger_refused:
            # The steward DID decide; the ledger would not take the items.
            question = (
                f"the steward decided {record_id} but the ledger refused the "
                f"decision's items on each of {attempts} attempts; decide this "
                "lesson yourself, using the recorded refusal as evidence (the "
                "steward's own case and sheet are on record beside it)"
            )
            because = (
                "what stopped the steward was the ledger, not the merits: "
                f"every attempt ended with {kind}, the item refused"
            )
        else:
            question = (
                f"the steward's decision for {record_id} reached the attempt "
                f"cap after {attempts} attempts without ever being decided; "
                "decide this lesson itself, using the recorded failure reason "
                "as evidence"
            )
            because = (
                "what stopped the steward was the machinery, not the "
                f"merits: every attempt ended with {kind}"
            )
        _dump_yaml(stage_path, {
            "kind": "parked",
            "trigger": "nightly",
            "outcome": "parked",
            "parked_for": "overseer",
            "parked_reason": "attempts-exhausted",
            "run_id": run_id,
            "records": [record_id],
            "scope": _record_scope(home, record_id),
            "question": question,
            "evidence": [{"ref": reference, "quote": detail}],
            "decision": {
                "because": because,
                "confidence": "provisional",
                "what_would_change": [
                    "the overseer decides this lesson itself on the record's "
                    "own evidence",
                ],
            },
            "dependencies": {
                "statements": [], "user_model": [], "conditions": [], "capabilities": [],
            },
        })
        successor = cases.record(home, stage_path, actor="steward")
    previous = (packet.get("dispositions") or {}).get(record_id) or {}
    owning_case = previous.get("case")
    if isinstance(owning_case, str) and owning_case != successor:
        _observe_abandonment(home, owning_case, record_id, successor)
    return successor


def _close_out_exhausted(home: Path, run_id: str, attempt_cap: int) -> list[str]:
    """Every packet at the cap that is still not terminal, closed by the
    RUNNER — never by the model, which by definition never produced
    anything for these records."""
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    closed: list[str] = []
    for packet in manifest.get("packets") or []:
        if packet.get("phase") in _TERMINAL_PACKET_PHASES:
            continue
        if _attempt_count(packet) < attempt_cap:
            continue
        closed.extend(_close_out_packet(home, run_id, int(packet["index"])))
    return closed


def _notify_abandoned(
    home: Path, run_id: str, manifest: dict, abandoned: list[str],
    units: list[str] | None = None,
) -> None:
    """Ruling 2's "the user is notified", ONCE per closed-out run (not once
    per record), through the shipped notification helper unchanged — this
    module never calls `notify-send` itself."""
    kinds = sorted({
        str(packet.get("failure") or packet.get("bound") or "no-progress")
        for packet in manifest.get("packets") or []
        if packet.get("phase") == "abandoned"
    })
    dropped = list(units or [])
    if not abandoned:
        # Every lesson WAS decided; what the cap dropped is bookkeeping. The
        # shared sentence ("0 lesson(s) parked ... decided none of them") is
        # simply false here, and this is the one line the user reads.
        summary = (
            f"self-learn steward: run {run_id} reached the attempt cap with "
            f"every lesson already decided, but dropped {len(dropped)} piece(s) "
            f"of bookkeeping without a successor: {', '.join(dropped)} "
            f"({', '.join(kinds) or 'unknown failure'})"
        )
    else:
        tail = f"; also dropped without a successor: {', '.join(dropped)}" if dropped else ""
        summary = (
            f"self-learn steward: {len(abandoned)} lesson(s) parked for the overseer "
            f"— run {run_id} reached the attempt cap and decided none of them "
            f"({', '.join(kinds) or 'unknown failure'}){tail}"
        )
    try:
        overseer_notify.send(home, "routine", summary, list(abandoned) or [run_id])
    except Exception as exc:  # noqa: BLE001 -- a notification never fails a run
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
            "status": "notify-failed", "error": str(exc)})


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
        # A25: `gitops.EXIT_GIT_FAILED`, not 8. `8` is `EXIT_BATCH_PARTIAL`,
        # which means "the ledger DID change"; nothing was written here, and
        # `run`'s own early return tests for EXIT_GIT_FAILED — so the literal
        # 8 meant the "git failed" branch almost never fired.
        return [], 0, gitops.EXIT_GIT_FAILED
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
            receipt_ok = bool(receipt and receipt.get("state") == "ok")
            phase = "parked" if receipt_ok else "unfinished"
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
                # The LEDGER refused here, not the steward: the decision
                # stands and the sheet could not be applied as the ledger
                # is tonight. S-68 treats that like any other non-merits
                # failure -- the next run re-drives the case (the preview's
                # reasons ride the case result), and at the cap the record
                # is parked for the overseer with those reasons. `refused`
                # is reserved for the steward's own refusals, which are
                # terminal; stamping it here made a ledger refusal drop the
                # record out of every later run while it was still pending
                # (lrn-351ba705, 2026-09-21, refused over a probe bug fixed
                # the next day).
                receipt_ok = False
                phase = "unfinished"
            else:
                dirty = _dirty_truth_paths(home)
                if dirty:
                    _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                        "status": "dirty-refused", "paths": dirty,
                        "error": "unexplained ledger paths before batch dispatch"})
                    return list(dict.fromkeys(decided)), refused, gitops.EXIT_GIT_FAILED
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
                    receipt_ok = bool(receipt and receipt.get("state") == "ok")
                    phase = "complete" if receipt_ok else "unfinished"
                except batch.BookkeepingHalt as exc:
                    result = exc.result
                    receipt_ok = False
                    phase = "unfinished"
                    halt_code = result.process_code or 8
        failed = [item for item in result.items if item.state in {"refused", "stopped", "not-attempted", "unresolved-host"}]
        refused += len(failed)
        if failed and phase == "complete":
            # The sheet ran to its end and is receipted, but an item the
            # ledger refused, or a STOP left undone, is not a finished
            # obligation. `complete` is skipped by every later run, so a
            # later run could never retry it; `unfinished` re-drives the
            # case -- the applied items come back from their receipts, the
            # rest are dispatched again -- until the cap parks what is left
            # (S-68 ruling 1: a failure that is not a judgment on the merits
            # is retried).
            phase = "unfinished"
        successful = {item.id for item in result.items if item.state in _SUCCESS_RECEIPT_STATES}
        # A record every one of whose sheet items applied is decided even
        # when another record's item in the same sheet was refused.
        settled = {rid for rid in successful if all(
            item.id != rid or item.state in _SUCCESS_RECEIPT_STATES for item in result.items
        )}
        parked = recipe.get("parking_reason") is not None
        if not parked and receipt_ok:
            decided.extend(settled)
        case_records = list(case_data.get("records") or []) if isinstance(case_data, dict) else []
        # Per record: `parked`, `applied` (its items are receipted as applied,
        # or the whole sheet applied cleanly), else `unfinished` -- never
        # `refused`: the steward's own refusals (`cases.CaseError`, above)
        # are the only terminal ones a runner stamps.
        dispositions = {
            rid: "parked" if parked
            else "applied" if receipt_ok and (not failed or rid in settled)
            else "unfinished"
            for rid in case_records
        }
        summary_state = "parked" if parked else "applied" if all(
            state == "applied" for state in dispositions.values()
        ) and not failed else "unfinished"
        result_json = result.to_json()
        try:
            _update_manifest(home, run_id, reason=f"case {case_id} {summary_state}", update=lambda current: (
                current["cases"][case_id].update(phase=phase, result=result_json),
                current["packets"][packet_index - 1]["dispositions"].update({
                    rid: {"state": state, "input_version": inputs[rid], "case": case_id}
                    for rid, state in dispositions.items()
                }),
            ))
        except gitops.GitOpsError as exc:
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dirty-refused",
                "paths": _dirty_truth_paths(home), "error": str(exc)})
            return list(dict.fromkeys(decided)), refused, gitops.EXIT_GIT_FAILED
        # Only a ledger STOP (5/6/7, "nothing written, safe to retry") or a
        # bookkeeping halt stops the cases behind this one. Exit 8 means
        # "some items applied, some refused" -- a finished sheet with a
        # known result, not a half-state -- and the later cases are other
        # lessons entirely; stopping on it left five prepared cases
        # undecided in the first real run (2026-09-21).
        if result.process_code in {5, 6, 7} or result.stopped_at is not None or halt_code is not None:
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
        attempt_cap_value, _source = settings.resolve_setting(
            home, settings.by_name("runs.attempt_cap")
        )
        packet_size = cast(int | str, packet_size_value)
        attempt_cap = int(cast(int | str, attempt_cap_value))
        feed_items: list[conditions.Item] | None = None  # built once, on the first model call
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
                    # 02-schema §3a, the attempt-counting fields.
                    "attempt_count": 0, "last_attempt_at": None,
                    "progress_at": None, "failure_detail": None,
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
            phase = str(packet_record.get("phase") or "")
            # A1 (S-68 ruling 1): `unfinished` has LEFT this skip set. A
            # packet whose model call failed, whose turn bound was hit, or
            # whose second schema validation failed is re-attempted here by
            # a LATER run; only a terminal phase is skipped. Before this,
            # `unfinished` was both "never retried" and "keeps the run
            # open", which is the exact state S-68 forbids.
            if phase in _TERMINAL_PACKET_PHASES:
                continue
            # S-68 ruling 2: at `runs.attempt_cap` the runner stops
            # attempting and `_close_out_exhausted` below the loop writes
            # the parked successor cases. Counting another attempt here
            # would also mean a close-out whose ledger write failed could
            # never be retried "with no count of its own" (02-schema §3a).
            attempts_made = _attempt_count(packet_record)
            if attempts_made >= attempt_cap:
                if dry_run:
                    # The rehearsal reports everything the real close-out
                    # would give up, not just the records: a packet can reach
                    # the cap with every lesson decided and only a case
                    # recipe or a maintenance operation left open.
                    result.abandoned.extend(_non_terminal_records(packet_record))
                    result.abandoned_units.extend(
                        _dropped_units(manifest, packet_record)
                    )
                continue
            needs_model = phase not in _MODEL_DONE_PHASES
            stage = run_dir / "steward" / f"packet-{packet_index:04d}"
            if needs_model:
                # A24: empty the stage before a fresh session. A re-attempt
                # used to validate the new session's files BESIDE the failed
                # session's leftovers.
                shutil.rmtree(stage, ignore_errors=True)
            stage.mkdir(parents=True, exist_ok=True)
            attempt_at = chrono.now_iso()
            attempt_no = attempts_made + 1
            if dry_run:
                if needs_model:
                    _reattempt_packet(packet_record)
            else:
                _update_manifest(
                    home, run_id, reason=f"packet {packet_index} attempt {attempt_no}",
                    update=lambda current: _start_attempt(
                        current, packet_index, attempt=attempt_no, at=attempt_at,
                        fresh=needs_model,
                    ),
                )
                manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
                packet_record = manifest["packets"][packet_index - 1]
            before = _progress_signature(manifest, packet_index)
            proposals = [row["proposal"] for row in packet_record["inputs"]]
            if needs_model:
                context = steward_prompt.RunContext(
                    run_id=run_id, stage_dir=stage, packet_index=packet_index,
                    packet_count=packet_count, last_run_at=_completed_manifest_time(home),
                    verbs_the_runner_executes=("case record", "batch --dry-run", "batch", "case receipt",
                        "user-model", "statement add", "reconsider"),
                )
                if feed_items is None:
                    # One conditions snapshot per run (plan §4.4), not one
                    # per packet: the feed gathers the report, the status
                    # probe and every host's HEAD, and a 29-lesson run
                    # rebuilt it three times for the same night.
                    feed_items = conditions.feed(home, cache_dir(home))
                prompt = steward_prompt.assemble(
                    home, cache_dir(home), context, proposals, conditions_items=feed_items,
                )
                fsops.atomic_write(run_dir / f"packet-{packet_index:04d}.md", prompt.text, fsync=True)
                spec = _session_spec(
                    home, run_dir, prompt.text,
                    label=f"steward-{run_id}-{packet_index}", lessons=len(proposals),
                )
                started = time.monotonic()
                outcome = invocation.write_session(spec)
                duration = float(time.monotonic() - started)
                result.calls += 1
                turns = getattr(outcome, "turns", None)
                attempt = {"kind": "decision", "turns": turns,
                    "failure": outcome.failure, "duration_secs": duration}
                packet_record.setdefault("attempts", []).append(attempt)
                packet_record["duration_secs"] = duration
                # A session that ended normally is judged on the files it
                # wrote, never on its turn count. The clause that used to
                # sit here (`turns >= max_turns`) compared two different
                # counters: `turns` is Claude Code's `num_turns`, roughly
                # one per tool result, while the limit handed to Claude
                # Code stops on model responses. The 2026-09-19 dry run
                # lost all 29 decided lessons to it: three sessions of
                # 61/51/58 responses, none stopped by the limit of 80,
                # each reporting 104/117/115 and each thrown away. A
                # session Claude Code really stopped at the limit arrives
                # here already failed (`error_max_turns`), with the reason
                # Claude Code gave.
                if not outcome.ok:
                    stopped_at_limit = (
                        getattr(outcome, "result_subtype", None) == "error_max_turns"
                    )
                    bound = "turns" if stopped_at_limit else outcome.failure or "invocation"
                    # A23: the message the transport actually returned, not
                    # just its kind. `exit` alone is what made the
                    # 2026-09-14 outage unreadable from the ledger.
                    detail = _failure_detail(outcome.detail)
                    bound_dispositions = {
                        row["record"]: {
                            "state": "unfinished", "input_version": row["version"],
                            "reason": bound,
                        }
                        for row in packet_record["inputs"]
                    }
                    failure_fields = {
                        "attempts": packet_record.get("attempts") or [],
                        "phase": "unfinished", "failure": bound, "detail": detail,
                        "duration": duration, "dispositions": bound_dispositions,
                    }
                    if dry_run:
                        _record_failure(manifest, packet_index, **failure_fields)
                    else:
                        # A2: ONE update over the record read from HEAD,
                        # changing named fields. The publish this replaces
                        # wrote the whole pre-invocation copy back, erasing
                        # the `last_attempt_at` the attempt-start just
                        # committed — the scheduler then saw "due now" on
                        # every 60-second tick, forever, making zero calls.
                        _update_manifest(
                            home, run_id, reason=f"packet {packet_index} {bound}",
                            update=lambda current: _record_failure(
                                current, packet_index, **failure_fields
                            ),
                        )
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
                        schema_dispositions = {
                            row["record"]: {
                                "state": "unfinished", "input_version": row["version"],
                                "reason": "schema-repair",
                            }
                            for row in packet_record["inputs"]
                        }
                        schema_fields = {
                            "attempts": packet_record.get("attempts") or [],
                            "phase": "unfinished", "failure": "schema-repair",
                            "detail": _failure_detail(second_error), "duration": duration,
                            "dispositions": schema_dispositions,
                            "error": str(second_error),
                        }
                        if dry_run:
                            _record_failure(manifest, packet_index, **schema_fields)
                        else:
                            # A2, latent site: named fields over HEAD. The
                            # splat it replaces wrote a whole local packet
                            # copy back, the same shape as the failure above.
                            _update_manifest(
                                home, run_id,
                                reason=f"packet {packet_index} schema unfinished",
                                update=lambda current: _record_failure(
                                    current, packet_index, **schema_fields
                                ),
                            )
                        continue
                if dry_run:
                    packet_record["phase"] = "complete"
                    continue
                manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
                manifest_packet = manifest["packets"][packet_index - 1]
                manifest_packet.update(
                    attempts=list(packet_record.get("attempts") or []),
                    repair_remaining=packet_record.get("repair_remaining", 1),
                    duration_secs=packet_record.get("duration_secs"),
                )
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
            # A20/A21 + S-68's PROGRESS guard, in one committed update.
            # `complete` is stamped ONLY when every input has a terminal
            # disposition, every case recipe is finished and every
            # maintenance operation is settled; anything less and the next
            # run re-drives this packet (the receipt write is idempotent by
            # `(sheet_sha, item)` key). An attempt that moved nothing is
            # recorded as `no-progress` so the generic guard still reaches
            # the cap on a trap nobody thought of.
            current_manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
            terminal = _packet_units_terminal(
                current_manifest, current_manifest["packets"][packet_index - 1]
            )
            progressed = _made_progress(
                before, _progress_signature(current_manifest, packet_index)
            )
            finished_at = chrono.now_iso()
            _update_manifest(
                home, run_id,
                reason=f"packet {packet_index} "
                + ("complete" if terminal else "attempted" if progressed else "no progress"),
                update=lambda current: _finish_packet_attempt(
                    current, packet_index, terminal=terminal, progressed=progressed,
                    at=finished_at,
                ),
            )

        if not dry_run:
            # Ruling 2, retried not raised: a close-out that cannot write
            # increments nothing and is picked up by the next run, so a
            # wedged ledger never turns into a lost run. It runs even after
            # a halt, because a packet that halts identically every time is
            # precisely the shape that must still reach the cap.
            try:
                _close_out_exhausted(home, run_id, attempt_cap)
            except Exception as exc:  # noqa: BLE001 -- retried by the next run
                # ...but "retried with no count" means NOTHING caps it, so a
                # deterministic failure would repeat for ever with only a
                # git-ignored journal line to show for it. The user hears
                # about it once per distinct cause, and the run says so.
                result.close_out_error = _short_cause(exc)
                waiting = _records_waiting_for_close_out(home, run_id, attempt_cap)
                _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                    "status": "close-out-failed", "error": result.close_out_error,
                    "waiting": waiting})
                if _read_close_out_hold(home) != result.close_out_error:
                    _notify_close_out_failure(
                        home, run_id, waiting, result.close_out_error
                    )
                    _write_close_out_hold(home, result.close_out_error)
            else:
                _write_close_out_hold(home, None)

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
        result.abandoned = list(dict.fromkeys(
            rid for packet in manifest["packets"]
            for rid, value in packet.get("dispositions", {}).items()
            if value.get("state") == "abandoned"
        ))
        # A close-out can abandon a packet whose every INPUT was already
        # disposed, because a case recipe or a maintenance operation was not
        # terminal. That packet is stamped `abandoned` with zero abandoned
        # records, so `result.abandoned` stays empty and the run used to
        # report `applied` and exit 0 over the dropped unit.
        result.abandoned_units = list(dict.fromkeys(
            unit for packet in manifest["packets"]
            for unit in packet.get("abandoned_units") or []
        ))
        coverage = _coverage_empty()
        for recipe in manifest.get("cases", {}).values():
            case_data = YAML(typ="safe").load(recipe["case"])
            if isinstance(case_data, dict):
                key = f"{case_data.get('outcome')}:{_scope_bucket(case_data.get('scope'))}"
                if key in coverage:
                    coverage[key] += 1
        result.coverage = coverage
        has_applied = bool(result.decided)
        # A close-out the runner could not write is unfinished business by
        # definition, and must never let the run report success: FW-85's
        # whole point is that automation reads the code, not the prose.
        has_unfinished = (
            bool(result.unfinished)
            or halt_code is not None
            or result.close_out_error is not None
        )
        # A run that closed lessons out never reports success: `refused` (or
        # `partial` beside applied work) is FW-85's "an actual failure", and
        # the text line below names the count so it can never again read
        # "0 decided, 0 refused, 0 unfinished" beside a non-zero exit.
        has_refused = (
            result.refused > 0
            or bool(result.abandoned)
            or bool(result.abandoned_units)
        )
        if halt_code == gitops.EXIT_GIT_FAILED:
            result.status = "partial" if has_applied else "stopped"
        elif has_unfinished or (has_applied and has_refused):
            result.status = "partial"
        elif has_refused:
            result.status = "refused"
        else:
            result.status = "applied"
        complete = not has_unfinished and all(
            packet.get("phase") in _TERMINAL_PACKET_PHASES for packet in manifest["packets"]
        )
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
                "abandoned": result.abandoned,
                "abandoned_units": result.abandoned_units,
                "close_out_error": result.close_out_error,
                "coverage": result.coverage,
            },
        )
        # Ruling 2's notification, ONCE per closed-out run and never once
        # per record: a run transitions to `complete` exactly once and is
        # never re-driven afterwards, so this is that one moment. A close-out
        # that abandoned only NON-record units is told too — it is still work
        # the runner gave up on, and it was previously silent.
        if complete and (result.abandoned or result.abandoned_units):
            _notify_abandoned(
                home, run_id, manifest, result.abandoned, result.abandoned_units
            )
        return result
