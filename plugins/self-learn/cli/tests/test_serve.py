"""U-engine Phase 2 -- `self-learn serve`'s own criteria.

Spec: `docs/specs/self-learn/drafts/u-engine-shared-sdk-core-spec.md`
Sec 7 (Phase 2 criteria): HP (the process), SUP (supervision), PORT
(portability, PORT1 -- PORT2/PORT3 live in install.sh's own dry-run and
in `ui/tests/test_service_unit.py` respectively), and `MS1-seq`, the
criterion that GATES this phase (Sec 5.2a, Sec 7.1).

Every SDK-driving test below uses `sdksession.FakeSdkClient` directly --
never the real `claude_agent_sdk` and never a subprocess `claude`
binary -- so none of it needs `SELF_LEARN_SDK_CLI_PATH` or the fake CLI
fixture `test_invocation_sdk.py` uses for the CLI backend's own tests.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from self_learn import gitops, miner, provider, serve, steward, worker
from self_learn import overseer as overseer_package
from self_learn.overseer import run as overseer_run
from self_learn.invocation.contract import Outcome
from self_learn.invocation_sdk import events as events_mod
from self_learn.invocation_sdk import lifecycle as lifecycle_mod
from self_learn.sdksession import events as sdk_events_mod
from self_learn.sdksession.fake import FakeSdkClient

from datetime import datetime, timezone

# Gate r1 M-2: the strengthened HP4 test below drives the REAL
# `worker.run` (never monkeypatched) through its own run-end follow-on
# DECISION, the same way `test_worker.py::test_kick_mid_run_triggers_
# followon` already does -- so it reuses that armor-pinned file's own
# fixtures/helpers by import rather than re-deriving them (nothing here
# edits `test_worker.py`; pytest resolves an imported fixture by name
# exactly as if it were declared locally).
from test_worker import env, sdk_fake_worker, seed_pending, shim_writes  # noqa: F401
from support import commit_all, make_home

_SRC_DIR = Path(serve.__file__).resolve().parent


def test_u10_steward_runs_after_worker_and_on_a_tick_where_mine_is_not_due(
    monkeypatch, tmp_path
):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    order = []
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: False)
    monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: True)
    monkeypatch.setattr(
        serve,
        "_run_steward_job",
        lambda home: order.append("steward") or steward.RunResult("idle"),
    )

    records = serve._run_tick(
        tmp_path / "home", cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    )

    assert [record.name for record in records] == ["steward"]
    assert order == ["steward"]

    order.clear()
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: True)
    monkeypatch.setattr(
        serve,
        "_run_mine_job",
        lambda home: order.append("mine") or miner.MineResult(status="ok", landed=["c1"]),
    )
    monkeypatch.setattr(
        serve,
        "_run_worker_job",
        lambda home: order.append("worker") or worker.RunResult(status="ok"),
    )
    serve._run_tick(
        tmp_path / "home", cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    )
    assert order == ["mine", "worker", "steward"]


def test_u10_steward_due_requires_fresh_proposal_cooldown_and_no_stop(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    entry = object()
    proposal = home / "proposals" / "lrn-deadbeef.yaml"
    proposal.parent.mkdir()
    proposal.write_text("version: 1\n", encoding="utf-8")
    (home / "config.yaml").write_text(
        "steward:\n  enabled: true\n  cooldown_secs: 50\n", encoding="utf-8"
    )
    monkeypatch.setattr(serve.steward, "_eligible_proposals", lambda actual: [(entry, {})])
    monkeypatch.setattr(serve, "_proposal_commit_epoch", lambda actual, path: 200.0)
    monkeypatch.setattr(serve, "_eligible_proposal_paths", lambda actual: [proposal])
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: "1970-01-01T00:01:40+00:00")
    clear = type("IntentState", (), {"stopped": []})()
    stopped = type("IntentState", (), {"stopped": [object()]})()
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: clear)

    assert serve._steward_is_due(home, cache_dir, 151.0) is True
    assert serve._steward_is_due(home, cache_dir, 149.0) is False
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: stopped)
    assert serve._steward_is_due(home, cache_dir, 151.0) is False
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: clear)
    monkeypatch.setattr(serve, "_proposal_commit_epoch", lambda actual, path: 99.0)
    assert serve._steward_is_due(home, cache_dir, 151.0) is False

    (home / "config.yaml").write_text(
        "steward:\n  enabled: false\n  cooldown_secs: 50\n", encoding="utf-8"
    )
    monkeypatch.setattr(serve, "_proposal_commit_epoch", lambda actual, path: 200.0)
    assert serve._steward_is_due(home, cache_dir, 151.0) is False

    (home / "config.yaml").write_text(
        "steward:\n  enabled: true\n  cooldown_secs: 50\n", encoding="utf-8"
    )
    monkeypatch.setattr(serve, "_eligible_proposal_paths", lambda actual: [])
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: None)
    assert serve._steward_is_due(home, cache_dir, 151.0) is False


def test_u10_describe_next_names_the_steward(monkeypatch, tmp_path):
    monkeypatch.setattr(serve, "_today_mine_target", lambda cache, now: now + 60)
    assert "steward" in serve._describe_next(tmp_path / "home", tmp_path, 100.0)


def test_u10_steward_due_for_committed_unfinished_work_without_proposals(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "steward:\n  enabled: true\n  cooldown_secs: 50\n", encoding="utf-8"
    )
    clear = type("IntentState", (), {"stopped": []})()
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: clear)
    monkeypatch.setattr(serve.steward, "committed_manifests", lambda actual: [{
        "run_id": "run-pending", "status": "unfinished",
        "last_attempt_at": "1970-01-01T00:01:40+00:00",
    }])
    monkeypatch.setattr(serve.steward, "_reconsider_proposals", lambda actual: ([], {}))
    monkeypatch.setattr(serve, "_eligible_proposal_paths", lambda actual: [])

    assert serve._steward_is_due(home, tmp_path / "cache", 151.0) is True
    assert serve._steward_is_due(home, tmp_path / "cache", 149.0) is False


def test_u10_run_forever_gates_steward_on_its_threaded_home(
    monkeypatch, tmp_path
):
    home_a = tmp_path / "home-a"
    home_b = tmp_path / "home-b"
    home_a.mkdir()
    home_b.mkdir()
    (home_a / "config.yaml").write_text(
        "steward:\n  enabled: false\n", encoding="utf-8"
    )
    (home_b / "config.yaml").write_text(
        "steward:\n  enabled: true\n", encoding="utf-8"
    )
    monkeypatch.setenv("SELF_LEARN_HOME", str(home_b))
    monkeypatch.setattr(serve, "_mine_is_due", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        serve, "_eligible_proposal_paths", lambda actual: [actual / "proposal.yaml"]
    )
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: None)
    calls = []
    monkeypatch.setattr(
        serve,
        "_run_steward_job",
        lambda actual: calls.append(actual) or steward.RunResult("applied"),
    )

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    assert serve.run_forever(
        home_a, cache_dir=cache_dir, tick_secs=0.01, max_ticks=1
    ) == 0
    assert calls == []


def _overseer_schedule_home(tmp_path: Path, *, enabled: bool = True) -> Path:
    home = tmp_path / "overseer-home"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text(
        f"overseer:\n  enabled: {'true' if enabled else 'false'}\n",
        encoding="utf-8",
    )
    return home


def test_o4_overseer_due_calendar_cooldown_unfinished_enabled_and_stop(
    monkeypatch, tmp_path
):
    """Breaks if calendar, cooldown, unfinished-work, opt-in, or STOP is ignored."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    home = _overseer_schedule_home(tmp_path)
    clear = type("IntentState", (), {"stopped": []})()
    stopped = type("IntentState", (), {"stopped": [object()]})()
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: clear)
    monkeypatch.setattr(overseer_package, "has_unfinished_work", lambda actual: False)
    monkeypatch.setattr(overseer_run, "last_run_iso", lambda actual: None)
    monkeypatch.setattr(serve, "_overseer_recently_attempted", lambda actual, now: False)

    target = time.mktime((2026, 9, 13, 4, 15, 0, 0, 0, -1))  # Sunday
    assert serve._overseer_is_due(home, cache_dir, target - 24 * 60 * 60) is False
    assert serve._overseer_is_due(home, cache_dir, target + 1) is True
    monkeypatch.setattr(serve, "_overseer_recently_attempted", lambda actual, now: True)
    assert serve._overseer_is_due(home, cache_dir, target + 1) is False

    monday = target + 24 * 60 * 60
    monkeypatch.setattr(serve, "_overseer_recently_attempted", lambda actual, now: False)
    monkeypatch.setattr(overseer_package, "has_unfinished_work", lambda actual: True)
    assert serve._overseer_is_due(home, cache_dir, monday) is True

    disabled = _overseer_schedule_home(tmp_path / "disabled", enabled=False)
    assert serve._overseer_is_due(disabled, cache_dir, monday) is False
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: stopped)
    assert serve._overseer_is_due(home, cache_dir, monday) is False


def test_o4_overseer_attempt_cooldown_reads_the_threaded_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    now = time.time()
    recent = datetime.fromtimestamp(now - 1).astimezone().isoformat()
    (cache_dir / "overseer.journal").write_text(
        json.dumps({"at": recent, "status": "refused"}) + "\n",
        encoding="utf-8",
    )
    assert serve._overseer_recently_attempted(cache_dir, now) is True
    assert (
        serve._overseer_recently_attempted(
            cache_dir, now + miner.ATTEMPT_COOLDOWN_SECS + 1
        )
        is False
    )


