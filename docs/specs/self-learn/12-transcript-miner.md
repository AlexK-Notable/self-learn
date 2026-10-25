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
  later session) land as telemetry events using the existing closed
  `fire` kind — ids/enums only, per S-7. *Amended 2026-09-13 (U6):* the
  miner marks the situation `suspected-compliance`,
  `suspected-violation`, or `cannot-tell` — a suspicion for the steward to
  evaluate against the rule's actual text and the surrounding transcript,
  never a verdict the miner itself renders (`11-telemetry-and-lifecycle.md`
  §4.3 as amended).

## 2. Pipeline

Four phases. 0–1 and 3–4 are deterministic code (fixture-testable); 2 is
the one judgment layer, and it is an LLM, not a similarity metric (§5).

### Phase 0 — walk and cursors

Enumerate `~/.claude/projects/<slug>/*.jsonl` newer than the per-file
cursor (transcript path + consumed line count + observed byte size, stored in
`${XDG_CACHE_HOME}/self-learn/home-<hash>/miner/cursors.json` — cache,
never repo). Scope of `<slug>` is a ratification item (§6 Q2: all
projects vs allowlist). Transcript retention (`cleanupPeriodDays`) plus a
daily cadence means the cursor never races deletion.

**Newline numbering and legacy cursors (2026-10-24).** Both engines count
only LF boundaries, agreeing with `#L<n>` in 02-schema §3a.6. A trailing CR
is retained as JSON whitespace; an unterminated tail stays unread. New cursor
entries, including the cursor saved inside a session engine waiting answer,
carry `line_format: newline-v1`. An entry without that marker counts the old
Python `splitlines()` pieces: on reading a grown file, translate its consumed
prefix to the equivalent number of physical rows before slicing. Persist the
new count and marker on the normal cursor advance. Unchanged/skipped files
keep their cheap size/skip checks and migrate lazily on their next cursor advance.
Waiting-answer replay converts both its saved cursor and the current cursor
before the forward-only comparison; it never rewrites the saved answer for
migration. Preview/backfill reads do not migrate files on disk. A malformed
old count inside a physical row leaves that row unread; a count beyond a
truncated file preserves the overrun rather than rewinding to its end.
Quotes/UUIDs follow old citations at read time as specified in 02-schema
§3a.6; the ledger's historical origin strings remain unchanged.

When both waiting and current cursors are already marked, replay compares
their counts without reading the transcript body (existence/size checks
remain). Cursor writes omit `halt` when false. The first-user opening scan
and captured-session entry counts also stream by LF, retaining replacement
decoding for malformed UTF-8.

Both engines' nightly and backfill landing use one in-memory origin index
that follows stored evidence quotes/UUIDs before comparing LF-numbered
candidates. The same translation serves lesson dedupe, a sighted record's
held evidence, and tracked/spooled recurrence-event keys. History is never
rewritten. Each corrupt record independently retains its raw-origin fallback,
even when a parsed record translates the same string.

The index streams each referenced transcript copy once per drain to check
whether its counts differ. Only affected files invoke resolution, reusing the
run's provenance sends rather than sweeping per user row. The exact test is
whether any physical row plus LF produces more than one `splitlines()` piece:
bare CR, VT, FF, U+001C–001E, U+0085, U+2028 or U+2029 can do so; CRLF alone
cannot. Missing copies keep their raw keys. Subagent origins identify their
own log and preserve that subagent path when followed.

New miner fire/recurrence events carry `line_format: newline-v1`; event keys
use `moment` UUIDs when present, otherwise unmarked affected-file positions
use the legacy count. Marked UUID-less event positions are never translated
again. No historical telemetry is rewritten.

Rejected-sighting cache lists migrate old origin positions when their source
is available, replacing each with `uuid:<entry uuid>` or, for UUID-less rows,
`newline-v1:transcript:<session>#L<n>`. Newly written keys always carry one of
these markers, so later reads cannot translate them twice. Unavailable old
origins remain raw and are retried later; their exact-origin dedupe remains.
The terminal `landed` mark is unchanged. The same moment does not add another
sighting merely because its old line count differs from its LF count.

**Loop exclusions (M-5):** skip transcripts whose opening prompt matches
one of the system's own prompt openings (the system must not mine its
own machinery): the worker's normal and repair passes, the miner's own
reader, the steward and the overseer. Each agent's opening is defined
beside the prompt that makes it (`worker.SESSION_OPENINGS`,
`steward_prompt.SESSION_OPENINGS`, `overseer.run.SESSION_OPENINGS`) and
`miner.SELF_PROMPT_HEADERS` unpacks them, so an edit to a prompt cannot
quietly start the miner reading that agent's sessions again
(2026-10-06). A session the cursor file already tracks is checked once
per header list by `halt_tracked_self_sessions` (its fingerprint is
kept in `cursors.json`); a file that cannot be read is checked again on
the next run, and a malformed row is skipped, never raised on.
Program-run sessions that are not self-learn's own are still mined, except a scheduled job's
(below); skip spans inside `/self-learn:review` and
`/self-learn:teach` command execution (identifiable by command tags in
the transcript) — a review session *discusses* lessons, and mining the
discussion re-captures them. Phase 3 dedup is the backstop for anything
the exclusions miss.

**Scheduled jobs (added 2026-10-07).** A rule of its own, not part of
M-5: a scheduled job is not self-learn. It rests on the user's words of
2026-10-07: "scheduled jobs maybe not unless i explicitly ask for
coverage. background jobs yes." A session whose first user turn begins
with a `<scheduled-task` tag (the opening Claude Desktop's scheduler
writes: `<scheduled-task name="<task>" file=".../scheduled-tasks/<task>/SKILL.md">`)
is halted for good, exactly as a self-learn session is, unless the tag's
`name` attribute is listed in the setting `miner.mined_scheduled_jobs`
(config `miner.mined_scheduled_jobs`, env
`SELF_LEARN_MINER_MINED_SCHEDULED_JOBS`; comma-separated; empty by
default, so every scheduled job is skipped). A Claude Code background
session and a typed session are mined as before. Sessions the cursor
file already tracks are checked once per opt-in list by
`halt_tracked_scheduled_sessions` (fingerprint `__scheduled_jobs__` in
`cursors.json`), so taking a job off the list halts its tracked
sessions on the next mine, while adding one does not reopen a session
already halted. The run log counts halts by reason only (`scheduled
job`, `self-learn prompt`, `self-learn command`), never a job's name or
a path. Known limit, shared with the self-prompt rule: "first user
turn" is the first one in the slice a run reads, so a typed session
whose later slice opens with the tag is halted too.

**Sessions the user lists (added 2026-10-11).** The user, 2026-10-11:
"add the ability to create a blacklist of session id's for the miner. that
feels like it should be trivial". The setting `miner.skip_sessions` (config
`miner.skip_sessions`, env `SELF_LEARN_MINER_SKIP_SESSIONS`; comma-separated
session ids, each a transcript's file stem `<project>/<id>.jsonl`; spaces and
empty items ignored; empty by default) names sessions the walk skips before
reading them, in the normal cursor path and in the `--since` backfill alike.
That second branch is the difference from `halt`: a backfill re-reads halted
files from line 0, but never a listed one. The list is read on every walk and
nothing is written for it, so taking an id off makes its file minable again
from its cursor, or from line 0 if it never had one. The use in view is a test
bed that copies a transcript under new session ids (`claude --resume <id>
--fork-session --session-id <id>`): each copy has a new id, so landing's
`transcript:<session id>#L<n>` dedup would not catch its lessons. The list
reaches only the walk: first activation's seeding (`initialize_cursors`)
still reads a listed file whole, the passes over tracked sessions
(`halt_tracked_self_sessions`, `halt_tracked_scheduled_sessions`) still read
the head of a listed file the cursor file tracks, and the
checked-pointer resolver (`refs.py`), through the steward's briefs and the
offline comparison, still reads it when a lesson cites it or a quote is
searched for. The run log does not count listed skips.

*2026-10-24: the offline comparison harness (`mining/compare.py`) is retired and removed; references above describe its historical role.*

**Cap holds (amended by `U-cursorhold`, FW-73).** A candidate refused at
Phase 4's per-run landing cap holds its originating session's cursor
rather than advancing past it, so the refusal costs a re-read, never the
candidate; a session already excluded under M-5 above always keeps that
exclusion — the hold never overrides the halt.

### Phase 1 — structural digest (deterministic, no model, no embeddings)

Reduce each transcript to an ordered, speaker-tagged skeleton:

