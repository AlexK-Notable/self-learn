#!/usr/bin/env bash
# m71.sh -- SUI6 leg (h)'s measurement (gate M-12): a `src` module renamed
# INTO docs/ is invisible to a rename-tracking diff (`NONDOC=0`, docs
# lane, while a src module was actually deleted); `--no-renames` reports
# both the old and new paths (`NONDOC=1`, full lane -- correct).
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git init -q -b master "$tmp" 2>/dev/null || { git init -q "$tmp"; git -C "$tmp" symbolic-ref HEAD refs/heads/master; }
git -C "$tmp" config user.email t@example.invalid
git -C "$tmp" config user.name Test
mkdir -p "$tmp/src"
printf 'def f():\n    return 1\n' > "$tmp/src/verbs.py"
git -C "$tmp" add src/verbs.py
git -C "$tmp" commit -q -m base
git -C "$tmp" checkout -q -b feature
mkdir -p "$tmp/docs"
git -C "$tmp" mv src/verbs.py docs/verbs.py
git -C "$tmp" commit -q -m rename

default_nondoc=$(git -C "$tmp" diff --name-only master..feature | grep -cv '^docs/' || true)
norenames_nondoc=$(git -C "$tmp" diff --no-renames --name-only master..feature | grep -cv '^docs/' || true)

printf 'default=%s no-renames=%s\n' "$default_nondoc" "$norenames_nondoc"
