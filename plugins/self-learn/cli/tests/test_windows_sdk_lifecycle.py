"""S-NEXT-w6-sdk. The Claude Code child's lifecycle on Windows.

self-learn's model-backed commands run Claude Code through the Agent SDK,
which spawns the child itself. On Windows self-learn joins its own
kill-on-close job before the first real child is spawned, puts the child in a
job of its own as soon as the SDK's transport has its PID (during the
handshake), records the child's and its own identity in the sidecar, ends the
child's job when the session ends, and sweeps a leftover child on a later run
only when its owner is gone and its live identity is exactly the recorded one.
The installed-CLI search hands the SDK only a native ``claude.exe``, and the
doctor never runs a batch shim.

Windows tests drive the real code with the fake SDK client
(``sdksession/fake.py``), made to spawn a Python stand-in for ``claude.exe``
(a copy of the interpreter named ``claude.exe``) that spawns a grandchild.
Every process a test starts is registered for cleanup the moment it exists.
Linux tests check that none of the Windows code is reached or loaded there.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from claude_agent_sdk import ClaudeSDKClient

from self_learn import provider
from self_learn.primitives import procs
from self_learn.sdksession import _containment_windows as cw
from self_learn.sdksession import children, teardown
from self_learn.sdksession.fake import FakeSdkClient

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows SDK lifecycle contract")
linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux SDK lifecycle contract")

#: The interpreter itself, not the venv redirector (whose PID is not the
#: Python it starts).
_BASE = getattr(sys, "_base_executable", sys.executable)

#: The stand-in for Claude Code: spawn a grandchild (the base interpreter),
#: publish "<own pid> <grandchild pid>" by writing a sibling and renaming it,
#: then sleep.
_STANDIN = r"""
import os, subprocess, sys, time
ready, base = sys.argv[1], sys.argv[2]
grandchild = subprocess.Popen([base, "-c", "import time; time.sleep(300)"])
temp = ready + ".tmp"
with open(temp, "w") as fh:
    fh.write(f"{os.getpid()} {grandchild.pid}")
os.replace(temp, ready)
time.sleep(300)
"""


def _wait_for(predicate, seconds=15.0):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "process observation timed out"
        time.sleep(0.02)


def _claude_exe(directory: Path, name: str = "claude.exe") -> Path:
    """A copy of the base interpreter named *name*, with the DLLs it loads
    from its own folder; run it with :func:`_standin_env`."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    shutil.copy2(_BASE, target)
    for dll in Path(_BASE).parent.glob("*.dll"):
        if not (directory / dll.name).exists():
            shutil.copy2(dll, directory / dll.name)
    return target


def _standin_env() -> dict[str, str]:
    return {**os.environ, "PYTHONHOME": sys.base_prefix}


def _kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=60)


class _Watch:
    """SYNCHRONIZE handles that pin each PID, so a death is observed on the
    process itself and never on a reused PID."""

    def __init__(self, pids):
        import win32api
        import win32con

        self.pids = list(pids)
        self.handles = [win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, pid)
                        for pid in self.pids]

    def alive(self):
        import win32event

        return [win32event.WaitForSingleObject(h, 0) == win32event.WAIT_TIMEOUT for h in self.handles]

    def wait_dead(self, seconds=15.0):
        _wait_for(lambda: not any(self.alive()), seconds)

    def kill(self):
        import pywintypes
        import win32api
        import win32process

        for handle, alive in zip(self.handles, self.alive()):
            if alive:
                try:
                    win32process.TerminateProcess(handle, 1)
                except pywintypes.error:  # already exiting
                    pass
        for handle in self.handles:
            win32api.CloseHandle(handle)
        self.handles = []


@pytest.fixture
def reaper():
    """Cleanups registered by each spawn the moment it exists, run whatever
    the test did."""
    cleanups: list = []
    yield cleanups
    for cleanup in reversed(cleanups):
        try:
            cleanup()
        except Exception:  # noqa: BLE001 - every cleanup runs
            pass


def _spawn(reaper, directory: Path, exe: Path | str = _BASE, name: str = "standin"):
    """Start the stand-in under *exe*; return ``(child, grandchild, watch)``,
    with the tree's cleanup registered before anything else can fail."""
    directory.mkdir(parents=True, exist_ok=True)
    ready = directory / name
    proc = subprocess.Popen([str(exe), "-u", "-c", textwrap.dedent(_STANDIN), str(ready), _BASE],
                            env=_standin_env())
    holder: dict = {}

    def cleanup():
        watch = holder.get("watch")
        if watch is not None:
            watch.kill()
        if proc.poll() is None:
            _kill_tree(proc.pid)
            proc.kill()
        proc.wait(timeout=10)

    reaper.append(cleanup)
    _wait_for(ready.exists)
    child, grandchild = (int(pid) for pid in ready.read_text().split())
    holder["watch"] = _Watch([child, grandchild])
    return child, grandchild, holder["watch"]


def _sleeper(reaper):
    """A live process with a known identity (an 'owner' for sweep records)."""
    proc = subprocess.Popen([_BASE, "-c", "import time; time.sleep(300)"])
    reaper.append(lambda: (proc.kill(), proc.wait(timeout=10)))
    _wait_for(lambda: procs.process_identity(proc.pid) is not None)
    return proc


def _gone_owner(reaper):
    """The identity of a process that has exited: a session owner that died."""
    proc = _sleeper(reaper)
    identity = procs.process_identity(proc.pid)
    proc.kill()
    proc.wait(timeout=10)
    return proc.pid, identity


def _terminate_pid(pid):
    import win32api
    import win32con
    import win32process

    opened = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
    try:
        win32process.TerminateProcess(opened, 9)
    finally:
        win32api.CloseHandle(opened)


# --------------------------------------------------------------------------
# The session kit: the fake SDK client, made to spawn the stand-in at
# connect() and registered as a real SDK client (the backend contains only
# those), and a minimal session spec. Also used by the launcher below.
# --------------------------------------------------------------------------


class SpawningClient(FakeSdkClient, ClaudeSDKClient):
    """`FakeSdkClient` (its methods come first), but `connect()` spawns the
    stand-in the way the real SDK spawns Claude Code: the PID appears on the
    private transport chain while the handshake is still running.
    ``fail_handshake``: after spawning, end only the child (what the SDK's
    disconnect does), drop the transport and raise, so the session never
    publishes the PID."""

    def __init__(self, exe, workdir, reaper, *, messages=None, hang=False, on_drive=None, order=None,
                 fail_handshake=False):
        FakeSdkClient.__init__(self, pid=0, messages=messages)
        self.exe, self.workdir, self.reaper, self.hang = exe, Path(workdir), reaper, hang
        self.on_drive, self.order, self.fail_handshake = on_drive, order, fail_handshake
        self.pids = None
        self.watch = None
        self.contained_during_handshake = None

    async def connect(self):
        await FakeSdkClient.connect(self)
        if self.order is not None:
            self.order.append("connect")
        child, grandchild, self.watch = _spawn(self.reaper, self.workdir, self.exe, name="session-standin")
        self.pids = [child, grandchild]
        self._transport._process.pid = child
        # The handshake: the containment watcher runs while this awaits.
        await asyncio.sleep(0.3)
        self.contained_during_handshake = child in cw.CONTAINED
        if self.fail_handshake:
            _terminate_pid(child)
            self._transport = None
            from claude_agent_sdk import CLIConnectionError

            raise CLIConnectionError("injected: the initialize handshake timed out")

    async def receive_response(self):
        if self.on_drive is not None:
            self.on_drive(self)
        if self.hang:
            await asyncio.sleep(600)
        for message in self._messages:
            yield message


