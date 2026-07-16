"""T19 — supply_mix + the 04 §Success-metrics counters in `status --json`
(08 §8.1 O-3/O-7-revisit row: counted-not-modeled, computed from the
ledger + git on demand, no state files).

Every number here is hand-counted against the fixture — the testing-regime
audit's lesson (a formula can be swapped and labels still pass) applied
from day one.
"""

from __future__ import annotations

import json

import pytest

from self_learn import cli, verbs
from self_learn.ledger_ops import create_record
from self_learn.report import ledger_metrics, supply_mix
from support import (
    days_ago,
    git,
    make_behavior,
    make_env,
    make_knowledge,
)


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    return e


def seed_record(env, rid, *, source="teach", age_days=0, scope="skill:s"):
    record = make_behavior(scope=scope, record_id=rid, created_at=days_ago(age_days))
    record.set_source(source)
    create_record(env.ledger, record)
    return record


class TestSupplyMix:
    def test_counts_pending_plus_resolved_by_source(self, env):
        seed_record(env, "lrn-aa000001", source="teach", age_days=1)
        seed_record(env, "lrn-aa000002", source="teach", age_days=2)
        seed_record(env, "lrn-aa000003", source="session", age_days=3)
        seed_record(env, "lrn-aa000004", source="backlog", age_days=4)
        verbs.route(env.ledger, "lrn-aa000001", dest="skill-md", no_push=True)
        verbs.reject(env.ledger, "lrn-aa000003", no_push=True)

        # hand-count: resolved records still count toward their source
        assert supply_mix(env.ledger) == {
            "teach": 2,
            "session": 1,
            "backlog": 1,
        }

    def test_empty_ledger_is_empty_mix(self, env):
        assert supply_mix(env.ledger) == {}


class TestMetrics:
    def test_time_to_triage_median_hand_counted(self, env):
        # routed after 10 days (routed_at = now, created 10d ago) and
        # rejected after 20 (resolution commit = now) → median 15.0
        seed_record(env, "lrn-aa000001", age_days=10)
        seed_record(env, "lrn-aa000002", age_days=20)
        seed_record(env, "lrn-aa000003", age_days=99)  # still pending: excluded
        verbs.route(env.ledger, "lrn-aa000001", dest="skill-md", no_push=True)
        verbs.reject(env.ledger, "lrn-aa000002", no_push=True)

        m = ledger_metrics(env.ledger)
        assert m["time_to_triage_median_days"] == 15.0

    def test_queue_health_pct_over_30d(self, env):
        seed_record(env, "lrn-aa000001", age_days=40)
        seed_record(env, "lrn-aa000002", age_days=5)
        m = ledger_metrics(env.ledger)
        assert m["pending_over_30d_pct"] == 50.0
        assert m["pending_total"] == 2

    def test_routed_and_corrected_excludes_graduations(self, env):
        # corrective supersession of a ROUTED record counts; graduation
        # (superseded_by: canon) is a success and must NOT (04 metric).
        seed_record(env, "lrn-aa000001", age_days=3)
        seed_record(env, "lrn-aa000002", age_days=3)
        seed_record(env, "lrn-aa000003", age_days=3)
        verbs.route(env.ledger, "lrn-aa000001", dest="skill-md", no_push=True)
        verbs.route(env.ledger, "lrn-aa000002", dest="skill-md", no_push=True)
        verbs.route(env.ledger, "lrn-aa000003", dest="skill-md", no_push=True)
        verbs.graduate(env.ledger, "lrn-aa000002", no_push=True)
        replacement = make_behavior(scope="skill:s", record_id="lrn-aa000009")
        create_record(env.ledger, replacement)
        verbs.supersede(env.ledger, "lrn-aa000001", "lrn-aa000009", no_push=True)

        m = ledger_metrics(env.ledger)
        assert m["routed_and_corrected"] == 1

    def test_empty_ledger_metrics_are_null_not_zero(self, env):
        # honesty: no data is "n/a", never a confident 0-days median.
        m = ledger_metrics(env.ledger)
        assert m["time_to_triage_median_days"] is None
        assert m["pending_over_30d_pct"] is None
        assert m["routed_and_corrected"] == 0


class TestStatusJson:
    def test_status_json_carries_the_blocks(self, env, capsys):
        seed_record(env, "lrn-aa000001", source="teach", age_days=40)
        seed_record(env, "lrn-aa000002", source="session", age_days=1)
        verbs.route(env.ledger, "lrn-aa000001", dest="skill-md", no_push=True)
        capsys.readouterr()

        assert cli.main(["status", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["supply_mix"] == {"teach": 1, "session": 1}
        assert payload["metrics"]["routed_and_corrected"] == 0
        assert payload["metrics"]["time_to_triage_median_days"] == 40.0
        assert payload["metrics"]["pending_total"] == 1

    def test_fast_path_untouched(self, env, capsys):
        # 08 §7.1: --fast stays a pending/-only frontmatter scan — no git,
        # no supply mix (the pin the SessionStart budget rides on).
        assert cli.main(["status", "--fast"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert "supply_mix" not in payload
        assert "metrics" not in payload
