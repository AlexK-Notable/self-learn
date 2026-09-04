"""M-D: `gitops.is_tracked` / `gitops.remove` — thin public wrappers over
`gitops._git` (sprint 1 plan v2 §2, ``BRIEF-ledger-git.md`` pinned
decisions). Closes A8/C12a: `ledger_ops` used to shell its own private
`_git` straight out to a git subprocess for these two checks; now it goes
through the bounded, already-tested seam this module owns.

Each test builds its own throwaway repo (`support.init_repo`/`commit_all`
— never the worktree repo itself, per that module's own header)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from self_learn import gitops, ledger_ops, verbs
from self_learn.hosts import host_add, slug_for
from self_learn.ledger_ops import create_record
from support import commit_all, failing_git_shim, git, init_repo, make_env, make_knowledge


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


# ============================ M-D fold r2 BLOCKER: _remove_file HalfWritten


#: A REAL git that fails `rm` only when NEEDLE appears in argv — unlike
#: `support.failing_git_shim` (one flag, one subcommand, no path
#: selectivity), this lets a two-removal sequence have its FIRST
#: succeed and its SECOND fail, reproducing the gate's exact repro
#: ("`D skills/a/meta.yaml` sits staged" while the second removal's
#: failure is what escapes).
_PATH_FAILING_RM_SHIM = '''#!/usr/bin/env python3
import subprocess, sys

args = sys.argv[1:]
if "rm" in args and any({needle!r} in a for a in args):
    sys.stderr.write("fatal: simulated git rm failure for {needle}\\n")
    sys.exit(1)
sys.exit(subprocess.run([{real!r}, *args]).returncode)
'''


def _failing_rm_shim_for_path(tmp_path: Path, monkeypatch, needle: str) -> None:
    real = shutil.which("git")
    assert real, "no git on PATH"
    d = tmp_path / "git-shim-rm-path"
    d.mkdir(parents=True, exist_ok=True)
    shim = d / "git"
    shim.write_text(_PATH_FAILING_RM_SHIM.format(needle=needle, real=real))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")


class TestRemoveFileHalfWritten:
    """cli.py's own dispatch contract (~:1899-1906): EXIT_GIT_FAILED (6,
    'nothing was written') is safe ONLY because every post-mutation git
    failure is re-raised as gitops.HalfWrittenError (-> exit 7) before
    reaching that handler. `_remove_file` calling the un-`-f`'d
    `gitops.remove` (M-D) reopened a way for a bare `GitOpsError` to
    violate that.

    M-D fold r2 (BLOCKER) closed it by having `_remove_file` itself
    catch and convert — but that primitive only ever sees the ONE path
    it is working on, so the repair it built could name a failing path
    while omitting an earlier-succeeded removal already staged in the
    same sequence (M-D fold r3 MINOR: the gate's own repro,
    `test_bucket_prune_...` below). Fixed by moving the conversion OUT
    of `_remove_file` and INTO each of its four callers — the VERB
    layer, the only place that holds the enclosing `touched` list, per
    `gitops.HalfWrittenError`'s own docstring ("constructed by the
    verb, never by this module")."""

    def test_remove_file_itself_raises_git_ops_error_not_half_written(
        self, repo: Path, tmp_path, monkeypatch
    ):
        """The primitive no longer converts — it has no `touched`
        context to build a correct repair from. A bare GitOpsError
        propagating out of `_remove_file` itself is now the CORRECT
        shape; the class docstring above is where the conversion
        promise actually lives, honored by each of the four callers."""
        f = repo / "d.txt"
        f.write_text("x\n", encoding="utf-8")
        commit_all(repo, "seed")
        flag = failing_git_shim(tmp_path, monkeypatch, sub="rm")
        flag.touch()
        with pytest.raises(gitops.GitOpsError) as excinfo:
            ledger_ops._remove_file(repo, f)
        assert not isinstance(excinfo.value, gitops.HalfWrittenError)
        assert f.exists()  # git rm never landed — the fs is untouched too

    def test_remove_proposal_siblings_raises_half_written_not_git_failed(
        self, repo: Path, tmp_path, monkeypatch
    ):
        bucket_dir = repo / "skills" / "s"
        pdir = bucket_dir / "proposals"
        pdir.mkdir(parents=True)
        (pdir / "lrn-00000001.yaml").write_text("x: 1\n", encoding="utf-8")
        commit_all(repo, "seed proposal")
        flag = failing_git_shim(tmp_path, monkeypatch, sub="rm")
        flag.touch()
        with pytest.raises(gitops.HalfWrittenError):
            ledger_ops.remove_proposal_siblings(repo, bucket_dir, "lrn-00000001")

    def test_bucket_prune_raises_half_written_not_git_failed_when_a_later_removal_fails(
        self, tmp_path, monkeypatch
    ):
        """The gate's own repro, reproduced directly: two empty project
        buckets. The first bucket's `meta.yaml` removal SUCCEEDS (lands
        staged); the second's is made to fail. `bucket_prune` must let
        `HalfWrittenError` escape -- never a bare `GitOpsError`, which
        would report exit 6 ("nothing was written") while the first
        bucket's staged deletion sits in the index."""
        sb = make_env(tmp_path, skills=("s",))
        buckets = []
        for name in ("empty1", "empty2"):
            host = tmp_path / "repos" / name
            init_repo(host)
            (host / "README.md").write_text(f"{name}\n", encoding="utf-8")
            commit_all(host, "seed")
            host_add(sb.ledger, host, "project")
            rid = f"lrn-{name[-1]}0000001"
            create_record(sb.ledger, make_knowledge(record_id=rid, scope="project"), project_path=host)
            commit_all(sb.ledger, f"seed {name}")
            verbs.rehome(sb.ledger, rid, to="user", no_push=True)
            buckets.append(sb.ledger / "projects" / slug_for(host))
        for b in buckets:
            assert (b / "meta.yaml").is_file()  # positive control: prune has work to do

        # fail ONLY the second bucket's meta.yaml removal -- the FULL path
        # (both buckets share the basename "meta.yaml", so a needle any
        # shorter than the full path would fail BOTH removals)
        second_meta = buckets[1] / "meta.yaml"
        _failing_rm_shim_for_path(tmp_path, monkeypatch, str(second_meta))

        with pytest.raises(gitops.HalfWrittenError) as excinfo:
            verbs.bucket_prune(sb.ledger, no_push=True)

        # the first bucket's removal DID land, staged -- the exact
        # contract violation the gate's report names: a bare GitOpsError
        # here would have claimed "nothing was written" over this.
        status = git(sb.ledger, "status", "--porcelain").stdout
        assert "D " in status and "meta.yaml" in status, status

        # M-D fold r3 (MINOR): the repair must name the MUTATION that
        # needs committing (the already-staged first bucket's deletion),
        # not just the path that failed -- an operator following the
        # repair line literally must not leave the ledger half-written.
        first_meta = buckets[0] / "meta.yaml"
        assert str(first_meta) in excinfo.value.repair, excinfo.value.repair
        # and the real verb message reached the repair, not a generic
        # per-path stand-in -- proves this was built by bucket_prune
        # itself, not reconstructed inside _remove_file.
        assert "bucket prune" in excinfo.value.repair, excinfo.value.repair
