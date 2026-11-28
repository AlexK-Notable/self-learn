"""A cooperative stop request for a running ``ask`` or ``summarise`` on
Windows (parity plan 1.14 and 3.4 row 6C).

On Linux the page's Stop, its watchdog and a service stop end these verbs
with SIGTERM, and their handlers turn it into a clean stop. Windows cannot
deliver SIGTERM to another process, and a process started without a
console never receives a console control event. So on Windows the running
command polls for a **stop file** instead:

- :func:`request_stop` (``pid``) writes
  ``<runtime root>/stop-requests/<pid>-<creation>.stop``, created through
  :mod:`fsops` in a private directory. ``<creation>`` is the process's
  creation time, so a file meant for a process that has exited can never
  stop a later process that reuses its PID.
- :func:`watch` (``handler``), called by the verb on its main thread
  around the model call, installs *handler* for ``SIGBREAK`` (so a console
  Ctrl+Break, when there is a console, stops the turn too) and starts a
  thread that looks for this process's own stop file every
  :data:`POLL_SECS`. When the file is there, the thread raises ``SIGBREAK``
  in the main thread (``_thread.interrupt_main``), which runs *handler*
  exactly as SIGTERM runs it on Linux. A file named for this PID with a
  different creation time is stale: it is never honoured, and it is
  removed.
- :func:`unwatch` stops the thread, puts the previous ``SIGBREAK`` handler
  back and removes this process's stop file. It is idempotent.

Nothing here runs on Linux: the verbs call it only when ``os.name ==
"nt"``, and :func:`request_stop` refuses elsewhere. Every file is in the
cache, never in a ledger.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .primitives import chrono, fsops, names

__all__ = ["POLL_SECS", "request_stop", "stop_dir", "stop_path", "unwatch", "watch"]

#: How often a watched command looks for its stop file.
POLL_SECS = 0.2
#: The folder under the runtime root that holds the stop files.
STOP_DIR = "stop-requests"
#: ``OpenProcess`` access that reads a process's times and exit code.
_QUERY_LIMITED = 0x1000
#: ``GetExitCodeProcess`` while the process runs.
_STILL_ACTIVE = 259
#: ``ERROR_INVALID_PARAMETER``: no process has this PID.
_NO_SUCH_PROCESS = 87


def stop_dir() -> Path:
    """The folder of stop files: the runtime root, which falls back to the
    application cache root (not a per-ledger folder), so a requester and
    the running command agree on it without knowing its ledger."""
    return names.runtime_root(fallback=names.cache_root) / STOP_DIR


def stop_path(pid: int, identity: str) -> Path:
    return stop_dir() / f"{int(pid)}-{identity}.stop"


def _win_error(exc: Any) -> OSError:
    error = OSError(0, getattr(exc, "strerror", str(exc)), None, getattr(exc, "winerror", None))
    return error


def _identity(pid: int) -> str | None:
    """The creation time of the running process *pid*, in microseconds
    since 1601 as a decimal string, or ``None`` when no running process has
    that PID. Windows only; a Win32 failure is an :class:`OSError` with
    ``winerror`` set and the original chained."""
    if sys.platform != "win32":
        raise NotImplementedError("process creation times are read on Windows only")
    import pywintypes
    import win32api
    import win32process

    if pid <= 0 or pid > 0xFFFFFFFF:
        return None
    try:
        handle = win32api.OpenProcess(_QUERY_LIMITED, False, pid)
    except pywintypes.error as exc:
        if exc.winerror == _NO_SUCH_PROCESS:
            return None
        raise _win_error(exc) from exc
    try:
        if win32process.GetExitCodeProcess(handle) != _STILL_ACTIVE:
            return None
        created = win32process.GetProcessTimes(handle)["CreationTime"]
    except pywintypes.error as exc:
        raise _win_error(exc) from exc
    finally:
        win32api.CloseHandle(handle)
    if isinstance(created, int):
        return str(created)
    epoch = datetime(1601, 1, 1, tzinfo=created.tzinfo)
    return str((created - epoch) // timedelta(microseconds=1))


def _write_stop(path: Path) -> None:
    """The one writer of this module: a stop file, in the cache."""
    fsops.ensure_private_parent(path.parent)
    fsops.private_write(path, chrono.now_iso() + "\n")


def _drop_stop(path: Path) -> None:
    """The one remover of this module: a stop file, in the cache."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def request_stop(pid: int) -> bool:
    """Ask the running ``ask`` or ``summarise`` with process id *pid* to
    stop. ``True`` when the request was written; ``False`` when no running
    process has that PID (nothing is written). Windows only: on Linux these
    verbs stop on SIGTERM, and this raises :class:`NotImplementedError`."""
    if os.name != "nt":
        raise NotImplementedError("on this platform these commands stop on SIGTERM")
    identity = _identity(int(pid))
    if identity is None:
        return False
    _write_stop(stop_path(pid, identity))
    return True


def _requested(path: Path) -> bool:
    try:
        return path.is_file() and not fsops.is_link(path) and fsops.owned_by_current_user(path)
    except OSError:
        return False


def _drop_stale(pid: int, identity: str) -> None:
    """Remove the stop files named for *pid* under another creation time:
    they were meant for a process that has exited."""
    folder = stop_dir()
    own = f"{pid}-{identity}.stop"
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(f"{pid}-") and entry.name.endswith(".stop") and entry.name != own:
            _drop_stop(folder / entry.name)


def _set_break(handler: Any) -> Any:
    """Install *handler* for ``SIGBREAK``; the previous handler. Windows only."""
    if sys.platform != "win32":
        raise NotImplementedError("SIGBREAK exists on Windows only")
    return signal.signal(signal.SIGBREAK, handler if handler is not None else signal.SIG_DFL)


def _raise_break() -> None:
    """Run the ``SIGBREAK`` handler in the main thread. Windows only."""
    if sys.platform != "win32":
        raise NotImplementedError("SIGBREAK exists on Windows only")
    import _thread

    _thread.interrupt_main(signal.SIGBREAK)


class _Watch:
    def __init__(self, handler: Callable[..., Any]) -> None:
        pid = os.getpid()
        identity = _identity(pid)
        if identity is None:  # this process is running; belt only
            raise OSError(f"cannot read this process's creation time (pid {pid})")
        self.path = stop_path(pid, identity)
        _drop_stale(pid, identity)
        self._closed = False
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._previous = _set_break(handler)
        self._thread = threading.Thread(target=self._poll, name="self-learn-stop-request",
                                        daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        while True:
            if _requested(self.path):
                with self._lock:
                    if not self._closed:
                        _raise_break()
                return
            if self._done.wait(POLL_SECS):
                return

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._done.set()
        self._thread.join(POLL_SECS * 10)
        _set_break(self._previous)
        _drop_stop(self.path)


_active: list[_Watch] = []


def watch(handler: Callable[..., Any]) -> None:
    """Honour a stop request (and a console Ctrl+Break) by running
    *handler* in the main thread, until :func:`unwatch`. Windows only, main
    thread only."""
    unwatch()
    _active.append(_Watch(handler))


def unwatch() -> None:
    """End :func:`watch`: the poller stops, the previous ``SIGBREAK``
    handler is back, and this process's stop file is gone."""
    while _active:
        _active.pop().close()
