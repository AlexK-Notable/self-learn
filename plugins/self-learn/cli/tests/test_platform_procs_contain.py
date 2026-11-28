"""S-NEXT-w6-procs. Identify and contain a child process that someone else spawned.

The Agent SDK spawns Claude Code itself, so self-learn can only act on the
child after the fact. These tests drive the four procs calls that let it do so:
``process_identity``, ``contain_child``, ``terminate_contained`` and
``contain_self``. Windows tests use a Python stand-in for Claude Code that
spawns a grandchild and sleeps; Linux tests compare the copies with the code
in ``sdksession/children.py`` and ``sdksession/teardown.py`` they were taken
from.
"""

from __future__ import annotations

import gc
import json
import os
import signal
import subprocess
import sys
import sysconfig
import textwrap
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from self_learn.primitives import procs


windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows process contract")
linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux process contract")

#: The interpreter itself, not the venv redirector (on Windows a venv's
#: python.exe is a launcher whose PID differs from the Python it starts).
_BASE = getattr(sys, "_base_executable", sys.executable)


def _python(script, *args, exe=_BASE):
    return [exe, "-u", "-c", textwrap.dedent(script), *map(str, args)]


def _wait_for(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "process observation timed out"
        time.sleep(0.02)


#: The stand-in for Claude Code: spawn a grandchild (optionally a chain of
#: them), write "<own pid> <grandchild pid> ..." to the ready file, then
#: sleep. Each generation is the base interpreter, so every PID is real.
_STANDIN = r"""
import os, subprocess, sys, time
from pathlib import Path
ready, depth = Path(sys.argv[1]), int(sys.argv[2])
pids = [os.getpid()]
if depth:
    child = subprocess.Popen([sys.executable, "-u", "-c", sys.argv[3], str(ready) + ".g", str(depth - 1), sys.argv[3]])
    tail = Path(str(ready) + ".g")
    while not tail.exists():
        time.sleep(.005)
    pids += tail.read_text().split()
ready.write_text(" ".join(map(str, pids)))
time.sleep(120)
"""


def _standin(directory, name="standin", depth=1):
    ready = directory / name
    proc = subprocess.Popen(_python(_STANDIN, ready, depth, _STANDIN))
    _wait_for(ready.exists)
    _wait_for(lambda: len(ready.read_text().split()) == depth + 1)
    return proc, [int(pid) for pid in ready.read_text().split()]


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

    def wait_dead(self, seconds=10.0):
        _wait_for(lambda: not any(self.alive()), seconds)

    def kill(self):
        import win32process

        import pywintypes

        for handle, alive in zip(self.handles, self.alive()):
            if alive:
                try:
                    win32process.TerminateProcess(handle, 1)
                except pywintypes.error:  # already exiting
                    pass


def _in_job(pid, job):
    import win32api
    import win32con
    import win32job

    handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    try:
        return win32job.IsProcessInJob(handle, job)
    finally:
        win32api.CloseHandle(handle)


def _bare_job():
    import win32job
    from uuid import uuid4

    job = win32job.CreateJobObject(None, uuid4().hex)
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


# --------------------------------------------------------------------------
# Windows: containment of a running child and its grandchild
# --------------------------------------------------------------------------


@windows
def test_windows_grandchild_outlives_child_without_containment(tmp_path):
    # Positive control for every containment test below.
    import win32process

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        procs.terminate_contained(procs.contain_child(child))
        _wait_for(lambda: watch.alive() == [False, True])
        time.sleep(0.3)
        assert watch.alive() == [False, True]
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_contain_then_terminate_kills_child_and_grandchild(tmp_path):
    from self_learn.primitives import _procs_windows as backend

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        handle = procs.contain_child(child)
        assert handle is not None and handle.pid == child
        assert handle.identity == procs.process_identity(child)
        assert handle.adopted == (grandchild,)
        assert _in_job(child, handle._job) and _in_job(grandchild, handle._job)
        assert backend._active_processes(handle._job) == 2
        assert watch.alive() == [True, True]
        procs.terminate_contained(handle)
        assert watch.alive() == [False, False]
        assert handle.released
        procs.terminate_contained(handle)  # a second call is a no-op
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_dropping_the_handle_kills_the_child(tmp_path):
    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        handle = procs.contain_child(child)
        assert watch.alive() == [True, True]
        del handle
        gc.collect()
        watch.wait_dead()
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_early_grandchild_race_is_closed_by_adoption(tmp_path):
    import win32api
    import win32con
    import win32job

    # Control: a bare assignment after the grandchild exists leaves it outside.
    proc, (child, grandchild) = _standin(tmp_path, "control")
    watch = _Watch([child, grandchild])
    bare = _bare_job()
    try:
        opened = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, child)
        win32job.AssignProcessToJobObject(bare, opened)
        win32api.CloseHandle(opened)
        assert _in_job(child, bare) and not _in_job(grandchild, bare)
        win32job.TerminateJobObject(bare, 1)
        _wait_for(lambda: watch.alive() == [False, True])
    finally:
        watch.kill()
        proc.wait(timeout=5)

    # contain_child adopts every generation spawned before the assignment.
    proc, pids = _standin(tmp_path, "chain", depth=3)
    watch = _Watch(pids)
    try:
        handle = procs.contain_child(pids[0])
        assert sorted(handle.adopted) == sorted(pids[1:])
        assert handle.complete and not handle.uncovered
        assert all(_in_job(pid, handle._job) for pid in pids)
        procs.terminate_contained(handle)
        assert not any(watch.alive())
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_early_grandchild_race_measured(tmp_path):
    """Measure the window: the stand-in spawns its grandchild as soon as it
    starts, and contain_child runs as soon as Popen returns. The assertion is
    the deterministic part: every grandchild ends up in the job, whether it
    inherited the job or was adopted; the timings are printed for the report."""
    trials = []
    for trial in range(8):
        ready = tmp_path / f"race{trial}"
        start = time.perf_counter()
        proc = subprocess.Popen(_python(_STANDIN, ready, 1, _STANDIN))
        spawned = time.perf_counter()
        handle = procs.contain_child(proc.pid)
        contained = time.perf_counter()
        try:
            assert handle is not None
            _wait_for(lambda: ready.exists() and len(ready.read_text().split()) == 2)
            grandchild = int(ready.read_text().split()[1])
            watch = _Watch([proc.pid, grandchild])
            assert _in_job(grandchild, handle._job)
            grandchild_created = procs.process_identity(grandchild).created
            trials.append({
                "popen_ms": round((spawned - start) * 1e3, 2),
                "assign_after_popen_ms": round((contained - spawned) * 1e3, 3),
                "grandchild_after_child_ms": (grandchild_created - handle.identity.created) / 1e3,
                "adopted": grandchild in handle.adopted,
            })
            procs.terminate_contained(handle)
            # The child is held and waited for; an inherited grandchild is
            # counted by the job, whose count can lead its exit by a moment.
            assert watch.alive()[0] is False
            watch.wait_dead(2)
        finally:
            if not handle.released:
                procs.terminate_contained(handle)
            proc.wait(timeout=5)
    print("RACE", json.dumps(trials))


