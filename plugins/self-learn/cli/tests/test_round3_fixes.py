"""Round-3 audit fixes (2026-07-16): the commit lock's real scope, git
timeouts, GitOpsError never reaching a traceback, the no-push leak through
the miner watchdog, and the no-remote guard across ALL ten verbs.

Design pin shared by every test here: **no mocks**. Real git sandboxes,
real second processes, real spawned children. Where a microsecond-wide
window has to be held open, it is held open by instrumenting *git* (a PATH
shim or a real hook) — never by replacing any code under test. A shim that
substitutes self-learn's own logic would be testing the test.

Why that matters here specifically: the previous round's flagship race
test PASSED against the reverted code, because the racer inside it also
passed ``paths=[…]`` and so exercised the pathspec layer rather than the
lock it was named for. Every test below was verified by reverting its fix
and watching it go red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from self_learn import cli, gitops, miner, verbs, worker
from self_learn.ledger_ops import create_record
from self_learn.records import Record
from support import (
    commit_all,
    failing_git_shim,
    git,
    init_repo,
    make_behavior,
    make_env,
)

CLI_SRC = str(Path(__file__).resolve().parents[1] / "src")
REAL_GIT = "/usr/bin/git"
#: U-cleanup-A: sdk-backed replacement `claude` target for the
#: bash PATH shim below.
FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"


# --------------------------------------------------------------- helpers


def bare_remote(tmp_path: Path, repo: Path, name: str = "bare.git") -> Path:
    """Give *repo* a REAL remote (a bare clone target) and push main."""
    bare = tmp_path / name
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True
    )
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


def third_clone(tmp_path: Path, bare: Path, name: str = "clone") -> Path:
    """A SECOND machine's clone of the same ledger — the thing that makes
    a later push a genuine non-fast-forward."""
    clone = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    git(clone, "config", "user.email", "b@example.com")
    git(clone, "config", "user.name", "MachineB")
    return clone


def remote_subjects(bare: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(bare), "log", "--format=%s", "main"],
        capture_output=True,
        text=True,
    )
    return out.stdout.split("\n") if out.returncode == 0 else []


def head_files(repo: Path) -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()


def run_child(script: str, timeout: float = 90, env: dict | None = None):
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def lock_holder_script(repo: Path, ready: Path, release: Path) -> str:
    """A REAL second process that takes *repo*'s commit lock and holds it
    until told to let go — the "another producer is committing right now"
    condition, with nothing simulated."""
    return textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {CLI_SRC!r})
        from pathlib import Path
        from self_learn import gitops
        with gitops.commit_lock(Path({str(repo)!r})):
            Path({str(ready)!r}).touch()
            deadline = time.monotonic() + 30
            while not Path({str(release)!r}).exists() and time.monotonic() < deadline:
                time.sleep(0.01)
    """)


def wait_for(path: Path, timeout: float = 30) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.005)
    return False


# ======================================== BLOCKER C: the rebase-autostash race


