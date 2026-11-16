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
from typing import Mapping, cast

from . import gitops, attribution, grant_uses, grants, skill_registry, skill_requests, skill_writer
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
#: person's, an agent's is the agent's (C7, attention round: an agent never
#: has to record its own act as the user's). ``overseer`` stays in
#: ``skill_registry.BY_VALUES`` for the runner's in-process calls.
_CLI_BY_VALUES = ("human", "agent")


def default_by() -> str:
    """``--by``'s default: ``agent`` from an agent's shell
    (:func:`settings.agent_caller`), ``human`` from a person's terminal."""
    from . import settings  # lazy: settings imports ledger, which imports hosts

    return "agent" if settings.agent_caller() else "human"


def _exit_for(ok: bool, kind: str | None) -> int:
    if ok:
        return EXIT_OK
    return EXIT_GIT_FAILED if kind == skill_writer.KIND_GIT else EXIT_REFUSED


def add_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "skill", help="create, maintain, register skills, or request a build/change"
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
        "--by", choices=_CLI_BY_VALUES, default=None,
        help="who decided the write (default: agent from an agent's shell, else human)",
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
        "--by", choices=_CLI_BY_VALUES, default=None,
        help="who decided the retirement (default: agent from an agent's shell, else human)",
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

    for verb in ("register", "unregister"):
        reg = commands.add_parser(verb, help=("permit full upkeep of a user-maintained skill (name or path)" if verb == "register" else "withdraw upkeep permission; keep the skill and link"))
        reg.add_argument("name")
        reg.add_argument("--note", required=True, help="why; agents may run this without a standing grant")
        reg.add_argument("--json", action="store_true", dest="as_json")
    req = commands.add_parser("request", help="ask the next overseer run to build or change a skill")
    requests = req.add_subparsers(dest="request_kind", required=True)
    build = requests.add_parser("build", help="request a new skill from existing lessons")
    build.add_argument("--name", required=True)
    build.add_argument("--lessons", required=True, help="comma-separated lesson ids")
    change = requests.add_parser("change", help="request changes to an owned or registered skill")
    change.add_argument("name")
    withdraw = requests.add_parser("withdraw", help="withdraw an open request; agents need no standing grant")
    withdraw.add_argument("name", metavar="id")
    for item in (build, change, withdraw):
        item.add_argument("--note", required=True, help="what should change and why")
        item.add_argument("--json", action="store_true", dest="as_json")

    ref = commands.add_parser("reference", help="read, check or inspect the Anthropic authoring reference")
    ref_commands = ref.add_subparsers(dest="reference_command", required=True)
    show = ref_commands.add_parser("show", help="print the reference pack")
    show.add_argument("--path", action="store_true", help="print its installed path instead")
    check = ref_commands.add_parser("check", help="check a skill name or folder, read-only")
    check.add_argument("target")
    mode = check.add_mutually_exclusive_group()
    mode.add_argument("--draft", dest="reference_mode", action="store_const", const="draft",
                      help="check every supplied file as a write draft")
    mode.add_argument("--installed", dest="reference_mode", action="store_const", const="installed",
                      help="check the editable view, retaining compiler blocks and user assets")

    status = ref_commands.add_parser("status", help="pack age and last source check")
    status.add_argument("--fetch", action="store_true", help="HTTP-check sources and record cache status; exit 1 if changed/unreachable")
    from . import script_cli
    script_cli.add_parser(commands)
    parser.set_defaults(_skill_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    command = args.skill_command
    if command == "script":
        from . import script_cli
        return script_cli.dispatch(resolve_home(), args)
    if command == "reference":
        return _reference(resolve_home(), args)
    if command == "list":
        return _list(resolve_home(), args)
    if command in ("register", "unregister", "request"):
        return _registration_request(resolve_home(), args)
    mutating = command in ("retire", "rename", "veto") or (command == "write" and not args.check)
    home = resolve_home()
    # C7 (attention round): with no --by, who decided is who ran it -- an
    # agent's shell is `agent`, a person's terminal `human`. Before this an
    # agent that left --by out was stored as the person.
    if getattr(args, "by", None) is None:
        args.by = default_by()
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
    use = (
        grant_uses.GrantUse(home, f"skill {command}", _use_args(args), prior=None)
        if granted is not None else None
    )
    with attribution.acting(granted, use=use):
        if command == "write":
            code = _write(home, args)
        elif command == "rename":
            code = _rename(home, args)
        elif command == "veto":
            code = _veto(home, args)
        else:
            code = _retire(home, args)
        if use is not None and code != EXIT_OK:
            use.applies = False
        return code


def _use_args(args) -> list[str]:
    """The argv a skill verb's grant-use row keeps (attention round,
    design r2 §3.4.6): enough to run it again as the redo. The draft folder
    is kept absolute (answers gate r3 NIT B, at integration): the redo runs
    from the inbox, whose working directory is not the shell the write ran
    in, and refuses a relative `--from` rather than guess."""
    command = args.skill_command
    if command == "write":
        return [args.name, "--from", str(Path(args.source).resolve())]
    if command == "rename":
        return [args.old, args.new]
    if command == "veto":
        return [args.name, *(["--rename-to", args.rename_to] if args.rename_to else [])]
    return [args.name]


def _print_lines(prefix: str, lines, stream) -> None:
    for line in lines:
        print(f"{prefix}{line}", file=stream)


def _write(home: Path, args) -> int:
    from .skill_reference import VERSION
    try:
        files = skill_writer.read_draft_dir(args.source)
    except (ValueError, OSError) as exc:
        print(f"self-learn skill write: cannot read the draft: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.check:
        result = skill_writer.check(home, args.name, files, expect_sha=args.expect_sha)
        if not args.as_json:
            print(f"skill reference checked: {VERSION}")
        if args.as_json:
            print(json.dumps({
                "reference_pack": VERSION, "command": "skill write --check", "name": result.name, "ok": result.ok,
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
    if not args.as_json:
        print(f"skill reference checked: {VERSION}")
    if args.as_json:
        print(json.dumps({
            "reference_pack": VERSION, "command": "skill write", "name": written.name, "ok": written.ok,
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
            "registrations": registry.registrations,
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
        line += f"; reference {state['last_write'].get('reference_pack', 'unrecorded')}"
        if state.get("retire_requested"):
            line += "; retirement requested"
        print(line)
    for name, row in sorted(registry.registrations.items()):
        stamp = row["registered"]
        print(f"{name}: registered ({row['status']}); {stamp['path']}; by {stamp['by']} at {stamp['at']}; {stamp['note']}; reference {(row.get('last_write') or {}).get('reference_pack', 'unrecorded')}")
    if registry.vetoed:
        print("vetoed names: " + ", ".join(registry.vetoed_names()))
    return EXIT_OK


def _registration_request(home: Path, args) -> int:
    from . import skill_registration
    try:
        skill_registration._note_by(args.note, default_by())
        if args.skill_command == "register":
            result = skill_registration.register(home, args.name, note=args.note, by=default_by())
        elif args.skill_command == "unregister":
            result = skill_registration.unregister(home, args.name, note=args.note, by=default_by())
        elif args.request_kind == "withdraw":
            result = skill_requests.withdraw_request(home, args.name, note=args.note, by=default_by())
        else:
            result = skill_requests.file_request(home, args.request_kind, args.name,
                lessons=[s.strip() for s in getattr(args, "lessons", "").split(",") if s.strip()],
                note=args.note, by=default_by())
    except (ValueError, OSError, skill_registry.SkillRegistryError, gitops.GitOpsError) as exc:
        print(f"self-learn skill {args.skill_command}: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if args.as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"{result['name']}: {result['state']}" + (f" ({result['id']})" if "id" in result else ""))
    _print_lines("  warning: ", result.get("notes", []), sys.stderr)
    return EXIT_OK


def _reference_files(target: Path) -> tuple[dict, list[str]]:
    """Read only files a rewrite replaces; do not open retained user assets."""
    import os

    files = {}
    retained = []
    for current, dirs, names in os.walk(target, followlinks=False):
        here = Path(current)
        for dirname in list(dirs):
            path = here / dirname
            if path.is_symlink():
                retained.append(path.relative_to(target).as_posix() + "/")
                dirs.remove(dirname)
        for name in names:
            path = here / name
            key = path.relative_to(target).as_posix()
            if key != "SKILL.md" and not skill_writer._is_managed_reference(key):
                retained.append(key)
                continue
            if path.is_symlink():
                raise ValueError(f"{key} is a symlink; editable draft files must be plain files")
            if path.stat().st_size > skill_writer.MAX_DRAFT_FILE_BYTES:
                raise ValueError(f"{key} is too large for a draft")
            raw = path.read_bytes()
            try:
                files[key] = raw.decode("utf-8")
            except UnicodeDecodeError:
                files[key] = raw
    return files, sorted(retained)


def _reference(home: Path, args) -> int:
    from . import skill_reference as reference
    from .skill_scaffold import check_skill, _read_frontmatter
    from .hosts import HostsError, load_hosts
    if args.reference_command == "show":
        path = reference.PACK_DIR / "PACK.md"
        print(path if args.path else path.read_text(), end="\n")
        return EXIT_OK
    if args.reference_command == "status":
        result = reference.status(home, fetch=args.fetch)
        print("\n".join(reference.status_lines(result)))
        for source in result["sources"]:
            print(f"{source['title']} ({source['date_read']}): {source['url']}")
        return EXIT_REFUSED if any(r["state"] != "unchanged" for r in result.get("checks", [])) else EXIT_OK
    try:
        target = Path(args.target).expanduser()
        if not target.is_dir():
            from .skill_reference import resolve_skill
            target = resolve_skill(home, args.target)
        target = target.resolve()
        registry = skill_registry.load(home)
        root = load_hosts(home).skills_root
        deployed = {}
        if root:
            for name in registry.skills:
                if registry.is_owned(name):
                    deployed[name] = skill_writer.skill_dir(Path(root), name).resolve()
        for name, row in registry.registrations.items():
            if row["status"] == skill_registry.STATUS_LIVE:
                deployed[name] = Path(row["registered"]["path"]).resolve()
        matched = next((name for name, folder in deployed.items() if folder == target), None)
        mode = getattr(args, "reference_mode", None) or ("installed" if matched else "draft")
        retained = []
        if mode == "installed":
            files, retained = _reference_files(target)
            text = {k: v for k, v in files.items() if isinstance(v, str)}
            clean = dict(skill_writer.draft_view(text))
            clean.update({k: v for k, v in files.items() if not isinstance(v, str)})
        else:
            clean = skill_writer.read_draft_dir(target)
        entry = clean.get("SKILL.md")
        front = _read_frontmatter(entry).mapping if isinstance(entry, str) else None
        name = front.get("name") if front else None
        expected = target.name if mode == "installed" else name if isinstance(name, str) else None
        existing = None
        carried = None
        if isinstance(name, str) and name in deployed:
            # Drafts of registered rewrites get the same carried-key allowance,
            # read from deployment, never from the supplied draft's own claims.
            deployed_md = deployed[name] / "SKILL.md"
            if deployed_md.is_file():
                previous = _read_frontmatter(skill_writer._unstamped(deployed_md.read_text())).mapping
                if previous and previous.get("name") == name:
                    existing = name
                if registry.is_registered(name):
                    carried = previous
        result = check_skill(cast(Mapping[str, str], clean), loaded_names=(), vetoed_names=(),
                             expected_name=expected, existing_name=existing, carried_frontmatter=carried)
        extra = skill_writer._compiler_owned_in_draft(clean) + skill_writer._secret_problems(clean)
    except (OSError, ValueError, HostsError, skill_registry.SkillRegistryError) as exc:
        print(f"skill reference check: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"skill reference checked: {reference.VERSION}; mode: {mode}; {target}")
    for key in retained:
        print(f"note: retained-file: {key}: left in place by writes; not part of a Markdown draft; source: self-learn writing policy")
    for severity, findings in (("refusal", result.problems), ("note", result.notes)):
        for finding in findings:
            print(f"{severity}: {finding} ({finding.path}); source: {reference.finding_source(finding.rule)}")
    for problem in extra:
        print(f"refusal: {problem}; source: self-learn writing policy")
    print(f"{len(result.problems) + len(extra)} refusals; {len(result.notes) + len(retained)} notes; semantic quality and triggering need real usage evaluation")
    return EXIT_OK if result.ok and not extra else EXIT_REFUSED
