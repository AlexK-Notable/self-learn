"""S-NEXT-w6-sdk. The Claude Code child's lifecycle on Windows.

self-learn's model-backed commands run Claude Code through the Agent SDK,
which spawns the child itself. On Windows self-learn now puts itself in a
kill-on-close job before the first child is spawned, puts the child in a job
of its own as soon as its PID is known, records the child's identity (image
path and creation time) in the sidecar, ends the child's job at the kill
ladder's last rung, and sweeps a leftover child on a later run only when its
live identity is exactly the recorded one. The installed-CLI search hands the
SDK only a native ``claude.exe``.

Windows tests drive the real code with the fake SDK client
(``sdksession/fake.py``), made to spawn a Python stand-in for ``claude.exe``
(a copy of the interpreter named ``claude.exe``) that spawns a grandchild.
Linux tests check that none of the Windows branches is reached there.
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
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from self_learn import provider
from self_learn.primitives import procs
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


def _claude_exe(directory: Path) -> Path:
    """A copy of the base interpreter named ``claude.exe``, with the DLLs it
    loads from its own folder; run it with :func:`_standin_env`."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "claude.exe"
    shutil.copy2(_BASE, target)
    for dll in Path(_BASE).parent.glob("*.dll"):
        shutil.copy2(dll, directory / dll.name)
    return target


def _standin_env() -> dict[str, str]:
    return {**os.environ, "PYTHONHOME": sys.base_prefix}


def _kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=60)


def _standin(directory: Path, exe: Path | str = _BASE, name: str = "standin"):
    """Start the stand-in under *exe*; return ``(Popen, (child, grandchild))``."""
    directory.mkdir(parents=True, exist_ok=True)
    ready = directory / name
    proc = subprocess.Popen([str(exe), "-u", "-c", textwrap.dedent(_STANDIN), str(ready), _BASE],
                            env=_standin_env())
    try:
        _wait_for(ready.exists)
    except BaseException:
        _kill_tree(proc.pid)
        proc.kill()
        raise
    child, grandchild = (int(pid) for pid in ready.read_text().split())
    return proc, (child, grandchild)


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
# The session kit: the fake SDK client made to spawn the stand-in at
# connect(), and a minimal session spec. Also used by the launcher below.
# --------------------------------------------------------------------------


class SpawningClient(FakeSdkClient):
    """`FakeSdkClient`, but `connect()` spawns the stand-in the way the real
    SDK spawns Claude Code, and the private PID chain names it."""

    def __init__(self, exe, workdir, *, messages=None, hang=False, on_drive=None, order=None):
        super().__init__(pid=0, messages=messages)
        self.exe, self.workdir, self.hang = exe, Path(workdir), hang
        self.on_drive, self.order = on_drive, order
        self.proc = None
        self.pids = None
        self.watch = None

    async def connect(self):
        await super().connect()
        if self.order is not None:
            self.order.append("connect")
        self.proc, self.pids = _standin(self.workdir, self.exe, name="session-standin")
        # Pinned at spawn, so a death is observed even after the last rung.
        self.watch = _Watch(self.pids)
        self._transport._process.pid = self.pids[0]

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
    registered = teardown.containment()
    assert registered is not None
    return registered[1]


@pytest.fixture
def session_env(tmp_path, monkeypatch):
    """A scratch ledger and cache, the stand-in ``claude.exe`` named as the
    program the session is handed, no self job for the test process (the
    launcher tests use the real one), and a clean containment registry."""
    from self_learn.invocation_sdk import backend

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    exe = _claude_exe(tmp_path / "bin")
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(exe))
    self_calls = []
    monkeypatch.setattr(procs, "contain_self", lambda: self_calls.append("contain_self") or True)
    monkeypatch.setattr(teardown, "_SELF_TRIED", [])
    monkeypatch.setattr(teardown, "CONTAINED", {})
    return backend, home, exe, self_calls


# --------------------------------------------------------------------------
# Windows: registration, the sidecar, the last rung
# --------------------------------------------------------------------------


@windows
def test_windows_backend_registers_the_procs_calls_on_import():
    from self_learn.invocation_sdk import backend

    registered = teardown.containment()
    assert registered is not None and registered[0] is procs
    assert backend._windows_procs is procs


