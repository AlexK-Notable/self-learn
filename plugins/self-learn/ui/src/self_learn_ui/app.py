"""app.py — the FastAPI app factory (10 §3 U3: "Front/Bucket/Detail routes
+ partials ... security middleware, SSE endpoint"). One function,
:func:`create_app`, wires every U3 piece together; nothing constructs its
own ad hoc FastAPI instance elsewhere (:mod:`self_learn_ui.cli`'s
``serve`` subcommand is the only other caller, at U9/U10 wiring — out of
this track's scope beyond exposing this factory).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import markupsafe
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from starlette.staticfiles import StaticFiles

from . import ledger, models, pane, rendering
from .env import EnvConfig
from .idle import ActivityTracker, IdleMonitor
from .middleware import SecurityMiddleware
from .prefetch import DetailPrefetchCache
from .routes import router
from .runner import RealRunner, VerbRunner
from .sse import AppEventHub

__all__ = ["create_app"]

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # .../ui
TEMPLATES_DIR = _PACKAGE_ROOT / "templates"
STATIC_DIR = _PACKAGE_ROOT / "static"


def _build_templates() -> Jinja2Templates:
    # AUTOESCAPE MARKER (09 §3 W-1): explicit autoescape=True, constructed
    # here and ONLY here — never `{% autoescape false %}` anywhere in the
    # template tree (enforced by convention + tests/test_templates.py).
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    env.filters["markdown"] = lambda text: markupsafe.Markup(rendering.render_markdown(text))
    env.filters["pygments_diff"] = lambda text: markupsafe.Markup(rendering.render_diff(text))
    env.filters["pygments_yaml"] = lambda text: markupsafe.Markup(rendering.render_yaml(text))
    env.filters["pygments_bash"] = lambda text: markupsafe.Markup(rendering.render_bash(text))
    env.filters["humanize_ts"] = lambda value: markupsafe.Markup(rendering.humanize_ts(value))
    # F5-9 (feedback round 5, U19 §1.5): the ONE label map (models.py's
    # _GROUP_LABELS, already Bucket's group-header source) — Detail's
    # action bar + Why region gloss through this same filter, never a
    # second map.
    env.filters["destination_label"] = models.destination_label
    # A1 (labels-only claude-md spec, P-A12): the resolved-path
    # counterpart to destination_label above — rendered alongside the
    # label at the two identity/decision surfaces (detail.html,
    # action_bar.html's cycle button).
    env.filters["destination_path"] = models.destination_path
    # F5-1 (feedback round 5, U19 §1.2 gate M1): detail_degraded.html has
    # no DetailModel/BucketModel to carry a pre-computed destination_cycle
    # (a degraded record's frontmatter may not even parse) — the one
    # other site threading `scope` straight into the cycle-length check
    # this global exposes. Every other action_bar.html include threads a
    # model-computed tuple instead (single source: models.py's own
    # function, never a second one).
    env.globals["destinations_for_scope"] = models.destinations_for_scope
    return Jinja2Templates(env=env)


def create_app(
    *,
    env: EnvConfig,
    token: str,
    runner: VerbRunner | None = None,
    refresh_hub: ledger.RefreshHub | None = None,
    app_hub: AppEventHub | None = None,
    start_watcher: bool = True,
    idle_exit_seconds: float = 0,
    idle_exit_callback=None,
) -> FastAPI:
    """Construct one server instance. ``token`` is minted by the caller
    (production: :mod:`self_learn_ui.cli`'s ``serve`` at process start,
    written 0600 via :func:`self_learn_ui.middleware.write_token_file`;
    tests: any fixed string) — the middleware needs it at construction
    time, before any request arrives. ``runner`` defaults to
    :class:`self_learn_ui.runner.RealRunner` (U4's serialized async
    subprocess queue, wired to this app's own ``refresh_hub`` so every
    verb forces a push on completion) — the injectable seam stays live
    for tests, which pass :class:`self_learn_ui.runner.FakeRunner`
    explicitly.

    ``idle_exit_seconds`` (Y-14, 09 §3): > 0 starts the idle monitor in
    the lifespan — the caller (``cli.serve``) resolves the arming rule
    via :func:`self_learn_ui.idle.resolve_idle_window`; the default 0
    keeps every existing test construction resident. The tracker is
    built unconditionally (cheap; the middleware and SSE generator use
    it either way). ``idle_exit_callback`` is the injectable exit seam
    — production ``None`` means SIGTERM-to-self; tests inject a flag
    setter (never a real SIGTERM in-suite, 10 §3 U13)."""
    refresh_hub = refresh_hub if refresh_hub is not None else ledger.RefreshHub()
    app_hub = app_hub if app_hub is not None else AppEventHub()
    runner = (
        runner
        if runner is not None
        else RealRunner(home=env.self_learn_home, refresh_callback=refresh_hub.force_refresh)
    )
    stop_event = asyncio.Event()
    tracker = ActivityTracker()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watch_task: asyncio.Task | None = None
        idle_task: asyncio.Task | None = None
        app.state.idle_task = None
        if start_watcher:
            watch_task = asyncio.ensure_future(
                ledger.watch_ledger(env.self_learn_home, refresh_hub, stop_event=stop_event)
            )
        if idle_exit_seconds > 0:
            monitor = IdleMonitor(
                tracker=tracker,
                subscriber_count=lambda: (
                    refresh_hub.subscriber_count + app_hub.subscriber_count
                ),
                runner_busy=lambda: runner.busy,
                pane_manager=app.state.pane_manager,
                window_seconds=idle_exit_seconds,
                exit_callback=idle_exit_callback,
            )
            idle_task = asyncio.ensure_future(monitor.run())
            app.state.idle_task = idle_task
        try:
            yield
        finally:
            stop_event.set()
            if watch_task is not None:
                watch_task.cancel()
            if idle_task is not None:
                idle_task.cancel()
            # Y-15 (code-review MINOR-2): the background pane drain no
            # longer lives inside any request uvicorn's graceful
            # shutdown waits for — tear the live session down with the
            # app so shutdown never leaks a free-floating drain task or
            # an open engine child.
            manager = getattr(app.state, "pane_manager", None)
            if manager is not None:
                await manager.shutdown()

    app = FastAPI(lifespan=lifespan)
    app.state.env = env
    app.state.runner = runner
    app.state.refresh_hub = refresh_hub
    app.state.app_hub = app_hub
    app.state.templates = _build_templates()
    app.state.watch_stop_event = stop_event
    app.state.activity_tracker = tracker
    app.state.pane_manager = pane.build_pane_manager(
        env=env, runner=runner, app_hub=app_hub, refresh_hub=refresh_hub
    )
    # 09 §11 Y-19 item 1: the next-record prefetch cache. One instance per
    # server (same lifetime as refresh_hub, which it is generation-gated
    # against — self_learn_ui.prefetch's module docstring has the full
    # staleness contract).
    app.state.detail_prefetch = DetailPrefetchCache()

    app.add_middleware(SecurityMiddleware, port=env.ui_port, token=token, tracker=tracker)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app
