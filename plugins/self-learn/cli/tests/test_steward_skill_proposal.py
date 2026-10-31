"""SK6 (S-NEXT-sk6-steward-proposes): the steward proposes skills.

The skill-writing plan's D6: only the overseer creates a skill on its own
decision; the steward PROPOSES one, by parking a case for the overseer with
`parked_reason: skill-proposal` and the proposal in `decision.skill`, and
may route a pending lesson into a skill self-learn already owns (listed in
its brief from the owned-skills registry).

The plan's tests, each red on master unless marked *control*:

(a) a `skill-proposal` case with a `decision.skill` validates (master: an
    unknown parked reason); without one it is refused by name -- by the
    case writer, and, in a steward run, at the repair turn;
(b) the generated steward brief carries the rule and the list of owned
    skills the steward may route into;
(c) the S-81 hold applies to the proposal's lessons;
    *control:* an `authority-unclear` park is unchanged.

Plus the brief's worked example, fed through the real case writer and the
runner's stage check, as every other example of the brief is.

No test here makes a model call: the steward runs against a fake
`write_session`, as in `test_steward_parking.py`. Every ledger is a scratch
`make_home`.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import cases, conditions, ledger_ops, steward, steward_prompt
from self_learn import skill_registry as sr
from self_learn.ledger_ops import find_record_path
from self_learn.records import Record

from support import git, make_home
from test_steward import _dump_yaml, _enable_steward, _seed_fresh_proposals, _write_decision_stage

REASON = "skill-proposal"
AT = "2026-10-30T12:00:00Z"
CASE = "case-0123abcd"
SHA = "ab" * 32


# ------------------------------------------------------------------ helpers


def _case_data(records: list[str], *, reason: str = REASON, skill: dict | None = None) -> dict:
    """A parked case as a stage file holds it. *skill* None leaves
    `decision.skill` out."""
    decision: dict = {
        "verb": "propose a skill",
        "because": "the lessons are steps of one task; whether a skill is worth it is the overseer's",
        "confidence": "provisional",
        "what_would_change": ["a release made without these steps going wrong"],
    }
    if skill is not None:
        decision["skill"] = skill
    return {
        "kind": "parked",
        "trigger": "nightly",
        "outcome": "parked",
        "parked_for": "overseer",
        "parked_reason": reason,
        "records": list(records),
        "scope": "user",
        "question": "should these lessons become one skill for cutting a release?",
        "evidence": [{"ref": "transcript:fake#L1", "quote": "push the tag before releasing"}],
        "decision": decision,
        "dependencies": {"statements": [], "user_model": [], "conditions": [], "capabilities": []},
    }


def _skill(lessons: list[str] | None, name: str = "cutting-a-release") -> dict:
    block = {"name": name, "why": "the lessons are steps of one release procedure"}
    if lessons is not None:
        block["lessons"] = list(lessons)
    return block


def _record(home: Path, tmp_path: Path, data: dict, *, actor: str = "steward") -> str:
    stage_file = tmp_path / f"stage-{len(list(tmp_path.glob('stage-*.yaml')))}.yaml"
    _dump_yaml(stage_file, data)
    return cases.record(home, stage_file, actor=actor)


def _head(home: Path) -> str:
    return git(home, "rev-parse", "HEAD").stdout.strip()


def _case_files(home: Path) -> list[Path]:
    return sorted((home / "cases").glob("*/case-*.md")) if (home / "cases").is_dir() else []


def _row(name: str, *, status: str = "live") -> dict:
    row = {
        "status": status,
        "plugin": f"plugins/{name}",
        "created": {"at": AT, "case": CASE, "by": "overseer"},
        "last_write": {"at": AT, "case": CASE, "by": "overseer", "authored_sha256": SHA},
    }
    if status == "retired":
        row["retired"] = {"at": AT, "case": CASE, "by": "human"}
    return row


def _put_registry(home: Path, rows: dict[str, dict]) -> None:
    """The owned-skills registry as the ledger would hold it, written with
    the module's own renderer (which validates it first)."""
    text = sr.render(sr.Registry(skills=copy.deepcopy(rows)))
    sr.registry_path(home).write_text(text, encoding="utf-8")


def _brief(home: Path, tmp_path: Path) -> steward_prompt.Packet:
    run = steward_prompt.RunContext(
        run_id="run-skill001", stage_dir=tmp_path / "stage" / "packet-0001",
        packet_index=1, packet_count=1, last_run_at=None,
        verbs_the_runner_executes=("case record", "batch"),
    )
    items = conditions.steward_feed(home, [("lrn-aa00beef", {})])
    return steward_prompt.assemble(
        home, tmp_path / "cache", run,
        [{"id": "lrn-aa00beef", "recommendation": "route",
          "card": {"headline": "about lrn-aa00beef", "evidence": "a quote", "advice": "route it"}}],
        conditions_items=items,
    )


