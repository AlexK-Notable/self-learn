# DRAFT — Analyst-pass riders: proposal-time lint (Y-22) + destination-bounded contradiction check (Y-23)

**Status: DRAFT — 2026-07-18. Not gated, not built.** Owns **FW-31 (Y-22,
lint)** and **FW-32 (Y-23, contradiction)** only — the two per-record-judgment
riders of the `(c)-ish` worker-domain boundary (`forward/worker-ecology.md`
§5). FW-33/34/35/36 are out of scope here.

**Proposed final home when this graduates:** two register entries in
`09-surface-spec.md` §11 — **Y-22 (lint)** and **Y-23 (contradiction)** —
plus a one-line amendment to the worker-prompt row in `08-build-plan.md`
§7.1 (the `Prompt = …` ingredient list gains the lint rider; the
contradiction check needs **no** new prompt ingredient — see §5). This
draft pins nothing normative; it graduates through the two-gate chain like
any FW item (14 §7).

**Verification note.** Every code claim below was checked against master
2026-07-18: `worker.py` (`_digest` :483, `_canon_excerpt` :544,
`_PROMPT_TEMPLATE` :581, `_compose_prompt` :615), `verbs.py`
(`_resolve_target` :528, `surface_fill` / `SURFACE_FILL_CAPPED_DESTINATIONS`
:172/:1065), `ledger_ops.py` (`validate_proposal` :482, `_validate_card`
:358, `contradicts` validation :516–529, `proposal_info` :913),
`ui/models.py` (`build_card_sections` :244, `leading_text` :268),
`ui/routes.py` (`link-contradicts` verb map :119, post-route
contradicts-offer :1003/:1424), `card-sections.yaml`, `routing-doctrine.md`.

## 0. What already exists (the substrate — both riders are thin)

Neither rider is greenfield. Verified shipped surface both build on:

- **The `contradicts:` proposal field already exists and is validated** —
  `validate_proposal` accepts an optional non-empty list of record-id /
  canon-anchor strings (`ledger_ops.py` :516–529, per 11 §2.4, the
  `already_canon` structured-field precedent). The worker prompt already
  invites it (`_PROMPT_TEMPLATE` :587–588: "You may also propose an optional
  `contradicts:` list … when a lesson conflicts with existing canon").
- **The propose→offer→verb flow already ships.** At routing the UI reads
  `proposal.contradicts` and renders a per-target contradicts-**offer**
  (`routes.py` :1003–1008, :1424–1428); accepting it runs `link contradicts
  <record> <target>` (:119–120), which writes the `links.contradicts` edge
  (11 §2.4/§2.5). **The check PROPOSES (the flat list); the human-accepted
  edge is written by the verb at routing** — that exact flow is already the
  code path. Y-23 does not rebuild it.
- **The destination section is already in the prompt.** `_canon_excerpt`
  (:544) injects the candidate target's managed section ±20 lines (or the
  whole file when <200 lines) per record (:637–638). Managed-section entries
  compile trigger-first with a `*(lrn-…)*` provenance tag (02 §4), so the
  conflicting entry's **record id is already legible** in the excerpt.
- **The card registry is generic.** `card-sections.yaml` is the single
  source; `build_card_sections` renders every present key in `order`,
  skipping absent keys (`models.py` :244). Adding a section is an edit to the
  registry file **only** — nothing downstream is hardcoded.

**Where the contradiction instruction lives today — the gate corrected this.**
`routing-doctrine.md` contains **ZERO** contradicts guidance (grep-confirmed):
the *only* "conflicts with existing canon" instruction anywhere is
`worker.py` `_PROMPT_TEMPLATE` :586–588 — **M2's private prompt**, which the
M1 inline analysis and the G-3 pane never load. So the contradiction check is
**not** three-producer today; it is M2-only. The propose→offer→verb *back
half* (`routes.py`) is genuinely producer-agnostic and already shipping — any
producer that emits a `contradicts` list gets the offer + verb for free — but
no producer except M2 is currently told to emit one.

Consequence for scope: **Y-22 adds a structured `lint:` block + one registry
section + a lint subsection in routing-doctrine.md (the three-producer home).
Y-23 does two distinct things: (a) it NARROWS the M2-only worker-prompt line
(:586–588) from "existing canon" (canon-wide, hallucination-prone) to the
destination section already shown; and (b) it ADDS a new bounded-contradiction
subsection to routing-doctrine.md — that addition is what FIRST makes
front-half detection three-producer (M1 inline + M2 + pane), matching the
already-agnostic back half.**

