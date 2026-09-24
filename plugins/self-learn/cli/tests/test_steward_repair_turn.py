"""S-71 §5 and §4.6: the steward's one repair turn also shows the model the
lines the ledger would refuse as written, and a lesson the ledger sent back
comes to the next run's brief with the ledger's words.

Full `steward.run` scenarios on sandbox ledgers (`support.make_env` under
pytest's tmpdir, never the real `~/.self-learn`) with the fake session writer
of `test_steward_refusals.py`, plus direct checks of the repair feed and the
brief block.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import batch, gitops, ledger_ops, steward, steward_prompt
from self_learn.hosts import MARKER_FILENAME, host_add
from support import git, make_behavior, make_env
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir
from test_steward_refusals import (
    _REPAIR_HEADER,
    _case,
    _dispositions,
    _notifications,
    _one_line_each,
    _seed,
    _writer,
)
from self_learn.invocation.contract import Outcome


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_LEDGER_REPAIR = "The ledger would refuse these lines of your sheets as written:"


def _repair_part(prompt: str) -> str:
    assert _REPAIR_HEADER in prompt
    return prompt.split(_REPAIR_HEADER, 1)[1]


def _stage_one(spec, rid: str, item: dict, outcome: str = "defer") -> Outcome:
    stage = _stage_dir(spec)
    _dump_yaml(stage / "cases" / f"{rid}.yaml", _case([rid], outcome, item["verb"]))
    _dump_yaml(
        stage / "sheets" / f"{rid}.yaml",
        {"version": 1, "case": "$CASE_ID", "items": [item]},
    )
    return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)


# ------------------------------------------------------------ §5, e2e


def test_a_line_the_ledger_would_refuse_goes_to_the_repair_turn_and_the_fix_applies(
    tmp_path, monkeypatch
):
    """The first session defers the lesson to a date in the past (a line
    the ledger refuses: bad-line). Its format is fine, so the one repair
    turn goes to the ledger's refusal: the repair session is told which
    line and why, rewrites it, and the repaired stage applies."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c0000001")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []
    allowance_when_repairing: list[int] = []

    def session(spec):
        prompts.append(spec.prompt)
        if _REPAIR_HEADER in spec.prompt:
            # committed BEFORE the repair session runs, so a session that
            # dies cannot leave a later run thinking the turn is unspent
            allowance_when_repairing.append(
                steward.committed_manifests(home)[-1]["packets"][0]["repair_remaining"]
            )
            return _stage_one(spec, rid, {"id": rid, "verb": "reject"}, "reject")
        return _stage_one(spec, rid, {"id": rid, "verb": "defer", "until": "2000-01-01"})

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    assert len(prompts) == 2 and result.calls == 2
    assert allowance_when_repairing == [0]
    repair = _repair_part(prompts[1])
    # the header is neutral: what failed is said below it
    assert "A check of the stage files you wrote failed." in repair
    assert "failed validation" not in repair
    assert _LEDGER_REPAIR in repair
    assert f"- sheets/{rid}.yaml: item 1 (defer {rid}): " in repair
    assert "is in the past" in repair
    assert "Fix each one: rewrite the line, choose a different destination or verb" in repair
    assert "Leave every other file as it is." in repair
    assert result.decided == [rid]
    manifest = _head_manifest(home, result.run_id)
    packet = manifest["packets"][0]
    assert packet["dispositions"][rid]["state"] == "applied"
    assert packet["repair_remaining"] == 0, "the turn was spent and committed as spent"
    assert [row["kind"] for row in packet["attempts"]] == ["decision", "repair"]


def test_a_repair_turn_spent_on_a_format_error_is_not_spent_again(tmp_path, monkeypatch):
    """The first session's sheet fails its format check; the repair
    session fixes the format but writes a line the ledger refuses. The turn
    is spent: no second repair, and apply time sends the lesson back."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c0000002")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        if _REPAIR_HEADER in spec.prompt:
            return _stage_one(spec, rid, {"id": rid, "verb": "defer", "until": "2000-01-01"})
        outcome = _stage_one(spec, rid, {"id": rid, "verb": "reject"}, "reject")
        _dump_yaml(_stage_dir(spec) / "sheets" / f"{rid}.yaml", {"version": 1, "unexpected": []})
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    assert len(prompts) == 2
    assert _LEDGER_REPAIR not in _repair_part(prompts[1]), "the turn went to the format error"
    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "returned", row
    assert row["kind"] == "bad-line" and "is in the past" in row["reason"]


def test_a_clean_stage_spends_no_repair_turn(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c0000003")
    _enable_steward(home)
    prompts: list[str] = []
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("reject", "reject"), prompts=prompts),
    )

    result = steward.run(home)

    assert len(prompts) == 1 and result.decided == [rid]
    assert _head_manifest(home, result.run_id)["packets"][0]["repair_remaining"] == 1


def test_a_status_refusal_whose_lesson_moved_on_is_not_the_model_s_to_repair(
    tmp_path, monkeypatch
):
    """A person rejects the lesson while the steward decides to defer it.
    The ledger would refuse the `defer` -- but the lesson moved on; that is
    not the model's mistake, so no repair turn. Apply time closes it."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c0000004")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(
            _one_line_each("defer", "defer", until="2099-01-01"),
            before=lambda ids: steward.verbs.reject(home, rid, no_push=True),
            prompts=prompts,
        ),
    )

    result = steward.run(home)

    assert len(prompts) == 1
    assert _dispositions(home, result.run_id)[rid]["state"] == "overtaken"


