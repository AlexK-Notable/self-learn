---
name: self-learn
description: Capture, triage, and route durable session lessons into canon. Use when the user corrects a mistake Claude made, states a rule or preference that should outlast the current task, names a gotcha that will recur, says "remember this" / "capture this lesson" / "teach", or wants to review, triage, or route pending lessons. Fronts the `self-learn` CLI (git-backed lesson ledger) and the /self-learn:teach and /self-learn:review commands.
---

# self-learn

A git-backed lesson ledger with a human decision gate. Lessons are captured
as one-record-per-file markdown under the ledger home (`~/.self-learn`, its
own git repo, independent of any code repo — doc 13) in `skills/<name>/`,
`projects/<slug>/`, and `user/` buckets, triaged in bounded review
sessions, and **routed by explicit human verbs** into canon: a skill's
SKILL.md managed section, CLAUDE.md, a references file, a deterministic
guard hook (M3 — human-approved script, verbatim two-phase apply), or a
new-skill scaffold. Nothing edits canon silently; every resolution is a
pinned git commit. Full architecture: `docs/specs/self-learn/` (01–04, 13).

## When to offer capture

Offer `self-learn teach` once and briefly when the user **corrects wrong
behavior, states a standing preference, or names a gotcha that will
recur** — durable lessons only, never one-off task instructions. Several
serious corrections in one session each deserve an offer. Invocation is
the approval: if the user says capture it, run teach — no confirmation
prompt after.

## CLI surface

| Verb | Semantics (one line) |
|---|---|
| `status` / `list` | Pending overview / queued records; `--json`; `list --include-deferred` |
| `teach` | Capture ONE lesson into `pending/` (scan-then-write). Scope: `--skill <name>` \| `--project` \| `--user`; type: `--type behavior --trigger … --instruction …` or `--type knowledge --fact … [--context …]`; `--route [--dest …]` resolves immediately. Capture-time grounding (optional-but-offered, 11 §3): `--verified [--verified-how …]`, `--incident-cost …`, `--generality environment-specific\|general-practice\|uncertain`, `--env COMP=VER` (repeatable) |
| `route <id> [--dest …]` | Compile the record into its destination (proposal or override), commit + push. Known-partial coverage: `--follow-up <action> [--unblocks-on <gate>] [--follow-up-note …]` rides the routing block |
| `followup done <id> [--note …]` | Clear a routed record's open follow-up into a dated `follow_up_done` block |
| `telemetry note <kind> [--reason …]` | Spool one offer-ledger event (`offer-made` \| `offer-declined`, reason enum: not-durable\|wrong\|duplicate\|private\|later\|other). Cache-only — no repo write, no commit |
| `telemetry flush` | Spool → tracked `telemetry/` files in the ledger home (scan-at-flush; the flush commits them — every producer commits its own writes, H-5). Teach/import/resolution verbs flush automatically |
| `report [--json]` | Facts layer v1: lifecycle counts, open follow-ups, deferred aging, offer ledger (capture rate labeled as a ceiling — declined-offer logging is best-effort) |
| `reject <id>` / `defer <id> [--until D]` / `graduate <id>` | Resolve without routing: rejected / hidden until date (default +30 d) / woven into authored canon |
| `supersede <old> <new>` | Mark a lesson corrected by a newer one (metadata + recompile) |
| `route <survivor> --collapse <cluster-id>` | Collapse a worker-proposed duplicate cluster in ONE commit: evidence merged, sightings summed, losers superseded by the survivor |
| `confirm-recurrence <id> --event <nonce> [--tolerate --note …]` | A routed rule was sighted failing again: append the dated recurrence (facts copied from the telemetry event). Tolerate = the rule stays, with the why |
| `confirm-held <id>` | A routed rule was seen working: stamp `last_confirmed` (the staleness metric is age-since-confirmation) |
| `link contradicts <id> <target>` | First-class contradiction edge to a record id or canon anchor |
| `worker kick` / `worker run [--coalesce]` | Background pre-analysis: teach/import kick a coalescing window (flock + pidfile; no scheduler); the run writes proposals via a write-restricted `claude -p` (no Bash/Edit), validates + stamps them, emits events + notifications |
| `mine run [--trigger …] [--since YYYY-MM-DD]` | Transcript miner (doc 12): digest unread session transcripts → contained reader → land `source: session` candidates in pending (use-scaled cap, secret-scanned, origin-deduped; NEVER routes). Nightly timer + >24 h verb watchdog + manual force all call this |
| `mine status [--json]` | The run journal: last run, staleness, and per-candidate outcomes (landed / folded / recurrence / dropped-and-why) |
| `status --fast` | Pending-only frontmatter scan for the SessionStart hook (<500 ms; staleness + escalation flags) |
| `push` | Retry unpushed resolution commits (rebase-retry, never auto-resolve) |
| `sentinel hold\|heartbeat\|release` | Pause the repo's autosync during review batches (2 h mtime TTL) |
| `import --backlog <skill>` \| `--memory DIR` | One-shot ETL: GOTCHAS journal / auto-memory topic files → pending records (idempotent, origin-deduped) (DIR or `$SELF_LEARN_MEMORY_DIR`; no default) |
| `prune-memory [--dry-run] DIR` | S-13 sweep: delete memory files whose records reached a terminal status (DIR or `$SELF_LEARN_MEMORY_DIR`; no default) |
| `proposal validate <id>` | Scan + schema-check + stamp a record's proposal sibling — REQUIRED after any direct edit of a pending record outside CLI verbs |
| `--selftest` | Loud PASS/FAIL install checks (capture, compiler dry-run, 02 §4 markers, sentinel, hooks: script intact/executable/byte-matched, incomplete supersession, dangling settings.json registrations) |

