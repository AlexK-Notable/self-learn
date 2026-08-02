# Spec — a `violated` fire must also raise a recurrence suspect

Unit **U-recur** of the r2 routing campaign
(`forward/r2-routing-campaign.md` §2, §7 row *"The promotion rule has
nothing under it"*). Wave 1, file set `miner.py` only.

Status: **DRAFT r1**, authored 2026-08-02.

**Normative register.** §3 (acceptance criteria) and §3.1 (mutation plan)
*are* the spec. Everything else is rationale. **Where prose and the
criteria conflict, the criteria win.** Every set named below is defined
exactly once, here, and referenced by name afterwards:

- **THE CROSSOVER** — on a `fires[]` entry with `outcome == "violated"`
  against a currently-`routed` record, also spool a `recurrence-suspect`.
- **THE SUSPECT KEY** — `("recurrence-suspect", <record id>, <origin>)`,
  where `<origin>` is the full `transcript:<session>#L<line>` string,
  byte-identical to the `origin` on the `fire` event it crosses over
  from. This is the tuple shape `_event_seen` already builds
  (`miner.py:934-943`); it is not extended, narrowed, or replaced.
- **THE BACKFILL** — a pass over `fire` events already in the tracked
  telemetry plane with `outcome == "violated"`, raising THE SUSPECT for
  any whose THE SUSPECT KEY is not already present.

---

## 1. The defect

`recurrence-suspect` is the only signal that says *a routed rule is not
holding*. It is the input to `confirm-recurrence`
(`verbs.py:3148-3228`), the sole caller of `Record.append_recurrence`,
and it is surfaced by `report.recurrence_suspects`
(`report.py:193-229`) and `report.html:49`. **Zero have ever been
emitted.**

Measured against the live ledger, **2026-08-02** (§6 has the raw rows):

| kind | count |
|---|---|
| `capture` | 54 |
| `surface-budget` | 29 |
| `fire` | 22 |
| `offer-declined` | 1 |
| **`recurrence-suspect`** | **0** |

The write path was never missing. The cause is a **channel split** in
the miner prompt (`_PROMPT_TEMPLATE`, `miner.py:634-692`), which offers
two ways to report the same phenomenon:

- a `candidates[]` entry carrying `match: {record, status: "routed"}`,
  which reaches `miner.py:1175-1190` and spools a `recurrence-suspect`
  with `basis="miner-match"`;
- the separate `fires[]` array with `outcome: complied | violated`,
  which reaches `miner.py:1294-1319` and spools a `fire`.

The model uses `fires`. That channel is purpose-built for routed rules
(*"=== ROUTED RULES (observe fires against these) ==="*, `:687`),
whereas the match route requires emitting a candidate the reader knows
is a duplicate — which the rubric's *"when in doubt, do not emit"*
(`:640`) actively discourages. Five weeks of data agree: 22 fires, 0
suspects.

The fire handler already validates the ref (`:1301`), already confirms
`status == "routed"` (`:1309`), already has the origin (`:1311`), and
already dedupes on `("fire", rid, origin)` (`:1312`). **It simply never
crosses over.** The safety net was never missing; it was wired to the
wrong terminal.

**Why this matters more than a missing counter.** Both records with
`violated` fires — `lrn-ea833a5b` and `lrn-5d0c592a` — are
`scope: user`, `destination: claude-md`. That is the most prominent
tier the system has, and they were violated there anyway. So the top
rung of the escalation ladder cannot be *"promote it to always-loaded"*:
it is already there. Text that has failed at maximum prominence is not
fixed by more prominence. Nothing in this unit builds an escalation —
but a ladder whose bottom rung never fires cannot be reasoned about at
all, which is why raising the suspect comes first.

---

## 2. The change

`_reconcile_and_land` (`miner.py:1104`) gains THE CROSSOVER and THE
BACKFILL. Nothing else in the file changes.

### 2.1 THE SUSPECT KEY — the part a naive fix gets wrong

A suspect raised from a fire must not double-raise on re-processing,
and must not *suppress* a legitimately distinct later sighting. Those
two requirements pull in opposite directions and the key is where they
are reconciled.

**The identity of a suspect-from-fire is the sighting, and a sighting is
`(record, transcript position)`.** Hence THE SUSPECT KEY. Component by
component:

- **The kind must stay in the key.** `("fire", rid, origin)` and
  `("recurrence-suspect", rid, origin)` are distinct entries of the same
  `_event_seen` set. Reusing the `key` variable already in scope at
  `:1312` produces **zero suspects forever**: it is added to
  `seen_events` at `:1318` in the same iteration, so any later
  `if key not in seen_events` is dead, and on the next run the
  early-`continue` at `:1313-1314` returns before any suspect logic is
  reached.
- **The origin must be the whole `transcript:<session>#L<line>`
  string.** Two violations are two sightings. Live proof, not a
  hypothetical: `lrn-5d0c592a` carries two `violated` fires from the
  **same session** `e18d1662-…`, spooled in the **same mine run**
  (`ts 2026-07-28T10:43:00Z`), differing only by line — `#L9826` and
  `#L10073`. A key that drops the line, truncates to the session, or
  buckets by day or by run swallows the second one. So does the
  reflexive "one suspect per record per run" guard a builder adds to
  avoid perceived spam; that guard is AC3's mutation for exactly this
  reason.
- **The nonce and the `ts` must stay out.** The nonce is fresh per
  event (`telemetry.py:164`), so including it makes the key never match
  and re-raises the same sighting on every run, unbounded.

**One set, shared across both channels.** THE CROSSOVER reads and writes
the same `seen_events` object the candidate loop uses. A candidate-match
suspect at origin O (`:1176-1184`) and a `violated` fire at the same
origin O on the same record are **one sighting**, and must produce
**one** suspect — double-listing overstates recurrence pressure, which
is the exact thing `confirm_recurrence` refuses at
`verbs.py:3193-3198`. The candidate loop runs first and wins;
`basis` stays `miner-match` in that case.

### 2.2 Retroactive, not forward-only — and why that is forced, not preferred

**Ruling: THE BACKFILL ships with this unit. Permanent, unbounded, and
idempotent — not a one-shot migration and not time-windowed.**

This is not a taste call. THE CROSSOVER **structurally cannot** reach
the four `violated` fires already in the ledger: `_event_seen` sees
their `("fire", rid, origin)` keys, so `:1313-1314` `continue`s out of
the loop body before any crossover code runs. A forward-only fix ships,
passes its suite, and leaves `recurrence-suspect` at **zero** on the
real ledger until the next violation happens to occur — an unfalsifiable
"it works" on live data, which is the campaign's signature failure mode
(§9, *"declaring completion on a green suite"*).

Three further reasons it is the right shape:

1. **It is nearly free.** `_event_seen` already walks
   `telemetry.read_events(home)` once per run. THE BACKFILL reuses that
   same pass (§4, decision 4) — no second read, no new I/O.
2. **It self-heals.** `telemetry.spool_quiet` swallows failures by
   design (`telemetry.py:189-197`). Without THE BACKFILL, a swallowed
   spool failure loses that suspect permanently, because the live path
   can never revisit it (same early-`continue`). With it, the next run
   repairs it.
3. **It cannot nag.** A suspect is raised exactly once per THE SUSPECT
   KEY, forever. Once the human confirms it, its nonce lands in
   `recurrences[].ref` and `report.recurrence_suspects` stops listing it
   (`report.py:226-227`). An ignored suspect stays listed — identical to
   every other suspect's behaviour.

**A one-shot migration is rejected**: it needs new persistent state to
record "already migrated", which this ledger has nowhere to put, and it
forfeits (2). **A time window is rejected**: it would silently drop
exactly the historical evidence the fix exists to recover.

**Expected effect on the live ledger, stated so it is not a surprise:**
the first productive `mine` run after this lands raises **four**
suspects — two on `lrn-ea833a5b`, two on `lrn-5d0c592a` — and they
appear as four rows in `report --json .recurrence_suspects`. That is the
unit's live positive control.

**Reachability, stated honestly:** THE BACKFILL lives in
`_reconcile_and_land`, which runs only when the reader produced
parseable output (`miner.py:1736-1760`). An `idle`, `held-gate`, or
`failed` run does not reconcile and therefore does not backfill. It runs
on the next productive run instead; nothing is lost.

### 2.3 What must not change

- **The candidate-match path, `miner.py:1175-1190`**, including its
  `basis="miner-match"` literal and its `_outcome(..., "recurrence", …)`
  name. AC5 pins that it wins on a shared origin.
- **The `fire` event itself.** Every fire that is emitted today is still
  emitted, with the same payload. THE CROSSOVER is additive.
- **`complied` fires.** They are the rule *working*. AC2 is the
  discriminator; without it a fix that raises a suspect for every fire
  passes AC1 just as well.
- **The live path's `routed` guard** (`:1308-1310`) — unchanged, and THE
  BACKFILL mirrors it (AC7).
- **`telemetry.py`.** No new event kind, so no `SCHEMA_VERSION` bump
  (`telemetry.py:64`; 11 §4.3's bump rule governs the closed *kind* set,
  and `recurrence-suspect` is already in it at `:75`). `spool_event`
  accepts any scalar payload field (`:166-174`) — there is no field
  allowlist to extend. **`telemetry.py` belongs to U-reach this wave and
  must not be touched.**

### 2.4 What must change that the diagnosis did not name

**`test_miner.py:1027-1052` asserts the current count as the contract.**
`test_fire_and_recurrence_replays_deduped` feeds a payload carrying a
candidate-match at `#L7` *and* a `violated` fire at `#L9` on one routed
record — two distinct origins — and ends with

```python
assert len([e for e in events if e.get("kind") == "recurrence-suspect"]) == 1
```

Under this unit that becomes **2**. The replay half of that test
(`result.recurrences == []`, exactly one `fire`) is unchanged and stays
— it is the pre-existing proof that cross-run dedupe works. Update it;
do not work around it. (Verified green on master 2026-08-02 before this
spec was written.)

**The journal outcome name is load-bearing and must be new.**
`_NEARMISS_DISPOSITION` maps `"recurrence"` → `already-canon`
(`miner.py:959`), `_enrich_near_miss` stamps a `disposition` +
human-facing `reason` on any mapped name (`:1082-1092`),
`near_miss_count` counts every row that gained one (`:1799`), and the UI
renders those rows as near-miss cards
(`ui/src/self_learn_ui/models.py:739-763`). A fire-derived suspect is
**not** a near-miss: nothing was dropped and there was no candidate.
Emitting `_outcome(..., "recurrence", …)` from THE CROSSOVER would
render it in the miner-visibility surface as *"this is already reflected
in an existing lesson"* and inflate the count. Use
**`"recurrence-from-fire"`**, which is outside `_NEARMISS_DISPOSITION`
and therefore passes through `_enrich_near_miss` unchanged (`:1088-1089`)
and is skipped by `_build_near_miss_rows` (`models.py:749-750`).

**`result.recurrences` gates the flush.** `miner.py:1822` flushes the
spool only `if result.landed or result.folded or result.recurrences or
result.fires`, and `telemetry.read_events` reads the **tracked plane
only** (`telemetry.py:364-390`) — an unflushed suspect is invisible to
`report`, to the UI, and to the next run's `_event_seen`. A
backfill-only run has no landings, no folds and **no fires**, so
`result.recurrences.append(rid)` is the only thing that opens that gate.
AC6 is written to make its absence fail.

---

## 3. Acceptance

Tests live in `plugins/self-learn/cli/tests/test_miner.py`, using the
existing `home` / `transcripts` fixtures and the `shim_reader`,
`candidate`, `make_behavior`, `_resolve` helpers already in that module.
Suite command (campaign §4a):
`cd plugins/self-learn/cli && .venv/bin/python -m pytest -q`.

**AC1 — THE CROSSOVER fires.** One `routed` record; reader payload with
`candidates: []` and `fires: [{record: rid, session: S, line: L,
outcome: "violated"}]`. After `miner.run(home)`,
`telemetry.read_events(home)` contains **exactly one**
`recurrence-suspect`, with `record == rid`, `basis == "fire-violated"`,
and `origin == "transcript:S#L<L>"` — asserted **both** against that
literal **and** against the `origin` of the `fire` event read back from
the same event list. The `fire` event is still present, unchanged.
*(Absent the feature this prints zero suspects and fails; it is not
vacuous.)*

**AC2 — the discriminator.** Identical to AC1 with
`outcome: "complied"`. **Zero** `recurrence-suspect` events; exactly one
`fire`.

**AC3 — two distinct sightings in one run are two suspects.** One
`routed` record; reader payload with `candidates: []` and two `fires[]`
entries, **same record, same session, different lines**, both
`violated` (the `lrn-5d0c592a` shape). After one `miner.run(home)`:
exactly **two** `recurrence-suspect` events, whose `origin` values are
the two distinct `transcript:S#L…` strings. Assert the origin *set*,
not just the count.

**AC4 — idempotence across runs.** Run AC1's payload; `telemetry.flush`;
re-run the identical payload with `since="2020-01-01"` (the replay shape
of `test_fire_and_recurrence_replays_deduped`). Still **exactly one**
`recurrence-suspect` and one `fire`; the second run's
`result.recurrences == []`. Then run a **third** time — **writing a new
transcript first** (see the productive-run trap below) — with a payload
carrying no candidates and no fires: still exactly one
`recurrence-suspect` (THE BACKFILL does not re-raise what it already
raised).

**AC5 — cross-channel, one origin, one suspect.** Reader payload
carrying **both** a `candidates[]` entry with
`match: {record: rid, status: "routed"}` at `(S, L)` **and** a
`violated` `fires[]` entry for the same record at the same `(S, L)`.
After the run: exactly **one** `recurrence-suspect`, with
`basis == "miner-match"` (the candidate loop runs first and wins).

**AC6 — THE BACKFILL, and the flush gate.** Pre-seed the **tracked**
plane: `telemetry.spool_quiet("fire", record=rid, origin=
"transcript:sess-old#L5", outcome="violated")` then
`telemetry.flush(home)`, with `rid` `routed` and no suspect anywhere.
Run the miner with a payload carrying **no candidates and no fires**,
over a **newly written transcript** (see the productive-run trap below).
Then, **without any explicit flush in the test**,
`telemetry.read_events(home)` contains exactly one `recurrence-suspect`
with `record == rid`, `origin == "transcript:sess-old#L5"`,
`basis == "fire-violated"`; and `result.recurrences == [rid]`.
*(The no-explicit-flush clause is the control: with `landed`, `folded`
and `fires` all empty, only `result.recurrences` opens `miner.py:1822`.
Omit the append and the tracked plane stays empty — the precise shape of
"the fix ran and nothing is visible".)*

**AC7 — THE BACKFILL respects live routed coverage.** AC6's pre-seed,
but `rid` is `superseded`. After the run: **zero**
`recurrence-suspect` events. *(`confirm_recurrence` refuses a
non-`routed` target at `verbs.py:3188-3192` and
`report.recurrence_suspects` filters it out at `report.py:223-225`, so
such an event is permanent litter in an append-only plane.)*

**AC8 — the journal row is not a near-miss.** For AC1's run,
`miner.read_journal()[-1]` contains an `outcomes` row with
`outcome == "recurrence-from-fire"`, `record == rid` and the fire's
`origin`; that row has **no** `disposition` key; and that run's
`near_miss_count == 0`.

**AC9 — the superseded existing test.** `test_miner.py:1052`'s
`== 1` becomes `== 2` (§2.4). Its other assertions are unchanged.

### 3.1 Mutation plan

Each row is a one-line edit to production code (`miner.py`) that must
make the named test fail. Collateral failures are disclosed rather than
hidden — a reviewer surprised by a second red test cannot tell a spec
error from a build error.

| # | Mutation | Named test | Also fails |
|---|---|---|---|
| M1 | delete THE CROSSOVER call from the `fires` loop | AC1 | AC3, AC8 |
| M2 | change the `basis` literal `"fire-violated"` → `"miner-match"` | AC1 | AC6 |
| M3 | broaden THE CROSSOVER's condition to `if outcome in ("complied", "violated")` | AC2 | — |
| M4 | insert `if rid in result.recurrences: return` at the head of the crossover helper (**the naive "one per record per run" fix**) | AC3 | — |
| M5 | delete the `if key in seen_events: return` guard from the crossover helper | AC4 | AC5 |
| M6 | delete `seen_events.add(key)` at `miner.py:1184` (the candidate loop's suspect path) | AC5 | — |
| M7 | delete THE BACKFILL call from the end of `_reconcile_and_land` | AC6 | — |
| M8 | delete `result.recurrences.append(rid)` from the crossover helper | AC6 | — |
| M9 | drop the `status == "routed"` check from THE BACKFILL | AC7 | — |
| M10 | change the crossover's journal outcome name to `"recurrence"` | AC8 | — |

**M1 is the whole-unit control**; M4 and M8 are the two shapes this fix
is most likely to ship broken in, and each is caught by exactly one
test.

**Fail-open audit — what each assertion prints when its target is
absent.** AC1/AC3/AC6 assert a **positive count and specific field
values** on events that do not exist without the change: absent the
feature they read `0 != 1`. AC2 and AC7 are the two absence assertions
in the set, and neither stands alone: AC2's scenario is AC1's with one
field changed (so AC1 proves the harness can see a suspect at all), and
AC7's is AC6's with one status changed (so AC6 proves the same for THE
BACKFILL). Each absence assertion therefore has a paired presence
assertion over the identical fixture — the positive control campaign §5
demands.

**The productive-run trap — every backfill test must clear it.**
`miner.run` returns `idle` at `miner.py:1704-1711`, **before the reader
is invoked**, when no new transcript digests exist. A backfill test that
does not `write_transcript(...)` a fresh session never reaches
`_reconcile_and_land` at all — so THE BACKFILL never runs, the
assertions read whatever the pre-seed left behind, and **the test passes
on a build with no backfill in it**. AC6 and AC4's third phase each
write a new transcript for exactly this reason. A reviewer should
confirm M7 (delete THE BACKFILL call) actually turns AC6 red; if it does
not, the fixture fell into this trap.

**Run-evidence control.** Report the collected/passed counts for
`tests/test_miner.py`, not just "green". A miscollected module is not a
red test.

---

## 4. Builder decisions, made here rather than left open

1. **`basis = "fire-violated"`** — a literal, distinct from
   `miner-match` (candidate path, `:1183`) and from the worker's
   `origin-match` / `title-token-overlap` (`worker.py:1001-1006`). 11
   §4.3 glosses the field as a *"similarity basis label"*; `miner-match`
   already sets the precedent that it labels the **source of suspicion**
   rather than a similarity metric, so no canon edit is needed.
2. **The suspect payload is exactly `{record, origin, basis}`** — no
   `outcome` field. That matches 11 §4.3's documented
   `recurrence-suspect` payload, and the violation fact is recoverable
   by joining on `(record, origin)` to the `fire` event, which is always
   present alongside it.
3. **The journal outcome name is `"recurrence-from-fire"`** (§2.4), with
   `record=` and the origin, so a later reader can answer "did the fix
   fire?" from the journal without diffing telemetry.
4. **`_event_seen` (`miner.py:934-943`) returns
   `(seen, violated_fires)`** — one `read_events` pass, one call site
   (`:1116`). `violated_fires` is the list of `(record, origin)` pairs
   from `fire` events with `outcome == "violated"`, in `read_events`
   order (ts-ordered), so THE BACKFILL's output order is deterministic.
   Telemetry lines are untrusted input (11 §4.2): skip any row whose
   `record` or `origin` is not a string, and re-validate `record`
   against `RECORD_ID_RE` — never a crash, never a guessed id.
5. **One emission point.** A single helper spools the suspect,
   checks/updates THE SUSPECT KEY against `seen_events`, appends to
   `result.recurrences`, and writes the journal row. THE CROSSOVER and
   THE BACKFILL both call it. Two copies of this logic is how the two
   dedupe rules drift apart.
6. **Ordering inside `_reconcile_and_land`:** candidates loop →
   `_handle_near_misses` (both unchanged) → `fires` loop with THE
   CROSSOVER → THE BACKFILL last, sharing the same `seen_events`. A live
   crossover in this run therefore pre-empts THE BACKFILL for the same
   key.
7. **The prompt is not changed.** The alternative fix — instruct the
   reader to *also* emit a `match`-carrying candidate whenever it
   reports a violated fire — is rejected on measurement: 22 fires and 0
   suspects is five weeks of demonstrated non-compliance with the
   affordance that already exists, and the rubric's *"when in doubt, do
   not emit"* pushes against emitting a known duplicate. A deterministic
   code crossover cannot be talked out of firing. (Prompt work on this
   surface belongs to `U-composer`.)
8. **Tests go in `plugins/self-learn/cli/tests/test_miner.py`**, which
   no concurrent unit touches.

## 5. Out of scope

- **`worker._recurrence_suspects` (`worker.py:969-1016`)** — the
  *second* silent suspect producer (see §6, finding 4). `worker.py` is
  `U-marker`'s file this wave. Report, do not fix.
- **Anything that acts on a confirmed recurrence** — the
  revise/escalate/tolerate/retire flow is FW-8. This unit raises the
  suspect; the human still confirms it with `confirm-recurrence`, per
  11 §2.2's machine-never-writes-the-record rule.
- **Surfacing.** `report.recurrence_suspects`, `report --json`, and
  `report.html:49` already render suspects and need no change.
- **The escalation-ladder doctrine** ("at the ALWAYS tier the escalation
  is a guard, not more prose") — playbook §6 item 6, `U-composer`.
- **`telemetry.py`, `verbs.py`, `worker.py`, `analyst.py`,
  `ledger_ops.py`, `selfcheck.py`** — all held by concurrent units. If
  this fix appears to need any of them, stop and say so rather than
  widening.

## 6. Evidence — the measurement behind §1, taken 2026-08-02

Read-only pass over `~/.self-learn/telemetry/*.jsonl`. The playbook's
§7 figures were taken 2026-07-28; five days later the picture has moved
in a way that strengthens the diagnosis rather than softening it.

| | §7 (2026-07-28) | measured 2026-08-02 |
|---|---|---|
| `capture` | 30 | 54 |
| `surface-budget` | 26 | 29 |
| `fire` | 8 | **22** |
| `offer-declined` | 1 | 1 |
| `recurrence-suspect` | **0** | **0** |

The fire channel nearly tripled while the suspect channel stayed at
zero. That *is* the channel split, measured rather than argued.

The four `violated` fires (all others are `complied`):

| ts | record | origin |
|---|---|---|
| 2026-07-26T10:43:14Z | `lrn-ea833a5b` | `transcript:e18d1662-…#L4088` |
| 2026-07-27T10:38:27Z | `lrn-ea833a5b` | `transcript:e18d1662-…#L6394` |
| 2026-07-28T10:43:00Z | `lrn-5d0c592a` | `transcript:e18d1662-…#L9826` |
| 2026-07-28T10:43:00Z | `lrn-5d0c592a` | `transcript:e18d1662-…#L10073` |

Both records are `scope: user`, `status: routed`,
`destination: claude-md`.

## 7. Revision history

- **r1** — this document.
