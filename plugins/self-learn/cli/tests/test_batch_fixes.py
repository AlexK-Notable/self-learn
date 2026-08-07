"""Regression tests for the 2026-07-16 re-review of the doc-13 fix batch.

The batch that fixed the hosting audit minted four blockers of its own, and
every one was INVISIBLE to a single-process ``cli.main()`` test — which is
exactly how they shipped past a green 644-test suite. So these tests
exercise the real surface:

- BLOCKER 1 EXECUTES the hook shell script in a subprocess (no test had
  ever run it; the warning it exists to print was dead code under
  ``set -e``).
- BLOCKER 3 spawns the REAL detached worker against a REAL bare remote (the
  suite disables autokick globally, so the leak was unobservable).
- BLOCKER 4 runs a REAL second process committing concurrently (one process
  cannot race itself).
- BLOCKER 2 is single-process, but asserts against the DOCUMENTED exit
  contract in commands/teach.md §5 rather than the code's behavior.

Same idioms as test_hosting.py / test_hosting_fixes.py: real git sandboxes
under pytest tmpdirs, no mocks, and no contact with the real
~/.self-learn, ~/repos/claude-skills, or ~/.claude.
"""

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from self_learn import cli, gitops, verbs, worker
from self_learn.ledger_ops import create_record
from support import commit_all, git, init_repo, make_behavior, make_env


#: <repo>/plugins — tests/ → cli/ → self-learn/ → plugins/
PLUGINS_ROOT = Path(__file__).resolve().parents[3]
HOOK = PLUGINS_ROOT / "self-learn" / "hooks" / "self-learn-pending.sh"
CLI_SRC = PLUGINS_ROOT / "self-learn" / "cli" / "src"


# ------------------------------------------------------------------ helpers


def bare_remote(tmp_path: Path, repo: Path, name: str = "origin") -> Path:
    """A real bare remote wired as *repo*'s upstream — the only way to
    observe what a push actually published."""
    remote = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)], check=True
    )
    git(repo, "remote", "add", name, str(remote))
    git(repo, "push", "-q", "-u", name, "HEAD")
    return remote


def remote_log(remote: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(remote), "log", "--format=%s", "--all"],
        capture_output=True,
        text=True,
    ).stdout


