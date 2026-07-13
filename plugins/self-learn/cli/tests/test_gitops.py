"""T7 gitops: targeted staging, pinned commits, per-verb push with the
pinned rebase-retry (08 §1 Push pin; §5 playbooks). All git activity runs
in sandbox repos under tmpdirs with `git init --bare` remotes."""

import subprocess
from pathlib import Path

import pytest

from self_learn import gitops
from support import commit_all, git, init_repo


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    init_repo(r)
    (r / "seed.md").write_text("seed\n", encoding="utf-8")
    commit_all(r, "seed")
    return r


@pytest.fixture
def remote(tmp_path, repo):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
    )
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


def clone(tmp_path, remote, name="clone2") -> Path:
    c = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(remote), str(c)], check=True)
    git(c, "config", "user.email", "other@example.com")
    git(c, "config", "user.name", "Other")
    return c


def local_subject(repo) -> str:
    return git(repo, "log", "-1", "--format=%s").stdout.strip()


class TestStage:
    def test_stages_only_named_existing_paths(self, repo):
        a = repo / "a.md"
        a.write_text("a\n", encoding="utf-8")
        (repo / "unrelated.md").write_text("dirty\n", encoding="utf-8")
        gone = repo / "never-existed.md"

        staged = gitops.stage(repo, [a, gone])
        assert staged == [a]
        out = git(repo, "diff", "--cached", "--name-only").stdout.split()
        assert out == ["a.md"]  # the unrelated dirty file was NOT swept

    def test_empty_after_filtering_is_a_noop(self, repo):
        assert gitops.stage(repo, [repo / "ghost.md"]) == []


class TestCommit:
    def test_message_and_note_body(self, repo):
        (repo / "a.md").write_text("a\n", encoding="utf-8")
        gitops.stage(repo, [repo / "a.md"])
        sha = gitops.commit(repo, "self-learn: reject lrn-00000001", body="my why")

        assert git(repo, "rev-parse", "HEAD").stdout.strip() == sha
        body = git(repo, "log", "-1", "--format=%B").stdout
        assert body.rstrip("\n") == "self-learn: reject lrn-00000001\n\nmy why"

    def test_no_body_when_note_absent(self, repo):
        (repo / "a.md").write_text("a\n", encoding="utf-8")
        gitops.stage(repo, [repo / "a.md"])
        gitops.commit(repo, "self-learn: reject lrn-00000001")
        assert (
            git(repo, "log", "-1", "--format=%B").stdout.rstrip("\n")
            == "self-learn: reject lrn-00000001"
        )


class TestPathsDirty:
    def test_clean_tracked_file(self, repo):
        assert not gitops.paths_dirty(repo, repo / "seed.md")

    def test_modified_tracked_file(self, repo):
        (repo / "seed.md").write_text("changed\n", encoding="utf-8")
        assert gitops.paths_dirty(repo, repo / "seed.md")

    def test_untracked_file_counts_as_dirty(self, repo):
        (repo / "new.md").write_text("x\n", encoding="utf-8")
        assert gitops.paths_dirty(repo, repo / "new.md")


def commit_change(repo, name, text, message):
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "--", name)
    git(repo, "commit", "-q", "-m", message)


class TestPush:
    def test_fast_forward_push(self, repo, remote):
        commit_change(repo, "a.md", "a\n", "local work")
        result = gitops.push_with_retry(repo)
        assert result.ok and not result.retried
        assert result.exit_code == 0
        assert git(remote, "log", "-1", "--format=%s").stdout.strip() == "local work"

    def test_non_ff_rebase_retry_succeeds(self, tmp_path, repo, remote):
        other = clone(tmp_path, remote)
        commit_change(other, "other.md", "o\n", "remote work")
        git(other, "push", "-q")

        commit_change(repo, "a.md", "a\n", "local work")
        result = gitops.push_with_retry(repo)

        assert result.ok and result.retried
        subjects = git(remote, "log", "--format=%s").stdout.split("\n")
        assert "local work" in subjects and "remote work" in subjects

    def test_rebase_conflict_aborts_loud_and_keeps_commit(
        self, tmp_path, repo, remote, capsys
    ):
        other = clone(tmp_path, remote)
        commit_change(other, "seed.md", "theirs\n", "remote conflicting")
        git(other, "push", "-q")

        commit_change(repo, "seed.md", "ours\n", "local conflicting")
        result = gitops.push_with_retry(repo)

        assert not result.ok
        assert result.rebase_conflict
        assert result.exit_code == gitops.EXIT_REBASE_CONFLICT
        assert "rebase conflict" in capsys.readouterr().err
        # local commit kept, no rebase left in progress
        assert local_subject(repo) == "local conflicting"
        gitdir = Path(git(repo, "rev-parse", "--git-dir").stdout.strip())
        if not gitdir.is_absolute():
            gitdir = repo / gitdir
        assert not (gitdir / "rebase-merge").exists()
        assert not (gitdir / "rebase-apply").exists()

    def test_push_failure_loud_commit_kept_distinct_exit(
        self, tmp_path, repo, remote, capsys
    ):
        git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        commit_change(repo, "a.md", "a\n", "stranded work")

        result = gitops.push_with_retry(repo)
        assert not result.ok and not result.rebase_conflict
        assert result.exit_code == gitops.EXIT_PUSH_FAILED
        assert "PUSH FAILED" in capsys.readouterr().err
        assert local_subject(repo) == "stranded work"

    def test_push_pending_later_succeeds(self, tmp_path, repo, remote):
        git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        commit_change(repo, "a.md", "a\n", "stranded work")
        assert not gitops.push_with_retry(repo).ok

        git(repo, "remote", "set-url", "origin", str(remote))
        result = gitops.push_pending(repo)
        assert result.ok
        assert git(remote, "log", "-1", "--format=%s").stdout.strip() == "stranded work"
