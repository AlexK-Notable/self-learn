# Review — UI in-flight feedback spec (Unit 1)

**Target:** `docs/specs/self-learn/drafts/ui-inflight-feedback-spec.md`
**Date:** 2026-07-24
**Gate:** blind spec gate. Reviewer did not read this directory.
**Round 1 verdict: NOT SOUND** — 4 BLOCKER, 7 MAJOR, 5 MINOR/NIT.

## Round 1 — what held

The reviewer independently re-ran every absence claim in the spec's §3
with a live positive control. **All findings verified**, including: both
SSE envelopes published and discarded at `app.js`'s `default:` branch;
`.badge-applying` referenced by no template; zero `hx-indicator` /
`hx-disabled-elt` outside the vendored htmx; zero `:disabled` rules
(control: 18 `:hover`); 10/19 keymap actions never pressed; the two
banner strings in zero test files (control: `"resolved elsewhere"` → 4
files); 51 assertions with none perceptual; `Page.accessibility` absent
and `Locator.aria_snapshot` present in Playwright 1.61.0; all four target
forms carrying exactly one `<button type="submit">` as final child.

`hx-disabled-elt="find button"` was verified correct htmx 2.0.9 semantics
by reading the minified source: it resolves through the same
extended-selector helper as `hx-target`, which implements `find `.

The defects were all downstream of the findings — in the fix design, the
test plan, and the mutation plan.

## Round 1 — BLOCKERS

**B1 — the oracle is blind to the CSS the spec specified.** §4.4 declared
that `aria_snapshot()` carries no colour or geometry, and §5.3 then
specified the disabled affordance as opacity + cursor — wholly inside the
blind spot. Measured: the snapshot is byte-identical across the CSS-only
delta, and `is_visible()` returns `True` at `opacity: 0`. V-2's required
divergence was unachievable, and the two tests the spec called a pair
asserted the same fact. The mutation plan written to prevent the project's
signature bug class contained it.

*Fold:* §4.4 now splits the oracle — ARIA for state change and
`[disabled]` (which it does carry), a targeted `to_have_css` for the CSS
fact, human for taste. V-2 rewritten. Builder rule 6 added.

**B2 — no test bound the server publish path.** `page.route()` intercepts
in the browser, so a held POST never reaches the handler and
`_publish_applying` never runs; every other test used synthetic seams.
Deleting all six `_publish_applying` calls plus the bulk publish would
have left all 24 proposed tests green — against a spec whose own F1 is
"three of four layers are present."

*Fold:* §4.5 names the problem; §6 adds 2 end-to-end tests submitting for
real with an in-page SSE frame recorder; V-8 added.

**B3 — the `bulk_progress` emitter cannot satisfy its own contract.**
`routes.py:2215-2227` assigns `failed_id` then `break`s *before* the
publish, so every emittable frame carries `failed_id=None`; the publish
follows the success check, so item 1 is never narrated and a failure on
item 1 emits zero frames; and there is no terminal frame, so a second tab
outside the `inScope()`-gated refresh would read "graduating N of N…"
indefinitely.

*Fold:* new finding F5; R-6 authorizes `routes.py`; §5.6 specifies
publish-before-item, terminal-on-failure, terminal-on-success; §4.3 adds
a refcount and TTL; V-4 rewritten to mutate the server.

**B4 — the `c` key is dead, and R-3 mandated fixing it.**
`action_bar.html:115` renders `data-key-action="confirm_recurrence"` on a
button whose label reads "Confirm (c)", while `KEYMAP` binds `c` to action
`confirm`. `confirm_recurrence` appears in neither `keymap.py` nor
`app.js`. `t` and `g` in the same form work. The spec's F3 claim that
every action's target exists was true only of a global name match.

*Fold:* new finding F6; R-6 authorizes `keymap.py`; §5.5 renames the `c`
action; V-9 added; §6 carries an explicit warning that driving the test on
an armed bar would pass vacuously.

**Independently re-verified by the orchestrator before folding:** B4 and
MAJOR 7 were both re-run against the live tree and confirmed.

## Round 1 — MAJORS

1. **Badge composition** — static "applying" in the badge plus "applying
   … " in the text renders the word twice, and asserts the wrong verb
   entirely on the bulk path. *Fold:* both spans JS-driven, §4.1 table.
