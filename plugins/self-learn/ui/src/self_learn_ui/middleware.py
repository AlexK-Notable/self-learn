"""middleware.py — the ~50-line security surface (09 §3 / 10 §1 "Network &
security" row), plus the token-minting half of U7 that this track owns per
10 §8's file-ownership partition ("U7's server-side half — token minting
+ middleware wiring — it lives in C's files").

Pinned, verbatim from 10 §1:

- Reject unless ``Host`` ∈ {``127.0.0.1:<port>``, ``localhost:<port>``}
  (DNS-rebinding guard).
- A per-service-start random bearer token (``secrets.token_urlsafe``),
  written 0600 to ``$XDG_RUNTIME_DIR/self-learn/ui-token`` — X-8/X-12
  fallback to ``<cache>/ui-token`` (the SAME home-namespaced cache dir
  :mod:`self_learn_ui.uilog` uses) when ``$XDG_RUNTIME_DIR`` is unset.
- ``GET /?token=…`` (any path) sets the token as a ``SameSite=Strict;
  HttpOnly`` cookie and 303-redirects to the clean URL.
- Every mutating route (non-GET/HEAD) is POST-only and requires the valid
  cookie **and** the ``HX-Request`` header (CSRF belt-and-braces — a
  cross-site form cannot set a custom header).
- Every OTHER route also requires the valid cookie — the whole point of
  the token→cookie flow is that a stale/absent cookie is a 403, named
  after the launcher that re-mints the tokened URL (09 §5's degradation
  row: "Token cookie absent/stale ... -> 403 page naming
  self-learn-ui-open").
- ``Content-Security-Policy`` on EVERY response — success, error, and
  static alike: ``default-src 'none'; script-src 'self'; style-src
  'self'; img-src 'self' data:; connect-src 'self'``.
"""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from self_learn.primitives import fsops

__all__ = [
    "CSP_HEADER_VALUE",
    "FORBIDDEN_PAGE_NAME",
    "SecurityMiddleware",
    "TOKEN_COOKIE_NAME",
    "TOKEN_FILE_NAME",
    "forbidden_response",
    "mint_token",
    "resolve_token_path",
    "write_token_file",
]

#: 09 §3 W-1/W-9, pinned VERBATIM — never edited per-route, never relaxed.
CSP_HEADER_VALUE = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'"
)

TOKEN_COOKIE_NAME = "slu_token"
TOKEN_FILE_NAME = "ui-token"

#: 09 §3 / 09 §5: the 403 page names this script as the fix — it
#: ensures the service is up and re-mints a tokened URL.
FORBIDDEN_PAGE_NAME = "self-learn-ui-open"

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ------------------------------------------------------------ token file


def mint_token() -> str:
    """A fresh per-service-start bearer token (09 §3)."""
    return secrets.token_urlsafe(32)


def resolve_token_path() -> Path:
    """The token file's resolved path — primary
    ``$XDG_RUNTIME_DIR/self-learn/ui-token``; X-8/X-12 fallback to
    ``<cache>/ui-token`` (:func:`self_learn.serve.cache_dir_readonly` —
    the SAME path formula :func:`self_learn.worker.cache_dir` and
    :mod:`self_learn_ui.uilog` use, never reimplemented, but WITHOUT
    their ``mkdir``/migration side effects: D8 gate r1 finding 1 — this
    is a path *read*, and mkdir-as-a-side-effect-of-reading is exactly
    what the D8 ``paths`` verb (:mod:`self_learn_ui.cli`) pins as never
    happening) when ``XDG_RUNTIME_DIR`` is unset.

    Reads real process env, like :func:`self_learn_ui.uilog.ui_log_path`
    and :func:`self_learn.worker.cache_dir` itself both do — the
    middleware runs in-process, not a subprocess, so there is no
    ``env=`` mapping to thread through (contrast
    :mod:`self_learn_ui.ledger`'s ``_invoke_json``, which DOES spawn a
    subprocess and therefore DOES take an explicit env). Tests redirect
    via ``monkeypatch.setenv`` (10 §0 rules 7/8; the same pattern
    ``tests/conftest.py``'s ``redirected_xdg`` fixture already uses).

    ``cache_dir_readonly`` is imported function-local (the shape
    :func:`self_learn_ui.cli._paths` already uses), not at module level,
    so this ~50-line security surface does not import the systemd-host
    module (:mod:`self_learn.serve`) at import time."""
    import os

    from self_learn.serve import cache_dir_readonly

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "self-learn" / TOKEN_FILE_NAME
    return cache_dir_readonly() / TOKEN_FILE_NAME


