"""U4-seam (2026-10-06): one surface, `miner-session`, runs with its OWN
tools, while every other surface keeps exactly the options it had.

The design is the U4 build spec's §4 (the session miner's launcher
change); the operator-facing account is `17-invocation-runbook.md` §1a.
This file is deliberately NOT named `test_invocation_*.py`, so it sits
outside the armor's naming family (`test_armor.py`), and it adds no
scenario to `fixtures/fake_claude.py`: the fake CLI knows no MCP, but it
records its argv, which is enough to prove the options reach the wire.

No test here makes a model call: every session runs against the fake CLI
(`SELF_LEARN_SDK_CLI_PATH`), and the tool handlers are called in-process.

Every name this unit adds is read through its module at CALL time
(`invocation.McpTool`, `backend_mod.MCP_HANDLER_TIMEOUT_SECS`, ...), never
imported by name at the top, so on a tree without the change each test
fails on its own, for its own reason, rather than the whole file failing
to import.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import threading
import time
from pathlib import Path

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from mcp import types as mcp_types

from self_learn import invocation, provider, settings, worker
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk import charter as charter_mod
from self_learn.invocation_sdk import lifecycle as lifecycle_mod
from self_learn.invocation_sdk.backend import SdkBackend
from self_learn.sdksession import children as sdk_children
from self_learn.sdksession import events as sdk_events

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"

_TOOL_NAMES = ("open_stretch", "find_similar_lessons", "search_subagent")
_SCHEMA = {
    "type": "object",
    "properties": {"q": {"type": "string"}},
    "additionalProperties": False,
}


@pytest.fixture()
def fake_cli(monkeypatch):
    """Every session in this file runs against the fake CLI, never a real
    one; the version check would shell out `<cli> -v`, which the fake does
    not implement."""
    monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    return FAKE_CLI


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


async def _echo(args):
    return invocation.ToolReply("echo " + json.dumps(args, sort_keys=True))


def _tool(name: str, handler=_echo, *, read_only: bool = True):
    return invocation.McpTool(
        name=name,
        description=f"the {name} tool",
        input_schema=_SCHEMA,
        handler=handler,
        read_only=read_only,
    )


def _toolset(*tools):
    return invocation.McpToolset("miner", tools or tuple(_tool(n) for n in _TOOL_NAMES))


def _containment(toolset, *, allowed: str | None = None, disallowed: str | None = "Bash,Task"):
    return invocation.containment_for(
        "miner-session",
        allowed_tools=",".join(toolset.qualified_names) if allowed is None else allowed,
        disallowed_tools=disallowed,
    )


def _spec(home: Path, *, surface: str = "miner-session", containment=None, prompt: str = "ok_text", **extra):
    """`extra` carries the new fields (`mcp_toolset`, `sidecar_key`,
    `skip_orphan_sweep`) only when a test sets them."""
    return invocation.SessionSpec(
        surface=surface,
        prompt=prompt,
        cwd=home,
        timeout=20.0,
        containment=containment,
        log=lambda _msg: None,
        **extra,
    )


def _worker_spec(home: Path):
    return _spec(
        home,
        surface="worker",
        containment=invocation.containment_for(
            "worker",
            allowed_tools="Read,Grep,Glob",
            disallowed_tools="Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch",
            home=str(home),
            stage_dir=home / "stage",
            stage_on=False,
        ),
    )


def _session_spec(home: Path, **extra):
    toolset = _toolset()
    return _spec(home, containment=_containment(toolset), mcp_toolset=toolset, **extra)


def _read_argv(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\0")[:-1]


def _value_after(argv: list[str], flag: str) -> str:
    assert argv.count(flag) == 1, (flag, argv)
    return argv[argv.index(flag) + 1]


def _server_instance(kwargs):
    return kwargs["mcp_servers"]["miner"]["instance"]


def _call_tool(server, name: str, arguments: dict) -> tuple[str, bool]:
    """Call one tool through the built server's own request handler --
    the path the SDK takes for a `tools/call` from Claude Code -- and
    return the reply's text and its error flag."""
    handler = server.request_handlers[mcp_types.CallToolRequest]
    request = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=name, arguments=arguments),
    )
    result = asyncio.run(handler(request)).root
    return "".join(block.text for block in result.content), bool(result.isError)


