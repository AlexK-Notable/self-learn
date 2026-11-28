"""Task Scheduler behind ``primitives.supervisor``, and the operating-system
side of the ``self-learn-supervise`` launcher.

What GitHub's Windows runner measured (``w3-taskspike-findings.md``) and
this backend relies on:

- A per-user task with ``InteractiveToken`` and a ``LogonTrigger`` naming
  the current user registers without administrator rights, in the root
  folder or a subfolder; ``S4U`` and an any-user logon trigger are refused
  (section 9).
- Task Scheduler never relaunches a task whose process exits nonzero
  (section 4), so the action is the launcher, which relaunches the host.
- ``schtasks /End`` ends only the task's own process (section 6): the
  launcher keeps itself and the host in kill-on-close jobs, so the host
  ends with it.
- A second ``/Run`` of a running ``IgnoreNew`` task exits 0 and overwrites
  the last result (section 5): :func:`start` asks the state first, and
  :func:`classify` reads the state before the last result.

One task per user and ledger: ``\\self-learn\\host-<16 hex>``, the hex
being a digest of the user's SID and the ledger's canonical path. The
launcher's lock, log and events carry the same leaf name.

The state and the last result are read through the Task Scheduler COM
interface (``Schedule.Service``) on a short-lived thread that owns its COM
apartment, with a time bound: its ``State`` is an enumeration and its
``LastTaskResult`` a number, so neither depends on the display language,
where ``schtasks /Query`` prints localised words. A query that fails or
does not answer in time is ``unknown``, never ``running`` or ``stopped``.
Registration, start, end and removal use ``schtasks.exe`` from the system
directory, never PATH.

The pywin32 imports are inside the functions that need them, so the
scheduling logic can be exercised with fakes on any platform; only the
facade's Windows branch loads this module in the product.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any
from xml.sax.saxutils import escape

from . import fsops, locks, names, procs
from .supervisor import (
    STOP_EVENT_ENV,
    STOP_WAIT_SECS,
    ServiceStatus,
    State,
    SupervisorRefused,
    SupervisorUnavailable,
    state_dir,
)

FOLDER = "\\self-learn\\"
LAUNCHER_EXE = "self-learn-supervise.exe"

#: Task Scheduler's own result codes, each observed on the runner.
SCHED_S_TASK_READY = 0x00041300
SCHED_S_TASK_RUNNING = 0x00041301
SCHED_S_TASK_HAS_NOT_RUN = 0x00041303
SCHED_S_TASK_TERMINATED = 0x00041306
#: Results that mean the last run ended cleanly or was ended on purpose
#: (``/End``, like systemd's ``SuccessExitStatus=143 SIGTERM``).
CLEAN_RESULTS = frozenset({0, SCHED_S_TASK_READY, SCHED_S_TASK_HAS_NOT_RUN, SCHED_S_TASK_TERMINATED})

#: ``TASK_STATE`` (taskschd.h). Queued counts as running: the run is on its way.
TASK_STATES = {0: "Unknown", 1: "Disabled", 2: "Queued", 3: "Ready", 4: "Running"}
RUNNING_STATES = frozenset({2, 4})

#: The longest one COM query may take before it counts as ``unknown``.
QUERY_SECS = 5.0
#: Time ``stop`` keeps for ``/End`` and the check after it.
END_RESERVE_SECS = 5.0
_POLL_SECS = 0.2
_LEAF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_NOT_FOUND = (2, 3)  # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND


@dataclass(frozen=True)
class QueryFailed:
    """A query that did not answer: the HRESULT (or ``None`` for a timeout
    or a non-COM error) and a short description."""

    code: int | None
    detail: str


Found = tuple[int, int]


def _signed(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def _win32_code(hresult: int) -> int:
    """The Win32 error inside an ``HRESULT_FROM_WIN32`` value, else the value."""
    unsigned = hresult & 0xFFFFFFFF
    return unsigned & 0xFFFF if unsigned & 0xFFFF0000 == 0x80070000 else _signed(hresult)


def _com_code(exc: BaseException) -> int:
    # com_error(hresult, text, excepinfo, argerror); excepinfo[5] is the
    # error the server raised when the call itself failed.
    hresult, _, info = [*getattr(exc, "args", ()), None, None, None][:3]
    if info and len(info) > 5 and info[5]:
        return _signed(int(info[5]))
    return _signed(int(hresult or 0))


@contextmanager
def _os_errors(filename: str | None = None) -> Iterator[None]:
    """pywin32 errors reach callers as ``OSError`` with ``winerror`` set."""
    import pywintypes

    try:
        yield
    except pywintypes.error as exc:
        raise OSError(0, exc.strerror, filename, exc.winerror) from exc


# ------------------------------------------------------------------ names


def leaf(name: str) -> str:
    """The task's own name inside :data:`FOLDER`, which also names the
    launcher's lock, log and events."""
    if not name.startswith(FOLDER) or not _LEAF.fullmatch(name[len(FOLDER):]):
        raise ValueError(f"unsupported task name {name!r}")
    return name[len(FOLDER):]


