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
resolution_note: null     # optional; the human's why, written once at
                          #   resolution (route/reject/graduate) — see §2
---

## Trigger
About to edit a `.storage/*.json` file while Home Assistant is running.

## Instruction
Stop the HA container first. HA caches `.storage` in memory and rewrites it
on shutdown, so a live edit is silently clobbered.
