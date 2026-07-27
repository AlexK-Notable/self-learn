# Spec — the selection ring must govern the verb keys

Status: **revision 7** — SPLIT. Targeting only; the no-op hint surface
moved to `noop-hint-surface-spec.md`.
Motivating finding: `ui-walks.md` **W4-F1** (walk 4, 2026-07-26).

**§3 is the normative register.** Acceptance criteria and the mutation
plan are the spec; §1–§2 are rationale. Where they conflict, §3 wins by
standing rule — a builder is never left to pick. Every set is defined
**once** and referenced by name; this document contains no second
enumeration of any set, no counts, and no re-listed subsets. Six rounds
of gate findings were one drifted enumeration after another.

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
(`app.js:94-100`). The gate looked for any other scoping mechanism — CSS,
server markup, event delegate, htmx — and found none.

**Why this is P0.** Every other walk finding costs comprehension. This one
costs correctness: with the ring on record 5, `x` denies a different
record.

> "With Approve/Deny/Graduate on the line, I stopped trusting the ring —
> but there is nothing else to trust instead." — walk 4

Reproduced twice, once with DOM focus on card 1 and once with focus on
`BODY`, ruling out focus and leaving document order.

---

## 2. What it must do instead

Resolution order, first match wins:

| # | When | Search scope |
|---|---|---|
| 1 | an armed action bar exists | that bar's subtree |
| 2 | the action is **row-scoped** AND the selected row is a `.record-row` | that row's subtree, **no fallback** |
| 3 | otherwise | the document, unchanged |

`focusNote` (`app.js:69-74`) takes the same order. Rule 1 is inert for it
— `case "note"` is reachable only in the not-armed branch — so no rule-1
test for `n` is possible.

### 2.1 Rule 1 prevents a mouse regression

`app.js:206-215` dispatches `confirm`/`disarm` through `clickAction` and
returns before the keymap switch. `ensureRowSelected` puts the ring on
row 0 on every load, so a mouse user clicking row 5's Approve leaves the
ring on row 0 and the armed bar in row 5. Scoping `confirm` to the ringed
row would **stop Enter confirming for mouse users**.

It also closes a latent hazard: `action_bar.html:10` sets
`data-armed="true"` for the commit-drift sub-state too, so with row 3
commit-drift-armed and row 5 armed, today's document-wide
`clickAction("confirm")` fires row 5's confirm.

### 2.2 `row_scoped` is a required field on `KeymapEntry`

**The classification lives on the keymap entry**, not in a list beside
it. `KeymapEntry` is a frozen dataclass and `keymap_as_dicts()` spreads
`asdict(entry)` (`keymap.py:136-140`), so the field flows into the JSON
blob `loadKeymap` already parses (`app.js:28-39`), which reads only
`.keys`/`.action` and tolerates extra keys.

**Required, with no default.** A defaulted field silently classifies
every future entry; a required one makes "adding a keymap action without
classifying it" a **construction-time** failure, which is stronger than
any test. This replaces the three-bucket prose classification earlier
revisions carried: two of those buckets were treated identically by all
three rules, and maintaining three lists in sync is where four of the
fifteen blockers bred.

**Membership needs both halves:**

1. the target can render inside a `.record-row`, **and**
2. the action **acts on, or edits, that record's own state** — not
   merely an element located in its subtree. Equivalently: the ring
   tracks it.

Half 1 alone admits `success_next`/`success_bucket`/`success_view`, which
render inside a `.record-row` via `evidence.html` (included at
`action_bar.html:11-13`, measured at row index 2). Half 2 excludes them,
and must: the gate measured that **the ring never moves across arm or
across confirm**, so row-scoping them would strand a visible "Next
pending record (j)" link that does nothing, and `[data-verb-success]`
holds the reload (`app.js:478`) so the state persists. They are
navigation; "next pending record" has no per-row meaning.

Half 1 also excludes `tolerate`/`confirm_recurrence` (targets render only
on `.holding-row`, `index.html:80-85`; `bucket.html:90` hardcodes
`kind="detail"` for every `.record-row`) and `toggle_brief`
(`detail.html:68` only).

