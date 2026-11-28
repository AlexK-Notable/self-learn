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
            asyncio.run(procs.terminate_owned(proc, kill_grace=2.5, wait_after_lost_kill=site == "ask"))
        return log

    expected = run_ui()
    assert run_facade() == expected
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
    results = []
    for site in ("runner", "ask", "facade"):
        proc, log = _FakeProc(), []
        getpgid, killpg, kill, _ = _recorders(scenario, proc, log)
        if site == "facade":
            with monkeypatch.context() as patch:
                patch.setattr(os, "getpgid", getpgid)
                patch.setattr(os, "killpg", killpg)
                patch.setattr(os, "kill", kill)
                returned = procs.stop_owned(proc, hard=hard)
        else:
            names = {"os": SimpleNamespace(getpgid=getpgid, killpg=killpg, kill=kill), "signal": signal}
            exec(_ui_stop_sequence(site), names)
            returned = names["_signal_group"](proc if site == "runner" else proc.pid, sig)
        results.append((returned, log))
    assert results[0] == results[1] == results[2]
    assert results[2][0] is (answer != "lookup")


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


class _Watch:
    """SYNCHRONIZE handles that pin each PID, so a death is observed on the
    process itself and never on a reused PID."""

    def __init__(self, pids):
        import win32api
        import win32con

        self.pids = list(pids)
        self.handles = [win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE
                                             | win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                        for pid in self.pids]

    def alive(self):
        import win32event

        return [win32event.WaitForSingleObject(h, 0) == win32event.WAIT_TIMEOUT for h in self.handles]

    def exit_codes(self):
        import win32process

        return [win32process.GetExitCodeProcess(h) for h in self.handles]

    def wait_dead(self, seconds=10.0):
        _wait_for(lambda: not any(self.alive()), seconds)

    def kill(self):
        import pywintypes
        import win32api
        import win32process

        for handle, alive in zip(self.handles, self.alive()):
            if alive:
                try:
                    win32process.TerminateProcess(handle, 1)
                except pywintypes.error:
                    pass
        for handle in self.handles:
            win32api.CloseHandle(handle)
        self.handles = []


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


def _kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=60)


def _this_process_in_a_job():
    import win32api
    import win32job

    return bool(win32job.IsProcessInJob(win32api.GetCurrentProcess(), None))


# ==========================================================================
# Windows: detached runs
# ==========================================================================

#: The detached run: report what stdin gave it, then append a line each time
#: "<ready>.more" appears, until "<ready>.stop" appears.
_DETACHED_CHILD = _PUBLISH + r"""
import os, sys, time
from pathlib import Path
ready = Path(sys.argv[1])
print("started", os.getpid(), repr(sys.stdin.read()), flush=True)
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
while not Path(str(out) + ".go").exists():
    time.sleep(.005)
report = {"in_job": bool(win32job.IsProcessInJob(win32api.GetCurrentProcess(), None)),
          "allowed": procs.breakaway_allowed()}
started = procs.spawn_detached([sys.executable, "-u", "-c", child, str(out) + ".child"], log_path=log)
report.update(pid=started.pid, broke_away=started.broke_away, launcher=os.getpid())
publish(out, json.dumps(report))
time.sleep(120)
"""

#: job chain (outermost first) -> (broke_away, breakaway_allowed, survives)
_CHAINS = {
    "allow": ([dict()], True, True, True),
    "forbid": ([dict(breakaway=False)], False, False, False),
    "forbid-without-kill-on-close": ([dict(breakaway=False, kill_on_close=False)], False, False, True),
    "allow-inside-forbid": ([dict(breakaway=False), dict()], False, False, False),
}