- **user turns: kept verbatim** — corrections are speech acts and live
  here; user turns are a tiny fraction of bytes. Each is labelled by who
  wrote it, by `refs.role_of` with the run's sends (02 §3a.6 rule 10,
  S-90): `[user]` for the person, `[agent]` for another agent's text
  typed in as if by the person, `[relay]` for text the harness or a
  program put there (a headless `claude -p` or SDK prompt, a task
  notification, skill text, a compaction summary), `[subagent]` for a
  sidechain row; a row that also carries a tool result keeps `[user]`.
  The reader's prompt and the rubric say only a `[user]` line is the
  person's words. The halts (self-prompt header, scheduled job, command
  tag) read every user text turn, whoever wrote it;
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

One model invocation per run over batched digests (batch cap by digest
bytes; unread files stay behind the cursor for the next run) — the
`miner-reader` surface of the invocation seam. *Amended 2026-08-25
(U-cleanup):* the `claude -p` subprocess backend this sentence used to
name as the default is retired — every surface, including this one, runs
on the Agent SDK unconditionally now (`03-decisions.md` `S-49`); "by
default" no longer means anything, since there is nothing else left to
default away from. Containment is the worker posture **tightened, not
copied**: the reader gets **no filesystem read tools at all** —
`build_reader_argv` (deleted alongside `CliBackend`, §8.1 of the
U-cleanup spec) used to emit no `--allowedTools` flag for this surface;
the sdk path's `options_kwargs` sends `allowed_tools: []` unconditionally
for every surface now (`invocation_sdk/backend.py`, `F-B`), so the whole
mechanism enforcing "no filesystem read tools" for the reader
specifically is the deny side alone — `READER_DISALLOWED_TOOLS` is the
worker's deny
list **plus `Read,Grep,Glob`** — because the reader's entire evidence base
rides in the prompt and transcript digests are attacker-influenceable text
(audit 2026-07-15, injection hardening). Write stays available only
through the settings file's `Edit(//…)` rule family, scoped to the cache
spool (the live-verified syntax, 08 appendix 2026-07-15). *(corrected
2026-08-19, U-docs: "the M2 worker posture verbatim" was wrong in the
direction that matters — the reader is stricter, not equal — and this
file already said so at §12.2 ("reader containment (Read/Grep/Glob-less)
is untouched"); the two statements contradicted each other and the code
sides with §12.2.)*

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
  generality) plus `confidence`, a one-line `why_durable`, and — *added
  2026-07-18, §11* — an optional **`episode_brief`**: a 100–200-word
  plain-words reconstruction of the episode, written from the same digest
  read and landed into the record body's `## Episode brief` section (§11
  is the full contract);
- **fire observations** — given the compiled canon index (record id +
  trigger line, supplied in the prompt): spans where a routed rule's
  situation occurred, marked `suspected-compliance \| suspected-violation \| cannot-tell`, with
  turn ref *(amended 2026-09-13, U6 — see §1's amendment; the miner's
  reader classifies a suspicion, the steward decides what it means)*.

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
logged in the run report, not silently dropped. **Amended by
`U-cursorhold` (FW-73):** a candidate refused at the per-run cap holds
its originating session's cursor instead of advancing past it — the same
posture the total-pending gate above already takes — so the candidate is
re-offered whole on a later run rather than lost; the M-5 halt still
takes precedence, so an already-excluded session's cursor is never held
on its account.

## 3. Scheduling and containment (amended 2026-08-27, U-engine Phase 2)

