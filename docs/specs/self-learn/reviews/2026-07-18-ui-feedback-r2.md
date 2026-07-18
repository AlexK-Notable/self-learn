# Review record — UI feedback round 2 (2026-07-18, agent-built)

Three fixes from `feedback/2026-07-18-ui-feedback-02.md`, each built by
a dedicated builder agent in its own worktree (user-directed: "spawn
agents to do the actual work"), each through the standing two-gate
discipline (blind review → fold → delta; Y-15 additionally got its own
spec gate before build). Orchestrated from the main session; every
verdict below is a blind reviewer's, none self-certified.

## Fix A — scope-filtered destinations (item 3; merged 54305f7)

Builder verified the CLI's real rules first (verbs.py `_resolve_target`:
skill-md ⇒ skill scope only; reference ⇒ skill|project; claude-md ⇒
everywhere; `route` without `--dest` falls back to the proposal's own
destination — so correction must be explicit). Built:
`destinations_for_scope`/`correct_destination` (+ plain-words note),
scope-filtered cycle + Approve defaults on Detail AND bucket rows,
pane-proposal intake scope refusals, dated 09 §2.3/§4.5 notes.

Blind review: **NOT CLEAN** — the round's best find, **F1 MAJOR:
the `o`-cycle never advanced in a real browser at all** (the endpoint
read a `current` form field no template ever sent; the templates post
`dest`) — pre-existing on master since U3, entrenched by the new
endpoint tests mirroring the handler, empirically demonstrated stuck,
and plausibly the very mechanism of the live stranding (master's `o`
force-rendered skill-md on every scope). Plus F2 (client-echoed dest
on disarm/failed-confirm re-renders), F3 (resolved-record cycle,
accepted-risk), fixture flag. Folds: handler reads `dest`; a
template-truth test drives the endpoint with fields parsed from the
RENDERED form (the whole field-mismatch class now fails loudly);
`_scope_corrected_dest` makes "always scope-valid" a property on the
echo paths; scope-derived fixture defaults. Delta: **CLEAN**
(reviewer re-probed empirically — advances; 619 tests).

## Fix C — SELF_LEARN_UI_MONITOR launcher placement (item 6; merged cc1b7c5)

Launcher-only env var (X-1 posture, like SELF_LEARN_UI_BROWSER):
focus-by-address then movewindow, numeric-id→name mapping for the
already-on-target skip, ≤5 s appearance poll, silent degrade
everywhere. Blind review: **NOT CLEAN** — F1 MINOR (empirically
demonstrated rc-5 death: unguarded jq inside `$()` under set -e when
hyprctl exits 0 printing non-JSON; healed at the source in
`_ui_window_address`, also curing the pre-existing presence-check
instance), F2 (stale-address gate: `activewindow -j` must confirm OUR
window holds focus before the move — a vanished window must not move
whatever the user has focused), F3/F4 test hardening, F5 10 §1 row
re-sync. Delta: **CLEAN, mutation-verified** — the reviewer injected
four regressions and each was killed by exactly the test claiming to
pin it. Post-merge: the one-clause activewindow-gate sync into 09
§4.4 (a52a9ca); host-side value wired outside the repo
(environment.d + set-environment, SELF_LEARN_UI_MONITOR=DP-2).

## Fix B — Y-15 non-blocking pane start (items 1+5)

Spec gate first: blind review **NOT SOUND** — F1 BLOCKER (the
completion story relied on `pane_result`, which app.js deliberately
ignores — the error strip/`r` retry/result footer are all POST-swap
content that never arrives under a backgrounded first turn: the
silent wall reborn on the failure leg), F2 (the mid-turn send "guard"
did not exist — today's code would dispatch a second concurrent
engine turn), F3 (drain-task disposal unpinned — orphaned drains
publish unkeyed SSE; the r-retry same-key window could wipe a
successor's slot), F4 (Esc during the pre-connect window silently
lost), 4 MINOR, NIT. Folded (completion = pane_result-triggered
panel-GET re-fetch/swap for both legs; send guard stated as a NEW
obligation; cancel-or-await + identity guard; promptness latch;
synchronous claim; START-scoped transport sentence; starting-line
clear; named re-trials) → delta **SOUND** with three residuals
(R1 suppression belt mirroring §4.5's [data-armed] precedent; R2
at-least-once wording; R3 panel-URL data attribute) folded before
build.

Build: background `_run_first_turn` task held on the session;
`_dispose_drain` on every teardown path; identity-guarded publishes
and clears; awaiting-input-only send dispatch; pre/post-connect
interrupt latch; synchronous claim with re-guarded force/retry;
app.js completion swap with the R1 defer loop; 18 new tests incl. a
cancellation-swallowing-engine orphan test and the TestClient-lifespan
infrastructure fix (a bare TestClient runs each request on a
throwaway event loop — background drains die silently; autouse
ExitStack + portal joins are the durable pattern).

Code gate + merge + live re-trials: recorded below.

## Round-2 code gate for Fix B, merge, live trials

Code gate: **NOT CLEAN** — MAJOR-1 proven with a live repro (the
post-Result validate window entered awaiting-input before the drain
finished; the completion swap handed the user a live send form inside
it; a send there dispatched a concurrent second engine turn, with a
state-stomp cascade to a third), MINOR-1 (r-retry leaked the
predecessor's engine — one orphaned SDK child per retry), MINOR-2
(app shutdown left the free-floating drain task undisposed), 3 NIT.
Fold 4533728 (state flips to awaiting-input only after validate, in
the drain tail; retry closes the old engine; PaneManager.shutdown()
in the lifespan; while-loop re-guard; Y-9 starting-line honesty; the
F5 dispose-window test) → second delta **NOT CLEAN** on one new
empirically-proven residual the fold itself introduced (the validate
window became INTERRUPTIBLE with an Interrupt button rendered — a
stale Esc latch there replayed engine.interrupt() into the user's
NEXT turn) → fold 704f087 (per-turn latch reset at _drain entry +
mutation-checked named test) → final delta **CLEAN** (the reviewer
re-ran their own repro probes and mutation tests on the final tree).

Merged into master with A and C: **647 tests green**, src pyright
zero. Y-15's three named re-trials run live before deploy (full log:
fixtures/ui-trials.md "Y-15 re-trials"): (i) PASS vividly — instant
split, starting line already cleared by the first streamed frame,
live tool activity mid-turn, completion swap landed the result
footer; (iii) PASS — Esc during starting terminated promptly, error
strip + r + Close rendered via the completion swap; (ii)
pass-by-composition, three forcing levers honestly recorded (the
fallback model rescues a bogus model; route guards intercept a
missing record; an unreadable record 500s the page — new backlog
item), with the exception leg pinned by unit+route tests and the
client path proven by (iii).

**Round 2 gate CLOSED 2026-07-18: all three fixes shipped.**
