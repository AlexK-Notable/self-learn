"""Temporary environment probe for the w6-procs lane (removed before the lane ends)."""

import os
import subprocess
import sys
import sysconfig
import time
from uuid import uuid4

import win32api
import win32con
import win32job


def report(*args):
    print("PROBE", *args, flush=True)


def new_job(flags):
    job = win32job.CreateJobObject(None, uuid4().hex)
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= flags
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


ALL = (win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE
       | win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE)
base = sys._base_executable
KILL = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
BREAK = win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK

# The helper puts itself in S (kill-on-close, breakaway OK), then spawns a breakaway child
# that reports its own immediate job flags.
HELPER = r"""
import site, subprocess, sys
site.addsitedir(sys.argv[1])
from uuid import uuid4
import win32api, win32job
job = win32job.CreateJobObject(None, uuid4().hex)
info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
child = r'''
import site, sys
site.addsitedir(sys.argv[1])
import win32api, win32job
try:
    f = hex(win32job.QueryInformationJobObject(None, win32job.JobObjectExtendedLimitInformation)["BasicLimitInformation"]["LimitFlags"])
except Exception as e:
    f = "noflags:" + repr(e)
print(win32job.IsProcessInJob(win32api.GetCurrentProcess(), None), f, flush=True)
'''
try:
    out = subprocess.run([sys.executable, "-c", child, sys.argv[1]], creationflags=0x01000000, capture_output=True, text=True, timeout=20)
    print("BREAKAWAY", out.stdout.strip(), out.stderr.strip()[-200:], flush=True)
except OSError as e:
    print("BREAKAWAY_ERR", getattr(e, "winerror", None), e, flush=True)
"""

for label, flags in (("runner_only", None), ("parent_forbids", KILL), ("parent_allows", KILL | BREAK)):
    env = dict(os.environ)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])  # warm
    p.wait()
    parent = new_job(flags) if flags is not None else None
    h = subprocess.Popen([base, "-c", HELPER, sysconfig.get_paths()["purelib"]], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    if parent is not None:
        hh = win32api.OpenProcess(ALL, False, h.pid)
        win32job.AssignProcessToJobObject(parent, hh)
    out, _ = h.communicate(timeout=60)
    report(label, out.strip().replace("\n", " | "))

# Timing of the early race with a venv-launcher child (two hops before the grandchild).
CHILD = r"""
import subprocess, sys, time
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
print(g.pid, flush=True)
time.sleep(30)
"""
for trial in range(3):
    p = subprocess.Popen([base, "-c", CHILD], stdout=subprocess.PIPE, text=True)
    t1 = time.perf_counter()
    g = int(p.stdout.readline())
    t2 = time.perf_counter()
    report("standin_grandchild_after_popen_ms", round((t2 - t1) * 1e3, 1))
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    p.wait()
