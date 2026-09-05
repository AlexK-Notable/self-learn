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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from self_learn import gitops, intents, reconcile as reconcile_mod, verbs, worker
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


def seed_pending(home, rid, *, supersedes=None, **kwargs):
    record = make_behavior(record_id=rid, **kwargs)
    if supersedes is not None:
        record.set_supersedes(supersedes)
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

# Gate r1 MAJOR-1: the three compile-record mutations between
# `remove_merge` and `complete` -- `_write_compile_record_entry`
# (the survivor's own compile record), `_complete_old_retirement`
# (a no-op unless `old_id` names an ALREADY-ROUTED record -- gate r2
# minor-2's `TestCollapseWithOldIdCrashWindow` tests below are where
# it does real work) and `_resync_three_regions` (a no-op for a plain
# `dest="skill-md"` collapse, real only for `reference`/`hook` -- same
# gate r2 minor-2 tests use `DEST=reference` to reach it), all real
# call boundaries the fix must survive across, per the gate's own
# `probe_collapse.py`.
_orig_cre = verbs._write_compile_record_entry
def _cre(*a, **k):
    r = _orig_cre(*a, **k)
    if KILL_AFTER == "compile_record":
        _die("compile_record")
    return r
verbs._write_compile_record_entry = _cre

_orig_cor = verbs._complete_old_retirement
def _cor(*a, **k):
    r = _orig_cor(*a, **k)
    if KILL_AFTER == "old_retirement":
        _die("old_retirement")
    return r
verbs._complete_old_retirement = _cor

_orig_resync = verbs._resync_three_regions
def _resync(*a, **k):
    r = _orig_resync(*a, **k)
    if KILL_AFTER == "resync":
        _die("resync")
    return r
verbs._resync_three_regions = _resync

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
    dest=os.environ.get("DEST", "skill-md"),
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
        sha_before_crash = head(env.ledger)
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
        return env, survivor, loser, merge_path, sha_before_crash

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
        # Gate r1 MAJOR-1: the compile-record write (`compiled/<slug>
        # .yaml`) is now inside the intent's own protected span too --
        # this fixture's survivor never routed before, so that path's
        # `old_sha` is `null` (it did not exist pre-transaction), and a
        # full restore means it is GONE again, not merely unchanged.
        compiled_dir = env.ledger / "compiled"
        assert (not compiled_dir.is_dir()) or list(compiled_dir.glob("*.yaml")) == []

    def _assert_fully_rolled_forward(self, env, survivor, loser, sha_before_crash: str) -> None:
        pending = env.ledger / "skills" / "s" / "pending" / f"{survivor.id}.md"
        resolved = env.ledger / "skills" / "s" / "resolved" / f"{survivor.id}.md"
        loser_resolved = env.ledger / "skills" / "s" / "resolved" / f"{loser.id}.md"
        assert not pending.exists()
        assert resolved.is_file()
        assert loser_resolved.is_file()
        assert "superseded" in loser_resolved.read_text(encoding="utf-8")
        route_subject = (
            f"self-learn: route {survivor.id} → skill-md "
            f"(collapse merge-0000f001, supersedes {loser.id})"
        )
        assert route_subject in subjects(env.ledger)
        # Gate r1 MAJOR-1's expected consequence: the compile-record
        # writes are now inside the intent's own protected span, so
        # roll-forward's one commit covers them too -- the two-commit
        # split the ORIGINAL M-W design accepted (a SEPARATE
        # `reconcile()` orphan-scan commit for the leftover
        # `compiled/*.yaml` this intent used to leave uncovered) no
        # longer happens: exactly one new commit lands relative to
        # right before the crash, and it is this one.
        new_subjects = git(
            env.ledger, "log", "--format=%s", f"{sha_before_crash}..HEAD"
        ).stdout.strip().splitlines()
        assert new_subjects == [route_subject], new_subjects
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    @pytest.mark.parametrize(
        "kill_after",
        ["write", "resolve", "supersede", "remove_merge", "compile_record", "resync"],
    )
    def test_kill_before_complete_restores_pre_transaction_state(
        self, cluster, tmp_path, kill_after
    ):
        env, survivor, loser, merge_path, _sha_before_crash = self._fire(
            cluster, tmp_path, kill_after
        )
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped
        self._assert_fully_restored(env, survivor, loser, merge_path)

    def test_kill_after_complete_rolls_forward(self, cluster, tmp_path):
        env, survivor, loser, merge_path, sha_before_crash = self._fire(
            cluster, tmp_path, "complete"
        )
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert not result.restored and not result.stopped
        self._assert_fully_rolled_forward(env, survivor, loser, sha_before_crash)

    def test_kill_after_commit_is_idempotent(self, cluster, tmp_path):
        """Advisor's item E: the commit landed for real before the
        SIGKILL — only `intents.finish` never ran. Recovery must not
        raise `HalfWrittenError` on a batch with nothing left to stage,
        and must not create a second commit."""
        env, survivor, loser, merge_path, sha_before_crash = self._fire(
            cluster, tmp_path, "commit"
        )
        sha_before_reconcile = head(env.ledger)
        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.rolled_forward, result
        assert head(env.ledger) == sha_before_reconcile  # no duplicate commit
        self._assert_fully_rolled_forward(env, survivor, loser, sha_before_crash)


