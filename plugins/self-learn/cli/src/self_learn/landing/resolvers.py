"""resolvers.py — the named conflict resolvers, and REGISTRY.

Four resolvers, promoted from the three ad-hoc per-landing scripts'
copy-pasted logic (misc/landing-scripts-2026-08-28/): `keep-both`,
`per-key`, `numeric-rows`, `count-line`. Every one plugs into
`conflicts.rewrite()`'s single driver. None is chosen automatically —
`land` requires `--resolver <path>=<name>` for every conflicted path
(ruling Q-4; RES4).

See docs/specs/self-learn/drafts/u-land-landing-runner-spec.md §4.4.
"""
from __future__ import annotations

import datetime
import hashlib
import re
from pathlib import Path
from typing import Sequence

from .conflicts import Refusal

# ---------------------------------------------------------------------------
# keep-both

def keep_both(ours: list[str], base: list[str], theirs: list[str]) -> list[str]:
    """Purely additive union: `ours + theirs`.

    Refuses when `base` is non-empty, or when `ours` and `theirs` share a
    line (§2.3's "keep-both variant" — an overlap means the hunk was not
    purely additive, and that is exactly when a human should look; the
    variant stays unbuilt by ruling, §3.4).
    """
    if base:
        raise Refusal("keep-both: base is non-empty (not purely additive)")
    overlap = set(ours) & set(theirs)
    if overlap:
        raise Refusal(f"keep-both: ours and theirs share line(s) {sorted(overlap)!r} (overlap)")
    return ours + theirs


# ---------------------------------------------------------------------------
# per-key

_KEY_LINE_RE = re.compile(r"^[^:]+:.*$")

# A sentinel a caller can look for in `per_key`'s output: a both-changed key
# named in `both_changed` produces this marker instead of a value, and the
# caller (the runner, with filesystem access) fills it in via
# `rederive_pin()`. Promoted from resolve-fw117.py's REDERIVE mechanism.
REDERIVE_MARKER = "\x00REDERIVE\x00"


