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
from support import make_env

from self_learn import steward, worker
from self_learn.overseer import notify as overseer_notify

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
    assert "the steward has not finished a run in over 48 hours" in stale
    assert "19 lesson(s) queued" in stale

    quiet = _hook(tmp_path, "b", _steward_payload(steward_stale=False))
    assert quiet == ""


def test_hook_prints_the_hold_and_the_stranded_count(tmp_path):
    out = _hook(
        tmp_path, "a", _steward_payload(steward_hold="OAuth session expired", stranded_count=2)
    )
    assert "the steward is held — OAuth session expired\n" in out
    fixed = _hook(
        tmp_path, "c",
        _steward_payload(steward_hold="OAuth session expired", steward_hold_fix="run `claude`, then `/login`"),
    )
    assert "held — OAuth session expired; run `claude`, then `/login`" in fixed
    hours = _hook(tmp_path, "d", _steward_payload(steward_stale=True, steward_stale_hours=72))
    assert "in over 72 hours" in hours
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


def test_hold_survives_the_rows_the_steward_writes_after_its_closing_row(led, tmp_path):
    _enable(led)
    cache = _cache(tmp_path)
    closing = {"ts": "t2", "run_id": "r1", "status": "partial", "decided": 0, "calls": 1,
               "held": "Failed to authenticate: OAuth session expired and could not be refreshed"}
    # the real order of a held run on a ledger with a remote (live journal 10-31)
    _journal(
        cache,
        {"ts": "t0", "run_id": "r1", "status": "attempt-start"},
        {"ts": "t1", "run_id": "r1", "status": "held-environment", "cause": closing["held"]},
        {"ts": "t1", "run_id": "r1", "status": "model-log"},
        closing,
        {"ts": "t3", "run_id": "r1", "status": "push", "ok": True},
    )
    fields = steward.nudge_fields(led, cache, 1, now=NOW)
    assert fields["steward_hold"] == closing["held"]
    assert fields["steward_hold_fix"] == "run `claude`, then `/login`"
    _journal(cache, {"ts": "t4", "run_id": "r1", "status": "recompile", "ok": True})
    assert steward.nudge_fields(led, cache, 1, now=NOW)["steward_hold"] == closing["held"]


def test_an_abandoned_row_is_not_a_hold_cause(led, tmp_path):
    _enable(led)
    cache = _cache(tmp_path)
    _journal(
        cache,
        {"ts": "t1", "run_id": "r1", "status": "applied", "decided": 2},
        {"ts": "t2", "run_id": "r2", "status": "abandoned", "held": ["lrn-1"]},
    )
    assert "steward_hold" not in steward.nudge_fields(led, cache, 1, now=NOW)


def test_hold_fix_names_the_step_for_the_known_environment_causes():
    assert steward.hold_fix("Failed to authenticate: OAuth session expired") == "run `claude`, then `/login`"
    assert "claude update" in steward.hold_fix("Please update Claude Code")
    assert steward.hold_fix("something odd") is None


def test_stranded_count_is_absent_unless_known(led, tmp_path):
    _enable(led)
    cache = _cache(tmp_path)
    assert "stranded_count" not in steward.nudge_fields(led, cache, 1, now=NOW)
    path = cache / "steward" / "stranded.json"
    # the census writer's shape (serve._write_stranded)
    path.write_text(json.dumps({"at": "t", "count": 2, "lessons": [{"id": "lrn-1"}, {"id": "lrn-2"}]}), encoding="utf-8")
    assert steward.nudge_fields(led, cache, 1, now=NOW)["stranded_count"] == 2
    path.write_text(json.dumps({"at": "t", "count": 0, "lessons": []}), encoding="utf-8")
    assert steward.nudge_fields(led, cache, 1, now=NOW)["stranded_count"] == 0
    path.write_text("not json", encoding="utf-8")
    assert "stranded_count" not in steward.nudge_fields(led, cache, 1, now=NOW)
    path.write_text(json.dumps({"stranded": [{"id": "x"}]}), encoding="utf-8")
    assert "stranded_count" not in steward.nudge_fields(led, cache, 1, now=NOW)


