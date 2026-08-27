"""U-sdk — `SdkBackend`, `SdkOutcome`, `run_sync`, the options builder,
the message drain, the outcome mapping, and the analyst text extraction.

This is the orchestrator: the only module in the package permitted to
import `claude_agent_sdk` (the client and message types), `..invocation`
(the seam contract), and every sibling module (`.charter`, `.lifecycle`,
`.events`, `.provider_env`).
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, fields as _dataclass_fields
from typing import Any, TypeVar, cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLINotFoundError,
    PermissionResultAllow,
    PermissionResultDeny,
    ProcessError,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .. import provider
from ..invocation.contract import (
    LOG_TEMPLATES,
    SELECTOR_FOR_SURFACE,
    TRANSPORT,
    LogTemplates,
    Outcome,
    SessionSpec,
)
from . import charter, lifecycle
from .charter import CharterPatternUnsupported
from .events import EventLog, new_run_id, prune_event_logs, write_event_log
from .provider_env import provider_env

__all__ = ["SdkBackend", "SdkOutcome", "run_sync", "options_kwargs"]

T = TypeVar("T")

#: `O-1` -- per-surface `max_turns` defaults, keyed by `SELECTOR_FOR_SURFACE`.
_DEFAULT_MAX_TURNS: dict[str, int] = {"WORKER": 120, "MINER": 60, "ANALYST": 30}

#: `Map-1` -- surfaces on which the SDK backend enters this build's
#: analyst-vs-worker/miner OSError/ClaudeSDKError split.
_CATCHES_OS_ERROR = dict(TRANSPORT)


@dataclass(frozen=True)
class SdkOutcome(Outcome):
    """`E-1` -- a frozen SUBCLASS of `Outcome`, not five new fields on it:
    `contract.py` stays byte-frozen, and four of these five facts are
    ones no CLI-shaped backend can ever populate."""

    tool_events: tuple[dict[str, Any], ...] = ()
    denials: tuple[dict[str, Any], ...] = ()
    cost_usd: float | None = None
    turns: int | None = None
    session_id: str | None = None


# --------------------------------------------------------------- Sync-1


def run_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """`Sync-1` -- the only bridge from a synchronous call site to the
    SDK's async session. Takes a FACTORY, not a coroutine object (`Y-a`):
    a coroutine created in one thread's frame and awaited inside a
    different loop is a `RuntimeError` waiting to happen."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    # `Y-b` second branch -- a loop is already running: drive the
    # coroutine on a DEDICATED NON-DAEMON thread, join() it UNBOUNDED
    # (`Y-d`: the coroutine is itself bounded by `spec.timeout` plus the
    # kill ladder's fixed window, so a second, weaker join timeout would
    # only add a bound whose expiry has no remedy), and re-raise
    # whatever it raised with its ORIGINAL type and `__traceback__`
    # (`Y-c`).
    result_box: list[T] = []
    error_box: list[BaseException] = []

    def _thread_target() -> None:
        try:
            result_box.append(asyncio.run(factory()))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            error_box.append(exc)

    thread = threading.Thread(target=_thread_target, daemon=False)
    thread.start()
    thread.join()
    if error_box:
        raise error_box[0]
    return result_box[0]


# --------------------------------------------------------------- Opt-1


def _supported_option_fields() -> set[str]:
    """`O-1a` -- feature detection via `dataclasses.fields`, never
    `hasattr` on an instance."""
    return {f.name for f in _dataclass_fields(ClaudeAgentOptions)}


def _max_turns_for(selector: str) -> int:
    raw = os.environ.get(f"SELF_LEARN_SDK_MAX_TURNS_{selector}")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_MAX_TURNS.get(selector, 120)


