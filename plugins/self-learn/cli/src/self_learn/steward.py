"""The autonomous steward runner (plan-steward 5.1-5.4, S-29/S-65/S-67).

The model may write only declared stage files below one cache run directory.
This module owns every ledger write made from those files.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field, replace as dataclass_replace
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable
from typing import cast

from ruamel.yaml import YAML, YAMLError

from . import (
    always_loaded,
    model_failures,
    batch,
    cases,
    conditions,
    config,
    execution_evidence,
    gitops,
    intents,
    invocation,
    ledger_ops,
    settings,
    statements,
    steward_inputs,
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
from .scan import format_refusal, refusal_text, yaml_error_text
from .scan import scan as secret_scan


@dataclass
class RunResult:
    status: str
    run_id: str | None = None
    decided: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    calls: int = 0
    #: How many of `calls` failed (2026-09-26): a dry run discards every
    #: decision, so without this "every call failed" and "every call
    #: returned and its work was discarded" read the same.
    failed_calls: int = 0
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
    #: 2026-09-28: the targets the post-run recompile skipped
    #: (``"<target>: <reason>"``), one pass, never retried in the run.
    recompile_skipped: list[str] = field(default_factory=list)
    #: 2026-09-27 (fail-state audit finding 4): the cause when this run was
    #: held because the model or the installed Claude Code could not run a
    #: call at all (`environment`); that attempt was not counted.
    held: str | None = None


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
#: S-71 splits what used to be one set. "This run is done with the
#: record": what every "is the packet finished?" question reads. A record
#: sent back (`returned`) is done for THIS run -- the run can complete --
#: but its input version still needs a decision, so the next run selects
#: it again with a fresh model call.
_RUN_TERMINAL_DISPOSITIONS = frozenset(
    {"applied", "parked", "refused", "abandoned", "returned", "overtaken"}
)
#: "This input version needs no new decision": what `_terminal_versions`,
#: and therefore `_eligible_lessons`, reads. `returned` is deliberately
#: NOT here, and an `applied` row whose case moved the lesson decides
#: nothing (`_terminal_versions`, 2026-10-06).
_DECIDED_DISPOSITIONS = frozenset(
    {"applied", "parked", "refused", "abandoned", "overtaken"}
)
#: The two sheet verbs that FILE a lesson -- move it to another bucket --
#: without deciding it (2026-10-06). The lesson is still pending after
#: either, in its new bucket, and needs a decision there. Since L8 every
#: move appends a `moved` history entry to the record (`ledger_ops.
#: move_record`), so a moved lesson is a new version anyway; a lesson moved
#: before that, project->project, kept its version, and only
#: `_terminal_versions`' skip of its move row brings it back.
_FILING_VERBS = frozenset({"rehome", "rescope"})
#: How many filing moves of one lesson the steward may have made -- its
#: committed `applied` move rows or the record's own `moved` entries by the
#: steward, whichever is more -- before a case that moves it again is
#: parked for the overseer as `scope-conflict` instead of applied
#: (2026-10-06). One: a
#: lesson filed once and then filed again -- back where it came from or
#: onward to a third bucket -- is a disagreement about where it belongs,
#: which is the overseer's to settle; without this a steward that keeps
#: changing its mind moves the lesson every night for ever (each move is a
#: complete, progressing run, so S-68's per-packet attempt cap never sees
#: it). Separately, the steward never moves a lesson a person or the
#: overseer moved last (`_last_mover`), whatever this count says.
_FILING_MOVE_LIMIT = 1
#: The reason that park is recorded with (`cases.PARKED_REASONS`): both
#: parks are a disagreement about which scope the lesson belongs in.
_REFILING_PARKED_REASON = "scope-conflict"
_SUCCESS_RECEIPT_STATES = frozenset({"applied", "already-applied"})
#: S-71 §4.2: what the steward does with a record whose line the ledger
#: refused, by kind. `status` never appears here: it is resolved first,
#: into `overtaken` (the lesson moved on since the run selected it) or
#: `bad-line` (the steward's own mistake).
_KIND_ACTIONS = {
    "secret-record": "refused",
    # The retried kinds are `batch.RETRIED_REFUSAL_KINDS`, the definition
    # the overseer's resume reads too (2026-09-26, N14).
    **{kind: "retry" for kind in sorted(batch.RETRIED_REFUSAL_KINDS)},
    "needs-person": "park",
    "unclassified": "park",
    "bad-line": "return",
    "destination-unavailable": "return",
    "overtaken": "close",
}
#: Item states that are not a refusal of the line: a STOP left the item
#: undone (`not-attempted`), or the ledger took the line and a host file
#: is still owed (`unresolved-host`). Neither is the line's fault, and
#: S-68 ruling 1 retried both before S-71; they still are. (Today an
#: `unresolved-host` item only ever arrives with a bookkeeping halt, whose
#: whole case is re-driven before any kind is read; it is named here so a
#: future path that returns one cannot park a lesson whose line landed.)
_RETRY_ITEM_STATES = frozenset({"not-attempted", "unresolved-host"})
_FAILED_ITEM_STATES = frozenset({"refused", "stopped", "not-attempted", "unresolved-host"})

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
#: 02-schema §3a: three `parked_reason` values are written by a RUNNER and
#: are never the model's to choose -- `plain-host-committed-file`, which
#: `_forced_parking_reason` assigns AFTER the model's output is validated,
#: `attempts-exhausted`, which only the close-out writes, and
#: `ledger-refused` (S-71), which only the park-now writes. A model that
#: wrote any of them would be telling the overseer "the machinery stopped me,
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
        if (dispositions.get(row["record"]) or {}).get("state") not in _RUN_TERMINAL_DISPOSITIONS
    ]


def _packet_units_terminal(manifest: dict, packet: dict) -> bool:
    """A20/A21: every input disposed, every case recipe finished, every
    maintenance operation settled. Anything less and the packet is NOT
    stamped `complete`, so the next run re-drives it (the receipt write is
    idempotent by `(sheet_sha, item)` key, so re-driving it is safe)."""
    dispositions = packet.get("dispositions") or {}
    for row in packet.get("inputs") or []:
        if (dispositions.get(row["record"]) or {}).get("state") not in _RUN_TERMINAL_DISPOSITIONS:
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
        signature[f"disposition:{record_id}"] = 2 if state in _RUN_TERMINAL_DISPOSITIONS else 1
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
        if isinstance(value, dict) and value.get("state") in _RUN_TERMINAL_DISPOSITIONS
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
    classified: dict | None = None,
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
    # 2026-09-27 (fail-state audit finding 4): the failed call's class and
    # the API's tag, or none of either when the failure was not a call's.
    packet.pop("failure_class", None)
    packet.pop("failure_tag", None)
    packet.update(classified or {})
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
    if _only_uncovered_open(manifest, packet):
        # 2026-09-27 (audit finding 3): what is left needs a decision, not
        # a re-drive, so the next attempt is a fresh model call for the
        # lessons still open (the attempt cap bounds it as ever).
        packet["phase"] = "unfinished"
    if progressed:
        return
    packet["failure"] = "no-progress"
    packet["failure_detail"] = _NO_PROGRESS_DETAIL
    dispositions = packet.setdefault("dispositions", {})
    for row in packet.get("inputs") or []:
        record_id = row["record"]
        value = dispositions.get(record_id)
        if isinstance(value, dict) and value.get("state") in _RUN_TERMINAL_DISPOSITIONS:
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


#: 2026-09-26 (agenda item 25): True while a `--dry-run` is in progress.
#: Every journal row written meanwhile -- `model-log`, a `refused` case,
#: the final `dry-run` row -- is marked `"dry_run": true`, and serve's
#: attempt cooldown skips a marked row, so a rehearsal never delays the
#: real run behind it. A plain module flag, not a ContextVar: the model
#: log callback may fire from another thread.
_DRY_RUN_JOURNAL = False

#: 2026-09-28: the ids of the route/rehome/rescope items this run applied
#: or left `unresolved-host` (:func:`verbs.host_result_ids`), gathered where
#: each sheet's result is known; `None` outside a run. :func:`run` hands
#: them to one narrowed recompile after `_run` returns.
_HOST_RESULT_IDS: list[str] | None = None


#: 2026-09-28 (follow-up 1): ``(record id, bucket)`` of each rehome or
#: rescope item, read before its sheet is applied (:func:`verbs.
#: move_origins`); the post-run recompile compiles the target it left.
_MOVED_FROM: list[tuple[str, Path]] | None = None


def _note_host_results(result: batch.BatchResult) -> None:
    if _HOST_RESULT_IDS is not None:
        _HOST_RESULT_IDS.extend(verbs.host_result_ids(result.items))


def _note_move_origins(home: Path, items: Iterable[object]) -> None:
    if _MOVED_FROM is not None:
        _MOVED_FROM.extend(verbs.move_origins(home, items))


def _journal(home: Path | str, entry: dict) -> None:
    if _DRY_RUN_JOURNAL:
        entry = {**entry, "dry_run": True}
    path = journal_path(home)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n", fsync=True)


def _read_yaml(path: Path) -> dict | list:
    """A stage file's YAML. Its errors reach the repair turn and, when no
    pair passes, the committed run record, so they never carry the
    model's text (2026-09-28): a parse error is the overseer's rule
    (:func:`scan.yaml_error_text` -- file, problem cut at its first quote,
    line and column), and any other failure is named by its type only."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path.name}: cannot read: {type(exc).__name__}") from exc
    try:
        value = YAML(typ="safe").load(text)
    except YAMLError as exc:
        raise ValueError(yaml_error_text(path.name, exc)) from exc
    except Exception as exc:  # noqa: BLE001 -- e.g. RecursionError; named, never quoted
        raise ValueError(f"{path.name}: cannot parse — {type(exc).__name__}") from exc
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


def _dirty_among(home: Path, paths: list[Path]) -> list[str]:
    """The uncommitted (modified or untracked) paths among *paths* -- the
    files the next commit will touch. 2026-09-27 (fail-state audit finding
    8): only these can refuse a step. Every commit is path-scoped
    (`gitops.stage_and_commit` stages and commits its own paths only), so
    a stray file anywhere else can never be committed by it."""
    found: list[str] = []
    for path in paths:
        found.extend(gitops.dirty_paths(home, path))
    return list(dict.fromkeys(found))


def _note_unexplained_paths(home: Path, run_id: str | None) -> None:
    """2026-09-27 (fail-state audit finding 8): uncommitted paths in the
    ledger that no step of this run touches are journaled and the user is
    told -- once per distinct set, never once per check -- and the run goes
    on. Before, one untracked file anywhere in the ledger stopped every
    steward run before its first model call, silently. Never raises."""
    try:
        dirty = sorted(_dirty_truth_paths(home))
    except gitops.GitOpsError:
        return
    if not dirty:
        return
    previous: list[str] | None = None
    try:
        for line in reversed(journal_path(home).read_text(encoding="utf-8").splitlines()):
            if '"unexplained-paths"' not in line:
                continue
            row = json.loads(line)
            if row.get("status") == "unexplained-paths":
                previous = row.get("paths")
                break
    except (OSError, ValueError):
        previous = None
    if previous == dirty:
        return
    _journal(home, {"ts": chrono.now_iso(), **({"run_id": run_id} if run_id else {}),
        "status": "unexplained-paths", "paths": dirty})
    shown = ", ".join(dirty[:5]) + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
    try:
        overseer_notify.send(
            home, "routine",
            f"self-learn steward: the ledger has uncommitted path(s) nothing of "
            f"self-learn wrote: {shown}. The steward goes on and never commits "
            "them; look at them when you can.",
            [run_id] if run_id else [],
        )
    except Exception as exc:  # noqa: BLE001 -- a notification never fails a run
        _journal(home, {"ts": chrono.now_iso(), "status": "notify-failed",
            "error": _short_cause(exc)})


def _sheet_record_paths(home: Path, items: batch.Sheet) -> list[Path]:
    """The record files a sheet's dispatch commits -- one per lesson it
    names that the ledger can still find."""
    paths: list[Path] = []
    for item in items:
        try:
            paths.append(ledger_ops.find_record_path(home, item.id))
        except ledger_ops.LedgerOpsError:
            continue
    return paths


