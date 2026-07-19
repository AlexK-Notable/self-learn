# Forward theme G — Process debt & horizon discipline

*Companion to `../14-forward-work-map.md` §2 (FW-26…FW-29). Dated
2026-07-18. Two halves: debt in the **build process itself** (the
machinery that produced eleven clean ship rounds is under-documented
and partly session-fragile), and **discipline about the horizon**
(what must NOT be built early, kept in one place so future enthusiasm
meets a written wall).*

## 1. FW-26 — The orchestration runbook (make the process survivable)

**The gap, plainly**: the two-gate discipline's *rules* are recorded
(review records, 10 §8's wave plan, the model split now in S-18), but
the **operational knowledge** that makes orchestrated rounds actually
work lives in the orchestrator's session memory and a handoff file
outside the repo: worktree lifecycle discipline (cut from the gated
master tip — builders behind the spec was a live failure; prune +
delete branches after merge; never `git add -A` from root with
worktrees present — the gitlink incident), parallel-author collision
protocol (pre-allocate register numbers and insertion points in
prompts; resolve merges theirs-then-ours by number order), reviewer
isolation mechanics (what blind reviewers may never see: `reviews/*`;
what they must receive: the spec, the diff, mutation-verification
mandates), sandbox trial invariants (SELF_LEARN_HOME + XDG redirects,
never the real ledger, H-3), and the small gotcha bank (eza-alias
breaking `$(ls)`, uv `.venv` copies pointing at the original tree,
notify-send bounded waits). If a different orchestrator — or this one
after memory loss — ran the next round, they would rediscover several
of these the expensive way.
**The work**: one repo doc (natural home: a new `15-orchestration-
runbook.md`, or an 08/10-appendix — spec author's call) capturing:
round lifecycle (spec → spec gate → build → code gate → merge →
trials → records → deploy), the agent-prompt skeletons that encode the
collision and isolation rules, the gotcha bank, and the model-split
mechanics (S-18 states the policy; the runbook states the practice).
**Test of done**: a competent orchestrator who has never seen this
project runs a small round from the runbook alone without violating a
standing rule — the same bar 08 set for the original build ("any
competent orchestrator… not only the one that authored the corpus").

## 2. FW-27 — The records index (cheap, batch with FW-26)

**The gap**: `reviews/` holds ~20 files, `research/` ~11, `fixtures/`
carries multi-section trial logs — all discoverable only by filename
convention and grep. Each new round makes "which review record pinned
that?" more expensive — archaeology, which this corpus exists to
prevent.
**The work**: one index page per directory (or one combined
`records-index.md`): date, subject, verdict/outcome, and what each
record *pinned* (the one-line "why you'd open this"). Generated
manually at round-close as part of the records step — a table row per
round is near-zero marginal cost once the index exists; the backfill
is one sitting.

## 3. FW-28 — Suite runtime budget (WATCH with a threshold)

**Trend**: CLI 970 + UI 722 tests and climbing every round; mutation
verification multiplies full-suite runs during gates (13 mutations in
the UX round alone = 13+ suite executions). Green-and-fast is a
discipline asset — the two-gate process is affordable *because*
verification is cheap; suite minutes compound directly into gate cost
and orchestration wall-clock.
**Threshold + response, pre-registered**: when a full combined run
exceeds ~3 minutes on this host, spend one maintenance slot on:
fixture-session reuse audit (per-test sandbox git inits are the likely
hot spot), parallelization (`pytest -n` — verify the suites'
sandbox-isolation assumptions hold under it), and a marked "gate
battery" subset for mutation kills (a mutation only needs the tests
that claim to guard it, plus the structural pins — the review records
already name them per mutation). Below the threshold: do nothing;
suite-tuning ahead of pain is procrastination with a green tint.

## 4. FW-29 — Horizon guard rails (the do-not-build list, consolidated)

The map's WATCH/DECIDE items create standing temptation to "just
build it while we're in there." The written wall, consolidated from
03/06/12 — each with its unlock condition, because a guard rail
without an unlock is dogma:

| Do not build | Until (the unlock) |
|---|---|
| PR-based routing, scope tiers, provenance/trust tiers | 06 stage 2: an actual team pilot (2–3 users, one shared repo) |
| Statistical layer, reputation, decay clocks (G-1) | Its trigger: second regular user / measured recurrence ≥2× / >50 active routed lessons — and evaluate SkillOpt-Sleep first, per the register |
| Vector/embedding dedup (G-5) | Observed lexical-clustering misses — observed, not presumed |
| Forensic transcript drain (G-4) | G-1 active AND volume worth mining |
| Miner autonomy ladder steps (12) | FW-2's measured precision window, then a user ruling per step |
| Ledger auto-sync mechanisms | FW-22's trigger AND the user ruling it (D3 stands until then) |
| Go port (O-8) | Python packaging demonstrably failing — not "seeming heavy" |
| Native-memory delivery surface (FW-24) | The surface exists AND passes the P1/P2 evaluation |
| Metrics dashboards / modeled scores | Never (counted-not-modeled is unconditioned) |

**The rail's own rationale, kept honest**: every one of these is
gated on *observed* need because the corpus's strongest empirical
finding (E-18…E-21 lineage) is that learning-system value concentrates
in the gate and the judgment, not the machinery — and because the
project's history already contains the counterexample that proves the
rule: the TUI plan, built on an unverified ground, voided post-gate
(README ground rule 4). Speculative building is how that happens
again.

## 5. Relationship to the self-learn loop itself (closing the circle)

This theme is the project applying its own doctrine to its own
process: FW-26 is routing the orchestrator's accumulated lessons into
a canon surface (the runbook) instead of session memory; FW-27 is the
references-append pattern for the project's own history; FW-29 is the
register's gate discipline turned on the roadmap. If the runbook's
lessons keep proving durable, the natural end state is capturing them
*through* self-learn into the product repo's own project scope — the
system maintaining the system. Noted as direction, not scheduled:
it becomes real the day the product repo is itself a registered host
with lessons flowing.
