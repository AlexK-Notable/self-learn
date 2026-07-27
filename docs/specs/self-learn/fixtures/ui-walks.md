# G-3 surface — agentic walk record

Companion to `ui-trials.md`. That file records **acceptance trials**:
dated, with a pass/fail predicate. This file records **walks**: an agent
driving the real UI in a browser and documenting what using it was like,
from the perspective of someone who cannot see the source.

There is deliberately no pass/fail here. A walk produces observations;
triage into defects is a separate, human step. The instrument's own
blind spots are recorded alongside the findings, because a walk that
under-reports is worse than no walk.

**Method.** `plugins/self-learn/ui/tools/` — see its README. A launcher
serves the real app against a seeded throwaway ledger; a probe enumerates
reachable surfaces and reports perceptual deltas; `WALK.md` is the
protocol the walking agent follows. The walker is always a fresh agent
with **no access to the source tree** — the rule the whole method rests
on, since an agent that knows the code documents intent instead of
experience.

---

## Walk 1 — 2026-07-26 · front page, git-hygiene bucket, one record detail

31 surfaces acted on. Opus. Stopped mid-stride (not stalled) to free the
browser; the shortfall was a keyboard-only resolution, completed in
walk 2.

### Findings

- **The header back-link advertises a key that is not bound.** The link
  reads "Back to this record's bucket **(Esc or h)**". The help overlay
  instead lists back as "Escape / a / ArrowLeft". Settled in walk 2:
  `h` does nothing, `a` works. See W2-F1.
- **Confirming a resolution acknowledges nothing.** Approve → Confirm
  landed on a *different record's* detail page. No toast, no banner,
  nothing naming the record just acted on. The walker reported "a
  resolution I believe landed but never saw confirmed."
- **The WORKER "Force run" button produces no perceptible response** —
  9s, three samples, no strip, no status change, still reading "worker
  overdue". The identically-labelled and identically-styled MINER "Force
  run" one section below visibly does something. Two walks and one
  hand-driven session found this independently.
- **Arming one record strips the action buttons off every other card**,
  leaving dangling "Note" labels above empty gaps: "the page looks
  half-broken while one record is armed."
- **`b` is labelled "Toggle episode brief" and does not toggle** — it
  turns the brief on and does nothing on a second press. There is no
  mouse control for it at all. What dismissed it was `n`, a different
  command, as a side effect.
- **`n` types its own keystroke into the field it focuses.** Keyboard
  focus leaves an "n" in the note field; a mouse click leaves it empty.
- **Escape is inert inside note fields** — no blur, no navigate. `Tab`
  was the only way out, and `Tab` appears in neither the footer legend
  nor the help overlay.
- **Sort has no direction indicator.** Clicking a header twice reverses
  the rows; nothing on screen says which way. Only the data tells you.
- **The MINER "Force run" silently discards the user's sort order** and
  collapses any disclosure panels they had opened.
- **The destination cycler cannot return to its default.** The ring is
  Skill doc → Skills repo instructions → Reference file → Skill doc;
  "(analyst suggestion)" is the initial state and is unreachable after
  the first click. It also renders the literal placeholder
  `<skills root>`, and grows 254px → 443px across two clicks, shoving
  the card layout.
- **Naming disagrees with itself**: the button says "Skill doc", the
  armed confirmation says "skill-md".
- **Status chips carry link styling but are not links** — five of six
  are plain text with tooltips under the same dotted underline as the
  one real link beside them.
- **The runs disclosure prints `None` as a value** — "scanned None,
  landed None, folded None".
- **The footer legend under-advertises.** Arrow keys work and are not
  listed; `d`, `a`, `ArrowRight`, `ArrowLeft` exist only in the `?`
  overlay. A user who never presses `?` never learns half the navigation.

---

## Walk 2 — 2026-07-26 · targeted at walk 1's gaps

Sonnet. Assignment was the six things walk 1 never reached.

### W2-F1 · The `h`/`a` contradiction, settled

`h` pressed on a record detail page and on a bucket page: **no effect,
either time.** `a` navigated correctly on both. The header link's own
printed label is wrong; the help overlay and footer are right.

This is the second instance in this codebase of a control advertising a
key bound to nothing — the first was the `c` key on "Confirm (c)", fixed
2026-07-25 by renaming the keymap action. Two instances make it a
pattern: **printed key hints and the live keymap drift apart, and nothing
in CI compares them.**

