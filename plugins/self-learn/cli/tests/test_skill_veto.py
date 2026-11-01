"""SK-B (S-110): the user stops a skill by saying so; nothing is
presented and nothing is asked.

Skills design ``misc/build-2026-10-31b/skills.md`` lane SK-B, as amended by
the round's decisions 1 and 6 (an agent's shell runs a person-only skill
command under the user's standing grant with ``--note``, never on
per-session typed words). It replaces the S-107 SK7 tests of the "Skills
this week" section and ``overseer respond --veto-skill|--retire-skill``,
which are gone.

Every absence assertion ("nothing printed", "nothing recorded") sits after a
positive control that shows the same check CAN see what it looks for.
"""

from __future__ import annotations

import io

import pytest

from self_learn import cases, cli, grants, skill_registry, skill_requests, skill_writer
from self_learn.overseer import conversation, skills as skills_mod
from self_learn.skill_scaffold import _read_frontmatter
from support import commit_all, git
from test_grants import _stmt
from test_overseer_conversation import _ask, _case, _report_and_index
from test_skill_rename import NEW, RID_A, RID_B, _route
from test_skill_write import CASE, NAME, Env, _rules, draft

UNUSED = "never-used-name"


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


def _grant(env: Env) -> str:
    stmt = _stmt(env.home, env.tmp)
    assert grants.add(env.home, statement=stmt)[1] is True
    return stmt


