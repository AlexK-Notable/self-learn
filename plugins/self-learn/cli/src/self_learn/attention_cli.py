"""``self-learn attention`` (attention round, design r2 §4.6).

    self-learn attention [--json] [--all]
        0 ok | 1 reader failed (the JSON is still printed, state broken)
    self-learn attention seen <id>... | --all-decided
        0 | 2 unknown id (the others are still marked)     [cache write only]
    self-learn attention packet <id> --json
        0 | 1 build failed | 2 unknown id
    self-learn attention feedback <id> --wanted needs-you|decided|silent [--note TEXT]
        0 | 2 unknown id | 64 refused from an agent's shell (the person's click only)

Neither ``attention`` nor ``ask`` ticks the miner watchdog (``cli.py``).
The list, ``seen`` and ``packet`` write no ledger file; ``feedback`` appends
one ``attention/feedback.jsonl`` row under the ledger lock and, for a
code-classified kind, sets ``attention.class.<kind-key>`` (answer 7: one
click changes every later item of that kind, reversible on /settings).

Two blocks below are reserved for later lanes: ``answers`` adds ``answer``,
``undo``, ``run``, ``fix``, ``claim`` and ``done``; ``ask-agent`` adds
``check-login``.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from . import attention, attention_packet, gitops, intents, settings
from .ledger import resolve_home
from .primitives import chrono, fsops

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNKNOWN = 2
EXIT_USAGE = 64

WANTED = ("needs-you", "decided", "silent")


def add_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "attention",
        help="what self-learn needs from you, and what it decided for you (the inbox)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--all", action="store_true", dest="all_items",
        help="decided items of any age, not only the last 30 days",
    )
    commands = parser.add_subparsers(dest="attention_command", required=False)

    seen_p = commands.add_parser("seen", help="mark items seen (clears their 'new' dot only)")
    seen_p.add_argument("ids", nargs="*", metavar="ID")
    seen_p.add_argument("--all-decided", action="store_true", dest="all_decided")

    packet_p = commands.add_parser("packet", help="one item's full context packet")
    packet_p.add_argument("id", metavar="ID")
    packet_p.add_argument("--json", action="store_true", dest="as_json")

    feedback_p = commands.add_parser(
        "feedback",
        help="the person's 'didn't need me' / 'should have asked me' click (never an agent's)",
    )
    feedback_p.add_argument("id", metavar="ID")
    feedback_p.add_argument("--wanted", required=True, choices=WANTED)
    feedback_p.add_argument("--note", default=None)

    # --- answers lane ---
    from . import attention_answers_cli

    attention_answers_cli.add_parsers(commands)

    # --- ask-agent lane ---

    parser.set_defaults(_attention_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    command = getattr(args, "attention_command", None)
    home = resolve_home()
    if command is None:
        return _list(home, args)
    if command == "seen":
        return _seen(home, args)
    if command == "packet":
        return _packet(home, args)
    if command == "feedback":
        return _feedback(home, args)
    # --- answers lane ---
    from . import attention_answers_cli

    if command in attention_answers_cli.COMMANDS:
        return attention_answers_cli.dispatch(home, args)

    # --- ask-agent lane ---
    print(f"self-learn attention: unknown command {command!r}", file=sys.stderr)
    return EXIT_USAGE


def _list(home: Path, args) -> int:
    document = attention.read(home, all_items=args.all_items)
    code = EXIT_FAILED if document.get("error") else EXIT_OK
    if args.as_json:
        print(json.dumps(document, ensure_ascii=False))
        return code
    print(document["tooltip"])
    if document.get("error"):
        print(f"  the inbox could not be read: {document['error']}", file=sys.stderr)
    for item in document["items"]:
        mark = "" if item["seen"] or item["class"] != "decided" else " (new)" if item["flagged"] else " (unseen)"
        print(f"  [{item['class']}] {item['id']} {item['title']}{mark}")
    return code


def _seen(home: Path, args) -> int:
    if not args.ids and not args.all_decided:
        print("self-learn attention seen: name item ids, or pass --all-decided", file=sys.stderr)
        return EXIT_USAGE
    marked, unknown = attention.mark_seen(home, list(args.ids), all_decided=args.all_decided)
    for item_id in unknown:
        print(f"self-learn attention seen: unknown item {item_id}", file=sys.stderr)
    print(f"attention seen: {len(marked)} item(s) marked")
    return EXIT_UNKNOWN if unknown else EXIT_OK


def _packet(home: Path, args) -> int:
    try:
        packet = attention_packet.build(home, args.id)
    except attention_packet.UnknownItem:
        print(f"self-learn attention packet: unknown or expired item {args.id}", file=sys.stderr)
        return EXIT_UNKNOWN
    except Exception as exc:  # noqa: BLE001 -- the page falls back to the list JSON
        print(f"self-learn attention packet: the packet could not be built: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    if args.as_json:
        print(json.dumps(packet, ensure_ascii=False))
    else:
        print(attention_packet.render_md(packet), end="")
    return EXIT_OK


def feedback_path(home: Path | str) -> Path:
    return Path(home) / "attention" / "feedback.jsonl"


def record_feedback(home: Path, item: dict, wanted: str, note: str | None) -> dict:
    """Append one feedback row (the person's click, ``by: human``) and, for a
    code-classified kind, set ``attention.class.<kind-key>`` to *wanted*.
    Both commit inside one ``ledger_write`` span."""
    row = {
        "id": "fb-" + uuid.uuid4().hex[:8], "at": chrono.now_iso(), "item": item["id"],
        "kind": item["kind"], "class_shown": item["class"], "class_wanted": wanted,
        "by": "human", "note": note,
    }
    with intents.ledger_write(home) as recovered:
        intents.announce_recovered(recovered)
        target = feedback_path(home)
        target.parent.mkdir(parents=True, exist_ok=True)
        prior = target.read_text(encoding="utf-8") if target.exists() else ""
        if prior and not prior.endswith("\n"):
            prior += "\n"
        fsops.atomic_write(target, prior + json.dumps(row, sort_keys=True) + "\n", fsync=True)
        gitops.stage_and_commit(
            home, [target],
            f"self-learn: attention feedback {row['id']} ({item['kind']}: {wanted})", None,
        )
        if not item["kind"].startswith("ask."):
            settings.config_set(
                home, f"attention.class.{settings.attention_kind_key(item['kind'])}", wanted,
                note=f"From the inbox: the person's feedback {row['id']} on {item['id']}",
            )
    return row


def _feedback(home: Path, args) -> int:
    if settings.agent_caller():
        print(
            "self-learn attention feedback: refused: 'didn't need me' and 'should have asked "
            "me' are the person's own click in the inbox, never an agent's "
            f"(agent shell detected: {', '.join(settings.agent_caller_markers())})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    item = attention.find(home, args.id)
    if item is None:
        print(f"self-learn attention feedback: unknown item {args.id}", file=sys.stderr)
        return EXIT_UNKNOWN
    try:
        row = record_feedback(home, item, args.wanted, args.note)
    except intents.LedgerStoppedError as exc:
        print(str(exc), file=sys.stderr)
        return gitops.EXIT_GIT_FAILED
    except gitops.HalfWrittenError as exc:
        print(f"self-learn attention feedback: written but not committed: {exc}", file=sys.stderr)
        return gitops.EXIT_HALF_WRITTEN
    except gitops.GitOpsError as exc:
        print(f"self-learn attention feedback: {exc}", file=sys.stderr)
        return gitops.EXIT_GIT_FAILED
    except settings.SettingsError as exc:
        print(f"self-learn attention feedback: the row is recorded, but the class could not "
              f"be set: {exc}", file=sys.stderr)
        return EXIT_FAILED
    scope = (
        "this item's kind is now shown as " + args.wanted
        if not item["kind"].startswith("ask.")
        else "recorded for the overseer, which weighs it on its next run"
    )
    print(f"attention feedback: {row['id']} on {item['id']}: {scope}")
    return EXIT_OK
