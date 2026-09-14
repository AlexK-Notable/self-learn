"""O-2a — `hook_activation.py`, the human `self-learn hook activate` /
`hook deactivate` verbs, and the `overseer.hook_activation` committed-
config gate reader (`13-hosting-and-separation.md` §7.4; `03-decisions.md`
S-66; `02-schema.md` §2 as amended: `history`'s closed set gains
`hook-activated`/`hook-deactivated`).

**Safety**: every test here resolves the Claude runtime directory through
`SELF_LEARN_CLAUDE_DIR` pointed at a `tmp_path` (the `env` fixture below).
No verb in this module is ever called against the real `~/.claude` — the
module-scoped `_real_claude_dir_never_touched` fixture is a positive
control on that fact, not merely a claim: it compares a RECURSIVE
listing of the real directory's `settings.json`, every
`settings.json.self-learn-bak.*`, and everything under `hooks/` (path,
size, mtime_ns) before and after every test in this file ran (fold r1,
D-h — the earlier module-scoped-lstat control only observed the parent
directory's OWN metadata, which a write inside `hooks/` never changes;
see `TestRealDirSnapshotObservesNestedWrites` below for the measured
proof). A per-test autouse fixture additionally asserts
`SELF_LEARN_CLAUDE_DIR` is set to a path under THIS test's own tmp dir
before every test runs.

Plan-overseer §O-2 tests 1-7 and 9 (build-o2a.md's numbering; test 8 is
O-2b's, not built here), the brief's two "Plus" extras, and fold r1's
own D-a..D-h + N7-N9 tests (`fold-o2a-r1.md`)."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from pathlib import Path

import pytest

from self_learn import cli, config, hook_activation, intents, selfcheck, verbs
from self_learn.hook_compiler import command_for, command_root, script_name, settings_snippet
from self_learn.records import Record
from support import git, hook_proposal_fields, make_behavior
from test_recover_or_refuse import _plant_stop, _probe_file
from test_route_hook import Env as RouteEnv
from test_route_hook import TRIGGER, seed_hook

RID = "lrn-0000eeee"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = RouteEnv(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.home))
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    e.claude = claude
    return e


@pytest.fixture(autouse=True)
def _claude_dir_isolated(env):
    """Fold r1, D-h (Opus S6 / Astra 10): asserts, before every test in
    this module runs, that `SELF_LEARN_CLAUDE_DIR` is actually set to a
    path under THIS test's own tmp dir — catches a future test in this
    file that forgets to request `env` (or a fixture that stops setting
    the override) before it can reach `hook_activation` at all."""
    override = os.environ.get("SELF_LEARN_CLAUDE_DIR")
    assert override is not None, (
        "SELF_LEARN_CLAUDE_DIR must be set for every test in this module"
    )
    assert Path(override) == env.claude
    yield


# --------------------------------------------- real ~/.claude positive control

_REAL_CLAUDE_DIR = Path.home() / ".claude"


def _snapshot_claude_dir(base: Path):
    """Fold r1, D-h (gate SHOULD-FIX 6 / Astra 10): a RECURSIVE listing
    — `settings.json`, every `settings.json.self-learn-bak.*`, and
    everything under `hooks/` — each as (relative path, size,
    mtime_ns). `None` when `base` does not exist. Takes a directory
    argument so it can be exercised on a scratch dir in
    `TestRealDirSnapshotObservesNestedWrites` below without ever
    touching the real one."""
    if not base.is_dir():
        return None
    entries: list[tuple[str, int, int]] = []
    settings = base / "settings.json"
    if settings.exists():
        st = settings.lstat()
        entries.append((str(settings.relative_to(base)), st.st_size, st.st_mtime_ns))
    for bak in sorted(base.glob("settings.json.self-learn-bak.*")):
        st = bak.lstat()
        entries.append((str(bak.relative_to(base)), st.st_size, st.st_mtime_ns))
    hooks_dir = base / "hooks"
    if hooks_dir.is_dir():
        for p in sorted(hooks_dir.rglob("*")):
            st = p.lstat()
            entries.append((str(p.relative_to(base)), st.st_size, st.st_mtime_ns))
    return tuple(entries)


def _snapshot_real_claude_dir():
    return _snapshot_claude_dir(_REAL_CLAUDE_DIR)


@pytest.fixture(scope="module", autouse=True)
def _real_claude_dir_never_touched():
    """Plus (build-o2a.md), widened fold r1 D-h: a positive control that
    this module's tests truly never reach the real ``~/.claude`` — not
    merely that ``SELF_LEARN_CLAUDE_DIR`` was set (a bug could still
    ignore it, or a fixture could forget to set it). A missing real
    directory is a SKIP with a message, never a silent pass (D-h)."""
    if not _REAL_CLAUDE_DIR.is_dir():
        pytest.skip(
            f"{_REAL_CLAUDE_DIR} does not exist on this machine -- cannot "
            "prove it was left untouched"
        )
    before = _snapshot_real_claude_dir()
    yield
    after = _snapshot_real_claude_dir()
    assert after == before, (
        "the real ~/.claude directory changed while test_hook_activation.py "
        "ran -- every test must resolve SELF_LEARN_CLAUDE_DIR to a tmp_path, "
        "and something here did not"
    )


class TestRealDirSnapshotObservesNestedWrites:
    """Fold r1, D-h / gate SHOULD-FIX 6: the module-scoped control above
    must actually OBSERVE a write inside ``hooks/`` — never on the real
    directory, always a scratch one here."""

    def test_snapshot_detects_new_symlink_under_hooks(self, tmp_path):
        fake = tmp_path / "fake-claude"
        (fake / "hooks").mkdir(parents=True)
        before = _snapshot_claude_dir(fake)
        target = tmp_path / "some-script.sh"
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        (fake / "hooks" / "self-learn-x.sh").symlink_to(target)

        after = _snapshot_claude_dir(fake)

        assert after != before

    def test_parent_lstat_alone_would_have_missed_it(self, tmp_path):
        # Reproduces the OLD (pre-fold) control's own mechanism to show
        # WHY it was insufficient -- this test PASSING is the measured
        # proof of the gap SHOULD-FIX 6 named, not a defect in this
        # test file.
        fake = tmp_path / "fake-claude"
        (fake / "hooks").mkdir(parents=True)
        before = fake.lstat()
        target = tmp_path / "some-script.sh"
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        (fake / "hooks" / "self-learn-x.sh").symlink_to(target)

        after = fake.lstat()

        assert (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size)


# ------------------------------------------------------------------ helpers


def route_hook(env, rid, **proposal_overrides):
    """Route a real hook record through the production ``verbs.route``
    path (proposal sibling included, then swept — see
    ``hook_activation._examples_for``'s docstring). Returns
    ``(script_name, host_relative_path)``."""
    seed_hook(env, rid=rid, **proposal_overrides)
    verbs.route(env.home, rid)
    name = script_name(rid, TRIGGER)
    return name, f"plugins/s-plugin/hooks/{name}"


def link_path(env, name):
    return env.claude / "hooks" / name


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def resolved_record(env, rid=RID):
    return Record.from_path(env.bucket / "resolved" / f"{rid}.md")


# ---------------------------------------------------------------- test 1


class TestPlaced:
    def test_symlink_placed_to_the_right_target(self, env):
        # Mutation witness (build-o2a.md test 1): pointing the placed
        # symlink at the script's PARENT directory instead of the script
        # itself reddens the `link.resolve() == ...` assertion below —
        # verified by hand-editing `activate()`'s `_write_claude_runtime(
        # link=link, link_target=script_abs, ...)` call to pass
        # `script_abs.parent`, confirmed RED, reverted, confirmed GREEN.
        name, rel = route_hook(env, RID)
        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=False
        )
        assert result.steps[0].step == "placed"
        link = link_path(env, name)
        assert link.is_symlink()
        assert link.resolve() == (env.host / rel).resolve()

    def test_idempotent_when_already_placed(self, env):
        name, rel = route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=False)
        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=False
        )
        assert "idempotent" in result.steps[0].detail


# ---------------------------------------------------------------- test 2


class TestConflict:
    def test_existing_different_target_symlink_refuses(self, env):
        # Mutation witness (test 2): commenting out the
        # `if classification == "conflict": raise HookActivationError(...)`
        # block (silently overwriting instead) reddens the
        # `pytest.raises` block below — verified, reverted, confirmed
        # GREEN.
        name, rel = route_hook(env, RID)
        other = env.claude / "other-script.sh"
        other.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        other.chmod(0o755)
        link = link_path(env, name)
        link.symlink_to(other)
        settings = env.claude / "settings.json"

        with pytest.raises(hook_activation.HookActivationError, match="refusing"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        # untouched: still points at the wrong target, no settings write
        assert os.readlink(link) == str(other)
        assert not settings.exists()


# ---------------------------------------------------------------- test 3


class TestUnparseableSettings:
    def test_unparseable_settings_refuses_before_any_write(self, env):
        # Mutation witness (test 3): treating the parse `problem` as if
        # it were an empty `{}` (removing the `if problem is not None:
        # raise ...` guard in `activate()`) reddens the `pytest.raises`
        # block — verified, reverted, confirmed GREEN.
        name, rel = route_hook(env, RID)
        settings = env.claude / "settings.json"
        settings.write_text("{not json", encoding="utf-8")
        before = sha(settings)

        with pytest.raises(hook_activation.HookActivationError, match="unparseable"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        assert sha(settings) == before
        # Fold r1, D-b: all-or-nothing -- step 1's symlink placement is
        # undone too, since this call's overall activation never
        # completed. A failed activation never leaves a half-state.
        assert not link_path(env, name).exists()


# ---------------------------------------------------------------- test 4


class TestIdempotentRegistration:
    def test_second_activate_hash_equal(self, env):
        # Mutation witness (test 4): forcing `_merge_snippet` to always
        # report `changed=True` (simulating "append duplicate") reddens
        # both the hash-equality and backup-count assertions below —
        # verified, reverted, confirmed GREEN.
        route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        settings = env.claude / "settings.json"
        first_hash = sha(settings)
        backups_after_first = sorted(env.claude.glob("settings.json.self-learn-bak.*"))

        result2 = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )

        assert sha(settings) == first_hash
        backups_after_second = sorted(env.claude.glob("settings.json.self-learn-bak.*"))
        assert backups_after_second == backups_after_first  # no NEW backup
        registered = next(s for s in result2.steps if s.step == "registered")
        assert "idempotent" in registered.detail


# ---------------------------------------------------------------- test 5


class TestBackupPrunedToFive:
    def test_backup_written_and_pruned_to_five(self, env):
        # Fold r2, item A: pruning moved OUT of `hook_activation.activate`
        # entirely -- it now runs in the VERB, `verbs._prune_hook_backups`,
        # only after `_commit_ledger` has succeeded. This test now drives
        # the CLI end to end (was: calling `hook_activation.activate`
        # directly, which no longer prunes at all). Mutation witness:
        # commenting out the `hook_activation._write_claude_runtime(
        # prune_backups=stale)` call in `verbs._prune_hook_backups`
        # reddens the `len(backups) == ...` assertion below (leaves all
        # 7 backups instead of 5) -- verified, reverted, confirmed GREEN.
        claude = env.claude
        (claude / "settings.json").write_text("{}", encoding="utf-8")
        n_records = hook_activation._BACKUP_KEEP + 2  # forces pruning
        first_backup: Path | None = None
        for i in range(1, n_records + 1):
            rid = f"lrn-0000ee{i:02d}"
            route_hook(env, rid)
            rc = cli.main(["hook", "activate", rid, "--no-push"])
            assert rc == 0
            backups_now = sorted(claude.glob("settings.json.self-learn-bak.*"))
            if i == 1:
                first_backup = backups_now[0] if backups_now else None

        backups = sorted(claude.glob("settings.json.self-learn-bak.*"))
        assert len(backups) == hook_activation._BACKUP_KEEP
        assert first_backup is not None and not first_backup.exists()  # pruned, oldest first

    def test_activate_alone_never_prunes(self, env):
        # Positive control for the move itself: calling
        # `hook_activation.activate` DIRECTLY -- never through the verb
        # -- must NOT prune, however many backups already exist. Proves
        # the test above is not vacuous (it would still pass if pruning
        # had simply moved to run unconditionally somewhere else that
        # this direct call also reaches).
        claude = env.claude
        (claude / "settings.json").write_text("{}", encoding="utf-8")
        n_records = hook_activation._BACKUP_KEEP + 2
        for i in range(1, n_records + 1):
            rid = f"lrn-0000ef{i:02d}"
            route_hook(env, rid)
            result = hook_activation.activate(
                env.home, rid, claude_dir=claude, register=True
            )
            assert result.backup_path is not None
            assert result.backup_path.is_file()

        backups = sorted(claude.glob("settings.json.self-learn-bak.*"))
        assert len(backups) == n_records  # nothing pruned -- the verb never ran


# ---------------------------------------------------------------- test 6


class TestReplayAbortsBeforeRegistering:
    def test_replay_mismatch_aborts_after_placing_before_registering(self, env):
        # Mutation witness (test 6): commenting out the
        # `if mismatches: raise HookActivationError(...)` block
        # ("swallow the failure") reddens the `pytest.raises` block below
        # — verified, reverted, confirmed GREEN.
        #
        # Fold r1, D-e changed WHERE examples live at activation time:
        # `route()` persists them onto `routing.hook.examples` now (the
        # proposal sibling is still swept, same as before), so a bad
        # example is injected by editing the RECORD's own persisted
        # examples directly -- re-authoring the (now-irrelevant, already
        # swept) proposal sibling no longer has any effect.
        name, rel = route_hook(env, RID)
        assert not (env.bucket / "proposals" / f"{RID}.yaml").exists()  # swept
        path = env.bucket / "resolved" / f"{RID}.md"
        record = Record.from_path(path)
        routing = dict(record.routing)
        hook_meta = dict(routing["hook"])
        hook_meta["examples"] = {
            "allow": [
                # WRONG on purpose: matches the guard's own deny regex
                # (`\.storage/`)
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/x/.storage/wrong.json"},
                },
            ],
            "deny": [
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/y/.storage/right.json"},
                },
            ],
        }
        routing["hook"] = hook_meta
        record.set_routing(routing)
        record.write(path)
        settings = env.claude / "settings.json"

        with pytest.raises(hook_activation.HookActivationError, match=r"allow\[0\]"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        # Fold r1, D-b: all-or-nothing -- the symlink this call placed
        # is undone on ANY later failure, including a replay mismatch.
        assert not link_path(env, name).exists()
        # step 2 never ran: no settings.json write at all
        assert not settings.exists()

    def test_no_examples_recorded_is_honestly_reported_not_clean(self, env):
        # Fold r1, D-e: a record routed BEFORE this amendment persisted
        # examples (its own meta never got them, and its proposal is
        # long swept) has genuinely NOTHING to replay -- the
        # activation-checked receipt must say so plainly rather than
        # ever claiming a "clean replay" it never ran (lrn-ea833a5b's
        # class -- a zero-coverage check must never read identically to
        # a real pass). Simulated here by stripping the just-persisted
        # examples back off, reproducing a pre-amendment record.
        route_hook(env, RID)
        path = env.bucket / "resolved" / f"{RID}.md"
        record = Record.from_path(path)
        routing = dict(record.routing)
        hook_meta = dict(routing["hook"])
        del hook_meta["examples"]
        routing["hook"] = hook_meta
        record.set_routing(routing)
        record.write(path)
        assert not (env.bucket / "proposals" / f"{RID}.yaml").exists()  # swept

        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )

        # Fold r2, item G (Astra 8): the STEP LABEL itself, not only the
        # detail text, must say a replay never ran -- "activation-checked"
        # is reserved for a record that actually HAD examples to replay.
        assert "activation-checked" not in {s.step for s in result.steps}
        checked = next(s for s in result.steps if s.step == "doctor-checked")
        assert "no examples recorded on this record" in checked.detail
        assert "replayed clean" not in checked.detail
        assert result.replay == "skipped-no-examples"

    def test_activation_checked_receipt_does_not_overclaim_doctor_verification(
        self, env
    ):
        # Fold r1, gate NIT 8: the pre-fold receipt said "the doctor's
        # byte-identity check below is the live verification" /
        # "registration verified live by the doctor's own hook check" --
        # but _check_hooks reads the approved bytes at the HOST path and
        # only .exists()-checks the symlink; it never reads bytes
        # THROUGH the link. The receipt must say only what was actually
        # verified (the gate's own suggested wording), never more.
        route_hook(env, RID)
        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )
        checked = next(s for s in result.steps if s.step == "activation-checked")
        assert (
            "the doctor confirms the approved bytes at the host path and "
            "that the symlink resolves" in checked.detail
        )
        assert "byte-identity check below is the live verification" not in checked.detail
        assert "verified live by the doctor's own hook check" not in checked.detail


# ---------------------------------------------------------------- test 7


class TestGateReader:
    def write_config(self, env, text):
        (env.home / "config.yaml").write_text(text, encoding="utf-8")

    def test_true_enables(self, env):
        self.write_config(env, "overseer:\n  hook_activation: true\n")
        assert config.hook_activation_enabled(env.home) is True

    def test_absent_disabled_silently(self, env, capsys):
        assert config.hook_activation_enabled(env.home) is False
        assert capsys.readouterr().err == ""

    def test_explicit_false_disabled_silently(self, env, capsys):
        self.write_config(env, "overseer:\n  hook_activation: false\n")
        assert config.hook_activation_enabled(env.home) is False
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize(
        "text",
        [
            "overseer:\n  hook_activation: yes\n",
            "overseer:\n  hook_activation: 1\n",
            'overseer:\n  hook_activation: "true"\n',
        ],
    )
    def test_malformed_truthy_disabled_and_warns(self, env, capsys, text):
        # Mutation witness (test 7): widening `if value is True: return
        # True` to `if value: return True` ("treat truthy as true") makes
        # every case here read as enabled -- reddens all three
        # parametrized `is False` assertions -- verified, reverted,
        # confirmed GREEN.
        self.write_config(env, text)
        assert config.hook_activation_enabled(env.home) is False
        err = capsys.readouterr().err
        assert "config.yaml ignored" in err
        assert "overseer.hook_activation" in err


# ---------------------------------------------------------------- test 9


class TestDeactivateReversal:
    def test_deactivate_removes_symlink_and_settings_and_writes_history(self, env):
        # Mutation witness (test 9): commenting out `record.
        # append_history("hook-deactivated", ...)` in `verbs.
        # hook_deactivate` reddens the `"hook-deactivated" in kinds`
        # assertion below (symlink/settings assertions stay green) --
        # verified, reverted, confirmed GREEN.
        name, rel = route_hook(env, RID)
        pre_existing = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "$HOME/.claude/hooks/unrelated.sh",
                            }
                        ]
                    }
                ]
            }
        }
        settings = env.claude / "settings.json"
        settings.write_text(json.dumps(pre_existing, indent=2) + "\n", encoding="utf-8")
        original_bytes = settings.read_bytes()

        rc = cli.main(["hook", "activate", RID, "--no-push"])
        assert rc == 0
        link = link_path(env, name)
        assert link.is_symlink()
        assert settings.read_bytes() != original_bytes  # our command was inserted

        rc = cli.main(["hook", "deactivate", RID, "--no-push"])
        assert rc == 0
        assert not link.exists()
        # restored byte-for-byte -- the unrelated SessionStart entry
        # survives untouched, AND the PreToolUse key we added is gone
        # entirely (fold r1, D-a: surgical removal, never a whole-file
        # restore -- this is still byte-identical because dropping the
        # only entry we ever added is EXACTLY the original shape).
        assert settings.read_bytes() == original_bytes

        record = resolved_record(env)
        kinds = [h.get("event") for h in record.history]
        assert "hook-activated" in kinds
        assert "hook-deactivated" in kinds


# ---------------------------------------------------------------- plus 1


class TestHumanPathIgnoresGate:
    def test_cli_activate_registers_even_with_gate_false(self, env):
        # Mutation witness (Plus 1): changing `verbs.hook_activate`'s
        # `hook_activation.activate(..., register=True)` call to
        # `register=config.hook_activation_enabled(home)` ("make the CLI
        # read the gate") reddens the `command in settings...` assertion
        # below when the gate is false -- verified, reverted, confirmed
        # GREEN.
        name, rel = route_hook(env, RID)
        (env.home / "config.yaml").write_text(
            "overseer:\n  hook_activation: false\n", encoding="utf-8"
        )
        assert config.hook_activation_enabled(env.home) is False  # gate genuinely off

        rc = cli.main(["hook", "activate", RID, "--no-push"])

        assert rc == 0
        settings = env.claude / "settings.json"
        # Fold r1, D-d: env.claude is an OVERRIDE runtime directory (it
        # is never the real ~/.claude), so the command names it
        # literally rather than the portable $HOME form.
        command = f"{env.claude}/hooks/{name}"
        assert command in settings.read_text(encoding="utf-8")

    def test_register_false_positive_control_genuinely_skips_step_2(self, env):
        # Proves the assertion above is not vacuous: `register=False` on
        # the SAME module-level function really does skip registration —
        # if it didn't, the CLI test's pass would tell us nothing about
        # whether the gate was really being ignored.
        route_hook(env, RID)
        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=False
        )
        assert {s.step for s in result.steps} == {"placed", "delegated"}
        assert not (env.claude / "settings.json").exists()


# ================================================== fold r1 (2026-09-14)


# ---------------------------------------------------------- D-a (surgical
# deactivate) — Opus B1, Astra 1+2


class TestDeactivateIsSurgical:
    def test_sibling_command_in_same_item_survives_deactivation(self, env):
        # D-a (i) / Astra 2's exact defect shape: TWO commands sharing
        # ONE PreToolUse item's "hooks" list -- `_merge_snippet` itself
        # never produces this (it always appends a brand-new item, even
        # for a repeated matcher), but a hand-edit that merges a second
        # command into an existing item does, and `_remove_command` must
        # handle it correctly regardless of how the shape arose.
        # Deactivating one must leave the OTHER's dict in place inside
        # that SAME item, not drop the whole item. Mutation witness:
        # restoring the old `if has_cmd: ... continue` body (drop the
        # whole item on any match) reddens the `command_b in text`
        # positive control below -- verified, reverted, confirmed GREEN.
        rid_a, rid_b = "lrn-0000aaa1", "lrn-0000aaa2"
        name_a, _ = route_hook(env, rid_a)
        name_b, _ = route_hook(env, rid_b)
        hook_activation.activate(env.home, rid_a, claude_dir=env.claude, register=False)
        hook_activation.activate(env.home, rid_b, claude_dir=env.claude, register=False)
        command_a = hook_activation._command_for(name_a, env.claude)
        command_b = hook_activation._command_for(name_b, env.claude)
        settings = env.claude / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Edit|Write",
                                "hooks": [
                                    {"type": "command", "command": command_a},
                                    {"type": "command", "command": command_b},
                                ],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        hook_activation.deactivate(env.home, rid_a, claude_dir=env.claude)

        text = settings.read_text(encoding="utf-8")
        assert command_a not in text  # positive control: A really gone
        assert command_b in text  # B survives, same item

    def test_registration_made_after_activation_survives_deactivation(self, env):
        # D-a (ii) = Opus B1's exact probe scenario: seed an unrelated
        # SessionStart hook, route+activate A then B, deactivate ONLY
        # A -- B's registration AND symlink must both survive, proving
        # deactivate never restores a whole-file backup taken BEFORE B
        # ever existed. Mutation witness: restoring the deleted
        # backup-restore branch in `deactivate()` reddens
        # `command_b in text` (and `link_path(env, name_b).is_symlink()`)
        # below -- verified, reverted, confirmed GREEN.
        pre_existing = {
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/unrelated.sh"}]}
                ]
            }
        }
        settings = env.claude / "settings.json"
        settings.write_text(json.dumps(pre_existing, indent=2) + "\n", encoding="utf-8")

        rid_a, rid_b = "lrn-0000bbb1", "lrn-0000bbb2"
        name_a, _ = route_hook(env, rid_a)
        name_b, _ = route_hook(env, rid_b)
        hook_activation.activate(env.home, rid_a, claude_dir=env.claude, register=True)
        hook_activation.activate(env.home, rid_b, claude_dir=env.claude, register=True)

        hook_activation.deactivate(env.home, rid_a, claude_dir=env.claude)

        text = settings.read_text(encoding="utf-8")
        command_a = hook_activation._command_for(name_a, env.claude)
        command_b = hook_activation._command_for(name_b, env.claude)
        assert command_a not in text
        assert command_b in text
        assert "unrelated.sh" in text
        assert link_path(env, name_b).is_symlink()  # B's guard still live

    def test_same_command_under_different_matcher_refuses_naming_both(self, env):
        # D-a (iii) / Astra 6: the SAME command string registered under
        # a DIFFERENT matcher must never be silently accepted (it would
        # leave the guard live for the wrong tool set) or silently
        # rewritten (that registration is not this call's to touch).
        # Mutation witness: dropping the `other_matcher is not None:
        # raise` branch in `_merge_snippet` reddens the `pytest.raises`
        # block below -- verified, reverted, confirmed GREEN.
        name, rel = route_hook(env, RID)
        settings = env.claude / "settings.json"
        command = hook_activation._command_for(name, env.claude)
        pre_existing = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Read", "hooks": [{"type": "command", "command": command}]}
                ]
            }
        }
        settings.write_text(json.dumps(pre_existing, indent=2) + "\n", encoding="utf-8")

        with pytest.raises(hook_activation.HookActivationError) as exc_info:
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        message = str(exc_info.value)
        assert "'Read'" in message
        assert "'Edit|Write'" in message
        # fold r1, D-b: the placement this call DID make is undone too.
        assert not link_path(env, name).exists()


# ------------------------------------------------- D-b (runtime writes
# inside the ledger lock, all-or-nothing) — Opus B2, Astra 3+5


class TestStopRefusesBeforeAnyRuntimeChange:
    def test_activate_stop_leaves_runtime_dir_untouched(self, env):
        # D-b (i): a live STOP must refuse BEFORE the runtime directory
        # is ever mutated. Mutation witness: moving the
        # `hook_activation.activate(...)` call back OUTSIDE the `with
        # _ledger_write(home)` span in `verbs.hook_activate` reddens the
        # `not link.exists()` assertion below (the symlink gets placed
        # before the STOP is ever observed) -- verified, reverted,
        # confirmed GREEN.
        name, rel = route_hook(env, RID)
        _plant_stop(env.home, _probe_file(env.home))
        link = link_path(env, name)
        settings = env.claude / "settings.json"

        with pytest.raises(intents.LedgerStoppedError):
            verbs.hook_activate(env.home, RID, no_push=True)

        assert not link.exists()  # never placed
        assert not settings.exists()  # never created
        record = resolved_record(env)
        kinds = [h.get("event") for h in record.history]
        assert "hook-activated" not in kinds

    def test_deactivate_stop_leaves_runtime_dir_untouched(self, env):
        # Same guarantee, the deactivate side (gate's P1-DEACT probe).
        name, rel = route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        settings = env.claude / "settings.json"
        link = link_path(env, name)
        assert link.exists()
        settings_before = settings.read_bytes()
        _plant_stop(env.home, _probe_file(env.home))

        with pytest.raises(intents.LedgerStoppedError):
            verbs.hook_deactivate(env.home, RID, no_push=True)

        assert link.exists()  # still placed -- never touched
        assert settings.read_bytes() == settings_before
        record = resolved_record(env)
        kinds = [h.get("event") for h in record.history]
        assert "hook-deactivated" not in kinds


class TestFailureAfterPlacementUndoesEverything:
    def test_settings_write_failure_undoes_symlink_and_settings_no_history(
        self, env, monkeypatch
    ):
        # D-b (ii): a failure injected AFTER placement (the settings
        # write itself) must undo what this call did -- symlink gone,
        # settings bytes identical, no history entry, ledger HEAD
        # unchanged. Mutation witness: deleting the
        # `except BaseException:` undo block in `activate()` reddens
        # BOTH the `not link.exists()` and the settings-byte-equality
        # assertions below (the placed symlink and the half-written
        # settings.json both survive the raise) -- verified, reverted,
        # confirmed GREEN.
        name, rel = route_hook(env, RID)
        pre_existing = {
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/unrelated.sh"}]}
                ]
            }
        }
        settings = env.claude / "settings.json"
        settings.write_text(json.dumps(pre_existing, indent=2) + "\n", encoding="utf-8")
        original_bytes = settings.read_bytes()

        real_write = hook_activation._write_claude_runtime
        seen = {"n": 0}

        def spy(**kwargs):
            if kwargs.get("settings_bytes") is not None:
                seen["n"] += 1
                if seen["n"] == 1:
                    raise OSError("simulated settings-write failure")
            return real_write(**kwargs)

        monkeypatch.setattr(hook_activation, "_write_claude_runtime", spy)
        sha_before = git(env.home, "rev-parse", "HEAD").stdout.strip()

        with pytest.raises(OSError, match="simulated"):
            verbs.hook_activate(env.home, RID, no_push=True)

        link = link_path(env, name)
        assert not link.exists()  # symlink placed, then undone
        assert settings.read_bytes() == original_bytes  # restored exactly
        sha_after = git(env.home, "rev-parse", "HEAD").stdout.strip()
        assert sha_after == sha_before  # nothing committed
        record = resolved_record(env)
        kinds = [h.get("event") for h in record.history]
        assert "hook-activated" not in kinds


# --------------------------------------------------------- D-c (byte check
# before placement; step 3's own test) — Astra 4 / Opus B3 / N10


class TestByteCheckBeforePlacement:
    # Both tests here use register=False DELIBERATELY: with register=True,
    # step 3's doctor verdict ALSO independently detects script drift
    # (`selfcheck._check_hooks`'s own byte-identity check) and raises a
    # message that happens to share the substring "approved bytes" too --
    # a test using register=True would stay green even with THIS
    # module's own byte check deleted outright, since the doctor catches
    # the same drift one step later and the undo-on-failure logic cleans
    # up regardless of which check caught it. register=False never
    # reaches step 3 at all, so only D-c's own check can refuse here --
    # confirmed empirically: the register=True version of this test was
    # tried first and found to stay GREEN under the byte-check-deleted
    # mutation (a false pass), which is why these use register=False.
    def test_drifted_script_refuses_before_placing(self, env):
        # Mutation witness: commenting out the byte-check block near the
        # top of `activate()` reddens the `pytest.raises` block below --
        # verified, reverted, confirmed GREEN.
        name, rel = route_hook(env, RID)
        script_path = env.host / rel
        script_path.write_text(
            script_path.read_text(encoding="utf-8") + "\n# hand-edited\n",
            encoding="utf-8",
        )

        with pytest.raises(hook_activation.HookActivationError, match="approved bytes"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=False)

        assert not link_path(env, name).exists()
        assert not (env.claude / "settings.json").exists()

    def test_drifted_script_message_distinguishable_from_settings_drift(self, env):
        # N10-adjacent: the refusal must name the SCRIPT, not read like
        # generic settings.json trouble.
        name, rel = route_hook(env, RID)
        script_path = env.host / rel
        script_path.write_text(
            script_path.read_text(encoding="utf-8") + "\n# hand-edited\n",
            encoding="utf-8",
        )

        with pytest.raises(hook_activation.HookActivationError) as exc_info:
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=False)

        assert str(script_path) in str(exc_info.value)
        assert "settings.json" not in str(exc_info.value)


class TestDoctorVerdictAbortsAfterRegistering:
    def test_unrelated_dangling_registration_aborts_and_undoes(self, env):
        # D-c: step 3's doctor verdict covers the WHOLE runtime dir, not
        # just this registration -- an unrelated dangling self-learn-*
        # entry (test_selftest_hooks.py's own shape for this) fails the
        # doctor and must abort AFTER registering, undoing what THIS
        # call did, and writing no `hook-activated` history. Mutation
        # witness: deleting the `if verdict is not
        # selfcheck.Verdict.PASS: raise ...` block reddens the
        # `pytest.raises` block below (M4 in the gate's own mutation
        # run) -- verified, reverted, confirmed GREEN.
        name, rel = route_hook(env, RID)
        settings = env.claude / "settings.json"
        unrelated_command = "$HOME/.claude/hooks/self-learn-deadbeef-unrelated.sh"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": unrelated_command}],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        # no symlink for the unrelated one -- dangling, doctor FAILs
        before_bytes = settings.read_bytes()

        with pytest.raises(
            hook_activation.HookActivationError, match="did not verify as live"
        ):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        # undone: our symlink removed, settings.json back to exactly
        # what it was before this call (the unrelated entry alone)
        assert not link_path(env, name).exists()
        assert settings.read_bytes() == before_bytes


# ------------------------------------------------------------- D-d (the
# registered command names the actual runtime directory) — Astra 7


class TestCommandRootDefaultVsOverride:
    def test_default_claude_dir_uses_home_form(self):
        # Pure-function test: `Path.home() / ".claude"` is passed as a
        # VALUE only, never read from or written to -- this never
        # touches the real directory.
        default = Path.home() / ".claude"
        assert command_root(default) == "$HOME/.claude"
        assert command_root(None) == "$HOME/.claude"
        snippet = settings_snippet(["Edit"], "self-learn-x.sh", claude_dir=default)
        assert '"command": "$HOME/.claude/hooks/self-learn-x.sh"' in snippet
        assert hook_activation._command_for("self-learn-x.sh", default) == (
            "$HOME/.claude/hooks/self-learn-x.sh"
        )

    def test_override_claude_dir_uses_literal_path(self, tmp_path):
        # Mutation witness: hardcoding `command_root` to always return
        # `"$HOME/.claude"` reddens the literal-path assertions below —
        # verified, reverted, confirmed GREEN.
        override = tmp_path / "custom-claude"
        assert command_root(override) == str(override)
        snippet = settings_snippet(["Edit"], "self-learn-x.sh", claude_dir=override)
        assert f'"command": "{override}/hooks/self-learn-x.sh"' in snippet
        assert hook_activation._command_for("self-learn-x.sh", override) == (
            f"{override}/hooks/self-learn-x.sh"
        )

    def test_route_time_snippet_stays_portable_home_form(self, env):
        # D-d: route's own printed two-step snippet is UNCHANGED by this
        # fold -- callers in verbs.py never pass claude_dir.
        seed_hook(env, rid=RID)
        result = verbs.route(env.home, RID)
        assert any("$HOME/.claude/hooks/" in note for note in result.post_notes)


# --------------------------------------------------- D-e (examples persist
# at route time) — Opus S4 / Astra 8


class TestExamplesPersistedAtRouteTime:
    def test_examples_persist_in_routing_hook_meta(self, env):
        # Mutation witness: reverting the `"examples": data["examples"]`
        # line added to `_prepare_hook_route`'s `meta` dict reddens the
        # `examples is not None` assertion below -- verified, reverted,
        # confirmed GREEN.
        route_hook(env, RID)
        record = resolved_record(env)
        examples = record.routing["hook"].get("examples")
        assert examples is not None
        assert examples["allow"] and examples["deny"]

    def test_one_motion_route_also_persists_examples(self, env):
        # The SAME persistence gap exists in `_prepare_one_motion_hook`
        # (verbs.py's other hook-route builder) -- applied there too
        # since both feed `routing["hook"] = hook_route.meta` (verbs.py
        # 4896) identically; not explicitly named by the fold brief's
        # own line-cite, but the SAME class of fix, flagged in the
        # report.
        (env.home / "config.yaml").write_text(
            "one_motion_route:\n  hook: true\n", encoding="utf-8"
        )
        rid = "lrn-0000ccc1"
        trigger = "About to edit `.storage/*.json` while HA is running."
        record = make_behavior(record_id=rid, trigger=trigger)
        verbs.route_direct(
            env.home,
            record,
            dest="hook",
            hook_input={
                "rationale": "deterministic guard",
                "alternates": ["skill-md"],
                **hook_proposal_fields(),
            },
            no_push=True,
        )
        landed = Record.from_path(env.resolved(rid))
        examples = landed.routing["hook"].get("examples")
        assert examples is not None
        assert examples["allow"] and examples["deny"]


# ----------------------------------------------------- D-f (exact bytes
# shown) — Astra 9


class TestExactBytesShown:
    def test_activate_result_carries_exact_entry_path_and_sha(self, env):
        # Mutation witness: not populating `hook_registered_entry`/
        # `hook_script_path`/`hook_script_sha256` on the returned
        # `ActivationResult` (leaving them `None`) reddens the
        # `is not None` assertions below -- verified, reverted,
        # confirmed GREEN.
        name, rel = route_hook(env, RID)
        script_path = env.host / rel
        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )

        assert result.hook_registered_entry is not None
        entry = json.loads(result.hook_registered_entry)
        assert entry["hooks"][0]["command"] == f"{env.claude}/hooks/{name}"
        assert result.hook_script_path == str(script_path)
        assert result.hook_script_sha256 == hashlib.sha256(script_path.read_bytes()).hexdigest()

        registered_step = next(s for s in result.steps if s.step == "registered")
        assert result.hook_registered_entry in registered_step.detail
        assert str(script_path) in registered_step.detail
        assert result.hook_script_sha256 in registered_step.detail

    def test_json_envelope_carries_hook_fields(self, env, capsys):
        route_hook(env, RID)

        rc = cli.main(["hook", "activate", RID, "--json", "--no-push"])

        assert rc == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["hook_registered_entry"] is not None
        assert envelope["hook_script_path"] is not None
        assert envelope["hook_script_sha256"] is not None

    def test_delegated_activation_carries_no_hook_fields(self, env):
        # register=False never reaches the registration step -- these
        # fields must stay None, never a stale/partial value.
        route_hook(env, RID)
        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=False
        )
        assert result.hook_registered_entry is None
        assert result.hook_script_path is None
        assert result.hook_script_sha256 is None


# ---------------------------------------------------- D-g (no phantom
# backup) — Opus S5


class TestBackupNoteWording:
    def test_idempotent_note(self, env):
        route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        result2 = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )

        assert result2.backup_path is None
        assert result2.backup_note == "no settings.json change (already registered)"

    def test_fresh_creation_note_is_truthful(self, env):
        # D-g / gate SHOULD-FIX 5: must NOT claim "no settings.json
        # change (already registered)" when a file WAS just created —
        # that note is false for this case (settings.json changed from
        # non-existent to existent). Mutation witness: collapsing both
        # branches to the SAME pinned "already registered" text reddens
        # the `"already registered" not in ...` assertion below --
        # verified, reverted, confirmed GREEN.
        assert not (env.claude / "settings.json").exists()
        route_hook(env, RID)

        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )

        assert result.backup_path is None  # nothing to back up -- no prior file
        assert "created" in result.backup_note
        assert "already registered" not in result.backup_note

    def test_real_backup_note_names_the_file(self, env):
        (env.claude / "settings.json").write_text("{}", encoding="utf-8")
        route_hook(env, RID)

        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )

        assert result.backup_path is not None
        assert result.backup_note == str(result.backup_path)

    def test_deactivate_never_carries_a_backup_path(self, env):
        # D-a: deactivate never restores from a backup, so it never has
        # one to name.
        route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        result = hook_activation.deactivate(env.home, RID, claude_dir=env.claude)

        assert result.backup_path is None


# ------------------------------------------------------------------- N9
# (STOP message not double-prefixed)


class TestStopMessageNotDoublePrefixed:
    def test_hook_activate_stop_message_is_not_double_prefixed(self, env, capsys):
        # Mutation witness: removing the dedicated
        # `except intents.LedgerStoppedError` arm from `_cmd_hook`
        # reddens the `not in err` assertion below (the generic
        # GitOpsError arm doubles the prefix) -- verified, reverted,
        # confirmed GREEN.
        route_hook(env, RID)
        stop = _plant_stop(env.home, _probe_file(env.home))

        rc = cli.main(["hook", "activate", RID, "--no-push"])

        assert rc == 6  # EXIT_GIT_FAILED
        err = capsys.readouterr().err
        assert stop.id in err
        assert "hook activate: self-learn: transaction intent" not in err


# ================================================== fold r2 (2026-09-14)
# Prepare-first activation with independent cleanups and residual
# receipts; deactivate symmetric; matcher conflicts before idempotence;
# quoted absolute override command; replay status in the envelope.


# ---------------------------------------------------------- item A (Opus
# S1-S3, Astra 5/11/12: prepare-first, independent cleanups, residuals)


class TestPrepareFirstIndependentCleanups:
    def test_settings_write_lands_then_raises_undoes_everything(self, env, monkeypatch):
        # Gate round-2 probe PB, remapped (the brief's own instruction:
        # "prune raising is now impossible inside activate -- instead
        # inject a raise from the directory fsync after the replace").
        # Pruning moved entirely out of `activate` (TestBackupPrunedToFive
        # above), so the live equivalent raise site is `fsops.atomic_write`
        # itself failing AFTER its OWN internal `os.replace` has already
        # landed the new bytes. Reproduced by letting the REAL
        # `atomic_write` run first (so the content genuinely lands, same
        # as a directory-fsync failure after a successful rename) and
        # THEN raising, for the settings.json target only. Mutation
        # witness: this test's own existence is the mutation witness for
        # "mark progress BEFORE the call, not after it returns" -- if
        # `activate()` set `settings_written` only AFTER
        # `_write_claude_runtime` returns (the pre-fold-r2 bug,
        # SHOULD-FIX 3), this test goes red (settings NOT restored).
        name, rel = route_hook(env, RID)
        pre_existing = {
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/unrelated.sh"}]}
                ]
            }
        }
        settings = env.claude / "settings.json"
        settings.write_text(json.dumps(pre_existing, indent=2) + "\n", encoding="utf-8")
        original_bytes = settings.read_bytes()

        real_atomic_write = hook_activation.fsops.atomic_write

        def fake_atomic_write(path, data, **kwargs):
            real_atomic_write(path, data, **kwargs)
            if Path(path) == settings:
                raise OSError("simulated directory-fsync failure after the replace landed")

        monkeypatch.setattr(hook_activation.fsops, "atomic_write", fake_atomic_write)

        with pytest.raises(OSError, match="simulated"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        assert settings.read_bytes() == original_bytes  # restored, even though the write LANDED
        assert not link_path(env, name).exists()  # the symlink this call placed is gone
        assert sorted(env.claude.glob("settings.json.self-learn-bak.*")) == []  # the fresh backup is gone

    def test_undo_settings_restore_failure_still_removes_link_and_backup(
        self, env, monkeypatch
    ):
        # Item A: "each cleanup attempted independently in its own try" —
        # a raise from WITHIN the undo's own settings-restore write must
        # not skip the OTHER cleanups, and the ORIGINAL exception (here,
        # the doctor-verdict abort) stays primary — never replaced by the
        # restore's own OSError. Mutation witness: wrapping all three
        # cleanups in ONE shared `try` (instead of three independent
        # ones) reddens the `not link_path` / backup-removed assertions
        # below — verified by hand, reverted.
        name, rel = route_hook(env, RID)
        settings = env.claude / "settings.json"
        unrelated_command = "$HOME/.claude/hooks/self-learn-deadbeef-unrelated.sh"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": unrelated_command}],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before_bytes = settings.read_bytes()

        real_write = hook_activation._write_claude_runtime
        calls = {"settings_writes": 0}

        def spy(**kwargs):
            if kwargs.get("settings_bytes") is not None:
                calls["settings_writes"] += 1
                if calls["settings_writes"] == 2:
                    # The FIRST settings-bytes write is activate()'s own
                    # registration; the SECOND is the undo's own restore
                    # attempt -- fail exactly that one.
                    raise OSError("simulated restore failure")
            return real_write(**kwargs)

        monkeypatch.setattr(hook_activation, "_write_claude_runtime", spy)

        with pytest.raises(
            hook_activation.HookActivationError, match="did not verify as live"
        ) as exc_info:
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        # the ORIGINAL error (the doctor verdict) is what's raised, not
        # the restore's OSError -- with the residual attached as a note.
        notes = list(getattr(exc_info.value, "__notes__", []))
        assert any("settings.json restore failed" in n for n in notes)
        assert settings.read_bytes() != before_bytes  # restore genuinely failed -- not silently OK
        # the OTHER two cleanups still ran despite the restore failing:
        assert not link_path(env, name).exists()
        assert sorted(env.claude.glob("settings.json.self-learn-bak.*")) == []

    def test_os_replace_failure_leaves_no_temp_symlink(self, env, monkeypatch):
        # Opus N10 (ii): if `os.replace(tmp, link)` raises, the temp
        # symlink must not litter `hooks/`. Mutation witness: removing
        # the `except OSError: tmp.unlink(missing_ok=True); raise` wrap
        # around `os.replace` in `_write_claude_runtime` reddens the
        # `leftovers == []` assertion below -- verified by hand, reverted.
        name, rel = route_hook(env, RID)
        real_replace = hook_activation.os.replace
        target = link_path(env, name)

        def fake_replace(src, dst):
            if Path(dst) == target:
                raise OSError("simulated os.replace failure")
            return real_replace(src, dst)

        monkeypatch.setattr(hook_activation.os, "replace", fake_replace)

        with pytest.raises(OSError, match="simulated"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=False)

        leftovers = sorted((env.claude / "hooks").glob(".*"))
        assert leftovers == []


class TestBackupInventoryUnchangedOnAbort:
    def test_doctor_abort_leaves_backup_inventory_unchanged(self, env):
        # Astra 12: a failed activation must not shrink the pre-existing
        # backup set -- the fresh backup THIS call wrote is itself part
        # of what gets undone. Mutation witness: dropping the backup
        # removal from `_undo` (the third independent cleanup) reddens
        # the `after_backups == existing_backups` assertion below --
        # verified by hand, reverted.
        claude = env.claude
        (claude / "settings.json").write_text(json.dumps({"hooks": {}}) + "\n", encoding="utf-8")
        for i in range(1, 4):
            rid = f"lrn-0000fe{i:02d}"
            route_hook(env, rid)
            hook_activation.activate(env.home, rid, claude_dir=claude, register=True)
        existing_backups = sorted(claude.glob("settings.json.self-learn-bak.*"))
        assert len(existing_backups) == 3

        settings = claude / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(
            {
                "matcher": "Bash",
                "hooks": [
                    {"type": "command", "command": "$HOME/.claude/hooks/self-learn-deadbeef-x.sh"}
                ],
            }
        )
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        rid_bad = "lrn-0000fe99"
        route_hook(env, rid_bad)
        with pytest.raises(hook_activation.HookActivationError, match="did not verify as live"):
            hook_activation.activate(env.home, rid_bad, claude_dir=claude, register=True)

        after_backups = sorted(claude.glob("settings.json.self-learn-bak.*"))
        assert after_backups == existing_backups


# ---------------------------------------------------------- item B (the
# runtime-to-ledger handoff is inside the failure model)


class TestRuntimeLedgerHandoffFailureModel:
    def test_record_write_failure_undoes_runtime_no_commit(self, env, monkeypatch):
        # A raise in `Record.write` (between the runtime activation
        # landing and the ledger commit) must undo the runtime change and
        # commit nothing. Mutation witness: removing the `head_after !=
        # head_before` branch's fallthrough to `_undo` in
        # `verbs._hook_commit_or_undo` reddens the `not link_path`
        # assertion below -- verified by hand, reverted.
        name, rel = route_hook(env, RID)
        sha_before = git(env.home, "rev-parse", "HEAD").stdout.strip()

        def fail_write(self, *a, **kw):
            raise OSError("simulated record.write failure")

        monkeypatch.setattr(Record, "write", fail_write)

        with pytest.raises(OSError, match="simulated record.write failure"):
            verbs.hook_activate(env.home, RID, no_push=True)

        assert not link_path(env, name).exists()
        assert not (env.claude / "settings.json").exists()
        sha_after = git(env.home, "rev-parse", "HEAD").stdout.strip()
        assert sha_after == sha_before

    def test_failure_after_commit_landed_keeps_runtime_reports_uncertain(
        self, env, monkeypatch
    ):
        # The commit itself LANDS (HEAD genuinely advances) but something
        # after it raises anyway -- the runtime activation must be KEPT,
        # never undone, and the caller must be told the outcome is
        # uncertain rather than silently either "succeeded" or "failed".
        # Mutation witness: dropping the `head_after != head_before`
        # check entirely (always undoing) reddens the `link.is_symlink()`
        # assertion below -- verified by hand, reverted.
        name, rel = route_hook(env, RID)
        sha_before = git(env.home, "rev-parse", "HEAD").stdout.strip()

        real_commit = verbs._commit_ledger

        def fake_commit(home, touched, message, note=None):
            result = real_commit(home, touched, message, note)
            raise OSError("simulated post-commit bookkeeping failure")

        monkeypatch.setattr(verbs, "_commit_ledger", fake_commit)

        with pytest.raises(verbs.VerbError, match="ledger commit landed"):
            verbs.hook_activate(env.home, RID, no_push=True)

        assert link_path(env, name).is_symlink()
        assert (env.claude / "settings.json").exists()
        sha_after = git(env.home, "rev-parse", "HEAD").stdout.strip()
        assert sha_after != sha_before  # a REAL commit landed
        record = resolved_record(env)
        kinds = [h.get("event") for h in record.history]
        assert "hook-activated" in kinds


# ---------------------------------------------------------- item C
# (deactivate gets the same structure, reversed write order)


class TestDeactivateUndoOnFailure:
    def test_settings_replaced_before_unlink_so_a_crash_leaves_the_safer_half_state(
        self, env, monkeypatch
    ):
        # Item C's reversed order (settings replace THEN unlink) matters
        # precisely when NO undo ever runs at all -- a hard crash between
        # the two writes, not a caught Python exception. Simulated here
        # by making `_undo` itself a no-op (nothing cleans up) and
        # failing exactly the SECOND write: with settings-then-unlink,
        # that second write is the (by-then harmless) unlink, so a crash
        # there leaves the registration GONE and the symlink -- orphaned,
        # unreferenced by anything -- still present; never the reverse
        # (a LIVE registration in settings.json pointing at a symlink
        # that no longer exists, which is what Claude Code would then
        # try, and fail, to invoke). Mutation witness: restoring the OLD
        # unlink-then-settings order reddens the `command not in
        # settings...` assertion below (the registration would still be
        # live while the guard is already gone) -- verified by hand,
        # reverted.
        name, rel = route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        settings = env.claude / "settings.json"
        link = link_path(env, name)
        command = hook_activation._command_for(name, env.claude)

        monkeypatch.setattr(hook_activation, "_undo", lambda progress: [])  # no cleanup ever runs

        real_write = hook_activation._write_claude_runtime

        def spy(**kwargs):
            if kwargs.get("link") is not None and kwargs.get("unlink"):
                raise OSError("simulated crash during unlink")
            return real_write(**kwargs)

        monkeypatch.setattr(hook_activation, "_write_claude_runtime", spy)

        with pytest.raises(OSError, match="simulated crash"):
            hook_activation.deactivate(env.home, RID, claude_dir=env.claude)

        # the settings replace landed FIRST -- the registration really is
        # gone, regardless of whether the unlink after it ever finishes.
        assert command not in settings.read_text(encoding="utf-8")
        # ... and the symlink itself -- now orphaned, referenced by
        # nothing -- is what's left, never a dangling registration.
        assert link.is_symlink()

    def test_settings_write_failure_leaves_link_untouched(self, env, monkeypatch):
        # A settings-write failure (the FIRST write in the new order)
        # happens before the link is ever touched, and -- with the
        # normal undo path enabled this time -- the whole call reverts
        # to exactly its starting state.
        name, rel = route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        settings = env.claude / "settings.json"
        link = link_path(env, name)
        assert link.is_symlink()
        before_bytes = settings.read_bytes()

        real_write = hook_activation._write_claude_runtime

        def spy(**kwargs):
            if kwargs.get("settings_bytes") is not None:
                raise OSError("simulated deactivate settings-write failure")
            return real_write(**kwargs)

        monkeypatch.setattr(hook_activation, "_write_claude_runtime", spy)

        with pytest.raises(OSError, match="simulated deactivate"):
            hook_activation.deactivate(env.home, RID, claude_dir=env.claude)

        assert link.is_symlink()
        assert settings.read_bytes() == before_bytes

    def test_unlink_failure_after_settings_removed_restores_registration(
        self, env, monkeypatch
    ):
        # The LAST write (the symlink removal) fails after the settings
        # replace already landed -- the registration this call removed
        # must be put BACK, so no half-state (settings gone, link gone
        # too but unconfirmed) is ever observable. Mutation witness: the
        # existence of this test IS the witness for D-b's undo extending
        # to deactivate at all (fold r1 shipped `deactivate` with NO undo
        # wrap whatsoever -- gate round-2 SHOULD-FIX 1); removing the
        # `except BaseException` wrap around deactivate's Phase 2 reddens
        # the `settings.read_bytes() == before_bytes` assertion below --
        # verified by hand, reverted.
        name, rel = route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        settings = env.claude / "settings.json"
        link = link_path(env, name)
        before_bytes = settings.read_bytes()
        command = hook_activation._command_for(name, env.claude)
        assert command in before_bytes.decode("utf-8")

        real_write = hook_activation._write_claude_runtime

        def spy(**kwargs):
            if kwargs.get("link") is not None and kwargs.get("unlink"):
                raise OSError("simulated unlink failure")
            return real_write(**kwargs)

        monkeypatch.setattr(hook_activation, "_write_claude_runtime", spy)

        with pytest.raises(OSError, match="simulated unlink"):
            hook_activation.deactivate(env.home, RID, claude_dir=env.claude)

        assert settings.read_bytes() == before_bytes
        assert command in settings.read_text(encoding="utf-8")
        assert link.is_symlink()  # the unlink genuinely never landed

    def test_deactivate_stop_and_undo_via_verb(self, env, monkeypatch):
        # Item C's own "same handoff wrap in the verb" half: a failure
        # AFTER `hook_activation.deactivate` returns (inside the ledger
        # write) must undo the removal via `verbs._hook_commit_or_undo`,
        # same as activate's own item-B test above.
        name, rel = route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        settings = env.claude / "settings.json"
        link = link_path(env, name)
        before_bytes = settings.read_bytes()
        sha_before = git(env.home, "rev-parse", "HEAD").stdout.strip()

        def fail_write(self, *a, **kw):
            raise OSError("simulated record.write failure")

        monkeypatch.setattr(Record, "write", fail_write)

        with pytest.raises(OSError, match="simulated record.write failure"):
            verbs.hook_deactivate(env.home, RID, no_push=True)

        assert link.is_symlink()  # put back
        assert settings.read_bytes() == before_bytes  # registration put back
        sha_after = git(env.home, "rev-parse", "HEAD").stdout.strip()
        assert sha_after == sha_before


# ---------------------------------------------------------- item D
# (matcher conflicts before idempotence; removal-side ownership)


class TestMatcherConflictPrecedence:
    def test_mixed_item_same_command_both_matchers_refuses_regardless_of_order(self, env):
        # Astra 6's first hole: a command registered under BOTH the
        # right matcher and a wrong one must refuse -- never read as
        # "already registered" just because a same-matcher hit also
        # exists. Checked in both array orders. Mutation witness:
        # checking `same_matcher_hit` before `conflict_desc` in
        # `_merge_snippet` (the pre-fold-r2 order) reddens the
        # `pytest.raises` block below for the [Read, Edit|Write] order --
        # verified by hand, reverted.
        name, rel = route_hook(env, RID)
        command = hook_activation._command_for(name, env.claude)
        settings = env.claude / "settings.json"

        for order in (["Read", "Edit|Write"], ["Edit|Write", "Read"]):
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": m,
                                    "hooks": [{"type": "command", "command": command}],
                                }
                                for m in order
                            ]
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with pytest.raises(hook_activation.HookActivationError) as exc_info:
                hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
            assert "'Read'" in str(exc_info.value)
            assert not link_path(env, name).exists()

    def test_missing_matcher_key_is_a_conflict_not_no_conflict(self, env):
        # Astra 6's second hole: a `None` collapse must not equate "found
        # with no matcher" with "not found anywhere". Mutation witness:
        # `other_matcher = item_matcher` (the pre-fold-r2 line, which
        # silently sets the tracking variable back to `None` when
        # `item_matcher` IS `None`) reddens the `pytest.raises` block
        # below -- verified by hand, reverted.
        name, rel = route_hook(env, RID)
        command = hook_activation._command_for(name, env.claude)
        settings = env.claude / "settings.json"
        settings.write_text(
            json.dumps(
                {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]}},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        with pytest.raises(hook_activation.HookActivationError, match="no matcher"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        assert not link_path(env, name).exists()

    def test_null_matcher_value_is_also_a_conflict(self, env):
        name, rel = route_hook(env, RID)
        command = hook_activation._command_for(name, env.claude)
        settings = env.claude / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"matcher": None, "hooks": [{"type": "command", "command": command}]}
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        with pytest.raises(hook_activation.HookActivationError, match="no matcher"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)


class TestRemovalSideOwnership:
    def test_deactivate_never_removes_a_command_under_a_different_matcher(self, env):
        # Reproduces gate round-2's G16 mutation (the gate found NO test
        # protected this) as a real regression test: deactivate must
        # refuse, naming the matcher found, rather than silently
        # reporting "already absent" while the registration (under a
        # DIFFERENT matcher) survives untouched. Mutation witness:
        # `if not isinstance(item, dict):` in place of the matcher
        # condition inside `_remove_command`'s loop (G16's own edit)
        # reddens the `settings.read_bytes() == before` assertion below
        # -- verified by hand (the exact G16 edit), reverted.
        name, rel = route_hook(env, RID)
        command = hook_activation._command_for(name, env.claude)
        settings = env.claude / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"matcher": "Read", "hooks": [{"type": "command", "command": command}]}
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before = settings.read_bytes()

        with pytest.raises(hook_activation.HookActivationError) as exc_info:
            hook_activation.deactivate(env.home, RID, claude_dir=env.claude)

        assert "'Read'" in str(exc_info.value)
        assert "'Edit|Write'" in str(exc_info.value)
        assert settings.read_bytes() == before


# ---------------------------------------------------------- item E
# (command string: quoted absolute override)


class TestOverrideCommandQuoting:
    def test_override_directory_with_a_space_is_one_shell_argument(self, tmp_path):
        override = tmp_path / "Claude Runtime"
        command = command_for("self-learn-x.sh", override)
        assert command == shlex.quote(f"{override}/hooks/self-learn-x.sh")
        assert shlex.split(command) == [f"{override}/hooks/self-learn-x.sh"]

    def test_relative_override_is_resolved_to_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        relative = Path("relative-claude")
        command = command_for("self-learn-x.sh", relative)
        assert command == str(tmp_path / "relative-claude" / "hooks" / "self-learn-x.sh")
        assert Path(command).is_absolute()

    def test_default_command_root_never_quoted(self):
        # $HOME must still expand as a shell variable -- shlex-quoting it
        # would break that expansion outright.
        assert command_for("self-learn-x.sh", None) == "$HOME/.claude/hooks/self-learn-x.sh"

    def test_route_time_snippet_byte_identical_for_default(self, env):
        # D-d's own criterion, re-verified after item E's quoting change.
        seed_hook(env, rid=RID)
        result = verbs.route(env.home, RID)
        assert any('"command": "$HOME/.claude/hooks/' in note for note in result.post_notes)

    def test_activation_with_spaced_override_directory_passes_doctor(self, env, tmp_path):
        # End to end: the doctor's own basename extraction
        # (`selfcheck._registered_hook_commands`, fold r2's shlex fix)
        # must recover the right name from a QUOTED command -- otherwise
        # every activation under a spaced directory would register
        # successfully but then FAIL step 4 regardless of the guard
        # actually being live. Mutation witness: reverting
        # `selfcheck._check_hooks`'s `name = Path(token).name` (shlex-
        # parsed) to the old `name = Path(cmd).name` reddens this whole
        # test (the call raises `HookActivationError` at step 4) --
        # verified by hand, reverted.
        spaced = tmp_path / "Claude Runtime"
        (spaced / "hooks").mkdir(parents=True)
        name, rel = route_hook(env, RID)

        result = hook_activation.activate(env.home, RID, claude_dir=spaced, register=True)

        assert result.hook_registered_entry is not None
        entry = json.loads(result.hook_registered_entry)
        assert entry["hooks"][0]["command"] == shlex.quote(f"{spaced}/hooks/{name}")
        verdict, message = selfcheck._check_hooks(env.home, spaced)
        assert verdict is selfcheck.Verdict.PASS, message


# ---------------------------------------------------------- item F
# (receipt accuracy: the actual registered entry, not the proposed one)


class TestIdempotentReceiptShowsActualEntry:
    def test_idempotent_receipt_shows_grouped_entry_with_timeout_and_sibling(self, env):
        # Astra 9's second half: on an idempotent match, the receipt must
        # show the ACTUAL registered item -- siblings, a hand-added
        # `timeout` key, whatever is really there -- never the freshly
        # rendered snippet this call would have proposed had nothing
        # already existed. Mutation witness: using `entry_json` (the
        # proposed snippet) unconditionally instead of looking up
        # `_registered_item` in the idempotent branch reddens the
        # `entry["timeout"] == 60` assertion below -- verified by hand,
        # reverted.
        name, rel = route_hook(env, RID)
        command = hook_activation._command_for(name, env.claude)
        settings = env.claude / "settings.json"
        grouped_item = {
            "matcher": "Edit|Write",
            "timeout": 60,
            "hooks": [
                {"type": "command", "command": "$HOME/.claude/hooks/sibling.sh"},
                {"type": "command", "command": command},
            ],
        }
        settings.write_text(
            json.dumps({"hooks": {"PreToolUse": [grouped_item]}}, indent=2) + "\n",
            encoding="utf-8",
        )

        result = hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        assert result.hook_registered_entry is not None
        entry = json.loads(result.hook_registered_entry)
        assert entry["timeout"] == 60
        assert entry["hooks"] == grouped_item["hooks"]
        registered_step = next(s for s in result.steps if s.step == "registered")
        assert "timeout" in registered_step.detail
        assert "sibling.sh" in registered_step.detail


# ---------------------------------------------------------- item G
# (replay status in the result and the --json envelope)


class TestReplayStatusEnvelope:
    def test_result_replay_ran_with_examples(self, env):
        route_hook(env, RID)
        result = hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        assert result.replay == "ran"
        assert result.reload_caveat is not None
        assert "FW-154" in result.reload_caveat

    def test_result_replay_skipped_without_examples(self, env):
        route_hook(env, RID)
        path = env.bucket / "resolved" / f"{RID}.md"
        record = Record.from_path(path)
        routing = dict(record.routing)
        hook_meta = dict(routing["hook"])
        del hook_meta["examples"]
        routing["hook"] = hook_meta
        record.set_routing(routing)
        record.write(path)

        result = hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        assert result.replay == "skipped-no-examples"

    def test_delegated_activation_carries_no_replay_status(self, env):
        route_hook(env, RID)
        result = hook_activation.activate(env.home, RID, claude_dir=env.claude, register=False)
        assert result.replay is None
        assert result.reload_caveat is None

    def test_json_envelope_carries_steps_replay_and_caveat_with_examples(self, env, capsys):
        # Mutation witness: dropping the `hook_steps`/`hook_replay`/
        # `hook_reload_caveat` keys from `cli._verb_envelope` reddens the
        # `envelope["hook_replay"]` lookup below with a KeyError --
        # verified by hand, reverted.
        route_hook(env, RID)
        rc = cli.main(["hook", "activate", RID, "--json", "--no-push"])
        assert rc == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["hook_replay"] == "ran"
        assert envelope["hook_reload_caveat"] is not None
        assert any("activation-checked" in s for s in envelope["hook_steps"])
        assert any("replayed clean" in s for s in envelope["hook_steps"])

    def test_json_envelope_carries_skipped_replay_status_without_examples(self, env, capsys):
        route_hook(env, RID)
        path = env.bucket / "resolved" / f"{RID}.md"
        record = Record.from_path(path)
        routing = dict(record.routing)
        hook_meta = dict(routing["hook"])
        del hook_meta["examples"]
        routing["hook"] = hook_meta
        record.set_routing(routing)
        record.write(path)

        rc = cli.main(["hook", "activate", RID, "--json", "--no-push"])
        assert rc == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["hook_replay"] == "skipped-no-examples"
        assert any("doctor-checked" in s for s in envelope["hook_steps"])
        assert not any("activation-checked" in s for s in envelope["hook_steps"])

    def test_never_fails_assertion_uses_the_string_the_code_can_emit(self, env):
        # NIT 7 (round 2, re-flagged as item G's own "fix the assertion
        # that can never fail"): the code's clean branch emits "replayed
        # clean", never "replay clean" -- assert on the string the code
        # can actually produce.
        route_hook(env, RID)
        result = hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)
        checked = next(s for s in result.steps if s.step == "activation-checked")
        assert "replayed clean" in checked.detail


# ---------------------------------------------------------- item H
# (deactivate validates routing.hook.tools like activate)


class TestDeactivateValidatesRoutingComplete:
    def test_deactivate_refuses_when_tools_missing(self, env):
        # Mutation witness: removing the `not tools` half of deactivate's
        # completeness check reddens the `pytest.raises` block below --
        # verified by hand, reverted.
        route_hook(env, RID)
        path = env.bucket / "resolved" / f"{RID}.md"
        record = Record.from_path(path)
        routing = dict(record.routing)
        hook_meta = dict(routing["hook"])
        del hook_meta["tools"]
        routing["hook"] = hook_meta
        record.set_routing(routing)
        record.write(path)

        with pytest.raises(hook_activation.HookActivationError, match="incomplete"):
            hook_activation.deactivate(env.home, RID, claude_dir=env.claude)


# ---------------------------------------------------------- item I (the
# deactivated note names the removed registration + symlink path)


class TestDeactivateNoteNamesRegistrationAndSymlink:
    def test_backup_note_names_matcher_command_and_symlink(self, env):
        name, rel = route_hook(env, RID)
        hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        result = hook_activation.deactivate(env.home, RID, claude_dir=env.claude)

        assert "Edit|Write" in result.backup_note
        command = hook_activation._command_for(name, env.claude)
        assert command in result.backup_note
        assert str(link_path(env, name)) in result.backup_note


# ---------------------------------------------------------- item J (nits)


class TestStep3AbortPinsOrderingAndHistoryViaVerb:
    def test_doctor_abort_via_verb_writes_no_history_and_settings_write_precedes_abort(
        self, env, monkeypatch
    ):
        # NIT 8: drive the abort through the REAL verb (not
        # `hook_activation.activate` directly) so the no-history half is
        # actually exercised, and spy on the settings write to pin that
        # registration genuinely happened BEFORE the doctor's raise --
        # distinguishing "registered, then undone" from "never
        # registered" (the pre-fold-r2 test could not tell these apart:
        # both leave the file byte-identical to before).
        name, rel = route_hook(env, RID)
        settings = env.claude / "settings.json"
        unrelated_command = "$HOME/.claude/hooks/self-learn-deadbeef-unrelated.sh"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": unrelated_command}],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before_bytes = settings.read_bytes()
        sha_before = git(env.home, "rev-parse", "HEAD").stdout.strip()

        seen = {"settings_write_happened": False}
        real_write = hook_activation._write_claude_runtime

        def spy(**kwargs):
            if kwargs.get("settings_bytes") is not None:
                seen["settings_write_happened"] = True
            return real_write(**kwargs)

        monkeypatch.setattr(hook_activation, "_write_claude_runtime", spy)

        with pytest.raises(verbs.VerbError, match="did not verify as live"):
            verbs.hook_activate(env.home, RID, no_push=True)

        assert seen["settings_write_happened"] is True  # it WAS registered, then undone
        assert settings.read_bytes() == before_bytes  # ... and undone back to exactly before
        assert not link_path(env, name).exists()
        sha_after = git(env.home, "rev-parse", "HEAD").stdout.strip()
        assert sha_after == sha_before
        record = resolved_record(env)
        kinds = [h.get("event") for h in record.history]
        assert "hook-activated" not in kinds


class TestDeactivateChecksRoutingHookToolsSameAsActivate:
    def test_nit9_deactivate_empty_tools_no_longer_reads_as_absent(self, env):
        # NIT 9 (Opus): with an EMPTY tools list the old code produced an
        # empty matcher, `_remove_command` matched nothing, and the run
        # took the "already absent (idempotent)" path even though the
        # record's OWN registration (if any) was never found under that
        # empty matcher. Item H's fix refuses outright instead.
        route_hook(env, RID)
        path = env.bucket / "resolved" / f"{RID}.md"
        record = Record.from_path(path)
        routing = dict(record.routing)
        hook_meta = dict(routing["hook"])
        hook_meta["tools"] = []
        routing["hook"] = hook_meta
        record.set_routing(routing)
        record.write(path)

        with pytest.raises(hook_activation.HookActivationError, match="incomplete"):
            hook_activation.deactivate(env.home, RID, claude_dir=env.claude)
