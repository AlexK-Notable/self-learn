"""S-NEXT-w7-procs. Detached background runs and asyncio children the caller owns.

Two more ways self-learn starts programs, behind the procs facade:
``spawn_detached`` (the worker, the miner and the overseer's notifier start a
run that must outlive the command that started it) and ``async_owned_child``
with ``stop_owned``, ``terminate_owned`` and ``release_owned`` (the web UI's
verb runner and ask runner start asyncio children and stop their whole tree).

Linux tests prove each POSIX copy makes the call of the site it copies: the
CLI sites are run for real against a spy, and the web UI's calls and stop
sequences are taken from the UI's own source (its package is not installed in
the CLI's environment) and run against the same fakes as the facade. Windows
tests drive real processes: launchers in jobs that allow or forbid breakaway,
consoles shared or not, and Python stand-ins that report what they received.
"""

from __future__ import annotations

import __future__
import ast
import asyncio
import gc
import inspect
import json
import os
import signal
import subprocess
import sys
import sysconfig
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import self_learn
from self_learn.primitives import procs


windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows process contract")
linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux process contract")

#: The interpreter itself, not the venv redirector (on Windows a venv's
#: python.exe is a launcher whose PID differs from the Python it starts).
_BASE = getattr(sys, "_base_executable", sys.executable)
_PURELIB = sysconfig.get_paths()["purelib"]
_UI_SRC = Path(self_learn.__file__).resolve().parents[3] / "ui" / "src" / "self_learn_ui"
#: What a Python process exits with when a console control event ends it.
_STATUS_CONTROL_C_EXIT = 0xC000013A
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_CONSOLE = 0x00000010
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


def _python(script, *args, exe=_BASE):
    return [exe, "-u", "-c", textwrap.dedent(script), *map(str, args)]


def _wait_for(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "process observation timed out"
        time.sleep(0.02)


_PUBLISH = r"""
def publish(path, text):
    import os
    temp = str(path) + ".tmp"
    with open(temp, "w") as stream:
        stream.write(text)
    os.replace(temp, str(path))
"""


# ==========================================================================
# Linux: every POSIX copy makes the call of the site it was copied from
# ==========================================================================


#: Read before any test replaces subprocess.Popen with a spy.
_POPEN_SIGNATURE = inspect.signature(subprocess.Popen)


def _popen_arguments(args, kwargs):
    """A Popen call as the full argument set it binds to, defaults applied, so
    an argument left out and the same argument passed as its default compare
    equal. A file object is compared by what it is: name, mode and encoding."""
    bound = _POPEN_SIGNATURE.bind(*args, **kwargs)
    bound.apply_defaults()
    out = {}
    for name, value in bound.arguments.items():
        if hasattr(value, "fileno") and hasattr(value, "mode"):
            value = ("file", str(value.name), value.mode, getattr(value, "encoding", None))
        out[name] = value
    return out


def _spy_popen(monkeypatch):
    calls = []

    def popen(*args, **kwargs):
        stdout = kwargs.get("stdout")
        calls.append((args, kwargs, stdout))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def _scratch_cache(monkeypatch, tmp_path):
    home = tmp_path / "ledger"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return home


def _replay(monkeypatch, original, call):
    """Record the site's own Popen call, then make the facade call with the
    values the site computed; both must bind to the same arguments."""
    calls = _spy_popen(monkeypatch)
    original()
    assert len(calls) == 1
    (args, kwargs, out) = calls[0]
    expected = _popen_arguments(args, kwargs)
    assert not hasattr(out, "closed") or out.closed  # the site closed its log after the call
    calls.clear()
    result = call(args, kwargs)
    assert len(calls) == 1
    (fargs, fkwargs, fout) = calls[0]
    assert _popen_arguments(fargs, fkwargs) == expected
    assert not hasattr(fout, "closed") or fout.closed
    assert result == procs.DetachedChild(4242, None)
    return expected


@linux
def test_detached_copy_matches_worker_spawn_window(monkeypatch, tmp_path):
    from self_learn import worker

    home = _scratch_cache(monkeypatch, tmp_path)
    log_path = worker._p("worker.log")

    def facade(args, kwargs):
        return procs.spawn_detached(args[0], cwd=kwargs["cwd"], env=kwargs["env"], log_path=log_path)

    expected = _replay(monkeypatch, lambda: worker._spawn_window(home, no_push=True), facade)
    assert expected["start_new_session"] is True and expected["stderr"] == subprocess.STDOUT
    assert expected["stdout"] == ("file", str(log_path), "a", "utf-8") and expected["stdin"] is None
    assert expected["env"][worker.NO_PUSH_ENV] == "1"


@linux
def test_detached_copy_matches_miner_spawn_run(monkeypatch, tmp_path):
    from self_learn import miner

    home = _scratch_cache(monkeypatch, tmp_path)
    log_path = miner.miner_dir() / "miner.log"

    def facade(args, kwargs):
        return procs.spawn_detached(args[0], cwd=kwargs["cwd"], env=kwargs["env"], log_path=log_path)

    expected = _replay(monkeypatch, lambda: miner._spawn_run(home), facade)
    assert expected["args"][-3:] == ["run", "--trigger", "kick"]
    assert expected["stdout"] == ("file", str(log_path), "a", "utf-8")


@linux
def test_detached_copy_matches_overseer_notify(monkeypatch, tmp_path):
    from self_learn.overseer import notify

    home = _scratch_cache(monkeypatch, tmp_path)
    monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)
    monkeypatch.setattr(notify.worker, "_notifications_suppressed", lambda actual: False)
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/shim/self-learn-notify")

    def site():
        notify.send(home, "routine", "the steward is held", ["run-1"], kind=notify.POPUP_KIND)

    expected = _replay(monkeypatch, site, lambda args, kwargs: procs.spawn_detached(args[0]))
    assert (expected["stdin"], expected["stdout"], expected["stderr"]) == (subprocess.DEVNULL,) * 3
    assert (expected["cwd"], expected["env"], expected["start_new_session"]) == (None, None, True)


def _ui_tree(name):
    path = _UI_SRC / name
    assert path.is_file(), path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _ui_exec_calls(name):
    return [node for node in ast.walk(_ui_tree(name)) if isinstance(node, ast.Call)
            and ast.unparse(node.func) in ("create_subprocess_exec", "asyncio.create_subprocess_exec")]


_UI_ENV = {"SELF_LEARN_HOME": "/scratch/home", "PATH": "/usr/bin"}


@linux
@pytest.mark.parametrize("site", ["runner.py:0", "ask_runner.py:0", "ask_runner.py:1", "ask_runner.py:2"])
def test_async_copy_matches_each_ui_spawn(monkeypatch, site):
    """The keyword arguments of each ``create_subprocess_exec`` call in the web
    UI, evaluated from its source, bind to the same arguments as the call the
    facade makes when handed the same stdin, stdout, stderr and env."""
    name, index = site.split(":")
    assert len(_ui_exec_calls("runner.py")) == 1 and len(_ui_exec_calls("ask_runner.py")) == 3
    call = _ui_exec_calls(name)[int(index)]
    names = {"asyncio_subprocess": asyncio.subprocess, "full_env": _UI_ENV,
             "self": SimpleNamespace(_full_env=lambda: _UI_ENV)}
    keywords = {kw.arg: eval(compile(ast.Expression(kw.value), name, "eval"), names) for kw in call.keywords}
    assert set(keywords) <= {"env", "stdin", "stdout", "stderr", "start_new_session"}, keywords
    assert keywords["start_new_session"] is True

    seen = []

    async def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return "process"

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    passed = {key: keywords[key] for key in ("stdin", "stdout", "stderr") if key in keywords}
    assert asyncio.run(procs.async_owned_child("self-learn", "verb", env=keywords["env"], **passed)) == "process"
    [(args, kwargs)] = seen
    assert args == ("self-learn", "verb")
    signature = inspect.signature(asyncio.subprocess.create_subprocess_exec)

    def bound(kw):
        arguments = signature.bind("self-learn", **kw)
        arguments.apply_defaults()
        return arguments.arguments

    assert bound(kwargs) == bound(keywords)


