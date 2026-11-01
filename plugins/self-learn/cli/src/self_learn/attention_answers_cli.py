"""The answers lane's ``self-learn attention`` verbs (attention round,
design r2 §4.6), registered from ``attention_cli``'s reserved block:

    self-learn attention answer <id> [--option OPT] [--text-file PATH|-] [--draft DRF]
                                     [--ref transcript:<s>#L<n>] [--session ID] [--confirm]
                                     [--note TEXT] [--json]
        0 recorded | 2 unknown or closed id | 3 refused downstream | 10 held | 64 usage
    self-learn attention undo <id> [--redo] [--note TEXT]
        0 | 2 unknown id | 3 no inverse / inverse refused | 10 held
    self-learn attention run <id> [--login]
        0 launched | 2 unknown id | 3 not approved | 4 would spend money | 5 no terminal
        | 64 agent shell
    self-learn attention fix <id> --option OPT
        0 done | 2 unknown id | 3 no such option, or the command failed | 64 agent shell
    self-learn attention claim <id> --session ID
        0 | 2 not approved | 3 claimed by another session
    self-learn attention done <id> --note TEXT --session ID [--failed]
        0 | 2 not approved | 3 no live claim by this session | 64 no note | 10 held

And ``self-learn case refreeze <case-id> --keep|--restore [--note TEXT]``
(:func:`cmd_refreeze`, called from ``cli._cmd_case``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import attention_answers as answers
from . import cases, gitops, intents, settings, statements
from .attention_answers import AnswerError

COMMANDS = frozenset({"answer", "undo", "run", "fix", "claim", "done"})


def add_parsers(commands) -> None:
    answer_p = commands.add_parser(
        "answer", help="answer an inbox item: an option, your own words, or an agent's draft",
    )
    answer_p.add_argument("id", metavar="ID")
    answer_p.add_argument("--option", default=None, metavar="OPT")
    answer_p.add_argument("--text-file", dest="text_file", default=None, metavar="PATH|-")
    answer_p.add_argument("--draft", dest="draft_id", default=None, metavar="DRF")
    answer_p.add_argument("--ref", default=None, metavar="transcript:<session>#L<n>")
    answer_p.add_argument("--session", default=None, metavar="ID")
    answer_p.add_argument("--confirm", action="store_true")
    answer_p.add_argument("--note", default=None)
    answer_p.add_argument("--json", action="store_true", dest="as_json")

    undo_p = commands.add_parser("undo", help="the one-step inverse of a decided item")
    undo_p.add_argument("id", metavar="ID")
    undo_p.add_argument("--redo", action="store_true")
    undo_p.add_argument("--note", default=None)
    undo_p.add_argument("--no-push", action="store_true", dest="no_push")

    run_p = commands.add_parser(
        "run", help="open a terminal running a Claude Code session that carries out an approved change",
    )
    run_p.add_argument("id", metavar="ID")
    run_p.add_argument("--login", action="store_true",
                       help="open a terminal running claude to log in (a log-in item only)")

    fix_p = commands.add_parser("fix", help="a code item's own fix (Restart self-learn)")
    fix_p.add_argument("id", metavar="ID")
    fix_p.add_argument("--option", required=True, metavar="OPT")

    claim_p = commands.add_parser("claim", help="the carrying-out session claims an approved change")
    claim_p.add_argument("id", metavar="ID")
    claim_p.add_argument("--session", required=True, metavar="ID")

    done_p = commands.add_parser("done", help="the carrying-out session reports it done (or failed)")
    done_p.add_argument("id", metavar="ID")
    done_p.add_argument("--note", default=None)
    done_p.add_argument("--session", required=True, metavar="ID")
    done_p.add_argument("--failed", action="store_true")


def _read_text(path: str | None) -> str | None:
    if path is None:
        return None
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def dispatch(home: Path, args: argparse.Namespace) -> int:
    command = args.attention_command
    name = f"self-learn attention {command}"
    try:
        if command == "answer":
            return _answer(home, args)
        if command == "undo":
            did = answers.undo(home, args.id, redo=args.redo, note=args.note, no_push=args.no_push)
            print(f"attention {'redo' if args.redo else 'undo'}: {did}")
            return answers.EXIT_OK
        if command == "run":
            result = answers.run(home, args.id, login=args.login)
            print(result.message, file=sys.stdout if result.exit == answers.EXIT_OK else sys.stderr)
            return result.exit
        if command == "fix":
            print(answers.fix(home, args.id, args.option))
            return answers.EXIT_OK
        if command == "claim":
            item = answers.claim(home, args.id, args.session)
            print(f"attention claim: {item['id']} is yours (session {args.session})")
            return answers.EXIT_OK
        if command == "done":
            outcome = answers.done(home, args.id, session=args.session, note=args.note,
                                   failed=args.failed)
            print(f"attention done: {outcome} ({'failed' if args.failed else 'done'})")
            return answers.EXIT_OK
    except AnswerError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return exc.exit_code
    except intents.LedgerStoppedError as exc:
        print(str(exc), file=sys.stderr)
        return answers.EXIT_HELD
    except statements.StatementError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return answers.EXIT_USAGE
    except gitops.HalfWrittenError as exc:
        print(f"{name}: written but not committed: {exc}", file=sys.stderr)
        return gitops.EXIT_HALF_WRITTEN
    except gitops.GitOpsError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return gitops.EXIT_GIT_FAILED
    except (cases.CaseError, settings.SettingsError) as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return getattr(exc, "exit_code", answers.EXIT_FAILED)
    except OSError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return answers.EXIT_FAILED
    print(f"{name}: unknown command", file=sys.stderr)
    return answers.EXIT_USAGE


def _answer(home: Path, args: argparse.Namespace) -> int:
    try:
        text = _read_text(args.text_file)
    except OSError as exc:
        print(f"self-learn attention answer: --text-file could not be read: {exc}", file=sys.stderr)
        return answers.EXIT_USAGE
    result = answers.answer(
        home, args.id, option=args.option, text=text, draft_id=args.draft_id, ref=args.ref,
        session=args.session, confirm=args.confirm, note=args.note,
    )
    if args.as_json:
        print(json.dumps(result.to_json(), ensure_ascii=False))
    else:
        print(f"attention answer: recorded {result.recorded_as} on {result.item} "
              f"(state: {result.state})")
        if result.registration:
            print(f"  {result.registration}")
        if result.run is not None:
            print(f"  {result.run.get('message')}")
    for warning in result.warnings:
        print(f"self-learn attention answer: {warning}", file=sys.stderr)
    return answers.EXIT_OK


def add_refreeze_parser(case_sub) -> None:
    """``case refreeze <case-id> --keep|--restore [--note TEXT]``."""
    refreeze_p = case_sub.add_parser(
        "refreeze", help="answer a hand-edited case: keep the edit, or restore the decided text",
    )
    refreeze_p.add_argument("id", metavar="case-...")
    which = refreeze_p.add_mutually_exclusive_group(required=True)
    which.add_argument("--keep", action="store_true")
    which.add_argument("--restore", action="store_true")
    refreeze_p.add_argument("--note", default=None)


def cmd_refreeze(home: Path, args: argparse.Namespace) -> int:
    """§3.4.8: refused from an agent's shell (the person's own click: only
    the person who edited the file knows whether the edit was meant)."""
    if settings.agent_caller():
        print(
            "self-learn case refreeze: refused from an agent's shell: whether a hand edit of a "
            "case was meant is the person's own answer, in the inbox "
            f"(agent shell detected: {', '.join(settings.agent_caller_markers())})",
            file=sys.stderr,
        )
        return answers.EXIT_USAGE
    try:
        digest = cases.refreeze(home, args.id, keep=bool(args.keep), note=args.note)
    except cases.CaseError as exc:
        print(f"self-learn case refreeze: {exc}", file=sys.stderr)
        return exc.exit_code
    except intents.LedgerStoppedError as exc:
        print(str(exc), file=sys.stderr)
        return answers.EXIT_HELD
    except gitops.GitOpsError as exc:
        print(f"self-learn case refreeze: {exc}", file=sys.stderr)
        return gitops.EXIT_GIT_FAILED
    print(f"case refreeze → {args.id} ({'kept' if args.keep else 'restored'}; {digest[:12]})")
    return answers.EXIT_OK
