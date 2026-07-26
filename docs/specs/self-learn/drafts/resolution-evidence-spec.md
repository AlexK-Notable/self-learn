# Spec — make a confirmed resolution say what it did

**Status:** SHIPPED — built and code-gate CLEAN, commit `29d1672`.
Spec gate passed at revision 4 over four blind rounds; the code gate then
took two more, and §10 records what it caught. Read §10 before extending
this surface: every item there was invisible to a green suite.
**Origin:** two independent source-blind walks (`fixtures/ui-walks.md`,
W2-F2) plus a hand-driven session. Design ratified by the user
2026-07-26.

---

## 0. Rules for the builder (read first)

1. **Do not parse stdout to decide an outcome.** Success and failure come
   from the exit status. §3.1 says exactly what stdout may be read for,
   and why the pin permits it.
2. **Prefer existing typed attributes.** Most of what the evidence
   surface needs already exists on `VerbResult` or a compile result.
   **Four** fields do not and are added deliberately (§2.1); everything
   else you find yourself deriving is probably already there under
   another name.
3. **There are TWO commits in two repos.** This is the correction that
   revision 1 got wrong, and every other mistake in it followed from
   this one. See §2.1.
4. **The failure leg already works. Do not regress it.** The dirty-target
   refusal renders the target path verbatim plus an armed "Commit that
   repo's changes, then retry" button, deliberately composed *inside*
   `action_bar.html`'s existing `error` leg (routes.py:1381-1399: "no new
   region, O-9"). Reachable per §2.3.
5. **The argv verb is `reject`.** The UI label is "Deny"
   (`routes.py:52`). The envelope's `action` carries the argv name.
6. **Walk it after building.** Advertised-key-bound-to-nothing has
   shipped here twice (`c`, then `h`), and §3.6 is where this unit is
   most likely to make it three.

---

## 1. Problem statement

Confirming any resolution acknowledges nothing.

Measured across **three verbs × both input methods** (walk 2, W2-F2):
Defer, Deny and Graduate, by keyboard and by mouse, all land on the
bucket's *first pending record's* detail page. Never the list, never a
done state, never a toast, with nothing naming the record just resolved.
Walk 1 reported the same thing from the other side: *"a resolution I
believe landed but never saw confirmed."*

An acknowledgement mechanism does exist — re-requesting a resolved
record's URL redirects to `?notice=resolved-elsewhere` — but it fires only
if the user goes looking, and nothing indicates it exists.

Verification difficulty differs by verb in a way nobody would predict: a
**deferred** row stays visible in a muted ~60% state, so you can see it.
**Denied and graduated** rows vanish from the listing entirely, leaving
`/report`'s raw JSON counts as the only confirmation.

### 1.1 The asymmetry that names the fix

Measured 2026-07-26 in one sandbox at `--world analysed,dirty-target`,
by the path a human takes — no destination cycling, because the
`analysed` world supplies the destination:

| | routing a **git-hygiene** record (dirty target) | routing a **home-assistant** record (clean target) |
|---|---|---|
| Outcome | refused | succeeded |
| Where you end up | stays on the record | an **unrelated** record's page |
| What you are told | the full target path, the reason, and a remedy button | **nothing** |

The product already knows how to report a filesystem fact to a human. It
does it on failure and not on success. This unit removes the asymmetry;
it does not invent a capability.

### 1.2 Why the tests could not have caught it

The UI suite asserts rendered HTML for states it constructs directly. No
test asserts what a human is told *after a successful state transition*,
because "you are told nothing" is not a state anything renders. The gap
is a missing surface, and a missing surface has no template to assert
against.

---

## 2. Scope rulings

### 2.1 Two commits, two repos — the data model

**This is the load-bearing correction.** A resolution writes to *two*
repos and produces *two* commits, and the fields are not interchangeable:

| | repo | commit | paths |
|---|---|---|---|
| **Ledger** | `$SELF_LEARN_HOME` | `VerbResult.commit_sha` / `.commit_message` | `VerbResult.staged` |
| **Canon (host)** | the host repo | `VerbResult.host_commit_sha` | `VerbResult.target` |

`staged` comes from `_commit_ledger` → `gitops.stage(home, touched)`
(`verbs.py:371-394`), where `home` is the **ledger**. Verified: a real
`route --dest skill-md` returns `staged = ['<ledger>/skills/s/resolved/lrn-….md']`
while the file the human cares about is `target =
'<host>/…/SKILL.md'`.

**A toast sourcing its "paths written" from `staged` would show the user
a ledger record path on every verb** — including defer, where §3.2
explicitly forbids showing one. The canon path is `target`.

The envelope:

| Field | Source |
|---|---|
| `action` | `VerbResult.action` — the **argv** verb (`route`/`reject`/`defer`/`graduate`) |
| `record_id` | `VerbResult.record_id` |
| `canon_path` | `VerbResult.target`. **Assigned unconditionally** (`verbs.py:2169`), so it is set even when the write failed — see §3.3 state 4. `None` for graduate and defer |
| `host_commit_sha` | `VerbResult.host_commit_sha` — `None` has **four** possible meanings (§3.3) |
| `ledger_paths` | `VerbResult.staged` — ledger records. Used **only** for reject's "moved to `resolved/`" |
| `commit_message` | `VerbResult.commit_message` — the **ledger** subject |
| `destination` | **NEW** — `spec.destination`. `None` on non-route verbs |
| `variant` | **NEW** — `spec.variant` (`rules` / `local` / `None`). Required to key §3.3 state 3 |
| `deferred_until` | **NEW** — `str \| None` |
| `warnings` | `VerbResult.warnings` — §3.7 |
| `created` | `SectionResult.bootstrapped` / `ReferenceResult.created` / `NewSkillApplyResult.scaffolded`. **`bootstrapped` means the managed-section MARKERS were absent and got appended** (`compilers.py:118`) — not that the file was created. For `claude-md` the file genuinely is created first (`verbs.py:1663`); for `skill-md` it never is (preflight refuses). Distinguish the two, or the surface will claim it created a file it appended to |
| `outcome_state` | **NEW, and the field this unit turns on.** `"landed" \| "no_op" \| "wrote_uncommitted" \| "drift" \| "unknown"`, derived **CLI-side** per §3.3. Subsumes what would otherwise be a `no_op` boolean |
| `over_cap` | `VerbResult.over_cap_note()`. Safe across result types via its `getattr`; `NewSkillApplyResult.over_cap` is a *property* delegating to `.section` (`verbs.py:1695-1697`), so a sixth result type without one quietly returns `False` |
| `pushed` | Three distinct states the surface must tell apart: **pushed** / **you chose not to** (`VerbResult.push is None`, i.e. `--no-push`, `verbs.py:397-403`) / **nowhere to push** (`PushResult(skipped=True)` from `push_if_remote`). Same for `.host_push` |

**No `host_commit_message`.** The host subject is
`f"self-learn: apply {record_id} → {rel} ({spec.destination})"`
(`verbs.py:1811-1816`) — every component is already in the envelope once
`destination` is. Shipping the formatted string would invert §3.1's own
doctrine: the envelope carries machine structure and the *surface* does
the human formatting. A sentence the CLI wrote for a terminal should not
be echoed into a web page.

**Four fields are genuinely new.** Three of them — `destination`,
`variant`, `deferred_until` — share one reason: **stop parsing prose for
UI facts.** The CLI currently recovers both by string-parsing its own
commit subjects (`cli.py:931-934` `_routed_destination`, splitting on
`→`; `cli.py:994` splitting on `" until "`). The fourth,
`outcome_state`, exists because a predicate must be evaluated on the side
of the process boundary that holds its inputs (§3.3). Revision 1's claim
that *nothing* was new was wrong.

**Scope the `_routed_destination` retirement to `route` only.** It has
**two** call sites — `cli.py:974` (route) and `cli.py:1006`
(**`rehome`**). `rehome`'s `VerbResult` sets neither `target` nor any
destination (`verbs.py:2885-2892`), and the thing after the arrow in its
subject is a **bucket** (`projects/<slug>`), not a canon target. `rehome`
is not in the `--json` set; it keeps `_routed_destination`. Do not
"finish the cleanup" — it would change rehome's output for no gain.

**Adding the fields is safe** (checked, not assumed): all 11
`VerbResult(...)` sites are keyword-form with `action=` first; nothing
uses `dataclasses.asdict`/`fields()` over it; no CLI test references
`VerbResult` by name; the UI never touches it, only the subprocess
boundary; and it is a plain non-frozen dataclass whose every field after
`staged` already has a default.

### 2.2 One outcome surface, not two

The failure leg is not a new region by deliberate design
(routes.py:1381-1399). A separate floating success region beside an
in-place failure strip would give the product two shapes for outcomes
differing only in sign. **Ruling: one surface, two legs** — the existing
`action_bar.html` gains a success leg, reusing the same
`hx-swap="outerHTML"` target the failure leg already renders into
(`routes.py:1238`), where success today returns only a bare `HX-Redirect`
(`routes.py:1267-1269`).

**Confirmed by the user 2026-07-26:** *"toast was more just a concept I
was trying to convey, not a verbatim requirement."* The binding
requirements are evidence, persistence, and a user-chosen destination.
Do not spend design effort making this look like a floating toast.

### 2.3 The refusal leg is in scope only as a regression guard