class TestCollapseWithOldIdCrashWindow:
    """`_execute_route`'s collapse intent-path construction has a
    dedicated `if old_id is not None:` arm (verbs.py, right after
    `intent_paths = [...]` is seeded) for `teach --supersedes` combined
    with `--collapse` in the SAME route call — the survivor itself
    supersedes a third record. `TestCollapseCrashWindows` above never
    sets `supersedes` on its survivor, so that arm ran on every green
    run without ever being exercised by a kill. This class closes that:
    the old record is pending (never routed), so its own retirement
    preflight is a no-op (`_retirement_preflight` returns immediately
    when `record.status != "routed"`) and the ONLY thing riding on the
    intent covering it is the plain pending→resolved supersede move —
    the simplest real instance of the branch, and sufficient to prove
    it is wired in at all."""

    @pytest.fixture
    def cluster_with_old_id(self, env, tmp_path):
        old = seed_pending(env.ledger, "lrn-0000f000")
        survivor = seed_pending(env.ledger, "lrn-0000f001", supersedes=old.id)
        loser = seed_pending(env.ledger, "lrn-0000f002")
        proposals_dir = env.ledger / "skills" / "s" / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        merge_path = proposals_dir / "merge-0000f001.yaml"
        merge_path.write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(env.ledger, "seed cluster")
        return env, survivor, loser, old, merge_path

    def test_kill_after_old_id_supersede_restores_everything(
        self, cluster_with_old_id, tmp_path
    ):
        env, survivor, loser, old, merge_path = cluster_with_old_id
        barrier = tmp_path / "barrier"
        # `_execute_route` calls `supersede_record` for `old_id` BEFORE
        # the losers loop, so `KILL_AFTER="supersede"` here fires right
        # after the OLD record's own pending→resolved move — a step the
        # `TestCollapseCrashWindows.cluster` fixture (no `old_id`) never
        # reaches on this same hook.
        proc = _run_child(
            _COLLAPSE_CHILD,
            {
                "SELF_LEARN_HOME": str(env.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "SURVIVOR_ID": survivor.id,
                "MERGE_ID": "merge-0000f001",
                "KILL_AFTER": "supersede",
            },
            barrier,
        )
        _assert_killed(proc, barrier, "supersede")

        old_pending = env.ledger / "skills" / "s" / "pending" / f"{old.id}.md"
        old_resolved = env.ledger / "skills" / "s" / "resolved" / f"{old.id}.md"
        survivor_pending = env.ledger / "skills" / "s" / "pending" / f"{survivor.id}.md"
        survivor_resolved = env.ledger / "skills" / "s" / "resolved" / f"{survivor.id}.md"
        loser_pending = env.ledger / "skills" / "s" / "pending" / f"{loser.id}.md"

        # Positive control: the old record's real supersede-move landed
        # (the child's hook calls through to the original before dying),
        # so a passing restore below proves reversal, not mere absence.
        assert old_resolved.is_file()
        assert not old_pending.exists()

        result = reconcile_mod.reconcile(env.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped

        assert old_pending.is_file()
        assert not old_resolved.exists()
        assert survivor_pending.is_file()
        assert "merged_from" not in survivor_pending.read_text(encoding="utf-8")
        assert not survivor_resolved.exists()
        assert loser_pending.is_file()
        assert merge_path.is_file()
        assert porcelain(env.ledger) == ""
        assert list(intents.intents_dir(env.ledger).glob("*.json")) == []

    # -------------------------------------------- gate r2 minor-2

    @pytest.fixture
    def cluster_with_a_routed_old_id(self, tmp_path, monkeypatch):
        """Gate r2 minor-2: `_complete_old_retirement`'s (verbs.py:4252)
        and `_resync_three_regions`'s (verbs.py:4261) own `intent=`
        threadings are unverified -- `cluster_with_old_id` above leaves
        `old` PENDING, so `_retirement_preflight` returns immediately
        and `_complete_old_retirement` never writes anything, and every
        `TestCollapseCrashWindows` fixture collapses to plain
        `dest="skill-md"`, which `_resync_three_regions` never resolves
        (real only for `reference`/`hook`, per its own docstring).

        This fixture ROUTES `old` to `skill-md` under the DEFAULT skill
        host BEFORE the collapse, then puts the survivor+loser under a
        SEPARATE, freshly `host_add`ed project host and collapses to
        `dest="reference"` there -- empirically confirmed (probe, not
        guessed) this makes BOTH functions do REAL work, each in its
        OWN compile-record FILE (`compiled_record_path` keys purely by
        HOST REPO PATH, one file per host -- a first probe using a
        SECOND SKILL under the SAME host repo put both writes in the
        SAME file, where retirement's own `add_step` call already
        covered the whole file and silently absorbed resync's write
        too, making the M-D3 mutation undetectable). Two hosts, two
        files, two independently restorable steps."""
        e = make_env(tmp_path, skills=("s",))
        monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))

        old = make_behavior(record_id="lrn-0000f000", scope="skill:s")
        create_record(e.ledger, old)
        commit_all(e.ledger, "seed old")
        verbs.route(e.ledger, old.id, dest="skill-md", no_push=True)
        compiled_dir = e.ledger / "compiled"
        [old_compiled] = list(compiled_dir.glob("*.yaml"))
        old_pre_bytes = old_compiled.read_bytes()

        project_repo = tmp_path / "proj-repo"
        init_repo(project_repo)
        (project_repo / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(project_repo, "proj seed")
        host_add(e.ledger, project_repo, "project")

        survivor = make_behavior(record_id="lrn-0000f001", scope="project")
        survivor.set_supersedes(old.id)
        create_record(e.ledger, survivor, project_path=project_repo)
        loser = make_behavior(record_id="lrn-0000f002", scope="project")
        create_record(e.ledger, loser, project_path=project_repo)
        proposals_dir = e.ledger / "projects" / slug_for(project_repo) / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        merge_path = proposals_dir / "merge-0000f001.yaml"
        merge_path.write_text(
            merge_proposal_text("merge-0000f001", [survivor.id, loser.id], survivor.id),
            encoding="utf-8",
        )
        commit_all(e.ledger, "seed cluster")
        return e, survivor, old_compiled, old_pre_bytes

    def _fire_routed_old_id(
        self, cluster_with_a_routed_old_id, tmp_path, kill_after: str
    ):
        e, survivor, old_compiled, old_pre_bytes = cluster_with_a_routed_old_id
        barrier = tmp_path / "barrier"
        proc = _run_child(
            _COLLAPSE_CHILD,
            {
                "SELF_LEARN_HOME": str(e.ledger),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache-child"),
                "SURVIVOR_ID": survivor.id,
                "MERGE_ID": "merge-0000f001",
                "KILL_AFTER": kill_after,
                "DEST": "reference",
            },
            barrier,
        )
        _assert_killed(proc, barrier, kill_after)
        compiled_dir = e.ledger / "compiled"
        proj_candidates = [p for p in compiled_dir.glob("*.yaml") if p != old_compiled]
        proj_compiled = proj_candidates[0] if proj_candidates else None
        return e, old_compiled, old_pre_bytes, proj_compiled

    def test_kill_after_old_retirement_restores_the_old_records_compile_record(
        self, cluster_with_a_routed_old_id, tmp_path
    ):
        """Mutation M-D2 (drop `intent=intent` from the
        `_complete_old_retirement` call in `_execute_route`): this
        kill lands right after `_complete_old_retirement`'s real
        rewrite of old's OWN compile-record entry and before
        `_resync_three_regions` even starts -- without the intent
        covering that write, restore leaves the retirement's rewrite
        in place instead of putting the entry back to its pre-collapse
        bytes."""
        e, old_compiled, old_pre_bytes, _proj_compiled = self._fire_routed_old_id(
            cluster_with_a_routed_old_id, tmp_path, "old_retirement"
        )
        # Positive control: the retirement's real write landed before
        # the kill (the child's hook calls through to the original
        # first, then dies) -- a passing restore below proves reversal.
        assert old_compiled.read_bytes() != old_pre_bytes

        result = reconcile_mod.reconcile(e.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped

        assert old_compiled.read_bytes() == old_pre_bytes
        assert porcelain(e.ledger) == ""
        assert list(intents.intents_dir(e.ledger).glob("*.json")) == []

    def test_kill_after_resync_restores_the_survivors_reference_region(
        self, cluster_with_a_routed_old_id, tmp_path
    ):
        """Mutation M-D3 (drop `intent=intent` from the
        `_resync_three_regions` call in `_execute_route`): this kill
        lands right after `_resync_three_regions` writes the survivor's
        OWN reference-region compile-record entry, in the project
        host's OWN compiled file -- a SEPARATE file from old's, so
        (unlike a same-host fixture) old's own `_complete_old_retirement`
        step can never absorb this write by accident. Without the
        intent covering it, restore leaves the project host's compiled
        file uncreated-but-uncleaned -- this fixture's `old_sha` for
        that step is `null` (the file did not exist before), so a
        correct restore DELETES it, not merely reverts its bytes.

        The PHYSICAL host-repo files (`references/LEARNINGS.md`) are a
        separate concern: `_host_phase` writes them AFTER the ledger
        commit + `intents.finish`, wholly outside this kill point (same
        as `_retirement_host_phase`'s script `git rm` above) -- a kill
        this early never reaches it in either branch, so it is not this
        test's job to assert on them."""
        e, _old_compiled, _old_pre_bytes, proj_compiled = self._fire_routed_old_id(
            cluster_with_a_routed_old_id, tmp_path, "resync"
        )
        # Positive control: the resync's real compile-record write
        # landed before the kill (a brand-new file -- `old_sha` is
        # `null`, this project host never had one before).
        assert proj_compiled is not None and proj_compiled.is_file()

        result = reconcile_mod.reconcile(e.ledger, no_push=True)
        assert result.restored, result
        assert not result.rolled_forward and not result.stopped

        assert not proj_compiled.exists(), "a null old_sha step restores by deleting the path"
        assert porcelain(e.ledger) == ""
        assert list(intents.intents_dir(e.ledger).glob("*.json")) == []


# ============================================================== rebind


class TestRebindCrashWindows:
    #: Gate r1 minor-1: the original fixture never committed the ledger
    #: bucket `create_record` writes, so it was UNTRACKED at rebind time
    #: — `git mv` on an untracked path stages nothing (`hosts.py`'s own
    #: `bucket.rename` fallback runs instead), so the `R`/`RM` staged-
    #: rename shape `_prune_empty_dirs`/the intent's `git reset -q --`
    #: exist to handle was never actually produced. Proof it mattered:
    #: mutation 3c (removing the index reset) reddened four COLLAPSE
    #: tests and ZERO rebind tests. Parametrized both ways: "tracked"
    #: covers the realistic case (a project bucket almost always has
    #: prior history by the time a rebind happens) and is what makes the
    #: staged-rename shape real; "untracked" keeps the ORIGINAL fixture's
    #: coverage of `hosts.py`'s plain-rename fallback path.
    @pytest.fixture(params=["tracked", "untracked"])
    def rebind_setup(self, env, tmp_path, request):
        project_repo = tmp_path / "proj-repo"
        init_repo(project_repo)
        (project_repo / "README.md").write_text("proj\n", encoding="utf-8")
        commit_all(project_repo, "proj seed")
        host_add(env.ledger, project_repo, "project")
        record = make_behavior(scope="project", record_id="lrn-0000e001")
        create_record(env.ledger, record, project_path=project_repo)
        if request.param == "tracked":
            commit_all(env.ledger, "commit the bucket")
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
        # Gate r1 MAJOR-3(b): a STOP must not stage anything either --
        # "nothing is touched" (the module docstring's own promise)
        # means the INDEX too, not just the worktree bytes.
        assert git(repo, "diff", "--cached").stdout == ""

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

    def test_oversize_untracked_step_stops_without_touching_bytes(self, tmp_path):
        """Gate r1 MAJOR-3(a): an untracked file BIGGER than `_INLINE_CAP`
        (64 KiB) gets no inline copy — recovery has no source at all for
        its pre-transaction bytes (not git, since it was never tracked;
        not the intent, since it is over the cap), so it must STOP,
        never silently accept whatever happens to be on disk.

        Gate r2 MAJOR-1: the fixture used to size itself from
        `intents._INLINE_CAP + 1` -- derived from the very constant this
        test exists to pin, so changing `_INLINE_CAP` to ANYTHING moved
        the fixture right along with it and this test could never redden
        on a cap change (measured: `_INLINE_CAP = 64 * 1024 * 1024` still
        passed). A literal size PLUS a separate assertion pinning the
        constant's own value closes that: raising the cap reddens the
        second line below, shrinking it reddens the first."""
        assert intents._INLINE_CAP == 64 * 1024, "the D7 pin itself"
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        f = repo / "big.bin"
        f.write_bytes(b"A" * 65_537)  # a literal 64 KiB + 1, untracked, over the cap

        intent = intents.begin(repo, "test-op", [f], "self-learn: test op")
        raw = json.loads(intent.file_path.read_text(encoding="utf-8"))
        assert "old_inline" not in raw["steps"][0], (
            "over the cap must NOT carry an inline copy — that is the "
            "whole point of the cap"
        )

        f.write_bytes(b"B" * 10)  # crash before complete(): mutated, uncompleted

        result = intents.recover(repo)
        assert result.stopped and intent.id in result.stopped[0]
        assert not result.rolled_forward and not result.restored
        assert intent.file_path.exists(), "a STOP must leave the intent in place"
        assert f.read_bytes() == b"B" * 10, "STOP must not touch the step's bytes"
        assert git(repo, "diff", "--cached").stdout == ""

    def test_recover_survives_a_ledger_moved_to_a_new_location(self, tmp_path):
        """Gate r1 minor-2: an intent opened against ``home`` must recover
        cleanly when ``home`` itself has moved (a restore from backup, or
        a relocated checkout) between the crash and the recovery call —
        storing ``step['path']`` HOME-RELATIVE (this fold) is what makes
        this possible: the ABSOLUTE path this fixture used to store would
        fall outside the new location's subtree and raise ``ValueError``
        out of every caller (`reconcile()`, `push`, the miner's own
        `except gitops.GitOpsError` — which does not catch it — and
        `worker.run`'s unguarded call)."""
        old_home = tmp_path / "old-location"
        init_repo(old_home)
        f = old_home / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(old_home, "seed")

        intent = intents.begin(old_home, "test-op", [f], "self-learn: test op")
        f.write_text("mutated, crash before complete()", encoding="utf-8")

        new_home = tmp_path / "new-location"
        shutil.move(str(old_home), str(new_home))

        result = intents.recover(new_home)
        assert result.restored == [intent.id]
        assert not result.stopped
        assert (new_home / "a.txt").read_text(encoding="utf-8") == "old"
        assert not (new_home / ".intents" / f"{intent.id}.json").exists()

    def test_head_show_converts_a_timeout_to_giterror(self, tmp_path, monkeypatch):
        """Gate r1 minor-3: `_head_show`'s bespoke `subprocess.run` (kept
        bespoke because it is the one byte-exact call in this module —
        `gitops._git`/`procs.run_bounded` both force `text=True`) must
        still convert a `TimeoutExpired` to `gitops.GitOpsError`, the way
        every OTHER child process in this codebase does, instead of
        letting the raw stdlib exception escape past `_capture_old_state`
        (called from `begin`, uncaught anywhere above it)."""
        repo = tmp_path / "repo"
        init_repo(repo)
        f = repo / "a.txt"
        f.write_text("old", encoding="utf-8")
        commit_all(repo, "seed")

        def _wedged(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git show", timeout=30.0)

        monkeypatch.setattr(intents.subprocess, "run", _wedged)

        with pytest.raises(gitops.GitOpsError, match="git show"):
            intents._head_show(repo, "a.txt")

    def test_recover_reports_a_corrupt_intent_file_as_unreadable(self, tmp_path):
        """Gate r2 nit-1: a genuinely corrupt (unparseable) intent file
        must report "unreadable intent file" -- distinct from
        "unresolvable intent", which names a real, half-written step the
        JSON parses fine but cannot restore. Widening `recover()`'s `try`
        to cover `_recover_one` too (gate r1 minor-2) folded BOTH failure
        phases into the same message; splitting them back out means an
        operator reads which repair applies (fix/delete the file, vs.
        inspect the path the message names) directly off the line,
        without opening the file first."""
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        bad = intents.intents_dir(repo) / "deadbeef0000.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not valid json", encoding="utf-8")

        result = intents.recover(repo)
        assert result.stopped and "unreadable intent file" in result.stopped[0]
        assert "unresolvable intent" not in result.stopped[0]
        assert bad.is_file(), "a STOP must leave the intent file in place"

    def test_recover_reports_a_malformed_intent_as_unresolvable(self, tmp_path):
        """Gate r2 nit-1's other half: valid JSON that does not match the
        intent schema (here, missing `steps` entirely) reaches
        `_from_dict`, raises `KeyError`, and must report "unresolvable
        intent" -- the file itself was perfectly readable, so the
        "unreadable" wording would misdirect an operator toward fixing
        JSON syntax that was never broken."""
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "placeholder.txt").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        bad = intents.intents_dir(repo) / "deadbeef0001.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text(
            json.dumps(
                {
                    "op": "test-op",
                    "id": "deadbeef0001",
                    "started": "2026-09-05T00:00:00Z",
                    # `steps` and `commit_subject` deliberately omitted --
                    # `_from_dict` indexes both unconditionally.
                }
            ),
            encoding="utf-8",
        )

        result = intents.recover(repo)
        assert result.stopped and "unresolvable intent" in result.stopped[0]
        assert "unreadable intent file" not in result.stopped[0]
        assert bad.is_file(), "a STOP must leave the intent file in place"
