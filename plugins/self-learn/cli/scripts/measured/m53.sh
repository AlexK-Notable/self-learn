#!/usr/bin/env bash
# m53.sh -- §4.10's B-1 measurement, form (2): under `set -euo pipefail`,
# a redirected-then-adjudicated command's rc-capture line is never
# reached, so the .rc file is never written. Prints "absent" when that
# happens (the ships-with form, (3), always writes it -- see EXC1/SUI5).
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# NOTE: deliberately NOT `(...) || true` -- bash suppresses -e for a
# subshell's ENTIRE body when that subshell is the LHS of `||`, even with
# an explicit `set -e` inside it (measured: `(set -e; false; echo X) ||
# true` prints X). This script's own top level has no `-e` (_lib.sh sets
# only `-uo pipefail`), so the subshell's nonzero exit is simply not
# fatal here without needing `|| true` at all.
(
  set -euo pipefail
  timeout 1 false > "$tmp/log" 2>&1
  echo $? > "$tmp/out.rc"
)

if [ -f "$tmp/out.rc" ]; then
  cat "$tmp/out.rc"
else
  echo "absent"
fi