def test_a_line_only_a_person_can_fix_is_not_the_model_s_to_repair(tmp_path, monkeypatch):
    """A route to a host that lost its marker (needs-person): no repair
    turn; apply time parks the lesson."""
    env = make_env(tmp_path)
    home = env.ledger
    plain = tmp_path / "plain-host"
    plain.mkdir()
    host_add(home, plain, "project", mode="plain")
    rid = _seed(
        home, "lrn-c0000005", scope="project",
        record=make_behavior(record_id="lrn-c0000005", scope="project"),
        project_path=plain,
    )
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(
            _one_line_each("route", "route", dest="claude-md"),
            before=lambda ids: (plain / MARKER_FILENAME).unlink(),
            prompts=prompts,
        ),
    )

    result = steward.run(home)

    assert len(prompts) == 1
    assert _dispositions(home, result.run_id)[rid]["state"] == "abandoned"


def test_a_case_the_model_parked_is_not_previewed_for_repair(tmp_path, monkeypatch):
    """The model parks the case; its sheet is a tentative answer that is
    never applied, so a line in it the ledger would refuse is nobody's to
    repair."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c0000006")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        outcome = _stage_one(spec, rid, {"id": rid, "verb": "defer", "until": "2000-01-01"})
        case = _case([rid], "parked", "defer")
        case.update(kind="parked", parked_for="overseer", parked_reason="authority-unclear")
        _dump_yaml(_stage_dir(spec) / "cases" / f"{rid}.yaml", case)
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    assert len(prompts) == 1
    assert _dispositions(home, result.run_id)[rid]["state"] == "parked"


def test_a_case_the_runner_will_park_is_not_previewed_for_repair(tmp_path, monkeypatch):
    """A sheet with a hook route is parked by the runner (never applied), so
    its other line the ledger would refuse is nobody's to repair either."""
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c000000b")
    _enable_steward(home)
    _notifications(monkeypatch)
    prompts: list[str] = []

    def session(spec):
        prompts.append(spec.prompt)
        stage = _stage_dir(spec)
        _dump_yaml(stage / "cases" / f"{rid}.yaml", _case([rid], "route", "route"))
        _dump_yaml(stage / "sheets" / f"{rid}.yaml", {"version": 1, "case": "$CASE_ID", "items": [
            {"id": rid, "verb": "defer", "until": "2000-01-01"},
            {"id": rid, "verb": "route", "dest": "hook"},
        ]})
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", session)

    result = steward.run(home)

    assert len(prompts) == 1
    assert _dispositions(home, result.run_id)[rid]["state"] == "parked"


def test_the_dry_run_spends_the_repair_turn_the_same_way_and_writes_nothing(
    tmp_path, monkeypatch
):
    home = make_env(tmp_path).ledger
    rid = _seed(home, "lrn-c0000007")
    _enable_steward(home)
    prompts: list[str] = []
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _writer(_one_line_each("defer", "defer", until="2000-01-01"), prompts=prompts),
    )
    head = gitops.head_sha(home)

    result = steward.run(home, dry_run=True)

    assert result.status == "dry-run"
    assert len(prompts) == 2 and _LEDGER_REPAIR in _repair_part(prompts[1])
    assert f"(defer {rid})" in _repair_part(prompts[1])
    assert gitops.head_sha(home) == head
    assert git(home, "status", "--porcelain").stdout == ""


# ------------------------------------------- §5, the feed itself


