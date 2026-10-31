"""``self-learn skill write|retire|list`` (SK1, S-NEXT-sk1-writer).

The person's door to :mod:`self_learn.skill_writer`; the overseer's runner
calls the same functions in-process. ``write`` and ``retire`` change the
ledger and the skills root, so they are a person's commands: from an agent
shell (``settings.agent_caller``) they are refused before anything is read
or locked, the way a tier-C ``config set`` is. ``write --check`` and
``list`` only read, and run anywhere.

    self-learn skill write <name> --from <dir> --case <id> [--by human]
                                  [--expect <sha>] [--check] [--no-push] [--json]
    self-learn skill retire <name> --case <id> [--by human] [--no-push] [--json]

``--by`` takes only ``human``: the command is a person's, and only the
overseer's runner, in-process, records a write or a retirement as the
overseer's.
    self-learn skill list [--json]

Exit status: 0 done (or nothing to do), 1 refused, 6 a git step failed
(``gitops.EXIT_GIT_FAILED``), 64 the draft folder could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import settings, skill_registry, skill_writer
from .gitops import EXIT_GIT_FAILED
from .ledger import resolve_home

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 64  # the CLI's own (cli.EXIT_USAGE, sysexits EX_USAGE)

#: What ``--by`` accepts from the command line: a person's run is the
#: person's. ``overseer`` stays in ``skill_registry.BY_VALUES`` for the
#: runner's in-process calls.
_CLI_BY_VALUES = ("human",)


def _exit_for(ok: bool, kind: str | None) -> int:
    if ok:
        return EXIT_OK
    return EXIT_GIT_FAILED if kind == skill_writer.KIND_GIT else EXIT_REFUSED


def add_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "skill", help="the skills self-learn owns: write | retire | list"
    )
    commands = parser.add_subparsers(dest="skill_command", required=True)

    write_p = commands.add_parser(
        "write", help="check and deploy one skill self-learn owns (create or update)"
    )
    write_p.add_argument("name", help="the skill's name (kebab-case)")
    write_p.add_argument(
        "--from", dest="source", required=True,
        help="a folder holding SKILL.md and any references/*.md",
    )
    write_p.add_argument("--case", required=True, help="the case this write belongs to")
    write_p.add_argument(
        "--by", choices=_CLI_BY_VALUES, default="human",
        help="who decided the write (default: human)",
    )
    write_p.add_argument(
        "--expect", dest="expect_sha", default=None,
        help="the authored sha256 the deployed files must still have (compare-and-swap)",
    )
    write_p.add_argument(
        "--check", action="store_true",
        help="run every check and write nothing",
    )
    write_p.add_argument("--no-push", action="store_true", dest="no_push")
    write_p.add_argument("--json", action="store_true", dest="as_json")

    retire_p = commands.add_parser(
        "retire", help="remove a skill self-learn owns (refused while lessons route into it)"
    )
    retire_p.add_argument("name")
    retire_p.add_argument("--case", required=True, help="the case this retirement belongs to")
    retire_p.add_argument(
        "--by", choices=_CLI_BY_VALUES, default="human",
        help="who decided the retirement (default: human)",
    )
    retire_p.add_argument("--no-push", action="store_true", dest="no_push")
    retire_p.add_argument("--json", action="store_true", dest="as_json")

    list_p = commands.add_parser("list", help="the skills self-learn owns, and their state")
    list_p.add_argument("--json", action="store_true", dest="as_json")

    parser.set_defaults(_skill_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    command = args.skill_command
    if command == "list":
        return _list(resolve_home(), args)
    mutating = command == "retire" or (command == "write" and not args.check)
    if mutating and settings.agent_caller():
        print(
            f"self-learn skill {command}: {command} is a person's command (the overseer's "
            "runner calls it in-process); run the same command in your own terminal "
            "(not through an agent) "
            f"(agent shell detected: {', '.join(settings.agent_caller_markers())})",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    home = resolve_home()
    if command == "write":
        return _write(home, args)
    return _retire(home, args)


def _print_lines(prefix: str, lines, stream) -> None:
    for line in lines:
        print(f"{prefix}{line}", file=stream)


def _write(home: Path, args) -> int:
    try:
        files = skill_writer.read_draft_dir(args.source)
    except (ValueError, OSError) as exc:
        print(f"self-learn skill write: cannot read the draft: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.check:
        result = skill_writer.check(home, args.name, files, expect_sha=args.expect_sha)
        if args.as_json:
            print(json.dumps({
                "command": "skill write --check", "name": result.name, "ok": result.ok,
                "kind": result.kind, "problems": list(result.problems),
                "notes": list(result.notes), "updating": result.updating,
                "current_sha": result.current_sha, "recorded_sha": result.recorded_sha,
            }, sort_keys=True))
        elif result.ok:
            verb = "update" if result.updating else "create"
            print(f"self-learn skill write --check: {result.name}: would {verb}; every check passed")
            _print_lines("  note: ", result.notes, sys.stdout)
        else:
            print(f"self-learn skill write --check: {result.name}: refused ({result.kind})", file=sys.stderr)
            _print_lines("  - ", result.problems, sys.stderr)
            _print_lines("  note: ", result.notes, sys.stderr)
        return EXIT_OK if result.ok else EXIT_REFUSED

    written = skill_writer.write(
        home, args.name, files, case=args.case, by=args.by,
        expect_sha=args.expect_sha, no_push=args.no_push,
    )
    if args.as_json:
        print(json.dumps({
            "command": "skill write", "name": written.name, "ok": written.ok,
            "kind": written.kind, "problems": list(written.problems),
            "notes": list(written.notes), "warnings": list(written.warnings),
            "updating": written.updating, "ledger_commit": written.ledger_sha,
            "skills_root_commit": written.host_sha, "link": written.link,
            "authored_sha256": written.authored_sha256,
        }, sort_keys=True))
    elif written.ok:
        if written.changed:
            verb = "updated" if written.updating else "created"
            print(f"self-learn skill write: {written.name} {verb} "
                  f"(authored sha256 {written.authored_sha256})")
        else:
            print(f"self-learn skill write: {written.name} is already as written; nothing changed")
        _print_lines("  note: ", written.notes, sys.stdout)
        for label, push in (("ledger", written.ledger_push), ("skills root", written.host_push)):
            if push is not None and not push.ok:
                print(f"self-learn skill write: {label} push failed ({push.detail}); "
                      "the commit is kept", file=sys.stderr)
    else:
        print(f"self-learn skill write: {written.name}: refused ({written.kind})", file=sys.stderr)
        _print_lines("  - ", written.problems, sys.stderr)
        _print_lines("  note: ", written.notes, sys.stderr)
    return _exit_for(written.ok, written.kind)


def _retire(home: Path, args) -> int:
    result = skill_writer.retire(
        home, args.name, case=args.case, by=args.by, no_push=args.no_push
    )
    if args.as_json:
        print(json.dumps({
            "command": "skill retire", "name": result.name, "ok": result.ok,
            "kind": result.kind, "problems": list(result.problems),
            "notes": list(result.notes), "routed": list(result.routed),
            "ledger_commit": result.ledger_sha, "skills_root_commit": result.host_sha,
            "unlinked": result.unlinked,
        }, sort_keys=True))
    elif result.ok:
        if result.changed:
            print(f"self-learn skill retire: {result.name} retired")
        else:
            print(f"self-learn skill retire: {result.name}: nothing to do")
        _print_lines("  note: ", result.notes, sys.stdout)
    else:
        print(f"self-learn skill retire: {result.name}: refused ({result.kind})", file=sys.stderr)
        _print_lines("  - ", result.problems, sys.stderr)
    return _exit_for(result.ok, result.kind)


def _skill_state(home: Path, name: str, row: dict) -> dict:
    """What is on disk for one registry row, read only."""
    state: dict = {"name": name, "status": row["status"], "plugin": row["plugin"],
                   "created": row["created"], "last_write": row["last_write"]}
    if "retired" in row:
        state["retired"] = row["retired"]
    if row.get("renamed_from"):
        state["renamed_from"] = list(row["renamed_from"])
    if row["status"] != skill_registry.STATUS_LIVE:
        return state
    current = skill_writer.deployed_authored_sha256(home, name)
    if current is None:
        state["files"] = "missing"
    elif current == row["last_write"]["authored_sha256"]:
        state["files"] = "as self-learn last wrote them"
    else:
        state["files"] = "changed since self-learn last wrote them"
    state["current_sha"] = current
    link = skill_writer.link_path(name)
    if not link.is_symlink():
        state["link"] = "missing" if not link.exists() else "not a link"
    elif link.exists() and (link / "SKILL.md").is_file():
        state["link"] = "ok"
    else:
        state["link"] = "broken"
    return state


def _list(home: Path, args) -> int:
    try:
        registry = skill_registry.load(home)
    except skill_registry.SkillRegistryError as exc:
        print(f"self-learn skill list: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    states = [_skill_state(home, name, registry.skills[name]) for name in sorted(registry.skills)]
    if args.as_json:
        print(json.dumps({
            "command": "skill list", "skills": states, "vetoed": registry.vetoed_names(),
        }, sort_keys=True, default=str))
        return EXIT_OK
    if not states:
        print("self-learn owns no skills yet")
    for state in states:
        line = f"{state['name']}: {state['status']}"
        if state["status"] == skill_registry.STATUS_LIVE:
            line += f"; files {state['files']}; link {state['link']}"
        line += (f"; last written {state['last_write']['at']} by {state['last_write']['by']} "
                 f"({state['last_write']['case']})")
        print(line)
    if registry.vetoed:
        print("vetoed names: " + ", ".join(registry.vetoed_names()))
    return EXIT_OK
