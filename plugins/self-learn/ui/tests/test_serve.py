"""End-to-end ``serve`` test (task U4 — this closes the gap named in the
brief: "serve was never end-to-end tested"). Spawns the REAL
``self-learn-ui serve`` process — the exact entry point
``systemd/self-learn-ui.service``'s ``ExecStart`` reaches through the
bash wrapper, invoked here as ``python -m self_learn_ui.cli serve`` to
skip the wrapper script itself (out of this track's scope; the wrapper is
tested separately in ``test_wrapper.py``) — on an ephemeral 127.0.0.1
port, against a throwaway ``SELF_LEARN_HOME`` (``support.bare_ledger``)
and redirected XDG dirs. No network beyond 127.0.0.1 (10 §0 rule 7); no
shimmed CLI here — the REAL ``self-learn`` binary runs against the
throwaway ledger (proving the actual production wiring, not a stand-in;
``test_runner_real.py`` covers the shimmed-binary argv matrix).

Drives the token->cookie->redirect flow with a real ``httpx`` client,
asserts the pinned CSP header on both the pre-auth 403 and the
authenticated 200, then shuts the server down with SIGTERM and asserts a
clean exit within a bounded wait (never an unattended block — same
discipline the user's own environment notes pin for other tools).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from self_learn_ui.middleware import CSP_HEADER_VALUE, TOKEN_COOKIE_NAME

from support import bare_ledger

_STARTUP_TIMEOUT_S = 15.0
_SHUTDOWN_TIMEOUT_S = 10.0


def _free_port() -> int:
    """Bind-then-release — the standard "pick a free ephemeral port"
    idiom; the tiny race window (something else grabbing the port before
    the child binds) is the accepted convention for test infra."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(proc: subprocess.Popen, port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            raise AssertionError(
                f"self-learn-ui serve exited early (rc={proc.returncode})\n"
                f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise AssertionError(f"self-learn-ui serve never opened 127.0.0.1:{port} within {timeout}s")


def _wait_for_file(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        time.sleep(0.05)
    raise AssertionError(f"{path} was never written within {timeout}s")


@pytest.fixture
def serve_process(tmp_path: Path):
    """Spawns the real server, yields (base_url, token), terminates +
    bounded-waits for a clean exit on teardown regardless of test outcome
    (never an unattended block on a hung child)."""
    home = bare_ledger(tmp_path)
    runtime_dir = tmp_path / "runtime"
    cache_home = tmp_path / "cache"
    runtime_dir.mkdir()
    cache_home.mkdir()
    port = _free_port()

    env = dict(os.environ)
    env["SELF_LEARN_HOME"] = str(home)
    env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    env["XDG_CACHE_HOME"] = str(cache_home)
    env["SELF_LEARN_UI_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "self_learn_ui.cli", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(proc, port, _STARTUP_TIMEOUT_S)
        token_path = runtime_dir / "self-learn" / "ui-token"
        _wait_for_file(token_path, _STARTUP_TIMEOUT_S)
        token = token_path.read_text(encoding="utf-8").strip()
        assert token, "token file was written but empty"
        assert oct(token_path.stat().st_mode)[-3:] == "600"
        yield f"http://127.0.0.1:{port}", token
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail(
                "self-learn-ui serve did not shut down cleanly within "
                f"{_SHUTDOWN_TIMEOUT_S}s of SIGTERM — had to SIGKILL"
            )


def test_serve_e2e_token_flow_and_csp(serve_process: tuple[str, str]) -> None:
    base_url, token = serve_process

    with httpx.Client(follow_redirects=False, timeout=5.0) as client:
        # Pre-auth: no cookie yet -> 403, but the CSP header is on EVERY
        # response, error pages included (09 §3 pin).
        forbidden = client.get(base_url + "/")
        assert forbidden.status_code == 403
        assert forbidden.headers.get("Content-Security-Policy") == CSP_HEADER_VALUE
        assert "self-learn-ui-open" in forbidden.text

        # Token-URL -> cookie -> 303 redirect to the clean path.
        minted = client.get(base_url + "/", params={"token": token})
        assert minted.status_code == 303
        assert minted.headers["location"] == "/"
        assert TOKEN_COOKIE_NAME in client.cookies

        # Authenticated GET on the clean URL: 200 + the pinned CSP header.
        home_page = client.get(base_url + "/")
        assert home_page.status_code == 200
        assert home_page.headers.get("Content-Security-Policy") == CSP_HEADER_VALUE
        assert "text/html" in home_page.headers.get("content-type", "")


def test_serve_rejects_wrong_host_header(serve_process: tuple[str, str]) -> None:
    """DNS-rebinding guard (09 §3) holds for the REAL running server, not
    just the in-process httpx ASGI transport test_middleware.py already
    covers."""
    base_url, _token = serve_process
    port = base_url.rsplit(":", 1)[1]
    with httpx.Client(follow_redirects=False, timeout=5.0) as client:
        r = client.get(
            base_url + "/",
            headers={"Host": f"evil.example:{port}"},
        )
        assert r.status_code == 403
