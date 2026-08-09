# Spec — U-repair: the unattended elicitation contract, one bounded repair round, and the throttle

Status: **r2 — folded, awaiting the delta gate.** The r1 blind spec gate
returned **UNSOUND — 3 BLOCKER / 4 MAJOR / 5 NOTE**; all twelve are
folded and §10 maps each to its change. The gate cite-checked all ~46
`file:line` references, re-derived §9-X2's census independently and
re-ran `X1`: **the evidence base survived intact and every defect was in
the normative register**, which is why r2 hardens rather than redesigns.
Unit `U-repair`, addressing **FW-83**
(`docs/specs/self-learn/14-forward-work-map.md:138`). Evidence of record:
`docs/specs/self-learn/research/2026-08-08-worker-maiden-run-elicitation-failure.md`
— **read it before this document**; every figure it states is treated here
as measured and is not re-derived. This spec adds seven measurements of
its own (§9), one of which corrects a count in that research doc (§8).

**Base commit:** `841784b` (master). The two intervening docs commits
since `beb54ec` (`FW-83`, `FW-84`) touch
`docs/specs/self-learn/14-forward-work-map.md` only, so every code
citation below is against the tree at `beb54ec`/`841784b` alike.

**Files this unit may touch:**

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/worker.py` | The repair round (`Seq-1`), the conditional-requirements constant, the timeout/backoff constants and their readers, the foreign-proposal rule inside `_validate_written`, `--strict-mcp-config` in `build_argv`. |
| `plugins/self-learn/skills/self-learn/references/routing-doctrine.md` | §5.2 gains the conditional checklist; §5.3 gains yes-branch worked examples. |
| `plugins/self-learn/cli/tests/test_worker.py` | The `claude_shim` fixture becomes multi-invocation-observable (§9-X7). |
| `plugins/self-learn/cli/tests/test_composer.py` | `A19` extended (§9-X6); `A13` re-run unchanged. |
| `plugins/self-learn/cli/tests/test_repair.py` | **NEW.** This unit's tests. |
| `docs/specs/self-learn/03-decisions.md` | New rows `S-30`, `S-31` (§7.4), landing in the same commit as the build. |
| `docs/specs/self-learn/14-forward-work-map.md` | FW-83 disposition; FW-84's partial answer recorded (§7.3). |

**`ledger_ops.py` is NOT in this list, deliberately and normatively.**
This unit changes **no validator**. The refusal set is exactly what
`U-schema` and `U-table` shipped; the defect is on the *producer* side and
the *landing* side. A builder who finds themselves relaxing a refusal in
`_validate_gates` or `_validate_derivation` has left this unit's mandate
and must stop and report. So has one who "helpfully" makes a conditional
requirement optional.

`analyst.py` is touched only in the sense that it consumes
`worker.compose_single_prompt` — see §3.2 (b3) and §6-BD9.
`verbs.py`, `commands/review.md`, `miner.py`, `compilers.py` and the UI
are **out of scope and must be reported, not edited.**

---

## 0. Reading order and precedence

This document has **eight normative definitions** — **Set-C** (§3.1, the
trace-writing contract), **Pair-1** (§3.2, the doctrine example↔record
pairing), **Seq-1** (§3.3, the run sequence), **Set-E** + **Table-E**
(§3.4, repair-eligible refusals and their classification probes),
**Set-J** with the `A`/`Φ`/`V`/`O` partition (§3.5, the pinned judgment
fields), **Rule-F** (§3.8, the foreign-proposal rule) and **Obs-1**
(§3.12, the observable surface) — plus one normative behaviour
definition, **the acceptance criteria (§4)**.

**Set-C and Set-E are independent and neither quantifies over the
other** *(r1 gate BLOCKER 2)*. Set-C is what the **producer** is told;
Set-E is which **refusals** a repair may act on. r1 conflated them and
the resulting criterion was unsatisfiable against the shipped refusal
messages.

**Precedence, on conflict:**

1. The acceptance criteria (§4) and the mutation plan (§5) win over
   everything else. They are the contract; the rest is rationale.
2. Set-C, Seq-1, Set-E, Table-E, Set-J, Pair-1, Rule-F and Obs-1 win over
   all prose and over any example.
3. Where this spec and the FW-83 research doc's §"Candidate fix scope"
   disagree, **this spec wins and §8 says why** — that section is
   evidence-ranked input, explicitly non-binding, and this unit re-ranks
   two of its five items and refuses one.

**Each normative definition appears exactly once.** Nothing downstream —
not the criteria, not the mutation plan, not the builder prompt — may
re-state a member. Refer to members by id (`C7`, `J3`, `E-INELIGIBLE-4`).

**Namespaces, so no id is ambiguous.** Set-C's members are `C1`…`C14`
(§3.1) — the acceptance-criteria groups are therefore lettered **A, B,
G, D, E, F, H**, with the fabrication-containment group taking `G` rather
than `C` (§4). Table-E's rows are `TE1`…`TE21` — **TE-prefixed because
bare `T1`/`T3a`/`T4` are the doctrine's gate labels**, which this spec
also cites. Set-E's rules are hyphenated (`E-1`, `E-INELIGIBLE-2`) and
are never criteria group `E`. Seq-1's steps are `S1`…`S8`;
decision-register rows are always hyphenated (`S-26`). Rule-F (§3.8) is
always written with its hyphen and is never criteria group `F`.
`X1`…`X7` are this spec's own measurements (§9), never criteria. **`A13` and `A19` are `U-composer`'s
criteria, not this spec's** — they are the two shipped tests in
`test_composer.py` this unit must keep passing and extend (§3.2, §4-A3),
and they are always cited with their file.

**Read §2 before §3.** Four constraints bind this design from outside it,
and one of them (FW-84) arrived after the defect was measured.

---

## 1. The defect

### 1.1 The analyst copies the one example it is shown, and that example omits every conditional field

The S-26 flip made the decision trace mandatory. The producer was never
taught the trace's **conditional** requirements — the fields whose
required-ness depends on a sibling field's value — and the one worked
example it can pattern-match, `routing-doctrine.md` §5.3, answers **no**
to every gate, so its `t4` block never has to carry them.

The example's `t4` block, verbatim (`routing-doctrine.md:499-502`):

```yaml
  t4:
    depth_behind_rule: {answer: no, evidence: null}
    conduct_mode:      {answer: no, evidence: null}
    fs: {verdict: INDETERMINATE, evidence: null}