2. **Settle assertion ill-posed** for three of four forms — `outerHTML`
   swaps detach the button rather than re-enabling it. *Fold:* per-form
   assertions.
3. **`push_applying` would have been a silent no-op** — `publish` is
   `async def`, `force_refresh` is sync, so mirroring `push_refresh` would
   hand `call_soon_threadsafe` an un-awaited coroutine. *Fold:*
   `publish_nowait` + an `app_hub` accessor.
4. **`retry`/`close_pane` need pane state** the target module's fixture
   cannot build. *Fold:* relocated to `test_js_dom_pane_persistence.py`.
5. **V-1 over-claimed** three failing tests where only two touch the
   strip. *Fold:* corrected.
6. **V-6 left its test green** — a `throw` in `onmessage` escapes to
   `window.onerror` leaving the DOM untouched. *Fold:* `pageerror`
   assertion.
7. **§4.2 contradicted §4.1** — claiming `hx-disabled-elt` discharges a
   server-wide obligation it cannot, having just rejected htmx indicators
   for being per-tab. *Fold:* §4.2 rewritten; strip is the obligation,
   `hx-disabled-elt` is local feedback.

## Round 1 — MINOR / NIT

12. `.applying-strip` with `display: flex` would beat the UA `[hidden]`
    rule and pin the strip visible; `.help-overlay[hidden]`
    (`style.css:385`) is the existing precedent. Load test must assert
    visibility, not the attribute.
13. R-1's rationale was factually wrong — pane verbs launch agent
    sessions and are not "near-instant local state flips."
14. §7.1's amendment over-promised coverage the unit does not deliver.
15. Marking the banner tests `js` would skip R-3-mandated coverage
    wherever Chromium is absent.
16. `.badge-applying` shares a declaration block with two referenced
    selectors — only the selector was dead, not the rule.

All folded into round 2.

## Round 2 — NOT SOUND (3 BLOCKER, 2 MAJOR, 2 MINOR)

The reviewer confirmed most of round 1's fold discharged its findings for
real, and **measured** the new two-oracle split sound: rebuilding V-2
against the live stylesheet with htmx's exact `setAttribute("disabled","")`
form showed `to_have_css` flipping (0.45/not-allowed → 1/pointer) while the
ARIA snapshot stayed byte-identical. Specificity also checked:
`button:disabled` (0,1,1) cleanly beats `button { cursor: pointer }`
(`style.css:768`, 0,0,1).

The pattern of round 2: the fold discharged what it addressed, then
introduced defects in the *new* design. Three of four blockers were new.

**B1 — the F6 rename breaks three ratified-name tests.** The reviewer
applied the rename and ran the suite: `test_keymap_covers_every_pinned_action`,
`test_pinned_key_bindings` (`KeyError: 'confirm'`), and
`test_holding_row_keys_are_t_and_c` all fail. `PINNED_ACTIONS`
(`test_keymap.py:14-30`) is a ratified list and the third test cites
`09 §11 Y-4`, so editing them is a corpus change the spec had not
authorized. The reviewer also found the spec's stated reason for choosing
`keymap.py` over the template — "would collide" — was an unexamined
premise.

*Fold:* R-6 authorizes `tests/test_keymap.py`; §7.2 records the ratified-name
change; §5.5 justifies the direction on evidence instead — `data-key-action="confirm"`
exists at three sites (`action_bar.html:96`, `proposal_bar.html:64`,
`host_add_bar.html:53`), and `host_add_bar.html` is included by *both*
`bucket.html:44` and `detail.html:30`, so the template-side rename would put
two identical targets on one Detail page and let `document.querySelector`
first-match decide.

**B2 — V-1 would still have reported CLEAN.** Round 2 described the two
tests V-1 names as *text* assertions, and the reviewer measured that
`to_have_text` and `to_contain_text` both survive
`.applying-strip { display: none }`. Worse, the round-1→2 fold had dropped
from three ARIA assertions to one, leaving §4.4's headline oracle row
applied to nothing — the unit's primary deliverable would have shipped with
no perceptual assertion at all.

