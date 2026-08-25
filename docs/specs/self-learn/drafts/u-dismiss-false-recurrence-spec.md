# U-dismiss — dismissing a FALSE recurrence suspect

**Status:** draft, round 1 · uncommitted · authored 2026-08-24 against
`self-learn` master `24f3f90`
**Queue:** wave-3 task #2 (`misc/orchestration-plan-2026-08-23.md`)
**Consumed by:** blind spec gate → orchestrator
**Live first target:** record `lrn-566216a6`, suspect nonce `b68b5811` —
**deliberately left open; this spec does not resolve it** (§12 narrates the
command without running it).

Every claim below was probed against the code at `24f3f90` or measured on a
throwaway copy of the live ledger. Line numbers are that commit's.
Mutation cells are marked **measured** or **predicted** — never blended.

---

## 0. Reading order and precedence

1. §1–§2 establish the gap and the producer defect that guarantees it will
   keep happening. §2.4 is the one finding that could change the unit's
   shape, so read it before §3.
2. §3–§5 are the three DECIDE sections (name · mechanism · reason field).
   They are ruled, with the rejected alternatives written down.
3. §6–§9 are the behaviour spec, the report surface, the exit-code table
   and the scope fence.
4. §10 is the mutation plan, §11 the test enumeration, §12 the worked
   example on the live instance, §13 the open questions **and the settled
   rulings** — N1 there is normative, not a question.

Where this spec and doc `11-telemetry-and-lifecycle.md` §2.2 disagree, §2.4
says so explicitly and the disagreement is a **finding**, not a licence to
edit canon silently.

---

## 1. Objective

`report --json`'s `recurrence_suspects` block is the derivation behind the
review skill's **"not holding" card**. A row appears there when the miner or
the worker has flagged a sighting against a routed record, and it leaves that
block through exactly two doors:

- the record stops being `routed`, or
- a human runs `confirm-recurrence <id> --event <nonce>` and the nonce lands
  in `recurrences[].ref`.

There is **no third door**. A suspect the human judges to be a matcher
false-positive has nowhere to go: it stays in `recurrence_suspects` for the
life of the routed record, on every future `report --json`, on every future
review batch's not-holding card, forever.

This unit adds the third door: one verb that records "this sighting was never
a recurrence", clears the row, and **preserves the underlying event and the
human's reason as analyst fuel** so matcher precision becomes measurable
instead of merely suspected.

**Non-objective:** deciding whether the live suspect `b68b5811` is in fact
false. That adjudication is the operator's, at the CLI, after this unit
ships.

---

## 2. Current behaviour, verified

### 2.1 The derivation — `report.recurrence_suspects`

`report.py:221-275`. A suspect row is emitted **iff** all of:

| # | Condition | Source |
|---|---|---|
| 1 | event `kind == "recurrence-suspect"` in the **tracked** plane | `report.py:242`; `telemetry.read_events`, `telemetry.py:393-435` (tracked dir only — the cache spool is invisible here) |
| 2 | `record` and `nonce` are both `str` | `report.py:249-250` — untrusted-input skip, never a crash |
| 3 | the target record exists **and** `status == "routed"` | `report.py:238-253` |
| 4 | the nonce is **not** already in `record.recurrences[].ref` | `report.py:254-255` |

`basis` is passed through verbatim and never interpreted (`report.py:256-274`).

**Measured on a copy of the live ledger** (`~/.self-learn` copied to a
scratch dir; `report.recurrence_suspects()` called directly — note that the
`report` *command* flushes, commits and pushes, `cli.py:1814-1821`, so it is
not a read-only inspection tool):

- 6 `recurrence-suspect` events in the tracked plane.
- **1** open row: `{id: lrn-566216a6, nonce: b68b5811, seen_at:
  2026-08-19T10:39:13Z, basis: miner-match}`.
- Why the other five are gone: `lrn-c9044f8c` **superseded** (condition 3);
  `lrn-ea833a5b` routed with both of its nonces already in `recurrences`
  (condition 4); `lrn-3c1ed719` **superseded**, one nonce confirmed, one
  (`ddb78f03`, `title-token-overlap`, 2026-08-23) silently dropped by
  condition 3.

That last case is worth naming: the only thing that has ever cleared a
false suspect on this ledger is the target record being superseded for an
unrelated reason. The mechanism works by accident, not by design.

### 2.2 The suspect event has no polarity field to flip

Three producers, one payload shape, `telemetry.spool_quiet("recurrence-
suspect", record=…, origin=…, basis=…)`:

| Site | Basis | Meaning |
|---|---|---|
| `miner.py:1072` (`_raise_recurrence_suspect`, called from the fires crossover `miner.py:1486` and the backfill `miner.py:1506`) | `fire-violated` | the model itself reported breaking this routed rule |
| `miner.py:1322` (the matcher, in `_reconcile_and_land`) | `miner-match` | a mined candidate was claimed to be the same lesson as this routed record |
| `worker.py:2811` (`_recurrence_suspects`) | `title-token-overlap` | a new pending record's title overlaps a routed one (Jaccard ≥ `SUSPECT_JACCARD`) |

**Three sites, three LIVE bases — a fourth, `origin-match`, is RETIRED.**
It was removed by FW-49 (2026-08-02) as provably unreachable, documented at
length in `worker.py:2750-2773`. Nothing emits it any more; it survives only
as prose in a `report.py:259` comment, a label in
`ui/src/self_learn_ui/models.py:866`, and hand-spooled test fixtures
(`test_g3_substrate.py:139`, `test_m2_verbs.py:287`,
`test_round3_fixes.py:948`). **A builder must not treat those four-basis
comments as a live producer list** — the analyst's contingency table is
3 × 5, not 4 × 5 (§5), and any live-basis enumeration this unit writes has
three rows. Those stale comments are not this unit's to fix (§9 item 13).

The live event, verbatim from `~/.self-learn/telemetry/2026-08.komi-hypr.jsonl`:

```json
{"actor":"komi-hypr","basis":"miner-match","kind":"recurrence-suspect",
 "nonce":"b68b5811","origin":"transcript:8c746bbd-917f-4218-ad9a-5fa67bef95ed#L361",
 "record":"lrn-566216a6","schema_version":2,"ts":"2026-08-19T10:39:13Z"}
```

Fields present: `actor · basis · kind · nonce · origin · record ·
schema_version · ts`. **There is no `disposition`, no `polarity`, no
`status` field on a suspect event.** The work order's first hypothesis —
"the matcher writes suspects with a polarity field the verb can flip" — is
**false**, measured. Dismissal must therefore write a *new* record
somewhere.

Two further facts constrain where:

- Telemetry is append-only by construction and the tracked plane is written
  only by `telemetry.flush` (`telemetry.py:225-…`). Nothing in this unit
  rewrites or deletes an event; the "preserve the event" requirement is
  satisfied trivially by not touching it.
- `EVENT_KINDS` is a **closed frozenset** (`telemetry.py:75-89`) and adding a
  member is a `SCHEMA_VERSION` bump (currently `3`, `telemetry.py:69`).

### 2.3 What `confirm-held` already is — the working name is taken

`confirm-held <id>` is **a shipped verb since M2**:

