"""Parity plan 6C: cancelling `ask` and `summarise`, and the Linux-only
probes, on Windows.

- On Windows a running `ask` or `summarise` stops cleanly on
  `stop_request.request_stop(pid)` (a stop file named by PID and creation
  time, polled by the running command) and on Ctrl+Break (`SIGBREAK`), and
  leaves no stop file; a stop file named for its PID under another
  creation time is stale and ignored.
- On Windows `systemd-show`, `package` and `git-file` probes are
  `unavailable` (cause `platform`) before any command runs, never counted
  as broken, and the mount table is never read.
- On Windows `ask` never offers the model its `probe` tool; on Linux the
  tool schema and the doctrine are byte-identical to master `729f58ed`.

Every model session is a scripted stand-in on `ask._backend`; no test
crosses the real model boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import ask, attention, premise_sweep, premises, settings, stop_request, summarise
from self_learn.invocation import Outcome
from support import days_ago, git, make_home

windows = pytest.mark.skipif(os.name != "nt", reason="native Windows cancel contract")
linux = pytest.mark.skipif(os.name == "nt", reason="Linux cancel contract")

BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX")
REPORT = "# Overseer report — 2026-10-25\n\n## Examined\n- nothing\n"
TARGET = "overseer-report:2026-10-25"
#: Measured on master `729f58ed` (Linux): the ask agent's tool schema and
#: its doctrine, as `_schema_digest` and `sha256(ASK_DOCTRINE)` read them.
LINUX_SCHEMA_SHA256 = "614f375f1f77ca304340cc8209376343c8e950abcef5d9ef65afa2e5e3861c62"
LINUX_DOCTRINE_SHA256 = "b95161400309522d9d59aa1f9c233e123b562474f2a1cd771bd53807201a72a3"


@pytest.fixture(autouse=True)
def person(tmp_path, monkeypatch):
    for marker in settings.AGENT_CALLER_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    for var in (*BILLING_VARS, "SELF_LEARN_PROVIDER", "SELF_LEARN_ASK_MODEL",
                "SELF_LEARN_SUMMARY_MODEL", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    person_home = tmp_path / "person-home"
    (person_home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(person_home))
    monkeypatch.setenv("USERPROFILE", str(person_home))
    monkeypatch.setattr(attention, "_systemctl_active", lambda unit: True)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(h))
    (h / "overseer").mkdir(exist_ok=True)
    (h / "overseer" / "2026-10-25-report.md").write_text(REPORT, encoding="utf-8")
    git(h, "add", "--", "overseer/2026-10-25-report.md")
    git(h, "commit", "-q", "-m", "a weekly report")
    return h


@pytest.fixture()
def item(home):
    """A `hold.credentials` inbox item (the steward held on a login failure)."""
    at = days_ago(1)
    journal = attention.cache_dir(home) / "steward" / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({"ts": at, "status": "held-environment",
                                   "cause": "Failed to authenticate: OAuth session expired"})
                       + "\n", encoding="utf-8")
    item_id = attention.item_id("hold.credentials", f"credentials@{at}")
    assert attention.find(home, item_id) is not None
    return item_id


class _Blocks:
    """A model session that blocks the way the real seam does: an asyncio
    loop on the calling (main) thread (`invocation_sdk.backend.run_sync`).
    *during* runs first, in the main thread."""

    def __init__(self, seconds: float = 30.0, during=None, outcome: Outcome | None = None):
        self.seconds = seconds
        self.during = during
        self.outcome = outcome or Outcome(ok=True, rc=0, stdout="late answer", detail="",
                                          failure=None)
        self.specs: list = []
        self.unwound = False

    def write_session(self, spec):
        self.specs.append(spec)
        try:
            if self.during is not None:
                self.during()
            asyncio.run(asyncio.sleep(self.seconds))
        finally:
            self.unwound = True
        return self.outcome

    text_session = write_session


def _request_from_another_thread(before=None):
    """What the page does on Windows: (optionally) its own marker, then a
    stop request for this process, from a thread that is not the verb's."""
    def go():
        time.sleep(0.3)
        if before is not None:
            before()
        assert stop_request.request_stop(os.getpid()) is True

    def during():
        threading.Thread(target=go, daemon=True).start()
    return during


