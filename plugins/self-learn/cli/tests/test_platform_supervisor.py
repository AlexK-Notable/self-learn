"""The supervisor interface: the systemd user manager on Linux, Task
Scheduler plus the ``self-learn-supervise`` launcher on Windows.

Linux tests never reach a real ``systemctl``: they spy at
``procs.run_bounded`` or put a fake ``systemctl`` first on PATH. Windows
tests register real per-user tasks with unique names and remove every one
of them, also when a test fails.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from uuid import uuid4

import pytest

from self_learn import supervisor_launcher
from self_learn.primitives import procs, supervisor

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows supervisor contract")
linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux supervisor contract")

REPO = Path(__file__).resolve().parents[4]


# ------------------------------------------------------------------ both platforms


def test_policy_matches_the_host_unit():
    unit = (REPO / "systemd" / "self-learn-host.service").read_text(encoding="utf-8")
    values = dict(re.findall(r"^(RestartSec|StartLimitBurst|StartLimitIntervalSec)=(\S+)$", unit, re.M))
    assert values == {"RestartSec": "5", "StartLimitBurst": "5", "StartLimitIntervalSec": "300"}
    assert supervisor.RESTART_DELAY_SECS == float(values["RestartSec"])
    assert supervisor.START_LIMIT_BURST == int(values["StartLimitBurst"])
    assert supervisor.START_LIMIT_INTERVAL_SECS == float(values["StartLimitIntervalSec"])
    assert supervisor_launcher.Policy() == supervisor_launcher.Policy(5.0, 5, 300.0)


class _Script:
    """Drives `supervise` with a list of exit codes (None = stop request) and
    a clock that advances `step` seconds per launch."""

    def __init__(self, codes, *, step=1.0, stop_on_pause=False):
        self.codes = list(codes)
        self.launches = 0
        self.pauses: list[float] = []
        self.lines: list[str] = []
        self.now = 1000.0
        self.step = step
        self.stop_on_pause = stop_on_pause

    def launch(self):
        self.launches += 1
        self.now += self.step
        code = self.codes.pop(0)
        if isinstance(code, BaseException):
            raise code
        return lambda: code

    def pause(self, seconds):
        self.pauses.append(seconds)
        return self.stop_on_pause

    def run(self, policy=None):
        return supervisor_launcher.supervise(
            self.launch, policy or supervisor_launcher.Policy(), pause=self.pause,
            log=self.lines.append, clock=lambda: self.now)


def test_crash_relaunches_after_the_delay_and_gives_up_at_the_limit():
    script = _Script([3] * 10)
    assert script.run() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.launches == 5
    assert script.pauses == [5.0] * 4
    assert "giving up" in script.lines[-1]


def test_failures_spread_beyond_the_window_never_give_up():
    script = _Script([3] * 12 + [0], step=100.0)
    assert script.run() == 0
    assert script.launches == 13


def test_clean_exit_and_stop_request_are_not_relaunched():
    for codes in ([0], [None]):
        script = _Script(codes)
        assert script.run() == 0
        assert (script.launches, script.pauses) == (1, [])


def test_stop_during_the_delay_is_not_relaunched():
    script = _Script([3, 3], stop_on_pause=True)
    assert script.run() == 0
    assert (script.launches, script.pauses) == (1, [5.0])


def test_restart_request_relaunches_at_once():
    script = _Script([supervisor.RESTART_REQUESTED_EXIT, supervisor.RESTART_REQUESTED_EXIT, 0])
    assert script.run() == 0
    assert (script.launches, script.pauses) == (3, [])


def test_restart_requests_beyond_the_limit_count_as_failures():
    script = _Script([supervisor.RESTART_REQUESTED_EXIT] * 20)
    assert script.run() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.launches == 10
    assert script.pauses == [5.0] * 4


def test_a_command_that_cannot_start_counts_as_a_failure():
    script = _Script([OSError("missing")] * 5)
    assert script.run() == supervisor.LAUNCHER_GAVE_UP_EXIT
    assert script.launches == 5
    assert "could not start" in script.lines[0]


# ----------------------------------------------------------------------- Linux


@linux
def test_linux_launcher_refuses_to_run():
    assert supervisor_launcher.main(["--name", "x", "--state-dir", "d", "--", "true"]) == 64


@linux
def test_linux_facade_loads_no_windows_module():
    probe = textwrap.dedent("""
        import sys
        from self_learn.primitives import supervisor
        assert supervisor.host_name() == "self-learn-host.service"
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
    binary, calls, _ = systemctl_spy
    unit = "self-learn-host.service"
    supervisor.restart(unit, timeout=10)
    supervisor.stop("self-learn-run-0123456789ab.service", timeout=10)
    supervisor.start(unit, timeout=3)
    supervisor.register(unit, ["ignored"], description="ignored", timeout=4)
    supervisor.unregister(unit, timeout=5)
    assert [(argv, timeout) for argv, timeout, _ in calls] == [
        ([binary, "--user", "reset-failed", unit], 10),
        ([binary, "--user", "restart", unit], 10),
        ([binary, "--user", "stop", "self-learn-run-0123456789ab.service"], 10),
        ([binary, "--user", "start", unit], 3),
        ([binary, "--user", "enable", unit], 4),
        ([binary, "--user", "stop", unit], 5),
        ([binary, "--user", "disable", unit], 5),
    ]
    assert all(kwargs == {} for _, _, kwargs in calls)


