# Spec — U-table: the decision table as a pure module, and the recompute-and-refuse check

Status: **r3 — GATED SOUND, CLEARED FOR BUILD.** Blind spec gate (r1,
2026-08-06) returned **SOUND — buildable after folds: 1 BLOCKER, 6 FOLD,
6 NOTE**; all were folded at r2 and the **delta round returned SOUND,
cleared for build**, with two figure substitutions landed at r3. §10
records each. The gate independently reproduced this spec's central
enumeration to the digit. Unit `U-table` of the r2 routing campaign
(`forward/r2-routing-campaign.md` §2, Wave 2). Dependency `U-schema` is
**MERGED** (`176eee6`); this spec is written against the code that shipped
and its post-merge fixes (FW-57/62/63/66/67, `05f8a5b`, `81cb694`,
`358c9c1`), not against U-schema's draft. Implementation reference:
`misc/routing-procedure-r2.md` §1.4 item 3, §1.5, §1.6 — **which this spec
corrects in five places, three of them measured; see §8.**

**Files this unit may touch:**

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/gates.py` | **NEW.** The pure table. |
| `plugins/self-learn/cli/src/self_learn/ledger_ops.py` | `_validate_gates` gains `scope`; new `_validate_derivation`; `validate_proposal` threads it; `write_proposal` + `proposal_info` supply it. |
| `plugins/self-learn/cli/src/self_learn/selfcheck.py` | **One call site, one keyword argument** (`scope=record.scope` at `selfcheck.py:163`). Nothing else. See §3.5 and §6-BD8. |
| `plugins/self-learn/cli/tests/test_decision_table.py` | **NEW.** This unit's tests. |
| `plugins/self-learn/cli/tests/test_decision_trace.py` | Four fixtures reconciled (§3.7). |
| `plugins/self-learn/cli/tests/test_proposal_validate.py` | One fixture reconciled (§3.7). |

Anything else — `worker.py`, `analyst.py`, `verbs.py`, `miner.py`,
`telemetry.py`, `compilers.py`, the UI, `routing-doctrine.md` — is **out of
scope and must be reported, not edited.** `verbs.py` is live in
`U-demand-user` this wave; `worker.py` and `analyst.py` are `U-composer`'s,
and `U-composer` is being spec'd concurrently. §8 names what is handed to
each.

**`ledger_ops.py` is contended with `U-composer`, and the wave plan
resolves it by ORDER, not by disjointness** *(N6)*. `U-composer` must
re-edit `_validate_gates` for the **S-26** optional→mandatory flip, i.e.
the same function this unit changes. The gate-confirmed sequencing is:

1. **U-table merges first** — it creates `gates.py` and both `ledger_ops`
   seams (the `scope=` parameter and `_validate_derivation`).
2. **U-demand-user runs concurrently** with U-table (`verbs.py` + `ui/*`,
   disjoint from this file set).
3. **U-composer rebases onto merged U-table**, then makes the S-26 flip,
   takes §8-H1 in full, and resolves its own assumption 7 via R-SCOPE.
4. Checkpoint A.

A builder who finds `_validate_gates` already carrying a mandatory-trace
flip has the order backwards and must stop and report.

**Base commit:** this spec was rebased onto master `07d8c08` before r2
(*N6*). The three intervening commits (`f3f3f76`, `190e26d`, `07d8c08`)
touch `docs/specs/self-learn/14-forward-work-map.md` **only** — verified
with `git diff --name-only 83c1d5d 07d8c08` — so every code citation below
is unaffected, and a merge from this branch cannot revert FW-71…FW-75.

---

## 0. Reading order and precedence

This document has **two normative definitions** — **Table-1** (§3.1, the
decision table) and **Render-1** (§3.3, the outcome → proposal-field
rendering map) — plus one normative behaviour definition, **the acceptance
criteria (§4)**.

**Precedence, on conflict:**

1. The acceptance criteria (§4) and the mutation plan (§5) win over
   everything else. They are the contract; the rest is rationale.
2. Table-1 and Render-1 win over all prose and over any example.
3. Where this spec and `misc/routing-procedure-r2.md` disagree, **this spec
   wins and §8 says why** — every divergence there is either measured or
   forced by a ruling that post-dates r2.

**Each of Table-1 and Render-1 appears exactly once.** Nothing downstream —
not the criteria, not the mutation plan, not the builder prompt — may
re-state a row. Refer to rows by their id (`L4`, `R-DEMAND`). U-schema's
own §0 forbade re-enumeration and then committed it twice (FOLD-10,
FW-67); the rule is inherited here for the same reason.

**Read §2 before anything else.** U-schema's shipped seam is what makes
this unit small, and three of its five handoffs are load-bearing.

---

## 1. The defect

**The analyst grades its own homework, and the CLI stamps the grade.**

U-schema shipped the trace: nine gate keys, closed enums, quote
containment against the record. It deliberately stopped one step short.
`gates.outcome` — the analyst's own statement of *what the table says* — is
**enum-checked only** (`ledger_ops.py:1244-1249`): any of the nine values is
accepted regardless of the answers above it. And the proposal's
`destination`, `variant`, `rules_paths` and `recommendation` are never
compared with that outcome at all.

So today all three of these validate:

- a trace whose every gate says *no* and whose `outcome:` says `HOOK`;
- an `outcome: DEMAND` trace on a proposal whose `destination` is
  `claude-md` — the exact monoculture shape the audit measured;
- an `outcome: PATHED` trace on a proposal carrying no `rules_paths` at
  all — a pathed verdict with nothing pathed about it, which is FW-40's
  defect ("a rules variant that validated globs it never wrote") relocated
  into the trace.

The trace was added so a reader could audit the *reasoning* rather than
only agree with the answer. A trace whose conclusion does not follow from
its own premises is worse than no trace: it is an audit trail that
launders the verdict. **This unit makes the conclusion mechanical.**

Two things follow that are worth stating separately, because they are the
reason this is a unit and not a nicety:

- **Every judgment cell in r2 is enum-shaped and quote-gated *except* the
  final one.** The residue r2 accepts is *interpretation of a real quote*
  (§1.4's closing paragraph). Recomputation removes the one place where a
  model could keep the residue and discard the reasoning.
- **`_load_class` is the anti-monoculture instrument.** r2 §1.6 requires a
  `HOOK` proposal to name, in `alternates`, the destination it would
  otherwise have had. That obligation is unenforceable without the table.

---

## 2. What `U-schema` shipped, and the obligations it handed here

Verified against `ledger_ops.py` on this tree, not against U-schema's draft.

| Shipped | Where |
|---|---|
| `TRACE_GATE_KEYS` — nine required keys, closed | `ledger_ops.py:92` |
| `TRACE_FLAGS` (Set-F, eight values) | `:98-107` |
| `TRACE_RECOMMENDATIONS` (Set-R) | `:110` |
| `TRACE_OUTCOMES` (Set-O, nine values) | `:116-126` |
| `TRACE_FS_VERDICTS` (Set-V) | `:129` |
| `_validate_gates(data, *, record_text=None)` — shape, enums, required-ness, quote containment | `:819` |
| `validate_proposal(data, *, record_text=None)` | `:1252`, calling `_validate_gates` at `:1309` |
| `write_proposal` — resolves the record, supplies `record_text` | `:1399-1419` |
| `proposal_info` — supplies `record_text` from the in-memory record | `:1787-1822`, call at `:1818` |

**The five obligations, and this unit's disposition of each:**

| U-schema | Obligation | Here |
|---|---|---|
| §8-O1 | `gates.py` imports `TRACE_OUTCOMES`; does not redefine `CLS` | **Built** — §3.1, A1. The import direction is measured (§3.6). |
| §8-O3 | enforce the scope-conditional `t4` presence rule a scope-free validator cannot (U-schema's own §6-D5) | **Built** — §3.2. Not tidiness: it is what makes the table total (§9-X1). |
| §3.7 item 2 | outcome recomputation | **Built** — §3.3, C-criteria. |
| §3.7 item 3 | the r2 §1.6 rendering map | **Built** — Render-1. |
| §3.7 item 7 | `t1` ⇔ `_validate_hook_extension` consistency (r2 §1.4 item 5) | **Built, in corrected form** — r2 states it as an iff and it is not one (§8-C3). Render-1's `R-HOOK` row carries the correct rule. |
| §3.7 item 4 | `e1.sightings` cross-check against the record | **NOT built** — §7.1, with the reason. |

**S1–S6, U-schema's seam, all still hold and this unit does not weaken
any.** The two that constrain the design hardest:

- **S4 — `validate_proposal` performs no filesystem I/O.** It is on the
  eligibility hot path (`proposal_info` → `is_unanalyzed` → `list` /
  `status` / the worker's queue computation). Table-1 is pure and reads no
  file; the one new ingredient (`scope`) is an attribute of a record the
  call sites already hold in memory (§3.5).
- **S6 — `_validate_gates` raises `ProposalError` and nothing else, on
  every input.** A `TypeError` escaping `validate_proposal` tracebacks
  `self-learn list` for **every** record in the bucket, not just the
  malformed one — measured live twice already (FW-63, FW-57). Table-1 is
  called from inside that contract, so **Table-1 must never raise on a
  trace `_validate_gates` accepted.** §9-X1 is the measurement that this
  is not free: r2's published table raises on 3,456 such traces.

---

## 3. The change

### 3.1 Table-1 — the decision table (NORMATIVE)

New module `plugins/self-learn/cli/src/self_learn/gates.py`. Pure: no
filesystem, no network, no clock, no mutation of its argument. Its only
import is `TRACE_OUTCOMES` from `ledger_ops` (§8-O1, §3.6).

`trace` is the proposal's `gates:` mapping, **already validated by
`_validate_gates`**. `scope` is the record's own `scope` string — the same
value `verbs.py` passes to `_resolve_target` (`record.scope`, e.g.
`verbs.py:1630`, `:2117`, `:2819`), one of `user`, `project`,
`skill:<name>` (`records.py:806-811`).

**Rows are evaluated top-down; the first match wins.** Row ids are
normative — the mutation plan and the criteria refer to them.

| id | condition | result |
|---|---|---|
| **G1** | `g0.reject.answer == "yes"` | `REJECT` |
| **G2** | `g0.defer.answer == "yes"` | `DEFER` |
| **G3** | `g0.canon.answer == "yes"` | `GRADUATE` |
| **H** | `hook_ok(trace)` | `HOOK` |
| — | otherwise | `load_class(trace, scope)` |

`hook_ok(trace)` is true iff **all three** of `t1.field_shaped.answer`,
`t1.separable.answer`, `t1.cost_bearing.answer` equal `"yes"`.
`t1.attempted` is **not** read (§6-BD2).

`load_class(trace, scope)`, same discipline:

| id | condition | result |
|---|---|---|
| **L1** | `t2.answer == "yes"` | `PATHED` |
| **L2** | `t3_route_taken(trace, scope)` — enter the t3a block | ↓ |
| **L2a** | … and `t3a.depth_behind_rule.answer == "yes"` | `DEMAND` |
| **L2b** | … and `t3a.fs.verdict ∈ {SILENT, COSTLY}` or `e1_promote(trace)` | `SKILL` |
| **L2c** | … otherwise | `DEMAND` |
| **L3** | `tn.answer == "yes"` | `NEW_SKILL` |
| **L4** | `t4.depth_behind_rule.answer == "yes"` | `DEMAND` |
| **L5** | `t4.conduct_mode.answer == "yes"` | `ALWAYS` |
| **L6** | `t4.fs.verdict ∈ {SILENT, COSTLY}` or `e1_promote(trace)` | `ALWAYS` |
| — | otherwise | `DEMAND` |

`t3_route_taken(trace, scope)` is true iff `t3.answer == "yes"` **and**
`scope == "skill:" + t3.owner`.

`e1_promote(trace)` is true iff `e1.sightings >= 2` **and**
`e1.post_demand_recurrence` is true.

**Three notes that are part of the definition, not commentary:**

1. **`load_class` is called even when `H` fires.** `R-HOOK` (Render-1)
   needs it, so it must be total on every trace that reaches `H`. §3.2 is
   what makes that so.
2. **`L2` is a scope-dependent branch and the only one.** Everything else
   in Table-1 reads the trace alone. That is why `scope` is the single new
   ingredient (§3.5) and why a scope-free caller gets no derivation at all
   rather than a partial one (§6-BD4).
3. **`L3`'s removal reddens by *exception*, not by a different answer** —
   measured (§9-X4). Deleting `L3` falls through to `t4`, which is `null`
   whenever `tn.answer == "yes"` (`ledger_ops.py:1167-1172`). A mutation
   sweep that only diffs return values will score `L3` as "survived". It
   did not; it crashed.

### 3.2 The scope-conditional `t4` presence rule (U-schema §8-O3)

`_validate_gates` gains a keyword-only `scope: str | None = None`.

The existing t4-presence block (`ledger_ops.py:1163-1181`) leaves one
window open — **`t3.answer == "yes"` AND `t2.answer == "no"` AND
`tn.answer != "yes"`** — because the scope-free validator cannot know
whether the t3 route is taken. **With `scope` in hand the window closes:**

- `t3_route_taken(gates, scope)` → `t4` **must** be `null` (Table-1 never
  reads it; r2 §1.2's "else null").
- otherwise → `t4` **must** be non-null (Table-1 falls through to `L4`).

**Both bullets apply INSIDE that window only. Outside it the shipped block
at `ledger_ops.py:1163-1181` is unchanged and still governs.** *(r1 gate
F4.)* This clause is load-bearing, not pedantry: read globally, bullet 2
says "`t4` must be non-null whenever the t3 route is not taken", which
contradicts the shipped rule that `t4` is `null` when `t2` or `tn`
answered yes (`:1167-1172`) and **makes `NEW_SKILL` unreachable** — every
`tn: yes` trace carries `t4: null` and would be refused. Measured
(§9-X1d): window reading → 608,256 kept / 175,104 refused, no outcome
unreachable; global misreading → 543,744 kept / 239,616 refused,
`NEW_SKILL` **unreachable**. And note which criterion catches it: **only
A4.** A3's two floors still pass under the misreading (543,744 ≥ 500,000
and 239,616 > 100,000), which is exactly why A4 asserts set *equality*.

Both bullets are **additions**: each refuses a trace the scope-free rule
accepted; neither accepts one it refused. That direction is mandatory, not
stylistic — see §6-BD3 for the two-path contradiction that the other
direction produces, and §7.2 for the residual it forces this unit to keep.

**This is a defect fix, not tidiness.** Enumerated exhaustively (§9-X1):
of the 97,920 (trace, scope) pairs the shipped validator accepts, **3,456
make r2's published table raise `TypeError: 'NoneType' object is not
subscriptable`** — a non-`ProposalError` escaping `validate_proposal`,
i.e. the exact S6 breach that tracebacks `self-learn list` for every
record in the bucket. With this rule, those 3,456 are refused with a
`ProposalError` naming `gates.t4` and the scope, and the table never sees
them.

### 3.3 Render-1 — outcome → proposal fields (NORMATIVE)

Checked by `_validate_derivation` after the outcome is recomputed and
agrees. `recommendation` absent is read as `"route"` (r2 §1.2's stated
default); `flags` absent is read as `[]`.

Let `rendered` = `load_class(trace, scope)` when the outcome is one of
`REJECT` / `DEFER` / `GRADUATE` (r2 §1.6's "best routable fallback"), and
the outcome itself otherwise.

| id | rendered | `destination` | variant shape | `recommendation` | extra |
|---|---|---|---|---|---|
| **R-HOOK** | `HOOK` | `hook` | `variant` absent | `route` | `alternates` must contain the `destination` of `load_class(trace, scope)` |
| **R-ALWAYS** | `ALWAYS` | `claude-md` | **not** (`variant == "rules"` ∧ `rules_paths` non-empty) | `route` | — |
| **R-PATHED** | `PATHED` | `claude-md` | `variant == "rules"` ∧ `rules_paths` non-empty | `route` (see R-SCOPE) | — |
| **R-SKILL** | `SKILL` | `skill-md` | `variant` absent | `route` | — |
| **R-DEMAND** | `DEMAND` | `reference` | `variant` absent | `route` (see R-SCOPE) | — |
| **R-NEW** | `NEW_SKILL` | `new-skill` | `variant` absent | `route` | `new_skill` == `gates.tn.proposed_name` |
| **R-FALL** | outcome ∈ {`REJECT`,`DEFER`,`GRADUATE`} | the `destination` of `rendered` | free | `reject` / `defer` / `graduate` respectively | `GRADUATE` additionally requires `already_canon: true` |

**R-SCOPE — the honest-degradation row.** When the rendered outcome has
**no routable surface at the record's scope** (§3.4), then instead of
`route`:

- `recommendation` must be `defer`, **and**
- `flags` must contain `no-cheap-surface`.

**R-SCOPE modifies the six `route` rows ONLY — R-HOOK, R-ALWAYS, R-PATHED,
R-SKILL, R-DEMAND, R-NEW. It never modifies R-FALL.** *(r1 gate F3.)*
Without that pin both readings pass §4 and they contradict each other:
for outcome `REJECT` at user scope whose load class is `DEMAND`, R-FALL
fixes `recommendation: reject` while an unpinned R-SCOPE would demand
`defer`. **R-FALL wins, always** — and the reason is not precedence, it is
meaning: `REJECT`/`DEFER`/`GRADUATE` are not routings at all, so "the
cheap surface does not exist at this scope" is not a fact about them. Their
`destination` is a schema-required placeholder (§6-BD7's note), and
degrading a rejection to "defer because the shelf is missing" would say
something false about a lesson nobody is shelving. **Criterion D7a is
what pins it.**

The destination stays the outcome's honest target. **It is never silently
upgraded** — r2 §1.6 states this for `DEMAND` at user scope ("NEVER
silently upgrade to ALWAYS — that is the monoculture rebuilt") and the
rule generalises: an unroutable honest verdict that quietly becomes a
routable dishonest one is the defect this campaign exists to remove.

**Two properties of Render-1 worth naming because a reviewer will test
them:**

- **`recommendation` is a pure function of (outcome, scope).** The analyst
  has no free choice left in that field — and loses nothing, because the
  channel for "I want this deferred" is `g0.defer.answer: yes`, which
  produces `DEFER` and therefore `recommendation: defer` by R-FALL. §6-BD6
  records the S-22 funnel analysis in full.
- **R-ALWAYS and R-PATHED are discriminated by the *load semantics*, not
  by a label.** A `variant: rules` file with no `rules_paths` is an
  always-loaded file (r2 §1.6's own parenthesis: "an unpathed rules file
  is a legal, always-loaded surface — same cost as CLAUDE.md"), so
  R-ALWAYS admits it, and admits `variant: local` too. §6-BD7 gives the
  reason this is not a loophole.

### 3.4 Routability by scope — the definition `routable()` implements

**This table is normative for the `routable(outcome, scope)` helper**
(the one M16 mutates), so it must cover **all six** of Render-1's route
rows, not only the two holes *(r1 gate N5)*. Rows verified by calling the
shipped resolvers directly (§9-X3) and by reading each branch:

| rendering | `skill:<name>` | `project` | `user` | governing code |
|---|---|---|---|---|
| `hook` (R-HOOK) | routable | routable | routable | `verbs.py::_hooks_dir_for` `:1088-1116` — branches on scope but **resolves for all three** (skill → the owning plugin's `hooks/`; project/user → `hooks/self-learn/`) |
| `claude-md`, unpathed (R-ALWAYS) | routable | routable | routable | `verbs.py:947-991` — one branch per scope (`user` `:964`, `project` `:973`, skill-root fall-through `:980-991`) |
| `claude-md` + `variant: rules` (R-PATHED) | **NOT routable** | routable | routable | `verbs.py::_resolve_rules_target` `:811-816` — P-A13 |
| `skill-md` (R-SKILL) | routable | refused, **unreachable by Table-1** | refused, **unreachable by Table-1** | `verbs.py:930-945` |
| `reference` (R-DEMAND) | routable | routable | **NOT routable** | `verbs.py:1045-1050` |
| `new-skill` (R-NEW) | routable | routable | routable | `verbs.py:993-1034` — **no scope test at all**; it gates on a registered skills root and a `marketplace.json`, never on scope |

**So `routable()` returns `False` in exactly two cells**: `DEMAND` at
`user`, and `PATHED` at `skill:*`. Every other cell is `True` — including
the two `skill-md` cells, which are `True` *vacuously* because Table-1
cannot reach them (see below). Stating the whole map matters because M16
mutates `routable()` to return `True` unconditionally; a partial
definition would leave a reviewer unable to tell an intended `True` from a
missing row.

- **`DEMAND` at user scope** is r2 §1.6's own transition rule. r2 framed it
  as "before B7 lands". **S-23 (2) makes it permanent**: user scope's cheap
  surface is PATHED, explicitly *not* a user-level reference file, and
  FW-42 records that the `verbs.py` refusal **stays**. So the rule is not a
  transition any more; it is the steady state. R-SCOPE carries it.
- **`PATHED` at skill scope** is **not named anywhere in r2.** Table-1's
  `L1` is scope-free, so a skill-scope record with `t2.answer: yes` derives
  `PATHED`, and `_resolve_rules_target` refuses it: *"claude-md:rules:<t>
  is not available for scope 'skill:s' yet — plugin-shipped rules is an
  unresolved documentation gap (P-A13)"*. Structurally identical hole,
  opposite corner of the table. R-SCOPE covers both with one rule rather
  than two special cases. **The underlying question — close P-A13, or
  steer the doctrine away from T2 at skill scope — was routed to the r1
  gate and is now RULED: degrade, and never the doctrine option (§6-BD10,
  which also carries the distinct-Checkpoint-C-measurement condition).**

**`R-SKILL` needs no scope rule**: `SKILL` is reachable only through `L2`,
which requires `scope == "skill:" + t3.owner`, so the table cannot emit it
where `verbs.py:930-935` would refuse it. That is a property of Table-1,
not a coincidence, and A6 pins it.

### 3.5 Where the check runs — the scoped-ingredient census

`validate_proposal` gains a second keyword-only parameter,
`scope: str | None = None`. **The derivation runs iff `scope` is
supplied** — exactly the shape U-schema gave containment, for the same
reason (S2: no call site outside this unit's file list changes).

| call site | today | after |
|---|---|---|
| `ledger_ops.write_proposal` (`:1399`) | `record_text=` | `record_text=` **+ `scope=`** — reuses the one `Record.from_path` already behind the `gates is not None` guard |
| `ledger_ops.proposal_info` (`:1818`) | `record_text=` | `record_text=` **+ `scope=entry.record.scope`** — the record is already in memory; an attribute read, no I/O (S4) |
| `selfcheck.proposal_validate` (`:163`) | `record_text=` (FW-62) | **+ `scope=record.scope`** — `record` is parsed on the line above (`:162`) |
| `worker.py:927` (`_land_outputs`) | positional | **unchanged — handed to `U-composer`** (§8-H1) |
| `worker.py:1282` (`fast_status`) | positional | unchanged |
| `analyst.py:244` (`analyze`) | positional | unchanged |
| `verbs.py:551`, `:1193`, `:1247` | positional | **unchanged, deliberately** — §6-BD5 |

**Why these three sites are sufficient coverage today, stated so the gate
can attack it rather than guess at it:**

1. `proposal_info` runs on **every pending record on every `list`,
   `status`, and worker queue computation**. No proposal in the queue
   escapes it. A mismatch there yields `proposal_fresh: False` →
   `is_unanalyzed: True` → re-analysis, exactly as a fabricated quote does
   today.
2. `write_proposal` is the only in-CLI producer (`import_backlog.py:267`;
   the worker's proposals are written by the model itself and landed at
   `worker.py:927`).
3. `selfcheck.proposal_validate` is the human's hand-edit path —
   `SKILL.md:52` documents it as REQUIRED after any direct edit outside
   CLI verbs. **Leaving it unscoped would rebuild FW-62's exact shape**: a
   validator whose machine path is strict and whose human path is lenient
   has its permissions inverted. That is the whole reason `selfcheck.py`
   is on this unit's file list for one keyword argument.

**`stamp_proposal` was considered as a fourth site and is REJECTED.** It
has the record and sits directly after `worker.py:927`, so it would cover
the worker producer path with no `worker.py` edit — but U-schema's **S5**
is an explicit, tested invariant (`A9`) that the trace validator never runs
from `stamp_proposal`, because a `ProposalError` raised there escapes
`selfcheck.proposal_validate`'s lock block and is caught by
`cli._cmd_proposal` as **rc=64 `EXIT_USAGE`** — a schema failure reported
as a usage error, breaking `proposal validate`'s pinned exit trio
(`EXIT_VALID=0` / `EXIT_SCHEMA_INVALID=1` / `EXIT_SCAN_HIT=2`). Convenience
does not outrank a sibling unit's tested invariant.

### 3.6 The import direction — measured, not reasoned

`ledger_ops` must call into `gates`; `gates` must import `TRACE_OUTCOMES`
from `ledger_ops` (§8-O1). That is a cycle, and it is **not** the benign
kind.

**Measured (§9-X2), both import orders, fresh interpreter:** a
module-level `from .gates import …` in `ledger_ops.py` breaks **both**
orders — not a warning, not order-dependent, so `self-learn` would not
start at all. **The two orders fail with different messages, and r1 quoted
only one of them** *(r1 gate N4)*:

| first import | message |
|---|---|
| `import self_learn.ledger_ops` | `ImportError: cannot import name 'TRACE_OUTCOMES' from partially initialized module 'self_learn.ledger_ops' (most likely due to a circular import)` |
| `import self_learn.gates` | `ImportError: cannot import name 'expected_outcome' from partially initialized module 'self_learn.gates' (most likely due to a circular import)` |

Which name and which module appear depends on which side of the cycle the
interpreter entered from. **A2 therefore asserts `returncode`, not message
text** — it is unaffected by this, and a criterion that matched on the
message would pass in one order and fail in the other.

**Pinned:** `ledger_ops` imports from `gates` **inside the function that
needs it** (`_validate_derivation`, and `_validate_gates` for
`t3_route_taken`). This is the file's own established pattern, not an
invention: `_validate_hook_extension` does `from .hook_compiler import
GUARDABLE_TOOLS` at `ledger_ops.py:487`, and `_generate_hook_script` does
the same at `:1453`. It also preserves U-schema's **S3** to the letter
(no new module-level import in `ledger_ops.py`), which is what keeps a
cycle with `worker`/`analyst`/`selfcheck`/`miner` impossible.

`gates.py` imports `TRACE_OUTCOMES` at module level. Measured to work in
both orders under the deferred arrangement.

### 3.7 What this breaks in the existing suite, and the only correct fix

**Measured, not predicted** (§9-X5): a working prototype of this exact
design, run against the real CLI suite, reddens **5 of 1379 tests**. Every
one is a *fixture* that pairs a trace with a proposal the trace does not
render to — written before the table existed, when nothing could notice.

| test | why it reddens | the fix |
|---|---|---|
| `test_decision_trace.py::test_quote_from_frontmatter_accepted` | fixture sets `t4.fs.verdict: COSTLY` → `L6` → `ALWAYS`, but `_base_gates()["outcome"]` is `DEMAND` | set `outcome: "ALWAYS"`, `destination="claude-md"` |
| `…::test_quote_from_frontmatter_accepted_via_proposal_info` | same | same |
| `…::test_write_proposal_supplies_record_text` | `_base_gates()` derives `DEMAND`; `proposal_dict()` destination is `skill-md` (`tests/support.py:236`) | `destination="reference"` |
| `…::test_fabricated_quote_makes_proposal_unfresh` | same | `destination="reference"` |
| `test_proposal_validate.py::test_true_record_quote_accepted_the_positive_control` | same, **at user scope** (`seed_record` uses `scope="user"`, `test_proposal_validate.py:33-38`) → R-SCOPE applies | `destination="reference"`, `recommendation="defer"`, `flags=["no-cheap-surface"]` |

With those five fixtures corrected, the two modules return **93 passed,
rc=0 captured unpiped** (§9-X5).

**The instruction to the builder is exact: fix the fixtures, never the
check.** Two of the five reddened because the recompute found a fixture
whose stated outcome contradicted its own answers — that is the feature
working on its first contact with real data. The fifth is the more
interesting one: it is the FW-62 positive control, at user scope, and its
corrected shape *is* R-SCOPE. If a builder finds themselves adding a
`scope is None` escape, or special-casing tests, or relaxing R-DEMAND,
they have inverted the unit.

---

## 4. Acceptance criteria

**These criteria are the contract.** Each states what its check reports
when the target is **absent or broken** — because "a check that cannot
fail" is this project's signature defect and every criterion below is
written to be falsifiable.

Tests live in `tests/test_decision_table.py` unless a criterion says
otherwise. Constants are **imported**, never re-listed: `TRACE_OUTCOMES`,
`TRACE_FLAGS`, `TRACE_FS_VERDICTS`, `PROPOSAL_DESTINATIONS` come from
`ledger_ops`; a test that hardcodes a copy fails A1's intent even if it
passes.

### A. The module

**A1 — one definition of Set-O.** `gates.py` contains no literal outcome
tuple/list/set; it imports `TRACE_OUTCOMES` from `ledger_ops`. The test
asserts every value Table-1 can return is in `ledger_ops.TRACE_OUTCOMES`,
**importing that name from `ledger_ops`, not through `gates`**.
*Broken:* if `gates.py` re-declares `CLS`, the assertion still passes —
which is why the test additionally asserts, by source read of
`gates.py`, that the file contains no second nine-member literal. *Absent
target:* if `gates.py` does not exist, collection fails at import — a
loud, unmistakable failure, not a skip.

**A2 — the import cycle is closed, proven in a fresh interpreter.** Two
`subprocess` runs of the project interpreter: `python -c "import
self_learn.ledger_ops"` and `python -c "import self_learn.gates"`, each
asserted `returncode == 0` with the rc captured **directly from
`CompletedProcess.returncode`, never through a pipe**.
*Broken:* a module-level import of `gates` in `ledger_ops` makes **both**
runs exit non-zero with `ImportError: … partially initialized module …`
(measured, §9-X2). *Why a subprocess:* an in-process `importlib.reload`
would find both modules already in `sys.modules` and pass vacuously — the
positive control is that the interpreter is fresh.

**A3 — totality.** Exhaustively enumerate the trace space of §9 (the
enumeration is the test's own code, not a fixture file, and it varies
**every** dimension §9 lists — `g0` included), keep only the (trace,
scope) pairs `_validate_gates` accepts **at the scope under test**, and
assert for every survivor that `expected_outcome` returns a member of
`TRACE_OUTCOMES` and raises nothing.
*Broken:* r2's published table raises `TypeError` on 3,456 pairs; the test
reports the count and one witness trace.
**Two vacuity guards, both mandatory** — without them a builder whose
enumeration or legality filter is broken gets a green run over an empty
set, which is the "selftest that printed zero rows" defect this campaign
keeps finding:
(i) the surviving pair count is **≥ 500,000** (measured here: 608,256);
(ii) the count **refused by §3.2's scoped rule** is **> 100,000**
(measured here: 175,104) — this one proves the filter *discriminates*
rather than accepting everything.
If the builder's enumeration legitimately differs from §9's, the test
docstring must say how and the two floors must be restated against the
new numbers — never dropped.

**A3b — the same sweep must call `load_class` DIRECTLY, with its own
floor.** *(r1 gate F5.)* Sweeping `expected_outcome` alone understates the
crash surface by 8.5×, because `expected_outcome` returns early on `G1`,
`G2`, `G3` and `H` and never reaches the table's fragile part. Measured
without §3.2's rule (§9-X1e): `expected_outcome` raises on **3,264** pairs,
`load_class` on **27,648**. That gap is not academic — **§3.1 note 1 and
R-FALL/R-HOOK call `load_class` even when `H` fires or a `g0` leg
short-circuits**, so the reachable surface in production is `load_class`'s,
not `expected_outcome`'s. §5's own lead (b) predicted exactly this shape;
this criterion is what closes it. Assert: over the A3 enumeration,
`load_class(trace, scope)` raises nothing and returns a member of
`TRACE_OUTCOMES` for every kept pair, with the same two vacuity floors.
*Broken:* a builder who applies §3.2's rule but computes the load class
somewhere it has not yet run — the second failure lead in §5 — reddens
here and nowhere else.

**A4 — onto: every outcome is reachable.** Over the same enumeration,
assert `{expected_outcome(t, s) for every survivor} == set(TRACE_OUTCOMES)`
— set **equality**, not containment, with the symmetric difference in the
assertion message.
*Broken:* a dead or shadowed row makes its outcome unreachable and the
message names the missing member; an outcome the table can emit but Set-O
does not contain shows up on the other side. This is the positive control
against the failure mode a green suite here has never caught: a table row
that can never fire. **A4 is why A3's enumeration must vary `g0`** —
`REJECT`, `DEFER` and `GRADUATE` are unreachable without it (measured:
absent from the `g0`-all-no slice, present in the full sweep).

**A5 — the golden rows, each drawn from its row's DIFFERS set.** One
pinned (trace, scope) → outcome per Table-1 row id (`G1`, `G2`, `G3`, `H`,
`L1`, `L2a`, `L2b`, `L2c`, `L3`, `L4`, `L5`, `L6`), each asserted
individually with the row id in the assertion message, and each pinned
trace one that `_validate_gates` accepts.

**A pinned fixture is only valid if deleting its own row changes what that
fixture produces** — a different outcome, or an exception. *(r1 gate F2.)*
This is not a formality: a naturally-chosen fixture frequently survives
deletion of the row it is meant to pin, because the fall-through returns
the same answer. Measured over the 608,256 kept pairs (§9-X1c), as
*fires / differs / raises / **surviving-fixture fraction***:

| row | fires | differs | raises | a naive fixture survives |
|---|---|---|---|---|
| `L5` | 15,232 | 5,712 | 0 | **62.5%** |
| `L2a` | 816 | 510 | 0 | **37.5%** |
| `L4` | 30,464 | 24,752 | 0 | **18.8%** |
| `L2c` | 306 | 102 | 204 | 0% — but only 33% of detections are by *value* |
| `L3` | 1,904 | 0 | 1,904 | 0% — **every** detection is by exception |
| `G1`,`G2`,`G3`,`H`,`L1`,`L2b`,`L6` | — | — | — | 0% |

`L5` is the worst case and its mechanism is instructive: a natural
`t4.conduct_mode: yes` fixture that also carries `fs.verdict` `SILENT` or
`COSTLY` falls through to `L6` and returns `ALWAYS` **either way**, so the
test passes with `L5` deleted. The fixture must pair `conduct_mode: yes`
with an `fs.verdict` of `LOUD_CHEAP` or `INDETERMINATE` and no `e1`
promotion, so the fall-through would return `DEMAND`.

**The builder must compute the DIFFERS set, not eyeball it** — the A3
enumeration is already in the module, so this is a filter over data the
test already has. *Broken:* a reordered or deleted row changes exactly the
rows that depend on it; §5's M2–M8 and M24a–M24d name which. *Recorded so
neither builder nor gate misreads its own sweep:* the `L3` and `L2c`
mutations redden **by exception**, not by a different value (§3.1 note 3,
measured §9-X1c) — a sweep that only diffs return values scores `L3` as
survived when it in fact crashed on every fixture that reaches it.

**A6 — `SKILL` is scope-safe by construction.** Over the A3 enumeration,
assert that every (trace, scope) yielding `SKILL` has
`scope.startswith("skill:")`.
*Broken:* a mutation that drops the scope test from `t3_route_taken`
produces `SKILL` at `project`/`user` scope, which `verbs.py:930-935`
refuses at route time — the test names the scope it saw.

### B. The scope-conditional `t4` rule

**B1 — the under-requirement closes.** `t3.answer: yes`, `owner: alpha`,
`t2: no`, `tn: no`, `t4: null`, scope `skill:beta` → `ProposalError`
matching `gates.t4` **and** the scope string.
*Broken:* without the rule the call returns cleanly and the table crashes
downstream; without the scope in the message the refusal is unactionable.

**B2 — its positive control.** The same trace with `t4` populated, same
scope → accepted. Without B2, B1 passes on a build that refuses
everything.

**B3 — the over-permission closes in the other direction.** Same trace with
`t4` populated at scope `skill:alpha` (the owner) → `ProposalError` naming
`gates.t4`; with `t4: null` at that scope → accepted.

**B4 — scope-free behaviour is byte-identical to today.** All four traces
of B1–B3 validate **unchanged** when `scope` is omitted (two accepted, two
accepted). Asserted against `validate_proposal(data)` called exactly as it
is at `analyst.py:244`.
*Broken:* if the builder makes the scoped rules unconditional, this
criterion fails — and so would `worker.py`'s landing check on proposals
`write_proposal` had just accepted (§6-BD3).

### C. Recompute-and-refuse

**C1 — the mismatch is refused, and the twin is accepted.** A trace whose
`outcome` disagrees with Table-1 → `ProposalError` whose message contains
**both** the stated and the derived outcome. The identical trace with the
derived outcome → accepted.

**C2 — S6 holds: nothing but `ProposalError` ever escapes.** *(r1 gate
BLOCKER, restated.)* Parameterised over genuinely **malformed** inputs:
`outcome` absent; `outcome` a non-string; `scope` not a string at all
(`123`, `["skill:s"]`); `scope` the empty string; and `scope` the
empty-name form `"skill:"`. For each, the call **either returns normally
or raises `ProposalError`** — assert by catching `Exception` and requiring
`isinstance(exc, ProposalError)`, never a bare `except Exception` that
swallows the distinction.
*Broken:* a `TypeError`/`KeyError`/`AttributeError` escaping here is the
FW-63 shape — `proposal_info` catches only `ProposalError` and `queue()`
catches nothing, so one malformed trace tracebacks `self-learn list` for
every record in the bucket.

**A legal scope value never refuses on shape alone — this counter-leg is
mandatory and is what the r1 gate's BLOCKER was about.** `records.py`'s
`_validate_scope` (`:806-811`) admits exactly `project`, `user` and
`skill:<name>`; **`project` and `user` have no `skill:` prefix and are all
but one of the live hot path** — of the 35 pending records, **31 are
`user` (89%), 3 are `project`, and 1 is `skill:*`**. So C2 must, in the
same test, assert that
a **coherent** trace validates cleanly at all three of `"project"`,
`"user"` and `"skill:s"`. Only the trace's own content may refuse it.
Without this leg, a build that refuses every scope satisfies C2 while
`proposal_info` — which §3.5 puts on every pending record on every
`list`/`status` — refuses the majority of the live ledger.

*A property worth asserting while here, because it is what makes the
empty-name case harmless:* `"skill:"` cannot take the t3 route, because
`t3_route_taken` compares against `"skill:" + owner` and `_validate_gates`
already refuses an empty `gates.t3.owner` when `t3.answer` is `yes`
(`ledger_ops.py:1024-1028`). The malformed scope therefore degrades to
"route not taken", which is a defined outcome, not a crash.

**C3 — the eligibility path is really wired.** Through the real
`queue()` → `proposal_info()` path (not a direct `validate_proposal`
call): a mismatched trace gives `proposal_fresh is False` **and**
`has_proposal is True`; rewriting the outcome to the derived value gives
`proposal_fresh is True`.
*Broken:* the `has_proposal` leg is what distinguishes "refused" from "the
file vanished" — without it, deleting the proposal would pass the same
assertion.

**C4 — the producer path is really wired.** `write_proposal` with a
mismatched trace raises `ProposalError` **and the proposal file does not
exist afterwards**; the twin with the derived outcome writes it.
*Broken:* without the file-absence leg, a build that validates after
writing passes.

**C5 — the human path is really wired, by exit code.** `cli.main(["proposal",
"validate", rid])` returns **1** (`EXIT_SCHEMA_INVALID`) on a mismatched
trace and **0** on the twin, with the rc taken from the return value —
**never read downstream of a pipe** (campaign §5).
*Broken:* dropping `scope=` at `selfcheck.py:163` makes both return 0,
which is the FW-62 inversion restored.

### D. Render-1

Each D-criterion asserts a **refusal with a message naming the offending
field**, immediately followed in the same test by its **accepting twin**.
A D-criterion without its twin is not satisfied.

**D1 — R-DEMAND**: `DEMAND` + `destination: claude-md` refused; +
`reference` accepted.
**D2 — R-PATHED**: `PATHED` + `variant: null` refused; `PATHED` +
`variant: rules` + non-empty `rules_paths` + `rules_topic` accepted.
**D3 — R-ALWAYS**: `ALWAYS` + `variant: rules` + non-empty `rules_paths`
refused; `ALWAYS` + `variant: null` accepted; **and** `ALWAYS` +
`variant: local` accepted, **and** `ALWAYS` + `variant: rules` with no
`rules_paths` accepted (the §6-BD7 admissions — without these two legs a
build that simply refuses every variant on `ALWAYS` passes D3).
**D4 — R-SKILL**: `SKILL` + `destination: claude-md` refused; +
`skill-md` accepted.
**D5 — R-HOOK**: `HOOK` + `destination: hook` but `alternates` missing the
load-class destination refused; with it present accepted. The test
derives the expected alternate from `load_class`, never hardcodes it.
**D6 — R-NEW**: `NEW_SKILL` with `new_skill` ≠ `gates.tn.proposed_name`
refused; equal accepted.
**D7 — R-FALL**: for each of `REJECT`/`DEFER`/`GRADUATE`, a wrong
`recommendation` refused and the right one accepted; and a `GRADUATE`
proposal with `already_canon: false` refused, `true` accepted. **And**:
the destination is asserted to equal the *load class's* destination, with
a second fixture whose load class differs from the first — otherwise the
rule passes for a build that hardcodes one destination.
**D7a — R-FALL beats R-SCOPE, asserted where they collide.** *(r1 gate
F3.)* A `REJECT` outcome at `scope="user"` whose load class is `DEMAND` —
i.e. an unroutable rendering under an outcome that is not a routing —
**keeps `recommendation: reject`, carries NO `no-cheap-surface` flag, and
is accepted**; the same proposal with `recommendation: defer` is refused.
Without D7a both readings of §3.3 pass §4 and the build picks one by
accident. This is the only criterion that exercises a fallback outcome at
an unroutable scope.
**D8 — R-SCOPE at user scope.** `DEMAND` at `scope="user"` with
`recommendation: route` refused (message names `no-cheap-surface` or the
scope); with `recommendation: defer` **and** `flags: ["no-cheap-surface"]`
accepted; with `defer` but **no** flag refused.
**D9 — R-SCOPE at skill scope.** The same three legs for `PATHED` at
`scope="skill:s"`. This is the hole r2 does not name (§3.4); without D9 a
build that special-cases user scope alone passes everything else.
**D10 — `recommendation` absent reads as `route`.** A `DEMAND` proposal at
project scope with no `recommendation` key is accepted; the same with
`recommendation: defer` is refused.
*Broken:* if absent were read as "skip the check", D10's second leg would
pass and the first would too — the twin is what separates them.

### E. The seam

**E1 — absent-is-valid survives.** A proposal with no `gates:`, no
`flags:`, no `recommendation:` validates identically with `scope=`
supplied, with `record_text=` supplied, with both, and with neither; and
its `proposal_info` dict and `is_unanalyzed` result are unchanged.
*Broken:* any derivation that runs on a trace-less proposal fails here,
loudly, and would otherwise have wedged all 20 live proposals (§9-X6).

**E2 — the new parameter is keyword-only with a default.** By
`inspect.signature`, `scope` on both `validate_proposal` and
`_validate_gates` is `KEYWORD_ONLY` with default `None`.
*Broken:* a positional parameter silently changes meaning at
`analyst.py:244`, `worker.py:927`, `:1282`, `verbs.py:551`, `:1193`,
`:1247` — six sites this unit may not edit.

**E3 — the suite.** `cd plugins/self-learn/cli && ./.venv/bin/python -m
pytest -q`, rc captured **unpiped**. Baseline re-measured on this tree
2026-08-06: **1379 passed, 5 skipped, 0 failed, rc=0**. After the unit:
1379 + the new module's tests, minus nothing, **0 failed**. Any failure
beyond that blocks — the CLI suite has **no** tolerated failure (campaign
§4a).

**E4 — pyright: zero new.** `pyright --pythonpath ./.venv/bin/python src`.
Judge on *zero new*, never an absolute count; the current figure moves
(campaign register: 50 with the interpreter pinned, 64 without — the
extra 14 are spurious `ruamel` resolution errors).

**E5 — the five reconciled fixtures (§3.7) are corrected, not deleted or
skipped.** Each keeps its original assertion set; only the proposal
fields change. A `pytest.mark.skip` or a deleted assertion in any of the
five is a build failure, not a fold.

---

## 5. Mutation plan

The code gate runs these. **Before any sweep:** `export
PYTHONDONTWRITEBYTECODE=1` and `find . -name __pycache__ -type d -prune
-exec rm -rf {} +` — a stale cache reports mutations as survived that
never executed (FW-61). Use absolute paths and confirm
`realpath(self_learn.__file__)` resolves inside the tree under review; a
survival from the wrong tree is not evidence, while a mutation that
*reddens* is trustworthy either way.

| # | one-line edit | reddens |
|---|---|---|
| M1 | delete the `gates.outcome != derived` refusal | C1, C3, C4, C5 |
| M2 | swap `G1` and `G2` | A5 (`G1`,`G2`) |
| M3 | delete `G3` | A4 (`GRADUATE` unreachable), A5 |
| M4 | `hook_ok`: require only `field_shaped` | A5 (`H`), D5 |
| M5 | delete `L1` | A5 (`L1`), D2 |
| M6 | delete `L3` | A5 (`L3`) — **by exception, not by value** (§3.1 note 3): all 1,904 detections raise, 0 differ |
| M7 | `L6`: drop the `e1_promote` disjunct | A5 (`L6`) |
| M8 | `e1_promote`: `>= 2` → `>= 1` | A5 (`L2b` or `L6`) |
| M9 | `t3_route_taken`: compare `scope == t3["owner"]` (drop the `skill:` prefix) | A6, B1, B3 |
| M10 | invert the two branches of §3.2's scoped `t4` rule | B1, B3 |
| M11 | make §3.2's rule unconditional (ignore `scope is None`) | B4 |
| M12 | `_validate_derivation`: drop the `scope is None` early return | **E1 only** — it reddens the trace-less-with-`scope=None` legs, because `expected_outcome(gates, None)` on an absent-or-partial trace raises. It does **not** redden E2, which asserts an `inspect.signature` property no runtime edit can move; r1's claim that it did was wrong *(gate N6)*. **The builder must state which of the two early returns `_validate_derivation` carries** — `gates is None` and `scope is None` are separate guards, and dropping only the second is what this mutation models |
| M13 | R-DEMAND destination → `claude-md` | D1 |
| M14 | R-ALWAYS: accept `variant: rules` with paths | D3 |
| M15 | drop the `no-cheap-surface` flag requirement from R-SCOPE | D8, D9 |
| M16 | `routable`: always return `True` | D8, D9 |
| M17 | drop `scope=` at `proposal_info` (`ledger_ops.py:1818`) | C3 |
| M18 | drop `scope=` at `write_proposal` | C4 |
| M19 | drop `scope=` at `selfcheck.py:163` | C5 |
| M20 | move `from .gates import …` to `ledger_ops.py` module level | A2 (**both** subprocesses) |
| M21 | R-HOOK: drop the `alternates` requirement | D5 |
| M22 | R-FALL: use the outcome's own destination instead of the load class's | D7 |
| M23 | A3's legality filter always returns `True` (i.e. skip `_validate_gates`) | A3 — the vacuity guard's counterpart: the enumeration then contains illegal traces and the table raises |
| M24 | R-SKILL destination → `claude-md` | D4 |
| M25 | read an absent `recommendation` as "skip the check" instead of `route` | D10 |
| M26 | re-declare a nine-member outcome tuple in `gates.py` and use it | A1 |
| M27 | delete §3.2's scoped `t4` rule while keeping the derivation | B1, B3, **C2** (derivation then raises `TypeError` on §9-X1's shape, i.e. the S6 breach), **A3 and A3b** — and the asymmetry is the point: A3 reddens on 3,264 pairs, A3b on 27,648 (§9-X1e) |
| **M30** | §3.2's rule refuses whenever the window is entered, both branches | **B2** — its positive control; without B2, M10/M27 pass on a build that refuses everything in the window |
| **M31** | R-NEW: drop the `new_skill == gates.tn.proposed_name` comparison | D6 |
| **M24a** | delete `L2a` | A5 (`L2a`) — 510 of 816 fixtures differ; **37.5% of naive fixtures survive**, so this mutation is only meaningful against a DIFFERS-set fixture |
| **M24b** | delete `L2c` (the `otherwise` leg of the `L2` block) | A5 (`L2c`) — 102 differ, 204 raise. **Two thirds of the detections are exceptions**, and both must be counted or the row scores as survived |
| **M24c** | delete `L4` | A5 (`L4`) — 24,752 of 30,464 differ; 18.8% survive |
| **M24d** | delete `L5` | A5 (`L5`) — 5,712 of 15,232 differ; **62.5% survive**, the worst row in the table. See A5 for the fixture shape that does not |
| **M28** | read §3.2's rule globally instead of inside its window | A4 (`NEW_SKILL` unreachable) — and **only** A4: A3's two floors still pass at 543,744 / 239,616 *(gate F4)* |
| **M29** | apply R-SCOPE to R-FALL as well as the six route rows | D7a |

*(M24a–M24d were absent from r1 — four table rows with no mutation at all,
inside the mutation plan written to hunt exactly that. Gate F2.)*

**Every criterion in §4 has at least one mutation above, except E3, E4 and
E5 — deliberately, and stated so the omission is not read as the same
gap.** Those three are process gates over the whole tree (suite green,
pyright zero-new, the five fixtures corrected rather than skipped), not
behaviours a one-line edit can toggle; the instrument that checks them is
running them, not mutating them.

**Reviewers are invited to invent mutations not listed here.** Two shapes
this unit is most likely to be wrong in, named as leads rather than as
findings: (a) a rendering rule that is checked only on the *routable*
branch, so R-SCOPE silently disables it; (b) a `load_class` call in
R-FALL/R-HOOK that is evaluated before §3.2's presence rule has run, which
would reintroduce §9-X1's crash from a different direction. **Lead (b) was
right and is now covered by A3b** — the crash surface reached through
`load_class` is 8.5× the one reached through `expected_outcome` (§9-X1e),
which is what r1 left untested.

---

## 6. Builder decisions, made here rather than left open

- **BD1 — `gates.py` is a new module, not a section of `ledger_ops.py`.**
  Campaign §2 names it; more importantly `ledger_ops.py` is 1,934 lines
  and the table is the one part of this subsystem that is genuinely pure
  and genuinely worth reading on its own. Keeping it separate is also what
  lets A3's exhaustive enumeration import the table without importing the
  validator's context.
- **BD2 — `t1.attempted` is not read by Table-1.** It records whether the
  analyst *attempted* T1, not the verdict; r2 §1.2 says the validator
  cannot referee its trigger condition ("literal command/flag/path
  token"), and r2 §8 item 2 keeps that as MEASURED-or-ACCEPTED work. A
  table that read it would make an unenforceable field load-bearing.
- **BD3 — scoped rules may only ADD refusals, never remove them.** The
  tempting move is to also *relax* U-schema's `t3a` over-requirement
  (§7.2) once scope is known. It is wrong: the scoped sites would then
  accept a trace that `worker.py:927`'s positional `validate_proposal(data)`
  refuses, and `_land_outputs` **deletes** invalid worker output
  (`worker.py:937-940`). A producer whose output the landing step deletes
  is a silent, total loss of the analysis.
  *(r1 said "`write_proposal` (scoped) would then accept…". Wrong path, and
  the correction is worth keeping visible — gate N3. `write_proposal` never
  reaches `_land_outputs`; its only in-CLI caller is `import_backlog.py:267`.
  The producer that actually meets the landing check is **the analyst**,
  whose proposals the model writes directly into `proposals/` and which the
  worker then validates positionally. The hazard is real and the ruling
  unchanged; only the path was misnamed.)*
- **BD4 — no partial derivation when `scope` is absent.** An
  "admissible-set" variant was designed and rejected: with `scope`
  unknown, `L2` may or may not fire, and when `t4` is null the
  fall-through is not computable at all, so the admissible set collapses
  to a constraint weak enough to be misleading — a check that mostly
  cannot fail, dressed as one that runs everywhere. The census (§3.5) is
  stated instead, and the one gap it leaves is handed to the unit that
  owns the file (§8-H1).
- **BD5 — the route verbs' positional call sites stay positional, on
  purpose.** `verbs.py:551` (`_resolve_destination`) reads the proposal at
  route time. Making it derivation-checked would let an internally
  inconsistent *analyst* trace **block a human's route**. The trace is the
  analyst's reasoning; the route is the human's decision. This check gates
  the proposal's honesty, never the human's action. (It also cannot bite
  in practice: the UI's approve path passes `--dest` explicitly — FW-64 —
  so `_resolve_destination` returns before reading the proposal at all.)
- **BD6 — `recommendation` is fully derived, and this is not an S-22
  funnel.** S-22 defines a funnel as a constraint that *silently removes an
  option the agent should have had*. Nothing is removed: every
  recommendation value remains reachable, through the gate that means it
  (`g0.defer.answer: yes` → `DEFER` → `defer`). What is removed is the
  ability to state a recommendation the reasoning does not support — which
  is the audit's original finding in miniature.
- **BD7 — R-ALWAYS admits `variant: local` and unpathed `variant: rules`.**
  Table-1 has no cell for either; refusing them would foreclose
  `CLAUDE.local.md` and topic-file routing for every traced proposal —
  that *would* be a funnel. Both are always-loaded surfaces, so admitting
  them under `ALWAYS` is semantically exact. The cost is stated in §7.3:
  `alternates` cannot distinguish `ALWAYS` from `PATHED`, because both
  render `claude-md`.
- **BD8 — `selfcheck.py` is on the file list for exactly one keyword
  argument. RULED IN SCOPE by the r1 gate (former §8-Q2); the question is
  closed.** *Grounds, recorded because they generalise:* the campaign's
  file-disjointness rule is about **concurrency, not ownership**, and
  nothing is concurrent on `selfcheck.py` — `U-reach` merged at `17aa06c`
  and neither in-flight sibling claims it. Against that, FW-62 was a
  **live fail-open on this exact line, fixed four days ago**; omitting
  `scope=` rebuilds the same inversion one field over, and **C5 is the
  only criterion that exercises the human path end to end by exit code.**
  A later unit taking it would leave the human's hand-edit path the
  lenient one for the whole interval.
- **BD9 — error messages name the gate path, the two outcomes, and the
  scope; never file contents.** Inherited from U-schema's D7 for the same
  reason: the fields echoed are already in the proposal and already
  secret-scanned on every producer path.
- **BD10 — `PATHED` at skill scope DEGRADES rather than being designed
  around. RULED by the r1 gate (former §8-Q1); the question is closed, with
  one condition.** *Grounds:* degrading **forecloses nothing** — closing
  P-A13 later flips one predicate (`routable`) and R-SCOPE simply stops
  firing for that cell, with no change to the schema, Table-1, Render-1 or
  the doctrine. The rejected alternative (b) — teach the doctrine not to
  ask T2 at skill scope — is the one that forecloses, and it is S-22's
  definition of a funnel verbatim: a constraint that silently removes an
  option the agent should have had.
  **The condition, and it is not cosmetic:** degrading routes *both* holes
  — `DEMAND`-at-user and `PATHED`-at-skill — into the same
  `defer` + `no-cheap-surface` bucket. One flag value for two structurally
  different gaps is illegible in aggregate exactly where Checkpoint C
  presses hardest ("did we build a new monoculture at the other end?").
  **So the FW row this unit opens must record skill-scope `PATHED` as a
  DISTINCT Checkpoint-C measurement**, counted separately from
  user-scope `DEMAND`, not folded into a single `no-cheap-surface` total.
  Card-side distinguishability — this spec's §8-H5 — is **owned by
  `U-demand-user`**, assigned to its fold round by the orchestrator; this
  unit supplies the flag, that unit makes the two cases readable apart.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 Not built, with reasons

- **`e1.sightings` cross-check against the record** (U-schema §3.7 item 4,
  offered to "`U-table` or a later unit"). **Deliberately not built. The
  decline is ACCEPTED by the r1 gate, with its stated reason NARROWED —
  and the narrowing matters, because r1's reason was partly wrong.**

  *What r1 argued and the gate corrected:* r1 said checking `sightings`
  alone half-closes a promotion vector while reading as closure. That
  overstates it. `post_demand_recurrence` is `false` corpus-wide (§9-X6
  measured zero traces on the live ledger at all), so a sightings-only
  check **cannot** produce a false promotion; and all three scoped call
  sites already hold the `Record`, so S4 does not bite either. The
  hazard r1 named is not live and the cost r1 implied is not real.

  *The defensible ground, which is the one to keep:* **`e1.sightings` is a
  TRANSCRIPTION of the record's own frontmatter, not a judgment.** This
  unit exists to close *judgment* fabrication — a conclusion that does not
  follow from its stated premises. A transcription check is a different
  class of work with a different owner, and bundling it here would blur
  what the unit is for. Stated explicitly so a later agent does not reopen
  §8-H4 as cheap-and-obvious: it **is** cheap, and it is still not this
  unit's.
- **TARGET-sourced quote containment** (U-schema §3.7 item 1, §8-O2,
  FW-50). Needs I/O on the eligibility hot path (S4). Untouched.
- **`tn.members` existence probes**, **`t3.roster_sha` against a composed
  roster** — U-schema §3.7 items 5 and 6; the second waits on
  `U-composer`'s B6.
- **Making the trace fields mandatory** — **S-26** rules this rides
  `U-composer`, and flipping it here would make `write_proposal` refuse
  every analyst proposal and wedge the worker pipeline. This unit ships
  the trace optional, exactly as U-schema did.
- **The doctrine rewrite** that teaches the analyst to emit a derivable
  trace — `U-composer` (§8-H2). Until it lands, **no proposal carries a
  trace at all** (measured: §9-X6, 0 of 20 live proposals), so every
  refusal this unit adds is inert on current data. That is the designed
  transition, not a gap.

### 7.2 ACCEPTED residual — `t3a` is over-required at a mismatched scope

When `t3.answer == "yes"` and the record's scope is **not**
`skill:<owner>`, Table-1 never reads `t3a` — the run falls through `L3`/`L4`
— yet `_validate_gates` still requires it non-null
(`ledger_ops.py:1073-1077`). The analyst pays real cost (a judgment and a
quote) for a block nobody will read.

**Accepted, not deferred.** Removing it would make the scoped path accept
what the scope-free path refuses, and `worker.py`'s `_land_outputs`
**deletes** proposals its positional `validate_proposal(data)` refuses
(§6-BD3) — trading a wasted paragraph for a destroyed analysis. It closes
for free the day the last positional producer site is scoped, which is
`U-composer`'s (§8-H1); until then it is the correct side of the trade.
U-schema's own §6-D5 named this direction of its residual explicitly and handed
it here; this row is the disposition, so a later agent does not reopen it
as a bug.

**To be recorded in `03-decisions.md` as a settled row (next free number,
S-27 at time of writing), landing in the same commit as the build** —
campaign §1's disposition rule, following `U-pathed`'s S-24/S-25
precedent.

### 7.3 ACCEPTED residual — `alternates` cannot distinguish ALWAYS from PATHED

R-HOOK requires `alternates` to contain the *destination* the load class
renders to. `ALWAYS` and `PATHED` both render `claude-md`
(§3.3), so a HOOK proposal whose real alternative was `PATHED` satisfies
the rule by naming `claude-md`, and so does one whose alternative was
`ALWAYS`.

Closing it would mean giving `alternates` a richer type than the shipped
`list from PROPOSAL_DESTINATIONS` (`ledger_ops.py:1275-1282`) — a schema
change to a field three surfaces already render, for a distinction the
human can read off `gates.t2.answer` on the same card. **Accepted, with
the note that the trace itself carries the missing bit**, so nothing is
actually unauditable — only `alternates` alone is insufficient.

**Same disposition: an `03-decisions.md` row (S-28 at time of writing),
same commit as the build.**

### 7.4 Disclosed, not accepted — the re-analysis loop

A trace that `worker.py:927` lands and `proposal_info` then refuses makes
the record permanently `is_unanalyzed: True`, so the next worker run
re-analyzes it. If the analyst re-emits the same mismatch, that repeats.

**This is the same loop U-schema accepted for quote containment** (its
§3.7 item 1(b), and its own criterion E7 —
`test_fabricated_quote_makes_proposal_unfresh`; note that is *U-schema's*
E7, not this spec's §9-X rows), bounded by the same things: the worker's
run coalescing (S-5), and the fact that every cycle is recorded in the run
journal. It is disclosed rather than accepted because the right fix is not
here: it is `worker.py:927` refusing at landing time and **deleting** the
bad output with a journal line, which is §8-H1 — the same one-line change,
and the same owner. **That handoff is now verified taken**: `U-composer`'s
gate independently found the same gap and its r2 fold requires H1 in full
(§8-H1), so this residual has a named closer and a scheduled one.

---

## 8. What this spec contradicts, and what is handed on

### Contradictions in `misc/routing-procedure-r2.md`, verified against shipped code

- **C1 — §1.5's published table crashes on traces the shipped validator
  accepts.** `TypeError: 'NoneType' object is not subscriptable`, 3,456 of
  97,920 enumerated (trace, scope) pairs, all one shape: `t2: no`,
  `t3: yes`, `tn ≠ yes`, `t4: null`, scope ≠ `skill:<owner>`. Corrected by
  §3.2 (which is also U-schema §8-O3). Measured, §9-X1.
- **C2 — §1.6's PATHED transition rule is DEAD, and following it now
  produces a refusal.** It says PATHED renders `recommendation: defer` +
  flag `pathed-unbuilt` "before B10 lands". **B10 landed**: `U-pathed`
  merged at `63f5962`, and `compilers.py` emits `paths:` frontmatter
  (the section at `compilers.py:330-778` — `read_paths_frontmatter`
  `:542`, `paths_frontmatter_drift` `:584`, `apply_paths_frontmatter`
  `:716`). Under Render-1,
  `PATHED` renders `recommendation: route`, so a doctrine that still
  teaches r2's rule makes every PATHED proposal refuse. **This is the
  single highest-risk coupling in this unit and it is handed to
  `U-composer` as H2.** The `pathed-unbuilt` member of `TRACE_FLAGS` stays
  *valid* — Set-F is U-schema's single definition and this unit does not
  narrow it — it is simply vestigial.
- **C3 — §1.4 item 5 states an iff that is not one.** "destination `hook`
  ⇔ t1 legs all yes" fails whenever a `g0` leg fires: a trace with all
  three t1 legs `yes` **and** `g0.reject.answer: yes` derives `REJECT`,
  which renders the load class's destination, not `hook`. The correct rule
  is `destination == "hook"` ⇔ `outcome == "HOOK"`, and R-HOOK carries it.
- **C4 — §1.6's NEW_SKILL row demands something the schema forbids.** It
  requires `alternates` to contain "the t4 rendering", but `tn.answer:
  yes` forces `t4: null` (`ledger_ops.py:1167-1172`), so there is no t4
  rendering to name. The requirement is **dropped**; R-NEW keeps the
  `new_skill` == `proposed_name` half, which is checkable.
- **C5 — §1.6's DEMAND-at-user-scope rule is described as temporary and is
  now permanent**, and it has an unnamed twin. S-23 (2) settles user scope
  on PATHED and FW-42 keeps the `verbs.py` refusal; and `PATHED` at
  **skill** scope is refused by `_resolve_rules_target` (P-A13) with r2
  saying nothing about it. R-SCOPE replaces both special cases with one
  rule. Measured, §9-X3.

**Cross-unit reconciliation with `U-composer`** *(gate F6)*. `U-composer`'s
r1 §8 carried an assumption 7 — *"doctrine keeps skill-scope T2 answering
no"* — which is the option §6-BD10 rejects as an S-22 funnel: a doctrine
that stops asking a question, to work around a capability gap the table
can state honestly. **Its own gate blocked on the same conflict, and its
r2 adopts R-SCOPE** in its D2/D3, so the two specs now agree that the
table answers T2 at every scope and degrades the rendering where the
surface does not exist. **No change is required on this side** — this
paragraph exists so a later reader who meets the r1 assumption in a diff
does not treat it as live. *(Cited from the sibling's r2 fold instruction;
confirm against `U-composer`'s r2 §8 when it lands.)*

### Observations in contended files — reported, NOT fixed

- **N1 — `worker.py:928`'s `rpath` is computed *after* the validation it
  would inform.** `validate_proposal(data)` runs at `:927`; the pending
  record's path is resolved at `:928`. Wiring `record_text=`/`scope=` there
  needs those two lines swapped. Reported for §8-H1's owner, not done here.
- **N2 — `test_proposal_validate.py:206` duplicates
  `test_decision_trace.py`'s `_base_gates`, deliberately** ("fixtures
  duplicated, not imported"). Both copies now need the same
  outcome/destination coherence, so the duplication has acquired a second
  drift surface. Left alone — merging them would edit two suites this unit
  does not own the design of.

### Obligations handed to other units

- **H1 → `U-composer` (owns `worker.py`):** wire `worker.py:927`'s landing
  check to `validate_proposal(data, record_text=…, scope=…)` (swap `:928`
  above `:927` first, per N1). This is what turns §7.4's silent
  re-analysis loop into a deleted output with a journal line, and it is
  one line plus a move. **It is not urgent before `U-composer` because no
  proposal carries a trace until `U-composer` ships** — the unit that
  creates the exposure is the unit that closes it.
  **HANDOFF VERIFIED TAKEN** *(gate F7)*: `U-composer`'s r1 §3.7 accepted
  only the `record_text=` half; its own blind gate independently found the
  gap (its F1) and its fold round requires taking H1 **in full** —
  `record_text=` **and** `scope=`, with the line swap. So §7.4's residual
  now has a named closer rather than an open hope. *(Cited from the r2
  fold instruction, not from a merged r2 hash; a reader checking this
  should confirm against `U-composer`'s r2 §3.7 when it lands.)*
- **H2 → `U-composer` (owns `routing-doctrine.md`):** the doctrine must
  teach the **current** rendering, not r2 §1.6's. Specifically: PATHED
  renders `route`, not `defer` + `pathed-unbuilt` (§8-C2); the
  DEMAND-at-user-scope and PATHED-at-skill-scope shapes are
  `recommendation: defer` + `flags: [no-cheap-surface]` (R-SCOPE); a HOOK
  proposal must name its load-class destination in `alternates` (R-HOOK);
  and `gates.outcome` is now recomputed, so an outcome that does not follow
  from the answers is a refusal the model must be able to avoid, not
  discover.
- **H3 → `U-name`:** R-NEW pins `new_skill == gates.tn.proposed_name`. If
  `U-name` moves where the proposed name lives, that rule moves with it —
  it is one comparison in `_validate_derivation`.
- **H4 → whoever takes `e1` honesty:** both halves together (§7.1) —
  `sightings` against the record's frontmatter *and*
  `post_demand_recurrence` against `recurrences[]` correlated with a prior
  DEMAND routing. Splitting them produces a check that reads as closure
  and is not.
- **H5 → the review-surface unit:** U-schema's O4 (render the trace's
  quotes verbatim on the card) is still unconfirmed, and this unit adds a
  second card obligation: **the derived outcome and the `no-cheap-surface`
  degradation must be visible.** A proposal whose `recommendation` is
  `defer` because its surface does not exist at that scope looks, on a
  card that shows only `destination`, exactly like one the analyst chose
  to defer.

### Questions this unit routed — both ANSWERED at the r1 gate

Kept as a record of what was asked and how it was settled; the rulings
themselves are normative in §6, not here.

- **Q1 — `PATHED` at skill scope: degrade, or close P-A13?** → **DEGRADE,
  with a condition. §6-BD10.** The remaining work is (a) an FW row for
  closing P-A13, which must record skill-scope `PATHED` as a **distinct**
  Checkpoint-C measurement rather than folding it into a single
  `no-cheap-surface` total. Option (b) — teach the doctrine not to ask T2
  at skill scope — is **rejected**, and `U-composer`'s r1 had assumed it
  (§8's cross-unit paragraph).
- **Q2 — is one keyword argument in `selfcheck.py` inside this unit's
  scope?** → **YES. §6-BD8.** Disjointness governs concurrency, not
  ownership; nothing is concurrent on that file; C5 stays.

---

## 9. What was executed, and against what oracle

Campaign §5: *"if a spec pins an algorithm precisely enough that a builder
is meant to transcribe it, the author must have EXECUTED it, and the spec
must say what was executed and against what oracle."* Table-1 is such an
algorithm. Everything below was run on this worktree, 2026-08-06, in a
scratch sandbox with `SELF_LEARN_HOME`, `XDG_CACHE_HOME`,
`XDG_RUNTIME_DIR`, `SELF_LEARN_CLAUDE_DIR`, `SELF_LEARN_TRANSCRIPTS_DIR`
and `HOME` redirected to `/tmp/utable-scratch`, `PYTHONDONTWRITEBYTECODE=1`,
and `realpath(self_learn.__file__)` confirmed to resolve **inside this
worktree** before any measurement was believed.

**The oracle for legality is the shipped `_validate_gates` itself**, called
directly — not a re-implementation of the schema. That is the whole point:
a trace is "legal" here iff the code that will run in production says so.

**The enumeration's stated preconditions** (an equivalence claim without
its preconditions is a coincidence someone wrote down):

- Varied: all three `g0` answers; `t1.field_shaped` ∈ {yes,no};
  `t1.separable`, `t1.cost_bearing` ∈ {yes,no,null}; `t2.answer`;
  `t3.answer`; `t3a.depth_behind_rule` and `t3a.fs.verdict` (all four);
  `tn.answer` ∈ {yes,no,indeterminate}; `t4` present/absent × its two
  answers × all four verdicts; `e1.sightings` ∈ {1,2};
  `e1.post_demand_recurrence` ∈ {false,true}.
- Fixed: `t1.attempted = True` (not read, §6-BD2); `t3.owner = "alpha"`;
  `t3.roster_sha` a well-formed anchor; every evidence string a single
  fixed quote long enough to clear `_QUOTE_MIN_CHARS`; `tn.terms`,
  `tn.members`, `tn.proposed_name` at their minimum legal shapes.
- **Four further values the enumeration is only LEGAL with, which r1
  omitted** *(gate N2 — and the omission is not cosmetic: without any of
  them the counts collapse and two outcomes become unreachable)*:
  1. **`gates.g0.canon.target`** — a non-empty string whenever
     `canon.answer` is `yes` (`ledger_ops.py:913-919`). Without it every
     `canon: yes` trace is refused and **`GRADUATE` is unreachable**.
  2. **`gates.t3a.depth_behind_rule.target` and
     `gates.t4.depth_behind_rule.target`** — non-empty whenever their own
     `answer` is `yes` (`:1098-1104`, `:1198-1204`).
  3. **`gates.t2.match_path`** — non-empty whenever `t2.answer` is `yes`
     (`:989-994`).
  4. **A sibling `rules_paths` on the proposal dict** whenever `t2.answer`
     is `yes` — U-schema's X1 positive control reads it off the
     *proposal*, not the trace (`:995-1013`), and `match_path` must match
     at least one of its globs. Without it every `t2: yes` trace is
     refused and **`PATHED` is unreachable**. The enumeration used
     `rules_paths: ["src/**/*.py"]` with `match_path: "src/a.py"`.
