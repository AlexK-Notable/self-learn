"""S-NEXT-u8-placement (premise-check design, unit U8; the hand-maintenance
cures design, M3): the steward's half of the placement premises.

The sweep half (U2) derives, for every placed lesson, whether a session
still loads its file (`@reach`), whether self-learn may still write there
(`@writable`) and whether its managed block is as self-learn left it
(`@intact`), and confirms a failure after two daily checks. This unit turns
those confirmations into `premise-moved` inputs and lets the steward answer
a person's hand edit in a managed block: fold it into the lesson (`replace`
with `adopt_region: true`) or put the ledger's text back (`premises`
`action: restore-region`). The user agreed to the fold on 2026-10-30
("i agree with the decisions", the cures design's Q4).

What this file pins, each of it failing on master (none of these names
exist there, and on the merged U2+U4 tree without this unit the steward
never sees a placement move):

* the steward reads the sweep's own cache rows (U2 writes them flat, under
  `id` and `at`; U4's reader expected `record` and `observed_at`);
* a confirmed placement failure is a `premise-moved` mover; `@reach` and
  `@writable` wait a week after the lesson's last decision, `@intact` does
  not; a block put right since the sweep is not offered;
* the lessons of one hand-edited block are one group: offered together,
  waiting together, counted once against the nightly cap, kept in one packet;
* `restore-region` puts the ledger's text back in one ledger commit, only on
  the block the daily check confirmed, only for the steward;
* a fold replaces the lesson over exactly the confirmed edit, and only then
  (the same replace without `adopt_region`, the control, is refused);
* the stage rules: a block-writing line only on an `@intact` input, every
  hand-edited lesson of the block in one case with its own fold or restore,
  and the person's lines quoted in the case's evidence;
* the brief shows the person's lines and the diff, and how to decide.

Every scenario runs on a sandbox ledger and host (`support.make_env` under
pytest's tmpdir, never the real `~/.self-learn`). No model call; no probe
runs a program (the lessons here record no written premise, and the
reachability instrument is replaced by fixed verdicts). Ids and texts are
synthetic.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import (
    batch,
    gitops,
    premise_sweep,
    premises,
    steward,
    steward_inputs,
    steward_prompt,
    verbs,
)
from self_learn.overseer import formats as overseer_formats
from support import commit_all, make_env
from test_e3b_agents_replace import _replace_line, _steward_case
from test_replace import NEW_INSTRUCTION
from test_premise_sweep import fake_reach, seed
from test_steward_premise_moved import (
    _apply,
    _body,
    _brief,
    _case,
    _pair,
    _rec,
    _routed,
    _sheet,
    _subject,
)

A = "lrn-a8000001"
B = "lrn-a8000002"
C = "lrn-a8000003"
DAY = 24 * 3600
EDIT = " (a person's correction)"


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
    monkeypatch.setenv("SELF_LEARN_EMBED_PROVIDER", "none")
    # A user-scope placement compiles into ~/.claude: never the real one.
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


# ------------------------------------------------------------- helpers


def _edit_line(env, rid: str, extra: str = EDIT) -> None:
    """A person's hand edit on *rid*'s entry line, committed in the git
    host (an uncommitted one is a dirty target, never written)."""
    lines = env.skill_md.read_text(encoding="utf-8").split("\n")
    edited = [line + extra if f"({rid})" in line else line for line in lines]
    assert edited != lines, f"{rid} has no entry line to edit"
    env.skill_md.write_text("\n".join(edited), encoding="utf-8")
    commit_all(env.host, "a person's hand edit")


def _sweeps(env, monkeypatch, tmp_path, ids: list[str], *, days: tuple[float, ...] = (2, 1)) -> None:
    """The daily sweep on the days given (days ago), into the cache the
    steward and the verbs read (`premise_sweep.default_cache_dir`), with
    the reachability instrument fixed (every lesson reachable)."""
    fake_reach(monkeypatch, env, ids)
    cache = premise_sweep.default_cache_dir(env.ledger)
    for ago in days:
        result = premise_sweep.run(
            env.ledger, cache, now=time.time() - ago * DAY, claude_dir=tmp_path / "no-claude"
        )
        assert result.status in ("ok", "idle"), result


def _intact_rows(home: Path) -> list[dict]:
    return [
        row for row in steward._premise_moved_inputs(home)
        if steward_inputs.intact_group(row) is not None
    ]


def _restore(rid: str, **extra) -> dict:
    return {"id": rid, "verb": "premises", "action": "restore-region",
            "because": "the edit contradicts the lesson", **extra}


def _input(
    rid: str, group: str, *, premise: str = "@intact", predecessor: str | None = None
) -> dict:
    item = {"source": "placement", "premise": premise, "value_sha": "0" * 32}
    if premise == "@intact":
        item["group"] = group
    row = {"record": rid, "kind": steward_inputs.INPUT_PREMISE_MOVED, "moved": [item]}
    if predecessor:
        row["predecessor"] = predecessor
    return row


# ============================ 1. the steward reads what the sweep writes


def test_the_steward_reads_the_sweeps_own_cache_rows(tmp_path, monkeypatch):
    """Fix round 1: U2's rows name the lesson `record` and the time
    `observed_at` (U2 gate round 2); a confirmed placement move reads its
    time from the row the sweep actually wrote, never a stale key."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    rows = premise_sweep.read_history(premise_sweep.default_cache_dir(home))[(A, "@intact")]
    assert rows and all("record" in row and "observed_at" in row for row in rows)  # the shape

    (move,) = [m for m in premise_sweep.confirmed_placement_moves(home) if m.record_id == A]
    assert move.premise_id == "@intact"
    assert move.observed_at == rows[-1]["observed_at"] and move.observed_at != "None"
    (item,) = steward_inputs.placement_moves(home)[A].items
    assert item["now_at"] == rows[-1]["observed_at"]


