"""U-engine Phase 1 -- the UI half of PIN (captured in 1A against the
UNEDITED engine), plus the 1B criteria Sec 9.2 assigns to this file:
AGR1/AGR2/AGR3, LAD3/LAD4, BND2, and MS1.

Spec: `docs/specs/self-learn/drafts/u-engine-shared-sdk-core-spec.md`
Sec 6 (Phase 1 criteria).

Every message pin below hardcodes its expected string INDEPENDENTLY of
`sdk.UI_SHUTDOWN_MESSAGES` -- comparing against that table itself would
be the exact tautology `PIN2` forbids.

Driven the same way `test_engine_sdk.py` already drives the ladder: a
stub client with `engine._client`/`engine._session_active` set directly
(no real `start()`), never a real model, never the network.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from claude_agent_sdk import ClaudeAgentOptions, PermissionResultAllow, PermissionResultDeny

from self_learn.invocation.contract import Containment, LogTemplates, SessionSpec
from self_learn.invocation_sdk import backend as backend_mod
from self_learn.invocation_sdk.charter import build_can_use_tool as cli_build_can_use_tool
from self_learn.sdksession import children as sdk_children
from self_learn.sdksession import events as sdk_events
from self_learn.sdksession import policy as sdk_policy
from self_learn.sdksession import result as sdk_result
from self_learn.sdksession import session as sdk_session_lib
from self_learn.sdksession import teardown as sdk_teardown
from self_learn.sdksession.fake import FakeSdkClient

from self_learn_ui.engine import PaneContext
from self_learn_ui.engine import sdk as sdk_mod
from self_learn_ui.engine.charter import build_can_use_tool as ui_build_can_use_tool
from self_learn_ui.engine.sdk import SdkPaneEngine, UI_SHUTDOWN_MESSAGES

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"


@pytest.fixture(autouse=True)
def _skip_sdk_version_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")


def _wedged_engine(client: object, *, grace: float = 0.05, kill: float = 0.12) -> SdkPaneEngine:
    engine = SdkPaneEngine(
        model="claude-sonnet-5",
        max_turns=5,
        max_budget_usd=1.0,
        cli_path=FAKE_CLI,
        canon_read_roots_fn=lambda: [],
        interrupt_grace_secs=grace,
        interrupt_kill_secs=kill,
    )
    engine._client = client  # type: ignore[assignment]  # noqa: SLF001 - wedged transport stand-in
    engine._session_active = True  # noqa: SLF001
    return engine


def _capture_uilog(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    logs: list[str] = []
    monkeypatch.setattr(sdk_mod.uilog, "log", logs.append)
    return logs


# ===================================================================== #
# PIN -- the unit's real product (UI half). Every message is hardcoded
# here, independently of `sdk.UI_SHUTDOWN_MESSAGES` (`PIN2`'s
# anti-tautology rule). Sec 2.8's UI rows: 5 close-ladder + 3
# interrupt-ladder + 1 drain + 1 client-owned SDK-log-forwarding line.
# ===================================================================== #

_UI_DISCONNECT_TIMEOUT = (
    "pane engine close: disconnect() still running at the kill "
    "bound — caller released; SDK subprocess escalation "
    "continues in the background"
)
_UI_DISCONNECT_RAISED = "pane engine close: disconnect() raised: boom"
_UI_ABANDONED_CANCELLED = "pane engine close: abandoned disconnect() was cancelled"
_UI_ABANDONED_FINISHED = "pane engine close: abandoned disconnect() finished with: boom2"
_UI_ABANDONED_COMPLETED = "pane engine close: abandoned disconnect() completed"
_UI_INTERRUPT_UNRESPONSIVE = (
    "pane engine interrupt: SDK interrupt() unresponsive within "
    "grace — escalating to close"
)
_UI_INTERRUPT_FAILED = "pane engine interrupt: SDK interrupt() failed, escalating: boom"
_UI_INTERRUPT_EXHAUSTED = "pane engine interrupt: grace + kill window exhausted — force-closing"
_UI_DRAIN_ABNORMAL = "pane engine: session ended abnormally (RuntimeError): boom"


async def test_pin1_pin2_ui_close_ladder_timeout_and_raised(monkeypatch):
    """`PIN1`/`PIN2` -- the two ladder-body lines (disconnect() timing
    out at the kill bound, disconnect() raising outright), driven
    through the REAL `close()` -> `sdk_teardown.run_kill_ladder` path."""
    logs = _capture_uilog(monkeypatch)
    timeout_engine = _wedged_engine(FakeSdkClient(hang_disconnect_secs=3600), grace=0.02, kill=0.05)
    await asyncio.wait_for(timeout_engine.close(), timeout=2.0)
    assert logs == [_UI_DISCONNECT_TIMEOUT], logs

    logs.clear()
    raised_engine = _wedged_engine(FakeSdkClient(disconnect_raises=RuntimeError("boom")))
    await asyncio.wait_for(raised_engine.close(), timeout=2.0)
    assert logs == [_UI_DISCONNECT_RAISED], logs


async def test_pin1_pin2_ui_close_abandoned_disconnect_all_three_outcomes(monkeypatch):
    """`PIN1`/`PIN2` -- the three abandoned-disconnect outcome lines
    (completed / finished-with-exception / cancelled), driven through
    the REAL `close()` path. All three legs share this ONE test
    function's event loop (pytest-asyncio's `asyncio_mode = auto` gives
    the whole `async def` one loop) -- mirrors the CLI-side sibling
    test's documented fix: splitting a leg's drive and its
    wait-for-completion across separate `asyncio.run()` calls corrupts
    the observation, because `asyncio.run()` forcibly cancels whatever
    is still pending when it returns."""
    logs = _capture_uilog(monkeypatch)

    async def _leg(client: object, *, cancel: bool) -> list[str]:
        logs.clear()
        engine = _wedged_engine(client, grace=0.02, kill=0.02)
        before = set(sdk_teardown.ABANDONED_DISCONNECTS)
        await engine.close()
        added = sdk_teardown.ABANDONED_DISCONNECTS - before
        assert len(added) == 1, added
        task = next(iter(added))
        if cancel:
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except BaseException:  # noqa: BLE001 - outcome retrieved via the done-callback below
            pass
        await asyncio.sleep(0)  # done-callbacks are scheduled via call_soon
        return list(logs)

    # completed cleanly, after the kill bound.
    logs_c = await _leg(FakeSdkClient(hang_disconnect_secs=0.08), cancel=False)
    assert logs_c == [_UI_DISCONNECT_TIMEOUT, _UI_ABANDONED_COMPLETED], logs_c

    # raised, after the kill bound.
    class _RaisesLateClient(FakeSdkClient):
        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            await asyncio.sleep(0.08)
            raise RuntimeError("boom2")

    logs_f = await _leg(_RaisesLateClient(), cancel=False)
    assert logs_f == [_UI_DISCONNECT_TIMEOUT, _UI_ABANDONED_FINISHED], logs_f

    # cancelled explicitly.
    logs_x = await _leg(FakeSdkClient(hang_disconnect_secs=3600), cancel=True)
    assert logs_x == [_UI_DISCONNECT_TIMEOUT, _UI_ABANDONED_CANCELLED], logs_x


async def test_pin1_pin2_ui_interrupt_unresponsive_within_grace(monkeypatch):
    logs = _capture_uilog(monkeypatch)
    engine = _wedged_engine(FakeSdkClient(hang_interrupt_secs=3600))
    await asyncio.wait_for(engine.interrupt(), timeout=2.0)
    assert logs == [_UI_INTERRUPT_UNRESPONSIVE], logs


async def test_pin1_pin2_ui_interrupt_sdk_interrupt_raises(monkeypatch):
    logs = _capture_uilog(monkeypatch)
    engine = _wedged_engine(FakeSdkClient(interrupt_raises=RuntimeError("boom")))
    await asyncio.wait_for(engine.interrupt(), timeout=2.0)
    assert logs == [_UI_INTERRUPT_FAILED], logs


async def test_pin1_pin2_ui_interrupt_grace_and_kill_exhausted(monkeypatch):
    """`interrupt()` itself neither hangs nor raises, but
    `_session_active` never flips false (nothing drives `_drain()` in
    this wedged setup) -- both `_wait_until_inactive()` windows time
    out, exhausting the ladder."""
    logs = _capture_uilog(monkeypatch)
    engine = _wedged_engine(FakeSdkClient())
    await asyncio.wait_for(engine.interrupt(), timeout=2.0)
    assert logs == [_UI_INTERRUPT_EXHAUSTED], logs


async def test_pin1_pin2_ui_drain_session_ended_abnormally(monkeypatch):
    logs = _capture_uilog(monkeypatch)

    class _RaisingClient:
        async def receive_response(self):
            raise RuntimeError("boom")
            yield  # pragma: no cover - unreachable; makes this an async generator

    engine = SdkPaneEngine(
        model="claude-sonnet-5", max_turns=5, max_budget_usd=1.0,
        cli_path=FAKE_CLI, canon_read_roots_fn=lambda: [],
    )
    engine._client = _RaisingClient()  # type: ignore[assignment]  # noqa: SLF001
    events = [event async for event in engine._drain()]
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].error == "boom"
    assert logs == [_UI_DRAIN_ABNORMAL], logs


def test_pin1_ui_sdk_log_forwarding_client_owned(monkeypatch):
    """The 24th message (Sec 2.8 CORRECTED-r3): client-owned, not
    library-owned -- `_ForwardSdkLogToUiLog` stays UI-side (G-4/C-4).
    Still pinned by `PIN1`. Driven through the REAL SDK logger, not a
    direct call to the handler."""
    import logging

    logs = _capture_uilog(monkeypatch)
    SdkPaneEngine(
        model="claude-sonnet-5", max_turns=5, max_budget_usd=1.0,
        cli_path=FAKE_CLI, canon_read_roots_fn=lambda: [],
    )  # __init__ installs the forwarding handler (idempotent).
    logging.getLogger("claude_agent_sdk").debug("malformed line skipped")
    assert logs == ["sdk[claude_agent_sdk]: malformed line skipped"], logs


def test_pin4_positive_control_the_cli_prefix_would_fail_this_pin(monkeypatch):
    """`PIN4` -- substituting the OTHER engine's message table must make
    the pin suite FAIL, observed. The CLI's table (the "run: sdk
    backend: ..." prefix, Sec 2.8) wired into the UI's ladder makes
    `test_pin1_pin2_ui_close_ladder_timeout_and_raised`'s own assertion
    fail."""
    from self_learn.invocation_sdk import lifecycle as cli_lifecycle_mod

    monkeypatch.setattr(sdk_mod, "UI_SHUTDOWN_MESSAGES", cli_lifecycle_mod.CLI_SHUTDOWN_MESSAGES)
    logs = _capture_uilog(monkeypatch)
    engine = _wedged_engine(FakeSdkClient(disconnect_raises=RuntimeError("boom")))
    asyncio.run(engine.close())
    assert logs != [_UI_DISCONNECT_RAISED], "PIN4 did not detect the swapped table"
    with pytest.raises(AssertionError):
        assert logs == [_UI_DISCONNECT_RAISED], logs


# ===================================================================== #
# AGR -- cross-surface agreement and disagreement.
# ===================================================================== #

_AGR1_TABLE = [
    lambda t: {"file_path": t},
    lambda t: {"path": t},
    lambda t: {"notebook_path": t},
    lambda t: {"file_path": t, "path": "/ignored/one", "notebook_path": "/ignored/two"},
    lambda t: {"file_path": "", "path": t},
    lambda t: {"file_path": 12345, "path": t},
]


def _target_from_ui_deny(message: str) -> str:
    m = re.search(r"— (.+) is outside all three\.", message)
    assert m, message
    return m.group(1)


def _target_from_cli_deny(message: str) -> str:
    prefix = "write scope does not include "
    idx = message.index(prefix)
    return message[idx + len(prefix) :]


def _closed_containment(**overrides: object) -> Containment:
    base = dict(
        allowed_tools=None, disallowed_tools=None,
        write_globs=(), write_exact=(), strict_mcp=True, default_mode="deny",
    )
    base.update(overrides)
    return Containment(**base)  # type: ignore[arg-type]


def test_agr1_target_path_extraction_agrees_across_both_charters(tmp_path):
    """`AGR1` -- one table of `tool_input` dicts (each key alone, all
    three present for precedence, an empty-string higher-precedence
    value, a non-string higher-precedence value) drives BOTH surfaces'
    real `build_can_use_tool`-produced callbacks; the resolved target
    paths -- read out of each `PermissionResultDeny.message` -- are
    byte-identical. **NORMATIVE:** neither leg calls the shared
    `extract_target_path` directly -- each callback resolves the target
    on its own, through its own real decision path (UI: a denied
    `Read`; CLI: a denied `Write`)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    target_file = outside / "secret.md"
    target_file.write_text("x")
    target = str(target_file)

    home = tmp_path / "home"
    home.mkdir()
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    ui_cb = ui_build_can_use_tool(
        self_learn_home=home, bucket_root=bucket, record_id="abc123",
        canon_read_roots_fn=lambda: [],
    )
    cli_cb = cli_build_can_use_tool(_closed_containment())

    for build_input in _AGR1_TABLE:
        tool_input = build_input(target)
        ui_result = asyncio.run(ui_cb("Read", tool_input, None))
        cli_result = asyncio.run(cli_cb("Write", tool_input, None))
        assert ui_result.behavior == "deny", tool_input
        assert cli_result.behavior == "deny", tool_input
        ui_target = _target_from_ui_deny(ui_result.message)
        cli_target = _target_from_cli_deny(cli_result.message)
        expected = str(Path(target).resolve())
        assert ui_target == cli_target == expected, (
            tool_input, ui_result.message, cli_result.message,
        )

    # The "no target at all" leg: both sides independently decide there
    # is nothing to resolve. No target to compare -- both still deny,
    # neither crashes.
    ui_none = asyncio.run(ui_cb("Read", {}, None))
    cli_none = asyncio.run(cli_cb("Write", {}, None))
    assert ui_none.behavior == "deny"
    assert cli_none.behavior == "deny"


