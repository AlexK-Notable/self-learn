"""FW-162: a capture made inside a git worktree files under its registered
parent host, never under an unregistered bucket keyed to the worktree.

Every repo here is real: ``git init`` plus ``git worktree add`` in
``tmp_path``. Captures go through the producers' own entry points —
``self-learn teach`` (``cli.main``), the miner's
``_reconcile_and_land`` and ``import_memory`` — so each remapping test
fails on the code before FW-162 by landing in the worktree's bucket, not
by a missing name.

A removed worktree (git can no longer answer) files under its host only
by the narrow ``<registered host>/.claude/worktrees/<name>`` shape, and
only while the path does not exist (``TestRemovedWorktree``).

The unchanged cases (a sibling repo, an unregistered repo's worktree, a
main-tree subdirectory, a removed path elsewhere) and the fail-closed
cases (git absent, hosts.yaml unloadable) pass before and after FW-162
by design.
Each of them carries a positive control in the same environment: the
remapping is shown to be live there, so "unchanged" cannot be a resolver
that never fires.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from self_learn import cli, hosts, miner
from self_learn.hosts import host_add, load_hosts, slug_for
from self_learn.import_memory import import_memory
from self_learn.ledger_ops import bucket_project_path

from support import commit_all, git, init_repo, make_env

FIXTURE_MEMORY = Path(__file__).parent / "fixtures" / "memory"


def _is_linked_worktree(path: Path) -> bool:
    """git's own answer, computed independently of the code under test."""
    git_dir, common_dir = git(path, "rev-parse", "--git-dir", "--git-common-dir").stdout.split()
    return (path / git_dir).resolve() != (path / common_dir).resolve()


def _add_worktree(repo: Path, where: Path, branch: str) -> Path:
    where.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", str(where), "-b", branch)
    return where


def _bucket(home: Path, path: Path) -> Path:
    return home / "projects" / slug_for(path)


def _pending_ids(bucket: Path) -> list[str]:
    return sorted(p.stem for p in bucket.glob("pending/lrn-*.md"))


def _teach(monkeypatch, home: Path, cwd: Path, fact: str) -> None:
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    monkeypatch.chdir(cwd)
    try:
        rc = cli.main(["teach", fact, "--project"])
    except SystemExit as exc:  # argparse's own exits
        rc = exc.code
    assert rc == 0, rc


def _mine(home: Path, cwds: dict[str, Path]) -> miner.MineResult:
    """Land one project-scoped knowledge candidate per session in *cwds*."""
    result = miner.MineResult(status="ok")
    parsed = {
        "candidates": [
            {
                "scope": "project",
                "type": "knowledge",
                "fact": f"Fact number {i} about the proxy.",
                "session": session,
                "line": 7,
                "quote": "",
            }
            for i, session in enumerate(cwds, start=1)
        ]
    }
    miner._reconcile_and_land(
        home, parsed, result, 10, {s: str(p) for s, p in cwds.items()}
    )
    return result


@dataclass(frozen=True)
class Sandbox:
    ledger: Path
    host: Path
    inside: Path  # linked worktree under <host>/.claude/worktrees/
    outside: Path  # linked worktree outside the host's tree


@pytest.fixture
def sandbox(tmp_path) -> Sandbox:
    """A registered host (``make_env``: project host + skills root) with
    two linked worktrees: one under ``.claude/worktrees/``, one in an
    unrelated directory outside the host's tree."""
    env = make_env(tmp_path)
    inside = _add_worktree(env.host, env.host / ".claude" / "worktrees" / "feat", "feat")
    outside = _add_worktree(env.host, tmp_path / "elsewhere" / "feat2", "feat2")
    # Positive controls for the fixture itself: both really are linked
    # worktrees, and each would key a DIFFERENT bucket than the host.
    assert _is_linked_worktree(inside) and _is_linked_worktree(outside)
    assert not _is_linked_worktree(env.host)
    assert slug_for(inside) != slug_for(env.host) != slug_for(outside)
    return Sandbox(ledger=env.ledger, host=env.host, inside=inside, outside=outside)


# ------------------------------------------------------------ teach (remaps)


