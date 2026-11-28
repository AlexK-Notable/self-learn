"""Temporary observer for the original KL4 assertion on the CI runner."""
import asyncio
import ctypes
import os
import platform
import signal
import sys
import threading
from pathlib import Path

import pytest


def chain(pid):
    rows = []
    while pid:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except FileNotFoundError:
            rows.append((pid, "absent"))
            break
        comm, fields = stat.rsplit(")", 1)
        state, parent, pgid = fields.split()[:3]
        rows.append((comm + ")", state, parent, pgid, fields.split()[19]))
        pid = int(parent)
    return rows


@pytest.fixture(autouse=True)
def trace_kl4(request, monkeypatch):
    if not request.node.name.startswith("test_kl4_hang"):
        return
    trace = []
    subreaper = ctypes.c_int()
    rc = ctypes.CDLL(None).prctl(37, ctypes.byref(subreaper), 0, 0, 0)
    trace.append(("environment", sys.version, platform.release(), "subreaper", rc, subreaper.value))
    real_kill = os.kill
    real_waitpid = os.waitpid
    original = request.module._child_gone

    def kill(pid, sig):
        result = real_kill(pid, sig)
        if sig == signal.SIGKILL:
            trace.append(("sent SIGKILL", pid))
        return result

    def waitpid(pid, flags):
        result = real_waitpid(pid, flags)
        if result[0] > 0:
            trace.append(("waitpid", result, threading.current_thread().name))
        return result

    def child_gone(pid, ticks, deadline):
        trace.append(("at return", chain(pid), "pytest", os.getpid()))
        result = original(pid, ticks, deadline)
        trace.append(("after poll", result, chain(pid)))
        try:
            status = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            status = "ECHILD"
        trace.append(("waitid WNOWAIT", status))
        Path(os.environ["TRACE_FILE"]).write_text("\n".join(map(str, trace)) + "\n")
        return result

    import asyncio.unix_events as unix
    for name in ("_PidfdChildWatcher", "_ThreadedChildWatcher", "PidfdChildWatcher", "ThreadedChildWatcher"):
        cls = getattr(unix, name, None)
        if cls is not None and "add_child_handler" in vars(cls):
            def register(self, pid, *args, original=cls.add_child_handler):
                trace.append(("watcher", type(self).__name__, pid))
                return original(self, pid, *args)
            monkeypatch.setattr(cls, "add_child_handler", register)
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(os, "waitpid", waitpid)
    monkeypatch.setattr(request.module, "_child_gone", child_gone)