def _stop_files() -> list[str]:
    folder = stop_request.stop_dir()
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def _events(out: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


def _schema_digest(toolset) -> str:
    shape = [{"name": t.name, "description": t.description, "input_schema": t.input_schema,
              "read_only": t.read_only} for t in toolset.tools]
    blob = json.dumps({"server": toolset.server, "tools": shape,
                       "allowed": ask.allowed_tools(toolset)},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _toolset(tmp_path):
    return ask.build_toolset(tmp_path, {"id": "att-0"}, roots=(), denied=(), cwd=tmp_path)


# ------------------------------------------------------------ both platforms


def test_stop_files_are_named_by_pid_and_creation_under_the_runtime_root(monkeypatch, tmp_path):
    from self_learn.primitives import names

    assert stop_request.stop_dir() == names.cache_root() / "stop-requests"
    assert stop_request.stop_path(12, "34") == names.cache_root() / "stop-requests" / "12-34.stop"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    assert stop_request.stop_dir() == tmp_path / "run" / "self-learn" / "stop-requests"


# ------------------------------------------------------------------ Windows


@windows
def test_windows_ask_stops_on_request_stop_and_leaves_no_stop_file(monkeypatch, home, item):
    before = signal.getsignal(signal.SIGBREAK)
    backend = _Blocks(during=_request_from_another_thread(lambda: ask.request_stop(home, item)))
    monkeypatch.setattr(ask, "_backend", backend)
    out = io.StringIO()
    started = time.monotonic()
    code, _ = ask.run_ask(home, item, "Stop me", stream=True, out=out, err=io.StringIO())
    assert time.monotonic() - started < 20
    assert code == ask.EXIT_INTERRUPTED
    assert backend.unwound
    assert _events(out)[-1]["code"] == "interrupted"
    assert ask.workspace.rows(home, item)[-1]["text"] == ask.STOPPED_NOTE
    assert _stop_files() == []
    assert stop_request._active == []  # noqa: SLF001
    assert signal.getsignal(signal.SIGBREAK) is before
    spec = backend.specs[0]
    assert spec.doctrine == ask.windows_doctrine() and "probe" not in spec.doctrine
    assert "probe" not in [t.name for t in spec.mcp_toolset.tools]


@windows
def test_windows_summarise_stops_on_request_stop_and_leaves_no_stop_file(monkeypatch, home):
    before = signal.getsignal(signal.SIGBREAK)
    backend = _Blocks(during=_request_from_another_thread())
    monkeypatch.setattr(ask, "_backend", backend)
    out = io.StringIO()
    started = time.monotonic()
    code, _ = summarise.run_summarise(home, TARGET, stream=True, out=out, err=io.StringIO())
    assert time.monotonic() - started < 20
    assert code == summarise.EXIT_INTERRUPTED
    assert backend.unwound
    assert _events(out)[-1]["code"] == "interrupted"
    journal = summarise._cache(home) / "journal.jsonl"  # noqa: SLF001
    assert json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])["outcome"] == "stopped"
    assert _stop_files() == []
    assert signal.getsignal(signal.SIGBREAK) is before


@windows
def test_windows_ctrl_break_stops_summarise(monkeypatch, home):
    # A stand-in outer handler: had the verb not installed its own, the
    # default action would end pytest itself; this one only records.
    reached: list[int] = []
    sentinel = lambda signum, frame: reached.append(signum)  # noqa: E731
    previous = signal.signal(signal.SIGBREAK, sentinel)
    try:
        backend = _Blocks(seconds=3, during=lambda: signal.raise_signal(signal.SIGBREAK))
        monkeypatch.setattr(ask, "_backend", backend)
        code, _ = summarise.run_summarise(home, TARGET, stream=True, out=io.StringIO(),
                                          err=io.StringIO())
        assert signal.getsignal(signal.SIGBREAK) is sentinel
    finally:
        signal.signal(signal.SIGBREAK, previous)
    assert reached == []
    assert code == summarise.EXIT_INTERRUPTED
    assert _stop_files() == []


