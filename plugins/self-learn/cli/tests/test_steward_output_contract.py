"""The last block of the steward's brief: the exact shape of every file
the steward writes.

Why this file exists. On the first real run (2026-09-19) each steward
session spent about 30 of its ~110 tool calls reading this package's
source code to find out what format its files had to have, because the
brief described the finished case DOCUMENT rather than the YAML the
steward writes, and said almost nothing about the other five files. The
user's instruction: "give the steward the information it needs up front
instead of having the poor guy read through the source code".

Two promises are tested here, and both are about drift:

1. every closed set and key table in the brief is READ from the constant
   the checker itself reads, so a new kind, verb or key reaches the brief
   without anyone remembering to write it down;
2. every worked example in the brief is accepted by the REAL checkers --
   the stage validator, `cases.record`, `statements.add`,
   `user_model.add_entry` / `lapse_entry` -- so an example can never teach
   the model a shape the runner refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from self_learn import batch, cases, records, statements, steward, steward_prompt, user_model

from support import make_home

_EXAMPLE_LESSONS = {"lrn-0a1b2c3d", "lrn-1b2c3d4e", "lrn-2c3d4e5f"}


def _text() -> str:
    return steward_prompt._render_output_contract()


def _load(name: str):
    return YAML(typ="safe").load(steward_prompt.STAGE_EXAMPLES[name])


def _write_examples(stage: Path, *, replace: dict[str, str] | None = None) -> Path:
    for name, body in steward_prompt.STAGE_EXAMPLES.items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((replace or {}).get(name, body), encoding="utf-8")
    return stage


# ------------------------------------------------ 1. read from the checkers


@pytest.mark.parametrize(
    "label, members",
    [
        ("case kinds", cases.KINDS),
        ("case triggers", cases.TRIGGERS),
        ("case outcomes", cases.OUTCOMES),
        ("confidence values", cases.CONFIDENCE_VALUES),
        ("parked reasons the model may choose", cases.PARKED_REASONS - steward_prompt.RUNNER_ONLY_PARKED_REASONS),
        ("statement answer kinds", statements.ANSWER_KINDS),
        ("statement scope levels", statements.SCOPE_LEVELS),
        ("verbs refused inside a sheet", batch.REFUSED_VERBS_LITERAL),
        ("lesson sections", {n for names in records.REQUIRED_SECTIONS.values() for n in names}),
    ],
)
def test_every_member_of_a_checkers_closed_set_is_in_the_brief(label, members):
    text = _text()
    assert members, label  # the control: an empty set would pass vacuously
    assert [m for m in sorted(members) if m not in text] == [], label


def test_every_sheet_verb_is_listed_with_exactly_the_keys_the_checker_allows():
    lines = {line.split()[0]: line for line in steward_prompt._sheet_verb_lines()}
    assert batch.SHEET_VERB_ALIASES and batch.SHEET_VERB_ALIASES < set(batch.PERMITTED_KEYS)  # the control
    listed = set(batch.PERMITTED_KEYS) - batch.SHEET_VERB_ALIASES  # `retire`'s pre-rename alias (S-67)
    assert set(lines) == listed
    for verb in listed:
        for key in batch.PERMITTED_KEYS[verb] - {"by"}:
            assert key in lines[verb], (verb, key)
        required = batch.REQUIRED_KEYS.get(verb, frozenset())
        required_part = lines[verb].split("optional:")[0]
        for key in required:
            assert key in required_part, (verb, key)
    assert "required: covered_by" in lines["retire"]  # one spelled out, so the loop is not the only witness
    assert all("by" not in line.replace("covered_by", "").split() for line in lines.values())


def test_a_kind_added_to_the_checker_reaches_the_brief_unprompted(monkeypatch):
    assert "zz-new-kind" not in _text()
    monkeypatch.setattr(cases, "KINDS", cases.KINDS | {"zz-new-kind"})
    assert "zz-new-kind" in _text()


def test_a_key_added_to_a_sheet_verb_reaches_the_brief_unprompted(monkeypatch):
    assert "zz_new_key" not in _text()
    widened = dict(batch.PERMITTED_KEYS)
    widened["reject"] = widened["reject"] | {"zz_new_key"}
    monkeypatch.setattr(batch, "PERMITTED_KEYS", widened)
    assert "zz_new_key" in _text()


def test_the_runner_only_parked_reasons_are_named_as_not_the_models_to_write():
    text = _text()
    choosable_line = next(line for line in text.splitlines() if "parked_reason is one of" in line)
    assert "authority-unclear" in choosable_line  # the control: the right line was found
    for reason in steward_prompt.RUNNER_ONLY_PARKED_REASONS:
        assert reason not in choosable_line
        assert reason in text  # ... but named, with "never write them"
    assert steward._RUNNER_ONLY_PARKED_REASONS is steward_prompt.RUNNER_ONLY_PARKED_REASONS


def test_the_files_the_brief_names_are_the_files_the_checker_allows(tmp_path):
    text = _text()
    for name in steward_prompt.OUTPUT_CONTRACT:
        assert name in text
    stage = _write_examples(tmp_path / "contract-stage" / "packet")
    (stage / "notes.txt").write_text("not a declared file", encoding="utf-8")
    with pytest.raises(ValueError, match="undeclared stage file: notes.txt"):
        steward._validate_declared_stage(stage)


def test_the_brief_says_what_the_runner_fills_in_and_the_model_must_not():
    text = _text()
    for key in ("case", "opened_at", "actor", "run_id", "superseded_by", "decided_sha256", "presented"):
        assert key in text.split("Do NOT write:")[1].split("\n")[0], key
    assert "case: $CASE_ID" in text
    assert "Never write `by`" in text


# ------------------------------------------- 2. the examples are really valid


def test_the_examples_pass_the_runners_stage_check_as_a_whole(tmp_path):
    stage = _write_examples(tmp_path / "contract-stage" / "packet")

    steward._validate_and_prepare_stage(stage, set(_EXAMPLE_LESSONS))

    # ... and the revision was folded into its case's sheet, before the route.
    sheet = YAML(typ="safe").load((stage / "sheets" / "shell-quoting.yaml").read_text(encoding="utf-8"))
    assert [item["verb"] for item in sheet["items"]] == ["revise", "route"]


def test_the_stage_check_is_live_a_broken_example_is_refused(tmp_path):
    broken = steward_prompt.STAGE_EXAMPLES["sheets/two-duplicates.yaml"].replace("verb: reject", "verb: forget", 1)
    stage = _write_examples(
        tmp_path / "contract-stage" / "packet", replace={"sheets/two-duplicates.yaml": broken}
    )
    with pytest.raises(ValueError, match="forget"):
        steward._validate_and_prepare_stage(stage, set(_EXAMPLE_LESSONS))


def test_the_examples_cover_their_lessons_exactly_once(tmp_path):
    stage = _write_examples(tmp_path / "contract-stage" / "packet")
    with pytest.raises(ValueError, match="cover every selected record exactly once"):
        steward._validate_and_prepare_stage(stage, set(_EXAMPLE_LESSONS) | {"lrn-9f9f9f9f"})


def test_every_example_lesson_has_its_own_sheet_item():
    """The rule the brief states and the checker does not enforce."""
    for name in steward_prompt.STAGE_EXAMPLES:
        if not name.startswith("cases/"):
            continue
        case, sheet = _load(name), _load(name.replace("cases/", "sheets/"))
        assert {item["id"] for item in sheet["items"]} == set(case["records"]), name


def test_the_example_revision_names_a_section_a_lesson_really_has():
    """`revise` refuses a section the lesson does not already have, but
    only at apply time and against a real record -- the stage check
    cannot see it. So the example is held to the one list there is."""
    real_sections = {name for names in records.REQUIRED_SECTIONS.values() for name in names}
    entries = _load("revisions.yaml")["entries"]
    assert entries  # the control: there is an example to check
    for entry in entries:
        assert entry["section"] in real_sections
        assert set(entry) == {"case", "id"} | set(batch.REQUIRED_KEYS["revise"])
        assert f"cases/{entry['case']}.yaml" in steward_prompt.STAGE_EXAMPLES


@pytest.mark.parametrize("name", ["cases/shell-quoting.yaml", "cases/two-duplicates.yaml"])
def test_each_example_case_is_accepted_by_the_real_case_writer(name, tmp_path):
    home = make_home(tmp_path)
    stage_file = tmp_path / "example-case.yaml"
    stage_file.write_text(steward_prompt.STAGE_EXAMPLES[name], encoding="utf-8")

    case_id = cases.record(home, stage_file, actor="steward")

    assert cases.CASE_ID_RE.fullmatch(case_id)


def test_the_case_writer_is_live_a_broken_example_is_refused(tmp_path):
    home = make_home(tmp_path)
    stage_file = tmp_path / "example-case.yaml"
    stage_file.write_text(
        steward_prompt.STAGE_EXAMPLES["cases/shell-quoting.yaml"].replace("confidence: settled", "confidence: sure"),
        encoding="utf-8",
    )
    with pytest.raises(cases.CaseUsageError, match="confidence"):
        cases.record(home, stage_file, actor="steward")


def test_the_example_statement_and_model_updates_are_accepted_by_their_real_writers(tmp_path):
    home = make_home(tmp_path)
    (statement,) = _load("statements.yaml")["entries"]
    add, lapse = _load("model-updates.yaml")["entries"]

    stmt_id = statements.add(
        home, verbatim=statement["verbatim"], source=statement["source"], recorded_by="steward",
        answers=statement.get("answers"), scope=statement.get("scope"),
    )
    assert statements.STMT_ID_RE.fullmatch(stmt_id)

    # The runner's own handling of a model-updates entry
    # (`steward._maintain_manifest`): pop `action`, refuse any source but
    # a system reading, pass the rest straight through as keywords.
    assert add.pop("action") == "add" and add["source"] == "system-reading"
    add["statements"] = [stmt_id]  # the example's id is invented; a real one exists now
    entry_id = user_model.add_entry(home, by="steward", **add)
    assert user_model.UM_ID_RE.fullmatch(entry_id)

    assert lapse.pop("action") == "lapse"
    assert user_model.UM_ID_RE.fullmatch(lapse.pop("id"))  # the example's id is well-formed
    user_model.lapse_entry(home, entry_id, by="steward", **lapse)


def test_the_block_is_the_last_thing_in_the_assembled_brief():
    assert steward_prompt._BLOCK_ORDER[-1] == "output_contract"
    assert "EXAMPLES (all ids and text invented)" in _text()