# ======================================== 2. placement movers and groups


def test_a_confirmed_hand_edit_is_a_premise_moved_input(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A], days=(2,))
    assert _intact_rows(home) == []  # control: one sweep is first sight
    _sweeps(env, monkeypatch, tmp_path, [A], days=(1,))

    (row,) = _intact_rows(home)
    assert row["record"] == A and row["kind"] == steward_inputs.INPUT_PREMISE_MOVED
    (item,) = row["moved"]
    assert item["source"] == "placement" and item["premise"] == "@intact"
    assert item["group"] == str(env.skill_md.resolve())
    assert item["members"] == [A]
    assert "@intact" in row["reason"]
    # the version is the failing state: the same edit is the same input
    assert row["version"] == steward_inputs.premise_moved_version(
        moved=[("@intact", item["value_sha"])]
    )
    # the row is committed with the run record: never the block's text
    assert EDIT.strip() not in json.dumps(row)


def test_a_block_put_right_since_the_sweep_is_not_offered(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    before = env.skill_md.read_text(encoding="utf-8")
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    assert len(_intact_rows(home)) == 1  # control
    # the person takes the edit back; the sweep has not run since
    env.skill_md.write_text(before, encoding="utf-8")
    commit_all(env.host, "the edit taken back")
    assert premise_sweep.confirmed_intact_values(home, env.skill_md)  # still in the cache
    assert _intact_rows(home) == []


def test_the_lessons_of_one_edited_block_are_one_group(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    _edit_line(env, A)
    _edit_line(env, B, " (another note)")
    _sweeps(env, monkeypatch, tmp_path, [A, B])

    rows = _intact_rows(home)
    assert sorted(row["record"] for row in rows) == [A, B]
    for row in rows:
        (item,) = row["moved"]
        assert sorted(item["members"]) == [A, B]
    # an earlier input of the run takes one: the whole group waits
    assert [r for r in steward._premise_moved_inputs(home, exclude={A})
            if steward_inputs.intact_group(r)] == []
    # the group counts as one against the nightly cap
    monkeypatch.setattr(steward_inputs, "PREMISE_MOVED_PER_RUN", 1)
    assert sorted(row["record"] for row in _intact_rows(home)) == [A, B]


def test_a_group_is_kept_in_one_packet():
    plans = [
        steward_inputs.PacketPlan([A, C], [A, C], [{"a": A, "b": C}], {"cosine": 0, "lexical": 0, "none": 1}),
        steward_inputs.PacketPlan([B], [B], [], {"cosine": 0, "lexical": 0, "none": 0}),
    ]
    rows = [_input(A, "/x/SKILL.md"), _input(B, "/x/SKILL.md"), {"record": C, "kind": "lesson"}]
    groups = steward_inputs.intact_groups(rows)
    assert groups == {"/x/SKILL.md": [A, B]}

    kept = steward_inputs.keep_groups_together(plans, groups)
    assert [plan.members for plan in kept] == [[A, C, B]]  # the emptied packet is dropped
    assert plans[1].members == [B]  # the caller's plans are not mutated
    # control: lessons in no group stay where relatedness put them
    assert [p.members for p in steward_inputs.keep_groups_together(plans, {})] == [[A, C], [B]]


def test_reach_and_writable_wait_a_week_after_the_last_decision(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    seed(env, A, routed_at="2026-09-22T06:24:50Z")
    # a plain skills root: the tracked SKILL.md may not be written (S-80)
    (home / "hosts.yaml").write_text(
        f"skills_root:\n  path: {env.host}\n  mode: plain\nprojects: []\n", encoding="utf-8"
    )
    commit_all(home, "a plain skills root")
    _sweeps(env, monkeypatch, tmp_path, [A])
    assert any(m.premise_id == "@writable" for m in premise_sweep.confirmed_placement_moves(home))

    assert steward_inputs.placement_moves(home, today=date(2026, 9, 25)) == {}
    found = steward_inputs.placement_moves(home, today=date(2026, 9, 30))
    (item,) = [i for i in found[A].items if i["premise"] == "@writable"]
    assert "tracked by git" in item["detail"]


def test_a_lesson_retired_since_the_sweep_is_not_offered(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    assert A in steward_inputs.placement_moves(home)  # control
    monkeypatch.setattr(steward_inputs, "_placed_record", lambda h, rid: None)
    assert steward_inputs.placement_moves(home) == {}


# =============================================== 3. restore-region


def test_restore_puts_the_ledgers_text_back_over_the_confirmed_edit(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    before = env.skill_md.read_text(encoding="utf-8")
    _edit_line(env, A)
    assert verbs.lesson_region(home, A).verdict == "edited"

    # before the daily check confirmed it: refused, nothing written
    head = gitops.head_sha(home)
    got = _apply(home, tmp_path, [_restore(A)])
    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert "daily check confirmed" in str(got.detail)
    assert gitops.head_sha(home) == head and EDIT in env.skill_md.read_text(encoding="utf-8")

    _sweeps(env, monkeypatch, tmp_path, [A])
    preview = batch.dry_run(home, _sheet(tmp_path, [_restore(A)]), actor="steward")
    (shown,) = preview.items
    assert shown.state != "would-refuse", shown
    assert gitops.head_sha(home) == head  # the preview wrote nothing

    got = _apply(home, tmp_path, [_restore(A)])
    assert (got.state, got.rc) == ("applied", 0), got
    assert env.skill_md.read_text(encoding="utf-8") == before
    after = verbs.lesson_region(home, A)
    assert after.verdict == "clean" and after.observed == after.expected
    assert _subject(home) == f"self-learn: premises restore-region {A}"
    body = _body(home)
    assert "the edit contradicts the lesson" in body and "it was edited" in body
    # its host write is one a post-run recompile finishes when it is owed
    assert verbs.host_result_ids([got], home) == [A]
    # a second run of the line has nothing to do
    assert _apply(home, tmp_path, [_restore(A)]).state == "already-applied"
    # and the next sweep finds the block intact
    _sweeps(env, monkeypatch, tmp_path, [A], days=(0,))
    assert premise_sweep.confirmed_intact_values(home, env.skill_md) == set()


def test_restore_refuses_a_block_edited_again_since_the_check(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    _edit_line(env, A, " (and a second edit)")
    head = gitops.head_sha(home)

    got = _apply(home, tmp_path, [_restore(A)])

    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert "not the one the daily check confirmed" in str(got.detail)
    assert gitops.head_sha(home) == head
    assert "(and a second edit)" in env.skill_md.read_text(encoding="utf-8")


def test_restore_puts_a_missing_block_back(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    before = env.skill_md.read_text(encoding="utf-8")
    env.skill_md.write_text("# s skill\n\nAuthored prose stays put.\n", encoding="utf-8")
    commit_all(env.host, "a person removed the block")
    assert verbs.lesson_region(home, A).verdict == "missing"
    _sweeps(env, monkeypatch, tmp_path, [A])

    got = _apply(home, tmp_path, [_restore(A)])

    assert (got.state, got.rc) == ("applied", 0), got
    assert f"({A})" in env.skill_md.read_text(encoding="utf-8")
    assert verbs.lesson_region(home, A).verdict == "clean"
    assert env.skill_md.read_text(encoding="utf-8").strip() == before.strip()


@pytest.mark.parametrize("actor", ["overseer", "human"])
def test_only_the_steward_may_rewrite_a_block_over_a_hand_edit(tmp_path, monkeypatch, actor):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    head = gitops.head_sha(home)
    for line in (_restore(A), _replace_line(A, adopt_region=True)):
        sheet = _sheet(tmp_path, [line])
        (shown,) = batch.dry_run(home, sheet, actor=actor).items
        assert (shown.state, shown.kind) == ("would-refuse", "bad-line"), (line, shown)
        (got,) = batch.run(home, sheet, no_push=True, actor=actor).items
        assert (got.state, got.kind) == ("refused", "bad-line"), (line, got)
        assert "the steward's alone" in str(got.detail)
    assert gitops.head_sha(home) == head
    assert EDIT in env.skill_md.read_text(encoding="utf-8")


def test_a_restore_line_names_no_premise(tmp_path):
    with pytest.raises(batch.BatchError, match="takes neither `premises` nor `ids`"):
        _sheet(tmp_path, [_restore(A, ids=["p1"])])
    assert _sheet(tmp_path, [_restore(A)], name="clean")  # control


# ============================================================= 4. the fold


def test_a_fold_replaces_the_lesson_over_exactly_the_confirmed_edit(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])

    # control: the same replace without `adopt_region` is refused by the edit
    plain = _apply(home, tmp_path, [_replace_line(A)])
    assert plain.state == "refused" and verbs.REGION_VERDICT_MARKER in str(plain.detail), plain
    assert _rec(home, A).status == "routed"

    got = _apply(home, tmp_path, [_replace_line(A, adopt_region=True)])

    assert (got.state, got.rc) == ("applied", 0), got
    old = _rec(home, A)
    assert old.status == "superseded" and old.superseded_by
    text = env.skill_md.read_text(encoding="utf-8")
    assert f"({old.superseded_by})" in text and NEW_INSTRUCTION in text
    assert EDIT not in text and f"({A})" not in text
    region = verbs.lesson_region(home, old.superseded_by)
    assert region.verdict == "clean" and region.observed == region.expected
    # the approval never outlives the fold
    assert verbs._APPROVED_EDITED_REGIONS.get() == frozenset()


def test_a_fold_refuses_an_edit_the_daily_check_did_not_confirm(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    head, text = gitops.head_sha(home), env.skill_md.read_text(encoding="utf-8")

    got = _apply(home, tmp_path, [_replace_line(A, adopt_region=True)])

    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert "daily check confirmed" in str(got.detail)
    assert gitops.head_sha(home) == head and env.skill_md.read_text(encoding="utf-8") == text
    assert _rec(home, A).status == "routed"


def test_a_fold_of_a_block_that_is_gone_is_refused(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    env.skill_md.write_text("# s skill\n", encoding="utf-8")
    commit_all(env.host, "a person removed the block")
    _sweeps(env, monkeypatch, tmp_path, [A])

    got = _apply(home, tmp_path, [_replace_line(A, adopt_region=True)])

    assert (got.state, got.kind) == ("refused", "bad-line"), got
    assert "no edit to fold" in str(got.detail)


@pytest.mark.parametrize("extra, fragment", [
    ({"adopt_region": "yes"}, "`adopt_region` is `true` or absent"),
    ({"adopt_region": True, "dest": "claude-md"}, "takes no ['dest']"),
    ({"adopt_region": True, "also": [B]}, "takes no ['also']"),
])
def test_a_fold_line_of_the_wrong_shape_refuses_the_whole_sheet(tmp_path, extra, fragment):
    with pytest.raises(batch.BatchError, match=re.escape(fragment)):
        _sheet(tmp_path, [_replace_line(A, **extra)])
    assert _sheet(tmp_path, [_replace_line(A, adopt_region=True)], name="clean")  # control


# ======================================================= 5. the stage rules


def _fold_case(records: list[str], quotes: list[str]) -> dict:
    case = _steward_case(records)
    case["evidence"] = [{"ref": "SKILL.md#managed", "quote": quote} for quote in quotes]
    return case


def test_a_block_writing_line_stands_only_on_an_intact_input(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    stage = tmp_path / "stage"
    group = str(env.skill_md.resolve())
    pair = _pair(stage, "restore", _case([A], outcome="no-action"), [_restore(A)])

    on_reach = steward._pair_problem(stage, pair, home, {A: _input(A, group, premise="@reach")})
    assert "stands only on a premise-moved input" in (on_reach or "")
    assert steward._pair_problem(stage, pair, home, {A: _input(A, group)}) is None  # control


def test_every_hand_edited_lesson_of_the_block_is_decided_in_one_case(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    _edit_line(env, A)
    _edit_line(env, B, " (another note)")
    stage = tmp_path / "stage"
    group = str(env.skill_md.resolve())
    inputs = {A: _input(A, group), B: _input(B, group)}
    quotes = verbs.edited_region_lines(verbs.lesson_region(home, A))
    assert any(EDIT in q for q in quotes) and any("(another note)" in q for q in quotes)

    alone = _pair(stage, "alone", _case([A], outcome="no-action", evidence=[
        {"ref": "SKILL.md#managed", "quote": q} for q in quotes]), [_restore(A)])
    assert f"add ['{B}'] to its `records`" in (steward._pair_problem(stage, alone, home, inputs) or "")

    noted = _pair(stage, "noted", _case([A, B], outcome="no-action", evidence=[
        {"ref": "SKILL.md#managed", "quote": q} for q in quotes]),
        [_restore(A), {"id": B, "verb": "note", "append": "looked at it"}])
    assert f"['{B}'] carry a hand edit" in (steward._pair_problem(stage, noted, home, inputs) or "")

    unquoted = _pair(stage, "unquoted", _case([A, B], outcome="no-action"),
                     [_restore(A), _restore(B)])
    assert "does not quote what a person wrote" in (
        steward._pair_problem(stage, unquoted, home, inputs) or "")

    both = _pair(stage, "both", _case([A, B], outcome="no-action", evidence=[
        {"ref": "SKILL.md#managed", "quote": q} for q in quotes]), [_restore(A), _restore(B)])
    assert steward._pair_problem(stage, both, home, inputs) is None

    # a fold and a restore in the one case, the person's lines quoted
    mixed = _pair(stage, "mixed", _fold_case([A, B], quotes),
                  [_replace_line(A, adopt_region=True), _restore(B)])
    assert steward._pair_problem(stage, mixed, home, inputs) is None

    # a parked case is never applied: only the first rule binds it
    parked = _case([A], outcome="parked", kind="parked", parked_for="overseer",
                   parked_reason="authority-unclear")
    parked["decision"]["confidence"] = "provisional"
    assert steward._pair_problem(
        stage, _pair(stage, "parked", parked, [_restore(A)]), home, inputs) is None


# ============== 5a. a block whose lessons separate cases placed (fix round 1)
#
# Gate round 1, MAJOR 1: the lessons of one block are often placed by
# different cases (each route has its own). A `kind: reconsider` case
# supersedes one case, so such a group is decided in one `kind: resolution`
# case; before this round the runner raised on it and the whole steward run
# died, on every run, until the attempt cap.


def test_a_block_two_cases_placed_is_decided_in_one_resolution_case(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _routed(env, B)
    _edit_line(env, A)
    _edit_line(env, B, " (another note)")
    stage = tmp_path / "stage"
    group = str(env.skill_md.resolve())
    quotes = verbs.edited_region_lines(verbs.lesson_region(home, A))
    split = {A: _input(A, group, predecessor="case-0000a001"),
             B: _input(B, group, predecessor="case-0000b002")}
    shared = {A: _input(A, group, predecessor="case-0000a001"),
              B: _input(B, group, predecessor="case-0000a001")}
    mixed = {A: _input(A, group, predecessor="case-0000a001"), B: _input(B, group)}
    lines = [_replace_line(A, adopt_region=True), _restore(B)]
    assert steward._split_intact_members(split) == {A, B}
    assert steward._split_intact_members(mixed) == {A, B}  # covered and uncovered differ
    assert steward._split_intact_members(shared) == frozenset()

    reconsider = _steward_case([A, B], kind="reconsider")
    reconsider["evidence"] = [{"ref": "SKILL.md#managed", "quote": q} for q in quotes]
    pair = _pair(stage, "reconsider", reconsider, lines)
    assert "a `kind: reconsider` case supersedes exactly one" in (
        steward._pair_problem(stage, pair, home, split) or "")

    resolution = _pair(stage, "resolution", _fold_case([A, B], quotes), lines)
    assert steward._pair_problem(stage, resolution, home, split) is None
    assert steward._pair_problem(stage, resolution, home, mixed) is None
    # control: lessons one case placed keep the reconsider case 02 §3a.10.7
    # names, and a resolution case may not fold a covered lesson
    assert "only through a kind: reconsider case" in (
        steward._pair_problem(stage, resolution, home, shared) or "")
    assert steward._pair_problem(stage, pair, home, shared) is None
    # only the fold: any other replace of a covered lesson still needs its own case
    plain = _pair(stage, "plain", _fold_case([A, B], quotes),
                  [_replace_line(A), _restore(B)])
    assert "only through a kind: reconsider case" in (
        steward._pair_problem(stage, plain, home, split) or "")


def test_a_reconsider_case_over_two_cases_is_refused_alone_not_raised():
    refusal = steward._spanning_reconsider_refusal(
        "block.yaml", {"kind": "reconsider"}, {"case-0000a001", "case-0000b002"}
    )
    assert refusal is not None and "supersedes exactly one" in refusal
    assert "case-0000a001, case-0000b002" in refusal
    # any other kind records with no predecessor; one predecessor is the fill's
    for kind in ("resolution", "parked"):
        assert steward._spanning_reconsider_refusal(
            "block.yaml", {"kind": kind}, {"case-0000a001", "case-0000b002"}) is None
    assert steward._spanning_reconsider_refusal(
        "block.yaml", {"kind": "reconsider"}, {"case-0000a001"}) is None


def _unit_row(rid: str, predecessor: str | None) -> tuple[str, dict]:
    item = {"source": "placement", "premise": "@intact", "group": "/x/SKILL.md",
            "value_sha": "0" * 32, "since": "2026-10-29T03:30:00Z"}
    row: dict = {"record": rid, "version": f"premise:{rid[-6:]}", "moved": [item]}
    if predecessor:
        row["predecessor"] = predecessor
    return "2026-10-29T03:30:00Z", row


@pytest.mark.parametrize("predecessors, differ", [
    (("case-0000a001", "case-0000b002"), True),
    (("case-0000a001", None), True),
    (("case-0000a001", "case-0000a001"), False),
])
def test_the_brief_says_when_no_one_case_covers_the_block(predecessors, differ):
    rows = {A: _unit_row(A, predecessors[0]), B: _unit_row(B, predecessors[1])}
    placement = {
        rid: steward_inputs.PlacementMoves(rid, list(row["moved"]), since)
        for rid, (since, row) in rows.items()
    }
    offered = steward._premise_moved_units(rows, placement, set(), [])
    assert sorted(row["record"] for row in offered) == [A, B]
    for row in offered:
        (item,) = row["moved"]
        assert sorted(item["members"]) == [A, B]
        assert bool(item.get("cases_differ")) is differ
    told = "\n".join(steward_inputs._placement_decide_lines(
        predecessors[0], ["@intact"], cases_differ=differ))
    resolution = "ONE `kind: resolution` case with no `supersedes`"
    assert (resolution in told) is differ
    assert ("`kind: reconsider` case (the runner fills in" in told) is not differ


def test_a_run_decides_a_block_two_cases_placed_in_one_resolution_case(tmp_path, monkeypatch):
    """End to end through `steward.run`, a fake session, the real stage
    check, recipe, batch and post-run recompile. Each lesson was placed by
    its own case; the packet size is 1, so only `keep_groups_together`
    (gate MINOR 2: nothing ran its call in `_run`) puts the two in the one
    packet whose session sees both. Before this round `_prepared_recipe`
    raised on the case and the run died."""
    from self_learn import cases
    from self_learn.invocation.contract import Outcome
    from test_steward import _configure_steward, _dump_yaml, _stage_dir
    from test_u3b_steward_authority import _route_through_a_case

    env = make_env(tmp_path)
    home = env.ledger
    setup = tmp_path / "setup"
    setup.mkdir()
    placed_a = _route_through_a_case(home, setup, A)
    placed_b = _route_through_a_case(home, setup, B)
    assert placed_a != placed_b
    _edit_line(env, A)
    _edit_line(env, B, " (another note)")
    _sweeps(env, monkeypatch, tmp_path, [A, B])
    rows = {row["record"]: row for row in _intact_rows(home)}
    assert {rid: row.get("predecessor") for rid, row in rows.items()} == {A: placed_a, B: placed_b}
    quotes = verbs.edited_region_lines(verbs.lesson_region(home, A))
    assert len(quotes) == 2
    _configure_steward(home, packet_size=1)
    seen: list[str] = []

    def session(spec):
        seen.append(spec.prompt)
        briefs = set(re.findall(r"^### brief: (lrn-[0-9a-f]{8})$", spec.prompt, re.M))
        if briefs == {A, B}:
            stage = _stage_dir(spec)
            case = _fold_case([A, B], quotes)
            case["question"] = "a person edited these lessons' block: fold it in or put it back?"
            _dump_yaml(stage / "cases" / "block.yaml", case)
            _dump_yaml(stage / "sheets" / "block.yaml", {
                "version": 1, "case": "$CASE_ID",
                "items": [_replace_line(A, adopt_region=True), _restore(B)],
            })
        return Outcome(ok=True, rc=0, stdout="", detail="", failure=None)

    monkeypatch.setattr(steward.invocation, "write_session", session)
    result = steward.run(home)

    assert result.status == "applied", result
    assert len(seen) == 1, "the group was split across packets"
    assert "ONE `kind: resolution` case with no `supersedes`" in seen[0]
    old = _rec(home, A)
    assert old.status == "superseded" and old.superseded_by
    text = env.skill_md.read_text(encoding="utf-8")
    assert NEW_INSTRUCTION in text and f"({B})" in text and f"({A})" not in text
    assert EDIT not in text and "(another note)" not in text
    assert verbs.lesson_region(home, B).verdict == "clean"
    (decided,) = [c for c in cases.list_cases(home, record_id=B) if c["case"] != placed_b]
    assert decided["kind"] == "resolution" and not decided.get("supersedes")
    # decided: neither block edit is offered again
    assert _intact_rows(home) == []


# ============================== 5b. where a whole-block write is refused


def test_a_block_write_is_refused_on_a_dirty_git_target(tmp_path, monkeypatch):
    """Gate MINOR 3: a person's uncommitted work in a git host's target is
    never overwritten by a fold or a restore (`verbs._refuse_block_write`)."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    # outside the managed block, uncommitted: the block itself is the confirmed one
    draft = env.skill_md.read_text(encoding="utf-8") + "\nA person's draft, not committed.\n"
    env.skill_md.write_text(draft, encoding="utf-8")
    head = gitops.head_sha(home)

    for line in (_restore(A), _replace_line(A, adopt_region=True)):
        got = _apply(home, tmp_path, [line])
        assert (got.state, got.kind) == ("refused", "bad-line"), (line, got)
        assert "uncommitted changes" in str(got.detail), got
    assert gitops.head_sha(home) == head
    assert env.skill_md.read_text(encoding="utf-8") == draft

    commit_all(env.host, "the person commits the draft")  # control
    got = _apply(home, tmp_path, [_restore(A)])
    assert (got.state, got.rc) == ("applied", 0), got
    text = env.skill_md.read_text(encoding="utf-8")
    assert EDIT not in text and "A person's draft, not committed." in text


def test_a_block_write_is_refused_on_a_file_git_tracks_in_a_plain_host(tmp_path, monkeypatch):
    """Gate MINOR 3: a plain host's file git tracks is never written (S-80)."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    hosts = (home / "hosts.yaml").read_text(encoding="utf-8")
    (home / "hosts.yaml").write_text(
        f"skills_root:\n  path: {env.host}\n  mode: plain\nprojects:\n  - path: {env.host}\n",
        encoding="utf-8",
    )
    commit_all(home, "the skills root is a plain host")
    head, text = gitops.head_sha(home), env.skill_md.read_text(encoding="utf-8")

    for line in (_restore(A), _replace_line(A, adopt_region=True)):
        got = _apply(home, tmp_path, [line])
        assert got.state == "refused", (line, got)
    assert gitops.head_sha(home) == head
    assert env.skill_md.read_text(encoding="utf-8") == text

    (home / "hosts.yaml").write_text(hosts, encoding="utf-8")  # control: a git host again
    commit_all(home, "the skills root is a git host again")
    assert _apply(home, tmp_path, [_restore(A)]).state == "applied"


# ======================= 5c. a heading a person wrote survives (fix round 1)


def test_a_heading_a_person_wrote_is_quoted_by_its_words(tmp_path):
    """Gate MINOR 4: the runner drops an evidence item with a line that
    starts with `## ` before the case is recorded, so a check that accepted
    that quote let the person's heading go unrecorded."""
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    lines = env.skill_md.read_text(encoding="utf-8").split("\n")
    edited = [line + "\n## Notes from a person" if f"({A})" in line else line for line in lines]
    env.skill_md.write_text("\n".join(edited), encoding="utf-8")
    commit_all(env.host, "a person added a heading inside the block")
    assert "## Notes from a person" in verbs.edited_region_lines(verbs.lesson_region(home, A))
    stage = tmp_path / "stage"
    inputs = {A: _input(A, str(env.skill_md.resolve()))}
    cited = {"ref": "transcript:fake#L1", "quote": "status: pending"}

    verbatim = _pair(stage, "verbatim", _case([A], outcome="no-action", evidence=[
        cited, {"ref": "SKILL.md#managed", "quote": "## Notes from a person"}]), [_restore(A)])
    assert "does not quote what a person wrote" in (
        steward._pair_problem(stage, verbatim, home, inputs) or "")

    words = _pair(stage, "words", _case([A], outcome="no-action", evidence=[
        cited, {"ref": "SKILL.md#managed", "quote": "Notes from a person"}]), [_restore(A)])
    assert steward._pair_problem(stage, words, home, inputs) is None
    assert steward_inputs.quotable_line("## Notes from a person") == "Notes from a person"
    assert steward_inputs.quotable_line("- a line (lrn-a8000001)") == "- a line (lrn-a8000001)"


# ===================== 5d. a restore that crashed before its host write


def test_a_restore_that_crashed_before_its_host_write_is_finished_on_recovery(
    tmp_path, monkeypatch
):
    """Gate MINOR 1: a `restore-region` line commits the ledger, then writes
    the block. A run that died in between left a `stale` block -- the
    person's words the case chose to overwrite, still loaded -- which the
    daily check reads as intact, so nothing offered it again. Recovery now
    proves the line by its commit subject and finishes the host write."""
    from self_learn import execution_evidence

    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    before = env.skill_md.read_text(encoding="utf-8")
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    start = gitops.head_sha(home)
    with monkeypatch.context() as crash:
        crash.setattr(verbs, "_host_phase", lambda *a, **k: None)  # dies before the block
        verbs.restore_region(home, A, because="the edit contradicts the lesson", no_push=True)
    restored = gitops.head_sha(home)
    assert restored != start
    assert EDIT in env.skill_md.read_text(encoding="utf-8")  # the half-state
    assert verbs.lesson_region(home, A).verdict == "stale"

    sheet = _sheet(tmp_path, [_restore(A)], name="recover")
    monkeypatch.setattr(steward, "_committed_receipts", lambda *a, **k: {})
    monkeypatch.setattr(execution_evidence, "validate_manifest_ref", lambda *a, **k: None)
    found = {"sha": start}
    monkeypatch.setattr(execution_evidence, "find_mutation_commit", lambda *a, **k: found["sha"])
    manifest = {"run_id": "run-0000u8re", "start_head": start}
    recipe = {"sheet_sha": "a" * 8, "sheet_digest": "b" * 64}

    # control: a commit that is not this lesson's restore proves nothing
    assert steward._recovered_items(home, manifest, "case-0000abcd", recipe, sheet) == {}
    assert EDIT in env.skill_md.read_text(encoding="utf-8")

    found["sha"] = restored
    done = steward._recovered_items(home, manifest, "case-0000abcd", recipe, sheet)

    assert done[1].state == "applied", (done[1].state, done[1].detail)
    assert env.skill_md.read_text(encoding="utf-8") == before
    assert verbs.lesson_region(home, A).verdict == "clean"
    assert verbs.host_result_ids([done[1]], home) == [A]


# ================================================================ 6. the brief


def test_the_brief_shows_the_persons_lines_the_diff_and_how_to_decide(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    _edit_line(env, A)
    _sweeps(env, monkeypatch, tmp_path, [A])
    (row,) = _intact_rows(home)

    body = _brief(home, row)

    assert "placement @intact moved: a person edited this lesson's managed block by hand" in body
    assert "the lines a person wrote there" in body
    edited = [line for line in body.splitlines() if line.strip().startswith("| ")]
    assert edited and all(EDIT in line for line in edited)
    assert "the diff (- the ledger's text, + the block on disk):" in body
    assert any(line.strip().startswith("+") and EDIT in line for line in body.splitlines())
    assert "[how to decide the hand edit]" in body
    assert "`adopt_region: true`" in body and "`action: restore-region`" in body
    # a placement mover owes no rebaseline, so U4's note-only advice is not given
    assert "one `note` item" not in body


def test_a_lesson_that_cannot_be_written_is_told_how_to_move(tmp_path):
    env = make_env(tmp_path)
    home = env.ledger
    _routed(env, A)
    row = {"record": A, "kind": steward_inputs.INPUT_PREMISE_MOVED, "moved": [{
        "source": "placement", "premise": "@writable", "claim": "self-learn may write there",
        "now": "tracked by git", "value_sha": "0" * 32, "since": "2026-10-29T03:30:00Z",
        "now_at": "2026-10-30T03:30:00Z",
    }]}
    body = _brief(home, row)
    assert "placement @writable moved: self-learn may no longer write where this lesson sits" in body
    assert "[how to decide where it sits]" in body
    # no case covers it: S-NEXT-u4-steward's resolution reroute moves it
    assert "a `route` line with the `dest` it should have (applied as a reroute)" in body
    assert "text_from" not in body
    assert "[how to decide the hand edit]" not in body  # control


# ============================================ 7. what the steward is told


def test_the_contract_and_the_overseer_formats_agree(tmp_path):
    """The method's text (steward-method section 17) is the premise-spec
    lane's, as it is for U4 (S-NEXT-u4-steward's fix round 1): this lane
    writes none of its own, so only the contract and the overseer's formats
    are pinned here."""
    contract = " ".join(steward_prompt._render_output_contract().split())
    assert "adopt_region" in contract and "restore-region" in contract
    assert "A PLACEMENT premise (`@reach`, `@writable`, `@intact`; method section 17)" in contract
    assert "that one case is `kind: resolution` with no `supersedes`" in contract
    root = overseer_formats.write(tmp_path / "ws", "B")
    sets = YAML(typ="safe").load((root / "closed-sets.yaml").read_text(encoding="utf-8"))
    replace_keys = sets["sheet"]["verbs"]["replace"]["keys"]
    assert "adopt_region" not in replace_keys and "because" in replace_keys  # with a control


def test_a_restore_commit_is_found_as_its_lines_proof():
    from self_learn import execution_evidence

    ref = execution_evidence.ExecutionRef(
        run_id="run-u8-restore", case_id="case-acde1234", sheet_sha="12ab34cd",
        sheet_digest="a" * 64, item=1, record_id=A, verb="premises", actor="steward",
    )
    assert execution_evidence._subject_matches(ref, f"self-learn: premises restore-region {A}")
    assert not execution_evidence._subject_matches(ref, f"self-learn: premises restore-region {B}")


def test_only_a_restore_owes_a_host_result_among_premises_lines():
    restored = batch.ItemResult(n=1, id=A, verb="premises", rc=0, state="applied",
                                detail=f"self-learn: premises restore-region {A}")
    rebased = batch.ItemResult(n=2, id=B, verb="premises", rc=0, state="applied",
                               detail=f"self-learn: premises rebaseline {B}")
    assert verbs.host_result_ids([restored, rebased]) == [A]


def test_the_one_spelling_of_a_failing_intact_value():
    assert premises.intact_failing_value("edited", "ab" * 32) == "edited:" + "ab" * 32
    assert premises.intact_failing_value("missing", None) == "region-missing"
    for verdict in ("clean", "stale", "unknown", "fresh"):
        assert premises.intact_failing_value(verdict, "ab" * 32) is None
    assert premises.intact_value_sha("edited", "cd" * 32) == premises.value_sha(
        premises.normalize_value("edited:" + "cd" * 32)
    )
