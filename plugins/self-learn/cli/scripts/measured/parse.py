#!/usr/bin/env python3
"""parse.py — UN4 leg (c)/(a): parse and RUN every §6.1 ledger block.

Each block's `measure:` command runs from the REPO ROOT (matching every
pasted command in the spec, which is written relative to it); its
stdout's LAST LINE is compared to `expect:`. A non-zero exit from the
`measure:` command is itself a failure — N-22's hardening: a missing
dependency must fail loudly, never read as an empty/wrong value at rc 0.

Usage:
  parse.py [<root-to-run-against>] [<spec-path>]
Defaults: root = this script's own repo root (git rev-parse
--show-toplevel from HERE); spec = spec_path().
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from floor import BLOCK_RE, ROOT, section, spec_path  # noqa: E402


def run_ledger(spec: Path, root: Path) -> tuple[int, int, list[str]]:
    text = spec.read_text()
    ledger_section = section(text, "### 6.1 The MEASURED ledger", "## 7. Scope")
    blocks = list(BLOCK_RE.finditer(ledger_section))
    passed = failed = 0
    lines: list[str] = []
    for m in blocks:
        mid, cmd, expect = m.group(1), m.group("cmd"), m.group("expect")
        proc = subprocess.run(["bash", "-c", cmd], cwd=root, capture_output=True, text=True)
        stripped = proc.stdout.rstrip("\n")
        last = stripped.split("\n")[-1] if stripped else ""
        ok = proc.returncode == 0 and last == expect
        status = "OK" if ok else "FAIL"
        lines.append(f"  {mid}  {status} rc={proc.returncode}  {last!r} (expect {expect!r})")
        if ok:
            passed += 1
        else:
            failed += 1
    return passed, failed, lines


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]).resolve() if argv else ROOT
    spec = Path(argv[1]) if len(argv) > 1 else spec_path()
    misc_present = "yes" if (root / "misc").exists() else "no"
    print(f"cwd={root}   misc/ present? {misc_present}")
    passed, failed, lines = run_ledger(spec, root)
    for l in lines:
        print(l)
    print(f"pass={passed} fail={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