def _agent(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")


def _observations(home, case_id: str) -> str:
    return cases.show(home, case_id, evidence_only=False).sections.get("Later observations", "")


# ============================================ 1. overseer open shows no skill


def test_1_overseer_open_shows_no_skill_and_records_no_presentation_of_one(env, tmp_path):
    """A live owned skill, a draft folder and a pending retire request: the
    output is the questions alone, and no case gains a skill presentation."""
    assert env.write().ok  # a live skill self-learn owns, written by case CASE
    draft_dir = env.home / "overseer" / "skills" / "2026-10-25" / "drafts" / "summing-prs"
    draft_dir.mkdir(parents=True)
    (draft_dir / "SKILL.md").write_text(
        "---\nname: summing-prs\ndescription: Sums PRs.\n---\n", encoding="utf-8"
    )
    commit_all(env.home, "a draft")
    assert skill_requests.request_retire(env.home, NAME, by="human").ok
    ask_case = _case(env.home, tmp_path, "000000a1", {})
    ask = _ask("q-something", [ask_case])
    _report_and_index(env.home, [ask], ["- q-something: something"])
    out = io.StringIO()

    shown = conversation.open_questions(env.home, out=out)

    text = out.getvalue()
    # Positive control: the question is printed and its presentation recorded.
    assert shown == 1
    assert f"- q-something: {ask['text']}" in text
    assert "overseer presented: - q-something" in _observations(env.home, ask_case)
    # No skill is shown, named or recorded as shown.
    assert "Skills this week" not in text
    assert NAME not in text and "summing-prs" not in text and "- skill " not in text
    for row in cases.list_cases(env.home, only_ok=True):
        assert "- skill " not in _observations(env.home, str(row["case"]))


def test_the_overseer_cli_no_longer_takes_skill_flags(capsys):
    """Control: ``--proposition`` still parses with the same parser."""
    import argparse

    from self_learn.overseer import cli as overseer_cli

    parser = argparse.ArgumentParser()
    overseer_cli.add_parser(parser.add_subparsers(dest="verb", required=True))
    args = parser.parse_args(["overseer", "respond", "--proposition", "q-a", "--text", "t"])
    assert args.proposition == "q-a"
    for flag in ("--veto-skill", "--retire-skill"):
        with pytest.raises(SystemExit):
            parser.parse_args(["overseer", "respond", flag, NAME, "--text", "t"])
    capsys.readouterr()


# ============================ 2-4. an agent's veto runs under the standing grant


def test_2_an_agent_s_veto_under_the_grant_bans_the_name(env, monkeypatch, capsys):
    stmt = _grant(env)
    _agent(monkeypatch)
    capsys.readouterr()

    code = cli.main(["skill", "veto", "foo-bar", "--note", "the user said never use foo-bar"])

    assert code == 0, capsys.readouterr().err
    entry = skill_registry.load(env.home).veto_of("foo-bar")
    assert entry is not None and entry["by"] == "agent" and entry["grant"] == stmt
    body = git(env.home, "log", "-1", "--format=%B").stdout
    assert "the user said never use foo-bar" in body
    assert body.strip().rpartition("\n\n")[2].splitlines() == ["By: agent", f"Grant: {stmt}"]
    assert "By: human" not in body
    # every later write of the name is refused, naming the veto
    checked = skill_writer.check(env.home, "foo-bar", draft("foo-bar"))
    assert not checked.ok and "name-vetoed" in _rules(checked.problems)


def test_3_an_agent_s_veto_without_the_grant_or_a_reason_records_nothing(env, monkeypatch, capsys):
    """Positive control: test 2, the same command under a grant, records."""
    _agent(monkeypatch)
    before = (env.head(env.home), env.status(env.home))
    capsys.readouterr()
    assert cli.main(["skill", "veto", "foo-bar"]) == 64
    assert "person-only" in capsys.readouterr().err
    assert cli.main(["skill", "veto", "foo-bar", "--note", "asked"]) == 1
    assert "no standing grant" in capsys.readouterr().err
    assert (env.head(env.home), env.status(env.home)) == before
    assert skill_registry.load(env.home).veto_of("foo-bar") is None


def test_4_a_person_s_veto_is_the_person_s_and_carries_no_grant(env, capsys):
    capsys.readouterr()
    assert cli.main(["skill", "veto", "foo-bar"]) == 0
    entry = skill_registry.load(env.home).veto_of("foo-bar")
    assert entry == {"name": "foo-bar", "at": entry["at"], "by": "human"}
    assert git(env.home, "log", "-1", "--format=%s").stdout.strip() == "self-learn: skill veto foo-bar"
    assert git(env.home, "log", "-1", "--format=%b").stdout.strip() == "By: human"


# ===================================================== 5. any name may be vetoed


def test_5_a_name_nothing_uses_is_banned_for_any_future_skill(env, capsys):
    capsys.readouterr()
    assert cli.main(["skill", "veto", UNUSED]) == 0
    out = capsys.readouterr().out
    assert f"{UNUSED} is vetoed for ever" in out and "banned for any future skill" in out
    assert UNUSED in skill_registry.load(env.home).vetoed_names()


def test_5_a_persons_own_skill_is_said_to_be_theirs_not_unused(env, capsys):
    """Gate r1 NIT: a skill a person made that self-learn does not own is
    vetoed and said to be theirs, never "not a name any skill uses"."""
    env.personal_skill("my-own-skill")
    capsys.readouterr()
    assert cli.main(["skill", "veto", "my-own-skill"]) == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "a skill on this machine that self-learn does not own" in out
    assert "not a name any skill uses" not in out
    assert "my-own-skill" in skill_registry.load(env.home).vetoed_names()


@pytest.mark.parametrize("kind", ["owned", "draft", "build-disposition", "retired"])
def test_5_each_kind_of_name_is_vetoed_and_said_what_it_is(env, capsys, kind):
    """The three names S-107's presentation anchor refused (a build
    disposition never drafted, a draft of an unseen week, a skill a person
    made with no case) are vetoable, and so is a retired skill's name."""
    name = {"owned": NAME, "draft": "drafted-one", "build-disposition": "decided-one",
            "retired": NAME}[kind]
    if kind in ("owned", "retired"):
        assert env.write(case=None, by="human").ok  # a person made it, with no case
    if kind == "retired":
        assert skill_writer.retire(env.home, NAME, case=None, by="human", no_push=True).ok
    if kind == "draft":
        folder = env.home / "overseer" / "skills" / "2026-01-04" / "drafts" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    if kind == "build-disposition":
        (env.home / "overseer" / "skills").mkdir(parents=True, exist_ok=True)
        (env.home / "overseer" / "skills" / "2026-01-04.yaml").write_text(
            "version: 1\nweek: '2026-01-04'\nruns:\n- run: r1\n  dispositions:\n"
            f"  - {{source: candidate, id: c1, disposition: build, skill: {name}, because: x}}\n",
            encoding="utf-8",
        )
    capsys.readouterr()
    assert cli.main(["skill", "veto", name]) == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    expected = {
        "owned": "live skill self-learn owns: the next overseer run that writes skills renames it",
        "draft": "drafted or decided to build",
        "build-disposition": "drafted or decided to build",
        "retired": "self-learn retired",
    }[kind]
    assert expected in out
    assert name in skill_registry.load(env.home).vetoed_names()


def test_a_veto_of_a_name_that_is_not_kebab_case_is_refused(env, capsys):
    before = env.head(env.home)
    assert cli.main(["skill", "veto", "Not_A_Name"]) == 1
    assert "is not a skill name" in capsys.readouterr().err
    assert env.head(env.home) == before


def test_a_second_veto_of_the_same_name_changes_nothing(env, capsys):
    assert cli.main(["skill", "veto", "foo-bar"]) == 0
    head = env.head(env.home)
    capsys.readouterr()
    assert cli.main(["skill", "veto", "foo-bar"]) == 0
    assert "already vetoed" in capsys.readouterr().out
    assert env.head(env.home) == head


# ==================================================== 6. veto and rename at once


def test_6_veto_with_rename_to_renames_at_once_as_the_person_with_no_case(env, capsys):
    assert env.write().ok
    capsys.readouterr()
    assert cli.main(["skill", "veto", NAME, "--rename-to", NEW, "--no-push"]) == 0
    out = capsys.readouterr().out
    assert f"{NAME} is now {NEW}" in out
    registry = skill_registry.load(env.home)
    assert NAME in registry.vetoed_names()
    row = registry.row(NEW)
    assert row is not None and row["status"] == "live" and row["renamed_from"] == [NAME]
    assert row["last_write"]["case"] is None and row["last_write"]["by"] == "human"
    assert registry.row(NAME) is None
    assert skill_requests.pending_renames(env.home) == []


def test_6_a_refused_rename_leaves_the_veto_for_the_overseer(env, capsys):
    assert env.write().ok
    env.personal_skill(NEW)  # the new name is taken on this machine
    capsys.readouterr()
    code = cli.main(["skill", "veto", NAME, "--rename-to", NEW, "--no-push"])
    assert code == 1
    err = capsys.readouterr().err
    assert "the veto stands" in err and "renames it" in err
    assert [r["name"] for r in skill_requests.pending_renames(env.home)] == [NAME]


# ====================================================== 7. retire is a request


def test_7_a_person_s_retire_of_a_skill_with_lessons_is_a_request(env, capsys):
    assert env.write().ok
    _route(env, RID_A)
    _route(env, RID_B)
    assert skill_writer.routed_lessons(env.home, NAME) == [RID_A, RID_B]  # control
    capsys.readouterr()

    code = cli.main(["skill", "retire", NAME, "--no-push"])

    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "requested: the next overseer run that writes skills moves its 2 lesson(s) out" in out
    row = skill_registry.load(env.home).row(NAME)
    assert row["status"] == "live"
    assert row["retire_requested"]["by"] == "human" and "grant" not in row["retire_requested"]
    assert "statement" not in row["retire_requested"]
    (pending,) = skill_requests.pending_retire_requests(env.home)
    assert pending["name"] == NAME and pending["by"] == "human"


def test_7_a_person_s_retire_of_a_skill_with_no_lessons_retires_it(env, capsys):
    assert env.write().ok
    capsys.readouterr()
    assert cli.main(["skill", "retire", NAME, "--no-push"]) == 0
    row = skill_registry.load(env.home).row(NAME)
    assert row["status"] == "retired" and row["retired"]["case"] is None
    assert row["retired"]["by"] == "human"


def test_7_a_request_is_gone_once_the_skill_is_retired(env):
    assert env.write().ok
    assert skill_requests.request_retire(env.home, NAME, by="human").ok
    assert "retire_requested" in skill_registry.load(env.home).row(NAME)  # control
    assert skill_writer.retire(env.home, NAME, case=CASE, by="overseer", no_push=True).ok
    row = skill_registry.load(env.home).row(NAME)
    assert row["status"] == "retired" and "retire_requested" not in row
    assert skill_requests.pending_retire_requests(env.home) == []


def test_7_an_agent_s_retire_request_under_the_grant_is_the_agent_s(env, monkeypatch, capsys):
    assert env.write().ok
    _route(env, RID_A)
    stmt = _grant(env)
    _agent(monkeypatch)
    capsys.readouterr()
    code = cli.main(["skill", "retire", NAME, "--no-push", "--note", "the user wants it gone"])
    assert code == 0, capsys.readouterr().err
    request = skill_registry.load(env.home).row(NAME)["retire_requested"]
    assert request["by"] == "agent" and request["grant"] == stmt


def test_a_retire_request_for_a_skill_self_learn_does_not_own_is_refused(env):
    result = skill_requests.request_retire(env.home, "nobody-s-skill", by="human")
    assert not result.ok and "not a live skill self-learn owns" in result.problems[0]


# ============================================== 9. a person's write needs no case


def test_9_a_person_s_write_without_a_case_stamps_case_null(env, tmp_path, capsys):
    src = tmp_path / "draft"
    for rel, text in draft().items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="utf-8")
    capsys.readouterr()

    code = cli.main(["skill", "write", NAME, "--from", str(src), "--no-push"])

    assert code == 0, capsys.readouterr().err
    row = skill_registry.load(env.home).row(NAME)
    assert row["created"]["case"] is None and row["created"]["by"] == "human"
    assert row["last_write"]["case"] is None
    text = env.skill_md().read_text(encoding="utf-8")
    assert "    case: null\n" in text
    stamp = _read_frontmatter(text).mapping["metadata"]["self-learn"]
    assert stamp["case"] is None  # YAML's null, not the string "None"
    subject = git(env.root, "log", "-1", "--format=%s").stdout.strip()
    assert subject == f"self-learn: skill write {NAME} (no case)"