def ok_messages():
    from claude_agent_sdk import ResultMessage

    return [ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                          num_turns=1, session_id="w6-sdk-session", result="ok")]


def make_spec(home, *, log, timeout=60.0):
    from self_learn.invocation.contract import SessionSpec, containment_for

    return SessionSpec(surface="analyst", prompt="ok", cwd=Path(home), timeout=timeout,
                       containment=containment_for("analyst", allowed_tools="Read,Grep,Glob"),
                       log=log, label="")


def _messages():
    from self_learn.invocation_sdk import lifecycle

    return lifecycle.CLI_SHUTDOWN_MESSAGES


def _registered_messages():
    registered = cw.containment()
    assert registered is not None
    return registered[1]


@pytest.fixture
def fresh_state(monkeypatch):
    """A clean containment registry for this test (module state)."""
    from self_learn.invocation_sdk import backend  # noqa: F401 - registers the procs calls

    monkeypatch.setattr(cw, "CONTAINED", {})
    monkeypatch.setattr(cw, "_SESSIONS", {})
    monkeypatch.setattr(cw, "_SELF_TRIED", [])
    monkeypatch.setattr(cw, "_SELF_IDENTITY", [])


@pytest.fixture
def session_env(tmp_path, monkeypatch, fresh_state, reaper):
    """A scratch ledger and cache, the stand-in ``claude.exe`` named as the
    program the session is handed, and no self job for the test process (the
    launcher tests use the real one): `procs.contain_self` records instead."""
    from self_learn.invocation_sdk import backend

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    exe = _claude_exe(tmp_path / "bin")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(exe))
    self_calls = []
    monkeypatch.setattr(procs, "contain_self", lambda: self_calls.append("contain_self") or True)
    return backend, home, exe, self_calls


def _run(backend, monkeypatch, client, home, logs):
    monkeypatch.setattr(backend, "ClaudeSDKClient", lambda options: client)
    return backend.SdkBackend().write_session(make_spec(home, log=logs.append))


# --------------------------------------------------------------------------
# Windows: registration, the sidecar, the last rung
# --------------------------------------------------------------------------


@windows
def test_windows_backend_registers_the_procs_calls_on_import():
    from self_learn.invocation_sdk import backend

    registered = cw.containment()
    assert registered is not None and registered[0] is procs
    assert backend._windows_procs is procs


@windows
def test_windows_sidecar_round_trips_both_identities(tmp_path, fresh_state, reaper):
    child, grandchild, watch = _spawn(reaper, tmp_path)
    logs = []
    session = cw.Session(logs.append)
    cw._contain(session, child)
    assert logs == [] and cw.CONTAINED[child] is session
    children.write_sidecar(tmp_path, "worker", child, _BASE)
    record = children.read_sidecar(tmp_path, "worker")
    assert set(record) == {"pid", "started_at", "cli", "identity", "owner", "program", "program_matches"}
    live = procs.process_identity(child)
    me = procs.process_identity(os.getpid())
    assert record["identity"] == {"image": live.image, "created": live.created}
    assert record["owner"] == {"pid": os.getpid(), "image": me.image, "created": me.created}
    assert (record["program"], record["program_matches"]) == ("handed", True)
    # A child whose containment read nothing records no identity.
    children.write_sidecar(tmp_path, "other", 4242, "")
    other = children.read_sidecar(tmp_path, "other")
    assert other["identity"] is None and (other["program"], other["program_matches"]) == ("sdk", False)
    # This process's own record is cleared at the session's end.
    children.clear_sidecar(tmp_path, "worker")
    assert children.read_sidecar(tmp_path, "worker") is None
    # The last rung ends the job even when pid_alive says the child is gone.
    teardown.kill_child(child, logs.append, lambda pid: False)
    watch.wait_dead()
    assert logs == [] and child not in cw.CONTAINED


@windows
def test_windows_last_rung_ends_the_grandchild_after_the_sdk_ended_the_child(tmp_path, fresh_state, reaper):
    """The SDK's own teardown ends only Claude Code (TerminateProcess): its
    descendants live on. The last rung ends them through the job."""
    child, grandchild, watch = _spawn(reaper, tmp_path)
    cw._contain(cw.Session(lambda line: None), child)
    _terminate_pid(child)  # what the SDK's terminate() does
    _wait_for(lambda: watch.alive() == [False, True])
    time.sleep(0.3)
    assert watch.alive() == [False, True], "the grandchild must outlive the child alone"
    teardown.kill_child(child, lambda line: None, procs.pid_alive)
    watch.wait_dead()


# --------------------------------------------------------------------------
# Windows: a whole session through the real backend with the fake client
# --------------------------------------------------------------------------


@windows
def test_windows_session_contains_the_child_and_teardown_kills_both(tmp_path, monkeypatch, session_env, reaper):
    from self_learn.invocation_sdk import lifecycle

    backend, home, exe, self_calls = session_env
    order = []
    monkeypatch.setattr(procs, "contain_self", lambda: order.append("contain_self") or True)
    seen = {}

    def on_drive(client):
        child = client.pids[0]
        entry = cw.CONTAINED.get(child)
        seen["contained"] = entry is not None and entry.handle is not None
        seen["sidecar"] = children.read_sidecar(lifecycle.worker.cache_dir(), "analyst")
        seen["live"] = procs.process_identity(child)
        seen["alive"] = client.watch.alive()

    client = SpawningClient(exe, tmp_path / "work", reaper, messages=ok_messages(), on_drive=on_drive, order=order)
    logs = []
    outcome = _run(backend, monkeypatch, client, home, logs)
    assert (outcome.ok, outcome.stdout) == (True, "ok"), (outcome.failure, logs)
    assert outcome.child_pid == client.pids[0]
    assert order == ["contain_self", "connect"], "self containment must come before the spawn"
    assert client.contained_during_handshake, "the child must be contained before connect() returns"
    assert seen["alive"] == [True, True] and seen["contained"]
    live = seen["live"]
    assert seen["sidecar"]["identity"] == {"image": live.image, "created": live.created}
    assert os.path.samefile(live.image, exe) and seen["sidecar"]["cli"] == str(exe)
    assert seen["sidecar"]["program_matches"] is True
    # The last rung ran when write_session returned: both are gone.
    assert client.watch.alive() == [False, False]
    assert cw.CONTAINED == {} and cw._SESSIONS == {}
    assert children.read_sidecar(lifecycle.worker.cache_dir(), "analyst") is None
    assert logs == [], logs  # a clean contained session logs nothing


