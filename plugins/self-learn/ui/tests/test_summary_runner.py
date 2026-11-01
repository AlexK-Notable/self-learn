"""Humane UI lane 5, gate r1 MINOR 2: `RealAskRunner.start_summary`, the
one real spawn of `self-learn summarise`, driven against a fake
`self-learn` (a Python script printing NDJSON), never the real CLI and
never a model: its argv (`--stream`, `--again`), its relay under
`type: summary`, and a Stop that ends the verb's whole process group (so
`start_new_session=True` is what Stop and the watchdog rely on).

Each test names the mutation it was checked against.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from self_learn_ui.ask_runner import RealAskRunner, summary_key

KEY = summary_key("overseer-report", "2026-11-01")

FAKE_CLI = r'''
import json, os, subprocess, sys, time
args = sys.argv[1:]
child = None
if os.environ.get("FAKE_MODE") == "hang":
    # A grandchild in the same process group: Stop must end it too.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"args": args, "pid": os.getpid(), "pgid": os.getpgid(0),
                         "child": child.pid if child else None}) + "\n")
def emit(ev):
    print(json.dumps(ev), flush=True)
emit({"ev": "start", "model": "fake"})
if os.environ.get("FAKE_MODE") != "hang":
    emit({"ev": "delta", "text": "Nothing needs you."})
    emit({"ev": "done", "text": "Nothing needs you.", "written": True, "summary": None})
    sys.exit(0)
deadline = time.time() + 30
while time.time() < deadline:
    time.sleep(0.05)
'''


@pytest.fixture
def fake_cli(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_self_learn.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    return [sys.executable, str(script)]


def _runner(tmp_path, fake_cli, events, mode="ok"):
    env = dict(os.environ)
    env.update(FAKE_LOG=str(tmp_path / "fake.log"), FAKE_MODE=mode)
    return RealAskRunner(home=tmp_path / "home", publish=events.append, argv_prefix=fake_cli,
                         env=env, ask_timeout=30, kill_grace=1.0)


def _log(tmp_path) -> list[dict]:
    path = tmp_path / "fake.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def _finish(runner, key, timeout=15.0):
    task = runner._tasks.get(key)  # noqa: SLF001 - the test joins the driver
    if task is not None:
        await asyncio.wait_for(task, timeout=timeout)


def test_a_summary_spawns_the_verb_streaming_and_relays_it_as_summary_envelopes(tmp_path, fake_cli):
    """Mutations: drop `--stream` -> red; relay under `type: ask` -> red."""
    events: list[dict] = []

    async def go():
        runner = _runner(tmp_path, fake_cli, events)
        assert await runner.start_summary("overseer-report", "2026-11-01") is None
        await _finish(runner, KEY)
        return runner.summary_view(KEY)

    view = asyncio.run(go())
    (row,) = _log(tmp_path)
    assert row["args"] == ["summarise", "overseer-report:2026-11-01", "--stream"]
    assert [e["ev"] for e in events] == ["start", "delta", "done", "end"]
    assert all(e["type"] == "summary" and e["item"] == KEY for e in events)
    assert view["running"] is False and view["result"]["text"] == "Nothing needs you."


def test_write_it_again_passes_again_to_the_verb(tmp_path, fake_cli):
    """Mutation: drop `--again` from the argv -> red ("Write it again"
    would quietly return the saved text)."""
    events: list[dict] = []

    async def go():
        runner = _runner(tmp_path, fake_cli, events)
        assert await runner.start_summary("overseer-report", "2026-11-01", again=True) is None
        await _finish(runner, KEY)

    asyncio.run(go())
    (row,) = _log(tmp_path)
    assert row["args"] == ["summarise", "overseer-report:2026-11-01", "--stream", "--again"]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return False


def test_stop_ends_the_verbs_whole_process_group(tmp_path, fake_cli):
    """Mutation: `start_new_session=False` -> red (the verb is not its own
    group leader, so Stop signals the verb alone and its child lives on)."""
    events: list[dict] = []

    async def go():
        runner = _runner(tmp_path, fake_cli, events, mode="hang")
        assert await runner.start_summary("overseer-report", "2026-11-01") is None
        deadline = time.monotonic() + 10
        while not _log(tmp_path) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert runner.summary_view(KEY)["running"] is True  # control: it is in flight
        assert await runner.stop(KEY) is True
        await _finish(runner, KEY)

    asyncio.run(go())
    (row,) = _log(tmp_path)
    assert row["pgid"] == row["pid"], "the verb leads its own process group"
    deadline = time.monotonic() + 5
    while _alive(row["child"]) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(row["child"]), "Stop left the verb's child running"
