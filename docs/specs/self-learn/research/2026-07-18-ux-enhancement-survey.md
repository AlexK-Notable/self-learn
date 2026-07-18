# UX enhancement survey — automation, preloading, routing-time information, miner briefs

**Date:** 2026-07-18
**Register:** analysis only. No code changes, no spec amendments. This document is
input for the owner to pick the next build round.
**Frame:** reduce friction *without* eroding the premise. The human decision gate
(arm→confirm on a keystroke) is the product; every proposal below targets friction
that is **not** the decision — navigation, staleness, waiting, re-reading, context
reconstruction. Proposals that would auto-resolve records, auto-register hosts, or
spend model tokens on speculation are named as non-recommendations in §5, not
smuggled in as convenience.

Sources are cited inline: `09` = 09-surface-spec.md, `08` = 08-build-plan.md,
`12` = 12-transcript-miner.md, `RD` = routing-doctrine.md, `CS` = card-sections.yaml,
`FB4` = feedback/2026-07-18-ui-feedback-04-design.md, plus UI code paths under
`plugins/self-learn/ui/`.

---

## 1. Current-state map — what already happens without a click

So that nothing below reinvents existing machinery.

**M2 pre-analysis worker (the proposal drafter).** Kick-driven, never scheduled
(`08` §7.1). `teach` and `import` end by calling `self-learn worker kick`; a coalesce
window (`SELF_LEARN_COALESCE_SECS`, default 600s) batches kicks, then one
`timeout 15m claude -p` invocation (model `claude-sonnet-5`, "cost beats brilliance")
drafts proposals for up to **15 eligible records, oldest first**. Eligible =
pending, non-deferred, and lacking a schema-valid proposal *or* hash-stale
(`record_sha` ≠ current normalized body hash — content identity, not mtime). The CLI
stamps `record_sha`; the model never emits it. **Critical fact for this survey: the
web UI has no path to kick the worker** — grep of `plugins/self-learn/ui/src/` for
`worker kick`/`worker run` returns nothing. By the time a user opens the UI (usually
from a "N new proposals" notification), proposals for captured records already exist,
drafted entirely outside the UI's control.

**The miner (third capture producer).** Nightly systemd timer runs `self-learn mine run`
(`12` §3, §8-Q5). A deterministic Phase-1 digest strips each transcript to
speaker-tagged text (10–50× reduction, tool-result bodies dropped), then one contained
`claude -p` (`Read,Grep,Glob` only, no filesystem for the reader — `12` §10-2) reads the
digest against `mining-rubric.md` and emits **candidate records**: Trigger + Instruction
in the record's voice, a **shortest-span** evidence quote (capped 400 chars) + turn ref,
inferred grounding, `confidence`, and a **one-line `why_durable`** (`12` §2 Phase 2).
Landing is verb-gated, capped (`min(2×sessions, 15)`), pending-gated (default 25), then a
worker kick so mined records are analyzed before any human sees them. The miner reads the
whole transcript arc but **keeps only the shortest span** — everything else is discarded
at the end of the run, and transcripts themselves are pruned on `cleanupPeriodDays`.

**SSE live refresh.** `watchfiles` over every bucket's `pending/` + `proposals/` and
`events.jsonl`, debounced ~300ms, pushes scoped `refresh` events; the client answers with
a full `window.location.reload()` when in scope, 10s poll as fallback
(`09` §3; `app.js:349-384`). Files are the only truth — no locks. A reload **chokepoint**
defers (never drops) while a `[data-verb-error]` element exists, a confirm POST is in
flight, or any armed bar exists (`app.js:284-307`) — so live frames never clobber a
half-made decision or wipe a persistent error.

**Launcher readiness.** `self-learn-ui-open` ensures the service is up, waits inside a
≤5s budget for a fresh per-start token *then* a TCP connect before opening the URL
(`09` §3, Y-14) — closing the cold-start 403 race that idle-exit turned routine.

