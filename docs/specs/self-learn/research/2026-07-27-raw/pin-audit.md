# Pin audit — `self-learn`

*A governance audit of the invariants, rulings, and hardcoded policy binding the
routing analyst, the miner, the worker, and the in-GUI iterator.*

Scope: `/home/komi/repos/self-learn` @ `e1a6445` (tree clean, unmodified), plus a
read-only forensic pass over the ledger at `/home/komi/.self-learn` (64 records,
32 routings, 26 proposals, 14 miner runs — full history, not just the working
tree) and the live canon surfaces on this host.

Date: 2026-07-26. Nothing was written, committed, or pushed. No `self-learn`
verb was run. `~/.self-learn` and `~/.cache/self-learn` untouched.

---

## 0. Executive summary

1. **The largest destination in the system delivers nothing.** 14 of 28 routed
   lessons (50%) went to `reference`, which appends to
   `references/LEARNINGS.md`. The compiler never writes a pointer to that file
   into any loaded surface, and none exists: in the live home-assistant plugin,
   `LEARNINGS.md` is named by **exactly one file — itself** (positive control:
   `GOTCHAS` is cross-referenced from 5, including SKILL.md:120). All 14 records
   are there, verified id by id. The doctrine calls this "progressive
   disclosure"; without an index entry it is deletion with a git commit.

2. **The `new-skill` naming pin cites an authority that does not contain it.**
   `08-build-plan.md:469` calls the name slot "the confirmed §4 human call."
   §4 (lines 264–283) is the table of judgment calls that stay with the human,
   and it has **no row about the new-skill name** — verified with a positive
   control. Worse, §4 is itself an agent-authored table of *who should decide*,
   not a record that the user *did*. The pin entered on 2026-07-16 as a side
   clause of a commit about hook schemas (`4be6d2b`), with no user quote and no
   review finding. It is self-authorizing, and it is now enforced in four places.

3. **The analyst's own system prompt contains two false premises, both of which
   inflate the cost of the destinations the queue is now stuck on.**
   `routing-doctrine.md:124` states `~/.claude/CLAUDE.md` "is
   **chezmoi-managed**… It only raises the cost of user scope — one more reason
   for the narrowest-surface bias." Chezmoi became optional in code on
   2026-07-21 (`97726df`) and was retired on this host on 2026-07-24.
   `routing-doctrine.md:129` states records, proposals and canon "are autosynced
   to a remote within seconds" — contradicted by S-17/D3, a **user-ratified**
   decision ("no autosync anywhere in the product or ledger"). Both are live in
   the deployed prompt today. The corpus's own P10 ("re-derive when premises
   change") was never applied to the file that steers every routing.

4. **The files that ARE the agents' system prompts have had almost no review, in
   a project whose entire quality discipline is two blind gates.** Across 26
   review records: `mining-rubric.md` **0**, `pane-charter.md` **0**,
   `card-sections.yaml` **0**, `routing-doctrine.md` **2** (positive control:
   `BLOCKER` appears in 12). `mining-rubric.md` and `pane-charter.md` have **one
   commit each, ever** — written on day 4 and day 5 and never revised. The gates
   were pointed at code and specs; they were never pointed at the prompts.

5. **The tests cannot detect a bad pin, and the corpus already proved this.**
   The naming pin has two tests asserting the refusal (`test_verbs.py:235`,
   `test_new_skill.py:153`) that repeat the fabricated citation in their
   comments. The 2026-07-16 post-mortem recorded the mechanism verbatim: green
   suites were blind to their blockers *"because the fixtures pre-satisfy the
   conditions the pins say the model must not produce."* A suite that codifies a
   pin proves the door is locked; it can never tell you the door should be open.

6. **Twice, an agent narrowed an explicit user request into a constraint — and
   in the more consequential case, the narrowing is probably right.** The user
   asked for a pane agent that acts: *"shouldn't just be a chat bot. if i tell
   it to route to a different bucket, for example, it should be able to do
   that"* (`09-surface-spec.md:1652`). The review geometry returned an agent
   that may only *propose*. And the user named autonomous review as a goal —
   *"Autonomous lesson capture with 'manual' human review, and potentially
   autonomous review, **are goals**"* (`12-transcript-miner.md:347`) — while
   invariant M-1 reads *"No exception, no flag."* Both narrowings are defensible
   on P1 grounds; neither was put back to the user as a question. These are
   listed for the user's adjudication, not recommended for reversal.

7. **The forward-work spec now in flight makes the undelivering destination the
   cheapest one to approve.** `drafts/fast-lane-spec.md:50` tiers `reference` as
   **FAST — archetype**, stating its reason plainly: *"**Unloaded surface** —
   progressive disclosure, read only when a human opens the file; affects **zero
   activations** until then."* The spec correctly identifies that reference
   delivers nothing, and uses that as the argument for making it frictionless.

The audit also finds a large number of agent-authored pins that are **correct,
load-bearing, and should not be touched** — §6 names them individually, and
several are ones a human would plausibly not have written.

---

## 1. The provenance instrument — how reliable it actually is

### 1.1 The hypothesis

When a decision is genuinely the user's, the corpus quotes them verbatim
(`08-build-plan.md:470` — *user ruling: "shouldn't be hard-coded. make it
configurable"*). So quote-presence marks user provenance and quote-absence
suggests agent authorship.

### 1.2 Verdict: high precision, near-zero recall — and one systematic false positive

**Use a quote as sufficient evidence of user provenance. Never use its absence
as evidence of anything.** Three findings support that.

**(a) The forward direction holds.** 48 distinct verbatim user utterances were
catalogued across ~60 sites. Exactly **one fabricated user ruling** was found in
the whole corpus — and the project's own blind gate caught and dissolved it
(`reviews/2026-07-18-deep-specs.md:70`, residue at
`drafts/settings-surface-spec.md:17`: *"Doc text-fix flag (F5 — **not a user
ruling**)"*). Two instances of quote drift exist (the same utterance rendered two
ways, both presented as verbatim — `11-telemetry-and-lifecycle.md:3` vs
`README.md:380`), and two self-declared non-quotes wear quote marks
("near-verbatim" at `09:1578`, "verbatim *intent*" at `forward/ui-ux.md:105`).
Minor hygiene, not a reliability problem.

**(b) The reverse direction fails outright, and fails hardest on the biggest
decisions.** Agent authorship is the **baseline state of this corpus**, not a
deviation. The first commit (`282a97c`, 2026-07-11) is the entire design corpus,
its own message calling it a *"single-authored ground-up rewrite,"* co-authored
by an agent. Across 367 commits the co-author trailers are Fable 255, Opus 5 31,
Opus 4.8 11, Sonnet 3, none 67 — there is no commit an agent did not write, so
authorship discriminates nothing.

More importantly, **quote-absence correlates with the capture mechanism, not
with authorship.** The four binding answers that chose the platform and the pane
engine — the foundation of the two largest documents in the corpus — live at
`research/2026-07-12-adjudication-surface-problem-space.md:168-176` under
*"User answers (binding, 2026-07-12 — AskUserQuestion, routed before any
freeze)"*. They are **structurally unquotable**: `AskUserQuestion` returns option
selections, not prose. Same for the four doc-13 calls behind S-17 and the four
2026-07-19 rulings.

**(c) The one systematic false positive: scope amplification, and it is
*quoted*.** `11-telemetry-and-lifecycle.md:3` quotes the user genuinely — *"review
them yourself and answer the questions you would ask me"* — but that quote
authorizes a **delegation**. The six substantive answers then land at
`README.md:384-408`, and I verified them directly: **Q1–Q5 are agent
self-answers** ("YES — …"), and only **Q6** was answered by the user. The
resulting register row `03-decisions.md:28` (S-16) reads "Ratified 2026-07-15"
and sits in the Settled table beside S-10 and S-17. **The presence of the quote
makes the row look more user-grounded than a row with none.** The same shape at
micro-scale: `forward/worker-ecology.md:4-7`, where the quoted fragment is the
two syllables `"(c)-ish"` and the surrounding prose expands it into a full
three-domain worker boundary rule.

Note the recursion: Q3's self-answer is justified by *"the user's
no-secrets-in-tracked-files posture is absolute and **autosync publishes in
seconds**"* — the same stale premise as §0.3.

### 1.3 The instrument that actually works

In descending strength: **(1)** a `feedback/` record or `reviews/*` origin line
dated the same day; **(2)** a non-autosync commit *message* using
`user ruling` / `user-requested` / `ratified` vocabulary — this vocabulary is
genuinely distinct from the agent-side `gate-zero` / `GATED SOUND` /
`fold the blind spec gate` vocabulary; **(3)** the phrase *"the user ruled
AGAINST the author's recommendation"* (`drafts/settings-surface-spec.md:717`) or
an enumerated live-answered call set — patterns no agent has an incentive to
fabricate; **(4)** per-file commit history.

