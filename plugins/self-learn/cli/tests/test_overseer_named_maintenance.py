"""E3b (2026-10-11): the overseer's named `kind: maintenance` pairs, and the
steward's coverage rule for a merge (D-AUTHOR §2.8; build plan E3b).

Before E3b every NAMED pair (`case-<name>.yaml` + `sheet-<name>.yaml`) was
a successor: `_validate_successor` required `supersedes`, so a catalogue
change -- a shortening, a merge, a correction no case covers -- could only
be the run's ONE caseless `case.yaml` + `sheet.yaml`. The 2026-10-04 report
had several such changes in one week and could write none of them.

(a) several named maintenance pairs beside a successor pair all apply, end
    to end through the overseer's runner and the REAL batch: one replaces
    a placed lesson, one merges two placed lessons; each new line compiles
    to ONE physical line;
(b) a merge case whose `also` lessons have no item of their own passes the
    steward's coverage check, and a lesson in neither `id` nor `also` is
    still refused;
plus each pair a runner drops, by name: a replace case without
`decision.rewrite`, and a sheet whose `also` names a lesson outside the
case's `records` -- in both runners.

Sandbox ledgers and hosts (`support.make_env`), fake model sessions; the
runners, `batch` and `cases` are the real code. No model call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import cases, steward
from self_learn.overseer import formats
from self_learn.overseer import run as overseer_run
from test_failstate_overseer import _dump, _ok, _phase_a, _phase_b_common, _seed_parked, _successor
from test_overseer_run import _enabled
from test_replace import Env, _place, _rec, _seed

NEW_A = ("About to run another round of the same review.",
         "Stop when the yield per round is flat: that is a steady state, not convergence.")
NEW_B = ("About to trust one failing run of a timing-sensitive test.",
         "Rerun it before acting: one failure under load is a lead, not a result.")


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _rewrite(*ideas: str) -> dict:
    return {"ideas": [{"idea": idea, "now": "loaded"} for idea in ideas]}


def _maintenance(records: list[str], *, rewrite: dict | None) -> dict:
    case = {
        "kind": "maintenance", "trigger": "weekly", "outcome": "replaced",
        "records": records, "scope": "skill:s",
        "question": "Can these lessons say the same in fewer words, or as one?",
        "evidence": [{"ref": f"record:{rid}", "quote": "status: routed"} for rid in records],
        "decision": {"verb": "replace", "because": "the same meaning, loaded once",
                     "confidence": "settled"},
    }
    if rewrite is not None:
        case["decision"]["rewrite"] = rewrite
    return case


def _replace_sheet(rid: str, text: tuple[str, str], also: list[str] | None = None) -> dict:
    item = {"id": rid, "verb": "replace", "trigger": text[0], "instruction": text[1],
            "because": "shorter, one line"}
    if also:
        item["also"] = also
    return {"version": 1, "items": [item]}


def _run(home: Path, monkeypatch, pairs: dict[str, tuple[dict, dict]]) -> overseer_run.RunResult:
    def invoke(spec):
        if spec.label == "phase-a":
            _phase_a(spec.cwd)
        else:
            _phase_b_common(spec.cwd)
            for name, (case, sheet) in pairs.items():
                _dump(spec.cwd / f"case-{name}.yaml", case)
                _dump(spec.cwd / f"sheet-{name}.yaml", sheet)
        return _ok()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)
    return overseer_run.run(home, no_push=True, manual=True)


def _refused_section(home: Path) -> str:
    report = (home / "overseer" / "latest-report.md").read_text(encoding="utf-8")
    assert "## Refused / could not do" in report  # positive control: the section rendered
    return report.split("## Refused / could not do", 1)[1].split("\n## ", 1)[0]


def _line_of(text: str, rid: str) -> list[str]:
    return [line for line in text.splitlines() if f"*({rid})*" in line]


# ------------------------------------------------------------------ (a)


def test_several_named_maintenance_pairs_beside_a_successor_all_apply(env, tmp_path, monkeypatch):
    """Two named maintenance pairs -- a shortening of a placed lesson and a
    merge of two placed lessons -- beside a successor that decides a parked
    case: all three apply in one run, through the real batch. Each new
    lesson's compiled line is ONE physical line carrying its whole
    instruction. On d960042 both maintenance pairs were dropped ("missing
    successor field(s) ['supersedes']")."""
    _enabled(monkeypatch)
    a, b, c = (_seed(env.home, rid) for rid in ("lrn-e3b0b001", "lrn-e3b0b002", "lrn-e3b0b003"))
    for rid in (a, b, c):
        _place(env.home, rid, "skill-md")
    pending = "lrn-e3b0b004"
    parked = _seed_parked(env.home, tmp_path, pending, "parked")
    before = env.skill_md.read_text(encoding="utf-8")
    assert all(_line_of(before, rid) for rid in (a, b, c))  # positive control

    result = _run(env.home, monkeypatch, {
        "shorten": (_maintenance([a], rewrite=_rewrite("stop when the yield is flat")),
                    _replace_sheet(a, NEW_A)),
        "merge": (_maintenance([b, c], rewrite=_rewrite("rerun a timing failure first")),
                  _replace_sheet(b, NEW_B, also=[c])),
        "decide": (_successor(pending, parked),
                   {"version": 1, "items": [{"id": pending, "verb": "reject"}]}),
    })

    assert overseer_run._unfinished_manifest(env.home) is None, result  # the run completed
    refused = _refused_section(env.home)
    assert "dropped" not in refused, refused
    new_a, new_b = _rec(env.home, a).superseded_by, _rec(env.home, b).superseded_by
    assert new_a and new_b and new_a != new_b
    assert (_rec(env.home, c).status, _rec(env.home, c).superseded_by) == ("superseded", new_b)
    assert _rec(env.home, pending).status == "rejected"
    text = env.skill_md.read_text(encoding="utf-8")
    for old in (a, b, c):
        assert not _line_of(text, old), old
    for new, words in ((new_a, NEW_A), (new_b, NEW_B)):
        (line,) = _line_of(text, new)  # exactly one physical line names it ...
        assert words[1].rstrip(".").lower() in line.lower()  # ... and carries the whole instruction
    # the maintenance cases are recorded as the overseer's, superseding nothing
    rows = {row["case"]: row for row in cases.list_cases(env.home, only_ok=True)}
    made = [row for row in rows.values() if row.get("kind") == "maintenance"]
    assert len(made) == 2 and all(row.get("actor") == "overseer" for row in made)
    assert all(not row.get("supersedes") for row in made)


def test_a_named_pair_takes_its_validator_from_its_kind(tmp_path):
    """`_is_maintenance_pair`: `case.yaml` always; a named case by its
    `kind`. A named maintenance case that names `supersedes` is still
    refused, and a named successor without `supersedes` still is too."""
    stage = tmp_path
    maintenance = _maintenance(["lrn-e3b0c001"], rewrite=_rewrite("x"))
    _dump(stage / "case-m.yaml", maintenance)
    _dump(stage / "case-r.yaml", {**maintenance, "kind": "resolution"})
    _dump(stage / "case.yaml", {**maintenance, "kind": "resolution"})
    assert overseer_run._is_maintenance_pair(stage / "case-m.yaml") is True
    assert overseer_run._is_maintenance_pair(stage / "case-r.yaml") is False
    assert overseer_run._is_maintenance_pair(stage / "case.yaml") is True  # validated as one ...
    with pytest.raises(overseer_run.OverseerError, match="must be kind: maintenance"):
        overseer_run._validate_maintenance_case(stage / "case.yaml")  # ... and refused as one
    overseer_run._validate_maintenance_case(stage / "case-m.yaml")
    _dump(stage / "case-s.yaml", {**maintenance, "supersedes": "case-0000000a"})
    with pytest.raises(overseer_run.OverseerError, match="supersedes no parked case"):
        overseer_run._validate_maintenance_case(stage / "case-s.yaml")
    with pytest.raises(overseer_run.OverseerError, match="missing successor field"):
        overseer_run._validate_successor(stage / "case-r.yaml", set(), tmp_path)


# ----------------------------------------------- the overseer drops by name


def test_the_overseer_drops_a_replace_pair_without_its_rewrite_or_records_and_the_rest_apply(
    env, tmp_path, monkeypatch
):
    """Rewrite required (D-AUTHOR §6.2) and the E1 gate's R1 item 3, in the
    overseer's pair loop: a replace case without `decision.rewrite`, and a
    merge whose `also` names a lesson the case's `records` do not, are each
    dropped with their sheet, named in "Refused / could not do"; nothing of
    either reaches a lesson. The good pair in the same run applies (the
    control)."""
    _enabled(monkeypatch)
    a, b, c, d = (_seed(env.home, f"lrn-e3b0d00{n}") for n in range(1, 5))
    for rid in (a, b, c, d):
        _place(env.home, rid, "skill-md")

    _run(env.home, monkeypatch, {
        "norewrite": (_maintenance([a], rewrite=None), _replace_sheet(a, NEW_A)),
        "outside": (_maintenance([b], rewrite=_rewrite("x")), _replace_sheet(b, NEW_B, also=[c])),
        "good": (_maintenance([d], rewrite=_rewrite("x")), _replace_sheet(d, NEW_A)),
    })

    refused = _refused_section(env.home)
    assert "case-norewrite.yaml: dropped with sheet-norewrite.yaml" in refused, refused
    assert "needs decision.rewrite" in refused, refused
    assert "case-outside.yaml: dropped with sheet-outside.yaml" in refused, refused
    assert f"replace {b} changes ['{c}'], which the case's records do not name" in refused, refused
    assert [_rec(env.home, rid).status for rid in (a, b, c)] == ["routed"] * 3
    assert _rec(env.home, d).status == "superseded"  # control: the good pair applied


# ------------------------------------------------------------------ (b)


def _stage_pair(stage: Path, name: str, case: dict, sheet: dict) -> Path:
    sheet = {**sheet, "case": "$CASE_ID"}
    case = {**case, "trigger": "nightly", "scope": "skill:s",
            "dependencies": {"statements": [], "user_model": [], "conditions": [], "capabilities": []}}
    for kind in ("cases", "sheets"):
        (stage / kind).mkdir(parents=True, exist_ok=True)
    _dump(stage / "cases" / f"{name}.yaml", case)
    _dump(stage / "sheets" / f"{name}.yaml", sheet)
    return stage / "cases" / f"{name}.yaml"


def _pending_merge_case(records: list[str]) -> dict:
    return {**_maintenance(records, rewrite=_rewrite("one rule")), "kind": "resolution"}


def test_b_a_steward_merge_case_counts_also_as_coverage_and_a_lesson_in_neither_is_refused(
    env, tmp_path
):
    """D-AUTHOR §2.8, the steward's change: a merge case `records: [A, B,
    C]` with one `replace` on A and `also: [B, C]` is accepted -- B and C
    cannot have items of their own (the new id is not minted). D, in the
    case's records but in neither the line's id nor its `also`, is still
    refused by the rule "every lesson in a case needs its own item". On
    d960042 the first pair was refused too ("no item for [B, C]")."""
    a, b, c, d = (_seed(env.home, f"lrn-e3b0e00{n}") for n in range(1, 5))  # pending
    stage = tmp_path / "stage"
    merge = _stage_pair(stage, "merge", _pending_merge_case([a, b, c]),
                        _replace_sheet(a, NEW_A, also=[b, c]))
    assert steward._pair_problem(stage, merge, env.home) is None

    stray = _stage_pair(stage, "stray", _pending_merge_case([a, b, d]),
                        _replace_sheet(a, NEW_A, also=[b]))
    problem = steward._pair_problem(stage, stray, env.home)
    assert problem == (
        f"stray.yaml: every lesson in a case needs its own item in sheets/stray.yaml; "
        f"no item for ['{d}']"
    )


def test_the_steward_refuses_a_replace_pair_without_its_rewrite_or_records(env, tmp_path):
    """The same two runner rules at the steward's stage check, each by name;
    the pair with both passes (the control)."""
    a, b = _seed(env.home, "lrn-e3b0f001"), _seed(env.home, "lrn-e3b0f002")
    stage = tmp_path / "stage"
    good = _stage_pair(stage, "good", _pending_merge_case([a, b]),
                       _replace_sheet(a, NEW_A, also=[b]))
    assert steward._pair_problem(stage, good, env.home) is None
    norewrite = _pending_merge_case([a, b])
    del norewrite["decision"]["rewrite"]
    bare = _stage_pair(stage, "bare", norewrite, _replace_sheet(a, NEW_A, also=[b]))
    assert "needs decision.rewrite" in (steward._pair_problem(stage, bare, env.home) or "")
    outside = _stage_pair(stage, "outside", _pending_merge_case([a]),
                          _replace_sheet(a, NEW_A, also=[b]))
    assert (steward._pair_problem(stage, outside, env.home) or "").startswith(
        f"outside.yaml: replace {a} changes ['{b}'], which the case's records do not name"
    )


# -------------------------------------------- the formats examples (§2.13)


def test_the_rewrite_merge_and_correct_examples_are_named_maintenance_pairs_that_validate(tmp_path):
    root = formats.write(tmp_path / "ws", "B")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "named pair" in readme and "case-<name>.yaml with sheet-<name>.yaml" in readme
    for stem in ("rewrite", "merge", "correct-lesson"):
        case_file, sheet_file = root / f"case-{stem}-example.yaml", root / f"sheet-{stem}-example.yaml"
        assert f"case-{stem}-example.yaml" in readme, stem
        assert overseer_run._is_maintenance_pair(case_file), stem
        overseer_run._validate_maintenance_case(case_file)
        assert overseer_run._case_rule_problem(case_file, "abcd1234") is None, stem
        case = overseer_run._yaml_mapping(case_file)
        assert "rewrite" in case["decision"], stem
        sheet = overseer_run._yaml_mapping(sheet_file)
        assert cases.replace_items_problem(case, sheet["items"], label=stem) is None, stem
        assert all(item["verb"] == "replace" for item in sheet["items"]), stem
        for item in sheet["items"]:
            for key in ("trigger", "instruction", "fact"):
                assert "\n" not in str(item.get(key) or ""), (stem, key)  # one physical line
        # broken twins: no rewrite; an `also` outside the records
        del case["decision"]["rewrite"]
        assert "needs decision.rewrite" in (cases.replace_items_problem(case, sheet["items"]) or "")
    merge = overseer_run._yaml_mapping(root / "case-merge-example.yaml")
    merge_sheet = overseer_run._yaml_mapping(root / "sheet-merge-example.yaml")
    assert merge_sheet["items"][0]["also"] == list(formats.EXAMPLE_MERGED)
    merge["records"] = [formats.EXAMPLE_RECORD]
    assert "records do not name" in (cases.replace_items_problem(merge, merge_sheet["items"]) or "")


# ============================================================ E3b fold 1


@pytest.mark.parametrize("placed_in", ["user-claude-md", "skill-md"])
def test_fold_d1_each_rewrite_example_meets_the_pair_rules_where_the_readme_says(
    tmp_path, monkeypatch, placed_in
):
    """Gate D1: a `replace` with no `dest` keeps its lesson's placement, so
    under an always-loaded placement it meets the combined test, exactly as
    a route there does. The shortening example -- an always-loaded line --
    failed `_pair_rules_problem` when its lesson sat in a user CLAUDE.md.
    It now carries `decision.always_loaded`. The merge and the correction
    show lessons placed in a SKILL.md, and the README says so plainly (the
    choice this fold made, rather than giving them the block too): they
    pass there, and under a CLAUDE.md placement they are refused by the
    combined test, which is what the README tells the model."""
    from self_learn import always_loaded

    placement = ("claude-md", None) if placed_in == "user-claude-md" else ("skill-md", None)
    monkeypatch.setattr(always_loaded, "placement_resolver", lambda _home: lambda _rid: placement)
    root = formats.write(tmp_path / "ws", "B")
    readme = " ".join((root / "README.md").read_text(encoding="utf-8").split())
    assert ("If it lands on an always-loaded line -- an always-loaded `dest`, or no `dest` and a "
            "lesson placed in a CLAUDE.md itself (not a rules file) -- the case needs the combined "
            "test, as a route there does.") in readme
    assert ("the merge's and the correction's lessons are placed in a SKILL.md, which needs none"
            in readme)
    home = tmp_path / "home"
    for stem in ("rewrite", "merge", "correct-lesson"):
        case_file = root / f"case-{stem}-example.yaml"
        sheet = overseer_run._load_sheet_allow_empty(root / f"sheet-{stem}-example.yaml", home)
        assert sheet is not None
        assert all("dest" not in item.fields for item in sheet), stem  # dest-less: inherits
        problem = overseer_run._pair_rules_problem(case_file, sheet, home)
        if placed_in == "skill-md" or stem == "rewrite":
            assert problem is None, (stem, problem)
        else:
            assert "to an always-loaded line" in (problem or ""), (stem, problem)
    # the broken twin: the shortening without its block, in a CLAUDE.md
    case_file = root / "case-rewrite-example.yaml"
    case = overseer_run._yaml_mapping(case_file)
    assert set(case["decision"]["always_loaded"]) == set(always_loaded.TEST_KEYS)
    del case["decision"]["always_loaded"]
    _dump(case_file, case)
    sheet = overseer_run._load_sheet_allow_empty(root / "sheet-rewrite-example.yaml", home)
    assert sheet is not None
    problem = overseer_run._pair_rules_problem(case_file, sheet, home)
    if placed_in == "user-claude-md":
        assert "to an always-loaded line" in (problem or ""), problem
    else:
        assert problem is None


def test_fold_r1_a_pair_touching_a_lesson_another_case_holds_is_dropped(
    env, tmp_path, monkeypatch
):
    """Gate R1 (probe p7), the real overseer run and the real batch: S-81's
    hold binds the overseer's own pairs. A lesson an open parked case is
    waiting on is decided through THAT case's successor only:

    * a maintenance pair whose line replaces W (held by P1) is dropped;
    * a maintenance merge with W in `also` is dropped;
    * a successor of P2 whose sheet also rejects W is dropped too -- before
      the fold nothing compared a successor's sheet with another parked
      case's lessons, so it applied;

    each named in "Refused / could not do", pointing at the parked case's
    successor. The control: P1's own successor rejects W and applies."""
    _enabled(monkeypatch)
    a = _seed(env.home, "lrn-e3bf0301")
    _place(env.home, a, "skill-md")
    w, v = "lrn-e3bf0302", "lrn-e3bf0303"
    p1 = _seed_parked(env.home, tmp_path, w, "p1")
    p2 = _seed_parked(env.home, tmp_path, v, "p2")
    assert {w, v} <= set(cases.held_lessons(env.home))  # positive control: both held

    _run(env.home, monkeypatch, {
        "mreplace": (_maintenance([w], rewrite=_rewrite("x")), _replace_sheet(w, NEW_A)),
        "malso": (_maintenance([a, w], rewrite=_rewrite("x")), _replace_sheet(a, NEW_B, also=[w])),
        "p2cross": (_successor(v, p2), {"version": 1, "items": [
            {"id": v, "verb": "reject"}, {"id": w, "verb": "reject"}]}),
        "p1own": (_successor(w, p1), {"version": 1, "items": [{"id": w, "verb": "reject"}]}),
    })

    refused = _refused_section(env.home)
    for name in ("mreplace", "malso", "p2cross"):
        assert f"case-{name}.yaml: dropped with sheet-{name}.yaml" in refused, (name, refused)
    assert refused.count(f"touches {w}, which the open parked case(s) {p1} hold") == 3, refused
    assert "decide it through that parked case's successor" in refused
    assert "case-p1own.yaml" not in refused, refused
    assert _rec(env.home, w).status == "rejected"  # control: P1's own successor applied
    assert _rec(env.home, a).status == "routed"
    assert _rec(env.home, v).status == "pending"  # P2's successor was dropped whole
    still = {row["case"] for row in cases.awaiting_overseer(env.home)}
    assert p2 in still and p1 not in still
