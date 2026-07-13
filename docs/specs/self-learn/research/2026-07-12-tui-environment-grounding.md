# TUI environment grounding — live-host facts (2026-07-12)

*Measured directly on the deployment host (the machine self-learn v1 targets),
2026-07-12. These are facts the G-3 TUI design may build on without further
verification; anything not listed here needs its own source. Companion memos:
`2026-07-12-agent-sdk-verification.md` (live SDK docs),
`2026-07-12-tui-framework-trade-study.md`.*

## Runtimes

| Fact | Value | How measured |
|---|---|---|
| Node | v22.23.1 | `node --version` |
| npm | 11.17.0 | `npm --version` |
| Python | 3.14.6 | `python3 --version` |
| uv | 0.9.25 | `uv --version` |
| Claude Code CLI | 2.1.207 | `claude --version` |

## Terminal & desktop

| Fact | Value | How measured |
|---|---|---|
| Terminal emulator | **Ghostty 1.3.2** (`TERM=xterm-ghostty`) | `ghostty --version`, `$TERM` |
| Compositor | Hyprland 0.55.4 (Wayland) | `hyprctl version` |
| Window control | `hyprctl` available (dispatch focuswindow etc.) | present in PATH |

> Correction note: earlier project notes assumed kitty; the live terminal is
> **Ghostty**. Both are GPU-accelerated, truecolor, kitty-keyboard-protocol
> terminals, so mainstream TUI frameworks are unaffected — but any pin that
> names the terminal must say Ghostty.

## Notifications

| Fact | Value | How measured |
|---|---|---|
| Daemon | **swaync** (`org.freedesktop.Notifications` owner, pid 3276) | `busctl --user list` |
| Client | notify-send 0.8.8 (libnotify) | `notify-send --version` |
| Action support | `--action/-A` available; **implies `--wait`** — the sending process blocks until the user clicks or the notification is dismissed/expires; chosen action name prints to stdout (or `--selected-action-fd`) | `notify-send --help` |

Design consequence (recorded, not yet designed): a *clickable* deep-link
notification via plain `notify-send -A` makes the **sender** block for the
user's response. The M2 notifier is a short-lived worker step, so the
notification→TUI deep-link needs either a detached blocking helper
(`setsid notify-send -A open … && exec self-learn-tui --record …`) or a
different D-Bus client. This is a G-3 design point, not an M2 change — M2's
pinned `notify-send` payload (human string, no action) is untouched.

## Claude Code CLI headless capabilities (verified on the live binary, 2.1.207)

`claude --help` on this host confirms every capability an embedded
adjudication pane needs, **on the CLI the user's other workers already run
under their normal (subscription) auth**:

| Capability | Flag(s) verified present |
|---|---|
| Bidirectional streaming | `--input-format stream-json`, `--output-format stream-json` (with `-p/--print`) |
| Token-level partial streaming | `--include-partial-messages` (stream-json only) |
| Byte-stable system prompt | `--system-prompt` / `--system-prompt-file`, `--exclude-dynamic-system-prompt-sections` |
| Tool restriction | `--allowedTools`, `--disallowedTools`, `--permission-mode` |
| Model control | `--model`, `--fallback-model` ~~(automatic fallback — the Agent SDK has no equivalent per the SDK memo §6)~~ **CORRECTED 2026-07-12 (phase-A reviewer, empirical — dataclass introspection on installed claude-agent-sdk 0.2.116): `ClaudeAgentOptions` DOES expose `fallback_model`, `max_turns`, and `max_budget_usd`; the SDK-memo-§6 absence claim was doc-derived and is false on the pinned stack**, `--effort` |
| Cost/turn caps | `--max-budget-usd` (and turn caps per headless docs — verify exact flag at build) |
| Context hygiene | `--setting-sources` (empty ⇒ no CLAUDE.md), `--settings`, `--strict-mcp-config`, `--add-dir` |
| Session lifecycle | `--session-id`, `--resume`, `--fork-session`, `--no-session-persistence` |

Design consequence: a "pane engine" built on `claude -p` stream-json is
fully capability-verified on this machine today, and rides the same auth
the M2 worker uses. The Agent SDK memo's API-key-only finding (§2) makes
this the economically material comparison for a heavy-daily-use resident
tool. Both engines are the same underlying agent loop — the SDK spawns
this very CLI — so the choice is wrapper/auth/typing, not capability.

## Repo conventions binding the TUI

- Deploy surface: shebang'd, extensionless entry point symlinked into
  `~/bin` (repo scripts policy); Python tooling in this repo uses uv
  (`cron-claude` precedent).
- The TUI consumes, never redefines, the M1/M2 contracts pinned in
  `08-build-plan.md` §1/§7.1: `list --json` / `status --json` shapes, the
  `events.jsonl` event schema at `~/.cache/claude-skills/self-learn/`,
  sentinel `hold|heartbeat|release` subcommands, and
  `references/routing-doctrine.md` as the pane's doctrine source (one file,
  three consumers).
