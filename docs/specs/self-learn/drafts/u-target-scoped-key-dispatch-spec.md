# U-target — keyboard dispatch resolves against the row the operator means, and refuses when it cannot

**Status:** SPEC r2, not built. Authored against live `master` at HEAD
`502ca8d`; revised in the worktree `u-target`, whose base has since
advanced to `ee62df0` (the `u-xdist` merge). **Every file this spec cites
by line number is byte-identical across that move** — measured:
`git diff 502ca8d ee62df0 -- static/app.js static/style.css templates/
keymap.py models.py routes.py ledger.py` is empty, with the merge's 11
other changed files as the positive control that the diff can see
anything at all. Every measurement in §2 was taken by this author unless
the row says otherwise.

**Blind spec gate r1: NOT SOUND — 0 blockers, 4 majors, 7 minors.** Every
finding is folded here, and each of the four majors was **re-verified by
this author before folding**, not taken on report:

| finding | what it was | where it landed |
|---|---|---|
| MAJOR-1 | `A2`/`A3`/`A5`'s co-armed fixture is unbuildable — `style.css:433` has blocked the mouse co-arm since 2026-07-17 | §2.7, §4.3, `A1`/`A2`/`A3`/`A5` re-anchored on the cluster-member door (§6.4) |
| MAJOR-2 | `A1`'s stated mutation left it green (measured: one armed bar ⇒ one `disarm` target page-wide) | `A1` rebuilt on the co-armed fixture (§6.4) |
| MAJOR-3 | §2.7(b) re-reported an already-closed finding as new | §2.7 rewritten; §2.8 gains the evidence-discipline row |
| MAJOR-4 | `S1` was scoped to KEYMAP-bound actions, so it never guarded the latent class §3.2 exists for | `S1` widened to **every** `data-key-action` (§6.8) |

Minors 1-7 are folded at §4.2 (the `n` precondition, the other
`clickAction` consumers), §4.5 (`o` is un-armed too), §6.1 (group
assignment), §6.3 (`B4` made mechanically checkable), §6.5 (`D3` gains a
fixture), and §7 (`[B-6]`, the MINOR-6 ruling — §4.2).

**One thing this author got wrong, stated plainly:** §2.7(b) of r1 claimed
a live `Enter`-confirms-a-host-registration hazard. It is **not** live —
a CSS rule shipped 2026-07-17 closed it, and *that rule's own comment
names the review finding I re-reported as new*. I reasoned reachability
of a **state** from document order in the markup without checking whether
anything downstream prevented it. The corrected rule is in §2.8.

**Subject in one sentence.** `clickAction(action)` resolves its target
with a page-wide `document.querySelector`, which returns the first match
in document order; several templates render one action bar *per row*
inside a `{% for %}` loop, so a keystroke silently acts on a record the
operator is not looking at — and on one bucket path it performs an
un-armed, multi-record write.

---

## 0. Reading order and precedence

1. **`03-decisions.md` row `S-20` (F6, human-ratified 2026-07-24).** It
   already rules that two elements sharing a `data-key-action` "would
   resolve ambiguously by document order", and fixed *that* instance by
   renaming the keymap action. Quoted in full in §2.6. Where this spec
   and a decision row disagree, **the row wins**. This unit owes **one
   new row** (§9.1).
2. **`09-surface-spec.md` Y-4 and Y-6** — the design intent that there
   are multiple rows, each independently actionable. Quoted in §2.6.
3. **`plugins/self-learn/ui/static/app.js`** — its own file header
   states the contract this defect violates (§2.6).
4. **`plugins/self-learn/ui/src/self_learn_ui/keymap.py`** — the module
   docstring and the `Context` comment, which state the absence of
   scoping twice, in the project's own words (§2.3).
5. **`misc/reviews-2026-08-29/frontpage-action-targeting.md`** — the
   prior wire-level investigation. It is an **input to this unit, not a
   gate's notes**. Every claim this spec leans on is marked *measured
   here* or *cited* in §2.8.

**Precedence inside this spec.** §6's acceptance criteria are the spec.
Prose is rationale. Where prose and a criterion conflict, the criterion
wins.

---

## 1. Objective, and the non-objectives

**Objective.** Make keyboard dispatch resolve against the row the
operator has selected, and make an unresolvable dispatch a **visible
refusal** rather than a silent first-match. One resolution primitive,
used by every keyboard-driven DOM lookup in `app.js`.

Three moves:

1. **Scope resolution to the selected row**, with a page-wide fallback
   that fires only when there is exactly **one** candidate on the page —
   so today's correct behaviour on single-target pages (Detail, and any
   list with one actionable row) does not regress.
2. **Refuse on multiplicity.** Zero requests, one visible
   `showNoopHint()` line, in plain words. Silently acting on the first
   match is the defect; picking "the nearest" or "the last" would be the
   same defect with better odds.
3. **Make the deferred-fire guard work on all three surfaces**, by
   comparing *what request the resolved element would actually issue*
   (§4.4) instead of a record id that only exists on Detail.

**Non-objectives** — each is a thing a builder or a gate may reach for.

1. **A per-key context filter.** `data-key-context` is declared and read
   by nothing, and wiring it would *break* a live binding — measured,
   §4.6. It is deleted, not wired.
2. **Making the bulk-collapse graduate keyboard-reachable.** §4.5 rules
   it click-only for this unit; an arm-then-confirm step for
   `graduate-bulk` is deferred (§7, `[B-1]`).
3. **Binding a key to `followup_done` or `link_contradicts`.** Both
   render duplicated targets today and neither is bound (§3.2 rows 2 and
   12). The class is closed structurally, so a future binding is safe;
   adding one here is not this unit's business.
4. **Capping the holding / follow-up lists.** There is no cap today.
   Deferred (§7, `[B-3]`).
5. **Selection-follows-arming** (moving `.selected` onto a row whose bar
   an `htmx:afterSettle` just armed). Considered and **rejected**: the
   page-wide-unique fallback already resolves the only case it would fix
   — a bar armed by mouse while the selection is stale elsewhere — and
   it would move selection as a side effect of a server swap, which is
   new state churn for no reachable gain. Recorded here because it is
   the obvious next idea (§4.3).
6. **Changing what `ensureRowSelected()` selects.** On Front it selects
   the first bucket-table row, which owns no action. That is why §4.2's
   page-wide fallback exists. Changing the load-time default is a
   separate taste decision (§7, `[B-5]`).
7. **Touching `routes.py`, `models.py`, or any CLI code.** The blast
   radius of this unit is `static/app.js` plus three template lines
   (§5.1).

---

## 2. What is actually true — measured, with the mutation of each claim

### 2.0 The number that sets this unit's priority

**The `user` bucket holds 14 pending records today.** Measured read-only
against `~/.self-learn` on 2026-08-30 by counting each bucket's `pending/`
directory:

```
  14  user/pending
   2  projects/<a project bucket>/pending
   1  projects/<another project bucket>/pending
   0  … eleven further project buckets
```

*(Positive control: the zero-count buckets printed too, so an empty result
would have been visible as `0` rather than as silence.)*

Surface #2 of §3.1 — Bucket pending record rows, keys `e`/`x`/`f`/`g`/`o`
— is therefore **mis-targeting in production right now, on a 14-row
page**: every one of those keys acts on row 1 regardless of which row the
operator selected. This is not a latent hazard waiting on an
`already_canon` proposal or a merge cluster. It is the busiest page in the
app, wrong on every keystroke, today.

The bulk-collapse row (§2.5) is the most *severe* single instance and the
cluster merge (§2.7) is the most *destructive*, but both currently render
**zero** times on the live ledger. The 14-row bucket is what makes this
unit urgent; the other two are what make it non-negotiable.

### 2.1 The mechanism

`plugins/self-learn/ui/static/app.js:173-176` (read at `502ca8d`):

```js
  function clickAction(action) {
    const selector = '[data-key-action="' + action + '"]';
    const el = document.querySelector(selector);
    if (!el) return false;
```

`document.querySelector` returns the **first element in document order,
page-wide**. Nothing between the keypress and this call narrows the
search to a row, a section, a selection, or a record.

**Every page-wide keyboard lookup in this file** (measured — `grep -n
'document\.querySelector' static/app.js`, and each read in place):

| line | lookup | consequence when duplicated |
|---|---|---|
| 65 | `findArmedBar()` — `.action-bar[data-armed="true"]` | any armed bar page-wide makes the whole page modal, and every key routes to the first one |
| 75 | `currentRecordId()` — `[data-record-id]` | see §2.4 — the attribute exists only on Detail |
| 175 | `clickAction()` dispatch resolution | the defect |
| 206 | `clickAction()`'s **fire-time** re-resolution | a deferred fire re-resolves globally, and a `!live` miss returns **silently** |
| 338 | `focusNote()` — `.action-bar input[name="note"]` | `n` focuses the first row's note field, not the selected row's — **the same defect, not previously reported** |
| 568 | `dispatchOrHint()`'s `[data-noop-hint][data-noop-action]` lookup | the gated-control hint is also first-match |

Lines 347 (`rows()`), 617, 639-663, 694, 1187-1192, 1938, 1974 are
either already scoped, or are not part of key dispatch (SSE scoping, the
sort handler, the reload-defer legs). They are out of scope and
untouched.

### 2.2 The duplicating templates

Measured by reading each template at `502ca8d`:

- `templates/index.html:83-95` — `{% for row in model.holding %}` →
  `partials/action_bar.html` with `kind="holding"`. Each iteration emits
  `tolerate`, `confirm_recurrence`, `graduate`, `dismiss_suspect`.