### W2-F2 · No-acknowledgement is universal

Confirmed across **three verbs × both input methods**. Defer, Deny, and
Graduate, by keyboard and by mouse, all land on the bucket's *first
pending record's* detail page. Never the list, never a done state, never
a toast, with nothing naming the record just resolved.

An acknowledgement mechanism does exist — re-requesting a resolved
record's URL redirects to `?notice=resolved-elsewhere` and renders "That
record was resolved elsewhere." But it only fires if the user goes
looking, and nothing indicates it exists.

Verification difficulty differs by verb, which nobody would have
predicted: a **deferred** row stays visible in a muted ~60% state, so you
can see it. **Denied and graduated** rows vanish from the listing
entirely, leaving `/report`'s raw JSON counts as the only confirmation.

### W2-F3 · Keyboard-only resolution works

`s` → `d` → `f` → `Enter`, zero mouse. The arm step is a real two-stage
gate, not just an endpoint name.

### W2-F4 · Deny nudges where Defer does not

Deny's armed state shows an amber "**[n] to say why**" hint that Defer's
armed state does not. An undocumented asymmetry, arguably correct.

### W2-F5 · `t`, `c`, `y` unreachable in the sandbox

Swept all five buckets; every record sat in the same "no analysis yet"
state with only `e/x/f/g/o` bound. Reported honestly as unreachable
rather than guessed at — they need a live analyst/worker session the
sandbox cannot run.

### W2-F6 · `r` (pane retry) is unknowable from outside

A retry that fails re-renders identical text, so no content-diff — and no
human — can distinguish "did nothing" from "retried and failed the same
way". A genuine epistemic limit, not a tooling gap.

---

## Walks 3–5 — 2026-07-26 · first parallel series, first non-clean world

Three Opus walkers, `2560x1440` headless, world `analysed,dirty-target`.
Walk 3 ran alone; walks 4 and 5 ran **concurrently in separate browsers
against separate sandboxes** (`45312`/`45313`, own `TMPDIR`, own ledger),
so no walker could see another's mutations. None was told what the others
found, and none was told a refusal existed.

The parallel arrangement is what makes the agreements below load-bearing:
where three walkers who could not communicate report the same thing, the
finding is not one walker's misreading.

**Viewport caveat.** At 2560x1440 every `sweep()` reported
`offscreen: 0` — nothing in this app falls below the fold at that size,
including a 2889px report page. The below-the-fold pressure that produced
blind spot 3 was absent, so these coverage counts are **not comparable**
to walks 1–2. Future walks wanting that pressure should shrink the
viewport deliberately.

### W3-F1 · The guided commit-and-retry resolves in silence

Route refuses on a dirty target, offers **"Commit that repo's changes,
then retry"**, the user confirms twice — a file write and a git commit —
and the app's entire response is to swap in an unrelated record. No
receipt, no message, nothing naming the record just resolved. Walk 3
learned it had worked by returning to the bucket and counting rows 7 → 6.

> "The longest, most anxious path through the app is the only one that
> ends in silence."

**Walk 5 reached the same silence independently and then ran a control
walk 3 did not**: approve from the bucket list (receipt ✔), approve from
a record detail page on a *clean* repo (receipt ✔), and corrected its own
first conclusion — the failure is the recovery path, not the page.

Cause, confirmed in source after the walks: `commit_drift_confirm`
mirrors `action_confirm` step for step — interrupt-first, contradicts
capture, adopt offer — then stops mirroring at the last step and falls
through to the pre-existing `HX-Redirect` (`routes.py:1781-1790`). It
never calls `_evidence_ctx`.

**The resolution-evidence spec §3.4 enumerated four redirect sites and
this is a fifth.** Its own warning applies verbatim: *"Fixing only the
third leaves the proposal-confirm path silently teleporting the user
while the DoD passes."* The reasoning was right and the enumeration was
short. What kept it short is still in the file — a comment at
`routes.py:1783-1787` justifying the redirect because "the redirect
target's re-read state IS the ground truth, same as every other
successful confirm." True when written; falsified by the unit that
shipped after it. A fossil rationale reads exactly like a live one.

### W4-F1 · The selection ring does not govern the destructive keys

Walk 4 pressed `e` with the ring on card 2 and watched Approve arm on
card 1. Reproduced with DOM focus on `BODY`, so it is not focus either.

