# self-learn — design corpus (gen 2)

*Single-authored 2026-07-12, replacing the gen-1 harness spec (archived at
`../archive/gen1-self-learning-harness/` — its README explains why). Status:
**RATIFIED 2026-07-12** · **M1 SHIPPED 2026-07-13** (v1.0 core loop live —
CLI + slash commands deployed, backlog drained; see revision log) ·
**11-telemetry PROPOSED 2026-07-14** (v2 after the four-agent audit;
awaiting user ratification). Everything here was written together, as one system, with
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
| `07-review-ui.md` | The review-surface vision (recorded 2026-07-12 as a resident TUI; platform since re-decided — see 09): attend-at-convenience, embedded agent adjudication pane, the don't-subvert contracts on v1/M2 |
| `08-build-plan.md` | **Execution authority for the build**: pinned interface contracts, the Phase-0 fixture runbook, the M1 task DAG, judgment-call routing, eventuality playbooks — written so any orchestrator can run the build |
| `09-surface-spec.md` | **Design authority for the G-3 adjudication surface** (web revision, 2026-07-12): interaction model, surfaces/routes, files-as-truth data flow, security middleware, the adjudication pane (Agent SDK engine default / CLI stream-json alternative, empirically probed), degradation table, stack selection |
| `10-surface-build-plan.md` | **Execution authority for the G-3 build** (gated on G-3's trigger): surface-local pins + verify-at-build ledger, acceptance fixtures incl. live trials, task DAG U1–U11, judgment routing, playbooks — 09 wins on conflict; shared pins stay owned by 08 |
| `11-telemetry-and-lifecycle.md` | **PROPOSED (2026-07-14)** — the life of a lesson after routing: follow-ups, recurrence tracking (suspect→confirm), certainty-as-measured-events, the three-plane data model (record frontmatter / actor-scoped telemetry JSONL / disposable index+report), and the standing multi-machine posture principles |
| `research/` | External evidence memos (SOTA surveys etc.) — shareable with blind reviewers, unlike `reviews/` |
| `fixtures/` | `gen-fixture-b` + `trials.md` (Phase 0 rounds 1–3: six candidates disqualified, B3 qualified + proven 3/3 post-routing — the system's primary behavioral evidence); `ui-trials.md` lands with the G-3 build |

## Ground rules for changing this corpus

1. A **settled** decision (`03-decisions.md`) reopens automatically if a later
   decision changes its inputs — "settled" is not "shielded" (gen-1's
   sequential-lock-in failure).
2. Material design changes get a **blind** review before settling — reviewers
   receive the docs and a mandate, never the expected conclusion.
3. No code until the user ratifies the corpus; build happens in this worktree
   per the repo's worktree → test → merge convention.
4. *(Added 2026-07-12, after the SDK-auth false-fact failure — znote
   `zQgIhHiqhJFes7RRzU4bF`.)* **Sourced ≠ true, and true ≠ right-for-us.**
   A decision-relevant claim that is locally testable gets an empirical
   test before it may ground a decision — quoting live docs is not
   verification. And every material-decision review includes a
   **framing lens**: what option or assumption was never priced; does
   the stated frame fit the actual circumstance (this user, this
   workflow, this maintenance reality). Problem-space map before option
   comparison; the user's values questions routed early and binding,
   never as post-hoc veto footnotes.

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
- **2026-07-12 — RATIFIED.** Final calls locked (user-delegated): **S-14**
  (O-2 — auto-memory importer in v1.0), **S-15** (O-6 — quality-gated teach
  offers in v1.0), **O-1 settled** (TUI after M2; G-3 owns the gate).
  Register: **15 settled · 1 open (O-3, deliberately empirical — M3
  revisits with supply data) · 1 parked (O-7) · 6 v2-gated.** Ground rule 3
  is satisfied: M1 may begin (test-first, in this worktree; first actions
  are the §0 baseline-qualification trials for fixtures B and C, which
  need no code).
- **2026-07-12 — acceptance fixtures hardened (independent review, folded).**
  §0 rewritten per `reviews/2026-07-12-fixture-review.md`: the sourcing
  rule was self-defeating (existing-canon lessons already pass at
  baseline); **A reframed as the hook fixture** (deterministic enforcement
  claim — the `.storage` rule already lives in the loaded SKILL.md body,
  so the behavioral A/B had no delta arm), evaluated at **M3 exit**;
  **B sharpened to the silent-substitution rule** (Edit tool self-verifies;
  the failure class is `sed -i`-style zero-match no-ops) with the
  chezmoi-apply persistence check; **C pinned to the `data.host`-reload
  references-only lesson** via plan-elicitation trials. Qualification gate
  added (absence proof · demonstrated baseline ≥2/3 failures · written
  binary predicate), trial protocol (outside-repo cwd, attribution set,
  3/3 pass bar), one-fixture-per-surface stated as a constraint.
- **2026-07-12 — implementability review folded; build plan added.** Two
  independent post-ratification passes (orchestrator read + one blind-to-
  each-other Fable reviewer with ground-truthing against the live repos;
  memo: `reviews/2026-07-12-implementability-review.md`, withheld from
  blind reviewers) hunted gaps that would mislead doc-only implementation
  sub-agents. Six blockers closed with dated edits: **packaging pinned**
  (plugin layout, `SELF_LEARN_HOME`, command namespace — 04-M1), **the
  sentinel's cross-repo contract pinned** (path/mtime-TTL/check-in-sync —
  02 §3), **marker bootstrap rule** (02 §4), **`route` reads proposal
  siblings — M1 inline analysis writes them** (01 §3.4, 04-M1),
  **already-canon flag criterion** (01 §3.2), and the **S-14/M3
  contradiction resolved** — v1.0 = M1+M2, v1.1 = M3+; the auto-memory
  importer moves to M1 (03 note, 04). Risk fixes folded: resolution-verb
  commit formats + per-verb push (02 §2), `superseded_by` merge-loser
  boundary (02 §2), `evidence.origin` key stability (02 §2), proposal
  cleanup at resolution (02 §3), `--route` no-prompt semantics + sentinel
  hold/release scoping (01), chezmoi drift guard, offer-line placement +
  wording, home-net residual (04-M1/08). E-16 re-verified against the
  live tool schema. New: **`08-build-plan.md`** — the durable,
  orchestrator-agnostic execution plan (pins table, fixture runbook, task
  DAG T1–T12, judgment routing, playbooks, acceptance procedure).
- **2026-07-12 — phased implementability gates: M1/M2/M3 all PASS (full
  plan, TUI excluded).** User-directed cycle — per-phase independent
  review → remediation → independent gate check — run to the terminal
  condition: an independent reviewer's verdict that a mid-tier agent
  could implement the full plan from the documentation alone. M1 gated
  after the command-deploy blocker (F1) was pinned; M2's execution plan
  (08 §7) was authored, reviewed (5 gates: merge-proposal schema,
  collapse verb, allowedTools, content-hash staleness, coalesce
  mechanics), remediated, and passed — including a reviewer-caught
  blocker *introduced by* a remediation (M2-21: models can't hash;
  the CLI stamps `record_sha`); M3's execution plan (08 §8) likewise
  (5 gates: snippet template, verbatim-apply exception, new-skill
  compiler contradiction — S-6/01 amended to CLI-owned scaffold — hook
  rollback, live fixture-A harness). Process record:
  `reviews/2026-07-12-phased-gate-process.md` (withheld from blind
  reviewers). 08-build-plan is now the gated execution authority for
  M1→M3; build may start at 08 §2.
- **2026-07-12 — G-3 TUI: empirical grounding + design spec gated
  (phase 1 of 3).** Three research memos landed (`research/`): live
  Agent SDK verification (API-key-only auth, 5-min cache TTL, no
  fallback model), live-host + live-CLI grounding (Ghostty/swaync;
  `claude` 2.1.207 verifies every pane-critical flag), framework trade
  study (Textual over Ink, "not genuinely close on fit"; bus-factor-1
  caveat recorded with switch conditions). New **`09-tui-spec.md`** —
  design authority for the G-3 TUI, refining 07 with two evidence-driven
  dated departures (PaneEngine abstraction, CLI-subprocess default over
  the SDK; caching demoted to opportunistic) and a §10 amendment set for
  02/03/07/08. Phase-1 gate: independent review FAIL (4 gates — bulk
  collapse armed reject where the corpus pins graduation; already-canon
  flag had no structured field; validate-verb delete semantics;
  verb/agent write race) → remediated → **gate re-check PASS** (two
  wording residuals folded). Phases 2–3 (corpus reconciliation;
  execution plan `10-tui-build-plan.md`) follow. Build stays gated on
  G-3's trigger (M2 shipped). **Phase-2 gate PASS (same day):** the nine
  09 §10 amendments landed as dated edits (01/02/03/07/08); the
  independent cross-document sweep (nine contract families, file:line
  traced) caught one real contradiction — the S-8 every-write
  secret-scan invariant had no mechanism on agent-mediated edits that
  bypass CLI verbs (pane + review Discuss-edit) — closed by extending
  `proposal validate <id>` into the scan enforcement point (exit codes
  0/1/2 pinned; resolution verbs scan the full record file as the
  no-bypass backstop). **Phase-3 gate PASS + TERMINAL VERDICT (same
  day):** new **`10-tui-build-plan.md`** — execution authority for the
  G-3 build (TUI-local pins + verify-at-build ledger, fixtures
  T-A..T-E with live trials, task DAG U1–U11, judgment routing,
  playbooks). First review failed it on a symlink-breaking wrapper pin
  and an untested cluster-collapse flow (+8 minors); remediated;
  re-check clean. Terminal conditions, from the third independent
  reviewer: coherence PASS (nine contract families traced
  cross-document), implementability PASS ("Opus 4.8 / Sonnet 5-tier
  agents can execute U1–U11, TUI and adjudication pane included, from
  the documentation alone"), design quality PASS. Build start stays
  gated on G-3's trigger. Process record:
  `reviews/2026-07-12-tui-phased-gates.md` (withheld from blind
  reviewers).
- **2026-07-12 — ratification calls, first batch (user).** **O-5 settled as
  S-13**: auto-memory pruning is a post-decision, post-processing sweep —
  never in-flight, never inline with adjudication. **O-6 amended**: the
  offer gate is quality, not count — gen-1's ≤2-interruptions budget
  superseded as artificial; serious corrections are never rationed. **O-7
  parked**: ha-note stays independent until the library matures — focus is
  the standalone tool, not claude-skills internals.
- **2026-07-12 — G-3 re-derived post-correction (platform → web, engine →
  SDK).** The TUI plan's terminal verdict was voided the same day it
  passed (POST-GATE CORRECTION in the phase memo; ground rule 4 added).
  This cycle repaired the failure modes per that rule: a **holistic
  problem-space map** authored first
  (`research/2026-07-12-adjudication-surface-problem-space.md` — the
  full option space priced: TUI / localhost web / hybrids / do-less
  baseline, on fit-for-us criteria); the user's values routed **early
  and binding** via one AskUserQuestion round (§6: platform = localhost
  web app; residency = any dedicated window; pane engine = Agent SDK,
  restoring the original directive; standing weighting = DX & agent
  leverage); decision-relevant SDK claims **empirically probed before
  pins froze** (`research/2026-07-12-sdk-pane-probes.md` — streaming
  chunk-level ~5 Hz; `can_use_tool` exact-file gating verified, with
  three pinned footguns: streaming-mode requirement, `allowed_tools`
  shadowing, `setting_sources` unset ≠ none). **09/10 rewritten and
  renamed** (`09-surface-spec.md`, `10-surface-build-plan.md`):
  FastAPI/Jinja/vendored-htmx surface, systemd --user service,
  security middleware in scope, SDK pane engine with the charter as a
  `can_use_tool` callback; every TUI-era substrate pin (P1-x/P2-x/P3-x
  closures) carried forward explicitly; socket/launcher subsystems
  deleted, not ported. Dated amendments: 07 (platform + engine
  restoration), 08 (terminology note + launcher rename), 02 §3 (token
  replaces socket), 03 (G-3 row). Textual TUI + cli engine = recorded
  alternatives (view-layer swap only). Build stays gated on G-3's
  trigger. Review phases of this cycle: recorded below as they gate.
- **2026-07-13 — G-3 re-derivation cycle COMPLETE: terminal verdict PASS.**
  Phase A (09 design, fresh reviewer, framing lens + empirical mandate):
  FAIL — render-path XSS un-priced (W-1, caught as a *map mispricing* by
  the framing lens; sanitization + CSP now v1 pins), a still-live
  falsified "SDK has no fallback" claim killed by live introspection
  (W-2), pane read scope contradictory (W-3, re-pinned two-tier and
  empirically confirmed) — remediated, re-check PASS. Phase B (10 to the
  08 standard + traced 00–10 sweep, third reviewer — no authorship, no
  remediation): **zero gates; T1 coherence PASS (twelve contract
  families traced file:line, all AGREE); T2 implementability PASS
  (Opus 4.8/Sonnet 5-tier agents from the docs alone); T3
  fit-for-circumstance PASS (judged against the map's C1–C9 and the
  user's binding answers)**. Nine minors folded post-verdict; fold
  verified by the terminal reviewer, verdict affirmed standing; three
  wording residuals folded per the reviewer's own dispositions.
  Never-self-certify tally: 7-of-8 remediation batches minted findings
  only independent re-check caught. Process record:
  `reviews/2026-07-12-surface-rederivation-gates.md` (withheld from
  blind reviewers). Build stays gated on G-3's trigger.
- **2026-07-13 — M1 BUILT AND MERGED (v1.0 core loop live).** All twelve
  08 §3 tasks executed test-first in the worktree by per-task
  implementation agents (376 tests green; per-task commits T1…T11 +
  T12's sentinel check live on master since f198e49); merged to master
  (523fbf5), deployed via install.sh — `~/bin/self-learn`, the skill,
  and colon-namespaced `/self-learn:teach` + `/self-learn:review`
  verified live. S-15 offer line applied through the guarded chezmoi
  flow (which caught and reconciled real pre-existing drift — E-17
  vindicated). Build findings recorded in 08's appendix, including:
  **Phase 0 disqualified both fixtures** (baselines passed 3/3 on
  claude-fable-5 — general-good-practice lessons are baseline-native
  on a frontier model) → user-directed replacement probes for
  environment-specific candidates under a hardened qualification gate
  (absence proof must cover the predicate behavior; the gate also
  killed the named C backup pre-trial); `proposal validate` pulled
  forward T13→T11. Remaining M1 exit items: the two [protocol] runs
  (exit a: one-motion teach --route; exit b: the GOTCHAS backlog-import
  review session) and fixture ratification + post-routing trials.
- **2026-07-14 — M1 [protocol] runs done; decision-support contract
  landed.** Exit (a): one-motion `teach --route` on home-assistant
  (lrn-e2e4026b → LEARNINGS.md, analyst-chosen destination, ~7 s).
  Exit (b): the real backlog-import review session (32 records
  imported; first batch of 10 resolved — 7 graduated against curated
  GOTCHAS.md, 3 routed to reference; sentinel/verbs/push all clean).
  **E-3 honeymoon verdict: throughput PASS, comprehension FAIL** — the
  user could not defend the approvals from the cards shown, and ruled
  the REPL "definitively not the right venue" (logged as G-3 trigger
  evidence; build stays gated on M2). Same-day remedy, the
  **decision-support contract**: 02 §1 `card:` map; routing-doctrine §8
  (story first, concrete behavioral before/after, steelman-the-no);
  `card-sections.yaml` — a section registry holding the set, order,
  labels, required-ness, and per-section generation prompts, so
  changing what decision-makers see is a one-file edit that no surface
  or validator change can break (extensibility per the user's explicit
  direction); validator shape-check (e702afb, 377 tests green);
  /self-learn:review re-carded sections-first; 09 §2.3 amended to
  render cards data-driven. Fixture probes: B1 (hyprctl focus-trap)
  DNQ'd — baseline 3/3 queried `hyprctl clients -j` unprompted; B2/B3
  remain open candidates awaiting user direction.
- **2026-07-14 (overnight) — backlog fully drained; fixture B proven
  end-to-end.** Under explicit user authorization ("do as much as you
  can... even the stuff needing my validation"), the remaining 22 HA
  records were analyzed under the new card contract and the safe subset
  resolved: 11 graduated (curated GOTCHAS.md covers them; canon even
  corrects one record's data=writeback claim), 9 routed to
  LEARNINGS.md, 1 deferred (unverified hypothesis). Two records held
  for the user with full cards: pyscript log.info (tensions with
  canon's marker advice) and chezmoi `chezmoi cd` (skill-md-now vs
  M3-hook). Fixture probes: **B2 dead at gate 0** (all naive pytest
  paths fail loudly — no honest predicate); **B3 QUALIFIED 3/3
  baseline FAIL** (notify-send -A under swaync blocks forever
  unbounded; predicate pre-registered). B3 adopted PROVISIONALLY
  (ratification pending — supersede lrn-c9044f8c to veto): routed to
  user CLAUDE.md via the chezmoi compiler (E-17 persistence HOLDS),
  then **post-routing trials 3/3 PASS with attribution** in every
  artifact — baseline 3/3 FAIL → routed 3/3 PASS is the first complete
  behavioral delta the system has produced. B-half of the M1+M2
  checkpoint pre-armed; C-half has no candidate → boundary decision
  (04 §0): hunt a C-class environment-specific lesson or re-scope to
  the B-half. Compiler note recorded: managed-section entries cut at
  the first sentence — front-load the operative content. Queue: 2
  pending (both user-held). znote hub current through session 3.
- **2026-07-14 — 11-telemetry-and-lifecycle.md DRAFTED (PROPOSED).**
  User-directed design session: routed lessons are claims, not
  facts-in-perpetuity; the system must measure certainty instead of
  declaring it. New layer: follow-ups (done-but-upgradeable, no new
  lifecycle status), recurrence suspects→confirmation (the "not
  holding" card), capture-time context (incident cost, generality, env
  fingerprint, verified), the observation plane (actor-scoped
  append-only telemetry JSONL — offer ledger, card outcomes, fires
  from transcript mining), the disposable index + report, and five
  standing multi-machine posture principles (single-writer by
  construction; two planes one-way flow; regenerate-never-merge;
  causal order from git ancestry; same-machine concurrency as the
  common case). §8 claims no settled decision reopens — top-to-bottom
  consistency audit commissioned same day.
- **2026-07-14 — four-agent top-to-bottom audit; 11 revised to v2.**
  User-commissioned full-system check (corpus coherence · code-vs-spec ·
  deployed state/ledger · adversarial review of 11). Deployed state:
  HEALTHY (zero dangling symlinks, 36 records self-consistent, canon 1:1,
  both user-held cards user-resolved → queue 0 pending). Code: HIGH
  conformance — all safety pins to the letter; four fixes landed
  (usage-exit 64, keep-the-why compiler, heartbeat coverage, over-cap
  surfacing) + review.md's deferred-resurface filter bug. Corpus: stale
  pre-build language swept (README header, fixtures row, 04 §0/08 §2
  supersession banners, designated-host leftover, S-6/O-4/O-1/S-2
  bookkeeping). **11 v1's headline guarantees were falsified** by two
  independent auditors (per-session tracked writes broke P6/E-8+S-7;
  worker emitters broke S-5; free-text payloads broke the scan claim;
  ancestry ordering unstable under rebase; unowned mutations) — **v2
  repairs all confirmed findings**: cache spool + verb-flush, CLI-only
  emission, enum decline reasons + scan-at-flush, ts-primary ordering,
  §2.5 verb table with pinned commits, honest §8 touch-point table
  (S-7 amendment + S-15 pin edit declared for ratification). 11 remains
  PROPOSED — ratifiable-with-edits per the adversarial verdict, edits
  now landed; user ratification still owed.
- **2026-07-15 — 11 RATIFIED (user-delegated) · M1 EXITED · checkpoint
  re-scoped.** The user declined to read 11 v2 and delegated: "review
  them yourself and try to answer the questions you would ask me." The
  questions and self-answered calls, each vetoable by dated register
  edit:
  **Q1 — telemetry lives in the repo (committed, synced): acceptable?**
  YES — the user's explicit directive was multi-machine-first hard
  facts; cache-only telemetry would forfeit cross-machine analytics;
  volume is KB/month of ids and enums; the spool/flush mechanism keeps
  every storage pin's letter.
  **Q2 — the pinned offer line in ~/.claude/CLAUDE.md grows a
  decline-logging clause: acceptable?** YES — the user asked for the
  denominator; the cost per decline lands on the model, not the user;
  applied only when the spool verb ships (S-15 row).
  **Q3 — decline reasons: enum or free text?** ENUM — the user's
  no-secrets-in-tracked-files posture is absolute and autosync
  publishes in seconds; a decline interesting enough to explain is a
  teach, not a payload.
  **Q4 — a worker pass reads local session transcripts for fire
  detection: acceptable?** YES with the existing pins — local-only,
  non-textual anchors, CLI-validated output; the user's own data on
  the user's own machine feeding the user's own analytics.
  **Q5 — four new verbs of CLI surface: worth the maintenance?** YES —
  the alternative is unowned mutations, the exact rot 02 §2's
  discipline exists to prevent; each verb is small, pinned, testable.
  **Q6 — accept one proven fixture (B3) and re-scope the C-half?** The
  user answered directly ("i genuinely can't think of anything else").
  Re-scoped, with the recorded rider that 11's recurrence/fire
  telemetry supersedes the C-slot's evidentiary role: continuous
  measurement of routed rules replaces one-shot proofs.
  Register edits landed: S-7 amended (telemetry storage class), S-15
  amended (offer-line clause, deferred to build time), S-16 added
  (the layer itself), 04 §0 boundary banner, 08 §6 completion.
  **With §6 fully satisfied, M1 is formally EXITED; M2 (worker,
  T13–T16 + 11's riders) is unblocked.**
