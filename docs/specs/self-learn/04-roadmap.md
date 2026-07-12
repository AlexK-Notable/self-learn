# 04 — Roadmap: milestones, acceptance, metrics

*No code until the user ratifies this corpus. Build in this worktree,
test-first, merge to master when green (repo convention).*

## 0. Pre-build acceptance fixture (defines "worth it" before anything exists)

Pick **three known, real failure modes** from the existing canon — candidates:
the `.storage`-while-running edit (home-assistant), the anchored-edit
verification rule, one hypr-doctor post-update behavior. For each, write
down: the trigger situation, today's failure shape, and the observable
success ("Claude stops the container first without being told").

These three are the corpus's definition of success: after M1+M2, routing
them through self-learn must produce canon/hook changes that **visibly change
behavior in a live session** (manual A/B: fresh session, provoke the trigger,
observe). If routed canon doesn't move behavior on hand-picked best cases,
no amount of pipeline sophistication was going to matter — stop and rethink.

## M1 — The core loop (teach → triage → canon)

Scope: record schema + ledger ops (create/supersede/move) · `self-learn`
CLI (`teach` with scope/type/`--route` flags, `list`, `status`, `--selftest`)
· backlog importer · `/self-learn:review` command with AskUserQuestion cards
· three compilers (SKILL.md managed section, CLAUDE.md managed section,
references append) · commit flow with record→commit linkage.

**Exit criteria:** (a) `teach --route` round-trips lesson→diff→commit on
home-assistant in one motion; (b) backlog import of home-assistant's GOTCHAS
produces a pending set that one bounded review session fully triages, ending
in real commits; (c) `--selftest` passes and fails loud when the compiler
target markers are missing; (d) all writes honor the layout/mutation rules in
`02-schema.md` (verified by tests, including the no-per-session-writes rule).

Note: M1 has **no worker and no notifications** — analysis runs inline during
`review` (slower per item, zero infrastructure). This proves the loop's value
with the minimum surface, per the pre-mortem's lesson.

## M2 — Surfacing (worker + nudges)

Scope: detached pre-analysis worker (coalesced, flock'd, lazy clustering,
proposal blocks + draft diffs) · SessionStart pending-count line ·
`notify-send` thresholds · staleness alarm · review consumes precomputed
proposals (one-tap fast path).

**Exit criteria:** (a) a taught lesson has a proposal attached within one
worker cycle without any session involvement; (b) clustering merges a
planted near-duplicate pair and bumps `sightings`; (c) killing the worker
trips the staleness alarm within its window; (d) a 10-item triage session
completes in under ~5 minutes using only card taps.

## M3 — v1.1 (supply widening + remaining compilers)

Scope: auto-memory importer (O-2, with prune-on-route per O-5) · hook
compiler (scaffold + settings.json snippet, P9 flow) · new-skill compiler
(plugin-dev delegation) · optional `/teach` wrapper (O-4) · statusline count
(optional) · revisit O-3 (SessionEnd appender) against a month of observed
supply.

**Exit criteria:** one real anti-pattern lesson routed end-to-end into a
working PreToolUse hook through the explicit-approval flow; auto-memory
entries appear in triage with origin preserved.

## M4 — Gated futures

Whatever `03-decisions.md` gates open: standalone UI (G-3/O-1), statistical
layer (G-1), portability extraction (G-2), forensic drain (G-4), znote
backend (G-5). Each arrives with its own blind review (P10).

## Success metrics (honest at n=1 — counted, not modeled)

- **Time-to-triage**: median days a learning sits pending. (Target: the
  notification thresholds keep it under ~2 weeks.)
- **Queue health**: % of pending older than 30 days. (The ha-note failure
  signature was 100%; sustained >50% means P3–P5 failed and the design
  needs the standing review, not more capture.)
- **Routed-and-reverted**: routed lessons later git-reverted or superseded —
  the honest "was it a good lesson" counter.
- **The acceptance fixture**: the three behaviors from §0, re-checked after
  routing. This is the only behavior-change metric v1 claims.
- **Supply mix**: teach vs import vs (later) appender — tells us where
  lessons actually come from before we invest in more capture (O-3's input).

Explicitly *not* metrics in v1: surfaced counts, reputation, recurrence
statistics — nothing that needs volume this deployment lacks (P7).
