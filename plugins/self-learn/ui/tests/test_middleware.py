"""SecurityMiddleware — the full pin set (10 §1 Network & security row):
Host allowlist, token->cookie->303 flow, POST-only+HX-Request on mutating
routes, cookie-gated GET, CSP header on every response, the 403 page
naming the launcher, and the token file's 0600 write + X-8 XDG fallback.

10 §0 rules 7/8: every test uses a throwaway env mapping — nothing here
touches the real ``$XDG_RUNTIME_DIR``/cache."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from starlette.testclient import TestClient

from self_learn_ui.middleware import (
    CSP_HEADER_VALUE,
    FORBIDDEN_PAGE_NAME,
    SecurityMiddleware,
    TOKEN_COOKIE_NAME,
    mint_token,
    resolve_token_path,
    write_token_file,
)

PORT = 7357
TOKEN = "test-token-abc123"


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityMiddleware, port=PORT, token=TOKEN)

    @app.get("/")
    def index():
        return PlainTextResponse("front")

    @app.get("/static/style.css")
    def static_css():
        return PlainTextResponse("body{}", media_type="text/css")

    @app.post("/record/lrn-aa000001/confirm")
    def confirm():
        return PlainTextResponse("confirmed")

    return app


def client(app: FastAPI, **kwargs) -> TestClient:
    # base_url controls the Host header TestClient sends.
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", **kwargs)


class TestHostAllowlist:
    def test_correct_host_127_passes(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.get("/")
        assert resp.status_code == 200

    def test_localhost_host_passes(self) -> None:
        app = make_app()
        c = TestClient(app, base_url=f"http://localhost:{PORT}")
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.get("/")
        assert resp.status_code == 200

    def test_wrong_host_rejected(self) -> None:
        app = make_app()
        c = TestClient(app, base_url="http://evil.example.com")
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.get("/")
        assert resp.status_code == 403
        assert FORBIDDEN_PAGE_NAME in resp.text

    def test_wrong_port_on_localhost_rejected(self) -> None:
        app = make_app()
        c = TestClient(app, base_url="http://127.0.0.1:9999")
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.get("/")
        assert resp.status_code == 403


class TestTokenCookieFlow:
    def test_token_query_param_sets_cookie_and_redirects_303(self) -> None:
        c = client(make_app())
        resp = c.get(f"/?token={TOKEN}", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        assert TOKEN_COOKIE_NAME in resp.cookies
        assert resp.cookies[TOKEN_COOKIE_NAME] == TOKEN

    def test_redirect_lands_on_clean_path_no_query_string(self) -> None:
        c = client(make_app())
        resp = c.get(f"/record/lrn-aa000001/confirm?token={TOKEN}", follow_redirects=False)
        # GET on this path isn't registered, but the redirect target is what's
        # asserted — the clean URL is the PATH with no query string.
        assert resp.headers["location"] == "/record/lrn-aa000001/confirm"

    def test_wrong_token_query_param_rejected(self) -> None:
        c = client(make_app())
        resp = c.get("/?token=not-the-real-token")
        assert resp.status_code == 403

    def test_cookie_set_by_token_flow_then_authenticates_subsequent_requests(self) -> None:
        c = client(make_app())
        c.get(f"/?token={TOKEN}")  # TestClient follows redirects + keeps cookies by default
        resp = c.get("/")
        assert resp.status_code == 200
        assert resp.text == "front"


class TestCookieGatedReads:
    def test_missing_cookie_rejected_with_403(self) -> None:
        c = client(make_app())
        resp = c.get("/")
        assert resp.status_code == 403
        assert FORBIDDEN_PAGE_NAME in resp.text

    def test_stale_cookie_rejected(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, "some-old-invalid-token")
        resp = c.get("/")
        assert resp.status_code == 403

    def test_valid_cookie_authenticates_get(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.get("/")
        assert resp.status_code == 200


class TestMutatingRoutes:
    def test_post_without_cookie_rejected(self) -> None:
        c = client(make_app())
        resp = c.post("/record/lrn-aa000001/confirm", headers={"HX-Request": "true"})
        assert resp.status_code == 403

    def test_post_with_cookie_but_no_hx_request_header_rejected(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.post("/record/lrn-aa000001/confirm")
        assert resp.status_code == 403

    def test_post_with_cookie_and_hx_request_succeeds(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.post("/record/lrn-aa000001/confirm", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert resp.text == "confirmed"

    def test_post_with_wrong_hx_request_value_rejected(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.post("/record/lrn-aa000001/confirm", headers={"HX-Request": "false"})
        assert resp.status_code == 403


class TestCSPHeader:
    def test_csp_present_on_success(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.get("/")
        assert resp.headers["content-security-policy"] == CSP_HEADER_VALUE

    def test_csp_present_on_403_host_rejection(self) -> None:
        app = make_app()
        c = TestClient(app, base_url="http://evil.example.com")
        resp = c.get("/")
        assert resp.status_code == 403
        assert resp.headers["content-security-policy"] == CSP_HEADER_VALUE

    def test_csp_present_on_403_auth_rejection(self) -> None:
        c = client(make_app())
        resp = c.get("/")
        assert resp.status_code == 403
        assert resp.headers["content-security-policy"] == CSP_HEADER_VALUE

    def test_csp_present_on_static_asset(self) -> None:
        c = client(make_app())
        c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
        resp = c.get("/static/style.css")
        assert resp.headers["content-security-policy"] == CSP_HEADER_VALUE

    def test_csp_exact_pinned_string(self) -> None:
        assert CSP_HEADER_VALUE == (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'"
        )


class TestForbiddenPageNamesLauncher:
    def test_403_names_the_launcher(self) -> None:
        c = client(make_app())
        resp = c.get("/")
        assert resp.status_code == 403
        assert "self-learn-ui-open" in resp.text


class TestMintToken:
    def test_mint_token_is_nonempty_and_varies(self) -> None:
        a = mint_token()
        b = mint_token()
        assert a and b
        assert a != b
        assert len(a) > 20


class TestTokenFile:
    def test_resolves_under_runtime_dir_when_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        path = resolve_token_path()
        assert path == runtime / "self-learn" / "ui-token"

    def test_x8_fallback_to_cache_dir_when_runtime_dir_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache_home = tmp_path / "cache"
        ledger_home = tmp_path / "ledger-home"
        cache_home.mkdir()
        ledger_home.mkdir()
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
        monkeypatch.setenv("SELF_LEARN_HOME", str(ledger_home))
        path = resolve_token_path()
        assert path.name == "ui-token"
        assert path.is_relative_to(cache_home)

    def test_write_token_file_is_0600(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        token = mint_token()
        path = write_token_file(token)
        assert path.read_text(encoding="utf-8") == token
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_write_token_file_creates_parent_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        path = write_token_file(mint_token())
        assert path.parent.is_dir()


# ------------------------------------------------- Y-14: activity tracking


class TestActivityTracking:
    """The middleware maintains the idle predicate's legs 2 and 5
    (in-flight counter, completion clock) around EVERY dispatched
    request — including 403s (any local probe is activity). The
    decrement lives in a ``finally`` (delta R3): a handler that raises
    (the client-disconnect-cancellation shape) must never leak a
    permanent in-flight count."""

    def _tracked_app(self):
        from self_learn_ui.idle import ActivityTracker

        tracker = ActivityTracker()
        app = FastAPI()
        app.add_middleware(SecurityMiddleware, port=PORT, token=TOKEN, tracker=tracker)
        seen = {}

        @app.get("/")
        def index():
            seen["in_flight_during"] = tracker.in_flight
            return PlainTextResponse("front")

        @app.get("/boom")
        def boom():
            raise RuntimeError("handler died mid-request")

        return app, tracker, seen

    def test_request_counts_in_flight_and_stamps_completion(self) -> None:
        app, tracker, seen = self._tracked_app()
        c = client(app)
        before = tracker.quiet_seconds()
        assert before >= 0.0
        resp = c.get("/", cookies={TOKEN_COOKIE_NAME: TOKEN})
        assert resp.status_code == 200
        assert seen["in_flight_during"] == 1
        assert tracker.in_flight == 0
        assert tracker.quiet_seconds() < 1.0

    def test_403_is_still_activity(self) -> None:
        app, tracker, _ = self._tracked_app()
        c = client(app)
        resp = c.get("/")  # no cookie -> 403
        assert resp.status_code == 403
        assert tracker.in_flight == 0
        assert tracker.quiet_seconds() < 1.0

    def test_raising_handler_never_leaks_in_flight(self) -> None:
        # Delta R3: the decrement runs in a finally, so an exception
        # (or a cancellation, which unwinds the same way) cannot leave
        # a permanent in-flight count blocking idle exit forever.
        app, tracker, _ = self._tracked_app()
        c = client(app, raise_server_exceptions=False)
        resp = c.get("/boom", cookies={TOKEN_COOKIE_NAME: TOKEN})
        assert resp.status_code == 500
        assert tracker.in_flight == 0

    def test_untracked_construction_still_works(self) -> None:
        # tracker=None (the pre-Y-14 construction every existing test
        # uses) must stay valid.
        app = make_app()
        c = client(app)
        assert c.get("/", cookies={TOKEN_COOKIE_NAME: TOKEN}).status_code == 200
