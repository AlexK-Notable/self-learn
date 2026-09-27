"""``self-learn index status|build|related|groups`` (U2; 02-schema.md §3a.7).

Read-mostly: ``build`` writes only the cache index; the others read it and
the ledger. ``status --json`` is the data a future dashboard reads.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..ledger import discover_buckets, resolve_home
from . import hybrid
from .related import Relatedness, group_for_steward
from .store import LessonIndex, collect, index_path

EXIT_OK = 0
EXIT_FAIL = 1

_NOT_BUILT = "self-learn index: not built yet -- run `self-learn index build`"


def add_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "index", help="the lesson index (cache): status | build | related | groups"
    )
    commands = parser.add_subparsers(dest="index_command", required=True)
    status_p = commands.add_parser("status", help="counts, mode, model, last build, stale rows")
    status_p.add_argument("--json", action="store_true")
    build_p = commands.add_parser("build", help="bring the index up to date (writes the cache only)")
    build_p.add_argument("--json", action="store_true")
    build_p.add_argument(
        "--no-embed", action="store_true",
        help="word index only; spend no embedding API calls",
    )
    related_p = commands.add_parser("related", help="the lessons related to one lesson")
    related_p.add_argument("record_id")
    related_p.add_argument("--limit", type=int, default=10, help="nearest lessons to list")
    related_p.add_argument("--json", action="store_true")
    groups_p = commands.add_parser(
        "groups", help="the pending queue grouped as the steward would read it"
    )
    groups_p.add_argument("--json", action="store_true")
    parser.set_defaults(_index_dispatch=dispatch)
    return parser


def dispatch(args) -> int:
    home = resolve_home()
    command = args.index_command
    if command == "build":
        return _build(home, args)
    index = LessonIndex.open_existing(home)
    if index is None:
        if command == "status" and args.json:
            print(json.dumps({
                "command": "index status", "built": False,
                "path": str(index_path(home)),
            }, sort_keys=True))
            return EXIT_OK
        print(_NOT_BUILT, file=sys.stderr)
        return EXIT_OK if command == "status" else EXIT_FAIL
    try:
        if command == "status":
            return _status(index, home, args)
        if command == "related":
            return _related(index, args)
        return _groups(index, home, args)
    finally:
        index.close()


def _build(home, args) -> int:
    index = LessonIndex.open(home)
    try:
        report = index.build(None) if args.no_embed else index.build()
    finally:
        index.close()
    if args.json:
        print(json.dumps({"command": "index build", **report.to_json()}, sort_keys=True))
    else:
        print(
            f"self-learn index: {report.mode}"
            + (f" ({report.mode_reason})" if report.mode_reason else "")
            + f"; added {len(report.added)}, changed {len(report.changed)}, "
            f"removed {len(report.removed)}, embedded {len(report.embedded)}"
        )
        for path in report.unreadable:
            print(f"  unreadable: {path}")
    return EXIT_OK


def _status(index: LessonIndex, home, args) -> int:
    docs, _bad = collect(home)
    data = {"command": "index status", **index.status(ledger_docs=docs)}
    if args.json:
        print(json.dumps(data, sort_keys=True))
        return EXIT_OK
    print(
        f"self-learn index: {data['records']} records in {data['buckets']} buckets; "
        f"{data['mode']}" + (f" ({data['mode_reason']})" if data["mode_reason"] else "")
    )
    print(f"  model: {data['model'] or '-'}; vectors current {data['vectors']['current']}, "
          f"missing {data['vectors']['missing']}")
    print(f"  last build: {data['last_build_at'] or '-'}")
    stale = data["stale"] or {}
    print(f"  stale: {stale.get('not_indexed', 0)} not indexed, {stale.get('changed', 0)} "
          f"changed, {stale.get('gone', 0)} gone")
    return EXIT_OK


def _related(index: LessonIndex, args) -> int:
    rel = Relatedness(index)
    target = args.record_id
    if target not in rel.docs:
        print(f"self-learn index: {target} is not in the index (run `self-learn index build`)",
              file=sys.stderr)
        return EXIT_FAIL
    relations = [rel.relation(target, other) for other in sorted(rel.docs) if other != target]
    related = [r for r in relations if r.related]
    near = hybrid.nearest(index, target, limit=max(0, args.limit))
    doc = rel.docs[target]
    if args.json:
        print(json.dumps({
            "command": "index related",
            "id": target,
            "bucket": {"scope": doc.bucket_scope, "name": doc.bucket_name},
            "basis": rel.basis,
            "basis_reason": rel.basis_reason,
            "threshold": rel.threshold,
            "related": [r.to_json() for r in related],
            "nearest": {
                "mode": near.mode,
                "note": near.note,
                "hits": [
                    {"id": h.id, "rrf": round(h.rrf, 6),
                     "lexical": None if h.lexical is None else round(h.lexical, 4),
                     "cosine": None if h.cosine is None else round(h.cosine, 4)}
                    for h in near.hits
                ],
            },
        }, sort_keys=True))
        return EXIT_OK
    print(f"{target} ({doc.bucket_scope}:{doc.bucket_name}) -- {rel.basis_reason}, "
          f"threshold {rel.threshold}")
    if not related:
        print("  related: none")
    for r in related:
        sim = "" if r.similarity is None else f" similarity {r.similarity:.3f}"
        print(f"  related: {r.b}  [{', '.join(r.reasons)}]{sim}")
    print(f"  nearest ({near.mode}):")
    for h in near.hits:
        print(f"    {h.id}  rrf {h.rrf:.4f}")
    return EXIT_OK


def pending_queue_ids(home) -> list[str]:
    """The queued records (pending, deferred hidden) across every bucket --
    the steward's candidate set."""
    from ..ledger_ops import queue

    return sorted(e.record.id for b in discover_buckets(home) for e in queue(b))


def _groups(index: LessonIndex, home, args) -> int:
    ids = pending_queue_ids(home)
    grouping = group_for_steward(ids, index=index)
    if args.json:
        print(json.dumps({"command": "index groups", "queued": len(ids), **grouping.to_json()},
                         sort_keys=True))
        return EXIT_OK
    print(f"self-learn index: {len(ids)} queued -> {len(grouping.groups)} group(s); "
          f"{grouping.basis_reason}, threshold {grouping.threshold}")
    for n, g in enumerate(grouping.groups, 1):
        print(f"  group {n}: {' '.join(g.members)}")
        if g.unrelated:
            print(f"    unrelated: {' '.join(g.unrelated)}")
    return EXIT_OK