@windows
def test_windows_sidecar_round_trips_the_contained_identity(tmp_path, monkeypatch):
    from self_learn.invocation_sdk import backend  # noqa: F401 - registers the procs calls

    monkeypatch.setattr(teardown, "CONTAINED", {})
    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        logs = []
        teardown.contain_session_child(child, logs.append)
        assert logs == [] and teardown.CONTAINED[child].handle is not None
        children.write_sidecar(tmp_path, "worker", child, "C:\\somewhere\\claude.exe")
        record = children.read_sidecar(tmp_path, "worker")
        assert set(record) == {"pid", "started_at", "cli", "identity"}
        assert record["pid"] == child and record["cli"] == "C:\\somewhere\\claude.exe"
        live = procs.process_identity(child)
        assert record["identity"] == {"image": live.image, "created": live.created}
        assert children._recorded_identity(record, procs) == live
        # A child whose containment found nothing records no identity, and
        # a later sweep never acts on it.
        teardown.CONTAINED[4242] = teardown._Contained(None, None)
        children.write_sidecar(tmp_path, "other", 4242, "")
        assert children.read_sidecar(tmp_path, "other")["identity"] is None
        del teardown.CONTAINED[4242]
        # The last rung ends the job even when pid_alive says the child is gone.
        teardown.kill_child(child, logs.append, lambda pid: False)
        watch.wait_dead()
        assert logs == [] and child not in teardown.CONTAINED
    finally:
        watch.kill()
        proc.wait(timeout=10)


@windows
def test_windows_last_rung_ends_the_grandchild_after_the_sdk_ended_the_child(tmp_path, monkeypatch):
    """The SDK's own teardown ends only Claude Code (TerminateProcess): its
    descendants live on. The last rung ends them through the job."""
    from self_learn.invocation_sdk import backend  # noqa: F401 - registers the procs calls

    monkeypatch.setattr(teardown, "CONTAINED", {})
    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        teardown.contain_session_child(child, lambda line: None)
        _terminate_pid(child)  # what the SDK's terminate() does
        _wait_for(lambda: watch.alive() == [False, True])
        time.sleep(0.3)
        assert watch.alive() == [False, True], "the grandchild must outlive the child alone"
        teardown.kill_child(child, lambda line: None, procs.pid_alive)
        watch.wait_dead()
    finally:
        watch.kill()
        proc.wait(timeout=10)


# --------------------------------------------------------------------------
# Windows: a whole session through the real backend with the fake client
# --------------------------------------------------------------------------


@windows
def test_windows_session_contains_the_child_and_teardown_kills_both(tmp_path, monkeypatch, session_env):
    from self_learn.invocation_sdk import lifecycle

    backend, home, exe, self_calls = session_env
    order = []
    monkeypatch.setattr(procs, "contain_self", lambda: order.append("contain_self") or True)
    seen = {}

    def on_drive(client):
        child = client.pids[0]
        entry = teardown.CONTAINED.get(child)
        seen["contained"] = entry is not None and entry.handle is not None
        seen["sidecar"] = children.read_sidecar(lifecycle.worker.cache_dir(), "analyst")
        seen["live"] = procs.process_identity(child)
        seen["alive"] = client.watch.alive()

    client = SpawningClient(exe, tmp_path / "work", messages=ok_messages(), on_drive=on_drive, order=order)
    monkeypatch.setattr(backend, "ClaudeSDKClient", lambda options: client)
    logs = []
    outcome = backend.SdkBackend().write_session(make_spec(home, log=logs.append))
    watch = client.watch
    try:
        assert outcome.ok, (outcome.failure, logs)
        assert outcome.child_pid == client.pids[0]
        assert order == ["contain_self", "connect"], "self containment must come before the spawn"
        assert seen["alive"] == [True, True] and seen["contained"]
        live = seen["live"]
        assert seen["sidecar"]["identity"] == {"image": live.image, "created": live.created}
        assert os.path.samefile(live.image, exe) and seen["sidecar"]["cli"] == str(exe)
        # The last rung ran when write_session returned: both are gone.
        assert watch.alive() == [False, False]
        assert teardown.CONTAINED == {}
        assert children.read_sidecar(lifecycle.worker.cache_dir(), "analyst") is None
        assert logs == [], logs  # a clean contained session logs nothing
    finally:
        watch.kill()
        client.proc.wait(timeout=10)


