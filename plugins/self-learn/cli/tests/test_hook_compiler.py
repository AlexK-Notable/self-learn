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
