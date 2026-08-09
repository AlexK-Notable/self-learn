# Spec — U-cursorhold: the per-run landing cap must hold the cursor it outran

Status: **r1 — written blind, not yet gated.**
Unit `U-cursorhold`, addressing **FW-73**
(`docs/specs/self-learn/14-forward-work-map.md:128`).

**Base commit:** `c8dcaf3` (master). Every `file:line` below was read
against that tree and cite-checked while writing. Two sibling units are
in flight on their own branches (`21a4dc0` U-pointer, `6e32dd7`
U-forcefail); both are **spec-only commits** and neither touches
`miner.py`, so the citations hold.

**Files this unit may touch:**

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/miner.py` | Rule-H (the hold): one new `MineResult` field, one new parameter on `_reconcile_and_land`, the classification at the cap-drop site, the filter at the `_advance_cursors` call site, one new journal key. |
| `plugins/self-learn/cli/tests/test_miner.py` | This unit's tests, beside the shipped cap tests. |
| `plugins/self-learn/ui/tests/test_models_front.py` | ONE added test — B3 leg (ii), the UI drill row's invariance. |
| `docs/specs/self-learn/12-transcript-miner.md` | Canon amendment: the cap now holds cursors (§2 Phase 0 / Phase 4), and the journal contract gains `cursors_held`. |
| `docs/specs/self-learn/14-forward-work-map.md` | FW-73 disposition, in the build commit. |

**Not in this list, deliberately and normatively.** No UI *source* file
changes — `models.py`, `routes.py`, and the templates are **out of scope
and must be reported, not edited** (§3.5 proves why none is needed). No
change to `_advance_cursors`'s signature or body (§6-BD2). No change to
`walk`, `digest_transcript`, `cap_for`, the flood gate, the cap
constants, or the near-miss promote path (§3.6). A builder who finds
themselves editing a *cap value* to make a test pass has left this
unit's mandate and must stop and report.

---

## 0. Reading order and precedence

This document has **two normative definitions** — **Rule-H** (§3.1, the
hold) and **Obs-C** (§3.5, the observable surface) — plus one normative
behaviour definition, **the acceptance criteria (§4)**.

**Precedence, on conflict:**

1. The acceptance criteria (§4) and the mutation plan (§5) win over
   everything else. They are the contract; the rest is rationale.
2. Rule-H and Obs-C win over all prose and over any example here.
3. Where this spec and `12-transcript-miner.md` disagree, **this spec
   wins and §3.6 says exactly which sentence of doc 12 is amended** —
   doc 12 §7-8 item 8 already states the intended posture for the flood
   gate ("cursors hold so nothing is lost"); this unit extends that
   posture to the cap and says so in canon rather than leaving two
   drop sites with opposite designs.

---

## 1. The defect

### 1.1 The mechanism

`processed` — the list `_advance_cursors` consumes — is built at
`miner.py:1815-1834`, entirely from *which session slices fit the digest
budget*:

- a slice with no minable content is appended and its cursor advances
  (`:1822-1825`);
- a slice that would blow `MAX_PROMPT_DIGESTS_CHARS` is **not** appended
  — "stays behind the cursor for next run" (`:1826-1828`);
- a slice whose digest is sent to the reader is appended (`:1829-1834`).

That loop finishes before `cap = cap_for(len(digests))` is computed at
`:1895`. The cap therefore cannot influence `processed`, and nothing
downstream reopens it.

The per-candidate cap check lives at `:1328-1343`, inside
`_reconcile_and_land` (`:1212`). At cap it increments `result.dropped`,
builds the near-miss snippet, journals `dropped-cap`, and `continue`s.
It touches no cursor state, and it has no way to: `_reconcile_and_land`
is not given the slices.

`_advance_cursors(processed)` then runs **unconditionally** on the
success path (`:1934`) — including after a swallowed `GitOpsError`
(`:1909-1918`). So the capped candidate's originating session is marked
read to its end, and `walk` (`:305-353`) will never offer those lines
again: the next run skips the file outright when its size is unchanged
(`:334-335`) and otherwise starts at the recorded line count (`:336`).

**The contrast is in the code's own comments.** The flood gate
(`:1849-1860`) says *"don't advance cursors — nothing is missed"* and
`return`s at `:1860`, before `_reconcile_and_land` or `_advance_cursors`
are ever reached — every cursor in the run is held. The over-budget
branch at `:1826-1828` does the same thing one slice at a time. The cap
is the only clip in the pipeline with no stay-behind at all.

### 1.2 The measurement

Source: the run journal named by the FW-73 row —
`~/.cache/self-learn/home-0f24de4d/miner/journal.jsonl`, read-only.
**27 journaled runs**, 2026-07-16 → 2026-08-08. Two of them hit the cap:

| journal line | run | scanned | cap | landed | `dropped-cap` |
|---|---|---|---|---|---|
| 14 | `28117725` (2026-07-26) | 1 | 2 | 2 | **4**, all from the same session |
| 18 | `e22fdb66` (2026-07-30) | 10 | 15 | 15 | 1 |

Run `28117725` is the sharper incident and it is the **multi-candidate
case, measured**: one session (`e18d1662…`) produced six candidates.
Two landed (`#L3799`, `#L3247`); four were cap-dropped (`#L3553`,
`#L3086`, `#L4108`, `#L3788`) at a cap of 2 — `cap_for(1)` is the
floor, `min(2 × 1, 15)`. That is a **67 % loss on the richest single
session in the entire journal**, and the cap that bound it was the
minimum cap the system can compute.

