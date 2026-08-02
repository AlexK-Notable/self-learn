# Spec — U-schema: the decision trace, its validator, quote containment, and the closed flag set

Status: **r3 — DRAFT, cleared for build** pending the coordinator's sign-off
(r1: NOT SOUND, 1 blocker + 15 folds; r2 delta: 0 blockers + 4 folds; all
20 folded — see §9). Unit `U-schema` of the r2 routing campaign
(`forward/r2-routing-campaign.md` §2, Wave 1).

**Builder's fast path:** the one section to read twice is **§3.4a** — the
`**`-aware glob matcher. It carries three corners that were each measured
wrong before being fixed (the `**` double-separator join, `^` as a literal
class member requiring an *escape*, and the two oracle preconditions), and
a literal reading of any earlier draft reproduces the original blocker.
Its criteria are **F1/F1a/F1b**; its mutations **M15/M15a–d**; its
rationale **§6-D10/D11**. Every folded finding is tagged inline as
`FOLD-n` (r1 round) or `FOLD-A/B/C/D` (delta round).

**File this unit may change: `plugins/self-learn/cli/src/self_learn/ledger_ops.py`
and one new test module.** Nothing else. `worker.py`, `analyst.py`,
`selfcheck.py`, `miner.py`, `verbs.py`, `telemetry.py` and the UI are live
in other units right now (§2) and are not touched.

**Read §2 before anything else.** `ledger_ops.py` is Wave 1's shared
dependency; the absent-is-valid seam is the whole reason this unit can ship
concurrently with four others.

---

## 0. Reading order and precedence

This document has one normative field definition (**Schema-1**, §3.1), one
normative flag set (**Set-F**, §3.2), three normative small enums (§3.3),
and one normative behaviour definition (**the acceptance criteria**, §4).

**Precedence, on conflict:**

1. The acceptance criteria (§4) and the mutation plan (§5) win over
   everything else. They are the spec; the rest is rationale.
2. Schema-1 / Set-F / §3.3 win over all prose and over the illustrative
   YAML in §3.6.
3. The illustrative YAML in §3.6 is **non-normative**. If it disagrees with
   Schema-1, the example is the bug.

**The field list appears exactly once, in Schema-1.** Nothing downstream —
not the criteria, not the mutation plan, not the builder prompt — may
re-enumerate it. Refer to legs by their Schema-1 path (`gates.t3.owner`).
A schema spec that states its field set twice will drift between the two
copies, and that is the worst artifact this unit could produce.

---

## 1. The defect

The analyst records a *verdict* (`destination`, `rationale`) and nothing
about *why*. A later reader cannot audit the reasoning; they can only agree
or disagree with the answer. Two measured consequences:

- **The reasoning is unauditable, so a monoculture is invisible.** The
  2026-07-27 audit measured **8 of 10 user-scope proposal rationales**
  carrying a variant of *"user-scope claude-md is the narrowest surface
  that still fires"*
  (`research/2026-07-27-routing-monoculture-and-pin-audit.md` §2) — a
  superlative asserted over a set of one, because
  `ui/src/self_learn_ui/models.py:101` makes the user-scope destination set
  the one-element tuple `("claude-md",)`. Nothing in the proposal file
  records which alternatives were weighed, so the uniformity reads as
  agreement rather than as a stuck gate.
  *(FOLD-9: r1 of this spec said "12 of 14 pending user/project proposals",
  a number it did not source and the audit does not support. Corrected to
  the audit's own measurement. A bullet two lines above a
  fabricated-citation argument is the last place to carry an unsourced
  count.)*
- **A justification can cite a source that does not contain it, and
  nothing catches it.** This has already happened in this corpus.
  `03-decisions.md` row **S-21** records an agent-authored pin that
  justified itself as *"the confirmed §4 human call"* — **§4 contains no
  such row** (verified with a positive control,
  `research/2026-07-27-routing-monoculture-and-pin-audit.md` §5). That pin
  then propagated into `routing-doctrine.md:262-263` and
  `08-build-plan.md:469` and made `new-skill` structurally un-approvable;
  it was used 0 times in 28 routings. A fabricated citation is not a
  hypothetical failure mode here. It is the failure mode that produced the
  audit that produced this campaign.

Today's validator has no defence against either. `validate_proposal`
(`ledger_ops.py:518-568`) checks `destination`, `rationale`, `model`,
`analyzed_at`, `alternates`, `already_canon`, `record_sha`, `contradicts`,
plus the `rules`/`lint`/`card`/`hook` blocks — every one of them a shape
check over the proposal's own bytes. **No field in the proposal is ever
checked against the record it claims to be about.**

This unit adds the trace, and makes one class of fabrication mechanically
impossible **on the paths it can reach**: a quote attributed to the record
must actually be in the record. The reach is bounded and stated rather than
implied — **enforced** on the `write_proposal` producer path and on the
eligibility path, **advisory elsewhere** (notably the worker's own
`_validate_written`, which will keep calling `validate_proposal` with one
positional argument) until a later unit wires the remaining call sites.
**§3.7 item 9 names exactly where it does not bite.**

---

## 2. The seam — absent-is-valid (Wave 1's shared dependency)

`ledger_ops.py` is imported by `worker.py`, `analyst.py`, `selfcheck.py`
and `miner.py`, all four of which are being built **concurrently with this
unit** (campaign §4a, second staging fact). Verified imports as of this
writing:

| Importer | What it imports from `ledger_ops` |
|---|---|
| `worker.py:54`, `:61-65` | `bucket_project_path`, `read_proposal`, `stamp_proposal`, `validate_proposal`, … |
| `analyst.py:57` | `ProposalError`, `validate_proposal` |
| `selfcheck.py:78-84` | `read_proposal`, `stamp_proposal`, `validate_proposal`, … |
| `miner.py:53` | `LedgerOpsError`, `create_record`, `record_title` — **none of them touched by this unit** |
| `verbs.py:102-118` | `read_proposal`, `validate_proposal`, … |
| `import_backlog.py:66` | `stamp_proposal`, `write_proposal`, … |

**The seam, stated as five obligations the builder builds toward and the
code gate tests:**

- **S1 — A proposal with no `gates:`, no `flags:` and no `recommendation:`
  validates exactly as it does today, and is indistinguishable in every
  observable (`validate_proposal` outcome, `proposal_info` dict,
  `is_unanalyzed`, `write_proposal`, `stamp_proposal`, `list --json`).**
  This is the absent-is-valid posture, mirroring `card:`
  (`ledger_ops.py:359-373`) and `lint:` (`:382-408`), and it is what makes
  the 13 pending pre-contract proposals stay routable through the
  transition (r2 §7).
- **S2 — No call site outside `ledger_ops.py` changes.** Every new
  parameter is **keyword-only with a default**, so `validate_proposal(data)`
  keeps working verbatim at `analyst.py:213`, `worker.py:908`, `:1236`,
  `selfcheck.py:145`, `verbs.py:509`, `:1098`, `:1152`. A builder who finds
  themselves editing another module has left this unit's scope and must
  stop and report instead.
- **S3 — No new module-level import is added to `ledger_ops.py`, so no
  import cycle with the four concurrent modules is possible.** Measured:
  the whole change is expressible with `re` (already imported at
  `ledger_ops.py:28`) plus names already in the file (`SHA_ANCHOR_RE`,
  `RECORD_ID_RE`, `validate_skill_name`, `ProposalError`). The glob matcher
  of §3.1-X1 needs `re` only — **not `fnmatch`, not `glob`** (§6-D10).
  *Its test is **G1***: a cycle or a missing import fails collection, so
  the suite passing at the baseline count is the machine-checkable form of
  S3. (FOLD-6: r1 asserted S3 with a headline claiming "no new import" and
  a body naming `fnmatch` as a new one. The blocker's resolution removed
  the need for either, so headline and body now agree.)
- **S4 — `validate_proposal` stays free of filesystem I/O.** It is on the
  eligibility hot path: `proposal_info` (`:1055-1058`) → `is_unanalyzed`
  (`:1063-1070`) → `list` / `status` / the worker's queue computation. Any
  I/O there is paid per queue item per render, and — worse — any file that
  can change under the validator turns an unrelated edit into a silent
  `proposal_fresh: False` and a silent re-analysis. `proposal_info`
  swallows `ProposalError` and returns "not fresh"; a check that can fail
  for environmental reasons therefore fails *invisibly*. This is why §3.5
  reads the record from memory and why §3.7 refuses to read target files at
  all in this unit.
- **S5 — `stamp_proposal` gains no new failure mode.** It is called inside
  `selfcheck.proposal_validate`'s lock block (`selfcheck.py:166-176`),
  whose `except` catches only `gitops.GitOpsError`, so a `ProposalError`
  raised there escapes the verb. **It does not become an uncaught
  traceback** — `ProposalError` subclasses `LedgerOpsError`, and
  `cli._cmd_proposal` (`cli.py:1721-1725`) catches `LedgerOpsError` and
  returns `EXIT_USAGE` (**rc=64**, `cli.py:70`). The damage is
  differently-shaped and arguably worse: a **schema** failure would be
  reported to the user as a **usage** error, breaking `proposal validate`'s
  pinned exit trio (`EXIT_VALID=0` / `EXIT_SCHEMA_INVALID=1` /
  `EXIT_SCAN_HIT=2`, `selfcheck.py:91-93`) — a wrong-category exit code is
  exactly the kind of failure that trains a human to distrust a gate.
  **This escape route is pre-existing, not created by this unit**
  (`stamp_proposal` already raises `ProposalError` at `:685`, reachable
  today via a `destination: hook` proposal on a `knowledge` record).
  **The conclusion is unchanged: the trace validator never runs from
  `stamp_proposal`.** Tested by A9.
  *(FOLD-4: r1 said "uncaught traceback". Wrong — verified at
  `cli.py:1721-1725`. The conclusion survived the correction; the reasoning
  did not, and a spec that argues from a false mechanism is one folded
  premise away from arguing the opposite.)*
