#!/usr/bin/env bash
# self-learn-pending.sh — SessionStart hook (08 §7.1 pin).
#
# Prints the pending line, the staleness alarm, and the escalation line
# into session context. ALL queue semantics come from
# `self-learn status --json --fast` — a guaranteed-cheap CLI path
# (pending/-only frontmatter scan, no git, <500 ms warm budget). This
# script only formats; it never reimplements queue rules and NEVER calls
# notify-send (S-9: session starts are many, popups are the treadmill —
# desktop escalation belongs to worker-run end alone).
#
# Deploy: install.sh symlinks this into ~/.claude/hooks/; registration in
# ~/.claude/settings.json is a documented MANUAL step (repo doctrine):
#
#   {"hooks": {"SessionStart": [{"matcher": "",
#     "hooks": [{"type": "command",
#       "command": "$HOME/.claude/hooks/self-learn-pending.sh"}]}]}}
set -euo pipefail

command -v self-learn >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

out="$(self-learn status --fast 2>/dev/null)" || exit 0
[ -n "$out" ] || exit 0

total="$(jq -r '.total_pending // 0' <<<"$out" 2>/dev/null)" || exit 0
oldest="$(jq -r '.oldest_days // 0' <<<"$out" 2>/dev/null)" || exit 0
stale="$(jq -r '.staleness_alarm // false' <<<"$out" 2>/dev/null)" || exit 0
escalate="$(jq -r '.escalate // false' <<<"$out" 2>/dev/null)" || exit 0
unanalyzed="$(jq -r '.unanalyzed_total // 0' <<<"$out" 2>/dev/null)" || exit 0

if [ "$total" -gt 0 ]; then
  # pinned example format (08 §7.1): "📥 self-learn: 7 pending, oldest 9d — /self-learn:review"
  echo "📥 self-learn: ${total} pending, oldest ${oldest}d — /self-learn:review"
fi

if [ "$stale" = "true" ]; then
  echo "⚠️  self-learn: ${unanalyzed} record(s) await analysis and the worker hasn't run in >3 days (or ever) — check \`self-learn worker run\` / worker.log"
fi

if [ "$escalate" = "true" ]; then
  echo "🔺 self-learn: backlog over threshold (≥5 pending or oldest >7d) — a review session is due"
fi

# Doc 12 R1 layer 3: the miner has not completed a run in >36h (timer,
# watchdog, and manual force all touch the same marker) — a silent death
# becomes humanly visible within a day.
miner_stale="$(jq -r '.miner_stale // false' <<<"$out" 2>/dev/null)" || exit 0
if [ "$miner_stale" = "true" ]; then
  echo "⚠️  self-learn: transcript miner hasn't completed a run in >36h — check \`self-learn mine status\` / miner.log"
fi

exit 0