### 2.3 Rule 2 applies only to `.record-row`

> Rule 2 applies exactly where the ring is both **visible** and
> **verb-bearing**.

Verified in both directions. `tr[data-row]` is ringed
(`style.css:764-765`) but bears no row-scoped action. `.holding-row`,
`.bulk-collapse-row`, `.followup-row` bear actions but are **not** ringed
— a selected `.holding-row` measured `outline: none`. `.near-miss-row` is
neither. `.cluster-row` bears `route` (`cluster_expanded.html:15`) but is
not ringed, so it stays on rule 3. **`.record-row` is the unique
intersection**, rendered at one site (`bucket.html:76`), always with
`data-row`.

An earlier revision keyed rule 2 on *any* selected row, which would have
made three front-page keys dead, turned three green tests red, and made
an invisible selection authoritative for `.bulk-collapse-row`'s **bulk**
graduate over `group.bulk_collapse.ids`.

Incidental gain: with a cluster expanded and the ring on a `.record-row`,
rule 2 finds that record's own `route`, so the cluster's `route` no
longer shadows every record row.

### 2.4 A row-scoped miss is SILENT — ruled, not defaulted

If the selected `.record-row` does not contain the action, **nothing
happens and nothing is said**. No fallback: falling back to the document
would reinstate the defect for rows whose action set differs — measured,
that is the success/evidence leg, which suppresses the quad
(`action_bar.html:166`).

**This is a deliberate, user-ratified cost, not an oversight.** Making
the miss *speak* is a second feature: it consumed four consecutive gate
rounds in this document (a hint mechanism that could not express cause; a
ruling that changed detail pages; wording that lied on the `defer` leg; a
trigger that fired where no record existed) without the targeting fix
moving an inch. It is split out to `noop-hint-surface-spec.md` with its
own gate.

The cost is real and is tracked there: a bucket-A miss is a keypress that
does nothing and says nothing, which is the shape W4-F4 objects to. **The
existing hint mechanism is untouched** — `NOOP_MESSAGES["toggle_brief"]`
and the singleton-cycle site (`action_bar.html:196-202`) keep working
exactly as today, including the gate-M1 replaced-bar silence pin.

---

## 3. Acceptance — the normative register

1. **Bucket page, ≥2 record rows, ring on the second, press a row-scoped
   verb** → that row arms; the first does **not**.
2. **Ring on a resolved (evidence-leg) row, press a row-scoped verb** →
   no bar arms anywhere, and **no hint renders** (§2.4).
3. **Armed bar in a later row, ring on row 0, press Enter** → the armed
   row's confirm fires.
4. **Escape on a bucket page, ring on a record row** → reaches the header
   `up` target. **Discriminator required — see §3.1.**
5. **Escape on a bucket page with a streaming pane** → interrupts.
6. **Front page: the keys whose targets live on non-`.record-row` rows**
   → behave exactly as today. `test_js_dom.py:2171` and `:2183` must stay
   green **unmodified**.
7. **`n` with the ring on the second row** → focuses that row's note
   field, and a note typed there rides that row's verb.
8. **`n` on a row with no note input** → silent (§2.4).
9. **`KeymapEntry` cannot be constructed without `row_scoped`** (§2.2).
10. **Record detail page** → every key behaves exactly as today. No
    exception: this revision adds no hint surface.

### 3.1 Mutation plan

| Mutation | Test that must fail |
|---|---|
| revert `clickAction` to the document-wide query | 1 |
| add a document fallback after a row-scoped miss | 2 |
| drop rule 1, so `confirm` scopes to the ringed row | 3 |
| set `row_scoped=True` on `up` | 4, 5 |
| widen rule 2 from `.record-row` to any `[data-row]` | 6 |
| leave `focusNote` document-wide | 7 |
| give `row_scoped` a default | 9 |

**Test 4's discriminator — measured twice, wrong twice before this.**
From a bucket page, `history.back()` lands on **exactly the URL the
header `up` link navigates to**, so asserting "reaches the front page"
passes on the broken build. An injected rival anchor does not fix it
either: the real `up` target is in `<header>`, first in document order,
so `document.querySelector` never picks the injection
(`picks_injected: false`).

