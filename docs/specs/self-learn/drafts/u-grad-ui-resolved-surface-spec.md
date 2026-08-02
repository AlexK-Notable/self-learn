# Spec — U-grad-ui: a resolved lesson must be reachable, and retirable, from the GUI

Status: **DRAFT r3**, 2026-08-02. Not an r2-campaign unit — this comes
from a user bug report filed the same day. r1 gated **NOT SOUND**
(2 blockers + 14 folds); r2 cleared both blockers and gated with 2
further folds, no blockers; r3 is the folded document and is the version
to build. See §9.

> "it's impossible to graduate an already approved lrn via the gui.
> there's no surface for it because you can't see lrns you've already
> approved."

**This unit adds no capability.** `graduate` already works on a routed
record — measured, §1.3. The whole defect is a missing *read* surface.
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

**Two decisions are settled and are not open to the builder:** the index
lives on the Bucket page (§4, user-ratified 2026-08-02), and the
`graduate`-on-a-rejected-record defect is logged as **FW-51**, not fixed
here (§6.5).

---

## 1. The defect

### 1.1 What the user sees

There is no place in the app that lists the lessons you have approved,
and no page you can open one on. All four navigable surfaces, walked
against a sandbox holding one pending and one routed record (probe,
2026-08-02):

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

### 1.2 Graduate is on screen every day — but never for a routed record

This section replaces r1's framing, which was wrong in the same way the
briefing that produced it was wrong. There are **three**
`data-key-action="graduate"` sites in the app, and two of them render
routinely:

| Site | Renders when | Reaches a routed record? |
|---|---|---|
| `action_bar.html`, default unarmed quad ("Graduate (g)") | every Detail page and every Bucket record row | **No** — those are pending records |
| `bucket.html`, bulk-collapse row ("Acknowledge all as canon") | a homogeneous already-canon group exists | **No** — the bulk-acknowledge door, pending records only |
| `action_bar.html`, `kind == "holding"` branch ("Graduate (g)") | the front page's "Is it holding?" section | **Yes — and it has never rendered** |

The holding branch is the only one a routed record can reach, and its
section renders only when `report --json`'s `recurrence_suspects` is
non-empty. Verified 2026-08-02 by `grep -c 'recurrence-suspect'` over
both real telemetry files
(`~/.self-learn/telemetry/2026-07.komi-hypr.jsonl`,
`2026-08.komi-hypr.jsonl`): **0 and 0.** No such event has ever been
emitted on this host (r2 campaign playbook §7 diagnoses the cause as a
channel split in the miner prompt).

So the precise claim is: **Graduate is a familiar, daily control that is
structurally unable to reach the records the user is asking about.**
Wiring the missing emitter is `U-recur` (`miner.py`); it is out of scope
here (§6.1), and re-siting its surface into this unit would be exactly
the adjacent-feature absorption the playbook §9 names as this project's
most expensive orchestration error.

### 1.3 What already works, and must not be rebuilt

- **The CLI verb.** `verbs.graduate` (`verbs.py:2913`) resolves its path
  with `find_record_path(home, record_id)  # pending OR resolved` and
  runs a host-cleanup phase written specifically for the routed case.
  Verified live in a sandbox, not read off the docstring.
- **The UI's own I/O layer.** `ledger.locate_record` already finds
  resolved records and already reports `RecordLocation.resolved`
  (`ledger.py:216-236`). `routes._gather_detail_bundle` already carries
  a branch for records that "fall out of `list --json` (pending-only)"
  (`routes.py:306-322`) and builds a complete `DetailReadBundle` for a
  routed record. `models.build_detail_model` consumes it without raising.
- **The execution half.** POSTing `verb=graduate` to
  `/record/<routed-id>/action/arm` then `…/action/confirm` returns
  `200`/`200` today and dispatches `["graduate", "<id>", "--json"]`.
  No new POST route is needed. **The arm/confirm pair never checks
  record status** — only the GET does.

### 1.4 The blocking line

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
everywhere else in this document. No later section re-enumerates one.**
(`commit-drift-evidence-spec.md` §7 finding 6: a re-enumerated set is
how a hand-maintained list drifts from the set that exists.)

### 2.1 `VIEWABLE` — what the Detail page renders

> **`VIEWABLE` = every record `ledger.locate_record` finds and
> `ledger.read_record` parses, whatever its `status`.**

The status test at `routes.py:570` is **deleted**, not widened. A record
is viewable iff the ledger can produce it.

Rationale. A status allow-list is the drift shape this corpus keeps
paying for. And the thing that must be gated is the *action*, not the
*view*: reading a rejected or graduated lesson is useful and harmless;
acting on one is not. Gating the action (§2.3) is strictly safer,
because the action gate also covers paths a page gate never touched.

**Consequence — deliberate, not incidental.** `NOTICE_RESOLVED_ELSEWHERE`
stops being emitted by `detail_page`. Its intent (09 §11 P1-9c: a
concurrent CLI session resolved this record; do not let the human act on
it) is preserved and better served — the human stays on the record and
sees what happened to it, with no resolution actions offered. A teleport
with no receipt is the W3-F1 defect class this project fixed six days
ago. **The proposal-slot clear on that path is kept, and its ordering is
now load-bearing** (criterion 4(b)).

**This changes a contract that five existing tests pin.** They are
enumerated and re-contracted in criterion 11 — not worked around.

### 2.2 `INDEX-SET` — what the index lists

> **`INDEX-SET` = exactly the records in `report --json`'s
> `routed_live` array, i.e. `status == "routed"`, taken verbatim from
> the CLI. The UI never re-derives this set.**

