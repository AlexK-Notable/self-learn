"""The supervisor interface: the systemd user manager on Linux, Task
Scheduler plus the ``self-learn-supervise`` launcher on Windows.

Three kinds of test:

- Logic tests run everywhere: the relaunch loop, the log, and the Task
  Scheduler backend's orchestration against fakes at its seams (``query``,
  ``_schtasks``, the launcher's events).
- Linux tests never reach a real ``systemctl``: they spy at
  ``procs.run_bounded`` or put a fake ``systemctl`` first on PATH.
- Windows tests run the real launcher. The ones that register real
  Task Scheduler tasks run only on CI (``GITHUB_ACTIONS=true``) or with
  ``SELF_LEARN_TEST_TASK_SCHEDULER=1``; they register under a test folder
  only through names they create, and remove every task they created.
  Cleanup acts only on process handles the test opened itself, and a
  cleanup that fails fails the test.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import sysconfig
import textwrap
import threading
import time
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import pytest

from self_learn import supervisor_launcher
from self_learn.primitives import _supervisor_tasks as tasks
from self_learn.primitives import procs, supervisor

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows supervisor contract")
linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux supervisor contract")
SCHEDULER_OPT_IN = os.environ.get("GITHUB_ACTIONS") == "true" or \
    os.environ.get("SELF_LEARN_TEST_TASK_SCHEDULER") == "1"
scheduler = pytest.mark.skipif(
    sys.platform != "win32" or not SCHEDULER_OPT_IN,
    reason="registers real Task Scheduler tasks: CI only (or SELF_LEARN_TEST_TASK_SCHEDULER=1)")

REPO = Path(__file__).resolve().parents[4]


# ============================================================ both platforms


def test_policy_matches_the_host_unit():
    unit = (REPO / "systemd" / "self-learn-host.service").read_text(encoding="utf-8")
    keys = "RestartSec|StartLimitBurst|StartLimitIntervalSec|Restart|SuccessExitStatus"
    values = dict(re.findall(rf"^({keys})=(.+)$", unit, re.M))
    assert values == {"RestartSec": "5", "StartLimitBurst": "5", "StartLimitIntervalSec": "300",
                      "Restart": "on-failure", "SuccessExitStatus": "143 SIGTERM"}
    assert supervisor.RESTART_DELAY_SECS == float(values["RestartSec"])
    assert supervisor.START_LIMIT_BURST == int(values["StartLimitBurst"])
    assert supervisor.START_LIMIT_INTERVAL_SECS == float(values["StartLimitIntervalSec"])
    assert supervisor.CLEAN_EXITS == {0, 143}
    assert supervisor_launcher.Policy() == supervisor_launcher.Policy(5.0, 5, 300.0)


class _Script:
    """Drives `supervise` with exit codes (None = stop request, an exception
    = cannot start). Each launch takes `run` seconds of the fake clock
    (`runs` overrides it per launch); each pause takes its full delay."""

    def __init__(self, codes, *, run=1.0, runs=(), stop_on_pause=False, stop_first=False):
        self.codes, self.runs = list(codes), list(runs)
        self.launches, self.pauses, self.lines = 0, [], []
        self.starts: list[float] = []
        self.now, self.run_secs = 1000.0, run
        self.stop_on_pause, self.stop_first = stop_on_pause, stop_first

    def launch(self):
        self.launches += 1
        self.starts.append(self.now)
        self.now += self.runs.pop(0) if self.runs else self.run_secs
        code = self.codes.pop(0)
        if isinstance(code, BaseException):
            raise code
        return lambda: code

    def pause(self, seconds):
        if seconds == 0:
            return self.stop_first
        self.pauses.append(seconds)
        self.now += seconds
        return self.stop_on_pause

    def go(self, policy=None):
        return supervisor_launcher.supervise(
            self.launch, policy or supervisor_launcher.Policy(), pause=self.pause,
            log=self.lines.append, clock=lambda: self.now)


def test_crash_relaunches_after_the_delay_and_gives_up_at_the_start_limit():
    script = _Script([3] * 10)
    assert script.go() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.launches == 5
    assert script.pauses == [5.0] * 5  # the sixth start is refused after its delay
    assert "giving up" in script.lines[-1]


def test_the_limit_counts_starts_inside_the_window_like_systemd():
    # The first host runs 301 s: its start has left the window when the
    # replacements crash, so systemd would allow a sixth start.
    script = _Script([3] * 10, runs=[301.0])
    assert script.go() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.launches == 6


def test_failures_spread_beyond_the_window_never_give_up():
    script = _Script([3] * 12 + [0], run=100.0)
    assert script.go() == 0
    assert script.launches == 13


@pytest.mark.parametrize("codes", [[0], [143], [None]])
def test_clean_exit_and_stop_request_are_not_relaunched(codes):
    script = _Script(codes)
    assert script.go() == 0
    assert (script.launches, script.pauses) == (1, [])


def test_stop_before_a_start_and_during_the_delay():
    script = _Script([3], stop_first=True)
    assert (script.go(), script.launches) == (0, 0)
    script = _Script([3, 3], stop_on_pause=True)
    assert script.go() == 0
    assert (script.launches, script.pauses) == (1, [5.0])


def test_restart_request_relaunches_at_once_and_is_not_a_start():
    script = _Script([supervisor.RESTART_REQUESTED_EXIT] * 4 + [3] * 10)
    assert script.go() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.pauses == [5.0] * 5
    assert script.launches == 4 + 5  # four immediate relaunches, then five counted starts


def test_restart_requests_beyond_the_limit_count_as_failures():
    script = _Script([supervisor.RESTART_REQUESTED_EXIT] * 20)
    assert script.go() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.launches == 10
    assert script.pauses == [5.0] * 5


def test_a_command_that_cannot_start_counts_as_a_failure():
    script = _Script([OSError("missing")] * 6)
    assert script.go() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.launches == 5
    assert "could not start" in script.lines[0]


@pytest.mark.parametrize("argv", [
    ["--restart-delay", "0"], ["--restart-delay", "-1"], ["--restart-delay", "nan"],
    ["--window", "0"], ["--window", "inf"], ["--burst", "0"], ["--stop-grace", "-1"],
    ["--stop-grace", "3601"], ["--log-bytes", "10"], [],
])
def test_unusable_launcher_options_are_refused(argv):
    base = ["--name", "x", "--state-dir", "d", *argv, "--", "prog"]
    if not argv:
        base = base[:-2] + ["--"]  # no command at all
    assert supervisor_launcher.parse(base) is None


def test_usable_launcher_options_parse():
    args, command, policy = supervisor_launcher.parse(
        ["--name", "x", "--state-dir", "d", "--restart-delay", "0.5", "--", "prog", "--flag", "a b"])
    assert command == ["prog", "--flag", "a b"] and policy.restart_delay == 0.5 and args.name == "x"


def test_log_rotates_while_it_grows_and_survives_a_failed_rotation(tmp_path, monkeypatch):
    log = supervisor_launcher._Log(tmp_path / "host.log", cap=4096)
    sink = log.sink()
    for _ in range(50):
        sink(("x" * 199 + "\n").encode())
    assert (tmp_path / "host.log.1").is_file()
    assert (tmp_path / "host.log").stat().st_size <= 4096
    # A rotation the system refuses is noted and writing goes on.
    real = os.replace

    def refuse(src, dst):
        raise PermissionError(13, "in use", str(src))

    monkeypatch.setattr(supervisor_launcher.os, "replace", refuse)
    for _ in range(30):
        log("line " + "y" * 200)
    monkeypatch.setattr(supervisor_launcher.os, "replace", real)
    log.close()
    text = (tmp_path / "host.log").read_text(encoding="utf-8")
    assert "could not rotate the log" in text and text.rstrip().endswith("y" * 200)
    # Split UTF-8 across chunks decodes whole.
    other = supervisor_launcher._Log(tmp_path / "u.log")
    split = other.sink()
    encoded = "é".encode()
    split(encoded[:1]), split(encoded[1:] + b"\n")
    other.close()
    assert (tmp_path / "u.log").read_text(encoding="utf-8") == "é\n"


# ------------------------------------- Task Scheduler logic against fakes


def test_task_names_are_per_user_and_per_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "current_sid", lambda: "S-1-5-21-1-2-3-1001")
    first, second = tasks.host_name(tmp_path / "a"), tasks.host_name(tmp_path / "b")
    assert first != second and first == tasks.host_name(tmp_path / "a")
    assert re.fullmatch(r"\\self-learn\\host-[0-9a-f]{16}", first)
    monkeypatch.setattr(tasks, "current_sid", lambda: "S-1-5-21-1-2-3-1002")
    assert tasks.host_name(tmp_path / "a") != first
    assert tasks.leaf(first) == first.split("\\")[-1]
    for bad in ("self-learn-host", "\\self-learn\\", "\\other\\host-1", "\\self-learn\\a\\b"):
        with pytest.raises(ValueError):
            tasks.leaf(bad)


class _FakeScheduler:
    """Tasks as a dict: name -> [state, result]. ``schtasks`` verbs change it
    the way Task Scheduler and a launcher would; ``plan`` scripts what a
    started launcher does (``ready``, ``dies`` with a result, ``never``)."""

    def __init__(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        self.tasks: dict[str, list[int]] = {}
        self.calls: list[tuple[str, str]] = []
        self.ready: set[str] = set()
        self.plan = "ready"
        self.graceful = True
        self.hang = False
        self.dying: dict[str, int] = {}
        monkeypatch.setattr(tasks, "query", self.query)
        monkeypatch.setattr(tasks, "_schtasks", self.schtasks)
        monkeypatch.setattr(tasks, "host_ready", lambda leaf: self.leafs(leaf) in self.ready)
        monkeypatch.setattr(tasks, "request_stop", self.request_stop)
        monkeypatch.setattr(tasks, "_POLL_SECS", 0.01)

    @staticmethod
    def leafs(leaf):
        return tasks.FOLDER + leaf

    def query(self, name, *, timeout=tasks.QUERY_SECS):
        if self.hang:
            return tasks.QueryFailed(None, f"no answer within {timeout:g} s")
        if name in self.dying:
            self.dying[name] -= 1
            if self.dying[name] < 0:
                del self.dying[name]
                self.tasks[name] = [3, supervisor.LAUNCHER_GAVE_UP_EXIT]
        found = self.tasks.get(name)
        return None if found is None else (found[0], found[1])

    def schtasks(self, verb, name, args, timeout):
        assert timeout > 0, (verb, timeout)
        self.calls.append((verb, name))
        if verb == "/Run":
            self.tasks[name] = [4, tasks.SCHED_S_TASK_RUNNING]
            if self.plan == "ready":
                self.ready.add(name)
            elif self.plan == "dies":
                self.dying[name] = 1  # seen running once, then gone with result 70
        elif verb == "/End":
            self.tasks[name] = [3, tasks.SCHED_S_TASK_TERMINATED]
            self.ready.discard(name)
        elif verb == "/Delete":
            del self.tasks[name]
        return ""

    def request_stop(self, leaf):
        name = self.leafs(leaf)
        if not self.graceful or name not in self.ready:
            return False
        self.tasks[name] = [3, 0]
        self.ready.discard(name)
        return True


@pytest.fixture
def fake(monkeypatch, tmp_path):
    return _FakeScheduler(monkeypatch, tmp_path)


NAME_A = "\\self-learn\\host-00000000000000aa"
NAME_B = "\\self-learn\\host-00000000000000bb"


def test_start_returns_once_a_host_is_confirmed(fake):
    fake.tasks[NAME_A] = [3, tasks.SCHED_S_TASK_HAS_NOT_RUN]
    tasks.start(NAME_A, timeout=2)
    assert fake.calls == [("/Run", NAME_A)]
    tasks.start(NAME_A, timeout=2)  # running and confirmed: no second /Run
    assert fake.calls == [("/Run", NAME_A)]


def test_start_reports_a_launcher_that_ends_before_its_host(fake):
    fake.tasks[NAME_A] = [3, 0]
    fake.plan = "dies"
    with pytest.raises(supervisor.SupervisorRefused, match="before a host started"):
        tasks.start(NAME_A, timeout=2)


def test_start_without_a_confirmed_host_fails_within_its_bound(fake):
    fake.tasks[NAME_A] = [3, 0]
    fake.plan = "never"
    began = time.monotonic()
    with pytest.raises(supervisor.SupervisorUnavailable, match="no running host confirmed"):
        tasks.start(NAME_A, timeout=0.5)
    assert time.monotonic() - began < 2


def test_stop_asks_the_launcher_first_and_ends_the_task_otherwise(fake):
    fake.tasks[NAME_A] = [4, tasks.SCHED_S_TASK_RUNNING]
    fake.ready.add(NAME_A)
    tasks.stop(NAME_A, timeout=5)
    assert fake.calls == [] and fake.tasks[NAME_A] == [3, 0]
    fake.tasks[NAME_A] = [4, tasks.SCHED_S_TASK_RUNNING]
    fake.graceful = False
    tasks.stop(NAME_A, timeout=10)
    assert fake.calls == [("/End", NAME_A)]


def test_stop_with_no_answer_fails_within_its_bound(fake, monkeypatch):
    fake.tasks[NAME_A] = [4, tasks.SCHED_S_TASK_RUNNING]
    fake.hang = True
    began = time.monotonic()
    with pytest.raises(supervisor.SupervisorUnavailable, match="did not answer"):
        tasks.stop(NAME_A, timeout=1)
    assert time.monotonic() - began < 3 and fake.calls == []
    # It answered once, then went quiet: /End is tried, success never claimed.
    fake.hang = False
    real_query = fake.query

    def quiet_after_first(name, *, timeout=tasks.QUERY_SECS):
        if not getattr(quiet_after_first, "asked", False):
            quiet_after_first.asked = True  # type: ignore[attr-defined]
            return real_query(name)
        return tasks.QueryFailed(None, "no answer")

    monkeypatch.setattr(tasks, "query", quiet_after_first)
    fake.graceful = False
    began = time.monotonic()
    with pytest.raises(supervisor.SupervisorUnavailable, match="not seen to stop"):
        tasks.stop(NAME_A, timeout=1)
    assert time.monotonic() - began < 3 and fake.calls == [("/End", NAME_A)]


def test_restart_of_a_running_task_stops_then_confirms_a_new_host(fake):
    fake.tasks[NAME_A] = [4, tasks.SCHED_S_TASK_RUNNING]
    fake.ready.add(NAME_A)
    fake.graceful = False
    tasks.restart(NAME_A, timeout=10)
    assert fake.calls == [("/End", NAME_A), ("/Run", NAME_A)]
    fake.plan = "never"
    with pytest.raises(supervisor.SupervisorUnavailable):
        tasks.restart(NAME_A, timeout=1)


def test_status_never_raises_and_never_guesses(fake):
    fake.tasks[NAME_A] = [4, -2147020576]
    assert tasks.status(NAME_A, timeout=1) == supervisor.ServiceStatus("running", "Running", -2147020576)
    assert tasks.status(NAME_B, timeout=1) == supervisor.ServiceStatus("missing", "missing", None)
    fake.hang = True
    found = tasks.status(NAME_A, timeout=1)
    assert found.state == "unknown" and found.raw.startswith("query failed") and found.last_result is None


def test_unregister_removes_only_its_own_task(fake):
    fake.tasks[NAME_A] = [4, tasks.SCHED_S_TASK_RUNNING]
    fake.tasks[NAME_B] = [4, tasks.SCHED_S_TASK_RUNNING]
    fake.ready.update({NAME_A, NAME_B})
    tasks.unregister(NAME_A, timeout=10)
    assert NAME_A not in fake.tasks and fake.tasks[NAME_B] == [4, tasks.SCHED_S_TASK_RUNNING]
    assert ("/Delete", NAME_A) in fake.calls and all(name == NAME_A for _, name in fake.calls)
    calls = len(fake.calls)
    tasks.unregister(NAME_A, timeout=10)  # already gone
    assert len(fake.calls) == calls


def test_lifecycle_changes_to_one_task_are_serialized(fake):
    fake.tasks[NAME_A] = [3, 0]
    entered, release = threading.Event(), threading.Event()

    def hold():
        with tasks._serialized(NAME_A, "/Run", time.monotonic() + 5):
            entered.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert entered.wait(5)
        with pytest.raises(supervisor.SupervisorUnavailable, match="still in progress"):
            tasks.start(NAME_A, timeout=0.3)
    finally:
        release.set()
        holder.join(5)
    tasks.start(NAME_A, timeout=2)


def test_query_is_bounded_and_failures_are_values(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(tasks, "_com_lookup", lambda name: gate.wait(30) and None)
    began = time.monotonic()
    found = tasks.query(NAME_A, timeout=0.3)
    gate.set()
    assert isinstance(found, tasks.QueryFailed) and time.monotonic() - began < 2

    def boom(name):
        raise RuntimeError("COM went away")

    monkeypatch.setattr(tasks, "_com_lookup", boom)
    found = tasks.query(NAME_A, timeout=2)
    assert isinstance(found, tasks.QueryFailed) and "COM went away" in found.detail


@pytest.mark.parametrize("program, ok", [
    ("C:\\tools\\host.exe", True), ("\\\\server\\share\\host.exe", True),
    ("\\tools\\host.exe", False), ("C:tools\\host.exe", False), ("host.exe", False),
], ids=["drive", "unc", "rooted", "drive-relative", "bare"])
def test_programs_must_be_fully_qualified(program, ok):
    if ok:
        assert tasks.check_program(program) == program
    else:
        with pytest.raises(ValueError, match="fully qualified"):
            tasks.check_program(program)


@pytest.mark.parametrize("where", ["program", "argument", "home"])
def test_percent_is_refused_in_the_action(tmp_path, monkeypatch, where):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(tasks, "launcher_path", lambda: Path("C:\\venv\\Scripts\\self-learn-supervise.exe"))
    program = "C:\\100%USERNAME%\\host.exe" if where == "program" else "C:\\tools\\host.exe"
    argument = "%TEMP%" if where == "argument" else "serve"
    home = tmp_path / ("%HOME%" if where == "home" else "home")
    with pytest.raises(ValueError, match="'%'.*Task Scheduler would expand") as refused:
        tasks.action_for(NAME_A, [program, argument], home)
    assert "%" in str(refused.value).split(": ", 1)[1]


def test_task_xml_has_one_restart_policy_and_the_trial_settings():
    xml = tasks.task_xml(user="HOST\\me", command="C:\\l.exe", arguments='--name "a b" & <x>',
                         working_directory="C:\\state", description="d")
    assert xml[:2] == b"\xff\xfe"
    root = ElementTree.fromstring(xml[2:].decode("utf-16-le").split("?>", 1)[1])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    text = {path: root.findtext(path, namespaces=ns) for path in (
        "t:Settings/t:MultipleInstancesPolicy", "t:Settings/t:ExecutionTimeLimit",
        "t:Settings/t:StartWhenAvailable", "t:Settings/t:DisallowStartIfOnBatteries",
        "t:Settings/t:StopIfGoingOnBatteries", "t:Principals/t:Principal/t:LogonType",
        "t:Triggers/t:LogonTrigger/t:UserId", "t:Actions/t:Exec/t:Arguments")}
    assert text == {
        "t:Settings/t:MultipleInstancesPolicy": "IgnoreNew", "t:Settings/t:ExecutionTimeLimit": "PT0S",
        "t:Settings/t:StartWhenAvailable": "true", "t:Settings/t:DisallowStartIfOnBatteries": "false",
        "t:Settings/t:StopIfGoingOnBatteries": "false",
        "t:Principals/t:Principal/t:LogonType": "InteractiveToken",
        "t:Triggers/t:LogonTrigger/t:UserId": "HOST\\me", "t:Actions/t:Exec/t:Arguments": '--name "a b" & <x>'}
    assert root.find("t:Settings/t:RestartOnFailure", ns) is None


# ======================================================================= Linux


@linux
def test_linux_launcher_refuses_to_run():
    assert supervisor_launcher.main(["--name", "x", "--state-dir", "d", "--", "true"]) == 64


@linux
def test_linux_facade_loads_no_windows_module():
    probe = textwrap.dedent("""
        import sys
        from self_learn.primitives import supervisor
        assert supervisor.host_name() == "self-learn-host.service"
        assert supervisor.host_name("/elsewhere") == "self-learn-host.service"
        loaded = sorted(m for m in sys.modules if "win32" in m or m.endswith(("_supervisor_tasks", "_procs_windows")))
        assert not loaded, loaded
    """)
    subprocess.run([sys.executable, "-c", probe], check=True, timeout=30)


@pytest.fixture
def systemctl_spy(tmp_path, monkeypatch):
    """A `systemctl` on PATH (never run) and a spy at the procs call."""
    binary = tmp_path / "bin" / "systemctl"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\nexit 99\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary.parent))
    calls = []
    replies = {}

    def spy(argv, *, timeout, **kwargs):
        calls.append((list(argv), timeout, kwargs))
        code, out, err = replies.get(argv[2], (0, "", ""))
        if isinstance(code, BaseException):
            raise code
        return subprocess.CompletedProcess(argv, code, out, err)

    monkeypatch.setattr(procs, "run_bounded", spy)
    return str(binary), calls, replies


@linux
def test_linux_argument_lists_are_the_existing_calls(systemctl_spy):
    binary, calls, replies = systemctl_spy
    unit = "self-learn-host.service"
    supervisor.restart(unit, timeout=10)
    replies["stop"] = (5, "", "not loaded")  # the existing stop does not check the status
    supervisor.stop("self-learn-run-0123456789ab.service", timeout=10)
    supervisor.start(unit, timeout=3)
    assert [(argv, timeout) for argv, timeout, _ in calls] == [
        ([binary, "--user", "reset-failed", unit], 10),
        ([binary, "--user", "restart", unit], 10),
        ([binary, "--user", "stop", "self-learn-run-0123456789ab.service"], 10),
        ([binary, "--user", "start", unit], 3),
    ]
    assert all(kwargs == {} for _, _, kwargs in calls)
    for operation in (lambda: supervisor.register(unit, ["x"], description="x"),
                      lambda: supervisor.unregister(unit)):
        with pytest.raises(NotImplementedError):
            operation()
    assert len(calls) == 4 and supervisor.last_result(unit) is None and len(calls) == 4


@linux
@pytest.mark.parametrize("word, state", [
    ("active", "running"), ("activating", "running"), ("deactivating", "running"),
    ("reloading", "running"), ("refreshing", "running"), ("failed", "failed"),
    ("inactive", "stopped"), ("maintenance", "unknown"), ("", "unknown"),
])
def test_linux_status_is_one_is_active_call(systemctl_spy, word, state):
    binary, calls, replies = systemctl_spy
    replies["is-active"] = (0 if word == "active" else 3, word + "\n", "")
    found = supervisor.status("self-learn-host.service", timeout=1.0)
    assert found == supervisor.ServiceStatus(state, word or "unknown", None)
    assert [(argv, timeout) for argv, timeout, _ in calls] == [
        ([binary, "--user", "is-active", "self-learn-host.service"], 1.0)]


@linux
def test_linux_errors_keep_the_existing_messages(systemctl_spy, monkeypatch):
    _, _, replies = systemctl_spy
    unit = "self-learn-host.service"
    replies["reset-failed"] = (1, "", "  Unit not loaded.\n")
    with pytest.raises(supervisor.SupervisorRefused) as refused:
        supervisor.restart(unit)
    assert str(refused.value) == f"systemctl --user reset-failed {unit} exited 1: Unit not loaded."
    assert (refused.value.returncode, refused.value.verb, refused.value.detail) == (1, "reset-failed", "Unit not loaded.")
    replies["reset-failed"] = (procs.BoundedTimeout(["systemctl"], 10), "", "")
    with pytest.raises(supervisor.SupervisorUnavailable) as timed_out:
        supervisor.restart(unit)
    assert str(timed_out.value).startswith(f"systemctl --user reset-failed {unit} failed: Command")
    assert isinstance(timed_out.value.__cause__, subprocess.TimeoutExpired)
    replies["stop"] = (procs.BoundedTimeout(["systemctl"], 10), "", "")
    with pytest.raises(supervisor.SupervisorUnavailable, match=f"^systemctl --user stop {unit} failed: "):
        supervisor.stop(unit)
    replies["is-active"] = (FileNotFoundError(2, "gone"), "", "")
    with pytest.raises(supervisor.SupervisorUnavailable):
        supervisor.status(unit)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(supervisor.SupervisorUnavailable, match="^systemctl is not on PATH$"):
        supervisor.stop(unit)


@linux
def test_linux_status_through_a_fake_systemctl(tmp_path, monkeypatch):
    fake = tmp_path / "bin" / "systemctl"
    fake.parent.mkdir()
    fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent("""
        import os, sys
        with open(os.environ["FAKE_SYSTEMCTL_LOG"], "a") as fh:
            fh.write(" ".join(sys.argv[1:]) + "\\n")
        print("failed")
        sys.exit(3)
    """))
    fake.chmod(0o755)
    log = tmp_path / "calls"
    monkeypatch.setenv("PATH", str(fake.parent))
    monkeypatch.setenv("FAKE_SYSTEMCTL_LOG", str(log))
    assert supervisor.status("self-learn-host.service", timeout=10) == supervisor.ServiceStatus(
        "failed", "failed", None)
    assert log.read_text().splitlines() == ["--user is-active self-learn-host.service"]


# ===================================================================== Windows


_HOST = r"""
import ctypes, os, subprocess, sys, time
from pathlib import Path
out, mode = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
with open(out / "launches", "a") as fh:
    fh.write(f"{os.getpid()} {time.time()}\n")
