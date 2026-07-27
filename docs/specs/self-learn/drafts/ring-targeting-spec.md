# Spec — the selection ring must govern the verb keys

Status: **revision 3** — folds spec-gate rounds 1 (B1–B5) and 2 (B6–B10).
Motivating finding: `ui-walks.md` **W4-F1** (walk 4, 2026-07-26).

---

## 1. The defect

On a bucket page listing N record rows, every record verb key acts on the
**first matching target in document order**, whatever the selection ring
shows.

`static/app.js:54-61`:

```js
function clickAction(action) {
  const el = document.querySelector('[data-key-action="' + action + '"]');
  if (el) { el.click(); return true; }
  return false;
}
```

The ring is an unrelated mechanism: `.selected`, written by
`moveSelection` (`app.js:84-92`) and `ensureRowSelected`
(`app.js:114-119`), read only by those two and `drillIntoSelection`
(`app.js:94-100`). The gate looked for any other scoping mechanism —
CSS, server markup, event delegate, htmx — and found none.

**Why this is P0.** Every other finding in five walks costs
comprehension. This one costs correctness: with the ring on record 5,
`x` denies a different record. Deny and Graduate are destructive and the
ring is the only "you are here" a record row draws.

> "With Approve/Deny/Graduate on the line, I stopped trusting the ring —
> but there is nothing else to trust instead." — walk 4