def check_leaf(value: str) -> str:
    if not _LEAF.fullmatch(value):
        raise ValueError(f"unsupported launcher name {value!r}")
    return value


def current_sid() -> str:
    """The current user's SID, as text."""
    import win32api
    import win32con
    import win32security

    with _os_errors():
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            return win32security.ConvertSidToStringSid(sid)
        finally:
            win32api.CloseHandle(token)


def host_name(home: Path) -> str:
    """One task per user and ledger. The folder is shared by every user
    of the machine, so the digest carries the user's SID as well as the
    ledger's canonical path (``names.registration_key``)."""
    key = names.registration_key(Path(os.path.abspath(home)))
    digest = hashlib.sha256(f"{current_sid()}\0{key}".encode("utf-8")).hexdigest()[:16]
    return f"{FOLDER}host-{digest}"


def stop_event_name(leaf_name: str) -> str:
    return f"Local\\self-learn-supervise-{check_leaf(leaf_name)}-stop"


def ready_event_name(leaf_name: str) -> str:
    return f"Local\\self-learn-supervise-{check_leaf(leaf_name)}-ready"


# ------------------------------------------------------------ native calls


def schtasks_exe() -> str:
    import win32api

    return str(Path(win32api.GetSystemDirectory()) / "schtasks.exe")


def _schtasks(verb: str, name: str, args: Sequence[str], timeout: float) -> str:
    if timeout <= 0:
        raise SupervisorUnavailable(f"schtasks {verb} {name}: no time left", verb=verb, name=name,
                                    detail="deadline passed")
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


def _com_lookup(name: str) -> Found | QueryFailed | None:
    """One query on the calling thread, which must be a fresh one: it joins
    the multithreaded apartment, releases every interface, then leaves."""
    import pythoncom
    import pywintypes
    import win32com.client

    try:
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    except pywintypes.com_error as exc:  # a fresh thread has no apartment yet
        return QueryFailed(_com_code(exc), "CoInitializeEx failed")
    service = folder = task = None
    try:
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            folder = service.GetFolder("\\")
        except pywintypes.com_error as exc:
            return QueryFailed(_com_code(exc), "connecting to Task Scheduler failed")
        try:
            task = folder.GetTask(name)
        except pywintypes.com_error as exc:
            code = _com_code(exc)
            if _win32_code(code) in _NOT_FOUND:
                return None
            return QueryFailed(code, "looking up the task failed")
        try:
            return int(task.State), _signed(int(task.LastTaskResult))
        except pywintypes.com_error as exc:
            return QueryFailed(_com_code(exc), "reading the task failed")
    finally:
        service = folder = task = None
        pythoncom.CoUninitialize()


def query(name: str, *, timeout: float = QUERY_SECS) -> Found | QueryFailed | None:
    """``(TASK_STATE, last result)``, ``None`` when there is no such task,
    or :class:`QueryFailed` when the query failed or did not answer within
    *timeout*. A query that does not answer is left on its daemon thread."""
    leaf(name)
    box: list[Found | QueryFailed | None] = []

    def run() -> None:
        try:
            box.append(_com_lookup(name))
        except BaseException as exc:  # noqa: BLE001 -- reported, never raised
            box.append(QueryFailed(None, f"{type(exc).__name__}: {exc}"))

    worker = threading.Thread(target=run, name="task-scheduler-query", daemon=True)
    worker.start()
    worker.join(max(0.0, timeout))
    if not box:
        return QueryFailed(None, f"no answer within {timeout:g} s")
    return box[0]


