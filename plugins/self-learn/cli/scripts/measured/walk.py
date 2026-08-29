#!/usr/bin/env python3
"""walk.py — §4.6a's AST walk, shipped as runnable code (gate M-2).

A measurement instrument (0 collected pytest ids), not a test — ships
under scripts/measured/, never under tests/ (gate M-23: staged under
tests/ this module's own CORPUS regex constant, `'(^|[^\\w])docs/'`, is
itself a strict hit, which would count the walk in its own output).

Usage:
  walk.py <scope> <column>   scope: src | tests   column: naive | incl | strict
  walk.py --union            the docs-only lane's module set (direct hit
                              UNION part-built), repo-relative, one per line, sorted
  walk.py --direct           direct-hit test modules only
  walk.py --part-built       part-built (no direct hit) test modules only

Roots: cli/tests + ui/tests for "tests"; cli/src + ui/src for "src" —
resolved from THIS FILE's own on-disk location (so a --dry-run copy at
$TMP walks $TMP's tree), never from the caller's cwd.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

CORPUS = re.compile(r"(^|[^\w])docs/")  # a corpus doc == a path under docs/

HERE = Path(__file__).resolve().parent
ROOT = Path(
    subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
)
assert (ROOT / "docs/specs/self-learn").is_dir(), f"{ROOT} is not the self-learn repo root"

SRC_ROOTS = ["plugins/self-learn/cli/src", "plugins/self-learn/ui/src"]
TEST_ROOTS = ["plugins/self-learn/cli/tests", "plugins/self-learn/ui/tests"]


def docstring_ids(tree: ast.AST) -> set[int]:
    o: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = getattr(n, "body", None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
               and isinstance(b[0].value.value, str):
                o.add(id(b[0].value))
    return o


def _consts(path: Path) -> tuple[list[ast.Constant], set[int]]:
    tree = ast.parse(path.read_text())
    skip = docstring_ids(tree)
    consts = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return consts, skip


def naive_hits(path: Path) -> int:
    """The grep-shaped count: lines of raw file TEXT matching CORPUS — no
    AST, so it also catches matches inside comments and f-string literals
    an ast.Constant walk cannot see. This is the count r2's prose (wrongly)
    claimed was "strict" (§3.5a item 1); kept here, clearly labelled, so a
    docstring-inclusive AST count can never again be presented as it."""
    return sum(1 for line in path.read_text().splitlines() if CORPUS.search(line))


def incl_hits(path: Path) -> int:
    """AST-based, EVERY string Constant, docstrings included."""
    consts, _ = _consts(path)
    return sum(1 for n in consts if CORPUS.search(n.value))


def strict_hits(path: Path) -> int:
    consts, skip = _consts(path)
    return sum(1 for n in consts if id(n) not in skip and CORPUS.search(n.value))


def _files(scope: str) -> list[Path]:
    roots = SRC_ROOTS if scope == "src" else TEST_ROOTS
    out: list[Path] = []
    for r in roots:
        out += sorted((ROOT / r).rglob("*.py"))
    return out


def column_total(scope: str, column: str) -> int:
    fn = {"naive": naive_hits, "incl": incl_hits, "strict": strict_hits}[column]
    total = 0
    for f in _files(scope):
        try:
            total += fn(f)
        except SyntaxError:
            continue
    return total


def direct_hit_modules() -> list[str]:
    out = []
    for f in _files("tests"):
        try:
            if strict_hits(f) > 0:
                out.append(str(f.relative_to(ROOT)))
        except SyntaxError:
            continue
    return sorted(out)


def part_built_modules() -> list[str]:
    """A test module holding 'docs' and 'specs' as SEPARATE bare constants
    but no direct hit — the part-built residual (FW-142)."""
    out = []
    for f in _files("tests"):
        try:
            consts, _ = _consts(f)
            if strict_hits(f) > 0:
                continue
            values = {n.value for n in consts}
            if "docs" in values and "specs" in values:
                out.append(str(f.relative_to(ROOT)))
        except SyntaxError:
            continue
    return sorted(out)


def lane_set() -> list[str]:
    return sorted(set(direct_hit_modules()) | set(part_built_modules()))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--union":
        print("\n".join(lane_set()))
        return 0
    if argv and argv[0] == "--direct":
        print("\n".join(direct_hit_modules()))
        return 0
    if argv and argv[0] == "--part-built":
        print("\n".join(part_built_modules()))
        return 0
    if len(argv) == 2:
        scope, column = argv
        if scope not in ("src", "tests") or column not in ("naive", "incl", "strict"):
            print(f"usage: walk.py <src|tests> <naive|incl|strict>", file=sys.stderr)
            return 2
        print(column_total(scope, column))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
