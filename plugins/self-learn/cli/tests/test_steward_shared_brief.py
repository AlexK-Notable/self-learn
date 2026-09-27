"""2026-09-26 -- the steward's brief in two parts, so a run's later calls
read the shared part from Claude Code's prompt cache.

The user, 2026-09-26 17:46 PDT: "you know what to do with caching." The
layout is the one measured on 2026-09-20 (cross-call caching report, 15 real
calls): the text shared by every call of a run goes in the APPENDED system
prompt, through a file (`--append-system-prompt-file`; a command-line
argument fails at 131,072 bytes), with `exclude_dynamic_sections` on; the
text that differs per call is the user message. The split and the fields
below are the orchestrator's choices (build spec, Part B).

No test here crosses the real SDK boundary (`conftest.py` forbids it): the
steward runs against a fake `write_session`, and the backend drives a
`FakeSdkClient`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from self_learn import conditions, invocation, steward, steward_prompt
from self_learn.invocation_sdk import backend
from self_learn.sdksession.fake import FakeSdkClient
from support import make_home
from test_steward import (
    _configure_steward,
    _enable_steward,
    _seed_fresh_proposals,
    _write_decision_stage,
)

_SHARED_BLOCKS = ("method", "conditions", "output_contract")
_PACKET_BLOCKS = ("containment", "user_model", "open_cases", "briefs")


def _run(tmp_path: Path, index: int, *, last_run_at=None) -> steward_prompt.RunContext:
    return steward_prompt.RunContext(
        run_id="run-shared01", stage_dir=tmp_path / "stage" / f"packet-{index:04d}",
        packet_index=index, packet_count=2, last_run_at=last_run_at,
        verbs_the_runner_executes=("case record", "batch"),
    )


def _proposal(record_id: str) -> dict:
    return {"id": record_id, "recommendation": "route",
            "card": {"headline": f"about {record_id}", "evidence": "a quote", "advice": "route it"}}


# ------------------------------------------------------------ B1: the split


def test_the_shared_part_is_byte_identical_across_a_runs_packets(tmp_path):
    home = make_home(tmp_path)
    items = conditions.steward_feed(home, [("lrn-aa00beef", {}), ("lrn-bb00beef", {})])
    one = steward_prompt.assemble(
        home, tmp_path / "cache", _run(tmp_path, 1), [_proposal("lrn-aa00beef")],
        conditions_items=items,
    )
    two = steward_prompt.assemble(
        home, tmp_path / "cache", _run(tmp_path, 2, last_run_at="2026-09-25T15:06:09Z"),
        [_proposal("lrn-bb00beef")], conditions_items=items,
    )

    # Positive control: what varies per packet IS in the per-packet part.
    for packet, index in ((one, 1), (two, 2)):
        assert f"packet {index} of 2" in packet.per_packet
        assert str(tmp_path / "stage" / f"packet-{index:04d}") in packet.per_packet
        assert "last steward run:" in packet.per_packet
    assert one.per_packet != two.per_packet
    # ... and none of it is in the shared part, which is the same bytes.
    for packet in (one, two):
        assert "packet 1 of 2" not in packet.shared and "packet 2 of 2" not in packet.shared
        assert str(tmp_path / "stage") not in packet.shared
        assert "last steward run:" not in packet.shared
        assert "run-shared01" not in packet.shared
        assert "lrn-aa00beef" not in packet.shared and "lrn-bb00beef" not in packet.shared
    assert one.shared.encode("utf-8") == two.shared.encode("utf-8")


def test_each_part_holds_its_blocks_in_reading_order(tmp_path):
    home = make_home(tmp_path)
    packet = steward_prompt.assemble(home, tmp_path / "cache", _run(tmp_path, 1), [_proposal("lrn-aa00beef")])

    def order(text: str) -> list[str]:
        return re.findall(r"^=== ([a-z_]+) ===$", text, re.M)

    assert order(packet.shared) == list(_SHARED_BLOCKS)
    assert order(packet.per_packet) == list(_PACKET_BLOCKS)
    assert packet.text == packet.shared + "\n\n" + packet.per_packet
    assert steward_prompt._BLOCK_ORDER == _SHARED_BLOCKS + _PACKET_BLOCKS


def test_a_sent_back_block_stays_in_the_per_packet_part(tmp_path):
    home = make_home(tmp_path)
    packet = steward_prompt.assemble(
        home, tmp_path / "cache", _run(tmp_path, 1), [_proposal("lrn-aa00beef")],
        returned={"lrn-aa00beef": {"case": "case-0a1b2c3d", "lines": ["refused"]}},
    )
    assert "=== sent_back ===" in packet.per_packet
    assert "=== sent_back ===" not in packet.shared
    assert packet.per_packet.index("=== sent_back ===") < packet.per_packet.index("=== open_cases ===")


# ----------------------------------------------- B2: the session's options


def _steward_spec(home: Path, tmp_path: Path, **kw) -> invocation.SessionSpec:
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    return steward._session_spec(home, run_dir, "per-packet text", label="steward-t", **kw)


def test_a_steward_session_carries_the_shared_file_and_the_static_prompt_flag(tmp_path):
    home = make_home(tmp_path)
    shared = tmp_path / "run" / "brief-shared.md"
    spec = _steward_spec(home, tmp_path, shared_brief=shared)
    assert spec.append_system_prompt_file == shared
    assert spec.exclude_dynamic_sections is True

    options = backend.options_kwargs(spec)

    assert options["system_prompt"] == {
        "type": "preset", "preset": "claude_code", "exclude_dynamic_sections": True,
    }
    assert options["extra_args"] == {"append-system-prompt-file": str(shared)}


def test_other_sessions_options_are_unchanged(tmp_path):
    home = make_home(tmp_path)
    for spec in (
        _steward_spec(home, tmp_path),  # the doctor's probe: no shared file
        invocation.SessionSpec(
            surface="worker", prompt="p", cwd=home, timeout=10.0,
            containment=invocation.containment_for("worker", allowed_tools="Read",
                                                   disallowed_tools="Bash", home=home),
            log=lambda _m: None,
        ),
    ):
        assert spec.append_system_prompt_file is None and spec.exclude_dynamic_sections is False
        options = backend.options_kwargs(spec)
        assert options["system_prompt"] == {"type": "preset", "preset": "claude_code"}
        assert "extra_args" not in options


def test_an_appended_file_and_appended_doctrine_are_refused_together(tmp_path):
    home = make_home(tmp_path)
    spec = _steward_spec(home, tmp_path, shared_brief=tmp_path / "run" / "brief-shared.md")
    from dataclasses import replace

    with pytest.raises(ValueError, match="doctrine"):
        backend.options_kwargs(replace(spec, doctrine="also appended"))


def test_a_shared_file_the_sdk_cannot_pass_refuses_the_session(tmp_path, monkeypatch):
    """Dropped silently, the file would leave the steward deciding with no
    method, no contract and no conditions."""
    home = make_home(tmp_path)
    spec = _steward_spec(home, tmp_path, shared_brief=tmp_path / "run" / "brief-shared.md")
    real = backend._supported_option_fields
    monkeypatch.setattr(backend, "_supported_option_fields", lambda: real() - {"extra_args"})
    with pytest.raises(ValueError, match="append-system-prompt-file"):
        backend.options_kwargs(spec)


# --------------------------------------------- B3: the repair round

def test_the_repair_round_carries_the_shared_file_and_the_flag(tmp_path):
    home = make_home(tmp_path)
    shared = tmp_path / "run" / "brief-shared.md"
    repair = steward._repair_spec(_steward_spec(home, tmp_path, shared_brief=shared), "bad file")
    assert repair.append_system_prompt_file == shared
    assert repair.exclude_dynamic_sections is True
    assert repair.prompt.startswith("per-packet text") and "=== repair ===" in repair.prompt


# ------------------------------------------------ the run, end to end


def test_a_run_sends_the_shared_part_as_a_file_and_the_packet_as_the_prompt(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    ids = _seed_fresh_proposals(home, 2)
    _configure_steward(home, packet_size=1)  # two packets, two calls
    seen: list[tuple[Path, bytes, str]] = []

    def capture(spec):
        path = spec.append_system_prompt_file
        seen.append((path, Path(path).read_bytes(), spec.prompt))
        return _write_decision_stage(spec)

    monkeypatch.setattr(steward.invocation, "write_session", capture)

    result = steward.run(home)

    assert result.status == "applied" and result.decided == ids and result.calls == 2
    (path_1, shared_1, prompt_1), (path_2, shared_2, prompt_2) = seen
    assert path_1 == path_2 and shared_1 == shared_2
    shared_text = shared_1.decode("utf-8")
    for name in _SHARED_BLOCKS:
        assert f"=== {name} ===" in shared_text
        assert f"=== {name} ===" not in prompt_1
    for name in _PACKET_BLOCKS:
        assert f"=== {name} ===" in prompt_1 and f"=== {name} ===" not in shared_text
    assert "packet 1 of 2" in prompt_1 and "packet 2 of 2" in prompt_2


# ------------------------------------------------------------ B4: usage


def _usage(read: int, written: int, fresh: int) -> dict:
    return {"cache_read_input_tokens": read, "cache_creation_input_tokens": written,
            "input_tokens": fresh, "output_tokens": 7}


def test_the_backend_reports_first_response_and_session_cache_usage(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    shared = tmp_path / "run" / "brief-shared.md"
    spec = _steward_spec(home, tmp_path, shared_brief=shared)
    messages = [
        AssistantMessage(content=[TextBlock(text="one")], model="m", usage=_usage(36032, 452, 10)),
        AssistantMessage(content=[TextBlock(text="two")], model="m", usage=_usage(40000, 90, 3)),
        ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                      num_turns=2, session_id="s-1", total_cost_usd=0.01,
                      usage=_usage(76032, 542, 13)),
    ]
    monkeypatch.setattr(backend, "ClaudeSDKClient", lambda options: FakeSdkClient(pid=None, messages=messages))

    outcome = backend.SdkBackend().write_session(spec)

    assert outcome.ok
    assert outcome.usage_first_response == {
        "cache_read_input_tokens": 36032, "cache_creation_input_tokens": 452, "input_tokens": 10,
    }
    assert outcome.usage_session == {
        "cache_read_input_tokens": 76032, "cache_creation_input_tokens": 542, "input_tokens": 13,
    }


def test_the_run_record_keeps_each_calls_cache_usage(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _seed_fresh_proposals(home, 1)
    _enable_steward(home)
    first = {"cache_read_input_tokens": 36032, "cache_creation_input_tokens": 452, "input_tokens": 10}
    total = {"cache_read_input_tokens": 90000, "cache_creation_input_tokens": 900, "input_tokens": 40}

    def with_usage(spec):
        _write_decision_stage(spec)
        return backend.SdkOutcome(ok=True, rc=0, stdout="", detail="", failure=None,
                                  usage_first_response=first, usage_session=total)

    monkeypatch.setattr(steward.invocation, "write_session", with_usage)

    result = steward.run(home)

    from test_steward import _head_manifest

    attempt = _head_manifest(home, result.run_id)["packets"][0]["attempts"][0]
    assert attempt["kind"] == "decision"
    assert attempt["usage"] == {"first_response": first, "session": total}
