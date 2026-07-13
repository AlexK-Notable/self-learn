"""self-learn CLI — argparse skeleton (T1) + real `status`/`list` (T3) +
`teach` (T5) + resolution verbs / `push` / `sentinel` (T7 functions, wired
at T8) + `import`/`prune-memory` (T9 modules, wired at T11) +
`proposal validate` and the real `--selftest` (T11; the validate verb is
08 §7.1's pull-forward from T13 — all its logic already existed).

`status` and `list` compute over the shared queue/eligibility functions in
ledger_ops (08 §1 `--json`-stubs pin incl. the G-3 hardening; §7.1 step 2 /
P2-4). `teach` lives in :mod:`self_learn.teach`; the verbs are thin
wrappers over :mod:`self_learn.verbs`; validate + selftest live in
:mod:`self_learn.selfcheck`.

Verb exit codes (T7's mapping, surfaced here): 0 success · a verb refusal
carries its exception's ``exit_code`` (``VerbError`` 1;
``DestinationNotBuilt`` 2; ``SecretRefusal`` 1 — P2-7 refusal) · unknown /
malformed record id (``LedgerOpsError``) 2 · a push failure after a kept
commit exits with the push result's code (``EXIT_PUSH_FAILED`` 3,
``EXIT_REBASE_CONFLICT`` 4 — gitops). `proposal validate` has its own
pinned trio (P2-8): 0 valid+stamped · 1 schema-invalid · 2 scan hit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from . import selfcheck, sentinel, verbs
from .chezmoi import ChezmoiAbort, ChezmoiError
from .compilers import CompileError
from .import_backlog import import_backlog
from .import_common import ImporterError
from .import_memory import import_memory, prune_memory
from .ledger import discover_buckets, resolve_home
from .ledger_ops import LedgerOpsError, list_items, status_infos, unparseable_pending
from .teach import add_teach_parser, run_teach

EXIT_OK = 0
EXIT_USAGE = 2

#: The auto-memory location for THIS repo (08 §3 T9/T11; MEMORY.md + topic
#: files). Env-overridable; tests always override — the real dir is never
#: resolved under pytest.
DEFAULT_MEMORY_DIR = "~/.claude/projects/-home-komi-repos-claude-skills/memory"


def default_memory_dir() -> Path:
    """`import --memory` / `prune-memory` dir default: env override first."""
    env = os.environ.get("SELF_LEARN_MEMORY_DIR")
    return Path(env if env else DEFAULT_MEMORY_DIR).expanduser()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="self-learn",
        description="Git-backed lesson ledger: capture, triage, route (M1).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run installation self-checks (loud PASS/FAIL, non-zero on FAIL)",
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

    add_teach_parser(sub)

    def _verb(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--note", metavar="TEXT", help="resolution note → commit body")
        p.add_argument(
            "--no-push",
            action="store_true",
            dest="no_push",
            help="commit exactly as pinned, skip only the push",
        )
        return p

    route = _verb("route", "route a pending record into canon")
    route.add_argument("id", metavar="ID")
    route.add_argument(
        "--dest",
        metavar="TARGET",
        help="override the proposal: skill-md | claude-md | reference[:<file>]",
    )

    reject = _verb("reject", "reject a pending record")
    reject.add_argument("id", metavar="ID")

    defer = _verb("defer", "defer a pending record (default +30 d)")
    defer.add_argument("id", metavar="ID")
    defer.add_argument("--until", metavar="YYYY-MM-DD", help="explicit defer date")

    graduate = _verb("graduate", "mark a lesson graduated into authored canon")
    graduate.add_argument("id", metavar="ID")

    supersede = _verb("supersede", "mark OLD superseded by NEW (metadata only)")
    supersede.add_argument("old_id", metavar="OLD_ID")
    supersede.add_argument("new_id", metavar="NEW_ID")

    sub.add_parser("push", help="publish pending local commits (pinned retry)")

    sentinel_p = sub.add_parser(
        "sentinel", help="autosync-pause sentinel: hold | heartbeat | release"
    )
    sentinel_p.add_argument("action", choices=("hold", "heartbeat", "release"))

    imp = sub.add_parser(
        "import", help="one-shot importers: --backlog <skill> | --memory [<dir>]"
    )
    src = imp.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--backlog",
        metavar="SKILL",
        help="mine the skill's references/GOTCHAS.journal.md (journal ONLY)",
    )
    src.add_argument(
        "--memory",
        nargs="?",
        const="",
        metavar="DIR",
        help=f"import auto-memory topic files (default: {DEFAULT_MEMORY_DIR})",
    )

    prune = sub.add_parser(
        "prune-memory",
        help="S-13 sweep: remove memory files whose records reached a terminal status",
    )
    prune.add_argument("--dry-run", action="store_true", dest="dry_run")
    prune.add_argument("dir", nargs="?", default=None, metavar="DIR")

    proposal = sub.add_parser("proposal", help="proposal-sibling operations")
    proposal_sub = proposal.add_subparsers(dest="proposal_command", metavar="<verb>")
    validate = proposal_sub.add_parser(
        "validate",
        help="scan + schema-validate + stamp one record's proposal (0/1/2)",
    )
    validate.add_argument("id", metavar="ID")

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


# ------------------------------------------------------- verb wiring (T8)


def _push_note(result: verbs.VerbResult) -> str:
    if result.push is None:
        return "not pushed — --no-push"
    if result.push.ok:
        return "pushed"
    return "PUSH FAILED — commit kept; run `self-learn push`"


def _finish_verb(result: verbs.VerbResult, target: str) -> int:
    """One-line success summary: id, action, target, short sha, push state.
    Exit 0, or the push result's distinct code when the push failed."""
    print(
        f"{result.action} {result.record_id} → {target} "
        f"@ {result.commit_sha[:7]} ({_push_note(result)})"
    )
    if result.push is not None and not result.push.ok:
        return result.push.exit_code
    return EXIT_OK