`app.js:54-61` resolves every verb key with a **document-wide**
`querySelector('[data-key-action=…]')` — first match in document order.
The ring is a separate mechanism, `.selected`, read only at
`app.js:96-98` to follow a row's link on Enter. On a bucket page listing
N records, `e`/`x`/`f`/`g` always act on **record 1**.

This is the only finding in five walks that can resolve the wrong
record. The walker's own account of the consequence:

> "With Approve/Deny/Graduate on the line, I stopped trusting the ring —
> but there is nothing else to trust instead."

### W4-F2 · `Enter` on a focused button navigates instead of pressing it

`Tab` to a button, press `Enter`, and the global "Open" fires: you land
on a page you did not ask for. `Space` is the only activation. Observed
on two different buttons on two different pages. **Neither `Tab` nor
`Space` appears in the footer or the `?` reference**, so the documented
keyboard contract omits the only two keys that make focused controls
work.

### W4-F3 · `Escape` at the front page goes *down*

Footer says "Back / up a level". At the root it is browser history-back:
front → bucket → front → `Escape` → bucket. It oscillates, and you can
never settle at the top with it. Three deliberate trials to establish.

### W4-F4 · Dead and half-dead keys, settled

| key | status |
|---|---|
| `h` | inert. Advertised **only** in the back-link tooltip; absent from `?` entirely. Fourth sighting (W1, W2-F1, W5, W4) |
| `r` | inert as key *and* as focused button activated with `Space`. **This closes W2-F6**, which called `r` unknowable from outside — it is knowable, and it does nothing |
| `v` | works only where its link rendered; dead after Deny and Graduate while `?` lists it unconditionally |
| `b` | works where a brief exists; advertised identically on records without one. **Re-diagnoses W1's "b does not toggle"** as a different bug |

`v` is the fourth instance of advertised-key-bound-to-nothing, and the
first **inside the unit built to end them**. The 2026-07-26 fix gates the
*footer* per key (`style.css:395-397`); the help overlay iterates the
same static `keymap_entries` (`keymap.py:129-131` → `routes.py:376` →
`help_overlay.html:13`) with no conditional. The test written alongside
that fix is `TestSuccessFooterNeverAdvertisesADeadKey` — footer-named,
footer-scoped, structurally unable to see the overlay. Same lesson as
`lrn-ea833a5b`: **the more specific a check, the more likely its blind
spot is the exact case it was written for.**

### W4-F5 · `n` inside an arm strip cancels the arm

The strip's first line reads "any other key cancels"; its second reads
"n to say why". `n` cancels. Two lines of one box contradicting each
other at the moment of commitment. Separately, `n` still types a literal
`"n"` into the field it focuses (W1 found this; two walks now).

### W4-F6 · A pane session runs invisibly

Opened with `p`, navigated away, and nothing — not the header, not the
front page — indicated a session was still live. It was discovered eight
minutes later only by trying to start another and getting a conflict
prompt whose buttons carry no keys.

### W5-F1 · The app never defines its own vocabulary

The cold-open walker listed terms it was never given a definition for:
*canon* / *authored canon*, *superseded*, *graduate*, *routed*, *held*,
*arm*, *holding*, *episode brief*, *blocks*, *landed*, *folded*,
*near-misses*, *fresh*, *adjudicated*, *capture_rate_ceiling*,
*honesty-labeled*. It reached the app's core purpose in about four
minutes and the stakes only at the first Approve receipt, ~9 minutes in.

Sharpest line of the series:

> "It is also the ONLY place in the entire app that told me which file
> 'Skill doc' means. I learned the destination by triggering a failure."

One destination names its path only after being cycled *away* from the
proposed one; the proposed one never does.

### W5-F2 · The confirm strip names a destination three verbs do not use

`Deny → skill-md`, `Defer → skill-md`, and `Graduate → skill-md` all
appear on the arm strip, at the moment of commitment, for verbs that
write nothing there. Graduate's receipt then names no path and no sha and
mentions only the ledger. Its pre-action summary and its result disagree.
Also three vocabularies for one destination: **Skill doc** (picker),
**skill-md** (confirm), and a filesystem path (receipt).

### Agreements across independent walkers

Separate browsers, separate ledgers, no shared knowledge:

