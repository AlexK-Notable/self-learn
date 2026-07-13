# 09 — Adjudication surface: full design spec (G-3, web revision)

*Rewritten 2026-07-12 in the post-correction /goal cycle. This revision
supersedes the Textual-TUI revision of this document (git history
through `1ce408c`; renamed from `09-tui-spec.md`). The platform was
re-decided from a holistic problem-space map with the user's values
routed first and binding:
`research/2026-07-12-adjudication-surface-problem-space.md` §6 —
**V1 platform = localhost server-rendered web app; V2 the residency
requirement is ambient presence in ANY dedicated window (terminal
residency is not part of the product); V3 pane engine default = Agent
SDK; V4 standing weighting = DX & agent leverage.** Grounding:
`research/2026-07-12-tui-vs-web-dx-study.md`,
`research/2026-07-12-sdk-auth-empirical-test.md`,
`research/2026-07-12-sdk-pane-probes.md` (SDK streaming +
`canUseTool`, run before these pins froze),
`research/2026-07-12-tui-environment-grounding.md` (host facts).
**Every substrate pin that closed a gate finding in the TUI revision
(P1-x/P2-x/P3-x citations below) is carried forward deliberately** —
those findings were about adjudication semantics, not the view layer.*

**Authority.** This document is the **design authority for the G-3
adjudication surface**, sitting beside 00–07 in the corpus family:

- `07-review-ui.md` remains the vision record; this spec refines it.
  Where this spec details something 07 only sketched, this spec wins.
  Where this spec *changes* a 07 position, the change lands as a dated
  amendment in 07 itself (nothing wins silently) — §10.
- The six don't-subvert contracts (07 §4), P1/P2/P9,
  CLI-owns-all-resolution-mechanics, and the pane agent having no path
  to `route` are **invariants** here; every mechanism below is designed
  inside them.
- `08-build-plan.md` remains execution authority for M1–M3 and owner of
  the shared pins (`--json` shapes, `events.jsonl`, sentinel,
  routing-doctrine single-sourcing, `proposal validate`, `--no-push`).
  The surface **consumes, never redefines** those pins; extensions land
  as dated 08 edits per 08 §9 — never as a 09-local override.
- `10-surface-build-plan.md` is the execution authority for building
  what this spec designs. On conflict between 09 and 10, **09 wins and
  the conflict is a finding**.
- **The build itself stays gated on G-3's trigger** (M2 shipped, worker
  proven). This spec exists so the gate opens onto a plan, not onto a
  design conversation.

---

## 1. Interaction model

Everything in 07 §1 stands: attend-at-convenience, ambient informative
notifications carrying event + aggregate, deep-link to the decision,
ignoring costs nothing. This section pins the mechanics.

- **A dedicated window, keyboard-first, modal-free.** The surface is a
  server-rendered web app on 127.0.0.1 (§3). Its standing presentation
  is a **chromeless browser app window**
  (`--app=http://127.0.0.1:<port>/` with a stable window class) pinned
  by a Hyprland window rule — the dedicated-window feel the vision
  wanted, per the user's binding V2: ambient presence + instant attend,
  in *any* dedicated window. (Mechanism verified live 2026-07-12,
  phase-A reviewer: `chromium --app=… --class=self-learn-ui-test`
  under Hyprland 0.55.4 yields a native-Wayland window with that
  app_id, `xwayland: false` — `hyprctl dispatch focuswindow class:…`
  matches. Chromium-family only; Firefox has no `--app` equivalent
  and takes the plain-tab degradation, §5.) A plain browser tab works identically
  (degradation, §5); the server neither knows nor cares.
- **Keyboard accelerators, single keys only.** `j`/`k` (and arrows)
  move within a list, `Enter`/`l` drill in, `Esc`/`h` go up a level,
  action keys per below. Implemented as a small vendored `app.js`
  keydown handler (~40 lines) driven by a keymap table the server
  renders as JSON — one source of truth (10 §1). Keys are inert while
  focus is in a text input (the standard Gmail/Linear rule). **No
  Ctrl/Alt chords, ever** — the browser owns Ctrl+W/T/N/L and the
  Ctrl+W tab-close hazard is designed out by never training the hand
  toward chords. Install notes cover the Vimium-class-extension
  localhost exclusion (10 §1). A persistent footer shows the live
  keymap; `?` overlays the full reference (a layer, not a modal — any
  action key acts immediately from it).
- **Three screens, one stack, URLs as state**: Front `/` → Bucket
  `/bucket/<scope>/<name>` → Detail `/record/<id>`. The browser's
  back/forward IS the stack walk; `Esc`/`h` navigate up
  programmatically. A deep-link lands directly on Detail with the
  stack derivable from the URL, so up-navigation still walks sensibly.
- **Action keys on Detail** (also usable on a Bucket row): `a` approve
  (route), `d` deny (reject), `i` iterate (agent pane), `f` defer, `g`
  graduate (always available; highlighted when the proposal flags
  already-canon — §2.3), `o` override destination, `n` attach/edit a
  resolution note.