## 1. Y-22 — Proposal-time lint (FW-31)

**What the analyst evaluates** (behavior records only — knowledge records
carry `## Fact`/`## Context`, no firing moment to recognize; the block is
omitted for them):

1. **Trigger recognizability** — would a fresh session, cold, recognize the
   firing moment from the `## Trigger` alone? (routing-doctrine §6: concrete
   artifacts — paths, commands, tool names — beat abstractions.)
2. **Why-clause presence** — does `## Instruction` carry the *why* on its
   first line (the compiler takes only that line, 02 §4), not a bare
   imperative?

**Output shape IN the proposal yaml — a structured block, counted-not-modeled
(worker-ecology §4.3):**

```yaml
lint:                              # optional; behavior records only
  trigger_recognizable: partial    # enum: yes | partial | no
  why_present: true                # bool
  sharpening: "name the .storage/*.json glob, not 'HA files'"  # optional string
```

- **Verdicts are binary/enum, never a numeric score** — no 0–10, no
  confidence float; the constitution forbids modeled metrics that n=1 cannot
  earn (14 §6; worker-ecology §4.3). `sharpening` is a single concrete
  rewrite suggestion, prose, optional — never a graded quantity.
- The block is authoritative for the verdicts; the card line (below) is its
  plain-words rendering — the `already_canon` / `already_canon_reason`
  pattern (structured truth + human render), moved into the registry.