@linux
def test_linux_running_status_is_one_is_active_call(systemctl_spy):
    binary, calls, replies = systemctl_spy
    replies["is-active"] = (0, "active\n", "")
    assert supervisor.status("self-learn-host.service", timeout=1.0) == supervisor.ServiceStatus(
        "running", "active", None)
    assert [argv for argv, _, _ in calls] == [[binary, "--user", "is-active", "self-learn-host.service"]]
    assert calls[0][1] == 1.0


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
    replies["is-active"] = (FileNotFoundError(2, "gone"), "", "")
    with pytest.raises(supervisor.SupervisorUnavailable):
        supervisor.status(unit)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(supervisor.SupervisorUnavailable, match="^systemctl is not on PATH$"):
        supervisor.stop(unit)


_FAKE_SYSTEMCTL = """\
#!{python}
import os, sys
from pathlib import Path
Path(os.environ["FAKE_SYSTEMCTL_LOG"]).open("a").write(" ".join(sys.argv[1:]) + "\\n")
verb = sys.argv[2]
if verb == "is-active":
    print(os.environ["FAKE_ACTIVE"])
    sys.exit(0 if os.environ["FAKE_ACTIVE"] == "active" else 3)
if verb == "show":
    print(os.environ["FAKE_SHOW"].replace(";", "\\n"))
"""


@linux
@pytest.mark.parametrize("active, show, expected", [
    ("active", "", ("running", None)),
    ("activating", "", ("running", None)),
    ("deactivating", "", ("running", None)),
    ("inactive", "LoadState=loaded;ActiveState=inactive;Result=success;ExecMainStatus=0", ("stopped", 0)),
    ("failed", "LoadState=loaded;ActiveState=failed;Result=exit-code;ExecMainStatus=3", ("failed", 3)),
    ("inactive", "LoadState=loaded;ActiveState=inactive;Result=start-limit-hit;ExecMainStatus=1", ("failed", 1)),
    ("inactive", "LoadState=not-found;ActiveState=inactive;Result=success;ExecMainStatus=0", ("missing", 0)),
])
def test_linux_status_through_a_fake_systemctl(tmp_path, monkeypatch, active, show, expected):
    fake = tmp_path / "bin" / "systemctl"
    fake.parent.mkdir()
    fake.write_text(_FAKE_SYSTEMCTL.format(python=sys.executable))
    fake.chmod(0o755)
    log = tmp_path / "calls"
    monkeypatch.setenv("PATH", str(fake.parent))
    monkeypatch.setenv("FAKE_SYSTEMCTL_LOG", str(log))
    monkeypatch.setenv("FAKE_ACTIVE", active)
    monkeypatch.setenv("FAKE_SHOW", show)
    result = supervisor.status("self-learn-host.service", timeout=10)
    assert (result.state, result.last_result) == expected
    assert result.raw == active
    asked = log.read_text().splitlines()
    assert asked[0] == "--user is-active self-learn-host.service"
    if expected[0] != "running":
        assert asked[1:] == [
            "--user show self-learn-host.service --property=LoadState,ActiveState,Result,ExecMainStatus"]
        assert supervisor.last_result("self-learn-host.service", timeout=10) == expected[1]


# --------------------------------------------------------------------- Windows


_HOST = """\
import os, subprocess, sys, time
from pathlib import Path
out, mode = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
with open(out / "launches", "a") as fh:
    fh.write(f"{os.getpid()} {time.time()}\\n")
launches = len((out / "launches").read_text().splitlines())
if mode == "crash":
    sys.exit(3)
if mode == "clean":
    sys.exit(0)
if mode == "restart-once":
    sys.exit(75 if launches == 1 else 0)
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
(out / "pids.tmp").write_text(f"{os.getpid()} {grandchild.pid}")
os.replace(out / "pids.tmp", out / "pids")
time.sleep(600)
"""


def _wait_for(predicate, timeout=30.0, what="condition"):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.1)