def test_o4_tick_order_is_mine_worker_steward_overseer(monkeypatch, tmp_path):
    """Breaks if the fourth job moves ahead of any earlier producer."""
    home = _overseer_schedule_home(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    order: list[str] = []
    monkeypatch.setattr(serve, "_mine_is_due", lambda *args, **kwargs: True)
    monkeypatch.setattr(serve, "_steward_is_due", lambda *args, **kwargs: True)
    monkeypatch.setattr(serve, "_overseer_is_due", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        serve, "_run_mine_job",
        lambda actual: order.append("mine") or miner.MineResult(status="ok", landed=["c1"]),
    )
    monkeypatch.setattr(
        serve, "_run_worker_job",
        lambda actual: order.append("worker") or worker.RunResult(status="ok"),
    )
    monkeypatch.setattr(
        serve, "_run_steward_job",
        lambda actual: order.append("steward") or steward.RunResult("idle"),
    )
    monkeypatch.setattr(
        serve, "_run_overseer_job",
        lambda actual: order.append("overseer") or overseer_run.RunResult("applied", 0, "run"),
    )

    records = serve._run_tick(
        home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    )
    assert [record.name for record in records] == [
        "mine", "worker", "steward", "overseer"
    ]
    assert order == ["mine", "worker", "steward", "overseer"]


def test_o4_disabled_overseer_never_creates_a_job_record(monkeypatch, tmp_path):
    """Breaks if _run_tick bypasses the enabled-aware due predicate."""
    home = _overseer_schedule_home(tmp_path, enabled=False)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(serve, "_mine_is_due", lambda *args, **kwargs: False)
    monkeypatch.setattr(serve, "_steward_is_due", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        serve, "_run_overseer_job",
        lambda actual: pytest.fail("disabled overseer reached the job runner"),
    )
    assert serve._run_tick(
        home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    ) == []


def test_o4_describe_next_names_the_fourth_job(monkeypatch, tmp_path):
    monkeypatch.setattr(serve, "_today_mine_target", lambda cache, now: now + 60)
    monkeypatch.setattr(serve, "_overseer_target_for", lambda now: now + 120)
    text = serve._describe_next(tmp_path / "home", tmp_path, 100.0)
    assert f"overseer at {datetime.fromtimestamp(220).isoformat(timespec='seconds')}" in text


# ===================================================================== #
# HP -- the process
# ===================================================================== #


def _run_serve_subprocess(tmp_path: Path, *, extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["SELF_LEARN_HOME"] = str(home)
    env["SELF_LEARN_MINER"] = "0"
    env["SELF_LEARN_MINER_AUTOKICK"] = "0"
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen([sys.executable, "-m", "self_learn.cli", "serve"], env=env)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_hp1_serve_exits_0_on_sigterm_and_sigint_within_a_bound(tmp_path, sig):
    """`HP1` -- driven as a REAL subprocess. No job is scheduled (a
    fresh home, no poke, and the daily mine target is either in the
    future or `SELF_LEARN_MINER=0` short-circuits it instantly even if
    due -- see `test_hp3`'s sibling reasoning), so "no job left
    mid-flight" is trivially true here; `test_ms1_seq_*` below proves
    a job in flight always runs to completion instead of being cut off."""
    proc = _run_serve_subprocess(tmp_path)
    try:
        time.sleep(0.8)  # let it tick at least once
        t0 = time.time()
        proc.send_signal(sig)
        rc = proc.wait(timeout=10)
        elapsed = time.time() - t0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    assert rc == 0, rc
    assert elapsed < 5.0, f"took {elapsed}s to exit after {sig!r}"


def test_hp2_serve_never_calls_run_sync_or_asyncio_run():
    """`HP2` -- AST test over `serve.py`'s OWN source (§4.6 R-2: the
    hazard is a NEW event loop inside `serve` nesting into `run_sync`'s
    `asyncio.run`; `serve` calls `miner.run`/`worker.run` as plain
    blocking Python calls -- the same shape `cli._cmd_mine`/`cli.
    _cmd_worker` already use today -- so it opens no loop of its own for
    that nesting to ever occur in)."""
    tree = ast.parse((_SRC_DIR / "serve.py").read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        dotted = None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            dotted = f"{func.value.id}.{func.attr}"
        if name == "run_sync" or dotted == "asyncio.run":
            hits.append(node.lineno)
    assert hits == [], f"serve.py calls run_sync/asyncio.run at line(s) {hits}"


def _ledger_mutation_hits(path: Path) -> list[str]:
    """`HP3`'s instrument: does `path`'s OWN source directly call
    `gitops.stage`/`gitops.commit`/`gitops.push_if_remote`, a mutating
    `_git`/`_git_ok` subcommand, or a `Record.write`-shaped `.write(...)`
    call? Scoped to the file's own text, NOT a transitive call-graph
    walk: `serve` legitimately calls `miner.run`/`worker.run`, which DO
    commit (producers commit their own writes, H-5) -- the property HP3
    checks is that `serve.py` itself never does, directly."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            owner = func.value.id if isinstance(func.value, ast.Name) else None
            if owner == "gitops" and func.attr in ("stage", "commit", "push_if_remote"):
                hits.append(f"L{node.lineno}: gitops.{func.attr}(...)")
            if func.attr == "write":
                recv = func.value
                recv_name = recv.id if isinstance(recv, ast.Name) else getattr(recv, "attr", None)
                if recv_name not in ("buf", "fh", "f", "sys", "stderr", "stdout", "out", "handle", "proc"):
                    hits.append(f"L{node.lineno}: {recv_name}.write(...)")
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if name in ("_git", "_git_ok") and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            if node.args[1].value in ("add", "commit", "mv", "rm", "push"):
                hits.append(f"L{node.lineno}: git {node.args[1].value}")
    return hits


def test_hp3_serve_never_stages_commits_or_pushes_the_ledger():
    hits = _ledger_mutation_hits(_SRC_DIR / "serve.py")
    assert hits == [], f"serve.py directly touches the ledger: {hits}"


def test_hp3_positive_control_the_sweep_finds_real_hits_in_verbs_py():
    """The sweep must not be vacuous -- run over a file KNOWN to commit
    ledger writes and confirm it actually reports something."""
    hits = _ledger_mutation_hits(_SRC_DIR / "verbs.py")
    assert hits, "the HP3 sweep found nothing in verbs.py -- it is vacuous"


def test_hp4_landed_mine_job_triggers_an_in_process_worker_follow_on_no_popen(monkeypatch, tmp_path):
    """`HP4` -- register item #11, closed by construction. A landed mine
    job is followed, IN THE SAME PROCESS, by a real call to
    `worker.run` -- never `worker.kick` (the setsid `Popen` HP4
    replaces) and never any `subprocess.Popen` at all during the
    handoff."""
    worker_run_calls = []

    def fake_worker_run(home, **kwargs):
        worker_run_calls.append((home, kwargs))
        return worker.RunResult(status="ok")

    def fake_miner_run(home, **kwargs):
        return miner.MineResult(status="ok", landed=["cand-1"])

    def spy_popen(*a, **k):
        raise AssertionError("subprocess.Popen must never fire during the in-process handoff")

    def spy_kick(*a, **k):
        raise AssertionError(
            "worker.kick must never fire during the in-process handoff -- "
            "that IS the setsid Popen path HP4 replaces"
        )

    monkeypatch.setattr(worker, "run", fake_worker_run)
    monkeypatch.setattr(miner, "run", fake_miner_run)
    monkeypatch.setattr(worker, "kick", spy_kick)
    monkeypatch.setattr(subprocess, "Popen", spy_popen)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    serve.request_poke(cache_dir)  # force this tick to run the mine job
    records = serve._run_tick(
        Path("/irrelevant-home"), cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    )

    assert [r.name for r in records] == ["mine", "worker"]
    assert len(worker_run_calls) == 1


def test_fw85_run_mine_job_returns_the_mine_result_object_untranslated(monkeypatch):
    """FW-85 (U0) acceptance #3: `_run_mine_job` is a plain call to
    `miner.run` and hands its caller the `MineResult` object BACK
    UNCHANGED -- `serve.py` consumes result objects, never an exit
    code, so `_cmd_mine`'s new `_MINE_RUN_EXIT` mapping (`cli.py`) has
    nothing to do with this path. `status="held-gate"` is deliberately
    a status whose CLI exit code changed under FW-85 (0 -> EXIT_HELD)
    -- proving the serve scheduling path never even looks at it."""
    sentinel = miner.MineResult(status="held-gate", run_id="run-fw85")

    def fake_miner_run(home, **kwargs):
        assert kwargs.get("trigger") == "serve"
        return sentinel

    monkeypatch.setattr(miner, "run", fake_miner_run)
    result = serve._run_mine_job(Path("/irrelevant-home"))
    assert result is sentinel


def test_hp4_m2_real_worker_run_never_opens_a_followon_window_from_a_serve_tick(
    env, sdk_fake_worker, monkeypatch, tmp_path
):
    """Gate r1 M-2, strengthened per the gate's own instruction: the test
    above monkeypatches `worker.run` wholesale, so it CANNOT see M-2's
    defect (the run-end follow-on lives INSIDE the real `worker.run`,
    gated by `worker._autokick_disabled()`). This test drives the REAL
    `worker.run` -- never monkeypatched -- through its own follow-on
    DECISION (a real `worker.dirty` marker, the SAME recipe
    `test_worker.py::test_kick_mid_run_triggers_followon` uses), with
    only the lowest-level primitive, `_spawn_window`, patched to RAISE.
    Before the M-2 fix this test failed with that AssertionError; after
    it, `worker.run` reaches `_autokick_disabled()` (True, held by
    `serve._worker_autokick_disabled()` across the whole tick) and
    reports `followon=False` without ever calling `_spawn_window`."""
    monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)  # ambient
    # unset, exactly gate r1's own measurement ("autokick_during_worker
    # = None") -- serve's OWN neutralisation is what must hold, not a
    # test-level kill switch already doing the job for it.

    rid = seed_pending(env)
    dirty = worker.cache_dir() / "worker.dirty"
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", f"{shim_writes(env, rid)}\ntouch {dirty}")

    def _raise_if_spawned(home, *, no_push=False):
        raise AssertionError(
            "subprocess spawn window must never open from inside a serve "
            "tick -- gate r1 M-2's exact shape"
        )

    monkeypatch.setattr(worker, "_spawn_window", _raise_if_spawned)
    monkeypatch.setattr(miner, "run", lambda home, **kw: miner.MineResult(status="ok", landed=["c1"]))

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    serve.request_poke(cache_dir)
    records = serve._run_tick(env.home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)

    assert [r.name for r in records] == ["mine", "worker"]
    worker_record = records[1]
    assert worker_record.ok, f"real worker.run raised: {worker_record.error}"
    assert worker_record.result.followon is False


def test_hp4_negative_space_reverting_to_worker_kick_is_caught(monkeypatch, tmp_path):
    """`N-1`'s positive control, observed directly: patching `serve`'s
    own worker-job body to go through `worker.kick` (the setsid `Popen`
    shape HP4 replaces) instead of `worker.run` must be CAUGHT."""
    monkeypatch.setattr(miner, "run", lambda home, **kw: miner.MineResult(status="ok", landed=["c1"]))
    monkeypatch.setattr(serve, "_run_worker_job", lambda home: worker.kick(home))

    calls = []
    monkeypatch.setattr(worker, "kick", lambda *a, **k: calls.append((a, k)) or "spawned")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    serve.request_poke(cache_dir)
    serve._run_tick(Path("/irrelevant-home"), cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)
    assert calls, "reverting to worker.kick should have been observed -- N-1's own shape"


def test_hp5_per_job_timeouts_still_bite_through_a_serve_scheduled_job(monkeypatch, tmp_path):
    """`HP5` -- the three timeouts a `serve`-scheduled job actually
    reaches (`SELF_LEARN_READER_TIMEOUT_SECS` via the mine job,
    `SELF_LEARN_INVOKE_TIMEOUT_SECS`/`SELF_LEARN_REPAIR_TIMEOUT_SECS`
    via the worker job) are read AT CALL TIME by `worker.
    invoke_timeout_secs`/`repair_timeout_secs`/`miner.reader_timeout_
    secs` -- unchanged, env-overridable, and `serve` does not shadow or
    cache them anywhere."""
    seen: dict[str, float] = {}

    def fake_mine_job(home):
        seen["reader"] = miner.reader_timeout_secs()
        return miner.MineResult(status="ok")

    def fake_worker_job(home):
        seen["invoke"] = worker.invoke_timeout_secs()
        seen["repair"] = worker.repair_timeout_secs()
        return worker.RunResult(status="ok")

    monkeypatch.setattr(serve, "_run_mine_job", fake_mine_job)
    monkeypatch.setattr(serve, "_run_worker_job", fake_worker_job)
    monkeypatch.setenv("SELF_LEARN_READER_TIMEOUT_SECS", "111")
    monkeypatch.setenv("SELF_LEARN_INVOKE_TIMEOUT_SECS", "222")
    monkeypatch.setenv("SELF_LEARN_REPAIR_TIMEOUT_SECS", "333")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    serve.run_one_job(cache_dir, serve.Job("mine", "miner-reader", lambda: serve._run_mine_job(Path("/x"))))
    serve.run_one_job(cache_dir, serve.Job("worker", "worker", lambda: serve._run_worker_job(Path("/x"))))

    assert seen == {"reader": 111.0, "invoke": 222.0, "repair": 333.0}


def test_hp5_analyst_timeout_is_untouched_by_serve():
    """`SELF_LEARN_ANALYST_TIMEOUT` is inherited "unchanged" (spec Sec
    5.2's own wording) precisely because `serve` never calls the
    analyst at all -- `analyst.analyze` is invoked from `teach.py`
    (spec Sec 5.2a.1), a verb, not a job `serve` schedules. Grepped
    rather than driven: there is no code path to exercise."""
    text = (_SRC_DIR / "serve.py").read_text(encoding="utf-8")
    assert "SELF_LEARN_ANALYST_TIMEOUT" not in text
    assert "analyst" not in text.lower()


def test_hp6_fresh_heartbeat_pokes_and_spawns_nothing(monkeypatch, tmp_path):
    """`HP6` leg 1. `conftest.py`'s autouse fixture sets
    `SELF_LEARN_MINER_AUTOKICK=0` for every test (correctly -- no test
    should EVER spawn a real detached watchdog run by accident); this
    ONE test deliberately unsets it to reach the poke branch, exactly
    the way `test_hp6_no_heartbeat_is_byte_identical_to_today` (below)
    proves that same kill switch still wins when it IS set."""
    monkeypatch.delenv("SELF_LEARN_MINER_AUTOKICK", raising=False)
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)  # gate r1 N-4: both kill switches leak from conftest/ambient env; only AUTOKICK was cleared before
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append((a, k)) or (_ for _ in ()).throw(
        AssertionError("Popen must not be called when serve pokes")
    ))
    home = tmp_path / "home"
    # M-P fold r1 (F1): `maybe_kick`'s heartbeat read now threads `home`
    # (previously bare/ambient) -- the heartbeat this test writes must
    # therefore live under THIS `home`'s own cache_dir, matching what
    # `maybe_kick(home)` now actually checks.
    cache_dir = worker.cache_dir(home)
    serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)

    result = miner.maybe_kick(home)

    assert result == "poked"
    assert calls == []
    assert (cache_dir / "serve.poke").is_file()


def test_hp6_no_heartbeat_is_byte_identical_to_today(monkeypatch, tmp_path):
    """`HP6` leg 2 -- no heartbeat at all: every existing leg
    (disabled / fresh / cooling / busy / spawned) is reached exactly as
    before this unit. The kill switches in particular must still win
    even before the (now-absent) poke check would matter."""
    home = tmp_path / "home"
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    assert miner.maybe_kick(home) == "disabled"
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    assert miner.maybe_kick(home) == "disabled"


def _noon_today_epoch() -> float:
    """A `now` baseline guaranteed past today's mine target (03:30 local
    +/- 15m jitter, `MINE_HOUR`/`MINE_MINUTE`/`MINE_JITTER_SECS`) and
    guaranteed same-calendar-day as `now + miner.ATTEMPT_COOLDOWN_SECS`
    (2h) -- mirrors `_today_mine_target`'s own `time.mktime` construction
    so the test is deterministic regardless of the real wall clock the
    suite happens to run at."""
    local = time.localtime()
    return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 12, 0, 0, 0, 0, -1))


def test_hp8_a_failing_mine_is_retried_at_most_once_per_cooldown_window(monkeypatch, tmp_path):
    """`HP8` (spec r6, gate r1 B-1) -- `serve`'s tick loop must not
    re-attempt a failing mine inside `miner.ATTEMPT_COOLDOWN_SECS`, the
    SAME guard `maybe_kick`'s watchdog already applies to the any-verb
    autokick (miner.py:1717) against the SAME file `miner.run` touches
    on every attempt (:1759). Frozen/advanced `now` (never real time --
    `_run_tick`/`_mine_is_due` take `now` explicitly), a miner that
    always fails: three ticks inside the window must produce exactly
    ONE attempt; a fourth tick past the window must produce a second."""
    now_box = {"t": _noon_today_epoch()}
    attempts: list[float] = []
    attempt_iso_box: dict[str, str | None] = {"iso": None}

    def _fake_run(home, trigger="serve", **kw):
        attempts.append(now_box["t"])
        attempt_iso_box["iso"] = datetime.fromtimestamp(
            now_box["t"], tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return miner.MineResult(status="failed")

    monkeypatch.setattr(miner, "run", _fake_run)
    monkeypatch.setattr(miner, "last_run_iso", lambda: None)  # never succeeded
    monkeypatch.setattr(miner, "last_attempt_iso", lambda: attempt_iso_box["iso"])

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    home = Path("/irrelevant-home")

    for delta in (0, 30, 60):  # three ticks, all inside the 2h window
        serve._run_tick(home, cache_dir, now=now_box["t"] + delta, pid=os.getpid(), tick_secs=60.0)
    assert len(attempts) == 1, f"expected exactly one attempt across N ticks inside the window, got {attempts}"

    now_box["t"] += miner.ATTEMPT_COOLDOWN_SECS + 60  # past the window, same day
    serve._run_tick(home, cache_dir, now=now_box["t"], pid=os.getpid(), tick_secs=60.0)
    assert len(attempts) == 2, "a second attempt should fire once the cooldown window has elapsed"


def test_hp8_real_files_the_touch_and_the_read_address_the_same_file(tmp_path, monkeypatch):
    """`HP8` fidelity leg (gate r2 N-2'): the arithmetic test above
    monkeypatches `miner.last_attempt_iso`, so it proves `_mine_is_due`'s
    ARITHMETIC but never that the real `miner.run` touch (`miner.py
    :1759`) and the real `last_attempt_iso()` read (`:209`) address the
    SAME file -- the gate's own live 8-tick run closed that gap; this
    leg ships it as a test. Nothing stubbed: a genuinely nonexistent
    home (`miner.run`'s refused-home leg, `home_state() == "missing"`),
    the REAL in-process `serve` scheduler loop (`run_forever`, not a
    hand-rolled `_run_tick` loop), and 8 REAL ticks at a short real
    interval. ONE `request_poke` kicks the daemon into evaluating
    immediately -- gate r2 B-1's `ignore_schedule` leg it exercises is
    itself gated by the SAME `KICK_AFTER_SECS`/cooldown rule as the
    clock path (see `_mine_is_due`), so this is not the poke-forces-mine
    antipattern gate r2 flagged in the OLD version of the third HP8 test
    below -- a poke here still has to pass real gates, and only fires
    once. Date-of-day independent: a fresh home's last-run is absent
    (age effectively infinite), always past `KICK_AFTER_SECS` regardless
    of wall-clock time; ticks 2-8 are blocked by the REAL cooldown
    (real mtime vs real `now`, never a frozen/real mismatch)."""
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    home = tmp_path / "nonexistent-home"  # never created
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdgcache"))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    serve.request_poke(cache_dir)
    rc = serve.run_forever(home, tick_secs=0.2, cache_dir=cache_dir, max_ticks=8)
    assert rc == 0

    real_cache = worker.cache_dir()
    attempt_path = real_cache / "miner" / "miner.last-attempt"
    assert attempt_path.is_file(), (
        "the real miner.run touch (:1759) never reached the path the "
        "real last_attempt_iso() read (:209) resolves -- touch and read "
        "do not address the same file"
    )

    journal_lines = [
        json.loads(line)
        for line in (real_cache / "miner" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    serve_attempts = [j for j in journal_lines if j.get("trigger") == "serve"]
    assert len(serve_attempts) == 1, f"expected exactly one real attempt across 8 real ticks, got {len(serve_attempts)}"
    assert serve_attempts[0]["status"] == "failed"


def test_hp8_positive_control_the_cooldown_leg_is_genuinely_consulted(monkeypatch, tmp_path):
    """`HP8`'s positive control -- REWRITTEN per gate r2 N-3'. The r1
    version replaced `_mine_is_due` WHOLESALE with a hand-written stub
    that never called the real function at all -- **proven insensitive**:
    the gate's real inverse edit, deleting the cooldown leg from the
    SHIPPED `_mine_is_due`, left this test passing unchanged, because it
    never exercised the real code path. This control instead SPIES on
    `_recently_attempted` -- the real, extracted seam the real
    `_mine_is_due` genuinely calls -- so it goes RED the moment that
    call is ever removed or short-circuited around, which is exactly
    the shape the real N-14 mutation takes."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    real = serve._recently_attempted
    calls: list[bool] = []

    def spy(now):
        result = real(now)
        calls.append(result)
        return result

    monkeypatch.setattr(serve, "_recently_attempted", spy)

    now = _noon_today_epoch()
    monkeypatch.setattr(miner, "last_run_iso", lambda: None)  # never completed
    fresh_attempt_iso = datetime.fromtimestamp(now - 60, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(miner, "last_attempt_iso", lambda: fresh_attempt_iso)  # 60s ago, inside the window

    due = serve._mine_is_due(cache_dir, now)

    assert calls == [True], (
        "_mine_is_due must consult _recently_attempted exactly once, and "
        f"it must report True inside the cooldown window; got {calls}"
    )
    assert due is False, "a recent attempt must still block the tick from being due"


def test_hp8_a_landed_worker_follow_on_is_not_gated_by_a_due_predicate_at_all(monkeypatch, tmp_path):
    """`HP8`'s "same shape for a failing worker job" check, per gate r1
    B-1's instruction. Unlike the mine job, the worker follow-on is
    never polled against a due-predicate -- `_run_tick` only starts it
    ONCE, in-tick, immediately after a mine job that landed candidates
    (`HP4`). So a failing worker job cannot retry-storm on its own: the
    next chance it gets is the next time a mine job lands, which is
    ITSELF now cooldown-gated when mining fails (the test above) and,
    when mining succeeds, only happens again after `miner.last-run`
    passes tomorrow's target (or a poke) -- never on the next tick
    regardless of the worker outcome.

    Gate r2 B-1'/N-4': the r1 version of this test called
    `serve.request_poke()` before every tick to force each one past the
    due-predicate -- exactly the poke-forces-mine SHAPE gate r2's
    blocker fixed elsewhere, shipped here undocumented as a bypass. It
    is rewritten to force the due decision directly, by monkeypatching
    `_mine_is_due` itself (the ONLY thing this test needs to control is
    "assume the tick decided a mine was due" -- HOW it decided that is
    covered by the HP8/HP9 tests above), never through a poke. N-4' also
    fixed: the final assertion compares against the number of LANDED
    mines actually observed, not a hardcoded constant equal to however
    many ticks the loop happens to run."""
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: True)
    monkeypatch.setattr(miner, "run", lambda home, **kw: miner.MineResult(status="ok", landed=["c1"]))
    worker_calls = []

    def _failing_worker_run(home, **kw):
        worker_calls.append(1)
        return worker.RunResult(status="failed")

    monkeypatch.setattr(worker, "run", _failing_worker_run)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    home = Path("/irrelevant-home")
    base_t = _noon_today_epoch()

    mine_landings = 0
    for delta in (0, 30, 60):  # three ticks; `_mine_is_due` is forced
        # True on every one, no poke involved -- the property under
        # test is the WORKER side, not the mine due-predicate the tests
        # above already cover.
        records = serve._run_tick(home, cache_dir, now=base_t + delta, pid=os.getpid(), tick_secs=60.0)
        if "mine" in [r.name for r in records]:
            mine_landings += 1

    # One worker call per landed mine is CORRECT here: the property
    # under test is that nothing INSIDE the worker job's own failure
    # causes MORE attempts than mine landings did -- never a
    # retry-within-a-single-landing.
    assert len(worker_calls) == mine_landings
    assert mine_landings == 3, "the forced due-predicate should have let all three ticks land a mine"


# ===================================================================== #
# HP9 -- the poke is a hint, never a bypass (spec r7, gate r2 B-1')
# ===================================================================== #


def test_hp9_a_fresh_ledger_never_pokes_regardless_of_serve(tmp_path, monkeypatch):
    """`HP9`: "a poke never causes a mine attempt the watchdog would not
    have spawned." Gate r2 measured the r1 shape poking on EVERY verb
    invocation while `serve` was alive, even against a ledger mined
    0.0s ago -- because the serve-alive check in `maybe_kick` ran BEFORE
    the staleness check. Fixed shape: N verb invocations against a
    freshly-mined ledger, with `serve` alive, must return `"fresh"`
    every time and must never write a poke."""
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    monkeypatch.delenv("SELF_LEARN_MINER_AUTOKICK", raising=False)
    home = tmp_path / "nonexistent-home"
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdgcache"))
    cache_dir = worker.cache_dir()

    miner.miner_dir()
    (miner.miner_dir() / "miner.last-run").touch()  # mined "just now"

    serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)

    for _ in range(5):
        result = miner.maybe_kick(home)
        assert result == "fresh", f"expected 'fresh' (do nothing) on a just-mined ledger, got {result!r}"

    assert not (cache_dir / "serve.poke").is_file(), (
        "a fresh ledger must never write a poke, live serve or not -- "
        "gate r2's exact measured shape: mined 0.0s ago still got poked"
    )


def test_hp9_a_stale_ledger_pokes_once_attempts_once_then_cooldown_holds(tmp_path, monkeypatch):
    """`HP9`, the positive half: a genuinely >24h-stale ledger with
    `serve` alive DOES still poke -- exactly once -- and the poke
    produces exactly one real mine attempt (real refused-home
    `miner.run`, nothing stubbed), after which the cooldown holds: a
    further verb invocation reports `"cooling"`, never a second poke."""
    monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
    monkeypatch.delenv("SELF_LEARN_MINER_AUTOKICK", raising=False)
    home = tmp_path / "nonexistent-home"
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdgcache"))
    cache_dir = worker.cache_dir()

    last_run = miner.miner_dir() / "miner.last-run"
    last_run.touch()
    stale = time.time() - miner.KICK_AFTER_SECS - 3600  # 25h ago
    os.utime(last_run, (stale, stale))

    serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)

    result = miner.maybe_kick(home)
    assert result == "poked"
    assert (cache_dir / "serve.poke").is_file()

    records = serve._run_tick(home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)
    assert [r.name for r in records] == ["mine"], f"expected exactly one mine attempt from the poke, got {records}"
    assert (miner.miner_dir() / "miner.last-attempt").is_file()

    result2 = miner.maybe_kick(home)
    assert result2 == "cooling", f"the cooldown must hold after the one attempt, got {result2!r}"


def test_hp9_a_stale_poke_whose_conditions_have_since_resolved_does_not_force_a_mine(tmp_path, monkeypatch):
    """`HP9`, the race-condition half -- specifically exercises the
    `_run_tick` END of gate r2 B-1's fix (the `maybe_kick`-side tests
    above only exercise the OTHER end and cannot see a regression here:
    confirmed by mutation -- reverting `_run_tick` to the r1
    short-circuit shape left those two tests green). A poke was written
    while the ledger was genuinely stale, but by the time `_run_tick`
    consumes it the ledger has ALREADY been mined (e.g. a clock-driven
    tick landed first, or another process ran `mine` directly). The r1
    shape trusted a consumed poke unconditionally
    (`_consume_poke(...) or _mine_is_due(...)`) and would still force a
    mine; the fixed shape re-validates staleness via `_mine_is_due(...,
    ignore_schedule=True)` AT CONSUMPTION TIME, not merely at the moment
    the poke was requested."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    home = Path("/irrelevant-home")

    serve.request_poke(cache_dir)  # written while conditions warranted it

    now = time.time()
    # conditions have since resolved: last-run is now recent.
    monkeypatch.setattr(
        miner, "last_run_iso",
        lambda: datetime.fromtimestamp(now - 5, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    monkeypatch.setattr(miner, "last_attempt_iso", lambda: None)

    calls: list[int] = []
    monkeypatch.setattr(miner, "run", lambda home, **kw: calls.append(1) or miner.MineResult(status="ok"))

    records = serve._run_tick(home, cache_dir, now=now, pid=os.getpid(), tick_secs=60.0)

    assert records == [], f"a stale poke whose conditions have since resolved must not force a mine, got {records}"
    assert calls == [], "miner.run must not have been called"


# ===================================================================== #
# SUP -- supervision
# ===================================================================== #


def test_sup1_heartbeat_carries_tick_time_pid_and_next_job(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    before = time.time()
    serve.write_heartbeat(cache_dir, pid=4242, next_job="mine at 2026-08-28T03:41:00", tick_secs=60.0)
    after = time.time()
    record = serve.read_heartbeat(cache_dir)
    assert record is not None
    assert before <= record["ts"] <= after
    assert record["pid"] == 4242
    assert record["next_job"] == "mine at 2026-08-28T03:41:00"
    assert record["tick_secs"] == 60.0


def test_sup1_idle_tick_heartbeat_lands_in_cache_dir_never_the_ledger_home(monkeypatch, tmp_path):
    """`SUP1`/H-5 -- the IDLE-tick branch of `_run_tick` (no job due, no
    poke) writes its heartbeat too, and it must land in `cache_dir()`,
    never anywhere under the ledger `home`. Distinct from `run_one_job`'s
    OWN heartbeat write (covered by the MS1-seq tests) -- `_run_tick`'s
    idle path is a SEPARATE call site and needs its own proof, which is
    exactly the site a `home`/`cache_dir` mix-up would hide in."""
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # No poke, and force `_mine_is_due` false regardless of wall-clock
    # time -- this tick must take the idle branch.
    monkeypatch.setattr(serve, "_mine_is_due", lambda cache_dir, now: False)

    records = serve._run_tick(home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)
    assert records == []
    assert serve.read_heartbeat(cache_dir) is not None
    assert not any(home.rglob("*serve.heartbeat*")), (
        "the idle-tick heartbeat leaked into the ledger home -- H-5 violation"
    )


def test_a_stopped_mine_job_prints_the_refusal_on_its_own_line(
    monkeypatch, tmp_path, capsys
):
    """Gate r1 MAJOR-2 (§7.2a.7, REQUIRED): `run_forever` discarded
    `_run_tick`'s own return value, so a STOP froze the mine job every
    tick with no line naming the intent anywhere `serve` itself
    controls -- `miner.log()`'s own internal write is exactly what the
    gate ruled insufficient ("a refusal that reaches only the job
    record and the journal does not satisfy this section")."""
    monkeypatch.setattr(
        miner, "run",
        lambda home, **kw: miner.MineResult(
            status="stopped", stopped=["a755c088bcb4: cannot restore probe.txt"]
        ),
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    serve.request_poke(cache_dir)

    records = serve._run_tick(
        Path("/irrelevant-home"), cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    )

    assert [r.name for r in records] == ["mine"]  # never reaches the worker job
    err = capsys.readouterr().err
    assert (
        "serve: mine job refused — a755c088bcb4: cannot restore probe.txt; "
        "every ledger write refuses until it is cleared. Run 'self-learn "
        "reconcile --clear-intent a755c088bcb4' after inspecting the "
        "offender." in err
    )


def test_a_stopped_worker_job_prints_its_own_refusal_line_too(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        miner, "run", lambda home, **kw: miner.MineResult(status="ok", landed=["cand-1"])
    )
    monkeypatch.setattr(
        worker, "run",
        lambda home, **kw: worker.RunResult(
            status="stopped", stopped=["b866d199cdec: cannot restore other.md"]
        ),
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    serve.request_poke(cache_dir)

    records = serve._run_tick(
        Path("/irrelevant-home"), cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    )

    assert [r.name for r in records] == ["mine", "worker"]
    err = capsys.readouterr().err
    assert "serve: mine job refused" not in err  # the mine job itself landed fine
    assert (
        "serve: worker job refused — b866d199cdec: cannot restore other.md; "
        "every ledger write refuses until it is cleared. Run 'self-learn "
        "reconcile --clear-intent b866d199cdec' after inspecting the "
        "offender." in err
    )


def test_a_healthy_tick_prints_no_refusal_line(monkeypatch, tmp_path, capsys):
    """Positive control for the two assertions above: an ORDINARY
    landed tick (mine ok, worker ok) prints neither line."""
    monkeypatch.setattr(
        miner, "run", lambda home, **kw: miner.MineResult(status="ok", landed=["cand-1"])
    )
    monkeypatch.setattr(worker, "run", lambda home, **kw: worker.RunResult(status="ok"))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    serve.request_poke(cache_dir)

    serve._run_tick(
        Path("/irrelevant-home"), cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0
    )

    assert "refused" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "setup, expected_verdict",
    [
        ("unconfigured_no_heartbeat", "SKIP"),
        ("configured_no_heartbeat", "FAIL"),
        ("fresh_heartbeat", "PASS"),
        ("stale_heartbeat", "FAIL"),
    ],
)
def test_sup2_all_four_verdict_legs(tmp_path, monkeypatch, setup, expected_verdict):
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("SELF_LEARN_SERVE_UNIT_DIR", str(tmp_path / "unitdir"))
    cache_dir = worker.cache_dir()

    if setup == "configured_no_heartbeat":
        unit_dir = Path(tmp_path / "unitdir")
        unit_dir.mkdir(parents=True, exist_ok=True)
        (unit_dir / "self-learn-host.service").write_text("x")
    elif setup == "fresh_heartbeat":
        serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)
    elif setup == "stale_heartbeat":
        serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)
        path = serve.heartbeat_path(cache_dir)
        data = json.loads(path.read_text())
        data["ts"] = time.time() - 999
        path.write_text(json.dumps(data))

    rows = provider.preflight(home)
    row = next(r for r in rows if r.name == "serve")
    assert row.verdict == expected_verdict, row.detail


def test_sup3_the_alarm_is_genuinely_outside_the_daemon(tmp_path, monkeypatch):
    """`SUP3` -- start `serve`, KILL it (SIGKILL, no graceful shutdown
    chance to log anything), then observe `doctor`'s row read `FAIL` --
    not merely the absence of a `PASS`. A one-second tick makes the
    heartbeat go stale fast enough for a real (not simulated) test."""
    proc = _run_serve_subprocess(tmp_path, extra_env={"SELF_LEARN_SERVE_TICK_SECS": "1"})
    home = tmp_path / "home"
    xdg_cache_home = tmp_path / "cache"
    # Read `doctor`'s row from THIS (the test) process -- point its own
    # env at the SAME cache/home the subprocess was given.
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache_home))
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    self_learn_dir = xdg_cache_home / "self-learn"
    try:
        deadline = time.time() + 10
        while True:
            matches = list(self_learn_dir.glob("home-*")) if self_learn_dir.is_dir() else []
            if matches and serve.read_heartbeat(matches[0]) is not None:
                break
            if time.time() > deadline:
                pytest.fail("serve never wrote a heartbeat")
            time.sleep(0.1)

        proc.kill()  # SIGKILL -- no graceful path, no chance to self-report
        proc.wait(timeout=10)

        time.sleep(1.5)  # > 1 tick_secs, so the heartbeat is now stale

        rows = provider.preflight(home)
        row = next(r for r in rows if r.name == "serve")
        assert row.verdict == "FAIL", row.detail
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_sup4_timer_and_serve_both_enabled_reports_warn_not_fail(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    unit_dir = tmp_path / "unitdir"
    monkeypatch.setenv("SELF_LEARN_SERVE_UNIT_DIR", str(unit_dir))
    cache_dir = worker.cache_dir()
    serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)

    (unit_dir / "default.target.wants").mkdir(parents=True, exist_ok=True)
    (unit_dir / "default.target.wants" / "self-learn-host.service").write_text("x")
    (unit_dir / "timers.target.wants").mkdir(parents=True, exist_ok=True)
    (unit_dir / "timers.target.wants" / "self-learn-miner.timer").write_text("x")

    rows = provider.preflight(home)
    row = next(r for r in rows if r.name == "serve")
    assert row.verdict == "WARN", row.detail
    assert "belt-and-braces" in row.detail or "deliberate" in row.detail


def test_sup4_negative_control_both_enabled_must_not_read_as_fail(tmp_path, monkeypatch):
    """`N-13`'s own shape, observed directly: a verdict function that
    reported both-enabled as `FAIL` would be caught by the assertion
    above (`verdict == "WARN"`) -- this test additionally pins that a
    stale heartbeat with both enabled is STILL `FAIL` (the alarm must
    stay loud about a genuinely dead daemon regardless of the timer
    situation)."""
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    unit_dir = tmp_path / "unitdir"
    monkeypatch.setenv("SELF_LEARN_SERVE_UNIT_DIR", str(unit_dir))
    cache_dir = worker.cache_dir()
    serve.write_heartbeat(cache_dir, pid=os.getpid(), next_job="idle", tick_secs=60.0)
    path = serve.heartbeat_path(cache_dir)
    data = json.loads(path.read_text())
    data["ts"] = time.time() - 999
    path.write_text(json.dumps(data))

    (unit_dir / "default.target.wants").mkdir(parents=True, exist_ok=True)
    (unit_dir / "default.target.wants" / "self-learn-host.service").write_text("x")
    (unit_dir / "timers.target.wants").mkdir(parents=True, exist_ok=True)
    (unit_dir / "timers.target.wants" / "self-learn-miner.timer").write_text("x")

    rows = provider.preflight(home)
    row = next(r for r in rows if r.name == "serve")
    assert row.verdict == "FAIL", row.detail


# ===================================================================== #
# PORT -- portability
# ===================================================================== #


def test_port1_serve_starts_ticks_and_exits_cleanly_with_no_systemd_on_path(tmp_path):
    """`PORT1` -- executed, not asserted in prose: `--max-ticks 1` in an
    environment where `systemctl` is entirely absent from `PATH`."""
    import shutil

    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", str(home)], check=True)
    env = os.environ.copy()
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir()
    env["PATH"] = str(empty_bin)
    assert shutil.which("systemctl", path=env["PATH"]) is None
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["SELF_LEARN_HOME"] = str(home)
    env["SELF_LEARN_MINER"] = "0"
    env["SELF_LEARN_MINER_AUTOKICK"] = "0"

    result = subprocess.run(
        [sys.executable, "-m", "self_learn.cli", "serve", "--max-ticks", "1"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def _run_install_sh_with_logging_shim(
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
    install_sh: Path | None = None,
) -> tuple[subprocess.CompletedProcess, Path, Path]:
    """Runs `install.sh` (the real repo copy, or `install_sh` if given --
    `test_port2_negative_control_enabling_the_unit_is_caught` passes a
    mutated COPY through this same param, U-servehermetic, so its own
    sandboxing/env-clearing logic is not duplicated a second time)
    against a throwaway fake `$HOME`, with `systemctl`/`uv` PATH-shimmed
    (same technique `install-commands-test.sh` already uses for the
    miner/UI units) so nothing outside the fake home is ever touched.
    The `systemctl` shim additionally LOGS every invocation's argv (one
    line each) -- a plain `exit 0` no-op shim proves nothing about
    whether `enable` was ever attempted, only that its filesystem side
    effect (a real `.wants/` symlink) is absent; logging what was
    actually asked for is what makes `N-11` ("install.sh enables the
    unit") an observable mutation rather than a vacuous one."""
    repo_root = Path(__file__).resolve().parents[4]
    if install_sh is None:
        install_sh = repo_root / "install.sh"
    assert install_sh.is_file(), install_sh

    shims = tmp_path / "shims"
    shims.mkdir()
    systemctl_log = tmp_path / "systemctl.calls.log"
    (shims / "systemctl").write_text(
        f'#!/usr/bin/env bash\necho "$@" >> {systemctl_log}\nexit 0\n'
    )
    (shims / "systemctl").chmod(0o755)
    for tool in ("uv", "update-desktop-database"):
        shim = shims / tool
        shim.write_text("#!/usr/bin/env bash\nexit 0\n")
        shim.chmod(0o755)

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["PATH"] = f"{shims}:{env['PATH']}"
    # U-servehermetic: a caller exercising the new `XDG_CONFIG_HOME` leg
    # must be able to point it at a fixture dir without inheriting
    # whatever this TEST process's own `XDG_CONFIG_HOME` happens to be --
    # and this is not a theoretical concern: conftest.py's autouse
    # `_worker_test_defaults` sets `XDG_CONFIG_HOME` to a fresh `tmp_path`
    # subdir for EVERY test in this suite, this one included, so
    # `os.environ.copy()` above genuinely carries a real value here --
    # that is exactly WHY the `pop()` below matters: without it, a caller
    # wanting the unset-XDG_CONFIG_HOME leg would silently get this
    # unit's own fixture dir instead.
    if extra_env:
        env.update(extra_env)
    else:
        env.pop("XDG_CONFIG_HOME", None)

    result = subprocess.run(
        ["bash", str(install_sh)], env=env, capture_output=True, text=True, timeout=60
    )
    return result, fake_home, systemctl_log


# M-U fold r1 (Major 2, orchestrator-authorized edit to this one test node):
# a substring check for "enable" also matches "is-enabled" -- once
# install.sh's read-only is-enabled probe became unconditional, that
# substring collision would make PORT2's own positive control trip on a
# call that never touched enable/disable, AND make its negative control
# pass vacuously (the log always contains "enable" via "is-enabled" now,
# whether or not the injected real `enable` call is present). Checked by
# exact verb token instead: only "daemon-reload" and "is-enabled" may
# ever appear as the EXECUTED systemctl verb.
_PORT2_ALLOWED_SYSTEMCTL_VERBS = {"daemon-reload", "is-enabled"}

# M-U fold r2 (minor A): a logged call with no `--user` (or `--user` as
# its last token) must not be silently skipped -- an unparseable call
# would otherwise read exactly like a call that never happened. It emits
# this sentinel instead, which can never be in
# _PORT2_ALLOWED_SYSTEMCTL_VERBS, so it always lands in `disallowed`.
_PORT2_NO_USER_FLAG_SENTINEL = "<missing --user>"


def _port2_systemctl_verbs(calls: list[str]) -> list[str]:
    verbs = []
    for line in calls:
        tokens = line.split()
        verb = None
        if "--user" in tokens:
            idx = tokens.index("--user")
            if idx + 1 < len(tokens):
                verb = tokens[idx + 1]
        verbs.append(verb if verb is not None else _PORT2_NO_USER_FLAG_SENTINEL)
    return verbs


def test_port2_install_sh_links_the_host_unit_without_enabling_it(tmp_path):
    """`PORT2`."""
    repo_root = Path(__file__).resolve().parents[4]
    result, fake_home, systemctl_log = _run_install_sh_with_logging_shim(tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)

    unit_link = fake_home / ".config" / "systemd" / "user" / "self-learn-host.service"
    assert unit_link.is_symlink()
    assert unit_link.resolve() == (repo_root / "systemd" / "self-learn-host.service").resolve()

    out = result.stdout
    assert "enable --now self-learn-host.service" in out
    assert "self-learn serve" in out  # the non-systemd fallback line
    assert "self-learn-miner.timer should" in out  # the timer-overlap NOTE

    # PORT2/install.sh:25's house rule -- enable is a PRINTED line, never
    # RUN: `daemon-reload` is the only real `systemctl` invocation this
    # script makes for the host unit.
    calls = systemctl_log.read_text().splitlines() if systemctl_log.is_file() else []
    assert calls, "the systemctl shim was never invoked at all -- daemon-reload should have called it"
    verbs = _port2_systemctl_verbs(calls)
    assert verbs, calls
    disallowed = [v for v in verbs if v not in _PORT2_ALLOWED_SYSTEMCTL_VERBS]
    assert not disallowed, f"install.sh invoked disallowed systemctl verb(s) {disallowed}: {calls}"
    # M-U fold r1 (the probe is now UNCONDITIONAL, as pinned): this run
    # never passed --legacy-miner and never pre-seeded a miner-timer
    # symlink, so a stray is-enabled call here proves the probe fires
    # regardless -- not merely when a miner unit happens to be linked.
    assert "is-enabled" in verbs, calls


def test_port2_positive_control_xdg_config_home_governs_the_link_target(tmp_path):
    """`PORT2` extension, U-servehermetic (2026-08-27): `install.sh`'s
    `UNIT_DIR` must resolve the same way `serve.unit_dir()` does --
    `$XDG_CONFIG_HOME/systemd/user` when `XDG_CONFIG_HOME` is set, not
    unconditionally `$HOME/.config/systemd/user` -- so the installer and
    the doctor `serve` row that later checks the linked unit never
    disagree about where it lives. `XDG_CONFIG_HOME` is pointed at a
    tmp dir SEPARATE from `fake_home`; the link must land under IT, and
    `fake_home/.config` must stay untouched.

    MUTATION that turns this red: revert `install.sh`'s `UNIT_DIR` line
    back to `UNIT_DIR="$HOME/.config/systemd/user"` (dropping the
    `${XDG_CONFIG_HOME:-...}` fallback) -- the unit then links under
    `fake_home/.config` regardless of `XDG_CONFIG_HOME`, and both
    assertions below fail."""
    repo_root = Path(__file__).resolve().parents[4]
    xdg_config_home = tmp_path / "xdg-config"
    result, fake_home, _systemctl_log = _run_install_sh_with_logging_shim(
        tmp_path, extra_env={"XDG_CONFIG_HOME": str(xdg_config_home)}
    )
    assert result.returncode == 0, (result.stdout, result.stderr)

    unit_link = xdg_config_home / "systemd" / "user" / "self-learn-host.service"
    assert unit_link.is_symlink()
    assert unit_link.resolve() == (repo_root / "systemd" / "self-learn-host.service").resolve()

    stray_link = fake_home / ".config" / "systemd" / "user" / "self-learn-host.service"
    assert not stray_link.exists(), (
        "install.sh linked the unit under $HOME/.config even though "
        "XDG_CONFIG_HOME was set -- it ignored the override"
    )


def test_port2_negative_control_enabling_the_unit_is_caught(tmp_path):
    """`N-11`'s positive control, observed directly: mutate a COPY of
    `install.sh` so it actually runs `systemctl --user enable --now
    self-learn-host.service` instead of only printing the line, and
    confirm the check above (`not any("enable" in line for line in
    calls)`) would have caught it. Routed through `_run_install_sh_
    with_logging_shim` (U-servehermetic) rather than duplicating its
    shim/env setup a second time -- in particular its `XDG_CONFIG_HOME`
    clearing, so this test is not exposed to whatever this test SESSION's
    own conftest-set `XDG_CONFIG_HOME` happens to be either."""
    repo_root = Path(__file__).resolve().parents[4]
    real_install_sh = repo_root / "install.sh"
    mutated = tmp_path / "install-mutated.sh"
    text = real_install_sh.read_text(encoding="utf-8")

    # The mutated copy lives OUTSIDE the repo (tmp_path) -- hardcode REPO
    # so every relative `link "$P/..."` call still resolves against the
    # REAL repo tree; only the enable-line mutation below is under test.
    repo_anchor = 'REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"'
    assert repo_anchor in text
    text = text.replace(repo_anchor, f'REPO={str(repo_root)!r}', 1)

    anchor = 'say "  enable with: systemctl --user enable --now self-learn-host.service"'
    assert anchor in text, "install.sh's host-unit block shape changed -- update this mutation"
    text = text.replace(
        anchor,
        anchor + '\nrun "systemctl --user enable --now self-learn-host.service"',
        1,
    )
    mutated.write_text(text, encoding="utf-8")

    result, _fake_home, systemctl_log = _run_install_sh_with_logging_shim(
        tmp_path, install_sh=mutated
    )
    assert result.returncode == 0, (result.stdout, result.stderr)

    calls = systemctl_log.read_text().splitlines() if systemctl_log.is_file() else []
    verbs = _port2_systemctl_verbs(calls)
    assert "enable" in verbs, (
        f"the mutated install.sh should have actually invoked `enable` -- "
        f"this negative control itself is broken if it did not: {calls}"
    )
    assert "enable" not in _PORT2_ALLOWED_SYSTEMCTL_VERBS


# ===================================================================== #
# MS1-seq -- the criterion that GATES this phase (Sec 5.2a, Sec 7.1)
# ===================================================================== #

_FROZEN_STRUCT = time.strptime("2026-08-27 03:30:00", "%Y-%m-%d %H:%M:%S")


def _fake_session_job(surface: str, tag: str, log: list, *, pid: int):
    """Mirrors `invocation_sdk/backend.py::_drive`'s REAL sequencing
    (`new_run_id` -> `sweep_orphans` -> connect/write_sidecar -> drive ->
    `run_kill_ladder` -> `clear_sidecar` -> `write_event_log` ->
    `prune_event_logs`, in that order) against a `FakeSdkClient`,
    through the PRODUCTION CLI wrappers (`invocation_sdk.lifecycle`/
    `invocation_sdk.events` -- the unkeyed, single-sidecar-per-surface
    shape `C-1`/`F-2` preserve), not a synthetic shortcut."""

    def _run() -> str:
        run_id = events_mod.new_run_id()
        lifecycle_mod.sweep_orphans(surface, log.append)
        client = FakeSdkClient(pid=pid, messages=[f"{tag}-msg"])
        child_pid = lifecycle_mod.child_pid_of(client)
        lifecycle_mod.write_sidecar(surface, child_pid, "claude")
        events = sdk_events_mod.EventLog()
        events.add_tool_use("b1", "Read", {"note": tag})
        asyncio.run(lifecycle_mod.run_kill_ladder(client, child_pid, log.append))
        lifecycle_mod.clear_sidecar(surface)
        events_mod.write_event_log(surface, run_id, meta={"tag": tag}, events=events)
        events_mod.prune_event_logs(surface)
        return run_id

    return _run


def _run_ms1_seq_pair(monkeypatch, cache_dir, surfaces: tuple[str, str]):
    monkeypatch.setattr(sdk_events_mod.time, "gmtime", lambda *_: _FROZEN_STRUCT)
    pid = os.getpid()
    log: list[str] = []
    surface_a, surface_b = surfaces

    rec_a = serve.run_one_job(
        cache_dir, serve.Job("A", surface_a, _fake_session_job(surface_a, "A", log, pid=5001)), pid=pid, tick_secs=60.0
    )
    hb_after_a = serve.read_heartbeat(cache_dir)
    # item 3: sidecar cleaned BETWEEN jobs -- observed directly.
    assert lifecycle_mod.read_sidecar(surface_a) is None

    rec_b = serve.run_one_job(
        cache_dir, serve.Job("B", surface_b, _fake_session_job(surface_b, "B", log, pid=5002)), pid=pid, tick_secs=60.0
    )
    hb_after_b = serve.read_heartbeat(cache_dir)

    return rec_a, rec_b, hb_after_a, hb_after_b


def test_ms1_seq_two_sequential_jobs_same_surface_forced_same_second(monkeypatch):
    cache_dir = worker.cache_dir()
    rec_a, rec_b, hb_a, hb_b = _run_ms1_seq_pair(monkeypatch, cache_dir, ("worker", "worker"))

    run_id_a, run_id_b = rec_a.result, rec_b.result
    assert rec_a.ok and rec_b.ok
    assert run_id_a != run_id_b  # item 1: distinct run ids

    path_a = events_mod._event_log_path("worker", run_id_a)
    path_b = events_mod._event_log_path("worker", run_id_b)
    assert path_a.is_file() and path_b.is_file() and path_a != path_b  # item 2
    meta_a = json.loads(path_a.read_text().splitlines()[0])
    meta_b = json.loads(path_b.read_text().splitlines()[0])
    assert meta_a["tag"] == "A" and meta_b["tag"] == "B"

    assert lifecycle_mod.read_sidecar("worker") is None  # item 3, after job B too

    assert hb_b["ts"] > hb_a["ts"]  # item 4: heartbeat advanced


def test_ms1_seq_two_sequential_jobs_different_surfaces_forced_same_second(monkeypatch):
    cache_dir = worker.cache_dir()
    rec_a, rec_b, hb_a, hb_b = _run_ms1_seq_pair(monkeypatch, cache_dir, ("worker", "miner-reader"))

    run_id_a, run_id_b = rec_a.result, rec_b.result
    assert rec_a.ok and rec_b.ok
    assert run_id_a != run_id_b

    path_a = events_mod._event_log_path("worker", run_id_a)
    path_b = events_mod._event_log_path("miner-reader", run_id_b)
    assert path_a.is_file() and path_b.is_file() and path_a != path_b
    meta_a = json.loads(path_a.read_text().splitlines()[0])
    meta_b = json.loads(path_b.read_text().splitlines()[0])
    assert meta_a["tag"] == "A" and meta_b["tag"] == "B"

    assert hb_b["ts"] > hb_a["ts"]


def test_ms1_seq_positive_control_reverted_run_id_fix_collides_under_frozen_clock(monkeypatch):
    """NORMATIVE (gate N-2, strengthened per gate r1 N-5): with the
    run-id fix REVERTED to the pre-`U-engine` shape (`strftime(...) +
    "-" + str(pid)`, no per-process counter), leg 1's OWN
    distinct-run-id assertion (via `_run_ms1_seq_pair`, the SAME helper
    the main tests above call) must FAIL under a frozen clock and an
    unchanged pid. Gate r1 N-5: the earlier version of this control only
    called the reverted `new_run_id` twice in isolation, which proves
    new_run_id collides but never actually exercises MS1-seq's own test
    body against the reverted implementation -- the control now runs the
    SAME `_run_ms1_seq_pair` path the main tests do, so it observes the
    real collision, not an isolated stand-in for it."""
    monkeypatch.setattr(sdk_events_mod.time, "gmtime", lambda *_: _FROZEN_STRUCT)

    def _pre_fix_new_run_id() -> str:
        return time.strftime("%Y%m%dT%H%M%SZ", sdk_events_mod.time.gmtime()) + "-" + str(os.getpid())

    monkeypatch.setattr(events_mod, "new_run_id", _pre_fix_new_run_id)

    cache_dir = worker.cache_dir()
    rec_a, rec_b, _hb_a, _hb_b = _run_ms1_seq_pair(monkeypatch, cache_dir, ("worker", "worker"))

    assert rec_a.result == rec_b.result, (
        "expected leg 1's OWN distinct-run-id assertion "
        "(`assert run_id_a != run_id_b`) to be violated under the "
        "pre-fix run-id shape, observed through the real MS1-seq path -- "
        "if it did NOT collide here, either this shim no longer matches "
        "the pre-fix code, or MS1-seq's real path no longer reaches "
        "`new_run_id` the way this control assumes"
    )


# ===================================================================== #
# U1 -- scheduler safety (A13, A16, A19, A22, B10; S-68)
#
# The audit of 2026-09-19 found that NO test drove `_run_tick` against a
# real ledger. These do: `support.make_home` builds the doc-13 layout in
# a real git repo, and the cache is the one `worker.cache_dir(home)`
# resolves for that home -- the same pairing `run_forever` itself uses,
# so a test cannot pass by handing the predicate a cache directory the
# runner would never write into.
# ===================================================================== #


def _u1_home(tmp_path: Path, monkeypatch, *, steward_on=True, overseer_on=True) -> tuple[Path, Path]:
    """A real ledger plus ITS cache dir, both under `tmp_path`."""
    home = make_home(tmp_path)
    (home / "config.yaml").write_text(
        f"steward:\n  enabled: {'true' if steward_on else 'false'}\n"
        f"overseer:\n  enabled: {'true' if overseer_on else 'false'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return home, worker.cache_dir(home)


def _u1_journal_statuses(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("status"), str):
            out.append(row["status"])
    return out


def test_u1_a13_a_raising_due_check_holds_only_that_job(monkeypatch, tmp_path):
    """A13: a due predicate that raises does not escape `_run_tick`, does
    not stop the later jobs in the same tick, records a `due-check-error`
    HOLD line, and -- inside its cooldown -- is not re-entered on the next
    tick. Before U1 the raise propagated out of `_run_tick` and (through
    `run_forever`) ended the whole daemon."""
    home, cache_dir = _u1_home(tmp_path, monkeypatch)
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: False)
    seen = {"manifests": 0, "overseer": 0}

    def _wedged(actual):
        seen["manifests"] += 1
        raise gitops.GitOpsError("git ls-tree failed: wedged repository")

    def _overseer_predicate(*args, **kwargs):
        seen["overseer"] += 1
        return False

    monkeypatch.setattr(serve.steward, "committed_manifests", _wedged)
    monkeypatch.setattr(serve, "_overseer_is_due", _overseer_predicate)

    now = time.time()
    ran = serve._run_tick(home, cache_dir, now=now, pid=4321, tick_secs=60.0)

    # Positive controls first: the raising read really ran, and the later
    # job really was evaluated -- otherwise the counts below prove nothing.
    assert seen["manifests"] == 1
    assert seen["overseer"] == 1
    assert ran == []
    assert "due-check-error" in _u1_journal_statuses(steward.journal_path(home))
    assert "wedged repository" in serve._held_cause(cache_dir, "steward", now)

    serve._run_tick(home, cache_dir, now=now + 60.0, pid=4321, tick_secs=60.0)
    assert seen["manifests"] == 1, "the held predicate was re-entered inside its cooldown"
    assert seen["overseer"] == 2, "the hold on one job silenced another job's due check"

    # The heartbeat -- and so `doctor`'s serve row, which prints it -- names
    # the held job and its cause while the hold lasts.
    record = serve.read_heartbeat(cache_dir)
    assert "holding: steward" in record["next_job"]


def test_u1_a13_run_forever_survives_a_tick_that_raises(monkeypatch, tmp_path):
    """A13(b): an exception escaping `_run_tick` costs one tick, not the
    daemon. `max_ticks` behaviour is unchanged -- the second tick runs."""
    home, cache_dir = _u1_home(tmp_path, monkeypatch)
    ticks = {"n": 0}

    def _tick(*args, **kwargs):
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise RuntimeError("tick blew up")
        return []

    monkeypatch.setattr(serve, "_run_tick", _tick)
    assert serve.run_forever(home, cache_dir=cache_dir, tick_secs=0.01, max_ticks=2) == 0
    assert ticks["n"] == 2


def test_u1_a19_a_zero_call_steward_run_arms_the_cooldown(monkeypatch, tmp_path):
    """A19/A22: a run that takes ownership and then dies before its first
    model call still leaves an `attempt-start` line, so the scheduler is
    not due again until the cooldown expires. A run that HOLDS (disabled)
    leaves none and arms nothing."""
    home, cache_dir = _u1_home(tmp_path, monkeypatch)
    proposal_path = home / "proposals" / "lrn-deadbeef.yaml"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text("version: 1\n", encoding="utf-8")
    commit_all(home, "u1 proposal")
    entry = type(
        "Entry",
        (),
        # S-71: a queued record carries its status (the run records it as
        # the input's selection-time `record_status`).
        {"record": type("R", (), {"id": "lrn-deadbeef", "status": "pending"})(),
         "proposal_path": proposal_path},
    )()
    monkeypatch.setattr(steward, "_reconcile_runs", lambda actual: [])
    monkeypatch.setattr(steward, "_reconsider_proposals", lambda actual: ([], {}))
    monkeypatch.setattr(steward, "_eligible_proposals", lambda actual: [(entry, {})])

    def _no_prompt(*args, **kwargs):
        raise RuntimeError("no model in this test")

    monkeypatch.setattr(steward.steward_prompt, "assemble", _no_prompt)
    with pytest.raises(RuntimeError):
        steward.run(home)

    statuses = _u1_journal_statuses(steward.journal_path(home))
    assert "attempt-start" in statuses  # positive control: ownership was taken
    now = time.time()
    assert serve._steward_recently_attempted(cache_dir, now) is True
    assert serve._steward_is_due(home, cache_dir, now) is False
    assert (
        serve._steward_recently_attempted(cache_dir, now + miner.ATTEMPT_COOLDOWN_SECS + 1)
        is False
    )

    # The hold half: a disabled run journals, but never as an attempt.
    held_home, held_cache = _u1_home(tmp_path / "held", monkeypatch, steward_on=False)
    assert steward.run(held_home).status == "disabled"
    held_statuses = _u1_journal_statuses(steward.journal_path(held_home))
    assert held_statuses == ["disabled"]  # positive control: the run really ran
    assert serve._steward_recently_attempted(held_cache, time.time()) is False


def test_u1_s68_steward_cooldown_is_tested_before_any_git_read(monkeypatch, tmp_path):
    """S-68's ordering rule. Before U1 `_steward_is_due` walked committed
    manifests FIRST, so a wedged git read was re-entered on every tick
    with no cooldown able to stop it."""
    home, cache_dir = _u1_home(tmp_path, monkeypatch)
    seen = {"n": 0}

    def _counting(actual):
        seen["n"] += 1
        return []

    monkeypatch.setattr(serve.steward, "committed_manifests", _counting)
    monkeypatch.setattr(serve.steward, "_reconsider_proposals", lambda actual: ([], {}))
    monkeypatch.setattr(serve, "_eligible_proposal_paths", lambda actual: [])
    journal = steward.journal_path(home)
    now = time.time()

    # Positive control: an OLD attempt does not suppress the git read.
    stale = datetime.fromtimestamp(now - miner.ATTEMPT_COOLDOWN_SECS - 10).astimezone().isoformat()
    journal.write_text(json.dumps({"ts": stale, "status": "attempt-start"}) + "\n", encoding="utf-8")
    assert serve._steward_is_due(home, cache_dir, now) is False  # nothing eligible
    assert seen["n"] == 1

    fresh = datetime.fromtimestamp(now - 5).astimezone().isoformat()
    journal.write_text(json.dumps({"ts": fresh, "status": "attempt-start"}) + "\n", encoding="utf-8")
    assert serve._steward_is_due(home, cache_dir, now) is False
    assert seen["n"] == 1, "a git read ran ahead of the cache cooldown test"


def test_u1_s68_unparseable_and_future_attempt_stamps_read_as_now(monkeypatch, tmp_path):
    """S-68: an unparseable stamp used to parse to epoch 0 (due on every
    tick) and a future stamp made a job due never."""
    assert serve._attempt_epoch("not-a-timestamp", 1000.0) == 1000.0
    assert serve._attempt_epoch("2099-01-01T00:00:00+00:00", 1000.0) == 1000.0
    assert serve._attempt_epoch("1970-01-01T00:00:10+00:00", 1000.0) == 10.0

    home, cache_dir = _u1_home(tmp_path, monkeypatch)
    clear = type("IntentState", (), {"stopped": []})()
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: clear)
    monkeypatch.setattr(serve.steward, "committed_manifests", lambda actual: [
        {"run_id": "run-pending", "status": "unfinished", "last_attempt_at": "banana"}
    ])
    monkeypatch.setattr(serve.steward, "_reconsider_proposals", lambda actual: ([], {}))
    monkeypatch.setattr(serve, "_eligible_proposal_paths", lambda actual: [])
    now = time.time()
    assert serve._steward_is_due(home, cache_dir, now) is False

    # The heartbeat preview reads its stamp through the same rule, so it
    # cannot promise a steward run in 2099.
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: "2099-01-01T00:00:00+00:00")
    monkeypatch.setattr(serve, "_today_mine_target", lambda cache, when: when + 60)
    preview = serve._describe_next(home, cache_dir, now)
    steward_at = preview.split("steward at ", 1)[1].split(" ", 1)[0]
    assert datetime.fromisoformat(steward_at).timestamp() < now + 100000.0


def _u1_sunday(year: int, month: int, day: int) -> float:
    """A local-time Sunday 04:15 boundary, built the way the shipped
    predicate builds it -- so this test says the same thing in every
    timezone the machine might be in."""
    return time.mktime((year, month, day, serve.OVERSEER_HOUR, serve.OVERSEER_MINUTE, 0, 0, 0, -1))


def test_u1_a16_overseer_catch_up_needs_a_previous_run(monkeypatch, tmp_path):
    """A16: after a Sunday the machine was down, the missed week runs on
    the next tick whatever the weekday -- but only once the overseer has
    run before. Never-run stays on the calendar rule, so flipping the
    switch on midweek cannot start an unattended first run."""
    home, cache_dir = _u1_home(tmp_path, monkeypatch)
    clear = type("IntentState", (), {"stopped": []})()
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: clear)
    monkeypatch.setattr(overseer_package, "has_unfinished_work", lambda actual: False)
    monkeypatch.setattr(serve, "_overseer_recently_attempted", lambda cache, now: False)
    monkeypatch.setattr(overseer_run, "_committed_overseer_manifests", lambda actual: [])

    boundary = _u1_sunday(2026, 9, 13)  # Sunday
    monday = boundary + 30 * 60 * 60  # Monday ~10:15 local
    coverage = home / "overseer" / "coverage.yaml"
    coverage.parent.mkdir(parents=True, exist_ok=True)

    # Never run: Monday is NOT due, the calendar Sunday still is.
    assert overseer_run.previous_run_exists(home) is False
    assert serve._overseer_is_due(home, cache_dir, monday) is False
    assert serve._overseer_is_due(home, cache_dir, boundary + 1) is True

    # Ran last week, missed this Sunday: due on Monday (the catch-up).
    last_week = datetime.fromtimestamp(boundary - 6 * 24 * 60 * 60).astimezone().isoformat()
    coverage.write_text(f"last_run_at: '{last_week}'\n", encoding="utf-8")
    assert overseer_run.previous_run_exists(home) is True
    assert overseer_run.week_done(home, overseer_run.week_boundary(monday)) is False
    assert serve._overseer_is_due(home, cache_dir, monday) is True

    # Already ran this week: not due again, whatever the weekday.
    this_week = datetime.fromtimestamp(boundary + 60).astimezone().isoformat()
    coverage.write_text(f"last_run_at: '{this_week}'\n", encoding="utf-8")
    assert overseer_run.week_done(home, overseer_run.week_boundary(monday)) is True
    assert serve._overseer_is_due(home, cache_dir, monday) is False

    # ... and the boundary itself is the most recent Sunday 04:15 at or
    # before `now`, whatever weekday `now` is.
    assert overseer_run.week_boundary(monday) == boundary
    assert overseer_run.week_boundary(boundary + 1) == boundary
    assert overseer_run.week_boundary(boundary - 1) == boundary - 7 * 24 * 60 * 60