@windows
def test_windows_failed_handshake_still_ends_the_childs_job(tmp_path, monkeypatch, session_env, reaper):
    """The SDK spawned the child, the handshake failed, and the SDK ended
    only the child: the session never published the PID. The job made during
    the handshake still ends the grandchild when the session ends."""
    backend, home, exe, self_calls = session_env
    terminate = Mock(wraps=procs.terminate_contained)
    monkeypatch.setattr(procs, "terminate_contained", terminate)
    client = SpawningClient(exe, tmp_path / "work", reaper, messages=ok_messages(), fail_handshake=True)
    logs = []
    outcome = _run(backend, monkeypatch, client, home, logs)
    assert not outcome.ok and outcome.failure == "os-error" and outcome.child_pid is None
    assert client.contained_during_handshake
    # Ended explicitly (bounded, waited for), not only by a dropped handle.
    (handle,), _ = terminate.call_args
    assert terminate.call_count == 1 and handle.pid == client.pids[0]
    assert client.watch.alive() == [False, False], "the grandchild must not outlive a failed handshake"
    assert cw.CONTAINED == {} and cw._SESSIONS == {}


@windows
def test_windows_a_substituted_client_is_never_contained(tmp_path, monkeypatch, session_env, reaper):
    """A test's plain fake client (any client that is not the SDK's own
    class) names a made-up or a test's process: neither the self job nor a
    child job is touched, so a fake session can never put the test process
    in a lifetime job."""
    backend, home, exe, self_calls = session_env
    sleeper = _sleeper(reaper)
    spy_self, spy_child = Mock(return_value=True), Mock(wraps=procs.contain_child)
    monkeypatch.setattr(procs, "contain_self", spy_self)
    monkeypatch.setattr(procs, "contain_child", spy_child)
    logs = []
    outcome = _run(backend, monkeypatch, FakeSdkClient(pid=sleeper.pid, messages=ok_messages()), home, logs)
    assert (outcome.ok, outcome.stdout) == (True, "ok"), logs
    spy_self.assert_not_called()
    spy_child.assert_not_called()
    assert sleeper.poll() is None and cw._SESSIONS == {} and cw.CONTAINED == {}
    # Positive control: the same run with the SDK's class is contained.
    client = SpawningClient(exe, tmp_path / "work", reaper, messages=ok_messages())
    assert _run(backend, monkeypatch, client, home, logs).ok
    spy_self.assert_called_once()
    assert spy_child.call_count >= 1


@windows
@pytest.mark.parametrize("fault", ["contain-raises", "contain-interrupted", "terminate-times-out", "self-refused"])
def test_windows_containment_trouble_never_fails_the_session(tmp_path, monkeypatch, session_env, reaper, fault):
    backend, home, exe, self_calls = session_env
    real_contain, real_terminate = procs.contain_child, procs.terminate_contained
    calls = {"contain": [], "terminate": 0}

    def contain(pid, *, expect=None):
        calls["contain"].append(expect)
        if len(calls["contain"]) == 1 and fault == "contain-raises":
            raise PermissionError(13, "injected refusal")
        handle = real_contain(pid, expect=expect)
        if len(calls["contain"]) == 1 and fault == "contain-interrupted":
            exc = OSError(1, "injected interruption after the child joined")
            exc.contained_child = handle
            raise exc
        return handle

    def terminate(handle):
        calls["terminate"] += 1
        if calls["terminate"] == 1 and fault == "terminate-times-out":
            real_terminate(handle)  # what a bound that expired leaves: handles released
            raise TimeoutError("injected: still has processes after 5 s")
        return real_terminate(handle)

    def refuse_self():
        raise PermissionError(5, "injected self-job refusal")

    monkeypatch.setattr(procs, "contain_child", contain)
    monkeypatch.setattr(procs, "terminate_contained", terminate)
    if fault == "self-refused":
        monkeypatch.setattr(procs, "contain_self", refuse_self)
    client = SpawningClient(exe, tmp_path / "work", reaper, messages=ok_messages())
    logs = []
    outcome = _run(backend, monkeypatch, client, home, logs)
    # A second session in the same process tries contain_self no more.
    second = SpawningClient(exe, tmp_path / "work2", reaper, messages=ok_messages())
    again = _run(backend, monkeypatch, second, home, logs)
    assert (outcome.ok, outcome.stdout, again.ok, again.stdout) == (True, "ok", True, "ok"), logs
    messages = _registered_messages()
    child = client.pids[0]
    expected = {
        "contain-raises": messages.contain_refused.format(pid=child, exc=PermissionError(13, "injected refusal")),
        "contain-interrupted": messages.contain_partial.format(
            pid=child, exc=OSError(1, "injected interruption after the child joined")),
        "terminate-times-out": messages.terminate_failed.format(
            pid=child, exc=TimeoutError("injected: still has processes after 5 s")),
        "self-refused": messages.self_failed.format(exc=PermissionError(5, "injected self-job refusal")),
    }[fault]
    assert logs == [expected], logs
    # Whatever went wrong, both sessions' trees were ended.
    _wait_for(lambda: not any(client.watch.alive() + second.watch.alive()))
    if fault == "contain-raises":
        # No handle at spawn: the session ended it by containing the identity
        # read at spawn again, and only that identity (expect=).
        assert len(calls["contain"]) == 3 and calls["contain"][0] is None
        assert isinstance(calls["contain"][1], procs.ProcessIdentity)
        assert os.path.samefile(calls["contain"][1].image, exe)
    if fault == "contain-interrupted":
        # The handle the failing call carried was kept: ended without
        # containing anything again.
        assert calls["contain"] == [None, None]
    assert cw.CONTAINED == {} and cw._SESSIONS == {}


@windows
@pytest.mark.parametrize("case", ["unresolved-pid", "contained"])
def test_windows_a_failing_logger_never_costs_the_answer(tmp_path, monkeypatch, session_env, reaper, case):
    """Every line a Windows session logs, at start-up and in teardown, may
    fail to be delivered; the answer is still returned."""
    backend, home, exe, self_calls = session_env

    def broken_log(line):
        raise RuntimeError("injected: the journal is locked")

    if case == "unresolved-pid":
        client = FakeSdkClient(pid=None, messages=ok_messages())  # logs "could not resolve the child pid"
    else:
        client = SpawningClient(exe, tmp_path / "work", reaper, messages=ok_messages())
        real_terminate = procs.terminate_contained

        def times_out(handle):
            real_terminate(handle)
            raise TimeoutError("injected")

        monkeypatch.setattr(procs, "contain_self", Mock(side_effect=PermissionError(5, "injected")))
        monkeypatch.setattr(procs, "terminate_contained", times_out)
    monkeypatch.setattr(backend, "ClaudeSDKClient", lambda options: client)
    outcome = backend.SdkBackend().write_session(make_spec(home, log=broken_log))
    assert (outcome.ok, outcome.stdout) == (True, "ok")
    if case == "contained":
        _wait_for(lambda: not any(client.watch.alive()))


