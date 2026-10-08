"""E0: the loaded text of a lesson is never cut silently.

`compilers.entry_line` keeps only the first non-empty line of a lesson's
Trigger, Instruction and Fact (`_one_liner`), so a multi-line section
compiled to its first line with exit 0 and no word to anyone. This file pins
the three parts of the repair (D-AUTHOR §2.12, §1.5, §7's E0 row):

1. a multi-line Trigger, Instruction or Fact that heads into a managed line
   is REFUSED, by name, before anything is written
   (`compilers.loaded_text_problem`, wired into the route preflight that
   `route`, `route_direct` and `route_dry_run` share); a reference shelf
   keeps whole text and is not refused; a plain `teach` capture to pending
   is not refused either;
2. a trigger that already begins "When" no longer renders "When when";
3. a behavior lesson may carry an optional `## Context`, kept in the record
   and never compiled into a managed line (it joins the reference journal);
   `rewrite` is a record source.

Every scenario that touches the ledger runs on a sandbox ledger and host
(`support.make_env` under pytest's tmpdir); no model is called.
"""

from __future__ import annotations

import hashlib
import re

import pytest
from ruamel.yaml import YAML

from self_learn import batch, cli, compilers, records, verbs
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record, ValidationError
from self_learn.scan import refusal_text
from support import commit_all, git, last_verb_sha, make_behavior, make_env

#: Destinations that compile a record into a MANAGED line, in every spelling
#: the verbs accept (`verbs._parse_dest`).
MANAGED = [
    "claude-md",
    "claude-md:local",
    "claude-md:rules:topic",
    "skill-md",
    "new-skill",
    "new-skill:my-skill",
]
#: Destinations whose compile keeps the record whole (or reads none of it).
KEEPS_WHOLE = ["reference", "reference:LEARNINGS.md", "hook"]

TWO_LINES = "First line, the loaded sentence.\nSecond line, which would be cut."


def _behavior(trigger="About to edit X.", instruction="Stop first.", rid="lrn-0e000001"):
    return Record.create(
        type="behavior",
        scope="skill:s",
        source="teach",
        kind="anti-pattern",
        trigger=trigger,
        instruction=instruction,
        record_id=rid,
    )


def _knowledge(fact="X reloads without re-reading.", context=None, rid="lrn-0e000002"):
    return Record.create(
        type="knowledge",
        scope="skill:s",
        source="teach",
        fact=fact,
        context=context,
        record_id=rid,
    )


# ------------------------------------------------------ the pure check (item 1)


@pytest.mark.parametrize("dest", MANAGED)
@pytest.mark.parametrize("section", ["Trigger", "Instruction"])
def test_a_multi_line_behavior_section_is_refused_by_name_for_each_managed_destination(
    dest, section
):
    other = "Instruction" if section == "Trigger" else "Trigger"
    kwargs = {section.lower(): TWO_LINES}
    record = _behavior(**kwargs)

    # positive control: the same record with that section on one line passes,
    # so the refusal below is the second line and nothing else
    assert compilers.loaded_text_problem(_behavior(), dest) is None

    problem = compilers.loaded_text_problem(record, dest)
    assert problem is not None
    assert section in problem
    assert other not in problem  # it names the offending section, not the lesson's other one
    assert "## Context" in problem  # and says where the rest goes
    assert record.id in problem


@pytest.mark.parametrize("dest", MANAGED)
def test_a_multi_line_fact_is_refused_by_name_for_each_managed_destination(dest):
    assert compilers.loaded_text_problem(_knowledge(), dest) is None  # control
    problem = compilers.loaded_text_problem(_knowledge(fact=TWO_LINES), dest)
    assert problem is not None
    assert "Fact" in problem
    assert "## Context" in problem


@pytest.mark.parametrize("dest", KEEPS_WHOLE)
def test_a_reference_or_hook_destination_is_not_refused(dest):
    record = _behavior(trigger=TWO_LINES, instruction=TWO_LINES)
    fact = _knowledge(fact=TWO_LINES)
    # positive control: the very same records ARE refused where the line is cut
    assert compilers.loaded_text_problem(record, "skill-md") is not None
    assert compilers.loaded_text_problem(fact, "skill-md") is not None
    assert compilers.loaded_text_problem(record, dest) is None
    assert compilers.loaded_text_problem(fact, dest) is None


