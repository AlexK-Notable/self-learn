# self-learn

A capture → triage → route system for lessons learned in Claude Code
sessions. Lessons accumulate inertly in a git-backed ledger
(`~/.self-learn`), a background analyst proposes routings, and a
human-gated review compiles approved lessons into the places future
sessions actually load: SKILL.md managed sections, CLAUDE.md, reference
files, deterministic PreToolUse guard scripts, and new-skill scaffolds.

**This repo is the PRODUCT** — CLI, plugin (skill + commands + hooks),
spec corpus, and the nightly transcript-miner units. It is a tool unto
itself: nothing is committed here except work specific to its own
development. Your lessons live in your ledger; compiled output lands in
your own registered host repos (doc 13 §7.3 D1).

## Layout

```
plugins/self-learn/
  cli/                  the Python CLI (uv project; `uv run pytest -q`)
  ui/                    the G-3 web adjudication surface (uv project; localhost, systemd service)
  skills/self-learn/    SKILL.md + references (routing doctrine, card registry)
  commands/             /self-learn:review, /self-learn:teach
  hooks/                self-learn-pending.sh (SessionStart pending-count line)
  scripts/self-learn    ~/bin shim (readlink -f → uv run against cli/)
  scripts/self-learn-ui        ~/bin shim (readlink -f → uv run against ui/; `serve` = the systemd entry point)
  scripts/self-learn-ui-open   ~/bin deep-link launcher / window-focuser (the only WM/browser-aware file)
  scripts/self-learn-notify    ~/bin desktop notifier (swaync action → self-learn-ui-open)
docs/specs/self-learn/  the ratified spec corpus (00–13 + fixtures + reviews)
systemd/                self-learn-miner.{service,timer} (nightly mine, 03:40)
                        self-learn-ui.service (G-3 surface, resident web server)
install.sh              idempotent live-symlink deploy (eight surfaces + units)
```

## Install (this machine's live-symlink model)

```bash
# self-learn is a PRIVATE repo — cloning it needs an SSH key on file
# with access to AlexK-Notable/self-learn (P-C1.4: private, by ruling)
git clone git@github.com:AlexK-Notable/self-learn.git ~/repos/self-learn
cd ~/repos/self-learn && ./install.sh
# then (manual, load-bearing): register hooks in ~/.claude/settings.json
systemctl --user enable --now self-learn-miner.timer
systemctl --user enable --now self-learn-ui.service   # G-3 surface, see below
```

The ledger needs a git repo at `$SELF_LEARN_HOME` (default
`~/.self-learn`) before anything else works — bootstrap one with
`self-learn init`; then register canon targets with `self-learn host add
<path> [--skills-root]`.

## G-3 surface — web adjudication UI

A localhost-only web app for reviewing and routing pending lessons — the
richer alternative to `/self-learn:review` inside a Claude Code session
(same underlying CLI verbs; see `plugins/self-learn/skills/self-learn/SKILL.md`
for how the two venues relate). It runs as a resident `systemd --user`
service (the server is the single instance; multiple browser tabs/windows
are concurrent readers of one process) bound to `127.0.0.1` only, and
presents as a dedicated, chromeless browser app window.

### Launch

```bash
self-learn-ui-open                    # starts the service if needed, opens/focuses the window
self-learn-ui-open --record <id>      # deep-link straight to one record's Detail page
```

or, to run the service directly without the launcher's window handling:

```bash
systemctl --user enable --now self-learn-ui.service   # one-time
self-learn-ui-open                                     # every subsequent open
```

No-systemd fallback: run the server in the foreground with
`self-learn-ui serve` and open `http://127.0.0.1:7357/` (or your
configured port) in any browser.

### Keyboard model

Single keys only, no chords — the browser keeps ownership of Ctrl+W/T/N/L,
so the keymap is designed to never train your hand toward them. Keys are
inert while focus is in a text input.