def _owned_lines(shared: str) -> list[str]:
    """The lines between the SKILLS heading's list intro and the first
    instruction after it: where the owned skills are listed."""
    lines = shared.splitlines()
    start = next(n for n, line in enumerate(lines) if "The skills self-learn owns" in line)
    end = next(n for n, line in enumerate(lines) if n > start and "A PENDING lesson" in line)
    return lines[start + 2:end]


# --------------------------------------------- (a) the case writer's rule


def test_a_skill_proposal_with_its_decision_skill_is_recorded(tmp_path):
    """Master: `skill-proposal` is not a parked reason, so this is refused."""
    home = make_home(tmp_path)
    data = _case_data(["lrn-0000000a", "lrn-0000000b"],
                      skill=_skill(["lrn-0000000a", "lrn-0000000b", "lrn-0000000c"]))

    case_id = _record(home, tmp_path, data)

    view = cases.show(home, case_id, evidence_only=False)
    assert view.frontmatter["parked_reason"] == REASON
    assert view.frontmatter["records"] == ["lrn-0000000a", "lrn-0000000b"]
    # the proposal itself is in the frozen Decision section
    assert "Skill: cutting-a-release" in view.sections["Decision"]
    assert "lrn-0000000c" in view.sections["Decision"]
    assert REASON in cases.PARKED_REASONS
    assert cases.SKILL_PROPOSAL_REASON == REASON


@pytest.mark.parametrize(
    "skill, words",
    [
        (None, ["skill-proposal", "needs decision.skill"]),
        (_skill(None), ["decision.skill.lessons is required", "skill-proposal"]),
        (_skill([]), ["decision.skill.lessons is required", "skill-proposal"]),
        (_skill(["lrn-0000000a"]), ["leaves out", "lrn-0000000b"]),
    ],
    ids=["no-skill", "no-lessons", "empty-lessons", "a-record-left-out"],
)
def test_a_skill_proposal_without_its_skill_is_refused_by_name_and_writes_nothing(
    tmp_path, skill, words
):
    home = make_home(tmp_path)
    # Positive control: the same ledger records a complete proposal, so the
    # file and HEAD checks below can see a write when one happens.
    before = _head(home)
    _record(home, tmp_path, _case_data(["lrn-0000000a", "lrn-0000000b"],
                                       skill=_skill(["lrn-0000000a", "lrn-0000000b"])))
    assert _head(home) != before and len(_case_files(home)) == 1
    before = _head(home)

    with pytest.raises(cases.CaseUsageError) as refused:
        _record(home, tmp_path, _case_data(["lrn-0000000a", "lrn-0000000b"], skill=skill))

    for word in words:
        assert word in str(refused.value)
    assert _head(home) == before
    assert len(_case_files(home)) == 1


def test_control_the_proposal_rule_binds_only_the_skill_proposal_reason(tmp_path):
    """*Control:* an `authority-unclear` park with no `decision.skill`
    records exactly as before, and a decided case may still carry a
    `decision.skill` with no lessons (the shape check is unchanged)."""
    home = make_home(tmp_path)
    parked = _record(home, tmp_path, _case_data(["lrn-0000000a"], reason="authority-unclear"))
    assert cases.show(home, parked, evidence_only=False).frontmatter["parked_reason"] == (
        "authority-unclear")

    decided = _case_data(["lrn-0000000b"], skill=_skill(None))
    for key in ("parked_for", "parked_reason"):
        decided.pop(key)
    decided.update(kind="resolution", outcome="route")
    decided["decision"]["confidence"] = "settled"
    assert cases.CASE_ID_RE.fullmatch(_record(home, tmp_path, decided))


# ----------------------------------- (a) in a steward run: the repair turn


def _stage_of(spec) -> Path:
    match = re.search(r"^stage directory \(the only place you may write\): (.+)$", spec.prompt, re.M)
    assert match is not None
    return Path(match.group(1))


def _load(path: Path) -> dict:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def _propose(stage: Path, rid: str, skill: dict | None) -> None:
    """Turn the fake model's reject case for *rid* into a skill proposal;
    its sheet keeps the `reject` item: the tentative answer if no skill is
    made."""
    path = stage / "cases" / f"{rid}.yaml"
    data = _load(path)
    data.update(kind="parked", outcome="parked", parked_for="overseer", parked_reason=REASON)
    data["decision"]["confidence"] = "provisional"
    if skill is None:
        data["decision"].pop("skill", None)
    else:
        data["decision"]["skill"] = skill
    _dump_yaml(path, data)


