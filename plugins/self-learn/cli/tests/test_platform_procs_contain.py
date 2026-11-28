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
#: FILETIME ticks (100 ns) between 1601-01-01 and 1970-01-01.
_UNIX_EPOCH_TICKS = 116444736000000000
_BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB


def _python(script, *args, exe=_BASE):
    return [exe, "-u", "-c", textwrap.dedent(script), *map(str, args)]


def _wait_for(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "process observation timed out"
        time.sleep(0.02)


#: Every helper below publishes a file by writing a sibling and renaming it,
#: so a reader that sees the name always sees the whole content.
_PUBLISH = r"""
def publish(path, text):
    import os
    temp = str(path) + ".tmp"
    with open(temp, "w") as stream:
        stream.write(text)
    os.replace(temp, str(path))
"""

#: The stand-in for Claude Code: spawn a grandchild (optionally a chain of
#: them), publish "<own pid> <grandchild pid> ..." to the ready file, then
#: sleep. Each generation is the base interpreter, so every PID is real.
#: Mode "early-away": first spawn a breakaway sleeper and publish its PID to
#: "<ready>.away". Mode "late-away": after publishing, wait for "<ready>.go"
#: and then spawn a breakaway sleeper, publishing its PID to "<ready>.late".
_STANDIN = _PUBLISH + r"""
import os, subprocess, sys, time
from pathlib import Path
ready, depth, mode = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[4]
sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
if mode == "early-away":
    away = subprocess.Popen(sleeper, creationflags=0x01000000)
    publish(str(ready) + ".away", str(away.pid))
pids = [os.getpid()]
if depth:
    child = subprocess.Popen([sys.executable, "-u", "-c", sys.argv[3], str(ready) + ".g", str(depth - 1),
                              sys.argv[3], "plain"])
    tail = Path(str(ready) + ".g")
    while not tail.exists():
        time.sleep(.005)
    pids += tail.read_text().split()
publish(ready, " ".join(map(str, pids)))
if mode == "late-away":
    while not Path(str(ready) + ".go").exists():
        time.sleep(.005)
    late = subprocess.Popen(sleeper, creationflags=0x01000000)
    publish(str(ready) + ".late", str(late.pid))
time.sleep(120)
"""


def _standin(directory, name="standin", depth=1, mode="plain"):
    ready = directory / name
    proc = subprocess.Popen(_python(_STANDIN, ready, depth, _STANDIN, mode))
    try:
        _wait_for(ready.exists)
    except BaseException:
        proc.kill()
        raise
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


def _in_job(pid, job):
    import win32api
    import win32con
    import win32job

    handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    try:
        return win32job.IsProcessInJob(handle, job)
    finally:
        win32api.CloseHandle(handle)


def _bare_job(flags=None):
    import win32job
    from uuid import uuid4

    job = win32job.CreateJobObject(None, uuid4().hex)
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    extra = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE if flags is None else flags
    info["BasicLimitInformation"]["LimitFlags"] |= extra
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


def _set_last_error_and_fail(code):
    import ctypes

    def fail(*args):
        ctypes.set_last_error(code)
        return 0
    return fail


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
        assert watch.alive() == [True, True]
        win32process.TerminateProcess(watch.handles[0], 1)
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
        assert handle.adopted == (grandchild,) and handle.left_out == () and handle.uncovered == ()
        assert handle.complete
        assert _in_job(child, handle._job) and _in_job(grandchild, handle._job)
        assert backend._active_processes(handle._job) == 2
        assert len(handle._processes) == 2  # every member it relied on stays pinned
        assert watch.alive() == [True, True]
        procs.terminate_contained(handle)
        assert watch.alive() == [False, False]
        assert handle.released
        procs.terminate_contained(handle)  # a second call is a no-op
        procs.terminate_contained(None)
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
    import win32job

    # Control: a bare assignment after the grandchild exists leaves it outside.
    proc, (child, grandchild) = _standin(tmp_path, "control")
    watch = _Watch([child, grandchild])
    bare = _bare_job()
    try:
        _assign(bare, child)
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
        assert handle.complete and not handle.uncovered and not handle.left_out
        assert all(_in_job(pid, handle._job) for pid in pids)
        assert len(handle._processes) == 4
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
        proc = subprocess.Popen(_python(_STANDIN, ready, 1, _STANDIN, "plain"))
        handle = None
        try:
            spawned = time.perf_counter()
            handle = procs.contain_child(proc.pid)
            contained = time.perf_counter()
            assert handle is not None
            _wait_for(ready.exists)
            grandchild = int(ready.read_text().split()[1])
            watch = _Watch([proc.pid, grandchild])
            assert _in_job(grandchild, handle._job)
            grandchild_created = procs.process_identity(grandchild).created
            trials.append({
                "popen_ms": round((spawned - start) * 1e3, 2),
                "contain_after_popen_ms": round((contained - spawned) * 1e3, 3),
                "grandchild_after_child_ms": (grandchild_created - handle.identity.created) / 1e4,
                "adopted": grandchild in handle.adopted,
            })
            procs.terminate_contained(handle)
            # The child is held and waited for; an inherited grandchild is
            # counted by the job, whose count can lead its exit by a moment.
            assert watch.alive()[0] is False
            watch.wait_dead(2)
            watch.kill()
        finally:
            if handle is not None and not handle.released:
                procs.terminate_contained(handle)
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
    print("RACE", json.dumps(trials))


@windows
def test_windows_orphaned_great_grandchild_is_the_uncovered_gap(tmp_path):
    """What adoption cannot reach: a descendant whose parent exited before the
    assignment has no live link to the child, so it stays outside the job.
    Its living sibling, spawned by the child directly, is adopted (control)."""
    middle = _PUBLISH + r"""
import subprocess, sys
leaf = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
publish(sys.argv[1], str(leaf.pid))
"""
    script = _PUBLISH + r"""
import subprocess, sys, time
subprocess.run([sys.executable, "-c", sys.argv[2], sys.argv[1]], check=True)
sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
publish(sys.argv[1] + ".done", str(sibling.pid))
time.sleep(120)
"""
    marker = tmp_path / "leaf"
    proc = subprocess.Popen(_python(script, marker, middle))
    watch = None
    try:
        _wait_for(lambda: (tmp_path / "leaf.done").exists())
        leaf, sibling = int(marker.read_text()), int((tmp_path / "leaf.done").read_text())
        watch = _Watch([proc.pid, leaf, sibling])
        handle = procs.contain_child(proc.pid)
        assert handle.complete and handle.adopted == (sibling,)
        assert not _in_job(leaf, handle._job)
        procs.terminate_contained(handle)
        _wait_for(lambda: watch.alive() == [False, True, False])
    finally:
        if watch is not None:
            watch.kill()
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


@windows
def test_windows_stale_snapshot_row_never_puts_an_unrelated_process_in_the_job(tmp_path, monkeypatch):
    """A snapshot row can name our child as the parent of a number that now
    belongs to another process (the original exited and the number was
    reused). The candidate is judged on its own handle: its real parent is
    read from the process object, so an unrelated live process is left alone,
    however young it is."""
    from self_learn.primitives import _procs_windows as backend

    sleeper = _python("import time; time.sleep(120)")
    proc, (child, grandchild) = _standin(tmp_path)
    unrelated = subprocess.Popen(sleeper)  # younger than the child, parent is pytest
    watch = _Watch([child, grandchild, unrelated.pid])
    real = backend._process_parents
    monkeypatch.setattr(backend, "_process_parents", lambda: real() + [(unrelated.pid, child)])
    try:
        handle = procs.contain_child(child)
        assert handle.adopted == (grandchild,)  # control: the real grandchild is taken
        assert not _in_job(unrelated.pid, handle._job)
        procs.terminate_contained(handle)
        time.sleep(0.2)
        assert watch.alive() == [False, False, True]
    finally:
        watch.kill()
        for p in (proc, unrelated):
            p.wait(timeout=5)


@windows
@pytest.mark.parametrize("case", ["older", "tie"])
def test_windows_adoption_requires_a_strictly_younger_child(tmp_path, monkeypatch, case):
    """A process whose real parent number is our child's is ours only if it was
    created strictly after our child: an older one got that number from an
    earlier owner of it, and a tie cannot be told apart. Injected at the real
    calls: the candidate's recorded parent, and (for the tie) its creation
    time. The stand-in's real grandchild is the control."""
    from self_learn.primitives import _procs_windows as backend

    sleeper = _python("import time; time.sleep(120)")
    older = subprocess.Popen(sleeper)
    time.sleep(0.05)
    proc, (child, grandchild) = _standin(tmp_path)
    if case == "tie":
        older.kill()
        older.wait(timeout=5)
        older = subprocess.Popen(sleeper)  # younger, but reported with the child's time
    watch = _Watch([child, grandchild, older.pid])
    root_created = procs.process_identity(child).created
    real_parent, real_created, real_rows = backend._parent_of, backend._created_of, backend._process_parents
    import win32process

    def pid_of(process):
        return win32process.GetProcessId(process)
    monkeypatch.setattr(backend, "_process_parents", lambda: real_rows() + [(older.pid, child)])
    monkeypatch.setattr(backend, "_parent_of",
                        lambda process: child if pid_of(process) == older.pid else real_parent(process))
    if case == "tie":
        monkeypatch.setattr(backend, "_created_of",
                            lambda process: root_created if pid_of(process) == older.pid else real_created(process))
    try:
        handle = procs.contain_child(child)
        assert handle.adopted == (grandchild,)
        assert (older.pid, "not-younger-than-parent") in handle.left_out
        procs.terminate_contained(handle)
        time.sleep(0.2)
        assert watch.alive() == [False, False, True]
    finally:
        watch.kill()
        for p in (proc, older):
            p.wait(timeout=5)


@windows
def test_windows_breakaway_after_assignment_is_never_recaptured(tmp_path, monkeypatch):
    """A child the contained process starts with CREATE_BREAKAWAY_FROM_JOB
    after it joined the job, but before the sweep sees it, stays out: it was
    created after its parent joined, so it is not a missed early child."""
    from self_learn.primitives import _procs_windows as backend

    proc, (child, grandchild) = _standin(tmp_path, mode="late-away")
    late_file = tmp_path / "standin.late"
    real = backend._process_parents
    calls = []

    def after_breakaway():
        if not calls:
            (tmp_path / "standin.go").write_text("")
            _wait_for(late_file.exists)
        calls.append(1)
        return real()
    monkeypatch.setattr(backend, "_process_parents", after_breakaway)
    watch = None
    try:
        handle = procs.contain_child(child)
        late = int(late_file.read_text())
        watch = _Watch([child, grandchild, late])
        assert handle.adopted == (grandchild,)  # control: the early child is adopted
        assert (late, "spawned-after-parent-joined") in handle.left_out
        assert not _in_job(late, handle._job)
        procs.terminate_contained(handle)
        time.sleep(0.2)
        assert watch.alive() == [False, False, True]
    finally:
        if watch is not None:
            watch.kill()
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


@windows
@pytest.mark.parametrize("failure", ["snapshot", "refusal", "passes"])
def test_windows_sweep_failures_are_reported_not_raised(tmp_path, monkeypatch, failure):
    import ctypes

    import pywintypes
    import win32job
    import win32process
    import winerror
    from self_learn.primitives import _procs_windows as backend

    proc, pids = _standin(tmp_path, depth=2 if failure == "passes" else 1)
    watch = _Watch(pids)
    try:
        if failure == "snapshot":
            monkeypatch.setattr(backend, "_process_parents",
                                Mock(side_effect=ctypes.WinError(winerror.ERROR_NOT_ENOUGH_MEMORY)))
        elif failure == "refusal":
            real_assign = win32job.AssignProcessToJobObject
            def refuse(job, process):
                if win32process.GetProcessId(process) == pids[1]:
                    raise pywintypes.error(winerror.ERROR_ACCESS_DENIED, "AssignProcessToJobObject", "injected")
                return real_assign(job, process)
            monkeypatch.setattr(win32job, "AssignProcessToJobObject", refuse)
        else:
            # One pass, deepest row first: the great-grandchild is seen before
            # its parent has joined the tree, and no second pass runs.
            real = backend._process_parents
            def deepest_first():
                rows = real()
                return sorted(rows, key=lambda row: row[0] != pids[2])
            monkeypatch.setattr(backend, "_process_parents", deepest_first)
            monkeypatch.setattr(backend, "_ADOPTION_PASSES", 1)
        handle = procs.contain_child(pids[0])
        assert handle is not None and _in_job(pids[0], handle._job)
        assert watch.alive() == [True] * len(pids)
        if failure == "snapshot":
            assert handle.uncovered == ((0, winerror.ERROR_NOT_ENOUGH_MEMORY),) and not handle.complete
            assert handle.adopted == ()
        elif failure == "refusal":
            assert handle.uncovered == ((pids[1], winerror.ERROR_ACCESS_DENIED),) and handle.complete
        else:
            assert handle.adopted == (pids[1],) and not handle.complete
        procs.terminate_contained(handle)
        time.sleep(0.2)
        expected = {"snapshot": [False, True], "refusal": [False, True], "passes": [False, False, True]}
        assert watch.alive() == expected[failure]
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_interrupted_containment_hands_the_job_over(tmp_path, monkeypatch):
    """An interruption after the child is in the job must not close the job
    (that would kill the SDK child): the handle travels on the exception and
    stays referenced until the caller terminates it."""
    from self_learn.primitives import _procs_windows as backend

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    monkeypatch.setattr(backend, "_process_parents", Mock(side_effect=KeyboardInterrupt))
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            procs.contain_child(child)
        handle = caught.value.contained_child
        assert handle in backend.unclaimed and _in_job(child, handle._job)
        del caught
        gc.collect()
        time.sleep(0.2)
        assert watch.alive() == [True, True]
        procs.terminate_contained(handle)
        assert handle not in backend.unclaimed
        assert watch.alive()[0] is False
    finally:
        watch.kill()
        proc.wait(timeout=5)


# --------------------------------------------------------------------------
# Windows: the containing process dies, abruptly or normally
# --------------------------------------------------------------------------

_HELPER = _PUBLISH + r"""
import gc, json, os, site, subprocess, sys, time
from pathlib import Path
site.addsitedir(sys.argv[1])
import win32api, win32job
from self_learn.primitives import procs
mode, out, standin = sys.argv[2], Path(sys.argv[3]), sys.argv[4]
go = Path(str(out) + ".go")
while not go.exists():
    time.sleep(.005)
report = {"in_job_before": win32job.IsProcessInJob(win32api.GetCurrentProcess(), None)}
sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
if mode in ("self", "exit", "finalize"):
    early = subprocess.Popen(sleeper)
    report["early"] = early.pid
    report["first"] = procs.contain_self()
    report["second"] = procs.contain_self()
    from self_learn.primitives import _procs_windows as backend
    report["self_jobs"] = len(backend._self_job)
    away = subprocess.Popen(sleeper, creationflags=0x01000000)
    report["breakaway"] = away.pid
ready = Path(str(out) + ".standin")
child = subprocess.Popen([sys.executable, "-u", "-c", standin, str(ready), "1", standin, "plain"])
while not ready.exists():
    time.sleep(.005)
report["pids"] = [int(p) for p in ready.read_text().split()]
if mode == "child":
    handle = procs.contain_child(child.pid)
    report["adopted"] = list(handle.adopted)
report["helper"] = os.getpid()
if mode == "finalize":
    # What interpreter shutdown does to module globals: drop them. The job
    # handle must not be Python's to close, or this process dies here.
    backend._self_job.clear()
    gc.collect()
    time.sleep(0.2)
    report["survived_finalization"] = True
publish(out, json.dumps(report))
if mode in ("exit", "finalize"):
    while not Path(str(out) + ".exit").exists():
        time.sleep(.005)
    sys.exit(37)
time.sleep(120)
"""


def _helper(tmp_path, mode):
    import win32job

    out = tmp_path / "report"
    helper = subprocess.Popen(_python(_HELPER, sysconfig.get_paths()["purelib"], mode, out, _STANDIN))
    # An outer job the helper is already in when it contains itself (the
    # runner and many terminals do the same); plain, so it kills nothing.
    outer = win32job.CreateJobObject(None, f"outer-{os.getpid()}-{mode}")
    try:
        _assign(outer, helper.pid)
        (tmp_path / "report.go").write_text("")
        _wait_for(out.exists, 20)
    except BaseException:
        helper.kill()
        raise
    return helper, outer, json.loads(out.read_text())


@windows
@pytest.mark.parametrize("mode", ["none", "child", "self"])
def test_windows_abrupt_death_of_the_container(tmp_path, mode):
    import win32api
    import win32con
    import win32process

    helper, outer, report = _helper(tmp_path, mode)
    assert report["helper"] == helper.pid and report["in_job_before"]
    pids = report["pids"]
    extra = [report["breakaway"], report["early"]] if mode == "self" else []
    watch = _Watch([*pids, *extra])
    try:
        assert all(watch.alive())  # nothing died before the container did
        opened = win32api.OpenProcess(win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE, False, helper.pid)
        win32process.TerminateProcess(opened, 9)
        win32api.CloseHandle(opened)
        helper.wait(timeout=5)
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
            assert watch.alive()[3], "a child started before contain_self stays outside its job"
    finally:
        watch.kill()
        win32api.CloseHandle(outer)


@windows
@pytest.mark.parametrize("mode", ["exit", "finalize"])
def test_windows_contained_self_keeps_its_exit_status(tmp_path, mode):
    """A normal exit after contain_self returns the program's own status, and
    the job still kills the descendants once the process has ended."""
    import win32api

    helper, outer, report = _helper(tmp_path, mode)
    pids = report["pids"]
    watch = _Watch(pids)
    try:
        assert all(watch.alive())
        if mode == "finalize":
            assert report["survived_finalization"] is True and report["self_jobs"] == 1
        (tmp_path / "report.exit").write_text("")
        assert helper.wait(timeout=10) == 37
        watch.wait_dead(5)
    finally:
        watch.kill()
        _Watch([report["breakaway"], report["early"]]).kill()
        win32api.CloseHandle(outer)


@windows
def test_windows_breakaway_from_the_self_job_before_containment_is_left_out(tmp_path):
    """Under contain_self a stand-in's normal children share its self job; one
    started with breakaway does not. contain_child leaves that one out even
    though it predates the assignment (the early-child rule alone would take
    it). Run in a helper, which owns the self job."""
    script = _PUBLISH + r"""
import json, site, subprocess, sys, time
from pathlib import Path
site.addsitedir(sys.argv[1])
from self_learn.primitives import procs
out, standin = Path(sys.argv[2]), sys.argv[3]
procs.contain_self()
ready = Path(str(out) + ".standin")
child = subprocess.Popen([sys.executable, "-u", "-c", standin, str(ready), "1", standin, "early-away"])
while not ready.exists():
    time.sleep(.005)
handle = procs.contain_child(child.pid)
away = int(Path(str(ready) + ".away").read_text())
publish(out, json.dumps({"pids": [int(p) for p in ready.read_text().split()], "away": away,
                         "adopted": list(handle.adopted), "left_out": [list(x) for x in handle.left_out]}))
time.sleep(120)
"""
    out = tmp_path / "report"
    helper = subprocess.Popen(_python(script, sysconfig.get_paths()["purelib"], out, _STANDIN))
    watch = None
    try:
        _wait_for(out.exists, 20)
        report = json.loads(out.read_text())
        watch = _Watch([*report["pids"], report["away"]])
        assert report["adopted"] == report["pids"][1:]  # control
        assert [report["away"], "outside-its-parents-job"] in report["left_out"]
    finally:
        if watch is not None:
            watch.kill()
        helper.kill()
        helper.wait(timeout=5)


# --------------------------------------------------------------------------
# Windows: identity, nesting, refusals and errors
# --------------------------------------------------------------------------


@windows
def test_windows_identity_tells_a_reused_pid_apart(tmp_path, monkeypatch):
    import win32job
    from self_learn.primitives import _procs_windows as backend

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        first = procs.process_identity(child)
        assert first == procs.process_identity(child)
        assert os.path.samefile(first.image, _BASE)
        assert abs((first.created - _UNIX_EPOCH_TICKS) / 1e7 - time.time()) < 120
        assert first.cmdline is None

        # Same PID, a creation time one tick (100 ns) later, injected at the
        # real GetProcessTimes call.
        real = backend._get_process_times
        def later(handle, created, *rest):
            ok = real(handle, created, *rest)
            created._obj.dwLowDateTime += 1
            return ok
        assign = Mock(wraps=win32job.AssignProcessToJobObject)
        with monkeypatch.context() as patch:
            patch.setattr(backend, "_get_process_times", later)
            patch.setattr(win32job, "AssignProcessToJobObject", assign)
            second = procs.process_identity(child)
            assert second.image == first.image and second.created == first.created + 1
            assert second != first
            assert procs.contain_child(child, expect=first) is None
            assign.assert_not_called()
            # Control in the same scope: the true identity is accepted.
            patch.setattr(backend, "_get_process_times", real)
            handle = procs.contain_child(child, expect=first)
            assert handle is not None and assign.call_count >= 1
        procs.terminate_contained(handle)
        assert not any(watch.alive())
    finally:
        watch.kill()
        proc.wait(timeout=5)

    assert procs.process_identity(0) is None and procs.process_identity(-1) is None
    assert procs.contain_child(0) is None


@windows
def test_windows_identity_keeps_the_full_creation_time(tmp_path):
    """pywin32 rounds the creation time to the millisecond; the identity keeps
    every 100 ns tick. Over five processes, some tick below the millisecond is
    set (all five landing on whole milliseconds has odds of 1 in 10^20)."""
    import win32api
    import win32con
    import win32process

    sub_ms = []
    for _ in range(5):
        proc = subprocess.Popen(_python("import time; time.sleep(30)"))
        try:
            created = procs.process_identity(proc.pid).created
            opened = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, proc.pid)
            rounded = win32process.GetProcessTimes(opened)["CreationTime"]
            win32api.CloseHandle(opened)
            from datetime import datetime, timezone
            delta = rounded - datetime(1601, 1, 1, tzinfo=timezone.utc)
            ticks = ((delta.days * 86400 + delta.seconds) * 10**6 + delta.microseconds) * 10
            assert created - created % 10000 == ticks  # pywin32's value, refined
            sub_ms.append(created % 10000)
        finally:
            proc.kill()
            proc.wait(timeout=5)
    assert any(sub_ms), sub_ms


