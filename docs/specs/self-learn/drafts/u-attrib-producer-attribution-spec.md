# Spec — U-attrib: producer attribution by exclusive namespace

Status: **r3 — DELTA, awaiting the delta gate.** Two rounds, 24 findings,
all folded (§10 maps each to its change). r1 blind gate: **UNSOUND — 3
BLOCKER / 6 MAJOR / 6 NOTE**; r2 delta: **UNSOUND — 1 BLOCKER / 3 MAJOR /
5 NOTE**, with 14 of r1's 15 folds verified closed at mechanism level.
**The direction has now survived two adversarial rounds** (§1.2): the
same-path premise was verified against the code, both refusals stand, and
the stage was judged to genuinely invert `_written_since` rather than
relocate the ambiguity. Both `Z1` legs were independently reproduced by
the r1 gate under a cleaner construction. Every r1 finding was a **code
site the spec had not yet owned**; every r2 finding was on the
**recovery machinery r2 itself added** — so both rounds harden rather
than redesign, and r3's one BLOCKER is the reminder that a mechanism
introduced to fix a defect is the most likely place to re-introduce it.
Unit `U-attrib`, addressing **FW-84**
(`docs/specs/self-learn/14-forward-work-map.md:139`). Evidence of record:
the live incident that row states (ledger commit `efd5ebd`, 2026-08-08
18:09 PDT — two attended-validated proposals deleted and two rewritten
mid-review-session), and `U-repair`'s spec §7.3, whose seven-residual /
three-root table this unit is written against. **Read `U-repair` §3.4,
§3.5, §3.8 and §7.3 before this document**; every figure they state is
treated here as measured and is not re-derived. This spec adds five
measurements of its own (§9), two of which contradict a property the
shipped code has claimed since T13.

**Base commit:** `c8dcaf3` (master — the `U-repair` merge). `worker.py`
is uncontended.

