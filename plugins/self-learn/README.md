# self-learn — plugin README

Git-backed lesson ledger: capture durable session lessons, triage them in
bounded review sessions, route them into canon by explicit human verbs.
The loaded surface is `skills/self-learn/SKILL.md` (kept tight — E-6);
this README holds install detail, the offer-line setup, environment, and
troubleshooting. Design corpus: `docs/specs/self-learn/`.

## Install

The short route is the root README's `/plugin marketplace add
AlexK-Notable/self-learn` path — it gets you the skill and commands. What
follows here is the full/development install.

From the repo root:

```bash
./install.sh
```

Idempotent; what it deploys for this plugin (live symlinks — edits in the
repo are live next session; this is the development deploy, not `/plugin
install`):

| Runtime path | → repo source | Purpose |
|---|---|---|
| `~/.claude/skills/self-learn` | `plugins/self-learn/skills/self-learn/` | native skill activation |
| `~/.claude/commands/self-learn` | `plugins/self-learn/commands/` | `/self-learn:teach`, `/self-learn:review` |
| `~/bin/self-learn` | `plugins/self-learn/scripts/self-learn` | the CLI (uv wrapper over `cli/`) |

`install.sh` also runs `uv sync` for `plugins/self-learn/cli/`. Verify the
install with:

```bash
self-learn --selftest
```

## The offer line (S-15) — a documented install step

The capture loop starts with Claude *offering* to record a lesson. That
behavior comes from one paragraph in `~/.claude/CLAUDE.md` — a **plain
host**: edit the file directly, there is no separate managed source to
run through first, and self-learn itself never commits it.

```bash
$EDITOR ~/.claude/CLAUDE.md   # add the paragraph below, then save
```

Paste this text exactly (load-bearing spec — 08 §1; revocable by deleting
the paragraph):

```
When I correct a mistake you made, or state a rule/preference that should change how you work beyond this task, offer once and briefly to capture it (`self-learn teach`); if declined, log it: `self-learn telemetry note offer-declined [--reason <enum>]`. Offer only for durable lessons — corrections of wrong behavior, standing preferences, gotchas that will recur — never for one-off task instructions. Several serious corrections in one session each deserve an offer.
```

## SessionStart hook (M2) — manual registration required

`hooks/self-learn-pending.sh` prints the pending line, the worker
staleness alarm, and the escalation line into session context. It only
formats `self-learn status --fast` output (queue semantics live in the
CLI, never in bash) and never calls notify-send.

install.sh symlinks the script into `~/.claude/hooks/`; registration in
`~/.claude/settings.json` is **manual** (settings.json is load-bearing —
per the repo's per-plugin-hooks convention). Add under `"hooks"`:

```json
"SessionStart": [
  {"matcher": "",
   "hooks": [{"type": "command",
              "command": "$HOME/.claude/hooks/self-learn-pending.sh"}]}
]
```

Staleness fires iff ≥1 pending record lacks a valid proposal AND
`worker.last-run` is >3 days old or missing. Quiet queues never alarm.

## PostToolUse reference-read hook (U-readref) — manual registration required

`hooks/self-learn-refread.sh` observes "a `references/*.md` file was
actually opened" — the on-demand tier's effectiveness was otherwise
entirely unmeasured (S-23's reopening condition; see the design corpus).
It never reads the file body: it extracts only the read path, the session
id, and whether the read came from a subagent, then spools a code-emitted
`reference-read` telemetry event (ids only — 11 §4.4) iff the path resolves
to a REGISTERED references target. It never fails the Read it rides on and
never writes to stdout, on every path including every error path.

install.sh symlinks the script into `~/.claude/hooks/`; registration in
`~/.claude/settings.json` is **manual** (settings.json is load-bearing —
per the repo's per-plugin-hooks convention; U-readref §4.4 ruled against
migrating to a plugin-provided hook: a hand-edit that breaks the file is
detectable here and would not be, there). Add under `"hooks"`:

```json
"PostToolUse": [
  {"matcher": "Read",
   "hooks": [{"type": "command",
              "command": "$HOME/.claude/hooks/self-learn-refread.sh",
              "timeout": 5}]}
]
```

`self-learn report` prints a `Reference shelf` block from what this hook
observes; a zero-read target is never omitted, and an un-instrumented
shelf (script missing, not registered, or an unparseable settings.json)
renders every read count as ABSENT — never as a false zero.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `SELF_LEARN_HOME` | `~/.self-learn` | the ledger home (its own git repo); all buckets resolve under it |
| `SELF_LEARN_ANALYST_MODEL` | `claude-sonnet-5` | model for the one-shot `teach --route` analyst |
| `SELF_LEARN_ANALYST_TIMEOUT` | `120` | analyst timeout, seconds |
| `SELF_LEARN_MEMORY_DIR` | (unset — required) | `import --memory` / `prune-memory` target dir; no default, both verbs refuse without it |
| `SELF_LEARN_WORKER_MODEL` | `claude-sonnet-5` | model for the background worker's analysis pass |
| `SELF_LEARN_COALESCE_SECS` | `600` | worker kick coalescing window, seconds |
| `SELF_LEARN_WORKER_AUTOKICK` | (unset) | set `0` to disable teach/import auto-kick (test suites) |
| `SELF_LEARN_MINER` | (unset) | set `0` to disable the transcript miner entirely (runs + watchdog + staleness alarm) |
| `SELF_LEARN_MINER_AUTOKICK` | (unset) | set `0` to disable only the >24 h verb watchdog spawn |
| `SELF_LEARN_MINER_MODEL` | `claude-sonnet-5` | model for the miner's contained reader pass |
| `SELF_LEARN_MINE_CAP_PER_SESSION` | `2` | landings allowed per scanned session (use-scaled cap) |
| `SELF_LEARN_MINE_CAP_MAX` | `15` | absolute landing ceiling per run |
| `SELF_LEARN_MINE_PENDING_GATE` | `25` | miner lands nothing while total pending ≥ this |
| `SELF_LEARN_TRANSCRIPTS_DIR` | `~/.claude/projects` | transcript corpus root (tests redirect it) |

## Transcript miner (doc 12) — nightly timer registration

The miner is the third capture producer: it walks session transcripts,
digests them structurally, runs one contained `claude -p` reader (same
write-restriction posture as the worker, pointed at a cache spool), and
lands `source: session` records in `pending/` — capped, secret-scanned,
never routed. `install.sh` already links the nightly timer's unit files
into `~/.config/systemd/user/` (or `$XDG_CONFIG_HOME/systemd/user/` if
that variable is set — U-servehermetic, 2026-08-27) (R1 layer 1;
`Persistent=true` covers a machine asleep at 03:30); enabling it is the
one step it deliberately leaves to you:

```bash
systemctl --user enable --now self-learn-miner.timer
```

Layers 2–3 need no registration: any `self-learn` verb spawns a catch-up
run when the last one is >24 h old, and the SessionStart hook prints a
staleness line at >36 h. Force a run any time with `self-learn mine run`
(`--since YYYY-MM-DD` for a deliberate historical sweep); inspect runs
with `self-learn mine status` (the run journal answers what was caught,
skipped, folded, and clipped — the same data the future web UI reads).

## Troubleshooting

- **Secret scan refusal** (`secret scan: N hits — refusing this write`):
  rephrase/shorten the quoted material, or use `--redact` on capture
  surfaces (writes `[redacted:<rule>]` + `redacted: true`). There is
  deliberately **no bypass flag** in v1.
- **`PUSH FAILED — commit kept`** (exit 3): the resolution committed
  locally; run `self-learn push` (rebase-retry built in). A rebase
  conflict (exit 4) stops loudly — resolve by hand, never auto-resolved.
- **Stale sentinel** (`~/.cache/self-learn/autosync-pause` older than
  2 h): ignorable — semantics ride the file's mtime, both sides ignore a
  stale one and either may delete it.
- **`--selftest` FAIL markers** naming a file: that target has ≥1 routed
  record but a missing/broken managed-section marker pair — restore the
  pair (or re-run `route` for a fresh target; the compiler bootstraps
  markers at EOF on first route).
- **Record edited directly** (outside CLI verbs, e.g. during a review
  Discuss tangent): finish with `self-learn proposal validate <id>` —
  exit 0 stamps the proposal, 1 = schema problem (file left intact),
  2 = secret-scan hit (redact before the card can complete).