@windows
def test_windows_identity_and_contain_of_missing_or_exited_pid(tmp_path):
    import win32api
    import win32con
    import win32event

    # A free number.
    gone = next(pid for pid in range(0x7FFFFFFC, 0, -4) if not procs.pid_alive(pid))
    assert procs.process_identity(gone) is None
    assert procs.contain_child(gone) is None

    # An exited process whose object another handle still holds open.
    proc = subprocess.Popen(_python("import sys; sys.stdin.read()"), stdin=subprocess.PIPE)
    held = win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, proc.pid)
    try:
        before = procs.process_identity(proc.pid)
        assert before is not None
        proc.stdin.close()
        assert win32event.WaitForSingleObject(held, 10000) == win32event.WAIT_OBJECT_0
        # The object still exists, but an exited process has no identity to
        # read and nothing to contain.
        assert procs.process_identity(proc.pid) is None
        assert procs.contain_child(proc.pid) is None
    finally:
        win32api.CloseHandle(held)
        proc.wait(timeout=5)


@windows
@pytest.mark.parametrize("code, expected", [("ERROR_ACCESS_DENIED", None), ("ERROR_INVALID_HANDLE", OSError)])
def test_windows_identity_open_errors(monkeypatch, code, expected):
    import pywintypes
    import win32api
    import win32con
    import winerror

    assert procs.process_identity(os.getpid()) is not None  # control: the real open works
    failure = pywintypes.error(getattr(winerror, code), "OpenProcess", "injected")
    opened = Mock(side_effect=failure)
    monkeypatch.setattr(win32api, "OpenProcess", opened)
    if expected is None:
        assert procs.process_identity(os.getpid()) is None
    else:
        with pytest.raises(OSError) as caught:
            procs.process_identity(os.getpid())
        assert caught.value.winerror == failure.winerror and caught.value.__cause__ is failure
    opened.assert_called_once_with(win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE,
                                   False, os.getpid())