class TestTeachRemaps:
    def test_host_and_its_worktree_share_one_bucket(self, sandbox, monkeypatch):
        home, host = sandbox.ledger, sandbox.host
        # Positive control: a capture from the host itself lands in the
        # host's bucket.
        _teach(monkeypatch, home, host, "The proxy strips trailing slashes.")
        host_bucket = _bucket(home, host)
        assert len(_pending_ids(host_bucket)) == 1

        _teach(monkeypatch, home, sandbox.inside, "The proxy caches for one hour.")

        assert len(_pending_ids(host_bucket)) == 2
        assert bucket_project_path(host_bucket) == host.resolve()
        assert not _bucket(home, sandbox.inside).exists()

    def test_worktree_outside_the_host_tree(self, sandbox, monkeypatch):
        home, host = sandbox.ledger, sandbox.host
        _teach(monkeypatch, home, sandbox.outside, "The proxy caches for one hour.")

        host_bucket = _bucket(home, host)
        assert len(_pending_ids(host_bucket)) == 1
        assert bucket_project_path(host_bucket) == host.resolve()
        assert not _bucket(home, sandbox.outside).exists()

    def test_subdirectory_of_a_worktree(self, sandbox, monkeypatch):
        home, host = sandbox.ledger, sandbox.host
        sub = sandbox.inside / "src" / "deep"
        sub.mkdir(parents=True)
        _teach(monkeypatch, home, sub, "The proxy caches for one hour.")

        assert len(_pending_ids(_bucket(home, host))) == 1
        assert not _bucket(home, sandbox.inside).exists()


# ------------------------------------------------------------ miner (remaps)


class TestMinerRemaps:
    def test_worktree_cwd_lands_in_the_host_bucket(self, sandbox):
        home, host = sandbox.ledger, sandbox.host
        result = _mine(
            home,
            {
                "sess-inside": sandbox.inside,
                "sess-outside": sandbox.outside,
                "sess-host": host,  # positive control: the host itself
            },
        )
        assert len(result.landed) == 3
        host_bucket = _bucket(home, host)
        assert sorted(_pending_ids(host_bucket)) == sorted(result.landed)
        assert bucket_project_path(host_bucket) == host.resolve()
        assert not _bucket(home, sandbox.inside).exists()
        assert not _bucket(home, sandbox.outside).exists()
        # the landing commit stages the HOST bucket's meta.yaml
        assert host_bucket / "meta.yaml" in result.touched

    def test_main_tree_subdirectory_keeps_the_raw_cwd(self, sandbox):
        """Unchanged: the miner files a session by its raw cwd, and a
        subdirectory of a MAIN working tree is not a worktree — FW-162
        must not widen into "map every cwd to its toplevel"."""
        home, host = sandbox.ledger, sandbox.host
        sub = host / "sub"
        sub.mkdir()
        result = _mine(home, {"sess-sub": sub, "sess-wt": sandbox.inside})
        assert len(result.landed) == 2
        assert len(_pending_ids(_bucket(home, sub))) == 1
        assert bucket_project_path(_bucket(home, sub)) == sub.resolve()
        # positive control, same run: the worktree session WAS remapped
        assert len(_pending_ids(_bucket(home, host))) == 1


# ---------------------------------------------------- import-memory (remaps)


def test_import_memory_default_project_path_in_a_worktree(sandbox, tmp_path, monkeypatch):
    home, host = sandbox.ledger, sandbox.host
    memory_dir = tmp_path / "memory"
    shutil.copytree(FIXTURE_MEMORY, memory_dir)
    monkeypatch.chdir(sandbox.inside)

    report = import_memory(home, memory_dir)

    host_ids = _pending_ids(_bucket(home, host))
    # the fixture's two project-scoped topic files (research-archive,
    # beacon-host) — the third is user-scoped
    assert len(host_ids) == 2
    assert set(host_ids) <= set(report.created)
    assert bucket_project_path(_bucket(home, host)) == host.resolve()
    assert not _bucket(home, sandbox.inside).exists()


# --------------------------------------------------------------- unchanged