Three of those four carried `promotable: true`; the fourth
(`#L3788`) carried `{overlength: true}`, so `_enrich_near_miss`
(`:1202-1208`) scored it `promotable: false` — **it has no recovery path
at all**, not even the UI's manual promote. Run `e22fdb66`'s single drop
(`#L414`) was promotable.

**None of the five origins ever appears again** in any later run's
outcomes — not as `landed`, not as `skipped-known-origin`, not as
anything. Confirmed by scanning every outcome of all 27 runs for those
two session ids. The loss is silent, permanent, and already realised on
the live ledger.

One more measured fact, which §3.4 turns into the starvation argument:
the run *immediately after* the cap-15 run went `held-gate` at
`pending: 36` and **has stayed `held-gate` for every run since** —
journal lines 19-27, nine consecutive runs.

### 1.3 What is *not* the defect

- **Not the cap values.** `DEFAULT_CAP_PER_SESSION = 2` /
  `DEFAULT_CAP_MAX = 15` (`:81-82`) are the ratified flood control (doc
  12 §8 Q3). A cap that refuses to land is working; a cap that *loses
  what it refused* is the bug. This unit changes no value.
- **Not the near-miss surface.** FW-34 already put a scanned snippet on
  the `dropped-cap` outcome and gave the human a promote button
  (`routes.py:1141`). That is a *manual* recovery that requires a person
  to open the drill row of the run that dropped it before the journal
  rolls; it is not a re-surface guarantee.
- **Not `landed-uncommitted`.** That path also advances cursors over
  records that failed to commit; it is already answered by the
  self-healing reconcile at `:1790-1800`. Out of scope (§7.1).
- **Not the reader's judgment.** Whether the model re-reports a
  candidate on a second look is not something a cursor can guarantee
  (§7.2-R3).

---

## 2. What binds this design from outside it

1. **M-5 exclusion is not negotiable.** A self-learn command tag halts
   the rest of a session forever, and "halt state persists in the cursor
   file across slice splits" is a ratified audit fix (doc 12 §7-8 item
   3; `_advance_cursors:356-368`). Nothing here may weaken it.
2. **Model-authored values never steer the machine.** `_valid_ref`
   (`:965-978`) regex-gates the session id and range-checks the line
   *because* they reach origins and telemetry. A cursor position is a
   strictly bigger lever than an origin string: it decides what gets
   re-read. §3.2 rejects the line-precise hold on exactly this ground.
