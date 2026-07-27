# Spec — the selection ring must govern the verb keys

Status: **revision 2** — folds the blind spec gate (NOT SOUND, 5 blockers).
Motivating finding: `ui-walks.md` **W4-F1** (walk 4, 2026-07-26).

---

## 1. The defect

On a bucket page listing N record rows, every record verb key acts on the
**first such row in document order**, whatever the selection ring shows.

`static/app.js:54-61`:

```js
function clickAction(action) {
  const el = document.querySelector('[data-key-action="' + action + '"]');
  if (el) { el.click(); return true; }
  return false;
}
```

`document.querySelector` returns the first match in document order. The
ring is an unrelated mechanism: `.selected`, written by `moveSelection`
(`app.js:84-92`) and `ensureRowSelected` (`app.js:114-119`), read only by
those two and `drillIntoSelection` (`app.js:94-100`). Nothing connects
the ring to verb dispatch — verified by the gate, which looked for any
other scoping mechanism (CSS, server markup, event delegate, htmx) and
found none.

**Why this is P0.** Every other finding in five walks costs
comprehension. This one costs correctness: with the ring on record 5,
`x` denies record 1. Deny and Graduate are destructive and the ring is
the only "you are here" a record row draws.

> "With Approve/Deny/Graduate on the line, I stopped trusting the ring —
> but there is nothing else to trust instead." — walk 4

**Reproduced twice**, once with DOM focus on card 1 and once with focus
on `BODY`, which rules out focus and leaves document order.

**Precision correction (gate N6):** with an expanded cluster,
`cluster_expanded.html:15` renders `data-key-action="route"` inside
`.cluster-row[data-row]`, which precedes the group's record rows
(`bucket.html:48` before `:61`). So `e` today hits the *cluster's* route
button, not necessarily "record 1". The defect is document order, not
literally the first record.

---

## 2. What it must do instead

Resolution order for `clickAction`, first match wins:

| # | When | Search scope |
|---|---|---|
| 1 | an armed action bar exists | **that bar's subtree** |
| 2 | the action is **row-scoped** AND the selected row is a **`.record-row`** | **that row's subtree, no fallback** |
| 3 | otherwise | the document, unchanged |

Rule 2 is narrower than revision 1's "any selected row". Revision 1 was
NOT SOUND for two independent reasons the gate measured, B1 and B2 below.

### 2.1 Rule 1 prevents a mouse regression

`app.js:206-215` dispatches `confirm`/`disarm` through the same
`clickAction` and returns before the keymap switch. `ensureRowSelected`
puts the ring on row 0 on every load, so a mouse user clicking row 5's
Approve leaves the ring on row 0 and the armed bar in row 5. Scoping
`confirm` to the ringed row would **stop Enter confirming for mouse
users** — a keyboard fix that breaks the mouse.

Verified by the gate: both targets live inside the armed bar
(`action_bar.html:99`, `:107`), and arming swaps only `#{{ dom_id }}`
(`hx-target`/`outerHTML`), so `.selected` on the enclosing row survives.

**Rule 1 also closes a latent hazard (gate N5)** this spec did not
claim: `action_bar.html:10` sets `data-armed="true"` for the commit-drift
armed sub-state, which renders `commit_drift_confirm`/`_disarm`, not
`confirm`/`disarm`. With row 3 commit-drift-armed and row 5 genuinely
armed, today's document-wide `clickAction("confirm")` fires **row 5's**
confirm. Rule 1 makes that impossible.

### 2.2 The row-scoped action set is explicit — B1

**Blocker (measured).** `goUp()` (`app.js:163-167`) dispatches
`interrupt` and `up` through `clickAction`, in the **not-armed** branch,
so rule 1 never covers them. `[data-key-action="up"]` is not inside
`#self-learn-ui-content` at all — it is in `<header>`
(`bucket.html:9`, outside `<main>` at `base.html:62-78`). `interrupt`,
`retry`, `close_pane`, `pane_send` (`pane.html:48,74,79,89-94`),
`bucket_pane` (`pane_idle.html:31,37`) and `arm_proposal`
(`proposal_bar.html:78`) are inside content but outside every
`[data-row]`.

Under revision 1, every one of them returned false on any bucket page,
and Escape fell through to `window.history.back()` — **propagating
W4-F3**, the finding §5 parks as out of scope, from Front to Bucket. It
also broke Escape-interrupts-a-streaming-pane, the sibling of the defect
`app.js:169-183` exists to close.

Revision 1 also contradicted itself: §2.3 claimed `up`/`interrupt` reach
their targets "through rule 3", which is only true if rule 2 falls back,
which §2.2 forbade. **The builder would have had to invent the
resolution.**

Rule 2 therefore applies **only** to this set:

```
route · reject · defer · graduate · cycle_destination · toggle_brief
tolerate · confirm_recurrence · success_next · success_bucket · success_view
```