class _FakeProc:
    def __init__(self, pid=4100, returncode=None):
        self.pid = pid
        self.returncode = returncode

    async def wait(self):  # never awaited: the recording wait_for decides
        return self.returncode


def _ui_stop_sequence(kind):
    """Compile the UI's own stop code from its source, in a namespace whose
    ``os`` and ``wait_for`` are the scenario's recorders."""
    if kind == "runner":
        tree = _ui_tree("runner.py")
        wanted = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name in ("_signal_group", "_terminate_then_kill")]
    else:
        tree = _ui_tree("ask_runner.py")
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RealAskRunner")
        wanted = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_signal_group"]
        wanted += [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_terminate"]
    assert len(wanted) == 2, [n.name for n in wanted]
    module = ast.Module(body=wanted, type_ignores=[])
    return compile(module, kind, "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True)


#: Windows has no SIGKILL; the table is only used by Linux tests.
_SIGKILL = getattr(signal, "SIGKILL", 9)
#: scenario -> (getpgid answer, which signals end the process, which signal
#: finds no process, whether it had exited before the call)
_SCENARIOS = {
    "exits-on-term": ("leader", {signal.SIGTERM}, None, False),
    "needs-kill": ("leader", {_SIGKILL}, None, False),
    "ignores-both": ("leader", set(), None, False),
    "gone-at-term": ("leader", set(), signal.SIGTERM, False),
    "gone-at-kill": ("leader", set(), _SIGKILL, False),
    "already-exited": ("leader", set(), None, True),
    "not-a-leader": ("other", {signal.SIGTERM}, None, False),
    "getpgid-lookup": ("lookup", set(), None, False),
}


def _recorders(scenario, proc, log):
    pgid_answer, killers, lost, _ = _SCENARIOS[scenario]
    state = {"dead": False}

    def getpgid(pid):
        log.append(("getpgid", pid))
        if pgid_answer == "lookup":
            raise ProcessLookupError(pid)
        return pid if pgid_answer == "leader" else 1

    def signaller(kind):
        def send(pid, sig):
            log.append((kind, pid, sig))
            if sig == lost:
                raise ProcessLookupError(pid)
            if sig in killers:
                state["dead"] = True
        return send

    async def wait_for(awaitable, timeout):
        awaitable.close()
        log.append(("wait", timeout))
        if state["dead"]:
            proc.returncode = -1
            return -1
        raise TimeoutError

    return getpgid, signaller("killpg"), signaller("kill"), wait_for


@linux
@pytest.mark.parametrize("site", ["runner", "ask"])
@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_stop_sequence_equals_the_ui(monkeypatch, site, scenario):
    """Signals, their targets and the waits between them, in order, for the
    UI's code and for ``terminate_owned`` (``wait_after_lost_kill=True`` for
    the ask runner, whose SIGKILL result is ignored)."""
    exited = _SCENARIOS[scenario][3]

    def run_ui():
        proc, log = _FakeProc(returncode=0 if exited else None), []
        getpgid, killpg, kill, wait_for = _recorders(scenario, proc, log)
        names = {"os": SimpleNamespace(getpgid=getpgid, killpg=killpg, kill=kill), "signal": signal,
                 "wait_for": wait_for, "asyncio": SimpleNamespace(wait_for=wait_for),
                 "TimeoutError": TimeoutError, "ProcessLookupError": ProcessLookupError}
        exec(_ui_stop_sequence(site), names)
        if site == "runner":
            asyncio.run(names["_terminate_then_kill"](proc, kill_grace=2.5))
        else:
            asyncio.run(names["_terminate"](SimpleNamespace(_kill_grace=2.5), proc))
        return log

    def run_facade():
        proc, log = _FakeProc(returncode=0 if exited else None), []
        getpgid, killpg, kill, wait_for = _recorders(scenario, proc, log)
        with monkeypatch.context() as patch:
            patch.setattr(os, "getpgid", getpgid)
            patch.setattr(os, "killpg", killpg)
            patch.setattr(os, "kill", kill)
            patch.setattr(asyncio, "wait_for", wait_for)
            asyncio.run(procs.terminate_owned(proc, kill_grace=2.5, wait_after_lost_kill=site == "ask",
                                              soft_request=asked.append))
        return log

    asked = []
    expected = run_ui()
    assert run_facade() == expected
    assert asked == [], "POSIX ignores soft_request: SIGTERM is its soft stop"
    if scenario == "needs-kill":  # the control: the recorders saw a full escalation
        assert expected == [("getpgid", 4100), ("killpg", 4100, signal.SIGTERM), ("wait", 2.5),
                            ("getpgid", 4100), ("killpg", 4100, signal.SIGKILL), ("wait", 2.5)]


@linux
@pytest.mark.parametrize("hard", [False, True])
@pytest.mark.parametrize("answer", ["leader", "other", "lookup"])
def test_stop_owned_sends_what_the_ui_signal_group_sends(monkeypatch, hard, answer):
    """One stop, compared with both UI copies of ``_signal_group`` (the
    runner's takes the process, the ask runner's its PID)."""
    sig = signal.SIGKILL if hard else signal.SIGTERM
    scenario = {"leader": "ignores-both", "other": "not-a-leader", "lookup": "getpgid-lookup"}[answer]
    results, asked = [], []
    for site in ("runner", "ask", "facade"):
        proc, log = _FakeProc(), []
        getpgid, killpg, kill, _ = _recorders(scenario, proc, log)
        if site == "facade":
            with monkeypatch.context() as patch:
                patch.setattr(os, "getpgid", getpgid)
                patch.setattr(os, "killpg", killpg)
                patch.setattr(os, "kill", kill)
                returned = procs.stop_owned(proc, hard=hard, soft_request=asked.append)
        else:
            names = {"os": SimpleNamespace(getpgid=getpgid, killpg=killpg, kill=kill), "signal": signal}
            exec(_ui_stop_sequence(site), names)
            returned = names["_signal_group"](proc if site == "runner" else proc.pid, sig)
        results.append((returned, log))
    assert results[0] == results[1] == results[2]
    assert results[2][0] is (answer != "lookup")
    assert asked == [], "POSIX ignores soft_request"


_IGNORES_TERM = r"""
import os, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(grandchild.pid, flush=True)
time.sleep(60)
"""


def _gone(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return True
    return state == "Z"


@linux
def test_owned_child_tree_dies_under_terminate_on_linux():
    """Real processes: a child that ignores SIGTERM and its grandchild both die
    when the escalation reaches SIGKILL of the group."""

    async def main():
        proc = await procs.async_owned_child(*_python(_IGNORES_TERM), stdout=asyncio.subprocess.PIPE)
        grandchild = int((await asyncio.wait_for(proc.stdout.readline(), 10)).split()[0])
        assert os.getpgid(proc.pid) == proc.pid and os.getpgid(grandchild) == proc.pid
        started = time.monotonic()
        await procs.terminate_owned(proc, kill_grace=0.5)
        return proc.returncode, grandchild, time.monotonic() - started

    code, grandchild, elapsed = asyncio.run(main())
    assert code == -signal.SIGKILL and elapsed >= 0.5
    _wait_for(lambda: _gone(grandchild), 5)


@linux
def test_new_names_never_load_windows_modules_on_linux():
    script = """
        import asyncio, sys
        from self_learn.primitives import procs
        assert procs.breakaway_allowed() is None
        procs.release_owned(object())
        assert "self_learn.primitives._procs_posix" in sys.modules
        # DetachedChild is built on first use, not at import.
        assert "DetachedChild" not in vars(procs), "built at import"
        assert procs.DetachedChild(7) == procs.DetachedChild(7, None, False)
        assert vars(procs)["DetachedChild"] is procs.DetachedChild
        assert procs.DetachedChild.__module__ == "self_learn.primitives.procs"
        loaded = [m for m in sys.modules if m.startswith(("win32", "pywintypes", "_winapi", "msvcrt"))]
        assert not loaded and "self_learn.primitives._procs_windows" not in sys.modules, loaded
        print("ok")
    """
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], capture_output=True,
                          text=True, timeout=30, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


@linux
def test_detached_child_really_detaches_on_linux(tmp_path):
    """Real process: a new session, output appended to the log, stdin left
    inherited exactly as the worker's and miner's copies leave it."""
    log = tmp_path / "run.log"
    log.write_text("earlier\n", encoding="utf-8")
    child = procs.spawn_detached(
        _python("import os; print(os.getsid(0) == os.getpid(), flush=True)"), cwd=str(tmp_path), log_path=log)
    _wait_for(lambda: log.read_text(encoding="utf-8").count("\n") == 2)
    assert log.read_text(encoding="utf-8") == "earlier\nTrue\n"
    assert child.broke_away is None and child.pid > 0


# ==========================================================================
# Windows helpers
# ==========================================================================

#: Every process a Windows test starts is pinned here the moment it exists.
#: The reaper below kills them all when the test ends, and a watchdog thread
#: kills them at the deadline, so a hung await or read in the test returns
#: (and fails) instead of hanging the CI step; faulthandler ends the run if
#: even that does not help.
_PINNED: list = []
_DEADLINE = 120.0


def _pin(pid):
    """A handle on *pid*, kept for the reaper; ``None`` when it is gone. Pin
    only a process that cannot have exited (its Popen or asyncio object still
    holds it, or it is waiting for the test), so the PID still names it."""
    import pywintypes
    import win32api
    import win32con

    try:
        handle = win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE
                                      | win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except pywintypes.error:
        return None
    _PINNED.append(handle)
    return handle


def _kill_pinned():
    import pywintypes
    import win32process

    for handle in list(_PINNED):
        try:
            win32process.TerminateProcess(handle, 1)
        except pywintypes.error:
            pass  # already gone


@pytest.fixture(autouse=True)
def _reaper():
    if sys.platform != "win32":
        yield
        return
    import faulthandler
    import win32api

    _PINNED.clear()
    watchdog = threading.Timer(_DEADLINE, _kill_pinned)
    watchdog.daemon = True
    watchdog.start()
    faulthandler.dump_traceback_later(_DEADLINE + 60, exit=True)
    try:
        yield
    finally:
        watchdog.cancel()
        faulthandler.cancel_dump_traceback_later()
        _kill_pinned()
        for handle in _PINNED:
            win32api.CloseHandle(handle)
        _PINNED.clear()


class _Watch:
    """Pinned handles on each PID, so a death is observed on the process
    itself and never on a reused PID (the reaper owns the handles)."""

    def __init__(self, pids):
        self.pids = list(pids)
        self.handles = [_pin(pid) for pid in self.pids]
        assert all(self.handles), f"a process to watch was already gone: {self.pids}"

    def alive(self):
        import win32event

        return [win32event.WaitForSingleObject(h, 0) == win32event.WAIT_TIMEOUT for h in self.handles]

    def exit_codes(self):
        import win32process

        return [win32process.GetExitCodeProcess(h) for h in self.handles]

    def wait_dead(self, seconds=20.0):
        _wait_for(lambda: not any(self.alive()), seconds)


def _job(*, kill_on_close=True, breakaway=True):
    import win32job
    from uuid import uuid4

    job = win32job.CreateJobObject(None, uuid4().hex)
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    flags = 0
    if kill_on_close:
        flags |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if breakaway:
        flags |= win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
    info["BasicLimitInformation"]["LimitFlags"] |= flags
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


def _assign(job, pid):
    import win32api
    import win32con
    import win32job

    opened = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
    try:
        win32job.AssignProcessToJobObject(job, opened)
    finally:
        win32api.CloseHandle(opened)


def _in_job(pid, job):
    import win32api
    import win32con
    import win32job

    handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    try:
        return win32job.IsProcessInJob(handle, job)
    finally:
        win32api.CloseHandle(handle)


def _this_process_in_a_job():
    import win32api
    import win32job

    return bool(win32job.IsProcessInJob(win32api.GetCurrentProcess(), None))


_QUIET = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _launcher(script, *args, **kwargs):
    """A helper process with no handle of pytest's, pinned at once."""
    launcher = subprocess.Popen(_python(script, *args), **{**_QUIET, **kwargs})
    _pin(launcher.pid)
    return launcher


def _children_of_this_process():
    from self_learn.primitives import _procs_windows as backend

    return {pid for pid, parent in backend._process_parents() if parent == os.getpid()}


# ==========================================================================
# Windows: detached runs
# ==========================================================================

#: The detached run: report what stdin gave it (to stdout) and a marker to
#: stderr, then append a line each time "<ready>.more" appears, until
#: "<ready>.stop" appears.
_DETACHED_CHILD = _PUBLISH + r"""
import os, sys, time
from pathlib import Path
ready = Path(sys.argv[1])
print("started", os.getpid(), repr(sys.stdin.read()), flush=True)
print("stderr marker", os.getpid(), file=sys.stderr, flush=True)
publish(ready, str(os.getpid()))
more, stop = Path(str(ready) + ".more"), Path(str(ready) + ".stop")
while not stop.exists():
    if more.exists():
        more.unlink()
        print("still here", flush=True)
    time.sleep(.02)
"""

#: The launcher: wait for "<out>.go" (the test puts it in its jobs first),
#: start the detached run, report, then sleep until the test kills it.
_DETACH_LAUNCHER = _PUBLISH + r"""
import json, os, site, sys, time
from pathlib import Path
site.addsitedir(sys.argv[1])
import win32api, win32job
from self_learn.primitives import procs
out, child, log = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
deadline = time.monotonic() + 60
while not Path(str(out) + ".go").exists() and time.monotonic() < deadline:
    time.sleep(.005)
report = {"in_job": bool(win32job.IsProcessInJob(win32api.GetCurrentProcess(), None)),
          "allowed": procs.breakaway_allowed()}
started = procs.spawn_detached([sys.executable, "-u", "-c", child, str(out) + ".child"], log_path=log)
report.update(pid=started.pid, broke_away=started.broke_away, child_in_job=started.in_job,
              launcher=os.getpid())
publish(out, json.dumps(report))
time.sleep(120)
"""

#: job chain (outermost first) -> (breakaway accepted, child in each of these
#: jobs, child survives the launcher and the closing of these jobs). Measured:
#: breakaway leaves the launcher's own job but a forbidding outer job keeps the
#: child (and, killing on close, takes it down).
_CHAINS = {
    "allow": ([dict()], True, [False], True),
    "forbid": ([dict(breakaway=False)], False, [True], False),
    "forbid-without-kill-on-close": ([dict(breakaway=False, kill_on_close=False)], False, [True], True),
    "allow-inside-forbid": ([dict(breakaway=False), dict()], True, [True, False], False),
}


@windows
@pytest.mark.parametrize("chain", sorted(_CHAINS))
def test_windows_detached_child_and_its_launchers_abrupt_death(tmp_path, chain):
    """The launcher is killed outright and the test closes the only handles to
    its jobs. A child outside them keeps running and logging. In a
    kill-on-close job that forbids breakaway (directly, or around the job that
    allows it), survival is impossible: the child can only end up inside that
    job, the facade reports so (``in_job``, and ``breakaway_allowed()`` false)
    and the job's closure kills it. In a job that forbids breakaway but does
    not kill on close, the child stays in the job and outlives the launcher."""
    import win32api
    import win32job
    import win32process

    specs, broke_away, membership, survives = _CHAINS[chain]
    out, log = tmp_path / "report", tmp_path / "run.log"
    launcher = _launcher(_DETACH_LAUNCHER, _PURELIB, out, textwrap.dedent(_DETACHED_CHILD), log)
    jobs = []
    try:
        for spec in specs:
            jobs.append(_job(**spec))
            _assign(jobs[-1], launcher.pid)
        (tmp_path / "report.go").write_text("")
        _wait_for(out.exists, 60)
        report = json.loads(out.read_text())
        watch = _Watch([report["pid"]])
        anywhere = bool(win32job.IsProcessInJob(watch.handles[0], None))
        print(f"{chain}: {report}; child in our jobs {[_in_job(report['pid'], j) for j in jobs]}, in any {anywhere}")
        assert report["in_job"] and report["broke_away"] is broke_away
        assert [_in_job(report["pid"], job) for job in jobs] == membership
        assert report["child_in_job"] is anywhere and report["allowed"] is (not anywhere)
        _wait_for((tmp_path / "report.child").exists)
        win32process.TerminateProcess(_PINNED[0], 9)  # the launcher, pinned first
        launcher.wait(timeout=20)
        for job in jobs:
            win32api.CloseHandle(job)
        jobs.clear()
        if survives:
            time.sleep(0.5)
            assert watch.alive() == [True]
            (tmp_path / "report.child.more").write_text("")
            _wait_for(lambda: "still here" in log.read_text(encoding="utf-8"), 20)
        else:
            watch.wait_dead()
        text = log.read_text(encoding="utf-8")
        assert text.startswith(f"started {report['pid']} ''\n"), text
        assert f"stderr marker {report['pid']}\n" in text, text
    finally:
        (tmp_path / "report.child.stop").write_text("")
        for job in jobs:
            win32api.CloseHandle(job)


#: Wait for "<ack>" (the test pins this process first), report each standard
#: handle's kind, write to all three, exit 0.
_ACK_CHILD = _PUBLISH + r"""
import ctypes, json, os, sys, time
from ctypes import wintypes
from pathlib import Path
report, ack = Path(sys.argv[1]), Path(sys.argv[2])
deadline = time.monotonic() + 60
while not ack.exists() and time.monotonic() < deadline:
    time.sleep(.01)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetStdHandle.restype = ctypes.c_void_p
kernel32.GetFileType.argtypes = [ctypes.c_void_p]
kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
def kind(which):
    handle = kernel32.GetStdHandle(which)
    mode = wintypes.DWORD()
    # NUL is a character device that is not a console.
    return {"type": kernel32.GetFileType(handle), "console": bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))}
kinds = {name: kind(which) for name, which in (("stdin", -10), ("stdout", -11), ("stderr", -12))}
print("to stdout", flush=True)
print("to stderr", file=sys.stderr, flush=True)
publish(report, json.dumps({"kinds": kinds, "stdin": sys.stdin.read()}))
"""


@windows
def test_windows_detached_without_a_log_writes_to_nul(tmp_path):
    """All three standard handles are ``NUL`` (a character device that is not
    a console), and writing to them succeeds."""
    report, ack = tmp_path / "report", tmp_path / "ack"
    child = procs.spawn_detached(_python(_ACK_CHILD, report, ack))
    watch = _Watch([child.pid])
    ack.write_text("")
    watch.wait_dead(30)
    assert watch.exit_codes() == [0]
    seen = json.loads(report.read_text())
    _FILE_TYPE_CHAR = 2
    assert seen["stdin"] == "" and seen["kinds"] == {name: {"type": _FILE_TYPE_CHAR, "console": False}
                                                     for name in ("stdin", "stdout", "stderr")}, seen


@windows
def test_windows_detached_membership_unreadable_still_returns_the_child(tmp_path, monkeypatch):
    """Once the child exists, a failure to read its job membership is reported
    as ``in_job=None``, never as a failed launch (a retry would start a second
    worker)."""
    import pywintypes
    from self_learn.primitives import _procs_windows as backend

    def refuse(pid, rights):
        raise pywintypes.error(5, "OpenProcess", "injected")

    monkeypatch.setattr(backend, "_open_process", refuse)
    report, ack = tmp_path / "report", tmp_path / "ack"
    child = procs.spawn_detached(_python(_ACK_CHILD, report, ack))
    watch = _Watch([child.pid])
    assert child.in_job is None and child.pid > 0
    ack.write_text("")
    watch.wait_dead(30)
    assert watch.exit_codes() == [0] and report.exists()


@windows
def test_windows_breakaway_allowed_from_here():
    """The doctor row's answer for this very process, measured on the runner,
    agrees with where a real detached child ends up."""
    answer = procs.breakaway_allowed()
    child = procs.spawn_detached(_python("import time; time.sleep(5)"))
    _pin(child.pid)
    print(f"in a job: {_this_process_in_a_job()}; breakaway allowed: {answer}; a detached child: {child}")
    assert isinstance(answer, bool) and answer is (not child.in_job)
    assert answer is True or _this_process_in_a_job()


class _FakeProbe:
    pid = 0


@windows
@pytest.mark.parametrize("case, expected", [
    ("free", True), ("held", False), ("refused", False), ("both-denied", None),
    ("other-error", None), ("unconfirmed", None),
])
def test_windows_breakaway_allowed_is_inconclusive_unless_proved(monkeypatch, case, expected):
    """Error 5 counts as a refusal only when the same trial without the flag
    starts; a trial whose exit cannot be confirmed proves nothing."""
    from self_learn.primitives import _procs_windows as backend

    tried = []

    def trial(flags):
        breakaway = bool(flags & subprocess.CREATE_BREAKAWAY_FROM_JOB)
        tried.append(breakaway)
        if breakaway and case in ("refused", "both-denied"):
            raise OSError(0, "denied", None, 5)
        if breakaway and case == "other-error":
            raise OSError(0, "missing", None, 2)
        if not breakaway and case == "both-denied":
            raise OSError(0, "denied", None, 5)
        return _FakeProbe()

    monkeypatch.setattr(backend, "_in_a_job", lambda: True)
    monkeypatch.setattr(backend, "_trial", trial)
    monkeypatch.setattr(backend, "_job_membership", lambda pid: case == "held")
    monkeypatch.setattr(backend, "_end_trial", lambda probe: case != "unconfirmed")
    assert procs.breakaway_allowed() is expected
    assert tried == ([True, False] if case in ("refused", "both-denied") else [True])


@windows
def test_windows_detached_second_failure_keeps_the_first(monkeypatch):
    from self_learn.primitives import _procs_windows as backend

    flags_seen = []

    def popen(argv, executable, cwd, env, flags, stdin, stdout, stderr):
        flags_seen.append(flags)
        raise OSError(0, "injected", None, 5 if flags & subprocess.CREATE_BREAKAWAY_FROM_JOB else 2)

    monkeypatch.setattr(backend, "_in_a_job", lambda: True)
    monkeypatch.setattr(backend, "_popen", popen)
    with pytest.raises(OSError) as raised:
        procs.spawn_detached(_python("pass"))
    assert raised.value.winerror == 2
    assert any("CREATE_BREAKAWAY_FROM_JOB" in note for note in getattr(raised.value, "__notes__", ()))
    assert [bool(f & subprocess.CREATE_BREAKAWAY_FROM_JOB) for f in flags_seen] == [True, False]


_LOGGING_CHILD = r"""
import os, sys, time
from pathlib import Path
go = Path(sys.argv[1])
deadline = time.monotonic() + 60
while not go.exists() and time.monotonic() < deadline:
    time.sleep(.005)
# One write per line: print() would write the text and the newline apart.
for n in range(200):
    os.write(1, f"{sys.argv[2]} {n:03d} {'x' * 40}\n".encode())
    os.write(2, f"{sys.argv[2]} err {n:03d}\n".encode())
os.write(1, f"{sys.argv[2]} stdin {sys.stdin.read()!r}\n".encode())
"""


@windows
def test_windows_detached_output_appends_and_only_standard_handles_are_inherited(tmp_path):
    """Two runs append stdout and stderr to one log that already has content,
    without losing or tearing a line; stdin is ``NUL``; an inheritable pipe end
    in the launcher does not reach them (its reader sees end-of-file as soon as
    the launcher closes its own copy)."""
    log = tmp_path / "shared.log"
    log.write_text("earlier\n", encoding="utf-8")
    go = tmp_path / "go"
    reader, writer = os.pipe()
    eof = []
    drain = threading.Thread(target=lambda: eof.append(os.read(reader, 1)), daemon=True)
    try:
        os.set_inheritable(writer, True)
        children = []
        for name in "ab":
            child = procs.spawn_detached(_python(_LOGGING_CHILD, go, name), log_path=log)
            children.append(child)
            _pin(child.pid)
        watch = _Watch([child.pid for child in children])
        os.close(writer)
        writer = None
        drain.start()
        drain.join(5)
        assert eof == [b""], "a detached child inherited a handle it was not given"
        go.write_text("")
        watch.wait_dead(30)
        assert watch.exit_codes() == [0, 0]
        lines = log.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "earlier" and len(lines) == 803, lines[:5]
        for name in "ab":
            assert [line for line in lines if line.startswith(f"{name} ") and " err " not in line][:201] == \
                [f"{name} {n:03d} {'x' * 40}" for n in range(200)] + [f"{name} stdin ''"]
            assert [line for line in lines if line.startswith(f"{name} err ")] == \
                [f"{name} err {n:03d}" for n in range(200)]
    finally:
        # Children first: closing the reader while the drain thread is blocked
        # in a read on it would itself block on Windows.
        go.write_text("")
        _kill_pinned()
        if writer is not None:
            os.close(writer)
        if drain.ident is not None:
            drain.join(20)
        if not drain.is_alive():
            os.close(reader)


#: Report this process's console: its PID and the PIDs attached to its
#: console (empty when it has none); with "spawn", start a grandchild with
#: Python's default flags that reports the same.
_CONSOLE_REPORT = _PUBLISH + r"""
import ctypes, json, os, subprocess, sys
from ctypes import wintypes
def console():
    buffer = (wintypes.DWORD * 64)()
    count = ctypes.WinDLL("kernel32").GetConsoleProcessList(buffer, 64)
    return sorted(buffer[:count])
report = {"pid": os.getpid(), "console": console()}
if sys.argv[2] == "spawn":
    sub = str(sys.argv[1]) + ".sub"
    subprocess.run([sys.executable, "-c", sys.argv[3], sub, "leaf", ""], timeout=60)
    report["grandchild"] = json.loads(open(sub).read())
publish(sys.argv[1], json.dumps(report))
"""


@windows
def test_windows_detached_console_flags_keep_grandchildren_windowless(tmp_path, monkeypatch):
    """The detached run has a console of its own without a window, so a
    console program it starts with default flags joins that console instead
    of getting a new one (which on a desktop is a window). The control: the
    same run started with ``DETACHED_PROCESS`` has no console, and its
    grandchild then sits alone in a console of its own."""
    from self_learn.primitives import _procs_windows as backend

    flags = []
    real_popen = subprocess.Popen

    def recording(*args, **kwargs):
        flags.append(kwargs["creationflags"])
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(backend.subprocess, "Popen", recording)
    script = textwrap.dedent(_CONSOLE_REPORT)
    ours = tmp_path / "ours"
    child = procs.spawn_detached(_python(_CONSOLE_REPORT, ours, "spawn", script))
    monkeypatch.setattr(backend.subprocess, "Popen", real_popen)
    control = tmp_path / "control"
    raw = _launcher(_CONSOLE_REPORT, control, "spawn", script, creationflags=_DETACHED_PROCESS)
    _wait_for(ours.exists, 60)
    _wait_for(control.exists, 60)
    raw.wait(60)
    mine, theirs = json.loads(ours.read_text()), json.loads(control.read_text())
    print(f"facade: {mine}; DETACHED_PROCESS: {theirs}")
    assert flags[-1] & (_CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW) == _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
    assert not flags[-1] & (_DETACHED_PROCESS | _CREATE_NEW_CONSOLE)
    assert mine["pid"] == child.pid and child.pid in mine["console"] and os.getpid() not in mine["console"]
    assert child.pid in mine["grandchild"]["console"]
    assert theirs["console"] == [] and theirs["grandchild"]["console"] == [theirs["grandchild"]["pid"]]


@windows
@pytest.mark.parametrize("call", ["spawn_detached", "async_owned_child"])
def test_windows_resolution_refuses_shims_and_the_current_folder(tmp_path, call):
    """A ``.cmd`` shim is refused before anything starts, and a bare name found
    only in the current folder is not found."""
    import winerror

    (tmp_path / "shim.cmd").write_text("@echo off\r\n", encoding="utf-8")
    (tmp_path / "local.exe").write_bytes(Path(_BASE).read_bytes())
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {**os.environ, "PATH": str(empty)}
    cases = [([str(tmp_path / "shim.cmd")], winerror.ERROR_BAD_EXE_FORMAT), (["local"], winerror.ERROR_FILE_NOT_FOUND)]
    before = _children_of_this_process()
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        for argv, code in cases:
            with pytest.raises(OSError) as raised:
                if call == "spawn_detached":
                    procs.spawn_detached(argv, cwd=str(tmp_path), env=env)
                else:
                    asyncio.run(procs.async_owned_child(*argv, env=env))
            assert raised.value.winerror == code
    finally:
        os.chdir(old)
    assert _children_of_this_process() <= before


@windows
@pytest.mark.parametrize("direction", ["owned-stderr", "detached-log", "bounded-pipes"])
def test_windows_concurrent_launches_share_no_handles(tmp_path, monkeypatch, direction):
    """Two launches overlap, each made to hold its inheritable-handle window
    open for half a second. ``owned-stderr`` and ``detached-log``: while one of
    ours is being created, a ``run_bounded`` child (which inherits every
    inheritable handle) starts; it must not get our child's stderr writer (its
    reader would then wait for it) or our log handle (an exclusive open would
    then fail). ``bounded-pipes``: while a ``run_bounded`` child is being
    created, a detached child of ours starts; it must not get the bounded
    child's output pipe (``run_bounded`` would then wait for it)."""
    import pywintypes
    import win32file
    import win32process

    entered = threading.Event()
    results = []
    if direction == "bounded-pipes":
        real_create = win32process.CreateProcess

        def slow_create(*args):
            entered.set()
            time.sleep(0.5)
            return real_create(*args)

        monkeypatch.setattr(win32process, "CreateProcess", slow_create)
        bounded = threading.Thread(daemon=True, target=lambda: results.append(
            procs.run_bounded(_python("print('done')"), timeout=60)))
        bounded.start()
        assert entered.wait(20)
        ack = tmp_path / "ack"
        child = procs.spawn_detached(_python(_ACK_CHILD, tmp_path / "report", ack))
        _pin(child.pid)
        bounded.join(20)  # our child is still waiting for its ack meanwhile
        assert not bounded.is_alive() and results[0].stdout.strip() == "done"
        ack.write_text("")
        return
    real_inheritable = subprocess.Popen._make_inheritable

    def slow_inheritable(self, handle):
        duplicate = real_inheritable(self, handle)
        entered.set()
        time.sleep(0.5)
        return duplicate

    monkeypatch.setattr(subprocess.Popen, "_make_inheritable", slow_inheritable)

    def bounded_run():
        assert entered.wait(20)
        results.append(procs.run_bounded(_python("import time; time.sleep(6)"), timeout=60))

    bounded = threading.Thread(target=bounded_run, daemon=True)
    bounded.start()
    if direction == "owned-stderr":
        async def main():
            proc = await procs.async_owned_child(*_python("import sys; sys.stderr.write('x')"),
                                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                 stderr=asyncio.subprocess.PIPE)
            _pin(proc.pid)
            try:
                return await asyncio.wait_for(proc.stderr.read(), 4.0)
            finally:
                procs.release_owned(proc)

        assert asyncio.run(main()) == b"x"
    else:
        log, ack = tmp_path / "run.log", tmp_path / "ack"
        child = procs.spawn_detached(_python(_ACK_CHILD, tmp_path / "report", ack), log_path=log)
        watch = _Watch([child.pid])
        ack.write_text("")
        watch.wait_dead(30)
        assert bounded.is_alive(), "the bounded child must still be running for this to prove anything"
        try:
            exclusive = win32file.CreateFile(str(log), win32file.GENERIC_READ, 0, None,
                                             win32file.OPEN_EXISTING, 0, None)
        except pywintypes.error as exc:
            raise AssertionError(f"another process still holds the log: {exc}") from exc
        exclusive.Close()
    bounded.join(30)


# ==========================================================================
# Windows: owned asyncio children
# ==========================================================================

#: The owned child: start a sleeping grandchild, publish
#: {"pid", "grandchild", "event"} to the ready file, then act by mode.
#:   plain     sleep
#:   break     on SIGBREAK, note "sigbreak" and exit 7
#:   default   no handler: a console event would end it
#:   event     ignore SIGBREAK; when the stop event is set, note "event", exit 8
#:   stubborn  ignore SIGBREAK, never look at the event
#:   holder    the grandchild holds this child's stderr; exit at once
#:   escaped   the grandchild breaks away from the job holding this child's stderr
#:   detach    start a detached run (procs.spawn_detached) and report it too
#:   tree      (a foreign child) like plain
_OWNED_CHILD = _PUBLISH + r"""
import ctypes, json, os, signal, subprocess, sys, time
from pathlib import Path
ready, mode = Path(sys.argv[1]), sys.argv[2]
note = Path(str(ready) + ".note")
sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
holds = mode in ("holder", "escaped")
grandchild = subprocess.Popen(sleeper, stderr=sys.stderr if holds else subprocess.DEVNULL,
                              creationflags=0x01000000 if mode == "escaped" else 0, **quiet)
report = {"pid": os.getpid(), "grandchild": grandchild.pid, "event": os.environ.get("SELF_LEARN_STOP_EVENT")}
if mode == "detach":
    import site
    site.addsitedir(sys.argv[3])
    from self_learn.primitives import procs
    started = procs.spawn_detached(sleeper)
    report.update(detached=started.pid, broke_away=started.broke_away)
def stop(code, words):
    publish(note, words)
    os._exit(code)
if mode == "break":
    signal.signal(signal.SIGBREAK, lambda *_: stop(7, "sigbreak"))
elif mode in ("event", "stubborn"):
    signal.signal(signal.SIGBREAK, signal.SIG_IGN)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenEventW.restype = ctypes.c_void_p
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
event = kernel32.OpenEventW(0x00100000, False, report["event"]) if mode == "event" else None
publish(ready, json.dumps(report))
if mode == "holder":
    sys.exit(0)
while True:
    if event and kernel32.WaitForSingleObject(event, 20) == 0:
        stop(8, "event")
    time.sleep(.02)
"""


async def _owned(tmp_path, mode="plain", name="child", **streams):
    """An owned child (and its grandchild) pinned as soon as each exists. By
    default it gets no handle of pytest's."""
    ready = tmp_path / name
    proc = await procs.async_owned_child(*_python(_OWNED_CHILD, ready, mode, _PURELIB), **{**_QUIET, **streams})
    _pin(proc.pid)  # asyncio holds it open, so the PID is ours
    deadline = time.monotonic() + 30
    while not ready.exists():
        assert time.monotonic() < deadline, "the owned child never reported"
        await asyncio.sleep(.02)
    report = json.loads(ready.read_text())
    _pin(report["grandchild"])
    if "detached" in report:
        _pin(report["detached"])
    return proc, report


def _owner(proc):
    from self_learn.primitives import _procs_windows as backend

    return backend._owned[proc]


def _active(job):
    import win32job

    return win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)["ActiveProcesses"]


def _recording_stops(monkeypatch):
    """Record each stop terminate_owned issues (it calls the backend's
    stop_owned by name)."""
    from self_learn.primitives import _procs_windows as backend

    issued = []
    real = backend.stop_owned

    def recording(proc, *, hard, soft_request=None):
        issued.append("hard" if hard else "soft")
        return real(proc, hard=hard, soft_request=soft_request)

    monkeypatch.setattr(backend, "stop_owned", recording)
    return issued


@windows
def test_windows_owned_child_and_grandchild_are_in_its_job(tmp_path):
    """The child is put in its own job before it runs, so its grandchild is
    born in the job; its environment names the stop event; releasing it kills
    both, and a second release does nothing."""
    import win32event
    import win32job

    async def main():
        proc, report = await _owned(tmp_path)
        owner = _owner(proc)
        watch = _Watch([report["pid"], report["grandchild"]])
        assert report["pid"] == proc.pid
        assert _in_job(proc.pid, owner.job) and _in_job(report["grandchild"], owner.job)
        assert report["event"].startswith("Local\\self-learn-stop-")
        assert win32event.WaitForSingleObject(owner.event, 0) == win32event.WAIT_TIMEOUT
        flags = win32job.QueryInformationJobObject(owner.job, win32job.JobObjectExtendedLimitInformation)
        limits = flags["BasicLimitInformation"]["LimitFlags"]
        assert limits & win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE and limits & win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
        procs.release_owned(proc)
        watch.wait_dead()
        procs.release_owned(proc)
        await asyncio.wait_for(proc.wait(), 20)

    asyncio.run(main())


@windows
def test_windows_owned_child_is_assigned_before_it_runs(tmp_path, monkeypatch):
    """Creation, then assignment to the job, then one resume of one thread, in
    that order, and the payload has not run before the resume."""
    import win32job
    import win32process

    ready = tmp_path / "child"
    order = []
    real_assign, real_resume = win32job.AssignProcessToJobObject, win32process.ResumeThread

    def assign(job, process):
        order.append(("assign", ready.exists()))
        return real_assign(job, process)

    def resume(thread):
        order.append(("resume", ready.exists()))
        return real_resume(thread)

    procs.contain_self()  # its own first assignment is not the one recorded
    monkeypatch.setattr(win32job, "AssignProcessToJobObject", assign)
    monkeypatch.setattr(win32process, "ResumeThread", resume)

    async def main():
        proc, report = await _owned(tmp_path)
        procs.release_owned(proc)

    asyncio.run(main())
    assert order == [("assign", False), ("resume", False)]


@windows
@pytest.mark.parametrize("step", ["assign", "resume", "suspend-count"])
def test_windows_owned_child_launch_failure_never_runs_the_payload(tmp_path, monkeypatch, step):
    """A failed assignment, a failed resume, or a first thread whose suspend
    count is not ours: the call raises, the child is terminated and reaped
    (exit status 1), and its payload never ran."""
    import pywintypes
    import win32job
    import win32process

    ready = tmp_path / "child"
    seen = {}
    real_assign, real_resume = win32job.AssignProcessToJobObject, win32process.ResumeThread

    def assign(job, process):
        seen["watch"] = _Watch([win32process.GetProcessId(process)])
        if step == "assign":
            raise pywintypes.error(5, "AssignProcessToJobObject", "injected")
        return real_assign(job, process)

    def resume(thread):
        if step == "resume":
            raise pywintypes.error(5, "ResumeThread", "injected")
        return 2  # "suspend-count": another suspension, and the thread stays suspended

    procs.contain_self()  # its own first assignment is not the one to fail
    monkeypatch.setattr(win32job, "AssignProcessToJobObject", assign)
    monkeypatch.setattr(win32process, "ResumeThread", resume if step != "assign" else real_resume)
    with pytest.raises(OSError):
        asyncio.run(procs.async_owned_child(*_python(_OWNED_CHILD, ready, "plain", _PURELIB), **_QUIET))
    seen["watch"].wait_dead()
    assert seen["watch"].exit_codes() == [1]
    time.sleep(0.5)
    assert not ready.exists()


_DEATH_LAUNCHER = _PUBLISH + r"""
import asyncio, os, site, sys
site.addsitedir(sys.argv[1])
import win32api, win32job, win32process
from self_learn.primitives import procs
pid_file, child = sys.argv[2], sys.argv[3:]
def die_in_the_handoff(job, process):
    publish(pid_file, str(win32process.GetProcessId(process)))
    win32process.TerminateProcess(win32api.GetCurrentProcess(), 9)
procs.contain_self()  # the self job that must take the suspended child down
win32job.AssignProcessToJobObject = die_in_the_handoff
asyncio.run(procs.async_owned_child(*child))
"""


@windows
def test_windows_launcher_death_in_the_handoff_takes_the_suspended_child(tmp_path):
    """The launcher dies after creating the child (suspended) and before
    assigning it to its job: the child is in the launcher's kill-on-close self
    job, so it dies with the launcher and never runs."""
    import pywintypes
    import win32api
    import win32con
    import win32event

    pid_file, ready = tmp_path / "pid", tmp_path / "child"
    launcher = _launcher(_DEATH_LAUNCHER, _PURELIB, pid_file, *_python(_OWNED_CHILD, ready, "plain", _PURELIB))
    assert launcher.wait(60) == 9
    child = int(pid_file.read_text())
    try:
        handle = win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, child)
    except pywintypes.error:
        handle = None  # already gone
    if handle is not None:
        _PINNED.append(handle)
        assert win32event.WaitForSingleObject(handle, 20000) == win32event.WAIT_OBJECT_0
    time.sleep(0.5)
    assert not ready.exists()


