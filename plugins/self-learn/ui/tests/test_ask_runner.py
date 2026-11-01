"""The inbox's ask runner (attention round 2026-10-31c, design r2 §3.3
"Streaming to the page", "Timeouts", "Stop"; §5.5 tests 6 and 7).

`RealAskRunner` is driven against a fake `self-learn` (a Python script
printing §4.8 NDJSON), never the real CLI and never a model: the runner's
own job is the process — spawn, relay, limits, watchdog, Stop.
`FakeAskRunner` is the scripted twin the routes and the walk world use.

Each test names the mutation it was checked against.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from self_learn_ui.ask_runner import (
    MAX_TURNS_IN_FLIGHT,
    FakeAskRunner,
    LoginCheck,
    RealAskRunner,
    build_ask_runner,
)
from self_learn_ui.idle import ActivityTracker, IdleMonitor

ITEM = "att-0000000000b2"
OTHER = "att-0000000000c3"
THIRD = "att-0000000000d4"

FAKE_CLI = r'''
import json, os, signal, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
if args[:2] == ["attention", "check-login"]:
    code = int(os.environ.get("FAKE_LOGIN", "0"))
    if code == 0:
        print("attention check-login: the login works")
    else:
        print("self-learn attention check-login: the login is broken -- fix: run claude", file=sys.stderr)
    sys.exit(code)
assert args[0] == "ask" and "--stream" in args, args
item = args[1]
message = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"item": item, "message": message, "args": args}) + "\n")
def emit(ev):
    print(json.dumps(ev), flush=True)
def on_term(signum, frame):
    marker = os.environ.get("FAKE_MARKER", "")
    note = "stopped by you" if marker and os.path.exists(marker) else "stopped before it answered"
    emit({"ev": "error", "code": "interrupted", "message": note, "fix": None})
    sys.exit(7)
signal.signal(signal.SIGTERM, on_term)
emit({"ev": "start", "item": item, "turn": 1, "session": None, "resumed": False, "reinjected": False, "model": "fake"})
if mode == "ok":
    emit({"ev": "tool", "name": "mcp__selflearn_ask__case", "target": "case-0fcce296"})
    emit({"ev": "delta", "text": "The drop-in "})
    emit({"ev": "delta", "text": "already exists."})
    emit({"ev": "draft", "draft_id": "drf-1a2b3c4d", "option": None, "text": "No, it is done."})
    emit({"ev": "done", "turn": 2, "text": "The drop-in already exists.", "session": "s", "sealed": [2, 3]})
    sys.exit(0)
if mode == "crash":
    print("Traceback: boom", file=sys.stderr)
    sys.exit(1)
if mode == "deaf":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
deadline = time.time() + 30  # never outlive a test run, even unkillable
while time.time() < deadline:
    time.sleep(0.05)
'''


@pytest.fixture
def fake_cli(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_self_learn.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    return [sys.executable, str(script)]


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["FAKE_LOG"] = str(tmp_path / "fake.log")
    env.update(extra)
    return env


def _runner(tmp_path, fake_cli, events, **kw):
    env = _env(tmp_path, **kw.pop("env", {}))
    return RealAskRunner(home=tmp_path / "home", publish=events.append, argv_prefix=fake_cli,
                         env=env, **kw)


async def _finish(runner: RealAskRunner, item: str, timeout: float = 15.0) -> None:
    task = runner._tasks.get(item)  # noqa: SLF001 - the test joins the driver
    if task is not None:
        await asyncio.wait_for(task, timeout=timeout)


def test_a_turn_relays_every_event_in_order_as_ask_envelopes(tmp_path, fake_cli):
    """Mutation: relay without the `type: ask` / `item` stamp -> red."""
    events: list[dict] = []

    async def go():
        runner = _runner(tmp_path, fake_cli, events, ask_timeout=30)
        assert await runner.start(ITEM, "is it already done?") is None
        assert runner.busy
        await _finish(runner, ITEM)
        assert not runner.busy
        return runner

    runner = asyncio.run(go())
    assert [e["ev"] for e in events] == ["start", "tool", "delta", "delta", "draft", "done", "end"]
    assert all(e["type"] == "ask" and e["item"] == ITEM for e in events)
    assert events[-1]["exit"] == 0
    logged = json.loads((tmp_path / "fake.log").read_text().splitlines()[0])
    # The question reaches the verb on stdin, never argv.
    assert logged["message"] == "is it already done?"
    assert "is it already done?" not in logged["args"]
    assert logged["args"][:5] == ["ask", ITEM, "--message-file", "-", "--stream"]
    assert runner.in_flight(ITEM) is None


def test_one_turn_per_item_and_two_across_the_ui(tmp_path, fake_cli):
    """Mutation: drop the per-item check -> red; raise the global cap -> red."""
    events: list[dict] = []

    async def go():
        runner = _runner(tmp_path, fake_cli, events, ask_timeout=30, env={"FAKE_MODE": "hang"})
        assert await runner.start(ITEM, "one") is None
        assert await runner.start(ITEM, "two") == "Still answering your last question."
        assert await runner.start(OTHER, "three") is None
        refused = await runner.start(THIRD, "four")
        assert refused is not None and "Two questions" in refused
        view = runner.in_flight(ITEM)
        assert view is not None and view["message"] == "one"
        for _ in range(200):
            if sum(1 for e in events if e.get("ev") == "start") == 2:
                break
            await asyncio.sleep(0.05)
        for item in (ITEM, OTHER):
            await runner.stop(item)
            await _finish(runner, item)
        assert not runner.busy

    asyncio.run(go())
    assert MAX_TURNS_IN_FLIGHT == 2
    starts = [json.loads(line)["item"] for line in (tmp_path / "fake.log").read_text().splitlines()]
    assert sorted(starts) == sorted([ITEM, OTHER])


def test_stop_leaves_the_persons_marker_before_the_signal(tmp_path, fake_cli):
    """§3.3: only a marked Stop is "stopped by you". Mutation: signal
    without `request_stop` -> red."""
    from self_learn import ask as sl_ask

    home = tmp_path / "home"
    marker = sl_ask.stop_marker(home, ITEM)
    events: list[dict] = []

    async def go():
        runner = RealAskRunner(home=home, publish=events.append, argv_prefix=fake_cli,
                               env=_env(tmp_path, FAKE_MODE="hang", FAKE_MARKER=str(marker)),
                               ask_timeout=30)
        await runner.start(ITEM, "why?")
        for _ in range(100):
            if any(e.get("ev") == "start" for e in events):
                break
            await asyncio.sleep(0.05)
        assert await runner.stop(ITEM) is True
        await _finish(runner, ITEM)
        assert await runner.stop(ITEM) is False

    asyncio.run(go())
    errors = [e for e in events if e["ev"] == "error"]
    assert errors and errors[0]["message"] == "stopped by you"
    assert events[-1]["ev"] == "end" and events[-1]["exit"] == 7


def test_the_watchdog_ends_a_turn_that_overruns_even_one_that_ignores_sigterm(tmp_path, fake_cli):
    """The UI's watchdog is the turn's timeout plus a grace, then SIGTERM,
    then SIGKILL. Mutation: drop the SIGKILL leg -> the turn never ends."""
    events: list[dict] = []

    async def go():
        runner = _runner(tmp_path, fake_cli, events, ask_timeout=0.3, watchdog_grace=0.2,
                         kill_grace=0.3, env={"FAKE_MODE": "deaf"})
        await runner.start(ITEM, "slow?")
        await _finish(runner, ITEM, timeout=10)
        assert not runner.busy

    asyncio.run(go())
    assert events[-1]["ev"] == "end"
    errors = [e for e in events if e["ev"] == "error"]
    assert errors and errors[0]["code"] == "interrupted"


def test_a_crashed_verb_becomes_an_error_with_its_stderr(tmp_path, fake_cli):
    events: list[dict] = []

    async def go():
        runner = _runner(tmp_path, fake_cli, events, ask_timeout=30, env={"FAKE_MODE": "crash"})
        await runner.start(ITEM, "x")
        await _finish(runner, ITEM)

    asyncio.run(go())
    errors = [e for e in events if e["ev"] == "error"]
    assert errors and "Traceback: boom" in errors[0]["message"]
    assert events[-1] == {"type": "ask", "item": ITEM, "ev": "end", "exit": 1}


def test_check_login_runs_its_verb_and_reports_the_fix(tmp_path, fake_cli):
    async def go(code: str) -> LoginCheck:
        runner = _runner(tmp_path, fake_cli, [], env={"FAKE_LOGIN": code})
        return await runner.check_login()

    ok = asyncio.run(go("0"))
    assert ok.ok and "the login works" in ok.message
    broken = asyncio.run(go("3"))
    assert broken.exit_code == 3 and "fix: run claude" in broken.message


# ----------------------------------------------------------------- 7. idle


class _Pane:
    def has_interruptible_session(self) -> bool:
        return False

    async def teardown_parked(self) -> bool:
        return False


def test_an_ask_turn_in_flight_blocks_the_idle_exit(tmp_path):
    """§3.3: the UI's idle exit is suspended while any ask turn is in
    flight. Mutation: ignore the runner (drop the ask leg) -> red."""
    events: list[dict] = []
    fired = {"n": 0}

    async def go():
        ask = FakeAskRunner(publish=events.append, hold=True,
                            script=[{"ev": "start"}, {"ev": "done", "text": "x"}])
        clock = [1000.0]
        tracker = ActivityTracker(clock=lambda: clock[0])
        monitor = IdleMonitor(
            tracker=tracker, subscriber_count=lambda: 0, runner_busy=lambda: False,
            pane_manager=_Pane(), window_seconds=60, exit_callback=lambda: fired.__setitem__("n", fired["n"] + 1),
            ask_busy=lambda: ask.busy,
        )
        clock[0] += 120
        await ask.start(ITEM, "still there?")
        await asyncio.sleep(0)
        assert ask.busy
        assert await monitor.sample_once() is False
        assert fired["n"] == 0
        ask.release(ITEM)
        await ask.wait(ITEM)
        assert not ask.busy
        assert await monitor.sample_once() is True

    asyncio.run(go())
    assert fired["n"] == 1


# ----------------------------------------------------------------- the switch


def test_the_fake_switch_builds_the_sealing_fake_and_logs_it(tmp_path):
    fake = build_ask_runner(home=tmp_path, publish=lambda e: None,
                            environ={"SELF_LEARN_UI_FAKE_ASK": "1"})
    assert isinstance(fake, FakeAskRunner) and fake.seal and fake.home == tmp_path
    real = build_ask_runner(home=tmp_path, publish=lambda e: None, environ={})
    assert isinstance(real, RealAskRunner)


def test_the_sealing_fake_marks_the_login_working_as_the_real_check_does(tmp_path, monkeypatch):
    """The walk world's fake (``seal=True``) writes ``login-ok.json`` after a
    working login check, the file the real ``attention check-login`` writes
    (S-124), so a ``hold.credentials`` item ends there too. 2026-11-01
    (integration): it now writes through ``fsops.atomic_write`` (the
    raw-write gate). Control first: an unsealed fake writes nothing."""
    from self_learn import ask as sl_ask

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    target = sl_ask.login_ok_path(tmp_path)
    plain = FakeAskRunner(publish=lambda e: None, home=tmp_path)
    assert asyncio.run(plain.check_login()).ok
    assert not target.exists()  # control: no seal, no file
    sealing = FakeAskRunner(publish=lambda e: None, home=tmp_path, seal=True)
    assert asyncio.run(sealing.check_login()).ok
    assert set(json.loads(target.read_text(encoding="utf-8"))) == {"at"}
