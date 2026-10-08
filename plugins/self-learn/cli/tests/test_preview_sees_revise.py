"""E0b: the batch preview sees a `revise` earlier in the same sheet.

S-79 refuses a route whose lesson would head into a managed line with a
multi-line Trigger, Instruction or Fact, and tells the writer to put the
loaded text on one line. An agent does that with a `revise` line placed
before the `route` line of the same sheet. `batch.dry_run` used to preview
every line against the ledger AS IT IS ON DISK, one line at a time, so:

1. ``[revise X -> one line, route X]`` previewed the route as refused (a
   false refusal): the steward's repair turn asked it to fix what line 1
   already fixed, and its sequence check held the whole case back, although
   `batch.run` applies both lines;
2. ``[revise X -> two lines, route X]`` previewed both lines as applying,
   and the run applied the revise and then refused the route -- half a case,
   outside the repair turn.

The preview now reads each lesson as the earlier lines of the same sheet
would leave it, when those lines would apply (an in-memory overlay, one per
preview; nothing is written). This file pins that for a person and for the
steward and overseer actors, through `batch.dry_run` AND `batch.run` on the
same sheet, plus the steward's own sequence check and repair turn as black
boxes.

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir); no model is called.
"""

from __future__ import annotations

import pytest
from ruamel.yaml import YAML

from self_learn import batch, steward, verbs
from self_learn.ledger_ops import (
    create_record,
    find_record_path,
    stamp_proposal,
    write_proposal,
)
from self_learn.records import Record
from support import commit_all, git, last_verb_sha, make_behavior, make_env

from test_route_hook import TRIGGER, hook_proposal

ONE = "First line, the loaded sentence."
TWO = "First line, the loaded sentence.\nSecond line, which would be cut."
TRIGGER_TWO = "About to edit X.\nOr about to touch Y."
TRIGGER_ONE = "About to edit X."
#: Built at runtime: the repository's secret hooks refuse the literal.
SECRET = "key is ghp_" + "c" * 36

X = "lrn-0e0b0001"
Y = "lrn-0e0b0002"

ACTORS = ["human", "steward", "overseer"]

#: What a preview state becomes when the same line runs.
_RUN_STATE = {
    "would-apply": "applied",
    "already-applied": "already-applied",
    "would-refuse": "refused",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    sandbox = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(sandbox.ledger))
    return sandbox


def _seed(env, rid, **kwargs):
    create_record(env.ledger, make_behavior(record_id=rid, **kwargs))
    commit_all(env.ledger, f"seed {rid}")


def _write_sheet(path, items):
    with path.open("w", encoding="utf-8") as fh:
        YAML().dump({"version": 1, "items": items}, fh)


def _sheet(tmp_path, items, name="sheet.yaml"):
    path = tmp_path / name
    _write_sheet(path, items)
    return batch.load_sheet(path)


def _revise(rid, section, text, because="put the loaded text on one line"):
    return {"id": rid, "verb": "revise", "section": section, "text": text,
            "because": because}


def _route(rid, dest="skill-md"):
    return {"id": rid, "verb": "route", "dest": dest}


def _shown(preview):
    return [(i.verb, i.state, i.kind) for i in preview.items]


def _ran(result):
    return [(i.verb, i.state, i.kind) for i in result.items]


def _as_run(shown):
    return [(verb, _RUN_STATE[state], kind) for verb, state, kind in shown]


# ------------------------------------------------------------ case 1 and case 2


