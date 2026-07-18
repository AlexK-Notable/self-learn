"""The ``sdk`` :class:`~self_learn_ui.engine.base.PaneEngine` (09 §4.1's
decision: the Agent SDK is the default pane engine; 10 §1's pane-engine
construction row, verbatim):

``ClaudeSDKClient`` in streaming mode (the ``can_use_tool`` callback
refuses to run under any other mode — probes memo footgun A/C) with:

- ``include_partial_messages=True`` — chunk-level deltas (probe 1),
- ``setting_sources=[]`` **explicit** — never rely on the SDK's default,
  which loads the full user environment on this stack (probe 3),
- ``allowed_tools=[]`` — a listed tool auto-approves before the callback
  runs (footgun B); leaving it empty routes every tool call through
  :func:`~self_learn_ui.engine.charter.build_can_use_tool`,
- ``disallowed_tools=["Bash", "Task", "WebSearch", "WebFetch"]`` —
  structural denies as belt, the callback as braces,
- ``can_use_tool`` — the charter callback,
- ``strict_mcp_config=True`` — confirmed-present field on 0.2.121; no MCP
  servers configured, so this is belt on top of "nothing to connect to",
- session persistence off. **Verify-at-build finding (see the module's
  bottom docstring and the U5 report): no ``ClaudeAgentOptions`` field
  named anything like "session persistence" exists on the resolved SDK
  (0.2.121, pin range ``>=0.2.116,<0.3``) — the X-7 contingency fires:
  the CLI's own ``--no-session-persistence`` flag (confirmed present via
  ``claude --help`` on the bundled 2.1.212 CLI) is passed through
  ``extra_args={"no-session-persistence": None}``.**
- ``cwd`` = the item's bucket root,
- ``model``/``fallback_model``/``max_turns``/``max_budget_usd`` — all
  four confirmed-present fields (09 §4.1's table; re-verified here on
  0.2.121). Wrapper-side cap enforcement (W-4) is therefore NOT invoked
  for turns/budget — only session-persistence needed the contingency.

Message -> :mod:`~self_learn_ui.engine.base` ``PaneEvent`` mapping
tolerates unknown message/event types by skipping them (never raising);
malformed (non-JSON) CLI stdout lines are already skipped by the SDK's
own transport layer before they ever reach this module (verified against
the installed SDK source — ``subprocess_cli._parse_stdout_line``) — this
module attaches a logging handler that forwards the SDK's own
``logger.debug`` calls for those two cases into ``uilog``, rather than
re-implementing the tolerance a second time.

Interrupt ladder (09 §4.2): SDK ``interrupt()`` call, then force-close the
client if the turn is still active after ``interrupt_grace_secs``
(default 2s), with a further ``interrupt_kill_secs`` (default 5s total)
before giving up and closing regardless. ``interrupt()`` on a session that
never started, or whose last turn already produced a ``Result``, is a
no-op (10 §3 U5's pinned test case).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from .. import uilog
from ..proposals import PROPOSAL_SERVER_NAME, PROPOSAL_TOOL_NAME, PROPOSAL_TOOL_QUALIFIED_NAME
from .base import BlockStart, FileChanged, PaneContext, PaneEngine, PaneEvent, Result, TextDelta, ToolUse
from .charter import build_can_use_tool

__all__ = ["DEFAULT_FALLBACK_MODEL", "SdkPaneEngine"]

#: 09 §4.2's pinned default — not env-configurable (only the primary model
#: has an env var; the fallback is a fixed pin).
DEFAULT_FALLBACK_MODEL = "claude-haiku-4-5"

#: 09 §4.2's interrupt ladder timings.
DEFAULT_INTERRUPT_GRACE_SECS = 2.0
DEFAULT_INTERRUPT_KILL_SECS = 5.0

#: File-writing tool names that make a completed ToolResultBlock worth
#: turning into a FileChanged event (09 §2.4's live re-render signal).
_WRITE_TOOLS = frozenset({"Edit", "Write"})


class _ForwardSdkLogToUiLog(logging.Handler):
    """Forwards the SDK's own ``logger.debug``/``logger.warning`` calls
    (which already implement "skip a malformed/unknown line", see the
    module docstring) into ``uilog`` — this module's "+log" half of
    10 §3's "malformed line -> skip+log" / "unknown event type -> skip"
    pins, without re-detecting what the SDK transport already detected.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            uilog.log(f"sdk[{record.name}]: {record.getMessage()}")
        except Exception:  # pragma: no cover - logging must never raise
            pass


_forward_handler = _ForwardSdkLogToUiLog(level=logging.DEBUG)


def _install_log_forwarding() -> None:
    sdk_logger = logging.getLogger("claude_agent_sdk")
    if _forward_handler not in sdk_logger.handlers:
        sdk_logger.addHandler(_forward_handler)
        sdk_logger.setLevel(logging.DEBUG)


