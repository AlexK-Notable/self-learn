# self-learn — design corpus (gen 2)

*Single-authored 2026-07-12, replacing the gen-1 harness spec (archived at
`../archive/gen1-self-learning-harness/` — its README explains why). Status:
**design, no code**. Everything here was written together, as one system, with
the full evidence of three review rounds and the repo's own usage history baked
in from the start — not iterated into shape.*

## What self-learn is, in one sentence

A **capture, triage, and routing system for lessons learned while using Claude
Code**: lessons accumulate quietly into per-skill and per-project buckets; a
review surface presents them pre-analyzed; the user routes each one — with
agent help — into the surface where it becomes permanent (SKILL.md, CLAUDE.md,
reference docs, a new skill, or a hook). Nothing influences Claude until a
human routes it.

## Reading order

| Doc | What it holds |
|---|---|
| `00-vision.md` | The problem (restated correctly), the target UX, and the ten design principles with their evidence |
| `01-architecture.md` | The six components, the life of a learning, failure modes, and what is deliberately absent |
| `02-schema.md` | The learning record, storage layout, and mutation rules |
| `03-decisions.md` | The decision register: settled / open / v2-gated (with explicit activation triggers) |
| `04-roadmap.md` | Build milestones, acceptance fixture, success metrics |
| `05-evidence.md` | The empirical facts this design is built on, with sources |

## Ground rules for changing this corpus

1. A **settled** decision (`03-decisions.md`) reopens automatically if a later
   decision changes its inputs — "settled" is not "shielded" (gen-1's
   sequential-lock-in failure).
2. Material design changes get a **blind** review before settling — reviewers
   receive the docs and a mandate, never the expected conclusion.
3. No code until the user ratifies the corpus; build happens in this worktree
   per the repo's worktree → test → merge convention.