*Fold:* §6 gains an explicit assertion-strength rule (⊕ = `to_be_visible()`
AND snapshot inequality; the body snapshot is `''` under the mutation, so it
binds), builder rule 7, and V-1 rewritten to name the tests.

**B3 — the refcount premise, and two state machines on one element.** The
reviewer's premise check was scoped to `routes.py` and concluded verbs are
not serialized. **This was wrong** — `RealRunner._lock = Lock()`
(`runner.py:248`), documented as the server-wide serialized subprocess queue.
The orchestrator verified and corrected it, and added the subsystem-scope
form of the pathspec trap to builder rule 3. The *mechanical* half stood
regardless: `applying` had a refcount while `bulk_progress` had a plain
show/hide, so one element was driven by two uncoordinated state machines,
plus an unpinned mid-verb-load `done`-at-zero case.

*Fold:* §4.3 specifies ONE counter for both envelope types, clamped at zero;
V-10 added to mutate exactly that defect.

**M1 — the TTL was unbuildable.** No value pinned, no seam budgeted;
`app.js` is an IIFE whose timing constants are closure-private, and a
production-safe TTL (> ~5 s interrupt + git subprocess + push) exceeds the
harness's sub-second wait budget (`_DEFER_QUIET_S = 0.6`).

*Fold:* the TTL is **removed**. Replaced by clearing the strip on SSE
connection loss, at the existing `showReconnectStrip(true)` site — no magic
number, no real-time wait, and semantically better: the channel that would
report completion is gone, so the surface stops asserting the verb runs.

**M2 — F2's test count was ambiguous** while §10 gated on an exact total.
*Fold:* §6 enumerates 32 numbered tests; F2 is explicitly 8.

**m1** — the success terminal frame's position was unspecified; the reviewer
confirmed it is not a race with `_force_refresh`, only under-specification.
*Fold:* pinned after `runner.run(["push"])`, before `_force_refresh`.

**m2** — `badge-applying` renders the word "graduating" on the bulk path.
*Fold:* template comment noting the class denotes in-flight style, not verb.

## Round 3 — NOT SOUND (2 BLOCKER, 3 MAJOR, 1 MINOR)

The reviewer opened by confirming and attributing its own round-2 error:
its "verbs are not serialized" finding came from a gate scoped to
`routes.py` alone, returning rc=1 vacuously. Widened
(`git grep -ln 'asyncio.Lock' -- plugins/self-learn/ui/src`) it resolves to
`runner.py` alone — `self._lock = Lock()` at 248, `async with self._lock`
at 270. Recorded in the spec's builder rule 3 as the subsystem-scope form
of the pathspec trap. It also established why the mechanical half survived
anyway: `_publish_applying(start)` (`routes.py:1205`) fires *before*
`runner.run` acquires the lock, so two tabs both emit `start` before either
executes — execution serialized, POST acceptance not, exactly as §4.3 says.

**B1 — the counter was unimplementable against the envelope §5 permitted.**
§4.3 classified bulk frames as open (increment) or terminal (decrement),
while §5.6 mandated a pre-loop open frame **and** one before each item:
N+1 increments against one decrement, so the strip stuck visible after
every bulk run. It could not be fixed by classification, because
`envelope_bulk_progress` (`sse.py:51`) has no frame-kind field, `sse.py`
was not in the change table, and the pre-loop frame is byte-identical to
item 1's — both `(done=0, total=N, failed_id=None)`. An empty bulk
(`ids=""` → `id_list == []`) compounded it with two identical `(0,0)` frames
of opposite effect. Root cause: round 3's §5.1 had deleted the explicit
per-envelope case list and delegated to an incomplete taxonomy.

*Fold:* §5.6 drops the pre-loop frame — item 1's frame *is* the open. §4.3
gains a three-way payload discrimination table (`failed_id` → terminal;
`done == total` → terminal; else progress), total because publishing
*before* each item makes progress frames `(0,N)…(N-1,N)` and the success
terminal the only `(N,N)`. Empty-bulk terminals with no bulk in flight are
ignored. §5.1 restores the per-envelope contract table. V-11 added.

**B2 — V-10 named a test it could not fail.** V-10 mutated the bulk
terminal path; test 8 was pure-`applying`, tests 5 and 6 pure-bulk. No test
in §6 interleaved the two envelope types, so the two-state-machine defect
V-10 existed to catch had no binding coverage at all — a §6 coverage gap
first, a §11 wording error second.

