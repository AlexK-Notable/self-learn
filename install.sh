#!/usr/bin/env bash
# install.sh — self-learn product deploy (live symlinks; doc 13 §7.3).
#
# Deploys the eight always-on surfaces below plus the G-3 UI unit and the
# U-engine Phase 2 host-process unit, always; the legacy miner units are
# OPT-IN (`--legacy-miner`) now that self-learn-host.service is the
# scheduler (M-U/D5):
#   - ~/.claude/skills/self-learn    -> plugins/self-learn/skills/self-learn
#   - ~/.claude/commands/self-learn  -> plugins/self-learn/commands
#   - ~/bin/self-learn               -> plugins/self-learn/scripts/self-learn
#   - ~/.claude/hooks/self-learn-pending.sh -> plugins/self-learn/hooks/…
#   - ~/.claude/hooks/self-learn-refread.sh -> plugins/self-learn/hooks/…
#     (U-readref — PostToolUse/Read reference-shelf observable)
#   - uv sync of the CLI project
#   - ~/bin/self-learn-ui            -> plugins/self-learn/scripts/self-learn-ui
#   - ~/bin/self-learn-ui-open       -> plugins/self-learn/scripts/self-learn-ui-open
#   - ~/bin/self-learn-notify        -> plugins/self-learn/scripts/self-learn-notify
#   - ~/.config/systemd/user/self-learn-ui.service -> systemd/self-learn-ui.service
#     (G-3 surface — 10 §1 "Service"/"Companion scripts" rows; explicit link
#     lines mirroring the miner-units block below, no glob — 13 §7.3)
#   - ~/.config/systemd/user/self-learn-host.service -> systemd/self-learn-host.service
#     (U-engine Phase 2 — the long-lived scheduler; NOT enabled by this
#     script, same as the other units — u-engine-shared-sdk-core-spec.md §5.7)
#   - with --legacy-miner:
#     ~/.config/systemd/user/self-learn-miner.{service,timer} -> systemd/…
#     (opt-in now that self-learn-host.service schedules the nightly mine;
#     without the flag, any PRE-EXISTING miner-unit symlinks are left
#     untouched and named, never silently dropped)
#
# All `~/.config/systemd/user/...` targets above are the DEFAULT -- every
# one honors `$XDG_CONFIG_HOME/systemd/user` instead when that variable is
# set (U-servehermetic, 2026-08-27; see `UNIT_DIR` below, resolved the same
# way `serve.unit_dir()` resolves it).
#
# Flags (M-U/D5):
#   --dry-run       print every step this run would take; touch NOTHING --
#                   every mutation (the first `mkdir -p` included) is
#                   routed through `run()`, and `run()` never executes a
#                   real command while `--dry-run` is in effect
#   --legacy-miner  also link the legacy self-learn-miner.{service,timer}
#                   units (see above)
#   --help, -h      print usage and exit 0
#   anything else   print usage (to stderr) and exit 64
#
# Safety (M-U/D5): every external command this script runs is BOUNDED
# (`timeout N …`) -- a hung `uv sync`, `systemctl`, or
# `update-desktop-database` can no longer hang the installer forever. If
# `timeout` itself is not on PATH, the script refuses to start rather than
# run anything unbounded. Symlink targets that already hold a real file or
# a real directory are backed up with a collision-checked, nanosecond-
# stamped name (never silently skipped, never nested into by `ln`), and a
# symlink failure AFTER a successful backup restores it before exiting.
# Every mutating command still goes through `run()`, which still `eval`s
# a string (so a caller can hand it a whole pipeline, same as before) --
# but every DYNAMIC component of that string is now escaped through
# `q()` (`printf %q`) before insertion, not hand-wrapped in single quotes.
# A path containing a shell-special character (an apostrophe in $HOME,
# say) can no longer corrupt the eval'd command into a different, wrong
# one -- `q()` round-trips it exactly.
#
# What this deliberately does NOT touch (13 §7.3 D1 — the product repo is
# a tool; compiled output lands in the USER'S hosts):
#   - guard scripts (they are host canon, e.g. claude-skills hooks/self-learn/)
#   - settings.json (load-bearing; registrations stay manual)
#   - any autosync watcher (D3: this repo syncs by manual push only)
#   - enabling/starting/stopping/restarting any systemd unit, or signaling
#     one directly (`is-enabled` below is a read-only query, never a
#     mutation) — enable is always a documented, printed manual line
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: install.sh [--dry-run] [--legacy-miner] [--help|-h]