def _run_with(home, monkeypatch, rewrite) -> list:
    calls: list = []

    def invoke(spec):
        calls.append(spec)
        outcome = _write_decision_stage(spec)
        rewrite(_stage_of(spec))
        return outcome

    monkeypatch.setattr(steward.invocation, "write_session", invoke)
    steward.run(home, dry_run=False)
    return calls


def _status(home, rid: str) -> str:
    return Record.from_path(find_record_path(home, rid)).status


def _packet(home) -> dict:
    record = next((steward.cache_dir(home) / "steward" / "runs").glob("*/run.json"))
    return json.loads(record.read_text(encoding="utf-8"))["packets"][0]


def test_the_steward_parks_a_skill_proposal_for_the_overseer_and_applies_nothing(
    tmp_path, monkeypatch
):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)

    calls = _run_with(home, monkeypatch, lambda stage: _propose(
        stage, ids[1], _skill([ids[1], "lrn-0000c0de"])))

    assert len(calls) == 1  # valid as staged: no repair turn
    # Control: the other lesson's case applied, so the run did real work.
    assert _status(home, ids[0]) == "rejected"
    # The proposed lesson: nothing done to it, parked for the overseer with
    # the steward's own reason and the proposal on record.
    assert _status(home, ids[1]) == "pending"
    (parked,) = cases.list_cases(home, parked_for="overseer")
    assert parked["parked_reason"] == REASON
    view = cases.show(home, parked["case"], evidence_only=False)
    assert view.frontmatter["records"] == [ids[1]]
    assert "Skill: cutting-a-release" in view.sections["Decision"]
    assert _packet(home)["dispositions"][ids[1]]["state"] == "parked"


def test_a_staged_skill_proposal_without_its_skill_gets_the_repair_turn(tmp_path, monkeypatch):
    """Master: the reason itself is refused; here the reason is accepted
    and the missing `decision.skill` is what the repair turn names."""
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _enable_steward(home)

    calls = _run_with(home, monkeypatch, lambda stage: _propose(stage, ids[1], None))

    assert len(calls) == 2  # the one repair turn was spent on it
    repair = calls[1].prompt
    assert f"cases/{ids[1]}.yaml" in repair
    assert "skill-proposal needs decision.skill" in repair
    # The reason was not the problem: the steward may choose it.
    assert "a parked case needs parked_reason" not in repair
    # Still unfixed after the repair turn: nothing of it is parked or applied.
    assert _status(home, ids[1]) == "pending"
    assert cases.list_cases(home, parked_reason=REASON) == []
    assert _status(home, ids[0]) == "rejected"  # control: the other case applied


def test_the_steward_may_choose_skill_proposal_and_never_the_runner_only_reasons():
    assert REASON in steward._MODEL_PARKED_REASONS
    assert REASON not in steward_prompt.RUNNER_ONLY_PARKED_REASONS
    assert "authority-unclear" in steward._MODEL_PARKED_REASONS  # control


# ---------------------------------------- (b) the brief: rule and owned list


def test_the_brief_lists_the_live_owned_skills_and_never_a_retired_one(tmp_path):
    """Master: the brief names no owned skill and no `skill-proposal`."""
    home = make_home(tmp_path)
    _put_registry(home, {
        "release-steps": _row("release-steps"),
        "shell-habits": _row("shell-habits"),
        "old-diagrams": _row("old-diagrams", status="retired"),
    })

    packet = _brief(home, tmp_path)

    owned = " ".join(_owned_lines(packet.shared))
    # Positive control first: the list is there and holds the live skills.
    assert "release-steps" in owned and "shell-habits" in owned
    assert "old-diagrams" not in owned
    assert "old-diagrams" not in packet.text
    # It is in the shared part (the output contract), not a packet's own.
    assert "release-steps" not in packet.per_packet
    contract = dict(packet.blocks)["output_contract"]
    assert "release-steps" in contract


def test_the_brief_says_none_when_no_skill_is_owned_and_says_so_when_unreadable(tmp_path):
    home = make_home(tmp_path)
    assert not sr.registry_path(home).exists()  # a fresh ledger owns nothing
    assert _owned_lines(_brief(home, tmp_path).shared) == ["    (none yet)"]

    sr.registry_path(home).write_text("version: 2\nskills: {}\n", encoding="utf-8")
    owned = " ".join(_owned_lines(_brief(home, tmp_path).shared))
    assert "could not be read" in owned and "route into" in owned