def _cache_path_filter(real, suffix, error):
    def patched(self, *args, **kwargs):
        if str(self).endswith(suffix):
            raise error
        return real(self, *args, **kwargs)
    return patched


@windows
def test_windows_sidecar_write_and_delete_denial_never_cost_the_answer(tmp_path, monkeypatch, session_env, reaper):
    from self_learn.invocation_sdk import lifecycle

    backend, home, exe, self_calls = session_env
    # Write denied before the query.
    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", _cache_path_filter(Path.write_text, ".sdk-child.pid",
                                                              PermissionError(13, "injected: write denied")))
        client = SpawningClient(exe, tmp_path / "work", reaper, messages=ok_messages())
        logs = []
        outcome = _run(backend, monkeypatch, client, home, logs)
    assert (outcome.ok, outcome.stdout) == (True, "ok"), logs
    assert logs == [_registered_messages().sidecar_failed.format(
        pid=client.pids[0], exc=PermissionError(13, "injected: write denied"))]
    assert client.watch.alive() == [False, False]
    # Delete denied after a successful result.
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", _cache_path_filter(Path.unlink, ".sdk-child.pid",
                                                          PermissionError(13, "injected: delete denied")))
        second = SpawningClient(exe, tmp_path / "work2", reaper, messages=ok_messages())
        logs = []
        outcome = _run(backend, monkeypatch, second, home, logs)
    assert (outcome.ok, outcome.stdout) == (True, "ok"), logs
    assert second.watch.alive() == [False, False]
    left = children.read_sidecar(lifecycle.worker.cache_dir(), "analyst")
    assert left is not None and left["pid"] == second.pids[0], "the undeletable record stays for a later sweep"


@windows
def test_windows_a_failing_sweep_never_stops_the_session(tmp_path, monkeypatch, session_env, reaper):
    from self_learn.invocation_sdk import lifecycle

    backend, home, exe, self_calls = session_env
    cache = lifecycle.worker.cache_dir()
    children.sidecar_path(cache, "analyst").write_text(json.dumps({"pid": 4242, "started_at": 0.0, "cli": ""}),
                                                        encoding="utf-8")
    failure = OSError(31, "injected: liveness probe failed")
    monkeypatch.setattr(lifecycle.worker, "_pid_alive", Mock(side_effect=failure))
    client = SpawningClient(exe, tmp_path / "work", reaper, messages=ok_messages())
    logs = []
    outcome = _run(backend, monkeypatch, client, home, logs)
    assert (outcome.ok, outcome.stdout) == (True, "ok"), logs
    assert logs == [_registered_messages().sweep_failed.format(surface="analyst", exc=failure)]


# --------------------------------------------------------------------------
# Windows: the orphan sweep on a later run
# --------------------------------------------------------------------------


def _orphan_record(pid, identity, cli, owner, *, program=None, matches=None):
    owner_pid, owner_identity = owner
    return {
        "pid": pid, "started_at": 0.0, "cli": cli,
        "identity": None if identity is None else {"image": identity.image, "created": identity.created},
        "owner": {"pid": owner_pid, "image": owner_identity.image, "created": owner_identity.created},
        "program": program or ("handed" if cli else "sdk"),
        "program_matches": (cw.program_matches(identity.image, cli) if identity is not None else False)
        if matches is None else matches,
    }


def _sweep(cache, record, *, keep=False):
    path = children.sidecar_path(cache, "worker")
    path.write_text(json.dumps(record), encoding="utf-8")
    logs = []
    children.sweep_orphans(cache, "worker", logs.append, pid_alive=procs.pid_alive,
                           messages=_messages(), process_start=time.time())
    assert path.exists() is keep, "the sidecar must be kept" if keep else "the sidecar must be cleared"
    return logs


@windows
@pytest.mark.parametrize("case", ["leftover", "sdk-chose", "sdk-chose-com", "relative-cli", "reused-pid",
                                  "reused-at-assignment", "predates-boot", "not-claude", "not-claude-no-cli",
                                  "claude-elsewhere", "no-identity", "malformed-program"])
def test_windows_orphan_sweep_kills_only_a_true_leftover(tmp_path, monkeypatch, fresh_state, reaper, case):
    from self_learn.primitives import _procs_windows as windows_backend

    exe = _claude_exe(tmp_path / "bin", "claude.com" if case == "sdk-chose-com" else "claude.exe")
    image = _BASE if case in ("not-claude", "not-claude-no-cli") else exe
    child, grandchild, watch = _spawn(reaper, tmp_path / "work", image)
    owner = _gone_owner(reaper)
    identity = procs.process_identity(child)
    cli = {"sdk-chose": "", "sdk-chose-com": "", "not-claude-no-cli": "", "relative-cli": "claude.exe",
           "claude-elsewhere": str(_claude_exe(tmp_path / "other"))}.get(case, str(exe))
    if case == "relative-cli":
        # The program was handed as a bare name in the session's own folder;
        # the match is decided there, at spawn, not in the sweeper's folder.
        monkeypatch.chdir(tmp_path / "bin")
        record = _orphan_record(child, identity, cli, owner)
        monkeypatch.chdir(tmp_path)
        assert not cw.program_matches(identity.image, cli), "control: from here it would not match"
    else:
        record = _orphan_record(child, None if case == "no-identity" else identity, cli, owner)
    if case == "malformed-program":
        record["program"] = "guessed"

    def one_tick_later(real):
        def later(handle, created, *rest):
            ok = real(handle, created, *rest)
            value = windows_backend._filetime(created._obj) + 1
            created._obj.dwLowDateTime, created._obj.dwHighDateTime = value & 0xFFFFFFFF, value >> 32
            return ok
        return later

    if case == "reused-pid":
        # Same PID, a creation time one tick later, at the real call.
        monkeypatch.setattr(windows_backend, "_get_process_times", one_tick_later(windows_backend._get_process_times))
    real_identity = procs.process_identity
    if case == "reused-at-assignment":
        # The live lookup still matches; the number then passes to another
        # process before the job is made (seen at the assignment's own check).
        def lookup(pid):
            found = real_identity(pid)
            if pid == child:
                monkeypatch.setattr(windows_backend, "_get_process_times",
                                    one_tick_later(windows_backend._get_process_times))
            return found
        monkeypatch.setattr(procs, "process_identity", lookup)
    if case == "predates-boot":
        # An uptime of zero puts the boot after the recorded creation time.
        monkeypatch.setattr(windows_backend, "_tick_count", lambda: 0)
    messages = _messages()
    contain = Mock(wraps=procs.contain_child)
    terminate = Mock(wraps=procs.terminate_contained)
    monkeypatch.setattr(procs, "contain_child", contain)
    monkeypatch.setattr(procs, "terminate_contained", terminate)
    killed = case in ("leftover", "sdk-chose", "sdk-chose-com", "relative-cli")
    logs = _sweep(tmp_path, record)
    if killed:
        assert logs == [messages.orphan_killed("worker", child)]
        watch.wait_dead()
        assert cw.CONTAINED == {}
        # The job was made only on that identity, and ended explicitly
        # (bounded, waited for), not by a dropped handle.
        assert contain.call_args_list[0].args == (child,)
        assert contain.call_args_list[0].kwargs == {"expect": identity}
        (handle,), _ = terminate.call_args
        assert terminate.call_count == 1 and handle.pid == child
    else:
        terminate.assert_not_called()
        line = (messages.orphan_uncorroborated if case in ("predates-boot", "no-identity", "malformed-program")
                else messages.orphan_cmdline_mismatch)
        assert logs == [line("worker", child)]
        if case == "reused-at-assignment":
            assert contain.call_args_list[0].kwargs == {"expect": identity}
        time.sleep(0.3)
        assert watch.alive() == [True, True]