def _stage(tmp_path: Path, rid: str, *, kind: str, item: dict) -> Path:
    stage = tmp_path / "stage"
    case = _case([rid], "reject", item["verb"])
    case["kind"] = kind
    _dump_yaml(stage / "cases" / "one.yaml", case)
    _dump_yaml(stage / "sheets" / "one.yaml",
               {"version": 1, "case": "$CASE_ID", "items": [item]})
    return stage


def _routed(tmp_path: Path, rid: str) -> Path:
    home = make_env(tmp_path).ledger
    _seed(home, rid)
    sheet = tmp_path / "route.yaml"
    sheet.write_text(
        f"version: 1\nitems:\n  - id: {rid}\n    verb: route\n    dest: skill-md\n",
        encoding="utf-8",
    )
    result = batch.run(home, batch.load_sheet(sheet), no_push=True)
    assert result.items[0].state == "applied", result.items[0]
    return home


def test_a_staged_reconsider_case_keeps_its_status_refusal_out_of_the_repair_turn(
    tmp_path,
):
    """The coordinator's correction to §5: the repair feed previews without
    the staged case (it is not in the ledger yet), so a `reject` of a ROUTED
    lesson under a staged `kind: reconsider` case previews as a status
    refusal the case would in fact widen at apply time. Not collected.
    The same `reject` under a case that is NOT a reconsider IS collected."""
    rid = "lrn-c0000008"
    home = _routed(tmp_path, rid)
    selected = {rid: "routed"}

    with_case = steward._ledger_repair_message(
        home, _stage(tmp_path / "a", rid, kind="reconsider", item={"id": rid, "verb": "reject"}),
        selected,
    )
    without_case = steward._ledger_repair_message(
        home, _stage(tmp_path / "b", rid, kind="resolution", item={"id": rid, "verb": "reject"}),
        selected,
    )

    assert without_case is not None, "positive control: the plain case is collected"
    assert f"(reject {rid})" in without_case and "'routed'" in without_case
    assert with_case is None


def test_a_status_refusal_is_collected_only_when_the_status_is_known_unchanged(tmp_path):
    rid = "lrn-c0000009"
    home = make_env(tmp_path).ledger
    _seed(home, rid)
    stage = _stage(tmp_path, rid, kind="resolution", item={"id": rid, "verb": "undefer"})

    assert steward._ledger_repair_message(home, stage, {rid: "pending"}) is not None
    assert steward._ledger_repair_message(home, stage, {rid: "deferred"}) is None
    assert steward._ledger_repair_message(home, stage, {}) is None, "unknown: not collected"


# ------------------------------------------------------------ §4.6


def test_the_sent_back_block_sits_just_before_the_open_cases(tmp_path, monkeypatch):
    home = make_env(tmp_path).ledger
    run = steward_prompt.RunContext(
        run_id="run-000000000001", stage_dir=tmp_path / "stage", packet_index=1,
        packet_count=1, last_run_at=None, verbs_the_runner_executes=("batch",),
    )
    returned = {"lrn-c000000a": {"case": "case-0000abcd",
                                 "lines": ["undefer lrn-c000000a: it is 'pending'"]}}

    plain = steward_prompt.assemble(home, tmp_path / "cache", run, [], conditions_items=[])
    packet = steward_prompt.assemble(
        home, tmp_path / "cache", run, [], conditions_items=[], returned=returned,
    )

    assert [name for name, _ in plain.blocks] == list(steward_prompt._BLOCK_ORDER)
    names = [name for name, _ in packet.blocks]
    assert names == [*steward_prompt._BLOCK_ORDER[:4], "sent_back",
                     *steward_prompt._BLOCK_ORDER[4:]]
    body = dict(packet.blocks)["sent_back"]
    assert body.startswith(steward_prompt.SENT_BACK_TITLE)
    assert "- lrn-c000000a (earlier case case-0000abcd):" in body
    assert "the ledger said: undefer lrn-c000000a: it is 'pending'" in body
    assert body.endswith(steward_prompt.SENT_BACK_INSTRUCTION)
    assert steward_prompt.SENT_BACK_INSTRUCTION == (
        "Your earlier decision for these lessons could not be applied as written. Decide "
        "again: you may write a different line, choose a different destination or verb, or "
        "park the case with the reason that names its question. Do not write the same line "
        "again."
    )


def test_the_output_contract_says_what_becomes_of_a_refused_line():
    text = " ".join(steward_prompt._render_output_contract().split())
    assert (
        "A lesson whose line the ledger refuses is either sent back to you on a later "
        "night (once) or parked for the overseer; a refusal is never retried unchanged "
        "unless it was git trouble or a target file with uncommitted edits."
    ) in text
    assert "parks it for the overseer after the attempt cap" not in text
