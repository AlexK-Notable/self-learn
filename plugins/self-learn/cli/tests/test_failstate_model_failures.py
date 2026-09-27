"""Fail-state batch 1, unit 4 (2026-09-27): a failed model call is
classified, and the steward and the overseer act on its class.

Audit finding 4: every model-side failure -- a safety-classifier flag, a
rate limit, an overloaded API, a Claude Code too old for the model -- came
back as the same `exit` and cost an attempt. The user's later word on a
fallback model (2026-09-27 13:30): "i'll only accept a fallback model as a
last resort" -- so a safeguard flag is counted like any content failure,
with its class and tag on record, and no other model is ever tried.

The failure messages below are synthetic, shaped like the ones the API and
Claude Code return; every scenario uses a sandbox ledger and fake sessions.
"""

from __future__ import annotations

import time

import pytest

from self_learn import intents, model_failures, steward
from self_learn.invocation import failure_class
from self_learn.invocation.contract import Outcome
from self_learn.invocation_sdk import backend
from self_learn.overseer import run as overseer_run
from self_learn.sdksession.events import EventLog
from support import make_home
from test_failstate_overseer import _ok, _phase_a, _phase_b_common
from test_failstate_steward import _stage, _states, _two
from test_heading_evidence import KEPT_ITEM, _case
from test_overseer_run import _enabled, _silence_notifications
from test_steward import _head_manifest
from test_steward_refusals import _notifications


SAFEGUARD = (
    "API Error: Model X's safeguards flagged this message (https://example.invalid/aup). "
    "Try rephrasing the request in a new session or change your model. "
    "Details: `[reasoning_extraction]` Request ID: req_0000 Message ID: msg_0000"
)
VERSION = (
    "Claude Code 2.0.1 does not support this model; version 2.0.9 or newer is "
    "required. Run 'claude update', then try again."
)
OVERLOADED = 'API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setattr(model_failures, "TRANSIENT_BACKOFF_SECS", 0.0)


def _failed(detail, failure="exit"):
    return Outcome(ok=False, rc=1, stdout="", detail=detail, failure=failure)


# ------------------------------------------------------------ the classifier


@pytest.mark.parametrize(("failure", "detail", "subtype", "expected"), [
    ("exit", SAFEGUARD, None, "safeguard"),
    ("exit", VERSION, None, "environment"),
    ("exit", "API Error: 401 authentication_error: invalid x-api-key", None, "environment"),
    ("not-found", "", None, "environment"),
    ("unavailable", "provider refused", None, "environment"),
    ("exit", OVERLOADED, None, "transient"),
    ("exit", "API Error: 429 rate_limit_error: too many requests", None, "transient"),
    ("exit", "API Error: 500 Internal server error", None, "transient"),
    ("os-error", "Connection error: ECONNRESET", None, "transient"),
    ("exit", "stopped", "error_max_turns", "content"),
    ("exit", "spent", "error_max_budget_usd", "content"),
    ("timeout", "", None, "unclassified"),
    ("exit", "reader produced no output", None, "unclassified"),
    (None, "", None, None),
])
def test_a_failed_call_is_classified_from_its_detail(failure, detail, subtype, expected):
    assert failure_class.classify(failure, detail, subtype) == expected


def test_the_safety_classifiers_tag_is_read_off_the_detail():
    assert failure_class.detail_tag(SAFEGUARD) == "reasoning_extraction"
    assert failure_class.detail_tag(VERSION) is None


def test_the_sdk_backend_puts_the_class_on_the_outcome():
    failed = backend._outcome(ok=False, rc=1, stdout="", detail=OVERLOADED,
                              failure="exit", events=EventLog())
    assert failed.failure_class == "transient"
    fine = backend._outcome(ok=True, rc=0, stdout="", detail="", failure=None, events=EventLog())
    assert fine.failure_class is None


# ------------------------------------------------------------ the steward


def test_steward_a_transient_failure_is_retried_once_within_the_attempt(tmp_path, monkeypatch):
    home, a, b = _two(tmp_path, monkeypatch, "d1")
    staged = {a: _case(a, [KEPT_ITEM]), b: _case(b, [KEPT_ITEM])}
    calls = []

    def session(spec):
        calls.append(1)
        if len(calls) == 1:
            return _failed(OVERLOADED)
        return _stage(spec, staged)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)
    assert len(calls) == 2
    assert _states(home, result.run_id) == {a: "applied", b: "applied"}
    packet = _head_manifest(home, result.run_id)["packets"][0]
    assert packet["attempt_count"] == 1
    decision = [row for row in packet["attempts"] if row["kind"] == "decision"]
    assert decision[-1]["transient_retry"]["failure_class"] == "transient"


