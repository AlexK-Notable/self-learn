# Spec — U-grad-ui: a resolved lesson must be reachable, and retirable, from the GUI

Status: **DRAFT r1**, 2026-08-02. Not an r2-campaign unit — this comes
from a user bug report filed the same day.

> "it's impossible to graduate an already approved lrn via the gui.
> there's no surface for it because you can't see lrns you've already
> approved."

**This unit adds no capability.** `graduate` already works on a routed
record — measured, §1.2. The whole defect is a missing *read* surface.
Every line below is about reachability.

**Read `resolution-evidence-spec.md` §10 and
`commit-drift-evidence-spec.md` §7 before touching this surface** —
between them, fifteen defects that a green suite could not see. This
unit is the same shape as the two findings that started the r2 audit:
a feature that exists, passes its tests, and delivers nothing because no
path leads to it. Ask at every step whether a **user** can get to the
thing, not whether the code that would render it is covered.

**§3 (acceptance) and §3.1 (mutation plan) ARE the spec. Prose is
rationale. Where prose and criteria conflict, the criteria win.**

---

## 1. The defect

### 1.1 What the user sees

There is no place in the app that lists the lessons you have approved,
and no page you can open one on. Concretely, all four navigable surfaces
were walked against a sandbox holding one pending and one routed record
(probe, 2026-08-02):

| Surface | Shows the routed record? |
|---|---|
| Front `/` | **no** |
| Bucket `/bucket/skill/s` | **no** (shows the pending one) |
| Detail `/record/<routed-id>` | **no** — `303 → /bucket/skill/s?notice=resolved-elsewhere` |
| Report `/report` | **the bare id, as inert text** |

The one surface that names the record at all is `/report`'s "Routed &
live" table (`report.html`), which renders

```html
<tr><td>lrn-bbbb0002</td><td>s</td><td>32</td><td>0</td></tr>
```

— no link, no lesson text, no action. A user looking at that row cannot
tell which lesson it is, cannot open it, and cannot act on it. The
user's word "see" is exact: the id is on screen and the lesson is not.

### 1.2 What already works, and must not be rebuilt

- **The CLI verb.** `verbs.graduate` (`verbs.py:2913`) resolves its path
  with `find_record_path(home, record_id)  # pending OR resolved` and
  runs a host-cleanup phase written specifically for the routed case.
  Verified live in a sandbox, not read off the docstring: graduating a
  really-routed record returns `action="graduate"` with a commit sha and
  leaves the record `superseded / superseded_by: canon`.
- **The UI's own I/O layer.** `ledger.locate_record` already finds
  resolved records and already reports `RecordLocation.resolved`
  (`ledger.py:216-236`). `routes._gather_detail_bundle` already carries
  a branch for records that "fall out of `list --json` (pending-only)"
  (`routes.py:306-322`) and builds a complete `DetailReadBundle` for a
  routed record. `models.build_detail_model` consumes it without
  raising (probe).
- **The execution half.** POSTing `verb=graduate` to
  `/record/<routed-id>/action/arm` then `…/action/confirm` returns
  `200`/`200` today and dispatches `["graduate", "<id>", "--json"]`
  (probe). No new POST route is needed. **The arm/confirm pair never
  checks record status** — only the GET does.
- **The button.** `action_bar.html`'s `kind == "holding"` branch already
  renders `Graduate (g)` wired to `verb: graduate` — for routed records,
  on the front page's "Is it holding?" section. That section renders
  only when `report --json`'s `recurrence_suspects` is non-empty, and
  **zero `recurrence-suspect` events have ever been emitted on this
  host** (r2 campaign playbook §7). So the one built path to this action
  has never once been on screen. That emitter is `U-recur`'s job; it is
  out of scope here (§6), and re-siting its surface into this unit would
  be exactly the adjacent-feature absorption §9 of the playbook names as
  this project's most expensive error.

So the parts exist and none of them are wired to a page a human can
reach. This unit wires them.