*Fold:* new **test 9**, the only mixed-envelope test: `applying/start` →
visible; bulk terminal → still visible; `applying/done` → hidden. V-10
retargeted to it. Test 9 also covers the empty-bulk rule.

**M1 — a spec cannot self-authorize amending ratified corpus.** R-6 was
authored in the document under gate and granted that same document
permission to amend a name governed by `03-decisions.md`. The reviewer had
no objection to the *direction* (now evidence-backed) — only to the
authority.

*Resolution:* **routed to the human and ratified 2026-07-24.** R-6 now
records that the scope comes from the spec and the authority from the
human.

**M2 — post-reconnect silent window.** `app.js` does not distinguish a
transient reconnect from a real drop: `onerror` (544) fires on any blip,
`onopen` (540) hides the reconnect strip and restores nothing. A verb
running *across* a reconnect ends with neither strip showing. §4.3's
rationale covers the outage, not the recovery.

*Fold:* **disclosed, not fixed** — §8 states it with line numbers; a
state-resync envelope would put `sse.py` and a new route in scope, a fourth
expansion this unit declines. Recorded as forward work (§9.2).

**M3 — test 6 could pass vacuously:** pushing a terminal at counter 0
clamps, so "assert hidden" would pass on a strip never shown. *Fold:* the
test must show the strip first.

**m1 — test 9's SSE-drop seam was unnamed.** `page.route()` cannot abort an
established stream. *Fold:* `BrowserContext.set_offline` named explicitly;
independently confirmed present, alongside `aria_snapshot`, `to_have_css`
and `to_be_visible`.

## Round 4 — NOT SOUND (1 BLOCKER, 2 MAJOR, 3 MINOR)

**The mechanism was verified, not argued.** The reviewer walked §4.3's
discrimination table against the real emitter (`done = 0` at
`routes.py:2214`, `done += 1` after success at 2225) and confirmed the
counter returns to zero across all seven sequences: N=1, N=3, empty,
failure at item 1, failure at item N, applying-then-bulk, bulk-then-applying.
It also confirmed `done == total` is unambiguous under publish-before-item,
that the `(0,0)` empty-bulk collision is disarmed by the ignore rule, that
the arithmetic was correct throughout, and that no round-3 gain had
regressed.

**B — V-11 was unsatisfiable at two layers.** It mutated `routes.py` but
named test 6, which lives in the client-rendering group driven by synthetic
`push_bulk_progress` seams and never calls `graduate_bulk` — the same layer
mismatch round 3's V-10 had. Worse, the mutation was **inert by design**:
under it the client sees `(0,N)` twice and the already-in-flight rule
absorbs the duplicate, so nothing observable changes. The danger named: a
builder unable to reproduce it might "fix" the absorption rule until it
did, reintroducing the runaway the rule prevents.

*Fold:* V-11 **deleted**. §4.3 records that the guard makes the runaway
**structurally impossible** — stronger than any mutation — and §11 explains
why there is deliberately nothing to mutate.

**M1 — the arbitration had no binding test, and the spec's own headline
pointed away from the fix.** Test 9 used a *bare* bulk terminal, so it
missed the reachable misreading: implementing "a bulk is already in flight"
as `counter > 0` would, with a real progress frame in the sequence, skip
the bulk's increment (counter already non-zero from `applying`) and then
decrement on the terminal — hiding the strip while the `applying` verb
still ran. R2-B3 reappearing with every test green. Root cause identified
as naming: `bulkInFlight` is a **second piece of state**, and §4.3's
headline "ONE counter for BOTH envelope types" obscured it.

*Fold:* new **test 9b**; §4.3's header changed to "one shared counter, a
separate bulk flag"; both tables name `bulkInFlight` as a field; both
sections state in bold that it must never be derived from `counter > 0`.
V-12 mutates that reading.

**M2 — §4.1 and §5.1 disagreed** on the rendered string for the same frame
(`<done>` vs `<done + 1>`). *Fold:* §4.1 corrected, §5.1 named
authoritative.