@windows
@pytest.mark.parametrize("owner_case", ["another-live-process", "this-process"])
def test_windows_orphan_sweep_leaves_a_live_owners_child_alone(tmp_path, monkeypatch, fresh_state, reaper,
                                                              owner_case):
    exe = _claude_exe(tmp_path / "bin")
    child, grandchild, watch = _spawn(reaper, tmp_path / "work", exe)
    if owner_case == "this-process":
        owner = (os.getpid(), procs.process_identity(os.getpid()))
    else:
        owner_proc = _sleeper(reaper)
        owner = (owner_proc.pid, procs.process_identity(owner_proc.pid))
    record = _orphan_record(child, procs.process_identity(child), str(exe), owner)
    assert _sweep(tmp_path, record, keep=True) == [_messages().orphan_not_stale("worker", child)]
    time.sleep(0.3)
    assert watch.alive() == [True, True]
    # A session's own end on the same key: another live owner's record is
    # kept, this process's own is removed.
    children.clear_sidecar(tmp_path, "worker")
    assert children.sidecar_path(tmp_path, "worker").exists() is (owner_case == "another-live-process")
    if owner_case == "another-live-process":
        # Positive control: once the owner is gone, the same record is swept.
        owner_proc.kill()
        owner_proc.wait(timeout=10)
        assert _sweep(tmp_path, record) == [_messages().orphan_killed("worker", child)]
        watch.wait_dead()


@windows
def test_windows_orphan_sweep_declines_a_sidecar_that_is_not_stale(tmp_path, fresh_state, reaper):
    exe = _claude_exe(tmp_path / "bin")
    child, grandchild, watch = _spawn(reaper, tmp_path / "work", exe)
    record = _orphan_record(child, procs.process_identity(child), str(exe), _gone_owner(reaper))
    record["started_at"] = time.time() + 3600  # written after this process started
    assert _sweep(tmp_path, record) == [_messages().orphan_not_stale("worker", child)]
    assert watch.alive() == [True, True]


@windows
def test_windows_orphan_sweep_keeps_the_record_when_the_kill_is_not_confirmed(tmp_path, monkeypatch, fresh_state,
                                                                             reaper):
    exe = _claude_exe(tmp_path / "bin")
    child, grandchild, watch = _spawn(reaper, tmp_path / "work", exe)
    record = _orphan_record(child, procs.process_identity(child), str(exe), _gone_owner(reaper))
    failure = TimeoutError("injected: still has processes after 5 s")
    monkeypatch.setattr(procs, "terminate_contained", Mock(side_effect=failure))
    logs = _sweep(tmp_path, record, keep=True)
    assert logs == [_registered_messages().terminate_failed.format(pid=child, exc=failure)]


@windows
def test_windows_orphan_sweep_ends_a_job_an_interruption_carries(tmp_path, monkeypatch, fresh_state, reaper):
    """An interruption after the leftover joined the sweep's job: the job
    carried on the interruption is ended (and leaves the primitive's
    unclaimed list) before the interruption propagates."""
    from self_learn.primitives import _procs_windows as windows_backend

    exe = _claude_exe(tmp_path / "bin")
    child, grandchild, watch = _spawn(reaper, tmp_path / "work", exe)
    record = _orphan_record(child, procs.process_identity(child), str(exe), _gone_owner(reaper))
    children.sidecar_path(tmp_path, "worker").write_text(json.dumps(record), encoding="utf-8")
    carried = []
    real_contain = procs.contain_child

    def contain(pid, *, expect=None):
        try:
            return real_contain(pid, expect=expect)
        except KeyboardInterrupt as exc:
            carried.append(exc.contained_child)
            raise

    monkeypatch.setattr(windows_backend, "_process_parents", Mock(side_effect=KeyboardInterrupt))
    monkeypatch.setattr(procs, "contain_child", contain)
    with pytest.raises(KeyboardInterrupt):
        children.sweep_orphans(tmp_path, "worker", lambda line: None, pid_alive=procs.pid_alive,
                               messages=_messages(), process_start=time.time())
    assert carried and carried[0] not in windows_backend.unclaimed and carried[0].released
    _wait_for(lambda: watch.alive()[0] is False)


@windows
def test_windows_session_end_ends_a_job_an_interruption_carries(tmp_path, monkeypatch, fresh_state, reaper):
    """The session's end, containing by the identity read at spawn: an
    interruption after the child joined ends the carried job, then
    propagates."""
    from self_learn.primitives import _procs_windows as windows_backend

    child, grandchild, watch = _spawn(reaper, tmp_path / "work", _BASE)
    session = cw.Session(lambda line: None)
    session.pid, session.identity = child, procs.process_identity(child)
    carried = []
    real_contain = procs.contain_child

    def contain(pid, *, expect=None):
        assert expect == session.identity, "the session's end contains only the identity read at spawn"
        try:
            return real_contain(pid, expect=expect)
        except KeyboardInterrupt as exc:
            carried.append(exc.contained_child)
            raise

    monkeypatch.setattr(windows_backend, "_process_parents", Mock(side_effect=KeyboardInterrupt))
    monkeypatch.setattr(procs, "contain_child", contain)
    with pytest.raises(KeyboardInterrupt):
        cw._end(session, lambda line: None)
    assert carried and carried[0] not in windows_backend.unclaimed and carried[0].released
    _wait_for(lambda: watch.alive()[0] is False)


@windows
def test_windows_session_end_leaves_a_pid_that_is_no_longer_the_child(tmp_path, monkeypatch, fresh_state, reaper):
    """The session's end with no handle: the PID now names a process with
    another creation time (a reused PID). The job is made only on the identity
    read at spawn, so nothing is contained or killed."""
    child, grandchild, watch = _spawn(reaper, tmp_path / "work", _BASE)
    live = procs.process_identity(child)
    session = cw.Session(lambda line: None)
    session.pid, session.identity = child, procs.ProcessIdentity(image=live.image, created=live.created - 1)
    terminate = Mock(wraps=procs.terminate_contained)
    monkeypatch.setattr(procs, "terminate_contained", terminate)
    assert cw._end(session, lambda line: None) is True
    assert terminate.call_args.args == (None,)
    time.sleep(0.3)
    assert watch.alive() == [True, True]


# --------------------------------------------------------------------------
# Windows: self-learn killed abruptly, and a second command beside a first
# --------------------------------------------------------------------------