def test_every_offending_section_is_named_in_one_message():
    problem = compilers.loaded_text_problem(
        _behavior(trigger=TWO_LINES, instruction=TWO_LINES), "skill-md"
    )
    assert problem is not None
    assert "Trigger" in problem and "Instruction" in problem


def test_a_blank_line_does_not_hide_a_second_paragraph_and_blank_edges_are_not_a_second_line():
    record = _behavior()
    record.set_body(
        "\n## Trigger\n\n\nAbout to edit X.\n\n\n## Instruction\nStop first.\n\n\n"
    )
    assert compilers.loaded_text_problem(record, "skill-md") is None  # edges only

    record.set_body("\n## Trigger\nAbout to edit X.\n\n## Instruction\nStop.\n\nThen restart.\n")
    problem = compilers.loaded_text_problem(record, "skill-md")  # the cut drops "Then restart."
    assert problem is not None and "Instruction" in problem


def test_context_and_the_episode_brief_are_never_examined():
    # a knowledge lesson's Context may run to any length; the Fact is one line
    assert compilers.loaded_text_problem(_knowledge(), "skill-md") is None  # control
    long_context = "\n".join(f"context line {n}" for n in range(6))
    assert (
        compilers.loaded_text_problem(_knowledge(context=long_context), "skill-md") is None
    )
    # the same for a behavior lesson's Context and the miner's Episode brief
    record = _behavior()
    record.set_body(
        record.body.rstrip("\n")
        + f"\n\n## Context\n{long_context}\n\n## Episode brief\n{long_context}\n"
    )
    assert "context line 5" in record.body  # the sections are there to be skipped
    assert compilers.loaded_text_problem(record, "skill-md") is None


def test_an_unknown_destination_is_an_error_not_a_pass():
    # fail closed: a destination the check does not know must not read as "fine"
    with pytest.raises(ValueError):
        compilers.loaded_text_problem(_behavior(trigger=TWO_LINES), "somewhere-else")


# ------------------------------------------ the route preflight wiring (item 1)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    return env


GOOD = "lrn-0e00a001"
CUT = "lrn-0e00a002"


def _seed(env, rid, **kwargs):
    create_record(env.ledger, make_behavior(record_id=rid, **kwargs))
    commit_all(env.ledger, f"seed {rid}")


def _head(env) -> str:
    """The newest commit that is not a telemetry flush (a flush may land on
    top of a verb's own commit, so HEAD alone would blur 'nothing was
    written' with 'the flush ran')."""
    return last_verb_sha(env.ledger)


@pytest.mark.parametrize("dest", ["skill-md", "claude-md"])
def test_preview_and_run_refuse_the_same_multi_line_route_and_write_nothing(sandbox, dest):
    env = sandbox
    _seed(env, GOOD)
    _seed(env, CUT, instruction=TWO_LINES)
    host_file = env.skill_md if dest == "skill-md" else env.host / "CLAUDE.md"

    # positive control: a one-line lesson previews clean and routes to the same target
    assert verbs.route_dry_run(env.ledger, GOOD, dest=dest).would_refuse == []
    verbs.route(env.ledger, GOOD, dest=dest, no_push=True)
    assert GOOD in host_file.read_text(encoding="utf-8")

    host_before = host_file.read_bytes()
    head_before = _head(env)
    preview = verbs.route_dry_run(env.ledger, CUT, dest=dest)
    assert len(preview.would_refuse) == 1, preview.would_refuse
    assert "Instruction" in preview.would_refuse[0]
    assert "## Context" in preview.would_refuse[0]
    assert isinstance(preview.refusal_errors[0], verbs.SheetLineError)

    with pytest.raises(verbs.SheetLineError) as excinfo:
        verbs.route(env.ledger, CUT, dest=dest, no_push=True)
    assert refusal_text(excinfo.value) == preview.would_refuse[0]  # one sentence, both ways
    # the lesson stayed pending and neither repository moved
    assert find_record_path(env.ledger, CUT).parent.name == "pending"
    assert _head(env) == head_before
    assert host_file.read_bytes() == host_before


