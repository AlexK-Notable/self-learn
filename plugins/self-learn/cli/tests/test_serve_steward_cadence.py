"""S-NEXT-cadence, part 1: the steward runs once a night after the mine, and a
run that failed or was held is retried after two hours.

The case (interventions survey 2026-10-31, §4): run `run-c5fa4e3c0a78` was
held at 22:07 PDT on 10-30 by an expired login; the user logged in again
about 22:30, and nothing retried for 20 hours, because `steward.cooldown_secs`
(72000 s) applied to the unfinished run too. The same rolling 20-hour cooldown
made every run start about four hours earlier than the one before. The
overseer already retried its unfinished work after two hours (13 §5).

Every scenario runs on a scratch home under pytest's tmpdir, with the
committed-state readers monkeypatched (no git, no model). Times are epochs;
the mine target is pinned so the slot does not depend on the clock the test
runs at.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from self_learn import serve, steward
from self_learn.invocation import failure_class

#: 2027-01-15, an arbitrary fixed instant; every time below is relative to it.
NOW = 1_800_000_000.0
HOUR = 3600.0


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def _home(tmp_path: Path, monkeypatch, *, cooldown: int | None = None) -> tuple[Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    lines = "steward:\n  enabled: true\n"
    if cooldown is not None:
        lines += f"  cooldown_secs: {cooldown}\n"
    (home / "config.yaml").write_text(lines, encoding="utf-8")
    cache = tmp_path / "cache"
    (cache / "steward").mkdir(parents=True)
    clear = type("IntentState", (), {"stopped": []})()
    monkeypatch.setattr(serve.intents, "classify_status", lambda actual: clear)
    monkeypatch.setattr(serve.steward, "_reconsider_proposals", lambda actual: ([], {}))
    monkeypatch.setattr(serve.steward, "_suspected_violation_inputs", lambda actual: [])
    monkeypatch.setattr(serve.steward, "_premise_moved_inputs", lambda actual, manifests=None: [])
    monkeypatch.setattr(serve, "_premise_extract_waiting", lambda actual: False)
    monkeypatch.setattr(serve, "_release_epochs", lambda actual, lessons: {})
    return home, cache


def _journal(cache: Path, *rows: dict) -> None:
    (cache / "steward" / "journal.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def _unfinished(monkeypatch, last_attempt: float) -> None:
    monkeypatch.setattr(serve.steward, "committed_manifests", lambda actual: [{
        "run_id": "run-held", "status": "unfinished",
        "started_at": _iso(last_attempt - 10 * HOUR), "last_attempt_at": _iso(last_attempt),
    }])
    monkeypatch.setattr(serve, "_eligible_input_paths", lambda actual: [])


def _night(monkeypatch, *, target: float, mine_finished: float | None) -> None:
    """Today's mine target (and so yesterday's, a day before it) and when
    the mine last finished."""
    monkeypatch.setattr(serve, "_today_mine_target", lambda cache, now: target)
    monkeypatch.setattr(serve, "_day_target", lambda now, days: target + days * 24 * HOUR)
    monkeypatch.setattr(
        serve.miner, "last_run_iso",
        lambda: None if mine_finished is None else _iso(mine_finished),
    )


def _completed(monkeypatch, *starts: float, last_run: float | None = None) -> None:
    monkeypatch.setattr(serve.steward, "committed_manifests", lambda actual: [
        {"run_id": f"run-{n}", "status": "complete", "started_at": _iso(start)}
        for n, start in enumerate(starts)
    ])
    finished = last_run if last_run is not None else max(starts) + HOUR
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: _iso(finished))


def _one_new_lesson(monkeypatch, tmp_path: Path, committed: float) -> None:
    path = tmp_path / "home" / "lrn-0cad0001.md"
    monkeypatch.setattr(serve, "_eligible_input_paths", lambda actual: [path])
    monkeypatch.setattr(serve, "_input_commit_epoch", lambda actual, p: committed)


# ------------------------------------------------- 1. unfinished: 2 h retry


def test_an_unfinished_run_is_due_two_hours_and_a_second_after_its_attempt(tmp_path, monkeypatch):
    """Would catch: the 20-hour (now 12-hour) `steward.cooldown_secs` still
    applied to an unfinished run, so a held run waits a day after the user
    logged in again."""
    home, cache = _home(tmp_path, monkeypatch)
    attempt = NOW - steward.RETRY_SECS - 1
    _unfinished(monkeypatch, attempt)
    _journal(cache, {"ts": _iso(attempt), "run_id": "run-held", "status": "attempt-start"})
    assert serve._steward_is_due(home, cache, NOW) is True
    # the same run a minute inside its retry interval waits (the control)
    assert serve._steward_is_due(home, cache, attempt + steward.RETRY_SECS - 60) is False


def test_an_unfinished_run_one_hour_after_its_attempt_is_not_due(tmp_path, monkeypatch):
    """The cache attempt journal is the clock: its attempt an hour ago holds
    the run although the committed stamp (an older attempt) is three hours
    old. Would catch: the journal check dropped, so a run is retried on the
    committed stamp alone, or on every tick."""
    home, cache = _home(tmp_path, monkeypatch)
    _unfinished(monkeypatch, NOW - 3 * HOUR)
    _journal(cache, {"ts": _iso(NOW - HOUR), "run_id": "run-held", "status": "attempt-start"})
    assert serve._steward_is_due(home, cache, NOW) is False
    # control: the same state an hour and a second later is due
    assert serve._steward_is_due(home, cache, NOW + HOUR + 1) is True


def test_with_the_cache_lost_the_committed_attempt_is_the_retry_clock(tmp_path, monkeypatch):
    home, cache = _home(tmp_path, monkeypatch)
    _unfinished(monkeypatch, NOW - HOUR)
    assert serve._steward_is_due(home, cache, NOW) is False
    assert serve._steward_is_due(home, cache, NOW - HOUR + steward.RETRY_SECS) is True


def test_the_retry_interval_is_the_miners_attempt_cooldown():
    assert steward.RETRY_SECS == serve.miner.ATTEMPT_COOLDOWN_SECS


# ---------------------------------------------------- 2. new work: nightly


def test_new_work_is_due_after_the_nights_mine_not_twenty_hours_after_the_last_run(
    tmp_path, monkeypatch
):
    """A run that started 13 h ago and finished 6 h ago (it was retried), and
    a lesson mined since: due once tonight's mine has finished. Would catch:
    the old rule (last run + cooldown), which holds it for 6 more hours and
    makes every run drift earlier."""
    home, cache = _home(tmp_path, monkeypatch)
    _completed(monkeypatch, NOW - 13 * HOUR, last_run=NOW - 6 * HOUR)
    _one_new_lesson(monkeypatch, tmp_path, committed=NOW - HOUR)
    # positive control: before the mine has finished (and inside the grace
    # after its target) tonight's slot is not open and the last run took
    # yesterday's, so nothing is due
    _night(monkeypatch, target=NOW - 2 * HOUR, mine_finished=NOW - 26 * HOUR)
    assert serve._steward_is_due(home, cache, NOW) is False
    _night(monkeypatch, target=NOW - 2 * HOUR, mine_finished=NOW - HOUR)
    assert serve._steward_is_due(home, cache, NOW) is True


def test_a_mine_that_never_finishes_opens_the_slot_three_hours_after_its_target(
    tmp_path, monkeypatch
):
    home, cache = _home(tmp_path, monkeypatch)
    # the last run took yesterday's slot (its target was 27 h ago)
    _completed(monkeypatch, NOW - 26 * HOUR)
    _one_new_lesson(monkeypatch, tmp_path, committed=NOW - 20 * HOUR)
    target = NOW - serve.STEWARD_MINE_GRACE_SECS
    _night(monkeypatch, target=target, mine_finished=None)
    assert serve._steward_is_due(home, cache, target + serve.STEWARD_MINE_GRACE_SECS - 1) is False
    assert serve._steward_is_due(home, cache, target + serve.STEWARD_MINE_GRACE_SECS) is True


def test_a_run_tonight_takes_the_slot_until_tomorrows_mine(tmp_path, monkeypatch):
    """No second run the same night, whatever arrives: a lesson mined after
    tonight's run waits for tomorrow's slot. Control: the same lesson with
    the last run before tonight's target is due."""
    home, cache = _home(tmp_path, monkeypatch)
    _night(monkeypatch, target=NOW - 20 * HOUR, mine_finished=NOW - 19 * HOUR)
    _one_new_lesson(monkeypatch, tmp_path, committed=NOW - HOUR)
    _completed(monkeypatch, NOW - 21 * HOUR)
    assert serve._steward_is_due(home, cache, NOW) is True  # control
    _completed(monkeypatch, NOW - 19 * HOUR)
    assert serve._steward_is_due(home, cache, NOW) is False


