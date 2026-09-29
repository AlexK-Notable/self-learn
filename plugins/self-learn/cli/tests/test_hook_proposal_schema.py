"""T17 — hook-destination proposal schema (02 §1 hook extension) + the
CLI script stamp (the record_sha precedent applied to executable bytes:
the model emits STRUCTURED input only; the CLI generates the script)."""

from __future__ import annotations

import pytest

from self_learn.hook_compiler import generate_script
from self_learn.ledger_ops import (
    ProposalError,
    read_proposal,
    stamp_proposal,
    validate_proposal,
    write_proposal,
)
from self_learn.records import Record
from support import make_env, proposal_dict


def hook_payload(**overrides) -> dict:
    base = {
        "tools": ["Edit", "Write"],
        "path_regex": r"\.storage/",
        "deny_message": "stop the HA container first — .storage is rewritten on shutdown",
    }
    base.update(overrides)
    return base


def hook_examples(**overrides) -> dict:
    base = {
        "allow": [
            {"tool_name": "Edit", "tool_input": {"file_path": "/x/configuration.yaml"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}},
        ],
        "deny": [
            {"tool_name": "Edit", "tool_input": {"file_path": "/x/.storage/core.config"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/y/.storage/auth"}},
        ],
    }
    base.update(overrides)
    return base


def hook_proposal(**overrides) -> dict:
    data = proposal_dict(
        destination="hook",
        alternates=["skill-md"],
        hook=hook_payload(),
        examples=hook_examples(),
    )
    data.update(overrides)
    return data


class TestValidate:
    def test_valid_hook_proposal_passes(self):
        validate_proposal(hook_proposal())

    def test_hook_destination_requires_hook_block(self):
        # M3-2: the proposal CARRIES the structured compile input — a hook
        # proposal without it has nothing to compile.
        data = hook_proposal()
        del data["hook"]
        with pytest.raises(ProposalError, match="hook"):
            validate_proposal(data)

    def test_hook_destination_requires_examples(self):
        # M3-12: the replay cases ride each proposal.
        data = hook_proposal()
        del data["examples"]
        with pytest.raises(ProposalError, match="examples"):
            validate_proposal(data)

    @pytest.mark.parametrize("n", [1, 4])
    def test_examples_must_be_two_or_three_per_verdict(self, n):
        # Pin: 2–3 allow + 2–3 deny (08 §4 replay row / M3-12).
        ex = {"tool_name": "Edit", "tool_input": {"file_path": "/x"}}
        data = hook_proposal(examples=hook_examples(allow=[dict(ex)] * n))
        with pytest.raises(ProposalError, match="2"):
            validate_proposal(data)

    def test_example_tool_must_be_guarded(self):
        # a Bash example against an Edit/Write guard is vacuous — the guard
        # allows unguarded tools by design, so the example can never assert
        # what its author thinks it does.
        data = hook_proposal(
            examples=hook_examples(
                deny=[
                    {"tool_name": "Bash", "tool_input": {"command": "x"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/.storage/a"}},
                ]
            )
        )
        with pytest.raises(ProposalError, match="tool_name"):
            validate_proposal(data)

    def test_unknown_hook_keys_rejected(self):
        data = hook_proposal(hook=hook_payload(matcher="Edit|Write"))
        with pytest.raises(ProposalError, match="matcher"):
            validate_proposal(data)

    def test_unknown_hook_keys_of_incomparable_types_rejected_not_typeerror(self):
        """FW-63's pre-existing clone: `_validate_hook_extension` sorts
        unknown hook keys the same way `_validate_gates` sorts unknown
        gate keys (`sorted(set(hook) - set(_HOOK_KEYS))`), so it shares
        the same defect — a `hook:` block with 2+ unknown keys of
        mutually incomparable types (an `int` key plus a `str` key) made
        bare `sorted()` raise `TypeError`, escaping every caller's
        `except ProposalError`. Fixing only `_validate_gates` and leaving
        this clone would be fixing the instance, not the class.

        A single unknown key does not discriminate this — `sorted()` on a
        1-element set never compares anything — so this needs two."""
        hook = hook_payload()
        hook[1] = "x"
        hook["matcher"] = "y"
        data = hook_proposal(hook=hook)
        with pytest.raises(ProposalError):
            validate_proposal(data)

    def test_bad_tools_rejected(self):
        data = hook_proposal(hook=hook_payload(tools=["Task"]))
        with pytest.raises(ProposalError, match="tools"):
            validate_proposal(data)

    def test_broken_regex_rejected_by_the_real_engine(self):
        # validated against grep -E — the engine the guard runs — not a
        # Python-re approximation.
        data = hook_proposal(hook=hook_payload(path_regex="(unclosed"))
        with pytest.raises(ProposalError, match="regex"):
            validate_proposal(data)

    def test_multiline_deny_message_rejected(self):
        data = hook_proposal(hook=hook_payload(deny_message="a\nb"))
        with pytest.raises(ProposalError, match="one line"):
            validate_proposal(data)

    def test_non_hook_destination_rejects_hook_payload(self):
        # a hook block on a skill-md proposal is a misfiled compile input.
        data = proposal_dict(destination="skill-md", hook=hook_payload())
        with pytest.raises(ProposalError, match="destination"):
            validate_proposal(data)

    def test_script_optional_but_shape_checked(self):
        validate_proposal(hook_proposal(script=None))
        with pytest.raises(ProposalError, match="script"):
            validate_proposal(hook_proposal(script="echo no shebang"))

    def test_plain_proposals_still_validate(self):
        validate_proposal(proposal_dict())  # the 754-test baseline shape


def warn_payload(**overrides) -> dict:
    base = {
        "mode": "warn",
        "tools": ["Bash"],
        "path_regex": r"p(kill|grep)[[:space:]]+-[a-zA-Z]*f",
        "warn_message": "a -f pattern can match your own shell;\nkill by the PID you captured",
    }
    base.update(overrides)
    return base


def warn_examples(**overrides) -> dict:
    base = {
        "allow": [
            {"tool_name": "Bash", "tool_input": {"command": "pkill -x node"}},
            {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        ],
        "warn": [
            {"tool_name": "Bash", "tool_input": {"command": "pkill -f 'node x'"}},
            {"tool_name": "Bash", "tool_input": {"command": "pgrep -af keys"}},
        ],
    }
    base.update(overrides)
    return base


def warn_proposal(**overrides) -> dict:
    data = hook_proposal(hook=warn_payload(), examples=warn_examples())
    data.update(overrides)
    return data


class TestWarnMode:
    """S-73 (FW-161 items 1 and 2): a hook block gains `mode` and `event`."""

    def test_warn_block_validates_on_both_events(self):
        validate_proposal(warn_proposal())
        validate_proposal(warn_proposal(hook=warn_payload(event="PreToolUse")))
        validate_proposal(warn_proposal(hook=warn_payload(event="PostToolUse")))

    def test_explicit_deny_mode_and_pretooluse_still_validate(self):
        validate_proposal(hook_proposal(hook=hook_payload(mode="deny", event="PreToolUse")))

    def test_posttooluse_deny_refused(self):
        validate_proposal(hook_proposal(hook=hook_payload(event="PreToolUse")))  # control
        with pytest.raises(ProposalError, match="needs mode: warn"):
            validate_proposal(hook_proposal(hook=hook_payload(event="PostToolUse")))

    @pytest.mark.parametrize("field,value", [("mode", "block"), ("mode", None),
                                             ("event", "Stop"), ("event", None)])
    def test_unknown_mode_or_event_refused(self, field, value):
        with pytest.raises(ProposalError, match=f"hook.{field}"):
            validate_proposal(warn_proposal(hook=warn_payload(**{field: value})))

    def test_wrong_mode_keys_refused_by_name(self):
        warn = warn_payload(deny_message="stop")
        with pytest.raises(ProposalError, match="deny_message.*belong to another mode"):
            validate_proposal(warn_proposal(hook=warn))
        deny = hook_payload(warn_message="careful")
        with pytest.raises(ProposalError, match="warn_message.*belong to another mode"):
            validate_proposal(hook_proposal(hook=deny))

    def test_warn_block_needs_its_message(self):
        hook = warn_payload()
        del hook["warn_message"]
        with pytest.raises(ProposalError, match="missing.*warn_message"):
            validate_proposal(warn_proposal(hook=hook))

    def test_warn_message_bounds(self):
        from self_learn.hook_compiler import WARN_MESSAGE_MAX

        validate_proposal(warn_proposal(hook=warn_payload(warn_message="x" * WARN_MESSAGE_MAX)))
        with pytest.raises(ProposalError, match="at most"):
            validate_proposal(
                warn_proposal(hook=warn_payload(warn_message="x" * (WARN_MESSAGE_MAX + 1)))
            )
        with pytest.raises(ProposalError, match="non-empty"):
            validate_proposal(warn_proposal(hook=warn_payload(warn_message="  ")))

    def test_warn_examples_are_allow_and_warn(self):
        with pytest.raises(ProposalError, match="allow.*warn"):
            validate_proposal(warn_proposal(examples=hook_examples()))
        with pytest.raises(ProposalError, match="allow.*deny"):
            validate_proposal(hook_proposal(examples=warn_examples()))

    @pytest.mark.parametrize("n", [1, 4])
    def test_warn_examples_keep_the_two_to_three_bound(self, n):
        ex = {"tool_name": "Bash", "tool_input": {"command": "pkill -f x"}}
        with pytest.raises(ProposalError, match="examples.warn"):
            validate_proposal(warn_proposal(examples=warn_examples(warn=[dict(ex)] * n)))


class TestStamp:
    def seed(self, tmp_path):
        env = make_env(tmp_path)
        record = Record.create(
            type="behavior",
            scope="skill:s",
            source="teach",
            kind="anti-pattern",
            trigger="About to edit `.storage/*.json` while HA is running.",
            instruction="Stop the container first.",
        )
        pending = env.ledger / "skills" / "s" / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        record.write(pending / f"{record.id}.md")
        return env, record

    def test_stamp_generates_script_from_structured_input(self, tmp_path):
        env, record = self.seed(tmp_path)
        write_proposal(env.ledger, record.id, hook_proposal())
        path = stamp_proposal(env.ledger, record.id)
        data = read_proposal(path)
        expected = generate_script(
            record.id,
            "About to edit `.storage/*.json` while HA is running.",
            ["Edit", "Write"],
            r"\.storage/",
            "stop the HA container first — .storage is rewritten on shutdown",
        )
        assert data["script"] == expected
        assert data["record_sha"].startswith("sha256:")

    def test_stamp_overwrites_model_emitted_script(self, tmp_path):
        # executable bytes are never model-trusted (M2-21 precedent).
        env, record = self.seed(tmp_path)
        write_proposal(
            env.ledger,
            record.id,
            hook_proposal(script="#!/bin/sh\nrm -rf / # malicious\n"),
        )
        data = read_proposal(stamp_proposal(env.ledger, record.id))
        assert "malicious" not in data["script"]
        assert data["script"].startswith("#!/usr/bin/env bash\n")

    def test_stamp_refuses_hook_on_knowledge_record(self, tmp_path):
        # slug/trigger come from ## Trigger — a knowledge record has none,
        # and a guard's firing condition IS the trigger (doctrine §6).
        env = make_env(tmp_path)
        record = Record.create(
            type="knowledge", scope="skill:s", source="teach", fact="A fact."
        )
        pending = env.ledger / "skills" / "s" / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        record.write(pending / f"{record.id}.md")
        write_proposal(env.ledger, record.id, hook_proposal())
        with pytest.raises(ProposalError, match="behavior"):
            stamp_proposal(env.ledger, record.id)

    def test_non_hook_stamp_unchanged(self, tmp_path):
        env, record = self.seed(tmp_path)
        write_proposal(env.ledger, record.id, proposal_dict())
        data = read_proposal(stamp_proposal(env.ledger, record.id))
        assert "script" not in data

    def test_episode_brief_excluded_from_generated_hook_script(self, tmp_path):
        """10 §3 U18 (b) / 02 §1: compiler exclusion extends to the hook
        compiler — record_title() (the trigger the script generator
        consumes) walks only the '## Trigger' section, so a record's
        '## Episode brief' text can never reach the generated script bytes."""
        marker = "ZZZ-EPISODE-BRIEF-MUST-NOT-LEAK-INTO-HOOK-ZZZ"
        env = make_env(tmp_path)
        record = Record.create(
            type="behavior",
            scope="skill:s",
            source="session",
            kind="anti-pattern",
            trigger="About to edit `.storage/*.json` while HA is running.",
            instruction="Stop the container first.",
        )
        record.set_body(
            record.body.rstrip("\n") + f"\n\n## Episode brief\n{marker} happened.\n"
        )
        pending = env.ledger / "skills" / "s" / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        record.write(pending / f"{record.id}.md")
        write_proposal(env.ledger, record.id, hook_proposal())
        data = read_proposal(stamp_proposal(env.ledger, record.id))
        assert marker not in data["script"]
        assert "about-to-edit" in data["script"]  # the trigger DID compile (slug)


def test_stamp_generates_the_warn_script_for_a_warn_block(tmp_path):
    """S-73: `proposal validate` stamps the script the block's mode and
    event name; a deny block keeps its guard."""
    from self_learn.hook_compiler import script_for_hook

    env, record = TestStamp().seed(tmp_path)
    hook = warn_payload(event="PostToolUse")
    write_proposal(env.ledger, record.id, warn_proposal(hook=hook))
    script = read_proposal(stamp_proposal(env.ledger, record.id))["script"]
    trigger = "About to edit `.storage/*.json` while HA is running."
    assert script == script_for_hook(record.id, trigger, hook)
    assert "PostToolUse warning hook" in script and "exit 2" not in script
    write_proposal(env.ledger, record.id, hook_proposal())  # control: deny
    deny = read_proposal(stamp_proposal(env.ledger, record.id))["script"]
    assert "exit 2" in deny and "warning hook" not in deny
