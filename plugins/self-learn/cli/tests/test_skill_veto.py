"""SK7 (S-107): the user's view of the skills self-learn made, and
the user's veto.

Skill-writing plan, unit SK7, decision D15 (except the rename itself, SK8):

(a) ``overseer open`` prints each skill built, changed, retired or kept as a
    draft that week, and every live skill it has never shown, after the
    questions. On master it prints the questions only, so every positive
    assertion below is red there;
(b) ``overseer respond --veto-skill <name>`` records the user's typed words
    through the answer path (S-94: the statement is anchored to a
    presentation ``open`` recorded, never to an agent's words) and adds the
    name to the registry's ``vetoed`` list, after which the template check
    that ``skill write`` runs refuses the name;
(c) ``--retire-skill <name>`` records the request for the next run and
    changes nothing else;
(d) a veto or retirement naming a skill that self-learn does not own is
    refused by name, and nothing is recorded. A veto may also name a draft
    ``open`` showed (the drafts-only week); a retirement may not.

Written under the user's 2026-10-30 rule (tests run only for a significant
change): the orchestrator runs these once over the combined landing. Every
absence assertion ("nothing recorded", "not listed") sits beside a positive
control that shows the same check CAN see what it is looking for.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_learn import cases, skill_registry, skill_scaffold, statements
from self_learn.primitives import chrono
from self_learn.overseer import cli as overseer_cli
from self_learn.overseer import conversation
from support import commit_all, git, make_home
from test_overseer_conversation import _case, _yaml
from test_skill_template import NAME as BUILT, skill as valid_skill_files

REPORT_DATE = "2026-10-25"
THIS_WEEK = "2026-10-26T04:30:00Z"  # after the report's run began
LAST_MONTH = "2026-09-20T04:30:00Z"
SHA = "ab" * 32

CHANGED = "fixing-flaky-tests"
EARLY = "old-timer"
GONE = "gone-skill"
DRAFT_NEW = "summarising-prs"
VETO_WORDS = "That name is silly. Never use it again."
RETIRE_WORDS = "Retire it, I do not want this skill."


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    # The overseer's week starts at Sunday 04:15 LOCAL time; pin the zone so
    # the week the section covers does not depend on the machine's.
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


# ------------------------------------------------------------------ helpers


def _stamp(at: str, case_id: str, by: str = "overseer") -> dict:
    return {"at": at, "case": case_id, "by": by}


def _row(name: str, *, created: tuple[str, str], changed: tuple[str, str] | None = None) -> dict:
    """A live registry row built at *created* (at, case) and, when given,
    last rewritten at *changed*."""
    last_at, last_case = changed or created
    return {
        "status": "live",
        "plugin": f"plugins/{name}",
        "created": _stamp(*created),
        "last_write": {**_stamp(last_at, last_case), "authored_sha256": SHA},
    }


def _retired_row(name: str, *, created: tuple[str, str], retired: tuple[str, str]) -> dict:
    row = _row(name, created=created)
    row["status"] = "retired"
    row["retired"] = _stamp(*retired)
    return row


def _seed(home: Path, rows: dict[str, dict]) -> None:
    def put(registry: skill_registry.Registry) -> None:
        registry.skills.update(rows)

    skill_registry.with_update(home, put, subject="seed skills")


def _write_report(home: Path, *, header: str | None = None) -> Path:
    header = header or f"# Overseer report — {REPORT_DATE}   run 6d38cdd1   actor overseer   model m"
    overseer = home / "overseer"
    overseer.mkdir(parents=True, exist_ok=True)
    path = overseer / "latest-report.md"
    path.write_text(
        f"{header}\n\n## Examined\n- one\n\n## Questions for you\n- none\n\n"
        "## Refused / could not do\n- none\n",
        encoding="utf-8",
    )
    _yaml(overseer / "open-questions.yaml", {"questions": []})
    return path


def _write_draft(home: Path, week: str, name: str, *, description: str | None) -> None:
    folder = home / "overseer" / "skills" / week / "drafts" / name
    folder.mkdir(parents=True, exist_ok=True)
    if description is not None:
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8"
        )


def _open(home: Path) -> str:
    out = io.StringIO()
    conversation.open_questions(home, out=out)
    return out.getvalue()


def _section(text: str) -> str:
    assert "## Skills this week\n" in text, text
    return text.split("## Skills this week\n", 1)[1]


def _old_case(home: Path, tmp_path: Path, monkeypatch, suffix: str = "e5") -> str:
    """A case opened long ago: the ledger's oldest, so the case a draft with
    no live skill is presented on (`conversation.draft_anchor_case`)."""
    with monkeypatch.context() as patch:
        patch.setattr(chrono, "now_iso", lambda: "2026-01-01T00:00:00Z")
        return _case(home, tmp_path, suffix, {})


def _observations(home: Path, case_id: str) -> str:
    return cases.show(home, case_id, evidence_only=False).sections["Later observations"]


def _presented(home: Path, case_id: str) -> list[dict]:
    return cases.show(home, case_id, evidence_only=False).frontmatter["presented"]


def _vetoed_commits(home: Path, name: str) -> int:
    subjects = git(home, "log", "--format=%s").stdout.splitlines()
    return subjects.count(f"self-learn: veto skill name {name}")


@pytest.fixture
def world(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    """A ledger with a report dated 2026-10-25 and four registry rows: one
    built this week, one rewritten this week, one built last month and never
    shown, one retired this week; plus drafts for this week and for an old
    week, and an old case for the draft of a name nobody owns."""
    home = make_home(tmp_path)
    ids = {
        key: _case(home, tmp_path, suffix, {})
        for key, suffix in (("new", "a1"), ("changed", "b2"), ("early", "d4"), ("retired", "c3"))
    }
    ids["anchor"] = _old_case(home, tmp_path, monkeypatch)
    _seed(
        home,
        {
            BUILT: _row(BUILT, created=(THIS_WEEK, ids["new"])),
            CHANGED: _row(CHANGED, created=(LAST_MONTH, ids["early"]), changed=(THIS_WEEK, ids["changed"])),
            EARLY: _row(EARLY, created=(LAST_MONTH, ids["early"])),
            GONE: _retired_row(GONE, created=(LAST_MONTH, ids["early"]), retired=(THIS_WEEK, ids["retired"])),
        },
    )
    _write_report(home)
    _write_draft(
        home, REPORT_DATE, DRAFT_NEW,
        description="Summarises a pull request for a reviewer. Use when asked for a PR summary.",
    )
    _write_draft(home, REPORT_DATE, CHANGED, description="A rewrite of the flaky-test skill.")
    _write_draft(home, "2026-09-27", "stale-draft", description="An old week's draft.")
    commit_all(home, "seed skills view")
    return SimpleNamespace(home=home, tmp_path=tmp_path, ids=ids)


# ============================================================ (a) the week's view


class TestOpenListsTheWeeksSkills:
    def test_each_skill_built_changed_retired_or_drafted_is_listed_after_the_questions(self, world):
        text = _open(world.home)

        # Positive control: the questions block rendered, and first.
        assert text.startswith("## Questions for you\n- none\n\n## Skills this week\n")
        section = _section(text)
        ids = world.ids
        assert f"- skill {BUILT}: [new skill] built 2026-10-26 by overseer (case {ids['new']})\n" in section
        assert (
            f"- skill {CHANGED}: [skill changed] changed 2026-10-26 by overseer (case {ids['changed']})\n"
            in section
        )
        assert f"- skill {GONE}: [skill retired] retired 2026-10-26 by overseer (case {ids['retired']})\n" in section
        assert (
            f"- skill {DRAFT_NEW}: [skill drafted] would build it; kept as a draft, nothing deployed; "
            "description: Summarises a pull request for a reviewer. Use when asked for a PR summary.\n"
        ) in section
        # A draft of a skill that is already live is a draft of a change.
        assert (
            f"- skill {CHANGED}: [skill drafted] would change it; kept as a draft, nothing deployed; "
            "description: A rewrite of the flaky-test skill.\n"
        ) in section
        # A live skill whose week went by unshown is listed once, with its own date.
        assert f"- skill {EARLY}: [new skill] built 2026-09-20 by overseer (case {ids['early']})\n" in section

    def test_a_skill_already_shown_and_untouched_since_and_an_old_weeks_draft_are_not_listed(self, world):
        first = _open(world.home)
        assert f"- skill {EARLY}: [new skill]" in first  # control: shown the first time
        text = _open(world.home)
        # Control: the same output does list this week's skills, so the
        # absences below are not an empty section.
        assert f"- skill {BUILT}: [new skill]" in text
        assert EARLY not in text
        assert "stale-draft" not in text

    def test_the_section_says_how_to_veto_or_retire(self, world):
        section = _section(_open(world.home))
        assert "--veto-skill <name>" in section and "--retire-skill <name>" in section

    def test_a_ledger_with_no_skills_prints_exactly_the_questions(self, tmp_path):
        home = make_home(tmp_path)
        _write_report(home)
        commit_all(home, "seed report")
        # Control: the report and its index are real, so this is the
        # questions-only output and not a missing report.
        assert _open(home) == "## Questions for you\n- none\n"
        assert not (home / skill_registry.REGISTRY_FILENAME).exists()

    def test_skills_that_moved_before_the_report_print_nothing_once_they_were_shown(self, tmp_path):
        home = make_home(tmp_path)
        early = _case(home, tmp_path, "d4", {})
        _seed(home, {EARLY: _row(EARLY, created=(LAST_MONTH, early))})
        _write_report(home)
        commit_all(home, "seed")
        assert skill_registry.load(home).is_owned(EARLY)  # control: there is a live skill
        # Never shown, it is listed (the week it moved went by unseen) ...
        assert f"- skill {EARLY}: [new skill] built 2026-09-20" in _open(home)
        assert len(_presented(home, early)) == 1
        # ... and once shown it is quiet until it moves again.
        assert _open(home) == "## Questions for you\n- none\n"

    def test_a_built_or_changed_skill_is_recorded_as_shown_and_a_retired_one_is_not(self, world):
        _open(world.home)

        (shown,) = _presented(world.home, world.ids["new"])
        assert shown["via"] == "overseer-conversation"
        assert shown["to"] == "human"
        # Only the dependencies were shown, never the case's decision; no
        # user-model entry is flipped.
        assert shown["covering"] == "dependencies"
        assert shown["entries"] == []
        assert shown["outcome"] == "noted"
        assert (
            f"overseer presented: - skill {BUILT}: [new skill] built 2026-10-26 by overseer "
            f"(case {world.ids['new']})"
        ) in _observations(world.home, world.ids["new"])
        # The rewrite, and the draft of a further rewrite (recorded on the
        # live skill's own case): two distinct lines.
        assert len(_presented(world.home, world.ids["changed"])) == 2
        # A retired skill can be neither vetoed nor retired, so it is shown
        # and not recorded.
        assert _presented(world.home, world.ids["retired"]) == []
        # A live skill that did not move this week but was never shown is
        # recorded as shown the first time it is listed.
        assert len(_presented(world.home, world.ids["early"])) == 1
        # A draft of a name nobody owns is recorded on the ledger's oldest case.
        assert conversation.draft_anchor_case(world.home) == world.ids["anchor"]
        assert (
            f"overseer presented: - skill {DRAFT_NEW}: [skill drafted] would build it; kept as a draft"
        ) in _observations(world.home, world.ids["anchor"])

    def test_opening_again_records_the_same_line_once(self, world):
        _open(world.home)
        _open(world.home)
        assert len(_presented(world.home, world.ids["new"])) == 1

    def test_nothing_is_recorded_when_the_print_does_not_complete(self, world):
        class ClosedPipe(io.StringIO):
            def flush(self) -> None:
                raise BrokenPipeError("reader closed")

        with pytest.raises(BrokenPipeError):
            conversation.open_questions(world.home, out=ClosedPipe())
        assert _presented(world.home, world.ids["new"]) == []

    def test_an_unreadable_registry_is_one_line_and_the_questions_still_print(self, tmp_path):
        home = make_home(tmp_path)
        _write_report(home)
        (home / skill_registry.REGISTRY_FILENAME).write_text("version: 1\nbogus: 1\n", encoding="utf-8")
        commit_all(home, "seed a bad registry")
        text = _open(home)
        assert text.startswith("## Questions for you\n- none\n\n## Skills this week\n- skills not shown: ")
        assert "bogus" in text

    def test_a_skill_whose_case_cannot_be_observed_is_named_on_stderr_and_cannot_be_vetoed(
        self, tmp_path, capsys
    ):
        home = make_home(tmp_path)
        _seed(home, {BUILT: _row(BUILT, created=(THIS_WEEK, "case-0badc0de"))})
        _write_report(home)
        commit_all(home, "seed")

        text = _open(home)

        # The line is shown (control), the failure is named, nothing crashed.
        assert f"- skill {BUILT}: [new skill] built" in text
        assert f"skill {BUILT}: not recorded as shown" in capsys.readouterr().err
        with pytest.raises(conversation.ConversationError, match="has not shown that skill"):
            conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)


class TestTheDraftsWindow:
    @pytest.mark.parametrize(
        ("week", "listed"),
        [
            ("2026-10-19", True),   # six days before the report: this week's
            ("2026-10-18", False),  # seven days before: the week before
            ("2026-10-25", True),
            ("2026-10-26", True),   # a host east of UTC keys the week a day later
            ("2026-10-27", False),
        ],
    )
    def test_a_draft_belongs_to_the_report_week_by_its_week_key(self, tmp_path, week, listed):
        home = make_home(tmp_path)
        _write_report(home)
        _write_draft(home, week, DRAFT_NEW, description="Summarises pull requests.")
        _write_draft(home, REPORT_DATE, "always-there", description="Control draft.")
        commit_all(home, "seed")
        text = _open(home)
        assert "- skill always-there: [skill drafted]" in text  # control: the section renders
        assert (f"- skill {DRAFT_NEW}: [skill drafted]" in text) is listed

    def test_a_draft_that_cannot_be_read_is_listed_without_a_description(self, tmp_path):
        home = make_home(tmp_path)
        _write_report(home)
        _write_draft(home, REPORT_DATE, "no-skill-md", description=None)
        _write_draft(home, REPORT_DATE, "described", description="Has words.")
        commit_all(home, "seed")
        section = _section(_open(home))
        assert (
            "- skill described: [skill drafted] would build it; kept as a draft, nothing deployed; "
            "description: Has words.\n"
        ) in section
        assert "- skill no-skill-md: [skill drafted] would build it; kept as a draft, nothing deployed\n" in section

    def test_a_long_description_is_cut_to_one_bounded_line(self, tmp_path):
        home = make_home(tmp_path)
        _write_report(home)
        _write_draft(home, REPORT_DATE, "wordy", description="word " * 100)
        commit_all(home, "seed")
        (line,) = [ln for ln in _section(_open(home)).splitlines() if ln.startswith("- skill wordy:")]
        assert len(line.split("description: ", 1)[1]) <= conversation._DRAFT_DESCRIPTION_MAX


class TestTheReportsStart:
    """The window is the overseer's week the latest report belongs to (the
    Sunday 04:15 boundary at or before the end of the report's UTC day), or
    the report's own day when that is later; the report's day is the UTC date
    in its first line, else the day its file was written."""

    @staticmethod
    def _changed_line(home: Path, at: str, tmp_path: Path, *, header: str | None = None) -> bool:
        """Whether `open` lists a rewrite made at *at* as this week's change.
        The skill was built last month, so when the rewrite is outside the
        window the only line about it is the never-shown `[new skill]` one."""
        case_id = _case(home, tmp_path, "a1", {})
        _seed(home, {BUILT: _row(BUILT, created=(LAST_MONTH, case_id), changed=(at, case_id))})
        _write_report(home, header=header)
        _write_draft(home, REPORT_DATE, "always-there", description="Control draft.")
        commit_all(home, "seed")
        text = _open(home)
        assert "- skill always-there: [skill drafted]" in text  # control: the section renders
        assert f"- skill {BUILT}: [new skill] built 2026-09-20" in text or f"- skill {BUILT}: [skill changed]" in text
        return f"- skill {BUILT}: [skill changed] changed" in text

    @pytest.mark.parametrize(
        ("at", "listed"),
        [
            ("2026-10-25T00:00:00Z", True),   # the report's own first second
            ("2026-10-24T23:59:59Z", False),  # a second before it
        ],
    )
    def test_a_report_on_the_boundary_day_opens_the_window_at_midnight(self, tmp_path, at, listed):
        assert self._changed_line(make_home(tmp_path), at, tmp_path) is listed

    @pytest.mark.parametrize(
        ("at", "listed"),
        [
            ("2026-10-25T04:15:00Z", True),   # the Sunday boundary that opened the report's week
            ("2026-10-25T04:14:59Z", False),  # the week before
        ],
    )
    def test_a_mid_week_report_still_covers_the_whole_week(self, tmp_path, at, listed):
        # 2026-10-28 is the Wednesday after: a manual run replaced the
        # scheduled run's report, and what the scheduled run built on Sunday
        # morning must not fall out of the section.
        header = "# Overseer report — 2026-10-28   run 6d38cdd1   actor overseer   model m"
        home = make_home(tmp_path)
        assert self._changed_line(home, at, tmp_path, header=header) is listed

    def test_a_report_without_a_date_uses_the_day_its_file_was_written(self, tmp_path):
        home = make_home(tmp_path)
        case_id = _case(home, tmp_path, "a1", {})
        _seed(home, {BUILT: _row(BUILT, created=(THIS_WEEK, case_id))})
        report = _write_report(home, header="# Overseer report")
        commit_all(home, "seed")

        written = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc).timestamp()
        os.utime(report, (written, written))
        assert f"- skill {BUILT}: [new skill] built" in _open(home)  # control: in the window

        later = datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc).timestamp()
        os.utime(report, (later, later))
        assert _open(home) == "## Questions for you\n- none\n"


# ================================================================ (b) the veto


class TestVeto:
    def test_the_words_are_recorded_the_name_is_banned_and_the_case_is_told(self, world):
        home = world.home
        _open(home)
        # Control: before the veto the template check accepts the name.
        before = skill_scaffold.check_skill(
            valid_skill_files(), loaded_names=(), vetoed_names=skill_registry.load(home).vetoed_names(),
            expected_name=BUILT,
        )
        assert before.ok

        result = conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)

        stored = next(row for row in statements.list_statements(home) if row["id"] == result.statement_id)
        assert stored["verbatim"] == VETO_WORDS
        assert stored["answers"]["kind"] == "instruction"
        assert stored["answers"]["ref"] == f"veto-skill:{BUILT}"
        assert stored["answers"]["text"].startswith(f"- skill {BUILT}: [new skill] built 2026-10-26")
        assert stored["scope"] == {"level": "user", "host": None}
        assert stored["recorded_by"] == "human"
        assert stored["source"]["message_ref"].startswith("conversation:obs-")
        assert result.observed_cases == (world.ids["new"],)

        registry = skill_registry.load(home)
        assert [(v["name"], v["statement"]) for v in registry.vetoed] == [(BUILT, result.statement_id)]
        assert registry.is_owned(BUILT)  # a veto bans the name; it does not retire the skill
        assert _vetoed_commits(home, BUILT) == 1
        assert (
            f"overseer statement: user vetoed the name of skill {BUILT} (ref: {result.statement_id})"
            in _observations(home, world.ids["new"])
        )

        after = skill_scaffold.check_skill(
            valid_skill_files(), loaded_names=(), vetoed_names=registry.vetoed_names(), expected_name=BUILT
        )
        assert after.problem_rules == (skill_scaffold.RULE_NAME_VETOED,)

    def test_the_veto_is_anchored_to_the_presentation_open_recorded(self, world):
        _open(world.home)
        (shown,) = _presented(world.home, world.ids["new"])
        result = conversation.respond_skill(world.home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)
        stored = next(row for row in statements.list_statements(world.home) if row["id"] == result.statement_id)
        assert stored["source"]["message_ref"] == f"conversation:{shown['id']}"

    def test_as_asked_replaces_the_recorded_question(self, world):
        _open(world.home)
        result = conversation.respond_skill(
            world.home, action="veto", name=BUILT, scope="user", text=VETO_WORDS,
            as_asked="Should the diagram skill keep this name?",
        )
        stored = next(row for row in statements.list_statements(world.home) if row["id"] == result.statement_id)
        assert stored["answers"]["text"] == "Should the diagram skill keep this name?"

    def test_the_scope_is_what_the_user_said(self, world):
        _open(world.home)
        result = conversation.respond_skill(
            world.home, action="veto", name=BUILT, scope="project:/work/repo", text=VETO_WORDS
        )
        stored = next(row for row in statements.list_statements(world.home) if row["id"] == result.statement_id)
        assert stored["scope"] == {"level": "project", "host": "/work/repo"}

    def test_saying_it_again_changes_nothing(self, world):
        home = world.home
        _open(home)
        first = conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)
        again = conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)
        assert again.statement_id == first.statement_id
        assert len(skill_registry.load(home).vetoed) == 1
        assert _vetoed_commits(home, BUILT) == 1
        assert len([r for r in statements.list_statements(home) if r["answers"]["ref"] == f"veto-skill:{BUILT}"]) == 1
        observations = _observations(home, world.ids["new"])
        assert observations.count(f"user vetoed the name of skill {BUILT}") == 1

    def test_a_vetoed_skill_waits_for_its_new_name_until_it_has_one(self, world):
        home = world.home
        _open(home)
        assert conversation.pending_renames(home) == []  # control: nothing waits yet
        result = conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)

        (waiting,) = conversation.pending_renames(home)
        assert (waiting["name"], waiting["statement"]) == (BUILT, result.statement_id)
        shown = _section(_open(home))
        assert f"- skill {BUILT}: [name vetoed] waits for a new name" in shown
        assert result.statement_id in shown

        # The skill is renamed (as skill rename will leave the registry): the
        # old name stays banned, and nothing waits.
        def renamed(registry: skill_registry.Registry) -> None:
            row = registry.skills.pop(BUILT)
            row["plugin"] = "plugins/better-name"
            row["renamed_from"] = [BUILT]
            registry.skills["better-name"] = row

        skill_registry.with_update(home, renamed, subject="rename for the test")
        assert conversation.pending_renames(home) == []
        assert skill_registry.load(home).vetoed_names() == [BUILT]
        assert "[name vetoed]" not in _open(home)


# ============================================================ (c) the retirement


class TestRetireRequest:
    def test_the_request_is_recorded_and_nothing_else_changes(self, world):
        home = world.home
        _open(home)
        registry_before = (home / skill_registry.REGISTRY_FILENAME).read_bytes()
        assert conversation.pending_retire_requests(home) == []  # control: no request yet

        result = conversation.respond_skill(home, action="retire", name=BUILT, scope="user", text=RETIRE_WORDS)

        stored = next(row for row in statements.list_statements(home) if row["id"] == result.statement_id)
        assert stored["verbatim"] == RETIRE_WORDS
        assert stored["answers"]["kind"] == "instruction"
        assert stored["answers"]["ref"] == f"retire-skill:{BUILT}"
        assert stored["source"]["message_ref"].startswith("conversation:obs-")
        # The registry is untouched: the overseer's next run decides.
        assert (home / skill_registry.REGISTRY_FILENAME).read_bytes() == registry_before
        assert skill_registry.load(home).is_owned(BUILT)
        assert skill_registry.load(home).vetoed == []
        (pending,) = conversation.pending_retire_requests(home)
        assert pending["name"] == BUILT
        assert pending["statement"] == result.statement_id
        assert pending["verbatim"] == RETIRE_WORDS
        assert pending["scope"] == {"level": "user", "host": None}
        assert (
            f"overseer statement: user asked for skill {BUILT} to be retired (ref: {result.statement_id})"
            in _observations(home, world.ids["new"])
        )

    def test_open_then_shows_the_request_as_waiting(self, world):
        home = world.home
        _open(home)
        result = conversation.respond_skill(home, action="retire", name=BUILT, scope="user", text=RETIRE_WORDS)
        shown = _section(_open(home))
        assert f"- skill {BUILT}: [retirement requested] waits for an overseer run that writes skills" in shown
        assert result.statement_id in shown

    def test_the_newest_request_for_a_skill_is_the_one_pending(self, world):
        home = world.home
        _open(home)
        conversation.respond_skill(home, action="retire", name=BUILT, scope="user", text="Retire it.")
        second = conversation.respond_skill(home, action="retire", name=BUILT, scope="user", text="Please retire it now.")
        (pending,) = conversation.pending_retire_requests(home)
        assert pending["statement"] == second.statement_id

    def test_a_request_is_no_longer_pending_once_the_skill_is_retired(self, world):
        home = world.home
        _open(home)
        conversation.respond_skill(home, action="retire", name=BUILT, scope="user", text=RETIRE_WORDS)
        assert len(conversation.pending_retire_requests(home)) == 1  # control

        def retire(registry: skill_registry.Registry) -> None:
            row = registry.skills[BUILT]
            row["status"] = "retired"
            row["retired"] = _stamp("2026-11-02T04:30:00Z", world.ids["new"])

        skill_registry.with_update(home, retire, subject="retire for the test")
        assert conversation.pending_retire_requests(home) == []

    def test_a_request_made_before_the_skill_was_created_belongs_to_an_earlier_skill(self, tmp_path):
        home = make_home(tmp_path)
        case_id = _case(home, tmp_path, "a1", {})
        _write_report(home)
        commit_all(home, "seed report")
        # Built in the far future, so a request made now precedes it. The
        # control is the same skill built in the past: the request counts.
        for created, pending in (("2026-10-26T04:30:00Z", 1), ("2099-01-01T00:00:00Z", 0)):
            _seed(home, {BUILT: _row(BUILT, created=(created, case_id))})
            _open(home)
            conversation.respond_skill(
                home, action="retire", name=BUILT, scope="user", text=f"Retire it ({created})."
            )
            assert len(conversation.pending_retire_requests(home)) == pending, created


class TestTheSameWordsForTheOtherRequest:
    def test_identical_words_cannot_stand_for_both_a_veto_and_a_retirement(self, world):
        home = world.home
        _open(home)
        conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text="No.")

        with pytest.raises(conversation.ConversationError, match="already recorded"):
            conversation.respond_skill(home, action="retire", name=BUILT, scope="user", text="No.")
        assert conversation.pending_retire_requests(home) == []

        # Control: other words are their own statement.
        conversation.respond_skill(home, action="retire", name=BUILT, scope="user", text="No, retire it.")
        assert len(conversation.pending_retire_requests(home)) == 1


# =============================================== (d) refused by name, nothing recorded


class TestRefusals:
    def _nothing_recorded(self, home: Path, registry_before: bytes) -> None:
        assert statements.list_statements(home) == []
        assert (home / skill_registry.REGISTRY_FILENAME).read_bytes() == registry_before

    @pytest.mark.parametrize(
        ("action", "name"),
        [
            ("veto", "no-such-skill"),    # unknown
            ("retire", "no-such-skill"),
            ("veto", GONE),               # a retired skill is not owned
            ("retire", GONE),
            ("retire", DRAFT_NEW),        # a draft was never deployed: nothing to retire
        ],
    )
    def test_a_skill_self_learn_does_not_own_is_refused_by_name(self, world, action, name):
        home = world.home
        _open(home)
        registry_before = (home / skill_registry.REGISTRY_FILENAME).read_bytes()

        with pytest.raises(conversation.ConversationError, match=f"{name} is not a skill self-learn owns"):
            conversation.respond_skill(home, action=action, name=name, scope="user", text=VETO_WORDS)

        self._nothing_recorded(home, registry_before)
        # Control: the same call for a skill it does own is accepted, so the
        # refusal was about the name and not a broken setup.
        conversation.respond_skill(home, action=action, name=BUILT, scope="user", text=VETO_WORDS)
        assert len(statements.list_statements(home)) == 1

    def test_the_refusal_names_the_skills_that_could_have_been_meant(self, world):
        _open(world.home)
        with pytest.raises(conversation.ConversationError, match=f"live skills: .*{BUILT}"):
            conversation.respond_skill(world.home, action="veto", name="nope", scope="user", text="No.")

    @pytest.mark.parametrize("name", ["Not A Name", "UPPER", "a" * 65, ""])
    def test_a_name_that_is_not_a_skill_name_is_a_usage_error(self, world, name):
        _open(world.home)
        registry_before = (world.home / skill_registry.REGISTRY_FILENAME).read_bytes()
        with pytest.raises(conversation.ConversationUsageError, match="skill name"):
            conversation.respond_skill(world.home, action="veto", name=name, scope="user", text="No.")
        self._nothing_recorded(world.home, registry_before)

    def test_a_skill_open_has_not_shown_is_refused(self, world):
        home = world.home
        registry_before = (home / skill_registry.REGISTRY_FILENAME).read_bytes()
        # `open` has not run: nothing was shown, so there is nothing to answer.
        with pytest.raises(conversation.ConversationError, match="has not shown that skill"):
            conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)
        self._nothing_recorded(home, registry_before)
        # Control: after `open` the same call is accepted.
        _open(home)
        conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=VETO_WORDS)

    def test_a_veto_of_a_name_no_draft_showed_is_refused(self, world):
        home = world.home
        registry_before = (home / skill_registry.REGISTRY_FILENAME).read_bytes()
        # `open` has not run, so no draft was shown: the draft's name is
        # refused like any name self-learn does not own.
        with pytest.raises(conversation.ConversationError, match=f"{DRAFT_NEW} is not a skill self-learn owns"):
            conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)
        self._nothing_recorded(home, registry_before)
        _open(home)  # control: once shown, the same call is accepted
        conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)

    @pytest.mark.parametrize("scope", ["", "project:", "everywhere"])
    def test_a_missing_or_bad_scope_records_nothing(self, world, scope):
        home = world.home
        _open(home)
        registry_before = (home / skill_registry.REGISTRY_FILENAME).read_bytes()
        with pytest.raises(conversation.ConversationUsageError, match="scope"):
            conversation.respond_skill(home, action="veto", name=BUILT, scope=scope, text="No.")
        self._nothing_recorded(home, registry_before)

    @pytest.mark.parametrize("text", ["", "   "])
    def test_empty_words_record_nothing(self, world, text):
        home = world.home
        _open(home)
        registry_before = (home / skill_registry.REGISTRY_FILENAME).read_bytes()
        with pytest.raises(conversation.ConversationUsageError, match="--text is required"):
            conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text=text)
        self._nothing_recorded(home, registry_before)

    def test_a_secret_in_the_words_is_refused_and_nothing_is_banned(self, world):
        from self_learn.scan import scan as secret_scan

        home = world.home
        _open(home)
        registry_before = (home / skill_registry.REGISTRY_FILENAME).read_bytes()
        token = "ghp_" + "Ab1" * 12
        assert secret_scan(token), "positive control: the scanner fires on this token"
        with pytest.raises(statements.StatementError):
            conversation.respond_skill(
                home, action="veto", name=BUILT, scope="user", text=f"veto it, the token is {token}",
            )
        self._nothing_recorded(home, registry_before)
        assert skill_registry.load(home).vetoed == []

    def test_an_unreadable_registry_is_refused_by_the_file_not_guessed_past(self, world):
        home = world.home
        _open(home)
        (home / skill_registry.REGISTRY_FILENAME).write_text("version: 1\nbogus: 1\n", encoding="utf-8")
        with pytest.raises(conversation.ConversationError, match="bogus"):
            conversation.respond_skill(home, action="veto", name=BUILT, scope="user", text="No.")
        assert statements.list_statements(home) == []


# ======================================= a skill is never out of reach of the veto


class TestASkillOpenNeverShownCanStillBeVetoed:
    """The window is the report's week, but the veto has no time limit: a
    live skill `open` has not shown before is shown (and recorded) the next
    time `open` runs, whenever the skill moved."""

    def test_the_week_the_skill_moved_went_by_unseen(self, world):
        home = world.home
        # Before `open` has run the skill was never shown (control: the
        # refusal that the old rule gave for every skill outside the week).
        with pytest.raises(conversation.ConversationError, match="has not shown that skill"):
            conversation.respond_skill(home, action="veto", name=EARLY, scope="user", text=VETO_WORDS)

        assert f"- skill {EARLY}: [new skill] built 2026-09-20" in _open(home)  # built last month

        result = conversation.respond_skill(home, action="veto", name=EARLY, scope="user", text=VETO_WORDS)
        assert skill_registry.load(home).vetoed_names() == [EARLY]
        assert result.observed_cases == (world.ids["early"],)

    def test_the_skill_is_shown_once_and_the_veto_still_works_in_a_later_week(self, world):
        home = world.home
        assert f"- skill {EARLY}:" in _open(home)
        assert f"- skill {EARLY}:" not in _open(home)  # not listed a second time
        # A later weekly report moves the window past everything.
        _write_report(home, header="# Overseer report — 2026-11-15   run 77aa77aa   actor overseer   model m")
        assert f"- skill {BUILT}:" not in _open(home)  # control: the window did move
        conversation.respond_skill(home, action="retire", name=EARLY, scope="user", text=RETIRE_WORDS)
        assert [r["name"] for r in conversation.pending_retire_requests(home)] == [EARLY]

    def test_a_renamed_skill_is_shown_under_its_new_name(self, tmp_path):
        home = make_home(tmp_path)
        case_id = _case(home, tmp_path, "a1", {})
        row = _row("better-name", created=(LAST_MONTH, case_id))
        row["renamed_from"] = [BUILT]
        _seed(home, {"better-name": row})
        _write_report(home)
        commit_all(home, "seed")

        text = _open(home)

        assert (
            f"- skill better-name: [skill renamed] renamed 2026-09-20 by overseer (case {case_id}); was {BUILT}"
        ) in text
        conversation.respond_skill(home, action="veto", name="better-name", scope="user", text=VETO_WORDS)

    def test_a_stamp_with_no_case_names_no_case_and_has_nothing_to_record_on(self):
        # The registry as it stands on this branch refuses a null case, so the
        # shape a person's CLI step without --case will leave (S-107,
        # part 2) is checked on the pure helpers: such a stamp prints "no case"
        # and names none to attach the user's words to.
        stamp = {"at": LAST_MONTH, "case": None, "by": "human"}
        row = {"created": stamp, "last_write": dict(stamp, authored_sha256=SHA)}
        assert conversation._stamp_cases(row) == []
        assert conversation._case_of(stamp, row) is None
        line = conversation._moved_line(BUILT, "[new skill]", "built", stamp)
        assert line == f"- skill {BUILT}: [new skill] built 2026-09-20 by human (no case)"
        # Control: with a case on the row, the same stamp is recorded there.
        with_case = {"created": stamp, "last_write": {**stamp, "case": "case-0badc0de"}}
        assert conversation._case_of(stamp, with_case) == "case-0badc0de"

    def test_a_line_with_no_case_to_be_recorded_on_is_named_on_stderr(self, tmp_path, capsys):
        home = make_home(tmp_path)
        conversation._present_skill(home, None, BUILT, f"- skill {BUILT}: [new skill] built")
        assert f"skill {BUILT}: not recorded as shown" in capsys.readouterr().err


# ================================== a draft's name can be vetoed before anything is deployed


class TestVetoOfADraftsName:
    def test_the_name_is_banned_before_a_skill_exists_under_it(self, world):
        home = world.home
        _open(home)
        registry_before = skill_registry.load(home)
        assert not registry_before.is_owned(DRAFT_NEW)  # control: nothing is deployed under it
        draft_files = valid_skill_files(front={"name": json.dumps(DRAFT_NEW)})
        assert skill_scaffold.check_skill(
            draft_files, loaded_names=(), vetoed_names=[], expected_name=DRAFT_NEW
        ).ok  # control: the template check accepts the name before the veto

        result = conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)

        stored = next(row for row in statements.list_statements(home) if row["id"] == result.statement_id)
        assert stored["answers"]["ref"] == f"veto-skill:{DRAFT_NEW}"
        assert stored["answers"]["kind"] == "instruction"
        assert stored["recorded_by"] == "human"
        assert stored["answers"]["text"].startswith(f"- skill {DRAFT_NEW}: [skill drafted] would build it;")
        # Anchored to the presentation recorded on the ledger's oldest case.
        (shown,) = [
            p for p in _presented(home, world.ids["anchor"]) if f"conversation:{p['id']}" == stored["source"]["message_ref"]
        ]
        assert shown["covering"] == "dependencies"
        assert result.observed_cases == (world.ids["anchor"],)
        assert f"user vetoed the name of skill {DRAFT_NEW}" in _observations(home, world.ids["anchor"])

        registry = skill_registry.load(home)
        assert [(v["name"], v["statement"]) for v in registry.vetoed] == [(DRAFT_NEW, result.statement_id)]
        assert not registry.is_owned(DRAFT_NEW)  # a veto does not create a skill
        after = skill_scaffold.check_skill(
            draft_files, loaded_names=(), vetoed_names=registry.vetoed_names(), expected_name=DRAFT_NEW
        )
        assert after.problem_rules == (skill_scaffold.RULE_NAME_VETOED,)

    def test_open_then_shows_the_draft_as_needing_another_name(self, world):
        home = world.home
        _open(home)
        conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)
        section = _section(_open(home))
        assert (
            f"- skill {DRAFT_NEW}: [skill drafted] would build it, but the name is vetoed; "
            "the next overseer run must give the draft another name or not build it\n"
        ) in section
        assert f"- skill {DRAFT_NEW}: [skill drafted] would build it; kept" not in section
        # It is not a pending rename: nothing is live under the name.
        assert conversation.pending_renames(home) == []

    def test_saying_it_again_changes_nothing(self, world):
        home = world.home
        _open(home)
        first = conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)
        again = conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)
        assert again.statement_id == first.statement_id
        assert _vetoed_commits(home, DRAFT_NEW) == 1
        assert _observations(home, world.ids["anchor"]).count(f"user vetoed the name of skill {DRAFT_NEW}") == 1

    def test_the_anchor_does_not_move_when_newer_cases_are_opened(self, world, tmp_path):
        home = world.home
        _open(home)
        _case(home, tmp_path, "f6", {})  # a case opened after the draft was shown
        assert conversation.draft_anchor_case(home) == world.ids["anchor"]
        # The presentation is still found where it was recorded.
        conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)

    def test_a_draft_of_a_live_skill_is_presented_on_the_skills_own_case(self, world):
        home = world.home
        _open(home)
        assert (
            f"overseer presented: - skill {CHANGED}: [skill drafted] would change it;"
            in _observations(home, world.ids["changed"])
        )
        assert f"- skill {CHANGED}: [skill drafted]" not in _observations(home, world.ids["anchor"])

    def test_a_ledger_with_no_case_cannot_record_a_draft_and_says_so(self, tmp_path, capsys):
        home = make_home(tmp_path)
        _write_report(home)
        _write_draft(home, REPORT_DATE, DRAFT_NEW, description="Summarises pull requests.")
        commit_all(home, "seed")

        text = _open(home)

        assert f"- skill {DRAFT_NEW}: [skill drafted] would build it;" in text  # control: it is shown
        assert f"skill {DRAFT_NEW}: not recorded as shown" in capsys.readouterr().err
        with pytest.raises(conversation.ConversationError, match="has not shown a draft"):
            conversation.respond_skill(home, action="veto", name=DRAFT_NEW, scope="user", text=VETO_WORDS)
        assert statements.list_statements(home) == []


# ============================================================ the CLI surface


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="verb", required=True)
    overseer_cli.add_parser(sub)
    return parser


class TestCli:
    def test_open_prints_the_skills_section(self, world, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(world.home))
        assert overseer_cli.dispatch(_parser().parse_args(["overseer", "open"])) == 0
        out = capsys.readouterr().out
        assert out.startswith("## Questions for you\n- none\n\n## Skills this week\n")
        assert f"- skill {BUILT}: [new skill]" in out

    def test_veto_skill(self, world, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(world.home))
        parser = _parser()
        overseer_cli.dispatch(parser.parse_args(["overseer", "open"]))
        capsys.readouterr()

        args = parser.parse_args(
            ["overseer", "respond", "--veto-skill", BUILT, "--scope", "user", "--text", VETO_WORDS]
        )
        assert overseer_cli.dispatch(args) == 0

        out = capsys.readouterr().out
        assert "recorded stmt-" in out and f"the name {BUILT} is vetoed for ever" in out
        assert skill_registry.load(world.home).vetoed_names() == [BUILT]

    def test_retire_skill(self, world, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(world.home))
        parser = _parser()
        overseer_cli.dispatch(parser.parse_args(["overseer", "open"]))
        capsys.readouterr()

        args = parser.parse_args(
            ["overseer", "respond", "--retire-skill", BUILT, "--scope", "user", "--text", RETIRE_WORDS]
        )
        assert overseer_cli.dispatch(args) == 0

        out = capsys.readouterr().out
        assert f"retirement of {BUILT} is asked of the overseer" in out
        assert [r["name"] for r in conversation.pending_retire_requests(world.home)] == [BUILT]
        assert skill_registry.load(world.home).vetoed == []

    def test_a_skill_self_learn_does_not_own_exits_1_with_the_reason(self, world, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(world.home))
        parser = _parser()
        overseer_cli.dispatch(parser.parse_args(["overseer", "open"]))
        capsys.readouterr()
        args = parser.parse_args(
            ["overseer", "respond", "--veto-skill", "no-such-skill", "--scope", "user", "--text", "No."]
        )
        assert overseer_cli.dispatch(args) == 1
        assert "no-such-skill is not a skill self-learn owns" in capsys.readouterr().err
        assert statements.list_statements(world.home) == []

    def test_veto_of_a_drafts_name(self, world, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(world.home))
        parser = _parser()
        overseer_cli.dispatch(parser.parse_args(["overseer", "open"]))
        capsys.readouterr()
        args = parser.parse_args(
            ["overseer", "respond", "--veto-skill", DRAFT_NEW, "--scope", "user", "--text", VETO_WORDS]
        )
        assert overseer_cli.dispatch(args) == 0
        assert skill_registry.load(world.home).vetoed_names() == [DRAFT_NEW]
        # The promise names what really happens in each case: a rename waits
        # for a run that writes skills, or the person's own command.
        out = capsys.readouterr().out
        assert "renamed by the next overseer run that writes skills" in out
        assert "self-learn skill rename" in out

    def test_an_empty_skill_name_is_a_usage_error_and_not_the_proposition_path(
        self, world, monkeypatch, capsys
    ):
        monkeypatch.setenv("SELF_LEARN_HOME", str(world.home))
        args = _parser().parse_args(
            ["overseer", "respond", "--veto-skill", "", "--scope", "user", "--text", "No."]
        )
        assert overseer_cli.dispatch(args) == 1
        err = capsys.readouterr().err
        assert "needs a skill name" in err
        assert "None" not in err
        assert statements.list_statements(world.home) == []

    def test_decline_does_not_apply_to_a_skill(self, world, monkeypatch, capsys):
        monkeypatch.setenv("SELF_LEARN_HOME", str(world.home))
        parser = _parser()
        overseer_cli.dispatch(parser.parse_args(["overseer", "open"]))
        capsys.readouterr()
        args = parser.parse_args(["overseer", "respond", "--veto-skill", BUILT, "--decline"])
        assert overseer_cli.dispatch(args) == 1
        assert "--decline" in capsys.readouterr().err
        assert statements.list_statements(world.home) == []

    def test_a_skill_flag_needs_the_words(self):
        with pytest.raises(SystemExit):
            _parser().parse_args(["overseer", "respond", "--veto-skill", BUILT, "--scope", "user"])

    def test_exactly_one_target_is_required(self):
        parser = _parser()
        # Control: one target parses.
        assert parser.parse_args(["overseer", "respond", "--veto-skill", "x", "--text", "t"]).veto_skill == "x"
        for argv in (
            ["overseer", "respond", "--text", "t"],
            ["overseer", "respond", "--veto-skill", "x", "--retire-skill", "x", "--text", "t"],
            ["overseer", "respond", "--veto-skill", "x", "--proposition", "q-a", "--text", "t"],
        ):
            with pytest.raises(SystemExit):
                parser.parse_args(argv)

    def test_the_question_flags_still_parse_as_before(self):
        args = _parser().parse_args(
            ["overseer", "respond", "--proposition", "q-a", "--scope", "user", "--text", "t"]
        )
        assert (args.proposition, args.veto_skill, args.retire_skill) == ("q-a", None, None)