def _publish_manifest(home: Path, manifest: dict, *, reason: str) -> str:
    """Intent-protect and commit one immutable-identity manifest revision."""
    run_id = str(manifest.get("run_id") or "")
    path = execution_evidence.manifest_path(home, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    subject = f"self-learn: steward manifest {run_id} ({reason})"
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        # 2026-09-27 (fail-state audit finding 8): only the file this commit
        # touches can refuse it; anything else is noted and never committed.
        dirty = _dirty_among(home, [path])
        if dirty:
            raise gitops.GitOpsError(
                "steward refuses unexplained dirty ledger paths before manifest "
                f"publication: {dirty}"
            )
        _note_unexplained_paths(home, run_id or None)
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


def _committed_blob(home: Path, path: Path) -> tuple[str, str]:
    """``(ledger-relative path, its blob at HEAD)``; ValueError when the file
    is outside the ledger or not committed."""
    try:
        rel = path.resolve().relative_to(home.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"input path is outside the ledger: {path}") from exc
    blob = gitops._git(home, "rev-parse", f"HEAD:{rel}")  # noqa: SLF001
    if blob.returncode != 0 or not blob.stdout.strip():
        raise ValueError(f"input is not committed: {rel}")
    return rel, blob.stdout.strip()


def _record_identity(home: Path, entry: ledger_ops.QueueEntry) -> dict:
    """U3a (2026-09-27): a lesson input's identity is the RECORD's committed
    blob, not the analyst proposal's. A record edited after selection is a
    new version and needs a new decision; an analyst proposal written or
    rewritten beside it changes nothing.

    ``legacy_version``: the proposal blob, when the lesson has a committed
    proposal. Every run record written before this change keyed its
    dispositions by that blob, so a lesson applied, parked or abandoned
    then is still decided now (:func:`_eligible_lessons`) -- but not one
    REFUSED then, which gets one fresh attempt under this identity
    (:data:`_LEGACY_DECIDED_DISPOSITIONS`) -- and a lesson
    sent back then still shows as sent back (:func:`_returned_for`)."""
    rel, version = _committed_blob(home, entry.path)
    row = {
        "path": rel,
        "blob": version,
        "version": version,
        "record": entry.record.id,
        "kind": steward_inputs.INPUT_LESSON,
        # S-71 §4.1: the status the lesson had when this run selected it,
        # so a `status` refusal at apply time can tell "the lesson moved
        # on" from "the steward's own line does not fit". A row without
        # it (written before S-71) reads as "unknown".
        "record_status": entry.record.status,
    }
    try:
        _rel, legacy = _committed_blob(home, entry.proposal_path)
    except (ValueError, OSError):
        legacy = None
    if legacy is not None:
        row["legacy_version"] = legacy
    return row


#: What the legacy bridge (U3a) carries from a run record written under the
#: PROPOSAL identity: decided outcomes only. A `refused` disposition is the
#: machinery refusing a write, not a judgment on the lesson (live 2026-09-27:
#: two lessons refused over a secret-scan false positive since fixed in
#: b8e4ef0, stranded for ever) -- under the record identity such a lesson
#: gets one fresh attempt, and a refusal then is terminal as before.
_LEGACY_DECIDED_DISPOSITIONS = _DECIDED_DISPOSITIONS - {"refused"}


def _files_record(recipe: object, record_id: str) -> bool:
    """True when this committed case recipe's sheet holds a filing item
    (`rehome` / `rescope`) for *record_id*. "Holds one", not "holds only
    those": a lesson an `applied` case moved and that is still pending at
    the same version was only moved -- any item that decides a lesson
    changes its status, and a `revise` changes its version."""
    if not isinstance(recipe, dict):
        return False
    return any(
        isinstance(item, dict)
        and item.get("id") == record_id
        and item.get("verb") in _FILING_VERBS
        for item in recipe.get("items") or []
    )


def _terminal_versions(
    home: Path, states: frozenset[str] = _DECIDED_DISPOSITIONS
) -> set[tuple[str, str]]:
    """Every ``(record, input version)`` a committed steward run decided.

    2026-10-06: an `applied` row whose case moved the lesson (a filing
    move, :func:`_files_record`) is not a decision: the lesson is still
    pending, in its new bucket, and needs one there. Since L8 a move also
    changes the record's version (its `moved` history entry), so this skip
    is what brings back a lesson moved project->project before that -- its
    bytes, and so its version, never changed."""
    terminal: set[tuple[str, str]] = set()
    for manifest in committed_manifests(home):
        recipes = manifest.get("cases") or {}
        for packet in manifest.get("packets") or []:
            if not isinstance(packet, dict):
                continue
            for rid, disposition in (packet.get("dispositions") or {}).items():
                if not isinstance(disposition, dict):
                    continue
                if disposition.get("state") in states:
                    if disposition.get("state") == "applied" and _files_record(
                        recipes.get(disposition.get("case")), str(rid)
                    ):
                        continue
                    version = disposition.get("input_version")
                    if isinstance(rid, str) and isinstance(version, str):
                        terminal.add((rid, version))
    return terminal


def _steward_filing_moves(home: Path) -> dict[str, int]:
    """record -> how many filing moves of it the steward's committed runs
    applied, at any version (so a `[revise, rehome]` pair each night is
    counted too). The overseer's own moves are not in a steward run record
    and are never counted; :func:`_last_mover` covers them."""
    moves: dict[str, int] = {}
    for manifest in committed_manifests(home):
        recipes = manifest.get("cases") or {}
        for packet in manifest.get("packets") or []:
            if not isinstance(packet, dict):
                continue
            for rid, disposition in (packet.get("dispositions") or {}).items():
                if (
                    isinstance(rid, str)
                    and isinstance(disposition, dict)
                    and disposition.get("state") == "applied"
                    and _files_record(recipes.get(disposition.get("case")), rid)
                ):
                    moves[rid] = moves.get(rid, 0) + 1
    return moves


def _last_mover(home: Path, record_id: str) -> str | None:
    """Who moved this lesson last: the ``by`` of the newest ``moved``
    history entry on its record (written by every move since L8), or
    `None` when it has none or cannot be read."""
    record = _find_record(home, record_id)
    if record is None:
        return None
    for entry in reversed(record.history or []):
        if isinstance(entry, dict) and entry.get("event") == "moved":
            by = entry.get("by")
            return str(by) if by is not None else None
    return None


def _steward_moves_on_record(home: Path, record_id: str) -> int:
    """How many ``moved`` history entries by the steward the lesson's
    record carries. This counts a steward move whatever became of the case
    that made it: a `[rehome, route]` case whose route the ledger refused
    ends `returned`, `unfinished` or `abandoned`, never `applied`, so the
    run records alone never count its move (the 6f9a33f review)."""
    record = _find_record(home, record_id)
    if record is None:
        return 0
    return sum(
        1
        for entry in record.history or []
        if isinstance(entry, dict)
        and entry.get("event") == "moved"
        and entry.get("by") == "steward"
    )


def _refiling_reason(home: Path, sheet_path: Path) -> str | None:
    """`scope-conflict` when this staged sheet would move a lesson that
    (a) the steward's committed runs have already moved
    `_FILING_MOVE_LIMIT` times, or (b) a person or the overseer moved last
    -- the steward never overrides their filing, however few moves it has
    made itself; else `None`. The case is then parked for the overseer (its
    sheet recorded, never applied), and the lesson stays pending where it
    is, decided at its version, until the overseer decides it.

    The steward's own count is the larger of its committed `applied` move
    rows (which still count a move made before moves wrote a `moved`
    entry) and the record's `moved` entries by the steward (which count a
    move inside a case that did not end `applied`)."""
    raw = _read_yaml(sheet_path)
    if not isinstance(raw, dict):
        return None
    filed = {
        str(item.get("id"))
        for item in raw.get("items") or []
        if isinstance(item, dict) and item.get("verb") in _FILING_VERBS
    }
    if not filed:
        return None
    moves = _steward_filing_moves(home)
    for rid in sorted(filed):
        count = max(moves.get(rid, 0), _steward_moves_on_record(home, rid))
        if count >= _FILING_MOVE_LIMIT:
            return _REFILING_PARKED_REASON
        last = _last_mover(home, rid)
        if last is not None and last != "steward":
            return _REFILING_PARKED_REASON
    return None


def _eligible_lessons(home: Path) -> list[tuple[ledger_ops.QueueEntry, dict]]:
    """Every queued (pending, not deferred) lesson whose current version no
    committed run has decided, oldest first, with its input row. A filing
    move decides nothing (:func:`_terminal_versions`), so a lesson the
    steward rehomed or rescoped is selected again by the next run, in its
    new bucket.

    U3a (2026-09-27): no analyst proposal is needed. The worker still
    writes proposals for now (U5 retires it); nothing here reads them
    except to recognise a version a run decided before this change.

    S-81 (2026-10-08): a lesson the overseer holds (`cases.held_lessons`)
    is not selected, whatever parked it; once the overseer's decision
    supersedes its parked case it is selected again if its version is
    still undecided."""
    held = cases.held_lessons(home)
    entries: list[ledger_ops.QueueEntry] = []
    for bucket in discover_buckets(home):
        entries.extend(
            entry for entry in ledger_ops.queue(bucket) if entry.record.id not in held
        )
    entries.sort(
        key=lambda entry: (
            chrono.to_dt(entry.record.created_at)
            or datetime.fromtimestamp(0, tz=timezone.utc),
            entry.record.id,
        )
    )
    terminal = _terminal_versions(home)
    legacy_terminal = _terminal_versions(home, _LEGACY_DECIDED_DISPOSITIONS)
    out: list[tuple[ledger_ops.QueueEntry, dict]] = []
    for entry in entries:
        try:
            identity = _record_identity(home, entry)
        except ValueError:
            continue
        rid = entry.record.id
        if (rid, identity["version"]) in terminal:
            continue
        legacy = identity.get("legacy_version")
        if isinstance(legacy, str) and (rid, legacy) in legacy_terminal:
            continue
        out.append((entry, identity))
    return out


def _find_record(home: Path, record_id: str) -> Record | None:
    try:
        return Record.from_path(ledger_ops.find_record_path(home, record_id))
    except (ledger_ops.LedgerOpsError, RecordError, OSError):
        return None


def _suspected_violation_inputs(home: Path, exclude: set[str] | None = None) -> list[dict]:
    """U3a (2026-09-27; the user's (b), 2026-09-26 19:32): one input per
    ROUTED record that unhandled `suspected-violation` fires name. Its
    version is its events' nonces (:func:`steward_inputs.fires_version`),
    so a run that decided those events -- applied, parked, refused or
    abandoned -- is never offered them again, and a later fire makes a
    new version. An event a record entry already handled
    (`confirm-recurrence` / `dismiss-suspect` wrote its nonce) is dropped
    before the version is taken. A lesson the overseer holds is not
    offered (S-81)."""
    found = steward_inputs.suspected_violations(home, _find_record)
    if not found:
        return []
    terminal = _terminal_versions(home)
    held = cases.held_lessons(home)
    out: list[dict] = []
    for rid, events in found.items():
        if (exclude and rid in exclude) or rid in held:
            continue
        version = steward_inputs.fires_version(events)
        if (rid, version) in terminal:
            continue
        out.append({
            "path": f"telemetry:fire/{rid}",
            "blob": version,
            "version": version,
            "record": rid,
            "kind": steward_inputs.INPUT_SUSPECTED_VIOLATION,
            "record_status": "routed",
            "events": [
                {key: event.get(key) for key in ("nonce", "ts", "outcome", "origin", "record")
                 if key in event} | ({"fire_nonce": event["fire_nonce"]} if event.get("fire_nonce") else {})
                for event in events
            ],
        })
    return out


#: A reconsider input's card line (`_reconsider_proposals`): the lesson an
#: earlier case placed, rejected or deferred is re-decided ...
_RECONSIDER_UNRESOLVED = "Re-decide against the new statement or dependency observation."
#: ... and one that is pending was not: it is decided, not reconsidered
#: (2026-10-07, run-9858d321b158: the model read "reconsider" and wrote a
#: `kind: reconsider` case for two pending lessons, which the ledger
#: refused).
_PENDING_UNRESOLVED = (
    "This lesson is pending: it is not placed, rejected or deferred, so there is no "
    "earlier decision to reconsider. Decide it with a `kind: resolution` case, not "
    "`kind: reconsider`."
)


def _reconsider_status_refusal(home: Path, record_id: str) -> ledger_ops.StatusRefusal | None:
    """The refusal `verbs.reconsider` would give *record_id* NOW for its
    status, from the verb's own check (`ledger_ops.require_status` over
    `RECONSIDERABLE_STATUSES`), or `None` when its status admits a
    reconsider or the record cannot be read (2026-10-07)."""
    try:
        ledger_ops.require_status(
            home, record_id, ledger_ops.RECONSIDERABLE_STATUSES, verb="reconsider"
        )
    except ledger_ops.StatusRefusal as exc:
        return exc
    except ledger_ops.LedgerOpsError:
        return None
    return None


def _reconsider_unresolved(home: Path, record: Record) -> str:
    """The card line a reconsider input comes with: for a PENDING lesson,
    which the reconsider verb refuses, that it takes a resolution case;
    otherwise the line every reconsider input carried before. The status is
    read the way the repair turn reads it (:func:`_reconsider_status_refusal`)."""
    if record.status == "pending" and _reconsider_status_refusal(home, record.id) is not None:
        return _PENDING_UNRESOLVED
    return _RECONSIDER_UNRESOLVED


def _reconsider_proposals(home: Path) -> tuple[list[tuple[_QueuedProposal, dict]], dict[str, str]]:
    """Every lesson a case's new statement or dependency observation brings
    back, as a reconsider input. A lesson the overseer holds is not (S-81):
    its observation stays unconsumed."""
    all_cases = cases.list_cases(home, only_ok=True)
    superseded = {row.get("supersedes") for row in all_cases if row.get("supersedes")}
    held = cases.held_lessons(home)
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
            if rid in seen or rid in held:
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
                            "unresolved": _reconsider_unresolved(home, record),
                        },
                        "recommendation": "reconsider",
                    },
                )
            )
    return selected, predecessors


def _reconsider_row(entry: _QueuedProposal, card: dict) -> dict:
    """A reconsider input as a run input row: identity is the observation
    that brought it back, as before U3a."""
    version = f"observation:{entry.observation_id}"
    raw = card.get("card")
    detail: dict = raw if isinstance(raw, dict) else {}
    reason = " ".join(str(detail.get(key) or "") for key in ("headline", "unresolved")).strip()
    row = {
        "path": entry.proposal_path.as_posix(), "blob": version, "version": version,
        "record": entry.record.id, "kind": steward_inputs.INPUT_RECONSIDER,
        "record_status": entry.record.status, "reason": reason,
    }
    if entry.predecessor:
        row["predecessor"] = entry.predecessor
    if entry.observation_id:
        row["observation_id"] = entry.observation_id
    return row


def _brief_input(row: dict) -> dict:
    """A manifest input row as :func:`steward_prompt.assemble` reads it. A
    row written before U3a has no ``kind`` and reads as a lesson; its
    ``proposal`` is never passed on."""
    out = {"id": row.get("record"), "kind": row.get("kind") or steward_inputs.INPUT_LESSON}
    for key in ("reason", "events"):
        if row.get(key):
            out[key] = row[key]
    return out


def _packet_briefs(
    home: Path, manifest: dict, packet: dict, inputs: list[dict]
) -> dict[str, steward_inputs.LessonBrief]:
    """The packet's briefs, built against the lesson index the run start
    refreshed (opened read-only here; absent, the briefs say so)."""
    index = steward_inputs.open_index(home)
    try:
        return steward_inputs.build_briefs(
            home, inputs,
            find_record_path=ledger_ops.find_record_path,
            index=index,
            links=list((packet.get("group") or {}).get("links") or []),
            head=str(manifest.get("start_head") or "") or None,
        )
    finally:
        if index is not None:
            index.close()


def _declared_stage_file(rel: str) -> bool:
    """A stage path the output contract names (`steward_prompt.OUTPUT_CONTRACT`)."""
    allowed_names = set(steward_prompt.OUTPUT_CONTRACT)
    allowed_files = {name for name in allowed_names if "*" not in name}
    return rel in allowed_files or (
        rel.startswith("cases/") and rel.endswith(".yaml") and "cases/*.yaml" in allowed_names
    ) or (
        rel.startswith("sheets/") and rel.endswith(".yaml") and "sheets/*.yaml" in allowed_names
    )


