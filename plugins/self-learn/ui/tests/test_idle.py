"""Y-14 idle-lifecycle tests (10 §3 U13): the ActivityTracker, the
arming rule, the five-legged predicate (each leg blocking alone), the
teardown-defers-exit pin (delta R1), the decrement-in-finally pin
(delta R3), and the monitor task lifecycle. The exit callback is ALWAYS
an injected flag — never a real SIGTERM in-suite (10 §3 U13, pinned).

Pane-manager-level pieces (has_interruptible_session/teardown_parked
against the real PaneManager + FakeEngine, incl. the delta-R4
idempotence pin) live in ``test_pane.py`` beside its `_manager`
harness; app-level wiring (middleware counter, SSE disconnect stamp,
lifespan task) lives here against the real app factory.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import cast

import pytest

from self_learn_ui.env import DEFAULT_UI_IDLE_EXIT_SECONDS, EnvConfig
from self_learn_ui.idle import ActivityTracker, IdleMonitor, resolve_idle_window

# ------------------------------------------------------------------ fakes


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakePane:
    """Just the two surfaces the monitor reads (the real PaneManager's
    behavior is pinned in test_pane.py)."""

    def __init__(self, *, interruptible: bool = False, parked: bool = False) -> None:
        self.interruptible = interruptible
        self.parked = parked
        self.teardown_calls = 0
        self.on_teardown: Callable[[], None] | None = None

    def has_interruptible_session(self) -> bool:
        return self.interruptible

    async def teardown_parked(self) -> bool:
        self.teardown_calls += 1
        was_parked = self.parked
        self.parked = False
        if self.on_teardown is not None:
            self.on_teardown()
        return was_parked


def _monitor(
    *,
    clock: FakeClock,
    tracker: ActivityTracker | None = None,
    subscribers: int = 0,
    busy: bool = False,
    pane: FakePane | None = None,
    window: float = 600.0,
) -> tuple[IdleMonitor, ActivityTracker, FakePane, dict[str, int]]:
    tracker = tracker if tracker is not None else ActivityTracker(clock=clock)
    pane = pane if pane is not None else FakePane()
    fired = {"count": 0}

    def exit_callback() -> None:
        fired["count"] += 1

    monitor = IdleMonitor(
        tracker=tracker,
        subscriber_count=lambda: subscribers,
        runner_busy=lambda: busy,
        pane_manager=pane,
        window_seconds=window,
        exit_callback=exit_callback,
        sample_seconds=0.01,
    )
    return monitor, tracker, pane, fired


# ------------------------------------------------------------ ActivityTracker


def test_tracker_counts_in_flight_and_stamps_on_finish() -> None:
    clock = FakeClock()
    tracker = ActivityTracker(clock=clock)
    tracker.request_started()
    tracker.request_started()
    assert tracker.in_flight == 2
    clock.advance(50)
    tracker.request_finished()
    assert tracker.in_flight == 1
    assert tracker.quiet_seconds() == 0.0
    clock.advance(30)
    assert tracker.quiet_seconds() == 30.0


def test_tracker_decrement_floors_at_zero() -> None:
    tracker = ActivityTracker(clock=FakeClock())
    tracker.request_finished()
    assert tracker.in_flight == 0


def test_tracker_mark_activity_resets_quiet() -> None:
    clock = FakeClock()
    tracker = ActivityTracker(clock=clock)
    clock.advance(500)
    assert tracker.quiet_seconds() == 500.0
    tracker.mark_activity()
    assert tracker.quiet_seconds() == 0.0


# ------------------------------------------------------------- arming rule


def _env_config(idle: int | None) -> EnvConfig:
    return EnvConfig(
        self_learn_home=Path("/tmp/x"),
        ui_port=7357,
        ui_browser=None,
        pane_model="m",
        pane_budget_usd=1.0,
        pane_max_turns=5,
        pane_engine="sdk",
        ui_idle_exit_seconds=idle,
    )


def test_arming_explicit_value_always_wins() -> None:
    assert resolve_idle_window(_env_config(120), environ={}) == 120
    assert resolve_idle_window(_env_config(120), environ={"INVOCATION_ID": "x"}) == 120


def test_arming_explicit_nonpositive_disables_never_errors() -> None:
    # Pinned at the Y-14 spec gate (09 §4.4): ≤0 disables, negatives
    # never error.
    assert resolve_idle_window(_env_config(0), environ={"INVOCATION_ID": "x"}) == 0
    assert resolve_idle_window(_env_config(-5), environ={"INVOCATION_ID": "x"}) == 0


def test_arming_default_only_under_systemd_unit() -> None:
    # Y-14 decision 6: foreground serve (no INVOCATION_ID) has no
    # launcher resurrection path — stays resident.
    assert (
        resolve_idle_window(_env_config(None), environ={"INVOCATION_ID": "abc"})
        == DEFAULT_UI_IDLE_EXIT_SECONDS
    )
    assert resolve_idle_window(_env_config(None), environ={}) == 0


# ---------------------------------------------------- predicate, leg by leg


def test_predicate_holds_when_fully_idle() -> None:
    clock = FakeClock()
    monitor, tracker, pane, fired = _monitor(clock=clock)
    clock.advance(601)
    assert monitor.predicate() is True


def test_each_leg_blocks_alone() -> None:
    clock = FakeClock()

    # leg 1: an SSE subscriber
    monitor, _, _, _ = _monitor(clock=clock, subscribers=1)
    clock.advance(601)
    assert monitor.predicate() is False

    # leg 2: an in-flight request (delta F2 — client may be long gone)
    clock = FakeClock()
    monitor, tracker, _, _ = _monitor(clock=clock)
    tracker.request_started()
    clock.advance(601)
    assert monitor.predicate() is False

    # leg 3: verb runner mid-verb
    clock = FakeClock()
    monitor, _, _, _ = _monitor(clock=clock, busy=True)
    clock.advance(601)
    assert monitor.predicate() is False

    # leg 4: pane session mid-turn (INTERRUPTIBLE)
    clock = FakeClock()
    monitor, _, _, _ = _monitor(clock=clock, pane=FakePane(interruptible=True))
    clock.advance(601)
    assert monitor.predicate() is False

    # leg 5: quiet shorter than the window
    clock = FakeClock()
    monitor, _, _, _ = _monitor(clock=clock)
    clock.advance(599)
    assert monitor.predicate() is False


def test_clock_stamps_at_completion_not_arrival() -> None:
    # Delta F2: a long request must not age toward idleness while it
    # runs — quiet time counts from request_finished(), and the
    # in-flight leg blocks the whole time regardless.
    clock = FakeClock()
    monitor, tracker, _, _ = _monitor(clock=clock)
    tracker.request_started()
    clock.advance(700)  # longer than the window, all of it in-flight
    assert monitor.predicate() is False  # leg 2
    tracker.request_finished()
    assert monitor.predicate() is False  # leg 5: quiet == 0 now
    clock.advance(601)
    assert monitor.predicate() is True


# -------------------------------------------------- sample_once (delta R1)


async def test_sample_exits_when_idle_and_nothing_parked() -> None:
    clock = FakeClock()
    monitor, _, pane, fired = _monitor(clock=clock)
    clock.advance(601)
    assert await monitor.sample_once() is True
    assert fired["count"] == 1
    assert pane.teardown_calls == 1  # probed, found nothing parked


async def test_sample_defers_after_parked_teardown() -> None:
    # Delta R1 pin: teardown and exit NEVER share a step — even when
    # the predicate would still hold after the teardown.
    clock = FakeClock()
    monitor, _, pane, fired = _monitor(clock=clock, pane=FakePane(parked=True))
    clock.advance(601)
    assert await monitor.sample_once() is False
    assert pane.teardown_calls == 1
    assert fired["count"] == 0
    # next sample: parked session gone, still quiet -> exits
    assert await monitor.sample_once() is True
    assert fired["count"] == 1


async def test_request_completing_during_teardown_blocks_the_signal() -> None:
    # Delta R1's failure scenario, pinned: activity landing while the
    # teardown awaits must be seen before any exit.
    clock = FakeClock()
    pane = FakePane(parked=True)
    monitor, tracker, _, fired = _monitor(clock=clock, pane=pane)
    pane.on_teardown = tracker.mark_activity  # "a request completed mid-teardown"
    clock.advance(601)
    assert await monitor.sample_once() is False  # defer (teardown ran)
    assert fired["count"] == 0
    # the NEXT sample re-reads the full predicate and sees the activity
    assert await monitor.sample_once() is False
    assert fired["count"] == 0


async def test_monitor_run_loops_until_exit_and_is_cancellable() -> None:
    clock = FakeClock()
    monitor, _, _, fired = _monitor(clock=clock, subscribers=1)
    task = asyncio.ensure_future(monitor.run())
    await asyncio.sleep(0.05)
    assert not task.done()  # subscriber leg blocks forever
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    clock2 = FakeClock()
    monitor2, _, _, fired2 = _monitor(clock=clock2)
    clock2.advance(601)
    task2 = asyncio.ensure_future(monitor2.run())
    await asyncio.wait_for(task2, timeout=2)
    assert fired2["count"] == 1


# ------------------------------------------------------- app-level wiring


def test_sse_disconnect_stamps_the_activity_clock() -> None:
    # 09 §3 leg 5's intent: the window counts from last-tab-close. The
    # middleware's completion stamp for a streaming response fires at
    # CONNECT time, so event_stream's own finally must stamp on
    # disconnect.
    import anyio

    from self_learn_ui.ledger import RefreshHub
    from self_learn_ui.sse import AppEventHub, event_stream

    clock = FakeClock()
    tracker = ActivityTracker(clock=clock)

    async def scenario() -> None:
        refresh_hub = RefreshHub()
        app_hub = AppEventHub()
        stream = cast(
            "AsyncGenerator[str, None]",
            event_stream(refresh_hub, app_hub, tracker=tracker),
        )
        # generators subscribe lazily on first __anext__ — start the
        # read (it blocks on the queues), THEN publish
        frame_task = asyncio.ensure_future(stream.__anext__())
        await asyncio.sleep(0.05)
        await app_hub.publish({"type": "banner", "text": "x"})
        assert "banner" in await asyncio.wait_for(frame_task, timeout=2)
        clock.advance(3600)  # an hour with the tab open
        await stream.aclose()  # the tab closes
        assert tracker.quiet_seconds() == 0.0
        assert refresh_hub.subscriber_count == 0
        assert app_hub.subscriber_count == 0

    anyio.run(scenario)


def test_create_app_starts_idle_task_only_when_window_positive(tmp_path) -> None:
    from starlette.testclient import TestClient

    from self_learn_ui.app import create_app
    from self_learn_ui.env import load_env
    from self_learn_ui.runner import FakeRunner

    from support import make_env

    sb = make_env(tmp_path)
    env = load_env(sb.env)

    app = create_app(
        env=env,
        token="t",
        runner=FakeRunner(),
        start_watcher=False,
        idle_exit_seconds=600,
        idle_exit_callback=lambda: None,
    )
    with TestClient(app, base_url="http://127.0.0.1:7357"):
        assert app.state.idle_task is not None
        assert not app.state.idle_task.done()
    # lifespan exit cancels the monitor — no leak, no exit fired

    app2 = create_app(
        env=env, token="t", runner=FakeRunner(), start_watcher=False
    )
    with TestClient(app2, base_url="http://127.0.0.1:7357"):
        assert getattr(app2.state, "idle_task", None) is None
