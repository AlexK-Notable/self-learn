# 11 — The life of a lesson after routing: telemetry, lifecycle, and the facts layer

**Status: PROPOSED (drafted 2026-07-14 from a user-directed design session;
direction user-ratified in conversation, this document is the durable
record; builds land per §7).** Extends 01/02/08; reopens no settled
register decision (§8 lists every touch-point so a reviewer can verify
that claim). Design authority for everything it covers once ratified.

## 0. Origin

Three findings from the first days of live M1 operation converge here:

1. **E-3 revision (2026-07-14):** the first review session passed on
   throughput and failed on comprehension — remedied for *presentation*
   by the decision-support contract (card registry). This document is
   the same correction applied to *epistemics*: the system recorded
   decisions richly and outcomes not at all.
2. **The follow-up gap:** routing the chezmoi `chezmoi cd` lesson
   surfaced that "resolved" conflates "coverage landed" with "nothing
   left to do" — the planned hook upgrade had nowhere durable to live
   (a resolution-note sentence is the dead-letter pattern E-2 warned
   about).
3. **User direction:** a routed lesson is a *claim*, not a fact-in-
   perpetuity; the system needs hard facts — certainty, iteration
   counts, next steps — about what it routes. And (second directive)
   the design must stay multi-machine-safe *by construction*, not by
   merge-conflict handling.

Core principle: **certainty is measured, not declared.** No confidence
scores anyone fills in; only events that happened, appended by code,
aggregated on demand.

## 1. The three silences (what we don't capture today)

Walking a lesson's real lifecycle — mistake happens → maybe captured →
triaged → compiled → loaded → occasionally *fires* → helps or doesn't →
eventually decays — the current system records the middle (capture
through compile) and discards both ends:

- **The denominator.** We know what was taught, never what *should*
  have been. Declined S-15 offers evaporate; capture rate is
  unmeasurable.
- **The silence after routing.** A rule that silently works and a rule
  that never once mattered both look like "no recurrences" — while both
  pay attention-tax on every load. Success and irrelevance are
  indistinguishable; dead weight accumulates.
- **Capture-time context.** What the incident cost, whether the lesson
  is an environment quirk or general practice (the strongest known
  predictor of behavioral value — six dead fixture candidates), and
  what environment versions it depends on. Cheap to ask while the wound
  is fresh; unreconstructable later.

## 2. Lifecycle after routing

### 2.1 Follow-ups (known-partial at routing time)

Optional structured field on the routing block, written by the
resolution verbs (`route --follow-up "<action>" --unblocks-on "<gate>"`
or equivalent):

```yaml
routing:
  destination: skill-md
  follow_up:
    action: upgrade-to-hook
    unblocks_on: M3
    note: "advisory text is the weak form; deterministic guard is the strong form"
```

- The record's status stays terminal — the *lesson* is resolved; the
  follow-up is a planned upgrade, not an open lesson. **No new
  lifecycle status exists or is wanted**: an "in-progress" state would
  force every surface to learn a new state and would clutter review
  with non-decisions.
- `status` output gains one line ("N open follow-ups"); `report` lists
  them. They never generate review cards.
- Each milestone's build plan gains a pinned first step: **drain the
  follow-up list** (M3's already-designed advisory→hook upgrade is a
  supersede + recompile; the follow-up is only the reminder that fires
  when it becomes actionable).
- First entry: lrn-98d42215 (chezmoi cd), backfilled from its
  resolution note when the field lands.

### 2.2 Recurrences (discovered-partial after routing)

A new capture that matches an **already-routed** lesson is a
*recurrence* — evidence the rule is absent, weak, or only partial.

- **Detection** is machine work (M2 worker: the same similarity
  machinery that clusters pending duplicates, pointed at resolved
  records; plus origin/id matching). A detection is a **suspect**, and
  suspects live in the observation plane (§4) — never written to the
  record by the machine.
- **Confirmation** is human work: a routed record with suspects
  surfaces in review as a **"not holding" card** — a distinct card
  kind: *"Routed <date>. Sighted N times since. Revise the wording,
  escalate to a stronger surface, or supersede?"* Confirming promotes
  the suspect into the record's frontmatter (`recurrences:` list,
  append-only, dated, with the telemetry reference); the review
  session's sentinel-held flow serializes the write.