@windows
@pytest.mark.parametrize("fault", ["contain-raises", "contain-interrupted", "terminate-times-out", "self-refused"])
def test_windows_containment_trouble_never_fails_the_session(tmp_path, monkeypatch, session_env, fault):
    backend, home, exe, self_calls = session_env
    real_contain, real_terminate = procs.contain_child, procs.terminate_contained
    calls = {"contain": 0, "terminate": 0}

    def contain(pid, *, expect=None):
        calls["contain"] += 1
        if calls["contain"] == 1 and fault == "contain-raises":
            raise PermissionError(13, "injected refusal")
        handle = real_contain(pid, expect=expect)
        if calls["contain"] == 1 and fault == "contain-interrupted":
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
    client = SpawningClient(exe, tmp_path / "work", messages=ok_messages())
    monkeypatch.setattr(backend, "ClaudeSDKClient", lambda options: client)
    logs = []
    outcome = backend.SdkBackend().write_session(make_spec(home, log=logs.append))
    # A second session in the same process tries contain_self no more.
    second = SpawningClient(exe, tmp_path / "work2", messages=ok_messages())
    monkeypatch.setattr(backend, "ClaudeSDKClient", lambda options: second)
    again = backend.SdkBackend().write_session(make_spec(home, log=logs.append))
    try:
        assert outcome.ok and again.ok, (outcome.failure, again.failure, logs)
        messages = _registered_messages()
        child = client.pids[0]
        expected = {
            "contain-raises": messages.contain_failed.format(
                pid=child, exc=PermissionError(13, "injected refusal")),
            "contain-interrupted": messages.contain_failed.format(
                pid=child, exc=OSError(1, "injected interruption after the child joined")),
            "terminate-times-out": messages.terminate_failed.format(
                pid=child, exc=TimeoutError("injected: still has processes after 5 s")),
            "self-refused": messages.self_failed.format(exc=PermissionError(5, "injected self-job refusal")),
        }[fault]
        assert logs == [expected], logs
        # Whatever went wrong, the last rung still ended both sessions' trees.
        _wait_for(lambda: not any(client.watch.alive() + second.watch.alive()))
        if fault == "contain-raises":
            # No handle at spawn: the rung contained the recorded identity
            # again (expect=) and ended it.
            assert calls["contain"] == 3
        if fault == "contain-interrupted":
            # The handle the failing call carried was kept: the rung ended it
            # without containing anything again.
            assert calls["contain"] == 2
        assert teardown.CONTAINED == {}
    finally:
        for spawned in (client, second):
            if spawned.watch is not None:
                spawned.watch.kill()
                spawned.proc.wait(timeout=10)


# --------------------------------------------------------------------------
# Windows: the orphan sweep on a later run
# --------------------------------------------------------------------------


def _orphan_record(pid, identity, cli):
    return {"pid": pid, "started_at": 0.0, "cli": cli,
            "identity": None if identity is None else {"image": identity.image, "created": identity.created}}


def _sweep(cache, record):
    path = children.sidecar_path(cache, "worker")
    path.write_text(json.dumps(record), encoding="utf-8")
    logs = []
    children.sweep_orphans(cache, "worker", logs.append, pid_alive=procs.pid_alive,
                           messages=_messages(), process_start=time.time())
    assert not path.exists(), "every sweep outcome clears the sidecar"
    return logs


@windows
@pytest.mark.parametrize("case", ["leftover", "sdk-chose", "reused-pid", "predates-boot", "not-claude",
                                  "not-claude-no-cli", "claude-elsewhere", "no-identity"])
def test_windows_orphan_sweep_kills_only_a_true_leftover(tmp_path, monkeypatch, case):
    from self_learn.invocation_sdk import backend  # noqa: F401 - registers the procs calls
    from self_learn.primitives import _procs_windows as windows_backend

    monkeypatch.setattr(teardown, "CONTAINED", {})
    exe = _claude_exe(tmp_path / "bin")
    image = _BASE if case in ("not-claude", "not-claude-no-cli") else exe
    proc, (child, grandchild) = _standin(tmp_path / "work", image)
    watch = _Watch([child, grandchild])
    try:
        identity = procs.process_identity(child)
        cli = {"sdk-chose": "", "not-claude-no-cli": "",
               "claude-elsewhere": str(_claude_exe(tmp_path / "other"))}.get(case, str(exe))
        record = _orphan_record(child, None if case == "no-identity" else identity, cli)
        if case == "reused-pid":
            # Same PID, a creation time one tick later, at the real call.
            real = windows_backend._get_process_times

            def later(handle, created, *rest):
                ok = real(handle, created, *rest)
                value = windows_backend._filetime(created._obj) + 1
                created._obj.dwLowDateTime, created._obj.dwHighDateTime = value & 0xFFFFFFFF, value >> 32
                return ok
            monkeypatch.setattr(windows_backend, "_get_process_times", later)
        if case == "predates-boot":
            # An uptime of zero puts the boot after the recorded creation time.
            monkeypatch.setattr(windows_backend, "_tick_count", lambda: 0)
        messages = _messages()
        logs = _sweep(tmp_path, record)
        if case in ("leftover", "sdk-chose"):
            assert logs == [messages.orphan_killed("worker", child)]
            watch.wait_dead()
            assert teardown.CONTAINED == {}
        else:
            line = (messages.orphan_uncorroborated if case in ("predates-boot", "no-identity")
                    else messages.orphan_cmdline_mismatch)
            assert logs == [line("worker", child)]
            time.sleep(0.3)
            assert watch.alive() == [True, True]
    finally:
        watch.kill()
        proc.wait(timeout=10)


