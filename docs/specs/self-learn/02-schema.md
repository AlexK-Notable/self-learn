# 02 — Schema: the learning record and its storage

## 1. The record

One file per learning: YAML frontmatter (machine fields) + markdown body
(the lesson itself). Filenames: `lrn-<8char-id>.md`.

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
  # no commit hash here — a commit's own hash can't live in a file it
  # contains. The record→commit link is the commit MESSAGE, which carries
  # the record id ("self-learn: route lrn-4c1e9a2f → hook"); git log --grep
  # by id recovers it.
supersedes: null
superseded_by: null
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
diff: proposals/lrn-4c1e9a2f.diff   # PREVIEW ONLY — compilers regenerate from
                                    # the record at apply time (01 §3.5)
model: claude-opus-4-8
analyzed_at: 2026-07-12T09:25:12Z
```

Keeping the proposal out of the record means that after capture, **the only
writer of a pending record is the human** — the worker's clustering emits
merge *proposals*, never record edits (blind re-review 2026-07-12). A stale
proposal can never corrupt a record. Honest scope of the guarantee: the
*ledger* is race-free single- and multi-machine (record-per-file, new-file
writes); the shared *compile targets* (managed sections) are not
record-per-file, so concurrent multi-machine routing degrades to autosync's
standard safe rebase-halt (`01` §5) rather than being excluded outright.

## 2. Field rules

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
- **Evidence quotes are minimal, and every record-body write is
  secret-scanned** — capture (`teach`), review edits, and merge collapses
  alike. Records are tracked files: autosync publishes each write to the
  remote within seconds, *before* any human review (E-8), and
  freeze-at-routing legalizes post-capture edits — so the scan guards the
  write path, not just the front door (blind-adjudication rider,
  2026-07-12). The scanner refuses (or redacts and flags) anything that
  trips it; quotes carry the shortest span that proves the sighting.
- **`superseded_by` ∈ {`null`, `<record-id>`, `"canon"`}.** A record-id
  marks *corrective* supersession — the lesson was wrong and a new record
  replaces it. `canon` marks **graduation** — the substance now lives in
  authored canon (a hand-weave, or the backlog's bulk-acknowledge). A
  canon-superseded record takes `status: superseded`, lives in `resolved/`,
  and carries no routing linkage. The two meanings are opposites — a failure
  and a success — and metrics must never conflate them (`04-roadmap.md`).
  Graduation's owning verb: `self-learn graduate <id>` (or the review card).
- **Lifecycle metadata may mutate**: `status`, `routing`, `sightings`,
  `scope`/`kind` (triage may re-classify — the filing is never frozen).
  `deferred` adds `deferred_until` (default: +30 days — the record is
  excluded from cards and pending counts until then) and `deferred_count`
  (at 2, the review card suggests reject). All such writes are
  **human-triggered** — the worker writes only proposal files, merges
  included (blind re-review 2026-07-12) — and never per-session; nothing in
  this schema is touched by merely *using* Claude Code (the gen-1
  counter/autosync-storm bug is excluded by construction, E-8).
- **Lifecycle notes for the implementer** *(deliberate choices, stated so no
  one hunts for missing fields)*: rejection/supersession provenance is
  carried by git — the resolving commit's author, date, and message are the
  who/when/why, so there are no `rejected_at`/`reason` fields · `status:
  routed` records live in `resolved/` (the directory is the umbrella for all
  terminal statuses; the status stays precise) · a deferred record keeps
  `status: deferred` while hidden — queue membership is *computed* from
  `deferred_until`, not read off the status · `teach --route` writes its
  record directly to `resolved/` as `status: routed`, never transiting
  `pending/` · `source: session` has no v1 writer — forward-declared for the
  v1.1 SessionEnd appender (O-3) · record ids are **random**
  (collision-resistant across offline machines); a sequential counter would
  add/add-conflict on every parallel capture.
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
  holds.)*
- Transient state (worker locks, run markers, coalescing timers) lives in
  `~/.cache/claude-skills/self-learn/`, never in the repo.
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
touched. Entries are **trigger-first** — "**When ⟨trigger⟩:** ⟨instruction⟩",
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
Moving a lesson from the managed section into the authored prose is a human
edit, recorded with **`self-learn graduate <id>`** (or the equivalent review
card) — which marks the record `superseded_by: canon` and lets the compiler
drop it from the section. (The backlog importer's bulk-acknowledge resolves
already-canon knowledge entries with the same marking — one mechanism,
several doors into it. ha-note's `--promoted` verb is the precedent.) That hand-weave is all that remains of
gen 1's "Level C," demoted from an automated milestone to an editing habit.
