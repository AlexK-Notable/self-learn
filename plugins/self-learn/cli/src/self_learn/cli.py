"""self-learn CLI — argparse skeleton (T1).

Real subcommands land at their build-plan tasks; until then each stub exits 2
with a pointer to the task that builds it. ``status`` is real (zero-state +
--json per the §1 M1-minimal shape); its pending counting is the T1 stub in
ledger.py (T3 owns queue semantics).
"""

from __future__ import annotations

import argparse
import json
import sys

from .ledger import discover_buckets, resolve_home

# subcommand -> build-plan task that implements it (08-build-plan.md §3/§7.2)
STUB_TASKS: dict[str, str] = {
    "teach": "T5",
    "route": "T7",
    "reject": "T7",
    "defer": "T7",
    "graduate": "T7",
    "supersede": "T7",
    "push": "T7",
    "sentinel": "T7",
    "import": "T9",
    "proposal": "T13",
    "list": "T3",
}

EXIT_OK = 0
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="self-learn",
        description="Git-backed lesson ledger: capture, triage, route (M1).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run installation self-checks (built at T11)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    status = sub.add_parser("status", help="show bucket/pending overview")
    status.add_argument("--json", action="store_true", dest="as_json")

    for name, task in STUB_TASKS.items():
        sub.add_parser(name, help=f"not built until {task}", add_help=False)

    return parser


def _cmd_status(as_json: bool) -> int:
    buckets = discover_buckets(resolve_home())
    infos = [
        {
            "bucket": b.name,
            "scope": b.scope,
            "pending": b.pending_count(),
            "oldest_days": b.oldest_days(),
        }
        for b in buckets
    ]
    total_pending = sum(i["pending"] for i in infos)

    if as_json:
        payload = {
            "buckets": infos,
            "total_pending": total_pending,
            "worker_last_run": None,
        }
        print(json.dumps(payload))
        return EXIT_OK

    if not infos:
        print("self-learn: no buckets, 0 pending")
        return EXIT_OK

    plural = "s" if len(infos) != 1 else ""
    print(f"self-learn: {total_pending} pending across {len(infos)} bucket{plural}")
    for i in infos:
        age = "" if i["oldest_days"] is None else f", oldest {i['oldest_days']}d"
        print(f"  {i['bucket']} ({i['scope']}): {i['pending']} pending{age}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # Stub subparsers take no options yet; swallow any extra args they were
    # given rather than erroring before the "not built" message can print.
    args, _extra = parser.parse_known_args(argv)

    if args.selftest:
        print("selftest: not built until T11")
        return EXIT_OK

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    if args.command == "status":
        return _cmd_status(as_json=args.as_json)

    task = STUB_TASKS[args.command]
    print(f"self-learn {args.command}: not built until {task}", file=sys.stderr)
    return EXIT_USAGE


def entrypoint() -> None:  # console-script target
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
