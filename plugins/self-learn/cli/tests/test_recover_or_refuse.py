"""S-62 / §7.2a.5(3)/(4)/(5): "finish and tell" across path families, and
the STOP refusal's own message completeness.

Deliberately NOT `support.py` (armor-pinned) — this module owns its own
plant helpers, `_plant_restorable`/`_plant_stop`, built on the SAME two
recipes `test_intents.py` already proves against `intents.recover`
directly (a restore that never completes; an unresolvable-anywhere STOP).
Here they are reused to prove the OUTER guarantee: every attended,
lock-holding surface that calls `intents.ledger_write` announces a
recovered intent BEFORE its own output, and a live STOP's message names
every intent involved — completed ones included, never just the STOP.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import pytest

from self_learn import batch, cli, gitops, hosts, intents, settings, telemetry, verbs
from self_learn.ledger_ops import create_record
from self_learn.primitives import fsops

from support import commit_all, git, make_behavior, make_env
from test_intents import _assert_killed, _run_child  # noqa: F401 -- gate r1 MAJOR-4


def _probe_file(home: Path, name: str = "probe.txt") -> Path:
    """A plain, tracked, ordinary text file -- never a file any verb under
    test reads for its OWN business logic (`hosts.yaml`/`config.yaml`
    would be parsed as YAML by the very surface being exercised, so a
    plant against either one is confounded by the verb's own precondition
    reads, not the guard being tested here)."""
    path = home / name
    path.write_text("seed\n", encoding="utf-8")
    commit_all(home, f"add {name}")
    return path


def _plant_restorable(home: Path, target: Path, op: str = "probe") -> intents.Intent:
    """begin -> mutate -> never complete()/finish(): recovery restores it
    and reports it via `RecoverResult.restored` -- the positive case
    every attended ledger-write call site must announce."""
    intent = intents.begin(home, op, [target], f"self-learn: {op}")
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "crash before complete()\n", encoding="utf-8")
    return intent


def _plant_roll_forward(home: Path, target: Path, op: str = "probe") -> intents.Intent:
    """begin -> mutate -> complete() (no commit): recovery finds every
    step's CURRENT bytes already match `complete`'s own recorded
    `new_sha` (the mutation genuinely landed, only the commit never
    ran) and rolls it forward via its OWN `gitops.stage_and_commit`
    call, reporting it via `RecoverResult.rolled_forward` -- the ONLY
    announcement route whose wording names `self-learn recompile`
    (gate r1 MAJOR-5: no attended surface planted this shape before
    this fold; every existing `_plant_restorable` use only ever
    reaches `.restored`)."""
    intent = intents.begin(home, op, [target], f"self-learn: {op}")
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "mutated, then complete() before the commit\n", encoding="utf-8")
    intents.complete(intent)
    return intent


def _plant_stop(home: Path, target: Path, op: str = "probe") -> intents.Intent:
    """begin -> mutate -> commit (moves HEAD past old_sha) -> mutate
    again, uncompleted: no source resolves the pre-transaction bytes
    anywhere (worktree / HEAD / inline) -- recovery cannot help this one
    and marks it STOPPED. Same recipe as test_intents.py's own
    `test_stop_when_prior_content_is_unresolvable_anywhere`. Stages ONLY
    *target* (never `-A`) -- another intent's own planted-but-uncommitted
    mutation elsewhere in the worktree must not get swept into this
    commit, which would silently turn IT unresolvable too."""
    intent = intents.begin(home, op, [target], f"self-learn: {op}")
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "mutated once\n", encoding="utf-8")
    git(home, "add", "--", str(target))
    git(home, "commit", "-q", "-m", "an unrelated commit moves HEAD past old_sha")
    target.write_text(
        original + "mutated once\nmutated twice, still uncompleted\n", encoding="utf-8"
    )
    return intent


def run_cli(argv):
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    return e


def _seed_pending(home, rid):
    record = make_behavior(record_id=rid, scope="skill:s")
    create_record(home, record)
    commit_all(home, "seed record")
    return record


# =========================================================== positive cases


class TestFinishAndTellAcrossPathFamilies:
    """One test per path family named in §7.2a.5(3)'s "attended" list —
    each plants a genuinely restorable intent, runs the surface, and
    asserts its own output carries "recovered <id>" (the exact wording
    `intents.announce_recovered`/`LedgerStoppedError` both use)."""

    def test_teach_announces_a_recovered_intent_before_its_own_output(self, env, capsys):
        home = env.ledger
        intent = _plant_restorable(home, _probe_file(home))
        rc = run_cli(
            [
                "teach", "never live-edit HA storage", "--skill", "s",
                "--type", "behavior", "--trigger", "t", "--instruction", "i",
            ]
        )
        assert rc == 0
        err = capsys.readouterr().err
        assert f"recovered {intent.id}" in err
        assert not intent.file_path.exists()

    def test_teach_prints_nothing_recovered_with_no_planted_intent(self, env, capsys):
        """Positive control for the assertion above: the SAME command,
        with nothing planted, prints no "recovered" line at all."""
        rc = run_cli(
            [
                "teach", "never live-edit HA storage", "--skill", "s",
                "--type", "behavior", "--trigger", "t", "--instruction", "i",
            ]
        )
        assert rc == 0
        assert "recovered" not in capsys.readouterr().err

    def test_config_set_announces_a_recovered_intent(self, env, capsys):
        home = env.ledger
        intent = _plant_restorable(home, _probe_file(home))
        settings.config_set(home, "worker.coalesce_secs", "5")
        assert f"recovered {intent.id}" in capsys.readouterr().err

    def test_config_set_prints_nothing_recovered_with_no_planted_intent(self, env, capsys):
        home = env.ledger
        settings.config_set(home, "worker.coalesce_secs", "5")
        assert "recovered" not in capsys.readouterr().err

    def test_host_remove_announces_a_recovered_intent(self, env, capsys):
        home = env.ledger
        intent = _plant_restorable(home, _probe_file(home))
        hosts.host_remove(home, env.host, gate_only=True)
        assert f"recovered {intent.id}" in capsys.readouterr().err

    def test_reject_announces_a_recovered_intent(self, env, capsys):
        home = env.ledger
        record = _seed_pending(home, "lrn-aaaaaaaa")
        intent = _plant_restorable(home, _probe_file(home))
        verbs.reject(home, record.id, no_push=True)
        assert f"recovered {intent.id}" in capsys.readouterr().err

    def test_telemetry_flush_attended_announces_a_recovered_intent(self, env, capsys):
        home = env.ledger
        telemetry.spool_event("capture", source="test", scope="skill:s", record="lrn-aaaaaaaa")
        intent = _plant_restorable(home, _probe_file(home))
        run_cli(["telemetry", "flush"])
        assert f"recovered {intent.id}" in capsys.readouterr().err

    def test_batch_announces_a_recovered_intent_in_its_json_envelope(self, env):
        home = env.ledger
        record = _seed_pending(home, "lrn-aaaaaaaa")
        intent = _plant_restorable(home, _probe_file(home))
        sheet = [batch.SheetItem(n=1, id=record.id, verb="reject", fields={})]
        result = batch.run(home, sheet, no_push=True)
        assert result.recovered_restored == [intent.id]
        assert result.process_code == 0

    def test_teach_announces_a_roll_forward_naming_recompile(self, env, capsys):
        """MAJOR-5: the roll-forward announcement (the line naming
        `self-learn recompile`) had zero attended-surface coverage --
        deleting `announce_recovered`'s `rolled_forward` loop left every
        existing test green. Plants the genuinely roll-forward-able
        shape (`begin` -> mutate -> `complete()`, no commit) instead of
        `_plant_restorable`'s shape."""
        home = env.ledger
        intent = _plant_roll_forward(home, _probe_file(home))
        rc = run_cli(
            [
                "teach", "never live-edit HA storage", "--skill", "s",
                "--type", "behavior", "--trigger", "t", "--instruction", "i",
            ]
        )
        assert rc == 0
        err = capsys.readouterr().err
        assert f"recovered {intent.id}" in err
        assert "rolled forward" in err
        assert "run 'self-learn recompile'" in err
        assert not intent.file_path.exists()

    def test_batch_announces_a_roll_forward_in_its_recovered_rolled_forward_field(self, env):
        """MAJOR-5's second half: `batch`'s own JSON envelope carries a
        SEPARATE field for this shape (`recovered_rolled_forward`,
        distinct from `recovered_restored` above) -- the gate noted the
        sibling test above only ever plants a restorable intent, never
        exercising this field for real."""
        home = env.ledger
        record = _seed_pending(home, "lrn-aaaaaaaa")
        intent = _plant_roll_forward(home, _probe_file(home))
        sheet = [batch.SheetItem(n=1, id=record.id, verb="reject", fields={})]
        result = batch.run(home, sheet, no_push=True)
        assert result.recovered_rolled_forward == [intent.id]
        assert result.recovered_restored == []
        assert result.process_code == 0