Excluded, each with its reason:

- **`superseded` (includes graduated).** Terminal. `report --json`
  exposes graduated records as an integer (`graduated`), never as ids
  (`report.py:348-357`), so listing them would need a new CLI read
  surface (§7). And a graduated record leaves `INDEX-SET` the moment it
  is graduated — this unit's structural answer to "do not offer the
  action twice" (§2.4).
- **`rejected`.** Also count-only in `report --json`. And the verb is
  wrong for it: measured, `graduate` on a rejected record **succeeds**
  and silently rewrites a denied lesson to `superseded_by: canon`.
  Logged as **FW-51**; see §6.5. Listing rejected records here would put
  that one keystroke away.
- **`deferred`.** Already reachable — Front and Bucket both read
  `list --json --include-deferred` (`routes.py:409, 444`) and
  `/record/<deferred-id>` already returns 200 (pinned today by
  `test_resolution_evidence.py::…::test_a_deferred_record_still_resolves_at_record_id`).
- **`pending`.** The queue. That is the rest of the app.

The single reason covering all four: `routed_live` is the *only*
resolved-record set the existing CLI read verbs enumerate **with ids**,
and this unit is UI-only by scheduling constraint (§7).

### 2.3 `RESOLVED-VERBS` — what is offered on a viewed resolved record

> **`RESOLVED-VERBS` = `{graduate}`, offered if and only if the record's
> `status == "routed"`.**

Everything else is refused, each for a stated reason:

- `route` / `reject` / `defer` — already resolved; the CLI would refuse
  or corrupt.
- `cycle destination` — there is no proposal to re-aim.
- `iterate` (the agent pane) — a resolved record is substance-frozen
  (`Record.substance_frozen`, `records.py:355-361`), so the pane agent's
  edits would be refused. Rendering the control offers a failure.
- `confirm-recurrence` / `tolerate` — already have a surface (§1.2).
  Their being dark is `U-recur`'s defect, not this unit's.
- `followup done`, `link contradicts` — already have surfaces.
- **revise / escalate** (the review skill's other two "not holding"
  outcomes) — these author a *new* record via `teach --supersedes`;
  session work, not a button. `action_bar.html` already says so in the
  holding branch, verbatim: *"Revise / Escalate: capture with
  `teach --supersedes` (session work)."*

The user asked for `graduate`. `graduate` is what ships.

### 2.4 The already-graduated rule — three doors, not two

`graduate` on an already-graduated record raises
`HalfWrittenError: git commit … failed: nothing to commit, working tree
clean` (measured) — an alarming, half-written-sounding error for a
benign double-tap. The surface must never produce it. Three independent
guards, because there are three doors:

1. **Structural (index).** `graduate` moves a record from `routed` to
   `superseded`, so it leaves `INDEX-SET` by construction. Verified:
   after graduating every routed record in a sandbox,
   `routed_live == []`.
2. **Per-GET (Detail page).** The Detail render independently re-checks
   `record.status == "routed"`, because a `VIEWABLE` record is reachable
   without the index (bookmark, stale tab, a link from elsewhere).
3. **Post-confirm (the response body).** `action_confirm`'s success leg
   re-renders `action_bar.html` through `_unarmed_context`, which
   **carries no record status at all** (`routes.py:951-1010`), so a new
   `{% elif kind == "resolved" %}` branch in the unarmed chain would
   render unconditionally on that round-trip — re-offering Graduate on
   the record that was just graduated, one click from the
   `HalfWrittenError`. The pending quad is immune only because of
   `{% if not evidence %}` at `action_bar.html:166`. **The resolved
   branch carries the same guard.** Doors 1 and 2 are both GET-side and
   neither closes this one.

---

## 3. Acceptance criteria

### 3.0 Fixture preamble — which state each criterion needs, and how it is minted

`support.resolve_record_directly` (`support.py:176-205`) writes `status`
and, for `routed`, a routing block. **It never writes `superseded_by`**,
so it cannot mint a graduated record: a `superseded` record with
`superseded_by: None` is a record replaced by a successor, not one
graduated into canon, and `report.gather` counts the two differently
(`report.py:352-357`). Criteria 2 and 7 both need `superseded_by:
canon` specifically; against a `None` record criterion 7 would be
vacuous and §2.2's `INDEX-SET` rationale would not be the thing under
test.

**Do not extend the shared helper** — it is shared with the concurrent
wave. Mint the state in-test:

| State needed by | How to build it |
|---|---|
| `routed` (criteria 1-8, 10-11, 13-14) | `resolve_record_directly(..., status="routed")` — unchanged |
| `rejected` (criteria 2, 5, 7) | `resolve_record_directly(..., status="rejected")` |
| **graduated** (criteria 2, 5, 7) | `resolve_record_directly(..., status="superseded")`, then re-read the file at `<bucket>/resolved/<id>.md`, call `Record.set_superseded_by("canon")` (`records.py:449-457` — verified to accept `"canon"` in every status) and re-`write()` it |
| `pending` (criteria 2, 5) | `seed_record` — unchanged |
| `deferred` (criterion 5) | `defer_record` — as `test_resolution_evidence.py` already does |
| cross-scope name collision (criterion 3(b)) | `make_env(tmp_path, skills=("user",))` — see criterion 3 |

Tests live in a new `plugins/self-learn/ui/tests/test_resolved_surface.py`
except where a criterion names an incumbent file.

