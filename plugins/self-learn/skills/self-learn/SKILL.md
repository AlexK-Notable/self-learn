---
name: self-learn
description: Capture, triage, and route durable session lessons into canon. Use when the user corrects a mistake Claude made, states a rule or preference that should outlast the current task, names a gotcha that will recur, says "remember this" / "capture this lesson" / "teach", or wants to review, triage, or route pending lessons. Fronts the `self-learn` CLI (git-backed lesson ledger) and the /self-learn:teach and /self-learn:review commands.
---

# self-learn

A git-backed lesson ledger that decides its own queue. Lessons are captured
as one-record-per-file markdown under the ledger home (`~/.self-learn`, its
own git repo, independent of any code repo — doc 13) in `skills/<name>/`,
`projects/<slug>/`, and `user/` buckets. The **steward** decides the
pending queue every night and the **overseer** examines its work every
week; both route lessons into canon — a skill's SKILL.md managed section,
CLAUDE.md, a references file, a deterministic guard hook, or a new skill —
and skills and hooks are written and activated without asking anyone. A
person steps in only by their own choice: `/self-learn:review`, the web
UI, or a veto. The few things that really need the user (a login, sudo,
spending money, a change to their system outside self-learn, writing into
another repo's git history, a conflict between two things they said,
self-learn broken past its own repair) wait in the inbox the tray icon
opens. Every change is still one attributed git commit (`By: steward`,
`overseer`, `agent` or `human`). Full architecture: `docs/specs/self-learn/`
(01–04, 13).

## When to capture