launches = len((out / "launches").read_text().splitlines())
if mode == "crash":
    sys.exit(3)
if mode in ("clean", "exit143"):
    sys.exit(0 if mode == "clean" else 143)
if mode == "restart-once":
    sys.exit(75 if launches == 1 else 0)
if mode == "chatty":
    for i in range(3000):
        print(f"{i:06d} " + "o" * 120, flush=i % 100 == 0)
    sys.stdout.flush()
    sys.stderr.write("stderr-marker\n")
    sys.stderr.flush()
if mode == "detach":
    import site
    site.addsitedir(sys.argv[3])
    from self_learn.primitives import procs
    procs.contain_self()
sleeper = [sys.executable, "-c", "import time; time.sleep(600)"]
children = [subprocess.Popen(sleeper)]
if mode == "detach":
    flags = 0x01000000 | 0x00000008 | 0x00000200  # BREAKAWAY_FROM_JOB, DETACHED, NEW_GROUP
    children.append(subprocess.Popen(sleeper, creationflags=flags))
(out / "pids.tmp").write_text(" ".join(str(p) for p in [os.getpid(), *(c.pid for c in children)]))
os.replace(out / "pids.tmp", out / "pids")
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.OpenEventW.restype = ctypes.c_void_p
kernel.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
event = kernel.OpenEventW(0x00100000, 0, os.environ.get("SELF_LEARN_SUPERVISOR_STOP_EVENT", ""))
deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    if mode != "stubborn" and event and kernel.WaitForSingleObject(event, 200) == 0:
        (out / "acknowledged").write_text("stopped on request")
        sys.exit(0)
    time.sleep(0.05 if event else 0.2)