- `verbs.confirm_held`, `verbs.py:4325-4364` — writes `last_confirmed`
  (today's date) and commits `self-learn: confirmed holding lrn-…`.
- Registered `cli.py:306-307`, dispatched `cli.py:1321-1324`, member of
  `VERB_COMMANDS` `cli.py:1876`, exported `verbs.py:164`.
- Documented: doc 11 §2.5 table row 2; `SKILL.md:42`.

It also **does not clear a suspect**: §2.1's derivation reads
`recurrences[].ref` and `status`, never `last_confirmed`. So "just run
`confirm-held`" is not a workaround for the gap, and reusing the name for a
different write is not available. §3 rules on this.

### 2.4 FINDING — the `miner-match` producer is polarity-inverted, and that
guarantees a steady supply of false suspects

This is the reason the unit exists and the reason it must not "fix the
producer" instead (§9 item 2).

**The reader is asked for a DEDUPE claim.** `_PROMPT_TEMPLATE`,
`miner.py:684-745`, defines the field:

```
"match": {"record": "lrn-…" | null, "status": "pending" | "routed" | "rejected" | null}
```

and the rule directly under it (`miner.py:723-725`):

> `match` reconciles against the LEDGER INDEX below — **if a candidate is the
> same lesson as an existing record, name it** (the CLI verifies your claim;
> a wrong id demotes the candidate).

Nothing in the prompt asks whether the rule was *broken*. The
correctly-polarised channel for that is a separate array, `fires[]`, whose
entries carry `"outcome": "complied" | "violated"` (`miner.py:714-716`), and
only `violated` raises a suspect (`miner.py:1484-1487`, basis
`fire-violated`).

**The CLI reads the dedupe claim as a recurrence claim.**
`_reconcile_and_land`, `miner.py:1318-1332`: when the matched record's status
is `routed`, it spools a `recurrence-suspect` with basis `miner-match`.

**The same run's journal says the opposite, in plain words.** The internal
outcome for that branch is `"recurrence"` (`miner.py:1327`), and the
near-miss fold maps it to disposition `already-canon`
(`_NEARMISS_DISPOSITION`, `miner.py:1089-1104`) with the human-facing reason
`"this is already reflected in an existing lesson"` (`_NEARMISS_REASON`,
`miner.py:1108-1115`).

So a single observation is written into two planes with **opposite
meanings**: the journal calls it *"already covered"*, the telemetry plane
calls it *"the rule may not be holding"*.

Doc `11-telemetry-and-lifecycle.md` §2.2 takes the telemetry side —
*"A new capture that matches an already-routed lesson is a recurrence —
evidence the rule is absent, weak, or only partial."* That is a design
assumption about human capture behaviour, and it does not survive contact
with a machine miner that is separately instructed to name duplicates.

The UI layer already documents the weakness without acting on it
(`plugins/self-learn/ui/src/self_learn_ui/models.py:852-868`):
`_BASIS_LABELS["miner-match"] = "a transcript matched this rule's text"`,
with the comment *"text-similarity heuristics that can fire on a lesson
nobody actually violated."*

**Consequence for this unit:** false suspects are a *structural* output of
the current producer set, not an occasional accident. A verb that clears
them one at a time is the correct first move precisely because the
alternative — silencing `miner-match` — destroys the data needed to decide
whether silencing it is right (§9 item 2, §13 Q3).

---

## 3. DECIDE — the verb is `dismiss-suspect`

```
self-learn dismiss-suspect <ID> --event <NONCE> --why <REASON> [--note TEXT] [--no-push]
```

**Ruled: `dismiss-suspect`.** Reasons, in order of force:

1. **`confirm-held` is taken** (§2.3, measured). Overloading it would make one
   verb write two unrelated frontmatter keys (`last_confirmed` vs a dismissal
   list) selected by flag presence — the shape the project already refused
   for `confirm-recurrence`/`--tolerate`'s note (`verbs.py:4258-4260`: the
   note lands in `recurrences[].note`, *never* `resolution_note`).
2. **The object dismissed is the machine's CLAIM, not the recurrence.** A
   recurrence that never happened cannot be "dismissed"; the suspect can.
   `confirm-recurrence` / `dismiss-suspect` reads as confirm-the-thing /
   dismiss-the-claim, and the two share an identical `<id> --event <nonce>`
   surface, which is the shape a human already has in muscle memory.
3. **It conflates nothing.** "The rule held" (a claim about the world,
   `confirm-held`) and "the matcher was wrong" (a claim about the
   instrument) are independent. The live instance shows both being true at
   once (§12) and they still want two commits, because a future operator
   filtering `git log` for matcher noise must not have to parse rule health
   out of the same subject line.

**Rejected — `confirm-held --event <nonce>`.** Rejected on (1) and (3). It
also inverts the burden: a suspect can be false because the *match* was
wrong (different lesson entirely), in which case nothing at all was observed
about whether the rule held, and stamping `last_confirmed` would be a
fabricated observation.

**Rejected — `reject-suspect`.** `reject` is already a record-lifecycle verb
(`cli.py`, `VERB_COMMANDS`); a second, unrelated "reject" in the vocabulary
is the collision `confirm_recurrence` vs the generic `confirm` button
already cost this project once (see the F6 note at
`ui/src/self_learn_ui/keymap.py:88-102`).

**Rejected — `dismiss-recurrence`.** Reads as "dismiss the recurrence"
i.e. tolerate it, which is the *opposite* of this verb.

Commit subject (pinned, new row in doc 11 §2.5):

```
self-learn: suspect dismissed on lrn-<id>
```

---

## 4. DECIDE — the mechanism is a record frontmatter list, not a telemetry event

**Ruled: a new append-only frontmatter list `dismissed_suspects[]` on the
target record.** Not a field flip (impossible, §2.2), not a new event kind,
not a hybrid.

### 4.1 Why not a new telemetry event kind

A `recurrence-dismissed` event is the intuitive shape — the suspect is a
telemetry claim, so its refutation looks like one too. It fails on the verb
contract:

- **A telemetry-only verb cannot honour the exit-code contract.** Verbs write
  a ledger file and commit it inside `_ledger_write` (`verbs.py:466-491`) →
  `_stage_and_commit` (`verbs.py:492-508`). Exit 3 (push failed), 6 (git
  failed pre-write) and 7 (half-written) are all *statements about that
  commit*. A verb that writes only to the cache spool has no commit and all
  three codes become vacuous.
- **The spool's flush outcome is DISCARDED on the verb path.** `main` runs
  `_flush_spool_best_effort(...)` after `_cmd_verb` and then
  `return code` — the flush's return string is dropped (`cli.py:2010-2014`).
  Only `_cmd_report` consumes it (`cli.py:1818-1819`). So a flush that
  refused or failed would leave the dismissal unrecorded while
  `dismiss-suspect` exited **0** and the operator moved on. That is the
  silent-failure shape this project has already been burned by twice
  (`cli.py:1325-1352`'s 6-vs-7 note).
- **It touches the closed set and bumps `SCHEMA_VERSION`** — a real edit, but
  a cheap one, and this spec does not lean on it. `telemetry.py:63-68` calls
  the bump *"honest bookkeeping, not a migration"*, and says why: no consumer
  filters on the number (`read_events`, `report.gather` and
  `worker._recurrence_suspects` all key on `kind` alone). Listed for
  completeness only; the two legs above — the vacuous exit codes and the
  discarded flush outcome — carry the decision on their own.

### 4.2 Why the record is the right home, measured

- **The filter already reads the record.** §2.1 condition 4 is
  `record.recurrences[].ref`. Adding a dismissal clause is one more clause in
  the same loop over data already in hand — no second read, no new plane.
- **The record commits inside the verb**, so 0/3/6/7 mean exactly what the
  review skill says they mean.
- **Frontmatter is not a whitelist — measured.** A copy of
  `lrn-566216a6.md` with a hand-written `dismissed_suspects:` block parses
  through `Record.from_path` without error and round-trips the value intact.
  So an older `self-learn` reading a record written by the new verb degrades
  to ignoring the key; it does not crash. (A `records.py` accessor +
  validator is still required so the *verb* cannot write garbage — see §6.2.)
- **It cannot leak into compiled canon — measured.** `compilers.py` contains
  no reference to `recurrences`, `last_confirmed`, or `follow_up`; the
  compiled entry is built from `record.type` / `trigger` / `instruction` /
  `fact` / `id` only (`compilers.py:257-263`, `1055-1056`). A new metadata
  key is invisible to every destination surface.
- **The telemetry event survives untouched**, which is the "analyst fuel"
  requirement, satisfied by doing nothing rather than by a mechanism.

### 4.3 The entry shape

```yaml
dismissed_suspects:
  - ref: b68b5811                                        # REQUIRED — the filter key
    ts: '2026-08-19T10:39:13Z'                           # REQUIRED — copied OUT of the event
    why: rule-followed                                        # REQUIRED — see §5
    origin: 'transcript:8c746bbd-…#L361'                 # copied out of the event
    basis: miner-match                                   # copied out of the event
    dismissed_at: '2026-08-24'                           # when a human ruled
    note: 'L361 shows the model stopping a benchmark …'  # optional free text
```

Each key earns its place:

- **`ref` is REQUIRED here, and this is a deliberate asymmetry with
  `recurrences[]`.** In `recurrences[]` the ref is explicitly *"a courtesy
  pointer, non-load-bearing"* (doc 11 §2.2; `_validate_recurrence`,
  `records.py:780-788`, requires `ts` + `origin` and **not** `ref`), because
  the confirmed recurrence stands alone as a fact about the world. A
  dismissal is a fact about *one specific machine claim*: without the nonce
  it clears nothing and means nothing. The validator must require it.
