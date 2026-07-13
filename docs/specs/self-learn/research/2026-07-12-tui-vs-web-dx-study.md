# Textual TUI vs localhost web app — developer-experience study (2026-07-12)

*User-commissioned after the G-3 gates closed: "which one is easier to
develop for — style, maintain, adapt, customize?" (explicitly NOT
"which is lighter"). Produced by an independent research agent; facts
live-verified 2026-07-12, DX assessments labeled judgment. The prior
framework trade study answered a different question (which TUI
framework) under a TUI-only mandate — this study prices the web option
it never evaluated. Shareable with blind reviewers.*

**The web comparator**: FastAPI/Starlette + Jinja partials + HTMX 2.x
(vendored, no build step) + Pygments server-side + SSE, as a
`systemd --user` service on 127.0.0.1 — deliberately NOT a Vite/React
SPA (which would lose the churn/dependency axes this stack wins).

## (a) Axis table

| # | Axis | Winner | Margin |
|---|------|--------|--------|
| 1 | Styling & visual polish | **Web** | Decisive |
| 2 | Iteration speed | **Web** | Clear, smaller than assumed |
| 3 | AI-agent development leverage | **Web** | Decisive, one honest counterweight |
| 4 | Maintainability over years | **Web** (server-rendered flavor only) | Clear |
| 5 | Adaptation & customization | **Web**, except keyboard ownership → Textual | Split |
| 6a | Token-stream rendering | **Textual** (narrowly) | MarkdownStream purpose-built; SSE+append well-trodden |
| 6b | File-watch → UI refresh | Tie | Same `watchfiles` either way |
| 6c | Subprocess orchestration | Tie by construction | Identical asyncio code |
| 6d | Deep-link from notification | **Web** | Decisive — the TUI's worst hard part vanishes |
| 6e | Session/window lifecycle | **Web** | Clear |
| 7 | Testing brittleness | **Web** | Clear (judgment) |
| 8 | Security/exposure surface | **Textual** | Real but mitigable |

## (b) Key narratives

**Styling (decisive, web).** TCSS is a competent CSS subset on a
character-cell grid: no typography, cell-quantized spacing, Nerd-Font
iconography. The browser has real fonts, `prefers-color-scheme`,
Pygments rendering the same YAML/diff lexers to a better canvas.
Streaming markdown chat panes are the most-implemented UI pattern of
2024–2026.

**AI-agent leverage (the heart of the question — web, decisively).**
(1) Training-data depth: HTML/CSS/JS/HTMX is the deepest well any
coding model has; Textual is niche AND churned (v4→v8 in 12 months), so
agents reliably emit stale-API Textual code and burn iterations against
current docs. (2) The see-judge-fix loop: this environment already has
Playwright MCP + claude-in-chrome — an agent can navigate to
localhost, screenshot, read the console, click, iterate natively; the
TUI equivalent (SVG snapshots, tmux driving) is bespoke and flakier,
and browser screenshots are easier for the human to judge too.
(3) Component vocabulary: Tailwind/daisyUI/plain-CSS patterns the agent
has seen millions of times vs a fixed widget set whose internals it
half-knows. Honest counterweight: for these exact screens Textual
ships the two hardest components (MarkdownStream, DataTable) — less
novel UI code to write at all — but "less code to generate" matters
less than "code the agent generates correctly and can visually
verify"; the HTMX-no-build-step constraint contains web-side
over-generation.