"""


def _wait_for(predicate, timeout=30.0, what="condition"):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.1)


class _Pinned:
    """A process the test opened itself: the handle keeps its PID from
    being reused, and the identity read through it says what it is."""

    def __init__(self, pid, image):
        import win32api
        import win32con

        access = win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE | win32con.PROCESS_QUERY_LIMITED_INFORMATION
        self.handle = win32api.OpenProcess(access, False, pid)
        self.pid = pid
        identity = procs.process_identity(pid)
        assert identity is not None and Path(identity.image).name.lower() == Path(image).name.lower(), \
            (pid, identity, image)

    def alive(self):
        import win32event

        return win32event.WaitForSingleObject(self.handle, 0) == win32event.WAIT_TIMEOUT

    def end(self):
        import win32event
        import win32process

        if self.alive():
            win32process.TerminateProcess(self.handle, 1)
        if win32event.WaitForSingleObject(self.handle, 10000) != win32event.WAIT_OBJECT_0:
            raise AssertionError(f"cleanup: process {self.pid} did not end")
        self.handle.Close()


@pytest.fixture
def win(tmp_path, monkeypatch):
    """The stand-in host, launchers started as Popen objects, processes
    pinned by handle, and (scheduler tests only) the tasks it created. Every
    cleanup step is tried; any failure fails the test."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    host = tmp_path / "host.py"
    host.write_text(_HOST)
    launchers: list[subprocess.Popen] = []
    pinned: list[_Pinned] = []
    created: list[str] = []
    base_python = getattr(sys, "_base_executable", sys.executable)

    class Win:
        python = base_python
        test_folder = "\\self-learn\\"

        @staticmethod
        def out(label):
            return tmp_path / label

        @staticmethod
        def host_argv(out, mode):
            extra = [sysconfig.get_paths()["purelib"]] if mode == "detach" else []
            return [base_python, str(host), str(out), mode, *extra]

        @staticmethod
        def launcher(name, state, out, mode, *extra, env=None):
            argv = [str(tasks.launcher_path()), "--name", name, "--state-dir", str(state), *extra,
                    "--", *Win.host_argv(out, mode)]
            launchers.append(subprocess.Popen(argv, env=env))
            return launchers[-1]

        @staticmethod
        def pids(out, timeout=30.0):
            path = _wait_for(lambda: (out / "pids").is_file() and out / "pids", timeout, f"{out}/pids")
            found = [_Pinned(int(pid), base_python) for pid in path.read_text().split()]
            pinned.extend(found)
            return found

        @staticmethod
        def launches(out):
            path = out / "launches"
            return [float(line.split()[1]) for line in path.read_text().splitlines()] if path.is_file() else []

        @staticmethod
        def created(name):
            created.append(name)
            return name

    yield Win
    errors = []
    for launcher in launchers:
        if launcher.poll() is None:
            launcher.kill()
        try:
            launcher.wait(timeout=15)
        except subprocess.TimeoutExpired:
            errors.append(f"launcher {launcher.pid} did not end")
    for name in created:
        try:
            found = tasks.query(name)
            if isinstance(found, tasks.QueryFailed):
                errors.append(f"{name}: {found.detail}")
                continue
            if found is None:
                continue
            if found[0] in tasks.RUNNING_STATES:
                tasks.end(name, timeout=30)
            tasks._schtasks("/Delete", name, ["/TN", name, "/F"], 30)
            if tasks.query(name) is not None:
                errors.append(f"{name} is still registered")
        except Exception as exc:  # noqa: BLE001 -- every step is tried
            errors.append(f"{name}: {exc}")
    for process in pinned:
        try:
            process.end()
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    assert not errors, "cleanup failed: " + "; ".join(errors)


