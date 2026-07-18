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
  by a Hyprland window rule *(the rule is optional polish — the
  presentation degrades gracefully without it; snippet documented as
  a manual step at 10 U10 — X-10, 2026-07-13)* — the dedicated-window
  feel the vision wanted, per the user's binding V2: ambient presence
  + instant attend, in *any* dedicated window. (Mechanism verified live 2026-07-12,
  phase-A reviewer: `chromium --app=… --class=self-learn-ui-test`
  under Hyprland 0.55.4 yields a native-Wayland window with that
  app_id, `xwayland: false` — `hyprctl dispatch focuswindow class:…`
  matches. Chromium-family only; Firefox has no `--app` equivalent
  and takes the plain-tab degradation, §5.) A plain browser tab works identically
  (degradation, §5); the server neither knows nor cares.
  *(Amended 2026-07-17 — T-D live trial: the 2026-07-12 verification
  holds only for a FRESH chromium. When chromium is already running —
  the common case — an `--app` window is created by the existing
  process, which derives the Wayland app_id from the URL
  (`chrome-<host>__…-Default`) and IGNORES `--class`; a dedicated
  `--user-data-dir` does not change this. So class-only window matching
  is unreliable. `self-learn-ui-open` therefore matches an existing UI
  window by the stable page-TITLE prefix "self-learn — " as well as the
  class (X-3 amended, 10 §1). Residual: focusing an existing window
  cannot re-navigate it to a different record, so cross-record
  deep-links still open a new window — the §5 "new window each time"
  degradation, now scoped to that case. The deep-link primary chain —
  notify → click → dedicated window on the correct record — is
  unaffected and was live-confirmed.)*
- **Keyboard accelerators, single keys only.** `j`/`k` (and arrows)
  move within a list, `Enter`/`l` drill in, `Esc`/`h` go up a level,
  action keys per below. *(Amended 2026-07-17, user-directed remap —
  feedback session: the layout recenters on gaming controls, not vim:
  `w`/`s` (and `↑`/`↓`) move within a list, `Enter`/`d`/`→` drill in,
  `Esc`/`a`/`←` go up a level. Navigation taking `a`/`d` evicted the
  approve/deny bindings — see the action-keys bullet's amendment.
  Everything else in this bullet — single keys, one-source keymap
  table, inert-in-inputs, no chords — unchanged.)* Implemented as a small vendored `app.js`
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
  back/forward IS the stack walk; `Esc`/`a`/`←` navigate up
  programmatically *(keys per the 2026-07-17 remap amendment above)*. A deep-link lands directly on Detail with the
  stack derivable from the URL, so up-navigation still walks sensibly.
