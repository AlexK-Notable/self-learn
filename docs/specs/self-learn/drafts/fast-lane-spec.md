# FW-35 — The review fast lane, stakes-tiered by destination

**DRAFT · 2026-07-18 · spec-author task · owns register entry Y-25 only.**
Proposed final home: **09 §11 entry Y-25** (surface register) + a
**review-skill amendment** (`plugins/self-learn/commands/review.md` — a
fast-lane clause beside the existing bulk-acknowledge block, since the
slash command and the web surface share the same CLI substrate, S-2). This
draft is build-grade for both landing sites; it pins nothing normative
until folded. Verified against master 2026-07-18: `verbs.py`
(`_resolve_target`, `PROPOSAL_DESTINATIONS`, `SURFACE_FILL_CAPPED_
DESTINATIONS = ("skill-md","claude-md")`, `ONE_MOTION_UNROUTABLE =
{"new-skill","hook"}`), `routes.py` (`bucket_page`, the action-bar
route/graduate quad, `read_proposal_raw`/`proposals_by_id` at `:367-371`,
`envelope_bulk_progress`), `ledger_ops.py` (`proposal_info`/`list_items`
`:913-1027`, `sha_anchor` at `:939`), `config.py` (S-10 fail-closed idiom
`:80-106`), `keymap.py` (`drill_in` `:60`, global-key-uniqueness),
`telemetry.py` (`EVENT_KINDS` closed set, `card-shown`/`card-decided`).
**Blind-gate round 1 folded (F1–F6 + builder warning), 2026-07-18;** F4
is a live RULING REQUIRED box (§2) for the human at the spec gate.

## 0. What this is, and the one direction it must be paranoid in