def _leaf():
    return f"test-{uuid4().hex[:12]}"


def _launcher_pid(log_path):
    text = _wait_for(lambda: log_path.is_file() and "supervising" in log_path.read_text(errors="replace")
                     and log_path.read_text(errors="replace"), what="the launcher's first log line")
    return int(re.search(r"self-learn-supervise\[(\d+)\]: supervising", text).group(1))


@windows
def test_windows_crash_is_relaunched_until_the_limit(win, tmp_path):
    name, out = _leaf(), win.out("crash")
    launcher = win.launcher(name, tmp_path / "state", out, "crash", "--restart-delay", "0.5")
    assert launcher.wait(timeout=60) == supervisor.LAUNCHER_GAVE_UP_EXIT
    times = win.launches(out)
    assert len(times) == supervisor.START_LIMIT_BURST
    assert all(later - earlier >= 0.45 for earlier, later in zip(times, times[1:]))
    log = (tmp_path / "state" / f"{name}.log").read_text()
    assert "relaunching in 0.5 s" in log and "giving up" in log


@windows
@pytest.mark.parametrize("mode", ["clean", "exit143"])
def test_windows_clean_exit_is_not_relaunched(win, tmp_path, mode):
    name, out = _leaf(), win.out(mode)
    launcher = win.launcher(name, tmp_path / "state", out, mode, "--restart-delay", "0.5")
    assert launcher.wait(timeout=60) == 0
    time.sleep(1.0)
    assert len(win.launches(out)) == 1


