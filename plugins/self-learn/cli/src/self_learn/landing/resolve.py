"""resolve.py — the `land` runner's entry point into conflicts.py/resolvers.py.

Invoked once per conflicted path: `python3 -m self_learn.landing.resolve
--root <abs> --path <rel> --resolver <name> [--branch <name>]`. Rewrites
the file in place via `conflicts.rewrite()`, applying the named resolver.
For `per-key`, any BOTH-CHANGED key shaped like a quoted pinned-file path
(`"plugins/...": "<sha>"`) is offered the re-derive door (RES5) — the
runner never asks the operator which keys may re-derive; it recognises
the pin shape and re-derives with an auto-generated, dated justification
naming both sides. Any other both-changed key still refuses.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

from . import resolvers as R
from .conflicts import Refusal, has_base_markers, rewrite

_PIN_KEY_RE = re.compile(r'^"[^"]+\.py"$')


def _both_changed_keys(text: str) -> frozenset[str]:
    """Every key in a per-key block shaped like a pinned-file path — the
    only shape RES5's re-derive door applies to."""
    keys = set()
    for line in text.split("\n"):
        if ":" in line:
            k = line.split(":", 1)[0].strip()
            if _PIN_KEY_RE.match(k):
                keys.add(k)
    return frozenset(keys)


def resolve_one(root: Path, rel_path: str, resolver_name: str, branch: str) -> int:
    target = root / rel_path
    text = target.read_text()
    if not has_base_markers(text):
        raise Refusal(
            f"{rel_path}: no ||||||| base marker present -- merge.conflictStyle is not diff3 "
            "(PRV3: the runner supplies -c merge.conflictStyle=diff3 itself; this should be unreachable)"
        )

    if resolver_name == "per-key":
        both_changed = _both_changed_keys(text)
        today = datetime.date.today()

        def resolver(ours, base, theirs):
            res = R.per_key(ours, base, theirs, both_changed=both_changed)
            out = []
            for line in res:
                if line.startswith(R.REDERIVE_MARKER):
                    key = line[len(R.REDERIVE_MARKER):]
                    justification = f"merge {today.isoformat()}: re-derived from the merged bytes ({branch} merged into master)"
                    out.append(R.rederive_pin(key=key, root=root, justification=justification, today=today))
                else:
                    out.append(line)
            return out
    elif resolver_name == "count-line":
        def resolver(ours, base, theirs):
            return R.count_line(ours, base, theirs)
    elif resolver_name in R.REGISTRY:
        resolver = R.REGISTRY[resolver_name]
    else:
        raise KeyError(resolver_name)

    return rewrite(target, resolver)


def suggest_for_path(root: Path, rel_path: str) -> list[str]:
    """Ruling Q-4's diagnostic: per conflicted path, every registered
    resolver name whose PRECONDITION the path's block(s) satisfy — never
    a default, just printed alongside a PRV2 refusal."""
    from .conflicts import blocks as parse_blocks

    text = (root / rel_path).read_text()
    _, bl = parse_blocks(text)
    names: set[str] = set()
    for (_s, _e, o, b, t) in bl:
        names |= set(R.candidates_for(o, b, t))
    return sorted(names)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m self_learn.landing.resolve")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--path", required=True)
    ap.add_argument("--resolver")
    ap.add_argument("--branch", default="")
    ap.add_argument("--suggest", action="store_true")
    args = ap.parse_args(argv)

    if args.suggest:
        names = suggest_for_path(args.root.resolve(), args.path)
        print(" ".join(names) if names else "(none)")
        return 0

    if not args.resolver:
        print("REFUSE: --resolver is required unless --suggest", file=sys.stderr)
        return 2
    if args.resolver not in R.REGISTRY:
        print(f"REFUSE: unknown resolver {args.resolver!r}; registry: {sorted(R.REGISTRY)}", file=sys.stderr)
        return 1
    try:
        n = resolve_one(args.root.resolve(), args.path, args.resolver, args.branch)
    except (Refusal, KeyError) as exc:
        print(f"REFUSE: {args.path}: {exc}", file=sys.stderr)
        return 1
    print(f"resolved {args.path}: {n} block(s) via {args.resolver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