- **Decision — the block ships now, and its consumer is named (gate F3).**
  Unlike `already_canon`, no *routing* action reads `lint:` at ship time — the
  human decides in prose off the card. It is nonetheless shipped as the
  structured field now, as **counting substrate for the FW-33 portfolio
  auditor**, whose receipts digest is the one honest named reader:
  counted-not-modeled aggregation over `trigger_recognizable` /
  `why_present` verdicts ("N pending behavior records read trigger-fuzzy this
  month") is exactly the class-level, score-free count worker-ecology §3/§4.3
  reserves for the auditor's briefs. Structure-now / count-later is cheaper
  than a later schema migration once briefs exist, and the block costs a
  validator branch and tens of output tokens (§5). The alternate — ship only
  the `lint` card section and defer the block until FW-33 is spec'd — was
  weighed and **rejected**: burying the verdicts in card prose would force the
  auditor to parse them back out, the exact anti-pattern the `already_canon` /
  `contradicts` structured-field precedents exist to forbid (11 §2.4). The
  block is inert (no consumer) until FW-33 lands; that is an accepted,
  named-reader deferral, not an orphan field.

**How the card renders it.** `card-sections.yaml` gains a **`lint`** section
(§6), ordered **after `discuss`** so it never becomes the Y-9 leading line
(`leading_text` uses `cards[0]` = `headline` at order 10). Rendered
generically, in plain words (Y-9): e.g. *"A fresh session might not catch
when this fires — the trigger says 'HA files', not the actual `.storage`
path. Consider naming the path before routing."* The analyst writes the
section text consistently with the structured verdicts.

**Kind-aware posture (pinned MUST).** Lint **never rejects** a record, and
in particular **never treats inherent trigger fuzziness of a
`kind: reasoning-pattern` lesson as a defect.** Reasoning-pattern behaviors
legitimately route to prose (routing-doctrine §2) and legitimately have
softer triggers than an anti-pattern hook. For such records the lint may
still offer a `sharpening`, but the card framing is non-punitive and
`trigger_recognizable: partial` on a reasoning-pattern record is **not** a
route-blocker signal. The doctrine text (§7) must state this explicitly.

**What lint NEVER does (MUSTs):**
- never blocks or gates routing (advisory only; a record with
  `trigger_recognizable: no` still routes on the human's word);
- never auto-edits the record — the record body is the human's (S-8
  freeze; routing-doctrine §7). Lint *suggests* a sharpening; the human may
  apply it on the Discuss/pane edit path, scanned at the
  `proposal validate` checkpoint (02 §2);
- never rejects reasoning-pattern lessons for soft triggers (above).

**M2 fast-path / one-schema interaction.** Lint rides the M2 worker's
proposal pass. The M1 **inline-analysis fallback inside `/self-learn:review`**
(routing-doctrine's three co-loaders: M1 inline, M2 worker, G-3 pane) writes
the **same** `lint:` block and the same card section — **one schema, three
producers**, exactly as routing/card sections are shared today. No producer
forks the shape.

**Instruction-placement MUST (protects the three-producer invariant).** The
lint judgment rules **MUST live in `routing-doctrine.md`** — the one file all
three producers load, the same channel card-section instructions already ride.
The M2 `_PROMPT_TEMPLATE` may carry **at most a one-line pointer** to them and
**MUST NOT** carry the rules themselves. This is not a stylistic preference: if
a builder puts the rules in the template (M2's private prompt), M1 inline and
the pane silently stop linting and the one-schema/three-producer claim breaks
with no test failing. The rules-in-doctrine placement is the mechanism that
makes "three producers" true, exactly as it already is for the card registry.

## 2. Y-23 — Destination-bounded contradiction check (FW-32)

**Scope (the whole point of the rider).** The check considers **ONLY the
destination section's current entries** — the `*(lrn-…)*` managed-section
lines already shown in that record's **`_canon_excerpt`** block
(`worker.py` :637–638). It does **not** scan canon-wide; **canon-wide
detection stays G-5-gated** (vector/retrieval, 14 §6). Two edits carry this
scope, and they touch different files (there is **no** contradicts guidance in
`routing-doctrine.md` today to narrow — §0): (a) the M2-only `_PROMPT_TEMPLATE`
line :586–588 is **narrowed** from "existing canon" to "an entry in the
destination section shown in the candidate-target excerpt"; and (b) a **new**
bounded-contradiction subsection is **added** to `routing-doctrine.md` so M1
inline and the pane emit the same bounded suspicion (§7).

**The bounded read — exact reuse, no new parser.** The destination section
text is already in the prompt via `_canon_excerpt`. Where a spec/build ever
needs a cleaner section-only read than the ±20-line excerpt, it reuses the
Y-20 read-only path — `verbs._resolve_target(…, check_dirty=False)` +
`compilers.compile_managed_text` (the `surface_fill` precedent, `verbs.py`
:1065–1150, scope `SURFACE_FILL_CAPPED_DESTINATIONS = ("skill-md",
"claude-md")`) — **never a second parser** (worker-ecology §6). Only the two
capped managed-section destinations carry a contradiction check; `reference`
is append-only and cap-free and is not contradiction-checked (the
`surface_fill` F1 exclusion applies identically).

**Output shape.** The machine field is the **existing** `contradicts: [<id or
anchor>, …]` list (unchanged — it is the `link contradicts` verb's input, and
restructuring it would break `routes.py` :119/:1003/:1424 and 11 §2.4). The
human-facing triple — **target record id + the conflicting text span + a
one-line reason** — is authored into a new **`conflict`** card section (§6),
in plain words that lead with the domestic gloss and demote the record id to
a footer per doctrine §8: *"This may clash with a rule you already kept —
'never restart Home Assistant mid-flash' tells Claude to leave the container
running, but this lesson tells it to stop the container first. (near:
'…rewrites .storage on shutdown…'; lrn-77ab01cd.)"* When more than one target
is suspected, the card names each in prose; the flat `contradicts` list
carries the machine targets.

**Relationship to the edge (cite the exact flow).** The analyst's
`contradicts` list is a **proposal** — a suspicion. At routing the UI renders
it as a dismissible post-route **contradicts-offer** (`routes.py` :1003,
:1424); the human clicks to apply, which runs **`link contradicts <record>
<target>`** (:119–120), and only then is the `links.contradicts` edge written
to the record (11 §2.4/§2.5). Proposer ≠ approver (worker-ecology §4.1): the
check never writes an edge.

**False-positive posture (MUSTs):** advisory, dismissible, **never blocks**
routing and never auto-writes an edge. A suspected contradiction the human
dismisses simply leaves no edge. The check is false-negative-tolerant by
construction (it sees only one bounded section) and must **never claim
completeness** — no "no contradictions found" assertion, only positive
suspicions.

## 3. Schema-validation posture (decided and pinned)

**Accept-and-shape-check when present; never require.** This mirrors the
whole proposal schema (card, `already_canon`, `contradicts`, alternates are
all optional + shape-checked, `ledger_ops.py` :482–530). Specifically:

- `lint` is **optional**. When present: must be a mapping;
  `trigger_recognizable` ∈ {`yes`,`partial`,`no`}; `why_present` a bool;
  `sharpening` (if present) a non-empty string. A malformed `lint` block is a
  `ProposalError` (same class as every other shape failure) — but its
  **absence is always valid** (a proposal without lint, e.g. a knowledge
  record or a degraded run, passes). New validation lives in a
  `_validate_lint(data)` helper called from `validate_proposal`, symmetric
  with `_validate_hook_extension`.
- `contradicts` is **already validated** (:516–529) — **no change**.
- The `lint` and `conflict` **card sections need no bespoke validation**:
  `_validate_card` already shape-checks every card key generically (non-empty
  str → non-empty str). Registering the keys in `card-sections.yaml` is the
  only card-side change.
- The M1 `proposal validate` verb (08 §7.1) picks up the new `_validate_lint`
  through `validate_proposal` unchanged; exit codes and the secret scan over
  the full sibling text (which already covers `sharpening`/card prose) are
  untouched.

## 4. Degradation legs (mirror Y-20 F5 — never a zero, never a guess)

- **Excerpt/resolver refusal → no contradiction check, key omitted.**
  `_canon_excerpt` already returns a sentinel string ("(… unresolvable)",
  "(target … does not exist yet)") on an unresolved/absent target; the
  analyst then has no section to check and **omits `contradicts` and the
  `conflict` card section entirely** (Y-20 F5 posture: omit, never emit an
  empty edge or a guessed target).
- **Lint prompt failure → proposal still valid without lint fields.** If the
  model omits `lint:` (prompt truncation, a non-behavior record, a run that
  drops the rider), `validate_proposal` passes and the card shows no lint
  line. Lint never being present is a supported state, not an error.
- **A managed section that HAS entries always renders whole — there is no
  "oversized section" degradation for it** (gate F4 correction). Reading
  `_canon_excerpt` (:566–578) precisely: a <200-line target returns the whole
  file; a ≥200-line target **with** markers returns the section ±20 lines
  **entire** — a section is never line-truncated. The only truncation
  (`lines[:60] + "… (truncated)"`, :575–576) fires when a target is **≥200
  lines AND marker-less** — i.e. a large hand-authored file that has **no
  managed section yet**. That case has no `*(lrn-…)*` entries to contradict, so
  it folds into the bootstrap leg below: no section → no suspicion. No
  builder should treat the 60-line clip as an entry-loss risk for a real
  section.
- **Bootstrap / marker-less target** (empty target, target not yet on disk, or
  the ≥200-line marker-less case above) reads as an empty section (0
  entries): no entry to contradict → no `contradicts`, no `conflict` card.

## 5. Cost accounting (prompt-token delta, bounded)

- **Y-23 per-record delta ≈ 0; per-run delta small and fixed.** The
  destination section is *already* injected per record via
  `_canon_excerpt`; the check reuses it. Y-23 narrows the
  worker-prompt line (net-neutral) and ADDS a small shared per-run
  doctrine subsection — bounded exactly like Y-22's block below.
  *(Delta-review residual folded at merge with the reviewer's
  wording, 2026-07-18.)*
- **Y-22 adds a fixed, batch-shared instruction block.** Per the §1 placement
  MUST, the lint judgment rules live in `routing-doctrine.md` (loaded once into
  `{doctrine}`, shared by all three producers); `_PROMPT_TEMPLATE` carries at
  most a one-line pointer. Either way this is a **per-run** addition
  (~200–400 tokens), **not per-record** (the template is shared across the
  ≤15-record batch, `_compose_prompt` :615). Output grows by the `lint:` block
  + two short card sections per behavior record (tens of tokens each).
- **Bound (MUST hold):** the prompt-assembly delta is O(1) in batch size —
  a fixed doctrine/template addition, independent of the record count. No new
  git, network, or model round-trips; the Y-20 read-only resolver (if ever
  used for a cleaner section read) is memoized per resolved target-path
  exactly as `surface_fill` is (:1104–1108).

## 6. Card registry additions + composition posture

Two sections added to `card-sections.yaml`, ordered **after `discuss`
(40)** so neither can hijack the Y-9 leading line:

- **`lint`** — order ~50, `required: optional`. `label` in plain words
  (e.g. *"Would a fresh session catch this?"*). `instruction`: render the
  recognizability + why-clause judgment as one or two plain sentences, name
  the concrete sharpening if any; never a score; for a reasoning-pattern
  record, frame a soft trigger as expected, not as a fault.
- **`conflict`** — order ~55, `required: optional`. `label` in plain words,
  **no jargon** (gate F5): e.g. *"May clash with a rule you already kept"* —
  never "canon"/"contradiction"/an enum. `instruction`: lead with the domestic
  gloss of the clash, name the suspected target in everyday terms, quote the
  shortest conflicting span, give a one-line reason, and demote the record id
  to a footer (doctrine §8); state it as a suspicion to dismiss, never a
  verdict.

**Composition statement (FW-19 / ui-ux §4 convention, satisfied).** These are
**card sections inside the existing card region**, not new Detail regions —
the Detail page's five-region count (finding/brief/budget-Why/proposals/pane)
is **unchanged**. Both sections render low in the card block, below the
decision-driving `headline`/`impact`/`discuss`, so they add detail without
competing for visual weight. No page-level region is introduced; the
round-4 composition debt does not grow.

## 7. Amendments this rider proposes (authored at build, not here)

- **`routing-doctrine.md`** — the analyst's single source, loaded by all three
  producers. Two **additions** (there is no contradicts guidance here today to
  narrow — §0): (i) a lint subsection carrying the two lint judgments + the
  kind-aware non-punitive posture — this is where the rules MUST live (§1
  placement MUST); (ii) a bounded-contradiction subsection: "flag conflicts
  only with the destination section's current entries, shown in the
  candidate-target excerpt — no canon-wide scan (G-5-gated)". Adding (ii) is
  what first makes front-half contradiction detection three-producer.
- **`worker.py` `_PROMPT_TEMPLATE`** — **narrow** the :586–588 `contradicts`
  line from "existing canon" to the bounded scope; the lint change here is
  **at most a one-line pointer** to the doctrine subsection — the rules
  themselves MUST NOT be added to the template (§1 placement MUST).
- **`card-sections.yaml`** — the two sections in §6.
- **`08-build-plan.md` §7.1** — one line on the prompt row: lint rider is a
  fixed doctrine addition; contradiction reuses the existing canon excerpt
  (no new ingredient).
- **`ledger_ops.py`** — `_validate_lint` helper wired into
  `validate_proposal`.

## 8. Test obligations + DoD

- **Validator:** proposal with a well-formed `lint:` block validates; each
  malformed field (enum out of set; non-bool `why_present`; empty/non-string
  `sharpening`) raises `ProposalError`; a proposal **without** `lint`
  validates (optional); `contradicts` behavior unchanged (regression guard).
- **Card render:** a proposal carrying `lint` + `conflict` sections renders
  both, in registry order, after `discuss`; `leading_text` still returns
  `headline` (Y-9 leading line unaffected).
- **One-schema:** a shared fixture asserts the M1 inline path and the M2
  worker emit the same `lint:` shape (no fork).
- **Placement invariant (§1 MUST):** a test asserts the lint judgment rules
  live in `routing-doctrine.md` and that `_PROMPT_TEMPLATE` carries no more
  than a pointer — e.g. the lint rule text appears in the shipped doctrine
  file and NOT inline in `_PROMPT_TEMPLATE`; guards the silent
  three-producer-break failure mode.
- **Degradation:** an unresolvable/`(target … does not exist)` excerpt yields
  a proposal with **no** `contradicts` and **no** `conflict` card, and does
  not crash the run or the `list --json` Detail paint.
- **Kind-aware:** doctrine text asserts the reasoning-pattern non-punitive
  clause is present (prompt-level check); a reasoning-pattern fixture with a
  soft trigger is **not** flagged as reject-worthy.
- **Contradiction flow (regression):** a proposal with a `contradicts`
  target still renders the post-route offer and still routes through
  `link contradicts` to write `links.contradicts` (the existing flow is not
  disturbed).
- **DoD:** two-gate blind review (spec gate → build gate); a live worker run
  on a real behavior record emitting a `lint:` block + card section, and a
  live contradiction suspicion rendering + being applied as an edge via the
  offer; DoD walk logged in `fixtures/ui-trials.md`.

## 9. Non-goals

- No numeric/confidence score, ever (counted-not-modeled).
- No blocking, gating, or auto-editing the record; no rejection of any record
  by lint (esp. no reasoning-pattern rejection for soft triggers).
- No canon-wide contradiction detection (G-5-gated); the check is
  destination-section-bounded.
- No new resolver/parser — reuse `_canon_excerpt` and, if needed, the Y-20
  `_resolve_target(check_dirty=False)` + `compile_managed_text` path.
- No restructuring of the flat `contradicts` list (it is the `link
  contradicts` verb input); the span/reason live in the `conflict` card.
- No auto-application of contradiction edges — the human applies them via
  `link contradicts` at routing (proposer ≠ approver).
- No new Detail page region (card sections only).
- Not FW-33/34/35/36 (the auditor, near-miss, fast-lane, ecology channels).
