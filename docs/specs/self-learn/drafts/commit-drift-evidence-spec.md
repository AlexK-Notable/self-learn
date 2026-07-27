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
step for step — interrupt-first (`:1741-1742`), contradicts capture
(`:1739`) and offer (`:1771-1772`), adopt offer (`:1777-1779`) — then
stops one step short and falls through to the pre-existing `HX-Redirect`
(`:1781-1790`). It never calls `_evidence_ctx`.

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
- **`_evidence_ctx` is fed by `retry` (`:1755`), not `commit_result`
  (`:1728`).** Two `RunResult`s exist in this handler; the evidence
  describes the route, not the guided commit.

### 2.1 The retry argv must carry `--json` — the clause r1 dropped

`route_argv` (`:1743-1753`) is built with **no `as_json=`**.
`action_confirm` builds its argv at `:1276-1287` with
`as_json=verb in _EVIDENCE_VERBS` (`:1286`) — *outside* the `:1354-1384`
block r1 scoped the mirror to, which is exactly how it went missing.

**This is not cosmetic, and it would have shipped green.**

- `RunResult.evidence` is populated only by `json.loads(stdout)`
  (`runner.py:80-88`), and the CLI prints the envelope only under
  `--json` (`_finish_verb`). Without the flag, `evidence is None` and
  `_evidence_ctx` **degrades**: measured against the shipped
  `action_confirm` leg with human stdout, `HAS_DEGRADED_TEXT True` —
  production renders *"route succeeded for `lrn-…` — the outcome details
  could not be read"* (`evidence.html:25-28`). That is the inadequate
  acknowledgement this unit exists to replace.
- **`FakeRunner.run` ignores argv entirely** (`runner.py:148-152`) — it
  pops the queued `RunResult` regardless. So an acceptance test written
  the way every existing evidence test is written renders the canon path
  and sha **and passes on a build that never sends `--json`**.

The parent spec already listed this as its own step
(`resolution-evidence-spec.md:477` — "Pass `--json`; carry evidence into
context; stop redirecting at all four sites"). r1 carried the second and
third clauses and dropped the first.

`route_argv` is therefore built with `as_json=True`, mirroring `:1286`.

### 2.2 What must not change

- **The two failure legs.** Commit failure (`:1729-1733`) and retry
  failure (`:1758-1763`) render plainly. A second dirty refusal must not
  re-offer the commit-drift button — the docstring pins this: "no loop,
  and the commit-drift button never re-appears on that leg".
  **One carve-out:** the retry-failure leg's empty-stderr fallback
  `f"self-learn {' '.join(route_argv)} failed"` (`:1762`) necessarily
  gains `--json` in its echoed argv. Everything else on that leg is
  unchanged.
- `action_confirm` itself, and the other four redirect sites.

### 2.3 What must change that r1 did not name

**`test_commit_drift.py:239-243` asserts the defect as the contract.** It
covers exactly this path and ends with
`assert r.headers.get("hx-redirect")` — pinning the silent teleport — and
asserts `runner.calls == [[…], ["route", rec.id, "--dest", "skill-md"]]`
with no `--json`. Both are superseded by this unit and must be updated,
not worked around.

It was written 2026-07-19 (`1bb0504`) and the resolution-evidence unit
(`29d1672`) never touched that file, so it kept asserting the
pre-evidence contract while the surface's contract changed underneath it.

**And the enumeration was the hole, not the assertions.**
`test_resolution_evidence.py:600` `TestRedirectSuppressionFourSites`
enumerates exactly the four sites §3.4 named, and contains **zero**
occurrences of `commit_drift` in the whole module. A hand-maintained list
of sites drifted from the set of sites that exist — the same defect class
as a spec re-enumerating a set it defined elsewhere. Whoever builds this
should consider whether that test can derive its site list rather than
carry one.

---

## 3. Acceptance

1. **The W3-F1 reproduction.** Dirty target → route refuses → arm
   commit-drift → confirm → **the evidence leg renders**, carrying the
   queued envelope's `canon_path` and its 7-char `host_commit_sha`
   (`evidence.html:33-34`). No redirect. **And the retry argv is
   asserted**: `["route", rec.id, "--dest", "skill-md", "--json"]` in
   `runner.calls` (§2.1 — without this the test passes on a build that
   never sends the flag, since `FakeRunner` ignores argv).

   *One line, not two.* For a landed `route`, `evidence.html:31-34`
   renders a single canon-path `@` sha line, and the envelope carries one
   sha (`host_commit_sha`; there is no ledger sha). The two "Committed …
   locally" note lines (`evidence.html:82-91`) render only under
   `pushed`/`host_pushed` ∈ {`no_remote`, `not_requested`} — true in the
   sandbox world, but envelope-state-dependent, so they are not asserted
   here.
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
| **drop `--json` from `route_argv`** | 1 |
| pass `evidence=None` to the contradicts response | 2 |
| pass `evidence=None` to the adopt response | 3 |
| build `next_url` with `next_record_url` instead of the raw id | 4 |
| add evidence to the retry-failure leg | 6 |

**Test 6 needs one more assertion or its mutation survives.** "Add
evidence to the retry-failure leg" yields `_evidence_ctx(run_result=retry)`
with `retry.evidence is None` (`__post_init__` returns early on non-zero
exit), so a *degraded* "route succeeded…" block renders above the error
strip — while test 6's stated assertions (marker text present,
`"commit-drift/arm" not in r.text`) both stay true. Add
`assert 'data-verb-success' not in r.text` (`evidence.html:24`).