- **S6 (FOLD-2) — `_validate_gates` raises `ProposalError` and nothing else, on
  every input, including malformed ones.** This is the seam's most likely
  real-world failure and it is not hypothetical: `proposal_info`
  (`:1055-1058`) catches **only** `ProposalError`, and `is_unanalyzed` and
  `queue()` catch nothing at all. A `TypeError` from indexing
  `gates: {g0: "oops"}` would surface as a traceback out of
  `self-learn list` — a trace-less user's `list` broken by a *malformed
  trace on somebody else's record in the same bucket*. **Every level must
  be type-checked before it is indexed**; no `data["gates"]["g0"]["reject"]`
  chain may run on unverified types. Tested by A7.

**S1 is a required acceptance criterion (§4 A1–A3), not a nicety.** It is
tested with a record carrying no trace at all, which must be ACCEPTED.
**S3–S6 are each machine-checkable** (G1, A8, A9, A7 respectively) — an
invariant with no test is a wish.

---

## 3. The change

Everything below lands in `ledger_ops.py`, beside `_validate_lint` and
`_validate_card`, which are the posture precedents.

### 3.1 Schema-1 — THE decision trace (the single normative field definition)

Three new **top-level** proposal keys: `gates`, `flags`, `recommendation`.
All three are **optional as a whole**; each is shape-checked strictly when
present.

`validate_proposal` does **not** reject unknown top-level keys today
(verified: `:518-568` inspects named keys only), so a proposal carrying
these keys already parses under the current CLI. This unit turns them from
*ignored* into *checked*.

**`gates` is a mapping whose key set is exactly `TRACE_GATE_KEYS` —
closed.** Unknown keys are refused (the `_validate_hook_extension`
precedent, `:449-454`); missing keys are refused.

`TRACE_GATE_KEYS = ("g0", "t1", "t2", "t3", "t3a", "t4", "tn", "e1", "outcome")`

**Schema-1a — the gate legs.**

| Path | Domain | Present / required | `evidence` | Quote source | Other required fields |
|---|---|---|---|---|---|
| `gates.g0.reject.answer` | `"yes"` \| `"no"` | always | required iff `yes` | RECORD | — |
| `gates.g0.defer.answer` | `"yes"` \| `"no"` | always | required iff `yes` | RECORD | — |
| `gates.g0.canon.answer` | `"yes"` \| `"no"` | always | required iff `yes` | **TARGET** | `gates.g0.canon.target` — non-empty str, required iff `yes` |
| `gates.t1.attempted` | `bool` | always | — | — | — |
| `gates.t1.field_shaped.answer` | `"yes"` \| `"no"` | always | **required both ways** | RECORD | — |
| `gates.t1.separable.answer` | `"yes"` \| `"no"` \| `null` | always (mapping); answer may be `null` | optional | RECORD | — |
| `gates.t1.cost_bearing.answer` | `"yes"` \| `"no"` \| `null` | always (mapping); answer may be `null` | required iff `yes` | RECORD | — |
| `gates.t2.answer` | `"yes"` \| `"no"` | always | **required both ways** | RECORD | `gates.t2.match_path` — non-empty str, required iff `yes` |
| `gates.t3.answer` | `"yes"` \| `"no"` | always | — | — | `owner` (non-empty str) required iff `yes`, else `null`; `scan_terms` (non-empty list of non-empty str) required iff `no`, else `null`; `roster_sha` always required |
| `gates.t3.roster_sha` | `sha256:<12 hex>` (matches `SHA_ANCHOR_RE`) \| the literal `"unavailable"` | always | — | — | see cross-check X3 |
| `gates.t3a` | mapping \| `null` | **non-null iff `gates.t3.answer == "yes"`** | — | — | — |
| `gates.t3a.depth_behind_rule.answer` | `"yes"` \| `"no"` | when `t3a` non-null | required iff `yes` | **TARGET** | `target` — non-empty str, required iff `yes` |
| `gates.t3a.fs.verdict` | `TRACE_FS_VERDICTS` | when `t3a` non-null | **required unless verdict is `INDETERMINATE`** | RECORD | — |
| `gates.t4` | mapping \| `null` | **must be `null`** when `t2.answer == "yes"` or `tn.answer == "yes"`; **must be non-null** when `t2.answer == "no"` and `t3.answer == "no"` and `tn.answer != "yes"`; **either** otherwise (see D5) | — | — | — |
| `gates.t4.depth_behind_rule.answer` | `"yes"` \| `"no"` | when `t4` non-null | required iff `yes` | **TARGET** | `target` — non-empty str, required iff `yes` |
| `gates.t4.conduct_mode.answer` | `"yes"` \| `"no"` | when `t4` non-null | required iff `yes` | RECORD | — |
| `gates.t4.fs.verdict` | `TRACE_FS_VERDICTS` | when `t4` non-null | **required unless verdict is `INDETERMINATE`** | RECORD | — |
| `gates.tn.answer` | `"yes"` \| `"no"` \| `"indeterminate"` | always | — | — | — |
| `gates.tn.terms` | list of non-empty str (may be empty) | always | — | — | — |
| `gates.tn.members` | list of ids matching `RECORD_ID_RE` | always | — | — | **≥2 iff `yes`; ≤1 iff `no`; unconstrained iff `indeterminate`** |
| `gates.tn.proposed_name` | kebab slug (`validate_skill_name`) \| `null` | always | — | — | required iff `yes`; must be `null` otherwise |
| `gates.e1.sightings` | `int`, ≥ 1 | always | — | — | — |
| `gates.e1.post_demand_recurrence` | `bool` | always | — | — | — |
| `gates.outcome` | `TRACE_OUTCOMES` | always | — | — | — |

Every `evidence` field, wherever it appears above, is a **non-empty string**
whose flattened form (§3.4) is at least `_QUOTE_MIN_CHARS` characters, or
`null` where the table permits absence. `null` and `""` are both "absent";
`""` is refused wherever evidence is required.

**Schema-1b — the top-level keys.**

| Key | Domain | Notes |
|---|---|---|
| `gates` | mapping over `TRACE_GATE_KEYS`, or absent | absent = valid (S1) |
| `flags` | list of values from **Set-F** (§3.2), possibly empty, no duplicates, or absent | absent = valid |
| `recommendation` | one of **Set-R** (§3.3), or absent | absent = valid; absent **means** `route` to consumers. **The validator does not insert a default** — validators do not mutate. |

**Three intra-trace cross-checks** (all pure — no I/O, no record, no other
file; they are part of Schema-1's meaning, not a separate feature):

- **X1 — `t2` positive control.** When `gates.t2.answer == "yes"`, the
  proposal must carry a non-empty `rules_paths`, and `_glob_match(match_path, p)`
  (§3.4a) must be true for at least one `p in rules_paths`. Rationale:
  `match_path`'s entire semantic content is "a path the globs I proposed
  actually match". Without globs the field cannot be checked at all, so
  requiring them is a *shape* requirement of the trace, not a rendering
  rule — and it is what stops the check passing vacuously.
- **X2 — `tn.proposed_name` well-formedness.** Reuse
  `validate_skill_name` (already imported at `ledger_ops.py:42`), and
  re-raise its `SkillScaffoldError` as a `ProposalError` naming the field —
  the `_validate_rules_fields` precedent at `:597-606`.
- **X3 — roster honesty.** When `gates.t3.roster_sha == "unavailable"`,
  then `gates.t3.answer` must be `"no"` **and** `flags` must contain
  `evidence-gap`. This is r2 §2's T3 degradation rule made mechanical: the
  model may not claim a roster judgment it had no roster for, and the
  admission must be visible on the card. It is also the one place the
  closed flag set does work rather than merely existing.

### 3.2 Set-F — the closed flag set (single normative definition)

```
TRACE_FLAGS = (
    "near-cluster",
    "cluster-indeterminate",
    "evidence-gap",
    "rehome-suggested",
    "no-cheap-surface",
    "scope-mismatch",
    "consider-local",
    "pathed-unbuilt",
)
```

Eight values. **This set is the single definition; no other module,
document or test may re-list it** — tests iterate `TRACE_FLAGS`, they do not
hardcode members.

`pathed-unbuilt` is present because **r2 contradicts itself**: §1.2 lists
seven flags and omits it, while §1.6's transition rule *requires* emitting
`flags: [pathed-unbuilt]` for a PATHED outcome before B10 lands. A closed
set that cannot express a value the design mandates is not closed, it is
broken. Resolved here in favour of §1.6 (the rule that has to run). See
§8-C1.

### 3.3 Set-R, Set-O, Set-V — the three small enums

```
TRACE_RECOMMENDATIONS = ("route", "reject", "defer", "graduate")           # Set-R
TRACE_OUTCOMES = ("HOOK", "ALWAYS", "PATHED", "SKILL", "DEMAND",
                  "NEW_SKILL", "REJECT", "DEFER", "GRADUATE")               # Set-O
TRACE_FS_VERDICTS = ("SILENT", "COSTLY", "LOUD_CHEAP", "INDETERMINATE")     # Set-V
```

All four constants (Set-F + these three) are exported in `__all__`.

**Set-O is defined here, not in `gates.py`.** r2 §1.5 sketches a `CLS`
tuple inside the future `gates.py` module (unit `U-table`). Two definitions
of the same nine-member set in two modules is precisely the drift this
spec exists to prevent, and the validator needs the set *now* while
`gates.py` does not exist yet. **Obligation handed to `U-table`: import
`TRACE_OUTCOMES` from `ledger_ops`; do not redefine `CLS`.** (§8-O1.)

### 3.4 Quote containment — what it checks, and what it deliberately does not

**The rule.** An `evidence` string whose Schema-1 quote source is RECORD
must be a **flattened substring** of the record's full file text
(frontmatter + body).

**Flattening** is `_flatten_quote(text)`: collapse every run of whitespace
(including newlines) to a single space, then strip. Applied to *both* the
quote and the source before the substring test.

- This is deliberately **not** `normalize.normalize_body`. That function is
  the project's single *hashing* normalization (`normalize.py` module
  docstring: "Never define a second normalization") and it is line-based —
  it strips per-line trailing whitespace but preserves interior newlines
  and indentation, because a hash must be stable, not forgiving. A quote
  copied out of a wrapped record body and re-wrapped by the model would
  fail a `normalize_body` substring test even though it is a true quote —
  a validator that refuses honest evidence is worse than no validator.
  `_flatten_quote` is a *comparison* normalization, is used for no hash,
  and does not violate that pin. **Stated explicitly so no reviewer reads
  it as a violation and no later agent "fixes" it by switching to
  `normalize_body`.**
