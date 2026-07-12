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
observe). Each SKILL.md-routed fixture gets **≥3 fresh-session provocations**
— one trial of a stochastic system is an anecdote, not a result; the
hook-routed fixture is deterministic and needs one. If routed canon doesn't
move behavior on hand-picked best cases, no amount of pipeline
sophistication was going to matter — stop and rethink.

## M1 — The core loop (teach → triage → canon)

Scope: record schema + ledger ops (create/supersede/move) · `self-learn`
CLI (`teach` with scope/type/structured-field/`--route` flags, `list`,
`status`, `graduate`, `--selftest`; secret scan on **every** record write) ·
`/teach` wrapper with in-session extraction (O-4) · backlog importer with
already-canon flagging · `/self-learn:review` command (bounded batches,
four-option cards with diff previews, bulk-acknowledge, TTL'd+heartbeated
autosync pause sentinel, **self-push at session end** — the sync's
clean-tree branch never pushes) · **pause-sentinel support in
`bin/claude-skills-watch`/`claude-skills-sync`** — a main-repo change on
master with its own test; the watcher honors no sentinel today, and it must
ignore only sentinels whose heartbeat is older than the ~2 h TTL · three compilers
(SKILL.md managed section, CLAUDE.md managed section — chezmoi-aware for
user scope (E-17) — references append) · commit flow with record→commit
linkage, one commit per routed lesson · the O-6 standing offer line, if O-6
settles yes.

**Exit criteria:** (a) `teach --route` round-trips lesson→diff→commit on
home-assistant in one motion; (b) backlog import of home-assistant's GOTCHAS
flags the already-canon majority into one bulk-acknowledge and produces a
card set — the behavioral minority (E-2: ~5–7) plus analyst-flagged misfiles
— that one bounded review session fully triages, ending in real commits;
(c) `--selftest` passes and fails loud when the compiler target markers are
missing; (d) all writes honor the layout/mutation rules in `02-schema.md`
(verified by tests, including the no-per-session-writes rule and the
secret-scan refusal path).

Note: M1 has **no worker and no notifications** — analysis runs inline during
`review` (slower per item, zero infrastructure). This proves the loop's value
with the minimum surface, per the pre-mortem's lesson.

## M2 — Surfacing (worker + nudges)

Scope: detached pre-analysis worker (any host — **fully append-only**:
analysis proposals + merge proposals as new files, never record writes;
coalesced, flock'd per machine, restricted `--allowedTools`) · SessionStart
pending-count line (manual `settings.json`
registration — a documented install step, not an assumed one) ·
`notify-send` thresholds · staleness alarm (computed by the SessionStart
hook from the worker's `~/.cache` last-run marker) · review consumes
precomputed proposals (one-tap fast path).

**Exit criteria:** (a) a taught lesson has a proposal attached within one
worker cycle without any session involvement; (b) clustering emits a
merge proposal for a planted near-duplicate pair, and the next review
collapses it into one routed survivor + one superseded record with
`sightings: 2`; (c) killing the worker
trips the staleness alarm within its window; (d) a 10-item triage session
completes in under ~5 minutes using only card taps.

## M3 — v1.1 (supply widening + remaining compilers)

Scope: auto-memory importer (O-2, origin-dedupe across all statuses, prune
on route *and* reject per O-5) · hook compiler (scaffold + settings.json
snippet, P9 flow) · new-skill compiler (plugin-dev delegation) · statusline
count (optional) · revisit O-3 (SessionEnd appender) and O-7 (ha-note
unification) against a month of observed supply. (`/teach` moved to M1 —
it's the primary capture UX, not an optional wrapper; O-4.)

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
- **Routed-and-corrected**: routed lessons later *correctively* superseded
  (`supersedes: <record-id>` + recompile) — the honest "was it a good
  lesson" counter. **Excludes `superseded_by: canon` graduations**, which
  are successes, not failures (conflating them would inflate the bad-lesson
  rate — blind adjudication 2026-07-12). Per-lesson commits keep
  attribution clean; `git revert` is not the correction mechanism (S-12).
- **The acceptance fixture**: the three behaviors from §0, re-checked after
  routing. This is the only behavior-change metric v1 claims.
- **Supply mix**: teach vs import vs (later) appender — tells us where
  lessons actually come from before we invest in more capture (O-3's input).

Explicitly *not* metrics in v1: surfaced counts, reputation, recurrence
statistics — nothing that needs volume this deployment lacks (P7).