@windows
def test_windows_orphaned_great_grandchild_is_the_uncovered_gap(tmp_path):
    """What adoption cannot reach: a descendant whose parent exited before the
    assignment has no live link to the child, so it stays outside the job."""
    middle = r"""
import subprocess, sys, time
from pathlib import Path
leaf = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
Path(sys.argv[1]).write_text(str(leaf.pid))
time.sleep(120)
"""
    script = r"""
import subprocess, sys, time
from pathlib import Path
subprocess.Popen([sys.executable, "-c", sys.argv[2], sys.argv[1]])
while not Path(sys.argv[1]).exists(): time.sleep(.01)
Path(sys.argv[1] + ".done").write_text("")
time.sleep(120)
"""
    marker = tmp_path / "leaf"
    proc = subprocess.Popen(_python(script, marker, middle))
    _wait_for(lambda: (tmp_path / "leaf.done").exists())
    leaf = int(marker.read_text())
    watch = _Watch([proc.pid, leaf])
    try:
        handle = procs.contain_child(proc.pid)
        assert handle.complete and leaf not in handle.adopted
        assert not _in_job(leaf, handle._job)
        procs.terminate_contained(handle)
        _wait_for(lambda: watch.alive() == [False, True])
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_adoption_refuses_a_process_older_than_its_claimed_parent(tmp_path, monkeypatch):
    """A snapshot entry naming our child as parent is adopted only if it was
    created after the child: an older process got that parent PID from an
    earlier owner of the number."""
    from self_learn.primitives import _procs_windows as backend

    sleeper = _python("import time; time.sleep(120)")
    older = subprocess.Popen(sleeper)
    time.sleep(0.05)
    proc, (child, grandchild) = _standin(tmp_path)
    time.sleep(0.05)
    newer = subprocess.Popen(sleeper)
    watch = _Watch([child, grandchild, older.pid, newer.pid])
    real = backend._process_parents
    monkeypatch.setattr(backend, "_process_parents",
                        lambda: real() + [(older.pid, child), (newer.pid, child)])
    try:
        handle = procs.contain_child(child)
        assert newer.pid in handle.adopted  # control: the newer one is taken
        assert older.pid not in handle.adopted
        procs.terminate_contained(handle)
        assert watch.alive() == [False, False, True, False]
    finally:
        watch.kill()
        for p in (proc, older, newer):
            p.wait(timeout=5)