@windows
def test_windows_restart_code_relaunches_at_once(win, tmp_path):
    name, out = _leaf(), win.out("restart")
    started = time.monotonic()
    launcher = win.launcher(name, tmp_path / "state", out, "restart-once", "--restart-delay", "60")
    assert launcher.wait(timeout=45) == 0
    assert time.monotonic() - started < 40
    times = win.launches(out)
    assert len(times) == 2 and times[1] - times[0] < 10


@windows
def test_windows_second_launcher_exits_and_a_stop_is_acknowledged(win, tmp_path):
    name, state = _leaf(), tmp_path / "state"
    first_out, second_out = win.out("first"), win.out("second")
    first = win.launcher(name, state, first_out, "serve")
    host, grandchild = win.pids(first_out)
    second = win.launcher(name, state, second_out, "serve")
    assert second.wait(timeout=30) == supervisor.LAUNCHER_ALREADY_RUNNING_EXIT
    assert not (second_out / "launches").exists() and (state / f"{name}.refused").is_file()
    assert tasks.host_ready(name)
    assert tasks.request_stop(name)
    assert first.wait(timeout=30) == 0
    assert (first_out / "acknowledged").read_text() == "stopped on request"
    _wait_for(lambda: not host.alive() and not grandchild.alive(), what="host and grandchild to end")
    assert len(win.launches(first_out)) == 1 and not tasks.host_ready(name)
    # Control: with the first launcher gone, the same command does start.
    third = win.launcher(name, state, second_out, "serve")
    win.pids(second_out)
    assert tasks.request_stop(name) and third.wait(timeout=30) == 0