def test_an_overseer_step_with_no_case_is_refused(env):
    before = env.snapshot()
    result = env.write(case=None, by="overseer")
    assert not result.ok and result.kind == "bad-line"
    assert "a step with no case is a person's" in result.problems[0]
    assert env.snapshot() == before


# =========================================== 10. no case hears about a request


def test_10_no_case_gains_an_observation_from_a_skill_request(env, tmp_path):
    created = _case(env.home, tmp_path, "000000c1", {})
    assert env.write(case=created).ok
    _route(env, RID_A)
    before = {
        str(row["case"]): _observations(env.home, str(row["case"]))
        for row in cases.list_cases(env.home, only_ok=True)
    }

    vetoed = skill_requests.veto(env.home, NAME, by="human")
    requested = skill_requests.request_retire(env.home, NAME, by="human")

    # Positive control: both requests are on the skill's own record.
    assert vetoed.ok and vetoed.added and requested.ok and requested.added
    registry = skill_registry.load(env.home)
    assert registry.veto_of(NAME) is not None and "retire_requested" in registry.row(NAME)
    after = {
        str(row["case"]): _observations(env.home, str(row["case"]))
        for row in cases.list_cases(env.home, only_ok=True)
    }
    assert after == before and created in after


# ======================================= 11. the overseer stages from the registry


def test_11_vetoes_yaml_is_staged_from_the_registry_alone(env, tmp_path):
    assert env.write().ok
    assert env.write(draft("other-skill"), name="other-skill").ok
    assert skill_requests.veto(env.home, NAME, by="human").ok
    assert skill_requests.request_retire(env.home, "other-skill", by="human").ok
    stage = tmp_path / "stage"
    stage.mkdir()

    def write(_stage, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    staged = skills_mod.StagedSkills()
    skills_mod._stage_vetoes(  # noqa: SLF001
        env.home, stage, skill_registry.load(env.home), staged, write
    )

    from ruamel.yaml import YAML

    data = YAML(typ="safe").load((stage / skills_mod.VETOES_FILE).read_text(encoding="utf-8"))
    assert [v["name"] for v in data["vetoed"]] == [NAME]
    assert [r["name"] for r in data["renames_owed"]] == [NAME]
    assert [r["name"] for r in data["retire_requests"]] == ["other-skill"]
    assert data["retire_requests"][0]["by"] == "human"
    assert staged.notes == []
