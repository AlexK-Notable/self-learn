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

# B-6 (d)/(e): a missing dependency used to mean this hook exited 0 with
# NOTHING printed -- indistinguishable from "0 pending, nothing to say",
# the exact silent-collapse shape the home_state branch below was
# already fixed against (audit 2026-07-16 BLOCKER 11). Say it instead,
# every time a guard below fires.
_degraded() {
  echo "⚠️  self-learn: pending-count check skipped — $1"
  exit 0
}

command -v self-learn >/dev/null 2>&1 || _degraded "self-learn is not on PATH"
command -v jq >/dev/null 2>&1 || _degraded "jq is not on PATH"
command -v timeout >/dev/null 2>&1 || _degraded "timeout is not on PATH"

# `|| true` is LOAD-BEARING under `set -e` (audit 2026-07-16 BLOCKER 1).
# --fast exits 5 for a missing / not-a-repo home while still printing the
# valid JSON that carries home_state. Without `|| true`, `set -e` killed
# the script on that very assignment — so the home warning below was DEAD
# CODE in exactly the state it exists to report (doc 13 §7.1 B-1), and a
# SessionStart hook that must never fail the session exited 5 instead.
# The `[ -n "$out" ]` guard already covers a genuinely empty read.
out="$(timeout 4 self-learn status --fast 2>/dev/null)" || true
[ -n "$out" ] || exit 0

# A wrong/unset SELF_LEARN_HOME used to render a silent, confident "0
# pending" forever — the records invisible with no error anywhere (audit
# 2026-07-16 BLOCKER 11). Say it at every session start instead.
home_state="$(jq -r '.home_state // "ok"' <<<"$out" 2>/dev/null)" || exit 0
if [ "$home_state" != "ok" ]; then
  home_path="$(jq -r '.home // "?"' <<<"$out" 2>/dev/null)" || exit 0
  echo "⚠️  self-learn: ledger home ${home_path} is ${home_state} — no records are visible (this is NOT an empty ledger). Check \$SELF_LEARN_HOME or clone/bootstrap the ledger repo; \`self-learn status\` explains."
  exit 0
fi

# B-6 secondary shape (R): `jq -r '.total_pending // 0'` cannot tell "the
# key is absent" from "the key is a genuine 0" — a CLI whose JSON shape
# regresses would degrade to a silent, healthy-looking session (total
# absent -> 0 -> the pending line simply never prints, no error
# anywhere). `jq -e` WITHOUT a `// 0` fallback fails (exit 1) exactly
# when the extracted value is null/absent, so absence is now a
# DISTINCT, reported outcome instead of a collapsed zero.
if ! total="$(jq -e -r '.total_pending' <<<"$out" 2>/dev/null)"; then
  _degraded "self-learn status --fast returned no total_pending (unexpected CLI output)"
fi
oldest="$(jq -r '.oldest_days // 0' <<<"$out" 2>/dev/null)" || exit 0
stale="$(jq -r '.staleness_alarm // false' <<<"$out" 2>/dev/null)" || exit 0
escalate="$(jq -r '.escalate // false' <<<"$out" 2>/dev/null)" || exit 0
unanalyzed="$(jq -r '.unanalyzed_total // 0' <<<"$out" 2>/dev/null)" || exit 0

if [ "$total" -gt 0 ]; then
  # pinned example format (08 §7.1): "📥 self-learn: 7 pending, oldest 9d — /self-learn:review"
  line="📥 self-learn: ${total} pending, oldest ${oldest}d — /self-learn:review"
  # B-7 consumer half: `total_unreadable` is `status --fast`'s own
  # honest-null field (absent, never a confident zero, when the scan
  # cannot tell) — the producer side was already fixed; this hook never
  # read it. `jq -e` (no fallback) so an absent key is silently skipped
  # here rather than manufacturing a "0 unreadable" that isn't real.
  if unreadable="$(jq -e -r '.total_unreadable' <<<"$out" 2>/dev/null)" \
      && [ "$unreadable" -gt 0 ] 2>/dev/null; then
    line="${line} (${unreadable} unreadable)"
  fi
  echo "$line"
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