When the user **corrects wrong behavior, states a standing preference, or
names a gotcha that will recur** — durable lessons only, never one-off
task instructions — compose and capture with `self-learn teach`; report the
id in one line only if the user is mid-conversation about it. Capture is
silent: no offer before, no echo of the wording, no confirmation round
after (the user, 2026-10-31: "capturing a lesson should happen quietly in
the background"). Several serious corrections in one session each get
their own capture. The capture lands in `pending/`; the steward decides its
placement the same night, and the user can see and overturn every decision
in the inbox. A `--statement` that teach records from your shell is stored
`recorded_by: agent`; the words stay the user's through the transcript line
it cites.

## The steward and the overseer

Pending lessons are decided without a person in the loop. The **steward**
runs once a night, after the mine: it reads each candidate's brief and
decides it — a hook route and an always-loaded line included, both are its
own to decide — and **parks** only what it is genuinely unsure of, or what
would spread badly before the next examination, for the **overseer**,
which runs weekly, decides parked items in the user's stead,
re-examines a sample of the week's steward decisions, and writes a
short report. Neither ever treats its own reading of the user as something
the user said: a system-formed reading is marked provisional until a
presentation shows it to them, and silence is never read as agreement.
`/self-learn:review` and the web UI stay open to anyone who wants to step
in; the queue is the steward's either way.

## When the user objects to a skill

Self-learn writes, renames and retires the skills it owns without asking;
never present one to the user or ask about one. When the user says, unasked,
that a skill's name is wrong or that it should go, do it: `self-learn skill
veto <name> [--rename-to <new>]` bans the name for ever (the skill under it
is renamed by the next overseer run, or at once with `--rename-to`);
`self-learn skill rename <old> <new>` renames; `self-learn skill retire
<name>` retires, or, while lessons still route into it, records a request
the next overseer run carries out. From your shell each runs under the
user's standing grant with `--note "<why>"` and is recorded `By: agent`.

## Project notices at session start

In a session inside a project a live notice names, the SessionStart hook
prints one header — "self-learn notices for this project — yours to carry
out in this session (no sudo needed)" — and then each notice. A notice is
this session's agent's work, never a step for the user: carry it out (for
example, commit the file self-learn changed with the command the notice
gives), then run `self-learn notice done <id>`. Do not relay a notice to the
user as something waiting on them.

## CLI surface

From an agent's shell every ledger-writing verb needs `--note "<why>"`
(recorded `By: agent`); `route|reroute|replace|revise|reconsider` also need
`--by analyst|human|agent`. Record your own act as `agent`, never as the
user's: `--by agent`, `case record --actor agent`, `case observe --by
agent`, `statement add --recorded-by agent` (an agent's shell may not pass
`human`; the user's words stay theirs through the transcript ref).

| Verb | Semantics (one line) |
|---|---|
| `status` / `list` | Pending overview / queued records; `--json`; `list --include-deferred` |
| `teach` | Capture ONE lesson into `pending/` (scan-then-write). Scope: `--skill <name>` \| `--project` \| `--user`; type: `--type behavior --trigger … --instruction …` or `--type knowledge --fact …`; `--context …` (either type) is the background, written as `## Context` and never loaded; `--route [--dest …]` resolves immediately. Capture-time grounding (optional, 11 §3): `--verified [--verified-how …]`, `--incident-cost …`, `--generality environment-specific\|general-practice\|uncertain`, `--env COMP=VER` (repeatable) |
| `route <id> [--dest …]` | Compile the record into its destination (proposal or override), commit + push. Known-partial coverage: `--follow-up <action> [--unblocks-on <gate>] [--follow-up-note …]` rides the routing block |
| `followup done <id> [--note …]` | Clear a routed record's open follow-up into a dated `follow_up_done` block |
| `grant add --statement <stmt-…> [--note …]` / `grant list` / `grant revoke <grant-…>` | The user's standing grant, recorded from a statement they typed. While one is in force, an agent's shell runs person-only commands (`host add\|remove\|rebind\|set-mode`, a tier-C `config set\|unset`, `skill write\|rename\|retire\|veto`) with `--note "<why>"`, recorded `By: agent` and `Grant: <stmt>`; without it they refuse |
| `telemetry note <kind> [--reason …]` | Spool one telemetry event. Cache-only — no repo write, no commit. Since silent capture (2026-10-31) no surface logs offers with it |
| `telemetry flush` | Spool → tracked `telemetry/` files in the ledger home (scan-at-flush; the flush commits them — every producer commits its own writes, H-5). Teach/import/resolution verbs flush automatically |
| `report [--json]` | Facts layer v1: lifecycle counts, open follow-ups, deferred aging, offer ledger (silent capture since 2026-10-31; the earlier capture rate is labeled a ceiling) |
| `reject <id>` / `defer <id> [--until D]` / `retire <id> --covered-by <surface>` | Resolve without routing: rejected / hidden until date (default +30 d) / woven into already-loaded canon, the surface named (`graduate` was removed on 2026-10-24) |
| `supersede <old> <new>` | Mark a lesson corrected by a newer one (metadata + recompile) |
| `route <survivor> --collapse <cluster-id>` | Collapse a worker-proposed duplicate cluster in ONE commit: evidence merged, sightings summed, losers superseded by the survivor |
| `confirm-recurrence <id> --event <nonce> [--tolerate --note …]` | A routed rule was sighted failing again: append the dated recurrence (facts copied from the telemetry event). Tolerate = the rule stays, with the why |
| `dismiss-suspect <id> --event <nonce> --why <reason> [--note …]` | A recurrence suspect was a matcher false-positive, not a real recurrence: append the dismissal (facts copied from the telemetry event, which is preserved untouched) |
| `confirm-held <id>` | A routed rule was seen working: stamp `last_confirmed` (the staleness metric is age-since-confirmation) |
| `link contradicts <id> <target>` | First-class contradiction edge to a record id or canon anchor |
| `hook activate <id>` / `hook deactivate <id>` | Place a routed hook's symlink, register it in `~/.claude/settings.json` and verify it — all three steps, always / take it out again. From an agent's shell, with `--note` |
| `batch <sheet>` | Apply a decision sheet in one locked run — the review skill's one apply path; never hand-write a sequence of verb calls |
| `steward run [--dry-run]` | The steward's nightly run, by hand; `--dry-run` writes only its cache stage |
| `overseer open` / `overseer respond …` / `overseer run [--dry-run]` | The overseer's latest report and questions / record a reply / its weekly run, by hand |
| `attention [--json]` / `attention packet <item> --json` | The inbox in a terminal: what needs the user, and what was decided for them / one item's full context |
| `skill list` / `skill write\|rename\|retire\|veto …` | The skills self-learn owns, and their state / change one (person-only; an agent under the grant with `--note`) |
| `premises check` | Run every premise probe now, read-only |
| `doctor invocation` / `doctor settings` | Read-only health views |
| `recompile` / `reconcile` | Re-derive every compiled target from the ledger / inspect or clear a transaction intent (`--clear-intent <id>` after inspecting) |
| `case …` / `statement add\|list` / `user-model …` | The decision-case store, the user-statement store and the model of the user (02 §3a) |
| `host add\|remove\|rebind\|set-mode` / `config get\|set\|unset` | Registered projects / settings (tier-C writes are person-only; an agent under the grant with `--note`) |
| `worker kick` / `worker run [--coalesce]` | Background pre-analysis: teach/import kick a coalescing window (flock + pidfile; no scheduler); the run writes proposals via a write-restricted `claude -p` (no Bash/Edit), validates + stamps them and logs a `proposals` event. It sends no popup |
| `mine run [--trigger …] [--since YYYY-MM-DD]` | Transcript miner (doc 12): read unread session transcripts one session per model call → land `source: session` candidates in pending (use-scaled cap, secret-scanned, origin-deduped; NEVER routes). The host process's nightly mine job (`self-learn serve`), the >24 h verb watchdog and a manual force all call this |
| `mine status [--json]` | The run journal: last run, staleness, and per-candidate outcomes (landed / folded / recurrence / dropped-and-why) |
| `status --fast` | Pending-only full record parse for the SessionStart hook (<500 ms): home and lock state, STOPPED intents, unreadable records, and `project_notices` when the working directory is inside a project a live notice names |
| `notice list [--all] [--json]` \| `notice done <id>` | Project notices (S-106): one line about one project, shown at session start only in sessions inside it. It ends when done, or when its condition clears (a tracked file self-learn left changed is committed); a notice with a condition has no age limit, one without ends after 14 days. Cache only, never the ledger |
| `push` | Retry unpushed resolution commits (rebase-retry, never auto-resolve) |
| `sentinel hold\|heartbeat\|release` | Pause the repo's autosync during review batches (2 h mtime TTL) |
| `import --backlog <skill>` \| `--memory DIR` | One-shot ETL: GOTCHAS journal / auto-memory topic files → pending records (idempotent, origin-deduped) (DIR or `$SELF_LEARN_MEMORY_DIR`; no default) |
| `prune-memory [--dry-run] DIR` | S-13 sweep: delete memory files whose records reached a terminal status (DIR or `$SELF_LEARN_MEMORY_DIR`; no default) |
| `proposal validate <id>` | Scan + schema-check + stamp a record's proposal sibling — REQUIRED after any direct edit of a pending record outside CLI verbs |
| `--selftest` | Loud install checks, **thirteen rows, in this order**: `capture`, `compiler` (dry-run), `markers` (02 §4), `drift` (a compiler-owned target hand-edited since its last compile), `reach` (every `reference`-routed record is reachable from a loaded surface), `hooks` (script intact/executable/byte-matched, incomplete supersession, dangling settings.json registrations), `surface`, `hosts`, `owned_skills`, `sentinel`, `invocation`, `premises`, `steward-queue` |

All record-body writes pass the secret scan: default **refuse** (span +
rule printed), `--redact` opt-in on capture surfaces, no bypass flag.

## Slash commands

- `/self-learn:teach` — extraction UX: compose trigger/instruction/evidence
  from the live session, then call the CLI. Silent: it captures and asks
  nothing.
- `/self-learn:review` — an optional triage batch: the steward decides the
  queue nightly anyway. The review agent decides what it can itself and
  puts a record to the person only for a needs-you reason. Routing
  doctrine: `references/routing-doctrine.md`.
- `/self-learn:overseer` — open the overseer's latest report and its
  questions, and record the user's replies. A stead ask carries the
  default it already applied and waits on nobody; a `needs you; meanwhile`
  ask waits for the user, and one with a plan is decided only by choosing
  one of its options (an inbox click, or `self-learn attention answer`). Never a review session: nothing here approves a lesson.
  The inbox (`self-learn-ui-open --page /inbox`, or `self-learn attention`
  in a terminal) shows the same items with everything needed to decide them.

## The web UI — the inbox and a review venue

The localhost web app (`self-learn-ui-open`) holds the **inbox** the tray
icon opens: each item that needs the user, or that was decided for them,
on one page with its question, the evidence, the recommendation, one-click
answers, a reply box and a read-only agent to ask about it. Pending lessons
can also be reviewed and routed there: keyboard-driven, one decision fully
explained per screen, with an agent pane ("iterate") for talking through a
lesson before routing it. Same CLI verbs underneath — a different venue,
not a second system. Install/launch/keymap/env vars are documented in the
product README's "G-3 surface" section; design is
`docs/specs/self-learn/09-surface-spec.md` + `10-surface-build-plan.md`.

## Environment & exit codes

- `SELF_LEARN_HOME` — the ledger home (default `~/.self-learn`).
- `SELF_LEARN_CLAUDE_DIR` — where hook selfchecks read `settings.json` /
  `hooks/` (default `~/.claude`; tests redirect it).
- `<home>/config.yaml` — operator policy, COMMITTED in the ledger repo
  (S-10 amendment 2026-07-16): `one_motion_route: {hook: true,
  new-skill: true}` enables `teach --route --dest hook --hook-input
  <yaml>` / `--dest new-skill:<name>`. Default (no file) = refuse and
  keep the queued flow; parsing is fail-closed (only the YAML
  boolean `true` enables). Enabled hook routes still validate, scan,
  and replay the compile input pre-commit and PRINT the applied script;
  the guard acts once `self-learn hook activate <id>` has placed,
  registered and verified it (an agent runs it, with `--note`).
- Analyst (bare-terminal `teach --route`): `SELF_LEARN_ANALYST_MODEL`
  (default `claude-sonnet-5`), `SELF_LEARN_ANALYST_TIMEOUT` (default 120 s).
- Exit codes — verbs: 0 ok · 1 refusal (dirty target, scan hit,
  replay/freshness abort on a hook route) · 3 push failed (commit
  kept — run `self-learn push`) · 4 rebase conflict · 64 usage/unknown
  id. (All five destinations compile as of M3 — hook needs a validated
  hook proposal, new-skill is `--dest new-skill:<name>`; the old exit-2
  "unbuilt destination" is gone.) `batch` shares this contract plus one
  new integer, · 8 batch partial (some sheet items applied, some
  refused — the ledger DID change; `batch` returns 1 only when nothing
  landed) — the review skill invokes `batch` as its one apply path,
  never a hand-written sequence of verb calls.
  `proposal validate`: **0 valid+stamped · 1 schema-invalid (file intact) ·
  2 scan hit (wins)**. `teach`'s own usage errors (bad/missing/conflicting
  flags, caught before anything is written) are **64** too (A22, fold r1,
  2026-09-04 — unified with the verbs' own 64 above; a bad *home* is
  still 5, unchanged). `--selftest` (tri-state PASS/FAIL/UNMEASURED per
  row, plus WARN, thirteen rows): 0 all measured and green · 1 any FAIL
  (wins) · 9 no FAIL but at least one row UNMEASURED (a check that could
  not measure anything, e.g. a missing prerequisite it cannot itself
  supply — never read as a silent PASS).

Install, the S-15 capture line, and troubleshooting live in the plugin
README (`plugins/self-learn/README.md`).