@windows
def test_windows_stubborn_host_is_ended_after_the_grace(win, tmp_path):
    name, out = _leaf(), win.out("stubborn")
    launcher = win.launcher(name, tmp_path / "state", out, "stubborn", "--stop-grace", "1")
    host, grandchild = win.pids(out)
    began = time.monotonic()
    assert tasks.request_stop(name)
    assert launcher.wait(timeout=30) == 0
    assert 0.9 <= time.monotonic() - began < 15
    assert not (out / "acknowledged").exists()
    _wait_for(lambda: not host.alive() and not grandchild.alive(), what="the ended host")


@windows
@pytest.mark.parametrize("victim", ["trampoline", "python"])
def test_windows_killing_the_launcher_leaves_no_host(win, tmp_path, victim):
    name, out, state = _leaf(), win.out(victim), tmp_path / "state"
    launcher = win.launcher(name, state, out, "serve")
    host, grandchild = win.pids(out)
    if victim == "trampoline":
        launcher.kill()  # what `schtasks /End` does to the task's own process
    else:
        import win32api
        import win32con

        handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, _launcher_pid(state / f"{name}.log"))
        win32api.TerminateProcess(handle, 9)
        handle.Close()
    launcher.wait(timeout=30)
    _wait_for(lambda: not host.alive() and not grandchild.alive(), timeout=15,
              what=f"no host after the {victim} was killed")


