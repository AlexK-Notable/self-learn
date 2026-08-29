"""sanitize.py — the sanitize gate: added-lines-only scan, fragment-assembled
pattern set, and exact-coverage `--sanitize-ack`.

Parses `git diff --unified=0 --no-renames <range>` into `(file, line, text)`
triples for every ADDED line, headers excluded by construction (anchored on
`diff --git`, never inferred from `---`/`+++` — gate M-21). The pattern set
is assembled from `sanitize_fragments.txt` FRAGMENTS, never stored verbatim
(gate M-3/SAN5, ruling F-2) — the home prefix is a `%HOME%` placeholder
substituted from `$HOME` at read time (SAN1).

See docs/specs/self-learn/drafts/u-land-landing-runner-spec.md §4.7/§4.7a.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

HEADER_START_RE = re.compile(r"^diff --git ")
HUNK_RE = re.compile(r"^@@ -\S+ \+(\d+)(?:,\d+)? @@")

Hit = tuple[str, int, str]


def added_lines(root: Path, rng: str) -> list[tuple[str, int, str]]:
    """Every ADDED line of `rng`, as (file, new-file-line-number, text).

    `+++`/`---`/`@@` are excluded by construction: header lines are
    recognised only between a `diff --git` line and that file's first
    `@@` hunk header, so a content line can never spoof a header (gate
    M-18/M-21 — a two-line `---`-then-`+++` heuristic can be spoofed by a
    deleted line whose content begins `-- `; anchoring on `diff --git`
    cannot, because content lines are always `+`/`-`/space-prefixed).
    """
    proc = subprocess.run(
        ["git", "diff", "--unified=0", "--no-renames", rng],
        cwd=root, capture_output=True, text=True, check=True,
    )
    out: list[tuple[str, int, str]] = []
    path: str | None = None
    ln = 0
    in_header = False
    for l in proc.stdout.split("\n"):
        if HEADER_START_RE.match(l):
            in_header = True
            path = None
            continue
        if in_header:
            if l.startswith("+++ "):
                path = l[6:] if l.startswith("+++ b/") else l[4:]
                continue
            if l.startswith("@@"):
                in_header = False  # fall through to hunk handling below
            else:
                continue
        m = HUNK_RE.match(l)
        if m:
            ln = int(m.group(1))
            continue
        if l.startswith("\\"):  # "\ No newline at end of file"
            continue
        if l.startswith("+"):
            out.append((path, ln, l[1:]))
            ln += 1
    return out


# ---------------------------------------------------------------------------
# the fragment-assembled pattern set (SAN5)

def _parse_fragment_field(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def load_fragments(path: Path) -> list[str]:
    """One alternative per non-blank, non-comment line; `|`-joined fields."""
    alts: list[str] = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = [_parse_fragment_field(f) for f in line.split("|")]
        alts.append("".join(fields))
    return alts


def assemble_pattern(fragments_path: Path, home: str) -> re.Pattern:
    alts = load_fragments(fragments_path)
    parts = [re.escape(home) if a == "%HOME%" else a for a in alts]
    return re.compile("|".join(parts), re.I)


def default_fragments_path(root: Path) -> Path:
    """Root-relative, per §4.1's root-resolution rule (so --dry-run reads
    $TMP's copy of the pattern file, not the main checkout's)."""
    return root / "plugins/self-learn/cli/src/self_learn/landing/sanitize_fragments.txt"


# ---------------------------------------------------------------------------
# hits + ack coverage (SAN2/SAN3/SAN4)

def hits(root: Path, rng: str, fragments_path: Path | None = None) -> list[Hit]:
    pattern = assemble_pattern(fragments_path or default_fragments_path(root), os.environ.get("HOME", ""))
    return [(f, n, t) for f, n, t in added_lines(root, rng) if pattern.search(t)]


def line_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def hit_key(hit: Hit) -> tuple[str, int, str]:
    f, n, t = hit
    return (f, n, line_sha(t))


ACK_RE = re.compile(r"^(?P<file>.+):(?P<line>\d+):(?P<sha>[0-9a-f]{64})=(?P<reason>.*)$", re.S)


class AckParseError(ValueError):
    pass


def parse_ack(raw: str) -> tuple[str, int, str, str]:
    """Split at the FIRST '=' after the 64-hex sha (a sha256 contains no
    '=', so the reason may contain as many as it likes — gate M-9)."""
    m = ACK_RE.match(raw)
    if not m:
        raise AckParseError(f"malformed --sanitize-ack (want 'file:line:sha256=reason'): {raw!r}")
    return m.group("file"), int(m.group("line")), m.group("sha"), m.group("reason")


class CoverageResult:
    def __init__(self, unacked: list[Hit], stale: list[tuple[str, int, str, str]], empty_reason: list[tuple[str, int, str, str]]):
        self.unacked = unacked
        self.stale = stale
        self.empty_reason = empty_reason

    @property
    def ok(self) -> bool:
        return not (self.unacked or self.stale or self.empty_reason)


def check_coverage(hits_list: list[Hit], acks: list[str]) -> CoverageResult:
    """Exact coverage: A == H, keyed (file, line, sha256-of-line-text)."""
    parsed = [parse_ack(a) for a in acks]
    empty = [p for p in parsed if not p[3].strip()]
    H = {hit_key(h): h for h in hits_list}
    A = {(f, n, s) for f, n, s, r in parsed}
    unacked = [h for k, h in H.items() if k not in A]
    stale = [p for p in parsed if (p[0], p[1], p[2]) not in H]
    return CoverageResult(unacked=unacked, stale=stale, empty_reason=empty)


def ack_suggestion(hit: Hit) -> str:
    f, n, t = hit
    return f"--sanitize-ack '{f}:{n}:{line_sha(t)}='"


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m self_learn.landing.sanitize")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--range", required=True)
    ap.add_argument("--fragments", type=Path, default=None)
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--print-hits", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sanitize-ack", action="append", default=[], dest="acks")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    hs = hits(root, args.range, args.fragments)

    if args.count:
        print(len(hs))
        return 0
    if args.print_hits:
        for f, n, t in hs:
            print(f"{f}:{n}:{line_sha(t)}\t{t}")
        return 0
    if args.check:
        result = check_coverage(hs, args.acks)
        if result.ok:
            print("sanitize OK")
            return 0
        for h in result.unacked:
            print(f"UNACKED: {ack_suggestion(h)}  # {h[2]}", file=sys.stderr)
        for f, n, s, r in result.stale:
            print(f"STALE ACK: {f}:{n}:{s}", file=sys.stderr)
        for f, n, s, r in result.empty_reason:
            print(f"EMPTY REASON: {f}:{n}:{s}", file=sys.stderr)
        return 1
    print(len(hs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
