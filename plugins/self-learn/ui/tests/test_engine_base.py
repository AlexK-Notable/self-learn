"""``PaneEngine`` seam + ``FakeEngine`` tests (10 §3 task U5, bullet 1;
10 §1's "Engine event protocol" row).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from self_learn_ui.engine import (
    BlockStart,
    FakeEngine,
    FileChanged,
    PaneContext,
    PaneEngine,
    Result,
    TextDelta,
    ToolUse,
)


def _ctx(record_id: str = "abc123") -> PaneContext:
    return PaneContext(
        record_id=record_id,
        bucket_root=Path("/tmp/bucket"),
        self_learn_home=Path("/tmp/home"),
        system_prompt="doctrine",
        first_message="look at this record",
    )


def test_pane_event_dataclasses_are_frozen_and_comparable() -> None:
    assert BlockStart(kind="text") == BlockStart(kind="text")
    assert TextDelta(text="hi") != TextDelta(text="bye")
    assert ToolUse(name="Edit", target="/a").target == "/a"
    assert FileChanged(path="/a").path == "/a"
    assert Result(status="success", cost_usd=0.01, error=None).error is None
    with pytest.raises(AttributeError):
        BlockStart(kind="text").kind = "other"  # frozen — assignment raises


def test_paneengine_is_abstract() -> None:
    with pytest.raises(TypeError):
        PaneEngine()  # type: ignore[abstract]


async def test_fake_engine_start_plays_first_turn() -> None:
    engine = FakeEngine(turns=[[BlockStart(kind="text"), TextDelta(text="hi"), Result("success", 0.0, None)]])
    events = [ev async for ev in engine.start(_ctx())]
    assert events == [BlockStart(kind="text"), TextDelta(text="hi"), Result("success", 0.0, None)]
    assert engine.started is True
    assert engine.contexts[0].record_id == "abc123"


async def test_fake_engine_send_plays_subsequent_turns_in_order() -> None:
    engine = FakeEngine(
        turns=[
            [Result("success", 0.0, None)],
            [TextDelta(text="follow-up"), Result("success", 0.0, None)],
        ]
    )
    first = [ev async for ev in engine.start(_ctx())]
    second = [ev async for ev in engine.send("more please")]
    assert first == [Result("success", 0.0, None)]
    assert second == [TextDelta(text="follow-up"), Result("success", 0.0, None)]
    assert engine.sent == ["more please"]


async def test_fake_engine_extra_send_beyond_scripted_turns_yields_nothing() -> None:
    engine = FakeEngine(turns=[[Result("success", 0.0, None)]])
    _ = [ev async for ev in engine.start(_ctx())]
    extra = [ev async for ev in engine.send("one too many")]
    assert extra == []


async def test_fake_engine_interrupt_and_close_are_recorded() -> None:
    engine = FakeEngine()
    await engine.interrupt()
    await engine.interrupt()
    await engine.close()
    assert engine.interrupt_calls == 2
    assert engine.close_calls == 1
    assert engine.closed is True
