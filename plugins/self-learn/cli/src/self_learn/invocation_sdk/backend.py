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
from dataclasses import dataclass, fields as _dataclass_fields, replace as _dataclass_replace
from pathlib import Path
from typing import Any, TypeVar, cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .. import provider, settings, worker
from ..invocation.contract import (
    LOG_TEMPLATES,
    SELECTOR_FOR_SURFACE,
    TRANSPORT,
    LogTemplates,
    Outcome,
    SessionSpec,
)
from ..sdksession import policy as sdk_policy
from ..sdksession import result as sdk_result
from ..sdksession import session as sdk_session_lib
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
    ones no CLI-shaped backend can ever populate.

    `child_pid` (U-kl4) is a SIXTH, added later: `None` unless `_drive`
    actually resolved a live child pid for this run. Lets a caller
    identify the exact child process THIS run spawned -- `test_kl4`'s
    pid-keyed liveness check reads it off the returned outcome instead
    of inferring the child from a host-global name pattern (the defect
    this field exists to close). Deliberately NOT threaded through
    `spec.log()`/any operator-visible line: an earlier version of this
    fix did exactly that and broke `test_lg1`/`test_lg6`/`test_fk2`/
    `test_ou4`/`test_fl2` (all of `test_invocation.py`/`test_worker_
    contract.py`), whose byte-pinned log-shape assertions ("a clean
    session logs nothing", "exactly N lines") did not expect a new
    unconditional line -- measured, then reverted."""

    tool_events: tuple[dict[str, Any], ...] = ()
    denials: tuple[dict[str, Any], ...] = ()
    cost_usd: float | None = None
    turns: int | None = None
    session_id: str | None = None
    child_pid: int | None = None


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
    `hasattr` on an instance. **NOT delegated to the shared library**
    (`sdksession.result.supported_option_fields` exists and is
    behaviourally identical, but `test_op9_...`/`test_ou4_...`
    (armor-pinned `test_invocation_sdk.py`) monkeypatch
    `backend_mod._dataclass_fields` directly -- a name delegation would
    make invisible, since the library calls `dataclasses.fields` from
    ITS OWN module namespace, not this one's local alias)."""
    return {f.name for f in _dataclass_fields(ClaudeAgentOptions)}


#: Selector ("WORKER"/"MINER"/"ANALYST") -> the registry entry naming
#: that surface's max-turns setting (U-settings Phase 1).
_MAX_TURNS_SETTING_NAME = {
    "WORKER": "sdk.max_turns.worker",
    "MINER": "sdk.max_turns.miner",
    "ANALYST": "sdk.max_turns.analyst",
}


def _max_turns_for(selector: str, *, home: Path | str) -> int:
    """U-settings Phase 1: resolves through the registry's per-surface
    `sdk.max_turns.<surface>` entry (env `SELF_LEARN_SDK_MAX_TURNS_
    <selector>` > config.yaml `sdk.max_turns.<surface>` >
    :data:`_DEFAULT_MAX_TURNS`). `selector` outside `_MAX_TURNS_SETTING_
    NAME` (never real input — `SELECTOR_FOR_SURFACE`'s three members are
    the only callers) falls back to the bare default, unregistered."""
    name = _MAX_TURNS_SETTING_NAME.get(selector)
    if name is None:
        return _DEFAULT_MAX_TURNS.get(selector, 120)
    value, _source = settings.resolve_setting(home, settings.by_name(name))
    return value


def _max_budget_usd(*, home: Path | str) -> float | None:
    """U-settings Phase 1: resolves through the registry's `sdk.
    max_budget_usd` entry (env `SELF_LEARN_SDK_MAX_BUDGET_USD` >
    config.yaml `sdk.max_budget_usd` > `None`, meaning unlimited)."""
    value, _source = settings.resolve_setting(home, settings.by_name("sdk.max_budget_usd"))
    return value


class CliSessionPolicy:
    """This engine's `sdksession.policy.SessionPolicy` (spec §4.3),
    structurally -- no import of `SessionPolicy` is needed to satisfy a
    `Protocol`. One instance per `SessionSpec`; every method is cheap
    and safe to call more than once except `option_floor()`, which
    `POL3` requires to be called exactly once per `options_kwargs`
    construction and to hand back a FRESH dict every time (delegated to
    `sdksession.policy.default_option_floor`, which does exactly that)."""

    def __init__(self, spec: SessionSpec) -> None:
        self._spec = spec

    def can_use_tool(self) -> "sdk_policy.CanUseTool":
        return charter.build_can_use_tool(self._spec.containment)

    def option_floor(self) -> dict[str, object]:
        return sdk_policy.default_option_floor()

    def messages(self) -> sdk_policy.ShutdownMessages:
        return lifecycle.CLI_SHUTDOWN_MESSAGES

    def env(self) -> dict[str, str]:
        return provider_env(self._spec)

    def cache_dir(self) -> Path:
        return worker.cache_dir()


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

    policy = CliSessionPolicy(spec)
    # `C-9`/`POL2` -- the containment-callback adapter that records every
    # DENY into this session's EventLog moved to the library verbatim;
    # only the charter decision itself (`policy.can_use_tool()`) stays
    # client-owned.
    can_use_tool = sdk_policy.wrap_can_use_tool(policy.can_use_tool(), events.add_denial)

    selector = SELECTOR_FOR_SURFACE.get(spec.surface, spec.surface)
    supported = _supported_option_fields()

    kwargs: dict[str, object] = {
        "cwd": str(spec.cwd),
        "system_prompt": system_prompt,
        "model": provider.model_for(spec.surface, home=spec.cwd),  # `IN3`/`Int-1`
        "disallowed_tools": disallowed,
        "can_use_tool": can_use_tool,
        "permission_mode": "default",  # `O-2` -- unconditionally
        "settings": None,  # `A-2` -- the charter is the only authority
        "mcp_servers": {},
        "include_partial_messages": False,
        "env": policy.env(),  # `PS-a` -- called exactly once, no merge
        # `O-4`/`IN3` -- unchanged since before `U-bedrock`: this already
        # equals `provider.resolve(home, surface).cli_path` bit-for-bit
        # (`_resolve_str_setting` resolves the same env var the same way,
        # `None` on absence), so `IN3`'s cli_path leg holds by
        # construction and this line does not need a second `resolve()`
        # call to satisfy it.
        "cli_path": os.environ.get("SELF_LEARN_SDK_CLI_PATH") or None,
        # `POL3` -- the three keys measured identical in §2.3
        # (`allowed_tools`, `setting_sources`, `strict_mcp_config`), a
        # FRESH dict every call, from the ONE shared definition both
        # engines splat.
        **policy.option_floor(),
    }

    if "max_turns" in supported:
        kwargs["max_turns"] = _max_turns_for(selector, home=spec.cwd)
    else:
        spec.log("run: sdk backend could not apply max_turns on this claude-agent-sdk version")

    if "max_budget_usd" in supported:
        kwargs["max_budget_usd"] = _max_budget_usd(home=spec.cwd)
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
        # §2.2a's skeleton-identical (1.000) pair -- the ONE mechanism
        # this unit found written twice, now moved verbatim.
        detail = sdk_result.reduce_result_error(result_message)
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
    # `session.py` -- the transport loop, not the vocabulary: `SdkSession`
    # does nothing except call the same `connect`/`query`/
    # `receive_response` methods this function already called directly,
    # so wrapping `client` in it changes no observable behaviour. Child-pid
    # resolution and the sidecar write stay routed through `lifecycle.*`
    # (module-attribute calls a test can monkeypatch), unchanged.
    session = sdk_session_lib.SdkSession(client)
    await session.connect()
    child_pid = lifecycle.child_pid_of(client)
    set_child_pid(child_pid)
    if child_pid is None:
        # gate r1 N-2: routed through the table (byte-identical text)
        # instead of a bare literal -- `CLI_SHUTDOWN_MESSAGES.
        # child_pid_unresolved` was written but read by nothing, a
        # second unwatched copy of one operator string.
        spec.log(lifecycle.CLI_SHUTDOWN_MESSAGES.child_pid_unresolved)
    else:
        lifecycle.write_sidecar(spec.surface, child_pid, str(options.cli_path or ""))

    await session.query(spec.prompt)

    final: ResultMessage | None = None
    last_assistant_text = ""
    async for message in session.drive():
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
        # `E-5`/`F-3`/`MS4` -- retention now runs at session END, not
        # START: a STARTING session must never unlink a running
        # session's in-flight log. The CLI's own call site never has a
        # second in-flight run in this process (`run_sync` blocks), so
        # this is a pure timing move, not a behaviour change to what
        # ends up retained.
        prune_event_logs(surface)

    assert outcome is not None
    # U-kl4: attach the resolved child pid (if any) to the outcome the
    # caller sees -- `child_pid` is a plain local, set by `finally`
    # above, still in scope here (Python has no block scoping); every
    # early-return branch above this point (`CharterPatternUnsupported`/
    # `ProviderRefused`) exits BEFORE a client/child ever exists, so its
    # `_outcome(...)` call correctly leaves `child_pid` at the
    # dataclass's own `None` default instead of reaching this line.
    return _dataclass_replace(outcome, child_pid=child_pid)


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