- Scopes: `user`, `project`, `skill:alpha` (the owner), `skill:beta` (a
  non-owner). Four scopes is the minimum that separates the `L2` branch
  from its fall-through *and* keeps both non-skill scopes distinct for
  R-SCOPE.
- **Containment was OFF** (`record_text=None`) — the enumeration measures
  the table, not the quote check, and containment is U-schema's, already
  tested.

**X1 — r2 §1.5 verbatim, over the legal space.** 66,096 traces enumerated,
**24,480 accepted** by `_validate_gates`; × 4 scopes = 97,920 pairs.
Result: **1 crash class, 3,456 occurrences** —
`TypeError: 'NoneType' object is not subscriptable`, every one at
`t2: no`, `t3: yes`, `tn ≠ yes`, `t4: null`, scope ≠ owner. An independent
count of pairs "the validator admits but the table cannot evaluate" agreed
exactly: 3,456. All nine outcomes were reachable.

**X1b — Table-1 as corrected, same space, with §3.2's rule applied.**
21,888 pairs refused by the scoped rule, **76,032 kept, 0 crashes**, every
result in `TRACE_OUTCOMES`. Over the full `g0` sweep (608,256 pairs):
**0 crashes, and `unreachable overall: []`** — all nine outcomes produced.

**X1c — every row is load-bearing. CORRECTED in r2 after the gate found a
harness bug; r1's load-class counts were exactly 2× too high** *(gate N1)*.

