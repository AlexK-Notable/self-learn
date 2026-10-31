"""SK8 -- ``skill rename``: a skill self-learn owns gets a new name
(``skill_writer.rename``, ``self-learn skill rename``; skill-writing plan
D15, §4.1 row SK8).

The plan's three tests: (a) every lesson compiled into the skill before the
rename is compiled into it after (the control first: both lines are in the
skill under its old name); (b) a skill whose own ledger bucket
``skills/<old>/`` holds a record is refused by name, and the control: an
empty bucket renames; (c) the old name joins ``vetoed`` when the rename
came from a veto, and the control: without one it stays free. The rest
covers the move itself, the refusals, interrupted runs and the CLI.

The scratch environment is ``test_skill_write``'s (a ledger, a skills root
with a marketplace, a scratch ``~/.claude``). Red on master:
``self_learn.skill_writer`` does not exist there; on the SK1 branch,
``skill_writer.rename`` does not.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from self_learn import cli, gitops, intents, skill_registry, skill_writer, verbs
from self_learn.compilers import BEGIN_MARKER, END_MARKER
from self_learn.ledger_ops import create_record, find_record_path
from self_learn.records import Record
from support import commit_all, git, make_behavior
from test_skill_write import CASE2, DESCRIPTION, NAME, REF, REF_TEXT, Env, _hand_edit, _rules, draft

NEW = "pointer-care"
CASE3 = "case-9c0d1e2f"
STMT = "stmt-0000bbbb"
RID_A = "lrn-5a8e0001"
RID_B = "lrn-5a8e0002"
RID_C = "lrn-5a8e0003"
RID_HELD = "lrn-5a8e0004"


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


def _record(env: Env, rid: str) -> Record:
    return Record.from_path(find_record_path(env.home, rid))


def _route(env: Env, rid: str, *, scope: str = "skill:s", project: bool = False, name: str = NAME) -> None:
    """A person routes one fresh lesson into ``new-skill:<name>``."""
    create_record(
        env.home,
        make_behavior(scope=scope, record_id=rid, trigger=f"About to touch {rid} live."),
        project_path=env.root if project else None,
    )
    commit_all(env.home, f"seed {rid}")
    verbs.route(env.home, rid, dest=f"new-skill:{name}", no_push=True)


def _section_ids(env: Env, name: str) -> set[str]:
    """The lesson ids compiled into the managed section of *name*'s SKILL.md."""
    text = env.skill_md(name).read_text(encoding="utf-8")
    section = text[text.index(BEGIN_MARKER) : text.index(END_MARKER)]
    return set(re.findall(r"\*\((lrn-[0-9a-f]{8})\)\*", section))


def _rename(env: Env, **kwargs):
    kwargs.setdefault("case", CASE2)
    kwargs.setdefault("by", "overseer")
    kwargs.setdefault("no_push", True)
    return skill_writer.rename(env.home, NAME, NEW, **kwargs)


# ============================================ (a) every lesson moves with it


def test_a_every_lesson_compiled_before_the_rename_is_compiled_after(env):
    assert env.write().ok
    _route(env, RID_A)
    _route(env, RID_B, scope="project", project=True)
    before = _section_ids(env, NAME)
    assert before == {RID_A, RID_B}  # control: both lines are in the skill under its old name
    routings = {rid: _record(env, rid).routing for rid in before}
    ledger_count, root_count = env.count(env.home), env.count(env.root)

    result = _rename(env)

    assert result.ok, result.problems
    assert sorted(result.rerouted) == sorted(before)
    assert _section_ids(env, NEW) == before
    assert not env.plugin_dir(NAME).exists()
    # one ledger commit to begin, one per lesson, one to finish; one skills-root commit
    assert len(result.ledger_shas) == 2 + len(before)
    assert env.count(env.home) == ledger_count + 2 + len(before)
    assert env.count(env.root) == root_count + 1 and result.settle_sha is None
    for rid in before:
        record = _record(env, rid)
        routing = record.routing
        assert routing["destination"] == "new-skill" and routing["new_skill"] == NEW
        # the rest of the block is as it was: the compiler's order and who placed it
        assert routing["routed_at"] == routings[rid]["routed_at"]
        assert routing["by"] == routings[rid]["by"]
        displaced = [h for h in record.history if h.get("event") == "routing"]
        assert displaced and displaced[-1]["routing"] == routings[rid]
    assert skill_writer.routed_lessons(env.home, NEW) == sorted(before)
    assert skill_writer.routed_lessons(env.home, NAME) == []
    assert env.status(env.home) == "" and env.status(env.root) == ""

    # The compiler now builds the skill from the new name: a later route
    # into it adds its line and drops none of the moved ones.
    _route(env, RID_C, name=NEW)
    assert _section_ids(env, NEW) == before | {RID_C}