@windows
def test_windows_detached_run_started_by_an_owned_child_escapes_its_job(tmp_path):
    """A ``worker kick`` run by the web UI starts a detached worker from inside
    an owned child: it breaks away, and survives the release of the child's
    job."""

    async def main():
        proc, report = await _owned(tmp_path, "detach")
        watch = _Watch([report["pid"], report["grandchild"], report["detached"]])
        assert report["broke_away"] is True and not _in_job(report["detached"], _owner(proc).job)
        procs.release_owned(proc)
        _wait_for(lambda: watch.alive() == [False, False, True], 20)
        time.sleep(0.3)
        assert watch.alive() == [False, False, True]

    asyncio.run(main())


@windows
def test_windows_cancel_of_the_reader_then_terminate_stops_the_tree(tmp_path, monkeypatch):
    """The web UI's pattern: a task waiting on ``communicate`` is cancelled,
    and its ``except CancelledError`` runs ``terminate_owned`` before
    re-raising. The cancellation propagates and nothing survives."""
    issued = _recording_stops(monkeypatch)

    async def main():
        proc, report = await _owned(tmp_path, "stubborn", stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE)
        watch = _Watch([report["pid"], report["grandchild"]])

        async def drive():
            try:
                await proc.communicate()
            except asyncio.CancelledError:
                await procs.terminate_owned(proc, kill_grace=0.5)
                raise

        task = asyncio.ensure_future(drive())
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        watch.wait_dead()
        assert issued == ["soft", "hard"] and proc.returncode == 1

    asyncio.run(main())