def _routed_destination(result: verbs.VerbResult) -> str:
    # The pinned commit subject is "self-learn: route lrn-… → <target>…";
    # the target after the arrow is authoritative (proposal or --dest).
    return result.commit_message.split("→", 1)[1].strip().split(" ")[0]


def _cmd_verb(args: argparse.Namespace) -> int:
    home = resolve_home()
    try:
        if args.command == "route":
            result = verbs.route(
                home,
                args.id,
                dest=args.dest,
                note=args.note,
                no_push=args.no_push,
            )
            return _finish_verb(result, _routed_destination(result))
        if args.command == "reject":
            result = verbs.reject(home, args.id, note=args.note, no_push=args.no_push)
            return _finish_verb(result, "rejected")
        if args.command == "defer":
            until = None
            if args.until is not None:
                try:
                    until = date.fromisoformat(args.until)
                except ValueError:
                    print(
                        f"self-learn defer: --until must be YYYY-MM-DD, "
                        f"got {args.until!r}",
                        file=sys.stderr,
                    )
                    return EXIT_USAGE
            result = verbs.defer(
                home, args.id, until=until, note=args.note, no_push=args.no_push
            )
            # pinned subject: "self-learn: defer lrn-… until <date>"
            until_str = result.commit_message.rsplit(" until ", 1)[1]
            return _finish_verb(result, f"deferred until {until_str}")
        if args.command == "graduate":
            result = verbs.graduate(
                home, args.id, note=args.note, no_push=args.no_push
            )
            return _finish_verb(result, "canon")
        if args.command == "supersede":
            result = verbs.supersede(
                home,
                args.old_id,
                args.new_id,
                note=args.note,
                no_push=args.no_push,
            )
            return _finish_verb(result, args.new_id)
    except verbs.VerbError as exc:  # incl. SecretRefusal, DestinationNotBuilt
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return exc.exit_code
    except LedgerOpsError as exc:  # unknown/malformed id, proposal trouble
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (CompileError, ChezmoiAbort, ChezmoiError) as exc:
        # broken markers / user-scope chezmoi aborts: refused, nothing lost
        print(f"self-learn {args.command}: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled verb {args.command!r}")  # pragma: no cover


