# Review record — armed host-add (feedback round 1 item 5, 2026-07-17)

Two gates, two independent reviewers, both taken to delta-clean.

## Gate 1 — the Y-11 amendment (blind SPEC review, fresh Opus agent)

Pass 1 VERDICT: **AMENDMENT NEEDS REWORK** (decision itself sound —
`host add` is strictly less consequential than the already-armed
`route`: ledger-only commit, no push/compile, trivially unwound).
Findings, all folded (8d758e8 + the F10 hunks in 2e30310):

- **F8 BLOCKER** — path provenance unpinned: an armed registration must
  use the SERVER-derived bucket meta.yaml path, never a client value
  (else a forged same-origin POST could mint an attacker-chosen canon
  write target + widen the pane read scope).
- **F1 BLOCKER** — consent visibility: the CLI's consent line is
  stdout, which the runner contract discards — the ARM state must
  render the consequence (canon write target + analyst-readable).
- **F2 BLOCKER** — "same runner" only holds at the subprocess seam;
  the bucket-scoped route triple + id-less arm rendering had to be
  specified as the surface's first path-scoped mutation.
- F3/F4/F5/F6/F7/F9 MINOR/NIT — no-keymap-entry recorded as dated
  choice; project-scope-only named; post-success render pinned;
  the copyable-command principle given an auditable T-A predicate +
  exempt list (teach --supersedes per §8/Y-4; stderr strips per §5;
  the 403 recovery line); prior 10 §4 row text quoted; "no path to
  route" extended to host add.
- **F10 (delta round)** — 10 §2's T-A fixture and 10 §3's U3 task
  still described the superseded copyable-command behavior; propagated.

Delta VERDICT: **AMENDMENT SOUND** (all hunks verified, 09↔10
consistent).

## Gate 2 — the build (blind CODE review, the session's standing
independent reviewer; no access to this directory)

Pass 1 VERDICT: **CLEAN** — no MAJOR, no pin violated. Verified solid:
path server-derived at every step with the client `path` field provably
dead (FastAPI never binds it; hostile-field test asserts argv);
`_RECORD_ID_RE` kills traversal/open-redirect shapes; consent carries
both consequences in Y-9 words under CSP with autoescaped path; error
path coherent + escaped; CSRF inherited (cookie + HX-Request on every
POST); sweep test honest about its predicate's reach. Two recommended
MINORs, both folded (305707e):

1. Two co-armable bars via mouse → Enter aimed at the DOM-first bar.
   Fold: while any bar is armed, other bars' triggers go
   `visibility: hidden` (live `:has()` rule — keyboard was already
   modal; closes the mouse path both directions).
2. Scope gate was path-presence only. Fold: explicit
   `scope != "project"` refusal FIRST in `_host_add_target`; new test
   plants a stray meta.yaml in a skill bucket and proves the belt
   (without it, `project_path_for` would have armed).

Delta VERDICT: **CLEAN** (ordering unbypassable; CSS reach exact —
armed bar untouched, single-bar pages unaffected, non-bar buttons
unmatched; 505 green).

## Empirical checks (orchestrator)

Live Playwright against the seeded sandbox (dev :7358, redirected XDG):
full keyboard flow on the unregistered zmk bucket — arm renders consent
+ exact command; `s` disarms; Enter confirms; the registration REALLY
landed (ledger commit `self-learn: host add project …`), redirect
returned to the bucket, notice gone (then reverted to restore the
fixture). Screenshots r1-hostadd-{notice,armed,registered}.png in
~/Pictures/self-learn-ui/. Observed and accepted (pre-existing, all
armed bars, unreachable at human speed): a keystroke inside htmx's
~20ms post-swap settle window falls through to a native GET reload
that loses arm state and executes nothing.