All record-body writes pass the secret scan: default **refuse** (span +
rule printed), `--redact` opt-in on capture surfaces, no bypass flag.

## Slash commands

- `/self-learn:teach` — extraction UX: compose trigger/instruction/evidence
  from the live session, then call the CLI.
- `/self-learn:review` — bounded triage batch: proposal per card, four
  options (route / reject / defer / discuss), bulk-acknowledge, session-end
  push. Routing doctrine: `references/routing-doctrine.md`.

## The G-3 surface — a richer review venue

Alongside `/self-learn:review`, pending lessons can be reviewed and routed
in a dedicated localhost web app (`self-learn-ui-open`): keyboard-driven,
one decision fully explained per screen, with an agent pane ("iterate")
for talking through a lesson before routing it. Same CLI verbs underneath
— it's a different venue for the same review-then-route act, not a second
system. The slash command stays as the in-session option when leaving
Claude Code isn't worth it; the surface is the better choice for a batch
or for anything that benefits from more screen space. Install/launch/
keymap/env vars are documented in the product README's "G-3 surface"
section; design is `docs/specs/self-learn/09-surface-spec.md` +
`10-surface-build-plan.md`.

## Environment & exit codes

- `SELF_LEARN_HOME` — the ledger home (default `~/.self-learn`).
- `SELF_LEARN_CLAUDE_DIR` — where hook selfchecks read `settings.json` /
  `hooks/` (default `~/.claude`; tests redirect it).
- `<home>/config.yaml` — operator policy, COMMITTED in the ledger repo
  (S-10 amendment 2026-07-16): `one_motion_route: {hook: true,
  new-skill: true}` enables `teach --route --dest hook --hook-input
  <yaml>` / `--dest new-skill:<name>`. Default (no file) = refuse and
  keep the review-gated flow; parsing is fail-closed (only the YAML
  boolean `true` enables). Enabled hook routes still validate, scan,
  and replay the compile input pre-commit and PRINT the applied script;
  the settings.json registration step stays manual either way.
- Analyst (bare-terminal `teach --route`): `SELF_LEARN_ANALYST_MODEL`
  (default `claude-sonnet-5`), `SELF_LEARN_ANALYST_TIMEOUT` (default 120 s).
- Exit codes — verbs: 0 ok · 1 refusal (dirty target, scan hit, chezmoi
  abort, replay/freshness abort on a hook route) · 3 push failed (commit
  kept — run `self-learn push`) · 4 rebase conflict · 64 usage/unknown
  id. (All five destinations compile as of M3 — hook needs a validated
  hook proposal, new-skill is `--dest new-skill:<name>`; the old exit-2
  "unbuilt destination" is gone.)
  `proposal validate`: **0 valid+stamped · 1 schema-invalid (file intact) ·
  2 scan hit (wins)**. `--selftest`: 0 all green · 1 any FAIL.

Install, the S-15 offer-line setup, and troubleshooting live in the plugin
README (`plugins/self-learn/README.md`).