*The bug, named because it is the point:* r1's sweep built its pair list by
concatenating (a) the `g0`-all-no slice and (b) the full `g0` sweep — but
(b) **already contains** (a), so every `g0`-all-no pair was scored twice.
Rows `G1`/`G2`/`G3` differ only on traces where a `g0` leg fires, which are
absent from the duplicated slice, so those three were unaffected — while
`H` and `L1`–`L6` differ only on `g0`-all-no traces, i.e. exactly the
duplicated set, and so doubled uniformly. That is precisely the signature
the gate reported: three rows agreeing, seven at 2×. **The gate was right
and r1 was wrong.** A3's two floors were computed by a different loop with
no duplication, which is why they reproduced exactly on both sides.

Re-run over the 608,256 kept pairs, **each pair scored once**:

| row | fires | differs | raises |
|---|---|---|---|
| `G1` | 304,128 | 304,128 | 0 |
| `G2` | 152,064 | 152,064 | 0 |
| `G3` | 76,032 | 76,032 | 0 |
| `H` | 4,224 | 4,224 | 0 |
| `L1` | 7,344 | 3,536 | 3,808 |
| `L2` (branch entry) | — | 544 | 1,088 |
| `L2a` | 816 | 510 | 0 |
| `L2b` | 510 | 510 | 0 |
| `L2c` | 306 | 102 | 204 |
| `L3` | 1,904 | 0 | 1,904 |
| `L4` | 30,464 | 24,752 | 0 |
| `L5` | 15,232 | 5,712 | 0 |
| `L6` | 9,520 | 9,520 | 0 |

