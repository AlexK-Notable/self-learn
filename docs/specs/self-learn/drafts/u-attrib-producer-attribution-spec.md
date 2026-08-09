# Spec — U-attrib: producer attribution by exclusive namespace

Status: **r1 — DRAFT, not yet gated.**
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
| `plugins/self-learn/cli/tests/test_repair.py` | Fixture relocation only — see `CP1`–`CP7` for exactly which of `U-repair`'s criteria may move and which may not. |
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
(install), `RT*` (retirement), `CP*` (compatibility), `OB*`
(observability), `HY*` (hygiene). Its mutations are `MA1`…, its
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

**What the stage is not:** it is not a queue, not durable state, and not
a second source of truth. Its entire lifetime is one run.

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
| `S8` | `_harvest(home, staged, roster, refuse=refuse, foreign=foreign, snap0=snap0)` — validates for real, applies `Install-1`, installs what may be installed, stamps, deletes the rest **from the stage**, sweeps orphans, commits. Still the only locked section, still the only mutation site. |

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
> `record_sha` key.
>
> **Both legs are evaluated at `S8`, on `d`'s state under the lock.** A
> `d` that is **absent from `snap0` but exists now** was created during
> the window and is therefore **not** byte-identical: `I-b` fails and the
> install is declined. Stated explicitly because the `.get()`-shaped
> implementation of that comparison silently inverts it (`MA19`).
>
> Otherwise the install is **declined**: the staged file is dropped, `d`
> is **not written, not stamped, not deleted, not staged for commit and
> not counted in `proposed`/`valid_landed`/`touched`**. A decline is
> logged once and recorded in `result.not_installed` (§3.8).
>
> **Progress accounting for a decline is `Rule-F`'s, unchanged.** If the
> declined `d` satisfies `Rule-F` (F-a ∧ F-b on `d`'s current bytes),
> it is recorded in `result.foreign_left` and logged with `U-repair`'s
> verbatim Rule-F line — the queue advanced, and `status` counts it
> exactly as `U-repair`'s `D7` requires.

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

**What this rule deliberately does not do:** it does not delete, ever.
Every declined path is left exactly as found. The only deletions this
unit performs are of *staged* files, in the cache, that the model wrote
this run.

**The residual it creates, declared here and pinned by `IN5`:** a
destination that is permanently an unstamped draft (a human abandoned a
proposal mid-session) is declined every window, so its record is
re-analyzed every window and never lands. It is visible — one log line
and one counter per run — and a human resolves it by validating or
deleting the draft. Accepted; the enumeration-side fix (skip records
whose destination is a foreign draft) is refused in §7.1 because it
changes queue semantics, which is a different unit's blast radius.

### 3.5 What survives from `U-repair`, and what legitimately changes (NORMATIVE)

This section is the complete divergence list. **A `U-repair` criterion
not named here must survive with its assertion, its mechanism and its
fixture intact.**

**Survive byte-for-byte — assertion, mechanism and fixture:**
`U-repair` `A1`–`A5` (the elicitation contract and `Table-E`), `E1`–`E8`
(headroom, backoff, constants), `F1`–`F4`, `F6` (hygiene; `F5`'s shim is
extended, not changed), `H1`–`H5` (Obs-1's lines, codes and fields),
`G1`–`G8` (the four fabrication legs, the Set-J pin, the `V`-rule, the
sentinel re-assert), `D3` (secret scan first), `D7` (a foreign file
counts as progress), `D9` (a hook proposal is never foreign, and is
stamped so `script` is regenerated).

**Survive in assertion; fixture relocates to the stage** (the shim writes
the model's output into `stage_dir()` instead of into
`<bucket>/proposals/` — nothing else changes):
`U-repair` `B1`–`B13`, `D2`, `D4`, `D5`, `D6(i)`, `D8(i)`.

**Legitimately altered, each with its replacement criterion here:**

| `U-repair` id | what changes | replaced/extended by |
|---|---|---|
| `D1` | assertion **survives verbatim** (the foreign validated proposal exists, bytes unchanged, absent from `proposed`/`invalid_deleted`/`touched`, named in `foreign_left`, Rule-F line logged); the **mechanism** becomes `Install-1`'s decline rather than a Rule-F skip inside the model-output loop, and the fixture no longer needs `Construction-1`'s in-window trick to be *seen* | `IN2`, `RT1` |
| `D6(ii)`, `D6(iii)` | **retired as partition rules.** `Φ` leaves `S5`'s partition entirely: a foreign file is a ledger file and is never in `staged1`, so it can never reach `V`. The **guarantee** they protect — a foreign proposal edited during the repair window is never deleted — is preserved by the namespace and must be asserted directly | `RT2` |
| `D8(ii)` (`E-5`) | **retired.** No staged file can be an attended edit, so "unstamped" no longer discriminates eligibility. The insight is re-sited into `Install-1` (`I-b`) | `RT4`, `IN3` |
| `D8(iii)` | **retired and INVERTED.** This is the flagship retirement: the pinned residual becomes a pinned *impossibility*. The test must now assert that a never-validated attended proposal for a batch record appears in **no** repair prompt and is **not** overwritten | `RT3` |
| `D8(i)` (`E-4`) | survives, **role narrowed**: it is no longer a provenance filter (everything staged is the model's) but a litter filter — a staged `lrn-<id>.yaml` for a non-batch id has no destination and is refused | `RT5`, `ST-e` |
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

**New `RunResult` fields** — additive only; no existing field changes
type or meaning: `staged_written: int`, `not_installed: list[str]`
(destination names, never installed), `foreign_seen: int` (the size of
`S7`'s `foreign` set).

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

### GR — the grant

**GR1 — the settings file enforces, rather than declares.** Assert
`json.loads(write_settings_file(home))["permissions"]["defaultMode"] ==
"default"`, and the same for `write_repair_settings_file`.
*Broken:* `MA7`. This is the criterion that fails on today's shipped
code, and `Z1` is why it is a criterion rather than a preference.

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
unchanged for files that ARE the model's.** Three legs on staged files:
a fabricated RECORD quote is refused and deleted; a laundered
`gates.outcome` is refused and deleted; a file still refused at `S8` is
deleted and its record stays pending.
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

### OB — the observable surface

**OB1 — the new lines exist with their counts.** Drive a run producing
two staged files, one decline of each kind, and one changed ledger file;
assert each §3.8 line appears with correct counts.
*Broken:* `MA29` (emit the stage line with no count).

**OB2 — the new fields are populated.** Assert `staged_written`,
`not_installed` and `foreign_seen` carry the right values on the same
run.
*Broken:* `MA30` (never assign `foreign_seen`, leaving it 0).

**OB3 — existing fields keep their meaning.** Assert `proposed`,
`valid_landed`, `touched`, `invalid_deleted`, `orphans_swept`,
`foreign_left`, `buckets` and the three repair counters all mean exactly
what Obs-1 says.
*Broken:* `MA31` (count declines in `invalid_deleted`) — which reads, to
every downstream consumer, as "the worker deleted a proposal", the one
thing it must never be able to say falsely.

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

**Every criterion has at least one mutation above except `CP1`, `CP6`,
`HY1` and `HY3` — deliberately, and stated so the omission is not read as
the same gap.** `CP6` and `HY1` are reddened by `U-repair`'s own `M21`,
`M36` and `M52`, which this unit must keep red; `CP1` and `HY3` are
process gates over the whole tree, and the instrument that checks them is
running them.

**`U-repair`'s mutation plan must still redden its own criteria**, with
the four exceptions §3.5 names (`M46`, `M49a`, `M53` and the `D8(ii)`
leg of `M49` lose their targets when `Φ`'s partition and `E-5` retire).
A gate should verify those four are *retired with their criteria*, not
silently surviving as green no-ops.

**Reviewers are invited to invent mutations not listed here.** Three
shapes this unit is most likely to be wrong in, named as leads rather
than findings:

- **(a)** the merge branch — `record_shas` are resolved in memory at
  `S4` (`U-repair` §3.3) and the file is written by `_dump_yaml`; an
  install path that copies staged **bytes** for merges instead of dumping
  the prepared document would land a proposal without its `record_shas`;
- **(b)** the install destination and the **stamp** destination are
  resolved by two different functions and must agree.
  `stamp_proposal(home, record_id)` (`ledger_ops.py:1680-1698`) finds the
  record itself (`find_record_path`) and derives the proposal path from
  *that* bucket; `ST-e` derives it from the **batch entry**. They agree
  today, and a resolver that ever disagrees would copy bytes to one path
  and stamp another — leaving an unstamped install and a
  `no proposal sibling for <id>` refusal that reads like a model defect;
- **(c)** the repair round's second write to the **same** staged path —
  `staged` at `S7` is the stage's contents, not a diff, so a repair that
  *deletes* a staged file rather than editing it must be handled, and
  the `A`-set's Set-J comparison must not raise on a missing file.

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
  copy, exactly as today.** Stamping is not moved into the stage: a
  staged file must never carry a `record_sha` this unit wrote, or `IN3`'s
  own signal would be manufactured by the worker.

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
and one counter per run — and `IN3`/`IN6(b)` pin both. To be recorded as
`S-33`.

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

1. **`worker.py:804-812`'s containment docstring, and `U-repair`'s `D5`,
   both overstate what is enforced on this host.** The settings file's
   `permissions.allow` list is **void** without an explicit
   `defaultMode`, because the user's global settings set
   `bypassPermissions` (`Z1`). "The CLI itself refuses writes outside the
   assigned set" (`U-repair` §3.7) is, today, false in production. This
   unit's `Grant-1` makes it true; `GR1` is the criterion that fails on
   the shipped code.
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
