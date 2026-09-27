"""2026-09-26 (agenda item 25): a `--dry-run` never arms the host's attempt
cooldown for the real run.

A dry run's journal rows -- `model-log` lines above all, and any `refused`
or `population` row -- are not hold statuses, so before this serve's
`_journal_attempt_epoch` read the newest of them as an attempt and held the
real steward or overseer run behind a rehearsal. Every row a dry run writes
is now marked `"dry_run": true`, and the due-check skips a marked row. A
REAL run's rows are unchanged and still arm the cooldown (positive
controls).

Sandbox ledgers and cache dirs under pytest's tmpdir only.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

from self_learn import miner, serve, steward, worker
from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_run import _fake_two_phase
from test_steward import (
    _enable_steward,
    _journal_rows,
    _seed_fresh_proposals,
    _write_decision_stage,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).astimezone().isoformat()


def _write_rows(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


# ------------------------------------------------ the due-check's own rule


def test_a_dry_run_model_log_row_alone_leaves_the_steward_due(tmp_path):
    cache_dir = tmp_path / "cache"
    now = time.time()
    journal = cache_dir / "steward" / "journal.jsonl"
    _write_rows(journal, [
        {"ts": _iso(now - 5), "run_id": "run-a", "status": "model-log", "message": "x",
         "dry_run": True},
        {"ts": _iso(now - 1), "run_id": "run-a", "status": "refused", "error": "e",
         "dry_run": True},
    ])
    assert serve._steward_recently_attempted(cache_dir, now) is False

    # Positive control: the same rows from a real run arm the cooldown.
    _write_rows(journal, [
        {"ts": _iso(now - 5), "run_id": "run-a", "status": "attempt-start"},
        {"ts": _iso(now - 1), "run_id": "run-a", "status": "model-log", "message": "x"},
    ])
    assert serve._steward_recently_attempted(cache_dir, now) is True


def test_a_dry_run_row_does_not_hide_an_earlier_real_attempt(tmp_path):
    """Skipping a marked row reads on to the real attempt behind it."""
    cache_dir = tmp_path / "cache"
    now = time.time()
    _write_rows(cache_dir / "steward" / "journal.jsonl", [
        {"ts": _iso(now - 60), "run_id": "run-r", "status": "attempt-start"},
        {"ts": _iso(now - 1), "run_id": "run-d", "status": "model-log", "dry_run": True},
    ])
    assert serve._steward_recently_attempted(cache_dir, now) is True
    assert serve._steward_recently_attempted(
        cache_dir, now + miner.ATTEMPT_COOLDOWN_SECS + 1
    ) is False


def test_a_dry_run_row_alone_leaves_the_overseer_due(tmp_path):
    cache_dir = tmp_path / "cache"
    now = time.time()
    journal = cache_dir / "overseer.journal"
    _write_rows(journal, [
        {"at": _iso(now - 5), "run": "r1", "status": "population", "count": 3, "dry_run": True},
        {"at": _iso(now - 1), "run": "r1", "status": "model-log", "phase": "a", "dry_run": True},
    ])
    assert serve._overseer_recently_attempted(cache_dir, now) is False

    _write_rows(journal, [
        {"at": _iso(now - 5), "run": "r1", "status": "attempt-start"},
        {"at": _iso(now - 1), "run": "r1", "status": "model-log", "phase": "a"},
    ])
    assert serve._overseer_recently_attempted(cache_dir, now) is True


# ------------------------------------------ the marker reaches every row


def _talking_session(spec):
    spec.log("the model said something")
    return _write_decision_stage(spec)


def test_every_row_a_steward_dry_run_writes_is_marked(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _talking_session)

    result = steward.run(home, dry_run=True)

    assert result.status == "dry-run"
    rows = _journal_rows(home)
    statuses = [row["status"] for row in rows]
    assert "model-log" in statuses, statuses  # positive control: the model log landed
    assert all(row.get("dry_run") is True for row in rows), rows
    cache_dir = worker.cache_dir(home)
    assert serve._steward_recently_attempted(cache_dir, time.time()) is False
    assert steward._DRY_RUN_JOURNAL is False  # the flag does not outlive the run


def test_a_real_steward_run_still_arms_the_cooldown(tmp_path, monkeypatch):
    """Positive control, end to end: a real run's rows are unmarked."""
    monkeypatch.setenv(worker.NO_PUSH_ENV, "1")
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _talking_session)

    result = steward.run(home, dry_run=False)

    assert result.status == "applied", result
    rows = _journal_rows(home)
    assert "model-log" in [row["status"] for row in rows]
    assert not any("dry_run" in row for row in rows), rows
    cache_dir = worker.cache_dir(home)
    assert serve._steward_recently_attempted(cache_dir, time.time()) is True


def test_every_row_an_overseer_dry_run_writes_is_marked(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _fake_two_phase(monkeypatch)
    fake = overseer_run.invocation.write_session

    def talking(spec):
        spec.log("the overseer model said something")
        return fake(spec)

    monkeypatch.setattr(overseer_run.invocation, "write_session", talking)

    result = overseer_run.run(home, dry_run=True, no_push=True)

    assert result.status == "dry-run", result
    rows = overseer_run.read_journal(home, limit=1000)
    statuses = [row["status"] for row in rows]
    assert "model-log" in statuses, statuses  # positive control
    assert all(row.get("dry_run") is True for row in rows), rows
    cache_dir = worker.cache_dir(home)
    assert serve._overseer_recently_attempted(cache_dir, time.time()) is False
    assert overseer_run._DRY_RUN_JOURNAL is False
