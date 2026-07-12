# 06 — Horizon: self-learn at team scale

*Direction, not spec. v1's scope statement (`01-architecture.md` §2) is
unchanged: this document exists so that v1's choices are made with the real
destination in view, and so the team-scale work, when it starts, begins from
written intent instead of archaeology. The reference picture is a shared
artifact repository — commands, skills, agents, hooks, MCP servers — used
daily by **~5–6 co-workers**. Deliberately conventions-agnostic: this doc
plans for the *scale*, not for any particular repo's layout or norms.*

## 1. Why this document exists

The gen-2 corpus was evidence-disciplined to the measured solo regime: ~1
durable behavioral lesson/month, zero recurrence, one human (E-2). Every
volume-dependent mechanism was cut or gated on that basis — correctly. But
the *planning horizon* is a team: the same capture → triage → route loop
serving a repo where a handful of engineers share one canon. At that scale,
several of the things we cut stop being fantasy and several things we take
for granted stop being safe. The SOTA survey (E-18–E-21,
`research/2026-07-12-sota-survey.md`) supplies shipped precedents for most
of it.

**What multiplies at N≈6 — and what doesn't.** Capture volume multiplies on
**two axes: headcount and per-user intensity**. E-2's floor is one person's
*casual* use; a work environment means multiple concurrent Claude Code
instances per person per day (user directive 2026-07-12), so the sizing
assumption is lessons per *day* across the team — headcount alone
understates it. Two qualitatively new signals appear that
no amount of solo usage produces: **independent corroboration** (two people
hitting the same gotcha without seeing each other's capture — the honest
version of `sightings`) and **measured recurrence** (a routed lesson failing
to stick for someone). E-2's zero-recurrence finding was a fact about n=1,
not a law: recurrence *couldn't* register with one user who personally
remembered every lesson. What does **not** multiply: the tolerance of any
individual for triage chores (E-3 applies per-person), and the attention
budget of the loaded canon (E-6 applies per-session, regardless of how many
people share the file).

## 2. What v1 already builds for this future — the invariants

These survive contact with team scale **unchanged**, and the team build must
not weaken them:

1. **The append-only ledger, record-per-file.** Designed for
   one-user-many-machines; the same construction is many-users-one-repo
   safe. Captures never collide (new files, random ids); proposals never
   collide; the only shared write surfaces are the compile targets — which
   is exactly where the human gate already sits.
2. **The fully append-only worker.** "Any machine may run the worker"
   generalizes for free to "any teammate's machine may run the worker."
   Proposals-not-mutations is also the pattern Anthropic's Dreams API
   converged on independently (E-20) — it is the correct multi-writer
   consolidation shape, not a small-scale workaround.
3. **The human gate before canon (P1).** The single strongest
   externally-validated choice in the corpus (E-18: curation gates decide
   whether accumulated experience helps or harms; E-19; E-20). At team
   scale it *generalizes* rather than relaxes: "the user approves" becomes
   "someone with routing authority approves" (§3.2).
4. **Record→commit linkage + one commit per routed lesson.** At n=1 this
   was attribution hygiene; at N=6 it is the audit trail — who taught it,
   who routed it, when, why (the same lineage story Foundry's Agent
   Optimizer treats as a headline feature).
5. **Native loading, lean canon, narrowest-surface bias (P2, the overflow
   cap).** More load-bearing at scale, not less: "Skills in the Wild"
   (E-21) found retrieval among many skills weak and skill *composition*
   performance-degrading. A six-person canon that bloats hurts six people
   per session.
6. **Counted-not-modeled metrics.** The benchmark-theatre findings (survey
   §Bench notes) are a standing warning: when team dashboards arrive,
   they count events; they do not model scores.

## 3. What changes — the six team-scale problems

### 3.1 The scope model grows a shared tier

v1's scopes (skill / project / user) implicitly equate "project" with "mine."
A shared repo splits that: **shared canon** (the repo's skills, CLAUDE.md,
hooks — everyone's blast radius) vs **personal scope** (each user's
`~/.claude/CLAUDE.md`, their machine, their preferences). Devin's shipped
tiers — per-user / organization / enterprise, plus repo-pinning — are the
precedent (E-21). Design consequences, banked now:

- A lesson's scope must name **who it binds**, not just where it lives.
  "Always use the staging inventory for scans" is org-canon; "I prefer
  terse commit messages" must never route there. Triage at team scale is
  routing *between tiers* as much as between files.
- Personal lessons need a home that isn't the shared repo — the v1 user
  scope already is one; it becomes each teammate's, and G-2's portability
  manifest is what makes "each teammate has a user scope" installable.

### 3.2 Routing becomes a role; the gate becomes review-with-authority

At n=1, capturer, reviewer, and canon-owner are one person. At N=6 they
split, and the gate needs an authority model:

- **Capture stays universal and frictionless** — anyone teaches, any time;
  P3/P4 per person.
- **Routing to shared canon acquires ownership** — per-scope routing
  authority (the CODEOWNERS shape: the person who owns a skill routes its
  lessons, or at minimum reviews the routing). The natural git-native form
  is the **pull request**: the review surface, instead of committing to the
  default branch, emits a branch + PR whose body is the card (record,
  rationale, diff) and whose merge *is* the route event. Nothing in the
  ledger schema changes — `routing.by` gains a name, the commit message
  format is already the linkage — but the compile step decouples from the
  approve step. This is the single largest mechanical change team scale
  demands, and it is a *narrowing* of v1 (add a PR hop), not a redesign.
- **Queue-death changes shape.** One inbox shared by six people is a
  tragedy-of-the-commons E-3; per-scope inboxes with named owners are six
  small queues with one accountable human each. The capture-time immediate
  path (`teach --route`, O-6 offers) matters *more* at team scale — the
  shipped approval-gated products all gate at the moment of capture, not
  via standing queues (E-20) — with the PR replacing the solo
  self-approval.