**Files this unit may touch:**

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/worker.py` | The stage (`Stage-1`), the permission contract (`Grant-1`), the run sequence delta (`Seq-2`), the install predicate (`Install-1`), the batch prompt's write instruction, `Obs-2`'s lines and fields. |
| `plugins/self-learn/cli/tests/test_attrib.py` | **NEW.** This unit's tests. |
| `plugins/self-learn/cli/tests/test_repair.py` | **Fixture relocation at scale, plus the meaning changes.** Measured (predicate and table in §3.5): **43 of its 55 tests** drive a run with the shim writing into `<bucket>/proposals/` — including all eight `G` tests, `H1`–`H5`, `E5`/`E6`/`E8`, `A5`, `F2`/`F5`. §3.5 is the per-criterion ruling; `CP1` is the gate. |
| `plugins/self-learn/cli/tests/test_worker.py` | **Added in r2** *(r1 gate BLOCKER 3)*. Three edit classes, enumerated: **(i)** `shim_writes()` (`:258-262`) — THE shim helper every relocation depends on, imported by `test_repair.py` (`:64`) — gains a stage-targeted form; **(ii)** the **18** run-driving tests here that stage output relocate their fixtures (23 drive a run; five stage nothing), including the only shipped **merge happy path**, the secret-bearing deletion, `test_unexpected_artifacts`, partial success and the orphan sweep; **(iii)** `test_run_argv_pins` (`:364`) is a **bucket 3** change — it asserts the three ledger globs `GR-b` replaces, not only `defaultMode`. |
| `plugins/self-learn/cli/tests/test_hosting.py` | `TestWorkerContainment` — two tests whose subject changes (`CP8`). |
| `plugins/self-learn/cli/tests/test_lock_invariant.py` | `NOT_REPO_TRUTH` gains the stage's entries, each with its why (`HY2`). |
| `docs/specs/self-learn/03-decisions.md` | New rows `S-32`, `S-33` (§7.4), landing in the same commit as the build. |
| `docs/specs/self-learn/14-forward-work-map.md` | FW-84 disposition. |

**`ledger_ops.py` is NOT in this list, deliberately and normatively.**
This unit changes **no validator**, adds **no refusal**, and relaxes
none. The refusal set is exactly what `U-schema`, `U-table` and
`U-repair` shipped. A builder who finds themselves editing
`_validate_gates`, `_validate_derivation`, `validate_proposal`,
`stamp_proposal` or `proposal_info` has left this unit's mandate and must
stop and report.

`analyst.py` is **out of scope and unaffected**: it builds its own argv
(`analyst.py:120`), carries no settings file, and parses the model's
**stdout** — it never grants a write tool at all. `verbs.py`,
`commands/review.md`, `selfcheck.py`, `miner.py`, the UI and the whole
attended path are **out of scope and must be reported, not edited.**

---

## 0. Reading order and precedence

This document has **five normative definitions** — **Stage-1** (§3.1, the
exclusive namespace), **Grant-1** (§3.2, the permission contract),
**Seq-2** (§3.3, the run sequence as a delta over `U-repair`'s `Seq-1`),
**Install-1** (§3.4, when bytes may move into the ledger) and **Obs-2**
(§3.8, the observable surface) — plus two normative behaviour
definitions, **the compatibility ruling (§3.5)** and **the acceptance
criteria (§4)**.

**Precedence, on conflict:**

1. The acceptance criteria (§4) and the mutation plan (§5) win over
   everything else. They are the contract; the rest is rationale.
2. Stage-1, Grant-1, Seq-2, Install-1, §3.5 and Obs-2 win over all prose
   and over any example.
3. Where this spec and `U-repair` disagree about a behaviour, **§3.5
   decides and nothing else does.** Every divergence from `U-repair` is
   listed there by criterion id; a divergence not listed there is a
   defect in this spec, not a licence.

**Each normative definition appears exactly once.** Nothing downstream —
not the criteria, not the mutation plan — may re-state a member. Refer to
members by id.

**Namespaces, so no id collides with `U-repair`'s.** This unit's criteria
are two-letter-prefixed: `NS*` (namespace), `GR*` (grant), `IN*`
(install), `RT*` (retirement), `CP*` (compatibility), `SW*` (switches),
`OB*` (observability), `HY*` (hygiene). Its mutations are `MA1`…, its
measurements `Z1`…`Z5`, its builder decisions `AD1`…. `U-repair`'s ids
keep their own shapes and are always cited as `U-repair`'s: criteria
`A*`/`B*`/`G*`/`D*`/`E*`/`F*`/`H*`, mutations `M1`…`M53`, measurements
`X1`…`X7`, steps `S1`…`S8`, sets `Set-C`/`Set-E`/`Set-J`/`Set-P`/`Set-Q`,
rules `E-1`…`E-5`, `Rule-F`, `Table-E`'s `TE1`…`TE21`. Decision-register
rows are always hyphenated (`S-26`, `S-31`, `S-32`).

**Read §1 before §3.** One argument decides this unit's whole shape, and
a reader who skips it will read §3 as an over-engineered alternative to
parsing a log.

---

## 1. The defect

### 1.1 The root, restated exactly

`_written_since(home, snap0)` (`worker.py:1473-1478`) returns every path
under any bucket's `proposals/` whose digest differs from a snapshot
taken before the model call. `run` treats that set as **the model's
output** (`worker.py:2570`, `:2654`), and `_validate_written` then
validates, stamps, deletes or commits each member under the unattended
policy. Nothing in that chain records what the model *did*; it records
what the *world* did. Any concurrent producer's write inside the model
window is therefore attributed to the model — which is the measured
incident, and the root `U-repair` §7.3 assigns to this unit for four of
its seven residuals.

### 1.2 Why the obvious fix is not a fix — the same-path argument

The obvious repair is to record the paths the model actually wrote
(`--output-format stream-json` tool-use events) and intersect. That
narrows attribution, and it is **feasible** — measured, not assumed
(`Z4`). It is nonetheless the wrong primary signal, for a reason that has
nothing to do with version fragility:

> **Both producers legitimately write the same path.** A record is
> eligible precisely when its proposal is missing, stale or invalid
> (`proposal_info`, `ledger_ops.py:2045-2085`), so the model's normal,
> intended behaviour on the common eligibility path is to **overwrite an
> existing proposal file** — `U-repair` §3.4 states this in as many
> words. The attended session's normal behaviour on the same record is to
> write the same file. Their writes are the same operation on the same
> bytes.

A per-path record of the model's writes therefore answers "did the model
write here?" — but the question landing needs answered is "**whose bytes
are on disk now?**", and when both producers wrote the same path inside
one window, no landing-time observation can answer it. The last writer
wins and leaves no trace of the first. That is why `U-repair` §7.3 lists
the Write-tool overwrite as needing a *different* direction from
provenance: by landing time the human's bytes are already gone.

The same argument disposes of the per-record lease. A lease is only a
signal if every writer consults it, and the writer that caused the
incident is a Claude Code session's `Write` tool, which consults nothing.
An advisory marker that the destroying party never reads is documentation
with a filename.

**What survives the argument:** stop the two producers from sharing a
namespace. If the model can only write where nothing else writes, then
its output is identified by *location* rather than by observation, the
collision cannot occur at all, and — the inversion that makes this cheap
— `_written_since(home, snap0)` stops being a bad proxy for "what the
model wrote" and becomes an **exact record of what the model did not
write.** The defective function is not deleted; it is made true by
changing what it is asked.

### 1.3 What is *not* the defect

Stated so the build does not re-open settled ground.

- **Not the elicitation contract.** `U-repair`'s Set-C, its exemplar fix
  and its repair round are the yield fix and are untouched here.
- **Not the validator.** Every refusal that fires today fires here,
  unchanged, on the same bytes.
- **Not the batch invocation's write scope being too wide *within* the
  ledger.** `U-repair` §7.1 refused narrowing it to the batch's own
  proposal paths, and that refusal stands and is not reversed here —
  §8 states precisely why relocation is a different move from narrowing.

---

## 2. What binds this design from outside it

- **S-26 — nothing is fabricated, ever.** This unit changes *where* the
  model writes and *when* bytes move, never *what is accepted*. The four
  legs `U-repair` §3.5 names — containment, recompute-and-refuse, the
  Set-J pin, deletion as the backstop — all still run, on the same
  files, before anything lands (§3.4). Deletion remains terminal; it
  merely becomes an unlink of a file that never entered the ledger.
- **H-3 — no autonomous process writes canon** (doc 13). This unit
  narrows the model's write reach from three recursive ledger globs to
  one directory outside every git repo, and — for the first time on this
  host — makes the narrowing **enforced** rather than declared (`Z1`).
- **The lock invariant** (`tests/test_lock_invariant.py`). Every byte
  that moves into the ledger moves inside `_harvest`'s `commit_lock`,
  from `_validate_written`, which is the only function that mutates.
  `_check_proposal_file` stays pure — that purity is what makes the
  invariant provable by source and it is not negotiable (`U-repair`
  §3.3, and its code gate broke a design over exactly this).
- **The attended path is untouched.** `proposal validate`'s
  report-never-delete promise, `route`, the review UI and
  `commands/review.md` are not edited. The only way this unit affects
  them is by *not* destroying what they write.
- **The working tree is production.** `~/bin/self-learn` runs master's
  working tree; the next kick executes whatever is merged. §3.7's two
  switches exist so a misbehaving change can be turned off without a code
  edit at 3 AM.
- **`U-repair` is merged and its criteria are live.** §3.5 is the
  complete list of what this unit may alter in them. Anything not listed
  there must survive.

---

## 3. The change

### 3.1 Stage-1 — the exclusive namespace (NORMATIVE)

- `ST-a` — **the stage** is `stage_dir() = _p("worker.stage")`, i.e.
  `cache_dir()/worker.stage/`. It is per-ledger-home (doc 13 H-4), lives
  outside every git repo, is never committed, and is never read by any
  surface but the worker.
- `ST-b` — **flat, no subdirectories.** A staged proposal is
  `stage_dir()/lrn-<id>.yaml` or `stage_dir()/merge-<8 hex>.yaml`. The
  destination bucket is resolved by the *worker* from the batch (`ST-e`),
  never encoded in the staged path. **Rationale, pinned because the
  obvious alternative is a known trap:** a bucket-keyed stage layout
  would key on a bucket *name*, and bucket identity is `(scope, name)` —
  a name-keyed layout silently merges two buckets that share a name in
  different scopes.
- `ST-c` — **cleared at the top of every run** (`Seq-2` `S1`). Nothing
  persists between runs; a crashed run's litter is removed by the next
  run's clear, not swept later.
- `ST-d` — **only the model writes it, and only the worker reads it.**
  The stage is the *only* path the batch and repair invocations may
  write (`Grant-1`). Nothing else in the product writes it.
- `ST-e` — **the destination resolver.** For a staged `lrn-<id>.yaml`,
  the destination is `<bucket_dir>/proposals/lrn-<id>.yaml` where
  `<bucket_dir>` is that of the batch entry whose `record.id == <id>`.
  For a staged `merge-<hex>.yaml`, it is the bucket of its **first
  member record** as read from the staged file's `records:` list. A
  staged file whose id resolves to no batch entry (`lrn-`) or whose
  `records:` is empty/unresolvable (`merge-`) has **no destination**: it
  is model litter, refused and unlinked from the stage with today's
  invalid-output line.

- `ST-f` — **the naming contract moves with the namespace** *(r1 gate
  NOTE 2)*. `_check_proposal_file`'s `expected_shape` today requires
  `path.parent.name == "proposals"` (`worker.py:1946`), which is **false
  for every staged path** — left alone, this unit's happy path refuses
  100% of the model's output as "unexpected artifact outside the proposal
  naming contract". The replacement is stated here once and is
  security-adjacent (it is what `test_unexpected_artifacts` pins):
  `path.parent == stage_dir() or path.parent.name == "proposals"`, with
  the suffix (`.yaml`) and prefix (`lrn-`/`merge-`) legs **unchanged**.
  Because the stage is flat (`ST-b`), a staged file in a subdirectory
  fails the parent test and is litter — which is exactly the recursive
  `rglob` hazard the shipped `_proposal_snapshot` docstring warns about,
  preserved rather than dropped.

**What the stage is not:** it is not a queue, not durable state, and not
a second source of truth. Its entire lifetime is one run — with **one**
deliberate exception, the install journal (`IJ`, §3.4), which lives
*outside* the stage precisely so it survives the clear.

### 3.2 Grant-1 — the permission contract (NORMATIVE)

Measured, not assumed. `Z1`–`Z3` are the measurements; this is the rule.

- `GR-a` — **every settings file the worker writes carries
  `"permissions": {"defaultMode": "default", "allow": [...]}`.** Without
  the `defaultMode` key the grant is **void on this host**: the user's
  global `~/.claude/settings.json` sets
  `permissions.defaultMode: bypassPermissions`, and a CLI-supplied
  `--settings` file that does not override it inherits it. Measured both
  ways (`Z1`): in today's shipped shape an *ungranted* write landed; with
  the key present the identical write was refused with `is_error: true`
  and a `permission_denials` entry. This applies to **both**
  `write_settings_file` and `write_repair_settings_file`.
  **STATUS — VERIFY, DO NOT BUILD; and the order is an obligation, not a
  hope** *(r2 gate NOTE 2)*. **Hotfix `1251552` must be merged to master
  BEFORE this unit's build branches from it.** The two changes edit the
  *same payload expressions* in `write_settings_file` and
  `write_repair_settings_file`, so building this unit on a pre-hotfix
  master produces a textual conflict at merge and, worse, invites
  whichever side lands second to resolve it by dropping the other's
  change. `AD10` carries this as a merge obligation.
  `GR-a` is landed ahead of this
  unit as a minimal hotfix (both settings writers + content tests),
  because a void write scope is live production exposure and this unit
  will not merge in time for the next worker window. **The builder must
  treat the hotfixed tree as the baseline**: `GR1` becomes a
  *verification* criterion asserting the property still holds after this
  unit's changes, not a build task, and a builder who finds `GR-a`
  already satisfied has found the expected state, not a merge accident.
  What this unit still owns is `GR-a` surviving the **relocation** — the
  key must be present on the *stage* settings file and on the repair
  settings file this unit rewrites.
- `GR-b` — **the batch invocation's allow list is exactly one rule**:
  `stage_permission_rules(home) == [f"Edit(/{stage_dir()}/**)"]`. The
  three ledger globs (`write_permission_rules`) are **not** in it.
- `GR-c` — `write_permission_rules(home)` is **kept, unchanged, and
  exported**, used only by the `SELF_LEARN_STAGE=0` fallback (§3.7). It
  is not deleted, because the fallback's promise is "today's write
  target", and that function *is* today's write target.
- `GR-d` — **the repair invocation** keeps `U-repair` §3.7's shape: one
  exact-path `Edit(/<abs path>)` rule per member of `E`, sorted — now
  over **staged** paths. `U-repair`'s `D5` therefore survives with its
  subject relocated, and its "or the glob fallback, if the builder's
  probe showed exact-path rules do not match" branch is **removed**: the
  probe has been run (`Z2`) and exact-path and glob `Edit(...)` rules
  both match, for create and for modify.
- `GR-e` — **the stage may live outside `cwd`.** Measured (`Z3`): with
  `cwd` set to one directory and a granted `Edit(/<other dir>/**)` rule,
  the write landed. No workspace-root restriction defeats an XDG-cache
  stage.

**What the `Edit(...)` rule family can and cannot express, since the
question is FW-84's own** *(the fifth residual's enforcement surface)*:

- it **can** scope writes to a path or a recursive glob, absolutely,
  and it governs the `Write` tool as well as `Edit` (`Z2` exercised
  both create and modify under one glob);
- it **cannot** express **create-only**. There is no rule verb that
  grants creation and withholds overwrite; one `Edit(<dir>/**)` rule
  granted both in the same run (`Z2`).
- The tempting workaround — emit a `permissions.deny` entry for every
  proposal file that exists at `S1`, leaving creation allowed — is
  **refused on record.** The model's normal path *is* overwriting an
  existing stale proposal for a batch record (§1.2), so a deny-the-extant
  rule blocks the analyst on the common case. Create-only semantics for
  analyst writes are therefore **not rule-expressible and must be
  structural**, which is what `Stage-1` + `Install-1` are.

### 3.3 Seq-2 — the run sequence (NORMATIVE)

Stated as a **delta over `U-repair`'s `Seq-1`**. A step not listed here
is unchanged, including its code and its log lines.

| # | change |
|---|---|
| `S1` | **gains** `stage_reset(home)` — remove the stage directory and recreate it empty — *before* composing the prompt. `snap0 = _proposal_snapshot(home)` is **unchanged** and stays: it is now the baseline for `Install-1`'s (`I-b`), not an attribution device. |
| `S2` | unchanged but for the settings file's contents (`Grant-1`). |
| `S3` | **replaced.** `staged1 = staged_paths()` — the files directly in the stage, sorted. This is the model's round-1 output **by construction**. `_written_since(home, snap0)` is **not** called here. |
| `S4` | unchanged in function (`_dry_check_batch` over `staged1`, mutating nothing) but each path is checked **against its destination-resolved record** (`ST-e`); the resolver's result is carried on the verdict. |
| `S5` | unchanged, with `E` computed over `staged1`. `E-4` survives with a narrowed role and `E-5` is retired — see §3.5 `RT3`/`RT4`. |
| `S6` | unchanged. |
| `S7` | **replaced by two sets, computed here:** `staged = staged_paths()` (both rounds' output — the stage is not cleared between rounds) and `foreign = _written_since(home, snap0)`, which is now **exactly the set of proposal files some producer other than this run's model wrote or changed during the window.** |
| `S8` | `_harvest(home, staged, roster, refuse=refuse, foreign=foreign, snap0=snap0)` — **two passes, in this order**, then the sweep and the commit. Still the only locked section, still the only mutation site. |

**`S8`'s two passes (NORMATIVE), because r1 left the second one implicit
and lost `D7` with it** *(r1 gate BLOCKER 2)*:

- **Pass 1 — the model's output.** For each staged path: `U-repair`'s
  per-file order, then `Install-1`. Installs, stamps, counts, or drops
  the staged file. This is the only pass that writes the ledger.
- **Pass 2 — `Rule-Fp`, foreign progress (NORMATIVE).** For **every**
  member of `foreign` — not only the ones a decline happened to name —
  compute the verdict **read-only** and, if `Rule-F` holds on it (F-a ∧
  F-b, predicate unchanged, §3.8/`CP7`), record it in
  `result.foreign_left` and log `U-repair`'s Rule-F line verbatim.
  Nothing in this pass installs, stamps, counts toward
  `proposed`/`valid_landed`, or appends to `touched`. Names are
  de-duplicated against pass 1.

**Why pass 2 must be independent of declines.** r1 populated
`foreign_left` only when a staged file *for the same destination* was
declined. But the common shape is the model producing **no** staged
output for a record at all — at FW-83's measured 13–30% yield, that is
the majority case — while a concurrent attended session validates that
record's proposal inside the window. Under r1's reading there is no
decline, so `foreign_left` is empty, `valid_landed` is 0, `status` is
`failed`, `worker.last-run` is skipped, the staleness alarm fires and
the failure counter increments toward the follow-on cap
(`worker.py:2758-2779`) — on a run whose queue advanced. That is exactly
the false failure `U-repair`'s `D7` exists to prevent, and r1 would have
re-introduced it while its own criterion asserted `status == "ok"`.
`RT7` pins the world r1 had no criterion for.

**The bound on pass 2's real-world reach, stated rather than left as an
implied universal** *(r2 gate NOTE 5)*. `Rule-F`'s F-a includes
`_roster_sha_dishonest` against **this run's** composed roster
(`worker.py:1428-1464`). A foreign proposal written against a *different*
composition — a roster that changed between windows, which is exactly
what happens when a skill is added or edited — carries a `roster_sha`
that fails F-a, so pass 2 does not fire for it and the run reports
`failed` despite the queue having advanced. So pass 2 closes the
false-failure hole **for the matching-roster case**, which is the common
one, and not universally; `RT7` is written as the matching-roster
criterion and is valid as such. Widening it would mean relaxing an
honesty check to improve a status line, which is the wrong trade and is
not made here.

**Pass 2 has exactly one carve-out, and it is a ratified ranking, not an
exception this unit invents.** A `foreign` path whose **secret scan**
hits is deleted with today's line, as `U-repair` `D3` requires: "a
scan-hitting file reaches the remote through autosync; that outranks
attribution" (§3.8). Preserving that ordering is the reason this unit's
"never delete what we did not write" rule is stated with one named
exception rather than as an absolute it would then violate (§3.4).

**The invariant, restated because this unit moves the bytes:** no ledger
mutation may precede its lock. `S1`'s `stage_reset`, `S3`/`S7`'s reads
and `S4`/`S5`'s classification touch **no ledger path at all**; the only
ledger writes this unit performs are the installs and stamps inside
`_validate_written`, under `_harvest`'s `commit_lock`, exactly where
`U-repair` put them.

**`_check_proposal_file` stays pure.** It gains a `dest: Path | None`
parameter (resolved by the caller per `ST-e`) and returns it on the
verdict. It still never writes, stamps, dumps, copies or deletes.

### 3.4 Install-1 — when bytes may move into the ledger (NORMATIVE)

Applies inside `_validate_written`, per staged path, **after** that
path's verdict is `error is None` and after `U-repair`'s per-file order
(naming contract → secret scan → `read_proposal` → refusal-map override →
resolve the record → `validate_proposal` + roster-sha honesty). A staged
file that fails any of those is deleted **from the stage** and logged
with today's line; it never reaches this rule and never enters the
ledger.

> **Install-1.** A validated staged proposal is installed at its
> destination `d` (`ST-e`) iff **either**:
> **(I-a)** `d` does not exist; **or**
> **(I-b)** `d`'s current bytes are byte-identical to `snap0`'s digest
> for `d` — nobody wrote it during the window — **and** `d` carries a
> `record_sha` key; **or**
> **(I-c)** `d` has a live **install-journal** (`IJ`) entry from a
> previous run **and** `d`'s current bytes still hash to that entry's
> recorded digest (or `d` is absent) — it is this worker's own
> interrupted install, untouched since. Otherwise `I-c` does **not**
> fire and the path falls through to the ordinary decline.
>
> **All legs are evaluated at `S8`, on `d`'s state under the lock.** A
> `d` that is **absent from `snap0` but exists now** was created during
> the window and is therefore **not** byte-identical: `I-b` fails and the
> install is declined. Stated explicitly because the `.get()`-shaped
> implementation of that comparison silently inverts it (`MA19`).
>
> Otherwise the install is **declined**: the staged file is dropped, `d`
> is **not written, not stamped, not deleted, not staged for commit and
> not counted in `proposed`/`valid_landed`/`touched`**. A decline is
> logged once and recorded in `result.not_installed` (§3.8). **Progress
> accounting is not decided here** — it is `Rule-Fp`'s, in `S8`'s pass 2
> (§3.3).

**`IJ` — the install journal (NORMATIVE)** *(r1 gate MAJOR 1; reshaped by
the r2 gate's BLOCKER 1 and MAJOR 1)*. A file at
`_p("worker.install-journal")` — in the cache, **outside** the stage, so
`ST-c`'s clear does not remove it — holding one
**`(destination, digest)`** pair per line, where `digest` is
`sha_anchor` of the bytes **this worker wrote** to that destination.

- **The digest is the whole safety property, and r2 shipped without it**
  *(r2 gate BLOCKER 1)*. A journal keyed on the path alone is an
  unconditional overwrite licence: between an interrupted run and the
  next window — minutes to hours — an attended session can legitimately
  write that exact path, because it *is* a batch record's proposal, the
  shared path §1.2 is entirely about. r2's `I-c` said "treated exactly as
  `I-a`", which bypasses `I-b`'s byte-identity check, so the next run
  would overwrite the human's bytes from the stage: **the FW-84 incident,
  re-entering through the machinery added to recover from a crash.** With
  the digest, `I-c` authorises overwriting **only the exact bytes this
  worker left behind**, and the moment anyone else touches that path the
  entry stops matching and the ordinary decline applies. `IN11` drives a
  concurrent producer into that gap.
- **Written before the copy; the entry is removed after the stamp
  succeeds**, per file.
- **Read, written and pruned only inside `S8`'s pass 1, under
  `_harvest`'s lock — there is no bulk truncation and no read at `S1`**
  *(r2 gate MAJOR 1)*. r2 read-then-truncated at `S1`, **before** the
  model window — the documented kill zone (a 1800 s invocation; FW-83's
  01:09Z window was killed by user decision on this host). A kill there
  discarded the licence for a still-valid unstamped destination and
  recreated the permanent stall `IJ` exists to prevent, one crash later.
  Entries are instead removed **individually**: on a successful stamp,
  or when found **stale** (the destination's digest no longer matches, so
  another producer has taken it over — dropping the entry is the correct
  reading of that). An unconsumed entry may persist across many windows
  and is inert while it does, because the digest leg makes it
  unusable against anything but the bytes it names.
- **The failure it exists for, measured against the shipped code.**
  `AD7` stamps *after* the copy, so a kill, a timeout, or a
  `stamp_proposal` exception leaves a **valid, unstamped** destination
  that the worker itself wrote. Under `I-a`/`I-b` alone that file is
  declined **every window, forever** — a permanent stall whose run also
  reports `status == "failed"` and feeds the backoff
  (`worker.py:2758-2779`) until the follow-on is suppressed. `IJ` is
  what makes the two-step recoverable.
- **And it covers the torn write**, since `write_text` is not atomic
  (`M5`/`AD8`): a crash mid-copy leaves a truncated destination, which is
  the same journaled state and the same recovery.
- **On a `stamp_proposal` exception the staged file is dropped and the
  destination is LEFT IN PLACE, journaled** — never rolled back. Rolling
  back is not expressible: when the destination was an overwrite, the
  pre-install bytes are already gone. Roll-forward through `IJ` is the
  only honest recovery, and the shipped `except` branch — which deletes
  `path`, i.e. under this design the **staged** file — must not be
  "helpfully" widened to delete the destination (`MA36`).

**Why (`I-b`) has two legs, and what each one is for.**

- **byte-identity to `snap0`** is the provenance fact this unit buys.
  The model cannot write the ledger (`Grant-1`), so a destination that
  changed during the window changed at *someone else's* hand. Declining
  is then not a heuristic: it is a refusal to overwrite a file we know we
  did not write. This is the leg that closes the incident's whole family.
- **the `record_sha` key** covers the *pre-window* draft. A destination
  unchanged during the window may still be an attended session's
  in-flight proposal written before the run started — and `U-repair`'s
  `Construction-1` observes exactly why the worker never notices: a file
  written before `run()` is already in `snap0`. Only two things put a
  `record_sha` on a ledger proposal — a completed worker install, and a
  `proposal validate` that passed (`selfcheck.py:167-192`) — so an
  **unstamped** destination is, necessarily, somebody's unfinished draft.
  This is `U-repair`'s `E-5` insight, retired from eligibility and
  re-sited where it is sound.

**What `Install-1` does not do, stated correctly this time** *(r1 gate
MAJOR 4 — r1 claimed "the only deletions this unit performs are of
staged files", which is false)*. `Install-1` itself never deletes a
ledger path: every declined destination is left exactly as found. But
**three other deletions run inside the same locked section**, and a
reader must not be told otherwise:

1. **`_still_pending`'s orphan sweep** (`worker.py:2097-2128`) `git rm`s
   every `lrn-*.yaml` with no pending record and every merge proposal
   whose members are gone — **provenance-blind**, and reachable in
   exactly this unit's concurrency: an attended session that *routes* a
   batch record mid-window resolves it, and this run then sweeps the
   proposal. **Declared OUT of scope, with the bound stated rather than
   hidden:** a routed record's proposal *should* be swept — that is the
   sweep doing its job, not a provenance failure — and the sweep is
   pre-existing behaviour this unit neither widens nor narrows. It is
   named here so "the worker never deletes what it did not write" is
   read as `Install-1`'s property, not the run's.
2. **The secret-scan carve-out** on `foreign` paths (§3.3 pass 2),
   preserving `U-repair` `D3`'s ratified ranking.
3. **Staged files**, in the cache, that the model wrote this run — the
   deletion backstop, unchanged in effect from S-26's.

**The shipped `Φ` skip must be REMOVED from pass 1** *(r1 gate MAJOR 2)*.
`_validate_written`'s `if verdict.phi and not verdict.is_hook:` branch
(`worker.py:2066-2076`) leaves a matching-`record_sha` file entirely
alone. Applied to a **staged** path it is a silent black hole: the
measured copy-the-sha-you-found shape (`U-repair` `D6(i)` measured 4 of 6
pending proposals stamped-and-invalid) produces a valid staged file
carrying a matching `record_sha`, which would then be **never installed,
never stamped, never deleted — yet counted toward `status == "ok"`** via
`foreign_left`, so the record never lands and never alarms, every window.
A staged file's provenance is settled by *where it is*; `phi` must have
no vote on it. `phi` survives as a field and is read **only** by pass 2's
`Rule-Fp`. `IN9` pins the removal, with a fixture that drives a **valid**
staged file carrying a matching `record_sha` — `U-repair`'s `D6(i)`
covers only the invalid one.

**The copy primitive is pinned, not left to the builder** *(r1 gate MAJOR
5)*. The install writes the destination with **`Path.write_text`** (and,
for a merge, `_dump_yaml`, which is the same writer `U-repair` already
uses). `shutil.copy*` is **forbidden**: `test_lock_invariant.py`'s
analyser recognises `write_text`/`rename`/`unlink` plus `shutil.move` and
`os.replace` (`:85`, `:223-229`) — a `shutil.copy` install would be
**invisible** to the invariant that is this project's whole defence, and
this unit's file table authorises `NOT_REPO_TRUTH` additions only, never
an analyser extension. `AD8` records the atomicity trade this choice
makes and `IJ` is what pays for it.

**The residual it creates, declared here and pinned by `IN5`:** a
destination that is permanently an unstamped draft (a human abandoned a
proposal mid-session) is declined every window, so its record is
re-analyzed every window and never lands. It is visible — one log line
and one counter per run — and a human resolves it by validating or
deleting the draft. Accepted; the enumeration-side fix (skip records
whose destination is a foreign draft) is refused in §7.1 because it
changes queue semantics, which is a different unit's blast radius.

### 3.5 What survives from `U-repair`, and what legitimately changes (NORMATIVE)

This section is the complete divergence list, in **three buckets**
*(r1 gate BLOCKER 1: r1's two-bucket version claimed "assertion,
mechanism AND fixture intact" for members that measurably cannot keep
their fixtures, and contradicted its own `CP4`)*. **A `U-repair`
criterion not named in any bucket below must survive whole.**

**Bucket 1 — assertion, mechanism and fixture all intact.** These do not
drive a run with a shim-written proposal, so the namespace never reaches
them: `U-repair` `A1`–`A4` (the checklist and the exemplar, read from
constants and doctrine), `E1`–`E4` (constants and timeout readers), `E7`
(the backoff gate's location), `F3`, `F4`, `F6`.

**`H1`, `H2` and `F1` were in bucket 1 in r2 and do not belong there**
*(r2 gate MAJOR 2)*. The error had r1-BLOCKER-1's exact shape — membership
computed by matching the literal `worker.run(`, which is blind to
cli-mediated runs. Measured: `test_h1_the_exit_code_contract` and
`test_h2_the_stdout_summary_is_byte_stable` drive via
`cli.main(["worker", "run"])` **and** call `shim_writes` → **bucket 2**.
`F1` (`test_worker.py::test_run_argv_pins`) drives `worker.run()`, stages
output, **and** asserts `rules == [the three ledger globs]` — which
`GR-b` replaces → **bucket 3**, beside `TestWorkerContainment`. Leaving
`F1` in bucket 1 would have reproduced the §3.5-versus-criterion
contradiction with §0 still naming §3.5 the arbiter.

**Bucket 2 — assertion intact; fixture relocates to the stage.** The
shim writes the model's output into `stage_dir()` instead of into
`<bucket>/proposals/`; **nothing about what is asserted changes.** This
is the build's mechanical scope. Members: `U-repair` `A5`, `B1`–`B13`,
**all eight `G` tests** (`G1`–`G8` — the Set-J pin, the `V`-rule, the
four fabrication legs and the sentinel re-assert), `E5`, `E6`, `E8`,
`F2`, `F5`, `H1`, `H2`, `H3`, `H4`, `H5`, `D2`, `D4`, `D5`, `D6(i)`,
`D8(i)`. **`CP4` is the worked example of this bucket, not an exception
to bucket 1** — r1 had `G1` in both, and `§0` makes this section the sole
arbiter, so the contradiction resolved the wrong way.

**The size, measured here with its predicate stated** *(r2 gate MAJOR 3:
r2 quoted "33 of 55 / 23", which were an estimate adopted as a
measurement — the failure this project keeps re-learning)*. Predicate,
stated so the number is checkable rather than trusted: *a test **drives a
run** if its body reaches `worker.run(`, `cli.main([… "worker", "run" …])`
or `_cmd_worker`; it **relocates** if it also makes the shim write —
`CLAUDE_SHIM_SCRIPT*`, `shim_writes`, or any `*_script(` helper.* Under
that predicate:

| file | tests | drive a run | **relocate** |
|---|---|---|---|
| `test_repair.py` | 55 | 44 | **43** |
| `test_worker.py` | 45 | 23 | **18** |

The single non-relocating driver in `test_repair.py` is
`test_f6_no_test_invokes_a_real_claude`; the five in `test_worker.py` are
the idle run, the deferred skip, the no-sync-script guard, escalation and
the sentinel release. **The count is predicate-sensitive** — a narrower
"stages a proposal literal" reading yields 30 and the r2 gate's own
reading yielded 41 — so **the build's obligation is the predicate, not
the integer**, and a builder should re-run it rather than trust any
number in this table.

**Bucket 3 — meaning changes.** The table below; each row names its
replacement criterion here.

**Legitimately altered, each with its replacement criterion here:**

| `U-repair` id | what changes | replaced/extended by |
|---|---|---|
| `D1` | assertion **survives verbatim** (the foreign validated proposal exists, bytes unchanged, absent from `proposed`/`invalid_deleted`/`touched`, named in `foreign_left`, Rule-F line logged); the **mechanism** becomes `Install-1`'s decline rather than a Rule-F skip inside the model-output loop, and the fixture no longer needs `Construction-1`'s in-window trick to be *seen* | `IN2`, `RT1` |
| `D6(ii)`, `D6(iii)` | **retired as partition rules.** `Φ` leaves `S5`'s partition entirely: a foreign file is a ledger file and is never in `staged1`, so it can never reach `V`. The **guarantee** they protect — a foreign proposal edited during the repair window is never deleted — is preserved by the namespace and must be asserted directly | `RT2` |
| `D8(ii)` (`E-5`) | **retired.** No staged file can be an attended edit, so "unstamped" no longer discriminates eligibility. The insight is re-sited into `Install-1` (`I-b`) | `RT4`, `IN3` |
| `D8(iii)` | **retired and INVERTED.** This is the flagship retirement: the pinned residual becomes a pinned *impossibility*. The test must now assert that a never-validated attended proposal for a batch record appears in **no** repair prompt and is **not** overwritten | `RT3` |
| `D8(i)` (`E-4`) | survives, **role narrowed**: it is no longer a provenance filter (everything staged is the model's) but a litter filter — a staged `lrn-<id>.yaml` for a non-batch id has no destination and is refused | `RT5`, `ST-e` |
| `D7` | assertion **survives verbatim** (a foreign file makes `status` `ok`, touches `worker.last-run`, stays out of `proposed`/`valid_landed`/`touched`); the **mechanism** moves from Rule-F inside the model-output loop to `S8`'s independent pass 2, which is what makes it hold when the model wrote nothing for that record | `RT7`, §3.3 pass 2 |
| `D3` | **the fixture inverts, and the ranking is preserved.** Today the concurrent producer's secret-bearing proposal is scanned-and-deleted because it is in `written1`; here the model's own output is scanned in the **stage** and never reaches the ledger at all — strictly stronger. For a **foreign** ledger path the scan still runs and still deletes, as the single named carve-out (§3.3 pass 2), because `U-repair` ratified scan-over-attribution and this unit does not get to re-rank it silently | `CP5`'s new secret-with-matching-`record_sha` leg, `IN10` |
| `D9` | **fails outright as written, and is replaced.** Its assertion ("a hook proposal satisfying F-a ∧ F-b is nonetheless stamped and counted in `proposed`") is *unfalsifiable in the stage* — with the `Φ` skip removed (`IN9`), **no** staged file is ever left foreign, hook or not — and *false in the ledger*, where pass 2 never stamps or counts anything. What `D9` protects — no model-authored `script:` bytes ever reaching `route` — is preserved by a stronger property: **every** staged hook proposal is installed only through the stamp, which regenerates `script`. Its converse must also be stated: a **foreign** hook proposal in the ledger is now left entirely alone rather than stamped-and-committed, which is safe precisely because a ledger hook proposal the worker did not write is either a previous install (already stamped) or an attended `proposal validate` (also stamped) | `RT8` |
| `F1` (`test_worker.py::test_run_argv_pins`) | *(r2 gate MAJOR 2)* it drives a run, stages output **and** asserts `rules == [the three ledger globs]` — an assertion `GR-b` replaces outright. Both its fixture and its expectation change | `GR2`, `SW1` |
| `test_hosting.py::TestWorkerContainment` | both tests change subject: the batch allow list becomes `Grant-1`'s one stage rule, and the settings file gains `defaultMode` | `CP8`, `GR1`, `GR2` |

**Explicitly NOT altered, with owners, so scope cannot creep:**

- **The foreign-hook-commit trade** — a genuinely foreign
  `destination: hook` proposal being stamped, counted and committed.
  Root: **script generation as a stamp-time side effect**
  (`ledger_ops.py:1700-1701`), with `_validate_hook_extension`
  (`:589-595`) never checking `script` against the `hook:` block. Owner:
  **`U-repair` §3.8**, whose un-adopted alternative (regenerate and
  compare) is named there. This unit does not adopt it, does not touch
  `stamp_proposal`, and does not claim to fix it. *One honest side
  effect must be stated rather than smuggled:* because the worker no
  longer validates or stamps ledger files it did not produce, that
  specific cell is no longer reachable **through the worker's landing
  path**. The root is untouched and still live on the attended path
  (`proposal validate` stamps, and stamping is still where `script` is
  generated), so the bullet stays `U-repair`'s and `D9` stays green
  here.
- **Backoff-suppression visibility** — today only in `worker.log`; not
  in `fast_status` or the UI. Root: operability. Owner: **FW-82**. This
  unit adds counters to `RunResult` and log lines (`Obs-2`) and
  deliberately surfaces **none** of them in `fast_status`, `cli.py`'s
  stdout summary or the UI; `OB4` pins that as a refusal, not an
  oversight.
- **The elicitation contract, the repair round's shape, `Set-C`,
  `Set-E`'s text rules, `Set-J`, `Set-P`/`Set-Q`, the timeouts and the
  backoff** — all `U-repair`'s, all unchanged.

### 3.6 Where the model is told to write

One instruction moves. `_PROMPT_TEMPLATE`'s opening
(`worker.py:1237-1239`) currently says to write each proposal at
`<bucket>/proposals/lrn-<id>.yaml`, and the merge instruction
(`:1256`) at `<bucket>/proposals/merge-<8 hex>.yaml`. Both become the
stage's **absolute** path, interpolated once per prompt:
`<stage>/lrn-<id>.yaml` and `<stage>/merge-<8 hex>.yaml`.

Three properties are load-bearing and are pinned by `NS4`:

- the batch prompt contains **no** `<bucket>/proposals/` write
  instruction anywhere after the change — a prompt that names both
  targets teaches the model to try the denied one;
- `compose_record_block` keeps `bucket:` in the per-record block
  (`worker.py:594`) — it is read material for the canon excerpt and the
  path roster, not a write target, and removing it would degrade routing;
- the merge instruction's `cluster_id`-equals-filename rule
  (`worker.py:1259-1263`) is preserved verbatim; only the directory
  changes.

**The compliance risk is real and is owned here, not hand-waved.** If the
model writes to the old path it is now **denied** (`Grant-1`), the run
produces zero staged files, `status` is `failed`, the staleness alarm and
the backoff fire, and `worker.log` carries the denial. That is a loud
failure, not a silent one — and it is the failure `AD4`'s canary
obligation exists to catch on the first live window.

### 3.7 Degradation, and the two switches (NORMATIVE)

Both switches revert exactly one thing, and both fail toward **today's**
behaviour, never toward wider deletion.

- `SELF_LEARN_STAGE=0` — **the namespace switch.** `S1` does not clear a
  stage; the batch allow list is `write_permission_rules(home)` (the
  three ledger globs, `GR-c`); the repair round's exact-path rules are
  over ledger paths as `U-repair` shipped them; `S3`/`S7` are
  `_written_since(home, snap0)` as today; `Install-1` is not consulted
  (there is nothing to install — the model wrote in place); `Rule-F`
  applies in `_validate_written` exactly as `U-repair` shipped it. The
  run is then behaviourally today's, with `U-repair`'s residuals back.
  Logged once: `run: stage disabled (SELF_LEARN_STAGE=0)`.
- `SELF_LEARN_ENFORCE_SCOPE=0` — **the enforcement switch.** The
  `defaultMode` key is omitted from both settings files, i.e. the exact
  file the shipped code writes today. Provided because `defaultMode`
  turns a silently-permitted write into a hard denial, and a 3 AM
  regression there must be reversible without a code edit.

**Deliberate asymmetry, stated because it deviates from `U-repair`'s
BD10 "byte-identical to today" phrasing:** `SELF_LEARN_STAGE=0` does
**not** disable `defaultMode`. Reverting the namespace without reverting
enforcement leaves the model writing where it writes today, under the
scope the shipped code has always *claimed*. Reverting enforcement is the
other switch's job, and doing it as a side effect of the first would
re-open H-3 containment silently.

**Where the switch actually goes, because a file-free revert path is not
a revert path** *(r1 gate MAJOR 3)*. `_spawn_window` copies
`os.environ` into the detached child (`worker.py:925-947`), so either
variable **propagates down a follow-on chain once set at its root** — but
the roots differ and only one of them reads a shell:

- **timer-triggered runs** get their environment from
  `systemd/self-learn-miner.service`, whose own comment records the trap
  (*"the systemd user manager does not inherit the shell's env"*, B-1 /
  doc 13 §7.1). A revert here means adding
  `Environment=SELF_LEARN_STAGE=0` to that unit and
  `systemctl --user daemon-reload`. **`export` in a terminal does
  nothing for these runs** — that is the failure mode this paragraph
  exists to prevent at 3 AM.
- **hand-kicked and nightly wrapper runs** inherit from `~/bin/self-learn`
  (user-owned, outside this repo), so an `export` in that wrapper — or in
  the invoking shell — is sufficient for them and only them.

Both switches must be documented with those two locations in the merge
report, and `SW1`/`SW2` are the criteria that stop either from being a
claim no test ever exercised.

**No stream-json dependence exists to degrade.** This unit parses no
model output and reads no CLI event format, so there is no version-fragile
surface to fail toward anything (§8).

### 3.8 Obs-2 — the observable surface (NORMATIVE)

**Unchanged, and must stay byte-identical** — every line, code and field
`U-repair`'s Obs-1 pins, including `run: ok — N proposal(s), M merge, K
invalid deleted`, `run: FAILED — …`, `run: invalid worker output <name>
deleted (<reason>)`, `run: orphan proposal <name> swept`, `worker run`'s
exit codes and stdout summary, the whole repair-round series, and
Rule-F's line verbatim.

**New lines** (formats load-bearing from this unit onward):

| when | line |
|---|---|
| after `S3` | `run: stage — {n} file(s) written by the model` |
| after `S7`, iff non-empty | `run: {n} ledger proposal(s) changed during the window — not this run's writes` |
| an install is declined, per file | `run: staged proposal {name} not installed — destination changed during the window` |
| an install is declined for the draft leg | `run: staged proposal {name} not installed — destination is an unstamped draft this run did not write` |
| a staged file has no destination | `run: invalid worker output {name} deleted (no batch record for {stem})` — today's invalid-output format, reused deliberately |
| namespace switched off | `run: stage disabled (SELF_LEARN_STAGE=0)` |
| an interrupted install is recovered | `run: resuming interrupted install of {name} (journal)` |
| a stamp raised after the copy | `run: {name} installed but not stamped ({exc}) — journaled for the next run` |

**New `RunResult` fields** — additive only; no existing field changes
type or meaning: `staged_written: int`, `not_installed: list[str]`
(destination names, never installed), `foreign_seen: int` (the size of
`S7`'s `foreign` set).

**`touched` keeps its type discipline** *(r1 gate NOTE 3)*.
`_git_rm_or_unlink` unlinks **and appends its path to `result.touched`**
(`worker.py:1631-1633`), which `_commit_locked` then stages — and
`touched` is documented as *"every **ledger** path this run wrote or
deleted"* (`worker.py:1019-1021`). Dropping a **staged** (cache) path
into it is measured harmless at commit time (`_commit_locked` skips a
path that neither exists nor is tracked) but it is a type lie one edit
away from staging a cache path into a ledger commit. **The fix is
structural, not documentary:** staged files are discarded by a separate
`_stage_discard(path)` that unlinks and appends **nothing**;
`_git_rm_or_unlink` stays exactly as shipped and keeps serving the
orphan sweep and the secret carve-out. `OB3` pins it.

**Deliberately not surfaced anywhere else** — not in `fast_status`, not
in `cli.py`'s stdout summary, not in the UI (`OB4`). Operator-facing
surfacing of worker internals is FW-82's, and adding it here is the
scope creep §3.5 forbids.

---

## 4. Acceptance criteria

**These criteria are the contract.** Each states what its check reports
when the target is **absent or broken**. Tests live in
`tests/test_attrib.py` unless a criterion says otherwise.

**No test may invoke a real `claude`.** The seam is `subprocess.run` in
`run`; the fixture is the PATH shim driven by `$CLAUDE_SHIM_SCRIPT` and
its numbered per-invocation forms (`U-repair` `F5`). Every fixture below
that says "the model writes X" means "the shim writes X into
`stage_dir()`"; every fixture that says "a concurrent producer writes Y"
means "the shim writes Y into a bucket's `proposals/`, standing in for
the attended session".

### NS — the namespace

**NS1 — the stage is cleared at `S1`, and its litter never lands.** Seed
the stage before the run with a file that would otherwise validate
(a complete valid proposal for a batch record) and with one junk file.
Run. Assert neither reaches the ledger, and that the valid pre-seeded
file is **not** in `result.proposed` — because `S1` removed it before the
model ran.
*Broken:* `MA1`. Without the clear, a crashed previous run's stale
proposal lands as if this run's model wrote it — the same
attribute-what-you-find defect this unit exists to remove, relocated.

**NS2 — a staged file is installed at its resolved destination, in the
right bucket.** Two batch records in **two different buckets**. The shim
writes one valid staged proposal for each. Assert each lands at its own
`<bucket_dir>/proposals/lrn-<id>.yaml`, that both are stamped, that
`result.proposed` names both and `result.buckets` names both buckets.
*Broken:* `MA2`. A resolver that returns the first bucket for everything
passes a single-bucket fixture and cross-files every record in a
multi-bucket ledger.

**NS3 — a staged file with no destination is litter, not output.** The
shim writes `lrn-<id>.yaml` for an id that is **not** in the batch, and a
`merge-<hex>.yaml` whose `records:` list is empty. Assert both are
deleted from the stage, both appear in `result.invalid_deleted`, and
**nothing** was written under any bucket's `proposals/`.
*Broken:* `MA3`. A resolver that falls back to "some bucket" invents a
destination for a record the worker was never asked about.

**NS4 — the prompt tells the model one place to write, and it is the
stage.** Compose a batch prompt. Assert it contains
`str(stage_dir())`; assert it contains **no** occurrence of
`proposals/lrn-` or `proposals/merge-` as a write instruction; assert the
per-record block still carries its `bucket:` line; assert the
`cluster_id`-equals-filename sentence is present verbatim.
*Broken:* `MA4` (leaves the old instruction in beside the new one) and
`MA5` (strips `bucket:` from the record block). The first teaches the
model to try a denied path; the second is the over-correction that
degrades routing.

**NS5 — the stage is not a ledger path.** Assert `stage_dir()` is
under `cache_dir()`, is not inside `home`, and that no bucket's
`proposals/` directory is an ancestor or descendant of it.
*Broken:* `MA6` (stage under `home/.worker-stage`) — which would put
model output inside the git worktree, where autosync and `git add -A`
elsewhere could publish unvalidated bytes.

**NS6 — the naming contract accepts the stage and nothing looser.**
Four legs against `_check_proposal_file` (`ST-f`): a staged
`lrn-<id>.yaml` passes the shape test; a staged `merge-<hex>.yaml`
passes; a staged file in a **subdirectory** of the stage is refused as
`unexpected artifact outside the proposal naming contract`; a staged
`notes.txt` is refused with the same message. Then the shipped
`test_unexpected_artifacts` leg: a ledger path outside `proposals/` is
still refused.
*Broken:* `MA34` (leave `path.parent.name == "proposals"` unchanged) —
which refuses **100% of the model's output** and turns this unit's happy
path into a total pipeline failure that every other criterion's fixture
would have to work around; and `MA35` (drop the parent test entirely) —
which accepts a staged file from any subdirectory and re-opens the
recursive-write hazard `_proposal_snapshot`'s own docstring exists for.

### GR — the grant

**GR1 — the settings file enforces, rather than declares.** Assert
`json.loads(write_settings_file(home))["permissions"]["defaultMode"] ==
"default"`, and the same for `write_repair_settings_file`.
*Broken:* `MA7` — which reddens `GR1` regardless of *which* change built
the property, so `GR1` is a fully-mutated criterion like any other
*(r2 gate NOTE 1: r2 described it three inconsistent ways at once)*.
Past tense, now that the hotfix has landed: this criterion **did** fail
on the shipped code before `GR-a`, and `Z1` is why it is a criterion
rather than a preference. What it verifies here is that the property
**survives this unit's relocation** of both settings files.

**GR2 — the batch invocation is granted the stage and nothing else.**
Assert the batch settings file's `permissions.allow` equals
`stage_permission_rules(home)`, that this is exactly one rule, that the
rule names `stage_dir()`, and that **no** rule mentions any bucket's
`proposals/`, any host path, or `.self-learn`.
*Broken:* `MA8` (allow list is `stage_permission_rules(home) +
write_permission_rules(home)` — the "be safe, grant both" edit that
silently restores the whole defect).

**GR3 — the repair invocation is narrower still, over staged paths.**
Assert the repair settings file's `permissions.allow` has exactly one
entry per member of `E`, that every entry is an absolute `Edit(//…)`
rule naming a **staged** path, that none is a glob, and that
`defaultMode` is present.
*Broken:* `MA9` (repair settings reuse `stage_permission_rules`). This is
`U-repair` `D5` relocated; its glob-fallback branch is gone because `Z2`
settled it.

**GR4 — `write_permission_rules` is preserved for the fallback.** Assert
it still returns `U-repair`'s three globs verbatim, and that
`SELF_LEARN_STAGE=0` makes `write_settings_file` emit exactly them.
*Broken:* `MA10` (delete the function as dead code) — which removes the
kill switch's target and makes §3.7 a lie.

### IN — the install

**IN1 — the ordinary path: absent destination.** One batch record, no
existing proposal. The shim writes a valid staged proposal. Assert it is
installed, stamped, counted in `proposed`, appears in `touched`, and is
committed.
*Broken:* `MA11` (decline when the destination is absent) — the
over-tight twin that makes every other IN criterion pass while landing
nothing. This is `IN`'s positive control and must be red-verified.

**IN2 — the incident: a destination written during the window is never
overwritten and never deleted.** One batch record whose proposal file
exists and is **valid and stamped** at `S1`. During the model window the
shim (a) writes the model's own staged proposal for that record and (b)
rewrites the ledger file with different valid, stamped bytes — the
attended session, still working. Assert: the ledger file's bytes are
**exactly the concurrent producer's**, the staged file did not land, the
name is in `result.not_installed`, it is in `result.foreign_left`, it is
**not** in `proposed`/`invalid_deleted`/`touched`, and `U-repair`'s
Rule-F line was logged.
*Broken:* `MA12` (drop `I-b`'s byte-identity leg). **This is the FW-84
incident**, and `MA12` reproduces it.

**IN3 — a pre-window unstamped draft is not overwritten.** The
destination exists at `S1`, is schema-valid, and carries **no**
`record_sha`; nothing touches it during the window. The shim writes a
valid staged proposal for that record. Assert the ledger file's bytes are
unchanged, the staged file did not land, the name is in
`result.not_installed`, and the draft-leg log line was emitted.
*Broken:* `MA13` (drop `I-b`'s `record_sha` leg) — the install then
overwrites an attended draft that `U-repair`'s `Construction-1` explains
the worker never even sees today.

**IN4 — a stale stamped destination IS overwritten.** The destination
exists at `S1`, carries a `record_sha` that does **not** match the record
(the ordinary stale-proposal case), and is untouched during the window.
Assert the staged proposal is installed, re-stamped, and counted.
*Broken:* `MA14` (require the destination's `record_sha` to *match*) —
which declines the single most common eligibility path and stalls the
whole drain.

**IN5 — a decline is loud, counted, and non-destructive.** Across `IN2`
and `IN3`: assert `result.not_installed` names the destinations, that
neither destination was deleted, that the stage is empty after the run,
and that `_git_rm_or_unlink` was never called on either destination.
*Broken:* `MA15` (delete the staged file **and** the destination on
decline) — a "clean up the conflict" edit that converts a refusal to
overwrite into the deletion this unit exists to prevent.

**IN6 — declines do not fake a failure, and do not fake a success.** Two
runs. (a) The batch's only outcome is one decline whose destination is
**fresh** (Rule-F holds): assert `status == "ok"`, `worker.last-run`
exists, `proposed == []`, `foreign_left` names it, the failure counter
does not exist. The fixture's batch is below `BATCH_CAP` so
`worker.dirty` is cleared and no follow-on is spawned. (b) The batch's
only outcome is one decline whose destination is an **unstamped draft**
(Rule-F does not hold): assert `status == "failed"` and `foreign_left ==
[]`.
*Broken:* `MA16` (count every decline as progress) — which reports a
successful run whenever an abandoned draft blocks the queue, hiding the
`IN3` residual behind a green status. Leg (a) is `U-repair` `D7`'s
assertion, preserved; leg (b) is the discrimination `D7` never had to
make.

**IN7 — every install happens under the lock, and nothing else does.**
Source-level, in `tests/test_lock_invariant.py`'s idiom: assert
`_check_proposal_file` contains no call to `write_text`, `unlink`,
`rename`, `_dump_yaml`, `stamp_proposal`, `shutil.copy*` or
`_git_rm_or_unlink`; assert the install site is inside
`_validate_written`; assert the whole shipped `test_lock_invariant.py`
suite passes unmodified except for `HY2`'s exemption entries.
*Broken:* `MA17` (install from `_check_proposal_file` when a flag is
set) — the shape `U-repair`'s code gate proved a spec can ship and a
static analyser cannot forgive.

**IN8 — an interrupted install is recovered, not stalled forever.**
Crash fixture, in four parts. (a) **Simulated crash:** monkeypatch
`stamp_proposal` to raise on its first call; run; assert the destination
exists, is unstamped, has an `IJ` entry whose digest equals the
destination's bytes, the staged file is gone, the destination was **not**
deleted, and the "installed but not stamped" line was logged. (b)
**Recovery:** run again with a fresh staged proposal for the same record
and a working stamp; assert `I-c` fired (the "resuming interrupted
install" line), the install landed, the record is in `proposed`, and the
entry is gone from `IJ`. (c) **No entry, no licence:** a third run whose
destination is unstamped-and-unchanged with **no** `IJ` entry
**declines**. (d) **The kill-zone leg** *(r2 gate MAJOR 1)*: kill the run
between the journal write and the stamp — i.e. raise from
`stamp_proposal` — then assert that a run which **fails inside the model
window** (shim exits non-zero, nothing staged) leaves the entry intact,
and that the run **after** that still recovers via `I-c`.
*Broken:* `MA36` (on a stamp exception, delete the destination as well as
the staged file — leg (a) then finds no destination and no entry to
recover from); `MA37` (drop `I-c`) — the destination is declined every
window forever while the run reports `failed` and drives the backoff to
the follow-on cap (`worker.py:2758-2779`); and `MA38` (read and truncate
`IJ` at `S1`, r2's shape) — leg (d) goes red, because the licence is
discarded before the kill zone it exists to survive.

**IN11 — the journal is not an overwrite licence.** *(r2 gate BLOCKER
1.)* Stage the crash of `IN8(a)` to leave a journaled, unstamped
destination. Then, **in the gap before the next run**, have the
concurrent-producer shim rewrite that exact path with different valid
bytes — the attended session legitimately picking up the record. Run.
Assert: the destination's bytes are **the concurrent producer's**, the
staged proposal did **not** land, the name is in `result.not_installed`,
the destination was **not** deleted, and the stale `IJ` entry was
dropped. Second leg — the positive control: the identical fixture
**without** the concurrent write installs normally, so a build that
simply disables `I-c` cannot pass both.
*Broken:* `MA49` (journal the destination only, with `I-c` treating it as
`I-a` — r2's shape). **This is the FW-84 incident re-entering through the
recovery machinery**, and it is the mutation this criterion exists for.

**IN9 — a staged file with a matching `record_sha` is installed like any
other.** The shim writes a **valid** staged proposal for a batch record
whose body carries that record's correct `record_sha` (the measured
copy-the-sha shape). Assert it is installed, **re-stamped**, counted in
`proposed`, in `touched`, committed — and **not** in `foreign_left`.
*Broken:* `MA39` (keep `_validate_written`'s `verdict.phi and not
verdict.is_hook` skip). The file is then never installed, never stamped,
never deleted **and counted toward `status == "ok"`** — a record that
silently never lands and never alarms, every window. `U-repair`'s
`D6(i)` cannot catch this: it drives the *invalid* member of the same
population.

**IN10 — the secret carve-out survives, on both sides.** (a) A
**staged** file with a secret-scan hit is deleted from the stage, appears
in `invalid_deleted` with today's line, and **nothing** is written under
any bucket's `proposals/`. (b) A **foreign** ledger path that changed
during the window and carries a secret-scan hit **is deleted**, with
today's line, even though the worker did not write it.
*Broken:* `MA40` (skip the scan on the foreign pass, reasoning that the
worker never deletes what it did not write) — which silently re-ranks a
decision `U-repair` settled and lets a scan hit reach the remote through
autosync.

### RT — the retirements (FW-84's residual family)

Each of these asserts that a residual `U-repair` §7.3 declared is now
**closed**, and each names the `U-repair` criterion it replaces.

**RT1 — "written but not yet validated during the model window".** The
shim writes, during the model window, a **valid, unstamped** proposal
directly into a bucket's `proposals/` for a batch record, and separately
writes the model's own staged proposal for that same record. Assert the
attended file's bytes are unchanged, it is not stamped, it is not
deleted, and the staged file did not land.
Run the fixture twice: once with the destination **absent** at `S1` (the
attended session creates it during the window) and once with a stale
stamped destination present at `S1` (the attended session replaces it).
*Broken:* `MA18` (the candidate set takes the ledger's changes back, so
the file is validated and stamped as model output) and `MA19` (the
absent-from-`snap0` comparison inverts, so a destination created during
the window reads as unchanged and is overwritten). Under `U-repair` this
file is validated, stamped or deleted as model output; that is the
residual, and this is its retirement.

**RT2 — "edited after validation, caught mid-edit" (replaces `U-repair`
`D6(ii)`/`D6(iii)`).** The destination is valid and stamped at `S1`; the
round-1 shim writes the model's staged proposal for it; the **round-2
(repair) shim** edits the ledger file again, leaving it mid-edit and
schema-invalid. Assert the ledger file is **not deleted**, is not in
`invalid_deleted`, is not refused with `repair rewrote a proposal that
had already validated`, and that the staged file did not land over it.
Run the same fixture a second time with `destination: hook` and assert
the identical three negatives.
*Broken:* `MA18` — which puts the ledger file back into both `S5`'s
partition and `S8`'s candidate set, so the `V`-rule's `refuse` entry has
something to act on and the mid-edit file is deleted: `U-repair`'s
`MAJOR 7` cell, reopened. *(A mutation that widens `S5`'s partition
**alone** is a no-op here and must not be mistaken for this one: a
`refuse` entry for a path that is not in `S8`'s candidate set is never
read. That asymmetry is itself worth a reviewer's attention.)* Under
`U-repair` this file is deleted (F-b holds, F-a fails); that is the
residual, and this is its retirement.

**RT3 — "a never-validated attended proposal for a batch record is
repair-eligible" (replaces and INVERTS `U-repair` `D8(iii)`).** A
schema-invalid, `gates.`-refused, **unstamped** proposal for a **batch**
record exists in a bucket's `proposals/`, written by the concurrent
producer. Assert: its path appears in **no** repair prompt; it is not in
`E`; it is not deleted; its bytes are unchanged after the run. The test's
docstring must name `U-repair` §7.3 and state in one line that this was
that spec's pinned residual and is now impossible because the model has
no grant to that path.
*Broken:* `MA20` (build `E` from `staged1 ∪ foreign`). Under `U-repair`
this file is handed to a second model under a write grant and a
successful repair lands and commits it; that is the residual, and this is
its retirement.

**RT4 — `E-5` is retired, and nothing regressed with it.** Assert
`repair_eligible_paths` is computed **without** consulting
`record_sha_matches`, and that a staged file whose body happens to carry
a matching `record_sha` **is** repair-eligible when its refusal is
`gates.`-shaped.
*Broken:* `MA21` (keep the `E-5` clause) — which is not a safety net
here but a silent narrowing: a model that copies a `record_sha` into its
own output would lose its repair round for no reason. `U-repair`'s
`E-5` insight lives on in `Install-1`'s (`I-b`), which `IN3` pins.

**RT5 — `E-4` survives as a litter rule, not a provenance rule.** Assert
that a staged file for a non-batch id is refused by the **destination
resolver** (`NS3`), and that `_repairable` is still text-only —
`E-1`…`E-3` and nothing else — with `U-repair`'s `Table-E` rows all still
classifying as they did.
*Broken:* `MA22` (fold the batch-membership check into `_repairable`) —
which re-creates the composed-eligibility shape `U-repair`'s delta-2 gate
refused, in a unit whose whole thesis is that provenance is structural.

**RT6 — "an uncommitted model-authored foreign file".** A run in which
the model's staged output is valid and its destination is absent: assert
the installed file is in `touched`, is staged for commit, and
`result.committed` is true. Then a run in which the destination changed
during the window: assert nothing was committed for that record and
nothing uncommitted was left in the ledger.
*Broken:* `MA23` (append declined destinations to `touched`) — which
commits bytes the worker did not write, the exact harm `U-repair`
accepted this residual rather than risk. Under `U-repair` a model-written
Φ file is left uncommitted forever; here the model's file is either
installed-and-committed or dropped, and the ledger is never left holding
an orphan the worker will not own.

**RT7 — foreign progress without any staged output for that record.**
*(r1 gate BLOCKER 2 — the world r1 had no criterion for, and the one
FW-83's yield makes common.)* Fixture: two batch records, both below
`BATCH_CAP` so `worker.dirty` is cleared. The model writes **no** staged
file for record A at all (the 13–30%-yield reality); during the model
window the concurrent-producer shim writes a **complete, valid,
correctly-stamped** proposal for A into its bucket. The model writes
nothing valid for B either. Assert: `result.status == "ok"`;
`worker.last-run` exists; `foreign_left` names A; `foreign_seen >= 1`;
`proposed == []`; `valid_landed == 0`; `touched == []`; A's bytes are
unchanged; the failure counter file does **not** exist; and no follow-on
was spawned.
*Broken:* `MA41` (populate `foreign_left` only from `Install-1`
declines — r1's reading). `status` is then `failed`, `worker.last-run`
is skipped, the staleness alarm fires and the backoff increments on a run
whose queue advanced — `U-repair`'s `D7` regression, re-introduced by the
unit that claimed to preserve it.

**RT8 — no model-authored `script:` can reach `route`, and a foreign hook
is left alone** (replaces `U-repair` `D9`, §3.5). Two legs. (a) The shim
writes a staged `destination: hook` proposal carrying a model-authored
`script:` **and** a matching `record_sha`; assert it is installed and its
`script` equals `_generate_hook_script`'s output for that record — the
stamp overwrote the model's bytes — and that it is counted in `proposed`.
(b) A **foreign** valid stamped hook proposal changed in the ledger
during the window with no staged counterpart; assert it is not stamped,
not counted in `proposed`, not in `touched`, not committed, and its bytes
are unchanged.
*Broken:* `MA42` (let a staged hook proposal skip the stamp when its
`record_sha` already matches) — model-authored executable bytes then
reach `route`, which applies stamped bytes **verbatim** (M3-2), and
`stamp_proposal`'s own stated guarantee ("no path ships model-authored
script text") becomes false. Leg (b) is the positive control: without it,
`MA42`'s over-tight twin — stamping every hook proposal the worker can
see, including foreign ones — passes leg (a) while re-creating
`U-repair`'s own §7.3 hook bullet inside this unit.

### CP — compatibility with `U-repair`

**CP1 — the whole shipped suite is green.** `uv run --project
plugins/self-learn/cli pytest` and `uv run --project
plugins/self-learn/ui pytest` both pass, with no failure other than the
one known pre-existing `test_service_unit.py` symlink case.
*Broken:* running it. No mutation is listed; the instrument is the suite.

**CP2 — `Seq-1`'s step identities and log lines survive.** Assert every
Obs-1 line in §3.8's "unchanged" list is emitted, byte-identical, by a
run that exercises it.
*Broken:* `MA24` (reword `run: invalid worker output …` for staged
files, on the reasoning that they were never "output" in the ledger) —
the plausible edit that breaks `review.md`'s and the UI's contract.

**CP3 — the repair round still works, end to end, over staged paths.**
A staged proposal refused with a `gates.`-shaped message is repaired by
the round-2 shim and lands. Assert `repair_attempted`,
`repair_eligible == 1`, `repair_cleared == 1`, and the
`run: repair round: 1 of 1 refusals cleared` line.
*Broken:* `MA25` (`E` is computed over ledger paths, so the exact-path
grants name files the model cannot see) — the repair round then silently
repairs nothing while reporting a set.

**CP4 — the Set-J pin still binds.** `U-repair` `G1`'s fixture, relocated
to the stage: a repair that flips an already-legal gate answer is refused
and deleted.
*Broken:* `MA26` (skip the Set-J comparison for staged paths, since "the
model owns them anyway") — the reasoning is true and the conclusion is
wrong: Set-J guards the *first* pass's judgment against the *second*
pass, both of which are the model's.

**CP5 — containment, recompute-and-refuse and the deletion backstop are
unchanged for files that ARE the model's.** Four legs on staged files:
a fabricated RECORD quote is refused and deleted; a laundered
`gates.outcome` is refused and deleted; a file still refused at `S8` is
deleted and its record stays pending; and — the leg the namespace makes
newly reachable *(r1 gate MAJOR 6)* — a staged file carrying a **matching
`record_sha` AND a secret-scan hit** is deleted, not skipped: `U-repair`'s
per-file order puts the scan **before** `read_proposal`, so `phi` is
never even computed for it, and with the `Φ` skip removed (`IN9`) there
is no branch left that could rescue it.
*Broken:* `MA27` (install before validating, then delete on failure) —
which lands unvalidated bytes in the ledger for the width of one
function call and leaves them there if the process dies.

**CP6 — the sentinel re-assert still happens after the last invocation
and before the first mutation.** `U-repair` `G8`, unchanged.
*Broken:* `U-repair`'s `M21`, which must still redden.

**CP7 — `Rule-F`'s predicate is unchanged.** Source-level: assert
`Rule-F` is still F-a (`validate_proposal` accepts **and**
`_roster_sha_dishonest` returns `None`) ∧ F-b (`record_sha` equals
`sha_anchor(pending_record.body)`), evaluated regardless of destination,
and that the hook carve-out still governs stamp-or-leave only.
*Broken:* `MA28` (reduce Rule-F to F-b now that provenance is
structural) — tempting, and wrong: `U-repair`'s `D6(i)` measured that
F-b alone is model-reachable, and Rule-F still decides progress
accounting for real files.

**CP8 — `TestWorkerContainment` asserts the new containment, and still
asserts H-3.** The batch allow list is `Grant-1`'s one rule; no rule
mentions any host path or `.self-learn`; the settings file carries
`defaultMode`.
*Broken:* `MA8`, `MA7`.

**CP9 — the merge happy path installs with its `record_shas`.** *(r1 gate
NOTE 1 — the only shipped merge happy path lives in `test_worker.py`, and
this unit moves the file it exercises.)* Two batch records in one bucket;
the shim writes both `lrn-*` staged proposals and one valid staged
`merge-<hex>.yaml` naming them. Assert the merge lands at the bucket
resolved from its **first member record** (`ST-e`), that the installed
file's `record_shas` map is present and correct for both members, that
`result.merge_proposed` names the cluster id, and that the installed
bytes are `_dump_yaml`'s output — not a byte copy of the staged file.
*Broken:* `MA43` (install merges by copying the staged bytes, like an
`lrn-*`) — `record_shas` is resolved **in memory** at `S4` (`U-repair`
§3.3) and exists nowhere in the staged file, so the byte copy lands a
merge proposal with no shas at all: valid-looking, and dead at
`route --collapse`.

**CP10 — a repair that deletes its staged file does not kill the run.**
*(r1 gate NOTE 1, and §5's lead (c).)* The round-2 shim **deletes** one
of the staged paths in `E` instead of editing it. Assert `run()` returns
normally with a `RunResult`, the `A`-set's Set-J comparison does not
raise on the missing file, the record stays pending, and a log line names
the disappearance.
*Broken:* `MA44` (read the post-repair text unguarded). `run()`'s body
has a `try:` at `worker.py:2536` with a `finally:` at `:2751` and **no
`except`**, so the exception escapes a `Popen`-detached process: a stack
dump into `worker.log`, no commit, no sentinel release ordering anyone
reviewed, and a dead run — the exact shape `U-repair`'s BLOCKER B exists
to prevent.

### SW — the switches

**SW1 — `SELF_LEARN_STAGE=0` reverts the namespace, end to end.** A
**full run** under the switch, not a file assertion: assert the batch
settings file's allow list is `write_permission_rules(home)` verbatim;
that no stage directory is created; that a shim writing into
`<bucket>/proposals/` (today's shape) produces a landed, stamped,
committed proposal; that `Rule-F` fires on a foreign stamped file exactly
as `U-repair` shipped it; that `not_installed` is empty; and that the
`run: stage disabled (SELF_LEARN_STAGE=0)` line is logged.
*Broken:* `MA45` (the switch gates only the settings file, leaving `S3`
reading the stage) — the run then writes into the ledger and harvests an
empty stage: **zero proposals land, silently**, which is the worst
possible behaviour for the control that exists to rescue a bad night.
`U-repair`'s `B9` is the precedent for testing a kill switch by running
it rather than by reading it.

**SW2 — `SELF_LEARN_ENFORCE_SCOPE=0` reverts enforcement, and only
that.** A full run under the switch: assert **both** settings files omit
`defaultMode` and are otherwise byte-identical to the enforcing form,
that the stage is still used, and that the run still installs normally.
Then assert the two switches are independent: `SELF_LEARN_STAGE=0` alone
leaves `defaultMode` **present** (§3.7's deliberate asymmetry).
*Broken:* `MA46` (make `SELF_LEARN_STAGE=0` drop `defaultMode` too) —
which reverts a security-relevant change as an undocumented side effect
of reverting an unrelated one, and is the reading §3.7 exists to forbid.

### OB — the observable surface

**OB1 — the new lines exist with their counts.** Drive a run producing
two staged files, one decline of each kind, and one changed ledger file;
assert each §3.8 line appears with correct counts.
*Broken:* `MA29` (emit the stage line with no count).

**OB2 — the new fields are populated.** Assert `staged_written`,
`not_installed` and `foreign_seen` carry the right values on the same
run.
*Broken:* `MA30` (never assign `foreign_seen`, leaving it 0).

**OB3 — existing fields keep their meaning, and `touched` keeps its
type.** Assert `proposed`, `valid_landed`, `touched`, `invalid_deleted`,
`orphans_swept`, `foreign_left`, `buckets` and the three repair counters
all mean exactly what Obs-1 says. Plus the type leg *(r1 gate NOTE 3)*:
after a run that discards several staged files, assert **every** member
of `result.touched` is under `home` and **none** is under `stage_dir()`.
*Broken:* `MA31` (count declines in `invalid_deleted`) — which reads, to
every downstream consumer, as "the worker deleted a proposal", the one
thing it must never be able to say falsely; and `MA47` (discard staged
files through `_git_rm_or_unlink`, which appends to `touched`) — harmless
at today's `_commit_locked`, and one edit away from staging a cache path
into a ledger commit.

**OB4 — the worker's internals stay out of the operator surfaces.**
Assert `cli.py`'s `worker run` stdout is unchanged, that `fast_status`'s
returned keys are unchanged, and that no UI file references
`not_installed`, `staged_written` or `foreign_seen`.
*Broken:* `MA32` (add the counts to `_cmd_worker`'s summary) — the
harmless-looking edit that breaks a documented contract and annexes
FW-82's scope in one line.

### HY — hygiene

**HY1 — no real `claude` runs in the suite**, and the shim remains
multi-invocation-observable.
*Broken:* `U-repair`'s `M36`/`M52`, which must still redden.

**HY2 — the lock-invariant exemption list is honest.** Assert every new
stage-writing function (`stage_reset`, and any helper that unlinks a
staged file) has a `NOT_REPO_TRUTH` entry naming the XDG cache as its
target, and that `test_the_exemption_list_cannot_rot` passes.
*Broken:* `MA33` (add the entries by wildcard or add one covering
`_validate_written`) — the second is the dangerous one: it would exempt
the function that legitimately mutates the ledger.

**HY3 — pyright is clean** on the touched files, and the new
`RunResult` fields are typed.
*Broken:* running it.

**HY4 — the install is visible to the lock-invariant analyser.**
Source-level: assert the install writes via `Path.write_text` (or
`_dump_yaml` for a merge), that `worker.py` imports no `shutil` copy
helper, and — the falsifiable leg — that
`test_lock_invariant.py`'s own **`_primitive`** classifier (`:218`)
**returns a primitive** for the install's call node. The test imports and
calls that function by name *(r2 gate NOTE 3: r2 called it
`_mutating_call`, which does not exist — an import-and-call criterion
naming a non-existent symbol fails as an `ImportError`, not as the check
it claims to be)*.
*Broken:* `MA48` (install with `shutil.copy2`). The analyser recognises
`write_text`/`rename`/`unlink`, `shutil.move` and `os.replace`
(`test_lock_invariant.py:85`, `:223-229`) — `copy2` is in none of them,
so the whole install becomes invisible to the invariant and the suite
still passes. A green test suite proving nothing is the failure mode this
criterion exists for.

---

## 5. Mutation plan

The code gate runs these. **Before any sweep:** `export
PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` — a stale cache
reports mutations as survived that never executed (FW-61). Confirm
`realpath(self_learn.__file__)` resolves inside the tree under review.

| # | one-line edit | reddens |
|---|---|---|
| MA1 | skip `stage_reset` at `S1` | NS1 |
| MA2 | destination resolver returns the first bucket for every id | NS2 |
| MA3 | resolver falls back to the first bucket when the id is not in the batch | NS3 |
| MA4 | keep the `<bucket>/proposals/` write instruction beside the stage one | NS4 |
| MA5 | drop `bucket:` from `compose_record_block` | NS4 |
| MA6 | `stage_dir()` → `home / ".worker-stage"` | NS5 |
| MA7 | omit `defaultMode` from both settings files | GR1, CP8 |
| MA8 | allow list = `stage_permission_rules(home) + write_permission_rules(home)` | GR2, CP8 |
| MA9 | repair settings file reuses `stage_permission_rules(home)` | GR3 |
| MA10 | delete `write_permission_rules` as dead code | GR4 |
| **MA11** | decline the install when the destination is absent | **IN1** — the positive control; without it every other IN criterion passes on a build that lands nothing |
| **MA12** | drop `I-b`'s byte-identity leg | **IN2** — the FW-84 incident, reproduced |
| **MA13** | drop `I-b`'s `record_sha` leg | **IN3** |
| MA14 | require the destination's `record_sha` to **match** in `I-b` | IN4 |
| MA15 | on decline, delete the destination as well as the staged file | IN5 |
| MA16 | count every decline toward `status` | IN6 leg (b) |
| MA17 | perform the install inside `_check_proposal_file` behind a flag | IN7, and the shipped `test_lock_invariant.py` |
| **MA18** | `S3`/`S7`'s candidate set becomes `staged_paths() + _written_since(home, snap0)`, **and** `S5`'s partition with it, with a path already sitting at its destination handled in place (validate → stamp → or delete) — i.e. `U-repair`'s attribution restored alongside the stage | **RT1, RT2** — both the never-validated file being stamped and `U-repair` MAJOR 7's cell |
| **MA19** | `Install-1` reads `snap0.get(d) == digest` such that a destination **absent** from `snap0` compares equal (the `.get()`-default trap, §5 lead (b)) | **RT1** — a destination the attended session *created* during the window reads as unchanged and is overwritten |
| **MA20** | build `E` from `staged1 ∪ foreign` | **RT3** — `U-repair`'s pinned residual, reopened |
| MA21 | keep the `E-5` (`not v.record_sha_matches`) clause in `E` | RT4 |
| MA22 | fold the batch-membership test into `_repairable` | RT5 |
| MA23 | append declined destinations to `result.touched` | RT6 |
| MA24 | reword `run: invalid worker output …` for staged files | CP2 |
| MA25 | compute `E` over ledger paths while the grants name staged ones | CP3 |
| MA26 | skip the Set-J comparison for staged paths | CP4 |
| MA27 | install first, validate after, delete on failure | CP5 |
| MA28 | reduce `Rule-F` to F-b | CP7, and `U-repair`'s `D6(i)` |
| MA29 | emit the stage line with no count | OB1 |
| MA30 | never assign `foreign_seen` | OB2 |
| MA31 | count declines in `invalid_deleted` | OB3 |
| MA32 | add the new counts to `_cmd_worker`'s stdout summary | OB4 |
| MA33 | exempt `_validate_written` in `NOT_REPO_TRUTH` | HY2 |
| **MA34** | leave `_check_proposal_file`'s `path.parent.name == "proposals"` unchanged | **NS6** — refuses 100% of the model's output |
| MA35 | drop the parent test from `expected_shape` entirely | NS6 |
| MA36 | on a stamp exception, delete the destination as well as the staged file | IN8(a) |
| **MA37** | drop `I-c` (no install journal) | **IN8(b)** — permanent stall + backoff to the follow-on cap |
| **MA38** | read and truncate `IJ` at `S1`, before the model window (r2's shape) | **IN8(d)** — a kill in the 1800 s window discards the licence and recreates the stall |
| **MA49** | journal the destination **only**, with `I-c` treating a journaled path exactly as `I-a` (r2's shape) | **IN11** — the FW-84 incident, re-entering through the recovery machinery |
| **MA39** | keep `_validate_written`'s `verdict.phi and not verdict.is_hook` skip | **IN9** — the silent black hole |
| MA40 | skip the secret scan on the foreign pass | IN10(b) |
| **MA41** | populate `foreign_left` only from `Install-1` declines (r1's reading) | **RT7** — `U-repair`'s `D7` regression |
| **MA42** | let a staged hook proposal skip the stamp when its `record_sha` matches | **RT8(a)** — model-authored `script:` reaches `route` |
| MA43 | install merges by copying staged bytes instead of dumping the prepared document | CP9 |
| MA44 | read the post-repair text of an `A`-set path unguarded | CP10 |
| **MA45** | `SELF_LEARN_STAGE=0` gates only the settings file, leaving `S3` reading the stage | **SW1** — zero proposals land, silently |
| MA46 | `SELF_LEARN_STAGE=0` also drops `defaultMode` | SW2 |
| MA47 | discard staged files through `_git_rm_or_unlink` | OB3's type leg |
| **MA48** | install with `shutil.copy2` | **HY4** — the install becomes invisible to the lock invariant while the suite stays green |

**Every criterion has at least one mutation above except `CP1`, `CP6`
and `HY1`/`HY3` — deliberately, and stated so the omission is not read as
the same gap.** `CP6` and `HY1` are reddened by `U-repair`'s own `M21`,
`M36` and `M52`, which this unit must keep red; `CP1` and `HY3` are
process gates over the whole tree, and the instrument that checks them is
running them. **`GR1` is NOT in this list** *(r2 gate NOTE 1)*: it is
verified-not-built in the sense that the hotfix supplies the property,
but `MA7` reddens it here all the same — "who built it" and "can a
one-line edit break it" are different questions, and only the second one
decides whether a criterion needs a mutation.

**`U-repair`'s mutation plan must still redden its own criteria**, with
the four exceptions §3.5 names (`M46`, `M49a`, `M53` and the `D8(ii)`
leg of `M49` lose their targets when `Φ`'s partition and `E-5` retire).
A gate should verify those four are *retired with their criteria*, not
silently surviving as green no-ops.

**Reviewers are invited to invent mutations not listed here.** Three
shapes this unit is most likely to be wrong in, named as leads rather
than findings:

- **(a)** *(promoted to `CP9`/`MA43` in r2, kept here as the reasoning)*
  the merge branch — `record_shas` are resolved in memory at `S4`
  (`U-repair` §3.3) and the file is written by `_dump_yaml`; an install
  path that copies staged **bytes** for merges instead of dumping the
  prepared document lands a proposal without its `record_shas`;
- **(b)** the install destination and the **stamp** destination are
  resolved by two different functions and must agree.
  `stamp_proposal(home, record_id)` (`ledger_ops.py:1680-1698`) finds the
  record itself (`find_record_path`) and derives the proposal path from
  *that* bucket; `ST-e` derives it from the **batch entry**. They agree
  today, and a resolver that ever disagrees would copy bytes to one path
  and stamp another — leaving an unstamped install and a
  `no proposal sibling for <id>` refusal that reads like a model defect;
- **(c)** *(promoted to `CP10`/`MA44` in r2)* the repair round deleting a
  staged path rather than editing it — `staged` at `S7` is the stage's
  contents, not a diff, and the `A`-set's Set-J comparison must not raise
  on a missing file inside a `run()` that has no `except`;
- **(d)** the `foreign` set's own cost — pass 2 runs `validate_proposal`
  and resolves a record for **every** changed ledger proposal. It is
  bounded by how much an attended session writes in one window, not by
  `BATCH_CAP`, and it is the one unbounded loop this unit adds.

---

## 6. Builder decisions, made here rather than left open

- **AD1 — the stage is flat and the worker resolves buckets.** Rejected:
  mirroring the bucket tree inside the stage. It would key on a bucket
  *name*, and bucket identity is `(scope, name)`; a name-keyed mirror
  merges two same-named buckets in different scopes. The batch already
  knows every record's bucket, so the resolver costs nothing (`ST-e`).
- **AD2 — `snap0` stays, and `_written_since` stays.** Neither is
  deleted. `snap0` becomes `Install-1`'s baseline and `_written_since`
  becomes the exclusion set (`S7`'s `foreign`). Rewriting them would
  churn code whose behaviour this unit depends on being exactly what it
  is.
- **AD3 — declines never delete.** The alternative ("resolve the
  conflict by keeping the newer file") requires the worker to adjudicate
  between two producers' bytes, which is the authority this whole unit
  exists to take away from it.
- **AD4 — first-window canary obligation.** The merge report must record
  the **first live window** after merge: the stage's file count, the
  install/decline counts, and `worker.log`'s denial lines if any. The
  elicitation risk in §3.6 is the one risk this unit cannot test away,
  and the instrument is the first real run, read deliberately rather
  than assumed.
- **AD5 — the probe is a builder obligation too.** `Z1`–`Z3` were run
  against a scratch home, not the ledger. The builder re-runs the
  `Grant-1` probe against the **real argv shape the build produces**
  (both settings files, both invocations) and records the outcome in the
  build report. A permission contract verified only in a spec is a
  permission contract verified by a document.
- **AD6 — no new caps, no new timeouts.** The stage adds no size limit
  and no file-count limit: the model's output is already bounded by
  `BATCH_CAP`, and a second bound would be an unmeasured lever.
- **AD7 — `stamp_proposal` is called on the installed path, after the
  copy, exactly as today.** Stamping is not moved into the stage:
  `stamp_proposal(home, record_id)` resolves its own path from the
  **record** (`ledger_ops.py:1693-1697`) and cannot be pointed at a
  staged file without editing `ledger_ops`, which this unit may not do;
  and re-implementing its two jobs — the sha and the hook `script`
  generation — inside `worker.py` would duplicate the P9 guard. **The
  cost of that decision is a two-step install, and `IJ` (§3.4) is what
  pays for it** *(r1 gate MAJOR 1: r1 took the decision and did not pay
  the cost)*.
- **AD8 — `Path.write_text`, accepting non-atomicity.** The install is
  not atomic and is deliberately not made so: the atomic idiom
  (`os.replace` of a temp file) is analyser-visible too, but it would put
  a temp file inside a bucket's `proposals/` — a path both the orphan
  sweep and `_proposal_snapshot`'s recursive `rglob` would then see. A
  torn write leaves the same journaled state as a crashed stamp, so `IJ`
  already covers it and one recovery mechanism is better than two.
- **AD10 — the merge order is part of the design** *(r2 gate NOTE 2)*.
  Hotfix `1251552` (`defaultMode` in both settings writers) merges to
  master **first**; this unit branches from a master that already
  contains it. Both changes edit the same payload expressions, so the
  reverse order is a textual conflict whose most likely resolution is
  someone dropping one of the two changes — and the one that looks
  droppable is the security fix. The build report states which master
  commit the build branched from.
- **AD9 — the flag-day facts, stated rather than left safe-by-silence**
  *(r1 gate NOTE 6)*. Two properties make the stage's first appearance
  safe, and both are facts about the shipped code rather than hopes:
  **(i)** `run()` holds a blocking `flock` on `_p("worker.lock")` for its
  whole body (`worker.py:2522-2523`), and the lock is per-ledger-home
  (`cache_dir()`, doc 13 H-4) — so two runs cannot bootstrap or clear the
  stage concurrently, and `ST-c`'s clear needs no lock of its own;
  **(ii)** a worker window already in flight keeps the code it imported
  at start, so merging this unit mid-window cannot change the behaviour
  of a run already executing — the next window is the first to see it,
  which is exactly what `AD4`'s canary reads.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 Not built, with reasons

- **Parsing `--output-format stream-json`** — feasible (`Z4`) and
  refused as the primary signal (§1.2, §8). Not adopted as a *secondary*
  signal either: a second, version-fragile provenance channel whose only
  effect is to agree with a structural one is cost without a decision.
- **A per-record lease** — refused: the writer that caused the incident
  consults nothing (§1.2).
- **A deny-list of extant proposal paths** to emulate create-only —
  refused: it blocks the model's common eligibility path (`Grant-1`).
- **Narrowing the batch invocation's write scope *within* the ledger** —
  still refused, exactly as `U-repair` §7.1 refused it, and §8 states why
  relocation is not that move.
- **Skipping enumeration for records whose destination is a foreign
  draft** — refused: it changes queue semantics (`proposal_info`,
  `is_unanalyzed`), which is `ledger_ops`' surface and a different unit's
  blast radius. The `IN3` residual stays visible instead.
- **Surfacing the new counters in `fast_status`/the UI** — FW-82's
  (`OB4`).
- **Touching `stamp_proposal`'s script generation** — `U-repair`'s
  (§3.5).

### 7.2 ACCEPTED residual — the permanently-blocked destination

An abandoned, unstamped attended draft at a batch record's destination is
declined every window, so its record is re-analyzed and never lands until
a human validates or deletes the draft. Accepted rather than deferred:
the alternative is either overwriting a human's work (the defect) or
changing queue semantics (out of scope). It is **loud** — one log line
and one counter per run — and `IN3`/`IN6(b)` pin both.

**r1 understated the blast radius and this is the corrected statement**
*(r1 gate NOTE 4)*. The cost is not confined to the blocked record. If
that record is the run's only outcome, `status` is `failed`, which
increments the failure counter; at `FOLLOWON_FAILURE_CAP` the follow-on
window is **suppressed** (`worker.py:2766-2779`), and the follow-on is
what drains `leftovers` — so **one abandoned human draft can stall the
backlog drain for entirely unrelated records.** The mitigation is the
same one either way (a human validates or deletes the draft), and the
detector is the `not_installed` line plus the existing suppression line;
what changes is that an operator reading them now knows the second-order
effect rather than discovering it. `IN6(b)` is the criterion that makes
the `failed` status here deliberate rather than accidental. To be
recorded as `S-33`.

### 7.3 ACCEPTED residual — a mid-window destination change loses one window

When a destination changes during the model window, this run's staged
proposal is dropped rather than merged or queued. The record stays
pending and the next window re-analyzes it. Accepted: one wasted analysis
is strictly cheaper than one destroyed human review, and merging two
producers' proposals is not a thing the worker may do (S-26).

### 7.4 What this unit does NOT close, with owners

- **The foreign-hook-commit trade** — root: script generation as a
  stamp-time side effect. Owner: `U-repair` §3.8. Unchanged here; §3.5
  states the one honest side effect and refuses to claim it as a fix.
- **Backoff-suppression visibility** — root: operability. Owner:
  **FW-82**. Unchanged here; `OB4` pins the refusal.
- **`U-repair`'s S-30 residual** (a repair clearing one Set-C defect and
  leaving a sibling is deleted, not re-repaired) — untouched and still
  `U-repair`'s.

### 7.5 Handed to `03-decisions.md`

Two rows, both landing with the build:

- **`S-32`** — *producer attribution is structural, not observational:
  the analyst writes only to a stage it exclusively owns, and the worker
  installs from the stage into the ledger under the commit lock. A ledger
  proposal that changed during the model window was, provably, not
  written by the model, and is never overwritten, stamped or deleted.
  `U-repair`'s `E-4` narrows to a litter rule, `E-5` retires into
  `Install-1`, and `Φ` leaves the repair partition.*
- **`S-33`** — *the accepted residuals of §7.2 and §7.3.*

---

## 8. What this spec re-ranks, refuses, and corrects

**Against FW-84's own three candidate directions** (evidence-ranked
input, explicitly non-binding):

| candidate | disposition |
|---|---|
| (a) parse `stream-json` tool-use events | **Refused as the primary signal**, on a design argument the row does not make: both producers legitimately write the same path, so a per-path record of the model's writes cannot answer "whose bytes are these?" (§1.2). Its feasibility and version-fragility were both measured rather than assumed (`Z4`): the events exist, carry `input.file_path`, and pair with `tool_result.is_error`; the terminal `result` event even carries `permission_denials`. The row's degradation worry is therefore **retired rather than answered** — this unit depends on no CLI output format at all, so there is nothing to degrade. |
| (b) a per-record lease | **Refused**: advisory to the one writer that caused the incident (§1.2). |
| (c) an equivalent real signal | **Adopted**, in the strongest form available: an exclusive namespace, which converts attribution from an observation into a fact and closes the fifth residual with the same mechanism. |
| create-only semantics for analyst writes (the fifth residual's named direction) | **Adopted, and relocated**: measured to be inexpressible in the `Edit(...)` rule family (`Z2`, `Grant-1`), so it is realised structurally by `Stage-1` + `Install-1` rather than by a permission rule. |

**Against `U-repair` §7.1's refusal of write-scope narrowing.** That
refusal stands and is not reversed. Its two reasons were (i) narrowing to
the batch's own proposal paths does not address the measured incident,
because the attended session was working on records *in* the batch, and
(ii) a wrong rule blocks the analyst entirely. This unit's move is not
that move: (i) a **disjoint namespace** is not a **subset** of the shared
one — the collision it removes is exactly the in-batch collision (i)
names; and (ii) the hazard is owned rather than dismissed — one rule over
one directory, verified against the live CLI for create and modify
(`Z2`), inside and outside `cwd` (`Z3`), with a kill switch (§3.7) and a
first-window canary obligation (`AD4`).

**Two corrections to shipped claims, offered so the documents do not
disagree silently:**

1. **The shipped code already half-knows the scope is void, and says the
   opposite two paragraphs earlier — that split is the correction, and r1
   stated it too crudely** *(r1 gate NOTE 5)*.
   `write_repair_settings_file`'s docstring **admits it outright** at
   `worker.py:849-855`: the host's own settings set
   `defaultMode: bypassPermissions`, *"which — same as it would for the
   ALREADY-shipped batch-invocation globs — voids every settings-file
   scope"*, and records that the probe had to set `defaultMode: "default"`
   in its own file to exercise real enforcement. The same docstring's
   **claim** at `:840-841` is that *"the CLI itself refuses writes
   outside the assigned set"*. Both sentences are in one docstring: the
   knowledge was present and did not reach the code. So the correction is
   not "nobody knew" but **"it was known, written down, and not
   acted on"** — and `Z1` is the measurement that closes the gap between
   the two halves. `Grant-1` makes the claim true; **`GR-a` is landing as
   a separate expedited hotfix ahead of this unit** (§3.2), so `GR1`
   verifies rather than builds.
2. **`U-repair` §3.7's exact-path fallback branch can be closed.** Its
   builder obligation left an "if exact-path rules do not match, fall
   back to the three globs" branch open. `Z2` settles it: a settings-file
   `Edit(...)` rule matches for both create and modify, exact-path and
   glob alike. `GR3` drops the branch.

---

## 9. What was executed, and against what oracle

All five measurements were run on 2026-08-09 against the **live CLI
2.1.226**, in scratch directories only, never against the ledger.
`Z1`–`Z3` write files; none of them is inside any git repo.

**A probe-location correction, recorded because it invalidated a first
attempt:** the initial probe base was under `~/.claude/`, and the CLI
classifies **any** path there as a "sensitive file" and denies writes to
it regardless of allow rules (`Claude requested permissions to edit
<path> which is a sensitive file`). That result says nothing about allow
rules. `Z1`–`Z3` were re-run under `/tmp/` and are reported from there.

**Two confounds the r1 gate controlled for, audited against `Z1`'s own
method and reported honestly rather than claimed away:**

- **The model reading the settings file.** `Z1` placed the settings file
  **inside `cwd`**, so the confound was *not* excluded by construction —
  only observed absent: the transcripts carry no `Read` of
  `settings-*.json` in either leg (the only `Read` is of the probe's
  pre-existing target). That is weaker than the gate's construction and
  is stated as such; a re-run should put the settings file outside `cwd`.
- **The model self-censoring on a suggestive directory name.** `Z1`'s
  ungranted path was `outside/b.txt` and `Z3`'s was `nope/control.txt`,
  both suggestive — but this confound **is** excluded by the *mechanism
  of the refusal*, not by the naming: in the enforcing leg the model
  **attempted** the write (a `tool_use` event is present) and the refusal
  arrived as a CLI `tool_result` with `is_error: true` plus an entry in
  the terminal `result` event's `permission_denials`. A model declining
  on its own produces neither. And in the non-enforcing leg the same
  model wrote the same suggestively-named path without hesitation, which
  is the direct control.

Both `Z1` legs were **independently reproduced by the r1 gate** under its
own cleaner construction.

- **`Z1` — the grant is void without `defaultMode`.** Worker argv shape
  (`-p --model claude-sonnet-5 --allowedTools Read,Grep,Glob
  --disallowedTools Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch
  --settings <file> --strict-mcp-config`), one allow rule
  `Edit(/<base>/stage/**)`, prompt asking for three writes: a new file in
  the granted dir, a modification of an existing file in the granted dir,
  and a new file in an **ungranted** sibling.
  - *Without* `defaultMode` in the settings file (**today's shipped
    shape**): all three succeeded — the ungranted write **landed**, rc 0,
    `permission_denials: []`.
  - *With* `"defaultMode": "default"`: the two granted writes succeeded
    and the ungranted one was refused —
    `tool_result.is_error: true`, message `Claude requested permissions
    to write to <path>, but you haven't granted it yet`, and one entry in
    the terminal `result` event's `permission_denials`.
- **`Z2` — `Edit(<dir>/**)` grants create *and* modify, and cannot
  express create-only.** Same run: the new file was created and the
  pre-existing file was overwritten under the same single glob rule.
- **`Z3` — a granted directory outside `cwd` is writable.** `cwd` set to
  one tree; two allow rules, one naming a directory **outside** that
  tree, one inside; plus an ungranted control inside. Both granted writes
  landed; the control was refused. An XDG-cache stage is therefore
  reachable.
- **`Z4` — `stream-json`'s shape, recorded for the refusal.**
  `--output-format stream-json --verbose` is accepted alongside the
  worker's full argv, rc 0. Event stream observed: `system` (7 ×
  `hook_started` / 7 × `hook_response` — the worker inherits the user's
  hooks — then `init`, `thinking_tokens`), `assistant` (whose
  `message.content[]` carries `{"type":"tool_use","name":"Write",
  "input":{"file_path":…,"content":…},"id":"toolu_…"}`), `user` (whose
  `content[]` carries `{"type":"tool_result","tool_use_id":…,
  "is_error":…}`), `rate_limit_event`, and a terminal `result` carrying
  `permission_denials`, `usage`, `total_cost_usd` and `terminal_reason`.
  So (a) is implementable — and that is precisely why its refusal is
  stated as a design argument (§1.2) rather than as a feasibility
  finding.
- **`Z5` — the user's global settings are the cause, not the CLI's
  defaults.** `~/.claude/settings.json` carries
  `permissions.defaultMode: "bypassPermissions"`. `Z1`'s two legs differ
  only in whether the CLI-supplied settings file overrides it, so the
  mechanism is inheritance, not a missing rule.

---

## 10. Revision history

- **r1 (2026-08-09)** — first draft. Direction chosen: exclusive
  namespace (`Stage-1`) + locked install (`Install-1`), with
  `stream-json` parsing and per-record leases both refused on the
  same-path argument (§1.2). Five measurements (`Z1`–`Z5`), two of which
  correct claims the shipped code and `U-repair` §3.7 both make.
- **r2 (2026-08-09)** — blind gate **UNSOUND: 3 BLOCKER / 6 MAJOR / 6
  NOTE**, all folded; the direction survived adversarial pressure and
  every finding was an unowned code site. Map:

  | finding | fold |
  |---|---|
  | B1 — §3.5's byte-for-byte list false, contradicts `CP4` | §3.5 rewritten as three buckets, with the measured 33-of-55 / 23 counts; `CP4` is now bucket 2's worked example |
  | B2 — `D7` lost when the model wrote nothing for the record | `S8` gains **pass 2 / `Rule-Fp`** (§3.3), `D7` moves to bucket 3, new criterion `RT7` + `MA41` |
  | B3 — `test_worker.py` missing from the footprint | added, with three enumerated edit classes (`shim_writes`, 23 run-driving tests, `test_run_argv_pins`) |
  | M1 — interrupted install stalls forever | **`IJ`**, the install journal, + `I-c` (§3.4); `IN8` + `MA36`–`MA38`; `AD7` now names the cost it pays |
  | M2 — shipped `Φ` skip unretired for staged paths | removal pinned in §3.4; `IN9` + `MA39` |
  | M3 — both switches unexercised, no revert path named | `SW1`/`SW2` + `MA45`/`MA46`; §3.7 names the unit file and the wrapper, and the `export`-does-nothing trap |
  | M4 — "the only deletions are staged files" false | §3.4 rewritten with three deletions listed; `_still_pending` declared out with its bound |
  | M5 — copy primitive invisible to the analyser | `Path.write_text` pinned; `HY4` + `MA48`; `AD8` records the atomicity trade |
  | M6 — `D3`/`D9` change meaning | both added to bucket 3; `D3`'s ranking preserved as a named carve-out (`IN10`), `D9` replaced by `RT8` |
  | N1 — merge happy path, repair-deleted staged path | `CP9`/`MA43`, `CP10`/`MA44`; §5 leads (a)/(c) marked promoted |
  | N2 — `parent.name == "proposals"` false for staged paths | `ST-f` + `NS6` + `MA34`/`MA35` |
  | N3 — `_git_rm_or_unlink` puts cache paths in `touched` | `_stage_discard` (Obs-2); `OB3` gains a type leg + `MA47` |
  | N4 — §7.2 understates the blast radius | corrected: one draft can suppress the follow-on and stall unrelated records |
  | N5 — docstring half-knowledge | §8 correction 1 rewritten: `:849-855` admits it, `:840-841` claims the opposite |
  | N6 — flag-day facts safe by silence | `AD9` (per-home `worker.lock`; in-flight windows keep loaded code) |

  Also folded: `GR-a` re-scoped to **verify-don't-build** against the
  expedited hotfix baseline, and `Z1`'s two confounds audited in §9 —
  one excluded by the refusal mechanism, one only *observed* absent and
  reported as the weaker claim it is.
- **r3 (2026-08-09)** — delta gate **UNSOUND: 1 BLOCKER / 3 MAJOR / 5
  NOTE**, all folded; 14 of r2's 15 folds were confirmed closed at
  mechanism level, and every new finding landed on the **recovery
  machinery r2 itself added** — which is the honest shape of a fix that
  introduced a new mechanism late. Map:

  | finding | fold |
  |---|---|
  | B1 — `I-c` was an unconditional overwrite licence keyed on a path | `IJ` now records **`(destination, digest)`**; `I-c` fires only if `d` is absent or still hashes to the journaled digest, else the ordinary decline. New `IN11` (concurrent producer in the gap, with a positive control) + `MA49` |
  | M1 — read-then-truncate at `S1` sat in the kill zone | journal is read, written and pruned **only inside `S8` pass 1, under the lock**; entries are removed individually on stamp or when stale; **no bulk truncation**. `IN8(d)` + `MA38` rewritten |
  | M2 — three bucket-membership errors | `H1`/`H2` → bucket 2 (they drive via `cli.main(["worker","run"])` + `shim_writes`); `F1` → bucket 3 with its own row (it asserts the three globs `GR-b` replaces) |
  | M3 — r2's counts were the gate's estimate adopted as measurement | re-measured here with the **predicate written out**: `test_repair.py` 55/44/**43**, `test_worker.py` 45/23/**18**, plus the named residuals and an explicit note that the count is predicate-sensitive (30 / 41 / 43 under three readings) so the obligation is the predicate |
  | N1 — `GR1` described three inconsistent ways | reconciled: removed from §5's exemption list (`MA7` reddens it), §4 body moved to past tense, verify-not-build kept only as provenance |
  | N2 — hotfix dependency asserted, not scheduled | `AD10`: hotfix `1251552` merges first; same payload expressions, and the droppable-looking side is the security fix |
  | N3 — `_mutating_call` does not exist | corrected to **`_primitive`** (`test_lock_invariant.py:218`); noted that a wrong symbol in an import-and-call criterion fails as `ImportError`, not as the check |
  | N4 — 48/48 bijection off by one | `MA36` is now named by `IN8(a)`'s Broken line |
  | N5 — pass 2's reach implied universal | §3.3 carries the roster bound: F-a's `_roster_sha_dishonest` is against **this run's** roster, so a cross-composition foreign proposal does not fire pass 2; `RT7` stands as the matching-roster criterion, and relaxing the honesty check to improve a status line is refused |