**m1 — `done`'s semantics were unpinned at the publish site.** Publishing
the 1-indexed ordinal would make the frame before item N read `(N,N)` —
classified as a success terminal, strip vanishing an item early — **with
every test still passing**, since the client would be behaving correctly on
a mislabelled frame. *Fold:* §5.6 pins it.

**m2 — stale strip text on a decrement to non-zero.** *Fold:* §5.1 requires
re-rendering for whatever still owns the strip.

**m3 — §8's residual window would not have reached canon.** §7.2's S-row
enumeration omitted it and §8 lives in a draft. *Fold:* added to the S-row.

§8's disclosure was judged honest and complete, and slightly *pessimistic*:
the window affects observer tabs only, since the submitting tab keeps its
`hx-disabled-elt` cue independent of SSE. Added.

## Round 5 — NOT SOUND (0 BLOCKER, 1 MAJOR, 1 MINOR, 1 NIT)

Q1, Q3 and the arithmetic came back clean. Test 9b was verified to bind
V-12 by walking the misreading step by step, and confirmed strictly
stronger than test 9 (it is the only test exercising the skipped-increment
path). All eleven mutations were checked against their named tests; the
layer error that killed R3's V-10 and R4's V-11 was confirmed not repeated.
Every round-4 fix confirmed landed.

**M — connection loss did not clear `bulkInFlight`.** The flag was
introduced in round 4; the connection-loss rule was written in round 2 and
never revisited. The orchestrator had flagged this as a possible gap when
sending round 5, but framed it as a self-healing nuisance. The reviewer's
trace showed it is materially worse:

> If a bulk's terminal frame is lost in an outage the flag stays true. The
> connection heals, the reconnect strip disappears, everything looks
> normal — and the **next** bulk reads every progress frame as "already in
> flight", never increments, and renders nothing for its **entire run**,
> before self-healing on the run after.

A silent total failure on a healthy connection. Crucially this is **outside
§8's disclosure**, which covers a verb *spanning* the blip, not one
*starting after recovery*. Reachable: a bulk is the longest-running verb on
the surface and the likeliest to span an outage. Untested: test 10 asserted
only that loss resets the counter.

*Fold:* §4.3 and §5.1 now clear the flag on connection loss, with the
failure trace recorded inline; new **test 10b** (open a bulk → drop before
its terminal → restore → run a fresh bulk → strip must appear); new
**V-13**.

**m — §5.1's re-render rule had no assertion.** *Fold:* folded into test 9b
rather than a new test, since 9b already stands at the decrement-to-nonzero
moment — it now also asserts the strip reverts to the `applying` label.

**NIT — §4.3's bullet head still read "ONE counter for BOTH envelope
types"**, the phrasing that produced R4-M1. Judged harmless, since every
table row names `bulkInFlight` and the MUST-NOT is bold. *Fold:* reworded
anyway — it cost a round once.

## Round 6 — NOT SOUND (0 BLOCKER, 1 MAJOR)

Q1/Q2/Q4 clean: test 10b verified to bind V-13 by walking the flag-left-set
path; clearing the flag on connection loss verified never wrong (a late
progress frame after reconnect re-populates and the strip *resumes* rather
than staying dark); two overlapping bulks shown to end at 0/false with only
a transient display flicker.

**M — the clamp rule broke the flag's invariant.** `bulkInFlight` true ⟹
counter ≥ 1 was violated by the clamp, which sat two bullets below the flag
rule in §4.3 and was never reconciled with it — the same root-cause shape as
R5-M1. An unmatched `applying/done` arriving while a bulk was live
decremented to zero, hid the strip, and left the flag true, silencing the
rest of the bulk run.

Critically, the reviewer showed **the bad ordering is designed-in, not
coincidental**: §5.6 publishes the progress frame *before* the item, and
`runner.run` acquires the serialization lock at its top (`runner.py:270`),
so a bulk submitted while another verb holds the lock *necessarily* emits
its first frame before that verb's `done`. It also upgraded its own grade
from MINOR to MAJOR on the reasoning that "the counter never goes wrong"
measures the wrong thing — the deliverable is that the strip is visible
while work is happening.

**This was the third consecutive round whose finding had one shape: new
state introduced without reconciling an older rule that touched it**
(R4-M1 flag-vs-counter, R5-M1 flag-vs-connection-loss, R6-M1 flag-vs-clamp).