@windows
def test_windows_orphan_sweep_declines_a_sidecar_that_is_not_stale(tmp_path, monkeypatch):
    from self_learn.invocation_sdk import backend  # noqa: F401 - registers the procs calls

    monkeypatch.setattr(teardown, "CONTAINED", {})
    exe = _claude_exe(tmp_path / "bin")
    proc, (child, grandchild) = _standin(tmp_path / "work", exe)
    watch = _Watch([child, grandchild])
    try:
        record = _orphan_record(child, procs.process_identity(child), str(exe))
        record["started_at"] = time.time() + 3600  # written after this process started
        assert _sweep(tmp_path, record) == [_messages().orphan_not_stale("worker", child)]
        assert watch.alive() == [True, True]
    finally:
        watch.kill()
        proc.wait(timeout=10)


# --------------------------------------------------------------------------
# Windows: self-learn killed abruptly in the middle of a session
# --------------------------------------------------------------------------


def launcher_main(argv):
    """The test's stand-in for self-learn: run one session through the real
    backend with the spawning fake client, publish a report once the child is
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
        teardown._CONTAINMENT.clear()

    def on_drive(client):
        child = client.pids[0]
        opened = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, child)
        try:
            in_self = (bool(windows_backend._self_job)
                       and bool(win32job.IsProcessInJob(opened, windows_backend._self_job[0])))
        finally:
            win32api.CloseHandle(opened)
        entry = teardown.CONTAINED.get(child)
        report = {"pids": client.pids, "order": order, "in_self_job": in_self,
                  "contained": entry is not None and entry.handle is not None, "launcher": os.getpid()}
        temp = Path(str(out) + ".tmp")
        temp.write_text(json.dumps(report), encoding="utf-8")
        os.replace(temp, out)

    client = SpawningClient(exe, out.parent / "work", hang=True, on_drive=on_drive, order=order)
    backend.ClaudeSDKClient = lambda options: client
    backend.SdkBackend().write_session(make_spec(home, log=lambda line: None, timeout=600.0))


_LAUNCHER = r"""
import site, sys
site.addsitedir(sys.argv[1])
sys.path.insert(0, sys.argv[2])
import test_windows_sdk_lifecycle as kit
kit.launcher_main(sys.argv[3:])
"""


@windows
@pytest.mark.parametrize("mode", ["contained", "self-only", "child-only", "uncontained"])
def test_windows_abrupt_death_of_self_learn_leaves_no_survivor(tmp_path, mode):
    exe = _claude_exe(tmp_path / "bin")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "report.json"
    env = {**_standin_env(), "SELF_LEARN_HOME": str(home), "XDG_CACHE_HOME": str(tmp_path / "cache"),
           "SELF_LEARN_SDK_CLI_PATH": str(exe)}
    env.pop("PYTHONHOME")  # the launcher is the base interpreter itself
    launcher = subprocess.Popen([_BASE, "-u", "-c", _LAUNCHER, sysconfig.get_paths()["purelib"],
                                 str(Path(__file__).parent), mode, str(out), str(exe), str(home)], env=env)
    try:
        _wait_for(lambda: out.exists() or launcher.poll() is not None, 60)
        assert out.exists(), f"the launcher exited {launcher.returncode} before reporting"
    except BaseException:
        _kill_tree(launcher.pid)
        raise
    report = json.loads(out.read_text(encoding="utf-8"))
    watch = _Watch(report["pids"])
    try:
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
    finally:
        watch.kill()


# --------------------------------------------------------------------------
# Windows: which Claude Code program self-learn hands the SDK
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

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
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
# Linux: none of the Windows branches is reached
# --------------------------------------------------------------------------


@linux
def test_linux_never_reaches_the_windows_branches(tmp_path, monkeypatch):
    import signal

    from self_learn.invocation_sdk import backend

    assert not hasattr(backend, "_windows_procs"), "the Windows registration ran on Linux"
    spy = Mock()
    monkeypatch.setattr(teardown, "_CONTAINMENT", [(spy, Mock())])
    monkeypatch.setattr(teardown, "CONTAINED", {})
    # Positive control: the spy is what the Windows branches would use.
    assert teardown.containment()[0] is spy

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

    monkeypatch.setattr(provider, "_installed_cli_path_windows", Mock(side_effect=AssertionError))
    monkeypatch.setattr(provider, "_windows_cli_choice", Mock(side_effect=AssertionError))
    monkeypatch.setattr(provider, "_resolve_sdk_cli_path", lambda: ("/sdk/claude", ""))
    monkeypatch.delenv("SELF_LEARN_SDK_CLI_PATH", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    provider._installed_cli_path()
    provider.resolve_cli_choice(None)
    assert spy.mock_calls == []
