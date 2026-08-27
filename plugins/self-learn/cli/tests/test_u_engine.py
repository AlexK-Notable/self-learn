"""U-engine Phase 1A -- the shared `sdksession` library's own criteria.

Spec: `docs/specs/self-learn/drafts/u-engine-shared-sdk-core-spec.md`
Sec 6 (Phase 1 criteria). This file carries the CLI-side half of PIN
(PIN1/PIN2/PIN4), all of LIB, MS, LAD1/LAD2, BND1/BND3/BND4, and POL2 --
everything the 1A files-may-touch table (Sec 9.1) assigns to
`cli/tests/test_u_engine.py`. Sec 9.2 extends this file in Phase 1B with
LIB4 and POL1/POL3.

Every message pin below hardcodes its expected string INDEPENDENTLY of
`lifecycle.CLI_SHUTDOWN_MESSAGES` -- comparing against that table itself
would be the exact tautology `PIN2` forbids (a pin that asserts a
`messages()` table against a literal copy of itself proves nothing).
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from self_learn import worker
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import charter as charter_mod
from self_learn.invocation_sdk import lifecycle as lifecycle_mod
from self_learn.sdksession import children as sdk_children
from self_learn.sdksession import events as sdk_events
from self_learn.sdksession import policy as sdk_policy
from self_learn.sdksession import result as sdk_result
from self_learn.sdksession import session as sdk_session
from self_learn.sdksession import teardown as sdk_teardown
from self_learn.sdksession.fake import FakeSdkClient

from test_invocation_sdk import (  # noqa: F401 -- fixtures/helpers resolved by name
    _containment,
    _run,
    _spec,
    sdk_cli_path,
)

_SDKSESSION_DIR = Path(sdk_children.__file__).resolve().parent
_CLI_PKG_DIR = Path(backend_mod.__file__).resolve().parent
_CLI_SRC_ROOT = _CLI_PKG_DIR.parent


# ===================================================================== #
# PIN -- the unit's real product (CLI half). Every message is hardcoded
# here, independently of `lifecycle.CLI_SHUTDOWN_MESSAGES` (`PIN2`'s
# anti-tautology rule).
# ===================================================================== #

_CLI_DISCONNECT_TIMEOUT = (
    "run: sdk backend: disconnect() still running at the kill "
    "bound — caller released; SDK subprocess escalation "
    "continues in the background"
)
_CLI_DISCONNECT_RAISED = "run: sdk backend: disconnect() raised: boom"
_CLI_ABANDONED_CANCELLED = "run: sdk backend: abandoned disconnect() was cancelled"
_CLI_ABANDONED_FINISHED = "run: sdk backend: abandoned disconnect() finished with: boom2"
_CLI_ABANDONED_COMPLETED = "run: sdk backend: abandoned disconnect() completed"
_CLI_CHILD_PID_UNRESOLVED = "run: sdk backend could not resolve the child pid"
_CLI_ORPHAN_MALFORMED = "run: sdk backend: orphan sweep for worker declined (malformed sidecar)"
_CLI_ORPHAN_NO_LIVE_PROCESS = "run: sdk backend: orphan sweep for worker found no live process at pid {pid}"
_CLI_ORPHAN_UNCORROBORATED = "run: sdk backend: orphan sweep for worker could not corroborate pid {pid}"
_CLI_ORPHAN_CMDLINE_MISMATCH = "run: sdk backend: orphan sweep for worker declined (pid {pid} cmdline mismatch)"
_CLI_ORPHAN_NOT_STALE = "run: sdk backend: orphan sweep for worker declined (pid {pid} not stale)"
_CLI_ORPHAN_KILLED = "run: sdk backend: orphan sweep for worker killed stale pid {pid}"
_CLI_MAX_TURNS_UNSUPPORTED = "run: sdk backend could not apply max_turns on this claude-agent-sdk version"
_CLI_MAX_BUDGET_UNSUPPORTED = "run: sdk backend could not apply max_budget_usd on this claude-agent-sdk version"


def _run_ladder_and_collect(monkeypatch, *, kill_secs=0.05, client) -> list[str]:
    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", kill_secs)
    monkeypatch.setattr(lifecycle_mod, "INTERRUPT_GRACE_SECS", 0.05)
    logs: list[str] = []
    asyncio.run(lifecycle_mod.run_kill_ladder(client, None, logs.append))
    return logs


def test_pin1_pin2_cli_ladder_timeout_and_raised_messages(monkeypatch):
    """`PIN1`/`PIN2` -- the two ladder-body lines (disconnect() timing
    out at the kill bound, disconnect() raising outright), driven
    through the REAL `lifecycle.run_kill_ladder`. Both legs and the
    abandoned-task drain run inside ONE `asyncio.run` call: a task left
    pending when `asyncio.run` returns gets forcibly cancelled by its
    OWN cleanup, which would otherwise plant a spurious third message
    ("...was cancelled") this test never asked for."""
    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 0.05)
    monkeypatch.setattr(lifecycle_mod, "INTERRUPT_GRACE_SECS", 0.05)

    async def _drive():
        timeout_client = FakeSdkClient(hang_disconnect_secs=3600)
        logs: list[str] = []
        await lifecycle_mod.run_kill_ladder(timeout_client, None, logs.append)
        assert logs == [_CLI_DISCONNECT_TIMEOUT], logs
        for task in set(lifecycle_mod._ABANDONED_DISCONNECTS):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        raising_client = FakeSdkClient(disconnect_raises=RuntimeError("boom"))
        logs2: list[str] = []
        await lifecycle_mod.run_kill_ladder(raising_client, None, logs2.append)
        assert logs2 == [_CLI_DISCONNECT_RAISED], logs2

    asyncio.run(_drive())


def test_pin1_pin2_cli_abandoned_disconnect_all_three_outcomes(monkeypatch):
    """`PIN1`/`PIN2` -- the three `_log_abandoned_disconnect` lines
    (cancelled / finished-with-exception / completed), driven through
    the REAL ladder's abandoned-task tracking. Each leg's drive AND its
    wait-for-completion run inside the SAME `asyncio.run` call -- a
    `Task` is bound to the loop that created it, and `asyncio.run`
    forcibly cancels anything still pending when it returns."""
    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 0.02)
    monkeypatch.setattr(lifecycle_mod, "INTERRUPT_GRACE_SECS", 0.02)

    async def _leg_and_wait(client, *, cancel: bool) -> list[str]:
        logs: list[str] = []
        before = set(lifecycle_mod._ABANDONED_DISCONNECTS)
        await lifecycle_mod.run_kill_ladder(client, None, logs.append)
        added = lifecycle_mod._ABANDONED_DISCONNECTS - before
        assert len(added) == 1, added
        task = next(iter(added))
        if cancel:
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except BaseException:  # noqa: BLE001 - the task's own outcome (incl. cancellation), retrieved via the done-callback below
            pass
        await asyncio.sleep(0)  # done-callbacks are scheduled via call_soon
        return logs

    # completed cleanly, after the kill bound.
    completed_client = FakeSdkClient(hang_disconnect_secs=0.08)
    logs_c = asyncio.run(_leg_and_wait(completed_client, cancel=False))
    assert logs_c == [_CLI_DISCONNECT_TIMEOUT, _CLI_ABANDONED_COMPLETED], logs_c

    # raised, after the kill bound.
    class _RaisesLateClient(FakeSdkClient):
        async def disconnect(self):
            self.disconnect_calls += 1
            await asyncio.sleep(0.08)
            raise RuntimeError("boom2")

    finished_client = _RaisesLateClient()
    logs_f = asyncio.run(_leg_and_wait(finished_client, cancel=False))
    assert logs_f == [_CLI_DISCONNECT_TIMEOUT, _CLI_ABANDONED_FINISHED], logs_f

    # cancelled explicitly.
    cancel_client = FakeSdkClient(hang_disconnect_secs=3600)
    logs_x = asyncio.run(_leg_and_wait(cancel_client, cancel=True))
    assert logs_x == [_CLI_DISCONNECT_TIMEOUT, _CLI_ABANDONED_CANCELLED], logs_x


def test_pin1_pin2_cli_orphan_sweep_six_messages(tmp_path, monkeypatch):
    """`PIN1`/`PIN2` -- all six orphan-sweep lines, driven through the
    REAL `lifecycle.sweep_orphans`, one sidecar shape per line."""
    monkeypatch.setenv("SELF_LEARN_HOME", str(tmp_path / "pin-orphan-home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "pin-orphan-xdg"))
    cache = worker.cache_dir()
    sidecar = cache / "worker.sdk-child.pid"

    def _sweep() -> list[str]:
        logs: list[str] = []
        lifecycle_mod.sweep_orphans("worker", logs.append)
        return logs

    # 1. malformed -- missing required keys.
    sidecar.write_text(json.dumps({"pid": "not-an-int"}), encoding="utf-8")
    assert _sweep() == [_CLI_ORPHAN_MALFORMED]
    assert not sidecar.exists()

    # 2. no live process.
    dead_pid = 999_999_999  # astronomically unlikely to be alive
    sidecar.write_text(
        json.dumps({"pid": dead_pid, "started_at": 0.0, "cli": "claude"}), encoding="utf-8"
    )
    logs2 = _sweep()
    assert logs2 == [_CLI_ORPHAN_NO_LIVE_PROCESS.format(pid=dead_pid)], logs2

    # 3. cannot corroborate -- `pid_alive` reports the pid as alive
    # (forced True via `worker._pid_alive`, looked up at CALL time --
    # `lifecycle.sweep_orphans`'s own docstring documents exactly this
    # seam: "worker.cache_dir() and worker._pid_alive are both looked
    # up at CALL time"), but the pid names no real process -- it is a
    # real child this test spawned and has already reaped -- so the
    # REAL `/proc/<pid>/cmdline` read genuinely raises `OSError`
    # regardless of this host's privilege level or `hidepid` mount
    # option (gate r1 B-1: the old "am I root" probe via
    # `/proc/1/cmdline` readability was wrong on any account -- that
    # file is world-readable for an ordinary user too on a default
    # Linux install, so the skip fired unconditionally here and legs
    # 4-6 died with it, four of the 24 pinned messages asserted
    # nowhere). Unconditional: no skip, on any host.
    reaped = subprocess.Popen(["true"])
    reaped.wait()
    phantom_pid = reaped.pid
    with monkeypatch.context() as mp:
        mp.setattr(lifecycle_mod.worker, "_pid_alive", lambda pid: True)
        sidecar.write_text(
            json.dumps({"pid": phantom_pid, "started_at": 0.0, "cli": "claude"}), encoding="utf-8"
        )
        logs3 = _sweep()
    assert logs3 == [_CLI_ORPHAN_UNCORROBORATED.format(pid=phantom_pid)], logs3

    # 4. cmdline mismatch -- this test process is alive but is not named
    # "claude" and its cli basename does not match either.
    my_pid = os.getpid()
    sidecar.write_text(
        json.dumps({"pid": my_pid, "started_at": 0.0, "cli": "not-claude-either"}), encoding="utf-8"
    )
    logs4 = _sweep()
    assert logs4 == [_CLI_ORPHAN_CMDLINE_MISMATCH.format(pid=my_pid)], logs4

    # 5. not stale -- matches "claude" via the recorded `cli` basename,
    # but `started_at` is in the far future (never stale).
    sidecar.write_text(
        json.dumps({"pid": my_pid, "started_at": time.time() + 3600, "cli": "python3"}),
        encoding="utf-8",
    )
    # `cli` basename must match `os.path.basename(cmdline[0])`; this
    # test process's argv[0] is a python interpreter, so use it exactly.
    import shutil as _shutil

    self_cmdline = Path(f"/proc/{my_pid}/cmdline").read_bytes().split(b"\x00")[0].decode()
    sidecar.write_text(
        json.dumps(
            {"pid": my_pid, "started_at": time.time() + 3600, "cli": os.path.basename(self_cmdline)}
        ),
        encoding="utf-8",
    )
    logs5 = _sweep()
    assert logs5 == [_CLI_ORPHAN_NOT_STALE.format(pid=my_pid)], logs5
    del _shutil

    # 6. killed -- a real, short-lived child process named "claude" via
    # a copy of `/bin/sleep`, stale (started_at in the past).
    real_sleep = subprocess.run(["which", "sleep"], capture_output=True, text=True).stdout.strip()
    claude_bin = tmp_path / "claude"
    import shutil as shutil2

    shutil2.copy(real_sleep, claude_bin)
    claude_bin.chmod(0o755)
    proc = subprocess.Popen([str(claude_bin), "60"])
    try:
        sidecar.write_text(
            json.dumps({"pid": proc.pid, "started_at": 0.0, "cli": str(claude_bin)}),
            encoding="utf-8",
        )
        logs6 = _sweep()
        assert logs6 == [_CLI_ORPHAN_KILLED.format(pid=proc.pid)], logs6
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_pin1_pin2_cli_child_pid_unresolved(tmp_path, sdk_cli_path, monkeypatch):
    """`PIN1`/`PIN2` -- driven through a REAL `_run(_spec(...))` session
    with `child_pid_of` forced to return `None` (mirrors `test_kl6`'s
    own technique, independently pinned here)."""
    home = tmp_path / "pin-childpid-home"
    home.mkdir()
    monkeypatch.setattr(lifecycle_mod, "child_pid_of", lambda client: None)
    logs: list[str] = []
    outcome = _run(_spec("worker", home=home, prompt="ok_text", log=logs.append))
    assert outcome.ok is True
    matching = [line for line in logs if line == _CLI_CHILD_PID_UNRESOLVED]
    assert len(matching) == 1, logs


def test_pin1_pin2_cli_option_capability_two_messages(tmp_path, monkeypatch):
    """`PIN1`/`PIN2` -- the two `options_kwargs` feature-detection
    lines, driven through the REAL `options_kwargs`, `_dataclass_fields`
    stubbed to a `ClaudeAgentOptions` shape missing both `max_turns` and
    `max_budget_usd` (mirrors `test_ou4`'s own technique)."""
    home = tmp_path / "pin-optcap-home"
    home.mkdir()

    class _StubField:
        def __init__(self, name):
            self.name = name

    logs: list[str] = []
    spec = _spec("worker", home=home, prompt="ok_text", log=logs.append)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(backend_mod, "_dataclass_fields", lambda _cls: [_StubField("cwd"), _StubField("model")])
        backend_mod.options_kwargs(spec)
    assert logs == [_CLI_MAX_TURNS_UNSUPPORTED, _CLI_MAX_BUDGET_UNSUPPORTED], logs


def test_pin4_positive_control_the_ui_prefix_would_fail_this_pin(monkeypatch):
    """`PIN4` -- substituting the OTHER engine's message table must make
    the pin suite FAIL, observed. A UI-flavoured table (the "pane
    engine close: ..." prefix, §2.8) wired into the CLI's ladder makes
    `test_pin1_pin2_cli_ladder_timeout_and_raised_messages`'s own
    assertion fail."""
    ui_flavoured = sdk_policy.ShutdownMessages(
        disconnect_timeout=(
            "pane engine close: disconnect() still running at the kill "
            "bound — caller released; SDK subprocess escalation "
            "continues in the background"
        ),
        disconnect_raised="pane engine close: disconnect() raised: {exc}",
        abandoned_cancelled="pane engine close: abandoned disconnect() was cancelled",
        abandoned_finished="pane engine close: abandoned disconnect() finished with: {exc}",
        abandoned_completed="pane engine close: abandoned disconnect() completed",
    )
    monkeypatch.setattr(lifecycle_mod, "CLI_SHUTDOWN_MESSAGES", ui_flavoured)
    client = FakeSdkClient(disconnect_raises=RuntimeError("boom"))
    logs = _run_ladder_and_collect(monkeypatch, client=client)
    assert logs != [_CLI_DISCONNECT_RAISED], "PIN4 did not detect the swapped table"
    with pytest.raises(AssertionError):
        assert logs == [_CLI_DISCONNECT_RAISED], logs


# ===================================================================== #
# LIB -- the library
# ===================================================================== #

_LIB1_ALLOWED_TOP_LEVEL = frozenset(sys.stdlib_module_names) | {"__future__"}


def test_lib1_import_set_is_stdlib_only_no_upward_or_sdk_imports():
    violations = []
    for path in sorted(_SDKSESSION_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in _LIB1_ALLOWED_TOP_LEVEL:
                        violations.append((path.name, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    continue  # `from .module import x` -- same-package
                                 # (sdksession's own submodules), fine.
                                 # BUG FOUND BY MUTATION SELF-CHECK (M-17):
                                 # the original form of this clause was
                                 # `if node.level and node.level > 0:
                                 # continue`, which treated EVERY relative
                                 # import as fine regardless of level --
                                 # `from .. import worker` (level=2, the
                                 # exact shape an upward import into a
                                 # sibling package takes from inside this
                                 # one-level-deep package) slipped through
                                 # unnoticed. Fixed to single out level==1
                                 # and treat level>=1... (see below) as an
                                 # escape from the package, recorded like
                                 # any other violation.
                if node.level and node.level > 1:
                    for alias in node.names:
                        violations.append(
                            (path.name, node.lineno, f"{'.' * node.level}{node.module or ''}.{alias.name}")
                        )
                    continue
                mod = node.module or ""
                top = mod.split(".")[0] if mod else ""
                if top and top not in _LIB1_ALLOWED_TOP_LEVEL:
                    violations.append((path.name, node.lineno, mod))
    assert violations == [], violations


def test_lib2_no_os_environ_or_getenv_read_anywhere_in_the_package():
    violations = []
    for path in sorted(_SDKSESSION_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                if isinstance(node.value, ast.Name) and node.value.id == "os":
                    violations.append((path.name, node.lineno, "os.environ"))
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr == "getenv":
                    violations.append((path.name, node.lineno, "getenv"))
    assert violations == [], violations


def test_lib3_full_session_driveable_with_claude_agent_sdk_absent(tmp_path):
    """`LIB3` -- a fresh subprocess that poisons `claude_agent_sdk`
    BEFORE importing `self_learn.sdksession`, then drives a full
    connect/query/drive/teardown cycle against `FakeSdkClient`. Proves
    the library is SDK-free in fact (import-time AND at every call it
    makes), not only in its static import list (`LIB1`)."""
    src_root = str(_CLI_SRC_ROOT)
    script = f"""
import sys
sys.path.insert(0, {src_root!r})
sys.modules['claude_agent_sdk'] = None
import self_learn.sdksession as sdksession
import asyncio

async def main():
    client = sdksession.FakeSdkClient(pid=4321, messages=['a', 'b', 'c'])
    session = sdksession.SdkSession(client)
    await session.connect()
    await session.query('hi')
    got = [m async for m in session.drive()]
    assert got == ['a', 'b', 'c'], got
    assert sdksession.child_pid_of(client) == 4321

    logs = []
    messages = sdksession.ShutdownMessages(
        disconnect_timeout='t', disconnect_raised='r {{exc}}',
        abandoned_cancelled='c', abandoned_finished='f {{exc}}',
        abandoned_completed='k',
    )
    await sdksession.run_kill_ladder(
        client, 4321, logs.append,
        kill_secs=1.0, interrupt_grace_secs=0.1, loop_closing=True,
        pid_alive=lambda pid: False, messages=messages,
    )
    assert 'claude_agent_sdk' not in sys.modules or sys.modules['claude_agent_sdk'] is None
    print('LIB3-OK')

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "LIB3-OK" in result.stdout, (result.stdout, result.stderr)


def test_lib5_ui_package_can_import_sdksession(tmp_path):
    """`LIB5` -- `cd ui && uv run python -c "import self_learn.sdksession"`
    exits 0, rc captured unpiped."""
    ui_dir = _CLI_SRC_ROOT.parents[2] / "ui"
    assert ui_dir.is_dir(), ui_dir
    # scrub this PROCESS's own VIRTUAL_ENV (it is running inside the
    # CLI package's .venv) -- inherited into the subprocess it would
    # otherwise make `uv run` resolve the wrong project's environment.
    clean_env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
    result = subprocess.run(
        ["uv", "run", "python", "-c", "import self_learn.sdksession; print('LIB5-OK')"],
        cwd=str(ui_dir),
        capture_output=True,
        text=True,
        timeout=60,
        env=clean_env,
    )
    rc = result.returncode
    assert rc == 0, (rc, result.stdout, result.stderr)
    assert "LIB5-OK" in result.stdout


def test_lib6_wheel_contains_sdksession_init(tmp_path):
    """`LIB6` -- `uv build --project cli` produces a wheel containing
    `self_learn/sdksession/__init__.py`, rc unpiped."""
    cli_dir = _CLI_SRC_ROOT.parents[1]
    out_dir = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--project", str(cli_dir), "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    rc = result.returncode
    assert rc == 0, (rc, result.stdout, result.stderr)
    wheels = sorted(out_dir.glob("*.whl"))
    assert wheels, list(out_dir.iterdir())
    with zipfile.ZipFile(wheels[-1]) as zf:
        names = zf.namelist()
    assert "self_learn/sdksession/__init__.py" in names, names


# ===================================================================== #
# MS -- multi-session
# ===================================================================== #


def test_ms1_two_sessions_one_process_one_loop_interleaved(tmp_path):
    """`MS1` -- two sessions, one process, one loop, INTERLEAVED, on
    `FakeSdkClient`: both event logs exist, are distinct and complete;
    both kill ladders run independently; neither sweeps the other's
    child; neither unlinks the other's log. Proves per-session
    BOOKKEEPING is not process-global -- it does not (and, per the
    spec's own §11 row 15, cannot) prove real-transport concurrency."""
    cache_dir = tmp_path / "ms1-cache"
    cache_dir.mkdir()
    messages = sdk_policy.ShutdownMessages(
        disconnect_timeout="t", disconnect_raised="r {exc}",
        abandoned_cancelled="c", abandoned_finished="f {exc}", abandoned_completed="k",
    )

    async def _session(tag: str, hold_secs: float) -> tuple[str, sdk_events.EventLog]:
        run_id = sdk_events.new_run_id()
        client = FakeSdkClient(pid=1000 + hash(tag) % 100, messages=[f"{tag}-msg"])
        sdk_children.write_sidecar(cache_dir, "worker", client._transport._process.pid, "claude", session_key=run_id)
        session = sdk_session.SdkSession(client)
        await session.connect()
        await session.query(tag)
        events = sdk_events.EventLog()
        async for m in session.drive():
            events.add_tool_use("b1", "Read", {"note": m})
        await asyncio.sleep(hold_secs)  # force interleaving with the other session
        await sdk_teardown.run_kill_ladder(
            client, client._transport._process.pid, lambda _m: None,
            kill_secs=1.0, interrupt_grace_secs=0.1, loop_closing=True,
            pid_alive=lambda pid: False, messages=messages,
        )
        sdk_children.clear_sidecar(cache_dir, "worker", session_key=run_id)
        sdk_events.write_event_log(
            cache_dir, "worker", run_id, log_kind="ms1-events",
            meta={"tag": tag}, events=events,
        )
        return run_id, events

    async def _main():
        return await asyncio.gather(_session("A", 0.05), _session("B", 0.01))

    (run_id_a, events_a), (run_id_b, events_b) = asyncio.run(_main())

    assert run_id_a != run_id_b
    assert events_a.tool_events[0]["input"]["note"] == "A-msg"
    assert events_b.tool_events[0]["input"]["note"] == "B-msg"

    path_a = sdk_events.event_log_path(cache_dir, "worker", run_id_a, log_kind="ms1-events")
    path_b = sdk_events.event_log_path(cache_dir, "worker", run_id_b, log_kind="ms1-events")
    assert path_a.is_file() and path_b.is_file() and path_a != path_b
    meta_a = json.loads(path_a.read_text().splitlines()[0])
    meta_b = json.loads(path_b.read_text().splitlines()[0])
    assert meta_a["tag"] == "A" and meta_b["tag"] == "B"

    # neither session's clear_sidecar touched the other's sidecar path.
    assert not sdk_children.sidecar_path(cache_dir, "worker", run_id_a).exists()
    assert not sdk_children.sidecar_path(cache_dir, "worker", run_id_b).exists()


def test_ms2_ten_thousand_run_ids_distinct_regardless_of_surface():
    """`MS2` -- both legs, 10 000 calls each. `new_run_id()` takes no
    surface argument (`MS2`'s NORMATIVE clause), so distinctness must
    hold over the CALL SEQUENCE regardless of how a caller conceptually
    groups the calls."""
    # leg 1: all "on one surface" -- a tight loop, nothing interleaved.
    same_surface_ids = {sdk_events.new_run_id() for _ in range(10_000)}
    assert len(same_surface_ids) == 10_000

    # leg 2: interleaved -- calls alternate with unrelated work between
    # them, simulating two callers taking turns.
    interleaved_ids: list[str] = []
    for i in range(10_000):
        surface = "worker" if i % 2 == 0 else "miner-reader"
        interleaved_ids.append(f"{surface}:{sdk_events.new_run_id()}")
    bare_ids = {rid.split(":", 1)[1] for rid in interleaved_ids}
    assert len(bare_ids) == 10_000


def test_ms3_two_live_sessions_one_surface_two_distinct_sidecars_neither_swept(tmp_path):
    """`MS3` -- two live sessions on ONE surface produce two distinct
    sidecar files; the scoped sweep judges each on its own three
    corroborating checks and kills neither (both alive, neither
    stale)."""
    cache_dir = tmp_path / "ms3-cache"
    cache_dir.mkdir()
    my_pid = os.getpid()
    sdk_children.write_sidecar(cache_dir, "worker", my_pid, "irrelevant", session_key="run-a")
    sdk_children.write_sidecar(cache_dir, "worker", my_pid, "irrelevant", session_key="run-b")

    path_a = sdk_children.sidecar_path(cache_dir, "worker", "run-a")
    path_b = sdk_children.sidecar_path(cache_dir, "worker", "run-b")
    assert path_a != path_b
    assert path_a.is_file() and path_b.is_file()

    # The full independence proof (both sidecars judged and each
    # decline text-observable) is in the companion test below --
    # `test_ms3_full_messages_two_sidecars_each_declined_independently`.
    # This half just proves the two paths are genuinely distinct files,
    # which is `F-2`'s own headline property.


def test_ms3_full_messages_two_sidecars_each_declined_independently(tmp_path):
    cache_dir = tmp_path / "ms3b-cache"
    cache_dir.mkdir()
    my_pid = os.getpid()
    self_cmdline = Path(f"/proc/{my_pid}/cmdline").read_bytes().split(b"\x00")[0].decode()
    cli_name = os.path.basename(self_cmdline)
    sdk_children.write_sidecar(cache_dir, "worker", my_pid, cli_name, session_key="run-a")
    sdk_children.write_sidecar(cache_dir, "worker", my_pid, cli_name, session_key="run-b")

    messages = sdk_policy.ShutdownMessages(
        disconnect_timeout="t", disconnect_raised="r {exc}",
        abandoned_cancelled="c", abandoned_finished="f {exc}", abandoned_completed="k",
        orphan_not_stale=lambda surface, pid: f"not-stale:{surface}:{pid}",
    )
    logs: list[str] = []
    sdk_children.sweep_orphans(
        cache_dir, "worker", logs.append,
        pid_alive=lambda pid: True,
        messages=messages,
        process_start=0.0,
    )
    assert logs.count(f"not-stale:worker:{my_pid}") == 2, logs
    # both sidecars were independently read and cleared (a per-surface
    # singleton bug would only ever see ONE of the two).
    assert not sdk_children.sidecar_path(cache_dir, "worker", "run-a").exists()
    assert not sdk_children.sidecar_path(cache_dir, "worker", "run-b").exists()


def test_ms4_retention_at_session_end_never_unlinks_a_live_run_id(tmp_path):
    """`MS4` -- a file whose run id is in `live_run_ids` is never
    unlinked, regardless of its mtime rank."""
    cache_dir = tmp_path / "ms4-cache"
    cache_dir.mkdir()
    for i in range(5):
        p = cache_dir / f"worker.ms4-events.run-{i}.jsonl"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (i, i))  # run-0 is oldest, run-4 is newest

    # keep=2 would normally retain only run-3/run-4 and delete run-0..2.
    # run-0 (the OLDEST -- the first candidate for deletion) is live.
    sdk_events.prune_event_logs(
        cache_dir, "worker", log_kind="ms4-events", keep=2, live_run_ids=frozenset({"run-0"})
    )
    remaining = {p.name for p in cache_dir.glob("worker.ms4-events.*.jsonl")}
    assert "worker.ms4-events.run-0.jsonl" in remaining, remaining
    assert "worker.ms4-events.run-4.jsonl" in remaining, remaining
    assert "worker.ms4-events.run-3.jsonl" in remaining, remaining


def test_ms4_production_retention_runs_exactly_once_and_after_the_log_write(tmp_path, sdk_cli_path, monkeypatch):
    """`MS4` -- gate r1 M-3: the test above only exercises the
    library's own `prune_event_logs(live_run_ids=...)`, which the CLI
    production path never calls -- `invocation_sdk/events.py` keeps
    its own self-contained `prune_event_logs(surface)` with no such
    parameter (see that module's docstring: "for exactly this reason
    too"). Neither test asserted WHERE retention runs. This drives the
    REAL production path (a real `_run(_spec(...))` session, through
    `backend._drive`) with `backend_mod.prune_event_logs`/
    `write_event_log` wrapped (never stubbed -- the real
    implementations still run) to record call order. `GATE-iv`'s
    sibling mutation, `GATE-iii` (gate r1), reinstates a SECOND
    `prune_event_logs(surface)` call immediately after `sweep_orphans`
    at session START (undoing F-3/MS4's one production behaviour
    change) while leaving the original end-of-session call in place --
    this assertion goes red on exactly that: a starting session's
    prune call, reintroduced, is a second call BEFORE the write."""
    home = tmp_path / "ms4-order-home"
    home.mkdir()
    calls: list[str] = []
    real_prune = backend_mod.prune_event_logs
    real_write = backend_mod.write_event_log

    def _spy_prune(surface):
        calls.append("prune")
        return real_prune(surface)

    def _spy_write(surface, run_id, *, meta, events):
        calls.append("write")
        return real_write(surface, run_id, meta=meta, events=events)

    monkeypatch.setattr(backend_mod, "prune_event_logs", _spy_prune)
    monkeypatch.setattr(backend_mod, "write_event_log", _spy_write)

    outcome = _run(_spec("worker", home=home, prompt="ok_text"))
    assert outcome.ok is True
    assert calls.count("prune") == 1, calls
    assert calls.count("write") == 1, calls
    assert calls.index("write") < calls.index("prune"), calls


def test_ms5_staleness_anchor_is_a_parameter_two_anchors_decide_differently(tmp_path, monkeypatch):
    """`MS5` -- two sweeps in one process with different anchors decide
    differently on the SAME sidecar. `pid_alive` is stubbed `True` so
    the "stale" leg reaches the real `kill_child` call -- `os.kill`/
    `os.killpg` are monkeypatched to RECORD instead of signalling,
    because the sidecar's own pid is THIS test process's pid (never
    send a real signal to the harness that is running the assertion).
    N-5(a) (gate r1, residual minor gap): `kill_calls` itself is now
    asserted on both legs -- the NOT-stale leg must record NOTHING
    (the sweep never signals `os.getpid()` when it declines), and the
    stale leg must record EXACTLY one call, naming this process's own
    pid (proving what a real deployment would do, without ever
    actually doing it)."""
    cache_dir = tmp_path / "ms5-cache"
    cache_dir.mkdir()
    kill_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr(os, "killpg", lambda pid, sig: kill_calls.append((pid, sig)))
    my_pid = os.getpid()
    self_cmdline = Path(f"/proc/{my_pid}/cmdline").read_bytes().split(b"\x00")[0].decode()
    cli_name = os.path.basename(self_cmdline)
    started_at = 500.0

    messages = sdk_policy.ShutdownMessages(
        disconnect_timeout="t", disconnect_raised="r {exc}",
        abandoned_cancelled="c", abandoned_finished="f {exc}", abandoned_completed="k",
        orphan_not_stale=lambda surface, pid: "not-stale",
        orphan_killed=lambda surface, pid: "killed",
    )

    # anchor BEFORE started_at -- not stale, declined.
    sdk_children.write_sidecar(cache_dir, "worker", my_pid, cli_name)
    logs_before: list[str] = []
    sdk_children.sweep_orphans(
        cache_dir, "worker", logs_before.append,
        pid_alive=lambda pid: True, messages=messages, process_start=100.0,
    )
    assert logs_before == ["not-stale"], logs_before
    assert kill_calls == [], kill_calls  # N-5(a) -- never signalled, either direction

    # anchor AFTER started_at -- stale, killed (re-seed, since the first
    # sweep cleared it). `started_at` is a real `time.time()` value
    # (set by `write_sidecar` itself); the anchor must be LARGER than
    # that to read as stale, not an arbitrary small constant.
    sdk_children.write_sidecar(cache_dir, "worker", my_pid, cli_name)
    logs_after: list[str] = []
    sdk_children.sweep_orphans(
        cache_dir, "worker", logs_after.append,
        pid_alive=lambda pid: True, messages=messages, process_start=time.time() + 3600,
    )
    assert logs_after == ["killed"], logs_after
    assert len(kill_calls) == 1 and kill_calls[0][0] == my_pid, kill_calls  # N-5(a)'s other half


_MS6_FORBIDDEN_CALLS = {"run", "get_event_loop", "new_event_loop", "set_event_loop"}


def test_ms5_default_process_start_is_resolved_at_first_call_not_at_import():
    """`MS5` -- gate r1 M-4: both legs above pass an explicit
    `process_start=`, so `default_process_start()` -- F-4/G-1's whole
    point, "defaulted at first call, not at import" -- is never
    driven. `GATE-iv` (gate r1) restores the pre-fix shape (a
    module-level `_IMPORT_TIME_ANCHOR = time.time()`, returned
    unconditionally): reproduced here via `importlib.reload`, which
    re-executes the module body exactly like a fresh import would.
    Under the FIX, the value the function returns on its first call
    reflects WHEN THAT CALL HAPPENED (well after the reload, past a
    deliberate sleep); under the mutation, the returned value would be
    frozen at reload/import time, before the sleep -- so it must go
    red on exactly that shape."""
    import importlib

    from self_learn.sdksession import children as children_mod

    t_reload = time.time()
    importlib.reload(children_mod)
    try:
        time.sleep(0.3)
        t_before_call = time.time()
        anchor = children_mod.default_process_start()

        assert anchor >= t_before_call - 0.05, (anchor, t_before_call)
        assert anchor - t_reload >= 0.2, (anchor, t_reload)
    finally:
        importlib.reload(children_mod)  # leave a clean, unresolved cache behind


def test_ms6_no_asyncio_run_or_loop_creation_anywhere_in_the_package():
    violations = []
    for path in sorted(_SDKSESSION_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if (
                    isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name)
                    and f.value.id == "asyncio"
                    and f.attr in _MS6_FORBIDDEN_CALLS
                ):
                    violations.append((path.name, node.lineno, f"asyncio.{f.attr}"))
            # module-level (not inside any function/class) Task/loop creation.
        for node in tree.body:
            if isinstance(node, (ast.Expr, ast.Assign)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        f = sub.func
                        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                        if name in ("create_task", "ensure_future") and path.name != "teardown.py":
                            violations.append((path.name, sub.lineno, "module-level task creation"))
    assert violations == [], violations


def test_ms7_public_symbol_set_is_literal_no_sweep_all_no_kill_all():
    import self_learn.sdksession as sdksession

    expected = {
        # `supported_option_fields` deliberately absent (gate r1 M-1/N-1
        # -- an orphan, demoted from the public surface; see result.py).
        "ABANDONED_DISCONNECTS", "EventLog", "FakeSdkClient", "INTERRUPT_GRACE_SECS",
        "KILL_SECS", "SdkSession", "SessionPolicy", "ShutdownMessages", "TARGET_PATH_KEYS",
        "child_pid_of", "extract_target_path", "new_run_id", "prune_event_logs",
        "reduce_result_error", "run_kill_ladder",
        "sweep_orphans", "wrap_can_use_tool", "write_event_log", "write_sidecar",
    }
    assert set(sdksession.__all__) == expected, set(sdksession.__all__)

    # no sweep-all / kill-all entry point anywhere in the package.
    banned_name_fragments = ("sweep_all", "kill_all", "sweepall", "killall")
    for path in sorted(_SDKSESSION_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lowered = node.name.lower()
                assert not any(frag in lowered for frag in banned_name_fragments), (path.name, node.name)

    # no logging.Handler installed on any logger the library does not
    # own -- there is no `logging` import anywhere in the package at all.
    for path in sorted(_SDKSESSION_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name == "logging" for a in node.names), path.name
            if isinstance(node, ast.ImportFrom):
                assert node.module != "logging", path.name


# ===================================================================== #
# LAD -- the ladder
# ===================================================================== #


def test_lad1_call_time_read_two_legs(monkeypatch):
    """`LAD1` -- leg 1 (deterministic): a spy on the library's teardown
    entry point sees the monkeypatched `KILL_SECS`. Leg 2
    (corroboration): a 3600s-hanging `disconnect()` still returns in
    under 0.5s (25x the patched 0.02s bound, 5x under the unpatched
    2.5s)."""
    captured: dict[str, object] = {}
    real_run_kill_ladder = sdk_teardown.run_kill_ladder

    async def _spy(*args, **kwargs):
        captured.update(kwargs)
        return await real_run_kill_ladder(*args, **kwargs)

    monkeypatch.setattr(lifecycle_mod.teardown, "run_kill_ladder", _spy)
    monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 0.02)

    client = FakeSdkClient(pid=1)
    asyncio.run(lifecycle_mod.run_kill_ladder(client, None, lambda _m: None))
    assert captured["kill_secs"] == 0.02, captured

    hanging_client = FakeSdkClient(hang_disconnect_secs=3600)
    t0 = time.time()
    asyncio.run(lifecycle_mod.run_kill_ladder(hanging_client, None, lambda _m: None))
    elapsed = time.time() - t0
    assert elapsed < 0.5, elapsed
    for task in set(lifecycle_mod._ABANDONED_DISCONNECTS):
        task.cancel()


def test_lad2_abandoned_disconnects_is_the_library_object_by_identity():
    """`LAD2` -- identity, not equality. A copy would pass an equality
    check and break the pinned tests on the next task."""
    assert lifecycle_mod._ABANDONED_DISCONNECTS is sdk_teardown.ABANDONED_DISCONNECTS


# ===================================================================== #
# BND -- boundaries
# ===================================================================== #


def test_bnd1_charter_does_not_import_events_and_no_self_learn_ui_import():
    tree = ast.parse(Path(charter_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "events":
                raise AssertionError("charter.py imports .events")
            if node.module is None and node.level == 1:
                assert not any(a.name == "events" for a in node.names)
    for path in sorted(_CLI_PKG_DIR.glob("*.py")):
        assert "self_learn_ui" not in path.read_text(encoding="utf-8"), path.name


def test_bnd3_cli_src_zero_self_learn_ui_imports_positive_control():
    """§2.7's own measured instrument, verbatim:
    `grep -rnE "^\\s*(from|import)\\s+self_learn_ui" plugins/self-learn/cli/src`
    returns nothing -- an ANCHORED import-statement grep, not a bare
    substring search (which would also catch the two pre-existing prose
    mentions in `worker.py`/`verbs.py`, and this unit's own two, in
    `sdksession`'s docstrings explaining exactly this boundary)."""
    import re as _re

    pattern = _re.compile(r"^\s*(from|import)\s+self_learn_ui", _re.MULTILINE)
    hits = []
    for p in _CLI_SRC_ROOT.rglob("*.py"):
        for m in pattern.finditer(p.read_text(encoding="utf-8")):
            hits.append((p, m.group(0)))
    assert hits == [], hits

    # positive control: the identical grep style with a pattern KNOWN
    # present must return nonzero, so an empty result above cannot be
    # an empty search. Every module under `src/self_learn` is a
    # relative-import package internally (§2.7: no absolute
    # `from self_learn...` import exists in this tree at all), so the
    # known-present pattern is `from __future__ import annotations`,
    # which nearly every file in the tree carries.
    positive_pattern = _re.compile(r"^\s*(from|import)\s+__future__", _re.MULTILINE)
    positive_hits = sum(
        len(positive_pattern.findall(p.read_text(encoding="utf-8")))
        for p in _CLI_SRC_ROOT.rglob("*.py")
    )
    assert positive_hits > 0, "positive control found nothing -- the sweep itself is broken"


def test_bnd4_ev4_extended_to_sdksession_nothing_reads_a_log_file_back():
    """`BND4` -- extends `test_ev4`'s "nothing reads a tool-events file"
    sweep to `sdksession/`, in this NEW file (never by editing the
    pinned `test_invocation_sdk.py::test_ev4_...`, which globs
    `invocation_sdk/` only)."""
    events_path = _SDKSESSION_DIR / "events.py"
    src = events_path.read_text(encoding="utf-8")
    assert ".glob(" in src  # the only reference is write/prune's own glob pattern
    assert "read_text" not in src  # never reads a written log back
    for path in sorted(_SDKSESSION_DIR.glob("*.py")):
        if path.name == "events.py":
            continue
        assert ".jsonl" not in path.read_text(encoding="utf-8"), path.name


# ===================================================================== #
# POL -- policy stays with the clients (POL2 lands in 1A per Sec 9.1;
# POL1/POL3 are extended onto this file in 1B)
# ===================================================================== #

_POL2_TOOL_NAMES = (
    "Read", "Write", "Edit", "Bash", "Grep", "Glob",
    "NotebookEdit", "Task", "WebSearch", "WebFetch",
)


def _tool_name_literal_hits(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in _POL2_TOOL_NAMES:
                count += 1
    return count


def test_pol2_library_contains_zero_tool_name_literals_positive_control():
    lib_hits = sum(_tool_name_literal_hits(p) for p in _SDKSESSION_DIR.glob("*.py"))
    assert lib_hits == 0
    charter_hits = _tool_name_literal_hits(Path(charter_mod.__file__))
    assert charter_hits > 0, "positive control found nothing -- the sweep itself is broken"


_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")


def _literal_segments(template: str, *, min_len: int = 8) -> list[str]:
    """Split a `ShutdownMessages` string field on its `{placeholder}`s;
    keep only segments long enough not to be a coincidental match."""
    return [seg for seg in _PLACEHOLDER_RE.split(template) if len(seg) >= min_len]


def _callable_literal_segments(fn, *, min_len: int = 8) -> list[str]:
    """For an `orphan_*` formatter callable: call it with two DIFFERENT
    dummy argument sets and diff the two renders (`difflib.
    SequenceMatcher`) to recover the invariant (literal) template text
    MECHANICALLY -- never by hardcoding the template's shape, which
    would just be a second hand-copy of the table (`PIN2`'s anti-
    tautology rule applies here too)."""
    import difflib

    argcount = fn.__code__.co_argcount
    args_a = ("AAAA_surface", 111_111)[:argcount]
    args_b = ("BBBB_surface", 222_222)[:argcount]
    rendered_a, rendered_b = fn(*args_a), fn(*args_b)
    matcher = difflib.SequenceMatcher(None, rendered_a, rendered_b)
    return [
        rendered_a[block.a : block.a + block.size]
        for block in matcher.get_matching_blocks()
        if block.size >= min_len
    ]


def _table_literal_segments(messages) -> list[str]:
    """Every literal segment of a REAL `ShutdownMessages` instance --
    both the five ladder fields (dual-use) plus `child_pid_unresolved`
    (CLI-only), and the six `orphan_*` formatter callables when
    present (CLI-only; the UI table leaves them `None`)."""
    segments: list[str] = []
    for field in (
        "disconnect_timeout", "disconnect_raised", "abandoned_cancelled",
        "abandoned_finished", "abandoned_completed", "child_pid_unresolved",
    ):
        value = getattr(messages, field, "") or ""
        segments.extend(_literal_segments(value))
    for field in (
        "orphan_malformed", "orphan_no_live_process", "orphan_uncorroborated",
        "orphan_cmdline_mismatch", "orphan_not_stale", "orphan_killed",
    ):
        fn = getattr(messages, field, None)
        if fn is not None:
            segments.extend(_callable_literal_segments(fn))
    return segments


def test_pol2_library_contains_no_operator_message_prefix_positive_control():
    """`POL2` -- gate r1 M-2: the old sweep grepped for the literal
    string `"self-learn "`, which NO CLI-owned message contains (the
    two real prefixes are `"run: sdk backend:"` and `"pane engine"`),
    so `M-18b` (a message literal inlined byte-identical to its own
    pin) sailed through untouched. This sweep instead derives its
    target strings MECHANICALLY from the CLI's real
    `lifecycle.CLI_SHUTDOWN_MESSAGES` table -- never hand-copied -- and
    checks that none of them appear anywhere in the library's source."""
    segments = _table_literal_segments(lifecycle_mod.CLI_SHUTDOWN_MESSAGES)
    assert segments, "the sweep itself found nothing -- broken"

    # AST-based, not raw-text: `disconnect_timeout` (like `M-18b`'s
    # planted copy of it) is written as THREE adjacent-quoted string
    # literals split across lines -- Python's parser concatenates them
    # into ONE `ast.Constant`, but a raw-text substring search would
    # miss it entirely (the concatenated text never appears contiguous
    # in the SOURCE, only in the parsed VALUE). This also naturally
    # excludes `#`-prefixed comments (never part of the AST at all --
    # `policy.py` legitimately QUOTES `child_pid_unresolved`'s example
    # text in a `#:` field comment, which must not trip this sweep).
    def _string_constants(path: Path) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                values.append(node.value)
            elif isinstance(node, ast.JoinedStr):  # f-string static parts
                for piece in node.values:
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                        values.append(piece.value)
        return values

    lib_strings = [v for p in _SDKSESSION_DIR.glob("*.py") for v in _string_constants(p)]
    hits = [seg for seg in segments if any(seg in value for value in lib_strings)]
    assert hits == [], hits

    # positive control -- a literal PLANTED into a library-shaped
    # string constant (the exact `M-18b` shape: a table literal
    # inlined byte-identical into library code) is unconditionally
    # detected by this same matching logic.
    planted = [*lib_strings, segments[0]]
    assert any(seg in value for seg in segments for value in planted), (
        "planted literal not detected -- the sweep itself is broken"
    )


# ===================================================================== #
# LIB4 / POL1 / POL3 -- 1B additions (Sec 9.2's table assigns these to
# this file). LIB4 and POL1 run entirely here; POL3's CLI leg runs here
# -- its UI leg lives in `ui/tests/test_engine_shared_core.py` (a spy on
# a REAL `SdkPaneEngine._build_options` call can only execute from that
# package's own venv; the CLI cannot import `self_learn_ui` at all --
# Sec 2.7 -- so the reverse direction does not just fail a check, it
# does not compile).
# ===================================================================== #

_REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=str(_CLI_SRC_ROOT), check=True,
    ).stdout.strip()
)


def _ast_importers(
    *roots: Path, symbol: str, exclude: Path | None, include_tests: bool = False
) -> list[str]:
    """`LIB4` (gate r1 M-1 fix) -- a REAL importer: an `ast.ImportFrom`
    naming `symbol` out of an `sdksession`-ish module, or an
    `ast.Attribute` access `<alias>.symbol` where `<alias>` is bound to
    an `sdksession` submodule import (`lifecycle.py`'s own
    `children.sweep_orphans(...)` shape). `include_tests=False` (the
    default, used for `_LIB4_DUAL_CONSUMED`'s strict check) is SRC
    ONLY -- a test file always mentions what it tests; that is not
    adoption (gate r1: "10 of the 20 names are satisfied only by the
    new test file", which is exactly how `M-9` escaped). The floor
    check below passes `include_tests=True` deliberately: it is not
    asking "did production wire this in" (that is what
    `_LIB4_DUAL_CONSUMED` is for) but "is this symbol referenced by
    ANYTHING at all" -- the genuine parking-lot question (Sec 4.5) --
    and several package-surface names are DOCUMENTED as intended for a
    future consumer or for direct library-level testing rather than
    today's production callers (`events.py`'s own docstring: "this
    module's generalised versions exist for the OTHER two consumers
    and for direct library-level testing"; `fake.FakeSdkClient` exists
    SPECIFICALLY to be imported by tests, `LIB3`). `exclude`, when
    given, skips the library's own package directory -- an
    intra-package call is not an external consumer. Accepts multiple
    `roots` so the floor check can add each package's `tests/` dir
    without a caller needing to compute a shared ancestor."""
    hits: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if not include_tests and "tests" in path.parts:
                continue
            if exclude is not None and exclude in path.parents:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "sdksession" not in text:
                continue
            tree = ast.parse(text, filename=str(path))
            aliases: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and "sdksession" in node.module:
                    for alias in node.names:
                        if alias.name == symbol:
                            hits.append(path.name)
                        aliases.add(alias.asname or alias.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == symbol:
                    base = ast.unparse(node.value)
                    if base in aliases or "sdksession" in base:
                        hits.append(path.name)
    return hits


#: `LIB4` (gate r1 M-1) -- names in `sdksession/__init__.py`'s `__all__`
#: that BOTH engines genuinely call today, verified by direct read of
#: both production files before writing this list (never derived from
#: the sweep itself, for the same anti-tautology reason `PIN2`'s
#: literals are hand-copied): `ShutdownMessages`/`TARGET_PATH_KEYS`/
#: `extract_target_path`/`run_kill_ladder`/`ABANDONED_DISCONNECTS`/
#: `INTERRUPT_GRACE_SECS`/`KILL_SECS`/`SdkSession` are used by both
#: `invocation_sdk/lifecycle.py` (or a sibling CLI file) and
#: `self_learn_ui/engine/sdk.py`; `reduce_result_error` is `AGR3`'s
#: 1.000-skeleton-identical reduction, called at `backend.py:351` AND
#: `sdk.py:543` -- this is the exact symbol `M-9` (gate r1) mutated to
#: prove the sweep discriminates. Everything else in the package's
#: `__all__` is CLI-only or UI-only TODAY by design (Sec 9.1/9.2's
#: files-may-touch tables never route `children.py`/`events.py`/
#: `fake.py` mechanisms through the UI's `sdk.py` -- the pane does not
#: do headless-run cache/event-log/orphan-sweep bookkeeping the way a
#: per-invocation CLI run does), so requiring BOTH sides for those
#: would be a false positive, not a real orphan check.
_LIB4_DUAL_CONSUMED = frozenset({
    "ABANDONED_DISCONNECTS", "INTERRUPT_GRACE_SECS", "KILL_SECS", "SdkSession",
    "ShutdownMessages", "TARGET_PATH_KEYS", "extract_target_path",
    "reduce_result_error", "run_kill_ladder",
})


def test_lib4_no_orphan_symbol_every_all_name_has_an_importer_in_both_packages():
    """`LIB4` -- every name in `sdksession/__init__.py`'s `__all__` has
    at least one REAL (AST-level, src-only) importer somewhere; the
    names both engines are meant to share (`_LIB4_DUAL_CONSUMED`) must
    have one on EACH side -- this is what actually discriminates `M-9`
    (gate r1): inlining the UI's own copy of `reduce_result_error`
    removes its one real UI importer, and this assertion (unlike the
    r1 instrument's whole-file regex, which a comment or a test file
    satisfied) goes red on exactly that."""
    from self_learn import sdksession as sdksession_pkg

    cli_tests_dir = Path(__file__).resolve().parent
    ui_dir = _CLI_SRC_ROOT.parents[2] / "ui"
    assert ui_dir.is_dir(), ui_dir
    ui_src = ui_dir / "src"
    ui_tests_dir = ui_dir / "tests"

    orphans = []
    mismatched_dual = []
    for name in sdksession_pkg.__all__:
        if name in _LIB4_DUAL_CONSUMED:
            cli_hits = _ast_importers(_CLI_SRC_ROOT, symbol=name, exclude=_SDKSESSION_DIR)
            ui_hits = _ast_importers(ui_src, symbol=name, exclude=None)
            if not (cli_hits and ui_hits):
                mismatched_dual.append((name, cli_hits, ui_hits))
        else:
            cli_hits = _ast_importers(
                _CLI_SRC_ROOT, cli_tests_dir, symbol=name, exclude=_SDKSESSION_DIR, include_tests=True
            )
            ui_hits = _ast_importers(
                ui_src, ui_tests_dir, symbol=name, exclude=None, include_tests=True
            )
            if not (cli_hits or ui_hits):
                orphans.append(name)
    assert mismatched_dual == [], mismatched_dual
    assert orphans == [], orphans

    # positive control -- the sweep DOES find `reduce_result_error`'s
    # real UI importer today; a mutation that removes it (M-9) is what
    # `mismatched_dual` above exists to catch.
    assert _ast_importers(ui_src, symbol="reduce_result_error", exclude=None), (
        "positive control found nothing -- the sweep itself is broken"
    )


def _source_at_ref(ref: str, path: Path, qualname: str) -> str:
    rel = path.resolve().relative_to(_REPO_ROOT)
    proc = subprocess.run(
        ["git", "show", f"{ref}:{rel.as_posix()}"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT), check=True,
    )
    return _extract_def(proc.stdout, qualname, str(path))


def _source_now(path: Path, qualname: str) -> str:
    return _extract_def(path.read_text(encoding="utf-8"), qualname, str(path))


def _extract_def(src: str, qualname: str, filename: str) -> str:
    tree = ast.parse(src, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == qualname:
            segment = ast.get_source_segment(src, node)
            assert segment is not None
            return segment
    raise AssertionError(f"{qualname!r} not found")


def test_pol1_both_build_can_use_tool_bodies_are_byte_unchanged_since_a0c67be():
    """`POL1` -- `git diff a0c67be` restricted to `build_can_use_tool`'s
    body (both charters), `CharterPaths` (both), and both fail-closed
    exception classes is empty. Extracted via `ast.get_source_segment`
    at each ref rather than a raw `git diff -- <file>`, so an unrelated
    import reshuffle ABOVE these definitions (this unit's own `P`/
    `_extract_target_path` -> import change, Sec 9.1) can never be
    mistaken for a change INSIDE them."""
    ui_dir = _CLI_SRC_ROOT.parents[2] / "ui"
    ui_charter_path = ui_dir / "src" / "self_learn_ui" / "engine" / "charter.py"
    cli_charter_path = Path(charter_mod.__file__)

    targets = [
        (cli_charter_path, "build_can_use_tool"),
        (cli_charter_path, "CharterPaths"),
        (cli_charter_path, "CharterPatternUnsupported"),
        (ui_charter_path, "build_can_use_tool"),
        (ui_charter_path, "CharterPaths"),
        (ui_charter_path, "CanonReadRootsUnavailable"),
    ]
    for path, qualname in targets:
        before = _source_at_ref("a0c67be", path, qualname)
        after = _source_now(path, qualname)
        assert before == after, (path, qualname)


def test_pol3_cli_option_floor_exact_keys_fresh_dict_and_called_once(monkeypatch, tmp_path, sdk_cli_path):
    """`POL3` -- CLI leg. `option_floor()` returns exactly the three
    keys measured identical in Sec 2.3, a FRESH dict every call (two
    calls, mutate one, the other is unaffected), and is called EXACTLY
    ONCE per construction -- checked by a spy on the shared function
    (the CLI's `CliSessionPolicy.option_floor` is a one-line delegation
    to it), asserted on options built by `_run(spec)`'s real call path
    (`SdkBackend().write_session` -> `_build_options` -> `options_kwargs`
    -- a REAL `SessionSpec` from the shared `_spec()` fixture, never a
    hand-built options dict)."""
    floor_a = sdk_policy.default_option_floor()
    floor_b = sdk_policy.default_option_floor()
    assert floor_a == floor_b == {
        "allowed_tools": [], "setting_sources": [], "strict_mcp_config": True,
    }
    floor_a["allowed_tools"].append("Bash")
    assert floor_b["allowed_tools"] == []  # unaffected -- a fresh dict per call

    calls: list[int] = []
    real_floor = sdk_policy.default_option_floor

    def _spy() -> dict[str, object]:
        calls.append(1)
        return real_floor()

    monkeypatch.setattr(sdk_policy, "default_option_floor", _spy)

    home = tmp_path / "home"
    home.mkdir()
    spec = _spec("worker", home=home)
    _run(spec)
    assert len(calls) == 1, calls