def launcher_main(argv):
    """The test's stand-in for self-learn: run one session through the real
    backend with the spawning client, publish a report once the child is
    contained, and hang until killed. Modes: ``contained`` (everything real),
    ``self-only`` (no per-session job), ``child-only`` (no self job),
    ``uncontained`` (no containment at all: the control)."""
    import win32api
    import win32con
    import win32job

    from self_learn.invocation_sdk import backend
    from self_learn.primitives import _procs_windows as windows_backend

    mode, out, exe, home = argv[0], Path(argv[1]), Path(argv[2]), Path(argv[3])
    order = []
    real_self = procs.contain_self
    procs.contain_self = lambda: order.append("contain_self") or (real_self() if mode != "child-only" else True)
    if mode == "self-only":
        procs.contain_child = lambda pid, expect=None: None
    if mode == "uncontained":
        cw._CONTAINMENT.clear()

    def on_drive(client):
        child = client.pids[0]
        opened = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, child)
        try:
            in_self = (bool(windows_backend._self_job)
                       and bool(win32job.IsProcessInJob(opened, windows_backend._self_job[0])))
        finally:
            win32api.CloseHandle(opened)
        entry = cw.CONTAINED.get(child)
        report = {"pids": client.pids, "order": order, "in_self_job": in_self,
                  "contained": entry is not None and entry.handle is not None, "launcher": os.getpid()}
        temp = Path(str(out) + ".tmp")
        temp.write_text(json.dumps(report), encoding="utf-8")
        os.replace(temp, out)

    client = SpawningClient(exe, out.parent / "work", [], hang=True, on_drive=on_drive, order=order)
    backend.ClaudeSDKClient = lambda options: client
    backend.SdkBackend().write_session(make_spec(home, log=lambda line: None, timeout=600.0))


_LAUNCHER = r"""
import site, sys
site.addsitedir(sys.argv[1])
sys.path.insert(0, sys.argv[2])
import test_windows_sdk_lifecycle as kit
kit.launcher_main(sys.argv[3:])
"""


def _launch(tmp_path, reaper, mode):
    exe = _claude_exe(tmp_path / "bin")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    out = tmp_path / "report.json"
    env = {**_standin_env(), "SELF_LEARN_HOME": str(home), "XDG_CACHE_HOME": str(tmp_path / "cache"),
           "SELF_LEARN_SDK_CLI_PATH": str(exe)}
    env.pop("PYTHONHOME")  # the launcher is the base interpreter itself
    launcher = subprocess.Popen([_BASE, "-u", "-c", _LAUNCHER, sysconfig.get_paths()["purelib"],
                                 str(Path(__file__).parent), mode, str(out), str(exe), str(home)], env=env)

    def cleanup():
        if launcher.poll() is None:
            _kill_tree(launcher.pid)
            launcher.kill()
        launcher.wait(timeout=10)

    reaper.append(cleanup)
    _wait_for(lambda: out.exists() or launcher.poll() is not None, 60)
    assert out.exists(), f"the launcher exited {launcher.returncode} before reporting"
    report = json.loads(out.read_text(encoding="utf-8"))
    watch = _Watch(report["pids"])
    reaper.append(watch.kill)
    return launcher, report, watch, home, tmp_path / "cache"


@windows
@pytest.mark.parametrize("mode", ["contained", "self-only", "child-only", "uncontained"])
def test_windows_abrupt_death_of_self_learn_leaves_no_survivor(tmp_path, reaper, mode):
    launcher, report, watch, _home, _cache = _launch(tmp_path, reaper, mode)
    assert report["launcher"] == launcher.pid
    assert all(watch.alive()), "nothing may die before self-learn does"
    assert report["order"] == ["contain_self", "connect"] or mode == "uncontained"
    assert report["in_self_job"] is (mode in ("contained", "self-only"))
    assert report["contained"] is (mode in ("contained", "child-only"))
    _terminate_pid(launcher.pid)
    launcher.wait(timeout=10)
    if mode == "uncontained":
        time.sleep(0.5)
        assert watch.alive() == [True, True], "control: without containment both survive"
    else:
        watch.wait_dead()


@windows
def test_windows_a_second_command_leaves_the_first_commands_session_alone(tmp_path, monkeypatch, fresh_state,
                                                                          reaper):
    """Two owners: a first self-learn (the launcher) is in a live session; this
    process, a second command on the same surface, sweeps before its own
    session. The first's child is not touched and its record is kept."""
    from self_learn import worker

    launcher, report, watch, home, cache = _launch(tmp_path, reaper, "contained")
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    cache_dir = worker.cache_dir()
    record = children.read_sidecar(cache_dir, "analyst")
    launcher_identity = procs.process_identity(launcher.pid)
    assert record["owner"] == {"pid": launcher.pid, "image": launcher_identity.image,
                               "created": launcher_identity.created}
    logs = []
    # An anchor in the future, so only the owner check can decline.
    children.sweep_orphans(cache_dir, "analyst", logs.append, pid_alive=procs.pid_alive,
                           messages=_messages(), process_start=time.time() + 3600)
    assert logs == [_messages().orphan_not_stale("analyst", report["pids"][0])]
    time.sleep(0.3)
    assert watch.alive() == [True, True]
    assert children.read_sidecar(cache_dir, "analyst") == record


# --------------------------------------------------------------------------
# Windows: which Claude Code program self-learn hands the SDK, and the doctor
# --------------------------------------------------------------------------


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


@pytest.fixture
def cli_dirs(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.delenv("SELF_LEARN_SDK_CLI_PATH", raising=False)
    monkeypatch.delenv("SELF_LEARN_SDK_PREFER_INSTALLED_CLI", raising=False)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return tmp_path, profile, cwd


@windows
def test_windows_cli_search_refuses_a_cmd_shim_and_finds_the_exe(cli_dirs, monkeypatch):
    tmp_path, profile, cwd = cli_dirs
    shim = _touch(tmp_path / "npm" / "claude.cmd")
    exe = _touch(tmp_path / "native" / "claude.exe")
    monkeypatch.setenv("PATH", os.pathsep.join([str(shim.parent), str(exe.parent)]))
    # Control: a plain PATH search finds the shim first.
    assert os.path.normcase(shutil.which("claude")) == os.path.normcase(str(shim))
    assert provider._installed_cli_path() == (str(exe), "installed (PATH)")

    # Shim only: nothing, and the reason names the shim passed over.
    monkeypatch.setenv("PATH", str(shim.parent))
    found, why = provider._installed_cli_path()
    assert found is None and str(shim) in why and "batch shim" in why
    # ... until the native installer's place has one.
    native = _touch(profile / ".local" / "bin" / "claude.exe")
    assert provider._installed_cli_path() == (str(native), f"installed ({native})")


@windows
def test_windows_cli_search_never_looks_in_the_current_folder(cli_dirs, monkeypatch):
    tmp_path, profile, cwd = cli_dirs
    planted = _touch(cwd / "claude.exe")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join([str(empty), ".", "relative\\bin", "\\rooted-no-drive"]))
    # Control: shutil.which on Windows searches the current folder first.
    assert shutil.which("claude.exe") is not None
    assert os.path.samefile(shutil.which("claude.exe"), planted)
    found, why = provider._installed_cli_path()
    assert found is None and "no native claude.exe" in why