@pytest.mark.parametrize("actor", ACTORS)
def test_a_revise_to_one_line_lets_the_route_after_it_preview_clean(env, tmp_path, actor):
    """Case 1: the fix S-79's own refusal asks for, placed before the route,
    previews clean -- and the run over the same sheet applies both lines."""
    _seed(env, X, instruction=TWO)
    sheet = _sheet(tmp_path, [_revise(X, "Instruction", ONE), _route(X)])
    path = find_record_path(env.ledger, X)
    record_before = path.read_bytes()
    head_before = last_verb_sha(env.ledger)

    preview = batch.dry_run(env.ledger, sheet, actor=actor)
    assert _shown(preview) == [("revise", "would-apply", None), ("route", "would-apply", None)]
    assert preview.ok
    # the overlay lives in memory only: the preview wrote nothing at all
    assert path.read_bytes() == record_before
    assert last_verb_sha(env.ledger) == head_before
    assert git(env.ledger, "status", "--porcelain").stdout == ""

    result = batch.run(env.ledger, sheet, no_push=True, actor=actor)
    assert _ran(result) == _as_run(_shown(preview))
    # positive control for the three "wrote nothing" checks above: the run moves them
    assert last_verb_sha(env.ledger) != head_before
    assert not path.exists()  # routed: the record left pending/
    assert f"*({X})*" in env.skill_md.read_text(encoding="utf-8")


@pytest.mark.parametrize("actor", ACTORS)
def test_a_revise_to_two_lines_makes_the_route_after_it_preview_refused(env, tmp_path, actor):
    """Case 2: the mirror image is caught by the preview, before anything
    applies, with the same sentence and kind the run gives."""
    _seed(env, X, instruction=ONE)
    sheet = _sheet(tmp_path, [_revise(X, "Instruction", TWO), _route(X)])
    skill_before = env.skill_md.read_bytes()

    preview = batch.dry_run(env.ledger, sheet, actor=actor)
    assert _shown(preview) == [("revise", "would-apply", None), ("route", "would-refuse", "bad-line")]
    shown = preview.items[1].detail or ""
    assert X in shown and "Instruction (2 lines)" in shown and "## Context" in shown

    result = batch.run(env.ledger, sheet, no_push=True, actor=actor)
    assert _ran(result) == _as_run(_shown(preview))
    assert result.items[1].detail == shown  # one sentence, both ways
    assert env.skill_md.read_bytes() == skill_before  # nothing cut, nothing written


def test_the_route_preview_predicts_the_revised_line_the_run_writes(env, tmp_path):
    """The byte prediction a route preview carries is computed from the
    lesson as the earlier revise leaves it: the line it predicts is the line
    the run writes."""
    _seed(env, X, instruction="Stop the container first.")
    sheet = _sheet(tmp_path, [
        _revise(X, "Instruction", "Halt the container before any edit.", because="clearer"),
        _route(X),
    ])

    preview = batch.dry_run(env.ledger, sheet, actor="steward")
    assert _shown(preview) == [("revise", "would-apply", None), ("route", "would-apply", None)]
    diff = ((preview.items[1].route_preview or {}).get("diff") or {}).get("unified") or ""
    (predicted,) = [
        line[1:] for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++") and X in line
    ]
    assert "halt the container before any edit" in predicted
    assert "stop the container" not in predicted

    result = batch.run(env.ledger, sheet, no_push=True, actor="steward")
    assert _ran(result) == _as_run(_shown(preview))
    assert predicted in env.skill_md.read_text(encoding="utf-8").splitlines()


# ------------------------------------------------- the steward, as a black box


def test_the_stewards_sequence_check_passes_case_one_and_holds_case_two(env, tmp_path):
    _seed(env, X, instruction=TWO)
    _seed(env, Y, instruction=ONE)
    one = _sheet(tmp_path, [_revise(X, "Instruction", ONE), _route(X)], "one.yaml")
    two = _sheet(tmp_path, [_revise(Y, "Instruction", TWO), _route(Y)], "two.yaml")

    p_one = batch.dry_run(env.ledger, one, actor="steward")
    p_two = batch.dry_run(env.ledger, two, actor="steward")

    assert steward._preview_is_clean_for_sequence(p_one, one) is True
    assert steward._held_refusals(p_one, one) == []
    assert steward._preview_is_clean_for_sequence(p_two, two) is False
    held = steward._held_refusals(p_two, two)
    assert [(h["n"], h["id"], h["verb"], h["kind"]) for h in held] == [(2, Y, "route", "bad-line")]