*Fold:* **design pivot** rather than a fourth one-clause patch — see round 7.

## Round 7 — NOT SOUND (0 BLOCKER, 1 MAJOR, 1 MINOR, 1 NIT); mechanism CLEAN

§4.3's counter-plus-flag was replaced by a keyed Map of in-flight work:
three rules over one variable instead of six over two.

```
applying/start       -> set("applying:"+verb+":"+id, {badge, detail})
applying/done|error  -> delete("applying:"+verb+":"+id)
bulk progress        -> set("bulk", {badge, detail})
bulk terminal        -> delete("bulk")
connection loss      -> clear()
```

Render after every operation: hide if empty, else `get("bulk")` if present,
else the first entry in insertion order.

**The reviewer implemented §4.3/§5.1 as written and ran everything
mechanically rather than hand-walking it.** Twelve sequences for twelve
passed, all ending with an empty Map and a hidden strip — including two
overlapping bulks, which a single boolean could not represent under the old
design. The render ladder (two applying → bulk opens → third applying →
bulk terminal → first applying ends) was verified deterministic, JS `Map`
insertion order being spec-guaranteed and re-`set` preserving position.

Every defect rounds 2–6 found dissolves structurally: R2-B3 (one Map,
membership *is* the state), R3-B1 (`set` idempotent), R4-M1 (no flag
exists), R5-M1 (`clear()` is one op over one variable), R6-M1 (`delete` of
an absent key is a no-op — precisely what the clamp approximated and got
wrong), R4-m2 (render derives from contents every op).

The reviewer also found the Map **strictly better than the counter** on a
path nobody was hunting: a retried verb reuses its key and overwrites, where
the counter double-counted.

**M — test 10b and V-13 were inherited from the counter design and guarded
nothing.** Under V-13 the stale `"bulk"` entry survives the outage, but the
fresh bulk's first progress frame overwrites it, so the strip shows with
correct text and the test passes. The spec had stated this reason at
§5.1 itself and kept the test anyway. *Fold:* retargeted to the measured
binding — after loss and reconnect, an `applying/start` must render the
`applying` label, not a stale `graduating` (baseline `applying → route`
vs V-13 `graduating 1 of 3`).

**m — V-12's wording produced no collision**, the `applying` key being
dynamic. *Fold:* reworded to collapse both sides to one constant.

**NIT — §11 cited the deleted already-in-flight rule.** *Fold:* reference
updated to `set` idempotence; conclusion unchanged.

**On the pivot itself (asked directly):** judged justified, and patching
judged the worse call — "that class is structurally prevented when there is
only one piece of state; there is no second variable to leave unreconciled."

## Round 8 — **SOUND**

Both retargets confirmed by measurement: the reworded test 10b binds V-13
(baseline PASS / V-13 FAIL), and the reworded V-12 binds test 9b.

**The result the verdict rests on is a 20,000-case randomized fuzz** the
reviewer added unprompted — 1–3 concurrent `applying` verbs (each start
paired with a later done), 0–2 bulk runs of size 0–4 with random failure
points including N=0 and fail-at-item-1, 0–2 injected SSE losses at random
positions, all interleaved arbitrarily with per-stream order preserved:

```
20000/20000 ended Map-empty and strip hidden; 0 violations
```

A different class of evidence from "the twelve sequences I thought of pass."

