#!/usr/bin/env bash
# install-commands-test.sh — T1 test for install.sh's slash-commands surface.
#
# Runs the FULL install.sh against a throwaway fake $HOME and asserts that
# ~/.claude/commands/self-learn is a live symlink to the plugin's commands/
# directory, that a re-run is an idempotent no-op, and that a wrong/dangling
# pre-existing link gets re-pointed.
#
# Approach to machine-specific steps (documented per the T1 brief): install.sh
# also runs `uv sync` (slow, writes .venv into the repo) and `systemctl --user`
# (talks to the REAL user manager regardless of $HOME — could restart the live
# autosync watcher). Both are neutralized with PATH shims that log and exit 0,
# so the script's own flow (including the commands block) runs honestly while
# nothing outside the fake HOME is touched. jq stays real (required).
#
# Standalone: bash plugins/self-learn/cli/tests/install-commands-test.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
INSTALL="$REPO/install.sh"
[ -f "$INSTALL" ] || { echo "FAIL: install.sh not found at $INSTALL"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- PATH shims: no-op systemctl + uv ---------------------------------------
SHIMS="$TMP/shims"
mkdir -p "$SHIMS"
for tool in systemctl uv; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$SHIMS/$tool"
  chmod +x "$SHIMS/$tool"
done

FAKE_HOME="$TMP/home"
mkdir -p "$FAKE_HOME"

run_install() {
  HOME="$FAKE_HOME" PATH="$SHIMS:$PATH" bash "$INSTALL" > "$TMP/out.$1" 2>&1 \
    || { echo "FAIL: install.sh run $1 exited non-zero"; cat "$TMP/out.$1"; exit 1; }
}

fail() { echo "FAIL: $1"; exit 1; }

LINK="$FAKE_HOME/.claude/commands/self-learn"
TARGET="$REPO/plugins/self-learn/commands"

# --- 1. fresh run creates the commands symlink -------------------------------
run_install 1
[ -L "$LINK" ] || fail "commands symlink missing after first run"
[ "$(readlink -f "$LINK")" = "$(readlink -f "$TARGET")" ] \
  || fail "symlink points at $(readlink -f "$LINK"), expected $TARGET"
[ -f "$LINK/teach.md" ] && [ -f "$LINK/review.md" ] \
  || fail "teach.md/review.md not reachable through the symlink"

# --- 2. re-run is an idempotent no-op ----------------------------------------
run_install 2
[ -L "$LINK" ] || fail "symlink gone after re-run"
[ "$(readlink -f "$LINK")" = "$(readlink -f "$TARGET")" ] \
  || fail "re-run changed the symlink target"
grep -q "ok    ~/.claude/commands/self-learn" "$TMP/out.2" \
  || fail "re-run did not report the commands link as already-ok"

# --- 3. wrong/dangling pre-existing link is re-pointed ------------------------
rm "$LINK"
ln -s /nonexistent/old-repo/commands "$LINK"
run_install 3
[ "$(readlink -f "$LINK")" = "$(readlink -f "$TARGET")" ] \
  || fail "dangling link was not re-pointed"

echo "PASS: install.sh commands surface (create, idempotent re-run, re-point) — 3/3"
