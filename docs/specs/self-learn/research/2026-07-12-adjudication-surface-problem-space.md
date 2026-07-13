# Adjudication surface — problem-space map (2026-07-12)

*Authored for the post-correction /goal cycle that reopened 09/10's
platform/framework/engine decisions. Per README ground rule 4: map the
problem space before comparing options; criteria are fit-for-us, not
generic bests. Shareable with blind reviewers. Inputs:
`07-review-ui.md` (vision), `2026-07-12-tui-vs-web-dx-study.md`,
`2026-07-12-sdk-auth-empirical-test.md`,
`2026-07-12-tui-framework-trade-study.md`, 09 §4 (engine table),
`06-horizon.md` (team scale).*

## 1. What the surface must do (UI-agnostic — the invariant substrate)

These requirements come from 07 §1–5 and survived every gate; they are
the *problem*, independent of any platform answer:

1. **Attend-at-convenience**: an ambient list, never a popup treadmill,
   never an invisible backlog. Notifications carry event + standing
   aggregate; ignoring one costs nothing.
2. **Deep-link**: notification → the specific decision, in ≤ a click.
3. **Three surfaces**: front (bucket walk) · bucket (grouped by
   proposed destination, homogeneous groups collapse to one bulk
   decision) · detail (finding, diff preview, rationale, provenance).
4. **Resolution**: Approve / Deny / Iterate / Defer (+ graduate),
   optional `resolution_note`; all mechanics live in CLI verbs — the
   surface is a skin (07 §4 contract 1).
5. **Iterate = embedded agent session**: fresh per item, stable shared
   doctrine prefix, agent edits files / never routes (P1), outcomes
   land in the ledger not the pane.
6. **Files as truth**: any concurrent surface (slash review, teammate)
   stays coherent because files are the only state.
7. **Volume envelope**: several proposals/day from multiple concurrent
   CC instances (heavy-use sizing, never E-2's ~1/month floor); team
   horizon ~5–6 users (06) with per-user surfaces over a shared repo.
8. **Non-goals**: not a monitoring platform; no approval bypass; not a
   fix for review avoidance.

Everything above transfers verbatim to any platform: notification ids
become URL paths or socket messages; the engine subprocess code is
identical asyncio either way (DX study 6c).

## 2. The circumstance (this user, this workflow, this maintenance reality)

C1. **Heavy terminal user on Hyprland + Ghostty**, keyboard-first
    habits. A tiling WM makes *any* dedicated window cheap — a pinned
    terminal and a chromeless `--app=http://localhost:PORT` browser
    window are both one window rule away. (Grounding memo.)
C2. **Development is agent-assisted, permanently.** This tool will be
    built and continuously modified by Claude agents; the repo's
    CLAUDE.md records that the user "actively edits these skills —
    daily tools, improved constantly." Agent leverage (training-data
    depth, the Playwright-MCP/claude-in-chrome see-judge-fix loop) is
    therefore a first-order *maintenance* cost, not a build-week
    nicety. (DX study axis 3.)
C3. **Maintenance horizon is years, style is boring-and-stable.** The
    user's infra pattern is vendored/pinned, systemd --user services
    already run twice in this repo (autosync watcher, cron-claude) —
    the web option's residency model is a solved pattern here; the
    TUI's days-resident stability is unverifiable for every framework
    (trade study).
C4. **Solo now, team horizon 06.** Both options stay per-user local in
    v1. At team scale a served surface generalizes more naturally
    (same app bound wider or per-user instances) while a TUI is
    strictly per-machine — a lean, not a decider.
C5. **Deep-link is a core interaction, not a feature.** The TUI needs
    a Unix-socket single-instance protocol + hyprctl focus dance; the
    web version's deep-link is `xdg-open <URL>` and the server *is*
    the single instance (DX study 6d/6e — two subsystems erased).
C6. **Security posture**: single-user Linux box. A 127.0.0.1 server
    that mutates state and spawns Claude subprocesses adds a real but
    small, standard surface (bind-local + Host validation + bearer
    token + POST-only ≈ 30 lines). The TUI has zero network surface.