def test_agr2_disagreement_survives_read_and_write(tmp_path):
    """`AGR2` -- the only detector for the over-reach of merging the two
    charters (Sec 3.1, Sec 4.8 R-e). (i) a `Read` under the resolved
    ledger home: ALLOW on the UI charter, DENY on the CLI charter (the
    CLI never scopes reads by path at all). (ii) a `Write` matching a
    CLI `write_glob`: ALLOW on the CLI charter, DENY on the UI charter
    (it names neither the record file nor a proposal file). Both deny
    messages byte-pinned, including their distinct prefixes."""
    home = tmp_path / "home"
    home.mkdir()
    read_target = home / "notes.md"
    read_target.write_text("x")
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    ui_cb = ui_build_can_use_tool(
        self_learn_home=home, bucket_root=bucket, record_id="abc123",
        canon_read_roots_fn=lambda: [],
    )
    cli_cb_no_glob = cli_build_can_use_tool(_closed_containment())

    ui_read = asyncio.run(ui_cb("Read", {"file_path": str(read_target)}, None))
    cli_read = asyncio.run(cli_cb_no_glob("Read", {"file_path": str(read_target)}, None))
    assert ui_read.behavior == "allow", ui_read
    assert cli_read.behavior == "deny", cli_read
    assert cli_read.message == (
        "self-learn invocation charter: Read is outside the permitted surface — denied by default"
    )

    writable_dir = tmp_path / "writable"
    writable_dir.mkdir()
    write_target = writable_dir / "out.md"
    glob_pattern = str(writable_dir / "**")
    cli_cb_glob = cli_build_can_use_tool(_closed_containment(write_globs=(glob_pattern,)))

    cli_write = asyncio.run(cli_cb_glob("Write", {"file_path": str(write_target)}, None))
    ui_write = asyncio.run(ui_cb("Write", {"file_path": str(write_target)}, None))
    assert cli_write.behavior == "allow", cli_write
    assert ui_write.behavior == "deny", ui_write
    assert ui_write.message == (
        "self-learn pane charter: Write is outside the pane's permitted "
        "surface — it may only edit this record's own pending record and "
        "proposal files. Denied by default."
    )