def _list_tools(server):
    handler = server.request_handlers[mcp_types.ListToolsRequest]
    return asyncio.run(handler(None)).root.tools


# ===================================================================== #
# 1. Shape
# ===================================================================== #


def test_s1_a_toolset_switches_off_the_builtins_and_serves_one_server(tmp_path):
    home = _home(tmp_path)
    spec = _session_spec(home)
    kwargs = backend_mod.options_kwargs(spec)

    assert kwargs["tools"] == []
    assert list(kwargs["mcp_servers"]) == ["miner"]
    assert kwargs["mcp_servers"]["miner"]["type"] == "sdk"
    assert kwargs["mcp_servers"]["miner"]["name"] == "miner"
    # The shared floor is unchanged: nothing is pre-approved, strict MCP,
    # no settings sources.
    assert kwargs["strict_mcp_config"] is True
    assert kwargs["allowed_tools"] == []
    assert kwargs["setting_sources"] == []

    # The server offers the three tools, in order, as defined, each
    # read-only; a tool marked not read-only says so.
    listed = _list_tools(_server_instance(kwargs))
    assert [t.name for t in listed] == list(_TOOL_NAMES)
    assert [t.description for t in listed] == [f"the {n} tool" for n in _TOOL_NAMES]
    assert all(t.inputSchema == _SCHEMA for t in listed)
    assert [t.annotations.readOnlyHint for t in listed] == [True, True, True]
    writer = _toolset(_tool("open_stretch"), _tool("note", read_only=False))
    writer_kwargs = backend_mod.options_kwargs(
        _spec(home, containment=_containment(writer), mcp_toolset=writer)
    )
    assert [t.annotations.readOnlyHint for t in _list_tools(_server_instance(writer_kwargs))] == [
        True,
        False,
    ]

    # Positive control: the same spec without the toolset has no `tools`
    # key and no server -- and differs in nothing else. It runs on
    # `miner-reader`, because `miner-session` refuses to run without its
    # own tools (test_s2c); the two share the MINER selector, so the model
    # and the turn bound are the same.
    plain = backend_mod.options_kwargs(
        dataclasses.replace(spec, surface="miner-reader", mcp_toolset=None)
    )
    assert "tools" not in plain
    assert plain["mcp_servers"] == {}
    ignore = {"tools", "mcp_servers", "can_use_tool"}
    assert {k: v for k, v in plain.items() if k not in ignore} == {
        k: v for k, v in kwargs.items() if k not in ignore
    }


def test_s1b_the_server_is_named_by_the_toolset(tmp_path):
    """The `mcp_servers` key and the server's name come from
    `McpToolset.server`, not from a constant: a server named `lessons`
    is served as `lessons`, and its tools are `mcp__lessons__*`."""
    home = _home(tmp_path)
    toolset = invocation.McpToolset("lessons", tuple(_tool(n) for n in _TOOL_NAMES))
    assert toolset.qualified_names == tuple(f"mcp__lessons__{n}" for n in _TOOL_NAMES)
    kwargs = backend_mod.options_kwargs(
        _spec(home, containment=_containment(toolset), mcp_toolset=toolset)
    )
    assert list(kwargs["mcp_servers"]) == ["lessons"]
    assert kwargs["mcp_servers"]["lessons"]["name"] == "lessons"
    assert kwargs["mcp_servers"]["lessons"]["instance"].name == "lessons"


# ===================================================================== #
# 2. Refusals
# ===================================================================== #


