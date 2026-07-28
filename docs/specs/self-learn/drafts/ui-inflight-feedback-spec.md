# Spec — close the in-flight feedback gap on the G-3 surface, and put perceptual assertions underneath it

**Status: SHIPPED** — spec gate SOUND at round 8 (2026-07-24); builder
landed `f69d38e`, ratified as `03` S-20. *(Header corrected 2026-07-27:
read "SOUND", i.e. gated-but-unbuilt, after shipping.)*
Ready to build.

**§4.3's mechanism was re-designed at R6** — a
counter-plus-flag replaced by a keyed Map — after five consecutive rounds
found defects in it, the last three sharing one shape (new state added
without reconciling an older rule that touched it). The Map dissolves all
six structurally; see §4.3's table.

At R7 the reviewer implemented §4.3/§5.1 as written and ran all twelve
sequences and all fourteen mutations mechanically: **the mechanism came back
clean**, and both remaining findings were in the mutation plan, not the
design. At R8 it added a **20,000-case randomized fuzz** over interleavings
of 1–3 concurrent `applying` verbs, 0–2 bulk runs of size 0–4 with random
failure points, and 0–2 injected SSE losses at random positions, per-stream
order preserved: **20000/20000 ended Map-empty and strip hidden, 0
violations.** That searches a space neither author nor reviewer hand-picked,
and is the result the SOUND verdict rests on.

(Blind spec gate: R1 NOT SOUND 4B/7M/5m; R2 NOT SOUND 3B/2M/2m; R3 NOT
SOUND 2B/3M/1m; R4 NOT SOUND 1B/2M/3m; R5 NOT SOUND 0B/1M/1m; R6 NOT SOUND
0B/1M; R7 NOT SOUND 0B/1M/1m; **R8 SOUND** — all folded.
R3's M1 — that a spec cannot self-authorize amending a ratified name — was
routed to the human and ratified 2026-07-24. R4 verified the strip's
counter returns to zero across all seven frame sequences; the remaining
findings were a dead mutation, one missing test, and three consistency
defects.)
**Date:** 2026-07-24.
**Unit:** 1 of 2. Unit 2 (a reusable, project-agnostic perceptual-testing
harness in its own repository) is parked — see §9.

## 0. Rules for the builder (read first)

1. **Sandbox discipline is absolute.** Dev/test ALWAYS redirect
   `SELF_LEARN_HOME`, `XDG_CACHE_HOME`, `SELF_LEARN_CLAUDE_DIR`,
   `SELF_LEARN_TRANSCRIPTS_DIR`. NEVER write, commit, or mutate the real
   `~/.self-learn`, `~/.claude`, or the chezmoi source tree.
2. **Leave the tree UNCOMMITTED.** The blind code gate reads the working diff.
3. **Every verification command runs from a proven cwd.** Print `pwd`
   beside any `git grep`/`find`/`git log` used as a gate; pathspecs are
   cwd-relative and a zero from the wrong directory is a silent false pass.
   Pair every "expect zero" with a positive control that must still match.
   (`lrn-ea833a5b`. This trap has now fired five times in this corpus —
   including once at the R2 gate, where a serialization check scoped to
   `routes.py` alone concluded verbs are not serialized. They are, in
   `runner.py`. Scope your pathspec to the whole subsystem.)
4. **Never `git checkout -- <file>`** to revert a mutation; it discards the
   whole uncommitted diff. Revert by reverse-`Edit`.
5. Line numbers are as-of 2026-07-24 and will drift. Quoted anchor text is
   authoritative, not the number.
6. **The oracle has a measured blind spot (§4.4). Respect it.** Never assert
   a colour, opacity, geometry, or cursor fact through `aria_snapshot()` or
   `is_visible()`. Those get a targeted computed-style assertion or nothing.
7. **`to_have_text` is not a visibility assertion.** Text assertions pass on
   a `display: none` subtree. Anything claiming a human can see something
   must use `to_be_visible()`, and where the spec says so, snapshot
   inequality as well.

## 1. Problem statement

The G-3 surface is good at reporting that something **broke** and silent
about reporting that something is **happening**.

`09 §5`'s fifteen-row degradation contract is largely implemented — error
strips carry verb stderr verbatim, the degraded-record view salvages what
it can, the resolved-elsewhere banner fires, the reconnect strip exists.
That half is sound.

The progress half is absent. Two SSE envelopes exist for it, are published
by the server, and are discarded by the browser. Forty-three htmx verbs
have no in-flight affordance. No test could detect any of it, because the
suite asserts DOM existence and never rendering.

### 1.1 Why the tests could not have caught it

`09 §7`: *"Browser-level checks … run via Playwright … as acceptance items;
CI stays at the httpx/pure-function level. **Visual polish trials are
acceptance items, not CI items.**"* `10 §4` (line 772) concurs.

A ratified boundary, and the human half was genuinely exercised —
`fixtures/ui-trials.md` is 709 lines across eighteen sessions. It is
nonetheless where these defects lived, because "is this perceptible at all"
is not a matter of taste. §7 amends it.

## 2. Scope rulings

**R-1 — Indicators on resolution verbs only:** the three confirm routes and
the bulk-graduate loop. The rest are deferred pending **measured** latency
(§9.2). *This is not a claim the others are fast — the pane verbs launch
agent sessions. It is a refusal to decide without measurement.*

**R-2 — Perceptual assertions cover NEW feedback only.** (§9.1)

**R-3 — The coverage work rides along:** ten never-pressed keymap actions,
two never-asserted banners.

