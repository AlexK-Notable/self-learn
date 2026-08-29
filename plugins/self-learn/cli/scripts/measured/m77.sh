#!/usr/bin/env bash
# m77.sh -- UN4 leg (b)'s self-check: floor.py's DERIVED floor (gate M-22),
# found via spec_path() (N-25), never a hardcoded path.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
SPEC=$(spec_path) || exit 3
if [ -z "$SPEC" ]; then
  echo "FATAL: spec_path() returned empty" >&2
  exit 3
fi
python3 "$HERE/floor.py" "$SPEC" | head -1