@windows
def test_windows_stale_stop_file_is_ignored_and_cleared(monkeypatch, home):
    stale = stop_request.stop_path(os.getpid(), "1")
    gone = stop_request.stop_dir() / "4294967294-1.stop"
    parent = os.getppid()
    other = stop_request.stop_path(parent, stop_request._identity(parent))  # noqa: SLF001
    for path in (stale, gone, other):
        stop_request._write_stop(path)  # noqa: SLF001
    failed = Outcome(ok=False, rc=1, stdout="", detail="scripted failure", failure="exit")
    backend = _Blocks(seconds=1.5, outcome=failed)  # several polls
    monkeypatch.setattr(ask, "_backend", backend)
    out = io.StringIO()
    code, _ = summarise.run_summarise(home, TARGET, stream=True, out=out, err=io.StringIO())
    assert code == summarise.EXIT_FAILED  # the turn ran to its own end
    assert _events(out)[-1]["code"] == "failed"
    assert not stale.exists() and not gone.exists()
    assert other.exists()  # a running process's request is not this process's to clear
    stop_request._drop_stop(other)  # noqa: SLF001
    assert _stop_files() == []


@windows
def test_windows_request_before_the_watch_is_honoured(monkeypatch, home):
    assert stop_request.request_stop(os.getpid()) is True  # no marker yet: still written
    backend = _Blocks()
    monkeypatch.setattr(ask, "_backend", backend)
    started = time.monotonic()
    code, _ = summarise.run_summarise(home, TARGET, stream=True, out=io.StringIO(),
                                      err=io.StringIO())
    assert time.monotonic() - started < 20
    assert code == summarise.EXIT_INTERRUPTED
    assert _stop_files() == []


@windows
def test_windows_request_stop_reaches_another_process(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent("""\
        import asyncio, sys
        from self_learn import stop_request

        class Stop(BaseException):
            pass

        def handler(signum, frame):
            raise Stop()

        stop_request.watch(handler)
        print("ready", flush=True)
        try:
            asyncio.run(asyncio.sleep(30))
        except Stop:
            stop_request.unwatch()
            sys.exit(7)
        sys.exit(1)
        """), encoding="utf-8")
    child = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "ready"
        # `child.pid` is the virtual environment's launcher; the watching
        # interpreter is its child, as under a console script.
        assert stop_request.request_stop(child.pid) is True
        assert child.wait(timeout=20) == 7
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    assert _stop_files() == []
    assert stop_request.request_stop(child.pid) is False  # exited: nothing is written
    assert _stop_files() == []


_LINUX_ONLY_PROBES = [
    {"kind": "systemd-show", "scope": "user", "unit": "foo.service", "property": "ActiveState"},
    {"kind": "package", "name": "git"},
    {"kind": "git-file", "repo": "~/repo", "path": "README.md", "contains": "x"},
]


def _no_runner(calls):
    def runner(argv, env, timeout):
        calls.append(argv)
        raise AssertionError("a Linux-only probe ran a command on Windows")
    return runner


@windows
@pytest.mark.parametrize("probe", _LINUX_ONLY_PROBES, ids=lambda p: p["kind"])
def test_windows_linux_only_probe_is_unavailable_and_runs_nothing(probe, tmp_path):
    calls: list = []
    env = premises.ProbeEnv(home=tmp_path, runner=_no_runner(calls))
    obs = premises.run_probe(probe, env)
    assert obs.state == premises.OBS_UNAVAILABLE
    assert obs.cause == premises.CAUSE_PLATFORM
    assert obs.reason.startswith("unavailable on Windows: ")
    assert calls == []


def _rows_of_platform(premise):
    sig = premise_sweep._premise_sig(premise)  # noqa: SLF001
    obs = premises.unavailable_observation("unavailable on Windows: x",
                                           cause=premises.CAUSE_PLATFORM)
    return [premise_sweep._row(f"2026-11-2{n}T00:00:00Z", "lrn-00000001", "p1", "probe", obs,  # noqa: SLF001
                               sig=sig) for n in range(3)]