```

Three properties of that block are the whole defect:

- **`target` does not appear anywhere in §5.3.** The validator requires
  `t4.depth_behind_rule.target` to be non-empty text when that leg
  answers yes (`ledger_ops.py:1255-1261`), and the same rule holds for
  `t3a.depth_behind_rule.target` (`:1255` sibling at `:1134-1140`) and
  `g0.canon.target` (`:949-955`). A producer reproducing the example's
  key set and flipping `answer` to `yes` emits a two-key node and is
  refused. **Measured: 8 of the replay's 13 refusals are exactly this**
  (§9-X2).
- **`answer: null` is shown as legal**, at `t1.separable` and
  `t1.cost_bearing` (`routing-doctrine.md:491-492`) — where it genuinely
  is (`ledger_ops.py:983`, `:998`). It is **not** legal at
  `t1.field_shaped` (`:968`), `g0.*` (`:924`, `:938`), `t2` (`:1014`),
  `t3` (`:1055`), `t3a.depth_behind_rule` (`:1123`),
  `t4.depth_behind_rule` (`:1244`) or `t4.conduct_mode` (`:1266`). The
  producer generalised the legal case to the illegal ones: the live run
  produced 4 × `gates.t1.field_shaped.answer must be 'yes' or 'no', got
  None`, and the replay corpus carries `t4.conduct_mode: {answer: null,
  evidence: null}` in **8 of 13** files (§9-X2).
- **`fs.verdict: INDETERMINATE` is the example's "I did not determine
  this" value**, and the producer substituted `null` for it in **12 of
  13** files. `verdict` has no null (`ledger_ops.py:818-823`);
  `INDETERMINATE` *is* the null.

This is not a knowledge failure that more doctrine prose would fix. The
doctrine already interpolates whole into a 231 KB prompt and the producer
still copies the exemplar. The exemplar is the instrument, and it teaches
the wrong shape.

### 1.2 The validator reports one refusal; the files carry three — measured

`_validate_gates` raises on the **first** violation it finds. Within the
`t4` block the order is fixed: `depth_behind_rule.answer` →
`.evidence` → `.target` → `conduct_mode.answer` → `.evidence` →
`fs.verdict` (`ledger_ops.py:1244-1281`).

Census of the 13 files the replay's own validator deleted (§9-X2):

| independent Set-C violations in one file | files |
|---|---|
| 3 (`t4…target` + `t4.conduct_mode.answer: null` + `t4.fs.verdict: null`) | 8 |
| 2 (containment + `t4.fs.verdict: null`) | 1 |
| 1 | 4 |

**SINGLE-SAMPLE CAVEAT, carried here because this is where the
conclusion is drawn** *(r1 gate NOTE 12)*: the 13-file corpus is the
**replay's** output. The live run's 7 schema refusals had a materially
different profile (4 × `t1.field_shaped.answer` null, 3 × `t4…evidence`
missing) and were **never censused** — and for the 12 ids the two runs
share, the reported refusal message differs on every one. So the 8/1/4
distribution is one sample of a distribution known to move between runs
over the same records. It is strong enough to rule OUT "one refusal line
is enough" (that conclusion needs only the existence of stacked defects,
which is measured beyond doubt), and it is **not** strong enough to
establish "one round plus the checklist is enough" (§7.2 accepts the
residual on that side rather than claiming it).

**9 of 13 files carry more than one independent defect, and the refusal
line names one of them.** This is the single most load-bearing figure in
this spec, because it decides the repair round's shape: a repair fed only
the validator's refusal line would fix `target` on eight files and every
one of those eight would then be refused for `conduct_mode.answer`, and
then for `fs.verdict`. **One round fed one refusal cannot clear this
population.** The repair prompt must therefore carry the whole conditional
checklist and instruct a whole-file re-check — which is the same artefact
§1.1 says the producer needed in the first place (§3.1, Set-C).

### 1.3 Deleted output teaches nothing, and the retry chain has no throttle

`_validate_written` deletes schema-invalid output and logs it
(`worker.py:1548-1551`). Nothing carries that refusal back to a producer.
The follow-on window (`worker.py:2101-2106`) re-sends the same prompt to
the same model, which makes substantially the same mistakes.

**One precision the FW-83 row invites a reader to get wrong, and this
spec fixes (§9-X5):** the blind chain is *conditional on a backlog above
the batch cap*. `run` clears `worker.dirty` when `leftovers == 0`
(`worker.py:1966-1967`) **before** the model call, so a run that fails
with nothing beyond the cap spawns no follow-on at all — the staleness
alarm is its only detector, by design (`worker.py:2068-2072`). The
unbounded chain needs `leftovers > 0`, which is exactly tonight's shape
(32 eligible, cap 15, 17 left over) and is self-sustaining: a chain that
never lands anything never reduces the leftovers, so it never stops.

### 1.4 What is *not* the defect

Stated so the build does not re-open settled ground. All four were ruled
out by controlled measurement on 2026-08-08 (research doc §"Controlled
measurements"): **time pressure** (unbounded replay: 745 s, 2 valid of
15 — no better than the wall-pressured run), **Write-permission scoping**
(the T13 Edit-family rules are intact on CLI 2.1.226; an 8 s probe wrote
its target file), **MCP/startup hang** (same probe), and **context size**
(231,443 B measured — well inside the window). *The research doc's
≈ 57.5 k-token figure is its own and is not re-derived here; a 4 B/token
rule of thumb gives ≈ 57.9 k. The byte count is the measurement, and
either estimate settles the question identically.*

The 900 s timeout is real and is fixed here (§3.9) — but it is the
*secondary* defect, and a build that fixes only the timeout ships a
pipeline that still yields 13–30%.

---

## 2. What binds this design from outside it

- **S-26 — nothing is fabricated, ever.** A repair round sees the record
  and the refusal and fixes *form*. It must not invent a judgment the
  analyst never made, and it must not escape a conditional requirement by
  changing the answer that triggered it. Deletion remains the terminal
  backstop for anything a repair cannot honestly fix. §3.5 is the
  structural expression of this row and is where a reviewer should look
  first.
- **H-3 — no autonomous process writes canon.** The worker writes only
  under `<bucket>/proposals/` via the settings-file `Edit(...)` rule
  family (`worker.py:751-765`, live-verified at T13 and re-probed
  2026-08-08). The repair round is a second invocation *under the same
  or a narrower* scope — never a wider one (§3.7).
- **The attended path is out of scope.** `commands/review.md`'s
  report→repair→re-validate loop and `proposal validate`'s
  report-never-delete promise are the *model* this unit copies into the
  unattended path; they are not to be edited. The one place this unit
  touches attended output is **defensive** — Rule-F (§3.8) stops the
  worker destroying it.
- **FW-84 — the producer-attribution race.**
  (`14-forward-work-map.md:139`, measured live 2026-08-08 from both
  seats: ledger commit `efd5ebd` deleted 7 proposal files, two of them
  freshly analyzed *and validated* by a concurrent attended session, and
  rewrote two more.) `_proposal_snapshot` is taken before the model call
  and `_written_since` attributes everything changed since to the model
  (`worker.py:1212-1236`), so a concurrent attended write inside that
  window is validated, stamped, overwritten or deleted under the
  unattended delete policy. **This binds U-repair because a second model
  invocation widens the window.** §3.8 states the answer this unit ships
  and §7.3 states, explicitly, the part it does not.
- **The working tree is production.** `~/bin/self-learn` runs master's
  working tree; the next kick executes whatever is merged. §6-BD10 lists
  the flag-day consequences and the two switches that exist so a
  misbehaving change can be turned off without a code edit at 3 AM.

---

## 3. The change

### 3.1 Set-C — the trace-writing contract the producer must be told (NORMATIVE)

**Set-C is the closed list of trace requirements a producer has to know
in order to emit a trace the shipped validator accepts.** Most of its
members are *conditional* (a field's required-ness, legality or nullity
depends on a sibling's value) and those are the measured failures; three
are *unconditional* and are included because a checklist that omits them
is not a contract. It is a *restatement of shipped validator behaviour* —
every member cites the line that enforces it — and this unit adds nothing
to it and removes nothing from it. Set-C is the single source for: the
doctrine's §5.2 checklist, the composer constant `TRACE_CONDITIONALS`,
the repair prompt, and criterion `A1`.

**Set-C is NOT the repair-eligible refusal class** *(r1 gate BLOCKER 2)*.
r1 made it serve both jobs, and the two are incompatible: `C14`'s
refusals name `flags` / `recommendation` / a missing `gates` key and are
all correctly **ineligible** for repair, while `C12` has one eligible
refusal (the enum leg) and one ineligible one (the derivation leg). The
eligible class is **Set-E** (§3.4), defined independently and probed by
**Table-E**; nothing in §3.4 quantifies over Set-C, and nothing here
quantifies over Set-E.

The `token` column is normative: it is the string `A1` requires to appear
**both** in the validator's refusal message **and** in
`TRACE_CONDITIONALS`. Two legs, so a validator rewording and a checklist
deletion each redden, in opposite directions.

| id | cond? | rule | token(s) | enforced at |
|---|---|---|---|---|
| `C1` | ✔ | `g0.reject.evidence` / `g0.defer.evidence` required **iff** that leg answers `yes`; RECORD-sourced | `gates.g0.reject.evidence` | `ledger_ops.py:928-934` |
| `C2` | ✔ | `g0.canon.evidence` required iff `answer: yes` (TARGET-sourced); `g0.canon.target` must be non-empty text when `answer: yes` | `gates.g0.canon.target` | `:942-955` |
| `C3` | ✔ | `t1.field_shaped.answer` ∈ {`yes`,`no`} — **never null**; its `evidence` required on **both** branches | `gates.t1.field_shaped.answer` | `:968-978` |
| `C4` | ✔ | `t1.separable.answer` / `t1.cost_bearing.answer` ∈ {`yes`,`no`,`null`} — the **only** answers where null is legal; `cost_bearing.evidence` required iff `yes` | `gates.t1.cost_bearing.answer` | `:983-1008` |
| `C5` | ✔ | `t2.answer` ∈ {`yes`,`no`}; `evidence` required both ways; when `yes`: `match_path` non-empty, `rules_paths` a non-empty list of non-empty strings, and `match_path` must glob-match at least one of them | `gates.t2.match_path` | `:1014-1049` |
| `C6` | ✔ | `t3.answer` ∈ {`yes`,`no`}; `owner` non-empty iff `yes` and null iff `no`; `scan_terms` a non-empty list of non-empty strings iff `no`, and **null when `yes`** | `gates.t3.scan_terms` | `:1055-1081` |
| `C7` | ✔ | `t3a` non-null **iff** `t3.answer: yes`, null iff `no`. Inside: `depth_behind_rule.answer` ∈ {`yes`,`no`}; its `evidence` required iff `yes`; its **`target` non-empty text required iff `yes`** | `gates.t3a.depth_behind_rule.target` | `:1109-1140` |
| `C8` | ✔ | `t4` **null** when `t2.answer: yes` or `tn.answer: yes`; **non-null** when `t2: no` and `t3: no` and `tn ≠ yes`; when `t3: yes` and scope is known, null iff the t3 route is taken. Inside: `depth_behind_rule.answer` ∈ {`yes`,`no`} with `evidence` and **`target` required iff `yes`**; `conduct_mode.answer` ∈ {`yes`,`no`} — **never null** — with `evidence` required iff `yes` | `gates.t4.depth_behind_rule.target`, `gates.t4.conduct_mode.answer` | `:1203-1276` |
| `C9` | ✔ | `fs.verdict` ∈ Set-V (`SILENT`,`COSTLY`,`LOUD_CHEAP`,`INDETERMINATE`) — **never null**; `fs.evidence` required unless the verdict is `INDETERMINATE`. Applies to both `t3a.fs` and `t4.fs` | `gates.t4.fs.verdict` | `:813-830` |
| `C10` | ✔ | `tn.answer` ∈ {`yes`,`no`,`indeterminate`}; `members` ≥2 iff `yes`, ≤1 iff `no`; `proposed_name` required iff `yes`, null otherwise | `gates.tn.members`, `gates.tn.proposed_name` | `:1151-1197` |
| `C11` | — | `e1.sightings` an int ≥ 1 (a bool is not an int here); `e1.post_demand_recurrence` a bool | `gates.e1.sightings` | `:1286-1299` |
| `C12` | ✔ | `gates.outcome` ∈ Set-O (unconditional enum leg) **and** equal to what Table-1 derives from the trace's own answers at the record's scope (conditional derivation leg) | `gates.outcome` | `:1302-1306`, `:1368-1375` |
| `C13` | ✔ | every RECORD-sourced `evidence` is a **verbatim span of the record** after whitespace flattening — a paraphrase is refused — and is ≥ `_QUOTE_MIN_CHARS` (8) once flattened | `contained in the record` | `:788-799` |
| `C14` | — | `gates`, `flags`, `recommendation` are all **required** (S-26); `flags` ⊆ Set-F with no duplicates; `recommendation` ∈ Set-R | `gates`, `flags`, `recommendation` | `:856-886` |

Three properties of Set-C the build must preserve rather than restate:

- **It is a producer-facing rendering of a validator, not a second
  validator.** No code in this unit evaluates Set-C. `A1` is what keeps
  the rendering honest, by pinning each member's token on both sides —
  the validator's refusal message and the checklist — rather than to a
  hand-written list on one side only.
- **`C4` is the trap.** It is the only place a null answer is legal, and
  it is the one the shipped exemplar displays. Any rendering of Set-C
  that does not make `C4`'s exceptionality explicit has reproduced the
  defect in new words.
- **`C11` and `C14` are unconditional, and `C14`'s tokens are weak by
  nature** — it is a top-level *presence* rule, so its refusal messages
  name keys rather than paths. Recorded so a reviewer does not read the
  weak token as an oversight; `C14`'s real guard is the shipped
  `test_a12b_trace_less_deletion_and_pipeline_not_dead_control`
  (`test_composer.py:675`), which this unit must keep green (`F3`).

### 3.2 Where the elicitation fix lives, and why

**Both the doctrine and the composer — with different content and
different reasons.** The alternative single-home designs were considered
and are refused, with reasons, in §6-BD1.

**(a) `routing-doctrine.md` §5.3 — the worked examples.** The doctrine's
example set must, taken together, **exhibit each Set-C conditional
satisfied on its triggering branch** — at minimum a `t3.answer: yes`
record (owner set, `scan_terms: null`, `t3a` populated, `t4: null`) and a
`depth_behind_rule.answer: yes` node carrying **both** `target` and
`evidence`, and a `fs.verdict` that is not `INDETERMINATE` carrying its
required `evidence`. The count and the composition of the example set are
the **builder's** choice; `A2` enforces coverage and `A3` enforces that
every example validates. This is the highest-leverage edit in the unit:
§1.1 measured that the exemplar, not the prose, is what the producer
reproduces.

**The record-pairing convention is INVENTED HERE and is normative**
*(r1 gate MAJOR 6 — r1 called it "the existing `lrn-00000000`
convention", which it is not: the doctrine has five yaml blocks, exactly
one parsing to a mapping with `gates:`, the shipped extraction
(`test_composer.py:990-995`) is two independent single-item selectors
with no link between them, and the example proposal carries no record id
at all).* Each example ships with its **own** synthetic record, and the
link is explicit:

> **Pair-1.** Every example proposal block carries, as its **first line
> inside the ` ```yaml ` fence**, the comment `# record: lrn-<8 hex>`.
> Every example record block carries that same id in its frontmatter
> `id:`. The pairing is the equality of those two ids.

A YAML comment is invisible to `yaml.load` (so the proposal schema gains
no key — the doctrine's own "never invent keys" rule holds) and trivially
extractable from the raw block text. `A2` asserts the pairing is **total
and injective**: every proposal block has exactly one matching record
block, every record block is claimed by exactly one proposal, and no id
is used twice. Without injectivity a builder can pair both examples with
the same record and satisfy `A3`'s letter while containment-checking
example 2's RECORD-sourced `evidence` (`quote_source="RECORD"`,
`ledger_ops.py:976`, `:1022`) against the wrong record — which passes
only by accident and teaches the producer nothing.

**(b) `worker.py` — one constant, three prompts.** A single module-level
string constant, `TRACE_CONDITIONALS`, renders Set-C imperatively and is
interpolated into:

- `b1` — `_PROMPT_TEMPLATE` (the batch prompt), positioned **after** the
  card-section registry and **immediately before** `=== PENDING RECORDS
  ===`. Position is normative (`A4`): the doctrine sits at byte ~2 k of a
  231 KB prompt and the records at the end, and the instruction to write
  conditional fields must be adjacent to the instruction to write files.
- `b2` — `_REPAIR_PROMPT_TEMPLATE` (§3.6).
- `b3` — `_SINGLE_PROMPT_TEMPLATE`, the one-shot analyst form
  (`worker.py:1119-1142`, consumed by `analyst.py`). **In scope, for the
  checklist interpolation only** — no repair round there. It is the same
  producer with the same defect and the fix is one interpolation;
  excluding it would knowingly leave a second producer emitting the
  shapes this unit exists to stop. `A13`
  (`test_composer.py:812`) already guards the argv-bound prompt's size
  and must still pass.

The doctrine does **not** restate the checklist in list form; it carries
the corrected exemplars plus a §5.2 sentence naming the conditional class
and pointing at the producer prompt. Rationale: the attended path reads
the doctrine and does **not** need the checklist — it has a validator
that *reports* and a session that fixes (that loop drained records the
unattended path failed on the same evening). Prose duplicated in two
files drifts; the exemplar helps everyone.

### 3.3 Seq-1 — the run sequence with the repair round (NORMATIVE)

Replaces `worker.py:1981-2031`. Steps marked *(unchanged)* keep their
current code and their current log lines.

| # | step | lock |
|---|---|---|
| `S1` | compose the batch prompt; `snap0 = _proposal_snapshot(home)` *(unchanged)* | — |
| `S2` | invoke `claude` #1, `timeout = invoke_timeout_secs()` *(unchanged but for the constant, §3.9)* | — |
| `S3` | `written1 = _written_since(home, snap0)` *(unchanged)* | — |
| `S4` | **dry check**: classify every path in `written1` with the *same* per-file check `_validate_written` performs, **mutating nothing on disk** — no `_dump_yaml`, no `stamp_proposal`, no deletion, no git. Yields `verdicts: dict[Path, ProposalError \| None]` **and** the `Φ` membership of each path (§3.5) | — |
| `S5` | if repairs are enabled (§3.7) and `E = {p : verdicts[p] is a Set-E refusal}` is non-empty: `snap1 = _proposal_snapshot(home)`; `pre = {p: p.read_text() for p in E}`; compose the repair prompt (§3.6) and the narrowed settings file (§3.7); invoke `claude` #2, `timeout = repair_timeout_secs()`; `touched2 = _written_since(home, snap1)`; build the **refusal map** `refuse: dict[Path, str]` per §3.5 | — |
| `S6` | re-assert the sentinel hold — `if not sentinel.heartbeat(): hold = sentinel.hold(); sentinel.heartbeat()`. **At least one re-assert must occur after the LAST model invocation and before the first mutation** (`worker.py:2010-2012`, moved). Re-asserting after **both** invocations is explicitly permitted and is strictly safer; only re-asserting *solely* after the first is forbidden *(r1 gate NOTE 8)* | — |
| `S7` | `written = _written_since(home, snap0)` — recomputed, so it covers both rounds *(same function, second call)* | — |
| `S8` | `_harvest(home, written, roster, refuse=refuse)` — validates for real, applies Rule-F (§3.8), deletes what still fails, sweeps orphans, commits *(unchanged but for the `refuse` parameter and Rule-F)* | **commit lock** |

**The invariant this ordering exists to protect:** *no ledger mutation may
precede its lock* (audit 2026-07-16 round 7,
`tests/test_lock_invariant.py`). `S4` and `S5` therefore **delete
nothing, stamp nothing and write nothing**. Every deletion this unit adds
is expressed as an entry in `refuse` and executed by the existing
delete-and-log path inside `_harvest`'s lock. A builder who reaches for
`_git_rm_or_unlink` anywhere between `S2` and `S8` has broken the
invariant.

**Exactly one repair round per run.** The repair's own output is never
re-repaired, and `S5` never recurses. A run that would benefit from a
third attempt gets one on the next window, subject to §3.10.

