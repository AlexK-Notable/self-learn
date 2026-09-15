"""M-W (Sprint 2 lane L7, D7): crash-safe multi-file ledger transactions.

Collapse (`_execute_route`, `collapse` set) and `hosts.host_rebind` each
mutate several files under one lock before their one commit — a
``SIGKILL`` between any two of those mutations used to leave a staged
rename `reconcile._BLOCKING_CODES` refuses to touch forever, or (rebind)
a modified-uncommitted ``hosts.yaml`` reconcile could not even SEE
(``reconcile._RECONCILABLE_HOME`` had no entry for it at all). This file
proves :mod:`self_learn.intents` closes both gaps.

**No mocks of git** (project discipline): every crash-window test spawns
a REAL child process that runs the REAL verb against a REAL git sandbox,
monkeypatches (in the CHILD only — a fresh interpreter, so this never
touches pytest's own process) one real mutation to write a barrier file
recording which step landed and then ``os.kill(getpid(), SIGKILL)`` —
deterministic, and the barrier file is the positive control that the
kill landed where intended, not earlier or later. :func:`TestCoreMechanics`
exercises the same recovery logic against a plain scratch repo, without a
child process, for the shapes a full verb scenario cannot cheaply isolate
(the "commit already landed, only `finish` never ran" idempotent case;
the "neither old nor new state is resolvable" stop case).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from self_learn import (
    batch,
    cases,
    execution_evidence,
    gitops,
    intents,
    reconcile as reconcile_mod,
    verbs,
    worker,
)
from self_learn.hosts import host_add, host_rebind, load_hosts, slug_for
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from self_learn.primitives import procs
from support import (
    commit_all,
    git,
    init_repo,
    make_behavior,
    make_env,
    make_home,
    merge_proposal_text,
)


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def subjects(repo: Path) -> list[str]:
    return git(repo, "log", "--format=%s").stdout.strip().splitlines()


def porcelain(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "-uall").stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return e


def seed_pending(home, rid, *, supersedes=None, **kwargs):
    record = make_behavior(record_id=rid, **kwargs)
    if supersedes is not None:
        record.set_supersedes(supersedes)
    create_record(home, record)
    commit_all(home, "seed record")
    return record


# ============================================================ child runner


#: The collapse child: installs one hook per real mutation `_execute_route`
#: makes when `collapse` is set, each calling through to the ORIGINAL
#: implementation first (so the kill always lands AFTER the real effect),
#: then — only for the step named by `$KILL_AFTER` — writing the barrier
#: and self-SIGKILLing. Every OTHER step is a plain pass-through, so one
#: script serves every kill point without six near-duplicate files.
_COLLAPSE_CHILD = r"""
import os, signal
from self_learn import execution_evidence, intents, ledger_ops, records, verbs

KILL_AFTER = os.environ["KILL_AFTER"]
BARRIER = os.environ["BARRIER"]

def _die(step):
    with open(BARRIER, "w", encoding="utf-8") as fh:
        fh.write(step)
    os.kill(os.getpid(), signal.SIGKILL)

_orig_write = records.Record.write
def _write(self, path):
    _orig_write(self, path)
    if KILL_AFTER == "write":
        _die("write")
records.Record.write = _write

_orig_resolve = verbs.resolve_record
def _resolve(*a, **k):
    r = _orig_resolve(*a, **k)
    if KILL_AFTER == "resolve":
        _die("resolve")
    return r
verbs.resolve_record = _resolve

_orig_supersede = verbs.supersede_record
def _supersede(*a, **k):
    r = _orig_supersede(*a, **k)
    if KILL_AFTER == "supersede":
        _die("supersede")
    return r
verbs.supersede_record = _supersede

_orig_remove = ledger_ops._remove_file
def _remove(*a, **k):
    r = _orig_remove(*a, **k)
    if KILL_AFTER == "remove_merge":
        _die("remove_merge")
    return r
ledger_ops._remove_file = _remove

# Gate r1 MAJOR-1: the three compile-record mutations between
# `remove_merge` and `complete` -- `_write_compile_record_entry`
# (the survivor's own compile record), `_complete_old_retirement`
# (a no-op unless `old_id` names an ALREADY-ROUTED record -- gate r2
# minor-2's `TestCollapseWithOldIdCrashWindow` tests below are where
# it does real work) and `_resync_three_regions` (a no-op for a plain
# `dest="skill-md"` collapse, real only for `reference`/`hook` -- same
# gate r2 minor-2 tests use `DEST=reference` to reach it), all real
# call boundaries the fix must survive across, per the gate's own
# `probe_collapse.py`.
_orig_cre = verbs._write_compile_record_entry
def _cre(*a, **k):
    r = _orig_cre(*a, **k)
    if KILL_AFTER == "compile_record":
        _die("compile_record")
    return r
verbs._write_compile_record_entry = _cre

_orig_cor = verbs._complete_old_retirement
def _cor(*a, **k):
    r = _orig_cor(*a, **k)
    if KILL_AFTER == "old_retirement":
        _die("old_retirement")
    return r
verbs._complete_old_retirement = _cor

_orig_resync = verbs._resync_three_regions
def _resync(*a, **k):
    r = _orig_resync(*a, **k)
    if KILL_AFTER == "resync":
        _die("resync")
    return r
verbs._resync_three_regions = _resync

_orig_complete = intents.complete
def _complete(intent):
    _orig_complete(intent)
    if KILL_AFTER == "complete":
        _die("complete")
verbs.intents.complete = _complete

_orig_proof = execution_evidence.write_compound_proof
def _proof(*a, **k):
    r = _orig_proof(*a, **k)
    if KILL_AFTER == "proof":
        _die("proof")
    return r
execution_evidence.write_compound_proof = _proof

_orig_commit = verbs._commit_ledger
def _commit(*a, **k):
    r = _orig_commit(*a, **k)
    if KILL_AFTER == "commit":
        _die("commit")
    return r
verbs._commit_ledger = _commit

execution = None
if os.environ.get("RUN_ID"):
    execution = execution_evidence.ExecutionRef(
        run_id=os.environ["RUN_ID"],
        case_id=os.environ["CASE_ID"],
        sheet_sha=os.environ["SHEET_SHA"],
        sheet_digest=os.environ["SHEET_DIGEST"],
        item=1,
        record_id=os.environ["SURVIVOR_ID"],
        verb="route",
        actor="steward",
    )

verbs.route(
    os.environ["SELF_LEARN_HOME"],
    os.environ["SURVIVOR_ID"],
    dest=os.environ.get("DEST", "skill-md"),
    collapse=os.environ["MERGE_ID"],
    no_push=True,
    execution=execution,
)
"""

#: The rebind child: same shape, one hook per real mutation `host_rebind`
#: makes. The git-mv hook filters on the subcommand so it does not fire
#: on every OTHER `_git` call the same run makes (staging, committing).
_REBIND_CHILD = r"""
import os, signal
from self_learn import gitops, hosts, intents

KILL_AFTER = os.environ["KILL_AFTER"]
BARRIER = os.environ["BARRIER"]

def _die(step):
    with open(BARRIER, "w", encoding="utf-8") as fh:
        fh.write(step)
    os.kill(os.getpid(), signal.SIGKILL)

_orig_git = gitops._git
def _git(repo, *args, **kwargs):
    r = _orig_git(repo, *args, **kwargs)
    if KILL_AFTER == "mv" and args and args[0] == "mv":
        _die("mv")
    return r
gitops._git = _git

_orig_dump_meta = hosts._dump_meta
def _dump_meta(*a, **k):
    r = _orig_dump_meta(*a, **k)
    if KILL_AFTER == "dump_meta":
        _die("dump_meta")
    return r
hosts._dump_meta = _dump_meta

_orig_save_hosts = hosts.save_hosts
def _save_hosts(*a, **k):
    r = _orig_save_hosts(*a, **k)
    if KILL_AFTER == "save_hosts":
        _die("save_hosts")
    return r
hosts.save_hosts = _save_hosts

_orig_complete = intents.complete
def _complete(intent):
    _orig_complete(intent)
    if KILL_AFTER == "complete":
        _die("complete")
hosts.intents.complete = _complete

_orig_commit = hosts._commit_or_half_written
def _commit(*a, **k):
    r = _orig_commit(*a, **k)
    if KILL_AFTER == "commit":
        _die("commit")
    return r
hosts._commit_or_half_written = _commit

hosts.host_rebind(
    os.environ["SELF_LEARN_HOME"],
    os.environ["OLD_PATH"],
    os.environ["NEW_PATH"],
)
"""


_U14_BATCH_KILL_CHILD = r"""
import os, signal
from self_learn import batch, verbs

SCENARIO = os.environ["SCENARIO"]
KILL_AFTER = os.environ["KILL_AFTER"]
HOME = os.environ["SELF_LEARN_HOME"]
RID = "lrn-acde1234"

def die(point):
    with open(os.environ["BARRIER"], "w", encoding="utf-8") as fh:
        fh.write(point)
    os.kill(os.getpid(), signal.SIGKILL)

def sheet():
    if SCENARIO == "reopen-defer":
        rows = [
            batch.SheetItem(n=1, id=RID, verb="reopen", fields={}),
            batch.SheetItem(n=2, id=RID, verb="defer", fields={}),
        ]
    elif SCENARIO == "revise-route":
        rows = [
            batch.SheetItem(
                n=1,
                id=RID,
                verb="revise",
                fields={
                    "section": "Trigger",
                    "text": "Reworded before routing.",
                    "because": "tighten wording before route",
                },
            ),
            batch.SheetItem(
                n=2, id=RID, verb="route", fields={"dest": "skill-md"}
            ),
        ]
    elif SCENARIO == "noop-reject":
        rows = [
            batch.SheetItem(n=1, id=RID, verb="reopen", fields={}),
            batch.SheetItem(n=2, id=RID, verb="reject", fields={}),
        ]
    else:
        assert SCENARIO == "route-host"
        rows = [
            batch.SheetItem(
                n=1, id=RID, verb="route", fields={"dest": "skill-md"}
            )
        ]
    return batch.Sheet(
        rows,
        case="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
    )

if KILL_AFTER == "after-first-ledger":
    name = "reopen" if SCENARIO == "reopen-defer" else "revise"
    original = getattr(verbs, name)
    def first(*args, **kwargs):
        result = original(*args, **kwargs)
        die(KILL_AFTER)
        return result
    setattr(verbs, name, first)
elif KILL_AFTER == "after-noop":
    original_classify = batch.classify
    def classify(*args, **kwargs):
        result = original_classify(*args, **kwargs)
        if result:
            die(KILL_AFTER)
        return result
    batch.classify = classify