- **`ts` and `origin`** follow doc 11 §2.2's minimal-facts rule — copied out
  of the event so the record stands alone when telemetry (explicitly "cheap
  truth", `telemetry.py:1-30`) is lost.
- **`basis` is copied even though `recurrences[]` does not copy it.** It is
  the analyst's x-axis: matcher precision is `dismissals ÷ suspects` *per
  basis*, and if the telemetry file is lost the basis is unrecoverable. This
  is the one field whose loss would defeat the unit's stated purpose.
- **`dismissed_at` (a date, same granularity as `last_confirmed`,
  `verbs.py:4344`) is distinct from `ts`** and answers a different question.
  `ts − dismissed_at` is the pollution latency: how long a false row sat in
  every review batch. That gap is the metric this unit exists to shrink, and
  it is unrecoverable if only one timestamp is kept.

---

## 5. DECIDE — the reason is a required `--why <enum>`, with `--note` optional

**Ruled: `--why` required, chosen from a closed list; `--note` optional free
text on top.** Proposed list (routed upward as §13 Q1 — it binds a schema):

| `--why` | Means |
|---|---|
| `rule-followed` | the sighting shows the rule being FOLLOWED, not broken |
| `unrelated` | the matched record is about something else entirely |
| `duplicate` | a re-derivation of the same lesson; no failure occurred |
| `misattributed` | a real recurrence, but of a different routed rule |
| `other` | none of the above (`--note` strongly advised) |

**Why a reason is mandatory at all.** `confirm-recurrence --tolerate` already
refuses without one, in these words (`verbs.py:4249-4253`):

> `--tolerate needs --note: 'the rule stays' without the why is exactly the
> dead-letter 11 §2.2 exists to prevent`

"This was never a recurrence" without a why is the same dead letter, and it
is worse in one respect: a tolerated recurrence at least leaves a
`recurrences[]` row that a later reader can re-derive from the event, while
an unreasoned dismissal erases a signal and explains nothing.

**Why an enum and not free text.** The dismissal's purpose is analyst fuel;
free text alone is unanalysable. `basis × why` is a 3×5 contingency table
— three LIVE bases (§2.2), five reasons — that answers the question §2.4
raises: *is `miner-match` systematically mis-polarised, or occasionally
wrong?* Counting, rather than reading.
The project already runs this pattern: `DECLINE_REASONS`
(`telemetry.py:96`), a closed enum precisely so the offer ledger is
countable.

**Why one flag and not two required flags.** Friction is the enemy here.
False suspects are structural (§2.4), so the operator will run this verb
often; a required essay per dismissal means the operator does nothing and the
pollution persists — the exact failure the unit exists to fix.

**Enum enforcement lives at the CLI, not in the record validator.** argparse
`choices=` refuses a bad value with exit **2** before anything is read
(§8). The record-layer validator requires only that `why` be a non-empty
string. This is the `_BASIS_LABELS` lesson applied
(`ui/models.py:858-863`: *"Deliberately NOT a closed set — an unrecognised
basis renders verbatim … a suspect that silently loses its reason is the
defect this mapping exists to fix"*): if the enum ever grows, records written
under the old list must not retroactively fail validation.

---

## 6. Behaviour spec

### 6.1 CLI surface

Registered with the existing `_verb()` helper (`cli.py:160-186`), which
supplies `--note` and `--no-push` for free, and **without** `json_flag` —
doc-pinned: `--json` is scoped to route/reject/defer/graduate and never to
the recurrence riders (`cli.py:172-177`).

```python
ds = _verb("dismiss-suspect",
           "dismiss a recurrence suspect as a matcher false-positive (11 §2.2)")
ds.add_argument("id", metavar="ID")
ds.add_argument("--event", required=True, metavar="NONCE",
                help="the recurrence-suspect telemetry event's nonce (see report --json)")
ds.add_argument("--why", required=True, choices=DISMISS_REASONS,
                help="why the suspect is false — the analyst's x-axis")
```

Dispatch in `_cmd_verb` (`cli.py:1290-1325` block), and the name added to
`VERB_COMMANDS` (`cli.py:1866-1878`). Adding it there is what buys the whole
contract: `_home_gate` → exit 5, the `except` chain → 1/64/6/7, and the
post-verb `_flush_spool_best_effort` (`cli.py:2010-2014`).

`_finish_verb(result, "suspect dismissed")`.

### 6.2 `records.py` — the schema half

Mirror the `recurrences` trio exactly:

- property `dismissed_suspects` → `tuple(copy.deepcopy(dict(d)) for d in
  self._fm.get("dismissed_suspects") or [])` (beside `records.py:310-313`).
- `append_dismissed_suspect(entry: dict)` → validate, lazily create the list,
  append (beside `records.py:581-587`).
- `_validate_dismissal(entry)` (beside `_validate_recurrence`,
  `records.py:780-788`): non-empty mapping; `ref`, `ts`, `why` present and,
  when strings, non-empty. **`ref` required — the §4.3 asymmetry.** No enum
  check (§5).
- One clause in `_validate` beside `records.py:721-726`: if
  `dismissed_suspects` is not `None` it must be a list and each entry must
  validate.

### 6.3 `verbs.dismiss_suspect` — step order

Identical in shape to `confirm_recurrence` (`verbs.py:4242-4322`); the
deltas are marked **NEW**.

1. `home = Path(home)`.
2. **Resolve the event.** Scan `telemetry.read_events(home)` for
   `kind == "recurrence-suspect"` **and** `nonce == event_ref`. `None` →
   `VerbError`, same wording shape as `verbs.py:4272-4277` ("flush first
   (`self-learn telemetry flush`) or check `self-learn report`").
3. **NEW — verify the event belongs to this record.** If
   `event.get("record") != record_id`, refuse with `VerbError` naming both
   ids. *(`confirm_recurrence` does not do this: `verbs.py:4265-4271` filters
   on `kind` + `nonce` only, then copies the event's `ts`/`origin` onto
   whatever record id was typed. That is a latent cross-record contamination
   path in the existing verb — see §13 Q2. This unit adds the guard on its
   own verb and does **not** retrofit `confirm_recurrence`, which is out of
   scope §9 item 6.)*
4. `path = find_record_path(home, record_id)` — `LedgerOpsError` → exit 64.
5. `_scan_or_refuse([path], note)` (`verbs.py:414-434`) — P2-7 secret scan
   over the whole record file **and** `--note`, before any write.
6. `record = Record.from_path(path)`.
7. Refuse unless `record.status == "routed"` — suspects only exist against
   live routed coverage (§2.1 condition 3; the same rule
   `confirm_recurrence` states at `verbs.py:4282-4286`). **This guard needs a
   dedicated test: the equivalent guard on `confirm_recurrence` is currently
   unmutable — see §10 M4.**
8. Refuse if `event_ref` is already in `record.recurrences[].ref`: *you
   cannot dismiss what you confirmed.*
9. Refuse if `event_ref` is already in `record.dismissed_suspects[].ref`:
   double-dismissal, the symmetric guard to `verbs.py:4287-4292`.
10. `hold = sentinel.hold()`; `sentinel.heartbeat()`.
11. Build the §4.3 entry; `record.append_dismissed_suspect(entry)`
    (`RecordError` → `VerbError`).
12. `message = f"self-learn: suspect dismissed on {record_id}"`.
13. `with _ledger_write(home): record.write(path); staged, sha =
    _stage_and_commit(home, [path], message, note)`.
14. `push = _push_ledger(home, no_push)`.
15. Return `VerbResult(action="dismiss-suspect", …)`.
16. `finally: hold.release()`.

Export `"dismiss_suspect"` from `verbs.__all__` (`verbs.py:143-181`) and the
enum as `DISMISS_REASONS`.

### 6.4 Directional guard asymmetry — deliberate

`dismiss-suspect` refuses a nonce already confirmed (step 8), but
`confirm-recurrence` is **not** taught to refuse a nonce already dismissed.

This is not an oversight. Dismissal is the cheap, low-stakes action (clearing
instrument noise); confirmation is the expensive one (it feeds recurrence
pressure, which drives revise/escalate/retire). Letting the expensive action
override the cheap one while forbidding the reverse is the correct polarity
for a reversal of judgment, and it keeps this unit's diff out of an existing
shipped verb. A record that ends up carrying the same ref in both lists reads
as "dismissed, then reconsidered", which is an honest audit trail; §2.1
condition 4 filters the row on the `recurrences` entry regardless.

---

## 7. Report surface

Three changes, all in `report.py`.

**(a) The filter — the whole point.** One clause in
`recurrence_suspects`, immediately after the confirmed check
(`report.py:254-255`):

```python
if any(d.get("ref") == nonce for d in record.dismissed_suspects):
    continue  # dismissed as a matcher false-positive
```

Order relative to the confirmed check does not change behaviour (both
`continue`); place it second so the cheaper, older check runs first and the
comment pair reads as one policy.

**(b) `routed_live[]` rows gain a count.** Beside
`"recurrences": len(record.recurrences)` (`report.py:1748`), inside the
`if record.status == "routed":` branch that opens at `report.py:1734`:

```python
"dismissed_suspects": len(record.dismissed_suspects),
```

Symmetry, one line. Without it the routed_live row asserts a recurrence
count with no denominator for how much of that record's suspect traffic was
noise.

**(c) NEW top-level facts key `suspects_dismissed`.** Flat rows across
**every** record regardless of status — `{id, ref, ts, dismissed_at, basis,
why}`.

**The attachment site is exact, and getting it wrong silently loses data.**
`gather` does **not** call `_walk_records`. That helper is defined at
`report.py:86` and called only at `:109`, `:181`, `:238` and `:1348` — all
outside `gather`; the sole mention of the name inside `gather` is a comment
at `:1716` saying the inline walk reuses its widened skip set. `gather` runs
its **own** bucket walk, opening at `report.py:1707`
(`for bucket in discover_buckets(home):`) and descending through
`for sub in ("pending", "resolved")` → `for path in sorted(directory.glob(…))`
→ `record = Record.from_path(path)` at **`:1715`**.

Collect the dismissal rows in that per-record loop **immediately after
`:1715`'s `Record.from_path`, before any status branching** — i.e. before
the `if record.source == "session"` block (`:1720`), before
`if record.routing is not None` (`:1732`), and before the
`if record.status == "routed" / elif rejected / elif superseded / elif
deferred` chain that starts at `:1734`.

Why the placement is load-bearing: §7b's `routed_live` row lives *inside*
the `status == "routed"` branch, and the obvious move is to append the
dismissal rows beside it. That would emit rows only for records still
routed — so the moment a record is superseded, every dismissal ever made
against it disappears from the analyst surface. That is exactly the hazard
**M16 / T-DISMISSALS-SURVIVE-SUPERSEDE** exists to catch, and §2.1's measured
live data shows it is not hypothetical: two of the six suspect events on this
ledger are already invisible to `recurrence_suspects` for precisely that
reason. The dismissal plane must outlive the rule it was made against.

(c) is what satisfies the "distinguishable in report" requirement. (b) alone
does not: a count cannot be joined to a `basis`, so it cannot answer the
§2.4 question. And the per-record field alone is scattered across 141 record
files, which is not an analyst surface.

**Text renderer: no change.** `render_text` (`report.py:1847+`) has never
rendered `recurrence_suspects` — verified: the only occurrences of that name
in `report.py` are `__all__` (`:54`), the definition (`:221`) and the
`gather` key (`:1814`). Suspects are a `--json`/UI surface; dismissals stay
in the same plane rather than inventing a text section for a sibling of an
invisible field.

**UI: no change required.** `_build_holding_rows`
(`ui/src/self_learn_ui/models.py:881-930`) builds the not-holding cards from
`report_data["recurrence_suspects"]`. A dismissed suspect vanishes from that
list at the source, so the card disappears with no UI edit. A `d` key
binding is §9 item 4.

---

## 8. Failure modes — every exit code and its trigger

Verified against `cli.py:65-76`, `cli.py:1325-1352`, `gitops.EXIT_GIT_FAILED`,
`ledger.EXIT_NO_HOME`, and the `_cmd_verb` handler chain.

| Code | Constant | Trigger for `dismiss-suspect` |
|---|---|---|
| **0** | `EXIT_OK` | Dismissal committed. (Push skipped by `--no-push`, or by the no-remote guard, still exits 0.) |
| **1** | `VerbError.exit_code` | Every refusal in §6.3 steps 2, 3, 7, 8, 9: no tracked `recurrence-suspect` event with that nonce · the event names a different record · the record is not `routed` · the nonce is already confirmed · the nonce is already dismissed. **Also** `SecretRefusal` (P2-7) — a secret in the record file or in `--note`, refused before any write. |
| **2** | *(argparse)* | A missing `--event`/`--why`, or a `--why` outside `choices`. argparse's own code; **the builder must not intercept and remap it** — `cli.py:66-70` pins 2 to `proposal validate`'s scan hit and notes argparse's 2 "cannot occur on a well-formed programmatic invocation". |
| **3** | `EXIT_PUSH_FAILED` | Commit landed; `push_if_remote` failed. Dismissal **kept**. |
| **4** | `EXIT_REBASE_CONFLICT` | Commit landed; the push's `pull --rebase` hit a conflict. Dismissal kept. |
| **5** | `EXIT_NO_HOME` | `_home_gate` — home missing or not a git repo. Refused before `find_record_path`, so a bad home never surfaces as "no such record". |
| **6** | `EXIT_GIT_FAILED` | A `GitOpsError` that is **not** half-written — e.g. the commit lock could not be taken. Nothing mutated. |
| **7** | `EXIT_HALF_WRITTEN` | `gitops.HalfWrittenError`: the record was rewritten, then `stage`/`commit` failed. Rendered through the single half-written renderer (`cli.py:1348-1352`). |
| **64** | `EXIT_USAGE` | `LedgerOpsError` — unknown or malformed record id. Deliberately not 2. |

**6 vs 7.** 6 = git failed with nothing mutated; 7 = the record changed and
the commit did not. The split is made in `_commit_ledger`
(`verbs.py:511-534`). `dismiss-suspect` mutates only one file and only inside
`_ledger_write`, so its 7-leg is a single-file half-write — the simplest case
`self-learn reconcile` handles.

**A note on the flush.** `main` runs `_flush_spool_best_effort` after the
verb and discards its result (`cli.py:2010-2014`). Because this unit writes
nothing to the spool (§4.1), that discard costs it nothing — which is itself
part of why the record was chosen over an event.

---

## 9. Out of scope

Each item is a real thing a builder might reach for.

1. **Resolving the live instance.** `lrn-566216a6` / `b68b5811` stays open
   through this unit's build and its gate. §12 is a narration, not a step.
2. **Fixing the `miner-match` polarity inversion (§2.4).** Not this unit, and
   deliberately not: the suspect stream is the *denominator* of matcher
   precision, and silencing the producer before dismissals exist destroys the
   only data that could justify silencing it. Sequencing: ship the verb →
   accumulate `basis × why` → then decide. Recommended as an FW row, worded
   as a finding, not a fix. **Do not change `miner.py`, the reader prompt, or
   `_NEARMISS_DISPOSITION` in this unit.**
3. **Editing doc 11 §2.2's "a match is a recurrence" assertion.** §2.4 shows
   it is contradicted by the miner's own prompt; correcting canon is a
   separate, human-ratified motion. This unit *adds* the dismiss resolution
   to §2.2's resolution list and adds the §2.5 verb row; it does not rewrite
   the assertion.
4. **UI (`self_learn_ui`) work.** No `d` keymap entry, no button, no
   `routes.py` verb mapping, no `HoldingRow` field, no change to the card's
   generated text (`models.py:917-925`). The clearing behaviour falls out of
   the report for free (§7).
5. **Review-skill card UX beyond the one new resolution mapping.** Exactly one
   bullet joins the four in `commands/review.md:210-221`, plus one sentence
   on reading `basis`. No new card kind, no reordering, no exit-code table
   edits.
6. **Changing `confirm_recurrence`'s shipped CODE.** No cross-record guard
   (§13 Q2), no already-dismissed guard (§6.4), no signature change, no
   behaviour change of any kind in that function or its CLI wiring.
   **This fences code, not tests.** Adding a *test* over `confirm_recurrence`'s
   existing, unchanged behaviour is explicitly IN scope and is required —
   see §13 N1 (ruled) and T-SHIPPED-NOT-ROUTED-GUARD in §11. A test that
   pins shipped behaviour changes nothing about the shipped verb; it only
   makes an already-correct guard falsifiable, which §10 A3 measured it is
   currently not.
7. **Any routing-gate change.** Strict-at-gate/light-at-file is untouched;
   this verb never reads or writes `routing`, `destination`, or a proposal.
8. **A new telemetry event kind or `SCHEMA_VERSION` bump** (§4.1).
9. **Bulk operations.** No `--all`, no dismiss-by-basis, no dismiss-by-record.
   One nonce per invocation.
10. **Permanent muting** of a `(record, basis)` pair. A future sighting of the
    same rule from a different transcript line gets a new nonce and a new
    suspect — correctly, since it is a new observation. A mute is a different
    design (§13 Q4).
11. **Un-dismissing.** Both lists are append-only. Reversal is
    `confirm-recurrence` on the same nonce (§6.4).
12. **`report`'s text renderer** (§7) and `status --fast` (pending-only
    frontmatter scan; this field lands on routed records).
13. **The stale `origin-match` references.** FW-49 retired that basis
    (§2.2), but four-basis prose survives at `report.py:259`,
    `ui/src/self_learn_ui/models.py:866` and in three test fixtures. A
    builder will meet them while reading §2.2's producer table and must
    leave them alone: correcting them is a docs sweep touching a shipped UI
    label and three passing tests, with no behaviour change. This unit only
    declines to *propagate* the error into anything it writes.

---

## 10. Mutation plan — what a code gate must be able to break

Each mutation names the test that must go red. **Cells are marked
`measured` only where the mutation was applied to code that exists today at
`24f3f90` and the suite was actually run; every cell describing code this
unit has not yet written is marked `predicted`.**

### Measured anchors (existing code, applied and reverted 2026-08-24)

Method: mutation applied by script to the working tree, the named test files
run with `.venv/bin/python -m pytest … -q -p no:cacheprovider`, the failing
set recorded, the file restored from a byte copy, and `git status --porcelain`
confirmed empty plus a positive-control grep of the restored anchor string.

| # | Mutation | Result |
|---|---|---|
| **A1** | delete the already-confirmed filter in `report.recurrence_suspects` (`report.py:254-255`) | **measured** — exactly 1 red: `test_g3_substrate.py::TestReportRecurrenceSuspects::test_confirmed_suspect_drops_off`. 142 other tests in `test_g3_substrate.py` + `test_m2_verbs.py` + `test_miner.py` passed. |
| **A2** | delete the double-confirm guard in `verbs.confirm_recurrence` (`verbs.py:4287-4292`) | **measured** — scope `tests/test_m2_verbs.py tests/test_round3_fixes.py tests/test_g3_substrate.py` → `1 failed, 72 passed`. The single red is `test_m2_verbs.py::test_confirm_same_event_twice_refused` — same file as the mutated verb's own suite. |
| **A3** | delete the `status != "routed"` guard in `verbs.confirm_recurrence` (`verbs.py:4282-4286`) | **measured — 0 red across the WHOLE CLI suite, clean-env both sides.** Unmutated baseline: `2369 passed, 8 skipped`, rc=0. Under the mutation: `2369 passed, 8 skipped`, rc=0 (301 s). Identical — the mutation kills **nothing**. *This guard is currently unmutable.* It is the direct precedent for §6.3 step 7, so **M4 below is mandatory, not optional** — writing the guard without the test reproduces an existing hole. |

A1 and A2 are the shapes M1 and M3 will take once the code exists: a filter
clause and a double-action guard each kill exactly one dedicated test. A3 is
the counter-example that says a guard without a dedicated test kills nothing.

### The unit's own mutations — all `predicted` (no code yet)

| # | Mutation | Must fail | Basis |
|---|---|---|---|
| **M1** | drop the dismissed clause from `report.recurrence_suspects` (§7a) | **T-CLEARS** | *predicted* — A1 measured the identical shape one clause above |
| **M2** | make the dismissed clause match on `origin` instead of `ref` | **T-CLEARS, T-SECOND-SIGHTING-SURVIVES** | *predicted* |
| **M3** | drop the already-dismissed guard (§6.3 step 9) | **T-DOUBLE-DISMISS** | *predicted* — A2 measured the identical shape |
| **M4** | drop the `status != "routed"` guard (§6.3 step 7) | **T-NOT-ROUTED** | *predicted* — **A3 proves this test must be written or the mutation kills nothing** |
| **M5** | drop the already-confirmed guard (§6.3 step 8) | **T-CONFIRMED-THEN-DISMISS** | *predicted* |
| **M6** | drop the cross-record guard (§6.3 step 3) | **T-EVENT-BELONGS** | *predicted* — no existing test covers this shape (A3's neighbourhood) |
| **M7** | make `--why` optional in the parser | **T-WHY-REQUIRED** | *predicted* |
| **M8** | widen `choices` to accept any string | **T-WHY-ENUM** | *predicted* |
| **M9** | `_validate_dismissal` stops requiring `ref` | **T-VALIDATOR-REF** | *predicted* — this is the §4.3 asymmetry; nothing else in the codebase enforces it |
| **M10** | write `dismissed_at` as the event's `ts` instead of today | **T-TWO-CLOCKS** | *predicted* |
| **M11** | omit `basis` from the entry | **T-BASIS-COPIED** | *predicted* |
| **M12** | append to `recurrences[]` instead of `dismissed_suspects[]` | **T-NOT-A-RECURRENCE** | **measured** — killer: T-NOT-A-RECURRENCE (+8 collateral: T-ENTRY-SHAPE, T-BASIS-COPIED, T-TWO-CLOCKS, T-DOUBLE-DISMISS, T-DISMISSED-THEN-CONFIRM, T-ROUTED-LIVE-COUNT, T-DISMISSALS-SURVIVE-SUPERSEDE, T-REPORT-JSON). T-CLEARS green BY DESIGN, as originally predicted: the mutated write still lands in `recurrences[]`, which satisfies `report.py`’s pre-existing already-confirmed filter (§2.1 condition 4) — the row still empties, so T-CLEARS alone cannot distinguish this mutation from a correct dismissal |
| **M13** | delete the telemetry event after a successful dismissal | **T-EVENT-PRESERVED** | *predicted* |
| **M14** | commit subject changed to `self-learn: recurrence confirmed on …` | **T-SUBJECT** | *predicted* |
| **M15** | drop `"dismissed_suspects"` from the `routed_live` row (§7b) | **T-ROUTED-LIVE-COUNT** | *predicted* |
| **M16** | `suspects_dismissed` (§7c) restricted to `routed` records | **T-DISMISSALS-SURVIVE-SUPERSEDE** | *predicted* |
| **M17** | `_scan_or_refuse` moved after `record.write` | **T-SCAN-BEFORE-WRITE** | *predicted* |
| **M18** | stamp `ts` with `_now_iso()` and `origin` with the record id instead of copying both OUT of the event (§6.3 step 11 / §4.3's minimal-facts rule) | **T-ENTRY-SHAPE, T-TWO-CLOCKS** | *predicted* — added at the r2 fold; T-ENTRY-SHAPE had no killer before it (see the census) |
| **M19** | drop the `event is None` refusal (§6.3 step 2) and use the first `recurrence-suspect` event found, whatever its nonce | **T-UNKNOWN-EVENT, T-EVENT-BELONGS** | *predicted* — added at the r2 fold |
| **M20** | omit `"dismiss-suspect"` from `VERB_COMMANDS` (`cli.py:1866-1878`) while leaving the parser and dispatch intact | **T-UNKNOWN-ID, T-NO-HOME, T-CLEARS** | *predicted* — added at the r2 fold; this is the one mutation that falsifies §6.1's "adding it there buys the whole contract" claim |
| **M21** | delete the `status != "routed"` guard from the SHIPPED `verbs.confirm_recurrence` (`verbs.py:4282-4286`) — the same edit as anchor A3 | **T-SHIPPED-NOT-ROUTED-GUARD** | **measured (A3), 0 red *today*** — full CLI suite, clean-env both sides, `2369 passed, 8 skipped`, rc=0 mutated and unmutated alike. That zero IS the defect: the guard is unmutable, and T-SHIPPED-NOT-ROUTED-GUARD is written expressly to become its killer. **A gate re-running M21 after the build must see this row RED**; if it is still 0-red, the courtesy test was not written or does not assert the guard. Added at the r3 fold per the §13 N1 ruling |

A gate must run each of these and record the actual red set, replacing
`predicted` with `measured` per row. **A row that stays `predicted` after the
build is an unverified claim, not a passing criterion.**

### 10.1 Unmutated-test census

Every test in §11 must appear exactly once below. **22 of 25 are named by at
least one mutation above.** The three that are not are listed here with the
reason, per the U-pointer method: a test nobody can break is the same defect
as a criterion that cannot fail, seen from the other side — but the plan is
not padded to one-mutation-per-test, and a mutation that duplicates another's
kill teaches the gate nothing.

**Covered (22):** T-CLEARS (M1, M2, M20) · T-SECOND-SIGHTING-SURVIVES
(M2) · T-ENTRY-SHAPE (M18) · T-BASIS-COPIED (M11) · T-TWO-CLOCKS (M10, M18) ·
T-NOT-A-RECURRENCE (M12) · T-DOUBLE-DISMISS (M3) · T-CONFIRMED-THEN-DISMISS
(M5) · T-NOT-ROUTED (M4) · T-UNKNOWN-EVENT (M19) · T-EVENT-BELONGS (M6, M19) ·
T-WHY-REQUIRED (M7) · T-WHY-ENUM (M8) · T-VALIDATOR-REF (M9) · T-SUBJECT
(M14) · T-SCAN-BEFORE-WRITE (M17) · T-EVENT-PRESERVED (M13) · T-UNKNOWN-ID
(M20) · T-NO-HOME (M20) · T-ROUTED-LIVE-COUNT (M15) ·
T-DISMISSALS-SURVIVE-SUPERSEDE (M16) · T-SHIPPED-NOT-ROUTED-GUARD (M21).

**Deliberately unmutated (3):**

1. **T-DISMISSED-THEN-CONFIRM** — it asserts the *absence* of a guard (§6.4's
   deliberate directional asymmetry: dismissal refuses an already-confirmed
   nonce, confirmation does not refuse an already-dismissed one). The only
   mutation that breaks it is **writing new code into `confirm_recurrence`** —
   an already-dismissed guard — which §9 item 6 forbids. That fence is about
   shipped *code*, and this entry leans on it only in that sense: it does not
   and must not imply that *tests* over `confirm_recurrence` are out of scope.
   They are not — M21 / T-SHIPPED-NOT-ROUTED-GUARD is exactly such a test and
   is required (§13 N1). A mutation the builder is not allowed to make is not
   a gate criterion. The test's real job here is forward-looking: it goes red
   the moment a future builder adds that guard, which is exactly when someone
   should have to re-read §6.4.
2. **T-REPORT-JSON** — end-to-end plumbing (`cli.main(["report", "--json"])`
   carries `suspects_dismissed`). Every mutation that could break it — M1,
   M12, M16 — kills a narrower, more diagnostic test first. A dedicated
   mutation would duplicate a kill and point the gate at the widest possible
   surface for the least possible information.
3. **T-OLD-RECORD-STILL-VALID** — a backward-compatibility pin on the
   *absence* of a change. It already passes today, before any of this unit's
   code exists (§4.2, measured: an unknown frontmatter key round-trips
   through `Record.from_path` intact). The mutation that would break it —
   making `dismissed_suspects` required in `_validate` — is something no
   criterion here asks for; and the other candidate, returning `None` rather
   than `()` for an absent key, crashes §7a's filter and is caught by M1's
   tests first. Its value is precisely that correct code cannot kill it: it
   guards against a builder over-tightening the validator and silently
   invalidating all 141 existing records.

---

## 11. Tests — enumerated

New file: `plugins/self-learn/cli/tests/test_dismiss_suspect.py`.

Model it on `test_m2_verbs.py`: module docstring naming what is covered; an
autouse fixture setting `XDG_CACHE_HOME` **and** `SELF_LEARN_ACTOR`
(`test_m2_verbs.py:30-33`); the `Env` class over `support.make_env` with a
bare remote so `--no-push` vs push is exercisable; `env.subject()` →
`verb_subject(home)` for the commit-subject assertions. Reuse
`test_m2_verbs.py`'s `seed_routed` / `spool_suspect` helper shape
(`:280-296`) — spool an event, `telemetry.flush`, read the nonce back.

Report-side tests extend `test_g3_substrate.py::TestReportRecurrenceSuspects`
(`:148-243`), whose `_spool_suspect` helper (`:137-146`) already returns
`(nonce, ts)`.

### 11.0 Runbook — run every suite under a neutralised environment

**Always:**

```
env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT \
  .venv/bin/python -m pytest tests/ -q -p no:cacheprovider
```

An interactive shell on this host exports `SELF_LEARN_ANALYST_MODEL` and
`SELF_LEARN_ANALYST_TIMEOUT`, and both leak into
`provider.model_for("analyst", …)`. With them set, eight tests fail
(`test_u_sdka.py` ×4, `test_invocation.py` ×2, `test_route_cli.py` ×2) —
every one of them a test that configured a sentinel model and got the
exported value instead. **This is host-environment contamination, not a
defect in the tree.** Measured both ways at `24f3f90`: contaminated
`8 failed, 2361 passed`; neutralised `2369 passed, 8 skipped`, rc=0, and the
three affected files alone go from 8-failed to `150 passed`.

Capture the exit status **unpiped** — `cmd > out.txt 2>&1; echo rc=$?` — never
`cmd | tail`, which reports `tail`'s status and prints `rc=0` over a red run.

| id | Assertion |
|---|---|
| **T-CLEARS** | route → spool suspect → `dismiss-suspect` exit 0 → `gather()["recurrence_suspects"] == []`. The unit's headline. |
| **T-SECOND-SIGHTING-SURVIVES** | two suspects on the same record, different nonces; dismissing one leaves the other in the block. Guards the ref-vs-origin mutation. |
| **T-ENTRY-SHAPE** | the written entry carries `ref`, `ts`, `origin`, `basis`, `why`, `dismissed_at`; `ts` and `origin` equal the event's, not `now`. |
| **T-BASIS-COPIED** | the entry's `basis` equals the spooled event's `basis`, for a non-default value (`fire-violated`). |
| **T-TWO-CLOCKS** | with an event `ts` in the past, `dismissed_at` is today and `ts` is the event's — the two differ. |
| **T-NOT-A-RECURRENCE** | after dismissal, `record.recurrences == ()` and `record.resolution_note is None`. The polarity assertion. |
| **T-DOUBLE-DISMISS** | dismissing the same nonce twice → exit 1, one entry. |
| **T-CONFIRMED-THEN-DISMISS** | `confirm-recurrence` then `dismiss-suspect` on the same nonce → exit 1. |
| **T-DISMISSED-THEN-CONFIRM** | `dismiss-suspect` then `confirm-recurrence` on the same nonce → exit **0** (§6.4's deliberate asymmetry), and the row is gone either way. |
| **T-NOT-ROUTED** | graduate the record, then dismiss → exit 1. **Mandatory per §10 A3.** |
| **T-UNKNOWN-EVENT** | `--event deadbeef` → `VerbError` matching "no recurrence-suspect event". |
| **T-EVENT-BELONGS** | two routed records, dismiss record A with record B's nonce → exit 1, A unchanged. |
| **T-WHY-REQUIRED** | `cli.main(["dismiss-suspect", rid, "--event", n])` → 2 (argparse). |
| **T-WHY-ENUM** | `--why banana` → 2; every value in `DISMISS_REASONS` → 0. |
| **T-VALIDATOR-REF** | `Record.append_dismissed_suspect({"ts": …, "why": …})` (no `ref`) raises; a full entry does not. |
| **T-SUBJECT** | `env.subject() == f"self-learn: suspect dismissed on {rid}"`. |
| **T-SCAN-BEFORE-WRITE** | a secret in `--note` → exit 1, `dismissed_suspects` absent, no new commit. |
| **T-EVENT-PRESERVED** | after dismissal, `telemetry.read_events(home)` still contains the suspect event byte-for-byte. |
| **T-UNKNOWN-ID** | `dismiss-suspect lrn-deadbeef --event …` → 64. |
| **T-NO-HOME** | `SELF_LEARN_HOME` pointed at a non-repo → 5, nothing written. |
| **T-ROUTED-LIVE-COUNT** | `gather()["routed_live"][0]["dismissed_suspects"] == 1` after one dismissal. |
| **T-DISMISSALS-SURVIVE-SUPERSEDE** | supersede the record after dismissing; `suspects_dismissed` still carries the row (the analyst plane must outlive the rule). |
| **T-REPORT-JSON** | `cli.main(["report", "--json"])` payload carries `suspects_dismissed` with the full row. |
| **T-OLD-RECORD-STILL-VALID** | a record with no `dismissed_suspects` key parses, and `record.dismissed_suspects == ()`. |
| **T-SHIPPED-NOT-ROUTED-GUARD** | **Not in the new file — add this one to `test_m2_verbs.py`**, beside the existing `confirm_recurrence` tests. Seed a routed record, `graduate` it, then `cli.main(["confirm-recurrence", rid, "--event", nonce, "--no-push"])` → **exit 1**, with the message matching `recurrences confirm`, and the record's `recurrences` still empty. This is the courtesy test over the SHIPPED guard that §10 A3 measured to be unmutable, ruled in scope by §13 N1. Model it on the sibling `test_confirm_held_refuses_non_routed` (`test_m2_verbs.py:350-355`), which is the same shape for the same reason on the neighbouring verb. **It tests existing behaviour and changes no shipped code** (§9 item 6). |

---

## 12. Worked example — `lrn-566216a6` / `b68b5811` (narration only; NOT run)

**What the operator sees today.** `report --json` yields exactly one
not-holding row (measured, §2.1):

```json
{"id": "lrn-566216a6", "nonce": "b68b5811",
 "seen_at": "2026-08-19T10:39:13Z", "basis": "miner-match"}
```

The review skill renders it as *"Routed 15d ago. Sighted 1 time since.
Revise, escalate, tolerate, or retire?"* with the basis clause *"a transcript
matched this rule's text"* (`ui/models.py:855-868`). None of the four
offered resolutions is correct, so the operator's only options are to
fabricate one or to leave the card standing. It has been standing since
2026-08-19.

**What the evidence actually says.** The record is the testing-methodology
lesson: *"Read the system load BEFORE believing the result … a suite result
taken under unexplained load is not a measurement."* The event's origin is
`transcript:8c746bbd-917f-4218-ad9a-5fa67bef95ed#L361`, and `#L<n>` is a
1-based line index into the session jsonl (`miner.py:461`:
`lineno = s.start_line + offset + 1  # 1-based, for origins`). Line 361 of
that transcript is an assistant turn:

> "The game is actively running (`R<` state, 303% CPU, started 7 minutes ago)
> — the user is at the machine playing right now. Stopping the benchmark
> immediately: it would wreck their framerate and the perf numbers would be
> contention-contaminated, which defeats the entire purpose of this run."

That is the rule being **followed**. The miner's own journal row for the same
origin agrees, in the other plane:

```json
{"origin":"transcript:8c746bbd-…#L361","outcome":"recurrence",
 "record":"lrn-566216a6","disposition":"already-canon",
 "reason":"this is already reflected in an existing lesson","promotable":false}
```

`already-canon`, not `violated`.

**And a third plane agrees — the model's own fire report, at the identical
origin.** Verbatim from `~/.self-learn/telemetry/2026-08.komi-hypr.jsonl`:

```json
{"actor":"komi-hypr","kind":"fire","nonce":"777d6030",
 "origin":"transcript:8c746bbd-917f-4218-ad9a-5fa67bef95ed#L361",
 "outcome":"complied","record":"lrn-566216a6",
 "schema_version":2,"ts":"2026-08-23T10:41:01Z"}
```

Same record, **same origin string**, `outcome: "complied"` — and it is the
only `fire` event for `lrn-566216a6` in the whole tracked plane (measured).
A later miner run (2026-08-23) re-read transcript line 361 and classified it
through the correctly-polarised `fires[]` channel, which reports compliance;
the earlier run (2026-08-19) had already classified the *same line* through
the `match` channel, which spooled a recurrence suspect. Had that fire come
back `violated`, `_raise_recurrence_suspect` would have emitted a
`fire-violated` suspect at the same `(record, origin)` key — it did not,
because the model said the opposite.

So the machine contradicts itself at one origin, across three planes: the
journal says *already covered*, the fire says *complied*, and the suspect
stream says *may not be holding*. Two of three read the transcript
correctly; the one that reached the human is the wrong one. That is §2.4's
inversion caught in the act on live data, and it is why the row cannot be
resolved by any of the four existing not-holding verbs.

**None of this resolves the instance.** The three planes are the evidence an
operator would weigh; the ruling is theirs, at the CLI, after this unit
ships. `b68b5811` stays open.

**The command this unit adds** (to be run by the operator, after the build,
not during it):

```
self-learn dismiss-suspect lrn-566216a6 \
  --event b68b5811 \
  --why rule-followed \
  --note "transcript L361 shows the model stopping a benchmark because a game was at 303% CPU — that is compliance with this rule, not a violation; the miner matched the lesson's text, which its own journal folded to already-canon"
```

**Resulting frontmatter delta on `~/.self-learn/user/resolved/lrn-566216a6.md`:**

```yaml
dismissed_suspects:
  - ref: b68b5811
    ts: '2026-08-19T10:39:13Z'
    why: rule-followed
    origin: 'transcript:8c746bbd-917f-4218-ad9a-5fa67bef95ed#L361'
    basis: miner-match
    dismissed_at: '<the day it is run>'
    note: 'transcript L361 shows the model stopping a benchmark …'
```

Commit `self-learn: suspect dismissed on lrn-566216a6`. Afterwards
`report --json`'s `recurrence_suspects` is `[]` for the first time since
2026-08-19, `routed_live` for that record reads `recurrences: 0,
dismissed_suspects: 1`, `suspects_dismissed` carries the joinable row, and
the telemetry event is untouched.

**The operator may also want `confirm-held lrn-566216a6`** — the transcript
is positive evidence the rule works. That is a second, separate verb call by
design (§3 reason 3), and this spec does not fold it in (§13 Q5).

---

## 13. Questions routed upward, and rulings received

`Q…` rows are still open and bind nothing until answered. `N…` rows are
**settled** — a ruling already made, restated here so a builder reading only
this section cannot mistake it for an open question. **N1 is normative: the
builder must act on it.**

**N2 (RULED 2026-08-24) — the `--why` enum values (§5).** Ruled set:
`rule-followed` / `unrelated` / `duplicate` / `misattributed` / `other`
(user ruling 2026-08-24; renamed from `complied` / `different-lesson` /
`duplicate-capture` / `wrong-record` / `other`). This binds the record
schema and is the analyst's x-axis. The open question — whether
`duplicate` is distinct enough from `rule-followed` to earn a slot, given
§2.4 says the `miner-match` producer emits *exactly* duplicate claims by
construction — is resolved by the ruling itself: the five-value set
stands as-is, with only the labels changed for clarity. Worked example:
`self-learn dismiss-suspect lrn-566216a6 --event <nonce> --why duplicate
--note '…'` records a `dismissed_suspects[]` entry with `why: duplicate`
— distinct from `--why rule-followed`, which marks the sighting as the
rule being followed, not a re-derivation of it. r1 routed this upward as
Q1; the ruling supersedes that.

**Q2 — the cross-record hole in `confirm_recurrence` (§6.3 step 3).**
Verified by reading `verbs.py:4265-4279`: the event is located by `kind` +
`nonce` alone and its `ts`/`origin` are then copied onto whatever record id
was typed, with no check that `event["record"]` matches. `dismiss-suspect`
closes this on itself; whether `confirm_recurrence` should be retrofitted is
a separate call (this spec says out of scope, §9 item 6, to keep the diff off
a shipped verb).

**Q3 — the FW row for the polarity inversion (§2.4, §9 item 2).** Should
this spec's finding be filed as an FW row now, or held until dismissal data
exists to size it? The spec's position is *file it now, fix it later* — the
finding is complete and the fix is not.

**Q4 — repeat false positives.** Dismissal is per-nonce. If the same routed
rule keeps drawing `miner-match` suspects from new transcript lines, the
operator dismisses repeatedly. Is a `(record, basis)` mute wanted, or is
repeated dismissal the *desired* signal (each one a data point for Q3)? The
spec assumes the latter and fences the mute out (§9 item 10).

**Q5 — a `--held` convenience flag.** Should `dismiss-suspect … --held` also
stamp `last_confirmed`, given the live case wants both? The spec says no
(§3 reason 3, §12) — two claims, two commits — but this is a UX call, not a
correctness one.

**N1 (RULED, not a question) — A3's unmutable shipped guard gets a courtesy
test, in this unit's commit.** `verbs.confirm_recurrence`'s
`status != "routed"` refusal kills zero tests today — measured across the
whole CLI suite, clean-env both sides (§10 A3). The orchestrator has ruled
that closing it is **in scope for this builder**, so it is no longer an open
question: write **T-SHIPPED-NOT-ROUTED-GUARD** (§11) into
`test_m2_verbs.py` beside the other `confirm_recurrence` tests, and expect
**M21** (§10) to go red once it lands. §9 item 6 still forbids touching that
verb's *code*; this is a test over unchanged behaviour, which is a different
thing. r1 routed this upward as Q6; the ruling supersedes that.

---

## 14. Docs to update in the same commit

| File | Change |
|---|---|
| `docs/specs/self-learn/11-telemetry-and-lifecycle.md` | §2.2 resolutions list gains **dismiss**, with one sentence on reading `basis`; §2.5 verb table gains the pinned row (`dismissed_suspects[]` append / `self-learn: suspect dismissed on lrn-<id>`); §3's frontmatter block gains `dismissed_suspects:`. The "a match is a recurrence" assertion is **not** rewritten (§9 item 3). |
| `docs/specs/self-learn/02-schema.md` | the `recurrences`/`last_confirmed` note near `:258` gains `dismissed_suspects`, with the §4.3 ref-is-load-bearing asymmetry stated in one line. |
| `plugins/self-learn/commands/review.md` | the not-holding card's four resolutions (`:210-221`) become five: **Dismiss** → `self-learn dismiss-suspect <id> --event <nonce> --why <reason> [--note …]`, plus one sentence: `fire-violated` is the model's own report, while `miner-match` and `title-token-overlap` — the other two LIVE bases (§2.2) — are text-similarity heuristics. Do **not** write `origin-match` into this sentence; it is retired. Exit-code list unchanged (`:227-254` already covers 1/3/4/5/6/7/64 — the bullets run from `- **1**` at `:227` to `- **64**` at `:254`). |
| `plugins/self-learn/skills/self-learn/SKILL.md` | one verb-table row after `confirm-recurrence` (`:41`). |

---

## 15. Revision history

- **r1, 2026-08-24** — first draft. All code claims probed at `24f3f90`;
  three mutations measured and reverted (§10 A1–A3); live ledger read from a
  scratch copy; `lrn-566216a6` / `b68b5811` left open, as ordered.
- **r2, 2026-08-24** — blind-gate fold (NOT SOUND: 2 MAJOR, 3 MINOR, 4 NIT,
  no BLOCKER; spine verified). **MAJOR-1:** r1's "master is red" claim was
  **false** and is retracted — the 8 failures were host-environment
  contamination (`SELF_LEARN_ANALYST_MODEL` / `SELF_LEARN_ANALYST_TIMEOUT`
  exported by the interactive shell, leaking into
  `provider.model_for("analyst", …)`). Q7 deleted; §11.0 runbook added; A3
  re-measured clean-env on both sides (`2369 passed, 8 skipped`, rc=0 each —
  the mutation kills nothing, now with no caveat). **MAJOR-2:** §7c corrected
  — `gather` does not call `_walk_records`; the attachment site is its own
  inline walk at `report.py:1715`, before the status branching, with the
  superseded-loss hazard stated. **MINOR-1/2:** `_commit_ledger` cite fixed to
  `verbs.py:511-534`; A2's measured scope named. **MINOR-3:** M18–M20 added
  (T-ENTRY-SHAPE had no killer) and §10.1 census added — 21 covered, 3
  deliberately unmutated with reasons; partition verified programmatically.
  **NIT-1:** `origin-match` marked retired (FW-49) everywhere; the contingency
  table is 3 × 5; §9 gains item 13. **NIT-2:** five citations corrected.
  **NIT-3:** §12 gains the third corroborating plane — the `fire` event
  `777d6030` at the identical origin, `outcome: "complied"`. **NIT-4:** the
  `SCHEMA_VERSION`-bump cost softened per `telemetry.py:63-68`.
  `lrn-566216a6` / `b68b5811` still open; `~/.self-learn` never mutated.
- **r3, 2026-08-24** — second gate fold (r2 verdict: all nine r1 folds closed;
  the gate retracted its own `:4241` cite, `:4242` stands). **MAJOR-3:** the
  spec contradicted a standing orchestrator ruling — a courtesy test over the
  SHIPPED `confirm_recurrence` `status != "routed"` guard **is** in scope for
  the builder, but r2 still routed it upward as an open Q6 and cited §9 item 6
  as fencing it out, so a builder reading r2 would not have written it. Fixed
  four ways: **T-SHIPPED-NOT-ROUTED-GUARD** added to §11 (landing in
  `test_m2_verbs.py`, not the new file); **M21** added to §10, carrying A3's
  measured 0-red-today with the new test named as the killer a post-build gate
  must see go red; **§9 item 6** reworded to fence shipped *code* and to state
  explicitly that tests over shipped behaviour are in scope and required;
  **§13 Q6 converted to N1**, a recorded ruling rather than a question, with
  §13 retitled and §0 updated so the Q/N distinction is unmissable. §10.1's
  census rebuilt for 25 tests (22 covered / 3 unmutated, partition re-verified
  programmatically) and unmutated-entry #1's §9-item-6 lean narrowed to the
  code-only sense. **NIT-A:** `if record.routing is not None` is
  `report.py:1732` (`:1733` is its body). **NIT-B:** review.md's exit-code
  bullets span `:227-254` (r2's `:242-256` started mid-list and omitted
  1/3/4/5). Spec-only edits; `lrn-566216a6` / `b68b5811` still open;
  `~/.self-learn` never mutated.
