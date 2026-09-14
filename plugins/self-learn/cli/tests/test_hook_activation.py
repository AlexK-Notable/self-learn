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
from pathlib import Path

import pytest

from self_learn import cli, config, hook_activation, intents, verbs
from self_learn.hook_compiler import command_root, script_name, settings_snippet
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
        # Mutation witness (test 5): passing `backup_path=None` instead
        # of the allocated backup path to `_write_claude_runtime` inside
        # `activate()`'s registration branch (simulating "skip backup")
        # reddens the very first iteration's `result.backup_path.is_file()`
        # assertion below — verified, reverted, confirmed GREEN.
        claude = env.claude
        (claude / "settings.json").write_text("{}", encoding="utf-8")
        n_records = hook_activation._BACKUP_KEEP + 2  # forces pruning
        first_backup: Path | None = None
        for i in range(1, n_records + 1):
            rid = f"lrn-0000ee{i:02d}"
            route_hook(env, rid)
            result = hook_activation.activate(
                env.home, rid, claude_dir=claude, register=True
            )
            assert result.backup_path is not None
            assert result.backup_path.is_file()
            if i == 1:
                first_backup = result.backup_path

        backups = sorted(claude.glob("settings.json.self-learn-bak.*"))
        assert len(backups) == hook_activation._BACKUP_KEEP
        assert first_backup is not None and not first_backup.exists()  # pruned, oldest first


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

        checked = next(s for s in result.steps if s.step == "activation-checked")
        assert "no examples recorded on this record" in checked.detail
        assert "replay clean" not in checked.detail

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
