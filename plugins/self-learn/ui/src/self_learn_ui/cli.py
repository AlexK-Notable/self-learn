"""Entry point for the ``self-learn-ui`` console script.

Reached through ``plugins/self-learn/scripts/self-learn-ui`` (the bash
wrapper — 10 §1's Code layout row). At U1 (scaffold), ``--help`` works
fully; ``serve`` parses env and reports "not implemented until U3" (or the
09 §4.1 pinned engine-not-built message when ``SELF_LEARN_PANE_ENGINE=cli``)
and exits non-zero — no routes, no server, no ledger model yet.
"""

from __future__ import annotations

import argparse
import sys

from .env import EngineNotBuiltError, EnvError, load_env

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


def _serve() -> int:
    try:
        load_env()
    except EngineNotBuiltError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except EnvError as exc:
        print(f"self-learn-ui: {exc}", file=sys.stderr)
        return 2
    # Scaffold only (10 §3 task U1) — routes/ledger/engine land at U2-U5.
    print(f"{PROG} serve: not implemented until U3", file=sys.stderr)
    return 1


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
