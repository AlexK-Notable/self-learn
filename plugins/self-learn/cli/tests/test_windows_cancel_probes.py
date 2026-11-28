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
    # A live process that is not above this one: a request for a launcher
    # of this process would be this process's to honour.
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        other = stop_request.stop_path(sleeper.pid, stop_request._identity(sleeper.pid))  # noqa: SLF001
        for path in (stale, gone, other):
            stop_request._write_stop(path)  # noqa: SLF001
        failed = Outcome(ok=False, rc=1, stdout="", detail="scripted failure", failure="exit")
        backend = _Blocks(seconds=1.5, outcome=failed)  # several polls
        monkeypatch.setattr(ask, "_backend", backend)
        out = io.StringIO()
        code, _ = summarise.run_summarise(home, TARGET, stream=True, out=out, err=io.StringIO())
        still_there = other.exists()
    finally:
        sleeper.kill()
        sleeper.wait(timeout=10)
    assert code == summarise.EXIT_FAILED  # the turn ran to its own end
    assert _events(out)[-1]["code"] == "failed"
    assert not stale.exists() and not gone.exists()
    assert still_there  # a running process's request is not this process's to clear
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


@windows
def test_windows_ask_honours_a_request_made_before_the_watch(monkeypatch, home, item):
    """Gate MAJOR 1: a stop already waiting when the watch starts is caught
    by the turn (exit 7, an `interrupted` event, a sealed note), never
    raised out of it. The note is "stopped before it answered": a turn
    drops a Stop marker left from before it began (unchanged Linux code),
    so only a marker written during the turn reads as "stopped by you"."""
    before = signal.getsignal(signal.SIGBREAK)
    assert stop_request.request_stop(os.getpid()) is True  # nobody watching yet
    backend = _Blocks()
    monkeypatch.setattr(ask, "_backend", backend)
    out = io.StringIO()
    started = time.monotonic()
    code, _ = ask.run_ask(home, item, "Stop me", stream=True, out=out, err=io.StringIO())
    assert time.monotonic() - started < 20
    assert code == ask.EXIT_INTERRUPTED
    assert _events(out)[-1]["code"] == "interrupted"
    assert ask.workspace.rows(home, item)[-1]["text"] == ask.INTERRUPTED_NOTE
    assert _stop_files() == []
    assert signal.getsignal(signal.SIGBREAK) is before


def _run_ask_catching(home, item, out) -> int | str:
    """`ask.run_ask` with a recording `SIGBREAK` handler outside it (had
    the verb installed none, the default action would end pytest), and a
    stop that escapes the verb turned into a failed assertion rather than
    the end of the test session."""
    previous = signal.signal(signal.SIGBREAK, lambda signum, frame: None)
    try:
        code, _ = ask.run_ask(home, item, "Stop me", stream=True, out=out, err=io.StringIO())
    except BaseException as exc:  # noqa: BLE001 -- a stop raised out of the verb
        return f"escaped: {exc!r}"
    finally:
        stop_request.unwatch()
        signal.signal(signal.SIGBREAK, previous)
    return code


@windows
def test_windows_ask_catches_a_stop_delivered_while_the_watch_starts(monkeypatch, home, item):
    """Gate MAJOR 1, made deterministic: the stop is delivered inside
    `watch()` itself (a waiting request or a Ctrl+Break landing as the
    watch begins), so only a watch started inside the turn's `try` is
    caught as a stop."""
    before = signal.getsignal(signal.SIGBREAK)
    real = stop_request.watch

    def watch(handler):
        real(handler)
        signal.raise_signal(signal.SIGBREAK)

    monkeypatch.setattr(stop_request, "watch", watch)
    monkeypatch.setattr(ask, "_backend", _Blocks())
    out = io.StringIO()
    code = _run_ask_catching(home, item, out)
    assert code == ask.EXIT_INTERRUPTED
    assert _events(out)[-1]["code"] == "interrupted"
    assert ask.workspace.rows(home, item)[-1]["text"] == ask.INTERRUPTED_NOTE
    assert stop_request._active == []  # noqa: SLF001
    assert _stop_files() == []
    assert signal.getsignal(signal.SIGBREAK) is before


@windows
def test_windows_ask_catches_a_stop_racing_the_end_of_the_turn(monkeypatch, home, item):
    """Gate MAJOR 1: a stop delivered as the finished turn ends its watch
    is caught as a stop, never raised out of the cleanup."""
    before = signal.getsignal(signal.SIGBREAK)
    real = stop_request.unwatch
    fired: list[int] = []

    def unwatch():
        if not fired:
            fired.append(1)
            signal.raise_signal(signal.SIGBREAK)
        real()

    monkeypatch.setattr(stop_request, "unwatch", unwatch)
    monkeypatch.setattr(ask, "_backend", _Blocks(seconds=0))
    out = io.StringIO()
    code = _run_ask_catching(home, item, out)
    assert fired == [1]
    assert code == ask.EXIT_INTERRUPTED
    assert _events(out)[-1]["code"] == "interrupted"
    assert stop_request._active == []  # noqa: SLF001
    assert _stop_files() == []
    assert signal.getsignal(signal.SIGBREAK) is before