def test_s2_the_containment_must_allow_exactly_the_toolsets_names(tmp_path, monkeypatch):
    home = _home(tmp_path)
    toolset = _toolset()
    names = list(toolset.qualified_names)

    def refusal(allowed: str) -> str:
        spec = _spec(home, containment=_containment(toolset, allowed=allowed), mcp_toolset=toolset)
        with pytest.raises(ValueError) as exc:
            backend_mod.options_kwargs(spec)
        return str(exc.value)

    # One too many: a built-in tool beside the session's own.
    message = refusal(",".join([*names, "Read"]))
    assert "allowed but not its own: ['Read']" in message
    assert "its own but not allowed: []" in message
    # One too few.
    message = refusal(",".join(names[:2]))
    assert "allowed but not its own: []" in message
    assert "its own but not allowed: ['mcp__miner__search_subagent']" in message
    # A name of a different server.
    message = refusal(",".join(["mcp__other__open_stretch", *names[1:]]))
    assert "allowed but not its own: ['mcp__other__open_stretch']" in message
    assert "its own but not allowed: ['mcp__miner__open_stretch']" in message
    # Nothing allowed at all.
    message = refusal("")
    assert "its own but not allowed: " + repr(sorted(names)) in message

    # Positive control: exactly the three names, in any order, is accepted.
    accepted = _spec(
        home, containment=_containment(toolset, allowed=",".join(reversed(names))), mcp_toolset=toolset
    )
    assert backend_mod.options_kwargs(accepted)["tools"] == []

    # An SDK without `tools` cannot switch the built-ins off: refused,
    # never run with every built-in tool beside the session's own.
    real_fields = backend_mod._dataclass_fields
    monkeypatch.setattr(
        backend_mod,
        "_dataclass_fields",
        lambda cls: [f for f in real_fields(cls) if f.name != "tools"],
    )
    with pytest.raises(ValueError) as exc:
        backend_mod.options_kwargs(accepted)
    assert "has no tools" in str(exc.value)

    # ... and the same for an SDK without `mcp_servers`.
    monkeypatch.setattr(
        backend_mod,
        "_dataclass_fields",
        lambda cls: [f for f in real_fields(cls) if f.name != "mcp_servers"],
    )
    with pytest.raises(ValueError) as exc:
        backend_mod.options_kwargs(accepted)
    assert "has no mcp_servers" in str(exc.value)
    assert "tools," not in str(exc.value)  # only the missing option is named


def test_s2c_miner_session_never_runs_without_its_own_tools(tmp_path):
    """Gate R2: a `miner-session` spec with no `mcp_toolset` would get every
    built-in tool, and its containment has no read roots -- so it is
    refused, with a reason that names the missing toolset."""
    home = _home(tmp_path)
    containment = invocation.containment_for(
        "miner-session", allowed_tools="Read,Grep,Glob", disallowed_tools="Bash,Task"
    )
    with pytest.raises(ValueError) as exc:
        backend_mod.options_kwargs(_spec(home, containment=containment))
    assert "miner-session" in str(exc.value)
    assert "mcp_toolset" in str(exc.value)

    # Positive controls: the same surface with its own tools is accepted,
    # and a surface that has built-in tools still runs without a toolset.
    assert backend_mod.options_kwargs(_session_spec(home))["tools"] == []
    reader = backend_mod.options_kwargs(_spec(home, surface="miner-reader", containment=containment))
    assert "tools" not in reader