@windows
def test_windows_cli_search_skips_network_folders_and_an_unresolvable_home(cli_dirs, monkeypatch):
    tmp_path, profile, cwd = cli_dirs
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join(["\\\\unreachable-server\\share\\bin", str(local),
                                                "//unreachable-server/share/bin"]))
    assert provider._windows_path_dirs() == [str(local)]
    # No resolvable home: the search answers nothing (with its reason) and
    # the sdk's own program stands.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no home"))))
    found, why = provider._installed_cli_path()
    assert found is None and "no home folder resolved" in why
    bundled = str(tmp_path / "sdk" / "_bundled" / "claude.exe")
    monkeypatch.setattr(provider, "_resolve_sdk_cli_path", lambda: (bundled, ""))
    choice = provider.resolve_cli_choice(None)
    assert (choice.path, choice.sdk_default) == (None, bundled)


@windows
def test_windows_cli_search_refuses_a_path_through_a_batch_named_folder(cli_dirs, monkeypatch):
    tmp_path, profile, cwd = cli_dirs
    inside = _touch(tmp_path / "tools.cmd" / "claude.exe")
    monkeypatch.setenv("PATH", str(inside.parent))
    found, why = provider._installed_cli_path()
    assert found is None and "named like a batch file" in why
    later = _touch(tmp_path / "ok" / "claude.exe")
    monkeypatch.setenv("PATH", os.pathsep.join([str(inside.parent), str(later.parent)]))
    assert provider._installed_cli_path() == (str(later), "installed (PATH)")


@windows
def test_windows_doctor_names_the_program_or_why_there_is_none(cli_dirs, monkeypatch):
    tmp_path, profile, cwd = cli_dirs
    bundled = str(tmp_path / "sdk" / "_bundled" / "claude.exe")
    monkeypatch.setattr(provider, "_resolve_sdk_cli_path", lambda: (bundled, ""))
    exe = _touch(tmp_path / "native" / "claude.exe")
    monkeypatch.setenv("PATH", str(exe.parent))
    choice = provider.resolve_cli_choice(None)
    assert (choice.path, choice.rule) == (str(exe), "installed (PATH)")
    assert provider._cli_choice_text(choice) == f"cli={exe} chosen by installed (PATH)"

    shim = _touch(tmp_path / "npm" / "claude.cmd")
    monkeypatch.setenv("PATH", str(shim.parent))
    choice = provider.resolve_cli_choice(None)
    assert choice.path is None and choice.sdk_default == bundled
    text = provider._cli_choice_text(choice)
    assert f"the sdk runs {bundled}" in text and str(shim) in text

    # The sdk's own answer is a shim it would refuse: said so, and no
    # program is left for the doctor's --version probe to run.
    monkeypatch.setattr(provider, "_resolve_sdk_cli_path", lambda: (str(shim), ""))
    choice = provider.resolve_cli_choice(None)
    assert choice.path is None and choice.sdk_default is None
    assert "batch shim it refuses to start" in choice.rule and "batch shim it refuses" in choice.sdk_reason
    assert provider._operative_cli_version(None) == (None, choice.sdk_reason)

    # The opt-out keeps the sdk's own order, as on POSIX.
    monkeypatch.setenv("SELF_LEARN_SDK_PREFER_INSTALLED_CLI", "0")
    assert provider.resolve_cli_choice(None).rule == "sdk default order (sdk.prefer_installed_cli is false)"


@windows
@pytest.mark.parametrize("route", ["explicit", "opt-out", "control-exe"])
def test_windows_doctor_never_runs_a_batch_shim(cli_dirs, monkeypatch, route):
    tmp_path, profile, cwd = cli_dirs
    shim = _touch(tmp_path / "npm" / "claude.cmd")
    exe = _touch(tmp_path / "native" / "claude.exe")
    ran = []

    def recording_run(argv, **kwargs):
        ran.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="9.9.9 (Claude Code)\n", stderr="")

    monkeypatch.setattr(provider.subprocess, "run", recording_run)
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    if route == "explicit":
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(shim))
    elif route == "opt-out":
        monkeypatch.setenv("SELF_LEARN_SDK_PREFER_INSTALLED_CLI", "0")
        monkeypatch.setattr(provider, "_resolve_sdk_cli_path", lambda: (str(shim), ""))
    else:
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(exe))
    version, reason = provider._operative_cli_version(None)
    if route == "control-exe":
        assert (version, ran) == ("9.9.9", [[str(exe), "--version"]])
    else:
        assert ran == [] and version is None
        assert reason == f"resolved cli {shim} is a .bat/.cmd batch script, which the sdk refuses to run"


@windows
def test_windows_bundled_claude_exe_answers_version():
    """Smoke check of the copy the Windows wheel bundles: ``--version`` only,
    no login, no model call."""
    import claude_agent_sdk

    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude.exe"
    assert bundled.is_file(), "the win_amd64 wheel is expected to bundle claude.exe"
    assert not provider._windows_batch_path(str(bundled))
    result = subprocess.run([str(bundled), "--version"], capture_output=True, text=True, timeout=120)
    print("BUNDLED", result.returncode, result.stdout.strip(), result.stderr.strip()[:200])
    assert result.returncode == 0, result.stderr
    assert provider._parse_cli_version(result.stdout.split()[0]) is not None, result.stdout


@windows
def test_windows_sessions_run_on_the_proactor_event_loop():
    """The SDK's subprocess pipes need asyncio's Proactor loop on Windows;
    `run_sync` relies on the default policy giving one."""
    from self_learn.invocation_sdk import backend

    async def loop_type():
        return type(asyncio.get_running_loop()).__name__

    assert backend.run_sync(loop_type) == "ProactorEventLoop"


# --------------------------------------------------------------------------
# Both platforms: the batch rule is the SDK's own
# --------------------------------------------------------------------------


_BATCH_CORPUS = [
    "C:\\a\\claude.exe", "C:\\a\\claude.cmd", "C:\\a\\claude.CMD", "C:\\a\\claude.bat",
    "C:\\a\\claude.cmd.", "C:\\a\\claude.cmd \\..", "C:\\x.cmd\\claude.exe", "C:\\a\\claude:evil.cmd",
    "C:\\a\\claude.cmd:stream", "C:claude.cmd", "C:/a/b/claude.exe", "\\\\server\\share\\claude.exe",
    ".cmd", "C:\\a\\claude.cmdx", "C:\\a\\claude.exe.cmd",
]


def test_batch_rule_matches_the_sdks_own(monkeypatch):
    from claude_agent_sdk._internal.transport import subprocess_cli

    monkeypatch.setattr(subprocess_cli.platform, "system", lambda: "Windows")
    sdk_rule = subprocess_cli.SubprocessCLITransport._is_windows_batch_cli
    verdicts = [(path, provider._windows_batch_path(path), sdk_rule(path)) for path in _BATCH_CORPUS]
    assert [v for v in verdicts if v[1] != v[2]] == []
    # Positive control: the corpus has both verdicts.
    assert {v[1] for v in verdicts} == {True, False}