# --------------------------------------------------------------------------
# Windows: the containing process dies abruptly
# --------------------------------------------------------------------------

_HELPER = r"""
import json, os, site, subprocess, sys, time
from pathlib import Path
site.addsitedir(sys.argv[1])
import win32api, win32job
from self_learn.primitives import procs
mode, out, standin = sys.argv[2], Path(sys.argv[3]), sys.argv[4]
go = Path(str(out) + ".go")
while not go.exists():
    time.sleep(.005)
report = {"in_job_before": win32job.IsProcessInJob(win32api.GetCurrentProcess(), None)}
if mode == "none": procs.contain_self()
if mode == "self":
    report["first"] = procs.contain_self()
    report["second"] = procs.contain_self()
    from self_learn.primitives import _procs_windows as backend
    report["self_jobs"] = len(backend._self_job)
    away = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=0x01000000)
    report["breakaway"] = away.pid
ready = Path(str(out) + ".standin")
child = subprocess.Popen([sys.executable, "-u", "-c", standin, str(ready), "1", standin])
while not (ready.exists() and len(ready.read_text().split()) == 2):
    time.sleep(.005)
report["pids"] = [int(p) for p in ready.read_text().split()]
if mode == "child":
    handle = procs.contain_child(child.pid)
    report["adopted"] = list(handle.adopted)
report["helper"] = os.getpid()
out.write_text(json.dumps(report))
time.sleep(120)
"""


