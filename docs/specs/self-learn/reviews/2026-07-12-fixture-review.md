# 2026-07-12 fixture review — the three acceptance candidates, independently assessed

*One independent reviewer (Fable, user-requested), given the corpus WITHOUT
`reviews/*` and without the orchestrator's own assessment, with a mandate to
derive the rubric from `04-roadmap.md` §0 and to ground-truth every claim
against the live repos (`~/repos/claude-skills` plugins, both CLAUDE.md
files, hook registrations). All dispositions below are folded into §0
(rewritten 2026-07-12). Like its siblings, this memo is withheld from
future blind reviewers.*

## Verdicts

- **A (`.storage`-while-running)** — QUALIFIED-WITH-CONDITIONS, **as the
  hook fixture only**. Ground truth: the rule already sits in the
  activation-loaded SKILL.md body **twice** (safe-mutation decision tree +
  hard-rules list) and the skill description names `.storage` — so the
  behavioral A/B has no delta arm; §0's original observable ("stops the
  container first without being told") described behavior the repo already
  produces. Reframed claim: **deterministic enforcement of an
  already-probabilistically-followed rule** (unguarded call passes before
  routing; compiled guard denies after). Side effect stated as a feature:
  A's record duplicates canon, exercising the already-canon flagging.
- **B (anchored-edit verification)** — QUALIFIED-WITH-CONDITIONS; the
  strongest candidate. Ground truth: no such rule on any always-loaded
  surface (genuinely empty destination), but the built-in Edit tool already
  enforces the rule's core for its own path — the real failure class is
  **silent scripted substitutions** (`sed -i` etc., exit 0 on zero
  matches). Sharpened lesson wording + canned-scratch-repo provocation
  (deliberate `timeout = 30` / `timeout=30` divergence) + written
  predicate + the post-routing `chezmoi apply` persistence check (the only
  fixture that can prove the E-17 coupling) — all folded.
- **C (hypr-doctor placeholder)** — REPLACE. A loose fixture is a
  non-fixture (it would be back-filled to pass). hypr-doctor's canon is
  nearly complete and its trial environment is contaminated by design (the
  drift SessionStart hook varies day to day). Pinned replacement, from the
  references-only pool: **the `data.host`-reload GOTCHAS entry**
  (references-only, absent from the loaded body — promotion is exactly the
  claimed mechanism), trialed in plan-elicitation mode; backup: the
  registry-write-batching entry.

## Findings beyond the candidates (all folded into §0)

1. **The sourcing rule was self-defeating**: "pick from the existing
   canon" selects for lessons whose baseline already passes, because the
   user hand-folds lessons into canon effectively (the fact 00-vision
   opens with). §0 now sources from the corpus excluding any
   loaded-during-trial surface, with a grep absence proof.
2. **Baselines must be demonstrated, not assumed**: ≥3 pre-routing
   provocations, ≥2 failures, or the candidate doesn't qualify (B, C);
   one mechanical unguarded-pass trial for A.
3. **No pass bar existed** for "≥3 provocations" — now 3/3 for B/C, with
   every failure attributed before any lesser result is discussed.
4. **Written binary predicates** fixed before routing; scoring is
   transcript inspection, never judgment.
5. **Attribution protocol** per trial: `attributionSkill`, SessionStart
   hook output, cwd (outside this repo) — a failed trial names its broken
   link (capture / compilation / loading-activation / compliance).
6. **Timing conflict resolved**: §0 claimed the hook fixture checkable
   "after M1+M2," but the hook compiler is M3 scope and M3's exit
   criterion essentially *is* fixture A. Acceptance is now staged: B/C at
   the M1+M2 checkpoint, A at M3 exit.
7. **Plan-elicitation trials sanctioned** for fixtures whose real
   execution has physical blast radius (live HA): provoke, require the
   plan stated before any action, score the plan.

## Process note

The reviewer was leading in mandate (assess these three) but blind to the
orchestrator's prior assessment; it independently reproduced the
orchestrator's convergent points (baseline gate, C-as-placeholder, surface
coverage as a constraint) and additionally overturned A's framing via
ground truth the orchestrator had only suspected, and caught the §0
sourcing-rule class error and the M3 timing conflict outright. Independent
verification over trusting the advocate: 6-for-6.