# ============================================================ STOP message


class TestStopMessageCompleteness:
    """§7.2a.5(4)(b): a STOP's message must report every recovery this SAME
    attempt already completed -- rolled-forward/restored ids are never
    hidden behind the refusal, on any surface."""

    def test_ledger_stopped_error_message_names_a_completed_recovery_too(self, env):
        home = env.ledger
        # Both probes committed BEFORE either intent is planted: `_probe_
        # file`'s own `commit_all` is a blanket `git add -A` (support.py)
        # -- committing probe-b AFTER probe-a's mutation would sweep that
        # uncommitted mutation in too, moving HEAD past probe-a's own
        # old_sha and turning IT unresolvable as well.
        probe_a = _probe_file(home, "probe-a.txt")
        probe_b = _probe_file(home, "probe-b.txt")
        restorable = _plant_restorable(home, probe_a)
        stop = _plant_stop(home, probe_b)

        with pytest.raises(intents.LedgerStoppedError) as excinfo:
            with intents.ledger_write(home):
                pass
        message = str(excinfo.value)
        assert f"recovered {restorable.id}" in message
        assert stop.id in message

    def test_batch_reports_a_stop_message_naming_the_offending_intent(self, env):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        sheet = [batch.SheetItem(n=1, id="lrn-aaaaaaaa", verb="reject", fields={})]
        result = batch.run(home, sheet, no_push=True)
        assert result.process_code == gitops.EXIT_GIT_FAILED
        assert result.stop_message is not None
        assert stop.id in result.stop_message
        assert result.items == []  # the whole sheet refused before item 1

    def test_reject_stop_message_is_not_double_prefixed(self, env, capsys):
        home = env.ledger
        record = _seed_pending(home, "lrn-aaaaaaaa")
        stop = _plant_stop(home, _probe_file(home))
        rc = run_cli(["reject", record.id])
        assert rc == gitops.EXIT_GIT_FAILED
        err = capsys.readouterr().err
        assert stop.id in err
        # The generic `except gitops.GitOpsError` arm wraps `str(exc)` in
        # its OWN "self-learn <verb>: ..." prefix -- doubling the one
        # `LedgerStoppedError`'s own message already carries. The
        # dedicated `except intents.LedgerStoppedError` arm (ahead of
        # that generic one) must intercept first and print `str(exc)`
        # bare, so this exact wrapped shape must never appear.
        assert "reject: self-learn: transaction intent" not in err

    def test_reconcile_refuses_on_a_live_stop(self, env):
        """§7.2a.8: the recovery verb itself, unclear-intent'd, must
        refuse rather than paper over its own STOP -- rc 6, HEAD
        unchanged (nothing partially committed), the intent file still
        on disk (not silently swallowed), and its persisted `stopped`
        field durable (`_mark_stopped` ran and confirmed the rewrite)."""
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        sha_before = git(home, "rev-parse", "HEAD").stdout.strip()

        rc = run_cli(["reconcile"])

        assert rc == gitops.EXIT_GIT_FAILED
        assert git(home, "rev-parse", "HEAD").stdout.strip() == sha_before
        assert stop.file_path.exists()
        persisted = json.loads(stop.file_path.read_text(encoding="utf-8"))
        assert persisted.get("stopped") is not None
        assert persisted["stopped"].get("reason")

    def test_reconcile_json_carries_the_stop_too(self, env, capsys):
        """Positive control for the assertion above, at the `--json`
        envelope `_cmd_reconcile` renders instead of the plain-text
        path: `refused` and `ok` must reflect the STOP, and `stopped`
        must name the offending id -- the same fields a healthy run
        would report as empty/true."""
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))

        rc = run_cli(["reconcile", "--json"])

        assert rc == gitops.EXIT_GIT_FAILED
        payload = json.loads(capsys.readouterr().out)
        assert payload["refused"] is True
        assert payload["ok"] is False
        assert any(stop.id in entry for entry in payload["stopped"])

    def test_status_names_the_real_id_not_a_literal_placeholder(self, env, capsys):
        """Gate r1 MINOR-2: `status`'s own STOPPED-intent line used to
        read `--clear-intent <id>` literally, even though the real id
        already sits right there in the same message's own `(...)`
        list."""
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        intents.recover(home)  # writes the durable marker `classify_status` reads

        rc = run_cli(["status"])

        assert rc == 0
        err = capsys.readouterr().err
        assert "STOPPED transaction intent" in err
        assert f"--clear-intent {stop.id}" in err
        assert "--clear-intent <id>" not in err


