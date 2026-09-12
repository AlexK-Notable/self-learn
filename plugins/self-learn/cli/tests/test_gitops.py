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


class TestCommitLockPath:
    def test_a_relative_and_an_absolute_spelling_key_identically(self, repo, monkeypatch):
        """Gate r1 NIT-1: `already_held`/`_held_locks` key off
        `str(commit_lock_path(repo))`, and `git rev-parse
        --git-common-dir` returns a path RELATIVE TO CWD (bare `.git`
        for an ordinary repo, confirmed empirically), so the unresolved
        function joined that onto whatever spelling of `repo` the
        caller passed -- a relative spelling and an absolute spelling
        of the SAME directory produced two different `Path` objects
        (one relative, one absolute), never caught by equality. Two
        differently-spelled *repo* arguments in one nesting chain must
        key identically, or an inner acquire reads as outermost."""
        monkeypatch.chdir(repo.parent)
        relative = gitops.commit_lock_path(Path(repo.name))
        absolute = gitops.commit_lock_path(repo)
        assert relative == absolute
        assert relative.is_absolute()


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

    def test_retry_push_runs_inside_the_lock(self, tmp_path, repo, remote, monkeypatch):
        """H-7 clause 2: "pull --rebase --autostash + re-push" is ONE
        span, in the repo being rebased -- gate MAJOR-6. Spies on every
        `_git` call and asserts the lock is held (`_held_locks`) at the
        moment the SECOND `push` call (the retry) runs, not just the
        pull."""
        other = clone(tmp_path, remote)
        commit_change(other, "other.md", "o\n", "remote work")
        git(other, "push", "-q")
        commit_change(repo, "a.md", "a\n", "local work")

        lock_path = str(gitops.commit_lock_path(repo))
        push_calls = []
        real_git = gitops._git

        def spy(r, *args, **kwargs):
            if args and args[0] == "push":
                push_calls.append(lock_path in gitops._held_locks)
            return real_git(r, *args, **kwargs)

        monkeypatch.setattr(gitops, "_git", spy)
        result = gitops.push_with_retry(repo)

        assert result.ok and result.retried
        # push_calls[0] is the FIRST push (unlocked, before the retry
        # branch even runs) -- push_calls[1] is the retry.
        assert push_calls == [False, True]

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


def _plant_unresolvable_stop(repo: Path, subject: str = "self-learn: test stop") -> str:
    """S-62: begin() over an UNTRACKED file too large for the inline
    cap, then mutate it -- ``_resolvable_old_bytes`` can then find no
    matching content anywhere (not on disk, not in HEAD, no inline
    copy), which guarantees a STOP on the next recovery attempt."""
    from self_learn import intents

    big = repo / "_stop_target.bin"
    big.write_bytes(b"x" * (intents._INLINE_CAP + 1))  # noqa: SLF001
    intent = intents.begin(repo, "test", [big], subject)
    big.write_bytes(b"y" * (intents._INLINE_CAP + 1))
    return intent.id


class TestPushLedgerStop:
    """S-62 (§7.2a.5(1)/(5)): the LEDGER rebase leg is the one push-path
    acquisition no prior recovery covers, so it checks for a live intent
    STOP itself — and, unlike every verb, stays exit 0 (the deliberate
    push/verb asymmetry, ruled at the 02:45 addendum: nothing corrupt
    can publish, what IS committed republishes)."""

    def test_non_ledger_rebase_is_unaffected_by_is_ledger_false(self, tmp_path, repo, remote):
        # Positive control, `is_ledger`'s OWN default: a HOST push (the
        # existing `test_non_ff_rebase_retry_succeeds` shape) behaves
        # identically whether or not the parameter is even passed.
        other = clone(tmp_path, remote)
        commit_change(other, "other.md", "o\n", "remote work")
        git(other, "push", "-q")
        commit_change(repo, "a.md", "a\n", "local work")

        result = gitops.push_with_retry(repo, is_ledger=False)
        assert result.ok and result.retried and not result.intent_stopped

    def test_ledger_rebase_succeeds_normally_with_is_ledger_true(self, tmp_path, repo, remote):
        # Positive control for the LEDGER leg itself, no intent planted:
        # `is_ledger=True` changes nothing about the ordinary path.
        other = clone(tmp_path, remote)
        commit_change(other, "other.md", "o\n", "remote work")
        git(other, "push", "-q")
        commit_change(repo, "a.md", "a\n", "local work")

        result = gitops.push_with_retry(repo, is_ledger=True)
        assert result.ok and result.retried and not result.intent_stopped

    def test_ledger_rebase_refuses_informationally_on_a_stop(
        self, tmp_path, repo, remote, capsys
    ):
        from self_learn import intents

        other = clone(tmp_path, remote)
        commit_change(other, "other.md", "o\n", "remote work")
        git(other, "push", "-q")
        commit_change(repo, "a.md", "a\n", "local work")
        intent_id = _plant_unresolvable_stop(repo)

        result = gitops.push_with_retry(repo, is_ledger=True)

        assert not result.ok
        assert result.intent_stopped
        assert result.exit_code == 0  # the deliberate push/verb asymmetry
        assert intent_id in capsys.readouterr().err
        # The rebase never ran: the local commit is exactly what it was,
        # and the remote never saw it (nothing corrupt published, but
        # nothing new did either).
        assert local_subject(repo) == "local work"
        assert (intents.intents_dir(repo) / f"{intent_id}.json").is_file()

    def test_push_if_remote_threads_is_ledger(self, tmp_path, repo, remote, capsys):
        # `gitops.push_pending` (the ledger-only alias) is what every
        # ledger-push call site in the tree now calls, so its own
        # `is_ledger=True` must reach the rebase leg too.
        other = clone(tmp_path, remote)
        commit_change(other, "other.md", "o\n", "remote work")
        git(other, "push", "-q")
        commit_change(repo, "a.md", "a\n", "local work")
        intent_id = _plant_unresolvable_stop(repo)

        result = gitops.push_pending(repo)

        assert result.intent_stopped and result.exit_code == 0
        assert intent_id in capsys.readouterr().err
