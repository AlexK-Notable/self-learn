"""S-120: four loose ends of the 2026-10-31b integration.

1. One cause-to-fix map for a steward hold (`failure_class.hold_fix`).
2. The stranded.json path and reader spelled once (`steward`).
3. The pending hook's overseer line no longer says "interpretation questions".
4. The heartbeat's steward preview knows overdue premise reviews alone make
   the steward due, from a cached answer only (fix round 1, gate r1 MAJOR 1).

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


def test_a_rejected_api_key_and_a_403_keep_the_login_step(tmp_path: Path):
    """Gate r1 MINOR 1: the old hook map gave both the login step; the
    unified map had dropped it. A rejected key also names an exported
    ANTHROPIC_API_KEY. Mutation checked: removing either `_OTHER_FIXES` row
    fails this test."""
    key = "Invalid API key · Fix external API key: invalid x-api-key"
    forbidden = "API Error: 403 {\"type\":\"error\",\"error\":{\"type\":\"permission_error\"}}"
    assert failure_class.classify("error", key) == "environment"  # control: both hold the steward
    assert failure_class.classify("error", forbidden) == "environment"
    key_fix = failure_class.hold_fix(key)
    assert key_fix is not None and key_fix.startswith(failure_class.LOGIN_FIX)
    assert "ANTHROPIC_API_KEY" in key_fix
    assert failure_class.hold_fix(forbidden) == failure_class.LOGIN_FIX
    for cause, fix in ((key, key_fix), (forbidden, failure_class.LOGIN_FIX)):
        assert steward.hold_fix(cause) == fix
        assert steward.hold_notice_text("run-x", cause, now=1.0).endswith(f"To fix it: {fix}.")
    # The API's own wording is a login failure too: the key hint still shows.
    api_words = 'authentication_error: {"message":"invalid x-api-key"}'
    assert failure_class.is_login_failure(api_words)  # control
    assert failure_class.hold_fix(api_words) == key_fix
    assert steward.hold_notice_text("run-x", api_words, now=1.0).endswith(
        f"The login no longer works: {key_fix}."
    )


def test_an_old_claude_code_gets_the_update_step():
    """Gate r1 NIT 1: the classifier's own "is too old". Mutation checked:
    dropping `too old` from the update pattern fails this test."""
    cause = "Claude Code 1.0.3 is too old for this model"
    assert failure_class.classify("error", cause) == "environment"  # control
    assert failure_class.hold_fix(cause) == "update Claude Code (`claude update`)"


def test_the_login_lead_says_what_the_cause_says():
    """Gate r1 NIT 4: "has expired" only for an expired login. Mutation
    checked: making `_hold_fix_lead` answer "The login has expired" for every
    login failure fails this test."""
    expired = steward.hold_notice_text("run-x", LOGIN, now=1.0)
    assert expired.endswith(f"The login has expired: {failure_class.LOGIN_FIX}.")  # control
    absent = steward.hold_notice_text("run-x", "Not logged in · Please run /login", now=1.0)
    assert absent.endswith(f"Claude Code is not logged in: {failure_class.LOGIN_FIX}.")
    assert "expired" not in absent
    other = steward.hold_notice_text("run-x", "authentication_error: invalid bearer token", now=1.0)
    assert other.endswith(f"The login no longer works: {failure_class.LOGIN_FIX}.")


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
    # Gate r1 NIT 2: the same objects, not two copies that agree today.
    assert serve.read_stranded is steward.read_stranded
    assert serve.stranded_path is steward.stranded_path
    assert serve.STRANDED_FILENAME is steward.STRANDED_FILENAME


# ------------------------------------------------------------- 3. the hook


def test_the_hook_does_not_call_legacy_asks_interpretation_questions(tmp_path: Path):
    payload = _base_payload()
    payload["overseer_open_questions"] = 3
    result = _run_hook(tmp_path, payload)
    assert result.returncode == 0, result.stderr
    assert "overseer has 3 older question(s) still waiting" in result.stdout  # control
    assert "interpretation" not in result.stdout


# ------------------------------------------------- 4. the rotation preview


_HEAD = "ab" * 20


def _fake_head(home: Path, sha: str = _HEAD) -> None:
    """A ledger HEAD the preview can read from files (no git process)."""
    git = home / ".git"
    (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (git / "refs" / "heads" / "master").write_text(sha + "\n", encoding="utf-8")


def _preview_home(tmp_path, monkeypatch):
    home, cache = _home(tmp_path, monkeypatch)
    start = NOW - 3600.0
    end = _completed_run_journal(cache, start)
    monkeypatch.setattr(serve.steward, "last_run_iso", lambda actual: _iso_of(end))
    _tonight_done(monkeypatch)
    monkeypatch.setattr(serve, "_rotation_on", lambda actual: True)
    _fake_head(home)
    return home, cache


def _forbid_ledger_walks(monkeypatch) -> list[str]:
    """Make the expensive question and the manifest walk record and fail:
    the preview must reach neither (gate r1 MAJOR 1)."""
    calls: list[str] = []

    def overdue(*_a, **_kw):
        calls.append("_premise_review_overdue")
        raise AssertionError("the preview asked the overdue question itself")

    def manifests(*_a, **_kw):
        calls.append("committed_manifests")
        raise AssertionError("the preview walked the committed manifests")

    monkeypatch.setattr(serve.steward, "_premise_review_overdue", overdue)
    monkeypatch.setattr(serve.steward, "committed_manifests", manifests)
    return calls


def _write_cached(cache: Path, *, overdue: bool, date: str | None = None, head: str = _HEAD) -> None:
    import json

    (cache / "steward").mkdir(parents=True, exist_ok=True)
    serve._review_overdue_path(cache).write_text(json.dumps({
        "at": "x", "date": date or serve._utc_day(NOW), "head": head, "overdue": overdue,
    }), encoding="utf-8")


def test_the_preview_reads_the_cached_answer_and_never_walks_the_ledger(tmp_path, monkeypatch):
    """Gate r1 MAJOR 1: the heartbeat preview is cache-only. Positive control
    first: a cached "overdue" for today at HEAD names the overdue reason.
    Mutation checked: making `_steward_next` call
    `steward._premise_review_overdue(home)` again fails this test (the
    preview is held by the raise, and `calls` is not empty)."""
    home, cache = _preview_home(tmp_path, monkeypatch)
    calls = _forbid_ledger_walks(monkeypatch)

    _write_cached(cache, overdue=True)
    when_due, why_due = _steward_preview(home, cache)
    assert why_due == "after the night's mine, for its overdue premise reviews"

    stale_cases = {
        "missing": None,
        "not overdue": dict(overdue=False),
        "yesterday": dict(overdue=True, date="2000-01-01"),
        "another HEAD": dict(overdue=True, head="cd" * 20),
    }
    for label, kwargs in stale_cases.items():
        if kwargs is None:
            serve._review_overdue_path(cache).unlink()
        else:
            _write_cached(cache, **kwargs)
        when, why = _steward_preview(home, cache)
        assert why == "after the night's mine, when there is work", label
        assert when == when_due, label  # the same gates decide the instant

    # the rotation off: even a fresh "overdue" is not named
    _write_cached(cache, overdue=True)
    monkeypatch.setattr(serve, "_rotation_on", lambda actual: False)
    assert _steward_preview(home, cache)[1] == "after the night's mine, when there is work"
    assert calls == []


def test_the_due_check_and_the_premise_sweep_cache_the_answer(tmp_path, monkeypatch):
    """The two writers: the due check's rotation clause and the daily
    premise sweep each leave the answer the preview reads. Mutation checked:
    removing the `_store_review_overdue` call from either fails this test."""
    home, cache = _preview_home(tmp_path, monkeypatch)
    monkeypatch.setattr(serve.steward, "_premise_review_overdue", lambda actual, **kw: True)
    assert not serve._review_overdue_path(cache).exists()  # control: nothing cached yet
    assert _steward_preview(home, cache)[1] == "after the night's mine, when there is work"

    assert serve._premise_review_overdue(home, [], cache, NOW) is True
    assert _steward_preview(home, cache)[1] == "after the night's mine, for its overdue premise reviews"

    serve._review_overdue_path(cache).unlink()
    sentinel = object()
    monkeypatch.setattr(serve.premise_sweep, "run", lambda home_, cache_, now: sentinel)
    assert serve._run_premises_job(home, cache, NOW) is sentinel
    assert _steward_preview(home, cache)[1] == "after the night's mine, for its overdue premise reviews"


def test_a_failing_overdue_answer_never_fails_the_premise_sweep(tmp_path, monkeypatch):
    home, cache = _preview_home(tmp_path, monkeypatch)
    sentinel = object()
    monkeypatch.setattr(serve.premise_sweep, "run", lambda home_, cache_, now: sentinel)

    def boom(*_a, **_kw):
        raise RuntimeError("wedged")

    monkeypatch.setattr(serve.steward, "_premise_review_overdue", boom)
    assert serve._run_premises_job(home, cache, NOW) is sentinel
    assert not serve._review_overdue_path(cache).exists()


def _iso_of(epoch: float) -> str:
    from test_serve_steward_cadence import _iso

    return _iso(epoch)
