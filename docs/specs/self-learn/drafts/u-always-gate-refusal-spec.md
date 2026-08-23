# U-always — the ALWAYS tier becomes a validator refusal

**Unit:** U-always (TaskList #6, Wave 1 of the caps/routing train)
**Target files:**
- `plugins/self-learn/cli/src/self_learn/ledger_ops.py` (`_validate_derivation`)
- `plugins/self-learn/skills/self-learn/references/routing-doctrine.md` (doctrine prose — this is the SOURCE; the deployed copy under the user's skills dir is byte-identical, verified by `diff` at `b316f1e`, and is regenerated from this file)
- `plugins/self-learn/cli/tests/test_always_gate.py` (new)

**Baseline:** `master @ b316f1e`. Every line number below was read at that commit.

---

## 1. Objective

Make the always-on tier a thing the validator **refuses without evidence**,
rather than a thing the doctrine merely discourages.

Two rules, both inside `_validate_derivation`:

- **R-ALWAYS-EV** — ALWAYS with no promoting signal in its own trace is
  refused, with a message that names the missing evidence and the cheaper
  shelves. This is the user's ruling, implemented literally.
- **R-ALWAYS-FLAG** — ALWAYS carrying the `no-cheap-surface` flag is
  refused. This is the S-23 corner's only machine-checkable signature and
  is **accepted today** (measured, §2.4).

Plus a doctrine edit that states the refusal where the analyst reads it,
and a decision on the rationale-leak (§5) that is grounded in a live
measurement rather than in taste.

### 1.1 The honest framing (read this before reviewing §4)

Table-1 **already** implements the ruling's promotion logic. `load_class`
returns ALWAYS only from row L5 or row L6
(`plugins/self-learn/cli/src/self_learn/gates.py:99-106`), and both rows
require one of the three signals. A trace with the barren triple already
derives `DEMAND`, and a proposal stating `ALWAYS` over it is already
refused — measured in §2.2.

So R-ALWAYS-EV is **not** new logic. What it changes is real but narrow,
and the spec claims exactly this much and no more:

1. **The message.** Today the refusal is a bookkeeping complaint ("your
   stated outcome does not follow from your answers"). It names neither
   the missing evidence nor the alternatives. These two messages are
   deliberately non-repairable (§8), so **no model ever reads them** —
   their readers are the operator, through the worker log line at
   `worker.py:2645-2646`, and the human running `self-learn proposal
   validate` (`selfcheck.py:169-175`). The model is steered by the
   doctrine edit in §6, not by this text. What changes is what the
   operator sees: the new message names the three signals by field path
   and names PATHED / SKILL / defer, so a refusal in the log is
   diagnosable without opening the trace.
2. **Independence from Table-1.** Today the *only* thing standing between
   an evidence-free lesson and the always-on shelf is two lines in
   `gates.py` (`:103` and `:104-105`) plus one tuple (`:38`). R-ALWAYS-EV
   is written against the evidence fields directly, so loosening L5, L6,
   or `_PROMOTING_FS_VERDICTS` no longer opens the door on its own. §7's
   test T5 pins this by mutating `_PROMOTING_FS_VERDICTS` and requiring
   the refusal to survive.
3. **R-ALWAYS-FLAG is genuinely new enforcement** — see §2.4.

A reviewer who checks §4 against the code and concludes "the triple was
already unreachable" is **correct**, and that is why R-ALWAYS-EV must be
evaluated on the *stated* outcome as well as the derived one (§4.2) —
otherwise it is a check that can never fire, which is the failure shape
this repo has already recorded (a gate whose "pass" is indistinguishable
from "could not see the target").

---

## 2. Current behavior (verified)

### 2.1 Where ALWAYS is decided

`gates.py:99-106` — the only two rows that produce ALWAYS:

```python
    t4 = trace["t4"]
    if t4["depth_behind_rule"]["answer"] == "yes":
        return "DEMAND"  # L4
    if t4["conduct_mode"]["answer"] == "yes":
        return "ALWAYS"  # L5
    if t4["fs"]["verdict"] in _PROMOTING_FS_VERDICTS or e1_promote(trace):
        return "ALWAYS"  # L6
    return "DEMAND"  # otherwise
```

Supporting definitions:

- `gates.py:38` — `_PROMOTING_FS_VERDICTS = ("SILENT", "COSTLY")`
- `gates.py:67-72` — `e1_promote`: `e1["sightings"] >= 2 and bool(e1["post_demand_recurrence"])`
- `ledger_ops.py:130` — `TRACE_FS_VERDICTS = ("SILENT", "COSTLY", "LOUD_CHEAP", "INDETERMINATE")`
- `ledger_ops.py:813-828` — `_check_fs_verdict`: evidence is required "unless the verdict is `INDETERMINATE`", so a `SILENT`/`COSTLY` verdict must carry a RECORD-contained quote.

### 2.2 What happens today to the barren triple

Measured at `b316f1e` by calling `_validate_derivation` directly over
traces built from `plugins/self-learn/cli/tests/support.py`'s
`_base_gate_answers()`, at `scope="project"`:

| t4 / e1 shape | `load_class` | `_validate_derivation` on a stated `ALWAYS` |
|---|---|---|
| conduct_mode no, fs INDETERMINATE, e1 (1, False) | `DEMAND` | REFUSED — "gates.outcome is 'ALWAYS' but Table-1 derives 'DEMAND' …" |
| conduct_mode **yes** | `ALWAYS` | accepted |
| fs **SILENT** | `ALWAYS` | accepted |
| fs **LOUD_CHEAP** | `DEMAND` | REFUSED (same generic message) |
| e1 (2, True) | `ALWAYS` | accepted |

The existing refusal, verbatim, `ledger_ops.py:1370-1375`:

```python
    if stated_outcome != derived_outcome:
        raise ProposalError(
            f"gates.outcome is {stated_outcome!r} but Table-1 derives "
            f"{derived_outcome!r} for scope {scope!r} — the stated "
            "outcome does not follow from the trace's own answers"
        )
```

It names no evidence field and no alternative shelf.

### 2.3 Where the derivation runs, and where it does not

`ledger_ops.py:1360-1364` — two early returns: no `gates`, or no `scope`.
`gates` is mandatory since S-26 (`ledger_ops.py:853-865`, `TRACE_REQUIRED`
at `:152`), so in practice the live gate is whether the caller threads
`scope`:

- **threads scope:** `analyst.py:337` (the producer), `ledger_ops.py:1673`
  (`write_proposal`), `ledger_ops.py:2081` (`proposal_info`, the freshness
  predicate), `selfcheck.py:169-171` (`proposal validate`),
  `worker.py:2316-2320` (the merge verdict).
- **does not thread scope:** `verbs.py:577`, `verbs.py:594`
  (`_resolve_destination` — the **route** path), `verbs.py:1390`,
  `verbs.py:1444` (hook compile/route), `worker.py:3057` (status
  freshness fallback).

This is a real residual — a proposal hand-edited after `write_proposal`
routes with no derivation recheck — but it is **out of scope** here
(§9), because threading `scope` through the route path changes behavior
for all nine outcomes, not just ALWAYS.

### 2.4 R-ALWAYS-FLAG is not currently enforced

`_routable` (`ledger_ops.py:1330-1347`) returns `True` for everything
except `DEMAND` at `user` and `PATHED` at `skill:*`. ALWAYS is therefore
routable at every scope, so R-SCOPE (`ledger_ops.py:1421-1435`) can never
legitimately attach `no-cheap-surface` to an ALWAYS proposal.

Measured: an ALWAYS proposal (L5, `conduct_mode: yes`) carrying
`flags: ["no-cheap-surface"]` at `scope="user"` is **accepted** by both
`_validate_gates` and `_validate_derivation` today — constructed by
assigning `data["flags"] = ["no-cheap-surface"]` *after* `proposal_dict`
returns, because passing `flags=` as an override does not survive
`default_trace_for` (see §7's fixture note for the mechanism). `no-cheap-surface` is
a member of the closed flag set (`ledger_ops.py:99-108`), and nothing
couples it to the outcome.

Doctrine already forbids the human-readable version of this
(`routing-doctrine.md:240-248`): the two no-surface corners "render
`recommendation: defer` with flag `no-cheap-surface` … and **never a
silent upgrade to `ALWAYS`**". R-ALWAYS-FLAG mechanizes that sentence.

### 2.5 Measured basis (live ledger, read-only, `~/.self-learn`)

29 proposal files; 27 carry a trace (2 predate S-26 and are already
refused as trace-less).

Outcome distribution: **ALWAYS 12, DEMAND 10, SKILL 2, PATHED 1, HOOK 1,
GRADUATE 1.** ALWAYS is 44% of traced proposals; PATHED is 3.7%. This
reproduces the ~50% / 4% figure the ruling cites, **on traces produced
after Table-1 went live** — the monoculture is not a pre-trace artifact.

Which signal promotes those 12:

| promoting signal | count |
|---|---|
| `t4.fs.verdict` COSTLY | 9 |
| `t4.fs.verdict` SILENT | 1 |
| `t4.conduct_mode.answer: yes` | 5 (3 of them also have a promoting verdict) |
| `e1_promote` | **0** (every record has `sightings: 1`) |
| **barren triple (would be refused by R-ALWAYS-EV)** | **0** |
| carries `no-cheap-surface` (would be refused by R-ALWAYS-FLAG) | 0 |

**Blast radius on live data: zero proposals change verdict.** The
mechanism actually producing the 44% is `t4.fs.verdict: COSTLY` — a
self-asserted verdict backed by a record-contained quote — in 9 of 12
cases. R-ALWAYS-EV does not touch that; it locks a door that is currently
held shut only by Table-1's row ordering. §10 carries this to the user as
an open question rather than silently widening the ruling.

---

## 3. New behavior — summary

1. `_validate_derivation` gains **R-ALWAYS-EV**, evaluated before the
   stated-vs-derived comparison, whenever ALWAYS is either stated or
   derived.
2. `_validate_derivation`'s existing `elif rendered == "ALWAYS":` branch
   (`ledger_ops.py:1451-1461`) gains **R-ALWAYS-FLAG**.
3. `routing-doctrine.md` §2's T4 paragraph and §3's tier model state the
   refusal as a refusal.
4. No change to `gates.py`. Table-1 is not edited by this unit.

---

## 4. Validation rules

### 4.1 Definitions

Let `gates = data["gates"]`, `t4 = gates.get("t4")`, `e1 = gates.get("e1")`.

```
promoting_fs   := t4["fs"]["verdict"] in ("SILENT", "COSTLY")
promoting_cm   := t4["conduct_mode"]["answer"] == "yes"
promoting_e1   := e1["sightings"] >= 2 and bool(e1["post_demand_recurrence"])
barren         := t4 is a mapping
                  and t4["fs"]["verdict"] == "INDETERMINATE"
                  and not promoting_cm
                  and not promoting_e1
```

`promoting_e1` MUST be computed by calling `gates_mod.e1_promote(gates)` —
never a second inline copy of the `>= 2` threshold. `barren` MUST NOT be
expressed as `not (promoting_fs or promoting_cm or promoting_e1)`: the
ruling names `INDETERMINATE` specifically, and `LOUD_CHEAP` is left to the
existing derivation mismatch (§10, open question 1).

**Ordering, not totality.** This rule does **not** need
`_validate_derivation` to be total on malformed shapes, and must not claim
that it is. Measured at `b316f1e`, calling `_validate_derivation` directly
with `gates.t4 = 123`, with `t4 = {}`, or with `e1.sightings = "two"`
raises `TypeError`/`KeyError` out of `gates.expected_outcome` →
`load_class`, at `ledger_ops.py:1369` — **one line before** §4.2's
insertion point, in code §4.5 explicitly does not change. A rule inserted
after that line cannot make those inputs safe, and no test of the new rule
can discriminate on them.

The contract the rule actually depends on is an **ordering** one:
`_validate_gates` runs first (`ledger_ops.py:1564-1565`) and refuses each of
those shapes at the schema layer — measured messages `gates.t4 must be a
mapping, got 123` (`ledger_ops.py:808-809`), `gates.t4.depth_behind_rule
must be a mapping, got None`, and `gates.e1.sightings must be an int >= 1,
got 'two'`. So by the time R-ALWAYS-EV executes through
`validate_proposal`, `t4` is either `None` or a fully shape-checked mapping
and `e1.sightings` is an int.

Write the accesses defensively anyway — `.get` chains, no bare subscripts,
`barren = False` on anything unexpected — as a style matter consistent with
the surrounding module. Do not claim, or test for, a totality guarantee
this function does not have; T7 pins the ordering instead.

### 4.2 R-ALWAYS-EV — placement and trigger

Insert **between** `derived_outcome = gates_mod.expected_outcome(...)`
(`ledger_ops.py:1369`) and the `if stated_outcome != derived_outcome:`
raise (`:1370`).

Trigger: `(stated_outcome == "ALWAYS" or derived_outcome == "ALWAYS") and barren`.

Both disjuncts are load-bearing:

- `stated_outcome == "ALWAYS"` makes the rule **reachable today** — it
  intercepts the case §2.2 row 1 measures, replacing the bookkeeping
  message with the evidence-naming one.
- `derived_outcome == "ALWAYS"` makes the rule **independent of Table-1** —
  unreachable at `b316f1e`, reachable the moment L5/L6/`_PROMOTING_FS_VERDICTS`
  is loosened. Test T5 proves it by mutating that tuple.

If `t4` is null (Table-1 forces this when `t2.answer == "yes"`,
when the T3 route is taken, or when `tn.answer == "yes"` — see
`ledger_ops.py:1200-1233` and `gates.py:95-99`), `barren` is False and the
existing mismatch raise handles the proposal unchanged.

### 4.3 R-ALWAYS-EV — exact refusal text

One `ProposalError`, built as a single f-string. `{cm}`, `{s}`, `{r}`,
`{derived}`, `{scope}` interpolate the observed values.

```
gates.outcome ALWAYS has no promoting evidence in its own trace:
gates.t4.fs.verdict is 'INDETERMINATE' (needs 'SILENT' or 'COSTLY'),
gates.t4.conduct_mode.answer is {cm!r} (needs 'yes'), and gates.e1 shows
no recurrence (sightings={s!r}, post_demand_recurrence={r!r}; needs
sightings >= 2 AND post_demand_recurrence true). Any ONE of those three
promotes. Table-1 derives {derived!r} for scope {scope!r}. The always-on
shelf is not the fallback for a missing cheap one — route PATHED
(variant: rules with rules_paths) if the lesson has a path trigger,
SKILL if an owning skill holds it, or defer with flag 'no-cheap-surface'
if neither has a surface at this scope.
```

Emit it as one line (no embedded newlines) so it survives the worker's
single-line log format; the wrapping above is presentational.

**Every one of the following substrings is normative** and is asserted by
test T1 — they are what downstream consumers and the existing suite match
on (§8):

`gates.outcome` · `ALWAYS` · `gates.t4.fs.verdict` ·
`gates.t4.conduct_mode.answer` · `gates.e1` · `Table-1 derives` ·
`PATHED` · `SKILL` · `defer` · `no-cheap-surface`

The message MUST begin with the literal `gates.` (see §8).

### 4.4 R-ALWAYS-FLAG — placement, trigger, text

Insert inside the existing `elif rendered == "ALWAYS":` branch
(`ledger_ops.py:1451`), after the `destination != "claude-md"` check and
before the `variant: rules` check.

Trigger: `"no-cheap-surface" in flags` (`flags` is already bound at
`ledger_ops.py:1383`).

```
gates.outcome ALWAYS must not carry the 'no-cheap-surface' flag. ALWAYS
is routable at every scope, so the flag can only mean the always-on
shelf was chosen because a cheaper one was missing — and Table-1 derives
'ALWAYS' here on the trace's own answers. routing-doctrine §3: the two
no-surface corners (DEMAND at user scope, PATHED at skill scope) render
recommendation: defer with this flag; they never render ALWAYS. Drop the
flag if the ALWAYS evidence is real, or defer on the honest destination.
```

Same two constraints: begins with `gates.`, contains `Table-1 derives`.

**Coverage is ALWAYS-only, by deliberate scoping.** The underlying
invariant is that `no-cheap-surface` is illegitimate wherever `_routable`
returns True (`ledger_ops.py:1330-1347`), but the rule sits inside the
`elif rendered == "ALWAYS":` branch, so a HOOK proposal carrying the flag
stays **accepted** (measured at `b316f1e`). That is an accepted residual,
not an oversight: the false-*positive* rate stays zero by construction,
and generalising the check to every routable rendering is a change to five
more rows than this unit's ruling covers. The general form is a separate
unit.

### 4.5 What is NOT changed

- `gates.py` — not edited. Table-1's rows stay exactly as they are.
- The generic mismatch raise at `:1370-1376` — unchanged text, still fires
  for every non-ALWAYS mismatch and for ALWAYS-with-a-null-`t4`.
- `_validate_gates` — untouched. `no-cheap-surface` stays in the closed
  flag set; the coupling is a derivation rule, not a schema rule.
- No new proposal field, no new flag, no new enum value.

---

## 5. DECIDE — the rationale-leak (the S-23 corner in prose)

**Question.** Proposals that justify ALWAYS with "no cheap surface exists
at this scope" in `rationale` or `card.discuss`. Option (a): a lint
refusal or warning matching that text. Option (b): doctrine prose only.

**Decision: (b) for the prose, plus the structured refusal R-ALWAYS-FLAG
(§4.4) in place of a text matcher.**

**Why — measured, not asserted.** A candidate matcher was run over all 29
live proposals' `rationale` and every `card.*` section: a negation/absence
token within 40 characters of a surface token. Recorded verbatim, so the
reopening condition below is re-measurable rather than a description:

```python
PAT = re.compile(
    r"(no|not|n'?t|without|lack\w*|absent|isn'?t|doesn'?t)\W{0,40}"
    r"(cheap|cheaper|narrow\w*|pathed|path trigger|glob|surface|shelf|skill|reference)|"
    r"(cheap|narrow\w*|pathed|glob|surface|shelf)\W{0,30}"
    r"(does ?n[o']?t exist|unavailable|missing|none|absent)",
    re.I,
)
# scan rule: for each proposals/*.yaml, apply PAT.finditer to `rationale`
# (when a str) and to every `card.<k>` value (when a str); one hit per match.
```

Result over the 27 traced proposals: **7 match events across 4 proposals,
2 of them ALWAYS — and 0 true positives.** A blind reconstruction of the
same description by the spec gate, using its own regex, scored 18 hit
proposals and 6 of 12 ALWAYS, also with 0 true positives. Two independent
matchers built from the same intent disagree by a factor of three on the
false-positive count and agree exactly on the true-positive count: zero.
That spread is itself part of the argument — the instrument is not stable
enough to gate on.

The hits, qualitatively:

- 4 events, on 2 ALWAYS proposals, are ordinary correct prose — a sentence
  saying the lesson is "not narrow reference material"; one reciting "T3
  stays no"; one naming `reference` as *the cheaper alternate* (i.e. the
  analyst doing exactly the right thing); one observing "no path trigger
  and no owning skill in the roster".
- 1 event, on a DEMAND proposal, describes "a different glob shape".
- 2 are the doctrine-mandated R-SCOPE sentence on **DEMAND** proposals —
  "reference has no user-scope surface, so this defers rather than …" —
  which is the exact wording the doctrine asks for and must never be
  penalized.

Restricting the matcher to ALWAYS-rendering proposals removes the DEMAND
hits and still leaves **2 false positives out of 12 ALWAYS proposals
(17%)** on this matcher, **6 of 12 (50%)** on the gate's. Either figure is
far too noisy for a refusal, and noisy enough as a warning to be trained
out rather than read.

A matcher narrow enough to clear those 3 would have to require a
surface-absence phrase *and* a consequential connective *and* an
always-on target token in the same sentence. On this corpus it scores
zero false positives and **zero true positives** — it is unvalidated in
both directions, which is the fail-open shape this repo has already
recorded three times (a check whose "clean" output is identical to its
"could not see anything" output). Shipping it would create the appearance
of coverage without the fact of it.

Against that, R-ALWAYS-FLAG catches the same corner on a **structured**
field, with a false-positive rate that is zero by construction (ALWAYS is
routable at every scope, so R-SCOPE can never put that flag there
legitimately), and is verified to be accepted today.

The prose half therefore goes to doctrine (§6), sharpened and moved to
where the analyst reads it at decision time.

**Reopening condition.** If a later corpus shows ALWAYS proposals whose
`rationale` asserts surface absence *without* the `no-cheap-surface`
flag, the text matcher becomes measurable and can be revisited — as a
non-blocking warning first, never as a refusal.

---

## 6. Doctrine prose

**Edit target:** `plugins/self-learn/skills/self-learn/references/routing-doctrine.md`
(the repo copy; the deployed skill copy is regenerated from it and is
byte-identical at `b316f1e`).

### 6.1 §2, the T4 paragraph (`:190-201`)

Current closing sentence:

> The default, absent any promoting evidence, is the **cheap** tier —
> `ALWAYS` is reached only when the record's own evidence argues for it,
> never by default.

Replace the closing clause so it states a refusal, not a preference. The
new text MUST:

- say the validator **refuses** an `ALWAYS` outcome whose `t4.fs.verdict`
  is `INDETERMINATE` with no recurrence and `conduct_mode: no`;
- name all three promoting signals by field path;
- name the three alternatives the refusal names: PATHED, SKILL, defer with
  `no-cheap-surface`;
- keep the existing sentence's "never by default" wording (it is prose the
  analyst already reads and there is no reason to churn it).

### 6.2 §3, the two-corners paragraph (`:240-248`)

The sentence "**never a silent upgrade to `ALWAYS`**" stays. Append that
this is now mechanized: an `ALWAYS` proposal carrying `no-cheap-surface`
is refused by the validator, naming R-ALWAYS-FLAG's shape.

### 6.3 Constraints on the edit

- **Do not reorder or rename gate labels.** `test_composer.py:848-882`
  (A14) pins the first-occurrence order of `G0, T1, T2, T3, T3a, T-N, T4,
  E1` and separately pins that the `**T2 —` heading precedes `**T3 —`.
- **Do not touch the `**T2 —` … `**T3 —` span.** `test_composer.py:885-904`
  (A15) asserts `first contact`, `Read`, `Grep`, `Glob`, `S-24`, and
  `no-cheap-surface` all appear inside it.
- **Do not touch the escalation paragraph.** `test_composer.py:906-921`
  (A16) pins `guard`, `prominence`, and the literal record id in it.
- **The worked example at `:627-665` must keep validating.**
  `test_composer.py:1034` (A19) validates it. It routes ALWAYS via
  `t4.conduct_mode.answer: yes` with `fs: {verdict: INDETERMINATE}` and
  `e1: {sightings: 2, post_demand_recurrence: false}` — i.e. it is
  promoted by exactly one signal and survives R-ALWAYS-EV unchanged. Do
  not "improve" it; it is a working positive control for the new rule and
  §7's T2 references it.
- Keep the file under the 64 KiB assertion at `test_composer.py:822`.

---

## 7. Tests

New module: `plugins/self-learn/cli/tests/test_always_gate.py`.

**Fixture helper.** Add a module-local builder in the new file (NOT in
`tests/support.py`):

```python
def _barren_always(**over) -> dict:
    """support._base_gate_answers() + a t4 whose three signals are all
    non-promoting; `outcome` defaults to ALWAYS."""
    g = support._base_gate_answers()
    g["t4"] = {
        "depth_behind_rule": {"answer": "no", "evidence": None},
        "conduct_mode": {"answer": "no", "evidence": None},
        "fs": {"verdict": "INDETERMINATE", "evidence": None},
    }
    g["e1"] = {"sightings": 1, "post_demand_recurrence": False}
    g["outcome"] = "ALWAYS"
    g.update(over)
    return g
```

**`support.proposal_dict` has two opposite traps around `flags=` /
`recommendation=`. Both were measured at `b316f1e`; a fixture that gets
either one wrong asserts something other than the rule under test.**

The mechanism is the ordering at `support.py:521-523`: `base.update(overrides)`
runs **first**, then `base.update(default_trace_for(base, scope))` runs on
the auto-trace path and overwrites what the caller passed.

1. **`gates=` supplied (auto-trace skipped).** `default_trace_for` never
   runs, so nothing supplies `flags`/`recommendation` and S-26
   (`ledger_ops.py:853-865`) refuses with *"proposal is missing the
   required decision-trace key 'flags'"*. Such fixtures **MUST** pass
   `recommendation=` and `flags=` explicitly.
   `test_decision_table.py:896-902` is the existing precedent.
2. **`gates=` NOT supplied (auto-trace path).** `default_trace_for` runs
   last, and for `destination: claude-md` it returns `_always_trace()`
   (`support.py:494-495`), whose payload includes `"flags": []` and
   `"recommendation": "route"` (`support.py:340`). A `flags=` or
   `recommendation=` override is therefore **silently discarded**:

   ```
   proposal_dict(scope="user", destination="claude-md",
                 flags=["no-cheap-surface"])["flags"]      == []
   proposal_dict(scope="user", destination="claude-md",
                 recommendation="defer")["recommendation"] == "route"
   ```

   Fixtures on this path must set the field **after** the call
   (`p["flags"] = [...]`), or switch to form 1.

T10 is unaffected by trap 2 only by coincidence: `_demand_trace`
(`support.py:395-400`) recomputes R-SCOPE itself and happens to re-supply
the same `flags`/`recommendation` the override asked for.

**`tests/support.py` MUST NOT change.** In particular `_always_trace()`
(`support.py:331-341`) keeps `conduct_mode: {answer: "yes"}` and
`default_trace_for` keeps mapping `destination: claude-md` →
`_always_trace()` (`support.py:495`). Changing either would re-point every
`claude-md` fixture in both suites at a refused trace. The same holds for
`plugins/self-learn/ui/tests/support.py:305-314`.

| id | leg | fixture | expectation |
|---|---|---|---|
| **T1** | R-ALWAYS-EV fires on the exact triple | `proposal_dict(scope="project", destination="claude-md", gates=_barren_always(), recommendation="route", flags=[])`, then `validate_proposal(..., scope="project")` | `ProposalError`; message contains every normative substring in §4.3, and `message.startswith("gates.")` |
| **T2** | conduct_mode promotes | T1's trace with `t4.conduct_mode = {"answer": "yes", "evidence": <record quote>}` | accepted |
| **T3** | fs verdict promotes | T1's trace with `t4.fs = {"verdict": "SILENT"/"COSTLY", "evidence": <record quote>}`, both legs | accepted |
| **T4** | e1 promotes, with both boundaries | `e1 = {"sightings": 2, "post_demand_recurrence": True}` → accepted; `(1, True)` → refused; `(2, False)` → refused | as stated |
| **T5** | **independence from Table-1** | monkeypatch `self_learn.gates._PROMOTING_FS_VERDICTS` to `("SILENT", "COSTLY", "INDETERMINATE")` so Table-1 now derives ALWAYS for the barren trace; then validate T1's proposal | still refused, same message. Positive control in the same test: under the same monkeypatch, T3's promoting-verdict proposal is still accepted |
| **T6** | null `t4` does not crash the new rule | `_pathed_trace`-shaped gates (`t2.answer: "yes"`, `t4: None`) with `gates.outcome` forced to `"ALWAYS"` | `ProposalError` whose message is the **generic** one — contains `Table-1 derives` and `does not follow from the trace's own answers`; NOT the §4.3 text |
| **T7** | **ordering** — malformed shapes are refused by the schema layer and never reach the new rule (§4.1) | via `validate_proposal(..., scope="project")`, three legs on an `outcome: "ALWAYS"` trace: `gates.t4 = 123`; `gates.t4 = {}`; `gates.e1.sightings = "two"` | each raises `ProposalError` whose message is the **schema** one (`gates.t4 must be a mapping`, `gates.t4.depth_behind_rule must be a mapping`, `gates.e1.sightings must be an int`) and does **not** contain §4.3's `has no promoting evidence` |
| **T8** | R-ALWAYS-FLAG refuses | build ONE base — `_flag_case(flag)` returning `p = support.proposal_dict(scope="user", destination="claude-md")` (the default `_always_trace`, derives ALWAYS via L5) then `p["flags"] = flag` — and call it with `["no-cheap-surface"]`. **Assert in-fixture** that `p["flags"] == ["no-cheap-surface"]` before validating | `ProposalError` containing `no-cheap-surface`, `ALWAYS`, `Table-1 derives`; starts with `gates.` |
| **T9** | R-ALWAYS-FLAG twin (positive control) | `_flag_case([])` — the same base, differing from T8 **in the flag alone**. Assert in-fixture that T8's and T9's dicts are equal except at `"flags"` | accepted |
| **T10** | R-ALWAYS-FLAG does not touch the legitimate corner | `destination="reference"`, `recommendation="defer"`, `flags=["no-cheap-surface"]`, DEMAND trace, `scope="user"` (the shape at `test_proposal_validate.py:310-320`); assert in-fixture that `flags` survived (trap 2 does not bite here, but the assertion is what proves it) | accepted |
| **T11** | repair classification unchanged | `worker._repairable(<T1 message>)` and `worker._repairable(<T8 message>)` | both `"INELIGIBLE"` |

**Mutation verification the builder must run and report:**

1. Delete the `stated_outcome == "ALWAYS"` disjunct in §4.2's trigger →
   T1 must fail (it would fall through to the generic message).
2. Delete the `derived_outcome == "ALWAYS"` disjunct → T5 must fail.
3. Replace `e1_promote(gates)` with an inline `sightings >= 1` → T4's
   `(1, True)` leg must fail.
4. Remove `"Table-1 derives"` from either new message → T11 must fail.
5. Remove R-ALWAYS-FLAG entirely → T8 must fail while T9/T10 stay green.
   This item only discriminates if T8's in-fixture flag assertion passes
   first: with the discarded-override recipe (trap 2 above) T8 fails
   identically with and without the rule, which is exactly the
   can't-see-the-target shape §1.1 and §5 both denounce. The builder must
   report T8's observed `p["flags"]` value alongside the mutation result.

### 7.1 Grep of the existing test trees for ALWAYS fixtures

Every fixture that produces or states `ALWAYS`, and its fate under the new
rules. **No test file requires an edit.**

| location | ALWAYS via | fate |
|---|---|---|
| `cli/tests/support.py:331-341` `_always_trace()` | `conduct_mode: yes` (L5) | survives (T2's leg) |
| `cli/tests/support.py:453-461` `_hook_trace` default branch | `conduct_mode: yes` | survives; `rendered` is HOOK anyway |
| `ui/tests/support.py:305-314` `_always_trace()` | `conduct_mode: yes` | survives |
| `cli/tests/test_decision_table.py:266-267` `_outcome_trace("ALWAYS")` | `t4=("no","no","COSTLY")` (L6) | survives |
| `test_decision_table.py:783-793` (A5 L5 golden row) | `conduct_mode: yes` | survives |
| `test_decision_table.py:796-802` (A5 L6 golden row) | `fs COSTLY` | survives |
| `test_decision_table.py:804-824` (L6 e1-driven + boundary) | `e1 (2, True)` | survives |
| `test_decision_table.py:982-1085` (C3/C4/C5 wiring) | `fs COSTLY` | survives |
| `test_decision_table.py:1133-1158` (D3 R-ALWAYS) | `_outcome_trace("ALWAYS")` → `fs COSTLY` | survives; R-ALWAYS-FLAG not triggered (no flag) |
| `cli/tests/test_decision_trace.py:901, 925` | `t4.fs COSTLY` | survives |
| `cli/tests/test_repair.py:104-114` `_valid_trace` (→ `_always_trace`) | `conduct_mode: yes` | survives; TE1-TE14 unaffected |
| `test_repair.py:593-601` **TE12** | stated `SKILL`, derived `ALWAYS` | **untouched** — R-ALWAYS-EV keys on stated-or-derived ALWAYS *with a barren t4*; TE12's t4 is `conduct_mode: yes`. Its `"but Table-1 derives"` assertion and its `INELIGIBLE` classification both hold |
| `test_repair.py:1240-1280` (G3) | repaired to `fs COSTLY` | survives |
| `test_repair.py:1303-1318` (G5) | stated `SKILL`, derived `ALWAYS` | survives; asserts `"Table-1 derives" in line` |
| `cli/tests/test_route_hook.py:186` | load class ALWAYS behind a HOOK | survives |
| `routing-doctrine.md:627-665` worked example (validated by `test_composer.py:1034`) | `conduct_mode: yes` | survives — see §6.3 |

**The one fixture whose observed message changes:**

`cli/tests/test_decision_table.py:890-915`
`test_c1_mismatch_refused_and_twin_accepted` states `ALWAYS` over a trace
that derives `DEMAND` — i.e. it is precisely the barren-triple case, and
R-ALWAYS-EV will intercept it. Its assertion is:

```python
    assert "ALWAYS" in msg and "DEMAND" in msg
```

§4.3's message contains `ALWAYS` literally and `DEMAND` via
`{derived!r}`, so the test stays green **unmodified**. The builder MUST
verify this by running that test specifically and reporting the observed
message, not by assuming it. If for any reason the message cannot carry
both tokens, the message is wrong — not the test.

---

## 8. Compatibility contract for the refusal text

Two consumers read derivation refusals as **text**. Both must keep working.

1. `worker._repairable` (`worker.py:1715-1727`):

```python
    if not message.startswith("gates."):
        return "INELIGIBLE"
    if "roster_sha" in message:
        return "INELIGIBLE"
    if "Table-1 derives" in message:
        return "INELIGIBLE"
    return "ELIGIBLE"
```

   A derivation refusal is INELIGIBLE for the repair round — the model may
   not re-author a trace to satisfy the gate. Both new messages must
   therefore **begin with `gates.`** and **contain `Table-1 derives`**.
   Were a new message to start with `gates.` but omit `Table-1 derives`,
   an evidence-free ALWAYS would become *repairable*, handing the model a
   second attempt at the very judgment the refusal exists to hold.
   Test T11 pins this directly.

2. `test_decision_table.py:906` — `"ALWAYS" in msg and "DEMAND" in msg`
   (§7.1).

Also note `worker.TRACE_CONDITIONALS` / Set-C: those tokens name
*conditional-field* defects validated by `_validate_gates`. Neither new
rule is a conditional-field defect, so no checklist entry is added.

---

## 9. Out of scope

- **Any cap, word-count, or managed-section threshold change** (TaskList
  #1). This unit is the strict-at-the-gate half only.
- **The reference-shelf read instrument** (TaskList #4) and **user-scope
  glob zero-match validation** (TaskList #5).
- **Threading `scope` into the scope-free `validate_proposal` call sites**
  (`verbs.py:577, 594, 1390, 1444`; `worker.py:3057` — §2.3). Real
  residual, all-outcomes blast radius, its own unit.
- **`gates.py` / Table-1.** No row is edited, no verdict is added or
  removed from `_PROMOTING_FS_VERDICTS`.
- **Raising the bar on `t4.fs.verdict` itself** — e.g. requiring a
  second-order check that a claimed `COSTLY` verdict is corroborated.
  §2.5 shows this is where 9 of 12 live ALWAYS routings come from, but it
  is a change to the *promotion* rule, which the ruling fixes.
- **A text matcher on `rationale` / `card.discuss`** — decided against in
  §5, with the reopening condition stated there.
- **The composer prompt** (`worker.compose_single_prompt`). The analyst
  reads the doctrine reference; §6 edits that. No prompt template change.
- **Any change to `verbs.py`'s route-time warning surface.**

---

## 10. Open questions for the user (not blocking the build)

1. **`LOUD_CHEAP`.** The ruling names `INDETERMINATE`. `LOUD_CHEAP` is
   equally non-promoting (`gates.py:38`) and today falls to the generic
   mismatch message rather than the evidence-naming one. §4.1 implements
   the ruling literally. Widening `barren` to "verdict not in
   `_PROMOTING_FS_VERDICTS`" is a one-token change if wanted.
2. **The measured leak is `t4.fs.verdict: COSTLY`, not the barren
   triple** (§2.5: 9 of 12). This unit closes a door that live data shows
   nothing currently walks through. If the goal is to move the 44%, the
   next lever is the `COSTLY`/`SILENT` verdict's evidentiary bar — a
   different ruling, deliberately not taken here.
3. **`e1` is inert in production.** All 12 live ALWAYS proposals carry
   `sightings: 1`. The recurrence promoter has never fired, so its
   acceptance leg is tested only synthetically.
