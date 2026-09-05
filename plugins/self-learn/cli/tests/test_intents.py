"""M-W (Sprint 2 lane L7, D7): crash-safe multi-file ledger transactions.

Collapse (`_execute_route`, `collapse` set) and `hosts.host_rebind` each
mutate several files under one lock before their one commit — a
``SIGKILL`` between any two of those mutations used to leave a staged
rename `reconcile._BLOCKING_CODES` refuses to touch forever, or (rebind)
a modified-uncommitted ``hosts.yaml`` reconcile could not even SEE
(``reconcile._RECONCILABLE_HOME`` had no entry for it at all). This file
proves :mod:`self_learn.intents` closes both gaps.

**No mocks of git** (project discipline): every crash-window test spawns
a REAL child process that runs the REAL verb against a REAL git sandbox,
monkeypatches (in the CHILD only — a fresh interpreter, so this never
touches pytest's own process) one real mutation to write a barrier file
recording which step landed and then ``os.kill(getpid(), SIGKILL)`` —
deterministic, and the barrier file is the positive control that the
kill landed where intended, not earlier or later. :func:`TestCoreMechanics`
exercises the same recovery logic against a plain scratch repo, without a
child process, for the shapes a full verb scenario cannot cheaply isolate
(the "commit already landed, only `finish` never ran" idempotent case;
the "neither old nor new state is resolvable" stop case).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from self_learn import gitops, intents, reconcile as reconcile_mod, worker
from self_learn.hosts import host_add, host_rebind, load_hosts, slug_for
from self_learn.ledger_ops import create_record
from support import commit_all, git, init_repo, make_behavior, make_env, merge_proposal_text


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def subjects(repo: Path) -> list[str]:
    return git(repo, "log", "--format=%s").stdout.strip().splitlines()


def porcelain(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "-uall").stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return e


def seed_pending(home, rid, **kwargs):
    record = make_behavior(record_id=rid, **kwargs)
    create_record(home, record)
    commit_all(home, "seed record")
    return record


# ============================================================ child runner


#: The collapse child: installs one hook per real mutation `_execute_route`
#: makes when `collapse` is set, each calling through to the ORIGINAL
#: implementation first (so the kill always lands AFTER the real effect),
#: then — only for the step named by `$KILL_AFTER` — writing the barrier
#: and self-SIGKILLing. Every OTHER step is a plain pass-through, so one
#: script serves every kill point without six near-duplicate files.
_COLLAPSE_CHILD = r"""
import os, signal
from self_learn import intents, ledger_ops, records, verbs

KILL_AFTER = os.environ["KILL_AFTER"]
BARRIER = os.environ["BARRIER"]

def _die(step):
    with open(BARRIER, "w", encoding="utf-8") as fh:
        fh.write(step)
    os.kill(os.getpid(), signal.SIGKILL)

_orig_write = records.Record.write
def _write(self, path):
    _orig_write(self, path)
    if KILL_AFTER == "write":
        _die("write")
records.Record.write = _write

_orig_resolve = verbs.resolve_record
def _resolve(*a, **k):
    r = _orig_resolve(*a, **k)
    if KILL_AFTER == "resolve":
        _die("resolve")
    return r
verbs.resolve_record = _resolve

_orig_supersede = verbs.supersede_record
def _supersede(*a, **k):
    r = _orig_supersede(*a, **k)
    if KILL_AFTER == "supersede":
        _die("supersede")
    return r
verbs.supersede_record = _supersede

_orig_remove = ledger_ops._remove_file
def _remove(*a, **k):
    r = _orig_remove(*a, **k)
    if KILL_AFTER == "remove_merge":
        _die("remove_merge")
    return r
ledger_ops._remove_file = _remove

_orig_complete = intents.complete
def _complete(intent):
    _orig_complete(intent)
    if KILL_AFTER == "complete":
        _die("complete")
verbs.intents.complete = _complete

_orig_commit = verbs._commit_ledger
def _commit(*a, **k):
    r = _orig_commit(*a, **k)
    if KILL_AFTER == "commit":
        _die("commit")
    return r
verbs._commit_ledger = _commit

verbs.route(
    os.environ["SELF_LEARN_HOME"],
    os.environ["SURVIVOR_ID"],
    dest="skill-md",
    collapse=os.environ["MERGE_ID"],
    no_push=True,
)
"""

#: The rebind child: same shape, one hook per real mutation `host_rebind`
#: makes. The git-mv hook filters on the subcommand so it does not fire
#: on every OTHER `_git` call the same run makes (staging, committing).
_REBIND_CHILD = r"""
import os, signal
from self_learn import gitops, hosts, intents