@windows
@pytest.mark.parametrize("site, code", [("_get_process_times", "ERROR_INVALID_HANDLE"),
                                        ("_query_image", "ERROR_INSUFFICIENT_BUFFER")])
def test_windows_identity_errors_carry_winerror_and_cause(monkeypatch, site, code):
    import winerror
    from self_learn.primitives import _procs_windows as backend

    number = getattr(winerror, code)
    monkeypatch.setattr(backend, site, _set_last_error_and_fail(number))
    with pytest.raises(OSError) as caught:
        procs.process_identity(os.getpid())
    assert caught.value.winerror == number
    assert isinstance(caught.value.__cause__, OSError) and caught.value.__cause__.winerror == number


@windows
def test_windows_contain_child_already_in_a_job(tmp_path):
    import win32api

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    outer = _bare_job()
    try:
        _assign(outer, child)
        handle = procs.contain_child(child)
        assert _in_job(child, outer) and _in_job(child, handle._job)
        assert grandchild in handle.adopted
        procs.terminate_contained(handle)
        assert not any(watch.alive())
    finally:
        watch.kill()
        win32api.CloseHandle(outer)
        proc.wait(timeout=5)


@windows
def test_windows_refused_assignment_surfaces_winerror_and_kills_nothing(tmp_path, monkeypatch):
    import pywintypes
    import win32job
    import winerror
    from self_learn.primitives import _procs_windows as backend

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
        assert not backend.unclaimed
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
def test_windows_refused_self_assignment_releases_the_job(monkeypatch):
    import pywintypes
    import win32job
    import winerror
    from self_learn.primitives import _procs_windows as backend

    assert backend._self_job == []  # this test process never contained itself
    created = []
    real_create = win32job.CreateJobObject
    def record(*args):
        job = real_create(*args)
        created.append(job)
        return job
    failure = pywintypes.error(winerror.ERROR_ACCESS_DENIED, "AssignProcessToJobObject", "injected")
    monkeypatch.setattr(win32job, "CreateJobObject", record)
    assign = Mock(side_effect=failure)
    monkeypatch.setattr(win32job, "AssignProcessToJobObject", assign)
    with pytest.raises(OSError) as caught:
        procs.contain_self()
    assert caught.value.winerror == winerror.ERROR_ACCESS_DENIED and caught.value.__cause__ is failure
    assert assign.call_count == 1 and len(created) == 1 and int(created[0]) == 0
    assert backend._self_job == []


