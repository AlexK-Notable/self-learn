# Review record — feedback round 5: U19/U20/U21/U22 + two walk-found fixes, 2026-07-19

Origin: the user's nine-item feedback list (live use). Investigated
same day by an Opus agent (every claim file:line-grounded,
`feedback/2026-07-19-ui-feedback-05.md`): 6 CONFIRMED, 2
NOT-CONFIRMED-but-UX-gap (the "dead" o/b keys were silent no-ops),
1 facts question answered (pane memory). Two rulings taken same day:
**guided commit-first** for dirty targets (pin intact, no override)
and **persist + resume for pane conversations this round** (gate-first).

## Spec gates

- `drafts/f5-round-spec.md` (U19 small set / U20 commit-first / U21
  iterate summary): blind gate **NOT SOUND** (4 MAJOR — the hint
  mechanism couldn't see its own marquee case; commit-first conflated
  chezmoi DRIFT with dirty; the overlay fix contradicted 09 §1's own
  doctrine line; the Detail timestamp is a pre-joined string a filter
  can't reach — plus 5 MINOR / 3 NIT) → 12 folds → delta **SOUND
  with 5 residuals** → folded → delta 2 **SOUND** (one sanctioned
  edge-pin tightened in place). Committed 280371d.
- `drafts/pane-transcript-persistence-spec.md` (Y-28/U22,
  Opus-authored): blind gate **NOT SOUND** (2 MAJOR — the carried-over
  no-session-persistence flag would have made all Tier-2 wiring dead
  code, its help text literally says "cannot be resumed"; rehome
  passed the resume gate against a moved bucket) → folds (flag
  dropped for the SDK's session_store + ephemeral-config pattern;
  rehome row + three-clause resumable predicate) → delta **SOUND**,
  two residuals folded with the reviewer's exact fixes
  (terminal_status clause; resolved-path compare). Committed 376f6eb.
  Both the author and the gate reviewer verified the SDK 0.2.121
  resume surface against installed source independently.

## Builds (Sonnet) + code gates (Opus)

- **U21** (merge c9a9226): CLEAN — 6 claimed + 3 reviewer mutations;
  the builder's session_key-not-record_id attribution fix
  independently re-derived correct; 2 coverage NITs accepted.
- **U19** (merge 948d3ee): CLEAN + 1 MINOR fold — the reviewer broke
  ALL FOUR scope-threading call sites and the 145-test route suite
  stayed green (every fixture user-scope = the default); three
  per-site discriminators added, delta-verified; the 4th site
  (_proposal_gone) judged NIT with the identical guarded path.
- **U20** (merge bc479f6): CLEAN + 2 MINOR folds (new-skill compound
  target probes both paths as the resolver does; drift-exit test
  strengthened to the message constant), delta-verified; the
  ruling-critical sweep found no override path and the eligibility
  truth-table matches only the two extracted dirty constants. Merge
  seam hand-joined per runbook §5: the confirm-failure re-render
  keeps BOTH U19's scope thread and U20's commit_drift block, and
  U20's four new _unarmed_context sites gained the scope thread they
  predate.
- **U22** (merge cf56a6c): CLEAN + 2 folds (view-mode plain-words
  footer; docstring) — 14 mutations incl. each resumable-predicate
  clause independently; the slot-never-persisted pin hunted clean;
  Tier-2 build trial had PASSED with real API probes (session_store
  mirror + cross-client recall).

## The DoD walk found two latent defects the gates could not

(Full walk: `fixtures/ui-trials.md` round-5 section.)

1. **Action-bar error strips were reload-wiped live** — leg (a)'s
   [data-verb-error] marker was only ever emitted by the U14
   registration strip; every failed-verb error on Detail/Bucket (and
   U20's button riding it) vanished before a human could act.
   FakeRunner tests are structurally blind to the post-subprocess
   refresh race. Fix merged (marker + audited sweep table + a
   real-partial render test closing the exact regression class);
   gate CLEAN first pass.
2. **Every Tier-2 resume aborted in-product** — the SDK's resume
   materialization probes optional SessionStore methods BY OBJECT
   IDENTITY; the adapter's pyright-appeasing raise-stubs read as
   implemented and were called for real. The build-trial probe had
   passed only because its ad-hoc store defined no stubs — it tested
   a different store shape than shipped. Fix merged (define ONLY
   append/load; the SDK's real materialize_resume_session now driven
   in a unit test; spec caveat corrected; multi-turn probe recall
   PASS); gate CLEAN first pass, root cause re-derived from SDK
   source by the reviewer.

Retrials after both fixes: every leg PASS, including genuine
context recall across a server SIGKILL and the two-commit
guided-commit shape (their drift commit, then our compile commit,
never entangled).

## Assembled master

**CLI 1027 passed / 4 skipped; UI 925+ passed (incl. 29 js); pyright
ui src 0 (one documented reportAbstractUsage ignore), cli src 56
pre-existing baseline.** All worktrees pruned. Live service
idle-exited; next launch runs round-5 code. Users should
hard-refresh once (stale-app.js hazard — cache-busting still open
backlog).

## Open items minted by this round

1. **Bulk-graduate errors invisible** (pre-existing): bucket.html
   posts with hx-swap="none", so the error response never enters the
   DOM.
2. **Keyboard path to Resume** absent by design this round; `i` on a
   record with history = Start-fresh (archives). For the keymap
   owner with F5's other keymap follow-ups.
3. **js flake watch**: test_no_hint_when_a_bar_is_armed_and_o_is_pressed
   failed once, clean on all re-runs (925/925 twice).
4. **Guided re-add for chezmoi DRIFT** (commit can't fix drift; the
   button correctly never offers) — a possible future ruling.
5. Carried from the drafts: static-asset cache-busting; multi-edge
   offer abandonment; promote bucket targeting; snippet-cap watch.

**Round 5 CLOSED: all nine feedback items resolved (two as
no-op-feedback UX, six as builds, one answered-and-shipped);
both rulings implemented and live-proven.**
