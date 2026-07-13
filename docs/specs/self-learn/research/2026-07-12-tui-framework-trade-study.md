# TUI framework trade study — self-learn adjudication console (2026-07-12)

*Produced by an independent research agent against live registries and
repos (GitHub API, npm, PyPI, official docs) on 2026-07-11/12. Every
version/maintenance/capability claim carries a primary source checked
this week; the agent's own not-fully-verified list is preserved at the
end. Shareable with blind reviewers (research/, not reviews/).*

*Orchestrator's notes: (1) the study was briefed with "kitty terminal";
the live terminal is **Ghostty** (environment memo) — immaterial to the
comparison (both are GPU terminals supporting the kitty keyboard
protocol). (2) The study weighted Agent SDK language alignment; the 09
engine decision (cli-subprocess default, SDK alternative) softens but
does not remove that axis — the `sdk` engine slot requires Python or TS,
and the stream-json protocol work is the same "sidecar" line item the
study priced for Go/Rust. Textual's margin rests on widget fit, testing,
and packaging, which are engine-independent.*

---

## The pivotal constraint, verified

The Claude Agent SDK officially exists in **Python and TypeScript only**: "programmable in Python and TypeScript" — https://code.claude.com/docs/en/agent-sdk/overview. Live packages: `@anthropic-ai/claude-agent-sdk` **0.3.207** (npm, 2026-07-10) and `claude-agent-sdk` **0.2.116** (PyPI, 2026-07-11) — both on near-daily release cadence. No Go or Rust Agent SDK exists in the `anthropics` org (`anthropic-sdk-go` is the low-level API client, not the agent loop). The SDK's **streaming input mode** is documented as "the preferred way... a long lived process that takes in user input, handles interruptions" — https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode — exactly the chat-pane shape. Output is async iteration (`async for message in query(...)` / `for await (const message of query(...))`).

This makes the field effectively Python (Textual) vs TypeScript (Ink, OpenTUI), with Go/Rust carrying a sidecar-subprocess tax.

## (a) Comparison table

Scores 1–5 per axis; weights implicit in narrative.

| Axis | Textual (Py) | Ink (TS) | OpenTUI (TS) | Bubble Tea (Go) | Ratatui (Rust) |
|---|---|---|---|---|---|
| Agent SDK language alignment | **5** (official Py SDK) | **5** (official TS SDK) | 4 (TS, but Bun-first runtime; SDK-on-Bun unverified) | 1 (sidecar) | 1 (sidecar) |
| Widget/layout fit (buckets/table/detail/split/action bar) | **5** | 3 (no native scroll; DIY lists/table) | **4.5** (ScrollBox, TextTable, Select, Input, first-party Diff) | 4 | 4 |
| Token-streaming rendering | **5** (purpose-built `MarkdownStream`) | 3 (re-render per chunk, DIY batching) | 4 (first-party Markdown renderable; no documented stream batcher) | 3 (glamour re-render) | 3 |
| Long-resident stability | 4 | 4 (v7 alt-screen is new but core) | 3 (young; opencode dogfoods it) | 5 | 5 |
| Maintenance health, mid-2026 | 3.5 (active, monthly releases, **bus factor 1**) | **5** (sindresorhus-stewarded, 22 releases/12mo, 29 open issues) | 3.5 (company-backed, bus factor ~2, pre-1.0 churn) | 5 (v2 line, whole Charm stack coordinated) | 5 |
| Testing story | **5** (Pilot + snapshot plugin) | 3 (ink-testing-library dormant since 2024; ink-7 compat undeclared) | 4 (first-party `createTestRenderer`, mockInput, snapshots) | 4 | 4 |
| Packaging fit (~/bin shebang, uv/node) | **5** (PEP 723 + `uv run`, officially demonstrated) | 3.5 (JSX not erasable → tsx shebang or bundle) | 2.5 (Bun, or Node ≥26.4 + `--experimental-ffi`) | 4 (static binary) | 4 (static binary) |
| Solo-maintainer burden | **5** (least code for these screens) | 3 (assemble scroll/lists/markdown/diff yourself) | 3.5 (good components, moving 0.x target) | 2 (+ sidecar protocol) | 1.5 (+ sidecar, Rust) |
| Diff/markdown/syntax ecosystem | **5** (Rich Syntax + Pygments DiffLexer, tree-sitter TextArea, Markdown widget) | 2.5 (marked-terminal 2025; diff/highlight components stale or unproven) | 4.5 (first-party `Diff`, `Code` w/ tree-sitter, `Markdown`) | 3.5 (glamour v2) | 3 (tui-markdown + syntect) |
| **Total (unweighted)** | **42.5** | 32 | 33.5 | 31.5 | 30.5 |