Three internal consistency checks, each derivable without running
anything, which is what makes these numbers trustworthy in a way r1's were
not: `L1`'s 3,536 + 3,808 = **7,344**, its own fire count; `L3`'s 1,904
raises = the `NEW_SKILL` population exactly; `L2c`'s 102 + 204 = **306**,
and the split is explained — deleting `L2c` falls through to `L3` for the
`tn: yes` subset (102, returns `NEW_SKILL`) and to `L4` for the rest (204,
reads `t4`, which §3.2 has just forced to `null` when the t3 route is
taken → raises).

**`L2c` is `306 / 102 differ / 204 raise` — 0% surviving. That is the sole
correct figure and there is no competing one.** The r1 gate reported
`306 / 0 / 100% surviving` ("no single-line deletion can redden it"); at
the delta round it established that its own harness had **no edit branch
for that row**, so the run measured no edit at all and the 100% was an
artefact, not a finding. The figures above are the author's line-deletion
measurement, reproduced by the gate. **`L2c` IS mutatable** (M24b), and
two thirds of its detections are exceptions rather than differing values,
which is the only thing about it a sweep must handle specially.

**X1d — §3.2's window clause, measured against its own misreading**
*(gate F4)*. Same enumeration, two readings of the scoped `t4` rule:

| reading | kept | refused | unreachable outcomes |
|---|---|---|---|
| **window** (§3.2 as pinned) | 608,256 | 175,104 | none |
| **global** (rule applied to every trace) | 543,744 | 239,616 | **`NEW_SKILL`** |