def _cmd_push() -> int:
    result = verbs.push_pending(resolve_home())
    if result.ok:
        print("push: ok" + (" (after rebase-retry)" if result.retried else ""))
        return EXIT_OK
    # gitops already printed the loud warning; exit with the distinct code.
    return result.exit_code


def _cmd_sentinel(action: str) -> int:
    path = sentinel.sentinel_path()
    if action == "hold":
        hold = sentinel.hold()
        if hold.owned:
            print(f"sentinel held: {path}")
        else:
            print(f"sentinel already held (live) — left in place: {path}")
        return EXIT_OK
    if action == "heartbeat":
        if sentinel.heartbeat():
            print(f"sentinel heartbeat: {path}")
        else:
            print("sentinel heartbeat: no live sentinel")
        return EXIT_OK
    # release: the CLI form releases across invocations (the slash review's
    # batch hold spans processes), so it deletes whatever sentinel exists —
    # in-process ownership scoping belongs to the verbs' self-holds.
    try:
        path.unlink()
        print(f"sentinel released: {path}")
    except FileNotFoundError:
        print("sentinel release: none held")
    return EXIT_OK


def _cmd_import(args: argparse.Namespace) -> int:
    home = resolve_home()
    try:
        if args.backlog is not None:
            report = import_backlog(home, args.backlog)
        else:
            memory_dir = (
                Path(args.memory).expanduser() if args.memory else default_memory_dir()
            )
            report = import_memory(home, memory_dir)
    except ImporterError as exc:  # missing journal / memory dir
        print(f"self-learn import: {exc}", file=sys.stderr)
        return 1
    except LedgerOpsError as exc:  # unknown skill bucket
        print(f"self-learn import: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(report.summary())
    return EXIT_OK


def _cmd_prune_memory(args: argparse.Namespace) -> int:
    home = resolve_home()
    memory_dir = Path(args.dir).expanduser() if args.dir else default_memory_dir()
    report = prune_memory(home, memory_dir, dry_run=args.dry_run)
    print(report.summary())
    return EXIT_OK


def _cmd_proposal(args: argparse.Namespace) -> int:
    if args.proposal_command != "validate":
        print("usage: self-learn proposal validate <id>", file=sys.stderr)
        return EXIT_USAGE
    try:
        return selfcheck.proposal_validate(resolve_home(), args.id)
    except LedgerOpsError as exc:  # unknown/malformed record id: usage, not P2-8
        print(f"self-learn proposal validate: {exc}", file=sys.stderr)
        return EXIT_USAGE


VERB_COMMANDS = frozenset({"route", "reject", "defer", "graduate", "supersede"})


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args, _extra = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse error (e.g. bad choice, missing group)
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    if args.selftest:
        return selfcheck.run_selftest(resolve_home())

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    if _extra:
        print(
            f"self-learn {args.command}: unrecognized arguments: {' '.join(_extra)}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.command == "status":
        return _cmd_status(as_json=args.as_json)

    if args.command == "list":
        return _cmd_list(
            as_json=args.as_json, include_deferred=args.include_deferred
        )

    if args.command == "teach":
        return run_teach(args)

    if args.command in VERB_COMMANDS:
        return _cmd_verb(args)

    if args.command == "push":
        return _cmd_push()

    if args.command == "sentinel":
        return _cmd_sentinel(args.action)

    if args.command == "import":
        return _cmd_import(args)

    if args.command == "prune-memory":
        return _cmd_prune_memory(args)

    if args.command == "proposal":
        return _cmd_proposal(args)

    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


def entrypoint() -> None:  # console-script target
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