Deploys the self-learn CLI, skill, commands, hooks, desktop launcher, and
systemd --user units as live symlinks into this user's home. Never
enables, starts, stops, or restarts any systemd unit -- that step is
always printed for the human to run by hand.

  --dry-run       print every step this run would take; touch nothing
  --legacy-miner  also link the legacy self-learn-miner.{service,timer}
                  units (opt-in now that self-learn-host.service is the
                  scheduler; omit unless you specifically want the R1
                  timer fallback running alongside it)
  --help, -h      show this message and exit
USAGE
}

DRY=0
LEGACY_MINER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --legacy-miner) LEGACY_MINER=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *)
      echo "install.sh: unknown option: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

if ! command -v timeout >/dev/null 2>&1; then
  echo "install.sh: 'timeout' (GNU coreutils) not found on PATH -- refusing to run unbounded external commands (uv sync, systemctl, update-desktop-database)" >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
COMMANDS_DIR="$HOME/.claude/commands"
HOOKS_DIR="$HOME/.claude/hooks"
BIN_DIR="$HOME/bin"
# Resolved the way systemd itself resolves the user unit search path
# (U-servehermetic, 2026-08-27, matching serve.unit_dir()'s order):
# $XDG_CONFIG_HOME/systemd/user if XDG_CONFIG_HOME is set, else the real
# ~/.config/systemd/user. self-learn's own explicit
# SELF_LEARN_SERVE_UNIT_DIR override is CLI-only (a test-hermeticity knob
# for serve.unit_dir()) and has no installer-side equivalent here.
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

say() { printf '%s\n' "$*"; }

# Shell-quote a single value for safe re-insertion into a string `run()`
# will later hand to `eval` (M-U/D5) -- `printf %q` escapes EVERY
# shell-special byte in the value (an apostrophe in $HOME, a space, a
# `$`, …), unlike the old idiom of hand-wrapping `'$var'` in single
# quotes, which breaks the instant the value itself contains a single
# quote (an apostrophe in $HOME corrupts the command into a different,
# wrong one -- or a syntax error -- rather than merely mis-displaying).
q() { printf '%q' "$1"; }

# Every MUTATING command is built as a STRING with every dynamic
# component passed through `q()` first, then run through here. Under
# --dry-run the string is only printed, never `eval`'d -- so a dry run
# touches nothing on disk. `run()`'s own exit status is the command's
# (or 0 for a print), so `if ! run "…"; then` can react to a real
# failure (`link()`'s rollback below relies on exactly this).
run() {
  if [ "$DRY" = 1 ]; then
    say "  [dry] $*"
  else
    eval "$*"
  fi
}

