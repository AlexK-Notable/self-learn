# Spec — make a confirmed resolution say what it did

**Status:** draft, awaiting blind spec gate.
**Origin:** two independent source-blind walks (`fixtures/ui-walks.md`,
W2-F2) plus a hand-driven session. Design ratified by the user
2026-07-26.

---

## 0. Rules for the builder (read first)

1. **Do not parse stdout to decide an outcome.** `RealRunner`'s pin —
   "Outcome is ALWAYS the subprocess's exit status + stderr — never
   parsed stdout" (07 §4 contract 2, runner.py:213) — stays intact. §4.1
   explains precisely what this unit is allowed to read from stdout and
   why that does not breach the pin.
2. **Nothing here computes new information.** Every field the toast shows
   already exists as a typed attribute on `VerbResult` or on a
   `compile_result`. If you find yourself deriving a fact, stop — you have
   probably re-implemented something the CLI already knows.
3. **The failure leg already works. Do not regress it.** The dirty-target
   refusal renders the target path verbatim plus an armed "Commit that
   repo's changes, then retry" button, deliberately composed *inside*
   `action_bar.html`'s existing `error` leg (routes.py:1381-1399: "no new
   region, O-9"). Verified reachable 2026-07-26 — see §2.3 for how.
4. **Walk it after building.** Toast buttons get keyboard equivalents,
   and advertised-key-bound-to-nothing has shipped here twice already
   (`c`, then `h`). A key hint that no keymap entry backs is a defect
   this unit is specifically likely to introduce.

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
both by the path a human actually takes (no destination cycling):

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
against. This is also why it took a walk to find it: the instrument's
premise is documenting experience, and the experience is the absence.

---

## 2. Scope rulings

### 2.1 The CLI work lands first, and it is small

`RealRunner` never sees the paths, because the CLI prints them on stdout
and the runner is contractually forbidden to read it for outcome. So the
resolution verbs need a `--json` mode.

This is smaller than it sounds. `host commit-drift --json` already prints
`{"repo", "files"}` (cli.py:1176) — a working precedent on the *sibling*
of this very feature — and `_invoke_json` already exists on the read path
(`ledger.py:108`). Everything the envelope carries is already a typed
attribute:

| Envelope field | Existing source |
|---|---|
| `action` | `VerbResult.action` |
| `record_id` | `VerbResult.record_id` |
| `paths_written` | `VerbResult.staged: list[Path]` |
| `commit_sha`, `commit_message` | `VerbResult.commit_sha` / `.commit_message` |
| `created` | `SectionResult.bootstrapped` / `ReferenceResult.created` |
| `no_op` | `SectionResult.changed is False` / `ReferenceResult.applied is False` |
| `over_cap` | `VerbResult.over_cap_note()` |
| `pushed` | `VerbResult.push` (`None` = `--no-push`) |

**Nothing in this unit computes a new fact.** It surfaces a structure
that already exists across a process boundary that currently drops it.

### 2.2 One outcome surface, not two

The failure leg is not a new region by deliberate design (routes.py:1389).
If success arrives as a *separate floating toast* while failure stays an
in-place strip, the product grows two differently-shaped feedback
surfaces for outcomes that differ only in sign.

**Ruling: one surface, two legs.** The existing strip gains a success leg
and the persistence + buttons the user asked for; it does not become a
second region. The user's requirements — filepaths, persistence,
navigation buttons — are all satisfied by this, and only the visual idiom
differs from a floating toast.

> **Flagged for the user before build.** This is the one place where the
> spec departs from the literal word "toast" in the ratified design. If a
> floating toast is wanted specifically, say so and §5 changes; the
> content and behaviour rulings below are unaffected either way.

### 2.3 The refusal leg is in scope only as a regression guard

It already works, and it is now walkable. To reach it:

```bash
uv run --project . python tools/sandbox_ui.py \
    up --fresh --world analysed,dirty-target
```

Then Approve → Confirm any git-hygiene record. `analysed` is required —
without it `route` raises `NoProposalError` before the dirty check, so
the refusal is unreachable by the human path.

### 2.4 Out of scope

- **Undo.** A graduate writes outside the ledger, so it is not one
  transaction. Design the layout assuming undo arrives later; do not
  build it here.