**The dry check and the real check are one definition.** `S4` and `S8`
call the *same* per-file function with an `apply` flag. Two copies of
that logic is the shape this unit must not ship (`B1`, `M5`).

**What `apply` governs, stated precisely, because "stamping" is not one
thing** *(r1 gate NOTE 9)*. For an `lrn-*.yaml` path, `apply` gates the
`stamp_proposal` call and nothing else. For a **merge** proposal the
stamp is a **precondition of validation**, not a consequence of it:
`_validate_written` sets `data["record_shas"]` from the pending records,
*then* calls `validate_merge_proposal(data)`, *then* writes with
`_dump_yaml` (`worker.py:1511-1524`). So in the dry pass the merge branch
must still resolve the members and compute `record_shas` **in memory**,
still call `validate_merge_proposal`, and suppress **only the
`_dump_yaml` write**. A naive `if apply:` around the whole merge block
makes every merge proposal refuse (or vacuously pass) in the dry pass;
`B1`'s fixture must contain a valid merge proposal and a member-missing
one so that shape reddens (`M45`).

### 3.4 Set-E — repair-eligible refusals (NORMATIVE)

A refusal is **repair-eligible** iff **all three**:

- `E-1` its message begins with `gates.`, **and**
- `E-2` its message does not contain `roster_sha`, **and**
- `E-3` its message does not contain `Table-1 derives`.

Everything else is **ineligible** and is handled exactly as today
(deleted at `S8`, same log line). The ineligible classes, named so the
gate can check the reasoning rather than the regex:

- `E-INELIGIBLE-1` — **roster-sha refusals** (`X3` legs A and B, and the
  sha-shape check; `ledger_ops.py:1082-1104`, `worker.py:1428-1464`).
  These are *honesty* refusals. The only way to "repair" one is to hand
  the model the sha it failed to echo, which is fabrication assistance
  wearing a repair's clothes. Never eligible, on principle, not on
  convenience.
- `E-INELIGIBLE-2` — **derivation refusals** (`gates.outcome is X but
  Table-1 derives Y`, and every Render-1 destination/recommendation/flags
  refusal). A derivation refusal means the analyst's stated *conclusion*
  contradicts its own *answers*. Repairing it means either changing the
  answers (forbidden, §3.5) or authoring the routing decision (the
  analyst's job, not the repairer's). **Both the principled and the
  pragmatic ruling coincide:** zero derivation refusals appear in the
  measured corpus (§9-X2). Most are excluded by `E-1` already — their
  messages begin `destination must be …`, `recommendation must be …`,
  `a HOOK proposal's alternates …`, `outcome … has no routable surface
  …`. The **one** that would slip through the prefix test is the outcome
  leg, whose message begins `gates.outcome is …`; `E-3` excludes it by
  name.
- `E-INELIGIBLE-3` — **pre-trace proposal refusals** (destination enum,
  missing `rationale`/`model`/`analyzed_at`, hook extension, rules
  fields, lint, `card:`). Repairing a `card:` refusal needs the section
  registry, which reopens the re-judgment surface the repair prompt is
  built to exclude (§3.6); and zero card/lint refusals appear in the
  measured corpus.
- `E-INELIGIBLE-4` — **`no pending record for <id>`** (the record was
  resolved mid-run). Nothing to repair; `_still_pending` sweeps it.
- `E-INELIGIBLE-5` — **secret-scan hits.** Never re-offered to a model.
- `E-INELIGIBLE-6` — **naming-contract litter** (anything under
  `proposals/` that is not a top-level `lrn-*.yaml` / `merge-*.yaml`).
- `E-INELIGIBLE-7` — **merge-proposal refusals.** Zero in the corpus, and
  Set-J does not cover merge fields, so including them would widen the
  judgment-pin surface for no measured benefit (§7.2).

**Two classes r1 got wrong, corrected here and stated as principle so the
prefix test is not mistaken for the reason** *(r1 gate BLOCKER 2)*:

- **`flags` and `recommendation` refusals** (`ledger_ops.py:871`, `:874`,
  `:878`, `:883`) are ineligible. Mechanically, none begins with
  `gates.`. On principle, they are the same class as `E-INELIGIBLE-2`:
  `recommendation` is **derived** from the gate answers and never chosen
  (doctrine §2 rule 5), and the two flags a refusal can turn on —
  `no-cheap-surface` and `evidence-gap` — are coupled to the derivation
  (`:1431`) and to the roster-honesty admission (`:1099`) respectively.
  Repairing either is authoring a conclusion.
- **The missing-trace-key refusal** (`:859`, `proposal is missing the
  required decision-trace key …`) is ineligible. There is no form defect
  to repair: the analyst produced no trace at all. Deleting is S-26's
  wedge case exactly as `test_a12b…` (`test_composer.py:675`) pins it.

**Set-E is decided by matching the validator's own refusal message, and
that is a deliberate fragility with a named guard: Table-E.**

**Table-E (NORMATIVE) — the classification probes.** `A5` quantifies over
these rows and nothing else. Each row states a refusal the **shipped**
validator raises, the class the classifier must return, and the rule that
decides it. `A5` asserts both directions per row: that the shipped code
still produces a message matching the row, and that the classifier
returns the stated class.

| # | refusal (message prefix, as raised today) | class | by |
|---|---|---|---|
| `TE1` | `gates.t4.depth_behind_rule.target must be non-empty text when answer is yes` | ELIGIBLE | `E-1` |
| `TE2` | `gates.t4.conduct_mode.answer must be 'yes' or 'no', got` | ELIGIBLE | `E-1` |
| `TE3` | `gates.t4.fs.verdict must be one of` | ELIGIBLE | `E-1` |
| `TE4` | `gates.t3.scan_terms must be null when answer is yes` | ELIGIBLE | `E-1` |
| `TE5` | `gates.t1.field_shaped.evidence is not contained in the record it claims to quote` | ELIGIBLE | `E-1` |
| `TE6` | `gates.t1.field_shaped.answer must be 'yes' or 'no', got` | ELIGIBLE | `E-1` |
| `TE7` | `gates.e1.sightings must be an int` | ELIGIBLE | `E-1` |
| `TE8` | `gates.tn.members must have ≥2 entries when answer is 'yes'` | ELIGIBLE | `E-1` |
| `TE9` | `gates.t2.match_path` … `matches none of rules_paths` | ELIGIBLE | `E-1` |
| `TE10` | `gates.t3a.depth_behind_rule.target must be non-empty text when answer is yes` | ELIGIBLE | `E-1` |
| `TE11` | `gates.outcome must be one of` (the enum leg) | ELIGIBLE | `E-1` |
| `TE12` | `gates.outcome is` … `but Table-1 derives` (the derivation leg) | INELIGIBLE | `E-3` |
| `TE13` | `gates.t3.roster_sha must match sha256:` | INELIGIBLE | `E-2` |
| `TE14` | `gates.t3.roster_sha is 'unavailable' but answer is` | INELIGIBLE | `E-2` |
| `TE15` | `gates.t3.roster_sha` … `does not match this run's composed roster sha` (`worker.py:1460`) | INELIGIBLE | `E-2` |
| `TE16` | `proposal is missing the required decision-trace key` | INELIGIBLE | `E-1` + principle |
| `TE17` | `flags must be a list, got` | INELIGIBLE | `E-1` + principle |
| `TE18` | `recommendation must be one of` | INELIGIBLE | `E-1` + principle |
| `TE19` | `destination must be one of` | INELIGIBLE | `E-1` |
| `TE20` | `no pending record for` | INELIGIBLE | `E-1` + `E-INELIGIBLE-4` |
| `TE21` | a `card:` refusal (`_validate_card`) | INELIGIBLE | `E-1` |

**`TE18` is the row that proves `E-1` cannot simply be widened**: it is
prefix-indistinguishable from `_validate_derivation`'s
`recommendation must be {expected!r} for outcome …` (`:1392`) and from
`:1416`, which `E-INELIGIBLE-2` forbids on principle. Widening `E-1` to
admit `recommendation` would admit a derivation refusal with it. Recorded
so a later agent does not "fix" `TE17`/`TE18` by loosening the prefix.

### 3.5 What the repair may and may not change (NORMATIVE)

**Set-P — permitted.** Exactly four moves, each a *form* fix:

- `P1` add a conditionally-required field that is absent (`…target`, an
  `…evidence` on a `yes` branch);
- `P2` replace a null or out-of-enum value with a legal member of its
  closed set (`fs.verdict`, an `…answer`);
- `P3` null a field the schema forbids at its sibling's answer
  (`t3.scan_terms` when `t3` is `yes`; the `t3a`/`t4` presence rules);
- `P4` replace a paraphrased RECORD quote with a verbatim span of the
  record.

**Set-J — the pinned judgment fields.** A field in Set-J whose pre-repair
value was **already legal for that field** must be **byte-identical**
after the repair. A field whose pre-repair value was absent, null or
out-of-enum is *not* pinned — supplying it is precisely `P1`/`P2`.

| id | field |
|---|---|
| `J1` | every `answer` under `gates` — `g0.reject`, `g0.defer`, `g0.canon`, `t1.field_shaped`, `t1.separable`, `t1.cost_bearing`, `t2`, `t3`, `t3a.depth_behind_rule`, `t4.depth_behind_rule`, `t4.conduct_mode`, `tn` |
| `J2` | `t3a.fs.verdict` and `t4.fs.verdict` |
| `J3` | `gates.t3.owner`, `gates.tn.proposed_name`, `gates.e1.sightings`, `gates.e1.post_demand_recurrence` |
| `J4` | `already_canon` |

**Deliberately NOT pinned — and this is the design, not an omission:**
`gates.outcome`, `destination`, `recommendation`, `flags`, `alternates`.
These are **derived** by Table-1/Render-1 from the answers, and
`_validate_derivation` already recomputes-and-refuses them at `S8`
(`ledger_ops.py:1349-1497`). Pinning them would fight the derivation:
filling `fs.verdict` from null to `COSTLY` legitimately moves the outcome
(`L6`), and a pin would then refuse the very repair it asked for.
**U-table's recompute-and-refuse is the guard on the conclusions; Set-J
is the guard on the premises.** Together they are complete.

**Set-Q — forbidden, and structurally prevented.** Any change to a
Set-J field that was already legal — above all, flipping an `answer` from
`yes` to `no` to escape a conditional requirement, which is the cheapest
possible way to satisfy "target required when answer is yes" and would
silently rewrite the analyst's judgment. Detection: at `S5`, for each
`p ∈ E` whose content changed, compare against `pre[p]` on Set-J; a
violation puts `p` in `refuse` with the reason
`repair changed a settled judgment (<json-path> <old> → <new>)`.

**Four further `refuse` rules, from `S5`'s FOUR-way partition of
`touched2`.** The partition is over `S4`'s verdicts, and `Φ` exists
because r1's three-way version routed foreign-and-valid files into `V`,
where the V-rule would delete them — FW-84's incident reproduced by the
machinery added to prevent it *(r1 gate MAJOR 7)*.

| set | membership (decided at `S4`) | rule |
|---|---|---|
| `A` | `= E`, the assigned repair set — refused at `S4` with a Set-E-eligible refusal | Set-J pin as above |
| `Φ` | **FOREIGN at `S4`** — valid **and** `record_sha`-matching, i.e. Rule-F's F-a ∧ F-b (§3.8) | **never refused, never assigned, never counted.** Excluded from `V` by construction. Re-evaluated against current bytes at `S8`, because the file may have changed again during the repair window |
| `V` | valid at `S4` **and not in `Φ`** | if changed during the repair window → `refuse[p] = "repair rewrote a proposal that had already validated"`. `Φ`'s exclusion is what makes this safe: every remaining member is round-1 **model** output, so refusing it destroys nothing foreign |
| `O` | changed in the repair window, in none of `A`/`Φ`/`V` | **not refused.** Rule-F is applied at `S8`; if not foreign, the file falls through to normal `S8` handling exactly as round-1 output would. **This is an FW-84 concession and is deliberate:** a blanket out-of-scope refusal here would make the repair round a *new* destroyer of concurrent attended writes, which §2 forbids. Genuinely-new repair litter is still caught by the naming-contract check and by ordinary validation |

**`Φ` is computable at `S4` for free** — `S4` already runs the same
`validate_proposal` call and already resolves the record, so F-a and F-b
are both in hand. A builder who computes `Φ` only at `S8` has left the
`V` rule reading r1's partition and reintroduces MAJOR 7.

**Why fabrication is structurally prevented, stated as the four
independent legs a reviewer should check separately:**

1. **Containment** — every RECORD quote the repair writes is checked
   against the record at `S8` (`C13`); a fabricated one is deleted.
2. **Recompute-and-refuse** — every conclusion the repair writes is
   recomputed from the answers at `S8` (`C12`); a laundered verdict is
   deleted.
3. **The Set-J pin** — the answers themselves cannot move. This is the
   one thing legs 1 and 2 cannot see, and it is why this unit adds it.
4. **Deletion** — anything still refused at `S8` is deleted, unchanged
   from today. S-26's backstop is *literally the same code*.

The repair round is given the record and the refusal and nothing that
would let it re-decide (§3.6). It cannot invent a judgment because it is
not permitted to change one, and it is not shown the material a new
judgment would need.

### 3.6 The repair prompt

`_REPAIR_PROMPT_TEMPLATE` carries, and carries **only**:

- the instruction that this is a **form repair, not a re-analysis**, with
  Set-P and Set-Q stated in the model's own second person;