| Key | Action |
|---|---|
| `j`/`k`, arrows | move within a list |
| `Enter`/`l` | drill in |
| `Esc`/`h` | up a level (`Esc` in an active pane interrupts first) |
| `a` | route (approve) |
| `d` | reject (deny) |
| `f` | defer |
| `g` | graduate |
| `i` | iterate (open the adjudication pane) |
| `o` | cycle override destination |
| `n` | attach/edit a note |
| `t`/`c` | tolerate / confirm, on an "is it holding?" recurrence row |
| `r` | retry the pane |
| `q` | (pane focused) close the split — ends the session |
| `?` | help overlay (full keymap reference) |

Resolution keys **arm** the action bar (showing exactly what will run);
`Enter` executes, any other key disarms — one extra keystroke, zero
confirmation dialogs.

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `SELF_LEARN_HOME` | `~/.self-learn` | the ledger home (shared with the CLI) |
| `SELF_LEARN_UI_PORT` | `7357` | server bind port (127.0.0.1 only) |
| `SELF_LEARN_UI_BROWSER` | *(auto)* | launcher-only — `self-learn-ui-open` tries this browser binary first, then `chromium`, then `google-chrome-stable`, then falls back to `xdg-open`. Never read by the server. |
| `SELF_LEARN_PANE_MODEL` | `claude-sonnet-5` | model for the adjudication (iterate) pane |
| `SELF_LEARN_PANE_BUDGET_USD` | `1.00` | per-session cost cap for the pane |
| `SELF_LEARN_PANE_MAX_TURNS` | `15` | per-session turn cap for the pane |
| `SELF_LEARN_PANE_ENGINE` | `sdk` | `sdk` is the only built engine; `cli` exits with "engine not built" — it is specced (09 §4.1) but not implemented in this milestone |

### Pane engine note

The adjudication pane ("iterate") runs a scoped `claude-agent-sdk` session
under a permission charter: no Bash/Task/WebSearch/WebFetch, and
Read/Grep/Glob restricted to the resolved ledger home, registered hosts'
canon surfaces, and the plugin's own references — everything else is
denied with a reason. The `cli` engine value is reserved for a future
subprocess-based engine satisfying the same event protocol; it is not
built yet, so setting `SELF_LEARN_PANE_ENGINE=cli` is a deliberate,
documented no-op-with-explanation, not a silent fallback.

### Browser notes

- **Chromium-family** (`chromium`, `google-chrome-stable`, …) gets the
  intended experience: a dedicated app window via `--app=<url>
  --class=self-learn-ui`, which `self-learn-ui-open` also uses for
  window-presence detection (via `hyprctl clients -j` on Hyprland) so a
  second launch focuses the existing window instead of opening a new one.
- **Firefox** has no `--app` equivalent and any other browser without one
  degrades to a plain tab (`xdg-open <url>`) — everything still works,
  minus the dedicated-window feel.
- **Vimium and similar keyboard-extension add-ons** intercept single-key
  presses the same way the surface's own keymap does. Add a
  `localhost:7357` (or your configured port) exclusion in the extension's
  settings so its keys don't shadow the app's.

### Optional polish: Hyprland window rule

Not required — the presentation degrades gracefully without it (plain
floating/tiled window instead of a pinned one). To pin the app window
(e.g. as a floating window of a fixed size), add to your Hyprland config:

```
windowrule = float, class:^(self-learn-ui)$
windowrule = size 1100 800, class:^(self-learn-ui)$
windowrule = center, class:^(self-learn-ui)$
```

Adjust the rule type/size to taste — the only pinned contract is the
window class, `self-learn-ui`, which the launcher's presence-detection
also relies on.

## Development

- Tests: `cd plugins/self-learn/cli && uv run pytest -q`
- Self-check: `self-learn --selftest`
- **No autosync on this repo** (13 §7.3 D3) — commit and push manually.
- The spec corpus in `docs/specs/self-learn/` is the authority; code
  follows it, and substantive changes land with a README revision-log
  entry there. History before 2026-07-17 was extracted from the
  claude-skills monorepo via git-filter-repo (H-6: full provenance
  preserved — `git log --follow` works across the move).