## (b) Per-candidate narratives

### Textual — v8.2.8 (2026-06-30), actively maintained by one person

**Maintenance reality.** Textualize the company announced wind-down 2025-05-07 with **no acquisition**; "Textual will live on as an Open Source project... Will McGugan will personally maintain both Textual and Rich" — https://textual.textualize.io/blog/2025/05/07/the-future-of-textualize/. Fourteen months later that promise is being kept: v8.2.8 shipped 2026-06-30 (https://github.com/Textualize/textual/releases, PyPI confirms), repo pushed 2026-07-11, ~monthly releases through 2026 — but **99 of the last 100 commits are McGugan's** (GitHub commits API), the former team is gone from the commit stream, and 2026 issues are opening slightly faster than closing (98 opened vs 65 closed, 216 open). Verdict: healthy activity, genuine bus-factor-1 risk. Also note churn: five major versions in 12 months (v4→v8) — pin the version, expect occasional migration work.

**Fit for these exact screens: the best in the field.**
- Buckets page: `DataTable`/`OptionList`; bucket page: `ListView` with grouped items — all first-party (https://textual.textualize.io/widget_gallery/).
- Detail page: `TextArea` with tree-sitter highlighting includes a **YAML grammar** in the `[syntax]` extra (PyPI metadata); the unified diff renders via Rich `Syntax` with Pygments' **DiffLexer** (aliases `diff, udiff` — verified at https://pygments.org/docs/lexers/; Pygments is already a core Textual dependency).
- Modal-free action bar: `Footer` + key `BINDINGS`; screen stack (`push_screen`, `switch_mode`) covers front/bucket/detail navigation — https://textual.textualize.io/guide/screens/.
- **Agent pane: this is where Textual is uniquely strong.** `Markdown.get_stream()` returns a `MarkdownStream` batching object added (v5.0.0) specifically because raw appends top out ~20/sec against LLM token rates — https://textual.textualize.io/widgets/markdown/. Feed it from an async worker iterating `ClaudeSDKClient.receive_response()`. Anthropic's Python SDK streaming-input mode + Textual's `@work` workers (https://textual.textualize.io/guide/workers/) are both documented primitives; the official blog even walks through an LLM chat TUI run as a PEP 723 single file via `uv run` — https://textual.textualize.io/blog/2024/09/15/anatomy-of-a-textual-user-interface/.

**Resident behavior.** Alt-screen default; resize was actively optimized in 2026 (v8.2.2/v8.2.3 are literally named resize releases); issue-tracker search shows no idle-CPU or memory-leak pattern (absence of evidence, flagged as such). `App.suspend()` exists. File watching: nothing built in — use `watchfiles` 1.2.0 (2026-05-18, PyPI) inside a worker. Single-instance/deep-link: **no framework story** (verified nothing official exists); DIY with `asyncio.start_unix_server` on an XDG-runtime socket — ~30 lines, and the second invocation writes `--record <id>` to the socket.

**Testing/packaging.** `App.run_test()` + Pilot (`press`, `click`) — https://textual.textualize.io/guide/testing/; `pytest-textual-snapshot` 1.1.0 (PyPI). Entry point: `#!/usr/bin/env -S uv run --script` with a PEP 723 block, matching this repo's shebang-in-~/bin convention exactly.

### Ink — v7.1.0 (2026-06-17), excellently maintained, but you assemble the app yourself

**Maintenance: the healthiest of the viable candidates.** 22 npm releases in 12 months, v7.0.0 on 2026-04-08, only 29 open issues, 3.59M weekly downloads. Notable nuance: creator vadimdemedes hasn't authored a commit since 2024-05-11; **sindresorhus** is now the top contributor and has cut every release since Sep 2025 (GitHub commits/contributors API, https://github.com/vadimdemedes/ink/releases). Claude Code itself is React+Ink+Yoga (https://newsletter.pragmaticengineer.com/p/how-claude-code-is-built); Gemini CLI uses a **patched Ink fork** (`npm:@jrichman/ink@6.6.9` in its package.json) — a mild signal that big fullscreen apps need patches; Codex CLI left Ink for Rust entirely (https://github.com/openai/codex/discussions/1174).

**Resident-app fit changed materially in 2026.** v7 added native `alternateScreen: true`, `useWindowSize()`, `suspendTerminal()`, **kitty keyboard protocol support**, bracketed paste, and `incrementalRendering` — https://github.com/vadimdemedes/ink/releases/tag/v7.0.0. Flicker is actively worked but not closed (open issues #889, #935).

**Where it costs you.** No native scroll — `overflow` is `visible|hidden` only; scrolling primitives are an open request (#765, citing Gemini CLI's workaround). Long lists: window manually (`ink-virtual-list` exists but is at 143 downloads/week — unproven). Markdown: the Ink-specific packages are stale (ink-markdown last published 2023); the real route is `marked` + `marked-terminal` 7.3.0 (2025-01, 4.9M dl/wk) rendered into `<Text>`, re-parsing the in-progress message per chunk — no batching primitive like MarkdownStream. Diff: no established component; compute with `jsdiff` 9.0.0 (2026-04) and color it yourself. Widgets: `ink-text-input` (2024) and `@inkjs/ui` (2024) are widely used but unrefreshed. Testing: `ink-testing-library` 4.0.0 is from 2024-05, ink-7 compatibility only inferable from loose peer ranges. Packaging: JSX is **not** erasable syntax, so bare `node app.tsx` fails even on Node 24 native type-stripping (https://nodejs.org/en/learn/typescript/run-natively) — you shebang `tsx` (4.23.1, actively maintained) or bundle.

Net: Ink's core is in the best institutional health here, but for *this* app you would hand-build the scroll containers, list windowing, markdown streaming batcher, and diff renderer that Textual (and OpenTUI) ship first-party.

### OpenTUI — v0.4.3 (2026-07-03), the interesting dark horse

Now at **github.com/anomalyco/opentui** (SST rebranded/consolidated as Anomaly; `sst/opentui` 301-redirects). Zig native core + TypeScript bindings, Yoga flexbox, React/Solid renderers (Vue binding abandoned at 0.1.25/2025-09). 12,435 stars in under a year; 477 commits on main in 2026; real docs site at https://opentui.com/docs/getting-started; **powers opencode in production** (opencode's workspace pins `@opentui/*` 0.4.3 — https://github.com/anomalyco/opencode).

**Its component set is actually the best first-party match for the detail screen:** `Markdown` (marked-based), `Code` (tree-sitter highlighting), **`Diff`**, `ScrollBox`, `TextTable`, `Select`, `Input`/`Textarea` — all in core (https://github.com/anomalyco/opentui/tree/main/packages/core/src/renderables). First-party test harness (`createTestRenderer`, `mockInput`, snapshot capture) documented.

**Why it isn't the pick:** the runtime story. It's Bun-first (`bun-ffi-structs` dependency); **Node support landed 2026-06-09 (v0.4.0) and requires Node ≥26.4 with `--experimental-ffi`** (https://opentui.com/docs/getting-started, https://github.com/anomalyco/opentui/releases/tag/v0.4.0) — four weeks old, with an immediate fix-up PR. Whether `@anthropic-ai/claude-agent-sdk` runs correctly under Bun is **unverified** — that's the exact pairing the agent pane needs. Add pre-1.0 with loose semver (three 0.x minors in six weeks; opencode pins exact versions), a bus factor of ~2 (two contributors ≈80% of commits), and 111 open PRs. Production-viable *if you adopt Bun and pin hard*; too much platform risk for a days-resident personal tool today. Worth rechecking in 6–12 months.

### Bubble Tea (Go) and Ratatui (Rust) — excellent, ruled out on sidecar cost

- **Bubble Tea v2.0.8 (2026-07-03)**, with bubbles v2.1.1, lipgloss v2.0.5, glamour v2.0.1 all cut within the last month — arguably the healthiest project in the study (https://github.com/charmbracelet/bubbletea/releases).
- **Ratatui v0.30.2 (2026-06-19)**, active, pre-1.0; markdown via third-party `tui-markdown` 0.3.8 (https://github.com/ratatui/ratatui/releases, https://crates.io/api/v1/crates/tui-markdown).

Both would require a Python/TS **sidecar subprocess** for the agent pane: spawn it, define a JSONL protocol over stdio for token stream + chat input + interrupts + permission prompts, supervise its lifecycle inside a days-resident app, and debug across two runtimes. For a solo-maintained personal tool, that's the single largest line item in the whole study — you'd be building a worse version of what the SDK's streaming mode gives Python/TS for free. Ruled out honestly: superior frameworks, wrong side of the constraint.

### Others, one paragraph each

- **prompt_toolkit 3.0.52** (2025-08-27; last commit 2026-05-14): genuinely capable of full-screen apps (https://python-prompt-toolkit.readthedocs.io/en/master/pages/full_screen_apps.html) and rock-stable, but in slow stewardship mode (no release in ~10.5 months) and deliberately lower-level — no markdown widget, no reactive framework; you'd rebuild a third of Textual by hand. Choose it only if Textual's abstraction ever became the problem.
- **blessed / neo-blessed / react-blessed**: last real releases 2015 / 2018 / 2021 respectively (npm publish dates; chjj/blessed last commit 2016-01-04). Dead for a decade in blessed's case; pre-date modern terminal features. Ruled out without ceremony.
- No other notable new Python/TS framework surfaced in the 2025–2026 window beyond OpenTUI itself.

## (c) Recommendation

**Pick Textual, on Python, with `claude-agent-sdk`.** It is the only candidate where every screen in the spec maps to a shipped, documented widget — including the two hardest ones: the token-streamed agent pane (`MarkdownStream` exists *specifically* for LLM-rate output) and the syntax-highlighted diff (Pygments DiffLexer via Rich, already a core dependency). It has the best testing story (Pilot + snapshots), and its packaging path (`uv run` + PEP 723 shebang) drops directly into the ~/bin conventions of this repo. Estimated build effort is materially lowest. Mitigate its two real risks mechanically: **pin the major version** (the v4→v8 churn is real) and accept the bus-factor-1 exposure documented above.

**Runner-up: Ink 7.** It wins if any of these conditions hold:
1. **Textual's maintenance visibly degrades** — concretely: no release for 6+ months, or McGugan announces stepping back again. Ink's stewardship (sindresorhus, near-monthly releases, Claude Code as an anchor consumer) is the most institutionally robust in the field.
2. **You decide the codebase must be TypeScript** (e.g., to share code with other Node tooling or the TS Agent SDK ecosystem).
3. **The UI simplifies** — if the console shrinks toward a scrolling chat-first layout (Claude Code's shape) rather than table/list/diff screens, Ink's weaknesses stop mattering.

**Watchlist: OpenTUI.** If it reaches 1.0 with stable Node support (or you're willing to standardize on Bun and verify the Agent SDK runs under it), its first-party Diff/Code/Markdown renderables make it a serious contender — re-evaluate in early 2027.

## (d) Genuinely close?

**No — not on fit. One clearly dominates for this application, with a single caveat a human should own.** Textual beats Ink on six of nine axes and ties on language alignment; Ink's only clear win is maintenance robustness. That gap is not marginal: for these specific screens, Ink requires you to build scroll containers, list windowing, a markdown stream batcher, and a diff renderer that Textual ships and documents today, while its own auxiliary ecosystem (testing library, text-input, markdown components) is 2023–2024 vintage.

The one judgment that legitimately belongs to a human: **how heavily to weight Textual's bus factor of one against Ink's institutional health**, for a tool you intend to run for years. If you weight 5-year longevity above build cost and fit, the ranking flips — that is a values choice, not a facts gap. On the facts as of 2026-07-12, Textual is the recommendation; a switch to Ink later would be a rewrite of the view layer only, since the Agent SDK, file formats, and `self-learn` CLI sit behind the UI in either design.

---

**Flagged as not fully verified:** multi-day-resident behavior for any framework (no positive evidence anywhere, only absence of complaint patterns); ink-testing-library's formal Ink-7 compatibility; Agent SDK under Bun; contents of Gemini CLI's Ink patches; Claude Code's internal rendering details (secondary teardowns only). Everything else above carries a primary source checked live this week.