To reach it:

```bash
uv run --project . python tools/sandbox_ui.py \
    up --fresh --world analysed,dirty-target
```

Then Approve → Confirm any git-hygiene record. `analysed` is required:
`_resolve_destination` raises `NoProposalError` (`verbs.py:493`) in route
step (c), before `_resolve_target`'s `_abort_if_dirty`. The ordering
holds only when no `--dest` is sent; `build_argv` adds one whenever
`dest` is truthy (`routes.py:106-107`), which the `o` cycle button sets.

### 2.4 Out of scope

- **Undo.** A graduate writes outside the ledger, so it is not one
  transaction. Assume it arrives later; do not build it.
- **The other `ui-walks.md` findings** — the `h` label, the destination
  cycler's unreachable default, sort direction, `b` not toggling.
- **`already_canon`.** A proposal field the analyst sets and the human
  reads; `verbs.py` never consults it. It is **not** the no-op path.

---

## 3. Design decisions

### 3.1 Evidence transport — restore the contract's own wording

`RealRunner` carries the pin "Outcome is ALWAYS the subprocess's exit
status + stderr — never parsed stdout" (`runner.py:213`). Read alone it
forbids this unit. Read against its own sources it does not:

- `07-review-ui.md:163-164`, contract 2: *"**`--json` on the read verbs**
  — the TUI parses structures, not human-formatted text."* That is a
  mandate to parse machine structure.
- `09-surface-spec.md:606-607`: *"Outcome renders from the verb's exit
  status and the subsequent file-state refresh — never by parsing
  **human-formatted** stdout (07 §4 contract 2)."*

`runner.py:213` **dropped the qualifier**. A JSON envelope is not
human-formatted stdout, so no carve-out is needed and none should be
written. **Amend `runner.py:213` to restore 09 §3's wording** — this is a
correction of a paraphrase that drifted, not a new exception.

**Chosen:** pass `--json`; `RunResult` gains `evidence: dict | None`,
populated only when the envelope parses **and** the exit status is
already success.

- Success/failure is decided by exit status alone. Unchanged.
- `stderr` is surfaced verbatim on failure. Unchanged.
- **A missing, truncated or unparseable envelope must not move the
  outcome.** The action still succeeded; the surface degrades to generic
  success text and says the details could not be read.

**Rejected:** a second `_invoke_json`-style read after the verb returns.
It can disagree with the call it describes — `routes.py:1281-1290`
documents that exact unsoundness class for `route` — and it could not
see `target` or `host_commit_sha` at all, since the ledger files do not
carry them.

### 3.2 Content is verb-shaped

| Verb | What it says | Sourced from |
|---|---|---|
| **route** | the canon path, **created** vs **appended**, over-cap warning | `target`, `created`, `host_commit_sha` |
| **graduate** | the record was retired; the host commit if there was one. **No created/appended** — graduate *retires* an entry via `_retirement_host_phase`, and its `VerbResult` carries neither `target` nor `compile_result` (`verbs.py:2960-2972`) | `host_commit_sha` |
| **defer** | the snooze date. **No path** — nothing was written outside the ledger | `deferred_until` |
| **reject** | moved to `resolved/`; the record id | `ledger_paths` |
| **no-op** | "nothing changed", **plus the existing file** | §3.3 |

`deferred_until` is computed at `verbs.py:2765` and used only to build
the commit subject; it is not a `VerbResult` field. The CLI recovers it
by string-parsing its own commit message (`cli.py:994`), exactly as
`_routed_destination` recovers the destination (`cli.py:931-934`).

**Ruling: add `deferred_until`, `destination` and `variant` to
`VerbResult`.** Parsing a commit subject to render a UI fact is the same
class of mistake as parsing stdout for an outcome, and one ruling retires
both existing parses rather than adding a field per symptom.

### 3.3 Four success states, not two

Revision 1 asserted the no-op signature was `staged == []`. That is
wrong: `staged` is the ledger paths and is non-empty on every successful
resolution. `host_paths` — the list the no-op logic actually keys on — is
local to `_apply_target` and never reaches `VerbResult`.

**The real gate** is `verbs.py:1806-1808`:

```python
if spec.host_repo is not None and host_paths:
    changed = getattr(compile_result, "changed", None)
    applied = getattr(compile_result, "applied", None)
    if changed is not False and applied is not False:
        ...  # host commit happens here
```

so the observable signal at the `VerbResult` boundary is
**`host_commit_sha is None`**. But that value is ambiguous three ways,
and `host_paths` differs per destination:

| destination | `host_paths` | line |
|---|---|---|
| hook | `[] if not changed` | 1617 |
| reference | `[compile_result.path]` — unconditional | 1624 |
| **user scope** | `[]` — **unconditional, even on success** | 1648 |
| skill-md / claude-md / new-skill | `[spec.target]`, except `variant == "local"` → `[]` **on success** | 1671 |

Revision 1 cited line 1617 as the managed-file branch. It is the **hook**
branch. The managed-file branch is 1671 and is unconditional on
`changed`.

**Which side evaluates this — the whole point of `outcome_state`.**

Every predicate below reads `compile_result`, a Python object that exists
**only inside the CLI process**. The UI receives an envelope, never that
object. So:

- **The CLI derives `outcome_state`** using the predicates below, because
  it is the only side holding the inputs.
- **The surface renders per `outcome_state`** and evaluates no predicate
  of its own.

Without this the UI cannot tell **drift** from **unknown** — both arrive
as `host_commit_sha: null` with no compile result to inspect — and its
only remaining signal would be substring-matching `"HOST PHASE FAILED"`
out of `warnings`, which is the exact move §3.7 forbids one section
later. Two builders would resolve that differently and the grep-based one
would pass every test.

This is the same gap class §6 names: *a predicate stated over an object
one side of a boundary holds and the other does not.* It recurred here in
the act of fixing it.

**Four states, plus unknown:**

1. **`landed`** — `host_commit_sha is not None`. Show the path.

2. **`no_op`** — `host_commit_sha is None`, `compile_result is not None`,
   and the result reports no change. Show "nothing changed" **and the
   existing file**. The read is per result type, because they do not
   share a field:
   - `SectionResult.changed`
   - `ReferenceResult.applied`
   - `HookApplyResult.changed` (`verbs.py:962-968`)
   - `NewSkillApplyResult.changed` (`verbs.py:1685-1693`)
   - `UserScopeResult` has **no `changed` field** (`chezmoi.py:119-132`) —
     read `.section.changed` together with `.committed`

3. **`wrote_uncommitted`** — wrote successfully; not committed, by
   design. Key it explicitly —
   **`isinstance(compile_result, UserScopeResult) or variant == "local"`**
   — not by inference. This is why `variant` is in the envelope: a
   `claude-md:local` route produces a plain `SectionResult` with
   `changed=True`, and *nothing else on `VerbResult` separates it from a
   managed claude-md route*.

   **Say why, do not shrug.** For `local` the absence of a commit is a
   **privacy guard**, not an implementation detail (`verbs.py:1665-1671`):
   the target is gitignored by design, "the file stays written on disk,
   outside git, forever". A user shown "wrote it, no commit" about their
   private rules file must be told that not-committing *is the feature*.

4. **`drift`** — ledger committed, canon did NOT land. Key:
   **`compile_result is None and host_commit_sha is None`**. Every
   success path sets a compile result, so `None` means `_host_phase`
   caught one of `_HOST_PHASE_ERRORS` (`verbs.py:1761-1769`) and returned
   `(None, None)` at :1845-1852.

   **This state exits 0.** `_finish_verb` only changes the exit code for
   a *push* failure (`cli.py:925-928`), so the UI sees success. And
   `canon_path` **is set anyway**, because `target=spec.target` is
   assigned unconditionally (`verbs.py:2169`).

   So this is the one case where the path names a file the verb did not
   write, and §7.4 must not apply to it. **Suppress or qualify
   `canon_path` here** — either rendering satisfies the DoD, because §8's
   row fails under both. Rendering a confident path over a failed write
   is the same defect this unit exists to fix, wearing the opposite face.

   **But whichever you choose, the drift state must still name the
   target** — as the file to *check*, explicitly not as the file written.
   The repair is target-scoped, and the warning text does not reliably
   supply it: it interpolates `{exc}`, and only some of those name a path
   (`compilers.py:276` "managed target does not exist: {path}" does;
   `compilers.py:245-248` "expected exactly one begin/end pair" does not).
   Suppressing outright would lose which file went stale.

   It is also the *most* known state in the system, not the least: it has
   a name, a documented repair, and the repair sentence is already in
   `VerbResult.warnings` — *"HOST PHASE FAILED after the ledger commit …
   canon is stale, never lost (H-2); run `self-learn recompile` to
   repair"*. Surface it verbatim.

Anything else with `host_commit_sha is None` is **`unknown`** and the
surface must say so explicitly. Silence standing in for success is the
defect being fixed; do not reintroduce it one level down.

### 3.7 Warnings are envelope fields, not stderr prose

`VerbResult.warnings` is a typed `list[str]` carrying the drift repair
instruction (`verbs.py:1851`), the orphaned-follow-up warning (:297-313),
`sync_warning` and `adopt_hint` (:1826-1841).