@windows
@pytest.mark.parametrize("stall", ["count", "handle"])
def test_windows_terminate_is_bounded(tmp_path, monkeypatch, stall):
    from self_learn.primitives import _procs_windows as backend

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        handle = procs.contain_child(child)
        if stall == "count":
            monkeypatch.setattr(backend, "_active_processes", lambda job: 1)
        else:
            # The job reports empty while a held process is never signalled.
            monkeypatch.setattr(backend, "_active_processes", lambda job: 0)
            monkeypatch.setattr(backend, "_wait_until", lambda process, deadline: False)
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            backend.terminate_contained(handle, timeout=0.3)
        assert time.monotonic() - start < 30  # a watchdog, not a timing claim
        assert handle.released
        watch.wait_dead()
    finally:
        watch.kill()
        proc.wait(timeout=5)


@windows
def test_windows_terminate_cleanup_error_surfaces(tmp_path, monkeypatch):
    import pywintypes
    import win32api
    import winerror

    proc, (child, grandchild) = _standin(tmp_path)
    watch = _Watch([child, grandchild])
    try:
        handle = procs.contain_child(child)
        real_close = win32api.CloseHandle
        failure = pywintypes.error(winerror.ERROR_INVALID_HANDLE, "CloseHandle", "injected")
        calls = []
        def close(h):
            calls.append(h)
            real_close(h)
            if len(calls) == 1:
                raise failure
        monkeypatch.setattr(win32api, "CloseHandle", close)
        with pytest.raises(OSError) as caught:
            procs.terminate_contained(handle)
        monkeypatch.undo()
        assert caught.value.winerror == winerror.ERROR_INVALID_HANDLE and caught.value.__cause__ is failure
        assert handle.released and len(calls) == 3  # every handle was still closed
        assert watch.alive() == [False, False]
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
@pytest.mark.parametrize("case", ["other-group", "same-group", "getpgid-lookup", "killpg-lookup",
                                  "permission-kill", "permission-getpgid", "other-error"])