def _per_key_map(side: list[str], side_name: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for line in side:
        if ":" not in line:
            raise Refusal(f"per-key: {side_name} has a line with no ':': {line!r}")
        key = line.split(":", 1)[0].strip()
        if key in keys:
            raise Refusal(f"per-key: {side_name} has a duplicate key {key!r}")
        keys[key] = line
    return keys


def per_key(
    ours: list[str],
    base: list[str],
    theirs: list[str],
    *,
    both_changed: frozenset[str] | None = None,
) -> list[str]:
    """Per-key merge: the side that differs from base wins, per `key: value` line.

    Refuses on: a both-changed key with no re-derive registered (naming the
    key); differing key sets across the three sides; a duplicate key on any
    side; a line with no ':'. `both_changed` is the set of keys the caller
    has pre-approved for the re-derive door (RES5) — this function never
    decides that door is open on its own; it only marks the line.
    """
    both_changed = both_changed or frozenset()
    O = _per_key_map(ours, "ours")
    B = _per_key_map(base, "base")
    T = _per_key_map(theirs, "theirs")
    if not (set(O) == set(B) == set(T)):
        raise Refusal(
            f"per-key: key sets differ (ours^base={set(O) ^ set(B)!r}, "
            f"theirs^base={set(T) ^ set(B)!r})"
        )
    res: list[str] = []
    for key in base:
        k = key.split(":", 1)[0].strip()
        o, t, b = O[k], T[k], B[k]
        if o == b:
            res.append(t)
        elif t == b:
            res.append(o)
        elif o == t:
            res.append(o)
        else:
            if k in both_changed:
                res.append(REDERIVE_MARKER + k)
            else:
                raise Refusal(f"per-key: both sides changed key {k!r} differently, no re-derive registered")
    return res


_JUSTIFICATION_DATE_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b")


def rederive_pin(*, key: str, root: Path, justification: str, today: datetime.date | None = None) -> str:
    """Fill in a REDERIVE_MARKER line: sha256 of the merged bytes + justification.

    `key` is the per-key dict key as it appears in the source, e.g.
    `"plugins/self-learn/cli/tests/test_u_fake.py"` (with the surrounding
    quotes). The path inside the quotes is read from `root` and hashed.
    Refuses (RES5) if `justification` carries no `YYYY-MM-DD` date, or is
    otherwise empty/trivial.
    """
    m = re.match(r'^"([^"]+)"$', key.strip())
    if not m:
        raise Refusal(f"per-key re-derive: key {key!r} is not a quoted path, cannot resolve a pinned file")
    rel = m.group(1)
    target = root / rel
    if not target.exists():
        raise Refusal(f"per-key re-derive: pinned file {rel!r} does not exist under {root}")
    if not _JUSTIFICATION_DATE_RE.search(justification):
        raise Refusal(f"per-key re-derive: justification lacks a YYYY-MM-DD date: {justification!r}")
    reason = _JUSTIFICATION_DATE_RE.sub("", justification).strip(" :-")
    if len(reason) < 3:
        raise Refusal(f"per-key re-derive: justification names no reason: {justification!r}")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    return f'    "{rel}": "{sha}",  # {justification}'


# ---------------------------------------------------------------------------
# numeric-rows

_ROW_RE = re.compile(r"^\| (S|FW)-(\d+) ")


def numeric_rows(ours: list[str], base: list[str], theirs: list[str]) -> list[str]:
    """Union of `ours` and `theirs`, sorted by the `S-`/`FW-` number.

    Refuses when a number appears twice, or the union is non-monotonic
    after sorting (the only way that can happen once sorted is a
    duplicate, but both are checked explicitly for a clearer refusal
    message).
    """
    rows = ours + theirs
    numbered: list[tuple[int, str]] = []
    for row in rows:
        m = _ROW_RE.match(row)
        if not m:
            raise Refusal(f"numeric-rows: row does not match '| S-N ' / '| FW-N ': {row!r}")
        numbered.append((int(m.group(2)), row))
    nums = [n for n, _ in numbered]
    dupes = {n for n in nums if nums.count(n) > 1}
    if dupes:
        raise Refusal(f"numeric-rows: duplicate row number(s) {sorted(dupes)!r}")
    numbered.sort(key=lambda pair: pair[0])
    sorted_nums = [n for n, _ in numbered]
    if sorted_nums != sorted(set(sorted_nums)):
        raise Refusal("numeric-rows: result is non-monotonic after sort")
    return [row for _, row in numbered]


# ---------------------------------------------------------------------------
# count-line

_COUNT_LINE_RE = re.compile(r"assert len\((\w+)\) == (\d+)")


def _count_line_parse(side: list[str], side_name: str) -> tuple[str, int, str]:
    if len(side) != 1:
        raise Refusal(f"count-line: {side_name} is not exactly one line ({len(side)} lines)")
    m = _COUNT_LINE_RE.search(side[0])
    if not m:
        raise Refusal(f"count-line: {side_name} does not match 'assert len(NAME) == N': {side[0]!r}")
    return m.group(1), int(m.group(2)), side[0]


def count_line(
    ours: list[str], base: list[str], theirs: list[str], *, today: datetime.date | None = None
) -> list[str]:
    """`assert len(NAME) == N` resolved as base + (ours delta) + (theirs delta).

    Refuses when any side is not exactly one line, when the three `NAME`s
    differ (N-4 — the registry signature carries no name argument, so this
    resolver must extract and cross-check it itself), or when the
    arithmetic yields a negative count.
    """
    o_name, o_n, o_line = _count_line_parse(ours, "ours")
    b_name, b_n, _ = _count_line_parse(base, "base")
    t_name, t_n, _ = _count_line_parse(theirs, "theirs")
    if not (o_name == b_name == t_name):
        raise Refusal(f"count-line: NAME differs across sides ({o_name!r}, {b_name!r}, {t_name!r})")
    merged = b_n + (o_n - b_n) + (t_n - b_n)
    if merged < 0:
        raise Refusal(f"count-line: arithmetic yields a negative count ({merged})")
    today = today or datetime.date.today()
    justification = (
        f"merge {today.isoformat()}: base {b_n} + ours's delta {o_n - b_n} "
        f"+ theirs's delta {t_n - b_n}"
    )
    new_line = re.sub(r"== \d+.*$", f"== {merged}  # {justification}", o_line)
    return [new_line]


# ---------------------------------------------------------------------------
# registry + suggestions

REGISTRY = {
    "keep-both": keep_both,
    "per-key": per_key,
    "numeric-rows": numeric_rows,
    "count-line": count_line,
}


def satisfies_precondition(name: str, ours: list[str], base: list[str], theirs: list[str]) -> bool:
    """Would resolver `name`'s PRECONDITION accept this block? (never runs the resolution)

    Used by `RES4` leg 2 / `PRV2`'s suggestion surface: an unmapped conflict
    refusal prints the candidate resolver names a block's shape satisfies —
    a diagnostic only, never a default (ruling Q-4).
    """
    if name == "keep-both":
        return not base and not (set(ours) & set(theirs))
    if name == "per-key":
        try:
            O, B, T = (_per_key_map(s, n) for s, n in ((ours, "ours"), (base, "base"), (theirs, "theirs")))
        except Refusal:
            return False
        return set(O) == set(B) == set(T)
    if name == "numeric-rows":
        return bool(ours or theirs) and all(_ROW_RE.match(row) for row in ours + theirs)
    if name == "count-line":
        try:
            for side, sn in ((ours, "ours"), (base, "base"), (theirs, "theirs")):
                _count_line_parse(side, sn)
        except Refusal:
            return False
        return True
    raise KeyError(name)


def candidates_for(ours: list[str], base: list[str], theirs: list[str]) -> list[str]:
    """Every registered resolver name whose precondition this block satisfies."""
    return [name for name in REGISTRY if satisfies_precondition(name, ours, base, theirs)]