**Idle lifecycle (Y-14).** The server self-exits clean (exit 0) after
`SELF_LEARN_UI_IDLE_EXIT_SECONDS` (default 600) on a five-legged predicate: no SSE
subscribers, no in-flight requests, runner between verbs, no INTERRUPTIBLE pane session,
request-completion clock aged past the window (`09` §11 Y-14). The request clock stamps at
completion, never arrival. Self-exit arms only under systemd (`INVOCATION_ID`). **Any
proposal to keep the server busy in the background interacts directly with this.**

**Already-automatic in the decision loop.** The post-verb **next-record queue-walk**:
a successful route/reject/defer/graduate returns `HX-Redirect` to the oldest remaining
pending record in the same bucket, or Front with a "bucket clear" banner if empty
(`routes.py:766-853`, `next_record_url:145-162`). **Proposal validate at pane session
end** runs automatically and force-refreshes so a freshened proposal flips to a "fresh"
badge (`pane.py:945-957`). **Bulk collapse**: a homogeneous already-canon group renders
as one row arming a loop of `graduate` verbs (`09` §2.2; `models.py:605-614`). The
`o` destination cycle is already **scope-filtered** and self-corrects a scope-invalid
analyst suggestion (`09` §2.3). Non-blocking pane start (Y-15) already returns the split
immediately in a "Starting the conversation…" state.

**The single most surprising finding:** the UI is a *pure reader* of the proposal
drafter. The miner has a "Force run" button on Front (`routes.py:510-521`), but the M2
worker — the thing that actually produces the proposals the whole surface exists to
adjudicate — has **no UI trigger at all**. Question 2 ("preload proposals") is half-answered
by machinery the user cannot see or invoke, and the obvious symmetric affordance (a worker
Force-run) simply does not exist.

---

## 2. Answers to the four named questions

### Q1 — "Things we should do automatically instead of making the user click"

**What exists today.** The queue-walk auto-advances after every verb; proposal-validate
auto-runs at pane end; bulk already-canon collapses; the `o` cycle self-corrects invalid
scopes; the non-blocking pane already renders instantly. The decision itself is
deliberately *not* automated (arm→confirm, `09` §1) and must stay that way.

**The gap.** The friction that remains is not decisions — it is **keyboard readiness and
navigation setup**. Three concrete costs, all pre-decision:

1. On page load **no row is visibly selected**. `app.js` only creates the `.selected`
   marker once the user presses `w`/`s`; `openSelected` (Enter) silently falls back to
   `list[0]` (`app.js:96`). So a returning user sees a list with no cursor and no signal
   that keys are live — a soft dead-end the round-4 "frame the page / compose on purpose"
   intent (FB4 §2) also implicates.
2. Keyboard focus is not guaranteed on the document after an `HX-Redirect` queue-walk hop,
   so the next record can require a click before keys work.
3. The queue-walk has **no front door**: it only begins once the user has manually clicked
   into a record. From Front or a Bucket page there is no "start reviewing" affordance that
   drops you onto the oldest actionable record and lets the walk carry you.

**Proposals.**

- **P1a — Auto-select the first actionable row and guarantee document focus on every load
  and every queue-walk hop.** *(build S)* Render `.selected` on the first `[data-row]`
  server-side (or set it in `app.js` on `DOMContentLoaded`), and focus the content region
  after each htmx swap/redirect.
  - *Trigger/cost/staleness:* client-only; zero model cost; no staleness surface (purely
    presentational, files remain truth).
  - *Constraint brushed:* none of the hard constraints. Touches Y-9 only positively (a
    visible cursor is plain-words orientation). Consistent with FB4 principle 1.
  - *Steelman against:* pre-selecting a row could imply the first record is
    "recommended" — it is merely oldest. Mitigate with a neutral cursor style, not a
    highlight that reads as endorsement.

- **P1b — A "Review N pending" entry action** on Front (per bucket) and at the top of each
  Bucket page that navigates to the oldest actionable record and begins the standard walk.
  *(build S)* No new verb, no new route semantics — it is a link to
  `next_record_url(bucket, exclude=None)`.
  - *Trigger/cost/staleness:* on click; zero model cost; the target is recomputed from files
    at click time so it cannot be stale.
  - *Constraint brushed:* none. It is navigation, not decision.
  - *Steelman against:* marginal — a user can already click the first row. The value is
    discoverability of the walk as the intended mode, and one fewer decision about *where*
    to start; if the team judges the walk already obvious, skip it.

