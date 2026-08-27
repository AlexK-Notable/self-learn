"""U-engine sdksession — `policy.py` (spec §4.3): policy as an object,
the one Protocol. The library takes policy IN; it never contains any.

`SessionPolicy` is duck-typed by design -- both `invocation_sdk/
policy_impl.py` (CLI) and `self_learn_ui/engine/policy_impl.py` (UI)
implement it structurally, with no import of this module required to
satisfy it (a `Protocol` needs none). `ShutdownMessages` is the
byte-pinnable message table §2.8 turns into client-owned data instead of
literals scattered through shared code -- every field is text or a
formatter callable the CLIENT supplies; nothing in this module hardcodes
operator-visible prose (`POL2`).

`wrap_can_use_tool` is `C-9`'s denial-recording adapter (today's
`backend.options_kwargs` inner closure), ported verbatim and duck-typed
over the SDK's `behavior` discriminator (`"deny"`) rather than
`isinstance(..., PermissionResultDeny)` -- `claude_agent_sdk` is never
imported here (`LIB1`/`LIB3`).

Import-bounded: stdlib only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

__all__ = ["CanUseTool", "ShutdownMessages", "SessionPolicy", "wrap_can_use_tool"]

#: Duck-typed: `(tool_name, tool_input, context) -> PermissionResultAllow |
#: PermissionResultDeny`, without importing either SDK type.
CanUseTool = Callable[[str, dict[str, Any], Any], Awaitable[Any]]


@dataclass(frozen=True)
class ShutdownMessages:
    """One client's operator-visible message table (§2.8's 24-message
    census). Every library-owned mechanism that logs anything takes its
    text from an instance of this, supplied by the caller's own
    `SessionPolicy.messages()` -- never from a literal inside the
    library (`POL2`).

    The five ladder fields are used by every client. The six `orphan_*`
    fields and `child_pid_unresolved` are CLI-only today (the UI engine
    never sweeps orphans or writes a pid sidecar) -- left `None`/`""` by
    a client that never reaches that code path costs nothing, since the
    library only reads a field when it is about to emit that exact
    message.
    """

    #: `"{...} still running at the kill bound ..."` -- no placeholder.
    disconnect_timeout: str
    #: `"{...} disconnect() raised: {exc}"` -- one placeholder, `.format(exc=...)`.
    disconnect_raised: str
    #: `"{...} abandoned disconnect() was cancelled"` -- no placeholder.
    abandoned_cancelled: str
    #: `"{...} abandoned disconnect() finished with: {exc}"` -- one placeholder.
    abandoned_finished: str
    #: `"{...} abandoned disconnect() completed"` -- no placeholder.
    abandoned_completed: str
    #: CLI only -- `"run: sdk backend could not resolve the child pid"`.
    child_pid_unresolved: str = ""
    #: CLI only -- `sweep_orphans`'s six lines, each a `(surface[, pid]) -> str`
    #: formatter supplying the exact f-string the caller used to inline.
    orphan_malformed: "Callable[[str], str] | None" = None
    orphan_no_live_process: "Callable[[str, int], str] | None" = None
    orphan_uncorroborated: "Callable[[str, int], str] | None" = None
    orphan_cmdline_mismatch: "Callable[[str, int], str] | None" = None
    orphan_not_stale: "Callable[[str, int], str] | None" = None
    orphan_killed: "Callable[[str, int], str] | None" = None


class SessionPolicy(Protocol):
    """The one Protocol (§4.3). Both charters stay with their clients;
    this is the seam between them and the library."""

    def can_use_tool(self) -> CanUseTool:
        """Return this session's `can_use_tool` callback (the client's
        own charter decision, unwrapped)."""
        ...

    def option_floor(self) -> dict[str, object]:
        """Return the three `ClaudeAgentOptions` keys measured identical
        across both engines (§2.3), as a FRESH dict every call."""
        ...

    def messages(self) -> ShutdownMessages:
        """Return this client's shutdown/ladder message table."""
        ...

    def env(self) -> dict[str, str]:
        """Return this session's provider environment."""
        ...

    def cache_dir(self) -> Path:
        """Return where this session's sidecars and event logs go."""
        ...


#: The three keys measured identical in §2.3 -- ONE definition, so both
#: `option_floor()` implementations return byte-identical dicts by
#: construction rather than by two hand-kept copies drifting apart.
def default_option_floor() -> dict[str, object]:
    """`POL3` -- a fresh dict every call; mutating the caller's copy
    never touches this function's next return value."""
    return {
        "allowed_tools": [],
        "setting_sources": [],
        "strict_mcp_config": True,
    }


def wrap_can_use_tool(raw_can_use_tool: CanUseTool, add_denial: Callable[[str, str], None]) -> CanUseTool:
    """`C-9` -- wrap a charter's callback so every DENY it returns is
    recorded, before the wrapper returns it to the SDK. Duck-typed on
    the SDK's own discriminator field (`behavior == "deny"`) rather than
    an `isinstance` check, so this module never imports
    `claude_agent_sdk` (`LIB1`)."""

    async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
        result = await raw_can_use_tool(tool_name, tool_input, context)
        if getattr(result, "behavior", None) == "deny":
            add_denial(tool_name, getattr(result, "message", ""))
        return result

    return can_use_tool
