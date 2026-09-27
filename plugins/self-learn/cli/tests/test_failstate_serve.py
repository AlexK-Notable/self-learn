"""Fail-state batch 1, unit 6 (2026-09-27): the host logs a crashed job.

Audit finding 6: `serve.run_one_job` caught a job's exception into a
`JobRecord` that nothing printed, journaled or notified, which is what made
findings 5 and 8 silent. Now the error and its traceback go to stderr (the
service log) and a `crashed` row goes to the job's own journal, or serve's.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from self_learn import serve, steward
from self_learn.overseer import run as overseer_run


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _boom(home):
    raise RuntimeError("synthetic crash in the job")


def test_a_crashed_steward_job_is_journaled_and_printed(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    cache_dir = tmp_path / "serve-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: False)
    monkeypatch.setattr(serve, "_overseer_is_due", lambda *a, **k: False)
    monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: True)
    monkeypatch.setattr(serve, "_run_steward_job", _boom)

    (record,) = serve._run_tick(home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)

    assert record.name == "steward" and not record.ok  # the daemon still survives it
    err = capsys.readouterr().err
    assert "the steward job crashed: RuntimeError: synthetic crash in the job" in err
    assert "Traceback" in err
    crashed = [row for row in _rows(steward.journal_path(home)) if row.get("status") == "crashed"]
    assert len(crashed) == 1 and "synthetic crash" in crashed[0]["error"]


def test_a_crashed_overseer_job_is_journaled_in_the_overseer_journal(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    cache_dir = tmp_path / "serve-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: False)
    monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: False)
    monkeypatch.setattr(serve, "_overseer_is_due", lambda *a, **k: True)
    monkeypatch.setattr(serve, "_run_overseer_job", _boom)

    (record,) = serve._run_tick(home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)

    assert record.name == "overseer" and not record.ok
    assert "the overseer job crashed" in capsys.readouterr().err
    rows = overseer_run.read_journal(home, limit=10)
    assert any(row.get("status") == "crashed" and "synthetic crash" in row.get("error", "") for row in rows)


def test_a_crashed_job_without_a_journal_of_its_own_goes_to_serves(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    cache_dir = tmp_path / "serve-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(serve, "_mine_is_due", lambda *a, **k: True)
    monkeypatch.setattr(serve, "_steward_is_due", lambda *a, **k: False)
    monkeypatch.setattr(serve, "_overseer_is_due", lambda *a, **k: False)
    monkeypatch.setattr(serve, "_run_mine_job", _boom)

    records = serve._run_tick(home, cache_dir, now=time.time(), pid=os.getpid(), tick_secs=60.0)

    assert [record.name for record in records] == ["mine"] and not records[0].ok
    assert "the mine job crashed" in capsys.readouterr().err
    rows = _rows(cache_dir / serve.SERVE_JOURNAL_FILENAME)
    assert rows == [{"at": rows[0]["at"], "status": "crashed", "job": "mine",
                     "error": "RuntimeError: synthetic crash in the job"}]


def test_a_job_that_returns_writes_no_crash_row(tmp_path, monkeypatch, capsys):
    """Control: an ordinary run leaves no `crashed` row and prints nothing."""
    cache_dir = tmp_path / "serve-cache"
    cache_dir.mkdir()
    record = serve.run_one_job(
        cache_dir, serve.Job("mine", "miner-reader", lambda: "fine"), home=tmp_path / "home",
    )
    assert record.ok and record.result == "fine"
    assert "crashed" not in capsys.readouterr().err
    assert not (cache_dir / serve.SERVE_JOURNAL_FILENAME).exists()