def _pair_problem(stage: Path, case_path: Path, home: Path | None = None) -> str | None:
    """What is wrong with ONE case/sheet pair, judged on its own, or `None`
    (2026-09-27, audit finding 3): the case's parked-reason rules, the
    sheet's own schema, and one sheet item for every lesson the case
    covers. The messages are the ones the whole-stage check always gave.

    U3b (2026-09-28): a decided case that routes a lesson to an
    always-loaded line must evidence all three tests of the combined test
    (:mod:`always_loaded`); *home*, when given, resolves a dest-less
    route's destination from the lesson's proposal."""
    try:
        case_data = _read_yaml(case_path)
    except ValueError as exc:
        return str(exc)
    sheet_path = stage / "sheets" / case_path.name
    if not sheet_path.is_file():
        return "cases/*.yaml and sheets/*.yaml must have matching stems"
    if isinstance(case_data, dict):
        reason = case_data.get("parked_reason")
        if reason in _RUNNER_ONLY_PARKED_REASONS:
            # Validated on what the MODEL wrote: `_forced_parking_reason`
            # assigns `plain-host-committed-file` later, in
            # `_prepared_recipe`, and is untouched by this.
            return (
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
            return (
                f"{case_path.name}: a parked case needs parked_reason, one of "
                f"{sorted(_MODEL_PARKED_REASONS)}; got {reason!r}"
            )
        if not parks and (reason is not None or case_data.get("parked_for") is not None):
            return (
                f"{case_path.name}: parked_reason/parked_for are only for a case "
                "whose kind is parked"
            )
    try:
        raw = _read_yaml(sheet_path)
    except ValueError as exc:
        return str(exc)
    if not isinstance(raw, dict):
        return f"{sheet_path.name}: sheet must be a mapping"
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
        return str(exc)
    finally:
        validation_path.unlink(missing_ok=True)
    if not isinstance(case_data, dict):
        return f"{case_path.name}: case must be a mapping"
    # Every lesson a case covers needs its own item on that case's sheet.
    # The runner dispositions every lesson of a finished case `applied`, so
    # a lesson with no item was recorded as handled with nothing done to it
    # (seen in the real run of 2026-09-19: a two-lesson case, one item).
    items = raw.get("items")
    item_ids = {
        item.get("id") for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
    }
    without_item = [
        str(rid) for rid in (case_data.get("records") or []) if rid not in item_ids
    ]
    if without_item:
        return (
            f"{case_path.name}: every lesson in a case needs its own item in "
            f"sheets/{case_path.name}; no item for {without_item}"
        )
    return always_loaded.route_problem(
        case_data,
        items if isinstance(items, list) else [],
        resolve=always_loaded.proposal_resolver(home) if home is not None else None,
        label=case_path.name,
    )


def _validate_declared_stage(stage: Path) -> None:
    """The whole-stage check in its STRICT form: every file declared and
    readable, every case/sheet pair valid. The brief's own examples are
    held to it; the runner itself applies :func:`_check_stage`, which
    judges each pair on its own (2026-09-27)."""
    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
        rel = path.relative_to(stage).as_posix()
        if not _declared_stage_file(rel):
            raise ValueError(f"undeclared stage file: {rel}")
        _read_yaml(path)
    case_files = sorted((stage / "cases").glob("*.yaml")) if (stage / "cases").is_dir() else []
    sheet_files = sorted((stage / "sheets").glob("*.yaml")) if (stage / "sheets").is_dir() else []
    if not case_files:
        raise ValueError("cases/*.yaml: at least one decision case is required")
    if {p.stem for p in case_files} != {p.stem for p in sheet_files}:
        raise ValueError("cases/*.yaml and sheets/*.yaml must have matching stems")
    for case_path in case_files:
        problem = _pair_problem(stage, case_path)
        if problem is not None:
            raise ValueError(problem)


@dataclass
class _StageCheck:
    """What :func:`_check_stage` found (2026-09-27, audit finding 3)."""

    #: stems whose case/sheet pair passed, in order.
    valid: list[str]
    #: stem -> what is wrong with that pair (or with a sheet without a case).
    problems: dict[str, str]
    #: selected lessons no valid pair covers.
    uncovered: list[str]
    #: stage-relative paths moved to the quarantine directory.
    quarantined: list[str]


def _quarantine_move(stage: Path, path: Path, quarantine: Path) -> str:
    """Move one stage file into the run-scoped quarantine directory in the
    cache (never the ledger), keeping its stage-relative path."""
    rel = path.relative_to(stage).as_posix()
    target = quarantine / rel
    n = 1
    while target.exists():
        n += 1
        target = quarantine / f"{rel}.{n}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    return rel


def _check_stage(
    stage: Path, selected_ids: set[str] | None, quarantine: Path,
    home: Path | None = None,
) -> _StageCheck:
    """The runner's stage check, per case/sheet pair (2026-09-27, audit
    finding 3). Before, one problem anywhere refused the whole packet, and
    one kind (an undeclared file) could never be repaired, because the
    session has no tool to delete a file.

    * An undeclared file is moved out of the stage into *quarantine* (a
      run-scoped cache directory), so it can never reach the ledger, and
      named in the result; it no longer refuses the packet.
    * Each case/sheet pair is judged on its own (:func:`_pair_problem`),
      and so is its coverage: a pair covering a lesson that is not open in
      this packet, or one another pair covers too, is a problem of that
      pair. A problem pair is not applied; its lessons stay open.
    * Only what is not a pair still refuses the packet: an unreadable
      declared file, a bad `revisions.yaml`, or no valid pair at all."""
    _incorporate_revisions(stage)
    quarantined: list[str] = []
    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
        rel = path.relative_to(stage).as_posix()
        if not _declared_stage_file(rel):
            quarantined.append(_quarantine_move(stage, path, quarantine))
        elif not rel.startswith(("cases/", "sheets/")):
            _read_yaml(path)
    case_stems = {p.stem for p in (stage / "cases").glob("*.yaml")} if (stage / "cases").is_dir() else set()
    sheet_stems = {p.stem for p in (stage / "sheets").glob("*.yaml")} if (stage / "sheets").is_dir() else set()
    problems: dict[str, str] = {}
    records: dict[str, list[str]] = {}
    for stem in sorted(case_stems | sheet_stems):
        case_path = stage / "cases" / f"{stem}.yaml"
        if not case_path.is_file():
            problems[stem] = "cases/*.yaml and sheets/*.yaml must have matching stems"
            continue
        problem = _pair_problem(stage, case_path, home)
        if problem is not None:
            problems[stem] = problem
            continue
        data = _read_yaml(case_path)
        records[stem] = [str(rid) for rid in (data.get("records") or [])] if isinstance(data, dict) else []
    if selected_ids is not None:
        covering: dict[str, list[str]] = {}
        for stem, rids in records.items():
            for rid in rids:
                covering.setdefault(rid, []).append(stem)
            strange = sorted(set(rids) - selected_ids)
            if strange:
                problems[stem] = (
                    f"{stem}.yaml: covers {strange}, not a lesson of this packet "
                    "still to decide"
                )
        for rid, stems in covering.items():
            if len(stems) > 1:
                for stem in stems:
                    problems.setdefault(
                        stem, f"{stem}.yaml: {rid} is covered by more than one case ({sorted(stems)})"
                    )
    valid = [stem for stem in sorted(records) if stem not in problems]
    covered = {rid for stem in valid for rid in records[stem]}
    uncovered = sorted(selected_ids - covered) if selected_ids is not None else []
    if not valid:
        if not problems:
            raise ValueError("cases/*.yaml: at least one decision case is required")
        raise ValueError("\n".join(
            ["no case/sheet pair passed the runner's checks:"]
            + [f"- cases/{stem}.yaml: {problem}" for stem, problem in sorted(problems.items())]
        ))
    return _StageCheck(valid, problems, uncovered, quarantined)


def _pair_message(check: _StageCheck) -> str | None:
    """The per-pair problems as a repair-turn section, one ``- `` line
    each (so :func:`_flag_lines` counts them), or `None`."""
    lines = [f"- cases/{stem}.yaml: {problem}" for stem, problem in sorted(check.problems.items())]
    lines += [f"- lesson {rid}: no case that passed the checks covers it" for rid in check.uncovered]
    if not lines:
        return None
    return "\n".join([
        "These case/sheet pairs fail the runner's checks and will not be applied as written,",
        "and these lessons are not covered by a case that passes:",
        *lines,
        "Fix each one in place. A pair still failing after this turn is left out on its own;",
        "its lessons stay open for a later attempt, and the other cases go ahead.",
    ])


def _set_aside_pairs(stage: Path, check: _StageCheck, quarantine: Path) -> list[str]:
    """Move every problem pair's files out of the stage into *quarantine*,
    so `_prepared_recipe` sees only the pairs that passed. Returns the
    stage-relative paths moved."""
    moved: list[str] = []
    for stem in sorted(check.problems):
        for sub in ("cases", "sheets"):
            path = stage / sub / f"{stem}.yaml"
            if path.is_file():
                moved.append(_quarantine_move(stage, path, quarantine))
    return moved


#: The disposition reason of a lesson no valid case covered this attempt
#: (2026-09-27, audit finding 3). It keeps the lesson open; when nothing
#: else of the packet is, the packet goes back to a fresh model attempt.
_NOT_COVERED = "not-covered"


def _open_inputs(packet: dict) -> list[dict]:
    """The packet's input rows whose lesson has no terminal disposition --
    what a fresh attempt still has to decide."""
    dispositions = packet.get("dispositions") or {}
    return [
        row for row in packet.get("inputs") or []
        if (dispositions.get(row["record"]) or {}).get("state") not in _RUN_TERMINAL_DISPOSITIONS
    ]


def _only_uncovered_open(manifest: dict, packet: dict) -> bool:
    """True when every case recipe and maintenance operation of the packet
    is settled and each lesson still open is one no valid case covered:
    the only way forward is another model attempt for those lessons."""
    recipes = manifest.get("cases") or {}
    if any(
        (recipes.get(case_id) or {}).get("phase") not in _TERMINAL_CASE_PHASES
        for case_id in packet.get("case_ids") or []
    ):
        return False
    if any(op.get("state") not in {"applied", "refused"} for op in packet.get("maintenance") or []):
        return False
    dispositions = packet.get("dispositions") or {}
    still_open = _open_inputs(packet)
    return bool(still_open) and all(
        (dispositions.get(row["record"]) or {}).get("reason") == _NOT_COVERED
        for row in still_open
    )


def _stage_repair_message(
    home: Path, stage: Path, check: _StageCheck, selected_status: dict[str, object]
) -> str | None:
    """Everything the one repair turn is told about a stage that passed as
    a whole: its failing pairs and uncovered lessons, the case writer's
    rules, and the lines the ledger would refuse (pairs that failed are
    left out of the ledger preview)."""
    return "\n\n".join(filter(None, [
        _pair_message(check),
        _case_rule_message(stage),
        _ledger_repair_message(home, stage, selected_status, skip=set(check.problems)),
    ])) or None


def _quarantine_dir(home: Path, run_id: str, packet_index: int, attempt: int) -> Path:
    """The run-scoped quarantine directory for one packet attempt, in the
    cache and outside the run directory the session may write in."""
    return (
        steward_dir(home) / "quarantine" / run_id
        / f"packet-{packet_index:04d}" / f"attempt-{attempt}"
    )


def _session_spec(
    home: Path, run_dir: Path, prompt: str, *, label: str, lessons: int = 1,
    run_id: str | None = None, shared_brief: Path | None = None,
) -> invocation.SessionSpec:
    timeout_value, _source = settings.resolve_setting(
        home, settings.by_name("steward.timeout_secs")
    )
    timeout = cast(int | float | str, timeout_value)
    per_lesson_value, _source = settings.resolve_setting(
        home, settings.by_name("steward.turns_per_lesson")
    )
    per_lesson = int(cast(int | str, per_lesson_value))
    # A local import: `serve` imports this module. The read-only resolver,
    # not `session_copies.sessions_dir` (whose `worker.cache_dir` creates
    # the cache), because `doctor`'s containment row builds this spec and
    # doctor writes nothing (`Doc-0`); both name the same directory.
    from .serve import cache_dir_readonly

    containment = invocation.containment_for(
        "steward",
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=_DISALLOWED_TOOLS,
        stage_dir=run_dir,
        # 2026-09-28 (follow-up 5): never the kept session copies.
        sessions_dir=cache_dir_readonly(home) / "sessions",
    )
    return invocation.SessionSpec(
        surface="steward",
        prompt=prompt,
        cwd=run_dir,
        timeout=float(timeout),
        containment=containment,
        log=lambda message: _journal(home, {"ts": chrono.now_iso(),
            **({"run_id": run_id} if run_id else {}), "status": "model-log", "message": message}),
        label=label,
        # U4b (2026-09-19): `cwd` is the packet's stage directory --
        # where the session runs and the only place it may write -- and
        # carries no `config.yaml`. The seam reads its settings (the
        # Claude Code binary, the model, the turn bound, the spend
        # bound, the provider, the backend) from THIS field instead.
        ledger_home=home,
        # Claude Code's auto-memory off (2026-09-24): a note one session
        # wrote under the stage-keyed memory folder would reach later
        # sessions (`invocation.NO_AUTO_MEMORY_ENV`).
        extra_env=invocation.NO_AUTO_MEMORY_ENV,
        # The turn limit grows with the batch: `steward.turns_per_lesson`
        # for each lesson in it (the user's instruction, 2026-09-19). It
        # stops a runaway session; it is never a reason to discard one
        # that finished.
        max_turns=per_lesson * max(lessons, 1),
        # 2026-09-26: the brief's shared part (method, conditions, output
        # contract) is appended to the system prompt from this file, and the
        # system prompt is kept free of per-session text, so a run's later
        # calls read it from the prompt cache. `prompt` is the per-packet
        # part. The doctor's containment probe passes no file.
        append_system_prompt_file=shared_brief,
        exclude_dynamic_sections=shared_brief is not None,
        # 2026-09-28: every session of one run keeps its transcript copy in
        # one folder, `<cache>/sessions/steward/<run id>/`.
        transcript_group=run_id,
    )


def _attempt_transcript(outcome: object) -> dict:
    """2026-09-28 (the user's words: "go ahead and just capture
    everything"): the call's transcript copy for its `attempts` row --
    ``{"session": {session_id, path, bytes, entries, assistant_blocks}}``
    or ``{"session": {session_id, error}}`` -- or nothing when no copy was
    attempted (`sdk.capture_sessions` off, or a fake backend). Counts
    only; the path is relative to the cache directory."""
    transcript = getattr(outcome, "transcript", None)
    return {"session": dict(transcript)} if isinstance(transcript, dict) else {}


def _attempt_usage(outcome: object) -> dict:
    """2026-09-26: a call's prompt-cache counts for its `attempts` row --
    ``{"usage": {"first_response": {...}, "session": {...}}}`` -- or nothing
    when the backend reported none (a fake, or an SDK without usage)."""
    first = getattr(outcome, "usage_first_response", None)
    session = getattr(outcome, "usage_session", None)
    if first is None and session is None:
        return {}
    return {"usage": {"first_response": first, "session": session}}


def _repair_spec(spec: invocation.SessionSpec, error: str) -> invocation.SessionSpec:
    return invocation.SessionSpec(
        surface=spec.surface,
        prompt=(
            spec.prompt
            + "\n\n=== repair ===\nA check of the stage files you wrote failed. "
            + "Repair them in place and do nothing else. What failed:\n"
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
        # Carried: the repair round runs with auto-memory off too.
        extra_env=spec.extra_env,
        # Carried (2026-09-26): the repair round is a NEW session. Without
        # the file it would run with no method, no output contract and no
        # conditions; with it, it reads them from the cache as well.
        append_system_prompt_file=spec.append_system_prompt_file,
        exclude_dynamic_sections=spec.exclude_dynamic_sections,
        # Carried (2026-09-28): the repair turn's transcript copy sits
        # beside its decision call's.
        transcript_group=spec.transcript_group,
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


def _reconsidered_by(case_data: object) -> frozenset[str]:
    """S-73 item 6: the record ids a staged ``kind: reconsider`` case
    covers -- the lines the preview widens as apply time will."""
    if not isinstance(case_data, dict) or case_data.get("kind") != "reconsider":
        return frozenset()
    return frozenset(str(rid) for rid in case_data.get("records") or [])


def _forced_parking_reason(
    home: Path, sheet_path: Path, reconsidered: frozenset[str] = frozenset()
) -> str | None:
    """Return the policy reason that prevents this sheet from dispatching.
    *reconsidered* (S-73 item 6): the lines a staged reconsider case covers
    preview with its widening, the same as :func:`_ledger_repair_message`."""
    raw = _read_yaml(sheet_path)
    if not isinstance(raw, dict):
        return None
    # U3b (S-72, 2026-09-28): a hook route is no longer parked here -- the
    # steward decides hooks itself; the batch dispatches it (actor steward,
    # `batch.HOOK_ROUTING_ACTORS`) and activation stays behind the human's
    # `overseer.hook_activation` (off: placed, with the delegated receipt).
    preview = batch.dry_run(
        home, _sheet_without_case(sheet_path), actor="steward",
        hook_activation=config.hook_activation_enabled(home),
        reconsidered=reconsidered,
    )
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


#: S-71 §5: the kinds the repair turn hands back to the model -- the line
#: itself is wrong, or its destination cannot take it here. `status` is
#: added per line, only when the lesson's status is still the one the run
#: selected it with (the steward's own mistake, not a lesson that moved on).
_REPAIRABLE_KINDS = frozenset({"bad-line", "destination-unavailable"})


def _status_unchanged(home: Path, record_id: str, selected_status: object) -> bool:
    """True only when the lesson's status is known to be the one the run
    selected it with."""
    if not isinstance(selected_status, str):
        return False
    try:
        path = ledger_ops.find_record_path(home, record_id)
        return ledger_ops.read_record_or_refuse(path).status == selected_status
    except ledger_ops.LedgerOpsError:
        return False


def _reconsider_status_problem(
    home: Path, record_id: str, selected_status: object
) -> str | None:
    """2026-10-07 (run-9858d321b158): the refusal `verbs.reconsider` gives
    *record_id* at apply time for its STATUS, in the verb's own words and
    from the verb's own check (`ledger_ops.require_status` over
    `RECONSIDERABLE_STATUSES`), when the lesson's status is still the one
    the run selected it with -- the steward's own mistake, known at
    selection time -- else `None`. A lesson that moved on since selection
    is left to apply time, as every `status` refusal of one is (S-71 §4.2)."""
    if not _status_unchanged(home, record_id, selected_status):
        return None
    refusal = _reconsider_status_refusal(home, record_id)
    return refusal_text(refusal) if refusal is not None else None


#: S-81: the sheet keys that name a lesson a line acts on -- the item's own
#: `id`, and a `supersede`'s `new_id` (the lesson named its replacement).
_HELD_LINE_KEYS = ("id", "new_id")


def _held_sentence(record_id: str, rows: list[dict]) -> str:
    """S-81: why a line on *record_id* is refused, naming each parked case
    that holds it and that case's reason."""
    named = ", ".join(
        f"{row.get('case')} ({row.get('parked_reason') or 'no reason given'})" for row in rows
    )
    return (
        f"{record_id}: the overseer holds this lesson (parked case {named}); write no "
        "line for it until the overseer decides -- you may add a note to that case in "
        "overseer-notes.yaml"
    )


def _held_lines(
    home: Path, items: object, held: dict[str, list[dict]] | None = None
) -> list[dict]:
    """S-81: the lines of a sheet (its raw `items` list) that name a lesson
    the overseer holds (`cases.held_lessons`), shaped like case-result
    items: kind `bad-line` -- the steward's own line is the mistake -- and
    :func:`_held_sentence` as the detail. The one check behind the repair
    turn's preview (:func:`_ledger_repair_message`) and apply time
    (:func:`_apply_packet`)."""
    if not isinstance(items, list):
        return []
    if held is None:
        held = cases.held_lessons(home)
    out: list[dict] = []
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        named = next(
            (str(item[key]) for key in _HELD_LINE_KEYS if str(item.get(key)) in held), None
        )
        if named is not None:
            out.append({
                "n": n, "id": named, "verb": str(item.get("verb")), "rc": 1,
                "state": "refused", "detail": _held_sentence(named, held[named]),
                "kind": "bad-line",
            })
    return out


def _holds_for(home: Path, case_id: str, case_records: list[str]) -> dict[str, list[dict]]:
    """S-81: the holds a case's lines are checked against at apply time.
    A case already in the ledger is being re-driven (a park or a receipt
    that did not land, a retried line): its decision predates any hold on
    its OWN lessons, which only its own outcome can have caused -- a lesson
    it parked now -- so those are not held against it, and every other
    line is checked as on the first apply."""
    held = cases.held_lessons(home)
    if any(row.get("case") == case_id for row in cases.list_cases(home)):
        return {rid: rows for rid, rows in held.items() if rid not in case_records}
    return held


def _sheet_items(sheet_path: Path) -> object:
    """A staged sheet's raw `items`, or `None` when it has none."""
    raw = _read_yaml(sheet_path)
    return raw.get("items") if isinstance(raw, dict) else None


def _ledger_repair_message(
    home: Path, stage: Path, selected: dict[str, object], skip: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """S-71 §5: the lines of the staged sheets the ledger would refuse as
    written, when the refusal is the model's to fix -- or `None`.

    A case the model parked, or one the runner will park
    (`_forced_parking_reason`, `_refiling_reason`), is skipped: none of
    its lines is applied.
    Each other sheet is previewed exactly as apply time will (the same
    `[reopen, verb]` sequence rule). A `status` refusal is collected only
    when the lesson's status is unchanged since selection, and never for a
    lesson a staged `kind: reconsider` case of the same pair covers. The
    preview runs without that case (it is not in the ledger yet), but
    since S-73 item 6 it passes the covered ids to `batch.dry_run`
    (`reconsidered=`), which widens those lines as the real case will at
    apply time: every check after the status gate runs -- a
    re-decision's hook shape, its replay, its destination -- so a bad
    example is found while the repair turn can still fix it. A pair in
    *skip* (its stem) failed the runner's own per-pair check and is left
    out (2026-09-27).

    2026-10-07: a staged `kind: reconsider` case is also held to the
    status `verbs.reconsider` needs of each lesson it names
    (:func:`_reconsider_status_problem`). Before, a reconsider case naming
    a PENDING lesson passed every check here and was refused only at apply
    time, after the one repair turn was gone (run-9858d321b158: two
    pending lessons an earlier case had moved).

    S-81 (2026-10-08): a line naming a lesson the overseer holds is
    flagged by name (:func:`_held_lines`), before the ledger preview of
    that sheet; apply time refuses the whole case for it."""
    found: list[str] = []
    case_found: list[str] = []
    held = cases.held_lessons(home)
    for case_path in sorted((stage / "cases").glob("*.yaml")):
        if case_path.stem in skip:
            continue
        sheet_path = stage / "sheets" / case_path.name
        case_data = _read_yaml(case_path)
        if not isinstance(case_data, dict) or case_data.get("kind") == "parked":
            continue
        reconsidered = _reconsidered_by(case_data)
        if _forced_parking_reason(home, sheet_path, reconsidered) is not None:
            continue
        if _refiling_reason(home, sheet_path) is not None:
            continue
        for record_id in dict.fromkeys(str(rid) for rid in case_data.get("records") or []):
            if record_id not in reconsidered:
                continue
            problem = _reconsider_status_problem(home, record_id, selected.get(record_id))
            if problem is not None:
                case_found.append(f"- cases/{case_path.name}: {problem}")
        held_lines = _held_lines(home, _sheet_items(sheet_path), held)
        found.extend(
            f"- sheets/{sheet_path.name}: item {line['n']} ({line['verb']} {line['id']}): "
            f"{line['detail']}"
            for line in held_lines
        )
        sheet = _sheet_without_case(sheet_path)
        preview = batch.dry_run(
            home, sheet, actor="steward",
            hook_activation=config.hook_activation_enabled(home),
            reconsidered=reconsidered,
        )
        for line in _held_refusals(preview, sheet):
            if line.get("n") in {held_line["n"] for held_line in held_lines}:
                continue  # named above, by the hold
            kind = line.get("kind")
            record_id = str(line.get("id"))
            if kind == "status":
                if record_id in reconsidered:
                    continue
                if not _status_unchanged(home, record_id, selected.get(record_id)):
                    continue
            elif kind not in _REPAIRABLE_KINDS:
                continue
            found.append(
                f"- sheets/{sheet_path.name}: item {line.get('n')} "
                f"({line.get('verb')} {record_id}): {line.get('detail') or kind}"
            )
    sections: list[str] = []
    if found:
        sections.append("\n".join([
            "The ledger would refuse these lines of your sheets as written:",
            *found,
            "Fix each one: rewrite the line, choose a different destination or verb, or park the case",
            "with the reason that names its question. Leave every other file as it is.",
        ]))
    if case_found:
        sections.append("\n".join([
            "The ledger would refuse these reconsider cases as written:",
            *case_found,
            *_RECONSIDER_REPAIR_ADVICE,
        ]))
    return "\n\n".join(sections) or None


#: What the repair turn says under a `kind: reconsider` case naming a lesson
#: whose status a reconsider cannot take (2026-10-07). The statuses are the
#: verb's own (`ledger_ops.RECONSIDERABLE_STATUSES`).
_RECONSIDER_REPAIR_ADVICE = (
    "A `kind: reconsider` case is only for a lesson an earlier case placed, rejected or",
    f"deferred (status {', '.join(sorted(ledger_ops.RECONSIDERABLE_STATUSES))}). A lesson that is",
    "pending -- even one an earlier case moved, or one that came back to you as a reconsider",
    "input -- is decided with a `kind: resolution` case: change the case's `kind` to",
    "`resolution` and keep or fix its sheet. Leave every other file as it is.",
)


def _as_recorded(data: dict, *, parked_entry: bool = False) -> dict:
    """A staged case as the runner will hand it to `cases.record`: the
    evidence items the runner drops (`cases.split_runner_evidence`) are
    gone, and a parked case carries the fields the runner sets for it
    (`_prepared_recipe`; `_maintain_manifest` for a parked.yaml entry)."""
    data, _dropped = cases.split_runner_evidence(dict(data))
    if parked_entry:
        return {**data, "kind": "parked", "outcome": "parked", "parked_for": "overseer"}
    if data.get("kind") == "parked":
        return {**data, "outcome": "parked", "parked_for": "overseer"}
    return data


def _case_rule_message(stage: Path) -> str | None:
    """2026-09-26: the staged cases the case writer would refuse as written
    -- its schema, its secret scan and its heading refusal, run through
    `cases.check_case_data`, the writer's own rules -- or `None`.

    Before this, those rules ran only when the case was written, after the
    one repair turn was gone. A file this cannot read is skipped: the
    format check names it. A case still refused after the repair turn is
    refused alone at apply time; the other cases of the packet proceed."""
    found: list[str] = []
    for case_path in sorted((stage / "cases").glob("*.yaml")):
        try:
            data = _read_yaml(case_path)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            cases.check_case_data(_as_recorded(data), withhold_spans=True)
        except cases.CaseError as exc:
            found.append(f"- cases/{case_path.name}: {exc}")
    try:
        entries = _stage_entries(stage / "parked.yaml")
    except ValueError:
        entries = []
    for number, entry in enumerate(entries, start=1):
        try:
            cases.check_case_data(_as_recorded(entry, parked_entry=True), withhold_spans=True)
        except cases.CaseError as exc:
            found.append(f"- parked.yaml entry {number}: {exc}")
    if not found:
        return None
    return "\n".join([
        "The case checker would refuse these cases as written:",
        *found,
        "Fix each one in place. A case still refused after this turn is refused on its own,",
        "and its lessons are not decided this run; the other cases go ahead.",
    ])


def _first_pass_path(home: Path, run_id: str, packet_index: int) -> Path:
    """Where a packet's validated first pass is kept while its repair turn
    runs (2026-09-27, audit finding 2): in the cache, OUTSIDE the run
    directory the session may write in, so the repair session cannot touch
    it."""
    return steward_dir(home) / "first-pass" / run_id / f"packet-{packet_index:04d}"


def _flag_lines(message: str | None) -> list[str]:
    """The flagged lines of a repair message (`_case_rule_message`,
    `_ledger_repair_message`): one ``- <file>: ...`` line per problem."""
    return [line for line in (message or "").splitlines() if line.startswith("- ")]


def _flag_key(line: str) -> str:
    """The file (or parked.yaml entry) a flagged line is about."""
    return line[2:].split(": ", 1)[0]


def _repair_made_worse(before: list[str], after: list[str]) -> bool:
    """A repair turn left the stage worse than the first pass when it
    flags more lines, or flags a file the first pass had clean."""
    return len(after) > len(before) or bool(
        {_flag_key(line) for line in after} - {_flag_key(line) for line in before}
    )


def _returned_for(home: Path, inputs: list[dict]) -> dict[str, dict]:
    """S-71 §4.6: for each input of this packet that a committed run record
    sent back at its CURRENT input version, the case that decided it and
    the ledger's words -- what the brief's sent-back block shows."""
    # U3a: a row selected under the record's blob also matches a
    # disposition written under its proposal blob before the change.
    wanted = {
        row["record"]: {row.get("version"), row.get("legacy_version")} - {None}
        for row in inputs
        if isinstance(row, dict) and isinstance(row.get("record"), str)
    }
    out: dict[str, dict] = {}
    for manifest in committed_manifests(home):
        for packet in manifest.get("packets") or []:
            for record_id, row in (packet.get("dispositions") or {}).items():
                if (
                    record_id in wanted
                    and isinstance(row, dict)
                    and row.get("state") == "returned"
                    and row.get("input_version") in wanted[record_id]
                ):
                    out[record_id] = {
                        "case": row.get("case"),
                        "lines": [str(row.get("reason") or row.get("kind") or "")],
                    }
    return out


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


def _withheld_refusal(texts: list[str]) -> str | None:
    """The secret-scan refusal for *texts*, or `None` when they scan clean.
    The message is committed into the run record, so it names each hit's
    rule and offsets, never the matched span (2026-09-26)."""
    hits = [hit for text in texts for hit in secret_scan(text)]
    if not hits:
        return None
    return format_refusal([dataclass_replace(hit, span="[withheld]") for hit in hits])


def _predecessor_fill(home: Path, stage: Path, predecessors: dict) -> dict[str, str]:
    """Which staged case the runner names as the successor of its lessons'
    predecessor case (`supersedes`), by stem. A case is superseded once --
    `cases.record` refuses a second successor -- so a predecessor is filled
    in on ONE case at most (2026-10-07, gate S1 way 1), and on none when:

    * a staged case names it itself;
    * the ledger shows it superseded already -- an earlier attempt of the
      same packet decided another of its lessons (2026-10-08, gate S1b F2:
      filled in again, the case writer refused the case);
    * the case's records span more than one predecessor (refused later,
      by `_prepared_recipe`).

    When two staged cases could take it, a ``kind: reconsider`` case does,
    since it cannot record without one; a ``resolution`` case records
    either way (gate S1b F3: file-name order decided, and a reconsider
    case that sorted second was refused). Cases of one kind go in file
    order."""
    staged = [
        (path.stem, _read_yaml(path)) for path in sorted((stage / "cases").glob("*.yaml"))
    ]
    claimed = {
        str(data["supersedes"])
        for _stem, data in staged
        if isinstance(data, dict) and data.get("supersedes")
    }
    claimed |= {str(row.get("case")) for row in cases.list_cases(home) if row.get("superseded_by")}
    fill: dict[str, str] = {}
    for reconsider_first in (True, False):
        for stem, data in staged:
            if not isinstance(data, dict) or data.get("supersedes"):
                continue
            if (data.get("kind") == "reconsider") is not reconsider_first:
                continue
            named = {
                predecessors[rid] for rid in data.get("records") or [] if rid in predecessors
            }
            if len(named) != 1:
                continue
            (predecessor,) = named
            if predecessor not in claimed:
                fill[stem] = str(predecessor)
                claimed.add(str(predecessor))
    return fill


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
    # 2026-09-27 (audit finding 3): an attempt that decides the lessons an
    # earlier attempt left uncovered keeps that attempt's (settled) cases
    # and operations beside its own.
    packet_case_ids: list[str] = list(packet.get("case_ids") or [])
    earlier_maintenance: list[dict] = list(packet.get("maintenance") or [])
    dropped_rows: list[dict] = []
    versions = {row["record"]: row.get("version") for row in packet.get("inputs") or []}
    fill = _predecessor_fill(home, stage, predecessors)
    for case_path in sorted((stage / "cases").glob("*.yaml")):
        stem = case_path.stem
        sheet_path = stage / "sheets" / f"{stem}.yaml"
        case_data = _read_yaml(case_path)
        if not isinstance(case_data, dict):
            raise ValueError(f"{case_path.name}: case must be a mapping")
        case_data = dict(case_data)
        case_data["run_id"] = run_id
        # 2026-09-25 (run-d8f5e198ff4f): an evidence item quoting a heading
        # line is dropped HERE, before the case text is frozen into the
        # committed run record, so the quote never reaches the ledger; the
        # decision records with the rest of its evidence. 2026-09-26
        # (run-1ca3de428b35): so is an item whose quote or ref matched the
        # secret scan -- dropped before the prepared-text scan below, which
        # would otherwise refuse the whole packet over it.
        case_data, dropped_evidence = cases.split_runner_evidence(case_data)
        predecessor_ids = {
            predecessors[rid]
            for rid in case_data.get("records") or []
            if rid in predecessors
        }
        if len(predecessor_ids) > 1:
            raise ValueError(
                f"{case_path.name}: records span more than one predecessor case"
            )
        if predecessor_ids and not case_data.get("supersedes") and stem in fill:
            case_data["supersedes"] = fill[stem]
        parking_reason = _forced_parking_reason(
            home, sheet_path, _reconsidered_by(case_data)
        )
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
            # own check fires too (a plain host's committed file), its
            # reason wins. (Until U3b a hook route was one of the runner's
            # own checks; since S-72 the steward decides hooks.)
            parking_reason = str(case_data.get("parked_reason"))
        if parking_reason is None:
            # 2026-10-06: a case that would move a lesson the steward has
            # already moved is a disagreement about where it belongs, and
            # is parked for the overseer (`_FILING_MOVE_LIMIT`). Checked
            # last, so a case the model parked keeps its own reason.
            parking_reason = _refiling_reason(home, sheet_path)
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
        refusal = _withheld_refusal(
            [case_text, sheet_text, *(row["ref"] for row in dropped_evidence)]
        )
        if refusal is not None:
            # Nothing of this case's text is frozen into the run record: it
            # holds the hit. 2026-10-08 (gate S1b F6): its lessons used to
            # get a bare `refused` row here -- no kind, no case -- which
            # `_terminal_versions` counts as a decision, so a LESSON input
            # was stranded for good. A hit in the steward's own text is S-71's
            # `bad-line` (`batch._typed_kind`: a secret in the line, not the
            # record), so the case is frozen as a stub -- its records and the
            # scan's rule and offsets, no text -- that apply time settles as
            # a case refused before it was recorded
            # (:func:`_refuse_unrecorded_case`): sent back once, parked on a
            # second refusal of the same version.
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                "status": "refused", "stage_file": case_path.name, "error": refusal})
            stub_records = [
                str(rid) for rid in dict.fromkeys(case_data.get("records") or [])
                if rid in versions
            ]
            recipes[case_id] = {
                "case": "", "sheet": "", "sheet_name": sheet_path.name,
                "sheet_sha": None, "sheet_digest": None, "items": [],
                "maintenance": [], "dispositions": [], "packet": packet["index"],
                "phase": "prepared", "parking_reason": None, "dropped_evidence": [],
                "unrecorded_refusal": {
                    "records": stub_records,
                    "lines": [
                        {"id": rid, "verb": "case", "rc": 1, "state": "refused",
                         "detail": refusal, "kind": "bad-line"}
                        for rid in stub_records
                    ],
                    "error": refusal,
                },
            }
            packet_case_ids.append(case_id)
            continue
        dropped_rows.extend(
            {"case": case_id, "stage_file": case_path.name, **row} for row in dropped_evidence
        )
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
            "dropped_evidence": dropped_evidence,
        }
        packet_case_ids.append(case_id)

    maintenance: list[dict] = []
    for kind, filename in (
        ("statement", "statements.yaml"),
        ("model", "model-updates.yaml"),
        ("parked-case", "parked.yaml"),
        # S-81: a note for the overseer on a lesson it holds.
        ("note", _NOTES_FILE),
    ):
        for item in _stage_entries(stage / filename):
            payload = dict(item)
            parked_dropped: list[dict] = []
            if kind == "parked-case":
                # 2026-09-25/26: as for a decided case above -- dropped
                # before the payload is frozen into the committed run record
                # and before the secret scan below.
                payload, parked_dropped = cases.split_runner_evidence(payload)
            refusal = _withheld_refusal(
                [_yaml_text(payload), *(row["ref"] for row in parked_dropped)]
            )
            if refusal is not None:
                # 2026-09-26: this operation alone is refused, and its
                # payload (which holds the hit) is never frozen.
                _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                    "status": "refused", "stage_file": filename, "error": refusal})
                payload, parked_dropped = {}, []
            ordinal = len(earlier_maintenance) + len(maintenance) + 1
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
                "state": "pending" if refusal is None else "refused",
                "baseline": None,
                "result": None if refusal is None else {"state": "refused", "error": refusal},
            }
            if kind == "parked-case":
                operation["reserved_case_id"] = _new_case_id()
                operation["dropped_evidence"] = parked_dropped
                dropped_rows.extend(
                    {"case": operation["reserved_case_id"], "stage_file": filename, **row}
                    for row in parked_dropped
                )
            maintenance.append(operation)

    for row in dropped_rows:
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
            "status": "evidence-dropped", **row})
    packet["case_ids"] = packet_case_ids
    packet["maintenance"] = [*earlier_maintenance, *maintenance]
    packet["phase"] = "prepared"
    packet["failure"] = None
    packet["bound"] = None
    packet["dispositions"] = dict(packet.get("dispositions") or {})


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
            # Sweep 2, R2 (2026-09-27): judge THIS record's own target(s)
            # only. A ledger-wide recompile here rewrote every other stale
            # host target while checking one item, and any unrelated
            # skipped target (a user's uncommitted edit to another
            # SKILL.md) became this item's `unresolved-host`, halting it
            # and every later case on every attempt.
            host = verbs.recompile(home, no_push=True, only_records=[item.id])
            refused = verbs.recompile_refusals(host, item.id)
            if refused:
                completed[item.n] = batch.ItemResult(
                    n=item.n,
                    id=item.id,
                    verb=item.verb,
                    rc=1,
                    sha=sha,
                    state="unresolved-host",
                    detail=refused[0],
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


#: S-81: the stage file of the steward's notes for the overseer, one entry
#: per note, on a lesson the overseer holds (`steward_prompt.OUTPUT_CONTRACT`).
_NOTES_FILE = "overseer-notes.yaml"
#: ... the observation kind a note is recorded as (`cases.OBSERVE_KINDS`):
#: `examined`, what the steward did. Never `statement` or
#: `dependency-moved`, which with a `ref` would queue the case for a
#: reconsider (`_reconsider_proposals`), and none of the others fits.
_NOTE_KIND = "examined"
#: ... and its longest text, the bound of a committed failure detail.
_NOTE_MAX = _FAILURE_DETAIL_MAX


def _note_observation_id(case_id: str, operation_id: str) -> str:
    """The reserved id of a note's observation, so a re-driven operation
    lands it once (as `_observe_abandonment` does)."""
    return "obs-" + hashlib.sha256(f"{case_id}:{operation_id}".encode("utf-8")).hexdigest()[:8]


def _add_overseer_note(home: Path, payload: dict, operation_id: str) -> str:
    """S-81: one entry of `overseer-notes.yaml` -- ``{case, text}`` -- as an
    `examined` later observation by the steward on that case, which must be
    one the overseer has yet to decide (`cases.awaiting_overseer`). The
    only thing the steward may do about a lesson the overseer holds (the
    user's words, 2026-10-08: "it can add notes for the overseer if it
    wants to"). The text is folded to one line; `cases.observe` scans it
    and refuses a heading line. Returns the observation id."""
    unknown = sorted(set(payload) - {"case", "text"})
    if unknown:
        raise ValueError(f"{_NOTES_FILE}: unknown key(s) {unknown}; an entry is case and text")
    case_id, text = payload.get("case"), payload.get("text")
    flat = " ".join(str(text).split()) if isinstance(text, str) else ""
    if not isinstance(case_id, str) or not flat:
        raise ValueError(f"{_NOTES_FILE}: every entry needs a case id and a non-empty text")
    if len(flat) > _NOTE_MAX:
        raise ValueError(f"{_NOTES_FILE}: a note is at most {_NOTE_MAX} characters")
    if case_id not in {row.get("case") for row in cases.awaiting_overseer(home)}:
        raise ValueError(
            f"{_NOTES_FILE}: {case_id} is not a parked case the overseer has yet to "
            "decide; a note goes only on one of those"
        )
    return cases.observe(
        home, case_id, _NOTE_KIND, text=flat, by="steward",
        reserved_id=_note_observation_id(case_id, operation_id),
    )


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
    elif operation["kind"] == "note":
        # Landed before the overseer decided the case, then the run died:
        # the note is on the case, whatever the case is now.
        case_id = payload.get("case")
        if isinstance(case_id, str) and cases.CASE_ID_RE.fullmatch(case_id):
            reserved = _note_observation_id(case_id, str(operation["id"]))
            try:
                view = cases.show(home, case_id, evidence_only=False)
            except (cases.CaseError, OSError):
                return None
            if f"- {reserved} " in view.sections.get("Later observations", ""):
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
                elif operation["kind"] == "note":
                    recovered = {
                        "state": "applied",
                        "id": _add_overseer_note(home, payload, str(operation["id"])),
                    }
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
            # A secret-scan span is withheld: the error is committed into
            # the run record (2026-09-26).
            error = refusal_text(exc)
            recovered = {"state": "refused", "error": error}
            status = {
                "statement": "statement-refused", "model": "model-update-refused",
                "note": "note-refused",
            }.get(operation["kind"], "parked-case-refused")
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": status, "error": error})
        operation_id = operation["id"]
        assert recovered is not None
        _update_manifest(
            home, run_id, reason=f"maintenance result {operation_id}",
            update=lambda current, op_id=operation_id, result=recovered: next(
                op for op in current["packets"][packet_index - 1]["maintenance"]
                if op["id"] == op_id
            ).update(state=result["state"], result=result),
        )


def _excused_after_reopen(shown: batch.DryRunItem, reopened: set[str]) -> bool:
    """The one refusal a sanctioned ``[reopen X, <verb> X]`` pair excuses
    on its later line: kind ``status``. The preview cannot see the reopen
    land, so it checks that line against the lesson's status before the
    reopen -- a refusal the reopen itself removes. Any other kind (a
    ``bad-line``, a destination that cannot take it) is the line's own and
    is a refusal like any other (2026-10-07; gate-l10 probe P3: before,
    every kind was excused, so a bad line after a reopen never reached the
    repair turn, and at apply the reopen landed alone)."""
    return shown.id in reopened and shown.kind == "status"


def _preview_is_clean_for_sequence(preview: batch.DryRunResult, items: batch.Sheet) -> bool:
    """Account for a sanctioned [reopen, verb] sheet's sequential state change
    (:func:`_excused_after_reopen`)."""
    if preview.ok:
        return True
    reopened: set[str] = set()
    for shown, item in zip(preview.items, items, strict=True):
        if item.verb == "reopen" and shown.state != "would-refuse":
            reopened.add(item.id)
            continue
        if shown.state == "would-refuse" and not _excused_after_reopen(shown, reopened):
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


#: The parked reasons a runner's successor case carries: the cap close-out
#: (`attempts-exhausted`) and the S-71 park-now (`ledger-refused`).
_SUCCESSOR_PARKED_REASONS = frozenset({"attempts-exhausted", "ledger-refused"})


def _successor_case_for(home: Path, run_id: str, record_id: str) -> str | None:
    """02-schema §3a: "a successor that already exists is reused, never
    duplicated". Looked up from committed cases rather than matched on
    content, because the evidence reference names HEAD and HEAD moves.
    Either runner reason counts, so a re-drive after a partial write
    reuses the case instead of writing a second one."""
    for row in cases.list_cases(home, only_ok=True, record_id=record_id):
        if row.get("parked_reason") not in _SUCCESSOR_PARKED_REASONS:
            continue
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


def _observe_abandonment(
    home: Path, case_id: str, record_id: str, successor: str, *, text: str | None = None
) -> None:
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
        text=text or (
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


def _notify_environment_hold(home: Path, run_id: str, cause: str) -> None:
    """Once per DISTINCT cause (2026-09-27, fail-state audit finding 4):
    the steward is held, not failing, until the environment is fixed."""
    summary = (
        f"self-learn steward: run {run_id} is held — the model call cannot run "
        f"here: {cause}. Nothing was counted; it retries on its next attempt."
    )
    try:
        overseer_notify.send(home, "routine", summary, [run_id])
    except Exception as exc:  # noqa: BLE001 -- a notification never fails a run
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
            "status": "notify-failed", "error": _short_cause(exc)})


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