That last one is decisive for this audit:

| File | Total commits | Traceable to a user touchpoint |
|---|---|---|
| `routing-doctrine.md` | 11 | **1** (`a0d8c99`, feedback r3 item 3 — the §3 re-home clause) |
| `mining-rubric.md` | **1** | **0** |
| `pane-charter.md` | **1** | **0** |
| `card-sections.yaml` | — | **0** |

### 1.4 A third laundering mechanism: eponym drift

A review-forced helper became the *name* of a doctrine, and the real authority
dropped out of its citations. The gate-zero review (2026-07-17) forced a
CLI-owned `canon_read_roots()` as the mechanism for its narrowed read scope. The
no-reimplementation rule it embodies is actually **P2-4**, an independent pin
from 2026-07-12. At `09-surface-spec.md:1953` both are correctly co-cited. But
at `08-build-plan.md:86` and `drafts/16-ecology-spec.md:207`, *"the
`canon_read_roots()` no-reimplementation posture"* is cited as standalone
authority for unrelated decisions the review never touched — with P2-4 absent
from both. A reader sees a named doctrine whose eponym is a review-forced
helper, and no trace of its agent origin.

### 1.5 Verification hygiene in this audit

Two greps here initially returned a clean-looking zero that was vacuous — one
from a `cd` that silently failed, one from a case mismatch. Both were caught and
re-run with positive controls, and every count in this document that matters
carries one. This is the failure mode the user's own `lrn-ea833a5b` names
("ask what the command prints when it cannot see the target AT ALL"), and it very
nearly landed in this audit. It also, as §3.7 shows, landed in the project's own
canary mechanism.

---

## 2. The pin inventory

Provenance key: **U** = user-ratified with a verbatim quote · **U\*** = user
decision via a structured mechanism (unquotable but corroborated) · **U?** =
user touchpoint attested, unverified · **R** = introduced by an agent
review/gate · **A** = agent-authored, no review, no user touchpoint ·
**?** = indeterminate.

### 2.1 Pins binding the routing analyst

`routing-doctrine.md` is the analyst's system prompt, loaded by four consumers:
the M1 inline `/self-learn:review` analysis, the M2 worker (`worker.py:607`),
the bare-terminal one-shot analyst (`analyst.py:74`), and the G-3 pane agent
(`doctrine.py` `compile_doctrine()`). Deployed copy at
`~/.claude/skills/self-learn/references/` verified byte-identical to the repo —
no deployment drift.

| # | Pin | Where | Prov | What it prevents | Has it fired? |
|---|---|---|---|---|---|
| A1 | Destination enum is exactly five | `routing-doctrine.md:15`; `ledger_ops.py:74` | A (first commit) | A sixth destination | structural |
| A2 | **Narrowest-surface bias — "the one standing tiebreak"** | `routing-doctrine.md:84-99` | R (`reviews/2026-07-11-refinement-review.md` C6), grounded in E-6 | Routing "up" when two destinations both work | **Fires on every routing.** It is also the *only* steering signal named in the terse one-shot analyst prompt (`analyst.py:85`) |
| A3 | **`~/.claude/CLAUDE.md` is chezmoi-managed → user scope costs more** | `routing-doctrine.md:124-127` | A — **now false** | Nothing; it inflates perceived user-scope cost | Fires as a premise on every user-scope judgment. **11 of 13 pending records are user-scope** |
| A4 | **"Records, proposals and canon are autosynced within seconds"** | `routing-doctrine.md:129` | A — **contradicted by U (S-17/D3)** | Grounds the no-secrets rule | Premise stale; the rule it grounds is still right (§6) |
| A5 | No secrets in any tracked file, ever; scan on every record-body write, default refuse, no bypass | `routing-doctrine.md:130`; S-8 | R → ratified into S-8 | Secret leakage | **Good — keep** |
| A6 | Never `GOTCHAS.journal.md` as a reference target | `routing-doctrine.md:134`; `compilers.py:351` | A (O-7 boundary) | Writing into ha-note's surface | **Good — keep** |
| A7 | **A `new-skill` proposal never names the skill** | `routing-doctrine.md:262-263` | **A — fabricated citation** | The analyst producing an approvable `new-skill` proposal | **Fired to completion: 0 proposals, 0 routings in 28.** §3.1 |
| A8 | No `rehome:` proposal field — re-home is prose only | `routing-doctrine.md:184-189` | R (Y-18 fold, `a5070a0`) | A machine-actionable re-home | Unmeasured |
| A9 | Hook proposals carry compile input + 2–3 allow/deny examples; replay mismatch **aborts** the route | `routing-doctrine.md:191-231`; `08 §8.1` | R + U (S-10 quoted) | A hook route on unvalidated bytes | **Good — keep.** But it makes `hook` expensive: §3.3 |
| A10 | Lint verdicts are enum/bool, **never a numeric score**; never blocks, never auto-edits, never penalises a soft `reasoning-pattern` trigger | `routing-doctrine.md:323-369` | R (`reviews/2026-07-18-deep-specs.md` F1–F5) | Score-driven gating; auto-editing the human's record | Present on 15/26 proposals; **`trigger_recognizable: no` = 0, `why_present: false` = 0** — never returned a negative |
| A11 | Contradiction check bounded by (scope, always-loaded); never canon-wide; **never claim completeness**; never auto-write an edge | `routing-doctrine.md:371-434` | R (FW-32 gate) | False-confidence "all clear" claims | **Good — keep.** Emitted once (`lrn-9a5d93cb`); **0 edges ever written** |
| A12 | `claude-md` `variant` decided by one question ("does the lesson have a file-path firing condition?") + two caveats forbidding presenting unpathed `rules` as narrower | `routing-doctrine.md:41-99` | A (A2, `b11d9aa`) | Overselling `rules` | **Fired to completion: 0 `rules`, 0 `local` in 12 claude-md routings — 6 of them *after* the feature shipped** |
| A13 | Propose only; never call `route`/`reject`/`defer`/`graduate`/`rehome` | `routing-doctrine.md:252-258` | A, aligned with U\* P1 | Proposer becoming approver | **Good — keep.** 32/32 routings `by: human` |
| A14 | `already_canon: true` only when substance is fully in loaded canon; bulk criterion = knowledge AND source file is canon; behavioural records never bulk-flagged | `routing-doctrine.md:174-182` | R (implementability review) | Over-graduation of behavioural records | **0 of 26 proposals ever set it true** |
| A15 | Managed sections cap at 10 entries / ~150 words | `02-schema.md:499`; `compilers.py:88` | R (refinement review C6), grounded in E-6 | Unbounded loaded-surface growth | **Fired 6×** — telemetry `surface-budget` `overflow: true` (claude-md 161 words ×4; skill-md 211 ×2). §3.6 |
| A16 | Trigger-first compile form; compiler takes only the first line of `## Instruction` | `routing-doctrine.md:233-249`; `02-schema.md:493` | R (SOTA fold, E-20) | Bare imperatives with no firing condition | **Good — keep** |

### 2.2 Pins binding the miner

`mining-rubric.md` — **one commit ever** (`2cd292d`, 2026-07-15), zero review
records, zero user touchpoints. This governs the system's only unattended writer.

