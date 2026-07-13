# 2026-07-12 — G-3 TUI phased gates (09/10 authoring process)

*User-directed goal: take the G-3 TUI from 07's recorded vision to a
gated, execution-ready plan. Three phases — design spec → contracts +
corpus reconciliation → execution plan + end-to-end corpus review — each
cycling independent review → remediation → independent gate check.
Reviewers are fresh Fable agents, blind to this directory, ground-truthing
against live repos and live SDK docs, with UX/maintainability/
extensibility/architectural-fit lenses mandated beyond implementability.
Like its siblings, this memo is withheld from blind reviewers.*

## Phase 0 — empirical grounding (before any design froze)

Three evidence memos in `research/` (shareable): Agent SDK live-doc
verification (API-key-only auth; 5-min default cache TTL; partial
streaming undocumented; no model fallback), live-host grounding (Ghostty
not kitty; swaync with action support; `claude` 2.1.207 verifying every
pane-critical flag including `--include-partial-messages` and
`--fallback-model`), and the framework trade study (Textual 8.2.8
dominant on fit; Ink 7 runner-up; explicit "not genuinely close"
verdict; bus-factor-1 caveat isolated as the one human-values question).
The SDK findings drove two design departures from 07 §3, both landed as
planned dated amendments: engine abstraction with CLI-subprocess default
(subscription economics + verified capabilities) and cache demoted to
opportunistic.

## Phase 1 — design spec (09-tui-spec.md)

- **Review (fresh Fable, blind): FAIL** — 4 gates, 10 minors. P1-1: bulk
  collapse armed `reject` where the corpus pins graduation — would have
  flooded the M2 rejected-digest's negative-exemplar window with
  graduations and conflated the two metric classes 02/04 forbid
  conflating. P1-2: already-canon flag had no structured field anywhere
  (a pre-existing corpus gap the TUI exposed); cluster rows had no
  permitted read path. P1-3: `proposal validate` inherited the worker's
  delete-on-invalid semantics and fired mid-session — would have deleted
  the pane agent's work-in-progress. P1-4: resolution verbs and a live
  pane agent were unserialized writers to the same files (resolved-
  record resurrection race). Minors: enum drift, socket-path
  self-contradiction, unpinned affordances (`o`/`g`), deep-link edges,
  verb execution model + bulk-loop push latency, sdk-engine build scope,
  doctrine-consumer arithmetic, permission fallback ladder, and the
  process question on the framework values caveat (P1-14).
- **Remediation** (`f3aa44f`): all fourteen — graduate loop, structured
  `already_canon` + `--include-deferred` + merge-yaml reads,
  report-never-delete + session-end-only validation, interrupt-first
  serialization at verb dispatch, serialized-async verbs, `--no-push`
  batch amendment, sdk engine specced-not-built, three-loaders fix +
  compiled-doctrine pin, two-step permission fallback ladder. P1-14
  disposition: caveat surfaced to the user for veto in the gate report
  (reviewer accepted as procedurally equivalent).
- **Gate re-check (same reviewer): PASS.** All four gates verified
  closed against the pins they violated (not merely suggested wording);
  the targeted new-defect hunt (item-7 push semantics, interrupt-first
  interactions) found two wording-level residuals: P1-15 (§1 still said
  `g` gated on qualification) and P1-16 (`self-learn push` re-pinned as
  if new; abort-path push unpinned; "sentinel-protected" overstated).
  Both folded same-day, plus the verb-dispatch phrasing nit. The
  reviewer's residual polish note — running `proposal validate` inside
  the auto-interrupt sequence — is carried to the 10-tui-build-plan
  backlog.

**Recurring lesson holds (now 4-for-4 across the project): the
remediation minted new defects (P1-15/P1-16), caught only by the
independent re-check.** Wording-level this time, but the mechanism is
identical to M2-21. Never self-certify a gate.

## Phase 2 — contracts + corpus reconciliation

*(pending)*

## Phase 3 — execution plan + end-to-end corpus review

*(pending)*