C7. **Engine facts (post-correction)**: SDK and CLI ride the same
    credential chain, subscription included — auth/economics is VOID
    as a discriminator. Both engines must run with emptied
    `--setting-sources` (measured 68k-token cache write otherwise).
    Genuine remaining deltas: CLI has live-verified token streaming +
    `--fallback-model`; SDK has `canUseTool` (in-process exact-file
    permission enforcement for the pane charter, vs flag rules) and
    typed/semver'd interface, at the cost of a second dependency.
    The original user directive named an SDK pane.
C8. **Sunk cost is at its lifetime minimum.** No code exists; a
    platform switch discards only the view-layer halves of 09/10.
    This is the cheapest the reopened decision will ever be.
C9. **07 §3's "the resident window is the point"** is a recorded
    vision sentence, not a validated requirement. The need behind it
    decomposes into (a) ambient standing presence and (b) instant
    attend — which several window arrangements satisfy. Whether
    *terminal residency itself* is part of the product is a values
    question only the user can answer (routed, below).

## 3. The option space, priced for this circumstance

**A. Textual TUI** (09/10 as gated). Fit: keyboard ownership total;
zero network surface; MarkdownStream/DataTable prebuilt; plans are
pin-complete today. Costs *for us*: weakest agent-assisted dev loop
(niche + churned API, bespoke SVG/tmux verification); bus-factor-1
framework with v4→v8-in-12-months history against a years-long
horizon; two bespoke subsystems (socket deep-link, residency) the web
never needs; styling ceiling (TCSS on a character grid).

**B. Localhost server-rendered web app** (FastAPI + Jinja partials +
vendored htmx 2.0.9 + SSE + Pygments; systemd --user; 127.0.0.1;
chromeless `--app` window + Hyprland rule for dedicated-window feel).
Fit: decisive winner on styling, iteration, agent leverage,
maintainability, testing, deep-link (DX study a-table); stack is the
boring-stable idiom this repo already lives in (C3); two TUI
subsystems vanish (C5). Costs *for us*: ~90% keyboard ownership
(browser owns Ctrl+W/T/N/L; Vimium exclusion needed); ~30-line
security mitigation that must actually be written (C6); re-implement
streaming-markdown + table rendering (a day; the most-implemented UI
pattern of 2024–26).

**C. Hybrids** — textual-serve (transport only, no DX gain),
textual-web (dormant), NiceGUI/FastHTML (niche idioms reintroduce the
agent-leverage problem). **Ruled out** (DX study, live-verified); a
reviewer may challenge this closure.

**D. Do-less baseline** — ship M1 slash review + M2 notifications;
defer the surface decision until usage data shows what is actually
missing. Honest pricing: build was *already* gated on M2 (G-3
trigger), so D defers only the *decision*, not just the build. For
it: decides with data, not projection. Against it: the decision
context (two empirical memos, DX study, this map, gate history) is
hot now and decays; a later cycle re-pays it. D is a scheduling
values call, orthogonal to A-vs-B on the merits.

## 4. What this map does not decide (routed to the user, binding)

The map narrows honestly: on the recorded DX/maintenance axes B
dominates; A survives on keyboard ownership, network surface, and
terminal-native identity — **a values weighting, not a fact deficit**.
Accordingly these go to the user *before anything freezes*:

V1. Platform: A / B / D.
V2. The C9 residency question: is terminal residency itself part of
    the product, or is ambient-presence-in-a-dedicated-window the real
    requirement?
V3. Pane engine default: SDK (directive origin, canUseTool) vs CLI
    (verified streaming, one engine family) vs settle-by-test.
V4. Standing weighting for future conflicts: keyboard/security vs
    DX/agent-leverage.

## 5. Discriminating unknowns (test only if live after V-answers)

- SDK partial-message streaming granularity (docs silent) — matters
  only if V3 ≠ CLI-default.
- `canUseTool` exact-file callback behavior under the pane charter —
  same condition.
- Browser-window keyboard capture completeness under Hyprland
  (`--app` window + keydown handling vs the Ctrl+W hazard) — matters
  only if V1 = B and V4 weights keyboard heavily.
- Textual long-residency stability — untestable cheaply (trade
  study); remains a recorded risk, not a testable claim.

Testing serves this map; nothing above is a prerequisite to asking
the V-questions.