Reproduced twice, once with DOM focus on card 1 and once with focus on
`BODY`, which rules out focus and leaves document order. With an expanded
cluster the first match is the *cluster's* `route`
(`cluster_expanded.html:15`, which precedes the group's record rows), so
the defect is document order, not literally "record 1".

---

## 2. What it must do instead

Resolution order, first match wins:

| # | When | Search scope |
|---|---|---|
| 1 | an armed action bar exists | **that bar's subtree** |
| 2 | the action is **row-scoped** AND the selected row is a **`.record-row`** | **that row's subtree, no fallback** |
| 3 | otherwise | the document, unchanged |

### 2.1 Rule 1 prevents a mouse regression

`app.js:206-215` dispatches `confirm`/`disarm` through `clickAction` and
returns before the keymap switch. `ensureRowSelected` puts the ring on
row 0 on every load, so a mouse user clicking row 5's Approve leaves the
ring on row 0 and the armed bar in row 5. Scoping `confirm` to the ringed
row would **stop Enter confirming for mouse users**.

Verified: both targets live inside the armed bar (`action_bar.html:99`,
`:107`), and arming swaps only `#{{ dom_id }}`, so `.selected` on the
enclosing row survives.

Rule 1 also closes a latent hazard: `action_bar.html:10` sets
`data-armed="true"` for the commit-drift sub-state, which renders
`commit_drift_confirm`/`_disarm`. With row 3 commit-drift-armed and row 5
armed, today's document-wide `clickAction("confirm")` fires **row 5's**
confirm. Rule 1 makes that impossible.

### 2.2 All 22 keymap actions are classified — B1, B6

Measured: `KEYMAP` holds exactly 22 distinct actions. Revision 2 listed
two groups that between them covered 17, named four values that are not
keymap actions at all, and left five unclassified — including `note`,
which §2.2 called document-scoped while §2.5 and test 7 required the
opposite. A builder had to invent the resolution. Same self-contradiction
shape as r1's B1.

**Bucket A — row-scoped (7).** Target resolved inside the selected
`.record-row`; no fallback.

```
route · reject · defer · graduate · cycle_destination · toggle_brief · note
```

**Bucket B — document-scoped (11).** Target resolved document-wide,
behaviour byte-identical to today.

```
up · iterate · bucket_pane · arm_proposal · retry · close_pane
tolerate · confirm_recurrence · success_next · success_bucket · success_view
```

**Bucket C — no DOM target lookup (4).** Pure client behaviour, explicit
`switch` cases at `app.js:220-238`, never reaches a lookup.

```
move_down · move_up · drill_in · help
```

**Invariant, tested (test 9):** the three buckets are pairwise disjoint
and their union equals `{e.action for e in KEYMAP}` exactly. Not "each
action is in one of two lists" — that is trivially satisfiable and was
the defect in r2. The point of the test is that **adding a keymap action
without classifying it fails the build.**

**`up` and `interrupt` are in bucket B for a measured reason (B1).**
`goUp()` (`app.js:163-167`) dispatches `interrupt` then `up` through
`clickAction`, in the **not-armed** branch, so rule 1 never covers them.
`[data-key-action="up"]` is not inside `#self-learn-ui-content` at all —
it is in `<header>` (`bucket.html:9`, outside `<main>` at
`base.html:62-78`). Row-scoping them would have made Escape fall to
`window.history.back()` on every bucket page — **propagating W4-F3**,
the finding §5 parks as out of scope — and broken
Escape-interrupts-a-streaming-pane, the sibling of the defect
`app.js:169-183` exists to close.

**`tolerate`/`confirm_recurrence` are in bucket B (N8).** Their targets
render only on `.holding-row` (`index.html:80-85`), never on a
`.record-row`, so rule 2 could never find them. Row-scoping them would
change `t` on a bucket page from silent to hinted with wording that
cannot be honest — the record is pending; the verb simply does not apply
to record rows.

**`success_*` are in bucket B — B9, measured.** The gate measured a
mouse arm-then-confirm cycle on a 3-record bucket: **the ring never moves
across arm or across confirm.** In that fixture row 0 is a
`.bulk-collapse-row`, so the `.record-row` guard accidentally saves
`j`/`u`/`v`; in a bucket with no bulk group the ring sits on
`.record-row` 0, which has no `success_*`, and they become misses. The
state persists — `[data-verb-success]` holds the reload
(`app.js:478`) — so the user sits on a page with a visible **"Next
pending record (j)"** link that does nothing.

Independently of the bug: `j`/`u`/`v` are **navigation, not record
verbs**. "Next pending record" has no per-row meaning. Document scope is
also unambiguous by construction — the success leg is unique on the page,
since `action_bar.html:166` suppresses the quad on the resolved row.

### 2.3 Rule 2 applies only to `.record-row` — B2, B4

The boundary states its own justification:

> **Rule 2 applies exactly where the ring is both visible and
> verb-bearing.**

Verified by the gate in both directions. `tr[data-row]` is ringed
(`style.css:764-765`) but bears no bucket-A action. `.holding-row`,
`.bulk-collapse-row`, `.followup-row` bear actions but are **not** ringed
— the gate measured a selected `.holding-row` with computed
`outline: none`. `.near-miss-row` is neither, and its Promote button
carries no `data-key-action`. `.cluster-row` bears `route`
(`cluster_expanded.html:15`) but is not ringed, so it stays on rule 3 and
behaves exactly as today. **`.record-row` is the unique intersection**,
and it renders at one site only (`bucket.html:76`), always with
`data-row`.

Revision 1 reasoned about one of seven `[data-row]` variants, which would
have made `t`/`c`/`g` dead on the front page, turned three green tests
red, and made an *invisible* selection authoritative for
`.bulk-collapse-row`'s **bulk** graduate over `group.bulk_collapse.ids`.

**Unclaimed improvement (N11):** with a cluster expanded and the ring on
a `.record-row`, rule 2 finds that record's own `route`, so the cluster's
`route` no longer shadows every record row.

### 2.4 No fallback, and the miss must speak — B3, B10

A bucket-A miss inside the selected `.record-row` means **nothing happens
to any record**. Falling back to the document would reinstate the defect
for rows whose action set differs — measured, that is the
**success/evidence leg**, which renders `evidence.html` and suppresses
the quad (`action_bar.html:11-13`, guard at `:166`). Not deferred rows:
`record-row-deferred` is `opacity: 0.6` and nothing else
(`style.css:788-790`) and includes the same action bar.

**The miss must be audible.** `dispatchOrHint` (`app.js:270-281`) emits
only for a `[data-noop-hint][data-noop-action]` element — one render site,
`action_bar.html:196-202` — or a `NOOP_MESSAGES` entry, and
`NOOP_MESSAGES` (`app.js:266-268`) has **one** key. This unit adds
entries for bucket A's `clickAction` verbs. Silence would ship a fifth
advertised-key-bound-to-nothing (W4-F4), the class `keymap.py:118-128`
exists to refuse.

**Wording must name the actual cause**, not one template — "this record
is already resolved" is right for a verb missing from an evidence-leg row
and would be wrong elsewhere.

**`n` needs its own mechanism — B10.** `focusNote` (`app.js:69-74`) ends
`if (input) input.focus();` with no `else`, and `case "note"`
(`app.js:233-235`) never calls `dispatchOrHint`, so §2.4's ruling
structurally cannot reach it. Measured: after a confirm, the evidence-leg
row carries **no** `input[name="note"]`, so the ordinary flow — confirm
row 2, press `n` — would produce silence where today it wrongly focuses
another row. **`focusNote`'s miss routes through `showNoopHint`
(`app.js:293-303`) with its own message.** Forbidding a silent dead key
in one function while creating one in the other, in the same document,
is not acceptable.

### 2.5 `n` is row-scoped — B5

`n` never reaches `clickAction`: `app.js:233-235` routes it to
`focusNote`, which runs its own document-wide query. Left alone, `n`
focuses another row's note field while the ring is on row 5. That is
**worse than a dead key**: the note posts via
`hx-include="#form-{{ dom_id }}"` (`action_bar.html:171`), so text typed
into row 1's field then armed on row 5 silently attaches nothing, and the
only tell is the armed strip reading "no note" (`action_bar.html:93`).

`focusNote` takes rules 2 and 3. **Rule 1 is inert for it (N9)** —
`case "note"` is reachable only in the not-armed branch — so no rule-1
test for `n` is possible; do not write one.

Builder note: `app.js:71`'s `const scope = armed ? document : document;`
is dead code — both branches identical, `scope` unused.

### 2.6 Where the classification lives — B7

**Decided, not left to the builder.** The three buckets ride
`KeymapEntry` as a field, so `keymap_as_dicts()` carries them into the
JSON blob that `loadKeymap` already parses (`app.js:28-39`).

A Python-only constant would be wrong in a way that matters: §3.1's
mutation *"remove one action from bucket A"* would then edit `app.js`
and leave the Python invariant test green while behaviour broke — the
mutation would not bite. A duplicated list also violates the
single-source doctrine both files open with (`app.js:1-8`,
`keymap.py:1-6`). Riding `KeymapEntry` keeps
`test_served_keymap_blob_matches_source` (`test_js_dom.py:1331`) and
`test_keymap_covers_every_pinned_action` valid and makes one edit change
both sides.

**Non-keymap `data-key-action` values** — `confirm`, `disarm`,
`interrupt`, `pane_send`, `commit_drift_confirm`, `commit_drift_disarm` —
are dispatched by rule 1 or by `goUp`, are not keymap actions, and are
outside the invariant. Test 9 must not assert over them.

---

## 3. Acceptance

1. **Bucket page, ≥2 record rows, ring on row 2, press a bucket-A verb**
   → row 2 arms; row 1 does **not**.
2. **Ring on a resolved (evidence-leg) row, press `e`** → no bar arms
   anywhere **and** the new no-op hint renders.
3. **Armed bar in row 5, ring on row 0, press Enter** → row 5's confirm
   fires. (§2.1.)
4. **Escape on a bucket page, ring on a record row** → reaches the header
   `up` target. **See §3.1 for the discriminator this test must use.**
5. **Escape on a bucket page with a streaming pane** → interrupts.
6. **Front page: `t` and `c` with the ring on `TR` row 0** → unchanged.
   These are `test_js_dom.py:2171` and `:2183`, which must stay green
   **unmodified**. (N7: r2 also cited `:2161`, which is a *bucket*-page
   `p` test and cannot bite this mutation; `g` on the front page has no
   test — add one or drop the claim.)
7. **`n` with the ring on row 2** → focuses row 2's note field, and a
   note typed there rides that row's verb.
8. **`n` on a row with no note input** → the new `focusNote` hint
   renders. (§2.4, B10.)
9. **Three-bucket invariant** — disjoint, union equals `KEYMAP`. (§2.2.)
10. **`j`/`u`/`v` after a mouse arm-then-confirm, ring never moved** →
    all three still work. (§2.2, B9.)
11. **Record detail page** → every verb key behaves exactly as before.

### 3.1 Mutation plan

| Mutation | Test that must fail |
|---|---|
| revert `clickAction` to the document-wide query | 1 |
| add a document fallback after a bucket-A miss | 2 |
| drop rule 1, so `confirm` scopes to the ringed row | 3 |
| move `up`/`interrupt` into bucket A | 4, 5 |
| widen rule 2 from `.record-row` to any `[data-row]` | 6 |
| leave `focusNote` document-wide | 7 |
| drop `focusNote`'s miss hint | 8 |
| move an action out of its bucket | 9 |
| move `success_*` into bucket A | 10 |

**Test 4's discriminator — B8, measured.** From a bucket page,
`history.length = 3` and `history.back()` lands on **exactly the URL the
header `up` link navigates to** (`/`). So a test 4 that asserts "reaches
the front page" — including an exact `wait_for_url(base + "/")` — **passes
on the broken build**, because `goUp()` falls through to
`window.history.back()` (`app.js:166`) and arrives at the same place.

Test 4 must therefore use a discriminator `history.back()` cannot fake.
The suite already has the technique:
`test_escape_first_rung_interrupts_pane_before_up`
(`test_js_dom.py:1372-1394`) injects
`<a data-key-action="up" href="#went-up">` and asserts `location.hash`.
Use that, **and** assert `history.length` is unchanged.

This is the third time `lrn-ea833a5b` has bitten this unit, and the first
time it bit a test written specifically to guard against a regression,
in a document that cites the lesson twice. Note it in the fold.

**Positive control on test 1.** Assert row 2 armed **then** row 1 not
armed, in that order — "row 1 did not arm" passes vacuously on a page
that armed nothing.

**Run-evidence control.** `test_js_dom.py:83-88` is an `importorskip`
and the `browser` fixture can `pytest.skip`, so **a skipped module is not
a red test and every mutation would leave the suite green.** Report the
collected/passed count for `-m js`, not an exit status. Measured
baseline, both gate rounds: **71 passed**.

**Fixture pinning.** Mutation 2 only bites if the action exists elsewhere
on the page; pin ≥2 rows where row A has the action and the ringed row B
does not.

### 3.2 The suite could not have caught this

**No test presses a record verb key on a bucket page.**
`TestNeverPressedKeymapActions` (`test_js_dom.py:2124-2199`) drives
`x`/`f`/`g`/`n`/`i` on `/record/<id>` — measured to have **zero**
`[data-row]`, the one page shape where this defect cannot occur. The only
bucket-page keyboard test is `p`, a page-level action.

**Check `f2_server` before building a fifth fixture.** The gate measured
`/bucket/skill/s` on it as 4 `[data-row]` — 3 `.record-row`
(`lrn-f2000001/2/3`) plus a `.bulk-collapse-row`. r2 asserted "every
seeded bucket holds exactly one pending record"; that is true of the
**shared** ledger and false of `f2_server`. Reuse it if it fits.

---

## 4. Revision history

- **r1** — rules keyed on "any selected row". **NOT SOUND**, 5 blockers:
  killed `up`/`interrupt` on every bucket page, broke three front-page
  keys and three green tests, promised a no-op hint that emits nothing,
  made an invisible selection authoritative for a bulk destructive verb,
  and named `n` while excluding the function that implements it.
- **r2** — **NOT SOUND**, 5 further blockers, all in the surface r1's
  fixes added. Four of r1's five verified closed. The new ones: a
  partition invariant that was false and classified `note` two
  contradictory ways; an unspecified home for the action set that would
  have made a mutation not bite; **a guard test that passes on the broken
  build**; `success_*` row-scoped, which strands `j`/`u`/`v` after a mouse
  confirm; and a silent dead key for `n`.
- **Recurring failure mode, recorded because it keeps recurring.** r1
  stated four inferences as measurements. r2 stated an invariant it had
  not enumerated and a discriminator it had not measured. Both rounds,
  the gate's decisive findings came from *running something* — a DOM
  probe, `history.back()`, an arm-confirm cycle — against claims derived
  by reading. The rule this project already has: when a claim is
  decision-relevant and locally testable, test it before it grounds a
  decision.
- **r3** — this document. All 22 keymap actions classified; `success_*`
  and `tolerate`/`confirm_recurrence` moved to document scope; `note`
  resolved as row-scoped in both places; the classification's home
  decided; test 4 given a discriminator; `focusNote`'s miss given a
  voice.

## 5. Out of scope

- **W4-F2** `Enter` on a focused button navigates instead of pressing it.
- **W4-F3** `Escape` at the front page goes down, not up. r1 would have
  *spread* this; r3 must not.
- **W3-F1** the commit-drift evidence hole (`routes.py:1781-1790`) — the
  next P0.
- **W4-F4** the dead-key set `h`/`r`/`v` and the unconditional overlay.
- **The missing ring on `.holding-row`, `.followup-row`, `.cluster-row`,
  `.bulk-collapse-row`, `.near-miss-row`.** Real, unreported by any walk,
  and decoupled from targeting by §2.3. Its own item.
- **N10, a pre-existing trap in test 7's path:** the armed bar renders
  `<kbd>n</kbd> to say why` (`action_bar.html:96-98`) while `n` in the
  armed state **disarms** (`app.js:211-213`). This is walk 4's W4-F5.
