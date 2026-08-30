"""checks.py — the landing checks (CHK1-CHK7) and world detection (WLD1/WLD2).

Runs INSIDE the merge, after resolvers have staged their rewrites and
before `git commit` (§4.5's chain). `land` (the bash runner) shells out to
`python3 -m self_learn.landing.checks <subcommand> ...` and branches on the
exit code; every function here also raises CheckFailure for direct/test
use.

CHK5 (the personal-literals gate) is deliberately NOT reimplemented here —
`land` invokes U-scrub's shipped `test_personal_literals.py` directly
(§2.5, §4.5 CHK5). A second implementation here would be a second thing to
keep correct.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

MARKER_RE = re.compile(r"^(<<<<<<<|=======|>>>>>>>|\|\|\|\|\|\|\|)", re.M)
PIN_RE = re.compile(r'^\s+"(plugins/[^"]+)": "([0-9a-f]{64})"', re.M)
ROW_RE = re.compile(r"^\| (S|FW)-(\d+) ")

# Promoted verbatim from misc/landing-scripts-2026-08-28/landing-checks.py.
PROSE_RE = re.compile(
    r"worktree left uncommitted|not yet merged/pushed|follows this note"
    r"|Uncommitted\. Spec only|still uncommitted",
    re.I,
)
# A spec's own sweep table quoting one of the patterns as evidence, e.g.
# "still uncommitted 6 0" (a historical/cited/live count row) — exempt.
QUOTED_EXEMPT_RE = re.compile(r"^(still uncommitted|not yet merged)\s+\d+\s+\d+")

# Built from SEPARATE constants, never one literal containing "docs/" — a
# src/ module holding such a literal is a real hit under §4.6a's strict
# walk and would permanently force the docs-only lane's SUI7 leg (b)
# detector to full (the same "part-built" shape test_reader_contract.py
# uses, deliberately, so this module never becomes the thing that leg
# exists to catch).
_D = "docs"
_SPEC_DIR = _D + "/specs/self-learn"
DEFAULT_DOCS = [
    _SPEC_DIR + "/14-forward-work-map.md",
    _SPEC_DIR + "/03-decisions.md",
    _SPEC_DIR + "/13-hosting-and-separation.md",
]
DRAFTS_SUBDIR = _SPEC_DIR + "/drafts"

WORLD_REMEASURE = "remeasure"
WORLD_ARMOR_SHAS = "armor_shas"


class CheckFailure(Exception):
    pass


# ---------------------------------------------------------------------------
# CHK1 — conflict markers, over the merge-touched set (not a hardcoded list)

def check_no_markers(paths: list[Path]) -> None:
    hits = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except (UnicodeDecodeError, OSError):
            continue
        if MARKER_RE.search(text):
            hits.append(str(p))
    if hits:
        raise CheckFailure(f"conflict markers found in: {hits}")


# ---------------------------------------------------------------------------
# CHK2 — every armor pin vs live bytes (pre-U-armor world only; WLD1)

def check_pins(root: Path) -> tuple[int, list[tuple[str, str, str]]]:
    wc_path = root / "plugins/self-learn/cli/tests/test_worker_contract.py"
    text = wc_path.read_text()
    pins = dict(PIN_RE.findall(text))
    mismatches: list[tuple[str, str, str]] = []
    for rel, expected in pins.items():
        target = root / rel
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else "<absent>"
        if actual != expected:
            mismatches.append((rel, expected[:12], actual[:12]))
    return len(pins), mismatches


def check_pins_or_raise(root: Path) -> int:
    n, mism = check_pins(root)
    if n < 1:
        raise CheckFailure(f"pins checked: {n}; refusing -- N < 1 (absence must not read as clean)")
    if mism:
        raise CheckFailure(f"pins checked: {n}; mismatches: {mism}")
    return n


# ---------------------------------------------------------------------------
# CHK3 — S-/FW- row order, monotonic + duplicate-free PER CONTIGUOUS RUN

def _row_runs(lines: list[str], prefix: str) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    prev_idx: int | None = None
    for i, line in enumerate(lines):
        m = ROW_RE.match(line)
        if m and m.group(1) == prefix:
            n = int(m.group(2))
            if prev_idx is not None and i == prev_idx + 1:
                current.append(n)
            else:
                if current:
                    runs.append(current)
                current = [n]
            prev_idx = i
    if current:
        runs.append(current)
    return runs


def check_row_order(text: str, prefix: str) -> list[tuple[int, int]]:
    """Return every (a, b) adjacent-in-run pair where b <= a."""
    runs = _row_runs(text.split("\n"), prefix)
    bad: list[tuple[int, int]] = []
    for run in runs:
        bad.extend((a, b) for a, b in zip(run, run[1:]) if b <= a)
    return bad


def check_duplicate_rows(text: str, prefix: str) -> list[int]:
    """Every row id appearing twice inside ONE contiguous table run.

    This is the half of CHK3 with a red/green pair on real history --
    measured 2026-08-29 with this function: at `37f48c4` it returns
    `[130]` (the duplicate a keep-both merge left) and at its child
    `6038eee`, at `master`, and at this branch's HEAD it returns `[]`.

    Per-run, not whole-file: `FW-30` legitimately appears in two
    different tables (the row itself at line 85 and a later index run of
    length 1), so a whole-file duplicate check reddens on correct content
    -- measured, it returns `[130, 30]` at `37f48c4` and `[30]` at
    `6038eee`, i.e. it cannot tell the defect from the corpus."""
    dupes: list[int] = []
    for run in _row_runs(text.split("\n"), prefix):
        seen: set[int] = set()
        for n in run:
            if n in seen and n not in dupes:
                dupes.append(n)
            seen.add(n)
    return dupes


def check_row_order_or_raise(root: Path, base: dict[str, str] | None = None) -> None:
    """CHK3, two legs.

    Leg 1 -- **duplicates refuse, always.** Whole file, both prefixes.

    Leg 2 -- **a landing may not ADD row disorder.** Measured on the real
    tree 2026-08-29: `14-forward-work-map.md` carries **9** descending
    adjacent pairs on master (`[(53,52), (52,49), (70,62), (67,57),
    (61,54), (56,50), (127,120), (132,128), (131,122)]`), and they are
    *inside one contiguous table* -- FW-48/53/52/49/60/61/54 sit on
    consecutive lines, grouped by fix batch rather than by number. So the
    spec's "per contiguous table run" framing (§4.5 CHK3, §11 item 5,
    which flags exactly this as unconfirmed) does not rescue them: a
    check that demands global monotonicity refuses EVERY landing,
    including this unit's own. With `base` supplied -- the pre-merge
    content of the same files -- the check refuses only on pairs the
    merge INTRODUCED, which keeps the teeth (`test_land_refuses_row_
    disorder`'s fixture still reddens) without asserting a property the
    corpus has never had. With `base` omitted the old strict form is
    kept, so a caller that has no baseline still fails closed.

    `base` maps the repo-relative doc path to its baseline text.
    """
    paths = {
        "FW": _SPEC_DIR + "/14-forward-work-map.md",
        "S": _SPEC_DIR + "/03-decisions.md",
    }
    dupes: dict[str, list[int]] = {}
    added: dict[str, list[tuple[int, int]]] = {}
    for prefix, rel in paths.items():
        text = (root / rel).read_text()
        d = check_duplicate_rows(text, prefix)
        if d:
            dupes[prefix] = d
        bad = check_row_order(text, prefix)
        if base is not None and rel in base:
            before = set(check_row_order(base[rel], prefix))
            bad = [p for p in bad if p not in before]
        if bad:
            added[prefix] = bad
    if dupes or added:
        raise CheckFailure(
            f"row duplicates: {dupes or '{}'}; row order violations "
            f"{'INTRODUCED by this merge' if base is not None else '(no baseline supplied)'}: "
            f"{added or '{}'}"
        )


# ---------------------------------------------------------------------------
# CHK4 — landing-state prose, quoted-pattern exemption preserved

def check_prose(root: Path, docs: list[str] | None = None) -> list[str]:
    docs = list(docs) if docs is not None else list(DEFAULT_DOCS)
    drafts_dir = root / DRAFTS_SUBDIR
    if drafts_dir.is_dir():
        docs += [
            str(p.relative_to(root)) for p in sorted(drafts_dir.glob("u-*.md"))
        ]
    hits: list[str] = []
    for rel in docs:
        p = root / rel
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text().split("\n"), 1):
            if PROSE_RE.search(line) and not QUOTED_EXEMPT_RE.match(line):
                hits.append(f"{rel}:{i}")
    return hits


def check_prose_or_raise(root: Path, docs: list[str] | None = None) -> None:
    hits = check_prose(root, docs)
    if hits:
        raise CheckFailure(f"landing-state prose hits: {hits}")


# ---------------------------------------------------------------------------
# CHK6 — verdict shape

SUBJECT_BUDGET = 200


def check_verdict_or_raise(verdict: str) -> None:
    if not verdict:
        raise CheckFailure("--verdict is empty")
    if "\n" in verdict:
        raise CheckFailure("--verdict contains a newline")
    if len(verdict) > SUBJECT_BUDGET:
        raise CheckFailure(f"--verdict is {len(verdict)} chars, over the {SUBJECT_BUDGET}-char budget")


# ---------------------------------------------------------------------------
# WLD1/WLD2 — world detection, POST-merge, over the staged tree

def detect_world(root: Path) -> str:
    has_armor = (root / "plugins/self-learn/cli/tests/test_armor.py").exists()
    wc_path = root / "plugins/self-learn/cli/tests/test_worker_contract.py"
    has_shas = 0
    if wc_path.exists():
        has_shas = len(PIN_RE.findall(wc_path.read_text()))
    if has_armor and has_shas == 0:
        return WORLD_REMEASURE
    if not has_armor and has_shas > 0:
        return WORLD_ARMOR_SHAS
    if has_armor and has_shas > 0:
        raise CheckFailure("BOTH armor mechanisms present -- ambiguous")
    raise CheckFailure("NEITHER armor mechanism present -- refusing to land unguarded")


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m self_learn.landing.checks")
    ap.add_argument("--root", required=True, type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_markers = sub.add_parser("markers")
    p_markers.add_argument("paths", nargs="*")

    sub.add_parser("pins")
    p_roworder = sub.add_parser("roworder")
    p_roworder.add_argument(
        "--base",
        default=None,
        help="a git rev whose copies of the two row files are the baseline "
             "(CHK3 leg 2 then refuses only on disorder this merge ADDED). "
             "Omitted, the check is the strict whole-file form.",
    )
    sub.add_parser("prose")

    p_verdict = sub.add_parser("verdict")
    p_verdict.add_argument("--verdict", required=True)

    sub.add_parser("world")

    args = ap.parse_args(argv)
    root: Path = args.root.resolve()
    try:
        if args.cmd == "markers":
            check_no_markers([root / p for p in args.paths])
            print("no conflict markers")
        elif args.cmd == "pins":
            n = check_pins_or_raise(root)
            print(f"pins checked: {n}; mismatches: []")
        elif args.cmd == "roworder":
            base = None
            if args.base:
                import subprocess

                base = {}
                for rel in (
                    _SPEC_DIR + "/14-forward-work-map.md",
                    _SPEC_DIR + "/03-decisions.md",
                ):
                    proc = subprocess.run(
                        ["git", "show", f"{args.base}:{rel}"],
                        cwd=root, capture_output=True, text=True,
                    )
                    # A file absent at the baseline is a NEW file: it has no
                    # prior disorder to forgive, so it stays strict. It must
                    # never silently become "no baseline, forgive nothing"
                    # for the OTHER file too.
                    if proc.returncode == 0:
                        base[rel] = proc.stdout
            check_row_order_or_raise(root, base)
            print(
                "row order OK"
                + (f" (baseline {args.base}: {len(base or {})} file(s))" if args.base else "")
            )
        elif args.cmd == "prose":
            check_prose_or_raise(root)
            print("no landing-state prose")
        elif args.cmd == "verdict":
            check_verdict_or_raise(args.verdict)
            print("verdict OK")
        elif args.cmd == "world":
            print(detect_world(root))
    except CheckFailure as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