**Every visibility assertion below is paired with an exclusion
assertion, and every absence assertion is paired with a presence
assertion, in the same criterion.** A test that a record IS listed
passes against a view that lists everything; a test that a control is
absent passes against a blank page. Neither is worth anything alone.

---

1. **The link-walk — the reachability control.** Starting from `/` and
   following only hrefs actually present in the returned HTML, a routed
   record's Detail page is reached: `GET /` → the bucket link → the
   bucket page → an `<a href="/record/<routed-id>">` → `GET` it →
   `200`. **No URL is hand-constructed after the first `GET "/"`.**
   Its discriminator is **M18**; if M18 survives, this test is
   constructing a URL somewhere and the unit can ship unreachable and
   green.

2. **The index lists `INDEX-SET` and nothing else.** Four records in one
   bucket — `pending`, `routed`, `rejected`, graduated (per §3.0) — the
   archive section contains the routed id and **does not contain** the
   pending, rejected, or graduated ids; its summary count reads `1`.

3. **The index does not cross buckets.** Two legs:
   (a) two buckets with different names — a routed record in bucket A
   does not appear in bucket B's section, and vice versa;
   (b) **the name collision, which is constructible in exactly one
   shape.** `make_env(tmp_path, skills=("user",))` yields buckets
   `("skill", "user")` and `("user", "user")` — `discover_buckets`
   names the user bucket by the literal constant `"user"`
   (`ledger.py`), while a skill bucket is named by its directory. Seed
   one routed record in each. `/bucket/skill/user`'s section must show
   only the skill one and `/bucket/user/user`'s only the user one.
   *Measured against a name-only filter: both records appear in both
   sections.* Guarded by **M2**.
   *(A project bucket can never collide: `slug_for` names it
   `<resolved-path-with-/-as-->-<sha8>`, always leading with `-`. The
   skill-named-`user` case is the whole collision space, not an
   example.)*

4. **Row honesty, slot hygiene, and selection hygiene.** Four legs:
   (a) **Y-9** — an archive row's link text is the record's leading
   text, not its id: a record whose Trigger reads *"About to edit
   .storage while HA is running."* renders that string, and the id is
   not the anchor's text. Assert this against the **anchor element
   specifically**, not the row and not the page: the row deliberately
   carries the id in its own `.record-row-id` span (§4), exactly as the
   pending rows do, so a row-scoped or page-scoped "id absent"
   assertion is wrong here. Guarded by **M4**.
   (b) **the slot clear, and its ordering** — `GET /record/<routed-id>`
   with a proposal slot held for that record returns `200`, the slot is
   cleared (the behaviour `routes.py:576-577` performed on the deleted
   redirect path), **and no proposal bar appears in the rendered body**.
   The clear must run *before* the render context reads `slot.current`,
   or a waiting proposal bar renders on a resolved record. Guarded by
   **M9** (clear deleted) and **M19** (clear moved after the context
   build). *This criterion is the incumbent
   `test_proposals.py::TestProposalRoutes::test_resolved_elsewhere_clears_slot_on_detail_render`
   updated in place (criterion 11) — not a new test.*
   (c) **no `data-row` on archive rows.** `app.js`'s `rows()`
   (`static/app.js:80-82`) is an unfiltered
   `querySelectorAll("#self-learn-ui-content [data-row]")` with no
   visibility check, and a closed `<details>`'s children are still in
   the DOM — so a `data-row` archive row would let `s` walk the
   selection into rows the human cannot see and `d` navigate to one.
   All seven existing `data-row` sites are top-level; there is no
   precedent, and fixing `rows()` means editing `static/app.js`, which
   §7 does not list. Assert **both halves**: the archive section
   contains no `data-row` attribute, **and** the pending record rows
   still do (so the assertion is not passing against a page with no
   rows at all). The archive stays reachable by mouse and by Tab —
   `<summary>` is natively focusable — and the `w`/`s` walk stops at
   the last pending row exactly as it does today. Guarded by **M14**.

5. **`VIEWABLE` renders every status.** `GET /record/<id>` returns `200`
   for `routed`, `rejected`, graduated, `pending` and `deferred`, and
   the body carries that record's own Trigger text in each case — not
   merely a `200` on an empty page. This criterion's presence assertions
   are the control for the absence assertions in 6 and 7.

6. **`RESOLVED-VERBS` is offered, and nothing else is.** On a routed
   record's Detail page: exactly one `data-key-action="graduate"`
   element, and **none** of `data-key-action="route"`, `"reject"`,
   `"defer"`, `"iterate"`. For cycle-destination assert the absence of
   **both** `data-key-action="cycle_destination"` **and**
   `data-noop-action="cycle_destination"` — `action_bar.html`'s
   singleton-cycle branch (F5-1) renders the control under
   `data-noop-action` only, so a `data-key-action`-only assertion passes
   vacuously for any user-scope record. Guarded by **M5** and **M7**.

7. **The action is not offered twice (GET side).** On a graduated
   record's Detail page and on a rejected record's Detail page there is
   **no** `data-key-action="graduate"` element — while the page returns
   `200` and carries the record's Trigger text (criterion 5's control,
   re-used so this is not an everything-is-absent pass). Guarded by
   **M6**.