Every other action — `up`, `interrupt`, `confirm`, `disarm`,
`bucket_pane`, `arm_proposal`, `retry`, `close_pane`, `iterate`,
`pane_send`, `commit_drift_*` — is **never** row-scoped and keeps
today's document-wide behaviour exactly.

**Invariant, tested:** the set must partition `KEYMAP` — every keymap
action is either row-scoped or explicitly not, with no action in neither
list and none in both. `tests/test_keymap.py:10-46` already tests key
uniqueness this way; follow it.

### 2.3 Rule 2 applies only to `.record-row` — B2 and B4

**Blocker (measured).** Revision 1 claimed the front page would be
"byte-identical" because `<tr data-row>` carries no verb buttons. That
reasoned about one of **seven** `[data-row]` variants. `.holding-row`
(`index.html:80-85`) and `.followup-row` (`:94-99`) include
`action_bar.html` and **do** carry verbs. With the ring on `TR` row 0,
revision 1 made `t`, `c` and `g` dead on the front page and turned three
green tests red — `test_js_dom.py:2161`, `:2171`, `:2183` — none of
which revision 1 mentioned.

**Second blocker (measured).** `style.css:762-767` rings only
`.record-row[data-row].selected` and `tr[data-row].selected`. The gate
measured a selected `.holding-row` with computed `outline: none`.
Revision 1 would have made an **invisible** selection authoritative for
destructive verbs — including `.bulk-collapse-row`
(`bucket.html:66-72`), whose `graduate` is a **bulk** acknowledge over
`group.bulk_collapse.ids`, and `.near-miss-row` (`index.html:141`),
which lives inside a default-collapsed `<details>` and can hold the ring
while invisible.

The boundary that resolves both:

> **Rule 2 applies exactly where the ring is both visible and
> verb-bearing.**

`.record-row` is that set. `tr[data-row]` is ringed but carries no
row-scoped verb, so rule 3 covers it and the front page stays
byte-identical — *now actually byte-identical, not asserted to be*.
`.holding-row`, `.followup-row`, `.near-miss-row`, `.cluster-row` and
`.bulk-collapse-row` are unringed, stay on rule 3, and behave exactly as
today.

This deliberately leaves the missing ring on those five variants
**unfixed and out of scope**. It is a real gap — see §5 — but rule 2 no
longer converts it into a targeting hazard.

### 2.4 No fallback, and the miss must speak — B3

If the selected `.record-row` does not contain a row-scoped action, the
outcome is **nothing happens to any record**. Falling back to the
document would reinstate the defect for rows whose action set differs.

**Blocker (measured).** Revision 1 claimed such a miss "joins the
existing no-op hint path. No new mechanism." Technically true, and
substantively false: `dispatchOrHint` (`app.js:270-281`) emits only for
a `[data-noop-hint][data-noop-action]` element — rendered at exactly one
site, `action_bar.html:196-202` — or a `NOOP_MESSAGES` entry, and
`NOOP_MESSAGES` (`app.js:266-268`) has **one** key, `toggle_brief`. A
miss on `route`/`reject`/`defer`/`graduate`/`tolerate`/
`confirm_recurrence` renders **nothing**. Revision 1's acceptance test 2
was unbuildable.

**Ruling:** this unit adds `NOOP_MESSAGES` entries for the row-scoped
verbs. Silence would create a new dead key, which is the class this
project has now shipped four times (W4-F4) and the reason the keymap
refuses to encode dead keys (`keymap.py:118-128`). Wording states the
gate in plain words, e.g. *"this record is already resolved"* for a
verb missing from an evidence-leg row.

**Which rows actually differ (gate N1).** Revision 1 cited deferred rows;
measured, `record-row-deferred` is `opacity: 0.6` and nothing else
(`style.css:788-790`) and includes the same `action_bar.html`. The real
case is the **success/evidence leg**: a resolved row renders
`evidence.html` and suppresses the quad (`action_bar.html:11-13`, guard
at `:166`), carrying `success_next`/`success_bucket`/`success_view`
instead. Cite that; it is also the fixture for acceptance test 2.

### 2.5 `n` gets the same treatment — B5

**Blocker.** §1 named `n` among the affected keys, but `n` never reaches
`clickAction`: `app.js:233-235` routes it to `focusNote`, which runs its
own document-wide query (`app.js:69-74`). Revision 1 pinned the change to
"one function's search scope", leaving `n` focusing record 1's note field
while the ring is on row 5.

That is **worse than a dead key.** The note posts via
`hx-include="#form-{{ dom_id }}"` (`action_bar.html:171`), so text typed
into row 1's field then armed on row 5 silently attaches nothing, and the
only tell is the armed strip reading "no note" (`action_bar.html:93`).