def _max_budget_usd() -> float | None:
    raw = os.environ.get("SELF_LEARN_SDK_MAX_BUDGET_USD")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def options_kwargs(spec: SessionSpec, events: EventLog | None = None) -> dict[str, object]:
    """`O-0` -- the option set assembled as a MAPPING (the observation
    point `OP14` looks at), not an AST-scanned `ClaudeAgentOptions(...)`
    call. `events` defaults to a private, throwaway `EventLog` so this
    function's documented single-parameter call shape
    (`options_kwargs(spec)`) still works standalone (tests compare its
    shape against a live-driven session's own, separately-supplied,
    `EventLog`)."""
    if events is None:
        events = EventLog()

    # U-cleanup §7 -- `spec.doctrine` is a first-class field now; the CLI
    # argv relay that used to carry it (`cli_argv_builder` +
    # `_read_argv_flag`, reading exactly one flag out of a constructed
    # argv nothing else used) is gone. Only the analyst ever populates
    # this field (§2.3.1, measured) -- worker and miner-reader pass
    # `doctrine=None`.
    doctrine = spec.doctrine

    # `A-3`/`F-D` -- never `None` (an absent flag renders `--system-prompt
    # ""`), never a bare `str` (replaces Claude Code's system prompt
    # instead of appending to it).
    system_prompt: dict[str, object]
    if doctrine is not None:
        system_prompt = {"type": "preset", "preset": "claude_code", "append": doctrine}
    else:
        system_prompt = {"type": "preset", "preset": "claude_code"}

    containment = spec.containment
    disallowed = [t for t in (containment.disallowed_tools or "").split(",") if t]

    raw_can_use_tool = charter.build_can_use_tool(containment)

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        result = await raw_can_use_tool(tool_name, tool_input, context)
        if isinstance(result, PermissionResultDeny):
            # `C-9` -- every DENY is recorded, before this wrapper returns.
            events.add_denial(tool_name, result.message)
        return result

    selector = SELECTOR_FOR_SURFACE.get(spec.surface, spec.surface)
    supported = _supported_option_fields()

    kwargs: dict[str, object] = {
        "cwd": str(spec.cwd),
        "system_prompt": system_prompt,
        "model": provider.model_for(spec.surface, home=spec.cwd),  # `IN3`/`Int-1`
        "allowed_tools": [],  # `F-B` -- always, every surface
        "disallowed_tools": disallowed,
        "can_use_tool": can_use_tool,
        "permission_mode": "default",  # `O-2` -- unconditionally
        "setting_sources": [],  # `F-C` -- always
        "settings": None,  # `A-2` -- the charter is the only authority
        "strict_mcp_config": True,  # `O-3` -- unconditionally
        "mcp_servers": {},
        "include_partial_messages": False,
        "env": provider_env(spec),  # `PS-a` -- called exactly once, no merge
        # `O-4`/`IN3` -- unchanged since before `U-bedrock`: this already
        # equals `provider.resolve(home, surface).cli_path` bit-for-bit
        # (`_resolve_str_setting` resolves the same env var the same way,
        # `None` on absence), so `IN3`'s cli_path leg holds by
        # construction and this line does not need a second `resolve()`
        # call to satisfy it.
        "cli_path": os.environ.get("SELF_LEARN_SDK_CLI_PATH") or None,
    }

    if "max_turns" in supported:
        kwargs["max_turns"] = _max_turns_for(selector)
    else:
        spec.log("run: sdk backend could not apply max_turns on this claude-agent-sdk version")

    if "max_budget_usd" in supported:
        kwargs["max_budget_usd"] = _max_budget_usd()
    else:
        spec.log(
            "run: sdk backend could not apply max_budget_usd on this claude-agent-sdk version"
        )

    return kwargs


def _build_options(spec: SessionSpec, events: EventLog) -> ClaudeAgentOptions:
    # `options_kwargs` returns `dict[str, object]` deliberately (OP14
    # compares it structurally against the built options), so the
    # keyword-splat below is widened back for pyright -- the actual
    # values are exactly what `ClaudeAgentOptions.__init__` expects,
    # this is a type-checker-only cast, not a runtime behavior change.
    return ClaudeAgentOptions(**cast("dict[str, Any]", options_kwargs(spec, events)))


# --------------------------------------------------------------- Map-1


def _format(template: str, spec: SessionSpec, **kwargs: object) -> str:
    return template.format(label=spec.label, **kwargs)


def _stdout_for(spec: SessionSpec, text: str) -> str:
    """`O-stdout`/`OU7` -- `""` on both worker surfaces, the extracted
    text on the miner and the analyst."""
    return text if spec.surface in ("miner-reader", "analyst") else ""