def test_s2b_toolset_and_sidecar_key_are_checked_at_construction(tmp_path):
    with pytest.raises(ValueError, match="duplicate tool name 'open_stretch'"):
        invocation.McpToolset("miner", (_tool("open_stretch"), _tool("open_stretch")))
    for bad in ("Miner", "1miner", "mi-ner", "m" * 33, ""):
        with pytest.raises(ValueError, match="bad server name"):
            invocation.McpToolset(bad, (_tool("open_stretch"),))
        with pytest.raises(ValueError, match="bad tool name"):
            invocation.McpToolset("miner", (_tool(bad),))
    # A trailing newline is refused too (gate N1: `$` alone accepts one).
    with pytest.raises(ValueError, match="bad server name"):
        invocation.McpToolset("miner\n", (_tool("open_stretch"),))
    with pytest.raises(ValueError, match="bad tool name"):
        invocation.McpToolset("miner", (_tool("open_stretch\n"),))
    for bad_key in ("", "a/b", "../x", "k" * 65, "a.b", "k1\n", "a" * 64 + "\n"):
        with pytest.raises(ValueError, match="bad sidecar_key"):
            _spec(tmp_path, containment=invocation.DEGRADED_WORKER_CONTAINMENT, sidecar_key=bad_key)
    # No tools at all (gate N4): the SDK would serve no tool list.
    with pytest.raises(ValueError, match="no tools"):
        invocation.McpToolset("miner", ())
    # A schema the SDK would misread (gate N3): it needs a string `type`
    # and a `properties` mapping.
    for bad_schema in (
        {"type": "object"},
        {"properties": {}},
        {"type": 1, "properties": {}},
        {"type": "object", "properties": []},
    ):
        tool = invocation.McpTool("open_stretch", "d", bad_schema, _echo)
        with pytest.raises(ValueError, match="input_schema"):
            invocation.McpToolset("miner", (tool,))
    no_arguments = invocation.McpTool("open_stretch", "d", {"type": "object", "properties": {}}, _echo)
    assert invocation.McpToolset("miner", (no_arguments,)).qualified_names == ("mcp__miner__open_stretch",)
    # Positive controls: the boundary shapes are accepted.
    assert invocation.McpToolset("m" * 32, (_tool("t" * 32),)).qualified_names == (
        f"mcp__{'m' * 32}__{'t' * 32}",
    )
    spec = _spec(tmp_path, containment=invocation.DEGRADED_WORKER_CONTAINMENT, sidecar_key="Run_1-" + "k" * 58)
    assert spec.sidecar_key is not None and len(spec.sidecar_key) == 64


# ===================================================================== #
# 3. The wire
# ===================================================================== #


def test_s3_the_options_reach_the_wire(tmp_path, fake_cli, monkeypatch):
    home = _home(tmp_path)
    argv_log = tmp_path / "argv"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(argv_log))

    outcome = SdkBackend().text_session(_session_spec(home))
    assert outcome.ok, outcome.detail
    # The session miner's answer is its final message (`_stdout_for`).
    assert outcome.stdout == "RESULT-SENTINEL"
    argv = _read_argv(argv_log)
    assert "--strict-mcp-config" in argv
    assert _value_after(argv, "--tools") == ""
    config = json.loads(_value_after(argv, "--mcp-config"))
    assert config == {"mcpServers": {"miner": {"type": "sdk", "name": "miner"}}}

    # Control: a worker session carries no MCP config and no tools value,
    # under the same floor.
    argv_log.unlink()
    worker_outcome = SdkBackend().write_session(_worker_spec(home))
    assert worker_outcome.ok, worker_outcome.detail
    worker_argv = _read_argv(argv_log)
    assert "--strict-mcp-config" in worker_argv
    assert "--mcp-config" not in worker_argv
    assert "--tools" not in worker_argv


# ===================================================================== #
# 4. Handler wrapping
# ===================================================================== #


