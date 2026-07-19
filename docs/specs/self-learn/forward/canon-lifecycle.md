# Forward theme B — Canon lifecycle: first-firing readiness

*Companion to `../14-forward-work-map.md` §2 (FW-6…FW-9). Dated
2026-07-18. Framing correction made while writing this map: the
lifecycle machinery is **more built than the backlog conversation
assumes** — `graduate` is in the UI verb set, `confirm-recurrence` is
wired through routes and keymap, over-cap state surfaces via Y-20's
budget indicator. The theme is therefore not greenfield: it is
**readiness for first firings** — each mechanism below has shipped but
never run against a real event, and first-firing is exactly when a
latent defect meets a user who has never seen the flow before.*

## 1. The common shape: drill before the event, not after

For each mechanism: (a) a **sandbox drill** — synthesize the triggering
event against a sandbox ledger (`SELF_LEARN_HOME` redirected, per the
standing rule) and walk the full flow as the user would; (b) fold
whatever the drill catches (the U13 SIGTERM blocker and the Y-20 0/10
falseness are the precedents — live walks catch what suites model
around); (c) leave a dated trial entry in `fixtures/ui-trials.md`.
Drills are cheap, bounded, and can batch into one session.

## 2. FW-6 — Over-cap graduation pressure

**The event**: a route pushes a managed section past its entry/word cap
(02 §4) → the verb prints the over-cap WARNING → the review flow owes a
graduation card for the section's oldest entries at the next batch.
**What exists**: the WARNING; Y-20's `over_cap` flag rendering on
Detail; the `graduate` verb in both surfaces; the review-skill's
open-next-batch-with-a-graduation-card instruction.
**The readiness questions the drill must answer**: does the *web*
surface carry any equivalent of the review-skill's graduation-pressure
card, or does a web-only user simply never learn the section is
over cap beyond the Y-20 line? Is graduating the *oldest* entries
actually the right heuristic when the drill makes you do it (oldest ≠
least valuable)? Does a graduation recompile visibly shrink the
section?
**Likely resulting BUILD**: a small over-cap notice + guided-graduation
affordance on the web surface, spec'd through 09 §11 with a Y-register
number, gated normally. Not built until the drill demonstrates the
gap — the web surface may prove sufficient as-is.

## 3. FW-7 — G-6 staleness revalidation (the one genuine build)

**The gate** (03 G-6): compiler/`--selftest` checks each routed
lesson's referenced target still exists; trigger = first routed lesson
observed stale, or a shared-repo deployment.
**Why it belongs in the map despite being gated**: it is the only
lifecycle mechanism with **no implementation at all**, and its trigger
is a *when not if* — canon references paths, tools, and daemon
behaviors that this user's fast-moving machine will eventually break.
**Pre-work worth doing at zero build cost**: when FW-26's runbook is
written, note the design intent already pinned in the G-6 row
(gate-the-read as complement, Copilot revalidation precedent, output =
supersession *cards* never auto-edits) so the eventual spec author
inherits the frame.
**Scope proposal (to ratify at spec time, not settled)**: the G-6 row
pins the check surface as "file, path, device, behavior" — this map
*proposes* that v1 narrow to existence checks (file/path/device/tool),
deferring behavioral staleness to recurrence telemetry (FW-8), which
detects it from the other side. That is a refinement OF the row's
stated scope, and the row wins until a spec-time ruling adopts the
narrowing; the recommendation is recorded here so the eventual spec
author argues it deliberately. *(Blind-review F2 fold, 2026-07-18: an
earlier draft stated the narrowing as an already-made decision — it
is not.)*

## 4. FW-8 — Recurrence resolution: revise / escalate / tolerate / retire

**The event**: telemetry accumulates recurrence *suspects* for a routed
record; the human confirms one (11 §2.2) — the lesson didn't hold.
**What exists**: the suspect→confirm data plane (11), the
`confirm-recurrence` verb (with `--tolerate`), review-skill "not
holding" cards, UI wiring for the verb.
**The readiness questions**: does a confirmed recurrence *visibly
change anything* on the record's Detail page afterward (or does the
event vanish into telemetry)? Are the four resolutions actually
reachable from the web surface, or only via the review skill? Does
"revise" (supersede with better wording, 11's mapping) hand off cleanly
into the teach flow with the supersession pre-linked?
**Honest expectation**: at n=1 with a user who personally remembers
every lesson, confirmed recurrences will be rare (E-2's logic) — this
drill ranks below FW-6 in urgency and mostly exists so the flow isn't
first exercised during real frustration ("the rule I routed didn't
stick" is precisely the moment the tooling must not fumble).
**Riding the same drill** (blind-review F6 fold): two more shipped,
never-fired lifecycle mechanisms share this readiness posture and this
sandbox session — **follow-up resolution** (11 §2.1's known-partial
routing, resolved by `followup done` — delta-check correction:
`confirm-held` is the adjacent holding-axis verb, §2.2, not the
follow-up resolver) and **contradiction edges** (11 §2.4's
`link contradicts`, analyst-proposed, verb-written). Both get walked
in the FW-8 drill; neither needs its own FW number unless the drill
finds real work.

## 5. FW-9 — Supersession end-to-end

**The event**: a routed lesson turns out to be wrong (not stale, not
unheeded — *wrong*), the S-12 path: supersede + recompile, never
git-revert.
**What exists**: `--supersedes` on teach, `superseded_by` semantics,
the routed-and-corrected metric that *depends* on this path being used
honestly.
**The drill**: sandbox — route a deliberately wrong lesson, then
correct it via `teach --supersedes` → route the successor → verify the
old text left every compiled surface, the metric counter moved, and the
record chain reads coherently on Detail (does the superseded record
*point forward* to its corrector visibly?).
**Why it matters beyond hygiene**: routed-and-corrected is the
design's honest "was it a good lesson" number (04 §metrics). If the
correction path has friction, corrections won't happen through it, and
the metric silently reads better than reality — a modeled metric by
accident.

## 6. Sequencing within the theme

One combined sandbox session covers FW-6 + FW-8 + FW-9 (they share
setup); order FW-6 first (most likely to fire soonest — caps are finite
and routing is ongoing). FW-7 stays gated; its pre-work is one
paragraph in the runbook. Any BUILD that falls out goes through the
normal spec→gate→build chain; the drills themselves need no gate (they
are trials, logged in fixtures, same as every DoD walk).
