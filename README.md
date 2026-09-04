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
your own registered host repos (doc 13 §7.3 D1). Concretely: do not
register this repo with `self-learn host add … --skills-root` — that
would make the compiler write into the product repo, which is exactly
what D1 forbids.

## Layout

```
plugins/self-learn/
  cli/                  the Python CLI (uv project; `uv run pytest -q`)
  ui/                    the G-3 web adjudication surface (uv project; localhost, systemd service)
  skills/self-learn/    SKILL.md + references (routing doctrine, card registry)
  commands/             /self-learn:review, /self-learn:teach
  hooks/                self-learn-pending.sh (SessionStart pending-count line)
                        self-learn-refread.sh (PostToolUse reference-read observer)
  scripts/self-learn    ~/bin shim (readlink -f → uv run against cli/)
  scripts/self-learn-ui        ~/bin shim (readlink -f → uv run against ui/; `serve` = the systemd entry point)
  scripts/self-learn-ui-open   ~/bin deep-link launcher / window-focuser (the only WM/browser-aware file)
  scripts/self-learn-notify    ~/bin desktop notifier (swaync action → self-learn-ui-open)
docs/specs/self-learn/  the ratified spec corpus (00–13 + fixtures + reviews)
systemd/                self-learn-host.service (resident host process: nightly mine at 03:30 + worker)
                        self-learn-ui.service (G-3 surface, resident web server)
                        self-learn-miner.{service,timer} (legacy timer route; superseded by the host service)
install.sh              idempotent live-symlink deploy (shims, hooks, skill, commands, units)
```

## Install

### As a Claude Code plugin (the short path)

```
/plugin marketplace add AlexK-Notable/self-learn
/plugin install self-learn@self-learn
```

That gives you the skill and the `/self-learn:*` slash commands.

### Full install — everything the plugin mechanism cannot deliver

The plugin install covers the skill and commands. It does **not** cover
the parts that live outside a plugin's boundary:

- the `~/bin` shims — `self-learn`, `self-learn-ui`, `self-learn-ui-open`,
  `self-learn-notify`
- the `systemd --user` units: `self-learn-host.service` (the resident host
  process that schedules the nightly mine and the worker), `self-learn-ui.service`
  (the G-3 surface), and the legacy `self-learn-miner.{service,timer}`
- the desktop launcher + icon
- the two hook symlinks into `~/.claude/hooks/` — the SessionStart
  pending-count hook and the PostToolUse reference-read hook (registration
  in `settings.json` stays manual either way; see `plugins/self-learn/README.md`)
- `uv sync` of the CLI project

For those, clone and run `install.sh`:

```bash
git clone https://github.com/AlexK-Notable/self-learn.git ~/repos/self-learn
cd ~/repos/self-learn && ./install.sh
# then (manual, load-bearing): register both hooks in ~/.claude/settings.json
systemctl --user enable --now self-learn-host.service  # nightly mine + worker
systemctl --user enable --now self-learn-ui.service    # G-3 surface, see below
```

`self-learn-host.service` is the U-engine host process (`self-learn serve`;
run it in the foreground where there is no systemd). It supersedes the older
`self-learn-miner.timer` route: a timer left enabled alongside it is a
supported belt-and-braces poke, and `self-learn doctor invocation` WARNs
(never fails) when both are enabled.

`install.sh` is a **live-symlink** deploy: the repo working tree *is* the
installed copy, so edits are live next session. The two routes are
alternatives for the skill and commands, not a sequence — pick one.

The model-invoking surfaces run on `claude-agent-sdk`, a base dependency of
the CLI project (`uv sync` installs it; the `[sdk]` extra is now empty and
kept only so older install lines keep working). See
`docs/specs/self-learn/17-invocation-runbook.md`.

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

### Invocation backend and settings (CLI surfaces)

The three CLI surfaces that invoke a model — the pre-analysis worker
(and its repair round), the transcript miner's reader, and the
`teach --route` analyst — run behind one seam as in-process
`claude_agent_sdk` sessions. `sdk` is the only backend
(`invocation/registry.py`, `KNOWN_BACKENDS`); the former `cli` backend (a
`claude -p` subprocess) was removed in U-cleanup, and a stale `cli` setting
is reported and `sdk` used. A second, orthogonal, install-wide switch
selects the `provider` (`anthropic` or `bedrock`).

Operator-facing settings live in one registry (U-settings). `self-learn
doctor settings` lists every setting with its value and source — built-in
default, environment variable, the ledger's `config.yaml`, or an ambient
`SELF_LEARN_OVERRIDE_<name>` variable, which outranks `config.yaml` and is
flagged as an active override. `self-learn config get|set|unset` is the
write path (registry-validated, committed under the ledger's commit lock,
secret-scanned), and the UI's `/settings` page shows the same registry with
source badges and inline editors. `self-learn doctor invocation` reports
what is resolved on this machine; the measured traps are in
`docs/specs/self-learn/17-invocation-runbook.md`. These switches are
deliberately absent from the environment table above: that table is
the UI's.

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

- Tests: `plugins/self-learn/cli/scripts/suite` (the sanctioned CLI runner:
  one pytest-xdist run; `SUITE_WORKERS=N` caps the workers) or, for one
  file, `cd plugins/self-learn/cli && uv run pytest -q tests/<file>.py`.
  UI: `cd plugins/self-learn/ui && uv run pytest -q` — the browser tests need
  Playwright's Chromium and FAIL loudly when it is absent; set
  `SELF_LEARN_UI_NO_BROWSER=1` to opt out of them explicitly.
- Self-check: `self-learn --selftest`
- **No autosync on this repo** (13 §7.3 D3) — commit and push manually.
- The spec corpus in `docs/specs/self-learn/` is the authority; code
  follows it, and substantive changes land with a README revision-log
  entry there. History before 2026-07-17 was extracted from the
  claude-skills monorepo via git-filter-repo (H-6: full provenance
  preserved — `git log --follow` works across the move).

## License

self-learn is licensed under the **Functional Source License, Version
1.1, MIT Future License** — SPDX identifier `FSL-1.1-MIT`. Full text at
[`LICENSE`](./LICENSE).

It is **source-available, not open source**: the License Grant is
conditioned on using the Software for a Permitted Purpose, and Permitted
Purposes specifically include your internal use and access — so you may
use, copy, modify, create derivative works of, and redistribute the
Software, including for internal and commercial purposes, subject to
that condition. What the license bars is **Competing Use**: offering the
Software, or something that substitutes for it or offers substantially
similar functionality, to others as a commercial product or service.

Each version of the Software converts to the plain MIT license,
irrevocably, on the second anniversary of the date that version was made
available — the conversion applies per version, not to the repository as
a whole.

This is a summary for orientation; the [`LICENSE`](./LICENSE) file is
the actual grant and controls if the two ever disagree.