- Quote sources include the **frontmatter**, not just the body: r2 §3
  requires `COSTLY` to quote `incident_cost`, which is a frontmatter field
  (`records.py`). The source is `Record.to_text()`, which is
  frontmatter + body.

**`_QUOTE_MIN_CHARS = 8`**, measured on the flattened quote. A one- or
two-character "quote" is contained in every record, so a containment check
with no minimum passes for the wrong reason on any input — the exact shape
this project's audit keeps finding. 8 is calibrated on the *shortest* marker
in r2 §3's own silence lexicon, `"no error"` (8 characters), so the floor
cannot refuse a marker the doctrine tells the model to look for. (§6-D6.)

**The boundary — say this out loud, it is not a defect.**

> **The validator checks reality, not relevance.** It answers "does this
> text exist in the source it names?" — nothing more. A quote that is real
> but describes a *different* aspect of the record than the claim it
> supports will pass. Judging whether a true quote actually supports the
> verdict is **the human's glance at the card**, and it is a deliberate,
> already-recorded acceptance (campaign §7, r2 §8 item 7:
> *"the validator checks containment, not relevance. Relevance is the
> human's five-second check on the card"*). This is a ratified residual,
> **not an open bug and not a gap for a later agent to close**. Anyone who
> "fixes" it is either re-litigating an accepted decision or building
> substring-semantics that will misfire.
>
> The obligation this creates lands elsewhere and is named here so it is
> not lost: **the review card must surface the quote verbatim**, or the
> human's check has nothing to look at. That is a UI obligation, out of
> scope for this unit (§7).

### 3.4a `_glob_match` — the pure `**`-aware matcher X1 uses

*(This section resolves r1's BLOCKER. r1 specified `fnmatch.fnmatch` for
X1, which is wrong and would have shipped criterion F1 **red on
arrival**.)*

**The defect in r1, measured on this venv:** `fnmatch.translate('src/**/*.py')`
compiles to `(?s:src/(?>.*?/).*\.py)\Z`. The `(?>.*?/)` requires **one or
more** directory levels, so `fnmatch.fnmatch('src/app.py', 'src/**/*.py')`
is `False` — while `glob.glob('src/**/*.py', root_dir=…, recursive=True)`
returns `['src/a/b/deep.py', 'src/app.py']`. `**/` in `glob` matches **zero
or more** levels. r1's X1 was therefore *stricter* than the route-time
check at `verbs.py:695-699`, which uses `glob(..., recursive=True)`.

**Why the looser rule is right, not merely convenient.** A validator that
refuses honest evidence the route verb accepts is the same failure §3.4
argues against for `normalize_body`: a false refusal blocks a real routing
and trains the human to distrust the gate, while the containment check's
actual quarry — a glob/path pair that does not correspond at all — is
unaffected by directory depth. Aligning with the route verb is also the
only rule that keeps **one** meaning of "this glob matches this path" in
the system.

**The mechanism, pinned so the builder does not re-derive it.** A
hand-rolled translator, ~20 lines, in `ledger_ops.py`, using `re` only:

- split the pattern on `/`;
- a `**` segment becomes `(?:[^/]+/)*` when non-final (**zero** or more
  levels) and `.*` when final. **The non-final form already carries its own
  trailing separator, so no `/` is emitted after it when segments are
  joined** — emitting one yields `src/(?:[^/]+/)*/[^/]*\.py`, which demands
  a literal `/` a zero-level path does not have and **reproduces the exact
  `fnmatch` defect this section exists to fix**. Measured under the
  double-separator join: `_glob_match("src/app.py", "src/**/*.py")` is
  `False` — and so is `_glob_match("src/a/b/deep.py", "src/**/*.py")`, so
  the mis-join breaks the multi-level case too; *(FOLD-A — r1's recipe
  said "join with `/`" immediately after a form that already ends in `/`,
  so a builder following it literally reproduced the blocker. F1a catches
  it, but "pinned so the builder does not re-derive it" was not true as
  written.)*
- any other segment is translated character-by-character — `*` → `[^/]*`,
  `?` → `[^/]`, `[...]` → a passed-through character class, an
  **unbalanced `[` → an escaped literal, never an exception**; everything
  else `re.escape`d;
- **only a leading `!` negates a character class. A leading `^` is a
  literal member of the class** — and because Python's `re` uses `^` for
  negation, **a leading `^` must be actively escaped to `\^`; leaving it
  un-rewritten is not enough.** Measured: `fnmatch.translate("[^a]bc")` →
  `(?s:[\^a]bc)\Z` versus `fnmatch.translate("[!a]bc")` → `(?s:[^a]bc)\Z`,
  and `fnmatch("abc", "[^a]bc")` is `True`. So `src/[^a]*.py` must compile
  to `src/[\^a][^/]*\.py` and match `src/app.py`, `src/a.b.py` and
  `src/^caret.py`. Translating `^` as negation makes `_glob_match`
  **refuse** paths `glob` accepts — the blocker's false-refusal failure,
  reintroduced by its own fix; *(FOLD-B. **Refinement beyond the ruling,
  found by implementing it:** simply "not rewriting `!`→`^`" still leaves
  the literal `^` in the class body, which `re` then reads as a negation —
  measured, `src/[^a]*.py` still mismatched `glob` after that partial fix.
  The escape is the actual requirement.)*
- join the pieces with `/` **only between segments that do not already
  supply one** (see the `**` bullet), wrap as `(?s:…)\Z`, `re.compile`.

**Do NOT use `glob.translate()` or `PurePath.full_match()`.** Both produce
correct semantics and both are **Python 3.13 additions**, while
`plugins/self-learn/cli/pyproject.toml:5` declares
`requires-python = ">=3.11"`. The dev venv is 3.13.11, so either would pass
every test here and break on a 3.11/3.12 install — a green suite hiding a
portability defect, which is this project's signature bug wearing a
different hat. (This is why the coordinator's instruction was to *verify*
the mechanism against the project's Python rather than assume a recent
stdlib addition is available. It is not.)

**Do NOT use `fnmatch` or `glob` at all**, which is also what keeps S3's
"no new import" true: `re` is already imported at `ledger_ops.py:28`.

**Verified equivalence — and its two preconditions, which are part of the
claim.** *(FOLD-C: r1 reported "0 mismatches over 13 patterns" with both
preconditions unstated. Re-measured under the **default** oracle
(`include_hidden=False`, files **and** directories), **7 of 13 patterns
mismatch**. The number was true only of an oracle r1 never named.)*

The translator was run against real
`glob.glob(pat, root_dir=…, recursive=True, include_hidden=True)` over a
scratch tree, compared on the tree's **files only**, across **13
patterns** — `src/**/*.py`, `**/*.py`, `src/*.py`, `docs/**/*.md`, `*.py`,
`src/**`, `**`, `src/a?b.py`, `src/[ab]*.py`, `src/[!a]*.py`,
`src/[^a]*.py`, `src/[weird].py`, `src/unbal[.py` — over a tree containing
dotfiles (`src/.secret.py`, `.claude/rules.md`), a `[`-bearing name
(`src/unbal[.py`) and a `^`-bearing name (`src/^caret.py`):
**0 mismatches**. Both preconditions are load-bearing:

1. **`include_hidden=True`.** `glob`'s default refuses to let a wildcard
   segment match a leading-`.` name. `_glob_match` implements the
   `include_hidden=True` semantics deliberately: **a pure string relation
   has no business hiding dotfiles**, and this project's subject matter is
   `~/.claude/`, `.storage/`, `.config/` — a matcher that silently skipped
   them would be wrong in the one domain it is used in. §6-D11 already
   named `include_hidden=True` as the 3.13-equivalent, so r1's §3.4a and
   D11 were **contradicting each other**; they now agree.
2. **Files, not directories.** `glob.glob("src/**", recursive=True)` also
   returns `src/`, `src/a`, `src/a/b` — the directories themselves —
   which `_glob_match("src", "src/**")` refuses. `match_path` names a
   file, so the files-only comparison is the meaningful one.

**The divergence direction is `false accept`, never `false refusal`**, in
both cases: `_glob_match` accepts a superset of what default-`glob`
accepts. That is the safe direction here — X1 is a positive control on the
analyst's own claim, and `verbs.py`'s route-time zero-match refusal
remains the stricter gate that actually touches the host tree. **Chosen
out loud rather than inherited**: a false *refusal* is the failure this
whole section exists to prevent.

Also measured, and relevant to §8-N1: both `glob` and `fnmatch` degrade an
unbalanced `[` to a **matching** literal (`glob.glob('src/unbal[.py')`
returns the file), so an "unparseable" pattern folds into **match**, not
zero-match — the opposite of what `verbs.py`'s own docstring claims.

**The boundary — state it so nobody "aligns" the two in the wrong
direction.** `_glob_match` is a **pure string relation**: two strings in,
a bool out, no filesystem, no `root_dir`, no cwd. It matches `glob` on
`**` semantics and on nothing else. In particular it does **not** inherit
`glob`'s absolute-path behaviour, where
`glob.glob("/etc/host*", root_dir=<elsewhere>)` returns `/etc/hosts`
because `glob` **ignores `root_dir` for absolute patterns** — a
**fail-open in the route-time check at `verbs.py:675-710`**, found by a
sibling unit. `_glob_match` cannot have that bug, having no root concept.
**If these two are ever reconciled, the direction is to fix `verbs.py`,
never to teach the validator to ignore its input.** (§8-O6.)

### 3.5 Where the validator runs — three call sites, all inside `ledger_ops.py`

The trace validator is a private `_validate_gates(data, *, record_text=None)`
called from `validate_proposal`, in the same position `_validate_lint` and
`_validate_card` occupy (`:566-568`). Containment runs **iff `record_text`
is supplied**; shape, enums, required-ness and the closed sets always run.

That immediately raises the question this project keeps getting wrong: *if
nothing supplies `record_text`, is the check decoration?* It would be.
So two call sites inside this file supply it, and **the criteria assert
that they do** (§4 E6, E7) rather than only asserting the validator's own
behaviour — the `--json`-argv lesson from `commit-drift-evidence-spec.md`
§2.1, where `FakeRunner` ignored argv and a green test rode a broken build.

| Call site | Line today | Change | Why it is the right site |
|---|---|---|---|
| `validate_proposal` | `:518` | gains `*, record_text: str \| None = None`; passes it to `_validate_gates` | keyword-only default keeps S2 |
| `write_proposal` | `:658-665` | resolve `find_record_path` **before** validating; when `data.get("gates") is not None`, pass `record_text=Record.from_path(record_path).to_text()` | already has `home` + `record_id`; the producer path used by `import_backlog.py:267` and the sandbox tooling |
| `proposal_info` | `:1055-1058` | when `data.get("gates") is not None`, pass `record_text=entry.record.to_text()` | `entry.record` is **already in memory** (`queue()` loaded it) — no new I/O, satisfying S4. This is the site that makes containment unavoidable: a fabricated quote makes the proposal schema-invalid → `proposal_fresh: False` → `is_unanalyzed: True` → the worker re-analyzes it. |

**The `data.get("gates") is not None` guard is load-bearing for cost, not
for correctness**: it keeps `to_text()` (a ruamel re-dump) off the path for
every trace-less proposal, which today is all of them. It must not be
weakened into "skip containment when convenient" — mutation M2 tests
exactly that.

**Consequence worth stating:** containment failure is a *subset* of
staleness in practice, because a record edited after analysis already fails
the `record_sha` check at `:1059`. The only proposals this newly marks
unfresh are ones whose quotes were never in the record — which is the
intended effect.

### 3.6 Illustrative shape — NON-NORMATIVE

If this disagrees with Schema-1, Schema-1 wins and this example is the bug.

```yaml
# proposals/lrn-aa000001.yaml — the three new top-level keys
recommendation: route
flags: [evidence-gap]
gates:
  g0:
    reject: {answer: "no", evidence: null}
    defer:  {answer: "no", evidence: null}
    canon:  {answer: "no", evidence: null, target: null}
  t1:
    attempted: true
    field_shaped: {answer: "no", evidence: "the mistake is a routing choice, not a tool call"}
    separable:    {answer: null, evidence: null}
    cost_bearing: {answer: null, evidence: null}
  t2:
    answer: "no"
    evidence: "record names no paths"
    match_path: null
  t3:
    answer: "no"
    owner: null
    scan_terms: [guard, invariant, lint]
    roster_sha: "sha256:0a1b2c3d4e5f"
  t3a: null
  t4:
    depth_behind_rule: {answer: "no", evidence: null, target: null}
    conduct_mode:      {answer: "no", evidence: null}
    fs: {verdict: INDETERMINATE, evidence: null}
  tn:
    answer: "no"
    terms: []
    members: []
    proposed_name: null
  e1:
    sightings: 1
    post_demand_recurrence: false
  outcome: DEMAND
```

**YAML scalar pin, verified empirically this session** against this
project's own loader (`ledger_ops._yaml()`, ruamel `typ="rt"`):
unquoted `yes` / `no` / `y` / `n` load as the **strings** `'yes'`, `'no'`,
`'y'`, `'n'` — ruamel defaults to YAML 1.2, where only `true`/`false` are
booleans — and round-trip unquoted. So `answer: no` is the string `"no"`,
not `False`, and comparing against `"no"` is correct. Criterion A6 pins
this with a test so a future loader-version change cannot flip every
answer to a boolean silently.

### 3.7 What this unit deliberately does NOT check

Each of these is a decision with a reason, not an omission. **None of them
is a defect to be found at the gate.**

1. **TARGET-sourced quotes are not contained against the target file.**
   Schema-1 *requires* the `target:` path alongside every TARGET quote, so
   the input for the check is recorded from day one — but the check itself
   does not run here. Three reasons, in order of weight:
   (a) it needs filesystem I/O, and the only enforcement sites available
   to this unit are on the eligibility hot path (S4);
   (b) canon files are **mutable for reasons unrelated to the record**, so
   a proposal that validated yesterday would become invalid today and be
   silently re-queued through `proposal_info`'s swallowed `ProposalError` —
   an unrelated edit causing an invisible re-analysis storm is a worse
   failure than the one being prevented;
   (c) resolving a target properly means `verbs.py::_resolve_target`, which
   is live in `U-demand-user`.
   **Honest consequence, stated rather than buried: the S-21 flavour of
   fabrication — a citation against a *document* — is only partially
   closed by this unit.** Every leg whose Schema-1 "Quote source" column
   reads RECORD is closed; the three whose column reads **TARGET** —
   `gates.g0.canon`, `gates.t3a.depth_behind_rule`,
   `gates.t4.depth_behind_rule` — are not. **Read the count off Schema-1's
   column; do not restate it here.**
   *(FOLD-10: r1 said "8 of the 11 evidence legs". Both numbers were
   wrong — Schema-1 defines 12 evidence-bearing legs, 9 RECORD and 3
   TARGET — and the sentence was a second enumeration of Schema-1 that had
   already drifted from it inside a single revision. Exactly the failure
   §0 forbids, committed by the document that forbids it. The fix is not a
   corrected number; it is no number.)*
2. **Outcome derivation is not recomputed.** `gates.outcome` is enum-checked
   only. Recompute-and-refuse is `U-table`'s `gates.py` (campaign §2), which
   must not be built here.
3. **The outcome → `destination`/`variant`/`recommendation` rendering map
   (r2 §1.6) is not enforced.** `U-table`.
4. **`e1.sightings` is not cross-checked against the record's `sightings`.**
   Shape only. It is a record cross-check of the same class as containment
   and would ride the same seam cheaply — it is excluded to keep this unit
   at four pieces, per campaign §9's "a unit absorbing an adjacent feature".
   `U-table` or a later unit.
5. **`tn.members` existence is not probed in the ledger.** Shape only
   (`RECORD_ID_RE`); existence needs bucket probes, i.e. I/O (S4).
6. **`t3.roster_sha` is not compared against a CLI-composed roster.** No
   roster composer exists yet — that is `U-composer`'s B6. X3 enforces the
   only part checkable today.
7. **`t1` ⇔ `_validate_hook_extension` consistency is not enforced**
   (r2 §1.4 item 5). It is a statement about *rendering* (destination `hook`
   ⇔ t1 legs all yes), i.e. `U-table`.
8. **`e1.post_demand_recurrence: true` is not cross-checked against
   `recurrences[]`.** Needs record history plus prior-routing analysis; and
   per r2 §8 item 5 it is `false` on every record in the corpus today.
9. **Containment does not bite on the worker or route call sites — the
   enforcement surface is narrower than "the validator checks quotes"
   suggests.** *(FOLD-11.)* `worker.py:908` (`_validate_written`) and
   `verbs.py:509` (`_resolve_destination`) both call
   `validate_proposal(data)` with one positional argument and will keep
   doing so, because S2 forbids touching those files. **Concretely: a
   worker-authored proposal carrying a fabricated quote is written to disk
   and kept, and a human can route it by hand.** What it will *not* do is
   read as analyzed — `proposal_info` re-validates with the record text
   (§3.5), so the record stays in the unanalyzed queue and gets
   re-proposed. So the fabrication is *contained and re-worked*, not
   *rejected at the door*, on the campaign's primary execution path.
   Closing it is a one-line change at each site, owned by whichever unit
   next holds those files (§8-O7). **This is stated here because the rest
   of this spec claims a standard of disclosure it would otherwise fail.**

---

## 4. Acceptance criteria

**These, plus §5, are the spec.** Every test named here lives in the new
module `plugins/self-learn/cli/tests/test_decision_trace.py` (§6-D1).

**Standing rule for this unit — the discriminating twin.** Every criterion
that asserts a REFUSAL must be accompanied by an acceptance of the
minimally-different valid input. A validator that refuses everything
satisfies a refusal-only test suite, and this project has shipped
assertions that passed for the wrong reason more often than any other bug.
Where a criterion below names a refusal without naming its twin, the twin
is still required.

### A. Absent-is-valid — the seam (S1)

- **A1** `test_traceless_proposal_validates_unchanged` — `proposal_dict()`
  (`tests/support.py:234`, carrying no `gates`/`flags`/`recommendation`)
  passes `validate_proposal`, and passes it identically with
  `record_text=` supplied and with it omitted. *(This is the mandated
  third positive control: a record with no trace at all is ACCEPTED.)*
- **A2** `test_traceless_proposal_stays_fresh_and_analyzed` — a real
  record + trace-less proposal written via `write_proposal` and stamped via
  `stamp_proposal` yields `proposal_info(entry)["proposal_fresh"] is True`
  and `is_unanalyzed(entry) is False`.
- **A3** `test_traceless_hook_and_rules_proposals_unchanged` — the
  `hook`-destination proposal (`support.hook_proposal_fields`) and a
  `variant: rules` proposal both still validate, proving `_validate_gates`
  did not disturb `_validate_hook_extension` or `_validate_rules_fields`.
- **A4** `test_validate_proposal_signature_is_backward_compatible` — the
  new parameters are keyword-only with defaults; asserted structurally via
  `inspect.signature` (`kind is KEYWORD_ONLY`, `default is None`), so the
  seam cannot be broken by a later positional-arg refactor without a red
  test. This is the machine-checkable form of S2.
- **A5** `test_flags_and_recommendation_absent_are_valid` — each of the
  three keys absent independently and together.
- **A6** `test_yes_no_scalars_round_trip_as_strings` — a trace dumped and
  reloaded through `_dump_yaml` / `_load_yaml_map` keeps
  `gates.g0.reject.answer == "no"` as a `str`, and the reloaded mapping
  still validates. Pins §3.6's verified YAML-1.2 behaviour.
- **A7** `test_malformed_trace_shapes_raise_only_proposal_error` — **the
  S6 test, and the seam's most likely real-world failure.** A
  parameterized sweep, each case asserting `pytest.raises(ProposalError)`
  and **never** a bare `except Exception`: `gates: "oops"` ·
  `gates: {g0: "oops"}` · `gates: [...]` (a list) · a `t1: null` where a
  mapping is required · `flags: "near-cluster"` (a bare string, which is
  iterable and would otherwise validate character by character) ·
  `recommendation: []` · an `int` where an `evidence` string is required ·
  `t3.scan_terms: "guard"` · `tn.members: "lrn-aa000001"`. A `TypeError`
  or `KeyError` escaping any case is a failure, because
  `proposal_info` catches only `ProposalError` and `queue()` catches
  nothing — the symptom is `self-learn list` traceback-ing on somebody
  else's malformed record.
- **A8** `test_validate_proposal_performs_no_filesystem_io` — **the S4
  test.** Monkeypatch `Path.read_text`, `Path.open` and `builtins.open` to
  raise, then call `validate_proposal` on a **full, valid** trace with
  `record_text=` supplied: it must pass. **Paired in the same test** with
  a fabricated quote under the same monkeypatch, which must still raise
  `ProposalError` — without that half the test would also pass on a build
  where the containment check is never reached, which is precisely the
  fail-open shape §5 audits for.
- **A9** `test_stamp_proposal_does_not_validate_the_trace` — **the S5
  test.** Write a proposal carrying a **fabricated** quote straight to disk
  (bypassing `write_proposal`), then call `stamp_proposal`: it **succeeds**
  and stamps `record_sha`. Guards the deliberate choice not to run the
  trace validator from `stamp_proposal`, whose escape would surface as
  rc=64 `EXIT_USAGE` from `proposal validate` instead of the pinned
  `EXIT_SCHEMA_INVALID` (§2 S5).

### B. The closed flag set (Set-F)

- **B1** `test_flag_outside_closed_set_refused` — `flags: ["invented"]`
  raises `ProposalError`. *(Mandated positive control 2: a value outside
  the set is REJECTED.)*
- **B2** `test_every_flag_in_the_closed_set_is_accepted` — the twin.
  Three parts, and **all three are required**:
  (a) iterate `TRACE_FLAGS` (never a hardcoded copy) and validate each —
  this proves B1 discriminates rather than refusing all lists;
  (b) `assert len(TRACE_FLAGS) == 8`;
  (c) `assert "pathed-unbuilt" in TRACE_FLAGS`.
  *(FOLD-1: with (a) alone the mutation "delete a member from
  `TRACE_FLAGS`" leaves the test **green**, because an iterating test
  iterates whatever survives — a closed set with no membership assertion
  is not pinned at all. (b) is the count guard. (c) names one member **by
  exception**: `pathed-unbuilt`'s membership **is** the resolution of C1,
  so asserting it is a reference to Set-F's decision, not a second
  enumeration of Set-F. No other member may be named here.)*
- **B3** `test_flags_shape` — non-list refused; non-string member refused;
  empty-string member refused; duplicate member refused; `[]` accepted.

### C. `recommendation` (Set-R)

- **C1** `test_recommendation_outside_enum_refused` — `"maybe"` raises.
- **C2** `test_each_recommendation_value_accepted` — the twin; iterates
  `TRACE_RECOMMENDATIONS`.
- **C3** `test_recommendation_absent_is_not_defaulted` — with the key
  absent, `validate_proposal` passes and **the input mapping is not
  mutated** (`"recommendation" not in data` after the call). Validators do
  not write.

### D. Trace shape, enums, required-ness (Schema-1)

- **D1** `test_unknown_gate_key_refused` / `test_missing_gate_key_refused`
  — `TRACE_GATE_KEYS` is closed in both directions; the error message names
  the offending key(s).
- **D2** `test_outcome_outside_enum_refused` + twin iterating
  `TRACE_OUTCOMES`.
- **D3** `test_fs_verdict_enum_and_evidence_rule` — a verdict outside
  `TRACE_FS_VERDICTS` refused; **every member of `TRACE_FS_VERDICTS` other
  than `"INDETERMINATE"`, obtained by iterating the tuple**, refused with
  `evidence: null` and accepted with a true quote; `INDETERMINATE` accepted
  both with `evidence: null` and with a true quote. Covers both `t3a.fs`
  and `t4.fs`. *(FOLD-15: r1 listed `SILENT`/`COSTLY`/`LOUD_CHEAP`
  inline — a partial re-enumeration of Set-V that would silently stop
  covering a fourth non-indeterminate verdict if one were ever added.
  Iterate the tuple and subtract the one exception; the exception is the
  rule's content, the members are not.)*
- **D4** `test_field_shaped_requires_evidence_both_ways` — `answer: "no"`
  with no evidence refused (this is the leg r2 singles out as required in
  *both* directions), `answer: "yes"` with no evidence refused, both
  accepted with a true quote.
- **D5** `test_canon_yes_requires_target_and_evidence` — `g0.canon.answer:
  "yes"` without `target` refused; without `evidence` refused; with both
  accepted. Same for `t3a.depth_behind_rule` and `t4.depth_behind_rule`.
- **D6** `test_t3a_presence_follows_t3_answer` — `t3.answer == "yes"` with
  `t3a: null` refused; `t3.answer == "no"` with a populated `t3a` refused;
  both matched shapes accepted.
- **D7** `test_t4_presence_rules` — `t4` non-null when `t2.answer == "yes"`
  refused; non-null when `tn.answer == "yes"` refused; `t4: null` when
  `t2=="no"` and `t3=="no"` and `tn != "yes"` refused; and — the case the
  scope-freedom decision creates (§6-D5) — `t4: null` **accepted** when
  `t3.answer == "yes"`, and a populated `t4` also accepted there.
- **D8** `test_tn_member_and_name_rules` — `answer: "yes"` with 1 member
  refused; with 2 accepted; `answer: "no"` with 2 members refused, with 1
  and with 0 accepted; `answer: "indeterminate"` with 3 accepted; a member
  id not matching `RECORD_ID_RE` refused; `answer: "yes"` with
  `proposed_name: null` refused; with `"Not Kebab"` refused; with
  `"link-checker"` accepted; `answer: "no"` with a non-null
  `proposed_name` refused.
- **D9** `test_e1_shape` — `sightings` non-int refused, `0` refused, `1`
  accepted; **`sightings: true` refused**; `post_demand_recurrence`
  non-bool refused, and `post_demand_recurrence: 1` refused.
  *(FOLD-14: `isinstance(True, int)` is `True` in Python — `bool`
  subclasses `int` — so a naive `isinstance(sightings, int)` accepts
  `true`, and `true >= 1` is also `True`, so even the range check passes.
  The guard must be `isinstance(v, int) and not isinstance(v, bool)`. The
  mirror case is a `post_demand_recurrence: 1` that a naive truthiness
  check would accept. Both directions are tested because the type
  confusion runs both ways.)*
- **D10** `test_t1_attempted_must_be_bool` — the string `"true"` refused,
  `True` accepted. (`t1.attempted` is the one genuinely boolean answer in
  the trace; a string here would silently read as truthy in any consumer.)

### E. Quote containment — the discriminator

- **E1** `test_true_record_quote_accepted` — a quote copied verbatim out
  of the fixture record's body validates when `record_text` is supplied.
- **E2** `test_fabricated_record_quote_refused` — **the mandated positive
  control 1.** A quote that appears nowhere in the record —
  `"the compiler writes uppercase markers"` against a record that says no
  such thing — raises `ProposalError`, and the message names the gate leg
  and echoes the quote. E1 is its twin: without E1 passing, E2 proves only
  that the validator refuses.
- **E3** `test_quote_matches_across_a_line_wrap` — a quote whose source
  spans a newline in the record body, re-wrapped with a single space in the
  proposal, is ACCEPTED. Proves `_flatten_quote` collapses rather than
  merely trimming, and guards against a "fix" that swaps in
  `normalize_body`.
- **E4** `test_quote_from_frontmatter_accepted` — a `COSTLY` verdict
  quoting the record's `incident_cost` frontmatter value validates. Proves
  the source is `to_text()`, not `body`.
- **E5** `test_quote_below_minimum_length_refused` — two fixtures, both
  required:
  (a) a 3-character quote that *is* a substring of the record — refused;
  (b) **the whitespace twin `"   the   "`** — raw length 9, flattened
  length 3, and a genuine substring of the record — **also refused**, and
  a legitimate 8-character quote accepted.
  The message names `_QUOTE_MIN_CHARS`.
  *(FOLD-7, the reviewer's unsuggested mutation: with (a) alone the test
  cannot tell whether the floor is measured on the raw or the flattened
  quote — the 3-char fixture is refused under either. (b) is the only
  fixture that discriminates, and §3.4 specifies the flattened
  measurement. A test that passes under both readings of the rule it
  guards has not pinned the rule.)*
- **E6** `test_write_proposal_supplies_record_text` — the **caller-wiring**
  test on the producer path: `write_proposal(home, rid, <trace with a
  fabricated quote>)` raises `ProposalError`, and the same proposal with a
  true quote is written successfully. Asserts the call site, not just the
  validator.
- **E7** `test_fabricated_quote_makes_proposal_unfresh` — the
  **caller-wiring** test on the eligibility path. Write a valid proposal,
  stamp it, assert `is_unanalyzed(entry) is False`; then rewrite the
  proposal's YAML on disk with a fabricated quote (bypassing
  `write_proposal`, as the worker's model does) and assert
  `is_unanalyzed(entry) is True` while `proposal_info(entry)["has_proposal"]
  is True`. **Its twin is mandatory in the same test**: the identical
  rewrite carrying a *true* quote must leave `is_unanalyzed` `False` —
  otherwise "unfresh" could be caused by the rewrite itself (a changed
  `record_sha`, a YAML shape slip) rather than by containment, and the test
  would pass for the wrong reason.

### F. Intra-trace cross-checks

- **F1** `test_t2_match_path_must_match_a_proposed_glob` —
  `match_path: "src/app.py"` with `rules_paths: ["docs/**/*.md"]` refused;
  with `rules_paths: ["src/**/*.py"]` **accepted**; with
  `["docs/**/*.md", "src/**/*.py"]` accepted (any one glob suffices).
- **F1a** `test_double_star_matches_zero_directory_levels` — **the case
  the blocker turns on.** `_glob_match("src/app.py", "src/**/*.py")` is
  `True`, and so is `_glob_match("src/a/b/deep.py", "src/**/*.py")`; a
  full-trace validation with that pair is accepted. Under r1's
  `fnmatch.fnmatch` this is `False` and F1's acceptance half was red on
  arrival. Pair it with `_glob_match("docs/x.md", "src/**/*.py") is False`
  so the test cannot pass by matching everything.
- **F1b** `test_glob_matcher_agrees_with_stdlib_glob` — the equivalence
  control. Build a scratch tree that **deliberately includes dotfiles**
  (`src/.secret.py`, `.claude/rules.md`), a `[`-bearing name
  (`src/unbal[.py`) and a `^`-bearing name (`src/^caret.py`). For each of
  §3.4a's 13 patterns assert `_glob_match` agrees with
  `glob.glob(pat, root_dir=<tmp>, recursive=True, **include_hidden=True**)`
  over the tree's **files, not its directories** — **both are required by
  §3.4a and the test is wrong without them** (under the default oracle 7 of
  13 mismatch, so a test written the obvious way is red on arrival). The
  pattern set **must include `src/[^a]*.py`**, whose `^` is a literal class
  member rather than a negation. **`glob` is imported in the test module
  only, never in `ledger_ops.py`** (S3/S4). This is what stops a later
  "simplification" back to `fnmatch` from passing.
- **F2** `test_t2_yes_requires_rules_paths` — `t2.answer: "yes"` with
  `rules_paths` absent refused, and with `rules_paths: []` refused (the
  check must never be vacuous).
- **F3** `test_roster_unavailable_forces_t3_no_and_evidence_gap` — four
  cases, the last two being FOLD-8:
  (a) `roster_sha: "unavailable"` with `t3.answer: "yes"` — refused;
  (b) `"unavailable"` + `t3.answer: "no"` + `flags: ["evidence-gap"]` —
  accepted;
  (c) `"unavailable"` + `t3.answer: "no"` + `flags: ["near-cluster"]`
  (present, but without `evidence-gap`) — refused;
  (d) `"unavailable"` + `t3.answer: "no"` + **`flags` absent entirely** —
  **refused**.
  *(FOLD-8: (c) and (d) are distinct failures and a naive `if not flags:`
  guard passes (c) while catching only (d) — or, written the other way,
  passes (d) while catching only (c). Absent-is-valid is the posture for a
  **trace-less** proposal; it is not a licence for a **trace** to claim a
  roster judgment it has just admitted it could not make. A trace that
  says "I had no roster" and carries no `evidence-gap` flag is exactly the
  invisible evidence gap X3 exists to surface.)*
- **F4** `test_roster_sha_form` — a `roster_sha` that is neither
  `SHA_ANCHOR_RE`-shaped nor `"unavailable"` refused; a well-formed
  `sha256:<12hex>` accepted; `"unavailable"` (with F3's conditions met)
  accepted.

### G. Suite-level

- **G1** The scoped CLI suite is green:
  `cd plugins/self-learn/cli && .venv/bin/python -m pytest -q`.
  **Verified baseline on master this session: `1133 passed, 5 skipped`,
  rc=0 read unpiped.** Any new failure blocks. Report the collected count,
  not just "green" — a suite that collected fewer tests than the baseline
  is not a pass.
- **G2** `pyright` adds **zero new errors for `ledger_ops.py`**.
  *(FOLD-3: r1 demanded "`pyright` clean on `ledger_ops.py`", unmeetable.
  FOLD-D: r1 then pinned a **count without its invocation**, which is only
  half a baseline.)*

  **Pin the invocation, not just the number.** Both figures below were
  measured on master this session, rc read **unpiped**; both are
  self-consistent and they disagree because they resolve imports against
  different interpreters:

  | Invocation (from `plugins/self-learn/cli`) | Total | `ledger_ops.py` | Pre-existing diagnostics there |
  |---|---|---|---|
  | `pyright src/self_learn` | 64 errors, rc=1 | **3** | `:35`, `:36` — `reportMissingImports` on `ruamel.yaml` / `ruamel.yaml.error` (**artefacts of resolving against the wrong interpreter**, not real); `:322` — `Argument of type "Path \| None" … "project_path"` |
  | `pyright --pythonpath ./.venv/bin/python src` | 50 errors, rc=1 | **1** | `:322` only — the two ruamel errors vanish, confirming they were resolution artefacts |

  **The bar:** run the **same invocation** before and after — record which
  one — and require the `ledger_ops.py` count not to increase. Under the
  venv-resolved invocation that count is **1**, and it is the better
  baseline because it does not carry two false diagnostics. Identify the
  pre-existing ones **by rule and line**, not by count alone, so a new
  error that displaces an old one cannot hide in an unchanged total.
  Do not fix `:322` — scope creep into a shared file (§7).
  `15-orchestration-runbook.md:131-132` states this rule as an absolute
  number that has since drifted, so **measure, do not quote** — and a
  count measured with a different invocation than the "before" is not a
  measurement, it is a coincidence.
- **G3** The UI suite is **not** required to change and must not need to:
  `cd plugins/self-learn/ui && uv run pytest` still passes with only the
  known pre-existing
  `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
  failure. Run it from the `ui` directory, never the repo root — a repo-root
  run collects both suites, which share basenames with no `__init__.py`
  between them, and yields 16 import errors that look like broken tests and
  are not (campaign §4a).

---

## 5. Mutation plan

The code gate **will** run these. Each is a one-line edit to production
code in `ledger_ops.py`. Revert by inverse `Edit`, never `git checkout` —
the tree under review is uncommitted and is the only copy.

**Read the third column literally.** Most rows must make **exactly** the
named test fail; the four rows marked **BLUNT** are deliberate
wide-radius controls and name the test that must be *among* the failures.
*(FOLD-5: r1's preamble said "exactly the named test" of every row, while
M1 and M20 could not possibly satisfy it — M1 breaks every test that
routes through containment, M20 breaks every trace-less test in the suite.
A mutation table that misstates its own blast radius trains the reviewer
to treat an over-broad failure as expected, which is how a real
over-broad regression gets waved through.)*

| # | One-line production edit | Test(s) that must fail |
|---|---|---|
| M1 | in `_validate_gates`' containment check, replace the `raise` with `pass` | **BLUNT** — **E2**, **E6** and **E7** all go red (all three route through containment). E2 must be among them. |
| M2 | in `proposal_info`, drop the conditional and pass `record_text=None` | **E7** `test_fabricated_quote_makes_proposal_unfresh` |
| M3 | in `write_proposal`, pass `record_text=None` | **E6** `test_write_proposal_supplies_record_text` |
| M4 | in `_flatten_quote`, `return text` (drop the whitespace collapse) | **E3** `test_quote_matches_across_a_line_wrap` |
| M5 | `_QUOTE_MIN_CHARS = 0` | **E5** `test_quote_below_minimum_length_refused` |
| M6 | in `write_proposal`/`_validate_gates`, source the quote from `record.body` instead of `record.to_text()` | **E4** `test_quote_from_frontmatter_accepted` |
| M7 | in the flag check, replace `if flag not in TRACE_FLAGS:` with `if False:` | **B1** `test_flag_outside_closed_set_refused` |
| M8 | remove `"pathed-unbuilt"` from `TRACE_FLAGS` | **B2** — via its `"pathed-unbuilt" in TRACE_FLAGS` assertion (part (c)). *Under r1's B2 this mutation survived: an iterating test iterates whatever is left. FOLD-1.* |
| M9 | in the recommendation check, drop the membership test | **C1** `test_recommendation_outside_enum_refused` |
| M10 | in the gate-key check, drop the unknown-key branch | **D1** `test_unknown_gate_key_refused` |
| M11 | in the `fs` check, allow `evidence: null` for every verdict | **D3** `test_fs_verdict_enum_and_evidence_rule` |
| M12 | in the `g0.canon` check, stop requiring `target` | **D5** `test_canon_yes_requires_target_and_evidence` |
| M13 | in the `t3a` presence check, allow `t3a: null` when `t3.answer == "yes"` | **D6** `test_t3a_presence_follows_t3_answer` |
| M14 | in the `t4` presence check, allow a populated `t4` when `t2.answer == "yes"` | **D7** `test_t4_presence_rules` |
| M15 | in X1, replace the `_glob_match` result with `True` | **F1** `test_t2_match_path_must_match_a_proposed_glob` |
| M15a | in `_glob_match`, translate a non-final `**` segment as `(?:[^/]+/)+` (one-or-more, i.e. r1's `fnmatch` semantics) | **F1a** `test_double_star_matches_zero_directory_levels` — **the blocker's regression guard**; **F1b** also goes red |
| M15b | in `_glob_match`, translate `*` as `.*` instead of `[^/]*` (let a single star cross directory boundaries) | **F1b** `test_glob_matcher_agrees_with_stdlib_glob` (via `src/*.py`) |
| M15c | in `_glob_match`, treat a leading `^` in a character class as a negation as well as `!` (or merely leave it un-escaped, which `re` reads as a negation) | **F1b** — via `src/[^a]*.py`, where `glob` matches `src/app.py`/`src/a.b.py`/`src/^caret.py` and a `^`-negating matcher refuses all three |
| M15d | in `_glob_match`, emit a `/` after a non-final `**` segment | **F1a** `test_double_star_matches_zero_directory_levels` — the double-separator join; **F1b** also goes red |
| M16 | in X1, skip the check when `rules_paths` is absent instead of refusing | **F2** `test_t2_yes_requires_rules_paths` |
| M17 | in X3, drop the `evidence-gap` flag requirement | **F3** `test_roster_unavailable_forces_t3_no_and_evidence_gap` |
| M17a | in X3, guard with `if not flags:` (treating absent and present-without-the-flag alike) | **F3** — specifically case (c); FOLD-8's whole point |
| M18 | in `_validate_gates`, `return` immediately when `data.get("gates")` is a mapping | **BLUNT** — the control that proves the validator is reached at all. **D2** must be among the failures; most of §4-D/E/F go red with it. |
| M19 | make the new `validate_proposal` parameter positional instead of keyword-only | **A4** `test_validate_proposal_signature_is_backward_compatible` |
| M20 | in `_validate_gates`, refuse when `data.get("gates") is None` | **BLUNT** — every trace-less test in the suite goes red. Run scoped (`pytest tests/test_decision_trace.py`) and require **A1** among the failures. |
| M21 | in the quote-length check, measure `len(quote)` (raw) instead of the flattened length | **E5** — specifically the whitespace twin `"   the   "` |
| M22 | in `_validate_gates`, index one level without a type check (e.g. `data["gates"]["g0"]["reject"]` on unverified types) | **A7** `test_malformed_trace_shapes_raise_only_proposal_error` — it raises `TypeError`, not `ProposalError` |
| M23 | in `_validate_gates`, read the record from disk (`Path(...).read_text()`) instead of using the passed `record_text` | **A8** `test_validate_proposal_performs_no_filesystem_io` |
| M24 | add a `_validate_gates(..., record_text=record.to_text())` call to `stamp_proposal` | **A9** `test_stamp_proposal_does_not_validate_the_trace` |
| M25 | in the `sightings` check, use a bare `isinstance(v, int)` (dropping the `not isinstance(v, bool)` clause) | **D9** `test_e1_shape` — via `sightings: true` |
| M26 | delete one member from `TRACE_FLAGS` | **B2** — via its `len(TRACE_FLAGS) == 8` assertion (FOLD-1: the iterating assertion alone stays green) |
| M27 | in the `flags` check, drop the `isinstance(flags, list)` guard | **B3** `test_flags_shape` (a bare string `"near-cluster"` is iterable and would validate character by character) |
| M28 | in the `recommendation` check, insert a default (`data.setdefault("recommendation", "route")`) | **C3** `test_recommendation_absent_is_not_defaulted` — the validator must not mutate its input |
| M29 | in `t1.field_shaped`, require `evidence` only when `answer == "yes"` | **D4** `test_field_shaped_requires_evidence_both_ways` |
| M30 | in `tn`, drop the ≥2-members rule for `answer == "yes"` | **D8** `test_tn_member_and_name_rules` |
| M31 | in `t1.attempted`, accept any truthy value instead of requiring `bool` | **D10** `test_t1_attempted_must_be_bool` |
| M32 | in the `roster_sha` check, accept any non-empty string | **F4** `test_roster_sha_form` |
| M33 | `raise ProposalError(...)` unconditionally at the top of `_validate_gates` | **BLUNT — the refuses-everything control.** Every *accepting* twin must go red: **E1**, **C2**, **B2**(a), **D2**'s twin, **F1**, **A1**. This is the single mutation that proves the twins are load-bearing rather than decorative, and it is the one the §5 audit's "a validator that refuses everything passes a refusal-only suite" argument rests on. |

**Exactly seven criteria carry no mutation row, and each is deliberate:**
**G1, G2, G3** are suite/tooling gates, not behaviours — nothing in
`ledger_ops.py` can be edited to fail them in the one-line sense.
**A2, A3, A5, A6** are absent-is-valid variants, collectively guarded by
the blunt **M20**. Every other criterion — including the accepting twins
**E1** and **C2**, which **M33** covers — is named by at least one row
above. *(Stated so the gap reads as a decision rather than an oversight: a
reviewer cross-checking rows against criteria will find seven unmatched
and should not have to guess which are deliberate.)*

**The fail-open audit — for every assertion, what does it print when the
thing it checks is absent?** Applied, with the answers:

- **E2 alone is worthless.** A validator that raises on every trace passes
  it. E1 (accept the true-quote twin) is what makes E2 mean something.
  Same pairing for B1/B2, C1/C2, D2's twin, F1's twin, F3's twin.
- **E7 alone is worthless.** `is_unanalyzed` returns `True` for a
  *missing* proposal, an *unparseable* proposal, and a *stale* proposal,
  all of which the rewrite could accidentally produce. Hence E7's mandated
  in-test twin (true quote ⇒ still fresh) **and** its
  `has_proposal is True` assertion, which distinguishes "refused for
  containment" from "the file vanished".
- **M18 exists** because every other mutation assumes `_validate_gates` is
  reached. If it were never called, M1–M17 would each fail their test for
  the right-looking reason while the whole block was dead. M18 is the
  positive control on the wiring itself.
- **A1/A5's "it validates" is a weak assertion by construction** — an
  empty `_validate_gates` passes it. It is paired with M20, which proves
  the trace-less path is a *decision* in the code and not an accident.
- **A8 would pass on a build where containment never runs** — "no I/O
  happened" is trivially true of a validator that does nothing. Hence its
  mandated in-test second half: a fabricated quote must still raise under
  the same monkeypatch. The I/O assertion and the discrimination assertion
  have to be in the *same* test or each covers for the other's absence.
- **B2's iterating half would pass on a shrunken `TRACE_FLAGS`** — an
  iterating test iterates whatever survives. The count and membership
  assertions (M8, M26) are what make the set closed rather than merely
  enumerated. This was r1's blind spot and the reviewer's FOLD-1.
- **E5's short-quote fixture passes under either length rule** — raw or
  flattened. Only the whitespace twin (M21) distinguishes them, and §3.4
  specifies flattened.
- **A7 is the criterion most likely to be quietly skipped**, because every
  case looks like "malformed input, obviously refused". It is not about
  refusal — it is about the *exception type*. `pytest.raises(ProposalError)`
  is the whole assertion; a `TypeError` fails it, and `except Exception`
  anywhere in the test destroys it.

---

## 6. Builder decisions, made here rather than left open

- **D1 — Tests live in a new module,
  `plugins/self-learn/cli/tests/test_decision_trace.py`, with its fixtures
  defined inside it.** Do **not** add helpers to `cli/tests/support.py`:
  that file is imported by most of the CLI suite and is in reach of the
  other four Wave-1 units, so a concurrent edit there is a merge conflict
  for someone else, and a changed shared fixture silently re-shapes tests
  this unit never read. Import `proposal_dict` / `hook_proposal_fields`
  from `support` read-only.
  *(FOLD-12: r1 justified this with "`ui/tests/support.py` imports
  `write_proposal` from it" — false. `ui/tests/support.py:27` imports
  `write_proposal` from `self_learn.ledger_ops`, the production module,
  not from the CLI's test-support file. The decision is unchanged and the
  contention argument stands on its own; the false coupling claim is
  withdrawn.)*
- **D2 — Names are fixed, so nobody invents a second spelling:**
  `TRACE_GATE_KEYS`, `TRACE_FLAGS`, `TRACE_RECOMMENDATIONS`,
  `TRACE_OUTCOMES`, `TRACE_FS_VERDICTS`, `_QUOTE_MIN_CHARS`,
  `ROSTER_UNAVAILABLE = "unavailable"`, `_flatten_quote`,
  `_validate_gates`. The four public tuples go in `__all__`; everything
  else stays private.
- **D3 — One function, not three.** `_validate_gates` also validates
  `flags` and `recommendation`. They are one contract (X3 couples the flag
  set to a gate answer) and splitting them invites a caller that runs one
  and not the others.
- **D4 — `_flatten_quote` is local to `ledger_ops.py` and is not exported.**
  It is a comparison normalization, not a hashing one; §3.4 states why that
  does not violate `normalize.py`'s single-normalization pin. Do not move
  it into `normalize.py` — that module's contract is hash inputs.
- **D5 — `t3a`/`t4` required-ness is scope-free.** r2 §1.2 conditions both
  on the *record's* scope (`scope == "skill:" + owner`), and
  `validate_proposal` has no record and no scope. Rather than smuggle a
  scope parameter in (which would relax silently on any path that omits it
  — a fail-open), required-ness is defined from the trace alone:
  `t3a` non-null iff `t3.answer == "yes"`; `t4` null iff `t2` or `tn`
  answered yes, non-null iff `t2`/`t3` both no and `tn != "yes"`, and
  **free** in the one case that genuinely needs the scope (`t3.answer ==
  "yes"` but the scope may not match, so the table may or may not fall
  through to t4). **The residual runs in both directions, and r1 named
  only one of them** *(FOLD-13)*:
  - **under**-requiring `t4` — a scope-mismatched `t3.answer: "yes"` record
    really does fall through to t4, and this validator will accept
    `t4: null` there;
  - **over**-requiring `t3a` — that same record must still fill in `t3a`,
    a block the table will never read for it. That is a real cost paid by
    the analyst (extra judgment, extra quote) for a scope-free rule.
  Both are handed to `U-table`, which has the scope at derivation time
  (§8-O3). Stating only the under-requirement would have made the trade
  look free, and it is not.
- **D6 — `_QUOTE_MIN_CHARS = 8`**, calibrated on `"no error"`, the shortest
  marker in r2 §3's silence lexicon. One constant; retuning it is a
  one-line human decision, not a redesign.
- **D7 — Error messages name the gate path and echo the quote, never file
  contents.** A containment failure prints the leg (`gates.t4.fs.evidence`)
  and the offending quote — which is already in the proposal and already
  secret-scanned on every producer path — and never any part of the source
  text. This keeps the failure debuggable without turning the validator
  into a file-content disclosure channel.
- **D8 — `sightings` minimum is 1, not 0.** `02-schema.md` §1 shows
  `sightings` as a count of sightings of a real lesson; a record that
  exists has been seen at least once, and `0` is a copy error worth
  refusing.
- **D9 — Empty `flags: []` is valid.** It is the honest encoding of "no
  flags", distinct from "the analyst did not consider flags" (key absent).
  Both validate; consumers treat them alike.
- **D10 — No new import at all, not merely no new dependency.** The glob
  matcher is hand-rolled on `re`, already imported at `ledger_ops.py:28`;
  everything else it needs is already imported at `:25-42`. **Neither
  `fnmatch` nor `glob` is imported into `ledger_ops.py`** — `fnmatch` has
  the wrong `**` semantics (§3.4a) and `glob` would breach S4 by touching
  the filesystem. `glob` appears in the **test** module only, as F1b's
  equivalence oracle.
- **D11 — The matcher is hand-rolled rather than delegated to
  `glob.translate()` / `PurePath.full_match()`, and this is a portability
  decision, not a preference.** Both stdlib helpers are Python **3.13**
  additions; `cli/pyproject.toml:5` declares `requires-python = ">=3.11"`.
  The dev venv is 3.13.11, so either would be green here and broken on a
  3.11 or 3.12 install — a portability defect wearing a green suite, which
  is this project's signature failure. ~20 lines of `re` translation is
  the cost of honouring the declared floor. **If the floor is ever raised
  to 3.13, `glob.translate(pat, recursive=True, include_hidden=True)` is
  the correct one-line replacement** — recorded so the simplification is
  available the moment it becomes safe, and not before.

---

## 7. Out of scope

- Everything in §3.7, each with its reason, and none of it a defect.
- **`gates.py` and outcome recomputation — `U-table`.** Do not create the
  module here even as a stub.
- **`verbs.py`, `analyst.py`, `worker.py`, `miner.py`, `selfcheck.py`,
  `telemetry.py`, the UI** — all live in other units.
- **The doctrine rewrite** that would make the analyst *emit* traces —
  `U-composer` (r2 B6). Until it lands, every proposal is trace-less and
  this unit's validator is correctly inert. That is the designed
  transition (r2 §7), not a gap.
- **Surfacing the quote verbatim on the review card** — the UI obligation
  that §3.4's relevance boundary depends on. Named in §8-O4.
- **When trace fields become mandatory** — human policy, r2 §8 item 8 /
  campaign §6 question 8. This unit ships them optional, permanently as far
  as it is concerned.
- **`write_proposal` does not secret-scan.** Pre-existing; the worker
  (`worker.py:887-891`), `proposal validate` (`selfcheck.py:118-132`) and
  the route verbs all scan the proposal file. Not this unit's to change.

---

## 8. What contradicts r2 or the playbook, and what is handed on

**Contradictions found in `misc/routing-procedure-r2.md` (2026-07-27),
verified against current source:**

- **C1 — the closed flag set contradicts itself.** §1.2 defines seven
  flags; §1.6's PATHED transition rule mandates emitting an eighth,
  `pathed-unbuilt`. Resolved in favour of §1.6 (§3.2).
- **C2 — `validate_proposal` does not load the record.** §1.4 item 2 says
  quote containment is cheap because *"the validator already loads the
  record to stamp `record_sha`"*. It does not: `validate_proposal`
  (`:518-568`) receives only the proposal mapping. `stamp_proposal`
  (`:668-691`) is the function that loads the record, and it is a
  *different* function called *later* — and it cannot host the check
  (S5: it runs inside `selfcheck.proposal_validate`'s lock block, whose
  `except` catches only `GitOpsError`, so a `ProposalError` raised there
  escapes the verb and is caught by `cli._cmd_proposal`
  (`cli.py:1721-1725`) as **rc=64 `EXIT_USAGE`** — a schema failure
  reported as a usage error, breaking the pinned exit trio, in a file this
  unit may not edit). The correction is §3.5's three-site design.
  *(This parenthetical said "uncaught traceback" in r1 — wrong; see
  §2-S5, FOLD-4.)*
- **C3 — the TARGET-sourced legs have nowhere to record their target.**
  §1.3 makes `t3a.depth_behind_rule` and `t4.depth_behind_rule` quote the
  *candidate target file*, but §1.2's schema puts a `target:` field only on
  `g0.canon`. Without it the validator has no source to check and the
  reader has no path to audit. Schema-1 gives all three legs a `target:`.
- **C4 — `t3.roster_sha` is "REQUIRED" but the degradation path produces
  no roster.** §1.2 marks it required; §2's T3 degradation says the CLI
  writes `roster: UNAVAILABLE` when it cannot compose one. Resolved by
  admitting the literal `"unavailable"` and coupling it to `t3.answer: no`
  + the `evidence-gap` flag (X3).
- **C5 — putting the outcome enum in `gates.py` duplicates it.** §1.5's
  `CLS` tuple would be a second definition of a set the validator needs
  first. Defined once, in `ledger_ops`, as `TRACE_OUTCOMES`.
- **C6 — §1.4's cross-check list mixes I/O-bearing checks into a validator
  that must stay pure.** Items 6 (ledger probes), 7 (record history) and 8
  (cache-dir roster artifact) all require I/O on the eligibility hot path
  (S4). Excluded here (§3.7), with reasons.

**Observations in contended files — reported, NOT fixed (campaign §3's
builder rule):**

- **N1 — `_validate_project_globs`' docstring is factually wrong.**
  `verbs.py:683-687` states that a pattern with an unbalanced bracket
  *"degrades to a non-matching literal … so 'unparseable' folds into
  'zero-match'"*. **Measured: it degrades to a *matching* literal.**
  `fnmatch.translate('unbal[.py')` → `(?s:unbal\[\.py)\Z`, and
  `glob.glob('src/unbal[.py', root_dir=…)` **returns** the file when it
  exists. The behaviour is fine (it is what `_glob_match` reproduces); the
  comment describing it inverts it, and a comment that inverts its code is
  the fossil-rationale pattern `commit-drift-evidence-spec.md` §1 warns
  about. One-line doc fix, `verbs.py`, not this unit's.
- **N2 — the route-time glob check fails open on absolute patterns.**
  `glob.glob("/etc/host*", root_dir=<elsewhere>)` returns `/etc/hosts` —
  `glob` ignores `root_dir` for absolute patterns, so
  `_validate_project_globs`' zero-match refusal cannot fire for an
  absolute glob no matter what the host tree contains. Found by a sibling
  unit, confirmed here, and **relevant to this spec only as a direction
  constraint**: §3.4a states that reconciling the two matchers means
  fixing `verbs.py`, never loosening `_glob_match`.

**Non-contradictions, verified so a reviewer need not re-check:** r2's
line-number claims that bear on this unit are accurate —
`_validate_lint`/`_validate_card` posture at `:359-408`,
`_validate_hook_extension` at `:426-515`, `stamp_proposal` at `:668-691`,
`_validate_project_globs` at `verbs.py:675-710`, `analyst.py:196-204`'s
fixed-key rebuild (F4), `worker.py:1330`'s `cwd=str(home)`.

**Obligations handed to other units — record them, do not build them here:**

- **O1 → `U-table`:** import `TRACE_OUTCOMES` from `ledger_ops`; do **not**
  redefine `CLS` in `gates.py`.
- **O2 → whoever takes target-quote containment:** Schema-1 already
  requires the `target:` path on all three TARGET legs, so the input
  exists. The check needs a call site that is *not* on the eligibility hot
  path and a decision about what happens when canon changes under a
  validated proposal (§3.7 item 1).
- **O3 → `U-table`:** enforce the scope-conditional `t4` presence rule
  that a scope-free validator cannot (§6-D5).
- **O4 → the review-surface unit:** the card must render the trace's
  quotes **verbatim**. §3.4's accepted residual — the validator checks
  reality, not relevance — is only honest if the human can see the quote.
  Campaign §7 already records this as *"a small UI obligation to confirm"*;
  it is still unconfirmed.
- **O5 → `U-composer` (B6):** the doctrine must teach the trace form, the
  `_QUOTE_MIN_CHARS` floor, the closed flag set, and X3's rule that a
  missing roster forces `t3.answer: no` + `evidence-gap`. A validator the
  doctrine never mentions produces refusals the model cannot act on.
- **O6 → whoever next holds `verbs.py`:** N1's inverted docstring and
  N2's absolute-glob fail-open. If `_glob_match` and
  `_validate_project_globs` are ever unified, **`_glob_match` is the
  correct semantics and `verbs.py` is the side that moves** — a pure
  string matcher cannot acquire a `root_dir` bug, and teaching it to
  ignore its input to "match" the verb would import the defect.
- **O7 → whoever next holds `worker.py` / `verbs.py`:** wire the two
  remaining `validate_proposal` call sites (`worker.py:908`,
  `verbs.py:509`) to pass `record_text=`, which turns §3.7 item 9's
  advisory reach into enforcement on the campaign's primary execution
  path. One line at each site; both already have the record or can load
  it (`worker.py:909-911` computes `rpath` two lines below its call).
  **Until then, do not describe this unit as "quote containment is
  enforced" without the qualifier** — §1 and §3.7 item 9 carry the honest
  wording.

---

## 9. Revision history

- **r1** — **NOT SOUND**: 1 blocker + 15 folds. The blocker: X1 specified
  `fnmatch.fnmatch` for glob matching, whose `**/` compiles to `(?>.*?/)` —
  **one or more** directory levels — so criterion F1's acceptance half was
  **red on arrival** and the validator was *stricter* than the route-time
  check it is supposed to agree with. Resolved in §3.4a with a pure,
  3.11-safe, `re`-only matcher measured equivalent to
  `glob.glob(..., recursive=True, include_hidden=True)` across 13
  patterns, files-only.
  Three folds corrected claims r1 asserted without measuring — the
  "uncaught traceback" consequence (FOLD-4, actually rc=64 `EXIT_USAGE`),
  the "12 of 14" monoculture count (FOLD-9, unsourced), and the
  `ui/tests/support.py` coupling (FOLD-12, false) — each within two pages
  of this spec's own argument that a citation must be checkable against
  its source. They are folded as corrections **with the error left
  visible**, because a spec about fabricated citations that silently
  rewrites its own is worth less than one that shows the correction.
- **r2** — folded all 15 under the 2026-07-26 verdict repricing, and
  resolved the blocker with the `_glob_match` design (§3.4a, §6-D10/D11).
- **r3** — this document. Delta round: **0 blockers, 4 folds.** All 15 r1
  folds were verified applied; the reviewer independently confirmed the
  `validate_proposal`-does-not-load-the-record correction, the
  absent-is-valid seam against all four importers, and the portability
  finding — testing real 3.11.14 and 3.12.12 interpreters to show
  `glob.translate` and `PurePath.full_match` are absent on both and
  present only on 3.13.11.

  **The four delta folds were all in `_glob_match`'s own specification,
  and three were found by implementing r2's recipe literally** — which is
  the lesson worth carrying: a "pinned so the builder does not re-derive
  it" recipe is a claim about *executability*, and r2's had never been
  executed. It emitted a double separator after `**` (reproducing the very
  blocker it fixed), treated `^` as a class negation (reintroducing the
  blocker's false-refusal failure), and rested on two unstated oracle
  preconditions without which the equivalence claim was 7-of-13 wrong.
  **A fourth error surfaced only while folding**: the ruling's own
  phrasing — "only `!` negates" — is the correct semantics but an
  insufficient instruction, because Python's `re` negates on `^`, so a
  literal `^` must be actively **escaped** rather than merely left
  un-rewritten. Verified: `src/[^a]*.py` must compile to
  `src/[\^a][^/]*\.py`. Final measurement, 13 patterns including
  `src/[^a]*.py`, over a tree with dotfiles and `[`/`^`-bearing names:
  **0 mismatches**.