- **Action keys on Detail** (also usable on a Bucket row): `a` approve
  (route), `d` deny (reject), `i` iterate (agent pane), `f` defer, `g`
  graduate (always available; highlighted when the proposal flags
  already-canon — §2.3), `o` override destination, `n` attach/edit a
  resolution note. *(Amended 2026-07-17, same remap: `e` approve
  (games' "use/interact" key), `x` deny — `a`/`d` now navigate.
  `i`/`f`/`g`/`o`/`n` and the holding/pane keys unchanged. Keymap
  invariant made explicit by the remap: app.js dispatches on first
  key match with no context filter, so every key is globally unique
  across the table — pinned by test.)* *(Amended 2026-07-17, item 7 —
  §11 Y-13: `p` opens the bucket-context pane on the Bucket page
  (§4.5), and `y` arms a WAITING pane proposal bar (§4.5's rework —
  the proposal's own consent keystroke; Enter then confirms per the
  standard armed contract). Both were unbound, so the
  global-uniqueness invariant holds. On Detail the pane remains `i` —
  one pane vocabulary, two contexts.)*
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
  live (someone is mid-apply somewhere), **miner last-run age +
  staleness and open-follow-ups count (added 2026-07-17 — §11
  Y-5/Y-6)**. Data: `status --json` and `mine status --json` plus the
  sentinel file's mtime read directly (read-only). No run *result*
  renders here — `worker_last_run` is the only pinned worker field and
  failed runs deliberately never touch it (08 T13); run forensics stay
  in `worker.log` (P1-7); miner run rows render on the miner section
  (Y-5), not the strip.
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
- Row *(order amended 2026-07-17 — §11 Y-9, the human-language-first
  rule)*: **the human line leads** — the proposal's leading card
  section when a proposal exists, else the title (first Trigger/Fact
  line, same derivation as `list --json .title`); then age, sightings
  count, a "mined" provenance badge when `source` is `session` (§11
  Y-5), deferred badge when `deferred_until` is future (dimmed at the
  bottom; fetched via `list --json --include-deferred`), already-canon
  flag when `proposal.already_canon` is set (the structured field,
  P1-2 — never parsed from rationale prose, 07 §4 contract 2). The
  `lrn-…` id renders as trailing metadata, never as the row's label.
- **Cluster rows** (merge-proposals): one row per cluster showing
  member count and the suggested survivor; expanding (`Enter`) lists
  members inline (an htmx partial swap); the survivor choice is a
  selection within the expanded view; approve arms
  `route <survivor> --collapse <cluster-id>` (08 §7 pin, consumed
  verbatim).
- **Bucket pane** *(added 2026-07-17, item 7 — §11 Y-13)*: `p` splits
  the Bucket page exactly as `i` splits Detail (§2.4's layout,
  generalized): left = the grouped record list (live), right = the
  agent pane (§4) started with **bucket context** (§4.5's context
  pin). The bucket session answers questions about the queue and may
  propose resolutions on any record in the bucket via the §4.5
  proposal tool; it holds **zero write allowance** (§4.3 as amended —
  record editing belongs to the record pane). `Esc`/`q`/`r` behave as
  on the Detail split.
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
  resort, not the only publisher. *(Post-13 note, 2026-07-17: the
  ledger repo has no autosync watcher (13 H-5), so W-5's benign race
  is void as described — the terminal push IS the only in-loop
  publisher now; the pin stays because it also covers reconcile- or
  verb-driven pushes from concurrent processes, the same
  no-op-if-published logic.)*

### 2.3 Detail page — one decision, fully explained

*Amended 2026-07-14 (decision-support contract — routing-doctrine §8,
02 §1 `card:`):* the page **opens with the proposal's `card:` sections,
rendered data-driven** from the skill's `card-sections.yaml` registry —
iterate ascending `order`, emit `label` + markdown text for each key
present, skip absent keys, render unknown keys last with the raw key as
label. **No per-section component, template branch, or hardcoded key
anywhere in the server or templates** — adding/changing/retiring a
section must be a registry-file edit with zero UI diff. The three
machine regions below follow the card sections; the first review
session (2026-07-14, slash-command venue) is the measured evidence for
this ordering: machine-led cards produced rubber-stamp approvals.

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
   *(Amended 2026-07-17 — §11 Y-7:)* a proposal with destination
   `hook` renders its **entire stored script** (bash lexer) plus the
   replay examples as this region — the M3 "whole script as the diff"
   pin, honored by the surface — and the caption swaps to the M3
   verbatim-apply wording (what you see IS the bytes the verb applies;
   a `record_sha` mismatch aborts at the verb, never silently
   regenerates). Destination `new-skill:<name>` renders the scaffold
   name + structure preview.
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
bounded interrupt. *(Amended 2026-07-17, item 7 — §11 Y-13, wording
per the same-day rework: the pane agent may itself propose a
resolution via §4.5's tool; the proposal renders as a WAITING bar in
the standing action-bar region, and the human's `y` arms it through
the same armed contract the keys use — one consent surface, one
two-keystroke path, whoever suggested the verb.)*

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
  push. External mutations (a concurrent `/self-learn:review`
  session, verb- or reconcile-driven pulls — the post-13 ledger has
  no autosync watcher) surface the same way. If the record
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
  `<cache>/ui.log` (size-capped like `worker.log`), the compiled
  `pane-doctrine.md` (§4.2), and the runtime token file. No config
  file in v1 — env vars only (§4.4). *(`<cache>` re-based 2026-07-17
  to the doc-13 home-namespaced cache dir — §11 Y-3; the literal
  `~/.cache/claude-skills/self-learn/` of the original revision is
  the pre-13 path and is dead.)* *(Amended 2026-07-17, item 7 — §11
  Y-13: plus ONE in-memory transient, the pane proposal slot —
  §4.5's server-held pending proposal; never persisted, cleared per
  §4.5's exhaustive clear-set, gone on restart by construction.)*

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
  sessions must not pollute resume lists). *(Amended 2026-07-17,
  item 7 — §11 Y-13: the bucket pane (§2.2) is the same lifecycle —
  fresh session per open, ephemeral transcript, same engine, same
  caps — differing only in its first-message context (§4.5) and its
  zero write allowance (§4.3). "One live session at a time" below
  covers BOTH variants: bucket pane and record pane never coexist;
  opening either while the other runs takes the existing armed
  interrupt prompt.)*
- **Prompt structure** (carried, P1-12): system prompt = the
  **compiled doctrine** — `routing-doctrine.md` (single source, 08 §1;
  one file, three loaders) + the **pane charter** appendix (§4.3
  rendered as prose, tracked:
  `plugins/self-learn/skills/self-learn/references/pane-charter.md`)
  *(+ third source added 2026-07-17, item 7 — §11 Y-13: the
  **surface model**, tracked
  `plugins/self-learn/skills/self-learn/references/pane-surface-model.md`
  — what the buckets/scopes/verbs/screens are and what the human
  sees, authored in the routing-doctrine §8 register per Y-9, so
  "talk to me about my buckets and routing" works without the agent
  rediscovering the system each session)*.
  Compilation is a runtime concat to `<cache>/pane-doctrine.md`
  (cache dir per §11 Y-3), re-concat when any source's mtime
  changes; the compiled artifact is cache, never tracked. Passed to the SDK as its system-prompt option (byte-stable
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

- **Read scope, pinned enforceably (W-3, 2026-07-12; scope set
  re-derived 2026-07-17 — §11 Y-2, after doc 13 split the one-repo
  topology this bullet assumed).** The enforcement reality, with
  honest attribution: probe 2 showed reads **auto-approve inside
  `cwd` and never reach the callback**; that reads *outside* `cwd` DO
  route to `can_use_tool` — and that a callback deny actually blocks
  them — was verified live by the phase-A gate re-check (out-of-cwd
  read denied, recorded in `ResultMessage.permission_denials`;
  2026-07-13). The pin therefore has two tiers: free reads inside
  `cwd` = the bucket root (the item's own subtree — harmless by
  construction); the callback **allows** `Read`/`Grep`/`Glob` on the
  three read roots pinned in §11 Y-2 (ledger tree, registered hosts'
  **canon surfaces** via the CLI-owned `canon_read_roots()` helper,
  plugin references dir) and **denies with
  reason every read outside them** (e.g. the user-scope
  `~/.claude/CLAUDE.md` — its excerpt already rides in the first user
  message per the excerpt rule; the agent is told to work from it or
  ask the human). *(The original single-root wording — "under the
  resolved `SELF_LEARN_HOME` repo tree (target canon, doctrine,
  corpus)" — described the pre-13 monorepo, where one repo held all
  three. Post-13, `SELF_LEARN_HOME` is the ledger alone; following
  the old wording verbatim would deny the analyst every canon and
  doctrine read. Y-2 is the authoritative scope set.)*
- **Allowed**: `Read`, `Grep`, `Glob` per the read-scope pin above;
  write access on **exactly** the item's own files (carried, P3-7):
  `Edit` on `pending/lrn-<id>.md` (the record always exists — granting
  `Write` would let a session recreate it whole, the resurrection
  vector §3 closes), and `Write`+`Edit` on `proposals/lrn-<id>.yaml` /
  `proposals/lrn-<id>.diff` (proposals may not exist yet) —
  absolute-path checks in the callback, no wildcards beyond the id's
  own siblings. *(Amended 2026-07-17, item 7 — §11 Y-13: this write
  allowance is the RECORD session's. A **bucket session (§2.2) holds
  zero write allowance** — it binds no single item, so there are no
  "item's own files"; the callback denies every write with a reason
  that names the record pane as the venue for edits.)*
- **Denied, structurally**: `Bash` (with it, every write restriction
  is void — E-18), `Task`, `WebSearch`, `WebFetch`, MCP (strict MCP
  config with none configured), everything else not allowed above.
  `cwd` = the bucket root. *(Amended 2026-07-17, item 7 — §11 Y-13:
  the strict MCP config now carries exactly ONE entry — the
  server's own in-process tool server (`create_sdk_mcp_server`,
  present on the pinned SDK — verified on installed 0.2.121 at
  drafting) exposing exactly one tool, §4.5's `propose_verb`. It runs
  in the server's process; there is no external transport. Every
  other MCP surface stays denied. The callback's allow-rule matches
  the tool's fully-qualified name exactly; `allowed_tools` stays
  empty (footgun B), and T-B must prove the tool call routes through
  the callback on the resolved SDK version.)*
- **No path to EXECUTE a verb** *(amended 2026-07-17, item 7 — §11
  Y-13; previously "No path to route")* (07 §4, P1): the resolution
  verbs are not tools, the CLI binary is unreachable without Bash,
  and approval is a POST from the human's window calling the verb
  from server code. §4.5's `propose_verb` is a path to *request*, not
  execute: its entire effect is rendering the armed consent bar to
  the human; the runner is invoked only by the human's confirm POST.
  Proposer ≠ approver, by construction — unchanged.
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
  only, never validation. Residual, named (W-8, 2026-07-12; mechanism
  updated 2026-07-17): between an agent write and the session-end
  scan, a concurrent push of the ledger — post-13 not autosync (the
  ledger has no watcher, 13 H-5) but any verb- or reconcile-driven
  push from another process — can publish the un-scanned record body
  to the private remote; on this one path the
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

### 4.5 Verb proposals from the pane *(added 2026-07-17 — feedback round 1 item 7; §11 Y-13 is the register entry)*

The pane agent can **request** a resolution; the human's standing
arm/confirm bar is the consent surface; the runner remains the single
mutation seam. Everything below is one tool, one bar, one POST.

- **The tool.** One in-process tool, `propose_verb`, served by the
  UI server's own SDK MCP server (§4.3 as amended — no external
  transport; the handler runs in server code). Signature:
  `propose_verb(verb, record_id, dest?, note?, until?)`.
  **Proposable verb set, v1 (closed list):** `route` (with optional
  `dest` from 02 §1's pinned enum — the VERB stays the enforcer of
  structural validity, e.g. a `hook` dest without stored script bytes
  refuses at the verb and the refusal renders verbatim, §5), `reject`
  (optional `note`), `defer` (optional `until`, ISO date), `graduate`.
  **Excluded, dated:** `host add` (Y-11's no-agent-path pin —
  the agent must never widen its own read scope or mint write
  targets; the design brief predated that pin and is corrected by
  this line); `route --collapse` (cluster consent has its own
  expanded-row survivor flow, and a pane proposal binding cluster
  state adds serialization surface v1 doesn't need); the telemetry
  verbs (`confirm-recurrence`, `followup done`, `link contradicts` —
  Y-4/Y-6/Y-8 rows are their consent surfaces). Extending the set is
  a dated edit to this list, never a code-only change.
- **Server-side validation, before anything renders.** The handler
  validates: verb in the closed list; `record_id` resolves to a
  PENDING record **in the session's own scope** — the record session
  may name only its own record; a bucket session may name any pending
  record in its bucket; `dest` in the pinned enum; `until` parses.
  Any failure returns a refusal string to the agent (it can correct
  itself or ask the human) and renders nothing.
- **One proposal at a time — refuse, never replace.** While a
  proposal slot is occupied (waiting OR armed — see the state pins
  below), further `propose_verb` calls refuse with "a proposal is
  already awaiting the human". Rationale: a replace rule would let
  the bar's content change between the human's read and their Enter —
  what-you-see-is-what-you-confirm is the arm/confirm spine's whole
  point. (Judgment row, 10 §4.)
- **Server-held proposal state** *(reworked same day after the blind
  spec review — its F2)*: the pending proposal is the surface's
  FIRST server-held armed-state precursor (the standing arm machine
  is deliberately stateless server-side — armed state lives in the
  rendered fragment). One in-memory slot beside the pane session
  manager (one live session ⇒ one slot; never persisted — a server
  restart clears it by construction). **Clear-set, exhaustive:**
  human confirm · human dismiss · the proposing session ending for
  any reason (result, interrupt, error, cap, `q`) · the record
  leaving pending (resolved elsewhere — the §3 banner path also
  clears the slot) · server restart. Page navigation does NOT clear
  it: any render of a page in the proposal's scope re-renders the
  waiting bar (the slot is server truth, so the bar survives
  reloads). 09 §3's server-owned-state list reads through this
  bullet (dated addition there).
- **Rendering — proposals arrive WAITING, never armed** *(reworked
  same day — the review's F1/F3 root cause: an SSE-driven swap could
  replace a human-armed bar between the human's read and their
  Enter, and the client's armed-exclusivity rule inerts keys, not
  swaps)*: a valid proposal renders a **waiting** proposal bar —
  full content visible: verb, the record's human line (Y-9), id as
  trailing metadata, destination, date, and the note rendered under
  an explicit "agent-suggested note:" label — **capped at intake**
  *(delta review R4: a display-only cap would let the human confirm
  note text they only partially read)*: the handler refuses notes
  over 200 characters with a refusal string (the agent shortens and
  retries), so **the note displayed is byte-identical to the note
  the confirm executes** — assembled from the SERVER-validated args. **Server-truth anchor: verb, record id,
  destination, and date are validated server fields; the note IS
  agent prose and is labeled as such** (the review's F7 — the bar
  never pretends otherwise). The waiting bar is NOT `[data-armed]`:
  `y` (unbound until now; global-uniqueness invariant holds) arms it
  through the STANDARD armed contract — Enter executes, any other
  key disarms **back to waiting** — giving the agent's proposal
  exactly the same two-keystroke consent path as the human's own
  actions, never a shorter one. Dismissing a waiting proposal is a
  visible button on the bar (click — a rare act, the Register-button
  precedent; no key spent). Enter NEVER acts on a waiting bar.
  **Single-armed-bar invariant, now global and tested:** no rendered
  page ever contains two `[data-armed]` elements — arming anything
  (proposal included) goes through the standing exclusivity rule,
  and the SSE `pane_proposal` handler no-ops while any
  `[data-armed]` element exists (client suppression, belt) — but the
  structural brace is that the incoming bar is waiting-state, so
  even a missed suppression cannot redirect a pending Enter.
  Detail: the waiting bar renders in the standing action-bar region
  (swapping the unarmed bar only); Bucket: adjacent to the pane. The
  transcript logs only that a proposal was made (the `tool_use`
  event line); the bar carries the consent. SSE gains one envelope
  type, `pane_proposal`, **scope-gated like `refresh`** (the
  review's F8): only the record's own Detail and its bucket's Bucket
  page act on it; other pages ignore it. The envelope never carries
  bar content — the region re-fetches server-rendered.
- **Confirm / cancel.** `Enter` on the ARMED proposal bar POSTs from
  the human's window through the same routes every human-armed bar
  uses; the runner executes the verb with all standing rules —
  serialized, scan/refusal path, and **interrupt-first**: a
  confirmed resolution on the record under active iteration
  interrupts the session before the verb runs (§3, P1-4 — yes, this
  means confirming the record pane's own proposal ends that pane
  session; the transcript's final line says so in plain words).
  **Bucket sessions are exempt from interrupt-first and survive the
  confirm** *(the review's F6)*: they hold zero write allowance, so
  there is no file race to serialize against; a still-live bucket
  session learns of the executed verb the way every concurrent
  surface does — file events. A confirm on a proposal whose record
  was resolved elsewhere takes the verb's own refusal path (stderr
  verbatim, §5) and clears the slot. The tool's return to the agent
  is immediate and honest: "rendered — the human decides; you will
  not be notified of a cancel." *(Validation clause, the review's
  F9: `dest` accepts the full 02 §1 surface forms —
  `skill-md | claude-md | reference[:<file>] | new-skill:<name> |
  hook`; the handler refuses only on parse failure; structural
  validity — e.g. a hook dest without stored script bytes — stays
  the verb's to enforce, refusal rendering verbatim.)*
- **What this does NOT change.** Session-end `proposal validate`
  (§4.3) — unchanged; bucket sessions write nothing so they add no
  validate obligation (confirmed verbs scan in-verb regardless,
  P2-7). Cross-bucket batch instructions ("route everything older
  than 30 days") stay out of v1 — each proposal is one record, one
  bar, one Enter. No auto-confirm, no trusted-verb list, no consent
  bypass of any kind.

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
- **No dashboards/scores** — the status strip and the `/report`
  screen (§11 Y-12) render counted facts with 04's honesty labels
  only; nothing modeled, no charts in v1 (counted-not-modeled, 04).
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
6. *(added 2026-07-14, landed same day)* **Decision-support contract**:
   02 §1 gains the optional `card:` map; routing-doctrine.md gains §8 +
   the `card-sections.yaml` registry (single source of the section set
   and each section's generation prompt); `validate_proposal` shape-
   checks the map; /self-learn:review renders cards card-sections-first.
   §2.3 above consumes it. Origin: first real review session
   (2026-07-14) — E-3 honeymoon verdict revised to "throughput pass,
   comprehension fail"; the user's venue verdict ("the REPL is
   definitively not the right venue for review") is recorded as G-3
   trigger evidence, with the build still gated on M2 (the worker fills
   the surface).

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

## 11. 2026-07-17 amendment set (post-11/12/13/M3 re-ground)

*This spec froze 2026-07-13 (cards amendment 07-14). Four structural
changes landed after it: doc 11 (telemetry & lifecycle — recurrence
suspects, "not holding" cards, follow-ups, contradicts), doc 12 (the
transcript miner + its R3 web-UI rider), doc 13 (ledger cutover to
`~/.self-learn` + the §7.3 product extraction), and M3 (hook + new-
skill compilers, shipped and live — v1.1). This set re-grounds every
pin those changes touched and folds the session-measured UX lessons
(E-21 presenter contamination; the doubly-proven jargon failure).
Tagged Y-n; each item names its consuming section. The G-3 trigger
(M2 shipped + worker proven) fired 2026-07-15 and M3's completion
removed the last competing workstream — the build gate is open.*

- **Y-1 · Topology re-ground (13 §7.3).** The product — CLI, plugin,
  this corpus, and the UI package this spec designs — lives in the
  standalone product repo (`AlexK-Notable/self-learn`,
  `~/repos/self-learn`). `SELF_LEARN_HOME` resolves to the **ledger**
  repo (`~/.self-learn`, its own git repo): buckets, telemetry,
  `hosts.yaml`. Target canon lives in **registered host repos**
  (`hosts.yaml`: `skills_root` + `projects[].path`). The deployed
  skill/commands/hooks are `~/.claude` symlinks into the product repo.
  Every section that assumed the pre-13 monorepo (one repo = ledger +
  canon + corpus) reads through this item.
- **Y-2 · Pane read scope, re-derived (consumes §4.3's W-3 tiers;
  replaces its scope set; revised same day after the gate-zero blind
  review read the first draft as a prospective loosening — the
  narrowed form below is what the register records).** Three allowed
  read roots, each resolved and `realpath`-canonicalized at session
  start, matched as path prefixes: **(1)** the resolved
  `SELF_LEARN_HOME` tree (the ledger — records, proposals,
  telemetry; `cwd` = bucket root stays inside it); **(2)** each
  registered host's **canon surfaces only — never the whole host
  repo**: the skill trees under `skills_root`
  (`plugins/*/skills/*/` — SKILL.md + references), each project
  host's compile-target files (CLAUDE.md, LEARNINGS.md, its
  reference-file dirs), and the **hook-canon dirs** (13 §7.3/D1:
  `<skills_root>/hooks/self-learn/` for project/user-scope guards,
  `plugins/*/hooks/` for skill-scope — a pane session on a
  hook-destination record must be able to read existing guards for
  overlap checks; delta-review fold 2026-07-17) — enumerated by
  **one CLI-owned helper**
  (`canon_read_roots()`, built at 10 U0; the pane callback imports
  it, never keeps a second list — P2-4); **(3)** the plugin
  `references/` dir (routing-doctrine.md, card-sections.yaml,
  pane-charter.md), resolved relative to the ui package's own
  installed location — never via `SELF_LEARN_HOME`. Everything else:
  deny with reason (user-scope `~/.claude/CLAUDE.md` stays
  excerpt-only in the first user message — unchanged). **Why
  canon-surfaces, not host roots** (the gate-zero finding, accepted):
  `host add` consents to *compilers writing managed sections* — it
  was never consent for a model-backed session to read an entire
  repo tree, untracked files included; whole-root reads would have
  silently widened with every future registration (and Y-11 actively
  encourages registering foreign repos). Canon surfaces are exactly
  what the analyst must quote and diff against (already-canon
  checks, target excerpts); anything beyond them, the agent asks the
  human — deny-with-reason is the ask. Companion (U0):
  `host add` prints a one-line consent note naming the consequence
  ("registers this repo's canon surfaces as compile targets and
  analyst-readable"). Write scope is UNCHANGED (the item's own
  files, exact-path — §4.3).
- **Y-3 · Transient-state paths re-based (13 §6 / H-4).** `<cache>` =
  `${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(resolved
  SELF_LEARN_HOME)[:8]>/` — the CLI already owns this derivation as
  one function; the ui package **imports it, never reimplements it**
  (P2-4's one-computation rule). Lives there: `ui.log`,
  `pane-doctrine.md`, and the X-8/X-12 token-file fallback. The
  runtime token's primary home stays `$XDG_RUNTIME_DIR/self-learn/`.
  02 §3's transient-state line updates accordingly (§10 item 3 is
  superseded on paths by this item).
- **Y-4 · "Is it holding?" section (11 §2.2 lands on the surface).**
  Front gains a section after the bucket walk: routed records with
  unconfirmed recurrence suspects (suspects beyond the record's own
  confirmed `recurrences`, nonce-matched — the CLI's existing
  deterministic computation, exposed via `report --json
  .recurrence_suspects`, 08 §1 dated edit; the server never
  re-derives it). Row, in plain words: "Routed <date>. Sighted <N>
  times since." Actions *(key set completed 2026-07-17 after gate
  zero — 11 §2.2's card is four-way and every way needs an
  affordance)*: **`t` tolerate** — arms `confirm-recurrence
  <id> --event <nonce> --tolerate` (note encouraged, the "why the
  rule stays"); **`c` confirm** — same verb without `--tolerate`
  (recurrence is real, fix comes later); **retire** — `g` graduate
  works directly on the row (woven into canon; supersede-style
  retirement stays session work). Revise and Escalate remain
  session work — they are *captures* (`teach --supersedes`), and §8's
  no-in-surface-capture stands; the row says so in plain words and
  shows the command. One suspect card per record, newest nonce.
- **Y-5 · Miner section (12 R3/A1, binding).** The Front page gains a
  miner block: last-run age + staleness on the status strip (§2.1),
  and an expandable run list (per-run: outcome, trigger, scanned,
  landed, folded, recurrences — the A1 journal rendered verbatim) via
  `mine status --json` — **which already exists (shipped with the miner,
  M2.5; gate-zero correction 2026-07-17: the first draft wrongly
  listed it as new substrate)** — emitting the pinned `{last_run,
  stale, runs: […]}`; the journal file stays the
  truth and the CLI owns staleness derivation ("CLI parity precedes
  the UI", 12 A1). Exactly **one action**: force-run, arming
  `self-learn mine run` (R3's one-action pin — nothing else is
  actionable from the miner block). Mined pending records carry a
  "mined" provenance badge on rows and Detail (from `list --json
  .source`, 08 §1 edit) — provenance display, zero behavioral
  difference (12's L0 rung: mined cards adjudicate identically).
- **Y-6 · Follow-ups.** The status strip shows the open-follow-ups
  count (`status --json .open_followups`, existing); a small
  read-only list from `report --json .open_followups` — **which already
  exists** (rows `{id, bucket, action, unblocks_on, note, routed_at}`
  — gate-zero correction 2026-07-17: the first draft wrongly pinned a
  new conflicting shape; the surface consumes the existing one) —
  renders each with `followup done <id>` arming. Counted facts;
  no aging alarms in v1.
- **Y-7 · Hook & new-skill proposals on Detail.** Consumed at §2.3
  region 2 (amended in place): full stored script + replay examples
  for `hook`; scaffold preview for `new-skill:<name>`; M3
  verbatim-apply caption instead of the regenerate-at-apply caption —
  the one documented exception (08 M3 pins) surfaces truthfully.
- **Y-8 · Contradiction edges (11 §2.4).** Detail renders a
  proposal's `contradicts:` list in plain words ("this conflicts with
  <target>") above the action bar. After a successful `route`, the
  response partial offers each accepted edge as its own armed action
  — `link contradicts <id> <target>` — analyst proposes, the human
  accepts per edge, only the verb writes. Declining an edge is just
  not arming it.
- **Y-9 · Human-language-first rendering (pinned UX rule; evidence:
  E-21 measured presenter contamination live, and the 2026-07-16
  review session's "i don't even know what you mean by a guard").**
  Across every screen: the leading text of any row or card is the
  proposal's leading card section (registry order) or the record
  title — never an id, enum value, or scope slug; `lrn-…` ids,
  destination enums, and bucket slugs render as trailing/footer
  metadata. Group headers and action labels are plain words (the
  §2.2 display-label rule generalized). The **pane charter authored
  at build (§4.3/10 U5) must include the routing-doctrine §8
  register**: pane prose renders directly to the decision-maker, so
  system vocabulary in pane output is a defect, not a style choice.
- **Y-10 · Color never the sole carrier (accessibility pin) + dark
  theme in v1.** Every badge/status distinction (fresh/stale,
  scan-blocked, deferred, mined, already-canon, unregistered-host,
  applying/error) carries a text label or glyph — hue alone is
  forbidden. Grounds: the standing user theme is daltonized;
  hue-only signals would be invisible by construction to this
  surface's own user. Dark/light via `prefers-color-scheme` is
  **promoted from the 10 §3 polish backlog into U3 scope** (CSS
  custom-properties block; styling is cheap here — the promotion is
  dated and deliberate).
- **Y-11 · Unregistered-host flow (live case: the first organically
  mined card sits in a foreign bucket today).** A record whose
  bucket has no `hosts.yaml` registration renders an "unregistered
  project" notice on Bucket and Detail with the exact copyable
  command (`self-learn host add <path>`). Resolution arming stays
  available — the verb is the enforcer and its refusal renders
  verbatim (§5 row added). v1 does **not** arm `host add` from the
  surface: registration is a canon-target decision, deliberately
  human + CLI (10 §4 row added). Data: `list --json
  .host_registered` (08 §1 edit).
  **Amended 2026-07-17 (feedback round 1 item 5; reworked same day
  after its blind spec review — findings folded below):** the 10 §4
  row's own revisit condition — "explicit user ask" — fired,
  near-verbatim: *"I should essentially be able to do everything I
  need to do via UI and not have to open a terminal."* The v1
  rationale conflated the DECISION with the HAND: registration
  remains a canon-target decision and remains the human's, but a UI
  arm/confirm round-trip IS the human deciding — the surface may now
  arm `host add <path>`. Grounding: `host add` is strictly LESS
  consequential than the already-armed `route` (ledger-only commit,
  no push, no compile, trivially unwound via `host remove`), so §1's
  arm rationale covers it with margin. Build pins (each a folded
  review finding):
  - **Path provenance (security):** the armed path is SERVER-derived
    from the record's own bucket `meta.yaml`
    (`ledger.project_path_for`, the same derivation
    `host_add_command` already uses) — NEVER a client-submitted
    value. A client field may pick the post-success return page (a
    constrained relative shape), nothing more.
  - **Consent visibility:** the CLI prints its consent line on
    stdout, which the verb runner discards by contract (§3) — so the
    ARM STATE must itself render the consequence in plain words:
    registering makes the project a canon WRITE target (managed
    section compiled in on the next route) and makes it
    analyst-READABLE (pane read scope widens via
    `canon_read_roots()`), plus the exact command that will run.
  - **Surface shape:** "same runner" holds at the subprocess seam
    only; the arming machine is record-scoped, so host-add gets the
    surface's FIRST bucket-scoped arm/disarm/confirm route triple and
    an id-less armed rendering (same `.action-bar[data-armed]`
    contract, so Enter-confirms / any-key-disarms works unchanged).
  - **Scope limitation:** derivable only for PROJECT buckets;
    skill/user-scope unregistered notices keep their prose fallback
    (no candidate path exists — a skills-root registration is a
    different invocation).
  - **Post-success:** confirm force-refreshes the bucket scope and
    redirects back to the arming page (Detail if armed from a record,
    else the Bucket page); the notice disappears because
    `host_registered` re-reads true.
  - **No affordance key:** deliberately NO keymap entry —
    registration is a rare, once-per-project act; the keymap stays
    lean (dated choice, not an omission).
  - **No agent path:** §4.3's "no path to route" extends verbatim to
    `host add` — the pane agent must never be able to widen its own
    read scope or mint write targets.
  Corollary, the generalized principle, now with an auditable
  predicate: any surface text asking the user to run a terminal
  command is a defect unless recorded here as exempt. T-A carries a
  template-source assertion: the only `self-learn …` command literals
  in templates are the EXEMPT LIST — (a) `teach --supersedes` in the
  holding row's session-note (capture is deliberately out of surface
  scope, §8/Y-4), (b) verb stderr rendered verbatim in error strips
  (§5 pins the server adds no interpretation), (c) the 403 page's
  `self-learn-ui-open` recovery line (no session to arm from).
- **Y-12 · `/report` screen.** One read-only page rendering `report
  --json` **plus `status --json`'s `metrics` and `supply_mix` blocks
  (gate-zero correction 2026-07-17: those two live in status, not
  report — the screen merges the two pinned reads, deriving
  nothing)**: the 04 metrics with their honesty labels, supply mix,
  mined accept rate, supersede rate, routed-live rows with
  recurrence counts, telemetry counters. Reached by a Front link
  (no dedicated key). No charts, no scores, no derived numbers the
  CLI didn't compute (04 counted-not-modeled; §8 amended in place).

- **Y-13 · Agentic chat panes with verb proposals (feedback round 1
  item 7 — G-3's second act; design brief
  `feedback/2026-07-17-chat-panes-design-brief.md`).** The user's
  directive, near-verbatim: a chat window on Bucket AND per-record,
  system-aware ("the contexts it should be ready to talk to me
  about — my buckets, the lesson, routing"), and able to act
  ("shouldn't just be a chat bot. if i tell it to route to a
  different bucket, for example, it should be able to do that").
  **Invariant treatment: refines, never repeals, "only the human
  routes"** — the agent gains a path to REQUEST (one tool that
  renders the standing armed bar), never a path to EXECUTE (the verb
  runs only off the human's confirm POST); 07 §3's bullet carries the
  dated refinement note. Normative mechanism lives at §4.5; consuming
  amendments: §1 (`p` key), §2.2 (bucket pane), §2.4 (proposal bar on
  the iterate split), §4.2 (surface-model third prompt source; bucket
  session = same lifecycle), §4.3 (single in-process MCP tool server;
  "no path to execute"; bucket sessions hold zero write allowance).
  Decisions of record, each dated here: **(1)** proposable set =
  route/reject/defer/graduate ONLY — `host add` excluded (Y-11's
  no-agent-path pin overrides the brief's suggestion), collapse and
  the telemetry verbs excluded v1; **(2)** refuse-not-replace while
  the proposal slot is occupied (what-you-see-is-what-you-confirm);
  **(3)** ONE live session globally across both pane variants (the
  brief's default posture, adopted; revisit only on felt cramping in
  use); **(4)** bucket sessions read-and-propose only, exempt from
  interrupt-first (zero writes ⇒ no race), surviving confirms;
  **(5)** bucket-pane first-message context = bucket summary +
  grouped pending rows (leading human line per Y-9, id as metadata,
  destination, freshness, deferred/cluster tags), capped at 50 rows
  with an honest truncation line — ambiguity about which record an
  instruction means is a clarifying question, never a guess
  (doctrine §8); **(6)** mechanism grounded empirically at drafting:
  `tool`/`create_sdk_mcp_server`/`mcp_servers` all present on
  installed SDK 0.2.121 — T-B must still prove the callback sees the
  tool call on the resolved build version (footgun B lineage);
  **(7 — added at the same-day rework, after this amendment's own
  blind spec review returned NEEDS REWORK; findings folded in
  place):** proposals render WAITING, never armed — the human's `y`
  arms, Enter confirms (two keystrokes, exact parity with the
  human's own actions; kills the replace-under-Enter race the
  review's F1 proved reachable through the stateless client-side
  arm machine); the pending proposal is a server-held single
  in-memory slot with an exhaustive clear-set (F2); single-armed-bar
  -per-document is now a tested invariant (F3); `pane_proposal` SSE
  is scope-gated (F8); the note renders as labeled agent prose,
  display-capped (F7).
  Substrate: NO new CLI fields — the pane consumes `list --json`
  shapes the surface already reads; the surface-model reference file
  is new tracked prose (authored at 10 U12 — corrected at the
  rework; the first draft said U5, a task already closed).
**Substrate edits this set requires elsewhere** (same discipline as
§10 — until landed, this list is authoritative; corrected after gate
zero 2026-07-17 against the live CLI): **08 §1** dated edit — the
genuinely NEW fields are `list --json` +`bucket`, `+host_registered`,
`+source`; `report --json` +`recurrence_suspects`; the CLI-owned
`canon_read_roots()` helper + the `host add` consent line (Y-2);
optional-if-cheap `status --json .sections_over_cap` for a
graduation-opener banner — all built as 10's U0. Already existing and
merely CONSUMED (the first draft mis-listed them as new): `mine
status --json` (shipped M2.5, shape `{last_run, stale, runs}`) and
`report --json .open_followups` (rows `{id, bucket, action,
unblocks_on, note, routed_at}`). **12 R3** gains a dated pointer line;
**02 §3** transient-state pointer per Y-3. 03's register: the gate-
zero blind review DID read Y-2's first draft (whole-host-root reads)
as a prospective loosening — per this paragraph's own rule that
finding reopened the register; the resolution is the narrowed
canon-surfaces scope now in Y-2, recorded as a dated 03 note on the
G-3 row (pending user ratification — the user may still choose the
wider posture; the narrow one is the conservative default).