**R-4 — Audio is out of scope entirely.**

**R-5 — No harness generality.** Nothing here is built "for reuse".

**R-6 — Three scope expansions, compelled by the gate, NOT discretionary:**

- **`routes.py`** — R-1's bulk indicator cannot work against an emitter that
  narrates no first item and emits no terminal frame (F5).
- **`keymap.py`** — R-3 mandates fixing all ten actions; one is bound to a
  name no template carries (F6).
- **`tests/test_keymap.py`** — the F6 fix renames a **ratified** action name,
  which three existing tests pin. See §5.5; recorded in §7.2.
  **Ratified by the human on 2026-07-24**, on the R3 gate's correct
  objection that a spec cannot self-authorize amending corpus-governed
  names: R-6 supplies the scope, the human supplies the authority.

Each is the minimum to deliver already-ratified scope.

## 3. Findings

All of F1–F4, F7 were independently re-verified at the R1 gate with live
positive controls.

### F1 — Both in-flight SSE envelopes are built and discarded

`09 §3`: *"further resolution submissions are **disabled with a visible
'applying…' state (SSE)**, and **bulk loops render per-item progress**."*

| | `applying` | `bulk_progress` |
|---|---|---|
| Envelope | `sse.py:46` | `sse.py:51` |
| Published | `routes.py` 1205/1207, 1577/1579, 2002/2004 | `routes.py:2227` |
| Client | `app.js:583-586` `default:` — ignored | same branch |
| CSS | `.badge-applying`, `style.css:541`, no template ref | none |

`sse.py:13` quotes the obligation in its own docstring. Three of four layers
present; the missing one is the only one a human perceives.

### F2 — Forty-three htmx verbs, no in-flight affordance

No template carries `hx-indicator`/`hx-disabled-elt` (39 `hx-post` + 4
`hx-get`; only matches repo-wide are inside vendored `htmx-2.0.9.min.js`).
`.htmx-indicator` (`style.css:1229`) was hand-ported at the 2026-07-17 CSP
fix and attached to nothing. **No `:disabled` rule exists** (control: 18
`:hover`). That trial's closing predicate was *"0 console errors on load"* —
which never asked whether an indicator existed to fade.

### F3 — Keyboard→control binding unverified for 10 of 19 actions

Never pressed: `reject`, `defer`, `graduate`, `iterate`, `note`, `tolerate`,
`confirm`, `retry`, `close_pane`, `bucket_pane`. Key-uniqueness *is* tested
(`test_keymap.py:91`); the routes *are* covered via httpx. The unproven link
is that the keystroke reaches the control — and for one action it provably
does not (F6).

### F4 — ~~Two~~ ONE user-visible banner asserted nowhere

**Corrected at build time — the original finding was half wrong.** Only
`"That record could not be found."` (`index.html:25`) is genuinely
uncovered.

`"Bucket clear — nothing pending there now."` (`index.html:23`) **is**
covered, by `test_notice_bucket_clear_renders_banner` — added 2026-07-17 at
commit `00aa784`, well before this audit — which asserts
`"bucket clear" in r.text.lower()`, an adequate text assertion.

The audit missed it because it searched for the literal `"Bucket clear"`
with a capital B, while the test lowercases. The positive control
(`"resolved elsewhere"` → 4 files) passed and was therefore trusted — but it
happened to be lowercase at both ends, so it could not surface the
case-sensitivity confounder. **A positive control only validates the
dimensions it actually varies**; this one varied presence, not case.

Recorded rather than quietly corrected. The builder caught it and added
**one** test instead of padding a second to reach §10's predicted 963 —
the right call, and the reason DoD item 1 measures 962.

### F5 — The `bulk_progress` emitter cannot satisfy its own contract

`routes.py:2215-2227` assigns `failed_id` then `break`s **before** the
publish, so every emittable frame carries `failed_id=None`; the publish
follows the success check, so **item 1 is never narrated** and a failure on
item 1 emits **zero** frames; and there is **no terminal frame**, so a tab
outside the `inScope()`-gated refresh would read "graduating N of N…"
indefinitely.

### F6 — The `c` key is dead; the button's own label advertises it

`action_bar.html:115`, in the `holding` context:

```html
<button type="button" data-key-action="confirm_recurrence" …>Confirm (c)</button>
```

`KEYMAP` binds `c` → action **`confirm`**. `confirm_recurrence` appears in
neither `keymap.py` nor `app.js`, so no key reaches that button. `t` and `g`
beside it are wired correctly. A shipped defect, not a coverage gap.

### F7 — Zero perceptual assertions; some tests assert source text

51 assertions (34 + 17); none checks visibility or rendering.
`.error-strip { display: none }` keeps the suite green. Weakest:
`test_degradation_walk.py:111` substring-matches `app.js` **source**,
satisfiable by a comment. Not repaired here (R-2); recorded §9.1.

## 4. Design decisions

### 4.1 One strip, SSE-driven, mirroring the reconnect strip

Rejected: *per-record badge only* (list rows carry bare `data-row`, no
record id — only `detail.html:22`/`detail_degraded.html:24` have one; and it
cannot express a server-wide condition); *htmx `hx-indicator` only* (the
CSS is opacity-based and cannot reveal an element hidden by the `hidden`
attribute, and indicators are per-request/per-tab).

**Chosen:** one global strip, SSE-driven, mirroring `base.html:47` and
`app.js:519`'s `showReconnectStrip`.

