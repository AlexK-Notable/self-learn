# Forward theme D — UI/UX: composition debt, the JS harness, backlog

*Companion to `../14-forward-work-map.md` §2 (FW-16…FW-19). Dated
2026-07-18. Context: four shipped rounds in two days each **added**
surface — worker button, budget lines, brief regions, proposal bars,
armed flows. All good individually; the round-4 principles
(`../feedback/2026-07-18-ui-feedback-04-design.md`) exist because the
user saw the sum drifting from composed to stacked.*

## 1. FW-17 — The JS DOM harness (do first)

**The gap**: `app.js` has grown through every round and now guards
real invariants — the reload-defer three-legged predicate (Y-16),
ensureRowSelected/ensureContentFocus (Y-19), the generic clickAction
dispatch, keyboard arming — with **zero tests**. Every invariant was
verified by live trials at ship time and is unprotected since. The
Y-16 predicate is the sharpest case: a regression there re-opens the
exact unreadable-flash bug the user reported, and no suite would
notice.
**The work**: a DOM-level harness (jsdom-class or Playwright-component;
the builder proposes, the gate judges) covering, at minimum: the
reload-defer predicate's three legs + defer-never-drop; focus
management (auto-select without stealing from pane/armed inputs); the
`data-key-action` dispatch table against the keymap. CI-integrated
beside the Python suites.
**Why first in the whole map**: it is the only item that makes *every
subsequent item cheaper* — round 4 will churn templates and JS
heavily, and doing that on an untested layer means re-buying live-trial
coverage every round.

## 2. FW-16 — Round 4: predicted shape and pre-work

**Standing state**: parked by the user (O-9); the four principles
already bind interim work.
**Prediction to hold the plan against**: round 4 is an
**information-architecture pass wearing a styling brief**. The
evidence: the user's own items (center the chat pane, frame with the
nav bar, collapse the hotkey footer) are all *hierarchy* complaints —
what deserves visual weight — and the Detail page now stacks five
region classes (finding, brief, budget/Why, proposals, pane). Restyling
a stack produces a prettier stack.
**Pre-work that costs nothing now**: when any new region ships in the
interim, it must name its place in the hierarchy in its spec (the
principles' "compose don't stack" applied at spec time — 09 §11
entries should say *where in the page's rhythm* a thing lives, not
just what it shows). This is already nominally standing effect;
making it an explicit spec-review check keeps round 4's debt from
growing.
**Build shape when unparked** (already agreed): design spec → its own
gate → build → **user walkthrough as the DoD** — the round exists
because live human perception catches what neither suites nor agent
trials do; the DoD must be the same instrument.
**Sequencing claim (14 §3)**: before packaging — first impressions
freeze at first install.

## 3. FW-18 — The carried backlog, dispositioned

Five items ride the backlog; batching FW-17 + the first three into one
maintenance round is the efficient shape (shared reviewer context):

1. **Push-fail surfacing in-UI** — promoted to FW-20 (sync theme); it
   stopped being cosmetic the moment a second capturing host became
   plausible.
2. **SSE pane_block duplication** — cosmetic, bounded; fix with a
   regression test in the maintenance round.
3. **Unreadable-record 500 on Detail** — 09 §5's degrade-gracefully
   invariant covers this in spirit, but the table has **no explicit
   unreadable-record row** (blind-review F4 correction); the
   maintenance round adds the row and the conforming behavior — a
   small spec addition riding its own gate, not a pure conformance
   patch.
4. **U14-F2 NIT** (swapError in the structural pin's asserted list) —
   one-line test hygiene, ride-along.
5. **Esc-interrupt 5 s kill backstop on subscription auth** — WATCH,
   not build: the backstop is *correct* fallback behavior; only worth
   revisiting if the SDK exposes a cleaner interrupt (FW-23's watch
   list carries it).

## 4. FW-19 — Detail-page composition pressure (WATCH with a tripwire)

**The trend line**: Detail regions per record: 2 at G-3 ship → 5 now.
Each earned its place through a gate; the *aggregate* was reviewed by
nobody — no gate owns the page as a whole. That is precisely the gap
the round-4 principles name ("one rhythm"), and it will not stay
closed after round 4 either: FW-6 (over-cap affordance), FW-8
(recurrence state), FW-9 (supersession chains) are all plausible
future Detail tenants from theme B alone.
**The tripwire, concrete — a *proposed* spec-review convention** (this
map cannot bind future specs; to become binding it should be folded
into 09 §11's authoring conventions when next touched): specs adding a
Detail region should include a **page-level composition statement** —
what the page's regions are *after* the addition, in display order,
with the new region's progressive-disclosure posture
(default-collapsed like the brief, or always-visible like the Why
region, and why). A spec gate can then judge the page, not the patch.
If a spec author cannot write that statement convincingly, the region
probably belongs behind an existing disclosure instead of beside it.
**Longer horizon (post-round-4, unscheduled)**: if region count keeps
growing, the structural answer is likely *modes* (a decision view vs
an archaeology view) rather than more collapsing — noted here so the
option is on record, deliberately unspec'd.

## 5. FW-30 — Settings surface (dated addition 2026-07-18, user-requested)

**The ask** (user, verbatim intent): a settings page deciding "which
models do what, and what their miner schedule looks like… maybe even
exposing a space for custom prompting of different parts of the
pipeline."
**The architectural invariant to pin at spec time**: the page is an
**editor over committed config** (`config.yaml` in the ledger home,
S-10's precedent — fail-closed parsing, policy in git history), never
a live toggle store. Every save commits; settings become auditable and
revocable the way routing decisions are.
**Exposure tiers, proposed for the spec to ratify**:
- *Expose freely*: models-per-role (miner / worker analyst / pane
  engine — the S-18 economics are the user's), miner cadence (shape:
  the systemd timer stays dumb and frequent, the miner reads its
  window from config — the UI never writes systemd units),
  notification thresholds, batch sizes.
- *Expose with care*: routing-doctrine additions ("your standing
  routing notes" — the feature most aligned with "make choices the way
  I would"), miner rubric emphasis. Both change what agents propose,
  never what executes without the human gate, so P1 holds either way.
- *Never expose*: the pane charter / permission enforcement, the
  secret scan, the consent invariants (Y-17-class), record schema.
  These are boundaries, not preferences.
**Interactions**: cohabits naturally with FW-14's `doctor` output
(settings + health = one page); the config surface should stabilize
**before** packaging freezes it for outside users (sequencing
pressure toward the packaging phase); page composition falls under
the round-4 principles and this doc's §4 convention.
**Status**: recorded, unspec'd, ungated — graduates via the normal
spec→gate chain when scheduled. The exposure-tier split above is the
user decision the spec must route first (queued in 14 §4).

## 6. Standing constraints on all of it

Y-9 (jargon-free user-facing text) binds every new string; the round-4
principles bind every layout choice now, parked or not; windows on
DP-2 never DP-1 in every trial; every unit through the two-gate chain;
DoD walks logged in `../fixtures/ui-trials.md`. Unchanged, restated
here only so this theme doc is self-contained for a future spec
author.