# idempotent symlink with collision-proof backup + rollback (M-U/D5;
# same idiom as claude-skills, hardened). $dst is backed up (never
# clobbered, never silently skipped, never nested-into by a directory-
# target `ln`) whenever it exists and is NOT already the right symlink.
link() { # $1=real src  $2=link path
  local src="$1" dst="$2"
  if [ -L "$dst" ] && [ "$(readlink -f "$dst" 2>/dev/null)" = "$(readlink -f "$src")" ]; then
    say "  ok    ${dst/#$HOME/\~}"; return
  fi
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    # A real file OR a real directory (never a symlink -- that leg falls
    # through to the plain `ln -sfn` below, which safely re-points it,
    # and never risks `ln` nesting a new link INSIDE an existing
    # directory: the directory is always moved out of the way first).
    local bak
    bak="$dst.bak.$(date +%s%N)"
    if [ -e "$bak" ] || [ -L "$bak" ]; then
      echo "install.sh: refusing to overwrite an existing backup path: $bak" >&2
      exit 1
    fi
    say "  bak   ${dst/#$HOME/\~} -> ${bak##*/}"
    run "mv -n $(q "$dst") $(q "$bak")"
    if [ "$DRY" != 1 ] && { [ -e "$dst" ] || [ -L "$dst" ]; }; then
      echo "install.sh: backup move did not take effect for $dst -- refusing to continue (mv -n silently declined, likely a race on $bak)" >&2
      exit 1
    fi
    if ! run "ln -sfn $(q "$src") $(q "$dst")"; then
      say "  ERROR ln failed for ${dst/#$HOME/\~} -- restoring backup"
      run "mv $(q "$bak") $(q "$dst")"
      echo "install.sh: symlink failed for $dst -- original restored from $bak" >&2
      exit 1
    fi
  else
    run "ln -sfn $(q "$src") $(q "$dst")"
  fi
  say "  link  ${dst/#$HOME/\~} -> ${src/#$HOME/\~}"
}

run "mkdir -p $(q "$SKILLS_DIR") $(q "$COMMANDS_DIR") $(q "$BIN_DIR") $(q "$HOOKS_DIR") $(q "$UNIT_DIR")"
P="$REPO/plugins/self-learn"

say "== skill (live symlink) =="
link "$P/skills/self-learn" "$SKILLS_DIR/self-learn"

say "== slash commands =="
link "$P/commands" "$COMMANDS_DIR/self-learn"

say "== CLI shim (~/bin) =="
link "$P/scripts/self-learn" "$BIN_DIR/self-learn"

say "== G-3 surface scripts (~/bin) =="
link "$P/scripts/self-learn-ui" "$BIN_DIR/self-learn-ui"
link "$P/scripts/self-learn-ui-open" "$BIN_DIR/self-learn-ui-open"
link "$P/scripts/self-learn-notify" "$BIN_DIR/self-learn-notify"

say "== desktop launcher (G-3; feedback round 1 item 6) =="
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
run "mkdir -p $(q "$APPS_DIR") $(q "$ICON_DIR")"
# The .desktop entry is GENERATED, not symlinked: Exec= needs an absolute
# path (the desktop spec expands neither ~ nor $HOME, and launchers do
# not inherit an interactive shell's PATH — ~/bin isn't findable there).
# M-U/D5: generated into a temp file IN THE SAME DIRECTORY first, then
# moved over the destination -- a reader never observes a half-written
# .desktop file, and a dry run touches neither the temp file nor the
# real one, since both steps are gated the same way `run()` gates them.
DESKTOP_TMP="$APPS_DIR/.self-learn-ui.desktop.tmp.$$"
# M-U fold r3: --dry-run must EXECUTE nothing, not merely leave the
# filesystem unchanged -- a bare EXIT trap fires even under --dry-run
# (DESKTOP_TMP was never created, so `rm -f` is a harmless no-op, but it
# is still a real, executed external command). Installing the trap only
# on the real path keeps real-run cleanup exactly as it was.
[ "$DRY" = 1 ] || trap 'rm -f "$DESKTOP_TMP"' EXIT
run "sed $(q "s|@BIN@|$BIN_DIR|") $(q "$P/assets/self-learn-ui.desktop.in") > $(q "$DESKTOP_TMP")"
run "mv $(q "$DESKTOP_TMP") $(q "$APPS_DIR/self-learn-ui.desktop")"
say "  gen   ~/.local/share/applications/self-learn-ui.desktop"
link "$P/assets/self-learn-ui.svg" "$ICON_DIR/self-learn-ui.svg"
if command -v update-desktop-database >/dev/null 2>&1; then
  run "timeout 10 update-desktop-database $(q "$APPS_DIR") >/dev/null 2>&1 || true"
