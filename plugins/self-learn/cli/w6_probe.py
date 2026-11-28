"""Temporary environment probe for the w6-procs lane (removed before the lane ends)."""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from uuid import uuid4

import pywintypes
import win32api
import win32con
import win32event
import win32job
import win32process


def report(*args):
    print("PROBE", *args, flush=True)


def flags_of(job):
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    return hex(info["BasicLimitInformation"]["LimitFlags"])


def try_(label, fn):
    try:
        report(label, "ok", fn())
    except Exception as exc:  # noqa: BLE001
        report(label, "ERR", type(exc).__name__, getattr(exc, "winerror", None), exc)


def new_job(flags):
    job = win32job.CreateJobObject(None, uuid4().hex)
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= flags
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


me = win32api.GetCurrentProcess()
report("executable", sys.executable, "base", getattr(sys, "_base_executable", None))
report("pid", os.getpid(), "ppid", os.getppid())
try_("in_job_self", lambda: win32job.IsProcessInJob(me, None))
try_("own_job_flags", lambda: flags_of(None))
try_("unnamed_job", lambda: win32job.CreateJobObject(None, ""))
try_("times_type", lambda: repr(win32process.GetProcessTimes(me)))

base = getattr(sys, "_base_executable", sys.executable)
CHILD = r"""
import subprocess, sys, time
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
print(g.pid, flush=True)
time.sleep(30)
"""
for exe_label, exe in (("venv", sys.executable), ("base", base)):
    p = subprocess.Popen([exe, "-c", "import os,time; print(os.getpid(), flush=True); time.sleep(5)"],
                         stdout=subprocess.PIPE, text=True)
    report(exe_label, "popen_pid", p.pid, "reported", p.stdout.readline().strip())
    p.kill(); p.wait()

# Race measurement: child spawns a grandchild immediately; assign as soon as Popen returns.
PROCESS_ALL = win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE | win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE
for trial in range(5):
    t0 = time.perf_counter()
    p = subprocess.Popen([base, "-c", CHILD], stdout=subprocess.PIPE, text=True)
    t1 = time.perf_counter()
    h = win32api.OpenProcess(PROCESS_ALL, False, p.pid)
    job = new_job(win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
    try:
        win32job.AssignProcessToJobObject(job, h)
        t2 = time.perf_counter()
        g = int(p.stdout.readline())
        t3 = time.perf_counter()
        gh = win32api.OpenProcess(PROCESS_ALL, False, g)
        ct = win32process.GetProcessTimes(h)["CreationTime"]
        gt = win32process.GetProcessTimes(gh)["CreationTime"]
        report("race", trial, "popen_ms", round((t1 - t0) * 1e3, 2), "assign_after_popen_ms",
               round((t2 - t1) * 1e3, 3), "grandchild_seen_ms", round((t3 - t1) * 1e3, 1),
               "grandchild_in_job", win32job.IsProcessInJob(gh, job), "gc_minus_child", gt - ct)
    except Exception as exc:  # noqa: BLE001
        report("race", trial, "ERR", getattr(exc, "winerror", None), exc)
    finally:
        win32job.TerminateJobObject(job, 1)
        p.kill(); p.wait()

# Nesting: child already in a job with UI limits, then nested assign.
for label, setup in (
    ("plain", lambda j: None),
    ("ui_limits", lambda j: win32job.SetInformationJobObject(j, win32job.JobObjectBasicUIRestrictions,
                                                             {"UIRestrictionsClass": win32job.JOB_OBJECT_UILIMIT_HANDLES})),
    ("silent_breakaway", lambda j: win32job.SetInformationJobObject(j, win32job.JobObjectExtendedLimitInformation, {**win32job.QueryInformationJobObject(j, win32job.JobObjectExtendedLimitInformation), "BasicLimitInformation": {**win32job.QueryInformationJobObject(j, win32job.JobObjectExtendedLimitInformation)["BasicLimitInformation"], "LimitFlags": win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE}})),
):
    p = subprocess.Popen([base, "-c", "import time; time.sleep(10)"])
    h = win32api.OpenProcess(PROCESS_ALL, False, p.pid)
    outer = new_job(win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    try:
        try_("nest_setup_" + label, lambda: setup(outer))
        win32job.AssignProcessToJobObject(outer, h)
        inner = new_job(win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        try_("nest_assign_" + label, lambda: win32job.AssignProcessToJobObject(inner, h))
    finally:
        win32job.TerminateJobObject(outer, 1)
        p.wait()

# Breakaway from our own job on the runner: does CREATE_BREAKAWAY_FROM_JOB work when nested?
job = new_job(win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
try_("self_assign", lambda: win32job.AssignProcessToJobObject(job, me))
try_("self_assign_again", lambda: win32job.AssignProcessToJobObject(job, me))
try_("in_job_after", lambda: win32job.IsProcessInJob(me, job))
try_("own_job_flags_after", lambda: flags_of(None))
CREATE_BREAKAWAY = 0x01000000
for flags_label, flags in (("plain", 0), ("breakaway", CREATE_BREAKAWAY)):
    def spawn():
        p = subprocess.Popen([base, "-c", "import time; time.sleep(3)"], creationflags=flags)
        h = win32api.OpenProcess(PROCESS_ALL, False, p.pid)
        r = (win32job.IsProcessInJob(h, job), win32job.IsProcessInJob(h, None))
        p.kill(); p.wait()
        return r
    try_("spawn_" + flags_label, spawn)

# Toolhelp via ctypes.
TH32CS_SNAPPROCESS = 2
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
entry = PROCESSENTRY32W(); entry.dwSize = ctypes.sizeof(entry)
ok = k32.Process32FirstW(snap, ctypes.byref(entry)); n = 0
while ok:
    n += 1
    if entry.th32ProcessID == os.getpid():
        report("toolhelp_self_parent", entry.th32ParentProcessID, entry.szExeFile)
    ok = k32.Process32NextW(snap, ctypes.byref(entry))
k32.CloseHandle(snap)
report("toolhelp_count", n)

buf = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(buf))
k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
hq = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, os.getpid())
report("image", k32.QueryFullProcessImageNameW(int(hq), 0, buf, ctypes.byref(size)), buf.value)
try_("open_missing", lambda: win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, 0x7FFFFFF0))
try_("open_system", lambda: win32api.OpenProcess(PROCESS_ALL, False, 4))
try_("open_system_query", lambda: win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, 4))
