"""Entry point for the ``self-learn-ui`` console script.

Reached through ``plugins/self-learn/scripts/self-learn-ui`` (the bash
wrapper — 10 §1's Code layout row) and, in production, by
``systemd/self-learn-ui.service``'s ``ExecStart`` running that wrapper
with the ``serve`` subcommand (10 §1 Service row). ``--help`` and env
parsing were wired at U1; ``serve`` itself was a stub through U3
("not implemented until U3") and is wired for real at U4 (this module's
task): it mints the per-start bearer token, writes it 0600
(:func:`self_learn_ui.middleware.write_token_file`), builds the real ASGI
app (:func:`self_learn_ui.app.create_app`, whose own default runner is
now :class:`self_learn_ui.runner.RealRunner` — U4), and runs it under
uvicorn on ``127.0.0.1:$SELF_LEARN_UI_PORT`` in the FOREGROUND (09 §3:
"a ``systemd --user`` service"; ``uvicorn.run`` blocks until the process
receives a shutdown signal — exactly what systemd's ``Restart=on-failure``
expects to manage). ``uvicorn`` is imported lazily, inside :func:`_serve`,
so ``--help``/other subcommands never pay its import cost and so tests
can monkeypatch ``uvicorn.run`` without importing this module's globals
eagerly.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from .env import EngineNotBuiltError, EnvConfig, EnvError, load_env

if TYPE_CHECKING:
    from fastapi import FastAPI

PROG = "self-learn-ui"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="self-learn adjudication surface — localhost web UI (G-3).",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "serve",
        help="Run the adjudication server in the foreground (what systemd runs).",
    )
    return parser


def _build_server_app(env: EnvConfig) -> tuple["FastAPI", str]:
    """Mint + write the per-start token, build the real ASGI app. Split
    out of :func:`_serve` so a test can call it directly (no uvicorn, no
    blocking) to assert the app/token side without spawning a server —
    the actual "does it serve HTTP" contract is covered end-to-end in
    ``tests/test_serve.py`` (a real subprocess on an ephemeral port, the
    same process boundary systemd's ``ExecStart`` uses)."""
    from .app import create_app
    from .idle import resolve_idle_window
    from .middleware import mint_token, write_token_file

    token = mint_token()
    write_token_file(token)
    # Y-14 (09 §3, mechanism corrected at the U13 live trial): the idle
    # exit callback sets uvicorn's own ``should_exit`` flag — NO signal.
    # The first-drafted SIGTERM-to-self died by re-raised signal (exit
    # 143): uvicorn's capture_signals restores default handlers and
    # re-raises every captured signal AFTER graceful shutdown, so the
    # process never returns 0 and Restart=on-failure RESTARTS it — the
    # exact opposite of stay-down. ``should_exit`` drives the identical
    # graceful shutdown path with a genuine return, so ``_serve``
    # really exits 0. The holder is filled by ``_serve`` once the
    # Server object exists; an unfilled holder no-ops (tests, callers
    # that never run uvicorn).
    exit_holder: dict = {}

    def request_idle_exit() -> None:
        server = exit_holder.get("server")
        if server is None:
            # Unreachable under _serve (holder filled before run()); an
            # embedder who armed the monitor without running uvicorn
            # would otherwise get "silently disarmed after the first
            # idle window" — the monitor believes it signaled and stops
            # sampling (delta NIT: make that visible).
            from . import uilog

            uilog.log(
                "idle monitor: exit requested but no uvicorn server is "
                "wired — nothing to stop (embedding without _serve?)"
            )
            return
        server.should_exit = True

    app = create_app(
        env=env,
        token=token,
        idle_exit_seconds=resolve_idle_window(env),
        idle_exit_callback=request_idle_exit,
    )
    app.state.idle_exit_holder = exit_holder
    app.state.request_idle_exit = request_idle_exit
    return app, token


def _serve() -> int:
    try:
        env = load_env()
    except EngineNotBuiltError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except EnvError as exc:
        print(f"self-learn-ui: {exc}", file=sys.stderr)
        return 2

    import uvicorn

    app, _token = _build_server_app(env)
    # Foreground, blocking (09 §3 / 10 §1 Service row) — returns once
    # uvicorn receives a shutdown signal (SIGTERM/SIGINT) or the Y-14
    # idle monitor sets ``should_exit`` (the explicit Server object
    # exists exactly so the monitor has that flag to set — see
    # _build_server_app; on idle exit this returns and we exit 0,
    # which Restart=on-failure reads as stay-down).
    # access_log=False is load-bearing (interim-review MAJOR, 2026-07-17):
    # the deep-link arrives as `GET /?token=<secret>` and uvicorn's access
    # logger records the full request line BEFORE the 303 strips it — under
    # the systemd unit that lands in the journal, persisting every minted
    # token. This localhost single-user service has no operational need for
    # per-request access logs; the app keeps its own ui.log.
    config = uvicorn.Config(app, host="127.0.0.1", port=env.ui_port, access_log=False)
    server = uvicorn.Server(config)
    app.state.idle_exit_holder["server"] = server
    server.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve()
    parser.print_help()
    return 0


def entrypoint() -> None:  # console-script target
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