# =================================================== multi-span refusal


class TestMultiSpanRefusal:
    """Gate r1 MAJOR-1 (§7.2a.5(4)): `recompile --adopt` commits under
    one outer lock span and takes another later for a different target
    -- if a concurrent producer crashes an intent between those two
    spans, the LATER span's refusal must report the earlier span's
    commit and exit 8, never claim "this verb wrote nothing" at exit 6.

    The second span: route a record into `env.host` (a GIT-mode host,
    already registered) normally, letting it render once -- then revert
    the target's tracked content back to its PRE-render bytes and
    commit that reversion. `compiled.verdict_for`'s own table makes this
    "stale" (`observed_hash == based_on_sha256`), never "edited" (which
    would refuse) -- a legitimate drift shape recompile is SUPPOSED to
    repair by re-rendering, which is exactly the second real ledger span
    this test needs, with no refusal of its own in the way."""

    def _setup(self, env, tmp_path):
        home = env.ledger
        from self_learn.compilers import BEGIN_MARKER
        from support import CLAUDE_MD_SEED

        plain_a = tmp_path / "adopt-plain"
        plain_a.mkdir()
        hosts.host_add(home, plain_a, "project", mode="plain")
        record_a = make_behavior(scope="project", record_id="lrn-0000000a")
        create_record(home, record_a, project_path=plain_a)
        verbs.route(home, record_a.id, dest="claude-md", no_push=True)
        target_a = plain_a / "CLAUDE.md"
        edited = target_a.read_text(encoding="utf-8").replace(
            BEGIN_MARKER, BEGIN_MARKER + "\nhand edit"
        )
        target_a.write_text(edited, encoding="utf-8")

        record_b = make_behavior(scope="project", record_id="lrn-0000000b")
        create_record(home, record_b, project_path=env.host)
        verbs.route(home, record_b.id, dest="claude-md", no_push=True)
        # Revert the host's CLAUDE.md to its pre-render bytes and commit
        # that -- `observed_hash` now equals the entry's own
        # `based_on_sha256`, the "stale" verdict, not "edited".
        (env.host / "CLAUDE.md").write_text(CLAUDE_MD_SEED, encoding="utf-8")
        git(env.host, "add", "-A")
        git(env.host, "commit", "-q", "-m", "revert to force a stale verdict")
        return target_a

    def _spy(self, monkeypatch, home):
        real_ledger_write = verbs._ledger_write
        calls = []

        def spy(home_arg, *, earlier_commits=None):
            calls.append(list(earlier_commits or []))
            if len(calls) == 2:
                # A concurrent producer crashes its own intent right
                # between the adopt span (already committed) and this
                # second target's own span -- same unresolvable-anywhere
                # recipe `_plant_stop` uses above, against an UNRELATED
                # probe file (never one of recompile's own targets).
                probe = _probe_file(home_arg, "between-spans.txt")
                _plant_stop(home_arg, probe)
            return real_ledger_write(home_arg, earlier_commits=earlier_commits)

        monkeypatch.setattr(verbs, "_ledger_write", spy)
        return calls

    def test_a_stop_planted_between_two_recompile_spans_reports_the_earlier_commit(
        self, env, tmp_path, monkeypatch
    ):
        target_a = self._setup(env, tmp_path)
        calls = self._spy(monkeypatch, env.ledger)

        with pytest.raises(intents.LedgerStoppedError) as excinfo:
            verbs.recompile(env.ledger, no_push=True, adopt=target_a)

        assert len(calls) == 2, calls
        assert calls[0] == []  # the adopt span itself has nothing earlier
        assert calls[1] and "recompile --adopt" in calls[1][0]
        message = str(excinfo.value)
        assert "no further requested writes; earlier commits:" in message
        assert "recompile --adopt" in message
        assert excinfo.value.earlier_commits

    def test_the_cli_recompile_dispatch_exits_8_not_6(self, env, tmp_path, monkeypatch, capsys):
        """The CLI's own `_cmd_recompile` had NO dedicated
        `LedgerStoppedError` arm at all before this fold -- it fell
        through to the generic `GitOpsError` catch, which would have
        double-prefixed the message AND always returned 6. Same plant
        as above, driven through `run_cli`."""
        target_a = self._setup(env, tmp_path)
        self._spy(monkeypatch, env.ledger)

        rc = run_cli(["recompile", "--adopt", str(target_a)])

        assert rc == 8
        err = capsys.readouterr().err
        assert "no further requested writes; earlier commits:" in err
        assert "recompile --adopt" in err
        # No double prefix ("self-learn recompile: self-learn: ...").
        assert "recompile: self-learn: transaction intent" not in err

