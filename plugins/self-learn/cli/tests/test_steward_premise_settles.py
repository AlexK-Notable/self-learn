"""P4 of the 2026-10-31 premises design (S-114): one decision of a
combined follow-up + premise input settles both.

Before it, a `premise-moved` input whose lesson had both a closed follow-up
and a moved premise hashed the two together. A `no-action` decision
rebaselined the premises, but `no-action` is not a `last_decision`, so the
lesson stayed in `moved_followups` and the next run offered the follow-up
again on its own (a new version: the follow-up alone). Until a deciding case
landed, the settled follow-up also rode along on every later premise move.

What this file pins:

* the combined input decided `no-action` through a real run is not offered
  again, and its manifest row records the follow-up-alone version it settles;
* a later premise move offers a premises-only row, with no `follow-up-done`
  item and a version that hashes no follow-up;
* control: a follow-up-only input decided `no-action` is still not offered;
* `open_followup_ids` drops the lesson after the combined decision;
* a deciding case (`replaced`) still ends the follow-up through
  `last_decision` (regression control).

Sandbox ledger only (`support.make_env` under tmpdir); no model call; the
probe runner is the fake from the premise-moved suite.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from self_learn import cases, steward, steward_inputs, verbs
from self_learn.invocation.contract import Outcome
from support import make_env
from test_steward import _configure_steward, _dump_yaml, _stage_dir
from test_steward_inputs import _publish_disposition
from test_steward_premise_moved import (
    BUS,
    P_CHANGED,
    FakeSystemctl,
    _case,
    _iso,
    _observe,
    _premised,
    _rec,
    _routed,
    _sha,
    _with_baseline,
)

A = "lrn-f7a00001"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


@pytest.fixture
def systemctl(tmp_path, monkeypatch) -> FakeSystemctl:
    from self_learn import premises

    fake = FakeSystemctl()
    monkeypatch.setattr(
        verbs, "_premise_probe_env",
        lambda home: premises.ProbeEnv(home=tmp_path / "fake-home", ledger_home=home,
                                       runner=fake, path_env="/usr/bin"),
    )
    return fake


def _day(offset: int = 0) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()


def _combined(tmp_path):
    """A routed lesson with a closed follow-up AND a moved premise: one
    combined `premise-moved` input. Returns (home, followup-alone version)."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A, follow_up={"action": "bind the unit", "unblocks_on": "the unit is bound"})
    verbs.followup_done(home, A, note="bound now", no_push=True)
    alone = steward_inputs.premise_moved_version(followup_done=_rec(home, A).follow_up_done)
    _premised(home, A, _with_baseline(P_CHANGED, "", at=_iso(-10), decided=_day(-10)))
    _observe(home, A, P_CHANGED, BUS, _iso(-1))
    _observe(home, A, P_CHANGED, BUS, _iso(-0.5))
    return home, alone


def _rebaseline_fake(seen: list[str]):
    def fake(spec):
        seen.append(spec.prompt)
        stage = _stage_dir(spec)
        for rid in re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M):
            _dump_yaml(stage / "cases" / f"{rid}.yaml", _case([rid], outcome="no-action"))
            _dump_yaml(stage / "sheets" / f"{rid}.yaml", {
                "version": 1, "case": "$CASE_ID",
                "items": [{"id": rid, "verb": "premises", "action": "rebaseline", "ids": ["p1"],
                           "because": "the binding is intended; the lesson still holds"}],
            })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    return fake


def test_a_combined_input_decided_no_action_settles_the_follow_up_too(
    tmp_path, monkeypatch, systemctl
):
    home, alone = _combined(tmp_path)
    (row,) = steward._premise_moved_inputs(home)
    # positive control: it IS the combined input, and it names what it settles
    assert [item["source"] for item in row["moved"]] == ["follow-up-done", "premise"]
    assert row["settles"] == [alone] and row["version"] != alone
    assert A in steward_inputs.open_followup_ids(home)

    systemctl.out = BUS
    _configure_steward(home)
    seen: list[str] = []
    monkeypatch.setattr(steward.invocation, "write_session", _rebaseline_fake(seen))
    result = steward.run(home)
    assert result.status == "applied", result
    assert len(seen) == 1
    (p1,) = _rec(home, A).premises or []
    assert p1["baseline"]["value_sha"] == _sha(BUS)
    # the manifest keeps the row whole, `settles` with it
    manifest = steward.committed_manifests(home)[-1]
    (kept,) = manifest["inputs"]
    assert kept["settles"] == [alone]
    # the follow-up is still "closed after the last decision" (no-action is
    # not a decision) -- that is exactly why `settles` is needed
    assert [m.record_id for m in steward_inputs.moved_followups(home)] == [A]
    assert (A, alone) in steward._terminal_versions(home)
    # so: not offered alone, not undecided on other briefs, and the next run is idle
    assert steward._premise_moved_inputs(home) == []
    assert A not in steward_inputs.open_followup_ids(home)
    assert steward.run(home).status == "idle"
    assert len(seen) == 1


def test_a_later_premise_move_no_longer_carries_the_settled_follow_up(
    tmp_path, monkeypatch, systemctl
):
    home, alone = _combined(tmp_path)
    systemctl.out = BUS
    _configure_steward(home)
    monkeypatch.setattr(steward.invocation, "write_session", _rebaseline_fake([]))
    assert steward.run(home).status == "applied"
    assert steward._premise_moved_inputs(home) == []
    # the premise moves again later (its baseline aged past the week's wait)
    _premised(home, A, _with_baseline(P_CHANGED, BUS, at=_iso(-10), decided=_day(-10)))
    _observe(home, A, P_CHANGED, "other.service", _iso(-0.3))
    _observe(home, A, P_CHANGED, "other.service", _iso(-0.1))

    (row,) = steward._premise_moved_inputs(home)
    assert [item["source"] for item in row["moved"]] == ["premise"]
    assert row["path"] == f"premise-moved:{A}" and "settles" not in row
    (item,) = row["moved"]
    assert row["version"] == steward_inputs.premise_moved_version(
        moved=[(item["premise"], item["value_sha"], item["recorded_at"])]
    )


def test_control_a_follow_up_only_input_decided_no_action_is_not_offered_again(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A, follow_up={"action": "bind the unit", "unblocks_on": "the unit is bound"})
    verbs.followup_done(home, A, note="bound now", no_push=True)
    (row,) = steward._premise_moved_inputs(home)  # positive control
    assert "settles" not in row  # nothing combined, nothing extra to settle
    _publish_disposition(home, A, row["version"], "applied", "run-0000f7a1")
    assert steward._premise_moved_inputs(home) == []
    assert A not in steward_inputs.open_followup_ids(home)


def test_a_deciding_case_still_ends_the_follow_up_through_last_decision(tmp_path, monkeypatch):
    home, _alone = _combined(tmp_path)
    assert A in steward_inputs.open_followup_ids(home)  # positive control
    opened = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [{"case": "case-0000f7a1", "kind": "resolution", "outcome": "replaced",
             "records": [A], "opened_at": opened}]

    def list_cases(home_, *, parked_for=None, record_id=None, **kwargs):
        if parked_for is not None:
            return []
        return [dict(r) for r in rows if record_id is None or record_id in r["records"]]

    monkeypatch.setattr(cases, "list_cases", list_cases)
    assert steward_inputs.moved_followups(home) == []
    assert A not in steward_inputs.open_followup_ids(home)
    # what is left is the premise move alone
    (row,) = steward._premise_moved_inputs(home)
    assert [item["source"] for item in row["moved"]] == ["premise"]
