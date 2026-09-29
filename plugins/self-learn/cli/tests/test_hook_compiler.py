"""T17 — hook compiler unit layer (08 §8.1 pins M3-1/M3-6/M3-8/M3-12/M3-14).

Generated-script behavior is tested by EXECUTING the generated bash against
stdin fixtures (the suite's mock-free convention): denied calls exit 2 with
the pinned message shape, allowed calls exit 0, malformed stdin fails
closed. These stdin-piped fixtures are the unit layer only — 08 §2 pins
that acceptance evidence is a live session trial (T20, protocol).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from self_learn.hook_compiler import (
    GUARDABLE_TOOLS,
    HookCompileError,
    generate_script,
    replay_examples,
    script_name,
    settings_snippet,
    trigger_slug,
)

RID = "lrn-4c1e9a2f"


def run_guard(script: Path, payload) -> subprocess.CompletedProcess:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [str(script)], input=text, capture_output=True, text=True
    )


def write_guard(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "guard.sh"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


# ------------------------------------------------------------------ slug


class TestSlug:
    def test_first_four_words_kebab(self):
        assert (
            trigger_slug("About to edit a `.storage/*.json` while HA runs")
            == "about-to-edit-a"
        )

    def test_punctuation_stripped_and_lowercased(self):
        assert (
            trigger_slug("About to run `chezmoi cd` in a shell")
            == "about-to-run-chezmoi"
        )

    def test_cap_32_chars(self):
        slug = trigger_slug(
            "Extraordinarily long first-word trigger sentence beyond caps"
        )
        assert len(slug) <= 32
        assert slug == slug.strip("-")

    def test_charset(self):
        slug = trigger_slug("safe-update/paru/pacman -Syu fails with 'error:'")
        assert all(c.isascii() and (c.isalnum() or c == "-") for c in slug)
        assert slug  # non-empty

    def test_unsluggable_trigger_refused(self):
        with pytest.raises(HookCompileError, match="slug"):
            trigger_slug("¡™£¢∞§¶")

    def test_script_name_drops_lrn_prefix(self):
        # M3-6: id WITHOUT the lrn- prefix.
        name = script_name(RID, "About to edit .storage files")
        assert name == "self-learn-4c1e9a2f-about-to-edit-storage.sh"
        assert "lrn-" not in name


# ------------------------------------------------------------ generation


class TestGenerate:
    def test_deterministic_and_shebanged(self):
        a = generate_script(RID, "About to edit x", ["Edit", "Write"], r"\.storage/", "stop first")
        b = generate_script(RID, "About to edit x", ["Edit", "Write"], r"\.storage/", "stop first")
        assert a == b  # byte-identical: no timestamps, no environment
        assert a.startswith("#!/usr/bin/env bash\n")
        assert RID in a

    def test_unknown_tool_refused(self):
        with pytest.raises(HookCompileError, match="tools"):
            generate_script(RID, "t", ["Task"], "x", "m")

    def test_multiline_deny_message_refused(self):
        # deny = ONE-line stderr message (08 §8.1 Generated-guard-shape pin).
        with pytest.raises(HookCompileError, match="one line"):
            generate_script(RID, "t", ["Edit"], "x", "line\nline2")

    def test_snippet_is_the_pinned_template(self):
        # M3-1 literal template; M3-14: matcher = tool-name set joined by |,
        # path regex NEVER in the matcher.
        name = script_name(RID, "About to edit .storage")
        snippet = settings_snippet(["Edit", "Write"], name)
        parsed = json.loads("{" + snippet + "}")
        entry = parsed["PreToolUse"][0]
        assert entry["matcher"] == "Edit|Write"
        assert entry["hooks"] == [
            {"type": "command", "command": f"$HOME/.claude/hooks/{name}"}
        ]

    def test_guardable_tools_are_the_field_mapped_set(self):
        assert set(GUARDABLE_TOOLS) == {"Edit", "Write", "Bash"}


# ----------------------------------------------------- generated behavior


class TestGuardBehavior:
    @pytest.fixture()
    def storage_guard(self, tmp_path: Path) -> Path:
        return write_guard(
            tmp_path,
            generate_script(
                RID,
                "About to edit .storage while HA runs",
                ["Edit", "Write"],
                r"\.storage/",
                "stop the HA container first — .storage is rewritten on shutdown",
            ),
        )

    def test_deny_exits_2_with_pinned_message(self, storage_guard):
        proc = run_guard(
            storage_guard,
            {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/core.config"}},
        )
        assert proc.returncode == 2
        # pinned shape: `self-learn lrn-…: <message>` (one line, cites record)
        assert proc.stderr.strip() == (
            f"self-learn {RID}: stop the HA container first — .storage is "
            "rewritten on shutdown"
        )

    def test_sibling_file_allowed(self, storage_guard):
        proc = run_guard(
            storage_guard,
            {"tool_name": "Edit", "tool_input": {"file_path": "/x/configuration.yaml"}},
        )
        assert proc.returncode == 0

    def test_write_tool_also_guarded(self, storage_guard):
        proc = run_guard(
            storage_guard,
            {"tool_name": "Write", "tool_input": {"file_path": "/x/.storage/a"}},
        )
        assert proc.returncode == 2

    def test_unguarded_tool_allowed(self, storage_guard):
        # M3-8: decide on tool_name ∈ the pinned set; a Bash call reaching
        # an Edit/Write guard (bad registration) is allowed, never regexed.
        proc = run_guard(
            storage_guard,
            {"tool_name": "Bash", "tool_input": {"command": "cat /x/.storage/a"}},
        )
        assert proc.returncode == 0

    def test_missing_field_allowed(self, storage_guard):
        proc = run_guard(storage_guard, {"tool_name": "Edit", "tool_input": {}})
        assert proc.returncode == 0

    def test_malformed_stdin_fails_closed(self, storage_guard):
        proc = run_guard(storage_guard, "this is not json {")
        assert proc.returncode == 2

    def test_empty_stdin_fails_closed(self, storage_guard):
        proc = run_guard(storage_guard, "")
        assert proc.returncode == 2

    def test_bash_guard_matches_command_field(self, tmp_path):
        # M3-8: Bash → .tool_input.command — never the raw JSON blob.
        guard = write_guard(
            tmp_path,
            generate_script(
                "lrn-6883f824",
                "About to sudo npm install -g",
                ["Bash"],
                r"sudo\s+npm\s+install\s+-g",
                "never sudo npm install -g on this machine (pacman split-brain)",
            ),
        )
        deny = run_guard(
            guard,
            {"tool_name": "Bash", "tool_input": {"command": "sudo npm install -g yarn"}},
        )
        assert deny.returncode == 2
        assert "lrn-6883f824" in deny.stderr
        allow = run_guard(
            guard,
            {"tool_name": "Bash", "tool_input": {"command": "npm install yarn"}},
        )
        assert allow.returncode == 0
        # an Edit call must not be matched by a Bash-only guard
        edit = run_guard(
            guard,
            {"tool_name": "Edit", "tool_input": {"file_path": "sudo npm install -g"}},
        )
        assert edit.returncode == 0

    def test_single_quotes_in_regex_and_message_survive(self, tmp_path):
        guard = write_guard(
            tmp_path,
            generate_script(
                RID, "t", ["Bash"], r"echo 'hi'", "don't do that — it's bad"
            ),
        )
        deny = run_guard(
            guard, {"tool_name": "Bash", "tool_input": {"command": "echo 'hi' there"}}
        )
        assert deny.returncode == 2
        assert "don't do that — it's bad" in deny.stderr

    def test_invalid_regex_fails_closed(self, tmp_path):
        # grep -E error (rc ≥ 2) must never fall through to allow.
        text = generate_script(RID, "t", ["Bash"], r"placeholder", "m")
        broken = text.replace("placeholder", "(unclosed")
        guard = write_guard(tmp_path, broken)
        proc = run_guard(
            guard, {"tool_name": "Bash", "tool_input": {"command": "anything"}}
        )
        assert proc.returncode == 2


# ---------------------------------------------------------------- replay


class TestReplay:
    def test_clean_replay_returns_no_mismatches(self, tmp_path):
        guard = write_guard(
            tmp_path,
            generate_script(RID, "t", ["Edit"], r"\.storage/", "stop first"),
        )
        mismatches = replay_examples(
            guard,
            {
                "allow": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/ok.yaml"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/y/fine.md"}},
                ],
                "deny": [
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/.storage/b"}},
                ],
            },
        )
        assert mismatches == []

    def test_mismatch_named_per_example(self, tmp_path):
        guard = write_guard(
            tmp_path,
            generate_script(RID, "t", ["Edit"], r"\.storage/", "stop first"),
        )
        mismatches = replay_examples(
            guard,
            {
                "allow": [
                    # WRONG: this one is denied by the guard
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/a"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/ok"}},
                ],
                "deny": [
                    # WRONG: this one is allowed by the guard
                    {"tool_name": "Edit", "tool_input": {"file_path": "/free.txt"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/b"}},
                ],
            },
        )
        assert len(mismatches) == 2
        assert any("allow[0]" in m for m in mismatches)
        assert any("deny[0]" in m for m in mismatches)


# ------------------------------------------- S-73: the warn script (item 2)

#: The deny oracle, generated on master a0fb55f by the orchestrator (the
#: advisory-hooks spec): a deny block with no `mode` must keep producing
#: exactly these bytes, since placed guards are re-derived and
#: byte-compared (verbs m-5).
DENY_ORACLE_SHA256 = "c681a150581d1ab9caa2ccb030649b4402f542b9c29b3b1370cbb182799b8921"
DENY_ORACLE_ARGS = (
    "lrn-0a1b2c3d",
    "About to run pkill -f with a pattern",
    ["Bash"],
    r"(^|[;&|[:space:]])p(kill|grep)[[:space:]]+-[a-zA-Z]*f",
    "self-learn lrn-0a1b2c3d: don't use pkill -f; it's got 'quotes'",
)
WARN_REGEX = r"(^|[;&|[:space:]])p(kill|grep)[[:space:]]+-[a-zA-Z]*f"
WARN_MESSAGE = "don't use pkill -f; it's got 'quotes' and \"doubles\"\nkill by the PID you captured"


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestDenyBytesUnchanged:
    def test_the_deny_oracle_hash_is_unchanged(self):
        assert _sha256(generate_script(*DENY_ORACLE_ARGS)) == DENY_ORACLE_SHA256

    def test_explicit_deny_and_pretooluse_give_the_same_bytes(self):
        from self_learn.hook_compiler import script_for_hook

        tools = DENY_ORACLE_ARGS[2]
        block = {"tools": tools, "path_regex": DENY_ORACLE_ARGS[3],
                 "deny_message": DENY_ORACLE_ARGS[4]}
        rid, trigger = DENY_ORACLE_ARGS[0], DENY_ORACLE_ARGS[1]
        assert _sha256(script_for_hook(rid, trigger, block)) == DENY_ORACLE_SHA256
        explicit = {**block, "mode": "deny", "event": "PreToolUse"}
        assert _sha256(script_for_hook(rid, trigger, explicit)) == DENY_ORACLE_SHA256
        assert _sha256(generate_script(*DENY_ORACLE_ARGS, mode="deny",
                                       event="PreToolUse")) == DENY_ORACLE_SHA256


def _warn(tmp_path: Path, event: str = "PreToolUse", message: str = WARN_MESSAGE,
          regex: str = WARN_REGEX) -> Path:
    return write_guard(tmp_path, generate_script(
        RID, "About to run pkill -f", ["Bash", "Edit"], regex, message,
        mode="warn", event=event,
    ))


def _deny_twin(tmp_path: Path, regex: str = WARN_REGEX) -> Path:
    twin = tmp_path / "deny"
    twin.mkdir(exist_ok=True)
    return write_guard(twin, generate_script(
        RID, "About to run pkill -f", ["Bash", "Edit"], regex, "stop",
    ))


PKILL = {"tool_name": "Bash", "tool_input": {"command": "pkill -f 'node x'"}}
LS = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}


class TestWarnScript:
    @pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse"])
    def test_match_prints_the_exact_json_and_exits_0(self, tmp_path, event):
        proc = run_guard(_warn(tmp_path, event), PKILL)
        assert proc.returncode == 0
        assert proc.stdout.endswith("\n") and proc.stdout.count("\n") == 1
        assert json.loads(proc.stdout) == {
            "hookSpecificOutput": {"hookEventName": event, "additionalContext": WARN_MESSAGE}
        }
        assert proc.stderr == ""

    def test_no_match_prints_nothing_and_exits_0(self, tmp_path):
        guard = _warn(tmp_path)
        assert run_guard(guard, PKILL).stdout != ""  # positive control
        proc = run_guard(guard, LS)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")

    def test_the_named_field_is_the_one_matched(self, tmp_path):
        guard = _warn(tmp_path)
        edit = {"tool_name": "Edit", "tool_input": {"file_path": "x pkill -f y"}}
        assert run_guard(guard, edit).stdout != ""  # Edit -> file_path
        blob = {"tool_name": "Bash", "tool_input": {"description": "run pkill -f x",
                                                    "command": "ls"}}
        assert run_guard(guard, blob).stdout == ""  # never the raw blob
        other = {"tool_name": "Write", "tool_input": {"file_path": "x pkill -f y"}}
        assert run_guard(guard, other).stdout == ""  # an unlisted tool

    def test_posttooluse_input_with_a_tool_response_still_matches(self, tmp_path):
        guard = _warn(tmp_path, "PostToolUse")
        payload = {**PKILL, "hook_event_name": "PostToolUse",
                   "tool_response": {"stdout": "", "stderr": "", "interrupted": False}}
        assert json.loads(run_guard(guard, payload).stdout)["hookSpecificOutput"][
            "hookEventName"] == "PostToolUse"

    @pytest.mark.parametrize("payload", ["this is not json {", "", "   \n",
                                         {"tool_name": "Bash", "tool_input": {}},
                                         {"tool_name": "Bash"}])
    def test_bad_input_fails_open_where_the_deny_guard_fails_closed(self, tmp_path, payload):
        warn = run_guard(_warn(tmp_path), payload)
        assert (warn.returncode, warn.stdout) == (0, "")
        deny = run_guard(_deny_twin(tmp_path), payload)
        if payload in ("this is not json {", "", "   \n"):
            assert deny.returncode == 2  # the same input fails CLOSED there
        else:
            assert deny.returncode == 0  # a missing field allows in both

    def test_a_broken_regex_fails_open_where_the_deny_guard_fails_closed(self, tmp_path):
        warn_text = generate_script(RID, "t", ["Bash"], r"placeholder", "careful",
                                    mode="warn")
        deny_text = generate_script(RID, "t", ["Bash"], r"placeholder", "stop")
        assert warn_text.count("'placeholder'") == 1 and deny_text.count("'placeholder'") == 2
        warn = write_guard(tmp_path, warn_text.replace("'placeholder'", "'(unclosed'"))
        (tmp_path / "d").mkdir()
        deny = write_guard(tmp_path / "d", deny_text.replace("'placeholder'", "'(unclosed'"))
        payload = {"tool_name": "Bash", "tool_input": {"command": "(unclosed"}}
        assert run_guard(deny, payload).returncode == 2
        proc = run_guard(warn, payload)
        assert (proc.returncode, proc.stdout) == (0, "")

    def test_a_missing_jq_fails_open_where_the_deny_guard_fails_closed(self, tmp_path):
        import os
        import shutil

        bin_dir = tmp_path / "bin-without-jq"
        bin_dir.mkdir()
        for tool in ("bash", "cat", "grep", "printf"):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)
        env = {**os.environ, "PATH": str(bin_dir)}

        def run(script):
            return subprocess.run([str(script)], input=json.dumps(PKILL),
                                  capture_output=True, text=True, env=env)

        assert run(_deny_twin(tmp_path)).returncode == 2  # control: jq really is absent
        proc = run(_warn(tmp_path))
        assert (proc.returncode, proc.stdout) == (0, "")

    def test_quotes_newlines_and_multibyte_round_trip(self, tmp_path):
        message = "naïve — «don't» \"x\" $HOME `id` \\n\n\tsecond line ✓"
        proc = run_guard(_warn(tmp_path, message=message), PKILL)
        assert json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"] == message

    def test_the_output_is_bounded_under_the_cap(self, tmp_path):
        from self_learn.hook_compiler import WARN_MESSAGE_MAX, WARN_OUTPUT_CAP

        # the worst case the schema admits: 2,000 characters that each need
        # JSON escaping stays under the cap
        worst = '"' * WARN_MESSAGE_MAX
        proc = run_guard(_warn(tmp_path, message=worst), PKILL)
        assert len(proc.stdout.encode("utf-8")) <= WARN_OUTPUT_CAP
        assert json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"] == worst
        # a multibyte message at the limit stays near its own size
        wide = "é✓" * (WARN_MESSAGE_MAX // 2)
        proc = run_guard(_warn(tmp_path, message=wide), PKILL)
        assert json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"] == wide
        with pytest.raises(HookCompileError, match="at most"):
            generate_script(RID, "t", ["Bash"], "x", "y" * (WARN_MESSAGE_MAX + 1), mode="warn")

    def test_the_output_cap_is_enforced_at_generation(self, monkeypatch):
        from self_learn import hook_compiler

        generate_script(RID, "t", ["Bash"], "x", "y" * 200, mode="warn")  # control
        monkeypatch.setattr(hook_compiler, "WARN_OUTPUT_CAP", 150)
        with pytest.raises(HookCompileError, match="output cap"):
            generate_script(RID, "t", ["Bash"], "x", "y" * 200, mode="warn")

    def test_posttooluse_deny_and_unknown_modes_are_refused(self):
        with pytest.raises(HookCompileError, match="PreToolUse only"):
            generate_script(RID, "t", ["Bash"], "x", "m", event="PostToolUse")
        with pytest.raises(HookCompileError, match="mode"):
            generate_script(RID, "t", ["Bash"], "x", "m", mode="block")

    def test_warn_script_is_deterministic(self):
        a = generate_script(RID, "t", ["Bash"], "x", WARN_MESSAGE, mode="warn")
        assert a == generate_script(RID, "t", ["Bash"], "x", WARN_MESSAGE, mode="warn")
        assert a.startswith("#!/usr/bin/env bash\n") and RID in a


# ----------------------------------------------- S-73: warn replay (item 3)

WARN_BLOCK = {"mode": "warn", "event": "PostToolUse", "tools": ["Bash"],
              "path_regex": WARN_REGEX, "warn_message": WARN_MESSAGE}
WARN_EXAMPLES = {"allow": [LS, {"tool_name": "Bash", "tool_input": {"command": "pkill -x node"}}],
                 "warn": [PKILL, {"tool_name": "Bash", "tool_input": {"command": "pgrep -af keys"}}]}


def _warn_block_guard(tmp_path: Path, block: dict = WARN_BLOCK) -> Path:
    from self_learn.hook_compiler import script_for_hook

    return write_guard(tmp_path, script_for_hook(RID, "About to run pkill -f", block))


class TestWarnReplay:
    def test_clean_warn_replay(self, tmp_path):
        assert replay_examples(_warn_block_guard(tmp_path), WARN_EXAMPLES, WARN_BLOCK) == []

    def test_an_allow_example_that_warns_is_named(self, tmp_path):
        examples = {**WARN_EXAMPLES, "allow": [PKILL, LS]}
        mismatches = replay_examples(_warn_block_guard(tmp_path), examples, WARN_BLOCK)
        assert len(mismatches) == 1 and mismatches[0].startswith("allow[0] expected no warning")

    def test_a_warn_example_that_stays_silent_is_named(self, tmp_path):
        examples = {**WARN_EXAMPLES, "warn": [PKILL, LS]}
        mismatches = replay_examples(_warn_block_guard(tmp_path), examples, WARN_BLOCK)
        assert len(mismatches) == 1 and mismatches[0].startswith("warn[1] expected a warning")

    def test_the_event_and_the_message_must_both_match(self, tmp_path):
        guard = _warn_block_guard(tmp_path)
        assert replay_examples(guard, WARN_EXAMPLES, WARN_BLOCK) == []  # control
        pre = {**WARN_BLOCK, "event": "PreToolUse"}
        assert len(replay_examples(guard, WARN_EXAMPLES, pre)) == 2
        other = {**WARN_BLOCK, "warn_message": "something else"}
        assert len(replay_examples(guard, WARN_EXAMPLES, other)) == 2

    def test_a_non_zero_exit_is_a_mismatch(self, tmp_path):
        guard = write_guard(tmp_path, "#!/usr/bin/env bash\ncat >/dev/null\nexit 2\n")
        mismatches = replay_examples(guard, WARN_EXAMPLES, WARN_BLOCK)
        assert len(mismatches) == 4 and all("exited 2" in m for m in mismatches)

    def test_a_deny_guard_replays_as_before_with_or_without_its_block(self, tmp_path):
        guard = write_guard(tmp_path, generate_script(RID, "t", ["Edit"], r"\.storage/", "stop"))
        examples = {"allow": [{"tool_name": "Edit", "tool_input": {"file_path": "/ok"}}],
                    "deny": [{"tool_name": "Edit", "tool_input": {"file_path": "/.storage/a"}}]}
        block = {"tools": ["Edit"], "path_regex": r"\.storage/", "deny_message": "stop"}
        assert replay_examples(guard, examples) == []
        assert replay_examples(guard, examples, block) == []
        # the deny guard read as a warn block mismatches: the verdicts differ
        as_warn = {"allow": examples["allow"], "warn": examples["deny"]}
        assert replay_examples(guard, as_warn, {**block, "mode": "warn"}) != []