The misreading refuses every `tn: yes` trace, because those legally carry
`t4: null`. **A3's two floors both still pass under it** (543,744 ≥ 500,000;
239,616 > 100,000) — only A4's set equality catches it, which is why A4 is
written as equality and not containment.

**X1e — the crash surface is 8.5× larger through `load_class`** *(gate
F5)*. Same enumeration, §3.2's rule **not** applied, counting pairs on
which each entry point raises: `expected_outcome` **3,264**, `load_class`
**27,648**. `expected_outcome` returns early on `G1`/`G2`/`G3`/`H` and so
never reaches most of the fragile region; `load_class` is called directly
by R-FALL and R-HOOK (§3.1 note 1), so the production-reachable surface is
the larger one. A3b exists for this.
*(The 3,264 here and X1's 3,456 are both correct and measure different
things: X1 runs r2's **verbatim** table, which computes the load class
eagerly **before** its hook test, so it also crashes on the 192 pairs
where `hook_ok` fires. Table-1 returns at `H` first. The 192-pair gap is
r2's eager evaluation, not a discrepancy.)*

**X2 — the import cycle.** In a scratch copy of the package: a
module-level `from .gates import …` in `ledger_ops.py` fails **both**
import orders — with **different messages**, tabulated in §3.6 *(gate
N4)*: entering from `ledger_ops` names `TRACE_OUTCOMES`, entering from
`gates` names `expected_outcome`. The deferred (function-level)
arrangement succeeds in both orders and the call path works.

**X3 — the scope holes**, by calling `verbs._resolve_target` and
`verbs._resolve_rules_target` directly against a sandbox ledger: the
table in §3.4 is that run's output. The two refusal messages quoted in
§3.4 are verbatim.

**X4 — the `L3` exception asymmetry** is X1c's `L3` row.

**X5 — suite impact, from a working prototype of this exact design.**
Baseline on this tree, real src + real tests: **1379 passed, 5 skipped,
rc=0** (rc from the process, not through a pipe) — matching the campaign
register. With the prototype (`gates.py` + the `ledger_ops` and
`selfcheck` wiring) on `PYTHONPATH` against the real tests:
**5 failed, 1374 passed, 5 skipped**; the five are exactly §3.7's table.
With §3.7's five fixture corrections applied, the two affected modules
return **93 passed, rc=0**.
*What this does and does not establish:* it establishes the blast radius
and the fixture fixes. It does **not** establish that the shipped build is
correct — the prototype was written to measure, its error messages are not
the spec, and the code gate's mutation sweep is a separate instrument
deliberately not run by the author.

**X6 — the live ledger, read-only** (`~/.self-learn`, no verb run against
it): **20 proposal siblings, 0 carrying `gates:`, 0 carrying `flags:`, 0
carrying `recommendation:`.** So every refusal this unit adds is inert on
current data. Also measured, as the baseline Checkpoint C will be scored
against: 54 resolved records (31 routed, 22 superseded, 1 rejected);
`routing.destination` = `reference` 14, `claude-md` 13, `skill-md` 5,
`hook` 3; `routing.variant` = **none, on all 54** — PATHED has never been
used. By scope: user → claude-md 8 + hook 1; project → claude-md 5 +
hook 1; `skill:home-assistant` → reference 14; `skill:hypr-doctor` →
skill-md 4; `skill:chezmoi` → skill-md 1 + hook 1. This reproduces and
extends the 2026-07-27 audit's baseline.

**X7 — what could NOT be executed, stated rather than skipped.** Campaign
§5 names *"the 51 resolved records are the table's regression fixtures"*.
That measurement **cannot run in this unit**: running Table-1 over a
resolved record requires that record to have a trace, and X6 measures zero
traces in the entire ledger. Hand-authoring traces for 54 resolved records
to make the fixture set exist would be fabricating the very inputs the
check exists to verify. **Disposition: the regression is a Checkpoint-A
measurement**, run after `U-composer` lands and the pending queue is
re-analyzed under the new doctrine — **35 pending records carrying 20
proposals as measured today** *(gate N6: r1 said "12 pending", a figure
inherited from the campaign playbook's 2026-07-27 text and stale by 23
records)* — at which point it becomes a diff of derived outcomes against
accepted routings, which is what it was always meant to be. What X6
establishes now is the *target distribution* that diff will be scored
against, and one fact worth carrying to Checkpoint C:
**four of Table-1's six routable outcomes have live precedent
(`ALWAYS`/`DEMAND`/`SKILL`/`HOOK`); `PATHED` and `NEW_SKILL` have never
been produced, ever.**

**One honest observation from X1b, offered as a caution and not as a
prediction.** Over the artificial, uniformly-weighted input space,
`DEMAND` is the single most common result (37,298 of 76,032 in the `g0`
all-no slice, ~49%): with every judgment answered "no", Table-1 lands on
`DEMAND`. That is r2's design — the cheap shelf is the default — and it is
**not** a forecast of real routing, because real traces are not uniformly
distributed. It is stated because Checkpoint C's hardest question is
*"did we build a new monoculture at the other end?"*, and the table's own
default is the first place to look.

---

## 10. Revision history

- **r1 (2026-08-06)** — first draft, for the blind spec gate. Written
  against merged `U-schema` (`176eee6`) and merged `U-pathed` (`63f5962`),
  under **S-23**, **S-26**, and the S-21 amendment. Five r2 corrections
  (§8-C1…C5), three of them measured; the executed evidence is §9.

- **r2 (2026-08-06)** — **blind spec gate: SOUND, buildable after folds.
  1 BLOCKER, 6 FOLD, 6 NOTE — all folded here.** The gate reproduced §9-X1,
  X1b, X1d, X1e, X2, X5 and X6 independently, from a clean sandbox with the
  shipped validator as oracle. Rebased onto master `07d8c08` first
  (docs-only delta; no citation moved).

  | # | fold | where |
  |---|---|---|
  | **BLOCKER** | C2 parameterised over `scope` values that are **legal** (`project`/`user` have no `skill:` prefix), so as written it demanded refusal of the two commonest scopes on the hot path — contradicting criteria D8/D10. Replaced with genuinely malformed shapes; added the mandatory counter-leg that a legal scope never refuses on shape alone | C2 |
  | F2 | golden fixtures could survive deletion of their own row (`L5` 62.5%, `L2a` 37.5%, `L4` 18.8%), and four rows had no mutation at all | A5, M24a–M24d |
  | F3 | R-SCOPE × R-FALL was unpinned and both readings passed §4 | §3.3, D7a, M29 |
  | F4 | §3.2's bullets lacked their window restriction; read globally they make `NEW_SKILL` unreachable and only A4 sees it | §3.2, X1d, M28 |
  | F5 | A3 swept `expected_outcome`, but the reachable crash surface is `load_class`'s — 8.5× larger | A3b, X1e |
  | F6 | cross-unit: `U-composer` r1 assumed the doctrine branch §6-BD10 rejects; its r2 adopts R-SCOPE | §8 |
  | F7 | cross-unit: H1 was taken only half; `U-composer`'s r2 takes it in full | §8-H1, §7.4 |
  | N1 | **§9-X1c's load-class counts were 2× too high — my harness double-counted the `g0`-all-no slice.** Gate right, r1 wrong; re-derived, with three first-principles consistency checks. `L2c` was reported as a disagreement at r2 and **resolved at the delta round in this spec's favour** — see r3 below | X1c |
  | N2 | four preconditions the enumeration is only legal with were unstated | §9 |
  | N3 | §6-BD3 named `write_proposal` where the producer is the **analyst** | §6-BD3 |
  | N4 | the `ImportError` quote is order-specific; both messages tabulated | §3.6, X2 |
  | N5 | §3.4 defined `routable()` over 3 of 6 destinations | §3.4 |
  | N6 | M12's redden-claim (E2 → E1); "12 pending" stale → 35 pending / 20 proposals; `ledger_ops.py` contention + wave sequencing; rebase | §5, X7, preamble |

  **Two open questions closed as rulings, written into §6 with their
  grounds:** Q2 → **D8** (`selfcheck.py` in scope; disjointness governs
  concurrency, not ownership), Q1 → **D10** (degrade, plus the condition
  that skill-scope `PATHED` be a *distinct* Checkpoint-C measurement; card
  distinguishability is `U-demand-user`'s). The §7.1 `sightings` decline
  was accepted with its reason **narrowed** — the honest ground is that
  `e1.sightings` is a transcription, not a judgment.

- **r3 (2026-08-06)** — **delta round: SOUND, CLEARED FOR BUILD.** The gate
  confirmed the blocker closed, verified every fold, and audited the four
  unrequested r2 changes (the `D-`→`BD-` rename, M30, M31, the build-order
  tripwire) as sound. Two figure substitutions land here, both measured
  read-only against the live ledger before editing:

  1. **§4-C2's counter-leg carried the wrong population.** r2 said "of the
     35 live pending records, 9 are `user` and 6 are `project`" — those are
     the *resolved*-by-destination tallies from §9-X6 (8+1 user, 5+1
     project) transposed onto the pending set. Re-measured: **31 `user`,
     3 `project`, 1 `skill:*` of 35 — 89% user.** The correction
     strengthens C2's own argument rather than weakening it.
  2. **§9-X1c's `L2c` disagreement is resolved in this spec's favour and
     the two-models framing is gone.** The gate established that its r1
     harness had **no edit branch for `L2c`**, so its `306 / 0 / 100%
     surviving` measured no edit at all. `306 / 102 differ / 204 raise`
     (0% surviving) is the sole correct figure. The old "two different edit
     models" wording is removed because it could have licensed a code gate
     to score `L2c` as unmutatable and reproduce the artefact.