Both spans are JS-driven — a hardcoded "applying" would render "applying
applying route to lrn-…" and would name the wrong verb on the bulk path:

| Envelope | badge | detail |
|---|---|---|
| `applying` | `applying` | `<verb> → <record_id>` |
| `bulk_progress` | `graduating` | `<done + 1> of <total>` |

*(`<done + 1>` because §5.6 publishes before the item it announces — see
§5.1, which is the authoritative table. R4-M2: these two disagreed in an
earlier round, and a builder reads this one first.)*

### 4.2 `hx-disabled-elt` is LOCAL feedback — it is not the obligation

It disables one button in one tab; `09 §3`'s serialization is server-wide.
**The strip discharges the obligation; `hx-disabled-elt` supplies the
instant local cue** the strip cannot, costing a round-trip. Both wanted;
only the first satisfies `09 §3`.

### 4.3 Strip lifecycle: a keyed Map of in-flight work

**Verbs ARE serialized server-wide** — `RealRunner._lock = Lock()`
(`runner.py:248`), docstring: *"The serialized async subprocess queue (10 §1
Verb runner row) server-wide: an `asyncio.Lock` means every concurrent
caller…"*. (The R2 gate concluded otherwise from a `routes.py`-only grep;
the lock lives in the runner.) Execution is serialized; **POST acceptance is
not**, so two tabs can each have a request in flight and the strip still
needs to survive interleaved frames.

**The mechanism is a keyed Map of in-flight work — NOT a counter (design
pivot, R6).** Rounds 2–6 each found a defect in a counter-based design, and
the last three shared one shape: *new state introduced without reconciling
an older rule that touched it.* A counter plus a `bulkInFlight` flag needed
six interacting rules (increment, decrement, clamp-at-zero, terminal-ignore,
flag-set/clear, connection-loss reset) over two variables, and every round
found another unreconciled pair. The pivot replaces that with **three rules
over one variable.**

```
inflight : Map<key, {badge, detail}>
```

| Event | Operation |
|---|---|
| `applying` `state:"start"` | `set("applying:"+verb+":"+id, {badge:"applying", detail: verb+" → "+id})` |
| `applying` `state:"done"`/`"error"` | `delete("applying:"+verb+":"+id)` |
| `bulk_progress`, `done < total` | `set("bulk", {badge:"graduating", detail:(done+1)+" of "+total})` |
| `bulk_progress` terminal (`done == total` or `failed_id`) | `delete("bulk")` |
| SSE connection loss | `clear()` |

After **every** operation: hide the strip if `inflight.size === 0`;
otherwise render `inflight.get("bulk")` if present, else the first entry
(JS `Map` preserves insertion order, so this is deterministic).

**Why this is the right shape: every defect rounds 2–6 found dissolves
structurally rather than being tested against.**

| Round | Defect | How the Map removes it |
|---|---|---|
| R2-B3 | two state machines, one element, no arbitration | one Map; membership *is* the state |
| R3-B1 | N+1 increments vs one decrement | `set` is idempotent — a duplicate open frame is a no-op by construction |
| R4-M1 | `bulkInFlight` derived from `counter > 0` | there is no flag; the `"bulk"` key *is* the flag, and cannot be derived from anything else |
| R5-M1 | connection loss didn't clear the flag | `clear()` is one operation over one variable; nothing can be left behind |
| R6-M1 | the clamp broke the flag's invariant | there is no clamp — `delete` of an absent key is a no-op, which is exactly what clamping was approximating |
| R4-m2 | stale strip text after a decrement to non-zero | render derives from Map contents after every operation, so text cannot lag state |

Note what R6-M1 becomes: an unmatched `applying/done` deletes a key that was
never present. That is a no-op on the Map, so a live `"bulk"` entry is
untouched and the strip keeps showing. The counter design needed a clamp
rule to approximate this, and the clamp is what broke the flag's invariant.

**Bulk frames must still be discriminated from the payload alone (R3-B1).**
`envelope_bulk_progress` (`sse.py:51`) has no frame-kind field and `sse.py`
is not in §5's change table, so classification is by payload:
`failed_id is not None` or `done == total` → terminal; otherwise progress.
This is total because §5.6 publishes *before* each item, so progress frames
run `(0,N) … (N-1,N)` — always `done < total` — while the success terminal
is the only `(N,N)`. A one-item bulk gives `(0,1)` then `(1,1)`.

**The empty-bulk case needs no special rule.** `ids=""` yields
`id_list == []` (`routes.py:2209`), the loop never runs, and the only frame
is a terminal `(0,0)` — a `delete("bulk")` on a Map that has no `"bulk"`
key. A no-op, for the same structural reason as R6-M1.

