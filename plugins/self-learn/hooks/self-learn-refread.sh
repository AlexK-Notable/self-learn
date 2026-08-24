#!/usr/bin/env bash
# self-learn-refread.sh — PostToolUse/Read hook (U-readref §4.2).
#
# Observes "a references/*.md file was actually opened" — nothing else.
# The shelf that absorbs what the expensive shelves reject is the one
# shelf whose effectiveness was, before this hook, entirely unobserved
# (U-readref §1).
#
# NORMATIVE, every path including every error path:
#   1. NEVER fails the Read this hook rides on — always `exit 0`.
#   2. NEVER reads `tool_response` — the file body is never bound to a
#      variable, echoed, or logged. Only `.tool_input.file_path`,
#      `.session_id`, and whether the payload carries an `agent_id` key
#      are ever extracted.
#   3. Guards ALL THREE binaries it depends on, `timeout` included.
#   4. Prefilters in-shell (a `case` glob) before spawning the CLI.
#   5. Runs the CLI in the FOREGROUND, bounded from the inside by its own
#      `timeout 4` — strictly inside the harness's own 5s bound, so this
#      script's `exit 0` stays reachable even if the CLI hangs
#      (lrn-1dd6163b: an external timeout(1) wrapper is the only
#      reliable bound). A timed-out CLI is an ordinary exit-0 path here,
#      never an error path.
#   6. Passes through, as flags: --path (absolute), --session
#      (.session_id), and --subagent iff the payload has an agent_id key
#      at all — keying on PRESENCE, not on any id differing (§2.7: those
#      ids are identical between a parent and its subagent).
#   7. NEVER writes to stdout — PostToolUse stdout is surfaced back into
#      the session, on the critical path of every reference read.
#
# Deploy: install.sh symlinks this into ~/.claude/hooks/; registration in
# ~/.claude/settings.json is a documented MANUAL step (repo doctrine —
# U-readref §4.4 RULED this, not migrated to a plugin-provided hook):
#
#   {"hooks": {"PostToolUse": [{"matcher": "Read",
#     "hooks": [{"type": "command",
#       "command": "$HOME/.claude/hooks/self-learn-refread.sh",
#       "timeout": 5}]}]}}
set -uo pipefail

# §4.2-3: all THREE binaries, `timeout` included — under an accidental
# `set -e` a missing `timeout` would be a non-zero exit, exactly what
# requirement 1 forbids, on the critical path of every Read.
command -v self-learn >/dev/null 2>&1 || exit 0
command -v jq         >/dev/null 2>&1 || exit 0
command -v timeout    >/dev/null 2>&1 || exit 0

# Stdin is a pipe and cannot be re-read, so it is captured exactly once.
# This binds the RAW payload to a variable, never the extracted FILE
# BODY (§4.2-2's actual guarantee) — no filter below ever selects
# `.tool_response` or anything under it.
payload="$(cat)" || exit 0

# Prefilter field, extracted alone (§4.2-4/§9.2's cheap common path): a
# false positive is harmless (the CLI resolves authoritatively and emits
# nothing); a false negative is not, so the glob below must stay at
# least as wide as every reachable references dir.
file_path="$(jq -r '.tool_input.file_path // empty' <<<"$payload" 2>/dev/null)" || exit 0

case "$file_path" in
  */references/*.md) ;;
  *) exit 0 ;;
esac

# Rare path only (a references/*.md match): the two extra fields §4.2-6
# passes through. Keying on `agent_id` PRESENCE is required — session_id,
# transcript_path, cwd and prompt_id are identical between a parent and
# its subagent (§2.7), so nothing else can distinguish them.
session="$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)" || exit 0
has_agent="$(jq -r 'if has("agent_id") then "1" else "0" end' <<<"$payload" 2>/dev/null)" || exit 0

args=(--path "$file_path" --session "$session")
[ "$has_agent" = "1" ] && args+=(--subagent)

# §4.2-5: foreground (the event must be durable before this hook exits),
# bounded from the inside — strictly inside the harness's own 5s bound
# (§4.4). Both stdout and stderr go to nowhere: §4.2-7 binds EVERY path,
# not merely a "clean" one, and this is the simplest way to guarantee it
# — the CLI itself never writes to stdout either way (§4.2-7), so
# nothing diagnostic is lost by discarding stderr too.
timeout 4 self-learn telemetry read-observed "${args[@]}" >/dev/null 2>&1

exit 0