def _tool_target(tool_input: dict[str, Any]) -> str | None:
    value = tool_input.get("file_path")
    return value if isinstance(value, str) and value else None


class SdkPaneEngine(PaneEngine):
    """The ``sdk`` engine. One instance is one pane session's worth of
    lifetime — a fresh :class:`SdkPaneEngine` per Iterate (09 §4.2: "fresh
    session per Iterate. No resume across Iterates")."""

    def __init__(
        self,
        *,
        model: str,
        fallback_model: str = DEFAULT_FALLBACK_MODEL,
        max_turns: int,
        max_budget_usd: float,
        cli_path: str | Path | None = None,
        canon_read_roots_fn: Callable[[], Iterable[Path | str]] | None = None,
        interrupt_grace_secs: float = DEFAULT_INTERRUPT_GRACE_SECS,
        interrupt_kill_secs: float = DEFAULT_INTERRUPT_KILL_SECS,
    ) -> None:
        _install_log_forwarding()
        self._model = model
        self._fallback_model = fallback_model
        self._max_turns = max_turns
        self._max_budget_usd = max_budget_usd
        self._cli_path = str(cli_path) if cli_path is not None else None
        self._canon_read_roots_fn = canon_read_roots_fn
        self._interrupt_grace_secs = interrupt_grace_secs
        self._interrupt_kill_secs = interrupt_kill_secs

        self._client: ClaudeSDKClient | None = None
        self._session_active = False
        self._pending_tool_uses: dict[str, tuple[str, str | None]] = {}

    # -- PaneEngine ---------------------------------------------------

    async def start(self, ctx: PaneContext) -> AsyncIterator[PaneEvent]:
        options = self._build_options(ctx)
        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._client = client
        self._pending_tool_uses = {}
        await client.query(ctx.first_message)
        async for event in self._drain():
            yield event

    async def send(self, text: str) -> AsyncIterator[PaneEvent]:
        if self._client is None:
            raise RuntimeError("SdkPaneEngine.send() called before start()")
        self._session_active = True
        await self._client.query(text)
        async for event in self._drain():
            yield event

    async def interrupt(self) -> None:
        if self._client is None or not self._session_active:
            return  # no-op: nothing running (never started, or already ended)
        try:
            await self._client.interrupt()
        except Exception as exc:  # noqa: BLE001 - any transport failure escalates
            uilog.log(f"pane engine interrupt: SDK interrupt() failed, escalating: {exc}")
            await self.close()
            return

        # Escalation ladder (09 §4.2): grace window, then force-close.
        try:
            await asyncio.wait_for(
                self._wait_until_inactive(), timeout=self._interrupt_grace_secs
            )
            return
        except TimeoutError:
            pass
        try:
            await asyncio.wait_for(
                self._wait_until_inactive(),
                timeout=max(self._interrupt_kill_secs - self._interrupt_grace_secs, 0),
            )
            return
        except TimeoutError:
            uilog.log("pane engine interrupt: grace + kill window exhausted — force-closing")
            await self.close()

    async def close(self) -> None:
        client, self._client = self._client, None
        self._session_active = False
        if client is not None:
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001 - close() must never raise
                uilog.log(f"pane engine close: disconnect() raised: {exc}")

    # -- internals ------------------------------------------------------

    async def _wait_until_inactive(self) -> None:
        while self._session_active:
            await asyncio.sleep(0.05)

    def _build_options(self, ctx: PaneContext) -> ClaudeAgentOptions:
        # Y-13 (09 §4.3 as amended): the strict MCP config carries exactly
        # ONE entry — the server's own in-process tool server exposing
        # propose_verb — and only when the session was handed a handler.
        # The handler runs in server code (self_learn_ui.proposals); the
        # charter's allow-rule matches the fully-qualified name EXACTLY.
        # `allowed_tools` stays [] (footgun B) — T-B(6) proves the call
        # routes through the callback on the resolved SDK version.
        mcp_servers: dict[str, Any] = {}
        extra_allowed: tuple[str, ...] = ()
        if ctx.propose_handler is not None:
            handler = ctx.propose_handler

            @tool(
                PROPOSAL_TOOL_NAME,
                "Propose a resolution verb (route/reject/defer/graduate) on a "
                "pending record. The human sees the proposal and decides — "
                "nothing executes unless they confirm. Args: verb, record_id, "
                "and optionally dest (route only), note (<=200 chars), "
                "until (defer only, YYYY-MM-DD).",
                {
                    "verb": str,
                    "record_id": str,
                    "dest": str | None,
                    "note": str | None,
                    "until": str | None,
                },
            )
            async def propose_verb_tool(args: dict[str, Any]) -> dict[str, Any]:
                text = await handler(args)
                return {"content": [{"type": "text", "text": text}]}

            mcp_servers[PROPOSAL_SERVER_NAME] = create_sdk_mcp_server(
                name=PROPOSAL_SERVER_NAME, tools=[propose_verb_tool]
            )
            extra_allowed = (PROPOSAL_TOOL_QUALIFIED_NAME,)

        can_use_tool = build_can_use_tool(
            self_learn_home=ctx.self_learn_home,
            bucket_root=ctx.bucket_root,
            record_id=ctx.record_id,
            canon_read_roots_fn=self._canon_read_roots_fn,
            extra_allowed_tools=extra_allowed,
            zero_write=ctx.session_kind == "bucket",
        )
        # X-7 fallback (see module docstring): no ClaudeAgentOptions field
        # matches "session persistence" on the resolved SDK — pass the
        # CLI's own flag straight through extra_args.
        extra_args: dict[str, str | None] = {"no-session-persistence": None}
        return ClaudeAgentOptions(
            cwd=str(ctx.bucket_root),
            system_prompt=ctx.system_prompt,
            include_partial_messages=True,
            setting_sources=[],
            allowed_tools=[],
            disallowed_tools=["Bash", "Task", "WebSearch", "WebFetch"],
            can_use_tool=can_use_tool,
            strict_mcp_config=True,
            mcp_servers=mcp_servers,
            model=self._model,
            fallback_model=self._fallback_model,
            max_turns=self._max_turns,
            max_budget_usd=self._max_budget_usd,
            cli_path=self._cli_path,
            extra_args=extra_args,
        )

    async def _drain(self) -> AsyncIterator[PaneEvent]:
        assert self._client is not None
        self._session_active = True
        try:
            async for message in self._client.receive_response():
                for event in self._map_message(message):
                    yield event
            self._session_active = False
        except Exception as exc:  # noqa: BLE001 - a dead/crashed session, not a bug here
            uilog.log(f"pane engine: session ended abnormally ({type(exc).__name__}): {exc}")
            self._session_active = False
            yield Result(status="error", cost_usd=None, error=str(exc))

    def _map_message(self, message: object) -> list[PaneEvent]:
        if isinstance(message, StreamEvent):
            return self._map_stream_event(message)
        if isinstance(message, AssistantMessage):
            return self._map_assistant(message)
        if isinstance(message, UserMessage):
            return self._map_user(message)
        if isinstance(message, ResultMessage):
            return [self._map_result(message)]
        # SystemMessage / HookEventMessage / RateLimitEvent / Task* /
        # MirrorErrorMessage: no PaneEvent vocabulary covers these —
        # tolerate silently (09 §4.2: "tolerate unknown message types
        # mid-stream — RateLimitEvent observed on Max OAuth").
        return []

    def _map_stream_event(self, message: StreamEvent) -> list[PaneEvent]:
        event = message.event if isinstance(message.event, dict) else {}
        event_type = event.get("type")
        if event_type == "content_block_start":
            block = event.get("content_block")
            kind = block.get("type", "unknown") if isinstance(block, dict) else "unknown"
            return [BlockStart(kind=kind)]
        if event_type == "content_block_delta":
            delta = event.get("delta")
            if not isinstance(delta, dict):
                return []
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                return [TextDelta(text=delta.get("text", ""))]
            if delta_type == "thinking_delta":
                return [TextDelta(text=delta.get("thinking", ""))]
            return []  # unrecognized delta type — skip (10 §3 U5 pin)
        # content_block_stop / message_start / message_delta / message_stop
        # / any future event type: no PaneEvent maps to it — skip.
        return []

    def _map_assistant(self, message: AssistantMessage) -> list[PaneEvent]:
        events: list[PaneEvent] = []
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                target = _tool_target(block.input)
                self._pending_tool_uses[block.id] = (block.name, target)
                events.append(ToolUse(name=block.name, target=target))
        return events

    def _map_user(self, message: UserMessage) -> list[PaneEvent]:
        events: list[PaneEvent] = []
        content = message.content
        if not isinstance(content, list):
            return events
        for block in content:
            if isinstance(block, ToolResultBlock) and not block.is_error:
                pending = self._pending_tool_uses.pop(block.tool_use_id, None)
                if pending is None:
                    continue
                name, target = pending
                if name in _WRITE_TOOLS and target:
                    events.append(FileChanged(path=target))
        return events

    def _map_result(self, message: ResultMessage) -> Result:
        error: str | None = None
        if message.is_error:
            if message.errors:
                error = "; ".join(message.errors)
            elif message.result:
                error = message.result
            else:
                error = message.subtype
        turns = getattr(message, "num_turns", None)
        return Result(
            status=message.subtype,
            cost_usd=message.total_cost_usd,
            error=error,
            turns=turns if isinstance(turns, int) else None,
        )
