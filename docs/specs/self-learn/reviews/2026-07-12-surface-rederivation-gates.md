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
- **Gate re-check (same reviewer): PASS (2026-07-13).** All eight
  dispositions VERIFIED-CLOSED — by trace, and by live test where
  load-bearing (caps introspection re-run; out-of-cwd read → callback
  routing AND deny enforcement proven — a mechanism probe 2 had not
  tested; renderer re-check). The reviewer independently endorsed the
  C6 framing judgment (render-path correction does not disturb the
  binding V1 answer). The remediation minted two new MINORs — the
  pattern holds, now 6-of-7 batches: **W-9** (CSP `style-src`
  consequences unpinned: Pygments must run class-mode + served
  stylesheet, no inline styles, `font-src` iff bundling) and **W-10**
  (dangling "P2-1a" anchor + non-verbatim 02 §2 quote). Both folded
  same-day (09 §3/§4.3, 10 §1), plus an attribution-honesty fix the
  re-check flagged as a caveat: 09 §4.3 no longer credits probe 2
  with the out-of-cwd routing fact — it credits the re-check's own
  live test.

## Phase B — 10 + end-to-end corpus sweep + terminal verdict

- **Reviewer**: a third, fresh Fable agent — no authorship, no
  remediation involvement in this cycle (terminal-verdict
  eligibility), blind to reviews/.
- **Review + TERMINAL VERDICT (2026-07-13): PASS — all three
  conditions, zero gates, nine minors.** The reviewer ran its own
  live verifications (full `ClaudeAgentOptions` introspection incl.
  the bonus `strict_mcp_config` presence + the missing
  session-persistence field; markdown-it `html=False` re-check; an
  independent re-run of the W-3 read-boundary mechanics with
  `permission_denials` evidence; the `hyprctl dispatch` exit-0
  gotcha; C1/C2/C8 circumstance facts ground-checked).
  - **T1 coherence PASS** — twelve contract families traced
    file:line across every speaking document, all AGREE; amendments
    landed; no stale renamed-doc references outside sanctioned
    history; correction chain intact at every site the falsified
    auth claim ever touched.
  - **T2 implementability PASS** — "a competent orchestrator running
    Opus 4.8/Sonnet 5-tier agents can build this from 10 + the
    corpus alone"; load-bearing pins independently re-verified true,
    the rest on the verify-at-build ledger with routed failures.
  - **T3 fit-for-circumstance PASS** — judged against C1–C9 (ground-
    checked) and the binding §6 answers; framing lens applied: the
    one unpriced region found (native GUI toolkits / editor-embedded
    surfaces) loses on the same decisive axes that eliminated the
    TUI, so it cannot disturb V1 — recorded as an observation, not a
    map-basis defect.
  - Minors X-1..X-9: env-var completeness (X-1), keymap `q` (X-2),
    launcher focus-detection gotcha — empirically demonstrated
    (X-3), unowned window-rule (X-4), missing browser-level
    acceptance channel (X-5), README fixtures-row tense (X-6),
    session-persistence fallback unnamed (X-7), XDG_RUNTIME_DIR
    playbook hole (X-8), no owning assertion for the W-9 Pygments
    pin (X-9).
- **Post-verdict fold (orchestrator, same day): all nine minors
  landed** (09 §4.4/§1-keymap-consumer, 10 §1 launcher detection +
  keymap + ledger + T-A/U7/U10/U11 + §5 playbook, README fixtures
  row). Folds sent back to the terminal reviewer for disposition
  verification — never self-certify, even after a PASS.
- **Fold verification (same terminal reviewer, 2026-07-13): all nine
  X-1..X-9 VERIFIED-CLOSED; the terminal verdict (T1/T2/T3 PASS)
  explicitly affirmed as standing over the folded state (826114a).**
  The fold minted three wording/enumeration residuals — the pattern
  in miniature, tally now 7-of-8 batches: X-10 (09 §1 still called
  the window rule pinned while 10 demoted it to optional), X-11 (the
  new browser acceptance pass missing from §2/§6.1's merge-gate
  enumerations), X-12 (token-path fallback not stated as shared
  between server and launcher). All three folded same-day by
  applying the reviewer's own dispositions verbatim; the reviewer
  had already affirmed the verdict independent of them and none
  touches a contract family, security control, or tested behavior.

## Outcome

**CYCLE COMPLETE, TERMINAL VERDICT PASS (2026-07-13).** The G-3
adjudication surface is re-derived and gated: localhost
server-rendered web app + Agent SDK pane engine, per the user's four
binding answers, on an honestly priced option space, with every
decision-relevant testable claim empirically grounded before it
carried weight. Standing lessons upheld: never self-certify
(7-of-8 remediation batches minted findings, caught only by
independent re-check); the framing lens earns its keep (it caught
the render-path XSS as a *map mispricing*, not just a build gap);
reviewers now test claims instead of citing them (three of this
cycle's reviewers ran their own live probes unprompted beyond
mandate). Build remains gated on G-3's trigger (M2 shipped, worker
proven). Docs: 09-surface-spec.md · 10-surface-build-plan.md ·
problem-space map + 5 research memos.