@windows
@pytest.mark.parametrize("chain", sorted(_CHAINS))
def test_windows_detached_child_and_its_launchers_abrupt_death(tmp_path, chain):
    """The launcher is killed outright and the test closes the only handles to
    its jobs. A child that broke away keeps running and logging. In a
    kill-on-close job that forbids breakaway, survival is impossible: the child
    can only be started inside the job, the facade reports so
    (``broke_away=False``) and the job's closure kills it. In a job that
    forbids breakaway but does not kill on close, the child stays in the job
    and outlives the launcher."""
    import win32api
    import win32con
    import win32process

    specs, broke_away, allowed, survives = _CHAINS[chain]
    out, log = tmp_path / "report", tmp_path / "run.log"
    launcher = subprocess.Popen(_python(_DETACH_LAUNCHER, _PURELIB, out, textwrap.dedent(_DETACHED_CHILD), log))
    jobs = []
    watch = None
    try:
        for spec in specs:
            jobs.append(_job(**spec))
            _assign(jobs[-1], launcher.pid)
        (tmp_path / "report.go").write_text("")
        _wait_for(out.exists, 30)
        report = json.loads(out.read_text())
        print(f"{chain}: {report}")
        watch = _Watch([report["pid"]])
        assert report["in_job"] and (report["broke_away"], report["allowed"]) == (broke_away, allowed)
        _wait_for((tmp_path / "report.child").exists)
        assert all(_in_job(report["pid"], job) for job in jobs) is not broke_away
        opened = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, launcher.pid)
        win32process.TerminateProcess(opened, 9)
        win32api.CloseHandle(opened)
        launcher.wait(timeout=10)
        for job in jobs:
            win32api.CloseHandle(job)
        jobs.clear()
        if survives:
            time.sleep(0.5)
            assert watch.alive() == [True]
            (tmp_path / "report.child.more").write_text("")
            _wait_for(lambda: "still here" in log.read_text(encoding="utf-8"))
        else:
            watch.wait_dead()
        text = log.read_text(encoding="utf-8")
        assert text.startswith(f"started {report['pid']} ''\n"), text
    finally:
        (tmp_path / "report.child.stop").write_text("")
        if watch is not None:
            watch.kill()
        _kill_tree(launcher.pid)
        for job in jobs:
            win32api.CloseHandle(job)


@windows
def test_windows_breakaway_allowed_from_here():
    """The doctor row's answer for this very process, measured on the runner;
    a job-free process may always break away."""
    answer = procs.breakaway_allowed()
    print(f"in a job: {_this_process_in_a_job()}; breakaway allowed: {answer}")
    assert answer is True or (answer is False and _this_process_in_a_job())


_LOGGING_CHILD = r"""
import sys, time
from pathlib import Path
go = Path(sys.argv[1])
while not go.exists():
    time.sleep(.005)
for n in range(200):
    print(f"{sys.argv[2]} {n:03d} {'x' * 40}", flush=True)
print(sys.argv[2], "stdin", repr(sys.stdin.read()), flush=True)
"""


@windows
def test_windows_detached_output_appends_and_only_standard_handles_are_inherited(tmp_path):
    """Two runs append to one log that already has content, without losing or
    tearing a line; stdin is ``NUL``; an inheritable pipe end in the launcher
    does not reach them (its reader sees end-of-file as soon as the launcher
    closes its own copy)."""
    log = tmp_path / "shared.log"
    log.write_text("earlier\n", encoding="utf-8")
    reader, writer = os.pipe()
    os.set_inheritable(writer, True)
    go = tmp_path / "go"
    children = [procs.spawn_detached(_python(_LOGGING_CHILD, go, name), log_path=log) for name in "ab"]
    watch = _Watch([child.pid for child in children])
    try:
        os.close(writer)
        eof = []
        drain = threading.Thread(target=lambda: eof.append(os.read(reader, 1)), daemon=True)
        drain.start()
        drain.join(5)
        assert eof == [b""], "a detached child inherited a handle it was not given"
        go.write_text("")
        watch.wait_dead(30)
        assert watch.exit_codes() == [0, 0]
        lines = log.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "earlier" and len(lines) == 403, lines[:5]
        for name in "ab":
            mine = [line for line in lines[1:] if line.startswith(name + " ")]
            assert mine[:200] == [f"{name} {n:03d} {'x' * 40}" for n in range(200)]
            assert mine[200] == f"{name} stdin ''"
    finally:
        os.close(reader)
        watch.kill()