- **Trigger: two supported topologies, not a worker phase and not
  SessionEnd** either way. The worker is event-kicked (a capture
  happened); mining is time-driven (transcripts accumulated) — coupling
  them muddies both, and a miner failure must never block analysis.
  SessionEnd was O-3's original shape and is declined: E-11 (1.5s,
  best-effort, crash-lossy), per-session spawn noise, and it forfeits
  the cross-session view (repeated friction is only visible in batch).
  The nightly batch sees everything SessionEnd would — later, but
  completely. (§6 Q5 ratifies this amendment to O-3's wording.)
  - **Timer-scheduled (original; unchanged by Phase 2):** the nightly
    `cron-claude` timer (`self-learn-miner.timer`, the house scheduler)
    fires `self-learn mine run` as a detached process. This remains the
    topology on any host that does not adopt the Phase 2 host process —
    nothing about it changed underneath U-engine.
  - **`serve`-scheduled (added, U-engine Phase 2; preferred where
    adopted):** `self-learn serve`, a long-lived host process, starts
    the same mine job on its own in-process clock instead of a timer
    starting a detached one (`17-invocation-runbook.md` §10). Neither
    topology changes the mine job itself — same lock, same cap, same
    reconciliation, same landing gate, same kill switches (below).
    Adopting `serve` is a per-host deployment choice, not a code
    default: `install.sh` links its unit but does not enable it, so a
    host that never enables it keeps the timer topology exactly as
    before.
- `miner.lock` flock; never shares `worker.lock`.
- **The any-verb watchdog now has two dispositions, not one.** Every
  `self-learn` verb except `mine` and `init` still opportunistically
  reacts to a >24h-stale last-run, but what it *does* depends on
  whether `serve` is both configured and alive: **poke** — if `serve`'s
  heartbeat is fresh, the verb asks `serve` to run its next job on its
  own next tick instead of spawning anything itself; **fall back to the
  original spawn** — a detached `mine run`, `SELF_LEARN_MINER_AUTOKICK`-
  gated — whenever `serve` is not configured, or is configured but its
  heartbeat is stale or absent (dead `serve`, or the timer-only
  topology, read identically here: no live `serve` to poke). The
  watchdog never blocks on `serve`'s liveness or tries to start it — a
  dead `serve` is `doctor`'s `serve` row's problem to surface loudly
  (`17-invocation-runbook.md` §10), not this watchdog's problem to work
  around.
- **Kill switches keep their documented meaning under both
  topologies.** Disabling the timer stops the timer-scheduled trigger;
  stopping/disabling `self-learn serve` stops the `serve`-scheduled
  trigger (`17-invocation-runbook.md` §10); `SELF_LEARN_MINER=0`,
  honored by the entrypoint, stops the mine job itself regardless of
  which topology (or watchdog leg) tried to start it.
  `SELF_LEARN_MINER_AUTOKICK=0` disables only the watchdog's fallback
  spawn leg, exactly as before — it has no poke leg to disable, since a
  poke is not a spawn. **E-11 stands: nothing may depend on the miner
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
*Amended 2026-08-19 (U-docs):* read "beyond Read/Grep/Glob" as "beyond
the reader's tool surface, which is **empty**" — those three are in
`READER_DISALLOWED_TOOLS`, not granted (see §2's Phase-2 paragraph as
corrected, and `Sub-9`). The argument is unaffected and in fact stronger:
granting the miner an MCP tool surface would not widen a narrow grant, it
would **create** one where none exists.
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

  *Amended 2026-09-13 (S-29 as amended):* "only the human" is superseded for
  who changes canon at review — the steward now does, nightly, alone
  (`01-architecture.md` §3.3a) — but the miner-side half of this invariant is
  untouched and remains absolute: **the miner itself never auto-routes, under
  any actor.** A mined record still lands in `pending/` and is still analyzed
  by the worker before either a human or the steward ever sees it.
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

## 10. Pre-merge audit round (2026-07-15, two independent reviewers)

Two blind-to-each-other auditors (adversarial code + systems blast
radius) each returned merge-blocking verdicts; all blockers and majors
were fixed with regression tests reproducing the exact scenarios. The
findings that ADJUSTED pinned behavior (dated letter-adjustments):

1. **Prompts ride stdin, never argv** — Linux caps one argv element at
   128 KiB (verified E2BIG live); a busy night's digests exceed it.
   Applied to the miner AND the M2 worker (whose 15-record batch prompt
   was plausibly already over the limit — latent since T13).
2. **The reader has NO filesystem tools** (§2 Phase 2 strengthened):
   unlike the worker, its whole evidence base is in the prompt, and
   transcript digests are attacker-influenceable — Read/Grep/Glob are
   disallowed; Write exists only via the spool-scoped rule family.
   Field-length caps enforced at landing (quote 400, fields 1000 chars,
   refuse-not-clip); model-authored session/line refs are regex-gated
   before they touch origins or telemetry.
3. **A self-learn command tag halts the REST of the session, forever**
   (M-5 tightened): the draft's "span ends at the next genuine user
   turn" collapsed on the first review reply, mining every card's
   verbatim lesson text back as fake sightings. Halt state persists in
   the cursor file across slice splits. Recall loss is cheap; evidence
   corruption is not.
4. **First run = cursor initialization only** (§8 R2 made real): status
   `initialized`, every existing transcript seeded at EOF, files already
   containing self-learn markers halted outright. Measured stake: 267 MB
   / 538 transcripts on the build machine.
5. **Watchdog attempt cool-down (2 h)** beside the 24 h completed-run
   check — a persistently failing reader must not turn every CLI
   invocation into a walk + 15-minute model attempt. *(2026-08-26,
   U-fw100/FW-100: the 15-minute figure is now the default, not a
   fixed value — env-overridable via `SELF_LEARN_READER_TIMEOUT_SECS`,
   `miner.reader_timeout_secs()`.)*
6. **Worker re-asserts the sentinel after its model pass** — a
   concurrent short holder (miner landing) could create-then-release
   the sentinel a mid-run worker had merely joined, deleting autosync
   cover before validation (the exact race the 2026-07-15 self-hold pin
   closed, reopened from the other side).
7. **Fire / recurrence-suspect events dedupe by (kind, record, origin)**
   — crash-replay and the documented `--since` replay previously
   duplicated both classes.
8. **Spec adjustments accepted:** mined landings ride autosync commits
   (like teach and import; the §9 pinned `self-learn: mine …` subject is
   dropped — no consumer greps it, and capture-producers have never
   owned commits); held-gate skips the entire run body including fire
   observation (saves the model pass; cursors hold so nothing is lost)
   and touches last-run (the ≥5-pending escalation alarms on the same
   condition the gate reacts to); the run journal stays cache-local.

Suite after the round: 540 (30 miner + 13 audit regressions on top of
the pre-audit 497).

## 8. Ratification round 1 (2026-07-15, user present)

**Q1 — build now.** User: "build now without a shadow of a doubt.
Autonomous lesson capture with 'manual' human review, and potentially
autonomous review, are goals." O-3 resolved (dated edit in 03); the
register stands at 16 settled · 0 open. The E-11 never-load-bearing
clause survives as M-3.

**Q2 — all projects.** The miner reads every project's transcripts.
Legitimacy chain: single-user machine → secret scan on every landing →
human review before canon.

**Q3 — caps scale with use, start loose.** User: a fixed 3/run is
constrictive on a 12-hour day. Amended: per-run landing cap =
`min(CAP_PER_SESSION × sessions_scanned, CAP_MAX)`, defaults 2 and 15;
pending-gate default 25. All env-tunable
(`SELF_LEARN_MINE_CAP_PER_SESSION`, `SELF_LEARN_MINE_CAP_MAX`,
`SELF_LEARN_MINE_PENDING_GATE`). M-4 amended accordingly: the *values*
scale; the *enforcement* stays hard, and the journal records every clip.

**Q4 — resurface on evidence.** A candidate matching a rejected record
is dropped and counted (cache-side, per rejected id); at 3 fresh
sightings it lands once, its why-durable carrying the resurfacing
context ("previously rejected as lrn-X; sighted 3× since") so the
analyst's card surfaces it honestly. No schema change.

**Q5 — nightly batch confirmed** over SessionEnd (§3 rationale stands).
Mechanism note: the schedule is a plain systemd user timer executing
`self-learn mine run` — not literally a cron-claude job, because
cron-claude schedules `claude -p` prompts and the miner's entrypoint is
a CLI verb that spawns its own contained `claude -p` internally.
*Amended 2026-08-19 (U-docs):* "its own contained `claude -p`" is now
"its own contained model invocation through the seam's `miner-reader`
surface"; `claude -p` is the default backend. *Amended again 2026-08-25
(U-cleanup, `03-decisions.md` `S-49`):* "the default backend" no longer
means anything — `claude -p` (the `cli` invocation backend) is retired,
and the seam's `miner-reader` surface, like all four surfaces, runs on
the Agent SDK unconditionally; there is no other backend a
`SELF_LEARN_BACKEND_MINER` pin could select. Note for operators: because
the miner runs from a **systemd user timer**, and the user manager does
not inherit a login shell's environment, a `config.yaml` edit — not an
exported env var — is the only flip that reaches the nightly run;
`17-invocation-runbook.md` §8 (`invocation-runbook.md`'s own numbered
§4.1 that this note used to cite is retired along with the rest of the
old §4).

*2026-10-24: the backend selector keys are retired; the historical flip advice above no longer applies. All miner invocations use SDK; `config unset invocation.backend_miner-reader` removes an obsolete key without changing the backend.*

**User requirements added:**

- **R1 · 24-hour watchdog, three layers:** `Persistent=true` on the
  timer (machine-was-off → fires at next boot); any self-learn verb
  opportunistically kicks a detached `mine run` when the last run is
  >24h old and no run is live (timer-broke; suite-disabled via
  `SELF_LEARN_MINER_AUTOKICK=0`, runtime kill via
  `SELF_LEARN_MINER=0`); the SessionStart status line gains a
  miner-staleness clause at >36h (everything-broke — a silent death is
  humanly visible within a day). *(As ratified 2026-07-15. The middle
  layer's disposition gained a second leg in U-engine Phase 2 — see §3,
  amended 2026-08-27: it now pokes a live `serve` instead of spawning,
  when one is configured and its heartbeat is fresh. The first and
  third layers, and this layer's fallback spawn, are unchanged.)*
- **R2 · Manual force:** `self-learn mine run` executes immediately
  (the timer calls the same verb). Force controls *timing* only — caps
  and the secret scan are never bypassable. `--since <date>` performs a
  deliberate historical sweep (first-run cursor is otherwise *now*:
  forward-only, no backlog flood).
- **R3 · Web-UI rider (binds 09/10 when G-3 builds):** the miner pane
  is a pure reader of the run journal plus exactly one action endpoint
  (force-run). All insight questions — last run, caught, skipped,
  choices made — are answered by the journal contract below, never by
  UI-side inference. *(Consumed 2026-07-17: 09 §11 Y-5 designs the
  pane to this rider; the journal's JSON rendering is the EXISTING
  `mine status --json` (shipped with the miner) — shape recorded in
  08 §1's dated substrate edit, nothing built. CLI parity preceded
  the UI, as A1 required.)*

**Design additions accepted with the ratification:**

- **A1 · Run journal (first-class contract).** Every run appends one
  JSONL entry: run id, trigger (timer|manual|kick), sessions scanned,
  rubric version, model, duration, per-candidate outcomes — `landed` /
  `folded(lrn-id)` / `recurrence(lrn-id)` / `dropped-rejected(lrn-id)` /
  `dropped-cap` / `held-pending-gate` / `scan-refused(rule)` — plus
  missed-window honesty when retention outran the cursor. Lives in the
  miner's cache dir (machine-local; nightly journal-only repo commits
  would be noise; G-3 runs on this machine and reads it directly).
  `self-learn mine status` renders the same journal in the terminal —
  CLI parity precedes the UI. **Amended by `U-cursorhold` (FW-73):**
  every `dropped-cap` outcome additionally carries a `cursor` field —
  `held` / `advanced-halted` / `advanced-unmatched` — and the `ok` /
  `landed-uncommitted` journal entry gains `cursors_held: <int>`, the
  count of distinct sessions this run withheld from the cursor advance.
- **A2 · Staged-autonomy ladder (the "potentially autonomous review"
  path).** L0 (now): human routes everything. L1: auto-resolve
  duplicate-folds and already-canon graduations. L2: auto-route
  high-confidence records to *reference* files (unloaded surface, cheap
  revert). L3: loaded canon (skill-md/claude-md) — human-gated longest.
  Each level activates by dated register edit, justified by measured
  per-class accept rates; therefore calibration (§4) tracks accept rate
  by kind × scope × confidence bucket × rubric version from day one.
  M-1 is untouched: the *miner* never routes at any level — the ladder
  governs the review component, not capture.

  *Amended 2026-09-13:* the L0–L3 tiered-config ladder above is the shape
  S-29 originally specified and is superseded by the steward, which decides
  every level without a config tier (S-29 as amended). This ladder's
  calibration intent — per-class accept rates justifying more autonomy —
  survives as the overseer's coverage record (`02-schema.md` §3a.1 rule 1,
  `13-hosting-and-separation.md` §3) rather than as a dated register edit
  per level. *Renamed 2026-09-13 (`S-67`):* this bullet's own "already-canon
  graduations" is now "already-covered retirements" — the rename does not
  change which records this ladder describes, only the word.
- **A3 · Rubric version stamping** on every run and journal entry, so
  accept-rate shifts are attributable to rubric edits.
- **A4 · Notification restraint.** Mined landings ride existing
  surfaces (pending count, SessionStart line, worker notification); no
  new popups. The journal is where detail lives.