def test_a_second_start_waits_for_the_minimum_gap(tmp_path, monkeypatch):
    """A hand run at 5 h ago (before tonight's slot opened at 1 h ago): the
    night's run waits until `cooldown_secs` after that start. Would catch:
    the minimum gap deleted, so two runs start hours apart."""
    home, cache = _home(tmp_path, monkeypatch)
    _night(monkeypatch, target=NOW - 2 * HOUR, mine_finished=NOW - HOUR)
    _one_new_lesson(monkeypatch, tmp_path, committed=NOW - 30 * 60)
    _completed(monkeypatch, NOW - 5 * HOUR)
    gap = 43200
    assert serve._steward_is_due(home, cache, NOW) is False
    assert serve._steward_is_due(home, cache, NOW - 5 * HOUR + gap) is True
    # the gap is the setting, not a constant
    (home / "config.yaml").write_text(
        "steward:\n  enabled: true\n  cooldown_secs: 3600\n", encoding="utf-8"
    )
    assert serve._steward_is_due(home, cache, NOW) is True


def test_a_deferral_that_came_due_since_the_last_run_is_new_work(tmp_path, monkeypatch):
    """An eligible lesson whose record is older than the last run, and whose
    deferral came due after it: due. Control: the same lesson with no
    deferral is not new work."""
    home, cache = _home(tmp_path, monkeypatch)
    _night(monkeypatch, target=NOW - 2 * HOUR, mine_finished=NOW - HOUR)
    _completed(monkeypatch, NOW - 25 * HOUR)
    _one_new_lesson(monkeypatch, tmp_path, committed=NOW - 40 * HOUR)
    monkeypatch.setattr(serve, "_deferral_due_epochs", lambda paths, now: {})
    assert serve._steward_is_due(home, cache, NOW) is False  # control
    monkeypatch.setattr(
        serve, "_deferral_due_epochs", lambda paths, now: {"lrn-0cad0001": NOW - 10 * HOUR}
    )
    assert serve._steward_is_due(home, cache, NOW) is True


