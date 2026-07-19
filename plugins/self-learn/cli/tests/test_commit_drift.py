"""U20 — F5-5 guided commit-first: ``self-learn host commit-drift`` (08 §1
Commit-drift-verb pin; f5-round-spec.md §2.1).

The dirty-target refusal stays fully intact — this verb is the GUIDED
path a human takes instead of it: commit the TARGET repo's OWN pending
changes (their commit, separate from ours), so the caller can retry its
route. Dirty-vs-drift boundary (gate M2) is the load-bearing distinction:
DRIFT (chezmoi.py's pre-existing-drift leg) is refused with a plain
explanation and NEVER committed; only DIRTY (uncommitted changes) is
served.

All git activity happens in sandbox repos under pytest tmpdirs; chezmoi
is a PATH shim extended (beyond test_verbs.py's read-only shim) to also
simulate ``add -A`` / ``commit`` / ``rev-parse HEAD`` / ``source-path``,
since this verb — unlike ``route``'s user-scope leg, which only ever
PREFLIGHTS — actually performs the chezmoi-side write.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from self_learn import cli, verbs
from self_learn.chezmoi import CHEZMOI_DIRTY_MARKER
from self_learn.ledger_ops import create_record, write_proposal
from support import commit_all, git, init_repo, make_behavior, make_env, proposal_dict

RID = "lrn-0000cafe"

CHEZMOI_SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CHEZMOI_SHIM_LOG"
case "$1" in
  diff)
    printf '%s' "${CHEZMOI_SHIM_DIFF-}"
    ;;
  source-path)
    printf '%s' "${CHEZMOI_SHIM_SOURCE-/tmp/fake-dotfiles}"
    ;;
  git)
    case "$3" in
      status) printf '%s' "${CHEZMOI_SHIM_STATUS-}" ;;
      rev-parse) printf '%s' "${CHEZMOI_SHIM_SHA-cafe1234cafe1234cafe1234cafe1234cafe123}" ;;
    esac
    ;;
esac
exit "${CHEZMOI_SHIM_EXIT-0}"
"""


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def chezmoi_shim(tmp_path, monkeypatch):
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    fake = bindir / "chezmoi"
    fake.write_text(CHEZMOI_SHIM, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "chezmoi-argv.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CHEZMOI_SHIM_LOG", str(log))
    monkeypatch.delenv("CHEZMOI_SHIM_DIFF", raising=False)
    monkeypatch.delenv("CHEZMOI_SHIM_STATUS", raising=False)

    def calls():
        return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]

    return calls


class Env:
    def __init__(self, tmp_path):
        sandbox = make_env(tmp_path)
        self.home = sandbox.ledger
        self.host = sandbox.host
        self.skill_dir = sandbox.skill_dir
        self.skill_md = sandbox.skill_md
        self.bucket = self.home / "skills" / "s"

    def pending(self, rid):
        return self.bucket / "pending" / f"{rid}.md"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def seed(env, rid=RID, scope="skill:s", dest="skill-md"):
    record = make_behavior(scope=scope, record_id=rid)
    create_record(env.home, record)
    write_proposal(env.home, rid, proposal_dict(destination=dest))
    return record


# --------------------------------------------------------------- gitops leg


class TestGitopsLeg:
    def test_dirty_target_committed_scoped_unrelated_file_excluded(self, env):
        """gate m8: an unrelated dirty file in the SAME repo must NOT ride
        the pinned-subject commit — the add is target-path scoped, never
        ``-A``."""
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        unrelated = env.host / "README.md"
        unrelated.write_text("unrelated pending work\n", encoding="utf-8")

        result = verbs.commit_drift(env.home, RID)

        assert result.commit_sha is not None
        assert not result.dry_run
        assert result.repo == env.host
        assert str(env.skill_md.relative_to(env.host)) in "\n".join(result.files) or any(
            env.skill_md.name in f for f in result.files
        )
        committed = git(
            env.host, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.split()
        assert "plugins/s-plugin/skills/s/SKILL.md" in committed
        assert "README.md" not in committed  # unrelated dirty file excluded
        subject = git(env.host, "log", "-1", "--format=%s").stdout.strip()
        assert subject == verbs.COMMIT_DRIFT_SUBJECT
        # README.md is STILL dirty/untracked afterward — untouched
        status = git(env.host, "status", "--porcelain").stdout
        assert "README.md" in status

    def test_clean_repo_refused_no_commit(self, env):
        seed(env)
        before = git(env.host, "rev-parse", "HEAD").stdout.strip()

        with pytest.raises(verbs.VerbError, match="nothing to commit"):
            verbs.commit_drift(env.home, RID)

        assert git(env.host, "rev-parse", "HEAD").stdout.strip() == before

    def test_out_of_scope_path_refused(self, env, tmp_path):
        """A project bucket whose recorded host was never registered — the
        SAME resolution route's own failure would hit refuses too (no
        arbitrary-repo commit surface)."""
        proj = tmp_path / "unregistered-project"
        init_repo(proj)
        (proj / "README.md").write_text("x\n", encoding="utf-8")
        commit_all(proj, "seed")
        record = make_behavior(scope="project", record_id=RID)
        create_record(env.home, record, project_path=proj)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))

        with pytest.raises(verbs.VerbError, match="not registered"):
            verbs.commit_drift(env.home, RID)

    def test_dry_run_lists_files_writes_nothing(self, env):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        before = git(env.host, "rev-parse", "HEAD").stdout.strip()

        result = verbs.commit_drift(env.home, RID, dry_run=True)

        assert result.dry_run
        assert result.commit_sha is None
        assert any("SKILL.md" in f for f in result.files)
        assert git(env.host, "rev-parse", "HEAD").stdout.strip() == before
        status = git(env.host, "status", "--porcelain").stdout
        assert "SKILL.md" in status  # still dirty — nothing written

    def test_hook_destination_refused(self, env):
        seed(env, dest="skill-md")  # base seed unused; overwritten below
        write_proposal(env.home, RID, proposal_dict(destination="skill-md"))
        with pytest.raises(verbs.VerbError, match="commit-drift"):
            verbs.commit_drift(env.home, RID, dest="hook")