def test_a_person_teach_route_gets_the_message_and_the_lesson_is_kept_in_pending(
    sandbox, capsys
):
    env = sandbox
    teach = [
        "teach", "--skill", "s", "--type", "behavior", "--kind", "anti-pattern",
        "--trigger", "About to edit X.", "--instruction", TWO_LINES,
    ]
    host_before = env.skill_md.read_bytes()
    host_head = git(env.host, "rev-parse", "HEAD").stdout.strip()

    rc = cli.main(teach + ["--route", "--dest", "skill-md", "--no-push"])
    err = capsys.readouterr().err
    # the refusal comes before any write to the target, naming the section and the way out ...
    assert rc != 0
    assert "Instruction" in err and "## Context" in err
    assert env.skill_md.read_bytes() == host_before
    assert git(env.host, "rev-parse", "HEAD").stdout.strip() == host_head
    assert not list((env.ledger / "skills" / "s").glob("resolved/lrn-*.md"))
    # ... and teach's never-lost fallback keeps the whole lesson, both lines, in pending
    (kept,) = (env.ledger / "skills" / "s" / "pending").glob("lrn-*.md")
    assert "Second line, which would be cut." in kept.read_text(encoding="utf-8")

    # a plain `teach` capture to pending is NOT refused: pending text can still be revised
    rc = cli.main(teach)
    capsys.readouterr()
    assert rc == 0
    assert len(list((env.ledger / "skills" / "s" / "pending").glob("lrn-*.md"))) == 2


def test_route_direct_refuses_before_it_writes_the_record(sandbox):
    env = sandbox
    good = make_behavior(record_id=GOOD)
    verbs.route_direct(env.ledger, good, dest="skill-md", no_push=True)  # control
    assert (env.ledger / "skills" / "s" / "resolved" / f"{GOOD}.md").is_file()

    head_before = _head(env)
    with pytest.raises(verbs.SheetLineError, match="Instruction"):
        verbs.route_direct(
            env.ledger, make_behavior(record_id=CUT, instruction=TWO_LINES),
            dest="skill-md", no_push=True,
        )
    assert _head(env) == head_before
    assert not (env.ledger / "skills" / "s" / "resolved" / f"{CUT}.md").exists()
    assert not (env.ledger / "skills" / "s" / "pending" / f"{CUT}.md").exists()


def _sheet(tmp_path, items):
    path = tmp_path / "sheet.yaml"
    with path.open("w", encoding="utf-8") as fh:
        YAML().dump({"version": 1, "items": items}, fh)
    return batch.load_sheet(path)


@pytest.mark.parametrize("actor", ["steward", "overseer"])
def test_for_an_agent_the_refusal_is_a_bad_line_and_the_preview_agrees(sandbox, tmp_path, actor):
    env = sandbox
    _seed(env, GOOD)
    _seed(env, CUT, instruction=TWO_LINES)
    sheet = _sheet(tmp_path, [{"id": CUT, "verb": "route", "dest": "skill-md"}])
    head_before = _head(env)

    preview = batch.dry_run(env.ledger, sheet, actor=actor)
    result = batch.run(env.ledger, sheet, no_push=True, actor=actor)
    refused, previewed = result.items[0], preview.items[0]
    assert (refused.state, refused.kind) == ("refused", "bad-line"), refused.detail
    assert (previewed.state, previewed.kind) == ("would-refuse", "bad-line")
    assert refused.detail == previewed.detail
    assert "Instruction" in (refused.detail or "") and "## Context" in (refused.detail or "")
    assert _head(env) == head_before

    # positive control: the same agent's one-line route applies
    ok = _sheet(tmp_path, [{"id": GOOD, "verb": "route", "dest": "skill-md"}])
    applied = batch.run(env.ledger, ok, no_push=True, actor=actor)
    assert applied.items[0].state == "applied", applied.items[0].detail
    assert GOOD in env.skill_md.read_text(encoding="utf-8")


def test_a_route_to_a_reference_shelf_keeps_every_line(sandbox):
    env = sandbox
    _seed(env, CUT, instruction=TWO_LINES)
    # the cut is refused for a managed line (control) ...
    assert verbs.route_dry_run(env.ledger, CUT, dest="skill-md").would_refuse
    # ... and the shelf, which keeps whole text, is not refused and holds both lines
    assert verbs.route_dry_run(env.ledger, CUT, dest="reference").would_refuse == []
    verbs.route(env.ledger, CUT, dest="reference", no_push=True)
    shelf = env.skill_dir / "references" / "LEARNINGS.md"
    text = shelf.read_text(encoding="utf-8")
    assert "First line, the loaded sentence." in text
    assert "Second line, which would be cut." in text


