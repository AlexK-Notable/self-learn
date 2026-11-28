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
  around the model call, checks that the folder is private and not a link,
  removes the files of processes that no longer run under their recorded
  creation time, records its launchers (the running processes it was
  started under, nearest first, each no younger than its child, up to the
  first one that watches for itself) in its watch marker
  ``<pid>-<creation>.watch``, installs *handler* for ``SIGBREAK`` (so a
  console Ctrl+Break, when there is a console, stops the turn too) and
  starts a thread that looks every :data:`POLL_SECS` for a stop file
  addressed to this process or to one of those launchers. When one is
  there, the thread raises ``SIGBREAK`` in the main thread
  (``_thread.interrupt_main``), once, which runs *handler* exactly as
  SIGTERM runs it on Linux.
- :func:`request_stop` (``pid``) is the Windows counterpart of signalling
  the process group: on Windows a console script and a virtual
  environment's ``python.exe`` are launchers that run the interpreter as a
  child, so the PID a caller holds is often not the watching process. It
  writes a stop file for each watching process in the tree under *pid*
  (*pid* and its descendants, each created no earlier than its parent and
  no later than the snapshot, at most :data:`MAX_TREE`). When none is
  watching yet it writes one file, addressed to *pid*: the first command
  under *pid* to start watching finds it among its launchers' requests,
  honours it and removes it, so a stop made too early is honoured once and
  leaves nothing behind. A file whose process has exited is removed by the
  next watch.
- :func:`unwatch` drops a stop that was already on its way, puts the
  previous ``SIGBREAK`` handler back and removes this process's stop file,
  its marker and the requests addressed to its launchers, even when a stop
  interrupts it. It is idempotent.

Nothing here runs on Linux: the verbs call it only when ``os.name ==
"nt"``, and :func:`request_stop` refuses elsewhere. Every file is in the
cache, never in a ledger.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
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
#: The most processes a request walks down, and the most launchers a watch
#: walks up.
MAX_TREE = 256
MAX_ANCESTORS = 8
#: 1601-01-01 to 1970-01-01, in microseconds.
_EPOCH_1601_US = 11_644_473_600 * 1_000_000


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


def _now_identity() -> int:
    """Now, in the unit of :func:`_identity` (microseconds since 1601)."""
    return time.time_ns() // 1000 + _EPOCH_1601_US


def _tree(pid: int, identity: str) -> list[tuple[int, str]]:
    """*pid* and its running descendants, each with its creation time, at
    most :data:`MAX_TREE` of them. A child counts only when it was created
    no earlier than its parent and no later than the snapshot: Windows never
    re-parents an orphan, so a recorded parent PID may since have been
    reused, and a PID may be reused again after the snapshot. A process
    whose times cannot be read (another user's, a protected one) cannot be
    this user's watching command, and is passed over."""
    taken = _now_identity()
    children: dict[int, list[int]] = {}
    for child, parent in _parents().items():
        if child != parent:
            children.setdefault(parent, []).append(child)
    found = [(pid, identity)]
    seen = {pid}
    queue = [(pid, int(identity))]
    while queue and len(found) < MAX_TREE:
        parent, born = queue.pop()
        for child in children.get(parent, []):
            if child in seen or len(found) >= MAX_TREE:
                continue
            seen.add(child)
            created = _identity(child)
            if created is None or not int(created) <= taken:
                continue
            found.append((child, created))
            queue.append((child, int(created)))
    return found


def _ancestors(pid: int, identity: str) -> list[tuple[int, str]]:
    """The running processes this one was started under -- its launchers --
    nearest first, at most :data:`MAX_ANCESTORS`, each verified by creation
    time (a parent is never younger than its child). The walk stops at a
    process that is watching for its own stop requests, at one whose times
    cannot be read, and at a parent link that a reused PID broke."""
    parents = _parents()
    chain: list[tuple[int, str]] = []
    child, born = pid, int(identity)
    seen = {pid}
    while len(chain) < MAX_ANCESTORS:
        parent = parents.get(child)
        if parent is None or parent in seen or parent <= 0:
            break
        seen.add(parent)
        try:
            created = _identity(parent)
        except OSError:
            break
        if created is None or watch_path(parent, created).is_file():
            break
        chain.append((parent, created))
        child, born = parent, int(created)
    return chain


