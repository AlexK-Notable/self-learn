"""M-D: `gitops.is_tracked` / `gitops.remove` — thin public wrappers over
`gitops._git` (sprint 1 plan v2 §2, ``BRIEF-ledger-git.md`` pinned
decisions). Closes A8/C12a: `ledger_ops` used to shell its own private
`_git` straight out to a git subprocess for these two checks; now it goes
through the bounded, already-tested seam this module owns.

Each test builds its own throwaway repo (`support.init_repo`/`commit_all`
— never the worktree repo itself, per that module's own header)."""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn import gitops
from support import commit_all, git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    init_repo(r)
    return r


class TestIsTracked:
    def test_true_for_a_committed_file(self, repo: Path):
        f = repo / "a.txt"
        f.write_text("hello\n", encoding="utf-8")
        commit_all(repo, "seed")
        assert gitops.is_tracked(repo, f) is True

    def test_false_for_an_untracked_file(self, repo: Path):
        f = repo / "b.txt"
        f.write_text("never added\n", encoding="utf-8")
        assert gitops.is_tracked(repo, f) is False

    def test_false_for_a_path_that_does_not_exist_at_all(self, repo: Path):
        assert gitops.is_tracked(repo, repo / "nope.txt") is False

    def test_false_for_the_old_path_right_after_a_git_mv(self, repo: Path):
        """Deliberately NOT `known_paths`' HEAD-widened behavior: the pin
        is plain `ls-files --error-unmatch` (no `--with-tree=HEAD`), so
        right after `git mv` the OLD path — gone from disk AND the index,
        surviving only in HEAD until the mv is committed — reads as
        untracked here. That is fine for this wrapper's own callers (each
        checks `is_tracked` on a path BEFORE moving it, never after)."""
        f = repo / "old.txt"
        f.write_text("x\n", encoding="utf-8")
        commit_all(repo, "seed")
        git(repo, "mv", "old.txt", "new.txt")
        assert not f.exists()
        assert gitops.is_tracked(repo, f) is False

    def test_accepts_a_string_path_too(self, repo: Path):
        f = repo / "c.txt"
        f.write_text("x\n", encoding="utf-8")
        commit_all(repo, "seed")
        assert gitops.is_tracked(repo, str(f)) is True


class TestRemove:
    def test_removes_a_clean_tracked_file_from_index_and_worktree(self, repo: Path):
        f = repo / "d.txt"
        f.write_text("x\n", encoding="utf-8")
        commit_all(repo, "seed")
        gitops.remove(repo, f)
        assert not f.exists()
        status = git(repo, "status", "--porcelain").stdout
        assert status.strip() == "D  d.txt", status

    def test_raises_on_an_untracked_file(self, repo: Path):
        """`remove` is `git rm --quiet` — no `--ignore-unmatch`. A caller
        MUST guard with `is_tracked` first (exactly what `ledger_ops.
        _remove_file` does); called bare against something git has never
        heard of, it raises rather than silently no-op-ing."""
        f = repo / "e.txt"
        f.write_text("x\n", encoding="utf-8")
        with pytest.raises(gitops.GitOpsError):
            gitops.remove(repo, f)
        assert f.exists()  # nothing removed — the raise fired before any fs change

    def test_raises_on_a_tracked_file_modified_since_its_last_commit(self, repo: Path):
        """Brief-statement probe (pinned decision says plain `git rm
        --quiet`, no `-f`): `git rm` refuses a tracked file whose worktree
        content differs from the index/HEAD UNLESS `-f` is given. Without
        `-f`, a dirty tracked file is another shape `remove` cannot
        silently swallow — see the report's "Brief statements found
        false" for whether `_remove_file`'s two callers can ever reach
        this shape in practice."""
        f = repo / "f.txt"
        f.write_text("original\n", encoding="utf-8")
        commit_all(repo, "seed")
        f.write_text("modified, never staged\n", encoding="utf-8")
        with pytest.raises(gitops.GitOpsError):
            gitops.remove(repo, f)
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "modified, never staged\n"

    def test_accepts_a_string_path_too(self, repo: Path):
        f = repo / "g.txt"
        f.write_text("x\n", encoding="utf-8")
        commit_all(repo, "seed")
        gitops.remove(repo, str(f))
        assert not f.exists()


def test_both_wrappers_are_exported():
    assert "is_tracked" in gitops.__all__
    assert "remove" in gitops.__all__
