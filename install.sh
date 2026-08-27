#!/usr/bin/env bash
# install.sh — self-learn product deploy (live symlinks; doc 13 §7.3).
#
# Deploys exactly nine surfaces + the miner units + the G-3 UI unit +
# the U-engine Phase 2 host-process unit:
#   - ~/.claude/skills/self-learn    -> plugins/self-learn/skills/self-learn
#   - ~/.claude/commands/self-learn  -> plugins/self-learn/commands
#   - ~/bin/self-learn               -> plugins/self-learn/scripts/self-learn
#   - ~/.claude/hooks/self-learn-pending.sh -> plugins/self-learn/hooks/…
#   - ~/.claude/hooks/self-learn-refread.sh -> plugins/self-learn/hooks/…
#     (U-readref — PostToolUse/Read reference-shelf observable)
#   - uv sync of the CLI project
#   - ~/.config/systemd/user/self-learn-miner.{service,timer} -> systemd/…
#   - ~/bin/self-learn-ui            -> plugins/self-learn/scripts/self-learn-ui
#   - ~/bin/self-learn-ui-open       -> plugins/self-learn/scripts/self-learn-ui-open
#   - ~/bin/self-learn-notify        -> plugins/self-learn/scripts/self-learn-notify
#   - ~/.config/systemd/user/self-learn-ui.service -> systemd/self-learn-ui.service
#     (G-3 surface — 10 §1 "Service"/"Companion scripts" rows; explicit link
#     lines mirroring the miner-units block below, no glob — 13 §7.3)
#   - ~/.config/systemd/user/self-learn-host.service -> systemd/self-learn-host.service
#     (U-engine Phase 2 — the long-lived scheduler; NOT enabled by this
#     script, same as the other two units — u-engine-shared-sdk-core-spec.md §5.7)
#
# What this deliberately does NOT touch (13 §7.3 D1 — the product repo is
# a tool; compiled output lands in the USER'S hosts):
#   - guard scripts (they are host canon, e.g. claude-skills hooks/self-learn/)
#   - settings.json (load-bearing; registrations stay manual)
#   - any autosync watcher (D3: this repo syncs by manual push only)
#   - enabling/starting any systemd unit (miner timer, the G-3 UI
#     service, or the U-engine host-process unit) — enable is always a
#     documented, printed manual line
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
COMMANDS_DIR="$HOME/.claude/commands"
HOOKS_DIR="$HOME/.claude/hooks"
BIN_DIR="$HOME/bin"
UNIT_DIR="$HOME/.config/systemd/user"

DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
say() { printf '%s\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then say "  [dry] $*"; else eval "$*"; fi; }

# idempotent symlink with conflict backup (same idiom as claude-skills)
link() { # $1=real src  $2=link path
  local src="$1" dst="$2"
  if [ -L "$dst" ] && [ "$(readlink -f "$dst" 2>/dev/null)" = "$(readlink -f "$src")" ]; then
    say "  ok    ${dst/#$HOME/\~}"; return; fi
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    bak="$dst.bak.$(date +%s)"
    say "  bak   ${dst/#$HOME/\~} -> ${bak##*/}"; run "mv -n '$dst' '$bak'"; fi
  run "ln -sfn '$src' '$dst'"; say "  link  ${dst/#$HOME/\~} -> ${src/#$HOME/\~}"
}

mkdir -p "$SKILLS_DIR" "$COMMANDS_DIR" "$BIN_DIR" "$HOOKS_DIR" "$UNIT_DIR"
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
run "mkdir -p '$APPS_DIR' '$ICON_DIR'"
# The .desktop entry is GENERATED, not symlinked: Exec= needs an absolute
# path (the desktop spec expands neither ~ nor $HOME, and launchers do
# not inherit an interactive shell's PATH — ~/bin isn't findable there).
run "sed 's|@BIN@|$BIN_DIR|' '$P/assets/self-learn-ui.desktop.in' > '$APPS_DIR/self-learn-ui.desktop'"
say "  gen   ~/.local/share/applications/self-learn-ui.desktop"
link "$P/assets/self-learn-ui.svg" "$ICON_DIR/self-learn-ui.svg"
if command -v update-desktop-database >/dev/null 2>&1; then
  run "update-desktop-database '$APPS_DIR' 2>/dev/null || true"
fi

say "== SessionStart pending hook =="
link "$P/hooks/self-learn-pending.sh" "$HOOKS_DIR/self-learn-pending.sh"
say "  (register in ~/.claude/settings.json as a SessionStart hook — manual)"

say "== PostToolUse reference-read hook (U-readref) =="
link "$P/hooks/self-learn-refread.sh" "$HOOKS_DIR/self-learn-refread.sh"
say "  (register in ~/.claude/settings.json as a PostToolUse/Read hook — manual)"

say "== CLI (uv sync) =="
if command -v uv >/dev/null; then
  run "uv sync --project '$P/cli' -q"
else
  say "  NOTE: 'uv' not found — the shim needs uv at runtime"
fi

say "== miner units (systemd --user) =="
link "$REPO/systemd/self-learn-miner.service" "$UNIT_DIR/self-learn-miner.service"
link "$REPO/systemd/self-learn-miner.timer" "$UNIT_DIR/self-learn-miner.timer"
run "systemctl --user daemon-reload"
say "  enable with: systemctl --user enable --now self-learn-miner.timer"

say "== G-3 surface unit (systemd --user) =="
link "$REPO/systemd/self-learn-ui.service" "$UNIT_DIR/self-learn-ui.service"
run "systemctl --user daemon-reload"
say "  ACTION NEEDED: enable with: systemctl --user enable --now self-learn-ui.service"
say "  (no-systemd fallback: run 'self-learn-ui serve' in the foreground — 10 §5)"

say "== host process unit (U-engine Phase 2; systemd --user) =="
link "$REPO/systemd/self-learn-host.service" "$UNIT_DIR/self-learn-host.service"
run "systemctl --user daemon-reload"
say "  enable with: systemctl --user enable --now self-learn-host.service"
say "  (no-systemd fallback: run 'self-learn serve' in the foreground — U-engine spec §5.7)"
say "  NOTE: once self-learn-host.service is enabled, self-learn-miner.timer should"
say "  not also stay enabled — 'self-learn doctor invocation' WARNs (never fails) if"
say "  both are; a timer left enabled on purpose is a supported belt-and-braces poke."

say "done."