8. **End to end: the verb runs, the receipt renders, and the control
   does not come back.** Three legs, all from a routed record's Detail
   page:
   (a) **argv, with nothing hand-written.** Parse the `hx-vals` (and
   `hx-post` target) **off the rendered Graduate control** and POST
   exactly those values to arm, then confirm. Assert
   `runner.calls == [["graduate", "<id>", "--json"]]`. No verb or kind
   string is written literally in the test — otherwise the test
   hand-constructs the thing it claims to guard and a template mutation
   changes nothing it observes. *(`FakeRunner.run` ignores argv
   entirely, `runner.py:148-152`, so a test that does not assert the
   argv also passes on a build that never sends `--json` — the
   `commit-drift` blocker, one layer over.)* Guarded by **M8**.
   (b) **envelope-sourced evidence.** The confirm response renders the
   evidence leg carrying the `canon_path` and 7-char `host_commit_sha`
   **from the queued envelope**. *Envelope-sourced, not URL-sourced:*
   `_evidence_ctx` sets `record_id` from the URL path parameter
   (`routes.py:1104`), so "the evidence names this record's id" is true
   on every reachable build including broken ones (`lrn-ea833a5b`).
   Guarded by **M10**.
   (c) **no re-offer** (§2.4 door 3). The same confirm response contains
   **no** `data-key-action="graduate"`. Its control is leg (b)'s
   `canon_path` assertion on that same response — so the absence is not
   passing against an empty body. Guarded by **M13**.

