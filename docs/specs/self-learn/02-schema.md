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
  by: human               # always human in v1
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

- **Substance freezes at routing** *(S-8/S-12 — settled 2026-07-12,
  blind-adjudicated ADOPT)*: while
  `pending`, the body and filing may be edited freely — a typo in your own
  thirty-second-old capture is not a provenance event, and git versions
  every draft state anyway. At routing the substance freezes: `created_at`,
  `type`, `source`, and the body never change afterward; a wrong *routed*
  lesson is corrected by a new record with `supersedes:` set, and the old
  one gets `superseded_by:` + `status: superseded`. The provenance ceremony
  is for canon, not drafts.
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
  why that proposal class loses. Secret-scanned like every record-body
  write.
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
  moves a **pending** record to another **registered project** bucket —
  the repair for capture-cwd filing the lesson under a narrower repo
  than its real firing range (the umbrella-project case,
  routing-doctrine §3). `--to` accepts the registered project's path or
  its bucket slug (the `host rebind` naming precedent — the two things
  a human can say). What moves: `pending/lrn-<id>.md` alone, one
  `git mv` into the target bucket's `pending/`; the target bucket's
  `{pending,resolved,proposals}/` dirs are created if absent and its
  `meta.yaml` stamped from the registered path (13 §3) — hosts.yaml
  stays the only registration authority; the verb registers nothing.
  The record file is **byte-untouched**: `scope: project` already reads
  correctly in the destination, so a re-home is a filing move, never a
  substance edit (the freeze rules above are unaffected; `sightings`,
  `evidence`, deferral metadata all ride along unchanged — a deferred
  record moves and stays deferred). **Proposal siblings are swept
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
  projects/<slug>`; optional `--note` rides the commit body only
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
  corruption to surface, never to merge into · source not a project
  bucket (**M1 is project→project only** — user-scope targets and
  skill/user-scope sources are dated future work, not silent
  extensions: a cross-scope move is a re-classification with its own
  consent story). Sequence otherwise standard for a record-writing
  verb: secret scan of the record file AND the note *(F6 — the file
  scan is a no-op in practice since the bytes don't change, but every
  record-writing verb scans both and uniformity beats the
  micro-optimization)*, `commit_lock` before the first mutation,
  sentinel self-hold + heartbeat, targeted staging, push.
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
  subsystem was deleted with the platform change). No new state
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

**Overflow rule (mechanical, not aspirational):** a managed section caps at
**10 entries or ~150 words** (per-target override allowed). At the cap the
compiler still applies the new entry but flags the section, and the next
review session opens with a graduation card: move the oldest knowledge
entries into `references/` or weave them into the authored prose.
Loaded-surface budget is the scarce resource (E-6: ≥60% of preloaded skill
content is attention dilution) — the cap is what keeps P2's native loading
from quietly becoming the preloading it replaced.
*(Cross-reference added 2026-07-18 — UX-survey item 4; 09 §11 Y-20 / 08 §1
`surface_fill` / 10 §3 U17:)* this cap — and how close a candidate section
already sits to it — is **surfaced at the routing decision** by the review
surface, in plain words ("this section already holds 8 of its 10 entries"),
computed at render from the compiler's own count via `list --json
.surface_fill`. The over-cap WARNING and graduation-opener flow named above
stay the authoritative enforcement (an over-cap route still applies + flags);
Y-20 only makes the fill **visible before** that boundary so the
narrowest-surface choice (routing-doctrine §3) is made with the cost in view
rather than discovered at apply-time rejection.
Moving a lesson from the managed section into the authored prose is a human
edit, recorded with **`self-learn graduate <id>`** (or the equivalent review
card) — which marks the record `superseded_by: canon` and lets the compiler
drop it from the section. (The backlog importer's bulk-acknowledge resolves
already-canon knowledge entries with the same marking — one mechanism,
several doors into it. ha-note's `--promoted` verb is the precedent.) That hand-weave is all that remains of
gen 1's "Level C," demoted from an automated milestone to an editing habit.
