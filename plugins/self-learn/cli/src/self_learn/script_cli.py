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
        run = subs.add_parser("run", help="verify an active script's managed copy, then run it with its declared interpreter")
        run.add_argument("script", metavar="SKILL/NAME")
        run.add_argument("--timeout", type=float, default=skill_scripts.RUN_TIMEOUT)
        run.add_argument("args", nargs=argparse.REMAINDER)


def dispatch(home, args):
    try:
        command = args.script_command
        if command == "list":
            result = skill_scripts.listed(home)
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
    argv = args.args[1:] if args.args[:1] == ["--"] else args.args
    finished = skill_scripts.run(home, args.script, argv, timeout=args.timeout)
    out = sys.stdout.buffer
    out.write(finished.stdout)
    out.flush()
    buf = sys.stderr.buffer
    buf.write(finished.stderr)
    buf.flush()
    return finished.returncode