def test_kill_body_makes_the_same_calls_as_teardown(monkeypatch, case):
    from self_learn.sdksession import teardown

    other_group = lambda pid: 100 if pid == 0 else 200  # noqa: E731
    getpgid = {"other-group": other_group, "killpg-lookup": other_group,
               "getpgid-lookup": ProcessLookupError(3, "gone"),
               "permission-getpgid": PermissionError(1, "denied"),
               "other-error": OSError(22, "invalid")}.get(case, lambda pid: 100)
    killpg = ProcessLookupError(3, "gone") if case == "killpg-lookup" else None
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
    if case in ("other-group", "killpg-lookup"):
        assert calls == [("getpgid", 4242), ("getpgid", 0), ("killpg", 4242, signal.SIGKILL)]
    if case == "same-group":
        assert calls == [("getpgid", 4242), ("getpgid", 0), ("kill", 4242, signal.SIGKILL)]
    assert raised is (OSError if case == "other-error" else None)


@linux
@pytest.mark.parametrize("pid", ["zero", "minus-one", "minus-group", "self", "group-leader"])
def test_containment_refuses_pids_that_address_ourselves_or_a_group(monkeypatch, pid):
    from self_learn.primitives import _procs_posix as backend

    number = {"zero": 0, "minus-one": -1, "minus-group": -os.getpgrp(), "self": os.getpid(),
              "group-leader": os.getpgrp()}[pid]
    with monkeypatch.context() as patch:
        calls = _recorder(patch, lambda p: 100)
        procs.terminate_contained(procs.contain_child(4242))
        assert calls  # control: a valid PID reaches the body
    with monkeypatch.context() as patch:
        calls = _recorder(patch, lambda p: 100)
        assert procs.contain_child(number) is None
        procs.terminate_contained(None)
        procs.terminate_contained(backend.ContainedChild(number))  # built directly
        assert calls == []