class TestUnchanged:
    def test_sibling_plain_repo(self, sandbox, tmp_path, monkeypatch):
        home = sandbox.ledger
        sibling = tmp_path / "sibling"
        init_repo(sibling)
        (sibling / "README").write_text("x\n", encoding="utf-8")
        commit_all(sibling)

        _teach(monkeypatch, home, sibling, "The sibling builds with make.")
        assert len(_pending_ids(_bucket(home, sibling))) == 1
        assert bucket_project_path(_bucket(home, sibling)) == sibling.resolve()

        # positive control, same ledger: a worktree capture IS remapped
        _teach(monkeypatch, home, sandbox.inside, "The proxy caches for one hour.")
        assert len(_pending_ids(_bucket(home, sandbox.host))) == 1

    def test_worktree_of_an_unregistered_repo(self, sandbox, tmp_path, monkeypatch):
        home = sandbox.ledger
        other = tmp_path / "other"
        init_repo(other)
        (other / "README").write_text("x\n", encoding="utf-8")
        commit_all(other)
        other_wt = _add_worktree(other, other / ".claude" / "worktrees" / "w", "w")
        # positive control: it IS a linked worktree, so only registration
        # decides that it stays put
        assert _is_linked_worktree(other_wt)

        _teach(monkeypatch, home, other_wt, "The other repo pins node 22.")
        assert len(_pending_ids(_bucket(home, other_wt))) == 1
        assert not _bucket(home, other).exists()

        # positive control, same ledger: a REGISTERED host's worktree remaps
        _teach(monkeypatch, home, sandbox.inside, "The proxy caches for one hour.")
        assert len(_pending_ids(_bucket(home, sandbox.host))) == 1

    def test_unregistered_repo_nested_under_a_registered_host(self, sandbox, tmp_path):
        """Exact match only: a repo nested inside a registered host is not
        that host, so its worktree is an unregistered repo's worktree."""
        home, host = sandbox.ledger, sandbox.host
        nested = host / "vendor" / "lib"
        init_repo(nested)
        (nested / "README").write_text("x\n", encoding="utf-8")
        commit_all(nested)
        nested_wt = _add_worktree(nested, tmp_path / "nested-wt", "n")
        # positive controls: linked, and its main tree DOES sit under a
        # registered host — an ancestor-match rule would remap it
        assert _is_linked_worktree(nested_wt)
        assert hosts.ancestors_of(load_hosts(home), nested) == [host.resolve()]

        result = _mine(home, {"sess-nested": nested_wt, "sess-wt": sandbox.inside})
        assert len(result.landed) == 2
        assert len(_pending_ids(_bucket(home, nested_wt))) == 1
        assert len(_pending_ids(_bucket(home, host))) == 1  # the control remapped

    def test_a_registered_worktree_keeps_its_own_registration(self, sandbox):
        home, host, wt = sandbox.ledger, sandbox.host, sandbox.outside
        # positive control: unregistered, the worktree maps to its host
        assert hosts.capture_host_path(home, wt) == host.resolve()

        host_add(home, wt, "project")

        assert hosts.capture_host_path(home, wt) == wt


# --------------------------------------------------------- removed worktree


