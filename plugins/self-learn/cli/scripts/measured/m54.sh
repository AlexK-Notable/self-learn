#!/usr/bin/env bash
# m54.sh -- SAN5 leg (c)'s measurement: the r2 VERBATIM pattern file (one
# pattern spelled out per line, not fragmented) scores self-hits under its
# own gate. `secret`, `password`, `PRIVATE KEY` and `ghp_` match
# themselves literally; `bearer [A-Za-z0-9_-]{8,}` and `api[_-]?key` do
# NOT self-match (the literal bracket/quantifier text is not itself 8+
# word chars, nor literally "apikey") -- so the count is 4, not 7 or 6.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need "$HERE/pat.txt"

PAT=$(cat "$HERE/pat.txt")
if [ -z "$PAT" ]; then
  echo "FATAL: pat.txt is empty (empty pattern matches every line -- M-20's shape one row over)" >&2
  exit 3
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<'VERBATIM'
bearer [A-Za-z0-9_-]{8,}
api[_-]?key
secret
password
PRIVATE KEY
ghp_
%HOME%
VERBATIM

grep -cEi "$PAT" "$tmp"