- **A5 · Multi-machine posture.** Cursors and journals are cache-local
  per machine; each machine mines its own transcripts; the ledger's
  Phase-3 reconciliation is the cross-machine meeting point. No
  coordination protocol needed.

## 9. Build plan (execution notes)

Worktree milestone (`self-learn-miner` branch), pre-merge audited per
the 2026-07-15 doctrine (this change activates real background behavior
— audit BEFORE merge), then live-verified.

- **T-M1 · digest + walk + cursors** — transcript JSONL parser, Phase-1
  structural digest (fixture-tested on synthetic transcripts: user turns
  kept, tool-result bodies dropped to status+edges, error/retry
  annotations, self-learn command-span and worker/miner-header
  exclusions), per-file line cursors in cache, `--since` override.
- **T-M2 · reader invocation** — reader invocation through the seam's
  `miner-reader` surface (**no** filesystem read tools — the worker deny
  list plus `Read,Grep,Glob`; settings-file Edit rule family over the
  miner spool only; timeout; `SELF_LEARN_MINER_MODEL` default
  claude-sonnet-5) *(corrected 2026-08-19, U-docs — same defect as §2's
  Phase-2 paragraph; see `Sub-9`)*;
  prompt = mining rubric (versioned reference file) + ledger index +
  compiled canon list + digests; artifact contract: one file at a FIXED
  name — `mine-output.json` (`miner.OUTPUT_BASENAME`) — schema-validated,
  every other spool file deleted as litter *(corrected 2026-08-19,
  U-docs: the run id is a `uuid4().hex[:8]` that appears only in log
  lines and `MineResult`, never in a filename. The old text was not
  merely stale — a file actually named `mine-<runid>.json` would be
  **swept by the very sweep the same clause describes**, so following it
  produced an artifact the miner deletes.)*
- **T-M3 · reconciliation + landing** — CLI verifies every claimed
  match id/status (the model's claim is never trusted raw; a wrong claim
  demotes the candidate to `none` and is journaled); outcomes per §2
  Phase 3 + Q4 resurfacing counter; landing via the import writer path
  (`source: session`), scaled caps, pending-gate, sentinel hold, pinned
  commit `self-learn: mine <n> candidate(s) (<run-id>)`, worker kick.
- **T-M4 · scheduling + watchdog + status** — systemd user units
  (repo `systemd/`, `Persistent=true`, documented registration), verb
  autokick >24h (conftest disables), fast-status miner clause (>36h),
  `mine run`/`mine status` dispatch, run journal writer.
- **T-M5 · calibration surface** — card-decided telemetry gains the
  source dimension; `report` shows mined supply and accept rate
  (honesty label: adjudicated cards only).
- **Acceptance (user-present):** (m-a) a real overnight or forced run
  over genuine transcripts lands ≥1 sensible candidate that survives
  review; (m-b) the watchdog demonstrably fires after a >24h gap;
  (m-c) `mine status` answers "what happened last night" without
  reading code; (m-d) a planted secret in a synthetic transcript is
  refused at landing and journaled as `scan-refused`.

## 11. Episode briefs — the miner's second record-side output (amendment 2026-07-18, Y-21/U18)

*UX enhancement survey (`research/2026-07-18-ux-enhancement-survey.md`)
Q4 / shortlist item 5. User's framing: "should the agent that does the
mining also write up a longer brief that can be shown when the user
clicks into a potential lesson within a bucket." Register entry
09 §11 Y-21; build contract 10 §3 U18. This section is the miner-side
normative pin; 02 §1 owns the record-body-section + compiler-exclusion
pin, 09 §2.3 owns the Detail display obligation.*

**The gap this closes.** The miner is the **only actor in the pipeline
that ever reads the full transcript**. The worker reads the record +
target canon, not the session; the human at review reads the card; and
the transcript itself is pruned on `cleanupPeriodDays` (§0/§3), so by
review time the raw episode is usually gone. Today the miner keeps only
a one-line `why_durable` and the shortest-span evidence quote and
discards the arc — the clearest case in the system of *capture-time
context lost before decision time*. The brief captures that arc while it
still exists.

**What the miner writes.** For a candidate it is landing as a NEW
`source: session` record (Phase 4), the reader emits an optional
`episode_brief` field (§2 Phase 2 structured output) and the CLI writes
it into the record body as a `## Episode brief` section. Contract:

- **Author + timing: miner only, at land, same run.** The reader
  already spent the digest-read tokens in the one Phase-2 `claude -p`;
  the brief is **marginal output tokens in that same call** — no new
  run, no new model pass, no analyst involvement. The brief is a
  record-body section (the capture producer's native artifact), **never
  a proposal `card:` section** — cards are the analyst's artifact and
  writing miner content into one would break the producer/consumer
  boundary §1's "no card-registry change" pin preserved (the resolution
  is argued at 02 §1's episode-brief amendment).
- **Only for records the miner actually authors.** No brief on
  `source: teach` (a human-confirmed teach has the live conversation the
  CLI never saw — the human *was* the context; nothing to reconstruct)
  or `source: backlog`/`auto-memory` (the importer never held a
  transcript). A later analyst-written brief is explicitly declined for
  M1: the worker reads record + canon, not the session, so it has no
  episode to reconstruct — RD §8's story-first card `headline` already
  carries the analyst's returning-human duty for non-mined records. The
  brief exists **iff `source: session`**.
- **On a sighting-append (Phase 3 match to a pending record), the brief
  is NOT written** — an existing record's brief is not the miner's to
  overwrite, and a matched sighting produces no new record body. Only a
  net-new landing carries a brief.
- **Size + register.** 100–200 words, story form per RD §8: the
  attempt → failure → correction → resolution arc **in the domestic
  terms the human lived** — what was tried, what broke, what the fix
  was. No record ids, no destination enums, no unexpanded acronyms
  (the Y-9 plain-words register). It **retells; it does not quote** —
  **no verbatim transcript spans beyond the existing evidence-quote
  rules** (the shortest-span `quote` stays the record's only verbatim
  transcript span; teach's evidence rule and §2 Phase 1 are unchanged).
- **Cost note.** Marginal *generation* cost only on the miner side
  (output tokens in an already-paid call); zero new infrastructure.
  **Downstream, though, it is recurring input:** every later worker /
  analyst / pane run that reads a mined record now ingests the brief as
  ~1200 chars of **input tokens** each time — small but not zero, and
  the "marginal output tokens" framing covers only the miner side.
  It widens the mined record's footprint during the miner's calibration
  probation (§4), but a legible episode brief plausibly *raises* the
  mined-card accept rate — the reviewer can defend the decision — which
  is exactly the metric that decides the miner's fate (§4). Worth trying
  **within** probation, measured on the same accept-rate surface.

**Landing safety (the leak surface a reconstruction raises).** The brief
rides the Phase-4 landing exactly as every other landed field — and its
one non-negotiable build invariant is **compose-before-scan**:

- **Compose site: `_build_record` (miner.py:812–862), before
  `_scan_candidate` (miner.py:1024).** The "no new scan path" guarantee
  holds *only* if the brief bytes are already in `record.body` when the
  scan runs. The `_build_record` → `_scan_candidate` → `create_record`
  (miner.py:1046) order means the brief **must** be composed into the
  record body inside `_build_record` — **never** in `create_record`,
  which runs *after* the scan and would ship an unscanned,
  attacker-influenceable prose field. Ordering invariant (pin, tested by
  m-g): the brief the secret scan sees is byte-identical to the brief
  that lands.
- **Secret-scanned** — the per-record landing scan (M-2, refuse default,
  no bypass) covers the whole record file including the brief; a trip
  refuses the landing and is journaled `scan-refused` (acceptance m-g
  below). No new scan path — the brief is body bytes the scan already
  walks, *given the compose-before-scan invariant above*.
- **Field-length cap, refuse-not-clip** (§10-2 posture): a dedicated
  cap for the section (pin **≤1200 chars** ≈ the 200-word bound). The
  cap is **one-sided by design** — the ceiling is enforced; the 100-word
  floor is rubric guidance only (under-length is a quality nudge, not a
  safety issue, so it never refuses). Over the ceiling refuses the
  **whole candidate** (refuse-not-clip — never a truncated brief on a
  landed record), which **can lose an otherwise-valid lesson**; that
  cost is accepted deliberately under miner probation (§4), and the
  journal entry makes it observable — revisit if it fires in practice.
- **Free prose, no structured refs.** The brief is narrative prose that
  builds **no origin string** and carries **no structured session/line
  fields** — so the evidence quote's ref-gating (`_valid_ref`, which
  guards the *structured* session/line fields that assemble an origin)
  **does not apply and is not required here**. The whole-record secret
  scan plus the char cap are the brief's **complete** landing defenses.
  The reader still has **no filesystem tools** — the brief is generated
  from the in-prompt digest alone.

**No staleness machinery.** The brief describes the **past** (the origin
episode), so it cannot go stale against a later record edit the way a
proposal can (no `record_sha`, no freshness badge, no regeneration). It
is body substance like Trigger/Instruction: freely editable while the
record is `pending` (02 §2 freeze-at-routing), editable in Discuss / the
pane like any other body text and scanned by the same
`proposal validate` checkpoint (02 §2), and frozen at routing with the
rest. A human who finds it wrong or leaky edits or deletes the section —
no special path.

**No backfill.** Records that landed before this amendment have no
brief and their transcripts may already be pruned, so there is nothing
to reconstruct — **no backfill run**. An absent `## Episode brief`
renders nothing (09 §2.3): no block, no placeholder, no apology.

**Acceptance extended (user-present):** (m-e) a forced `mine run` over a
synthetic transcript with a clear failure→fix arc lands a record whose
`## Episode brief` reconstructs the arc in plain words within the word
cap, carries no verbatim transcript span beyond the evidence quote, and
survives the landing scan; (m-f) a brief that would exceed the char cap
refuses the candidate and journals it (refuse-not-clip); (m-g) a planted
secret placed **in the brief text** of a synthetic candidate is refused
at landing and journaled `scan-refused` — the test that proves the
compose-before-scan invariant (a secret reaching the record only via the
brief must still be caught, which holds iff the brief was composed in
`_build_record` before `_scan_candidate`).

## 12. Near-miss visibility + canary recall checks (amendment 2026-07-19,
FW-34/Y-24)