- **Arm-then-confirm, never modal-confirm** (carried): a resolution
  key **arms** the action bar — it shows exactly what will run (verb,
  id, destination, note present/absent) and `Enter` executes (a POST),
  any other key disarms. One extra keystroke, zero dialogs. Rationale
  unchanged: `route` compiles + commits + pushes — a mis-keyed
  single-stroke apply would demand supersession to unwind.
- **Flow after resolution**: the response swaps in the next pending
  record in the bucket (queue-clearing rhythm); if the bucket empties,
  return to Front with a one-line "bucket clear" banner. (Carried,
  P3-9.)
- **Notes** (`n`): an inline single-line input in the action bar
  (multi-line paste accepted); submitted with the armed verb as
  `--note`. The deny arm-state displays a gentle `n to say why` hint
  when no note is attached — hint only, never a gate (07: informative,
  not demanding).
- **Leaving**: close the window. The server is a `systemd --user`
  service and keeps running (it holds no state that isn't a file — §3);
  the notification → deep-link path reopens the window in one click.

## 2. Surfaces

### 2.1 Front page — the bucket walk

- A table of buckets with pending learnings: bucket name, scope
  (skill/project/user), pending count, oldest pending age, unanalyzed
  count (records with no *usable* analysis — the worker's own
  eligibility predicate: no schema-valid proposal, or hash-stale;
  pinned in 08 §1, one shared function — P2-4). Sorted oldest-first
  (queue health is age, not size — 04's time-to-triage metric).
- A **status strip**: worker last-run age, staleness alarm (worker
  overdue per its escalation pins), total pending, sentinel state if
  live (someone is mid-apply somewhere). Data: `status --json` plus the
  sentinel file's mtime read directly (read-only). No run *result*
  renders here — `worker_last_run` is the only pinned field and failed
  runs deliberately never touch it (08 T13); run forensics stay in
  `worker.log` (P1-7).
- Data source: `self-learn status --json` and `list --json` (08 §1
  pinned shapes, including the G-3 hardening fields already landed:
  `unanalyzed`, `proposal_fresh`, `destination`, `already_canon`,
  `--include-deferred`). The Front page never walks the ledger itself;
  a missing field is a dated 08 §1 edit, never server-side derivation.

### 2.2 Bucket page — grouped pending

- Records grouped by **proposed destination** — `proposal.destination`,
  02 §1's pinned enum (`skill-md | claude-md | reference | new-skill |
  hook`; headers are display labels, not a second vocabulary) — plus
  two synthetic groups: **"no analysis yet"** and **clusters**. (The
  group's display label is deliberately NOT "unanalyzed" — W-6,
  2026-07-12: the Front page's `unanalyzed` *count* uses the worker
  eligibility predicate, a different measure; distinct labels keep a
  future maintainer from conflating them.) Group
  precedence carried verbatim (P2-9): a record with *any* proposal file
  rows under its `destination` group — hash-stale ones carry the stale
  badge there — so the **"no analysis yet" group holds only records
  with no proposal file at all**; the Front page's `unanalyzed`
  *count* keeps the worker's eligibility predicate (a different
  measure, documented as such; distinct display labels per W-6).
  Groups render as sections, not tabs — one scroll.
- Row: id (short), age, title (first Trigger/Fact line — same
  derivation as `list --json .title`), sightings count, deferred badge
  when `deferred_until` is future (dimmed at the bottom; fetched via
  `list --json --include-deferred`), already-canon flag when
  `proposal.already_canon` is set (the structured field, P1-2 — never
  parsed from rationale prose, 07 §4 contract 2).
- **Cluster rows** (merge-proposals): one row per cluster showing
  member count and the suggested survivor; expanding (`Enter`) lists
  members inline (an htmx partial swap); the survivor choice is a
  selection within the expanded view; approve arms
  `route <survivor> --collapse <cluster-id>` (08 §7 pin, consumed
  verbatim).
- **Bulk collapse** (carried verbatim, P1-1): a homogeneous
  already-canon group renders as a single collapsible decision row
  ("N already-canon records — acknowledge all as canon"), arming a loop
  of per-record **`graduate <id>`** verbs — canon-supersession, never
  rejection (02 §2 pins `superseded_by: canon`; a graduation bulk
  landing as rejects would flood the rejected-proposal digest's
  negative-exemplar window). The server loops **individual pinned
  verbs**; it never invents a bulk CLI surface. Progress renders
  per item (SSE, §3); a mid-loop failure stops the loop with the
  failing id on screen. Loop latency uses the `--no-push` batch
  amendment + terminal `self-learn push` on exit **success or abort**
  (08 §1 as amended; P1-10/P1-16). One benign race, named (W-5,
  2026-07-12): each looped verb releases its own sentinel, so autosync
  may push the loop's commits between the last release and the
  terminal push — the terminal push then no-ops. Harmless (commits
  exist, files are truth); the terminal push is the guarantee of last
  resort, not the only publisher.

### 2.3 Detail page — one decision, fully explained

Three stacked regions (07 §2's finding / change / why), one scroll:

1. **Finding** — record Trigger + Instruction rendered from the
   pending file, evidence quotes with origins, provenance line (source,
   sightings, created, teacher at team scale).
2. **Change** — the diff preview from `proposals/lrn-<id>.diff` when
   present, Pygments-highlighted (`DiffLexer`, server-side), with the
   standing preview-honesty caption ("compilers regenerate from the
   record at apply time — this preview is advisory"; 02 §4). Proposal
   YAML renders via Pygments' YAML lexer. When the proposal exists but
   the diff sibling doesn't, render the proposal's proposed text; when
   nothing exists, render "no analysis yet — `i` to analyze now".
3. **Why** — proposal rationale, suggested destination (+ alternates),
   already-canon reasoning if set, `record_sha` freshness badge:
   **fresh** or **stale** (record edited since analysis — Iterate to
   regenerate). Staleness is computed by the CLI (`list --json
   .proposal_fresh`), never by the server hashing things itself.

Action bar at the bottom (armed states per §1). `o` (override
destination) cycles the destination the armed `route` will pass via
`--dest` — **among the parameter-free values only** (`skill-md`,
`claude-md`, `reference`). `new-skill:<name>` and `hook` need
structure a cycling key cannot supply: reachable via Iterate or the
CLI directly; the cycle skips them with a footer hint saying so
(P1-9a, carried). The overridden value renders distinctly (analyst's
suggestion vs. override). `g` is always available on Detail for a
pending record and *highlighted* when `proposal.already_canon` is set
(affordance, not qualification logic; P1-9b, carried).

### 2.4 The iterate split

`i` splits Detail: left = the record/diff (live — it re-renders on the
pane agent's file edits, via the same SSE refresh channel), right =
the **agent pane** (§4): streaming transcript + a single-line input.
`Esc` with the pane focused interrupts the stream; `q` closes the
split (ending the session) and returns to full Detail. Approve/deny
keys stay live during iteration — arming works at any time, and
executing a resolution on the record under iteration auto-interrupts
the session first (the serialization rule, §3; P1-4 carried):
adjudication never waits for the agent to *finish*, only for its
bounded interrupt.

## 3. Process & data architecture

**The files are the only truth; the server is a reader and a
verb-invoker.** The server process never writes ledger files — not
records, not proposals, not canon. Exactly two kinds of writes exist
anywhere near it: the CLI verbs it spawns (which own
compile/commit/sentinel/push), and the pane agent's tool calls
(record/proposal edits, legal pre-routing per S-8, inside the
permission surface of §4.3).

- **The server**: FastAPI + uvicorn, a `systemd --user` service
  (`self-learn-ui.service` — the residency pattern this repo already
  runs twice: autosync watcher, cron-claude). Bind **127.0.0.1 only**,
  port `SELF_LEARN_UI_PORT` (default pinned in 10 §1). Server-rendered
  Jinja pages + htmx 2.x partial swaps (vendored single file — no
  build step, no CDN, works offline); Pygments and markdown rendering
  server-side. **The server IS the single instance** — the whole
  socket/takeover subsystem of the TUI revision is deleted, not
  ported. Multiple windows/tabs are legal concurrent readers; mutating
  actions serialize in the verb runner regardless of origin.
- **Security surface** (new obligation the TUI never had; priced in
  the problem-space map C6, accepted under binding V4): bind-local;
  reject requests whose `Host` isn't `127.0.0.1:<port>`/`localhost:
  <port>` (DNS-rebinding guard); a per-service-start random **bearer
  token** written 0600 to `$XDG_RUNTIME_DIR/self-learn/ui-token` —
  deep-links carry it once (`?token=…`), the server sets it as a
  SameSite=Strict cookie and redirects to the clean URL; every
  mutating route is **POST-only** and requires the cookie plus htmx's
  custom header (CSRF belt-and-braces). Failure renders a 403 page
  naming the launcher (`self-learn-ui-open`) as the fix.
  **Render-path hardening (added 2026-07-12, phase-A gate W-1 — the
  content this server renders is adversarial by construction: records
  are captured from sessions that read arbitrary web/tool content, and
  pane blocks are model output; unsanitized, a `<script>` payload in
  either executes inside the token-cookied origin, satisfies SameSite
  AND can set `HX-Request` — defeating every mutating-route control
  above and the P1 human-gate invariant itself. Empirically confirmed:
  markdown-it-py's default preset passes raw HTML through):**
  (a) Jinja autoescape ON for all templates (pinned, never disabled
  per-block); (b) markdown rendered with **`html=False`** — raw HTML
  in markdown is escaped, never passed through — for every
  file-sourced and pane-sourced render, page and SSE frame alike;
  (c) the only trusted raw-HTML injections are Pygments' own generated
  markup and the app's templates; (d) a **`Content-Security-Policy`
  response header on every response**: `default-src 'none';
  script-src 'self'; style-src 'self'; img-src 'self' data:;
  connect-src 'self'` (the app vendors its only script — inline
  scripts and external loads are dead even if something slips
  through). Pinned consequences of that header (W-9, 2026-07-13):
  **Pygments runs in class mode with a served stylesheet** — never
  `noclasses` inline-style mode, whose `style=""` spans the CSP would
  silently drop; **no inline `style=` attributes or `<style>` blocks
  anywhere** in templates/partials; fonts are `system-ui`-class
  system fonts — add `font-src 'self'` if and only if a font is ever
  bundled. All of the above is v1 scope, pinned in 10 §1 and tested
  in T-A (a record body containing `<script>`/`onerror` payloads must
  render escaped; the CSP header must be present). Together with the
  Host/token/POST pins this is **~50 lines of middleware + renderer
  configuration — in scope for v1, not optional hardening**.
- **Reads**: `list --json` / `status --json` for lists and counts; raw
  files (record md, proposal yaml, diff) for Detail, and raw
  `proposals/merge-*.yaml` for cluster groups (structured YAML —
  files-as-truth, not text-parsing; `list --json` stays record-level);
  `events.jsonl` only as a wake-up signal, never as state (08 §7.1).
- **Refresh**: `watchfiles` in the server over every bucket's
  `pending/` + `proposals/` dirs and `events.jsonl`, debounced
  ~300 ms; changes push an **SSE event** to connected pages, which
  re-request their current partial (htmx swap); a 10 s client poll is
  the fallback when SSE is disconnected. Any verb completion forces a
  push. External mutations (autosync pull, a concurrent
  `/self-learn:review` session) surface the same way. If the record
  open in Detail disappears (resolved elsewhere), Detail shows a
  "resolved elsewhere" banner and swaps to the Bucket page — **and if
  that record was under active iteration, the pane session is
  interrupted first (the banner implies the interrupt — P3-8,
  carried)**. No locks, no leases: concurrent surfaces stay coherent
  because files are the only truth (07 §3).
- **Verb invocation** (carried verbatim from the TUI revision — this
  block closed P1-4 and is view-layer-independent): subprocess
  `self-learn <verb> <id> [--dest …] [--note …] [--collapse …]`, exit
  status + stderr captured. Outcome renders from the verb's exit
  status and the subsequent file-state refresh — never by parsing
  human-formatted stdout (07 §4 contract 2). **Execution model**:
  verbs run async so the UI never blocks, but strictly **serialized —
  one verb subprocess at a time** server-wide (concurrent verbs would
  race the git index; multiple browser tabs make this MORE important,
  not less); while one runs, navigation stays live, further resolution
  submissions are disabled with a visible "applying…" state (SSE), and
  bulk loops render per-item progress. If the record under **active
  iteration** is resolved — by keypress *or* by a bulk loop reaching
  it — the check lives **at verb dispatch**, not at the keyboard: the
  server **first interrupts the session** (§4.2 ladder, ≤5 s worst
  case), then runs the verb — never concurrently (the pane agent holds
  live write permission on the exact files the verb is about to
  `git mv`/`git rm`; an unserialized agent write could resurrect a
  resolved record as a duplicate pending file). Sentinel
  hold/heartbeat/release is entirely inside the verb (08 §1); the
  server holds nothing, so a service up for weeks holds the autosync
  pause for zero seconds beyond each verb's own window (07 §4
  contract 4 by construction).
- **Deep-link + launcher**: the notification's click action runs
  `self-learn-ui-open [--record <id>]` — a tiny script and **the only
  WM/browser-aware file**: it ensures the service is up
  (`systemctl --user start self-learn-ui.service` if not), then
  focuses the existing app window (`hyprctl dispatch focuswindow` on
  the pinned window class) or launches the chromeless app window with
  the tokened URL (`/record/<id>?token=…`), falling back to plain
  `xdg-open` (correct-but-untidy: a normal tab). Degraded behavior
  elsewhere is "new tab each time". Deep-link edge cases carried
  (P1-9c): a multi-id worker-run notification deep-links to the
  **first id** in its `record_ids`; an id already resolved by click
  time lands on that record's Bucket page with a "resolved elsewhere"
  banner, or Front if the bucket can't be derived.
- **Notifications** (sender side; carried): M2's pinned notifier is
  unchanged until G-3 lands. At G-3, the emission point swaps to the
  detached helper `self-learn-notify` (`notify-send -A open --wait`,
  verified semantics, environment memo) whose click action now runs
  `self-learn-ui-open --record <id>` (dated 08 §7.1 pointer updated —
  §10). Worker code passes the same ids it already logs. swaync
  renders actions natively; without an action-capable daemon the
  helper degrades to informative-only, exactly M2's behavior.
- **Server-owned state**: none in the repo. A log at
  `~/.cache/claude-skills/self-learn/ui.log` (size-capped like
  `worker.log`), the compiled `pane-doctrine.md` (§4.2), and the
  runtime token file. No config file in v1 — env vars only (§4.4).

## 4. The adjudication pane

### 4.1 Engine decision — SDK default, empirically re-grounded

07 §3 recorded the pane as "a small Agent SDK session". The TUI
revision inverted that to a `cli` default on grounds that included a
false auth fact (corrected 2026-07-12 — empirical-test memo). This
revision **restores the Agent SDK as the default engine**, per the
user's binding V3 and probes run before these pins froze
(`research/2026-07-12-sdk-pane-probes.md`):

| | `sdk` engine — `claude-agent-sdk` (Python) — **default** | `cli` engine — `claude -p` stream-json — specced alternative |
|---|---|---|
| Auth / economics | Identical — both resolve the same credential chain, subscription OAuth included (empirical-test memo) | Identical |
| Token-level streaming | **Verified empirically** (probes memo, probe 1): `include_partial_messages=True` emits raw Anthropic stream events before the final message; granularity is chunk-level (~5 Hz, ~14 words/delta over a ~150-word answer) — smooth live rendering, not per-token | `--include-partial-messages` verified live on 2.1.207 |
| Permission surface | **In-process `can_use_tool` callback, verified empirically** (probes memo, probe 2): fires per tool call with absolute paths, denial reason surfaces to the agent, denials fail closed and land in `ResultMessage.permission_denials`. Caveats pinned in §4.3: callback requires `ClaudeSDKClient` streaming mode, and a gated tool listed in `allowed_tools` is auto-approved **before** the callback runs | flag rules only; PreToolUse-guard fallback |
| Model fallback / caps | **Verified empirically 2026-07-12** (phase-A reviewer, dataclass introspection on installed 0.2.116): `ClaudeAgentOptions` exposes `fallback_model`, `max_turns`, `max_budget_usd` as real fields. (This also corrects the grounding memo's doc-derived "the Agent SDK has no fallback equivalent" — false on the pinned stack; dated correction landed there.) Re-verified against the resolved SDK version at build (10 §1 ledger) | `--fallback-model`, `--max-budget-usd`, `--max-turns` verified live |
| Interface stability | semver'd typed library (version-pinned, 10 §1) | stream-json protocol, versioned with the CLI |
| Uniformity | Second dependency (bundled CLI binary rides the wheel; `cli_path` can point at the system CLI) | One engine family with the worker |

**Decision: the `sdk` engine is the default; the `cli` engine is the
recorded alternative behind the same seam.** Grounds: the user's
binding V3 (restoring the original directive, whose earlier reversal
leaned on the falsified auth claim); `canUseTool` — the charter (§4.3)
enforced as an exact-file allowlist *in process*, structurally
stronger than flag rules; one language across CLI, server, and engine.
The `cli` engine is kept **specced, not built** (mirror of the old
P1-11 economy — a solo maintainer should not keep a second engine
green): `SELF_LEARN_PANE_ENGINE=cli` exits with "engine not built —
see 09 §4.1". Its spec is the TUI revision's §4 invocation pin set
(git history; 10 §5 carries the pointer), and it is the terminal rung
of the §4.3 fallback ladder.

**`PaneEngine` interface** (the seam both implementations satisfy;
carried verbatim): `start(item_context) → session`, `send(text)`,
`interrupt()`, `close()`, plus an async event stream of:
`block_start(kind)`, `text_delta(str)` (absent → per-block fallback),
`tool_use(name, target_path)`, `file_changed(path)`,
`result(status, cost_usd | null, error | null)`. The UI renders
events; it never reaches around the engine to the transport. The
browser sees these events re-emitted over SSE; the transcript region
appends `text_delta`s live and re-renders each block server-side
(markdown → HTML) at `block_start`/`result` boundaries — live text is
plain, finished blocks are typeset (the standard streaming-chat
pattern; no client-side markdown dependency).

### 4.2 Session lifecycle

- **Fresh session per Iterate** (07 §3, unchanged). No resume across
  Iterates: adjudication context is small and rebuilt from files, and
  a stale session's view of edited files is a liability. Session
  persistence off (SDK option; verified at build — these ephemeral
  sessions must not pollute resume lists).
- **Prompt structure** (carried, P1-12): system prompt = the
  **compiled doctrine** — `routing-doctrine.md` (single source, 08 §1;
  one file, three loaders) + the **pane charter** appendix (§4.3
  rendered as prose, tracked:
  `plugins/self-learn/skills/self-learn/references/pane-charter.md`).
  Compilation is a runtime concat to
  `~/.cache/claude-skills/self-learn/pane-doctrine.md`, re-concat when
  either source's mtime changes; the compiled artifact is cache, never
  tracked. Passed to the SDK as its system-prompt option (byte-stable
  across sessions by construction). **`setting_sources` explicitly
  `[]`** — no CLAUDE.md/skills/hooks ride in. This pin is load-bearing
  twice over: the empirical-test memo measured a 68k-token cache write
  when defaults load, and the probes memo (probe 3) proved that
  *unset* `setting_sources` loads the FULL user environment on this
  stack (33,972 vs 3,027 cache tokens, 13 hooks vs 0 — the documented
  "default = no settings" is false; isolation must be explicit).
  Per-item context —
  record body, proposal + diff if present, target canon excerpt (the
  same excerpt rule as the worker prompt pin, 08 §7) — rides in the
  first user message, never in the system prompt.
- **Caching is opportunistic economics, never a dependency** (carried;
  5-minute default TTL). The byte-stable prefix maximizes whatever
  caching the auth path provides; the design budget assumes zero cache
  hits and stays acceptable.
- **Caps**: budget `SELF_LEARN_PANE_BUDGET_USD` (default 1.00) →
  `max_budget_usd`, turn cap `SELF_LEARN_PANE_MAX_TURNS` (default 15)
  → `max_turns`, model `SELF_LEARN_PANE_MODEL` (default
  `claude-sonnet-5`) with `fallback_model=claude-haiku-4-5` — all
  three option fields **empirically confirmed present on 0.2.116**
  (§4.1 table; re-verify at build). Wrapper-side cap enforcement
  (count turns, kill + `result(error_*)`) exists ONLY as the
  contingency for a future SDK version dropping a field — it is not a
  co-equal build path (W-4, 2026-07-12).
- **Cost honesty** (carried): the pane footer renders the `result`
  event's cost/usage verbatim when present (subscription auth may
  report 0/absent — render what the engine reports, never invent a
  number), plus turn count.
- **Interrupt**: `Esc` → `engine.interrupt()` (the SDK's interrupt
  call; escalate to terminating the SDK client/subprocess after 2 s
  grace, kill after 5). Interrupting never discards file changes
  already written (files are truth; the re-render already showed
  them).
- **One live session at a time** server-wide (carried — same
  serialization ground as verbs). Iterate on another record while a
  session runs → armed prompt to interrupt the current one first.
- **Session end**: on `result`, the input line stays open for a
  follow-up `send` (the SDK client is multi-turn in-place); the
  transcript is ephemeral — closing the split discards it (outcomes
  live in files; 07 §3).

### 4.3 Pane permission surface (the charter)

The pane agent's job: improve the pending record and its proposal,
answer questions about the target canon. Its **hard surface**,
expressed once in code and compiled to engine config — for the `sdk`
engine: the in-process `can_use_tool` callback holding the whole
charter; for the specced `cli` engine: the flag rules (git history).
**Pinned callback mechanics (probes memo, empirically grounded):**
the engine is built on `ClaudeSDKClient` in streaming mode (the
callback refuses to run otherwise — probe footgun A; the `query()` +
finite-generator pattern closes the control channel and every
permission request dies "Stream closed" — footgun C, fails closed but
unusable); **`allowed_tools` stays empty** — a tool listed there is
auto-approved *before* the callback runs (`CanUseToolShadowedWarning`,
footgun B), so every tool call routes through the callback, which
allows/denies per the rules below; paths are canonicalized
(`realpath`) before matching; unknown stream message types are
tolerated and skipped (`RateLimitEvent` appears mid-stream on
subscription auth):

- **Read scope, pinned enforceably (W-3, 2026-07-12).** The
  enforcement reality, with honest attribution: probe 2 showed reads
  **auto-approve inside `cwd` and never reach the callback**; that
  reads *outside* `cwd` DO route to `can_use_tool` — and that a
  callback deny actually blocks them — was verified live by the
  phase-A gate re-check (out-of-cwd read denied, recorded in
  `ResultMessage.permission_denials`; 2026-07-13). The pin therefore has two tiers:
  free reads inside `cwd` = the bucket root (the item's own subtree —
  harmless by construction); the callback **allows** `Read`/`Grep`/
  `Glob` on paths under the resolved `SELF_LEARN_HOME` repo tree
  (target canon, doctrine, corpus — repo-wide readability is accepted
  and stated: the repo policy is no secrets in any tracked file) and
  **denies with reason every read outside the repo** (e.g. the
  user-scope `~/.claude/CLAUDE.md` — its excerpt already rides in the
  first user message per the excerpt rule; the agent is told to work
  from it or ask the human). "Corpus + target canon" below is this
  rule, not a third scope.
- **Allowed**: `Read`, `Grep`, `Glob` per the read-scope pin above;
  write access on **exactly** the item's own files (carried, P3-7):
  `Edit` on `pending/lrn-<id>.md` (the record always exists — granting
  `Write` would let a session recreate it whole, the resurrection
  vector §3 closes), and `Write`+`Edit` on `proposals/lrn-<id>.yaml` /
  `proposals/lrn-<id>.diff` (proposals may not exist yet) —
  absolute-path checks in the callback, no wildcards beyond the id's
  own siblings.
- **Denied, structurally**: `Bash` (with it, every write restriction
  is void — E-18), `Task`, `WebSearch`, `WebFetch`, MCP (strict MCP
  config with none configured), everything else not allowed above.
  `cwd` = the bucket root.
- **No path to route** (07 §4, P1): the resolution verbs are not
  tools, the CLI binary is unreachable without Bash, and approval is a
  POST from the human's window calling the verb from server code.
  Proposer ≠ approver, by construction.
- **Post-iterate stamping and scanning** (carried verbatim —
  P1-3/P2-1/M2-21 closures): anything the pane agent writes into a
  proposal is unstamped by definition (models cannot compute
  `record_sha`), and its direct record edits bypass CLI verbs — so on
  session end, the server invokes `self-learn proposal validate <id>`
  (08 §7.1 pin): stamps `record_sha` AND secret-scans the record body
  + proposal siblings; **report-never-delete** on invalid; pinned exit
  codes 0 clean · 1 schema-invalid · 2 scan hit — never stderr
  parsing; a scan hit badges the item "scan-blocked" until a
  re-validate exits 0, and resolution verbs refuse on their own
  full-file scan regardless (P2-7 — the no-bypass backstop). The verb
  commits nothing. Mid-session `file_changed` events trigger re-render
  only, never validation. Residual, named (W-8, 2026-07-12): between
  an agent write and the session-end scan, autosync can publish the
  un-scanned record body to the private remote — on this one path the
  S-8 rider is detect-at-checkpoint, not prevent-at-write: exactly the
  accepted posture 02 §2 records (it "detects at the checkpoint
  rather than preventing at the keystroke" — P2-1). Canon remains
  protected by the resolution verbs' own scan.
- **Permission-surface fallback ladder** (rebuilt for the sdk engine):
  rung 1 = `canUseTool` exact-file callback (default; probes memo is
  the pre-build evidence, the live refusal trial T-B the build-time
  arbiter); rung 2 = the same charter as `allowed_tools`/
  `disallowed_tools` path-scoped rules (SDK options mirroring the CLI
  flags) if the callback proves unreliable; rung 3 = a PreToolUse
  guard delivered via a settings file (the organizer-guard pattern
  this repo already runs); rung 4 = the specced `cli` engine (§4.1).
  A failed verification is a pivot down this ladder, never a stall and
  never a loosened surface.

### 4.4 Configuration (complete list)

`SELF_LEARN_HOME` (existing) · `SELF_LEARN_UI_PORT` ·
`SELF_LEARN_UI_BROWSER` (launcher-only — consumed by
`self-learn-ui-open`, never by the server; X-1, 2026-07-13) ·
`SELF_LEARN_PANE_MODEL` · `SELF_LEARN_PANE_BUDGET_USD` ·
`SELF_LEARN_PANE_MAX_TURNS` · `SELF_LEARN_PANE_ENGINE` (`sdk` |
`cli`, default `sdk`; `cli` → exit "engine not built — 09 §4.1").
Nothing else in v1; no config file.

## 5. Error handling & degradation

Ordered by blast radius; the invariant throughout: **adjudication
never depends on any optional subsystem.** Approve/deny/defer work
when the worker is dead, the pane is broken, the network is down
(push failures surface from the verb, per its own pins), and
notifications are absent.

| Failure | Behavior |
|---|---|
| Pane engine start fails / `result: error_*` | Pane renders the error + `r` retry; Detail and all resolution actions unaffected. Budget/turn-cap errors render as "cap hit — r to continue in a fresh session". |
| Engine emits no `text_delta` (partial streaming unavailable or coarse) | Per-block rendering with an activity indicator — a rendering degradation, not a feature loss. |
| SSE disconnects (laptop sleep, server restart) | Client falls back to the 10 s poll and retries SSE; a thin "live updates reconnecting" strip shows meanwhile. No state is lost — files are truth. |
| Server not running at deep-link time | `self-learn-ui-open` starts the service before opening the URL; direct URL visits fail visibly (browser error) — the launcher is the pinned entry path. |
| Token cookie absent/stale (new browser, cleared cookies) | 403 page naming `self-learn-ui-open` as the fix (it re-mints the tokened URL). |
| No proposal for a record | Detail renders record-only; Iterate works from scratch (the agent generates the proposal). |
| Proposal stale (`record_sha` mismatch) | Badge + hint to Iterate; approve stays available (the verb re-validates authoritatively at apply — the badge is advisory UI, the CLI is the enforcer). |
| Verb exits non-zero (dirty target, push failure, scan refusal…) | Error strip with the verb's stderr verbatim; state re-read from files; nothing optimistic. The verb's messages are the contract — the server adds no interpretation. |
| `proposal validate` scan hit at session end | Exit-code discrimination (0/1/2); error strip shows the verb's report verbatim; record/proposal stay as written (report-never-delete); "scan-blocked" badge until a re-validate exits 0. |
| Record resolved elsewhere mid-view | SSE fires → "resolved elsewhere" banner → Bucket page; if under active iteration, the pane session is interrupted first (§3/P3-8). |
| `events.jsonl` absent/corrupt line | Skip + log; wake-ups degrade to the poll; ledger walk is truth. |
| swaync/action support absent | Notifications degrade to M2's informative-only behavior. |
| Browser has no `--app` mode / Hyprland absent | Plain tab via `xdg-open`; everything works, minus the dedicated-window feel. |
| Worker overdue / never ran | Status strip alarm (reuses the worker's own escalation thresholds); everything else functions — the surface is not the worker's supervisor. |

## 6. Stack selection

**Decision: FastAPI + uvicorn + Jinja2 + vendored htmx 2.0.9 + SSE +
Pygments + markdown-it-py + watchfiles, as a `systemd --user` service.
No node, no bundler, no CDN, no database.** Grounds: the DX study's
axis table (styling, iteration, agent leverage, maintainability,
testing, deep-link — all web, most decisively) under the user's
binding V1/V4; the stack is deliberately the deepest-training-data,
lowest-churn idiom available (HTML/CSS/HTTP/SSE don't churn; htmx
2.0.9 is vendored as one file and upgraded never or deliberately —
the v4 beta line is explicitly ignored). The see-judge-fix loop is
native: this environment already runs Playwright MCP and
claude-in-chrome, so build-time agents can navigate, screenshot, and
iterate on localhost directly.

- **Risks accepted, with mitigations**: (1) a localhost HTTP surface —
  mitigated by the §3 security pins (in scope v1, tested in T-A);
  (2) browser keyboard limits — mitigated by the no-chords keymap rule
  and the Vimium exclusion note; (3) htmx 4.x churn — irrelevant by
  vendoring 2.0.9; (4) **rendered content is adversarial** (records
  originate in sessions that read the web; pane blocks are model
  output) — mitigated by the §3 render-path pins (autoescape +
  `html=False` + CSP; added 2026-07-12, W-1 — this risk was missing
  from the problem-space map's security pricing and is recorded there
  as a dated correction; the pricing delta is small and does not
  disturb the platform answer).
- **The recorded runner-up is the Textual TUI** (this document's prior
  revision, git history) — switch conditions: the user re-weights
  toward total keyboard ownership / zero network surface (reversing
  V4), or a future circumstance makes running a local service
  untenable. The exposure is bounded exactly as before: the CLI, file
  formats, engines, and doctrine sit behind the surface, so a switch
  is a view-layer rewrite only.

Sections 1–5 are template/route-level by construction; only
`10-surface-build-plan.md` names library APIs.

## 7. Testing & acceptance posture (design-level)

Detailed fixtures live in 10; the design constrains them:

- The surface's logic (state derivation from files, verb arming,
  engine event handling, charter compilation, security middleware) is
  testable headless: screen models are pure functions of a directory
  tree (throwaway `SELF_LEARN_HOME` repos, 08 rule 4), and routes are
  exercised in-process with httpx against the ASGI app, asserting
  returned partials — fast, deterministic, framework-upgrade-proof.
- The pane's permission surface gets a **live refusal check** (T-B):
  a real sdk-engine session instructed to run Bash / write outside its
  allowlist must be refused — callback construction is the cheap test,
  live refusal is the real one.
- Browser-level checks (keymap handling, SSE swaps) run via Playwright
  against a test server as acceptance items; CI stays at the
  httpx/pure-function level. Visual polish trials are acceptance
  items, not CI items.

## 8. What is deliberately absent

- **No approval bypass** through the pane (07 §5; P1). No
  batch-approve of heterogeneous items.
- **No SPA, no node toolchain, no client build step, no database** —
  server-rendered pages, one vendored htmx file, one small `app.js`;
  no state that isn't a file (plus the runtime token).
- **No remote bind, no multi-user auth in v1** — 127.0.0.1 only; team
  scale is 06's staged path, not a v1 latch.
- **No dashboards/scores** — the status strip is counted facts only
  (counted-not-modeled, 04).
- **No in-surface capture** (`teach` lives where the lesson happens;
  this is the adjudication surface, not a fifth producer).
- **No notification ownership** — the server never sends
  notifications; it is their destination.

## 9. Extensibility posture (team scale, 06-horizon)

The web substrate widens naturally: provenance fields already render
(§2.3); PR-based routing authority would swap the verb the action bar
arms behind the same armed-bar UX; a Stage-2 team deployment binds the
same app wider behind real auth (the v1 token middleware is the seam);
the sdk engine default is already the shape an API-key team deployment
wants. Multi-user presence stays out until Stage 2 exists — files +
SSE make eventual coherence the default anyway.

## 10. Corpus amendments this revision necessitates

To land as dated edits at each named site (this cycle's phase 2);
until landed, this list is authoritative:

1. **07 §3** — dated amendment: the destination surface is re-decided
   from the problem-space cycle — a localhost server-rendered web app
   in a dedicated (chromeless app) window; "the resident window is the
   point" is refined per the user's binding V2 to "ambient presence in
   a dedicated window"; the pane engine returns to the Agent SDK
   (binding V3), closing the loop on 07 §3's original sentence. 07's
   title line gains a pointer ("TUI" → the recorded vision's surface,
   since revised — see 09).
2. **08 §7.1 notification pointer** — the G-3 click action becomes
   `self-learn-ui-open --record <id>` (was `self-learn-tui-open`);
   payload, template, events line all byte-unchanged.
3. **02 §3 storage layout** — the transient-state line updates: the
   surface's state is `ui.log` + compiled `pane-doctrine.md` under
   `~/.cache/claude-skills/self-learn/`, plus the runtime token under
   `$XDG_RUNTIME_DIR/self-learn/` (replacing the socket entry — the
   socket subsystem is deleted in the web revision).
4. **03-decisions G-3 row** — dated note: platform re-decided
   2026-07-12 (web surface, SDK pane engine) via the post-correction
   problem-space cycle with binding user answers; 09/10 renamed;
   trigger unchanged.
5. **README** — doc-table rows for 09/10 renamed + revision-log entry
   for this cycle.

Already-landed amendments from the TUI revision that this revision
**keeps consuming unchanged** (no re-landing needed): 08 §1 `--json`
hardening fields; 02 §1 `already_canon`; 08 §7.1 `proposal validate`
(+ P2-7 full-file scan on resolution verbs); 08 §1 `--no-push` +
terminal push; 08 §1 sentinel clarification. These were substrate
amendments and are platform-independent — exactly why they were
landed in 08/02, not in 09.

No settled decision's *inputs* change beyond the G-3 row itself: the
07 §4 contracts are honored, not amended; the platform/engine
amendments revise vision details (07 §3) under a recorded user
decision. If a reviewer finds otherwise, that finding reopens the
register per P10 before anything lands.