**Explicitly not automated here** (see §5): auto-dismissing errors, auto-advancing past a
failed verb, one-key apply.

### Q2 — "Should we preload anything in the background at server launch?"

**What exists today.** Proposal drafting is *already* preloaded — but by the worker at
capture time, not by the UI at launch (`08` §7.1). SSE keeps pages live. The launcher does
a readiness wait. Nothing is model-preloaded at UI launch, and Y-14 wants the server *gone*
when idle — so "preload = hold resident + burn tokens" is exactly the anti-pattern the idle
lifecycle was built against.

**The gap.** Two real ones, and they are *not* "draft more proposals speculatively":

1. **The user cannot pre-warm the queue.** If a record reaches review with no proposal
   (worker run failed, or it is freshly mined and the kick is still coalescing) or a stale
   one, the only UI remedy is to open an Iterate pane per record and wait 30–90s of model
   time each (`09` §2.4). There is no batch "analyze the queue" affordance, even though the
   worker exists precisely to do that in one 15-record batch.
2. **Cold-start read latency.** Every Front render shells out to four CLI subprocesses
   (`list`, `status`, `report`, `mine status` — `routes.py:205-208`); Bucket and Detail
   shell out too. After an idle-exit the user pays the ≤5s launcher wait *plus* these reads
   before first paint.

**Proposals.**

- **P2a — A worker "Force run" (`worker kick`) button on Front, mirroring the miner's.**
  *(build S)* This is the missing symmetric affordance. The worker spawns **detached**
  (`setsid`, `08` §7.1), so the UI fires-and-forgets and lets SSE surface proposals as they
  land — the server can still idle-exit while the worker keeps running, so **Y-14 is
  respected**.
  - *Trigger/cost/staleness:* on explicit click only (never autoload). Cost is bounded by
    the worker's own batch cap (15 records) and coalesce window; if nobody looks, the
    proposals simply wait in files like any worker output. Staleness is the worker's normal
    `record_sha` self-heal.
  - *Constraint brushed:* model-cost budget — mitigated by being manual and batch-capped,
    strictly cheaper than the per-record pane path it replaces. Does **not** hold the server
    resident (detached process).
  - *Steelman against:* the worker is "supposed to" be current already (it kicked at
    capture); a button implies the automatic path is unreliable. Counter: the button costs
    almost nothing and directly serves the "everything via UI, never open a terminal" ruling
    (Y-11 amendment) — today `self-learn worker kick` is a terminal-only escape hatch.

- **P2b — Prefetch the next record in the queue-walk.** *(build S)* While the user reads
  record N, warm record N+1's Detail partial (a CLI read + server render, **no model
  tokens**) so the post-confirm `HX-Redirect` paints instantly. The walk is the product's
  core rhythm; this removes a subprocess-read stall from *every single resolution*.
  - *Trigger/cost/staleness:* fires on Detail load for the computed next id; zero model cost;
    the prefetched partial is re-validated on actual navigation (files are truth), so a
    concurrent external resolution just falls through to a normal render.
  - *Constraint brushed:* Y-14 — one in-flight prefetch request keeps the idle clock from
    aging only momentarily (the request-completion clock stamps at completion, `09` §11
    Y-14), which is correct: an actively-walking user is not idle.
  - *Steelman against:* adds a speculative render that is wasted if the user resolves to
    "bucket clear" or navigates away; the waste is one cheap CLI read, so the risk is low
    but non-zero engineering surface (cache invalidation on SSE change).

**Not recommended** (see §5): auto-kicking the worker on Front load; pre-warming a pane's
first model turn.

### Q3 — "Extra layers of information gathered and displayed at the point of routing"