### 3.3 Trust and provenance become first-class

Solo, every record is self-authored and trust-by-invocation is fine. Shared:

- **Teacher identity enters evidence** (`evidence[].by`, or simply the git
  author of the capture commit — the ledger's git-native design means this
  is already recorded; it becomes *displayed* and *considered* at review).
- **Source-trust tiers return from the gen-1 archive.** Gen 1's safety
  analysis (source-trust, injection caps, quarantine) was shelved as v2
  source material; a shared canon consumed by six people's sessions is the
  deployment that justifies it. The 26.1%-of-community-skills-vulnerable
  finding (E-21) is the outside-world version of the same lesson: **shared
  executable canon (hooks especially) needs provenance gates**, and P9's
  human-approved-diff rule extends to "approved by someone other than the
  proposer" at team scale.
- **Secret scanning goes from discipline to hard requirement.** v1 already
  scans every record-body write because autosync publishes pre-review
  (E-8); a team remote with six writers and org secrets raises the stakes
  and adds the org's secret patterns to the scanner's corpus.

### 3.4 The statistical layer (G-1) becomes real — and mostly pre-built elsewhere

Cross-user corroboration finally gives `sightings` honest semantics, and
recurrence becomes measurable. The register's G-1 trigger ("a second
regular human user") fires on day one of a team pilot. The plan of record:

- **First, the cheap version we already own**: the worker's lazy clustering
  over a six-user pending set *is* corroboration detection; a merge card
  reading "3 teammates, same lesson, 9 days" is the entire pitch for the
  statistical layer at 10% of its cost.
- **Then, evaluate before building** (per the amended G-1 register entry):
  **microsoft/SkillOpt-Sleep** is the shipping reference for
  transcript-harvest → replay-validated skill edits with Claude Code as a
  backend. At team transcript volume, "mine recurring tasks and replay
  them" stops being vacuous. If its replay gate can score even a subset of
  our lessons (the deterministic, hook-shaped ones), it slots in as a
  *proposal generator* — its output enters the same human-gated review
  queue, never canon directly (P1 is not for sale; E-18's poisoning and
  misevolution results are precisely about skipping that gate).
- **Per-rule helpful/harmful bookkeeping** (ACE's pattern) becomes worth
  its cost once six people's sessions exercise the same rules — it is the
  input the graduation/supersession cards want.

### 3.5 Staleness at team velocity (G-6)

Six people change a shared repo faster than one person's memory of what's
routed. Copilot's citation-revalidation (E-21) is the model: every routed
lesson already carries evidence pointers; a compile-time/`--selftest` pass
that checks "does this lesson's referenced file/path/tool still exist"
turns silent canon rot into supersession cards. Gate-the-read as a
*complement* to gate-the-write — the register's G-6.

### 3.6 Concurrency: discipline becomes mechanism

v1's "one review host at a time" operating discipline doesn't survive six
users. The PR flow (§3.2) dissolves most of it — compile targets stop being
directly shared write surfaces, because routing lands via merge, and the
forge serializes merges. What remains is per-scope review claims (two
people triaging the same skill's inbox) — a small, solvable locking problem
(claim marker *in the PR/branch namespace*, not in records), explicitly
deferred until a pilot shows it matters.

## 4. Staged path

| Stage | What | Gate to advance |
|---|---|---|
| **0 — now** | v1 personal deployment per the corpus (M1–M3). The acceptance fixture is the only behavior-change evidence anywhere in this field at low volume (E-21) — run it honestly. | Fixture passes; a month of real supply-mix and queue-health numbers |
| **1 — second host** | G-2 portability: manifest + install story, so "a user scope per person" and "self-learn in another repo" are installable acts, not surgery. Gen-1's TOML/adapter spec is the raw material. | A second repo/user actually wanting it (the G-2 trigger, unchanged) |
| **2 — team pilot** | 2–3 users on one shared repo. PR-based routing (§3.2), scope tiers (§3.1), teacher provenance (§3.3), G-6 staleness pass. Worker runs anywhere; clustering surfaces cross-user corroboration. **Pilot metric: time-to-triage and queue health *per scope owner*** — the E-3 signature at team scale is one owner's queue at 100% >30d while the others are clean. | A quarter of counted evidence: corroborated lessons exist, routed canon demonstrably sticks for people who didn't teach it |
| **3 — volume features** | G-1 for real: evaluate SkillOpt-Sleep as proposal generator; per-rule bookkeeping; G-4 forensic drain if transcript volume warrants; G-5 if lexical clustering visibly misses merges. | Each gate's own trigger + its own blind review (P10) |

Each stage narrows the previous one (adds a hop, a tier, a check); none
rewrites the loop. That is the design intent of writing this down now: **the
team system is v1 plus authority, provenance, and volume — not a different
machine.**

## 5. What we will not do, even then

- **No autonomous writes to shared canon.** The gate generalizes (PR,
  routing authority); it never disappears. This is the field's clearest
  empirical line (E-18, E-19, E-20), and it gets *sharper* with more users,
  because a bad shared rule taxes six people silently.
- **No vector/retrieval infrastructure by default.** Files + git + grep won
  at personal scale on the vendors' own benchmarks (E-20); the shared-repo
  failure that would justify more (G-5's trigger) must be *observed*, not
  presumed.
- **No modeled metrics.** Counts of observable events, per scope and per
  owner. The memory-platform benchmark record (survey §Bench notes) shows
  what score-shaped numbers do to judgment.
- **No third-party lesson sources without provenance tiers.** A shared
  canon is a supply chain (E-21's 26.1%); imports carry origin and trust
  level or they don't come in.
