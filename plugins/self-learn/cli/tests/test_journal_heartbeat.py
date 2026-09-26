"""2026-09-26 (agenda item 22, from the dashboard guide): the journals and
the heartbeat tell the truth during a run.

(a) every steward journal row written once the run id is known carries it
    (`attempt-start`, `model-log`, `push`, the run's own final row);
(b) a steward `--dry-run` writes a journal row, marked `"dry_run": true`,
    with a hold status so serve's cooldown never reads it as an attempt;
(c) serve keeps its heartbeat fresh WHILE a job runs, naming the job, and
    drops that name once the job is done.

Sandbox ledgers and cache dirs under pytest's tmpdir only.
"""

from __future__ import annotations

import time

import pytest

from self_learn import serve, steward, worker
from support import make_home
from test_steward import (
    _enable_steward,
    _journal_rows,
    _seed_fresh_proposals,
    _with_bare_remote,
    _write_decision_stage,
)


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _talking_session(spec):
    spec.log("the model said something")
    return _write_decision_stage(spec)


def test_steward_journal_rows_carry_the_run_id(tmp_path, monkeypatch):
    monkeypatch.delenv(worker.NO_PUSH_ENV, raising=False)
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    _with_bare_remote(home, tmp_path)
    monkeypatch.setattr(steward.invocation, "write_session", _talking_session)

    result = steward.run(home, dry_run=False)

    assert result.status == "applied" and result.run_id
    rows = {row["status"]: row for row in _journal_rows(home)}
    for status in ("attempt-start", "model-log", "applied", "push"):
        assert status in rows, (status, list(rows))  # positive control: the row exists
        assert rows[status].get("run_id") == result.run_id, rows[status]


def test_steward_dry_run_writes_one_marked_journal_row(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _write_decision_stage)

    result = steward.run(home, dry_run=True)

    assert result.status == "dry-run" and result.run_id
    rows = [row for row in _journal_rows(home) if row.get("dry_run") is True]
    assert len(rows) == 1, _journal_rows(home)
    (row,) = rows
    assert (row["status"], row["run_id"], row["calls"]) == ("dry-run", result.run_id, 1)
    assert "attempt-start" not in [r["status"] for r in _journal_rows(home)]
    # The row never arms serve's cooldown: `dry-run` is a hold status.
    assert "dry-run" in serve._HOLD_STATUSES


def test_the_heartbeat_is_refreshed_and_names_the_job_while_it_runs(tmp_path):
    cache = tmp_path / "cache"
    serve.write_heartbeat(cache, pid=4242, next_job="steward at 2026-09-26T03:00:00", tick_secs=0.2)
    seen: list[dict] = []

    def long_job():
        for _ in range(8):
            time.sleep(0.1)
            seen.append(dict(serve.read_heartbeat(cache) or {}))
        return "done"

    started = time.time()
    record = serve.run_one_job(cache, serve.Job("steward", "steward", long_job), pid=4242, tick_secs=0.2)

    assert record.ok and record.result == "done"
    assert len(seen) == 8
    late = seen[-1]
    assert late["running"] == "steward"
    assert late["running_since"] >= started - 1
    assert late["next_job"] == "steward at 2026-09-26T03:00:00"
    # Fresh DURING the job: the last reading, 0.8 s into a 0.2 s tick, was
    # written well inside one tick of when it was read.
    stamps = [row["ts"] for row in seen]
    assert stamps[-1] > stamps[0], stamps
    assert stamps[-1] >= started + 0.5, (started, stamps)
    after = serve.read_heartbeat(cache) or {}
    assert "running" not in after and after["next_job"] == "steward"