@windows
@pytest.mark.parametrize("how", ["cancel", "cancel-twice", "stop-raises"])
def test_windows_teardown_ends_the_tree_however_it_is_interrupted(tmp_path, monkeypatch, how):
    """``terminate_owned`` itself is interrupted while the caller keeps the
    process: cancelled during its first grace wait (once, or again while it
    settles), or its soft stop raising. The job is terminated anyway, the
    original exception leaves, and the child and grandchild die."""
    import pywintypes
    import win32event

    async def main():
        proc, report = await _owned(tmp_path, "stubborn")
        watch = _Watch([report["pid"], report["grandchild"]])
        if how == "stop-raises":
            def fail(event):
                raise pywintypes.error(6, "SetEvent", "injected")
            monkeypatch.setattr(win32event, "SetEvent", fail)
            with pytest.raises(OSError):
                await procs.terminate_owned(proc, kill_grace=60)
        else:
            task = asyncio.ensure_future(procs.terminate_owned(proc, kill_grace=60))
            await asyncio.sleep(0.5)  # inside the first (60 s) grace wait
            task.cancel()
            if how == "cancel-twice":
                await asyncio.sleep(0)
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        watch.wait_dead()
        assert proc is not None and _active(_owner(proc).job) == 0

    asyncio.run(main())