def _event_signalled(event_name: str) -> bool:
    """Whether the named event exists in this session and is signalled."""
    import pywintypes
    import win32api
    import win32con
    import win32event

    try:
        handle = win32event.OpenEvent(win32con.SYNCHRONIZE, False, event_name)
    except pywintypes.error as exc:
        if exc.winerror in _NOT_FOUND:
            return False
        raise OSError(0, exc.strerror, event_name, exc.winerror) from exc
    try:
        return win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_OBJECT_0
    finally:
        win32api.CloseHandle(handle)


def host_ready(leaf_name: str) -> bool:
    """The launcher of *leaf_name* runs in this session and has a host
    running (its ready event is set while a host process lives)."""
    return _event_signalled(ready_event_name(leaf_name))


def request_stop(leaf_name: str) -> bool:
    """Signal the launcher's stop event; ``False`` when no launcher of that
    name runs in this session."""
    import pywintypes
    import win32api
    import win32con
    import win32event

    event_name = stop_event_name(leaf_name)
    try:
        handle = win32event.OpenEvent(win32con.EVENT_MODIFY_STATE, False, event_name)
    except pywintypes.error as exc:
        if exc.winerror in _NOT_FOUND:
            return False
        raise OSError(0, exc.strerror, event_name, exc.winerror) from exc
    try:
        with _os_errors(event_name):
            win32event.SetEvent(handle)
    finally:
        win32api.CloseHandle(handle)
    return True


def current_user() -> str:
    """``DOMAIN\\user``, the form the trial registered with."""
    import win32api
    import win32con

    with _os_errors():
        return win32api.GetUserNameEx(win32con.NameSamCompatible)


def launcher_path() -> Path:
    """The windowless launcher uv installs beside this interpreter."""
    return Path(sys.executable).parent / LAUNCHER_EXE


# ---------------------------------------------------------------- status


def classify(task_state: int, result: int) -> State:
    """The state comes first: while a task runs, a refused second ``/Run``
    overwrites its last result (spike section 5)."""
    if task_state in RUNNING_STATES:
        return "running"
    if task_state not in TASK_STATES or task_state == 0:
        return "unknown"
    return "stopped" if result in CLEAN_RESULTS else "failed"


def status(name: str, *, timeout: float) -> ServiceStatus:
    found = query(name, timeout=min(timeout, QUERY_SECS))
    if found is None:
        return ServiceStatus("missing", "missing", None)
    if isinstance(found, QueryFailed):
        code = "" if found.code is None else f" (0x{found.code & 0xFFFFFFFF:08X})"
        return ServiceStatus("unknown", f"query failed: {found.detail}{code}", None)
    task_state, result = found
    return ServiceStatus(classify(task_state, result), TASK_STATES.get(task_state, str(task_state)), result)


def last_result(name: str, *, timeout: float) -> int | None:
    return status(name, timeout=timeout).last_result


# ------------------------------------------------------------- lifecycle


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


@contextmanager
def _serialized(name: str, verb: str, deadline: float) -> Iterator[None]:
    """One lifecycle change per task at a time, across processes of this
    user (a lock under the per-user cache root)."""
    path = names.cache_root() / "supervisor" / f"{leaf(name)}.op.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with locks.open_lock(path, purpose="private") as holder:
        try:
            lease = locks.acquire(holder.fileno(), path=path, wait=max(0.0, _remaining(deadline)))
        except BlockingIOError as exc:
            raise SupervisorUnavailable(f"schtasks {verb} {name}: another change to this task is "
                                        "still in progress", verb=verb, name=name,
                                        detail="busy") from exc
        with lease:
            yield


def _known(verb: str, name: str, deadline: float) -> Found | None:
    found = query(name, timeout=max(0.0, min(_remaining(deadline), QUERY_SECS)))
    if isinstance(found, QueryFailed):
        raise SupervisorUnavailable(f"schtasks {verb} {name}: Task Scheduler did not answer: "
                                    f"{found.detail}", verb=verb, name=name, detail=found.detail,
                                    returncode=found.code)
    return found


def _missing(verb: str, name: str) -> SupervisorRefused:
    return SupervisorRefused(f"schtasks {verb} {name}: no such task", verb=verb, name=name,
                             detail="no such task")


