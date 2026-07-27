# Why `skills/home-assistant` routed to `reference` 14 times — full analysis

Read-only investigation of `~/.self-learn` (frontmatter + bodies of every
`skills/home-assistant/resolved/*.md`, every `user/resolved/*.md`, every
`projects/*/resolved/*.md`, `skills/chezmoi/resolved/*.md`,
`skills/hypr-doctor/resolved/*.md`), the one surviving
`skills/home-assistant/proposals/*.yaml`, `hosts.yaml`, the CLI source
(`import_backlog.py`, `verbs.py`, `ledger_ops.py`, `records.py`), and
`routing-doctrine.md`. No files in `~/.self-learn` were modified.

## Verdict up front

**Real control group for the *mechanism*, artefact-inflated on the
*magnitude*.** Two independent findings, and they point in different
directions on the question as posed:

1. The **direction** of the effect — knowledge-type content at skill
   scope routes to `reference`, never to `claude-md` — is real,
   doctrine-encoded, and confirmed by a *second, independent* data point
   that has nothing to do with the import (see lrn-e2e4026b below). This
   part transfers.
2. The **magnitude** (14 straight, vs. 0 anywhere else) is inflated by a
   one-off artefact: a bulk backlog import that only `home-assistant` had
   the raw material for. No other bucket had an equivalent corpus to
   import, so no other bucket could have produced this count even if the
   underlying mechanism applied to it identically.

One candidate explanation is **ruled out structurally, not just
empirically**: `routing.by: human`.

## Candidate-by-candidate

### Ruled out: human override (`routing.by`)

`routing.by` is `human` on **every single resolved record in every
bucket** — home-assistant, user, projects, chezmoi, hypr-doctor, all 28+
records. This isn't a pattern to interpret; it's a hardcoded constant.
`plugins/self-learn/cli/src/self_learn/verbs.py:2325`:

```python
routing: dict[str, object] = {
    "routed_at": _now_iso(), "destination": destination, "by": "human"
}
```

`ledger_ops.py:756` — `by: str = "human"` — is the only other write site,
and no call anywhere in the CLI passes a different value. The `route`
verb stamps `by: human` unconditionally, regardless of whether the human
deliberated per-record or pre-authorized a script to call `route` in a
loop 14 times in 15 seconds (which is what happened — see below). The
field carries **zero discriminating information** across this dataset;
it cannot be evidence for or against the control-group hypothesis.

### Confirmed: backlog import is the origin of 13/14 (the "artefact" half)

`plugins/self-learn/cli/src/self_learn/import_backlog.py` mines
`references/GOTCHAS.journal.md` — a hand-maintained, dated operator
journal — into pending records, one shot, idempotent by origin anchor.
Evidence this is exactly what produced the home-assistant records:

- All 32 `skills/home-assistant/resolved/*.md` records share
  **`source: backlog`** and the identical **`created_at:
  '2026-07-14T04:19:30Z'`** — down to the second. That is not 32
  independent captures; it is one import run.
- Every `evidence.origin` is `GOTCHAS.journal.md#<date-or-sha>`, matching
  `_entry_origins()`'s exact anchor scheme in the importer.
- The journal is real and still on disk: `/home/komi/repos/claude-skills/
  plugins/home-assistant/skills/home-assistant/references/
  GOTCHAS.journal.md` (32K, dated entries 2026-06-02 → 2026-07-07),
  alongside a curated `GOTCHAS.md` (the canon it was mined against) and
  `LEARNINGS.md` (14 Jul 12:02 — created same day as the import, per
  doctrine §4: "`reference` means the skill's `references/LEARNINGS.md`
  (created on first route)").
- Of the 32 imported records, **18 were auto-flagged `already_canon` and
  graduated (`superseded_by: canon`, `routing: null` — never routed at
  all)** by the importer's own canon-match heuristic (title substring
  match against `GOTCHAS.md`, ≥24 normalized chars). Those never touch
  the "14 reference" count.
