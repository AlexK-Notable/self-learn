"""Task Scheduler behind ``primitives.supervisor``, and the operating-system
side of the ``self-learn-supervise`` launcher.

What GitHub's Windows runner measured (``w3-taskspike-findings.md``) and
this backend relies on:

- A per-user task with ``InteractiveToken`` and a ``LogonTrigger`` naming
  the current user registers without administrator rights; ``S4U`` and an
  any-user logon trigger are refused (section 9).
- Task Scheduler never relaunches a task whose process exits nonzero
  (section 4), so the action is the launcher, which relaunches the host.
- ``schtasks /End`` ends only the task's own process (section 6): the
  launcher keeps the host in a kill-on-close job, so the host and its
  descendants end with it.
- A second ``/Run`` of a running ``IgnoreNew`` task exits 0 and overwrites
  the last result (section 5): :func:`start` asks the state first, and
  :func:`status` reads the state before the last result.

The state and the last result are read through the Task Scheduler COM
interface (``Schedule.Service``): its ``State`` is an enumeration and its
``LastTaskResult`` a number, so neither depends on the display language,
where ``schtasks /Query`` prints localised words. Registration, start, end
and removal use ``schtasks.exe`` from the system directory, never PATH.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from . import fsops, procs
from .supervisor import (
    STOP_EVENT_ENV,
    STOP_WAIT_SECS,
    ServiceStatus,
    State,
    SupervisorRefused,
    SupervisorUnavailable,
    state_dir,
)

if sys.platform == "win32":
    import pythoncom
    import pywintypes
    import win32api
    import win32con
    import win32event
    import winerror
    import win32com.client
else:
    raise NotImplementedError("Task Scheduler operations require Windows")


HOST_NAME = "self-learn-host"
LAUNCHER_EXE = "self-learn-supervise.exe"

#: Task Scheduler's own result codes, each observed on the runner.
SCHED_S_TASK_READY = 0x00041300
SCHED_S_TASK_RUNNING = 0x00041301
SCHED_S_TASK_HAS_NOT_RUN = 0x00041303
SCHED_S_TASK_TERMINATED = 0x00041306
#: Results that mean the last run ended cleanly or was ended on purpose
#: (``/End``, like systemd's ``SuccessExitStatus=143 SIGTERM``).
CLEAN_RESULTS = frozenset({0, SCHED_S_TASK_READY})

#: ``TASK_STATE`` (taskschd.h). Queued counts as running: the run is on its way.
TASK_STATES = {0: "Unknown", 1: "Disabled", 2: "Queued", 3: "Ready", 4: "Running"}
RUNNING_STATES = frozenset({2, 4})

_POLL_SECS = 0.2
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_NOT_FOUND = (winerror.ERROR_FILE_NOT_FOUND, winerror.ERROR_PATH_NOT_FOUND)


def _signed(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def _win32_code(hresult: int) -> int:
    """The Win32 error inside an ``HRESULT_FROM_WIN32`` value, else the value."""
    unsigned = hresult & 0xFFFFFFFF
    return unsigned & 0xFFFF if unsigned & 0xFFFF0000 == 0x80070000 else _signed(hresult)


@contextmanager
def _os_errors(filename: str | None = None) -> Iterator[None]:
    """pywin32 and COM errors reach callers as ``OSError`` with ``winerror``."""
    try:
        yield
    except pywintypes.com_error as exc:
        # com_error(hresult, text, excepinfo, argerror); excepinfo[5] is the
        # error the server raised when the call itself failed.
        args: list[Any] = [*exc.args, None, None, None][:3]
        hresult, message, info = args
        code = _signed(info[5]) if info and len(info) > 5 and info[5] else _signed(int(hresult or 0))
        text = (info[2] if info and len(info) > 2 and info[2] else None) or str(message or exc)
        raise OSError(0, text, filename, _win32_code(code)) from exc
    except pywintypes.error as exc:
        raise OSError(0, exc.strerror, filename, exc.winerror) from exc


def check_name(name: str) -> str:
    """Task names here are plain: letters, digits, ``.``, ``_`` and ``-``.
    The same name spells the launcher's event and its files."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"unsupported task name {name!r}")
    return name


