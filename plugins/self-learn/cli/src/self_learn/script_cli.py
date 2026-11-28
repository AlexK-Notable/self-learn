"""Agent-available S-160 commands. There is deliberately no approve verb."""
import argparse
import json
import os
import sys
from pathlib import Path
from . import skill_scripts


def add_parser(commands):
    parser = commands.add_parser("script", help="draft local helpers; only a proven Fable review activates")
    subs = parser.add_subparsers(dest="script_command", required=True)
    subs.add_parser("list", help="all versions, states and approval evidence")
    show = subs.add_parser("show", help="held source and lifecycle evidence")
    show.add_argument("id")
    draft = subs.add_parser("draft", help="hold a draft; no network/deletion/overwrites/services/credential reads")
    draft.add_argument("skill")
    draft.add_argument("--file", required=True, type=Path)
    draft.add_argument("--name", required=True)
    draft.add_argument("--usage", required=True)
    draft.add_argument("--note", required=True)
    for verb in ("review", "deactivate", "activate"):
        sub = subs.add_parser(verb, help={"review": "run one fresh Fable review", "activate": "retry an existing exact approval; never approve", "deactivate": "quarantine the file and remove its usage entry"}[verb])
        sub.add_argument("id")
        sub.add_argument("--note", required=verb != "activate")
    if os.name == "nt":
        # Windows has no shebang or mode bits: this launcher verifies the
        # managed copy and runs it with its declared interpreter.
        run = subs.add_parser(
            "run", help="verify an active script's managed copy, then run it with its declared interpreter",
            usage="self-learn skill script run [--timeout SECONDS] [--stdin] SKILL/NAME [-- ARGS ...]",
            description="Options go before SKILL/NAME; everything after it (and after an optional --) is the script's.")
        run.add_argument("--timeout", type=float, default=skill_scripts.RUN_TIMEOUT,
                         help=f"stop the script after this many seconds (at most {skill_scripts.RUN_TIMEOUT:g})")
        run.add_argument("--stdin", action="store_true",
                         help="pass this command's standard input to the script (it reads EOF otherwise)")
        run.add_argument("script", metavar="SKILL/NAME")
        run.add_argument("args", nargs=argparse.REMAINDER)


def dispatch(home, args):
    try:
        command = args.script_command
        if command == "list":
            result = skill_scripts.listed(home)
        elif os.name == "nt" and command == "show":
            result = _show(home, args.id)
        elif command == "show":
            result = next((r for r in skill_scripts.listed(home) if r["id"] == args.id), None)
            if result is None:
                raise ValueError("unknown script id: " + args.id)
            result["script"] = skill_scripts._held(Path(home), result).read_text()
        elif command == "draft":
            from .skill_cli import default_by
            from .script_screen import CREDENTIAL
            if CREDENTIAL.search(str(args.file)) or CREDENTIAL.search(str(args.file.resolve())):
                raise ValueError("credentials: refusing credential source path")
            result = skill_scripts.draft(home, args.skill, text=args.file.read_bytes().decode("utf-8"), name=args.name, usage=args.usage, note=args.note, by=default_by())
        elif command == "review":
            result = skill_scripts.review(home, args.id, note=args.note)
        elif command == "activate":
            result = skill_scripts.activate(home, args.id)
        elif os.name == "nt" and command == "run":
            return _run(home, args)
        else:
            result = skill_scripts.deactivate(home, args.id, note=args.note)
        if os.name == "nt" and isinstance(result, dict) and command in ("review", "activate"):
            result = {**result, "interpreter": skill_scripts.interpreter(result)}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"self-learn skill script: {exc}", file=sys.stderr)
        return 1


def _run(home, args):
    """Windows only. The child's exit status is the command's."""
    # argparse has already consumed the separator; every remaining word,
    # including a literal "--", belongs to the script.
    data = None
    finished = skill_scripts.run(home, args.script, list(args.args), timeout=args.timeout, stdin=data)
    out = sys.stdout.buffer
    out.write(finished.stdout)
    out.flush()
    buf = sys.stderr.buffer
    buf.write(finished.stderr)
    buf.flush()
    return finished.returncode


def _show(home, ident):
    """Windows only: the held source as its exact UTF-8 bytes, from a checked path."""
    home = Path(home)
    result = next((r for r in skill_scripts.listed(home) if r["id"] == ident), None)
    if result is None:
        raise ValueError("unknown script id: " + ident)
    held = skill_scripts._held(home, result)
    result["script"] = held.read_bytes().decode("utf-8")
    return result