def test_u1_b10_same_week_guard_holds_and_writes_nothing(monkeypatch, tmp_path):
    """B10: the guard lives in the RUNNER, so the `serve` job, a typed
    `overseer run` and the (unenabled) timer cannot between them run one
    week twice. A held run touches neither HEAD nor the working tree."""
    home, _cache_dir = _u1_home(tmp_path, monkeypatch)
    coverage = home / "overseer" / "coverage.yaml"
    coverage.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    coverage.write_text(
        f"last_run_at: '{datetime.fromtimestamp(now - 60).astimezone().isoformat()}'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(overseer_run, "_committed_overseer_manifests", lambda actual: [])

    # Positive control FIRST: the precondition this test rests on.
    assert overseer_run.week_done(home, overseer_run.week_boundary(now)) is True

    head_before = gitops.head_sha(home)
    tree_before = gitops._git(home, "status", "--porcelain").stdout

    result = overseer_run.run(home)

    assert result.status == "held-week-done"
    assert result.code == 0
    assert gitops.head_sha(home) == head_before
    assert gitops._git(home, "status", "--porcelain").stdout == tree_before
    assert "held-week-done" in _u1_journal_statuses(overseer_run.journal_path(home))


def test_u2_a_hold_that_cannot_be_recorded_still_only_costs_one_job(monkeypatch, tmp_path):
    """U2's nit on U1: `_hold_due_check` is itself I/O (a cache write, a
    journal append, a notification) and can raise. That raise used to
    escape `_due_or_hold` and skip every REMAINING job of the tick --
    A13's whole-daemon blast radius, one level in. A failure to RECORD a
    hold still means "not due", and the later jobs still run."""
    home, cache_dir = _u1_home(tmp_path, monkeypatch)
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: False)
    seen = {"overseer": 0}

    def _overseer_predicate(*args, **kwargs):
        seen["overseer"] += 1
        return False

    monkeypatch.setattr(
        serve.steward, "committed_manifests",
        lambda actual: (_ for _ in ()).throw(gitops.GitOpsError("wedged repository")),
    )
    monkeypatch.setattr(serve, "_overseer_is_due", _overseer_predicate)
    monkeypatch.setattr(
        serve, "_write_holds",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only cache")),
    )

    now = time.time()
    ran = serve._run_tick(home, cache_dir, now=now, pid=4321, tick_secs=60.0)

    assert ran == []
    # positive control: the later job in the SAME tick was still evaluated
    assert seen["overseer"] == 1
    # and no hold was recorded, so the next tick re-enters the predicate
    assert serve._held_cause(cache_dir, "steward", now) is None