KILL_AFTER = os.environ["KILL_AFTER"]
BARRIER = os.environ["BARRIER"]

def _die(step):
    with open(BARRIER, "w", encoding="utf-8") as fh:
        fh.write(step)
    os.kill(os.getpid(), signal.SIGKILL)

_orig_git = gitops._git
def _git(repo, *args, **kwargs):
    r = _orig_git(repo, *args, **kwargs)
    if KILL_AFTER == "mv" and args and args[0] == "mv":
        _die("mv")
    return r
gitops._git = _git

_orig_dump_meta = hosts._dump_meta
def _dump_meta(*a, **k):
    r = _orig_dump_meta(*a, **k)
    if KILL_AFTER == "dump_meta":
        _die("dump_meta")
    return r
hosts._dump_meta = _dump_meta

_orig_save_hosts = hosts.save_hosts
def _save_hosts(*a, **k):
    r = _orig_save_hosts(*a, **k)
    if KILL_AFTER == "save_hosts":
        _die("save_hosts")
    return r
hosts.save_hosts = _save_hosts

_orig_complete = intents.complete
def _complete(intent):
    _orig_complete(intent)
    if KILL_AFTER == "complete":
        _die("complete")
hosts.intents.complete = _complete

_orig_commit = hosts._commit_or_half_written
def _commit(*a, **k):
    r = _orig_commit(*a, **k)
    if KILL_AFTER == "commit":
        _die("commit")
    return r
hosts._commit_or_half_written = _commit