def _refusal_lines(items: list, record_id: str, out: list[str] | None = None) -> list[str]:
    """The ledger's own words for why this record's items did not apply,
    one `"<verb> <id>: <detail[:240]>"` line per distinct refusal."""
    out = [] if out is None else out
    for item in items:
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


def _ledger_refusals(manifest: dict, packet: dict, record_id: str) -> list[str]:
    """The ledger's own words for why this record's sheet items did not
    apply, read from the case results the packet's attempts committed
    (`_apply_packet` stores every `BatchResult` on its case recipe)."""
    out: list[str] = []
    recipes = manifest.get("cases") or {}
    for case_id in packet.get("case_ids") or []:
        result = (recipes.get(case_id) or {}).get("result") or {}
        _refusal_lines(result.get("items") or [], record_id, out)
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
        question, because = _cap_close_out_texts(record_id, attempts, kind, record_detail)
        try:
            successor = _close_out_record(
                home, run_dir, run_id, packet, packet_index, record_id,
                parked_reason="attempts-exhausted", question=question,
                because=because, detail=record_detail, reference=reference,
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


def _cap_close_out_texts(
    record_id: str, attempts: int, kind: str, detail: str
) -> tuple[str, str]:
    """The question and `because` of an `attempts-exhausted` successor."""
    if "; the ledger refused: " in detail:
        # The steward DID decide; the ledger would not take the items.
        return (
            f"the steward decided {record_id} but the ledger refused the "
            f"decision's items on each of {attempts} attempts; decide this "
            "lesson yourself, using the recorded refusal as evidence (the "
            "steward's own case and sheet are on record beside it)",
            "what stopped the steward was the ledger, not the merits: "
            f"every attempt ended with {kind}, the item refused",
        )
    return (
        f"the steward's decision for {record_id} reached the attempt "
        f"cap after {attempts} attempts without ever being decided; "
        "decide this lesson itself, using the recorded failure reason "
        "as evidence",
        "what stopped the steward was the machinery, not the "
        f"merits: every attempt ended with {kind}",
    )


def _park_now_texts(record_id: str, kind: str, *, recorded: bool = True) -> tuple[str, str]:
    """S-71 §4.5: the question and `because` of a `ledger-refused` successor.

    *recorded* says whether the steward's case reached the ledger. When it
    did not -- the case writer refused it, a line named a lesson the
    overseer holds, or its text matched the secret scan -- no case or sheet
    of it is on record, and the text says so (2026-10-08, gate S1b nit c:
    it said they were "on record beside it" either way)."""
    if recorded:
        return (
            f"the steward decided {record_id} but the ledger refused the decision's "
            "line for a reason neither a retry nor a fresh decision can fix "
            f"({kind}); decide this lesson yourself, using the ledger's words as "
            "evidence (the steward's own case and sheet are on record beside it)",
            f"the ledger, not the merits, stopped this decision: {kind}",
        )
    return (
        f"the steward decided {record_id} but its case was refused before it was "
        "recorded, for a reason neither a retry nor a fresh decision can fix "
        f"({kind}); decide this lesson yourself, using the refusal as evidence "
        "(the steward's case and sheet are not on record)",
        f"the refusal, not the merits, stopped this decision: {kind}",
    )


def _close_out_record(
    home: Path,
    run_dir: Path,
    run_id: str,
    packet: dict,
    packet_index: int,
    record_id: str,
    *,
    parked_reason: str,
    question: str,
    because: str,
    detail: str,
    reference: str,
    observation: str | None = None,
) -> str:
    """Reuse or write one record's parked successor case, and name it on
    the case the record already belonged to. Returns the successor id.

    The ONE writer for both runner reasons: the cap close-out
    (`attempts-exhausted`) and the S-71 park-now (`ledger-refused`).
    `observation`, when given, is the later-observation text for the
    owning case, with `{successor}` standing for the successor's id."""
    successor = _successor_case_for(home, run_id, record_id)
    if successor is None:
        stage_path = run_dir / f"close-out-{packet_index:04d}-{record_id}.yaml"
        _dump_yaml(stage_path, {
            "kind": "parked",
            "trigger": "nightly",
            "outcome": "parked",
            "parked_for": "overseer",
            "parked_reason": parked_reason,
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
        _observe_abandonment(
            home, owning_case, record_id, successor,
            text=observation.replace("{successor}", successor) if observation else None,
        )
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


# ------------------------------------------- ledger refusals (S-71 §4)
#
# Module-level, like the close-out above: the lock invariant's walker
# treats a nested closure as its own node, and these reach the ledger only
# through `_close_out_record` (the lock-owning `cases.record` /
# `cases.observe`) and `_update_manifest`.

#: `_KIND_ACTIONS`' keys, most severe first -- the same order as
#: `batch._KIND_PRECEDENCE`, with `status` resolved (§4.2 step 1), so the
#: actions come out as §4.2 step 2 orders them: refused, retry, park,
#: return, close. First match wins. `refused` first because S-68 forbids
#: retrying or parking a secret-scan block (a retry would end at the cap
#: as a park); `retry` next because every other judgment is re-made on
#: the retry's fresh evidence. Within one action it picks the kind a
#: disposition row names.
_EFFECTIVE_PRECEDENCE = (
    "secret-record", "git", "target-busy", "needs-person", "unclassified",
    "bad-line", "destination-unavailable", "overtaken",
)


@dataclass(frozen=True)
class _Refusal:
    #: the kind the ledger gave the refusal (S-71 §3)
    kind: str
    #: the key into `_KIND_ACTIONS`: `kind`, with `status` resolved
    effective: str
    #: for `overtaken`, what the lesson is now
    moved: str | None = None


def _parked_already(row: object) -> bool:
    """A disposition that already names its parked successor case."""
    return (
        isinstance(row, dict)
        and row.get("state") == "abandoned"
        and bool(row.get("successor_case"))
    )


def _is_park_now_row(row: object) -> bool:
    """A disposition the S-71 park-now wrote, as opposed to the cap
    close-out: both are `abandoned` with a `successor_case`, and only the
    park-now row names the refusal's kind."""
    return isinstance(row, dict) and row.get("state") == "abandoned" and "kind" in row


def _item_kind(item: dict) -> str:
    """The S-71 kind of one failed item of a case result."""
    kind = item.get("kind")
    if isinstance(kind, str) and kind in batch.REFUSAL_KINDS:
        return kind
    state = str(item.get("state") or "")
    if state in _RETRY_ITEM_STATES:
        return "git"
    rc = item.get("rc")
    return batch.refusal_kind(None, rc=rc if isinstance(rc, int) else 1, state=state)


def _moved_on(home: Path, record_id: str, selected_status: object) -> str | None:
    """S-71 §4.2 step 1: what the lesson is now, when that is not the
    status the run selected it with; `None` when it is the same, or when
    the selection-time status is unknown (a row written before S-71)."""
    if not isinstance(selected_status, str):
        return None
    try:
        path = ledger_ops.find_record_path(home, record_id)
    except ledger_ops.RecordNotFound:
        return "record no longer exists"
    except ledger_ops.LedgerOpsError:
        return None
    try:
        current = ledger_ops.read_record_or_refuse(path).status
    except ledger_ops.UnreadableRecord:
        return None
    return None if current == selected_status else f"record is now {current}"


def _applied_earlier(manifest: dict, packet: dict, case_id: str) -> set[str]:
    """Every record an earlier case of this packet applied an item to.

    Read from every committed case result, whichever attempt wrote it: a
    status our own earlier line changed is the steward's doing, never a
    lesson that moved on without it."""
    applied: set[str] = set()
    recipes = manifest.get("cases") or {}
    for earlier in packet.get("case_ids") or []:
        if earlier == case_id:
            break
        result = (recipes.get(earlier) or {}).get("result") or {}
        for item in result.get("items") or []:
            if (
                isinstance(item, dict)
                and item.get("state") in _SUCCESS_RECEIPT_STATES
                and isinstance(item.get("id"), str)
            ):
                applied.add(item["id"])
    return applied


def _record_refusals(
    home: Path,
    record_id: str,
    failed: list[dict],
    items: list[dict],
    *,
    selected_status: object,
    applied_before: set[str],
) -> list[_Refusal]:
    """One `_Refusal` per failed item of this record, `status` resolved:
    `overtaken` when the lesson's status moved since selection (or it no
    longer exists) and no earlier item of the packet applied to it;
    otherwise `bad-line`, the steward's own line."""
    out: list[_Refusal] = []
    for item in failed:
        kind = _item_kind(item)
        if kind != "status":
            out.append(_Refusal(kind, kind))
            continue
        n = item.get("n")
        ours = record_id in applied_before or any(
            other.get("id") == record_id
            and other.get("state") in _SUCCESS_RECEIPT_STATES
            and isinstance(other.get("n"), int)
            and isinstance(n, int)
            and other["n"] < n
            for other in items
        )
        moved = None if ours else _moved_on(home, record_id, selected_status)
        out.append(_Refusal("status", "overtaken" if moved else "bad-line", moved))
    return out


def _deciding(refusals: list[_Refusal]) -> _Refusal:
    """The refusal whose kind decides a record's action (§4.2 step 2)."""
    return min(refusals, key=lambda refusal: _EFFECTIVE_PRECEDENCE.index(refusal.effective))


def _selected_again(home: Path, record_id: str) -> bool:
    """True when the next run will select *record_id* as an ordinary lesson
    input: it is queued (pending, not deferred) at a version no committed
    run has decided. Asked of :func:`_eligible_lessons`, the function that
    selects, so the answer cannot drift from the selection. It reads every
    queued lesson's committed version, which is why only a refused
    `observation:` input asks it (2026-10-07, gate S1 D1)."""
    return any(entry.record.id == record_id for entry, _row in _eligible_lessons(home))


def _returned_before(home: Path, record_id: str, version: str, case_id: str) -> bool:
    """S-71 §4.2: one return per input version. A committed `returned`
    disposition for the same record and version, written by a DIFFERENT
    case, means a fresh decision was refused a second time; the same case
    re-driven is the same decision, not a second one."""
    for manifest in committed_manifests(home):
        for packet in manifest.get("packets") or []:
            row = (packet.get("dispositions") or {}).get(record_id)
            if (
                isinstance(row, dict)
                and row.get("state") == "returned"
                and row.get("input_version") == version
                and row.get("case") != case_id
            ):
                return True
    return False


@dataclass
class _CaseDispositions:
    #: one disposition row per record of the case; a record to park now
    #: stays `unfinished` here until its successor case has landed
    rows: dict[str, dict]
    #: record -> the kind it is parked now for
    park_now: dict[str, str]
    #: a failed item for a record outside the case's own records asked for
    #: a retry, so the case must be re-driven
    retry_outside: bool = False


def _case_dispositions(
    home: Path,
    manifest: dict,
    packet: dict,
    case_id: str,
    case_records: list[str],
    items: list[dict],
    *,
    held: bool,
) -> _CaseDispositions:
    """S-71 §4.2-§4.4 for one case whose receipt landed.

    `items` is the case's result: for a DISPATCHED case every item, each
    record then following §4.2 on its own (a record all of whose items
    applied is `applied`); for a case the PREVIEW held back, only the
    lines the ledger would refuse -- nothing was dispatched, the case is
    one decision, and every record takes the case's most severe action."""
    selected = {row["record"]: row for row in packet.get("inputs") or []}
    applied_before = _applied_earlier(manifest, packet, case_id)
    failed: dict[str, list[dict]] = {}
    for item in items:
        if isinstance(item, dict) and item.get("state") in _FAILED_ITEM_STATES:
            failed.setdefault(str(item.get("id")), []).append(item)
    refusals = {
        rid: _record_refusals(
            home, rid, lines, items,
            selected_status=(selected.get(rid) or {}).get("record_status"),
            applied_before=applied_before,
        )
        for rid, lines in failed.items()
    }
    case_lines: list[str] = []
    for rid in failed:
        _refusal_lines(items, rid, case_lines)
    retry_outside = any(
        _KIND_ACTIONS[_deciding(found).effective] == "retry"
        for rid, found in refusals.items()
        if rid not in case_records and found
    )
    everything = [refusal for found in refusals.values() for refusal in found]
    case_best = _deciding(everything) if held and everything else None
    held_now = cases.held_lessons(home) if failed else {}
    rows: dict[str, dict] = {}
    park_now: dict[str, str] = {}
    for rid in case_records:
        version = (selected.get(rid) or {}).get("version")
        existing = (packet.get("dispositions") or {}).get(rid)
        if _parked_already(existing):
            # Parked by an earlier attempt at this same case (the case was
            # re-driven for another of its lessons): keep the row, never
            # park or notify twice.
            assert isinstance(existing, dict)
            rows[rid] = existing
            continue
        row: dict = {"input_version": version, "case": case_id}
        own = refusals.get(rid) or []
        if case_best is not None:
            best = case_best
            if _KIND_ACTIONS[best.effective] == "close":
                # The case is one decision. A lesson of it that moved on
                # is closed; one that did not still needs a decision, so
                # it goes back rather than being called overtaken.
                mine = [refusal for refusal in own if refusal.effective == "overtaken"]
                best = mine[0] if mine else _Refusal("status", "bad-line")
        elif own:
            best = _deciding(own)
        else:
            rows[rid] = {"state": "applied", **row}
            continue
        action = _KIND_ACTIONS[best.effective]
        lines = _refusal_lines(items, rid) or case_lines
        reason = "; ".join(lines) or best.kind
        row.update(kind=best.kind, reason=reason)
        if action == "return" and (
            not isinstance(version, str)
            # A reconsider input (`observation:<id>`) is never selected
            # again under its observation, which this run consumed. It is
            # sent back only when the next run selects the LESSON again --
            # still pending, at a version no committed run has decided, it
            # comes back as an ordinary lesson input at its record's
            # version (:func:`_selected_again`). Otherwise, sent back, it
            # would be decided by no one, and it is parked now instead.
            # (2026-10-07, gate S1 D1.) Since S-81 a parked lesson is never
            # selected while its parked case is open, so parking here is
            # safe on any path; sending it back is kept because a fresh
            # steward decision is cheaper than the overseer's.
            or (version.startswith("observation:") and not _selected_again(home, rid))
            or _returned_before(home, rid, version, case_id)
        ):
            action = "park"
        if action == "park" and rid in held_now and any(
            row.get("case") != _successor_case_for(home, str(manifest.get("run_id")), rid)
            for row in held_now[rid]
        ):
            # S-81: another parked case holds it already (it was parked
            # after this run selected it). A second one would only ask the
            # same question again; it is sent back, and decided -- by the
            # overseer, or by a later run once the overseer lets it go. A
            # successor this run wrote for it is not another: a re-drive
            # reuses that one (`_close_out_record`).
            action = "return"
        if action == "close":
            rows[rid] = {**row, "state": "overtaken", "reason": best.moved}
        elif action == "refused":
            rows[rid] = {**row, "state": "refused"}
        elif action == "return":
            rows[rid] = {**row, "state": "returned"}
        elif action == "park":
            rows[rid] = {**row, "state": "unfinished"}
            park_now[rid] = best.kind
        else:  # retry
            rows[rid] = {**row, "state": "unfinished"}
    return _CaseDispositions(rows, park_now, retry_outside)


def _held_refusals(preview: batch.DryRunResult, sheet: batch.Sheet) -> list[dict]:
    """The lines a held-back case's preview says the ledger would refuse,
    shaped like case-result items, with the same sequence rule as
    `_preview_is_clean_for_sequence` (a sanctioned `[reopen, verb]`
    pair's second line is not a refusal when the refusal is the `status`
    one the reopen removes, :func:`_excused_after_reopen`)."""
    reopened: set[str] = set()
    out: list[dict] = []
    for shown, item in zip(preview.items, sheet, strict=True):
        if item.verb == "reopen" and shown.state != "would-refuse":
            reopened.add(item.id)
            continue
        if shown.state == "would-refuse" and not _excused_after_reopen(shown, reopened):
            out.append({
                "n": shown.n, "id": shown.id, "verb": shown.verb, "rc": 1,
                "state": "refused", "detail": shown.detail,
                **({"kind": shown.kind} if shown.kind is not None else {}),
            })
    return out


def _park_now(
    home: Path,
    run_dir: Path,
    run_id: str,
    packet_index: int,
    pending: dict[str, str],
    *,
    recorded: bool = True,
) -> tuple[dict[str, dict], list[str]]:
    """S-71 §4.5: write each record's `ledger-refused` successor case now,
    through the cap close-out's own writer. Returns the `abandoned` rows
    that landed and one error line per record that did not; a record whose
    write failed keeps its `unfinished` row, so its case is re-driven.
    *recorded*: whether the case that decided them is in the ledger
    (:func:`_park_now_texts`)."""
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    packet = manifest["packets"][packet_index - 1]
    relative = f"cases/runs/{run_id}.json"
    committed = gitops._git(home, "show", f"HEAD:{relative}")  # noqa: SLF001
    first, last = _packet_line_span(committed.stdout, packet_index)
    reference = f"ledger@{gitops.head_sha(home)}:{relative}#L{first}-{last}"
    landed: dict[str, dict] = {}
    errors: list[str] = []
    for record_id, kind in pending.items():
        row = dict((packet.get("dispositions") or {}).get(record_id) or {})
        question, because = _park_now_texts(record_id, kind, recorded=recorded)
        try:
            successor = _close_out_record(
                home, run_dir, run_id, packet, packet_index, record_id,
                parked_reason="ledger-refused", question=question, because=because,
                detail=_failure_detail(row.get("reason")) or kind,
                reference=reference,
                observation=(
                    f"the ledger refused this case's line for {record_id} ({kind}); "
                    "parked for the overseer as {successor}"
                ),
            )
        except Exception as exc:  # noqa: BLE001 -- one record never blocks the rest
            errors.append(f"{record_id}: {_short_cause(exc)}")
            continue
        row.update(state="abandoned", successor_case=successor)
        landed[record_id] = row
    return landed, errors


def _notify_parked_now(home: Path, run_id: str, parked: list[tuple[str, str]]) -> None:
    """S-71 §4.5: ONE notification per run for the lessons it parked at
    once, through the shipped helper; a failure is journaled, never raised."""
    ids = list(dict.fromkeys(record_id for record_id, _kind in parked))
    kinds = sorted({kind for _record_id, kind in parked})
    summary = (
        f"self-learn steward: {len(ids)} lesson(s) parked for the overseer — "
        f"the ledger refused a line a person must fix ({', '.join(kinds)})"
    )
    try:
        overseer_notify.send(home, "routine", summary, ids)
    except Exception as exc:  # noqa: BLE001 -- a notification never fails a run
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
            "status": "notify-failed", "error": _short_cause(exc)})


def _commit_park_now(
    home: Path,
    run_dir: Path,
    run_id: str,
    packet_index: int,
    case_id: str,
    rows: dict[str, dict],
    pending: dict[str, str],
    *,
    retry_outside: bool,
    closed_phase: str,
    recorded: bool = True,
) -> tuple[list[tuple[str, str]], bool]:
    """S-71 §4.5 for one case whose disposition rows were just committed:
    park each record of *pending* NOW, not at the cap -- a retry cannot fix
    its refusal, and a fresh decision was already refused once or cannot be
    asked for. The record's committed row, with the ledger's words, is the
    successor's evidence. Then commit the `abandoned` rows that landed and
    the case's phase: *closed_phase* once none of its records is left
    open, else `unfinished` (the case is re-driven).

    Returns the `(record, kind)` pairs to tell the user about, and False
    when the run record could not be written (the caller stops the packet,
    as for any failed run-record write). *recorded*: whether the case is
    in the ledger (:func:`_park_now_texts`)."""
    landed, errors = _park_now(home, run_dir, run_id, packet_index, pending, recorded=recorded)
    if errors:
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
            "status": "park-now-failed", "case": case_id, "errors": errors})
    still_open = retry_outside or any(
        row["state"] == "unfinished" and rid not in landed
        for rid, row in rows.items()
    )
    final_phase = "unfinished" if still_open else closed_phase
    if not landed:
        return [], True
    try:
        _update_manifest(
            home, run_id,
            reason=f"case {case_id} parked {len(landed)} lesson(s) now",
            update=lambda current: (
                current["cases"][case_id].update(phase=final_phase),
                current["packets"][packet_index - 1]["dispositions"].update(landed),
            ),
        )
    except gitops.GitOpsError as exc:
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
            "status": "dirty-refused", "paths": _dirty_truth_paths(home),
            "error": str(exc)})
        return [], False
    # Told about once its row says so: a re-drive after a failed row write
    # reuses the successor, and is told then.
    return [(rid, pending[rid]) for rid in landed], True