`_finish_verb` prints them to stderr **unprefixed** (`cli.py:921-922`),
so recovering them from `RunResult.stderr` means substring-matching
prose — the move §3.2 rules out for `deferred_until`, and which
`_extract_adopt_path` already does elsewhere.

**Ruling: `warnings` joins the envelope.** It is already a typed
attribute, so this costs no derivation. The success leg renders them.
They stay on stderr as well, unchanged, because §5's byte-identical rule
requires it.

The same surface also fixes "Force run gives no response" (walk 1).

### 3.4 Do not navigate away on success — at four sites

`action_confirm` has success returns that never reach the redirect, and
there is a second confirm path entirely:

| Site | Today |
|---|---|
| `routes.py:1253-1254` | success + `contradicts_pre` → `_contradicts_offer_response` |
| `routes.py:1260-1263` | success + adopt signal → `_adopt_offer_response` |
| `routes.py:1266-1269` | the `HX-Redirect` |
| `routes.py:2013-2032` | **pane-proposal confirm** — its own `build_argv`, `runner.run`, offer branches and `HX-Redirect` (incl. a `kind == "bucket"` variant) |

Fixing only the third leaves the proposal-confirm path silently
teleporting the user while the DoD passes.

**Ruling on the offer branches:** the offer *composes with* the evidence
— an adopt or contradicts offer is an additional decision about a
resolution that already happened, so suppressing the evidence hides the
thing the offer is about.

Buttons: **next pending record** · **back to the bucket** · **view what
changed**. Staying put means the user watches the row change state in
place, which is better evidence than any message.

### 3.5 Persistence needs a named mechanism

The success leg lives in `action_bar.html`, an htmx `outerHTML` target
that any SSE broadcast re-renders. The **error** strip survives only
because of the Y-16 leg at `app.js:461`:

```js
if (document.querySelector("[data-verb-error]")) return true;  // defer the reload
```

`action_bar.html:12-18` records why, and the note is a warning aimed
directly at this unit:

> a failed verb's error + the U20 commit-drift button were reload-wiped
> before the human could read/act on them (**FakeRunner tests never push
> the post-subprocess refresh, so this was invisible to the suite**).

**Ruling:** the success leg carries a `data-verb-success` marker joining
the same Y-16 chokepoint. `app.js` is in scope (§4). Without this, DoD #3
and #6 pass under `FakeRunner` while the real strip is wiped — this
project's signature bug, at the exact file being extended.

09 §3's "no state that isn't a file" (echoed `routes.py:43-45`)
constrains how the marker may be held: it is DOM presence, not a
JS-side session object.

### 3.6 Keymap — the defect was ambiguity, not absence

`app.js:55` dispatches `document.querySelector('[data-key-action="…"]')`
— one global lookup, first match in document order, no context filter
(`keymap.py:33-35`: every key is unique across the whole table, and that
is tested). The `c` failure (`keymap.py:88-102`) was **not** a missing
entry: three co-rendered partials carried the same
`data-key-action="confirm"` and document order resolved it to the wrong
one.

So "every printed key resolves to its button's handler" **passes when a
duplicate exists** — it resolves, just to the wrong element.

**Requirements:**

- Assert `data-key-action` **uniqueness in the rendered document** with
  the success leg up, on Detail and Bucket, alongside
  `host_add_bar.html`.
- Scoping is **DOM presence**, not a context-filtered dispatcher. The
  buttons leave the DOM and the selector finds nothing. Do not add
  context filtering — it would break the global-uniqueness invariant the
  keymap tests rely on. Free keys today: `h j k l m u v z`.
- `h` is currently printed on the header back-link and bound to nothing
  (`ui-walks.md` W2-F1). **Do not claim `h`** without fixing that first,
  or the uniqueness test will encode the existing bug.

---

## 4. Per-change table