**Maintainability (clear, web — both sides' warts shown).** Textual
8.2.8 is genuinely alive (released 2026-06-30, pushed 2026-07-11) but
bus-factor-1 post-Textualize (McGugan 7,049 commits; former team gone),
issues opening faster than closing, v4→v8 churn recent. HTML/CSS/HTTP/
SSE don't churn; FastAPI 0.139.0 / uvicorn 0.51.0 are boring and huge.
Wart disclosed: htmx v4.0.0-beta5 (2026-06-26) is a breaking rewrite in
flight — but htmx 2.0.9 stays the maintained stable line, vendorable as
one ~50 KB file, upgrade never or on your own schedule.

**Keyboard-first in a browser (the honest split).** Gmail/Linear/GitHub
prove single-key accelerator UIs work (~40 lines of keydown handling,
defer when focus is in the chat input). Real caveats: the browser owns
Ctrl+W/T/N/L (Ctrl+W closes the tab — a muscle-memory hazard), and
Vimium-class extensions need a localhost exclusion. A chromeless
`--app=http://localhost:PORT` window + Hyprland window rule gives a
dedicated-window feel. Textual owns the whole keyboard; the web version
is ~90% as good with two known caveats. (Judgment.)

**Where the web erases two whole subsystems (6d/6e).** The TUI plan
needs a single-instance Unix socket, a navigate protocol, and a
hyprctl focus dance for swaync deep-links; the web version's deep-link
is `xdg-open "http://localhost:PORT/record/<id>"` — the server IS the
single instance, tabs are disposable, and "days-resident process
stability" (unverifiable for every TUI framework per the trade study)
becomes a systemd user service, a problem this repo already solves
twice (autosync watcher, cron-claude).

**Testing (judgment, web).** httpx against Starlette routes asserting
returned HTML partials is fast, deterministic, upgrade-proof; Textual
Pilot is good but SVG snapshot baselines invalidate wholesale on
framework rendering changes — brittleness that compounds with a
churn-prone bus-factor-1 framework.

**Security (Textual).** A TUI has zero network surface. A localhost
server that mutates state and spawns Claude subprocesses faces local
processes + CSRF/DNS-rebinding; mitigation is standard and small
(bind 127.0.0.1, Host-header validation, random bearer token in the
xdg-open URL + cookie, POST-only mutations — ~30 lines), but it is a
real difference the TUI never thinks about.

**Hybrids (live-verified).** textual-serve 1.1.3 (2025-11-01, quiet 8
months): transport only — same character grid in a tab, none of the
styling/devtools/agent-leverage gains. textual-web 0.8.0: dormant since
2024-08-30, ruled out. NiceGUI 3.14.0 (alive, company-backed, ~2
maintainers): viable middle path but reintroduces the niche-idiom
problem (Vue/Quasar under an abstraction) — not optimal for agent
leverage. FastHTML 0.14.6 (active daily, 0.x): idiosyncratic FT style
agents fumble; plain FastAPI+Jinja is the same thing with maximal
training-data depth.

## (c) Bottom line (verbatim from the study)

On the question asked — easier to style, maintain, adapt, customize,
iterate on, extend, for a solo maintainer working heavily with AI
agents — **the server-rendered localhost web app wins, and not
narrowly.** Textual's surviving advantages: total keyboard ownership,
zero network surface, MarkdownStream/DataTable prebuilt, PEP 723
single-file elegance, terminal-native identity. The first two are
real; the middle two are re-implementable in a day; the last is a
values preference, not a DX fact.

**Reopen the Textual decision? The study says yes — this is the
cheapest it will ever be**: no code exists; the switch discards only
the view-layer halves of 09/10; every 07 §4 substrate contract
transfers verbatim (notification ids become URL paths — simpler); the
engine decision (claude -p stream-json) is identical server-side;
interaction model 07 §1–3 is UI-agnostic. The one thing that should
keep Textual: the user deciding a resident terminal window IS the
product — a legitimate values call the vision doc leans toward ("the
resident window is the point"), now to be made knowing the DX price
the TUI-only mandate previously hid.

## (d) Sources

Textual PyPI 8.2.8 + GitHub contributors API · textual-serve 1.1.3 ·
textual-web 0.8.0 (dormant) · NiceGUI 3.14.0 · FastHTML 0.14.6 · htmx
releases (2.0.9 stable / 4.0.0-beta5) · FastAPI 0.139.0 · uvicorn
0.51.0 · watchfiles 1.2.0 — all checked live 2026-07-12; internal:
`2026-07-12-tui-framework-trade-study.md`, `07-review-ui.md`.