- `TRACE_CONDITIONALS` (§3.2 b2 — the same constant, one definition);
- the explicit statement that **the validator reports only the first
  problem it finds**, and that every line of the checklist must be
  checked against the whole file before finishing — the direct
  consequence of §1.2, and the reason a one-round repair can clear
  three-defect files at all;
- per eligible file: its **absolute path**, its **current contents**, the
  **exact refusal line** (byte-identical to what `S8` would log), and the
  **record's `to_text()`**;
- the instruction to modify **only** the listed paths.

It carries **none** of: the routing doctrine, the skill roster, the
cluster candidates, the rejected-proposal digest, the canon excerpt, the
card-section registry. Those are the materials a *routing decision* needs;
withholding them is a structural limit on re-judgment, not an oversight.

**The record text *is* included, deliberately**, even though it is also
re-judgment material. Nearly every Set-C repair needs a verbatim record
span (`C1`, `C3`, `C4`, `C5`, `C13`), and withholding it would make the
model *invent* quotes — the precise failure the unit exists to stop. The
limit on judgment is the Set-J pin, not information starvation.

**The repair set is bounded by construction:** `E ⊆ written1`, and
`written1` is bounded by the batch, which is bounded by `BATCH_CAP`. No
separate cap is introduced (§6-BD5).

### 3.7 The repair invocation

- **argv** — built by the *same* `build_argv(home, settings_path)`, with
  a different `settings_path`. Both invocations must therefore be
  byte-identical except that one value (`F2`). Same model, same
  `--allowedTools Read,Grep,Glob`, same `--disallowedTools`, same
  `--strict-mcp-config` (§3.11), prompt on **stdin**, `cwd = home`.
- **timeout** — `repair_timeout_secs()`, default `REPAIR_TIMEOUT_SECS =
  10 * 60` (§3.9).
- **write scope** — a **second** settings file,
  `_p("worker.repair.settings.json")`, written by
  `write_repair_settings_file(home, paths)`, whose
  `permissions.allow` is one **exact-path** `Edit(/<abs path>)` rule per
  member of `E`, sorted. This is the structural half of "the repair round
  must not enlarge the blast radius" (§2, FW-84): the CLI itself refuses
  writes outside the assigned set.
  **Builder obligation, not an assumption:** exact-path `Edit(...)` rules
  are *not* verified against the live CLI by this spec. The builder runs
  the T13-style probe the research doc used (a scratch home, the worker's
  argv shape, a settings file carrying one exact-path rule, a prompt that
  writes that file and one sibling) and **records the outcome in the
  build report**. If exact-path rules do not match, the fallback is
  `write_permission_rules(home)` — today's three globs — and the build
  report says so; the `V`-set refusal (§3.5) still holds the line.
- **enable switch** — `SELF_LEARN_REPAIR=0` disables the repair round
  entirely; the run is then byte-identical to today's behaviour (`B9`).
  Rationale in §6-BD10.

### 3.8 Rule-F — the foreign-proposal rule (NORMATIVE)

Inside `_validate_written`, for an `lrn-*.yaml` path. The per-file order
is normative and is stated once, here:

> naming-contract check → secret scan → `read_proposal` → refusal-map
> override (§3.5) → resolve the pending record → **`validate_proposal`
> (+ the roster-sha honesty check)** → **Rule-F** → stamp + count.

> **Rule-F.** A path is **FOREIGN** iff **both**:
> **(F-a)** `validate_proposal(data, record_text=…, scope=…)` accepts it
> **and** `_roster_sha_dishonest` returns `None`; **and**
> **(F-b)** its `record_sha` equals `sha_anchor(pending_record.body)`.
>
> A foreign file is left **entirely alone**: not stamped, not deleted,
> not added to `result.touched`, not counted in `result.proposed` or
> `result.valid_landed`. It is recorded in `result.foreign_left` and
> logged once (§3.12).
>
> A file satisfying **F-b but not F-a is NOT foreign**: it falls through
> to today's delete path, unchanged.

`sha_anchor` is imported from **`normalize`** (`normalize.py:57`), not
from `ledger_ops` — it is re-exported there by import (`:40`) but is not
in `ledger_ops.__all__` *(r1 gate NOTE 11)*.

**Why F-a is not optional — r1 shipped Rule-F without it and the gate
broke it** *(BLOCKER 1)*. r1's justification was "the model cannot
compute that hash". True and irrelevant: **the model does not need to
compute the hash, only to not delete it.** The analyst is handed a record
and told to write a proposal at a path whose current contents already
contain the correct `record_sha:` line, and a model rewriting a YAML file
whole keeps fields it does not understand. And the record IS handed to
it: `is_unanalyzed` (`ledger_ops.py:2088-2095`) is `not proposal_fresh`,
and `proposal_fresh` is False when the proposal is **schema-invalid**
*or* sha-mismatched (`:2082-2085`) — so a stamped, matching-sha,
S-26-invalid proposal makes its record **eligible**. Measured live by the
gate, read-only: of 6 pending records carrying a proposal, all 6 have a
matching `record_sha` and 4 are schema-invalid (`lrn-3e4c2df3`,
`lrn-547d8eb6`, `lrn-792f43c8`, `lrn-f2053910`); `lrn-792f43c8` is
eligible **today** with exactly that file on disk. Under r1's Rule-F the
model's own output would have won total immunity — no containment, no
derivation check, no roster-sha check, no deletion — and, being excluded
from `result.touched`, would never even be staged by `_commit_locked`:
uncommitted, invalid, re-batched every window and skipped every time.

With F-a the immunity set becomes exactly *"proposals that are already
fresh by the shipped predicate"* — files with literally nothing to do —
which is the definition it should have had. The two clauses are the same
two, in the same order, as `proposal_info` (`ledger_ops.py:2045-2085`);
Rule-F adds no new notion of "fresh", it just evaluates it without
constructing a `QueueEntry`.

What Rule-F does and does not close:

- **It closes the destructive half of FW-84's measured incident**: the
  two proposals the attended session had analyzed *and validated*, which
  `efd5ebd` deleted, satisfy F-a and F-b and would now be left untouched.
- **It does not close** an attended proposal written but not yet
  validated (no `record_sha` — indistinguishable from model output), nor
  one **mid-edit after validation** (F-b holds, F-a fails, so it is
  deleted — the same outcome as today, and F-a is what makes that a
  *non-regression* rather than a new loss). Nor does it stop the
  analyst's Write tool overwriting an attended proposal at the same path
  before landing runs at all. All three remain FW-84's (§7.3).
- **Secret scan stays first and still deletes.** A scan-hitting file
  reaches the remote through autosync; that outranks attribution. In
  practice near-impossible — stamping only happens on a `proposal
  validate` that already passed the scan.
- Merge proposals are out of Rule-F's scope (`merge-*.yaml` carries
  `record_shas`, plural, and no attended producer writes them).
- **Foreign ∩ V is decided at `S4`, not here** — see §3.5's `Φ` set. A
  file that is foreign at `S4` is never in `V`, so the V-rule can never
  delete it; that cell is `D6`'s (`r1` gate MAJOR 7).

### 3.9 Timeout and batch headroom

| constant | today | this unit | env override |
|---|---|---|---|
| `INVOKE_TIMEOUT_SECS` | `15 * 60` (`worker.py:103`) | `30 * 60` | `SELF_LEARN_INVOKE_TIMEOUT_SECS` |
| `REPAIR_TIMEOUT_SECS` | — | `10 * 60` | `SELF_LEARN_REPAIR_TIMEOUT_SECS` |
| `BATCH_CAP` | `15` (`worker.py:102`) | **unchanged, 15** | none |

- **1800 s** is ~2.1× the measured maximum (857 s live, 745 s replayed,
  both at batch 15). A cap the normal case brushes is a coin flip that
  costs a whole batch when it loses; a cap the normal case clears with
  margin costs only wall time when a call genuinely hangs, and only for
  runs that were going to produce nothing anyway. Two samples is a thin
  distribution and this spec says so rather than dressing 1800 as
  measured: what is measured is that 900 is too low.
- **600 s for the repair** — it is a bounded mechanical edit over a
  subset of the batch with none of the doctrine/roster/candidate reading
  the first round does. Worst-case run wall becomes 2400 s + coalesce,
  inside the sentinel's 2 h TTL.
- **Both are env-overridable**, following `coalesce_secs()`/
  `worker_model()` (`worker.py:724-735`). Reason: the working tree is
  production, so the alternative to an env var is editing running code.
  **Differs from `coalesce_secs` in one way, deliberately:** a value ≤ 0
  or unparseable falls back to the default. A zero coalesce is
  meaningful; a zero `subprocess.run(timeout=...)` expires instantly and
  would kill every run (`E4`).
- **`BATCH_CAP` does not change, and the refusal is reasoned.** The
  research doc's item 3 offers "raise the cap and/or lower `BATCH_CAP`".
  The measurement supports the first and is silent on the second: quality
  did not improve unhurried, so batch size is a **latency/quota lever,
  not a quality lever**, and there is no measurement at any other batch
  size. Changing it would alter the drain's throughput characteristics on
  no evidence. Re-ranked and refused (§8).

### 3.10 Follow-on backoff

- **State:** `cache_dir()/worker.failures`, one decimal integer — the
  count of *consecutive failed runs*. Unreadable/garbage is read as `0`
  and logged once; a cache file must never wedge the worker.
- **Increment:** at the end of `run`, when `result.status == "failed"`.
- **Reset (delete the file):** when `result.status` is `ok` or `idle`;
  and in `kick()` (`worker.py:888-899`) **before** `_open_window` — an
  explicit kick from a human, the UI, `teach`/`import` or the miner is a
  fresh mandate.
- **Gate:** at `worker.py:2101`, the follow-on spawns only if
  `worker.dirty` exists **and** the counter is `< FOLLOWON_FAILURE_CAP`.
  When suppressed: no spawn, `result.followon = False`, `worker.dirty` is
  **left set** (honest — work remains), and one log line (§3.12).
- **`FOLLOWON_FAILURE_CAP = 2`**, a pinned constant (an edit, not
  config — the `ESCALATE_*` precedent, `worker.py:107-111`). Two
  consecutive failed runs means **four** model attempts have produced
  nothing, since each run now carries a repair round. Beyond that the
  chain is burning quota on a systemic defect and the staleness alarm is
  the correct surface. **This number is a judgment about quota, not a
  measurement, and is named as such** — revisit after the first
  post-merge week.
- **The gate is at the run-end site, not inside `_open_window`.**
  `_open_window` is shared with `kick`, and a human kick must never be
  refused by a backoff counter (`E7`, `M32`).
- **No new notification.** `_maybe_escalate` and the staleness alarm
  (`worker.last-run` is untouched on failure, `fast_status` reads it)
  already surface a stalled queue. Adding a notification class is scope
  creep; the residual — suppression is visible only in `worker.log` — is
  declared in §7.3.

### 3.11 `--strict-mcp-config`

Added to `build_argv` (`worker.py:783-799`), therefore to both
invocations. The analyst needs no MCP server; today it inherits the
user's, paying their startup cost and their side effects for tools
`--allowedTools` will not let it call anyway.

**Verified, not assumed** (§9-X1): on CLI 2.1.226 the flag is accepted
with **no** `--mcp-config` present, rc 0, no diagnostic. `--bare` was
considered and **refused**: its help text states that under it "Anthropic
auth is strictly `ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings`
(OAuth and keychain are never read)", and the unattended worker has no
API key in its environment — adopting it would break every run. Recorded
so a later agent does not re-propose it as the stronger hygiene move
(§7.1).

### 3.12 Obs-1 — the observable surface (NORMATIVE)

**Every line and code in this section is pinned by criteria group `H`
and by mutations `M41`–`M44`** *(r1 gate MAJOR 4: r1 declared them
normative and left them unexercised, in a unit that rewrites `run`'s
tail)*.

**Unchanged, and must stay byte-identical** (review.md and the UI depend
on them):

- `worker run` exit codes: `0` for `ok`/`idle`, `1` otherwise
  (`cli.py:761`).
- `worker run` stdout: `worker run: {status} — {n} proposal(s), {merge}
  merge, {eligible} eligible, {suspects} recurrence suspect(s)`
  (`cli.py:756-760`).
- `run: ok — N proposal(s), M merge, K invalid deleted`
  (`worker.py:2061-2065`); `run: FAILED — …` (`:2068-2072`);
  `run: invalid worker output <name> deleted (<reason>)` (`:1549`);
  `run: orphan proposal <name> swept` (`:1573`);
  `run: follow-on window: <outcome>` (`:2105`).

**One existing count widens, and it is declared rather than smuggled:**
`invalid_deleted` now also counts files deleted for a Set-J violation or
for rewriting an already-valid proposal. The per-file line still names
the reason, so the widening is legible in the log rather than only in the
totals.

**New lines** (their formats are load-bearing from this unit onward):

| when | line |
|---|---|
| repair set computed | `run: repair round — {n_refused} refused, {n_eligible} eligible, {n_ineligible} not repairable` |
| nothing eligible | `run: repair round skipped (no eligible refusals)` |
| switched off | `run: repair round disabled (SELF_LEARN_REPAIR=0)` |
| repair timed out | `run: repair claude timed out after {secs}s` |
| repair exited non-zero | `run: repair claude exited {rc}: {first 400 chars}` |
| after the repair | `run: repair round: {cleared} of {n_eligible} refusals cleared` |
| Rule-F fired | `run: proposal {name} carries a matching record_sha — another producer wrote it; left untouched` |
| backoff fired | `run: follow-on suppressed after {n} consecutive failed runs — `self-learn worker kick` retries` |