3. **Origin dedup is THE replay backstop.** `existing_origins`
   (`import_common.py:147-186`) is what already makes the documented
   `--since` replay safe (`miner.py:308`: *"origin dedup makes landing
   replays safe"*). This unit re-uses it; it does not add a second
   dedup.
4. **Obs stability.** Existing log lines, journal keys, stdout lines and
   exit codes stay byte-identical unless this spec amends them as an
   explicit criterion. Obs-C (§3.5) is the complete list of changes.
5. **Proportionality.** This is a small unit. Every neighbouring drop
   site with the same shape is *named* in §7.1 and left alone.

---

## 3. The change

### 3.1 Rule-H — the hold (NORMATIVE)

**H-1 (the holdable set).** In the digest loop (`:1820-1834`), build
`digested: dict[str, bool]` mapping `s.session_id` → that slice's `halt`
flag, populated **only in the branch that appends a digest**
(`:1829-1834`) — never for a slice excluded at `:1822-1825`, never for
one deferred at `:1826-1828`. A session absent from `digested` is a
session whose text this run's reader never saw.

**H-2 (the classification).** `_reconcile_and_land` receives `digested`
(new parameter, beside the existing `cwds`). At the cap-drop site
(`:1328-1343`), after the existing snippet work and before `continue`,
the drop is classified into exactly one of three values, and that value
is journaled on the outcome as `cursor` (Obs-C):

| condition | `cursor` | cursor effect |
|---|---|---|
| `session_id in digested` and its halt flag is `False` | `held` | the slice is withheld from the advance |
| `session_id in digested` and its halt flag is `True` | `advanced-halted` | M-5 wins; cursor advances **with `halt` persisted**, exactly as today |
| `session_id not in digested` | `advanced-unmatched` | nothing to hold; cursor state untouched by this drop |

On `held` — and only then — the session id is added to
`result.held_sessions`.

**H-3 (the effect).** At `:1934` the advance becomes

> advance every entry of `processed` **whose slice's `session_id` is not
> in `result.held_sessions`**.

`processed` itself is **not** mutated or reassigned; the filter is a
freshly built list at that one call site. `_advance_cursors` is called
with the same 2-tuple shape it takes today, and its body is unchanged.

**H-4 (what a hold writes).** A hold writes **nothing** for that
transcript. The cursors file's entry for the held path must be
byte-identical to what it was before the run — absent stays absent, and
a pre-existing entry keeps *both* its `lines` and its `size`. Writing a
"partial advance" (old `lines`, new `size`) is forbidden and is the
sharpest trap in this unit: `walk` skips a file whose size matches the
recorded size (`:334-335`), so a partial advance silently re-loses the
candidate while looking like a hold.

**H-5 (granularity).** The hold is **whole-slice and keyed by session
id**. It is never derived from a candidate's `line`. Where two
transcripts under different project directories share a stem, both are
held — the same aliasing `cwds` already carries (`:1832-1834`), and it
errs toward over-holding, which costs a re-read and loses nothing.

**H-6 (scope).** Only `dropped-cap` triggers a hold. `scan-refused`,
`dropped-invalid`, `dropped-land-failed`, `dropped-rejected`,
`match-claim-invalid` and `rubric-dropped` do not (§7.1 says why).

### 3.2 Where it lives, and the two rejected alternatives

The seam is forced: the *decision* (this candidate exceeded the cap) is
inside `_reconcile_and_land`, and the *state* (which slices exist) is in
`_run_locked`. Passing slice-derived data down is the shipped pattern —
`cwds` (`:1217`, `:1219-1221`) does precisely this for project-scope
bucket resolution. Returning a set up through `MineResult` is likewise
the shipped pattern for everything `_reconcile_and_land` learns.

**Rejected — hold at the candidate's line.** The cursor is a line
offset, so `{"lines": <dropped line> - 1}` is expressible and would
re-read less. It is refused: `line` is **model-authored**, gated only
for type and the range 1…10 000 000 (`:974-977`). A rewind driven by
that number lets attacker-influenceable transcript text re-point the
miner at an arbitrarily large already-read span, every run, forever.
Cursor positions must derive only from values the *code* computed —
`SessionSlice.start_line`, `len(lines)`, `stat_size`. A1/A8 pin this.

**Rejected — hold the halted slice too.** Withholding the `halt` write
would keep the candidate reachable, and the exclusion *would* in fact be
re-derived next run (the command tag still sits ahead of the unmoved
cursor, and `digest_transcript` breaks on it again at `:488-490`). It is
still refused: it makes an M-5 guarantee — the one the 2026-07-15 audit
tightened *because* the previous rule collapsed in practice —
conditional on an unrelated cap decision. Recall loss is cheap;
evidence corruption is not. The halted case is a declared residual
(§7.2-R2), not a silent one: it journals `advanced-halted`.

### 3.3 Re-run behaviour: the idempotency story

A held slice is re-read whole on the next run, so every candidate the
reader reported from it can be reported again — including the ones that
already landed. Nothing double-lands, and each mechanism is already
shipped:

- **Landed candidates.** `existing_origins(home)` is read at the top of
  `_reconcile_and_land` (`:1223`) across every bucket, `pending` *and*
  `resolved` (`import_common.py:165-170`), gathering every
  `evidence.origin`. A repeat is journaled `skipped-known-origin` and
  `continue`d at `:1238-1240`, before any landing work. Note this reads
  the **working tree**, not git — so it dedups correctly even on a run
  whose predecessor ended `landed-uncommitted`.
- **Folded candidates.** A fold appends the origin to the target's
  evidence and rewrites the pending record (`:1261-1281`), so the next
  `existing_origins` sweep contains it. A re-read folds once.
- **The rejected-resurface counter.** `_rejected_counter_bump`
  (`:838-853`) accumulates a **set of origins** (`:849-851`) and returns
  its length. Re-reading the same origin re-adds the same member: the
  count does not move. A held slice cannot inflate a rejected lesson
  toward its `REJECTED_RESURFACE_SIGHTINGS = 3` threshold.
- **Fires and recurrence-suspect events.** Deduped on
  `(kind, record, origin)` against the tracked telemetry plane
  (`_event_seen:990`, key checks `:1284-1297` and `:1420-1422`) —
  the mechanism built for exactly this class of replay.

Every dedupe on the path is origin-keyed and idempotent, which is why
doc 12 already ships a full-file replay (`--since`) as a supported
operation.

### 3.4 The starvation bound

**Claim: the hold cannot introduce a re-scan loop the system does not
already have, and the bound is the one the flood gate already imposes.**

For any `cap ≥ 1`, a hold can only occur in a run that landed exactly
`cap` records — that is what `len(result.landed) >= cap` (`:1328`)
means. So every run that holds is a run that made maximal forward
progress, and each such run pushes `total_pending` up by `cap`. The
flood gate reads `total_pending` at `:1850-1852` and, at
`DEFAULT_PENDING_GATE = 25` (`:83`), returns before the reader is even
invoked — holding **every** cursor in the system.

This is measured, not projected. Run `e22fdb66` landed 15 at cap 15
(journal line 18). The next run — and each of the nine runs after it —
was `held-gate` at `pending: 36`, then `32` (lines 19-27). The live
system spent the entire subsequent week in the state where *all*
cursors are frozen pending human review. A cap hold converges on the
same state one session at a time; the release valve for both is the
same person doing the same review.

The costs while held are bounded and already-priced: a held slice
re-enters `digests`, so it re-consumes its share of
`MAX_PROMPT_DIGESTS_CHARS` and of the reader's context — and the
overflow behaviour for that is the existing `deferred_files`
stay-behind (`:1826-1828`), which loses nothing either.

`cap = 0` is the one unbounded case, and it is operator-created; §7.2-R1
declares it.

### 3.5 Obs-C — the observable surface (NORMATIVE)

**Exactly three additions. Nothing else changes.**

- **O-1.** Every `dropped-cap` outcome gains `cursor`, whose value is
  one of `held` / `advanced-halted` / `advanced-unmatched` (§3.1 H-2).
  Present on every `dropped-cap` outcome; present on no other outcome.
  The value is always a non-empty string, which matters: the human
  renderer drops falsy extras (`cli.py:720-724`), so a boolean `False`
  would have been invisible in exactly the case worth seeing.
- **O-2.** The run journal entry for `ok` / `landed-uncommitted`
  (`:1947-1960`) gains `"cursors_held": <int>` — the number of
  **distinct** held sessions, i.e. `len(result.held_sessions)`, not the
  number of dropped candidates.
- **O-3.** `MineResult` gains `held_sessions: set[str]`.

**Byte-stable, pinned by B3:** the outcome name `dropped-cap`; its
`disposition: cap-refused`, its `reason` string and its `promotable`
flag (`:1061-1091`, `:1182-1209`); `result.dropped`'s meaning and count;
the `mine run` stdout line (`cli.py:650-654`); the miner.log run-status
line (`:1961-1965`); the `mine status` one-liner format
(`cli.py:698-705`); every exit code.

**No UI change is needed, and none is permitted.** `_build_near_miss_rows`
(`models.py:1010-1036`) reads only `disposition`, `promotable`,
`reason`, `snippet`, `record`; the promote endpoint
(`routes.py:1141-1173`) re-reads by index and checks `promotable`.
An added key is inert to both. B3 leg (ii) proves it instead of assuming
it. `cursors_held` is journal-side only: the human one-liner is left
byte-stable deliberately (§6-BD4), because the per-candidate `cursor`
value already renders in that same output through the extras dict.

### 3.6 What does not change (NORMATIVE)

- **The flood gate** (`:1849-1860`): same predicate, same position
  *before* the reader, same whole-run hold. C1.
- **The cap values and `cap_for`** (`:81-82`, `:167-171`): untouched. C2.
- **The near-miss promote path**: snippet construction (`:1336-1341`),
  scan-before-journal ordering (`:1330-1335`), `_snippet_fields`,
  `_nearmiss_snippet`, `_enrich_near_miss`, and the UI route. Untouched.
- **`_advance_cursors`** (`:356-368`): signature and body unchanged,
  including the sticky-halt merge at `:364-365`. Its other call site,
  the idle path at `:1841`, is unchanged (an idle run has no candidates,
  so it can hold nothing).
- **Canary scoring** (`:1926-1930`) keeps the **full** `processed` set:
  a held session was still mined this run, and `_score_canaries` uses
  `mined_session_ids` to decide `missed` (`:1595`). A4.

**Doc 12 amendment (the only canon edit).** §2 Phase 0 and the Phase 4
flood-control paragraph gain one sentence each recording that a
cap-refused candidate holds its originating session's cursor, and that
the M-5 halt takes precedence over the hold; the §8 A1 journal contract
gains the `cursors_held` key and the `cursor` outcome field. No other
doc-12 text changes.

---

## 4. Acceptance criteria

**These criteria are the contract.** Each states what its check reports
when the target is **absent or broken** — a check that cannot fail is
this project's signature defect. Tests live in
`plugins/self-learn/cli/tests/test_miner.py` unless a criterion says
otherwise, and use the shipped fixtures (`home`, `transcripts`,
`write_transcript`, `shim_reader`, `candidate`, `u`) — no new harness.
**No test may invoke a real `claude`**: the seam is
`miner._invoke_reader`, shimmed by `shim_reader`
(`test_miner.py:311-319`).

### A. The hold

**A1 — a cap-dropped candidate holds its session's cursor, positive
control first.** One session, `SELF_LEARN_MINE_CAP_PER_SESSION=1`, a
reader payload of two distinct candidates from it.

- **(i) control, run first:** with the cap set to 2 (nothing dropped),
  after the run `miner.walk()` is `[]`.
- **(ii) the hold:** with the cap at 1 — one `landed`, one
  `dropped-cap` — and **without appending a byte to the transcript
  between runs**, `miner.walk()` returns that file with `start_line`
  equal to its pre-run value.

*Broken:* today, and under M1, leg (ii)'s `walk()` is empty. Under M14
(the partial advance) leg (ii) is *also* empty — the recorded size
matches, so `walk` skips the file at `:334-335` — which is why the
"transcript unchanged between runs" condition is part of the criterion
and not an incidental detail.
*Vacuity guard:* leg (i) must run and pass in the same test; a fixture
that never advances any cursor would pass leg (ii) for free.

**A2 — no over-hold: other drop classes still advance.** A run whose
only non-landing outcomes are `scan-refused` (a candidate whose quote
trips `secret_scan`) and `dropped-invalid` leaves `miner.walk()` empty.
*Broken:* M2 — extending the hold to any drop outcome — reddens this,
and it is the anti-absorption pin: the cap is a decision about the
**run**, so a re-read changes the answer; a scan refusal or a malformed
record is a decision about the **candidate**, and a re-read reproduces
it identically, forever.

**A3 — the multi-candidate session: held once, replayed without
double-landing.** Modelled on the measured run `28117725`. One session,
cap 1, payload of three distinct candidates → 1 landed, 2 `dropped-cap`,
session held. Then raise the cap, replay **the identical payload**, and
run again:

- the previously-landed origin journals `skipped-known-origin`;
- both previously-capped candidates journal `landed`;
- the ledger holds exactly **three** pending records with distinct ids,
  and exactly one record carries the first origin.

*Broken:* without the hold (M1) the second run has nothing to read and
lands zero; under M3 (hold only when the session landed nothing) the
same; with dedup disabled (M17) the first origin lands twice and the
count is four.

**A4 — the filter touches the advance only, never canary scoring.**
Following the shipped
`test_canary_missed_when_source_session_mined_without_match`
(`test_miner.py:1872`): plant a canary whose `session` is the session
that will be held, with lesson text that matches nothing this run lands.
After a run that holds that session, the canary's status is `missed`.
Assert additionally, by monkeypatching `_score_canaries`, that the
session-id set it receives contains the held session.
*Broken:* M4 — filtering `processed` in place before `:1926` — leaves
the canary `open`, and the run is scored as if the session had never
been mined.

**A5 — M-5 wins: a halted slice advances and stays halted.** A
transcript whose early turns produce a cap-dropped candidate and whose
later turns contain `<command-name>/self-learn:review</command-name>`
(so `digest_transcript` returns a digest **and** `halt=True`,
`:488-490`). After the run:

- `miner._load_cursors()[str(path)]["halt"] is True`;
- `miner.walk() == []` (the halted file is skipped at `:332-333`);
- the outcome journals `cursor: "advanced-halted"`.

*Broken:* M5 (holding halted slices too) leaves no cursor entry for the
path at all, so both the `halt` assertion and the `walk` assertion fail
— the exclusion the 2026-07-15 audit installed would be silently
deferred to a re-derivation this unit is not entitled to rely on.

**A6 — an unmatched session holds nothing.** Two legs, both with a
cap-dropped candidate whose `session` is not in `digested`:

- **(i) fabricated:** the candidate cites a session id no transcript has;
- **(ii) excluded:** the candidate cites a real transcript that produced
  no digest (`digest_transcript` returned `None`, so it entered
  `processed` at `:1824` but contributed nothing to the prompt). A
  transcript of `tool(...)` lines only digests to `None` — the
  `tool_use` branch appends nothing to `out`, so `:522-523` returns
  early.

In both, `cursor` is `advanced-unmatched`, and in (ii) that transcript's
cursor advances to its end.
*Broken:* M6 — building `digested` from all of `processed` — reddens
leg (ii), and would pin a file that yields no digest into a re-read
every run for as long as the reader keeps naming it.

**A7 — a hold writes nothing.** Snapshot `miner._cursors_path()`'s bytes
before a holding run; after it, the held path's key is byte-identical
(absent stays absent, present keeps both `lines` and `size`), while a
second, non-held session in the same run **is** written.
*Broken:* M1 (writes a full advance), M14 (writes the partial advance).
The two-session shape is required: a criterion that only asserts "not
written" passes vacuously against a build that stopped writing cursors
altogether.

**A8 — no model-authored value reaches a cursor.** A cap-dropped
candidate carrying `line: 1` from a session whose slice starts far
beyond line 1 (append to an already-advanced transcript, so
`start_line > 0`). After the run the cursors file for that path is
unchanged (per A7) and the **next** run's slice has the same
`start_line` as this run's — never 0, never `line - 1`.
*Broken:* M15 — rewinding to the dropped candidate's line — reddens
this. This is the injection lever §3.2 refuses.

### B. Observability

**B1 — `cursor` is present, complete, and enumerated.** Across the
suite's fixtures assert (i) every `dropped-cap` outcome in the journal
carries `cursor`, (ii) its value is always one of the three literals,
(iii) no outcome of any other name carries the key, and (iv) **all
three values are observed** by the tests in this file (A1 → `held`,
A5 → `advanced-halted`, A6 → `advanced-unmatched`).
*Broken:* M7 (emit only in the held case) reddens (i) and (iv). The
value literals are asserted against the enrichment output read back from
the journal, which also proves `_enrich_near_miss`'s dict copy
(`:1198`) preserves the key.

**B2 — `cursors_held` counts distinct sessions.** A run with two
sessions, one dropping **two** candidates and the other dropping one:
the journal entry's `cursors_held` is `2`, while `result.dropped` is
`3`.
*Broken:* M8 (journal `result.dropped`) reddens it. The asymmetric
fixture is mandatory — with one drop per session the two numbers agree
and the criterion is vacuous.

**B3 — Obs stability, three legs.** For a run that drops one candidate
at cap:

- **(i) the CLI surface is byte-identical:** the outcome name is exactly
  `dropped-cap`; `disposition` is exactly `cap-refused`; `reason` is
  exactly *"a real lesson, but this run had already landed its cap"*;
  `promotable` is `True` for a clean snippet.
- **(ii) the UI drill row is unchanged** (in
  `plugins/self-learn/ui/tests/test_models_front.py`): a journal entry
  carrying `cursor` yields a `NearMissRow` with badge `cap refused`,
  `promotable=True` and a non-empty `draft_line` — identical to the same
  entry without the key.
- **(iii) `mine status`'s one-liner is unchanged:** the rendered line
  for an `ok` run contains `cap=` and `near-misses=` and does **not**
  contain a held count.

*Broken:* M9 (renaming the outcome) reddens (i) **and** (ii) — the
rename drops the row out of `_NEARMISS_DISPOSITION` (`:1061-1076`), so
the enrichment stops emitting `disposition`, and `_build_near_miss_rows`
skips it entirely (`models.py:1020-1022`): the human's only recovery
path for a capped lesson would vanish from the UI while every miner test
stayed green. M10 (adding a held count to the one-liner) reddens (iii).

### C. What must not change

**C1 — the flood gate still holds every cursor, before the reader.**
Re-run the shipped `test_run_held_gate_keeps_cursors`
(`test_miner.py:293-306`) unchanged: reader never invoked, `walk()`
still returns the session.
*Broken:* M11.

**C2 — the cap values and the scaling are untouched.** Re-run the
shipped `test_cap_scales_with_use` (`test_miner.py:259-268`) unchanged.
*Broken:* M12.

**C3 — `result.dropped` still counts every cap drop.** In A3's first
run, `result.dropped == 2` — held drops count exactly as they do today.
*Broken:* M13 (count only unheld drops), which would make the run report
fewer refusals than it made.

**C4 — canon and disposition, verified by the code gate.** `12-transcript-miner.md`
states the cursor hold and the M-5 precedence, and its §8 A1 journal
contract lists `cursors_held` and the `cursor` outcome field; the FW-73
row in `14-forward-work-map.md` is dispositioned in the build commit.
*Broken:* M16 — shipping the build without them — leaves two drop sites
with opposite documented designs and an open row pointing at fixed code.

---

## 5. Mutation plan

The code gate runs these. **Before any sweep:** `export
PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` — a stale cache
reports mutations as survived that never executed. Confirm
`realpath(self_learn.__file__)` resolves inside the tree under review.

| # | one-line edit | reddens |
|---|---|---|
| M1 | pass `processed` unfiltered to `_advance_cursors` (`:1934`) | A1(ii), A3, A7 |
| M2 | add `scan-refused` to the hold trigger beside `dropped-cap` | A2 |
| M3 | hold only when the session landed nothing this run | A3 |
| M4 | reassign `processed` to the filtered list before `_score_canaries` (`:1926`) | A4 — *and only A4: A1, A3 and A7 all stay green, which is why it must be red-verified rather than trusted* |
| M5 | drop the halt branch from H-2 (hold halted slices too) | A5 |
| M6 | build `digested` from every entry of `processed`, not the digest-contributing branch | A6(ii) |
| M7 | emit `cursor` only when the drop is held | B1(i), B1(iv) |
| M8 | journal `result.dropped` as `cursors_held` | B2 |
| M9 | rename the outcome `dropped-cap` → `dropped-cap-held` | B3(i), B3(ii) |
| M10 | append `held={…}` to the `mine status` one-liner (`cli.py:698-705`) | B3(iii) |
| M11 | move the flood-gate check below `_reconcile_and_land` | C1 |
| M12 | `DEFAULT_CAP_MAX = 30` | C2 |
| M13 | increment `result.dropped` only when the drop is not held | C3 |
| M14 | on hold, write `{"lines": s.start_line, "size": s.stat_size}` (the "partial advance") | A7, A1(ii) — *the trap: `walk`'s size skip (`:334-335`) makes this look like a hold and behave like an advance* |
| M15 | set a held file's cursor `lines` to the dropped candidate's `line - 1` | A8 |
| M16 | ship without the doc-12 amendment / FW-73 disposition | C4 |
| M17 | replace `existing_origins(home)` with `set()` at `:1223` | A3 (dedup leg) — proves A3 tests the replay guarantee rather than assuming it |
| M18 | classify the unmatched case as a fourth value `"advanced"` | B1(ii), A6 |
| M19 | set `cursor` on every outcome by defaulting it inside `_outcome` (`:810-811`) | B1(iii) |

---

## 6. Builder decisions, made here rather than left open

- **BD1 — the parameter is `digested: dict[str, bool] | None = None`**,
  added after `cwds` on `_reconcile_and_land`. Session id → that slice's
  halt flag. `None` behaves as `{}` (every cap drop classifies
  `advanced-unmatched`), so the function stays callable from a test
  without it.
- **BD2 — `_advance_cursors` is not touched.** The filter is a list
  comprehension at the `:1934` call site. Its signature is load-bearing
  for the idle path (`:1841`) and for four shipped tests that call it
  directly (`test_miner.py:237, 248, 938, 951`).
- **BD3 — `MineResult.held_sessions` is a `set[str]`** (`field(default_factory=set)`),
  and the journal writes its **length** under `cursors_held`. The field
  names what is held; the journal key names the effect. The set is never
  serialised — session ids already ride the journal inside origins, and
  a count is what `mine status` and any future census need.
- **BD4 — the `mine status` one-liner is not extended.** The
  per-candidate `cursor` value already appears in that same command's
  output through the extras dict (`cli.py:719-726`), so the aggregate
  would be redundant, and the one-liner's format is a documented
  surface. B3(iii) pins the decision so a later builder cannot "improve"
  it silently.
- **BD5 — the classification happens at the drop site, not at the
  advance.** Deciding `held` vs `advanced-*` later would require
  re-deriving which drops belonged to which slice, and the journal entry
  would then be written by a different code path from the decision it
  reports. One decision, one write.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 Not built, with reasons

- **The other drop sites.** `dropped-land-failed` (`:1372-1374`) is the
  nearest neighbour with the same shape: a `LedgerOpsError` can be
  transient, and its cursor advances too. It is **disclosed, not
  fixed** — FW-73 is about the cap, and absorbing a second failure class
  would put two different recovery stories in one unit. A future row
  should ask whether that site wants Rule-H or a retry.
  `scan-refused`, `dropped-invalid`, `dropped-rejected` and
  `rubric-dropped` are deliberately *not* candidates: re-reading
  reproduces each of those decisions identically, so a hold there is an
  infinite loop with no possible progress (A2 pins the boundary).
- **`landed-uncommitted` cursor advance.** Already answered by the
  self-healing reconcile (`:1790-1800`); untouched.
- **Any change to the cap, the gate, or their env overrides.**
- **Re-offering the five candidates already lost** (§1.2). They are past
  the cursor and their transcripts may have rolled; a `--since` backfill
  is the operator's existing tool and this unit does not automate it.

### 7.2 ACCEPTED residuals

- **R1 — `cap = 0` never advances.** With
  `SELF_LEARN_MINE_CAP_PER_SESSION=0`, `cap_for` returns 0 (`:167-171`),
  every candidate is cap-dropped, every digest-contributing session is
  held, and the miner makes no forward progress until the value is
  restored. This is **not a new behaviour class**: the sibling tunable
  already does exactly this — `SELF_LEARN_MINE_PENDING_GATE=0` makes
  `total_pending >= gate` true forever (`:1852`), wedging every run at
  the flood gate with all cursors held. An operator who sets a landing
  cap of zero has asked for "land nothing", and holding is the honest
  reading of that. Not fixed here; recorded so a future reader does not
  mistake it for an oversight.
- **R2 — a capped candidate from a halted slice is still lost.**
  §3.2 explains the trade; the loss is now *visible* rather than silent
  (`cursor: "advanced-halted"`), and the near-miss promote path remains
  its only recovery. Unmeasured frequency: no journaled run to date
  shows a cap drop and a mid-slice halt in the same session, so this is
  a reasoned bound, not a measured one.
- **R3 — the hold guarantees a re-READ, not a re-OFFER.** The reader is
  a model. A re-digested slice may not re-report the same candidate, or
  may report it differently. The deterministic recovery for that run's
  specific text stays what FW-34 shipped: the scanned near-miss snippet
  in the journal and the UI's promote button.
- **R4 — held slices re-spend budget.** Each held slice re-consumes its
  share of `MAX_PROMPT_DIGESTS_CHARS` and of the reader's context on the
  next run, and at the extreme can push another slice into the existing
  `deferred_files` stay-behind (`:1826-1828`). That mechanism loses
  nothing either, so the worst case is latency, not loss.
- **R5 — session-id aliasing.** Two transcripts sharing a stem under
  different project directories are held together (§3.1 H-5). Same
  aliasing `cwds` already has; over-holds, never under-holds.
- **R6 — the stay-behind precedent is design-level, not
  production-exercised.** `deferred_files` is `0` in all 27 journaled
  runs, so the branch this unit mirrors has never fired on the live
  ledger. That is why A1/A3/A7 test the hold's re-read directly rather
  than leaning on the precedent's field record.

---

## 8. What was measured, and against what oracle

1. **The journal census (§1.2).** All 27 entries of the miner run
   journal parsed; every outcome of every run scanned for
   `outcome == "dropped-cap"` and for the two session ids involved.
   Oracle: the journal is written by `_journal` (`:1461-1465`) at the
   end of each run and is the same file `mine status` renders. Result:
   2 capping runs, 5 lost candidates, 0 later re-appearances, 1 of the 5
   not promotable.
2. **The post-cap gate state (§3.4).** Runs 19-27 are `held-gate` with
   `pending` 36 → 32. Oracle: the same journal, `status` and `pending`
   keys written at `:1855-1858`.
3. **The mechanism (§1.1).** Read directly at `c8dcaf3`; every line
   reference in §1.1 and §3 was opened and confirmed, including that
   `digest_transcript` can return a **non-None digest together with
   `halt=True`** (`:488-490`), which is what makes §7.2-R2 a real case
   rather than a hypothetical.
4. **The consumer survey (§3.5).** Every reader of `dropped-cap` /
   `cap-refused` in the repo enumerated: `miner.py` (the fold maps),
   `models.py:572,1010-1036`, `routes.py:1141-1173`,
   `cli.py:719-726`, plus tests. None performs an exact-dict comparison
   on an outcome, and none enumerates keys — which is what makes O-1
   additive rather than breaking.
5. **The shipped-test survey.** Every test that produces a
   `dropped-cap` (`test_miner.py:677`, `:980`, the cap-refused
   near-miss family at `:1541`, `:1576`, `:1639`, and `:1966`) was read
   for cursor assumptions. All but one are single-run; the two-run one
   (`test_resurface_not_killed_by_cap`, `:980`)
   asserts landed counts and outcome names only, and its second run's
   shimmed payload does not cite the held session — so **no shipped test
   is expected to need editing**. A builder who finds otherwise must
   report it rather than adjust the test.

---

## 9. Revision history

- **r1** — first draft. Rule-H (hold, halt precedence, unmatched
  sessions), Obs-C, 15 acceptance criteria, 19 mutations, 6 declared
  residuals.
