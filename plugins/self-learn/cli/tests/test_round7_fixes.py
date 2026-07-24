"""Round-7 audit fixes (2026-07-16): the exit code that made a false state
claim, and the data-loss window the honest report did not close.

The invariant itself (no ledger/host mutation may precede its
``commit_lock``) is enforced structurally next door in
``test_lock_invariant.py`` — that is the deliverable; these are the
behavioural pins for the two findings that are not about lock ORDER.

Design pin, inherited from round 3 and non-negotiable: **no mocks**. Real
git sandboxes, real second processes. The half-written state is produced
by a real ``git`` whose ``commit`` really fails (``support.
failing_git_shim``), never by monkeypatching the code under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from self_learn import cli, gitops, miner, reconcile as reconcile_mod, verbs
from self_learn.ledger_ops import create_record
from support import (
    commit_all,
    failing_git_shim,
    git,
    make_behavior,
    make_env,
)


def head_files(repo: Path) -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.split()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(env.ledger))
    monkeypatch.setenv("SELF_LEARN_MINER_AUTOKICK", "0")
    monkeypatch.setenv("SELF_LEARN_MINER", "0")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return env.ledger


# ============================ BLOCKER 2: one code, one state fact


class TestExitSixNeverLiesAboutState:
    """``commands/review.md`` and ``cli._cmd_verb`` both documented exit 6
    as "the verb refused BEFORE writing, so nothing is half-done; it is
    safe to retry". True for a lock TIMEOUT. **False when ``gitops.commit``
    itself fails** — same exception, same code, opposite state.

    Probed: `reject` with a commit-failing git exited 6 with the record
    ALREADY moved pending→resolved, and the documented retry then failed
    with exit 64 "record not found". The caller was told the ledger had not
    changed by the one code whose entire content is that claim.

    This is round 3's own fixed class, one layer up: round 3 removed the
    false "nothing was written" sentence from ``commit_lock``'s error text
    because the module cannot know — and the gitops docstring still says
    "That is the verb's fact to state, not this module's". The verb then
    stated it unconditionally.
    """

    def test_a_commit_failure_is_not_reported_as_nothing_written(
        self, home, tmp_path, monkeypatch, capsys
    ):
        create_record(home, make_behavior(record_id="lrn-77770001"))
        commit_all(home, "record seed")
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            code = cli.main(["reject", "lrn-77770001"])
        finally:
            flag.unlink()
        out = capsys.readouterr()

        # the state the CLI must not misdescribe: the record REALLY moved
        assert (home / "skills/s/resolved/lrn-77770001.md").is_file(), (
            "the probe no longer reproduces: the record did not move"
        )
        assert "skills/s/resolved/lrn-77770001.md" not in head_files(home)

        assert code != gitops.EXIT_GIT_FAILED, (
            "exit 6 over a HALF-WRITTEN ledger. 6 means 'nothing was "
            "written, safe to retry' — here the record has already moved "
            "pending→resolved, and the documented retry fails with 64 "
            f"'record not found'.\n{out.err}"
        )
        assert code == gitops.EXIT_HALF_WRITTEN, f"reject → {code}\n{out.err}"
        assert "Traceback" not in out.err
        # and a surface may not report this state without the repair
        assert "Repair:" in out.err, out.err
        assert "git -C" in out.err

    def test_a_lock_timeout_still_means_nothing_written_and_is_true(
        self, home, tmp_path, monkeypatch, capsys
    ):
        """The other cause of the same exception must keep the code whose
        promise it CAN keep — and the promise must be real, not just
        printed: the ledger is clean and the retry works."""
        create_record(home, make_behavior(record_id="lrn-77770002"))
        commit_all(home, "record seed")

        import subprocess
        import sys
        import textwrap
        import time

        monkeypatch.setattr(gitops, "COMMIT_LOCK_TIMEOUT", 0.3)
        ready, release = tmp_path / "r", tmp_path / "rel"
        src = str(Path(__file__).resolve().parents[1] / "src")
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                textwrap.dedent(f"""
                    import sys, time
                    sys.path.insert(0, {src!r})
                    from pathlib import Path
                    from self_learn import gitops
                    with gitops.commit_lock(Path({str(home)!r})):
                        Path({str(ready)!r}).touch()
                        deadline = time.monotonic() + 30
                        while (not Path({str(release)!r}).exists()
                               and time.monotonic() < deadline):
                            time.sleep(0.01)
                """),
            ],
        )
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        try:
            code = cli.main(["reject", "lrn-77770002"])
        finally:
            release.touch()
            holder.wait(timeout=30)
        out = capsys.readouterr()

        assert code == gitops.EXIT_GIT_FAILED, f"reject → {code}\n{out.err}"
        assert "Traceback" not in out.err
        assert (home / "skills/s/pending/lrn-77770002.md").is_file(), (
            "exit 6 promises nothing was written — the record moved anyway"
        )
        assert not git(home, "status", "--porcelain").stdout.strip()
        # the documented retry really works now that nobody holds the lock
        assert cli.main(["reject", "lrn-77770002"]) == 0, (
            "the retry exit 6 documents as safe did not work"
        )

    def test_the_two_causes_never_share_a_code(self):
        """The whole point, as an invariant on the constants."""
        assert gitops.EXIT_GIT_FAILED != gitops.EXIT_HALF_WRITTEN

    def test_a_half_written_error_cannot_exist_without_a_repair(self):
        """The type is what forces the repair to be printed: a surface
        cannot report this state and forget to say how to fix it, because
        the exception has nowhere to hide the omission."""
        with pytest.raises(TypeError):
            gitops.HalfWrittenError("something broke")  # no repair=

    def test_the_sweep_reached_import_too(self, home, tmp_path, monkeypatch, capsys):
        """BLOCKER 2 asked for a sweep, not a patch of the reported site.
        `import` had the identical shape: `EXIT_OK if report.committed else
        EXIT_GIT_FAILED` — exit 6, "nothing was written", over N records
        sitting on disk uncommitted."""
        skill_refs = tmp_path / "host-repo" / "plugins" / "s-plugin" / "skills" / "s" / "references"
        skill_refs.mkdir(parents=True, exist_ok=True)
        (skill_refs / "GOTCHAS.journal.md").write_text(
            "### 2026-07-16 — the Beacon reserves its own DHCP lease\n\n"
            "The router hands 192.0.2.232 to the Beacon by MAC reservation.\n",
            encoding="utf-8",
        )
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            code = cli.main(["import", "--backlog", "s"])
        finally:
            flag.unlink()
        out = capsys.readouterr()
        written = list(home.glob("skills/s/pending/lrn-*.md"))
        assert written, f"the probe did not reproduce: no records\n{out.err}"
        assert code == gitops.EXIT_HALF_WRITTEN, (
            f"import → {code} over {len(written)} record(s) on disk; 6 "
            f"promises nothing was written\n{out.err}"
        )
        assert "reconcile" in out.err, out.err

    def test_teach_and_the_verbs_agree_on_what_each_code_means(
        self, home, tmp_path, monkeypatch, capsys
    ):
        """The deepest half of the finding: the SAME integer meant
        opposite things on two surfaces, and each command file documented
        its own as the truth — teach.md said 6 = "the record IS written",
        review.md said 6 = "nothing was written". Both were locally
        correct, which is why neither looked like a bug. Pin the agreement
        end-to-end: on BOTH surfaces, a commit failure is 7."""
        flag = failing_git_shim(tmp_path, monkeypatch)
        flag.touch()
        try:
            teach_code = cli.main(
                [
                    "teach",
                    "--skill",
                    "s",
                    "--type",
                    "knowledge",
                    "--fact",
                    "The Beacon reserves 192.0.2.232.",
                ]
            )
        finally:
            flag.unlink()
        capsys.readouterr()
        create_record(home, make_behavior(record_id="lrn-77770003"))
        commit_all(home, "seed")
        flag.touch()
        try:
            verb_code = cli.main(["reject", "lrn-77770003"])
        finally:
            flag.unlink()
        capsys.readouterr()
        assert teach_code == verb_code == gitops.EXIT_HALF_WRITTEN, (
            f"teach → {teach_code}, reject → {verb_code}: the same state "
            "(written, uncommitted) must be the same code on every surface"
        )


# ================== MAJOR 4: reporting a loss is not preventing one


class TestUncommittedRecordsAreRecovered:
    """``miner._advance_cursors`` runs unconditionally. When the landing
    commit fails, the ``landed-uncommitted`` status and the non-zero exit
    are HONEST — and the records are still lost: written untracked, cursors
    advanced past their origins, never re-mined (origin dedup reads them
    off disk), destroyed by the next clone.

    Honesty is not recovery. The fix is a capability, not a better
    sentence: :mod:`self_learn.reconcile` finds orphaned ledger writes and
    commits them under the lock, by pathspec; the miner calls it at run
    start, so a nightly timer closes the window with no human involved.
    """

    def test_reconcile_commits_what_a_producer_could_not(self, home):
        orphan = home / "skills" / "s" / "pending" / "lrn-77771001.md"
        create_record(home, make_behavior(record_id="lrn-77771001"))
        assert orphan.is_file()
        assert "skills/s/pending/lrn-77771001.md" not in head_files(home)

        result = reconcile_mod.reconcile(home, no_push=True)

        assert result.healed
        assert orphan in result.committed
        assert "skills/s/pending/lrn-77771001.md" in head_files(home)
        assert not git(home, "status", "--porcelain").stdout.strip()
        subject = git(home, "log", "-1", "--format=%s").stdout.strip()
        assert subject == "self-learn: reconcile 1 uncommitted record(s)", subject

    def test_reconcile_is_a_no_op_on_a_clean_ledger(self, home):
        before = git(home, "rev-parse", "HEAD").stdout
        result = reconcile_mod.reconcile(home, no_push=True)
        assert not result.healed
        assert git(home, "rev-parse", "HEAD").stdout == before, (
            "reconcile made an empty commit — it is called on every mine "
            "run and every push, so a no-op must really be a no-op"
        )

    def test_reconcile_only_commits_what_it_found(self, home):
        """Concurrency safety: a producer that writes the instant we
        release must not find its work absorbed into our commit. The scan
        runs inside the lock and the commit is pathspec-scoped to exactly
        what it saw — so a file appearing afterwards is untouched."""
        create_record(home, make_behavior(record_id="lrn-77771002"))
        # a "concurrent producer" file that exists but is NOT a record —
        # reconcile owns records/proposals/meta, never a directory sweep
        (home / "skills" / "s" / "scratch.txt").write_text("x\n", encoding="utf-8")

        result = reconcile_mod.reconcile(home, no_push=True)

        assert len(result.committed) == 1
        assert "skills/s/scratch.txt" not in head_files(home), (
            "reconcile swept a file that is not the ledger's truth — it "
            "commits records, it does not `git add -A`"
        )

    def test_reconcile_refuses_to_commit_half_a_rename(self, home):
        """The one shape it must NOT guess at. A half-committed `git mv`
        (what a resolution verb leaves when its commit fails) committed one
        half at a time is the exact corruption `gitops.known_paths` exists
        to prevent: the record in BOTH pending/ and resolved/, git status
        clean, exit 0."""
        create_record(home, make_behavior(record_id="lrn-77771003"))
        (home / "skills" / "s" / "resolved").mkdir(parents=True, exist_ok=True)
        commit_all(home, "seed")
        git(
            home,
            "mv",
            "skills/s/pending/lrn-77771003.md",
            "skills/s/resolved/lrn-77771003.md",
        )

        result = reconcile_mod.reconcile(home, no_push=True)

        assert not result.healed, "reconcile committed half a rename"
        assert result.blocked, "…and did not even say it saw one"
        assert any("lrn-77771003" in line for line in result.blocked)

    def test_the_miner_reconciles_a_previous_runs_orphans_at_run_start(
        self, home, monkeypatch, tmp_path
    ):
        """The wire that makes the system self-heal without being asked:
        a failed landing is committed by the NEXT run, before it mines
        anything. This is what turns "lost on the next clone" into
        "committed within a day"."""
        monkeypatch.delenv("SELF_LEARN_MINER", raising=False)
        transcripts = tmp_path / "transcripts"
        (transcripts / "-home-u-proj").mkdir(parents=True)
        monkeypatch.setenv("SELF_LEARN_TRANSCRIPTS_DIR", str(transcripts))
        # the wreckage a `landed-uncommitted` run leaves behind
        create_record(home, make_behavior(record_id="lrn-77771004"))
        assert "skills/s/pending/lrn-77771004.md" not in head_files(home)

        miner.run(home, trigger="timer", no_push=True)

        assert "skills/s/pending/lrn-77771004.md" in head_files(home), (
            "the miner ran and left the previous run's uncommitted records "
            "uncommitted — the cursors already moved past them, so nothing "
            "will ever mine them again and a clone deletes them"
        )

    def test_push_reconciles_before_publishing(self, home, capsys):
        """`push` is what a human runs when something went wrong. A ledger
        whose records are not even committed is the state it must not
        quietly publish around."""
        create_record(home, make_behavior(record_id="lrn-77771005"))
        cli.main(["push"])
        capsys.readouterr()
        assert "skills/s/pending/lrn-77771005.md" in head_files(home)

    def test_the_mine_run_message_names_the_recovery(self, home, capsys):
        """The honest report stays, and now it names the verb that fixes
        the state instead of telling the user to commit by hand."""
        entries = [
            {
                "ts": "2026-07-16T00:00:00Z",
                "status": "landed-uncommitted",
                "trigger": "timer",
                "landed": 3,
                "folded": 1,
                "sessions_scanned": 2,
            }
        ]
        path = miner.journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        cli.main(["mine", "status"])
        out = capsys.readouterr().out
        # the MINOR: counts expanded for `ok` only, so the row that most
        # needs them ("how many records are at risk?") rendered bare
        assert "landed=3" in out, (
            f"the landed count is hidden on the status that most needs it:\n{out}"
        )
        assert "reconcile" in out, out