**New `RunResult` fields** — additive only, no existing field changes
type or meaning beyond the `invalid_deleted` widening above:
`repair_attempted: bool`, `repair_eligible: int`, `repair_cleared: int`,
`foreign_left: list[str]`.

---

## 4. Acceptance criteria

**These criteria are the contract.** Each states what its check reports
when the target is **absent or broken** — "a check that cannot fail" is
this project's signature defect, and every criterion below is written to
be falsifiable.

Tests live in `tests/test_repair.py` unless a criterion says otherwise.
Constants are **imported**, never re-listed: `TRACE_FLAGS`,
`TRACE_FS_VERDICTS`, `TRACE_GATE_KEYS`, `TRACE_OUTCOMES`,
`PROPOSAL_DESTINATIONS` come from `ledger_ops`.

**No test may invoke a real `claude`.** The seam is `subprocess.run` in
`run`; the fixture is the PATH shim
(`test_worker.py:122-142`, `test_composer.py:707-718`), driven by
`$CLAUDE_SHIM_SCRIPT`. `F5` makes it multi-invocation-observable first —
**that fixture change is a prerequisite for eight of the criteria below,
and a builder who writes them against the truncating shim will get green
tests that observed only the second call** (§9-X7).

### A. The elicitation contract

**A1 — the checklist is pinned to the validator on both sides.** For each
member of Set-C and **each token in that member's `token(s)` column**,
two legs:

- **(i) the validator still says it.** Construct an input violating that
  member and nothing else; assert `ledger_ops._validate_gates` (or, for
  `C12`'s derivation leg, `_validate_derivation`; for `C14`,
  `validate_proposal`) raises `ProposalError`, and assert the raised
  message **contains the token verbatim**.
- **(ii) the checklist still says it.** Assert
  `worker.TRACE_CONDITIONALS` **contains the token verbatim**.

*Broken:* deleting a checklist line reddens leg (ii) for the member that
names it; renaming a field in the validator reddens leg (i) for the same
member. Neither direction can pass silently, which is what "harvest from
the validator" has to mean in practice.
*Vacuity guard, mandatory:* assert **≥ 14 distinct tokens** were checked
and that **every** Set-C row contributed at least one — without it, a
builder whose fixtures fail to violate anything gets a green run over an
empty set.
*Recorded so the gate does not read it as a gap:* `C14`'s tokens
(`gates`, `flags`, `recommendation`) are weak — it is a presence rule, so
its messages name keys, not paths (§3.1). Its real guard is the shipped
`test_a12b…` (`test_composer.py:675`), kept green by `F3`.

**A2 — the doctrine's examples exercise every conditional branch.**
Extract every ` ```yaml ` block in `routing-doctrine.md` that parses to a
mapping carrying `gates:`. Assert the union of those traces exhibits, on
its **triggering** branch: a `t3.answer: yes` (with non-null `owner`,
`scan_terms: null`, non-null `t3a`, `t4: null`); a
`depth_behind_rule.answer: yes` carrying **both** a non-empty `target`
and a non-empty `evidence`; a `conduct_mode.answer: yes` carrying
`evidence`; and an `fs.verdict` that is a member of `TRACE_FS_VERDICTS`
other than `INDETERMINATE`, carrying `evidence`.
*Broken:* reverting §5.3 to the single all-`no` exemplar fails every leg,
naming which. *Absent target:* zero extracted blocks fails collection
loudly, not silently.
**Pairing legs, mandatory** *(r1 gate MAJOR 6)*: assert Pair-1 (§3.2 a)
holds — every extracted proposal block's first in-fence line matches
`# record: (lrn-[0-9a-f]{8})`; every extracted record block's frontmatter
`id` is claimed by exactly one proposal; the map is **total** (no
unpaired block on either side) and **injective** (no record claimed
twice).
*Broken without injectivity:* a builder pairs both examples with the one
existing record, `A3` still passes, and example 2's RECORD quotes are
containment-checked against the wrong record.

**A3 — every doctrine example validates, with `scope` supplied.**
*(Extends `test_composer.py::test_a19_worked_example_validates_and_the_check_can_fail`;
that test currently selects one block by content and calls
`validate_proposal` **without** `scope=`, so the derivation never runs on
the shipped exemplar — §9-X6.)* For **every** example extracted by `A2`,
paired with its own record **through Pair-1** (never positionally, never
by content-matching — `A2`'s pairing legs are this criterion's
precondition), assert `validate_proposal(data,
record_text=record.to_text(), scope=record.scope)` does not raise.
**Two positive controls in the same test, both mandatory:** (i) replacing
one RECORD-sourced `evidence` with a near-miss paraphrase must raise —
this is what proves `record_text=` was supplied at all; (ii) replacing
`gates.outcome` with a different member of `TRACE_OUTCOMES` must raise —
this is what proves `scope=` was supplied at all. Assert the example
count is **≥ 2**.
*Broken:* an exemplar that teaches a derivation-invalid shape fails; a
builder who drops either keyword argument fails the matching control.

