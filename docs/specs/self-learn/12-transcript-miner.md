# 12 — The transcript miner: autonomous capture, mined provenance, and the embeddings question

**Status: RATIFIED 2026-07-15, same day as draft — user: "build now
without a shadow of a doubt." §8 records the ratification round (every §6
question answered, three user requirements added, six design additions
accepted). O-3 is resolved by this document (03-decisions carries the
dated edit). Absorbs the "transcript fire miner" follow-on from 08's
appendix — fire observation and lesson mining are one corpus walk with
two outputs. §9 is the build plan.**

## 0. Origin and the O-3 contract

O-3 (03-decisions) held autonomous capture at arm's length: *v1.1 at the
earliest, precision-tuned, and only if a month of teach+import volume
shows real lessons are still escaping* — an empirical question, never a
design being avoided. Two things changed on 2026-07-15:

1. **Anecdotal supply evidence.** Of the day's three genuine lessons, two
   entered the ledger only because a session happened to make the offer,
   and one because the assistant remembered its own gotcha across a
   compaction. Capture volume is visibly bottlenecked on offer-moments,
   not on lesson supply. (Anecdote, not the month of supply-mix data O-3
   asked for — §6 Q1 puts that tension to the user.)
2. **The user commissioned this design**, including a specific mechanism
   hypothesis (embedding-based transcript retrieval) to be assessed on
   one axis: *helpful, or an unnecessary layer of abstraction?* §5 records
   that assessment in full — it is a design decision of record, not a
   footnote.

**Doctrinal position: the miner is continuous import.** The teach path's
"never silently capture" rule governs Claude composing a record from a
live conversation with the human present — the confirmation *is* the
human's participation. Import established the other legitimacy model:
bulk ingest without per-record confirmation is sound *because the review
gate adjudicates every record before anything touches canon*. The miner
inherits import's model and moves the human gate entirely to review.
What it may never do is route (invariant M-1, §7).

## 1. Position in the architecture

A third producer beside teach and import; everything downstream is
untouched:

```
teach   (human-confirmed, in-session)   ─┐
import  (bulk, human-invoked)           ─┼→ pending/ → M2 worker analyzes → review adjudicates → canon
miner   (autonomous, machine-suggested) ─┘
```

- Provenance: `source: session` — already in the schema enum (02 §1,
  forward-declared for exactly this producer). **No schema migration.**
- Mined records land in `pending/` only, are analyzed by the existing
  worker before any human sees them, and surface on ordinary review
  cards. The worker's card `provenance` section carries the mined origin
  ("machine-mined from session …, why-durable: …") — the analyst reads
  `source: session` off the record; **no card-registry change**.
- Fire observations (a routed rule's trigger-situation occurring in a
  later session, complied or violated) land as telemetry events using
  the existing closed `fire` kind — ids/enums only, per S-7.

## 2. Pipeline

Four phases. 0–1 and 3–4 are deterministic code (fixture-testable); 2 is
the one judgment layer, and it is an LLM, not a similarity metric (§5).

### Phase 0 — walk and cursors

Enumerate `~/.claude/projects/<slug>/*.jsonl` newer than the per-file
cursor (session id + byte offset, stored in
`${XDG_CACHE_HOME}/claude-skills/self-learn/miner/cursors.json` — cache,
never repo). Scope of `<slug>` is a ratification item (§6 Q2: all
projects vs allowlist). Transcript retention (`cleanupPeriodDays`) plus a
daily cadence means the cursor never races deletion.

**Loop exclusions (M-5):** skip transcripts whose opening prompt matches
the pinned worker or miner prompt headers (the system must not mine its
own machinery); skip spans inside `/self-learn:review` and
`/self-learn:teach` command execution (identifiable by command tags in
the transcript) — a review session *discusses* lessons, and mining the
discussion re-captures them. Phase 3 dedup is the backstop for anything
the exclusions miss.

### Phase 1 — structural digest (deterministic, no model, no embeddings)

Reduce each transcript to an ordered, speaker-tagged skeleton:

- **user turns: kept verbatim** — corrections are speech acts and live
  here; user turns are a tiny fraction of bytes;
- **assistant text turns: kept** (final messages and inter-tool prose —
  where discoveries get stated); tool-call bodies dropped;
- **tool results: bodies dropped**, keeping status, error flag, and
  first/last lines — tool results are >90% of transcript bytes and ~0%
  of lesson *statements* (lessons are about results, stated in text);
- **annotations:** error events (is_error, non-zero exits) and retry
  clusters (normalized command shape recurring with edits) marked
  in-line; every kept span carries a turn ref (session id + line) so
  candidate evidence can cite a real location.

Expected reduction 10–50× with essentially zero recall loss — this is
the "focusing" layer, and it is structural (§5 for why).

### Phase 2 — the reader (LLM, rubric-driven, contained)

