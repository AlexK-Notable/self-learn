# Spec — the guided commit-and-retry must say what it did

Status: **DRAFT, ungated.**
Motivating finding: `ui-walks.md` **W3-F1** (walks 3 and 5, 2026-07-26).

**Read `resolution-evidence-spec.md` §10 before touching this surface** —
seven things its code gate caught, every one invisible to a green suite.
This unit is that spec's fifth redirect site.

---

## 1. The defect

Route refuses on a dirty target and offers **"Commit that repo's changes,
then retry"**. The user confirms twice — a file write and a git commit —
and the app swaps in an unrelated record with no receipt and no message.

Two source-blind walkers found this independently. Walk 5 then ran the
control walk 3 did not: approve from a bucket list (receipt ✔), approve
from a record detail page on a *clean* repo (receipt ✔), and corrected
itself — the failure is the recovery path, not the page.

> "The longest, most anxious path through the app is the only one that
> ends in silence." — walk 3

`commit_drift_confirm` (`routes.py:1704-1790`) mirrors `action_confirm`
step for step — interrupt-first, contradicts capture (`:1771`), adopt
offer (`:1777`) — then stops one step short and falls through to the
pre-existing `HX-Redirect` (`:1781-1790`). It never calls
`_evidence_ctx`.

**`resolution-evidence-spec.md` §3.4 enumerated four redirect sites; this
is a fifth**, and that spec had already written the warning that convicts
it: *"Fixing only the third leaves the proposal-confirm path silently
teleporting the user while the DoD passes."*

**What kept it short is still in the file.** `routes.py:1783-1787`
justifies the redirect because "the redirect target's re-read state IS
the ground truth, **same as every other successful confirm**." True when
written. The resolution-evidence unit changed what every other successful
confirm does, and the comment went on justifying the old behaviour. Delete
it with the code it defends — a fossil rationale reads exactly like a
live one.

---

## 2. The change

`commit_drift_confirm`'s **success leg only** mirrors `action_confirm`'s
`:1354-1384` evidence block, and renders the evidence leg instead of
redirecting.

Three things make this narrower than it sounds:

- **The verb is always `route`.** `route_argv` is built with `"route"`
  (`:1743-1753`), and `route` ∈ `_EVIDENCE_VERBS` (`routes.py:1058`), so
  the `if verb in _EVIDENCE_VERBS` guard is statically true here. Keep
  the guard anyway, for symmetry with `action_confirm` and so a future
  verb change cannot silently produce `evidence=None`.
- **`next_url` is built from the raw id, not `next_record_url`.**
  `action_confirm`'s comment (`:1361-1366`) pins why: `next_record_url`
  always returns *some* string — a bucket-clear front-page URL when
  nothing remains — so the evidence leg's "next pending record" link must
  be **absent** rather than point at that URL under a misleading label.
  The current success leg uses `next_record_url` (`:1782`) precisely
  because it was feeding a redirect, which has no such constraint.
  **Switching to the raw-id form is part of the fix, not incidental.**
- **The offers compose.** `_contradicts_offer_response` and
  `_adopt_offer_response` already take `evidence=`; this path passes
  nothing (`:1772`, `:1779`). Per the resolution-evidence §3.4 ruling —
  "an offer *composes with* the evidence, since suppressing it hides the
  thing the offer is about" — both must receive it.

### 2.1 What must not change

- **The two failure legs.** Commit failure (`:1729-1733`) and retry
  failure (`:1758-1763`) render plainly and must stay byte-identical. A
  second dirty refusal must not re-offer the commit-drift button — the
  docstring pins this: "no loop, and the commit-drift button never
  re-appears on that leg".
- `action_confirm` itself, and the other four redirect sites.

---

## 3. Acceptance

1. **The W3-F1 reproduction.** Dirty target → route refuses → arm
   commit-drift → confirm → **the evidence leg renders, naming this
   record**, with the canon path and both commit lines. No redirect.
2. **Contradicts composes** — a contradicts offer on this path renders
   the offer *and* the evidence.
3. **Adopt composes** — likewise.
4. **A cleared bucket omits the "next pending record" link** rather than
   linking the front page under that label.
5. **Commit-failure leg** unchanged.
6. **Retry-failure leg** unchanged, and still does not re-offer the
   commit-drift button.

### 3.1 Mutation plan

| Mutation | Test that must fail |
|---|---|
| delete the evidence build, restore the `HX-Redirect` | 1 |
| pass `evidence=None` to the contradicts response | 2 |
| pass `evidence=None` to the adopt response | 3 |
| build `next_url` with `next_record_url` instead of the raw id | 4 |
| add evidence to the retry-failure leg | 6 |

**Positive control on test 1.** Assert the evidence names **this
record's id**, not merely that an evidence leg rendered. "Some evidence
appeared" passes on a build that renders the wrong record's receipt —
which is the defect one layer over, since the bug being fixed is landing
the user on a different record.

**Run-evidence control.** If any test lands in the js/browser module,
report the collected/passed count — `test_js_dom.py:83-88` is an
`importorskip` and a skipped module is not a red test.

---

## 4. Out of scope

- W4-F1 ring targeting — its own spec, `ring-targeting-spec.md`.
- The no-op hint surface split out of that spec.
- The other `ui-walks.md` findings.
