#!/usr/bin/env python3
"""A PATH/``cli_path``-shimmed fake ``claude`` binary (10 §0 rule 7): speaks
just enough of the Agent SDK's bidirectional stream-json control protocol
to drive :class:`self_learn_ui.engine.sdk.SdkPaneEngine` through canned
scenarios, with NO network access and NO real model anywhere in the loop.

Invoked exactly like the real CLI would be (argv is accepted and ignored —
this fake never inspects flags): the SDK always runs
``ClaudeSDKClient`` in streaming mode, so the protocol is fixed regardless
of ``ClaudeAgentOptions``:

1. First stdin line is always a ``control_request`` with
   ``request.subtype == "initialize"`` — reply with a success
   ``control_response`` immediately (every real session needs this before
   anything else happens; skipping it hangs the SDK on
   ``query.initialize()``'s 60s timeout).
2. Then read stdin lines; a ``{"type": "user", ...}`` message starts one
   "turn" — its ``message.content`` string selects a scenario from
   :data:`SCENARIOS` below, which is replayed to stdout line-by-line.
   Any other ``control_request`` (e.g. ``interrupt``) gets a generic
   success reply so the SDK never hangs waiting on one.
3. On stdin EOF, exit 0 — except the ``mid_stream_kill`` scenario, which
   calls ``os._exit(1)`` mid-replay to simulate a crashed subprocess
   (verified against the installed SDK: a nonzero exit becomes a
   ``ProcessError`` that ``Query.receive_messages()`` re-raises as a
   plain ``Exception`` on the message stream).

Scenario transcripts are literal NDJSON dicts matching the exact required
fields of ``claude_agent_sdk._internal.message_parser.parse_message`` for
each message ``type`` (verified against the installed SDK source, 0.2.121
— the U5 verify-at-build ledger).
"""

from __future__ import annotations

import json
import os
import sys

SESSION_ID = "fake-session-1"


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def emit_raw(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def stream_event(event: dict, uuid: str) -> dict:
    return {"type": "stream_event", "uuid": uuid, "session_id": SESSION_ID, "event": event}


def content_block_start(index: int, kind: str, uuid: str) -> dict:
    return stream_event(
        {"type": "content_block_start", "index": index, "content_block": {"type": kind}}, uuid
    )


def text_delta(index: int, text: str, uuid: str) -> dict:
    return stream_event(
        {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}},
        uuid,
    )


def assistant_message(text: str, uuid: str, content: list[dict] | None = None) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "session_id": SESSION_ID,
        "parent_tool_use_id": None,
        "message": {
            "id": "msg_1",
            "model": "claude-sonnet-5",
            "stop_reason": "end_turn",
            "usage": {},
            "content": content if content is not None else [{"type": "text", "text": text}],
        },
    }


def result_message(*, is_error: bool, subtype: str, uuid: str, errors: list[str] | None = None) -> dict:
    msg = {
        "type": "result",
        "uuid": uuid,
        "subtype": subtype,
        "duration_ms": 10,
        "duration_api_ms": 8,
        "is_error": is_error,
        "num_turns": 1,
        "session_id": SESSION_ID,
        "total_cost_usd": 0.001,
    }
    if errors:
        msg["errors"] = errors
    return msg


def _scenario_happy() -> None:
    emit(content_block_start(0, "text", "u1"))
    emit(text_delta(0, "Hello ", "u2"))
    emit(text_delta(0, "world", "u3"))
    emit(assistant_message("Hello world", "u4"))
    emit(result_message(is_error=False, subtype="success", uuid="u5"))


def _scenario_error_result() -> None:
    emit(content_block_start(0, "text", "u1"))
    emit(text_delta(0, "trying...", "u2"))
    emit(assistant_message("trying...", "u3"))
    emit(result_message(is_error=True, subtype="error_during_execution", uuid="u4", errors=["boom"]))


def _scenario_mid_stream_kill() -> None:
    emit(content_block_start(0, "text", "u1"))
    emit(text_delta(0, "partway", "u2"))
    sys.stdout.flush()
    os._exit(1)  # noqa: SLF001 - deliberate hard kill, no cleanup, no result


def _scenario_malformed_line() -> None:
    emit(content_block_start(0, "text", "u1"))
    emit(text_delta(0, "before", "u2"))
    # Not JSON, and does not start with "{" — the SDK's own transport
    # layer (_parse_stdout_line) skips this silently and keeps reading.
    emit_raw("not json output from a misbehaving build")
    emit(text_delta(0, "after", "u3"))
    emit(assistant_message("beforeafter", "u4"))
    emit(result_message(is_error=False, subtype="success", uuid="u5"))


def _scenario_unknown_event_type() -> None:
    emit(content_block_start(0, "text", "u1"))
    emit(text_delta(0, "A", "u2"))
    # A recognized top-level "stream_event" wrapping an inner event type
    # our OWN mapper doesn't know — must be skipped, not raised.
    emit(stream_event({"type": "some_future_event_type", "foo": "bar"}, "u3"))
    emit(text_delta(0, "B", "u4"))
    emit(assistant_message("AB", "u5"))
    emit(result_message(is_error=False, subtype="success", uuid="u6"))


def _scenario_tool_use() -> None:
    emit(
        assistant_message(
            "",
            "u1",
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Edit",
                    "input": {"file_path": "/tmp/example/pending/lrn-abc.md"},
                }
            ],
        )
    )
    emit(
        {
            "type": "user",
            "uuid": "u2",
            "session_id": SESSION_ID,
            "parent_tool_use_id": None,
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok", "is_error": False}
                ],
            },
        }
    )
    emit(result_message(is_error=False, subtype="success", uuid="u3"))


SCENARIOS = {
    "happy_path": _scenario_happy,
    "error_result": _scenario_error_result,
    "mid_stream_kill": _scenario_mid_stream_kill,
    "malformed_line": _scenario_malformed_line,
    "unknown_event_type": _scenario_unknown_event_type,
    "tool_use": _scenario_tool_use,
}


def _respond_control_success(request_id: str, response: dict | None = None) -> None:
    emit(
        {
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id, "response": response or {}},
        }
    )


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        if data.get("type") == "control_request":
            request_id = data.get("request_id", "")
            _respond_control_success(request_id)
            continue

        if data.get("type") == "user":
            content = data.get("message", {}).get("content", "")
            scenario = SCENARIOS.get(content)
            if scenario is not None:
                scenario()
            else:
                emit(
                    result_message(
                        is_error=True,
                        subtype="error_unknown_scenario",
                        uuid="u-err",
                        errors=[f"fake_claude: no such scenario {content!r}"],
                    )
                )
            continue
        # Anything else on stdin is ignored — this fake only understands
        # control_request/initialize and one user message per turn.

    return 0


if __name__ == "__main__":
    sys.exit(main())