@windows
@pytest.mark.parametrize("mode", ["none", "child", "self"])
def test_windows_abrupt_death_of_the_container(tmp_path, mode):
    import win32api
    import win32con
    import win32job
    import win32process

    out = tmp_path / "report"
    helper = subprocess.Popen(_python(_HELPER, sysconfig.get_paths()["purelib"], mode, out, _STANDIN))
    # An outer job the helper is already in when it contains itself (the
    # runner and many terminals do the same); plain, so it kills nothing.
    outer = win32job.CreateJobObject(None, f"outer-{os.getpid()}-{mode}")
    opened = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, helper.pid)
    win32job.AssignProcessToJobObject(outer, opened)
    win32api.CloseHandle(opened)
    (tmp_path / "report.go").write_text("")
    _wait_for(lambda: out.exists())
    report = json.loads(out.read_text())
    assert report["helper"] == helper.pid and report["in_job_before"]
    pids = report["pids"]
    extra = [report["breakaway"]] if mode == "self" else []
    watch = _Watch([*pids, *extra])
    try:
        win32process.TerminateProcess(watch_helper := win32api.OpenProcess(
            win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE, False, helper.pid), 9)
        helper.wait(timeout=5)
        win32api.CloseHandle(watch_helper)
        if mode == "none":
            time.sleep(0.5)
            assert watch.alive() == [True, True]
        else:
            _wait_for(lambda: watch.alive()[:2] == [False, False])
        if mode == "child":
            assert report["adopted"] == pids[1:]  # spawned before the assignment
        if mode == "self":
            assert (report["first"], report["second"], report["self_jobs"]) == (True, True, 1)
            time.sleep(0.3)
            assert watch.alive()[2], "a breakaway child must outlive the contained process"
    finally:
        watch.kill()
        win32api.CloseHandle(outer)


# --------------------------------------------------------------------------
# Windows: identity, nesting, refusals and errors
# --------------------------------------------------------------------------


@windows
def test_windows_identity_tells_a_reused_pid_apart(tmp_path, monkeypatch):
    import win32job
    import win32process
    from datetime import timedelta

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        first = procs.process_identity(child)
        assert first == procs.process_identity(child)
        assert os.path.samefile(first.image, _BASE)
        assert abs(first.created / 1e6 - time.time()) < 120
        assert first.cmdline is None

        # Same PID, different creation time, injected at the real call.
        real = win32process.GetProcessTimes
        def later(handle):
            times = real(handle)
            return {**times, "CreationTime": times["CreationTime"] + timedelta(milliseconds=1)}
        assign = Mock(wraps=win32job.AssignProcessToJobObject)
        with monkeypatch.context() as patch:
            patch.setattr(win32process, "GetProcessTimes", later)
            patch.setattr(win32job, "AssignProcessToJobObject", assign)
            second = procs.process_identity(child)
            assert second.image == first.image and second.created == first.created + 1000
            assert second != first
            assert procs.contain_child(child, expect=first) is None
            assign.assert_not_called()
        handle = procs.contain_child(child, expect=first)  # control: the true identity
        assert handle is not None
        procs.terminate_contained(handle)
        assert not any(watch.alive())
    finally:
        watch.kill()
        proc.wait(timeout=5)

    assert procs.process_identity(0) is None and procs.process_identity(-1) is None
    assert procs.contain_child(0) is None


@windows
def test_windows_identity_and_contain_of_missing_pid(tmp_path):
    proc = subprocess.Popen(_python("pass"))
    proc.wait(timeout=10)
    # Windows PIDs are multiples of four; find a free one without assuming.
    gone = next(pid for pid in range(0x7FFFFFFC, 0, -4) if not procs.pid_alive(pid))
    assert procs.process_identity(gone) is None
    assert procs.contain_child(gone) is None


@windows
@pytest.mark.parametrize("code, expected", [("ERROR_ACCESS_DENIED", None), ("ERROR_INVALID_HANDLE", OSError)])
def test_windows_identity_open_errors(monkeypatch, code, expected):
    import pywintypes
    import win32api
    import winerror

    failure = pywintypes.error(getattr(winerror, code), "OpenProcess", "injected")
    monkeypatch.setattr(win32api, "OpenProcess", Mock(side_effect=failure))
    if expected is None:
        assert procs.process_identity(os.getpid()) is None
    else:
        with pytest.raises(OSError) as caught:
            procs.process_identity(os.getpid())
        assert caught.value.winerror == failure.winerror and caught.value.__cause__ is failure


