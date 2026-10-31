"""Argument parser and dispatch for ``self-learn overseer`` (O-3)."""

from __future__ import annotations

import argparse
import json
import sys

from ..ledger import resolve_home
from . import conversation
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
    commands.add_parser("open", help="show every open question from the latest report")
    respond_parser = commands.add_parser(
        "respond",
        help="answer or decline a displayed question, or veto or retire a skill it showed",
    )
    target = respond_parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--proposition",
        help="the question's id as `overseer open` showed it: a reading's "
        "um-<4 hex>@r<revision>, or an ask's q-<slug>",
    )
    target.add_argument(
        "--veto-skill", metavar="NAME",
        help="ban a skill's name for ever: a skill self-learn built, or a draft `overseer open` "
        "showed (needs --text and --scope)",
    )
    target.add_argument(
        "--retire-skill", metavar="NAME",
        help="ask the overseer to retire a skill self-learn built "
        "(needs --text and --scope)",
    )
    reply = respond_parser.add_mutually_exclusive_group(required=True)
    reply.add_argument(
        "--text",
        help="your answer, in your own words. For a question that says a plain "
        "yes registers a host, typing yes registers it in this command "
        "(from your own terminal; an agent's shell registers only when its own session "
        "shows the person typed the yes)",
    )
    reply.add_argument("--decline", action="store_true")
    respond_parser.add_argument("--scope")
    respond_parser.add_argument("--as-asked")
    respond_parser.add_argument(
        "--session", metavar="ID",
        help="an agent's shell only, and only where $CLAUDE_CODE_SESSION_ID is not set "
        "(it is the default): the session the person typed their plain yes in, so a "
        "host registration the question carries can be checked against that "
        "transcript (the last thing they typed there must be the yes). A session "
        "other than $CLAUDE_CODE_SESSION_ID is refused",
    )
    parser.set_defaults(_overseer_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    home = resolve_home()
    command = args.overseer_command
    try:
        if command == "run":
            # A hand-typed run is MANUAL (2026-09-24, the user's words:
            # "user initiated runs don't count toward the weekly limit").
            result = runner.run(home, dry_run=args.dry_run, manual=True)
            if args.json:
                print(json.dumps(result.to_json(), sort_keys=True))
            elif result.status == "disabled":
                print("self-learn overseer: disabled")
            elif result.status == "held-week-done":
                print("self-learn overseer: held — this week is already done")
            else:
                print(
                    f"self-learn overseer: {result.status_text}; "
                    f"examined={len(result.examined)} applied={result.applied} refused={result.refused}"
                )
                for line in result.recompile_skipped:
                    # 2026-09-28: the post-run recompile's skips, one pass.
                    print(f"self-learn overseer: recompile skipped {line}")
            return result.code
        if command == "status":
            payload = runner.status(home)
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            elif payload["last"] is None:
                if payload.get("last_run_at"):
                    print(
                        "self-learn overseer: committed coverage; "
                        f"last run {payload['last_run_at']}"
                    )
                else:
                    print("self-learn overseer: no runs")
            else:
                row = payload["last"]
                print(f"self-learn overseer: {row.get('status', 'unknown')} at {row.get('at', 'unknown')}")
            return 0
        if command == "open":
            conversation.open_questions(home)
            return 0
        if command == "respond":
            if args.veto_skill is not None or args.retire_skill is not None:
                if args.decline:
                    raise conversation.ConversationUsageError(
                        "overseer respond: --decline answers a question; it does not apply to "
                        "--veto-skill or --retire-skill"
                    )
                vetoing = args.veto_skill is not None
                skill = args.veto_skill if vetoing else args.retire_skill
                result = conversation.respond_skill(
                    home,
                    action="veto" if vetoing else "retire",
                    name=skill,
                    scope=args.scope or "",
                    text=args.text,
                    as_asked=args.as_asked,
                )
                if vetoing:
                    print(
                        f"self-learn overseer: recorded {result.statement_id}; the name {skill} "
                        "is vetoed for ever: no skill is written under it again, and a live skill "
                        "under it is renamed by the next overseer run that writes skills, or at "
                        "once by you with self-learn skill rename"
                    )
                else:
                    print(
                        f"self-learn overseer: recorded {result.statement_id}; retirement of "
                        f"{skill} is asked of the overseer; the request stays until the skill is retired"
                    )
                return 0
            if args.decline:
                conversation.decline(home, proposition=args.proposition)
                print(f"self-learn overseer: declined {args.proposition}")
            else:
                result = conversation.respond(
                    home,
                    proposition=args.proposition,
                    scope=args.scope or "",
                    text=args.text,
                    as_asked=args.as_asked,
                    session=args.session,
                )
                print(
                    f"self-learn overseer: recorded {result.statement_id}; "
                    f"reconsidered={len(result.observed_cases)}"
                )
                if result.registration is not None:
                    print(f"self-learn overseer: {result.registration}")
            return 0
        print(runner.report(home, date=args.date), end="")
        return 0
    except (runner.OverseerError, conversation.ConversationError) as exc:
        print(f"self-learn: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 1
