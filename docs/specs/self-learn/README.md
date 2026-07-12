# self-learn — design corpus (gen 2)

*Single-authored 2026-07-12, replacing the gen-1 harness spec (archived at
`../archive/gen1-self-learning-harness/` — its README explains why). Status:
**design, no code**. Everything here was written together, as one system, with
the full evidence of three review rounds and the repo's own usage history baked
in from the start — not iterated into shape.*

## What self-learn is, in one sentence

A **capture, triage, and routing system for lessons learned while using Claude
Code**: lessons accumulate quietly into per-skill and per-project buckets; a
review surface presents them pre-analyzed; the user routes each one — with
agent help — into the surface where it becomes permanent (SKILL.md, CLAUDE.md,
reference docs, a new skill, or a hook). Nothing influences Claude until a
human routes it.

## Reading order

| Doc | What it holds |
|---|---|
| `00-vision.md` | The problem (restated correctly), the target UX, and the ten design principles with their evidence |
| `01-architecture.md` | The six components, the life of a learning, failure modes, and what is deliberately absent |
| `02-schema.md` | The learning record, storage layout, and mutation rules |
| `03-decisions.md` | The decision register: settled / open / v2-gated (with explicit activation triggers) |
| `04-roadmap.md` | Build milestones, acceptance fixture, success metrics |
| `05-evidence.md` | The empirical facts this design is built on, with sources |
| `06-horizon.md` | The team-scale future (~5–6 users, shared artifact repo): invariants, the six team problems, staged path |
| `07-review-ui.md` | The resident TUI (recorded destination surface): attend-at-convenience, embedded SDK adjudication pane, the don't-subvert contracts on v1/M2 |
| `research/` | External evidence memos (SOTA surveys etc.) — shareable with blind reviewers, unlike `reviews/` |

## Ground rules for changing this corpus

1. A **settled** decision (`03-decisions.md`) reopens automatically if a later
   decision changes its inputs — "settled" is not "shielded" (gen-1's
   sequential-lock-in failure).
2. Material design changes get a **blind** review before settling — reviewers
   receive the docs and a mandate, never the expected conclusion.
3. No code until the user ratifies the corpus; build happens in this worktree
   per the repo's worktree → test → merge convention.

## Revision log

- **2026-07-11 — refinement pass (draft, unratified).** Spec-bug fixes
  (evidence mutability contradiction, AskUserQuestion option limit, defer
  semantics, diff-as-preview ambiguity, `routed/`→`resolved/`),
  environment-verified gaps (chezmoi-managed `~/.claude/CLAUDE.md`, autosync
  pre-review publication + review-race, machine-local flock), and
  enhancements (in-session capture extraction, model-prompted offers O-6,
  backlog already-canon flagging, bounded review batches, per-lesson
  commits, managed-section overflow cap, ha-note unification O-7). New
  evidence: E-16, E-17. **S-8/S-12 reopened** (freeze-at-routing) pending
  blind review per ground rule 2. Findings→edits map:
  `reviews/2026-07-11-refinement-review.md` — for a *blind* re-review, give
  the reviewer the corpus without that memo.
- **2026-07-12 — blind adjudication + concurrency red-team (folded in).**
  Two blind reviewers (memo withheld). **S-8/S-12 SETTLED** —
  freeze-at-routing ADOPTED, with the secret-scan-on-every-write rider.
  Concurrency findings folded: review **self-pushes** (the sync's clean-tree
  branch never pushes); correction = **supersede + recompile**, not
  per-lesson `git revert` (unsound against regenerating sections);
  **merges-as-proposals** — the worker is now fully append-only and the
  designated-host/claim-marker machinery is deleted; sentinel **heartbeated**
  (TTL means dead, not long); `superseded_by: canon` formally defined with a
  `graduate` verb; routed-and-corrected metric excludes canon graduations;
  chezmoi user-scope writes must also commit+push the dotfiles repo (E-17
  extended). Register: S-2/S-5/S-6/S-7 re-amended, S-8/S-12 settled.
  Details: `reviews/2026-07-12-blind-adjudication.md` (also withheld from
  future blind reviewers).
- **2026-07-12 — SOTA survey folded + horizon set.** Five-stream external
  research (`research/2026-07-12-sota-survey.md`) found independent
  convergence on the corpus's load-bearing choices (curation gates, compiled
  canon over retrieval, files over infra, bounded edits, proposals-never-
  mutate) and no contradiction of any settled decision. New evidence
  E-18–E-21. Short-term adoptions folded: **rejected-proposal digest** for
  the M2 worker (SkillOpt's rejected-edit-buffer pattern), **trigger-first
  phrasing** as a compiler rule (`02` §4), **G-6** staleness revalidation
  gated (Copilot's citation-revalidation pattern), SkillOpt-Sleep named as
  G-1's evaluate-first reference. **Planning horizon reframed to team scale**
  (~5–6 users, shared artifact repo — user directive): new `06-horizon.md`
  (invariants, scope tiers, PR-based routing authority, provenance/trust,
  staged path). v1 scope and all gate triggers unchanged.
- **2026-07-12 — review-UI vision recorded (user-specified).** New
  `07-review-ui.md`: resident TUI as the destination adjudication surface —
  attend-at-convenience (ambient notifications carrying event + aggregate;
  neither popup treadmill nor invisible backlog), deep-link into the
  decision, embedded **SDK adjudication pane** (fresh session per item over
  a stable cached doctrine prefix; agent iterates, only the human's button
  routes). Consequent amendments: **S-2** (all resolution mechanics —
  `route`/`reject`/`defer` verbs, sentinel, self-push, `--note` — live in
  the CLI; slash command is a thin caller; `--json` on reads), **S-9**
  (per-worker-run ambient events with aggregate replace pure thresholds;
  "never per-item" refined to "never per-item-*demanding*"),
  **`resolution_note`** added to the schema (M1; feeds the M2 digest;
  amends the git-only-provenance lifecycle bullet), M2 notification payload
  carries record ids, **O-1/G-3 rewritten** (TUI is the recorded
  destination, gated on M2). **E-2 demoted to casual-solo floor** — the
  sizing environment is heavy daily work use (user directive; E-2 caveat,
  06-horizon §1).