| finding | walks |
|---|---|
| commit-and-retry resolves in silence | W3, W5 |
| `Graduate` receipt carries no path | W3, W4, W5 |
| `Deny`/`Defer` arm names `skill-md` | W3, W5 |
| `/report` counts one graduate three ways (`graduated 1`, `superseded 1`, `supersede_rate 0.0`) | W3, W5 |
| `h` advertised, inert | W4, W5 |
| Worker "Force run" wholly unresponsive | W1, W2, W3 |
| `v` absent after some verbs, advertised always | W3, W4, W5 |

### Ruled a fixture artifact, not a defect

W5 flagged seven records carrying three distinct texts, each claiming
"1 sighting(s)", and read it as the app failing to group duplicates. The
seeder cycles a template list to reach 24 records
(`sandbox_ui.py:315-345`) — **the duplication is ours.** It does leave a
real question for separate triage: `RECURRENCE SUSPECTS` stayed at 0
against byte-identical triggers. Recorded so the artifact is not filed as
product behaviour later.

---

## Instrument blind spots the walks exposed

Recorded because they bound what any walk can claim.

1. **Row order was invisible.** Anchoring digest keys to row *content*
   (added to kill phantom "row A's text became row B's" reports) meant a
   re-sort changed no key and no value. Clicking a sort header visibly
   reordered five rows and the digest reported **zero**. *Fixed*:
   position now lives in the value; verified 31 changes all carrying
   position markers.
2. **Selection state was invisible.** The selected row is a
   `div.record-row.selected` with no own text and no interactivity, whose
   only signal is an `outline`. `capture()` skipped it entirely — the
   list-navigation key reported zero changes while the screen plainly
   moved. *Fixed*: bordered/outlined/shadowed containers are now captured
   even with no text; verified 2 changes for one keypress, ambient noise
   still 0, and a down-then-up round trip nets to 0.
3. **Below-the-fold surfaces were silently absent.** **The walker
   believed it had covered a bucket while seeing 3 of 7 records.** *Fixed
   2026-07-26.* Measuring first corrected the diagnosis: `surfaces()` did
   list off-screen elements, tagged `hidden_because:"off-viewport"` — but
   that tag sat alongside `display:none` and `occluded`, which mean
   genuinely unreachable, so nothing distinguished "scroll to me" from
   "you cannot have me". The worse half was the digest, which dropped
   off-screen nodes entirely: a change below the fold reported
   `changed_count: 0`, making "I clicked it and nothing happened"
   indistinguishable from "the feedback was off-screen" — a defect report
   the instrument would have *invented*, the same failure as the phantom
   advertised keys. Fixed by stating the shortfall rather than loosening
   `perceptible()`: `coverage.offscreen`, a measured `sweep()`, and
   `unseen_offscreen` on the digest. Control: same page, viewport the
   only variable — 1600px tall reports none, 500px reports 67.
4. **Ambient noise is zero only within a relative-timestamp bucket.**
   Across a step that crosses a `humanize_ts` boundary it is nonzero,
   and was once the *only* thing reported for a real graduation.
5. **Selection state was invisible on the front page.** *Blind spot 2 was
   only half fixed.* Walk 4 moved the front-page ring and the digest
   reported `changed_count: 0` while the screen visibly moved.
   ***Diagnosed and fixed 2026-07-26.*** The cause was **not** the CSS —
   `style.css:763-768` gives `.record-row[data-row].selected` and
   `tr[data-row].selected` the same `outline: 2px solid`, and the walk
   record's note that symmetry ruled styling out was correct. The
   asymmetry was `capture()`'s enumeration list (`probe.js:510-513`),
   which contains `td` and `th` but **not `tr`**. An outline on the `tr`
   changes no computed property of its captured `td` children, so the
   outlined element was simply never visited. Blind spot 2's fix — count
   an outlined container even with no own text — was written against
   `<div class="record-row selected">` (`bucket.html:76`) and could not
   reach `<tr data-row>` (`index.html:62`).
   **Measured both ways, front page**: ring move reported `0` before and
   `2` after; a down-then-up round trip nets to `0`; idle reports `0`.
   Probe `version: 4`.