@pytest.fixture
def win(tmp_path, monkeypatch):
    """Unique task names, the stand-in host, and cleanup of every task and
    every recorded process, whatever the test's outcome."""
    from self_learn.primitives import _supervisor_tasks as tasks

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    host = tmp_path / "host.py"
    host.write_text(_HOST)
    names: list[str] = []
    dirs: list[Path] = []

    class Win:
        tasks_module = tasks
        python = getattr(sys, "_base_executable", sys.executable)

        @staticmethod
        def name():
            names.append(f"self-learn-test-{uuid4().hex[:12]}")
            return names[-1]

        @staticmethod
        def out(label):
            dirs.append(tmp_path / label)
            return dirs[-1]

        @staticmethod
        def host_argv(out, mode):
            return [Win.python, str(host), str(out), mode]

        @staticmethod
        def launcher(name, state, out, mode, *extra):
            argv = [str(tasks.launcher_path()), "--name", name, "--state-dir", str(state), *extra,
                    "--", *Win.host_argv(out, mode)]
            return subprocess.Popen(argv)

        @staticmethod
        def pids(out):
            path = _wait_for(lambda: (out / "pids").is_file() and out / "pids", what=f"{out}/pids")
            return tuple(map(int, path.read_text().split()))

        @staticmethod
        def launches(out):
            path = out / "launches"
            return [float(line.split()[1]) for line in path.read_text().splitlines()] if path.is_file() else []

    yield Win
    schtasks = tasks.schtasks_exe()
    for name in names:
        subprocess.run([schtasks, "/End", "/TN", name], capture_output=True, timeout=30)
        subprocess.run([schtasks, "/Delete", "/TN", name, "/F"], capture_output=True, timeout=30)
    for out in dirs:
        if (out / "pids").is_file():
            for pid in (out / "pids").read_text().split():
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=30)


def _gone(*pids):
    return all(not procs.pid_alive(pid) for pid in pids)


@windows
def test_windows_crash_is_relaunched_until_the_limit(win, tmp_path):
    name, out = win.name(), win.out("crash")
    launcher = win.launcher(name, tmp_path / "state", out, "crash", "--restart-delay", "0.5")
    assert launcher.wait(timeout=60) == supervisor.LAUNCHER_GAVE_UP_EXIT
    times = win.launches(out)
    assert len(times) == supervisor.START_LIMIT_BURST
    assert all(later - earlier >= 0.45 for earlier, later in zip(times, times[1:]))
    log = (tmp_path / "state" / f"{name}.log").read_text()
    assert "relaunching in 0.5 s" in log and "giving up" in log


@windows
def test_windows_clean_exit_is_not_relaunched(win, tmp_path):
    name, out = win.name(), win.out("clean")
    launcher = win.launcher(name, tmp_path / "state", out, "clean", "--restart-delay", "0.5")
    assert launcher.wait(timeout=60) == 0
    time.sleep(1.0)
    assert len(win.launches(out)) == 1


@windows
def test_windows_restart_code_relaunches_at_once(win, tmp_path):
    name, out = win.name(), win.out("restart")
    started = time.monotonic()
    launcher = win.launcher(name, tmp_path / "state", out, "restart-once", "--restart-delay", "60")
    assert launcher.wait(timeout=45) == 0
    assert time.monotonic() - started < 40
    times = win.launches(out)
    assert len(times) == 2 and times[1] - times[0] < 10


@windows
def test_windows_second_launcher_exits_and_stop_request_ends_the_first(win, tmp_path):
    name, state = win.name(), tmp_path / "state"
    first_out, second_out = win.out("first"), win.out("second")
    first = win.launcher(name, state, first_out, "serve")
    try:
        host, grandchild = win.pids(first_out)
        second = win.launcher(name, state, second_out, "serve")
        assert second.wait(timeout=30) == supervisor.LAUNCHER_ALREADY_RUNNING_EXIT
        assert not (second_out / "launches").exists()
        assert win.tasks_module.request_stop(name)
        assert first.wait(timeout=30) == 0
        _wait_for(lambda: _gone(host, grandchild), what="the stopped host and its grandchild to end")
        assert len(win.launches(first_out)) == 1
        # Control: with the first launcher gone, the same command does start.
        third = win.launcher(name, state, second_out, "serve")
        win.pids(second_out)
        assert win.tasks_module.request_stop(name)
        assert third.wait(timeout=30) == 0
    finally:
        if first.poll() is None:
            first.kill()


def _definition(name):
    import win32com.client

    service = win32com.client.Dispatch("Schedule.Service")
    service.Connect()
    return service.GetFolder("\\").GetTask("\\" + name).Definition