def test_the_repair_turn_asks_about_case_two_and_not_about_case_one(env, tmp_path):
    """The steward's repair turn (`_ledger_repair_message`) previews every
    staged sheet: case 1's route is not sent back as wrong, case 2's is,
    before anything applies."""
    _seed(env, X, instruction=TWO)
    _seed(env, Y, instruction=ONE)
    stage = tmp_path / "stage"
    (stage / "cases").mkdir(parents=True)
    (stage / "sheets").mkdir()
    for name, rid, text in (("one", X, ONE), ("two", Y, TWO)):
        YAML().dump({"kind": "route", "id": rid},
                    (stage / "cases" / f"{name}.yaml").open("w", encoding="utf-8"))
        _write_sheet(stage / "sheets" / f"{name}.yaml",
                     [_revise(rid, "Instruction", text), _route(rid)])

    message = steward._ledger_repair_message(
        env.ledger, stage, {X: "pending", Y: "pending"}
    )
    assert message is not None
    assert f"sheets/two.yaml: item 2 (route {Y})" in message
    assert "Instruction (2 lines)" in message
    assert "sheets/one.yaml" not in message
    assert X not in message


# ------------------------------------------------------------ what the overlay is


def test_a_revise_the_preview_refuses_leaves_the_lesson_as_it_is_on_disk(env, tmp_path):
    """X's revise would put the Instruction on one line, but the preview
    refuses it (its text trips the secret scan), so X's route is previewed
    against the two lines on disk -- refused, as the run refuses it. Y, in
    the same sheet, is the control that the overlay is live in this very
    preview."""
    _seed(env, X, instruction=TWO)
    _seed(env, Y, instruction=TWO)
    sheet = _sheet(tmp_path, [
        _revise(X, "Instruction", f"{ONE} The {SECRET}."),
        _route(X),
        _revise(Y, "Instruction", ONE),
        _route(Y),
    ])

    preview = batch.dry_run(env.ledger, sheet, actor="steward")
    states = [(i.verb, i.state) for i in preview.items]
    assert states == [
        ("revise", "would-refuse"), ("route", "would-refuse"),
        ("revise", "would-apply"), ("route", "would-apply"),
    ]
    assert preview.items[1].kind == "bad-line"
    assert X in (preview.items[1].detail or "") and "Instruction (2 lines)" in (preview.items[1].detail or "")

    result = batch.run(env.ledger, sheet, no_push=True, actor="steward")
    assert _ran(result) == _as_run(_shown(preview))
    assert result.items[1].detail == preview.items[1].detail
    assert f"*({Y})*" in env.skill_md.read_text(encoding="utf-8")
    assert f"*({X})*" not in env.skill_md.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "seed, items, expected",
    [
        pytest.param(
            {"trigger": TRIGGER_TWO, "instruction": TWO},
            [_revise(X, "Trigger", TRIGGER_ONE), _revise(X, "Instruction", ONE), _route(X)],
            ["would-apply", "would-apply", "would-apply"],
            id="two-sections-both-carried-to-the-route",
        ),
        pytest.param(
            {"instruction": TWO},
            [_revise(X, "Instruction", ONE), _revise(X, "Instruction", ONE), _route(X)],
            ["would-apply", "already-applied", "would-apply"],
            id="the-same-revise-twice-is-already-applied-the-second-time",
        ),
        pytest.param(
            {"instruction": TWO},
            [_revise(X, "Instruction", ONE), _revise(X, "Instruction", TWO), _route(X)],
            ["would-apply", "would-apply", "would-refuse"],
            id="the-later-revise-wins",
        ),
    ],
)
def test_two_revises_of_one_lesson_chain_in_sheet_order(env, tmp_path, seed, items, expected):
    _seed(env, X, **seed)
    sheet = _sheet(tmp_path, items)

    preview = batch.dry_run(env.ledger, sheet, actor="steward")
    assert [i.state for i in preview.items] == expected, [i.detail for i in preview.items]

    result = batch.run(env.ledger, sheet, no_push=True, actor="steward")
    assert _ran(result) == _as_run(_shown(preview))
    if expected[-1] == "would-refuse":
        assert result.items[-1].detail == preview.items[-1].detail


