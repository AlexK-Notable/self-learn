"""Argument parser and dispatch for ``self-learn overseer`` (O-3)."""

from __future__ import annotations

import argparse
import json
import sys

from ..ledger import resolve_home
from . import run as runner


def add_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser("overseer", help="run or inspect the weekly overseer")
    commands = parser.add_subparsers(dest="overseer_command", required=True)
    run_parser = commands.add_parser("run", help="run the two-phase examination")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--json", action="store_true")
    status_parser = commands.add_parser("status", help="show the last overseer run")
    status_parser.add_argument("--json", action="store_true")
    report_parser = commands.add_parser("report", help="print an overseer report")
    report_parser.add_argument("--date")
    parser.set_defaults(_overseer_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    home = resolve_home()
    command = args.overseer_command
    try:
        if command == "run":
            result = runner.run(home, dry_run=args.dry_run)
            if args.json:
                print(json.dumps(result.to_json(), sort_keys=True))
            elif result.status == "disabled":
                print("self-learn overseer: disabled")
            else:
                print(
                    f"self-learn overseer: {result.status}; "
                    f"examined={len(result.examined)} applied={result.applied} refused={result.refused}"
                )
            return result.code
        if command == "status":
            payload = runner.status(home)
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            elif payload["last"] is None:
                print("self-learn overseer: no runs")
            else:
                row = payload["last"]
                print(f"self-learn overseer: {row.get('status', 'unknown')} at {row.get('at', 'unknown')}")
            return 0
        print(runner.report(home, date=args.date), end="")
        return 0
    except runner.OverseerError as exc:
        print(f"self-learn: {exc}", file=sys.stderr)
        return 1