def test_the_brief_carries_the_proposal_rule_in_the_contract_and_the_method(tmp_path):
    home = make_home(tmp_path)
    contract = " ".join(dict(_brief(home, tmp_path).blocks)["output_contract"].split())

    assert "you never make a skill" in contract
    assert "`dest: new-skill:<name>`, <name> from the list above" in contract
    assert f"PROPOSING A SKILL: park the case with `parked_reason: {REASON}`" in contract
    for key in ("name", "why", "lessons"):
        assert re.search(rf"\b{key}\b", contract.split("PROPOSING A SKILL", 1)[1]), key
    assert "IF NO SKILL IS MADE" in contract
    # the choosable reasons line names it, the runner-only line does not
    choosable = next(
        line for line in steward_prompt._render_output_contract().splitlines()
        if "parked_reason is one of" in line
    )
    assert REASON in choosable and "authority-unclear" in choosable

    method = " ".join(steward_prompt._render_method().split())
    assert "You never make a skill." in method
    assert "`parked_reason: skill-proposal`" in method
    assert "`scope-conflict`, `skill-proposal`" in method  # section 12's list of six


def test_the_brief_tells_a_reconsider_never_to_move_a_placed_lesson_into_a_skill():
    contract = " ".join(steward_prompt._render_output_contract().split())
    assert "never `new-skill` or `reference`; a placed lesson that belongs in a skill is proposed" in contract


# --------------------------------------------- the brief's worked example


def _example_stage(tmp_path: Path) -> Path:
    stage = tmp_path / "stage"
    for name, body in steward_prompt.SKILL_PROPOSAL_EXAMPLES.items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return stage


def test_the_skill_proposal_example_is_rendered_and_passes_the_real_checkers(tmp_path):
    names = sorted(steward_prompt.SKILL_PROPOSAL_EXAMPLES)
    assert names == ["cases/cutting-a-release.yaml", "sheets/cutting-a-release.yaml"]
    text = steward_prompt._render_output_contract()
    for name in names:
        assert f"--- {name}" in text

    stage = _example_stage(tmp_path)
    case_path = stage / "cases" / "cutting-a-release.yaml"
    assert steward._pair_problem(stage, case_path) is None
    case = _load(case_path)
    assert case["parked_reason"] == REASON
    assert set(case["records"]) <= set(case["decision"]["skill"]["lessons"])
    sheet = _load(stage / "sheets" / "cutting-a-release.yaml")
    assert {item["id"] for item in sheet["items"]} == set(case["records"])
    assert not any(str(item.get("dest", "")).startswith("new-skill") for item in sheet["items"])

    home = make_home(tmp_path)
    case_id = cases.record(home, case_path, actor="steward")
    assert cases.show(home, case_id, evidence_only=False).frontmatter["parked_reason"] == REASON


def test_the_example_checker_is_live_the_example_without_its_skill_is_refused(tmp_path):
    stage = _example_stage(tmp_path)
    case_path = stage / "cases" / "cutting-a-release.yaml"
    case = _load(case_path)
    case["decision"].pop("skill")
    _dump_yaml(case_path, case)
    home = make_home(tmp_path)
    with pytest.raises(cases.CaseUsageError, match="needs decision.skill"):
        cases.record(home, case_path, actor="steward")


# --------------------------------------------- (c) the S-81 hold applies


def test_a_skill_proposal_holds_its_lessons_for_the_overseer(tmp_path):
    """The hold is the S-81 one every parked case gets: the case's
    `records`. A placed lesson the proposal names only in
    `decision.skill.lessons` is part of the proposal, not held by it."""
    home = make_home(tmp_path)
    assert cases.held_lessons(home) == {}  # control: nothing held before

    case_id = _record(home, tmp_path, _case_data(
        ["lrn-0000000a", "lrn-0000000b"],
        skill=_skill(["lrn-0000000a", "lrn-0000000b", "lrn-0000000c"])))

    held = cases.held_lessons(home)
    assert sorted(held) == ["lrn-0000000a", "lrn-0000000b"]
    assert [row["case"] for row in held["lrn-0000000a"]] == [case_id]
    assert held["lrn-0000000a"][0]["parked_reason"] == REASON
    assert [row["case"] for row in cases.awaiting_overseer(home)] == [case_id]
    # the steward's brief names the hold with its reason
    rendered = steward_prompt._render_held(home)
    assert rendered is not None and f"- lrn-0000000a: {case_id} ({REASON})" in rendered
    # the ledger's refusal sentence names it too
    assert f"(parked case {case_id} ({REASON}))" in ledger_ops.held_text(
        "lrn-0000000b", held["lrn-0000000b"])


def test_control_an_authority_unclear_park_holds_its_lessons_as_before(tmp_path):
    home = make_home(tmp_path)
    case_id = _record(home, tmp_path, _case_data(["lrn-0000000d"], reason="authority-unclear"))

    held = cases.held_lessons(home)
    assert sorted(held) == ["lrn-0000000d"]
    assert held["lrn-0000000d"][0]["case"] == case_id
    assert held["lrn-0000000d"][0]["parked_reason"] == "authority-unclear"