_AGR3_TABLE = [
    SimpleNamespace(
        is_error=True, errors=["e1", "e2"], result=None, subtype="error_max_turns",
        num_turns=3, session_id="sid-1", total_cost_usd=0.1, permission_denials=None,
    ),
    SimpleNamespace(
        is_error=True, errors=[], result="some result text", subtype="error_max_turns",
        num_turns=1, session_id="sid-2", total_cost_usd=0.2, permission_denials=None,
    ),
    SimpleNamespace(
        is_error=True, errors=[], result=None, subtype="error_during_execution",
        num_turns=0, session_id="sid-3", total_cost_usd=None, permission_denials=None,
    ),
    SimpleNamespace(
        is_error=True, errors=["only one"], result=None, subtype="error_max_turns",
        num_turns=2, session_id="sid-4", total_cost_usd=0.05, permission_denials=None,
    ),
    SimpleNamespace(
        is_error=True, errors=[], result="", subtype="error_max_turns",
        num_turns=5, session_id="sid-5", total_cost_usd=0.0, permission_denials=None,
    ),
]


def test_agr3_error_detail_reduction_agrees_across_both_engines(tmp_path):
    """`AGR3` -- one table of `ResultMessage` shapes (errors non-empty;
    errors empty with result set; both empty with only subtype; errors
    with one element; result an empty string) driven through each
    engine's REAL mapping -- `backend._map_result_message` and
    `SdkPaneEngine._map_result` -- producing byte-identical strings."""
    spec = SessionSpec(
        surface="worker", prompt="p", cwd=tmp_path, timeout=10.0,
        containment=_closed_containment(), log=lambda _m: None,
    )
    templates = LogTemplates(
        exited="exited {rc}: {detail}", timed_out="t", not_found="nf",
        os_error="oe", unavailable="u", detail_cap=None, detail_strip=False,
    )
    engine = SdkPaneEngine(
        model="claude-sonnet-5", max_turns=5, max_budget_usd=1.0,
        cli_path=FAKE_CLI, canon_read_roots_fn=lambda: [],
    )

    for result_message in _AGR3_TABLE:
        cli_outcome = backend_mod._map_result_message(
            spec, result_message, "", templates, sdk_events.EventLog()
        )
        ui_result = engine._map_result(result_message)  # noqa: SLF001
        assert cli_outcome.detail == ui_result.error, (
            result_message, cli_outcome.detail, ui_result.error,
        )