def _refuse_unrecorded_case(
    home: Path,
    run_dir: Path,
    run_id: str,
    packet_index: int,
    manifest: dict,
    case_id: str,
    case_records: list[str],
    items: list[dict],
    error: str,
    *,
    journal: bool = True,
) -> tuple[list[tuple[str, str]], bool]:
    """A case refused BEFORE it reached the ledger: the case writer refused
    it (2026-10-07, gate S1 R1), a sheet line names a lesson the overseer
    holds (S-81), or its text matched the secret scan when it was prepared
    (gate S1b F6). Nothing of it is in the ledger or dispatched; *items*
    are the refused lines, each with its S-71 kind. Its lessons follow
    §4.2 as for a case the preview holds back -- every one takes the
    case's most severe action: sent back, parked now, or retried -- and no
    row names the case, since there is no case to receipt on or to add
    the park's later observation to. Its phase is `refused` once none of
    its lessons is left open. Returns what :func:`_commit_park_now` does.
    *journal*: whether to write the refusal's journal row (a refusal on
    record already has one)."""
    if journal:
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "refused",
            "stage_file": f"{case_id}.yaml", "error": error})
    settled = _case_dispositions(
        home, manifest, manifest["packets"][packet_index - 1], case_id, case_records,
        items, held=True,
    )
    rows = {
        rid: {key: value for key, value in row.items() if key != "case"}
        for rid, row in settled.rows.items()
    }
    phase = "unfinished" if settled.retry_outside or any(
        row["state"] == "unfinished" for row in rows.values()
    ) else "refused"
    try:
        _update_manifest(home, run_id, reason=f"case {case_id} refused", update=lambda current: (
            current["cases"][case_id].update(phase=phase, error=error, unrecorded_refusal={
                "records": list(case_records), "lines": list(items), "error": error,
            }),
            current["packets"][packet_index - 1]["dispositions"].update(rows),
        ))
    except gitops.GitOpsError as write_error:
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dirty-refused",
            "paths": _dirty_truth_paths(home), "error": str(write_error)})
        return [], False
    if not settled.park_now:
        return [], True
    return _commit_park_now(
        home, run_dir, run_id, packet_index, case_id, rows, settled.park_now,
        retry_outside=settled.retry_outside, closed_phase="refused", recorded=False,
    )