- Resolution of a not-holding card is one of: **revise** (supersede
  with better wording), **escalate** (supersede toward a stronger
  surface — reference→skill-md, advisory→hook), **tolerate** (append
  the recurrence, note why the rule stays as-is), or **retire**
  (supersede with nothing — the lesson was wrong).
- `last_confirmed:` (date) is the flip side: any human-confirmed
  observation that the rule held. Age-since-confirmation, not
  age-since-capture, is the staleness metric.

### 2.3 The unripe case is already solved

A lesson that was never verified (tree-lamp flare class) is **defer**,
unchanged: it *should* come back as a card. Follow-up = done-but-
upgradeable; recurrence = done-but-not-holding; defer = not-done. Three
moments, three mechanisms, no limbo status.

### 2.4 Contradiction edges

`links.contradicts: [<lrn-id or canon anchor>]` — first-class,
machine-checkable. Live precedent: the pyscript log.info record
contradicting curated GOTCHAS.md's log-marker advice was caught only by
analyst judgment; an edge lets `report` and the worker flag tension
mechanically. Written at triage (analyst proposes, human confirms via
the card) or at any later sighting.

## 3. Adjudication-plane schema additions (record frontmatter)

All human-owned, verb-written, low-volume. New optional fields:

```yaml
verified: true                    # capture-time grounding grade
verified_how: "repro'd twice on this host"   # optional one-liner
incident_cost: "an evening"       # free short phrase, captured fresh;
                                  #   report buckets heuristically
generality: environment-specific  # environment-specific | general-practice | uncertain
env:                              # versions the lesson is ABOUT (best-effort
  swaync: "0.10.2"                #   auto-stamp + user-suppliable; powers
  model: claude-fable-5           #   staleness sweeps)
routing:
  follow_up: {action: …, unblocks_on: …, note: …}
recurrences:                      # HUMAN-CONFIRMED only (suspects live in
  - {ts: …, origin: …, ref: …}    #   telemetry until promoted, §2.2)
last_confirmed: 2026-08-02
links:
  contradicts: [lrn-889241d9]
```

Compatibility pins: every field optional (all existing records stay
valid); substance-freeze (S-8/S-12) untouched — these are metadata,
same mutability class as `superseded_by`; only verbs write them.
Capture-time fields ride `teach` as **optional-but-offered** — two tiny
prompts (cost, generality), never a form; `verified` defaults from
evidence presence; `env` auto-stamps. **Capture stays ambient or every
downstream table starves (E-3).**

## 4. Observation plane (telemetry)

Append-only JSONL under `.self-learn/telemetry/` (root bucket;
committed — observations from every machine matter), **one file per
month per actor**: `2026-07.<machine>.jsonl` (team scale:
`<machine>.<user>`). Single-writer by construction; same-machine
concurrent sessions append single-line events under flock.

Event envelope:

```json
{"v":1,"ts":"2026-07-14T09:12:00Z","actor":{"machine":"komi-desktop","user":"komi"},
 "session":"<id>","kind":"<kind>","record":"lrn-…","payload":{}}
```

Event kinds (v1 closed set; extending = version bump):

| kind | emitted by | payload |
|---|---|---|
| `offer-made` / `offer-declined` | the S-15 offer flow | decline reason (optional free text) |
| `capture` | teach/import | source, bucket |
| `card-shown` / `card-decided` | review surfaces | recommendation, decision, overridden: bool, dest-delta |
| `fire` | transcript miner (M2) | source transcript, anchor (id cite or phrase match), confidence |
| `recurrence-suspect` | worker matching (M2) | matched record, origin, similarity basis |
| `staleness-flag` | env sweep | component, from-version, to-version |
| `surface-budget` | compilers | target, words, cap, overflow: bool |

Disciplines: events reference ids/origins/versions, **never lesson body
text or quotes** (keeps the secret-scan surface where it already is);
transcript mining runs locally, its outputs are references into local
transcripts, and mined `fire` events carry anchors, not excerpts;
telemetry is truth (adjudication inputs) but *cheap* truth — losing a
month of it degrades analytics, never the ledger.

## 5. Derived plane (index + report)