### 1.3 The blocking line

```python
# routes.py:570-579, inside detail_page
    if record.status not in ("pending", "deferred"):
        slot = _proposal_slot(request)
        if slot is not None:
            slot.clear_for_record(record_id)
        target = f"/bucket/{location.scope}/{location.bucket_name}?notice={NOTICE_RESOLVED_ELSEWHERE}"
        return RedirectResponse(url=target, status_code=303)
```

Everything above it — locate, read, bundle, item synthesis — has already
succeeded for the resolved record by the time this fires. The bundle is
built and thrown away.

---

## 2. The normative register

Three sets. **Each is defined once, here, and referenced by name
everywhere else in this document. No later section re-enumerates
one.** (`commit-drift-evidence-spec.md` §7 finding 6: a re-enumerated
set is how a hand-maintained list drifts from the set that exists.)

### 2.1 `VIEWABLE` — what the Detail page renders

> **`VIEWABLE` = every record `ledger.locate_record` finds and
> `ledger.read_record` parses, whatever its `status`.**

That is: the status test is **deleted**, not widened. A record is
viewable iff the ledger can produce it.

Rationale. A status allow-list is the drift shape this corpus keeps
paying for. And the thing that must be gated is the *action*, not the
*view*: reading a rejected or graduated lesson is useful and harmless;
acting on one is not. Gating the action (§2.3) is strictly safer than
gating the page, because the action gate also covers the pending-page
paths, which a page gate never touched.

**Consequence — deliberate, not incidental.** `NOTICE_RESOLVED_ELSEWHERE`
stops being emitted by `detail_page`. Its intent (09 §11 P1-9c: a
concurrent CLI session resolved this record; do not let the human act on
it) is preserved and *better served* — instead of a teleport with a
banner on another page, the human stays on the record and sees what
happened to it, with no resolution actions offered. A teleport with no
receipt is the W3-F1 defect class this project fixed six days ago.
The proposal-slot clear on that path is **kept** (§3, criterion 4).

### 2.2 `INDEX-SET` — what the index lists

> **`INDEX-SET` = exactly the records in `report --json`'s
> `routed_live` array, i.e. `status == "routed"`, taken verbatim from
> the CLI. The UI never re-derives this set.**

Excluded, each with its reason:

- **`superseded` (includes graduated).** Terminal. `report --json`
  exposes graduated records as an integer (`graduated`), never as ids
  (`report.py:348-357`), so listing them would require a new CLI read
  surface — see §7. And a graduated record leaves `INDEX-SET` the moment
  it is graduated, which is this unit's structural answer to "do not
  offer the action twice" (§2.4).
- **`rejected`.** Also count-only in `report --json`. And the verb is
  wrong for it: measured, `graduate` on a rejected record **succeeds**
  and silently rewrites a denied lesson to `superseded_by: canon` (§7).
  The CLI does not guard this. Listing rejected records here would put
  that one keystroke away.
- **`deferred`.** Already reachable — Front and Bucket both read
  `list --json --include-deferred` (`routes.py:409, 444`) and
  `/record/<deferred-id>` already returns 200 (pinned today by
  `test_resolution_evidence.py::…::test_a_deferred_record_still_resolves_at_record_id`).
  Adding it would duplicate a live surface.
- **`pending`.** The queue. That is the rest of the app.

The single reason that covers all four: `routed_live` is the *only*
resolved-record set the existing CLI read verbs enumerate **with ids**,
and this unit is UI-only by scheduling constraint (§7).

### 2.3 `RESOLVED-VERBS` — what is offered on a viewed resolved record

> **`RESOLVED-VERBS` = `{graduate}`, offered if and only if the record's
> `status == "routed"`.**

Everything else is refused, each for a stated reason:

- `route` / `reject` / `defer` — the record is already resolved; the CLI
  would refuse or corrupt.