class TestRebaseAutostashRace:
    """What the commit lock ACTUALLY guarantees, proven.

    Reverting ``commit_lock`` to a no-op used to cost exactly ONE test
    failure — a tautological unit test of flock itself — because the only
    "race" test's racer also passed ``paths=[…]`` and therefore proved the
    PATHSPEC layer. The hazard a pathspec cannot survive is the one below,
    established by probe (2026-07-16, /tmp probe p3) before this test was
    written:

    A producer stages work (``resolve_record``'s ``git mv`` + record
    rewrite). A concurrent producer's push is non-fast-forward, so it
    enters ``git pull --rebase --autostash``. The autostash sweeps the
    victim's staged work into a stash; the restore CONFLICTS (the other
    machine resolved the same record), so git leaves CONFLICT MARKERS in
    the worktree and strands the work in an orphaned stash. The victim's
    pathspec commit — which commits worktree content — then commits the
    conflict markers as the resolution.

    Measured damage with the fix reverted (2026-07-16), and it is worse
    than "a lost commit": the resolved record file lands in history
    carrying THREE status lines — ``status: deferred``, ``status:
    pending``, ``status: rejected`` — between ``<<<<<<<``/``>>>>>>>``
    markers, with ``git status`` CLEAN, an orphaned stash, and **exit 0**.
    An unparseable record in the ledger, reported as a success. Every
    reader downstream (the queue, the worker, the compilers, the digest)
    then trips over a file the CLI itself says it wrote correctly.

    (An earlier draft of this docstring claimed the damage was "the record
    in both pending/ and resolved/" — that is what the /tmp probe's
    2-line stand-in file produced, not what the real records do. Corrected
    to what was actually measured: overclaiming in a test name is the bug
    this round exists to fix.)

    The window is between ``git mv`` and ``commit`` and is microseconds
    wide, so it is held open by instrumenting GIT — a PATH shim that runs
    the real ``git mv``, releases the racer, and waits. (Probed: a
    ``pre-commit`` hook is the WRONG place — git holds ``index.lock``
    across the hook of a pathspec commit, so a racing autostash there
    merely fails. The gap between two git processes is the real window.)
    """

    def _setup(self, tmp_path, *, collide: bool = True):
        env = make_env(tmp_path)
        home = env.ledger
        record = make_behavior(record_id="lrn-aaaa0001")
        rec_path = create_record(home, record)
        commit_all(home, "record seed")

        bare = bare_remote(tmp_path, home)
        clone = third_clone(tmp_path, bare)

        # MACHINE B resolves the SAME record and publishes it — the
        # ordinary multi-machine ledger situation, and the whole reason
        # ``pull --rebase`` exists here. It is what makes both (a) our push
        # non-fast-forward and (b) the autostash restore CONFLICT.
        #
        # It must collide on the same LINE, and that is not a contrivance:
        # ``status:`` is the line every resolution verb rewrites, so two
        # machines resolving one record always meet there. (Measured
        # 2026-07-16: when B touched a DIFFERENT line — `sightings:` — the
        # autostash merged cleanly and nothing broke. The corruption needs
        # a real content collision, so the test must stage a real one.)
        rel = rec_path.relative_to(home)
        if collide:
            theirs = clone / rel
            theirs.write_text(
                theirs.read_text(encoding="utf-8").replace(
                    "status: pending", "status: deferred"
                ),
                encoding="utf-8",
            )
            git(clone, "commit", "-q", "-am", "machine B: deferred the same record")
        else:
            # A merely BUSY neighbour: B publishes something unrelated, so
            # the rebase is clean and the only question is whether the lock
            # serializes without starving anyone.
            (clone / "unrelated.md").write_text("b\n", encoding="utf-8")
            git(clone, "add", "-A")
            git(clone, "commit", "-q", "-m", "machine B: unrelated work")
        git(clone, "push", "-q")

        # ...and OUR ledger has an unpushed local commit, so our push is a
        # real non-FF against a real remote.
        (home / "telemetry" / "2026-07.testhost.jsonl").write_text(
            '{"kind":"capture"}\n', encoding="utf-8"
        )
        commit_all(home, "local telemetry commit")
        return home, rec_path, rel, bare

    def _stage_shim(self, tmp_path, go: Path, done: Path) -> Path:
        """A PATH shim for GIT (never for any self-learn code): on the
        verb's ``git add`` it runs the real add, releases the racer, and
        waits a BOUNDED time for it. Under a correctly scoped lock the
        racer is blocked, this simply times out, and that is the passing
        case.

        WHY ``add`` AND NOT ``mv`` — measured, not assumed. Instrumenting
        ``git mv`` opens the window one step too early: at that instant the
        index holds a PURE rename of unchanged content, and git's
        rename detection reapplies that over machine B's edit cleanly (run
        2026-07-16: racer confirmed ``R pending -> resolved`` staged, the
        rebase ran, and NOTHING broke). The corruption needs the rename
        AND the rewritten body at the same path — i.e. the state after
        ``resolve_record`` has finished, which is what the verb's single
        ``git add`` marks. That is the last git call before ``commit``, and
        the widest real window in the sequence."""
        shims = tmp_path / "shims"
        shims.mkdir(exist_ok=True)
        shim = shims / "git"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            'for a in "$@"; do\n'
            '  if [ "$a" = "add" ]; then\n'
            f'    {REAL_GIT} "$@"; rc=$?\n'
            f'    touch "{go}"\n'
            "    for _ in $(seq 1 300); do\n"
            f'      [ -f "{done}" ] && break\n'
            "      sleep 0.01\n"
            "    done\n"
            "    exit $rc\n"
            "  fi\n"
            "done\n"
            f'exec {REAL_GIT} "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return shims

    def test_a_racing_rebase_cannot_split_a_verbs_rename(
        self, tmp_path, monkeypatch
    ):
        home, rec_path, rel, bare = self._setup(tmp_path)
        go, done = tmp_path / "go", tmp_path / "racer-done"

        # The racer: a REAL process running the REAL push path. Its push is
        # non-FF, so it falls back to pull --rebase --autostash — the thing
        # that rewrites the index and worktree under everybody else.
        racer_src = f"""
            import sys, time
            sys.path.insert(0, {CLI_SRC!r})
            from pathlib import Path
            from self_learn import gitops
            go, done = Path({str(go)!r}), Path({str(done)!r})
            deadline = time.monotonic() + 30
            while not go.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            try:
                gitops.push_with_retry(Path({str(home)!r}))
            finally:
                done.touch()
        """
        racer = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(racer_src)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PATH": "/usr/bin:/bin"},  # racer uses REAL git
        )

        shims = self._stage_shim(tmp_path, go, done)
        monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        # The victim: the REAL verb, unmodified.
        result = verbs.reject(home, "lrn-aaaa0001", note=None)
        racer.communicate(timeout=90)
        monkeypatch.setenv("PATH", os.environ["PATH"].split(":", 1)[-1])

        files = head_files(home)
        assert str(rel) not in files, (
            "the rename committed in HALF — the record is in pending/ AND "
            f"resolved/ at once. HEAD: {files}"
        )
        assert "skills/s/resolved/lrn-aaaa0001.md" in files, (
            f"the resolved record never landed. HEAD: {files}"
        )

        # THE assertion: what got COMMITTED must be a record, not a merge
        # casualty. This is what the reverted code fails.
        committed = git(
            home, "show", "HEAD:skills/s/resolved/lrn-aaaa0001.md"
        ).stdout
        assert "<<<<<<<" not in committed and ">>>>>>>" not in committed, (
            "THE BUG: conflict markers were COMMITTED as the resolved "
            f"record — exit 0, `git status` clean.\n{committed}"
        )
        status_lines = [
            ln for ln in committed.splitlines() if ln.startswith("status:")
        ]
        assert status_lines == ["status: rejected"], (
            "THE BUG: the committed record does not have exactly one, "
            f"correct status — got {status_lines}"
        )
        Record.from_path(home / "skills" / "s" / "resolved" / "lrn-aaaa0001.md")

        # the pinned subject is what H-6 / doc 13 §1 Q3 make load-bearing
        assert result.commit_sha
        assert git(
            home, "log", "--grep", "^self-learn: reject ", "--format=%s"
        ).stdout.strip(), "the digest's grep finds no reject commit"
        # and nothing was left marooned in a stash
        assert not git(home, "stash", "list").stdout.strip(), (
            "work was left in an orphaned autostash"
        )

    def test_the_racers_own_work_still_lands(self, tmp_path, monkeypatch):
        """The lock must SERIALIZE, not starve: after the verb releases it,
        the racer's rebase+push completes and its commit reaches the
        remote. A lock that merely traded the victim's loss for the
        racer's would be no fix at all.

        ``collide=False`` here on purpose. With a colliding machine B (the
        first test's setup) the serialized racer correctly reports a REBASE
        CONFLICT — two machines really did resolve one record differently,
        and the pinned policy is never-auto-resolve. That is the right
        answer, not starvation, but it is a different property; this test
        isolates "does the second producer still get through"."""
        home, rec_path, rel, bare = self._setup(tmp_path, collide=False)
        go, done = tmp_path / "go2", tmp_path / "racer-done2"
        racer_src = f"""
            import sys, time
            sys.path.insert(0, {CLI_SRC!r})
            from pathlib import Path
            from self_learn import gitops
            go, done = Path({str(go)!r}), Path({str(done)!r})
            deadline = time.monotonic() + 30
            while not go.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            try:
                r = gitops.push_with_retry(Path({str(home)!r}))
                print("PUSH_OK" if r.ok else "PUSH_FAIL")
            finally:
                done.touch()
        """
        racer = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(racer_src)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PATH": "/usr/bin:/bin"},
        )
        shims = self._stage_shim(tmp_path, go, done)
        monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        verbs.reject(home, "lrn-aaaa0001", note=None)
        out, _ = racer.communicate(timeout=90)
        monkeypatch.setenv("PATH", os.environ["PATH"].split(":", 1)[-1])
        assert "PUSH_OK" in out, f"the racer's own publish was lost: {out}"
        assert "local telemetry commit" in remote_subjects(bare)


