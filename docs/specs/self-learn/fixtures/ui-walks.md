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

---

## Change control

New walks append a dated section. Findings graduate out of this file by
being cited in a spec or a `14-forward-work-map.md` item; they are not
edited away. Instrument blind spots stay listed with their status, since
every one of them retroactively weakens the walks that ran before it was
fixed.