`focusNote` takes the same resolution order. Note for the builder:
`app.js:71`'s `const scope = armed ? document : document;` is dead code —
both branches identical, `scope` unused.

---

## 3. Acceptance

1. **Bucket page, ≥2 record rows, ring on row 2, press a verb** → row 2
   arms; row 1 does **not**.
2. **Ring on a resolved (evidence-leg) row, press `e`** → no bar arms
   anywhere **and** the new no-op hint renders.
3. **Armed bar in row 5, ring on row 0, press Enter** → row 5's confirm
   fires. (§2.1, the mouse regression.)
4. **Escape on a bucket page with the ring on a record row** → reaches
   the header `up` target; does **not** fall through to
   `history.back()`. (§2.2, B1.)
5. **Escape on a bucket page with a streaming pane** → interrupts the
   pane. (§2.2, the F5-3 sibling.)
6. **Front page: `t`, `c`, `g` with the ring on `TR` row 0** → behave
   exactly as today. (§2.3, B2 — these are `test_js_dom.py:2161/2171/2183`,
   which must stay green **unmodified**.)
7. **`n` with the ring on row 2** → focuses row 2's note field, and a
   note typed there rides that row's verb.
8. **Record detail page** → every verb key behaves exactly as before.
9. **KEYMAP partition invariant** (§2.2).

### 3.1 Mutation plan

| Mutation | Test that must fail |
|---|---|
| revert `clickAction` to the document-wide query | 1 |
| add a document fallback after a row-scoped miss | 2 |
| drop rule 1, so `confirm` scopes to the ringed row | 3 |
| add `up`/`interrupt` to the row-scoped set | 4, 5 |
| widen rule 2 from `.record-row` to any `[data-row]` | 6 |
| leave `focusNote` document-wide | 7 |
| remove one action from the row-scoped set | 9 |

**Positive control on test 1.** Assert row 2 armed **then** row 1 not
armed, in that order — "row 1 did not arm" passes vacuously on a page
that armed nothing. This is `lrn-ea833a5b`, which this surface has now
met five times.

**Run-evidence control (gate N4).** `test_js_dom.py:83-88` is an
`importorskip` and the `browser` fixture can `pytest.skip`, so **a
skipped module is not a red test and every mutation would leave the
suite green.** The mutation plan requires the collected/passed count for
`-m js`, not an exit status. Baseline measured by the gate on this host:
**71 passed**.

**Fixture pinning (gate N2).** Mutation 2 only bites if the action
exists elsewhere on the page; pin ≥2 rows where row A has the action and
the ringed row B does not.

### 3.2 The suite could not have caught this

Stated because it tells the builder what to add. **No test presses a
record verb key on a bucket page.** `TestNeverPressedKeymapActions`
(`test_js_dom.py:2124-2199`) drives `x`/`f`/`g`/`n`/`i` on
`/record/<id>` — measured to have **zero** `[data-row]`, the one page
shape where this defect cannot occur. The only bucket-page keyboard test
is `p`, a page-level action.

**A new fixture is part of the deliverable (gate N3).** Every seeded
bucket holds exactly one pending record, and `test_js_dom.py:311-320`,
`:455-459` forbid adding records to the shared ledger. Tests 1, 2 and 7
need a module-scoped ledger + server fixture with a ≥2-record bucket.

---

## 4. Revision history

- **r1** — three rules keyed on "any selected row". **NOT SOUND**, five
  blockers: it killed `up`/`interrupt` on every bucket page (B1), broke
  three front-page keys and three green tests (B2), promised a no-op hint
  that emits nothing (B3), made an invisible selection authoritative for
  a bulk destructive verb (B4), and named `n` while excluding the
  function that implements it (B5).
- **r1 claims that were measured false**, recorded because the pattern
  repeats: "front-page behaviour byte-identical" (inferred from one row
  variant of seven), "deferred rows render differently" (inferred from a
  class name; it is opacity only), "the no-op is not silent" (inferred
  from the existence of a code path without checking what it emits), and
  a §2.3 sentence that contradicted §2.2. Four inferences stated as
  measurements — the same failure mode recorded in the
  resolution-evidence spec's §9.
- **r2** — this document.

## 5. Out of scope

- **W4-F2** `Enter` on a focused button navigates instead of pressing it.
- **W4-F3** `Escape` at the front page goes down, not up. Note r1 would
  have *spread* this; r2 must not.
- **W3-F1** the commit-drift evidence hole (`routes.py:1781-1790`) — the
  next P0.
- **W4-F4** the dead-key set `h`/`r`/`v` and the unconditional overlay.
- **The missing ring on `.holding-row`, `.followup-row`, `.cluster-row`,
  `.bulk-collapse-row`, `.near-miss-row`** (gate B4). Real, unreported by
  any walk, and now decoupled from targeting by §2.3. Worth its own item.