def test_wiring_the_check_did_not_widen_the_compile_itself(sandbox):
    # `recompile` and the compile functions still never refuse: a legacy routed
    # lesson with several lines keeps compiling to its first line (the refusal
    # is at routing, not at every later read of the ledger)
    record = _behavior(instruction=TWO_LINES)
    record.set_routing({"routed_at": "2026-07-13T18:02:00Z", "destination": "skill-md", "by": "human"})
    record.set_status("routed")
    assert compilers.loaded_text_problem(record, "skill-md") is not None  # it is flagged ...
    line = compilers.entry_line(record)  # ... and the compile still goes through
    assert "first line, the loaded sentence." in line  # (lower-cased after "When ...:")
    assert "Second line" not in line


# ------------------------------------------------ "When when" (item 2)


def _says_when_when(line: str) -> bool:
    return re.search(r"\bwhen\s+when\b", line, re.IGNORECASE) is not None


@pytest.mark.parametrize(
    "trigger, loaded",
    [
        ("When about to edit X.", "about to edit X"),
        ("when about to edit X.", "about to edit X"),
        ("WHEN about to edit X", "about to edit X"),
        ("When   about to edit X", "about to edit X"),
        ("When when about to edit X", "about to edit X"),  # the prefix repeated
        ("When About to Edit X", "about to Edit X"),
    ],
)
def test_the_entry_line_drops_a_leading_when_from_the_trigger(trigger, loaded):
    line = compilers.entry_line(_behavior(trigger=trigger))
    assert line == f"- **When {loaded}:** stop first. *(lrn-0e000001)*"
    assert not _says_when_when(line)


@pytest.mark.parametrize(
    "trigger, loaded",
    [
        ("About to edit X.", "about to edit X"),
        ("Whenever X happens", "whenever X happens"),
        ("Somewhen soon, when X happens", "somewhen soon, when X happens"),
        ("Edit X when Y is running", "edit X when Y is running"),
    ],
)
def test_only_the_leading_word_when_is_dropped(trigger, loaded):
    expected = f"- **When {loaded}:** stop first. *(lrn-0e000001)*"
    # a trigger that does not open with the word "When" is untouched ...
    assert compilers.entry_line(_behavior(trigger=trigger)) == expected
    # ... and the strip is live beside it: the same trigger with a "When " in
    # front compiles to the very same line
    assert compilers.entry_line(_behavior(trigger="When " + trigger)) == expected


def test_a_when_leading_trigger_compiles_without_when_when_in_a_whole_section():
    records = []
    for n, trigger in enumerate(
        ["When about to edit X.", "About to edit Y.", "when Z is running", "Whenever W"]
    ):
        record = _behavior(trigger=trigger, rid=f"lrn-0e00b00{n}")
        record.set_routing(
            {"routed_at": f"2026-07-13T18:0{n}:00Z", "destination": "skill-md", "by": "human"}
        )
        record.set_status("routed")
        records.append(record)
    result = compilers.compile_managed_text("# skill\n", records)
    section = result.text
    assert "lrn-0e00b000" in section and "lrn-0e00b003" in section  # the section is there
    assert not _says_when_when(section)
    assert "- **When about to edit X:** stop first. *(lrn-0e00b000)*" in section
    # regeneration is byte-stable
    assert compilers.compile_managed_text(section, records).text == section


def test_a_route_to_skill_md_writes_the_line_without_when_when(sandbox):
    env = sandbox
    create_record(
        env.ledger, make_behavior(record_id=GOOD, trigger="When about to edit .storage.")
    )
    commit_all(env.ledger, "seed")
    verbs.route(env.ledger, GOOD, dest="skill-md", no_push=True)
    skill = env.skill_md.read_text(encoding="utf-8")
    assert f"- **When about to edit .storage:** stop the container first. *({GOOD})*" in skill
    assert not _says_when_when(skill)
    # the strip belongs to the managed line only: the same record's journal
    # entry (the shelf) keeps the trigger word for word
    routed = Record.from_path(find_record_path(env.ledger, GOOD))
    assert "**Trigger:** When about to edit .storage." in compilers._reference_block(routed)


# ------------------------- an optional Context on a behavior lesson (item 3)

MARK = "CONTEXT-ONLY-MARKER-7f3a"
CONTEXT = f"Why this matters, line one.\nLine two keeps {MARK}."


def _with_context(context=CONTEXT, rid="lrn-0e000003", **kwargs):
    return Record.create(
        type="behavior",
        scope="skill:s",
        source="teach",
        kind="anti-pattern",
        trigger=kwargs.pop("trigger", "About to edit X."),
        instruction=kwargs.pop("instruction", "Stop first."),
        context=context,
        record_id=rid,
    )