# ======================================================== clear_stopped


class TestClearStopped:
    """S-62 / §7.2a.4, §7.2a.6: `intents.clear_stopped` — THE required
    recovery verb's clear leg — has FOUR distinct return values, one
    more than fffee09's fold message names ("three outcomes": cleared /
    recovered / refused-for-a-live-writer). `"not-found"` is the extra:
    neither §7.2a.4 nor §7.2a.6 speaks to an id naming no file at all,
    since both sections classify an intent that EXISTS. Not a spec
    violation -- but untested until this class (zero prior coverage of
    this function anywhere in the suite, despite being the one recovery
    verb the sprint assignment requires)."""

    def test_cleared_when_the_persisted_stopped_field_is_already_set(self, env):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        # `recover()` runs the failing attempt once and persists `stopped`
        # on the intent's own JSON -- the FIRST of §7.2a.4's three ways to
        # classify STOPPED (the other two are covered by the next two
        # tests below).
        intents.recover(home)
        outcome = intents.clear_stopped(home, stop.id)
        assert outcome == "cleared"
        assert not stop.file_path.exists()

    def test_cleared_when_the_intent_file_is_unreadable(self, env):
        home = env.ledger
        restorable = _plant_restorable(home, _probe_file(home))
        restorable.file_path.write_text("{not json", encoding="utf-8")
        outcome = intents.clear_stopped(home, restorable.id)
        assert outcome == "cleared"
        assert not restorable.file_path.exists()

    def test_cleared_when_unmarked_and_this_spans_own_attempt_fails(self, env):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        outcome = intents.clear_stopped(home, stop.id)
        assert outcome == "cleared"
        assert not stop.file_path.exists()

    def test_recovered_not_cleared_when_unmarked_and_this_spans_own_attempt_succeeds(
        self, env
    ):
        home = env.ledger
        restorable = _plant_restorable(home, _probe_file(home))
        outcome = intents.clear_stopped(home, restorable.id)
        assert outcome == "recovered"
        assert not restorable.file_path.exists()

    def test_not_found_for_an_id_naming_no_intent_file(self, env):
        home = env.ledger
        outcome = intents.clear_stopped(home, "lrn-doesnotexist")
        assert outcome == "not-found"

    def test_refused_when_another_holder_has_the_ledger_lock(self, env, monkeypatch):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        # A short timeout so the refusal path doesn't sit for the real
        # 5s default -- `_CLEAR_INTENT_TIMEOUT` is read at CALL time
        # inside `clear_stopped`, same reason `commit_lock`'s own
        # `timeout=None` reads `COMMIT_LOCK_TIMEOUT` at call time.
        monkeypatch.setattr(intents, "_CLEAR_INTENT_TIMEOUT", 0.05)
        lock_path = gitops.commit_lock_path(home)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "w", encoding="utf-8")
        # A SEPARATE `open()` from this same process, not routed through
        # `gitops._flock_lock` -- `flock` conflicts across independent
        # open-file-descriptions even within one process, so this holds
        # against `clear_stopped`'s own `commit_lock` acquisition exactly
        # like a genuinely different process would, without needing one.
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            outcome = intents.clear_stopped(home, stop.id)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()
        assert outcome == "refused"
        assert stop.file_path.exists()  # untouched -- refusal never reaches the file

    def test_a_wedged_git_reset_during_its_own_attempt_is_a_failed_recovery_not_a_refusal(
        self, env, monkeypatch
    ):
        """The bug this test guards: `_recover_one`'s restore leg calls
        `gitops._git(home, "reset", ...)` directly -- not through
        `stage_and_commit`'s `HalfWrittenError` conversion -- so a wedged
        subprocess there raises a plain `gitops.GitOpsError`. Before this
        turn's fix, `clear_stopped`'s inner catch around `_recover_one`
        didn't include `GitOpsError`, so it escaped to the OUTER `except
        gitops.GitOpsError: return "refused"` -- mislabeling a failed
        recovery ATTEMPT (this call holds the lock throughout; nothing
        here is ever "a live writer") as a lock refusal, and leaving the
        intent's file untouched instead of clearing it.

        Needs a RESTORABLE plant, not a STOP one: `_recover_one`'s restore
        leg only reaches its `git reset` call after every step's old bytes
        resolve -- a `_plant_stop` intent fails at that resolution check
        and returns before ever reaching the line this test wedges."""
        home = env.ledger
        restorable = _plant_restorable(home, _probe_file(home))
        real_git = gitops._git

        def wedged(repo, *args, **kwargs):
            if args and args[0] == "reset":
                raise gitops.GitOpsError("git reset in <repo> exceeded 30s and was killed")
            return real_git(repo, *args, **kwargs)

        monkeypatch.setattr(gitops, "_git", wedged)
        outcome = intents.clear_stopped(home, restorable.id)
        assert outcome == "cleared"
        assert not restorable.file_path.exists()

    def test_recover_also_marks_stopped_on_a_wedged_git_reset_not_just_clear_stopped(
        self, env, monkeypatch
    ):
        """The identical gap existed at `recover()`'s own call site
        (§7.2a.4's ordinary recovery path, not just the clear leg) --
        this proves the SAME fix there: a wedged `git reset` is reported
        as a proper STOP, not an uncaught exception past every caller."""
        home = env.ledger
        restorable = _plant_restorable(home, _probe_file(home))
        real_git = gitops._git

        def wedged(repo, *args, **kwargs):
            if args and args[0] == "reset":
                raise gitops.GitOpsError("git reset in <repo> exceeded 30s and was killed")
            return real_git(repo, *args, **kwargs)

        monkeypatch.setattr(gitops, "_git", wedged)
        result = intents.recover(home)  # must not raise
        assert [d.id for d in result.stopped_detail] == [restorable.id]
        assert "git reset" in result.stopped_detail[0].reason

    def test_clear_intent_cli_json_envelope_carries_the_outcome(self, env, capsys):
        home = env.ledger
        restorable = _plant_restorable(home, _probe_file(home))
        rc = run_cli(["reconcile", "--clear-intent", restorable.id, "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["cleared"] == restorable.id
        assert payload["clear_outcome"] == "recovered"


# ==================================================== classify_status


class TestClassifyStatus:
    """§7.2a.7: zero prior coverage of `intents.classify_status` /
    `IntentStatus` / `StatusClass` anywhere in the suite -- `cli.py`'s
    own `status --fast` JSON fields (`intents_probe`, `intents_stopped`,
    `intents_stopped_count`) ride on this function untested. One test
    per `probe` value, plus the interleaving witness `probe == "busy"`
    exists to prove: a marker on disk is HISTORICAL under contention,
    never current state."""

    def test_a_restorable_intent_classifies_as_pending(self, env):
        home = env.ledger
        restorable = _plant_restorable(home, _probe_file(home))
        status = intents.classify_status(home)
        assert status.probe == "ok"
        assert not status.busy
        assert [i.cls for i in status.intents] == ["pending"]
        assert status.intents[0].id == restorable.id

    def test_a_recovered_stop_classifies_as_stopped_with_reason_and_at(self, env):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        intents.recover(home)  # runs `_mark_stopped` -- the marker this reads
        status = intents.classify_status(home)
        assert status.probe == "ok"
        assert [i.id for i in status.stopped] == [stop.id]
        stopped = status.stopped[0]
        assert stopped.reason
        assert stopped.at

    def test_lock_contention_reports_busy_for_every_intent_marker_included(
        self, env
    ):
        """The interleaving witness: a STOPPED marker under a live
        holder is HISTORICAL, not current -- `classify_status` must
        report `"busy"` for it too, never `"stopped"`. The probe's own
        `O_RDONLY|O_CREAT` open (never truncating) must leave the
        holder's pid bytes exactly as they were."""
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        intents.recover(home)  # marks it stopped, then releases the lock

        lock_path = gitops.commit_lock_path(home)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "w", encoding="utf-8")
        # Same SEPARATE-open-file-description technique as
        # `test_refused_when_another_holder_has_the_ledger_lock` above:
        # a genuinely conflicting flock from this same process, standing
        # in for a second process holding the lock.
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write("999999\n")
        fh.flush()
        try:
            before = lock_path.read_bytes()
            status = intents.classify_status(home)
            after = lock_path.read_bytes()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

        assert status.probe == "busy"
        assert status.busy
        assert status.intents  # the STOPPED marker is still enumerated
        assert all(i.cls == "busy" for i in status.intents)
        assert status.stopped == []  # never classified "stopped" under contention
        assert after == before  # the probe never touched the holder's pid

    def test_a_non_contention_probe_failure_classifies_as_error(self, env, monkeypatch):
        home = env.ledger
        lock_path = gitops.commit_lock_path(home)
        real_open = os.open

        def raiser(path, *args, **kwargs):
            if str(path) == str(lock_path):
                raise PermissionError("probe denied for this test")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(intents.os, "open", raiser)
        status = intents.classify_status(home)
        assert status.probe == "error"
        assert not status.busy
        assert status.error
        assert status.intents == []


# =========================================== marker-publication failure


#: Gate r1 MAJOR-4, case (iii): a real child process that hooks
#: `intents._write_intent` to write a barrier and self-SIGKILL the
#: MOMENT `_mark_stopped` reaches for it -- before any byte of the
#: marker rewrite lands, matching `test_intents.py`'s own
#: barrier-then-kill discipline (`_COLLAPSE_CHILD`/`_REBIND_CHILD`).
_MARKER_KILL_CHILD = r"""
import os, signal
from self_learn import intents

BARRIER = os.environ["BARRIER"]

def _die(intent):
    with open(BARRIER, "w", encoding="utf-8") as fh:
        fh.write("write-marker")
    os.kill(os.getpid(), signal.SIGKILL)

intents._write_intent = _die
intents.recover(os.environ["SELF_LEARN_HOME"])
"""


class TestMarkerPublicationFailure:
    """§7.2a.3/§7.2a.8, all three marker-publication cases. (i) Caught
    failure BEFORE replacement: `_mark_stopped`'s own rewrite fails
    durably, but the STOP itself is still real -- both facts must reach
    the caller (`marker_uncertain`, the wording), and the intent file on
    disk must be untouched (the write never landed) -- exercised both
    starting unmarked (gate r1's own test) and starting with an earlier
    retry's OWN marker already on it (MINOR-3: the second write attempt
    must overwrite that stale marker with THIS attempt's own facts, not
    leave the earlier one standing). (ii) Caught failure AFTER
    replacement (the directory fsync raising): same two-fact report, but
    `os.replace` already landed -- the file carries the NEW marker, not
    the pre-attempt bytes. (iii) Process death (a real SIGKILL, not a
    caught exception) before the marker rewrite starts at all: the file
    is readable and unmarked, and there is no surviving caller to report
    anything -- the NEXT ledger write (a fresh, independent attempt)
    decides purely from what it reads, whether that means marking it
    stopped again (the fault is still there) or finishing it cleanly
    (something repaired the underlying content in between)."""

    def test_a_write_failure_before_replace_is_reported_uncertain_not_silent(
        self, env, monkeypatch
    ):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        before_bytes = stop.file_path.read_bytes()

        def raiser(intent):
            raise OSError("disk full before the atomic replace")

        monkeypatch.setattr(intents, "_write_intent", raiser)

        with pytest.raises(intents.LedgerStoppedError) as excinfo:
            with intents.ledger_write(home):
                pass

        detail = excinfo.value.result.stopped_detail
        assert [d.id for d in detail] == [stop.id]
        assert detail[0].marker_uncertain
        assert "could not be durably confirmed" in str(excinfo.value)
        # The write never landed -- the file is exactly what `_plant_stop`
        # left it (never rewritten with a `stopped` field at all).
        assert stop.file_path.read_bytes() == before_bytes

    def test_a_write_failure_before_replace_starting_from_an_earlier_markers_own_bytes(
        self, env, monkeypatch
    ):
        """MINOR-3: case (i)'s second sub-case -- this is not the
        intent's FIRST failed attempt. A prior attempt already
        durably wrote a `stopped` marker (a real, successful
        `_mark_stopped` call); THIS attempt's own rewrite then fails
        before replacement. The file must be untouched by the failed
        attempt -- i.e. it still carries the EARLIER marker's bytes,
        not the pre-transaction bytes and not any hint of this
        attempt -- and the caller still gets both facts."""
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        first = intents.recover(home)  # a real, successful mark -- no fault yet
        assert [d.id for d in first.stopped_detail] == [stop.id]
        assert not first.stopped_detail[0].marker_uncertain
        earlier_marker_bytes = stop.file_path.read_bytes()
        assert b'"stopped"' in earlier_marker_bytes

        def raiser(intent):
            raise OSError("disk full before the atomic replace, on retry")

        monkeypatch.setattr(intents, "_write_intent", raiser)

        with pytest.raises(intents.LedgerStoppedError) as excinfo:
            with intents.ledger_write(home):
                pass

        detail = excinfo.value.result.stopped_detail
        assert [d.id for d in detail] == [stop.id]
        assert detail[0].marker_uncertain
        assert "could not be durably confirmed" in str(excinfo.value)
        # This retry's own rewrite never landed -- the earlier marker
        # (not the pre-transaction bytes) is exactly what survives.
        assert stop.file_path.read_bytes() == earlier_marker_bytes

    def test_a_post_replace_directory_fsync_failure_still_reports_two_facts_but_the_new_bytes_land(
        self, env, monkeypatch
    ):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))

        real_fsync = os.fsync
        calls = {"n": 0}

        def raiser(fd):
            calls["n"] += 1
            if calls["n"] == 2:  # 1st = the temp file's own fsync; 2nd = the directory's
                raise OSError("directory fsync failed for this test")
            return real_fsync(fd)

        monkeypatch.setattr(fsops.os, "fsync", raiser)

        with pytest.raises(intents.LedgerStoppedError) as excinfo:
            with intents.ledger_write(home):
                pass

        detail = excinfo.value.result.stopped_detail
        assert [d.id for d in detail] == [stop.id]
        assert detail[0].marker_uncertain
        assert "could not be durably confirmed" in str(excinfo.value)
        # Unlike case (i): `os.replace` already landed before the
        # directory fsync raised -- the file carries the NEW marker.
        data = json.loads(stop.file_path.read_text(encoding="utf-8"))
        assert data["stopped"]["reason"]

    def test_process_death_before_the_marker_write_starts_leaves_the_file_unmarked(
        self, env, tmp_path
    ):
        home = env.ledger
        stop = _plant_stop(home, _probe_file(home))
        before_bytes = stop.file_path.read_bytes()
        assert b'"stopped"' not in before_bytes  # sanity: genuinely unmarked

        barrier = tmp_path / "barrier"
        proc = _run_child(_MARKER_KILL_CHILD, {"SELF_LEARN_HOME": str(home)}, barrier)
        _assert_killed(proc, barrier, "write-marker")

        # No bytes of the rewrite landed at all -- exactly what
        # `_plant_stop` left, and no surviving caller to report anything.
        assert stop.file_path.read_bytes() == before_bytes

        # "the fault is still active": the underlying content is still
        # unresolvable -- the NEXT, independent ledger write marks it
        # stopped on its own, unmonkeypatched attempt.
        result = intents.recover(home)
        assert [d.id for d in result.stopped_detail] == [stop.id]
        assert not result.stopped_detail[0].marker_uncertain
        data = json.loads(stop.file_path.read_text(encoding="utf-8"))
        assert data["stopped"]["reason"]

    def test_process_death_before_the_marker_write_starts_then_a_repaired_target_finishes_on_retry(
        self, env, tmp_path
    ):
        home = env.ledger
        target = _probe_file(home)
        original = target.read_text(encoding="utf-8")
        stop = _plant_stop(home, target)

        barrier = tmp_path / "barrier"
        proc = _run_child(_MARKER_KILL_CHILD, {"SELF_LEARN_HOME": str(home)}, barrier)
        _assert_killed(proc, barrier, "write-marker")

        # "the fault is cleared": something repairs the target back to
        # its pre-transaction bytes between the crash and the retry --
        # `_resolvable_old_bytes`'s "already-correct on disk" leg.
        target.write_text(original, encoding="utf-8")

        result = intents.recover(home)
        assert result.stopped_detail == []
        assert result.restored == [stop.id]
        assert not stop.file_path.exists()  # `finish()` removed the marker
        assert target.read_text(encoding="utf-8") == original