def _apply_packet(
    home: Path, run_id: str, packet_index: int
) -> tuple[list[str], int, int | None, list[tuple[str, str]]]:
    """Continue one prepared packet using its immutable committed recipes."""
    decided: list[str] = []
    refused = 0
    halt_code: int | None = None
    parked_now: list[tuple[str, str]] = []
    manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
    # 2026-09-27 (fail-state audit finding 8): the run record is the file
    # every step here commits; a stray path elsewhere is noted, not a halt.
    dirty = _dirty_among(home, [execution_evidence.manifest_path(home, run_id)])
    if dirty:
        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dirty-refused",
            "paths": dirty, "error": "unexplained ledger paths refuse continuation"})
        # A25: `gitops.EXIT_GIT_FAILED`, not 8. `8` is `EXIT_BATCH_PARTIAL`,
        # which means "the ledger DID change"; nothing was written here, and
        # `run`'s own early return tests for EXIT_GIT_FAILED — so the literal
        # 8 meant the "git failed" branch almost never fired.
        return [], 0, gitops.EXIT_GIT_FAILED, []
    run_dir = _project_manifest(home, manifest)
    packet = manifest["packets"][packet_index - 1]
    inputs = {row["record"]: row["version"] for row in packet["inputs"]}
    for case_id in packet.get("case_ids") or []:
        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
        recipe = manifest["cases"][case_id]
        if recipe.get("phase") in {"complete", "parked", "refused"}:
            continue
        stored = recipe.get("unrecorded_refusal")
        if isinstance(stored, dict):
            # A case already refused before it was recorded, re-driven to
            # park a lesson whose park did not land -- or a case whose
            # prepared text matched the secret scan, frozen as a stub
            # (`_prepared_recipe`, gate S1b F6). Its refusal is the one on
            # record: re-deciding it now could apply a case once refused.
            stored_records = [str(rid) for rid in stored.get("records") or []]
            refused += max(1, len(stored_records))
            told, written = _refuse_unrecorded_case(
                home, run_dir, run_id, packet_index, manifest, case_id, stored_records,
                [dict(line) for line in stored.get("lines") or [] if isinstance(line, dict)],
                str(stored.get("error") or ""), journal=False,
            )
            if not written:
                return list(dict.fromkeys(decided)), refused, gitops.EXIT_GIT_FAILED, parked_now
            parked_now.extend(told)
            continue
        case_path, sheet_path = _write_recipe_stage(run_dir, packet_index, case_id, recipe)
        case_data = _read_yaml(case_path)
        records_named = case_data.get("records") if isinstance(case_data, dict) else None
        named_records = (
            [str(rid) for rid in dict.fromkeys(records_named)]
            if isinstance(records_named, list) else []
        )
        # S-81 (2026-10-08): a line on a lesson the overseer holds is
        # refused by name before anything of the case applies -- the case
        # is not recorded, so no reconsider widens it and no line
        # dispatches -- unless the case is parked, whose sheet never
        # applies. Kind `bad-line`: the steward's own line is the mistake,
        # so its lessons are sent back to be decided again without it
        # (parked on a second refusal, as ever).
        refused_lines = (
            _held_lines(home, _sheet_items(sheet_path), _holds_for(home, case_id, named_records))
            if recipe.get("parking_reason") is None else []
        )
        error = "; ".join(dict.fromkeys(str(line["detail"]) for line in refused_lines))
        unrecorded = bool(refused_lines)
        if not unrecorded:
            try:
                cases.record(home, case_path, actor="steward", reserved_id=case_id)
            except cases.CaseError as exc:
                # 2026-10-07 (gate S1 R1): the case writer refused the case,
                # so it is not in the ledger. Its lessons were written a
                # bare `refused` row -- no kind, no case -- which no S-71
                # rule reads and which `_terminal_versions` counts as a
                # decision: a lesson input refused here was stranded for
                # good. The refusal now takes its S-71 kind from the
                # exception's type (`batch.refusal_kind`; the table names no
                # `cases.CaseError`, so it is `unclassified` unless a typed
                # cause lies under it): `unclassified` parks the lessons
                # now; a `git` cause is retried. The reason is a sent-back
                # row the next brief shows the model: a secret-scan span is
                # withheld (2026-09-26).
                unrecorded = True
                error = refusal_text(exc)
                kind = batch.refusal_kind(exc, rc=1, state="refused")
                refused_lines = [
                    {"id": rid, "verb": "case", "rc": 1, "state": "refused",
                     "detail": error, "kind": kind}
                    for rid in named_records
                ]
        if unrecorded:
            refused += max(1, len(named_records))
            told, written = _refuse_unrecorded_case(
                home, run_dir, run_id, packet_index, manifest, case_id, named_records,
                refused_lines, error,
            )
            if not written:
                return list(dict.fromkeys(decided)), refused, gitops.EXIT_GIT_FAILED, parked_now
            parked_now.extend(told)
            continue
        #: (kind, the ledger's words) when `verbs.reconsider` refused this case
        reconsider_refusal: tuple[str, str] | None = None
        if isinstance(case_data, dict) and case_data.get("kind") == "reconsider":
            try:
                for rid in case_data.get("records") or []:
                    verbs.reconsider(home, rid, case=case_id, by="steward", no_push=True)
            except (verbs.VerbError, ledger_ops.LedgerOpsError) as exc:
                # 2026-09-28 (fail-state audit finding 10): a reconsider
                # case whose outcome does not fit the record ("outcome
                # 'rehome' does not apply to a 'rejected' record") raised
                # out of the run after `cases.record` had committed the
                # case, so the rest of the packet and every later packet
                # stopped, run after run, until the cap. Its sheet is not
                # applied, and the run goes on.
                #
                # 2026-10-07 (run-9858d321b158): its lessons were written
                # a bare `refused` row -- no kind, no case -- which no S-71
                # rule reads. In that run they were reconsider inputs, so
                # the row decided only their observation, and both
                # lessons, still pending, came back the next night as
                # ordinary lesson inputs; a LESSON input refused this way
                # was stranded for good, since `_terminal_versions` counts
                # `refused` as a decision of the record's version. The
                # refusal now carries its kind, from the exception's type
                # as every refusal's is (`batch.refusal_kind`: the verb's
                # status check is `status`; a raise site no type names is
                # `unclassified`), and the case is handled below exactly
                # as one the preview holds back: its sheet receipted
                # refused, nothing of it dispatched, every lesson taking
                # the case's action (S-71 §4.2: sent back, parked now, or
                # retried). A pending lesson the steward's own `status`
                # line refused is sent back whatever its input kind
                # (`_case_dispositions`): the next run selects it again.
                error = refusal_text(exc)
                reconsider_refusal = (batch.refusal_kind(exc, rc=1, state="refused"), error)
                _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "refused",
                    "stage_file": case_path.name, "error": error})
        items = batch.load_sheet(sheet_path, home=home)
        held: list[dict] | None = None
        if reconsider_refusal is not None:
            reconsider_kind, error = reconsider_refusal
            case_records_now = case_data.get("records") if isinstance(case_data, dict) else None
            result = batch.BatchResult(
                items=[
                    batch.ItemResult(
                        n=item.n, id=item.id, verb=item.verb, rc=1,
                        state="refused", detail=error, kind=reconsider_kind,
                    )
                    for item in items
                ],
                process_code=1,
                case=case_id,
                sheet_sha=items.sheet_sha,
                actor="steward",
            )
            receipt = batch.write_receipt(
                home, result, str(recipe["sheet_name"]), no_push=True, prefix=True
            )
            # One refused `reconsider` line per lesson of the case, shaped
            # like `_held_refusals`' rows: the verb that refused is named in
            # each lesson's reason.
            held = [
                {"id": str(rid), "verb": "reconsider", "rc": 1, "state": "refused",
                 "detail": error, "kind": reconsider_kind}
                for rid in dict.fromkeys(case_records_now if isinstance(case_records_now, list) else [])
            ]
            receipt_ok = bool(receipt and receipt.get("state") == "ok")
            phase = "complete" if receipt_ok else "unfinished"
        elif recipe.get("parking_reason") is not None:
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
            preview = batch.dry_run(
                home, items, actor="steward",
                hook_activation=config.hook_activation_enabled(home),
            )
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
                            kind=item.kind,
                        )
                        for item in preview.items
                    ],
                    process_code=1,
                    case=case_id,
                    sheet_sha=items.sheet_sha,
                    actor="steward",
                )
                receipt = batch.write_receipt(
                    home, result, str(recipe["sheet_name"]), no_push=True, prefix=True
                )
                # The LEDGER refused here, before anything was dispatched:
                # the case is one decision and none of it ran. What happens
                # to its lessons is S-71 §4.2 on the refusal's kind, below
                # -- every lesson of the case takes the case's most severe
                # action. (Before S-71 every such case was re-driven until
                # the cap, whatever the ledger said.)
                held = _held_refusals(preview, items)
                receipt_ok = bool(receipt and receipt.get("state") == "ok")
                phase = "complete" if receipt_ok else "unfinished"
            else:
                # 2026-09-27 (fail-state audit finding 8): the files this
                # sheet's dispatch commits are its lessons' records; only an
                # unexplained change to one of those halts the dispatch.
                dirty = _dirty_among(home, _sheet_record_paths(home, items))
                if dirty:
                    _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                        "status": "dirty-refused", "paths": dirty,
                        "error": "unexplained ledger paths before batch dispatch"})
                    return list(dict.fromkeys(decided)), refused, gitops.EXIT_GIT_FAILED, parked_now
                continuation = batch.BatchContinuation(
                    run_id=run_id, case_id=case_id, sheet_digest=str(recipe["sheet_digest"]),
                    completed=_recovered_items(home, manifest, case_id, recipe, items),
                )
                checkpoint = lambda partial, name=str(recipe["sheet_name"]): batch.write_receipt(
                    home, partial, name, no_push=True, prefix=True
                )
                _note_move_origins(home, items)
                try:
                    result = batch.run(home, items, no_push=True, actor="steward",
                        continuation=continuation, checkpoint=checkpoint,
                        hook_activation=config.hook_activation_enabled(home))
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
                _note_host_results(result)
        failed = [item for item in result.items if item.state in _FAILED_ITEM_STATES]
        refused += len(failed)
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
        result_json = result.to_json()
        pending: dict[str, str] = {}
        retry_outside = False
        if parked:
            rows = {
                rid: {"state": "parked", "input_version": inputs[rid], "case": case_id}
                for rid in case_records
            }
        elif not receipt_ok:
            # The receipt did not land (or a bookkeeping halt stopped the
            # sheet): nothing about the lines is known to be final, so the
            # whole case is re-driven, exactly as before S-71 -- except a
            # lesson an earlier attempt already parked, which keeps its row.
            existing = manifest["packets"][packet_index - 1].get("dispositions") or {}
            rows = {
                rid: existing[rid] if _parked_already(existing.get(rid))
                else {"state": "unfinished", "input_version": inputs[rid], "case": case_id}
                for rid in case_records
            }
            phase = "unfinished"
        else:
            # S-71 §4.2-§4.4: each refused record follows its refusal's
            # kind -- retried (`unfinished`), sent back (`returned`), closed
            # (`overtaken`), refused, or parked now for the overseer. The
            # case is `complete` once none of its records is `unfinished`.
            # `refused` stays reserved for a secret-scan hit in the record
            # itself (S-68 forbids retrying or parking one); a ledger
            # refusal of any other kind never drops a pending lesson out of
            # every later run (lrn-351ba705, 2026-09-21).
            settled_rows = _case_dispositions(
                home, manifest, manifest["packets"][packet_index - 1], case_id,
                case_records, held if held is not None else result_json["items"],
                held=held is not None,
            )
            rows = settled_rows.rows
            pending = settled_rows.park_now
            retry_outside = settled_rows.retry_outside
            if retry_outside or any(row["state"] == "unfinished" for row in rows.values()):
                phase = "unfinished"
        summary_state = "parked" if parked else "applied" if all(
            row["state"] == "applied" for row in rows.values()
        ) and not failed else phase
        try:
            _update_manifest(home, run_id, reason=f"case {case_id} {summary_state}", update=lambda current: (
                current["cases"][case_id].update(phase=phase, result=result_json),
                current["packets"][packet_index - 1]["dispositions"].update(rows),
            ))
        except gitops.GitOpsError as exc:
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dirty-refused",
                "paths": _dirty_truth_paths(home), "error": str(exc)})
            return list(dict.fromkeys(decided)), refused, gitops.EXIT_GIT_FAILED, parked_now
        if pending:
            told, written = _commit_park_now(
                home, run_dir, run_id, packet_index, case_id, rows, pending,
                retry_outside=retry_outside, closed_phase="complete",
            )
            if not written:
                return list(dict.fromkeys(decided)), refused, gitops.EXIT_GIT_FAILED, parked_now
            parked_now.extend(told)
        # Only a ledger STOP (5/6/7, "nothing written, safe to retry") or a
        # bookkeeping halt stops the cases behind this one. Exit 8 means
        # "some items applied, some refused" -- a finished sheet with a
        # known result, not a half-state -- and the later cases are other
        # lessons entirely; stopping on it left five prepared cases
        # undecided in the first real run (2026-09-21).
        if result.process_code in {5, 6, 7} or result.stopped_at is not None or halt_code is not None:
            halt_code = result.process_code or halt_code or 8
            break
    return list(dict.fromkeys(decided)), refused, halt_code, parked_now


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
    """One steward run, then one push of what it committed (doc 13 §5,
    H-5). Every write inside the run is ``no_push=True``, so before this
    wrapper a run's decisions stayed local until some other producer
    happened to push (found 2026-09-24: 41 ledger commits waiting)."""
    home = Path(home)
    publish = not dry_run and not worker.no_push_requested()
    head_before = verbs.ledger_head(home) if publish else None
    result: RunResult | None = None
    global _DRY_RUN_JOURNAL, _HOST_RESULT_IDS, _MOVED_FROM
    marked_before = _DRY_RUN_JOURNAL
    host_before = _HOST_RESULT_IDS
    moved_before = _MOVED_FROM
    _DRY_RUN_JOURNAL = dry_run
    _HOST_RESULT_IDS = []
    _MOVED_FROM = []
    try:
        result = _run(home, dry_run=dry_run)
        if not dry_run and _HOST_RESULT_IDS:
            result.recompile_skipped = _post_run_recompile(
                home, result.run_id, _HOST_RESULT_IDS, _MOVED_FROM
            )
        return result
    finally:
        _DRY_RUN_JOURNAL = marked_before
        _HOST_RESULT_IDS = host_before
        _MOVED_FROM = moved_before
        if publish:
            _publish(home, head_before, result.run_id if result is not None else None)


