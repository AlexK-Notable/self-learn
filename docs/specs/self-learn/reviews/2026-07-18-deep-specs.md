# Review record — the deep-spec round: five build-grade drafts (2026-07-18/19)

Origin: the user's directive ("do we have any in depth specs…? that's
kind of what i was hoping for") after the forward map shipped. Five
Opus spec authors in parallel (register numbers pre-allocated per the
runbook: Y-22…Y-27 + doc 16), five blind Opus gates, folds by the
original authors, deltas to the original reviewers. Reviewers and
authors never saw `reviews/*`. **All five first-pass verdicts were
NOT SOUND; all five reached SOUND** — 2 in one fold cycle, 1 in one
cycle plus merge-folded residuals, 2 in two cycles.

## analyst-riders-spec.md (Y-22 lint + Y-23 contradiction) — SOUND

Gate: NOT SOUND. F1 MAJOR: the spec (and the orchestrator's charter
behind it) claimed a doctrine "narrowing" — but routing-doctrine.md
contains no contradicts guidance at all; the canon-wide instruction
lives only in the M2 worker's private prompt, so M1/pane never had
detection. Reframed: narrow the worker line + ADD the bounded doctrine
subsection (which first makes it three-producer). F2 MAJOR: lint-rule
placement "and/or" would let a builder silently break the one-schema
invariant — now a placement MUST (rules in the doctrine, template gets
a pointer). F3: the structured lint block's consumer named (FW-33
digest; inert-until accepted). F4: oversized-section degradation leg
corrected to the real `_canon_excerpt` mechanics. F5: Y-9 label fixes.
Delta: SOUND; one editorial residual (Y-23 cost bullet) merge-folded
with the reviewer's wording.

## fast-lane-spec.md (Y-25) — SOUND

Gate: NOT SOUND. F1 MAJOR: the eligibility predicate conflated two
field classes with opposite absent-semantics (safety fields fail
closed; red-flag fields' absence must NOT disqualify) and mis-sourced
`contradicts` as a `list --json` field. Now a two-class normative MUST
with an anti-collapse test. F3: TOCTOU pin. F4: the residual
"tick-N-in-seconds" erosion risk routed to the user as a marked RULING
(count cap / dwell / accept-soft-defense). Delta: SOUND conditional on
two wording fixes, merge-folded: the TOCTOU re-check moved INTO
`route()` (reference joins hook's record_sha re-check — the reviewer's
preferred option, keeping "the server derives nothing" literally
true), and the suspend-card copy gained its count placeholder.
Affirmed under attack: the tier table (reviewer tried to argue the
middle rows into FAST and failed), NEVER-row un-promotability,
closed-set telemetry handling, the ladder feed's confidence-axis
separation.

## miner-visibility-spec.md (Y-24 + a 12 §12 amendment) — SOUND

Gate: NOT SOUND. Security backstop confirmed closed (teach's
unconditional re-scan). F1 MAJOR: the snippet scan-site was asserted,
not pinned — and the existing `dropped-cap` branch fires BEFORE any
scan today, so cap-refused prose is currently never scanned; now a
named build-pin (field-by-field scan before each `_outcome` call, both
sites) with the killing test extended to both paths. F2: the
`rejected` disposition's double-absence (no snippet, no record id)
pinned at the journal-WRITE site. F3: no evidence quote anywhere —
provenance rides `--session` alone. F4: drill pinned to the latest run
only (the second-queue guard). Delta: SOUND; two residuals
merge-folded (t-b plants the secret in `why_durable`; the
`--session`-without-`--quote` parser verify; plus the concrete
`record=` kwarg removal spelled out).

## settings-surface-spec.md (Y-26 + `config` verb family) — SOUND (two cycles)

Gate: NOT SOUND, four MAJORs of the ships-a-lie class: the env-shadow
display treated "the environment" as singular (three mutually
invisible contexts exist); the pane knob's provenance crossed the
UI→CLI package boundary with no path; `cadence_hours` didn't gate the
nightly timer at all; hardcoded "36h/24h" labels would lie once
derived (plus the worker/miner same-named-constant collision guard).
It also dissolved a phantom user ruling (the doc-12 pending-gate
drift was already superseded intra-doc). Fold → delta 2: the skip-path
fold itself had introduced a latent never-mines-again bug (a skip that
stamps `last-run` starves every cadence above the timer interval) —
now a four-part pinned contract (placement, zero-work invariant, the
trap spelled out, byte-identical-mtime test). Delta 3: SOUND; the
lock-race probe answered — skip-under-flock is the correct order
(busy-if-running → skip-if-fresh → run), strictly reducing contention.
Three genuine user rulings stand in §7 (exposure tiers, timer
frequency, env>config precedence).

## 16-ecology-spec.md (FW-33 + FW-36, Y-27 + doc 16) — SOUND (two cycles)

Gate: NOT SOUND, foundation intact — the load-bearing staleness claim
(11 §4.2's "human-triggered only" prose already superseded; the miner
already timer-flushes telemetry) VERIFIED on every leg. F3 MAJOR: the
doctrine-draft consent path claimed verbatim reuse of `propose_verb`,
which structurally cannot carry it (closed verb set, record-keyed
slots, zero-write pane) — respec'd as `propose_doctrine` + server-side
`doctrine draft` + independent slot. F5 MAJOR: the reader-schema
extension (`contradictions[]`) stated. F8: three-stage build plan
(A field reports → B auditor → C doctrine drafts). Delta 2: NOT SOUND
narrowly, Stage-C-contained — the respec killed the bucket-staleness
axis correctly but missed the applicable one: **the doctrine file
itself** can change between draft and apply. Folded: CLI-stamped
`base_fingerprint` + apply-time refuse (the 09 §4.5 confirm-side check
transposed to file-content identity) + concurrent-apply clear leg +
draft enumeration/GC. Delta 3: SOUND; Stages A/B explicitly
build-ready; three Stage-C-local residuals merge-folded (whole-file
fallback's fail-toward-re-review posture stated as deliberate;
bar-dismiss shells `doctrine dismiss` so declines are durable; the
package-tree commit-failure rider).

## Cross-cutting observations

Every spec was required to verify its code claims against source, and
every gate re-verified them — the round's defect profile vindicates
both: the majors were overwhelmingly *fidelity* failures (a fictional
doctrine instruction, a phantom data source, a knob that wouldn't do
what its name says, a mechanism that couldn't carry its payload), the
exact class that survives when specs are written from memory. Twice, a
reviewer caught a defect introduced BY a fold (the settings
skip-marker bug; the ecology freshness gap) — the
delta-to-same-reviewer rule is what caught them.

**Graduation path**: drafts live in `drafts/`; on build scheduling,
each graduates into its final register home (09 §11 Y-22…Y-27, doc 16,
the 12 §12 amendment) with Y-number collision re-verified. The
consolidated user rulings from this round: fast-lane sweep guard;
settings exposure tiers, timer frequency, env>config precedence.

**Deep-spec round gate CLOSED: five drafts SOUND, build-ready
(Stage C of doc 16 rides its stated ratification gate).**
