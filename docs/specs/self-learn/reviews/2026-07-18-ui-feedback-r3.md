# Review record — UI feedback round 3 (2026-07-18, agent-built)

Feedback source: `feedback/2026-07-18-ui-feedback-03.md`. Two build
units, each with its OWN spec gate before build (both specs were
authored by dedicated agents in parallel worktrees, blind-reviewed,
folded to SOUND), then built by dedicated agents, blind code-reviewed
to CLEAN, merged, and live-trialed in a full sandbox. Every verdict
below is a blind reviewer's; none self-certified; reviewers never saw
`reviews/*`.

## U14 — registration flow (Y-16 persistent readable error + Y-17 git-init-on-register)

**Spec gate.** First review: **NOT SOUND** — F1 BLOCKER was a consent
hole in the goes-stale race direction (a stateless confirm could
append `--init` although the arm banner never disclosed it — an
undisclosed `git init` and read≠run). Folded to the pinned invariant:
`--init` executes only when the ARM rendering displayed the disclosure
AND confirm-time re-derivation still holds; any mismatch runs plain
`host add` and fails safely into the Y-16 error leg. Plus 4 MAJOR
(required copy falsified by the half-init and half-written legs — the
final copy is "registration did not complete", the only sentence true
in every failure leg; a third unenumerated reload path — the defer
moved to the single `reload()` chokepoint; the pre-render race — an
in-flight-POST defer leg; release-on-re-arm clobbering a fresh armed
bar — the any-armed-bar defer leg), 2 MINOR (refusal ordering: pure-
argument refusals before the init mutation; zero-commit-repo residue),
2 NIT. Delta: **NOT SOUND** on F10–F13 residuals (client-field honesty
sentence, the twice-corrected copy, the page-global defer widening
stated, the one-directional weaker-than-read pin) → second fold →
**SOUND** (the reviewer truth-tabled the consent invariant in all four
disclosure×state cells plus forged-marker). One F14 NIT handed to the
builder: the in-flight flag releases on error/abort too.

**Build + code gate.** Empirical wipe-pin committed BEFORE the fix per
DoD: prime suspect CONFIRMED — the runner's unconditional post-verb
push on failure, `front`-scoped (no `lrn-` token in a host-add argv),
broadcast `window.location.reload()`; the push is queued before the
error partial renders, so the marker-only defense was provably
insufficient (leg (b) earned its place). Blind code review: **CLEAN**
first pass — 7 mutations run, each killed by exactly its claiming
test (incl. refusal-ordering, marker-dropped, re-derivation-dropped);
the consent walk covered all cells; app.js reverted wholesale to
prove the wipe suite pins the server mechanism honestly. 3 NITs
accepted (the spec-priced hand-crafted-POST boundary; a swapError
omission in the structural pin's asserted list; confirmInFlight as
boolean under the one-armed-bar invariant).

## U15 — record re-home (Y-18)

**Spec gate.** First review: **NOT SOUND** — F1 BLOCKER was mechanical
spec-text corruption (the insertion destroyed the neighboring pinned
"`kind` drives routing" bullet — repaired byte-identical, verified
purely-additive against master); F2 MAJOR the armed-bar bucket-
staleness race (an Enter on a bar armed before a CLI-side rehome
would execute against the NEW bucket, compiling into a different
project's CLAUDE.md — the re-check now runs at arm AND confirm,
pinned load-bearing); F3 MAJOR the merge-cluster sweep gap (rehome
now sweeps `merge-*.yaml` naming the record, matching resolution
behavior); +4 MINOR, 2 NIT. Delta: **NOT SOUND** on one residual
(F10: "disarm" used against its pinned survives-to-waiting meaning —
repaired to clear-slot+notice at all four sites) → **SOUND**.

**Build + code gate.** Blind code review: **CLEAN** first pass — 6
mutations run, each killed by its claiming test (merge-sweep,
collision refusal, unregistered-target on both CLI and intake sides,
confirm-side staleness check, clear-vs-disarm); consent path walked
(no agent route to execution; rehome excluded from the human
action-bar verb set entirely, so no forged-POST human path); the
flagged typing diagnostics proven pre-existing environment noise.
2 NITs accepted (duplicated target-resolution helper; scan-order
cosmetics). One accepted residual pinned by design: the microsecond
await window between confirm's bucket check and the runner — inherent
to the render/arm-time detection pin, serialized by the CLI's own
commit lock.

## Merge + live trials

Merged to master (932/676 suites green at merge — final master counts
931 CLI + 676 UI; pyright ui src 0, cli src at the 56-error
pre-existing baseline, zero new). Live trials in a full sandbox
(never the real ledger): **all three PASS** — git-init-on-register
end-to-end with the disclosure banner and pinned init commit; the
failed-registration error surviving the exact push that used to wipe
it, plain-words copy leading, dismiss restoring the notice; and a
pane-agent-proposed rehome through y+Enter landing the pinned ledger
commit with the record in its new bucket, the amended ancestor-
project doctrine visibly reasoning in the agent's reply (mtime-driven
recompile, zero code changes). Full log: `fixtures/ui-trials.md`
"Round-3 DoD trials".

**Round 3 gate CLOSED 2026-07-18: both units shipped.**
