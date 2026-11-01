"""``self-learn skill write|retire|rename|veto|list`` (SK1, S-107;
``rename``: SK8, S-107; ``veto`` and the case-less steps:
S-110).

The person's door to :mod:`self_learn.skill_writer` and
:mod:`self_learn.skill_requests`; the overseer's runner calls the same
writer functions in-process. Nothing presents a skill to the user or asks
about one: when the user wants a skill's name banned, the skill renamed or
retired, they say so and these commands do it. ``write``, ``retire``,
``rename`` and ``veto`` change the ledger and the skills root, so they are
person-only commands:
from an agent shell (``settings.agent_caller``) they run only under the
user's standing grant with ``--note`` (:func:`grants.authorize`,
S-109), refused before anything is read or locked otherwise,
the way a tier-C ``config set`` is; under the grant the registry and the
commits say ``agent``, never ``human``. ``write --check`` and ``list`` only
read, and run anywhere.

    self-learn skill write <name> --from <dir> [--case <id>] [--by human]
                                  [--expect <sha>] [--check] [--no-push] [--json]
    self-learn skill retire <name> [--case <id>] [--by human] [--no-push] [--json]
    self-learn skill rename <old> <new> [--case <id>] [--expect <sha>]
                                  [--no-push] [--json]
    self-learn skill veto <name> [--rename-to <new>] [--no-push] [--json]
    self-learn skill list [--json]

``--case`` is optional: a person's step (or an agent's under the grant)
that answers no case records ``case: null``. ``retire`` of a skill lessons
still route into records the request on the skill's registry row
(``retire_requested``) and exits 0: the next overseer run that writes
skills moves the lessons out and retires it. ``veto`` bans any kebab-case
name for ever; ``--rename-to`` renames a live skill under it at once (the
veto stays if that rename is refused; the overseer renames it instead).

``--by`` takes only ``human`` (an agent's shell records ``agent`` whatever
it passes): only the overseer's runner, in-process, records a write or a
retirement as the overseer's. ``rename`` has no ``--by``: run from the CLI it is always the person's and
records ``by: human`` (the skills spec row: the CLI never records the
overseer, whose runner calls :func:`skill_writer.rename` itself).

Exit status: 0 done (or nothing to do), 1 refused, 6 a git step failed
(``gitops.EXIT_GIT_FAILED``), 64 the draft folder could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import attribution, grants, skill_registry, skill_requests, skill_writer
from .gitops import EXIT_GIT_FAILED
from .ledger import resolve_home
# Called by its bare name, never as ``skill_writer.rename(...)``: the lock
# invariant's walker (tests/test_lock_invariant.py) reads every
# ``<x>.rename(...)`` call as ``Path.rename``, an unlocked filesystem move,
# and would stop there instead of following the call into the writer,
# whose own lock it must check.
from .skill_writer import rename as rename_skill

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
        "skill", help="the skills self-learn owns: write | retire | rename | list"
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
    write_p.add_argument(
        "--case", default=None,
        help="the case this write belongs to (optional for a person's own step)",
    )
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
    write_p.add_argument(
        "--note", default=None,
        help="from an agent's shell, required: why it runs this under the user's standing grant",
    )
    write_p.add_argument("--no-push", action="store_true", dest="no_push")
    write_p.add_argument("--json", action="store_true", dest="as_json")

    retire_p = commands.add_parser(
        "retire",
        help="remove a skill self-learn owns; while lessons route into it, ask the next "
        "overseer run to move them out and retire it",
    )
    retire_p.add_argument("name")
    retire_p.add_argument(
        "--case", default=None,
        help="the case this retirement belongs to (optional for a person's own step)",
    )
    retire_p.add_argument(
        "--by", choices=_CLI_BY_VALUES, default="human",
        help="who decided the retirement (default: human)",
    )
    retire_p.add_argument(
        "--note", default=None,
        help="from an agent's shell, required: why it runs this under the user's standing grant",
    )
    retire_p.add_argument("--no-push", action="store_true", dest="no_push")
    retire_p.add_argument("--json", action="store_true", dest="as_json")

    rename_p = commands.add_parser(
        "rename",
        help=(
            "give a skill self-learn owns a new name: its folder, marketplace entry and link "
            "move, and every lesson routed to it follows"
        ),
    )
    rename_p.add_argument("old", help="the skill's name now")
    rename_p.add_argument("new", help="its new name (kebab-case)")
    rename_p.add_argument(
        "--case", default=None,
        help="the case this rename belongs to (optional for a person's own step)",
    )
    rename_p.add_argument(
        "--expect", dest="expect_sha", default=None,
        help="the authored sha256 the skill's files have now, when they changed since "
        "self-learn last wrote them (compare-and-swap)",
    )
    rename_p.add_argument(
        "--note", default=None,
        help="from an agent's shell, required: why it runs this under the user's standing grant",
    )
    rename_p.add_argument("--no-push", action="store_true", dest="no_push")
    rename_p.add_argument("--json", action="store_true", dest="as_json")

    veto_p = commands.add_parser(
        "veto",
        help="ban a skill name for ever: a live skill under it is renamed (by the next overseer "
        "run, or at once with --rename-to), and no skill is written under it again",
    )
    veto_p.add_argument("name", help="the name to ban (kebab-case)")
    veto_p.add_argument(
        "--rename-to", dest="rename_to", metavar="NEW", default=None,
        help="rename the live skill under that name to NEW at once",
    )
    veto_p.add_argument(
        "--note", default=None,
        help="from an agent's shell, required: why it runs this under the user's standing grant",
    )
    veto_p.add_argument("--no-push", action="store_true", dest="no_push")
    veto_p.add_argument("--json", action="store_true", dest="as_json")

    list_p = commands.add_parser("list", help="the skills self-learn owns, and their state")
    list_p.add_argument("--json", action="store_true", dest="as_json")

    parser.set_defaults(_skill_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    command = args.skill_command
    if command == "list":
        return _list(resolve_home(), args)
    mutating = command in ("retire", "rename", "veto") or (command == "write" and not args.check)
    home = resolve_home()
    granted: attribution.Authority | None = None
    if mutating:
        try:
            granted = grants.authorize(home, f"skill {command}", note=getattr(args, "note", None))
        except grants.GrantError as exc:
            print(f"self-learn skill {command}: {exc}", file=sys.stderr)
            return exc.exit_code
        if granted is not None:
            args.by = "agent"
    # The statement id of the grant an agent's request runs under, kept on
    # the request's registry entry (a typed yes is never a skill request's).
    args.grant = granted.ref if granted is not None and granted.kind == "grant" else None
    with attribution.acting(granted):
        if command == "write":
            return _write(home, args)
        if command == "rename":
            return _rename(home, args)
        if command == "veto":
            return _veto(home, args)
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


def _request_retire(home: Path, args, routed: tuple[str, ...]) -> int:
    """``skill retire`` of a skill lessons still route into: the request is
    recorded on its registry row for the next overseer run."""
    request = skill_requests.request_retire(
        home, args.name, by=args.by, grant=getattr(args, "grant", None)
    )
    if args.as_json:
        print(json.dumps({
            "command": "skill retire", "name": request.name, "ok": request.ok,
            "requested": request.ok, "added": request.added, "routed": list(request.routed or routed),
            "problems": list(request.problems), "ledger_commit": request.ledger_sha,
        }, sort_keys=True))
    elif request.ok:
        count = len(request.routed or routed)
        print(
            f"self-learn skill retire: {args.name}: requested: the next overseer run that writes "
            f"skills moves its {count} lesson(s) out and retires it"
            + ("" if request.added else " (already requested)")
        )
    else:
        print(f"self-learn skill retire: {args.name}: refused", file=sys.stderr)
        _print_lines("  - ", request.problems, sys.stderr)
    return EXIT_OK if request.ok else EXIT_REFUSED


def _retire(home: Path, args) -> int:
    result = skill_writer.retire(
        home, args.name, case=args.case, by=args.by, no_push=args.no_push
    )
    if not result.ok and result.routed:
        # S-110: lessons still route in, so the person's
        # retire is a request the overseer carries out (it moves them out
        # first), never a hand job of rerouting each.
        return _request_retire(home, args, tuple(result.routed))
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


def _rename(home: Path, args) -> int:
    result = rename_skill(
        home, args.old, args.new, case=args.case, by=getattr(args, "by", None) or "human",
        expect_sha=args.expect_sha, no_push=args.no_push,
    )
    if args.as_json:
        print(json.dumps({
            "command": "skill rename", "old": result.old, "new": result.new, "ok": result.ok,
            "kind": result.kind, "problems": list(result.problems),
            "notes": list(result.notes), "warnings": list(result.warnings),
            "rerouted": list(result.rerouted), "ledger_commits": list(result.ledger_shas),
            "skills_root_commit": result.host_sha, "recompile_commit": result.settle_sha,
            "link": result.link, "unlinked": result.unlinked,
            "authored_sha256": result.authored_sha256,
        }, sort_keys=True))
    elif result.ok:
        if result.changed:
            print(f"self-learn skill rename: {result.old} is now {result.new} "
                  f"({len(result.rerouted)} lesson(s) re-routed)")
        else:
            print(f"self-learn skill rename: {result.old} is already {result.new}; nothing changed")
        _print_lines("  note: ", result.notes, sys.stdout)
        _print_lines("  warning: ", result.warnings, sys.stderr)
        for label, push in (("ledger", result.ledger_push), ("skills root", result.host_push)):
            if push is not None and not push.ok:
                print(f"self-learn skill rename: {label} push failed ({push.detail}); "
                      "the commit is kept", file=sys.stderr)
    else:
        print(f"self-learn skill rename: {result.old} → {result.new}: refused ({result.kind})",
              file=sys.stderr)
        _print_lines("  - ", result.problems, sys.stderr)
        _print_lines("  note: ", result.notes, sys.stderr)
    return _exit_for(result.ok, result.kind)


def _veto(home: Path, args) -> int:
    by = getattr(args, "by", None) or "human"
    result = skill_requests.veto(
        home, args.name, by=by, grant=getattr(args, "grant", None),
        rename_to=args.rename_to, no_push=args.no_push,
    )
    renamed = result.rename
    if args.as_json:
        print(json.dumps({
            "command": "skill veto", "name": result.name, "ok": result.ok,
            "added": result.added, "what": result.what, "problems": list(result.problems),
            "ledger_commit": result.ledger_sha,
            "rename": None if renamed is None else {
                "new": renamed.new, "ok": renamed.ok, "kind": renamed.kind,
                "problems": list(renamed.problems), "rerouted": list(renamed.rerouted),
            },
        }, sort_keys=True))
    elif not result.ok:
        print(f"self-learn skill veto: {args.name}: refused", file=sys.stderr)
        _print_lines("  - ", result.problems, sys.stderr)
    else:
        state = "vetoed for ever" if result.added else "already vetoed"
        print(f"self-learn skill veto: {result.name} is {state}; {result.what}")
        if renamed is not None and renamed.ok:
            print(f"self-learn skill veto: {renamed.old} is now {renamed.new} "
                  f"({len(renamed.rerouted)} lesson(s) re-routed)")
        elif renamed is not None:
            print(
                f"self-learn skill veto: the rename to {renamed.new} was refused "
                f"({renamed.kind}); the veto stands and the next overseer run that writes skills "
                "renames it",
                file=sys.stderr,
            )
            _print_lines("  - ", renamed.problems, sys.stderr)
    if not result.ok:
        return EXIT_REFUSED
    # A refused --rename-to leaves the veto in place, which is what was
    # asked first; the exit says the rename did not happen.
    return EXIT_OK if renamed is None or renamed.ok else _exit_for(False, renamed.kind)


def _skill_state(home: Path, name: str, row: dict) -> dict:
    """What is on disk for one registry row, read only."""
    state: dict = {"name": name, "status": row["status"], "plugin": row["plugin"],
                   "created": row["created"], "last_write": row["last_write"]}
    if "retired" in row:
        state["retired"] = row["retired"]
    if row.get("renamed_from"):
        state["renamed_from"] = list(row["renamed_from"])
    if row.get("retire_requested"):
        state["retire_requested"] = dict(row["retire_requested"])
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
        case = state["last_write"]["case"]
        line += (f"; last written {state['last_write']['at']} by {state['last_write']['by']} "
                 f"({case if case is not None else skill_writer.NO_CASE})")
        if state.get("retire_requested"):
            line += "; retirement requested"
        print(line)
    if registry.vetoed:
        print("vetoed names: " + ", ".join(registry.vetoed_names()))
    return EXIT_OK
