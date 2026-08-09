# Spec — U-forcefail: a failed Force run says so

Status: **DRAFT r1**. Register row **FW-76**. Files in scope, and no others:
`ui/static/app.js` (the `applying` case + `renderInflight`),
`ui/src/self_learn_ui/routes.py` (`worker_kick` and `mine_run`, their failure
legs only), `ui/tests/test_js_dom.py`, `ui/tests/test_routes.py`.

**Where prose and the acceptance criteria conflict, the criteria win.** This
is a one-behaviour unit: *a Force run that failed must look different from one
that succeeded, and must still look different a second later.* Everything
below that does not serve that sentence is out of scope by construction (§5).

## 1. The defect — two halves, both live today

### 1.1 The client half: every terminal state is the same terminal state

`app.js:720-733` handles `type: "applying"`. `state === "start"` sets the
keyed entry; a bare `else` runs `inflight.delete(...)` for **both** `"done"`
and `"error"`. `renderInflight` (`:638-651`) hides the strip when the Map is
empty. So the rendered difference between a successful Force run and a failed
one is nil: strip appears, strip disappears. Measured by the 2026-08-06 blind
code gate against a deliberately failing runner — `strip seen → hidden_after=True;
error/failed text on page after? []`.

The server side is already correct and is **not** the defect:
`routes.py:1103-1110` (`worker_kick`) and `:1130-1137` (`mine_run`) publish
`_publish_applying(..., "done" if result.ok else "error")`, and `sse.py:46-47`
pins `state ∈ start | done | error`. `test_routes.py`'s
`test_worker_kick_emits_error_state_on_nonzero_exit` and its `mine_run`
sibling assert that emission and pass today — they read as though failure
reaches the human. It does not.

### 1.2 The server half: the failure is erased milliseconds after it is published

Both handlers finish, on **every** outcome, with `_force_refresh(request,
"front")` and an unconditional `200` + `HX-Redirect: /`. Both of those wipe
the only thing that carries the failure:

- `HX-Redirect` is handled by htmx before any swap logic and unconditionally —
  `if(T(n,/HX-Redirect:/i)){…Q.location.href=…;return}` in the vendored
  `htmx-2.0.9.min.js`. A full navigation follows; the new document's
  `inflight` Map is empty and `base.html:57`'s strip renders `hidden`.
- `_force_refresh` broadcasts a `refresh` envelope to every connected tab;
  `app.js:694` routes it to `reload()`, which is `window.location.reload()`
  (`:559-565`).

This matters because it is the same bug the codebase has already named. From
`app.js`'s own leg (f) comment (`:529-533`): *"a FakeRunner test never pushes
the post-subprocess refresh, so a persistent strip with no defer marker looks
fine under test and gets reload-wiped by the very next broadcast SSE refresh
in production — this project's signature bug, landing again at the exact file
being extended."* A client-side error leg alone would ship exactly that: green
in `test_js_dom.py` (which pushes frames at a page nobody redirected) and
invisible in the product. Fixing §1.1 without §1.2 is not a smaller version of
this unit; it is a unit that does not work.

### 1.3 One existing test pins the defect and must be rewritten

`test_js_dom.py::TestApplyingStripClientRendering::test_4_applying_error_hides_strip`
(currently `:1690-1696`) asserts the strip goes hidden on `"error"`. That is
the behaviour this unit removes. Rewriting it is **authorised here** and named
as criterion F; silently deleting it is not.

## 2. The change

### 2.1 Client — the Map gains a fourth rule, not a second mechanism

S-20's posture holds (`03-decisions.md` S-20): one keyed Map, render derived
from its contents after every operation, never a parallel variable. The rules
become:

