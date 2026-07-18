"""idle.py — the Y-14 idle monitor (09 §3 "resident while in use";
10 §3 U13).

The server self-exits cleanly when a five-legged predicate holds — ALL
of (09 §3, as reworked at the Y-14 spec gate):

1. zero SSE subscribers (both hubs);
2. zero in-flight HTTP requests (delta F2's belt — a long bulk POST
   whose client vanished must still block);
3. the verb runner between verbs;
4. no live pane session in an INTERRUPTIBLE state (starting/streaming/
   interrupting — an agent mid-turn is work-in-flight; a session parked
   at awaiting-input does NOT block, it is torn down instead — Y-14
   decision 5);
5. the request-COMPLETION clock aged past the window (stamps at
   completion, never arrival — F2).

**Teardown and exit never share a step** (delta R1): a sample that
finds a parked session tears it down and DEFERS the exit decision to a
later sample; the signal fires only from a predicate read that reaches
the signal with no ``await`` in between. Everything here runs on the
request event loop, so that read-then-signal really is atomic with
respect to request handling.

Arming (Y-14 decision 6) lives in :func:`resolve_idle_window`: the
default 600 s window applies only under the systemd unit (detected via
``INVOCATION_ID``); a foreground ``serve`` — 10 §5's systemd-absent
playbook, where no launcher resurrection exists — stays resident
unless ``SELF_LEARN_UI_IDLE_EXIT_SECONDS`` is set explicitly. Any
value ≤ 0 disables (pinned: negatives never error — §4.4).
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Callable

from . import uilog
from .env import DEFAULT_UI_IDLE_EXIT_SECONDS, EnvConfig

__all__ = [
    "ActivityTracker",
    "IdleMonitor",
    "default_exit",
    "resolve_idle_window",
]

#: Sample cadence (10 §3 U13: "~30 s sample").
SAMPLE_SECONDS = 30.0


def resolve_idle_window(
    env: EnvConfig, environ: dict[str, str] | None = None
) -> int:
    """The effective idle window in seconds; ``0`` means disabled.

    Explicit ``SELF_LEARN_UI_IDLE_EXIT_SECONDS`` always wins (clamped
    at 0 — ≤0 disables, never errors). Unset: the default arms ONLY
    under the systemd unit (``INVOCATION_ID`` is set by the manager for
    every unit invocation) — a foreground serve has no launcher
    resurrection path and must stay resident (Y-14 decision 6).
    """
    e = os.environ if environ is None else environ
    if env.ui_idle_exit_seconds is not None:
        return max(0, env.ui_idle_exit_seconds)
    if e.get("INVOCATION_ID"):
        return DEFAULT_UI_IDLE_EXIT_SECONDS
    return 0


class ActivityTracker:
    """In-flight request counter + last-request-COMPLETION monotonic
    stamp (predicate legs 2 and 5). Maintained by
    :class:`self_learn_ui.middleware.SecurityMiddleware` around every
    dispatched request — 403s and static files included: any local
    probe is activity (09 §3's accepted residual). The SSE generator
    additionally calls :meth:`mark_activity` on disconnect, so the
    idle window counts from last-tab-close, not from the page load
    that opened the stream.

    ``clock`` is injectable for tests; production uses
    :func:`time.monotonic` (suspend-safe: CLOCK_MONOTONIC excludes
    suspended time, so a laptop lid-close never fast-forwards the
    window).
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._in_flight = 0
        self._last_completion = clock()

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def request_started(self) -> None:
        self._in_flight += 1

    def request_finished(self) -> None:
        """Decrement + stamp. Callers MUST invoke this from a
        ``finally`` (delta R3: a client-disconnect-cancelled handler
        that skipped the decrement would leak a permanent in-flight
        count and silently re-create resident-forever)."""
        self._in_flight = max(0, self._in_flight - 1)
        self.mark_activity()

    def mark_activity(self) -> None:
        self._last_completion = self._clock()

    def quiet_seconds(self) -> float:
        return self._clock() - self._last_completion


def default_exit() -> None:
    """SIGTERM to self → uvicorn graceful shutdown → exit 0 (09 §3:
    under ``Restart=on-failure`` a clean exit stays down; the launcher
    is the resurrection path)."""
    os.kill(os.getpid(), signal.SIGTERM)


class IdleMonitor:
    """One background task sampling the predicate every
    :data:`SAMPLE_SECONDS`. Constructor takes callables/objects rather
    than the app so tests drive it with fakes and an injected clock;
    ``exit_callback`` defaults to :func:`default_exit` and is NEVER a
    real SIGTERM in-suite (10 §3 U13).
    """

    def __init__(
        self,
        *,
        tracker: ActivityTracker,
        subscriber_count: Callable[[], int],
        runner_busy: Callable[[], bool],
        pane_manager,
        window_seconds: float,
        exit_callback: Callable[[], None] | None = None,
        sample_seconds: float = SAMPLE_SECONDS,
    ) -> None:
        self._tracker = tracker
        self._subscriber_count = subscriber_count
        self._runner_busy = runner_busy
        self._pane_manager = pane_manager
        self._window = window_seconds
        self._exit = exit_callback if exit_callback is not None else default_exit
        self._sample = sample_seconds

    def predicate(self) -> bool:
        """The five legs, all sync reads — callers rely on there being
        NO await between this returning True and the signal (09 §3)."""
        return (
            self._subscriber_count() == 0
            and self._tracker.in_flight == 0
            and not self._runner_busy()
            and not self._pane_manager.has_interruptible_session()
            and self._tracker.quiet_seconds() >= self._window
        )

    async def sample_once(self) -> bool:
        """One sample. Returns True iff the exit signal fired.

        Delta R1 pin: if a parked pane session exists, tear it down and
        DEFER — the teardown awaits engine calls, so this sample never
        signals; the next sample re-reads the full predicate (a request
        that completed during the teardown is seen before any exit).
        """
        if not self.predicate():
            return False
        if await self._pane_manager.teardown_parked():
            return False  # defer: never tear down and signal in one step
        if not self.predicate():  # pure sync re-read; no await after this
            return False
        uilog.log(
            f"idle monitor: predicate held for {self._window:.0f}s window — "
            "clean self-exit (09 §3 Y-14)"
        )
        self._exit()
        return True

    async def run(self) -> None:
        """The task :func:`self_learn_ui.app.create_app` starts when the
        resolved window is > 0. Cancellation (app shutdown) is the only
        exit besides the signal itself."""
        while True:
            await asyncio.sleep(self._sample)
            if await self.sample_once():
                return