| # | Pin | Where | Prov | What it prevents | Has it fired? |
|---|---|---|---|---|---|
| M1 | **"When in doubt, do not emit"** — err toward precision | `mining-rubric.md:7`; echoed `12:317` | A | Noise floods that kill the review habit | Every run; the false-negative side is unmeasured |
| M2 | Exactly four lesson shapes may be emitted | `mining-rubric.md:9-30` | A | Any fifth shape | Every run |
| M3 | Never emit meta-lessons about self-learn from its own sessions; a self-learn command tag halts the **rest of that session forever** | `mining-rubric.md:38-41`; `12:76-81`, `12:313-318`; `miner.py:126` | A, tightened by blind audit after it *"collapsed on the first review reply, mining every card's verbatim lesson text back as fake sightings"* | Self-referential capture loops | **Good — keep.** Largest recall sacrifice in the design, nowhere quantified |
| M4 | Never emit emotional or interpersonal observations about the user | `mining-rubric.md:42-43` | A (no recorded rationale) | Profiling the user | **Good — keep** |
| M5 | Confidence high only for corrections and verified gotchas | `mining-rubric.md:55-56` | A | Overconfident inferences | Every run |
| M6 | **Reconciliation honesty** — claiming no-match to get a fresh landing is *"the one behavior that most damages trust"* | `mining-rubric.md:58-63` | A | Duplicates displacing folds | **Never fired: `folded: 0` across all 14 runs** — the behaviour the rubric calls most damaging is entirely unmeasured |
| M-1 | **Mined records never auto-route — "No exception, no flag."** | `12:281-283` | A — **and more restrictive than the user's own quoted goal** (§4.6) | Any capture→canon path | **Good in substance — keep.** 32/32 routings `by: human`. But the wording forecloses what the user named a goal |
| M-2 | Landing is verb-gated; the miner has no direct file or git path into the repo | `12:284-287` | A, hardened by two-reviewer audit | Direct writes/commits | **Good — keep.** This is what makes no-per-record-confirmation survivable |
| M-3 | Never load-bearing; additive and killable with zero data loss | `12:286-288` | R, traced to E-11; survived the user's "build now" | Downstream dependence on the miner | **Good — keep** |
| M-4 | **Caps are hard — refuse, not warn** | `12:289-291` | **Values = U** (*"a fixed 3/run is constrictive on a 12-hour day"*); **hardness = A** | Silently squeezing overflow through | **Fired and biting.** §3.4 |
| M-5 | The system never mines itself | `12:291-293` | A + blind audit | Fake sightings from review sessions | **Good — keep** |
| M8 | Per-run cap `min(2 × sessions_scanned, 15)`; pending-gate 25 | `12:357-363`; `miner.py:81-83` | **U** for the values | Flooding | **4 real lessons dropped in one run** when 6 qualified against a cap of 2. §3.4 |
| M9 | Episode-brief cap ≤1200 chars, **refuse-not-clip** — *"can lose an otherwise-valid lesson; that cost is accepted deliberately"* | `12:557-565`; `miner.py:105` | A, self-flagged with a revisit condition | An unbounded prose field | Unreported; observable in the journal |
| M10 | Compose-before-scan ordering invariant (brief built in `_build_record` before `_scan_candidate`) | `12:540-550`; `miner.py:812-862, 1024` | A | An unscanned, attacker-influenceable prose field reaching the record | **Good — keep.** Genuinely load-bearing, with a named test |
| M11 | Autonomy ladder L1/L2/L3 activate only *"by dated register edit, justified by measured per-class accept rates"* | `12:414-423` | A, responsive to a real user aspiration | Ungrounded autonomy | **Gated shut at L0.** No such register edit exists; no document reports the accept rate being read. §3.8 |
| M12 | A rejected class returns **only** via 3 fresh machine sightings; `dropped-rejected` emits no record id, never a snippet, never promotable | `12:639-648`, `12:365-369` | **U** for resurfacing-on-evidence; **A** for the id suppression | Re-litigating a human's "no" | Defensible consent pin — but a door with no human-side handle (§3.9) |

### 2.3 Pins binding the M2 worker

The worker's prompt is **private** — it lives in `worker.py:581`, not in the
reviewable `references/` tree, and no human-facing surface renders it.

| # | Pin | Where | Prov | What it prevents | Has it fired? |
|---|---|---|---|---|---|
| W1 | Fully append-only; write surface = new proposal files only; **no Bash, no Edit** | S-5 (blind re-review 2026-07-12); `worker.py:321` | R → ratified into S-5 | Record mutation by a background process | **Good — keep** |
| W2 | **"Never re-propose the classes below (recently rejected)"** — last 20 rejected records injected as negative exemplars, no expiry, no positive counterpart | `worker.py:604`, `_digest()` | A | Re-proposing a refused class | Near-inert today (**1 rejection in 64**) — a ratchet with no release. §4.3 |
| W3 | Merge proposals only; the human collapses clusters | S-5; `worker.py:593` | R | Worker-executed merges | Unmeasured |

### 2.4 Pins binding the in-GUI iterator and the review surface

The pane agent's system prompt is `routing-doctrine.md` + `pane-surface-model.md`
+ `pane-charter.md` concatenated by `doctrine.py`. Everything in §2.1 binds it
too.

