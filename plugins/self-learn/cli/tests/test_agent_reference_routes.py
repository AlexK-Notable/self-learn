"""The steward and the overseer never route a lesson to a reference shelf
(2026-10-06).

A shelf is a project's or a skill's `references/LEARNINGS.md`, reached
through one pointer line no task can match. Measured 2026-10-05, seven
shelves held 40 lessons and none had ever been read; on 2026-10-06 the
steward shelved one more. The user said yes to stopping new shelf routes.
S-23 had already made path-scoped rules the cheap tier and kept shelves for
lessons tied to no file.

The refusal is enforced in the batch, by name, for the two agent actors
(`batch.REFERENCE_REFUSED_ACTORS`): a fresh route, a route whose
destination comes from the proposal, and a re-decision under a reconsider
case. Its kind is `bad-line`, so the steward is sent the line back to
choose again. A person's route there (a review session's sheet, which runs
as `human`) is unchanged -- the positive control every refusal here is
measured against. The agents are told, in their own instructions, where
such a lesson goes instead.

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir); no model is called.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import batch, ledger_ops, steward, steward_prompt
from self_learn.ledger_ops import find_record_path
from self_learn.overseer import formats
from self_learn.overseer import run as overseer_run
from self_learn.records import Record
from support import commit_all, last_verb_sha, make_behavior, make_env, proposal_dict
from test_steward import _dump_yaml
from test_steward_refusals import _case
from test_u3b_steward_authority import _record_case, _route_through_a_case

RID = "lrn-5e1f1001"
AGENTS = ("steward", "overseer")
REFS = Path(__file__).resolve().parents[2] / "skills" / "self-learn" / "references"
REVIEW_MD = Path(__file__).resolve().parents[2] / "commands" / "review.md"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


def _record(home: Path, rid: str) -> Record:
    return Record.from_path(find_record_path(home, rid))


def _pending_with_a_shelf_proposal(home: Path, rid: str) -> None:
    """A skill lesson whose analyst proposal says `reference`, as DEMAND
    proposals still may: the person reading it decides."""
    ledger_ops.create_record(home, make_behavior(record_id=rid))
    ledger_ops.write_proposal(home, rid, proposal_dict(destination="reference"))
    ledger_ops.stamp_proposal(home, rid)
    commit_all(home, f"seed {rid}")


def _sheet(tmp_path: Path, items: list[dict], case: str | None = None) -> batch.Sheet:
    path = tmp_path / "sheet.yaml"
    body: dict = {"version": 1, "items": items}
    if case is not None:
        body["case"] = case
    _dump_yaml(path, body)
    return batch.load_sheet(path)


def test_the_refusal_is_one_constant_naming_the_two_agents():
    assert batch.REFERENCE_REFUSED_ACTORS == frozenset({"steward", "overseer"})
    assert "human" not in batch.REFERENCE_REFUSED_ACTORS
    assert batch.REFERENCE_REFUSED_ACTORS <= batch.verbs.ROUTING_BY_VALUES


# ------------------------------------------------------------- a fresh route


@pytest.mark.parametrize("actor", AGENTS)
@pytest.mark.parametrize("line", ["dest-named", "dest-from-proposal"])
def test_an_agent_route_to_a_shelf_is_refused_by_name_and_a_persons_applies(tmp_path, actor, line):
    env = make_env(tmp_path)
    home = env.ledger
    _pending_with_a_shelf_proposal(home, RID)
    item = {"id": RID, "verb": "route"}
    if line == "dest-named":
        item["dest"] = "reference"
    sheet = _sheet(tmp_path, [item])
    shelf = env.skill_dir / "references" / "LEARNINGS.md"
    before = last_verb_sha(home)

    preview = batch.dry_run(home, sheet, actor=actor)
    result = batch.run(home, sheet, no_push=True, actor=actor)

    refused, previewed = result.items[0], preview.items[0]
    assert (refused.state, refused.kind) == ("refused", "bad-line"), refused.detail
    assert (previewed.state, previewed.kind) == ("would-refuse", "bad-line")
    assert refused.detail == previewed.detail  # one sentence, run and preview alike
    assert f"refused for the {actor}" in (refused.detail or "")
    assert "path-scoped rule" in (refused.detail or "")
    assert steward._KIND_ACTIONS[refused.kind] == "return"  # sent back to choose again
    assert _record(home, RID).status == "pending"
    assert not shelf.exists()
    assert last_verb_sha(home) == before  # no ledger write of any verb

    # positive control: the same sheet, run as a person, lands on the shelf
    applied = batch.run(home, sheet, no_push=True)
    assert applied.items[0].state == "applied", applied.items[0].detail
    assert (_record(home, RID).routing or {}).get("destination") == "reference"
    assert f"— {RID}" in shelf.read_text(encoding="utf-8")


def test_an_agents_other_routes_are_untouched(tmp_path):
    """The refusal is the destination's, not the actor's: the same agent's
    route of the same lesson to its skill applies."""
    env = make_env(tmp_path)
    home = env.ledger
    _pending_with_a_shelf_proposal(home, RID)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": "skill-md"}])
    assert batch.dry_run(home, sheet, actor="steward").items[0].state == "would-apply"
    result = batch.run(home, sheet, no_push=True, actor="steward")
    assert result.items[0].state == "applied", result.items[0].detail
    assert RID in env.skill_md.read_text(encoding="utf-8")
    # ... and the refusal is live on this fixture (the control for the above)
    other = "lrn-5e1f1002"
    _pending_with_a_shelf_proposal(home, other)
    sheet = _sheet(tmp_path, [{"id": other, "verb": "route", "dest": "reference"}])
    assert batch.run(home, sheet, no_push=True, actor="steward").items[0].state == "refused"


# ---------------------------------------------- a re-decision onto a shelf


@pytest.mark.parametrize("actor", AGENTS)
def test_an_agent_reroute_onto_a_shelf_is_refused_and_a_persons_applies(tmp_path, actor):
    """A reconsider's correcting route is a route line too: refused before
    the reroute is attempted, the lesson left where it was."""
    env = make_env(tmp_path)
    home = env.ledger
    setup = tmp_path / "setup"
    setup.mkdir()
    prior = _route_through_a_case(home, setup, RID)  # the steward routed it to its skill
    reconsider = _case([RID], "route", "route")
    reconsider.update(kind="reconsider", supersedes=prior)
    rc = _record_case(home, setup, reconsider, actor=actor)
    sheet = _sheet(tmp_path, [{"id": RID, "verb": "route", "dest": "reference"}], case=rc)

    preview = batch.dry_run(home, sheet, actor=actor)
    result = batch.run(home, sheet, no_push=True, actor=actor)

    assert (preview.items[0].state, preview.items[0].kind) == ("would-refuse", "bad-line")
    assert (result.items[0].state, result.items[0].kind) == ("refused", "bad-line")
    assert f"refused for the {actor}" in (result.items[0].detail or "")
    assert (_record(home, RID).routing or {}).get("destination") == "skill-md"
    assert RID in env.skill_md.read_text(encoding="utf-8")

    # positive control: a person's same line under the same case is a reroute
    applied = batch.run(home, sheet, no_push=True)
    assert applied.items[0].state == "applied", applied.items[0].detail
    assert (_record(home, RID).routing or {}).get("destination") == "reference"
    assert RID not in env.skill_md.read_text(encoding="utf-8")


def test_the_stewards_repair_turn_is_told_before_anything_is_applied(tmp_path):
    """The steward's preview of its staged sheets (S-71 §5) finds the
    shelf line and names it, so the repair turn can choose again. The
    control: the same staged pair with a skill route needs no repair."""
    env = make_env(tmp_path)
    home = env.ledger
    _pending_with_a_shelf_proposal(home, RID)
    stage = tmp_path / "stage"
    _dump_yaml(stage / "cases" / "shelf.yaml", _case([RID], "route", "route"))
    _dump_yaml(stage / "sheets" / "shelf.yaml", {"version": 1, "case": "$CASE_ID", "items": [
        {"id": RID, "verb": "route", "dest": "reference"}]})
    message = steward._ledger_repair_message(home, stage, {RID: "pending"})
    assert message is not None and f"(route {RID})" in message, message
    assert "refused for the steward" in message

    _dump_yaml(stage / "sheets" / "shelf.yaml", {"version": 1, "case": "$CASE_ID", "items": [
        {"id": RID, "verb": "route", "dest": "skill-md"}]})
    assert steward._ledger_repair_message(home, stage, {RID: "pending"}) is None


# ------------------------------------------------- what the agents are told


def _all_example_lines() -> list[dict]:
    examples = {**steward_prompt.STAGE_EXAMPLES, **steward_prompt.AUTHORITY_EXAMPLES}
    lines = []
    for name, body in examples.items():
        if name.startswith("sheets/"):
            lines += YAML(typ="safe").load(body)["items"]
    return lines


def test_the_stewards_examples_and_contract_never_route_to_a_shelf():
    lines = [line for line in _all_example_lines() if line.get("verb") == "route"]
    assert len(lines) >= 5  # control: the examples' route lines were read
    for line in lines:
        assert not str(line.get("dest", "")).startswith("reference"), line
    # the re-decision example now moves a lesson OFF a shelf
    moved = steward_prompt.AUTHORITY_EXAMPLES["cases/move-off-the-shelf.yaml"]
    assert "kind: reconsider" in moved and "references/LEARNINGS.md" in moved
    text = " ".join(steward_prompt._render_output_contract().split())
    assert "NEVER `reference` (or `reference:<file name>`)" in text
    assert "takes a lesson off a reference shelf" in text


def test_the_stewards_method_says_where_a_shelf_lesson_goes():
    method = " ".join((REFS / "steward-method.md").read_text(encoding="utf-8").split())
    assert "## 16. Never a reference shelf" in method
    for phrase in ("a path-scoped rule", "an existing skill", "a warning hook",
                   "park it or reject it", "§14's three tests still decide that"):
        assert phrase in method, phrase
    # the always-loaded test's own wording, which `always_loaded.py` checks, is untouched
    assert "(a path rule, the shelf, a skill)" in method


def test_the_overseer_is_told_and_its_closed_sets_name_the_refusal(tmp_path):
    root = formats.write(tmp_path / "ws", "B")
    sets = YAML(typ="safe").load((root / "closed-sets.yaml").read_text(encoding="utf-8"))
    assert sets["sheet"]["refused_dests"] == ["reference"]
    readme = " ".join((root / "README.md").read_text(encoding="utf-8").split())
    assert "TO claude-md (any variant), skill-md, hook; never new-skill or reference." in readme
    assert "Never route a lesson to `reference`" in readme
    assert "a `reject` or `defer` line takes it off too" in readme
    prompt = overseer_run._phase_b_prompt(tmp_path / "ws", (), ())
    assert "Never route a lesson to `reference`" in " ".join(prompt.split())


def test_the_doctrine_and_the_review_command_say_so():
    doctrine = " ".join((REFS / "routing-doctrine.md").read_text(encoding="utf-8").split())
    assert "The steward and the overseer never route a lesson to `reference`" in doctrine
    review = " ".join(REVIEW_MD.read_text(encoding="utf-8").split())
    assert "A record routed to a `reference` or `hook` destination cannot yet" not in review
    assert "A record routed to a `hook` destination cannot yet be corrected this way" in review
    assert "the steward's and the overseer's runners refuse a route to `reference`" in review