- `cycle destination` — there is no proposal to re-aim.
- `iterate` (the agent pane) — a resolved record is substance-frozen
  (`Record.substance_frozen`, `records.py:355-361`), so the pane agent's
  edits would be refused. Rendering the control offers a failure.
- `confirm-recurrence` / `tolerate` — already have a surface (the front
  page's holding rows). Their being dark is `U-recur`'s defect, not
  this unit's.
- `followup done`, `link contradicts` — already have surfaces.
- **revise / escalate** (the review skill's other two "not holding"
  outcomes) — these author a *new* record via `teach --supersedes`;
  they are session work, not a button. `action_bar.html` already says so
  in the holding branch, verbatim: *"Revise / Escalate: capture with
  `teach --supersedes` (session work)."*

The user asked for `graduate`. `graduate` is what ships.

### 2.4 The already-graduated rule

Two independent defences, deliberately not one:

1. **Structural.** `graduate` moves a record from `routed` to
   `superseded`, so it leaves `INDEX-SET` by construction. Verified:
   after graduating every routed record in a sandbox, `routed_live ==
   []`.
2. **Per-page.** The Detail page independently re-checks
   `record.status == "routed"` before offering the action, because a
   record in `VIEWABLE` can be reached without going through the index
   (a bookmarked URL, a stale tab, a link from elsewhere).

Defence 2 is not redundant. Measured: `graduate` on an
already-graduated record raises
`HalfWrittenError: git commit … failed: nothing to commit, working tree
clean` — an alarming, half-written-sounding error for what is really a
benign double-tap. The surface must never produce it.

---

## 3. Acceptance criteria

All tests live in a new `plugins/self-learn/ui/tests/test_resolved_surface.py`
unless named otherwise. Fixtures use the existing
`support.resolve_record_directly(...)` (already builds routed/rejected/
superseded ledger states without a real verb) and `support.make_env`.

**Every visibility assertion below is paired with an exclusion
assertion in the same criterion.** A test that a record IS listed passes
against a view that lists everything; it is worth nothing alone.

1. **The link-walk — the reachability control.** Starting from `/` and
   following only hrefs actually present in the returned HTML, a routed
   record's Detail page is reached: `GET /` → the bucket link → the
   bucket page → an `<a href="/record/<routed-id>">` → `GET` it →
   `200`. **No URL in this test is hand-constructed after the first
   `GET "/"`.** This is the criterion the r2 audit's two dead features
   would have failed.

2. **The index lists `INDEX-SET` and nothing else.** With four records
   seeded in one bucket — one `pending`, one `routed`, one `rejected`,
   one `superseded`/`superseded_by: canon` — the index section contains
   the routed id and **does not contain** the pending, rejected, or
   graduated ids. The count in the section's summary reads `1`.

3. **The index does not cross buckets.** Two buckets exist whose names
   differ; a routed record in bucket A does not appear in bucket B's
   index section, and vice versa. Plus the collision leg: two buckets
   sharing a **name** across different **scopes** (`skills/x` and
   `projects/x`) each show only their own routed record.
   *(`routed_live` carries the bucket NAME and no scope —
   `report.py:279-289` — so a name-only filter mis-attributes. The
   builder must confirm scope through `ledger.locate_record`.)*

4. **Y-9 holds, and the redirect's slot-clear survives.** Two legs:
   (a) an index row's link text is the record's leading text, not its
   id — the row for a record whose Trigger reads *"About to edit
   .storage while HA is running."* renders that string, and the id does
   **not** appear as the anchor's text;
   (b) `GET /record/<routed-id>` with a proposal slot held for that
   record returns `200` **and** the slot is cleared (the behaviour
   `routes.py:576-577` performed on the deleted redirect path).

5. **`VIEWABLE` renders every status.** `GET /record/<id>` returns `200`
   for a `routed`, a `rejected`, and a `superseded` record, and the
   response body carries the record's own Trigger text in each case
   (not merely a `200` on an empty page). The pending and deferred legs
   still return `200` — no regression.

6. **`RESOLVED-VERBS` is offered, and nothing else is.** On a routed
   record's Detail page: exactly one `data-key-action="graduate"`
   element is present, and **none** of
   `data-key-action="route"`, `"reject"`, `"defer"`,
   `"cycle_destination"`, `"iterate"` appear anywhere in the response.
   Assert both halves; the absence half alone passes against a blank
   page, so criterion 5's positive text assertion is its control.

7. **The action is not offered twice.** On a `superseded`/`canon`
   record's Detail page, and on a `rejected` record's Detail page, there
   is **no** `data-key-action="graduate"` element — while the page
   still returns `200` and still carries the record's Trigger text
   (criterion 5's control, re-used so this is not an
   everything-is-absent pass).

8. **End to end: the verb actually runs, and the receipt renders.**
   From a routed record's Detail page, POST `…/action/arm` then
   `…/action/confirm` with `verb=graduate` and the page's own `kind`:
   - `runner.calls == [["graduate", "<id>", "--json"]]` — asserted
     exactly, including `--json`. *(`FakeRunner.run` ignores argv
     entirely, `runner.py:148-152`, so a test that does not assert the
     argv passes on a build that never sends the flag — the
     `commit-drift` blocker, one layer over.)*
   - The response renders the **evidence leg**, carrying the
     `canon_path` and the 7-char `host_commit_sha` **from the queued
     envelope**. *Envelope-sourced, not URL-sourced:* `_evidence_ctx`
     sets `record_id` from the URL path parameter
     (`routes.py:1104`), so "the evidence names this record's id" is
     true on every reachable build including broken ones
     (`lrn-ea833a5b`, and measured as such in
     `commit-drift-evidence-spec.md` §3.1).

9. **The fossil comment is corrected.** `_evidence_ctx`'s comment at
   `routes.py:1108-1121` (the block immediately above `record_url` at
   `:1122`) justifies `record_url = None` for
   `route`/`reject`/`graduate` on the grounds that *"`record_detail`'s
   GET redirects (`record.status not in ("pending", "deferred")`)"*.
   After this unit that sentence is **false**. The behaviour is
   unchanged (§6) and the comment must be rewritten to state the
   surviving reason. Asserted as a source-text check: the string
   `record_detail`'s-GET-redirects rationale no longer appears.
   *(`commit-drift-evidence-spec.md` §1: "a fossil rationale reads
   exactly like a live one." That fossil was worth a blocker there.)*

10. **The two proposal-slot staleness guards are untouched.**
    `routes.py:1253` (`_sweep_stale_proposal`) and `routes.py:2117`
    (`proposal_confirm`) contain the *same textual predicate*
    `record.status not in ("pending", "deferred")` and must both keep
    it — a proposal held against a resolved record is stale and must
    still clear. Pinned as an assertion: arming a pane proposal on a
    record, resolving it out of band, then re-entering
    `proposal_confirm` still returns the `proposal_gone` response.

11. **The existing test that asserts the defect is updated, not worked
    around.** `test_resolution_evidence.py`'s
    `TestResolvedRecordRedirectsAwayFromItsOwnDetailPage::test_a_routed_record_no_longer_resolves_at_record_id`
    (class at `:391`, the test at `:396-404`) asserts `303` and the
    `resolved-elsewhere` location — it pins the behaviour this unit
    removes. Rewrite it in place to the new contract; do not delete it
    and do not add a sibling. Its class name and the block comment
    immediately above it (`:375-389`) both describe the redirect
    as the reason "View what changed (v)" is suppressed; that reason
    changes and the prose must change with it. **The `v`-button
    behaviour itself does not change** (§6).

12. **Suite baseline.** `cd plugins/self-learn/ui && uv run pytest -q`
    with `XDG_CACHE_HOME` redirected: no new failures against the
    2026-07-28 baseline (1010 passed / 77 skipped / 1 known
    `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`).
    If any new test lands in a browser/js module, **report the
    collected/passed count** — `test_js_dom.py:87` is an `importorskip`
    and a skipped module is not a red test.

### 3.1 Mutation plan

Each row is a **one-line edit to production code** that must make
**exactly** the named criterion fail. The code gate will run every one
of them and is invited to invent more.

| # | Mutation | Criterion that must fail |
|---|---|---|
| M1 | In `detail_page`, restore `if record.status not in ("pending","deferred"): return RedirectResponse(...)` | 1, 5 |
| M2 | In the index builder, drop the scope confirmation and filter `routed_live` on `bucket` name alone | 3 (collision leg only) |
| M3 | In the index builder, replace the `routed_live` source with a walk of every `resolved/` record | 2 |
| M4 | In the index row builder, return `record.id` instead of the record's leading text | 4(a) |
| M5 | In `detail_page`, render the pending action-bar `kind` for a resolved record instead of the resolved one | 6 |
| M6 | Delete the `record.status == "routed"` condition guarding the Graduate control | 7 |
| M7 | In the resolved Detail render, restore the `detail-right` pane column include | 6 (the `iterate` half) |
| M8 | Change the resolved Graduate control's `hx-vals` verb from `graduate` to `reject` | 8 (argv leg) |
| M9 | Delete the `slot.clear_for_record(record_id)` call on the new resolved-render path | 4(b) |
| M10 | Feed the evidence leg from a second `RunResult` with no stdout (evidence degrades) | 8 (envelope leg) |
| M11 | Restore the old comment text at `routes.py:1110-1121` | 9 |
| M12 | Change `record.status not in ("pending","deferred")` at `routes.py:1253` to `record is None` | 10 |

**Two traps this plan is built around.**

*M3 is the positive control for criterion 2.* A test asserting "the
routed record is listed" passes against an index that lists every
resolved record — which is what M3 produces. Only the paired exclusion
assertions (rejected + graduated absent) kill it. If criterion 2 is
written without them, M3 survives and the criterion is worthless.

*M6 and M7 both target criterion 6/7 by absence.* Absence assertions
pass against a blank page. That is why criteria 6 and 7 each carry a
**presence** assertion (the record's own Trigger text) in the same test:
the presence half is the positive control for the absence half. A
criterion that only asserts absences is the
`test_cleared_bucket_omits_next_pending_link` failure
(`commit-drift-evidence-spec.md` §7 finding 2), which stayed green with
the entire feature deleted.

---

## 4. THE FORK — where the index lives *(the only substitutable section)*

Everything else in this document is invariant across the three options
below. The row model, the data source (`report --json` → `routed_live`),
the Detail page, the action, and every criterion except the two words
naming the host page are identical. Switching options is a bounded
substitution confined to this section.

### 4.1 Recommended — **B1: a collapsed section on the Bucket page**

Beneath the pending destination groups, a default-collapsed
`<details>`:

```
▸ Routed here (7)
```

expanding to rows in the shape the Bucket page already uses for pending
records — `<a href="/record/{id}">{leading text}</a>` plus plain-words
facts (routed N days ago → destination; recurrences if any) — and
`data-row` so the existing `w`/`s`/`d` selection walk covers them for
free.

Why this one:

1. **The data is already on the page's doorstep and needs no CLI
   change.** `report --json` already returns every routed record's id
   and bucket; the Bucket page already knows its own scope and name.
2. **It is where the user already looks.** A bucket page is "this
   skill's lessons". Approved lessons belong under the pending ones, not
   behind new navigation the user has to discover. This is the
   discoverability half of the bug report, and a new top-level route
   would leave it unsolved in a different place.
3. **Zero new routes, zero new keys, zero new navigation.** Collapsed
   `<details>` is the app's established pattern for secondary content
   (episode brief, near-misses, raw proposal YAML).

### 4.2 Alternative — **B2: a dedicated `/resolved` route**

Cleanest separation; the archive stops sharing a page with the decision
queue. Costs: a new route, a new `page_kind`, a new footer/CSS context,
and a new discoverability problem (it needs a link from the front page,
which is the thing the bug report says does not exist). Prefer this if
the user's judgment is that the Bucket page must stay a pure decision
surface.

### 4.3 Alternative — **B3: a section on `/report`**

Cheapest possible diff — the table is already there; it gains links and
leading text. But `/report`'s own contract is *"rendered verbatim,
read-only. No charts, no derived numbers the CLI didn't compute"*
(`report.html`), and a navigable, action-adjacent list fights it. It is
also the page a user visits least. Prefer this only if minimal diff
outranks discoverability.

### 4.4 Explicitly rejected — a filter/toggle on the pending queue

The Bucket page's queue is `list --json` items grouped by *proposed
destination*, with proposal-derived leading text, freshness badges and
bulk-collapse. A resolved record has **no proposal** — the siblings are
deleted at resolution by `remove_proposal_siblings` — so it has no
group, no card sections, no freshness. Putting resolved records into
that list means either changing `list --json` (a CLI edit into
`ledger_ops.py`, which `U-schema` is editing right now — a direct
collision) or re-deriving the CLI's computed list shape inside the UI,
which 09 §3's two-read-path pin forbids. Highest cost, highest collision
risk, worst semantic fit. B1 is not this: it adds a second section and
leaves the queue list untouched.

### 4.5 Not an option on its own — direct id lookup

Making `/record/<id>` render resolved records is **necessary for all
three options** and is specified as invariant (§2.1, criterion 5). It is
not an alternative to them: a user cannot type an id they have never
seen. Shipping it alone would answer "can the app address a resolved
record" while leaving the user's actual sentence — *"you can't see
lrns you've already approved"* — untouched.

---

## 5. Builder decisions, made here rather than left open

- **The action lives on the Detail page, never on index rows.**
  `app.js`'s `clickAction` is
  `document.querySelector('[data-key-action="' + action + '"]')`
  (`static/app.js:54-55`) — **first match in document order, with no
  awareness of which row is selected.** N rows each carrying a Graduate
  button would make `g` always fire row 1, silently retiring the wrong
  lesson. The Detail page renders exactly one record, so `g` is
  unambiguous there. *(The Bucket page already has the N-row shape and
  therefore already has this hazard; fixing it is out of scope, §6, but
  no new surface may add to it.)*

- **No new keymap entries.** `KeymapEntry(("g",), "graduate", …)`
  already exists and the resolved Detail page renders exactly one
  `data-key-action="graduate"` target. Free letters are `h k l m z`; this
  unit consumes none. The keymap-uniqueness test is untouched.

- **A separate template, `templates/detail_resolved.html`.** Precedent:
  `detail_degraded.html` is already a second Detail template for a
  non-ordinary record state. The resolved view diverges too far to
  branch inside `detail.html` — it renders no proposal cards, no Change
  region, no destination cycle, no pane column, and a different action
  bar. Branching a template that large invites a stale-`{% if %}`
  defect. It **must** carry a distinct `{% block page_kind %}` so the
  keymap footer does not advertise `e`/`x`/`f`/`o`/`i` as live keys on a
  page where they do nothing — that is the `h`-on-the-header defect
  (ui-walks W2-F1) and must not be reproduced. Show `g` there with a
  `body[data-page="…"] .keymap-footer-entry[data-action="graduate"]`
  rule, the shape `style.css:328/342/395-397` already uses.

- **A new action-bar `kind`: `"resolved"`.** Added as one more branch in
  `action_bar.html`'s unarmed `{% elif kind == … %}` chain, rendering
  the single Graduate control. The **armed** branch is kind-agnostic and
  is reused verbatim — arm-then-confirm, `Enter` confirms, any other key
  cancels, unchanged. `_dom_id(kind, record_id, target)` disambiguates
  as it already does.

- **No new POST route.** `action_arm`/`action_confirm` already accept
  `verb=graduate` against a resolved record and already dispatch
  `--json` (`as_json=verb in _EVIDENCE_VERBS`, `routes.py:1293`).
  Measured working. Adding a route would fork the evidence surface.

- **The index's set comes from the CLI; its text comes from a raw read.**
  Ids and routing facts: `report --json`'s `routed_live`, verbatim, so
  the set can never drift from what the CLI says is routed. Leading
  text: `ledger.read_record` on the located path + the CLI's own
  `ledger_ops.record_title` — the same raw-read path Detail already
  uses, never a second title definition. This honours 09 §3's pin
  literally: CLI-computed *shapes* are never re-derived; raw file reads
  serve display text.

- **Filter `routed_live` by name first, confirm scope second.**
  `routed_live` rows carry `bucket` (name) and no scope, so name-only
  filtering mis-attributes across `skills/x` vs `projects/x`. Filter on
  name (cheap, over-broad), then confirm each survivor's true scope via
  `ledger.locate_record`. O(k), not O(all routed). Guarded by M2.

- **Fix `_gather_detail_bundle`'s synthesized `title`.** `routes.py:320`
  hardcodes `"title": models.leading_text(None, [], "")` → `"(untitled)"`
  for exactly the records this unit makes viewable, and that value flows
  into `FindingRegion.title` (`models.py:1442` →`_build_finding`). Set
  it from `ledger_ops.record_title(record)`. The resolved template
  renders `model.finding.title` as its heading, so the fix has a
  consumer and a test rather than being a silent tidy-up.

- **On the real ledger this is 31 rows.** Measured 2026-08-02 (file
  counts only — no verb was run against `~/.self-learn`): 35 pending,
  54 resolved, of which **31 routed**, 22 superseded (19 of them
  `superseded_by: canon`), 1 rejected. `report --json` is already one of
  the front page's four subprocess reads; adding it to the Bucket page
  is within the app's existing budget at this scale.

---

## 6. Out of scope — named so a reviewer does not read them as gaps

1. **`U-recur` / the dark "Is it holding?" section.** Zero
   `recurrence-suspect` events have ever been emitted (r2 playbook §7),
   so the front page's holding rows — and the Graduate button already
   inside them — have never rendered. Fixing the emitter is `U-recur`
   (`miner.py`). This unit neither depends on it nor duplicates it.
2. **`_evidence_ctx`'s `record_url` suppression.** After this unit the
   post-`route`/-`graduate` evidence leg *could* honestly offer "View
   the record". Changing it is a behaviour change to a surface shipped
   six days ago; **only the comment is corrected** (criterion 9).
3. **`clickAction`'s first-match dispatch on multi-row pages.** A real,
   pre-existing defect on the Bucket page. Not created, not fixed, and
   worked *around* here by keeping the action off list rows (§5).
4. **`watch_paths` does not watch `resolved/`** (`ledger.py:422-431`).
   An in-app graduate refreshes the index (`_force_refresh` runs after
   every verb); a graduate performed by an external CLI session does
   not push a refresh, and the 10 s client poll catches it. Adding
   `resolved/` to the watcher would make every autosync touch of the
   archive wake every client. Known limitation, deliberately unfixed.
5. **The CLI's willingness to graduate a `rejected` record** (§7) and
   its `HalfWrittenError` on a double-graduate. Both are CLI-side, both
   collide with the concurrent wave, and neither is reachable through
   this unit's surface (§2.3/§2.4). Reported, not fixed.
6. **Front-page bucket rows do not show a routed count.** Adding one
   would be a second surface with a second set of counts.

---

## 7. Scheduling: **no CLI change is needed**

This unit is **UI-only**. Files touched:

```
plugins/self-learn/ui/src/self_learn_ui/routes.py
plugins/self-learn/ui/src/self_learn_ui/models.py
plugins/self-learn/ui/src/self_learn_ui/ledger.py        (only if a helper is added)
plugins/self-learn/ui/templates/bucket.html              (§4 fork — B1)
plugins/self-learn/ui/templates/detail_resolved.html     (new)
plugins/self-learn/ui/templates/partials/action_bar.html
plugins/self-learn/ui/static/style.css
plugins/self-learn/ui/tests/test_resolved_surface.py     (new)
plugins/self-learn/ui/tests/test_resolution_evidence.py  (criterion 11)
```

None of `worker.py`, `analyst.py`, `ledger_ops.py`, `selfcheck.py`,
`telemetry.py`, `verbs.py`, `miner.py` is touched. No collision with the
five concurrent CLI units.

**The read surfaces were enumerated before concluding this**, per the
brief:

| Existing CLI read | Enumerates resolved records? |
|---|---|
| `list --json` (`ledger_ops.list_items:1108`) | **No** — iterates `queue(bucket, …)`, pending only. `--include-deferred` widens to deferred, which still lives in `pending/`. `--id` filters the same pending set. |
| `status --json` (`status_infos`) | **No** — per-bucket pending counts only. |
| `report --json` (`report.gather:230`) | **Yes, partly.** `routed_live[]` = every `status: routed` record with `{id, bucket, routed_days_ago, last_confirmed, recurrences}`. `open_followups[]` and `recurrence_suspects[]` also carry resolved ids. `graduated`/`rejected` are **integers only** — no ids. `buckets[].counts` gives per-status counts per bucket. |
| `mine status --json` | No. |

`routed_live` is sufficient for `INDEX-SET` and is why `INDEX-SET` is
defined as it is (§2.2). Widening the surface to graduated or rejected
records **would** require a new CLI read path — the natural home being
`report.gather`'s return map in
`plugins/self-learn/cli/src/self_learn/report.py` (adding
`graduated_live` / `rejected_live` id lists beside `routed_live`, ~10
lines, no shared-function edit). That file is **not** in the concurrent
wave's file set, so it is schedulable — but it is not needed for this
unit and is not requested.

---

## 8. Empirical basis

Every measurement below was taken 2026-08-02 in a throwaway sandbox
(`support.make_env` under `/tmp`, all five env vars redirected).
**No mutating verb was run against `~/.self-learn`; the only contact
with the real ledger was `find`/`grep` over record files.**

1. `graduate` on a genuinely **routed** record → succeeds; record ends
   `resolved/`, `status: superseded`, `superseded_by: canon`.
2. `graduate` on an **already-graduated** record → raises
   `HalfWrittenError: git commit -q -m "self-learn: graduate lrn-…" …
   failed: On branch main / nothing to commit, working tree clean`.
3. `graduate` on a **rejected** record → **succeeds**, silently
   rewriting a denied lesson to `superseded_by: canon`. Unguarded in the
   CLI.
4. After graduating them all, `report.gather(...)["routed_live"] == []`
   — `routed_live` tracks `status == "routed"` exactly.
5. `GET /record/<routed-id>` → `303`, `location:
   /bucket/skill/s?notice=resolved-elsewhere`.
6. `GET /` and `GET /bucket/skill/s` → the routed id appears in neither;
   the "Is it holding?" section does not render.
7. `GET /report` → the routed id appears, as inert `<td>` text; the
   string `/record/<id>` appears nowhere in the page; the record's own
   Trigger text appears nowhere in the page.
8. `POST /record/<routed-id>/action/arm` (`verb=graduate,
   kind=holding`, `HX-Request: true`) → `200`, Graduate rendered;
   `POST …/action/confirm` → `200`,
   `runner.calls == [["graduate", "lrn-bbbb0002", "--json"]]`.
9. `_gather_detail_bundle` + `models.build_detail_model` on a routed
   record → succeed; `finding.title == "(untitled)"` (the §5 defect),
   `change.kind == "none"`, `record_title(record) == "ROUTED trigger
   about the printer."`
10. Real ledger, file counts only: 35 pending; 54 resolved = 31 routed +
    22 superseded (19 `canon`) + 1 rejected.

## 9. Revision history

- **r1** — this document.