@windows
def test_windows_soft_stop_then_hard_stop_leaves_no_survivor(tmp_path, monkeypatch):
    """A child that ignores the soft stop is hard-stopped after the grace, and
    the hard stop takes the grandchild too. A further stop finds nothing."""
    issued = _recording_stops(monkeypatch)

    async def main():
        proc, report = await _owned(tmp_path, "stubborn")
        watch = _Watch([report["pid"], report["grandchild"]])
        await procs.terminate_owned(proc, kill_grace=1.0)
        watch.wait_dead()
        assert issued == ["soft", "hard"] and proc.returncode == 1 and watch.exit_codes()[0] == 1
        assert _active(_owner(proc).job) == 0
        assert procs.stop_owned(proc, hard=False) is False and procs.stop_owned(proc, hard=True) is False

    asyncio.run(main())


@windows
def test_windows_soft_request_gets_the_pid_and_cannot_block_the_hard_stop(tmp_path, monkeypatch):
    """The caller's soft request (``stop_request.request_stop`` in the UI) is
    called with the child's PID; one that raises does not stop the escalation."""
    asked = []

    def request(pid):
        asked.append(pid)
        raise RuntimeError("the stop file could not be written")

    async def main():
        proc, report = await _owned(tmp_path, "stubborn")
        watch = _Watch([report["pid"], report["grandchild"]])
        await procs.terminate_owned(proc, kill_grace=0.5, soft_request=request)
        watch.wait_dead()
        assert asked == [proc.pid]

    asyncio.run(main())