| frame | rule |
|---|---|
| `start` | `set(key, {badge:"applying", detail:"<verb> → <id>", failed:false})` — unchanged |
| `done` | `delete(key)` — unchanged, and it removes a `failed` entry at that key too (§4) |
| `error` | `set(key, {badge:"failed", detail:"<verb> → <id>", failed:true})` — **new**; replaces an applying entry at the same key, and CREATES one when the key is absent |
| connection loss | `clear()` — unchanged (§5) |

`renderInflight` (hidden iff `size === 0`, unchanged) picks, in order: the
`"bulk"` entry if present; else the first entry in insertion order with
`failed !== true`; else the first entry. **Live work outranks a failure
notice** — without this a persisted failed entry sitting first in insertion
order would mask a later in-flight verb, which is S-20's own founding defect
class re-introduced.

Two attributes, set on the strip element when **the Map holds at least one
failed entry** (not merely when a failed entry is the one rendering) and
removed otherwise:

- `data-verb-error="true"` — this is a deliberate reuse, not a new leg.
  `reloadDeferred()` leg (a) (`:550`) already queries `[data-verb-error]`
  document-wide, and its documented purpose (`:485-489`) is *"the persistent
  error rendering a broadcast reload would erase"* — precisely this case. The
  builder extends leg (a)'s comment to name the strip as a second producer.
- `role="alert"` — parity with every other error surface in this app
  (`action_bar.html:22`, `host_add_bar.html:23`).

Keying the marker on Map contents rather than on what renders means a failure
masked by live work still cannot be reload-erased before the human sees it.

When a render **transitions the marker from present to absent**, and only
then, `renderInflight` calls `releaseReload()`. This is the leg's release:
deferred-never-dropped is the invariant, and an unconditional call would give
the pre-existing applying path a reload timing it does not have today.

### 2.2 Server — do not erase what was just published

In `worker_kick` and `mine_run`, on `not result.ok` only: **no
`_force_refresh`, no `HX-Redirect`**. The response stays `200`; both buttons
carry `hx-swap="none"` (`index.html:118-119`, `:187-188`), so a body-less 200
swaps nothing and the human stays on the page they clicked from, with the
failure showing. This mirrors `action_confirm`'s shape (`routes.py:1775-1795`:
`if not result.ok:` takes a different response path), at this route's scale.

The success path is byte-for-byte unchanged: refresh, redirect, 200.

### 2.3 Not changed

The `applying` envelope keeps its four fields — no `text`/`stderr` field, no
`sse.py` signature change, no `push_applying` fixture change. No dismiss
control, no timer, no new `reloadDeferred` leg, no new CSS requirement
(colour/contrast stay a human-taste item per S-20; a builder adding a
`.applying-strip[data-verb-error]` rule must not disturb the
`.applying-strip[hidden] { display: none }` override at `style.css:279`, which
is what makes `hidden` beat `display: flex` at all).

## 3. Acceptance criteria

Every criterion below must **fail against the unmodified tree**; running them
pre-build and recording the failures is this unit's positive control. Judged
under FW-81's standing rule — no NEW failures against the 14 environmental
ones (`14-forward-work-map.md:136`). **No new browser test may use
`.click()`**: every one of the 14 fails on `Locator.click` actionability on
this host, and the SSE-push-driven tests in the same class pass. All client
criteria drive `server.push_applying` / `server.push_refresh` only.

**A — the server stops erasing the failure** (`test_routes.py`, extending
`TestForceRunApplyingFeedback`; `FakeRunner.queue_result(RunResult(1,
stderr="boom"))` is the failing-runner seam already used at `:3315`/`:3339`).
For `/worker/kick` and `/mine/run` alike:

- **A0 — positive control, asserted first:** with the default (succeeding)
  runner, the response still carries `hx-redirect: /` and a `front`-scope
  refresh event is still published. (`worker_kick`'s half exists at
  `test_redirects_to_front`/`test_forces_a_front_scope_refresh`; `mine_run`
  has no such test today — the control adds it.)
- **A1** with a failing runner, the response carries **no** `hx-redirect`
  header.