Unchanged from the ratified-in-conversation design, now with richer
feedstock: **disposable SQLite** at
`~/.cache/claude-skills/self-learn/index.db`; never committed; stores
the (git HEAD, telemetry high-water marks, schema_version) it was built
from and any reader rebuilds on mismatch; schema changes = version bump
+ rebuild, never migrations. Ingests: record files, git history
(`transitions` table — the replayed lifecycle timeline), telemetry
events, and (M2) transcript-mine results. Tables: `records`,
`transitions`, `events`, `fires`, `offers`, `edges`
(supersedes/contradicts/cluster), `surfaces`, plus **FTS5** over
trigger/instruction/fact text ("have we learned anything about X?" —
which also serves the analyst's already-canon checks and the worker's
recurrence matching).

`self-learn report` builds/refreshes the index, then answers at
minimum: routed per bucket · supersede rate (being-wrong rate) ·
recurrence-flagged rules · open follow-ups · iteration depth
(supersede-chain length) · capture rate (offers made/accepted/declined)
· loads-vs-fires per lesson (dead-weight list) · ROI proxy (sum of
incident_cost buckets on fired lessons) · analyst calibration (override
rate over time) · staleness queue (env moved, last_confirmed old) ·
contradiction queue · deferred aging. Output human-readable + `--json`
snapshot (a snapshot, never truth).

## 6. Multi-machine posture (standing design principles)

Every future piece of this system is audited against these five, the
way §2.2's promotion path and §4's file scoping already were:

1. **Solve concurrency in the namespace, not the merge.** Every file
   has exactly one writer by construction (create-only record files;
   actor-scoped telemetry; one human per decision). CRDT-shaped
   convergence from filesystem + git discipline, no CRDT machinery.
2. **Two planes, one-way flow.** Machines write only the observation
   plane; record files change only through human-serialized verbs;
   promotion (suspect → confirmed) is always a human action inside a
   sentinel-held session.
3. **Derived artifacts are regenerated, never merged.** The index
   rebuilds; managed-section merge conflicts are in principle
   resolvable by recompiling from the union of records — a
   `recompile`-on-conflict handler is DESIGNED-NOT-BUILT (the
   rebase-halt degradation stands at current scale).
4. **Causal order from git ancestry, not wall clocks.** "Recurrence
   after routing" = the event's commit descends from the routing
   commit. Cross-machine event order is partial; report says so.
5. **Same-machine concurrency is the common case.** Multiple concurrent
   sessions per machine are normal; append paths use single-line writes
   + flock. The one irreducible conflict — two humans adjudicating the
   same record — is a coordination problem answered by visibility
   (status strip / claim events), not merging.

## 7. Sequencing

- **Now (M1-era, small):** schema fields (§3) + validator; follow-up
  flag on resolution verbs + `status` line; telemetry append library +
  offer-ledger and card-decided events; `report` v1 (may walk files
  directly; index optional at this scale); backfill lrn-98d42215's
  follow-up.
- **M2 riders (worker-adjacent):** fire detection (transcript miner as
  a worker pass); recurrence-suspect matching; not-holding cards in
  review; index as report's engine + FTS; analyst calibration from
  card-decided events.
- **Later:** recompile-on-conflict handler for managed sections;
  actor-scoping widening for team scale; staleness sweeps wired to
  package-manager logs.

## 8. Register touch-points (verify-no-reopen list)

- **S-8/S-12 substance freeze:** untouched — every new record field is
  metadata in the existing `superseded_by` mutability class; §2.2
  promotion is verb-written under the sentinel.
- **S-13 prune / S-15 offers:** S-15 gains event emission only (offer
  ledger); offer *behavior* unchanged.
- **02 §1 proposals:** contradicts-edge proposing rides the existing
  card flow; no proposal schema change beyond what the card contract
  already added.
- **E-2 (dead queues) / E-3 (honeymoon):** §2.1 exists *because of*
  E-2; §3's ambient-capture constraint restates E-3.
- **P2-4 (single eligibility predicate), P2-7/P2-8 (scan + exit
  codes):** unchanged; telemetry deliberately carries no body text so
  the scan surface doesn't widen.
- **01 §5 multi-machine degradation:** §6.3 narrows when the
  degradation fires but keeps it as the designed fallback.
- **No new lifecycle status** — reaffirms the pending → terminal state
  machine exactly as pinned.