# ===================================================================== #
# LAD -- the ladder.
# ===================================================================== #

def test_lad3_registry_and_constants_are_the_library_objects_by_identity():
    """`LAD3` -- `engine.sdk._ABANDONED_DISCONNECTS` is the SAME object
    as `sdksession.teardown.ABANDONED_DISCONNECTS` (identity, not
    equality -- a copy passes `==` and breaks the pinned tests on the
    next task); `DEFAULT_INTERRUPT_GRACE_SECS`/`DEFAULT_INTERRUPT_KILL_SECS`
    are the library's `ladder` objects, also by identity."""
    from self_learn.sdksession import ladder as sdk_ladder

    assert sdk_mod._ABANDONED_DISCONNECTS is sdk_teardown.ABANDONED_DISCONNECTS  # noqa: SLF001
    assert sdk_mod.DEFAULT_INTERRUPT_GRACE_SECS is sdk_ladder.INTERRUPT_GRACE_SECS
    assert sdk_mod.DEFAULT_INTERRUPT_KILL_SECS is sdk_ladder.KILL_SECS


def test_lad3_original_constants_test_still_passes_unmodified():
    """`LAD3` -- `test_engine_sdk.py::test_default_ladder_constants_
    match_the_tuned_pin` passes unmodified. Re-run here, inline, as a
    belt-and-braces proof this file's own suite run witnesses it (the
    canonical proof is running that file itself, unedited)."""
    from self_learn_ui.engine.sdk import DEFAULT_INTERRUPT_GRACE_SECS, DEFAULT_INTERRUPT_KILL_SECS

    assert DEFAULT_INTERRUPT_GRACE_SECS == 1.0
    assert DEFAULT_INTERRUPT_KILL_SECS == 2.5