| # | Pin | Where | Prov | What it prevents | Has it fired? |
|---|---|---|---|---|---|
| G1 | **Proposer and approver are never the same party; no path to `route`/`reject`/`defer`/`graduate`, ever** | `pane-charter.md:65-78`; `07:139-150` | A/R, on a U\* foundation (P1) — but see §4.6 | Agent self-approval | **Good — keep.** The most load-bearing invariant in the system |
| G2 | Fixed allow/deny read surface; a denied read is *"not delayed, not negotiable"*; retrying a denied read is never the fix | `pane-charter.md:36-52` | A | Scope escape by re-spelling a path | **Good — keep** |
| G3 | **No shell, no task delegation, no web, no MCP** — *"structurally absent so that the write restriction cannot be routed around"* | `pane-charter.md:57-63`; `09:966-978` | A, citing E-18 | Sandbox escape | **Good — keep.** Single most load-bearing pin on the surface |
| G4 | Writes exactly two files; **`Edit` only on the record, never `Write`** — *"granting `Write` would let a session recreate it whole"* | `pane-charter.md:53-56`; `09:954-965` | A | Record resurrection; cross-record writes | **Good — keep.** Precise and non-obvious |
| G5 | Pane canon-read scope = canon surfaces only, **not** whole host roots | `03-decisions.md:54`; `09:1443-1480` | **R — the reviewer overruled the spec author's draft on a values question** | Whole-tree reads incl. untracked files | Conservative default holding. Recorded as *"user-ratifiable and unexercised"* for 9 days. §4.7 |
| G6 | No system vocabulary in human-facing prose | `pane-charter.md:96-108`; `09:1543-1554` | R + **U** (*"i have no idea what you mean by a guard"*, `05-evidence.md:180`) | Cards that convert adjudication into rubber-stamping | **Good — keep.** Grounded in measured failure |
| G7 | `o` destination cycle offers parameter-free destinations only, scope-filtered | `models.py:88`; `routes.py:214`; `09:365-382` | R (09 §2.3) + U? (feedback r2 item 3) | A cycling key supplying structure it cannot | **Fired: `new-skill` and `hook` unreachable from the GUI action bar.** For `user` scope the cycle is a **single** option, `('claude-md',)` |
| G8 | Pane proposal `dest` must match `_DEST_RE`, requiring `new-skill:.+` | `proposals.py:97-100` | A | A malformed dest reaching the human as armable | **Fired: refuses the exact form doctrine A7 mandates.** §3.1 |
| G9 | Scope validity joins parse validity at intake | `proposals.py:308-320` | R + U? | Arming a route the CLI would refuse | **Good — keep.** Fixed a live bug |
| G10 | `hook` and user-scope `claude-md` never fast-lane — *"invariant, not a default"* | `drafts/fast-lane-spec.md:41-42` | R | A habituated sweep applying executable code | **Good — keep**, but its stated ground for the user-scope half is the stale A3 premise |
| G11 | Arm-then-confirm, never modal-confirm; **no Ctrl/Alt chords ever** | `09:136-141`, `09:92-95` | A (rationale stated) | One-keystroke irreversible routing; accidental tab close | **Good — keep** |
| G12 | Agent proposals render **WAITING, never armed**; `y` arms, `Enter` confirms — *"exactly the same two-keystroke consent path, never a shorter one"*; one proposal at a time, **refuse not replace** | `09:1158-1194`, `09:1113-1119` | R (Y-13, after its own review returned NEEDS REWORK) | A proven race: an SSE swap replacing a human-armed bar between read and Enter | **Good — keep.** Closed structurally, not by client suppression |
| G13 | Bucket-change staleness cleared on **both** arm and confirm — *"the confirm-side check is load-bearing, not belt"* | `09:1130-1157` | R (Y-18 F2/F5/F10) | Compiling into a different project's canon than the bar the human read | **Good — keep.** Genuinely non-obvious correctness pin |
| G14 | Closed proposable verb list; **`host add`, `route --collapse`, and all telemetry verbs excluded** — *"the agent must never widen its own read scope or mint write targets"* | `09:1062-1086` | R (Y-11, overriding the design brief's own suggestion) | Self-widening | **Good — keep.** The corpus catching itself |
| G15 | `allowed_tools` stays empty (a listed tool is auto-approved *before* the callback runs); `setting_sources` explicitly `[]` (the documented default-is-none is **false** — 33,972 vs 3,027 cache tokens measured) | `09:918-929`, `09:844-852` | R, **empirically grounded, doc-falsifying** | Silent bypass of the entire charter; the user's whole environment riding into the pane | **Excellent — keep.** Exactly the fail-open shape that looks like a pass |
| G16 | Render path is adversarial by construction: autoescape on, markdown `html=False`, CSP `default-src 'none'` on every response, Pygments class-mode, no inline `style=` | `09:520-558` | R (phase-A gate), empirically confirmed | A `<script>` payload in a record or a pane block executing in the token-cookied origin — *"defeating every mutating-route control and the P1 human-gate invariant itself"* | **Excellent — keep.** Probably the clearest case of an agent pin a human would not have written |
| G17 | Bulk operations: exactly one, and it is a **loop of per-record `graduate`**, never rejects — *"a graduation bulk landing as rejects would flood the rejected-proposal digest's negative-exemplar window"* | `09:246-267` | A/carried | Bulk route; heterogeneous batch-approve | **Good — keep.** Note it is the only thing standing between W2's ratchet and a flood |

---

## 3. Consequence accounting

The fingerprint asked for is **a capability that exists in code but has never
been exercised.** The ledger gives exact numbers over the project's whole life.

### 3.1 `new-skill` — 0 proposals, 0 routings

Three constraints close the door, in three different files:

| Layer | Constraint | Effect |
|---|---|---|
| Doctrine (analyst + pane prompt) | `routing-doctrine.md:262` — *"A `new-skill` proposal never names the skill"* | Analyst must emit bare `new-skill` |
| GUI intake | `proposals.py:99` — `_DEST_RE` requires `new-skill:.+` | Bare `new-skill` **refused** — verified live |
| CLI route | `verbs.py:898-903` — bare `new-skill` raises `VerbError` | A doctrine-compliant proposal file cannot be routed from |
| GUI action bar | `models.py:88` — absent from `PARAMETER_FREE_DESTINATIONS` | Human cannot cycle to it either |

The pane agent's *own concatenated system prompt* contains both halves:
`routing-doctrine.md:262` says never name it; `pane-surface-model.md:60` says
`new-skill:<name>` "need[s] structure a proposal must already carry."

Verified live in an isolated sandbox (pure functions, no verbs, no ledger):

```
_DEST_RE   'new-skill'      -> REFUSE      'new-skill:foo' -> ACCEPT
destinations_for_scope: skill ('skill-md','claude-md','reference')
                        project ('claude-md','reference')
                        user    ('claude-md',)          # a cycle of one
```

**Measured consequence:** never proposed as a primary destination in 26
proposals; never routed in 32 routings. It appears only as an `alternates:`
entry three times, all on records still pending. The sole surviving path is a
human typing `self-learn route <id> --dest new-skill:<name>` in a bare
terminal — which `09:1620-1628` itself classifies as a defect
(*"any surface text asking the user to run a terminal command is a defect unless
recorded here as exempt"*), and `new-skill` is not on the exempt list.

**Provenance:** entered at `4be6d2b` (2026-07-16), a commit titled *"T17b:
hook-proposal schema + CLI script stamp + doctrine §5.1"*. The clause was a
rider, not the subject. It replaced honest prior text (*"`new-skill` and `hook`
may be proposed but cannot compile until M3"*). No user quote. Its downstream
citation `08-build-plan.md:469` ("the confirmed §4 human call") **points at a
section that does not contain it**, and §4 is itself an agent-authored table of
*who should decide*. Two tests then codified the refusal and repeated the
citation.

### 3.2 `reference` — 14 routings, 0 delivered

The same failure class with the opposite signature: not a capability never used,
but the **most-used capability delivering nothing**.

- `reference` is the largest destination: **14 of 28 routed records (50%)**.
- `compile_reference` (`compilers.py:317-373`) appends to
  `references/LEARNINGS.md` and **touches nothing else**. No code anywhere in
  `cli/src`, `ui/src`, or `skills/` writes a pointer into SKILL.md on a reference
  route — verified by grepping every `LEARNINGS` occurrence in the tree.
- Exactly one `LEARNINGS.md` exists on the host:
  `~/repos/claude-skills/plugins/home-assistant/skills/home-assistant/references/LEARNINGS.md`.
  It holds **all 14** reference-routed records — verified id by id, 14/14.
- **Nothing in the entire home-assistant plugin mentions it.** Case-insensitive
  search for `learnings` across the plugin returns one file — itself. Positive
  control: `GOTCHAS` is cross-referenced from 5 files, including `SKILL.md:120`
  and the plugin README. That SKILL.md links six other reference files by name;
  not this one.

Progressive disclosure in Claude Code works because SKILL.md tells the model
which reference files exist and when to open them. An unlinked reference file is
never loaded. **P2 ("Delivery is native loading only… reference docs
(progressive disclosure)") is not satisfied for half the routed corpus.**

The lessons are substantive — e.g. `lrn-01865691`, the Adaptive-Lighting
`sleep_rgb_color` CCT-floor finding with a verified cause and fix. That one cost
an evening and is currently unreachable.

**This is a missing pin, not a bad one** — the hole that A2 steers traffic into,
at scale, while every metric reads green (commits happen; the inbox drains; P5
is satisfied).

### 3.3 `hook` — the analyst is 0 for 3, and every real hook bypassed it

| Record | Analyst proposed | Human routed to |
|---|---|---|
| `lrn-98d42215` | `hook` | `skill-md` |
| `lrn-6883f824` | `hook` | `skill-md` |
| `lrn-25968266` | `hook` | `claude-md` |

Every analyst `hook` proposal was downgraded. Conversely the three records
actually routed to `hook` (`lrn-38514455`, `lrn-4f5971c8`, `lrn-dd9489b2`) **had
no proposal at all** — one-motion `teach --route` captures that bypassed the
analyst.

Doctrine §2 (*"Prefer `hook` when the mistake is mechanical and
tool-detectable"*) is producing recommendations the human rejects 3 for 3, while
the destination is reached only by routing around the analyst. Three points is
not proof, but the mechanism is legible: A9 makes a hook proposal far more
expensive to author and more brittle to approve than the `skill-md` alternate
the doctrine also requires the analyst to offer.

### 3.3a The one-shot analyst can never emit a `hook` proposal — and that silently implements a split the user explicitly rejected

A second instance of the fingerprint, mechanically tighter than `new-skill`, and
the only one that defeats a **verbatim user ruling**.

The chain, verified directly:

1. `analyst.py:91` offers the destination in the prompt:
   `destination: <one of skill-md | claude-md | reference | new-skill | hook>`.
2. The same template (`analyst.py:85-102`) provides **no slot** for `hook:` or
   `examples:` — only `destination`, `alternates`, `rationale`, `variant`,
   `rules_topic`, `rules_paths`.
3. `analyst.py:196-211` builds the proposal from a **fixed key allowlist** —
   6 keys plus optional variant fields. Any `hook:`/`examples:` the model emits
   anyway is **silently dropped**.
4. `analyst.py:212` calls `validate_proposal`, which reaches
   `ledger_ops.py:443-447`: *"a hook proposal carries the structured compile
   input — hook: {tools, path_regex, deny_message}"* → `ProposalError`.
5. `analyst.py:214` converts that to `AnalystError`; `teach.py:676-685` catches
   it and falls back to a plain pending capture.

So `analyst.analyze()` **can never return `destination == "hook"`**, and
`teach.py:689-694` is unreachable code whose own comment describes data the
function above it just stripped: *"the analyst's proposal IS the compile input
(it carries the §5.1 hook block + examples…)"*.

**Why this matters more than the others.** S-10's amendment is one of the most
carefully recorded user rulings in the corpus, with *two* verbatim quotes. The
second is a scope ruling that answers precisely this question
(`03-decisions.md:21`):

> *Scope ruling 2026-07-16 (user, closing the delta review's n-2 question — "when
> the flag flips and opens the gate, it opens it fully."):* `hook: true` enables
> BOTH one-motion roads — the explicit `--hook-input` path AND the
> analyst-authored bare `teach --route` path… **Considered and rejected:
> splitting the knob per authorship.**

The code splits the knob per authorship anyway. `--hook-input` works; the
analyst-authored road cannot fire. `config.py:25-31` still documents both, and
`routing-doctrine.md:269-271` still instructs the analyst in the behaviour the
code forecloses: *"When enabled, a hook proposal you author for a bare `--route`
still needs the FULL §5.1 block."*

**Scoping, to be fair:** `hook` is not dead overall. The **batch worker** writes
proposal YAML directly through a path-scoped Write grant (`worker.py:279-293`)
with the full doctrine appended, so it can produce a valid §5.1 hook proposal.
The dead thing is specifically the one-shot analyst leg. Provenance: the analyst
template dates to `61cd796` (2026-07-13); the §5.1 schema landed at `4be6d2b`
(2026-07-16); the unreachable branch landed at `891a715` the same day, in a
commit whose message asserts the capability that cannot exist. Nobody widened the
allowlist. This one is a **bug against a real ruling, not a pin to revisit** —
cheap to fix either way (widen the template + allowlist, or delete the branch and
correct the config docs).

### 3.3b `reference:<file>` — the silent sibling, and the missing link in §3.2

Doctrine invites the analyst to name a target file (`routing-doctrine.md:133`:
*"You may name another **existing** references file when the lesson clearly
belongs there"*). But **the proposal schema has no field for it**, and
`verbs.py:510-516` passes `ref_name=None` on the proposal branch.
`verbs.py:427-431` parses `reference:<file>` only from a human-typed `--dest`.

Unlike `new-skill`, this raises nothing. It **silently lands in the default
`LEARNINGS.md`**. Ledger: 14 reference routes, **0 with a named file**.

This is the missing mechanism behind §3.2. The home-assistant SKILL.md *does*
link `references/GOTCHAS.md` (line 120). Had the analyst been able to name it,
those 14 lessons would have been discoverable. Doctrine flags exactly this
schema gap for `rehome` (*"There is no `rehome:` proposal field… do not invent
one, the validator will not accept it"*) but **not for `reference`**, despite an
identical mechanism gap — so the analyst is invited to do something it has no
way to do, and the failure is silent rather than loud.

### 3.4 The miner cap is discarding lessons the rubric already vetted

One run had **6 qualifying candidates against a cap of 2**. The 4 losers are
journalled `outcome: "dropped-cap"`, `disposition: "cap-refused"`,
`promotable: false`, with the note *"a real lesson, but this run had already
landed its cap."* They are not deferred — they are dropped, recoverable only via
a cache-local near-miss snippet that rolls off.

Compounding: M1's *"when in doubt, do not emit"* means everything reaching the
cap already survived a conservative filter. **The cap cuts into the good
candidates specifically, not the noise.**

Miner totals: 14 real runs, 12 candidates landed, **4 of 12 survived to
routing (33%)**, `folded: 0`, `recurrences: 0`.

### 3.5 `claude-md` variants `rules` / `local` — 0 and 0

A2 shipped both on 2026-07-22 (`b11d9aa`). **Six claude-md routings have
happened since, all plain.** The `variant` key has never been written to any
record or proposal in the ledger's entire history.

A12 is a plausible cause: it collapses the decision to one question ("does the
lesson have a file-path firing condition?"), then adds two pinned caveats
warning the analyst *not* to present unpathed rules as narrower or cheaper. Since
most durable lessons name a *moment* rather than a *path* — the doctrine's own
example is "about to spawn a subagent", which is a real routed record
(`lrn-5d0c592a`) — the pin routes essentially everything back to plain
`claude-md`. The capability may be correctly unused; but it is unused because a
pin written the same week made it hard to select, and nobody has measured
whether that is right.

### 3.6 Other measured zero-usage

| Capability | Usage | Note |
|---|---|---|
| `already_canon: true` | **0 of 26 proposals** | 19 records *were* graduated (`superseded_by: canon`) — graduation happens, but never via the analyst's flag. A14's careful criterion has never been applied |
| `lint.trigger_recognizable: no` | **0** | Lint has never returned a hard negative |
| `lint.why_present: false` | **0** | Ditto |
| `links.contradicts` edges | **0 ever** | `link contradicts` never invoked. One proposal emitted an anchor (`lrn-9a5d93cb`), still unapplied |
| Miner `folded` / `recurrences` | **0 / 0** | M6 has never had an occasion to be honoured or violated |
| `source: memory` | **value does not exist** | S-14's auto-memory importer has never landed a record |
| Telemetry kinds for route/reject/defer/graduate | **none exist** | **Resolution is not telemetered at all.** The only record of an outcome is the frontmatter and the git commit |
| `routing.by` non-human | **0 of 32** | P1 holds |
| Rejection | **1 in 64** | The gate is essentially never used to say no |

### 3.7 A trigger that fired and was not noticed

`14-forward-work-map.md:135` lists "02 §4 over-cap WARNING on a route → FW-6
graduation-pressure flow" as a **dormant, unexercised** mechanism.

Telemetry says otherwise: **6 `surface-budget` events carry `overflow: true`** —
claude-md at 161 words (×4) and skill-md at 211 words (×2), against a ~150-word
cap. The trigger has fired six times. FW-6 was never activated, and the forward
map still describes it as waiting.

### 3.8 Fail-open shapes the corpus built into itself

Two, both matching the user's own captured lesson `lrn-ea833a5b` — *"ask what the
command prints when it cannot see the target AT ALL. If that output is identical
to 'pass', the gate is worthless."*

- **The canary recall check cannot report the failure it exists to detect.**
  `12:686-692`: plant writes *"a **best-effort** session id … a canary with none
  simply cannot score `missed`, only `caught`."* A canary block reading
  `{planted: N, caught: K, missed: 0}` is indistinguishable from one that cannot
  see misses at all. The mechanism was built to measure miner recall.
- **DP-2 is permanently exempt from the only instrument built to measure it.**
  `12:693-695`: plant *"refuses any lesson naming DP-2 — the standing
  window-placement experiment … stays the first natural canary … and is never
  planted artificially."* The designated first canary is the one thing the canary
  mechanism refuses to instrument.

### 3.9 A door with no human-side handle

`12:639-648`: `dropped-rejected` emits **no record id**, **never** a snippet, and
is **never promotable**; *"the resurfacing counter remains the only path a
rejected class returns."* A human who changes their mind about a rejection
cannot see it in the near-miss drill and cannot promote it — only three fresh
machine sightings can resurrect it. Defensible as a consent pin; but it is a
one-way door, and the register does not record it as one.

### 3.10 The permission-fallback ladder has no floor

`09:1013-1022` pins the ladder as *"a pivot down this ladder, never a stall and
never a loosened surface"*, with **rung 4 = the `cli` engine**. But `09:702-713`:
the `cli` engine is *"kept specced, not built"* and `SELF_LEARN_PANE_ENGINE=cli`
**exits**. If rungs 1–3 fail, the pinned outcome is "never loosen" plus a rung
that a human must first implement. Not currently harmful (rung 1 passed T-B), but
the safety net's last rung does not exist.

### 3.10a Smaller structural items

- **The stale chezmoi premise has a second firing site in code.**
  `verbs.py:951-955` refuses reference-at-user-scope because *"the user host is
  the chezmoi-managed CLAUDE.md, it has no references dir (doc 13 §2)."* The
  refusal may still be right; its stated justification is dead. This is why
  `destinations_for_scope("user")` is a cycle of one (§5.2).
- **The whole chezmoi subsystem is dead by environment.** `chezmoi.py` (438
  lines), the `chezmoi-adopt` verb (`cli.py:281`, `routes.py:64`),
  `CHEZMOI_DRIFT_REFUSAL` (`verbs.py:2484`), and `preflight_user_scope` span 8
  files. `chezmoi-adopt` shipped in `b11d9aa`, dated **2026-07-24** — the same
  day chezmoi was retired on this host.
- **Two independent "what counts as a write" lists.**
  `engine/sdk.py:120` `_WRITE_TOOLS = {"Edit","Write"}` is UI-signalling only;
  enforcement uses separate inline literals at `charter.py:229`
  (`Write`,`Edit`,`NotebookEdit`) and `charter.py:264` (`Write`,`Edit`). Drift is
  already visible — sdk's copy lacks `NotebookEdit`. Low severity today (the
  permissive copy is the non-enforcing one), but it is two copies of one rule in
  a codebase whose P2-4 pin exists to forbid exactly that.
- **A documented hole in the pane charter:** reads inside `cwd` are
  SDK-auto-approved and never reach the charter callback at all
  (`charter.py:24-28`). Disclosed, not hidden — but it means the read-scope pin
  (G5) is enforced everywhere except the one directory the session starts in.
- **Low-surface capabilities:** `canary plant` (`cli.py:387`) has zero
  documentation outside argparse help — absent from SKILL.md, doctrine, and
  commands. `confirm-held` has one SKILL.md row and no UI key. `supersede` is
  CLI-only. `defer --until` is fully wired but has **no UI date control** — only
  the pane agent can supply `until`, so a human can defer but cannot choose the
  date from the surface.

### 3.11 Document-integrity findings

- **A merge-conflict marker is committed in the design-authority document.**
  `09-surface-spec.md:2388` contains a bare diff3 marker `||||||| 1e830b5` with
  no siblings, attributed by blame to `8e48621` — the merge titled *"blind code
  gate CLEAN"*. Cosmetic damage only, but direct evidence that the gate did not
  read the spec it amended.
- **`12 §2` states the opposite of its own `§10` amendment, and code follows
  §10.** `12:106-109` still reads *"Containment is the M2 worker posture
  verbatim: `--allowedTools "Read,Grep,Glob"`."* `12:306-312` reverses it: *"the
  reader has NO filesystem tools."* Shipped: `miner.py:565`
  `READER_DISALLOWED_TOOLS = worker.DISALLOWED_TOOLS + ",Read,Grep,Glob"`.
  **A reader taking §2 as normative would loosen the reader's containment.**
- **`12 §2` Phase 4's cap numbers are superseded by §8 and never corrected in
  place** (3/run and pending-gate 10 vs the shipped 2×sessions/15 and 25).
- **`09 §8`'s "No in-surface capture" is now false.** `09:1351-1352` still
  asserts it; `09:2413-2423` + `12:719-730` add
  `POST /mine/near-miss/promote`, which rides `teach` and lands a real pending
  record from a single GUI tap — explicitly without arm-then-confirm (*"the tap
  **is** the confirmation"*). The corpus's own rule is that a 09↔corpus conflict
  *"is a finding"*; this one was never raised.
- **`09:1620-1628`'s exempt list is stale against its own enforcing test.**
  `tests/test_templates.py:63-69` was updated to permit the armed host-add bar's
  command display; the spec's enumeration was not.

---

## 4. Ranked list: which pins to revisit first

Ranked by *(consequence severity × confidence it was never ratified)*.

| # | Pin | Severity | Confidence never ratified | Action |
|---|---|---|---|---|
| **1** | **Missing reference-discoverability rule** (a hole, not a pin — A2 steers into it) | **Highest.** 50% of routed lessons undelivered; 14 real lessons unreachable | n/a — never surfaced as a decision at all | Either make `compile_reference` maintain a pointer in the owning SKILL.md, or stop calling `reference` a delivery destination. A values call, and the user's |
| **2** | **A7 — `new-skill` naming pin** (`routing-doctrine.md:262`, `verbs.py:899`, `proposals.py:99`, `08:469`, + 2 tests) | High: a whole destination dead, 0/28 | **Very high.** No quote; §4 citation verified false; entered as a rider; tests codify it | Already user-ruled for reversal. Reverse in all four code/doc sites **plus `pane-surface-model.md:60`** at once, and delete the two asserting tests — otherwise the contradiction just moves |
| **2a** | **The `reference:<file>` schema gap** (`routing-doctrine.md:133` invites it; no proposal field; `verbs.py:510-516` passes `None`) | High, and it *is* the mechanism behind #1: 14/14 reference routes defaulted to the orphan file when a linked one (`GOTCHAS.md`) existed | High: no citation of any kind | Add the field, or state the gap in doctrine the way `rehome` states its own. A silent default is the worst of the three options |
| **2b** | **The one-shot analyst's `hook` allowlist gap** (`analyst.py:196-211`) — *not a pin, a bug* | High: silently implements the per-authorship split the user **explicitly considered and rejected** | n/a — this contradicts a quoted ruling rather than substituting for one | Fix, don't adjudicate: widen the template + allowlist, or delete `teach.py:689-694` and correct `config.py:25-31`. §3.3a |
| **3** | **A3 — "chezmoi-managed" premise** (`routing-doctrine.md:124`) | High: biases every user-scope judgment; 11 of 13 pending records are user-scope | High: agent-authored, now false in code *and* on this host | Delete or rewrite. Also strip it from `drafts/fast-lane-spec.md:39`, which inherited it as the ground for an invariant |
| **4** | **A4 — "autosynced within seconds" premise** (`routing-doctrine.md:129`) | Medium-high: a false premise in a live prompt, contradicting a *user-ratified* decision, and it is load-bearing for at least one agent self-answer (§1.2c Q3) | High | Fix the premise. **Keep the rule it grounds** (A5, no secrets) — restate on its own merits. Also check `review.md:18` and `SKILL.md:49`, which still tell the review flow to `sentinel hold` to "pause autosync" |
| **5** | **M8/M-4 — miner cap** | Medium-high: measurably discarding rubric-vetted lessons (4 dropped when 6 qualified against a cap of 2) | Low-medium — **the values are the user's** (quoted); only the drop-don't-defer behaviour is the agent's | Do not re-litigate the numbers. Change the *disposition*: carry near-misses into the next run instead of dropping them. The journal already has the data |
| **6** | **A12 — `claude-md` variant decision rule** | Medium: two shipped capabilities at zero usage | Medium: A, same-week authorship, never reviewed | Revisit after #3 — the variant question and the user-scope-cost question are entangled |
| **7** | **A10 — lint that never says no** | Low-medium: a signal consuming card space and analyst tokens while carrying no information | Medium: R | Either accept it as advisory-only and stop reading its presence as a quality signal, or find out why `no` is never emitted |
| **8** | **A15 — the 10/150 cap** | Low now, rising: already exceeded 6× | Medium: R, grounded in real evidence (E-6) | Don't change the cap; **activate FW-6**, whose trigger has already fired |
| **9** | **W2 — rejected-proposal digest** | Low now (1 rejection), structurally concerning | Medium: A | Add an expiry or a scope bound before rejections accumulate. §5.3 |
| **10** | **Document-integrity items** (§3.11) | Low individually; corrosive together — three of them would mislead a future agent into loosening a containment or re-asserting a false invariant | n/a | Fold the amendments into the original text. This is where the corpus actually leaks |

### 4.6 Two narrowings of explicit user requests — for the user, not for us

These are **not** recommendations. They are places where a verbatim user request
was answered with a narrower constraint, and the narrowing was never put back as
a question. In both cases I judge the constraint substantively defensible.

- **The pane agent.** User: *"shouldn't just be a chat bot. if i tell it to route
  to a different bucket, for example, it should be able to do that"*
  (`09:1652`). Result: an agent that may **request** via one server-owned tool
  rendering a WAITING bar the human arms with `y` and confirms with `Enter`
  (`09:979-986`). The corpus is explicit that this *"refines, never repeals"* P1.
  Consequence: 32/32 routings are `by: human`, which is the invariant working.
- **The miner.** User: *"Autonomous lesson capture with 'manual' human review,
  and potentially autonomous review, **are goals**"* (`12:347`). Result:
  invariant M-1, *"No exception, no flag"*, plus an autonomy ladder (M11) gated
  behind a metric no document reports having read (§3.8). The user named a
  direction; the corpus built a door and never opened it.

### 4.7 The one values question bound by a reviewer, unasked for 9 days

`09:1443-1446` records that Y-2's **first draft was whole-host-root reads**, and
that the gate-zero blind review narrowed it to canon surfaces only, reasoning:
*"`host add` consents to compilers writing managed sections — it was never
consent for a model-backed session to read an entire repo tree, untracked files
included."* That is a judgment about what a human's consent covered. The register
has said *"user-ratifiable and unexercised"* since 2026-07-18
(`03-decisions.md:54`, `14-forward-work-map.md:121`).

The narrow scope is substantively right. The hygiene is exemplary — the corpus
flagged its own agent-set boundary and kept flagging it. It is listed here only
because it is still open.

---

## 5. Forward prediction — named mechanisms

Weighted toward the analyst, miner, and GUI iterator.

### 5.1 Analyst — the fast lane will industrialise the delivery gap

**Mechanism.** `drafts/fast-lane-spec.md:50` tiers `reference` as **FAST —
archetype**, justified by the observation that it is an *"**Unloaded surface** …
affects **zero activations**"*. A2 already steers the majority class toward it
(E-2: ~90% of real lessons are knowledge; doctrine §2 sends knowledge/skill-scope
to `reference` unless the fact "must be present at activation to prevent a wrong
first move" — a deliberately high bar). Today that produces 50% of routings
landing in an orphan file. The fast lane makes those routings a one-line sweep,
with a `FAST_SWEEP_CAP=5` the user ratified.

**Prediction.** Throughput rises sharply; delivered lessons stay flat.
**Every instrument the system has will read green** — commits happen (P5
satisfied), the inbox drains, `report` shows a rising accept rate — because no
metric distinguishes "routed" from "loadable". The fast-lane spec is explicitly
paranoid about P1's *spirit* eroding into rubber-stamping; it is not watching the
axis where the erosion has already happened.

**Cheapest early warning:** a `--selftest` check that every `reference` compile
target is reachable from a loaded surface. It would fail today, 14 times.

### 5.2 Analyst — the user-scope queue will keep growing and cannot drain

**Mechanism.** Three constraints compose: (a) A2 makes user scope "the most
expensive destination in the system"; (b) A3 adds a *now-false* chezmoi cost on
top; (c) in the GUI, `destinations_for_scope("user")` returns
**`('claude-md',)`** — a cycle of one — so a human looking at a user-scope record
has no destination choice to make in the surface at all.

**Evidence it has started.** 11 of 13 pending records are user or hypr-doctor
scope; every project-scope record has been routed (6/6); no routing has occurred
in ~1.7 days while 5 new records were captured.

**Prediction.** The pending queue becomes a user-scope-only queue that the review
surface has no affordance for resolving and the doctrine actively discourages
resolving. It will be experienced as "the queue is full of hard ones", and the
diagnosis will be sought in the records rather than in the pin that made their
only destination expensive on a premise that is no longer true.

### 5.3 Analyst — rejection is a one-way ratchet

**Mechanism.** `worker.py:604` injects *"Never re-propose the classes below
(recently rejected)"* with the last 20 rejected records (`_digest()`). There is
**no expiry, no scope bound, and no positive counterpart** — no "these classes
were approved" digest. Approval teaches the analyst nothing; refusal teaches it
permanently. The digest is assembled at runtime from `git log` and appears in no
file a human reads.

**Why it is quiet now:** 1 rejection in 64 records.

**Prediction.** As rejections accumulate the analyst's live option space narrows
monotonically and invisibly. A user who rejects three `hook` proposals in a
fortnight — already 3 for 3 on downgrades (§3.3), and a downgrade is one keystroke
from a reject — will durably suppress hook proposals without ever deciding to.
Note the coupling to G17: the bulk-graduate loop exists partly *because* a
graduation flood into the reject digest would poison this window. The corpus
already knows this mechanism is sharp; it has not bounded it in time.

### 5.4 Miner — the cap discards the highest-value class, and the instrument that would show it is off

**Mechanism.** M8's cap drops qualifying candidates with `promotable: false`
rather than deferring them. Already observed: 4 real lessons dropped in one run.
M1's precision posture guarantees the cap cuts into vetted candidates, not noise.

**Prediction.** Miner yield stays flat as usage grows, and the flatness reads as
"the rubric is well-calibrated" rather than "the cap is binding". The near-miss
journal (FW-34, shipped 2026-07-19) is the instrument that would show this, and
it has recorded a nonzero count in exactly **one run out of fourteen**; the six
earliest runs have no near-miss instrumentation at all, so the pre-cap candidate
volume for those is unrecoverable.

### 5.5 Miner — an unreviewed rubric governs the only autonomous writer

**Mechanism.** `mining-rubric.md`: one commit, zero review records, zero user
touchpoints, `rubric-version: 1` never incremented. Its exclusions (M3, M4) are
good; its four-shape taxonomy and confidence ladder are one agent's judgment from
day 5, never contested. Separately, `12 §2` still documents a *looser* reader
tool surface than the code implements (§3.11).

**Prediction.** The first serious miner quality complaint will be diagnosed as a
model problem or a digest-selection problem — the two things the corpus has
language for (`08 §4`: *"Worker prompt quality tuning… human + strong
reasoner"*) — because there is no review record, no gate, and no revision history
pointing at the rubric as a possible cause. M6, the behaviour the rubric itself
calls *"the one behavior that most damages trust"*, has never fired in 14 runs and
is entirely unmeasured.

### 5.6 GUI iterator — a contradiction inside the agent's own prompt

**Mechanism.** `compile_doctrine()` concatenates three files; the result contains
both *"A `new-skill` proposal never names the skill"* (`routing-doctrine.md:262`)
and *"`new-skill:<name>`… need[s] structure a proposal must already carry"*
(`pane-surface-model.md:60`). Obey the first and `_DEST_RE` refuses; obey the
second and you violate doctrine.

**Prediction.** In the pane this shows up as an agent that avoids `new-skill`
entirely (what has happened — 0 proposals) or emits a proposal that fails intake
with a parse error the human sees verbatim, reading as agent malfunction rather
than doctrine defect. Any reversal must move all five sites together.

### 5.7 GUI iterator — the enum silently shrinks from five to three

**Mechanism.** `PARAMETER_FREE_DESTINATIONS` bounds the `o` cycle to
`skill-md`/`claude-md`/`reference`, scope-filtered further. The comment at
`routes.py:214` is accurate and defensible for a cycling key. But nothing in the
surface tells the human that two of the five destinations exist and are reachable
only from a terminal — which the surface's own doctrine calls a defect class.

**Prediction.** The GUI's destination set becomes the *de facto* destination set.
The ledger already shows it: `reference` 14, `claude-md` 12, `skill-md` 3, `hook`
3 (all via CLI bypass), `new-skill` 0. Nobody will decide this; it will just be
true.

### 5.8 Structural — the two-gate discipline does not point at the prompts

**Mechanism.** The gates review specs and code. Across 26 review records:
`mining-rubric.md` 0, `pane-charter.md` 0, `card-sections.yaml` 0,
`routing-doctrine.md` 2. And the post-mortem established that green suites are
blind to pin defects *"because the fixtures pre-satisfy the conditions the pins
say the model must not produce"* — which the two naming-pin tests demonstrate
literally. §3.11 adds that a gate returning CLEAN shipped a merge-conflict marker
into the document it amended.

**Prediction.** Pin defects will continue to be found only by (a) the user using
the thing, or (b) an out-of-band audit — never by the gates and never by the
suite. The post-mortem's §7.1 already named the missing rule and it was never
routed:

> *"the corpus has a rule for facts and a rule for framings; it has no rule that
> says **a 'therefore' that changes an architecture is a question for the
> user**. The orchestrator proposed exactly that sentence as a lesson and the
> user has not yet routed it. On this system's own terms, that is a lesson with
> a capture and no route."*

That sentence is the single highest-value unrouted lesson in the project, and
this audit is a second, independent sighting of it.

---

## 6. Agent-authored pins that are GOOD — do not touch

Stated explicitly, because the point of this audit is not that agent-authored
pins are bad. Several of these are ones a human plausibly would not have written.

**Safety / correctness — strongest tier:**
- **G15 — `allowed_tools=[]` and `setting_sources=[]`.** Empirically grounded
  and *doc-falsifying*: a tool listed in `allowed_tools` is auto-approved
  **before** the callback runs, and the documented "default = no settings" is
  false (33,972 vs 3,027 cache tokens measured). This is exactly the fail-open
  shape that looks like a pass.
- **G16 — the adversarial render path.** Autoescape on, `html=False`, CSP
  `default-src 'none'` on every response, Pygments class-mode. The threat model
  is stated outright: unsanitized model output executes in the token-cookied
  origin, *"defeating every mutating-route control and the P1 human-gate
  invariant itself."*
- **G3 — no Bash, no Task, no web, no MCP**, structurally absent rather than
  merely unused, with the reasoning for *why* absent.
- **G4 — `Edit` on the record, never `Write`**, closing the resurrection vector.
- **G13 — bucket recheck at confirm as well as arm**, preventing a route
  compiling into a different project's canon than the bar the human read.
- **M10 — compose-before-scan ordering**, so a secret in the episode brief is
  still caught.
- **A5 — no secrets, default refuse, no bypass flag.** Its stated *rationale*
  (A4) is stale; the rule is right independently and must not be weakened while
  the rationale is corrected.
- **P1 / M-1 / A13 / G1 — the proposer is never the approver.** 32 of 32
  routings `by: human`. See §4.6 for the honest caveat about how M-1's absolutism
  compares to the user's stated goal.

**Design / integrity:**
- **New-skill collision rule (M3-9)** — refuse to append unless the target
  SKILL.md carries a self-learn managed section: *"never inject into a foreign
  authored SKILL.md."*
- **A9 — hook compile-input + replay-before-commit**, verbatim two-phase apply,
  manual settings.json registration. P9 implemented properly. It makes hooks
  expensive; that is the correct price for executable bytes.
- **A11 — the bounded contradiction check** that never claims completeness and
  never auto-writes an edge. A rare pin that correctly refuses to overclaim.
- **G12 — proposals render WAITING, never armed; refuse-not-replace.** Closed a
  race the review proved reachable, structurally rather than by suppression.
- **G14 — closed proposable verb list excluding `host add`.** The corpus
  catching itself: an agent must never widen its own read scope.
- **G17 — the one bulk operation is a graduate loop, never rejects.**
- **G6 / Y-9 / Y-10 — human-language-first, and colour never the sole carrier**
  (the user's theme is daltonized). Grounded in measured failure and in a fact
  about the actual user.
- **G9 — scope validity at intake**; **G11 — arm-then-confirm, no chords**.
- **M3 / M4 / M5 — miner exclusions.** The self-mining halt was empirically
  forced after the draft *"collapsed on the first review reply, mining every
  card's verbatim lesson text back as fake sightings."*
- **M-2 / M-3 / W1 — verb-gated landing, never load-bearing, append-only
  worker.**
- **A16 — trigger-first compile form.**
- **The `07 §4` don't-subvert contracts** — CLI owns resolution mechanics,
  `--json` on read verbs, the server never writes ledger files. The healthiest
  pin family in the corpus; it has repeatedly caught real drift.

---

## 7. Pins that ARE the user's — do not reopen

Each is listed with its evidence, and I have **split the rows where only part of
a "Settled" entry is actually the user's**. Overclaiming user provenance is as
bad an error as the reverse, so the third column says exactly what is covered.

### 7.1 Directly quoted — dispositive

| Ruling | Where | Verbatim |
|---|---|---|
| One-motion hook/new-skill gating must be configurable, not hardcoded | S-10, `03-decisions.md:21`; `08:470` | *"this is exactly the kind of thing that shouldn't be hard-coded. make it configurable."* |
| When the flag flips, it opens the gate fully (both one-motion roads) | S-10 scope ruling, `03:21` | *"when the flag flips and opens the gate, it opens it fully."* |
| Fable is never a subagent; Opus reviews, Sonnet builds | S-18, `03:30` | *"fable is too expensive for multi-agent use"* |
| Build the transcript miner now | O-3, `03:40`; `12:3` | *"build now without a shadow of a doubt"* |
| The ledger gets an independent home | S-17 / doc 13, `13:3` | *"we need an independent home for the ledger"* |
| Miner caps scale with use, start loose | `12:357` | *"a fixed 3/run is constrictive on a 12-hour day"* |
| Rejected candidates resurface on evidence (3 fresh sightings) | `12:365` | Q4 answered live |
| The miner reads every project's transcripts | `12:352` | Q2 answered live |
| Everything doable via UI; no terminal | Y-11, `09:1578` (labelled *near-verbatim*) | *"I should essentially be able to do everything I need to do via UI and not have to open a terminal."* |
| The pane agent must be able to act, not just chat | Y-13, `09:1652` | *"shouldn't just be a chat bot. if i tell it to route to a different bucket, for example, it should be able to do that"* — **see §4.6** |
| Non-blocking pane start | Y-15, `09:1750` | *"'open bucket chat' doesn't seem to do anything…"* |
| Episode briefs on mined candidates | Y-21, `09:2299` | *"should the agent that does the mining also write up a longer brief…"* |
| Plain language over jargon | `05-evidence.md:180` | *"i have no idea what you mean by a guard."* |
| The REPL is the wrong review venue | `README.md:308` | *"the REPL is definitively not the right venue for review"* |
| `git init` disclosure on UI registration | Y-17, `feedback/2026-07-18-ui-feedback-03.md:59` | quoted |
| Design round 4 parked but governing | O-9, `feedback/2026-07-18-ui-feedback-04-design.md:3` | *"can be saved for further down the road."* |
| Publication of the product repo | S-19 half, `13:410`; `drafts/public-release-spec.md:1181` | *"user ruling — publication"* |
| Resolution-evidence scope narrowing | `drafts/resolution-evidence-spec.md:169` | *"toast was more just a concept I was trying to convey, not a verbatim requirement."* |
| The A/A2 destination taxonomy (R-1…R-5, incl. *"yes, we go with path-scoped rules"*, *"agent suggest path, glob, etc. user can concur or not"*) | `drafts/a2-rules-local-spec.md:60-62` | quoted in a dedicated "Words" column |

### 7.2 Structured-mechanism decisions — unquotable but corroborated, treat as the user's

| Ruling | Where | Corroboration |
|---|---|---|
| **Platform = localhost web app; pane engine = Agent SDK; residency; DX weighting** (V1–V4) | `research/2026-07-12-adjudication-surface-problem-space.md:168-176` | *"User answers (binding — AskUserQuestion, routed before any freeze)"*; cross-cited at `README.md:245`, `reviews/2026-07-12-surface-rederivation-gates.md:145`, `09:1374` |
| **D1/D2/D3 — hosting separation; pushes are MANUAL, no autosync anywhere** | S-17, `03:29`; `13:419` | "four calls answered live"; commit `4e94dd5`; README:544 enumerates all four. **Load-bearing operating posture — reviewers must not "fix" it by adding auto-push** |
| **The four 2026-07-19 rulings** (fast-lane tier table as written; timer; precedence flip; `FAST_SWEEP_CAP=5`) | `drafts/settings-surface-spec.md:712-723`; `drafts/fast-lane-spec.md:210` | Commit `a01147e`; and `:717` records *"the user ruled AGAINST the author's recommendation"* — a pattern no agent invents |
| **Prune imported auto-memory post-decision, never in-flight** | S-13, `03:24` | "User directive 2026-07-12"; commit `0c62663` |
| **Parks: ha-note (O-7), Go port (O-8)** | `03:44-45` | Dated "(user)" parks |
| **Gaming-centric WASD keymap** | `09:84-89` | *"user-directed remap — feedback session"* |
| **The action rename `confirm`→`confirm_recurrence`** | S-20 element, `03:32` | Gate record `reviews/2026-07-24-…:237-245` shows the reviewer refusing self-authorisation and routing it: *"a spec cannot self-authorize amending ratified corpus… routed to the human and ratified 2026-07-24"* |

### 7.3 Rows whose "Settled/Ratified" status is broader than the user's actual input

Flagged so they are neither reopened casually **nor** cited as user authority.

| Row | What is the user's | What is not |
|---|---|---|
| **S-16** (doc 11 telemetry) | The **delegation** — *"review them yourself and answer the questions you would ask me"* — and **Q6** (*"i genuinely can't think of anything else"*) | **Q1–Q5 are agent self-answers** (`README.md:384-408`, verified). The row reads "Ratified" |
| **S-14 / S-15** (auto-memory importer; teach offers) | The direction | Both say *"Delegated lock-in 2026-07-12, consistent with the user's pattern"* — an agent's inference from a pattern. Commit `5c7f527` says "RATIFIED", which the row text does not support |
| **S-19** (public + FSL-1.1-MIT + CLA) | The **publication** decision (quoted) | The FSL-over-MIT choice and the CLA-over-DCO reasoning cite only *"the… option the user wishes to keep"*. Load-bearing for the public install path |
| **S-20** (in-flight perceptibility) | The action rename only (7.2) | The rest is six gate rounds + a 20,000-interleaving fuzz test. Longest row in the register, sitting visually identical to S-10 |
| **`forward/worker-ecology.md`** three-domain boundary | The fragment *"(c)-ish"* | The full boundary rule around it |

### 7.4 Open items the corpus is holding for the user — not settled pins

- **Tighten terminal `host add` (no `--init`) against paths inside a parent work
  tree?** `03:54`, `09:2039`, `14:120` — *"recorded not pinned… needs the user's
  yes/no."* Today a terminal registration on such a path registers a host whose
  canon commits land in the **parent repo**. This is a live correctness hazard,
  not a preference.
- **Widen the pane agent's canon read scope to whole host roots?** `03:54`,
  `14:121` — *"user-ratifiable and unexercised."* §4.7.
- **Raise or kill the miner caps after probation** (`12:188`); **advance the
  autonomy ladder** (`12:414`) — both require a dated register edit that does not
  exist.
- **R-1 / R-2 / FW-38** — scoped refusals under S-20, explicitly deferred pending
  measured data, correctly disclosed.

---

## 8. Operational note (not a pin)

`~/.cache/self-learn` holds **31,033** `home-<8hex>` namespace directories,
248,466 files, **1.1 GB**. The cache key is `sha256(SELF_LEARN_HOME)`
(`worker.py:113-121`); tests and scratch runs set `SELF_LEARN_HOME` without
redirecting `XDG_CACHE_HOME`, so every throwaway ledger home mints a permanent
directory in the user's real cache. Only `home-0f24de4d` is the live ledger.
Aggregate logs show ~31,939 watchdog-spawned miner runs across these namespaces,
each scanning the user's real `~/.claude/projects` transcripts. Still growing —
7,254 directories dated 2026-07-26 alone. Nothing was modified; flagging only.

---

*Audit performed read-only. `~/.self-learn` untouched, `~/.cache/self-learn`
untouched, working tree clean, no verbs run, no tests run.*
