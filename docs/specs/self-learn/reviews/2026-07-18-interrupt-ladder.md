# Review record — Esc-interrupt ladder tuning (2026-07-18)

Backlog item (T-E UX finding: Esc rides the full kill window because
the SDK fast-interrupt is ineffective on subscription auth). Dated
09 §4.2 amendment (grace 2 s→1 s, kill 5 s→2.5 s, every-await-bounded
pins) + engine implementation, built directly on master (small cycle),
commit b322aa5.

## Blind review (agent a693c682250f24a1e; reviews/ off-limits)

Verdict: **NOT CLEAN** — 1 HIGH, 1 MEDIUM, 2 LOW, 1 INFO. The HIGH
was the night's best catch:

- **F1 · HIGH — cancel-vs-abandon.** `wait_for` on `disconnect()`
  CANCELS it on timeout, and a raw asyncio cancellation pierces the
  SDK transport's `CancelScope(shield=True)` SIGTERM/SIGKILL
  escalation (the transport's own docstring carries the caveat; the
  reviewer verified with an empirical cancel probe on the installed
  anyio/SDK). With kill=2.5 s < the SDK's first 5 s graceful wait,
  the cancel ALWAYS landed before SIGTERM — a wedged CLI child would
  outlive a "bounded" teardown with no further escalation, silently
  re-creating resident-forever at the subprocess level. **Fold:**
  shield-and-abandon (caller bounded, disconnect finishes killing in
  the background, completion logged) + a test pinning background
  completion.
- **F2 · MEDIUM — ladder arithmetic.** The added bounds were additive
  (true worst case ~6 s, exceeding both the "~2.7 s" claim and 09
  §3's untouched "≤5 s" verb-dispatch pin). **Fold:** one deadline
  anchored at Esc; ceiling = ladder ≤2.5 + bounded close ≤2.5 = 5 s;
  both spec sites restated/re-derived.
- **F3/F4 · LOW** — stale module docstring; tests couldn't
  distinguish cancel from abandon. **Folded** (docstring; the
  background-completion test; the bounded-per-callee caveat recorded
  in the amendment).
- **F5 · INFO** — premises overstated (the installed SDK already
  bounds these at ~60 s/~20 s internally). **Folded:** spec and
  commit wording corrected to "tightens to keystroke scale and fixes
  the semantics".
- Attack "is 1 s grace too tight": no finding — T-E shows the ack is
  effectively instant on this stack; a spurious ack-timeout merely
  force-closes, live-proven non-destructive.

Fold commits: dc18744 + b3f4728. Delta round 1: NOT CLEAN — F3's
docstring edit was claimed folded but had silently no-matched (the
reviewer caught the discrepancy between the claim and the diff; edit
scripts now assert their anchors). Delta round 2 (F3 landed + the
abandoned-task strong-reference nit hardened): **CLEAN** — no
residuals; gate closed 2026-07-18.

## Live retrial

T-E addendum (`fixtures/ui-trials.md`): teardown 2.90 s (was ~5.3 s),
close 0.00 s, PASS.
