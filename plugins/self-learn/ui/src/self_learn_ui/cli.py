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
    from .middleware import mint_token, write_token_file

    token = mint_token()
    write_token_file(token)
    app = create_app(env=env, token=token)
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
    # uvicorn receives a shutdown signal (SIGTERM/SIGINT), exactly what
    # systemd's ExecStart + Restart=on-failure expects to manage.
    # access_log=False is load-bearing (interim-review MAJOR, 2026-07-17):
    # the deep-link arrives as `GET /?token=<secret>` and uvicorn's access
    # logger records the full request line BEFORE the 303 strips it — under
    # the systemd unit that lands in the journal, persisting every minted
    # token. This localhost single-user service has no operational need for
    # per-request access logs; the app keeps its own ui.log.
    uvicorn.run(app, host="127.0.0.1", port=env.ui_port, access_log=False)
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