| Area | Change |
|---|---|
| `cli.py` | `--json` on `route`/`reject`/`defer`/`graduate`; emit the §2.1 envelope. Follow `host commit-drift --json` (`cli.py:1176`). **Under `--json`, stdout is the envelope and NOTHING else** — `_finish_verb` also prints `result.diff` (a hook route's entire generated script, :913-914) and `result.post_notes` (multi-line prose, :919-920; set by hook *and* new-skill routes, `verbs.py:2153-2158`). Suppressing only `diff` still yields JSON-then-prose. **stderr must be byte-identical** (§5). |
| `verbs.py` | Add `deferred_until`, `destination`, `variant`. No behaviour change. |
| `runner.py` | `RunResult.evidence: dict \| None`; parse only on success; never let a parse failure move the outcome. Restore 09 §3's "human-formatted" wording at :213. |
| `routes.py` | Pass `--json`; carry evidence into context; stop redirecting at **all four** sites (§3.4). |
| `action_bar.html` | Success leg beside the `error` leg, carrying `data-verb-success`. |
| `app.js` | Extend the Y-16 chokepoint (:461) to defer on the success marker. |
| `style.css` | Persistent strip; no auto-dismiss. |
| `keymap.py` | Success-leg bindings + the uniqueness test (§3.6). |

---

## 5. Test plan

**CLI envelope.** One per verb — route-append, route-create, defer,
reject, graduate — plus one per destination shape that differs
(reference, user-scope, `claude-md:local`, hook, new-skill). Assert
exact fields; assert `--json` changes neither exit status nor what lands
on disk; assert **stdout parses as JSON and contains nothing else** for a
hook route (which prints a script) and a new-skill route (which prints
`post_notes`).

**The drift state (§3.3 state 4) — two tests at two layers. Do not write
one test spanning both**, or the weaker half is what gets asserted.

*CLI layer, real fixture, no monkeypatching.* These tests run the real
binary as a subprocess, so patching is impossible by construction — and
unnecessary. `_HOST_PHASE_ERRORS` includes `CompileError`
(`verbs.py:1761-1769`), and `compile_managed_file` raises it on broken
markers (`compilers.py:237-248`). **Fixture: seed the skill-md target
with an unbalanced marker pair, then route.** A real user reaches this by
hand-editing inside the managed section. Assert exit status **0**,
`outcome_state == "drift"`, `host_commit_sha` null, the warning present,
and the target still named. (`OSError` via a read-only parent is a second
trigger if a non-`CompileError` variant is wanted.)

*Render layer.* Inject a drift envelope directly — no fixture needed —
and assert the surface does not present `canon_path` as written while
still naming it as the file to check.

**stderr is byte-identical under `--json`.** Two live behaviours read it:
`_extract_adopt_path(result.stderr)` gates the adopt offer on a
*successful* route (`routes.py:1261`), and `_commit_drift_eligible`
gates the dirty-target button (`routes.py:1227`). `_finish_verb` writes
warnings and `over_cap_note()` there (`cli.py:905-928`), and
`_host_phase` prints `sync_warning`/`adopt_hint` (`verbs.py:1826-1841`).
A builder who "moves the warnings into the envelope" silently kills the
adopt offer.

**Runner.** Evidence parses on success; malformed stdout on a zero exit
still reports success with `evidence = None`; stdout is never consulted
for outcome (mutate the envelope to claim failure — the outcome must not
move).

**Routes.** Each verb renders its own shape; all **four** §3.3 states
render distinctly — including `claude-md:local` as state 3 and not as
no-op; unknown-outcome renders explicitly; success no longer redirects
**at each of the four sites**; the offer branches still render the
evidence.

**Persistence.** A test that **pushes a post-verb refresh** — the thing
`FakeRunner` tests never do — and asserts the success leg survives it.

**Keymap.** Uniqueness of `data-key-action` in the rendered document with
the success leg up.

**Perceptual (browser).** The strip is *perceptible* after a confirm, not
merely present — this codebase has shipped an `opacity: 0` element that
`is_visible()` called visible.

**Walk (not a gate).** One source-blind walk at
`--world analysed,dirty-target`, which reaches success and refusal in one
sitting. Findings are observations, not pass/fail.

---

## 6. What this unit does NOT claim

- It does not make resolutions safer, only legible.
- It does not prove the write landed where the user *wanted* — only where
  the verb put it.
- It does not address the other `ui-walks.md` findings.
- The success leg is only as truthful as `target` / `host_commit_sha`.
  §3.3 state 4 closes the one case where `target` actively lies; there
  may be others.
- The no-op branch is only as good as the per-type reads in §3.3; a
  sixth result type added later without a read defaults to unknown,
  which is the safe direction but still a gap. State 4 *was* that gap,
  already present rather than hypothetical — it was found by review, not
  by the design.

---

## 7. Definition of Done

1. All resolution paths in §5 emit a valid envelope, asserted per verb
   **and per destination shape**.
2. A malformed envelope on a zero exit still reports success.
3. `--json` leaves stderr byte-identical; the adopt offer still fires on
   a successful route.
4. Confirming a resolution names the record and shows the canon path —
   `target`, never `staged` — **when one was actually written**. In §3.3
   state 4 the path must not be presented as written.
5. All **four** §3.3 states render distinctly, `claude-md:local` among
   them; anything else renders unknown-outcome text, not silence. The
   state is carried by `outcome_state`, derived CLI-side — the surface
   evaluates no predicate over objects it cannot see.
6. Success no longer navigates away on its own, at **all four** sites.
7. The success leg survives a post-verb SSE refresh, asserted by a test
   that actually pushes one.
8. `data-key-action` is unique in the rendered document with the success
   leg up.
9. The refusal leg is unchanged — regression-verified in the
   `analysed,dirty-target` world, not by reading the code.

---

## 8. Mutation-verification plan

Every check must fail when the thing it checks is broken. Per
`lrn-ea833a5b`: ask what each check prints when it cannot see its target
at all; if that is identical to "pass", the check is worthless.

| Mutation | Must break |
|---|---|
| Drop `canon_path` from the envelope | CLI envelope tests |
| Point `canon_path` at `staged` instead of `target` | the "shows the canon path" test |
| Make `RunResult.evidence` always `None` | the path/sha **content** assertion (not merely "a success leg rendered") |
| Corrupt stdout JSON | evidence test fails, **outcome test still passes** |
| Print anything else to stdout (`result.diff`, a `post_notes` line) | hook-route and new-skill envelope tests |
| Remove the stderr `adopt_hint` print | adopt-offer route test |
| Invert one per-type no-op read | that type's no-op render test |
| Make a user-scope success report no-op | the §3.3 state-3 test |
| Make a `claude-md:local` success report no-op | the state-3 `local` test |
| Repair the fixture's broken markers | the §3.3 state-4 drift test |
| Emit `outcome_state: "unknown"` for a drift result | the drift **render** test |
| Emit `outcome_state: "no_op"` for a `wrote_uncommitted` result | the state-3 render test |
| Present `canon_path` as written in the drift state | the drift test's path assertion |
| Drop `warnings` from the envelope | the drift test's repair-instruction assertion |
| Remove the `data-verb-success` marker | the post-refresh persistence test |
| Duplicate a `data-key-action` target | the uniqueness test |
| Revert redirect suppression, **one site at a time** | four separate tests |
| Clean the host repo in the fixture | refusal regression test |

Rows 4 and 11 are the important ones. Row 4 proves evidence and outcome
are actually decoupled rather than merely described as such. Row 11
proves the four redirect sites are independently covered — a single
combined test would pass with three of them still broken.

---

## 9. Revision history

**Revision 2** folds a blind spec gate that returned 2 BLOCKERs and 7
MAJORs. Recorded because the errors are instructive, not to be tidied
away:

- Revision 1 claimed `VerbResult.staged` was "the paths written". It is
  the **ledger** paths. The canon path is `target`. Built as written, the
  surface would have shown a ledger record path on every verb — including
  defer, which the same document forbade.
- Revision 1's no-op predicate cited `verbs.py:1617` as the managed-file
  branch; it is the **hook** branch. The managed-file branch (1671) is
  unconditional on `changed`, `host_paths` never reaches `VerbResult`,
  and two destinations produce empty host paths *on success* — so the
  rule would have rendered successful user-scope and `local` routes as
  bugs.
- Both errors share one cause: a measurement of `compile_managed_file`
  returning `changed = False` was real, and the chain from there to
  `staged` was **inferred, then described as measured**. Verifying one
  link and asserting the chain is the failure mode this project's
  mutation discipline exists to catch, and it reached a spec anyway.
- The gate also found that §3.1's contract argument was unnecessary:
  `09-surface-spec.md:606-607` says "human-formatted stdout", and
  `runner.py:213` dropped the qualifier. The design needed a restoration,
  not a carve-out.

**Revision 3** folds the delta round (2 MAJOR, 2 MINOR, no blockers):

- **A fourth state exists and revision 2 sent it to "unknown".** When the
  host phase raises, `_host_phase` returns `(None, None)`, the verb still
  exits 0, and `canon_path` is set anyway because `target=spec.target` is
  unconditional. So the surface would have confidently named a file that
  was never written — the defect this unit exists to fix, inverted. It
  is also the most *knowable* state in the system: the repair sentence is
  already sitting in `VerbResult.warnings`. Now §3.3 state 4.
- **State 3 was inference, and half of it was unkeyable.** `user-scope`
  is identifiable by result type; `claude-md:local` is identifiable by
  *nothing* on `VerbResult`. Hence `variant` in the envelope, and an
  explicit key rather than prose.
- **`host_commit_message` rejected**; `destination` + `variant` added
  instead. Shipping a formatted git subject to a web page inverts §3.1's
  own doctrine, and the fields retire two existing prose-parses
  (`_routed_destination`, the `" until "` split) under one reason.
- `warnings` given a channel (§3.7) rather than left to a builder to
  substring-match back out of stderr.
- Suppressing `result.diff` was insufficient — `post_notes` also goes to
  stdout, so the rule is now "the envelope and nothing else".
- The `pushed` row regained the three-state distinction revision 2
  accidentally narrowed to two.

**Revision 4** folds one MAJOR — and it is the most instructive of the
four rounds, because the fix for finding 1 *committed finding 1's own
error*:

- Revision 3's four-state predicate keyed on `compile_result`, **an
  object that exists only inside the CLI process**. The envelope never
  carried it. So the UI could not tell `drift` from `unknown`, and its
  only remaining signal would have been substring-matching
  `"HOST PHASE FAILED"` out of `warnings` — the exact move §3.7 forbids
  one section later. Fixed by `outcome_state`, derived CLI-side: the
  predicate is evaluated on the side that holds its inputs, and the
  surface renders a value rather than computing one.
- §6 had already named this gap class in the abstract ("a predicate
  stated over an object one side of a boundary holds and the other does
  not") one revision before committing it. Recognising a failure mode is
  not the same as being immune to it.
- Q1's "suppress or qualify" latitude was kept — it is latitude over
  wording inside one template leg, bounded by a §8 row that fails under
  either choice, unlike `host_commit_message` which was latitude over an
  interface. But the two options were not informationally equivalent, so
  the drift state must now **name the target either way**, as the file to
  check.
- Q2: state 4 is reachable **without monkeypatching** — an unbalanced
  marker pair raises `CompileError` through a real subprocess. §5's
  wording was pushing a builder toward a patch that cannot work across a
  process boundary, whose documented fallback is constructing the
  `VerbResult` directly: the round-1 failure shape. The drift tests are
  now split by layer.
- Q3: the field addition is safe (11 keyword-form sites, no reflection,
  no test asserting the field set). But `_routed_destination` has a
  **second** caller — `rehome`, whose arrow carries a bucket, not a canon
  target — so the retirement is scoped to `route`.

---

## 10. What the code gate caught (two blind rounds, all mutation-verified)

Recorded because **every item here was invisible to a green suite**, and
because this is the list to read before extending this surface.

1. **`canon_path` read `staged`** — the ledger paths. The surface would
   have shown a ledger record path on every verb, including defer, where
   §3.2 forbade it. The canon path is `target`.
2. **A `reference` route rendered `None`.** Its `TargetSpec` carries no
   target by construction, and only one of four template branches guarded
   the field. The unit built to say what a resolution did would have said
   `in <code>None</code>`.
3. **"View what changed" navigated to the resolved-elsewhere banner** —
   the exact inadequate acknowledgement §1 says this unit replaces. It
   only worked for `defer`. Invisible because `FakeRunner` never changes
   record status.
4. **The no-op derivation had no coverage at any layer.**
   `_reports_no_change` could be replaced with `return False` and the
   whole CLI suite stayed green.
5. **The contradicts offer rendered the evidence once per EDGE**,
   duplicating keymap-bound actions and making §7.8's uniqueness
   invariant false in a reachable shape.
6. **A test comment claimed coverage it could not provide** — it cited
   `action_bar.html:99/107` for the unarmed quad, but those lines are the
   *armed* branch, and the count it asserted was 1 either way
   (`lrn-ea833a5b`).
7. **The defect §0 rule 6 predicted by name.** `style.css` gated the
   whole success-key group on the STRIP being present while the links
   inside are individually conditional, so a route confirm advertised `v`
   and `j` with neither bound — the third instance of
   advertised-key-bound-to-nothing here, arriving from a file §3.6 never
   mentions.

### 10.1 The check that closes item 7, and how it failed open twice

`TestSuccessFooterNeverAdvertisesADeadKey` is the first thing in this
repo that compares **what the page says** against **what the page can
do** — the invariant whose absence produced `c`, `h`, and now `v`/`j`.
It took three passes to become sound, and the two failures are the
lesson:

1. *"Every footer entry SHOWN has an element."* Fails open on a key with
   no CSS rule: `.keymap-footer-entry` defaults to `display: none`, so a
   missing rule is silence, and silence satisfies it. Measured — a fourth
   key with no rule left the whole suite green.
2. Adding *"every `success_*` element IS advertised"* closed that, but
   both halves iterate sets that can be empty, so a leg with **zero**
   links passes both vacuously. Measured by forcing one.
3. An anchor asserting *something rendered at all* now runs first. It
   names no key on purpose — pinning `success_bucket` would defend only
   the keys that already have rules, which is the blind spot (1) was
   rewritten to remove.

No reachable state produces a linkless leg today (`bucket_url` comes from
`locate_record`, which resolves out of `resolved/`; verified against the
real CLI for all four verbs), so the anchor guards **fixture drift**, not
a live defect. Keep it anyway: the shape it protects is one fixture
change away, and `success_next` is already absent from that fixture.

**The general rule this unit keeps re-teaching:** ask what a check
reports when it cannot see its target at all. If that equals "pass", the
check is worthless — and the more specific the check, the more likely
its blind spot is the exact case it was written for.
