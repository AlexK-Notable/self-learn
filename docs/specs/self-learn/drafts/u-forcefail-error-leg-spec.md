# Spec — U-forcefail: a failed Force run says so

Status: **DRAFT r3**. Register row **FW-76**. Files in scope, and no others:
`ui/static/app.js` (the `applying` case + `renderInflight`),
`ui/src/self_learn_ui/routes.py` (`worker_kick` and `mine_run`, their failure
legs only), `ui/static/style.css` (**one** selector, §2.3),
`ui/tests/test_js_dom.py`, `ui/tests/test_routes.py`.

**Where prose and the acceptance criteria conflict, the criteria win.** This
is a one-behaviour unit: *a Force run that failed must look different from one
that succeeded, must still look different a second later, and must be
somewhere the human is looking.* Everything below that does not serve that
sentence is out of scope by construction (§5).

r2 folds a spec-gate round: the marker/role split (§2.1), the viewport leg
(§2.1, criterion B4), a discriminating B2, criteria D3 and E's reddening
mutation, and two residuals that were derivable but unstated (§5h, §5b). r3
adds §1.2's third leg — the hub-merge ordering finding, read and confirmed at
`sse.py:113-131` rather than inherited.

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
- **The two envelopes' arrival order at the client is not guaranteed**, so a
  client-side defer marker cannot be relied on to save the failure even in the
  no-redirect case. `sse.py`'s `event_stream` (`:113-131`) merges the hubs by
  holding one `get()` task per hub in a `pending` set and awaiting
  `asyncio.wait(pending, return_when=FIRST_COMPLETED)` (`:121-123`), then
  iterating the returned **`done` set** (`:124`) — set iteration order is
  arbitrary (these are `Task` objects, hashed by identity), not production
  order. And in these handlers both envelopes are *always* ready at the same
  wakeup: `_publish_applying` reaches `await q.put(...)` (`sse.py:88-90`) on an
  **unbounded** queue (`asyncio.Queue()`, `sse.py:76` / `ledger.py:499`), whose
  `put` skips its `while self.full()` wait entirely and returns
  `put_nowait(item)` — it never suspends, so the loop is never yielded to
  between the error publish and the `_force_refresh` that follows it
  (`ledger.py:516-521`, also `put_nowait`). Both tasks are therefore complete
  before the stream generator is resumed, and which envelope reaches the
  browser first is decided by set ordering. If `refresh` wins, `reload()` fires
  before the client has been told a failure happened — there is no marker to
  defer on yet. This is why §2.2 removes the refresh at the source rather than
  relying on leg (a) to hold it: a fix whose correctness depends on unspecified
  set iteration order is not a fix.

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

Two attributes on the strip element, **keyed differently on purpose** — the
split is normative, and criteria B3/D3 pin both halves:

- `data-verb-error="true"` — set whenever **the Map holds at least one failed
  entry**, even when live work is the entry currently rendering; removed
  otherwise. This is a deliberate reuse, not a new leg: `reloadDeferred()`
  leg (a) (`:550`) already queries `[data-verb-error]` document-wide, and its
  documented purpose (`:485-489`) is *"the persistent error rendering a
  broadcast reload would erase"* — precisely this case. The builder extends
  leg (a)'s comment to name the strip as a second producer. Keying it on Map
  contents rather than on what renders is what stops a failure that is
  momentarily masked by live work from being reload-erased before the human
  ever sees it (criterion D3; mutation M8 is the rendered-entry keying).
- `role="alert"` — set only while **the rendered entry is failed**; removed
  otherwise. Parity with every other error surface in this app
  (`action_bar.html:22`, `host_add_bar.html:23`), but render-scoped rather
  than Map-scoped: a Map-scoped alert role would make assistive tech announce
  every `graduating N of M` bulk progress update as an alert. The marker
  protects evidence; the role announces what is on screen.

