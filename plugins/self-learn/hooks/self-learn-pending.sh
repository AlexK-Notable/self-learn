#!/usr/bin/env bash
# self-learn-pending.sh — SessionStart hook (08 §7.1 pin).
#
# Since the attention round (design r2 §3.9) this hook prints only what an
# agent in this session must know or act on, and nothing that waits on the
# user — their items are in the tray's inbox:
#   - a degraded check (a missing dependency, a timed-out status call);
#   - home and lock problems (a missing or broken ledger home, a lock probe
#     that failed);
#   - a STOPPED transaction intent, with the command that clears it;
#   - unreadable records;
#   - this project's notices (S-106), under one header that says they are
#     this session's to carry out.
# Dropped: the overseer-questions line, the pending, backlog, worker and
# miner lines, and the steward's stale and held lines. It prints nothing
# about approved inbox work: that runs only in the session the approve click
# opens (design r2 §3.4.7).
#
# ALL queue semantics come from `self-learn status --json --fast` — a
# guaranteed-cheap CLI path (pending/-only frontmatter scan, no git, <500 ms
# warm budget). This script only formats; it never reimplements queue rules
# and NEVER calls notify-send (S-9: session starts are many; the one popup
# left, a login hold, is sent by the job that is held).
#
# Deploy: install.sh symlinks this into ~/.claude/hooks/; it runs once this
# entry is in ~/.claude/settings.json (whoever installs adds it, an agent
# included -- no person-only step; `self-learn --selftest`'s hooks row reports
# a registration whose symlink dangles):
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

# `&& rc=0 || rc=$?` is LOAD-BEARING under `set -e` (audit 2026-07-16
# BLOCKER 1; extended fold r1 MAJOR 1). --fast exits 5 for a missing /
# not-a-repo home while still printing the valid JSON that carries
# home_state, so a GENERIC non-zero check would misfire on that
# legitimate shape — the rc is captured and only rc 124 (this `timeout`
# actually firing) gets its own degraded line; every other rc (0, 5,
# ...) falls through exactly as before. Without capturing rc via a
# plain assignment-then-test, `set -e` would kill the script on the
# substitution itself — so the home warning below was DEAD CODE in
# exactly the state it exists to report (doc 13 §7.1 B-1).
out="$(timeout 4 self-learn status --fast 2>/dev/null)" && rc=0 || rc=$?
if [ "$rc" -eq 124 ]; then
  # Fold r1 MAJOR 1: a wedged/hung `self-learn status --fast` used to
  # degrade SILENTLY here (the same "nothing printed, rc 0" collapse
  # this whole move exists to abolish) — say it, same as every other
  # dependency guard above.
  _degraded "self-learn status timed out after 4s"
fi
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

# S-62 (§7.2a.7): the `2>/dev/null` on the `status --fast` call above used
# to be the ONLY route a live STOP had to reach this hook — discarding the
# stderr line `_warn_intents_in_flight_report`'s own docstring calls "the
# human's one notice" (cli.py). `intents_stopped_count` rides the SAME
# stdout JSON every other field here reads, so it survives that discard;
# `jq -e` (no `// 0` fallback) so a CLI whose JSON shape regresses reports
# absence rather than a silent, healthy-looking "0 stopped" (the B-6
# secondary-shape discipline).
# §7.2a.7 ("never as free"): a probe error means STOPPED intents are
# genuinely unknown, not zero -- `intents_stopped_count` reads 0/absent
# in that case (§7.2a.7's own classification never inspects individual
# intents when the probe itself failed), so without this the STOPPED
# warning above would silently look identical to a healthy ledger.
if intents_probe="$(jq -e -r '.intents_probe' <<<"$out" 2>/dev/null)" && [ "$intents_probe" = "error" ]; then
  echo "⚠️ self-learn: could not probe the ledger lock — a STOPPED intent may be hidden; run \`self-learn status\`"
fi

if intents_stopped_count="$(jq -e -r '.intents_stopped_count' <<<"$out" 2>/dev/null)"; then
  if [ "$intents_stopped_count" -gt 0 ] 2>/dev/null; then
    intents_stopped_ids="$(jq -r '(.intents_stopped // []) | join(", ")' <<<"$out" 2>/dev/null)" || intents_stopped_ids="?"
    # Gate r1 MINOR-2: the real, first id -- `intents_stopped` is the
    # same array `intents_stopped_ids` above already joins.
    first_stopped_id="$(jq -r '(.intents_stopped // [])[0] // "?"' <<<"$out" 2>/dev/null)" || first_stopped_id="?"
    plural=""
    if [ "$intents_stopped_count" -ne 1 ]; then plural="s"; fi
    echo "🛑 self-learn: ${intents_stopped_count} STOPPED transaction intent${plural} (${intents_stopped_ids}) — every ledger write refuses until cleared. Run \`self-learn reconcile --clear-intent ${first_stopped_id}\` after inspecting the offender."
  fi
fi

# B-7 consumer half: `status --fast` reports `total_unreadable` from the
# same full record parse as `status --json` (perf batch 1, 2026-11-01).
# `jq -e` (no fallback) still reads an absent key, from an older CLI, as ""
# rather than manufacturing a "0 unreadable" that isn't real. An unreadable record is a
# ledger problem nobody's queue covers, so it prints whoever owns the queue.
unreadable="$(jq -e -r '.total_unreadable' <<<"$out" 2>/dev/null)" || unreadable=""
if [ -n "$unreadable" ] && [ "$unreadable" -gt 0 ] 2>/dev/null; then
  echo "⚠️  self-learn: ${unreadable} unreadable record(s) in the queue — \`self-learn status\` names them"
fi

# S-106: project notices. `self-learn status --fast` carries
# `project_notices` ONLY when this session's directory is inside a project a
# live notice names (an overseer finding about that project, or a tracked file
# of a plain host that self-learn left changed); each entry's `line` is the
# whole line, formatted by the CLI, so the wording lives in one place. At most
# three arrive; `project_notices_more` counts the rest. An absent or malformed
# field prints nothing -- the normal case in every other project.
# M9 (attention round): one header first, saying whose these are -- this
# session's agent carries each out and closes it; none waits on the user.
notice_lines="$(jq -r '(.project_notices // [])[] | .line // empty' <<<"$out" 2>/dev/null)" || notice_lines=""
if [ -n "$notice_lines" ]; then
  echo "self-learn notices for this project — yours to carry out in this session (no sudo needed): do it, then \`self-learn notice done <id>\`"
  printf '%s\n' "$notice_lines"
  notices_more="$(jq -r '.project_notices_more // 0' <<<"$out" 2>/dev/null)" || notices_more=0
  if [ "$notices_more" -gt 0 ] 2>/dev/null; then
    echo "self-learn: ${notices_more} more notice(s) for this project — self-learn notice list"
  fi
fi

exit 0