@windows
@pytest.mark.parametrize("site", ["GetProcessTimes", "QueryFullProcessImageNameW"])
def test_windows_identity_errors_carry_winerror_and_cause(monkeypatch, site):
    import pywintypes
    import win32process
    import winerror
    from self_learn.primitives import _procs_windows as backend

    if site == "GetProcessTimes":
        failure = pywintypes.error(winerror.ERROR_INVALID_HANDLE, site, "injected")
        monkeypatch.setattr(win32process, site, Mock(side_effect=failure))
    else:
        failure = OSError(0, "injected", None, winerror.ERROR_INSUFFICIENT_BUFFER)
        monkeypatch.setattr(backend, "_image_of", Mock(side_effect=failure))
    with pytest.raises(OSError) as caught:
        procs.process_identity(os.getpid())
    assert caught.value.winerror == failure.winerror and caught.value.__cause__ is failure


@windows
def test_windows_contain_child_already_in_a_job(tmp_path):
    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    outer = _bare_job()
    try:
        import win32api
        import win32con
        import win32job

        opened = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, child)
        win32job.AssignProcessToJobObject(outer, opened)
        win32api.CloseHandle(opened)
        handle = procs.contain_child(child)
        assert _in_job(child, outer) and _in_job(child, handle._job)
        assert grandchild in handle.adopted
        procs.terminate_contained(handle)
        assert not any(watch.alive())
    finally:
        watch.kill()
        import win32api

        win32api.CloseHandle(outer)
        proc.wait(timeout=5)


@windows
def test_windows_refused_assignment_surfaces_winerror_and_kills_nothing(tmp_path, monkeypatch):
    import pywintypes
    import win32job
    import winerror

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    created = []
    real_create = win32job.CreateJobObject
    def record(*args):
        job = real_create(*args)
        created.append(job)
        return job
    try:
        failure = pywintypes.error(winerror.ERROR_ACCESS_DENIED, "AssignProcessToJobObject", "injected")
        with monkeypatch.context() as patch:
            patch.setattr(win32job, "CreateJobObject", record)
            patch.setattr(win32job, "AssignProcessToJobObject", Mock(side_effect=failure))
            with pytest.raises(OSError) as caught:
                procs.contain_child(child)
        assert caught.value.winerror == winerror.ERROR_ACCESS_DENIED
        assert caught.value.__cause__ is failure
        assert len(created) == 1 and int(created[0]) == 0  # the job was released
        time.sleep(0.2)
        assert watch.alive() == [True, True]

        # A real refusal: the System process cannot be opened to be assigned.
        with pytest.raises(OSError) as caught:
            procs.contain_child(4)
        assert caught.value.winerror == winerror.ERROR_ACCESS_DENIED
        assert isinstance(caught.value.__cause__, pywintypes.error)
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_terminate_is_bounded(tmp_path, monkeypatch):
    from self_learn.primitives import _procs_windows as backend

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        handle = procs.contain_child(child)
        monkeypatch.setattr(backend, "_active_processes", lambda job: 1)
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            backend.terminate_contained(handle, timeout=0.3)
        assert 0.3 <= time.monotonic() - start < 3
        assert handle.released
        watch.wait_dead()
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_job_flags_allow_breakaway_and_kill_on_close(tmp_path):
    import win32job

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        handle = procs.contain_child(child)
        info = win32job.QueryInformationJobObject(handle._job, win32job.JobObjectExtendedLimitInformation)
        flags = info["BasicLimitInformation"]["LimitFlags"]
        assert flags & win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        assert flags & win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
        assert not flags & win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
        procs.terminate_contained(handle)
    finally:
        watch.kill()
        proc.wait(timeout=5)


# --------------------------------------------------------------------------
# Linux: the copies behave exactly like the code they were copied from
# --------------------------------------------------------------------------


def _sleeper(*, argv0=None, new_session=False):
    argv = [argv0 or sys.executable, "-c", "import time; time.sleep(60)"]
    return subprocess.Popen(argv, executable=sys.executable, start_new_session=new_session)


