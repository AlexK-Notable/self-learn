"""O-2a — `hook_activation.py`, the human `self-learn hook activate` /
`hook deactivate` verbs, and the `overseer.hook_activation` committed-
config gate reader (`13-hosting-and-separation.md` §7.4; `03-decisions.md`
S-66; `02-schema.md` §2 as amended: `history`'s closed set gains
`hook-activated`/`hook-deactivated`).

**Safety**: every test here resolves the Claude runtime directory through
`SELF_LEARN_CLAUDE_DIR` pointed at a `tmp_path` (the `env` fixture below).
No verb in this module is ever called against the real `~/.claude` — the
module-scoped `_real_claude_dir_never_touched` fixture is a positive
control on that fact, not merely a claim: it compares the real
directory's actual `(mtime, size)` before and after every test in this
file ran.

Plan-overseer §O-2 tests 1-7 and 9 (build-o2a.md's numbering; test 8 is
O-2b's, not built here), plus the brief's two "Plus" extras."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from self_learn import cli, config, hook_activation, verbs
from self_learn.hook_compiler import script_name
from self_learn.records import Record
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


# --------------------------------------------- real ~/.claude positive control

_REAL_CLAUDE_DIR = Path.home() / ".claude"


def _snapshot_real_claude_dir():
    try:
        st = _REAL_CLAUDE_DIR.lstat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


@pytest.fixture(scope="module", autouse=True)
def _real_claude_dir_never_touched():
    """Plus (build-o2a.md): a positive control that this module's tests
    truly never reach the real ``~/.claude`` — not merely that
    ``SELF_LEARN_CLAUDE_DIR`` was set (a bug could still ignore it, or a
    fixture could forget to set it). Compares an actual filesystem fact
    — the real directory node's ``(mtime_ns, size)`` — taken before and
    after every test in this module ran; a change here means some test
    genuinely wrote outside the sandbox."""
    before = _snapshot_real_claude_dir()
    yield
    after = _snapshot_real_claude_dir()
    assert after == before, (
        "the real ~/.claude directory changed while test_hook_activation.py "
        "ran -- every test must resolve SELF_LEARN_CLAUDE_DIR to a tmp_path, "
        "and something here did not"
    )


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
        # step 1 already committed -- only registration refuses
        assert link_path(env, name).is_symlink()


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
        # `route()` sweeps the proposal sibling on every successful route
        # (ledger_ops.remove_proposal_siblings; confirmed by
        # test_route_hook.py's own `test_two_phase_route_lands_a_working_
        # guard`), so this test RE-AUTHORS the sibling after routing —
        # the one legitimate way examples are still present at activation
        # time (see hook_activation._examples_for's docstring).
        name, rel = route_hook(env, RID)
        proposals_dir = env.bucket / "proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        (proposals_dir / f"{RID}.yaml").write_text(
            json.dumps(
                {
                    "examples": {
                        "allow": [
                            # WRONG on purpose: matches the guard's own
                            # deny regex (`\.storage/`)
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
                }
            ),
            encoding="utf-8",
        )
        settings = env.claude / "settings.json"

        with pytest.raises(hook_activation.HookActivationError, match=r"allow\[0\]"):
            hook_activation.activate(env.home, RID, claude_dir=env.claude, register=True)

        # step 1 already committed: symlink placed
        assert link_path(env, name).is_symlink()
        # step 2 never ran: no settings.json write at all
        assert not settings.exists()

    def test_zero_examples_is_honestly_reported_not_clean(self, env):
        # A record routed through the real production path (proposal
        # swept, nothing re-authored) has 0 examples to replay -- the
        # activation-checked receipt must say so explicitly rather than
        # claiming a "clean replay" it never ran (advisor-flagged
        # fail-open: lrn-ea833a5b's class -- a zero-coverage check must
        # never read identically to a real pass).
        route_hook(env, RID)
        result = hook_activation.activate(
            env.home, RID, claude_dir=env.claude, register=True
        )
        checked = next(s for s in result.steps if s.step == "activation-checked")
        assert "0 examples replayed" in checked.detail
        assert "replay clean" not in checked.detail


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
        # survives untouched, proving a real restore, not a rebuild
        assert settings.read_bytes() == original_bytes

        resolved_path = env.bucket / "resolved" / f"{RID}.md"
        record = Record.from_path(resolved_path)
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
        command = f"$HOME/.claude/hooks/{name}"
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