@windows
def test_windows_log_is_bounded_while_the_host_runs(win, tmp_path):
    name, out, state = _leaf(), win.out("chatty"), tmp_path / "state"
    launcher = win.launcher(name, state, out, "chatty", "--log-bytes", "65536")
    win.pids(out)
    log = state / f"{name}.log"
    _wait_for(lambda: (state / f"{name}.log.1").is_file() and "stderr-marker" in log.read_text(errors="replace"),
              what="a rotation and the host's stderr in the log")
    assert log.stat().st_size <= 65536 + 4096
    assert launcher.poll() is None
    assert tasks.request_stop(name) and launcher.wait(timeout=30) == 0


# ------------------------------------------- real Task Scheduler (CI only)


@pytest.fixture
def com():
    """COM for this test's own reads (the product queries on its own threads)."""
    import pythoncom

    pythoncom.CoInitialize()
    yield
    pythoncom.CoUninitialize()


def _definition(name):
    import win32com.client

    service = win32com.client.Dispatch("Schedule.Service")
    service.Connect()
    return service.GetFolder("\\").GetTask(name).Definition


@scheduler
def test_windows_task_lifecycle(win, tmp_path, com):
    home = tmp_path / "home"
    name = win.created(supervisor.host_name(home))
    out = win.out("lifecycle")
    supervisor.register(name, win.host_argv(out, "serve"), description="self-learn test host", home=home)
    assert supervisor.status(name) == supervisor.ServiceStatus("stopped", "Ready", tasks.SCHED_S_TASK_HAS_NOT_RUN)

    definition = _definition(name)
    settings, action = definition.Settings, definition.Actions.Item(1)
    assert settings.MultipleInstances == 2  # TASK_INSTANCES_IGNORE_NEW
    assert settings.ExecutionTimeLimit == "PT0S"
    assert settings.StartWhenAvailable and not settings.DisallowStartIfOnBatteries
    assert not settings.StopIfGoingOnBatteries
    assert settings.RestartCount == 0 and not settings.RestartInterval  # no RestartOnFailure
    assert "RestartOnFailure" not in definition.XmlText
    assert definition.Principal.LogonType == 3  # TASK_LOGON_INTERACTIVE_TOKEN
    assert definition.Principal.RunLevel == 0  # TASK_RUNLEVEL_LUA
    assert definition.Triggers.Item(1).Type == 9  # TASK_TRIGGER_LOGON
    assert definition.Triggers.Item(1).UserId.lower() == tasks.current_user().lower()
    assert Path(action.Path) == tasks.launcher_path()
    assert str(supervisor.state_dir(home)) in action.Arguments and str(home) in action.Arguments
    assert f"--name {tasks.leaf(name)} " in action.Arguments
    del definition, settings, action  # released before COM is left

    supervisor.start(name)
    host, grandchild = win.pids(out)
    running = supervisor.status(name)
    assert (running.state, running.raw) == ("running", "Running")
    supervisor.start(name)  # already running: no second /Run, no overwritten result
    assert supervisor.status(name) == running and len(win.launches(out)) == 1

    (out / "pids").unlink()
    supervisor.restart(name)  # of a running task: a new host is confirmed
    assert not host.alive() and (out / "acknowledged").is_file()
    assert supervisor.status(name).state == "running"
    (out / "acknowledged").unlink()
    win.pids(out)
    assert len(win.launches(out)) == 2

    supervisor.stop(name)
    assert supervisor.status(name) == supervisor.ServiceStatus("stopped", "Ready", 0)
    assert (out / "acknowledged").read_text() == "stopped on request"
    supervisor.unregister(name)
    assert supervisor.status(name) == supervisor.ServiceStatus("missing", "missing", None)
    supervisor.unregister(name)  # already gone: nothing to do


