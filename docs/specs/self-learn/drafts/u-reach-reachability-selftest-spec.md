# Spec — U-reach: the reachability selftest, a `route` telemetry kind, and `routing.by`

Status: **r2 — SPEC GATE PASSED**, 9 findings folded, 0 blockers.
Cleared for build. Campaign unit `U-reach`
(`forward/r2-routing-campaign.md` §2, Wave 1). Register rows **FW-40**
(the reachability selftest half) and **FW-45**. Implementation reference:
`misc/routing-procedure-r2.md` **B9**. Evidence base:
`research/2026-07-27-routing-monoculture-and-pin-audit.md` §3, §2, §11.

**Acceptance criteria (§4) and the mutation plan (§5) ARE the spec.**
Everything else is rationale. **Where prose and the criteria conflict, the
criteria win.**

**This unit builds the detector and the instrument, never the cure.** The
pointer emission that would make the R14 set reachable is `U-pointer`, a
later wave, additionally blocked on an open human decision (`14 §4`, "What
should `reference` DO?"). A build that emits a pointer destroys this
unit's own positive control and collides with a blocked unit.

---

## 1. The defect

### 1.1 The measured fact — the **R14** set

**R14** = the 14 resolved records whose `routing.destination` is
`reference`. Defined here, once; referenced by name everywhere below and
never re-enumerated.

Re-measured against the live ledger **2026-08-02** (the audit's numbers
held):

| property | value |
|---|---|
| size | 14 |
| bucket | all `skills/home-assistant`, scope `skill:home-assistant` |
| status | all `routed`, all `superseded_by: null` |
| `routing.reference_file` | absent on all 14 ⇒ the default `LEARNINGS.md` |
| target file | `<skills-root>/plugins/home-assistant/skills/home-assistant/references/LEARNINGS.md` (exists, 14 KB) |
| reachable | **zero of 14** |

**Nothing anywhere names that file.** Case-insensitive search for
`LEARNINGS` across the whole `plugins/home-assistant/` tree returns
exactly one file — `LEARNINGS.md` itself. **Positive controls, same
tree, same command, 2026-08-02:** `GOTCHAS` → 8 files, `Home Assistant`
→ 10 files. The search discriminates; the absence is real.

Sharper control, on the *same surface that fails*: the skill's `SKILL.md`
names **7 of the 9 files** in its own `references/` directory
(`TOPOLOGY.md`, `CAPABILITY-MAP.md`, `STORAGE-SCHEMA.md`, `ASSIST.md`,
`GOTCHAS.md`, `GOTCHAS.journal.md`, `INVENTORY.generated.md`) and does
not name `LEARNINGS.md`. One file, one parser, seven trues and one false.

`SKILL.md` also contains **zero** occurrences of `self-learn` and zero
managed-section markers (control: `references` appears 15 times, so grep
can see the file). There is no managed section to have gone stale — half
the routed corpus was written into a document with no path leading to it,
and none was ever cut.

### 1.2 The instrument that certified this state as healthy

Run against the real ledger, 2026-08-02, before this unit:

```
selftest: PASS drift — 28 routed record(s) present in their compiled targets
selftest: all 6 checks green
rc=0
```

`_check_drift` (`selfcheck.py:281-404`) verified that each of R14's ids
**is inside `LEARNINGS.md`** and called that success. It answers "did the
write land?", which was never the question. Nothing in the system asks
"can anything get to it?" — so `--selftest` returns 0 on a host where
half the routed corpus is undeliverable. That is this project's signature
bug in its purest form: **a check reporting success because it cannot see
its target at all.**

### 1.3 `routing.by` is a hardcoded constant, and on one live path it is false

Two write sites, both literal:

- `verbs.py:2325` — `route_direct` builds `{"routed_at": …,
  "destination": destination, "by": "human"}`.
- `ledger_ops.py:756` — `resolve_record(by: str = "human")`; `route()`
  (`verbs.py:2053-2076`) never passes `by`, so it takes the default.

It reads `human` on all 28 routed records. Three consequences:

1. **It cannot fail.** If an autonomous router existed tomorrow (12 §A2's
   ladder L1/L2 contemplates exactly that), the field would still print
   `human`. The pin audit
   (`research/2026-07-27-raw/pin-audit.md:224, :242, :505`) cites
   "32/32 routings `by: human`" as evidence that **A13** ("propose only,
   never route") and **M-1** ("mined records never auto-route") hold.
   That is a constant read as a measurement. It was never evidence.
2. **It is already false on a live path.** `teach --route` with no
   `--dest` takes its destination from `analyst.analyze()`
   (`teach.py:670-694`), prints it *after* the fact, and routes with no
   confirmation prompt (08 §1 pin: invocation is the approval). The
   destination on that path was chosen by a model, and the ledger says a
   human chose it.
3. **The one discrimination the field could carry is free.** The review
   UI builds `["route", <id>]` with **no** `--dest` when the human
   approves a proposal as-proposed, and appends `--dest <x>` only on an
   override (`ui/src/self_learn_ui/routes.py:112-118`). `route()`'s
   `_resolve_destination` (`verbs.py:495-516`) already branches on
   exactly that. The accept-vs-override signal that 12 §A2/§T-M5 needs
   for any autonomy-ladder calibration is sitting unrecorded at the seam
   both paths already cross.

### 1.4 No telemetry kind represents a routing

`EVENT_KINDS` (`telemetry.py:67-79`) has nine members; `route` is not one.
Live tracked plane, 2026-08-02: **capture 54, surface-budget 29, fire 22,
offer-declined 1 — 106 events, zero of every other kind.** (The campaign
playbook's 2026-07-28 figures were 30/26/8/1; the counts moved, the shape
did not.) The resolution plane is unobserved: nothing records that a
routing happened, where it went, or who chose it.

---

## 2. The change

Three parts, one unit. **Files: `selfcheck.py`, `telemetry.py`,
`verbs.py`. Nothing else.**

### 2.1 Part A — the `reach` selftest check (`selfcheck.py`)

Three new module-private functions plus one row in `run_selftest`.

**RR (the check's domain)** — for every bucket returned by
`ledger.discover_buckets(home)` (the same enumeration `_check_drift`
uses: `skills/*`, `projects/*`, **and the single one-level `user/`
bucket** — a `<home>/*/*/resolved/` glob would silently miss
`user/resolved/`, which exists on the live ledger), every record in
`<bucket>/resolved/lrn-*.md` with `status == "routed"`,
`superseded_by is None`, and `routing.destination == "reference"`.
Today RR == R14.

**LS(bucket, record) (the loaded-surface set)** — the files a session
loads for a record's scope, resolved exactly as the verbs resolve them:

| scope | LS |
|---|---|
| bucket scope `skill` | `[skill_dir_for(load_hosts(home), bucket.name) / "SKILL.md"]` |
| record scope `project` | `[bucket_project_path(bucket.path) / "CLAUDE.md"]` |
| record scope `user` | `[DEFAULT_USER_CLAUDE_MD.expanduser()]` |
| anything else, or the host is unregistered/unresolvable | `[]` |

A list from day one, with exactly one member per scope in v1 — see §6 for
why it is a list and what is deliberately excluded from it.

**`_surface_names_target(surface, target) -> bool`** — the reachability
predicate, pure text + path arithmetic, no globbing:

1. `surface` not a file ⇒ `False`.
2. **Left-maximal, anchored on the basename.** For every occurrence of
   `target.name` in the text, extend the token **leftward only**, over
   characters that are neither whitespace nor any of
   `( ) [ ] < > " ' `` `. The token **ends at the basename**; nothing to
   its right is ever consumed. Equivalently: `re.finditer(r"[^\s()\[\]<>\"'`]*"
   + re.escape(target.name), text)`.
3. For each token: `expanduser()`; absolute ⇒ itself, else
   `surface.parent / token`.
4. `True` iff any candidate's `.resolve()` equals `target.resolve()`.

**Step 2's direction is normative, and the two readings differ.** A
both-directions-maximal reading rejects `see references/LEARNINGS.md.` —
a sentence-final period, the commonest hand-written pointer shape — while
the anchored reading accepts it. Criterion 6 discriminates them. The
anchored reading adds no false positives: `myLEARNINGS.md` still yields a
token that fails step 4.

Steps 3-4 are the half that matters: a bare basename match would pass on
*some other* `LEARNINGS.md`. The whole file is searched, not just the
managed section — the whole file is loaded, and a hand-written pointer is
a real path (that is what the seven passing controls in §1.1 are).

**`_check_reach(home) -> tuple[bool, str]`** — mirrors `_check_drift`'s
posture exactly, so the two checks read the same:

- `home_state(home) in ("missing", "not-a-repo")` ⇒ `(False,
  home_state_message(...))`.
- `hosts.yaml` absent ⇒ `(True, "hosts.yaml absent — reachability not
  checked")`.
- For each record in RR: resolve the target via the **existing**
  `_reference_target_for` (`selfcheck.py:235-256`); resolve LS. A record
  **FAILS** when the target is unresolvable, when LS is empty, or when no
  member of LS names the target. Never skipped, never softened.
- RR empty ⇒ `(True, "no reference-routed records — nothing to reach")`.
- Any failures ⇒ `(False, "<n> of <m> reference-routed record(s)
  unreachable: <ids>; …")` — **the count leads the message**, so
  Checkpoint B's number is greppable from one line.
- All reachable ⇒ `(True, "<m> reference-routed record(s) reachable from
  their scope's loaded surface")`.

**Wiring.** One row in `run_selftest`'s `results` list, `("reach",
*_check_reach(home))`, placed after `drift`. A FAIL therefore makes
`--selftest` return 1 — which is the point. `--selftest` is an attended
verb; nothing automated invokes it (verified: no systemd unit, hook, or
CI path references it), so a red selftest reports a real defect and blocks
nothing. **A check that cannot change the exit code is decoration.**

### 2.2 Part B — the `route` telemetry kind (`telemetry.py`, `verbs.py`)

- `EVENT_KINDS` gains `"route"`. `NOTE_KINDS` does **not** — this is
  code-emitted inside a verb flow, never model-emitted (11 §4.3).
- `SCHEMA_VERSION` `1` → `2`. 11 §4.3: "v1 closed set; extending = version
  bump". No consumer filters on it (`read_events`, `report.gather`, and
  `worker._recurrence_suspects` all key on `kind` alone — verified), so
  the bump is honest bookkeeping, not a migration.
- **ROUTE-SITES** — the complete set of functions in `verbs.py` that write
  a `routed` routing block, derived by AST walk, not by hand:
  `route` (`:1897`, via `resolve_record(..., "routed", ...)` at `:2053`)
  and `route_direct` (`:2189`, via `set_routing(routing)` at `:2346`).
  `reject`, `graduate`, `rehome`, `supersede` do not write one (`rehome`
  moves pending records only). Each ROUTE-SITE spools exactly one event:

  ```python
  telemetry.spool_quiet(
      "route",
      record=<id>, destination=<destination>, scope=<record.scope>,
      by=<by>, variant=<spec.variant>,      # variant None ⇒ omitted
  )
  ```

- **`spool_quiet`, never `spool_event`** — telemetry must never break a
  verb (module docstring). The corollary is a trap the tests must handle:
  a spool refusal is swallowed with a stderr warning, so *"the verb
  returned 0"* proves nothing about the event. Every emission test asserts
  the event is in the spool.
- **Placement: immediately after the `with _ledger_write(home):` block
  closes**, in both ROUTE-SITES — not at the end of the function. The
  ledger commit *is* the routing (doc 13 §4.1: ledger first, canon
  compiled after). A host-phase failure leaves a routed record behind, and
  an event stream that drops exactly those under-counts the interesting
  cases.
- No `flags` field. `proposal.flags` is `U-schema`'s new key and does not
  exist yet; a field that is always absent is not instrumentation. The
  campaign's "destination × scope × flags" shorthand is served by
  destination × scope × by; flags is a later additive field.
- No new flush plumbing: `route` is in `cli.VERB_COMMANDS`
  (`cli.py:1727`), which already flushes the spool at verb end.

### 2.3 Part C — `routing.by` (`verbs.py`)

**`routing.by` names the actor that CHOSE THE DESTINATION.** v1 value set:
`"human"` | `"analyst"`. Derived at both ROUTE-SITES, hardcoded at
neither.

| path | destination source | `by` |
|---|---|---|
| `route <id>` (no `--dest`) — the review UI's approve-as-proposed argv | the proposal sibling, analyst-written | `analyst` |
| `route <id> --dest X` — the UI's override, or the terminal | the human's flag | `human` |
| `route_direct(dest=…)` from `teach --route --dest X` | the human's flag | `human` |
| `route_direct(dest=…)` from bare `teach --route` | `analyst.analyze()` | `analyst` — **see §6, one line outside this unit's files** |

Mechanically: `route()` passes `by="human" if dest is not None else
"analyst"` to `resolve_record`; `route_direct()` gains a keyword-only
`by: str = "human"` and the literal at `:2325` becomes `by`.

**Why this reading and not "who authorized the write".** Sourced, not
chosen for convenience:

- `02-schema.md:29` annotates the field `by: human  # always human in
  v1` — the field was always meant to be able to say something else; v1
  simply had no non-human chooser. It has one now (§1.3 item 2).
- `06-horizon.md:104`: at team scale "`routing.by` gains a name" under a
  PR model where the *merge* is the route event. A person's name is the
  team-scale refinement of `human` — a chooser, not an executor.
- A13 and M-1 are about who *executes* a route, and they are enforced
  structurally (the analyst has no route verb; the pane may only
  propose). They never needed this field, and the pin audit's use of it
  was reading a constant (§1.3 item 1).

**Pinned against misreading, because this is the one way this change can
do harm:** `by: analyst` means *"the analyst chose this destination and a
human approved it by invoking the verb."* It never means an agent routed
autonomously. Any future reader treating `by: analyst` as an A13/M-1
violation is wrong, and A13/M-1 are not measured by this field.

**No schema change is needed and no migration exists.**
`Record.set_routing` requires only `routed_at`/`destination`/`by` and
validates no enum (`records.py:404-412`, `:663-668`) — the same passthrough
that carries `reference_file`, `variant`, `hook`, `new_skill`. All 28
existing records read `human` and stay valid. **Both existing `by`
assertions in the suite are on `--dest` routes**
(`test_route_cli.py:194`, `test_verbs.py:193`) and stay green unchanged —
a test that has to be edited to accommodate a semantic change is a signal,
and there isn't one here.

---

## 3. What must not change

- `_check_drift`, `_check_markers`, `_check_compiler`, `_check_hooks`,
  `_check_capture`, `_target_for`, `_reference_target_for`. `reach` is an
  independent row with an independent loop; it must not be folded into
  `_check_drift` (one check masking the other's failure is how a two-fact
  check becomes a one-fact check).
- `compile_reference` and everything else in `compilers.py`. **No pointer
  is emitted by this unit.**
- The `reference`-at-user-scope refusal (`verbs.py:950-955`). That is
  `U-demand-user`'s B7.
- `resolve_record`'s `by: str = "human"` default in `ledger_ops.py` —
  that file is `U-schema`'s. `verbs.py` stops *relying* on the default by
  passing explicitly; the default itself is untouched.

---

## 4. Acceptance criteria

Numbered; the mutation plan (§5) references these numbers.

**Part A — reachability**

1. **Reachable fixture PASSES.** A skill-scope record routed to
   `reference`, its `LEARNINGS.md` written, and the host `SKILL.md`
   containing `[Learnings](references/LEARNINGS.md)` ⇒ `_check_reach`
   returns `(True, …)` **whose message contains `1 reference-routed
   record(s) reachable`**, and `cli.main(["--selftest"]) == 0`.
   **The count in the PASS message is asserted, not just the boolean: a
   `(True, …)` produced because RR was EMPTY is precisely the failure
   this half of the gate exists to exclude.**
2. **Unreachable fixture FAILS.** The same fixture with the `SKILL.md`
   line removed ⇒ `(False, …)`, the message contains the record id and
   the surface path, and `cli.main(["--selftest"]) == 1`.
   **1 and 2 are the two halves of the gate. Neither alone proves
   anything.**
3. **The count is asserted.** With three unreachable reference records in
   one bucket, the `reach` message starts with `3 of 3` and names all
   three ids. With one reachable and two not, it reads `2 of 3`.
4. **A same-basename file elsewhere does not satisfy it.** The `SKILL.md`
   names `../other/LEARNINGS.md` (a real file, wrong directory) ⇒ FAIL.
5. **A different file in the right directory does not satisfy it.** The
   `SKILL.md` names `references/GOTCHAS.md` only ⇒ FAIL.
6. **The token must RESOLVE, not merely appear — and it is
   right-anchored.** One test, four directions, same fixture:
   - `SKILL.md` containing `read LEARNINGS.md for prior lessons` ⇒
     **FAIL** — that token resolves to `<skill>/LEARNINGS.md`, which is
     not the target under `references/`.
   - `SKILL.md` containing `read references/LEARNINGS.md` ⇒ **PASS**.
   - `SKILL.md` containing `see references/LEARNINGS.md.` — **trailing
     sentence period** ⇒ **PASS**. This leg is the §2.1-step-2
     discriminator; a both-directions-maximal tokenizer fails it and
     nothing else in this suite would notice.
   - `SKILL.md` containing the target's **absolute** path ⇒ **PASS**.
7. **An unresolvable reference target FAILS, never skips** — a
   skill-scope record whose skill is not under the registered skills root
   ⇒ FAIL naming the record.
8. **An empty LS FAILS, never skips** — a project-scope reference record
   whose bucket has no registered project host ⇒ FAIL naming the record.
8a. **A present-but-missing LS member FAILS** — a skill-scope reference
    record whose host `SKILL.md` **does not exist** ⇒ FAIL naming the
    record. LS is non-empty here, so criterion 8 does not cover it;
    without this fixture `if not surface.is_file(): return True` turns
    nothing red (reviewer's INV-5).
8b. **The target-side `.resolve()` is load-bearing** — a fixture whose
    registered skills root is reached through a **symlink**, so the
    surface resolves via the link and the target via the real path.
    Dropping `target.resolve()` must turn this red; on Linux without a
    symlink in the fixture it turns nothing red (reviewer's INV-3).
9. **Only live records count** — a `superseded_by`-set reference record
   and a `status: pending` one are both excluded from RR (fixture:
   both present, `reach` reports `0` and PASSes).
9a. **The `user/` bucket is in the domain.** A direct unit test of the LS
    helper for `record.scope == "user"` returns
    `[DEFAULT_USER_CLAUDE_MD.expanduser()]`, not `[]`. The `user` row is
    deliberately dead end-to-end until `U-demand-user`
    (`_reference_target_for` returns `None` for user scope before LS is
    ever consulted), so the helper is tested directly — the alternative
    is a scope silently outside RR, which is F1.
10. **Zero reference records PASSes** with a message containing `no
    reference-routed records`.
11. **`hosts.yaml` absent** ⇒ PASS whose message contains `not checked`;
    **a missing / not-a-repo home** ⇒ FAIL (mirrors `_check_drift`).
12. **`run_selftest` reports 7 checks** and its all-green line reads
    `all 7 checks green`.
13. **No existing selftest test changes.** `test_hosting.py:716`,
    `test_selftest.py`, `test_new_skill.py:227` keep asserting `== 0`
    unmodified. If any goes red, the fix is to add a pointer to that
    fixture's `SKILL.md` — **never** to exempt a scope or narrow RR.

**Part B — telemetry**

14. `"route" in telemetry.EVENT_KINDS` and `"route" not in
    telemetry.NOTE_KINDS`.
15. `telemetry.SCHEMA_VERSION == 2`.
16. **`route()` emits.** A proposal-driven `cli.main(["route", id])`
    leaves exactly one spooled line with `kind == "route"`, carrying
    `record`, `destination`, `scope`, `by`. Asserted on the spool/tracked
    contents, **never** on the verb's exit code.
17. **`route_direct()` emits** the same shape via `teach --route --dest`.
18. **The event survives flush**: after the verb, `telemetry.read_events`
    returns it and `report.gather(home)["telemetry"]["events_by_kind"]`
    contains `route`.
19. **A host-phase failure still emits.** `_host_phase` monkeypatched to
    raise ⇒ the verb raises, the record is routed on disk, and the
    `route` event is spooled.
20. **ROUTE-SITES is derived, not listed.** An AST walk of `verbs.py`
    collects every function containing a `set_routing(` call or a
    `resolve_record(` call whose third positional argument is the string
    literal `"routed"`; every such function must also contain a
    `spool_quiet("route"` call. AST, not regex — a docstring naming
    `set_routing()` must not turn this red.
    **Plus the collector's own positive control, in the same test:** the
    derived set must be **non-empty** and must contain **at least**
    `route` and `route_direct`. "Every collected function spools" is
    vacuously true when the collector matches nothing — hoisting
    `"routed"` into a module constant, or renaming `set_routing`, empties
    the set and the guard stays green through a deleted spool call
    (reviewer's INV-1). The floor is a floor, **never a whitelist**: a
    third route site must be *added to* the derived set by the collector,
    not enumerated here.

**Part C — `routing.by`**

21. `route(home, id)` with a proposal and no `dest` ⇒
    `routing["by"] == "analyst"`.
22. `route(home, id, dest="skill-md")` ⇒ `routing["by"] == "human"`.
23. `route_direct(..., dest="skill-md")` ⇒ `"human"`;
    `route_direct(..., dest="skill-md", by="analyst")` ⇒ `"analyst"`.
    (The second proves the plumbing the §6 follow-up needs.)
24. **The route event's `by` equals the record's `routing["by"]`** on
    both criteria 21 and 22 — one assertion, both directions.
25. **No `by` is a string literal at a call site.** AST walk of
    `verbs.py`: no `ast.keyword` named `by`, and no `"by"` key in a dict
    literal, may have an `ast.Constant` string value. The `route_direct`
    **signature default** is the one exemption, named in the test with
    §6's reason.
    **Two must-stay-green controls in the same test, both against
    UNMUTATED code:**
    - `verbs.py:2954` passes `superseded_by="canon"` — a keyword match
      written as `arg.endswith("by")` goes red on clean source, which
      trains "relax the guard" (reviewer's INV-4). Match the keyword
      name **exactly**, and assert this stays green.
    - A docstring containing `by="human"` must not turn it red — the
      AST-not-regex requirement, and the reason
      `commit-drift-evidence-spec.md` §7.5 exists.

**Run evidence.** The builder reports the CLI suite's own pass/fail line
(baseline measured 2026-08-02: **1133 passed, 5 skipped, 0 failed**), the
count of new tests collected, and `pyright`. An `importorskip`ped module
is not a green test.

---

## 5. Mutation plan

A blind reviewer will run these. Each is one line of production code.
**A cell listing several criteria is a blast radius, not a defect in the
tests** — see M1. Where a criterion is meant to be *isolated* by exactly
one mutation, the cell says so.

| # | One-line mutation | Criteria that must fail |
|---|---|---|
| M1 | `_check_reach`: change the destination literal `"reference"` → `"skill-md"` | 2, 3, 4, 5, 6, 7, 8 — RR collapses to empty on **every** reference-only fixture, so all seven negative criteria go red at once. **M1 is a blast-radius check, NOT the count's isolator.** Do not "fix" the breadth by weakening the negative criteria until M1 isolates 3 — that destroys the negative half of the gate, which is the whole instrument. The count is isolated by **M9** (FAIL side) and **M21** (PASS side). |
| M2 | delete the `("reach", *_check_reach(home))` row from `run_selftest`'s `results` | 2, 12 |
| M3 | `_surface_names_target`: `return True` as the first statement | 2, 4, 5, 6 |
| M4 | `_surface_names_target`: `return False` as the first statement | 1, 6 |
| M5 | `_surface_names_target`: replace the resolve-and-compare with `return target.name in text` | 4, 6 |
| M5a | `_surface_names_target`: make step 2 both-directions-maximal (require the whole non-delimiter run to end at the basename) | 6 (the trailing-period leg **only** — this is F6's discriminator) |
| M5b | `_surface_names_target`: drop `target.resolve()`, compare against the unresolved target | 8b (**needs the symlinked-skills-root fixture; without it this turns nothing red on Linux**) |
| M6 | `_check_reach`: `continue` instead of appending a failure when the target is unresolvable | 7 |
| M7 | `_check_reach`: `continue` instead of appending a failure when LS is empty | 8 |
| M7a | `_surface_names_target`: `if not surface.is_file(): return True` | 8a (LS non-empty, member absent — criterion 8 does **not** cover this) |
| M8 | `_check_reach`: drop the `status == "routed" and superseded_by is None` filter | 9 |
| M8a | `_check_reach`: iterate `home.glob("*/*/resolved/lrn-*.md")` instead of `discover_buckets(home)` | 9a (**F1's mutation.** Turns nothing else red — the `user/` bucket has no reference records today, which is exactly why the narrowing was invisible) |
| M9 | `_check_reach`: replace the leading `f"{len(failures)} of {checked}"` with a constant | 3 |
| M21 | `_check_reach`: drop the count from the **all-reachable** return (`"reference-routed records reachable"` with no number) | 1 — **the PASS-side fail-open probe.** Without it, a countless PASS ships and §9.5's `14 → 0` comparison has nothing to compare |
| M10 | `telemetry.py`: remove `"route"` from `EVENT_KINDS` | 14, 16, 17, 18, 24 — `spool_quiet` swallows the `TelemetryError`, so the verbs still succeed and only the event vanishes. **If 16/17 stay green they are asserting the verb's exit code instead of the event — the §2.2 trap, and a finding in its own right.** |
| M11 | `telemetry.py`: add `"route"` to `NOTE_KINDS` | 14 |
| M12 | `telemetry.py`: `SCHEMA_VERSION = 1` | 15 |
| M13 | delete the `spool_quiet("route", …)` call in `route()` | 16, 18, 20, 24 |
| M14 | delete the `spool_quiet("route", …)` call in `route_direct()` | 17, 20 |
| M15 | drop `destination=` from the `route()` event payload | 16 |
| M16 | move `route()`'s spool call from after the `_ledger_write` block to after `_host_phase` | 19 |
| M17 | `route()`: pass `by="human"` unconditionally to `resolve_record` | 21, 24, 25 |
| M18 | `route()`: invert the branch (`"analyst"` when `dest is not None`) | 21, 22 |
| M19 | `route_direct()`: restore the `"by": "human"` dict literal at `:2325` | 23, 25 |
| M20 | spool a constant `by="human"` in the `route()` event while leaving the record correct | 24, 25 |
| M22 | the ROUTE-SITES collector: hoist `"routed"` into a module constant so the `resolve_record` matcher stops matching | 20 (**the collector's positive control** — the "every collected function spools" assertion is vacuous with an empty set) |

**Reviewer-invented mutations are explicitly invited** — the campaign's
most valuable finding last cycle came from one, and three of the five
invented against r1 became F2, F3 and F8(b) above. Two more worth trying:

- **Add a new function to `verbs.py` that calls `set_routing(...)` and
  does not spool.** Criterion 20 must go red. This is the commit-drift
  precedent (`commit-drift-evidence-spec.md` §7.4): the guard that counts
  sites which *do* call a function stays green through a defect that is a
  site which does *not*.
- **Write `by="human"` inside a docstring in `verbs.py`.** Criterion 25
  must stay **green**. A guard whose false positive trains "just update
  the count" is worse than no guard (`commit-drift-evidence-spec.md`
  §7.5).

---

## 6. Builder decisions, made here

- **The check does not grep for `*(self-learn:index)*`.** r2 B9 specifies
  the anchor and the basename. The anchor is `U-pointer`'s artifact and
  r2 itself calls its wording "the human's to veto once". Coupling the
  detector to the cure's exact text turns it into a conformance test for
  the cure instead of a measurement of the property, and — worse — it is
  satisfiable by emitting the anchor **without a working path**. The
  filename that resolves is the load-bearing half; require only that.
  **The contract this imposes on `U-pointer` is exactly one clause: the
  pointer must contain a path token that resolves to the demand file.**
- **LS is a list with one member per scope.** `CLAUDE.local.md` and
  `.claude/rules/*.md` are deliberately **not** members in v1: a pointer
  must be at least as durable as the thing it points at, and the `local`
  variant is git-excluded by design (A2 §6/P-A3). The list shape exists so
  the Model B cutover (`U-modelb`, unratified) adds a member instead of
  editing a predicate. **This contradicts r2 §5's claim that the selftest
  is unchanged by Model B — see §8.**
- **The whole loaded-surface file is searched, not the managed section.**
  The whole file is loaded; and the home-assistant `SKILL.md` has no
  managed section at all, so a section-scoped check would fail today for
  a reason unrelated to reachability.
- **A `reach` FAIL sets a non-zero exit code**, and will therefore make
  `--selftest` return 1 on this host from merge until `U-pointer` lands.
  That is the correct state: the system is broken and the instrument says
  so. Nothing automated consumes `--selftest`.
- **User scope FAILs loudly rather than skipping.**
  `_reference_target_for` returns `None` for user scope today (`reference`
  is refused there). When `U-demand-user` opens B7, user-scope reference
  records become routable and this check will FAIL them until
  `_reference_target_for` and LS learn the user branch. **That is a
  deliberate loud handoff, not a bug — see §8.**
- **The `user` LS row is therefore dead code end-to-end until
  `U-demand-user`, and is unit-tested directly** (criterion 9a).
  `_reference_target_for` returns `None` before LS is ever consulted, so
  no end-to-end fixture can reach that row. The row still exists, and RR
  still enumerates the `user/` bucket, because the alternative is a scope
  silently outside the domain — which is F1, the exact silent narrowing
  criterion 13 forbids. **`user/` is one level deep** (`ledger.py:157-159`),
  unlike two-level `skills/*` and `projects/*`; `discover_buckets` is the
  only enumeration that gets this right, and it is the one
  `_check_drift` already uses.
- **Tests live in:** `cli/tests/test_selftest.py` for Part A (its `env` /
  `seed_routed_skill_target` fixtures already build the ledger+host pair);
  a **new** `cli/tests/test_route_observability.py` for Parts B and C
  together with both AST guards. One new file keeps this unit's footprint
  off the shared modules while five siblings build.
- **`route_direct` gets `by: str = "human"` (defaulted, not required).**
  Making it required would break `teach.py:698`, which is outside this
  unit's file set. Criterion 23 proves the plumbing, so the completing
  change is a call-site edit with no design left in it — see §7.

---

## 7. Out of scope

- **The cure.** Pointer emission, `compile_reference` changes, the
  reference-route ALWAYS recompile: `U-pointer` (r2 B8), later wave,
  human-blocked.
- **`reference` at user scope** (r2 B7): `U-demand-user`.
- **`reject` / `defer` / `graduate` telemetry kinds.** FW-45 names all
  four; this unit closes only `route`. **FW-45 is partially closed and
  must not be marked done.** The other three are mechanically identical
  once `route` lands and are a good follow-on unit; they are excluded here
  only because they widen the `verbs.py` footprint while five units build
  concurrently.
- **FW-40 has three clauses — decide / selftest / re-deliver — and this
  unit closes only the middle one.** Record U-reach against FW-40's
  **selftest clause** and **leave the row's state unchanged.** Its DECIDE
  clause is settled by **S-23** (the on-demand shelf keeps its pointer;
  PATHED becomes the primary cheap tier), and its **re-delivery clause is
  still `U-pointer`'s** — 14 records remain stranded until that lands. A
  bookkeeping sweep marking FW-40 done on the strength of this unit would
  erase a clause that is genuinely open, on the row that gates FW-35 and
  FW-42.
- **`teach.py:698-706` — one line, and it completes Part C.** The bare
  `teach --route` path must pass `by="analyst" if args.dest is None else
  "human"` into `verbs.route_direct`. Without it, that path keeps writing
  the false `by: human` §1.3 item 2 identifies. `teach.py` is outside the
  file set I was given and is not claimed by any concurrent unit
  (`U-capture` is in the gated queue). **Recommendation to the
  orchestrator: fold this line into this unit's build with an explicit
  file-set widening, or schedule it immediately after.** Do not let it sit.
- **Doc obligations this unit creates and cannot discharge** (all outside
  the file set):
  - `11-telemetry-and-lifecycle.md` §4.3 — the event-kind table needs a
    `route` row and the version bump noted.
  - `02-schema.md:29` — `by: human  # always human in v1` becomes wrong
    the moment §2.3 lands.
  - `plugins/self-learn/skills/self-learn/SKILL.md:53` — the `--selftest`
    check list gains reachability.
  These are text, and leaving them stale reproduces exactly the
  fossil-rationale defect `commit-drift-evidence-spec.md` §1 convicts.
- **Cleaning up `misc/` git-ignore status, the UI cache leak, `one_motion_route`.**

---

## 8. Findings that contradict r2, the audit, or the playbook

Recorded here because a later reader will otherwise inherit them.

1. **r2 §5 says the selftest is unchanged by the Model B cutover.** It
   lists "the selftest" among the things a Model B target remap does not
   touch. That is only true if the check resolves loaded surfaces through
   a list it can extend; a check that names `CLAUDE.md` directly *is* a
   Model B edit. §6 makes it a list for this reason.
2. **r2 B9's `*(self-learn:index)*` anchor is the wrong primary
   criterion** — §6. The anchor can be present with no working path.
3. **The pin audit's A13/M-1 evidence is not evidence** — §1.3 item 1.
   "32/32 routings `by: human`" is a hardcoded literal, and it would read
   the same on a host where the invariant was violated.
4. **Telemetry counts have moved since the playbook was written.**
   2026-08-02: capture 54, surface-budget 29, fire 22, offer-declined 1
   (playbook §7 / audit §11, 2026-07-28: 30/26/8/1). The zero-of-
   everything-else claim still holds. **No spec or test may pin absolute
   telemetry counts.**
5. **The R14 positive-control figures drifted by one.** The campaign
   brief cites "11 files match 'Home Assistant' and 7 match 'GOTCHAS'";
   the audit §3 says 8 for GOTCHAS. Re-measured 2026-08-02: **GOTCHAS 8,
   "Home Assistant" 10**. The controls still discriminate; the numbers are
   not stable and should be re-run, not quoted.
6. **`--selftest` is not read-only against the real ledger.**
   `_check_capture` creates and deletes a scratch directory *under*
   `SELF_LEARN_HOME` (`selfcheck.py:410`). It self-cleans and commits
   nothing (verified: `git status --porcelain` empty, HEAD unmoved after
   the §9 run), but "read-only" is the wrong word for it, and the §9
   procedure verifies cleanliness because of it.
7. **`U-demand-user` opens a seam into this unit's file.** B7 makes
   user-scope `reference` routable in `verbs.py`, while the resolver that
   must learn about it (`_reference_target_for`) lives in `selfcheck.py`.
   The two units do not share a file, so the wave plan reads them as
   disjoint, and they are not. §6 makes the failure loud rather than
   silent; the orchestrator should still name the seam in both prompts.
8. **`route` is `verbs.py`'s only routed-write pair.** Verified by AST
   walk, against the possibility that `rehome` or `graduate` also route:
   they do not. Criterion 20 keeps that true.
9. **The bare-basename FAIL is a live shape on the instrumented host —
   expect a SECOND `reach` failure once `U-pointer` lands, and do not
   misread it as the check being broken.** `SKILL.md:129` names
   `` `GOTCHAS.revisions.md` `` with no directory component, so that
   token resolves to `<skill>/GOTCHAS.revisions.md` and the predicate
   calls it unreachable. Measured 2026-08-02 over the 9 files in that
   `references/` dir: **True for 7, False for `LEARNINGS.md` and
   `GOTCHAS.revisions.md`.** It costs nothing today (no record is routed
   to `GOTCHAS.revisions.md`), and it is the predicate behaving exactly as
   §2.1 step 3 specifies. **If it ever bites, the repair is to write a
   resolving path into the surface — never to loosen the predicate.**
   A basename-only match would make `LEARNINGS.md` "reachable" tomorrow
   with no pointer written at all.

---

## 9. The positive control — exact capture procedure

**This unit's whole point.** The check must be demonstrated failing 14
times against the live ledger, before any cure exists. Run **after merge,
before `U-pointer`.**

### 9.1 The BEFORE half is already captured

Measured 2026-08-02 against `~/.self-learn` at ledger HEAD `f97e27c`,
with the pre-U-reach build:

```
selftest: PASS capture — scratch record round-tripped under ~/.self-learn
selftest: PASS compiler — regenerated 7 managed sections in-memory
selftest: PASS markers — marker pairs intact on 7 target(s)
selftest: PASS drift — 28 routed record(s) present in their compiled targets
selftest: PASS hooks — 3 live hook script(s) intact; 0 registration(s) resolvable
selftest: PASS sentinel — probe held and released at <scratch>/self-learn/autosync-pause
selftest: worker: M2 — not checked
selftest: all 6 checks green
rc=0
```

The ledger does not change between the two runs. **The instrument
changes. That is the control.**

### 9.2 The AFTER run

```sh
cd plugins/self-learn/cli   # from the repo root
SCRATCH=$(mktemp -d)

# (i) provenance control FIRST — a measurement taken against master's
# CLI is worthless, and it looks identical to a good one. MACHINE-CHECKED,
# not eyeballed: `cli/.venv` is an EDITABLE install pinned to an absolute
# path in the main checkout, so a builder in a worktree running the main
# venv gets a path with the same `cli/src/self_learn/` suffix while
# measuring master's unmodified CLI — and prints the success string.
.venv/bin/python -c 'import self_learn, os, sys; p=os.path.realpath(self_learn.__file__); r=os.path.realpath("src/self_learn/__init__.py"); print(p); sys.exit(0 if p == r else 1)'
prov=$?; echo "provenance rc=$prov"      # MUST be 0, captured UNPIPED

# (ii) the run. rc captured UNPIPED.
SELF_LEARN_HOME="$HOME/.self-learn" \
XDG_CACHE_HOME="$SCRATCH/cache" \
XDG_RUNTIME_DIR="$SCRATCH/run" \
SELF_LEARN_CLAUDE_DIR="$SCRATCH/claude" \
SELF_LEARN_TRANSCRIPTS_DIR="$SCRATCH/transcripts" \
.venv/bin/python -c 'import sys; from self_learn.cli import main; sys.exit(main(["--selftest"]))' \
  > "$SCRATCH/selftest.out" 2>&1
rc=$?
echo "rc=$rc"

# (iii) read the tool's own verdict line, not a pipeline's exit status.
grep -n 'reach' "$SCRATCH/selftest.out"

# (iv) the ledger must be untouched (§8 item 6).
git -C "$HOME/.self-learn" status --porcelain     # must print nothing
git -C "$HOME/.self-learn" log --oneline -1       # must still be f97e27c
```

### 9.3 What counts as the control passing

All four, or the control did not pass:

1. **`provenance rc=0`** — the machine-checked identity, not a path that
   merely *looks* right. An eyeballed suffix match passes on master's
   CLI run from a worktree.
2. `rc=1` — where the same command returned `0` in §9.1.
3. The `reach` line reads
   `selftest: FAIL reach — 14 of 14 reference-routed record(s) unreachable: …`
   and names 14 distinct `lrn-` ids.
4. Every other check still PASSes, and the summary reads `1 of 7 checks
   FAILED`. **A run where other checks also went red is not this
   measurement** — it means the environment moved, and it must be
   re-taken.

A prototype of the exact algorithm in §2.1, run against the live ledger
2026-08-02, produced `checked=14 failures=14` with all 14 ids naming
`SKILL.md`. The build is expected to reproduce that number exactly; a
different number is a finding, not a rounding error.

### 9.4 Where the number is recorded

1. **This file**, appended as `§10 Measured baseline`: the date, the
   ledger HEAD sha, `rc`, the verbatim `reach` line, and the 14 ids. This
   is the durable copy — `misc/` is git-ignored and local-only, and the
   ledger is severed from this repo.
2. **`misc/r2-progress.md`** — U-reach's row plus a `Checkpoint B
   baseline: 14` line (campaign §8: the register is updated at every state
   transition, not at wave end).
3. Nothing else. The raw `selftest.out` is transient.

### 9.5 Checkpoint B's comparison run

After `U-pointer` merges, re-run §9.2 verbatim on the same ledger. The
claim under test is `14 → 0`:

- The `reach` line must read `selftest: PASS reach — 14 reference-routed
  record(s) reachable from their scope's loaded surface`, and `rc=0`.
- `14` must still appear — **a 0-of-0 pass is the M1 mutation happening in
  production.** If the count is not 14, the record set changed and the
  comparison is invalid regardless of the verdict.

---

## 10. Measured baseline

> **EMPTY BY DESIGN. Filled once, at merge, by whoever runs §9.2.** The
> §9.1 BEFORE run is already recorded above; this section holds the AFTER
> run and is Checkpoint B's comparison basis. Required contents: the date,
> the ledger HEAD sha, `rc`, the verbatim `reach` line, and the 14 ids.
> An empty §10 at Checkpoint B means the positive control was never taken,
> and the check is unproven regardless of what the suite says.

---

## 11. Revision history

- **r1** — first draft. Every line number and field name re-verified
  against current source 2026-08-02; §8 recorded where r2, the audit, and
  the playbook were found wrong. Gated: **9 findings, all FOLD, no
  blockers.**
- **r2** — this document. Folded under the 2026-07-26 verdict repricing
  (bounded substitutions verify at the code gate, not in a fresh spec
  round). Two of the nine were the unit's own defect class occurring
  inside the unit: **F1**, an RR glob that silently dropped the one-level
  `user/` bucket — the exact silent narrowing criterion 13 forbids; and
  **F2**, a PASS-half criterion that went green with zero records
  checked. Also folded: the ROUTE-SITES collector had no positive control
  (F3); M1's blast radius invited a builder to weaken the negative half of
  the gate (F4); M10/M13/M20 under-listed their radius (F5); the
  tokenizer had two readings and no criterion discriminating them (F6);
  the provenance control was eyeball-only against an editable install
  (F7); two missing controls (F8); and FW-40's three clauses needed
  separating (F9). New criteria 8a, 8b, 9a; new mutations M5a, M5b, M7a,
  M8a, M21, M22.
  Three of the reviewer's five invented mutations found real holes.
