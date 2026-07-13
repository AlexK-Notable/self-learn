---
name: self-learn
description: Capture, triage, and route durable session lessons into canon. Use when the user corrects a mistake Claude made, states a rule or preference that should outlast the current task, names a gotcha that will recur, says "remember this" / "capture this lesson" / "teach", or wants to review, triage, or route pending lessons. Fronts the `self-learn` CLI (git-backed lesson ledger) and the /self-learn:teach and /self-learn:review commands.
---

# self-learn

A git-backed lesson ledger with a human decision gate. Lessons are captured
as one-record-per-file markdown under `.self-learn/` buckets (per-skill +
repo root), triaged in bounded review sessions, and **routed by explicit
human verbs** into canon: a skill's SKILL.md managed section, CLAUDE.md,
or a references file. Nothing edits canon silently; every resolution is a
pinned git commit. Full architecture: `docs/specs/self-learn/` (01–04).

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
| `teach` | Capture ONE lesson into `pending/` (scan-then-write). Scope: `--skill <name>` \| `--project` \| `--user`; type: `--type behavior --trigger … --instruction …` or `--type knowledge --fact … [--context …]`; `--route [--dest …]` resolves immediately |
| `route <id> [--dest …]` | Compile the record into its destination (proposal or override), commit + push |
| `reject <id>` / `defer <id> [--until D]` / `graduate <id>` | Resolve without routing: rejected / hidden until date (default +30 d) / woven into authored canon |
| `supersede <old> <new>` | Mark a lesson corrected by a newer one (metadata + recompile) |
| `push` | Retry unpushed resolution commits (rebase-retry, never auto-resolve) |
| `sentinel hold\|heartbeat\|release` | Pause the repo's autosync during review batches (2 h mtime TTL) |
| `import --backlog <skill>` \| `--memory [dir]` | One-shot ETL: GOTCHAS journal / auto-memory topic files → pending records (idempotent, origin-deduped) |
| `prune-memory [--dry-run] [dir]` | S-13 sweep: delete memory files whose records reached a terminal status |
| `proposal validate <id>` | Scan + schema-check + stamp a record's proposal sibling — REQUIRED after any direct edit of a pending record outside CLI verbs |
| `--selftest` | Loud PASS/FAIL install checks (capture, compiler dry-run, 02 §4 markers, sentinel) |

All record-body writes pass the secret scan: default **refuse** (span +
rule printed), `--redact` opt-in on capture surfaces, no bypass flag.

## Slash commands

- `/self-learn:teach` — extraction UX: compose trigger/instruction/evidence
  from the live session, then call the CLI.
- `/self-learn:review` — bounded triage batch: proposal per card, four
  options (route / reject / defer / discuss), bulk-acknowledge, session-end
  push. Routing doctrine: `references/routing-doctrine.md`.

## Environment & exit codes

- `SELF_LEARN_HOME` — ledger repo root (default `~/repos/claude-skills`).
- Analyst (bare-terminal `teach --route`): `SELF_LEARN_ANALYST_MODEL`
  (default `claude-sonnet-5`), `SELF_LEARN_ANALYST_TIMEOUT` (default 120 s).
- Exit codes — verbs: 0 ok · 1 refusal (dirty target, scan hit, chezmoi
  abort) · 2 usage/unknown id/unbuilt destination · 3 push failed (commit
  kept — run `self-learn push`) · 4 rebase conflict.
  `proposal validate`: **0 valid+stamped · 1 schema-invalid (file intact) ·
  2 scan hit (wins)**. `--selftest`: 0 all green · 1 any FAIL.

Install, the S-15 offer-line setup, and troubleshooting live in the plugin
README (`plugins/self-learn/README.md`).
