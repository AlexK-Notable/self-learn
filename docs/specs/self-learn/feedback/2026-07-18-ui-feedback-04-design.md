# UI feedback — round 4: aesthetics & composition (2026-07-18, user-present)

**Status: PARKED by the user** — *"can be saved for further down the
road."* Capture now, build as a dedicated visual-design round after the
functional queue. One standing effect immediately: any UI built before
that round should follow the §2 principles so new work doesn't deepen
the unevenness.

## 1. The user's feedback (condensed, their examples)

- *"The different UI elements feel a bit uneven right now."*
- Agent chat window: **center it vertically**.
- Left column (register option, analysis window, approval card, etc.):
  **center vertically** as well.
- Top toolbar / nav bar: **bigger and clearer — to help frame the
  contents of the window**.
- Hotkey legend at the bottom: **collapsed and expandable**, not
  always displayed.
- *"There's a few other sensibilities that i think should be applied…
  if you can discern the intention(s) behind my feedback and apply
  said intentions to the entire UI/UX of the project, you might find
  some areas to improve on yourself."*

## 2. Discerned intentions (the design principles behind the examples)

The surface grew feature-by-feature — each element landed where it
functionally fit — and it visually reads that way. The four examples
share four generalizable principles:

1. **Compose, don't stack.** Primary content should sit balanced in
   its region (vertical centering is the instance), not hug the top
   with dead space below. Every region should look placed on purpose.
2. **Frame the page.** The nav bar is structural, not decorative — a
   stronger frame makes the regions inside it read as intentional
   zones. Weight, size, and contrast of the chrome should establish
   hierarchy at a glance.
3. **Progressive disclosure of reference chrome.** Anything that is
   *reference* rather than *decision content* (the hotkey legend is
   the instance) earns its pixels only when summoned. Decision
   content owns the screen; help, metadata, and machine detail
   recede until asked for.
4. **One rhythm.** A single spacing scale, aligned edges, and
   consistent component sizing across all screens — "uneven" is the
   absence of a shared grid, not any one element's fault.

## 3. Self-audit candidates (areas the principles implicate beyond the examples)

To be re-verified against the live surface at build time; from code
knowledge of the templates:

- **Record-page metadata footers** (record ids, destination enums,
  diff previews): doctrine already demotes them textually (§8 "story
  first, plumbing last") — visually they should recede the same way
  (principle 3).
- **Action/proposal bars appearing and disappearing** shift layout
  when they arm/disarm/error; reserved space or a stable slot would
  keep the composition steady (principle 1).
- **Empty and sparse states** (a bucket with one record, a fresh
  chat pane): most acute source of top-hugging dead space —
  centering and deliberate empty-state copy (principle 1).
- **Error strips and banners**: several variants exist
  (banner-warning, error-strip, waiting bar, starting line) — one
  visual family with consistent weight (principle 4).
- **Bucket page destination groupings and the front-page bucket
  list**: check shared max-width, card padding, and type scale
  against the record page (principle 4).
- **Chat pane split proportions**: the split ratio and internal
  padding should match the record page's column rhythm (principles
  1+4).
- **Keyboard-first affordances** (the `y`/`o`/`i` hints inline in
  bars): audit whether each is decision-critical at that moment or
  reference chrome that belongs in the collapsed legend (principle 3).

## 4. Build-round shape (when unparked)

Aesthetic passes here have precedent (the 2026-07-17 dark-first visual
pass — reviewed like any other work). Same two-gate treatment: a short
design spec stating the principles as testable claims (spacing scale,
frame dimensions, disclosure behavior), then build, then a live
walkthrough with the user as the acceptance gate — composition quality
is not unit-testable; the user's eye is the DoD.
