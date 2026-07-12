# 01 — Architecture: components, data flow, failure modes

## 1. Overview

```
        SUPPLY                    LEDGER                 PRE-ANALYSIS
  ┌─────────────────┐      ┌──────────────────┐      ┌────────────────┐
  │ teach (CLI/cmd) │─────▶│  per-skill +     │─────▶│ detached worker│
  │ auto-memory     │      │  project buckets │      │ attaches:      │
  │   importer      │      │  (pending        │◀─────│  destination + │
  │ backlog importer│      │   records)       │      │  rationale +   │
  │ [v1.1 appender] │      └────────┬─────────┘      │  draft diff    │
  └─────────────────┘               │                └────────────────┘
                                    │ threshold
                                    ▼
                            ┌──────────────┐         NOTIFICATIONS
                            │ /self-learn: │◀── SessionStart line ·
                            │    review    │    notify-send · statusline
                            │ (Claude Code)│
                            └──────┬───────┘
                                   │ per-item: apply / edit / discuss /
                                   │           reject / defer
                                   ▼
                            ┌──────────────┐
                            │  COMPILERS   │──▶ SKILL.md managed section
                            │  (diff-first,│──▶ CLAUDE.md managed section
                            │  idempotent) │──▶ references/ append
                            └──────┬───────┘──▶ new-skill scaffold (plugin-dev)
                                   │        ──▶ hook scaffold (hookify pattern)
                                   ▼
                              git commit  ──▶ record marked routed(commit)
```

The consumption side has **no runtime of its own**: routed lessons reach
Claude because SKILL.md, CLAUDE.md, references, and hooks are loaded by
Claude Code's native machinery (P2). self-learn's runtime footprint is
capture, analysis, and triage — all outside the session's hot path.

## 2. Scopes

| Scope | Bucket | Typical destinations |
|---|---|---|
| `skill:<name>` | that skill's `.self-learn/` dir | its SKILL.md managed section · its references/ |
| `project` | repo-root `.self-learn/` | repo CLAUDE.md managed section · repo docs |
| `user` | repo-root `.self-learn/` (tagged `user`) | `~/.claude/CLAUDE.md` managed section |

Scope is set at capture (`teach --skill home-assistant`, `--project`,
`--user`; imports carry their origin; transcript `attributionSkill` gives
free skill attribution when a session-derived capture exists). Mis-scoping
is cheap: triage re-routes.

## 3. Components

### 3.1 Ledger (the buckets)

One markdown+frontmatter file per learning (schema in `02-schema.md`), in-repo
so autosync carries buckets across machines and git provides history:

```
plugins/<p>/skills/<s>/.self-learn/    # skill bucket
  pending/lrn-<id>.md
  routed/lrn-<id>.md                   # moved here on routing (with commit ref)
.self-learn/                           # project + user buckets (repo root)
  pending/…   routed/…
```

Record-per-file keeps writes atomic, merges conflict-free, and the format
znote-compatible for a future backend (v2 gate G-5).

### 3.2 Supply

- **`self-learn teach "<lesson>"`** — the primary channel. Flags: scope
  (above), `--type behavior|knowledge` (default: inferred, confirmed in
  output), `--route` (skip the bucket: analyze + apply + commit now, P3).
  Runs mid-session via Bash or a thin `/teach` wrapper; the invocation is the
  capture, well-forming is the tool's job (it may call a small model to
  extract trigger/instruction shape; malformed input echoes back for
  confirmation).
- **Auto-memory importer** — `self-learn import --auto-memory` copies new
  entries from the native memory directory (`~/.claude/projects/<proj>/memory/`)
  into the project bucket as pending learnings (origin preserved). Rationale:
  the platform already captures project-scoped lessons discretionarily
  (E-7); we drain it rather than duplicate it. Auto-memory is machine-local,
  so importing into the in-repo bucket is also what makes those lessons
  multi-machine. On routing, the compiler may prune the corresponding
  memory entry (keeping MEMORY.md lean is part of the value).
- **Backlog importer** — `self-learn import --backlog <skill>` mines existing
  canon (ha-note GOTCHAS journal, SKILL.md gotcha sections) into pending
  records **once**, as an honest one-shot ETL. These enter triage like
  everything else — deriving a trigger from a knowledge fact is inference
  and gets human eyes (gen-1 review finding). A bounded, one-time review of
  a fixed list is a chore the record shows the user will do; a standing
  queue is not (E-3).
- **[v1.1, optional] SessionEnd appender** — a *precision*-tuned structural
  scan (error→fix pairs, `interrupted`, explicit teaching phrases with
  co-occurrence gating; E-10) that appends candidate records. Ships only
  after the triage loop is proven, because SessionEnd delivery is
  best-effort (E-11) and noisy supply is the #2 way to kill the inbox
  (`00-vision.md` P3/P4). Never load-bearing.

### 3.3 Pre-analysis worker

When a learning lands (teach without `--route`, or import), a **detached
`claude -p` worker** (the proven home-net-capture pattern: `setsid`, flock,
survives the session) analyzes it and writes a `proposal` block into the
record: destination, rationale, draft diff, model, timestamp. The analyst
prompt loads the routing doctrine (§3.5) and repo conventions. Proposer and
approver stay distinct by construction — the approver is the human (gen-1's
proposer≠verifier principle, collapsed to its useful core).