def _wait_stopped(name: str, deadline: float) -> bool:
    """``True`` once the task is seen not running (or gone); a failed query
    is no evidence either way, so it keeps asking until *deadline*."""
    while True:
        left = _remaining(deadline)
        found = query(name, timeout=max(0.0, min(left, QUERY_SECS)))
        if found is None or (not isinstance(found, QueryFailed) and found[0] not in RUNNING_STATES):
            return True
        if _remaining(deadline) <= 0:
            return False
        time.sleep(min(_POLL_SECS, max(0.0, _remaining(deadline))))


def _start(name: str, deadline: float) -> None:
    found = _known("/Run", name, deadline)
    if found is None:
        raise _missing("/Run", name)
    if found[0] not in RUNNING_STATES:
        # A second /Run of a running task would only overwrite its result.
        _schtasks("/Run", name, ["/TN", name], _remaining(deadline))
    seen_running = found[0] in RUNNING_STATES
    while True:
        if host_ready(leaf(name)):
            return
        found = query(name, timeout=max(0.0, min(_remaining(deadline), QUERY_SECS)))
        if found is None:
            raise _missing("/Run", name)
        if not isinstance(found, QueryFailed):
            if found[0] in RUNNING_STATES:
                seen_running = True
            elif seen_running:
                raise SupervisorRefused(
                    f"schtasks /Run {name}: the launcher ended (last result {found[1]}) before a "
                    "host started", verb="/Run", name=name, detail="launcher ended",
                    returncode=found[1])
        if _remaining(deadline) <= 0:
            raise SupervisorUnavailable(
                f"schtasks /Run {name}: no running host confirmed in time (a launcher in another "
                "login session cannot be seen from here)", verb="/Run", name=name,
                detail="not confirmed")
        time.sleep(min(_POLL_SECS, max(0.0, _remaining(deadline))))


def _end(name: str, timeout: float) -> None:
    _schtasks("/End", name, ["/TN", name], timeout)


def end(name: str, *, timeout: float) -> None:
    """``schtasks /End``: ends the launcher; its job ends the host."""
    _end(name, timeout)


def _stop(name: str, deadline: float) -> None:
    found = _known("/End", name, deadline)
    if found is None:
        raise _missing("/End", name)
    if found[0] not in RUNNING_STATES:
        return
    graceful = min(time.monotonic() + STOP_WAIT_SECS, deadline - END_RESERVE_SECS)
    if request_stop(leaf(name)) and _wait_stopped(name, graceful):
        return
    _end(name, _remaining(deadline))
    if not _wait_stopped(name, deadline):
        raise SupervisorUnavailable(f"schtasks /End {name}: the task was not seen to stop in time",
                                    verb="/End", name=name, detail="still running or unknown")