# --------------------------------------------------------------------------
# Linux: none of the Windows code is reached, or loaded
# --------------------------------------------------------------------------


@linux
def test_linux_never_reaches_the_windows_branches(tmp_path, monkeypatch):
    import signal

    from self_learn.invocation_sdk import backend

    assert not hasattr(backend, "_windows_procs"), "the Windows registration ran on Linux"
    spy = Mock()
    monkeypatch.setattr(cw, "_CONTAINMENT", [(spy, Mock())])
    monkeypatch.setattr(cw, "CONTAINED", {})
    # Positive control: the spy is what the Windows code would use.
    assert cw.containment()[0] is spy

    monkeypatch.setattr(children.time, "time", lambda: 1_726_000_000.0)
    children.write_sidecar(tmp_path, "worker", 4242, "claude")
    assert children.sidecar_path(tmp_path, "worker").read_bytes() == (
        b'{"pid": 4242, "started_at": 1726000000.0, "cli": "claude"}'
    )

    calls = []
    monkeypatch.setattr(teardown.os, "getpgid", lambda pid: 100)
    monkeypatch.setattr(teardown.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    teardown.kill_child(4242, lambda line: None, lambda pid: True)
    assert calls == [(4242, signal.SIGKILL)]

    # A live-looking PID with no /proc entry: Linux declines on the /proc
    # read, where the Windows branch would have asked the spy instead.
    absent = 2**31 - 7
    record = {"pid": absent, "started_at": 0.0, "cli": "claude", "identity": {"image": "x", "created": 1}}
    children.sidecar_path(tmp_path, "worker").write_text(json.dumps(record), encoding="utf-8")
    logs = []
    children.sweep_orphans(tmp_path, "worker", logs.append, pid_alive=lambda pid: True,
                           messages=_messages(), process_start=time.time())
    assert logs == [_messages().orphan_uncorroborated("worker", absent)]
    assert not children.sidecar_path(tmp_path, "worker").exists()

    async def ladder():
        await teardown.run_kill_ladder(FakeSdkClient(pid=None), None, lambda line: None, kill_secs=1.0,
                                       interrupt_grace_secs=None, loop_closing=True,
                                       pid_alive=lambda pid: False, messages=_messages())
    asyncio.run(ladder())

    monkeypatch.setattr(provider, "_installed_cli_path_windows", Mock(side_effect=AssertionError))
    monkeypatch.setattr(provider, "_windows_cli_choice", Mock(side_effect=AssertionError))
    monkeypatch.setattr(provider, "_resolve_sdk_cli_path", lambda: ("/sdk/claude", ""))
    monkeypatch.delenv("SELF_LEARN_SDK_CLI_PATH", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    provider._installed_cli_path()
    provider.resolve_cli_choice(None)
    assert spy.mock_calls == []


@linux
def test_linux_never_loads_the_windows_module():
    """A fresh interpreter imports the backend, runs the sidecar, sweep and
    kill paths, and never loads `_containment_windows` (so Linux import does
    no new work)."""
    script = textwrap.dedent(r"""
        import asyncio, sys, tempfile, time
        from pathlib import Path
        from self_learn.invocation_sdk import backend, lifecycle
        from self_learn.sdksession import children, teardown
        from self_learn.sdksession.fake import FakeSdkClient
        loaded_after_import = "self_learn.sdksession._containment_windows" in sys.modules
        cache = Path(tempfile.mkdtemp())
        children.write_sidecar(cache, "worker", 2**31 - 7, "claude")
        children.sweep_orphans(cache, "worker", lambda line: None, pid_alive=lambda pid: False,
                               messages=lifecycle.CLI_SHUTDOWN_MESSAGES, process_start=time.time())
        children.clear_sidecar(cache, "worker")
        teardown.kill_child(None, lambda line: None, lambda pid: False)
        async def ladder():
            await teardown.run_kill_ladder(FakeSdkClient(pid=None), None, lambda line: None, kill_secs=1.0,
                                           interrupt_grace_secs=None, loop_closing=True,
                                           pid_alive=lambda pid: False,
                                           messages=lifecycle.CLI_SHUTDOWN_MESSAGES)
        asyncio.run(ladder())
        print(loaded_after_import, "self_learn.sdksession._containment_windows" in sys.modules)
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["False", "False"]


def test_concurrent_first_self_job_attempts_are_serialized(monkeypatch):
    """Both platforms (the once-per-process rule is plain Python): a second
    caller waits until the first caller's attempt has finished."""
    release, entered = threading.Event(), threading.Event()
    facade = Mock()

    def slow_self():
        entered.set()
        release.wait(10)
        return True

    facade.contain_self.side_effect = slow_self
    monkeypatch.setattr(cw, "_CONTAINMENT", [(facade, Mock())])
    monkeypatch.setattr(cw, "_SELF_TRIED", [])
    done = {}

    def caller(name):
        cw.contain_self(lambda line: None)
        done[name] = time.monotonic()

    first = threading.Thread(target=caller, args=("first",))
    first.start()
    assert entered.wait(10)
    second = threading.Thread(target=caller, args=("second",))
    second.start()
    time.sleep(0.3)
    assert "second" not in done, "the second caller went on before the first attempt finished"
    released = time.monotonic()
    release.set()
    first.join(10)
    second.join(10)
    assert done["second"] >= released and facade.contain_self.call_count == 1


def test_a_handle_less_session_never_takes_another_sessions_job(monkeypatch):
    """Both platforms (plain bookkeeping, with a stand-in for the process
    calls): a session whose containment was refused is not listed by PID, so
    neither the last rung nor its own end can reach the job another session
    later holds for a process with that number."""
    facade = Mock()
    facade.contain_child.side_effect = PermissionError(13, "refused")
    facade.process_identity.return_value = None
    messages = cw.ContainmentMessages(**{name: "{pid} {exc}" for name in (
        "self_failed", "contain_refused", "contain_partial", "contain_incomplete", "terminate_failed",
        "sidecar_failed", "sweep_failed")})
    monkeypatch.setattr(cw, "_CONTAINMENT", [(facade, messages)])
    monkeypatch.setattr(cw, "CONTAINED", {})
    monkeypatch.setattr(cw, "_SESSIONS", {})
    refused_client, logs = object(), []
    refused = cw.Session(logs.append)
    cw._SESSIONS[id(refused_client)] = refused
    cw._contain(refused, 4242)
    assert logs == ["4242 [Errno 13] refused"] and cw.CONTAINED == {}
    # Another session now holds a real job for a process with that number.
    other, job = cw.Session(lambda line: None), object()
    other.pid = 4242
    cw._hold(other, job)
    asyncio.run(cw.close_session(refused_client, logs.append))
    assert cw.CONTAINED == {4242: other} and other.handle is job
    facade.terminate_contained.assert_not_called()