@windows
def test_windows_detached_without_a_log_writes_to_nul(tmp_path):
    marker = tmp_path / "done"
    script = _PUBLISH + r"""
import sys
for n in range(1000):
    print("noise", n)
    print("more noise", n, file=sys.stderr)
publish(sys.argv[1], repr(sys.stdin.read()))
"""
    child = procs.spawn_detached(_python(script, marker))
    watch = _Watch([child.pid])
    try:
        watch.wait_dead(30)
        assert watch.exit_codes() == [0] and marker.read_text() == "''"
    finally:
        watch.kill()


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
    raw = subprocess.Popen(_python(_CONSOLE_REPORT, control, "spawn", script), creationflags=_DETACHED_PROCESS,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait_for(ours.exists, 30)
    _wait_for(control.exists, 30)
    raw.wait(30)
    mine, theirs = json.loads(ours.read_text()), json.loads(control.read_text())
    print(f"facade: {mine}; DETACHED_PROCESS: {theirs}")
    assert flags[-1] & (_CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW) == _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
    assert not flags[-1] & (_DETACHED_PROCESS | _CREATE_NEW_CONSOLE)
    assert mine["pid"] == child.pid and child.pid in mine["console"]
    assert child.pid in mine["grandchild"]["console"]
    assert theirs["console"] == [] and theirs["pid"] not in theirs["grandchild"]["console"]


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


# ==========================================================================
# Windows: owned asyncio children
# ==========================================================================

#: The owned child: start a sleeping grandchild, publish
#: {"pid", "grandchild", "event"} to the ready file, then act by mode.
#:   plain     sleep
#:   break     on SIGBREAK, note "sigbreak" and exit 7
#:   default   no handler: a console event ends it
#:   event     ignore SIGBREAK; when the stop event is set, note "event", exit 8
#:   stubborn  ignore SIGBREAK, never look at the event
#:   holder    the grandchild holds this child's stderr; exit at once
#:   detach    start a detached run (procs.spawn_detached) and report it too
_OWNED_CHILD = _PUBLISH + r"""
import ctypes, json, os, signal, subprocess, sys, time
from pathlib import Path
ready, mode = Path(sys.argv[1]), sys.argv[2]
note = Path(str(ready) + ".note")
sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
grandchild = subprocess.Popen(sleeper, stderr=sys.stderr if mode == "holder" else subprocess.DEVNULL, **quiet)
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
    ready = tmp_path / name
    proc = await procs.async_owned_child(*_python(_OWNED_CHILD, ready, mode, _PURELIB), **streams)
    deadline = time.monotonic() + 20
    while not ready.exists():
        assert time.monotonic() < deadline, "the owned child never reported"
        await asyncio.sleep(.02)
    return proc, json.loads(ready.read_text())


def _owner(proc):
    from self_learn.primitives import _procs_windows as backend

    return backend._owned[proc]


def _active(job):
    import win32job

    return win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)["ActiveProcesses"]


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
        try:
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
            await asyncio.wait_for(proc.wait(), 10)
        finally:
            watch.kill()

    asyncio.run(main())


@windows
def test_windows_detached_run_started_by_an_owned_child_escapes_its_job(tmp_path):
    """A ``worker kick`` run by the web UI starts a detached worker from inside
    an owned child: it breaks away, and survives the release of the child's
    job."""

    async def main():
        proc, report = await _owned(tmp_path, "detach")
        watch = _Watch([report["grandchild"], report["detached"]])
        try:
            assert report["broke_away"] is True and not _in_job(report["detached"], _owner(proc).job)
            procs.release_owned(proc)
            _wait_for(lambda: watch.alive() == [False, True])
            time.sleep(0.3)
            assert watch.alive() == [False, True]
        finally:
            watch.kill()

    asyncio.run(main())


@windows
def test_windows_cancel_stops_the_tree(tmp_path):
    """The web UI's pattern: a task waiting on ``communicate`` is cancelled,
    and its ``except CancelledError`` runs ``terminate_owned`` before
    re-raising. The cancellation propagates and nothing survives."""

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
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
            assert watch.alive() == [False, False] and _active(_owner(proc).job) == 0
            assert proc.returncode == 1
        finally:
            watch.kill()

    asyncio.run(main())


@windows
def test_windows_soft_stop_then_hard_stop_leaves_no_survivor(tmp_path):
    """A child that ignores the soft stop is hard-stopped after the grace, and
    the hard stop takes the grandchild too. A further stop finds nothing."""

    async def main():
        proc, report = await _owned(tmp_path, "stubborn")
        watch = _Watch([report["pid"], report["grandchild"]])
        try:
            started = time.monotonic()
            await procs.terminate_owned(proc, kill_grace=1.0)
            elapsed = time.monotonic() - started
            assert 1.0 <= elapsed < 5, elapsed
            assert proc.returncode == 1 and watch.exit_codes()[0] == 1 and watch.alive() == [False, False]
            assert _active(_owner(proc).job) == 0
            assert procs.stop_owned(proc, hard=False) is False and procs.stop_owned(proc, hard=True) is False
        finally:
            watch.kill()

    asyncio.run(main())


@windows
def test_windows_hard_stop_alone_kills_the_whole_job(tmp_path):
    async def main():
        proc, report = await _owned(tmp_path)
        watch = _Watch([report["pid"], report["grandchild"]])
        try:
            assert procs.stop_owned(proc, hard=True) is True
            watch.wait_dead()
            assert await asyncio.wait_for(proc.wait(), 10) == 1
        finally:
            watch.kill()

    asyncio.run(main())


@windows
def test_windows_watchdog_timeout_then_terminate(tmp_path):
    """A child that writes nothing trips the reader's own deadline; the
    terminate that follows is bounded and leaves nothing running."""

    async def main():
        proc, report = await _owned(tmp_path, "stubborn", stdout=asyncio.subprocess.PIPE)
        watch = _Watch([report["pid"], report["grandchild"]])
        try:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.5):
                    await proc.stdout.readline()
            started = time.monotonic()
            await procs.terminate_owned(proc, kill_grace=0.5)
            assert time.monotonic() - started < 5
            assert watch.alive() == [False, False]
        finally:
            watch.kill()

    asyncio.run(main())


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
        try:
            assert await asyncio.wait_for(proc.wait(), 10) == 0
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(proc.stderr.read(), 1.0)
            assert watch.alive() == [True]
            await procs.terminate_owned(proc, kill_grace=2.0)
            assert await asyncio.wait_for(proc.stderr.read(), 5) == b""
            assert watch.alive() == [False]
        finally:
            watch.kill()

    asyncio.run(main())


@windows
def test_windows_dropping_the_process_object_kills_the_tree(tmp_path):
    async def main():
        proc, report = await _owned(tmp_path)
        watch = _Watch([report["pid"], report["grandchild"]])
        del proc
        gc.collect()
        try:
            watch.wait_dead()
        finally:
            watch.kill()

    asyncio.run(main())


@windows
def test_windows_a_process_started_elsewhere_is_stopped_alone(tmp_path):
    """No job, no event, no console group of ours: both stops terminate that
    one process, and report ``False`` once it has exited."""

    async def main():
        proc = await asyncio.create_subprocess_exec(*_python("import time; time.sleep(60)"))
        assert procs.stop_owned(proc, hard=False) is True
        await asyncio.wait_for(proc.wait(), 10)
        assert procs.stop_owned(proc, hard=False) is False and procs.stop_owned(proc, hard=True) is False
        procs.release_owned(proc)

    asyncio.run(main())


@windows
def test_windows_selector_loop_refuses_before_anything_starts(tmp_path):
    """Only the Proactor loop can run subprocesses on Windows: under a Selector
    loop asyncio raises NotImplementedError and no child ever runs."""
    ready = tmp_path / "child"
    loop = asyncio.SelectorEventLoop()
    try:
        with pytest.raises(NotImplementedError):
            loop.run_until_complete(procs.async_owned_child(*_python(_OWNED_CHILD, ready, "plain", _PURELIB)))
    finally:
        loop.close()
    time.sleep(1.0)
    assert not ready.exists()


#: Run one owned child to a soft stop in a launcher whose console is chosen by
#: the test, and report what happened.
_SOFT_LAUNCHER = _PUBLISH + r"""
import asyncio, json, sys, time
from pathlib import Path
site_dir, out, mode, child = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
import site
site.addsitedir(site_dir)
import win32api, win32con, win32event, win32process
from self_learn.primitives import procs
from self_learn.primitives import _procs_windows as backend

async def main():
    ready = Path(str(out) + ".child")
    proc = await procs.async_owned_child(sys.executable, "-u", "-c", child, str(ready), mode, site_dir)
    while not ready.exists():
        await asyncio.sleep(.02)
    pids = json.loads(ready.read_text())
    pinned = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pids["grandchild"])
    started = time.monotonic()
    await procs.terminate_owned(proc, kill_grace=1.5)
    note = Path(str(ready) + ".note")
    return {"has_console": backend._has_console(), "shares_console": backend._owned[proc].shares_console,
            "code": proc.returncode, "elapsed": time.monotonic() - started,
            "note": note.read_text() if note.exists() else "",
            "grandchild_dead": win32event.WaitForSingleObject(pinned, 5000) == win32event.WAIT_OBJECT_0}

