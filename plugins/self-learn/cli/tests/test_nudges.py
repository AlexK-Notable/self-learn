"""L3 (S-NEXT-nudges): person-facing nudges follow the queue's owner.

While `steward.enabled` is on the queue is the steward's: no review popups,
no "review session is due", and a session-start line only when the steward
is not keeping up. With the steward off every line stays as pinned (08 §7.1).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from self_learn import steward, worker
from self_learn.overseer import notify as overseer_notify

# The worker suite's fixtures (an autouse cache/notify sandbox, the fake
# model session, the notify shim) are reused as they are.
from test_worker import (  # noqa: F401  (fixtures)
    redirect,
    _wait_for_file,
    env,
    notify_shim,
    sdk_fake_worker,
    seed_pending,
    shim_writes,
)
from test_pending_hook import _base_payload, _run_hook

HOUR = 3600.0
NOW = 1_800_000_000.0


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _enable(home: Path) -> None:
    (home / "config.yaml").write_text("steward:\n  enabled: true\n", encoding="utf-8")


def _cache(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    (cache / "steward").mkdir(parents=True)
    return cache


def _journal(cache: Path, *rows: dict) -> None:
    with open(cache / "steward" / "journal.jsonl", "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


@pytest.fixture()
def led(tmp_path, monkeypatch):
    home = tmp_path / "ledger"
    home.mkdir()
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    return home


# ------------------------------------------------------------------ hook


def _hook(tmp_path: Path, name: str, payload: dict) -> str:
    (tmp_path / name).mkdir()
    result = _run_hook(tmp_path / name, payload)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _steward_payload(**extra) -> dict:
    payload = _base_payload()
    payload.update(total_pending=19, oldest_days=55, escalate=True, steward_enabled=True)
    payload.update(extra)
    return payload


def test_hook_is_quiet_while_the_steward_keeps_up(tmp_path):
    # positive control first: the same payload, stale, does print.
    stale = _hook(tmp_path, "a", _steward_payload(steward_stale=True))
    assert "the steward has not finished a run in over 2 days" in stale
    assert "19 lesson(s) queued" in stale

    quiet = _hook(tmp_path, "b", _steward_payload(steward_stale=False))
    assert quiet == ""


def test_hook_prints_the_hold_and_the_stranded_count(tmp_path):
    out = _hook(
        tmp_path, "a", _steward_payload(steward_hold="OAuth session expired", stranded_count=2)
    )
    assert "the steward is held — OAuth session expired" in out
    assert "2 queued lesson(s) the steward never selects" in out
    assert "--selftest" in out
    # a zero census is silent
    assert _hook(tmp_path, "b", _steward_payload(stranded_count=0)) == ""


def test_hook_with_the_steward_off_prints_todays_lines_byte_for_byte(tmp_path):
    payload = _base_payload()
    payload.update(total_pending=19, oldest_days=55, escalate=True, steward_enabled=False)
    expected = (
        "📥 self-learn: 19 pending, oldest 55d — /self-learn:review\n"
        "🔺 self-learn: backlog over threshold (≥5 pending or oldest >7d) — a review session is due\n"
    )
    assert _hook(tmp_path, "a", payload) == expected
    # an older CLI that sends no steward field behaves the same
    del payload["steward_enabled"]
    assert _hook(tmp_path, "b", payload) == expected


def test_hook_keeps_the_worker_alarm_only_with_the_steward_off(tmp_path):
    payload = _base_payload()
    payload.update(total_pending=1, staleness_alarm=True, unanalyzed_total=1)
    off = _hook(tmp_path, "a", payload)
    assert "await analysis" in off
    payload["steward_enabled"] = True
    assert _hook(tmp_path, "b", payload) == ""


# ------------------------------------------------------------ nudge_fields


def test_steward_off_reports_only_that(led, tmp_path):
    cache = _cache(tmp_path)
    assert steward.nudge_fields(led, cache, 19, now=NOW) == {"steward_enabled": False}


def test_steward_stale_is_measured_from_the_completed_run(led, tmp_path):
    _enable(led)
    cache = _cache(tmp_path)
    marker = cache / "steward" / "steward.last-run"
    # A recent ATTEMPT must not count: only the completed-run marker does.
    _journal(cache, {"ts": _iso(NOW - HOUR), "run_id": "r1", "status": "partial"})
    marker.write_text(_iso(NOW - 49 * HOUR) + "\n", encoding="utf-8")
    assert steward.nudge_fields(led, cache, 19, now=NOW)["steward_stale"] is True
    marker.write_text(_iso(NOW - 47 * HOUR) + "\n", encoding="utf-8")
    assert steward.nudge_fields(led, cache, 19, now=NOW)["steward_stale"] is False


def test_steward_stale_needs_a_queue_and_a_marker(led, tmp_path):
    _enable(led)
    cache = _cache(tmp_path)
    # never completed, lessons waiting: stale
    assert steward.nudge_fields(led, cache, 3, now=NOW)["steward_stale"] is True
    # nothing waiting: nothing to be behind on
    assert steward.nudge_fields(led, cache, 0, now=NOW)["steward_stale"] is False


def test_fast_probe_creates_nothing(led, tmp_path):
    _enable(led)
    cache = tmp_path / "cache-absent"
    fields = steward.nudge_fields(led, cache, 1, now=NOW)
    assert fields["steward_enabled"] is True
    assert not cache.exists()


def test_hold_is_the_newest_run_outcome(led, tmp_path):
    _enable(led)
    cache = _cache(tmp_path)
    _journal(
        cache,
        {"ts": "t1", "run_id": "r1", "status": "held-environment", "cause": "OAuth session expired"},
        {"ts": "t2", "run_id": "r1", "status": "partial", "held": "OAuth session expired"},
        {"ts": "t3", "run_id": "r1", "status": "model-log"},
    )
    assert steward.nudge_fields(led, cache, 1, now=NOW)["steward_hold"] == "OAuth session expired"
    # a rehearsal after it is not the steward's state
    _journal(cache, {"ts": "t4", "run_id": "r2", "status": "applied", "dry_run": True})
    assert steward.nudge_fields(led, cache, 1, now=NOW)["steward_hold"] == "OAuth session expired"
    # a later real run that did not hold clears it
    _journal(cache, {"ts": "t5", "run_id": "r3", "status": "applied", "decided": 3})
    assert "steward_hold" not in steward.nudge_fields(led, cache, 1, now=NOW)


def test_stranded_count_is_absent_unless_known(led, tmp_path):
    _enable(led)
    cache = _cache(tmp_path)
    assert "stranded_count" not in steward.nudge_fields(led, cache, 1, now=NOW)
    path = cache / "steward" / "stranded.json"
    path.write_text(json.dumps({"stranded": [{"id": "lrn-1"}, {"id": "lrn-2"}]}), encoding="utf-8")
    assert steward.nudge_fields(led, cache, 1, now=NOW)["stranded_count"] == 2
    path.write_text("[]", encoding="utf-8")
    assert steward.nudge_fields(led, cache, 1, now=NOW)["stranded_count"] == 0
    path.write_text("not json", encoding="utf-8")
    assert "stranded_count" not in steward.nudge_fields(led, cache, 1, now=NOW)


# ------------------------------------------------------------------ worker


def test_escalation_is_silent_while_the_steward_owns_the_queue(env, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(worker, "_notify", sent.append)
    # control: steward off, over threshold -> escalates and touches the marker
    assert worker._maybe_escalate(env.home, worker.ESCALATE_PENDING, []) is True
    assert len(sent) == 1 and "backlog needs attention" in sent[0]
    marker = worker._p("worker.last-escalated")
    marker.unlink()
    # steward on: no popup, no marker
    _enable(env.home)
    assert worker._maybe_escalate(env.home, worker.ESCALATE_PENDING, []) is False
    assert len(sent) == 1
    assert not marker.exists()


def test_proposals_popup_follows_the_owner(env, sdk_fake_worker, notify_shim, monkeypatch):
    monkeypatch.delenv("SELF_LEARN_NO_NOTIFY", raising=False)
    _enable(env.home)
    rid = seed_pending(env)
    monkeypatch.setenv("CLAUDE_SHIM_SCRIPT", shim_writes(env, rid))
    worker.run(env.home)
    events = (worker.cache_dir() / "events.jsonl").read_text(encoding="utf-8")
    assert '"proposals"' in events  # the run landed a proposal (positive control)
    time.sleep(0.5)  # the helper is spawned detached: give it the time a popup would take
    assert not notify_shim["log"].exists()


# ------------------------------------------------------------ parked wording


@pytest.mark.parametrize(
    ("kinds", "person"),
    [(["needs-person"], True), (["bad-line", "needs-person"], True), (["bad-line"], False)],
)
def test_parked_notice_says_a_person_only_for_needs_person(led, monkeypatch, kinds, person):
    sent: list[str] = []
    monkeypatch.setattr(overseer_notify, "send", lambda h, cue, summary, ids: sent.append(summary))
    steward._notify_parked_now(led, "run-1", [("lrn-1", k) for k in kinds])
    (summary,) = sent
    assert ("a person must fix" in summary) is person
    assert ("decides them on its next run" in summary) is (not person)