elif KILL_AFTER == "after-second-ledger":
    original_reject = verbs.reject
    def reject(*args, **kwargs):
        result = original_reject(*args, **kwargs)
        die(KILL_AFTER)
        return result
    verbs.reject = reject
elif KILL_AFTER == "before-host":
    def host_phase(*args, **kwargs):
        die(KILL_AFTER)
    verbs._host_phase = host_phase

def checkpoint(partial):
    result = batch.write_receipt(
        HOME,
        partial,
        f"u14-{SCENARIO}.yaml",
        no_push=True,
        prefix=True,
    )
    if KILL_AFTER == "after-first-receipt" and len(partial.items) == 1:
        die(KILL_AFTER)
    return result

batch.run(
    HOME,
    sheet(),
    no_push=True,
    actor="steward",
    continuation=batch.BatchContinuation(
        run_id="run-u14-fold",
        case_id="case-acde1234",
        sheet_digest="a" * 64,
        completed={},
    ),
    checkpoint=checkpoint,
)
"""


_U14_BATCH_RESUME_CHILD = r"""
import json, os
from self_learn import batch

SCENARIO = os.environ["SCENARIO"]
HOME = os.environ["SELF_LEARN_HOME"]
RID = "lrn-acde1234"

if SCENARIO == "reopen-defer":
    rows = [
        batch.SheetItem(n=1, id=RID, verb="reopen", fields={}),
        batch.SheetItem(n=2, id=RID, verb="defer", fields={}),
    ]
elif SCENARIO == "revise-route":
    rows = [
        batch.SheetItem(
            n=1,
            id=RID,
            verb="revise",
            fields={
                "section": "Trigger",
                "text": "Reworded before routing.",
                "because": "tighten wording before route",
            },
        ),
        batch.SheetItem(n=2, id=RID, verb="route", fields={"dest": "skill-md"}),
    ]
else:
    assert SCENARIO in {"noop-reject", "route-host"}
    rows = (
        [
            batch.SheetItem(n=1, id=RID, verb="reopen", fields={}),
            batch.SheetItem(n=2, id=RID, verb="reject", fields={}),
        ]
        if SCENARIO == "noop-reject"
        else [
            batch.SheetItem(n=1, id=RID, verb="route", fields={"dest": "skill-md"}),
            batch.SheetItem(
                n=2, id=RID, verb="note", fields={"append": "after repair"}
            ),
        ]
    )

completed = {
    int(key): batch.ItemResult(**value)
    for key, value in json.loads(os.environ["COMPLETED"]).items()
}
items = batch.Sheet(
    rows,
    case="case-acde1234",
    sheet_sha="12ab34cd",
    sheet_digest="a" * 64,
)
result = batch.run(
    HOME,
    items,
    no_push=True,
    actor="steward",
    continuation=batch.BatchContinuation(
        run_id="run-u14-fold",
        case_id="case-acde1234",
        sheet_digest="a" * 64,
        completed=completed,
    ),
    checkpoint=lambda partial: batch.write_receipt(
        HOME,
        partial,
        f"u14-{SCENARIO}.yaml",
        no_push=True,
        prefix=True,
    ),
)
receipt = batch.write_receipt(
    HOME,
    result,
    f"u14-{SCENARIO}.yaml",
    no_push=True,
    prefix=True,
)
assert receipt is not None and receipt["state"] == "ok"
print(json.dumps(result.to_json(), sort_keys=True))
"""


_U14_RECOMPILE_CHILD = r"""
import json, os, signal
from self_learn import verbs

result = verbs.recompile(os.environ["SELF_LEARN_HOME"], no_push=True)
if os.environ.get("KILL_AFTER") == "after-recompile":
    with open(os.environ["BARRIER"], "w", encoding="utf-8") as fh:
        fh.write("after-recompile")
    os.kill(os.getpid(), signal.SIGKILL)
print(json.dumps({"warnings": result.warnings}, sort_keys=True))
"""


_OVERSEER_CRASH_CHILD = r"""
import json, os, signal
from pathlib import Path
from self_learn import batch, cases, settings, verbs
from self_learn.overseer import run as overseer_run

HOME = Path(os.environ["SELF_LEARN_HOME"])
KILL_AFTER = os.environ.get("KILL_AFTER", "none")
RID1 = os.environ["RID1"]
RID2 = os.environ["RID2"]
PARKED1 = os.environ["PARKED1"]
PARKED2 = os.environ["PARKED2"]

def die(point):
    Path(os.environ["BARRIER"]).write_text(point, encoding="utf-8")
    os.kill(os.getpid(), signal.SIGKILL)

real_setting = settings.resolve_setting
def resolve(home, setting):
    if setting.name == "overseer.enabled":
        return True, "crash-test"
    return real_setting(home, setting)
settings.resolve_setting = resolve

calls = []
def invoke(spec):
    calls.append(spec.label)
    stage = spec.cwd
    if spec.label == "phase-a":
        (stage / "selection.yaml").write_text(
            f"cases:\n- id: {PARKED1}\nwhy_these: crash guard\nwhy_stopped: one selected\n",
            encoding="utf-8",
        )
        (stage / "initial-views.yaml").write_text(
            f"cases:\n- id: {PARKED1}\n  what_i_would_do: reject\n  why: evidence\n  what_evidence_decides_it: record\n  confidence: clear\n",
            encoding="utf-8",
        )
        return type("Outcome", (), {"ok": True, "failure": None, "turns": 1})()
    headings = [
        "Examined", "Decided in the user's stead", "Hooks", "User model",
        "Catalogue health", "Questions for you", "Refused / could not do",
    ]
    (stage / "report.md").write_text(
        "# crash report\n" + "\n".join(f"## {h}\n- none" for h in headings) + "\n",
        encoding="utf-8",
    )
    (stage / "findings.yaml").write_text(
        f"findings:\n- case: {PARKED1}\n  kind: examined\n  text: evidence held\n",
        encoding="utf-8",
    )
    (stage / "questions.yaml").write_text("questions: []\n", encoding="utf-8")
    (stage / "user-model-delta.yaml").write_text("updates: []\n", encoding="utf-8")
    rows = (("a", RID1, PARKED1),) if os.environ.get("COLLAPSE") else (
        ("a", RID1, PARKED1), ("b", RID2, PARKED2)
    )
    for suffix, rid, parked in rows:
        records = f"[{RID1}, {RID2}]" if os.environ.get("COLLAPSE") else f"[{rid}]"
        (stage / f"case-{suffix}.yaml").write_text(
            "kind: resolution\ntrigger: weekly\noutcome: reject\n"
            f"records: {records}\nscope: skill:s\nquestion: reject it?\n"
            f"supersedes: {parked}\nevidence:\n- ref: record:{rid}\n  quote: pending\n"
            "decision:\n  verb: reject\n  because: evidence is conclusive\n  confidence: settled\n",
            encoding="utf-8",
        )
    if os.environ.get("COLLAPSE"):
        (stage / "sheet-a.yaml").write_text(
            f"version: 1\nitems:\n- id: {RID1}\n  verb: route\n  dest: skill-md\n  collapse: merge-0000f001\n",
            encoding="utf-8",
        )
    else:
        (stage / "sheet-a.yaml").write_text(
            "version: 1\nitems:\n"
            f"- id: {RID1}\n  verb: revise\n  section: Trigger\n  text: Reworded after evidence.\n  because: make the trigger exact\n"
            f"- id: {RID1}\n  verb: reject\n",
            encoding="utf-8",
        )
        (stage / "sheet-b.yaml").write_text(
            f"version: 1\nitems:\n- id: {RID2}\n  verb: reject\n",
            encoding="utf-8",
        )
    return type("Outcome", (), {"ok": True, "failure": None, "turns": 1})()

if KILL_AFTER == "none":
    def invoke(spec):
        raise AssertionError("committed recovery invoked the model")
overseer_run.invocation.write_session = invoke

if KILL_AFTER == "after-successor":
    original = cases.record
    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("actor") == "overseer":
            die(KILL_AFTER)
        return result
    overseer_run.cases.record = record
elif KILL_AFTER == "raise-after-successor":
    original = cases.record
    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("actor") == "overseer":
            raise RuntimeError("successor publication returned late failure")
        return result
    overseer_run.cases.record = record
elif KILL_AFTER == "between-items":
    original = verbs.revise
    def revise(*args, **kwargs):
        result = original(*args, **kwargs)
        die(KILL_AFTER)
        return result
    verbs.revise = revise
elif KILL_AFTER == "after-ledger":
    original = verbs.reject
    def reject(*args, **kwargs):
        result = original(*args, **kwargs)
        die(KILL_AFTER)
        return result
    verbs.reject = reject
elif KILL_AFTER == "after-sheet-1":
    original = batch.run
    sheet_calls = []
    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        sheet_calls.append(getattr(args[1], "case", None))
        if len(sheet_calls) == 1:
            die(KILL_AFTER)
        return result
    overseer_run.batch.run = run
elif KILL_AFTER == "after-observation":
    original = cases.observe
    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        die(KILL_AFTER)
        return result
    overseer_run.cases.observe = observe
elif KILL_AFTER == "before-report":
    original = overseer_run._write_manifest_truth
    def truth(*args, **kwargs):
        die(KILL_AFTER)
    overseer_run._write_manifest_truth = truth
elif KILL_AFTER == "after-collapse-commit":
    original = verbs._commit_ledger
    def commit(*args, **kwargs):
        result = original(*args, **kwargs)
        die(KILL_AFTER)
        return result
    verbs._commit_ledger = commit
elif KILL_AFTER == "stop-first":
    sheet_calls = []
    def run(*args, **kwargs):
        sheet_calls.append(getattr(args[1], "case", None))
        assert len(sheet_calls) == 1, "a later sheet ran after whole-sheet STOP"
        return batch.BatchResult(
            items=[], process_code=6, case=getattr(args[1], "case", None),
            sheet_sha=getattr(args[1], "sheet_sha", None), actor="overseer",
            stop_message="intent STOP before item 1",
        )
    overseer_run.batch.run = run
elif KILL_AFTER == "partial-first":
    sheet_calls = []
    def run(*args, **kwargs):
        sheet_calls.append(getattr(args[1], "case", None))
        assert len(sheet_calls) == 1, "a later sheet ran after aggregate exit 8"
        return batch.BatchResult(
            items=[
                batch.ItemResult(n=1, id=RID1, verb="revise", rc=0, state="applied"),
                batch.ItemResult(n=2, id=RID1, verb="reject", rc=1, state="refused", detail="refused item"),
            ],
            process_code=8, case=getattr(args[1], "case", None),
            sheet_sha=getattr(args[1], "sheet_sha", None), actor="overseer",
        )
    overseer_run.batch.run = run
