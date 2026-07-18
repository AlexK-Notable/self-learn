# Build-gate review record — U13 idle lifecycle (2026-07-18)

Build of 10 §3 U13 (Y-14, spec gate closed same day —
`2026-07-18-idle-lifecycle-spec.md`). Built in the `u13-idle-lifecycle`
worktree during the overnight autonomous run; base c9270ed.

## What was built (commit 36cbe62 + fold ac4c070)

- `self_learn_ui/idle.py` (new): `ActivityTracker` (in-flight counter +
  completion-stamped monotonic clock, injectable), `IdleMonitor`
  (five-legged predicate; teardown-defers-exit per delta R1; final
  predicate-read → signal with no await between; exception-guarded
  sampling loop), `resolve_idle_window` (explicit env wins, ≤0
  disables; default 600 only under `INVOCATION_ID`), `default_exit`
  (SIGTERM to self).
- Middleware: wraps every dispatch in `request_started`/`finished`
  (finally — delta R3); SSE generator stamps the clock on disconnect
  (the middleware's stamp for a streaming response fires at connect);
  hubs expose `subscriber_count`; `RealRunner.busy` =
  `_lock.locked()`; `PaneManager.has_interruptible_session` /
  `teardown_parked` (slot clears via the Y-13 clear-set; engine
  close/interrupt verified idempotent — delta R4).
- `EnvConfig.ui_idle_exit_seconds` (None = unset, keyword-only safe);
  app factory starts the monitor when the resolved window > 0 and
  cancels it at shutdown; `serve` wires `resolve_idle_window`.
- Launcher readiness wait exactly per the §3 pin (snapshot state +
  token before start; cold ⟺ not `active`; one ≤5 s budget:
  fresh-token then `/dev/tcp` connect; unchanged-token+connect early
  success — delta R2; timeout degrades to the 403 path); unit header
  re-worded to the Y-14 posture.
- Tests: 590 UI (32 new) + 894 CLI green; pyright clean on `src` and
  the new/modified test files (pre-existing test-side pyright noise in
  untouched files left as found).

## Blind code review (agent afa89983dee12e564; reviews/ off-limits)

Verdict: **CLEAN** — no BLOCKER/MAJOR; 2 MINOR + 3 NIT. Notable: the
reviewer verified the two riskiest mechanisms EMPIRICALLY on the
installed starlette/uvicorn (not from comments): (1) a mid-POST client
hard-disconnect does NOT cancel the handler on this stack — the agent
turn completes and parks, so the walk-away path holds even mid-turn;
(2) SSE under BaseHTTPMiddleware decrements at connect time and the
generator's `finally` really fires at tab-close, so the compensating
stamp makes the window count from last-tab-close.

- MINOR 1 — "cancelled at shutdown" claimed, never asserted →
  **folded**: post-lifespan `cancelled()/done()` assertion.
- MINOR 2 — `IdleMonitor.run()` had no exception guard (a raising
  sample would kill the monitor silently = unobservable
  resident-forever) → **folded**: log-and-continue guard +
  `test_monitor_survives_a_raising_sample`.
- NIT (delayed token) → **folded**: `threading.Timer` variant pins
  the actual polling (token + listen arrive at t=0.4 s).
- NITs kept as accepted: un-awaited `cancel()` (existing app pattern),
  sleep-counted 5 s budget (spec "~" tolerance).

Follow-up chased after the review: the "local probes reset the clock"
residual, one hop further for STALE windows (10 s poll fallback after
a deploy restart). Benign by construction: the fallback is
`window.location.reload()`, which lands the stale window on the 403
page — which carries no JavaScript — so a stale window stamps the
clock exactly once and goes permanently quiet.

## Delta re-check

Verdict: **CLEAN** (36cbe62..ac4c070; reviewer re-ran the suite —
590/590 — and read the diff in full). Both MINOR folds verified as
genuine regression traps (deleting the lifespan `cancel()` fails the
new assertion; reverting the exception guard times out the new
survive-a-raising-sample test); the delayed-token test verified as
pinning real polling with the honest write-before-bind ordering. One
cosmetic flag-only note (the flaky-leg test pokes a private
attribute). The stale-window residual chase CONFIRMED against
app.js + the 403 page source, with a refinement: worst case is up to
TWO stamped completions (EventSource's one-shot 403 + one reload onto
the script-free 403 page), bounded and self-quenching — idle exit
delayed by at most one window; no spec change needed.

## Live-trial BLOCKER + second delta

The DoD trial (a) caught a production BLOCKER both blind reviews had
passed as sound: **SIGTERM-to-self exits 143** — uvicorn 0.29+
`capture_signals` restores default handlers and re-raises the captured
signal after graceful shutdown, so the process dies BY SIGNAL and
`Restart=on-failure` RESTARTS it (three cycles in the journal; the
exact opposite of stay-down). Fix (afc1495): `serve` constructs an
explicit `uvicorn.Server`; the idle callback sets `server.should_exit`
via a holder dict filled before `run()` — same graceful path, genuine
return, real exit 0. `idle.default_exit` demoted to documented
last-resort fallback. Dated corrections: 09 §3 mechanism sentence,
Y-14 decision (2), 10 §3 U13 row, build-findings appendix (lesson
recorded: signal/systemd semantics are live-trial-only facts).

Second delta (same reviewer): **CLEAN** — verified against installed
uvicorn 0.51 source that `handle_exit` does nothing but set the flag
(identical graceful path minus the re-raise); holder late-binding
airtight for every armable path; `default_exit` production-unreachable;
the reworked serve test genuinely traps a regression to `uvicorn.run`
(the holder stays unfilled → the final should_exit assertion fails).
One NIT folded post-verdict: the empty-holder branch now logs instead
of silently no-opping.

## Live trial (DoD)

All four trials run 2026-07-18 (full log:
`fixtures/ui-trials.md` "U13 DoD"): **(a)** FAILED-then-PASS — the
143 BLOCKER above, then `Result=success ExecMainStatus=0`, stays
down; **(b)** PASS — launcher cold start opens tokened, no 403;
**(c)** PASS — walk-away path with the delta-R1 two-sample
choreography visible in ui.log (teardown+defer at sample 1, clean
exit at sample 2, `SERVER_EXIT=0`), foreground-explicit arming leg
proven en route; **(d)** attempted — the no-connection drain is
sub-200 ms and unhittable by timed click; degrades to (b)'s path,
hermetic tests carry the not-`active` condition.

**Gate CLOSED 2026-07-18: U13 shipped** (merge d5baa9f + live-trial
fix afc1495 + NIT fold).
