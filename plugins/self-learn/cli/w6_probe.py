"""Temporary environment probe for the w6-procs fix round (removed before the round ends)."""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

import win32api
import win32con
import win32process

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
nt = ctypes.WinDLL("ntdll")


def report(*args):
    print("PROBE", *args, flush=True)


class FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


def ft(f):
    return (f.hi << 32) | f.lo


def precise():
    f = FT()
    k32.GetSystemTimePreciseAsFileTime(ctypes.byref(f))
    return ft(f)


def coarse():
    f = FT()
    k32.GetSystemTimeAsFileTime(ctypes.byref(f))
    return ft(f)


def created(handle):
    c, e, k, u = FT(), FT(), FT(), FT()
    assert k32.GetProcessTimes(int(handle), ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    return ft(c)


class PBI(ctypes.Structure):
    _fields_ = [("ExitStatus", ctypes.c_long), ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_size_t), ("BasePriority", ctypes.c_long),
                ("UniqueProcessId", ctypes.c_size_t), ("InheritedFromUniqueProcessId", ctypes.c_size_t)]


base = sys._base_executable
rows = []
for i in range(12):
    p0, c0 = precise(), coarse()
    p = subprocess.Popen([base, "-c", "import time; time.sleep(3)"])
    p1, c1 = precise(), coarse()
    h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, p.pid)
    cr = created(h)
    pyw = win32process.GetProcessTimes(h)["CreationTime"]
    pbi = PBI()
    ret = wintypes.ULONG()
    st = nt.NtQueryInformationProcess(int(h), 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(ret))
    rows.append((cr - p0, p1 - cr, cr - c0, c1 - cr, cr % 10000, st, pbi.InheritedFromUniqueProcessId == os.getpid(),
                 pbi.UniqueProcessId == p.pid, pyw.microsecond))
    p.kill(); p.wait()
    time.sleep(0.003)
report("sizeof PBI", ctypes.sizeof(PBI))
for r in rows:
    report("created-precise0", r[0], "precise1-created", r[1], "created-coarse0", r[2], "coarse1-created", r[3],
           "sub-ms", r[4], "ntstatus", r[5], "ppid_ok", r[6], "pid_ok", r[7], "pywin32_us", r[8])
# coarse clock granularity
vals = set()
t = time.perf_counter()
while time.perf_counter() - t < 0.1:
    vals.add(coarse())
v = sorted(vals)
report("coarse steps", [b - a for a, b in zip(v, v[1:])][:10])