# -------------------------------------------------------- 3. the preview


def test_the_heartbeat_preview_names_the_instant_the_unfinished_run_becomes_due(
    tmp_path, monkeypatch
):
    """Would catch: the preview reading `steward.last-run` (the last
    COMPLETED run) and the cooldown, which printed "now" for a run the
    predicate held, or a time 20 h off."""
    home, cache = _home(tmp_path, monkeypatch)
    attempt = NOW - HOUR
    _unfinished(monkeypatch, attempt)
    _journal(cache, {"ts": _iso(attempt), "run_id": "run-held", "status": "attempt-start"})
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: _iso(NOW - 30 * HOUR))
    monkeypatch.setattr(serve, "_today_mine_target", lambda cache_, now: now + 60)

    preview = serve._describe_next(home, cache, NOW)
    steward_at = preview.split("steward at ", 1)[1].split(" ", 1)[0]
    instant = datetime.fromisoformat(steward_at).timestamp()
    assert instant == attempt + steward.RETRY_SECS
    assert "retry" in preview
    # the predicate agrees, to the second
    assert serve._steward_is_due(home, cache, instant - 1) is False
    assert serve._steward_is_due(home, cache, instant) is True


def test_the_preview_after_a_completed_run_names_the_next_nights_slot(tmp_path, monkeypatch):
    home, cache = _home(tmp_path, monkeypatch)
    start = NOW - HOUR
    _journal(
        cache,
        {"ts": _iso(start), "run_id": "run-done", "status": "attempt-start"},
        {"ts": _iso(start + 600), "run_id": "run-done", "status": "applied"},
    )
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: _iso(start + 600))
    target = NOW - 2 * HOUR
    monkeypatch.setattr(serve, "_today_mine_target", lambda cache_, now: target)
    monkeypatch.setattr(serve.miner, "last_run_iso", lambda: _iso(target + 600))
    monkeypatch.setattr(serve, "_target_for", lambda when: when - 10 * HOUR)

    preview = serve._describe_next(home, cache, NOW)
    steward_at = preview.split("steward at ", 1)[1].split(" ", 1)[0]
    instant = datetime.fromisoformat(steward_at).timestamp()
    # tomorrow's target (noon tomorrow minus 10 h in this stub), never
    # `last run + 20 h`, and never before the minimum gap
    assert instant > NOW
    assert instant >= start + 43200
    assert "after the night's mine" in preview


# ------------------------------------------------------- 4. the hold notice


def test_the_hold_notice_names_the_retry_time_and_the_login_fix():
    """Would catch: the old words ("it retries on its next attempt"), which
    named neither when (20 h away) nor what to type."""
    cause = "Failed to authenticate: OAuth session expired and could not be refreshed"
    text = steward.hold_notice_text("run-c5fa4e3c0a78", cause, now=NOW)
    retry = datetime.fromtimestamp(NOW + steward.RETRY_SECS).astimezone()
    assert retry.strftime("%Y-%m-%d %H:%M") in text
    assert "every 2 h while the cause lasts" in text
    assert "`claude` and `/login`" in text
    assert cause in text
    # another environment cause keeps its cause line and no login advice
    other = steward.hold_notice_text("run-x", "model not found", now=NOW)
    assert "model not found" in other and "/login" not in other
    assert retry.strftime("%Y-%m-%d %H:%M") in other


def test_the_login_class_is_the_auth_half_of_the_environment_class():
    for text in (
        "Failed to authenticate: OAuth session expired and could not be refreshed",
        "API Error: 401 authentication_error",
        "Not logged in · Please run /login",
    ):
        assert failure_class.is_login_failure(text), text
        assert failure_class.classify("exit", text) == "environment", text
    for text in ("model not found", "credit balance is too low", "overloaded"):
        assert not failure_class.is_login_failure(text), text


def test_the_runner_sends_the_new_words_once(tmp_path, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(
        steward.overseer_notify, "send", lambda home, cue, summary, ids: sent.append(summary)
    )
    steward._notify_environment_hold(tmp_path, "run-x", "Failed to authenticate: OAuth expired")
    assert len(sent) == 1
    assert "It tries again after" in sent[0] and "/login" in sent[0]
