#!/usr/bin/env bash
# _lib.sh — sourced by every scripts/measured/ helper (gate M-20, N-22).
# set -uo pipefail (NOT -e — §4.10's B-1 rule: -e and explicit rc capture
# are mutually exclusive). HERE resolves via $BASH_SOURCE, never $OLDPWD
# or a hardcoded misc/ path (gate M-20 — r5's m73.sh read $OLDPWD/misc/...,
# git-excluded, and reproduced only on the author's machine).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# depth-independent (gate r7's own clean-clone finding: climbing a fixed
# number of directory levels from scripts/measured/ landed on the wrong
# directory once already) — ask git, then assert the shape.
ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
if [ ! -d "$ROOT/docs/specs/self-learn" ]; then
  echo "FATAL: $ROOT is not the self-learn repo root" >&2
  exit 3
fi

need() {
  if [ ! -e "$1" ]; then
    echo "FATAL: missing required file: $1" >&2
    exit 3
  fi
}

# spec_path(): the ONE u-land-*.md, asserted (N-25). exit 3 here only ends
# a $(...) subshell -- callers MUST test the substitution themselves
# (N-27): SPEC=$(spec_path) || exit 3, plus an empty-value guard.
spec_path() {
  local matches n
  matches=$(find "$ROOT/docs/specs/self-learn" -name 'u-land-*.md' 2>/dev/null)
  n=$(printf '%s\n' "$matches" | grep -c . || true)
  if [ "$n" != "1" ]; then
    echo "FATAL: expected exactly 1 u-land-*.md, found $n" >&2
    exit 3
  fi
  printf '%s\n' "$matches"
}
