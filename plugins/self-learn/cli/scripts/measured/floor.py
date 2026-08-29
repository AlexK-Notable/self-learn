#!/usr/bin/env python3
"""floor.py — UN4 leg (b): the DERIVED floor.

Compares the SET of mutation ids labelled **MEASURED** in the spec's
section 6 (the mutation plan) against the SET of ```measured M<n>``` block
ids in section 6.1 (the ledger), and reports missing/extra — both must be
empty for UN4 to hold. Also checks the three label counts (MEASURED /
OBSERVED / predicted) against section 6's own totals line, and refuses
any mutation row carrying a bold MEASURED/OBSERVED token OUTSIDE its
status column (N-26 — a substring scan of a row whose evidence cell
merely NAMES the other label would otherwise miscount it).

Usage:
  floor.py [--delete-one] [<spec-path>]

Exit 0 iff missing/extra are both empty AND the totals line MATCHes;
exit 1 on a real mismatch; exit 3 if the spec cannot be found/parsed
(spec_path()'s N-27 fix: the caller tests the substitution itself; this
script IS the caller of its own spec_path(), so it just raises directly).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(
    subprocess.run(
        ["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

BOLD_LABEL_RE = re.compile(r"\*\*(MEASURED|OBSERVED)\*\*")
BLOCK_RE = re.compile(r"```measured (M\d+)\nmeasure: (?P<cmd>.*)\nexpect: (?P<expect>.*)\n```")
TOTALS_RE = re.compile(
    r"\*\*Totals:\s*(\d+)\s*mutations\s*.\s*(\d+)\s*MEASURED[^,]*,\s*(\d+)\s*OBSERVED,\s*(\d+)\s*predicted\.\*\*"
)


def spec_path() -> Path:
    matches = sorted((ROOT / "docs/specs/self-learn").glob("**/u-land-*.md"))
    if len(matches) != 1:
        print(f"FATAL: expected exactly 1 u-land-*.md, found {len(matches)}", file=sys.stderr)
        raise SystemExit(3)
    return matches[0]


def section(text: str, start_marker: str, end_marker: str) -> str:
    i = text.index(start_marker)
    j = text.index(end_marker, i)
    return text[i:j]


def parse_mutation_rows(mutation_section: str) -> list[dict]:
    rows = []
    for line in mutation_section.split("\n"):
        m = re.match(r"^\|\s*(M\d+)\s*\|(.*)\|\s*$", line)
        if not m:
            continue
        mid, rest = m.group(1), m.group(2)
        cells = rest.split("|")
        if len(cells) < 2:
            continue
        status_cell = cells[-1]
        other_cells = cells[:-1]
        stray = any(BOLD_LABEL_RE.search(c) for c in other_cells)
        lm = BOLD_LABEL_RE.search(status_cell)
        label = lm.group(1) if lm else "predicted"
        rows.append({"id": mid, "label": label, "stray_bold": stray})
    return rows


def parse_ledger_blocks(ledger_section: str) -> dict[str, tuple[str, str]]:
    return {m.group(1): (m.group("cmd"), m.group("expect")) for m in BLOCK_RE.finditer(ledger_section)}


def _numkey(mid: str) -> int:
    return int(mid[1:])


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    delete_one = "--delete-one" in argv
    positional = [a for a in argv if a != "--delete-one"]
    spec = Path(positional[0]) if positional else spec_path()
    text = spec.read_text()

    mutation_section = section(text, "## 6. Mutation plan", "## 7. Scope")
    ledger_section = section(text, "### 6.1 The MEASURED ledger", "## 7. Scope")

    rows = parse_mutation_rows(mutation_section)
    blocks = parse_ledger_blocks(ledger_section)

    stray = [r["id"] for r in rows if r["stray_bold"]]
    if stray:
        print(f"FATAL: bold label token outside the status column: {stray}", file=sys.stderr)
        return 3

    measured_ids = {r["id"] for r in rows if r["label"] == "MEASURED"}
    block_ids = set(blocks.keys())

    if delete_one:
        first = sorted(block_ids, key=_numkey)[0]
        block_ids = block_ids - {first}

    missing = sorted(measured_ids - block_ids, key=_numkey)
    extra = sorted(block_ids - measured_ids, key=_numkey)

    counts = {"MEASURED": 0, "OBSERVED": 0, "predicted": 0}
    for r in rows:
        counts[r["label"]] += 1
    total = len(rows)

    tm = TOTALS_RE.search(mutation_section)
    totals_match = "UNKNOWN"
    if tm:
        t_total, t_meas, t_obs, t_pred = (int(x) for x in tm.groups())
        totals_match = (
            "MATCH"
            if (t_total, t_meas, t_obs, t_pred) == (total, counts["MEASURED"], counts["OBSERVED"], counts["predicted"])
            else "MISMATCH"
        )

    print(
        f"measured={len(measured_ids)} blocks={len(block_ids)} "
        f"missing={','.join(missing) or 'none'} extra={','.join(extra) or 'none'}"
    )
    print(
        f"labels total={total} MEASURED={counts['MEASURED']} OBSERVED={counts['OBSERVED']} "
        f"predicted={counts['predicted']} unlabelled=0"
    )
    print(f"totals-line {totals_match} stray-bold=none")

    return 0 if (not missing and not extra and totals_match == "MATCH") else 1


if __name__ == "__main__":
    raise SystemExit(main())