def schtasks_exe() -> str:
    return str(Path(win32api.GetSystemDirectory()) / "schtasks.exe")


def _schtasks(verb: str, name: str, args: Sequence[str], timeout: float) -> str:
    try:
        proc = procs.run_bounded([schtasks_exe(), verb, *args], timeout=timeout, binary=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SupervisorUnavailable(f"schtasks {verb} {name} failed: {exc}", verb=verb, name=name,
                                    detail=str(exc)) from exc
    out = proc.stdout.decode("oem", "replace")
    if proc.returncode != 0:
        detail = (proc.stderr.decode("oem", "replace") or out).strip()[:400]
        raise SupervisorRefused(f"schtasks {verb} {name} exited {proc.returncode}: {detail}",
                                verb=verb, name=name, detail=detail, returncode=proc.returncode)
    return out


def query(name: str) -> tuple[int, int] | None:
    """``(TASK_STATE, last result)`` of the task, or ``None`` when there is
    no such task. The last result is signed, as ``schtasks`` prints it."""
    check_name(name)
    try:
        pythoncom.CoInitialize()
    except pywintypes.com_error:
        pass  # This thread already joined another apartment; COM still works.
    try:
        with _os_errors(name):
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            task = service.GetFolder("\\").GetTask("\\" + name)
            return int(task.State), _signed(int(task.LastTaskResult))
    except OSError as exc:
        if exc.winerror in _NOT_FOUND:
            return None
        raise


def classify(task_state: int, result: int) -> State:
    """The state comes first: while a task runs, a refused second ``/Run``
    overwrites its last result (spike section 5)."""
    if result not in CLEAN_RESULTS | {SCHED_S_TASK_RUNNING}:
        return "failed"
    if task_state in RUNNING_STATES:
        return "running"
    return "stopped" if result in CLEAN_RESULTS and result != 0 else "failed"


def status(name: str, *, timeout: float) -> ServiceStatus:
    del timeout  # COM has no per-call bound; the query is local.
    found = query(name)
    if found is None:
        return ServiceStatus("missing", "missing", None)
    task_state, result = found
    return ServiceStatus(classify(task_state, result), TASK_STATES.get(task_state, str(task_state)), result)


def last_result(name: str, *, timeout: float) -> int | None:
    return status(name, timeout=timeout).last_result


def _wait_until_stopped(name: str, deadline: float) -> bool:
    while True:
        found = query(name)
        if found is None or found[0] not in RUNNING_STATES:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_SECS)


def _missing(verb: str, name: str) -> SupervisorRefused:
    return SupervisorRefused(f"schtasks {verb} {name}: no such task", verb=verb, name=name,
                             detail="no such task")


def start(name: str, *, timeout: float) -> None:
    found = query(name)
    if found is None:
        raise _missing("/Run", name)
    if False:
        return  # A second /Run would only overwrite the last result.
    _schtasks("/Run", name, ["/TN", name], timeout)


def end(name: str, *, timeout: float) -> None:
    """``schtasks /End``: ends the launcher; its job ends the host."""
    _schtasks("/End", name, ["/TN", name], timeout)


def stop(name: str, *, timeout: float) -> None:
    found = query(name)
    if found is None:
        raise _missing("/End", name)
    if found[0] not in RUNNING_STATES:
        return
    if request_stop(name) and _wait_until_stopped(name, time.monotonic() + STOP_WAIT_SECS):
        return
    end(name, timeout=timeout)
    if not _wait_until_stopped(name, time.monotonic() + timeout):
        raise SupervisorRefused(f"schtasks /End {name}: the task still runs", verb="/End", name=name,
                                detail="still running")


def restart(name: str, *, timeout: float) -> None:
    stop(name, timeout=timeout)
    start(name, timeout=timeout)


def unregister(name: str, *, timeout: float) -> None:
    found = query(name)
    if found is None:
        return
    if found[0] in RUNNING_STATES:
        stop(name, timeout=timeout)
    _schtasks("/Delete", name, ["/TN", name, "/F"], timeout)


def current_user() -> str:
    """``DOMAIN\\user``, the form the trial registered with."""
    with _os_errors():
        return win32api.GetUserNameEx(win32con.NameSamCompatible)


