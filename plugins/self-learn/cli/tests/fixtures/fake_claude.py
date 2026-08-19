#!/usr/bin/env python3
"""U-sdk §3.10 `Fake-2` — a `SELF_LEARN_SDK_CLI_PATH`-shimmed fake `claude`
binary, ported from the UI's fixture of the same name
(`plugins/self-learn/ui/tests/fixtures/fake_claude.py`): the control
protocol ports verbatim (argv accepted and ignored; the first stdin
`control_request` with `subtype == "initialize"` answered immediately;
any other `control_request` gets a generic success reply so
`interrupt()` never hangs; a `{"type": "user"}` message's content string
selects a scenario; EOF exits 0). NO network access, NO real model,
anywhere in this file.

This unit's OWN scenario set (`Fake-2`'s table) plus a permission
round-trip: `ok_write` emits a real `can_use_tool` control_request (the
CLI-initiated direction — the SDK receives it FROM the child's stdout and
answers on the child's stdin) for a `Write` on a path read from
`FAKE_CLAUDE_WRITE_TARGET` (falling back to a fixed path), so the charter
callback actually runs end-to-end. Reading uses `sys.stdin.readline()`
exclusively (never `for line in sys.stdin:`), because a scenario that
blocks on a NESTED read (waiting for that control_response) would
otherwise desync against the outer loop's iterator read-ahead buffer.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time

SESSION_ID = "fake-session-1"


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def emit_raw(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def read_line() -> str | None:
    """Blocking single-line read; `None` on EOF. `main()` and the
    scenarios that need a nested read (the permission round-trip) both
    use ONLY this, never the file's iterator protocol."""
    raw = sys.stdin.readline()
    if raw == "":
        return None
    return raw


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


def user_tool_result(tool_use_id: str, uuid: str, *, content: str, is_error: bool) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "session_id": SESSION_ID,
        "parent_tool_use_id": None,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
    }


def result_message(
    *,
    is_error: bool,
    subtype: str,
    uuid: str,
    errors: list[str] | None = None,
    result: str | None = None,
) -> dict:
    msg: dict = {
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
    if result is not None:
        msg["result"] = result
    return msg


def _request_permission(tool_name: str, tool_input: dict, tool_use_id: str) -> dict:
    """Emits a `can_use_tool` control_request (CLI -> SDK direction) and
    blocks for the matching `control_response`. Any OTHER line seen while
    waiting (there should not be one, in these scenarios) is ignored
    rather than wedging the fake."""
    request_id = f"perm-{tool_use_id}"
    emit(
        {
            "type": "control_request",
            "request_id": request_id,
            "request": {
                "subtype": "can_use_tool",
                "tool_name": tool_name,
                "input": tool_input,
                "tool_use_id": tool_use_id,
                "permission_suggestions": [],
            },
        }
    )
    while True:
        line = read_line()
        if line is None:
            return {}
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "control_response":
            response = data.get("response", {})
            if response.get("request_id") == request_id:
                return response.get("response", {}) or {}
        # a stray control_request (not expected here) or anything else:
        # keep waiting for our own response rather than mis-handling it.


def _scenario_ok_text() -> None:
    # `M41`/`E-7`: the assistant text and the `ResultMessage.result` are
    # DELIBERATE SENTINELS, not the same string -- E-7's branch order
    # (branch 1, `ResultMessage.result`, wins over branch 2, the final
    # AssistantMessage's text) is untestable if the two happen to match.
    emit(assistant_message("ASSISTANT-SENTINEL", "u1"))
    emit(result_message(is_error=False, subtype="success", uuid="u2", result="RESULT-SENTINEL"))


def _scenario_ok_blocks_only() -> None:
    emit(assistant_message("Hello from blocks", "u1"))
    emit(result_message(is_error=False, subtype="success", uuid="u2"))


def _scenario_ok_write() -> None:
    target = os.environ.get("FAKE_CLAUDE_WRITE_TARGET", "/tmp/example/pending/lrn-abc.md")
    tool_name = os.environ.get("FAKE_CLAUDE_WRITE_TOOL", "Write")
    tool_use_id = "toolu_1"
    response = _request_permission(tool_name, {"file_path": target}, tool_use_id)
    allowed = response.get("behavior") == "allow"
    emit(
        assistant_message(
            "",
            "u1",
            content=[
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": {"file_path": target},
                }
            ],
        )
    )
    emit(
        user_tool_result(
            tool_use_id,
            "u2",
            content="ok" if allowed else response.get("message", "permission denied"),
            is_error=not allowed,
        )
    )
    emit(result_message(is_error=False, subtype="success", uuid="u3"))