6. **`<details>` expansion — NOT REPRODUCED. Probably a
   misattribution.** Walk 4 pressed `b`, got `changed_count: 0`, saw the
   Episode brief expanded in the screenshot, and recorded the digest as
   blind. Measured 2026-07-26 on a real record page: toggling a
   `<details>` is **fully visible in both directions** — open `13`
   changes, close `13`, reopen `13`, `unseen_offscreen: 0`.
   The likely explanation is that the digest was **right**: walk 1 found
   that `b` "turns the brief on and does nothing on a second press", and
   walk 5 found a record whose brief was **already open on load**. A `b`
   press against an already-open brief changes nothing, so
   `changed_count: 0` alongside a screenshot of an expanded brief is the
   correct report of a key that did nothing — which *strengthens* walk
   1's finding instead of impeaching the instrument.
   **Not yet settled**: the measurement above drives the `<details>` by
   clicking its summary, not by pressing `b` through the app's own
   handler, and the record used had no episode brief. Settling it needs
   one run of `b` on a record that has one, in both open and closed
   starting states.

**A blind spot that manufactures "I pressed it and nothing happened" is
the most expensive kind, because that is the single most common
conclusion these walks draw.** Note which way the ledger fell here: 5 was
a real instrument defect that hid a real change; 6 looks like the
instrument being blamed for correctly reporting a real no-op. **Both
directions of that error are live**, so a walker's "the digest missed it"
deserves the same measurement a walker's "the control is dead" does.

---

## World-state coverage

Raised 2026-07-26: *"did you set up a lesson that's routed to a claude.md
that has uncommitted changes?"* No. The seeded corpus varied what a
**record** looks like — scope, type, episode brief, unicode, long bodies
— against exactly **one world**: host repo committed clean, every
destination present, every host registered, every record unanalysed. Both
walks above reported coverage that could not have included anything else,
and neither said so.

The axis matters because most of this product's refusals live on it.
`verbs._abort_if_dirty` fires at six call sites, and the UI has a whole
affordance behind it: `routes._commit_drift_eligible` renders an armed
**"Commit that repo's changes, then retry"** button inside the error
strip when a route's stderr carries `GITOPS_DIRTY_MARKER`. It has unit
tests. No walk had ever seen it.

**Walks 3–5 saw it, and it was worth the trouble.** Two independent
walkers reached the refusal by the path a human takes, both called the
error message the best in the app — *"says what, why, and offers the
remedy"* — and both then fell into W3-F1: the remedy resolves in
silence. A green suite had covered that button since it shipped. The
first walk that ever pressed it found the hole in one attempt.

`sandbox_ui.py up --world <names>` now seeds selectable worlds (composable,
comma-separated, `clean` by default so the normal path stays the normal
path). Applied before the snapshot, so `reset` rewinds *to* the world.

| World state | Product behaviour it reaches | Status |
|---|---|---|
| repo clean, dest present | the happy path | `clean` (default) |
| route target dirty | `DirtyTargetError` + guided commit-first button | `dirty-target` ✅ reached 2026-07-26 |
| destination absent | create-vs-append branch of the compiler | `missing-dest` |
| record carries a proposal | Approve without cycling; post-analysis controls | `analysed` |
| host not registered | `"host not registered — self-learn host add"` | **not seeded** |
| destination unroutable | `"unroutable destination"` | **not seeded** |
| secret in record body | `SecretRefusal` — nothing written, no bypass | **not seeded** |
| ledger has a remote | real push / `EXIT_PUSH_FAILED` / rebase conflict | **not seeded** (no-remote is a divergence today) |
| managed section over cap | `VerbResult.over_cap_note` warning | **not seeded** |
| chezmoi source present | the user-scope leg, `CHEZMOI_DIRTY_MARKER` | **not seedable** — chezmoi is retired on this host |

Two findings fell out of building it, both of which bound earlier walks:

1. **World states are gated behind record states.** Dirtying the repo was
   not enough to reach the dirty-target refusal: `route` raises
   `NoProposalError` first, because every seeded record sat in "no
   analysis yet". Reaching the refusal took the destination cycler, which
   is not the path a human takes. Walk 2 hit the same wall from the other
   side and reported `t`, `c`, `y` unreachable. The `analysed` world
   removes the gate; the two now compose.
2. **Composing worlds with `git add -A` silently un-did one of them.**
   `missing-dest` committed with `commit_all`, which swept up
   `dirty-target`'s uncommitted edit — so the sandbox came up clean while
   printing that it was dirty. Caught by checking `git status` rather
   than trusting the startup banner. Fixed with targeted staging, which
   is the rule the product's own `gitops` module already pins.

## Change control

New walks append a dated section. Findings graduate out of this file by
being cited in a spec or a `14-forward-work-map.md` item; they are not
edited away. Instrument blind spots stay listed with their status, since
every one of them retroactively weakens the walks that ran before it was
fixed.
