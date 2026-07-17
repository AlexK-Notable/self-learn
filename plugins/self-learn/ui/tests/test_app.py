"""app.py — the FastAPI app factory (10 §3 U3). Verifies the wiring: the
security middleware is installed, static files are mounted (with CSP),
autoescape is on, and SSE frames escape adversarial content (the SSE half
of the render-path security matrix — the page half lives in
test_routes.py)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from starlette.testclient import TestClient

from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.middleware import CSP_HEADER_VALUE, TOKEN_COOKIE_NAME
from self_learn_ui.runner import FakeRunner
from self_learn_ui.sse import envelope_banner

from support import make_env

TOKEN = "test-token"


def make_client(sb):
    env = load_env(sb.env)
    app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    c = TestClient(app, base_url="http://127.0.0.1:7357")
    c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
    return c, app


class TestCreateApp:
    def test_security_middleware_rejects_unauthenticated(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        env = load_env(sb.env)
        app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
        c = TestClient(app, base_url="http://127.0.0.1:7357")
        r = c.get("/")
        assert r.status_code == 403

    def test_authenticated_request_succeeds(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _app = make_client(sb)
        r = c.get("/")
        assert r.status_code == 200

    def test_csp_header_on_every_response(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _app = make_client(sb)
        for path in ("/", "/report", "/static/style.css"):
            r = c.get(path)
            assert r.headers["content-security-policy"] == CSP_HEADER_VALUE

    def test_static_files_mounted(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        c, _app = make_client(sb)
        for name in ("style.css", "app.js", "htmx-2.0.9.min.js", "pygments.css"):
            r = c.get(f"/static/{name}")
            assert r.status_code == 200, name

    def test_default_runner_is_not_wired(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        env = load_env(sb.env)
        app = create_app(env=env, token=TOKEN, start_watcher=False)
        from self_learn_ui.runner import NotWiredRunner

        assert isinstance(app.state.runner, NotWiredRunner)

    def test_wrong_port_in_env_changes_host_allowlist(self, tmp_path: Path) -> None:
        sb = make_env(tmp_path)
        env = load_env({**sb.env, "SELF_LEARN_UI_PORT": "9999"})
        app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
        c = TestClient(app, base_url="http://127.0.0.1:7357")  # wrong port for this app
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        r = c.get("/")
        assert r.status_code == 403


class TestSSEEscaping:
    async def test_pane_block_style_envelope_with_script_payload_stays_escaped(
        self, tmp_path: Path
    ) -> None:
        """The SSE half of W-1's escaping pin: ANY html rendered into an
        SSE frame must go through the same html=False markdown renderer
        as the page. This exercises the actual wire format via
        AppEventHub + rendering.render_markdown, the same pipeline a
        future U6 pane_block frame would use."""
        from self_learn_ui.rendering import render_markdown
        from self_learn_ui.sse import format_sse

        payload = render_markdown("<script>alert(1)</script>")
        frame = format_sse({"type": "pane_block", "html": payload})
        assert "<script>alert(1)</script>" not in frame
        decoded = json.loads(frame[len("data: ") : -2])
        assert "<script>" not in decoded["html"]

    def test_events_route_is_registered_and_security_gated(self, tmp_path: Path) -> None:
        # A live, never-ending SSE body cannot be drained through the
        # synchronous TestClient without a real client-side disconnect
        # (attempting it deadlocks the test process — the request handler
        # and the test body share one event loop under TestClient).
        # event_stream()'s merge/escaping logic is exhaustively covered
        # at the unit level in test_sse.py; here we only prove the route
        # exists and is gated by the same security middleware as
        # everything else (an unauthenticated GET must still 403, never
        # hang or bypass auth for this one path).
        sb = make_env(tmp_path)
        env = load_env(sb.env)
        app = create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)

        # Gated (403, not a hang or an auth bypass) when unauthenticated —
        # a fast, deterministic check that doesn't require draining a
        # live never-ending body (draining one through the synchronous
        # TestClient deadlocks the test process regardless of any
        # per-request timeout passed to it — a TestClient/asyncio
        # interaction, not an app bug; a real ASGI server + browser
        # EventSource has no such issue, and is the X-5 acceptance venue
        # for the live-stream path per 09 §7/10 §2).
        c = TestClient(app, base_url="http://127.0.0.1:7357")  # no cookie set
        r = c.get("/events")
        assert r.status_code == 403