def _post_run_recompile(
    home: Path, run_id: str | None, record_ids: list[str],
    moved_from: list[tuple[str, Path]] | None = None,
) -> list[str]:
    """2026-09-28: after a run that applied a route, rehome or rescope, one
    recompile of those records' own targets (:func:`verbs.post_run_recompile`)
    -- after `_run` has let go of every lock, before the run's push. It is
    journaled and never raises out of the run; a target it skips is
    returned for the run's result and journaled, not retried here (the
    next run that touches it, or a person's `self-learn recompile`, does)."""
    ident = {"run_id": run_id} if run_id else {}
    try:
        outcome = verbs.post_run_recompile(home, record_ids, moved_from or ())
    except Exception as exc:  # noqa: BLE001 -- never mask the run's own outcome
        _journal(home, {"ts": chrono.now_iso(), **ident, "status": "recompile-failed",
            "records": sorted(set(record_ids)), "error": _failure_detail(_short_cause(exc))})
        return []
    skipped = [str(line) for line in cast(list, outcome["skipped"])]
    _journal(home, {"ts": chrono.now_iso(), **ident, "status": "recompile", **outcome})
    _tell_host_refusals(home, run_id, skipped)
    return skipped


#: The journal status of a host refusal the user was told about.
HOST_REFUSED_TOLD = "host-refused-told"


def _tell_host_refusals(home: Path, run_id: str | None, skipped: list[str]) -> None:
    """2026-09-28 (follow-up 2): a host whose commit hook keeps refusing the
    post-run recompile's write tells the user -- once per distinct cause
    (:func:`verbs.host_refusal_causes`), like an environment hold. Each
    told cause is journaled; a cause already told is not told again."""
    told = model_failures.told_causes(journal_path(home), HOST_REFUSED_TOLD)
    ident = {"run_id": run_id} if run_id else {}
    for cause in verbs.host_refusal_causes(skipped):
        if cause in told:
            continue
        _journal(home, {"ts": chrono.now_iso(), **ident, "status": HOST_REFUSED_TOLD,
            "cause": cause})
        summary = (
            f"self-learn steward: a host refused self-learn's commit — {cause}. "
            "The lesson's line waits there; fix what refuses it, then run "
            "`self-learn recompile`."
        )
        try:
            overseer_notify.send(home, "routine", summary, [run_id] if run_id else [])
        except Exception as exc:  # noqa: BLE001 -- a notification never fails a run
            _journal(home, {"ts": chrono.now_iso(), **ident,
                "status": "notify-failed", "error": _short_cause(exc)})


def _publish(home: Path, head_before: str | None, run_id: str | None = None) -> None:
    # The run id rides the push rows too when the run got one (2026-09-26).
    ident = {"run_id": run_id} if run_id else {}
    try:
        push = verbs.publish_after_run(home, head_before)
    except Exception as exc:  # never mask the run's own outcome
        _journal(home, {"ts": chrono.now_iso(), **ident, "status": "push-error",
            "reason": str(exc)[:300]})
        return
    if push is not None:
        _journal(home, {"ts": chrono.now_iso(), **ident, "status": "push", "ok": push.ok,
            "code": push.exit_code})