def test_a_queue_of_only_overseer_held_lessons_is_not_a_stale_steward(led, tmp_path, monkeypatch):
    _enable(led)
    cache = _cache(tmp_path)
    marker = cache / "steward" / "steward.last-run"
    marker.write_text(_iso(NOW - 72 * HOUR) + "\n", encoding="utf-8")
    queued = ["a", "b", "c"]
    # control: nothing held, old marker -> stale
    assert steward.nudge_fields(led, cache, 3, queued_ids=queued, now=NOW)["steward_stale"] is True
    monkeypatch.setattr(steward.cases, "held_lessons", lambda home: {"a": [], "b": [], "c": []})
    assert steward.nudge_fields(led, cache, 3, queued_ids=queued, now=NOW)["steward_stale"] is False
    # a queued lesson beyond the held ones is the steward's: stale again
    assert steward.nudge_fields(led, cache, 4, queued_ids=[*queued, "d"], now=NOW)["steward_stale"] is True


def test_held_lessons_that_are_not_queued_do_not_hide_a_stale_steward(led, tmp_path, monkeypatch):
    """Parked cases also name placed (resolved) lessons; those are not in the queue."""
    _enable(led)
    cache = _cache(tmp_path)
    (cache / "steward" / "steward.last-run").write_text(_iso(NOW - 72 * HOUR) + "\n", encoding="utf-8")
    monkeypatch.setattr(steward.cases, "held_lessons", lambda home: {"r1": [], "r2": [], "r3": []})
    fields = steward.nudge_fields(led, cache, 3, queued_ids=["q1", "q2", "q3"], now=NOW)
    assert fields["steward_stale"] is True


def _seed_queued(home: Path, rid: str) -> None:
    from self_learn.ledger_ops import create_record
    from support import make_behavior

    create_record(home, make_behavior(scope="skill:s", record_id=rid))


def test_fast_status_reports_queued_ids_without_changing_the_payload(ledger):
    _seed_queued(ledger, "lrn-0000f001")
    ids: list[str] = []
    with_ids = worker.fast_status(ledger, ids)
    assert with_ids["total_pending"] == 1  # positive control: the seeded record is queued
    assert with_ids == worker.fast_status(ledger)
    assert ids == ["lrn-0000f001"]
    # mutation: `queued_ids.append(str(fm["id"]))` -> `pass` leaves ids empty


def test_status_fast_cli_hands_the_queued_ids_to_the_stale_check(ledger, tmp_path, monkeypatch, capsys):
    """Mutation: drop `queued_ids=queued_ids` from the `status --fast` call ->
    the held lesson is not recognised and `steward_stale` stays true."""
    from self_learn import cli, serve

    _enable(ledger)
    _seed_queued(ledger, "lrn-0000f002")
    marker = serve.cache_dir_readonly(ledger) / "steward" / "steward.last-run"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_iso(time.time() - 72 * HOUR) + "\n", encoding="utf-8")

    def fast() -> dict:
        assert cli.main(["status", "--json", "--fast"]) == 0
        return json.loads(capsys.readouterr().out)

    # control first: nothing held, an old marker, one queued lesson -> stale
    payload = fast()
    assert payload["total_pending"] == 1 and payload["steward_stale"] is True
    monkeypatch.setattr(steward.cases, "held_lessons", lambda home: {"lrn-0000f002": []})
    assert fast()["steward_stale"] is False


def test_hold_fix_prefers_model_not_found_over_a_trailing_update_hint():
    assert steward.hold_fix("model not found; please update your model setting") == "check the configured model name"
    assert steward.hold_fix("this CLI version is unsupported") == "update Claude Code (`claude update`)"


# ------------------------------------------------------------------ worker


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    home = make_env(tmp_path).ledger
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    return home


def test_escalation_is_silent_while_the_steward_owns_the_queue(ledger, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(worker, "_notify", sent.append)
    # control: steward off, over threshold -> escalates and touches the marker
    assert worker._maybe_escalate(ledger, worker.ESCALATE_PENDING, []) is True
    assert len(sent) == 1 and "backlog needs attention" in sent[0]
    marker = worker._p("worker.last-escalated")
    marker.unlink()
    # steward on: no popup, no marker
    _enable(ledger)
    assert worker._maybe_escalate(ledger, worker.ESCALATE_PENDING, []) is False
    assert len(sent) == 1
    assert not marker.exists()


def test_proposals_popup_follows_the_owner(ledger, monkeypatch):
    sent: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(worker, "_notify_with_ids", lambda line, ids: sent.append((line, ids)))
    worker._notify_proposals(ledger, "line", ["lrn-1"])  # control: steward off
    assert sent == [("line", ["lrn-1"])]
    _enable(ledger)
    worker._notify_proposals(ledger, "line", ["lrn-2"])
    assert sent == [("line", ["lrn-1"])]


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