def test_a_cap_closed_week_is_not_due_all_sunday_for_a_never_run_overseer(
    tmp_path, monkeypatch
):
    """S-68 / fold r1 item 6: a DONE week is never due, on the calendar
    branch too.

    An overseer that has never completed a run stays on the plain calendar
    rule, because `previous_run_exists` is false — so the catch-up branch
    that consults `week_done` is skipped entirely. Once such a week was
    closed at `runs.attempt_cap`, the calendar branch still answered "due"
    for the rest of Sunday; `run` then replied `held-week-done`, which is a
    HOLD and therefore arms no cooldown, so the job was re-entered on every
    60-second tick until Monday.

    A REAL scratch ledger and REAL `overseer_run.run` calls: the failures
    are transport failures of the first model call, the shape that leaves no
    run record at all and counts through its committed failure note. The
    cache-side cooldown is stubbed off throughout so this asserts the
    git-side branch and nothing else.
    """
    home = make_home(tmp_path)
    (home / "config.yaml").write_text("overseer:\n  enabled: true\n", encoding="utf-8")
    commit_all(home, "enable overseer")
    cache_dir = worker.cache_dir(home)
    monkeypatch.setattr(serve, "_overseer_recently_attempted", lambda actual, now: False)
    monkeypatch.setattr(overseer_run.notify, "send", lambda *a, **k: None)
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: Outcome(
            ok=False, rc=1, stdout="",
            detail="API Error: 400 this build does not support the selected model",
            failure="exit",
        ),
    )
    # Sunday 04:25 of the week the failure notes will belong to.
    sunday = overseer_run.week_boundary(time.time()) + 600
    assert time.localtime(sunday).tm_wday == 6

    # positive control: with the week not yet done, the calendar branch is
    # due — and stays due after the first two failed attempts.
    assert serve._overseer_is_due(home, cache_dir, sunday) is True
    for expected in (1, 2):
        assert overseer_run.run(home, no_push=True).status == "refused"
        assert overseer_run.week_attempts(home, overseer_run.week_key(sunday)) == expected
        assert overseer_run.previous_run_exists(home) is False
        assert serve._overseer_is_due(home, cache_dir, sunday) is True

    assert overseer_run.run(home, no_push=True).status == "refused"

    week = overseer_run.week_key(sunday)
    assert overseer_run.week_attempts(home, week) == 3
    assert overseer_run.week_closed(home, week)
    assert overseer_run.previous_run_exists(home) is False
    assert serve._overseer_is_due(home, cache_dir, sunday) is False
    # ...and it stays not-due for the rest of the day, which is the loop.
    assert serve._overseer_is_due(home, cache_dir, sunday + 6 * 3600) is False