elif KILL_AFTER == "item-stop-first":
    sheet_calls = []
    def run(*args, **kwargs):
        sheet_calls.append(getattr(args[1], "case", None))
        assert len(sheet_calls) == 1, "a later sheet ran after item stop"
        return batch.BatchResult(
            items=[
                batch.ItemResult(n=1, id=RID1, verb="revise", rc=7, state="stopped", detail="item stopped"),
                batch.ItemResult(n=2, id=RID1, verb="reject", rc=-1, state="not-attempted"),
            ],
            stopped_at=1, process_code=7,
            case=getattr(args[1], "case", None),
            sheet_sha=getattr(args[1], "sheet_sha", None), actor="overseer",
        )
    overseer_run.batch.run = run

result = overseer_run.run(HOME, dry_run=False, no_push=True)
print(json.dumps(result.to_json(), sort_keys=True))
"""


def _run_child(script: str, env_overrides: dict, barrier: Path) -> subprocess.CompletedProcess:
    child_env = dict(os.environ)
    child_env.pop("SELF_LEARN_ANALYST_MODEL", None)
    child_env.pop("SELF_LEARN_ANALYST_TIMEOUT", None)
    child_env.update(env_overrides)
    child_env["BARRIER"] = str(barrier)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc


def _assert_killed(proc: subprocess.CompletedProcess, barrier: Path, expected_step: str) -> None:
    assert proc.returncode == -9, (proc.returncode, proc.stdout, proc.stderr)
    assert barrier.is_file(), "the child never reached the intended kill point"
    assert barrier.read_text(encoding="utf-8") == expected_step


def _seed_overseer_crash_run(home: Path, tmp_path: Path) -> tuple[str, str, str, str]:
    rid1 = "lrn-0a0b0c0d"
    rid2 = "lrn-0e0f0102"
    seed_pending(home, rid1)
    seed_pending(home, rid2)
    parked_ids = []
    for index, rid in enumerate((rid1, rid2), start=1):
        stage = tmp_path / f"overseer-parked-{index}.yaml"
        stage.write_text(
            "kind: parked\ntrigger: nightly\noutcome: parked\n"
            f"records: [{rid}]\nscope: skill:s\nquestion: decide this?\n"
            "parked_for: overseer\nparked_reason: authority-unclear\n"
            f"evidence:\n- ref: record:{rid}\n  quote: pending\n"
            "decision:\n  verb: parked\n  because: delegated authority\n  confidence: provisional\n",
            encoding="utf-8",
        )
        parked_ids.append(cases.record(home, stage, actor="steward"))
    return rid1, rid2, parked_ids[0], parked_ids[1]


@pytest.mark.parametrize(
    "kill_after",
    [
        "after-successor",
        "between-items",
        "after-ledger",
        "after-sheet-1",
        "after-observation",
        "before-report",
    ],
)
def test_overseer_real_kill_resumes_committed_recipe_without_replay(
    tmp_path, kill_after
):
    home = make_home(tmp_path)
    rid1, rid2, parked1, parked2 = _seed_overseer_crash_run(home, tmp_path)
    cache = tmp_path / "entire-overseer-cache"
    claude_dir = tmp_path / "isolated-claude"
    barrier = tmp_path / f"overseer-{kill_after}-barrier"
    child_env = {
        "SELF_LEARN_HOME": str(home),
        "XDG_CACHE_HOME": str(cache),
        "SELF_LEARN_CLAUDE_DIR": str(claude_dir),
        "RID1": rid1,
        "RID2": rid2,
        "PARKED1": parked1,
        "PARKED2": parked2,
        "KILL_AFTER": kill_after,
    }

    killed = _run_child(_OVERSEER_CRASH_CHILD, child_env, barrier)
    _assert_killed(killed, barrier, kill_after)
    manifests = git(
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs"
    ).stdout.splitlines()
    assert len(manifests) == 1
    prepared = json.loads(git(home, "show", f"HEAD:{manifests[0]}").stdout)
    assert prepared["status"] == "unfinished"
    reserved = list(prepared["case_order"])
    shutil.rmtree(cache, ignore_errors=True)

    resumed = _run_child(
        _OVERSEER_CRASH_CHILD,
        {**child_env, "KILL_AFTER": "none"},
        tmp_path / "unused-overseer-resume-barrier",
    )
    assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
    result = json.loads(resumed.stdout.splitlines()[-1])
    assert (result["run"], result["status"]) == (prepared["run_id"], "applied")
    finished = json.loads(git(home, "show", f"HEAD:{manifests[0]}").stdout)
    assert finished["status"] == "complete"
    assert finished["case_order"] == reserved
    assert subjects(home).count(f"self-learn: revise {rid1}") == 1
    assert subjects(home).count(f"self-learn: reject {rid1}") == 1
    assert subjects(home).count(f"self-learn: reject {rid2}") == 1
    assert len(list((home / "overseer").glob("????-??-??-report.md"))) == 1
    assert intents.recover(home).restored == []
    observations = cases.show(home, parked1, evidence_only=False).sections[
        "Later observations"
    ]
    assert observations.count("overseer examined: evidence held") == 1
    for case_id in reserved:
        application = cases.show(home, case_id, evidence_only=False).sections[
            "Application"
        ]
        assert application.count("item=1") == 1


def test_overseer_collapse_commit_kill_resumes_from_compound_proof(tmp_path):
    home = make_home(tmp_path)
    rid1, rid2, parked1, parked2 = _seed_overseer_crash_run(home, tmp_path)
    proposal_dir = home / "skills" / "s" / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    (proposal_dir / "merge-0000f001.yaml").write_text(
        merge_proposal_text("merge-0000f001", [rid1, rid2], rid1),
        encoding="utf-8",
    )
    commit_all(home, "seed overseer collapse")
    cache = tmp_path / "overseer-collapse-cache"
    child_env = {
        "SELF_LEARN_HOME": str(home),
        "XDG_CACHE_HOME": str(cache),
        "SELF_LEARN_CLAUDE_DIR": str(tmp_path / "isolated-claude"),
        "RID1": rid1,
        "RID2": rid2,
        "PARKED1": parked1,
        "PARKED2": parked2,
        "COLLAPSE": "1",
        "KILL_AFTER": "after-collapse-commit",
    }
    barrier = tmp_path / "overseer-collapse-barrier"

    killed = _run_child(_OVERSEER_CRASH_CHILD, child_env, barrier)
    _assert_killed(killed, barrier, "after-collapse-commit")
    shutil.rmtree(cache, ignore_errors=True)
    resumed = _run_child(
        _OVERSEER_CRASH_CHILD,
        {**child_env, "KILL_AFTER": "none"},
        tmp_path / "unused-collapse-resume-barrier",
    )

    assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
    result = json.loads(resumed.stdout.splitlines()[-1])
    assert result["status"] == "applied"
    assert sum(
        subject.startswith(
            f"self-learn: route {rid1} → skill-md (collapse merge-0000f001,"
        )
        for subject in subjects(home)
    ) == 1
    assert Record.from_path(find_record_path(home, rid1)).status == "routed"
    assert Record.from_path(find_record_path(home, rid2)).status == "superseded"
    manifest_rel = git(
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs"
    ).stdout.strip()
    case_id = json.loads(git(home, "show", f"HEAD:{manifest_rel}").stdout)[
        "case_order"
    ][0]
    assert "evidence: host result established by recompile" in cases.show(
        home, case_id, evidence_only=False
    ).sections["Application"]


def test_overseer_whole_sheet_stop_halts_later_sheets_and_finalization(tmp_path):
    home = make_home(tmp_path)
    rid1, rid2, parked1, parked2 = _seed_overseer_crash_run(home, tmp_path)
    child_env = {
        "SELF_LEARN_HOME": str(home),
        "XDG_CACHE_HOME": str(tmp_path / "overseer-stop-cache"),
        "SELF_LEARN_CLAUDE_DIR": str(tmp_path / "isolated-claude"),
        "RID1": rid1,
        "RID2": rid2,
        "PARKED1": parked1,
        "PARKED2": parked2,
        "KILL_AFTER": "stop-first",
    }
    proc = _run_child(
        _OVERSEER_CRASH_CHILD, child_env, tmp_path / "unused-stop-barrier"
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    result = json.loads(proc.stdout.splitlines()[-1])
    assert (result["status"], result["code"]) == ("partial", 8)
    manifest_rel = git(
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs"
    ).stdout.strip()
    manifest = json.loads(git(home, "show", f"HEAD:{manifest_rel}").stdout)
    assert manifest["status"] == "unfinished"
    assert manifest["remaining"] == manifest["case_order"]
    successor_rows = [
        row for row in cases.list_cases(home, only_ok=True)
        if row.get("actor") == "overseer"
    ]
    assert len(successor_rows) == 1
    assert "intent STOP before item 1" in (
        home / "overseer" / "latest-report.md"
    ).read_text(encoding="utf-8")
    assert not (home / "overseer" / "open-questions.yaml").exists()


def test_overseer_aggregate_exit_8_halts_later_sheets(tmp_path):
    home = make_home(tmp_path)
    rid1, rid2, parked1, parked2 = _seed_overseer_crash_run(home, tmp_path)
    proc = _run_child(
        _OVERSEER_CRASH_CHILD,
        {
            "SELF_LEARN_HOME": str(home),
            "XDG_CACHE_HOME": str(tmp_path / "overseer-partial-cache"),
            "SELF_LEARN_CLAUDE_DIR": str(tmp_path / "isolated-claude"),
            "RID1": rid1, "RID2": rid2,
            "PARKED1": parked1, "PARKED2": parked2,
            "KILL_AFTER": "partial-first",
        },
        tmp_path / "unused-partial-barrier",
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    result = json.loads(proc.stdout.splitlines()[-1])
    assert (result["status"], result["code"]) == ("partial", 8)
    assert len([
        row for row in cases.list_cases(home, only_ok=True)
        if row.get("actor") == "overseer"
    ]) == 1


@pytest.mark.parametrize("scenario", ["item-stop-first", "raise-after-successor"])
def test_overseer_item_stop_and_late_successor_failure_are_partial(
    tmp_path, scenario
):
    home = make_home(tmp_path)
    rid1, rid2, parked1, parked2 = _seed_overseer_crash_run(home, tmp_path)
    proc = _run_child(
        _OVERSEER_CRASH_CHILD,
        {
            "SELF_LEARN_HOME": str(home),
            "XDG_CACHE_HOME": str(tmp_path / f"overseer-{scenario}-cache"),
            "SELF_LEARN_CLAUDE_DIR": str(tmp_path / "isolated-claude"),
            "RID1": rid1, "RID2": rid2,
            "PARKED1": parked1, "PARKED2": parked2,
            "KILL_AFTER": scenario,
        },
        tmp_path / f"unused-{scenario}-barrier",
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    result = json.loads(proc.stdout.splitlines()[-1])
    assert (result["status"], result["code"]) == ("partial", 8)
    manifest_rel = git(
        home, "ls-tree", "-r", "--name-only", "HEAD", "--", "cases/runs"
    ).stdout.strip()
    assert json.loads(git(home, "show", f"HEAD:{manifest_rel}").stdout)[
        "status"
    ] == "unfinished"
    assert len([
        row for row in cases.list_cases(home, only_ok=True)
        if row.get("actor") == "overseer"
    ]) == 1


def _u14_child_env(home: Path, cache: Path, scenario: str) -> dict[str, str]:
    return {
        "SELF_LEARN_HOME": str(home),
        "XDG_CACHE_HOME": str(cache),
        "SELF_LEARN_CLAUDE_DIR": str(cache.parent / "claude"),
        "SCENARIO": scenario,
    }


def _u14_record_case(home: Path, tmp_path: Path) -> str:
    stage = tmp_path / "u14-case.yaml"
    stage.write_text(
        "kind: resolution\n"
        "trigger: nightly\n"
        "outcome: reject\n"
        "records: [lrn-acde1234]\n"
        "scope: skill:s\n"
        "question: What is the durable outcome?\n"
        "evidence:\n"
        "  - ref: transcript:u14-fold#L1\n"
        "    quote: committed evidence\n"
        "decision:\n"
        "  verb: reject\n"
        "  because: the evidence is conclusive\n"
        "  confidence: settled\n"
        "run_id: run-u14-fold\n",
        encoding="utf-8",
    )
    return cases.record(
        home, stage, actor="steward", reserved_id="case-acde1234"
    )


def _u14_ref(verb: str, *, item: int = 1) -> execution_evidence.ExecutionRef:
    return execution_evidence.ExecutionRef(
        run_id="run-u14-fold",
        case_id="case-acde1234",
        sheet_sha="12ab34cd",
        sheet_digest="a" * 64,
        item=item,
        record_id="lrn-acde1234",
        verb=verb,
        actor="steward",
    )


def _u14_resume(
    home: Path,
    tmp_path: Path,
    cache: Path,
    scenario: str,
    completed: dict[int, dict],
) -> dict:
    proc = _run_child(
        _U14_BATCH_RESUME_CHILD,
        {
            **_u14_child_env(home, cache, scenario),
            "COMPLETED": json.dumps(completed),
        },
        tmp_path / "unused-resume-barrier",
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return json.loads(proc.stdout.splitlines()[-1])


# =========================================== U14 delegated-run crash windows


@pytest.mark.parametrize(
    ("scenario", "first_verb", "final_status"),
    [
        ("reopen-defer", "reopen", "deferred"),
        ("revise-route", "revise", "routed"),
    ],
)
def test_u14_real_kill_after_first_ledger_commit_skips_the_proven_item(
    tmp_path, scenario, first_verb, final_status
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    seed_pending(home, rid)
    if scenario == "reopen-defer":
        verbs.reject(home, rid, no_push=True)
    _u14_record_case(home, tmp_path)
    prepared = head(home)
    cache = tmp_path / "entire-cache"
    barrier = tmp_path / "first-ledger-barrier"

    proc = _run_child(
        _U14_BATCH_KILL_CHILD,
        {
            **_u14_child_env(home, cache, scenario),
            "KILL_AFTER": "after-first-ledger",
        },
        barrier,
    )
    _assert_killed(proc, barrier, "after-first-ledger")
    shutil.rmtree(cache, ignore_errors=True)

    ref = _u14_ref(first_verb)
    first_sha = execution_evidence.find_mutation_commit(
        home, ref, after=prepared
    )
    assert first_sha is not None
    record = Record.from_path(find_record_path(home, rid))
    if first_verb == "reopen":
        assert record.status == "pending"
    else:
        assert "Reworded before routing." in record.body
    result = _u14_resume(
        home,
        tmp_path,
        cache,
        scenario,
        {
            1: {
                "n": 1,
                "id": rid,
                "verb": first_verb,
                "rc": 0,
                "sha": first_sha,
                "state": "applied",
                "evidence": "ledger mutation verified against original item",
            }
        },
    )

    assert [(row["n"], row["state"]) for row in result["items"]] == [
        (1, "applied"),
        (2, "applied"),
    ]
    assert Record.from_path(find_record_path(home, rid)).status == final_status
    assert subjects(home).count(f"self-learn: {first_verb} {rid}") == 1


@pytest.mark.parametrize(
    "kill_after", ["after-noop", "after-first-receipt", "after-second-ledger"]
)
def test_u14_noop_then_reject_real_kill_at_every_barrier_converges_once(
    tmp_path, kill_after
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    seed_pending(home, rid)
    verbs.reject(home, rid, note="first resolution", no_push=True)
    verbs.reopen(home, rid, note="correction", no_push=True)
    _u14_record_case(home, tmp_path)
    prepared = head(home)
    cache = tmp_path / "entire-cache"
    barrier = tmp_path / f"noop-{kill_after}-barrier"

    proc = _run_child(
        _U14_BATCH_KILL_CHILD,
        {
            **_u14_child_env(home, cache, "noop-reject"),
            "KILL_AFTER": kill_after,
        },
        barrier,
    )
    _assert_killed(proc, barrier, kill_after)
    shutil.rmtree(cache, ignore_errors=True)

    completed: dict[int, dict] = {}
    if kill_after in {"after-first-receipt", "after-second-ledger"}:
        completed[1] = {
            "n": 1,
            "id": rid,
            "verb": "reopen",
            "rc": 0,
            "state": "already-applied",
        }
    if kill_after == "after-second-ledger":
        reject_sha = execution_evidence.find_mutation_commit(
            home, _u14_ref("reject", item=2), after=prepared
        )
        assert reject_sha is not None
        completed[2] = {
            "n": 2,
            "id": rid,
            "verb": "reject",
            "rc": 0,
            "sha": reject_sha,
            "state": "applied",
            "evidence": "ledger mutation verified against original item",
        }
    result = _u14_resume(
        home, tmp_path, cache, "noop-reject", completed
    )

    assert [(row["n"], row["state"]) for row in result["items"]] == [
        (1, "already-applied"),
        (2, "applied"),
    ]
    assert Record.from_path(find_record_path(home, rid)).status == "rejected"
    assert subjects(home).count(f"self-learn: reopen {rid}") == 1
    application = cases.show(home, "case-acde1234", evidence_only=False).sections[
        "Application"
    ]
    assert application.count("item=1") == 1
    assert application.count("item=2") == 1


def test_u14_route_real_kill_before_host_restarts_with_recompile_not_replay(
    tmp_path,
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    seed_pending(home, rid)
    _u14_record_case(home, tmp_path)
    prepared = head(home)
    cache = tmp_path / "entire-cache"
    barrier = tmp_path / "before-host-barrier"

    proc = _run_child(
        _U14_BATCH_KILL_CHILD,
        {
            **_u14_child_env(home, cache, "route-host"),
            "KILL_AFTER": "before-host",
        },
        barrier,
    )
    _assert_killed(proc, barrier, "before-host")
    shutil.rmtree(cache, ignore_errors=True)
    route_sha = execution_evidence.find_mutation_commit(
        home, _u14_ref("route"), after=prepared
    )
    assert route_sha is not None
    host_file = tmp_path / "host-repo/plugins/s-plugin/skills/s/SKILL.md"
    assert rid not in host_file.read_text(encoding="utf-8")

    repaired = _run_child(
        _U14_RECOMPILE_CHILD,
        _u14_child_env(home, cache, "route-host"),
        tmp_path / "unused-recompile-barrier",
    )
    assert repaired.returncode == 0, (repaired.stdout, repaired.stderr)

    assert rid in host_file.read_text(encoding="utf-8")
    route_shas = git(
        home,
        "log",
        "--format=%H",
        "--grep",
        f"^self-learn: route {rid}",
    ).stdout.splitlines()
    assert route_shas == [route_sha]


def test_u14_recompile_then_real_kill_before_receipt_restarts_and_checkpoints(
    tmp_path,
):
    home = make_home(tmp_path)
    rid = "lrn-acde1234"
    seed_pending(home, rid)
    _u14_record_case(home, tmp_path)
    prepared = head(home)
    cache = tmp_path / "entire-cache"
    route_barrier = tmp_path / "before-host-barrier"
    proc = _run_child(
        _U14_BATCH_KILL_CHILD,
        {
            **_u14_child_env(home, cache, "route-host"),
            "KILL_AFTER": "before-host",
        },
        route_barrier,
    )
    _assert_killed(proc, route_barrier, "before-host")
    shutil.rmtree(cache, ignore_errors=True)
    route_sha = execution_evidence.find_mutation_commit(
        home, _u14_ref("route"), after=prepared
    )
    assert route_sha is not None

    recompile_barrier = tmp_path / "after-recompile-barrier"
    killed_recompile = _run_child(
        _U14_RECOMPILE_CHILD,
        {
            **_u14_child_env(home, cache, "route-host"),
            "KILL_AFTER": "after-recompile",
        },
        recompile_barrier,
    )
    _assert_killed(killed_recompile, recompile_barrier, "after-recompile")
    shutil.rmtree(cache, ignore_errors=True)
    repaired_again = _run_child(
        _U14_RECOMPILE_CHILD,
        _u14_child_env(home, cache, "route-host"),
        tmp_path / "unused-second-recompile-barrier",
    )
    assert repaired_again.returncode == 0, (
        repaired_again.stdout,
        repaired_again.stderr,
    )
    result = _u14_resume(
        home,
        tmp_path,
        cache,
        "route-host",
        {
            1: {
                "n": 1,
                "id": rid,
                "verb": "route",
                "rc": 0,
                "sha": route_sha,
                "state": "applied",
                "evidence": "host result established by recompile",
            }
        },
    )

    assert [(row["n"], row["state"]) for row in result["items"]] == [
        (1, "applied"),
        (2, "applied"),
    ]
    assert subjects(home).count(f"self-learn: route {rid} → skill-md") == 1
    application = cases.show(home, "case-acde1234", evidence_only=False).sections[
        "Application"
    ]
    assert "item=1" in application
    assert "evidence: host result established by recompile" in application
    assert "item=2" in application


# ================================================================ collapse


class TestCollapseCrashWindows:
    """One kill point per adjacent mutation pair `_execute_route` makes
    for a collapse (survivor + one loser, no old_id — the shortest
    sequence that still exercises write / resolve / supersede /
    remove_merge), plus the roll-forward and the idempotent-after-commit
    windows."""

    @pytest.fixture
    def cluster(self, env, tmp_path):
        survivor = seed_pending(env.ledger, "lrn-0000f001")
        loser = seed_pending(env.ledger, "lrn-0000f002")
        proposals_dir = env.ledger / "skills" / "s" / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        merge_path = proposals_dir / "merge-0000f001.yaml"
        merge_path.write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(env.ledger, "seed cluster")
        return env, survivor, loser, merge_path

    def _fire(self, cluster, tmp_path, kill_after: str):
        env, survivor, loser, merge_path = cluster
        sha_before_crash = head(env.ledger)
        barrier = tmp_path / "barrier"
        proc = _run_child(
            _COLLAPSE_CHILD,
            {
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "SURVIVOR_ID": survivor.id,
                "MERGE_ID": "merge-0000f001",
                "KILL_AFTER": kill_after,
            },
            barrier,
        )
        _assert_killed(proc, barrier, kill_after)
        return env, survivor, loser, merge_path, sha_before_crash

    def _assert_fully_restored(self, env, survivor, loser, merge_path) -> None:
        pending = env.ledger / "skills" / "s" / "pending" / f"{survivor.id}.md"
        resolved = env.ledger / "skills" / "s" / "resolved" / f"{survivor.id}.md"
        loser_pending = env.ledger / "skills" / "s" / "pending" / f"{loser.id}.md"
        assert pending.is_file()
        assert "merged_from" not in pending.read_text(encoding="utf-8")
        assert not resolved.exists()
        assert loser_pending.is_file()
        assert merge_path.is_file()
        assert porcelain(env.ledger) == ""
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []
        # Gate r1 MAJOR-1: the compile-record write (`compiled/<slug>
        # .yaml`) is now inside the intent's own protected span too --
        # this fixture's survivor never routed before, so that path's
        # `old_sha` is `null` (it did not exist pre-transaction), and a
        # full restore means it is GONE again, not merely unchanged.
        compiled_dir = env.ledger / "compiled"
        assert (not compiled_dir.is_dir()) or list(compiled_dir.glob("*.yaml")) == []

    def _assert_fully_rolled_forward(self, env, survivor, loser, sha_before_crash: str) -> None:
        pending = env.ledger / "skills" / "s" / "pending" / f"{survivor.id}.md"
        resolved = env.ledger / "skills" / "s" / "resolved" / f"{survivor.id}.md"
        loser_resolved = env.ledger / "skills" / "s" / "resolved" / f"{loser.id}.md"
        assert not pending.exists()
        assert resolved.is_file()
        assert loser_resolved.is_file()
        assert "superseded" in loser_resolved.read_text(encoding="utf-8")
        route_subject = (
            f"self-learn: route {survivor.id} → skill-md "
            f"(collapse merge-0000f001, supersedes {loser.id})"
        )
        assert route_subject in subjects(env.ledger)
        # Gate r1 MAJOR-1's expected consequence: the compile-record
        # writes are now inside the intent's own protected span, so
        # roll-forward's one commit covers them too -- the two-commit
        # split the ORIGINAL M-W design accepted (a SEPARATE
        # `reconcile()` orphan-scan commit for the leftover
        # `compiled/*.yaml` this intent used to leave uncovered) no
        # longer happens: exactly one new commit lands relative to
        # right before the crash, and it is this one.
        new_subjects = git(
            env.ledger, "log", "--format=%s", f"{sha_before_crash}..HEAD"
        ).stdout.strip().splitlines()
        assert new_subjects == [route_subject], new_subjects
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    @pytest.mark.parametrize(
        "kill_after",
        ["write", "resolve", "supersede", "remove_merge", "compile_record", "resync"],
    )
    def test_kill_before_complete_restores_pre_transaction_state(
        self, cluster, tmp_path, kill_after
    ):
        env, survivor, loser, merge_path, _sha_before_crash = self._fire(
            cluster, tmp_path, kill_after
        )
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped
        self._assert_fully_restored(env, survivor, loser, merge_path)

    def test_kill_after_complete_rolls_forward(self, cluster, tmp_path):
        env, survivor, loser, merge_path, sha_before_crash = self._fire(
            cluster, tmp_path, "complete"
        )
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert not result.restored and not result.stopped
        self._assert_fully_rolled_forward(env, survivor, loser, sha_before_crash)

    def test_kill_after_commit_is_idempotent(self, cluster, tmp_path):
        """Advisor's item E: the commit landed for real before the
        SIGKILL — only `intents.finish` never ran. Recovery must not
        raise `HalfWrittenError` on a batch with nothing left to stage,
        and must not create a second commit."""
        env, survivor, loser, merge_path, sha_before_crash = self._fire(
            cluster, tmp_path, "commit"
        )
        sha_before_reconcile = head(env.ledger)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert head(env.ledger) == sha_before_reconcile  # no duplicate commit
        self._assert_fully_rolled_forward(env, survivor, loser, sha_before_crash)

    @pytest.mark.parametrize("kill_after", ["proof", "complete", "commit"])
    def test_u14_compound_proof_recovers_in_the_same_mutation_commit(
        self, cluster, tmp_path, kill_after
    ):
        env, survivor, loser, _merge_path = cluster
        run_id = "run-u14-collapse"
        case_id = "case-acde1234"
        sheet_sha = "12ab34cd"
        sheet_digest = "a" * 64
        manifest_path = execution_evidence.manifest_path(env.ledger, run_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "run_id": run_id,
                    "cases": {
                        case_id: {
                            "sheet_sha": sheet_sha,
                            "sheet_digest": sheet_digest,
                            "items": [
                                {"n": 1, "id": survivor.id, "verb": "route"}
                            ],
                        }
                    },
                    "ledger_effects": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        commit_all(env.ledger, "prepared U14 run")
        prepared_sha = head(env.ledger)
        barrier = tmp_path / "barrier-u14-proof"
        cache = tmp_path / "u14-entire-cache"
        proc = _run_child(
            _COLLAPSE_CHILD,
            {
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": str(cache),
                "SURVIVOR_ID": survivor.id,
                "MERGE_ID": "merge-0000f001",
                "KILL_AFTER": kill_after,
                "RUN_ID": run_id,
                "CASE_ID": case_id,
                "SHEET_SHA": sheet_sha,
                "SHEET_DIGEST": sheet_digest,
            },
            barrier,
        )
        _assert_killed(proc, barrier, kill_after)
        shutil.rmtree(cache, ignore_errors=True)
        recovered = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert not recovered.stopped
        ref = execution_evidence.ExecutionRef(
            run_id=run_id,
            case_id=case_id,
            sheet_sha=sheet_sha,
            sheet_digest=sheet_digest,
            item=1,
            record_id=survivor.id,
            verb="route",
            actor="steward",
        )
        if kill_after == "proof":
            assert recovered.restored
            verbs.route(
                env.ledger,
                survivor.id,
                dest="skill-md",
                collapse="merge-0000f001",
                no_push=True,
                execution=ref,
            )
        else:
            assert recovered.rolled_forward

        route_commits = git(
            env.ledger,
            "log",
            "--format=%H",
            f"{prepared_sha}..HEAD",
            "--grep",
            f"^self-learn: route {survivor.id}",
        ).stdout.strip().splitlines()
        assert len(route_commits) == 1
        route_sha = route_commits[0]
        committed_manifest = json.loads(
            git(env.ledger, "show", f"{route_sha}:cases/runs/{run_id}.json").stdout
        )
        assert committed_manifest["ledger_effects"] == [ref.to_proof()]
        prior_manifest = json.loads(
            git(env.ledger, "show", f"{route_sha}^:cases/runs/{run_id}.json").stdout
        )
        assert prior_manifest["ledger_effects"] == []
        assert execution_evidence.find_compound_proof_commit(
            env.ledger, ref, after=prepared_sha
        ) == route_sha
        if kill_after == "complete":
            tagless_body = git(
                env.ledger, "show", "-s", "--format=%B", route_sha
            ).stdout
            assert execution_evidence.parse_trailers(tagless_body) is None


class TestCollapseWithOldIdCrashWindow:
    """`_execute_route`'s collapse intent-path construction has a
    dedicated `if old_id is not None:` arm (verbs.py, right after
    `intent_paths = [...]` is seeded) for `teach --supersedes` combined
    with `--collapse` in the SAME route call — the survivor itself
    supersedes a third record. `TestCollapseCrashWindows` above never
    sets `supersedes` on its survivor, so that arm ran on every green
    run without ever being exercised by a kill. This class closes that:
    the old record is pending (never routed), so its own retirement
    preflight is a no-op (`_retirement_preflight` returns immediately
    when `record.status != "routed"`) and the ONLY thing riding on the
    intent covering it is the plain pending→resolved supersede move —
    the simplest real instance of the branch, and sufficient to prove
    it is wired in at all."""

    @pytest.fixture
    def cluster_with_old_id(self, env, tmp_path):
        old = seed_pending(env.ledger, "lrn-0000f000")
        survivor = seed_pending(env.ledger, "lrn-0000f001", supersedes=old.id)
        loser = seed_pending(env.ledger, "lrn-0000f002")
        proposals_dir = env.ledger / "skills" / "s" / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        merge_path = proposals_dir / "merge-0000f001.yaml"
        merge_path.write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(env.ledger, "seed cluster")
        return env, survivor, loser, old, merge_path

    def test_kill_after_old_id_supersede_restores_everything(
        self, cluster_with_old_id, tmp_path
    ):
        env, survivor, loser, old, merge_path = cluster_with_old_id
        barrier = tmp_path / "barrier"
        # `_execute_route` calls `supersede_record` for `old_id` BEFORE
        # the losers loop, so `KILL_AFTER="supersede"` here fires right
        # after the OLD record's own pending→resolved move — a step the
        # `TestCollapseCrashWindows.cluster` fixture (no `old_id`) never
        # reaches on this same hook.
        proc = _run_child(
            _COLLAPSE_CHILD,
            {
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "SURVIVOR_ID": survivor.id,
                "MERGE_ID": "merge-0000f001",
                "KILL_AFTER": "supersede",
            },
            barrier,
        )
        _assert_killed(proc, barrier, "supersede")

        old_pending = env.ledger / "skills" / "s" / "pending" / f"{old.id}.md"
        old_resolved = env.ledger / "skills" / "s" / "resolved" / f"{old.id}.md"
        survivor_pending = env.ledger / "skills" / "s" / "pending" / f"{survivor.id}.md"
        survivor_resolved = env.ledger / "skills" / "s" / "resolved" / f"{survivor.id}.md"
        loser_pending = env.ledger / "skills" / "s" / "pending" / f"{loser.id}.md"

        # Positive control: the old record's real supersede-move landed
        # (the child's hook calls through to the original before dying),
        # so a passing restore below proves reversal, not mere absence.
        assert old_resolved.is_file()
        assert not old_pending.exists()

        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped

        assert old_pending.is_file()
        assert not old_resolved.exists()
        assert survivor_pending.is_file()
        assert "merged_from" not in survivor_pending.read_text(encoding="utf-8")
        assert not survivor_resolved.exists()
        assert loser_pending.is_file()
        assert merge_path.is_file()
        assert porcelain(env.ledger) == ""
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    # -------------------------------------------- gate r2 minor-2

    @pytest.fixture
    def cluster_with_a_routed_old_id(self, tmp_path, monkeypatch):
        """Gate r2 minor-2: `_complete_old_retirement`'s (verbs.py:4252)
        and `_resync_three_regions`'s (verbs.py:4261) own `intent=`
        threadings are unverified -- `cluster_with_old_id` above leaves
        `old` PENDING, so `_retirement_preflight` returns immediately
        and `_complete_old_retirement` never writes anything, and every
        `TestCollapseCrashWindows` fixture collapses to plain
        `dest="skill-md"`, which `_resync_three_regions` never resolves
        (real only for `reference`/`hook`, per its own docstring).

        This fixture ROUTES `old` to `skill-md` under the DEFAULT skill
        host BEFORE the collapse, then puts the survivor+loser under a
        SEPARATE, freshly `host_add`ed project host and collapses to
        `dest="reference"` there -- empirically confirmed (probe, not
        guessed) this makes BOTH functions do REAL work, each in its
        OWN compile-record FILE (`compiled_record_path` keys purely by
        HOST REPO PATH, one file per host -- a first probe using a
        SECOND SKILL under the SAME host repo put both writes in the
        SAME file, where retirement's own `add_step` call already
        covered the whole file and silently absorbed resync's write
        too, making the M-D3 mutation undetectable). Two hosts, two
        files, two independently restorable steps."""
        e = make_env(tmp_path, skills=("s",))
        monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))

        old = make_behavior(record_id="lrn-0000f000", scope="skill:s")
        create_record(e.ledger, old)
        commit_all(e.ledger, "seed old")
        verbs.route(e.ledger, old.id, dest="skill-md", no_push=True)
        compiled_dir = e.ledger / "compiled"
        [old_compiled] = list(compiled_dir.glob("*.yaml"))
        old_pre_bytes = old_compiled.read_bytes()

        project_repo = tmp_path / "proj-repo"
        init_repo(project_repo)
        (project_repo / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(project_repo, "proj seed")
        host_add(e.ledger, project_repo, "project")

        survivor = make_behavior(record_id="lrn-0000f001", scope="project")
        survivor.set_supersedes(old.id)
        create_record(e.ledger, survivor, project_path=project_repo)
        loser = make_behavior(record_id="lrn-0000f002", scope="project")
        create_record(e.ledger, loser, project_path=project_repo)
        proposals_dir = e.ledger / "projects" / slug_for(project_repo) / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        merge_path = proposals_dir / "merge-0000f001.yaml"
        merge_path.write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(e.ledger, "seed cluster")
        return e, survivor, old_compiled, old_pre_bytes

    def _fire_routed_old_id(
        self, cluster_with_a_routed_old_id, tmp_path, kill_after: str
    ):
        e, survivor, old_compiled, old_pre_bytes = cluster_with_a_routed_old_id
        barrier = tmp_path / "barrier"
        proc = _run_child(
            _COLLAPSE_CHILD,
            {
                "SELF_LEARN_HOME": str(e.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "SURVIVOR_ID": survivor.id,
                "MERGE_ID": "merge-0000f001",
                "KILL_AFTER": kill_after,
                "DEST": "reference",
            },
            barrier,
        )
        _assert_killed(proc, barrier, kill_after)
        compiled_dir = e.ledger / "compiled"
        proj_candidates = [p for p in compiled_dir.glob("*.yaml") if p != old_compiled]
        proj_compiled = proj_candidates[0] if proj_candidates else None
        return e, old_compiled, old_pre_bytes, proj_compiled

    def test_kill_after_old_retirement_restores_the_old_records_compile_record(
        self, cluster_with_a_routed_old_id, tmp_path
    ):
        """Mutation M-D2 (drop `intent=intent` from the
        `_complete_old_retirement` call in `_execute_route`): this
        kill lands right after `_complete_old_retirement`'s real
        rewrite of old's OWN compile-record entry and before
        `_resync_three_regions` even starts -- without the intent
        covering that write, restore leaves the retirement's rewrite
        in place instead of putting the entry back to its pre-collapse
        bytes."""
        e, old_compiled, old_pre_bytes, _proj_compiled = self._fire_routed_old_id(
            cluster_with_a_routed_old_id, tmp_path, "old_retirement"
        )
        # Positive control: the retirement's real write landed before
        # the kill (the child's hook calls through to the original
        # first, then dies) -- a passing restore below proves reversal.
        assert old_compiled.read_bytes() != old_pre_bytes

        result = reconcile_mod.reconcile(e.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped

        assert old_compiled.read_bytes() == old_pre_bytes
        assert porcelain(e.ledger) == ""
        assert list(intents.intents_dir(e.ledger).glob("*.json")) == []

    def test_kill_after_resync_restores_the_survivors_reference_region(
        self, cluster_with_a_routed_old_id, tmp_path
    ):
        """Mutation M-D3 (drop `intent=intent` from the
        `_resync_three_regions` call in `_execute_route`): this kill
        lands right after `_resync_three_regions` writes the survivor's
        OWN reference-region compile-record entry, in the project
        host's OWN compiled file -- a SEPARATE file from old's, so
        (unlike a same-host fixture) old's own `_complete_old_retirement`
        step can never absorb this write by accident. Without the
        intent covering it, restore leaves the project host's compiled
        file uncreated-but-uncleaned -- this fixture's `old_sha` for
        that step is `null` (the file did not exist before), so a
        correct restore DELETES it, not merely reverts its bytes.

        The PHYSICAL host-repo files (`references/LEARNINGS.md`) are a
        separate concern: `_host_phase` writes them AFTER the ledger
        commit + `intents.finish`, wholly outside this kill point (same
        as `_retirement_host_phase`'s script `git rm` above) -- a kill
        this early never reaches it in either branch, so it is not this
        test's job to assert on them."""
        e, _old_compiled, _old_pre_bytes, proj_compiled = self._fire_routed_old_id(
            cluster_with_a_routed_old_id, tmp_path, "resync"
        )
        # Positive control: the resync's real compile-record write
        # landed before the kill (a brand-new file -- `old_sha` is
        # `null`, this project host never had one before).
        assert proj_compiled is not None and proj_compiled.is_file()

        result = reconcile_mod.reconcile(e.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped

        assert not proj_compiled.exists(), "a null old_sha step restores by deleting the path"
        assert porcelain(e.ledger) == ""
        assert list(intents.intents_dir(e.ledger).glob("*.json")) == []


# ============================================================== rebind


class TestRebindCrashWindows:
    #: Gate r1 minor-1: the original fixture never committed the ledger
    #: bucket `create_record` writes, so it was UNTRACKED at rebind time
    #: — `git mv` on an untracked path stages nothing (`hosts.py`'s own
    #: `bucket.rename` fallback runs instead), so the `R`/`RM` staged-
    #: rename shape `_prune_empty_dirs`/the intent's `git reset -q --`
    #: exist to handle was never actually produced. Proof it mattered:
    #: mutation 3c (removing the index reset) reddened four COLLAPSE
    #: tests and ZERO rebind tests. Parametrized both ways: "tracked"
    #: covers the realistic case (a project bucket almost always has
    #: prior history by the time a rebind happens) and is what makes the
    #: staged-rename shape real; "untracked" keeps the ORIGINAL fixture's
    #: coverage of `hosts.py`'s plain-rename fallback path.
    @pytest.fixture(params=["tracked", "untracked"])
    def rebind_setup(self, env, tmp_path, request):
        project_repo = tmp_path / "proj-repo"
        init_repo(project_repo)
        (project_repo / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(project_repo, "proj seed")
        host_add(env.ledger, project_repo, "project")
        record = make_behavior(scope="project", record_id="lrn-0000e001")
        create_record(env.ledger, record, project_path=project_repo)
        if request.param == "tracked":
            commit_all(env.ledger, "commit the bucket")
        moved = tmp_path / "proj-moved"
        project_repo.rename(moved)
        return env, project_repo, moved

    def _fire(self, rebind_setup, tmp_path, kill_after: str):
        env, project_repo, moved = rebind_setup
        barrier = tmp_path / "barrier"
        proc = _run_child(
            _REBIND_CHILD,
            {
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "OLD_PATH": str(project_repo),
                "NEW_PATH": str(moved),
                "KILL_AFTER": kill_after,
            },
            barrier,
        )
        _assert_killed(proc, barrier, kill_after)
        return env, project_repo, moved

    def _assert_fully_restored(self, env, project_repo, moved) -> None:
        old_bucket = env.ledger / "projects" / slug_for(project_repo)
        new_bucket = env.ledger / "projects" / slug_for(moved)
        assert old_bucket.is_dir()
        assert not new_bucket.exists()
        assert (old_bucket / "pending" / "lrn-0000e001.md").is_file()
        assert project_repo.resolve() in [Path(p).resolve() for p in load_hosts(env.ledger).projects]
        assert moved.resolve() not in [Path(p).resolve() for p in load_hosts(env.ledger).projects]
        assert porcelain(env.ledger) == ""
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    def _assert_fully_rolled_forward(self, env, project_repo, moved) -> None:
        new_bucket = env.ledger / "projects" / slug_for(moved)
        old_bucket = env.ledger / "projects" / slug_for(project_repo)
        assert new_bucket.is_dir()
        assert not old_bucket.exists()
        assert (new_bucket / "pending" / "lrn-0000e001.md").is_file()
        assert moved.resolve() in [Path(p).resolve() for p in load_hosts(env.ledger).projects]
        assert subjects(env.ledger)[0] == (
            f"self-learn: host rebind {project_repo.resolve()} → {moved.resolve()}"
        )
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    @pytest.mark.parametrize("kill_after", ["mv", "dump_meta", "save_hosts"])
    def test_kill_before_complete_restores_pre_transaction_state(
        self, rebind_setup, tmp_path, kill_after
    ):
        env, project_repo, moved = self._fire(rebind_setup, tmp_path, kill_after)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped
        self._assert_fully_restored(env, project_repo, moved)

    def test_kill_after_complete_rolls_forward(self, rebind_setup, tmp_path):
        env, project_repo, moved = self._fire(rebind_setup, tmp_path, "complete")
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        self._assert_fully_rolled_forward(env, project_repo, moved)

    def test_kill_after_commit_is_idempotent(self, rebind_setup, tmp_path):
        env, project_repo, moved = self._fire(rebind_setup, tmp_path, "commit")
        sha_before = head(env.ledger)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert head(env.ledger) == sha_before
        self._assert_fully_rolled_forward(env, project_repo, moved)


# ========================================================= worker.run

class TestWorkerRunFindsAnIntent:
    def test_worker_run_recovers_an_interrupted_intent_at_start(self, env, tmp_path):
        """Positive control (coordinator pin): a leftover intent is found
        and resolved by `worker.run`'s START, not just by an explicit
        `reconcile()` call. This plants the intent directly (via the
        SAME `intents.begin`/crash shape the subprocess-kill tests above
        already prove end-to-end for a REAL SIGKILL against `reconcile()`)
        rather than re-driving a full collapse under a subprocess: this
        assertion is about `worker.run`'s WIRING, and re-deriving the SDK-
        fake harness (`backends.install_fake`, needed the instant `worker.
        run` finds eligible pending work) to reach the same wiring proof
        would cost real complexity for no additional coverage.
        `make_env` seeds no pending records, so `run` reaches `status ==
        "idle"` right after recovery without ever touching the SDK."""
        yaml_path = env.ledger / "hosts.yaml"
        old_bytes = yaml_path.read_bytes()
        intent = intents.begin(
            env.ledger, "host_add", [yaml_path], "self-learn: host add project /tmp/x"
        )
        yaml_path.write_bytes(old_bytes + b"  # crash before complete()\n")
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == [intent.file_path]

        result = worker.run(env.ledger, no_push=True)

        assert result.status == "idle"
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []
        assert yaml_path.read_bytes() == old_bytes
        assert porcelain(env.ledger) == ""
        log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
        assert "recovered intent" in log_text

    def test_worker_run_ends_at_start_on_a_live_stop(self, env, tmp_path):
        """§7.2a.5(4)/§7.2a.8: "a run that sees a `stopped` outcome ends
        there... before enumeration and before any model session is
        spent." Same unresolvable-anywhere plant as
        `TestCoreMechanics.test_stop_when_prior_content_is_unresolvable_
        anywhere`, against `worker.run`'s own start-of-run
        `intents.recover` call rather than a bare `intents.recover()`."""
        yaml_path = env.ledger / "hosts.yaml"
        old_bytes = yaml_path.read_bytes()
        intent = intents.begin(
            env.ledger, "host_add", [yaml_path], "self-learn: host add project /tmp/x"
        )
        yaml_path.write_bytes(old_bytes + b"  # mutated once\n")
        git(env.ledger, "add", "-A")
        git(env.ledger, "commit", "-q", "-m", "an unrelated commit moves HEAD past old_sha")
        yaml_path.write_bytes(old_bytes + b"  # mutated once\n  # mutated twice, still uncompleted\n")

        result = worker.run(env.ledger, no_push=True)

        assert result.status == "stopped"
        assert result.stopped and intent.id in result.stopped[0]
        # Never enumerated, never handed to a model -- left exactly
        # where the STOP found it, for a human.
        assert intent.file_path.exists()
        log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
        assert "could not resolve an intent" in log_text


# ============================================ reconcile._RECONCILABLE_HOME gain


class TestReconcilableHomeExtension:
    """`reconcile._RECONCILABLE_HOME` gains `hosts.yaml`/`config.yaml`
    (the pin, independent of the intent mechanism above): a plain
    orphaned write to either — no intent involved at all, the ordinary
    "producer wrote it, could not commit it" shape — used to be
    completely invisible to `find_orphans` (no path-shape match
    whatsoever); it must now heal exactly like `compiled/*.yaml` already
    did."""

    def test_a_plain_hosts_yaml_orphan_is_healed(self, env):
        from self_learn.hosts import save_hosts, Hosts

        before = (env.ledger / "hosts.yaml").read_text(encoding="utf-8")
        save_hosts(env.ledger, Hosts(skills_root=env.host, projects=[], skills_root_mode="git"))
        assert (env.ledger / "hosts.yaml").read_text(encoding="utf-8") != before
        assert porcelain(env.ledger) != ""

        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert not result.refused, result
        assert env.ledger / "hosts.yaml" in result.committed
        assert porcelain(env.ledger) == ""

    def test_a_plain_config_yaml_orphan_is_healed(self, env):
        from self_learn import config as config_mod

        config_path = config_mod.config_path(env.ledger)
        data = config_mod.load_editable(env.ledger)
        data["worker"] = {"repair": False}
        config_mod.dump_editable(env.ledger, data)
        assert config_path.is_file()
        assert porcelain(env.ledger) != ""

        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert not result.refused, result
        assert config_path in result.committed
        assert porcelain(env.ledger) == ""


class TestHostAddAndRemoveIntents:
    """`host_add`/`host_remove` write the same single-step intent shape
    `TestCoreMechanics` already proves generically — this is the ONE
    end-to-end witness that the REAL verbs wire it in, via an ordinary
    (non-SIGKILL) exception raised between the write and `intents.
    complete` -- a plain interpreter-level crash needs no subprocess to
    simulate: it unwinds `commit_lock`'s context manager exactly the way
    a SIGKILL's kernel-level lock release does."""

    def test_host_add_recovers_from_a_crash_before_complete(self, env, tmp_path, monkeypatch):
        from self_learn import hosts as hosts_mod

        real_save_hosts = hosts_mod.save_hosts

        def _boom(*a, **k):
            path = real_save_hosts(*a, **k)
            raise RuntimeError("simulated crash before intents.complete")

        monkeypatch.setattr(hosts_mod, "save_hosts", _boom)
        new_host = tmp_path / "new-host"
        init_repo(new_host)
        before = load_hosts(env.ledger)

        with pytest.raises(RuntimeError, match="simulated crash"):
            hosts_mod.host_add(env.ledger, new_host, "project")

        assert list(intents.intents_dir(env.ledger).glob("*.json"))
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert load_hosts(env.ledger) == before
        assert porcelain(env.ledger) == ""

    def test_host_remove_recovers_from_a_crash_before_complete(self, env, tmp_path, monkeypatch):
        from self_learn import hosts as hosts_mod

        project_repo = tmp_path / "proj-repo"
        init_repo(project_repo)
        (project_repo / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(project_repo, "proj seed")
        hosts_mod.host_add(env.ledger, project_repo, "project")
        before = load_hosts(env.ledger)

        real_save_hosts = hosts_mod.save_hosts

        def _boom(*a, **k):
            real_save_hosts(*a, **k)
            raise RuntimeError("simulated crash before intents.complete")

        monkeypatch.setattr(hosts_mod, "save_hosts", _boom)
        with pytest.raises(RuntimeError, match="simulated crash"):
            hosts_mod.host_remove(env.ledger, project_repo)

        assert list(intents.intents_dir(env.ledger).glob("*.json"))
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert load_hosts(env.ledger) == before
        assert porcelain(env.ledger) == ""


# ============================================================ core mechanics


class TestCoreMechanics:
    """Direct exercise of `begin`/`complete`/`finish`/`recover` against a
    plain scratch repo — the shapes a full verb scenario cannot cheaply
    isolate."""

    def test_roll_forward_when_commit_never_ran(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("new", encoding="utf-8")
        intents.complete(intent)
        assert intent.file_path.is_file()

        result = intents.recover(repo)
        assert result.rolled_forward == [intent.id]
        assert not intent.file_path.exists()
        assert git(repo, "log", "-1", "--format=%s").stdout.strip() == "self-learn: test op"
        assert f.read_text(encoding="utf-8") == "new"

    def test_roll_forward_is_a_noop_when_the_commit_already_landed(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("new", encoding="utf-8")
        intents.complete(intent)
        # simulate: the commit landed for real, only `finish` never ran
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "self-learn: test op")
        sha_before = head(repo)

        result = intents.recover(repo)
        assert result.rolled_forward == [intent.id]
        assert head(repo) == sha_before
        assert not intent.file_path.exists()

    def test_restore_undoes_a_mid_transaction_crash(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("new", encoding="utf-8")  # crash before complete()

        result = intents.recover(repo)
        assert result.restored == [intent.id]
        assert f.read_text(encoding="utf-8") == "old"
        assert not intent.file_path.exists()
        assert porcelain(repo) == ""

    def test_restore_deletes_a_path_that_should_not_have_existed(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        new_f = repo / "new.txt"

        intent = intents.begin(repo, "test-op", [new_f], "self-learn: test op")
        new_f.write_text("premature", encoding="utf-8")  # crash before complete()

        result = intents.recover(repo)
        assert result.restored == [intent.id]
        assert not new_f.exists()
        assert not intent.file_path.exists()

    def test_stop_when_prior_content_is_unresolvable_anywhere(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("mutated", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "an unrelated commit moves HEAD past old_sha")
        f.write_text("further mutated, still uncompleted", encoding="utf-8")

        result = intents.recover(repo)
        assert result.stopped and intent.id in result.stopped[0]
        assert not result.rolled_forward and not result.restored
        assert intent.file_path.exists(), "a STOP must leave the intent in place"
        assert f.read_text(encoding="utf-8") == "further mutated, still uncompleted"
        # Gate r1 MAJOR-3(b): a STOP must not stage anything either --
        # "nothing is touched" (the module docstring's own promise)
        # means the INDEX too, not just the worktree bytes.
        assert git(repo, "diff", "--cached").stdout == ""

    def test_untracked_file_restores_from_the_inline_copy(self, tmp_path):
        """The pin-implied `old_inline` key: an UNTRACKED file's bytes
        are not in git's object store, so recovery can only restore them
        from the intent's own inline copy."""
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        f = repo / "untracked.txt"
        f.write_text("untracked original", encoding="utf-8")  # never committed

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        raw = json.loads(intent.file_path.read_text(encoding="utf-8"))
        assert raw["steps"][0].get("old_inline"), "untracked content must be captured inline"

        f.write_text("mutated, crash before complete()", encoding="utf-8")
        result = intents.recover(repo)
        assert result.restored == [intent.id]
        assert f.read_text(encoding="utf-8") == "untracked original"

    def test_oversize_untracked_step_stops_without_touching_bytes(self, tmp_path):
        """Gate r1 MAJOR-3(a): an untracked file BIGGER than `_INLINE_CAP`
        (64 KiB) gets no inline copy — recovery has no source at all for
        its pre-transaction bytes (not git, since it was never tracked;
        not the intent, since it is over the cap), so it must STOP,
        never silently accept whatever happens to be on disk.

        Gate r2 MAJOR-1: the fixture used to size itself from
        `intents._INLINE_CAP + 1` -- derived from the very constant this
        test exists to pin, so changing `_INLINE_CAP` to ANYTHING moved
        the fixture right along with it and this test could never redden
        on a cap change (measured: `_INLINE_CAP = 64 * 1024 * 1024` still
        passed). A literal size PLUS a separate assertion pinning the
        constant's own value closes that: raising the cap reddens the
        second line below, shrinking it reddens the first."""
        assert intents._INLINE_CAP == 64 * 1024, "the D7 pin itself"
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        f = repo / "big.bin"
        f.write_bytes(b"A" * 65_537)  # a literal 64 KiB + 1, untracked, over the cap

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        raw = json.loads(intent.file_path.read_text(encoding="utf-8"))
        assert "old_inline" not in raw["steps"][0], (
            "over the cap must NOT carry an inline copy — that is the "
            "whole point of the cap"
        )

        f.write_bytes(b"B" * 10)  # crash before complete(): mutated, uncompleted

        result = intents.recover(repo)
        assert result.stopped and intent.id in result.stopped[0]
        assert not result.rolled_forward and not result.restored
        assert intent.file_path.exists(), "a STOP must leave the intent in place"
        assert f.read_bytes() == b"B" * 10, "STOP must not touch the step's bytes"
        assert git(repo, "diff", "--cached").stdout == ""

    def test_recover_survives_a_ledger_moved_to_a_new_location(self, tmp_path):
        """Gate r1 minor-2: an intent opened against ``home`` must recover
        cleanly when ``home`` itself has moved (a restore from backup, or
        a relocated checkout) between the crash and the recovery call —
        storing ``step['path']`` HOME-RELATIVE (this fold) is what makes
        this possible: the ABSOLUTE path this fixture used to store would
        fall outside the new location's subtree and raise ``ValueError``
        out of every caller (`reconcile()`, `push`, the miner's own
        `except gitops.GitOpsError` — which does not catch it — and
        `worker.run`'s unguarded call)."""
        old_home = tmp_path / "old-location"
        init_repo(old_home)
        f = old_home / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(old_home, "seed")

        intent = intents.begin(old_home, "test-op", [f], "self-learn: test op")
        f.write_text("mutated, crash before complete()", encoding="utf-8")

        new_home = tmp_path / "new-location"
        shutil.move(str(old_home), str(new_home))

        result = intents.recover(new_home)
        assert result.restored == [intent.id]
        assert not result.stopped
        assert (new_home / "a.txt").read_text(encoding="utf-8") == "old"
        assert not (new_home / ".intents" / f"{intent.id}.json").exists()

    def test_head_show_converts_a_timeout_to_giterror(self, tmp_path, monkeypatch):
        """Gate r1 minor-3, then S3 ITEM 2: `_head_show` now calls
        `procs.run_bounded(..., binary=True)` instead of a bespoke
        `subprocess.run` — so the seam this test must wedge moved from
        `intents.subprocess.run` (which the migration leaves unreachable
        from this function: `intents.py` no longer calls `subprocess.run`
        at all) to `procs.subprocess.Popen`, the one `run_bounded` itself
        calls. `_FakePopen` mimics a real hang for the ONE argv this test
        cares about -- `.communicate()` raises `TimeoutExpired` on the
        first call (the wait), then returns clean output on the second
        (the post-killpg drain `run_bounded` always attempts) -- so
        `run_bounded` reaches its own `raise BoundedTimeout(...) from
        None`, which must still convert to `gitops.GitOpsError` here
        (`BoundedTimeout` subclasses `subprocess.TimeoutExpired`, so the
        existing `except subprocess.TimeoutExpired:` below keeps catching
        without any change to that line). `procs.subprocess` IS the
        stdlib `subprocess` module (not a copy), so patching its `Popen`
        attribute is process-global -- every OTHER matching argv (here,
        `gitops._index_lock_note`'s own real `git rev-parse --git-dir`,
        called while building the error message this test asserts on)
        must fall through to the REAL `Popen`, or it wedges too."""
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        real_popen = procs.subprocess.Popen
        target_argv = ["git", "-C", str(repo), "show", "HEAD:a.txt"]

        class _FakePopen:
            def __new__(cls, argv, **kwargs):
                if list(argv) != target_argv:
                    return real_popen(argv, **kwargs)
                return object.__new__(cls)

            def __init__(self, argv, **kwargs):
                self.argv = argv
                self.pid = 2**30  # never a real pid; getpgid must miss
                self.returncode = 0
                self._calls = 0

            def communicate(self, input=None, timeout: float | None = None):
                self._calls += 1
                if self._calls == 1:
                    raise subprocess.TimeoutExpired(
                        cmd=self.argv, timeout=timeout if timeout is not None else 0.0
                    )
                return b"", b""

        monkeypatch.setattr(procs.subprocess, "Popen", _FakePopen)

        with pytest.raises(gitops.GitOpsError, match="git show"):
            intents._head_show(repo, "a.txt")

    def test_recover_reports_a_corrupt_intent_file_as_unreadable(self, tmp_path):
        """Gate r2 nit-1: a genuinely corrupt (unparseable) intent file
        must report "unreadable intent file" -- distinct from
        "unresolvable intent", which names a real, half-written step the
        JSON parses fine but cannot restore. Widening `recover()`'s `try`
        to cover `_recover_one` too (gate r1 minor-2) folded BOTH failure
        phases into the same message; splitting them back out means an
        operator reads which repair applies (fix/delete the file, vs.
        inspect the path the message names) directly off the line,
        without opening the file first."""
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        bad = intents.intents_dir(repo) / "deadbeef0000.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not valid json", encoding="utf-8")

        result = intents.recover(repo)
        assert result.stopped and "unreadable intent file" in result.stopped[0]
        assert "unresolvable intent" not in result.stopped[0]
        assert bad.is_file(), "a STOP must leave the intent file in place"

    def test_recover_reports_a_malformed_intent_as_unresolvable(self, tmp_path):
        """Gate r2 nit-1's other half: valid JSON that does not match the
        intent schema (here, missing `steps` entirely) reaches
        `_from_dict`, raises `KeyError`, and must report "unresolvable
        intent" -- the file itself was perfectly readable, so the
        "unreadable" wording would misdirect an operator toward fixing
        JSON syntax that was never broken."""
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        bad = intents.intents_dir(repo) / "deadbeef0001.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text(
            json.dumps(
                {
                    "op": "test-op",
                    "id": "deadbeef0001",
                    "started": "2026-09-05T00:00:00Z",
                    # `steps` and `commit_subject` deliberately omitted --
                    # `_from_dict` indexes both unconditionally.
                }
            ),
            encoding="utf-8",
        )

        result = intents.recover(repo)
        assert result.stopped and "unresolvable intent" in result.stopped[0]
        assert "unreadable intent file" not in result.stopped[0]
        assert bad.is_file(), "a STOP must leave the intent file in place"

    def test_recover_reports_a_non_utf8_intent_file_as_unreadable(self, tmp_path):
        """Gate r3: the r2 fold's read-leg guard was `(OSError,
        json.JSONDecodeError)` -- too narrow. `f.read_text(encoding=
        "utf-8")` on a non-UTF-8 file raises `UnicodeDecodeError` BEFORE
        `json.loads` is even reached, and that exception is a
        `ValueError` subclass too, but NOT a `JSONDecodeError` — it
        escaped uncaught out of `recover()`, and past every caller:
        `reconcile()` (so `push` and the miner, whose `except gitops.
        GitOpsError` does not catch a bare `ValueError`), and `worker.
        run`'s unguarded call. The guard is now `(OSError, ValueError)`
        -- both `UnicodeDecodeError` and `json.JSONDecodeError` are
        `ValueError` subclasses, so this still reports "unreadable
        intent file", never "unresolvable intent" (this file never gets
        far enough to reach that phase)."""
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        bad = intents.intents_dir(repo) / "deadbeef0002.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"\xff\xfe" + b"A" * 93)  # 95 bytes, not valid UTF-8

        result = intents.recover(repo)
        assert result.stopped and "unreadable intent file" in result.stopped[0]
        assert "unresolvable intent" not in result.stopped[0]
        assert bad.is_file(), "a STOP must leave the intent file in place"

        # `reconcile()` calls `intents.recover` BEFORE its own orphan
        # scan -- it must forward the same stopped entry, never raise.
        reconcile_result = reconcile_mod.reconcile(repo, no_push=True)
        assert (
            reconcile_result.stopped
            and "unreadable intent file" in reconcile_result.stopped[0]
        )

        # `worker.run` calls `intents.recover` at START, UNGUARDED (no
        # `except` around it at all) -- it must not crash on the same
        # `UnicodeDecodeError`. (2026-09-11, S-62 §7.2a.5(4): a STOP
        # found here now ENDS the run rather than logging and reaching
        # `idle` -- the pre-S-62 assertion here was exactly the
        # "log it and proceed" behavior this sprint replaces.)
        worker_result = worker.run(repo, no_push=True)
        assert worker_result.status == "stopped"
        assert worker_result.stopped and "unreadable intent file" in worker_result.stopped[0]


class TestLedgerWriteNestedAcquire:
    """S-62 (§7.2a.5(2)): the mandatory mutation :func:`intents.
    ledger_write`'s own docstring names as the single sharpest edge in
    this design. Re-running recovery on a NESTED acquire -- after the
    caller's own ``intents.begin``/``complete`` -- would find the live
    transaction's OWN intent with every step's ``new_sha`` already
    verifying against disk (``complete()`` runs before the caller's
    commit, same as every real ``_stage_and_commit`` call site), read
    that as roll-forward-able, and finish it out from under the
    still-running transaction before its own commit ever lands. This
    is the ONE test the ``already_held`` pre-check exists for; every
    other lock-holding call site this sprint converts rests on it
    holding."""

    def test_nested_acquire_does_not_touch_a_completed_but_unfinished_intent(
        self, tmp_path
    ):
        repo = tmp_path / "repo"
        init_repo(repo)
        target = repo / "a.md"
        target.write_text("before\n", encoding="utf-8")
        commit_all(repo, "seed")

        with intents.ledger_write(repo):
            intent = intents.begin(repo, "test", [target], "self-learn: test nested")
            target.write_text("after\n", encoding="utf-8")
            intents.complete(intent)  # every new_sha now verifies against disk

            marker = intent.file_path
            before_bytes = marker.read_bytes()

            with intents.ledger_write(repo) as nested:
                assert nested.rolled_forward == []
                assert nested.restored == []
                assert nested.stopped == []

            # The nested acquire must not have touched the live intent
            # at all -- not finished it, not rewritten it, and not
            # committed on the outer transaction's behalf.
            assert marker.is_file(), "a nested acquire must not finish the live intent"
            assert marker.read_bytes() == before_bytes
            assert git(repo, "status", "--porcelain").stdout.strip() != ""

            intents.finish(intent)
        gitops.stage_and_commit(repo, [target], "self-learn: test nested")
        assert not marker.exists()
        assert git(repo, "status", "--porcelain").stdout.strip() == ""