def remote_files(remote: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout


# ========================================================== BLOCKER 1: hook


class TestHookHomeWarning:
    """The SessionStart hook's home warning was DEAD CODE, and the hook
    itself regressed from exit 0 to exit 5.

    ``set -euo pipefail`` (line 18) + ``out="$(self-learn status --fast)"``
    (line 25): the CLI exits 5 for a missing / not-a-repo home, so ``set
    -e`` killed the script ON THAT ASSIGNMENT — before the warning at lines
    32-36 that doc 13 §7.1 B-1 exists to print. A SessionStart hook must
    never fail the session, and this one failed it in precisely the state
    it was written to explain.

    These tests EXECUTE the script (PATH-shimmed `self-learn` + real jq).
    No test in the suite had ever run it — that is why the bug shipped.
    """

    def _shim(self, tmp_path: Path, home: Path) -> dict:
        """A PATH with a real `self-learn` shim that carries SELF_LEARN_HOME
        into the CLI, plus the real jq the hook needs."""
        bin_dir = tmp_path / "shim-bin"
        bin_dir.mkdir(exist_ok=True)
        src = CLI_SRC
        shim = bin_dir / "self-learn"
        shim.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                export PYTHONPATH="{src}"
                export SELF_LEARN_HOME="{home}"
                exec {sys.executable} -m self_learn.cli "$@"
                """
            ),
            encoding="utf-8",
        )
        shim.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SELF_LEARN_HOME"] = str(home)
        env["XDG_CACHE_HOME"] = str(tmp_path / "hook-cache")
        env.pop("SELF_LEARN_WORKER_AUTOKICK", None)
        return env

    def _run(self, tmp_path: Path, home: Path):
        assert HOOK.is_file(), f"hook not found at {HOOK}"
        return subprocess.run(
            ["bash", str(HOOK)],
            capture_output=True,
            text=True,
            env=self._shim(tmp_path, home),
            timeout=60,
        )

    def test_missing_home_warns_and_exits_zero(self, tmp_path):
        """The live failure mode doc 13 §7.1 B-1 names: home `missing` →
        CLI exit 5 → (before the fix) hook exit 5 and NO warning."""
        proc = self._run(tmp_path, tmp_path / "missing")
        assert proc.returncode == 0, (
            "a SessionStart hook must never fail the session; got "
            f"rc={proc.returncode}\nstderr={proc.stderr}"
        )
        assert "ledger home" in proc.stdout
        assert "missing" in proc.stdout
        assert "NOT an empty ledger" in proc.stdout

    def test_not_a_repo_home_warns_and_exits_zero(self, tmp_path):
        home = tmp_path / "not-a-repo"
        home.mkdir()
        proc = self._run(tmp_path, home)
        assert proc.returncode == 0, f"rc={proc.returncode}\n{proc.stderr}"
        assert "not-a-repo" in proc.stdout
        assert "ledger home" in proc.stdout

    def test_uninitialized_home_warns_and_exits_zero(self, tmp_path):
        home = tmp_path / "uninit"
        init_repo(home)
        (home / "README").write_text("x", encoding="utf-8")
        commit_all(home, "seed")
        proc = self._run(tmp_path, home)
        assert proc.returncode == 0, f"rc={proc.returncode}\n{proc.stderr}"
        assert "uninitialized" in proc.stdout
        assert "ledger home" in proc.stdout

    def test_healthy_home_still_prints_pending_and_exits_zero(self, tmp_path):
        """The fix must not cost the hook its normal job."""
        env = make_env(tmp_path)
        home = env.ledger
        create_record(home, make_behavior(record_id="lrn-aaaabbbb"))
        commit_all(home, "record")

        proc = self._run(tmp_path, home)
        assert proc.returncode == 0, f"rc={proc.returncode}\n{proc.stderr}"
        assert "📥 self-learn: 1 pending" in proc.stdout
        assert "/self-learn:review" in proc.stdout
        # …and the home warning must NOT fire for a good home.
        assert "NOT an empty ledger" not in proc.stdout

    def test_hook_exits_zero_when_cli_is_absent(self, tmp_path):
        """The pre-existing guard still holds (no self-learn on PATH).

        NB: bash is invoked by ABSOLUTE path and PATH points at an empty
        dir — a PATH of "/nonexistent" hides `bash` itself, and the 127
        that produces comes from exec, never from the hook."""
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        bash = shutil.which("bash")
        assert bash, "bash is required to run the hook"
        proc = subprocess.run(
            [bash, str(HOOK)],
            capture_output=True,
            text=True,
            env={"PATH": str(empty), "HOME": str(tmp_path)},
            timeout=60,
        )
        assert proc.returncode == 0, f"rc={proc.returncode}\n{proc.stderr}"
        assert proc.stdout.strip() == ""


# ================================================ BLOCKER 2: teach exit codes


class TestTeachRoutePushExitCodes:
    """`teach --route` that commits but fails to PUSH must exit 0.

    The batch added ``return push.exit_code`` — but ``gitops.
    EXIT_PUSH_FAILED == 3 == teach.EXIT_SCAN`` and ``gitops.
    EXIT_REBASE_CONFLICT == 4 == teach.EXIT_ANALYST``. commands/teach.md §5
    tells the agent 3 = "secret scan refused → re-run with --redact" and
    4 = "record safely captured to pending/, nothing lost" — both
    catastrophically wrong for a record that DID route and compile.

    The pin (08 §1 / teach.py's own module docstring): "A route that
    commits but fails to push still exits 0: the commit is kept, the push
    failure is loud, and `self-learn push` retries it."
    """

    def _break_remote(self, repo: Path, tmp_path: Path, name: str = "origin"):
        """A configured-but-unreachable remote: push fails, and the
        pull --rebase --autostash retry fails too."""
        git(repo, "remote", "add", name, str(tmp_path / "nope.git"))

    def _teach_route(self, home, extra=()):
        args = [
            "teach",
            "--skill",
            "s",
            "--trigger",
            "About to edit .storage while HA runs.",
            "--instruction",
            "Stop the container first.",
            "--route",
            "--dest",
            "skill-md",
            *extra,
        ]
        return cli.main(args)

    def test_ledger_push_failure_exits_zero_and_routes(
        self, tmp_path, monkeypatch, capsys
    ):
        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        self._break_remote(env.ledger, tmp_path)

        code = self._teach_route(env.ledger)
        out = capsys.readouterr()

        assert code == 0, (
            "documented pin: a route that commits but fails to push exits 0 "
            f"(3 means 'scan refused', 4 means 'captured to pending'); got {code}"
        )
        # The failure is LOUD…
        assert "PUSH FAILED" in out.out + out.err
        # …and names the retry command.
        assert "self-learn push" in out.out + out.err
        # …and the record really routed AND compiled.
        assert "routed lrn-" in out.out
        assert "(lrn-" in env.skill_md.read_text(encoding="utf-8")
        resolved = list((env.ledger / "skills" / "s" / "resolved").glob("*.md"))
        assert len(resolved) == 1

    def test_host_push_failure_exits_zero_and_routes(
        self, tmp_path, monkeypatch, capsys
    ):
        """The HOST phase half — same collision, same pin."""
        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        self._break_remote(env.host, tmp_path)

        code = self._teach_route(env.ledger)
        out = capsys.readouterr()

        assert code == 0, f"host push failure must not exit {code}"
        assert "PUSH FAILED" in out.out + out.err
        assert "self-learn push" in out.out + out.err
        assert "(lrn-" in env.skill_md.read_text(encoding="utf-8")

    def test_route_verb_push_exit_code_is_unchanged(
        self, tmp_path, monkeypatch, capsys
    ):
        """M4's folding was CORRECT for the `route` verb, where
        push-failure=3 is the established meaning. Confirm this fix did not
        leak into it."""
        env = make_env(tmp_path)
        monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
        record = make_behavior(record_id="lrn-ccccdddd")
        create_record(env.ledger, record)
        commit_all(env.ledger, "record")
        self._break_remote(env.ledger, tmp_path)

        code = cli.main(["route", record.id, "--dest", "skill-md"])
        capsys.readouterr()
        assert code == gitops.EXIT_PUSH_FAILED == 3, (
            "the route VERB keeps its distinct push-failure exit"
        )


# ============================================== BLOCKER 3: --no-push leak


class TestNoPushBindsSpawnedWorker:
    """`--no-push` was defeated by the worker teach itself spawns.

    ``cli._kick_after_capture`` → ``worker.kick`` → detached
    ``Popen(start_new_session=True)``; that worker ends with
    ``telemetry.flush(home)`` (default push=True) and ``_commit_run`` →
    ``push_with_retry`` — and ``git push`` publishes the WHOLE branch,
    including the commit the user said keep local. NEW in this batch: at
    43f8abe the worker never pushed.

    Real processes, real bare remote: the existing tests all disable
    autokick, which is exactly why this was invisible.
    """

    def _wait_for_worker(self, home: Path, timeout: float = 90.0) -> None:
        """Block until the detached worker window has really exited.

        NOT via worker._pid_alive: that child is spawned by Popen from THIS
        process, so on exit it becomes a ZOMBIE until someone reaps it —
        and os.kill(pid, 0) keeps succeeding for a zombie, so _pid_alive
        would report it alive forever. Reap it with waitpid instead.
        """
        # cache_dir() is namespaced per ledger home (doc 13 §6, H-4):
        # …/self-learn/home-<sha256(home)[:8]>/ — never $XDG/self-learn.
        window = worker.cache_dir() / "worker.window"
        deadline = time.monotonic() + timeout
        while not window.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert window.is_file(), "no worker window was ever opened"
        pid = int(window.read_text(encoding="utf-8").strip())
        while time.monotonic() < deadline:
            try:
                done, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return  # already reaped by subprocess's internal cleanup
            if done == pid:
                return
            time.sleep(0.02)
        raise AssertionError("detached worker did not finish in time")

    def test_teach_no_push_kicked_worker_does_not_publish(
        self, tmp_path, monkeypatch, capsys
    ):
        """END-TO-END, real detached process, real bare remote.

        The reachable shape (verified 2026-07-16): `--no-push` is rejected
        without `--route`, and a SUCCESSFUL `teach --route` never kicks —
        so the one live path where a --no-push verb spawns a worker is a
        `teach --route --no-push` whose route FAILS: the record falls back
        to pending/ (exit 4) and cli.main kicks on exactly that code.
        The kicked worker then commits its proposal and `git push`es the
        WHOLE branch — publishing the record the user said keep local.

        `claude` is a PATH shim (never the real model): the detached child
        inherits PATH via the env we hand Popen.
        """
        env = make_env(tmp_path)
        home = env.ledger
        remote = bare_remote(tmp_path, home)

        # Autokick ENABLED — the suite-wide default disables it, which is
        # exactly why this leak was invisible. Coalesce 0.
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)
        monkeypatch.setenv("SELF_LEARN_COALESCE_SECS", "0")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "kick-cache"))
        monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
        monkeypatch.delenv(worker.NO_PUSH_ENV, raising=False)

        # A `claude` shim that writes a valid proposal for whatever landed
        # in user/pending — giving the worker real work to commit + push.
        shims = tmp_path / "shims"
        shims.mkdir()
        proposals = home / "user" / "proposals"
        shim = shims / "claude"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            "cat > /dev/null || true\n"
            f"mkdir -p '{proposals}'\n"
            f"for f in '{home}'/user/pending/lrn-*.md; do\n"
            '  [ -e "$f" ] || continue\n'
            '  rid=$(basename "$f" .md)\n'
            f"  cat > '{proposals}'/\"$rid\".yaml <<'YAML'\n"
            "destination: claude-md\n"
            "alternates: [reference]\n"
            'rationale: "shim-written proposal"\n'
            "already_canon: false\n"
            "model: claude-sonnet-5\n"
            'analyzed_at: "2026-07-15T00:00:00Z"\n'
            "card:\n"
            '  headline: "A test headline."\n'
            '  impact: "Next time Claude does X it will Y."\n'
            '  discuss: "Nothing contentious."\n'
            "YAML\n"
            "done\n"
            "exit 0\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")

        before = remote_log(remote)

        # user scope + reference dest is an unroutable pair (S-23 (2):
        # user scope has no reference shelf) → route fails → record
        # captured to pending → exit 4 → worker kick.
        code = cli.main(
            [
                "teach",
                "--user",
                "--trigger",
                "When about to edit .storage while HA runs.",
                "--instruction",
                "Stop the container first.",
                "--route",
                "--dest",
                "reference",
                "--no-push",
            ]
        )
        out = capsys.readouterr()
        assert code == 4, f"expected the pending fallback; got {code}\n{out.err}"
        assert remote_log(remote) == before, "the VERB pushed despite --no-push"

        self._wait_for_worker(home)

        log_path = worker.cache_dir() / "worker.log"
        wlog = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
        assert "run:" in wlog, f"the detached worker never ran:\n{wlog}"

        after = remote_log(remote)
        assert after == before, (
            "--no-push means this invocation AND anything it spawns: the "
            f"kicked worker published what the user kept local.\nworker.log:\n"
            f"{wlog}\nremote now:\n{after}"
        )
        assert "pending/lrn-" not in remote_files(remote)

    def test_no_push_env_propagates_to_spawned_child(self, tmp_path, monkeypatch):
        """The mechanism, directly: kick(no_push=True) must put
        SELF_LEARN_NO_PUSH=1 in the DETACHED child's env — the child cannot
        inherit the flag any other way."""
        home = make_env(tmp_path).ledger
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "env-cache"))
        monkeypatch.delenv("SELF_LEARN_WORKER_AUTOKICK", raising=False)
        monkeypatch.delenv(worker.NO_PUSH_ENV, raising=False)

        seen: dict = {}

        def fake_popen(argv, **kwargs):
            seen.update(kwargs.get("env") or {})

            class P:
                pid = os.getpid()  # "alive", so no real process leaks

            return P()

        monkeypatch.setattr(worker.subprocess, "Popen", fake_popen)
        worker._spawn_window(home, no_push=True)
        assert seen.get(worker.NO_PUSH_ENV) == "1"

        seen.clear()
        worker._spawn_window(home, no_push=False)
        assert worker.NO_PUSH_ENV not in seen

    def test_no_push_requested_is_honored_by_run_end_flush(
        self, tmp_path, monkeypatch
    ):
        """The receiving half: with SELF_LEARN_NO_PUSH=1 set, a telemetry
        flush commits but never pushes."""
        home = make_env(tmp_path).ledger
        remote = bare_remote(tmp_path, home)
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))
        monkeypatch.setenv(worker.NO_PUSH_ENV, "1")

        from self_learn import telemetry

        telemetry.spool_quiet("capture", source="teach", scope="user")
        before = remote_log(remote)
        telemetry.flush(home, push=not worker.no_push_requested())

        assert "telemetry flush" in git(
            home, "log", "--format=%s"
        ).stdout, "the flush must still COMMIT (H-5) — only the push waits"
        assert remote_log(remote) == before, "no-push flush published anyway"


# ========================================== BLOCKER 4: whole-index commit race


class TestCommitRaceAndPathspec:
    """``gitops.commit`` was ``git commit -q -m <msg>`` with NO pathspec:
    everything staged by ANY process landed in whichever commit fired
    first. At 43f8abe the ledger had one committer class (sequential
    foreground verbs); M3 added two background committers into the same
    repo (the worker, Popen-detached, kicked by every teach/import; the
    nightly miner). ``sentinel.hold()`` is advisory (a pre-existing hold
    returns owned=False and the caller CONTINUES) and ``worker.lock``
    excludes worker-vs-worker only — nothing serialized
    background-vs-foreground.

    The severe interleave: ``resolve_record``'s ``git mv`` stages the
    rename immediately; a racing ``telemetry.flush`` commits it under
    ``self-learn: telemetry flush N events``; the verb's own ``commit()``
    then raises "nothing to commit" — the record is resolved but its pinned
    ``self-learn: reject …`` subject NEVER enters history (H-6; doc 13 §1
    Q3 calls that history load-bearing — the digest greps
    ``^self-learn: reject ``), and the verb reports failure for a
    half-succeeded op.

    SCOPE OF THIS CLASS (corrected 2026-07-16, round 3): everything here
    exercises the PATHSPEC layer, including the "racing committer" test —
    see its docstring. The LOCK's distinct guarantee lives in
    ``test_round3_fixes.py::TestRebaseAutostashRace``; the two flock unit
    tests below only prove flock is flock.
    """

    # ------------------------------------------------ layer (b): pathspec

    def test_pathspec_commit_excludes_a_foreign_staged_file(self, tmp_path):
        """A foreign staged file must NOT be swept into a scoped commit."""
        repo = tmp_path / "r"
        init_repo(repo)
        (repo / "mine.md").write_text("mine\n", encoding="utf-8")
        (repo / "foreign.md").write_text("theirs\n", encoding="utf-8")
        commit_all(repo, "seed")

        (repo / "mine.md").write_text("mine v2\n", encoding="utf-8")
        (repo / "foreign.md").write_text("theirs v2\n", encoding="utf-8")
        git(repo, "add", "-A")  # BOTH staged, as a racing producer would

        sha = gitops.commit(repo, "self-learn: scoped", paths=[repo / "mine.md"])
        files = git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha
        ).stdout.split()
        assert files == ["mine.md"], f"foreign file swept in: {files}"
        # and the foreign work is left staged, not destroyed
        assert "foreign.md" in git(repo, "diff", "--cached", "--name-only").stdout

    def test_pathspec_carries_both_halves_of_a_git_mv_rename(self, tmp_path):
        """git mv-staged renames need BOTH old and new paths in the
        pathspec (probed 2026-07-16: naming only the new half commits the
        addition and ORPHANS the deletion in the index)."""
        repo = tmp_path / "r"
        init_repo(repo)
        (repo / "pending").mkdir()
        (repo / "resolved").mkdir()
        (repo / "pending" / "rec.md").write_text("a\n", encoding="utf-8")
        commit_all(repo, "seed")

        git(repo, "mv", "pending/rec.md", "resolved/rec.md")
        sha = gitops.commit(
            repo,
            "self-learn: reject lrn-deadbeef",
            paths=[repo / "pending" / "rec.md", repo / "resolved" / "rec.md"],
        )
        status = git(
            repo, "diff-tree", "--no-commit-id", "-r", "-M", "--name-status", sha
        ).stdout
        assert "R" in status.split()[0], f"rename not committed whole: {status}"
        # nothing left dangling in the index
        assert git(repo, "diff", "--cached", "--name-only").stdout.strip() == ""

    def test_known_paths_drops_never_tracked_absent_paths(self, tmp_path):
        """A pathspec naming a never-tracked absent path makes git fail the
        WHOLE commit, so such paths must be filtered out, while the git
        mv-ed old path (HEAD-only) must be kept."""
        repo = tmp_path / "r"
        init_repo(repo)
        (repo / "pending").mkdir()
        (repo / "pending" / "rec.md").write_text("a\n", encoding="utf-8")
        commit_all(repo, "seed")
        git(repo, "mv", "pending/rec.md", "rec.md")

        kept = gitops.known_paths(
            repo,
            [
                repo / "pending" / "rec.md",  # gone from worktree AND index
                repo / "rec.md",  # exists
                repo / "ghost.md",  # never existed
            ],
        )
        assert str(repo / "pending" / "rec.md") in kept, "HEAD-only path dropped"
        assert str(repo / "rec.md") in kept
        assert str(repo / "ghost.md") not in kept

    # ---------------------------------------------------- layer (a): lock

    def test_commit_lock_is_reentrant_within_one_process(self, tmp_path):
        """Verbs hold the lock across helpers that take it again; flock
        would otherwise self-deadlock on a second fd."""
        repo = tmp_path / "r"
        init_repo(repo)
        (repo / "f").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")
        with gitops.commit_lock(repo, timeout=5):
            with gitops.commit_lock(repo, timeout=5):
                pass  # must not hang

    def test_commit_lock_excludes_a_real_second_process(self, tmp_path):
        """The lock must actually be cross-process (flock, not a flag)."""
        repo = tmp_path / "r"
        init_repo(repo)
        (repo / "f").write_text("x", encoding="utf-8")
        commit_all(repo, "seed")

        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(CLI_SRC)!r})
            from pathlib import Path
            from self_learn import gitops
            try:
                with gitops.commit_lock(Path({str(repo)!r}), timeout=0.3):
                    print("ACQUIRED")
            except gitops.GitOpsError:
                print("BLOCKED")
            """
        )
        with gitops.commit_lock(repo, timeout=5):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=60,
            )
        assert "BLOCKED" in proc.stdout, (
            f"a second PROCESS took the lock we hold: {proc.stdout}{proc.stderr}"
        )

    def test_two_concurrent_committers_files_never_mix(
        self, tmp_path, monkeypatch
    ):
        """The PATHSPEC layer (b), under a real concurrent committer.

        RENAMED 2026-07-16 (round-3 audit, BLOCKER C). This test was called
        ``test_verb_subject_always_lands_despite_a_racing_committer`` and
        was believed to cover the commit LOCK. It does not, and never did:
        reverting ``commit_lock`` to a no-op leaves it green, because the
        racer inside it also passes ``paths=[…]`` — so what it actually
        forces is two PATHSPEC-scoped committers interleaving, which is
        layer (b)'s job and layer (b) handles it. A test whose name
        overclaims is worse than no test: this suite spent a round
        believing the lock was covered.

        The lock's own guarantee — the ``pull --rebase --autostash``
        hazard, which no pathspec can survive — is proven in
        ``test_round3_fixes.py::TestRebaseAutostashRace``.

        What this DOES prove, and is worth keeping: (1) the verb's pinned
        subject lands in history, (2) no commit ever carries another
        producer's files, (3) ``git log --grep '^self-learn: reject '``
        finds the reject (H-6 / doc 13 §1 Q3 make that grep load-bearing).

        Mechanism note: the window is held open with a real ``pre-commit``
        hook. Probed in round 3 — for a PATHSPEC commit git holds
        index.lock across that hook, which is precisely why a racing
        autostash cannot be demonstrated from here, and why the round-3
        test instruments ``git mv`` instead.
        """
        rounds = 3
        for i in range(rounds):
            env = make_env(tmp_path / f"round{i}")
            home = env.ledger
            monkeypatch.setenv("SELF_LEARN_HOME", str(home))

            record = make_behavior(record_id=f"lrn-aaaa{i:04d}")
            create_record(home, record)
            racer_file = home / "telemetry" / "events.jsonl"
            racer_file.parent.mkdir(parents=True, exist_ok=True)
            racer_file.write_text('{"kind":"capture"}\n', encoding="utf-8")
            commit_all(home, "record + telemetry seed")

            go = tmp_path / f"go{i}"
            racer_done = tmp_path / f"racer-done{i}"
            fired = tmp_path / f"fired{i}"

            # The racer: a REAL process. It waits for the hook's GO, then
            # stages + commits its own file exactly as telemetry.flush does.
            script = textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(CLI_SRC)!r})
                from pathlib import Path
                from self_learn import gitops
                home, f = Path({str(home)!r}), Path({str(racer_file)!r})
                go, done = Path({str(go)!r}), Path({str(racer_done)!r})
                deadline = time.monotonic() + 30
                while not go.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                f.write_text('{{"kind":"capture","n":2}}\\n')
                try:
                    with gitops.commit_lock(home):
                        gitops.stage(home, [f])
                        gitops.commit(
                            home,
                            "self-learn: telemetry flush 3 events",
                            paths=[f],
                        )
                finally:
                    done.touch()
                """
            )

            # The pre-commit hook: fires once, inside the VERB's commit,
            # with the rename already staged. Releases the racer, then
            # waits a BOUNDED time for it. Under the commit lock the racer
            # is blocked and this simply times out — which is the point.
            hook = home / ".git" / "hooks" / "pre-commit"
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text(
                "#!/usr/bin/env bash\n"
                f"[ -f '{fired}' ] && exit 0\n"   # racer's own commit: no-op
                f"touch '{fired}'\n"
                f"touch '{go}'\n"
                f"for _ in $(seq 1 150); do\n"
                f"  [ -f '{racer_done}' ] && break\n"
                "  sleep 0.01\n"
                "done\n"
                "exit 0\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)

            racer = subprocess.Popen(
                [sys.executable, "-c", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                verbs.reject(home, record.id, note="nope", no_push=True)
            finally:
                go.touch()  # never strand the racer if the verb refused
                racer.wait(timeout=60)

            log = git(home, "log", "--format=%s").stdout

            # (1) + (3): the pinned subject IS in history.
            grep = git(
                home, "log", "--format=%s", "--grep", "^self-learn: reject "
            ).stdout
            assert f"self-learn: reject {record.id}" in grep, (
                f"round {i}: the verb's pinned subject never entered history "
                f"— H-6 / doc 13 §1 Q3 make it load-bearing (the digest greps "
                f"'^self-learn: reject ').\nlog:\n{log}"
            )

            # (2) no commit carries another producer's files.
            reject_sha = git(
                home, "log", "--format=%H", "--grep", "^self-learn: reject "
            ).stdout.split()[0]
            reject_files = git(
                home, "diff-tree", "--no-commit-id", "--name-only", "-r", reject_sha
            ).stdout.split()
            assert reject_files, f"round {i}: empty reject commit"
            assert not any("telemetry/" in f for f in reject_files), (
                f"round {i}: the reject commit swept the racer's file: "
                f"{reject_files}"
            )
            for sha in git(
                home, "log", "--format=%H", "--grep", "^self-learn: telemetry flush"
            ).stdout.split():
                files = git(
                    home, "diff-tree", "--no-commit-id", "--name-only", "-r", sha
                ).stdout.split()
                assert all("telemetry/" in f for f in files), (
                    f"round {i}: a telemetry flush commit absorbed the verb's "
                    f"record files: {files}"
                )


# ============================== MAJOR 5: recompile/push silent all-clear


class TestRepairCommandsHomeGate:
    """`recompile` — the ADVERTISED drift repair — printed "no managed
    targets (no routed records)" and exited 0 against a missing home: the
    repair command telling a user with real drift that everything is fine
    (the exact B-11 silent all-clear). `self-learn push` died with an
    uncaught GitOpsError traceback.
    """

    @pytest.mark.parametrize("state", ["missing", "not-a-repo"])
    def test_recompile_is_loud_and_nonzero(
        self, tmp_path, monkeypatch, capsys, state
    ):
        home = tmp_path / state
        if state == "not-a-repo":
            home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        code = cli.main(["recompile"])
        out = capsys.readouterr()

        assert code == cli.EXIT_NO_HOME == 5, f"got {code}"
        assert "no managed targets" not in out.out, (
            "the repair command must never render a confident all-clear for a "
            "ledger it cannot see"
        )
        assert "ledger home" in out.err
        assert "Traceback" not in out.err

    @pytest.mark.parametrize("state", ["missing", "not-a-repo"])
    def test_push_is_loud_and_nonzero_without_a_traceback(
        self, tmp_path, monkeypatch, capsys, state
    ):
        home = tmp_path / state
        if state == "not-a-repo":
            home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        code = cli.main(["push"])
        out = capsys.readouterr()

        assert code == cli.EXIT_NO_HOME == 5, f"got {code}"
        assert "ledger home" in out.err
        assert "Traceback" not in out.err

    # The commit lock (BLOCKER 4) is taken at the VERB boundary, so a
    # missing / not-a-repo home now raises GitOpsError inside the verb —
    # which _cmd_verb/_cmd_followup/_cmd_link do not catch. Found
    # 2026-07-16 by running the verbs against a missing home: the fix batch
    # for BLOCKER 4 turned "no such record" into an uncaught TRACEBACK, and
    # the suite stayed green because nothing had ever driven this surface.
    # Before the lock these came back rc=2 "no record lrn-…" — which was
    # its own B-11 sin: blaming the ID for a home nobody could see.
    @pytest.mark.parametrize(
        "argv",
        [
            ["reject", "lrn-12345678"],
            ["route", "lrn-12345678", "--dest", "skill-md"],
            ["defer", "lrn-12345678"],
            ["graduate", "lrn-12345678"],
            ["supersede", "lrn-11111111", "lrn-22222222"],
            ["confirm-held", "lrn-12345678"],
            ["followup", "done", "lrn-12345678"],
            ["link", "contradicts", "lrn-12345678", "lrn-87654321"],
        ],
    )
    @pytest.mark.parametrize("state", ["missing", "not-a-repo"])
    def test_write_verbs_are_loud_not_tracebacks_on_a_bad_home(
        self, tmp_path, monkeypatch, capsys, argv, state
    ):
        home = tmp_path / state
        if state == "not-a-repo":
            home.mkdir()
        monkeypatch.setenv("SELF_LEARN_HOME", str(home))

        code = cli.main(argv)
        out = capsys.readouterr()

        assert code == cli.EXIT_NO_HOME == 5, f"{argv} → {code}\n{out.err}"
        assert "ledger home" in out.err
        assert "Traceback" not in out.err
        assert "GitOpsError" not in out.err

    def test_selfcheck_drift_refuses_to_certify_a_bad_home(self, tmp_path):
        """A bad home has no hosts.yaml either, so the drift check answered
        "hosts.yaml absent — drift not checked" and PASSED: the silent
        all-clear wearing a green tick."""
        from self_learn.selfcheck import _check_drift

        ok, reason = _check_drift(tmp_path / "missing")
        assert ok is False
        assert "does not exist" in reason

        not_repo = tmp_path / "not-a-repo"
        not_repo.mkdir()
        ok, reason = _check_drift(not_repo)
        assert ok is False
        assert "not a git repo" in reason