@windows
def test_windows_task_lifecycle(win, tmp_path):
    tasks = win.tasks_module
    name, out = win.name(), win.out("lifecycle")
    home = tmp_path / "home"
    supervisor.register(name, win.host_argv(out, "serve"), description="self-learn test host", home=home)
    never = supervisor.status(name)
    assert never == supervisor.ServiceStatus("stopped", "Ready", tasks.SCHED_S_TASK_HAS_NOT_RUN)

    definition = _definition(name)
    settings, action = definition.Settings, definition.Actions.Item(1)
    assert settings.MultipleInstances == 2  # TASK_INSTANCES_IGNORE_NEW
    assert settings.ExecutionTimeLimit == "PT0S"
    assert settings.StartWhenAvailable and not settings.DisallowStartIfOnBatteries
    assert not settings.StopIfGoingOnBatteries
    assert definition.Principal.LogonType == 3  # TASK_LOGON_INTERACTIVE_TOKEN
    assert definition.Triggers.Item(1).Type == 9  # TASK_TRIGGER_LOGON
    assert definition.Triggers.Item(1).UserId.lower() == tasks.current_user().lower()
    assert Path(action.Path) == tasks.launcher_path() and action.Path.endswith("self-learn-supervise.exe")
    state = supervisor.state_dir(home)
    assert str(state) in action.Arguments and str(home) in action.Arguments
    assert "SELF_LEARN" not in definition.XmlText.replace("self-learn", "")

    supervisor.start(name)
    host, grandchild = win.pids(out)
    running = supervisor.status(name)
    assert (running.state, running.raw) == ("running", "Running")
    supervisor.start(name)  # Already running: no second /Run, no overwritten result.
    assert supervisor.status(name) == running
    assert len(win.launches(out)) == 1

    supervisor.stop(name)
    assert supervisor.status(name) == supervisor.ServiceStatus("stopped", "Ready", 0)
    _wait_for(lambda: _gone(host, grandchild), what="the stopped host and its grandchild to end")
    log = (state / f"{name}.log").read_text()
    assert "stop requested" in log

    supervisor.restart(name)
    _wait_for(lambda: len(win.launches(out)) == 2, what="the restarted host")
    assert supervisor.status(name).state == "running"
    supervisor.unregister(name)
    assert supervisor.status(name) == supervisor.ServiceStatus("missing", "missing", None)
    assert supervisor.last_result(name) is None
    supervisor.unregister(name)  # Already gone: nothing to do.


@windows
def test_windows_end_kills_host_and_grandchild(win, tmp_path):
    tasks = win.tasks_module
    # Positive control first: a task whose action is the host itself leaves
    # the grandchild running after /End (spike section 6).
    bare, bare_out = win.name(), win.out("bare")
    argv = win.host_argv(bare_out, "serve")
    tasks.create_task(bare, tasks.task_xml(
        user=tasks.current_user(), command=argv[0], arguments=subprocess.list2cmdline(argv[1:]),
        working_directory=str(tmp_path), description="self-learn test control"), timeout=30)
    supervisor.start(bare)
    bare_host, bare_grandchild = win.pids(bare_out)
    tasks.end(bare, timeout=30)
    _wait_for(lambda: _gone(bare_host), what="the bare host to end")
    time.sleep(3)
    assert procs.pid_alive(bare_grandchild), "control: without the launcher's job the grandchild survives"

    name, out = win.name(), win.out("ended")
    supervisor.register(name, win.host_argv(out, "serve"), description="self-learn test host",
                        home=tmp_path / "home")
    supervisor.start(name)
    host, grandchild = win.pids(out)
    tasks.end(name, timeout=30)
    _wait_for(lambda: _gone(host, grandchild), timeout=15, what="the ended host and its grandchild")
    assert supervisor.status(name) == supervisor.ServiceStatus("stopped", "Ready", tasks.SCHED_S_TASK_TERMINATED)


@windows
def test_windows_failed_and_missing_status(win, tmp_path):
    tasks = win.tasks_module
    name = win.name()
    tasks.create_task(name, tasks.task_xml(
        user=tasks.current_user(), command=win.python, arguments='-c "import sys; sys.exit(3)"',
        working_directory=str(tmp_path), description="self-learn test failure"), timeout=30)
    supervisor.start(name)
    found = _wait_for(lambda: (s := supervisor.status(name)).state != "running" and s.last_result != tasks.SCHED_S_TASK_HAS_NOT_RUN and s,
                      what="the failing task to finish")
    assert found == supervisor.ServiceStatus("failed", "Ready", 3)
    assert supervisor.status(win.name()) == supervisor.ServiceStatus("missing", "missing", None)


@windows
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
])
def test_windows_status_mapping(task_state, result, expected):
    from self_learn.primitives import _supervisor_tasks as tasks

    assert tasks.classify(task_state, result) == expected