# -------------------------------------------------------------- chezmoi leg


class TestChezmoiLeg:
    def test_dirty_dotfiles_goes_through_chezmoi_git(
        self, env, chezmoi_shim, tmp_path, monkeypatch
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))
        monkeypatch.setenv("CHEZMOI_SHIM_STATUS", " M dot_zshrc\n")

        result = verbs.commit_drift(env.home, RID, user_claude_md=target)

        assert result.commit_sha == "cafe1234cafe1234cafe1234cafe1234cafe123"
        assert result.files == ["dot_zshrc"]
        calls = chezmoi_shim()
        assert "git -- add -A" in calls
        assert f"git -- commit -m {verbs.COMMIT_DRIFT_SUBJECT}" in calls

    def test_drift_refused_no_commit(self, env, chezmoi_shim, tmp_path, monkeypatch):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))
        monkeypatch.setenv("CHEZMOI_SHIM_DIFF", "--- a/CLAUDE.md\n+++ b/CLAUDE.md\n")

        with pytest.raises(verbs.VerbError, match="a commit can't fix drift"):
            verbs.commit_drift(env.home, RID, user_claude_md=target)

        calls = chezmoi_shim()
        assert not any(c.startswith("git -- add") for c in calls)
        assert not any(c.startswith("git -- commit") for c in calls)

    def test_clean_dotfiles_refused(self, env, chezmoi_shim, tmp_path):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))

        with pytest.raises(verbs.VerbError, match="nothing to commit"):
            verbs.commit_drift(env.home, RID, user_claude_md=target)

    def test_dry_run_reports_repo_and_files_writes_nothing(
        self, env, chezmoi_shim, tmp_path, monkeypatch
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))
        monkeypatch.setenv("CHEZMOI_SHIM_STATUS", " M dot_zshrc\n")
        dotfiles_dir = tmp_path / "the-dotfiles-repo"
        monkeypatch.setenv("CHEZMOI_SHIM_SOURCE", str(dotfiles_dir))

        result = verbs.commit_drift(env.home, RID, user_claude_md=target, dry_run=True)

        assert result.dry_run and result.commit_sha is None
        assert result.files == ["dot_zshrc"]
        assert str(result.repo) == str(dotfiles_dir)
        calls = chezmoi_shim()
        assert not any(c.startswith("git -- add") for c in calls)
        assert not any(c.startswith("git -- commit") for c in calls)


# ------------------------------------------------------------- markers/gate


class TestMarkersLoadBearing:
    def test_gitops_dirty_message_carries_the_extracted_marker(self, env):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        with pytest.raises(verbs.DirtyTargetError) as excinfo:
            verbs.route(env.home, RID, dest="skill-md")
        assert verbs.GITOPS_DIRTY_MARKER in str(excinfo.value)

    def test_chezmoi_dirty_message_carries_the_extracted_marker(
        self, env, chezmoi_shim, tmp_path, monkeypatch
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        monkeypatch.setenv("CHEZMOI_SHIM_STATUS", " M dot_zshrc\n")
        from self_learn.chezmoi import ChezmoiAbort

        with pytest.raises(ChezmoiAbort) as excinfo:
            verbs.route(env.home, RID, dest="claude-md", user_claude_md=target)
        assert CHEZMOI_DIRTY_MARKER in str(excinfo.value)


# -------------------------------------------------------------------- CLI


class TestCliDispatch:
    def test_commit_drift_success_exit_0(self, env, monkeypatch):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rc = cli.main(["host", "commit-drift", RID])
        assert rc == 0

    def test_commit_drift_clean_exit_64(self, env, monkeypatch, capsys):
        seed(env)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rc = cli.main(["host", "commit-drift", RID])
        assert rc == cli.EXIT_USAGE
        assert rc == 64
        assert "nothing to commit" in capsys.readouterr().err

    def test_commit_drift_dry_run_json(self, env, monkeypatch, capsys):
        seed(env)
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8") + "\nuncommitted edit\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))
        rc = cli.main(["host", "commit-drift", RID, "--dry-run", "--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["repo"] == str(env.host)
        assert any("SKILL.md" in f for f in out["files"])
        # nothing committed
        assert git(
            env.host, "status", "--porcelain"
        ).stdout.strip() != ""

    def test_commit_drift_drift_exit_64(
        self, env, chezmoi_shim, tmp_path, monkeypatch
    ):
        target = tmp_path / "dot-claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text("# user conduct\n", encoding="utf-8")
        record = make_behavior(scope="user", record_id=RID)
        create_record(env.home, record)
        write_proposal(env.home, RID, proposal_dict(destination="claude-md"))
        monkeypatch.setenv("CHEZMOI_SHIM_DIFF", "--- a/CLAUDE.md\n+++ b/CLAUDE.md\n")
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.home))

        import self_learn.verbs as verbs_mod

        monkeypatch.setattr(verbs_mod, "DEFAULT_USER_CLAUDE_MD", target)
        rc = cli.main(["host", "commit-drift", RID])
        assert rc == 64
