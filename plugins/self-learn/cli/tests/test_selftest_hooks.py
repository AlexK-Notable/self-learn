"""T17 — the `--selftest` hooks check (08 §8.1 Hook-selftest pin).

Read-only checks over sandbox ledger/host pairs + a sandbox ~/.claude
(SELF_LEARN_CLAUDE_DIR — conftest redirects it suite-wide so the real
machine state is never read).
"""

from __future__ import annotations

import json

import pytest

from self_learn import cli
from self_learn.hook_compiler import generate_script, script_name
from self_learn.selfcheck import _check_hooks, claude_runtime_dir
from support import make_behavior, make_env

RID = "lrn-0a1b2c3d"
TRIGGER = "About to edit .storage while HA is running."


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(e.ledger))
    claude = tmp_path / "claude-dir"
    (claude / "hooks").mkdir(parents=True)
    monkeypatch.setenv("SELF_LEARN_CLAUDE_DIR", str(claude))
    e.claude = claude
    return e


SCRIPT = generate_script(
    RID, TRIGGER, ["Edit"], r"\.storage/", "stop the container first"
)
NAME = script_name(RID, TRIGGER)


def seed_hook_routed(env, *, status="routed", superseded_by=None, write_script=True):
    """A resolved hook-routed record (routing.hook carries the approved
    bytes) + optionally its host-side script."""
    rel = f"plugins/s-plugin/hooks/{NAME}"
    record = make_behavior(scope="skill:s", record_id=RID, trigger=TRIGGER)
    record.set_routing(
        {
            "routed_at": "2026-07-15T00:00:00Z",
            "destination": "hook",
            "by": "human",
            "hook": {
                "tools": ["Edit"],
                "path_regex": r"\.storage/",
                "deny_message": "stop the container first",
                "script_path": rel,
                "script": SCRIPT,
            },
        }
    )
    record.set_status(status)
    if superseded_by is not None:
        record.set_superseded_by(superseded_by)
    resolved = env.ledger / "skills" / "s" / "resolved"
    resolved.mkdir(parents=True, exist_ok=True)
    record.write(resolved / f"{RID}.md")
    script = env.host / rel
    if write_script:
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(SCRIPT, encoding="utf-8")
        script.chmod(0o755)
    return script


def check(env):
    return _check_hooks(env.ledger, claude_runtime_dir())


class TestLedgerSide:
    def test_intact_script_passes(self, env):
        seed_hook_routed(env)
        ok, reason = check(env)
        assert ok, reason
        assert "1 live hook script(s) intact" in reason

    def test_missing_script_fails_naming_recompile(self, env):
        seed_hook_routed(env, write_script=False)
        ok, reason = check(env)
        assert not ok
        assert "missing" in reason and "recompile" in reason

    def test_non_executable_script_fails(self, env):
        script = seed_hook_routed(env)
        script.chmod(0o644)
        ok, reason = check(env)
        assert not ok
        assert "not executable" in reason

    def test_hand_edited_script_fails_as_drift(self, env):
        script = seed_hook_routed(env)
        script.write_text(SCRIPT + "\n# hand edit\n", encoding="utf-8")
        script.chmod(0o755)
        ok, reason = check(env)
        assert not ok
        assert "drifted" in reason

    def test_superseded_record_with_surviving_script_flagged(self, env):
        # the pin's inverse case: script present for a superseded record
        # = incomplete supersession.
        seed_hook_routed(env, status="superseded", superseded_by="canon")
        ok, reason = check(env)
        assert not ok
        assert "INCOMPLETE SUPERSESSION" in reason

    def test_superseded_record_with_removed_script_clean(self, env):
        seed_hook_routed(
            env, status="superseded", superseded_by="canon", write_script=False
        )
        ok, reason = check(env)
        assert ok, reason

    def test_no_hook_records_is_quietly_green(self, env):
        ok, reason = check(env)
        assert ok
        assert "no hook-routed records" in reason


class TestSettingsSide:
    def write_settings(self, env, command):
        (env.claude / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Edit",
                                "hooks": [{"type": "command", "command": command}],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_registration_with_dangling_symlink_fails(self, env):
        seed_hook_routed(env)
        self.write_settings(env, f"$HOME/.claude/hooks/{NAME}")
        # no symlink in the sandbox claude dir → dangling registration
        ok, reason = check(env)
        assert not ok
        assert "install.sh" in reason

    def test_registration_with_live_symlink_passes(self, env):
        script = seed_hook_routed(env)
        self.write_settings(env, f"$HOME/.claude/hooks/{NAME}")
        (env.claude / "hooks" / NAME).symlink_to(script)
        ok, reason = check(env)
        assert ok, reason
        assert "1 registration(s) resolvable" in reason

    def test_foreign_hook_registrations_ignored(self, env):
        self.write_settings(env, "$HOME/.claude/hooks/organizer-guard.sh")
        ok, reason = check(env)
        assert ok, reason

    def test_unparseable_settings_fails_loud(self, env):
        (env.claude / "settings.json").write_text("{not json", encoding="utf-8")
        ok, reason = check(env)
        assert not ok
        assert "unparseable" in reason


def test_selftest_cli_includes_hooks_line(env, capsys):
    script = seed_hook_routed(env)
    # U-pointer's `surface` row (--selftest) checks record->registration,
    # not merely script-on-disk (§2.4/§5.4 of the reachability spec) --
    # the healthy-install premise this test relies on needs a real
    # settings.json PreToolUse registration plus its live claude_dir/
    # hooks/ symlink, exactly as `TestSettingsSide.
    # test_registration_with_live_symlink_passes` already builds.
    (env.claude / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit",
                            "hooks": [
                                {"type": "command", "command": f"$HOME/.claude/hooks/{NAME}"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (env.claude / "hooks" / NAME).symlink_to(script)
    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out
    assert "PASS hooks" in out
    assert rc == 0


def test_selftest_cli_fails_on_missing_script(env, capsys):
    seed_hook_routed(env, write_script=False)
    rc = cli.main(["--selftest"])
    out = capsys.readouterr().out
    assert "FAIL hooks" in out
    assert rc == 1