- **A2** with a failing runner, **no** refresh event is published (subscribe to
  the hub before the POST; the queue is empty after it).
- **A3** the `error` applying frame is still published — A1/A2 must not be
  reachable by not publishing at all.

**B — the strip renders the failure** (`test_js_dom.py`, in
`TestApplyingStripClientRendering`). Push `start` for `("worker","kick")`,
snapshot, push `error`:

- **B1** the strip is visible, `#self-learn-ui-applying-badge` reads `failed`,
  `#self-learn-ui-applying-text` reads `worker → kick`.
- **B2** `page.locator("body").aria_snapshot()` differs from the snapshot taken
  in the `applying` state — S-20's pinned oracle, not a source-text assertion.
- **B3** the strip carries `data-verb-error` and `role="alert"`.

**C — the failure survives a broadcast refresh.** After B's error frame:

- **C0 — positive control:** on a freshly loaded page with an empty Map,
  `_mark_nav(page)` then `server.push_refresh("front")` reloads
  (`_assert_reloaded`). Without C0, C1 passes on a harness whose refresh never
  arrives.
- **C1** with the failed entry present, `_mark_nav(page)` then
  `server.push_refresh("front")` does **not** reload (`_assert_deferred`), and
  the strip still reads `failed`.
- **C2** pushing `done` for the failed key clears the entry, and the deferred
  reload then fires (`_assert_reloaded`) — the leg releases.

**D — a failure notice never masks live work.** Push `error` for
`("worker","kick")`, then `start` for `("route", REC_BRIEF)`:

- **D1** the strip renders the applying entry (`applying` / `route → …`), not
  the failed one, while both are in the Map.
- **D2** on `done` for the route key, the strip returns to rendering the failed
  entry — the failure was held, not dropped.