@windows
def test_windows_platform_unavailable_rows_are_never_broken():
    premise = {"id": "p1", "claim": "x", "probe": _LINUX_ONLY_PROBES[0]}
    rows = _rows_of_platform(premise)
    assert all(r["state"] == premises.OBS_UNAVAILABLE for r in rows)
    assert premise_sweep.broken_tail(premise, rows) is None
    record = SimpleNamespace(id="lrn-00000001", premises=[premise, {"id": "p2", "probe": None}])
    shown = premise_sweep._platform_rows([(None, record)])  # noqa: SLF001
    assert [(r.verdict, r.name) for r in shown] == [("INFO", "platform-unavailable")]
    assert "1 probe(s) cannot run on Windows (systemd-show)" in shown[0].detail


@windows
def test_windows_mount_table_reads_no_linux_path(monkeypatch):
    read: list[str] = []
    monkeypatch.setattr(premises, "_read_text", lambda path: read.append(path) or "")
    table = premises.read_mount_table()
    assert read == []
    assert (table.readable, dict(table.current), table.declared) == (False, {}, frozenset())


@windows
def test_windows_ask_schema_omits_probe_and_keeps_every_other_tool(tmp_path):
    tools, toolset = _toolset(tmp_path)
    linux_rows = [row for row in ask.AskTools._TOOLS if row[0] != "probe"]  # noqa: SLF001
    assert [(t.name, t.description, t.input_schema) for t in toolset.tools] == [
        (name, description, schema) for name, description, schema, _attr in linux_rows]
    assert "mcp__selflearn_ask__probe" not in ask.allowed_tools(toolset)
    with pytest.raises(ask._Refused, match="not available on Windows"):  # noqa: SLF001
        tools.probe({"command": "systemctl show", "target": "foo.service"})
    doctrine = ask.windows_doctrine()
    assert "probe" not in doctrine
    assert doctrine.replace("list_dir, settings_hooks)", "list_dir, probe, settings_hooks)") != doctrine


# -------------------------------------------------------------------- Linux


@linux
def test_linux_ask_schema_and_doctrine_are_byte_identical(tmp_path):
    _tools, toolset = _toolset(tmp_path)
    assert _schema_digest(toolset) == LINUX_SCHEMA_SHA256
    assert "probe" in [t.name for t in toolset.tools]
    assert hashlib.sha256(ask.ASK_DOCTRINE.encode()).hexdigest() == LINUX_DOCTRINE_SHA256


@linux
def test_linux_never_watches_for_a_stop_file(monkeypatch, home):
    calls: list[str] = []
    monkeypatch.setattr(stop_request, "watch", lambda handler: calls.append("watch"))
    monkeypatch.setattr(stop_request, "unwatch", lambda: calls.append("unwatch"))
    failed = Outcome(ok=False, rc=1, stdout="", detail="scripted failure", failure="exit")
    monkeypatch.setattr(ask, "_backend", _Blocks(seconds=0, outcome=failed))
    code, _ = summarise.run_summarise(home, TARGET, stream=True, out=io.StringIO(),
                                      err=io.StringIO())
    assert code == summarise.EXIT_FAILED
    assert calls == []
    with pytest.raises(NotImplementedError):
        stop_request.request_stop(os.getpid())


@linux
def test_linux_systemd_probe_still_runs_and_platform_rows_still_count():
    calls: list = []

    def runner(argv, env, timeout):
        calls.append(argv)
        return premises.CommandResult(0, b"active\n" if "ActiveState" in argv else b"loaded\n", b"")

    obs = premises.run_probe(_LINUX_ONLY_PROBES[0], premises.ProbeEnv(runner=runner))
    assert obs.state == premises.OBS_OK and len(calls) == 2
    premise = {"id": "p1", "claim": "x", "probe": _LINUX_ONLY_PROBES[0]}
    assert premise_sweep.broken_tail(premise, _rows_of_platform(premise)) is not None
    assert not premises.read_mount_table("/nonexistent/mountinfo").readable
