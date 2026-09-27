"""Fail-state batch 1, the steward's units (2026-09-27).

The user's words, 06:58: "Make the fix. Look for any other similarly
outlandish fail states." The audit (findings 2, 3 and 8) found packets of
up to ten lessons lost to one failed repair call, one stray file in the
stage, or one stray file in the ledger. The rule the user has now accepted
three times: a bad item costs that item, not the unit around it.

Every scenario runs on a pytest sandbox ledger with fake model sessions;
the ids and texts are synthetic.
"""

from __future__ import annotations

import pytest

from self_learn import steward
from self_learn.invocation.contract import Outcome
from support import make_env
from test_heading_evidence import KEPT_ITEM, _case
from test_steward import _dump_yaml, _enable_steward, _stage_dir
from test_steward_refusals import _REPAIR_HEADER, _dispositions, _notifications, _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _stage(spec, cases_by_rid, extra_files=()):
    stage = _stage_dir(spec)
    for rid, case in cases_by_rid.items():
        _dump_yaml(stage / "cases" / f"{rid}.yaml", case)
        _dump_yaml(
            stage / "sheets" / f"{rid}.yaml",
            {"version": 1, "case": "$CASE_ID", "items": [{"id": rid, "verb": "reject"}]},
        )
    for name in extra_files:
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("scratch notes\n", encoding="utf-8")
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


def _two(tmp_path, monkeypatch, tag):
    home = make_env(tmp_path).ledger
    a = _seed(home, f"lrn-{tag}000001")
    b = _seed(home, f"lrn-{tag}000002")
    _enable_steward(home)
    _notifications(monkeypatch)
    return home, a, b


def _states(home, run_id):
    return {rid: row["state"] for rid, row in _dispositions(home, run_id).items()}


# ------------------------------------------------------------ unit 2


def test_a_failed_repair_call_keeps_the_valid_first_pass(tmp_path, monkeypatch):
    """Audit finding 2 (`test_S1_…`): the first pass validates; one case's
    `because` carries a heading line, so the repair turn fires; the repair
    CALL fails (as a safety-classifier flag, a 529 or a timeout would).
    Before: both lessons `unfinished`, the attempt spent. Now the first
    pass goes ahead: the good lesson applies and only the flagged case is
    refused, at apply time, by the case writer."""
    home, bad, good = _two(tmp_path, monkeypatch, "f1")
    first = {bad: _case(bad, [KEPT_ITEM], because="settled\n## heading"), good: _case(good, [KEPT_ITEM])}
    calls = []

    def session(spec):
        calls.append(spec.prompt)
        if _REPAIR_HEADER in spec.prompt:
            return Outcome(ok=False, rc=1, stdout="", detail="API Error: overloaded", failure="exit")
        return _stage(spec, first)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)
    states = _states(home, result.run_id)
    assert len(calls) == 2  # the repair turn did fire
    # Positive control: the lesson the first pass decided validly applied.
    assert states[good] == "applied"
    assert good in result.decided
    # Only what the first pass still flags is refused.
    assert states[bad] == "refused"


def test_a_repair_that_breaks_a_valid_case_is_undone(tmp_path, monkeypatch):
    """The repair call succeeds but rewrites the good case into one the
    case writer refuses (`confidence: high`) and leaves the flagged one as
    it was: the stage is worse than the first pass, so the first pass is
    put back and the good lesson still applies."""
    home, bad, good = _two(tmp_path, monkeypatch, "f6")
    first = {bad: _case(bad, [KEPT_ITEM], because="settled\n## heading"), good: _case(good, [KEPT_ITEM])}
    broken = _case(good, [KEPT_ITEM])
    broken["decision"]["confidence"] = "high"

    def session(spec):
        if _REPAIR_HEADER in spec.prompt:
            return _stage(spec, {bad: first[bad], good: broken})
        return _stage(spec, first)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)
    states = _states(home, result.run_id)
    assert states[good] == "applied"
    assert states[bad] == "refused"


def test_a_repair_that_fixes_the_flagged_case_is_kept(tmp_path, monkeypatch):
    """Control: a repair turn that fixes the flagged case and leaves the
    rest alone is used, so both lessons apply."""
    home, bad, good = _two(tmp_path, monkeypatch, "f7")
    first = {bad: _case(bad, [KEPT_ITEM], because="settled\n## heading"), good: _case(good, [KEPT_ITEM])}
    fixed = {bad: _case(bad, [KEPT_ITEM]), good: _case(good, [KEPT_ITEM])}

    def session(spec):
        return _stage(spec, fixed if _REPAIR_HEADER in spec.prompt else first)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)
    states = _states(home, result.run_id)
    assert states == {bad: "applied", good: "applied"}