def _routed(record, destination="skill-md"):
    record.set_routing(
        {"routed_at": "2026-07-13T18:02:00Z", "destination": destination, "by": "human"}
    )
    record.set_status("routed")
    return record


def test_rewrite_is_a_record_source():
    assert "rewrite" in records.SOURCES
    # the source set is still closed
    with pytest.raises(ValidationError, match="source"):
        Record.create(type="behavior", scope="skill:s", source="bogus", kind="anti-pattern",
                      trigger="About to edit X.", instruction="Stop first.")
    record = Record.create(
        type="behavior", scope="skill:s", source="rewrite", kind="anti-pattern",
        trigger="About to edit X.", instruction="Stop first.", record_id="lrn-0e000004",
    )
    assert record.source == "rewrite"
    # and a record file that names it reads back
    assert Record.from_text(record.to_text()).source == "rewrite"
    with pytest.raises(ValidationError, match="source"):
        Record.from_text(record.to_text().replace("source: rewrite", "source: bogus"))
    # the setter reads the same closed set
    other = _behavior()
    other.set_source("rewrite")
    assert other.source == "rewrite"
    with pytest.raises(ValidationError, match="source"):
        other.set_source("bogus")


def test_a_behavior_lesson_keeps_an_optional_context_in_the_record():
    plain = _behavior()
    assert "## Context" not in plain.body  # optional: absent when not given
    record = _with_context()
    assert f"## Context\n{CONTEXT}" in record.body
    # the file reads back whole, and the section is not one of the loaded ones
    again = Record.from_text(record.to_text())
    assert again.body == record.body
    assert MARK in again.body


def test_a_second_context_section_on_a_behavior_lesson_is_refused():
    body = _with_context().body
    records.validate_body("behavior", body)  # one Context is fine
    with pytest.raises(ValidationError, match="duplicate optional '## Context'"):
        records.validate_body("behavior", body.rstrip("\n") + "\n\n## Context\nand again\n")
    record = _with_context()
    with pytest.raises(ValidationError, match="Context"):
        record.set_body(record.body.rstrip("\n") + "\n\n## Context\nand again\n")


@pytest.mark.parametrize("kind", ["behavior", "knowledge"])
def test_context_is_never_compiled_into_a_managed_line(kind):
    if kind == "behavior":
        record = _routed(_with_context())
    else:
        record = _routed(_knowledge(context=CONTEXT))
    assert MARK in record.body  # positive control: the text is in the record ...
    line = compilers.entry_line(record)
    assert record.id in line and MARK not in line  # ... and not in its managed line
    result = compilers.compile_managed_text("# skill\n", [record])
    assert record.id in result.text and MARK not in result.text
    # a multi-line Context is not a reason to refuse the route
    assert compilers.loaded_text_problem(record, "skill-md") is None


def test_the_reference_journal_includes_a_behavior_lessons_context():
    record = _routed(_with_context(), destination="reference")
    block = compilers._reference_block(record)
    assert "**Trigger:** About to edit X." in block
    assert "**Instruction:** Stop first." in block
    assert f"**Context:** {CONTEXT}" in block
    # the order is Trigger, Instruction, Context
    assert block.index("**Instruction:**") < block.index("**Context:**")
    # a behavior lesson with no Context writes exactly what it always did
    bare = compilers._reference_block(_routed(_behavior(), destination="reference"))
    assert bare == (
        "## 2026-07-13 — lrn-0e000001\n\n**Trigger:** About to edit X.\n\n"
        "**Instruction:** Stop first."
    )
    # and a knowledge lesson's block is unchanged
    fact = compilers._reference_block(_routed(_knowledge(context="why"), destination="reference"))
    assert fact.endswith("**Fact:** X reloads without re-reading.\n\n**Context:** why")


def test_the_episode_brief_still_stays_out_of_every_compile_target():
    brief = "EPISODE-BRIEF-MARKER-91c2"
    record = _with_context()
    record.set_body(record.body.rstrip("\n") + f"\n\n## Episode brief\n{brief}\n")
    _routed(record)
    assert brief in record.body and MARK in record.body  # both are in the record
    block = compilers._reference_block(record)
    assert MARK in block  # the Context joins the journal ...
    assert brief not in block  # ... the brief never does
    assert brief not in compilers.entry_line(record)