@windows
def test_windows_hard_stop_alone_kills_the_whole_job(tmp_path):
    async def main():
        proc, report = await _owned(tmp_path)
        watch = _Watch([report["pid"], report["grandchild"]])
        assert procs.stop_owned(proc, hard=True) is True
        watch.wait_dead()
        assert await asyncio.wait_for(proc.wait(), 20) == 1

    asyncio.run(main())


@windows
def test_windows_watchdog_timeout_then_terminate(tmp_path, monkeypatch):
    """A child that writes nothing trips the reader's own deadline; the
    terminate that follows escalates and leaves nothing running."""
    issued = _recording_stops(monkeypatch)

    async def main():
        proc, report = await _owned(tmp_path, "stubborn", stdout=asyncio.subprocess.PIPE)
        watch = _Watch([report["pid"], report["grandchild"]])
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.5):
                await proc.stdout.readline()
        await procs.terminate_owned(proc, kill_grace=0.5)
        watch.wait_dead()
        assert issued == ["soft", "hard"]

    asyncio.run(main())


async def _exit_seen(proc, seconds=20.0):
    deadline = time.monotonic() + seconds
    while proc.returncode is None:
        assert time.monotonic() < deadline, "asyncio never saw the child exit"
        await asyncio.sleep(.02)


@windows
def test_windows_grandchild_holding_stderr_does_not_hang_the_reader(tmp_path):
    """The child exits at once while its grandchild keeps the child's stderr
    pipe open, so reading stderr to its end would wait for the grandchild (the
    control shows it does). ``terminate_owned`` on the exited child empties its
    job, the grandchild dies and the read completes."""

    async def main():
        proc, report = await _owned(tmp_path, "holder", stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE)
        watch = _Watch([report["grandchild"]])
        await _exit_seen(proc)
        assert proc.returncode == 0
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(proc.stderr.read(), 1.0)  # the control
        try:
            waited = await asyncio.wait_for(proc.wait(), 1.0)
        except TimeoutError:
            waited = "hung"
        print(f"asyncio wait() while the grandchild held stderr: {waited}")
        assert watch.alive() == [True]
        await procs.terminate_owned(proc, kill_grace=5.0)
        assert await asyncio.wait_for(proc.stderr.read(), 20) == b""
        assert await asyncio.wait_for(proc.wait(), 20) == 0
        watch.wait_dead()

    asyncio.run(main())


