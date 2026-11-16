"""Agent-available S-160 commands. There is deliberately no approve verb."""
import json
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
        else:
            result = skill_scripts.deactivate(home, args.id, note=args.note)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"self-learn skill script: {exc}", file=sys.stderr)
        return 1