*Build-grade draft `drafts/miner-visibility-spec.md`, gated SOUND;
charter `forward/worker-ecology.md` §5/§6 + `forward/supply-quality.md`
§5. This section is the miner-side normative pin (mirrors §11's own
split); 09 §11 Y-24 owns the surface obligation. Invariants **M-1**
(never auto-route) and **M-3** (never load-bearing) are reaffirmed,
unchanged.*

**The gap this closes.** §8 A1's run journal already records a
per-candidate `outcome` enum + the transcript `origin`, but never the
candidate's draft content — so a near-miss (something the reader saw but
the run did not land) is unrecoverable the moment its transcript prunes
on `cleanupPeriodDays` (§0/§3). This amendment adds (a) a self-contained,
pre-scanned snippet at the sites that already drop a candidate, so a
near-miss survives pruning; (b) a human-facing `disposition` fold + a
plain-words `reason`, computed once at journal-write time (the UI never
re-derives them); (c) one promote action, riding `teach`; (d) low-
ceremony canary recall counts. The journal's shipped `outcome` vocabulary
is **unchanged** — this is additive.

### 12.1 The disposition fold

Every near-miss `outcome` is folded to exactly one of five human-facing
`disposition`s, computed once when the run's journal entry is written
(never re-derived downstream):

| `disposition` | Folds | Promotable | Snippet | Record id |
|---|---|---|---|---|
| `cap-refused` | `dropped-cap` | yes | yes | — |
| `rubric-dropped` | the new `near_misses[]` outcome (§12.2) | yes | yes | — |
| `already-canon` | `folded`, `skipped-resolved`, `recurrence`, `recurrence-already-known`, `skipped-known-origin` | no | no | yes |
| `rejected` | `dropped-rejected` | no | **never** | **never** |
| `scan-blocked` | `scan-refused`, `fold-quote-scan-refused` | no | never (rule only) | no |
| `other` | `dropped-invalid`, `dropped-land-failed`, `match-claim-invalid`, `quote-dropped-overlength` | no | no | no |

`landed`/`resurfaced`/`recurrence-from-fire` carry no disposition — they are not near-misses.

**The `rejected` double-absence** (a data pin, not merely a UI one): the
`dropped-rejected` outcome (`miner.py`'s `_reconcile_and_land`, the
rejected-status branch) no longer emits `record=record.id` — surfacing
the id would invite re-promoting a lesson the human already said no to.
Counts-only (`sightings` stays); the resurfacing counter
(`_rejected_counter_bump`) remains the *only* path a rejected class
returns.

### 12.2 The self-contained snippet + the one reader-output extension

For `cap-refused` and `rubric-dropped` only, the outcome carries
`snippet`: `{type, trigger, instruction}` (behavior) or `{type, fact,
context}` (knowledge), plus `why_durable` and — when the source dict
carries them — `scope`/`kind` (a build-time addition beyond the
draft's literal field list: the promote argv, §12.4, needs a scope to
build `teach --<scope>`, and these are cheap, short, enum-shaped strings
already covered by the same scan/cap). **No evidence quote, ever** — the
snippet's provenance is the `origin` ref alone; promote passes it as
`--session`, never `--quote`.

- **Scan before `_outcome`, at each disposition site.** Field-by-field
  `secret_scan`, reduced to a clean dict, `{scan_refused_rule: "<rule>"}`,
  or `{overlength: true}`, **before** the `_outcome(...)` call — nothing
  near-miss enters the journal unscanned. The `dropped-cap` branch used
  to fire before any scan ran at all (the leak this amendment closes).
- **Char-capped, refuse-not-clip.** `MAX_NEARMISS_SNIPPET_CHARS = 600`
  (smaller than the episode brief's 1200 — a snippet is a draft stub,
  not a story). Over the cap → `{overlength: true}`, counts only.
- **`near_misses[]`** — the one genuine Phase-2 output-schema addition:
  an optional array beside `candidates`/`fires`, `{type, trigger|fact,
  instruction|context, why_durable, session, line, confidence}`. Every
  field rides `MAX_FIELD_CHARS` (1000) refuse-not-clip (an over-length
  field drops the WHOLE near-miss, mirroring `_build_record`'s candidate
  cap), the snippet scan above, and `_valid_ref` gating on
  `session`/`line` (an invalid ref drops the whole near-miss too — never
  a guessed origin). The miner works completely without this array
  (M-3); reader containment (Read/Grep/Glob-less) is untouched.
- **Cache-local**, like the whole journal — never autosynced, never a
  tracked file. Only an explicit human promote lifts a snippet into the
  repo, through `teach`'s full scan/gate.

### 12.3 Canary recall checks

The honest low-ceremony mechanism (no synthetic transcripts, ever):

- **Plant**: `self-learn canary plant --lesson "<description>" [--expect
  "<phrase>"]` — a human act, run after genuinely stating the lesson
  in-session. Writes one entry to `miner_dir()/canaries.json`
  (cache-local, like the cursors), with a best-effort session id (no
  reliable current-session channel exists for a bare CLI invocation; a
  canary with none simply cannot score `missed`, only `caught`). Never
  writes a transcript file. Refuses (nothing written) any lesson naming
  DP-2 — the standing window-placement experiment (`supply-quality.md`
  §5, FW-4) stays the first natural canary, adjudicated by human
  judgment at review, and is never planted artificially.
- **Score**: deterministic, after `_reconcile_and_land`, every mining
  run. Reuses the WORKER's own recurrence-suspect similarity —
  `worker._tokens` + `worker.SUSPECT_JACCARD` (0.6) — rather than
  reimplementing it: no new infrastructure, drift-free. An open canary
  is `caught` when its lesson/expect token-overlaps a record this run
  landed or folded at or above the threshold; once its own source
  session has itself been mined with no match, it is `missed`.
