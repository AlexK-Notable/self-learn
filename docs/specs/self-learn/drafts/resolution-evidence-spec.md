# Spec — make a confirmed resolution say what it did

**Status:** revision 2, folded from blind spec-gate findings. Awaiting
delta re-review.
**Origin:** two independent source-blind walks (`fixtures/ui-walks.md`,
W2-F2) plus a hand-driven session. Design ratified by the user
2026-07-26.

---

## 0. Rules for the builder (read first)

1. **Do not parse stdout to decide an outcome.** Success and failure come
   from the exit status. §3.1 says exactly what stdout may be read for,
   and why the pin permits it.
2. **Prefer existing typed attributes.** Most of what the evidence
   surface needs already exists on `VerbResult` or a compile result. Two
   fields do not and are added deliberately (§2.1); everything else you
   find yourself deriving is probably already there under another name.
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
| `canon_path` | `VerbResult.target` — the compiled destination. `None` for graduate and defer |
| `host_commit_sha` | `VerbResult.host_commit_sha` — `None` means nothing landed in canon (§3.3) |
| `ledger_paths` | `VerbResult.staged` — ledger records. Used **only** for reject's "moved to `resolved/`" |
| `commit_message` | `VerbResult.commit_message` — the **ledger** subject. Note it differs from the host apply subject built at `verbs.py:1811-1816`; if the host subject is wanted, add `host_commit_message` and say so |
| `created` | `SectionResult.bootstrapped` / `ReferenceResult.created` / `NewSkillApplyResult.scaffolded` |
| `no_op` | per result type — §3.3 |
| `deferred_until` | **NEW field on `VerbResult`** — §3.2 |
| `over_cap` | `VerbResult.over_cap_note()` |
| `pushed` | `VerbResult.push` (`PushResult(skipped=True)` when there is no remote) and `.host_push` |

Two fields are genuinely new: `deferred_until`, and optionally
`host_commit_message`. Everything else exists. Revision 1's claim that
*nothing* was new was wrong.

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
the commit subject; it is not a `VerbResult` field. The CLI currently
recovers it by string-parsing its own commit message
(`cli.py:994`, `result.commit_message.rsplit(" until ", 1)[1]`).
**Ruling: add `deferred_until: str | None` to `VerbResult`.** Parsing a
commit subject to render a UI fact is the same class of mistake as
parsing stdout for an outcome.

### 3.3 Three success states, not two

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

**Three states the surface must distinguish:**

1. **Landed in canon** — `host_commit_sha is not None`. Show the path.
2. **No-op** — `host_commit_sha is None` **and** the compile result
   reports no change. Show "nothing changed" and the existing file. The
   read is per result type, because they do not share a field:
   - `SectionResult.changed`
   - `ReferenceResult.applied`
   - `HookApplyResult.changed` (`verbs.py:962-968`)
   - `NewSkillApplyResult.changed` (`verbs.py:1685-1693`)
   - `UserScopeResult` has **no `changed` field** (`chezmoi.py:119-132`) —
     read `.section.changed` together with `.committed`
3. **Wrote successfully, no host commit by design** — user-scope routes
   and `claude-md:local`, which produce empty `host_paths` *on success*.
   These must **not** render as no-op and must **not** render as unknown.

Anything else with `host_commit_sha is None` is **unknown outcome** and
must say so explicitly. Silence standing in for success is the defect
being fixed; do not reintroduce it one level down.

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
| `cli.py` | `--json` on `route`/`reject`/`defer`/`graduate`; emit the §2.1 envelope. Follow `host commit-drift --json` (`cli.py:1176`). **Suppress `result.diff`** — a hook route prints the entire generated script to stdout first (`cli.py:913-914`), which would make the envelope unparseable. **stderr must be byte-identical** (§5). |
| `verbs.py` | Add `deferred_until` (and `host_commit_message` if §2.1 takes it). No behaviour change. |
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
on disk; assert a hook route's stdout parses.

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

**Routes.** Each verb renders its own shape; all three §3.3 states render
distinctly; unknown-outcome renders explicitly; success no longer
redirects **at each of the four sites**; the offer branches still render
the evidence.

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
- The no-op branch is only as good as the per-type reads in §3.3; a
  sixth result type added later without a read defaults to unknown,
  which is the safe direction but still a gap.

---

## 7. Definition of Done

1. All resolution paths in §5 emit a valid envelope, asserted per verb
   **and per destination shape**.
2. A malformed envelope on a zero exit still reports success.
3. `--json` leaves stderr byte-identical; the adopt offer still fires on
   a successful route.
4. Confirming a resolution names the record and shows the canon path —
   `target`, never `staged`.
5. All three §3.3 states render distinctly; anything else renders
   unknown-outcome text, not silence.
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
| Stop suppressing `result.diff` | hook-route envelope test |
| Remove the stderr `adopt_hint` print | adopt-offer route test |
| Invert one per-type no-op read | that type's no-op render test |
| Make a user-scope success report no-op | the §3.3 state-3 test |
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