def test_a_behavior_lesson_with_context_routes_to_a_line_and_to_a_shelf(sandbox):
    env = sandbox
    create_record(env.ledger, _with_context(rid=GOOD))
    create_record(env.ledger, _with_context(rid=CUT))
    commit_all(env.ledger, "seed")

    verbs.route(env.ledger, GOOD, dest="skill-md", no_push=True)
    skill = env.skill_md.read_text(encoding="utf-8")
    assert f"*({GOOD})*" in skill  # the line is there ...
    assert MARK not in skill  # ... and the Context is not
    kept = find_record_path(env.ledger, GOOD).read_text(encoding="utf-8")
    assert MARK in kept  # it stays in the routed record

    verbs.route(env.ledger, CUT, dest="reference", no_push=True)
    shelf = (env.skill_dir / "references" / "LEARNINGS.md").read_text(encoding="utf-8")
    assert f"— {CUT}" in shelf and f"**Context:** {CONTEXT}" in shelf


# ------------------------------------------------------- reroute (item 4)


def _on_a_shelf(env, rid, **kwargs):
    """A routed lesson on the reference shelf: the one place a multi-line
    lesson can sit, since a reference keeps whole text."""
    _seed(env, rid, **kwargs)
    verbs.route(env.ledger, rid, dest="reference", no_push=True)
    assert Record.from_path(find_record_path(env.ledger, rid)).status == "routed"


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("dest", ["claude-md", "skill-md"])
def test_reroute_refuses_a_routed_lesson_whose_loaded_text_would_be_cut(sandbox, dest):
    env = sandbox
    host_file = env.host / "CLAUDE.md" if dest == "claude-md" else env.skill_md
    _on_a_shelf(env, GOOD)
    _on_a_shelf(env, CUT, instruction=TWO_LINES)
    shelf = env.skill_dir / "references" / "LEARNINGS.md"

    # positive control: the one-line lesson moves from the shelf to the managed line
    assert f"*({GOOD})*" not in host_file.read_text(encoding="utf-8")
    verbs.reroute(env.ledger, GOOD, dest=dest, no_push=True)
    assert f"*({GOOD})*" in host_file.read_text(encoding="utf-8")

    record_path = find_record_path(env.ledger, CUT)
    before = {
        "target": _sha(host_file), "record": _sha(record_path), "shelf": _sha(shelf),
        "ledger": _head(env),
    }
    with pytest.raises(verbs.SheetLineError) as excinfo:
        verbs.reroute(env.ledger, CUT, dest=dest, no_push=True)
    message = refusal_text(excinfo.value)
    assert "Instruction" in message and "## Context" in message and CUT in message
    after = {
        "target": _sha(host_file), "record": _sha(record_path), "shelf": _sha(shelf),
        "ledger": _head(env),
    }
    assert after == before  # target, record, shelf and ledger history are all as they were
    assert Record.from_path(record_path).routing["destination"] == "reference"

    # the preview a reconsider sheet gets runs the same preflight, and says the same
    refused = batch._preview_reroute(
        env.ledger, batch.SheetItem(1, CUT, "route", {"dest": dest}), "steward", False
    )
    assert (refused.state, refused.kind) == ("would-refuse", "bad-line")
    assert refused.detail == message
    other = "skill-md" if dest == "claude-md" else "claude-md"  # control: the one-line lesson
    applies = batch._preview_reroute(
        env.ledger, batch.SheetItem(2, GOOD, "route", {"dest": other}), "steward", False
    )
    assert applies.state == "would-apply", applies.detail


def test_reroute_into_a_reference_is_not_refused(sandbox):
    env = sandbox
    _on_a_shelf(env, CUT, instruction=TWO_LINES)
    # a named references file is never created: it must already exist, committed
    (env.skill_dir / "references" / "Other.md").write_text("# Other shelf\n", encoding="utf-8")
    commit_all(env.host, "an existing second shelf")
    # the same lesson is refused where the line is cut (control) ...
    with pytest.raises(verbs.SheetLineError, match="Instruction"):
        verbs.reroute(env.ledger, CUT, dest="skill-md", no_push=True)
    # ... and moves to another reference file, whole
    verbs.reroute(env.ledger, CUT, dest="reference:Other.md", no_push=True)
    other = (env.skill_dir / "references" / "Other.md").read_text(encoding="utf-8")
    assert "First line, the loaded sentence." in other
    assert "Second line, which would be cut." in other