@windows
def test_windows_teardown_closes_pipes_a_writer_outside_the_job_holds(tmp_path):
    """The grandchild broke away from the job holding the child's stderr: the
    job empties, but the pipe would never reach end-of-file. Teardown closes our
    end, the read completes, and the escaped grandchild (not ours) lives on."""

    async def main():
        proc, report = await _owned(tmp_path, "escaped", stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE)
        watch = _Watch([report["pid"], report["grandchild"]])
        assert not _in_job(report["grandchild"], _owner(proc).job)
        await procs.terminate_owned(proc, kill_grace=2.0)
        assert await asyncio.wait_for(proc.stderr.read(), 20) == b""
        _wait_for(lambda: watch.alive() == [False, True], 20)

    asyncio.run(main())


@windows
def test_windows_teardown_reports_members_that_outlive_the_grace(tmp_path, monkeypatch):
    """A job that still counts members at the end of the grace is reported as
    TimeoutError, not as a clean teardown."""
    from self_learn.primitives import _procs_windows as backend

    async def main():
        proc, report = await _owned(tmp_path)
        _Watch([report["pid"], report["grandchild"]])
        monkeypatch.setattr(backend, "_active_processes", lambda job: 1)
        with pytest.raises(TimeoutError, match="still has 1 process"):
            await procs.terminate_owned(proc, kill_grace=0.5)
        monkeypatch.undo()
        procs.release_owned(proc)

    asyncio.run(main())