**The viewport leg.** When the marker transitions **absent→present**, and only
then, the strip is scrolled into view with `scrollIntoView({block: "nearest"})`
— the idiom this file already uses at `:92`, `:127` and `:378`. This is not
polish; without it the fix is invisible for the same reason FW-71's keyboard
`b` defect was. The strip is a static block at the top of `<body>`
(`base.html:57`; `.applying-strip` at `style.css:267-281` sets no
`position`), both Force-run buttons live in the **last two** sections of the
front page (`index.html:114-121`, `:183-190`), and §2.2 deliberately removes
the redirect that was the only thing repositioning the viewport. A human who
scrolls down to click Force run and gets a failure rendered off-screen above
them has been told nothing — `app.js:74-88` records this app's own measured
instance of exactly that class (*"a scrolled-to-bottom repro: identical
before/after screenshots, the toggled element's own `getBoundingClientRect()`
landing entirely negative"*), fixed with this same call. `block: "nearest"` is
a no-op when the strip is already in view, so the common case costs nothing.
**Accepted cost, stated:** an observer tab that did not act is also scrolled,
once per failure episode. The client cannot distinguish its own action from
another tab's — the envelope carries no actor, and inventing an actor token is
the second mechanism S-20 forbids. Showing a real failure is judged worth one
minimal scroll.

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
control, no timer, no new `reloadDeferred` leg.

**`style.css` is in scope for exactly one selector** —
`.applying-strip[data-verb-error]` — and nothing else in that file. It must be
declared **after** `.applying-strip[hidden] { display: none }`
(`style.css:279`), or must not set `display` at all: that override is the only
thing making `hidden` beat the block's own `display: flex`, and a later
same-specificity rule that reintroduces `display` pins the strip permanently
visible. The colour itself is asserted by no criterion — per S-20, contrast and
palette stay a human acceptance item. The rule is permitted rather than
required: no criterion fails without it.

## 3. Acceptance criteria

Every criterion below must **fail against the unmodified tree**, with two
named exceptions: **A0 and C0 are positive controls and must PASS on master**
— they assert behaviour this unit preserves (A0) or machinery the other
criteria depend on (C0). A pre-build run that reddens A0 or C0 means the
harness is broken, not that the unit is needed; the red-run record should read
"A1–A3, B, C1–C2, D, E, F red; A0, C0 green". Judged
under FW-81's standing rule — no NEW failures against the 14 environmental
ones (`14-forward-work-map.md:136`). **No new browser test may use
`.click()`**: every one of the 14 fails on `Locator.click` actionability on
this host, and the SSE-push-driven tests in the same class pass. All client
criteria drive `server.push_applying` / `server.push_refresh` only — plus, for
B4 alone, a scroll (`page.mouse.wheel` / `page.evaluate`), which is not a
click and does not touch the actionability path the 14 fail on.

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
- **B2 — a DISCRIMINATING snapshot comparison.** *Not* applying-vs-error:
  measured at the spec gate, that pair already differs on **master** (the
  strip merely disappearing changes the body snapshot), so it can never
  redden. Compare instead the two **terminal** states at the same key from the
  same start: `body.aria_snapshot()` after `error(worker,kick)` vs after
  `done(worker,kick)`. On the fixed tree they differ (`- alert: failed …` vs
  nothing); on master both terminals hide the strip and the snapshots are
  identical, so B2 is red pre-fix. S-20's oracle is kept, and it is now
  load-bearing rather than decorative.
- **B3** the strip carries `data-verb-error` **and** `role="alert"` (both, here
  — the rendered entry is the failed one, so the two keyings coincide; D3 is
  where they must not).
- **B4 — the failure is where the human is looking.** With the page scrolled
  to the bottom (`page.mouse.wheel` or `window.scrollTo(0, document.body.
  scrollHeight)` — never a `.click()`), push `start` then `error`, then assert
  `expect(strip).to_be_in_viewport()`. Verified available in this venv's
  Playwright build. `to_be_visible()` must NOT be used as the oracle here: a
  non-empty box does not imply viewport intersection, which is precisely how
  this defect class hides.

**C — the failure survives a broadcast refresh.** After B's error frame:

- **C0 — positive control:** on a freshly loaded page with an empty Map,
  `_arm_reload_sentinel(page)` then `server.push_refresh("front")` reloads
  (`_assert_reloaded`). Without C0, C1 passes on a harness whose refresh never
  arrives.
- **C1** with the failed entry present, `_arm_reload_sentinel(page)` then
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
- **D3 — the marker outlives the render it is not attached to.** This is the
  criterion that makes §2.1's Map-vs-render keying testable; without it a
  builder writing `if (rendered.failed) strip.setAttribute(...)` passes every
  other criterion here (D asserts only what renders; C is scoped to a
  pure-failure Map; B3's two keyings coincide). Push `error(worker,kick)` then
  `start(route, REC_BRIEF)`; assert (i) the strip renders `applying` /
  `route → …` **and** carries `data-verb-error`, and — per §2.1's split —
  does **not** carry `role="alert"`; (ii) `_arm_reload_sentinel(page)` then
  `server.push_refresh("front")` → `_assert_deferred`; (iii) `done(route, …)`
  → the strip reads `failed`. The failure survived a broadcast refresh it was
  not even rendering at the time.

**E — unmatched-`error` hygiene.** Two arms, each with its own reddening
mutation (M7, M11):

- **E1** an `error` frame for a key this page never saw start renders the
  failed strip — a real failure elsewhere is still a failure.
- **E2** an `error` arriving while a `bulk` entry is live does not displace the
  bulk render. Note the fixture must set the bulk entry **first**: with bulk
  inserted first, M6 (first-insertion-order-wins) still renders bulk and E2
  would be vacuous, which is why E2's mutation is M11 (failed-wins-outright),
  not M6.

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
| M4 | re-add `_force_refresh` to the failure leg of one route | A2 (that route) |
| M5 | re-add the `HX-Redirect` header to the failure leg of one route | A1 (that route) |
| M6 | drop the render precedence — first-insertion-order wins outright | D1 |
| M7 | make `error` a no-op on an absent key (`if (map.has(key))`) | E1 |
| M8 | key the marker on the *rendered* entry instead of Map contents | **D3** |
| M9 | drop the `releaseReload()` transition call | C2 |
| M10 | publish `"done"` unconditionally from `worker_kick` (the fail-open shortcut) | A3 |
| M11 | render precedence checks `failed` **before** the `"bulk"` key — the plausible "errors are important, show them first" edit | E2 |
| M12 | drop the `scrollIntoView` call on the absent→present transition | B4 |
| M13 | set `role="alert"` from Map contents instead of the rendered entry | D3(i) |

M4/M5 are the two halves of §1.2 and are the mutations most likely to survive
a client-only review. M8 is the subtle one — it passes B, C and D1/D2, and
only D3 sees it. M10 fails A3 alone: B is driven by `server.push_applying`
directly (`test_js_dom.py:138`), so no route participates in it and no
route-side mutation can redden it.

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
reconcile`), which the CLI prints to stderr. See (c). **And this is the one
case where §2.2's dropped `_force_refresh` costs something real:** it is the
only failure outcome in scope that *writes*, so no tab's bucket table or
status strip updates until someone navigates. Largely self-cancelling — leg
(a) would have deferred that broadcast anyway while the failure is on screen
— but the refresh is genuinely not merely deferred here, it is never sent.
Accepted: the alternative is erasing the only report of the failure to
refresh a view of records the human has just been told are uncommitted.

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

**(g) Out of scope entirely:** the bulk-graduate failure path, FW-38's
reconnect window, FW-77's keyboard-unreachable glosses, and any change to
`sse.py`.

**(h) The blast radius is app-wide, deliberately, and here is its full
shape.** `_publish_applying(..., "done"/"error")` has **five** call sites, not
two: `routes.py:1106` (`worker_kick`), `:1133` (`mine_run`), `:1773`
(`action_confirm`), `:2267` (the route retry) and `:2753` (the proposal-bar
verb). The client leg keys on the envelope's `state`, never on which route
sent it, so **every** failed verb-confirm now also renders a persistent failed
strip in **every** connected tab, and every one of those tabs holds
reload-defer leg (a) until it navigates. The acting tab's dismissal of its own
server-rendered error bar does not clear the strip — nothing publishes a
terminal for that key afterwards — so the hold outlives the bar that caused
it. Three things bound the cost, and they are why this is accepted rather than
scoped away: (i) **a failed verb wrote nothing**, so the deferred refresh is
deferring a view of state that did not change — the sole exception is residual
(b)'s `landed-uncommitted`; (ii) `routes.py:1776` still force-refreshes on
that same leg, so the broadcast is deferred, never dropped, for the four
non-Force routes; (iii) every hold has a user-reachable release (navigation).
**The refused alternative, named:** scoping the failed render to
`verb ∈ {worker, mine}` would make the Map's render depend on verb identity
rather than frame state — a second mechanism keyed on a list that rots as
routes are added, which is exactly what S-20 exists to prevent. Uniform is
also the more honest posture: an observer tab currently learns nothing when a
verb fails in another tab.

## 6. Merge obligations

- **Re-point FW-82's prerequisite.** Its row currently reads *"(4) FW-76 as a
  prerequisite"* (`14-forward-work-map.md:137`). Per residual (a), landing
  this unit does **not** satisfy what that clause needs — a machine-readable
  success signal. At merge, that clause must be re-pointed at the new
  exit-code row (a) recommends, or FW-82 will read as unblocked by a unit that
  did not unblock it.
- **FW-76's own row** takes the usual FIXED annotation, and should carry
  residuals (a), (b) and (h) by name — (h) especially, since it changes
  behaviour at three routes this unit's title does not mention.