def test_lad4_loop_closing_gates_step_three_both_directions(monkeypatch):
    """`LAD4` -- `R-1`, both directions, driven directly against the
    shared `teardown.run_kill_ladder` (the SAME function `close()`
    delegates to, always with `loop_closing=False` -- this test proves
    the direction that matters on THIS engine, and its opposite, so a
    build that hard-codes either value would fail one leg).
    `os.kill`/`os.killpg`/`os.getpgid` are monkeypatched -- never a real
    signal (mirrors the CLI-side sibling's safety note: an unguarded
    `kill_child` walks a real pid)."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr("os.getpgid", lambda _pid: 1)
    monkeypatch.setattr("os.kill", lambda pid, _sig: calls.append(("kill", pid)))
    monkeypatch.setattr("os.killpg", lambda pid, _sig: calls.append(("killpg", pid)))

    async def _run(loop_closing: bool) -> None:
        client = FakeSdkClient()
        await sdk_teardown.run_kill_ladder(
            client, 4242, lambda _m: None,
            kill_secs=0.2, interrupt_grace_secs=None, loop_closing=loop_closing,
            pid_alive=lambda _pid: True, messages=UI_SHUTDOWN_MESSAGES,
        )

    asyncio.run(_run(True))
    assert calls == [("kill", 4242)], calls  # signalled before the coroutine returns

    calls.clear()
    asyncio.run(_run(False))
    assert calls == [], calls  # NOT signalled -- this engine's own shape


# ===================================================================== #
# BND -- boundaries.
# ===================================================================== #

def test_bnd2_exactly_one_new_module_scope_import_root():
    """`BND2` -- `ui/src/self_learn_ui/engine/` gains EXACTLY ONE new
    module-scope import root (`self_learn.sdksession`); the pre-existing
    LAZY `from self_learn.hosts import ...` inside
    `charter.default_canon_read_roots` is unchanged (it lives inside a
    function body, not at module scope, so this scan -- deliberately
    restricted to `tree.body`, never `ast.walk` -- never sees it; if it
    ever became module-level, `self_learn.hosts` would show up in
    `roots` too and this assertion would catch it)."""
    import ast

    engine_dir = Path(sdk_mod.__file__).resolve().parent
    roots: set[str] = set()
    for path in sorted(engine_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("self_learn."):
                parts = node.module.split(".")
                roots.add(".".join(parts[:2]))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("self_learn."):
                        roots.add(".".join(alias.name.split(".")[:2]))
    assert roots == {"self_learn.sdksession"}, roots

    charter_src = (engine_dir / "charter.py").read_text(encoding="utf-8")
    assert "from self_learn.hosts import" in charter_src  # still present, still lazy


# ===================================================================== #
# MS1 -- multi-session (a LIBRARY criterion; Sec 9.2 assigns it here).
# ===================================================================== #

async def test_ms1_two_sessions_one_process_one_loop_interleaved(tmp_path):
    """`MS1` -- two sessions, one process, one loop, INTERLEAVED, driven
    directly against the library (the mechanism this engine's
    `close()`/`_drain()` are themselves built from), using `surface=
    "pane"` -- the UI's own conceptual surface name. Both event logs
    exist, are distinct and complete; both kill ladders run
    independently; neither session's `clear_sidecar` touches the
    other's sidecar path -- proving per-session bookkeeping is not
    process-global. `sweep_orphans` is intentionally NOT called here
    (a real pid-scoped kill path -- exercised safely, without any real
    pid, in the LIB4 smoke test below)."""
    cache_dir = tmp_path / "ms1-cache"
    cache_dir.mkdir()

    async def _session(tag: str, hold_secs: float) -> tuple[str, sdk_events.EventLog]:
        run_id = sdk_events.new_run_id()
        client = FakeSdkClient(pid=2000 + hash(tag) % 100, messages=[f"{tag}-msg"])
        pid = sdk_children.child_pid_of(client)
        assert pid is not None
        sdk_children.write_sidecar(cache_dir, "pane", pid, "claude", session_key=run_id)
        session = sdk_session_lib.SdkSession(client)
        await session.connect()
        await session.query(tag)
        events = sdk_events.EventLog()
        async for message in session.drive():
            events.add_tool_use("b1", "Read", {"note": message})
        await asyncio.sleep(hold_secs)  # force interleaving with the other session
        await sdk_teardown.run_kill_ladder(
            client, pid, lambda _m: None,
            kill_secs=1.0, interrupt_grace_secs=0.1, loop_closing=False,
            pid_alive=lambda _p: False, messages=UI_SHUTDOWN_MESSAGES,
        )
        sdk_children.clear_sidecar(cache_dir, "pane", session_key=run_id)
        sdk_events.write_event_log(
            cache_dir, "pane", run_id, log_kind="ms1-events",
            meta={"tag": tag}, events=events,
        )
        return run_id, events

    (run_id_a, events_a), (run_id_b, events_b) = await asyncio.gather(
        _session("A", 0.05), _session("B", 0.01),
    )

    assert run_id_a != run_id_b
    assert events_a.tool_events[0]["input"]["note"] == "A-msg"
    assert events_b.tool_events[0]["input"]["note"] == "B-msg"

    import json

    path_a = sdk_events.event_log_path(cache_dir, "pane", run_id_a, log_kind="ms1-events")
    path_b = sdk_events.event_log_path(cache_dir, "pane", run_id_b, log_kind="ms1-events")
    assert path_a.is_file() and path_b.is_file() and path_a != path_b
    meta_a = json.loads(path_a.read_text().splitlines()[0])
    meta_b = json.loads(path_b.read_text().splitlines()[0])
    assert meta_a["tag"] == "A" and meta_b["tag"] == "B"

    assert not sdk_children.sidecar_path(cache_dir, "pane", run_id_a).exists()
    assert not sdk_children.sidecar_path(cache_dir, "pane", run_id_b).exists()


def test_sdksession_smoke_sweep_prune_probe_wrap_and_protocol_ui_reachable(tmp_path):
    """Direct coverage of the sidecar/event-log-retention/capability-
    probe/`C-9` denial-wrapper mechanisms this engine's OWN production
    code never reaches (those are CLI-only per Sec 2.8's pin census --
    the pane does not do headless-run cache-dir bookkeeping). Renamed
    off "lib4" (gate r1 M-1): the rewritten `LIB4` test in
    `cli/tests/test_u_engine.py` no longer counts a test file as an
    importer, so this test no longer satisfies any part of it -- its
    real, remaining value is proving the library still WORKS when
    driven from the UI's own venv (LIB5-adjacent), not orphan
    coverage. SAFE by construction: the `sweep_orphans` leg below
    exercises only the MALFORMED-sidecar branch (declined on the very
    first check, before `pid_alive` or `/proc/<pid>/cmdline` is ever
    consulted) -- never a real pid, never a real signal."""
    cache_dir = tmp_path / "smoke-cache"
    cache_dir.mkdir()

    path = sdk_children.sidecar_path(cache_dir, "pane", None)
    path.write_text('{"not": "a real record"}', encoding="utf-8")
    sdk_children.sweep_orphans(
        cache_dir, "pane", lambda _m: None,
        pid_alive=lambda _pid: False,
        messages=UI_SHUTDOWN_MESSAGES,
        process_start=0.0,
    )
    assert not path.exists()  # malformed -> declined and cleared

    sdk_events.write_event_log(
        cache_dir, "pane", "run-1", log_kind="smoke-events", meta={}, events=sdk_events.EventLog()
    )
    sdk_events.write_event_log(
        cache_dir, "pane", "run-2", log_kind="smoke-events", meta={}, events=sdk_events.EventLog()
    )
    sdk_events.prune_event_logs(cache_dir, "pane", log_kind="smoke-events", keep=1)
    remaining = list(cache_dir.glob("pane.smoke-events.*.jsonl"))
    assert len(remaining) == 1

    fields = sdk_result.supported_option_fields(ClaudeAgentOptions)
    assert "max_turns" in fields

    denials: list[tuple[str, str]] = []

    async def _deny(tool_name: str, tool_input: dict, context: object) -> PermissionResultDeny:
        del tool_input, context
        return PermissionResultDeny(message="nope")

    wrapped = sdk_policy.wrap_can_use_tool(
        _deny, lambda name, reason: denials.append((name, reason))
    )
    result = asyncio.run(wrapped("Write", {}, None))
    assert result.behavior == "deny"
    assert denials == [("Write", "nope")]

    async def _allow(tool_name: str, tool_input: dict, context: object) -> PermissionResultAllow:
        del tool_name, tool_input, context
        return PermissionResultAllow()

    wrapped_allow = sdk_policy.wrap_can_use_tool(_allow, lambda *_a: denials.append(("unexpected", "")))
    allow_result = asyncio.run(wrapped_allow("Read", {}, None))
    assert allow_result.behavior == "allow"
    assert denials == [("Write", "nope")]  # unchanged -- an ALLOW is never recorded

    pid = sdk_children.child_pid_of(FakeSdkClient(pid=777))
    assert pid == 777

    assert sdk_policy.SessionPolicy is not None  # a Protocol -- referenced, not instantiated


# ===================================================================== #
# POL2 (UI leg) -- gate r1 M-2 fold. The CLI leg (`lifecycle.
# CLI_SHUTDOWN_MESSAGES`, all twelve fields) lives in
# `cli/tests/test_u_engine.py`; this is the UI's own real table
# (`UI_SHUTDOWN_MESSAGES` -- only the five ladder fields, dual-use --
# `orphan_*`/`child_pid_unresolved` are CLI-only and left at their
# defaults here). Same mechanical, AST-based extraction, duplicated
# because the CLI package cannot import `self_learn_ui` (Sec 2.7).
# ===================================================================== #

_POL2_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")


def _pol2_literal_segments(template: str, *, min_len: int = 8) -> list[str]:
    return [seg for seg in _POL2_PLACEHOLDER_RE.split(template) if len(seg) >= min_len]


def _pol2_table_literal_segments(messages) -> list[str]:
    segments: list[str] = []
    for field in (
        "disconnect_timeout", "disconnect_raised", "abandoned_cancelled",
        "abandoned_finished", "abandoned_completed", "child_pid_unresolved",
    ):
        value = getattr(messages, field, "") or ""
        segments.extend(_pol2_literal_segments(value))
    return segments


def test_pol2_ui_library_contains_no_operator_message_prefix_positive_control():
    """`POL2` UI leg -- gate r1 M-2: mechanically-derived target strings
    from the REAL `UI_SHUTDOWN_MESSAGES` table, checked (AST string
    constants, not raw text -- a multi-line concatenated literal like
    `disconnect_timeout`'s never appears contiguous in the SOURCE, only
    in the parsed value) against the library's own source. A planted
    copy is unconditionally detected by the same matching logic."""
    import ast

    segments = _pol2_table_literal_segments(UI_SHUTDOWN_MESSAGES)
    assert segments, "the sweep itself found nothing -- broken"

    sdksession_dir = Path(sdk_teardown.__file__).resolve().parent

    def _string_constants(p: Path) -> list[str]:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                values.append(node.value)
            elif isinstance(node, ast.JoinedStr):
                for piece in node.values:
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                        values.append(piece.value)
        return values

    lib_strings = [v for p in sdksession_dir.glob("*.py") for v in _string_constants(p)]
    hits = [seg for seg in segments if any(seg in value for value in lib_strings)]
    assert hits == [], hits

    planted = [*lib_strings, segments[0]]
    assert any(seg in value for seg in segments for value in planted), (
        "planted literal not detected -- the sweep itself is broken"
    )


# ===================================================================== #
# POL3 (UI leg) -- the CLI leg (exact keys / fresh-dict-per-call /
# spy-counted-once via a real `_run(spec)` call) lives in
# `cli/tests/test_u_engine.py`, per Sec 9.2's table. A spy on
# `SdkPaneEngine._build_options`'s real call path can only run from
# THIS package's own venv -- the CLI cannot import `self_learn_ui` at
# all (Sec 2.7), so the reverse direction does not just fail a check,
# it does not compile. This supplement is the only place this half of
# `POL3` can physically execute.
# ===================================================================== #

def test_pol3_ui_option_floor_called_once_per_real_build_options(monkeypatch, tmp_path):
    calls: list[int] = []
    real_floor = sdk_policy.default_option_floor

    def _spy() -> dict[str, object]:
        calls.append(1)
        return real_floor()

    monkeypatch.setattr(sdk_policy, "default_option_floor", _spy)

    engine = SdkPaneEngine(
        model="claude-sonnet-5", max_turns=5, max_budget_usd=1.0,
        cli_path=FAKE_CLI, canon_read_roots_fn=lambda: [],
    )
    home = tmp_path / "home"
    home.mkdir()
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    ctx = PaneContext(
        record_id="abc123", bucket_root=bucket, self_learn_home=home,
        system_prompt="doctrine", first_message="hi",
    )
    options = engine._build_options(ctx)  # noqa: SLF001
    assert len(calls) == 1, calls
    assert options.allowed_tools == []
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