class TestRemovedWorktree:
    """Once a worktree is removed git has nothing left to answer, so for a
    path that does NOT exist — and only then — the shape
    ``<P>/.claude/worktrees/<name>[/…]`` with ``<P>`` exactly a registered
    project host files under ``<P>``."""

    def test_removed_worktree_under_a_registered_host_maps_to_the_host(self, sandbox):
        home, host, wt = sandbox.ledger, sandbox.host, sandbox.inside
        assert hosts.capture_host_path(home, wt) == host.resolve()  # git's answer while live

        git(host, "worktree", "remove", str(wt))
        assert not wt.exists()
        # git no longer knows it: the remap below cannot be git's answer
        listing = git(host, "worktree", "list", "--porcelain").stdout
        assert f"worktree {sandbox.outside}" in listing  # control: listing is real
        assert f"worktree {wt}" not in listing

        assert hosts.capture_host_path(home, wt) == host.resolve()
        assert hosts.capture_host_path(home, wt / "src" / "deep") == host.resolve()

    def test_removed_path_under_an_unregistered_repo_is_unchanged(self, sandbox, tmp_path):
        home, host = sandbox.ledger, sandbox.host
        other = tmp_path / "other"
        init_repo(other)
        (other / "README").write_text("x\n", encoding="utf-8")
        commit_all(other)
        other_wt = _add_worktree(other, other / ".claude" / "worktrees" / "w", "w")
        git(other, "worktree", "remove", str(other_wt))
        assert not other_wt.exists()
        # nested inside the registered host, but not the host itself
        nested_gone = host / "vendor" / "lib" / ".claude" / "worktrees" / "w"
        assert hosts.ancestors_of(load_hosts(home), nested_gone)  # an ancestor IS registered

        assert hosts.capture_host_path(home, other_wt) == other_wt
        assert hosts.capture_host_path(home, nested_gone) == nested_gone

        # positive control, same registry: the pattern is live for the host
        gone = host / ".claude" / "worktrees" / "never-existed"
        assert hosts.capture_host_path(home, gone) == host.resolve()

    def test_removed_path_elsewhere_is_unchanged(self, sandbox):
        home, host, wt = sandbox.ledger, sandbox.host, sandbox.outside
        assert hosts.capture_host_path(home, wt) == host.resolve()  # control, while live

        git(host, "worktree", "remove", str(wt))
        assert not wt.exists()

        assert hosts.capture_host_path(home, wt) == wt

    def test_existing_non_worktree_dir_follows_git_not_the_pattern(self, sandbox):
        """A directory that EXISTS under ``.claude/worktrees/`` but is not a
        worktree is part of the host's main working tree: git says so, and
        git's answer is the only one asked for a live path."""
        home, host = sandbox.ledger, sandbox.host
        plain = host / ".claude" / "worktrees" / "scratch"
        plain.mkdir(parents=True)
        assert not _is_linked_worktree(plain)  # git: a main working tree

        assert hosts.capture_host_path(home, plain) == plain

        # positive control: the SAME shape, once gone, does map
        gone = host / ".claude" / "worktrees" / "scratch-gone"
        assert hosts.capture_host_path(home, gone) == host.resolve()

    def test_bare_worktrees_dir_without_a_name_is_unchanged(self, sandbox, tmp_path):
        """``<P>/.claude/worktrees`` itself is not a worktree: the shape
        needs a ``<name>`` segment after it."""
        home = sandbox.ledger
        second = tmp_path / "second-host"  # a registered host with no .claude/ yet
        init_repo(second)
        (second / "README").write_text("x\n", encoding="utf-8")
        commit_all(second)
        host_add(home, second, "project")
        bare = second / ".claude" / "worktrees"
        assert not bare.exists()

        assert hosts.capture_host_path(home, bare) == bare

        # positive control: one segment deeper, the same host IS named
        assert hosts.capture_host_path(home, bare / "gone") == second.resolve()

    def test_innermost_registered_host_wins(self, sandbox):
        """Several ``.claude/worktrees`` segments: the innermost one whose
        ``<P>`` is registered names the host."""
        home, host, inner = sandbox.ledger, sandbox.host, sandbox.inside
        gone = inner / ".claude" / "worktrees" / "nested-gone"
        assert not gone.exists()
        # positive control: with only the OUTER host registered, the outer
        # segment is the one that matches — both segments are reachable
        assert hosts.capture_host_path(home, gone) == host.resolve()

        host_add(home, inner, "project")  # the worktree itself, registered

        assert hosts.capture_host_path(home, gone) == inner.resolve()

    def test_miner_lands_a_removed_worktree_session_in_the_host_bucket(self, sandbox):
        """The nightly mine reads a session after it ends — the path that
        produced 6 of the 7 live misfiles."""
        home, host = sandbox.ledger, sandbox.host
        git(host, "worktree", "remove", str(sandbox.inside))
        git(host, "worktree", "remove", str(sandbox.outside))
        assert not sandbox.inside.exists() and not sandbox.outside.exists()

        result = _mine(
            home, {"sess-inside": sandbox.inside, "sess-outside": sandbox.outside}
        )

        assert len(result.landed) == 2
        host_bucket = _bucket(home, host)
        assert len(_pending_ids(host_bucket)) == 1
        assert bucket_project_path(host_bucket) == host.resolve()
        assert not _bucket(home, sandbox.inside).exists()
        # control, same run: a removed worktree NOT under .claude/worktrees/
        # keeps its own bucket, so the remap above is the pattern's doing
        assert len(_pending_ids(_bucket(home, sandbox.outside))) == 1


# ------------------------------------------------------------- fail closed


class TestFailClosed:
    def test_git_absent(self, sandbox, tmp_path, monkeypatch):
        home, host, wt = sandbox.ledger, sandbox.host, sandbox.inside
        # positive control: with git on PATH the worktree maps to its host
        assert hosts.capture_host_path(home, wt) == host.resolve()

        empty = tmp_path / "no-git-here"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert shutil.which("git") is None  # git really is absent now

        assert hosts.capture_host_path(home, wt) == wt

    def test_unloadable_hosts_yaml(self, sandbox):
        home, host, wt = sandbox.ledger, sandbox.host, sandbox.inside
        assert hosts.capture_host_path(home, wt) == host.resolve()  # control

        (home / "hosts.yaml").write_text("projects: 7\n", encoding="utf-8")
        with pytest.raises(hosts.HostsError):
            load_hosts(home)  # the registry really is unloadable

        assert hosts.capture_host_path(home, wt) == wt

    def test_main_tree_registered_only_as_skills_root(self, sandbox, tmp_path):
        """A project bucket needs a registered PROJECT host; a worktree of a
        repo registered only as the skills root keeps today's bucket. An
        unrelated project stays registered, so the registry is non-empty
        and the exact-match check is what decides."""
        home, host, wt = sandbox.ledger, sandbox.host, sandbox.inside
        assert hosts.capture_host_path(home, wt) == host.resolve()  # control

        unrelated = tmp_path / "unrelated"
        init_repo(unrelated)
        (home / "hosts.yaml").write_text(
            f"skills_root: {host}\nprojects:\n  - path: {unrelated}\n",
            encoding="utf-8",
        )
        registry = load_hosts(home)
        assert registry.skills_root == host and registry.projects == [unrelated]

        assert hosts.capture_host_path(home, wt) == wt
