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

**v1 territory, stated plainly:** skill scopes and the user scope are served
from anywhere (their buckets and destinations live in this repo and
`~/.claude/`); the `project` scope covers **this repo only**. Lessons
project-scoped to *other* repos have no v1 destination — they ride native
auto-memory until a second host exists (G-2). This is a coverage statement,
not an accident.

## 3. Components

### 3.1 Ledger (the buckets)

One markdown+frontmatter file per learning (schema in `02-schema.md`), in-repo
so autosync carries buckets across machines and git provides history:

```
plugins/<p>/skills/<s>/.self-learn/    # skill bucket
  pending/lrn-<id>.md
  resolved/lrn-<id>.md                 # moved here on resolution: routed
                                       #   (with commit ref) · rejected ·
                                       #   superseded
  proposals/lrn-<id>.yaml              # worker analyses (records untouched)
.self-learn/                           # project + user buckets (repo root)
  pending/…   resolved/…   proposals/…
```

Record-per-file keeps writes atomic, merges conflict-free, and the format
znote-compatible for a future backend (v2 gate G-5).

### 3.2 Supply

- **`self-learn teach "<lesson>"`** — the primary channel. Flags: scope
  (above), `--type behavior|knowledge` (default: inferred, confirmed in
  output), `--trigger`/`--instruction`/`--evidence-session` (structured
  fields), `--route` (skip the bucket: analyze + apply + commit now, P3).
  **The primary UX is in-session capture with the session model as the
  extractor**: the user says "capture that as a lesson" (or runs `/teach`),
  and the Claude that just *watched the failure* — holding the transcript,
  the error, and the session id — composes trigger, instruction, and
  evidence, then invokes the CLI with the structured flags. That beats any
  after-the-fact extraction from a terse string, and it attacks capture
  friction (the problem statement's #1) directly. The CLI remains the
  dependable substrate; its small-model well-forming fallback exists only
  for bare-terminal captures with no session in context. `teach` runs a
  capture-time secret scan before writing (autosync publishes records within
  seconds — `02-schema.md` §2) and echoes malformed input back for
  confirmation.
- **Auto-memory importer** — `self-learn import --auto-memory` copies new
  entries from the native memory directory (`~/.claude/projects/<proj>/memory/`)
  into the project bucket as pending learnings (origin preserved). Rationale:
  the platform already captures project-scoped lessons discretionarily
  (E-7); we drain it rather than duplicate it. Auto-memory is machine-local,
  so importing into the in-repo bucket is also what makes those lessons
  multi-machine. On routing — or rejection — the compiler may prune the
  corresponding memory entry with confirmation (keeping MEMORY.md lean is
  part of the value; a rejected entry left behind eats the E-7 cap forever,
  O-5). Imports **dedupe by `evidence.origin` against all records in all
  statuses** — a rejected entry must not resurrect on the next run, and
  because the dedupe ledger *is* the records, it syncs across machines for
  free. v1 drains this repo's own project memory; sweeping other projects'
  memory dirs for skill-/user-scoped entries is O-2's open extension.
- **Backlog importer** — `self-learn import --backlog <skill>` mines existing
  canon (ha-note GOTCHAS journal, SKILL.md gotcha sections) into pending
  records **once**, as an honest one-shot ETL. These enter triage like
  everything else — deriving a trigger from a knowledge fact is inference
  and gets human eyes (gen-1 review finding). **The import flags knowledge
  entries whose substance already lives in loaded canon** — the GOTCHAS
  journal *is* a reference doc — so triage presents those as one
  bulk-acknowledge card (resolved as `superseded_by: canon` — the schema's
  existing already-in-canon semantics, `02-schema.md` §4 — no diff) and spends its
  per-item cards on the behavioral minority (E-2: ~5–7 of ~58) plus anything
  the analyst flags as misfiled. Re-routing ~50 facts one card at a time
  into the file they already occupy would burn the honeymoon session (E-3)
  on make-work. A bounded, one-time review of a fixed list is a chore the
  record shows the user will do; a standing queue is not (E-3).
- **[open, O-6] Model-prompted offers** — a one-line standing instruction
  ("when the user corrects a mistake or states a durable preference while a
  skill is active, *offer* `self-learn teach`"). Still explicit,
  human-confirmed capture — S-3's rationale intact — and the only automatic
  supply the **skill** scope would have (auto-memory feeds only the
  project/user scopes). Revocable in one line if it over-offers.
- **[v1.1, optional] SessionEnd appender** — a *precision*-tuned structural
  scan (error→fix pairs, `interrupted`, explicit teaching phrases with
  co-occurrence gating; E-10) that appends candidate records. Ships only
  after the triage loop is proven, because SessionEnd delivery is
  best-effort (E-11) and noisy supply is the #2 way to kill the inbox
  (`00-vision.md` P3/P4). Never load-bearing.

### 3.3 Pre-analysis worker

When a learning lands (teach without `--route`, or import), a **detached
`claude -p` worker** (the proven home-net-capture pattern: `setsid`, flock,
survives the session) analyzes it and writes the proposal — destination,
rationale, draft diff, model, timestamp — to `proposals/lrn-<id>.yaml`, a
**sibling file; the record itself is untouched** (`02-schema.md` §1). The
analyst prompt loads the routing doctrine (§3.5) and repo conventions.
Proposer and approver stay distinct by construction — the approver is the
human (gen-1's proposer≠verifier principle, collapsed to its useful core).

Two constraints keep the worker honest and race-free:

- **The worker is append-only — merges included** *(blind re-review
  2026-07-12)*. Clustering never mutates records: when the worker judges
  that several pending records look like one lesson, it writes
  `proposals/merge-<clusterid>.yaml` naming them. The review surface shows
  the cluster as a single card ("3 sightings"), and the **human** collapses
  it at apply time — route the survivor (its `evidence` gains the merged
  records' provenance then, at routing), mark the rest `superseded`. With
  record mutation gone, no designated-analysis-host or claim-marker
  machinery is needed: **any machine may run the worker**, because proposal
  writes are new files that never collide, and machine-local flock only has
  to serialize runs on its own host.
- **Restricted permissions.** The worker runs `claude -p` with
  `--allowedTools` limited to reading the repo and writing new files under
  `.self-learn/**/proposals/`. It processes model-written (auto-memory) and
  journal-imported text, so a poisoned lesson can steer it no further than a
  bad proposal a human will read (P1/P9, defense in depth) — literally true,
  since the worker holds no write path to any record.

Batch behavior: the worker coalesces (one run per N minutes), and at each run
also does **lazy corroboration** — a cheap cluster pass over the pending set
("these three candidates look like the same lesson" → a merge proposal the
next review collapses). This is how *"Claude has tried X multiple times…"*
surfaces without any cross-session statistical infrastructure: the pending
bucket **is** the corroboration corpus, examined at analysis time.

From M2 the analyst prompt also carries a **rejected-proposal digest** — the
recent rejections in `resolved/` with their resolving commit messages — as
negative exemplars, so the worker stops proposing classes of lesson the
human has already declined (SkillOpt's rejected-edit-buffer pattern, E-20).
A queue that re-surfaces rejected material is the fastest way to re-run E-3;
the digest costs nothing because rejection provenance already lives in git.

### 3.4 Review surface

- **`/self-learn:review`** (Claude Code command/skill — v1's UI): loads a
  **bounded batch** of pending records (default ~10, oldest first; scopable
  `--skill X`) and presents each as a card via AskUserQuestion — **Apply /
  Discuss / Reject / Defer**. Four options is the tool's hard limit (E-16);
  *Edit* lives inside Discuss, which is where editing happens naturally, and
  the auto-added free-text "Other" is always available. The draft diff
  renders in the Apply option's `preview`; homogeneous groups (e.g. the
  backlog's already-canon entries) collapse into one multiSelect bulk card.
  On Apply, the compilers **apply the record, not the diff** — the diff is a
  preview, and output is regenerated against the target's current state, so
  proposal staleness is harmless by construction. (Honesty note: what lands
  is the regenerated section, which can differ from the previewed diff and
  may touch other lessons' lines — the card says so.) Each routed lesson gets
  **its own commit**, whose message carries the record id
  (`self-learn: route lrn-… → <target>`) — the message *is* the
  record→commit linkage, since a commit's own hash can't be stored inside a
  file it contains. Un-routing is **supersede + recompile, not `git
  revert`**: managed-section compilers regenerate whole sections, so a later
  routing rewrites earlier lines and reverting commit N after N+1 is unsound
  (blind re-review 2026-07-12); per-lesson commits are kept for attribution.
  The record is `git mv`'d to `resolved/`, and the session ends by reporting
  what remains **and pushing its commits** — `claude-skills-sync`'s
  clean-tree branch never pushes, so without a self-push, routed canon would
  sit unpublished until some unrelated change dirtied the tree.
  For its duration the command sets an **autosync pause sentinel** in
  `~/.cache` so mid-review working-tree states are never committed out from
  under it with a generic sync message. Two honesty notes: the watcher does
  **not** honor any sentinel today — teaching `bin/claude-skills-watch`/
  `claude-skills-sync` to check it is a named M1 deliverable in the *main*
  repo (on master), not an existing capability — and the sentinel carries a
  **TTL (~2 h) that the live review heartbeats** (re-touches periodically),
  so expiry means a *dead* review, not a long one: a crashed review degrades
  to normal autosync, while a legitimate two-hour Discuss tangent keeps its
  pause. The sentinel is per-machine by nature (`~/.cache`): reviews on two
  machines at once are an operating-discipline no (see §5). Discuss
  drops into normal conversation with the analysis context loaded, then
  returns to the queue.
- **`self-learn` CLI** (portable core): `list`, `status`, `teach`, `import`,
  `graduate <id>`, `--selftest`. `graduate` is the owning verb for the
  hand-weave transition (`02-schema.md` §4): it marks a routed lesson
  `superseded_by: canon` so the compiler drops its managed-section line —
  the same move ha-note exposes as `--promoted`. The CLI is the dependable
  substrate; the slash command is the experience.
- **`--selftest`** (inherited from ha-note): proves capture path, worker
  spawn, and compiler dry-run still work — loud, not silent, when dead.

### 3.5 Compilers (the routing targets)

All compilers are **diff-first** (show, then apply), **idempotent**, and own
only their managed region:

| Target | Mechanism | Notes |
|---|---|---|
| SKILL.md | `<!-- self-learn:begin/end -->` managed section | behavioral rules + skill-scoped knowledge; loads natively at activation. Compiler keeps it tight; weaving learned text into the authored prose is a human editorial act, done whenever the user likes (that *is* gen-1's "Level C", demoted from milestone to habit) |
| CLAUDE.md (repo or `~/.claude/`) | same managed-section pattern | project/user conduct + knowledge. **`~/.claude/CLAUDE.md` is chezmoi-managed (E-17): the compiler must `chezmoi re-add` after writing *and* commit+push the dotfiles repo — `re-add` alone is same-machine-only, and the next `chezmoi apply` elsewhere clobbers the section** |
| `references/<file>` | plain append (ha-note-style) | bulk knowledge; progressive disclosure |
| new skill | delegates to plugin-dev scaffolding | when triage decides a lesson cluster wants to be a skill |
| hook | scaffolds script + prints the `settings.json` snippet | **never auto-registers** (repo doctrine: settings.json is manual) and **always explicit-diff-approved** (P9). For `kind: anti-pattern` lessons where advisory text is the weakest enforcement and a PreToolUse guard is the strongest |

Routing doctrine (the analyst's map, human overridable): behavior/anti-pattern
→ hook candidate or SKILL.md rule · behavior/surface-rule → SKILL.md rule ·
behavior/reasoning-pattern → SKILL.md or CLAUDE.md prose · knowledge, skill
scope → references or SKILL.md section · knowledge, project/user →
CLAUDE.md or docs. One standing bias: **prefer the narrowest surface that
still fires** — `~/.claude/CLAUDE.md` loads in every session of every
project, making user scope the most expensive destination in the system; a
lesson that can live with a skill or a repo should.

### 3.6 Notifications

Threshold-batched, never per-item: SessionStart context line
("📥 self-learn: 7 pending, oldest 9d — /self-learn:review") + `notify-send`
when crossing thresholds (default: ≥5 pending, or oldest >7 days) + optional
statusline count. Also a **staleness alarm**: "worker hasn't completed a run
in N days" — the silent-death guard for the analysis path. The alarm's owner
is the **SessionStart hook** that already computes the pending count:
comparing the worker's last-run marker in `~/.cache` is one stat call, and
it means no *additional* background process exists to rot (E-5). The hook
itself is registered manually in `settings.json` per repo doctrine — a
documented install step, not an assumed one.

## 4. The life of one learning (worked example)

1. Mid-session, HA config work goes wrong the familiar way. You type:
   `self-learn teach "when about to edit a .storage/*.json while HA is
   running, stop the container first — HA rewrites .storage on shutdown"
   --skill home-assistant`.
2. A record lands in `plugins/home-assistant/…/.self-learn/pending/`,
   `type: behavior`, `kind: anti-pattern`, source `teach`.
3. The worker (on the designated analysis host) writes the proposal sibling:
   *destination: hook candidate (PreToolUse guard on Edit/Write to
   `.storage/*` paths) + SKILL.md rule as fallback; draft diff for both.* It
   also notes the backlog import already holds a similar GOTCHAS entry →
   merges, 2 sightings.
4. Next session start: "📥 self-learn: 5 pending…". You run
   `/self-learn:review`. The card shows both options; you pick the hook,
   review the script diff and the settings.json snippet, apply. Commit lands;
   record moves to `resolved/` with the commit hash.
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
| Managed sections bloat canon | every routed token loads every activation | mechanical cap — 10 entries/~150 words — with graduation cards (`02-schema.md` §4) · triage can route to references instead · narrowest-surface bias in the doctrine |
| Concurrent writers (worker, autosync, sessions) | E-8; flock is machine-local | record-per-file · a fully append-only worker (analysis *and* merges are proposal files; no record is ever worker-written) · no per-session writes to tracked files |
| Two machines review or route at once | compile targets (managed sections) are shared lines; the ledger is conflict-free but canon isn't | single-machine-safe by design; cross-machine collisions degrade to autosync's standard safe halt. Operating discipline: one review host at a time, and review self-pushes so the next host starts current |
| Secret lands in a capture | autosync publishes tracked files within seconds, pre-review | capture-time secret scan in `teach` (refuse, or redact + flag) · minimal-quote policy |
| `chezmoi apply` clobbers the user-scope section | `~/.claude/CLAUDE.md` is chezmoi-managed (E-17) | compiler runs `chezmoi re-add` **and commits+pushes the dotfiles repo** — `re-add` alone fixes only this machine; other machines' `chezmoi apply` still serves the old committed state. A two-repo coupling, and one more reason for the narrowest-surface bias |
| Autosync races a review session | watcher debounce vs. Discuss pauses mid-apply | review sets a TTL'd pause sentinel in `~/.cache`; watcher support is a **named M1 change** to `bin/claude-skills-watch` (main repo) — no sentinel exists today |
| Review crashes, sentinel left behind | a stale pause = autosync silently off | heartbeated TTL (~2 h): live reviews re-touch the sentinel, so the watcher ignores only *dead* ones — a crash resumes syncing, a long review keeps its pause |
| Deferred items clutter the queue forever | defer with no semantics = E-3 in miniature | `deferred_until` hides them until due · `deferred_count` ≥ 2 makes the card suggest reject |

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
