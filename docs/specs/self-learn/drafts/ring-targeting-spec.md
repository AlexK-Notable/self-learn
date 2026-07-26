# Spec — the selection ring must govern the verb keys

Status: **DRAFT, ungated.**
Motivating finding: `ui-walks.md` **W4-F1** (walk 4, 2026-07-26).

---

## 1. The defect

On a bucket page listing N records, every verb key acts on **record 1**,
whatever the selection ring shows.

`static/app.js:54-61`:

```js
function clickAction(action) {
  const el = document.querySelector('[data-key-action="' + action + '"]');
  if (el) { el.click(); return true; }
  return false;
}
```

`document.querySelector` returns the first match in document order. The
ring is an unrelated mechanism: `.selected`, moved by `moveSelection`
(`app.js:84-92`) and read only by `drillIntoSelection` (`app.js:94-100`)
to follow a row's link on Enter. Nothing connects the two.

So `e`/`x`/`f`/`g`/`o`/`n` ignore the ring.

**Why this is P0 and the other walk findings are not.** Every other
finding in five walks costs the user comprehension. This one costs
correctness: with the ring on record 5, pressing `x` denies record 1.
Deny and Graduate are destructive and the ring is the only "you are
here" the page draws. Walk 4:

> "With Approve/Deny/Graduate on the line, I stopped trusting the ring —
> but there is nothing else to trust instead."

**Reproduced, not inferred.** Walk 4 hit it twice: ring on card 2 with
DOM focus on card 1, and ring on card 2 with focus on `BODY`. Both armed
card 1, which rules out focus as the mechanism and leaves document order.

---

## 2. What it must do instead

**The ring is authoritative for record-scoped verbs.** Resolution order,
first match wins:

| # | When | Search scope |
|---|---|---|
| 1 | an armed action bar exists | **that bar's subtree** |
| 2 | else, a `[data-row].selected` exists inside `#self-learn-ui-content` | **that row's subtree, with NO fallback** |
| 3 | else | the document, unchanged |

### 2.1 Rule 1 is not optional — it prevents a regression

`app.js:206-215` dispatches `confirm`/`disarm` through the same
`clickAction`, and returns before the keymap switch, so the armed branch
never reaches `dispatchOrHint`.

A **mouse** user can arm any row: `ensureRowSelected` (`app.js:114-119`)
puts the ring on row 0 on every load, so clicking row 5's Approve leaves
the ring on row 0 and the armed bar in row 5. If `confirm` scoped to the
ringed row it would find nothing and **Enter would stop confirming
armed actions for mouse users** — trading a keyboard defect for a worse
mouse one. The armed bar is the active decision context; while one
exists it wins.

### 2.2 Rule 2 has no fallback, deliberately

If a selected row exists but does not contain the action, the correct
outcome is **nothing happens to any record** — not "act on some other
row that does have it". Falling back to the document here would
reinstate the exact defect for every row whose action set differs from
row 1's (deferred rows render differently; `bucket.html:76` carries a
`record-row-deferred` variant).

The no-op is not silent: `dispatchOrHint` (`app.js:270-281`) already
renders a plain-words hint when `clickAction` returns false, via
`[data-noop-hint]` or `NOOP_MESSAGES`. A row-scoped miss returns false
and joins that existing path. **No new mechanism.**

### 2.3 What must not change

- **Front page.** `<tr data-row>` bucket rows (`index.html:62`) contain
  no `[data-key-action]` verb buttons, so rule 2 finds nothing and
  returns false. Front-page behaviour must be **byte-identical**, and
  `up`/`interrupt` must keep reaching their global targets — they are
  dispatched when no row contains them, i.e. through rule 3.
- **Record detail pages.** One record, no `[data-row]`, so rule 3
  applies and behaviour is unchanged.
- The keymap, the arm/confirm spine, and the no-op hint mechanism are
  untouched. This spec changes **one function's search scope** and
  nothing else.

---

## 3. Acceptance

A green suite already covers this file and did not see the defect, so
the tests below are the deliverable, not the fix.

1. **Bucket page, ring on row 2, press a verb** → row 2's bar arms; row
   1's bar does **not**. This is the finding, stated as a test.
2. **Ring on a row lacking the action** → no bar arms anywhere, and the
   existing no-op hint renders.
3. **Armed bar in row 5, ring on row 0, press Enter** → row 5's confirm
   fires. (§2.1 — the mouse regression.)
4. **Front page** → selection, `up`, and drill-in unchanged.
5. **Record detail page** → every verb key behaves exactly as before.

### 3.1 Mutation plan

Each must turn a green test red:

| Mutation | Test that must fail |
|---|---|
| revert `clickAction` to the document-wide query | 1 |
| add a document fallback after a row-scoped miss | 2 |
| drop rule 1, so `confirm` scopes to the ringed row | 3 |
| scope rule 2 to the document root instead of the row | 1 |

**Positive control required.** Test 1 must fail if *no* bar arms at all —
otherwise "row 1 did not arm" passes vacuously on a page that armed
nothing. Assert row 2 armed **and** row 1 not armed, in that order. This
is `lrn-ea833a5b`, which has now cost this surface four times; the
footer keymap test shipped with exactly this hole and a fifth key proved
it.

---

## 4. Out of scope

Named so the gate does not ask for them:

- **W4-F2** `Enter` on a focused button navigates instead of pressing it
  (`Space` is the only activation, and neither key is documented). A
  keyboard-contract unit of its own.
- **W4-F3** `Escape` at the front page goes down, not up.
- **W3-F1** the commit-drift evidence hole (`routes.py:1781-1790`) — the
  next P0, specced separately.
- **W4-F4** the dead-key set `h`/`r`/`v` and the unconditional help
  overlay.
- Whether the ring should also be visible on the record detail page.
