#!/usr/bin/env bash
# install.sh — self-learn product deploy (live symlinks; doc 13 §7.3).
#
# Deploys exactly five surfaces + the miner units:
#   - ~/.claude/skills/self-learn    -> plugins/self-learn/skills/self-learn
#   - ~/.claude/commands/self-learn  -> plugins/self-learn/commands
#   - ~/bin/self-learn               -> plugins/self-learn/scripts/self-learn
#   - ~/.claude/hooks/self-learn-pending.sh -> plugins/self-learn/hooks/…
#   - uv sync of the CLI project
#   - ~/.config/systemd/user/self-learn-miner.{service,timer} -> systemd/…
#
# What this deliberately does NOT touch (13 §7.3 D1 — the product repo is
# a tool; compiled output lands in the USER'S hosts):
#   - guard scripts (they are host canon, e.g. claude-skills hooks/self-learn/)
#   - settings.json (load-bearing; registrations stay manual)
#   - any autosync watcher (D3: this repo syncs by manual push only)
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

say "== SessionStart pending hook =="
link "$P/hooks/self-learn-pending.sh" "$HOOKS_DIR/self-learn-pending.sh"
say "  (register in ~/.claude/settings.json as a SessionStart hook — manual)"

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

say "done."