def start(name: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    with _serialized(name, "/Run", deadline):
        _start(name, deadline)


def stop(name: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    with _serialized(name, "/End", deadline):
        _stop(name, deadline)


def restart(name: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    with _serialized(name, "/Run", deadline):
        _stop(name, deadline)
        _start(name, deadline)


def unregister(name: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    with _serialized(name, "/Delete", deadline):
        found = _known("/Delete", name, deadline)
        if found is None:
            return
        if found[0] in RUNNING_STATES:
            _stop(name, deadline)
        _schtasks("/Delete", name, ["/TN", name, "/F"], _remaining(deadline))
        if _known("/Delete", name, deadline) is not None:
            raise SupervisorRefused(f"schtasks /Delete {name}: the task is still registered",
                                    verb="/Delete", name=name, detail="still registered")


# ---------------------------------------------------------- registration


def refuse_percent(what: str, value: str) -> str:
    """Task Scheduler expands ``%NAME%`` in an action's program, arguments
    and working directory, so a literal ``%`` cannot be carried there."""
    if "%" in value:
        raise ValueError(f"{what} contains '%', which Task Scheduler would expand: {value}")
    return value


def check_program(path: str) -> str:
    """A fully qualified Windows path: a drive or UNC share and a root
    (``\\x.exe`` and ``C:x.exe`` are relative to something)."""
    pure = PureWindowsPath(path)
    if not (pure.drive and pure.root):
        raise ValueError(f"the supervised command needs a fully qualified program path: {path}")
    return path


def task_xml(*, user: str, command: str, arguments: str, working_directory: str,
             description: str) -> bytes:
    """The task the trial registered (spike, "Full Accepted XML") without
    ``RestartOnFailure``: the launcher is the one restart policy. UTF-16
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
    with tempfile.TemporaryDirectory(prefix="self-learn-task-") as scratch:
        path = Path(scratch) / f"{leaf(name)}.xml"
        fsops.atomic_write(path, xml, fsync=False)
        _schtasks("/Create", name, ["/XML", str(path), "/TN", name, "/F"], timeout)


def action_for(name: str, command: Sequence[str], home: Path) -> tuple[str, str, str]:
    """``(program, arguments, working directory)`` of the task's action,
    each checked: no ``%`` anywhere, fully qualified programs."""
    if not command:
        raise ValueError("the supervised command is empty")
    check_program(command[0])
    launcher = str(launcher_path())
    folder = state_dir(home)
    argv = ["--name", leaf(name), "--state-dir", str(folder), "--home", str(home), "--", *command]
    for value in argv:
        refuse_percent("the supervised command", value)
    refuse_percent("the launcher path", launcher)
    return launcher, subprocess.list2cmdline(argv), refuse_percent("the state folder", str(folder))


def register(name: str, command: list[str], *, description: str, home: Path,
             timeout: float) -> None:
    deadline = time.monotonic() + timeout
    home = Path(os.path.abspath(home.expanduser()))
    launcher, arguments, folder = action_for(name, command, home)
    if not Path(launcher).is_file():
        raise SupervisorUnavailable(f"{launcher} is missing; run `uv sync` for the CLI",
                                    verb="/Create", name=name, detail=launcher)
    Path(folder).mkdir(parents=True, exist_ok=True)
    xml = task_xml(user=current_user(), command=launcher, arguments=arguments,
                   working_directory=folder, description=description)
    with _serialized(name, "/Create", deadline):
        create_task(name, xml, timeout=_remaining(deadline))


# ------------------------------------------------------------- the launcher's side


class LauncherRuntime:
    """One launcher's events (both manual reset): *stop* stays set once a
    stop was requested; *ready* is set while a host it started is alive.
    Each host runs in its own kill-on-close job, its output drained into
    *sink* by a thread, so a host never blocks on a full log."""

    def __init__(self, leaf_name: str, *, grace: float) -> None:
        import win32event

        self.event_name = stop_event_name(leaf_name)
        self._grace = grace
        with _os_errors(leaf_name):
            self._event: Any = win32event.CreateEvent(None, True, False, self.event_name)
            self._ready: Any = win32event.CreateEvent(None, True, False, ready_event_name(leaf_name))

    def child_environment(self, base: Mapping[str, str], extra: Mapping[str, str]) -> dict[str, str]:
        return {**base, **extra, STOP_EVENT_ENV: self.event_name}

    def launch(self, argv: Sequence[str], *, env: Mapping[str, str],
               sink: Callable[[bytes], None]) -> Callable[[], int | None]:
        """Start *argv*; return its waiter. The waiter gives the exit code,
        or ``None`` after a stop request (the child had ``grace`` seconds
        to finish, then its job was ended)."""
        if sys.platform != "win32":
            raise NotImplementedError("the launcher's children need Windows")
        import win32event

        from . import _procs_windows

        child = _procs_windows.start_supervised(argv, env=env)

        def drain() -> None:
            try:
                while data := child.read_output():
                    sink(data)
            except OSError:
                pass  # The pipe failed; the host keeps running.
            finally:
                child.close_output()

        threading.Thread(target=drain, name="host-output", daemon=True).start()
        pass

        def wait() -> int | None:
            try:
                code = child.wait(wake=self._event)
                if code is not None:
                    return code
                if child.wait(self._grace) is None:
                    child.terminate()
                return None
            finally:
                with _os_errors():
                    win32event.ResetEvent(self._ready)
                child.close()  # Ends anything the child left running in its job.

        return wait

    def pause(self, seconds: float) -> bool:
        """Sleep up to *seconds*; ``True`` when a stop was requested."""
        import win32event

        with _os_errors():
            millis = max(0, math.ceil(seconds * 1000))
            return win32event.WaitForSingleObject(self._event, millis) == win32event.WAIT_OBJECT_0

    def close(self) -> None:
        import win32api

        win32api.CloseHandle(self._ready)
        win32api.CloseHandle(self._event)