def _extract_text(result_message: ResultMessage, last_assistant_text: str) -> str:
    """`E-7` -- branch 1: `ResultMessage.result` when it is a non-empty
    (after `.strip()`) `str`, used VERBATIM (unstripped). Branch 2/3:
    the joined `TextBlock`s of the final `AssistantMessage` (already
    `""` when there were none)."""
    value = result_message.result
    if isinstance(value, str) and value.strip():
        return value
    return last_assistant_text


def _render_exit_detail(templates: LogTemplates, detail: str) -> str:
    rendered = detail.strip() if templates.detail_strip else detail
    if templates.detail_cap is not None:
        rendered = rendered[: templates.detail_cap]
    return rendered


def _outcome(
    *,
    ok: bool,
    rc: int | None,
    stdout: str,
    detail: str,
    failure: str | None,
    events: EventLog,
    cost_usd: float | None = None,
    turns: int | None = None,
    session_id: str | None = None,
    exc: BaseException | None = None,
) -> SdkOutcome:
    return SdkOutcome(
        ok=ok,
        rc=rc,
        stdout=stdout,
        detail=detail,
        failure=failure,
        exc=exc,
        tool_events=tuple(events.tool_events),
        denials=tuple(events.denials),
        cost_usd=cost_usd,
        turns=turns,
        session_id=session_id,
    )


def _map_result_message(
    spec: SessionSpec,
    result_message: ResultMessage,
    last_assistant_text: str,
    templates: LogTemplates,
    events: EventLog,
) -> SdkOutcome:
    turns = getattr(result_message, "num_turns", None)
    session_id = getattr(result_message, "session_id", None)
    cost_usd = getattr(result_message, "total_cost_usd", None)
    turns = turns if isinstance(turns, int) else None
    session_id = session_id if isinstance(session_id, str) else None
    cost_usd = cost_usd if isinstance(cost_usd, (int, float)) else None

    permission_denials = getattr(result_message, "permission_denials", None)
    if permission_denials:
        for denial in permission_denials:
            events.add_sdk_permission_denial(denial)

    text = _extract_text(result_message, last_assistant_text)
    stdout = _stdout_for(spec, text)

    if result_message.is_error:
        if result_message.errors:
            detail = "; ".join(result_message.errors)
        elif result_message.result:
            detail = result_message.result
        else:
            detail = result_message.subtype
        assert templates.exited is not None  # T-c: worker/miner/analyst all carry this leg
        spec.log(
            _format(templates.exited, spec, rc=1, detail=_render_exit_detail(templates, detail))
        )
        return _outcome(
            ok=False,
            rc=1,
            stdout=stdout,
            detail=detail,
            failure="exit",
            events=events,
            cost_usd=cost_usd,
            turns=turns,
            session_id=session_id,
        )

    return _outcome(
        ok=True,
        rc=0,
        stdout=stdout,
        detail="",
        failure=None,
        events=events,
        cost_usd=cost_usd,
        turns=turns,
        session_id=session_id,
    )


# --------------------------------------------------------------- Sync-1 drive


async def _run_session(
    spec: SessionSpec,
    client: ClaudeSDKClient,
    options: ClaudeAgentOptions,
    events: EventLog,
    set_child_pid: Callable[[int | None], None],
) -> tuple[ResultMessage | None, str]:
    await client.connect()
    child_pid = lifecycle.child_pid_of(client)
    set_child_pid(child_pid)
    if child_pid is None:
        spec.log("run: sdk backend could not resolve the child pid")
    else:
        lifecycle.write_sidecar(spec.surface, child_pid, str(options.cli_path or ""))

    await client.query(spec.prompt)

    final: ResultMessage | None = None
    last_assistant_text = ""
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            last_assistant_text = "".join(
                block.text for block in message.content if isinstance(block, TextBlock)
            )
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    events.add_tool_use(block.id, block.name, block.input)
        elif isinstance(message, UserMessage):
            content = message.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        events.add_tool_result(
                            block.tool_use_id, bool(block.is_error), block.content
                        )
        elif isinstance(message, ResultMessage):
            final = message
        # `O-drain` -- every other message type (StreamEvent, SystemMessage,
        # HookEventMessage, RateLimitEvent, Task*...) is tolerated by
        # skipping, never raised.
    return final, last_assistant_text