@windows
def test_windows_ctrl_break_stops_ask(monkeypatch, home, item):
    reached: list[int] = []
    sentinel = lambda signum, frame: reached.append(signum)  # noqa: E731
    previous = signal.signal(signal.SIGBREAK, sentinel)
    try:
        backend = _Blocks(seconds=3, during=lambda: signal.raise_signal(signal.SIGBREAK))
        monkeypatch.setattr(ask, "_backend", backend)
        out = io.StringIO()
        code, _ = ask.run_ask(home, item, "Stop me", stream=True, out=out, err=io.StringIO())
        assert signal.getsignal(signal.SIGBREAK) is sentinel
    finally:
        signal.signal(signal.SIGBREAK, previous)
    assert reached == []
    assert code == ask.EXIT_INTERRUPTED
    assert _events(out)[-1]["code"] == "interrupted"
    assert _stop_files() == []


_LATE_CHILD = """\
import asyncio, sys, time
from self_learn import stop_request

class Stop(BaseException):
    pass

def handler(signum, frame):
    raise Stop()

print("started", flush=True)
time.sleep(2)  # the request comes while nothing is watching
try:
    stop_request.watch(handler)
    asyncio.run(asyncio.sleep(30))
except Stop:
    stop_request.unwatch()
    sys.exit(7)
sys.exit(1)
"""


@windows
def test_windows_request_to_a_launcher_before_the_watch_is_honoured_once(tmp_path):
    """Gate MAJOR 3: `child.pid` is the virtual environment's launcher and
    nothing watches yet; the interpreter under it honours the request when
    its watch starts, and no file is left for the launcher."""
    script = tmp_path / "late_child.py"
    script.write_text(_LATE_CHILD, encoding="utf-8")
    child = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "started"
        assert stop_request.request_stop(child.pid) is True
        assert child.wait(timeout=20) == 7
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    assert _stop_files() == []


class _Interrupt(BaseException):
    """Stands in for a stop handler raising at an awkward moment."""


@windows
def test_windows_a_watch_interrupted_while_starting_is_undone(monkeypatch):
    """Gate MAJOR 2: a stop raised after the handler is installed but
    before the watch returns still leaves nothing behind after `unwatch`."""
    sentinel = lambda signum, frame: None  # noqa: E731
    previous = signal.signal(signal.SIGBREAK, sentinel)
    try:
        class _Thread:
            def __init__(self, *a, **k):
                pass

            def start(self):
                raise _Interrupt()

            def join(self, timeout=None):
                pass

        monkeypatch.setattr(stop_request.threading, "Thread", _Thread)
        with pytest.raises(_Interrupt):
            stop_request.watch(lambda signum, frame: None)
        assert signal.getsignal(signal.SIGBREAK) is not sentinel  # it was installed
        stop_request.unwatch()
        assert signal.getsignal(signal.SIGBREAK) is sentinel
        assert stop_request._active == []  # noqa: SLF001
        assert _stop_files() == []
    finally:
        signal.signal(signal.SIGBREAK, previous)


@windows
def test_windows_a_watch_interrupted_while_closing_is_still_undone():
    """Gate MAJOR 2: a stop raised in the middle of `unwatch` still puts the
    handler back and removes the files."""
    sentinel = lambda signum, frame: None  # noqa: E731
    previous = signal.signal(signal.SIGBREAK, sentinel)
    try:
        stop_request.watch(lambda signum, frame: None)
        current = stop_request._active[-1]  # noqa: SLF001
        assert _stop_files() != []  # the marker

        class _Joins:
            def join(self, timeout=None):
                raise _Interrupt()

        real = current._thread  # noqa: SLF001
        current._thread = _Joins()  # noqa: SLF001
        with pytest.raises(_Interrupt):
            stop_request.unwatch()
        real.join(5)
        assert signal.getsignal(signal.SIGBREAK) is sentinel
        assert stop_request._active == []  # noqa: SLF001
        assert _stop_files() == []
    finally:
        signal.signal(signal.SIGBREAK, previous)


_FAKE_CHILD = 4_000_000_001


@windows
def test_windows_request_passes_over_a_process_it_cannot_read(monkeypatch):
    """Gate MAJOR 4: an unreadable process recorded under the target (an
    orphan of a reused PID, another user's) is passed over, not raised."""
    real_parents, real_identity = stop_request._parents, stop_request._identity  # noqa: SLF001
    me = os.getpid()
    monkeypatch.setattr(stop_request, "_parents", lambda: {**real_parents(), _FAKE_CHILD: me})

    def identity(pid):
        if pid == _FAKE_CHILD:
            raise OSError(0, "Access is denied", None, 5)
        return real_identity(pid)

    monkeypatch.setattr(stop_request, "_identity", identity)
    assert stop_request.request_stop(me) is True
    own = stop_request.stop_path(me, real_identity(me))
    assert own.exists()
    stop_request._drop_stop(own)  # noqa: SLF001