# =========================================== BLOCKER A: what the lock covers


class TestLockScope:
    """The lock is [first mutation → commit] and [rebase → re-push], and
    NOTHING else (audit 2026-07-16 round 3) — **AMENDED by U-hostmode
    §4.5b**: the close now widens to also cover the host write (see below)."""

    def test_the_ledger_lock_is_free_during_the_host_phase(
        self, tmp_path, monkeypatch
    ):
        """U-hostmode §4.5b **deliberately reverses** this test's original
        premise (kept out of the §2.10b census, flagged as a build-report
        exception): the old ``_serialized_on_ledger`` decorator held the
        LEDGER lock across the whole verb, which round 3 narrowed to
        [first mutation → ledger commit] — proven free during the host
        phase, as this test's name still says.

        §4.5b measured why that narrow scope is UNSOUND once a compile
        record is written inside the ledger commit: a racing producer's
        ledger commit landing between this route's OWN ledger commit and
        its host write would make `_compile_set` re-read a record set the
        compile-record's `sha256` expectation never accounted for — the
        next route would then misread the result as a hand edit it never
        made. The fix holds the LEDGER lock through the host write too
        (nested with the per-host lock, REC12/`test_lock_invariant.py`'s
        AST walker is the criterion's own Check). So the ledger lock is
        now HELD, not free, at the exact instant this test's pre-commit
        hook fires — proven the same way, from inside the HOST's own real
        pre-commit hook, that a second process now BLOCKS there."""
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        record = make_behavior(record_id="lrn-bbbb0001")
        create_record(home, record)
        commit_all(home, "record seed")

        probe_out = tmp_path / "probe-out"
        probe = tmp_path / "probe.py"
        probe.write_text(
            textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {CLI_SRC!r})
                from pathlib import Path
                from self_learn import gitops
                try:
                    with gitops.commit_lock(Path({str(home)!r}), timeout=1.0):
                        Path({str(probe_out)!r}).write_text("ACQUIRED")
                except gitops.GitOpsError:
                    Path({str(probe_out)!r}).write_text("BLOCKED")
                """
            ),
            encoding="utf-8",
        )
        hook = env.host / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            f"#!/usr/bin/env bash\n{sys.executable} {probe} || true\nexit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        verbs.route(home, "lrn-bbbb0001", dest="skill-md")
        assert probe_out.is_file(), "the host pre-commit hook never fired"
        assert probe_out.read_text() == "BLOCKED", (
            "U-hostmode §4.5b: the ledger lock must be HELD through the "
            "host write (nested with the per-host lock) — a racing "
            "producer's ledger commit landing in this window is exactly "
            "the defect r2 shipped (§4.5b), which the compile record's "
            "own `sha256`/`based_on_sha256` expectation is not immune to"
        )


class TestGitTimeouts:
    """``subprocess.run`` had NO timeout, which is why "blocking with a
    sane timeout" was fiction: a wedged git hung the caller forever
    (probed 2026-07-16: a `teach` blocked 120 s behind a hanging push and
    was still going)."""

    def _wedged_git(self, tmp_path) -> Path:
        shims = tmp_path / "wedge"
        shims.mkdir()
        shim = shims / "git"
        shim.write_text("#!/usr/bin/env bash\nsleep 30\n", encoding="utf-8")
        shim.chmod(0o755)
        return shims

    def test_a_wedged_git_raises_instead_of_hanging(self, tmp_path, monkeypatch):
        repo = tmp_path / "r"
        init_repo(repo)
        (repo / "f").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        monkeypatch.setenv("PATH", f"{self._wedged_git(tmp_path)}:{os.environ['PATH']}")
        with pytest.raises(gitops.GitOpsError) as exc:
            gitops._git(repo, "status", timeout=0.4)
        assert "exceeded" in str(exc.value)

    def test_every_network_call_is_bounded(self, tmp_path):
        """The push/pull calls must carry the NETWORK timeout, not run
        unbounded: a finite ceiling is the whole point."""
        assert gitops.GIT_NETWORK_TIMEOUT > 0
        assert gitops.GIT_LOCAL_TIMEOUT > 0
        # the lock must outlast the longest legitimate hold (pull + re-push)
        assert gitops.COMMIT_LOCK_TIMEOUT > 2 * gitops.GIT_NETWORK_TIMEOUT, (
            "a lock timeout must mean 'wedged', not merely 'busy'"
        )


# ============================ BLOCKER B: GitOpsError never reaches a traceback


class TestGitOpsErrorIsHandledEverywhere:
    """Probed 2026-07-16: with a second process merely HOLDING the commit
    lock, `reject`, `push`, `recompile` and the detached worker's
    ``_commit_run`` all died with an uncaught GitOpsError traceback. A
    contended lock is not even an error — it is a busy neighbour."""

    def _held_lock(self, tmp_path, home, monkeypatch):
        """Start a REAL second process holding the ledger's commit lock,
        and shorten the wait so the test does not sit for 150 s."""
        monkeypatch.setattr(gitops, "COMMIT_LOCK_TIMEOUT", 0.3)
        ready, release = tmp_path / "ready", tmp_path / "release"
        holder = subprocess.Popen(
            [sys.executable, "-c", lock_holder_script(home, ready, release)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert wait_for(ready), "the lock holder never started"
        return holder, release

    @pytest.mark.parametrize(
        "argv",
        [
            ["reject", "lrn-cccc0001"],
            ["defer", "lrn-cccc0001"],
            ["graduate", "lrn-cccc0001"],
        ],
    )
    def test_a_held_lock_is_a_clean_exit_not_a_traceback(
        self, tmp_path, monkeypatch, capsys, argv
    ):
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        create_record(home, make_behavior(record_id="lrn-cccc0001"))
        commit_all(home, "record seed")
        holder, release = self._held_lock(tmp_path, home, monkeypatch)
        try:
            code = cli.main(argv)  # must not raise
        finally:
            release.touch()
            holder.wait(timeout=30)
        out = capsys.readouterr()
        assert code == gitops.EXIT_GIT_FAILED, (
            f"{argv} → {code}; want the documented git-failure code, and "
            f"never a traceback.\n{out.err}"
        )
        assert "Traceback" not in out.err

    def test_recompile_survives_a_held_HOST_lock(self, tmp_path, monkeypatch):
        """`recompile` is the drift repair: it reads the ledger and writes
        HOSTS, so the lock it can block on is the HOST's — not the
        ledger's (that asymmetry is itself a consequence of the re-scope;
        the old whole-verb decorator took the ledger lock for a verb that
        does not mutate the ledger at all). `_cmd_recompile` had no
        try/except whatsoever."""
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        create_record(home, make_behavior(record_id="lrn-cccc0002"))
        commit_all(home, "record seed")
        verbs.route(home, "lrn-cccc0002", dest="skill-md")
        # force a recompile that must actually touch the host
        env.skill_md.write_text(
            env.skill_md.read_text(encoding="utf-8").replace("*(lrn-", "*(gone-"),
            encoding="utf-8",
        )
        commit_all(env.host, "hand-broken marker")

        holder, release = self._held_lock(tmp_path, env.host, monkeypatch)
        try:
            code = cli.main(["recompile"])  # must not raise
        finally:
            release.touch()
            holder.wait(timeout=30)
        assert code == gitops.EXIT_GIT_FAILED, (
            f"recompile → {code}; a held HOST lock must be a documented "
            "exit, not the uncaught traceback _cmd_recompile used to give"
        )

    def test_push_survives_a_held_lock(self, tmp_path, monkeypatch):
        """`self-learn push` had no try/except at all. Its rebase fallback
        is exactly what takes the lock now, so a held lock is precisely
        the condition it must report rather than die on."""
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        bare = bare_remote(tmp_path, home)
        clone = third_clone(tmp_path, bare)
        (clone / "other.md").write_text("b\n", encoding="utf-8")
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "machine B")
        git(clone, "push", "-q")
        (home / "local.md").write_text("a\n", encoding="utf-8")
        commit_all(home, "local")  # our push is now a real non-FF

        holder, release = self._held_lock(tmp_path, home, monkeypatch)
        try:
            code = cli.main(["push"])  # must not raise
        finally:
            release.touch()
            holder.wait(timeout=30)
        assert code == gitops.EXIT_GIT_FAILED, f"push → {code}"

    #: The one teach invocation both halves of the class use.
    _TEACH_ARGV = [
        "teach",
        "--skill",
        "s",
        "--type",
        "behavior",
        "--kind",
        "anti-pattern",
        "--trigger",
        "About to edit .storage while HA runs.",
        "--instruction",
        "Stop the container first.",
    ]

    def test_a_capture_that_cannot_commit_is_a_failure_not_an_exit_0(
        self, tmp_path, monkeypatch, capsys
    ):
        """THE probed BLOCKER: `teach` printed "created lrn-… → …/pending/
        lrn-….md", warned that "the record is written but uncommitted" —
        and **exited 0**. With H-5 there is no watcher and every other
        producer stages only its own paths, so nothing ever commits it: a
        re-clone destroys it.

        Round 7 re-points the HAZARD without weakening the assertion. A
        held lock no longer produces this state (the lock is taken before
        the write now — see the sibling test), so the state is produced the
        only way left: a real git that fails the commit. The claim under
        test is unchanged and still the strong one — never exit 0 over an
        uncommitted record, always name the repair — plus the code is now
        the one that means what happened."""
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            code = cli.main(self._TEACH_ARGV)
        finally:
            flag.unlink()
        out = capsys.readouterr()
        assert code != 0, (
            "exit 0 on an uncommitted capture — the record is one re-clone "
            f"from gone and the caller was told it succeeded.\n{out.err}"
        )
        assert code == gitops.EXIT_HALF_WRITTEN, (
            f"teach → {code}; a written-but-uncommitted record is exit 7 "
            "(written), never 6 (nothing written) — one code, one state "
            f"fact (round 7 BLOCKER 2).\n{out.err}"
        )
        assert "Traceback" not in out.err
        # the record REALLY is on disk: the message must say so, and must
        # not claim the opposite
        written = list(home.glob("skills/s/pending/lrn-*.md"))
        assert written, "the record was not written at all"
        assert "nothing was written" not in out.err, (
            "the false claim is back: the record IS written"
        )
        assert "The record IS written" in out.err
        # and it must name the exact repair
        assert "git -C" in out.err and "commit" in out.err

    def test_a_held_lock_leaves_teach_with_nothing_written(
        self, tmp_path, monkeypatch, capsys
    ):
        """The other half of the same class, and the round-7 invariant's
        payoff at the capture surface: because the lock is now taken BEFORE
        ``create_record``, a busy neighbour cannot leave a stranded record
        at all. Exit 6's promise ("nothing was written") becomes true here
        for the first time — and the ledger is left CLEAN, which is the
        fact a stranded-record class is actually about."""
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        holder, release = self._held_lock(tmp_path, home, monkeypatch)
        try:
            code = cli.main(self._TEACH_ARGV)
        finally:
            release.touch()
            holder.wait(timeout=30)
        out = capsys.readouterr()
        assert code == gitops.EXIT_GIT_FAILED, f"teach → {code}\n{out.err}"
        assert "Traceback" not in out.err
        assert not list(home.glob("skills/s/pending/lrn-*.md")), (
            "a record was written despite the lock being unavailable — the "
            "lock must open BEFORE the first mutation (round 7 invariant)"
        )
        assert not git(home, "status", "--porcelain").stdout.strip(), (
            "the ledger is dirty after a refusal that claimed to write "
            "nothing"
        )

    def test_the_detached_worker_never_dies_with_a_stack_dump(
        self, tmp_path, monkeypatch
    ):
        """``worker._commit_run`` runs in a Popen-detached process. An
        escaping GitOpsError there is a stack dump into worker.log and a
        dead run — for a condition that is not an error."""
        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        proposal = home / "skills" / "s" / "proposals" / "lrn-dddd0001.yaml"
        proposal.parent.mkdir(parents=True, exist_ok=True)
        proposal.write_text("destination: skill-md\n", encoding="utf-8")
        result = worker.RunResult(status="ok")
        result.touched = [proposal]
        result.valid_landed = 1
        holder, release = self._held_lock(tmp_path, home, monkeypatch)
        try:
            worker._commit_run(home, result)  # must not raise
        finally:
            release.touch()
            holder.wait(timeout=30)
        assert result.commit_sha is None


class TestNothingReportsSuccessOverUncommittedWork:
    """BLOCKER B (c): the sweep for other "wrote something, then reported
    success" paths. Two survivors were found and judged differently —
    which is the point of a sweep rather than a blanket rule:

    - ``telemetry._commit_flush`` — genuinely benign. The events are on
      disk and the NEXT flush commits them. Stays a warning.
    - ``miner`` landings — NOT benign, and this is its test. The miner
      advances its cursors immediately after the landing commit, so a
      failed commit means those candidates are never mined again AND
      never committed by anyone (H-5: no watcher). They sit untracked
      until a clone deletes them, over a journal entry saying ``ok``.
    """

    def test_the_miner_does_not_journal_ok_over_uncommitted_landings(
        self, tmp_path, monkeypatch
    ):
        """A REAL mining run (real reader exec via a PATH ``claude`` shim,
        real second process holding the lock) whose landing commit cannot
        happen. The candidate lands on disk, the cursors advance — the run
        must NOT call itself ok, and the CLI must not exit 0."""
        from test_miner import candidate, write_transcript, a, u

        env = make_env(tmp_path)
        home = env.ledger
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("SELF_LEARN_ACTOR", "testhost")
        transcripts = tmp_path / "transcripts"
        (transcripts / "-home-u-proj").mkdir(parents=True)
        monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(transcripts))
        miner._save_cursors({"__initialized__": "test-fixture"})
        write_transcript(transcripts, "sess-e2e", [u("work"), a("the cause")])

        # the model, shimmed via SdkBackend -> fake_claude.py's
        # shim_script scenario (U-cleanup-A) -- same heredoc-write idiom
        # the bash shim used, now interpreted by the fake CLI instead of
        # a real subprocess-cli PATH shim.
        monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "sdk")
        monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
        monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
        monkeypatch.setenv("FAKE_CLAUDE_FORCE_SCENARIO", "shim_script")
        monkeypatch.setenv(
            "CLAUDE_SHIM_SCRIPT",
            f"cat > {miner.spool_dir()}/{miner.OUTPUT_BASENAME} <<'JSON'\n"
            + json.dumps({"candidates": [candidate()], "fires": []})
            + "\nJSON\n",
        )

        # ...and a real git whose `commit` fails, so the landing commit
        # genuinely cannot happen. (Round 7: a HELD LOCK no longer produces
        # this state — the lock is now taken before `_reconcile_and_land`
        # mutates, so a busy neighbour makes the run a clean no-op instead
        # of a landing it cannot commit. The hazard is re-pointed at the
        # only cause that survives; the assertions below are unchanged.)
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            result = miner.run(home, trigger="timer")  # must not raise
        finally:
            flag.unlink()

        assert result.landed, "the run never landed a candidate — no hazard"
        assert result.status != "ok", (
            "the miner reported a clean run over candidates it never "
            "committed; the cursors have advanced, so they are never mined "
            "again and no watcher will ever commit them (H-5) — a clone "
            "deletes them"
        )
        assert result.status == "landed-uncommitted"
        entry = miner.read_journal(1)[0]
        assert entry["status"] == "landed-uncommitted", entry
        # ...and the records really ARE on disk, uncommitted. (The exact
        # porcelain code moved with the lock scope — the landing now gets
        # as far as STAGING before the commit fails, where a held lock used
        # to stop it at untracked. The claim that matters is unchanged and
        # stated directly: the record is on disk and NOT in history.)
        assert result.touched and Path(result.touched[0]).is_file()
        rel = str(Path(result.touched[0]).relative_to(home))
        assert rel not in head_files(home), (
            f"{rel} is in HEAD — the test no longer reproduces the hazard"
        )
        assert git(home, "status", "--porcelain").stdout.strip(), (
            "the ledger is clean — the landing was never written at all"
        )


# ===================================== MAJOR F: no code that cannot fire


class TestImportHasNoDeadNoPushGuard:
    """``import_common`` guarded its push on ``worker.no_push_requested()``
    under a comment about "`import --no-push`". There is no such flag, and
    the env var that function reads is only ever set on a worker/miner
    CHILD — `import` runs in the parent. The guard could not fire in any
    reachable state.

    Deleted rather than invented: adding the flag would have been adding
    product surface to justify a line of code, and nothing asks for it.
    This test pins the choice so the guard cannot drift back in without
    the flag that would make it real."""

    def test_import_really_has_no_no_push_flag(self):
        parser = cli._build_parser()
        choices = parser._subparsers._group_actions[0].choices
        options = {
            opt
            for action in choices["import"]._actions
            for opt in action.option_strings
        }
        assert "--no-push" not in options, (
            "import grew a --no-push flag — then import_common must honour "
            "it as a PARAMETER (never via worker's env var, which belongs "
            "to spawned children)"
        )

    def test_commit_import_does_not_consult_the_workers_env(self, monkeypatch):
        import inspect
        from self_learn import import_common

        src = inspect.getsource(import_common.commit_import)
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.strip().startswith("#")
        )
        body = code.split('"""')[-1]  # past the docstring
        assert "no_push_requested" not in body, (
            "a guard that cannot fire is back in commit_import"
        )