publish(out, json.dumps(asyncio.run(main())))
"""

#: (console, child mode) -> (exit status, note, hard stop needed)
_SOFT = {
    ("console", "break"): (7, "sigbreak", False),
    ("console", "default"): (_STATUS_CONTROL_C_EXIT, "", False),
    ("console", "event"): (8, "event", False),
    ("console", "stubborn"): (1, "", True),
    ("no-console", "break"): (1, "", True),
    ("no-console", "default"): (1, "", True),
    ("no-console", "event"): (8, "event", False),
    ("no-console", "stubborn"): (1, "", True),
}


@windows
@pytest.mark.parametrize("console, mode", sorted(_SOFT))
def test_windows_what_the_soft_stop_reaches(tmp_path, console, mode):
    """Measured: with a shared console a Python child receives ``SIGBREAK``
    (and with no handler exits ``0xC000013A``); a child whose console is its
    own receives no console event at all, only the stop event. A child that
    observes neither is hard-stopped after the grace. Every case leaves the
    grandchild dead."""
    out = tmp_path / "report"
    flags = _CREATE_NEW_CONSOLE if console == "console" else _DETACHED_PROCESS
    launcher = subprocess.Popen(_python(_SOFT_LAUNCHER, _PURELIB, out, mode, textwrap.dedent(_OWNED_CHILD)),
                                creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    try:
        assert launcher.wait(60) == 0
        report = json.loads(out.read_text())
    finally:
        _kill_tree(launcher.pid)
    print(f"{console}/{mode}: {report}")
    code, note, hard = _SOFT[(console, mode)]
    assert report["has_console"] is report["shares_console"] is (console == "console")
    assert (report["code"], report["note"], report["grandchild_dead"]) == (code, note, True)
    assert (report["elapsed"] >= 1.5) is hard, report["elapsed"]