- **Counts only**: `{planted, caught, missed}` + the open list. Never
  enters `supply_mix` or the mined-accept-rate (`report`'s §4 surface)
  — canary recall is an orthogonal probe, reported on its own line.

### 12.4 `mine status --json` additions + degradation

Per-run entries gain `near_miss_count`; each outcome dict additionally
gains `disposition`, `reason`, `promotable` (bool — CLI-emitted, one
rule: true iff `snippet` is a populated `{type,…}` dict), and `snippet`.
Top-level `canaries: {planted, caught, missed, open: [{lesson,
planted_at}]}`, absent when nothing has ever been planted. Degradation
mirrors the shipped skip+log posture: a malformed snippet renders as
enum+reason only; `canaries.json` unreadable → `{planted:0…}` + a
`log()` line, never a crash; no backfill (pre-amendment near-misses have
no snippet, `promotable: false`, nothing to reconstruct).

### 12.5 The promote surface (09 §11 Y-24 owns the UI obligation)

`POST /mine/near-miss/promote` rides `teach` — the existing human-
capture writer, full scan/cap/pending-gate discipline unchanged. The
server re-reads the snippet from a fresh `mine status --json` at
promote time (never trusts a client-posted body) and rejects a
non-promotable index outright. Consent posture: the tap *is* the
confirmation (§0's legitimacy model) — one tap lands one real pending
record in the correct bucket, which the worker analyzes before any
human sees a card. There is no near-miss state left to manage once
promoted; every other row either ages out with the rolling journal or
stays a count.

**Non-goals (unchanged from the charter):** no dismiss/snooze/note/seen
on near-misses; no near-miss bucket, cards, or review cadence; no
multi-run near-miss list; no auto-promotion (M-1); no re-litigating
rejected records; canaries never synthesize transcript content, never
enter supply metrics, never auto-plant, and never touch DP-2.

## 13. Session engine foundations (R1b, 2026-10-19)

These read-only modules are built for the session engine; this section does
not enable that engine or change the digest engine. The engine builds one
`mining.tools.build_toolset(session_file, subagents, judged_end, home,
sent=…, provider=…)` per call. Its `McpToolset("miner", …)` contains exactly
`open_stretch`, `find_similar_lessons`, and `search_subagent`. Names,
descriptions and input schemas are constants, pinned together by SHA-256.
Handlers are async; blocking file, SQLite and embedding operations execute
in worker threads. Each connection is opened and closed in its owning
thread. Bad arguments return a one-line schema reason, or the valid turn/page
range. Integer fields reject floats (including `1.0`) and booleans. Every
returned text is redacted, including errors, and raw text is redacted before
shortening. Unexpected dispatcher failures are logged by tool and exception
class without echoing the exception's potentially sensitive message.

### 13.1 Tools and provenance

- `open_stretch(after_turn, page=1)` reads only lines 1 through the judged
  end. Turn numbering comes from `contract.typed_turn_lines(entries, sent)`;
  0 precedes the first person-typed turn. Pages contain at most 24,000
  characters, retain physical line numbers and include a continuation or
  end footer. Tool inputs, result edges, assistant messages and subagent
  summaries are bounded. Missing results say pending, never success.
  A result appears only inside its TOOL line; there is no duplicate result
  row. Token/usage-reminder attachments and hook-success rows are omitted, except hook output from `SessionStart` and `UserPromptSubmit`, which injects context the agent read (a reminder in front of it matters to a rule check) and is shown as `RELAY`.
  One-line results are shown once, without a repeated last edge.
- `find_similar_lessons(draft)` accepts 20–2,000 characters and returns up
  to five records, at most 1,800 characters each and 10,000 overall, with
  status, scope/bucket, placement, loaded sections and the first evidence
  quote (at most 300 characters). It follows `superseded_by`, deduplicates
  live successors and skips cycles, missing successors, retirements and
  superseded records without a successor.
  There is no production mask. The index is refreshed by the engine once
  per run, not by a handler.
- `search_subagent(subagent, query)` reaches only the supplied session's
  subagent files. An unknown id returns the allowed ids. A quoted query
  is a case-insensitive substring; otherwise it is FTS5 OR with Porter
  stemming. The brief and final report are at most 1,500 characters each,
  with up to 20 matching excerpts and 12,000 characters overall. A log's
  FTS image is built once per call and reused without sharing live SQLite
  connections. Launch links use `toolUseResult.agentId` and tool-result
  ids; an exact first-user-text/input.prompt match is the fallback.

Main-session rows use `refs.role_of(entry, sent=…)`: `YOU` is the person,
`AGENT` the assistant, `AGENT-WRITTEN` a provenance-detected typed turn
another agent wrote, `RELAY` a relayed row, `TOOL_RESULT` a result, and
`SUBAGENT` a sidechain row. Every row read from a subagent file instead uses
`refs.role_of(entry, in_subagent_file=True, sent=…)`, so its role is always
`SUBAGENT`, including when the row omits `isSidechain`. Agent-written and
relayed text never becomes a typed turn.

All content-built output fields replace line breaks with the visible ` ⏎ `
marker before shortening. Result edges retain their ` ⋯ ` separator.
Only the tool's templates create physical output rows; embedded text cannot
forge an `L<n> YOU:` row. The method instructs the model to quote within a
displayed span, stopping before a line-break marker, which is display notation
and cannot match the raw transcript verbatim.

`index.textquery.nearest_text(index, text, limit=5, exclude_ids=…,
provider=…)` returns `HybridResult`. FTS5 and document-form embeddings
are fused with RRF. Exclusions apply before rank cuts (the API remains
useful independently; the miner passes no mask). A missing provider,
model mismatch, incomplete vectors, failure or 20-second embedding timeout
produces lexical-only results with a reason. Timeout bounds the caller's
wait; Python cannot cancel an already running synchronous provider request.
For Gemini look-alike requests, a private copy of its interactive profile
uses one attempt, no pacing or retries, and at most a five-second transport
timeout, while retaining document templates and model identity. The shared
provider's bulk policy is unchanged. This avoids the bulk policy's minutes
of retries after a caller has timed out. The waiting daemon owns no SQLite
connection or ledger state; arbitrary injected providers still own their
transport cancellation behavior. Provider failures preserve their exception class
across the thread boundary. Fallback notes name that class (including
`TimeoutError`); provider message text is withheld because it can contain
credentials or private input, even when it matches no secret-scan pattern.

### 13.2 Rule-situation flags and method

`mining.tools.stretches(entries, sent)` creates work-only documents from
assistant text, tool names/string inputs and result edges, excluding the
person's turns, agent-written briefs and relays. `mining.flags.flag_rules`
compares those documents with routed records: Trigger for behavior,
Fact plus Context for knowledge. User scope always qualifies; project
scope requires the cwd to be inside the registered host when resolvable;
unknown project buckets remain eligible. Skill scope requires a matching
Skill call or `skills/<name>/` in the session. Superseded rules are excluded.

In-memory FTS5 scores are normalized against the query's own score. If the
lesson index is hybrid, non-empty work documents are embedded in one batch and
compared with the rules' stored vectors, then ranks are fused with RRF.
No provider or an embedding failure degrades to lexical-only and is
reported in `FlagResult.mode/note`. A flag needs normalized lexical score
at least 0.30 or cosine at least 0.75. At most two stretches per rule and
eight flags per session survive, best first. These bars are provisional.
Empty or whitespace-only stretches are excluded before embedding and ranking;
remaining stretches retain their original turn and line positions. An all-empty
set makes no embedding call and yields no flags, without degrading index mode.

`miner-method.md` starts with `<!-- method-version: 1 -->` and is byte-pinned
in tests. It carries the four lesson shapes, exclusions, composition,
pointer discipline, look-alike reconciliation, suspicion-only rule checks,
subagent causes and output instructions. Only the person's typed turns
are their words. Trigger, Instruction and Fact are each one line;
`verification.how` maps to `verified_how`, `incident_cost.text` to
`incident_cost`, and `context` to `## Context`. The integration unit inlines
the shared lesson-writing passage and output schema after this method.

### 13.3 The session engine in `miner.run` (R2, 2026-10-19)

`miner.engine` (`digest` | `session`, default `digest`, tier C, no environment
variable, and no process override: `SELF_LEARN_OVERRIDE_MINER_ENGINE` is
ignored, named by `doctor settings` as a var that does nothing, and
`settings.override` refuses the entry) chooses the engine of a run. The session engine replaces exactly the
digest step of `_run_locked`: the run lock, reconcile healing, cursor seeding,
the self-session and scheduled-job sweeps, `walk()`, the run's one sweep of
sends (`provenance.sweep`), the pending gate, the ledger lock and the landing
commit are shared, so a rollback is flipping the setting back. `serve.py` is
unchanged. `mining/engine.py` plans, calls and checks and writes only the run
folder; the one seam call (`invocation.text_session`) and every ledger write
are in `miner.py`.

**Plan.** Each slice is cut at `miner.halt_point(s).end` (relative to the
slice; `spine.judged_range` adds `s.start_line`). A session is skipped as
`halted`, `no-typed-turns`, `no-marker` or `nothing-new` (its cursor
advances), or planned: flags from `flags.flag_rules` over the stretches the
judged lines reach, mapped to spine flags (`engine.spine_flags`: the record's
scope, the stretch, `lexical+meaning` when a cosine was computed, the rule's
Trigger and Instruction or Fact and Context), then the spine and the three
tools. The tools get the spine's own subagent logs (`Spine.subagents`) and its
`end_ts`, so `search_subagent` and `open_stretch` never show a log or a line
the checker would refuse. The lesson index is refreshed once per run
(`steward_inputs.refresh_index`); without it there are no flags (flag mode
`unavailable`). At most `miner.max_sessions_per_run` (30) sessions are called
(a skipped session uses no place); the rest, and a second file with a session
id already planned, wait behind their cursors (`deferred`). The judged-uuid
store is read once, before anything is judged; the moments
(`Spine.moment_uuids`) of every session already planned for a call in this
run are added to the judged set of the plans after it (they are *claimed*),
so a fork's copies of its parent's moments read as already mined (a fork
with nothing else new is `nothing-new`) and its check drops a copied moment
as `already-judged`. A claim only stops duplicate model output within the
run; a claimed moment reaches the store only through its claimer's own save
(**Save**).

A session that keeps failing does not starve the others. The cache file
`<cache>/miner/session-failures.json` counts, per transcript file, the runs
in a row its session failed at one cursor: a failed call, bad output or a
checker error, and nothing else (a landing never counts: a saved answer's
items wait and land later, fix round 4). Sessions that have failed are
planned after those that have not. A moved cursor restarts the count and a
saved answer clears it. A run-wide failure is no session's: a run where no
call succeeded (logged out, the service down), or where the ledger lock was
not taken for its waiting answers, counts nothing, and neither does a call
the runaway guard never started. There is no give-up: a failing session is
always judged again when its turn comes (fix round 2 withdrew the round-1
give-up rule).

**Call.** The shared instructions (the method, the lesson-writing passage
between its markers, the output schema) are written once per run and passed
as `append_system_prompt_file` with `exclude_dynamic_sections`. Call `k` runs
on `miner-session` in `<cache>/miner/session-stage`, with the reader's
timeout, `sidecar_key=<run_id>-<k>`, `skip_orphan_sweep=(k != 0)`, the reader's
disallowed tools, auto-memory off and `transcript_group=<run_id>`. The first
call runs alone; the rest run `miner.parallel` (4, at most 8) at once. A
`transient` failure is retried once (the retry never sweeps). No call starts
once `spent + in_flight × 0.60 >= miner.max_run_usd` (8.0; a call that reports
no cost counts as 0.60); a session not started keeps its cursor.

**Check.** `check.check_output` with the run's sends, the plan's judged set and
the ledger's record ids. Any exception the check raises makes that one
session `failed` (`error: checker-error`); a failed call, or a call that
raised, makes it `failed` (`error: call`); neither touches another session.

The final message must be one JSON object, bare or inside exactly one
triple-backtick fence (optionally labelled `json`) that ends the message.
Prose before that fence is tolerated; whitespace after it is allowed.
The closing backticks may follow the object directly or start their own line.
Multiple fences, trailing prose, prose without a fence, and prose followed
by an unfenced object are refused: without a fence there is no explicit
boundary separating commentary from the answer. The extracted object still
passes the full output contract and evidence checks. `counts.prose_before_json`
in `run.json` counts contract-valid answers accepted through this tolerance
(once per answer); bare objects and fence-only answers count zero. The run
contract validates the optional count as a nonnegative integer, never a bool.

**Save** (fix round 4; the orchestrator laid out options and the user typed
"go with option 1", replacing round 3's families). When a session's answer
passes the checker, it is written as a *waiting answer* before anything of it
lands (`mining.waiting`): one JSON file per session answer in
`<cache>/miner/pending/`, never inside a run folder, written whole and
atomically (temp file, fsync, rename), mode 0600. It holds the checked output
(`miner-output/1`, verbatim), the session id, the transcript path, the run
id, the method version, the halt flag, the session's cwd, the cursor entry
the session takes, what the judged-uuid store learns from it, and one state
per item (each lesson, sighting and rule check, in that order: `waiting`,
`landed`, or `dropped` on purpose, with its failure count and, once it has
them, its outcome, reason and last error). Once the file is on disk, the
judged-uuid store learns the spine's moments except those its spine showed
as already judged or claimed by another session this run, plus the uuids the
checked output cites, a moment another session of the run claimed excepted
(it reaches the store only through its claimer's own save); then the
session's cursor advances (the halt rule still applies: a halted session
keeps its halt). The model is never asked about those lines again, whatever
happens to the landing. A failed call or check saves, moves and teaches
nothing; that session is called again later. A run that stopped between a
save and the store or cursor write applies both again from the waiting
answer: the cursor, forward only, before the next run's walk; the store
(a row keeps its first date) before the next run's snapshot. A waiting answer
stays on disk until what it teaches the store is durably written (fix round
5): if the store write fails, at the save or on a later run's re-learning, the
file is kept even when every item in it has landed. Every night run re-learns
from every waiting file it keeps, before its snapshot, and the snapshot
includes each kept file's `learn` set whether or not that write succeeded;
a file is removed only once its items are all done and its learning has
succeeded (`judged_uuids.relearn_failed` counts the files whose re-learning
failed). A preview saves nothing and never loads the waiting answers.

**Land** (`_drain_waiting`, inside `intents.ledger_write`). Every run that is
not a preview lands the waiting answers, oldest first (earlier runs' answers,
then this run's), even when it called no one and when every call failed. A
run the flood gate held lands nothing: the gate keeps new pending records
out of a review queue that is already full, so the waiting answers stay as
they are and land on the first run after it opens. The gate is checked in the
one place every landing goes through (fix round 5), so it holds on a run that
called no one, on a run whose every session was skipped, and on the failure
path a run takes when it stops early (the method file does not read); while
it is closed, `pending/` stays byte-identical.

*Intent before write* (fix round 5). Items land one at a time. Before an
item's write, the attempt's decision is recorded on the item in one atomic
rewrite of its file: the item's state becomes `writing`, and its `intent`
names the output (`lesson`, `resurface`, `fold`, `recurrence-suspect` or
`fire`), the target record id (none for a new lesson) and the origin. After
the write, the item stays `writing` until the run's landing commit has
succeeded; only then is it marked `landed`. A replayed `writing` item
finishes the output it recorded and never decides again from the target's
current status or successor: if that output already exists (a lesson by
its known origin; a resurfaced lesson by its known origin held by the
rejected record's own resurfaced copy; a fold only when every one of its
evidence moments is in the recorded target's own evidence, so a partial
fold folds what is missing; a fire or recurrence-suspect by `(kind, record,
origin)`, or by `(kind, record, moment uuid)`, against the spooled and the
tracked events), the item is marked
`landed` with outcome `already-written`; if it does not, the same output is
written; if the recorded target is gone, the item is dropped
(`dropped-invalid`, with the reason). A replayed new lesson or resurface
counts against this run's lesson cap like any other: over it, the item
stays `writing` with outcome `waiting-cap` and lands on a later run, the
model never asked again; output that already exists is acknowledged
without a cap place (fix round 6). The replay of a resurface also marks
the rejected record's counter as landed (`_rejected_mark_landed`, an atomic
write), so one rejected lesson resurfaces once. A sighting decided again
whose origin a record already holds marks the rejected record only when
that record is the rejected record's own resurfaced copy; another record at
that moment, a lesson from the same answer, leaves the counter as it is
(fix round 6). The copy is known by what it says it is, never by its text
(fix round 7): every evidence entry of a resurfaced copy carries
`resurfaces: <rejected id>`, and the copy is a record holding that origin
whose evidence has an entry naming the rejected record; the marked entry
need not be the one at that origin, since a later fold into the copy adds
entries without the marker (R3, 2026-10-24). Evidence is append-only,
so an edit of either record's text, or a section the copy does not carry,
never hides it, and a lesson that only uses the same words is never taken
for it.

*One moment, one event* (fix round 7). A fire or recurrence-suspect carries
its moment's uuid (`moment`) when the moment has one. A parent and its fork
share a moment's uuid, not its origin, so a replayed event that finds an
event for the same record at the same moment uuid, spooled or tracked, is
already written: a parent whose append failed once while its fork wrote the
moment's event in the same run writes no second event. Items still
`waiting` are checked against the ledger as it is now (*Stale items*,
below).

*Durable before marked* (fix round 5). An output is durable before its item
is marked. A spooled fire or recurrence-suspect is fsynced, and its folder
too, before `_spool_output` returns, and a replay that finds its event
already spooled fsyncs the spool files and the folder before the mark (the
first append's own fsync may have failed); a replay that finds its event
already flushed into a tracked telemetry file that is still uncommitted (the
flush's commit failed) has the landing commit commit that file too, and
waits for it to be clean before the mark (fix round 7); records and folds
are written whole with fsync and the folder fsynced, and are committed to
git by the run's landing commit before any item is marked. A terminal mark (`landed`
or `dropped`), and so a file's removal, needs a landing commit that
succeeded (fix round 6): when `_commit_landing` reports the landing
uncommitted, no item of the run gets a terminal mark; and an item whose
record file, written now or found by a replay, still has uncommitted
changes (the run's reconcile failed) keeps its state too. The next run's
reconcile commits the files and its replay marks the items. The digest
engine is unchanged. A file whose items have all landed or been dropped, and whose learning
has succeeded (**Save**), is removed. When the lock is not taken, nothing lands
and every waiting answer stays as it is. `waiting.drained` in `run.json` is
set the moment the ledger lock is acquired, before the landing starts: a run
that took the lock and then failed still counts its failed sessions (fix
round 5).

*Files that do not read* (fix round 5). A waiting file must parse, declare
`miner-waiting/1`, carry a `checked` part that passes
`validate_checked_output`, its `cursor` and its `learn`, and hold exactly one
item per checked lesson, sighting and rule check, with no gap and no
duplicate. Every field is checked as the code that consumes it reads it,
before cursor settlement, learning or landing (fix round 6): `transcript` a
string; `cursor.lines` and `cursor.size` non-negative ints and
`cursor.halt` a bool; indexes and counts ints, never bools; and a `writing`
item's intent an output its kind can record (a lesson: `lesson`; a sighting:
`resurface`, `fold` or `recurrence-suspect`; a rule check: `fire`), a
non-empty target record id for every output but a lesson (which has
none), and an origin of the transcript shape. A file that fails any of these stays in place, byte-identical;
nothing of it lands, and its cursor and store rows are not applied from it.
It is named in the run's journal row and in `run.json`
(`waiting.unreadable`), the run gives it a `waiting-unreadable` outcome
saying its output waits on a manual repair, and `self-learn doctor miner`
shows it as a WARN. *Manual repair* means a person reads the file, fixes it
to the contract (or moves it out of `pending/` once its output is otherwise
in the ledger); the miner never deletes or rewrites it. A later change to
the checked-output contract (`miner-output/1`) or to `miner-waiting/1` must
keep reading waiting files written under the earlier version, or migrate
them in place, so an upgrade never turns saved answers into unreadable
ones.

A lesson becomes a pending record (`source: session`): its loaded text and
`## Context`, its steps as `## Episode brief` lines `L<line> (<role>, T<turn>):
<what>` (a step in a subagent's log names it, `agent-<id> L<line>`),
`verified: true` with `verified_how`, `incident_cost`, `generality`. Its
evidence items are `{ref, quote?, session, ts: ref.entry_ts, origin}` (a
resurfaced copy's also `resurfaces: <rejected id>`, fix round 7), then the
verification's and the incident cost's pointers (`why: verification`, `why:
incident-cost`); a withheld quote (`check.quote_withheld`) is stored without
`quote`. The origin of a subagent line is
`transcript:<session>/subagents/agent-<id>.jsonl#L<n>`. The known-origin skip
(the first main-session evidence item's origin), the secret scan (body,
quotes, `verified_how`, `incident_cost`, `why_durable`), skill-scope checks
and `capture_host_path` for project scope follow the digest engine's landing.
The lesson cap (`cap_for` over the sessions called) counts every lesson the
run lands, drained ones included; a lesson over it stays waiting
(`waiting-cap`, in a halted session too) and lands first on a later run. A
`hosts.yaml` that does not load leaves the lesson waiting, as a failed write
does. A lesson whose evidence moments were all cited by a lesson landed
earlier in the run is `skipped-duplicate-moment`. The brief keeps whole step
lines up to 1,200 characters (the digest engine's `MAX_EPISODE_BRIEF_CHARS`)
and then says how many steps were left out. A sighting follows
`superseded_by` to the live record: pending folds (evidence appended,
sightings +1) unless the record's own evidence already holds that moment or
origin (another record's evidence, or a new lesson's origin, never
suppresses it), routed spools a `recurrence-suspect` (basis `miner-match`),
rejected bumps the resurface counter and, at three, lands the rejected
lesson's own text again as a new pending record, anything else is
`skipped-resolved`. A rule check spools a `fire` `{record, origin, outcome,
action?, moment?}` against a routed record only, once per `(record,
origin)`; a recurrence-suspect is `{record, origin, basis, moment?}`
(`moment`: the moment's uuid, fix round 7). Fires
and recurrence-suspects are the miner's output, not usage telemetry: a spool
that fails raises. Within one run a sighting or rule check of one record at
one moment (a fork and its parent) lands once (`skipped-duplicate-moment`).
Each check drop becomes a `dropped-check` outcome at the answer's save. A run
that only folds commits too (`_commit_landing(..., folds_alone=True)`; the
digest engine's rule is unchanged).

*Stale items.* Each item is checked against the ledger as it is when it
lands, not as it was when it was saved. An item that can no longer land is
dropped on purpose, with an outcome and a reason: a sighting whose record is
gone (`dropped-invalid`) or is no longer pending, routed or rejected
(`skipped-resolved`, naming the status); a rule check whose record is gone or
no longer routed (`fire-skipped`); a lesson whose origin another record now
holds (`skipped-known-origin`). A superseded record is followed to its live
successor. An outcome of an item saved by an earlier run carries
`waited_from` (that run's id).

*Stuck items.* A write that fails (a record, a fold, a spool) leaves its item
waiting, counts one failure for it (`land-failed`, with the error), and the
run goes on with the next item. An item whose write failed on 3 runs
(`mining.waiting.STUCK_AFTER`) is *stuck*: `run.json` lists it and
`self-learn doctor miner` shows it as a WARN (with every waiting-answer file
that does not read). It keeps retrying every run; nothing drops it. Only the
session engine lands waiting answers: when `miner.engine` is `digest` (a
rollback) and any wait, `doctor miner` shows a WARN with their count saying
they land only when the session engine runs; the digest engine never drains
them.

**After.** The run flushes the spool whenever it landed waiting answers or
the spool holds a fire or recurrence-suspect. A run is `failed` when it
called sessions and saved none of their answers. A run that found a waiting
file that does not read writes `run.json` and journals it even when it
called no one. The journal row keeps every
digest-engine key and adds `engine: "session"`, `method_version`,
`sessions_called`, `sessions_failed`, `sessions_saved`, `not_run`, `drops`
by reason and `waiting` (the counts below, stuck items counted);
`cursors_held` counts the called sessions whose answer was not saved. A run
that called no one and found no waiting answer journals `idle` as before; a
flood-gate run journals `held-gate`, with its `waiting` counts. `run.json` is
written after the landing, by every run that called a session or found a
waiting answer: each called session's row says whether its answer was
`saved`; a session the flood gate held is `not-run` with reason
`pending-gate`; `landed` counts what this run landed (lessons, folds,
recurrences, fires), whichever run's answer it came from, apart from
`totals`, which counts what this run's checks kept; and `waiting` holds the
waiting answers found from earlier runs (`found`), the items landed from
earlier runs' answers (`landed_earlier`) and from this run's
(`landed_this_run`), the items still waiting after the landing
(`still_waiting`), the stuck items (`stuck`: session, kind, origin, failures,
last error), the waiting files that do not read (`unreadable`: file names),
and whether the ledger lock was acquired for the landing (`drained`). The run folder
`<cache>/miner/runs/<run_id>/` (mode 0600: `run.json`,
`shared-instructions.md`, `plans/`, `raw/`, `out/`, `calls/`) keeps the
newest 30; waiting answers are outside it and outlive that prune. The seam's
transcript copies of the surface (`<cache>/sessions/miner-session/<run_id>/`),
which the seam never prunes, are kept to 30 groups the same way. Judged-uuid
stores moved aside as damaged are kept to the newest 3.

**CLI.** `self-learn mine run --engine digest|session` overrides the setting
for one run; `--engine session` is refused without `--preview` (`EXIT_USAGE`),
so only the user's flip of `miner.engine` lands session-engine output.
`--preview` (session engine only) calls and checks, writes the run folder and
prints counts (sessions by filter reason, calls, drops by reason, spine token
estimates, cost) and never transcript text; it does not reconcile, seed,
sweep, save or land an answer, read or drain `pending/` (it leaves it
byte-identical), advance a cursor, write or prune the judged-uuid store,
journal, or touch `miner.last-run`/`miner.last-attempt`. It changes nothing in the
cache outside its own run folder: it reads copies of the judged-uuid store
and the lesson index made inside that folder (a hot journal is rolled back
in the copy; the index refresh writes the copy) and removes them when done,
prunes no run folder and no transcript copy, sweeps no orphans, stages its
calls in the folder, logs to the folder's own `miner.log`, and opens the run
lock without truncating it. What it may still write outside: the lock file
when it did not exist, and the seam's own copies and logs of its calls. `--session ID` (repeatable,
preview only) judges those sessions' whole files (the larger file when two
folders hold one id; a listed `miner.skip_sessions` id is not read).