**What exists today.** Detail opens with the proposal's `card:` sections rendered
data-driven from `CS` (`09` §2.3), then Finding / Change / Why regions. The card registry
currently defines four sections: `headline`, `provenance`, `impact`, `discuss` (`CS`).
`RD` §8 makes clear the machine fields justify *filing*; the card must equip a human
*deciding*. **The card-sections registry is the sanctioned extension point** — new
routing-time information is new or richer card sections, not ad-hoc UI (`RD` §8, `CS`
contract).

**The gap.** The decision the human is asked to make — *which surface should this load
into* — turns on facts the surface does not show:

1. **Loaded-surface budget is invisible.** The entire narrowest-surface bias (`RD` §3)
   exists because managed sections cap at **10 entries / ~150 words** and every routed token
   dilutes attention at every activation. The human routing to `skill-md` cannot see how
   full that section already is. `status --json` has an optional `sections_over_cap` field
   already contemplated (`08` §1). This is the single most decision-relevant invisible fact.
2. **The target neighborhood is unseen.** The worker already reads the *target-canon
   excerpt* — the candidate section ±20 lines, or the whole file if <200 lines (`08` §7.1) —
   to write its rationale, then discards it. The human never sees the neighborhood the rule
   will join, even though contradiction detection runs against exactly that material.
3. **Rehome evidence is prose-only.** `RD` §3/§7 require a rehome recommendation to "name
   the evidence: which trigger elements live outside the record's own repo" — but that lives
   as free text in `discuss`, not as a structured, skimmable layer.

**Proposals.**

- **P3a — A loaded-surface budget indicator at the routing decision.** *(build S–M)*
  Surface `sections_over_cap`-style data (entries used / cap, words used / ~150) as a small
  Detail badge next to the suggested destination, or as a new **optional** `CS` section
  (e.g. `cost`, written by the analyst who already knows the target). "This skill-md section
  holds 8 of 10 entries" makes the `RD` §3 tradeoff a fact rather than a doctrine the human
  is trusted to remember.
  - *Trigger/cost/staleness:* computed by the CLI at render (like `proposal_fresh`), never by
    the server hashing; no model cost if delivered as a Detail badge, marginal analyst tokens
    if delivered as a card section.
  - *Constraint brushed:* Y-9 (must be plain words — "nearly full", not "sections_over_cap");
    the card-registry-only rule (deliver via `CS`, never a hardcoded template branch).
  - *Steelman against:* the compilers regenerate managed sections at apply time and enforce
    caps authoritatively, so an over-cap route is caught by the verb anyway; the badge is
    advisory. Counter: `RD` §8's whole point is that the human should *decide* with the cost
    visible, not discover it at apply-time rejection.

- **P3b — A "joins here" target-section preview.** *(build M)* Render the target-canon
  excerpt the worker already fetched, in the Change region beneath the diff, captioned as
  the neighborhood (not the applied bytes). The human sees the section the rule lands in.
  - *Trigger/cost/staleness:* the excerpt is a byproduct of the worker run — capturing it
    onto the proposal (or re-reading it CLI-side at render) adds no model cost. Staleness:
    it is advisory context, same posture as the diff preview's honesty caption (`09` §2.3).
  - *Constraint brushed:* model-cost (none if reusing the worker's read); Y-9 (caption in
    plain words); no secrets (the excerpt is canon, already tracked).
  - *Steelman against:* more on-screen material competes with the decision content that FB4
    principle 3 wants to own the screen — deliver it progressively disclosed (collapsed by
    default, `d`/expand), not always-on.

- **P3c — Structured rehome evidence layer.** *(build S)* When a proposal recommends rehome,
  render the "trigger elements living outside the repo" as a short labeled list rather than
  buried prose — the same content `RD` §3 already mandates, given a skimmable home.
  - *Trigger/cost/staleness:* analyst writes it at proposal time (already required prose);
    no new model cost, a rendering change plus a card-section convention.
  - *Constraint brushed:* `RD` §7/Y-18 pin — there is **no `rehome:` proposal YAML field**;
    this must stay a rendering of `discuss`/`rationale` prose, not a new schema key.
  - *Steelman against:* rehome is rare (`09` §11 Y-18 gives it no human key); spending
    registry surface on a rare act may not pay. Fold into `discuss` styling rather than a new
    section if volume stays low.