def test_the_rename_moves_the_folder_the_entry_the_link_and_the_row(env):
    assert env.write().ok
    old_md = env.skill_md().read_text(encoding="utf-8")
    old_row = env.row()
    market_before = env.marketplace.read_text(encoding="utf-8")
    assert f'"name": "{NAME}"' in market_before and env.link().is_symlink()  # control

    result = _rename(env)

    assert result.ok, result.problems
    # SKILL.md: only its name line changed; the stamp, the prose and the
    # managed section moved as they were
    new_md = env.skill_md(NEW).read_text(encoding="utf-8")
    assert f"name: {NAME}\n" in old_md
    assert new_md == old_md.replace(f"name: {NAME}\n", f"name: {NEW}\n", 1)
    assert (env.skill_dir(NEW) / REF).read_text(encoding="utf-8") == REF_TEXT
    manifest = json.loads(
        (env.plugin_dir(NEW) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest == {"name": NEW, "version": "0.1.0", "description": DESCRIPTION}
    assert not env.plugin_dir(NAME).exists()

    # the marketplace: the entry renamed where it stood, every other byte as it was
    assert env.marketplace.read_text(encoding="utf-8") == market_before.replace(
        f'"name": "{NAME}"', f'"name": "{NEW}"'
    ).replace(f'"./plugins/{NAME}"', f'"./plugins/{NEW}"')

    # the links
    assert not env.link(NAME).exists() and not env.link(NAME).is_symlink()
    assert env.link(NEW).resolve() == env.skill_dir(NEW).resolve()
    assert result.unlinked and result.link == "created"

    # the registry: the row moved, its creation kept, the old name recorded
    registry = skill_registry.load(env.home)
    assert registry.row(NAME) is None
    row = registry.row(NEW)
    assert row["status"] == "live" and row["plugin"] == f"plugins/{NEW}"
    assert row["created"] == old_row["created"] and row["renamed_from"] == [NAME]
    assert row["last_write"]["case"] == CASE2 and row["last_write"]["by"] == "overseer"
    deployed = skill_writer.deployed_authored_sha256(env.home, NEW)
    assert row["last_write"]["authored_sha256"] == deployed == result.authored_sha256
    assert NAME not in registry.vetoed_names() and not result.vetoed

    # git: the move is one commit; both trees clean
    tracked = git(env.root, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()
    assert f"plugins/{NEW}/skills/{NEW}/SKILL.md" in tracked
    assert f"plugins/{NEW}/skills/{NEW}/{REF}" in tracked
    assert not [path for path in tracked if path.startswith(f"plugins/{NAME}/")]
    assert git(env.root, "log", "-1", "--format=%s").stdout.strip() == (
        f"self-learn: skill rename {NAME} → {NEW} ({CASE2})"
    )
    assert git(env.root, "log", "-1", "--format=%b").stdout.strip() == "By: overseer"
    assert env.status(env.home) == "" and env.status(env.root) == ""

    # the skill under its new name is self-learn's to update, with no hand edit in the way
    files = skill_writer.deployed_files(env.home, NEW)
    assert files is not None
    check = skill_writer.check(env.home, NEW, skill_writer.draft_view(files))
    assert check.ok and check.updating, check.problems


# ===================================== (b) a skill whose bucket holds records


def test_b_a_skill_whose_own_bucket_holds_a_record_is_not_renamed(env):
    assert env.write().ok
    create_record(
        env.home,
        make_behavior(scope=f"skill:{NAME}", record_id=RID_HELD, trigger="About to press a side button."),
    )
    commit_all(env.home, "a lesson filed under the skill's own bucket")
    assert (env.home / "skills" / NAME / "pending" / f"{RID_HELD}.md").is_file()  # control
    before = env.snapshot()

    result = _rename(env)

    assert not result.ok and result.kind == "needs-person"
    assert f"skills/{NAME}/" in result.problems[0] and RID_HELD in result.problems[0]
    assert env.snapshot() == before
    assert env.skill_md().is_file() and env.row()["status"] == "live"
    assert skill_registry.load(env.home).row(NEW) is None


def test_b_control_a_skill_whose_bucket_is_empty_is_renamed(env):
    assert env.write().ok
    (env.home / "skills" / NAME / "pending").mkdir(parents=True)
    (env.home / "skills" / NAME / "resolved").mkdir()
    assert (env.home / "skills" / NAME).is_dir()  # the bucket is there, holding no record

    result = _rename(env)

    assert result.ok, result.problems
    assert env.skill_md(NEW).is_file() and not env.plugin_dir(NAME).exists()


def test_b_a_record_filed_under_the_new_name_refuses_too(env):
    """Records in ``skills/<new>/`` would start compiling into the renamed
    skill (a skill-scope lesson resolves to the skill of its bucket's name),
    so they are a person's to settle first."""
    assert env.write().ok
    folder = env.home / "skills" / NEW / "resolved"
    folder.mkdir(parents=True)
    make_behavior(scope=f"skill:{NEW}", record_id=RID_HELD).write(folder / f"{RID_HELD}.md")
    commit_all(env.home, "a record filed under the new name")
    before = env.snapshot()

    result = _rename(env)

    assert not result.ok and result.kind == "needs-person"
    assert f"skills/{NEW}/" in result.problems[0] and RID_HELD in result.problems[0]
    assert env.snapshot() == before


# ============================================== (c) a rename from a veto


def test_c_a_rename_that_comes_from_a_veto_bans_the_old_name(env):
    assert env.write().ok
    assert NAME not in skill_registry.load(env.home).vetoed_names()  # control

    result = _rename(env, by="human", veto_statement=STMT)

    assert result.ok and result.vetoed, result.problems
    (veto,) = [v for v in skill_registry.load(env.home).vetoed if v["name"] == NAME]
    assert veto["statement"] == STMT
    # the old name is never used again
    again = env.write(case=CASE3)
    assert not again.ok and "name-vetoed" in _rules(again.problems)


def test_c_control_a_rename_without_a_veto_leaves_the_old_name_free(env):
    assert env.write().ok
    result = _rename(env)
    assert result.ok and not result.vetoed, result.problems
    assert NAME not in skill_registry.load(env.home).vetoed_names()
    assert skill_writer.check(env.home, NAME, draft()).ok


def test_c_a_veto_recorded_before_the_rename_is_not_added_twice(env):
    """``overseer respond --veto-skill`` records the veto first (SK7); the
    rename that follows it names the same veto and adds nothing."""
    assert env.write().ok
    env.veto(NAME)  # statement stmt-0000aaaa
    result = _rename(env, veto_statement=STMT)
    assert result.ok and not result.vetoed, result.problems
    vetoes = [v for v in skill_registry.load(env.home).vetoed if v["name"] == NAME]
    assert [v["statement"] for v in vetoes] == ["stmt-0000aaaa"]


def test_a_veto_that_is_not_a_statement_id_is_refused(env):
    assert env.write().ok
    before = env.snapshot()
    result = _rename(env, veto_statement="the user said so")
    assert not result.ok and result.kind == "bad-line"
    assert env.snapshot() == before


# ======================================================== refusals


@pytest.mark.parametrize("why", ["vetoed", "loaded", "owned", "reserved", "same", "not-kebab"])
def test_a_new_name_skill_write_would_refuse_is_refused(env, why):
    assert env.write().ok
    new, rule = NEW, None
    if why == "vetoed":
        env.veto(NEW)
        rule = "name-vetoed"
    elif why == "loaded":
        env.personal_skill(NEW)
        rule = "name-collision"
    elif why == "owned":
        assert env.write(draft(NEW), name=NEW, case=CASE3).ok
        rule = "name-collision"
    elif why == "reserved":
        new, rule = "claude-care", "name-reserved-word"
    elif why == "same":
        new = NAME
    else:
        new = "Pointer_Care"
    before = env.snapshot()

    result = skill_writer.rename(env.home, NAME, new, case=CASE2, by="overseer", no_push=True)

    assert not result.ok and result.kind == "bad-line", result.problems
    if rule is not None:
        assert rule in _rules(result.problems), result.problems
    assert env.snapshot() == before
    assert env.skill_md().is_file() and env.row()["status"] == "live"


def test_a_skill_self_learn_does_not_own_is_not_renamed(env):
    """The sandbox's seeded skill ``s`` is in the skills root but has no
    registry row."""
    assert (env.root / "plugins" / "s-plugin" / "skills" / "s" / "SKILL.md").is_file()  # control
    before = env.snapshot()
    result = skill_writer.rename(env.home, "s", NEW, case=CASE2, by="overseer", no_push=True)
    assert not result.ok and result.kind == "needs-person"
    assert "not a skill self-learn owns" in result.problems[0]
    assert env.snapshot() == before


def test_a_hand_edit_refuses_without_expect_and_moves_with_the_skill_with_it(env):
    assert env.write().ok
    _hand_edit(env, "How the pieces fit together", "How the parts fit together")
    current = skill_writer.deployed_authored_sha256(env.home, NAME)
    assert current != env.row()["last_write"]["authored_sha256"]  # control: it did change
    before = env.snapshot()

    refused = _rename(env)
    assert not refused.ok and refused.kind == "target-busy"
    assert f"--expect {current}" in refused.problems[0]
    stale = _rename(env, expect_sha="0" * 64)
    assert not stale.ok and stale.kind == "target-busy"
    assert env.snapshot() == before

    moved = _rename(env, expect_sha=current)
    assert moved.ok, moved.problems
    assert "How the parts fit together" in env.skill_md(NEW).read_text(encoding="utf-8")


def test_an_uncommitted_change_in_the_plugin_folder_refuses_target_busy(env):
    assert env.write().ok
    (env.skill_dir() / "notes.md").write_text("a person's scratch\n", encoding="utf-8")
    before = env.snapshot()
    result = _rename(env)
    assert not result.ok and result.kind == "target-busy"
    assert env.snapshot() == before and (env.skill_dir() / "notes.md").is_file()


# ======================================================== interrupted runs


class _Crash(BaseException):
    """A process dying mid-rename: nothing in the writer catches it."""


@pytest.mark.parametrize(
    "where", ["before-the-move", "before-the-move-commit", "between-two-lessons"]
)
def test_an_interrupted_rename_is_finished_by_running_it_again(env, monkeypatch, where):
    assert env.write().ok
    _route(env, RID_A)
    _route(env, RID_B)
    before = _section_ids(env, NAME)
    assert before == {RID_A, RID_B}  # control
    real_move, real_commit = skill_writer._move_plugin, gitops.commit
    real_reroute = skill_writer._reroute_lesson
    if where == "before-the-move":
        def crash(*_args, **_kwargs):
            raise _Crash()

        monkeypatch.setattr(skill_writer, "_move_plugin", crash)
    elif where == "before-the-move-commit":
        def crash_on_root(repo, message, body=None, paths=None):
            if Path(repo).resolve() == env.root.resolve():
                raise _Crash()
            return real_commit(repo, message, body=body, paths=paths)

        monkeypatch.setattr(gitops, "commit", crash_on_root)
    else:
        calls: list[object] = []

        def crash_on_second(*args, **kwargs):
            if calls:
                raise _Crash()
            calls.append(args)
            return real_reroute(*args, **kwargs)

        monkeypatch.setattr(skill_writer, "_reroute_lesson", crash_on_second)

    with pytest.raises(_Crash):
        _rename(env)

    # the rename began: the new row names the old one, the old row is still live
    registry = skill_registry.load(env.home)
    assert registry.is_owned(NAME) and NAME in registry.row(NEW)["renamed_from"]
    if where == "between-two-lessons":
        assert env.skill_md(NEW).is_file() and not env.plugin_dir(NAME).exists()
        moved = [rid for rid in (RID_A, RID_B) if _record(env, rid).routing["new_skill"] == NEW]
        assert len(moved) == 1
    elif where == "before-the-move-commit":
        assert env.skill_md(NEW).is_file() and env.status(env.root) != ""  # written, not committed
    else:
        assert env.skill_md().is_file() and not env.plugin_dir(NEW).exists()
    monkeypatch.setattr(skill_writer, "_move_plugin", real_move)
    monkeypatch.setattr(gitops, "commit", real_commit)
    monkeypatch.setattr(skill_writer, "_reroute_lesson", real_reroute)

    rerun = _rename(env)

    assert rerun.ok, rerun.problems
    assert (rerun.host_sha is None) == (where == "between-two-lessons")
    assert _section_ids(env, NEW) == before
    assert not env.plugin_dir(NAME).exists()
    assert all(_record(env, rid).routing["new_skill"] == NEW for rid in before)
    registry = skill_registry.load(env.home)
    assert registry.row(NAME) is None and registry.row(NEW)["renamed_from"] == [NAME]
    assert env.link(NEW).resolve() == env.skill_dir(NEW).resolve()
    assert not env.link(NAME).is_symlink()
    assert env.status(env.home) == "" and env.status(env.root) == ""


def test_a_record_filed_in_the_old_bucket_after_a_crash_refuses_the_rerun(env, monkeypatch):
    """Gate M8 (d3e5dc6): the bucket check runs on a RESUMED rename too. A
    lesson filed under `skills/<old>/` between the crash and the rerun would
    be stranded on a folder that no longer exists, so the rerun is refused
    `needs-person` and changes nothing."""
    assert env.write().ok
    real_move = skill_writer._move_plugin

    def crash(*_args, **_kwargs):
        raise _Crash()

    monkeypatch.setattr(skill_writer, "_move_plugin", crash)
    with pytest.raises(_Crash):
        _rename(env)
    # the rename began: the new row names the old one, the old row is still live
    registry = skill_registry.load(env.home)
    assert registry.is_owned(NAME) and NAME in registry.row(NEW)["renamed_from"]
    monkeypatch.setattr(skill_writer, "_move_plugin", real_move)
    create_record(
        env.home,
        make_behavior(scope=f"skill:{NAME}", record_id=RID_HELD, trigger="About to press a side button."),
    )
    commit_all(env.home, "a lesson filed under the old bucket after the crash")
    assert (env.home / "skills" / NAME / "pending" / f"{RID_HELD}.md").is_file()  # control
    before = env.snapshot()

    refused = _rename(env)

    assert not refused.ok and refused.kind == "needs-person"
    assert f"skills/{NAME}/" in refused.problems[0] and RID_HELD in refused.problems[0]
    assert env.snapshot() == before
    assert env.skill_md().is_file() and not env.plugin_dir(NEW).exists()


def test_a_failed_move_commit_puts_the_skills_root_and_the_row_back(env, monkeypatch):
    assert env.write().ok
    real_commit = gitops.commit

    def refuse_on_root(repo, message, body=None, paths=None):
        if Path(repo).resolve() == env.root.resolve():
            raise gitops.GitOpsError("simulated: a pre-commit hook said no")
        return real_commit(repo, message, body=body, paths=paths)

    monkeypatch.setattr(gitops, "commit", refuse_on_root)
    root_head = env.head(env.root)
    md_before = env.skill_md().read_text(encoding="utf-8")

    result = _rename(env)

    assert not result.ok and result.kind == "git"
    assert env.head(env.root) == root_head and env.status(env.root) == ""
    assert env.skill_md().read_text(encoding="utf-8") == md_before
    assert not env.plugin_dir(NEW).exists()
    assert env.marketplace.read_text(encoding="utf-8") == git(
        env.root, "show", "HEAD:.claude-plugin/marketplace.json"
    ).stdout
    registry = skill_registry.load(env.home)
    assert registry.row(NEW) is None and registry.is_owned(NAME)
    assert env.link().resolve() == env.skill_dir().resolve()
    assert env.status(env.home) == ""


def test_running_a_finished_rename_again_changes_nothing(env):
    assert env.write().ok
    assert _rename(env).ok
    counts = (env.count(env.home), env.count(env.root))
    before = env.snapshot()

    again = _rename(env)

    assert again.ok and not again.changed, again
    assert (env.count(env.home), env.count(env.root)) == counts
    assert env.snapshot() == before
    assert any("already renamed" in note for note in again.notes)


# ================================================================== CLI


def test_cli_rename_as_the_person(env, capsys):
    assert env.write().ok
    capsys.readouterr()
    code = cli.main(["skill", "rename", NAME, NEW, "--case", CASE2, "--veto", STMT, "--no-push"])
    assert code == 0, capsys.readouterr().err
    registry = skill_registry.load(env.home)
    assert registry.row(NEW)["last_write"]["by"] == "human"
    assert NAME in registry.vetoed_names()
    assert git(env.root, "log", "-1", "--format=%b").stdout.strip() == "By: human"
    out = capsys.readouterr().out
    assert f"{NAME} is now {NEW}" in out and "vetoed" in out


@pytest.mark.parametrize("marker", ["CLAUDECODE", "CODEX_THREAD_ID"])
def test_cli_rename_is_refused_from_an_agent_shell(env, monkeypatch, capsys, marker):
    """The person's own run is the control: ``test_cli_rename_as_the_person``."""
    assert env.write().ok
    before = env.snapshot()
    monkeypatch.setenv(marker, "")

    def no_lock(*_a, **_k):
        pytest.fail("the agent-shell refusal must come before any lock")

    monkeypatch.setattr(intents, "ledger_write", no_lock)
    capsys.readouterr()
    assert cli.main(["skill", "rename", NAME, NEW, "--case", CASE2, "--no-push"]) == 1
    err = capsys.readouterr().err
    assert "person's command" in err and marker in err
    assert env.snapshot() == before