def launcher_path() -> Path:
    """The windowless launcher uv installs beside this interpreter."""
    return Path(sys.executable).parent / LAUNCHER_EXE


def task_xml(*, user: str, command: str, arguments: str, working_directory: str,
             description: str) -> bytes:
    """The task the trial registered (spike, "Full Accepted XML"), UTF-16
    with a byte order mark. It carries no environment and no secret: the
    launcher's arguments name the ledger, the log folder and the host."""
    text = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>5</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(working_directory)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
    return b"\xff\xfe" + text.replace("\n", "\r\n").encode("utf-16-le")


def create_task(name: str, xml: bytes, *, timeout: float) -> None:
    """``schtasks /Create /XML`` from a temporary file that is removed after."""
    check_name(name)
    with tempfile.TemporaryDirectory(prefix="self-learn-task-") as scratch:
        path = Path(scratch) / f"{name}.xml"
        fsops.atomic_write(path, xml, fsync=False)
        _schtasks("/Create", name, ["/XML", str(path), "/TN", name, "/F"], timeout)


def register(name: str, command: list[str], *, description: str, home: Path,
             timeout: float) -> None:
    check_name(name)
    if not command or not os.path.isabs(command[0]):
        raise ValueError("the supervised command needs an absolute program path")
    launcher = launcher_path()
    if not launcher.is_file():
        raise SupervisorUnavailable(f"{launcher} is missing; run `uv sync` for the CLI",
                                    verb="/Create", name=name, detail=str(launcher))
    home = Path(os.path.abspath(home.expanduser()))
    folder = state_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    arguments = subprocess.list2cmdline(
        ["--name", name, "--state-dir", str(folder), "--home", str(home), "--", *command])
    xml = task_xml(user=current_user(), command=str(launcher), arguments=arguments,
                   working_directory=str(folder), description=description)
    create_task(name, xml, timeout=timeout)


# ------------------------------------------------------------- the launcher's side


def stop_event_name(name: str) -> str:
    return f"Local\\self-learn-supervise-{check_name(name)}-stop"


def request_stop(name: str) -> bool:
    """Signal the launcher's stop event; ``False`` when no launcher of that
    name runs in this session."""
    try:
        with _os_errors(name):
            handle = win32event.OpenEvent(win32con.EVENT_MODIFY_STATE, False, stop_event_name(name))
    except OSError as exc:
        if exc.winerror in _NOT_FOUND:
            return False
        raise
    try:
        with _os_errors(name):
            win32event.SetEvent(handle)
    finally:
        win32api.CloseHandle(handle)
    return True


class LauncherRuntime:
    """One launcher's stop event (manual reset, so it stays signalled once
    set) and the children it starts, each in its own kill-on-close job."""

    def __init__(self, name: str, *, grace: float) -> None:
        self.event_name = stop_event_name(name)
        self._grace = grace
        with _os_errors(name):
            self._event: Any = win32event.CreateEvent(None, True, False, self.event_name)

    def child_environment(self, base: Mapping[str, str], extra: Mapping[str, str]) -> dict[str, str]:
        return {**base, **extra, STOP_EVENT_ENV: self.event_name}

    def launch(self, argv: Sequence[str], *, env: Mapping[str, str], output: Path) -> Callable[[], int | None]:
        """Start *argv*; return its waiter. The waiter gives the exit code,
        or ``None`` after a stop request (the child had ``grace`` seconds
        to finish, then its job was ended)."""
        from . import _procs_windows

        child = _procs_windows.start_supervised(argv, env=env, output=str(output))

        def wait() -> int | None:
            try:
                code = child.wait(wake=self._event)
                if code is not None:
                    return code or 3
                if child.wait(self._grace) is None:
                    child.terminate()
                return None
            finally:
                child.close()  # Ends anything the child left running in its job.

        return wait

    def pause(self, seconds: float) -> bool:
        """Sleep up to *seconds*; ``True`` when a stop was requested."""
        with _os_errors():
            millis = max(0, int(seconds * 1000))
            return win32event.WaitForSingleObject(self._event, millis) == win32event.WAIT_OBJECT_0

    def close(self) -> None:
        win32api.CloseHandle(self._event)