- The remaining 14 are the importer's `behavioral_minority` card set —
  new knowledge, not yet in canon — which a later analysis pass (model
  `claude-fable-5`, per the one surviving proposal
  `lrn-3e4c2df3.yaml`, `analyzed_at: 2026-07-14T07:22:13Z`) proposed
  `destination: reference` for, and the human bulk-approved. Timestamps
  confirm mechanical batch application, not 14 individual real-time
  judgments: 8 of the 14 have `routed_at` within a **15-second window**
  (07:23:08 → 07:23:23), and their `resolution_note` says so explicitly:
  *"overnight batch per user authorization 2026-07-14 (safe subset) —
  reference append, reversible."* Four more were routed earlier the same
  day (04:35, 19:02) via the interactive review flow.

**Neither `hypr-doctor` nor `chezmoi` has a `GOTCHAS.journal.md`** —
checked directly: both skills have live `references/` directories
(`recovery-playbook.md`, `plugin-manifest.md` for hypr-doctor;
`commands.md`, `troubleshooting.md`, etc. for chezmoi) but no
pre-existing journal to import. `import_backlog.py` requires that file to
exist (`raise ImporterError(f"no journal at {journal_path}")` if absent)
— there was structurally nothing to mine. This is the artefact: the
importer isn't biased toward home-assistant, home-assistant is simply
the only bucket that had 32 pre-self-learn journal entries sitting there
waiting to be mined, because it's the only skill with its own
long-running gotcha-capture habit (the `ha-note` tool referenced in the
home-assistant skill description) predating self-learn's ledger.

### Confirmed, and this is the part that transfers: content type × doctrine's routing map

Every one of the 14 (and the 18 superseded) home-assistant records is
`type: knowledge` with an identical body shape —
`## Fact` / `## Context` with `Status / HA version / Cause / Fix / Repro
/ Tags` bullets (verified by reading multiple full bodies, e.g.
lrn-01865691 — an Adaptive Lighting color-temp-floor bug — and
lrn-a103d52a — a `custom_sentences` `lists:` gotcha). These are pure
diagnostic facts, not behavioral rules.

`routing-doctrine.md` §2 (`## 2. The routing map`) hardcodes two
**different** rules by scope, not one general "knowledge → reference"
rule:

> - **knowledge, skill scope** → `reference` or `skill-md` section...
>   otherwise `reference`.
> - **knowledge, project/user scope** → `claude-md` (or project docs).

And §1's destination table defines `reference` narrowly: *"append to
**the skill's** `references/LEARNINGS.md`"* — it is not a generic
"knowledge bucket," it is a skill-scoped surface by construction. There
is no user-scope or project-scope equivalent anywhere in the doctrine or
on disk (checked `~/.claude` for any reference-style file outside
plugin/skill directories — none exists).

This is why every `type: knowledge` record found outside a skill bucket
routed to `claude-md`, never `reference` — not by coincidence, but
because doctrine gives it no other legal destination:

- `lrn-2fd0cdd7` (user scope, knowledge — the CodeBoarding
  `recursion_limit=40` fact) → `claude-md`.
- `lrn-56e5aa0a` (project scope, knowledge — the `kmalloc-128` slab-leak
  fact) → `claude-md`.