def test_s4_the_server_wraps_every_handler(tmp_path, monkeypatch):
    home = _home(tmp_path)
    canary = "CANARY-7f3a-transcript-text"

    async def ok(args):
        return invocation.ToolReply("whole reply for " + args["q"])

    async def bad_argument(args):
        return invocation.ToolReply("after_turn out of range", is_error=True)

    async def raises(args):
        raise RuntimeError(f"failed while reading {canary}")

    async def too_long(args):
        return invocation.ToolReply("x" * 48_001)

    async def at_the_bound(args):
        return invocation.ToolReply("y" * 48_000)

    async def sleeps(args):
        await asyncio.sleep(10)
        return invocation.ToolReply("late")

    async def at_once(args):
        return invocation.ToolReply("at once")

    async def not_a_reply(args):
        return "plain text"

    async def own_timeout(args):
        # e.g. a socket timeout inside the handler, long before the bound
        raise TimeoutError(f"read timed out on {canary}")

    handlers = {
        "ok": ok,
        "bad_argument": bad_argument,
        "raises": raises,
        "too_long": too_long,
        "at_the_bound": at_the_bound,
        "sleeps": sleeps,
        "at_once": at_once,
        "not_a_reply": not_a_reply,
        "own_timeout": own_timeout,
    }
    toolset = _toolset(*(_tool(name, handler) for name, handler in handlers.items()))
    kwargs = backend_mod.options_kwargs(
        _spec(home, containment=_containment(toolset), mcp_toolset=toolset)
    )
    server = _server_instance(kwargs)

    # A normal reply passes through, arguments and all.
    assert _call_tool(server, "ok", {"q": "T3"}) == ("whole reply for T3", False)
    # The handler's own error reply passes through as an error.
    assert _call_tool(server, "bad_argument", {}) == ("after_turn out of range", True)

    # A raising handler: the type name, never the message.
    text, is_error = _call_tool(server, "raises", {"q": "x"})
    assert is_error is True
    assert "RuntimeError" in text  # positive control: the reply names the failure
    assert canary not in text
    assert text == "tool failed: RuntimeError"

    # A reply over the bound is an error naming the bound, never cut.
    text, is_error = _call_tool(server, "too_long", {})
    assert is_error is True
    assert "48000" in text
    assert len(text) < 200
    # Control: a reply exactly at the bound passes through whole.
    text, is_error = _call_tool(server, "at_the_bound", {})
    assert (len(text), is_error) == (48_000, False)

    # A handler that outlives the bound times out (read at call time).
    monkeypatch.setattr(backend_mod, "MCP_HANDLER_TIMEOUT_SECS", 0.1)
    started = time.monotonic()
    text, is_error = _call_tool(server, "sleeps", {})
    assert time.monotonic() - started < 5
    assert is_error is True
    assert "timed out" in text
    # Control: one that answers at once is not timed out.
    assert _call_tool(server, "at_once", {}) == ("at once", False)

    # A handler that answers with something other than a ToolReply fails
    # closed, by type name.
    assert _call_tool(server, "not_a_reply", {}) == ("tool failed: TypeError", True)

    # A handler's OWN TimeoutError is a failure of the handler, not the
    # seam's bound running out (gate N2) -- reported by type name, message
    # withheld. (The bound is still 0.1 s here; this one raises at once.)
    assert _call_tool(server, "own_timeout", {}) == ("tool failed: TimeoutError", True)


def test_s4b_a_cancelled_session_cancels_the_tool_call(tmp_path):
    """The wrapper turns every handler FAILURE into a reply, but never a
    cancellation: when the session is cancelled (its own timeout, a kill)
    while a tool runs, the CancelledError must reach the caller rather
    than come back as a `tool failed: CancelledError` reply (gate M8)."""
    home = _home(tmp_path)

    async def waits(args):
        await asyncio.sleep(30)
        return invocation.ToolReply("never")

    toolset = _toolset(_tool("waits", waits))
    server = _server_instance(
        backend_mod.options_kwargs(_spec(home, containment=_containment(toolset), mcp_toolset=toolset))
    )
    request = mcp_types.CallToolRequest(
        method="tools/call", params=mcp_types.CallToolRequestParams(name="waits", arguments={})
    )

    async def cancel_while_running():
        task = asyncio.ensure_future(server.request_handlers[mcp_types.CallToolRequest](request))
        await asyncio.sleep(0.05)
        assert not task.done()  # positive control: the call really was in flight
        task.cancel()
        try:
            result = await task
        except asyncio.CancelledError:
            return "cancelled"
        return result

    started = time.monotonic()
    assert asyncio.run(cancel_while_running()) == "cancelled"
    assert time.monotonic() - started < 5


# ===================================================================== #
# 5. Sidecars
# ===================================================================== #


def _spy_sidecar_writes(monkeypatch, on_write=None):
    """Spies on the LIBRARY write (`sdksession.children.write_sidecar`),
    which `lifecycle.write_sidecar` reaches through a module attribute at
    call time. Records each written file's name and whether it existed
    right after the write."""
    seen: list[tuple[str, bool]] = []
    real_write = sdk_children.write_sidecar

    def spy(cache_dir, surface, pid, cli, *, session_key=None):
        real_write(cache_dir, surface, pid, cli, session_key=session_key)
        path = sdk_children.sidecar_path(cache_dir, surface, session_key)
        seen.append((path.name, path.is_file()))
        if on_write is not None:
            on_write(cache_dir, surface, session_key)

    monkeypatch.setattr(sdk_children, "write_sidecar", spy)
    return seen