- `templates/index.html:102-110` — `{% for row in model.followups %}` →
  `action_bar.html` with `kind="followup"` → `followup_done`.
- `templates/bucket.html:75-100` — `{% for row in group.rows %}` →
  `action_bar.html` with `kind="detail"` → `route`, `reject`, `defer`,
  `graduate`, `cycle_destination`, and the note input.
- `templates/bucket.html:65-73` — the bulk-collapse row, rendered
  **before** the record rows in the same `{% for group %}` iteration.
- `templates/partials/cluster_expanded.html:9-23` — `{% for member_id in
  cluster.records %}` → one `data-key-action="route"` button **per
  member**, all inside the single `.cluster-row[data-row]` at
  `bucket.html:49`.
- `templates/partials/contradicts_offer.html:35-42` — `{% for edge in
  edges %}` → `action_bar.html` with `kind="contradicts"` →
  `link_contradicts` per edge.

### 2.3 There is no scoping — the project says so, twice

`keymap.py`, the `Context` type comment (line 33-34):

> "Context gates DISPLAY only (footer filtering, style.css) — dispatch is
> first-match with no context filter, which is why every key is unique."

`keymap.py`, module docstring (lines 22-23):

> "app.js dispatches on the FIRST key match with no context filter, so
> every key must be unique across the whole table (tested)."

The invariant the project enforces is **key → action**. There is no
invariant on **action → element multiplicity**, which is exactly what a
`{% for %}` loop breaks.

`.selected` is referenced in `app.js` at three places only —
`moveSelection` (350), `drillIntoSelection` (360), `ensureRowSelected`
(380). `clickAction` never reads it. Measured: `grep -n '\.selected'
static/app.js` returns lines 342 (a comment), 353, 354, 362, 377 (a
comment), 383 — no dispatch site.

`data-key-context` is declared at `action_bar.html:10` and
`pane.html:16` and read by **nothing**. Measured here:

```sh
$ grep -rnE 'data-key-context|key_context|keyContext' \
    --include='*.py' --include='*.js' --include='*.css' --include='*.html' .
plugins/self-learn/ui/templates/partials/pane.html:16
plugins/self-learn/ui/templates/partials/action_bar.html:10
# (plus this unit's own inputs under misc/)
```

Positive control that the grep can see a consumed attribute:
`grep -c 'data-noop-hint' static/app.js` → non-zero (lines 568, 572,
605, 617).

### 2.4 N10 is structurally inert on two of three surfaces

`currentRecordId()` (app.js:74-77) reads `[data-record-id]`. Measured:
that attribute is stamped at exactly three sites, all Detail —
`detail.html:22`, `detail_resolved.html:23`, `detail_degraded.html:24`.
On Front and Bucket it is absent, so the fire-time check
`recordNow !== recordAtDefer` is `null !== null` — always false, always
passes, and never warns.

### 2.5 The bulk-collapse row — the severe one

`bucket.html:65-73`, read here in full:

```jinja
  {% if group.bulk_collapse %}
  <div class="bulk-collapse-row" data-row>
    <p>{{ group.bulk_collapse.text }}</p>
    <form hx-post="/bucket/{{ model.scope }}/{{ model.bucket }}/graduate-bulk" hx-swap="none" hx-disabled-elt="find button">
      <input type="hidden" name="ids" value="{{ group.bulk_collapse.ids | join(',') }}">
      <button type="submit" data-key-action="graduate" title="…">Acknowledge all as canon</button>
    </form>
  </div>
  {% endif %}
```

Four facts, each read at `502ca8d`:

1. The button carries `data-key-action="graduate"`, and `g` is bound to
   `graduate` (`keymap.py:70`).
2. It is `type="submit"` in a form posting straight to
   `/bucket/{scope}/{name}/graduate-bulk` with a hidden `ids` field
   naming **multiple** records.
3. `routes.py:3035-3062` — `graduate_bulk` loops
   `build_argv("graduate", record_id, no_push=True)` through the runner
   for every id **immediately**. There is no arm step, no nonce, no
   confirm. The arm-then-confirm mitigation that softens every other key
   **does not exist on this path**.
4. `models.py:1436-1444` sets `rows = ()` for a group whose every row is
   `already_canon`, so the bulk row *replaces* that group's record rows,
   and `_GROUP_ORDER` (`models.py:534`) puts `skill-md` first — putting
   the bulk button first in document order on a page that still has
   record rows in later groups.

**Live reachability, measured read-only against `~/.self-learn` on
2026-08-30:** every proposal in the ledger carries
`already_canon: false` (16 files, 16 occurrences, zero `true`), so **no
bulk-collapse row renders today**. The hazard is code-live and
fixture-reachable, not currently on screen. Stated this way deliberately:
the previous write-up did not measure this, and a severity claim that
outruns its evidence is the thing this project keeps catching.

### 2.6 What the design intended — quotes, not paraphrase

`09-surface-spec.md`, Y-4:

> "Front gains a section after the bucket walk: routed records with
> unconfirmed recurrence suspects … Actions … **`t` tolerate** … **`c`
> confirm** … **retire** — `g` graduate works directly on the row …
> **One suspect card per record, newest nonce.**"

`09-surface-spec.md`, Y-6:

> "a small read-only list from `report --json .open_followups` …
> **renders each** with `followup done <id>` arming."

`app.js:14-17`, its own header:

> "this file's job is purely: keymap lookup -> find **the** matching
> `[data-key-action]` element on the currently visible screen -> click
> it."

That is a singular-match assumption. It is true on Detail and false on
Front and Bucket.

`03-decisions.md`, row `S-20` (F6, 2026-07-24, human-ratified):

> "`data-key-action="confirm"` already exists at three other sites
> (`action_bar.html`'s armed block, `proposal_bar.html`,
> `host_add_bar.html`), and `host_add_bar.html` is included by both
> `bucket.html` and `detail.html` — a holding Detail page for a record
> with an unregistered host could **co-render two identical targets, and
> `clickAction`'s `document.querySelector` would resolve ambiguously by
> document order.** Renaming the keymap action instead leaves every
> existing target unambiguous."

So document-order resolution of duplicate targets is **already on the
record as unacceptable ambiguity in this codebase**. The remedy chosen
then — rename the action — works for two *different* actions that
collided on one name. It cannot work for the *same* action rendered N
times by a `{% for %}` loop. "Act on the first row" is documented
nowhere, and no `FW-` row in `14-forward-work-map.md` tracks it.

### 2.7 A second cross-target door — and one claim of r1's that was wrong

**(a) The expanded cluster — real, and the most destructive instance
found.** `bucket.html:48-59` renders cluster rows **before** the
`{% for group %}` loop, and an expanded cluster
(`cluster_expanded.html`) emits one `data-key-action="route"` per member
inside that single row. `e` is bound to `route`. So on a bucket page with
an expanded cluster, `e` — pressed anywhere, with any row selected —
resolves to **cluster member 1's** "Route as survivor" button, whose
`hx-vals` carries `"collapse": cluster_id`. That is not merely the wrong
record: it is a *merge*, retiring the cluster's other members into a
survivor the operator never chose.

Reachability, measured read-only: `read_clusters()` (`ledger.py:356-378`)
globs `proposals/merge-*.yaml`; `find ~/.self-learn -name 'merge-*.yaml'`
→ **0 files** (positive control: 7 `proposals/` directories, 16 `*.yaml`
in them). So the cluster surface has **no live instance today**; it is
reachable by construction and by fixture. Independently reproduced on the
wire at the r1 gate: with selection asserted on an unrelated pending
record row, `e` POSTed
`/record/<member 1>/action/arm  collapse=merge-…&kind=detail&verb=route`.

**(b) `Enter` confirming a host registration — CLAIMED IN r1, AND WRONG.**
r1 argued from document order that a mouse-armed `host_add_bar` sitting
above a keyboard-armed record bar would make `Enter` confirm the host
registration. The state is **not reachable**. `static/style.css:433`,
read here in full:

```css
/* Armed state is modal by design (Enter confirms, any key cancels) —
   the keyboard can never stack a second armed bar, but a MOUSE click
   on another bar's trigger could, leaving Enter aimed at whichever bar
   sits first in the DOM (review 2026-07-17 host-add, finding 4). While
   any bar is armed, every other bar's triggers go inert; they return
   the moment it disarms. */
body:has(.action-bar[data-armed="true"]) .action-bar[data-armed="false"] button {
  visibility: hidden;
}
```

That comment names **the exact review finding r1 re-reported as new**, and
it shipped as the fix for it on 2026-07-17. Both other bars are covered by
the selector: `host_add_bar.html:21` and `proposal_bar.html:12` each carry
`class="action-bar"` with a `data-armed` attribute (read here). The gate
measured a real Playwright mouse click on a second bar's trigger timing
out with `element is not visible`; a human is in the same position.

**(c) What the mitigation does NOT cover — the real residual door.** The
rule reaches only `button`s **inside** a `.action-bar`. Two controls that
arm or write live outside one (both read here):

