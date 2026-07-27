# Spec — the selection ring must govern the verb keys

Status: **revision 5** — folds spec-gate rounds 1–4 (B1–B13, N7–N21).
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

**Bucket A — row-scoped (6).** Target resolved inside the selected
`.record-row`; no fallback.

```
route · reject · defer · graduate · cycle_destination · note
```

**Bucket B — document-scoped (12).** Target resolved document-wide,
behaviour byte-identical to today.

```
up · iterate · bucket_pane · arm_proposal · retry · close_pane
tolerate · confirm_recurrence · toggle_brief
success_next · success_bucket · success_view
```

**Bucket C — no DOM target lookup (4).**

```
move_down · move_up · drill_in · help
```

The criterion for C is **never performs a `[data-key-action]` lookup** —
not "has an explicit `switch` case" (N16), since `up` and `note` have
cases at the same site and both do reach a lookup. Verified: `rows()` and
`drillIntoSelection` query `[data-row]`/`a[href]`, `toggleHelp` uses
`getElementById`; none resolves a key target.

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

**`tolerate`/`confirm_recurrence`/`toggle_brief` are in bucket B — the
inert-target rule (N8, N12).** A verb whose target can never render on a
`.record-row` gains nothing from rule 2 and would only convert a silent
miss into a hint whose wording cannot be honest. `tolerate` and
`confirm_recurrence` render only on `.holding-row`
(`index.html:80-85`); `toggle_brief` renders only at `detail.html:68`,
and a detail page has no `[data-row]` so rule 3 covers it anyway.

r3 applied this rule to the first two and not the third, which was
inconsistent rather than harmful. Stated once, as a rule, so the next
action added is classified by it. **Bucket A membership needs BOTH
halves:**

1. the target can render inside a `.record-row`, **and**
2. the action is a **verb acting on that record** — not merely an
   element located in its subtree. Equivalently: the ring tracks it.

**Half 2 is not decoration, and r4 omitted it (N17).** r4 asserted the
first half alone selected "exactly the six in A" and labelled that
*measured*. It is not: `success_next`/`success_bucket`/`success_view`
also render inside a `.record-row`, via `evidence.html` included at
`action_bar.html:11-13` — the gate measured them at row index 2 on a
bucket page. Half 1 alone selects **nine**, and would have classified
the next navigation-shaped-but-row-located action into A, reintroducing
**B9** three sections after B9 was resolved.

Half 2 is what B9 actually established: `j`/`u`/`v` are navigation, the
ring does not track them, and "next pending record" has no per-row
meaning. With both halves the rule selects exactly the six — all of which
live in the single `<form id="form-{{ dom_id }}">` at
`action_bar.html:167-227`.

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

**The miss must be audible**, or this ships a fifth
advertised-key-bound-to-nothing (W4-F4), the class `keymap.py:118-128`
exists to refuse.

**It is rendered server-side, and NO `NOOP_MESSAGES` entries are added —
B12.** r3 said the opposite and was wrong three ways, all measured:

1. It **reverses a ratified pin.** `app.js:259-264` records it verbatim:
   a proposal-replaced bar "hits leg 2 with no `NOOP_MESSAGES` entry for
   `cycle_destination` — **deliberately silent, no scope message (it
   would be wrong there, gate M1's replaced-bar pin)**."
2. It **turns a green test red.**
   `test_o_on_proposal_replaced_bar_shows_no_hint`
   (`test_js_dom.py:1528-1537`) presses `o` on that bar and asserts
   `[data-noop-hint-active]` is `None`. r3 never mentioned it, while §3
   test 6 demands existing tests stay green unmodified.
3. It **cannot produce the wording r3 itself demanded.**
   `NOOP_MESSAGES` is keyed by **action alone** (`app.js:266-268`), but
   one bucket-A verb misses for at least three distinct causes: the
   ringed row is an evidence leg; a proposal bar has replaced the action
   bar; the verb does not apply to this row type. One static string per
   action cannot name any of them correctly in all three.

So: render `data-noop-hint` / `data-noop-action` on the **evidence leg**
(`evidence.html`) for the **five bucket-A `clickAction` verbs** —
`route`, `reject`, `defer`, `graduate`, `cycle_destination` (N19; `note`
is bucket A but never reaches `dispatchOrHint`, and is handled by §2.5
instead — do not look for a `data-noop-action="note"` element). The
server knows *why* the quad is absent, so wording is cause-accurate by
construction. This is the growth path `app.js:263-264` already names —
"the next gated key joins by adding a message here **or a data-noop-hint
attribute server-side** — never a new mechanism." The M1 pin survives,
`:1535` stays green unmodified, and no new mechanism is invented.

**Markup shape and wording, decided.** The existing site puts the pair on
a visible button; the evidence leg has no analogous control, so these are
**attribute-only carriers** — one per action, emitted by a loop over the
five, e.g.
`<span hidden data-noop-hint="…" data-noop-action="route"></span>`.
**One shared string, not five**: the cause is uniform across all three
include paths — under `evidence` the record is resolved, and the
`contradicts`/`adopt` branches thread `evidence=` through, so the record
is resolved there too and an *additional* decision is merely offered. A
single "already resolved" wording is accurate in every path.

**The existing `NOOP_MESSAGES["toggle_brief"]` entry stays (N20).** "No
entries are added" is not a licence to remove one. `toggle_brief` changed
buckets in r4, which is not a reason to drop its message —
`test_b_on_briefless_record_shows_brief_hint` (`test_js_dom.py:1539`)
asserts that exact string.

**A second miss state exists and is already served.** §2.4 named only the
evidence leg; the **singleton destination cycle** is the other state
where a bucket-A verb misses on a ringed `.record-row` that is not
resolved. It needs no new work — `action_bar.html:196-202` already puts
the hint pair on that row's own button, and the row-scoped lookup makes
it *more* correct (today's document-wide query can return a different
row's hint). Recorded so the builder does not treat it as unhandled.

**The hint lookup must be row-scoped too (N14).** `dispatchOrHint`
resolves `[data-noop-hint][data-noop-action=…]` against the whole
document (`app.js:272-274`). That is invisible today — one render site,
one static string — but this ruling puts a hint inside every resolved
row, so an unscoped lookup would source a hint from a row other than the
ringed one, recreating the defect in the explanation of the defect. It
takes the same rules 1/2/3 as `clickAction`.

`focusNote`'s hint (§2.5, test 8) is unaffected by all of this —
`showNoopHint` takes a literal string, and its cause is the same one:
the ringed row is resolved, so there is no note field to focus. Use
wording that says that, not a generic failure.

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

**The field is REQUIRED — no default (N15).** `KeymapEntry` is a frozen
dataclass and `keymap_as_dicts()` spreads `asdict(entry)`
(`keymap.py:136-140`), so a new field flows into the blob automatically
and `loadKeymap` tolerates it (it reads only `.keys`/`.action`). All four
blob consumers stay green — `test_js_dom.py:1341`, `test_keymap.py:43`,
`:44-46`, `test_routes.py:2309-2320`. **But a field added *with* a
default — the natural move when retrofitting 22 rows — silently
classifies every future entry and makes §2.2's invariant trivially
true.** The whole point is that adding an action without classifying it
fails the build. Required, or the test is theatre.

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
11. **Record detail page** → every verb key behaves exactly as before,
    **with one deliberate exception**: on a *resolved* (evidence-leg)
    record, the five suppressed bucket-A verbs now render the new hint
    instead of falling silent. — B13, measured both sides: a detail page
    has zero `[data-row]`, so the hint lookup takes rule 3 and finds the
    attributes §2.4 adds; today `e`/`x`/`f`/`g`/`o` there are silent with
    `noop_hint_elements: 0`.

    This is the good direction — silence becoming an honest explanation
    is what §2.4 exists to produce — so the ruling stands and the test
    narrows. Gating the attributes to bucket pages to preserve the letter
    of "exactly as before" would be worse.

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

**Test 4's discriminator — B8, then B11. Both measured, and r3's
replacement was worse than the defect it replaced.**

The original hazard: from a bucket page, `history.back()` lands on
**exactly the URL the header `up` link navigates to** (`/`), because
`goUp()` falls through to `window.history.back()` (`app.js:166`). So
asserting "reaches the front page" passes on the broken build.

r3's two-part replacement **fails in both parts**:

- **Injection cannot fire.** The cited technique
  (`test_js_dom.py:1372-1394`) works because a `/record/` page has no
  real `interrupt` target. A bucket page always has a real `up` target
  and it is in `<header>` — before anything appended at body end.
  Measured: `all_hrefs: ['/', '#went-up']`, `picks_injected: False`.
  `clickAction` takes the first in document order, so the injected
  anchor can never receive the click, and the hash never changes **on a
  correct build**.
- **The `history.length` assertion is inverted.** Measured A/B:
  correct build (click the header link) `3 → 4`; broken build
  (`history.back()`) `5 → 5`. Link navigation **pushes**; `back()` moves
  the pointer. r3 said "assert unchanged" — which **passes on the broken
  build and fails on the correct one.**

**The ruling.** Assert `history.length` **increased**. If a hash
discriminator is also wanted, **mutate the existing target in place**
rather than injecting a rival:

```js
document.querySelector('[data-key-action="up"]').setAttribute('href', '#went-up')
```

A click then yields a hash change with no navigation; `history.back()`
yields neither. Either half discriminates once corrected; r3's stated
combination discriminated in neither.

**Verified by the gate on the corrected form**, in-place mutation on
`/bucket/skill/t`: `history 3 → 4`, `hash "#went-up"`,
`still_on_bucket: true`. Against the broken build's `5 → 5`, navigates to
`/`, no hash — both discriminators now fire in the direction written.

**Do not also assert the URL became `/`.** With the href mutated, the
correct build **stays on the bucket page**. That assertion holds for the
un-mutated correct build and fails for the mutated one, which would make
the test red on good code for the third round running.

**Three rounds, one test.** `lrn-ea833a5b` has now bitten this unit
three times, twice in a test written specifically to catch a regression,
in a document that cites the lesson by name. The generalisation earned
here is narrower and more useful than the original: **a guard test needs
its own A/B — run it against the mutation before trusting it, because a
discriminator derived by reading is a hypothesis, not a control.**

**Positive control on test 1.** Assert row 2 armed **then** row 1 not
armed, in that order — "row 1 did not arm" passes vacuously on a page
that armed nothing.

**Run-evidence control.** `test_js_dom.py:83-88` is an `importorskip`
and the `browser` fixture can `pytest.skip`, so **a skipped module is not
a red test and every mutation would leave the suite green.** Report the
collected/passed count for `-m js`, not an exit status. Measured
baseline, both gate rounds: **71 passed**.

**Fixture pinning, two mutations not one.**

- *Mutation 2* only bites if the action exists elsewhere on the page: pin
  ≥2 rows where row A has the action and the ringed row B does not.
- *Mutation "move `success_*` into bucket A"* (test 10) only bites if the
  default ring lands on a `.record-row`. **Measured, `f2_server` fails
  this**: `/bucket/skill/s` has `[data-row]` index **0 =
  `.bulk-collapse-row`** (the three `.record-row`s are 1–3), so rule 2
  never engages and the mutation leaves test 10 **green**. Test 10's
  premise is "the ring never moved", so it cannot repair this by
  pressing `s`. **Test 10 needs a bucket with no bulk-collapse group.**

**Test 10 asserts over what rendered, not a fixed triple** — **every
success link present in the DOM is reachable by its key**. Same shape as
the footer fix.

**Why a fixed triple would have been wrong (N21, now resolved).**
`evidence.html`'s own comment settles it: `route`/`reject`/`graduate` all
move the record out of `pending`/`deferred` *before* this leg renders, so
`/record/{id}` 303-redirects and `_evidence_ctx` sets `record_url` **only
for `defer`**. So `success_view` renders on a `defer` success leg and
nowhere else — the gate measured a route confirm producing
`success_links: ["success_bucket"]`, one link, not three. Asserting a
triple would have been red on four of five verbs.

**One fixture serves tests 1, 2, 7 and 10.** It needs **≥2
`.record-row`s and no bulk-collapse group** — the second condition
because a bulk row takes `[data-row]` index 0, the ring lands there, rule
2 never engages, and test 10's mutation goes green. A single-record
bucket also fails test 10: the ring would sit on the resolved row itself,
which *does* hold the `success_*` links, so the mutation would not bite
there either. Test 10 mouse-arms a row **other than** the ringed one,
which is the state B9 was measured in.

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
- **r3** — **NOT SOUND**, 2 blockers, both in r2's repairs. Eight of ten
  prior blockers verified closed. The new ones: a test-4 discriminator
  that failed in **both** halves — an injected anchor that document order
  guarantees can never be clicked, and a `history.length` assertion
  inverted so it passed on the broken build and failed on the correct one
  — and a `NOOP_MESSAGES` ruling that reversed a pin recorded verbatim in
  the code, turned a green test red, and could not express the wording it
  itself demanded.
- **r4** — hints moved server-side to the evidence leg with no
  `NOOP_MESSAGES` entries added and the hint lookup row-scoped; test 4
  asserted `history.length` **increased** and mutated the real target in
  place; `toggle_brief` joined bucket B; the `KeymapEntry` field made
  required; test 10 given a fixture pin and an assert-over-what-rendered
  form. **NOT SOUND**, 1 blocker. B11 and B12 verified closed by
  measurement, all four N-items landed. The blocker: §2.4's server-side
  hints also render on **record detail pages**, because `evidence.html`
  is reached from three sites, two of which render standalone — so five
  keys changed behaviour there while test 11 promised "exactly as
  before".
- **The class this document produces, named by the gate in round 4.**
  Every round's blocker has been the same shape: **a §2 ruling
  contradicting another §2 or §3 criterion, with the builder left to
  pick.** r1 §2.3 vs §2.2 · r2 `note` in §2.2 vs §2.5 · r3 test 4's two
  halves · r4 §2.4 vs test 11. Four instances is not four slips, it is a
  property of how this spec was written: each round repaired a section
  in place without re-reading the criteria that section is checked
  against. Any future revision should diff its new ruling against §3
  before submitting.
- **r5** — this document. Test 11 narrowed; the inert-target rule given
  its missing second half (N17 — r4's "measured, exactly the six" was
  inferred and selects nine); hint markup, wording, and the `note`
  carve-out decided; test 4 told not to assert the URL; one fixture
  specified for tests 1/2/7/10; `success_view`'s render condition
  resolved.
- **What five rounds actually taught, beyond the thirteen blockers.** Every
  decisive finding came from *running something* — enumerating `KEYMAP`,
  driving `history.back()`, injecting an anchor and reading document
  order, walking an arm-confirm cycle. Every defect came from *reading*
  and reasoning confidently. The specific lesson worth carrying: **a
  guard test is itself a claim, and needs its own A/B against the
  mutation before it can be trusted to guard anything.** Two rounds
  running, the test written to catch the regression was the thing that
  was broken.

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