- **The other findings in `ui-walks.md`.** The `h` label, the destination
  cycler's unreachable default, sort-direction indicators, `b` not
  toggling. Recorded there, not fixed here.
- **`already_canon`.** It is a proposal field the analyst sets and the
  human reads; `verbs.py` never consults it. It is *not* the no-op path
  and must not be wired to one.

---

## 3. Design decisions

### 3.1 Evidence transport — one call, outcome unchanged

Two options exist and the choice is load-bearing:

**(a) A second `_invoke_json`-style read after the verb returns.** Keeps
`RealRunner` untouched, but it is a second invocation and can therefore
*disagree* with the first — the verb succeeded, the follow-up read sees a
concurrently-modified ledger, and the toast reports something that was
never true of this action. It also doubles the subprocess cost of every
resolution.

**(b) Pass `--json`, and let `RunResult` carry parsed stdout as
*evidence*, never as outcome.** — **Chosen.**

The pin exists so that pass/fail cannot be spoofed or mis-parsed out of
prose. Evidence is not pass/fail. Concretely:

- Success/failure is still decided by exit status alone. Unchanged.
- `stderr` is still surfaced verbatim on failure. Unchanged.
- `RunResult` gains `evidence: dict | None`, populated only when the
  envelope parses **and** the exit status is already success.
- **If stdout is missing, truncated, or unparseable, the outcome does not
  move.** The action still succeeded; the toast degrades to its generic
  success text and says it could not read the details. A malformed
  envelope must never turn a success into a failure — that would be
  exactly the coupling the pin forbids.

Amend the contract comment at `runner.py:213` to state this explicitly,
so the next reader does not have to re-derive whether this breached it.

### 3.2 Content is verb-shaped, not one template

A single "Saved!" with a path list is wrong for three of the four verbs.

| Verb | What the toast says |
|---|---|
| **route / graduate** | the destination path, and whether it was **created** or **appended to**; the commit subject; over-cap warning when present |
| **defer** | the snooze date. No path — nothing was written outside the ledger, and showing a ledger path would imply otherwise |
| **deny** | moved to `resolved/`; the record id it applied to |
| **no-op** | "nothing changed" **and the existing file(s)**, so the user can check for themselves |

Worked example, measured — this exact route produced this exact commit:

```
self-learn: apply lrn-fcaa3e1a → plugins/home-assistant-plugin/skills/home-assistant/SKILL.md (skill-md)
1 file changed, 4 insertions(+)
```

### 3.3 The no-op branch, with a measured predicate

Pinned early because silence and success currently look identical, and it
is the hardest case to retrofit.

**Predicate (measured, not assumed):** `compile_managed_file` returns
`SectionResult.changed = False` when the record's entry is already
present in the target. Verified 2026-07-26 by recompiling a
just-routed record against its own destination: `changed = False`,
`bootstrapped = False`, `entry_count = 1`. `verbs.py:1617` then sets
`host_paths = [] if not changed`, so the no-op signature at the
`VerbResult` boundary is **`staged == []`**, and the recompile path
(verbs.py:3601) skips the commit entirely on the same condition.

The toast must therefore distinguish:

- `staged == []` **and** `no_op` → "nothing changed", listing the
  existing file(s).
- `staged == []` **and not** `no_op` → this is a *bug*, not a no-op.
  Render it as an unknown outcome and say so, rather than silently
  claiming nothing changed. Silence and success looking identical is the
  defect being fixed; do not reintroduce it one level down.

The same surface also fixes "Force run gives no response" (walk 1) —
it is the same missing-acknowledgement shape.

### 3.4 Do not navigate until the user clicks

Currently a confirm lands the user on an unrelated record. Staying put
means they watch the row change state in place, which is better evidence
than any message — and it makes the buttons meaningful rather than
decorative.

Buttons: **next pending record** · **back to the bucket** · **view what
changed** (the commit, or the target file). Exact set to be settled at
build time against what the templates can already reach.

### 3.5 The toast persists

Buttons imply clickability; an auto-dismiss timer partly recreates the
bug being fixed. It clears on the next action or on explicit dismiss.

### 3.6 Keyboard equivalents — the most bug-prone part

Buttons need keys, live only while the toast is up, not colliding with
the page's existing bindings. Advertised-key-bound-to-nothing has shipped
here **twice** (`c`, fixed 2026-07-25; `h`, still open). Requirements:

