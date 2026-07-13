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

- **Amendments landed** (`3f5867a`): all nine 09 §10 items as dated
  edits across 01/02/03/07/08 + README, plus an orchestrator
  stale-reference sweep (07 §3 heading, README doc row, 01 §3.4 verb
  mechanics, 08 already-canon row).
- **Review (fresh Fable, blind): FAIL** — the required cross-document
  sweep (nine contract families, file:line traces, AGREE/CONFLICT per
  family) agreed on eight of nine and surfaced one genuine
  contradiction: **P2-1 — the S-8 every-record-write secret-scan
  invariant had no enforcement mechanism on the pane agent's direct
  record edits** (and, pre-existingly, on the slash review's
  Discuss-edit path); the amendment set had pinned `proposal validate`
  as proposals-only, cementing the hole. Minors: 01's graduate wording
  under-inclusive for the pending-already-canon door; 03 asserting a
  not-yet-existing 10-doc; `unanalyzed` predicate unpinned; a
  three-cell table row; §10 item-1 citation overstatement.
- **Remediation** (`480fedb`): `proposal validate <id>` extended into
  the S-8 rider's enforcement point for verb-bypassing writes —
  secret-scans record body + all proposal siblings, report + exit
  non-zero, never delete/auto-redact, commits nothing; callers = pane
  session end + Discuss-edit card completion (T10); 02 §2
  enforcement-points paragraph; all minors.
- **Gate re-check (same reviewer): PASS.** All six dispositions closed;
  the targeted hunt found three remediation-introduced
  under-specifications, folded same-day: P2-7 (resolution verbs pinned
  to scan the **full record file** they rewrite — refusal = the
  no-bypass backstop 09 §5 relies on), P2-8 (validate exit codes pinned
  0/1/2 so the scan-blocked badge never parses prose), P2-9 (bucket
  group precedence: any-proposal → destination group with stale badge;
  unanalyzed group = no proposal file; Front count keeps the worker
  predicate, documented as a different measure). Plus the 02 §2
  detection-not-prevention honesty half-sentence (P2-1a residue).

**Lesson tally now 5-for-5: every remediation batch has minted findings
only the independent re-check caught.**

## Phase 3 — execution plan + end-to-end corpus review

- **10-tui-build-plan.md authored** during phase 2's review window
  (held in scratchpad until that gate closed to keep the phase-2
  reviewer blind to unreviewed material), landed `0a9755a` with
  P2-aware updates.
- **Review (fresh Fable — third distinct reviewer, no authorship or
  remediation involvement): FAIL** — 2 gates, 8 minors, against a
  terminal-condition scorecard of coherence PASS / implementability
  FAIL-pending / design-quality PASS. P3-1: the pinned `~/bin` entry
  wrapper resolved sibling paths through the deployment *symlink*
  (`$(dirname "$0")` → `~/tui`); the reviewer ground-truthed
  install.sh's link line and cited home-net-capture's `readlink -f`
  precedent. P3-2: the cluster-collapse adjudication flow —
  fully-designed in 09 §2.2 — had no owning test; acceptance could go
  green with it absent (T-A's predicate is scoped to behaviors its
  sentence names). Minors: interrupt-message shape missing from the
  verify-at-build ledger, `[syntax]` extra, socket bare-invocation +
  `--no-socket` unpinned, notify argv inventable, two unrecorded 09↔10
  divergences (uv-project packaging; Edit-only record grant), external
  resolution of an iterating record unspecified, advance-to-next
  untested, em-dash filename + XDG_CACHE_HOME test hygiene. Notable
  positive ground-truth: every pane-critical flag verified live,
  including probing `--max-turns` (accepted though undocumented).
- **Remediation** (`c935ddc`): all ten; the Edit-only record grant
  recorded as deliberate least-privilege (a session cannot recreate a
  `git mv`'d record — strengthens the P1-4/P3-8 bound).
- **Gate re-check (same reviewer): PASS + TERMINAL VERDICT.** All ten
  dispositions verified (wrapper path arithmetic re-checked; cluster
  flow inside the test net); the targeted introduced-defect hunt found
  nothing gate-severity (one folded U5 assertion note: `interrupt()`
  no-op on ended sessions). **Terminal conditions: 1 Coherence PASS
  (traced, not asserted — nine contract families + authority chain);
  2 Implementability PASS ("Opus 4.8 / Sonnet 5-tier agents can
  execute U1–U11, TUI and adjudication pane included, from the
  documentation alone"); 3 Design quality PASS (choices judged on the
  axes, not on rationale-text existence).**

## POST-GATE CORRECTION (2026-07-12, same day — user challenge)

The terminal verdict's design-quality condition cited "cli engine
default grounded in source-verified economics" — **that ground was
false.** The user challenged the "SDK is API-key-only" claim; an
empirical test disproved it in minutes (subscription OAuth works;
`research/2026-07-12-sdk-auth-empirical-test.md`). All three phases'
reviewers had "ground-truthed" the claim by confirming the quote exists
in live docs — none tested it. A user-commissioned DX study
(`research/2026-07-12-tui-vs-web-dx-study.md`) further showed the
Phase-0 trade study's TUI-only frame hid a decisively
easier-to-develop-for alternative (localhost web app). Failure analysis
(three modes: sourced ≠ true; frame narrowing — reviewers inherit the
author's frame; asymmetric retroactivity / true ≠ right-for-us):
znote `zQgIhHiqhJFes7RRzU4bF`, memory
`verification-and-framing-doctrine`, README ground rule 4 (new).
**Status: 09/10 remain structurally gated, but their platform/framework
/engine decisions are REOPENED** pending a further /goal cycle
(holistic problem-space map, early user-values routing, framing lens in
all reviews). Do not build from 09/10 until that cycle lands.

## Standing notes

- Lesson tally closed at **5-for-6**: phases 1 and 2 remediations each
  minted re-check findings; phase 3's remediation was the first to
  survive its re-check clean (its two probes came back
  no-hazard/consistent). The discipline stays: never self-certify.
- The Textual-vs-Ink bus-factor-vs-longevity weighting is a recorded
  **user values choice** (09 §6, trade study §d) — surfaced in the gate
  reports; flipping it later is a view-layer rewrite only.
- Build start remains gated on G-3's trigger (M2 shipped, worker
  proven); running 10 before that is itself a routed escalation
  (10 §4).

*(Rename note, 2026-07-12: the post-correction cycle rewrote and
renamed the gated docs — `09-tui-spec.md` → `09-surface-spec.md`,
`10-tui-build-plan.md` → `10-surface-build-plan.md` (platform → web,
engine → SDK, per binding user answers). The TUI revisions this memo
reviews live in git history through `1ce408c`. This memo is the
process record of that superseded cycle; its substrate findings
(P1-x/P2-x/P3-x) remain live pins, carried into the web revision.)*