async def _drive(spec: SessionSpec) -> SdkOutcome:
    events = EventLog()
    run_id = new_run_id()
    surface = spec.surface
    templates = LOG_TEMPLATES[surface]

    # `K-5` -- before connecting.
    lifecycle.sweep_orphans(surface, spec.log)
    prune_event_logs(surface)  # `E-5`

    try:
        options = _build_options(spec, events)
    except CharterPatternUnsupported as exc:
        # `C-7`/`CH7` -- the session never starts: no `ClaudeSDKClient` is
        # ever constructed. FW-108/M-1 (gate r1): this handler renders the
        # same template under the same surface guard as its neighbours
        # below, and unlike them never re-raises because no session exists
        # yet.
        if _CATCHES_OS_ERROR.get(surface, True) and templates.os_error is not None:
            spec.log(_format(templates.os_error, spec, exc=exc))
        return _outcome(
            ok=False, rc=None, stdout="", detail=str(exc), failure="os-error", events=events, exc=exc
        )
    except provider.ProviderRefused as exc:
        # `In-d`/`IN5` -- the guarded call. `_build_options` reaches
        # `provider_env(spec)` (via `options_kwargs`), which raises
        # `ProviderRefused` on a refusing bedrock+sdk resolution. Caught
        # HERE, narrowly (`ProviderRefused` only -- a different exception
        # from the same position is NOT this branch and keeps propagating,
        # `IN5`'s narrowness leg): no `ClaudeSDKClient` is ever
        # constructed, so the transport is never reached (`RT3`, `IN5`).
        # `In-c`'s shape: `failure="unavailable"`, `detail` carries
        # `Rs-d`'s two pinned tokens verbatim (`str(exc)` IS
        # `resolution.refusal`), `exc` is the `ProviderRefused` instance.
        return _outcome(
            ok=False, rc=None, stdout="", detail=str(exc), failure="unavailable", events=events, exc=exc
        )

    client = ClaudeSDKClient(options=options)
    child_pid_holder: list[int | None] = [None]

    outcome: SdkOutcome | None = None
    try:
        result_message, last_assistant_text = await asyncio.wait_for(
            _run_session(spec, client, options, events, child_pid_holder.append),
            timeout=spec.timeout,
        )
    except asyncio.TimeoutError:
        timeout_value = spec.timeout_display if spec.timeout_display is not None else spec.timeout
        assert templates.timed_out is not None
        spec.log(_format(templates.timed_out, spec, timeout=timeout_value))
        outcome = _outcome(ok=False, rc=None, stdout="", detail="", failure="timeout", events=events)
    except CLINotFoundError as exc:
        assert templates.not_found is not None
        spec.log(_format(templates.not_found, spec))
        outcome = _outcome(
            ok=False, rc=None, stdout="", detail="", failure="not-found", events=events, exc=exc
        )
    except ProcessError as exc:
        rc = exc.exit_code if isinstance(exc.exit_code, int) else 1
        assert templates.exited is not None
        spec.log(_format(templates.exited, spec, rc=rc, detail=_render_exit_detail(templates, str(exc))))
        outcome = _outcome(
            ok=False, rc=rc, stdout="", detail=str(exc), failure="exit", events=events, exc=exc
        )
    except ClaudeSDKError as exc:
        # `T-c` parity: this leg (JSON decode / connection / protocol
        # errors that are not a bare OSError) is only caught on the
        # surfaces whose transport catches OSError too -- the analyst's
        # missing `os_error` template (`R-1`) means this must re-raise
        # there exactly as a bare OSError does, rather than crash on the
        # template assertion below.
        if not _CATCHES_OS_ERROR.get(surface, True):
            raise
        assert templates.os_error is not None
        spec.log(_format(templates.os_error, spec, exc=exc))
        outcome = _outcome(
            ok=False, rc=None, stdout="", detail=str(exc), failure="os-error", events=events, exc=exc
        )
    except OSError as exc:
        if not _CATCHES_OS_ERROR.get(surface, True):
            raise  # `T-c`/`OU5`/`R-1` -- the analyst's bare OSError escapes uncaught
        assert templates.os_error is not None
        spec.log(_format(templates.os_error, spec, exc=exc))
        outcome = _outcome(
            ok=False, rc=None, stdout="", detail=str(exc), failure="os-error", events=events, exc=exc
        )
    except Exception as exc:  # noqa: BLE001 - narrowed below to the SDK's wrapped-ProcessError shape
        # `Map-1`'s "ProcessError (nonzero CLI exit)" row, reached via its
        # ACTUAL shape on the resolved SDK: `Query`'s internal read task
        # catches `ProcessError` itself (query.py's message-reader loop)
        # and re-raises it as a bare `Exception` carrying only the
        # rendered text, so `except ProcessError` above never fires in
        # practice -- verified empirically while building this unit (not
        # in any probe memo). `MAJOR-3`: the catch is narrowed to THAT
        # specific shape -- a message containing "exit code N" is the one
        # thing `ProcessError.__str__` always appends
        # (`f"{message} (exit code: {exit_code})"`), so it is a reliable
        # discriminator between a genuine wrapped CLI exit and a
        # programming error (`AttributeError`/`TypeError`/`KeyError`/...)
        # raised anywhere in `_run_session`, the drain, or the outcome
        # mapping -- those must PROPAGATE, not be rendered to the operator
        # as a fake "claude exited N" line. Applied UNIFORMLY across every
        # surface when it IS the wrapped shape, never re-raised there
        # (Map-1's row carries no analyst exception, unlike the OSError
        # row above it). `rc` is recovered best-effort from the wrapped
        # message text; `O-rc`'s synthetic `1` is the fallback when it
        # cannot be.
        match = re.search(r"exit code (-?\d+)", str(exc))
        if match is None:
            raise
        rc = int(match.group(1))
        assert templates.exited is not None
        spec.log(
            _format(templates.exited, spec, rc=rc, detail=_render_exit_detail(templates, str(exc)))
        )
        outcome = _outcome(
            ok=False, rc=rc, stdout="", detail=str(exc), failure="exit", events=events, exc=exc
        )
    else:
        if result_message is None:
            detail = "sdk session ended without a result"
            assert templates.exited is not None
            spec.log(
                _format(templates.exited, spec, rc=1, detail=_render_exit_detail(templates, detail))
            )
            outcome = _outcome(
                ok=False, rc=1, stdout="", detail=detail, failure="exit", events=events
            )
        else:
            outcome = _map_result_message(
                spec, result_message, last_assistant_text, templates, events
            )
    finally:
        child_pid = child_pid_holder[-1]
        await lifecycle.run_kill_ladder(client, child_pid, spec.log)
        lifecycle.clear_sidecar(surface)
        write_event_log(
            surface,
            run_id,
            meta={
                "surface": surface,
                "run_id": run_id,
                "session_id": outcome.session_id if outcome is not None else None,
                "cost_usd": outcome.cost_usd if outcome is not None else None,
                "turns": outcome.turns if outcome is not None else None,
                "failure": outcome.failure if outcome is not None else "exit",
            },
            events=events,
        )

    assert outcome is not None
    return outcome


# --------------------------------------------------------------- SdkBackend


class SdkBackend:
    """Implements `U-seam`'s two-operation `Backend` protocol via a
    `ClaudeSDKClient` session instead of a `claude` subprocess. Both
    operations delegate to `self._run` -- neither may call
    `write_session(`/`text_session(` (`L-d`/`PL5`: no module under
    `src/self_learn/` other than `worker.py`/`miner.py`/`analyst.py` may
    CALL either seam function; these are DEFINITIONS, not counted)."""

    def write_session(self, spec: SessionSpec) -> Outcome:
        return self._run(spec)

    def text_session(self, spec: SessionSpec) -> Outcome:
        return self._run(spec)

    def _run(self, spec: SessionSpec) -> Outcome:
        return run_sync(lambda: _drive(spec))
