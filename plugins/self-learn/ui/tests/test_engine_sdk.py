"""``SdkPaneEngine`` tests, driven entirely through the PATH/``cli_path``
-shimmed fake ``claude`` in ``tests/fixtures/fake_claude.py`` (10 §0 rule
7; 10 §3 task U5, bullet 6's scenario list, verbatim): happy path, error
result, mid-stream kill, malformed line -> skip+log, unknown event type
-> skip, interrupt() no-op on ended session. No network, no real model,
anywhere in this file.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from self_learn_ui.engine import BlockStart, FileChanged, PaneContext, Result, TextDelta, ToolUse
from self_learn_ui.engine.sdk import SdkPaneEngine

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude.py"


@pytest.fixture(autouse=True)
def _skip_sdk_version_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # The version check shells out to `<cli_path> -v`; this fake doesn't
    # implement that flag, and it's irrelevant to what these tests cover.
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")


def _engine(*, canon_roots: list[Path] | None = None) -> SdkPaneEngine:
    return SdkPaneEngine(
        model="claude-sonnet-5",
        max_turns=5,
        max_budget_usd=1.0,
        cli_path=FAKE_CLI,
        canon_read_roots_fn=lambda: canon_roots or [],
    )


def _ctx(tmp_path: Path, scenario: str) -> PaneContext:
    bucket = tmp_path / "bucket"
    bucket.mkdir(exist_ok=True)
    return PaneContext(
        record_id="abc123",
        bucket_root=bucket,
        self_learn_home=tmp_path / "home",
        system_prompt="doctrine text",
        first_message=scenario,
    )


async def _drain(agen: AsyncIterator, timeout: float = 15.0) -> list:
    events = []
    ait = agen.__aiter__()
    while True:
        try:
            event = await asyncio.wait_for(ait.__anext__(), timeout=timeout)
        except StopAsyncIteration:
            break
        events.append(event)
    return events


async def test_happy_path(tmp_path: Path) -> None:
    engine = _engine()
    try:
        events = await _drain(engine.start(_ctx(tmp_path, "happy_path")))
    finally:
        await engine.close()

    assert events == [
        BlockStart(kind="text"),
        TextDelta(text="Hello "),
        TextDelta(text="world"),
        Result(status="success", cost_usd=0.001, error=None, turns=1),
    ]


async def test_error_result(tmp_path: Path) -> None:
    engine = _engine()
    try:
        events = await _drain(engine.start(_ctx(tmp_path, "error_result")))
    finally:
        await engine.close()

    assert isinstance(events[-1], Result)
    assert events[-1].status == "error_during_execution"
    assert events[-1].error == "boom"


async def test_mid_stream_kill_surfaces_as_an_error_result_never_a_crash(
    tmp_path: Path,
) -> None:
    engine = _engine()
    try:
        events = await _drain(engine.start(_ctx(tmp_path, "mid_stream_kill")))
    finally:
        await engine.close()

    # The partial content that streamed before the crash is preserved...
    assert BlockStart(kind="text") in events
    assert TextDelta(text="partway") in events
    # ...and the abrupt exit becomes a clean Result, never a raised
    # exception out of start() (10 §3 U5's "mid-stream kill" pin).
    assert isinstance(events[-1], Result)
    assert events[-1].status == "error"
    assert events[-1].cost_usd is None
    assert events[-1].error


async def test_malformed_line_is_skipped_and_the_turn_completes(tmp_path: Path) -> None:
    """A raw non-JSON stdout line mid-transcript (the CLI's own transport
    layer skips it, per the installed SDK's ``_parse_stdout_line`` —
    verified in the module docstring) must not interrupt the turn: both
    the delta before and the delta after it arrive, and the turn reaches
    its result normally."""
    engine = _engine()
    try:
        events = await _drain(engine.start(_ctx(tmp_path, "malformed_line")))
    finally:
        await engine.close()

    deltas = [ev.text for ev in events if isinstance(ev, TextDelta)]
    assert deltas == ["before", "after"]
    assert isinstance(events[-1], Result)
    assert events[-1].status == "success"


async def test_unknown_event_type_is_skipped_not_raised(tmp_path: Path) -> None:
    engine = _engine()
    try:
        events = await _drain(engine.start(_ctx(tmp_path, "unknown_event_type")))
    finally:
        await engine.close()

    deltas = [ev.text for ev in events if isinstance(ev, TextDelta)]
    assert deltas == ["A", "B"]
    assert isinstance(events[-1], Result)
    assert events[-1].status == "success"


async def test_unrecognized_stream_delta_type_is_skipped_pure_unit() -> None:
    """The same tolerance, exercised directly on the mapping function with
    no subprocess at all — the sdk engine must not crash on an inner
    ``StreamEvent.event`` shape it has never seen."""
    from claude_agent_sdk import StreamEvent

    engine = _engine()
    weird = StreamEvent(
        uuid="u1",
        session_id="s1",
        event={"type": "content_block_delta", "index": 0, "delta": {"type": "totally_new_delta_kind"}},
        parent_tool_use_id=None,
    )
    assert engine._map_message(weird) == []  # noqa: SLF001 - the mapping function's own contract


async def test_tool_use_and_file_changed_mapping(tmp_path: Path) -> None:
    engine = _engine()
    try:
        events = await _drain(engine.start(_ctx(tmp_path, "tool_use")))
    finally:
        await engine.close()

    assert ToolUse(name="Edit", target="/tmp/example/pending/lrn-abc.md") in events
    assert FileChanged(path="/tmp/example/pending/lrn-abc.md") in events
    assert isinstance(events[-1], Result)
    assert events[-1].status == "success"


async def test_interrupt_is_a_no_op_before_any_session_started() -> None:
    engine = _engine()
    await asyncio.wait_for(engine.interrupt(), timeout=2.0)  # must return promptly, not hang


async def test_interrupt_is_a_no_op_on_an_ended_session(tmp_path: Path) -> None:
    """10 §3 U5's pinned case: once a turn has produced its Result, the
    session is 'ended' for interrupt purposes — calling interrupt() must
    not try to talk to the (now-idle) subprocess."""
    engine = _engine()
    try:
        events = await _drain(engine.start(_ctx(tmp_path, "happy_path")))
        assert isinstance(events[-1], Result)
        await asyncio.wait_for(engine.interrupt(), timeout=2.0)
    finally:
        await engine.close()


async def test_close_is_idempotent() -> None:
    engine = _engine()
    await engine.close()
    await engine.close()  # must not raise on a session that never started


# -- production construction path (interim-review BLOCKER regression) -----
#
# The wave-1 join reconciled `default_canon_read_roots` to one-arg but the
# suite injected a zero-arg fake into EVERY engine/charter test, so the
# production default (SdkPaneEngine built with no canon_read_roots_fn, as
# build_pane_manager's engine_factory does) was never exercised — it would
# have raised TypeError on the FIRST real Iterate. These tests build the
# engine exactly as the factory does and drive _build_options, the method
# every session start runs, with NO fake injected.

def _real_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    skills_root = tmp_path / "skillsrepo"
    (skills_root / "plugins" / "demo" / "skills" / "demo").mkdir(parents=True, exist_ok=True)
    (home / "hosts.yaml").write_text(f"skills_root: {skills_root}\nprojects: []\n")
    return home


def test_build_options_works_with_production_default_canon_fn(tmp_path: Path) -> None:
    """SdkPaneEngine constructed the way build_pane_manager's factory does
    — NO canon_read_roots_fn injected — must build its options (and thus
    its can_use_tool charter) without raising. This is the exact path the
    zero-arg-fake mock theater hid."""
    home = _real_home(tmp_path)
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    engine = SdkPaneEngine(
        model="claude-sonnet-5",
        max_turns=15,
        max_budget_usd=1.0,
        cli_path=str(FAKE_CLI),
    )
    ctx = PaneContext(
        record_id="abc123",
        bucket_root=bucket,
        self_learn_home=home,
        system_prompt="doctrine",
        first_message="hi",
    )
    options = engine._build_options(ctx)  # the per-session-start call
    assert options.can_use_tool is not None  # charter built, no TypeError


def test_result_carries_turn_count() -> None:
    """num_turns flows from ResultMessage into Result.turns (interim-review
    MINOR 4 — the field IS reported by the SDK; it must not render None)."""
    engine = SdkPaneEngine(
        model="claude-sonnet-5",
        max_turns=15,
        max_budget_usd=1.0,
        cli_path=str(FAKE_CLI),
    )

    class _Msg:
        subtype = "success"
        total_cost_usd = 0.01
        is_error = False
        errors: list[str] = []
        result = ""
        num_turns = 4

    mapped = engine._map_result(_Msg())
    assert mapped.turns == 4