9. **The fossil comment is corrected.** `_evidence_ctx`'s comment at
   `routes.py:1108-1121` (the block immediately above `record_url` at
   `:1122`) justifies `record_url = None` for `route`/`reject`/
   `graduate` on the grounds that *"`record_detail`'s GET redirects
   (`record.status not in ("pending", "deferred")`)"*. After this unit
   that sentence is **false**. The behaviour is unchanged (§6.2) and the
   comment must be rewritten to state the surviving reason. Asserted as
   a source-text check: the redirect rationale no longer appears.
   *(`commit-drift-evidence-spec.md` §1: "a fossil rationale reads
   exactly like a live one.")* Guarded by **M11**.

10. **Both proposal-slot staleness guards survive — one leg each.**
    `routes.py:1253` and `routes.py:2117` carry the *same textual
    predicate* `record.status not in ("pending", "deferred")`, and a
    builder deleting the `:570` predicate by search-and-replace would
    take them too. They live in different functions and need different
    scenarios:
    (a) **`:1253`, `_sweep_stale_proposal`** — reached after a verb this
    server executed. Hold a slot on record X, execute a bulk/collapse
    verb that resolves X, assert the slot is cleared.
    (b) **`:2117`, `proposal_arm`** — *not* `proposal_confirm`, which
    has **no status predicate at all** (r1 named the wrong function, so
    its scenario never exercised `:2117`). Hold a slot on record X,
    resolve X by direct ledger mutation (no verb), POST `/proposal/arm`,
    assert the `proposal_gone` response and a cleared slot. This is the
    shape `test_proposals.py::test_stale_arm_after_external_resolution_renders_gone`
    already uses.
    Guarded by **M12** (a) and **M15** (b).

11. **The five incumbent tests that pin the old contract are updated in
    place.** The contract is changing deliberately; all five are named
    here with their new contract. Do not delete, do not add siblings,
    do not duplicate them in the new file.

    | Test | New contract |
    |---|---|
    | `test_routes.py::TestDetailPage::test_resolved_elsewhere_redirects_to_bucket_with_banner` (`:761`) | `200`, the resolved-state render; renamed to say so. No 303, no banner. |
    | `test_routes.py::TestNextRecordPrefetch::test_never_stale_an_externally_resolved_record_is_never_served_from_cache` (`:2958`) | see below — replacement observable |
    | `test_proposals.py::TestProposalRoutes::test_resolved_elsewhere_clears_slot_on_detail_render` (`:749`) | **this is criterion 4(b)'s exact behaviour** — update the incumbent to `200` + slot cleared + no proposal bar |
    | `test_degradation_walk.py::TestBulkGraduateResumeIdempotency::test_already_resolved_id_vanishes_from_the_bulk_collapse_group` (`:310`) | see below — group-scoped |
    | `test_resolution_evidence.py::TestResolvedRecordRedirectsAwayFromItsOwnDetailPage::test_a_routed_record_no_longer_resolves_at_record_id` (class `:391`, test `:396-404`) | `200` + the resolved render. The class name and the block comment at `:375-389` both describe the redirect as the reason the `v` button is suppressed; that reason changes and the prose must change with it. **The `v`-button behaviour itself does not change** (§6.2). |

    **The cache-staleness test needs a replacement observable, and it
    must not be weakened to "returns 200".** The 303 was that test's
    only observable for a genuinely orthogonal contract: a record
    resolved externally is never served from the prefetch cache. Use
    instead: the response must render the **resolved** state — assert
    `data-key-action="route"` is **absent** and
    `data-key-action="graduate"` is **present**. This bites exactly
    where the 303 did, because a stale bundle holds the record object as
    it was while `pending`, which renders the pending quad *including*
    `route`. Weakening to `200` would not: a stale pending render is
    also a `200`. Criterion 5's presence assertion is this leg's
    control.

    **The bulk-collapse assertion is rewritten group-scoped, not
    page-scoped.** It currently asserts `first not in r.text` for
    `GET /bucket/skill/s`, which B1 makes false by design — the archive
    section renders `<a href="/record/{first}">`. The contract that
    matters is *"the id vanishes from the bulk-collapse group"*. Anchor
    it on the group's own markup: extract the `.bulk-collapse-row`
    form's `<input type="hidden" name="ids">` value (`bucket.html:69`)
    and assert `first` is not among the comma-separated ids, while
    `ids[1]` and `ids[2]` are. Note the pending rows already print raw
    ids in `.record-row-id` (`bucket.html:82`), so a page-scoped absence
    assertion was always only true because the record had left
    `pending/`.

12. **Suite baseline.** `cd plugins/self-learn/ui && uv run pytest -q`
    with `XDG_CACHE_HOME` redirected: no new failures against the
    2026-07-28 baseline (1010 passed / 77 skipped / 1 known
    `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`).
    The five tests in criterion 11 are **updated**, so they are not new
    failures; any other change is. If a test lands in a browser/js
    module, **report the collected/passed count** — `test_js_dom.py:87`
    is an `importorskip` and a skipped module is not a red test.

13. **The title fix is guarded.** `routes.py:320` hardcodes
    `"title": models.leading_text(None, [], "")` → `"(untitled)"` for
    exactly the records this unit makes viewable, and that flows into
    `FindingRegion.title` (`models.py:1442` → `_build_finding`). Set it
    from `ledger_ops.record_title(record)`; the resolved template
    renders `model.finding.title` as its heading. Assert the heading
    carries the record's Trigger text. **State the empty case:**
    `record_title` returns `""` (not `"(untitled)"`) when the section is
    absent (`ledger_ops.py`), and `_build_finding`'s own
    `title or "(untitled)"` supplies the fallback — assert that leg too,
    with a record whose Trigger section is missing. Without this
    criterion the heading can revert to `(untitled)` with the suite
    green. Guarded by **M16**.

14. **The distinct `page_kind` is guarded, and `g` is advertised there.**
    `.keymap-footer-entry` defaults to `display: none`
    (`style.css:311-313`): every entry is in the markup on every page
    and only CSS decides which are visible. So this criterion has one
    markup leg and one stylesheet leg, both assertable in the fast
    suite. **Neither goes in `test_js_dom.py`** — it is
    `importorskip`-gated (`:87`) and skips wherever Playwright or
    Chromium is absent, the fail-open shape criterion 12 warns about.
    (a) **Markup.** A resolved record's page renders
    `<body data-page="…">` with a value that is neither `detail` nor
    empty. (Measured: a pending Detail page renders
    `data-page="detail"`.) Guarded by **M17**.
    (b) **Stylesheet.** `style.css` contains a
    `body[data-page="<the new kind>"]` rule selecting
    `.keymap-footer-entry[data-action="graduate"]`, **and contains no**
    `body[data-page="<the new kind>"]` rule selecting
    `.keymap-footer-entry[data-context="detail"]`. Assert both halves.
    The first is necessary because `style.css:319-322` enumerates only
    `front`/`bucket`/`detail` — a new kind matches nothing, so `g` would
    be bound on the page and advertised nowhere (the dead-key defect).
    The second is the W2-F1 half: one `data-context="detail"` rule
    lights `e`/`x`/`f`/`o`/`i`. Criterion 6 already pins that those five
    controls are absent from the page, so together the two criteria pin
    *advertised iff present*. Guarded by **M20**.

### 3.1 Mutation plan

Each row is a **one-line edit to production code** that must make
**exactly** the named criterion fail. The code gate will run every one
and is invited to invent more.

| # | Mutation | Criterion that must fail |
|---|---|---|
| M1 | In `detail_page`, restore `if record.status not in ("pending","deferred"): return RedirectResponse(...)` | 1, 4(b), 5, 6, 7 — **a smoke check, not a discriminator** (see below) |
| M2 | In the index builder, drop the scope confirmation; filter `routed_live` on `bucket` name alone | 3(b) |
| M3 | In the index builder, replace the `routed_live` source with a walk of **this bucket's own** `resolved/` directory | 2 |
| M4 | In the index row builder, return `record.id` instead of the record's leading text | 4(a) |
| M5 | In the resolved Detail render, pass the pending action-bar `kind` instead of `"resolved"` | 6 |
| M6 | Delete the `record.status == "routed"` condition guarding the Graduate control | 7 |
| M7 | In the resolved template, restore the `detail-right` pane column include | 6 (the `iterate` half) |
| M8 | Change the resolved Graduate control's `hx-vals` verb from `graduate` to `reject` | 8(a) |
| M9 | Delete the `slot.clear_for_record(record_id)` call on the resolved-render path | 4(b) |
| M10 | In `_evidence_ctx`, replace `envelope = run_result.evidence` with `envelope = None` (`routes.py:1101`) | 8(b) |
| M11 | Restore the old comment text at `routes.py:1108-1121` | 9 |
| M12 | Change `record.status not in ("pending","deferred")` at `routes.py:1253` to `record is None` | 10(a) |
| M13 | Drop the `{% if not evidence %}` guard from the `kind == "resolved"` branch in `action_bar.html` | 8(c) |
| M14 | Add `data-row` to the archive row element | 4(c) |
| M15 | Change `record.status not in ("pending","deferred")` at `routes.py:2117` to `record is None` | 10(b) |
| M16 | In `_gather_detail_bundle`, restore `"title": models.leading_text(None, [], "")` | 13 |
| M17 | Emit `{% block page_kind %}detail{% endblock %}` in the resolved template | 14 |
| M18 | Render the archive row's leading text as plain text — drop the `<a href>`, keep everything else | **1 only** |
| M19 | Move the `slot.clear_for_record` call to *after* the render context is built | 4(b) |
| M20 | Change the resolved page's `style.css` footer rule from `[data-action="graduate"]` to `[data-context="detail"]` | 14(b) |

**M1 is a smoke check, not a discriminator.** It takes down five
criteria at once, which tells you the guard is load-bearing and nothing
about which criterion covers what. The discriminating mutations are
M2-M19; a reviewer whose only red is M1 has verified almost nothing.

**M18 is the mutation the whole unit turns on.** Nothing else in this
plan reproduces the defect being fixed: *text on screen with no path to
it.* M4 changes the anchor's **text**; only M18 removes the **anchor**.
This is the rules-variant / dead-destination shape from the r2 audit,
and criterion 1 is the only thing that can see it.

**M18 must redden criterion 1 and nothing else.** If the code gate sees
M18 also reddening criterion 2 or 3, the archive row is missing its
`.record-row-id` span (§4) and those criteria are keying off the
anchor's `href` — fix the row, not the criteria.

**M3 is the positive control for criterion 2.** A test asserting "the
routed record is listed" passes against an index that lists every
resolved record — which is what M3 produces. Only the paired exclusion
assertions (rejected + graduated absent) kill it. M3 is scoped to *this
bucket's own* `resolved/` dir precisely so it does not also fail
criterion 3 and read as a discriminator for two things at once.

**M6/M7/M13/M14 all target absence assertions.** Absence passes against
a blank page. Criteria 6, 7, 8(c) and 4(c) each therefore carry a
presence assertion in the same test — that presence half is the positive
control. A criterion that only asserts absences is the
`test_cleared_bucket_omits_next_pending_link` failure
(`commit-drift-evidence-spec.md` §7 finding 2), which stayed green with
the entire feature deleted.

---

## 4. Where the index lives — **B1, ratified**

**Decided by the user, 2026-08-02.** r1 offered three hosts; the fork is
closed and no substitution section remains.

Beneath the pending destination groups on the Bucket page, a
default-collapsed `<details>`:

```
▸ Routed here (7)
```

expanding to rows shaped like the page's existing record rows
(`bucket.html:76-84`) — `<a href="/record/{id}">{leading text}</a>`, a
`<span class="record-row-id">{id}</span>` exactly as the pending rows
already carry (`bucket.html:82`), and plain-words facts (routed N days
ago → destination; recurrences if any) — but **without `data-row`**
(criterion 4(c)).

**The id span is load-bearing, not decoration.** Criteria 2 and 3
assert presence and absence *by id*. If the id lives only in the
anchor's `href`, then M18 — which removes the anchor — also removes the
id from the section, and M18 reddens criteria 1, 2 and 3 instead of
criterion 1 alone. The id span makes 2 and 3 anchor-independent, so M18
reduces to exactly what it claims to be: the lesson is on screen and
there is no path to it.

Why B1 was recommended and chosen:

1. **The data needs no CLI change.** `report --json` already returns
   every routed record's id and bucket; the Bucket page already knows
   its own scope and name.
2. **It is where the user already looks.** A bucket page is "this
   skill's lessons". Approved lessons belong under the pending ones, not
   behind new navigation the user has to discover — which is the
   discoverability half of the bug report.
3. **Zero new routes, zero new keys, zero new navigation.** Collapsed
   `<details>` is the app's established pattern for secondary content
   (episode brief, near-misses, raw proposal YAML).

Recorded for posterity, not for reopening: a dedicated `/resolved` route
was the runner-up (cleanest separation, but needs a front-page link the
user must find); a `/report` section was cheapest (but fights that
page's read-only-verbatim contract and is the least-visited page); and a
filter/toggle on the pending queue was rejected outright, because a
resolved record has no proposal — the siblings are deleted at resolution
by `remove_proposal_siblings` — so it has no destination group, no card
sections and no freshness, and getting one into that list means either
editing `list --json` in `ledger_ops.py` (a live collision with
`U-schema`) or re-deriving the CLI's computed list shape in the UI,
which 09 §3's two-read-path pin forbids. **B1 is not that**: it adds a
second section and leaves the queue list untouched.

Making `/record/<id>` render resolved records is **not an alternative to
the index** — it is a prerequisite (§2.1, criterion 5). Shipping it
alone would answer "can the app address a resolved record" while leaving
the user's actual sentence untouched.

---

## 5. Builder decisions, made here rather than left open

- **The action lives on the Detail page, never on index rows.**
  `app.js`'s `clickAction` is
  `document.querySelector('[data-key-action="' + action + '"]')`
  (`static/app.js:54-55`) — **first match in document order, with no
  awareness of which row is selected.** N rows each carrying a Graduate
  button would make `g` always fire row 1, silently retiring the wrong
  lesson. The Detail page renders exactly one record, so `g` is
  unambiguous. *(The Bucket page already has the N-row shape and
  therefore already has this hazard; fixing it is out of scope, §6.3,
  but no new surface may add to it.)*

- **No new keymap entries.** `KeymapEntry(("g",), "graduate", …)`
  already exists and the resolved Detail page renders exactly one
  `data-key-action="graduate"` target. Free letters are `h k l m z`;
  this unit consumes none. The keymap-uniqueness test is untouched.

- **A separate template, `templates/detail_resolved.html`.** Precedent:
  `detail_degraded.html` is already a second Detail template for a
  non-ordinary record state. The resolved view renders no proposal
  cards, no Change region, no destination cycle, no pane column, and a
  different action bar; branching a template that large invites a stale
  `{% if %}`. It carries its own `page_kind` (criterion 14) and renders
  `model.finding.title` as its heading (criterion 13), plus the record
  body, the routing facts (`record.routing`, `recurrences`,
  `last_confirmed`, `resolution_note`, `follow_up`) and one action bar.

- **A new action-bar `kind`: `"resolved"`**, added as one more branch in
  `action_bar.html`'s unarmed `{% elif kind == … %}` chain, **inside a
  `{% if not evidence %}` guard** (§2.4 door 3). The **armed** branch is
  kind-agnostic and reused verbatim — arm-then-confirm, `Enter`
  confirms, any other key cancels, unchanged.

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

- **Filter by name, then confirm scope.** Necessary, not defensive —
  measured. `routed_live` rows carry `bucket` (name) and no scope
  (`report.py:279-289`). The collision space is exactly one shape: a
  skill directory named `user` versus the user bucket, which
  `discover_buckets` names by the literal constant `"user"`. A project
  bucket cannot collide (`slug_for` = path-with-dashes + sha8, always
  leading `-`). Filter on name (cheap, over-broad), then confirm each
  survivor's `(scope, bucket_name)` via `ledger.locate_record`. O(k),
  not O(all routed).

- **On the real ledger this is 31 rows.** Measured 2026-08-02 (file
  counts only — no verb run against `~/.self-learn`): 35 pending, 54
  resolved, of which **31 routed**, 22 superseded (19 `superseded_by:
  canon`), 1 rejected.

---

## 6. Out of scope — named so a reviewer does not read them as gaps

1. **`U-recur` / the dark holding surface.** Zero `recurrence-suspect`
   events have ever been emitted (§1.2, verified). Fixing the emitter is
   `U-recur` (`miner.py`). This unit neither depends on it nor
   duplicates it.
2. **`_evidence_ctx`'s `record_url` suppression and the `v` button.**
   After this unit the post-`route`/-`graduate` evidence leg *could*
   honestly offer "View the record". Changing it is a behaviour change
   to a surface shipped six days ago; **only the comment is corrected**
   (criterion 9).
3. **`clickAction`'s first-match dispatch on multi-row pages**, and
   `rows()`'s lack of a visibility filter. Both are real, pre-existing
   defects in `static/app.js`. Neither is created nor fixed here; both
   are worked *around* (§5, criterion 4(c)).
4. **`watch_paths` does not watch `resolved/`** (`ledger.py:422-431`).
   An in-app graduate refreshes the index (`_force_refresh` runs after
   every verb); a graduate by an external CLI session does not push a
   refresh, and the 10 s client poll catches it. Watching `resolved/`
   would make every autosync touch of the archive wake every client.
   Known limitation, deliberately unfixed.
5. **`graduate` succeeds on a `rejected` record** — silently rewriting a
   denied lesson to `superseded_by: canon`, unguarded in the CLI
   (measured, §8). **Registered as FW-51 in `14-forward-work-map.md`;
   user ruling 2026-08-02: log it, fix after the wave.** Report-not-fix
   posture retained: it is CLI-side, it collides with the concurrent
   wave, and it is unreachable through this unit's surface (§2.2/§2.3).
   The `HalfWrittenError` on a double-graduate rides with it.
6. **Front-page bucket rows do not show a routed count.** A second
   surface with a second set of counts.

---

## 7. Scheduling: **no CLI change is needed**

This unit is **UI-only**. Files touched:

```
plugins/self-learn/ui/src/self_learn_ui/routes.py
plugins/self-learn/ui/src/self_learn_ui/models.py
plugins/self-learn/ui/src/self_learn_ui/ledger.py        (only if a helper is added)
plugins/self-learn/ui/templates/bucket.html              (the B1 section)
plugins/self-learn/ui/templates/detail_resolved.html     (new)
plugins/self-learn/ui/templates/partials/action_bar.html
plugins/self-learn/ui/static/style.css                   (criterion 14(b) — a REQUIRED edit, not incidental)
plugins/self-learn/ui/tests/test_resolved_surface.py     (new)
plugins/self-learn/ui/tests/test_routes.py               (criterion 11 — two classes)
plugins/self-learn/ui/tests/test_proposals.py            (criterion 11 / 4(b))
plugins/self-learn/ui/tests/test_degradation_walk.py     (criterion 11)
plugins/self-learn/ui/tests/test_resolution_evidence.py  (criterion 11)
```

None of `worker.py`, `analyst.py`, `ledger_ops.py`, `selfcheck.py`,
`telemetry.py`, `verbs.py`, `miner.py` is touched. No collision with the
five concurrent CLI units. **`static/app.js` is deliberately absent** —
criterion 4(c) exists so this stays true.

**`static/style.css` is a required edit, not a cosmetic one.** Every
keymap footer entry is `display: none` by default (`style.css:311-313`)
and `:319-322` enumerates only `front`/`bucket`/`detail`, so a new
`data-page` value matches no rule at all: without the stylesheet edge
criterion 14(b) pins, `g` would be bound on the resolved page and
advertised nowhere. The file is in this unit's set for that reason.

**B1 adds a new subprocess read to the Bucket page.** Stated plainly
because r1 implied otherwise: `bucket_page` today calls
`ledger.list_items` (`:444`) and `ledger.status` (`:464`) and **does
not** call `ledger.report` — the only `report --json` call sites are
`front()` (`:411`) and `report_page()` (`:891`). B1 adds a third
subprocess per bucket-page load. Accepted: it matches the front page's
existing four-subprocess budget, and `report.gather` walks 89 record
files on the real ledger.

**The read surfaces were enumerated before concluding no CLI change is
needed:**

| Existing CLI read | Enumerates resolved records? |
|---|---|
| `list --json` (`ledger_ops.list_items:1108`) | **No** — iterates `queue(bucket, …)`, pending only. `--include-deferred` widens to deferred, which still lives in `pending/`. `--id` filters the same pending set. |
| `status --json` (`status_infos`) | **No** — per-bucket pending counts only. |
| `report --json` (`report.gather:230`) | **Yes, partly.** `routed_live[]` = every `status: routed` record with `{id, bucket, routed_days_ago, last_confirmed, recurrences}`. `open_followups[]` and `recurrence_suspects[]` also carry resolved ids. `graduated`/`rejected` are **integers only** — no ids. `buckets[].counts` gives per-status counts per bucket. |
| `mine status --json` | No. |

`routed_live` is sufficient for `INDEX-SET` and is why `INDEX-SET` is
defined as it is (§2.2). Widening to graduated or rejected records
**would** need a new CLI read path — `report.gather`'s return map in
`plugins/self-learn/cli/src/self_learn/report.py` (adding
`graduated_live`/`rejected_live` beside `routed_live`, ~10 lines, no
shared-function edit). That file is **not** in the concurrent wave's
file set, so it is schedulable — but it is not needed here.

---

## 8. Empirical basis

All measurements 2026-08-02 in a throwaway sandbox (`support.make_env`
under `/tmp`, all five env vars redirected). **No mutating verb ran
against `~/.self-learn`; the only contact with the real ledger was
`find`/`grep` over its files.**

1. `graduate` on a genuinely **routed** record → succeeds; ends
   `resolved/`, `status: superseded`, `superseded_by: canon`.
2. `graduate` on an **already-graduated** record → raises
   `HalfWrittenError: git commit … failed: … nothing to commit, working
   tree clean`.
3. `graduate` on a **rejected** record → **succeeds**, silently
   rewriting a denied lesson to `superseded_by: canon`. Unguarded in the
   CLI → **FW-51**.
4. After graduating them all, `report.gather(...)["routed_live"] == []`.
5. `GET /record/<routed-id>` → `303`, `location:
   /bucket/skill/s?notice=resolved-elsewhere`.
6. `GET /` and `GET /bucket/skill/s` → the routed id appears in neither;
   the "Is it holding?" section does not render.
7. `GET /report` → the routed id appears as inert `<td>` text;
   `/record/<id>` appears nowhere in the page; the record's own Trigger
   text appears nowhere in the page.
8. `POST /record/<routed-id>/action/arm` (`verb=graduate,
   kind=holding`, `HX-Request: true`) → `200`, Graduate rendered;
   `…/action/confirm` → `200`,
   `runner.calls == [["graduate", "lrn-bbbb0002", "--json"]]`.
9. `_gather_detail_bundle` + `models.build_detail_model` on a routed
   record → succeed; `finding.title == "(untitled)"` (the criterion-13
   defect); `change.kind == "none"`;
   `record_title(record) == "ROUTED trigger about the printer."`
10. **The cross-scope bucket-name collision is real and one-line
    constructible.** `make_env(tmp_path, skills=("user",))` →
    `discover_buckets` returns `[("skill","user"), ("user","user")]`;
    two routed records, one per bucket, both appear in `routed_live`
    with `bucket == "user"`. A name-only filter returns **both** for
    `/bucket/skill/user` *and* for `/bucket/user/user`; the
    scope-confirmed filter returns exactly one each.
11. `grep -c 'recurrence-suspect'` over both real telemetry files → `0`
    and `0`.
12. Real ledger, file counts only: 35 pending; 54 resolved = 31 routed +
    22 superseded (19 `canon`) + 1 rejected.

## 9. Revision history

- **r1** — **NOT SOUND**: 2 blockers + 14 folds. Blocker 1: five
  existing tests pin the redirect this unit removes; r1 named one, in
  one file, and its criteria 11 and 12 contradicted each other per test.
  Blocker 2: the fixture helper r1 named cannot mint a graduated record
  (`superseded_by` is never written), so two criteria were vacuous. The
  most consequential fold was **FOLD 1** — a third, post-confirm door to
  the `HalfWrittenError` that both of r1's §2.4 defences missed, because
  both were GET-side.
- **r2** — this document. Fork closed to B1 (user, 2026-08-02);
  rejected-record defect routed to FW-51 (user, 2026-08-02). §1.2
  rewritten: the r1 framing (and the briefing behind it) understated the
  defect — Graduate renders daily from three sites and can reach a
  routed record from none of them. Criteria grew 12 → 14, mutations
  12 → 19; M18 added as the only mutation that reproduces the defect
  the unit exists to fix.
- **r3** — this document. Both r2 blockers confirmed resolved and every
  r2 fold verified; two further folds, no blockers. **FOLD A:** under
  r2's row shape the id appeared only in the anchor's `href`, so M18
  would have reddened criteria 1, 2 and 3 — destroying the claim M18
  exists for, since a code gate could then not tell whether criterion 1
  is a real link-walk. §4 now requires the `.record-row-id` span the
  pending rows already carry (`bucket.html:82`), making 2 and 3
  anchor-independent. **FOLD B:** criterion 14's "is shown" half was not
  assertable at all — every footer entry is `display: none` by default
  (`style.css:311-313`) and only CSS decides visibility, so the only
  mechanism was the `importorskip`-gated browser module criterion 12
  itself warns about. Worse, `style.css:319-322` enumerates only
  `front`/`bucket`/`detail`, so a new `page_kind` matches nothing and
  `g` would be advertised **nowhere** — the dead-key defect, the
  opposite of the W2-F1 defect r2 was guarding. Criterion 14 is now a
  markup leg plus a stylesheet leg, both fast-suite assertable, pinning
  both directions; **M20** added.