Assert **`history.length` increased** — measured `3 → 4` on the correct
build versus `5 → 5` on the broken one (link navigation pushes;
`back()` moves the pointer). If a hash discriminator is also wanted,
**mutate the real target in place**
(`setAttribute('href', '#went-up')`), which yields `hash "#went-up"` with
`still_on_bucket: true`. **Do not also assert the URL became the front
page** — with the href mutated the correct build stays put.

**Positive control on test 1.** Assert the second row armed **then** the
first row not armed, in that order — "row 1 did not arm" passes
vacuously on a page that armed nothing.

**Run-evidence control.** `test_js_dom.py:87` is an `importorskip` and
the `browser` fixture can skip, so **a skipped module is not a red test
and every mutation would leave the suite green.** Report the
collected/passed count for `-m js`, not an exit status. Measured
baseline: **71 passed**.

**Fixture.** One module-scoped ledger + server fixture in
`test_js_dom.py` serves tests 1, 2 and 7, seeding a bucket with **≥2
pending `.record-row`s and no bulk-collapse group** (no `already_canon`
proposals). Both exclusions are measured: `f2_server`'s `[data-row]`
index 0 is a `.bulk-collapse-row`, and a single-record bucket puts the
ring on the resolved row itself — either neutralises a mutation.

### 3.2 The suite could not have caught this

**No test presses a record verb key on a bucket page.**
`TestNeverPressedKeymapActions` (`test_js_dom.py:2124-2199`) drives its
keys on `/record/<id>` — measured to have **zero** `[data-row]`, the one
page shape where this defect cannot occur. The only bucket-page keyboard
test is a page-level action.

---

## 4. What six spec-gate rounds cost and taught

Fifteen blockers, all measured, none argued down: 5, 5, 2, 1, 1, 1. The
core — rules 1/2/3, the `.record-row` boundary, the membership rule,
test 4's discriminator, the fixture pins — has produced **zero** findings
for the last two rounds and is what ships here. Everything from round 4
onward lived in the hint surface, now split out.

Three lessons, in descending order of how much they cost:

- **A guard test is itself a claim.** Twice, the test written to catch a
  regression was the broken thing — once passing on the broken build,
  once inverted so it also failed on the correct one. Run a guard against
  its own mutation before trusting it.
- **A duplicated enumeration drifts.** Every blocker shared one shape: a
  ruling contradicting a criterion stated elsewhere. Adding a "diff
  before submitting" step did not help — the revision that added the
  warning committed another instance. Defining each set once, and giving
  §3 standing precedence, is the structural fix; this revision applies
  both.
- **Claims derived by reading are hypotheses.** Every decisive finding
  came from running something — enumerating `KEYMAP`, driving
  `history.back()`, reading document order, walking an arm-confirm cycle.
  Every defect came from reasoning confidently instead.

## 5. Out of scope

- **The no-op hint surface** — `noop-hint-surface-spec.md`.
- **W4-F2** `Enter` on a focused button navigates instead of pressing it;
  `Space` is the only activation and neither key is documented.
- **W4-F3** `Escape` at the front page goes down, not up. Note an earlier
  revision would have *spread* this; this one must not.
- **W4-F4** the dead-key set `h`/`r`/`v`. `r` and `v` need re-validating
  against the fixed probe (v4) before being specced — `r`'s "inert"
  finding sits inside the instrument's blindness class.
- **The missing ring on `.holding-row`, `.followup-row`, `.cluster-row`,
  `.bulk-collapse-row`, `.near-miss-row`** — real, unreported by any
  walk, decoupled from targeting by §2.3.
- **N28, adjacent and pre-existing:** `focusNote`'s selector
  `.action-bar input[name="note"]` also matches the un-armed commit-drift
  branch's hidden note input (`action_bar.html:65`), which precedes the
  visible one, so `n` focuses a hidden input and returns truthy. Leave
  it; a builder editing that line will see it.