# ================================= MINOR G: one exit-code contract, unified


class TestExitCodesAreUnified:
    """`teach` pinned its OWN integers and returned EXIT_USAGE(2) for a
    bad home — "you typed the command wrong" — while all eight other
    surfaces returned 5. The codes now live beside the concepts they name
    (:mod:`ledger` / :mod:`gitops`) and every surface imports them, which
    is what stops them drifting apart again."""

    def test_a_bad_home_is_5_everywhere_including_teach(
        self, tmp_path, monkeypatch
    ):
        missing = tmp_path / "no-such-home"
        monkeypatch.setenv("SELF_LEARN_HOME", str(missing))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        teach_argv = [
            "teach", "--skill", "s", "--type", "knowledge",
            "--fact", "The router reserves .232 for the Beacon.",
        ]
        assert cli.main(teach_argv) == cli.EXIT_NO_HOME == 5, (
            "teach still answers a missing home with its own code — the "
            "one surface out of nine that disagrees"
        )
        # ...and the record must NOT have been written into the void
        assert not missing.exists() or not list(missing.rglob("lrn-*.md"))
        for argv in (["status"], ["list"], ["recompile"], ["push"]):
            assert cli.main(argv) == cli.EXIT_NO_HOME, argv

    def test_the_codes_have_exactly_one_definition(self):
        from self_learn import ledger, teach as teach_mod

        assert ledger.EXIT_NO_HOME is cli.EXIT_NO_HOME
        assert ledger.EXIT_NO_HOME == teach_mod.EXIT_NO_HOME
        assert gitops.EXIT_GIT_FAILED is cli.EXIT_GIT_FAILED
        assert gitops.EXIT_GIT_FAILED == teach_mod.EXIT_GIT_FAILED
        # and they collide with nothing else in either namespace
        assert len({0, 1, 2, 3, 4, 5, 6, 64}) == 8
        assert teach_mod.EXIT_SCAN == 3 and teach_mod.EXIT_ANALYST == 4