def test_steward_an_environment_failure_is_a_hold_not_an_attempt(tmp_path, monkeypatch):
    home, a, b = _two(tmp_path, monkeypatch, "d2")
    sent = _notifications(monkeypatch)
    calls = []

    def session(spec):
        calls.append(1)
        return _failed(VERSION)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    first = steward.run(home)
    packet = _head_manifest(home, first.run_id)["packets"][0]
    # Positive control: the call really was made and recorded.
    assert len(calls) == 1 and packet["attempts"][-1]["failure_class"] == "environment"
    assert packet["attempt_count"] == 0  # not counted
    assert packet["failure_class"] == "environment"
    assert first.held and "does not support this model" in first.held
    assert len(sent) == 1 and "held" in sent[0][1]

    second = steward.run(home)
    packet = _head_manifest(home, second.run_id)["packets"][0]
    assert len(calls) == 2 and packet["attempt_count"] == 0
    assert len(sent) == 1  # the same cause is told once


def test_steward_a_safeguard_flag_is_counted_with_its_class_and_tag(tmp_path, monkeypatch):
    home, a, b = _two(tmp_path, monkeypatch, "d3")
    calls = []

    def session(spec):
        calls.append(1)
        return _failed(SAFEGUARD)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)
    packet = _head_manifest(home, result.run_id)["packets"][0]
    assert len(calls) == 1  # no retry, and no other model
    assert packet["attempt_count"] == 1
    assert packet["failure_class"] == "safeguard"
    assert packet["failure_tag"] == "reasoning_extraction"
    assert _states(home, result.run_id) == {a: "unfinished", b: "unfinished"}


# ------------------------------------------------------------ the overseer


def _week(home):
    return overseer_run.week_key(overseer_run.week_boundary(time.time()))


def test_overseer_a_transient_phase_a_failure_is_retried_and_the_run_goes_on(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    labels = []

    def invoke(spec):
        labels.append(spec.label)
        if labels == ["phase-a"]:
            return _failed(OVERLOADED)
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            (spec.cwd / "sheet.yaml").write_text("version: 1\nitems: []\n", encoding="utf-8")
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    result = overseer_run.run(home, no_push=True)
    assert labels == ["phase-a", "phase-a", "phase-b"]
    assert result.status == "applied"
    rows = overseer_run.read_journal(home, limit=100)
    assert any(row.get("status") == "transient-retry" for row in rows)


def test_overseer_an_environment_failure_in_phase_a_is_a_hold(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    notices = _silence_notifications(monkeypatch)
    monkeypatch.setattr(overseer_run.invocation, "write_session", lambda spec: _failed(VERSION))

    result = overseer_run.run(home, no_push=True)
    assert result.status == model_failures.HELD_ENVIRONMENT
    assert overseer_run.week_attempts(home, _week(home)) == 0
    assert overseer_run._committed_failure_notes(home, _week(home)) == []
    assert len(notices) == 1 and "does not support this model" in notices[0][1]
    overseer_run.run(home, no_push=True)
    assert len(notices) == 1  # told once per cause


def test_overseer_an_environment_failure_in_phase_b_restores_coverage_and_counts_nothing(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
            return _ok()
        return _failed("API Error: 401 authentication_error: OAuth token has expired")

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    coverage = home / "overseer" / "coverage.yaml"
    assert not coverage.exists()
    result = overseer_run.run(home, no_push=True)
    assert result.status == model_failures.HELD_ENVIRONMENT
    assert not coverage.exists()  # put back as it was
    assert overseer_run.week_attempts(home, _week(home)) == 0
    assert list(intents.intents_dir(home).glob("*.json")) == []


def test_overseer_a_safeguard_flag_is_counted_and_its_note_names_class_and_tag(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)

    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
            return _ok()
        return _failed(SAFEGUARD)

    calls = []
    monkeypatch.setattr(overseer_run.invocation, "write_session",
                        lambda spec: (calls.append(spec.label), invoke(spec))[1])
    result = overseer_run.run(home, no_push=True)
    assert calls == ["phase-a", "phase-b"]  # no retry
    assert result.status == "refused"
    assert overseer_run.week_attempts(home, _week(home)) == 1
    (note,) = overseer_run._committed_failure_notes(home, _week(home))
    text = (home / note).read_text(encoding="utf-8")
    assert "- class: safeguard" in text and "- tag: reasoning_extraction" in text
