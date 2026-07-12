# 2026-07-12 — State-of-the-art survey: self-improvement tooling for agents

*Five research streams (4× Sonnet 5, 1× Haiku 4.5 with spot-verification, plus
direct investigation of microsoft/SkillOpt at the user's pointer), run
2026-07-12 while the gen-2 corpus awaited ratification. Researchers were given
the design space, never our conclusions — convergence below is independent,
not echo. This is EXTERNAL EVIDENCE, not a review memo; it may be shown to
blind reviewers. Full reports in the session transcript
(f687d7ce-a89a-439a-abb5-b18d8e2f43c9).*

## 1. The field's shape, in one paragraph

Everything surveyed sorts into two regimes. **High-volume, machine-scorable**:
RL/optimizer systems (Agent Lightning, Trace, SkillOpt, GEPA, ACE) that need
scored rollouts and a held-out validation signal, and auto-extraction memory
platforms (Mem0, Zep, Letta, LangMem) that need fact volume no human could
review. **Low-volume, human-judged**: curated instruction files + a human gate
(Devin Knowledge, Cursor Memories, Claude Code CLAUDE.md/Skills, the whole
community-plugin ecosystem). Nothing surveyed bridges the two; the systems
that tried to automate the low-volume side (auto-memories) are the ones whose
own vendors tell users not to trust them for anything durable.

## 2. Convergences that independently validate settled gen-2 choices

- **Two-tier architecture is universal** (commercial sweep): every product
  separates a static human-curated instruction layer (CLAUDE.md / AGENTS.md /
  Rules) from a disposable auto-generated layer (memories) — and every
  vendor's docs steer users to the static layer for durable knowledge
  (Windsurf verbatim: "write it as a Rule... rather than relying on
  auto-generated Memories"). Matches our auto-memory-as-inbox / canon-as-
  files split (E-7, P2).
- **Automatic consolidation is the failure point, not storage** (academic):
  Zhang et al. 2026 (arXiv:2605.12978) — continuously LLM-consolidated
  memories degrade *below the no-memory baseline*; raw episodic retention
  matched or doubled forced consolidation; the summarization step itself is
  the lossy operation. Letta's own blog concedes consolidation errors get
  "baked into the learned context and amplified." Our append-only ledger +
  merges-as-*proposals* (human collapses) sits exactly on the safe side.
- **Curation gates are the difference between harm and help** (academic):
  Cui et al. 2026 (arXiv:2606.17591) — the *same* accumulated experience
  either degrades below zero-shot or dramatically improves, depending solely
  on whether a curation loop governs rule retention. OEP poisoning
  (arXiv:2605.18930): >50% attack success planting wrong lessons because
  agents "over-trust self-generated reflections." Misevolution (arXiv:
  2509.26354): safety decay from unsupervised self-evolution. P1 is
  load-bearing per the literature, not just per our taste.
- **Compiled rules beat memory retrieval for "stop repeating this
  correction"** (academic — closest paper to self-learn): **TRACE**
  (arXiv:2606.13174, Notre Dame/IBM, June 2026) compiles a user's in-session
  corrections into structured runtime-enforceable rules; residual preference
  violations 2.0–60.5% vs a Mem0 retrieval baseline leaving **57.5%** still
  violated. Direct external support for P2 (deliver via canon/hooks, not
  injection/retrieval) — and TRACE is nearly alone in framing our exact
  problem (individual + coding agent + corrections that don't persist).
- **Files beat vector infrastructure at personal scale** (memory-infra):
  Letta's own benchmark — grep-over-files 74.0% LoCoMo vs Mem0's best 68.5%;
  full-context ~73%; Salesforce ConvoMem: "first 150 conversations don't
  need RAG"; Claude Code, Manus, OpenClaw all converged on markdown files.
  Every documented file-approach failure is a *scale* failure (concurrency,
  paraphrase over large corpora) that ~1 lesson/month never reaches.
- **Bounded incremental edits, never wholesale rewrites** (three independent
  sources): ACE's "context collapse" finding (arXiv:2510.04618), SkillOpt's
  edit budget as "textual learning rate," and Codex/Copilot practice. Our
  marker-bounded managed sections + overflow cap are the same conclusion.
- **Self-authored procedural memory isn't ready; human-reviewed is what
  ships** (memory-infra): Mem0's own 2026 state-of-field calls procedural
  tooling "still early-stage"; what shipped (Claude Skills, Devin Playbooks)
  is human-authored/reviewed by design; Anthropic explicitly defers agent
  skill self-authoring to future work. Also "Skills in the Wild"
  (arXiv:2604.04323): retrieval among many skills is weak and *composing*
  skills degrades performance — supports lean canon + overflow cap.
- **Anthropic's own "Dreams" API** (Managed Agents research preview) is
  architecturally our worker: async consolidation reads memory + transcripts
  and writes a *separate output store*, input never modified, explicitly so
  a human can review and discard. Independent arrival at
  proposals-never-mutate-records.
- **Gate-the-write is half the industry** (commercial): Devin Knowledge
  (suggest → edit/dismiss → save), Cursor Memories (background model
  proposes, user approves), Amp (asks before appending to AGENTS.md).
  The other half gates the read (Copilot: citation revalidation + 28-day
  expiry; Codex: post-hoc inspection only).

## 3. The Microsoft pointer: SkillOpt (user-supplied lead)

microsoft/SkillOpt (MIT, ~12.3k stars, v0.2.0 2026-07-02; paper
arXiv:2605.23904) — "the skill document as the trainable state of a frozen
agent." Optimizer model turns scored rollouts into bounded add/delete/replace
edits on one skill markdown file; edits accepted only on strict held-out
validation improvement; stability via edit budget ("textual learning rate"),
**rejected-edit buffer** (rejections become negative feedback), epoch-wise
slow/meta updates. Claude Code is a first-class harness (+19.1 avg on
GPT-5.5; +58.3 SpreadsheetBench). **SkillOpt-Sleep** (v0.2.0): nightly
offline engine that harvests real session transcripts, mines recurring
tasks, replays them, consolidates into memory/skills behind a train/val/test
replay gate; backends include Claude Code, Codex, Copilot, Devin.

**Verdict:** regime mismatch for v1 — its machine gate requires
machine-scorable improvement (replayable, scorable tasks); our lessons are
prose behavioral rules at ~1/month with zero measured recurrence (E-2).
But it is the strongest known **G-1 reference implementation**: if the
statistical-layer trigger ever fires, evaluate SkillOpt-Sleep before
building anything bespoke.

## 4. Also assessed from the Microsoft stable

- **Agent Lightning** (github.com/microsoft/agent-lightning, ~17.4k stars):
  RL on execution traces → weight updates; thousands of rollouts, GPU infra,
  no per-lesson human review. Opposite regime; not applicable.
- **Trace** (github.com/microsoft/Trace, NeurIPS 2024): generative
  optimization of prompts/code from feedback, data-efficient (single-digit
  iterations) but requires instrumenting the agent as an optimization graph
  with machine-computable feedback. Not applicable.
- **Foundry Agent Optimizer + procedural memory** (Build 2026, proprietary
  Azure preview): consumes production traces, generates ranked candidate
  improvements to prompts/skills, surfaces winner **as a diff with lineage,
  audit trail, human approval before promotion**. Convergent evidence for
  the review-surface shape; nothing to adopt (closed, cloud).

## 5. Community practice (Haiku sweep; three load-bearing finds spot-verified)

20+ Claude Code lesson-capture projects exist; none contradict the corpus,
several are close cousins:
- **claude-reflect** (BayramAnnakov, 1.2k stars, v2.6.0 Feb 2026 —
  verified): hooks detect corrections in-session (regex + semantic
  validation, confidence scores), `/reflect` presents a review queue, human
  approves before sync to CLAUDE.md/skills. Closest community analogue to
  teach-capture + review cards.
- **claude-diary** (rlancemartin, 379 stars — verified): /diary captures,
  /reflect promotes recurring patterns (2+ mentions) into CLAUDE.md.
- **learning-loop-skill** (melodykoh, 14 stars, v4.2 Jul 2026 — verified):
  scan/wrap-up phases, quality gates, routes by type to CLAUDE.md / docs /
  skills / MEMORY.md with user verification — a routing table like ours.
- Pattern across the ecosystem (unverified breadth, verified core): capture
  triggers are hooks (Stop/PreCompact/SessionStart); storage is markdown;
  human gates before CLAUDE.md edits are the norm; Anthropic ships no
  official lesson-capture skill — the space is entirely community-built.

## 6. What the SOTA has that we lack (candidate adoptions — user to approve)

1. **Rejected-proposal negative feedback** (from SkillOpt's rejected-edit
   buffer): feed past rejections (already in git provenance) to the M2
   pre-analysis worker so it stops re-proposing rejected lesson classes.
   One-line M2 spec addition; directly mitigates E-3 queue-death (a queue
   re-surfacing rejected material burns goodwill fastest). **Recommend
   adopt at M2.**
2. **Trigger phrasing on routed items** (from Devin Knowledge): each
   knowledge item carries a natural-language "when this applies" condition.
   For SKILL.md-routed lessons the skill's activation is the trigger; for
   CLAUDE.md-routed lessons, compiling the rule as "when X, do Y" (not a
   bare imperative) is free discipline. **Recommend: compiler style rule,
   M1, zero cost.**
3. **Citation revalidation at compile/selftest time** (from Copilot Memory):
   Copilot validates each stored fact's code citation against the current
   branch before reuse; stale facts never fire. Analogue: `--selftest`
   could check that a routed lesson's evidence.origin target (file, skill,
   device) still exists, flagging stale canon. **Recommend: bank as v2
   candidate (G-4-adjacent); revisit after M1 experience.**
4. **Per-rule helpful/harmful counters** (from ACE): itemized playbook
   bookkeeping. This is the statistical loop; volume-gated. **Already
   correctly gated at G-1 — no change.**

## 7. The honest blind spot

No paper, product, or project evaluates the ~1-lesson/month single-user
regime — the literature's smallest "sample-efficient" result is ~152
training examples (Memory-R1). The academic reviewer's inference (the
documented failure modes — consolidation drift, poisoning, misevolution —
worsen with volume and repetition, so low volume is comparatively *safe*)
is reasonable but unmeasured. Consequence: the corpus's acceptance fixture
(three real failure modes, fresh-session provocations, behavior observed
directly) is not optional rigor — it is the only evidence about our regime
that will exist anywhere.

## 8. One tension worth naming

The two shipped approval-gated products (Devin, Cursor) fold approval into
the **moment of capture** (suggest → tap → saved), not a standing review
queue. Our E-3 evidence says standing queues die; the corpus already
answers this (teach --route immediate path, O-6 in-the-moment offers,
P3 queue-never-gates) — but the survey sharpens the prior: **the immediate
path should be treated as the primary UX and the review queue as overflow**,
not the reverse. Worth keeping in view when O-6 settles and when M1's
review-session ergonomics get built.

## Bench notes on evidence quality

Vendor memory-platform benchmark numbers (LoCoMo etc.) are untrustworthy —
documented answer-key corruption (6.4% of questions), judge accepting 62.8%
of intentionally wrong answers, two vendors publicly disputing 17–25-point
swings in each other's configs. Consistent with the corpus's counted-not-
modeled metrics stance. SkillOpt/TRACE/ACE numbers are paper-reported and
not yet independently reproduced; treat as directional.
