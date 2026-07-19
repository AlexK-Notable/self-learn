# Review record — forward work map (14 + forward/*), 2026-07-18

Origin: the user's directive to project the required work forward
("write up substantial documentation that can provide a deep mapping
of the potential required work") after the same-day corpus status
realignment (commit 3bca848). Authored by the orchestrator (planning
is the orchestrator's role under S-18); gated because the set steers
future rounds. Reviewer: blind Opus, corpus + code access,
`reviews/*` withheld per standing rule.

## Scope

`14-forward-work-map.md` (FW-1…FW-29 register, sequencing, decision
queue, trigger table, non-goals) + seven theme docs under `forward/`
(supply-quality, canon-lifecycle, packaging, ui-ux, sync-and-fleet,
platform-drift, process-and-horizon).

## First pass: NOT SOUND

The reviewer verified the set's checkable claims against 02/03/05–13,
the UI/CLI code, plugin.json, and the bundle-exclusion memo — and
confirmed the overwhelming majority true (including the load-bearing
ones: no JS harness exists; graduate/confirm-recurrence are UI-wired;
the X-7 contingency fired on the 0.2.121 verify-at-build run; FW
numbering clean). Findings:

- **F1 BLOCKER (sync-and-fleet §3)**: the draft scheduled a
  session-opener ledger fetch/ff "when FW-20 builds" — automatic
  ledger sync, which D3/S-17 excludes ("no autosync anywhere…
  orchestrators must not 'fix'") and which FW-22 explicitly reserves
  for the user's ruling. The map's own §4 claimed "documentation and
  visibility only" two paragraphs later. Classic silent D3 weakening;
  exactly what the gate exists to catch. **Fold**: schedule struck;
  pull-before-review demoted to manual operator discipline; automatic
  fetch of any shape named as FW-22-reserved; dated fold note.
- **F2 MAJOR (canon-lifecycle §3)**: the draft narrowed G-6's scope to
  existence-never-behavior and presented the narrowing as a settled
  decision — but the G-6 row pins "file, path, device, behavior."
  A misquote plus scope-pinning from a doc that claims to pin nothing.
  **Fold**: reframed as a scope *proposal* to ratify at spec time; the
  row wins until then.
- **F3 MINOR**: records-index file counts inflated (~20/~11, not
  25+/12+). Folded.
- **F4 MINOR (ui-ux §3)**: claimed 09 §5 "already specifies"
  unreadable-record degradation; the table has no such row. Folded —
  the maintenance round adds the row via its own gate.
- **F5 SCOPE (ui-ux §4)**: the page-level composition statement read
  as binding ("must") on future specs. Folded to a proposed
  convention, binding only if adopted into 09 §11.
- **F6 MINOR (omission)**: follow-up resolution (11 §2.1) and
  contradiction edges (11 §2.4) are equally shipped-never-fired and
  had no readiness home. Folded into FW-8's drill.
- Nits folded: Y-11 included in the extension-unit register span;
  "vanished/broke" SDK wording tightened to the precise
  contingency-fired form; O-9 build-shape phrasing noted consistent.
- F7 adjudicated fine-as-intent by the reviewer (FW-12's
  append-preserving migration constraint — a faithful S-12 extension,
  self-labeled to-be-spec'd); no change.

## Delta re-check: SOUND

The reviewer re-read every changed span, verified each fold faithful
(including re-checking the new F6 claims against 11 §2.5), and
confirmed sync-and-fleet §4's "visibility and documentation only" is
now true after the F1 fold. One MINOR residual introduced by the F6
fold — `confirm-held` cited as the follow-up resolver; per 11 §2.5 the
resolver is `followup done`, `confirm-held` belongs to the holding
axis — folded at merge with the reviewer's exact correction.

**Verdict: SOUND. The forward work map (FW-1…FW-29) is the gated
planning baseline; items graduate into specs via the normal two-gate
chain, and the map takes dated disposition notes as they fire, die,
or graduate (14 §7).**