| control | markup | not covered because |
|---|---|---|
| cluster member "Route as survivor" | `cluster_expanded.html:15`, inside `<li>` → `<ul class="cluster-members">` → `<div class="cluster-expanded">` — **no `.action-bar` ancestor** (grep of the file's every `class=`: `cluster-expanded`, `cluster-rationale`, `cluster-members`, `cluster-member-id`, `badge`) | arms a bar while another is armed |
| bulk-collapse "Acknowledge all as canon" | `bucket.html:66-72`, inside `<div class="bulk-collapse-row">` → `<form>` — **no `.action-bar` ancestor** | performs the un-armed multi-record **write** mid-decision |

So the co-arm class is real, through the cluster-member door, and it is
**worse** than the door r1 claimed. Measured at the gate: with a record
bar armed, the cluster member button still computes visible; clicking it
produced two armed bars; `findArmedBar()` returned the cluster member's
(document order puts clusters first); `Enter` POSTed
`/record/<member 1>/action/confirm  verb=route&kind=detail&collapse=merge-…`
— **it executed a merge the operator never armed.**

This is the fixture `A1`, `A2`, `A3` and `A5` are built on (§6.4), and the
inventory in the table above is pinned by `S2` (§6.8) so a third such
control cannot be added silently.

### 2.8 Measured here vs. cited

| claim | status |
|---|---|
| `clickAction`/`findArmedBar`/`focusNote`/fire-time lookups are page-wide | **measured here** (source read + grep, §2.1) |
| the six duplicating templates and their loop bounds | **measured here** (each file read, §2.2) |
| `data-key-context` has zero consumers | **measured here** (repo-wide grep with a positive control, §2.3) |
| `[data-record-id]` exists only on the three Detail templates | **measured here** (grep, §2.4) |
| `graduate-bulk` has no arm step and writes N records | **measured here** (`routes.py:3035-3062` read, §2.5) |
| bulk row precedes record rows; collapsed group drops its rows | **measured here** (`bucket.html`, `models.py:1436-1447`, §2.5) |
| no bulk-collapse row and no cluster renders on the live ledger today | **measured here**, read-only, 2026-08-30 (§2.5, §2.7) |
| `recurrence-suspect` telemetry: 8 events across 6 distinct records | **measured here**, read-only grep of the telemetry JSONL |
| **≥2 holding rows render today** | **supported, not merely cited.** 8 `recurrence-suspect` events across 6 distinct records (measured here); of those 6, 4 carry `status: routed` and none has a `confirm-recurrence`/`dismiss-suspect` telemetry event (measured at the r1 gate, read-only). So the rendered count is bounded above by 4 and is almost certainly ≥2. The **exact** figure still needs `report.recurrence_suspects()`'s own filter, which neither this author nor the gate ran against the real home. |
| the ordering claim that the keys act on the `miner-match` suspect when the operator means the `fire-violated` one | **cited** — `misc/reviews-2026-08-29/frontpage-action-targeting.md` §8. Deriving the *filtered* count needs `report.recurrence_suspects()` run against the real home, which this author declined (the ledger is read-only for this unit and probes are required to use a throwaway `SELF_LEARN_HOME`). The raw-event half is re-measured above. **Builder: treat the "2 rows today" number as unverified; nothing in §6 depends on it.** |
| the live pending-record counts (`user` = 14) | **measured here**, read-only, 2026-08-30, with a positive control (§2.0) |
| the `style.css:433` modal mitigation and its 2026-07-17 provenance; the cluster-member and bulk-collapse controls having no `.action-bar` ancestor | **measured here** (file reads, §2.7 b/c) |
| the co-armed cluster fixture's wire behaviour (`Enter` → a `collapse=` confirm) | **cited** — blind spec gate r1, which reproduced it in Chromium. The *structural* premise it rests on (the cluster button is outside `.action-bar`, so `style.css:433` does not reach it) is measured here. |
| **Discipline this table now enforces, after r1 got it wrong:** the reachability of a *state* (two bars armed, a row rendered) needs a **reachability measurement**, not a document-order read of the markup that would produce it. Markup order tells you what the DOM would look like; it does not tell you whether anything downstream — CSS, a guard, a model filter — prevents that DOM from ever existing. Every "live" claim above is a measurement of the live ledger or of a rendered document, never an inference from template order. | — |
| the wire-level POSTs (`k`/`t`/`c`/`g` with row 2 selected all hitting row 1; the mouse control landing correctly; the deferred relocation onto row 2 with zero warnings; the bulk `g` POSTing `ids=…,…`) | **cited** — same report §§2, 5, 6. **Not re-run here**: re-running its harness requires copying a probe module into `plugins/self-learn/ui/tests/`, and two sibling agents share this working tree and would collect it. The harness is preserved at `misc/reviews-2026-08-29/harness_test_probe_frontpage_targeting.py` with its own re-run notes. Every one of those behaviours is re-established from scratch by §6's criteria, which are the builder's obligation regardless of whether the report is right. |

---

## 3. The surfaces, exhaustively

A fix that covers two of three is how this class survives. Every template
that can render a `[data-key-action]` is listed; nothing is omitted as
obvious.

### 3.1 Surfaces that duplicate a *bound* action (live defect)

| # | surface | template | duplicated actions | keys |
|---|---|---|---|---|
| 1 | Front — holding rows | `index.html:83-95` | `tolerate`, `confirm_recurrence`, `graduate`, `dismiss_suspect` | `t` `c` `g` `k` |
| 2 | Bucket — pending record rows | `bucket.html:75-100` | `route`, `reject`, `defer`, `graduate`, `cycle_destination` | `e` `x` `f` `g` `o` |
| 3 | Bucket — bulk-collapse row vs. record rows | `bucket.html:65-73` + `:75-100` | `graduate` | `g` |
| 4 | Bucket — expanded cluster members | `cluster_expanded.html:15` | `route` (× members) | `e` |
| 5 | Bucket — co-armed bars, **via the cluster-member door only** | `cluster_expanded.html:15` arming a bar while `action_bar.html:110/119` holds another | `confirm`, `disarm` | `Enter`, any key |
| 6 | Front/Bucket — note inputs | `action_bar.html:125/161/232` | (`focusNote`'s selector, not a `data-key-action`) | `n` |

### 3.2 Surfaces that duplicate an *unbound* action (latent)

| # | surface | template | duplicated action | why latent |
|---|---|---|---|---|
| 7 | Front — follow-up rows | `index.html:102-110` | `followup_done` | no `KEYMAP` entry binds it (measured: `grep followup_done keymap.py` → nothing) |
| 8 | contradicts offer — one bar per edge | `contradicts_offer.html:35-42` | `link_contradicts` | no `KEYMAP` entry |

Both become live the moment anyone binds a key — and `keymap.py:104-109`
records `l` and `z` being held free for exactly that kind of addition.
The fix must close the class, not the four holding keys, or this arms
itself later.

**Two mechanisms close it, and only one of them is automatic.** The
*dispatch* fix closes it by construction: `resolveScoped` is
action-agnostic, so a key bound to `followup_done` tomorrow is scoped the
day it is bound. The *structural guard* is what stops a template from
re-opening it, and `S1` therefore inspects **every `data-key-action` in
the document**, not only the KEYMAP-bound ones — r1 of this spec scoped it
to bound actions, which made it blind to exactly these two rows and made
its own "≥2 follow-up rows" fixture requirement decorative (gate r1
MAJOR-4).

### 3.3 Surfaces verified unique-by-construction (must not regress)

| # | surface | why unique | measured |
|---|---|---|---|
| 9 | Detail / `detail_resolved` / `detail_degraded` | one record, one bar; **no `[data-row]` element at all** | grep: no `data-row` in any `detail*.html` |
| 10 | pane / `pane_idle` | the two `data-key-action="{{ 'bucket_pane' if bucket_pane else 'iterate' }}"` buttons at `pane_idle.html:31` and `:37` are the two arms of one `{% if pane and pane.has_persisted_transcript %}` / `{% else %}` — never co-rendered | file read in full |
| 11 | `proposal_bar.html` | `confirm`/`disarm` in the `{% if proposal.armed %}` arm, `arm_proposal` in the `{% else %}` — exclusive | file read |
| 12 | `host_add_bar.html` | `confirm`/`disarm` only in its armed branch | file read |
| 13 | `report.html` | one `up` link, nothing else | grep |
| 14 | Front — bucket-table rows, near-miss rows | carry `data-row` (they are selectable) but no `data-key-action` | `index.html:62`, `:163` |
| 15 | Bucket — archive rows | deliberately carry **no** `data-row` (`bucket.html:104-117`) and no action | file read |

Surfaces 9-15 are the regression surface: `T3`, `T5` and `R1` exist to
prove the fix does not break them.

### 3.4 One dead affordance, described so the gate does not find it undescribed

`bucket.html:52` puts `data-key-action="drill_in"` on the cluster
"Expand" button. `drill_in` never reaches `clickAction`: `onKeyDown`'s
switch (`app.js:523-525`) handles it with `drillIntoSelection()`, which
looks for an `a[href]` inside the selected row — and a `.cluster-row` has
none. So the attribute is inert and the Expand button is
keyboard-unreachable today. **Disposition: unreachable, untouched.**
Making it reachable is `[B-4]` (§7) — it is a keyboard-coverage gap, not
a targeting defect, and folding it in here would widen the diff without
touching the root cause.

---

## 4. The design

### 4.1 One primitive

All of §2.1's keyboard lookups route through a single function. Sketch —
the builder owns the exact code; the **behaviour** is what §6 pins.

```js
  // The action's own combined target set: a live control, or a
  // server-marked gated control (the [data-noop-hint] pair
  // action_bar.html already uses for the singleton `o` cycle).
  function targetSelector(action) {
    return '[data-key-action="' + action + '"], ' +
           '[data-noop-hint][data-noop-action="' + action + '"]';
  }

  // -> {status: "one"|"none"|"ambiguous", el}
  function resolveScoped(selector) {
    const sels = document.querySelectorAll(
      "#self-learn-ui-content [data-row].selected"
    );
    if (sels.length > 1) return { status: "ambiguous", el: null };
    if (sels.length === 1) {
      const inRow = sels[0].querySelectorAll(selector);
      if (inRow.length === 1) return { status: "one", el: inRow[0] };
      if (inRow.length > 1) return { status: "ambiguous", el: null };
      // exactly 0 in the selected row -> fall through, page-wide
    }
    const all = document.querySelectorAll(selector);
    if (all.length === 1) return { status: "one", el: all[0] };
    if (all.length === 0) return { status: "none", el: null };
    return { status: "ambiguous", el: null };
  }
```

Notes the builder must honour:

- **The selected-row query is scoped to `#self-learn-ui-content`**, the
  same container `rows()` already walks (`app.js:347`), so the two agree
  on what a row is. The **page-wide fallback is not** so scoped — `up`
  lives in the status strip, outside that container, and must stay
  reachable.
- **Action names are `[a-z_]+`** (every `KeymapEntry.action` in
  `keymap.py`), so string-concatenating them into a selector needs no
  escaping. If a future action name ever contains anything else, this
  becomes an injection into a selector — noted, not guarded.
- **Two `.selected` rows is `ambiguous`, not "pick one".**
  `moveSelection` clears all before setting one, so this is defensive;
  it must not silently degrade to first-match.

### 4.2 What each caller does with each status

| caller | `one` | `none` | `ambiguous` |
|---|---|---|---|
| `clickAction(action)` (dispatch) | click it, or — if it is the `[data-noop-hint]` half — show that hint | return "absent" so `dispatchOrHint` can try `NOOP_MESSAGES` | `showNoopHint(MULTI_TARGET_HINT)`, **zero requests**, and report *handled* |
| armed-bar detection | enter the armed branch, scoped to that bar | fall through to normal dispatch | `preventDefault()`, `showNoopHint(MULTI_ARMED_HINT)`, return — **except `Escape`**, §4.3 |
| `focusNote()` | focus it | silent no-op (today's behaviour; the armed branch already hints for `n`) | `showNoopHint(MULTI_NOTE_HINT)` |
| `dispatchOrHint`'s gated-control lookup | folded into `clickAction` above — the noop pair is part of `targetSelector` | `NOOP_MESSAGES[action]` as today | as above |

**The return contract.** `clickAction` must report *handled* for
`one`-that-fired, `one`-that-hinted, **and** `ambiguous`; only `none`
reports *not handled*. `goUp()` branches on it
(`if (clickAction("up")) return; … window.history.back();`), so a refusal
that reported *not handled* would refuse **and then navigate away** —
the worst of both. Pinned by `R1`.

**Every consumer of that return value, named** (gate r1 MINOR-5). Beyond
`dispatchOrHint`, `clickAction` is called from `goUp()` twice
(`clickAction("interrupt")`, `clickAction("up")`) and from the armed
branch twice (`clickAction("confirm")`, `clickAction("disarm")`). After
§4.1's folding, any of those four could in principle return *handled* for
a **hint** rather than a click. Today that is **inert**: no
`[data-noop-hint][data-noop-action]` pair exists for `confirm`, `disarm`,
`interrupt` or `up` anywhere in the templates (measured — the only
producer of the pair is `action_bar.html`'s singleton-cycle branch, keyed
`cycle_destination`). It is stated rather than left implicit because
adding such a pair later for any of those four would silently change
`goUp()`'s branching — exactly the second-order shape this unit exists to
stop.

**`focusNote`'s selector is also wrong in a second way, found here.**
`.action-bar input[name="note"]` (`app.js:338`) can match a **hidden**
input: `action_bar.html:33`, `:52`, `:67` and `:86` each render
`<input type="hidden" name="note">` inside an action bar. **Each of the
four is conditional, and the condition matters** (gate r1 MINOR-1 — r1 of
this spec stated the premise as unconditional, which it is not): `:33`,
`:52` and `:67` are guarded by `{% if commit_drift.retry.note %}` and
`:86` by `{% if armed.note %}`. The one that bites is `:67` — the
**un-armed** commit-drift retry branch, the only one `focusNote` can
reach, since an armed bar routes `n` through the armed branch's own hint
instead. So the enabling condition is precise: a route that **failed** on
that row **and whose retry carried a note**. In that state a Bucket page
puts a hidden `note` input ahead of every real one, and `n` "focuses"
something invisible — a silently dead key, the exact shape of the two
UI-walk defects `NOOP_MESSAGES` was built for. The selector must be
`input[type="text"][name="note"]`. `F1b` states the precondition in full,
so a builder cannot seed a note-less failure and get a criterion that is
green before and after the narrowing.

**MINOR-6 — the fallback's residual cost, and why it stays silent
`[A]`.** There is a shape the carve-out above does not cover: the
selected row owns no such action and exactly one exists **elsewhere**, so
the key acts on a row the operator is not standing on. Reachable today —
Front with one holding row and any number of follow-up rows, selection on
a follow-up row, press `t`/`c`/`g`/`k`. **Ruling: the fallback acts
silently in this unit; a signal is `[B-6]`, not `[A]`.** Three reasons,
in order of weight:

1. **It is not signal-free, contra the obvious reading.** `fire()`
   already ends `live.click(); live.scrollIntoView({block: "nearest"})`
   (`app.js:224-225`, read here), so a fallback dispatch **scrolls the
   element it acted on into view**; and every verb reachable this way
   arms rather than writes, with `action_bar.html:95` rendering
   `<code>{{ armed.record_id }}</code>` in the armed strip. The operator
   is taken to the row and shown its id before `Enter` executes anything.
2. **A hint here would be loudest where it is least needed.** The
   fallback also fires on every Detail page (no `[data-row]` at all) and
   on a single-holding-row Front, which are the common cases and the ones
   where the key means exactly one thing. Gating the hint on "a selection
   exists but owns no target" would narrow it, at the cost of a second
   condition.
3. **`showNoopHint` is the wrong channel for it.** Its entire existing
   vocabulary is "that key did nothing" (`NOOP_MESSAGES`, the armed-`n`
   hint, the `?`-in-a-field hint). Routing a *success* message through it
   makes the line ambiguous. The right shape is a separate quiet
   "acted elsewhere" affordance — a surface decision with its own taste
   question, not a targeting fix.

The residual is stated, not waved away: **an operator can press a key and
have it act on a row they are not on, and nothing says so in words.** The
bound on the damage is arm-then-confirm plus the scroll; the one
un-armed action that can take this path is `o` (§4.5).

**Why a page-wide fallback at all, rather than "refuse unless it is in
the selected row".** On Front, `ensureRowSelected()` selects the first
`[data-row]`, which is a bucket-table row owning no action; on Detail
there is no `[data-row]` at all. A selection-only rule would make `t`
dead on a one-holding-row Front page and `e` dead on every Detail page —
turning a targeting defect into a dead keyboard. The fallback fires only
when there is exactly **one** thing the key could possibly mean, which is
precisely the case where today's behaviour is already correct.

**Why the `[data-noop-hint]` pair is inside the *scoped* query and not
only the fallback.** Because of the bulk row. After §4.5 the bulk button
carries the noop pair rather than `data-key-action`. If the scoped query
looked only for `data-key-action`, then with the **bulk row selected** it
would find 0 in scope, fall through, find the single record row in
another group, and **graduate a record the operator did not select**.
Treating the selected row's gated control as a positive, in-scope answer
is what stops that. This is the subtlest rule in the unit; `B2` is its
criterion and the mutation that reddens it is dropping the pair from
`targetSelector`.

### 4.3 The armed branch

`findArmedBar()` becomes `resolveScoped('.action-bar[data-armed="true"]')`
and the armed branch acts **within** the resolved bar: `confirm` and
`disarm` are looked up with `bar.querySelector(...)`, not page-wide. On
every reachable document shape that within-bar lookup and a second
`resolveScoped` agree, so **it gets no criterion of its own** — a
criterion that cannot fail is the thing this project keeps catching. It
is required anyway because it is the honest expression of "this bar's
Confirm", and it is exercised by `A1`, `A4` and `A5`.

**Why a second armed bar exists at all — the two mechanisms, and the
hole between them.** The **keyboard** can never stack one: the armed
branch runs before the KEYMAP lookup, so while any bar is armed every key
either confirms or disarms it — there is no keystroke that reaches a
second bar's trigger. The **mouse** cannot either, for any trigger
**inside** a `.action-bar`: `style.css:433` sets
`visibility: hidden` on those while any bar is armed (§2.7 b). The
residual door is therefore exactly **"a bar-arming control that lives
outside a `.action-bar`"** — today, the cluster member's "Route as
survivor" button, and nothing else (§2.7 c). That inventory is what `S2`
pins, and it is what makes the co-armed criteria buildable at all.

Consequences, each deliberate:

- **One armed bar, selection elsewhere** → the page-wide fallback finds
  it; the armed branch engages exactly as today. This is the mouse-arm
  case, and it is why §1's non-objective 5 rejects
  selection-follows-arming. Pinned by `A4`.
- **One armed bar inside the selected row, another armed elsewhere** →
  the selection breaks the tie in favour of the row the operator is on
  (`A5`). Today, document order picks the *other* one — which on a bucket
  page with an expanded cluster means `Enter` **executing a merge**
  (§2.7 c), because `bucket.html` renders clusters above the record rows.
- **Two armed bars, neither in the selected row (or no selection at
  all)** → refuse (`A2`). This is a **deliberate behaviour change** on a
  mouse-only-reachable state that today resolves by document order.
- **`Escape` is exempt from the multi-armed refusal** and performs the
  ordinary `up` action (`goUp()`). Without this the keyboard is *trapped*
  until a mouse click — every key refused, no way out. `Escape` cannot
  disambiguate *which* bar to cancel, but leaving the page abandons both
  harmlessly: arming renders a partial and issues no write, so nothing is
  lost. Pinned by `A3`. The `MULTI_ARMED_HINT` must say so.

### 4.4 The deferred-fire guard — replacing N10's inertness

N10 stamps `currentRecordId()` at defer time and re-checks it at fire
time. On Front and Bucket both reads are `null`, so it passes vacuously
(§2.4). **A guard that is structurally inert on two of three surfaces is
not a guard.**

**Rejected: stamping `data-record-id` on each row.** It is the obvious
move and it is wrong, for two reasons — the second is the stronger one
and r1 of this spec missed it (gate r1, §4).

1. **Additive, through `currentScopes()`.** `app.js:692-700` reads
   `document.querySelector("[data-record-id]")` to build the SSE scope
   list; stamping rows would make a Bucket page suddenly claim
   `record:<first row's id>` as one of its scopes and change which SSE
   frames `inScope()` accepts.
2. **Subtractive, through `handlePaneProposal()`** — a live-refresh
   *regression*, not merely a widened scope. `app.js:1964-1981`, read
   here:

   ```js
       if (document.querySelector("[data-record-id]")) {
         if (recordMatch) reload();
         return;                    // <-- never reaches the bucket check
       }
       var bucketMatch = …
       if (recordMatch || bucketMatch) reload();
   ```

   **Any** `[data-record-id]` in the document flips the page onto the
   record-only branch and returns before the bucket check. A Bucket page
   with stamped rows would **stop reloading on bucket-scoped
   `pane_proposal` envelopes entirely.** It would also give Bucket a
   non-null `currentRecordId()`, quietly changing what N10's own
   fire-time comparison means there — the guard this section is
   *replacing* would silently start doing something different on the
   surface where it is currently inert.

A *new* attribute (e.g. `data-row-record-id`) would avoid both
collisions, but adds a template concept for one consumer. The signature
below needs neither.

**Adopted: a target signature** — "what request would this element
actually issue", computed from what the templates already carry. No new
attribute anywhere.

```js
  function targetSignature(el) {
    if (!el) return null;
    const host = el.closest("[hx-post],[hx-get],[hx-put],[hx-delete]");
    const verb = host
      ? (host.getAttribute("hx-post") || host.getAttribute("hx-get") ||
         host.getAttribute("hx-put") || host.getAttribute("hx-delete"))
      : "";
    const bar = el.closest(".action-bar");
    return [
      el.getAttribute("data-key-action") || "",
      verb || "",
      el.getAttribute("hx-vals") || (host ? host.getAttribute("hx-vals") : "") || "",
      el.getAttribute("hx-include") || (host ? host.getAttribute("hx-include") : "") || "",
      el.getAttribute("href") || "",
      bar ? bar.id : "",
    ].join("|");
  }
```

Measured premise: **no template uses htmx's `data-hx-*` prefixed form** —
`grep -rn 'data-hx-' templates/` returns nothing — so reading the plain
attributes is complete today. If that ever changes the signature silently
weakens; `SIG1` (§6) is the pin that fails if it does.

The deferred entry captures `sigAtDefer` alongside the existing
`recordAtDefer`, and `fire()`:

1. re-resolves by the **same rule** (`resolveScoped`, or
   `document.getElementById(barId)` + `querySelector` when the armed
   branch supplied a bar scope — never a closed-over element, per D1);
2. **drops with exactly one `console.warn`** if the re-resolution is
   `none` or `ambiguous`. Today a `!live` miss is a bare `return` — a
   dropped keystroke indistinguishable from a key that does nothing.
   Pinned by `D4`;
3. drops with a warn if `currentRecordId() !== recordAtDefer` — **N10 is
   kept, not replaced.** It is the only leg that catches a whole-page
   record change for an identity-less target (`up` to the same bucket,
   `toggle_brief`), whose signature is unchanged across records. Its
   shipped test
   (`test_js_dom.py::TestClickActionSettleGating::test_deferred_click_no_ops_when_record_changes_before_fire`)
   is a regression pin for this unit, not a new criterion — the signature
   leg would also catch that case, so a new criterion there could not
   distinguish the two and would be untestable-by-construction;
4. drops with a warn if `targetSignature(live) !== sigAtDefer` — the leg
   that finally works on Front and Bucket (`D1`, `D2`);
5. then the existing r7 wired-check and `live.click()`, unchanged.

### 4.5 The bulk-collapse row — ruling

**Ruling: not keyboard-reachable in this unit.** `bucket.html:70` loses
`data-key-action="graduate"` and gains the gated pair the codebase
already has for exactly this ("renders but the keyboard cannot act on
it"):

```jinja
      <button type="submit"
              data-noop-hint="Acknowledging a whole group as canon is click-only — it retires every record in the group at once, with no confirm step."
              data-noop-action="graduate"
              title="…">Acknowledge all as canon</button>
```

Reasoning, in order of weight:

1. **It is the only un-armed, MULTI-RECORD, immediately-writing control
   in the app.** Every other destructive verb goes through
   arm-then-confirm, and the armed strip prints the record id it is about
   to act on. This path prints nothing and writes N records on one
   keystroke (§2.5). *The qualifier is load-bearing and is not a claim
   that this is the only un-armed POST* (gate r1 MINOR-7):
   `cycle_destination` (`action_bar.html:267`, bound to `o`) also posts
   immediately with no arm step — but single-record, reversible by
   cycling again, and re-rendering the destination it changed in place.
2. **Making it key-reachable safely requires inventing an arm step for
   `graduate-bulk`** — a route change, a nonce, an armed partial. That is
   a real unit, not a line in this one (§7, `[B-1]`).
3. **No affordance is lost — and the residual is stated, not left as
   the last word.** It remains a button: clickable, and natively
   focusable by Tab. **After this unit, the un-armed two-record write is
   still one mouse click away, with no confirm step**, and `[B-1]` defers
   the arm step indefinitely. That is accepted as out of scope *for a
   targeting unit* — this unit's job is to stop a **keystroke** reaching
   it — but it is a real, known, open hazard, not a closed one. It is
   made worse by the same structural hole as §2.7(c): the bulk button
   lives outside any `.action-bar`, so `style.css:433` does not hide it
   even while another bar is armed, i.e. it stays clickable mid-decision.
4. **The noop pair is not decoration.** It is what makes `g` *with the
   bulk row selected* refuse instead of falling through to a record row
   elsewhere on the page (§4.2). Without it the fix would introduce a
   new, quieter version of the same bug.

No new keymap entry is added (`B4`). "Give bulk graduate its own key
after it has an arm step" is `[B-1]`.

### 4.6 `data-key-context` — delete, do not wire

Deleted from `action_bar.html:10` and `pane.html:16`. Reason, measured:
wiring it as a dispatch filter would **kill a live binding**. `KEYMAP`
binds `g` → `graduate` with `context="detail"` (`keymap.py:70`), but
`action_bar.html`'s holding branch renders
`data-key-context="holding"` on a bar that carries
`data-key-action="graduate"` (`action_bar.html:10` and `:146`). A filter
requiring the target's context to match the entry's would make `g` dead
on Front's holding rows — a regression, delivered by the very mechanism
meant to fix targeting. The `context` field is a **display** classifier
(footer/overlay filtering, as `keymap.py` says) and does not agree with
the templates; scoping is by selected row (§4.1), not by context.
Leaving a declared-and-ignored attribute in place is what let this
mechanism look like it existed. `C1` pins the deletion.

### 4.7 The plain-words hints

Y-9 (no system vocabulary without a translation). Exact strings are the
builder's to place in one const block; each must name the *way out*:

- `MULTI_TARGET_HINT` — "More than one row here can do that. Move to the
  row you mean (w or s), then press the key again."
- `MULTI_ARMED_HINT` — "More than one action is armed. Click Confirm or
  Cancel on the one you mean, or press Esc to leave."
- `MULTI_NOTE_HINT` — "More than one note field here. Move to the row you
  mean (w or s), then press n."

They render through the existing `showNoopHint()` (`app.js:599`) — the
same transient, self-clearing, `scrollIntoView`-ed line every other dead
key uses. No new surface.

---

## 5. Blast radius

### 5.1 Files this unit changes

| file | change |
|---|---|
| `plugins/self-learn/ui/static/app.js` | `resolveScoped` + `targetSignature`; `clickAction`, `findArmedBar`'s call site, `focusNote`, `dispatchOrHint`, `fire()` rewired through them; three hint constants; the `Escape` exemption |
| `plugins/self-learn/ui/templates/bucket.html` | line 70: `data-key-action="graduate"` → the `data-noop-hint`/`data-noop-action` pair |
| `plugins/self-learn/ui/templates/partials/action_bar.html` | line 10: drop `data-key-context` |
| `plugins/self-learn/ui/templates/partials/pane.html` | line 16: drop `data-key-context` |
| `plugins/self-learn/ui/tests/` | one new Playwright module + one new render-level module (§6.1) |
| `docs/specs/self-learn/03-decisions.md`, `14-forward-work-map.md` | one `S-` row, the `[B]` `FW-` rows (§9) |

**No change** to `routes.py`, `models.py`, `keymap.py`, or any CLI
module. If a builder finds themselves editing one, that is a signal the
design has been misread — say so in the build note rather than widening
quietly.

### 5.2 Armor

`plugins/self-learn/cli/tests/test_armor.py` protects **CLI** test files
only (`plugins/self-learn/cli/tests/...`, per its `ARMOR` table). No UI
test file is pinned, so the builder may edit `test_js_dom.py`. They
should not need to: §6.1 puts the new criteria in new modules, which
keeps the diff legible and avoids colliding with `test_js_dom.py`'s
module-scoped browser/server fixtures.

---

## 6. Acceptance criteria

`[A]` must hold for the unit to land. `[B]` is deferred (§7) and no `[B]`
appears here.

**Every criterion states the mutation that turns it RED.** Criteria about
*when* or *in what order* something happens are driven through the real
served page in a real browser — never by calling a helper in isolation. A
sibling unit lost a whole gate round to exactly that.

### 6.1 How each group is run

- **Playwright group (`T`, `A`, `D`, `F`, `R`, and `B2`/`B3`)** — a new
  module
  `plugins/self-learn/ui/tests/test_js_dom_targeting.py`, built on
  `test_js_dom.py`'s plumbing (module-scoped uvicorn on 127.0.0.1, fresh
  browser context per test, `SELF_LEARN_HOME` + XDG under a pytest
  tmpdir, `pytestmark = pytest.mark.js`, auto-skip without Chromium).
  Selection is moved with **real key presses** (`s`/`w`) and asserted in
  the DOM before the acting key is pressed — never by injecting
  `.selected` from script. Requests are captured off the wire
  (`page.expect_request` / a `request` listener), not inferred from DOM
  changes. Console output is captured for every criterion that asserts a
  warning or asserts silence.
- **Render-level group (`B1`, `B4`, `C1`, `S1`, `S1b`, `S2`, `SIG1`)** — a
  new module
  `plugins/self-learn/ui/tests/test_target_scoping.py` using the existing
  `make_client` / `seed_record` helpers. These are template and
  source-shape facts, not orderings; a browser would add nothing.
  **The `B` group is deliberately split** (gate r1 MINOR-4): `B1`/`B4`
  are render/source shape, `B2`/`B3` are dispatch orderings and belong in
  the Playwright module.

Run from **inside** the package:

```sh
cd plugins/self-learn/ui && env -u SELF_LEARN_ANALYST_MODEL \
  -u SELF_LEARN_ANALYST_TIMEOUT uv run pytest -p no:cacheprovider -q
```

`uv run --project plugins/self-learn/ui pytest` from the repo root
collects the CLI tree instead. Foreground only, with an explicit
`timeout`. `PLAYWRIGHT_BROWSERS_PATH` must stay pinned if
`XDG_CACHE_HOME` is redirected, or the module silently skips.

### 6.2 Group T — scoped dispatch

| id | criterion | RED mutation |
|---|---|---|
| **T1** `[A]` | Front, **2** holding rows. Selection moved to holding row 2 by real `s` presses (asserted in the DOM first). Each of `t`, `c`, `g`, `k` issues exactly one POST to `/record/<row2-id>/action/arm`, and the body carries **row 2's** `event` nonce. | revert dispatch resolution to `document.querySelector(selector)` → all four POST to row 1 with row 1's nonce |
| **T2** `[A]` | Same page, selection left at the load default (a bucket-table row). Pressing `t` issues **zero** network requests **and** a `[data-noop-hint-active]` element is present in the DOM. Both halves asserted. | (a) global `querySelector` → a POST fires, first half RED; (b) delete the `showNoopHint` call in the ambiguous branch → second half RED. A one-half criterion passes on a dead keyboard, which is why both are required. |
| **T3** `[A]` | Front with **exactly one** holding row, selection at the load default (a bucket-table row, which owns no `tolerate`): `t` POSTs to that holding row. **Today's correct single-target behaviour does not regress.** | delete the page-wide fallback (refuse whenever the selected row has no match) → zero POSTs |
| **T4** `[A]` | Bucket, 2 pending record rows, selection moved to row 2: each of `e`, `x`, `f`, `g` POSTs to `/record/<row2-id>/action/arm`. | global `querySelector` → all POST to row 1 |
| **T5** `[A]` | Detail page (no `[data-row]` anywhere in the document — asserted in the same test): `e` POSTs to that record's arm URL. | make resolution refuse when no `.selected` row exists → zero POSTs |
| **T6** `[A]` | Bucket with a cluster expanded to **≥2** members, cluster row selected: `e` issues **zero** requests and shows a hint. (The members share one `[data-row]`, so no selection can pick between them.) | make the in-row branch take `inRow[0]` instead of refusing → a POST to member 1's arm URL fires |
| **T7** `[A]` | Same page, a **pending record row** selected instead: `e` POSTs to that record's arm URL — never a cluster member's, and never with `collapse` in the body. | global `querySelector` → POSTs to cluster member 1 (document order puts clusters first) |

### 6.3 Group B — the bulk-collapse row

| id | criterion | RED mutation |
|---|---|---|
| **B1** `[A]` | A rendered bucket page whose group is bulk-collapsed: the bulk button carries **no** `data-key-action`, and carries `data-noop-hint` together with `data-noop-action="graduate"`. Asserted against the real rendered HTML of a fixture seeded so `all(r.already_canon)` holds for one group. | restore `data-key-action="graduate"` on `bucket.html:70` |
| **B2** `[A]` | Bucket with a bulk-collapse group **and exactly one** pending record row in another group. **Bulk row selected.** `g` → zero network requests, and the bulk row's own hint text is visible. | drop the `[data-noop-hint][data-noop-action]` clause from `targetSelector` → the lone record row becomes the only page-wide match and **graduates** (an arm POST fires). This is the subtlest trap in the unit. |
| **B3** `[A]` | Same page, **record row selected**: `g` POSTs `/record/<that-id>/action/arm` and **never** `/bucket/<scope>/<name>/graduate-bulk`. | global `querySelector` → POSTs `graduate-bulk` with a multi-id body |
| **B4** `[A]` | Two mechanically checkable halves (gate r1 MINOR-3 — r1's "or any other name bound to the bulk button" was not checkable and could only fail if someone added what nobody proposed): (a) the bulk-collapse button carries **no** `data-key-action` attribute at all; (b) `[e.action for e in KEYMAP]` equals a literal list pinned in the test, so **any** entry added or renamed reddens — including one named for the bulk write. | (a) restore the attribute; (b) append any `KeymapEntry` to `KEYMAP` → the pinned list comparison fails. *Honesty note: `B4` is a cheap guard, not a load-bearing pin — it is listed so the `[A]` count is not read as N equally weighted criteria.* |

### 6.4 Group A — the armed branch

**The fixture these four share, and why it is the only one.** `A1`, `A2`,
`A3` and `A5` need **two bars armed at once**. r1 of this spec specified
that state via a mouse click on a second `.action-bar`'s trigger; the gate
measured that this is **impossible** — `style.css:433` has set those
triggers `visibility: hidden` since 2026-07-17, and a real Playwright
mouse click on one times out with `element is not visible` (§2.7 b). The
one remaining door is the cluster member's "Route as survivor" button,
which lives outside any `.action-bar` and so is not covered by that rule
(§2.7 c, verified here by reading `cluster_expanded.html`'s every
`class=`).

**Fixture CO-ARM** (used by `A1`, `A2`, `A3`, `A5`): a Bucket page with a
valid `merge-*.yaml` cluster over 2 records **plus 2 plain pending record
rows**. The cluster is expanded by a real click on "Expand". Then:

1. put `.selected` where the criterion needs it, with real `s`/`w`
   presses, asserted in the DOM — **before** anything is armed, because
   once a bar is armed the armed branch consumes `s`/`w` too;
2. arm a **record row's** bar (real click on its Approve, or `e` when
   that row is the selected one — both are available while nothing is
   armed);
3. arm a **cluster member's** bar with a real mouse click on "Route as
   survivor" — the click that `style.css:433` does not prevent.

Two bars are now armed. `.selected` survives both steps: each swap
replaces `#action-bar-<id>`, never the `[data-row]` that carries the
class. **Builder: assert the two-armed precondition explicitly** (both
bars matching `[data-armed="true"]`) before the acting keypress — if
`style.css` is ever widened to cover the cluster button, these fixtures
stop being buildable and must fail loudly rather than silently degrade to
one armed bar.

| id | criterion | RED mutation |
|---|---|---|
| **A1** `[A]` | Fixture CO-ARM with `.selected` on the **record row whose bar is armed**. Press `t` (any non-`Enter`, non-`n` key reaches the armed branch): the POST is `/record/<that record>/action/disarm` — **never** the cluster member's disarm. | revert `findArmedBar` to the page-wide `document.querySelector` → document order puts the cluster above the groups (`bucket.html:48` vs `:61`), so the key **disarms the merge arm instead of the record's**. *(This replaces r1's `A1`, whose stated mutation was measured to leave it green: with one bar armed there is exactly one `disarm` target page-wide, `action_bar.html:119` being inside the `{% if armed %}` branch, so page-wide and scoped resolution agree. Gate r1 MAJOR-2.)* |
| **A2** `[A]` | Fixture CO-ARM with `.selected` on the **second, unarmed** record row (positioned at step 1). `Enter` issues **zero** requests **and** renders a `[data-noop-hint-active]` element. Both halves asserted. Deliberate behaviour change on a state that today resolves by document order. | revert `findArmedBar` to page-wide → `Enter` POSTs the cluster member's confirm carrying `collapse=merge-…`, i.e. **executes a merge the operator never armed** |
| **A3** `[A]` | In `A2`'s exact state, `Escape` issues **no** confirm/disarm POST **and** is not swallowed: the page navigates (or `history.back()` is attempted). The keyboard is never trapped by the refusal. | route `Escape` through the refusal branch like every other key → no navigation, keyboard trapped until a mouse click |
| **A4** `[A]` | Front, 2 holding rows, **row 2 armed** (real mouse click, while nothing else is armed) and the selection left on **row 1** (positioned before arming): `Enter` POSTs `/record/<row2-id>/action/confirm`. | make armed resolution selection-only (no page-wide fallback) → zero POSTs, the armed bar unreachable from the keyboard. *Honesty note: today's build also passes `A4`. It is a **design pin**, not a defect pin — its job is to forbid a plausible over-correction, and its mutation is that over-correction rather than a revert to today. Flagged so it is not counted as defect coverage.* |
| **A5** `[A]` | Fixture CO-ARM with `.selected` on the **record row whose bar is armed**: `Enter` POSTs `/record/<that record>/action/confirm` — **never** the cluster member's confirm, and the body carries **no** `collapse=`. The selection breaks the tie. | revert `findArmedBar` to page-wide → `Enter` POSTs `/record/<cluster member 1>/action/confirm  collapse=merge-…`. This is the wire behaviour measured at the gate, and it is a **write that merges records**. |

### 6.5 Group D — the deferred fire

All four drive the same synthetic `htmx:` CustomEvent seam the shipped
`test_js_dom.py` already uses. Two mechanics are load-bearing and easy to
get wrong: `pendingSwapKey` compares the `xhr` with `===`, so the
`afterSwap` and its matching `afterSettle` must carry the **same** object;
and a deferred dispatch drops itself fail-closed 500 ms after deferring
(N17), so the DOM mutation and the releasing `afterSettle` belong in
**one** `page.evaluate` round trip.

| id | criterion | RED mutation |
|---|---|---|
| **D1** `[A]` | Front, 2 holding rows. With a swap outstanding, press `k` while row 2 is selected; before releasing the settle, move `.selected` to row 1; then release. The deferred fire is **dropped**: zero requests, exactly one `console.warn` naming the action. | delete the `targetSignature` comparison → the fire re-resolves into row 1 and POSTs, with no warning |
| **D2** `[A]` | Front, 2 holding rows, selection on row 1. Defer `k`; replace row 1's action bar with one that has no `dismiss_suspect` button (the shape an arm/confirm swap really produces); release. The fire is **dropped** with one warn and **zero clicks anywhere** — in particular it does not relocate onto row 2. | delete the signature comparison → the click lands on row 2 with **zero** console output, which is precisely today's measured behaviour |
| **D3** `[A]` | Fire-time re-resolution returning **`ambiguous`** drops the fire with exactly one `console.warn` and zero clicks. **Fixture** (gate r1 MINOR-2 — r1 stated this behaviour with no way to produce the `ambiguous` half, so a builder could satisfy it with `D2`'s scenario and ship the leg untested): Front with **one** holding row, selection at the load default (a bucket-table row, so resolution is via the page-wide fallback). Defer `t` behind an outstanding swap; then, in the **same** `page.evaluate` round trip, inject a second holding row carrying its own `tolerate` button and release the settle. At fire time the page-wide count is 2 and the selected row still owns none → `ambiguous` → drop. | delete the `ambiguous` branch from `fire()`'s re-resolution (fall through to the first match) → a POST fires against one of the two rows |
| **D3b** `[A]` | Fire-time re-resolution returning **`none`** drops the fire with exactly one `console.warn` and zero clicks. **Fixture — its own, NOT `D2`'s:** Front with **one** holding row, selection at the load default (a bucket-table row). Defer `k` behind an outstanding swap (resolution at defer time is `one`, via the page-wide fallback); then in the same `page.evaluate` round trip strip that row's `dismiss_suspect` button and release the settle. At fire time the selected row has 0 matches **and** the page-wide count is 0 → `none`. *`D2` does **not** produce this state and must not be reused for it: with two holding rows, fire-time re-resolution falls through to row 2 and returns `one` — `D2`'s drop comes from the **signature** leg (step 4), never the `none` leg (step 2). Traced against §4.1's algorithm; r2 of this spec initially mis-folded gate r1's MINOR-2 by asserting otherwise, which would have shipped the `none` branch untested while the criterion went green off the signature leg — the very vacuity MINOR-2 was raised about.* | replace the warn with a bare `return` (today's `if (!live) return;`) → console silent; a dropped keystroke becomes indistinguishable from a key that does nothing |
| **D4** `[A]` regression | `test_js_dom.py::TestClickActionSettleGating::test_deferred_click_no_ops_when_record_changes_before_fire` (N10's own shipped test) stays green. | deleting the `currentRecordId` comparison. *No new criterion is written for the N10 leg: the signature leg would also catch that case, so a new assertion could not distinguish the two and would be untestable by construction.* |

### 6.6 Group F — the note input

| id | criterion | RED mutation |
|---|---|---|
| **F1** `[A]` | Front, 2 holding rows, selection on row 2: `n` puts focus in **row 2's** note input, and that input is **visible** (`document.activeElement`'s enclosing `.action-bar` id is `action-bar-<row2-id>`, and its `type` is `text`). | revert `focusNote` to `document.querySelector` → focus lands in row 1 |
| **F1b** `[A]` | Bucket, 2 record rows, where **row 1 carries a failed-verb error whose retry carried a NOTE** — the full precondition, not merely "a failed verb" (gate r1 MINOR-1: `action_bar.html:67`'s hidden input is guarded by `{% if commit_drift.retry.note %}`, so a note-less failure yields a criterion that is green before *and* after the narrowing) — and the selection is on row 2: `n` focuses row 2's **text** note input. Assert the precondition itself: row 1's bar contains an `input[type="hidden"][name="note"]`. | widen the selector back to `input[name="note"]` **and** revert the row scoping → focus lands on row 1's hidden input, i.e. nowhere visible |
| **F2** `[A]` | Front, 2 holding rows, selection on a bucket-table row: `n` leaves `document.activeElement` unchanged **and** shows the multi-note hint. | (a) global `querySelector` → focus moves; (b) delete the hint call → no hint element |

### 6.7 Group R — the return contract

| id | criterion | RED mutation |
|---|---|---|
| **R1** `[A]` | Front (which renders **no** `data-key-action="up"` — asserted in the same test): `Escape` still falls through to `window.history.back()` and the page navigates. `none` must keep reporting *not handled*. **Test mechanics:** a fresh Playwright page with a single navigation has no history entry to go back to, so the test must navigate **twice** (e.g. `/report`, then `/`), press `Escape`, and assert the page is back at `/report`. Without the second navigation the test reads "no navigation happened" on a correct build. | make the dispatcher report *handled* for `none` → no navigation, `Escape` dead on Front |

### 6.8 Group S — structural guards

| id | criterion | RED mutation |
|---|---|---|
| **S1** `[A]` | For **every `data-key-action` value present in the document** — not only the KEYMAP-bound ones (gate r1 MAJOR-4: scoping it to bound actions meant it never inspected `followup_done` or `link_contradicts`, the very latent class §3.2 says must be closed, and made its own "≥2 follow-up rows" fixture requirement decorative) — in each of Front (≥2 holding rows, ≥2 follow-up rows), Bucket (≥2 record rows **and a bulk-collapse group; no cluster expanded** — see `S1b`) and Detail: either the action occurs **exactly once** in the document, or **every** occurrence has a `[data-row]` ancestor **and** no two occurrences share the same `[data-row]` ancestor. | add a second `data-key-action="route"` inside one `[data-row]`. **Stated plainly: this guard does NOT catch the bulk-collapse shape** (bulk row and record rows are distinct `[data-row]`s), which is why `B1`/`B2`/`B3` exist as separate criteria. A guard whose coverage is overstated is worse than no guard. |
| **S1b** `[A]` | On a Bucket fixture **with a cluster expanded**: the *only* same-`[data-row]` duplicate sets in the document are the `route` buttons inside a `.cluster-expanded` element. Every other `data-key-action` still satisfies `S1`'s rule. This is the one sanctioned same-row multiplicity in the codebase — it is dispatch-covered by `T6`'s refusal, and removing it means making members individually selectable, which is `[B-2]`. | add a second `data-key-action="route"` inside a `.record-row` (i.e. a same-row duplicate **outside** `.cluster-expanded`) → RED. *Why this is split from `S1` rather than folded into it: `S1`'s clause (b) is false on the intended tree the moment a cluster is expanded, so a single-fixture `S1` covering both shapes would be a criterion that cannot pass — the mirror image of the defect class this unit exists to fix.* |
| **S2** `[A]` | **The arming-control inventory.** In a rendered Bucket document with a cluster expanded and a bulk-collapse group present, the set of elements that carry an `hx-post` ending in `/action/arm` (or that submit a form posting to one) **and** have no `.action-bar` ancestor is exactly the cluster-member "Route as survivor" buttons. Rationale: `style.css:433` neutralises a second mouse-arm only for triggers **inside** a `.action-bar` (§2.7 b/c), so any *new* arming control outside one silently re-opens the co-arm door that `A1`/`A2`/`A5` exist to govern — and would do so with no test noticing. The bulk-collapse button is named in the test as a known, separately-tracked exception: it is not an *arming* control but an un-armed **write** outside a `.action-bar` (`[B-1]`). | add an `hx-post=".../action/arm"` control outside any `.action-bar` (e.g. a second survivor button in `bucket.html` itself) → RED. *This guard is a detector, not a fix: it does not close the door, it makes a third one impossible to add unnoticed. Closing it is `[B-7]`.* |
| **C1** `[A]` | `data-key-context` appears **zero** times under `plugins/self-learn/ui/` (templates and source). The test carries its own positive control: the same search for `data-noop-hint` returns a non-zero count. | re-add `data-key-context` to `action_bar.html` |
| **SIG1** `[A]` | No template under `plugins/self-learn/ui/templates/` uses htmx's `data-hx-*` prefixed attribute form. (The signature in §4.4 reads the plain form; if a template ever switches, the signature silently weakens and this fails first.) Positive control in the same test: the search for `hx-post` returns a non-zero count. | add `data-hx-post="…"` to any template |

### 6.9 Suite

`[A]` The full UI suite is green from inside the package, with the one
known pre-existing failure
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`)
and no other. Any *new* failure blocks.

---

## 7. Deferred `[B]`

| id | item | why deferred |
|---|---|---|
| **B-1** | Give `graduate-bulk` a real arm-then-confirm step (route + nonce + armed partial naming the records), and only then consider a key binding. | a route/partial change with its own consent semantics; §4.5 makes the current path safe without it |
| **B-2** | Make expanded cluster members individually selectable (`data-row` per member) so `e` can pick a survivor from the keyboard. | changes what `rows()` walks and therefore `w`/`s` navigation; `T6`'s refusal is correct and complete in the meantime |
| **B-3** | Cap or paginate the holding and follow-up lists. There is no cap today: `_build_holding_rows` emits one row per grouped suspect record and `_build_followup_rows` is a straight passthrough. | a model/surface decision, unrelated to targeting |
| **B-4** | Make the cluster "Expand" button keyboard-reachable (§3.4) — its `data-key-action="drill_in"` is inert because the keymap switch intercepts `drill_in` before `clickAction`. | a keyboard-coverage gap, not a targeting defect |
| **B-5** | Reconsider what `ensureRowSelected()` selects on load (the first row owns no action on Front). | taste; the page-wide fallback makes it harmless |
| **B-6** | A quiet "acted on a row you are not standing on" signal when the **page-wide fallback** fires with a selection present that owns no such target. | the MINOR-6 ruling (§4.2): the case is not signal-free (`fire()` scrolls the acted element into view; the armed strip prints the record id), a hint would be loudest on Detail and single-row Front where it is least needed, and routing a *success* message through `showNoopHint` — a channel whose whole vocabulary is "that key did nothing" — makes the line ambiguous. Needs its own affordance and its own taste call. |
| **B-7** | Close the outside-`.action-bar` door: bring the cluster-member arming buttons (and the bulk-collapse write) under `style.css:433`'s modal rule, or give that rule a selector that does not depend on `.action-bar` ancestry. | **must not land in this unit**: it would make the CO-ARM fixture (§6.4) unbuildable and take `A1`/`A2`/`A3`/`A5` with it. `S2` detects a third such control in the meantime. Sequencing note for whoever takes it: land it *after* U-target, and expect to re-anchor those four criteria on whatever door remains — or retire them with the hazard. |

---

## 8. Risks and what would falsify this design

1. **A page where the operator legitimately wants a key to act outside
   the selected row, with more than one candidate.** None found across
   the fifteen surfaces in §3, but the refusal is the failure mode: the
   operator must move the selection. If a real workflow is found that
   this makes worse, the fix is a smaller selection step, not a return to
   first-match.
2. **`.selected` not surviving a swap.** The design assumes it does:
   every action bar's `hx-target` is `#action-bar-<id>`, which sits
   *inside* the `[data-row]` that carries `.selected` — the class is on
   the row, not the bar. Read at `index.html:84/91`, `bucket.html:76/96`,
   `action_bar.html:10`. **The builder must verify this first, with a
   real arm swap in the browser**, before building anything else: if it
   is false, `A1` and `T1` cannot pass and the model needs a different
   anchor.
3. **`page.wait_for_function` must be given an arrow-function string**
   (`"() => …"`), not a bare expression: the app's CSP is
   `script-src 'self'` with no `unsafe-eval`, and Playwright's string
   form uses `eval`. A bare expression raises
   `EvalError: … violates the following Content Security Policy
   directive`. (Cited from the prior harness's own re-run notes; cheap
   for the builder to confirm on first use.)
4. **Two sibling agents share this working tree.** Test runs are
   foreground with an explicit `timeout`, and no probe module is left in
   `tests/`.
5. **The CO-ARM fixture depends on an open hazard.** `A1`/`A2`/`A3`/`A5`
   are buildable only because a bar-arming control lives outside a
   `.action-bar` (§2.7 c). If `[B-7]` lands, or if `style.css:433`'s
   selector is widened for any other reason, those four fixtures become
   unbuildable — which is why §6.4 requires the two-armed precondition to
   be asserted explicitly, so they fail loudly instead of quietly
   degrading into one-armed tests that pass for the wrong reason. This is
   the same failure mode r1 shipped: a criterion whose state cannot be
   reached, read as coverage.
6. **A reachability claim needs a reachability measurement.** The one
   thing r1 got wrong (§2.8) was inferring that a document state was
   reachable from the order of the markup that would produce it, without
   checking whether anything downstream prevented it. Any new "live"
   claim in a revision owes a measurement of the live ledger or of a
   rendered document.

---

## 9. Owed bookkeeping

### 9.1 One decision row

`03-decisions.md` gains one row — next free is **after `S-56`** (the
current maximum in the file), **claimed against `origin/master`'s
maximum at landing time, not hard-coded here**: `14-forward-work-map.md`
records (2026-08-25) a numbering collision caused by sequencing from a
stale local maximum, and the same discipline applies to `S-` rows.

Its content: *keyboard dispatch resolves against the selected row with a
page-wide-unique fallback and refuses visibly on multiplicity; `S-20`'s
rename remedy is confirmed correct for its own case and explicitly
insufficient for an action repeated by a `{% for %}` loop; the
bulk-collapse graduate is ruled click-only until it has an arm step;
`data-key-context` is deleted rather than wired, because wiring it would
kill the `g` binding on Front's holding rows.*

The row must also carry **two things this unit learned that outlive it**:

1. **`style.css:433` is load-bearing consent machinery, not styling.** It
   is the only thing preventing a second armed bar from a mouse click,
   and it works by `.action-bar` ancestry — so any control that arms or
   writes from **outside** a `.action-bar` silently escapes it. Two do
   today (§2.7 c), and `S2` pins the inventory. Whoever widens or
   replaces that rule owns `A1`/`A2`/`A3`/`A5` (§10.4).
2. **Reachability of a state is a measurement, not a reading.** r1 of
   this spec claimed a live hazard that a CSS rule had closed six weeks
   earlier — and that rule's own comment named the
   review finding being re-reported. The corrected discipline is in
   §2.8's table and §8.6.

### 9.2 Forward-work rows

One `FW-` row per `[B]` in §7, numbered against `origin/master`'s current
maximum at landing (the file's own 2026-08-25 lesson again — the local
maximum here is `FW-143`, which may be stale by the time this lands).
`B-1` and `B-2` are **BUILD**; `B-3`, `B-4`, `B-5` are **WATCH**.

---

## 10. What this spec could not resolve

1. **The exact live front-page holding count.** Now **supported rather
   than cited** (§2.8): 8 `recurrence-suspect` events across 6 distinct
   records (measured here), of which 4 are `status: routed` with no
   `confirm-recurrence`/`dismiss-suspect` event anywhere (measured at the
   r1 gate, read-only). So the rendered count is bounded above by 4 and
   is almost certainly ≥2 — enough to make the Front defect live. The
   **exact** number still needs `report.recurrence_suspects()`'s own
   filter run against the real home, which both this author and the gate
   declined (probes are confined to a throwaway `SELF_LEARN_HOME`).
   Nothing in §6 depends on it, and §2.0's 14-record Bucket figure is now
   what carries the urgency argument.
2. **How often a bulk-collapse group or a merge cluster occurs.**
   Measured today: **never** — 16 proposal YAMLs all `already_canon:
   false`, zero `merge-*.yaml` (measured here, confirmed independently at
   the gate). Whether that changes as the analyst marks records
   `already_canon` is unmeasured. The §4.5 ruling does not depend on
   frequency — an un-armed multi-record write on a single keystroke is
   wrong at any frequency — but §2.0 is deliberate about which number
   sets priority: the 14-row Bucket page is live, these two are not.
3. **Whether the `MULTI_*` hint wordings are right.** They are plain
   words and they name the way out, which is the testable part. Whether
   an operator reading one actually knows what to do is a human
   acceptance item, not something §6 can settle.
4. **Whether `A1`/`A2`/`A3`/`A5` should exist at all once `[B-7]` lands.**
   They pin dispatch behaviour in a state that is reachable *because* of
   an open structural hole. That is honest today and will be wrong the
   day the hole closes. Flagged as a known expiry, not left for a future
   reader to discover as rot.
