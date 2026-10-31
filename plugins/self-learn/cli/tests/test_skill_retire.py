"""SK1 -- ``skill retire``: self-learn removes a skill it owns
(``skill_writer.retire``, ``self-learn skill retire``; skill-writing plan
§2 step 8, §4.1 row SK1 test (g), plus the interrupted-retire half of (h)).

The scratch environment is ``test_skill_write``'s (a ledger, a skills root
with a marketplace, a scratch ``~/.claude``). Red on master:
``self_learn.skill_writer`` does not exist there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import cli, gitops, skill_registry, skill_writer, verbs
from self_learn.ledger_ops import create_record
from support import git, make_behavior
from test_skill_write import CASE, CASE2, NAME, RID, RID2, Env, draft

CASE3 = "case-9c0d1e2f"


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


def _route_in(env: Env, rid: str = RID) -> None:
    create_record(env.home, make_behavior(scope="skill:s", record_id=rid))
    verbs.route(env.home, rid, dest=f"new-skill:{NAME}", no_push=True)


def test_retire_refuses_while_a_lesson_routes_there_then_passes_once_none_does(env):
    assert env.write().ok
    _route_in(env)
    assert f"*({RID})*" in env.skill_md().read_text(encoding="utf-8")  # control
    before = env.snapshot()

    refused = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)

    assert not refused.ok and refused.kind == "needs-person"
    assert refused.routed == (RID,)
    assert any(RID in p for p in refused.problems)
    assert env.snapshot() == before
    assert env.skill_md().is_file() and env.link().is_symlink()
    assert env.row()["status"] == "live"

    # the lesson leaves (replaced by a newer one routed elsewhere)
    create_record(env.home, make_behavior(scope="skill:s", record_id=RID2))
    verbs.supersede(env.home, RID, RID2, no_push=True)
    assert skill_writer.routed_lessons(env.home, NAME) == []
    root_count, ledger_count = env.count(env.root), env.count(env.home)

    retired = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)

    assert retired.ok, retired.problems
    assert retired.host_sha and retired.ledger_sha and retired.unlinked
    # folder, marketplace entry and link gone, in ONE skills-root commit
    assert env.count(env.root) == root_count + 1
    assert env.count(env.home) == ledger_count + 1
    assert not env.plugin_dir().exists()
    assert not env.link().exists() and not env.link().is_symlink()
    names = [p["name"] for p in json.loads(env.marketplace.read_text())["plugins"]]
    assert NAME not in names and "s-plugin" in names
    assert env.marketplace.read_text(encoding="utf-8") == env.marketplace_seed
    changed = git(env.root, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert ".claude-plugin/marketplace.json" in changed
    assert f"plugins/{NAME}/skills/{NAME}/SKILL.md" in changed
    assert f"plugins/{NAME}/.claude-plugin/plugin.json" in changed
    assert git(env.root, "log", "-1", "--format=%s").stdout.strip() == (
        f"self-learn: skill retire {NAME} ({CASE2})"
    )
    assert env.status(env.root) == "" and env.status(env.home) == ""
    row = env.row()
    assert row["status"] == "retired"
    assert row["retired"]["case"] == CASE2 and row["retired"]["by"] == "overseer"
    # both commits carry the trailer (gate r1 MINOR 3)
    assert "By: overseer" in git(env.home, "log", "-1", "--format=%b").stdout
    assert "By: overseer" in git(env.root, "log", "-1", "--format=%b").stdout


def test_retiring_a_retired_skill_is_a_no_op(env):
    assert env.write().ok
    assert skill_writer.retire(env.home, NAME, case=CASE2, by="human", no_push=True).ok
    before = env.snapshot()
    again = skill_writer.retire(env.home, NAME, case=CASE3, by="human", no_push=True)
    assert again.ok and not again.changed
    assert env.snapshot() == before


def test_a_skill_self_learn_does_not_own_is_not_retired(env):
    """A person's ``new-skill`` scaffold is not in the registry: retire
    leaves it alone."""
    create_record(env.home, make_behavior(scope="skill:s", record_id=RID))
    verbs.route(env.home, RID, dest="new-skill:scaffolded", no_push=True)
    assert env.skill_md("scaffolded").is_file()  # control: the skill exists
    before = env.snapshot()
    result = skill_writer.retire(env.home, "scaffolded", case=CASE2, by="overseer", no_push=True)
    assert not result.ok and result.kind == "needs-person"
    assert "not a skill self-learn owns" in result.problems[0]
    assert env.snapshot() == before


def test_an_uncommitted_change_in_the_plugin_folder_refuses_target_busy(env):
    assert env.write().ok
    (env.skill_dir() / "notes.md").write_text("a person's scratch\n", encoding="utf-8")
    result = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)
    assert not result.ok and result.kind == "target-busy"
    assert (env.skill_dir() / "notes.md").is_file() and env.link().is_symlink()
    assert env.row()["status"] == "live"


def test_a_link_that_is_not_self_learn_s_is_left_alone(env):
    assert env.write().ok
    env.link().unlink()
    other = env.tmp / "elsewhere"
    other.mkdir()
    (other / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")
    env.link().symlink_to(other)
    result = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)
    assert result.ok and not result.unlinked
    assert env.link().resolve() == other.resolve()
    assert not env.plugin_dir().exists()


class _Crash(BaseException):
    pass


def test_an_interrupted_retire_never_leaves_a_link_to_a_missing_folder(env, monkeypatch):
    assert env.write().ok
    real = skill_writer._remove_plugin

    def crash(*_args, **_kwargs):
        raise _Crash()

    monkeypatch.setattr(skill_writer, "_remove_plugin", crash)
    with pytest.raises(_Crash):
        skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)
    # the link went first; the folder and the row are still there
    assert not env.link().exists() and not env.link().is_symlink()
    assert env.skill_md().is_file() and env.row()["status"] == "live"

    monkeypatch.setattr(skill_writer, "_remove_plugin", real)
    rerun = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)
    assert rerun.ok, rerun.problems
    assert not env.plugin_dir().exists() and env.row()["status"] == "retired"


def test_a_failed_removal_commit_puts_everything_back(env, monkeypatch):
    assert env.write().ok
    real_commit = gitops.commit

    def refuse_on_root(repo, message, body=None, paths=None):
        if repo.resolve() == env.root.resolve():
            raise gitops.GitOpsError("simulated: a pre-commit hook said no")
        return real_commit(repo, message, body=body, paths=paths)

    monkeypatch.setattr(gitops, "commit", refuse_on_root)
    before = env.snapshot()
    result = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)
    assert not result.ok and result.kind == "git"
    assert env.snapshot() == before
    assert env.link().resolve() == env.skill_dir().resolve()
    assert env.row()["status"] == "live"


def test_a_failed_registry_commit_after_the_removal_still_pushes_the_removal(env, monkeypatch):
    """Gate r1 NIT 5: the skills-root removal is committed before the row.
    When the row's commit then fails, the result carries the removal commit
    so it is pushed, and a rerun marks the row."""
    assert env.write().ok
    pushes: list[Path] = []
    monkeypatch.setattr(
        gitops, "push_if_remote", lambda repo, **_kw: pushes.append(Path(repo).resolve())
    )
    real_update = skill_registry.with_update

    def refuse(*_args, **_kwargs):
        raise gitops.GitOpsError("simulated: the ledger commit failed")

    monkeypatch.setattr(skill_registry, "with_update", refuse)
    result = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer")

    assert not result.ok and result.kind == "git"
    assert result.host_sha == env.head(env.root)
    assert not env.plugin_dir().exists() and env.row()["status"] == "live"
    assert pushes == [env.root.resolve()]

    monkeypatch.setattr(skill_registry, "with_update", real_update)
    rerun = skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True)
    assert rerun.ok, rerun.problems
    assert rerun.ledger_sha and rerun.host_sha is None
    assert env.row()["status"] == "retired"


def test_a_retired_name_can_be_written_again(env):
    assert env.write().ok
    assert skill_writer.retire(env.home, NAME, case=CASE2, by="overseer", no_push=True).ok
    again = env.write(case=CASE3)
    assert again.ok, again.problems
    assert env.row()["status"] == "live" and env.row()["created"]["case"] == CASE3
    assert env.link().resolve() == env.skill_dir().resolve()


def test_cli_retire_as_the_person(env, capsys):
    assert env.write().ok
    code = cli.main(["skill", "retire", NAME, "--case", CASE2, "--no-push"])
    assert code == 0, capsys.readouterr().err
    assert env.row()["retired"]["by"] == "human"
    assert not env.plugin_dir().exists()


def test_cli_retire_names_the_lessons_that_block_it(env, capsys):
    assert env.write().ok
    _route_in(env)
    capsys.readouterr()
    assert cli.main(["skill", "retire", NAME, "--case", CASE2, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["routed"] == [RID]
    assert env.skill_md().is_file()


def test_the_draft_helper_is_shared(env):
    """``draft`` is imported from test_skill_write; a guard that this file
    builds on the same valid draft as that one."""
    assert set(draft()) == {"SKILL.md", "references/buttons.md"} and CASE != CASE2