Batch behavior: the worker coalesces (one run per N minutes), and at each run
also does **lazy corroboration** — a cheap cluster pass over the pending set
("these three candidates look like the same lesson → merge into one record,
noting 3 sightings"). This is how *"Claude has tried X multiple times…"*
surfaces without any cross-session statistical infrastructure: the pending
bucket **is** the corroboration corpus, examined at analysis time.

### 3.4 Review surface

- **`/self-learn:review`** (Claude Code command/skill — v1's UI): loads
  pending records, presents each as a card (lesson · proposal · diff
  preview) via AskUserQuestion — **Apply / Edit / Discuss / Reject / Defer**
  — applies accepted diffs through the compilers, commits, marks records
  routed. Discuss drops into normal conversation with the analysis context
  loaded, then returns to the queue.
- **`self-learn` CLI** (portable core): `list`, `status`, `teach`, `import`,
  `--selftest`. The CLI is the dependable substrate; the slash command is
  the experience.
- **`--selftest`** (inherited from ha-note): proves capture path, worker
  spawn, and compiler dry-run still work — loud, not silent, when dead.

### 3.5 Compilers (the routing targets)

All compilers are **diff-first** (show, then apply), **idempotent**, and own
only their managed region:

| Target | Mechanism | Notes |
|---|---|---|
| SKILL.md | `<!-- self-learn:begin/end -->` managed section | behavioral rules + skill-scoped knowledge; loads natively at activation. Compiler keeps it tight; weaving learned text into the authored prose is a human editorial act, done whenever the user likes (that *is* gen-1's "Level C", demoted from milestone to habit) |
| CLAUDE.md (repo or `~/.claude/`) | same managed-section pattern | project/user conduct + knowledge |
| `references/<file>` | plain append (ha-note-style) | bulk knowledge; progressive disclosure |
| new skill | delegates to plugin-dev scaffolding | when triage decides a lesson cluster wants to be a skill |
| hook | scaffolds script + prints the `settings.json` snippet | **never auto-registers** (repo doctrine: settings.json is manual) and **always explicit-diff-approved** (P9). For `kind: anti-pattern` lessons where advisory text is the weakest enforcement and a PreToolUse guard is the strongest |

Routing doctrine (the analyst's map, human overridable): behavior/anti-pattern
→ hook candidate or SKILL.md rule · behavior/surface-rule → SKILL.md rule ·
behavior/reasoning-pattern → SKILL.md or CLAUDE.md prose · knowledge, skill
scope → references or SKILL.md section · knowledge, project/user →
CLAUDE.md or docs.

### 3.6 Notifications

Threshold-batched, never per-item: SessionStart context line
("📥 self-learn: 7 pending, oldest 9d — /self-learn:review") + `notify-send`
when crossing thresholds (default: ≥5 pending, or oldest >7 days) + optional
statusline count. Also a **staleness alarm**: "worker hasn't completed a run
in N days" — the silent-death guard for the analysis path.

## 4. The life of one learning (worked example)

1. Mid-session, HA config work goes wrong the familiar way. You type:
   `self-learn teach "when about to edit a .storage/*.json while HA is
   running, stop the container first — HA rewrites .storage on shutdown"
   --skill home-assistant`.
2. A record lands in `plugins/home-assistant/…/.self-learn/pending/`,
   `type: behavior`, `kind: anti-pattern`, source `teach`.
3. The worker attaches a proposal: *destination: hook candidate (PreToolUse
   guard on Edit/Write to `.storage/*` paths) + SKILL.md rule as fallback;
   draft diff for both.* It also notes the backlog import already holds a
   similar GOTCHAS entry → merges, 2 sightings.
4. Next session start: "📥 self-learn: 5 pending…". You run
   `/self-learn:review`. The card shows both options; you pick the hook,
   review the script diff and the settings.json snippet, apply. Commit lands;
   record moves to `routed/` with the commit hash.
5. The rule now fires deterministically forever, costs zero context tokens,
   and its provenance (session, quote, sightings, commit) is one file away.

## 5. Failure modes and their mitigations

| Failure | Why it's the risk | Mitigation (designed-in) |
|---|---|---|
| Inbox rots unworked | E-3: it happened to ha-note | P3 (nothing gates on it) · P4 (one-tap) · P5 (commit reward) · batched nudges with staleness, not spam |
| Noisy supply floods triage | silent capture's base rate (E-2) | v1 supply is explicit + imported only; appender is v1.1, precision-tuned, optional |
| Worker dies silently | detached processes rot (E-5) | staleness alarm in notifications + `--selftest` |
| Bad lesson lands in canon | teach/`--route` is trust-by-invocation | diff shown before apply · git revert · supersede records · managed sections isolate the blast radius |
| Hook compiles from bad text | executable surface | P9: explicit human diff approval, no auto-registration |
| Managed sections bloat canon | every routed token loads every activation | compiler keeps sections terse; triage can route to references instead; periodic weave-in editing |
| Concurrent writers (worker, autosync, sessions) | E-8 | record-per-file · flock on bucket ops · no per-session writes to tracked files |

## 6. Deliberately absent (and where the ideas went)

- **SessionStart directive injection, retrieval ranking, injection caps** —
  wrong mechanism for skill scope; replaced by native loading (E-1, P2).
- **Classifier pipeline (GATE-0, buckets, verifier chain)** — triage + the
  human replace it; the analyst's proposal absorbs its useful judgment.
- **Statistical loop (corroboration counts, reputation, decay clocks,
  quarantine state machine)** — cannot close at this volume (E-2); v2 gate
  G-1. Lazy clustering at analysis time covers the useful fraction now.
- **In-the-moment confirm prompts** — not implementable via hooks (E-12);
  `teach` is the in-the-moment channel.
- **TOML manifest + capability probe + adapter tiers** — portability build
  waits for a second real host (gate G-2); the gen-1 docs are its spec.
- **approve-before-first-use queue** — nothing needs it: pending is already
  inert (P1), and explicit captures are approved by invocation.