- Every key printed on the toast has a keymap entry that resolves to the
  same handler the button calls.
- A test asserts label↔keymap agreement mechanically, not by eye. The
  two `c`/`h` instances happened because printed hints and the live
  keymap drift apart with nothing in CI comparing them.
- The scoped keymap deactivates when the toast clears.

---

## 4. Per-change table

| Area | Change |
|---|---|
| `cli.py` | `--json` on the resolution verbs; emit the §2.1 envelope on stdout. Follow `host commit-drift --json`'s existing shape. |
| `verbs.py` | No behaviour change. Expose the envelope from `VerbResult` + `compile_result`; add nothing new to either. |
| `runner.py` | `RunResult.evidence: dict | None`; parse only on success; never let a parse failure move the outcome. Amend the contract comment at :213. |
| `routes.py` | Pass `--json`; carry evidence into the render context. Stop redirecting to an unrelated record on success. |
| `action_bar.html` | Success leg beside the existing `error` leg. |
| `style.css` | Persistent outcome strip; no auto-dismiss. |
| `keymap.py` | Scoped toast bindings + the label↔keymap agreement test. |

---

## 5. Test plan

**CLI envelope (pytest).** One per verb: route-append, route-create,
route-no-op, defer, deny, graduate. Assert exact fields, and that
`--json` does not change the exit status or what lands on disk.

**Runner (pytest).** Evidence parses on success; **malformed stdout on a
successful exit still reports success with evidence `None`**; stdout is
never consulted for outcome (mutate the envelope to say `"failed"` and
assert the outcome is unmoved).

**Routes (pytest).** Each verb's success renders its own shape;
`staged == []` with `no_op` renders "nothing changed"; `staged == []`
*without* `no_op` renders the unknown-outcome text; success no longer
redirects.

**Keymap (pytest).** Every key printed on the toast resolves to the
handler its button calls — mechanically, over the rendered template.

**Perceptual (browser).** The strip is *perceptible* after a confirm, not
merely present — this codebase has already shipped an `opacity: 0`
element that `is_visible()` called visible.

**Walk (not a gate).** After building, one source-blind walk at
`--world analysed,dirty-target`, which reaches success and refusal in one
sitting. Findings go to `ui-walks.md`; they are observations, not a
pass/fail.

---

## 6. What this unit does NOT claim

- It does not make resolutions *safer*, only legible.
- It does not prove the write landed where the user wanted — only where
  the verb put it.
- It does not address the other `ui-walks.md` findings.
- The success leg is only as truthful as `VerbResult.staged`. If a verb
  ever stages a path it does not write, the toast will faithfully report
  the lie. Out of scope to defend against; worth knowing.

---

## 7. Definition of Done

1. All six resolution paths emit a valid envelope, asserted per verb.
2. A malformed envelope on a zero exit still reports success. **Mutation:
   corrupt the JSON; the outcome must not move.**
3. Confirming a resolution names the record and shows the paths, for all
   four content shapes in §3.2.
4. The no-op branch renders "nothing changed" **plus the existing file**,
   driven by the §3.3 predicate.
5. `staged == []` without `no_op` renders unknown-outcome text, not
   silence.
6. Success no longer navigates away on its own.
7. Every printed key resolves to its button's handler, asserted
   mechanically.
8. The refusal leg is unchanged — the dirty-target path still shows the
   target and the commit-first button. **Regression-verified in the
   `analysed,dirty-target` world, not by reading the code.**

---

## 8. Mutation-verification plan

Every check must fail when the thing it checks is broken. Per
`lrn-ea833a5b`: ask what each check prints when it cannot see its target
at all, and if that is identical to "pass", the check is worthless.

| Mutation | Must break |
|---|---|
| Drop `paths_written` from the envelope | CLI envelope tests |
| Make `RunResult.evidence` always `None` | routes success-render tests |
| Corrupt stdout JSON | evidence test fails, **outcome test still passes** |
| Invert the `no_op` predicate | no-op render test |
| Force `staged = []` on a successful append | unknown-outcome test |
| Remove one toast keymap entry | label↔keymap agreement test |
| Revert the redirect suppression | "stays put" test |
| Clean the host repo in the fixture | refusal regression test |

The third row is the important one: it is the check that proves evidence
and outcome are actually decoupled, rather than merely described as such.