Prose sweep clean: all 13 counter/clamp/flag hits classified individually as
historical, intentional (§7.2's S-row), or current-and-correct (§5.1's "no
counter, no flag, no clamp"), against 58 hits of Map-era vocabulary. §8 was
re-read unprompted and holds — exact for a single `applying` verb, slightly
pessimistic for a bulk, which is the safe direction for a disclosure.

Mutation roster complete at fourteen (V-1…V-10, V-12…V-15; V-11 correctly
absent), every one naming a test. Counts reconcile.

One operational note, explicitly not a finding: test 10b needs
`wait_for_subscriber` before the `applying/start` is pushed. Failure mode is
loud, not vacuous. Folded into §6 as a builder note.

**Retrospective on the pivot, from the reviewer:** the counter design
produced a finding in five consecutive rounds; the Map produced two in one
round — both in the mutation plan, neither in the mechanism — none in the
next, and survives randomized search. That is the empirical justification
for the round-7 call, and belongs in §7.2's S-row.

---

# Code gate — build (2026-07-25)

Blind code gate on the uncommitted build. Reviewer did not read this
directory. Round 1 **NOT CLEAN** (1 BLOCKER, 1 MINOR, 3 NIT); round 2
**CLEAN**.

## Round 1 — mutation matrix: 13 of 14 bound

All fourteen §11 mutations were applied, the named tests run, and each
reverted by reverse-`Edit`; the full working diff was `cmp`-verified
identical to its pre-gate state afterwards.

**BLOCKER — V-6 survived: test 7's `pageerror` assertion was structurally
dead.** The test used `time.sleep(0.3)` before `assert errors == []`.
`time.sleep` never enters playwright-python's sync event dispatcher, so the
list is empty at assert time *regardless of duration* — making it, in
substance, exactly the DOM-only assertion §11 says "stays green."

The measurement that makes this actionable rather than a flakiness guess:

| Variant (with V-6 applied) | Result |
|---|---|
| `time.sleep(0.3)` — as built | `1 passed` |
| `time.sleep(1.5)` — 5× longer | `1 passed` |
| `page.wait_for_timeout(300)` | **FAILED** with the thrown error |

A longer sleep is *not* the fix and would have made the test permanently
useless while looking more robust. **The test written to catch the
project's signature defect was itself an instance of it.**

*Fold:* `page.wait_for_timeout(300)`, with `assert errors == []` moved after
the existing `expect(...).to_be_hidden()` — two dispatcher round-trips, so
the fix does not depend on either alone. The comment records the mechanism
*and* the negative result, which is what prevents the wrong fix. Binding
verified independently by both orchestrator and reviewer.

**MINOR — a false "MEASURED" claim.** `_wait_for_js_flag`'s docstring
asserted as measured that this app's CSP (`script-src 'self'`) rejects
Playwright's `wait_for_function`. The gate probed it directly: the
expression form returns OK with zero console CSP violations, and the same
file already uses `wait_for_function` successfully three times. *Fold:* the
rationale corrected, the code kept (rewriting working waits on a false
premise is the larger risk), and the correction *recorded* rather than
deleted so the false claim cannot be resurrected from history as verified.

**NITs:** spec drift (§6 heading said 36 while F4/DoD reconciled to 35 —
the build correctly matched F4, so 962 not 963); a duplicated sentence in
S-20's Notes; and the `data-verb-error` synthetic-body deviation, judged
acceptable (it prevents a pending reload destroying the JS context and has
no path to the detach mechanism under test).

**The three builder deviations were each judged, not accepted on
explanation.** `set_offline` → `_simulate_sse_error` was confirmed
legitimate by independent reproduction (`set_offline(True)` leaves an
established EventSource untouched for 12 s while `fetch()` fails
immediately), *and* proven load-bearing on production code by V-13 — which
flips test 10b to `assert 'graduating' == 'applying'` when `source.onerror`
is mutated.

## Round 2 — **CLEAN**, matrix 14/14

V-6 re-applied by the reviewer independently — failing at the `errors`
assertion line, i.e. caught by the `pageerror` leg rather than incidentally
by the DOM leg — then reverted, md5 restored, diff `cmp`-identical.

The other 13 rows were carried forward rigorously rather than assumed: §11
unchanged, every production file the other mutations target byte-identical
pre/post-fold, and the only behavioural change inside `test_js_dom.py`
being test 7's body.

Two new NITs, neither fold-caused: residual stale "two banner tests"
plurals (folded), and one non-reproducible timing failure in
`test_retry_presses_r_and_posts_pane_retry` observed only when the two
suites ran concurrently — traced to `_wait_for_held`'s 5 s wall-clock
budget under contention, with the file's diff hunk proven byte-identical
pre/post fold. Recorded in the spec's §9.1 so a future CI flake is not
mysterious.

DoD independently re-run at both rounds: `-m js` 75 passed; `-m 'not js'`
1 failed / 962 passed (the known pre-existing failure); CLI 1117 passed /
5 skipped; pyright exactly 50 on `cli/src`, 0 on `ui/src`; `hx-disabled-elt`
= 4 with a live positive control.