**A4 — the checklist sits where attention is.** In the composed batch
prompt, assert `TRACE_CONDITIONALS` appears exactly once, at an offset
**greater than** the doctrine's and **less than** `=== PENDING RECORDS
===`.
*Broken:* a builder who appends the constant to the preamble at the top
of the prompt (the natural place) puts it 200 KB from the records and
fails the ordering leg. Also assert it appears in the prompt
`compose_single_prompt` returns (§3.2 b3).

**A5 — the Set-E classifier is pinned to the validator's real messages.**
**Quantifies over Table-E (§3.4), NOT over Set-C** — r1 quantified over
Set-C and was unsatisfiable, because `C14`'s refusals name `flags` /
`recommendation` / a missing `gates` key (none begins with `gates.`) and
`C12` has one eligible refusal and one ineligible one *(r1 gate BLOCKER
2)*. For each row `TE1`…`TE21`, **two legs**:

- **(i) the refusal is still producible.** Construct an input that makes
  the shipped validator (`_validate_gates`, `_validate_derivation`,
  `validate_proposal`, or `worker._roster_sha_dishonest` as the row
  requires) raise, and assert the raised message matches that row's
  stated prefix.
- **(ii) the classifier agrees.** Assert `_repairable(message)` returns
  the row's stated class.

*Broken:* re-wording a refusal fails leg (i) — which is the point: a
cosmetic message edit would otherwise silently move a file between "a
model may edit this" and "delete it". Loosening `E-1` to admit
`recommendation` fails `TE18`/`TE12` on leg (ii).
*Vacuity guard, mandatory:* assert the classifier returned ELIGIBLE for
**≥ 10** rows and INELIGIBLE for **≥ 8** — a classifier stuck at `True`
or at `False` cannot pass either floor.

### B. The repair round

**B1 — the dry check and the real check are one function.** By source
read of `worker.py`, assert the per-file validation body appears once
(no second `validate_proposal(` call site inside a per-path loop other
than the shared one), and assert by behaviour that the dry check mutates
nothing: after `S4` on a batch containing one valid and one invalid file,
the on-disk bytes of **both** files are unchanged, no `record_sha` has
been stamped, and `git status --porcelain` in the ledger is what it was.
*Broken:* a builder who copies the validation body into a `_dry_check`
passes the behavioural leg and fails the source-read leg — which is the
point, because the copy would drift silently.

**B2 — world: all-valid output.** Shim writes valid traced proposals for
every batch record. Assert `claude` was invoked **exactly once**,
`result.repair_attempted is False`, the log carries
`repair round skipped`, and every proposal landed stamped.
*Broken:* a build that invokes the repair unconditionally shows two calls.

**B3 — world: all-invalid output, cleared.** Shim call #1 writes traces
missing `t4.depth_behind_rule.target`; call #2 writes the same files with
the target added. Assert two invocations; assert
`repair round: N of N refusals cleared`; assert every proposal landed and
carries a stamped `record_sha`; assert `result.status == "ok"`.
*Broken:* a build that never re-reads the repaired files (`S7` reusing
`written1` instead of recomputing from `snap0`) lands nothing.

**B4 — world: mixed, and the repair prompt is scoped.** One valid file,
two invalid. Assert the repair prompt (captured from the shim's
per-invocation stdin log) contains the two invalid paths and their record
texts, and does **not** contain the valid path; assert the valid file's
bytes are unchanged after the run; assert both repaired files land.
*Broken:* a build that hands the model the whole batch fails the
exclusion leg.

**B5 — the refusal line handed to the model is the one the log would
print.** Run once with `SELF_LEARN_REPAIR=0` and capture the
`run: invalid worker output X deleted (<reason>)` line; run again with
repairs enabled on an identical fixture and capture the refusal string
embedded in the repair prompt. Assert **string equality**.
*Broken:* a build that summarises, truncates or re-words the refusal
fails — and a model given a re-worded refusal is being told something the
validator did not say.

**B6 — world: orphaned record mid-run.** The shim writes a proposal and
then resolves its record (moves `pending/lrn-X.md` away). Assert the
`no pending record` refusal is classified **ineligible**, does not appear
in any repair prompt, and the file is deleted with the line **the delete
path actually prints**:
`run: invalid worker output <name> deleted (no pending record for <name>)`.
**Do NOT assert `run: orphan proposal <name> swept`** *(r1 gate NOTE
10)*: that line comes from `_still_pending` (`worker.py:1573`), which
globs `proposals/` **after** `_validate_written` has already unlinked
this file (`:1527` raises, `:1548-1551` deletes and logs), so it never
fires for a path that was in `written`. r1 named the wrong line and would
have handed the builder a red test on correct code.
*Broken:* a build that routes orphan refusals into the repair set puts
the path in the prompt; a build that changes the delete line's format
fails the verbatim leg (and `H3`).

**B7 — world: the repair round itself times out.** Shim call #2 sleeps
past `SELF_LEARN_REPAIR_TIMEOUT_SECS` (set to ~1 s for the test). Assert
`run: repair claude timed out after`; assert the run **completes**;
assert round-1's valid files still land; assert the still-invalid files
are deleted with the ordinary line; assert `result.status` reflects what
landed.
*Broken:* a build that lets `TimeoutExpired` escape kills the run and
loses round-1's valid output too.

**B8 — world: repair output is still invalid.** Call #2 writes the same
defect back. Assert `repair round: 0 of N refusals cleared`, the files
are deleted, and (with nothing else landing) `result.status == "failed"`
and the failure counter incremented.
*Broken:* a build that counts "the model wrote something" as cleared
reports `N of N`.

**B9 — the kill switch is exact, and it switches off COMPOSITION, not
just the call.** With `SELF_LEARN_REPAIR=0`, on a fixture whose output is
entirely invalid, assert **all five**:

1. exactly **one** `claude` invocation;
2. `run: repair round disabled (SELF_LEARN_REPAIR=0)` in the log, and
   **no** `run: repair round —` line;
3. **`_p("worker.repair.settings.json")` does not exist** — the narrowed
   settings file is written during composition, so its absence is the one
   observable that separates "skipped the invocation" from "skipped the
   round" *(r1 gate MAJOR 5: without this leg `M12` moves nothing)*;
4. the repair-prompt composer was never called (monkeypatched counter
   reads 0);
5. the concrete `RunResult` expectation, stated here rather than by
   reference to "the pre-change code path", which is not mechanically
   executable *(same finding)*: `status == "failed"`,
   `proposed == []`, `merge_proposed == []`,
   `invalid_deleted == [<every fixture file name>, sorted]`,
   `touched == []`, `repair_attempted is False`, `repair_eligible == 0`,
   `repair_cleared == 0`, `foreign_left == []`.

*Broken:* a kill switch that skips only `subprocess.run` leaves the
settings file on disk and the composer counter at 1, and fails legs 3–4.

**B10 — exactly one round, never recursive.** A fixture where call #2's
output is invalid must produce exactly **two** invocations, never three.
*Broken:* a `while` where there should be an `if`.

**B11 — ineligible refusals never reach a model.** End-to-end through
`run` (`A5` pins the classifier in isolation; this pins that the
classification is actually *consulted*). For each of `E-INELIGIBLE-1` (a
roster-sha leg), `E-INELIGIBLE-2` (an outcome-derivation mismatch),
`E-INELIGIBLE-3` (a `card:` refusal), `E-INELIGIBLE-5` (a secret-scan
hit) and `E-INELIGIBLE-7` (a merge refusal): assert the file's path does
not appear in any repair prompt and the file is deleted with today's
line.
*Broken:* a classifier that admits roster-sha refusals would be caught
here **and** at `A5` — deliberately doubled, because handing a model the
sha it failed to echo is the one repair that would be fabrication.

**B12 — the repair prompt carries the two things that make it work.**
*(r1 gate BLOCKER 3: r1 asserted the repair prompt's paths, record texts
and refusal string, and nothing about its instructional content — so a
build shipping the repair prompt WITHOUT the checklist passed every
criterion, while §1.2 measures that the checklist is what clears
three-defect files.)* On the captured round-2 stdin, assert:

1. `worker.TRACE_CONDITIONALS` appears in it **verbatim and exactly
   once** — the same constant object `A1` pins, not a paraphrase;
2. the first-problem-only statement appears — assert on the pinned
   substring `only the FIRST problem` (§3.6's normative sentence), so a
   build that drops it reddens;
3. Set-P and Set-Q are stated — assert the pinned substrings
   `do not change` and `only the files listed`.

*Broken:* a build whose repair prompt is "here is the file and the error,
fix it" passes `B3`–`B5` and fails all three legs here.

**B13 — the repair prompt EXCLUDES the re-judgment materials.** §3.5's
fabrication leg 4 rests on this exclusion, so it is a criterion, not
prose. On the same captured stdin, assert **none** of these markers
appears — each is a distinctive literal from the material it stands for:

| material | marker |
|---|---|
| the routing doctrine | `## 2. The gate procedure` |
| the skill roster | `roster sha:` |
| cluster candidates | `cluster candidates (T-N)` |
| the rejected-proposal digest | `Never re-propose the classes below` |
| the card-section registry | `=== CARD SECTION REGISTRY ===` |
| the canon excerpt | `=== PENDING RECORDS ===` (the batch prompt's own record-block header, which carries the excerpt) |

Also assert the composed repair prompt is **< 64 KiB** on a full
`BATCH_CAP`-sized all-invalid fixture — an alarm, labelled as one, that
fires if a future edit starts interpolating bulk context.
*Broken:* a builder who reuses `_PROMPT_TEMPLATE` or `compose_record_block`
for the repair round trips several markers at once and the failure names
which.

### G. Fabrication containment

**G1 — the Set-J pin refuses a flipped answer.** Call #1 writes
`t4.depth_behind_rule: {answer: yes, evidence: <verbatim>}` (no
`target`); call #2 writes the same file with `answer: no` and no target —
a document that **passes** `_validate_gates`. Assert the file is
**deleted**, with `repair changed a settled judgment` naming
`gates.t4.depth_behind_rule.answer`, and that its record is still
pending.
*Broken:* **without the pin this file lands**, and the ledger records a
judgment the analyst never made. This is the highest-stakes criterion in
the unit; it must be red-verified by reproducing the defect (delete the
pin, watch it land) before it is trusted.

**G2 — the pin's positive control.** The same fixture where call #2 adds
the `target` and changes nothing else → the file **lands**.
*Broken:* without `G2`, `G1` passes on a build that refuses every
repaired file.

**G3 — a supplied field is not a changed field.** Call #1 writes
`fs: {verdict: null}`; call #2 writes `fs: {verdict: COSTLY, evidence:
<verbatim record span>}` and the resulting `gates.outcome` moves from
`DEMAND` to `ALWAYS` with `destination` following Render-1. Assert the
file **lands**.
*Broken:* a pin that treats `null → COSTLY` as a judgment change, or that
pins `gates.outcome`, refuses the very repair Set-P `P2` authorises.

**G4 — containment still runs on repaired output.** Call #2 replaces a
RECORD-sourced `evidence` with a plausible paraphrase. Assert deletion,
with the containment refusal in the line.
*Broken:* a build that trusts repaired output and skips validation at
`S8`.

**G5 — the derivation still runs on repaired output.** Call #2 writes a
`gates.outcome` that does not follow from its own answers. Assert
deletion with the `Table-1 derives` refusal.
*Broken:* same as `G4`, on the other leg.

**G6 — the repair may not rewrite a proposal that already validated.**
Call #2 modifies a file that was valid in the dry pass. Assert that file
is deleted with `repair rewrote a proposal that had already validated`,
and that its record is still pending.
*Broken:* the `V`-set rule missing lets a repair round silently re-author
a passing analysis.

**G7 — no ledger mutation between the invocations.** Monkeypatch
`worker._git_rm_or_unlink` and `ledger_ops.stamp_proposal` to record the
invocation index at which they are called (the shim writes a marker file
per call). Assert **zero** calls before the final invocation returns; and
assert `tests/test_lock_invariant.py` passes unchanged.
*Broken:* a builder who deletes in `S5` rather than deferring to `refuse`
reddens here — the round-7 invariant is what this protects.

**G8 — the sentinel is re-asserted after the LAST invocation.** Same
instrumentation: assert **at least one** re-assertion occurs after
invocation #2 and before the first mutation. **Do not assert there is
exactly one, and do not assert none occurs between #1 and #2** — a build
that re-asserts after *both* invocations is strictly safer and must pass
*(r1 gate NOTE 8: r1's exclusion rejected the better implementation, and
its Broken clause had the mechanism backwards — re-asserting at `:2010`
ADDS cover, it does not remove any)*.
*Broken, correctly stated:* a build that re-asserts **only** at
`worker.py:2010` and then runs the repair round leaves the window between
invocation #2 and `_harvest` uncovered — if a concurrent short holder
created-then-released the sentinel during the repair call,
`heartbeat()` returns False (`worker.py:2010`'s own comment) and the
harvest's tracked deletions run with autosync live. That is the hazard
`S6` exists for, and this is the leg that detects it.

### D. Attribution (Rule-F)

**D1 — a foreign, validated proposal survives the landing.** Seed a
record in the batch. The shim script, standing in for a concurrent
attended session, writes a **complete, schema-valid** proposal for that
record **and stamps it** (call `ledger_ops.stamp_proposal` from the test
before the run, then have the shim write nothing for that record).
Assert after the run: the file **exists**, its bytes are **unchanged**,
it is not in `result.proposed`, it is not in `result.invalid_deleted`, it
is not in `result.touched`, and `result.foreign_left` names it; assert
the Rule-F log line.
*Broken:* **this is the FW-84 incident.** Without Rule-F the file is
validated and re-stamped (bytes change) or, if the model wrote its own
version at the same path, deleted. Red-verify by removing Rule-F and
watching the bytes move.

**D2 — Rule-F's positive control.** The same fixture where the shim
writes a **valid but unstamped** proposal for that record → it is
validated, stamped and landed as today.
*Broken:* without `D2`, `D1` passes on a build that skips every file.

**D3 — Rule-F does not rescue a scan hit.** A file carrying a matching
`record_sha` **and** a secret-scan hit is deleted, with today's line.
*Broken:* a builder who puts Rule-F before the scan.

**D4 — the repair round does not enlarge the blast radius.** During the
repair window the shim writes a **foreign stamped** proposal for a record
that is in the batch but **not** in the repair set (an `O`-set member).
Assert it is left untouched by Rule-F and **not** refused by the
out-of-scope rule.
*Broken:* a builder who implements a blanket "anything touched outside
the assigned set is deleted" makes the repair round a new destroyer of
attended work — exactly what §2 forbids and what this criterion exists to
catch.

**D5 — the narrowed repair scope is real.** Assert the repair settings
file exists at `_p("worker.repair.settings.json")`, that its
`permissions.allow` has exactly one entry per member of `E`, that every
entry is an absolute `Edit(//…)` rule naming a member of `E`, and that no
entry is a glob — **or**, if the builder's live probe (§3.7) showed
exact-path rules do not match, that the file carries
`write_permission_rules(home)` verbatim and the build report records the
probe's output.
*Broken:* a repair settings file that silently reuses the batch's three
globs while the spec claims narrowing.

**D6 — a copied `record_sha` buys no immunity, and `Φ` keeps foreign
files out of `V`.** *(r1 gate BLOCKER 1 + MAJOR 7 — two legs, one
criterion, because they are the two halves of "who is Rule-F for".)*

- **(i) F-a is enforced.** The shim writes, as the analyst's own output
  for a batch record, a proposal that is **schema-invalid** (a Set-C
  violation) **and** carries a `record_sha` matching the record — the
  copy-the-line-you-found shape, reachable today: measured live, 4 of the
  6 pending records that carry a proposal are stamped-and-invalid, and
  `lrn-792f43c8` is eligible right now with exactly that file on disk.
  Assert the file is **NOT** foreign: it is deleted, it appears in
  `result.invalid_deleted`, it is **not** in `result.foreign_left`, and
  its record is still pending.
  *Broken:* r1's Rule-F (sha-match alone) grants it immunity — no
  containment, no derivation check, no roster check, no deletion — and,
  being excluded from `result.touched`, it is never staged by
  `_commit_locked` either: uncommitted, invalid, re-batched forever,
  skipped every window. Red-verify by dropping F-a and watching the
  invalid file survive.
- **(ii) `Φ` is excluded from `V`.** A **foreign, valid, stamped** file
  exists at `S4` (so it would be in `V` under r1's three-way partition)
  and is edited again during the repair window — the attended session
  still working. Assert it is **not** deleted, **not** in
  `result.invalid_deleted`, and **not** refused with
  `repair rewrote a proposal that had already validated`.
  *Broken:* the `V` rule deletes it — FW-84's incident reproduced by the
  machinery added to prevent it, which is the regression `M46` models.

### E. Headroom, backoff and constants

**E1 — the timeouts are read, not hardcoded.** Assert
`worker.invoke_timeout_secs()` returns `1800` by default and
`worker.repair_timeout_secs()` returns `600`; assert each honours its env
var; assert the value actually reaches `subprocess.run` by capturing the
`timeout=` kwarg.
*Broken:* a builder who changes the constant but leaves
`timeout=INVOKE_TIMEOUT_SECS` reading the old name fails the capture leg.

**E2 — `BATCH_CAP` is unchanged.** `worker.batch_cap() == 15`.
*Broken:* a builder who "helpfully" lowers it while raising the timeout —
the change §3.9 refuses.

**E3 — the timeout floor is defensible against the measurement.** Assert
`worker.invoke_timeout_secs() >= 2 * 857`, with the two measured figures
(745 s replay, 857 s live) in the assertion message.
*Broken:* a later edit that walks the cap back toward the coin flip
reddens with the numbers in front of the reader. This is an alarm, not a
control, and is labelled so.

**E4 — a zero or garbage timeout falls back.** `SELF_LEARN_INVOKE_TIMEOUT_SECS`
set to `0`, `-5`, and `banana` each yield the default.
*Broken:* a builder who copies `coalesce_secs()`'s `max(0.0, …)` clamp
ships a var that makes every run time out instantly.

**E5 — the backoff suppresses at the cap.** Two consecutive failed runs
(shim writes nothing, leftovers > 0 so `worker.dirty` stays set). Assert
`_spawn_window` was called after run 1 and **not** after run 2, that the
suppression line was logged, that `result.followon is False`, and that
`worker.dirty` still exists.
*Broken:* a build with no counter spawns after both.

**E6 — an `ok` run resets the counter.** fail → ok → fail: assert the
third run **does** spawn a follow-on.
*Broken:* a counter that only ever increments turns the cap into a
lifetime budget.

**E7 — `kick` resets the counter and is never suppressed.** With the
counter at the cap, `worker.kick(home)` returns `spawned` and clears
`worker.failures`.
*Broken:* a builder who puts the gate inside `_open_window` refuses the
human — the one caller that must always be honoured.

**E8 — a corrupt counter is read as zero.** Write `not-a-number` to
`worker.failures`; assert the run proceeds and spawns.
*Broken:* an unguarded `int()` wedges the worker on a corrupt cache file.

### F. Hygiene and process

**F1 — `--strict-mcp-config` is on the argv.** Extend
`test_worker.py::test_run_argv_pins`: assert the flag is present, that it
carries no value, and that no `--mcp-config` accompanies it.
*Broken:* absent flag; and the existing index-based assertions in that
test must still pass unchanged.

**F2 — both invocations share one argv builder.** Assert the two captured
argvs are equal except at the `--settings` value.
*Broken:* a second, hand-rolled argv for the repair drifts from
`build_argv` the first time either changes.

**F3 — the suite is green.** `uv run --project plugins/self-learn/cli
pytest` and `uv run --project plugins/self-learn/ui pytest`, both
reported with the rc captured **unpiped** (`PIPESTATUS` or a direct
`CompletedProcess.returncode`); the one known pre-existing UI failure
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`)
does not block, any new failure does.

**F4 — no new pyright diagnostics.**

**F5 — the shim fixture can observe two invocations.** `claude_shim`
appends rather than truncates and records a per-invocation counter and a
per-invocation stdin capture. A dedicated test drives two invocations and
asserts **both** argvs and **both** prompts were captured, and that the
counter reads `2`.
*Broken:* **the current fixture truncates (`>`), so a two-invocation test
silently observes only the second call and every repair criterion above
becomes a test of round 2 alone** (§9-X7). This criterion is listed under
process because it is a prerequisite, not a behaviour — build it first.

**F6 — no test invokes a real `claude`.** By source read of
`tests/test_repair.py`, assert no `subprocess` call whose argv[0] is
`claude` outside the shim, and that the shim directory precedes the
inherited `PATH`.

### H. Obs-1 — the observable surface

*(r1 gate MAJOR 4: §3.12 declared these normative and byte-identical and
then left them with no criterion and no mutation, while this unit rewrites
`run`'s tail. A builder perturbing a status string breaks review.md's
documented contract with a green suite.)*

**H1 — the exit-code contract.** Drive `cli.main(["worker", "run"])` and
assert the return value is `0` on an `ok` run, `0` on an `idle` run, and
`1` on a `failed` run, matching `cli.py:761`.
*Broken:* a builder who returns the new failure-counter value, or who
folds `failed` into `0` because the repair round "handled it", breaks
review.md's contract and reddens here.

**H2 — the stdout summary is byte-stable.** Capture stdout of the same
three runs and assert each matches, exactly,
`worker run: {status} — {n} proposal(s), {merge} merge, {eligible} eligible, {suspects} recurrence suspect(s)`
with the values substituted (`cli.py:756-760`).
*Broken:* any reformatting, any added field, any em-dash change.

**H3 — the four existing log lines are byte-stable.** Over runs that
produce each, assert verbatim (format string, then values):
`run: ok — {p} proposal(s), {m} merge, {d} invalid deleted`
(`worker.py:2061-2065`); `run: FAILED — {n} eligible, 0 valid proposals`
(`:2068-2072`); `run: invalid worker output {name} deleted ({reason})`
(`:1549`); `run: orphan proposal {name} swept` (`:1573`);
`run: follow-on window: {outcome}` (`:2105`).
*Broken:* `M41`. This is the criterion `B6` leans on for its verbatim
leg, and the one that makes "unchanged" in §3.12 mean something.

**H4 — every NEW line in §3.12 is produced and pinned.** Drive a fixture
per line and assert each appears verbatim, including the two r1 left
entirely unexercised: `run: repair round — {n_refused} refused,
{n_eligible} eligible, {n_ineligible} not repairable` and
`run: repair claude exited {rc}: {…}` (shim exits non-zero on call #2 via
`CLAUDE_SHIM_EXIT`). Also: the skipped, disabled, timeout, cleared,
Rule-F and suppression lines.
*Broken:* `M43`; and a build that emits the summary line without its
counts.

**H5 — the new `RunResult` fields are asserted as fields.** For a mixed
fixture assert `repair_attempted`, `repair_eligible`, `repair_cleared`
and `foreign_left` **directly on the returned `RunResult`**, not by
parsing log text.
*Broken:* `M44`. r1 asserted `repair_eligible` only through the log
string, so a field that never moved off its default read as correct.

---

## 5. Mutation plan

The code gate runs these. **Before any sweep:** `export
PYTHONDONTWRITEBYTECODE=1` and `find . -name __pycache__ -type d -prune
-exec rm -rf {} +` — a stale cache reports mutations as survived that
never executed (FW-61). Use absolute paths and confirm
`realpath(self_learn.__file__)` resolves inside the tree under review.

| # | one-line edit | reddens |
|---|---|---|
| M1 | delete one line from `TRACE_CONDITIONALS` | A1 (the member naming that path) |
| M2 | revert §5.3 to the single all-`no` example | A2 (every leg), A3 (count floor) |
| M3 | drop `scope=` from A3's `validate_proposal` call | A3 control (ii) |
| M4 | move `TRACE_CONDITIONALS` to the top of `_PROMPT_TEMPLATE` | A4 |
| M5 | copy the validation body into a second `_dry_check` | B1 (source-read leg only — the behavioural leg survives, which is the point) |
| M6 | invoke the repair unconditionally, even with zero refusals | B2 |
| M7 | `S7` reuses `written1` instead of recomputing from `snap0` | B3, B8 |
| M8 | put every batch file in the repair prompt, not just `E` | B4 |
| M9 | truncate the refusal string to 80 chars in the repair prompt | B5 |
| M10 | let `subprocess.TimeoutExpired` escape the repair call | B7 |
| M11 | count "the file changed" as "cleared" | B8 |
| M12 | make `SELF_LEARN_REPAIR=0` skip only the invocation, not the prompt composition | B9 |
| M13 | `if` → `while` on the repair round | B10 |
| M14 | drop `E-2` (the `roster_sha` exclusion) | A5, B11 |
| M15 | drop `E-3` (the `Table-1 derives` exclusion) | A5, B11 |
| M16 | **delete the Set-J pin** | **G1** — and only G1; G2–G5 all still pass, which is exactly why G1 must be red-verified rather than trusted |
| M17 | pin `gates.outcome` in Set-J | G3 |
| M18 | delete the `V`-set rule | G6 |
| M19 | skip `validate_proposal` for files the repair touched | G4, G5 |
| M20 | delete in `S5` instead of populating `refuse` | G7, and `test_lock_invariant.py` |
| M21 | leave the sentinel re-assert between the two invocations | G8 |
| M22 | **delete Rule-F** | **D1** |
| M23 | make Rule-F fire on *any* present `record_sha`, not a matching one | D2 (an unstamped model proposal that emitted a junk sha would be skipped) |
| **M23a** | **drop Rule-F's F-a leg** (immunity on sha match alone — r1's shipped rule) | **D6(i)** — and only D6(i): D1–D5 all still pass, which is precisely why r1 shipped it |
| M24 | move Rule-F before the secret scan | D3 |
| M25 | refuse every `O`-set path (blanket out-of-scope deletion) | **D4** — the FW-84 regression |
| M26 | write the repair settings file with `write_permission_rules(home)` while the report claims narrowing | D5 |
| M27 | `INVOKE_TIMEOUT_SECS` back to `15 * 60` | E1, E3 |
| M28 | `BATCH_CAP` → 10 | E2 |
| M29 | `invoke_timeout_secs()` uses `max(0.0, float(raw))` | E4 |
| M30 | never increment the failure counter | E5 |
| M31 | never reset the failure counter on `ok` | E6 |
| M32 | move the backoff gate inside `_open_window` | E7 |
| M33 | bare `int(text)` on the counter file | E8 |
| M34 | drop `--strict-mcp-config` from `build_argv` | F1 |
| M35 | build the repair argv by hand instead of calling `build_argv` | F2 |
| M36 | revert `claude_shim` to `>` | F5 |
| **M37** | classify `no pending record for <id>` as eligible | B6 |
| **M38** | the Set-J pin refuses **any** difference in a Set-J field, including one that was absent/null/out-of-enum before | G2, G3 |
| **M39** | drop `TRACE_CONDITIONALS` from `_REPAIR_PROMPT_TEMPLATE` (keep it in the batch prompt) | **B12** — and *only* B12: A1 reads the constant, not the repair prompt, so every other criterion stays green. This is r1's BLOCKER 3 in one line |
| **M40** | interpolate the doctrine into `_REPAIR_PROMPT_TEMPLATE` | B13 (doctrine marker), and its size alarm on a full fixture |
| **M41** | rewrite `run: ok — ` as `run: OK - ` | H3, and B6's verbatim leg |
| **M42** | `_cmd_worker` returns `0` for a `failed` run | H1 |
| **M43** | emit `run: repair round` with no counts | H4 |
| **M44** | never assign `result.repair_eligible` (leave it 0) | H5 |
| **M45** | wrap the **whole** merge branch in `if apply:` in the shared per-file check | B1 — the dry pass then refuses (or vacuously passes) every merge; §3.3's `apply` note is what this models |
| **M46** | compute `Φ` at `S8` only, leaving `S5`'s partition three-way | **D6(ii)** — the foreign∩V cell; the file is deleted by the `V` rule |
| **M47** | add the repair counts to `_cmd_worker`'s stdout summary (`cli.py:756-760`) | H2 — the tempting, harmless-looking edit that breaks a documented contract |

**Every criterion has at least one mutation above except the vacuity
guards in `A1`/`A5`, and `F3`, `F4`, `F6` — deliberately, and stated so
the omission is not read as the same gap.**
*(r1 gate: `A5`, `B6`, `B9`, `G2`, `G8` and all of Obs-1 previously
claimed that property without holding it. `M23a`, `M37`–`M46` close the
gap; `M12`'s claim on `B9` is made true by `B9`'s new legs 3–4 rather
than by a new mutation.)* Those are process gates over the whole tree
(suite green, pyright clean, no real `claude`), not behaviours a one-line
edit can toggle; the instrument that checks them is running them.

**Reviewers are invited to invent mutations not listed here.** Three
shapes this unit is most likely to be wrong in, named as leads rather
than findings:

- **(a)** a repair-round rule that is enforced only on the *changed*
  files, so a repair that deletes a file rather than editing it escapes
  every check;
- **(b)** an interaction between Rule-F and the `V`-set rule — a file
  that is both foreign and previously-valid should take Rule-F's branch,
  and the ordering that guarantees that is stated once (§3.8) and is easy
  to get backwards;
- **(c)** `S7`'s recomputation from `snap0` silently re-including a file
  that `S4` classified and `S5` never touched, so a stale verdict is
  applied to fresh bytes.

---

## 6. Builder decisions, made here rather than left open

- **BD1 — the elicitation fix lives in two files, not one.** A
  doctrine-only fix was rejected: the doctrine sits ~2 KB into a 231 KB
  prompt and the measured behaviour is that the producer reproduces the
  *exemplar*, not the prose, so a checklist buried there is a checklist
  200 KB from the writing. A composer-only fix was rejected: the attended
  path and the one-shot analyst read the doctrine, and leaving the
  corrected exemplar out of it would fix one producer of three. The
  anti-drift instrument is `A1` (harvest the paths from the validator's
  own refusals), not a "define once" rule about prose — because *both*
  copies are restatements of `_validate_gates`, and only a test can hold
  them to it.
- **BD2 — the repair prompt does not carry the doctrine.** It is a form
  repair. Giving it the routing materials would let it re-decide, and the
  first thing a model asked to "fix this proposal" with a full doctrine
  in context will do is improve the rationale. The record text *is*
  carried, and §3.6 says why that is not a contradiction.
- **BD3 — the repair round does not collect all refusals.** Making
  `_validate_gates` report every violation would be a second
  implementation of the validator's conditionals (drift) or a change to
  `ledger_ops` (out of scope, §"Files"). Instead the repair carries the
  first refusal **plus** Set-C **plus** an explicit statement that the
  validator reports only the first problem. §1.2 is the measurement that
  makes this the load-bearing decision of the unit, and §7.3 declares the
  residual honestly: whether the checklist does the work the refusal line
  cannot is measured by the first post-merge `repair round: X of N
  cleared` line, not asserted here.
- **BD4 — deletion, not restoration, for a refused repair.** Restoring
  the pre-repair bytes was designed and rejected: it makes the worker a
  *writer* of proposal content it composed from a cache, with new failure
  modes (partial write, encoding), for a case that must not happen if the
  narrowed scope works. Deletion is the policy this pipeline already has
  for output it cannot trust; the record stays pending and the next run
  re-analyzes. The cost is one wasted cycle for those records and it is
  visible in the log.
- **BD5 — no separate cap on the repair set.** `E ⊆ written1 ⊆` the
  batch, and the batch is capped. A second cap would be a constant with
  no independent meaning.
- **BD6 — `FOLLOWON_FAILURE_CAP` is a pinned constant, not config.**
  Following `ESCALATE_*` (`worker.py:107-111`): "changing them is an edit
  to the pin, not a config file". The two things that *are* env-readable
  are the ones whose wrong value is a live hazard (the timeouts) or whose
  purpose is to be an off switch (`SELF_LEARN_REPAIR`).
- **BD7 — the backoff gate sits at the run-end follow-on site.**
  `_open_window` is shared with `kick`; putting the gate inside it would
  let a counter refuse a human. `E7`/`M32` pin this.
- **BD8 — no new notification on suppression.** `_maybe_escalate` and the
  staleness alarm already surface a stalled queue, and the alarm is
  *correct* here because `worker.last-run` is untouched on a failed run.
  The residual (suppression is log-only) is declared, not smuggled.
- **BD9 — `_SINGLE_PROMPT_TEMPLATE` gets the checklist but not the repair
  round.** Same producer, same defect, one-line fix. The one-shot path has
  its own 120 s budget (`analyst.py:31`), its own `AnalystError` contract
  and exactly one parse attempt with no reprompt (`analyst.py:34-38` —
  r1 cited `:31-35`, which straddles the two *(r1 gate NOTE 11)*);
  giving it a repair round would be a
  second unit's worth of design for a path that already has a human in
  the loop.
- **BD10 — two switches exist because the working tree is production.**
  `SELF_LEARN_REPAIR=0` and `SELF_LEARN_INVOKE_TIMEOUT_SECS` mean a
  misbehaving change can be neutralised by an env var in the systemd unit
  or the shell, not by editing code that is simultaneously executing.
  **Flag-day notes for the merge:** (i) the next kick after merge runs
  the new code against a live ledger that currently has `worker.dirty`
  set and 17+ leftovers, so expect a batch of 15 with a repair round and
  a sentinel hold up to ~40 min; (ii) the worker reads the doctrine
  PACKAGE-relative (`package_skill_refs`, `worker.py:129-135`), so the
  corrected exemplars are live at merge — but the **deployed** copy at
  `~/.claude/skills/self-learn/references/routing-doctrine.md`, which
  `commands/review.md` step 2 reads, is written by `install.sh` and is
  **not** updated by a merge. The attended path keeps the old exemplar
  until the user re-installs. Say this in the merge report.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 Not built, with reasons

- **`--bare`** — strictly stronger isolation than `--strict-mcp-config`
  (skips hooks, LSP, plugin sync, auto-memory, CLAUDE.md
  auto-discovery), and **refused**: its own help text states OAuth and
  keychain are never read under it, and the unattended worker has no
  `ANTHROPIC_API_KEY`. Adopting it would break every run. Recorded so it
  is not re-proposed as the obvious upgrade; if the worker ever gains an
  API key, this is the first thing to reconsider.
- **Narrowing the *batch* invocation's write scope** to the batch's
  proposal paths. It would shrink the blast radius, and it is refused
  here: it does **not** address FW-84's measured incident (the attended
  session was working on records *in* the batch), and a wrong rule means
  the analyst cannot write at all — a total-pipeline flag day against the
  T13-pinned, twice-verified rule set. Handed to FW-84 (§8).
- **Multi-error validation** — see BD3.
- **Repairing `card:`/lint refusals** — needs the section registry in the
  repair prompt, which reopens the re-judgment surface; zero occurrences
  in the measured corpus.
- **Repairing merge proposals** — zero occurrences; Set-J does not cover
  merge fields.
- **TARGET-sourced quote containment** — `g0.canon.evidence`,
  `t3a.depth_behind_rule.evidence`, `t4.depth_behind_rule.evidence` are
  not machine-checked (U-schema §3.7 item 1, **FW-50**). The repair round
  can write an unverifiable TARGET quote exactly as round 1 can; it is no
  worse, and the human card is the only reader that can catch it.
  Unchanged, and named so "the repair round is fabrication-safe" is not
  read as more than §3.5's four legs claim.
- **Changing `BATCH_CAP`** — §3.9, and re-ranked in §8.

### 7.2 ACCEPTED residual — a repair that clears one defect and leaves another is deleted

Measured (§1.2, §9-X2): 9 of 13 refused files carry ≥2 independent Set-C
violations, and the validator names one. The mitigation is the checklist
(BD3), not a second round. A file whose repair clears the named refusal
and leaves a sibling violation is deleted at `S8`, its record stays
pending, and the next window re-analyzes it from scratch.

**The single-sample caveat applies to the acceptance, not just to the
figure** *(r1 gate NOTE 12; stated in full at §1.2)*. The 8/1/4
distribution comes from the **replay** corpus alone; the live run's 7
schema refusals had a different profile and were never censused, and the
two logs disagree on the reported refusal for every one of the 12 ids
they share. So this residual is accepted on a **one-sample** basis, and
the acceptance is explicitly conditional: it says "one round plus the
checklist is the right *first* bet", not "one round is enough". What
would change it is the post-merge `repair round: X of N cleared` series —
which is a second sample, from live data, of exactly the quantity this
paragraph is guessing at.

**Accepted, not deferred.** A second repair round would double the model
budget per run against a population this unit has no measurement for, and
it is the kind of loop that becomes permanent. The honest instrument is
the `repair round: X of N cleared` line: if the first post-merge week
shows X consistently far below N, the answer is a better checklist or a
better exemplar, not a third invocation.

**To be recorded in `03-decisions.md` as a settled row (next free number,
`S-30` at time of writing), landing in the same commit as the build** —
campaign §1's disposition rule, following `U-pathed`'s S-24/S-25 and
`U-table`'s S-27/S-28 precedent.

### 7.3 DISCLOSED — FW-84 is only half-closed here, and the other half has a named owner

**What this unit closes:** the destruction of attended proposals that
were **validated** before the worker's landing ran (Rule-F, §3.8) — which
is the destructive half of the measured incident, and the half the
operator had to recover from by routing with `--dest`, proposal
unconsulted.

**What it does not close, explicitly:**

- an attended proposal **written but not yet validated** during the model
  window carries no `record_sha` and is indistinguishable from model
  output; it is validated, stamped, or deleted as today;
- an attended proposal **edited after validation and caught mid-edit**
  satisfies Rule-F's F-b but fails F-a, so it is deleted. **This is the
  cost of BLOCKER 1's fix and it is paid deliberately** *(r1 gate)*:
  immunity on sha-match alone was model-reachable, and the same immunity
  that would have saved this file would have handed the analyst's own
  invalid output a permanent bypass of containment, derivation and
  deletion (`D6(i)`). The outcome for this file is **identical to
  today's**, so the fix is a non-regression, not a new loss;
- the analyst's Write tool can **overwrite** an attended proposal at the
  same path before landing runs at all — no landing-time rule can undo
  that;
- backoff suppression is visible only in `worker.log`; `fast_status` and
  the UI do not report it.

**Choice made, and why (a) was not taken in full:** a complete attribution
fix means real per-file provenance — parsing `--output-format stream-json`
tool-use events, or a per-record lease, or create-only semantics for
analyst writes — each of which is a unit's worth of design against a
version-fragile surface. Doing it inside U-repair would put the unit's
elicitation fix (the thing that takes yield from 13% to something usable)
behind an unrelated redesign. So: this unit ships the **cheap, sound,
in-lane** guard, refuses to enlarge the blast radius (`D4`, `M25` — the
regression that criterion exists to catch is one this unit could easily
have introduced), and hands the rest to **FW-84**, whose row already
sequences it "with or immediately after U-repair".

**Operational mitigation until FW-84 lands, to be repeated in the merge
report:** do not run an attended review session while a worker window is
open — `cache_dir()/worker.window` holds the live pid — and if a card's
proposal vanishes mid-session, route with an explicit `--dest`.

**To be recorded in `03-decisions.md` as `S-31`**, same commit as the
build: *the worker leaves a proposal it did not write, identified by a
matching `record_sha`, entirely alone; full producer attribution is
FW-84's.*

### 7.4 Handed to `03-decisions.md`

Two rows, both landing with the build: `S-30` (§7.2) and `S-31` (§7.3).

---

## 8. What this spec re-ranks, refuses, and corrects

**Against the FW-83 research doc's §"Candidate fix scope"** (evidence-
ranked input, explicitly non-binding):

| item | disposition |
|---|---|
| 1. elicitation contract | **Kept as rank 1**, and sharpened: the fix is the *exemplar*, not the prose (§1.1's copying diagnosis, which the research doc does not make). |
| 2. one bounded repair round | **Kept**, and re-shaped by a measurement the research doc does not have: the stacked-defect census (§1.2) makes the *checklist*, not the refusal line, the load-bearing content of the repair prompt. |
| 3. timeout headroom | **Split.** Raising the cap is adopted (900 → 1800, §3.9). Lowering `BATCH_CAP` is **refused**: the evidence establishes batch size is not a quality lever and is silent on it as a throughput lever, so changing it would be an unmeasured change to the drain's characteristics. |
| 4. follow-on backoff | **Kept**, and corrected: the blind chain is *conditional on leftovers > 0* (§9-X5), which the FW-83 row's phrasing invites a reader to miss. |
| 5. `--strict-mcp-config` | **Kept, and verified** rather than assumed (§9-X1). `--bare` considered and refused (§7.1). |

**One correction to the research doc**, offered so the two documents do
not disagree silently: its failure-catalog table records **7** refusals
of `t4.depth_behind_rule.target` in the replay. The run's own log,
`misc/evidence-2026-08-08-worker-maiden/scratch-validation.log`, records
**8** (`lrn-0f56868d`, `10fc232c`, `4b8c3ec2`, `4f89e33a`, `4ffc006f`,
`84596839`, `b44c89e1`, `fe16fceb`). The log is the primary artefact and
the column totals still sum to 13; nothing downstream of the table
changes.

**Handed to other units:**

- **FW-84** — full producer attribution (§7.3), plus the refused
  batch-scope narrowing (§7.1) as one candidate direction.
- **FW-50** — TARGET-quote containment remains the one fabrication leg
  neither round can machine-check (§7.1).
- **FW-82** — the backoff's log-only visibility (§7.3) is an operability
  gap that unattended review automation will want surfaced in
  `fast_status`.

---

## 9. What was executed, and against what oracle

Everything below was run on 2026-08-08/09 on this host, read-only against
the local evidence directory
(`misc/evidence-2026-08-08-worker-maiden/`, git-excluded) and the
installed CLI. No `self-learn` verb was invoked and `~/.self-learn` was
not touched.

- **X1 — `--strict-mcp-config` is accepted with no `--mcp-config`.**
  `printf 'Reply with exactly: ok' | claude -p --model claude-sonnet-5
  --allowedTools Read,Grep,Glob --disallowedTools
  Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch --strict-mcp-config` →
  stdout `ok`, `rc=0`, no diagnostic. CLI `2.1.226`. Grounds §3.11.
- **X2 — the stacked-defect census.** Over the 13 files
  `scratch-validation.log` records as deleted: reported refusals are
  8 × `t4.depth_behind_rule.target`, 3 × `t4.fs.verdict … got None`,
  1 × containment on `gates.t1.field_shaped.evidence`,
  1 × `t3.scan_terms must be null when answer is yes`. Present but
  **unreported** because the validator stops at the first: `t4.fs.verdict:
  null` in **12 of 13** (the exception is the `t3: yes` file, whose `t4`
  is correctly null) and `t4.conduct_mode: {answer: null}` in **8 of 13**.
  Distribution: 8 files with 3 independent violations, 1 with 2, 4 with 1.
  Grounds §1.2 and BD3.
- **X3 — the copying diagnosis.** `routing-doctrine.md` §5.3's `t4` block
  has the key set `{depth_behind_rule: {answer, evidence}, conduct_mode:
  {answer, evidence}, fs: {verdict, evidence}}`; the string `target`
  appears nowhere in §5.3; `answer: null` appears there only at
  `t1.separable`/`t1.cost_bearing`. **12 of the 13** refused files
  reproduce that key set with answers flipped — the exception is
  `lrn-c826137f`, which has `t3.answer: yes` and therefore correctly
  carries `gates.t4: null` and no `t4` block to copy *(r1 said "all 13";
  gate NOTE 11)*. Grounds §1.1 and §3.2 (a).
- **X4 — refusal order is fixed and fail-first.** Within `t4`:
  `depth_behind_rule.answer` → `.evidence` → `.target` →
  `conduct_mode.answer` → `.evidence` → `fs.verdict`
  (`ledger_ops.py:1244-1281`). Grounds §1.2's "fix one, meet the next".
- **X5 — the blind chain requires leftovers.** `run` clears
  `worker.dirty` when `leftovers == 0` *before* the model call
  (`worker.py:1966-1967`), so a failed run with nothing beyond the cap
  spawns no follow-on at all. Grounds §1.3 and §8's correction of the
  FW-83 row's phrasing.
- **X6 — the doctrine's exemplar is never checked against Table-1.**
  `test_composer.py::test_a19_worked_example_validates_and_the_check_can_fail`
  selects the first yaml block matching `destination: reference` **and**
  `outcome: DEMAND`, and calls `validate_proposal(proposal,
  record_text=…)` with **no** `scope=`, so `_validate_derivation` returns
  at its `scope is None` guard. Grounds `A3` — and means adding a second
  example would, unextended, either be ignored by that test or break its
  `next(...)` selector.
- **X7 — the shim fixture truncates.** `claude_shim`
  (`test_worker.py:131-139`) writes argv with `>` and stdin with `cat >`,
  both truncating; a two-invocation run leaves only the **second** call
  observable. Grounds `F5` and its "build this first" instruction.

**Executed by the r1 gate, not by this author, and attributed as such:**
the live census behind §3.8's BLOCKER-1 argument and `D6(i)` — of 6
pending records carrying a proposal, all 6 have a matching `record_sha`
and 4 are schema-invalid (`lrn-3e4c2df3`, `lrn-547d8eb6`,
`lrn-792f43c8`, `lrn-f2053910`), with `lrn-792f43c8` eligible at the time
of measurement. Read-only against the live ledger. It is load-bearing for
a BLOCKER fold, so it is named with its provenance rather than absorbed
into the `X` series as though this author ran it; the delta gate should
re-check it as it would any borrowed figure.

**Not executed, and named as such:** exact-path `Edit(...)` settings
rules were **not** probed against the live CLI. §3.7 makes that a builder
obligation with a stated fallback, rather than an assumption this spec
smuggles into a criterion.

---

## 10. Revision history

- **r1 (2026-08-09)** — first draft. Written against master `841784b`,
  after FW-84 landed; §2, §3.5's `O`-set rule, §3.8 and §7.3 exist
  because of it.
- **r2 (2026-08-09)** — blind spec gate returned **UNSOUND — 3 BLOCKER /
  4 MAJOR / 5 NOTE**; all twelve folded. The gate cite-checked all ~46
  file:line references (all resolve), independently re-derived §9-X2's
  census (every figure matched) and re-ran `X1`, so the evidence base is
  unchanged; every defect was in the normative register. Substantive
  changes: Rule-F gains its **F-a validity leg** (r1's immunity was
  model-reachable by *preserving* a `record_sha` line rather than
  computing it — measured live on 4 stamped-and-invalid proposals, one
  eligible today) → `D6(i)`, `M23a`; `S5`'s partition gains **`Φ`**, so a
  foreign file can never be deleted by the `V` rule → `D6(ii)`, `M46`;
  **Set-C and Set-E are split** — Set-C is the producer's checklist,
  Set-E is probed by the new **Table-E**, and `A5` no longer quantifies
  over Set-C (it was self-contradictory and unsatisfiable) ; the repair
  prompt's instructional content and its exclusions become criteria
  `B12`/`B13` with `M39`/`M40`; **Obs-1 gains criteria group `H`** and
  `M41`–`M44`; `B9` gains the settings-file and composer-counter legs
  that make `M12` bite; the doctrine example↔record pairing is invented
  and pinned as **Pair-1**; `S4`'s `apply` flag is specified for the
  merge branch's stamp-before-validate order (`M45`); `B6` names the log
  line the delete path actually prints; `G8` stops rejecting the safer
  implementation and its Broken clause is corrected; four small
  inaccuracies fixed (§9-X3 12-of-13, `analyst.py:34-38`, `sha_anchor`
  from `normalize`, the token arithmetic); the single-sample caveat is
  carried into §1.2 and §7.2. No renumbering: `A5`, `B6`, `B9`, `G8` and
  `D1` were rewritten in place; everything added took a new id.