def _run(home: Path, *, dry_run: bool) -> RunResult:
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
        # U3a (2026-09-27): every input is a row carrying its kind --
        # a reconsider input, a pending lesson (no analyst proposal
        # needed), a suspected rule violation about a routed lesson.
        eligible: list[dict] = [_reconsider_row(entry, card) for entry, card in reconsider]
        eligible += [
            row for entry, row in _eligible_lessons(home) if entry.record.id not in reconsider_ids
        ]
        eligible += _suspected_violation_inputs(
            home, exclude={row["record"] for row in eligible}
        )
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
        # The run id is known before the attempt is recorded (2026-09-26):
        # a pure read of the committed manifest, or a fresh id -- nothing
        # here can raise, so the attempt row still lands first.
        run_id = (
            str(unfinished_runs[0]["run_id"]) if unfinished_runs
            else "run-" + uuid.uuid4().hex[:12]
        )
        if not dry_run:
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "attempt-start"})

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
            run_dir = _project_manifest(home, manifest)
        else:
            run_dir = steward_dir(home) / "runs" / run_id
            run_dir.mkdir(parents=True)
            # U3a: batches are U2's groups -- at most 10, at most 5 of them
            # unrelated -- over an index brought up to date here, in the
            # cache. `steward.packet_size` can only lower the 10.
            index, index_info = steward_inputs.refresh_index(home)
            try:
                plans, grouping = steward_inputs.plan_packets(
                    [row["record"] for row in eligible], index, int(packet_size)
                )
            finally:
                if index is not None:
                    index.close()
            by_record = {row["record"]: row for row in eligible}
            packet_rows = []
            observations: list[str] = []
            for packet_index, plan in enumerate(plans, start=1):
                inputs = [by_record[rid] for rid in plan.members]
                predecessors: dict[str, str] = {}
                for row in inputs:
                    if row.get("predecessor"):
                        predecessors[row["record"]] = row["predecessor"]
                    if row.get("observation_id"):
                        observations.append(row["observation_id"])
                packet_rows.append({
                    "index": packet_index, "inputs": inputs, "records": [row["record"] for row in inputs],
                    "predecessors": predecessors, "phase": "pending", "attempts": [],
                    "repair_remaining": 1, "case_ids": [], "maintenance": [],
                    "dispositions": {}, "bound": None, "failure": None,
                    # 02-schema §3a, the attempt-counting fields.
                    "attempt_count": 0, "last_attempt_at": None,
                    "progress_at": None, "failure_detail": None,
                    # U3a data point: why these lessons share a packet.
                    "group": plan.to_json(),
                })
            manifest = {
                "version": 1, "actor": "steward", "run_id": run_id,
                "started_at": chrono.now_iso(), "last_attempt_at": None,
                "completed_at": None, "status": "running", "outcome": None,
                "start_head": gitops.head_sha(home), "cases": {}, "packets": packet_rows,
                "inputs": [row for packet in packet_rows for row in packet["inputs"]],
                "reconsider_observations": observations, "coverage": _coverage_empty(),
                "ledger_effects": [],
                # U3a data point: how the run's inputs were batched.
                "grouping": {**grouping, "index": index_info},
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
        #: S-71 §4.5: every lesson this invocation parked at once, with the
        #: kind that parked it, for the run's one notification.
        parked_now: list[tuple[str, str]] = []
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
            # 2026-09-27 (audit finding 3): a fresh attempt decides only the
            # lessons still open -- a packet re-attempted because some of its
            # lessons had no valid case keeps the ones already decided.
            open_inputs = _open_inputs(packet_record)
            open_records = {row["record"] for row in open_inputs}
            inputs = [_brief_input(row) for row in open_inputs]
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
                    # 2026-09-26: the steward's cut of the feed, its two
                    # per-lesson sections sliced to EVERY lesson of the run
                    # (not this packet's), so each packet reads the same block.
                    feed_items = conditions.steward_feed(
                        home,
                        [
                            (str(row.get("record")), {})
                            for packet in manifest["packets"]
                            for row in packet.get("inputs") or []
                        ],
                        cache_dir(home),
                    )
                # U3a: the per-lesson briefs -- the record, its evidence pack,
                # the closest existing lessons, the packet's links -- built
                # here, where the index and the packet's group are known.
                briefs = _packet_briefs(home, manifest, packet_record, inputs)
                brief_stats = steward_inputs.packet_stats(
                    briefs.values(), packet_record.get("group")
                )
                prompt = steward_prompt.assemble(
                    home, cache_dir(home), context, inputs, conditions_items=feed_items,
                    returned=_returned_for(home, open_inputs), briefs=briefs,
                )
                # 2026-09-26: two files. `brief-shared.md` is the part every
                # packet of the run shares, appended to the system prompt;
                # it is rewritten before each call from the same bytes, so a
                # session cannot leave the next one a changed copy.
                # `packet-NNNN.md` is this packet's part, the user message.
                shared_brief = run_dir / "brief-shared.md"
                fsops.atomic_write(shared_brief, prompt.shared, fsync=True)
                fsops.atomic_write(
                    run_dir / f"packet-{packet_index:04d}.md", prompt.per_packet, fsync=True
                )
                spec = _session_spec(
                    home, run_dir, prompt.per_packet,
                    label=f"steward-{run_id}-{packet_index}", lessons=len(inputs),
                    run_id=run_id, shared_brief=shared_brief,
                )
                started = time.monotonic()
                outcome = invocation.write_session(spec)
                result.calls += 1
                # 2026-09-27 (fail-state audit finding 4): a transient
                # failure (overloaded, 5xx, rate limit, network) is retried
                # once within this attempt, from an empty stage.
                transient_retry: dict | None = None
                if model_failures.should_retry(outcome):
                    result.failed_calls += 1
                    transient_retry = {"failure": outcome.failure,
                        "detail": _failure_detail(outcome.detail),
                        **model_failures.failure_fields(outcome),
                        **_attempt_transcript(outcome)}
                    _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                        "status": "transient-retry", "packet": packet_index,
                        "call": "decision", **transient_retry})
                    shutil.rmtree(stage, ignore_errors=True)
                    stage.mkdir(parents=True, exist_ok=True)
                    model_failures.backoff()
                    outcome = invocation.write_session(spec)
                    result.calls += 1
                duration = float(time.monotonic() - started)
                if not outcome.ok:
                    result.failed_calls += 1
                turns = getattr(outcome, "turns", None)
                attempt = {"kind": "decision", "turns": turns,
                    "failure": outcome.failure, "duration_secs": duration,
                    **model_failures.failure_fields(outcome),
                    **({"transient_retry": transient_retry} if transient_retry else {}),
                    **_attempt_usage(outcome),
                    **_attempt_transcript(outcome),
                    # U3a data points: what the brief carried, and how much
                    # the steward still read for itself.
                    "brief": brief_stats,
                    "reads": steward_inputs.tool_reads(outcome, home)}
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
                    classified = model_failures.failure_fields(outcome)
                    if classified.get("failure_class") == "environment":
                        # 2026-09-27 (fail-state audit finding 4): the model
                        # or the installed Claude Code cannot run the call at
                        # all (a version, auth or not-found failure). That
                        # is a HOLD, not an attempt: the count goes back to
                        # what it was, the lessons stay open, the user is
                        # told once per distinct cause, and no later packet
                        # of this run is tried -- each would fail the same.
                        cause = _failure_detail(model_failures.hold_cause(outcome)) or bound
                        previous_cause = model_failures.last_hold_cause(journal_path(home))
                        held_fields = {
                            "attempts": packet_record.get("attempts") or [],
                            "phase": "unfinished", "failure": bound, "detail": detail,
                            "duration": duration, "dispositions": {},
                        }
                        if dry_run:
                            _record_failure(manifest, packet_index, **held_fields)
                        else:
                            _update_manifest(
                                home, run_id, reason=f"packet {packet_index} held: environment",
                                update=lambda current: (
                                    _record_failure(current, packet_index, **held_fields),
                                    current["packets"][packet_index - 1].update(
                                        attempt_count=attempts_made, **classified,
                                    ),
                                ),
                            )
                        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                            "status": model_failures.HELD_ENVIRONMENT, "packet": packet_index,
                            "cause": cause, **classified})
                        result.held = cause
                        if not dry_run and cause != previous_cause:
                            _notify_environment_hold(home, run_id, cause)
                        break
                    bound_dispositions = {
                        row["record"]: {
                            "state": "unfinished", "input_version": row["version"],
                            "reason": bound,
                        }
                        for row in open_inputs
                    }
                    failure_fields = {
                        "attempts": packet_record.get("attempts") or [],
                        "phase": "unfinished", "failure": bound, "detail": detail,
                        "duration": duration, "dispositions": bound_dispositions,
                        # 2026-09-27: what kind of failure, and the API's tag.
                        "classified": classified,
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
                # One repair turn per attempt (S-68 ruling 1), spent on
                # whichever comes first: a stage file that fails its format
                # check, or -- only when the format passed on the first try
                # -- S-71 §5's lines the ledger would refuse as written that
                # are the model's to fix. Ledger refusals left after the
                # repair never fail the stage: they flow to apply time.
                second_error: ValueError | None = None
                repair_message: str | None = None
                #: 2026-09-27 (audit finding 2): the first pass, kept when it
                #: validated, so a failed or worse repair turn can never
                #: throw away a packet whose first output was usable.
                first_pass = _first_pass_path(home, run_id, packet_index)
                shutil.rmtree(first_pass, ignore_errors=True)
                first_flags: list[str] = []
                selected_status: dict[str, object] = {
                    str(row["record"]): row.get("record_status")
                    for row in open_inputs
                }
                # 2026-09-27 (audit finding 3): judged pair by pair. An
                # undeclared file is moved to this quarantine directory, a
                # pair that fails is left out on its own, and only what is
                # not a pair (or no valid pair at all) fails the stage.
                quarantine = _quarantine_dir(home, run_id, packet_index, attempt_no)
                check: _StageCheck | None = None
                #: every file any of this attempt's checks quarantined -- the
                #: first pass's too, when a repair turn followed it.
                quarantined_all: list[str] = []
                try:
                    check = _check_stage(stage, open_records, quarantine, home)
                    quarantined_all.extend(check.quarantined)
                except ValueError as first_error:
                    if packet_record.get("repair_remaining", 0) <= 0:
                        second_error = first_error
                    else:
                        # The case writer's own rules ride along
                        # (2026-09-26), so one turn can fix both.
                        repair_message = "\n\n".join(filter(None, [
                            str(first_error), _case_rule_message(stage),
                        ]))
                else:
                    if packet_record.get("repair_remaining", 0) > 0:
                        repair_message = _stage_repair_message(
                            home, stage, check, selected_status,
                        )
                        if repair_message is not None:
                            first_flags = _flag_lines(repair_message)
                            shutil.copytree(stage, first_pass)
                if repair_message is not None:
                    packet_record["repair_remaining"] = 0
                    if not dry_run:
                        _update_manifest(home, run_id, reason=f"packet {packet_index} repair allowance", update=lambda current: current["packets"][packet_index - 1].update(repair_remaining=0))
                    repair_started = time.monotonic()
                    fsops.atomic_write(shared_brief, prompt.shared, fsync=True)
                    repair = invocation.write_session(_repair_spec(spec, repair_message))
                    result.calls += 1
                    # 2026-09-27 (fail-state audit finding 4): one retry of
                    # a transient failure here too; the repair works on the
                    # files in place, so the stage is left as it is.
                    repair_retry: dict | None = None
                    if model_failures.should_retry(repair):
                        result.failed_calls += 1
                        repair_retry = {"failure": repair.failure,
                            "detail": _failure_detail(repair.detail),
                            **model_failures.failure_fields(repair),
                            **_attempt_transcript(repair)}
                        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                            "status": "transient-retry", "packet": packet_index,
                            "call": "repair", **repair_retry})
                        model_failures.backoff()
                        repair = invocation.write_session(_repair_spec(spec, repair_message))
                        result.calls += 1
                    if not repair.ok:
                        result.failed_calls += 1
                    packet_record["attempts"].append({"kind": "repair", "failure": repair.failure,
                        "duration_secs": float(time.monotonic() - repair_started),
                        **model_failures.failure_fields(repair),
                        **({"transient_retry": repair_retry} if repair_retry else {}),
                        **_attempt_usage(repair),
                        **_attempt_transcript(repair),
                        "reads": steward_inputs.tool_reads(repair, home)})
                    try:
                        if not repair.ok:
                            raise ValueError(repair.detail or repair.failure or "repair invocation failed")
                        check = _check_stage(stage, open_records, quarantine, home)
                        quarantined_all.extend(check.quarantined)
                    except ValueError as exc:
                        second_error = exc
                    if first_pass.is_dir():
                        # 2026-09-27 (audit finding 2): the first pass
                        # validated. A repair call that failed, a stage it
                        # left invalid, or one it left flagging more (or a
                        # file the first pass had clean) is undone: the
                        # first pass is put back and goes ahead, and only
                        # what it still flags is refused, case by case, at
                        # apply time -- the lessons it decided validly are
                        # not held back to another attempt.
                        worse = second_error is not None
                        why = str(second_error) if second_error is not None else None
                        if not worse:
                            assert check is not None
                            after = _flag_lines(_stage_repair_message(
                                home, stage, check, selected_status,
                            ))
                            worse = _repair_made_worse(first_flags, after)
                            if worse:
                                why = (
                                    "the repair turn left more flagged than the first pass: "
                                    + ", ".join(sorted(
                                        {_flag_key(line) for line in after}
                                        - {_flag_key(line) for line in first_flags}
                                    ) or ["more lines"])
                                )
                        if worse:
                            shutil.rmtree(stage, ignore_errors=True)
                            shutil.copytree(first_pass, stage)
                            second_error = None
                            try:
                                check = _check_stage(stage, open_records, quarantine, home)
                                quarantined_all.extend(check.quarantined)
                            except ValueError as exc:  # it passed before; never expected
                                second_error = exc
                            packet_record["attempts"][-1]["restored_first_pass"] = True
                            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                                "status": "repair-undone", "packet": packet_index,
                                "reason": _failure_detail(why)})
                        shutil.rmtree(first_pass, ignore_errors=True)
                if second_error is not None:
                    if quarantined_all:
                        _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                            "status": "stage-quarantined", "packet": packet_index,
                            "undeclared": list(dict.fromkeys(quarantined_all)),
                            "dir": str(quarantine)})
                    schema_dispositions = {
                        row["record"]: {
                            "state": "unfinished", "input_version": row["version"],
                            "reason": "schema-repair",
                        }
                        for row in open_inputs
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
                assert check is not None
                # 2026-09-27 (audit finding 3): a pair that still fails is
                # moved out of the stage, so only the pairs that passed are
                # prepared; the lessons no passing pair covers stay open.
                set_aside = _set_aside_pairs(stage, check, quarantine)
                if quarantined_all or set_aside:
                    _journal(home, {"ts": chrono.now_iso(), "run_id": run_id,
                        "status": "stage-quarantined", "packet": packet_index,
                        "undeclared": list(dict.fromkeys(quarantined_all)), "pairs": set_aside,
                        "problems": {stem: _failure_detail(problem)
                                     for stem, problem in sorted(check.problems.items())},
                        "uncovered": check.uncovered, "dir": str(quarantine)})
                uncovered_rows = {
                    row["record"]: {
                        "state": "unfinished", "input_version": row["version"],
                        "reason": _NOT_COVERED,
                    }
                    for row in open_inputs if row["record"] in check.uncovered
                }
                if dry_run:
                    packet_record.setdefault("dispositions", {}).update(uncovered_rows)
                    packet_record["phase"] = "complete"
                    continue
                manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
                manifest_packet = manifest["packets"][packet_index - 1]
                manifest_packet.update(
                    attempts=list(packet_record.get("attempts") or []),
                    repair_remaining=packet_record.get("repair_remaining", 1),
                    duration_secs=packet_record.get("duration_secs"),
                )
                manifest_packet.setdefault("dispositions", {}).update(uncovered_rows)
                # A secret-scan hit refuses only the case or operation it is
                # in (`_prepared_recipe`); the rest of the packet proceeds.
                _prepared_recipe(home, stage, manifest, manifest_packet)
                _publish_manifest(home, manifest, reason=f"packet {packet_index} prepared recipe")
            if dry_run:
                continue
            packet_decided, packet_refused, packet_halt, packet_parked = _apply_packet(
                home, run_id, packet_index
            )
            result.decided.extend(packet_decided)
            result.refused += packet_refused
            parked_now.extend(packet_parked)
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

        if parked_now and not dry_run:
            # Once per run, never once per record, and before anything
            # below can return early: the parked cases already exist.
            _notify_parked_now(home, run_id, parked_now)

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
            # 2026-09-26: a rehearsal leaves a journal row too, marked so no
            # reader takes it for a real run. `dry-run` is a hold status, so
            # serve's cooldown never reads it as an attempt.
            _journal(home, {"ts": chrono.now_iso(), "run_id": run_id, "status": "dry-run",
                "dry_run": True, "calls": result.calls, "failed_calls": result.failed_calls,
                "abandoned": result.abandoned})
            return result

        manifest = execution_evidence.read_manifest(home, run_id, at="HEAD")
        # 2026-09-27 (fail-state audit finding 8): the finalization commits
        # the run record only; a stray path elsewhere was noted, not a halt.
        dirty = _dirty_among(home, [execution_evidence.manifest_path(home, run_id)])
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
        # A lesson sent back (S-71 `returned`) is a line the ledger refused:
        # counted here, so a run that decided nothing and sent a lesson back
        # never reports "applied, 0 refused" and exits 0 (FW-85).
        result.refused = sum(
            1 for value in dispositions if value.get("state") in {"refused", "returned"}
        ) + maintenance_refused_total
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
                "failed_calls": result.failed_calls,
                "decided": len(result.decided),
                "refused": result.refused,
                "unfinished": result.unfinished,
                "abandoned": result.abandoned,
                "abandoned_units": result.abandoned_units,
                "close_out_error": result.close_out_error,
                "coverage": result.coverage,
                **({"held": result.held} if result.held else {}),
            },
        )
        # Ruling 2's notification, ONCE per closed-out run and never once
        # per record: a run transitions to `complete` exactly once and is
        # never re-driven afterwards, so this is that one moment. A close-out
        # that abandoned only NON-record units is told too — it is still work
        # the runner gave up on, and it was previously silent.
        # A lesson parked at once (S-71) was told about when it was parked,
        # with its own sentence; this one is the attempt cap's.
        capped = [
            rid for rid in result.abandoned
            if not any(
                _is_park_now_row((packet.get("dispositions") or {}).get(rid))
                for packet in manifest["packets"]
            )
        ]
        if complete and (capped or result.abandoned_units):
            _notify_abandoned(
                home, run_id, manifest, capped, result.abandoned_units
            )
        return result
