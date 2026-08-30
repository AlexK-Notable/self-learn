"""suites.py — Step 4's suite adjudication, in ONE frame (SUI3/SUI4/SUI9).

**Why this module exists (gate r1 B-1).** `known_failures.txt` names node
ids repo-root-relative. pytest prints them relative to its own invocation
directory. Those are two different frames, and the runner ran the UI suite
from `plugins/self-learn/ui` while the allowlist said
`plugins/self-learn/ui/tests/test_service_unit.py::…` — so the one
genuinely-allowlisted failure in the repository read as *not* allowlisted
and **every real landing refused**, this unit's own bootstrap included.

Rewriting the literal into the other frame is not the fix: it only moves
which frame is wrong, and the next suite added from a different directory
reintroduces it. Instead every node id — parsed from a log, or read from
the allowlist — is RESOLVED against the directory it was produced in and
re-expressed **repo-root-relative** before anything is compared. The runner
hands this module the same `--cwd` it handed the suite, so the allowlist
cannot drift from the invocation again.

The same normalisation serves `SUI4`: to ask whether an allowlist entry
still collects, you must run pytest from the package that owns it, which is
found by walking up to the nearest `pyproject.toml` rather than by a
hardcoded table.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

#: pytest's short-summary lines. `ERROR ` (with the space) is a collection
#: or fixture error against a node id; `ERRORS` section headers are not.
FAIL_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)

VERDICT_OK = "allowlisted-only"
VERDICT_UNPARSEABLE = "unparseable-log"
VERDICT_NO_ALLOWLIST = "unreadable-allowlist"
VERDICT_NOT_ALLOWLISTED = "not-allowlisted"


class FrameError(ValueError):
    pass


def parse_failing(log_text: str) -> list[str]:
    """Every node id named by a FAILED/ERROR short-summary line, deduped
    and sorted. Order is stabilised so a verdict line is comparable."""
    return sorted(set(FAIL_RE.findall(log_text)))


def split_node_id(node_id: str) -> tuple[str, str]:
    """`path::test[param]` -> (`path`, `::test[param]`). A parameter id may
    itself contain `::`, so the split is on the FIRST one."""
    head, sep, tail = node_id.partition("::")
    return head, (sep + tail)


def to_root_frame(node_id: str, cwd: Path, root: Path) -> str:
    """Re-express one node id repo-root-relative.

    `cwd` is the directory the id was produced in — pytest's invocation
    directory for a log line, or the repo root for an allowlist entry.
    Absolute ids, `../`-relative ids (pytest emits these when handed a path
    outside its rootdir) and plain relative ids all normalise the same way,
    because the file part is resolved to an absolute path first.
    """
    file_part, rest = split_node_id(node_id)
    p = Path(file_part)
    absolute = p if p.is_absolute() else (cwd / p)
    absolute = Path(os.path.normpath(str(absolute)))
    try:
        rel = absolute.relative_to(root)
    except ValueError as exc:
        raise FrameError(
            f"node id {node_id!r} resolves to {absolute}, which is outside the "
            f"repository root {root} — it cannot be adjudicated against a "
            f"root-relative allowlist"
        ) from exc
    return str(rel) + rest


def allowlist_entries(allow_path: Path) -> list[str]:
    """Non-blank, non-comment lines. The file is authored root-relative;
    it is normalised anyway, so a hand-edit in another frame is corrected
    rather than silently mismatched."""
    return [
        ln.strip()
        for ln in allow_path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def package_root_for(root: Path, rel_file: str) -> Path:
    """The directory pytest must run from to collect `rel_file`: the nearest
    ancestor holding a `pyproject.toml`, falling back to the repo root.
    Derived, never a hardcoded suite table — that is what B-1 was."""
    d = (root / rel_file).parent
    while True:
        if (d / "pyproject.toml").is_file():
            return d
        if d == root or d.parent == d:
            return root
        d = d.parent


def adjudicate(
    log_text: str, cwd: Path, root: Path, allow_path: Path
) -> tuple[str, list[str]]:
    """(verdict, detail). `VERDICT_OK` ONLY when at least one failing id was
    parsed AND every one of them is allowlisted — never because nothing was
    found (SUI9: a check that cannot see its target must not read clean)."""
    if not allow_path.is_file():
        return VERDICT_NO_ALLOWLIST, [str(allow_path)]
    allowed = {to_root_frame(e, root, root) for e in allowlist_entries(allow_path)}
    failing = parse_failing(log_text)
    if not failing:
        return VERDICT_UNPARSEABLE, []
    normalised = [to_root_frame(f, cwd, root) for f in failing]
    unexpected = [n for n in normalised if n not in allowed]
    if unexpected:
        return VERDICT_NOT_ALLOWLISTED, unexpected
    return VERDICT_OK, normalised


def collect_check(root: Path, entries: list[str], timeout: int = 300) -> list[tuple[str, int]]:
    """`SUI4`: every allowlist entry must still collect. Returns (entry, rc)
    per entry; rc 0 means `pytest --collect-only <id>` found it. Each entry
    is run from ITS OWN package root, so an id in the UI tree is collected
    by the UI package exactly as the landing runner would reach it."""
    out: list[tuple[str, int]] = []
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("SELF_LEARN_ANALYST_MODEL", "SELF_LEARN_ANALYST_TIMEOUT")
    }
    for entry in entries:
        rel_file, rest = split_node_id(to_root_frame(entry, root, root))
        pkg = package_root_for(root, rel_file)
        local = str(Path(rel_file).relative_to(pkg.relative_to(root))) if pkg != root else rel_file
        proc = subprocess.run(
            ["uv", "run", "--no-sync", "pytest", "--collect-only", "-q",
             "-p", "no:cacheprovider", local + rest],
            cwd=pkg, capture_output=True, text=True, env=env, timeout=timeout,
        )
        out.append((entry, proc.returncode))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m self_learn.landing.suites")
    ap.add_argument("--root", required=True, type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_adj = sub.add_parser("adjudicate")
    p_adj.add_argument("--cwd", required=True, type=Path,
                       help="the directory the suite was RUN from — the same "
                            "value the runner passed to the suite invocation")
    p_adj.add_argument("--log", required=True, type=Path)
    p_adj.add_argument("--allow", required=True, type=Path)

    p_ver = sub.add_parser("verify-allowlist")
    p_ver.add_argument("--allow", required=True, type=Path)

    args = ap.parse_args(argv)
    root: Path = args.root.resolve()

    if args.cmd == "adjudicate":
        if not args.log.is_file():
            print(f"{VERDICT_UNPARSEABLE} (no log at {args.log})")
            return 1
        try:
            verdict, detail = adjudicate(
                args.log.read_text(errors="replace"), args.cwd.resolve(), root, args.allow
            )
        except FrameError as exc:
            print(f"{VERDICT_NOT_ALLOWLISTED} {exc}")
            return 1
        print(f"{verdict} {' '.join(detail)}".rstrip())
        return 0 if verdict == VERDICT_OK else 1

    entries = allowlist_entries(args.allow)
    if not entries:
        print("empty-allowlist 0 entries")
        return 0
    bad = [(e, rc) for e, rc in collect_check(root, entries) if rc != 0]
    for e, rc in bad:
        print(f"STALE: {e} does not collect (rc {rc})", file=sys.stderr)
    print(f"checked {len(entries)} entries, {len(bad)} stale")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
