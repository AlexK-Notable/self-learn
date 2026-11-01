"""S-136 (gate r1 MINOR-3): `status --json` carries the
steward's own verdicts, the same `steward.nudge_fields` `status --fast`
carries, so the UI's header can name a nightly review that is held or
behind. Additive: the keys lane 0 and earlier pinned are untouched."""

from __future__ import annotations

import json

import pytest

from self_learn import cli
from self_learn.ledger_ops import create_record
from support import make_behavior, make_env


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _status(capsys) -> dict:
    assert cli.main(["status", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_status_json_names_a_stale_steward(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    (env.ledger / "config.yaml").write_text("steward:\n  enabled: true\n", encoding="utf-8")
    create_record(env.ledger, make_behavior(scope="skill:s", record_id="lrn-0a0a0a0a"))
    data = _status(capsys)
    # positive control: the existing keys are all still there
    for key in ("buckets", "total_pending", "steward_last_run_at", "overseer_next"):
        assert key in data
    assert data["steward_enabled"] is True
    # never completed a run, one lesson it may take: behind
    assert data["steward_stale"] is True
    assert isinstance(data["steward_stale_hours"], int)


def test_status_json_with_the_steward_off_says_only_that(tmp_path, monkeypatch, capsys):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    (env.ledger / "config.yaml").write_text("steward:\n  enabled: false\n", encoding="utf-8")
    create_record(env.ledger, make_behavior(scope="skill:s", record_id="lrn-0b0b0b0b"))
    data = _status(capsys)
    assert data["steward_enabled"] is False
    assert "steward_stale" not in data


def test_status_json_names_a_held_steward(tmp_path, monkeypatch, capsys):
    from self_learn import serve

    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    (env.ledger / "config.yaml").write_text("steward:\n  enabled: true\n", encoding="utf-8")
    journal = serve.cache_dir_readonly(env.ledger) / "steward" / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps({"ts": "t1", "run_id": "r1", "status": "held-environment",
                    "cause": "OAuth session expired"}) + "\n"
        + json.dumps({"ts": "t2", "run_id": "r1", "status": "partial",
                      "held": "OAuth session expired"}) + "\n",
        encoding="utf-8",
    )
    data = _status(capsys)
    assert data["steward_hold"] == "OAuth session expired"