fi

say "== SessionStart pending hook =="
link "$P/hooks/self-learn-pending.sh" "$HOOKS_DIR/self-learn-pending.sh"
say "  (register in ~/.claude/settings.json as a SessionStart hook — manual)"

say "== PostToolUse reference-read hook (U-readref) =="
link "$P/hooks/self-learn-refread.sh" "$HOOKS_DIR/self-learn-refread.sh"
say "  (register in ~/.claude/settings.json as a PostToolUse/Read hook — manual)"

say "== CLI (uv sync) =="
if command -v uv >/dev/null 2>&1; then
  run "timeout 60 uv sync --project $(q "$P/cli") -q"
else
  say "  NOTE: 'uv' not found — the shim needs uv at runtime"
fi

say "== miner units (systemd --user; legacy, opt-in) =="
MINER_SERVICE_LINK="$UNIT_DIR/self-learn-miner.service"
MINER_TIMER_LINK="$UNIT_DIR/self-learn-miner.timer"
if [ "$LEGACY_MINER" = 1 ]; then
  link "$REPO/systemd/self-learn-miner.service" "$MINER_SERVICE_LINK"
  link "$REPO/systemd/self-learn-miner.timer" "$MINER_TIMER_LINK"
  run "timeout 10 systemctl --user daemon-reload"
  say "  enable with: systemctl --user enable --now self-learn-miner.timer"
elif [ -L "$MINER_SERVICE_LINK" ] || [ -L "$MINER_TIMER_LINK" ]; then
  say "  left alone: an existing self-learn-miner.{service,timer} symlink is"
  say "  untouched — pass --legacy-miner to this script to (re)link them"
else
  say "  skipped (opt-in) — pass --legacy-miner to link self-learn-miner.{service,timer}"
fi

say "== G-3 surface unit (systemd --user) =="
link "$REPO/systemd/self-learn-ui.service" "$UNIT_DIR/self-learn-ui.service"
run "timeout 10 systemctl --user daemon-reload"
say "  ACTION NEEDED: enable with: systemctl --user enable --now self-learn-ui.service"
say "  (no-systemd fallback: run 'self-learn-ui serve' in the foreground — 10 §5)"

say "== host process unit (U-engine Phase 2; systemd --user) =="
link "$REPO/systemd/self-learn-host.service" "$UNIT_DIR/self-learn-host.service"
run "timeout 10 systemctl --user daemon-reload"
say "  enable with: systemctl --user enable --now self-learn-host.service"
say "  (no-systemd fallback: run 'self-learn serve' in the foreground — U-engine spec §5.7)"
say "  NOTE: once self-learn-host.service is enabled, self-learn-miner.timer should"
say "  not also stay enabled — 'self-learn doctor invocation' WARNs (never fails) if"
say "  both are; a timer left enabled on purpose is a supported belt-and-braces poke."
if command -v systemctl >/dev/null 2>&1; then
  # Bounded, read-only (never a mutation): UNCONDITIONAL after linking the
  # host unit (M-U/D5 fold r1, as pinned) -- a missing self-learn-miner.timer
  # unit is not an error (systemctl reports it non-"enabled", swallowed by
  # `|| true`); a missing `systemctl` itself is not an error either (this
  # whole block is skipped). Previewed under --dry-run rather than silently
  # both run for real AND omitted from the preview.
  if [ "$DRY" = 1 ]; then
    say "  [dry] timeout 5 systemctl --user is-enabled self-learn-miner.timer"
  else
    MINER_TIMER_STATE="$(timeout 5 systemctl --user is-enabled self-learn-miner.timer 2>/dev/null || true)"
    if [ "$MINER_TIMER_STATE" = "enabled" ]; then
      say "  self-learn-miner.timer is currently enabled — to disable:"
      say "  systemctl --user disable --now self-learn-miner.timer"
    fi
  fi
fi

say "done."
