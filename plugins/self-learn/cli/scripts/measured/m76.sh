#!/usr/bin/env bash
# m76.sh -- SAN3's deleted-`-- ` variant (gate M-21): a DELETED line whose
# content begins `-- ` renders as `--- old marker line`, which satisfies a
# two-line "`+++` is a header only after `---`" rule (r5's form) even
# though no real file header is there. The next ADDED line
# (`++ b/evil-path`) is then mis-consumed as a header, `f.md` is lost from
# the parse, and the real hit is attributed to a fabricated path. The
# `diff --git`-anchored parser (r6, this package's shipped form) is
# immune: header lines are recognised only before a file's first `@@`.
#
# NOTE ON THE PRINTED NUMBERS: this script builds its own fixture and its
# own frozen transliteration of the r5 two-line rule (parse_r5, below) to
# demonstrate the MECHANISM live rather than assert it as prose. The exact
# line numbers depend on fixture details the original incident's fixture
# did not publish byte-for-byte; this script's `expect:` is pinned to
# what THIS fixture deterministically produces, and the build report
# states this explicitly (UN4's "say so with both numbers" rule) rather
# than silently forcing a match to the spec's own narrated example.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
SRC="$ROOT/plugins/self-learn/cli/src"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git init -q -b master "$tmp" 2>/dev/null || { git init -q "$tmp"; git -C "$tmp" symbolic-ref HEAD refs/heads/master; }
git -C "$tmp" config user.email t@example.invalid
git -C "$tmp" config user.name Test

# Two SEPARATE hunks in f.md (an unchanged middle line splits them under
# --unified=0), matching the spec's own illustration: line 1 changes to
# the fake-header-shaped line, line 2 is untouched, line 3 changes to the
# seeded secret -- so hunk 2's own `@@` header resets the line counter
# identically for both parsers; only the PATH differs (evil-path vs f.md).
printf -- '-- old marker line\nunchanged context\nold line three\n' > "$tmp/f.md"
printf 'context\n' > "$tmp/collide.md"
git -C "$tmp" add f.md collide.md
git -C "$tmp" commit -q -m base

git -C "$tmp" checkout -q -b feature
printf 'context\n++ b/evil-two\nSEEDED password123\n' > "$tmp/collide.md"
printf -- '++ b/evil-path\nunchanged context\nSEEDED ghp_deadbeefcafe\n' > "$tmp/f.md"
git -C "$tmp" add f.md collide.md
git -C "$tmp" commit -q -m change

PYTHONPATH="$SRC" python3 - "$tmp" "$ROOT" <<'PYEOF'
import re
import subprocess
import sys
from pathlib import Path

tmp, root = sys.argv[1], sys.argv[2]
sys.path.insert(0, f"{root}/plugins/self-learn/cli/src")
from self_learn.landing import sanitize as san

def r5_added_lines(root, rng):
    """Frozen transliteration of the r5 two-line '+++ after ---' rule."""
    out, path, ln = [], None, 0
    prev_minus = False
    proc = subprocess.run(["git", "diff", "--unified=0", "--no-renames", rng], cwd=root, capture_output=True, text=True, check=True)
    for l in proc.stdout.split("\n"):
        is_header = False
        if prev_minus and l.startswith("+++ "):
            path = l[6:] if l.startswith("+++ b/") else l[4:]
            is_header = True
        prev_minus = l.startswith("--- ")
        if is_header:
            continue
        m = re.match(r"^@@ -\S+ \+(\d+)(?:,\d+)? @@", l)
        if m:
            ln = int(m.group(1)); continue
        if l.startswith("\\"):
            continue
        if l.startswith("+"):
            out.append((path, ln, l[1:])); ln += 1
    return out

pattern = san.assemble_pattern(Path(root) / "plugins/self-learn/cli/src/self_learn/landing/sanitize_fragments.txt", "")

r5_hits = [(f, n, t) for f, n, t in r5_added_lines(tmp, "master..feature") if pattern.search(t)]
r6_hits = san.hits(Path(tmp), "master..feature", Path(root) / "plugins/self-learn/cli/src/self_learn/landing/sanitize_fragments.txt")

def fmt(hits):
    # the ghp_ hit specifically (the one M-18/M-21 are about)
    for f, n, t in hits:
        if "ghp_" in t:
            return f"{f}:{n}"
    return "MISSING"

print(f"r5={fmt(r5_hits)} r6={fmt(r6_hits)}")
PYEOF