def test_s5_a_keyed_session_keeps_its_own_sidecar(tmp_path, fake_cli, monkeypatch):
    home = _home(tmp_path)
    seen = _spy_sidecar_writes(monkeypatch)
    cache = worker.cache_dir()

    outcome = SdkBackend().text_session(_session_spec(home, sidecar_key="k1"))
    assert outcome.ok, outcome.detail
    assert seen == [("miner-session.sdk-child.k1.pid", True)]
    assert not (cache / "miner-session.sdk-child.k1.pid").exists()

    # Control: without a key, the one unkeyed sidecar, as before.
    seen.clear()
    outcome = SdkBackend().text_session(_session_spec(home))
    assert outcome.ok, outcome.detail
    assert seen == [("miner-session.sdk-child.pid", True)]
    assert not (cache / "miner-session.sdk-child.pid").exists()
    assert sorted(p.name for p in cache.glob("miner-session.sdk-child*")) == []


def test_s5b_two_keyed_sessions_at_once_keep_two_sidecars(tmp_path, fake_cli, monkeypatch):
    """Both sessions skip the sweep, as the session miner's fan-out does:
    a sweep judges every sidecar of the surface and would clear a live
    sibling's (the fake CLI's process name is the Python interpreter, not
    `claude`, so a sweep reads a sibling's sidecar as a mismatch)."""
    home = _home(tmp_path)
    written = threading.Barrier(2, timeout=60)
    listed = threading.Barrier(2, timeout=60)
    during: dict[str, list[str]] = {}

    def hold_until_both_wrote(cache_dir, surface, session_key):
        written.wait()
        during[session_key] = sorted(p.name for p in cache_dir.glob(f"{surface}.sdk-child*.pid"))
        listed.wait()

    seen = _spy_sidecar_writes(monkeypatch, hold_until_both_wrote)
    results: dict[str, object] = {}

    def run(key: str) -> None:
        try:
            results[key] = SdkBackend().text_session(
                _session_spec(home, sidecar_key=key, skip_orphan_sweep=True)
            )
        except BaseException as exc:  # noqa: BLE001 - reported by the assertions below
            results[key] = exc

    threads = [threading.Thread(target=run, args=(key,)) for key in ("k1", "k2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads)

    for key in ("k1", "k2"):
        outcome = results[key]
        assert getattr(outcome, "ok", False) is True, (key, outcome)
    both = ["miner-session.sdk-child.k1.pid", "miner-session.sdk-child.k2.pid"]
    assert during == {"k1": both, "k2": both}
    assert sorted(seen) == [(name, True) for name in both]
    assert list(worker.cache_dir().glob("miner-session.sdk-child*")) == []


# ===================================================================== #
# 6. The sweep switch
# ===================================================================== #


def test_s6_skip_orphan_sweep_skips_the_sweep(tmp_path, fake_cli, monkeypatch):
    home = _home(tmp_path)
    swept: list[str] = []
    monkeypatch.setattr(lifecycle_mod, "sweep_orphans", lambda surface, log: swept.append(surface))

    # Positive control: a default spec sweeps once, before it starts.
    outcome = SdkBackend().text_session(_session_spec(home))
    assert outcome.ok, outcome.detail
    assert swept == ["miner-session"]

    swept.clear()
    outcome = SdkBackend().text_session(_session_spec(home, skip_orphan_sweep=True))
    assert outcome.ok, outcome.detail
    assert swept == []


# ===================================================================== #
# 7. The prune race
# ===================================================================== #


def test_s7_prune_tolerates_a_file_a_sibling_already_removed(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    base = time.time() - 1_000
    real = []
    for i in range(21):
        path = cache / f"miner-session.tool-events.run{i:02d}.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        os.utime(path, (base + i, base + i))
        real.append(path)
    ghost = cache / "miner-session.tool-events.ghost.jsonl"
    offered: list[Path] = []

    class _DirWithGhost(type(cache)):
        """The glob a sibling's prune raced: it still lists a file that
        is gone by the time it is `stat`-ed."""

        def glob(self, pattern, *args, **kwargs):
            found = list(super().glob(pattern, *args, **kwargs))
            found.insert(len(found) // 2, ghost)
            offered.append(ghost)
            return iter(found)

    sdk_events.prune_event_logs(
        _DirWithGhost(cache), "miner-session", log_kind="tool-events", keep=20
    )

    assert offered == [ghost]  # positive control: the vanished file WAS listed
    assert not ghost.exists()
    # The 20 newest are kept; only the oldest real file is gone.
    assert sorted(p.name for p in cache.iterdir()) == sorted(p.name for p in real[1:])


# ===================================================================== #
# 8. Containment
# ===================================================================== #


class _Ctx:
    pass


def test_s8_the_containment_allows_exactly_the_sessions_own_tools(tmp_path):
    toolset = _toolset()
    allowed = ",".join(toolset.qualified_names)

    kept = invocation.containment_for("miner-session", allowed_tools=allowed, disallowed_tools="Bash,Task")
    assert kept.allowed_tools == allowed
    assert kept.disallowed_tools == "Bash,Task"

    containment = invocation.containment_for("miner-session", allowed_tools=allowed)
    assert containment.allowed_tools == allowed
    assert containment.write_globs == ()
    assert containment.write_exact == ()
    assert containment.strict_mcp is True
    assert containment.default_mode == "default"
    assert containment.read_roots == ()
    assert containment.read_denied == ()

    # The charter built from it (no disallow list here, so every denial
    # below comes from the allow-list and the empty write scope).
    can_use_tool = charter_mod.build_can_use_tool(containment, cwd=tmp_path)

    def decide(tool_name: str, tool_input: dict):
        return asyncio.run(can_use_tool(tool_name, tool_input, _Ctx()))

    for name in toolset.qualified_names:
        assert isinstance(decide(name, {"q": "x"}), PermissionResultAllow), name
    for name, tool_input in (
        ("Read", {"file_path": str(tmp_path / "a.md")}),
        ("Write", {"file_path": str(tmp_path / "a.md"), "content": "x"}),
        ("Bash", {"command": "ls"}),
        ("mcp__other__open_stretch", {"q": "x"}),
    ):
        assert isinstance(decide(name, tool_input), PermissionResultDeny), name


# ===================================================================== #
# 9. Every surface still resolves
# ===================================================================== #


def test_s9_the_new_surface_resolves_like_the_old_miner(tmp_path, monkeypatch):
    for var in (
        "SELF_LEARN_BACKEND",
        "SELF_LEARN_BACKEND_MINER",
        "SELF_LEARN_MINER_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    home = _home(tmp_path)

    assert "miner-session" in invocation.SURFACES
    assert type(invocation.backend_for("miner-session", home=home)) is SdkBackend

    (home / "config.yaml").write_text("models:\n  miner: test-miner-model\n", encoding="utf-8")
    assert provider.model_for("miner-reader", home=home) == "test-miner-model"  # the config is read
    assert provider.model_for("miner-session", home=home) == provider.model_for("miner-reader", home=home)

    # One selector for both miners: the backend lever moves both.
    setting = settings.by_name("invocation.backend_miner-session")
    assert setting.env_var == "SELF_LEARN_BACKEND_MINER"
    assert setting.tier == "C"
    monkeypatch.setenv("SELF_LEARN_BACKEND_MINER", "cli")
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for("miner-session", home=home)
    with pytest.raises(invocation.BackendUnavailable):
        invocation.backend_for("miner-reader", home=home)

    # Its rows in the seam's tables.
    assert invocation.SELECTOR_FOR_SURFACE["miner-session"] == "MINER"
    assert invocation.TRANSPORT["miner-session"] is True
    assert (
        invocation.LOG_TEMPLATES["miner-session"].os_error
        == "run: session miner invocation failed ({exc})"
    )