@linux
@pytest.mark.parametrize("argv0", [None, b"claude-\xff\xfe"])
def test_identity_reads_what_the_orphan_sweep_reads(tmp_path, monkeypatch, argv0):
    from self_learn.sdksession import children, teardown
    from self_learn.sdksession.policy import ShutdownMessages

    proc = _sleeper(argv0=argv0)
    try:
        _wait_for(lambda: Path(f"/proc/{proc.pid}/cmdline").read_bytes()[:1] not in (b"",))
        reads = []
        real_read = Path.read_bytes
        def spy(path):
            data = real_read(path)
            if str(path).endswith("/cmdline"):
                reads.append((str(path), data))
            return data
        monkeypatch.setattr(Path, "read_bytes", spy)
        killed = []
        monkeypatch.setattr(teardown, "kill_child", lambda pid, log, alive: killed.append(pid))
        identity = procs.process_identity(proc.pid)
        # The sweep matches on the program's basename; give it this one.
        basename = os.path.basename(identity.image)
        record = {"pid": proc.pid, "started_at": 0.0, "cli": basename}
        children._sweep_one(tmp_path, "probe", None, record, log=lambda line: None,
                            pid_alive=lambda pid: True, process_start=1.0,
                            messages=ShutdownMessages(abandoned_cancelled="", abandoned_finished="",
                                                      abandoned_completed="", disconnect_timeout="",
                                                      disconnect_raised=""))
        assert killed == [proc.pid]  # the sweep corroborated the same program
        assert len(reads) == 2 and reads[0] == reads[1]
        path, raw = reads[1]
        assert path == f"/proc/{proc.pid}/cmdline"
        assert identity.cmdline == raw
        assert identity.image == raw.split(b"\x00")[0].decode("utf-8", "replace")
        assert identity.created is None
    finally:
        proc.kill()
        proc.wait(timeout=5)


@linux
def test_identity_is_none_where_the_sweep_reads_nothing(monkeypatch):
    proc = _sleeper()
    proc.kill()
    proc.wait(timeout=5)
    with pytest.raises(OSError):
        Path(f"/proc/{proc.pid}/cmdline").read_bytes()
    assert procs.process_identity(proc.pid) is None

    def denied(path):
        raise PermissionError(13, "denied", str(path))
    monkeypatch.setattr(Path, "read_bytes", denied)
    assert procs.process_identity(os.getpid()) is None
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=RuntimeError("not an OSError")))
    with pytest.raises(RuntimeError):
        procs.process_identity(os.getpid())


def _recorder(monkeypatch, getpgid, killpg=None, kill=None):
    calls = []
    def record(name, behaviour):
        def call(*args):
            calls.append((name, *args))
            if isinstance(behaviour, BaseException):
                raise behaviour
            return behaviour(*args) if callable(behaviour) else None
        return call
    monkeypatch.setattr(os, "getpgid", record("getpgid", getpgid))
    monkeypatch.setattr(os, "killpg", record("killpg", killpg))
    monkeypatch.setattr(os, "kill", record("kill", kill))
    return calls


@linux
@pytest.mark.parametrize("case", ["other-group", "same-group", "lookup", "permission-kill",
                                  "permission-getpgid", "other-error"])
def test_kill_body_makes_the_same_calls_as_teardown(monkeypatch, case):
    from self_learn.sdksession import teardown

    getpgid = {"other-group": lambda pid: 100 if pid == 0 else 200,
               "lookup": ProcessLookupError(3, "gone"),
               "permission-getpgid": PermissionError(1, "denied"),
               "other-error": OSError(22, "invalid")}.get(case, lambda pid: 100)
    killpg = ProcessLookupError(3, "gone") if case == "lookup" else None
    kill = PermissionError(1, "denied") if case == "permission-kill" else None
    outcomes = []
    for run in (lambda: teardown.kill_child(4242, lambda line: None, lambda pid: True),
                lambda: procs.terminate_contained(procs.contain_child(4242))):
        with monkeypatch.context() as patch:
            calls = _recorder(patch, getpgid, killpg, kill)
            try:
                run()
            except OSError as exc:
                outcomes.append((calls, type(exc), exc.errno))
            else:
                outcomes.append((calls, None, None))
    assert outcomes[0] == outcomes[1]
    calls, raised, _ = outcomes[1]
    assert calls  # control: the body ran at all
    if case == "other-group":
        assert calls == [("getpgid", 4242), ("getpgid", 0), ("killpg", 4242, signal.SIGKILL)]
    if case == "same-group":
        assert calls == [("getpgid", 4242), ("getpgid", 0), ("kill", 4242, signal.SIGKILL)]
    assert raised is (OSError if case == "other-error" else None)