**Connection loss clears the Map (replaces R2's TTL).** R2 mandated a TTL,
unbuildable as specified: no value pinned, `app.js` is an IIFE whose timing
constants are closure-private, and a production-safe value (> the ~5 s
interrupt plus a git subprocess plus `push`) exceeds the harness's
sub-second wait budget (`_DEFER_QUIET_S = 0.6`). A production-safe TTL and a
testable one are different numbers.

Instead, at the existing `showReconnectStrip(true)` site: `inflight.clear()`
and hide. Semantically better than a timer — we have lost the channel that
would report completion, so we stop asserting work is running — needs no
magic number, and is testable through SSE machinery the harness already
drives. A late frame arriving after reconnect re-populates the Map and the
strip resumes, which is the correct recovery rather than staying dark.

### 4.4 The perceptual oracle, and its measured blind spot

`page.locator("body").aria_snapshot()`. Measured 2026-07-24: byte-identical
idle→idle and across a pushed SSE refresh changing no state, while
registering the help overlay immediately. A hand-rolled computed-style
digest was measured and **rejected** — it drifted on an idle page because it
counted content inside a collapsed `<details>` as visible.

**The blind spot** (measured R1, re-confirmed R2 against the real
stylesheet with htmx's exact `setAttribute("disabled","")` form):

```
WITH :disabled rule    → opacity 0.45 / not-allowed ; aria: button "Confirm" [disabled]
WITHOUT (V-2 mutation) → opacity 1    / pointer     ; aria: button "Confirm" [disabled]
                         to_have_css FLIPS          ; aria snapshot IDENTICAL
```

`aria_snapshot()` **and** `is_visible()` are blind to opacity, colour, and
cursor (`is_visible()` returns `True` at `opacity: 0`).

**Two oracles, each used only where valid:**

| Fact | Oracle |
|---|---|
| "the perceptible state changed" | `aria_snapshot()` inequality |
| "the control became disabled" | `aria_snapshot()` — `[disabled]` **is** carried |
| "the disabled control is visually distinct" | targeted `to_have_css` |
| "does it look good" | human, `10 §4` — unchanged |

Specificity verified at R2: `button:disabled` (0,1,1) cleanly beats the
existing `button { cursor: pointer }` (`style.css:768`, 0,0,1) — no ordering
hazard. `:disabled` matches htmx's attribute form.

### 4.5 Test seams

**`publish_nowait`, not `publish`.** `push_refresh` works because
`RefreshHub.force_refresh` is **sync** (`ledger.py:504`).
`AppEventHub.publish` is `async def` (`sse.py:88`) — handing it to
`call_soon_threadsafe` yields an un-awaited coroutine and publishes nothing,
silently. `publish_nowait` (`sse.py:92`) exists for this. `ServerHandle`
needs an `app_hub` accessor; it exposes only `_refresh_hub` and `_slot`.

**In-flight windows** use Playwright `page.route()` to hold a POST open;
`FakeRunner.run` (`runner.py:121`) returns immediately with no delay hook.

**But `page.route()` intercepts in the browser** — a held POST never reaches
the handler, so `_publish_applying` never runs. Synthetic seams alone would
let a build delete every server publish and stay green, against a spec whose
premise is "three of four layers are present." §6 therefore includes
end-to-end tests that submit for real and record SSE frames in-page; V-8
proves they bind.

## 5. Per-change table

### 5.1 `static/app.js`

Replace `default:` (583-586) with explicit `applying` and `bulk_progress`
cases; add `renderInflight()` (hide-or-render from the Map, §4.3) beside
`showReconnectStrip`; implement §4.3's `inflight` Map; on SSE connection loss
call `inflight.clear()` then `renderInflight()`, at the existing
`showReconnectStrip(true)` site.

**Clearing on connection loss is not optional bookkeeping (R5-M1).** If a
bulk's terminal frame is lost in an outage, its entry must not survive the
reconnect: the connection heals, the reconnect strip disappears, everything
looks normal — and under the previous counter+flag design the **next** bulk
read every progress frame as "already in flight", never incremented, and
**rendered nothing for its entire run** before self-healing on the run
after. A silent total failure on a healthy connection. Under the Map this
specific failure is weaker (a stale `"bulk"` entry would leave the strip
*showing* rather than silent, and the next progress frame overwrites it),
but `clear()` on loss remains required so the strip does not assert work
that may have finished unobserved. Test 10b asserts the recovery; V-13
mutates it.

**The per-envelope contract is pinned here, not delegated (R3-B1).** Round 3
deleted this list and pointed at §4.3, leaving the builder without a
per-frame rule:

| Frame | Map operation | Badge | Detail |
|---|---|---|---|
| `applying` `state:"start"` | `set("applying:"+verb+":"+id, …)` | `applying` | `<verb> → <record_id>` |
| `applying` `state:"done"`/`"error"` | `delete("applying:"+verb+":"+id)` | — | — |
| `bulk_progress`, `done < total` | `set("bulk", …)` | `graduating` | `<done + 1> of <total>` |
| `bulk_progress` terminal (`done == total` or `failed_id`) | `delete("bulk")` | — | — |
| SSE connection loss | `clear()` | — | — |

There is **no counter, no flag, and no clamp** — see §4.3 for why. `set` is
idempotent, so repeated progress frames need no guard; `delete` of an absent
key is a no-op, so an unmatched `done` or an empty-bulk terminal needs no
special case.

`<done + 1>` because §5.6 publishes *before* the item it announces — a frame
carrying `done=0, total=7` means item 1 is now running, so the human reads
"graduating 1 of 7", not "0 of 7".

**Re-render after EVERY operation** (this is what makes R4-m2 structural
rather than a rule to remember): hide if `inflight.size === 0`; otherwise
render `inflight.get("bulk")` if present, else the first entry in insertion
order. So when a bulk terminal removes its entry while an `applying` verb
still holds one, the strip re-renders to the `applying` label instead of
holding "graduating 3 of 3" for work that finished.

Unknown envelope types must STILL be ignored silently (`10 §1`) —
`default:` remains, minus these two.

### 5.2 `templates/base.html`

After the reconnect strip; **both spans empty**, JS-driven:

```html
<div id="self-learn-ui-applying-strip" class="applying-strip" hidden>
  <span class="badge badge-applying" id="self-learn-ui-applying-badge"></span>
  <span id="self-learn-ui-applying-text"></span>
</div>
```

Carry a template comment noting `badge-applying` denotes the **in-flight
style**, not the verb — it renders "graduating" on the bulk path (R2-m2).

### 5.3 `static/style.css`

- `.applying-strip`, mirroring `.reconnect-strip` (`style.css:254`).
  **`[hidden]` trap:** two children make `display: flex` natural, which
  **beats the UA `[hidden]` rule** and would pin the strip permanently
  visible. Follow the `.help-overlay[hidden]` precedent (`style.css:385`)
  with an explicit `.applying-strip[hidden] { display: none }`.
- A `:disabled` rule (none exists): reduced opacity + `cursor: not-allowed`,
  covering `button:disabled` and `[disabled]`. Asserted only by §4.4's
  targeted computed-style check.

### 5.4 `action_bar.html`, `proposal_bar.html`, `bucket.html`

`hx-disabled-elt="find button"` on the four resolution submitters, only
those (R-1): `action_bar.html`'s `/action/confirm` and
`/action/commit-drift/confirm`; `proposal_bar.html`'s `/proposal/confirm`;
`bucket.html:68`'s `/graduate-bulk`.

Verified at R1: correct htmx 2.0.9 semantics (`hx-disabled-elt` resolves
through the same extended-selector helper as `hx-target`, which implements
`find `), and all four forms hold **exactly one** `<button type="submit">`
as final child.

### 5.5 `keymap.py` + `tests/test_keymap.py` — fix F6

Change the `c` entry's action from `confirm` to **`confirm_recurrence`**.

**Why this direction, on evidence rather than assumption (R2-B1).** The
alternative — renaming the template attribute to `confirm` — was rejected
because `data-key-action="confirm"` already exists at **three** sites:
`action_bar.html:96`, `proposal_bar.html:64`, and `host_add_bar.html:53`.
`host_add_bar.html` is included by **both** `bucket.html:44` **and**
`detail.html:30`, so on a Detail page for a holding record with an
unregistered host, two identical targets would co-render and
`clickAction`'s `document.querySelector` (`app.js:55`) would resolve by
document order. Renaming the keymap action leaves every existing target
unambiguous.

**This renames a RATIFIED action name and three tests pin it.** Measured at
R2 by applying the change and running the suite:

```
FAILED tests/test_keymap.py::test_keymap_covers_every_pinned_action
FAILED tests/test_keymap.py::test_pinned_key_bindings   - KeyError: 'confirm'
FAILED tests/test_keymap.py::test_holding_row_keys_are_t_and_c
```

`PINNED_ACTIONS` (`test_keymap.py:14-30`) is a ratified list and
`test_holding_row_keys_are_t_and_c` cites `09 §11 Y-4`. Editing them is a
corpus change, authorized here by **R-6** and recorded in **§7.2** — not a
silent test fixup. Update all three to the new name; do not weaken any
assertion, and do not delete a test to make a rename pass.

`keymap_json()` feeds footer and help overlay;
`test_served_keymap_blob_matches_source` compares served against source and
keeps them consistent. The armed-bar `Enter` path is unaffected — it
resolves through `findArmedBar()`.

### 5.6 `routes.py` — fix F5

In `graduate_bulk`:

- publish one frame **before** each item, so item 1 is narrated rather than
  silent. **No separate pre-loop open frame** — it would be byte-identical
  to item 1's and unclassifiable by the client (§4.3, R3-B1). Item 1's
  frame *is* the open.

  **`done` is items COMPLETED, 0-indexed at the top of each iteration —
  never the item's ordinal (R4-m1).** The existing `done = 0` /
  `done += 1`-after-success accounting (`routes.py:2214`, `2225`) already
  has this shape; keep it. Publishing the 1-indexed item number instead
  would make the frame before item N read `(N,N)`, which §4.3 classifies as
  a success terminal — the strip would vanish one item early, and every
  test would still pass because the client is behaving correctly on a
  mislabelled frame;
- on failure, publish a **terminal frame carrying `failed_id`** before
  breaking, so the parameter stops being unreachable;
- on success, publish a **terminal frame after `await runner.run(["push"])`
  (line 2229) and before `_force_refresh`** — the push is part of what the
  user is waiting through, so the strip stays up for it. Pinned because R2
  correctly noted the position was unspecified.

No change to verb semantics, loop ordering, the `break`, or the
serialization guarantee. Verified safe at R2: the inserted publishes go to
unbounded queues and no-op with no subscribers, and no existing test asserts
on bulk frames (`test_sse.py:36` checks envelope shape only).

### 5.7 `tests/test_js_dom.py`

Add `push_applying(verb, record_id, state)` and `push_bulk_progress(...)`
routed through **`publish_nowait`**, plus an `app_hub` accessor.

## 6. Test plan — 35 tests

*(Was 36. Corrected at build time when F4 dropped from two tests to one —
its second banner was already covered; see F4. 34 `js` + 1 non-`js`.)*

**Markers:** browser tests carry `js`. The F4 banner test needs no
browser and must **NOT** be `js`-marked, or R-3-mandated coverage skips
wherever Chromium is absent.

**Assertion-strength rule (fixes R2-B2).** Round 2 described tests 2 and 5
as text assertions, which survive `display: none` — so V-1 could pass having
made the deliverable permanently invisible, and §4.4's headline oracle row
applied to nothing. **Every test below marked ⊕ asserts `to_be_visible()`
AND `aria_snapshot()` inequality**, not text alone. Under V-1's mutation the
body snapshot is `''`, so the inequality binds.

**F1 — client rendering (13, `js`).** *(1–10 plus 8b, 9b and 10b.)*
1. strip **not visible** on load (visibility, not the `hidden` attribute)
2. ⊕ visible with correct badge+detail after `applying/start`
3. hidden after `applying/done`
4. hidden after `applying/error`
5. ⊕ bulk progress frame renders `<done + 1> of <total>` (§5.1)
6. bulk **terminal** frame hides the strip. **Must show it first** — push a
   progress frame and assert visible, *then* the terminal and assert hidden.
   *(R3-M3: a terminal on an empty Map is a no-op, so a test that skips the
   show step asserts "hidden" on a strip that was never visible and passes
   having tested nothing.)*
7. unknown envelope ignored **and no `pageerror` fired** — a bare "nothing
   happened" assertion stays green when the handler throws, because the
   throw escapes to `window.onerror` leaving the DOM untouched
8. two distinct `applying/start`s then one matching `done` leaves the strip
   visible (the other entry still holds it); a `done` for a verb never
   started is a no-op and does not hide a strip another entry owns — §4.3
8b. **unmatched `done` against a live bulk (R6-M1).** Bulk progress `(0,3)`
   → strip visible → an `applying/done` for a verb whose `start` this client
   never saw → strip **still visible** → subsequent progress `(1,3)` still
   renders. Under the previous counter design this sequence silenced the
   rest of the bulk run, and the ordering was guaranteed rather than
   incidental: §5.6 publishes the progress frame *before* the item, and the
   bulk then blocks on the runner's serialization lock (`runner.py:270`)
   behind the other verb, whose `done` therefore always lands after the
   bulk's first frame. What V-14 mutates.
9. **mixed envelopes, bare terminal (R3-B2).** `applying/start` → strip
   visible; a bulk **terminal** frame arrives → strip **still visible** (the
   `applying` entry still holds it); then `applying/done` → hidden. What V-10
   mutates. Also covers §4.3's empty-bulk case — a terminal with no `"bulk"`
   key present must be a no-op, never touching an `applying` entry.
9b. **mixed envelopes, with a real bulk in flight (R4-M1).** `applying/start`
   → bulk **progress** `(0,3)` → bulk **terminal** `(3,3)` → strip **still
   visible**; then `applying/done` → hidden. Test 9 alone does not exercise
   the case where the bulk genuinely opens, which is where the counter design
   failed; retained under the Map design as the direct regression test for
   that class. What V-12 mutates.
   **Also asserts §5.1's re-render rule (R5-m1)** at the terminal step: the
   strip must revert to the `applying` label, not keep reading "graduating 3
   of 3" for a bulk that finished.
10. SSE connection loss clears the Map and hides the strip (§4.3).
    **Seam: `BrowserContext.set_offline`** — verified present in the
    installed Playwright. `page.route()` cannot abort an already-established
    stream, and no production change is needed or permitted here (R3-m1).
10b. **a stale entry does not survive a reconnect (R5-M1, retargeted R7).**
    Open a bulk (progress frame → strip visible), drop the connection
    **before** its terminal arrives, restore it, then push an
    `applying/start`: the strip must render the **`applying`** label, not a
    stale `graduating`.
    *(The obvious assertion — "a fresh bulk still renders" — is immune under
    the Map by construction, because that bulk's first progress frame
    `set("bulk", …)` overwrites the stale entry. §5.1 states this outright,
    and R7 measured test 10b passing under V-13 for exactly that reason: the
    test was inherited from the counter design and guarded nothing here. The
    observable consequence of a stale entry under the Map is that it **wins
    the render** over a later `applying` entry — narrating a bulk that may
    have finished during the outage — so that is what must be asserted.
    R7 measured this binding: baseline renders `applying → route`, V-13
    renders `graduating 1 of 3`.)*
    **Builder note:** the client must be resubscribed before the
    `applying/start` is pushed — use `wait_for_subscriber`
    (`test_js_dom.py:128`), as test 10 already does. Missing the wait loses
    the frame and fails the assertion loudly rather than passing vacuously,
    so the failure mode is safe; it is called out only to save the debugging.

**F1 — server publish, end-to-end (3, `js`).** Real submissions, no
`page.route()`, with an in-page SSE frame recorder.
11. real confirm → an `applying` frame arrives carrying the right verb and
    record id
12. real bulk → a frame is observed **for item 1**
13. real bulk failure → a terminal frame arrives **carrying `failed_id`**
    (the path F5 showed is currently unreachable)

**F2 — in-flight disabling (8, `js`).** POST held open via `page.route()`.
14. the submitter carries `disabled`
15. ⊕ the ARIA snapshot differs during flight
16. the disabled element **is the submitter**, not merely some element
17. targeted `to_have_css` confirms §5.3's rule applies
18–20. settle, the three `hx-swap="outerHTML"` forms (`action_bar` ×2,
    `proposal_bar`): the button is **detached**, not re-enabled — asserting
    "no longer disabled" is ill-posed for these
21. settle, `bucket.html`'s `hx-swap="none"` form: the button **is**
    re-enabled

**F3 — keymap binding (10, `js`).** One per never-pressed action. Each
presses the key in a context where the control renders and asserts **the
control was activated**, never that the key was accepted.

- The `confirm` test is F6's regression test: press `c` **in the `holding`
  context** and assert the recurrence button activated. **Vacuous-pass
  warning:** driving it on an *armed* bar instead passes via
  `Enter → clickAction("confirm")` and proves nothing. V-9 catches that.
- `retry` and `close_pane` need pane state (`pane.html:48` is gated on
  `{% if pane.error_message %}`; `close_pane` needs `pane_split`) that
  `test_js_dom.py`'s fixture cannot build. **Place these two in
  `test_js_dom_pane_persistence.py`**, which owns the pane server fixture
  and `PaneTranscriptStore`. Do not fabricate DOM in the wrong module.

**F4 — banners (1, NOT `js`).** The `"That record could not be found."`
banner rendered under its real condition. *(The bucket-clear banner was
already covered — see F4; adding a second test here would be padding.)*

## 7. Corpus amendments

### 7.1 `09-surface-spec.md` §7 — dated amendment, appended not rewritten

Per the D2 precedent in `13-hosting-and-separation.md`: original
ratification stays visible, amendment beneath it, dated, naming what is
severed. **Perceptibility moves into CI; taste stays human.**

*Wording constraint:* the amendment must NOT claim perceptibility is now
asserted across the surface. It is asserted **for the feedback this unit
introduces** (R-2); ~20 pre-existing sites remain unasserted (§9.1), and
colour/opacity facts stay outside the automated oracle (§4.4).

### 7.2 `03-decisions.md` — new S-row

Record: the boundary move; the ARIA-snapshot choice, the rejected
computed-style digest, and the measured blind spot; R-1's deferral to
measured latency; R-6's three expansions; and — explicitly — **the rename of
the ratified action name `confirm` → `confirm_recurrence`**, why the
template-side alternative was rejected (§5.5), and that three pinned-name
tests were updated under that authority (human-ratified 2026-07-24).

**It must ALSO record §4.3's mechanism choice** — a keyed Map of in-flight
work rather than a counter — together with *why*: five consecutive gate
rounds found defects in the counter design, three of them the same shape
(new state added without reconciling an older rule that touched it), and
the Map removes all six structurally rather than testing against them. That
reasoning is the reusable part; a future reader tempted to "simplify" it
back to a counter should be able to see what that costs.

**It must ALSO record §8's residual post-reconnect window (R4-m3).** §8
lives in a draft, and drafts do not persist into canon — a known shipped
gap that exists only in a draft is a gap nobody will find again. The S-row
carries it, with the forward-work pointer to the state-resync envelope.

### 7.3 `14-forward-work-map.md` — the §9.2 items.

## 8. What this unit does NOT claim

Colour, opacity, contrast, geometry, occlusion, and `text-transform` casing
are **not** asserted by anything here except one targeted computed-style
check on one element. The general oracle cannot see them.

**A residual silent window survives, disclosed rather than papered over
(R3-M2).** `app.js` does not distinguish a transient SSE reconnect from a
real drop — `source.onerror` (line 544) fires on any blip and
`source.onopen` (540) hides the reconnect strip and restores nothing. So a
verb still running *across* a reconnect ends with **neither** strip
showing: §4.3's clearing removed the applying strip during the outage, and
`onopen` removes the reconnect strip on recovery. §4.3's rationale ("we
have lost the channel that would report completion") covers the outage, not
the recovery.

Closing it properly needs a state-resync envelope, which would put `sse.py`
and a new route in scope — a fourth expansion this unit declines. It is
recorded as forward work (§9.2) **and in §7.2's S-row**, so it survives
beyond this draft.

Two bounds, stated for precision rather than comfort: the verb must span an
SSE blip, and it affects **observer tabs only** — the submitting tab keeps
its `hx-disabled-elt` cue throughout, since that is local to its own
request and independent of SSE. The window is real; the corpus should say
so rather than let §7.1's amendment imply otherwise.

## 9. Explicitly out of scope

### 9.1 Not fixed here (recorded, not lost)

- Retro-fitting perceptual assertions to the ~20 pre-existing feedback sites
  (R-2). A CSS regression can still hide any of them silently.
- `test_degradation_walk.py:111` and its source-text-substring siblings.
- Audio (R-4).
- **A known timing sensitivity, recorded so a future flake is not
  mysterious.** `test_js_dom_pane_persistence.py::test_retry_presses_r_and_posts_pane_retry`
  (one of F3's ten keymap tests) failed once at the code gate when the `js`
  and non-`js` suites were run *concurrently*, on `_wait_for_held`'s 5 s
  wall-clock budget under the resulting CPU contention. Not reproducible in
  normal use — module alone 5/5, full `js` suite alone 75/75, and 75/75 again
  on a repeated concurrent run — and provably not caused by any change here
  (the file's diff hunk is byte-identical pre- and post-fix). If this ever
  goes red in CI, the cause is the wall-clock budget, not the feedback logic.

### 9.2 Forward work

- **Measure per-verb latency** across the remaining 39 htmx verbs, then
  decide indicators on data (R-1). Unit 2's natural first job.
- **An in-flight state-resync envelope**, so a client reconnecting mid-verb
  can recover the strip instead of showing nothing (§8's residual window).
  Touches `sse.py` and needs a route; deliberately not taken here.
- **Unit 2** — reusable project-agnostic perceptual harness, own repo,
  self-learn as target #1.

## 10. Definition of Done

**Baseline, measured 2026-07-24 before any change**, from
`plugins/self-learn/ui/` (re-confirmed exact at the R2 gate):

| Command | Result |
|---|---|
| `uv run pytest -q -m 'not js'` | **1 failed, 961 passed**, 41 deselected |
| `uv run pytest -q -m js` | **41 passed**, 962 deselected |

The failure is
`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
— pre-existing, unrelated. It must remain the *only* failure; if it
disappears or gains company, that is a result to explain, not absorb.

1. `uv run pytest -q -m 'not js'` → **1 failed, 962 passed** (961 + **1**
   banner test), same named failure. *(The three `test_keymap.py` tests
   §5.5 updates stay passing — they are edited, not added.)*
   **Corrected from 963 at build time:** F4's second banner turned out to be
   already covered (see F4). 962 is the correct target; a 963 here would
   mean a padded test.
2. `uv run pytest -q -m js` → **75 passed** (41 + 34 new `js` tests;
   13 + 3 + 8 + 10 = 34, the 1 banner test being non-`js`).
3. CLI suite and pyright unchanged: 1117 passed / 5 skipped, exactly 50
   pyright errors.
4. From the repo root with `pwd` proven:
   `git grep -c 'hx-disabled-elt' -- plugins/self-learn/ui/templates` → 4,
   with positive control `git grep -c 'hx-post'` on the same pathspec still
   matching.
5. Mutation verification (§11) complete; every mutation reverted by
   reverse-`Edit`.

## 11. Mutation-verification plan

Each mutation must make a **named** test fail.

- **V-1 — the strip is rendered, not merely present.** Set
  `.applying-strip { display: none }`. **Tests 2 and 5 (⊕) must fail.**
  *R2 measured that under this mutation `to_have_text` and `to_contain_text`
  both PASS and the body snapshot is `''` — so if either test was written
  as a text assertion, V-1 reports CLEAN having made the deliverable
  invisible. That is the whole reason for the ⊕ rule.*
- **V-2 — the disabled style is perceptible.** Delete the `:disabled` rule.
  **Test 17 (`to_have_css`) must fail; tests 14 and 15 must still pass.**
  Divergence measured achievable at R2.
- **V-3 — `bulk_progress` is wired.** Revert its case to `default:`. Tests
  5 and 6 must fail. *(Assert the detail text first so the test cannot
  short-circuit on an earlier assertion.)*
- **V-4 — the failure path is real, not synthetic.** Remove §5.6's
  terminal-failure publish. **Test 13 must fail.**
- **V-5 — keymap tests bind to activation.** Remove one action's
  `data-key-action`. That action's test must fail.
- **V-6 — unknown envelopes are ignored.** Add a case that throws. **Test 7
  must fail via its `pageerror` assertion** — a DOM-only assertion stays
  green.
- **V-7 — banner tests bind to render, not source.** Change one banner's
  wording. Its test must fail.
- **V-8 — the server publish path is bound.** Delete all six
  `_publish_applying` calls and the `envelope_bulk_progress` publish.
  **Tests 11–13 must fail.**
- **V-9 — the `c` fix is real (F6).** Revert `keymap.py`'s `c` entry to
  `confirm`. **The `confirm` test must fail.** If it passes, the test was
  driven on an armed bar and proves nothing.
- **V-10 — a terminal removes only its own entry (§4.3).** Make
  `bulk_progress`'s terminal call `inflight.clear()` instead of
  `delete("bulk")`. **Test 9 must fail** — a bulk terminal must not evict an
  `applying` entry that still owns the strip.
  *(Retargeted at R3-B2: round 3 named test 8, which is pure-`applying` and
  which this mutation never touches — it would have passed. Tests 5 and 6
  are pure-bulk and would also have passed. Only test 9 interleaves the two
  envelope types, which is exactly what the defect requires; that is why
  test 9 was added rather than V-10 merely renamed.)*
- **V-12 — bulk and applying occupy DISTINCT keys (R4-M1's class).** Key
  **both** `applying` and `bulk` entries under a **single constant**, so one
  evicts the other. **Test 9b must fail** — the bulk's terminal must not
  remove a live `applying` entry. *(Worded precisely at R7: "key bulk under
  the key an applying entry uses" does not collide, because that key is
  dynamic (`applying:<verb>:<id>`); the mutation must collapse both sides to
  one constant to produce the eviction.)*
- **V-13 — connection loss clears the Map (R5-M1).** Hide the strip on SSE
  loss without calling `inflight.clear()`. **Test 10b must fail.**
- **V-14 — an unmatched `delete` is a no-op, not a reset (R6-M1).** Make an
  `applying/done` whose key is absent call `inflight.clear()` (or hide the
  strip directly) — the behaviour the old clamp rule approximated and got
  wrong. **Test 8b must fail** — an unmatched `done` must not silence a live
  bulk.
- **V-15 — `applying` entries are keyed per verb+record (§4.3).** Key every
  `applying` entry under one constant. **Test 8 must fail** — two concurrent
  verbs would collide and the first `done` would hide a strip the second
  still owns.

*(No mutation for the N+1 runaway R3-B1 found. It is **structurally
impossible** under §4.3's Map: `set("bulk", …)` is idempotent, so no
sequence of progress frames — including a restored pre-loop open frame —
can produce more than one entry. A round-4 draft carried such a mutation,
targeting a client-side test with a server-side change; it was
unsatisfiable at both layers and, worse, invited a builder to weaken the
guard until it reproduced. Structural impossibility is the stronger
guarantee; there is nothing to mutate. Reference updated at R7 — the
earlier wording cited the already-in-flight flag rule, which the Map pivot
deleted; the conclusion is unchanged.)*