@windows
def test_windows_request_does_not_follow_a_reused_parent_pid(monkeypatch):
    """Gate MAJOR 4: a process recorded under the target but created before
    it is an orphan of an earlier holder of that PID: not a descendant."""
    real_parents, real_identity = stop_request._parents, stop_request._identity  # noqa: SLF001
    me = os.getpid()
    monkeypatch.setattr(stop_request, "_parents", lambda: {**real_parents(), _FAKE_CHILD: me})
    monkeypatch.setattr(stop_request, "_identity",
                        lambda pid: "1" if pid == _FAKE_CHILD else real_identity(pid))
    stop_request._write_stop(stop_request.watch_path(_FAKE_CHILD, "1"))  # noqa: SLF001
    stop_request._write_stop(stop_request.watch_path(me, real_identity(me)))  # noqa: SLF001
    assert stop_request.request_stop(me) is True
    assert not stop_request.stop_path(_FAKE_CHILD, "1").exists()
    assert stop_request.stop_path(me, real_identity(me)).exists()
    for path in stop_request.stop_dir().iterdir():
        stop_request._drop_stop(path)  # noqa: SLF001


@windows
def test_windows_ancestor_walk_stops_at_a_younger_parent(monkeypatch):
    """A parent PID whose process is younger than this one was reused: the
    launcher chain ends there, so its requests are never ours."""
    real_parents, real_identity = stop_request._parents, stop_request._identity  # noqa: SLF001
    me = os.getpid()
    monkeypatch.setattr(stop_request, "_parents", lambda: {**real_parents(), me: _FAKE_CHILD})
    monkeypatch.setattr(stop_request, "_identity",
                        lambda pid: str(10 ** 18) if pid == _FAKE_CHILD else real_identity(pid))
    assert stop_request._ancestors(me, real_identity(me)) == []  # noqa: SLF001


@windows
def test_windows_watch_refuses_a_linked_stop_folder_before_touching_it(tmp_path):
    """Gate MINOR 1: a junction in place of the stop folder is refused before
    any stale file behind it is scanned or removed."""
    import _winapi

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    victim = elsewhere / "4294967294-1.stop"
    victim.write_text("x\n", encoding="utf-8")
    folder = stop_request.stop_dir()
    folder.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(elsewhere), str(folder))
    before = signal.getsignal(signal.SIGBREAK)
    try:
        with pytest.raises(OSError):
            stop_request.watch(lambda signum, frame: None)
        stop_request.unwatch()
    finally:
        os.rmdir(folder)  # removes the junction, not its target
    assert victim.exists()
    assert signal.getsignal(signal.SIGBREAK) is before


@windows
def test_windows_doctor_premises_reports_platform_probes_and_no_broken(tmp_path, monkeypatch):
    """Gate MINOR 2: through `doctor_rows` itself, a routed lesson whose
    systemd probe was `platform` on three sweeps is information, not broken."""
    from self_learn.records import Record
    from support import commit_all, make_behavior, make_env

    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    rid = "lrn-0000c001"
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record = make_behavior(scope="skill:s", record_id=rid)
    record.set_routing({"routed_at": "2026-09-22T06:24:50Z", "destination": "skill-md",
                        "by": "human"})
    record.set_status("routed")
    baseline = {**premises.make_baseline(premises.observation_from_value("active")),
                "observed_at": "2026-09-22T06:24:50Z"}
    record.set_premises([{"id": "p1", "claim": "the unit runs",
                          "probe": dict(_LINUX_ONLY_PROBES[0]), "baseline": baseline}])
    record.write(resolved / f"{rid}.md")
    commit_all(env.ledger, f"seed {rid}")
    premise = (Record.from_path(resolved / f"{rid}.md").premises or [])[0]
    cache = premise_sweep.default_cache_dir(env.ledger)
    cache.mkdir(parents=True, exist_ok=True)
    rows = [{**row, "record": rid} for row in _rows_of_platform(premise)]
    premise_sweep._store_history(cache, {(rid, "p1"): rows})  # noqa: SLF001
    found = premise_sweep.doctor_rows(env.ledger)
    named = [(r.verdict, r.name) for r in found]
    assert ("INFO", "platform-unavailable") in named, named
    assert not any(name == "broken-probes" for _v, name in named), named


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
def test_linux_ask_never_watches_for_a_stop_file(monkeypatch, home, item):
    calls: list[str] = []
    monkeypatch.setattr(stop_request, "watch", lambda handler: calls.append("watch"))
    monkeypatch.setattr(stop_request, "unwatch", lambda: calls.append("unwatch"))
    failed = Outcome(ok=False, rc=1, stdout="", detail="scripted failure", failure="exit")
    monkeypatch.setattr(ask, "_backend", _Blocks(seconds=0, outcome=failed))
    code, _ = ask.run_ask(home, item, "Why?", stream=True, out=io.StringIO(), err=io.StringIO())
    assert code == ask.EXIT_FAILED
    assert calls == []


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