@linux
def test_terminate_kills_a_real_process_group(tmp_path):
    script = textwrap.dedent("""
        import subprocess, sys, time
        from pathlib import Path
        g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(sys.argv[1]).write_text(str(g.pid))
        time.sleep(60)
    """)
    def leader():
        marker = tmp_path / f"g{len(list(tmp_path.iterdir()))}"
        proc = subprocess.Popen([sys.executable, "-c", script, str(marker)], start_new_session=True)
        _wait_for(marker.exists)
        return proc, int(marker.read_text())

    def dead(pid):
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
        except FileNotFoundError:
            return True

    # Control: killing only the leader leaves the grandchild running.
    proc, grandchild = leader()
    try:
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        time.sleep(0.2)
        assert not dead(grandchild)
    finally:
        os.kill(grandchild, signal.SIGKILL)

    proc, grandchild = leader()
    handle = procs.contain_child(proc.pid)
    procs.terminate_contained(handle)
    proc.wait(timeout=5)
    _wait_for(lambda: dead(grandchild))


@linux
def test_contain_child_and_contain_self_make_no_calls(monkeypatch, tmp_path):
    proc = _sleeper()
    try:
        audit = []
        for name in ("getpgid", "killpg", "kill", "getpgrp", "setsid", "setpgid"):
            monkeypatch.setattr(os, name, Mock(side_effect=AssertionError(name)))
        real_read = Path.read_bytes
        monkeypatch.setattr(Path, "read_bytes", lambda path: audit.append(str(path)) or real_read(path))
        assert procs.contain_self() is False
        handle = procs.contain_child(proc.pid)
        assert handle.pid == proc.pid and audit == []
        monkeypatch.undo()
        identity = procs.process_identity(proc.pid)
        assert procs.contain_child(proc.pid, expect=identity) == handle
        other = procs.ProcessIdentity(image=identity.image + "x", created=None, cmdline=identity.cmdline)
        assert procs.contain_child(proc.pid, expect=other) is None
    finally:
        proc.kill()
        proc.wait(timeout=5)


@linux
def test_containment_names_never_load_windows_modules_on_linux():
    script = """
        import sys
        from types import SimpleNamespace
        from self_learn.primitives import procs
        procs.os = SimpleNamespace(name="nt")
        calls = (lambda: procs.process_identity(1), lambda: procs.contain_child(1),
                 lambda: procs.terminate_contained(object()), lambda: procs.contain_self())
        for call in calls:
            try:
                call()
            except NotImplementedError:
                pass
            else:
                raise AssertionError("a containment call returned on Windows")
        loaded = [m for m in sys.modules if m.startswith(("win32", "pywintypes", "_winapi"))]
        assert not loaded, loaded
        assert "self_learn.primitives._procs_posix" not in sys.modules
        print("ok")
    """
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], capture_output=True,
                          text=True, timeout=30, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_handles_and_identities_are_plain_values():
    identity = procs.ProcessIdentity(image="claude", created=1, cmdline=None)
    assert identity == procs.ProcessIdentity("claude", 1) and hash(identity) == hash(procs.ProcessIdentity("claude", 1))
    assert identity != procs.ProcessIdentity("claude", 2)
    with pytest.raises(AttributeError):
        identity.created = 2  # type: ignore[misc]
