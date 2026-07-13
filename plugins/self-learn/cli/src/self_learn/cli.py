"""self-learn CLI — argparse skeleton (T1) + real `status`/`list` (T3).

Remaining subcommands land at their build-plan tasks; until then each stub
exits 2 with a pointer to the task that builds it. `status` and `list`
compute over the shared queue/eligibility functions in ledger_ops (08 §1
`--json`-stubs pin incl. the G-3 hardening; §7.1 step 2 / P2-4).
"""

from __future__ import annotations

import argparse
import json
import sys

from .ledger import discover_buckets, resolve_home
from .ledger_ops import list_items, status_infos, unparseable_pending

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

    list_p = sub.add_parser("list", help="list queued records")
    list_p.add_argument("--json", action="store_true", dest="as_json")
    list_p.add_argument(
        "--include-deferred",
        action="store_true",
        dest="include_deferred",
        help="superset: also show records whose deferred_until is in the future",
    )

    for name, task in STUB_TASKS.items():
        sub.add_parser(name, help=f"not built until {task}", add_help=False)

    return parser


def _warn_unparseable(home) -> None:
    """Unparseable pending files are excluded from the queue — never
    silently: name each one on stderr."""
    for bucket in discover_buckets(home):
        for path in unparseable_pending(bucket):
            print(
                f"self-learn: warning: skipping unparseable record {path}",
                file=sys.stderr,
            )


def _cmd_status(as_json: bool) -> int:
    home = resolve_home()
    _warn_unparseable(home)
    infos = status_infos(home)
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
        print(
            f"  {i['bucket']} ({i['scope']}): {i['pending']} pending, "
            f"{i['unanalyzed']} unanalyzed{age}"
        )
    return EXIT_OK


def _proposal_cell(item: dict) -> str:
    if not item["has_proposal"]:
        return "-"
    return "fresh" if item["proposal_fresh"] else "stale"


def _cmd_list(as_json: bool, include_deferred: bool) -> int:
    home = resolve_home()
    _warn_unparseable(home)
    items = list_items(home, include_deferred=include_deferred)

    if as_json:
        print(json.dumps(items))
        return EXIT_OK

    if not items:
        print("self-learn: 0 records")
        return EXIT_OK

    print(
        f"{'ID':<13} {'AGE':>4} {'STATUS':<9} {'TYPE':<9} "
        f"{'PROPOSAL':<8} {'SCOPE':<22} TITLE"
    )
    for i in items:
        print(
            f"{i['id']:<13} {str(i['age_days']) + 'd':>4} {i['status']:<9} "
            f"{i['type']:<9} {_proposal_cell(i):<8} {i['scope']:<22} {i['title']}"
        )
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

    if args.command == "list":
        return _cmd_list(
            as_json=args.as_json, include_deferred=args.include_deferred
        )

    task = STUB_TASKS[args.command]
    print(f"self-learn {args.command}: not built until {task}", file=sys.stderr)
    return EXIT_USAGE


def entrypoint() -> None:  # console-script target
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