def test_a_revise_of_one_lesson_does_not_reach_the_route_of_another(env, tmp_path):
    _seed(env, X, instruction=TWO)
    _seed(env, Y, instruction=TWO)
    sheet = _sheet(tmp_path, [_revise(X, "Instruction", ONE), _route(Y), _route(X)])

    preview = batch.dry_run(env.ledger, sheet, actor="steward")
    assert _shown(preview) == [
        ("revise", "would-apply", None),
        ("route", "would-refuse", "bad-line"),
        ("route", "would-apply", None),
    ]
    refused = preview.items[1].detail or ""
    assert refused.startswith(f"{Y}:") and X not in refused

    result = batch.run(env.ledger, sheet, no_push=True, actor="steward")
    assert _ran(result) == _as_run(_shown(preview))
    assert result.items[1].detail == refused


def test_a_hook_route_after_a_revise_previews_the_stale_analysis_refusal(env, tmp_path):
    """Another check that reads the lesson's text: a proposal-carried hook is
    bound to the body the analyst saw (`record_sha`). A revise before the
    hook route makes the run refuse it; the preview now says so too."""
    create_record(env.ledger, make_behavior(record_id=X, trigger=TRIGGER))
    write_proposal(env.ledger, X, hook_proposal())
    stamp_proposal(env.ledger, X)
    commit_all(env.ledger, f"seed {X}")
    # control: on its own, the hook route previews clean
    alone = _sheet(tmp_path, [_route(X, "hook")], "alone.yaml")
    assert _shown(batch.dry_run(env.ledger, alone, actor="overseer")) == [
        ("route", "would-apply", None)
    ]

    sheet = _sheet(tmp_path, [
        _revise(X, "Instruction", "Stop the HA container before touching .storage.",
                because="clearer"),
        _route(X, "hook"),
    ])
    preview = batch.dry_run(env.ledger, sheet, actor="overseer")
    assert [(i.verb, i.state) for i in preview.items] == [
        ("revise", "would-apply"), ("route", "would-refuse")
    ]
    assert "record_sha mismatch" in (preview.items[1].detail or "")

    result = batch.run(env.ledger, sheet, no_push=True, actor="overseer")
    assert _ran(result) == _as_run(_shown(preview))
    assert result.items[1].detail == preview.items[1].detail


# ------------------------------------------------- the override's own guards


def test_a_record_file_naming_another_id_never_crashes_the_preview(env, tmp_path):
    """A hand-corrupted record file (X's file, Y's id in its frontmatter)
    gets no overlay: the preview still returns a verdict per line, the
    route read against the two lines on disk, instead of raising."""
    _seed(env, X, instruction=TWO)
    path = find_record_path(env.ledger, X)
    path.write_text(
        path.read_text(encoding="utf-8").replace(f"id: {X}", f"id: {Y}"), encoding="utf-8"
    )
    commit_all(env.ledger, "corrupt the id")
    sheet = _sheet(tmp_path, [_revise(X, "Instruction", ONE), _route(X)])

    preview = batch.dry_run(env.ledger, sheet, actor="steward")
    assert [i.verb for i in preview.items] == ["revise", "route"]
    assert preview.items[1].state == "would-refuse"


def test_route_dry_run_refuses_an_override_for_another_lesson(env):
    _seed(env, X, instruction=ONE)
    _seed(env, Y, instruction=ONE)
    other = Record.from_path(find_record_path(env.ledger, Y))
    with pytest.raises(ValueError):
        verbs.route_dry_run(env.ledger, X, dest="skill-md", record_override=other)


def test_route_dry_run_never_changes_the_override_it_is_given(env):
    _seed(env, X, instruction=ONE)
    override = Record.from_path(find_record_path(env.ledger, X))
    before = override.to_text()
    preview = verbs.route_dry_run(env.ledger, X, dest="skill-md", record_override=override)
    assert preview.would_refuse == []  # positive control: a full route preview ran
    assert override.to_text() == before