@scheduler
def test_windows_two_ledgers_have_their_own_tasks(win, tmp_path):
    names, outs = [], []
    for label in ("ledger-a", "ledger-b"):
        home = tmp_path / label
        names.append(win.created(supervisor.host_name(home)))
        outs.append(win.out(f"{label}-host"))
        supervisor.register(names[-1], win.host_argv(outs[-1], "serve"), description=label, home=home)
    assert names[0] != names[1]
    for name, out in zip(names, outs):
        supervisor.start(name)
        win.pids(out)
    supervisor.unregister(names[0])
    assert supervisor.status(names[0]).state == "missing"
    assert supervisor.status(names[1]).state == "running"
    supervisor.unregister(names[1])


@scheduler
def test_windows_end_spares_only_detached_work(win, tmp_path):
    # Positive control first: a task whose action is the host itself leaves
    # its ordinary grandchild running after /End (spike section 6).
    bare = win.created(tasks.FOLDER + _leaf())
    bare_out = win.out("bare")
    argv = win.host_argv(bare_out, "serve")
    tasks.create_task(bare, tasks.task_xml(
        user=tasks.current_user(), command=argv[0], arguments=subprocess.list2cmdline(argv[1:]),
        working_directory=str(tmp_path), description="self-learn test control"), timeout=30)
    tasks._schtasks("/Run", bare, ["/TN", bare], 30)
    bare_host, bare_grandchild = win.pids(bare_out)
    tasks.end(bare, timeout=30)
    _wait_for(lambda: not bare_host.alive(), what="the bare host to end")
    time.sleep(3)
    assert bare_grandchild.alive(), "control: without the launcher's job the grandchild survives"

    home = tmp_path / "home"
    name = win.created(supervisor.host_name(home))
    out = win.out("ended")
    supervisor.register(name, win.host_argv(out, "detach"), description="self-learn test host", home=home)
    supervisor.start(name)
    host, ordinary, detached = win.pids(out)
    tasks.end(name, timeout=30)
    _wait_for(lambda: not host.alive() and not ordinary.alive(), timeout=15,
              what="the ended host and its ordinary grandchild")
    time.sleep(2)
    assert detached.alive(), "a child started with CREATE_BREAKAWAY_FROM_JOB escapes the launcher's job"
    assert supervisor.status(name) == supervisor.ServiceStatus("stopped", "Ready", tasks.SCHED_S_TASK_TERMINATED)


@scheduler
def test_windows_failed_and_missing_status(win, tmp_path):
    name = win.created(tasks.FOLDER + _leaf())
    tasks.create_task(name, tasks.task_xml(
        user=tasks.current_user(), command=win.python, arguments='-c "import sys; sys.exit(3)"',
        working_directory=str(tmp_path), description="self-learn test failure"), timeout=30)
    tasks._schtasks("/Run", name, ["/TN", name], 30)
    found = _wait_for(lambda: (s := supervisor.status(name)).state not in ("running", "unknown")
                      and s.last_result != tasks.SCHED_S_TASK_HAS_NOT_RUN and s,
                      what="the failing task to finish")
    assert found == supervisor.ServiceStatus("failed", "Ready", 3)
    assert supervisor.status(tasks.FOLDER + _leaf()) == supervisor.ServiceStatus("missing", "missing", None)


@scheduler
def test_windows_restart_into_a_missing_program_reports_failure(win, tmp_path):
    home = tmp_path / "home"
    name = win.created(supervisor.host_name(home))
    out = win.out("replaced")
    supervisor.register(name, win.host_argv(out, "serve"), description="self-learn test host", home=home)
    supervisor.start(name)
    win.pids(out)
    supervisor.register(name, [str(tmp_path / "gone" / "host.exe")], description="gone", home=home)
    began = time.monotonic()
    with pytest.raises(supervisor.SupervisorError):
        supervisor.restart(name, timeout=20)
    assert time.monotonic() - began < 25
    assert not tasks.host_ready(tasks.leaf(name))


@pytest.mark.parametrize("task_state, result, expected", [
    (4, 0x41301, "running"),
    (4, -2147020576, "running"),  # a refused second /Run overwrote the result
    (2, 0, "running"),
    (3, 0, "stopped"),
    (3, 0x41303, "stopped"),
    (3, 0x41306, "stopped"),
    (3, 3, "failed"),
    (3, supervisor.LAUNCHER_GAVE_UP_EXIT, "failed"),
    (3, -2147024894, "failed"),
    (1, 0, "stopped"),
    (0, 0, "unknown"),
])
def test_status_mapping(task_state, result, expected):
    assert tasks.classify(task_state, result) == expected
