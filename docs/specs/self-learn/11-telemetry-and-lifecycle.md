# 11 — The life of a lesson after routing: telemetry, lifecycle, and the facts layer

**Status: RATIFIED 2026-07-15 (user-delegated — "review them yourself and answer the questions you would ask me"; the Q&A is in the README revision log; any answer is user-vetoable, veto = dated register edit). v2 (drafted 2026-07-14; v2 same day after a
four-agent audit — the corpus-coherence and adversarial reviewers
independently confirmed that v1's observation plane violated P6/E-8 and
S-7, its worker emitters violated S-5/E-18, and its §8 no-reopen
certification was false. v2 repairs all confirmed findings; the v1
design survives in shape, corrected in mechanism. Builds land per §7.)**

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
   counts, next steps. And the design must stay multi-machine-safe *by
   construction*, not by merge-conflict handling.

Core principle: **certainty is measured, not declared.** Events, not
scores. One honesty rider (audit v2): where an event can only be
emitted by model discipline rather than code (declined offers, §4.3),
the derived metric is labeled a **lower bound**, never a measurement.

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
  pay attention-tax on every load. Dead weight accumulates. (§5 carries
  the audit caveat: observation of fires is lossy, so this silence can
  be *narrowed*, not eliminated.)
- **Capture-time context.** What the incident cost, whether the lesson
  is an environment quirk or general practice (the strongest known
  predictor of behavioral value — six dead fixture candidates), and
  what environment versions it depends on. Cheap to ask while the wound
  is fresh; unreconstructable later.

## 2. Lifecycle after routing

### 2.1 Follow-ups (known-partial at routing time)

Optional structured field on the routing block, written by the
resolution verbs (`route … --follow-up "<action>" --unblocks-on
"<gate>"`):

```yaml
routing:
  destination: skill-md
  follow_up:
    action: upgrade-to-hook
    unblocks_on: M3
    note: "advisory text is the weak form; deterministic guard is the strong form"
```

- The record's status stays terminal — the *lesson* is resolved; the
  follow-up is a planned upgrade. **No new lifecycle status exists or
  is wanted.**
- `status` output gains one line ("N open follow-ups") — **excluded
  from `status --json --fast`** (that path is pinned as a
  pending/-only frontmatter scan under a 500 ms SessionStart budget,
  08 §7.1; follow-ups live in `resolved/`). Full `status` and `report`
  carry it.
- `unblocks_on` is a human-readable gate label, not machine-evaluated;
  "open" simply means not yet cleared. Each milestone's build plan
  gains a pinned first step — **drain the follow-up list** — and
  clearing is owned by the `followup done <id> [--note …]` verb (§2.5).
- First entry: lrn-98d42215 (chezmoi cd), backfilled from its
  resolution note when the field lands.

### 2.2 Recurrences (discovered-partial after routing)

A new capture that matches an **already-routed** lesson is a
*recurrence* — evidence the rule is absent, weak, or only partial.

- **Detection** is machine work (M2: the worker's similarity machinery
  pointed at resolved records; plus origin/id matching). A detection is
  a **suspect** and lives in the observation plane (§4) — the machine
  never writes the record.
- **Confirmation** is human work: a routed record with suspects
  surfaces in review as a **"not holding" card**: *"Routed <date>.
  Sighted N times since. Revise, escalate, tolerate, or retire?"*
  Confirming runs `confirm-recurrence` (§2.5), which appends to the
  record's `recurrences:` list — append-only, dated, carrying the
  minimal facts (ts, origin) copied out of the event; the `ref` back
  into telemetry is a **courtesy pointer, non-load-bearing** (telemetry
  is cheap truth; the record must stand alone).