def write_token_file(token: str) -> Path:
    """Write *token* 0600 to :func:`resolve_token_path`'s location,
    creating parent dirs as needed. Returns the path written.

    Sprint 2 M-I (D6): the bearer token is the secret-file class --
    :func:`self_learn.primitives.fsops.private_write` (0600 always,
    symlinks refused, fsync'd), not the general :func:`fsops.
    atomic_write` every ledger content write below uses."""
    path = resolve_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fsops.private_write(path, token)
    return path


# --------------------------------------------------------------- 403 page


def forbidden_response(reason: str) -> HTMLResponse:
    """The pinned 403 page (09 §3/§5): names ``self-learn-ui-open`` as the
    fix. Plain, unstyled HTML — no inline ``style=``/``<script>`` (CSP;
    and static assets may themselves be behind this same gate, so the
    page must render meaningfully with nothing but the served stylesheet,
    which may not load)."""
    body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>403 — self-learn-ui</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body>
<main>
<h1>403 — access denied</h1>
<p>{reason}</p>
<p>Run <code>{FORBIDDEN_PAGE_NAME}</code> to re-open this window with a
fresh token.</p>
</main>
</body>
</html>"""
    return HTMLResponse(body, status_code=403)


# ---------------------------------------------------------------- middleware


class SecurityMiddleware(BaseHTTPMiddleware):
    """The whole security surface, one middleware (10 §1: "~50 lines of
    middleware + renderer configuration"). Constructed once per app with
    the service's port and per-start token."""

    def __init__(self, app, *, port: int, token: str, tracker=None) -> None:
        super().__init__(app)
        self._allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._token = token
        # Y-14 (09 §3): in-flight counter + completion clock. EVERY
        # dispatched request counts — 403s and static included (any
        # local probe is activity; accepted residual). The decrement
        # lives in a ``finally`` (delta R3: a client-disconnect
        # CancelledError mid-handler must not leak a permanent
        # in-flight count).
        self._tracker = tracker

    def _authed(self, request: Request) -> bool:
        cookie = request.cookies.get(TOKEN_COOKIE_NAME)
        return cookie is not None and hmac.compare_digest(cookie, self._token)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self._tracker is None:
            return await self._dispatch_inner(request, call_next)
        self._tracker.request_started()
        try:
            return await self._dispatch_inner(request, call_next)
        finally:
            self._tracker.request_finished()

    async def _dispatch_inner(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        host = (request.headers.get("host") or "").lower()
        if host not in self._allowed_hosts:
            return self._csp(forbidden_response("Host header rejected"))

        token_param = request.query_params.get("token")
        if token_param is not None:
            if not hmac.compare_digest(token_param, self._token):
                return self._csp(forbidden_response("invalid token"))
            resp = RedirectResponse(url=request.url.path, status_code=303)
            resp.set_cookie(
                TOKEN_COOKIE_NAME,
                token_param,
                httponly=True,
                samesite="strict",
                secure=False,  # 127.0.0.1 plaintext HTTP by design (09 §3)
                path="/",
            )
            return self._csp(resp)

        authed = self._authed(request)
        if request.method in _MUTATING_METHODS:
            hx = request.headers.get("HX-Request")
            if not authed or hx != "true":
                return self._csp(forbidden_response("mutating request rejected"))
        elif not authed:
            return self._csp(forbidden_response("missing or stale token cookie"))

        response = await call_next(request)
        return self._csp(response)

    @staticmethod
    def _csp(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = CSP_HEADER_VALUE
        return response