One `claude -p` per run over batched digests (batch cap by digest bytes;
unread files stay behind the cursor for the next run). Containment is the
M2 worker posture verbatim: `--allowedTools "Read,Grep,Glob"`, the same
disallow list, and a settings file granting the `Edit(//…)` rule family
over the miner spool directory only (the live-verified syntax, 08
appendix 2026-07-15).

The prompt's judgment core is **`references/mining-rubric.md` — a
versioned, curated file of lesson-shapes with exemplar phrasings**:
corrections ("no —", "I told you", "never do X here"), failure→recovery
arcs, stated preferences, repeated-friction patterns, discovery
statements ("turns out", "the actual cause was"). *This is where the
user's "strong set of search terms and phrases" lives* — applied by a
reasoning model that understands stance and context, not by cosine
similarity (§5). Reject notes from review feed rubric revisions, the
same loop the routing analyst's rejected-proposal digest runs.

Structured output (schema-validated, like the worker):

- **candidates** — draft record fields (type/kind/scope guess, Trigger +
  Instruction in the record's voice, shortest-span evidence quote + turn
  ref, inferred grounding: verified/verified_how/incident_cost/
  generality) plus `confidence` and a one-line `why_durable`;
- **fire observations** — given the compiled canon index (record id +
  trigger line, supplied in the prompt): spans where a routed rule's
  situation occurred, marked complied|violated, with turn ref.

### Phase 3 — ledger reconciliation (mechanical, in the CLI)

Each candidate is compared against the ledger index (id + title +
trigger of every pending/resolved/rejected record — small enough to ride
in the Phase 2 prompt, so the reader performs the comparison with full
reasoning and the CLI enforces the id-level consequences):

| Candidate matches… | Consequence |
|---|---|
| a **pending** record | evidence append (sighting++), no new record |
| a **routed** record | recurrence event → existing "not holding" card flow |
| a **rejected** record | dropped by default (the human said no); counted in the run report; resurfacing policy is §6 Q4 |
| nothing | lands as a new pending record |

### Phase 4 — landing (verb-gated, capped, scanned)

All writes through a CLI verb (`self-learn mine land`, reusing import's
writer path with `source: session`): per-record secret scan (refuse
default, no bypass), evidence-quote length cap, sentinel hold for the
batch, pinned commit subject `self-learn: mine <n> candidate(s)
(<run-id>)`, then a worker kick so every mined record is analyzed before
a human ever sees it.

**Flood control (M-4, hard):** per-run landing cap (default **3**);
total-pending gate — land nothing when `total_pending ≥ 10` (the
escalation threshold is ≥5 pending; an uncapped miner would perma-trip
it and train the user to ignore the alarm). Skipped candidates are
logged in the run report, not silently dropped.

## 3. Scheduling and containment

