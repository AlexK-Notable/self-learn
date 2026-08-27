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
- **session persistence (corrected 2026-07-19, task U22 / Y-28).** The
  U5-era claim above ("no field named anything like session persistence
  exists") is STALE: 0.2.121 ships ``resume: str | None``,
  ``session_id``, and a first-class ``session_store: SessionStore | None``
  (a duck-typed Protocol — ``append``/``load`` only required). The X-7
  privacy rationale for ``extra_args={"no-session-persistence": None}``
  is retired: session materialization already lands in a temporary,
  SDK-cleaned location, so the flag bought a privacy property the store
  mechanism now provides natively — and the flag is actively
  INCOMPATIBLE with resume (``claude --help`` verbatim: "sessions will
  not be saved to disk and cannot be resumed"). **Live build-trial
  (2026-07-19, subscription-auth streaming path, real model, both
  probes against raw ``claude_agent_sdk`` before any wiring landed —
  recorded in ``docs/specs/self-learn/fixtures/ui-trials.md``): (i)
  with the flag DROPPED, ``session_store.append`` populated a
  cache-local mirror file during a live streaming turn — PASS; (ii)
  ``resume=<captured session_id>`` on a FRESH ``ClaudeSDKClient``
  restored context — the resumed turn correctly quoted a phrase from the
  torn-down turn it never saw — PASS.** Both passed, so Tier 2 ships as
  SDK-resume: ``TIER2_SESSION_STORE_ENABLED = True`` below,
  :func:`_build_options` drops the flag and wires
  ``session_store=CacheSdkSessionStore(...)`` on EVERY session (so a
  session_id is captured for a LATER resume, even on a first, non-resumed
  Iterate) plus ``resume=ctx.resume_session_id`` when the caller (a Y-28
  Resume) set one on :class:`~self_learn_ui.engine.base.PaneContext`.
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

Interrupt ladder (09 §4.2, tuned 2026-07-18): bounded SDK ``interrupt()``
ack, then force-close the client if the turn is still active after
``interrupt_grace_secs`` (default 1s), killing at ``interrupt_kill_secs``
(default 2.5s) — every wait derived from ONE deadline anchored at the
keystroke, and ``close()``'s ``disconnect()`` shield-and-abandoned at the
kill bound (never cancelled — a raw cancel would pierce the SDK
transport's shielded SIGTERM/SIGKILL escalation). ``interrupt()`` on a
session that never started, or whose last turn already produced a
``Result``, is a no-op (10 §3 U5's pinned test case).
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

from self_learn.sdksession import ladder as sdk_ladder
from self_learn.sdksession import policy as sdk_policy
from self_learn.sdksession import result as sdk_result
from self_learn.sdksession import session as sdk_session_lib
from self_learn.sdksession import teardown as sdk_teardown

from .. import uilog
from ..proposals import PROPOSAL_SERVER_NAME, PROPOSAL_TOOL_NAME, PROPOSAL_TOOL_QUALIFIED_NAME
from ..store import CacheSdkSessionStore
from .base import BlockStart, FileChanged, PaneContext, PaneEngine, PaneEvent, Result, TextDelta, ToolUse
from .charter import build_can_use_tool

__all__ = [
    "DEFAULT_FALLBACK_MODEL",
    "TIER2_SESSION_STORE_ENABLED",
    "UI_SHUTDOWN_MESSAGES",
    "SdkPaneEngine",
]

#: 09 §4.2's pinned default — not env-configurable (only the primary model
#: has an env var; the fallback is a fixed pin).
DEFAULT_FALLBACK_MODEL = "claude-haiku-4-5"

#: Y-28 §1's build-trial gate outcome (module docstring above has the
#: dated finding): both probes PASSED on 2026-07-19 against the resolved
#: SDK on the subscription-auth streaming path, so Tier 2 ships as
#: SDK-resume. Flipping this back to ``False`` alone reverts to the
#: pre-U22 ``no-session-persistence`` posture (Tier 1 still works
#: unaffected — it never depends on this flag).
TIER2_SESSION_STORE_ENABLED = True

#: 09 §4.2's interrupt ladder timings.
#: Tuned 2026-07-18 (09 §4.2, T-E follow-up): the SDK fast-interrupt is
#: ineffective on the subscription-auth streaming path, so the ladder is
#: the COMMON Esc path — a keystroke deserves ~2.7 s worst case, not ~5.3.
#: `LAD3` -- rebound to the library's own objects, by IDENTITY (Python
#: assignment never copies): `sdk_ladder.INTERRUPT_GRACE_SECS is
#: DEFAULT_INTERRUPT_GRACE_SECS` holds from the moment this module is
#: imported, not merely `==`. Values unchanged (1.0 / 2.5, tuned
#: 2026-07-18) -- only the ONE definition moved to `sdksession/ladder.py`
#: (spec Sec 4.2); `test_default_ladder_constants_match_the_tuned_pin`
#: (unedited) still passes because the `==` checks it makes still hold.
DEFAULT_INTERRUPT_GRACE_SECS = sdk_ladder.INTERRUPT_GRACE_SECS
DEFAULT_INTERRUPT_KILL_SECS = sdk_ladder.KILL_SECS

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


#: `POL2`/`PIN1` -- this client's own shutdown/ladder message table
#: (spec Sec 2.8's 10 UI-owned rows: 5 close-ladder + 3 interrupt-ladder
#: + 1 drain + 1 client-owned SDK-log-forwarding line, the last never
#: carried in this table -- Sec 2.8 CORRECTED-r3 keeps it UI-side by
#: design, G-4/C-4). Every field's text is byte-identical to what this
#: module printed before the extraction -- only the close-ladder's FIVE
#: lines now render through the library (`sdk_teardown.run_kill_ladder`)
#: instead of being inlined here.
UI_SHUTDOWN_MESSAGES = sdk_policy.ShutdownMessages(
    disconnect_timeout=(
        "pane engine close: disconnect() still running at the kill "
        "bound — caller released; SDK subprocess escalation "
        "continues in the background"
    ),
    disconnect_raised="pane engine close: disconnect() raised: {exc}",
    abandoned_cancelled="pane engine close: abandoned disconnect() was cancelled",
    abandoned_finished="pane engine close: abandoned disconnect() finished with: {exc}",
    abandoned_completed="pane engine close: abandoned disconnect() completed",
)

#: `LAD2`/`LAD3` -- rebound to the library's own registry object, by
#: IDENTITY: `sdk_teardown.ABANDONED_DISCONNECTS is _ABANDONED_DISCONNECTS`
#: holds from import time. `run_kill_ladder`'s own `shielded_disconnect`
#: adds/discards tasks on `sdk_teardown.ABANDONED_DISCONNECTS` directly;
#: this module-level name is the SAME set object, not a copy, so it
#: still observes every abandoned task this engine creates.
_ABANDONED_DISCONNECTS = sdk_teardown.ABANDONED_DISCONNECTS


class SdkPaneEngine(PaneEngine):
    """The ``sdk`` engine. One instance is one pane session's worth of
    lifetime — a fresh :class:`SdkPaneEngine` per Iterate (09 §4.2: "fresh
    session per Iterate" — no *implicit* resume across Iterates; explicit
    Resume is Y-28/U22, opt-in per session via
    :attr:`~self_learn_ui.engine.base.PaneContext.resume_session_id`)."""

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
        sdk_session_store_root: Path | None = None,
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
        #: Y-28 Tier 2: root dir for the cache-local SDK session mirror
        #: (``cache_dir()/panes/sdk-sessions`` in production, wired by
        #: ``build_pane_manager``). ``None`` disables Tier 2 for this
        #: engine instance regardless of :data:`TIER2_SESSION_STORE_ENABLED`
        #: (a safe default for any caller that doesn't pass it — existing
        #: tests/constructions keep the pre-U22 behavior).
        self._sdk_session_store_root = sdk_session_store_root

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
        # ONE Esc-anchored deadline (review F2): every wait below derives
        # from it, so the ladder's total is ≤ interrupt_kill_secs and
        # interrupt()+close() together stay ≤ 2×kill = 5 s — the 09 §3
        # verb-dispatch pin ("≤ 5 s worst case") holds by arithmetic,
        # not by hope.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._interrupt_kill_secs
        try:
            # The SDK ack is bounded by the grace window (09 §4.2 as
            # tuned 2026-07-18). Cancel-on-timeout is safe HERE: the
            # abandoned control request is moot once close() disconnects
            # the transport (contrast disconnect(), which must never be
            # cancelled — see close()).
            await asyncio.wait_for(
                self._client.interrupt(), timeout=self._interrupt_grace_secs
            )
        except TimeoutError:
            uilog.log(
                "pane engine interrupt: SDK interrupt() unresponsive within "
                "grace — escalating to close"
            )
            await self.close()
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure escalates
            uilog.log(f"pane engine interrupt: SDK interrupt() failed, escalating: {exc}")
            await self.close()
            return

        # Escalation ladder (09 §4.2): grace window, then force-close —
        # both windows clipped to the shared deadline.
        grace_left = min(self._interrupt_grace_secs, max(deadline - loop.time(), 0))
        try:
            await asyncio.wait_for(self._wait_until_inactive(), timeout=grace_left)
            return
        except TimeoutError:
            pass
        try:
            await asyncio.wait_for(
                self._wait_until_inactive(),
                timeout=max(deadline - loop.time(), 0),
            )
            return
        except TimeoutError:
            uilog.log("pane engine interrupt: grace + kill window exhausted — force-closing")
            await self.close()

    async def close(self) -> None:
        client, self._client = self._client, None
        self._session_active = False
        if client is None:
            return
        # `teardown.run_kill_ladder` (spec Sec 4.2) -- SHIELD-and-abandon,
        # never cancel (review F1, verified against the installed SDK + an
        # empirical cancel probe): a plain wait_for CANCELS disconnect() on
        # timeout, and a raw asyncio cancellation pierces the SDK
        # transport's shielded SIGTERM/SIGKILL escalation (its own
        # docstring carries the caveat) — the caller would return "bounded"
        # while a wedged CLI child lives on with no further escalation.
        # shield() keeps the CALLER bounded at the kill window while
        # disconnect() — itself ~20 s-bounded inside the SDK — finishes
        # killing the subprocess in the background.
        #
        # `interrupt_grace_secs=None` skips step 1 -- this engine's
        # close() never ran a bounded interrupt() of its own (that is
        # `interrupt()`'s job). `loop_closing=False` skips step 3 (the
        # explicit child kill, `R-1`) -- this engine tracks no child pid
        # and never killed one; the SDK's own shielded escalation is
        # left to finish on its own, exactly as before this delegation.
        await sdk_teardown.run_kill_ladder(
            client,
            None,
            uilog.log,
            kill_secs=self._interrupt_kill_secs,
            interrupt_grace_secs=None,
            loop_closing=False,
            pid_alive=lambda _pid: False,
            messages=UI_SHUTDOWN_MESSAGES,
        )

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

            # A FULL JSON Schema, not the dict-of-types shorthand: the
            # shorthand marks every key required, and the T-B(6) live
            # trial showed the model then fills optionals with "" —
            # which the handler must treat as absent (belt in
            # proposals.validate_proposal; this schema is the braces).
            @tool(
                PROPOSAL_TOOL_NAME,
                "Propose a resolution verb (route/reject/defer/graduate/"
                "rehome) on a pending record. The human sees the proposal "
                "and decides — nothing executes unless they confirm. Args: "
                "verb, record_id, and optionally dest (route only), note "
                "(<=200 chars), until (defer only, YYYY-MM-DD), to (rehome "
                "only — a REGISTERED project's path or bucket slug; an "
                "unregistered project is a fact to tell the human, never a "
                "proposal).",
                {
                    "type": "object",
                    "properties": {
                        "verb": {"type": "string"},
                        "record_id": {"type": "string"},
                        "dest": {"type": "string"},
                        "note": {"type": "string"},
                        "until": {"type": "string"},
                        "to": {"type": "string"},
                    },
                    "required": ["verb", "record_id"],
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
        # Y-28 §1 (MAJOR-1 corrected, live build-trial PASSED both probes
        # 2026-07-19 — see module docstring): Tier 2 wires session_store +
        # resume and DROPS the flag; the flag is INCOMPATIBLE with resume
        # ("cannot be resumed"). Falls back to the old X-7 posture when
        # either the module gate is off or this instance has no session
        # store root wired (a safe default for callers that predate U22).
        extra_args: dict[str, str | None] = {}
        session_store = None
        resume = None
        if TIER2_SESSION_STORE_ENABLED and self._sdk_session_store_root is not None:
            # pyright flags this as abstract-class instantiation because
            # CacheSdkSessionStore deliberately leaves SessionStore's four
            # OPTIONAL methods undefined (store.py's class docstring: this
            # is load-bearing at RUNTIME — the SDK's own
            # `_store_implements()` probe treats an inherited-unchanged
            # method as "not implemented" by object identity, which is
            # exactly what materialize_resume_session() needs to skip
            # subkey enumeration on a store with no subagent transcripts).
            # Python itself never treats a Protocol's own concrete
            # (non-abstractmethod) bodies as abstract — this is a pyright
            # Protocol-subclass heuristic, not a real runtime constraint.
            session_store = CacheSdkSessionStore(  # pyright: ignore[reportAbstractUsage]
                self._sdk_session_store_root
            )
            resume = ctx.resume_session_id
        else:
            extra_args = {"no-session-persistence": None}
        # `POL3` -- the three keys measured identical in Sec 2.3
        # (`allowed_tools`, `setting_sources`, `strict_mcp_config`), a
        # FRESH dict every call, from the ONE shared definition both
        # engines splat (`sdk_policy.default_option_floor`).
        floor = sdk_policy.default_option_floor()
        return ClaudeAgentOptions(
            cwd=str(ctx.bucket_root),
            system_prompt=ctx.system_prompt,
            include_partial_messages=True,
            disallowed_tools=["Bash", "Task", "WebSearch", "WebFetch"],
            can_use_tool=can_use_tool,
            mcp_servers=mcp_servers,
            model=self._model,
            fallback_model=self._fallback_model,
            max_turns=self._max_turns,
            max_budget_usd=self._max_budget_usd,
            cli_path=self._cli_path,
            extra_args=extra_args,
            session_store=session_store,
            resume=resume,
            **floor,
        )

    async def _drain(self) -> AsyncIterator[PaneEvent]:
        assert self._client is not None
        self._session_active = True
        # `session.SdkSession` (spec Sec 4.2) -- does nothing except call
        # the same `receive_response()` this loop already called directly;
        # wrapping `self._client` in it changes no observable behaviour.
        session = sdk_session_lib.SdkSession(self._client)
        try:
            async for message in session.drive():
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
        # `AGR3`/`result.reduce_result_error` (Sec 2.2a's 1.000
        # skeleton-identical pair) -- errors joined by "; " when
        # non-empty, else `result` when truthy, else `subtype`. Only the
        # reduction itself moved; this engine still decides WHEN to
        # apply it (only on an errored result) and what to DO with the
        # string (`Result.error`, vs the CLI's log template).
        error: str | None = None
        if message.is_error:
            error = sdk_result.reduce_result_error(message)
        turns = getattr(message, "num_turns", None)
        session_id = getattr(message, "session_id", None)
        return Result(
            status=message.subtype,
            cost_usd=message.total_cost_usd,
            error=error,
            turns=turns if isinstance(turns, int) else None,
            session_id=session_id if isinstance(session_id, str) else None,
        )
