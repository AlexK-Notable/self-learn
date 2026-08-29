#!/usr/bin/env bash
# m73.sh -- SAN3's measurement (gate M-14): a file *named* secret_fixture.md
# (contents "clean") is 1 hit under the flat `grep '^+'` stream -- the
# `+++ b/.../secret_fixture.md` HEADER line matches the pattern on the
# PATH -- and 0 hits under the `--unified=0` header-anchored parser.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
SRC="$ROOT/plugins/self-learn/cli/src"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git init -q -b master "$tmp" 2>/dev/null || { git init -q "$tmp"; git -C "$tmp" symbolic-ref HEAD refs/heads/master; }
git -C "$tmp" config user.email t@example.invalid
git -C "$tmp" config user.name Test
echo base > "$tmp/README.md"
git -C "$tmp" add README.md
git -C "$tmp" commit -q -m base
git -C "$tmp" checkout -q -b feature
mkdir -p "$tmp/docs/x"
echo clean > "$tmp/docs/x/secret_fixture.md"
git -C "$tmp" add docs/x/secret_fixture.md
git -C "$tmp" commit -q -m "add fixture"

flat=$(git -C "$tmp" diff --unified=0 master..feature | grep '^+' | grep -cEi 'secret' || true)

parsed=$(PYTHONPATH="$SRC" python3 -c "
from pathlib import Path
from self_learn.landing import sanitize
hs = sanitize.hits(Path('$tmp'), 'master..feature', Path('$ROOT/plugins/self-learn/cli/src/self_learn/landing/sanitize_fragments.txt'))
print(len(hs))
")

printf 'flat=%s parsed=%s\n' "$flat" "$parsed"