The human gate is the system's **central empirical commitment** (P1;
E-18: automatic consolidation degrades *below* the no-memory baseline —
the curation loop decides the sign). The fast lane makes low-stakes
routing cheaper. That is precisely the feature whose **letter can survive
while its spirit erodes**: every fast route is still an explicit human
verb (P1's letter intact), yet a habituated sweep of unread rows is a
gate in name only (P1's spirit gone). This spec is built to make that
erosion **structurally hard and empirically visible**, not to trust that
it won't happen.

Two load-bearing charter pins (14 §2 FW-35; worker-ecology §5):
- **Tiering is by DESTINATION, a fact — never by a model's confidence
  opinion.** Destination is what `_resolve_target` already computes from
  the record; no score, no bucket, no analyst verdict enters the tier
  decision. (Non-goal §8: no confidence scores anywhere.)
- **`hook` and user-scope `claude-md` NEVER qualify. Invariant, not a
  default.** No config, ladder step, or override can promote them.

This is **not worker work** (worker-ecology §5): UI/CLI stakes tiering
only. It *consumes* FW-31's lint flag and the existing contradiction
edge; it builds no analyst change.

## 1. The tier table (destination → tier, reason = a reversibility/blast-radius fact)

| Destination | Tier | The fact that fixes the tier |
|---|---|---|
| `reference` / `reference:<file>` | **FAST** — archetype | Append to `references/LEARNINGS.md` (or a named existing reference). **Unloaded surface** — progressive disclosure, read only when a human opens the file; affects **zero activations** until then. **Cap-free** — it is the overflow sink the cap graduates *into* (02 §4; `compile_reference` has no `_compile_set`). Reversal = delete the line + recompile, git-revertible. Lowest blast radius in the system. |
| `skill-md` | **FULL** | Loads at **every activation** of the owning skill. Consumes the **capped attention budget** (10 entries / ~150 words; E-6: ≥60% of preloaded content is dilution). The real decision here is the narrowest-surface tiebreak (routing-doctrine §3) — a judgment, not an append. Reversible via graduate/supersede, but it touches a *loaded* surface, so full ceremony. |
| `claude-md` (project) | **FULL** | Loads at **session start for every session in the project**, cross-skill. Broader loaded surface than `skill-md`. Git-revertible, but the blast radius spans a whole repo's sessions. |
| `claude-md` (user, `~/.claude/CLAUDE.md`) | **NEVER — invariant** | Loads in **every session of every project** — the most expensive surface in the system (routing-doctrine §3) — and is **chezmoi-managed**, so a route propagates across machines. Never fast, by charter. |
| `new-skill` | **FULL** | Creates a **new loadable surface + directory structure** (M3 compiler); the human-named skill slot is a judgment, not an append. In `ONE_MOTION_UNROUTABLE` for the same reason. |
| `hook` | **NEVER — invariant** | **Executable code.** P9: eyes on the *exact bytes*, never a summary (M3 verbatim two-phase apply). The one place gen-1's source-trust caution still binds. No fast path can ever exist. |

**The honest middle-case argument.** `skill-md` and `claude-md`-project
are reversible and scoped — a plausible fast case. They are held to full
ceremony anyway because **loaded surface is the one scarce resource the
whole system rations** (P2/E-6), and the fast lane's one-line card cannot
carry the narrowest-surface comparison (Y-20's budget) that *is* the
decision. When in doubt, full ceremony — and here we are in doubt, so
they stay. This matches the staged-autonomy ladder's own gradient (12 A2:
L2 = reference/unloaded; L3 = loaded canon, human-gated longest).

*The narrowest-surface tiebreak cited above is
`plugins/self-learn/skills/self-learn/references/routing-doctrine.md`,
heading **§3 "The narrowest-surface bias (the one standing tiebreak)."***

## 2. The fast-lane interaction

**Where it renders — no new surface, no new region.** The fast lane is a
**rendering treatment of the existing Bucket-page `reference` destination
group** (09 §2.2, records grouped by `proposal.destination`), parallel to
the already-canon **bulk-collapse** row that already lives there. It adds
**no Detail region** and **no page** (satisfying the ui-ux §4 / FW-19
composition tripwire: the fast lane sits in the Bucket page's existing
rhythm as the `reference` group's collapsed one-line-per-row treatment).

**What a fast card shows — one row per record:**
1. **The ONE human line** — the proposal's leading `card:` section in
   registry order, plain words (Y-9); the same line the Bucket row leads
   with today. **Never an id as the label** (the `lrn-…` rides as
   trailing metadata).
2. **The destination** — `reference` or `reference:<file>`.
3. **The honesty note** (once, at the group head): the compiler
   regenerates from the record at apply time (02 §4).

**Action shape — multiSelect sweep, per-item affirmative (bulk-acknowledge
precedent, hardened).** The group is one multiSelect card (S-2's bulk
mechanism; the review skill's bulk-acknowledge block). The paranoid pins
that keep the *spirit* of P1 (each of these is a build obligation, not a
nicety):
- **No pre-selection. No "select-all" affordance in v1.** Every row is
  unchecked; selecting a row is an explicit per-record act. The speedup
  is *compressing three Detail regions to one line*, **not** approving
  unread rows in bulk. (A select-all is a possible later affordance —
  §3 gates it on audit evidence, never ships it by default.)
- Each selected record resolves via **its own pinned `route <id>` verb**,
  looped (09 §2.2 pin: individual pinned verbs, SSE per-item progress via
  `envelope_bulk_progress`, mid-loop failure stops on the failing id).
  **The server never invents a bulk CLI surface.**
- The confirm **names the count** ("route 4 selected to reference").

> **Builder warning (do not copy the template blindly).** The
> bulk-acknowledge precedent this multiSelect is modeled on
> **PRE-SELECTS its rows** (the review skill's already-canon card). The
> fast lane **deliberately inverts that** to **no pre-selection** — a
> builder cloning the bulk-acknowledge template MUST flip the default
> from all-checked to none-checked. This is the single most important
> line for whoever builds it: the inversion is the spirit-of-P1 guard,
> not a detail.

**What ALWAYS remains (P1 letter AND spirit):** the human's explicit act
**per record** — N selections + one confirm = N explicit human decisions.
**No auto-anything.** The fast lane is never an auto-route; it is a
cheaper *manual* route.

**Escalation to full ceremony — one keystroke, plus five automatic
triggers.**
- **Manual:** promoting a fast row to its full Detail page (finding /
  change / why; Iterate available) reuses the **existing `drill_in`
  action** (`Enter`/`d`/`ArrowRight`, `keymap.py:60`) — a fast row *is* a
  Bucket-page row, and drilling into it already opens Detail; no new
  binding needed. **If** the multiSelect claims `Enter` for row-toggle
  (a build finding to resolve at implementation), register a dedicated
  `escalate_fast` action against `keymap.py`'s KEYMAP under its
  global-key-uniqueness invariant (tested; an unbound key — `b`/`p`/`y`
  were the last three added this way) rather than overloading a bound
  one. The action name is pinned here; the exact key is a build call the
  registry owns. Always present.
- **Automatic (a RED-FLAG or SAFETY condition forcibly removes the record
  from the fast lane; it can then only be resolved through full Detail).**
  The exact field classes and their absent-semantics are pinned in §5 —
  this list names the triggers; §5 is the normative predicate.
  1. **Contradiction-suspect present** — the proposal carries a
     `contradicts:` field (FW-32). **This is NOT a `list --json` field**
     — it lives in the proposal YAML, read at Bucket render via the
     existing `read_proposal_raw` → `proposals_by_id` path
     (`routes.py:367-371`), never a new parser. A conflict needs the full
     *why*. (Red-flag class: absent ⇒ trigger does not fire.)
  2. **Lint red flag** — FW-31's trigger/why lint failed. The proposal's
     own recognizability is in question. **This field does not exist
     until FW-31 ships** — until then the trigger is dormant, not
     fail-closed (§5). (Red-flag class.)
  3. **Over-cap destination** — the destination's managed section is at
     its cap (02 §4). **Structurally unreachable for the v1 fast tier**
     (`reference` is cap-free; `SURFACE_FILL_CAPPED_DESTINATIONS` excludes
     it). Pinned as a **latent guard** with an honest forward-compat cost:
     the over-cap *predicate* is pre-wired, but the fill datum it reads
     (`surface_fill`, 08 §1) is **Detail-only by the Y-20 F4 posture,
     which forbids a Bucket-altitude fill request**. So a future ladder
     step that ever admits a capped destination to the fast lane must
     **also wire a Bucket-level fill feed** — work today's posture
     prohibits. The guard exists; its data feed does not, and cannot until
     that posture is deliberately reopened. (Safety class *when reachable*.)
  4. **`already_canon` set** (`list --json` safety field) — the right
     resolution is *graduate*, not *route*; the record belongs to the
     bulk-acknowledge (graduation) path, never the fast-route lane.
  5. **Stale proposal** (`proposal_fresh` false — `list --json` safety
     field) — the one-line card would be derived from a stale proposal.
     Detail's Iterate regenerates first.
- **Destination override is not a fast-lane act.** The fast lane routes
  *only* to the record's fast-eligible destination as proposed. Any
  `--dest` to a full-ceremony destination requires escalating to Detail
  first — you cannot fast-lane your way into `skill-md`.
- **TOCTOU pin (freshness re-checked by the VERB, not trusted from
  render).** Render-time filtering places a record in the fast lane; the
  confirm may land seconds later. The enforcement lives in the CLI:
  **`route()` extends its `record_sha` freshness re-check — today
  hook-only — to `reference` destinations when invoked from the fast
  lane** (same mechanism, same `sha_anchor` the proposal carries;
  mismatch = a clean verb refusal, which the server renders as
  escalate-to-Detail, never a route). The server's render-time filter
  remains a pure optimization that derives nothing authoritative — so
  §5's "the server derives nothing" stays literally true, mirroring the
  hook precedent instead of inventing a server-side authority.
  *(Delta-review reconciliation, 2026-07-18 — the reviewer's preferred
  option; the earlier draft's server-side re-derivation contradicted
  the enforcer doctrine.)*

> ### ⚖️ RULING REQUIRED (values question — do NOT resolve in the build)
>
> **The residual erosion risk the interaction pins do not fully close.**
> The no-pre-selection / no-select-all pins (§2) force an affirmative tick
> per record, but a **habituated user can still tick N one-liners in a few
> seconds** without reading them. The spec's remaining defense is *soft* —
> one-line-per-row (you at least see the line) + `reference`'s genuinely
> low stakes + the monthly spot-check (§3) + the kill-switch (§8). Whether
> that is enough is a **values call about the P1 gate's spirit**, and it
> belongs to the human, not the builder or this author. Two hardening
> options, presented neutrally:
>
> - **(A) Per-sweep count cap** — a fast sweep may route at most *k*
>   records at once (e.g. 3–5); more requires a second sweep or Detail.
>   Bounds blind velocity directly; costs friction on legitimately large
>   reference batches (import backfills).
> - **(B) Minimum dwell** — the confirm is inert until the card has been
>   on screen for *t* seconds (or until the user has scrolled the list),
>   forcing a pause proportional to the batch. Bounds reflex-approval
>   without capping volume; adds latency the attentive user also pays and
>   can feel patronizing.
>
> Neither is in v1 unless the human rules it in. **Do NOT pick one during
> the build** — surface this box to the user at the spec gate; ratify or
> defer explicitly. (If deferred, the audit loop is the safety net that
> makes deferral tolerable — it catches the erosion after the fact rather
> than preventing it.)

## 3. The audit loop (the retroactive gate)

**Cadence: monthly**, aligned with the report/telemetry month-file
granularity (11 §4) and the auditor's ~monthly position (worker-ecology
§2). At the first review session of a new month in which ≥1 record was
fast-laned, the surface opens with a **spot-check card**:

> "**N records were fast-laned last month. Review 3, chosen at random.**"

The 3 are re-opened as **full Detail pages** — retroactive full ceremony
on a random sample. The human either affirms the past route or overturns
it (reject / supersede / graduate-away).

**What a failed spot-check does (pinned, justified):**
- **Always: logged distinctly** — a `card-decided` with `spot_check:
  true` and the retrospective decision (§4). This is the evidence the
  whole feature exists to produce: fast-lane **error rate**, not just
  accept rate.
- **A single failure is count-only.** It demotes nothing. **Tiers are
  spec-pinned, not runtime state — there is nothing to demote** (§8
  non-goal). And at ~1 durable lesson/month (P7: scale honestly), one
  miss in a sample of 3 is within noise; building an auto-demotion off it
  would be a mechanism whose signal needs volume this deployment lacks.
- **A threshold breach raises a suspend *proposal*, human-gated, never
  automatic.** ≥2 of 3 spot-checks failing in a month (the concrete v1
  line) raises a standing card proposing the human **flip the fast lane
  off** (§8's committed-config kill-switch). The card copy, verbatim
  (Y-9 plain words, no jargon, no counts-as-verdict framing):

  > **The quick-approve lane may be letting mistakes through.**
  > Last month, N of the 3 quick-approved lessons you re-checked would
  > not have been approved on a full look. Turn the quick-approve lane
  > off? You can turn it back on any time. — **[Turn it off] [Keep it
  > on] [Show me those N]**

  (N is the actual failed count, 2 or 3 — the template must interpolate
  it, never hardcode "2"; a 3-of-3 month must not misstate the count.
  *Delta-review nit folded 2026-07-18.*)

  The system **never demotes its own tier or disables its own gate
  silently** — that would be an autonomous policy change, and the
  community constitution (worker-ecology §4, rule 1: *"Workers inform
  proposals; only the human amends the constitution"*) reserves amendment
  to the human. Proposer ≠ approver, at feature level.

## 4. Evidence duty (feed the ladder, don't preempt it)

Fast-lane decisions log through the **existing** `card-shown` /
`card-decided` kinds — **no new event kind** (`EVENT_KINDS` is a closed
set; extending it is a schema version bump, P7) and **no new plane** (11
§4 actor-scoped observation plane, `telemetry.py`). New **scalar payload
fields** (allowed — `spool_event` takes `**payload`; only new *kinds* are
version bumps; content stays counts/enums only, §4.4):
- `lane: "fast" | "full"` — which venue rendered/decided the card.
- `escalated: bool` — did the record leave the fast lane (trigger or
  keystroke) before decision.
- `spot_check: bool` — this decision is a monthly retro-review.

The existing `card-decided` payload already carries `recommendation,
decision, overridden, dest-delta`; these ride alongside. `report` and the
future auditor (FW-33) can then compute **accept / reject / spot-check-fail
counts by destination-lane**, giving the **12 A2 staged-autonomy ladder**
real per-destination evidence for its **L2 step** (auto-route reference,
unloaded, cheap revert) — the fast lane is L2's human-kept-in-loop
predecessor and its evidence generator.

**The confidence tension, resolved.** The A2 ladder tracks accept rate by
kind × scope × **confidence bucket** × rubric version. FW-35 contributes
**only the destination-lane axis and its counts** — it neither emits nor
reads any confidence score (charter; §8 non-goal). The ladder's
confidence axis is separate machinery FW-35 does not touch.

## 5. The eligibility predicate + degradation legs (the normative MUST)

A record is **fast-eligible** iff **every SAFETY field is present and
clears** AND **no RED-FLAG field is present-and-tripped**. The two classes
have **opposite absent-semantics** — conflating them is the F1 bug this
section exists to kill.

**Class A — SAFETY fields. Absence ⇒ NOT fast-eligible (fail-closed).**
These are real `list --json` fields, surfaced by `ledger_ops.proposal_info`
/ `list_items` (`ledger_ops.py:913-1027`); each MUST be present *and* hold
the eligible value:

| Field | Source | Eligible value | Absent/other ⇒ |
|---|---|---|---|
| `has_proposal` | `list --json` | `true` | not eligible |
| `proposal_fresh` | `list --json` (`sha_anchor` at `:939`) | `true` | not eligible |
| `destination` | `list --json` | `reference` / `reference:<file>` (the fast tier, §1) | not eligible |
| `already_canon` | `list --json` | `false` | `true` ⇒ escalate to graduation path (§2 trigger 4) |

The rule that makes this fail-closed is the §2.1 CLI-is-enforcer /
missing-field posture: **the server derives nothing**; an **absent or
non-`true`** safety field means **not fast-eligible → full ceremony**, the
safe direction. A no-proposal record (slash-review era, no worker) fails
`has_proposal` and therefore has no fast lane until a proposal exists —
correct, and it lands on Detail's "no analysis yet — `i` to analyze".

**Class B — RED-FLAG fields. Absence ⇒ trigger simply does not fire; the
record STAYS eligible.** These are *escalation* signals, not eligibility
prerequisites — a missing red flag is the *normal* case, not a fault:

| Field | Source | Present-and-tripped ⇒ | Absent ⇒ |
|---|---|---|---|
| `contradicts` | **proposal YAML**, read at Bucket render via `read_proposal_raw`/`proposals_by_id` (`routes.py:367-371`) — **not** a `list --json` field | escalate (§2 trigger 1) | stays eligible |
| lint flag | **does not exist until FW-31 ships** | escalate (§2 trigger 2) | stays eligible (dormant) |

**FW-35 may ship before FW-31.** Until FW-31, the lint red flag is
**dormant, not fail-closed** — no flag emitted means the trigger never
fires, and the record stays eligible. This is correct because a missing
lint does not make a *reference append* dangerous; it makes the proposal's
trigger possibly unrecognizable — a quality miss the monthly spot-check
(§3) catches retroactively. Failing this class closed would wrongly gate
the whole fast lane on an unbuilt feature.

**The build obligation, stated once:** the eligibility function reads
Class A from the `list --json` item and Class B from the render-time
proposal read (`proposals_by_id`), applies the opposite absent-semantics
above, and — for `proposal_fresh` specifically — is **re-confirmed at the
route call site** per §2's TOCTOU pin (render-time membership is
necessary but not sufficient).

**Other degradation legs:**
- **M2 fast-path record** (`has_proposal` + `proposal_fresh`, usually the
  worker's output) — the fast lane's natural input; the one-line card.
- **Unreadable record** (09 §5) — never enters the fast lane; shows its
  unreadable row on Detail.

## 6. Composition statement (ui-ux §4 / FW-19 pre-work)

The fast lane adds **no Detail region and no page**. It is the Bucket
page's existing `reference` destination group, rendered as a hardened
multiSelect (parallel to the already-canon bulk-collapse already there).
Its place in the page's rhythm: **the low-stakes group, collapsed to one
line per row, at the destination-group altitude** — never promoted above
the per-record Detail decision it defers to.

## 7. Test obligations + DoD

1. **Tier table as a pure function** `destination → tier`: asserts `hook`
   and user-`claude-md` are **NEVER** fast; `reference` /
   `reference:<file>` **IS** fast; `skill-md`, project-`claude-md`,
   `new-skill` are **FULL**. Drives off the same `_resolve_target`
   destinations `verbs.py` already computes.
2. **Invariant test:** no code path routes a `hook` or user-`claude-md`
   record through the fast lane — assert at both the eligibility function
   *and* the loop's route call site (defense in depth).
3. **Two-class eligibility predicate (the F1 fix, directly tested):**
   assert the **opposite absent-semantics** — a **missing SAFETY field**
   (`has_proposal`/`proposal_fresh`/`destination`/`already_canon` absent
   or non-eligible) ⇒ **NOT fast-eligible**; a **missing RED-FLAG field**
   (`contradicts` absent, lint flag absent) ⇒ **stays eligible**. A table
   test over both classes with present/absent/wrong-value cells; the two
   directions must not be collapsible into one branch.
4. **TOCTOU test:** a record fast-eligible at render whose `record.body`
   changes before confirm — assert **`route()` itself refuses** (the
   reference-destination `record_sha` re-check, per the §2 pin's
   verb-side reconciliation) and the server renders the refusal as
   escalate-to-Detail; a stale proposal is never compiled. The mutation
   target is the verb's re-check, not any server-side derivation.
5. **Escalation-trigger trial (task-required DoD item):** each of the five
   triggers fires. Contradiction (read from the proposal via
   `proposals_by_id`), `already_canon`, stale-proposal are testable live
   on synthetic records. The over-cap guard is unit-tested on the
   **predicate** with a synthetic capped-fast input (it cannot fire live
   for the v1 reference tier, and its Bucket fill feed does not exist —
   §2 trigger 3; the test proves the guard *predicate* exists for the
   forward case, not the data path).
6. **Spirit test (the paranoid one):** the fast card renders the human
   line per item; **no pre-selection, no select-all** (the inverted-
   default builder warning, §2); a fast route emits `card-shown` and
   `card-decided` with `lane:"fast"`. A DOM harness trial (FW-17) that a
   sweep still requires per-item selection.
7. **Telemetry test:** `card-decided` carries `lane` / `escalated` /
   `spot_check`; `report` computes fast-lane accept and spot-check-fail
   counts by destination; content stays counts/enums (§4.4 scan-clean).
8. **Audit-loop test:** after ≥1 fast route in month M, the first review
   session in M+1 opens the spot-check card with 3 random picks; a
   spot-check-fail logs distinctly; ≥2/3 fails raises the suspend-proposal
   card (human-gated, no auto-flip).
9. **Config test:** `fast_lane.enabled` parses fail-closed by the
   `config.py:80-106` idiom — only YAML `true` enables; missing/`false`/
   malformed → off (+ `_warn` on malformed).
10. **Live-trial DoD** (the round's instrument, ui-ux §6): a browser
    walkthrough **on DP-2, never DP-1**, exercising the sweep, one-keystroke
    escalation, and a forced automatic trigger; logged in
    `fixtures/ui-trials.md`. Two-gate blind review like every unit.

## 8. Non-goals (guard rails)

- **No confidence scores anywhere.** Destination is the fact; no score
  gates a tier (charter).
- **No auto-apply, no auto-route.** Every fast route is a human keystroke
  — P1's letter *and* spirit.
- **No per-destination tier config / settings in v1.** Tiers are
  **spec-pinned, not settings.** The **only** runtime control is a single
  committed-config boolean, parsed by the **same idiom as S-10's
  `one_motion_route`** (`config.py:80-106`): a top-level section in
  `<home>/config.yaml`, **fail-closed** — only the YAML boolean `true`
  enables; `None`/`false`/missing/malformed → disabled, malformed shapes
  `_warn` on stderr. Shape:

  ```yaml
  fast_lane:
    enabled: true      # only the YAML boolean true enables; anything else = off
  ```

  Default (no file / no section) = **off** until the feature ships and
  the operator opts in — policy that changes what the gate does lives in
  git history, synced and revocable by commit, never an env var. The §3
  audit-loop suspend-proposal targets *this one flag* (`enabled: false`),
  never a per-destination knob. (A single boolean would also work; the
  section shape is chosen so a later `fast_lane:` sub-key — e.g. the F4
  ruling's sweep cap or dwell — has a committed home without a schema
  break.)
- **No new telemetry event kind; no new plane.** Scalar fields on the
  closed set only (P7; §4).
- **No bulk CLI surface** — the sweep loops individual pinned `route <id>`
  verbs (09 §2.2).
- **No fast lane for a mined record's episode brief** — a mined
  `reference` record is fast-eligible, but its brief (12 §11 / Y-21) is
  Detail-only; wanting it means escalating.
- **Not worker work** — FW-35 consumes FW-31's lint flag and the
  contradiction edge; it builds no analyst change (worker-ecology §5).
