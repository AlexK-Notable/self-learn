# 2026-07-12 — G-3 surface re-derivation gates (09/10 web revision)

*The post-correction /goal cycle: re-derive the adjudication surface
from a holistic problem-space map, repair the prior cycle's failure
modes (sourced≠true, frame narrowing, asymmetric retroactivity —
README ground rule 4), and re-gate the plan. Like its siblings, this
memo is withheld from blind reviewers.*

## Phase 0 — map, binding answers, probes (before any pin froze)

1. **Problem-space map** authored first:
   `research/2026-07-12-adjudication-surface-problem-space.md` — the
   surface's UI-agnostic requirements, nine circumstance facts, the
   full option space priced (Textual TUI / localhost web / hybrids /
   do-less baseline) on fit-for-us criteria.
2. **User values routed early and BINDING** (one AskUserQuestion
   round, map §6): V1 platform = localhost server-rendered web app;
   V2 residency = any dedicated window (terminal residency not part
   of the product); V3 pane engine = Agent SDK default (original
   directive restored); V4 standing weighting = DX & agent leverage.
3. **Discriminating SDK probes run empirically before pins froze**
   (`research/2026-07-12-sdk-pane-probes.md`): streaming chunk-level
   ~5 Hz VERIFIED; `can_use_tool` exact-file gating VERIFIED; three
   pin-changing footguns (ClaudeSDKClient-only, `allowed_tools`
   shadowing, `setting_sources` unset loads the full user env).
4. **09/10 rewritten + renamed** (`09-surface-spec.md`,
   `10-surface-build-plan.md`, commit `4ab5f50`): every TUI-era
   substrate pin (P1-x/P2-x/P3-x closures) carried forward
   explicitly; socket/launcher subsystems deleted; corpus amendments
   landed (02 §3, 03 G-3 row, 07 platform+engine, 08 terminology +
   launcher rename, README).

## Phase A — 09 design review

- **Review (fresh Fable, blind to reviews/, framing lens + empirical
  mandate per ground rule 4): FAIL** — 3 gates, 5 minors. The
  reviewer ran their own live tests (markdown-it-py default preset
  passes raw HTML; `ClaudeAgentOptions` introspection;
  chromium `--app`/`--class` under live Hyprland).
  - **W-1 (gate)**: render-path XSS un-priced — records/pane blocks
    are adversarial content; unsanitized markdown → script inside the
    token-cookied origin defeats every mutating-route control and the
    P1 human-gate. Framing-lens finding: the problem-space map's C6
    security pricing omitted this class entirely.
  - **W-2 (gate)**: SDK caps/fallback deferred to build though
    locally testable now — and the TUI-era grounding memo still
    carried the falsified "SDK has no fallback" claim. Reviewer's own
    introspection on 0.2.116: `fallback_model`, `max_turns`,
    `max_budget_usd` all present.
  - **W-3 (gate)**: pane read scope contradictory across 09 §4.3 /
    10 §1 / cwd reality; probe 2 shows reads inside cwd never reach
    the callback, so the written scope was unenforceable as stated.
  - Minors W-4..W-8: dead wrapper-cap path; bulk-loop terminal-push
    no-op race unnamed; "unanalyzed" double-naming; window-class
    mechanism confirmation + Firefox note; W-8 detect-at-checkpoint
    residual unnamed in 09 §4.3.
- **Remediation (orchestrator, same day)**: all eight.
  W-1 → 09 §3 render-path pins (autoescape ON, markdown `html=False`
  everywhere incl. SSE frames, pinned CSP header) + 09 §6 risk row +
  10 §1 security row + T-A escape/CSP tests + dated map C6
  correction (pricing honesty; delta judged not to disturb V1).
  W-2 → empirical result landed in 09 §4.1/§4.2 + dated CORRECTION in
  the grounding memo's model-control row + 10 ledger updated
  (pre-verified, re-verify at U5). W-3 → two-tier read-scope pin in
  09 §4.3 (cwd free-reads accepted; callback allows repo-tree reads,
  denies outside; user-scope CLAUDE.md via excerpt only) + 10 §1
  callback clause + T-B gains the outside-repo read refusal (now
  4 parts). W-4 → wrapper caps demoted to contingency. W-5 →
  terminal-push race named benign. W-6 → bucket group relabeled
  "no analysis yet". W-7 → verified mechanism + Firefox note in
  09 §1. W-8 → residual named in 09 §4.3, cross-ref 02 §2 P2-1a.
- **Gate re-check (same reviewer): pending.**

## Phase B — 10 + end-to-end corpus sweep + terminal verdict

Pending phase A gate close.
