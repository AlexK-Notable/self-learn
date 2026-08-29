"""conflicts.py — the ONE diff3 parser and the ONE rewrite driver.

Lifted from the three ad-hoc scripts' identical, copy-pasted ``blocks()``
(misc/landing-scripts-2026-08-28/resolve-{cachelit,fw117,hostmode}.py) and
their shared ``rewrite()`` driver. There is exactly one parser and one
driver in this package; every resolver in ``resolvers.py`` plugs into it.

See docs/specs/self-learn/drafts/u-land-landing-runner-spec.md §4.4.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Sequence

MARKER_RE = re.compile(r"^(<<<<<<<|=======|>>>>>>>|\|\|\|\|\|\|\|)", re.M)

# A block as (start_line, end_line, ours, base, theirs). start/end are line
# indices into the split-on-"\n" text; end is the line index of the
# ">>>>>>> " marker (inclusive of the marker line itself).
Block = tuple[int, int, list[str], list[str], list[str]]


class ConflictParseError(Exception):
    """The text does not parse as diff3-style conflict markers."""


class Refusal(Exception):
    """A resolver refuses to resolve a block; carries a human reason."""


def has_base_markers(text: str) -> bool:
    """PRV3's pre-resolver check: at least one ``|||||||`` line exists.

    Under ``merge.conflictStyle=merge`` (not diff3) there is no base marker
    at all and a real diff3 parse would walk off the end of the file. The
    runner asserts this BEFORE invoking any resolver — see §2.4/PRV3.
    """
    return any(line.startswith("||||||| ") for line in text.split("\n"))


def blocks(text: str) -> tuple[list[str], list[Block]]:
    """Parse every diff3 conflict block in `text`.

    Returns (lines, blocks) where `lines` is `text.split("\\n")` and each
    block is (start, end, ours, base, theirs). Raises ConflictParseError on
    a truncated/malformed marker sequence (e.g. no base marker at all —
    the merge-style-not-diff3 case PRV3 exists to prevent reaching here).
    """
    lines = text.split("\n")
    i = 0
    n = len(lines)
    out: list[Block] = []
    while i < n:
        if lines[i].startswith("<<<<<<< "):
            s = i
            i += 1
            ours: list[str] = []
            while i < n and not lines[i].startswith("||||||| "):
                ours.append(lines[i])
                i += 1
            if i >= n:
                raise ConflictParseError(
                    f"block starting at line {s + 1}: no ||||||| base marker "
                    "(merge.conflictStyle is not diff3?)"
                )
            i += 1
            base: list[str] = []
            while i < n and lines[i] != "=======":
                base.append(lines[i])
                i += 1
            if i >= n:
                raise ConflictParseError(f"block starting at line {s + 1}: no ======= marker")
            i += 1
            theirs: list[str] = []
            while i < n and not lines[i].startswith(">>>>>>> "):
                theirs.append(lines[i])
                i += 1
            if i >= n:
                raise ConflictParseError(f"block starting at line {s + 1}: no >>>>>>> marker")
            out.append((s, i, ours, base, theirs))
            i += 1
        else:
            i += 1
    return lines, out


Resolver = Callable[[list[str], list[str], list[str]], Sequence[str]]


def rewrite(path: Path, resolver: Resolver) -> int:
    """Rewrite `path` in place, resolving every conflict block with `resolver`.

    `resolver(ours, base, theirs)` returns the replacement lines for one
    block, or raises Refusal. Returns the number of blocks resolved.
    Raises ConflictParseError if the file has no blocks, or if a marker
    somehow remains after every block was resolved (defence in depth: a
    correct resolver can never leave one, so this is unreachable in
    practice and exists as the same final assertion the three ad-hoc
    scripts each carried).
    """
    text = path.read_text()
    lines, bl = blocks(text)
    if not bl:
        raise ConflictParseError(f"{path}: no conflict blocks")
    new: list[str] = []
    last = 0
    for (s, e, o, b, t) in bl:
        new.extend(lines[last:s])
        new.extend(resolver(o, b, t))
        last = e + 1
    new.extend(lines[last:])
    out = "\n".join(new)
    if MARKER_RE.search(out):
        raise ConflictParseError(f"{path}: conflict markers remain after rewrite")
    path.write_text(out)
    return len(bl)