def _scenario_error_result() -> None:
    emit(assistant_message("trying...", "u1"))
    emit(result_message(is_error=True, subtype="error_during_execution", uuid="u2", errors=["boom"]))


def _scenario_no_result() -> None:
    emit(assistant_message("partial, then nothing", "u1"))
    sys.stdout.flush()
    sys.exit(0)  # clean exit -- EOF on the SDK's read side, deliberately
    # no ResultMessage ever emitted.


def _scenario_hard_exit() -> None:
    emit(assistant_message("about to die", "u1"))
    sys.stdout.flush()
    os._exit(1)  # noqa: SLF001 - deliberate hard kill, no cleanup, no result


def _scenario_hang() -> None:
    time.sleep(3600)


def _scenario_hang_sigterm_ignored() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(3600)


def _scenario_malformed_line() -> None:
    emit(assistant_message("before", "u1"))
    # Not JSON, and does not start with "{" -- the SDK's own transport
    # layer skips this silently and keeps reading.
    emit_raw("not json output from a misbehaving build")
    emit(assistant_message("after", "u2"))
    emit(result_message(is_error=False, subtype="success", uuid="u3"))


def _scenario_unknown_message_type() -> None:
    """`M42`/`OU8`: `malformed_line` is skipped by the SDK's OWN
    transport layer before any message object is ever constructed --
    `O-drain`'s "every other message type is tolerated by skipping" is
    about a message that DOES reach `client.receive_response()` as a
    real, parsed object our drain's `if/elif` chain does not explicitly
    branch on. A `stream_event` line is exactly that: a message type the
    SDK's parser recognizes and constructs (`StreamEvent`), which
    `receive_response()` forwards like any other message ahead of the
    terminating `ResultMessage`, and which this unit's drain must
    silently skip rather than raise on."""
    emit(
        {
            "type": "stream_event",
            "uuid": "u-se1",
            "session_id": SESSION_ID,
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "partial"}},
        }
    )
    emit(assistant_message("after the stream event", "u1"))
    emit(result_message(is_error=False, subtype="success", uuid="u2", result="after the stream event"))


SCENARIOS = {
    "ok_text": _scenario_ok_text,
    "ok_blocks_only": _scenario_ok_blocks_only,
    "ok_write": _scenario_ok_write,
    "error_result": _scenario_error_result,
    "no_result": _scenario_no_result,
    "hard_exit": _scenario_hard_exit,
    "hang": _scenario_hang,
    "hang_sigterm_ignored": _scenario_hang_sigterm_ignored,
    "malformed_line": _scenario_malformed_line,
    "unknown_message_type": _scenario_unknown_message_type,
}


def _respond_control_success(request_id: str, response: dict | None = None) -> None:
    emit(
        {
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id, "response": response or {}},
        }
    )


def main() -> int:
    while True:
        raw_line = read_line()
        if raw_line is None:
            return 0
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
            # `MAJOR-2`: a REAL `worker.run()` prompt is a long, dynamic,
            # record-specific string that can never match a fixed
            # SCENARIOS key by exact equality -- so a test driving the
            # charter end-to-end through the real `SELF_LEARN_ENFORCE_SCOPE`
            # variable and the real prompt (rather than a hand-built
            # `SessionSpec`) needs a way to pick a canned scenario anyway.
            # `FAKE_CLAUDE_FORCE_SCENARIO`, when set, overrides content
            # matching unconditionally -- a test-fixture-only knob, no
            # production code reads it, and it changes nothing about which
            # scenarios exist or what they do.
            forced = os.environ.get("FAKE_CLAUDE_FORCE_SCENARIO")
            scenario = SCENARIOS.get(forced) if forced else SCENARIOS.get(content)
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
        # Anything else on stdin is ignored -- this fake only understands
        # control_request/initialize and one user message per turn.


if __name__ == "__main__":
    sys.exit(main())
