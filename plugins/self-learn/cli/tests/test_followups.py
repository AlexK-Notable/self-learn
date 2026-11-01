"""S-NEXT-followups: four loose ends of the 2026-10-31b integration.

1. One cause-to-fix map for a steward hold (`failure_class.hold_fix`).
2. The stranded.json path and reader spelled once (`steward`).
3. The pending hook's overseer line no longer says "interpretation questions".
4. The heartbeat's steward preview knows overdue premise reviews alone make
   the steward due.

No ledger, no model call. Each absence assertion has a positive control first.
"""

from __future__ import annotations

from pathlib import Path

from self_learn import serve, steward
from self_learn.invocation import failure_class

from test_pending_hook import _base_payload, _run_hook
from test_serve_steward_cadence import (
    NOW,
    _completed_run_journal,
    _home,
    _steward_preview,
    _tonight_done,
)

LOGIN = "Failed to authenticate: OAuth session expired and could not be refreshed"
CREDIT = "Your credit balance is too low to access the Anthropic API"


def _fix_sentence(text: str) -> str:
    """The fix a notification names: the words after its last ': ' up to the
    closing full stop."""
    return text.rsplit(": ", 1)[1].rstrip(".")


# ----------------------------------------------------- 1. one hold-fix map


def test_both_surfaces_give_the_same_fix_for_a_login_and_for_a_non_login_hold():
    for cause in (LOGIN, CREDIT):
        fix = steward.hold_fix(cause)
        assert fix is not None  # positive control: the cause has a fix
        notice = steward.hold_notice_text("run-x", cause, now=1.0)
        assert fix in notice
        assert _fix_sentence(notice) == fix
        assert failure_class.hold_fix(cause) == fix
    # the two are different causes with different fixes (the control)
    assert steward.hold_fix(LOGIN) != steward.hold_fix(CREDIT)
    # no fix, no fix line, on either surface
    assert steward.hold_fix("something odd") is None
    assert "To fix it" not in steward.hold_notice_text("run-x", "something odd", now=1.0)


def test_the_steward_holds_no_fix_patterns_of_its_own():
    assert not hasattr(steward, "_HOLD_FIXES")


# ----------------------------------------------- 2. stranded.json spelled once


class _Row:
    def as_dict(self) -> dict:
        return {"record": "lrn-ca0e00a1"}


def test_a_census_written_by_serve_is_counted_by_the_steward(tmp_path: Path):
    cache = tmp_path / "cache"
    assert steward._stranded_count(cache) is None  # positive control: nothing yet
    serve._write_stranded(cache, [_Row(), _Row()], "2026-10-31T00:00:00Z")  # type: ignore[list-item]
    assert (cache / "steward" / "stranded.json").is_file()
    assert steward._stranded_count(cache) == 2
    assert serve.read_stranded(cache) == steward.read_stranded(cache)
    assert serve.stranded_path(cache) == steward.stranded_path(cache)


# ------------------------------------------------------------- 3. the hook


def test_the_hook_does_not_call_legacy_asks_interpretation_questions(tmp_path: Path):
    payload = _base_payload()
    payload["overseer_open_questions"] = 3
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0, result.stderr
    assert "overseer has 3 older question(s) still waiting" in result.stdout  # control
    assert "interpretation" not in result.stdout


# ------------------------------------------------- 4. the rotation preview


def test_the_preview_names_overdue_reviews_and_only_when_one_is_overdue(tmp_path, monkeypatch):
    home, cache = _home(tmp_path, monkeypatch)
    start = NOW - 3600.0
    end = _completed_run_journal(cache, start)
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: _iso_of(end))
    _tonight_done(monkeypatch)
    monkeypatch.setattr(serve, "_rotation_on", lambda actual: True)

    # positive control: with no review overdue the generic reason stands
    monkeypatch.setattr(serve.steward, "_premise_review_overdue", lambda actual, **kw: False)
    when_none, why_none = _steward_preview(home, cache)
    assert why_none == "after the night's mine, when there is work"

    monkeypatch.setattr(serve.steward, "_premise_review_overdue", lambda actual, **kw: True)
    when_due, why_due = _steward_preview(home, cache)
    assert why_due == "after the night's mine, for its overdue premise reviews"
    assert when_due == when_none  # the same gates decide the instant

    # the rotation off: an overdue-looking review is not asked about
    monkeypatch.setattr(serve, "_rotation_on", lambda actual: False)
    assert _steward_preview(home, cache)[1] == "after the night's mine, when there is work"


def _iso_of(epoch: float) -> str:
    from test_serve_steward_cadence import _iso

    return _iso(epoch)
