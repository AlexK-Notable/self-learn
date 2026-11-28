"""A cooperative stop request for a running ``ask`` or ``summarise`` on
Windows (parity plan 1.14 and 3.4 row 6C).

On Linux the page's Stop, its watchdog and a service stop end these verbs
with SIGTERM sent to the verb's process group, and their handlers turn it
into a clean stop. Windows cannot deliver SIGTERM to another process, and a
process started without a console never receives a console control event.
So on Windows the running command polls for a **stop file** instead. Every
file lives in ``<runtime root>/stop-requests/`` (:func:`stop_dir`), a
private folder created through :mod:`fsops`, and is named
``<pid>-<creation>`` with ``<creation>`` the process's creation time, so a
file meant for a process that has exited can never stop a later process
that reuses its PID.

- :func:`watch` (``handler``), called by the verb on its main thread
  around the model call, writes the watch marker ``<pid>-<creation>.watch``,
  installs *handler* for ``SIGBREAK`` (so a console Ctrl+Break, when there
  is a console, stops the turn too) and starts a thread that looks for
  this process's own ``<pid>-<creation>.stop`` every :data:`POLL_SECS`.
  When the file is there, the thread raises ``SIGBREAK`` in the main thread
  (``_thread.interrupt_main``), which runs *handler* exactly as SIGTERM
  runs it on Linux. A stop request made before the watch began is honoured
  at once. Files named for a process that no longer runs under that
  creation time (a stale one for this PID included) are never honoured and
  are removed.
- :func:`request_stop` (``pid``) is the Windows counterpart of signalling
  the process group: on Windows a console script and a virtual
  environment's ``python.exe`` are launchers that run the interpreter as a
  child, so the PID a caller holds is often not the watching process. It
  writes a stop file for every watching process in the tree under *pid*
  (*pid* and its descendants, each created no earlier than its parent),
  and, when none is watching yet, for every process of that tree, so a
  request that comes before the watch starts is not lost.
- :func:`unwatch` stops the thread, puts the previous ``SIGBREAK`` handler
  back and removes this process's stop file and marker. It is idempotent.

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

__all__ = ["POLL_SECS", "request_stop", "stop_dir", "stop_path", "unwatch", "watch",
           "watch_path"]

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
#: ``CreateToolhelp32Snapshot``: every process.
_SNAP_PROCESSES = 0x2
#: ``Process32NextW`` past the last entry.
_NO_MORE_FILES = 18


def stop_dir() -> Path:
    """The folder of stop files: the runtime root, which falls back to the
    application cache root (not a per-ledger folder), so a requester and
    the running command agree on it without knowing its ledger."""
    return names.runtime_root(fallback=names.cache_root) / STOP_DIR


def stop_path(pid: int, identity: str) -> Path:
    return stop_dir() / f"{int(pid)}-{identity}.stop"


def watch_path(pid: int, identity: str) -> Path:
    return stop_dir() / f"{int(pid)}-{identity}.watch"


def _win_error(exc: Any) -> OSError:
    return OSError(0, getattr(exc, "strerror", str(exc)), None, getattr(exc, "winerror", None))


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


def _parents() -> dict[int, int]:
    """Every process's parent PID, from one process snapshot. Windows only;
    a Win32 failure is an :class:`OSError` with ``winerror`` set."""
    if sys.platform != "win32":
        raise NotImplementedError("process snapshots are taken on Windows only")
    import ctypes
    from ctypes import wintypes

    class _Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot_fn = kernel32.CreateToolhelp32Snapshot
    snapshot_fn.restype = wintypes.HANDLE
    snapshot_fn.argtypes = (wintypes.DWORD, wintypes.DWORD)
    first, following = kernel32.Process32FirstW, kernel32.Process32NextW
    for fn in (first, following):
        fn.restype = wintypes.BOOL
        fn.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = snapshot_fn(_SNAP_PROCESSES, 0)
    if snapshot in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    out: dict[int, int] = {}
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        ok = first(snapshot, ctypes.byref(entry))
        while ok:
            out[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = following(snapshot, ctypes.byref(entry))
        code = ctypes.get_last_error()
        if code != _NO_MORE_FILES:
            raise ctypes.WinError(code)
    finally:
        kernel32.CloseHandle(snapshot)
    return out


def _tree(pid: int, identity: str) -> list[tuple[int, str]]:
    """*pid* and its running descendants, each with its creation time. A
    child created before its recorded parent is not its child: that parent
    PID was reused, so the walk does not go down it."""
    children: dict[int, list[int]] = {}
    for child, parent in _parents().items():
        if child != parent:
            children.setdefault(parent, []).append(child)
    found = [(pid, identity)]
    seen = {pid}
    queue = [(pid, int(identity))]
    while queue:
        parent, born = queue.pop()
        for child in children.get(parent, []):
            if child in seen:
                continue
            seen.add(child)
            created = _identity(child)
            if created is None or int(created) < born:
                continue
            found.append((child, created))
            queue.append((child, int(created)))
    return found


def _write_stop(path: Path) -> None:
    """The one writer of this module: a stop file or a watch marker, in
    the cache."""
    fsops.ensure_private_parent(path.parent)
    fsops.private_write(path, chrono.now_iso() + "\n")


def _drop_stop(path: Path) -> None:
    """The one remover of this module: a stop file or a watch marker, in
    the cache."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def request_stop(pid: int) -> bool:
    """Ask the running ``ask`` or ``summarise`` started as process *pid*
    (directly, or under a launcher) to stop. ``True`` when a request was
    written; ``False`` when no running process has that PID (nothing is
    written). Windows only: on Linux these verbs stop on SIGTERM, and this
    raises :class:`NotImplementedError`."""
    if os.name != "nt":
        raise NotImplementedError("on this platform these commands stop on SIGTERM")
    identity = _identity(int(pid))
    if identity is None:
        return False
    tree = _tree(int(pid), identity)
    watching = [(p, i) for p, i in tree if watch_path(p, i).is_file()]
    for p, i in watching or tree:
        _write_stop(stop_path(p, i))
    return True


def _requested(path: Path) -> bool:
    try:
        return path.is_file() and not fsops.is_link(path) and fsops.owned_by_current_user(path)
    except OSError:
        return False


def _drop_stale() -> None:
    """Remove every stop file and watch marker named for a process that no
    longer runs under that creation time: it was meant for a process that
    has exited (a launcher's request included)."""
    folder = stop_dir()
    try:
        entries = [entry.name for entry in os.scandir(folder)]
    except OSError:
        return
    for name in entries:
        stem, dot, ext = name.rpartition(".")
        pid, dash, identity = stem.partition("-")
        if not (dot and dash and ext in ("stop", "watch") and pid.isdigit() and identity.isdigit()):
            continue
        try:
            alive = _identity(int(pid)) == identity
        except OSError:
            continue
        if not alive:
            _drop_stop(folder / name)


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
        self.marker = watch_path(pid, identity)
        _drop_stale()
        _write_stop(self.marker)
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
        _drop_stop(self.marker)


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
