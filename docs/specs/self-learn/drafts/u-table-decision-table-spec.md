# Spec — U-table: the decision table as a pure module, and the recompute-and-refuse check

Status: **r1 — DRAFT, for the blind spec gate.** Unit `U-table` of the r2
routing campaign (`forward/r2-routing-campaign.md` §2, Wave 2). Dependency
`U-schema` is **MERGED** (`176eee6`); this spec is written against the code
that shipped and its post-merge fixes (FW-57/62/63/66/67, `05f8a5b`,
`81cb694`, `358c9c1`), not against U-schema's draft. Implementation
reference: `misc/routing-procedure-r2.md` §1.4 item 3, §1.5, §1.6 — **which
this spec corrects in five places, three of them measured; see §8.**

**Files this unit may touch:**

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/gates.py` | **NEW.** The pure table. |
| `plugins/self-learn/cli/src/self_learn/ledger_ops.py` | `_validate_gates` gains `scope`; new `_validate_derivation`; `validate_proposal` threads it; `write_proposal` + `proposal_info` supply it. |
| `plugins/self-learn/cli/src/self_learn/selfcheck.py` | **One call site, one keyword argument** (`scope=record.scope` at `selfcheck.py:163`). Nothing else. See §3.5 and §6-D8. |
| `plugins/self-learn/cli/tests/test_decision_table.py` | **NEW.** This unit's tests. |
| `plugins/self-learn/cli/tests/test_decision_trace.py` | Four fixtures reconciled (§3.7). |
| `plugins/self-learn/cli/tests/test_proposal_validate.py` | One fixture reconciled (§3.7). |

Anything else — `worker.py`, `analyst.py`, `verbs.py`, `miner.py`,
`telemetry.py`, `compilers.py`, the UI, `routing-doctrine.md` — is **out of
scope and must be reported, not edited.** `verbs.py` is live in
`U-demand-user` this wave; `worker.py` and `analyst.py` are `U-composer`'s,
and `U-composer` is being spec'd concurrently. §8 names what is handed to
each.

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
| §8-O3 | enforce the scope-conditional `t4` presence rule a scope-free validator cannot (§6-D5) | **Built** — §3.2. Not tidiness: it is what makes the table total (§9-X1). |
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
`t1.attempted` is **not** read (§6-D2).

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
   rather than a partial one (§6-D4).
3. **`L3`'s removal reddens by *exception*, not by a different answer** —
   measured (§9-X4). Deleting `L3` falls through to `t4`, which is `null`
   whenever `tn.answer == "yes"` (`ledger_ops.py:1167-1172`). A mutation
   sweep that only diffs return values will score `L3` as "survived". It
   did not; it crashed.

### 3.2 The scope-conditional `t4` presence rule (U-schema §8-O3)

`_validate_gates` gains a keyword-only `scope: str | None = None`.

The existing t4-presence block (`ledger_ops.py:1163-1181`) leaves one
window open — `t3.answer == "yes"`, `t2.answer == "no"`,
`tn.answer != "yes"` — because the scope-free validator cannot know
whether the t3 route is taken. **With `scope` in hand the window closes:**

- `t3_route_taken(gates, scope)` → `t4` **must** be `null` (Table-1 never
  reads it; r2 §1.2's "else null").
- otherwise → `t4` **must** be non-null (Table-1 falls through to `L4`).

Both are **additions**: each refuses a trace the scope-free rule accepted;
neither accepts one it refused. That direction is mandatory, not stylistic
— see §6-D3 for the two-path contradiction that the other direction
produces, and §7.2 for the residual it forces this unit to keep.

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
  produces `DEFER` and therefore `recommendation: defer` by R-FALL. §6-D6
  records the S-22 funnel analysis in full.
- **R-ALWAYS and R-PATHED are discriminated by the *load semantics*, not
  by a label.** A `variant: rules` file with no `rules_paths` is an
  always-loaded file (r2 §1.6's own parenthesis: "an unpathed rules file
  is a legal, always-loaded surface — same cost as CLAUDE.md"), so
  R-ALWAYS admits it, and admits `variant: local` too. §6-D7 gives the
  reason this is not a loophole.

### 3.4 The two scope holes — one of which r2 does not name

Measured by calling the shipped resolvers directly (§9-X3):

| rendering | `skill:<name>` | `project` | `user` |
|---|---|---|---|
| `reference` (R-DEMAND) | resolves | resolves | **REFUSED** — `verbs.py:1045-1050` |
| `claude-md` + `variant: rules` (R-PATHED) | **REFUSED** — `verbs.py:811-816` | resolves | resolves |
| `skill-md` (R-SKILL) | resolves | refused, unreachable by Table-1 | refused, unreachable by Table-1 |

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
  than two special cases. **§8-Q1 routes the underlying question (close
  P-A13, or steer the doctrine away from T2 at skill scope) to the gate
  and the human; this unit does not decide it and does not need to.**

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
| `verbs.py:551`, `:1193`, `:1247` | positional | **unchanged, deliberately** — §6-D5 |

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
module-level `from .gates import …` in `ledger_ops.py` fails with
`ImportError: cannot import name 'TRACE_OUTCOMES' from partially
initialized module 'self_learn.ledger_ops' (most likely due to a circular
import)`. Not a warning, not order-dependent — **both** orders fail, so
`self-learn` would not start at all.

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

**A5 — the golden rows.** One pinned (trace, scope) → outcome per Table-1
row id (`G1`, `G2`, `G3`, `H`, `L1`, `L2a`, `L2b`, `L2c`, `L3`, `L4`,
`L5`, `L6`), each asserted individually with the row id in the assertion
message. Each pinned trace must be one `_validate_gates` accepts.
*Broken:* a reordered or deleted row changes exactly the rows that depend
on it; §5's M2–M8 name which. *Recorded so the gate does not misread its
own sweep:* the `L3` mutation reddens by **exception**, not by a different
value (§3.1 note 3, measured §9-X4).

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
`write_proposal` had just accepted (§6-D3).

### C. Recompute-and-refuse

**C1 — the mismatch is refused, and the twin is accepted.** A trace whose
`outcome` disagrees with Table-1 → `ProposalError` whose message contains
**both** the stated and the derived outcome. The identical trace with the
derived outcome → accepted.

**C2 — S6 holds.** Parameterised over malformed shapes (`outcome` absent,
`outcome` a non-string, `gates` legal but `scope` an empty string, a scope
string with no `skill:` prefix): every call raises `ProposalError` and
nothing else, asserted with `pytest.raises(ProposalError)` — never a bare
`except Exception`.
*Broken:* a `TypeError`/`KeyError` escaping here is the FW-63 shape;
`proposal_info` catches only `ProposalError` and `queue()` catches
nothing.

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
`rules_paths` accepted (the §6-D7 admissions — without these two legs a
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
| M6 | delete `L3` | A5 (`L3`) — **by exception, not by value** (§3.1 note 3) |
| M7 | `L6`: drop the `e1_promote` disjunct | A5 (`L6`) |
| M8 | `e1_promote`: `>= 2` → `>= 1` | A5 (`L2b` or `L6`) |
| M9 | `t3_route_taken`: compare `scope == t3["owner"]` (drop the `skill:` prefix) | A6, B1, B3 |
| M10 | invert the two branches of §3.2's scoped `t4` rule | B1, B3 |
| M11 | make §3.2's rule unconditional (ignore `scope is None`) | B4 |
| M12 | `_validate_derivation`: drop the `scope is None` early return | E1, E2 |
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
| M27 | delete §3.2's scoped `t4` rule while keeping the derivation | B1, B3, **and C2** — derivation then raises `TypeError` on §9-X1's 3,456-pair shape, i.e. the S6 breach |

**Reviewers are invited to invent mutations not listed here.** Two shapes
this unit is most likely to be wrong in, named as leads rather than as
findings: (a) a rendering rule that is checked only on the *routable*
branch, so R-SCOPE silently disables it; (b) a `load_class` call in
R-FALL/R-HOOK that is evaluated before §3.2's presence rule has run, which
would reintroduce §9-X1's crash from a different direction.

---

## 6. Builder decisions, made here rather than left open

- **D1 — `gates.py` is a new module, not a section of `ledger_ops.py`.**
  Campaign §2 names it; more importantly `ledger_ops.py` is 1,934 lines
  and the table is the one part of this subsystem that is genuinely pure
  and genuinely worth reading on its own. Keeping it separate is also what
  lets A3's exhaustive enumeration import the table without importing the
  validator's context.
- **D2 — `t1.attempted` is not read by Table-1.** It records whether the
  analyst *attempted* T1, not the verdict; r2 §1.2 says the validator
  cannot referee its trigger condition ("literal command/flag/path
  token"), and r2 §8 item 2 keeps that as MEASURED-or-ACCEPTED work. A
  table that read it would make an unenforceable field load-bearing.
- **D3 — scoped rules may only ADD refusals, never remove them.** The
  tempting move is to also *relax* U-schema's `t3a` over-requirement
  (§7.2) once scope is known. It is wrong: `write_proposal` (scoped) would
  then accept a proposal that `worker.py:927`'s positional
  `validate_proposal(data)` refuses, and `_land_outputs` **deletes**
  invalid worker output (`worker.py:937-940`). A producer whose output the
  landing step deletes is a silent, total loss of the analysis.
- **D4 — no partial derivation when `scope` is absent.** An
  "admissible-set" variant was designed and rejected: with `scope`
  unknown, `L2` may or may not fire, and when `t4` is null the
  fall-through is not computable at all, so the admissible set collapses
  to a constraint weak enough to be misleading — a check that mostly
  cannot fail, dressed as one that runs everywhere. The census (§3.5) is
  stated instead, and the one gap it leaves is handed to the unit that
  owns the file (§8-H1).
- **D5 — the route verbs' positional call sites stay positional, on
  purpose.** `verbs.py:551` (`_resolve_destination`) reads the proposal at
  route time. Making it derivation-checked would let an internally
  inconsistent *analyst* trace **block a human's route**. The trace is the
  analyst's reasoning; the route is the human's decision. This check gates
  the proposal's honesty, never the human's action. (It also cannot bite
  in practice: the UI's approve path passes `--dest` explicitly — FW-64 —
  so `_resolve_destination` returns before reading the proposal at all.)
- **D6 — `recommendation` is fully derived, and this is not an S-22
  funnel.** S-22 defines a funnel as a constraint that *silently removes an
  option the agent should have had*. Nothing is removed: every
  recommendation value remains reachable, through the gate that means it
  (`g0.defer.answer: yes` → `DEFER` → `defer`). What is removed is the
  ability to state a recommendation the reasoning does not support — which
  is the audit's original finding in miniature.
- **D7 — R-ALWAYS admits `variant: local` and unpathed `variant: rules`.**
  Table-1 has no cell for either; refusing them would foreclose
  `CLAUDE.local.md` and topic-file routing for every traced proposal —
  that *would* be a funnel. Both are always-loaded surfaces, so admitting
  them under `ALWAYS` is semantically exact. The cost is stated in §7.3:
  `alternates` cannot distinguish `ALWAYS` from `PATHED`, because both
  render `claude-md`.
- **D8 — `selfcheck.py` is on the file list for exactly one keyword
  argument.** It is not contended this wave (`U-reach` merged at
  `17aa06c`; no in-flight unit names it). The alternative — hand it to a
  later unit — recreates FW-62, whose own row calls a validator with a
  strict machine path and a lenient human path "permissions inverted".
  Flagged to the gate as a scope call (§8-Q2).
- **D9 — error messages name the gate path, the two outcomes, and the
  scope; never file contents.** Inherited from U-schema's D7 for the same
  reason: the fields echoed are already in the proposal and already
  secret-scanned on every producer path.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 Not built, with reasons

- **`e1.sightings` cross-check against the record** (U-schema §3.7 item 4,
  offered to "`U-table` or a later unit"). **Deliberately not built, and
  the reason is not cost.** `e1_promote` requires `sightings >= 2` **and**
  `post_demand_recurrence`, and the second conjunct is *structurally*
  uncheckable here (it needs `recurrences[]` history correlated with a
  prior DEMAND routing — U-schema §3.7 item 8; r2 §8 item 5 records it as
  `false` on every record in the corpus). Checking `sightings` alone
  closes one of two doors on a promotion vector and leaves the other wide
  open, while *reading* as though the vector were closed. Both halves are
  handed as one obligation (§8-H4).
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
(§6-D3) — trading a wasted paragraph for a destroyed analysis. It closes
for free the day the last positional producer site is scoped, which is
`U-composer`'s (§8-H1); until then it is the correct side of the trade.
U-schema §6-D5 named this direction of its residual explicitly and handed
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

**This is the same loop U-schema accepted for quote containment**
(its §3.7 item 1(b) and E7's test), bounded by the same things: the
worker's run coalescing (S-5), and the fact that every cycle is recorded
in the run journal. It is disclosed rather than accepted because the
right fix is not here: it is `worker.py:927` refusing at landing time and
**deleting** the bad output with a journal line, which is §8-H1 — the same
one-line change, and the same owner.

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

### Questions this unit routes rather than answers

- **Q1 — `PATHED` at skill scope: degrade, or close P-A13?** This spec
  degrades (R-SCOPE), because that is the change that does not require a
  ruling. The alternatives are (a) close P-A13 so skill-scope rules files
  exist — real work in `verbs.py`/`compilers.py`, and a documentation
  question about plugin-shipped rules; (b) teach the doctrine that T2 is
  not asked at skill scope — cheap, but it hides a real capability gap
  behind a prompt. **Recommendation: degrade now (this spec), open an FW
  row for (a), and do not do (b)** — a doctrine that stops asking a
  question is how the monoculture was built the first time.
- **Q2 — is one keyword argument in `selfcheck.py` inside this unit's
  scope?** §6-D8 argues yes; the gate should rule. If the answer is no,
  criterion C5 moves out with it and the human's hand-edit path stays
  FW-62-shaped until someone else takes it — which the gate should weigh
  against the campaign's file-disjointness rule, not just against the
  file list.

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
- Fixed: `t1.attempted = True` (not read, §6-D2); `t3.owner = "alpha"`;
  `t3.roster_sha` a well-formed anchor; every evidence string a single
  fixed quote long enough to clear `_QUOTE_MIN_CHARS`; `tn.terms`,
  `tn.members`, `tn.proposed_name` at their minimum legal shapes.
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

**X1c — every row is load-bearing.** Deleting each Table-1 row and
re-running the full sweep: `G1` 304,128 differing results; `G2` 152,064;
`G3` 76,032; `H` 8,448; `L1` 7,072 (+7,616 errors); `L2` 1,088 (+2,176);
`L2a` 1,020; `L2b` 1,020; `L4` 49,504; `L5` 11,424; `L6` 19,040. **`L3`:
0 differing results, 3,808 errors** — the finding recorded at §3.1 note 3
and M6.

**X2 — the import cycle.** In a scratch copy of the package: a
module-level `from .gates import …` in `ledger_ops.py` fails **both**
import orders with `ImportError: cannot import name 'TRACE_OUTCOMES' from
partially initialized module 'self_learn.ledger_ops' (most likely due to a
circular import)`. The deferred (function-level) arrangement succeeds in
both orders and the call path works.

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
resolved record requires that record to have a trace, and E6 measures zero
traces in the entire ledger. Hand-authoring traces for 54 resolved records
to make the fixture set exist would be fabricating the very inputs the
check exists to verify. **Disposition: the regression is a Checkpoint-A
measurement**, run after `U-composer` lands and the 12 pending records are
re-analyzed under the new doctrine — at which point it becomes a diff of
derived outcomes against accepted routings, which is what it was always
meant to be. What E6 establishes now is the *target distribution* that
diff will be scored against, and one fact worth carrying to Checkpoint C:
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
