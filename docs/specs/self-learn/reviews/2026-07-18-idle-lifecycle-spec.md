# Spec-gate review record — Y-14 idle lifecycle (2026-07-18)

Amendment set under gate: 09 §3 (server bullet + launcher bullet),
09 §4.3 (dated acceptance note), 09 §4.4 (env var), 09 §11 (Y-14
register entry), 10 §3 (U13 task row). Drafted 2026-07-18 during the
overnight autonomous run (user-ratified roadmap: idle-lifecycle is the
queue head of the UI-completion phase).

## Round 1 — blind review (agent a7f07ef0faa13d735, no access to reviews/)

Verdict: **NOT SOUND** — 4 MAJOR, 2 MINOR, plus test/DoD gaps. No
BLOCKER; the exit mechanism (clean exit under `Restart=on-failure`,
launcher as resurrection path) and the launcher-wait skeleton were
verified sound and kept.

- **F1 · MAJOR — abandoned `awaiting-input` session re-creates
  resident-forever.** The draft's "any non-ENDED session blocks exit"
  covered `awaiting-input` — the state every successful pane turn
  parks in — so the most common walk-away path (Iterate → read →
  close window without `q`) would pin the server resident forever.
  The draft's own casualty sentence ("the proposal slot") named a
  state the predicate made unreachable (slot occupied ⇒ session
  non-ENDED ⇒ exit blocked), proving the interaction untraced.
  **Fold:** blocking leg narrowed to `INTERRUPTIBLE_STATES`
  (starting/streaming/interrupting); the monitor tears down a parked
  session through the standard teardown (slot clears via the §4.5
  clear-set) before exiting. Judgment call recorded in Y-14 decision
  (5) with the rejected alternative — resolved toward the user's
  stated requirement and the existing 09 §4.2 transcript-is-ephemeral
  pin. Flagged for the user's morning review.
- **F2 · MAJOR — request-clock stamp point unpinned.** Stamp-at-entry
  would let a >window bulk loop (one POST, client gone) be SIGTERMed
  mid-run when a sample lands in an inter-verb lock gap. **Fold:**
  clock stamps at request COMPLETION, plus a fifth predicate leg —
  zero in-flight requests (middleware counter).
- **F3 · MAJOR — casualty list omitted the scan-blocked badge map**
  (`PaneManager._validate_results`, pinned to outlive sessions;
  "exactly the restart set" was false). **Fold:** honest casualty
  list in §3 + dated acceptance in §4.3: badge is advisory, P2-7's
  in-verb scan is the surviving enforcer.
- **F4 · MAJOR — systemd-absent foreground server would silently
  self-kill** with no resurrection path, contradicting the 10 §5
  playbook. **Fold:** arming rule — self-exit arms only under the
  unit (`INVOCATION_ID` detection); foreground `serve` stays resident
  unless the env var is set explicitly.
- **F5 · MINOR — "was-inactive" cold-start condition missed
  `failed`/`activating`/`deactivating`** (a click landing in the
  idle-exit shutdown drain is the natural boundary case). **Fold:**
  cold ⟺ snapshot state anything other than `active`.
- **F6 · MINOR — token freshness is an early readiness proxy** (the
  token is written before uvicorn binds; the draft's premise sentence
  had the order wrong). **Fold:** readiness wait = fresh token THEN
  TCP connect, one ≤5 s budget; premise corrected.
- **F7 · test/DoD gaps.** **Fold:** U13 tests now pin the
  awaiting-input teardown case, the in-flight long-request case,
  per-leg blocking, launcher not-`active` snapshot branches; DoD
  adds close-without-`q` and click-during-drain trials; ≤0/negative
  env values pinned as "disabled, never an error"; the
  decide-and-signal-in-one-loop-step note added to U13.

Verified-sound by the reviewer (kept, no change): systemd semantics
(SIGTERM-to-self → uvicorn graceful → exit 0 → `inactive (dead)`,
start-limit unreachable at human pace); check-then-signal race
(single event loop, no await between read and signal); SSE
reconnect/poll gaps (open tab always blocks via one leg); watchfiles
correctly not-activity; no sentinel/single-instance/§4.5
contradictions beyond F1/F4.

Residual risks accepted and logged: frozen/discarded browser tab
drops SSE → exit under a "sleeping" window (relaunch degradation);
any localhost probe resets the idle clock (cosmetic); boot-time
`enable --now` starts idle out after one window (harmless — unit
comment notes it).

## Round 2 — delta review (same reviewer, folds verified)

Verdict: **SOUND**. All six folds verified faithful against the
working-tree diff (F1 leg matches pane.py's `INTERRUPTIBLE_STATES`
exactly; F2's redundant SSE double-blocking noted as safe-direction;
F3/F4/F5/F6/F7 confirmed). One must-pin residual introduced by the
folds themselves, three nits — all folded before gate close:

- **R1 · MINOR (must-pin) — teardown/atomicity tension.** The F1
  teardown awaits engine calls, so "tears down ... then exits" read
  as one function call would put an `await` between predicate read
  and signal — SIGTERM under a freshly active user. **Fold:** §3 now
  pins "teardown and exit never share a step" — a sample that finds
  a parked session tears down and DEFERS; the signal fires only on a
  later sample whose predicate read reaches the signal await-free.
  Matching test pinned in U13 (request-completes-during-teardown
  blocks the signal).
- **R2 · NIT — double-click burns the 5 s budget** (second launcher
  snapshots the already-fresh token; token-change never comes).
  **Fold:** unchanged-token + successful-connect counts as ready
  (§3 launcher bullet + U13 test).
- **R3 · NIT — in-flight counter leak on cancelled handlers.**
  **Fold:** U13 pins decrement-in-`finally` + test.
- **R4 · NIT — teardown idempotence against already-closed engines.**
  **Fold:** U13 pins `close()` idempotence + test.

## Gate close

Spec gate CLOSED 2026-07-18 (delta SOUND, R1 pinned, nits folded).
The F1 judgment call (parked sessions torn down rather than blocking
— resolved toward the user's stated requirement and the 09 §4.2
ephemeral-transcript pin, alternative recorded in Y-14 decision 5)
is flagged for the user's morning review; it is spec text and freely
reversible before or after the U13 build if they prefer the
conservative posture.
