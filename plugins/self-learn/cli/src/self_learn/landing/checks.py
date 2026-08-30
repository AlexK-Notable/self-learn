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

def check_no_markers(paths: list[Path]) -> int:
    """CHK1. Returns the number of files actually SCANNED.

    Floor rule (gate r2 MAJOR-5): a check that can return an empty result
    must distinguish "I looked and found nothing" from "I could not look".
    Three ways this one could previously return clean without looking:
    a path that is not a regular file was skipped, an unreadable file was
    skipped, and an EMPTY path list scanned nothing at all. The first two
    are now fatal and the third is floored by the caller, which compares
    the returned count against the set it asked for."""
    hits: list[str] = []
    unreadable: list[str] = []
    scanned = 0
    for p in paths:
        if not p.exists():
            # a merge-touched path that has been DELETED is legitimately
            # absent; a marker cannot hide in a file that is not there
            continue
        if not p.is_file():
            unreadable.append(f"{p} (not a regular file)")
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError as exc:
            unreadable.append(f"{p} ({exc.__class__.__name__})")
            continue
        scanned += 1
        if MARKER_RE.search(text):
            hits.append(str(p))
    if unreadable:
        raise CheckFailure(
            f"could not read {len(unreadable)} of the {len(paths)} merge-touched "
            f"path(s), so 'no conflict markers' would be a claim about files "
            f"this check never opened: {unreadable}"
        )
    if hits:
        raise CheckFailure(f"conflict markers found in: {hits}")
    return scanned


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
    parsed: dict[str, int] = {}
    for prefix, rel in paths.items():
        src = root / rel
        if not src.is_file():
            raise CheckFailure(
                f"CHK3: the {prefix}- row file is ABSENT ({rel}); a clean row "
                "order over a file that is not there is not a result"
            )
        text = src.read_text()
        parsed[prefix] = sum(len(r) for r in _row_runs(text.split("\n"), prefix))
        d = check_duplicate_rows(text, prefix)
        if d:
            dupes[prefix] = d
        bad = check_row_order(text, prefix)
        if base is not None and rel in base:
            before = set(check_row_order(base[rel], prefix))
            bad = [p for p in bad if p not in before]
        if bad:
            added[prefix] = bad
    empty = [p for p, n in parsed.items() if n < 1]
    if empty:
        raise CheckFailure(
            f"CHK3: parsed ZERO {empty} rows; refusing -- no violations over no "
            f"rows is not a result (parsed: {parsed})"
        )
    if dupes or added:
        raise CheckFailure(
            f"row duplicates: {dupes or '{}'}; row order violations "
            f"{'INTRODUCED by this merge' if base is not None else '(no baseline supplied)'}: "
            f"{added or '{}'}"
        )


# ---------------------------------------------------------------------------
# CHK4 — landing-state prose, quoted-pattern exemption preserved

def check_prose(root: Path, docs: list[str] | None = None) -> tuple[list[str], int, list[str]]:
    """CHK4. Returns (hits, docs_read, missing).

    Floor rule (gate r2 MAJOR-5): this used to `continue` past any doc that
    was not a file, so a tree missing all three named docs returned `[]`
    and the CLI printed "no landing-state prose" -- the identical shape
    `CHK1` was given a floor for in the same round. The caller now refuses
    on a missing NAMED doc and on a zero read count."""
    named = list(docs) if docs is not None else list(DEFAULT_DOCS)
    globbed: list[str] = []
    drafts_dir = root / DRAFTS_SUBDIR
    if drafts_dir.is_dir():
        globbed = [str(p.relative_to(root)) for p in sorted(drafts_dir.glob("u-*.md"))]
    hits: list[str] = []
    missing: list[str] = []
    read = 0
    for rel in named + globbed:
        p = root / rel
        if not p.is_file():
            # a NAMED doc that is absent is a hole; a globbed one cannot be
            missing.append(rel)
            continue
        read += 1
        for i, line in enumerate(p.read_text().split("\n"), 1):
            if PROSE_RE.search(line) and not QUOTED_EXEMPT_RE.match(line):
                hits.append(f"{rel}:{i}")
    return hits, read, [m for m in missing if m in named]


def check_prose_or_raise(root: Path, docs: list[str] | None = None) -> int:
    hits, read, missing = check_prose(root, docs)
    if missing:
        raise CheckFailure(
            f"{len(missing)} named landing-state doc(s) are ABSENT, so a clean "
            f"result would describe files this check never opened: {missing}"
        )
    if read < 1:
        raise CheckFailure(
            "read 0 documents; refusing -- 'no landing-state prose' over zero "
            "files is not a result"
        )
    if hits:
        raise CheckFailure(f"landing-state prose hits: {hits}")
    return read


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
            # The floor is on being GIVEN nothing, not on FINDING nothing to
            # read: a merge that only DELETES files legitimately scans zero,
            # and refusing that would be a false refusal (measured -- it
            # refused a delete-only branch). Paths that exist but cannot be
            # read are already fatal inside check_no_markers.
            if not args.paths:
                raise CheckFailure(
                    "given 0 paths; refusing -- 'no conflict markers' over an "
                    "empty set is not a result"
                )
            n = check_no_markers([root / p for p in args.paths])
            # positive control in the OUTPUT: a clean result always carries
            # the counts it is a claim about, so "nothing found" and "nothing
            # looked at" never render the same.
            print(
                f"no conflict markers (scanned {n} of {len(args.paths)} "
                f"merge-touched path(s); {len(args.paths) - n} absent/deleted)"
            )
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
            n = check_prose_or_raise(root)
            print(f"no landing-state prose (read {n} document(s))")
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