# ================================ MAJOR E: the no-remote guard, for ALL verbs


class TestNoRemoteGuardCoversEveryVerb:
    """doc 13 §7.1 step 5 creates a remote-less ledger ON PURPOSE (the home
    is bootstrapped and committed BEFORE its private remote exists). Every
    verb run in that window must exit 0.

    Only route/route_direct/supersede were fixed last round, and the tests
    were written to the fix rather than to the failure CLASS — so the seven
    verbs behind ``_commit_and_push`` still called ``push_with_retry``
    unguarded and exited 3 with a loud, false "PUSH FAILED" over a perfect
    commit. This is parametrized across ALL ten so the class is covered.
    """

    def _home(self, tmp_path, monkeypatch):
        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        assert not gitops.has_remote(env.ledger), "sandbox must be remote-less"
        return env

    def _pending(self, home, rid="lrn-eeee0001", scope="skill:s"):
        create_record(home, make_behavior(record_id=rid, scope=scope))
        commit_all(home, f"seed {rid}")
        return rid

    def _routed(self, home, rid):
        verbs.route(home, rid, dest="skill-md")
        return rid

    def test_reject(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        rid = self._pending(env.ledger)
        self._assert_skipped(verbs.reject(env.ledger, rid))

    def test_defer(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        rid = self._pending(env.ledger)
        self._assert_skipped(verbs.defer(env.ledger, rid))

    def test_graduate(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        rid = self._pending(env.ledger)
        self._assert_skipped(verbs.graduate(env.ledger, rid))

    def test_route(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        rid = self._pending(env.ledger)
        self._assert_skipped(verbs.route(env.ledger, rid, dest="skill-md"))

    def test_supersede(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        old = self._pending(env.ledger, "lrn-eeee0002")
        new = self._pending(env.ledger, "lrn-eeee0003")
        self._assert_skipped(verbs.supersede(env.ledger, old, new))

    def test_confirm_held(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        rid = self._routed(env.ledger, self._pending(env.ledger))
        self._assert_skipped(verbs.confirm_held(env.ledger, rid))

    def test_confirm_recurrence(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        rid = self._routed(env.ledger, self._pending(env.ledger))
        from self_learn import telemetry

        telemetry.spool_event(
            "recurrence-suspect",
            record=rid,
            origin="lrn-0000eeee",
            basis="origin-match",
        )
        telemetry.flush(env.ledger)
        nonce = next(
            e["nonce"]
            for e in telemetry.read_events(env.ledger)
            if e["kind"] == "recurrence-suspect"
        )
        self._assert_skipped(
            verbs.confirm_recurrence(env.ledger, rid, event_ref=nonce)
        )

    def test_followup_done(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        rid = self._pending(env.ledger)
        verbs.route(
            env.ledger,
            rid,
            dest="skill-md",
            follow_up={"action": "verify on the next update"},
        )
        self._assert_skipped(verbs.followup_done(env.ledger, rid))

    def test_link_contradicts(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        a = self._pending(env.ledger, "lrn-eeee0004")
        b = self._pending(env.ledger, "lrn-eeee0005")
        self._assert_skipped(verbs.link_contradicts(env.ledger, a, b))

    def test_recompile(self, tmp_path, monkeypatch):
        env = self._home(tmp_path, monkeypatch)
        self._routed(env.ledger, self._pending(env.ledger))
        # recompile has no PushResult to inspect; it must simply not blow up
        # or report a push failure on a remote-less ledger.
        result = verbs.recompile(env.ledger)
        assert not [w for w in result.warnings if "PUSH" in w.upper()]

    def _assert_skipped(self, result):
        assert result.push is not None, "the verb did not attempt a push at all"
        assert result.push.ok, f"false failure on a remote-less ledger: {result.push}"
        assert result.push.skipped, (
            "the push was ATTEMPTED against a ledger with no remote — that is "
            "the exit-3 'PUSH FAILED' over a perfect commit (doc 13 §7.1 "
            "step 5 creates exactly this window)"
        )
        assert result.push.exit_code == 0


# ============================== BLOCKER D: --no-push must survive every spawn


class TestNoPushSurvivesSpawns:
    """``--no-push`` used to be AMBIENT (an env var read wherever someone
    remembered), and the miner watchdog proved the ambience was not there:
    ``cli.py`` ticks ``miner.maybe_kick`` before EVERY command except
    `mine`, ``miner._spawn_run`` Popen'd with **no env= at all**, and
    nothing set SELF_LEARN_NO_PUSH in the parent's own environ (worker.py
    builds it into the WORKER child's env dict only). Probed: ``reject
    --no-push`` → watchdog spawns a miner → child sees no var → pushes the
    whole branch. It is a parameter now; the env var survives only at the
    process boundary that has no other channel."""

    def test_the_miner_spawn_carries_no_push_to_a_real_child(self, tmp_path):
        """A REAL spawned child, observed through its own ``/proc/<pid>/
        environ`` — ``_spawn_run``'s Popen had no ``env=`` at all, so this
        is the regression, read straight off the kernel's copy.

        The child is made observably ALIVE first (a ``claude`` PATH shim
        that sleeps, so the real miner run blocks in the reader): reading
        /proc of a child racing to exit is how a test earns an
        intermittent green."""
        env = make_env(tmp_path)
        cache = tmp_path / "cache"
        shims = tmp_path / "slow-reader"
        shims.mkdir()
        (shims / "claude").write_text(
            "#!/usr/bin/env bash\ncat > /dev/null\nsleep 10\n", encoding="utf-8"
        )
        (shims / "claude").chmod(0o755)
        transcripts = tmp_path / "transcripts"
        (transcripts / "-home-u-proj").mkdir(parents=True)
        (transcripts / "-home-u-proj" / "sess-1.jsonl").write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "work"}],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        child_env = {
            **os.environ,
            "PATH": f"{shims}:{os.environ['PATH']}",
            "XDG_CACHE_HOME": str(cache),
            "SELF_LEARN_HOME": str(env.ledger),
            "SELF_LEARN_TRANSCRIPTS_DIR": str(transcripts),
        }
        script = f"""
            import os, sys, time
            sys.path.insert(0, {CLI_SRC!r})
            from pathlib import Path
            from self_learn import miner
            miner._save_cursors({{"__initialized__": "test"}})
            pid = miner._spawn_run(Path({str(env.ledger)!r}), no_push=True)
            environ = b""
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    environ = Path(f"/proc/{{pid}}/environ").read_bytes()
                except OSError:
                    environ = b""
                if environ:
                    break
                time.sleep(0.02)
            print("ALIVE" if environ else "CHILD_GONE")
            print("SEEN" if b"SELF_LEARN_NO_PUSH=1" in environ else "MISSING")
            os.kill(pid, 9)
        """
        proc = run_child(script, env=child_env)
        assert "ALIVE" in proc.stdout, (
            f"could not observe the child at all: {proc.stdout}{proc.stderr}"
        )
        assert "SEEN" in proc.stdout, (
            "the spawned miner child did not inherit --no-push — the flag is "
            f"a lie the moment the watchdog fires.\n{proc.stdout}{proc.stderr}"
        )

    def test_the_watchdog_tick_passes_the_verbs_flag(self, tmp_path, monkeypatch):
        """The leak's actual route: the tick happens in ``cli.main`` BEFORE
        dispatch, so it must be handed the parsed verb's flag."""
        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "1")
        create_record(env.ledger, make_behavior(record_id="lrn-ffff0001"))
        commit_all(env.ledger, "seed")

        seen: list[bool] = []
        real_spawn = miner._spawn_run
        monkeypatch.setattr(
            miner, "_spawn_run", lambda h, **kw: seen.append(kw.get("no_push")) or 1
        )
        cli.main(["reject", "lrn-ffff0001", "--no-push"])
        assert seen == [True], (
            "the watchdog spawned a miner that was never told about "
            f"--no-push (got {seen}) — it publishes the whole branch"
        )
        assert real_spawn is not None

    def test_the_worker_spawn_carries_no_push_to_a_real_child(self, tmp_path):
        """The worker path (the one that WAS fixed) must STAY fixed — the
        same real-child observation, so both spawn paths are covered by
        the same standard. The child is held alive by its own coalesce
        window rather than by a shim."""
        env = make_env(tmp_path)
        child_env = {
            **os.environ,
            "XDG_CACHE_HOME": str(tmp_path / "cache-w"),
            "SELF_LEARN_HOME": str(env.ledger),
            "SELF_LEARN_COALESCE_SECS": "10",  # the child sleeps; we can look
        }
        script = f"""
            import os, sys, time
            sys.path.insert(0, {CLI_SRC!r})
            from pathlib import Path
            from self_learn import worker
            pid = worker._spawn_window(Path({str(env.ledger)!r}), no_push=True)
            environ = b""
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    environ = Path(f"/proc/{{pid}}/environ").read_bytes()
                except OSError:
                    environ = b""
                if environ:
                    break
                time.sleep(0.02)
            print("ALIVE" if environ else "CHILD_GONE")
            print("SEEN" if b"SELF_LEARN_NO_PUSH=1" in environ else "MISSING")
            os.kill(pid, 9)
        """
        proc = run_child(script, env=child_env)
        assert "ALIVE" in proc.stdout, (
            f"could not observe the child at all: {proc.stdout}{proc.stderr}"
        )
        assert "SEEN" in proc.stdout, f"{proc.stdout}{proc.stderr}"

    def test_no_push_is_a_parameter_not_ambience(self, tmp_path, monkeypatch):
        """``miner.run``/``worker.run`` must honour an EXPLICIT no_push even
        when the environment says nothing — the property that makes the
        policy data rather than ambience."""
        assert "no_push" in miner.run.__code__.co_varnames
        assert "no_push" in worker.run.__code__.co_varnames
        monkeypatch.delenv(worker.NO_PUSH_ENV, raising=False)
        assert worker.no_push_requested() is False