hosts.host_rebind(
    os.environ["SELF_LEARN_HOME"],
    os.environ["OLD_PATH"],
    os.environ["NEW_PATH"],
)
"""


def _run_child(script: str, env_overrides: dict, barrier: Path) -> subprocess.CompletedProcess:
    child_env = dict(os.environ)
    child_env.pop("SELF_LEARN_ANALYST_MODEL", None)
    child_env.pop("SELF_LEARN_ANALYST_TIMEOUT", None)
    child_env.update(env_overrides)
    child_env["BARRIER"] = str(barrier)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc


def _assert_killed(proc: subprocess.CompletedProcess, barrier: Path, expected_step: str) -> None:
    assert proc.returncode == -9, (proc.returncode, proc.stdout, proc.stderr)
    assert barrier.is_file(), "the child never reached the intended kill point"
    assert barrier.read_text(encoding="utf-8") == expected_step


# ================================================================ collapse


class TestCollapseCrashWindows:
    """One kill point per adjacent mutation pair `_execute_route` makes
    for a collapse (survivor + one loser, no old_id — the shortest
    sequence that still exercises write / resolve / supersede /
    remove_merge), plus the roll-forward and the idempotent-after-commit
    windows."""

    @pytest.fixture
    def cluster(self, env, tmp_path):
        survivor = seed_pending(env.ledger, "lrn-0000f001")
        loser = seed_pending(env.ledger, "lrn-0000f002")
        proposals_dir = env.ledger / "skills" / "s" / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        merge_path = proposals_dir / "merge-0000f001.yaml"
        merge_path.write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(env.ledger, "seed cluster")
        return env, survivor, loser, merge_path

    def _fire(self, cluster, tmp_path, kill_after: str):
        env, survivor, loser, merge_path = cluster
        barrier = tmp_path / "barrier"
        proc = _run_child(
            _COLLAPSE_CHILD,
            {
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "SURVIVOR_ID": survivor.id,
                "MERGE_ID": "merge-0000f001",
                "KILL_AFTER": kill_after,
            },
            barrier,
        )
        _assert_killed(proc, barrier, kill_after)
        return env, survivor, loser, merge_path

    def _assert_fully_restored(self, env, survivor, loser, merge_path) -> None:
        pending = env.ledger / "skills" / "s" / "pending" / f"{survivor.id}.md"
        resolved = env.ledger / "skills" / "s" / "resolved" / f"{survivor.id}.md"
        loser_pending = env.ledger / "skills" / "s" / "pending" / f"{loser.id}.md"
        assert pending.is_file()
        assert "merged_from" not in pending.read_text(encoding="utf-8")
        assert not resolved.exists()
        assert loser_pending.is_file()
        assert merge_path.is_file()
        assert porcelain(env.ledger) == ""
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    def _assert_fully_rolled_forward(self, env, survivor, loser) -> None:
        pending = env.ledger / "skills" / "s" / "pending" / f"{survivor.id}.md"
        resolved = env.ledger / "skills" / "s" / "resolved" / f"{survivor.id}.md"
        loser_resolved = env.ledger / "skills" / "s" / "resolved" / f"{loser.id}.md"
        assert not pending.exists()
        assert resolved.is_file()
        assert loser_resolved.is_file()
        assert "superseded" in loser_resolved.read_text(encoding="utf-8")
        # The intent's own commit carries the ORIGINAL subject regardless
        # of whether reconcile's ordinary orphan scan (compile-record
        # entries this intent deliberately does not cover — see
        # `_execute_route`'s own comment) lands a SEPARATE, later commit
        # in the same `reconcile()` call — hence membership, not `[0]`.
        assert (
            f"self-learn: route {survivor.id} → skill-md "
            f"(collapse merge-0000f001, supersedes {loser.id})"
        ) in subjects(env.ledger)
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    @pytest.mark.parametrize("kill_after", ["write", "resolve", "supersede", "remove_merge"])
    def test_kill_before_complete_restores_pre_transaction_state(
        self, cluster, tmp_path, kill_after
    ):
        env, survivor, loser, merge_path = self._fire(cluster, tmp_path, kill_after)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped
        self._assert_fully_restored(env, survivor, loser, merge_path)

    def test_kill_after_complete_rolls_forward(self, cluster, tmp_path):
        env, survivor, loser, merge_path = self._fire(cluster, tmp_path, "complete")
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert not result.restored and not result.stopped
        self._assert_fully_rolled_forward(env, survivor, loser)

    def test_kill_after_commit_is_idempotent(self, cluster, tmp_path):
        """Advisor's item E: the commit landed for real before the
        SIGKILL — only `intents.finish` never ran. Recovery must not
        raise `HalfWrittenError` on a batch with nothing left to stage,
        and must not create a second commit."""
        env, survivor, loser, merge_path = self._fire(cluster, tmp_path, "commit")
        sha_before = head(env.ledger)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert head(env.ledger) == sha_before  # no duplicate commit
        self._assert_fully_rolled_forward(env, survivor, loser)


# ============================================================== rebind


class TestRebindCrashWindows:
    @pytest.fixture
    def rebind_setup(self, env, tmp_path):
        project_repo = tmp_path / "proj-repo"
        init_repo(project_repo)
        (project_repo / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(project_repo, "proj seed")
        host_add(env.ledger, project_repo, "project")
        record = make_behavior(scope="project", record_id="lrn-0000e001")
        create_record(env.ledger, record, project_path=project_repo)
        moved = tmp_path / "proj-moved"
        project_repo.rename(moved)
        return env, project_repo, moved

    def _fire(self, rebind_setup, tmp_path, kill_after: str):
        env, project_repo, moved = rebind_setup
        barrier = tmp_path / "barrier"
        proc = _run_child(
            _REBIND_CHILD,
            {
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "OLD_PATH": str(project_repo),
                "NEW_PATH": str(moved),
                "KILL_AFTER": kill_after,
            },
            barrier,
        )
        _assert_killed(proc, barrier, kill_after)
        return env, project_repo, moved

    def _assert_fully_restored(self, env, project_repo, moved) -> None:
        old_bucket = env.ledger / "projects" / slug_for(project_repo)
        new_bucket = env.ledger / "projects" / slug_for(moved)
        assert old_bucket.is_dir()
        assert not new_bucket.exists()
        assert (old_bucket / "pending" / "lrn-0000e001.md").is_file()
        assert project_repo.resolve() in [Path(p).resolve() for p in load_hosts(env.ledger).projects]
        assert moved.resolve() not in [Path(p).resolve() for p in load_hosts(env.ledger).projects]
        assert porcelain(env.ledger) == ""
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    def _assert_fully_rolled_forward(self, env, project_repo, moved) -> None:
        new_bucket = env.ledger / "projects" / slug_for(moved)
        old_bucket = env.ledger / "projects" / slug_for(project_repo)
        assert new_bucket.is_dir()
        assert not old_bucket.exists()
        assert (new_bucket / "pending" / "lrn-0000e001.md").is_file()
        assert moved.resolve() in [Path(p).resolve() for p in load_hosts(env.ledger).projects]
        assert subjects(env.ledger)[0] == (
            f"self-learn: host rebind {project_repo.resolve()} → {moved.resolve()}"
        )
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    @pytest.mark.parametrize("kill_after", ["mv", "dump_meta", "save_hosts"])
    def test_kill_before_complete_restores_pre_transaction_state(
        self, rebind_setup, tmp_path, kill_after
    ):
        env, project_repo, moved = self._fire(rebind_setup, tmp_path, kill_after)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped
        self._assert_fully_restored(env, project_repo, moved)

    def test_kill_after_complete_rolls_forward(self, rebind_setup, tmp_path):
        env, project_repo, moved = self._fire(rebind_setup, tmp_path, "complete")
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        self._assert_fully_rolled_forward(env, project_repo, moved)

    def test_kill_after_commit_is_idempotent(self, rebind_setup, tmp_path):
        env, project_repo, moved = self._fire(rebind_setup, tmp_path, "commit")
        sha_before = head(env.ledger)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert head(env.ledger) == sha_before
        self._assert_fully_rolled_forward(env, project_repo, moved)


# ========================================================= worker.run

class TestWorkerRunFindsAnIntent:
    def test_worker_run_recovers_an_interrupted_intent_at_start(self, env, tmp_path):
        """Positive control (coordinator pin): a leftover intent is found
        and resolved by `worker.run`'s START, not just by an explicit
        `reconcile()` call. This plants the intent directly (via the
        SAME `intents.begin`/crash shape the subprocess-kill tests above
        already prove end-to-end for a REAL SIGKILL against `reconcile()`)
        rather than re-driving a full collapse under a subprocess: this
        assertion is about `worker.run`'s WIRING, and re-deriving the SDK-
        fake harness (`backends.install_fake`, needed the instant `worker.
        run` finds eligible pending work) to reach the same wiring proof
        would cost real complexity for no additional coverage.
        `make_env` seeds no pending records, so `run` reaches `status ==
        "idle"` right after recovery without ever touching the SDK."""
        yaml_path = env.ledger / "hosts.yaml"
        old_bytes = yaml_path.read_bytes()
        intent = intents.begin(
            env.ledger, "host_add", [yaml_path], "self-learn: host add project /tmp/x"
        )
        yaml_path.write_bytes(old_bytes + b"  # crash before complete()\n")
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == [intent.file_path]

        result = worker.run(env.ledger, no_push=True)

        assert result.status == "idle"
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []
        assert yaml_path.read_bytes() == old_bytes
        assert porcelain(env.ledger) == ""
        log_text = (worker.cache_dir() / "worker.log").read_text(encoding="utf-8")
        assert "recovered intent" in log_text


# ============================================ reconcile._RECONCILABLE_HOME gain


class TestReconcilableHomeExtension:
    """`reconcile._RECONCILABLE_HOME` gains `hosts.yaml`/`config.yaml`
    (the pin, independent of the intent mechanism above): a plain
    orphaned write to either — no intent involved at all, the ordinary
    "producer wrote it, could not commit it" shape — used to be
    completely invisible to `find_orphans` (no path-shape match
    whatsoever); it must now heal exactly like `compiled/*.yaml` already
    did."""

    def test_a_plain_hosts_yaml_orphan_is_healed(self, env):
        from self_learn.hosts import save_hosts, Hosts

        before = (env.ledger / "hosts.yaml").read_text(encoding="utf-8")
        save_hosts(env.ledger, Hosts(skills_root=env.host, projects=[], skills_root_mode="git"))
        assert (env.ledger / "hosts.yaml").read_text(encoding="utf-8") != before
        assert porcelain(env.ledger) != ""

        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert not result.refused, result
        assert env.ledger / "hosts.yaml" in result.committed
        assert porcelain(env.ledger) == ""

    def test_a_plain_config_yaml_orphan_is_healed(self, env):
        from self_learn import config as config_mod

        config_path = config_mod.config_path(env.ledger)
        data = config_mod.load_editable(env.ledger)
        data["worker"] = {"repair": False}
        config_mod.dump_editable(env.ledger, data)
        assert config_path.is_file()
        assert porcelain(env.ledger) != ""

        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert not result.refused, result
        assert config_path in result.committed
        assert porcelain(env.ledger) == ""


class TestHostAddAndRemoveIntents:
    """`host_add`/`host_remove` write the same single-step intent shape
    `TestCoreMechanics` already proves generically — this is the ONE
    end-to-end witness that the REAL verbs wire it in, via an ordinary
    (non-SIGKILL) exception raised between the write and `intents.
    complete` -- a plain interpreter-level crash needs no subprocess to
    simulate: it unwinds `commit_lock`'s context manager exactly the way
    a SIGKILL's kernel-level lock release does."""

    def test_host_add_recovers_from_a_crash_before_complete(self, env, tmp_path, monkeypatch):
        from self_learn import hosts as hosts_mod

        real_save_hosts = hosts_mod.save_hosts

        def _boom(*a, **k):
            path = real_save_hosts(*a, **k)
            raise RuntimeError("simulated crash before intents.complete")

        monkeypatch.setattr(hosts_mod, "save_hosts", _boom)
        new_host = tmp_path / "new-host"
        init_repo(new_host)
        before = load_hosts(env.ledger)

        with pytest.raises(RuntimeError, match="simulated crash"):
            hosts_mod.host_add(env.ledger, new_host, "project")

        assert list(intents.intents_dir(env.ledger).glob("*.json"))
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert load_hosts(env.ledger) == before
        assert porcelain(env.ledger) == ""

    def test_host_remove_recovers_from_a_crash_before_complete(self, env, tmp_path, monkeypatch):
        from self_learn import hosts as hosts_mod

        project_repo = tmp_path / "proj-repo"
        init_repo(project_repo)
        (project_repo / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(project_repo, "proj seed")
        hosts_mod.host_add(env.ledger, project_repo, "project")
        before = load_hosts(env.ledger)

        real_save_hosts = hosts_mod.save_hosts

        def _boom(*a, **k):
            real_save_hosts(*a, **k)
            raise RuntimeError("simulated crash before intents.complete")

        monkeypatch.setattr(hosts_mod, "save_hosts", _boom)
        with pytest.raises(RuntimeError, match="simulated crash"):
            hosts_mod.host_remove(env.ledger, project_repo)

        assert list(intents.intents_dir(env.ledger).glob("*.json"))
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert load_hosts(env.ledger) == before
        assert porcelain(env.ledger) == ""


# ============================================================ core mechanics


class TestCoreMechanics:
    """Direct exercise of `begin`/`complete`/`finish`/`recover` against a
    plain scratch repo — the shapes a full verb scenario cannot cheaply
    isolate."""

    def test_roll_forward_when_commit_never_ran(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("new", encoding="utf-8")
        intents.complete(intent)
        assert intent.file_path.is_file()

        result = intents.recover(repo)
        assert result.rolled_forward == [intent.id]
        assert not intent.file_path.exists()
        assert git(repo, "log", "-1", "--format=%s").stdout.strip() == "self-learn: test op"
        assert f.read_text(encoding="utf-8") == "new"

    def test_roll_forward_is_a_noop_when_the_commit_already_landed(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("new", encoding="utf-8")
        intents.complete(intent)
        # simulate: the commit landed for real, only `finish` never ran
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "self-learn: test op")
        sha_before = head(repo)

        result = intents.recover(repo)
        assert result.rolled_forward == [intent.id]
        assert head(repo) == sha_before
        assert not intent.file_path.exists()

    def test_restore_undoes_a_mid_transaction_crash(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("new", encoding="utf-8")  # crash before complete()

        result = intents.recover(repo)
        assert result.restored == [intent.id]
        assert f.read_text(encoding="utf-8") == "old"
        assert not intent.file_path.exists()
        assert porcelain(repo) == ""

    def test_restore_deletes_a_path_that_should_not_have_existed(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        new_f = repo / "new.txt"

        intent = intents.begin(repo, "test-op", [new_f], "self-learn: test op")
        new_f.write_text("premature", encoding="utf-8")  # crash before complete()

        result = intents.recover(repo)
        assert result.restored == [intent.id]
        assert not new_f.exists()
        assert not intent.file_path.exists()

    def test_stop_when_prior_content_is_unresolvable_anywhere(self, tmp_path):
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        f.write_text("mutated", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "an unrelated commit moves HEAD past old_sha")
        f.write_text("further mutated, still uncompleted", encoding="utf-8")

        result = intents.recover(repo)
        assert result.stopped and intent.id in result.stopped[0]
        assert not result.rolled_forward and not result.restored
        assert intent.file_path.exists(), "a STOP must leave the intent in place"
        assert f.read_text(encoding="utf-8") == "further mutated, still uncompleted"

    def test_untracked_file_restores_from_the_inline_copy(self, tmp_path):
        """The pin-implied `old_inline` key: an UNTRACKED file's bytes
        are not in git's object store, so recovery can only restore them
        from the intent's own inline copy."""
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        f = repo / "untracked.txt"
        f.write_text("untracked original", encoding="utf-8")  # never committed

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        raw = json.loads(intent.file_path.read_text(encoding="utf-8"))
        assert raw["steps"][0].get("old_inline"), "untracked content must be captured inline"

        f.write_text("mutated, crash before complete()", encoding="utf-8")
        result = intents.recover(repo)
        assert result.restored == [intent.id]
        assert f.read_text(encoding="utf-8") == "untracked original"
