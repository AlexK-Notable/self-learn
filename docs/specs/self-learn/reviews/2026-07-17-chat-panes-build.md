# Review record — U12 chat-panes build (feedback round 1, item 7 — CODE gate)

**Cycle:** the build half of Y-13 (spec gate closed same day —
`reviews/2026-07-17-chat-panes-spec.md`). Worktree branch `chat-panes`:
implementation → tests/pyright → T-B(6)–(8) live trials → U12 DoD
browser trial → blind adversarial code review → fold → delta re-check →
one residual hardened → merge.

**Branch commits:** `cf5a147` (U12 core) → `d1aa2a4` (T-B(6) live
BLOCKER fix: tool schema) → `6afdad8` (trial records) → `db21ca8`
(review fold F1–F9) → the nonce-required hardening (this commit).

**Reviewer setup:** fresh blind adversarial reviewer, no authorship
stake, `reviews/` withheld; ran the suite and pyright itself,
re-reproduced findings empirically, and ran the delta on the fold.

## Pre-review live trials (fixtures/ui-trials.md)

- **T-B(6)** PASS — the footgun-B question answered on the resolved SDK
  (0.2.121): the in-process `propose_verb` call ROUTES THROUGH the
  charter callback; slot occupies WAITING; nothing executes. The trial
  caught a BLOCKER: the SDK's dict-of-types tool schema marks every
  param required → the model filled `until=""` → valid proposals
  refused. Fixed (real JSON Schema + empty-string normalization).
- **T-B(7)** PASS-BY-COMPOSITION — the agent refuses to propose
  `host add` at the in-context layer (surface-model prose) before the
  handler's closed list is reachable; the handler half is unit-pinned.
- **T-B(8)** PASS — bucket zero-write held live; the deny reason
  steered the agent to tell the human to use the record pane.
- **U12 DoD** PASS — full real chain in a browser: `p` → live bucket
  session → typed instruction → propose_verb → SSE → WAITING bar →
  `y` armed → Enter → real `defer` executed with pinned commit
  subject; the bucket session survived the confirm (the §4.5
  exemption, live).

## Round 1 — NOT CLEAN (2 MAJOR, 5 MINOR, 4 NIT)

The consent core HELD under adversarial reading — the reviewer could
construct no path where the agent executes or effectively executes a
verb without y+Enter. Both MAJORs were pinned-behavior violations on
the consent surface:

- **F1 MAJOR** — `validate_proposal` checked record EXISTENCE, not
  status; `locate_record` also finds resolved/ records, so a consent
  bar could advertise an impossible action (empirically reproduced by
  the reviewer). Fixed: status ∈ (pending, deferred) at intake — the
  same predicate the arm re-check uses.
- **F2 MAJOR** — the bar led with the `lrn-` id and omitted the pinned
  Y-9 human line entirely. Fixed: `VerbProposal.title` captured via
  the CLI-owned `record_title` (imported — P2-4), rendered leading,
  id trailing.
- F3/F4 MINOR — clear-set gaps (bulk-graduate, collapse members):
  fixed with a post-verb stale-slot sweep.
- F5 MINOR — arm matched by record id only: a clear-then-reoccupy
  between the human's read and their `y` could arm content they never
  saw as waiting. Fixed with a per-proposal server nonce required
  through arm/disarm/dismiss/confirm.
- F6 MINOR — sync routes mutated the slot from threadpool threads:
  now async (loop-side discipline).
- F7 MINOR — SSE scope gate wider than pinned (sibling Detail pages
  reacted): narrowed.
- F8/F9 NIT — `\Z` regex anchors (trailing-newline bytes); dest intake
  length cap.

## Delta — CLEAN

All nine verified closed against the actual diff (the reviewer re-ran
its own F1 attack script: refused). New-defect scan of the fold clean.
Residuals: (1) empty-nonce bypass — HARDENED post-delta (nonce is now
`Form(...)`-required on all four routes; 422 test); (2) accepted,
recorded: the client-side JS belt (armed no-op + scope guard) has no
CI harness — inspection + the logged browser trial only (standing
project posture, backlog line below); (3) F10 bucket-identity-by-name
is pre-existing, not charged.

## Disposition

Merged to master (--no-ff). Final state: ui 556 tests green, pyright
src clean. Backlog additions from this cycle: SSE pane_block
append-vs-swap duplicate (cosmetic race, pre-existing, observed live);
thin DOM-level JS test harness for app.js belts; bucket identity by
name-only (pre-existing convention, needs a scope-qualified bucket
key if bucket names ever collide across scopes).