**The positive control r1 specified cannot fail — measured.**
`_evidence_ctx` sets `"record_id"` from the **URL path parameter**
(`routes.py:1097`), never from the envelope. Queueing an envelope with
`record_id="lrn-deadbeef"` against `/record/<rec.id>/…` renders the URL
id and never the envelope id (`URL_ID_RENDERED True`,
`ENVELOPE_ID_RENDERED False`). So "assert the evidence names this
record's id" is true on every reachable build, including broken ones —
`lrn-ea833a5b` exactly.

**The control that does bite** is envelope-sourced: assert the
`canon_path` and 7-char sha from the *queued envelope*, which can only
appear if the evidence came from the **retry's** `RunResult` rather than
from `commit_result` or a degraded default.

**Run-evidence control.** If any test lands in the js/browser module,
report the collected/passed count — `test_js_dom.py:87` is an
`importorskip` and a skipped module is not a red test.

---

## 4. Builder decisions, made here rather than left open

- **Where the new tests live:** `test_commit_drift.py`, importing
  `envelope` from `test_resolution_evidence` — this is the commit-drift
  path, and `:239-243` in that file must change anyway (§2.3).
- **The statically-true guard:** there is no `verb` variable in this
  handler. Bind `verb = "route"` next to `route_argv` and keep
  `if verb in _EVIDENCE_VERBS`, so the mirror stays textually identical
  to `action_confirm` and a future verb change cannot silently produce
  `evidence=None`.
- **`_bucket_name_for` (`:1781`) is replaced by the single
  `ledger.locate_record` call** the mirrored block needs anyway for
  `bucket_scope` → `bucket_url`. Two lookups where the mirror uses one
  is how they drift.

## 5. Revision history

- **r1** — **NOT SOUND**, 1 blocker + 7 bounded substitutions. The
  blocker: the retry argv never gained `--json`, so the fix would ship
  the degraded acknowledgement in production while every `FakeRunner`
  test stayed green. r1 carried two of the parent spec's three clauses
  and dropped the first.
- **r2** — this document. Folded under the 2026-07-26 verdict repricing:
  the seven substitutions were dictated in full by the gate and are
  verified downstream at the code gate rather than costing another spec
  round.

## 6. Out of scope

- W4-F1 ring targeting — its own spec, `ring-targeting-spec.md`.
- The no-op hint surface split out of that spec.
- The other `ui-walks.md` findings.