def _write_stop(path: Path, text: str | None = None) -> None:
    """The one writer of this module: a stop file or a watch marker, in
    the cache."""
    fsops.ensure_private_parent(path.parent)
    fsops.private_write(path, text if text is not None else chrono.now_iso() + "\n")


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
    written). A watching process in the tree under *pid* gets its own stop
    file; when none is watching yet, one file addressed to *pid* waits for
    the first command under it to start watching, which honours it and
    removes it. Windows only: on Linux these verbs stop on SIGTERM, and this
    raises :class:`NotImplementedError`."""
    if os.name != "nt":
        raise NotImplementedError("on this platform these commands stop on SIGTERM")
    identity = _identity(int(pid))
    if identity is None:
        return False
    watching = [(p, i) for p, i in _tree(int(pid), identity) if watch_path(p, i).is_file()]
    for p, i in watching or [(int(pid), identity)]:
        _write_stop(stop_path(p, i))
    return True


def _requested(path: Path) -> bool:
    try:
        return path.is_file() and not fsops.is_link(path) and fsops.owned_by_current_user(path)
    except OSError:
        return False


def _drop_stale(folder: Path) -> None:
    """Remove every stop file and watch marker in *folder* (already checked
    private, never a link) named for a process that no longer runs under
    that creation time: it was meant for a process that has exited."""
    try:
        with os.scandir(folder) as found:
            names_ = [entry.name for entry in found]
    except OSError:
        return
    for name in names_:
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


def _get_break() -> Any:
    if sys.platform != "win32":
        raise NotImplementedError("SIGBREAK exists on Windows only")
    return signal.getsignal(signal.SIGBREAK)


def _raise_break() -> None:
    """Run the ``SIGBREAK`` handler in the main thread. Windows only."""
    if sys.platform != "win32":
        raise NotImplementedError("SIGBREAK exists on Windows only")
    import _thread

    _thread.interrupt_main(signal.SIGBREAK)


def _swallow(signum: int, frame: Any) -> None:  # noqa: ARG001 -- signal handler signature
    """Installed while a watch closes: a stop that was already on its way
    when the watch ended is dropped, never raised in the caller's cleanup."""


_UNSET = object()


class _Watch:
    """One watch. Constructing it has no side effect; :meth:`start` makes
    them in an order :meth:`close` can always undo, so a stop that arrives
    while either runs (as a raised handler) never leaves the ``SIGBREAK``
    handler installed or a file behind."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.marker: Path | None = None
        self.addressed: list[Path] = []
        self._previous: Any = _UNSET
        self._closed = False
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, handler: Callable[..., Any]) -> None:
        pid = os.getpid()
        identity = _identity(pid)
        if identity is None:  # this process is running; belt only
            raise OSError(f"cannot read this process's creation time (pid {pid})")
        folder = stop_dir()
        pass  # MUTATION: folder not checked first
        self.path = stop_path(pid, identity)
        self.marker = watch_path(pid, identity)
        ancestors = []  # MUTATION
        self.addressed = [self.path, *(stop_path(p, i) for p, i in ancestors)]
        _drop_stale(folder)
        _write_stop(self.marker, json.dumps(
            {"pid": pid, "creation": identity, "ancestors": [list(a) for a in ancestors]}) + "\n")
        self._previous = _get_break()
        _set_break(handler)
        self._thread = threading.Thread(target=self._poll, name="self-learn-stop-request",
                                        daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        while True:
            if any(_requested(path) for path in self.addressed):
                with self._lock:
                    if not self._closed:
                        self._closed = True
                        _raise_break()
                return
            if self._done.wait(POLL_SECS):
                return

    def close(self) -> None:
        try:
            if self._previous is not _UNSET:
                _set_break(_swallow)
            with self._lock:
                self._closed = True
            self._done.set()
            if self._thread is not None:
                self._thread.join(POLL_SECS * 10)
        except Exception:
            raise
        if True:
            try:
                if self._previous is not _UNSET:
                    _set_break(self._previous)
                    self._previous = _UNSET
            finally:
                for path in (*self.addressed, self.marker):
                    if path is not None:
                        _drop_stop(path)


_active: list[_Watch] = []


def watch(handler: Callable[..., Any]) -> None:
    """Honour a stop request (and a console Ctrl+Break) by running
    *handler* in the main thread, until :func:`unwatch`. Windows only, main
    thread only. The watch is registered before it starts, so
    :func:`unwatch` undoes a start that a stop interrupted."""
    unwatch()
    current = _Watch()
    current.start(handler)
    _active.append(current)


def unwatch() -> None:
    """End :func:`watch`: the poller stops, the previous ``SIGBREAK``
    handler is back, and this process's stop file, marker and the requests
    addressed to its launchers are gone. A stop that was on its way is
    dropped. Idempotent."""
    while _active:
        current = _active[-1]
        try:
            current.close()
        finally:
            _active.pop()
