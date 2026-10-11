"""E3a: one shared passage on writing a lesson, INLINED into each lesson
writer (never a pointer an agent must choose to open).

(a) the three inlined copies -- the `/self-learn:teach` command, the
    steward's brief, the overseer's workspace README -- equal the canonical
    file byte for byte;
(b) `teach --context` on a BEHAVIOR lesson writes `## Context`, and the
    line compiled after `--route` never carries that text;
(c) the byte-for-byte check can fail (a one-character mutation of a copy).

Every test runs under the suite-wide sandboxed SELF_LEARN_HOME/XDG_CACHE_HOME.
"""

from __future__ import annotations

import pytest

from self_learn import cli, lesson_writing, steward_prompt
from self_learn.overseer import formats
from self_learn.records import Record
from support import make_env, make_home

CANON_PATH = lesson_writing.path()
PLUGIN = CANON_PATH.parents[3]
TEACH_MD = PLUGIN / "commands" / "teach.md"

# A distinctive sentence from the passage, so "the copy is really there" is
# asserted separately from "the copy equals the file".
PASSAGE_SENTINEL = "The loaded text is the core of the lesson, not its background."


def _canon() -> str:
    return CANON_PATH.read_bytes().decode("utf-8")


def _steward_shared(tmp_path) -> str:
    """The text the steward's model receives in the appended system prompt."""
    home = make_home(tmp_path)
    run = steward_prompt.RunContext(
        run_id="run-test1",
        stage_dir=tmp_path / "stage",
        packet_index=1,
        packet_count=1,
        last_run_at=None,
        verbs_the_runner_executes=("case record", "batch"),
    )
    packet = steward_prompt.assemble(home, tmp_path / "cache", run, [])
    return packet.shared


def _copies(tmp_path) -> dict[str, str]:
    """name -> the document each writer is handed."""
    return {
        "teach": TEACH_MD.read_bytes().decode("utf-8"),
        "steward": _steward_shared(tmp_path),
        "overseer": formats._rules("B"),
    }


# ---------------------------------------------------------------- (a)


def test_canonical_file_exists_and_is_the_passage():
    assert CANON_PATH.is_file()
    text = _canon()
    assert text.startswith("**Writing a lesson**\n")
    assert PASSAGE_SENTINEL in text
    assert text.endswith("said by another lesson you name).\n")


@pytest.mark.parametrize("name", ["teach", "steward", "overseer"])
def test_each_inlined_copy_equals_the_canonical_file(tmp_path, name):
    document = _copies(tmp_path)[name]
    # positive control: the markers and the passage are really in the document,
    # so a None below cannot be read as "nothing to compare".
    assert lesson_writing.BEGIN in document and lesson_writing.END in document
    copy = lesson_writing.extract(document)
    assert copy is not None
    assert copy == _canon()
    assert copy.encode("utf-8") == CANON_PATH.read_bytes()


def test_each_copy_is_inlined_once_not_pointed_at(tmp_path):
    for name, document in _copies(tmp_path).items():
        assert document.count(PASSAGE_SENTINEL) == 1, name
        assert document.count(lesson_writing.BEGIN) == 1, name


def test_teach_command_section_two_holds_the_copy():
    document = TEACH_MD.read_text(encoding="utf-8")
    two = document.index("## 2. ")
    three = document.index("## 3. ")
    assert two < document.index(lesson_writing.BEGIN) < document.index(lesson_writing.END) < three


def test_overseer_phase_a_readme_carries_no_passage():
    """Phase A selects cases and writes no lesson text; only phase B writes
    lessons and gets the passage. Control: phase B has it."""
    assert lesson_writing.BEGIN in formats._rules("B")
    assert lesson_writing.BEGIN not in formats._rules("A")


# ---------------------------------------------------------------- (c)


@pytest.mark.parametrize("name", ["teach", "steward", "overseer"])
def test_one_character_drift_in_a_copy_is_caught(tmp_path, name):
    """The comparison in (a) must be able to fail: flip one character inside
    the markers of a copy and the equality no longer holds."""
    document = _copies(tmp_path)[name]
    assert lesson_writing.extract(document) == _canon()  # green before the mutation
    at = document.index(PASSAGE_SENTINEL)
    drifted = document[:at] + "X" + document[at + 1 :]
    assert drifted != document
    assert lesson_writing.extract(drifted) != _canon()


def test_a_copy_that_goes_missing_is_caught(tmp_path):
    document = _copies(tmp_path)["teach"]
    assert lesson_writing.extract(document) == _canon()
    gone = document.replace(lesson_writing.BEGIN, "")
    assert lesson_writing.extract(gone) is None


# ---------------------------------------------------------------- (b)

CONTEXT = "BACKGROUND-ONLY: the story of how the storage file got clobbered, twice."
BEHAVIOR = [
    "teach", "--skill", "s", "--type", "behavior", "--kind", "anti-pattern",
    "--trigger", "About to edit .storage while HA is running.",
    "--instruction", "Stop the container first.",
]


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.chdir(env.host)
    return env


def _only(ledger, bucket):
    (path,) = sorted((ledger.ledger / "skills" / "s" / bucket).glob("lrn-*.md"))
    return path


def test_teach_context_on_a_behavior_lesson_writes_a_context_section(ledger):
    assert cli.main(BEHAVIOR + ["--context", CONTEXT]) == 0
    record = Record.from_path(_only(ledger, "pending"))
    assert record.type == "behavior"
    assert "## Context" in record.body and CONTEXT in record.body
    # the loaded sections are untouched and Context follows them
    assert record.body.index("## Instruction") < record.body.index("## Context")


def test_teach_without_context_writes_no_context_section(ledger):
    """Control for the test above: no flag, no section."""
    assert cli.main(BEHAVIOR) == 0
    assert "## Context" not in Record.from_path(_only(ledger, "pending")).body


def test_the_compiled_line_never_carries_the_context(ledger):
    rc = cli.main(BEHAVIOR + ["--context", CONTEXT, "--route", "--dest", "skill-md", "--no-push"])
    assert rc == 0
    path = _only(ledger, "resolved")
    record = Record.from_path(path)
    # control: the record file holds the Context text ...
    assert CONTEXT in path.read_text(encoding="utf-8")
    # ... and the compiled canon holds the record's line (so it did compile) ...
    compiled = ledger.skill_md.read_text(encoding="utf-8")
    assert record.id in compiled and "stop the container first." in compiled
    # ... but never the Context text
    assert "BACKGROUND-ONLY" not in compiled
    assert "clobbered" not in compiled


def test_context_alone_still_means_a_knowledge_record(ledger):
    """The pre-E3a reading of `--context` with no behavior flag is kept."""
    assert cli.main(["teach", "--skill", "s", "--fact", "A fact.", "--context", CONTEXT]) == 0
    record = Record.from_path(_only(ledger, "pending"))
    assert record.type == "knowledge" and "## Context" in record.body
