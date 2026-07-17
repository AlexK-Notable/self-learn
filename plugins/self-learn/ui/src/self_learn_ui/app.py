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

from . import ledger, rendering
from .env import EnvConfig
from .middleware import SecurityMiddleware
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
    return Jinja2Templates(env=env)


def create_app(
    *,
    env: EnvConfig,
    token: str,
    runner: VerbRunner | None = None,
    refresh_hub: ledger.RefreshHub | None = None,
    app_hub: AppEventHub | None = None,
    start_watcher: bool = True,
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
    explicitly."""
    refresh_hub = refresh_hub if refresh_hub is not None else ledger.RefreshHub()
    app_hub = app_hub if app_hub is not None else AppEventHub()
    runner = (
        runner
        if runner is not None
        else RealRunner(home=env.self_learn_home, refresh_callback=refresh_hub.force_refresh)
    )
    stop_event = asyncio.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watch_task: asyncio.Task | None = None
        if start_watcher:
            watch_task = asyncio.ensure_future(
                ledger.watch_ledger(env.self_learn_home, refresh_hub, stop_event=stop_event)
            )
        try:
            yield
        finally:
            stop_event.set()
            if watch_task is not None:
                watch_task.cancel()

    app = FastAPI(lifespan=lifespan)
    app.state.env = env
    app.state.runner = runner
    app.state.refresh_hub = refresh_hub
    app.state.app_hub = app_hub
    app.state.templates = _build_templates()
    app.state.watch_stop_event = stop_event

    app.add_middleware(SecurityMiddleware, port=env.ui_port, token=token)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app