@windows
def test_windows_release_during_teardown_is_safe(tmp_path):
    """The UI releases the child while a teardown is still settling: the
    teardown keeps working on its own handles and ends cleanly."""

    async def main():
        proc, report = await _owned(tmp_path, "stubborn")
        watch = _Watch([report["pid"], report["grandchild"]])
        task = asyncio.ensure_future(procs.terminate_owned(proc, kill_grace=1.0))
        await asyncio.sleep(0.2)
        procs.release_owned(proc)
        await asyncio.wait_for(task, 30)
        watch.wait_dead()

    asyncio.run(main())


@windows
def test_windows_dropping_the_process_object_kills_the_tree(tmp_path):
    async def main():
        proc, report = await _owned(tmp_path)
        watch = _Watch([report["pid"], report["grandchild"]])
        del proc
        gc.collect()
        watch.wait_dead()
        await asyncio.sleep(0.5)  # let asyncio see the exit, then free its
        gc.collect()  # transport while the loop is still open

    asyncio.run(main())


@windows
@pytest.mark.parametrize("hard", [False, True])
def test_windows_a_process_started_elsewhere_is_stopped_alone(tmp_path, hard):
    """No job, no event, no console group of ours: either stop terminates that
    one process and leaves its grandchild, and reports ``False`` once it has
    exited."""

    async def main():
        ready = tmp_path / "child"
        proc = await asyncio.create_subprocess_exec(*_python(_OWNED_CHILD, ready, "tree", _PURELIB), **_QUIET)
        _pin(proc.pid)
        _wait_for(ready.exists, 30)
        report = json.loads(ready.read_text())
        watch = _Watch([proc.pid, report["grandchild"]])
        assert procs.stop_owned(proc, hard=hard) is True
        await asyncio.wait_for(proc.wait(), 20)
        assert watch.alive() == [False, True]
        assert procs.stop_owned(proc, hard=False) is False and procs.stop_owned(proc, hard=True) is False
        procs.release_owned(proc)

    asyncio.run(main())


@windows
def test_windows_selector_loop_refuses_before_anything_starts(tmp_path):
    """Only the Proactor loop can run subprocesses on Windows: under a Selector
    loop asyncio raises NotImplementedError and no child process exists."""
    ready = tmp_path / "child"
    before = _children_of_this_process()
    loop = asyncio.SelectorEventLoop()
    try:
        with pytest.raises(NotImplementedError):
            loop.run_until_complete(procs.async_owned_child(*_python(_OWNED_CHILD, ready, "plain", _PURELIB)))
    finally:
        loop.close()
    assert _children_of_this_process() <= before
    assert not ready.exists()


#: Run one owned child to a soft stop in a launcher whose console is chosen by
#: the test, beside a witness in its own console group; report what happened.
_SOFT_LAUNCHER = _PUBLISH + r"""
import asyncio, json, subprocess, sys, time
from pathlib import Path
site_dir, out, mode, child = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
import site
site.addsitedir(site_dir)
import win32api, win32con, win32event, win32process
from self_learn.primitives import procs
from self_learn.primitives import _procs_windows as backend
witness_note = Path(str(out) + ".witness")
# In the launcher's console when it has one (in a group of its own), else in a
# console of its own without a window.
witness_flags = 0x00000200 | (0 if backend._has_console() else 0x08000000)
witness = subprocess.Popen([sys.executable, "-c", (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGBREAK, lambda *_: open(sys.argv[1], 'w').write('break'))\n"
    "time.sleep(60)\n"), str(witness_note)], creationflags=witness_flags,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
issued = []
real = backend.stop_owned
def recording(proc, *, hard, soft_request=None):
    issued.append("hard" if hard else "soft")
    return real(proc, hard=hard, soft_request=soft_request)
backend.stop_owned = recording

async def main():
    ready = Path(str(out) + ".child")
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc = await procs.async_owned_child(sys.executable, "-u", "-c", child, str(ready), mode, site_dir, **quiet)
    deadline = time.monotonic() + 30
    while not ready.exists():
        assert time.monotonic() < deadline
        await asyncio.sleep(.02)
    pids = json.loads(ready.read_text())
    pinned = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pids["grandchild"])
    await procs.terminate_owned(proc, kill_grace=1.5)
    time.sleep(0.3)  # time for a stray console event to reach the witness
    note = Path(str(ready) + ".note")
    return {"has_console": backend._has_console(), "shares_console": backend._owned[proc].shares_console,
            "code": proc.returncode, "issued": issued, "note": note.read_text() if note.exists() else "",
            "grandchild_dead": win32event.WaitForSingleObject(pinned, 10000) == win32event.WAIT_OBJECT_0,
            "witness": witness_note.read_text() if witness_note.exists() else ""}

try:
    publish(out, json.dumps(asyncio.run(main())))
finally:
    witness.kill()
"""

#: (console, child mode) -> (exit status, note, stops issued). No console
#: event is ever sent: the event is the only soft channel.
_SOFT = {
    ("console", "break"): (1, "", ["soft", "hard"]),
    ("console", "default"): (1, "", ["soft", "hard"]),
    ("console", "event"): (8, "event", ["soft"]),
    ("console", "stubborn"): (1, "", ["soft", "hard"]),
    ("no-console", "break"): (1, "", ["soft", "hard"]),
    ("no-console", "default"): (1, "", ["soft", "hard"]),
    ("no-console", "event"): (8, "event", ["soft"]),
    ("no-console", "stubborn"): (1, "", ["soft", "hard"]),
}


@windows
@pytest.mark.parametrize("console, mode", sorted(_SOFT))
def test_windows_what_the_soft_stop_reaches(tmp_path, console, mode):
    """The soft stop is the stop event alone: a child watching it stops
    cooperatively (8), and one with only a ``SIGBREAK`` handler, or none,
    receives nothing and is hard-stopped after the grace, with or without a
    shared console. A witness in its own console group never sees a break.
    Every case leaves the grandchild dead."""
    out = tmp_path / "report"
    flags = _CREATE_NEW_CONSOLE if console == "console" else _DETACHED_PROCESS
    launcher = _launcher(_SOFT_LAUNCHER, _PURELIB, out, mode, textwrap.dedent(_OWNED_CHILD), creationflags=flags)
    assert launcher.wait(90) == 0
    report = json.loads(out.read_text())
    print(f"{console}/{mode}: {report}")
    code, note, issued = _SOFT[(console, mode)]
    assert report["has_console"] is report["shares_console"] is (console == "console")
    assert (report["code"], report["note"], report["issued"]) == (code, note, issued)
    assert report["grandchild_dead"] is True and report["witness"] == ""