@linux
def test_terminate_kills_a_real_process_group(tmp_path):
    script = textwrap.dedent("""
        import os, subprocess, sys, time
        g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        temp = sys.argv[1] + ".tmp"
        open(temp, "w").write(str(g.pid))
        os.replace(temp, sys.argv[1])
        time.sleep(60)
    """)
    started = []
    def leader():
        marker = tmp_path / f"g{len(started)}"
        proc = subprocess.Popen([sys.executable, "-c", script, str(marker)], start_new_session=True)
        started.append(proc)
        _wait_for(marker.exists)
        return proc, int(marker.read_text())

    def dead(pid):
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
        except FileNotFoundError:
            return True

    try:
        # Control: killing only the leader leaves the grandchild running.
        proc, grandchild = leader()
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        time.sleep(0.2)
        assert not dead(grandchild)
        os.kill(grandchild, signal.SIGKILL)

        proc, grandchild = leader()
        assert not dead(proc.pid) and not dead(grandchild)
        procs.terminate_contained(procs.contain_child(proc.pid))
        proc.wait(timeout=5)
        _wait_for(lambda: dead(grandchild))
    finally:
        for proc in started:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)


@linux
def test_contain_child_and_contain_self_send_no_signal_and_read_no_group(monkeypatch):
    """The named group and signal calls are never made; only our own PID and
    group are read (to refuse those numbers)."""
    proc = _sleeper()
    try:
        with monkeypatch.context() as patch:
            audit = []
            for name in ("getpgid", "killpg", "kill", "setsid", "setpgid"):
                patch.setattr(os, name, Mock(side_effect=AssertionError(name)))
            real_read = Path.read_bytes
            patch.setattr(Path, "read_bytes", lambda path: audit.append(str(path)) or real_read(path))
            assert procs.contain_self() is False
            handle = procs.contain_child(proc.pid)
            assert handle.pid == proc.pid and audit == []
            identity = procs.process_identity(proc.pid)  # control: the read spy is live
            assert audit == [f"/proc/{proc.pid}/cmdline"]
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


@linux
def test_linux_dispatch_reaches_the_posix_backend_and_nothing_else():
    """Importing the facade loads no backend and does no process work; the
    first containment call loads the POSIX backend only."""
    script = """
        import os, sys
        from self_learn.primitives import procs
        assert "self_learn.primitives._procs_posix" not in sys.modules
        identity = procs.process_identity(os.getpid())
        assert identity is not None and identity.cmdline
        assert "self_learn.primitives._procs_posix" in sys.modules
        assert procs.contain_self() is False
        loaded = [m for m in sys.modules if m.startswith(("win32", "pywintypes", "_winapi"))]
        assert not loaded and "self_learn.primitives._procs_windows" not in sys.modules, loaded
        print("ok")
    """
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], capture_output=True,
                          text=True, timeout=30, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_identities_compare_and_hash_by_value():
    identity = procs.ProcessIdentity(image="claude", created=1, cmdline=None)
    assert identity == procs.ProcessIdentity("claude", 1) and hash(identity) == hash(procs.ProcessIdentity("claude", 1))
    assert identity != procs.ProcessIdentity("claude", 2)
    with pytest.raises(AttributeError):
        identity.created = 2  # type: ignore[misc]
