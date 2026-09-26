"""2026-09-26 (agenda item 9): the steward's dry-run summary can say "every
model call failed". A dry run discards its decisions either way, so before
this its summary read the same whether every call failed or every call
returned. Now the text and `--json` count failed calls separately and say
it plainly.

The overseer has no such ambiguity: a failed model call ends its dry run
with status `refused` or `timed-out` (exit 1), never `dry-run` -- pinned
below so it stays that way.

Sandbox ledgers under pytest's tmpdir only (`support.make_home`).
"""

from __future__ import annotations

import contextlib
import io
import json

import pytest

from self_learn import cli, steward
from self_learn.overseer import run as overseer_run
from support import make_home
from test_overseer_run import _enabled, _silence_notifications
from test_steward import _enable_steward, _seed_fresh_proposals, _transport_failure, _write_decision_stage


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _steward_cli(tmp_path, monkeypatch, session, *extra: str) -> str:
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", session)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["steward", "run", "--dry-run", *extra])
    return out.getvalue()


def test_a_dry_run_whose_calls_all_fail_reads_as_failed(tmp_path, monkeypatch):
    text = _steward_cli(tmp_path, monkeypatch, _transport_failure)
    assert "steward run: dry-run" in text  # positive control: the summary printed
    assert "every model call FAILED (1 of 1); nothing was decided" in text, text
    assert "every model call returned" not in text


def test_a_dry_run_whose_calls_all_fail_says_so_in_json(tmp_path, monkeypatch):
    payload = json.loads(_steward_cli(tmp_path, monkeypatch, _transport_failure, "--json"))
    assert payload["outcome"] == "dry-run"
    assert (payload["calls"], payload["failed_calls"], payload["all_calls_failed"]) == (1, 1, True)


def test_a_dry_run_whose_calls_succeed_reads_as_succeeded(tmp_path, monkeypatch):
    text = _steward_cli(tmp_path, monkeypatch, _write_decision_stage)
    assert "every model call returned (1); a dry run discards its decisions" in text, text
    assert "FAILED" not in text
    payload = json.loads(_steward_cli(tmp_path / "again", monkeypatch, _write_decision_stage, "--json"))
    assert (payload["calls"], payload["failed_calls"], payload["all_calls_failed"]) == (1, 0, False)


def test_an_overseer_dry_run_whose_call_fails_is_not_a_dry_run_result(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    monkeypatch.setattr(
        overseer_run.invocation, "write_session",
        lambda spec: type("SdkLike", (), {"ok": False, "rc": 1, "stdout": "", "detail": "boom",
                                          "failure": "exit", "turns": None})(),
    )

    result = overseer_run.run(home, dry_run=True, no_push=True)

    assert (result.status, result.code) == ("refused", 1), result
    assert result.model_calls == 1


def test_a_failed_repair_call_is_counted(tmp_path, monkeypatch):
    from test_steward import _invalid_schema_stage
    from test_steward_refusals import _REPAIR_HEADER

    def session(spec):
        if _REPAIR_HEADER in spec.prompt:
            return _transport_failure(spec)
        return _invalid_schema_stage(spec)

    text = _steward_cli(tmp_path, monkeypatch, session)
    assert "steward run: 1 of 2 model call(s) failed" in text, text