**The one live, non-imported data point that proves this isn't purely an
import artefact:** `lrn-e2e4026b` — `source: teach`, captured live in a
session on 2026-07-13 (a full day *before* the backlog import ran),
routed to `reference` within 7 seconds via the "one-motion `teach
--route`" protocol, `resolution_note: "M1 exit (a) protocol run:
one-motion teach --route, analyst-chosen destination"`. This record
(a fact about HA's `.storage` write debouncing) is `type: knowledge`,
`scope: skill:home-assistant`, and got the same destination the 13
imported records got — via a completely different pipeline (live
teach, not backlog import; individual one-motion route, not batch).
That is the control that isolates the mechanism: **when the content is
`type: knowledge` at skill scope, it routes to `reference` regardless of
whether it arrived via live session capture or bulk import.** The
mechanism is content-type × scope, not import-provenance.

### Also true, secondary: the destination is genuinely unavailable elsewhere, not merely unused

Because `reference` is defined as *the skill's* references file, a
project or user-scope record literally has nowhere named `reference` to
go — this is the "bucket has a surface that already exists" candidate
from the task, confirmed, but subordinate to the content-type finding:
even a skill bucket with a `references/` dir (hypr-doctor, chezmoi) did
*not* route anything there in this dataset, because neither bucket's
captured lessons were `type: knowledge`-shaped diagnostic facts — both
of hypr-doctor's and chezmoi's resolved records are `type: behavior`
(`kind: anti-pattern`/`surface-rule`), which doctrine routes to
`skill-md` or `hook`, never `reference`, regardless of whether a
references surface exists. Surface availability is necessary but not
sufficient; content type is what actually decides it.

## Field-by-field comparison table

| Field | `skills/home-assistant` (14 → reference) | `user` (5 → claude-md, 1 → hook) | `projects/*` (5 → claude-md, 1 → hook) |
|---|---|---|---|
| `type` | 14/14 `knowledge` | 5/6 `behavior`, 1 `knowledge` (→claude-md anyway) | 4/6 `behavior`, 1 `knowledge` (→claude-md anyway), 1 `behavior`(project, ZMK Studio) |
| `kind` (behavior only) | n/a | `surface-rule` ×2, `anti-pattern` ×3 | `anti-pattern` ×3, `surface-rule` ×1 |
| `source` | 13/14 `backlog`, 1 `teach` | all `teach`/`session` (live capture) | all `teach`/`session` (live capture) |
| `created_at` | 13/14 identical: `2026-07-14T04:19:30Z` (single import instant) | spread across 4 distinct days (07-14, 07-15, 07-18, 07-21, 07-24) | spread across 3 distinct days (07-15, 07-17, 07-18, 07-20) |
| `routing.routed_at` | 8/14 within a 15-second window (batch apply); rest same-day, two distinct passes | one per lesson, spread over days/weeks | one per lesson, spread over days/weeks |
| `routing.by` | `human` (100%, but hardcoded constant — see above) | `human` (100%, same constant) | `human` (100%, same constant) |
| `routing.destination` | `reference` ×14 | `claude-md` ×5, `hook` ×1 | `claude-md` ×5, `hook` ×1 |
| body shape | `## Fact` / `## Context` with Status/HA-version/Cause/Fix/Repro/Tags | `## Trigger`/`## Instruction` (behavior) or narrative (knowledge) | same as user |
| `verified` / `verified_how` / `incident_cost` / `generality` fields | **absent** on all 32 (older/lighter schema) | present on 6/8 (richer, later schema) | present on 4/5 |
| pre-existing corpus to mine | yes — `GOTCHAS.journal.md`, hand-maintained since 2026-06-02, unique to this skill | none | none |
| `reference`-class destination available in doctrine at this scope | yes (`references/LEARNINGS.md`, skill-scoped by definition) | **no** — no user-scope analog exists | **no** — no project-scope analog exists |

Note on the "richer schema" row: this is consistent with, not
contradictory to, the import-artefact finding — the backlog importer
(and the 2026-07-14 batch-approval pass right after it) predates the
`verified`/`incident_cost`/`generality` fields that show up on every
`teach`-sourced record from 07-15 onward. It's a timing/provenance
signature, not evidence of a different doctrine *for routing* (the
routing map in §2 that actually decides `reference` vs `claude-md` has
no version history noted for that specific rule).

## The transferable mechanism — could `user` be given it?

The mechanism is **content type, gated by a scope-conditioned
destination the doctrine only defines for skills**:

```
type: knowledge  +  scope: skill:*  → reference   (doctrine §2, exists)
type: knowledge  +  scope: user|project → claude-md   (doctrine §2, only option)
```

`user` doesn't collapse to `claude-md` because its lessons are somehow
worse-behaved than home-assistant's — it collapses because (a) the
lessons it actually generates are overwhelmingly `type: behavior`
(corrections of live mistakes: sudo misuse, model selection, false-pass
verification gates — all "next time X happens, do Y", not free-standing
facts), and (b) even the one `type: knowledge` record it did generate
(`lrn-2fd0cdd7`) had **no `reference`-equivalent destination to go to** —
the enum's `reference` entry is scoped to "the skill's
`references/LEARNINGS.md`" by definition, and no user-scope or
project-scope analog exists anywhere in the doctrine or on disk.

To transfer the mechanism, two independent things would need to be true,
and only one is really about `user`'s content:

1. **User-scope lessons would need to include more standalone facts**,
   not just behavioral corrections — plausible but not something routing
   doctrine controls; it's about what actually gets taught.
2. **Doctrine would need a `reference`-analog destination at user
   scope** — e.g. a `~/.claude/reference/LEARNINGS.md`-style progressive-
   disclosure surface, parallel to the `variant: local` carve-out §2a
   already adds for `claude-md` (personal, per-machine). This is the
   half that's squarely in self-learn's design space: §3's own stated
   rationale for `reference` — *"`~/.claude/CLAUDE.md` loads in every
   session of every project — user scope is the most expensive
   destination in the system... when a skill-md section is getting fat,
   prefer `reference`"* — applies with at least equal force to user
   scope, which currently has no cheaper fallback than `claude-md` at
   all. Right now a `knowledge`-type, low-urgency user-scope fact is
   forced into the most expensive surface in the system for lack of any
   alternative — the same problem `reference` exists to solve for
   skills, unsolved at user scope.

## What I could not verify

- Whether the `resolution_note`'s "overnight batch per user
  authorization" was a single blanket approval command or N individual
  approvals executed in sequence by a human working quickly — the ledger
  records the *outcome* (`by: human`, tight timestamp clustering,
  explicit batch note) but not the UI/CLI transcript of that session, and
  I did not search Claude Code session transcripts (out of scope for a
  read-only `~/.self-learn` + repo investigation, and the task's file
  list didn't point there).
- Whether `model: claude-fable-5` (the only model value seen, from the
  one surviving proposal `lrn-3e4c2df3.yaml`) was the model used for all
  14 reference-routing proposals, or just that one — the other 13
  proposals no longer exist on disk (proposals are apparently deleted or
  not retained once a record is resolved; only the resolved record and
  routing metadata survive). This is an inference from the one surviving
  sibling proposal plus timestamp proximity, not a direct read of all 14.

## Key record IDs cited

- `lrn-01865691`, `lrn-a103d52a` — example `reference`-routed knowledge
  bodies (Adaptive Lighting CCT floor; `custom_sentences` `lists:` gotcha).
- `lrn-e2e4026b` — the live, non-imported, one-motion `teach --route`
  record that isolates the content-type mechanism from the import
  artefact.
- `lrn-3e4c2df3` — the one surviving proposal (still pending, not
  resolved — a deferred Govee-lamp record), the only evidence of
  `model: claude-fable-5` and the 07:22–07:23 analysis window.
- `lrn-2fd0cdd7` (user), `lrn-56e5aa0a` (project) — the two
  `type: knowledge` records outside skill scope, both forced to
  `claude-md` for lack of any `reference`-equivalent destination.
- `lrn-dd9489b2`, `lrn-4f5971c8`, `lrn-38514455` — the three `hook`-routed
  records (user, project, chezmoi), confirming `routing.by: human` is
  constant even for the destination requiring the most machine-generated
  content (compiled guard scripts).