### Q4 — "Should the mining agent also write a longer brief, shown when clicking into a bucket record?"

**What exists today.** The miner emits a one-line `why_durable` and a **shortest-span**
evidence quote (`12` §2 Phase 2). The worker's `provenance` card section carries a terse
mined origin ("machine-mined from session …, why-durable: …", `12` §1). When the human
clicks into a mined record, Detail shows the record body (Trigger/Instruction), the short
evidence quote with its origin, and the provenance line — but **no reconstruction of what
actually happened** in that session: the attempt → failure → correction → resolution arc.

**The gap — and why this is the strongest of the four.** The miner is the **only actor in
the entire pipeline that ever reads the full transcript**. The worker reads the record +
target canon, not the session. The human at review reads the card. And the source itself is
**ephemeral**: transcripts are pruned on `cleanupPeriodDays` (`12` §0/§3), so by review time
the raw episode may be gone. `RD` §8 and `CS.headline` demand "story first… what happened,
in domestic terms… a reader returning after a week away must recognize the episode." A
one-line `why_durable` cannot carry that arc. The miner had the whole story in context and
threw it away — this is the clearest case of *capture-time context lost before decision
time* in the system.

**Proposals.**

- **P4a — The miner emits a bounded "episode brief," surfaced as an optional card section
  for `source: session` records.** *(build M)* Add one section to `CS` (e.g. `episode` /
  `story`), written from the miner's transcript reading: 2–4 sentences reconstructing the
  arc — what was attempted, what failed, what the correction was — with the existing turn
  refs. It renders generically like every other section (no template branch), and is absent
  (skipped) for non-mined records.
  - *Trigger/cost/staleness:* the miner **already spent the read tokens** on the digest; the
    brief is marginal *output* tokens in the same Phase-2 `claude -p` call — no new run, no
    new model pass. Field-length caps apply at landing (refuse-not-clip, `12` §10-2). It is
    fixed at capture and never regenerated, so it cannot go stale against a later record edit
    (it describes the origin episode, not the current record).
  - *Constraint brushed:* the producer/consumer boundary — card sections are normally written
    by the analyst (worker), not the capture producer. This is the real design question:
    either (i) the miner writes this section directly onto the record/proposal at land time
    (a producer writing a card section — a genuine architectural addition), or (ii) the miner
    stores a bounded episode digest on the record and the worker lifts it into the card. Path
    (ii) keeps "analyst writes cards" intact but adds a record-side field. Also: attacker-
    influenceable transcript text (`12` §10-2) means the brief inherits the same landing
    scan + regex-gated refs the evidence quote already gets.
  - *Steelman against:* it widens the mined-record footprint and the miner's output contract
    for a supply channel still on probation (`12` §4 — mined-card accept rate decides the
    miner's fate). If mined cards are getting rejected wholesale, a richer brief polishes
    something being deprecated. Counter: a legible episode brief plausibly *raises* the
    accept rate (the reviewer can defend the decision), which is exactly the calibration
    metric — so it is worth trying *within* probation, measured.

- **P4b — Cheaper interim: expand `why_durable` into 2–3 sentences with the arc, no new
  section.** *(build S)* If the registry change in P4a is too much for now, let the miner's
  `why_durable` carry the arc and let the existing `provenance` section render it. Less
  structured, but captures the ephemeral context at near-zero cost.
  - *Steelman against:* overloads a field designed as a one-liner; the provenance section's
    `CS` instruction says "one short phrase" — stretching it fights the registry contract.
    P4a is the honest version; P4b is the stopgap.

**Non-recommendation adjacent to Q4:** do *not* try to reconstruct the episode on demand
via the Iterate pane at review time — the transcript is likely pruned by then, so capture
time is the *only* place the story exists. This is the load-bearing reason the brief must be
written by the miner, now, not by an analyst later.

---

## 3. Unnamed opportunities (the "etc.")

Same rigor; friction the questions did not name.

**U1 — Queue triage at scale (30 pending).** The Bucket page has **no pagination and no
count cap** on the record list (`models.py`; the 50-row cap is only the bucket *chat pane's*
context). Thirty mixed records render as one long scroll grouped by destination. Bulk
collapse handles homogeneous already-canon groups, but a bucket of genuinely mixed records
has no "triage mode." *Proposal (build S–M):* a compact/dense list toggle and a count-badge
per destination group, plus the P1b "Review N pending" walk entry so scale is handled by the
one-decision-at-a-time walk rather than the scroll. *Steelman:* the walk already linearizes
the queue; if users adopt it, the scroll length stops mattering — measure before building
dense-list chrome.

**U2 — First-launch discoverability of the keyboard model.** The entire surface is
keyboard-first, and `?` opens the reference overlay (`keymap.py:92`), but a first-time user
has no signal that `?` exists or that keys are live (compounded by U1/P1a's missing
cursor). Keys like `y`/`p` silently no-op on pages where they do not apply (`app.js:54-61`).
*Proposal (build S):* a one-time, dismissible "press ? for keys" hint in the (round-4:
bigger, framing) nav bar; and render context-inapplicable keys as visibly disabled in the
footer rather than silently inert. *Constraint:* FB4 principle 3 (reference chrome recedes)
— the hint is a summon-once affordance, not permanent chrome. *Steelman:* single-user
system; the owner already knows the keys — value is mostly for the "returning cold after a
week" case `RD` §8 keeps invoking.

**U3 — The post-verb landing is good but the "bucket clear" terminus is a dead stop.**
After clearing a bucket the walk dumps to Front with a banner (`routes.py:849-853`). A user
in triage flow then has to re-decide where to go next. *Proposal (build S):* on "bucket
clear," offer the next non-empty bucket's walk as a one-key continue ("Bucket clear —
`Enter` to start the next: <bucket> (N pending)"), keeping the queue-walk rhythm across
buckets. *Constraint:* Y-9 plain words; no new verb. *Steelman:* crossing bucket boundaries
mixes scopes and may deserve a deliberate pause; some users want the stop. Make it an offer,
never an auto-jump.

**U4 — Error-recovery beyond the persistent registration strip.** Y-16 made the *host-add*
error persistent and plain-words, but every other verb failure still renders stderr verbatim
in a re-armable bar and relies on the user to read it (`09` §5). Push-failure surfacing is
already on the roadmap backlog (per MEMORY). *Proposal (build M):* a consistent error-strip
family (FB4 §3 self-audit already flags "several variants exist… one visual family") with a
plain-words lead sentence for the *common, recoverable* failures (dirty target → "commit or
stash first"; push failure → "your route is committed locally; push failed"), stderr demoted
beneath — generalizing the Y-16 pattern to the recoverable-failure class only, leaving the
verbatim-first contract for everything unexpected. *Constraint:* `09` §5's invariant that the
verb's stderr is the contract — this must *add* a lead line for known cases, never replace or
reinterpret stderr. *Steelman:* enumerating "known recoverable failures" is a maintenance
surface that drifts from the CLI's actual messages; keep the set tiny and test it against
real stderr.

**U5 — Round-4 principles have a functional (not just aesthetic) implication: the action bar
appears/disappears and shifts layout** (FB4 §3). When a verb arms/disarms/errors, the bar
changes height and the composition jumps. This is a *usability* issue (the target the user
is about to `Enter` on moves), not only an aesthetic one. *Proposal (build S):* reserve a
stable slot for the action bar so arm/disarm/error never reflows the decision content — worth
pulling forward from the parked round-4 because it affects mis-keying risk on the confirm
step, which is a decision-integrity concern. *Constraint:* none; strengthens arm→confirm.
*Steelman:* it is listed under a parked round; pulling one item risks doing aesthetics
piecemeal. Frame it as decision-safety, build it with the rest if the owner prefers.

---

## 4. Ranked shortlist — top 5 by (user-felt benefit ÷ build size)

1. **Next-record prefetch in the queue-walk** *(S)* — *What ships:* record N+1's Detail
   partial is warmed (CLI read + render, zero model tokens) so every post-confirm hop paints
   instantly instead of stalling on a subprocess read. Touches the product's core loop, every
   single resolution.

2. **Worker "Force run" button on Front** *(S)* — *What ships:* the missing symmetric
   affordance to the miner's Force-run; one click detached-spawns `worker kick` to pre-warm
   proposals for the whole queue without opening a pane per record, and without holding the
   server resident (Y-14 respected).

3. **Auto-select the first actionable row + guarantee keyboard focus on load and every
   walk hop** *(S)* — *What ships:* a visible neutral cursor on page load and focus after each
   redirect, killing the silent "keys do nothing until you click / press `s`" dead-end on
   every screen.

4. **Loaded-surface budget indicator at the routing decision** *(S–M)* — *What ships:* a
   plain-words "this section holds 8 of 10 entries / near its word cap" fact on Detail, making
   the narrowest-surface tradeoff (`RD` §3) — the whole basis of the routing decision —
   visible instead of trusted to memory.

5. **Miner episode brief as an optional card section** *(M)* — *What ships:* the miner spends
   marginal output tokens (same run it already pays for) to reconstruct the session arc into a
   bounded `episode` card section for mined records, capturing the ephemeral transcript story
   before it is pruned — directly serving `RD` §8 "story first" and, plausibly, the miner's own
   accept-rate calibration.

*Just below the line:* the "joins here" target-section preview (P3b, M — high comprehension
value but competes for screen space) and the "Review N pending" walk entry (P1b, S — pure
discoverability of an existing flow).

---

## 5. Explicit non-recommendations (do not relitigate)

- **Auto-resolving anything** — already-canon graduations, duplicate folds, high-confidence
  routes. This is the `12` §8 A2 staged-autonomy ladder (L1/L2/L3), governed by *dated
  register edits justified by measured per-class accept rates*, **not** a UI convenience. The
  human gate is the premise (`09` §1; `12` M-1). "Automate the click" never means "auto-resolve
  the record."

- **Auto-kicking the worker on Front load.** Speculative model-token burn on every page
  open, and it fights Y-14's idle-exit cost story. Make worker analysis a *button* (P2a),
  never an autoload.

- **Pre-warming an Iterate pane's first model turn.** 30–90s of model time
  (`09` §11 Y-15) spent speculatively on sessions the user may never open. The non-blocking
  start (Y-15) already solved the *perceived* latency; paying for turns nobody requested is
  the wrong fix.

- **Auto-dismissing error strips / auto-advancing past a failed verb.** Y-16 deliberately made
  registration errors *persist* until dismissed because a flashed-and-gone red strip was
  unreadable. Verb stderr is the contract (`09` §5). Do not "helpfully" clear it.

- **One-key apply / auto-arming any verb.** `route` compiles + commits + pushes; arm→confirm
  exists precisely so a mis-keyed single stroke cannot trigger an apply that needs supersession
  to unwind (`09` §1). The extra keystroke is the safety, not friction to remove.

- **Client-side proposal-freshness / `record_sha` computation.** The CLI is the enforcer; the
  server never hashes (`09` §2.3, §5). Any "preload freshness" idea must read
  `list --json .proposal_fresh`, never recompute.

- **Auto-registering unregistered hosts or ancestor projects.** H-3 consent stays human; host
  add is never proposed or automated, and the pane agent must never mint write targets or widen
  its own read scope (`09` §11 Y-11). An unregistered ancestor project is a *fact you tell the
  human* ("register ~/repos/keyboards and this lesson can move there"), never something the
  system assumes (`RD` §3).

- **Embedding-based retrieval on the transcript side** (relevant if "gather more for the brief"
  tempts a retrieval layer). `12` §5 already decided this is an unnecessary abstraction:
  teachable moments are speech acts where embedding similarity is weakest, and its worst
  miss-mode is the novel gotcha that resembles no anchor — the miner's whole reason to exist.
  The rubric survives; the retrieval layer does not. (Embeddings' legitimate home is ledger-side
  dedup at ~200+ records — out of scope here.)