- Resolutions: **revise** (supersede with better wording) · **escalate**
  (supersede toward a stronger surface) · **tolerate**
  (`confirm-recurrence --tolerate --note "<why the rule stays>"` — the
  note lands in `recurrences[].note`, NOT `resolution_note`, which
  stays write-once per 02 §2) · **retire** (supersede with nothing) ·
  **dismiss** (`dismiss-suspect <id> --event <nonce> --why <reason>
  [--note …]` — the sighting was never a recurrence: a matcher
  false-positive, not evidence the rule is absent or weak; appends to
  `dismissed_suspects:` (append-only, §3) and the telemetry event
  itself is preserved untouched). Read the suspect's `basis` before
  choosing tolerate vs dismiss: `fire-violated` is the model's own
  report that it broke the rule, while `miner-match` and
  `title-token-overlap` are text-similarity heuristics that can fire on
  a lesson nobody actually violated.
- `last_confirmed:` (date) is the flip side — written by the
  `confirm-held` verb (§2.5) whenever a human observes the rule
  working (typically from a "still good?" prompt on old rules in
  review, or ad hoc). Age-since-confirmation, not age-since-capture,
  is the staleness metric.
- **Multi-machine honesty (audit v2):** promotion is a same-file
  mutation of a resolved record. Like every record mutation (and unlike
  record *creation*), it is NOT namespace-protected: two machines
  promoting onto the same record degrade to autosync's standard
  rebase-halt (01 §5). The sentinel serializes within one machine only;
  one-review-host-at-a-time remains operating discipline, with claim
  visibility (§6.5) as the aid, not the guarantee.

### 2.3 The unripe case is already solved

Never-verified lessons (tree-lamp class) are **defer**, unchanged.
Follow-up = done-but-upgradeable; recurrence = done-but-not-holding;
defer = not-done. Three moments, three mechanisms, no limbo status.

### 2.4 Contradiction edges

`links.contradicts: [<lrn-id or canon anchor>]` — first-class,
machine-checkable. Written by the `link contradicts` verb (§2.5),
proposed by the analyst via a structured proposal field: **the proposal
schema gains an optional `contradicts:` list** (audit v2 — the
`already_canon` precedent applies: structured field, never parsed out
of rationale prose; §8 declares this schema addition honestly).

### 2.5 New verbs (pinned — 02 §2's discipline: no unowned mutations)

