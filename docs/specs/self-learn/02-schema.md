# 02 — Schema: the learning record and its storage

## 1. The record

One file per learning: YAML frontmatter (machine fields) + markdown body
(the lesson itself). Filenames: `lrn-<8char-id>.md` — 8 **random lowercase
hex** chars.

```yaml
---
id: lrn-4c1e9a2f
type: behavior            # behavior | knowledge
scope: skill:home-assistant   # skill:<name> | project | user
kind: anti-pattern        # behavior only: anti-pattern | surface-rule | reasoning-pattern
source: teach             # teach | auto-memory | backlog | session
status: pending           # pending | routed | rejected | deferred | superseded
created_at: 2026-07-12T09:14:00Z
sightings: 2              # set when a merge proposal is collapsed at review
                          #   (the worker itself never writes records)
evidence:                 # pointers, never transcripts
  - {session: f687d7ce, ts: 2026-07-12T09:13:41Z, quote: "never edit .storage while HA is running"}
  - {origin: "GOTCHAS.journal.md#2026-06-08", note: "added when the merge proposal was collapsed at review"}
# (no proposal block — the worker writes proposals/lrn-4c1e9a2f.yaml, a
#  sibling file; see below. The record itself is untouched between capture
#  and routing, so cross-machine analysis never mutates a synced file.)
routing:                  # written on routing; null before
  routed_at: 2026-07-13T18:02:00Z
  destination: hook
  by: human               # FW-64: the actor that chose the destination —
                          #   human | analyst | agent | steward | overseer
                          #   (this line was stale even before FW-64:
                          #   U-reach's §2.3 already introduced `analyst`
                          #   and never updated this comment; `agent` names
                          #   the SDK pane's own `propose_verb` route
                          #   proposals — verbs.py's `ROUTING_BY_VALUES`;
                          #   `steward` and `overseer` widen the same list,
                          #   2026-09-13, S-65 — every sheet item and case
                          #   `actor` field draws from it)
  reference_file: null    # 2026-07-16 (doc 13 audit): `reference`
                          #   destination ONLY — WHICH references file got
                          #   the entry (`--dest reference:<file>`); absent
                          #   ⇒ LEARNINGS.md, the pre-doc-13 default, so
                          #   records routed before the field existed still
                          #   read correctly (the audit verified this
                          #   against all 14 live reference-routed
                          #   records). Load-bearing: recompile and the
                          #   drift check READ it to find the target.
                          #   compilers.reference_target_path is the one
                          #   place that mapping lives.
  hook:                   # 2026-07-16 (M3): `hook` destination ONLY —
    script_path: hooks/…  #   host-relative path of the applied guard and
    script: "#!/usr/…"    #   the exact APPROVED script bytes (M3-2:
                          #   drift check + recompile re-APPLY these
                          #   bytes, never regenerate from changed
                          #   inputs; --selftest byte-compares disk vs
                          #   this field). Secret-scanned like all
                          #   record writes; ~2 KB per routed hook.
  new_skill: <name>       # 2026-07-16 (M3): `new-skill` destination ONLY —
                          #   which plugin/skill the scaffold created;
                          #   recompile, drift, markers, and supersede
                          #   READ it to find the target.
  # no commit hash here — a commit's own hash can't live in a file it
  # contains. The record→commit link is the commit MESSAGE, which carries
  # the record id ("self-learn: route lrn-4c1e9a2f → hook"); git log --grep
  # by id recovers it.
supersedes: null
superseded_by: null
resolution_note: null     # optional; the human's why, written once at
                          #   resolution (route/reject/graduate) — see §2
---

## Trigger
About to edit a `.storage/*.json` file while Home Assistant is running.

## Instruction
Stop the HA container first. HA caches `.storage` in memory and rewrites it
on shutdown, so a live edit is silently clobbered.
```

**Body shape by type:** `behavior` → `## Trigger` (the firing condition — the
record's real key, written so the model recognizes the moment) + `##
Instruction` (what to do, carrying the *why*). `knowledge` → `## Fact` +
optional `## Context`. One lesson per record; a capture containing two
lessons becomes two records.

**`## Episode brief` — a miner-only, compiler-excluded body section**
*(added 2026-07-18 — UX survey item 5; doc 12 §11 is the miner-side
contract, 09 §2.3 the display, 09 §11 Y-21 the register, 10 §3 U18 the
build).* An **optional** body section, written only for
`source: session` records (a producer convention, not a validator gate —
see below) — a 100–200-word plain-words
reconstruction of the origin episode (the attempt→failure→correction→
resolution arc, in the human's domestic terms), written by the
**transcript miner** at land from its transcript read (doc 12 §11). It is
a *record-body* section, not a proposal `card:` section, for a load-
bearing reason: **cards are the analyst's artifact** (the `card:` map
below, written by the M2 worker / pane per `card-sections.yaml` and
routing-doctrine §8), while **the record body is the capture producer's
artifact** — the miner writes records, never cards, and doc 12 §1's "no
card-registry change" pin depends on that boundary. Homing the brief in
the body keeps the miner writing only what it already writes (a record),
needs no card-registry change, and does not couple the brief's existence
to a later successful worker run. *(Alternates weighed and rejected: a
`card:` section written by the miner — producer writing the analyst's
artifact, and cards render at the TOP of Detail, pushing decision content
down; a record field lifted into a card by the worker — couples the brief
to the worker run and still lands it in the top card region; a
frontmatter field — prose does not belong in machine frontmatter and it
would bloat every `list --json` parse; a sibling file — the analyst's
space, an extra thing to sweep on rehome/resolve and scan out-of-band,
whereas a body section is secret-scanned on every write (§2), moves
byte-untouched on rehome/rescope *(true of the BODY unconditionally —
corrected 2026-08-28, code gate r2, N-r2-2: since U-verbs §3.2 widened
`--to` past project↔project, a cross-scope move now rewrites the
record's `scope:` frontmatter to match the destination — §2 `rehome`'s
own amendment above — so only the body, never the whole record byte-
for-byte, is guaranteed untouched)*, and is git-versioned with the
record.)*

- **Validator (register it as optional; do not gate compilers on it).**
  `## Episode brief` joins the record's **optional** body sections
  (`records.py` `OPTIONAL_SECTIONS`), permitted for both `behavior` and
  `knowledge` records. The one-lesson duplicate guard **will** refuse a
  repeated `## Episode brief` **once the section is registered** — the
  U18 build adds `"Episode brief"` to both type tuples; `_validate_body`
  only duplicate-guards names it knows, so the guard does not apply until
  then. Existing records stay valid (unknown headings already pass; this
  merely *documents and de-duplicates* the section). It carries **no**
  `required` weight — a mined record without one is valid (no-backfill,
  below).
- **`source: session` is a producer-side convention, not a validator or
  render gate — stated honestly.** In practice only the miner writes a
  brief, and only onto `source: session` records (12 §11). But the
  validator does not key the section to `source`, and the Detail render
  keys on **section presence**, not provenance. So a human who, on the
  Discuss / pane edit path, adds a `## Episode brief` to a `teach`
  record produces a record that **validates and renders** — this is
  **accepted**: it is a human editing their own pending record's body
  (legal under §2 freeze-at-routing), the same edit path that can rewrite
  Trigger or Instruction, and it is covered by the same
  `proposal validate` secret-scan checkpoint (§2) that guards every
  non-CLI body write. The gate that matters — the leak surface — is the
  scan, and the scan is provenance-blind by design.
- **Compiler exclusion — pinned, and it holds by construction.** Every
  compiler selects body sections by **explicit heading name** —
  `compilers.py` `_body_sections()` maps all `## …` headings, then each
  compiler reads only the names it wants: the managed-section compiler
  and the reference-journal compiler both do `sections.get("Trigger")`,
  `.get("Instruction")`, `.get("Fact")`, `.get("Context")` and **nothing
  else**; there is no whole-body dump anywhere in `compilers.py` or
  `hook_compiler.py`. So `## Episode brief` is extracted into the map but
  **never read into any compile target** — it can never reach a managed
  section, a `references/` journal entry, a hook script, or a scaffold.
  **Obligation (do not regress):** no compiler may add a
  `sections.get("Episode brief")` (or any glob-all-sections) read, and a
  regression test asserts that for a record carrying a `## Episode
  brief`, **no** compiled output (managed section, reference journal,
  hook) contains the brief text. The brief is decision-surface material
  only (09 §2.3); it must never leak into canon.

**The proposal sibling.** The pre-analysis worker writes its analysis to
`proposals/lrn-<id>.yaml` beside the record — never into the record itself:

```yaml
# proposals/lrn-4c1e9a2f.yaml
destination: hook         # skill-md | claude-md | reference | new-skill | hook
alternates: [skill-md]
rationale: "deterministic guard beats advisory text for a destructive edit"
already_canon: false      # true ⇒ the lesson is already fully present in
                          #   loaded canon (01 §3.2's criterion). A
                          #   structured field, not prose: UI surfaces
                          #   group and bulk-resolve on it, and 07 §4
                          #   contract 2 forbids parsing it out of
                          #   rationale text. Set by the backlog importer
                          #   and the worker; `list --json` surfaces it.
                          #   Bulk resolution of a true-flagged group is
                          #   GRADUATION (§2 `superseded_by: canon`),
                          #   never rejection. (Added 2026-07-12, G-3
                          #   phase 2 — 09 §2.2/P1-2; previously this
                          #   judgment lived only in free-form rationale.)
already_canon_reason: ""  # optional one-liner rendered on the detail page
diff: proposals/lrn-4c1e9a2f.diff   # PREVIEW ONLY — compilers regenerate from
                                    # the record at apply time (01 §3.5)
record_sha: sha256:a1b2c3d4e5f6     # of the normalized record at analysis
                                    #   time — proposal staleness = hash
                                    #   mismatch, NEVER file mtime (git
                                    #   checkouts rewrite mtimes; M2 review).
                                    #   STAMPED BY THE CLI at proposal
                                    #   validation, never emitted by the
                                    #   model (same normalization fn as
                                    #   evidence.origin's content hash)
model: claude-opus-4-8
analyzed_at: 2026-07-12T09:25:12Z
card:                     # human-facing review-card sections (added
  headline: "…"           #   2026-07-14, decision-support contract —
  impact: "…"             #   routing-doctrine.md §8). A map of section
  discuss: "…"            #   key → markdown text. The section SET —
                          #   keys, labels, display order, required-ness,
                          #   and each section's writing instruction —
                          #   lives in the skill's card-sections.yaml
                          #   registry, NOT here and NOT in any surface:
                          #   analysts write the sections the registry
                          #   requires; surfaces render the map
                          #   generically in registry order, skipping
                          #   absent keys and rendering unknown keys
                          #   last. Adding/changing/retiring a section
                          #   is an edit to the registry file only.
                          #   VALIDATOR POSTURE (M1): `card` is optional
                          #   (pre-contract proposals stay valid) and
                          #   shape-checked only — a mapping of
                          #   non-empty string → non-empty string; the
                          #   secret scan already covers it via the
                          #   full-sibling-text rule. Required-section
                          #   enforcement is analyst discipline until
                          #   T13, where the worker's output QA revisits
                          #   strictness (08 §7).
```

**The merge proposal** (M2; same directory, `proposals/merge-<8hex>.yaml`):

```yaml
cluster_id: merge-9f3d2c1a
records: [lrn-4c1e9a2f, lrn-77ab01cd]   # SAME BUCKET ONLY in v1 — the worker
                                        #   never emits a cross-bucket cluster;
                                        #   if it judges records in different
                                        #   buckets to be one lesson, it splits
                                        #   them into per-bucket proposals
suggested_survivor: lrn-4c1e9a2f        # worker's nomination (best-formed
                                        #   trigger/instruction); the human's
                                        #   collapse card confirms or overrides
rationale: "same .storage-while-running lesson: one teach, one backlog import"
record_shas:
  lrn-4c1e9a2f: sha256:a1b2c3d4e5f6
  lrn-77ab01cd: sha256:0f9e8d7c6b5a
model: claude-sonnet-5
analyzed_at: 2026-07-13T02:10:00Z
```

Merge-proposal lifecycle: removed (`git rm`) when the cluster is collapsed at
review, **or** as soon as any member record resolves individually — a partial
cluster is invalid and must not resurface as a card.

**Hook-destination extension** *(M3; the one documented exception to
regenerate-at-apply)*: a `destination: hook` proposal additionally carries
the structured compile input — `hook: {tools: […], path_regex: "…",
deny_message: "…"}` plus the full generated script text and the analyst's
allow/deny example inputs. The route verb applies that content **verbatim**
(byte-identical to the approved diff; P9 — the target is executable);
a `record_sha` mismatch aborts and forces re-analysis + fresh approval,
never silent regeneration (`08-build-plan.md` §8.1).

Keeping the proposal out of the record means that after capture, **the only
writer of a pending record is the human** — the worker's clustering emits
merge *proposals*, never record edits (blind re-review 2026-07-12). A stale
proposal can never corrupt a record. Honest scope of the guarantee: the
*ledger* is race-free single- and multi-machine (record-per-file, new-file
writes); the shared *compile targets* (managed sections) are not
record-per-file, so concurrent multi-machine routing degrades to autosync's
standard safe rebase-halt (`01` §5) rather than being excluded outright.

## 2. Field rules

> **Amendment 2026-07-15 (11 §3, ratified):** the frontmatter gains the
> adjudication-plane fields — `verified`/`verified_how`, `incident_cost`,
> `generality`, `env`, `routing.follow_up` → `follow_up_done`,
> `recurrences` (append-only, ts+origin minimal facts), `last_confirmed`,
> `links.contradicts`. All optional (existing records stay valid), all
> **metadata class** like `superseded_by` — verb-written, mutable in every
> status; the substance freeze below is untouched. The owning verbs and
> their pinned commit subjects are 11 §2.5's table; tolerate-notes land in
> `recurrences[].note`, never `resolution_note` (which stays write-once).
>
> **Amendment 2026-08-24 (U-dismiss, 11 §2.2/§2.5):** the frontmatter
> also gains `dismissed_suspects` (append-only) — a human's ruling that a
> `recurrence-suspect` telemetry claim was a matcher false-positive, not
> a real recurrence. Same metadata class as `recurrences`, but its `ref`
> is **REQUIRED and load-bearing**, unlike `recurrences[]`'s courtesy
> pointer: a dismissal is a fact about one specific machine claim, and
> without the nonce it clears nothing and means nothing.
>
> **Amendment 2026-08-28 (U-verbs §4.10):** the frontmatter gains two more
> append-only lists, both **metadata class** like `recurrences`/
> `dismissed_suspects` above — verb-written, mutable in every status, the
> substance freeze below untouched. `history` records what a verb
> **displaced**: `reopen` moves a `resolved` record back to `pending` and
> appends the old `resolution_note` as a `history` entry (`event:
> "resolution"`, carrying the displaced `status`/`note`) before clearing
> the field, so a write-once value can be superseded without being
> destroyed; a later verb correcting a wrong routing destination displaces
> the old `routing` block the same way (`event: "routing"`). `event` is a
> **closed set** — `{"resolution", "routing"}` — a third displacement kind
> is a decision, not a silent widening. `notes` records what a human
> **added**: `self-learn note <id> --append TEXT` appends `{at, by, text}`
> (plus an optional `key`, the idempotency token `self-learn batch`
> stamps on a `note` sheet item's entry) to `notes[]`, in any status,
> never touching `resolution_note` — `notes` is additive commentary,
> `history` is what the record used to say; merging the two would make
> both unreadable. `Record.clear_resolution_note()` is the **only**
> permitted writer of `resolution_note` back to `None`, and it refuses
> unless the current note already appears in a `history` entry with
> `event: "resolution"` — the write-once field may be *displaced*, never
> *destroyed* outright. Neither key exists at all on a record no verb in
> this set has ever touched — the schema addition is **absent**, not an
> empty list.

- **`history`'s closed set widens to five kinds** *(2026-09-13 — the
  overseer build, O-0; note text amended 2026-09-14 — O-2a fold r2,
  ruling 5)*: `{"resolution", "routing", "hook-activated",
  "hook-deactivated", "reconsidered"}`, superseding the 2026-08-28
  amendment's two-kind set above without rewriting it. `hook-activated`/
  `hook-deactivated` record `13-hosting-and-separation.md` §7.4's verb
  applying or reversing a hook route, for either caller — the human's
  `hook activate`/`hook deactivate` or the overseer's own runner call.
  Deactivation is surgical (it removes exactly one registration, never a
  whole-file restore) and so never has a backup of its own to name: a
  `hook-activated` entry's `note` carries the settings-file backup path,
  or a truthful no-backup string when this call wrote none (already
  registered; or settings.json was freshly created, with nothing prior
  to back up); a `hook-deactivated` entry's `note` instead names the
  removed registration (its matcher and command) and the symlink path,
  or the same truthful "already absent"/"left untouched" string when
  nothing changed. `reconsidered` is the
  successor-case pointer a dependency-moved observation queues
  (`02-schema.md` §3a.2) — a decision, made once, here.
- **`<ledger>/overseer/` is not a bucket** *(2026-09-13 — the overseer
  build, O-0)*: it holds no `pending/resolved/proposals` records, is never
  a route destination, and never appears in `list --json`'s bucket
  enumeration.

- **What a placement must eventually persist, named here descriptively
  — no field below exists yet, and this amendment adds none**
  *(2026-09-11 — the placement amendment; forward work, not this
  sprint — `14-forward-work-map.md`)*: *applicability*, distinct from
  provenance (trigger-shape tags; bounded artifact/task/tool
  qualifiers; candidate project root; latest-useful-event; an optional
  validity condition); *approved activation* (a versioned snapshot of
  native mechanism, entry surface/task cue, target host, and payload
  reference — reusing `routing`'s existing `rules_paths`/`rules_topic`/
  `reference_file` rather than duplicating them); *review obligation*
  (a review-after date or a named event, a reason, and the latest human
  disposition); *evidence linkage* (existing session/origin plus
  confirmed-recurrence/held evidence, tied to a routing revision). A
  placement revision, once it exists, starts a new exposure window but
  must not erase prior sightings, validity limits, or review history —
  the same append-only discipline `evidence` already has below, applied
  to a field that does not exist yet.
- **Substance freezes at routing** *(S-8/S-12 — settled 2026-07-12,
  blind-adjudicated ADOPT)*: while
  `pending`, the body and filing may be edited freely — a typo in your own
  thirty-second-old capture is not a provenance event, and git versions
  every draft state anyway. At routing the substance freezes: `created_at`,
  `type`, `source`, and the body never change afterward; a wrong *routed*
  lesson is corrected by a new record with `supersedes:` set, and the old
  one gets `superseded_by:` + `status: superseded`. The provenance ceremony
  is for canon, not drafts. *(Added 2026-09-13, S-65:)* `self-learn revise
  <id> --section … --text … --because …` is the one sanctioned pending or
  deferred edit through a scanned verb — for refining a lesson's wording
  at adjudication
  without changing what it claims; a routed record still admits no edit but
  `reconsider` (§3a).
- **`evidence` is append-only** — it may *gain* entries (cluster merges add
  the merged record's provenance) but existing entries are never rewritten
  or removed. *(Draft 1 listed `evidence` as immutable while also having the
  cluster pass append to it; this resolves that contradiction.)*
- **`evidence.origin` is a stable dedupe key** *(implementability review
  2026-07-12)*: `<repo-relative-path>#<anchor>`, where the anchor is a
  heading/date anchor when the source has one
  (`GOTCHAS.journal.md#2026-06-08`) or `sha256:<first-12-hex>` of the
  normalized entry text when it doesn't (auto-memory bullets). **Never line
  numbers** — the key must survive file reflow, or rejected entries
  resurrect on the next import (the exact failure the dedupe exists to
  prevent).
- **Evidence quotes are minimal, and every record-body write is
  secret-scanned** — capture (`teach`), review edits, and merge collapses
  alike. Records are tracked files: autosync publishes each write to the
  remote within seconds, *before* any human review (E-8), and
  freeze-at-routing legalizes post-capture edits — so the scan guards the
  write path, not just the front door (blind-adjudication rider,
  2026-07-12). The scanner refuses (or redacts and flags) anything that
  trips it; quotes carry the shortest span that proves the sighting.
  *(Enforcement points, pinned 2026-07-12 — G-3 phase 2/P2-1: CLI verbs
  scan their own writes; writes that bypass CLI verbs — the review
  Discuss-edit and the G-3 pane agent's edits — are scanned by
  `self-learn proposal validate <id>` at card completion / pane session
  end, 08 §7.1 — on those two paths the scan **detects at the
  checkpoint rather than preventing at the keystroke** (agent writes
  may sync before the checkpoint runs; the resolution verbs' own
  full-file scan is the no-bypass backstop before anything reaches
  canon). The every-write claim names its mechanism on every path.)*
- **`superseded_by` ∈ {`null`, `<record-id>`, `"canon"`}.** A record-id
  marks *corrective* supersession — the lesson was wrong and a new record
  replaces it. `canon` marks **graduation** — the substance now lives in
  authored canon (a hand-weave, or the backlog's bulk-acknowledge). A
  canon-superseded record takes `status: superseded`, lives in `resolved/`,
  and carries no routing linkage. The two meanings are opposites — a failure
  and a success — and metrics must never conflate them (`04-roadmap.md`).
  Graduation's owning verb: `self-learn graduate <id>` (or the review card).
  One boundary case pinned (implementability review 2026-07-12):
  **merge-collapse losers** — records that were never routed, merely
  redundant — take `superseded_by: <survivor-id>` while still pending; the
  *corrective* reading ("the lesson was wrong") applies only when the
  superseded record had reached `routed`.

  *Amended 2026-09-13 (`S-67`, U13):* the field's domain widens to
  `superseded_by ∈ {null, <record-id>, covered_by:<kind>:<name>}`
  (`claude-md:<path>`, `skill-md:<name>`, `reference:<file>`, or
  `output-style:<name>`) — a new write always names the covering surface,
  never the bare literal `"canon"`. The two meanings this bullet already
  calls opposite now get display words to match: a canon-superseded record
  — what this bullet calls **graduation** — is displayed as **retire**; a
  record-id supersession — this bullet's *corrective* case — is displayed
  as **replaced**. Both stay one internal status, `status: superseded`;
  nothing branches on the display word. A legacy record still carrying the
  bare literal `superseded_by: "canon"` is read as a retirement whose
  covering surface is unrecorded — never invented, never blocking the read.
  `self-learn graduate <id>` stays callable, unchanged, for one release as a
  hidden alias for `self-learn retire <id> --covered-by <surface>`;
  `self-learn supersede`/`--supersedes` are untouched by this rename (they
  were never the ambiguous word). `reopen` widens to admit a wrong
  **retire** back to `pending`; it stays refused for a **replaced** record,
  since undoing a live successor is `reconsider`'s territory
  (`misc/audit-2026-09-02/steward-design/plan-steward-2026-09-12.md` U5),
  never a reopen.
- **Lifecycle metadata may mutate**: `status`, `routing`, `sightings`,
  `scope`/`kind` (triage may re-classify — the filing is never frozen).
  `deferred` adds `deferred_until` (default: +30 days — the record is
  excluded from cards and pending counts until then) and `deferred_count`
  (at 2, the review card suggests reject). All such writes are
  **human-triggered** — the worker writes only proposal files, merges
  included (blind re-review 2026-07-12) — and never per-session; nothing in
  this schema is touched by merely *using* Claude Code (the gen-1
  counter/autosync-storm bug is excluded by construction, E-8).
- **`resolution_note`** *(added 2026-07-12, UI direction — `07-review-ui.md`)*:
  optional free text, written **exactly once** at resolution
  (route/reject/graduate; the CLI verbs take `--note`, the review card's
  free-text path feeds it), echoed into the resolving commit message. Legal
  under freeze-at-routing — it is part of the resolution event, not a later
  edit of substance. It is the user's *why*, and it is fuel: the M2 worker's
  rejected-proposal digest reads it, so a noted denial teaches the analyst
  why that proposal class loses *(Amended 2026-09-14, U7: the digest no
  longer reaches the analyst prompt — prior decisions arrive there as
  cited cases instead, §3a.1 item 6, below; `_digest` still reads
  `resolution_note` this way, unused in that path)*. Secret-scanned like
  every record-body write.
- **Lifecycle notes for the implementer** *(deliberate choices, stated so no
  one hunts for missing fields)*: rejection/supersession provenance is
  carried by git — the resolving commit's author, date, and message are the
  who/when, so there are no `rejected_at`/`reason` fields *(amended
  2026-07-12: the **why** may now live in `resolution_note`, above; git
  remains the who/when)* · `status:
  routed` records live in `resolved/` (the directory is the umbrella for all
  terminal statuses; the status stays precise) · **every resolution verb
  commits**, with pinned message formats — `self-learn: route lrn-… →
  <target>` · `self-learn: reject lrn-…` · `self-learn: defer lrn-… until
  <date>` · `self-learn: graduate lrn-…` · `self-learn: supersede lrn-… →
  lrn-…` — and `resolution_note` becomes the commit body, so no resolution
  ever rides an anonymous autosync commit (the M2 digest greps these
  messages; implementability review 2026-07-12) · a deferred record keeps
  `status: deferred` while hidden — queue membership is *computed* from
  `deferred_until`, not read off the status · `teach --route` writes its
  record directly to `resolved/` as `status: routed`, never transiting
  `pending/` · `source: session` is written by the doc-12 transcript miner
  *(swept 2026-07-17 — this line predated the miner: it originally
  forward-declared the enum for a v1.1 SessionEnd appender (O-3);
  O-3 settled 2026-07-15 as the miner instead, live since M2.5)* · record ids are **random**
  (collision-resistant across offline machines); a sequential counter would
  add/add-conflict on every parallel capture.
- **`self-learn rehome <id> --to <path-or-slug>`** *(added 2026-07-18 —
  feedback round 3 item 3; 09 §11 Y-18 is the surface register entry)*:
  moves a **pending** (or **deferred**) record to **any registered
  scope** — `user` | `skill:<name>` | a registered project bucket
  *(widened 2026-08-28 — U-verbs §3.2, ruling R1; originally
  project→project only — the repair for capture-cwd filing the lesson
  under a narrower repo than its real firing range, the umbrella-project
  case, routing-doctrine §3)*. `--to` accepts the UNION grammar shared
  with `rescope` below (`_resolve_move_target`, one resolver behind
  both verbs): the literal `user`; `skill:<name>`; a
  `project:<path-or-slug>` prefix; or a bare path/slug, read as a
  project (the `host rebind` naming precedent) unless it collides with
  a reserved literal — a registered project host directory literally
  named `user` needs `project:user` or `./user` to reach it. What moves: `pending/lrn-<id>.md` alone, one
  `git mv` into the target bucket's `pending/`; the target bucket's
  `{pending,resolved,proposals}/` dirs are created if absent and its
  `meta.yaml` stamped from the registered path (13 §3) — hosts.yaml
  stays the only registration authority; the verb registers nothing.
  The record's bytes are untouched **apart from `scope:`** *(amended
  2026-08-28 — U-verbs §3.2)*: a project→project move rewrites nothing
  (both read the literal `"project"` — the round-trip write is
  byte-identical there), but a move crossing a scope literal
  (`user ↔ skill:<name> ↔ project`) rewrites `scope:` to match the
  destination — a re-home is still a filing move, never a substance
  edit of anything else (the freeze rules above are unaffected;
  `sightings`, `evidence`, deferral metadata all ride along unchanged —
  a deferred record moves and stays deferred). **Proposal siblings are swept
  (`git rm proposals/lrn-<id>.{yaml,diff}`), never moved**: the
  analyst's destination judgment is bucket-relative (which CLAUDE.md,
  which references file) and `record_sha` staleness cannot catch a
  move — the hash is of record content, which didn't change — so a
  carried sibling would render an honest-looking stale card. The
  worker re-analyzes any proposal-less pending record on its next run;
  re-proposal in the new home is the honest cost of the move. **The
  same commit also `git rm`s any `merge-*.yaml` in the SOURCE bucket
  that names the record** *(review fold 2026-07-18, F3)*: a partial
  cluster is invalid and must not resurface (§1's merge lifecycle) —
  the resolution sweep already behaves exactly this way (08 §1), and a
  narrower rehome sweep would strand an invalid merge file behind. A
  worker mid-analysis on the moving record needs no special handling
  *(F9)*: its late-landing analyst proposal is an orphan `lrn-*.yaml`
  in the source bucket, swept by the worker's own next-run orphan
  sweep, and the two writers serialize on `commit_lock`. One
  ledger commit, pinned subject `self-learn: rehome lrn-… →
  projects/<slug>` (or `→ user` / `→ skills/<name>`, once the widened
  grammar above targets one of those — amended 2026-08-28, U-verbs
  §3.2); optional `--note` rides the commit body only
  (rehome is not a resolution — `resolution_note` stays write-once and
  untouched). Refusals, each checked on **status, never mere
  existence** (`find_record_path` also sees `resolved/`) and rendered
  verbatim on the surface (09 §5): unknown id · record not in
  `pending/` with status `pending`/`deferred` (a resolved lesson does
  not move — supersede is the correction machinery) · target not a
  registered project (the refusal names `self-learn host add <path>`
  as the human's repair) · target == the record's current bucket ·
  `lrn-<id>.md` already present in the target bucket, `pending/` OR
  `resolved/` *(F4 — the create-record collision precedent)*, checked
  **before** any target-dir/`meta.yaml` creation: a duplicated id is
  corruption to surface, never to merge into. *(The "source not a
  project bucket" refusal that used to close this list is GONE —
  amended 2026-08-28, U-verbs §3.2, ruling R1: a cross-scope move,
  `user`/`skill:<name>`/project source to any other registered scope,
  is now this verb's own business, not dated future work.)* Sequence
  otherwise standard for a record-writing verb: secret scan of the record file AND the note *(F6 — the file
  scan is a no-op in practice since the bytes don't change, but every
  record-writing verb scans both and uniformity beats the
  micro-optimization)*, `commit_lock` before the first mutation,
  sentinel self-hold + heartbeat, targeted staging, push.
- **`self-learn rescope <id> --to <scope>`** *(added 2026-08-23 — u-rescope,
  the `rehome` sibling for the `user ↔ skill:<name>` pair; 09 §11 Y-25 is the
  surface register entry)*: moves a **pending** (or `deferred`) record
  between the `user` bucket and a `skills/<name>` bucket, rewriting
  `scope:` in the SAME motion. *(Amended 2026-08-28 — U-verbs §3.2,
  ruling R1): `rehome` and `rescope` are no longer scope-partitioned
  siblings — both now delegate to the SAME resolver and the SAME verb
  body (`_move`, `MOVE10`), differing only in the commit-subject
  label. `rehome` is no longer project↔project only, and `rescope` no
  longer refuses `project` on either side nor `skill:<a> → skill:<b>`
  — either verb reaches any registered scope from any registered
  scope, gated on record status alone. The two entry points remain
  distinct call surfaces (argv, CLI help text, the pane's
  proposable-verb list) for human legibility — "rehome" reads as a
  project move, "rescope" as a scope-literal move — but the widened
  grammar means either name now reaches every destination the other
  does.)* `--to` accepts `user` or `skill:<name>`, resolved
  against the registered `skills_root` (a typo or an unregistered root
  refuses, never silently creates a bucket). **Same as `rehome` now**
  *(amended 2026-08-28, see the byte-untouched-apart-from-`scope:`
  amendment above)*: the scope literal lives in frontmatter and
  `bucket_dir_for_scope` maps `scope → bucket`, so a record whose
  `scope:` disagrees with its bucket is exactly the corruption this
  verb exists to repair — `rescope` rewrites `scope` to
  match the destination in the same `git mv`-then-write motion
  `resolve_record` uses (mv first, so a kill leaves a loudly-blocked
  staged rename that `reconcile` refuses to auto-commit, never a
  silently-committable modified file — the mv-first ordering is the
  point). `status`, `sightings`, `evidence`, `deferral` metadata, and the
  body all ride unchanged; a deferred record re-scopes and stays
  deferred. **Proposal siblings are SWEPT, never carried** — the same
  Y-18 decision `rehome` already made, re-affirmed on fresh evidence: a
  scope-only edit does not change `record_sha` (scope is frontmatter,
  not body), so a carried proposal would render an honest-looking stale
  card reasoning from the wrong scope. **The sweep is DISCLOSED** —
  the same behavior `rehome` now has too *(U-verbs `MOVE6`, amended
  2026-08-28: `rehome`'s sweep used to be silent, no longer is)*: when
  the sweep removes at least one file, the
  human-facing output gets one line naming the non-zero swept components
  (`swept 1 proposal — lrn-… will be re-analyzed in skills/<name>`; a
  component at zero is never named, and nothing swept means no line at
  all), and the commit body records every swept path. One ledger commit,
  pinned subject `self-learn: rescope lrn-… → skills/<name>` or `→ user`;
  `--note` rides the commit body only (rescope is not a resolution).
  Refusals, each checked on **status, never mere existence**, and — for
  the source scope — on **the bucket, never the record's `scope:`
  field** (a scope↔bucket disagreement is repaired by this verb, not
  refused on the strength of the field the corruption lives in): unknown
  id · not pending/deferred · `--to` unparseable, an unregistered
  project, or an unknown/ambiguous skill name (no skills root
  registered) · target == source (same bucket) · id already present in
  the target bucket, `pending/` OR `resolved/` (F4). *(Amended
  2026-08-28 — U-verbs §3.2, ruling R1: the three scope-partition
  refusals that used to open this list — source in a `projects/*`
  bucket, `--to == project`, `skill → skill` — are GONE; `rescope`
  reaches project buckets exactly as `rehome` does, via the same
  shared resolver.)* `meta.yaml` stamped **IFF the target is a project
  bucket** *(corrected 2026-08-28, code gate r2, N-r2-1 — the widened
  grammar above means a `rescope --to <project>` now stamps one, same
  rule `rehome` always used — MOVE2; only a `user`/`skill:<name>`
  target carries no `meta.yaml`, since those buckets carry no project
  identity to stamp)*. No telemetry event — `EVENT_KINDS` is a closed set,
  the sibling verb `rehome` emits nothing either, and git is already the
  provenance record. Not agent-proposable in M1 — human-CLI-only, and
  does not join the pane's closed proposable-verb list.
- **Every resolution verb refuses on status, never mere existence —
  generalized 2026-08-27 (FW-51, u-verbguards)**: `route`/`reject`/
  `defer` need the record `pending` or `deferred`; `graduate` and
  `supersede` (BOTH the old and the new side) need `pending`,
  `deferred`, or `routed` — a `supersede` also refuses when the new
  side's `superseded_by` chain would trace back to the old side (a
  cycle), and refuses outright when old and new are the SAME record
  (a direct self-cycle the chain-walk alone cannot see, since a live
  record's own `superseded_by` is `None`). `confirm-held` /
  `confirm-recurrence` / `dismiss-suspect` / `followup-done` need
  `routed` — the criterion for needing this precondition is whether
  the verb's correctness is GATED ON status, never whether the verb
  happens to WRITE `status` itself (code gate r1 correction:
  `followup-done` never mutates `status`, but its own docstring always
  said "Clear a ROUTED record's follow-up" — measured, it cleared a
  stale follow-up on an already-superseded record just the same, since
  nothing enforced that docstring).

  One shared precondition, `ledger_ops.require_status`, resolves the
  record across BOTH `pending/` AND `resolved/` (never "not found"
  merely because the status makes the verb illegal — the lie
  `route`/`reject`/`defer` used to tell for a resolved record) and is
  consulted by `resolve_record` itself, closing the hole at its root
  rather than per-verb. `confirm-held`/`confirm-recurrence`/
  `dismiss-suspect` route through the SAME helper via its `reason`
  kwarg, which overrides only the message TAIL — their pre-existing,
  differently-worded refusals stay byte-identical (pinned verbatim by
  `test_dismiss_suspect.py`); `followup-done` takes the helper's
  generic message, being a new guard with nothing pinned to preserve.
  `rehome`/`rescope` are the one deliberate exception: their predicate
  is the BUCKET (directory) AND status together, not status alone
  (Y-18/u-rescope, above), and their refusal wording is pinned
  verbatim by `test_rehome.py` — left as their own inline checks, not
  routed through `require_status`.

  The refusal fires BEFORE any lock or mutation, is exit **1** (never
  64 — 64 stays reserved for a record that genuinely does not exist;
  `self-learn host commit-drift`'s unrelated 64 "not found" is a
  different, host-family verb, 64-mapped by design, and stays out of
  this pin's scope), and names the record's actual status. FW-51 was
  the measured gap: `reject A` then `graduate A` used to rc 0 and
  silently invert the human's denial into `superseded_by: canon` — 14
  §6a has the dated disposition and the full before/after.
- **`kind` drives routing, not decay.** Gen 1 gave `kind` decay clocks and
  injection priority; those needed the statistical layer. What remains is
  its routing value: anti-pattern → hook candidate · surface-rule → SKILL.md
  rule · reasoning-pattern → SKILL.md/CLAUDE.md prose.
- **Dropped from gen 1, deliberately:** `confidence` (source + sightings
  carry the trust story at this volume), `classification`
  (defect/preference/user-error — triage routing *is* the classification:
  preferences route to CLAUDE.md/user scope, user errors get rejected),
  `surfaced_count`/`recurrence_count`/`reputation`/`applied_count` (v2 gate
  G-1; nothing at n=1 can measure them honestly), `topic` (the quarantine
  key without a quarantine machine; clustering compares full records),
  seven-state status machine (`quarantined`/`contested` go with G-1).

## 3. Storage layout

```
plugins/<p>/skills/<s>/.self-learn/
  pending/lrn-*.md          # awaiting triage (deferred records stay here,
                            #   hidden until their deferred_until passes)
  resolved/lrn-*.md         # routed | rejected | superseded (terminal-ish)
  proposals/lrn-*.yaml      # worker analyses (+ lrn-*.diff previews)
.self-learn/                # repo root: project + user scopes, same shape
```

*(Added 2026-09-13, S-65 — the steward/overseer build, `_LAYOUT` in
`ledger.py:31` widened; "create if missing", never "refuse if missing" on an
older home):*

```
<ledger>/
  cases/<yyyy-mm>/case-<8hex>.md   # decision cases (§3a); one per decision
  user-statements.jsonl            # append-only; the user's own words (§3a)
  user-model.md                    # the model of the user (§3a)
  overseer/{<date>-report.md, latest-report.md, coverage.yaml,
    open-questions.yaml, evaluation-<date>.md}   # the overseer's own
                                    # subtree, owned by the overseer plan
```

(Full shape of the `overseer/` subtree — this fence names only the files —
is the same list `13-hosting-and-separation.md` §3's own K1 delta carries;
the contract is one list, described twice for readability, not two lists.)

- **In-repo** → autosynced across machines, versioned, `git blame`-able.
- **Record-per-file** → atomic writes, no merge conflicts between concurrent
  writers, and directly readable by any future UI without a serving layer.
- `pending/` → `resolved/` is a `git mv` at resolution time (routing,
  rejection, supersession), so the pending directory listing *is* the queue
  — minus deferred records whose `deferred_until` is still in the future —
  with no index to maintain or corrupt. *(Draft 1 called this directory
  `routed/`, which misnamed the rejected and superseded records it also
  holds.)* Resolution also `git rm`s the record's proposal siblings
  (`proposals/lrn-<id>.{yaml,diff}`) — the M2 digest reads `resolved/`
  records and resolving commit messages, never stale proposal files
  (implementability review 2026-07-12).
- Transient state (worker locks, run markers, coalescing timers) lives in
  the per-home cache dir `${XDG_CACHE_HOME:-~/.cache}/self-learn/
  home-<sha256(resolved SELF_LEARN_HOME)[:8]>/`, never in the repo.
  *(Paths re-based 2026-07-17 per doc 13 §6/H-4 — the cutover moved
  `~/.cache/claude-skills/self-learn/` → `~/.cache/self-learn/…` in
  code 2026-07-16 but this line was not swept then; 09 §11 Y-3 is the
  surface-side consumer.)* *(G-3
  addition, 2026-07-12 — 09 §3/§10; revised same day with the platform
  re-decision, 09-surface-spec.md:)* the adjudication surface follows
  suit — `ui.log` and the compiled `pane-doctrine.md` live there; its
  runtime bearer token lives under `$XDG_RUNTIME_DIR/self-learn/`
  (`ui-token`, 0600 — runtime secrets belong in the runtime dir, not
  the cache; replaces the TUI revision's socket entry — the socket
  subsystem was deleted with the platform change).

  *Amended 2026-09-13 (O-3/O-4, overseer build):* the overseer adds two
  items to this same cache dir, both transient — `overseer.journal` (the
  same append-only journal shape the miner's own `<cache>/…/journal` already
  uses, one line per run) and the overseer's own schedule-state file,
  beside the mine schedule state `serve.py` already keeps there (the same
  `_target_for`/`_recently_attempted` shape, one weekly target instead of
  one nightly one). Neither is repo truth; both are rebuildable from the
  ledger's own `overseer/` subtree and the case index.

  No new state
  locations. **The autosync
  pause sentinel is part of this contract** *(the one cross-repo interface;
  implementability review 2026-07-12)*: path
  `${XDG_CACHE_HOME:-~/.cache}/self-learn/autosync-pause` (a machine
  singleton — deliberately NOT home-namespaced; it pauses the host
  repo's autosync machine-wide; path per 13 §6, matches
  `sentinel.py`); contents one
  informational line (`pid=… host=… started=…`) — **semantics ride the
  file's mtime only**: the sentinel is *live* iff mtime is younger than the
  2 h TTL; every mutating CLI invocation re-touches it (that is the
  heartbeat); `claude-skills-sync` (main repo) checks it at top-of-run and
  exits 0 without committing while live — the watcher inherits the check
  because it only ever calls sync. A stale sentinel is ignored and may be
  deleted by either side.
- The format is znote-compatible (md + frontmatter) by design; a znote
  backend (v2 gate G-5) is a relocation, not a migration.

## 3a. Cases, statements, and the user model

*Added 2026-09-13, S-65 — the steward and overseer build. Three new
ledger-truth files and the rules for them, plus one line for the overseer's
own subtree.*

### 3a.1 The ledger content contract

1. `<ledger>/cases/**` (including committed delegated-run manifests at
   `<ledger>/cases/runs/<run_id>.json`), `<ledger>/user-statements.jsonl`,
   `<ledger>/user-model.md`, and `<ledger>/overseer/**` (the overseer's own
   subtree — reports, the coverage record, open questions, evaluations) are
   ledger truth: written only under `intents.ledger_write`, committed in the
   same section, secret-scanned before commit, never edited by an agent's
   file tool — each agent's write scope is its own run's stage directory;
   the CLI copies validated content in.
2. Free text is allowed in these files and nowhere else new. Within
   `overseer/**`, the report and evaluation files carry prose about *what
   was examined and decided* — ids, counts, and dates, drawn from cases and
   receipts already committed — never a lesson's body text or a transcript
   span; `coverage.yaml` and `open-questions.yaml` carry no free text at
   all (structured records only), matching the content discipline
   `11-telemetry-and-lifecycle.md` §4.4 already states for telemetry.
3. Sections 1–4 of a case are frozen at commit; sections 5–6 are
   append-only; a change of decision is a **successor case**, never an edit.
4. `provisional` means only "the user has not yet seen it" (§3a.2, §3a.4).
   On a **case** it is derived and never stored: `actor != human` and no
   `presented` entry covers its decision. On a **user-model entry** it is a
   stored field, written `true` by the steward or overseer and flipped to
   `false` only by the presentation record that lists the entry in its
   `entries` (§3a.2); nothing else flips it, and no run re-derives it. The
   case index and the steward's reconsider queue
   (`<cache>/steward/reconsider-queue.jsonl`) are cache, not truth.
5. Attribution draws from one list, `{human, steward, overseer, analyst,
   agent}`: `actor` on a case, `recorded_by` on a statement, `updated_by` on
   the user model, and `by:` on every sheet item, permitted on every
   resolution verb, not `route` alone (U3).
6. The worker's rejected-proposal digest (`worker.py:1549-1618`, built from
   `git log --grep '^self-learn: reject '`) attributes every entry with its
   decider (`human | steward | overseer`) and the rejected reason; the
   analyst prompt's "Never re-propose" wording is dropped in favour of "Prior
   decisions on this record's class, as cases:" (with case ids and outcomes,
   `misc/audit-2026-09-02/steward-design/plan-steward-2026-09-12.md:538`).
   Until this lands, the overseer withholds the digest from its own prompts.
7. `graduate`/`superseded_by: "canon"` are read as legacy: `graduate` decides
   the same status this section calls **retire**, and the literal `"canon"`
   is read as a `covered_by:` reference with the covering surface
   unrecorded. See §2's amendment note on `superseded_by` for the field's
   two live shapes.

### 3a.2 Decision-case record

```
<ledger>/cases/<yyyy-mm>/case-<8hex>.md
```

One file per decision. `<yyyy-mm>` is the month the case was opened;
`<8hex>` is the first eight hex digits of a random 128-bit id, the same
shape as a record id, so the record-id pattern's sibling validates it. The
file is committed by the CLI in the same locked section that applies the
decision; git history is the case's own change log, never a field inside it.

YAML frontmatter plus six fixed Markdown sections, in this order:

| # | Section | Frozen? | Who writes |
|---|---|---|---|
| 1 | `## Identity and scope` | yes | the deciding actor, at decision time |
| 2 | `## Evidence` | yes | same |
| 3 | `## Decision` | yes | same |
| 4 | `## Dependencies` | yes | same |
| 5 | `## Application` | append-only | the CLI, from executor receipts |
| 6 | `## Later observations` | append-only | the CLI, on behalf of the overseer, a human, or a later steward run |

"Frozen" is mechanical: the frontmatter's `decided_sha256` is the SHA-256 of
sections 1–4 exactly as committed; a later append re-hashes them and refuses
if they differ. A change of mind is a successor case, never an edit.

```yaml
---
case: case-3f9a1c2e            # id; file name matches
opened_at: 2026-09-13T03:41:00Z
actor: steward                 # human | steward | overseer (closed set; no alias)
run_id: st-20260913-0341-7b1c  # the run that wrote it; null for a human case
records: [lrn-08ed825b]        # every lrn-… this case decides about
kind: resolution               # resolution | maintenance | parked | reconsider
trigger: nightly               # nightly | reconsider | maiden | human | weekly
outcome: reject                # route | reject | defer | retire | replaced |
                                #   rehome | revise | no-action | parked
supersedes: null               # case id this one replaces, else null
superseded_by: null            # filled by the CLI when a successor lands
parked_for: null               # overseer, always (only when kind: parked)
parked_reason: null            # hook | always-loaded-user-scope |
                                #   broad-removal | authority-unclear |
                                #   scope-conflict | plain-host-committed-file |
                                #   attempts-exhausted
                                #   (closed set; only when
                                #   kind: parked)
decided_sha256: "a3c1…"        # hash of sections 1-4 as committed
presented: []                  # scoped presentation records, see below
---
```

**Section 1, Identity and scope:**

```
- records: lrn-08ed825b
- scope: project:/home/…/dotfiles
- question: <one sentence: what is being decided>
- trigger: nightly | reconsider | maiden | human | weekly
```

**Section 2, Evidence** — every item is a reference plus a verbatim quote (a
few lines at most); no paraphrase-only evidence. The reference is one of:

| Evidence kind | Reference grammar |
|---|---|
| ledger record body or proposal | `ledger@<commit>:<path>#L<a>-<b>` |
| transcript line | `transcript:<session-id>#L<n>` |
| a line typed into the overseer conversation | `conversation:<obs-id>` (the `presented` observation's id, below) |
| a canon or reference file | `file@<commit>:<path>#L<a>-<b>`, or `file:<path>@<mtime-iso>` for untracked files |
| an output style | `file:~/.claude/output-styles/<name>.md@<mtime-iso>#L<a>-<b>` plus `cond:surface.output-style.active` |
| a user statement | `stmt-<8hex>` (§3a.3) |
| a user-model entry | `um-<4hex>@r<n>` (§3a.4) |
| a condition | `cond:<key>@<observed_at>` (§3a.5) |
| telemetry | `telemetry:<event-id>` |
| a prior case | `case-<8hex>` |

**Section 3, Decision** — free text, with these labelled lines first:

```
- verb: retire
- covered_by: output-style:shared-context   (retire only: claude-md:<path> |
                                              skill-md:<name> |
                                              reference:<file> |
                                              output-style:<name>)
- because: <the deciding reason, one or two sentences>
- confidence: settled | provisional   (provisional ⇒ section 6 must
                                        eventually carry a presentation)
```
followed by "What would change this decision" (one to three bullets). The
deciding actor writes reasons, not votes.

**Section 4, Dependencies** — everything the decision rests on, each cited
from the evidence table:

```
- statements: [stmt-…]
- user_model: [um-…@r…]
- conditions: [cond:…]
- capabilities: [FW-163]     (a forward-work row id where one exists, else a
                               settings key such as models.steward)
```

**Section 5, Application** — appended by the CLI from the executor's
receipts, never by an agent. One line per sheet item, including items the
executor never reached:

```
- 2026-09-13T03:44:03Z sheet=01.yaml item=1 lrn-08ed825b reject → applied (exit 0)
- 2026-09-13T03:44:03Z sheet=01.yaml item=2 lrn-e8b13ee8 defer → not-attempted (stopped_at=1, code 6)
```
Receipt states mirror `ItemResult.state` (`applied | already-applied |
refused | stopped`) plus `not-attempted`, for items after `stopped_at`.

**Committed delegated-run recipe and continuation.** A delegated runner
that may need to survive interruption commits one JSON manifest at
`cases/runs/<run_id>.json`. Version 1 binds the runner-owned `run_id`, its
starting ledger commit and selected input blob/version identities, packet
membership, reconsider-observation ids, invocation/repair bookkeeping, and
outstanding or terminal dispositions. Before publishing a case, it also
commits that case's reserved id, validated and secret-scanned case input,
the exact effective sheet bytes, the existing eight-hex `sheet_sha`, the
full SHA-256 digest, and each original item ordinal/id/verb. Supported
time-dependent defaults are frozen in that effective sheet. Maintenance
instructions remain in the same committed recipe. Invalid or secret-bearing
prepared output publishes no manifest, case, or Application entry.

The version-1 object has this core shape (the runner may add
versioned bookkeeping fields, but may not rename or weaken these bindings):

```json
{
  "version": 1,
  "run_id": "run-...",
  "actor": "steward",
  "start_head": "<40-hex ledger commit>",
  "inputs": [
    {"path": "<ledger-relative>", "blob": "<40-hex>", "version": "<source version>"}
  ],
  "reconsider_observations": ["obs-<8hex>"],
  "cases": {
    "case-<8hex>": {
      "sheet": "<exact effective YAML bytes>",
      "sheet_sha": "<8-hex>",
      "sheet_digest": "<64-hex>",
      "items": [{"n": 1, "id": "lrn-<8hex>", "verb": "reject"}],
      "maintenance": [],
      "dispositions": []
    }
  },
  "ledger_effects": [
    {
      "case": "case-<8hex>", "sheet_sha": "<8-hex>",
      "sheet_digest": "<64-hex>", "item": 1,
      "record": "lrn-<8hex>", "verb": "route"
    }
  ]
}
```

The `cases` mapping key is the reserved case id. `inputs` and
`reconsider_observations` may be empty; `ledger_effects` starts empty and is
otherwise populated only by the compound-commit rule below. Each disposition
names its original instruction key and one of the states described next; it
does not substitute a new item number or a cache-local phase flag.

The manifest records executable instructions and unfinished obligations; it
does not replace the case or its Application section. Application remains the
receipt. Completion is checked against every expected original
`(sheet_sha, item)` key. Dispositions distinguish applied-and-receipted,
pending retry, parked with a committed case reference, refused with reason
and input version, abandoned with a durable successor/redecision obligation,
and visible unresolved evidence. A partially receipted sheet or unfinished
maintenance/packet remains unfinished. A legacy case without a committed
recipe is reported as an unknown execution-evidence gap; no sheet, success,
or receipt is invented from cache.

**Attempt counting, close-out, and the failure detail** *(added 2026-09-19,
`03-decisions.md` S-68).* Attempts are counted on the unit of work that can
actually be retried — a steward packet, an overseer sheet item, an overseer
week — not on the run as a whole. Each such unit carries, in the manifest:

```json
{
  "attempt_count": 2,
  "last_attempt_at": "2026-09-19T04:15:07Z",
  "progress_at": "2026-09-18T03:41:22Z",
  "failure": "exit",
  "failure_detail": "API Error: 400 …"
}
```

- `attempt_count` increments once at the START of every attempt, before the
  first model call, so an attempt that makes zero calls, raises, or is killed
  still counts. An attempt that finishes without PROGRESS (S-68's first
  definition) counts exactly like one that failed.
- **A run that HOLDS before taking ownership of a unit is not an attempt**
  and increments nothing: a disabled switch, a STOP refusal, a lock another
  process holds, a week the same-week guard finds already done, and a raise
  inside an "is it due?" check all leave every count untouched, so neither a
  wedged lock nor a wedged git can exhaust a cap and park work nobody
  examined. Such a hold may still arm the scheduler's cache-side cooldown —
  a raised due-check does, so the tick loop cannot spin on it (S-68) — but it
  never touches a count in this record.
- `last_attempt_at` is written by that same increment and is what the
  scheduler's cooldown reads; a value that is unparseable or in the future
  reads as "attempted now", never as "due every tick" or "never due".
- `progress_at` is the time of the last attempt that made progress, and is
  what a later run compares against to tell a retry apart from a loop.
- `failure` is the kind, and it reuses the literals the runner already writes
  rather than a second vocabulary: a `FAILURE_KINDS` member (`exit`,
  `timeout`, `not-found`, `os-error`, `unavailable`), `invocation` (a failed
  call that named no kind), `turns` (the turn bound. In the steward's
  record it means Claude Code itself stopped the session at its turn limit
  and said so — result subtype `error_max_turns` — and is never inferred
  from a reported turn count, which counts something else: revision log,
  2026-09-20. In the overseer's record it is still the overseer's own
  guard over the reported count, `overseer.max_model_calls`, unchanged),
  `schema-repair` (a
  second staged-output validation failure), and one genuinely new value,
  `no-progress`, for an attempt that ran and moved nothing. A ledger stop
  keeps riding the run record's own numeric halt code — the overseer's run
  record names it `halt_code` *(field named here 2026-09-19, U4; written by
  `overseer/run.py` since U3)*, an integer drawn from the closed set the
  runner accepts, `3` (push failed, the commit landed), `4` (rebase
  conflict), `5` (no ledger home), `6` (git failed before any mutation —
  nothing was written), `7` (half-written — the write landed, its commit did
  not), `8` (batch partial — some items applied), and `null` for a stop
  whose code falls outside that set; a code is
  never folded into this field. `failure_detail` is the message the transport or
  the validator actually returned, at most 2,000 characters (truncated with a
  trailing ellipsis) and secret-scanned on write. A scan hit REDACTS the
  detail to `<redacted: secret-scan>` and the attempt record still commits
  with its kind and counts: a trace is never suppressed by its own content,
  because a failure whose reason lives only in the git-ignored cache journal
  is the state this field exists to end.
- An overseer run additionally carries `week` — the local date of the Sunday
  04:15 boundary that opened it — and, when the cap closed it,
  `status: closed` with `outcome: attempts-exhausted`. The week is done
  because the run record says so; coverage cannot say it, since coverage does
  not advance on a failed attempt. An overseer attempt that fails before it
  has a run record — every failure of the first model call, and every phase-B
  refusal — has nowhere else to put its trace, so it commits one note per
  attempt under `overseer/failures/<week>/`, and the close-out's own note is
  `overseer/failures/<week>/closed.md`. The week's attempt count is those
  notes plus the run record's `attempt_count`; the two sources are disjoint,
  because an attempt that reaches the run record writes its reason into the
  record's `failure`/`failure_detail` instead of a note.

A run record written before this rule has no `attempt_count`, and one is
never invented for it: its count is DERIVED from the evidence the record
already carries — for a steward packet, the number of rows of kind
`decision` in that packet's own `attempts` list — and the first attempt made
under this rule writes the explicit field. This is not a migration nicety:
the run left stuck on 2026-09-14 is exactly this shape (three packets, one
`decision` attempt each, `last_attempt_at` null), and it has to be
re-attempted and counted by the product itself, never carried to a terminal
state by hand-editing committed JSON.

Writing the close-out is itself an ordinary ledger write and can fail like
one. A close-out that fails — the steward's parked successor case, or the
overseer's close-out note and question — is retried by the next run, is
idempotent (a successor that already exists is reused, never duplicated), and
increments no count of its own. A unit becomes `abandoned`, and the run
closes, only once every abandoned item's `successor_case` actually exists.
Because it is retried without a count, no cap will ever stop a close-out
that fails the same way every time, and nothing else would surface it: so
a failed close-out is reported to the user **once per distinct cause** —
not once per run and not once per record — and the run's own report names
it beside the count of lessons still waiting for a successor.

The `abandoned` disposition named above has this shape, and is written only
by a runner reaching the cap, never by a model:

```json
{
  "state": "abandoned",
  "input_version": "<source version>",
  "attempts": 3,
  "reason": "<the real failure reason, the same text as failure_detail>",
  "successor_case": "case-<8hex>"
}
```

`successor_case` is the durable successor/redecision obligation this section
already requires, and it is never null for a steward abandonment: it is a
parked case (`kind: parked`, `parked_for: overseer`, `parked_reason:
attempts-exhausted`) that the runner writes, whose section 2 cites the
committed run record — `ledger@<commit>:cases/runs/<run_id>.json#L<a>-<b>` —
and quotes the failure detail as its evidence, and whose section 1 question
the runner writes mechanically: this record's decision reached the attempt
cap, so decide the lesson itself, using the recorded failure reason as
evidence. When the abandoned item already belongs to a case, the runner also
appends an `abandoned` later observation (§3a.2, section 6) to that case,
naming the successor. The overseer's own abandonment has no lesson of its own
to park: its durable obligation is a committed close-out note and the question
its report puts to the user, beside the closed run record above. **The runner
writes both, mechanically** — the cap is reached exactly when the model never
produced a report or a question of its own, so neither can be a model output;
how that runner-written question joins the proposition-keyed index
`overseer open` reads is the runner's own design problem, not a schema
question.

For an opted-in ordinary ledger mutation, the item's own mutation commit has
one canonical final trailer block: `By: <runner>`, `Case: <case-id>`,
`Sheet: <sheet_sha>`, `Item: <original-n>`. The manifest's full digest binds
the trusted continuation map; recovery requires exact case, digest, ordinal,
record, verb, ancestry, and committed-effect matching. The shared lookup seam
requires the final trailer block's exact identity and the pinned subject the
referenced verb writes for that record. Before a matching commit can make an
item proven and skipped, the delegated runner must additionally verify that
commit's content against the original item and its verb-specific ledger
effect. Trailer-shaped prose under a foreign subject, a matching present
status, `By:` alone, a cache SHA, an unrelated matching commit, conflicting
proof, or an intervening incompatible change proves nothing and causes
recover-or-refuse before dispatch.

An intent-backed compound mutation such as collapse adds one `ledger_effect`
proof entry to its run manifest inside the same existing transaction and
mutation commit. The manifest path is registered with `intents.add_step`
before it is changed; this is one additional registered path in the existing
intent, not an extension of the intent schema and not a separate progress
commit. A recovered commit is accepted only when it first introduces the
matching proof together with the compound ledger mutation.

Continuation reuses the original case, exact sheet bytes, short hash, full
digest, and ordinals. `batch.run` alone classifies and dispatches the
unproven suffix; it never reserializes or renumbers a remainder. Proven
successful items are skipped. A no-op, refusal, or owner-returned host
outcome is written to Application before the next dependent item dispatches;
failure of that ordered receipt checkpoint halts with the actual partial
batch result and untouched tail. A host-outcome verb (`route`, `reject`,
`retire`, `graduate`, `supersede`) that returned non-zero with the ledger's
HEAD unchanged wrote nothing — each commits its ledger leg before its host
leg — and is an ordinary refusal: receipted, and the sheet continues. One
that failed after its ledger commit landed halts the same way, with the
partial result and untouched tail, because its host obligation is
outstanding. A host result reconstructed after an
interruption names `recompile` as its source. A trailer proves only the ledger
leg and never authorizes repeating that leg or inventing a host exit code. If
`recompile` refuses an implicated target, the continuation carries that
ledger-proven item as `unresolved-host`, with the target and refusal reason.
`batch.run` skips the ledger leg, receipts
`unresolved-host: <target>: <reason>` before anything dependent can run, and
halts with the partial result and untouched tail in `BookkeepingHalt` so the
runner can report the outstanding host obligation.

**Section 6, Later observations** — append-only; each entry has an id
(`obs-<8hex>`), a timestamp, an actor, a kind, and text, some kinds also a
reference. Kinds: `examined | presented | statement | corrected |
dependency-moved | reconsider-queued | abandoned`. A `statement` or
`dependency-moved` observation whose reference is one of the case's own
section-4 dependencies makes the CLI enqueue the case for the steward's next
nightly run (a `kind: reconsider, trigger: reconsider` case, run through
`reconsider`); the queue itself is cache, rebuildable from the observations.

**Two views.** `case show --evidence-only` is **blind by default** (no
separate `--blind` flag): frontmatter reduced to exactly `case`, `opened_at`,
`actor`, `kind`, `records`, and `supersedes` (an allowlist, so
`presented`, `outcome`, `superseded_by`, `parked_for`, `parked_reason`, and any
key added later stay out unless named here — amended 2026-09-14 after a
denylist let `presented` through; `scope` is section 1's own body text, never
a frontmatter key, and stays visible there in this same blind view); sections
1, 2, and 4 only — neither the
reasoning, the verb, nor the receipts (which name the verb) reach the
reader. `case show` (no flag) is the full view, everything. The overseer
reads the evidence-only view first, by tool, so "evidence before rationale"
is a property of the CLI, not of a prompt.

**`provisional`** is derived, never stored: a case is provisional when
`actor != human` and no `presented` entry covers its decision (`covering`
∈ {`decision`, `all`}) —
`provisional = actor != "human" and not any(p.covering in ("decision",
"all") for p in presented)`. A presentation with any outcome clears it —
seen is seen; what the user said, if anything, lives in the presentation's
own `outcome` and in the statement it produced, never in the flag. A
`presented` entry is written only by the operation that actually displayed
that content, with `covering` naming what was shown: a case whose id is
merely cited in a question, a report, or a user-model entry the user was
shown is not thereby presented, and showing a system reading does not
present every case that depends on it — `overseer open` records a
presentation only for the content it printed, never for every case a
question cites:

```yaml
presented:
  - id: obs-…
    at: 2026-09-20T18:10:00Z
    to: human
    covering: decision       # one of: decision | dependencies | all
    entries: [um-…]          # user-model entries displayed with the case; each one's stored provisional flips to false
    outcome: agreed | corrected | noted | declined
    via: overseer-conversation | review-ui | teach | cli
```

**A parked case** has `kind: parked`, `outcome: parked`, `parked_for:
overseer` (always — a values call the overseer cannot settle is raised in
its own conversation with the user, never parked for a human by the
steward), a `parked_reason` from the closed set above, sections 1/2/4
filled, and section 3 holding the question and the steward's tentative
answer if any. The overseer decides it in the user's stead as a **successor
case** (`actor: overseer`, `supersedes: <parked case>`); the parked case
gets `superseded_by`. Parking never installs a standing belief.

Two reasons in that closed set are written by a runner rather than chosen by
the steward: `plain-host-committed-file`, and `attempts-exhausted` *(added
2026-09-19, S-68)*, which a runner writes when a record's decision reached
`runs.attempt_cap` attempts without ever being decided. Such a case asks the
overseer the same thing any other parked case does — decide the lesson
itself — with the recorded failure reason as its evidence rather than a
values question; what stopped the steward was the machinery, not the merits.

**The index**, `<cache>/cases/index.json`, is rebuildable, not truth (a
`NOT_REPO_TRUTH` disposition): `case, opened_at, actor, kind, trigger,
outcome, records[], supersedes, superseded_by, parked_for, parked_reason,
provisional, presented_count, dependency_refs[], last_observation_at`. The
overseer samples from it and never rereads the catalogue.

### 3a.3 User-statement store

```
<ledger>/user-statements.jsonl
```

Append-only JSON Lines; nothing is ever rewritten in place. A correction is
a new line naming the line it amends.

```json
{"id": "stmt-2b7e91c0",
 "at": "2026-09-12T17:47:00-07:00",
 "verbatim": "cost-sensitivity was a symptom of a broken pipeline",
 "answers": {"kind": "proposition", "ref": "um-00a3@r1", "text": "load cost dominates"},
 "source": {"message_ref": "transcript:9c1e…#L412", "surface": "conversation"},
 "scope": {"level": "user", "host": null},
 "uncertainty": "said in passing while affirming a design note",
 "recorded_by": "steward",
 "amends": null}
```

- `verbatim` is the user's words, unedited; secret-scanned on write, refused
  if it trips.
- `answers.kind` ∈ `proposition | question | instruction`; `answers.ref` is
  the thing it answers (a user-model entry, a case, a record, or null).
- `source.message_ref` is `transcript:<session-id>#L<n>` (the miner's own
  grammar, for words found in a transcript) or `conversation:<obs-id>` (for
  words typed into the overseer conversation, where no transcript line
  exists at record time — `<obs-id>` is the `presented` observation the
  reply answers). Dedupe key: `(source.message_ref, verbatim)`.
- `scope.level` ∈ `user | project`; `scope.host` is a registered host path
  when `project`.
- `uncertainty` is the recorder's doubt about what the words *mean*, kept
  beside them, never inside them.
- `recorded_by` ∈ `human | steward | overseer` — whoever captured the words
  records them, the steward included. An agent records a statement only
  with a `transcript:` or `conversation:` reference, never from memory of a
  conversation.
- `amends` is a `stmt-…` id when this line corrects an earlier one; readers
  follow `amends` chains to the newest line.

A reading of a statement is a user-model entry (§3a.4) that cites the
statement id, or a case dependency that cites it — the statement line
itself never grows an "interpretation" field.

### 3a.4 The user model

```
<ledger>/user-model.md
```

**Vocabulary, binding for every entry and every document describing one.**
The words "ratified", "ruled", "stated", and "contradicted" are never used.
Every entry carries `held_since` (the date held from), `because` (the
reason), `conditions` (the feed keys, §3a.5, it depends on), `status`
(`CURRENT` or `LAPSED` — a LAPSED entry carries `lapsed_at` and
`changed_condition`, naming the condition that changed, the contrary
evidence's reference, or `consolidated-into:um-…`; nothing lapses for lack
of a reply), and `source` — one of `own-words` (a verbatim quote with a
`stmt-…` reference, recorded by whoever captured it, the steward included)
or `system-reading` (the system's reading of an episode, with a case or
telemetry reference and at least one `stmt-…` it is a reading of;
`provisional: true` means only "the user has not yet seen it", the same
derivation §3a.2 states for a case). **There
is no `review_by` field and no expiry** — this is the mechanical half of
D6 (nothing lapses for silence): an entry is never deleted and never
edited into a different claim — a change is a LAPSED status with its date
and cause, or a new entry.

One Markdown file, YAML frontmatter, five containers grouping entries by
source (the grouping adds no meaning of its own):

```yaml
---
revision: 7
updated_at: 2026-09-13T21:00:00Z
updated_by: human           # human | steward | overseer
---
```

| Container | Holds | Who may add | Who may mark LAPSED |
|---|---|---|---|
| `## A. From the user's own words` | `own-words` entries | human; steward or overseer, with a `transcript:` or `conversation:` reference | human; steward or overseer, naming the changed condition or contrary evidence |
| `## B. System readings the user has seen` | `system-reading, provisional: false`; ≥1 `stmt-…` each | nobody directly — an entry moves here when a presentation record names it in `entries` (§3a.2) | steward, overseer, human |
| `## C. System readings, provisional` | `system-reading, provisional: true`; ≥1 `stmt-…` each | steward; overseer, including a consolidation of two or more entries into one, with a `basis` citing the lapsed entries and their statements | steward, overseer, human |
| `## D. Observed regularities` | system readings whose reference is telemetry or receipts rather than one episode; `provisional` as above; ≥1 `stmt-…` where the regularity is about a preference, else the telemetry refs alone | overseer | overseer, human |
| `## E. Declared conditions` | facts about the environment no probe observes (§3a.5) | human; steward or overseer with an own-words reference | human; steward or overseer, when the feed starts observing the key |

One entry, and the same entry after its condition clears:

```
### um-00a3 — load cost dominates          (r1)
- held_since: 2026-08-14
- because: the pipeline was misrouting lessons and the always-loaded file had no cheaper neighbour
- conditions: [report.destinations, report.reference_shelf]
- status: CURRENT
- source: system-reading; ref: <August review-model note>; statements: [stmt-…]; provisional: true

### um-00a3 — load cost dominates          (r2)
- held_since: 2026-08-14
- because: (unchanged)
- conditions: [report.destinations, report.reference_shelf]
- status: LAPSED
- lapsed_at: 2026-09-20
- changed_condition: report.destinations   (misrouting cleared; a cheaper neighbour surface exists)
- source: system-reading; ref: <August review-model note>; statements: [stmt-…]; provisional: true
```

An own-words entry:

```
### um-00b1 — cost-sensitivity was a symptom          (r1)
- held_since: 2026-09-12
- because: (the user's words) "cost-sensitivity was a symptom of a broken pipeline"
- conditions: []
- status: CURRENT
- source: own-words; ref: stmt-2b7e91c0; recorded_by: steward
```

A consolidation written by the overseer (container C's own-only-action
clause above, worked example):

```
### um-00c4 — correct-then-land          (r1)
- held_since: 2026-09-27
- because: two readings said the same thing from two episodes: fix the root cause, then land
- conditions: []
- status: CURRENT
- basis: [um-0012@r1, um-0019@r2]; statements: [stmt-…, stmt-…]
- source: system-reading; ref: case-…; provisional: true
```
with `um-0012` and `um-0019` marked `LAPSED`,
`changed_condition: consolidated-into:um-00c4`.

`um-<4hex>` ids are stable for the life of the entry; every write that changes
the claim bumps its `r<n>` (a presentation flipping `provisional` is not a
change of claim), so "did the dependency move" is a revision comparison, not
a diff of prose.

### 3a.5 Conditions feed

A block of facts about the world *as of this run*, assembled by code and
handed to the deciding agent with its prompt — never stored as a snapshot;
a case records only the items its decision relied on, each with its
`observed_at`, so the overseer can re-observe the same key later and
compare. Importable as `conditions.feed(home) -> list[Item]`, `Item = (key,
value, observed_at, source)`.

| Source | Keys |
|---|---|
| `self-learn report --json` | `report.buckets`, `report.destinations`, `report.routed_live`, `report.open_followups`, `report.recurrence_suspects`, `report.deferred`, `report.reference_shelf`, `report.context_budget`, `report.surface_reach` |
| `self-learn status --json` | `status.total_pending`, `status.unanalyzed_total`, `status.intents_probe`, `status.intents_stopped_count` |
| `hosts.yaml` | `host.<path>.mode`, `host.<path>.claude-md` (after FW-163) |
| settings | `models.worker`, `models.miner`, `models.analyst`, `models.steward`, `models.overseer`, `sdk.max_turns.*` |
| `~/.claude/settings.json` `outputStyle` | `surface.output-style.active` — output styles are a canon surface that can already contain a lesson; self-learn reads them and never writes to them |
| user-model container E | `declared.<key>` |
| the steward's own last run | `steward.last_run_at`, `steward.last_run_outcome`, `steward.cases_since_overseer` |
| the overseer's own last run | `overseer.last_run_at`, `overseer.last_examined_at` |
| git | `ledger.head`, `repo.head` |

Withheld on purpose: lesson bodies (they arrive through the worker's brief,
not the feed), telemetry event text (counts and ids only), transcript text.

## 4. Managed sections (the compile targets' contract)

Compilers own exactly the region between their markers, and nothing else:

```markdown
<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->
- **When about to edit `.storage/*.json` while HA runs:** stop the container
  first — HA rewrites `.storage` on shutdown. *(lrn-4c1e9a2f)*
<!-- self-learn:end -->
```

Rules: entries are one tight line each, carrying the record id for
provenance; the compiler regenerates the whole section idempotently from
`resolved/` records routed to it; text *outside* the markers is never
touched. **Bootstrap rule** *(implementability review 2026-07-12 — no
target file has markers today, so the very first route hits this)*: on the
first route to a target with no markers, the compiler appends the marker
pair at end-of-file and proceeds; `--selftest` flags only targets that
*should* have a section (≥1 record routed to them) but lack markers. Entries are **trigger-first** — "**When ⟨trigger⟩:** ⟨instruction⟩",
never a bare imperative: the record's `## Trigger` section exists precisely
to be compiled this way, and a rule that names its firing condition is one
the model can recognize *in the moment* (Devin's trigger-description
precedent, E-20; free discipline, enforced by the compiler).

**Budget reporting (U-cap, retiring the old Overflow rule):** the compiler
counts entries and words inside a managed section
(`SectionResult.entry_count` / `.word_count`) and applies every entry
**unconditionally** — there is no threshold, no cap, and nothing here is
ever refused, dropped, or gated. Loaded-surface budget is still the scarce
resource (E-6: ≥60% of preloaded skill content is attention dilution), but
a mechanical cap converted a *measured* cost into an *unmeasured* one the
moment it pushed content onto `reference` (risk transfer into the region
where failure is silent) — so the counts feed a **report-only context
budget** instead: `report --json .context_budget` carries four signals
(`budget`, `crowding`, `composition`, `growth`) plus two conditional
arrival verdicts (`conditional.reference`, `conditional.rules_cofire`),
every one of them `severity: "informational"`. No signal refuses a route,
blocks a verb, or changes an exit code. The review flow's response to a
flagged signal is §6.4's **budget card** — never a graduation-opener
forced by a cap.
*(Cross-reference added 2026-07-18 — UX-survey item 4, amended by U-cap
§6.3; 09 §11 Y-20 / 08 §1 `surface_fill` / 10 §3 U17:)* a candidate
section's fill — entries, words, its load class, and (for `claude-md`)
the whole file's word count and managed share — is **surfaced at the
routing decision** by the review surface, computed at render from the
compiler's own count via the opt-in `list --json --surface-fill` field
(the probed destinations `skill-md`/`claude-md` carry it; `reference`
carries a **read-rate verdict** instead — sourced from
`report.reference_read_verdict`, never a compile probe — stating whether
it is currently a *safe overflow target*, per §6.4's reference-safety
constraint). Y-20 makes the fill **visible at the routing decision** so
the narrowest-surface choice (routing-doctrine §3) is made with the cost
in view, not to enforce anything — there is nothing left to enforce.
Moving a lesson from the managed section into the authored prose is a human
edit, recorded with **`self-learn graduate <id>`** (or the equivalent review
card) — which marks the record `superseded_by: canon` and lets the compiler
drop it from the section. (The backlog importer's bulk-acknowledge resolves
already-canon knowledge entries with the same marking — one mechanism,
several doors into it. ha-note's `--promoted` verb is the precedent.) That hand-weave is all that remains of
gen 1's "Level C," demoted from an automated milestone to an editing habit.