**E — unmatched-`error` hygiene.** An `error` frame for a key this page never
saw start renders the failed strip (a real failure elsewhere is still a
failure); an `error` arriving while a `bulk` entry is live does not displace
the bulk render (D's precedence rule, bulk arm).

**F — the pinning test is rewritten.**
`test_4_applying_error_hides_strip` becomes `test_4_applying_error_shows_failed_strip`
asserting the opposite, with a comment naming FW-76 so a later editor does not
"restore" it. `test_3_applying_done_hides_strip`, `test_2b`, `test_6`, `test_7`,
`test_8`, `test_8b`, `test_9`, `test_9b` must pass unchanged.

### 3.1 Mutation plan

Each mutation is one edit to production code; the named criterion must go red.

| # | One-line edit | Must fail |
|---|---|---|
| M1 | restore the bare `else { inflight.delete(...) }` in the applying case | B |
| M2 | keep the failed entry but leave `badge: "applying"` | B1 |
| M3 | set the failed entry without the `data-verb-error` marker | B3, C1 |
| M4 | re-add `_force_refresh` to the failure leg of one route | A2 (that route), C-in-production |
| M5 | re-add the `HX-Redirect` header to the failure leg of one route | A1 (that route) |
| M6 | drop the render precedence — first-insertion-order wins outright | D1 |
| M7 | make `error` a no-op on an absent key (`if (map.has(key))`) | E |
| M8 | key the marker on the *rendered* entry instead of Map contents | D-with-C: a refresh while live work masks the failure erases it |
| M9 | drop the `releaseReload()` transition call | C2 |
| M10 | publish `"done"` unconditionally from `worker_kick` (the fail-open shortcut) | A3, B |

M4/M5 are the two halves of §1.2 and are the mutations most likely to survive
a client-only review; M8 is the subtle one — it passes B and C1 and only fails
when a failure and live work coexist.

## 4. Builder decisions, made here rather than left open

- **`done` deletes a `failed` entry at the same key.** No producer publishes a
  terminal twice for one key (each route publishes exactly one), so this cannot
  erase an unseen failure, and it is what gives C2 a user-reachable release.
- **The badge carries the whole visible delta** — detail text stays
  `<verb> → <id>`, identical to the applying state. "failed  worker → kick"
  reads correctly; "failed  worker → kick failed" does not.
- **New tests live beside their siblings**: A in
  `test_routes.py::TestForceRunApplyingFeedback`, B–F in
  `test_js_dom.py::TestApplyingStripClientRendering`. No new file.
- **No status-code change.** `200` with no redirect is sufficient under
  `hx-swap="none"`; `204` would be equivalent and is not worth the churn.

## 5. Declared residuals — recorded, not fixed

**(a) The CLI's own fail-open exits are a different unit's, and cannot honestly
be fixed from here.** `self-learn worker kick` returns `EXIT_OK`
unconditionally (`cli.py:747-750`) for all four outcomes —
`spawned | absorbed-window | absorbed-race | disabled` — so a kick that did
nothing because autokick is disabled reaches this UI as `result.ok is True`
and this unit's error leg correctly never fires. `mine run` is the same shape
for `held-gate` (`EXIT_OK if result.status != "failed"`, `cli.py:666`). The UI
cannot distinguish these: the outcome is printed to **human stdout**
(`print(f"worker kick: {outcome}")`), `worker kick` has no `--json` form
(`cli.py:365-367`), and `RunResult.evidence` parses `--json` envelopes only —
reading it would violate the ratified "never by parsing human-formatted
stdout" contract that `runner.py`'s own docstring restates from `07 §4`. The
honest fix is an exit-code contract change in the CLI, whose blast radius is
the systemd units, the miner's callers and their tests — out of proportion to
this unit and not adjudicable behind a UI gate. **Consequence for FW-82,
stated plainly:** this unit gives the *human* a truthful Force-run signal; it
does not give *automation* one. If FW-82's prerequisite was the machine-
readable signal, that prerequisite is this paragraph's exit-code unit, not
this one. Recommended as a new register row at merge; this spec does not edit
the map.

**(b) `mine run`'s `landed-uncommitted` exits `7`** (`gitops.EXIT_HALF_WRITTEN`),
so `result.ok` is False and the strip will read `failed` for an outcome that
wrote records but could not commit them. That is not a false statement — the
run did fail — but the strip does not carry the recovery (`self-learn
reconcile`), which the CLI prints to stderr. See (c).

**(c) The strip names the failure, not its cause.** The envelope carries no
text and this unit does not add one. Cause discovery stays with `worker.log` /
`mine status`. Note that the front page will not fill the gap after the fact:
its miner line is built from `_latest_ok_run` (`models.py:981-988`), which
skips every `failed` run — so a page reload genuinely shows nothing new, which
is why §2.2 stops the reload rather than relying on it.

**(d) SSE connection loss still clears the failure.** `source.onerror`'s
`clear()` (`app.js:681`) drops failed entries with everything else. Unchanged
on purpose — S-20's R5-M1 refused a timer here, and the recovery (a late frame
re-populating the Map) does not apply to a terminal that already fired. Same
family as FW-38's disclosed silent window.

**(e) No explicit dismiss.** Releases are: a later run of the same verb, a
`done` for that key, navigation, or SSE loss. While the marker holds, that tab
defers broadcast reloads and may go stale — the accepted posture already
documented for legs (d)/(f) (`app.js:541-543`: *"files stay truth and every
hold has a user-reachable release"*).

**(f) The no-JS path is unchanged.** With htmx absent the `<form>`'s native
submit already lands on a bodyless 200 today (a plain browser ignores
`HX-Redirect`); removing that header on failure changes nothing there.

**(g) Out of scope entirely:** the three verb-confirm routes' own error
rendering (they already have a server-rendered bar and now additionally get a
strip — deliberate, one Map, and asserted only by not breaking their existing
tests), the bulk-graduate failure path, FW-38's reconnect window, FW-77's
keyboard-unreachable glosses, and any change to `sse.py`.
