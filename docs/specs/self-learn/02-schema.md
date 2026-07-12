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
sightings: 2              # bumped only by lazy clustering at analysis time
evidence:                 # pointers, never transcripts
  - {session: f687d7ce, ts: 2026-07-12T09:13:41Z, quote: "never edit .storage while HA is running"}
  - {origin: "GOTCHAS.journal.md#2026-06-08", note: "merged by cluster pass"}
proposal:                 # written by the pre-analysis worker; null until analyzed
  destination: hook       # skill-md | claude-md | reference | new-skill | hook
  alternates: [skill-md]
  rationale: "deterministic guard beats advisory text for a destructive edit"
  diff: proposals/lrn-4c1e9a2f.diff    # sibling file; may be inline if short
  model: claude-opus-4-8
  analyzed_at: 2026-07-12T09:25:12Z
routing:                  # written on routing; null before
  routed_at: 2026-07-13T18:02:00Z
  destination: hook
  commit: abc1234
  by: human               # always human in v1
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

## 2. Field rules

- **Substance is append-only** (P6): body, `evidence`, `created_at`, `type`,
  `source` never change after creation. A wrong lesson is corrected by a new
  record with `supersedes:` set, and the old one gets `superseded_by:` +
  `status: superseded`. Git provides the audit trail on top.
- **Lifecycle metadata may mutate**: `status`, `proposal`, `routing`,
  `sightings`, `scope`/`kind` (triage may re-classify — the *capture* is
  frozen, the *filing* is not). All such writes are human- or worker-
  triggered, never per-session — nothing in this schema is touched by merely
  *using* Claude Code (the gen-1 counter/autosync-storm bug is excluded by
  construction, E-8).
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
  pending/lrn-*.md          # awaiting triage (worker may still be analyzing)
  routed/lrn-*.md           # routed | rejected | superseded (terminal-ish)
  proposals/lrn-*.diff      # draft diffs referenced by records
.self-learn/                # repo root: project + user scopes, same shape
```

- **In-repo** → autosynced across machines, versioned, `git blame`-able.
- **Record-per-file** → atomic writes, no merge conflicts between concurrent
  writers, and directly readable by any future UI without a serving layer.
- `pending/` → `routed/` is a `git mv` at routing time, so the pending
  directory listing *is* the queue — no index to maintain or corrupt.
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
`routed/` records targeting it; text *outside* the markers is never touched.
Moving a lesson from the managed section into the authored prose is a human
edit — after which the record is marked `superseded_by: canon` and the
compiler drops it from the section. That hand-weave is all that remains of
gen 1's "Level C," demoted from an automated milestone to an editing habit.
