# Review record — gaming-centric keymap remap (2026-07-17)

Scope: `git show c544c40` (worktree self-learn-keymap, branch
keymap-wasd) — the user-directed remap recentering navigation on WASD +
arrows (w/s move, Enter/d/→ open, Esc/a/← up), evicting approve/deny to
e/x. Blind adversarial review by the same independent Opus reviewer as
the round-1 batch (no access to this directory), then a scoped delta
re-check on the fold.

## Pass 1 — adversarial (VERDICT: NOT CLEAN — no functional defects)

Runtime confirmed correct: all 22 keys globally unique (the NEW
uniqueness test proven effective by mutation — it fails on an injected
duplicate); armed-state branch intercepts every non-Enter key as
"disarm" BEFORE keymap lookup, so arming-then-w disarms rather than
navigates; table order behaviorally irrelevant once keys are unique;
help overlay + footer render from the one table automatically; `d` on
Detail is a harmless no-op (no [data-row]); `a` reproduces old-`h` up
semantics everywhere including pane interrupt-first; suite 493 green,
pyright src 0.

Findings — all documentation drift:

4. **MINOR** — three app.js comments still taught j/k/l (moveSelection,
   rows(), and the sort docstring).
5. **MINOR** — 09 §1's "one stack" bullet still read "`Esc`/`h`
   navigate up" with no amendment note, contradicting the remap
   amendment three bullets above it.
6. **MINOR** — doc 10 §1's "Keymap (single source)" row — the doc
   positioned as the keymap's canonical description — still enumerated
   the pre-remap layout in full.

## Fold (ae4dac2)

app.js comments now teach w/s + Enter/d/ArrowRight; 09's stack-walk
line reads Esc/a/← with a pointer to the dated amendment; the 10 §1 row
carries the dated amendment tag and the full new binding list.

## Pass 2 — delta re-check (DELTA VERDICT: CLEAN)

All three folds verified (grep-clean app.js; 09's only surviving
old-key literals sit inside the bullet carrying its own dated
amendment; the 10 §1 row matches keymap.py verbatim across all 16
bindings). Delta touches exactly the three files; suite 493 green.

## Empirical checks run during the pass (orchestrator)

Live Playwright walk on the seeded sandbox (dev :7358, redirected XDG):
s/s/w selection movement; d and ArrowRight drill-in; e arms Approve; w
disarms; x arms Deny; s disarms (no accidental mutation — argv-free
round-trips); a returns to Bucket; ArrowLeft returns to Front; footer
renders s/w/Enter/Escape/? on Front. Incidental pre-existing wart
observed, not introduced here: Open on a linkless row (bulk-acknowledge)
is a silent no-op.