| Verb | Writes | Commit subject |
|---|---|---|
| `confirm-recurrence <id> --event <ref> [--tolerate --note …]` | `recurrences[]` append (+ optional note) | `self-learn: recurrence confirmed on lrn-<id>` |
| `confirm-held <id> [--note …]` | `last_confirmed` | `self-learn: confirmed holding lrn-<id>` |
| `dismiss-suspect <id> --event <ref> --why <reason> [--note …]` | `dismissed_suspects[]` append | `self-learn: suspect dismissed on lrn-<id>` |
| `link contradicts <id> <target>` | `links.contradicts` append | `self-learn: link lrn-<id> contradicts <target>` |
| `followup done <id> [--note …]` | clears `routing.follow_up` (moves it to a dated `follow_up_done` block) | `self-learn: follow-up done on lrn-<id>` |
| `undefer <id> [--note …]` | `status: pending`, clears `deferred_until` (keeps `deferred_count`) *(U-verbs Phase 1, §4.2 — pulled forward from D1's Phase-2 sweep, code gate r1: shipping without a row here left the doc table three verbs short of the code it documents)* | `self-learn: undefer lrn-<id>` |
| `reopen <id> [--note …]` | `status: pending`, displaces `resolution_note` into `history` (event: `resolution`), sweeps stale proposal/merge siblings *(U-verbs Phase 1, §4.2 — pulled forward, code gate r1)* | `self-learn: reopen lrn-<id>` |
| `note <id> --append <text> [--key <token>]` | `notes[]` append *(ANY status — never touches `resolution_note`; U-verbs Phase 1, §4.2 — pulled forward, code gate r1)* | `self-learn: note lrn-<id>` |
| `telemetry note <kind> [flags]` | **spool only (§4.2) — no repo write, no commit** | — |
| `telemetry flush` | spool → tracked telemetry file (§4.2) | *(none — autosync commits; never part of a verb's surgical commit)* |

All record-writing verbs here: sentinel self-hold + heartbeat, targeted
staging, full-record-file secret scan (P2-7), note → commit body — the
standard resolution-verb sequence.

## 3. Adjudication-plane schema additions (record frontmatter)

All human-owned, verb-written, low-volume, optional (existing records
stay valid). Substance-freeze (S-8/S-12) untouched — metadata class,
same as `superseded_by`.

```yaml
verified: true                    # capture-time grounding grade
verified_how: "repro'd twice on this host"
incident_cost: "an evening"       # free short phrase, captured fresh
generality: environment-specific  # environment-specific | general-practice | uncertain
env:                              # versions PRESENT at capture — an ambient
  swaync: "0.10.2"                #   HINT auto-stamp (code cannot know what a
  model: claude-fable-5           #   lesson is "about"); user-supplied entries
                                  #   WIN and are the only staleness triggers
                                  #   unless the user opts a hint in (else every
                                  #   model bump would flag every lesson)
routing:
  follow_up: {action: …, unblocks_on: …, note: …}
recurrences:
  - {ts: …, origin: …, note: …, ref: …}   # ref = courtesy pointer (§2.2)
dismissed_suspects:
  - {ref: …, ts: …, why: …, origin: …, basis: …, dismissed_at: …}
    # ref REQUIRED here (§4.3 asymmetry with recurrences[]'s courtesy
    # pointer) — a dismissal is a fact about one specific machine claim;
    # without the nonce it clears nothing and means nothing
last_confirmed: 2026-08-02
links:
  contradicts: [lrn-889241d9]
```

Capture-time fields ride `teach` as **optional-but-offered** — and the
in-session `/self-learn:teach` model **may infer cost/generality from
the transcript it holds** and simply confirm them in its summary,
rather than asking; two extra exchanges per capture would violate the
ambient-capture constraint (E-3). Bare-CLI teach prompts for neither
(flags only).

## 4. Observation plane (telemetry) — *v2: spool-and-flush*

### 4.1 Why v2 (the audit findings)

v1 had sessions appending directly to committed files — a per-session
tracked-file write, the exact class P6/E-8 and 02 §2 exclude "by
construction" (autosync would publish mid-session, unscanned), and its
worker emitters violated S-5's pinned write surface. v2 keeps the
plane, fixes the mechanism.

### 4.2 Mechanism: cache spool, verb flush

- **Any process may append events to the SPOOL** —
  `~/.cache/claude-skills/self-learn/spool/<month>.<actor>.jsonl` —
  because the spool is untracked transient state (exactly S-7's
  `~/.cache` class). Single-line JSON, flock on append (same-machine
  concurrent sessions are the common case).
- **Only human-triggered CLI verbs flush** the spool into the tracked
  plane — `.self-learn/telemetry/<month>.<actor>.jsonl` (root bucket,
  committed). Flushing verbs: `teach`, `import`, every resolution verb,
  `report`, worker run-end (kick-chained from teach/import, so still
  inside the human-triggered class), and explicit `telemetry flush`.
  **At flush, the §1 secret scan runs over every flushed line — a hit
  refuses the flush** (belt-and-suspenders; payloads are ids/enums by
  schema, §4.4).
- Flushed telemetry files are **never staged by a resolution verb's
  surgical commit** (they would sweep other sessions' lines into a
  pinned per-lesson commit); autosync commits them on its normal cycle.
  During a sentinel-held review, flushed lines simply wait for the
  release — acceptable, telemetry is cheap truth.
- `<actor>` = machine name (team scale: `machine.user`) —
  single-writer per tracked file by construction. Losing a month of
  spool (cache wipe, crash before flush) degrades analytics, never the
  ledger.
- The bucket-discovery glob and `--selftest` **skip
  `.self-learn/telemetry/`** (not records; pinned here so the validator
  never trips on it).
- The M2 worker's `claude -p` analysis pass **never writes telemetry**
  — it holds no write path to the telemetry plane on either backend:
  `--allowedTools` grants read tools only, and the write grant (settings
  file on `cli`, charter on `sdk`) names the worker's exclusive stage and
  nothing else (S-5/E-18 unchanged; `S-32`). *(corrected 2026-08-19,
  U-docs: `--allowedTools` never carried the write surface, and the scope
  is the stage, not `proposals/`. The bullet's claim — the analysis pass
  never writes telemetry — is unaffected and is now enforced by two
  mechanisms instead of one.)* It emits structured suspect/fire candidates as proposal-
  dir artifacts; **CLI harness code** validates them (run-sequence
  step-4 class) and spools the events. Only CLI code appends anywhere
  in this plane.

### 4.3 Event kinds (v1 closed set; extending = version bump)

| kind | emitted by | payload |
|---|---|---|
| `offer-made` / `offer-declined` | the model, via `telemetry note` (spool-only, cache write — permitted per-session) | decline reason: **closed enum** `not-durable \| wrong \| duplicate \| private \| later \| other` — **no free text** (audit v2) |
| `capture` | teach/import (CLI) | source, bucket |
| `card-shown` / `card-decided` | CLI/TUI code paths; tolerated-absent in the slash-review era (prompt-driven surface) | recommendation, decision, overridden: bool, dest-delta |
| `fire` | worker harness (CLI) from miner candidates | **non-textual anchor only: (transcript-id, line-number) or content-hash — never a phrase or span** (audit v2; transcript text is the least-trusted text in the system), confidence |
| `recurrence-suspect` | worker harness (CLI) | matched record id, origin id, similarity basis label |
| `staleness-flag` | env sweep (CLI) | component, from-version, to-version |
| `surface-budget` | compilers (CLI, inside verb flow) | target, words, cap, overflow: bool |

**Honesty pins (audit v2):** the offer denominator is **model-emitted,
best-effort** — accepted offers get a code-emitted `capture` event
(teach runs), but declined offers depend on the model invoking
`telemetry note`, whose compliance is itself unmeasured and biased
against the quantity it measures. `report` MUST therefore label capture
rate a **lower bound**. This requires one clause appended to the S-15
offer line (a verbatim-pinned spec edit, declared in §8): *"…offer once
and briefly to capture it (self-learn teach); if declined, log it:
`self-learn telemetry note offer-declined [--reason <enum>]`."*

### 4.4 Content discipline

Events carry ids, enums, versions, hashes, counts — **never lesson body
text, quotes, transcript spans, or free text** (the one free-ish field,
decline reason, is an enum). The scan-at-flush (§4.2) enforces the
class; the schema makes violations structurally awkward first.

## 5. Derived plane (index + report)

Disposable SQLite at `~/.cache/claude-skills/self-learn/index.db`;
never committed; keyed to (git HEAD, telemetry high-water marks,
schema_version); any reader rebuilds on mismatch; schema change =
version bump + rebuild, never migrations. Ingests record files, git
history (`transitions`), telemetry, and worker-mined candidates.
Tables: `records`, `transitions`, `events`, `fires`, `offers`, `edges`
(supersedes/contradicts/cluster), `surfaces`, + FTS5 over
trigger/instruction/fact text. (§7 sequencing note: `report` v1 may
walk files directly; the index becomes its engine at M2 — this is the
one deliberate divergence from "report always builds the index".)

`report` answers at minimum: routed per bucket · supersede rate ·
recurrence-flagged rules · open follow-ups · iteration depth ·
**capture rate (labeled lower-bound, §4.3)** · **no-observed-fires
candidate list** (audit v2: NOT "dead weight" — a silently-working rule
often fires without a trace; observation is lossy, the list nominates
candidates for the human `confirm-held`/demote judgment, never
auto-retirement; the miner must run within the transcript-retention
window or fires undercount further) · ROI proxy (incident_cost buckets
on fired lessons) · analyst calibration (override rate) · staleness
queue (user-pinned env moved; last_confirmed old) · contradiction queue
· deferred aging.

**Event ordering (audit v2 — replaces v1's ancestry rule):** "before/
after routing" is decided by **event `ts` vs `routing.routed_at`**
(day-granularity decisions tolerate clock skew). Git ancestry is NOT a
usable order proxy here: rebase-based autosync rewrites commits on top
of whatever arrived first, so ancestry is retroactively unstable and
systematically after-biased. Ancestry serves only as a knowledge bound
(a worker that matched against a resolved record necessarily had the
routing commit locally). Cross-machine order remains partial; `report`
says so.

## 6. Multi-machine posture (standing design principles)

1. **Solve concurrency in the namespace, not the merge** — for
   *creation and append*: create-only record files, actor-scoped
   telemetry, spool-per-actor. **Record *mutation* is the honest
   exception** (audit v2): promotion, confirm-held, links — same-file
   writes that degrade to the standard rebase-halt cross-machine, held
   rare by one-review-host discipline. CRDT-shaped convergence where
   the namespace can give it; declared degradation where it can't.
2. **Two planes, one-way flow, code-only appends.** Sessions and
   workers write the spool (cache); human-triggered verbs flush to the
   tracked plane; humans alone mutate records; the worker's model pass
   writes proposals only. Promotion (suspect → confirmed) is always a
   human verb inside a sentinel-held session.
3. **Derived artifacts are regenerated, never merged.** The index
   rebuilds; managed-section conflicts are in principle resolvable by
   recompiling from the union of records — recompile-on-conflict is
   DESIGNED-NOT-BUILT; rebase-halt stands at current scale.
4. **Order from timestamps at decision granularity; ancestry as a
   knowledge bound only** (§5 — v1's ancestry-primary rule was
   falsified under rebase-based sync).
5. **Same-machine concurrency is the common case** — spool appends are
   single-line + flock. The irreducible conflict (two humans, one
   record) is answered by visibility (claim events, status strip), not
   merging.

## 7. Sequencing

- **Now (M1-era, small):** §3 schema fields + validator; follow-up flag
  + `followup done`; spool library + `telemetry note` (offer ledger)
  + flush-in-verbs; S-15 offer-line clause (chezmoi flow); `report` v1
  (file-walking); backfill lrn-98d42215.
- **M2 riders:** worker suspect/fire candidates through CLI validation;
  not-holding cards + `confirm-recurrence`/`confirm-held`/`link
  contradicts`; proposal `contradicts:` field; index as report's engine
  + FTS; analyst calibration; miner-within-retention pin.
- **Later:** recompile-on-conflict handler; actor-scoping widening;
  staleness sweeps wired to package-manager logs.

## 8. Register touch-points (v2 — the honest list)

v1 certified "no settled decision reopens"; the audit falsified that.
The v2 list, for ratification:

| Pin | Status under v2 |
|---|---|
| **P6 / E-8 (never per-session tracked writes)** | **Letter preserved by the spool**: sessions write `~/.cache` only; every tracked write remains human-triggered (flush inside verbs). No reopen needed — but this row exists because v1 violated it. |
| **S-7 (storage taxonomy)** | **Dated amendment required at ratification**: `.self-learn/telemetry/` is a declared third storage class — committed, append-only, actor-scoped, verb-flushed observation files (neither record-per-file nor cache-transient). Argument: single-writer filenames + human-triggered flushes keep both E-8 halves (no storm, no unreviewed publication — flush is scanned). |
| **S-5 / E-18 (worker write surface)** | **Unchanged** — pinned here: the model pass writes proposals only; telemetry appends are CLI-harness code. |
| **S-15 (offer line, verbatim-pinned in 08 §1)** | **Dated pin edit required**: the line gains the decline-logging clause quoted in §4.3. Offer *semantics* unchanged. |
| **02 §1 (proposal schema)** | Gains optional `contradicts:` (structured-not-prose precedent: `already_canon`). Beyond the card contract's `card:`, this is the only addition. |
| **02 §2 (mutation rules / write-once resolution_note)** | New verbs (§2.5) extend the *verb set* with pinned commits; `resolution_note` stays write-once (tolerate notes live in `recurrences[].note`). |
| **08 §7.1 (`status --json --fast`)** | Unchanged — follow-up counts excluded from the fast path (§2.1). |
| **S-8/S-12 (substance freeze), P2-4, P2-7/P2-8** | Untouched; scan surface *narrows* if anything (scan-at-flush adds a check; no new free text anywhere). |
| **No new lifecycle status** | Reaffirmed. |