- **Trigger: nightly `cron-claude` timer** (the house scheduler), not a
  worker phase and not SessionEnd. The worker is event-kicked (a capture
  happened); mining is time-driven (transcripts accumulated) — coupling
  them muddies both, and a miner failure must never block analysis.
  SessionEnd was O-3's original shape and is declined: E-11 (1.5s,
  best-effort, crash-lossy), per-session spawn noise, and it forfeits
  the cross-session view (repeated friction is only visible in batch).
  The nightly batch sees everything SessionEnd would — later, but
  completely. (§6 Q5 ratifies this amendment to O-3's wording.)
- `miner.lock` flock; never shares `worker.lock`.
- Kill switches: disable the timer, or `SELF_LEARN_MINER=0` honored by
  the entrypoint. **E-11 stands: nothing may depend on the miner
  running.** It is additive supply; teach and import remain complete
  without it.

## 4. Calibration: the metric that decides the miner's fate

**Mined-card accept rate at review** — (routed + graduated) / adjudicated,
computed from existing card-decided telemetry plus a `source` dimension,
surfaced in `report` beside the supply-mix block M3 already plans. Report
honesty labels apply: the rate is measured over adjudicated cards only.

Probation: the 3/run cap holds for the first month; raising (or killing
the miner) is a user decision on the numbers, recorded as a dated
register edit. A miner whose candidates get rejected wholesale is
answering O-3 with "no" — the design must make that outcome cheap to
see and cheap to act on.

## 5. The embeddings decision (assessed 2026-07-15, user-commissioned)

**The proposal assessed:** chunk and embed transcripts; query with a
curated set of anchor terms/phrases; mine the top-k similar chunks —
evaluated purely on *helpful vs unnecessary abstraction*, cost excluded
by instruction.

**Finding: at the transcript side, an unnecessary layer.** Four reasons:

1. **Teachable moments are speech acts, not topics.** Corrections,
   refusals, failure→recovery arcs are *pragmatic* patterns — and
   stance, negation, and short utterances are precisely where embedding
   similarity is weakest. An anchor like "never edit config while the
   service runs" retrieves chunks *about* config editing, not moments of
   *being corrected* about it; "no." — the highest-value token in the
   corpus — embeds into noise.
2. **The signal is already structural.** Speaker identity, turn type,
   error flags, retry shapes: deterministic, explainable ("this
   candidate exists because exit≠0 occurred 3× and the next user turn
   was corrective"), fixture-testable, drift-free — and Phase 1's
   structural superset (all human/assistant text + error annotations) is
   high-recall *by construction*, because lessons are stated in text
   turns while tool-result bodies carry >90% of bytes and ~0% of lesson
   statements.
3. **Lesson arcs span turns.** Attempt → failure → correction →
   resolution crosses any chunk boundary; chunk-level retrieval returns
   fragments, and reassembling the arc requires exactly the turn-
   structure navigation that made retrieval redundant.
4. **A ranking layer is a budget-allocation device.** An LLM reader must
   read every surviving candidate regardless — composition requires
   judgment no similarity metric supplies. With cost excluded from the
   frame, a retrieval layer inserted between the structural superset and
   the reader can only *silently lower recall* (dropping what the reader
   would have caught); its benefit evaporates while its miss-modes
   remain. And its worst miss-mode is the worst possible one: the novel
   gotcha that resembles no anchor — the lesson nobody thought to
   enumerate — which is the miner's whole reason to exist.

**What survives of the idea — the rubric.** The curated anchor set is
genuinely valuable *as the reader's generation prompt*
(`mining-rubric.md`, Phase 2): exemplar phrasings applied by a model
with full reasoning rather than by cosine distance. The curation
instinct is kept; the mechanism is upgraded.

**Where embeddings DO earn a place — the ledger side.** Matching a
*distilled* candidate against *distilled* records (Phase 3 dedup,
recurrence, fire-matching) is same-register, same-length, topical
similarity — embeddings' home turf. The current recurrence heuristic
(title-token Jaccard ≥ 0.6) is the weakest link there: "don't edit
.storage live" vs "stop HA before touching storage JSON" share almost no
tokens and one meaning. **Pinned scaling path:** move Phase 3 matching
to an embedding index when either (a) the ledger index outgrows
comfortable prompt residence (~200+ records) or (b) a review session
surfaces a missed duplicate the in-context pass should have caught.
Until then, LLM-with-index-in-context is strictly more accurate than
cosine and adds no infrastructure. Distill-then-match beats match-raw.

**znote MCP: declined for the autonomous path.** (1) Storing candidates
as z-notes creates a second source of truth beside the ledger; (2)
ingesting transcript chunks into the zettelkasten pollutes a curated
corpus; (3) widening the miner's tool surface beyond Read/Grep/Glob
weakens the containment posture that was live-verified on 2026-07-15.
Legitimate marginal use: during *interactive review*, the session may
consult `zk_search_notes` while discussing a card (is this gotcha
already documented in a z-note?) — human-present enrichment, never a
pipeline dependency. Likewise episodic-memory's transcript search may
someday accelerate fire-detection known-item lookups — verify its actual
capabilities before depending on it, and never load-bearing (E-11
spirit).

## 6. Ratification questions

- **Q1 — the O-3 gate.** Build now on the 2026-07-15 anecdote, or hold
  until M3's supply-mix month confirms lessons are escaping? Either
  answer is a dated register edit to O-3.
- **Q2 — privacy scope.** The miner reads transcripts — everything typed
  in any session. All projects by default, or an explicit allowlist
  (start with `-home-komi-repos-claude-skills` + skill-owning projects)?
- **Q3 — defaults.** Nightly cadence; 3 landings/run; pending-gate 10.
  Confirm or adjust.
- **Q4 — rejected-match resurfacing.** Drop forever, or resurface with a
  new-evidence flag after N fresh sightings?
- **Q5 — O-3 wording amendment.** SessionEnd appender → nightly batch
  miner (§3 rationale). Confirm the shape change.

## 7. Invariants

- **M-1 · Mined records never auto-route.** The miner grows the queue;
  only the human, at review, changes canon. No exception, no flag.
- **M-2 · Landing is verb-gated.** Every mined write passes the CLI's
  secret scan (refuse default), caps, sentinel, and pinned commits —
  the miner has no direct file or git path into the repo.
- **M-3 · Never load-bearing (E-11).** teach and import remain the
  complete capture story; the miner is additive and killable at any
  moment with zero data loss.
- **M-4 · Caps are hard.** Per-run and pending-gate limits refuse, not
  warn; overflow is reported, not squeezed through.
- **M-5 · The system never mines itself.** Worker runs, miner runs, and
  self-learn command spans are excluded at Phase 0; Phase 3 dedup is
  the backstop, not the mechanism.
