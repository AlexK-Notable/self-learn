# 10 — Surface build plan: durable, orchestrator-agnostic execution of G-3

*Rewritten 2026-07-12 in the post-correction /goal cycle (renamed from
`10-tui-build-plan.md`; the Textual revision lives in git history
through `1ce408c`). Purpose identical to 08's: any competent
orchestrator or implementation sub-agent can build the adjudication
surface from this document plus the corpus, with judgment calls that
genuinely need a strong reasoner or the human routed explicitly (§4),
never silently absorbed.*

**Authority.** `09-surface-spec.md` is design authority for everything
here; on any conflict, **09 wins and the conflict is a finding** —
stop, record it, surface it; never improvise a reconciliation
mid-build. `08-build-plan.md` remains execution authority for M1–M3
and owner of every shared pin (resolution verbs, `--json` shapes,
`events.jsonl`, sentinel, doctrine file, `proposal validate`,
`--no-push`); this plan **consumes** those pins and never restates
them normatively — where a §1 row touches one, the row cites 08 and
adds only what is surface-local. **Execution is gated on G-3's
trigger** (03: M2 shipped and the worker proven). Running this plan
before the trigger fires is itself a §4 escalation — ask the human,
do not start.

---

## 0. Operating rules (read before any task)

Rules 1–6 of 08 §0 apply verbatim (worktree; autosync hazard on
master; test-first honestly; tests never touch the real ledger or
`~/.claude` — `SELF_LEARN_HOME` always points at a throwaway repo in
tests; escalation discipline; repo conventions). Surface-specific
additions:

7. **Tests never talk to the network or a real model.** UI logic is
   tested against a `FakeEngine` behind the `PaneEngine` seam; the
   `sdk` engine module itself is tested by pointing the SDK's
   `cli_path` option at a PATH-shimmed fake `claude` that replays
   canned stream-json transcripts (the SDK wraps the CLI — proven in
   the auth empirical test, run 2). The ONLY live-model executions in
   this plan are the §2 live trials, run deliberately and logged.
8. **Tests never touch the user's desktop, real cache, or real
   runtime dir.** `notify-send`, `hyprctl`, `xdg-open`, `systemctl`,
   and browsers are PATH-shimmed in tests; `$XDG_RUNTIME_DIR` and
   `$XDG_CACHE_HOME` are redirected to tmpdirs (the server resolves
   cache/runtime homes via XDG vars; pinned literal paths hold in
   production — carried, P3-10b). Live desktop behavior is §2
   acceptance, not CI.
9. **Dependency pins are never bumped mid-build.** `claude-agent-sdk`
   is minor-pinned (§1); htmx is vendored at an exact version with a
   recorded hash; a forced bump (security) is a §4 escalation.

## 1. Pinned interface contracts (surface-local; shared pins live in 08 §1)

| Contract | Pin | Cites |
|---|---|---|
| Code layout | UI package: `plugins/self-learn/ui/` — a uv project (`pyproject.toml`, `src/self_learn_ui/…`, `templates/`, `static/`, `tests/`). Entry point: `plugins/self-learn/scripts/self-learn-ui` (shebang'd, extensionless): `#!/usr/bin/env bash` + `exec uv run --project "$(dirname "$(readlink -f "$0")")/../ui" self-learn-ui "$@"` — **`readlink -f` is load-bearing** (carried, P3-1): install.sh deploys scripts as `~/bin` *symlinks*, so bare `$(dirname "$0")` resolves beside the symlink, not the repo (`home-net-capture` precedent; same rule for sibling-path references in `self-learn-ui-open`/`self-learn-notify`). Subcommands: `self-learn-ui serve` (foreground server — what systemd runs) · `self-learn-ui --help` | 09 §3, §6; repo CLAUDE.md |
| Service | `plugins/self-learn/systemd/self-learn-ui.service` (`ExecStart=%h/bin/self-learn-ui serve`, `Restart=on-failure`), installed/enabled by install.sh **via the same mechanism as the existing watcher unit** (exact install-side wiring verified at U10 against install.sh as it then stands — a repo-convention consume, not a new invention). Foreground `self-learn-ui serve` is the documented no-systemd fallback | 09 §3 |
| Network & security | Bind `127.0.0.1` only, port `SELF_LEARN_UI_PORT` default **7357**. Middleware (all in one module, ~30 lines, tested in T-A): reject unless `Host` ∈ {`127.0.0.1:<port>`, `localhost:<port>`}; bearer token minted per service start (`secrets.token_urlsafe`), written 0600 to `$XDG_RUNTIME_DIR/self-learn/ui-token`; `GET /?token=…` (any path) sets it as a `SameSite=Strict; HttpOnly` cookie and 303-redirects to the clean URL; every mutating route is POST-only and requires valid cookie **and** the `HX-Request` header (cross-site forms cannot set custom headers); failure → 403 page naming `self-learn-ui-open`. **Render-path pins (W-1, 2026-07-12)**: Jinja environment constructed with autoescape ON (never disabled per-block); ALL markdown rendering (records, rationale free-text, pane blocks — pages and SSE frames alike) through markdown-it-py constructed with **`html=False`** (never the default preset — it passes raw HTML, empirically confirmed); trusted raw-HTML injections limited to Pygments output + own templates; every response carries `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'` | 09 §3 |
| Companion scripts | `plugins/self-learn/scripts/self-learn-ui-open` (launcher, **the only WM/browser-aware file**: ensure service via `systemctl --user start self-learn-ui.service` (skip if systemctl absent); read token; focus existing window `hyprctl dispatch focuswindow class:self-learn-ui`, else launch app window — browser resolved in order `$SELF_LEARN_UI_BROWSER` → `chromium` → `google-chrome-stable` → fallback `xdg-open <url>`; app-window launch pins `--app=<tokened-url> --class=self-learn-ui` and degrades to `xdg-open` when unsupported) · `plugins/self-learn/scripts/self-learn-notify` — **argv pinned, carried verbatim (P3-6)**: `self-learn-notify --line "<rendered human string>" --ids <csv-of-record-ids>`; `notify-send -A open --wait`; on `open` → `self-learn-ui-open --record <first-id>`; no daemon — one process per notification | 09 §3; 08 §7.1 |
| Dependencies | `fastapi` + `uvicorn` + `jinja2` + `pygments` + `markdown-it-py` + `watchfiles` + `PyYAML` + **`claude-agent-sdk>=0.2.116,<0.3` (minor-pinned; probes ran on 0.2.116)**; dev/test: `pytest`, `pytest-asyncio`, `httpx`. **Vendored static, committed**: `static/htmx-2.0.9.min.js` (exact version + recorded sha256 in the file header comment; the htmx 4.x line is ignored) · `static/app.js` (authored, ~40-line keydown handler + EventSource client) · `static/style.css`. No node, no bundler, no CDN. Python ≥3.11 | 09 §6 |
| Keymap (single source) | `keymap.py` table: `j/k`+arrows move · `Enter/l` drill · `Esc/h` up (Esc in pane = interrupt first) · `a` route · `d` reject · `f` defer · `g` graduate · `i` iterate · `o` cycle destination · `n` note · `r` retry pane · `?` help overlay. Armed action: resolution key arms, `Enter` executes, any other key disarms. Keys inert while focus is in a text input. **No Ctrl/Alt chords** (browser owns them — 09 §1). Rendered from the one table into the footer partial, the help overlay, AND the JSON blob `app.js` consumes — never duplicated. Install/docs note: Vimium-class extensions need a `localhost:7357` exclusion (U10 docs item) | 09 §1 |
| SSE protocol | `GET /events` (EventSource in app.js; token-cookie-gated like every route): JSON envelopes, one `type` field each: `{"type":"refresh","scope":"front"\|"bucket:<b>"\|"record:<id>"}` (client re-requests its current partial if in scope) · `{"type":"applying","verb":…,"id":…,"state":"start"\|"done"\|"error"}` · `{"type":"bulk_progress","done":n,"total":m,"failed_id":null\|id}` · `{"type":"banner","text":…}` · pane events namespaced `{"type":"pane_delta","text":…}` / `{"type":"pane_block","html":…}` / `{"type":"pane_tool","name":…,"target":…}` / `{"type":"pane_result","status":…,"cost":…,"turns":…}`. Unknown types ignored client-side. Reconnect: EventSource auto-retry + the 10 s poll fallback (09 §5) | 09 §3, §4 |
| Pane `sdk` engine construction | **Empirically pinned (probes memo)**: `ClaudeSDKClient` (streaming mode — `can_use_tool` refuses to run under string-prompt `query()`, and the finite-generator `query()` pattern closes the control channel: footguns A/C) with `ClaudeAgentOptions`: `include_partial_messages=True` (chunk-level deltas ~5 Hz — probe 1) · `setting_sources=[]` **explicitly** (unset loads the full user environment — probe 3; never rely on the documented default) · `system_prompt` = compiled doctrine string (09 §4.2) · **`allowed_tools=[]`** (a listed tool is auto-approved before the callback — footgun B) · `disallowed_tools=["Bash","Task","WebSearch","WebFetch"]` (structural denies as belt; the callback is the braces) · `can_use_tool` = the charter callback (canonicalize paths via `realpath` before matching; **read scope per 09 §4.3's W-3 pin**: reads inside `cwd` auto-approve and never reach the callback — accepted; the callback allows Read/Grep/Glob under resolved `SELF_LEARN_HOME` and denies-with-reason every read outside the repo; Edit/Write per 09 §4.3's exact-file rules; deny-with-reason otherwise) · `cwd` = bucket root · `model=$SELF_LEARN_PANE_MODEL` · `fallback_model`, `max_turns`, `max_budget_usd` — **fields empirically confirmed on 0.2.116** (phase-A introspection; re-verify at U5) · session-persistence-off + strict-MCP: exact option names resolved at U5 start (verify-at-build ledger). Wrapper-side cap enforcement exists only as the contingency for a future SDK dropping a field (09 §4.2/W-4). Tolerate unknown message types mid-stream (`RateLimitEvent` observed on Max OAuth). Interrupt: SDK interrupt call, then client close at +2 s, kill at +5 s | 09 §4.1–4.3 |
| Engine event protocol (internal seam) | `PaneEngine.start(ctx) → AsyncIterator[PaneEvent]`; `PaneEvent = block_start(kind) \| text_delta(str) \| tool_use(name, target) \| file_changed(path) \| result(status, cost_usd\|None, error\|None)`; `send(str)`, `interrupt()`, `close()`. The UI imports only this module; SDK message parsing lives entirely inside the sdk engine. The specced-not-built `cli` engine (09 §4.1) satisfies the same seam; its invocation pin set is the TUI revision's §1 row (git history `1ce408c`) | 09 §4.1 |
| Doctrine compile | `<cache>/pane-doctrine.md` = concat of `references/routing-doctrine.md` + `references/pane-charter.md` (both tracked in the plugin; charter authored in U5 from 09 §4.3's charter text). Recompiled when either source mtime > compiled mtime. Byte-stable between recompiles; read into the `system_prompt` string at session start | 09 §4.2 |
| Server transient state | `~/.cache/claude-skills/self-learn/ui.log` (capped ~1 MB, same truncation as `worker.log`) · `<cache>/pane-doctrine.md` · `$XDG_RUNTIME_DIR/self-learn/ui-token`. Nothing else; no config file | 02 §3, 09 §3/§4.4 |
| Env vars (complete) | `SELF_LEARN_HOME` (08) · `SELF_LEARN_UI_PORT` (default `7357`) · `SELF_LEARN_UI_BROWSER` (launcher only) · `SELF_LEARN_PANE_MODEL` (default `claude-sonnet-5`) · `SELF_LEARN_PANE_BUDGET_USD` (default `1.00`) · `SELF_LEARN_PANE_MAX_TURNS` (default `15`) · `SELF_LEARN_PANE_ENGINE` (`sdk`; `cli` → exit with "engine not built — 09 §4.1") | 09 §4.4 |
| Refresh mechanics | `watchfiles` watcher over every bucket's `pending/` + `proposals/` + `events.jsonl`, 300 ms debounce; SSE `refresh` push; 10 s client poll fallback; forced push after every verb return. Bucket set re-discovered on Front-page request (a new skill's first record must appear without restart) | 09 §3 |
| Verb runner | One subprocess at a time server-wide (asyncio queue — multiple tabs share it); resolution POSTs rejected with "applying…" state while running; interrupt-first check **at verb dispatch** (09 §3, P1-4); bulk loop = sequential `graduate <id> --no-push` + terminal `self-learn push` on exit **success or abort** (08 §1 as amended); per-item progress via SSE; halt-on-first-failure with failing id shown | 09 §2.2, §3 |
| Rendering | Diffs: Pygments `DiffLexer`; proposal YAML: Pygments YAML lexer; markdown (records, transcripts' finished blocks): `markdown-it-py` server-side; live pane deltas append as plain text, blocks re-render server-side at block boundaries (09 §4.1 — no client-side markdown dependency). The preview-honesty caption is a fixed string under every diff (02 §4's wording) | 09 §2.3, §4.1 |
| Screen-state derivation | Pure functions: `(list --json output, status --json output, merge-yaml set, sentinel mtime) → screen model` — templates render models; no route handler reads ledger files directly; all reads go through one `ledger.py` module (testable headless, 09 §7) | 09 §3, §7 |

**Verify-at-build ledger** (each gets a scripted check at its task's
start; failures route per §5): exact `ClaudeAgentOptions` names for —
session-persistence off · strict MCP (`max_turns` ·
`max_budget_usd` · `fallback_model` pre-verified 2026-07-12 by
phase-A introspection on 0.2.116, alongside the probes'
`include_partial_messages`, `setting_sources`, `can_use_tool`,
`allowed_tools` shadowing, `cli_path`; **re-verify all on the
resolved SDK version at U5 and record both SDK + CLI versions in the
U5 test log**) · htmx
vendored file sha256 matches the recorded release hash · systemd unit
install mechanism in install.sh as it stands at U10 · `hyprctl
dispatch focuswindow class:…` syntax on the live Hyprland ·
app-window `--class` behavior of the resolved browser.

## 2. Acceptance fixtures & live trials (defined FIRST, built last)

Trials log: `docs/specs/self-learn/fixtures/ui-trials.md` (same
discipline as 08 §2's `trials.md`: every live trial gets a dated
entry — command, environment, outcome, pass/fail against its
predicate).

- **T-A · Headless suite** (CI): constructed throwaway ledgers
  (empty; mixed buckets; deferred records; stale/fresh/missing
  proposals; merge clusters; homogeneous already-canon group) →
  assert derived Front/Bucket/Detail models field-by-field; httpx
  against the ASGI app asserting rendered partials and full flows:
  arm→disarm→confirm POSTs, note entry, `o` cycling +
  parameterized-destination skip, bulk-collapse arming the graduate
  loop, **cluster expand → survivor select/override → armed
  `route <survivor> --collapse <cluster-id>` with argv asserted
  against the fake `self-learn`** (carried, P3-2), **advance-to-next
  after resolution + bucket-clear return to Front** (carried, P3-9),
  keymap JSON = footer = help (single source), **and the security
  middleware: wrong Host rejected · tokenless mutation rejected ·
  mutation without `HX-Request` rejected · token-URL → cookie →
  redirect flow · a record body containing `<script>` and
  `<img onerror=…>` payloads renders escaped (page AND SSE
  `pane_block` frame) · the pinned CSP header present on every
  response (W-1)**. *Predicate:* every 09 §2/§3 behavior named in this
  sentence has a test that fails when its logic is inverted.
- **T-B · Pane permission live refusal** (live, logged): a real
  `sdk`-engine session over a sacrificial record in a throwaway
  `SELF_LEARN_HOME`, instructed verbatim to (1) run `git log` via
  Bash, (2) write a file outside its allowlist, (3) read a file
  outside the repo (e.g. `~/.zshrc` — the W-3 read boundary), (4)
  edit its own record — expect refuse/refuse/refuse/succeed, with (1)
  blocked by `disallowed_tools` and (2)/(3) by the callback
  (`ResultMessage.permission_denials` is the evidence — probes memo).
  *Predicate:* 4/4; any failure of (1)–(3) triggers the 09 §4.3
  ladder and re-trial before U6 proceeds.
- **T-C · End-to-end adjudication** (live, logged): seeded record +
  valid proposal in a throwaway repo with a bare remote → service up →
  approve via the real POST route (tokened httpx or the browser) →
  *predicate:* route commit exists with pinned message, record in
  `resolved/`, proposals `git rm`'d, push landed on the bare remote,
  sentinel released, SSE `refresh` observed — all verified from the
  filesystem/git, not from UI output.
- **T-D · Deep-link chain** (live desktop, logged):
  `self-learn-notify` with a fake event (ids + aggregate) → click
  "open" on the swaync notification → *predicate:* the app window is
  focused-or-launched showing that record's Detail; a second
  notification for a different id focuses the same window at the new
  record (server is the single instance; window identity proven via
  `hyprctl clients` class match).
- **T-E · Stream + interrupt smoke** (live, logged): Iterate on a
  seeded record; *predicate:* streamed text visibly renders
  incrementally (chunk cadence per probe 1); Esc ends the stream with
  the SDK subprocess gone within 5 s; the post-session
  `proposal validate` call ran and its exit code surfaced per the
  08 §7.1 pin (0 → stamped fresh; 1/2 → the right badge + error
  strip); interrupted-then-approve completes.

Merge to master requires: T-A green in CI; T-B/T-C/T-D/T-E each with
a passing dated entry in `ui-trials.md`; the 09 §5 degradation table
walked row-by-row with each row's behavior demonstrated (test or
logged manual check).

## 3. Task DAG

Each task = tests + code + DoD, same contract as 08 §3. Dependencies
in brackets.

- **U1 · Scaffold** []: uv project, entry wrapper (+`serve`
  subcommand), vendored htmx (hash recorded) + `app.js` skeleton +
  base template/CSS, env parsing, capped logging, keymap module, CI
  wiring (pytest + pytest-asyncio + httpx). *DoD:*
  `self-learn-ui --help` runs from a clean clone via the wrapper;
  lint+test skeleton green.
- **U2 · Ledger model** [U1]: `ledger.py` — CLI `--json` invocations
  (list incl. `--include-deferred`, status), record/proposal/merge
  YAML + diff readers, screen-model derivation (pure), watcher +
  debounce + poll + forced refresh, bucket re-discovery. *Tests:*
  T-A's model half. *DoD:* screen models correct on all constructed
  ledgers.
- **U3 · Routes & templates** [U2]: Front/Bucket/Detail routes +
  partials, status strip, action bar (arm/confirm/disarm as POSTs),
  note input, help overlay, banners ("resolved elsewhere",
  bucket-clear), Pygments/markdown rendering, **security middleware**,
  SSE endpoint + `app.js` EventSource client + keydown handler.
  *Tests:* httpx route/partial suite + middleware suite. *DoD:* T-A's
  interaction + security halves green.
- **U4 · Verb runner** [U3]: serialized async subprocess queue,
  reject-during-run, error strip (stderr verbatim), bulk graduate
  loop (`--no-push` + terminal push success-or-abort,
  halt-on-failure), interrupt-first dispatch check (stub pane),
  post-verb refresh push. *Tests:* PATH-shimmed fake `self-learn`
  asserting argv sequences (incl. push-on-abort AND
  `route <survivor> --collapse <cluster-id>` — P3-2); race test: verb
  during fake-iteration → interrupt called first.
- **U5 · Pane engine (sdk)** [U1]: PaneEngine seam, ClaudeSDKClient
  wrapper (streaming client, charter `can_use_tool` callback, message
  → PaneEvent mapping with unknown-type tolerance, interrupt ladder,
  caps incl. wrapper-enforced fallbacks), doctrine compiler,
  `pane-charter.md` authored, **verify-at-build ledger executed and
  logged**. *Tests:* `cli_path` → fake `claude` canned transcripts
  (happy path, error result, mid-stream kill, malformed line →
  skip+log, unknown event type → skip, `interrupt()` no-op on an
  ended session); callback unit tests (path canonicalization, id
  siblings only). *DoD:* events replay byte-exact; live smoke
  deferred to T-B/T-E.
- **U6 · Iterate split** [U3, U5]: split layout, SSE transcript
  (delta append + block re-render), input line, session lifecycle
  (fresh per Iterate, one live at a time, cap surfacing, cost
  footer), Esc interrupt, `q` close, post-session
  `proposal validate <id>` with **exit-code discrimination (0
  stamped · 1 schema-invalid · 2 scan hit → "scan-blocked" badge +
  error strip, never stderr parsing)**, stale badge refresh, live
  re-render on `file_changed`. *Tests:* FakeEngine flows incl. a fake
  `self-learn` returning each exit code.
- **U7 · Service & launcher** [U3]: systemd unit, token minting +
  middleware wiring end-to-end, `self-learn-ui-open` (shimmed
  systemctl/hyprctl/browser tests), deep-link edge cases
  (resolved-id → bucket + banner, first-id rule).
- **U8 · Notifier swap** [U7]: `self-learn-notify` helper (pinned
  argv); the M2 emission point swap (the 08 §7.1 pointer executes — a
  change in the *worker's* notify call, same PR, own test: headless
  fallback intact, action degradation intact); events.jsonl tail as
  wake-up source. *Constraint:* M2 notification template, payload,
  and events line byte-unchanged (08 §7.1).
- **U9 · Degradation walk** [U4, U6, U7]: implement + test every
  09 §5 row not already covered (engine start fail + retry, per-block
  fallback when no `text_delta`, SSE reconnect strip, 403 page,
  no-proposal Detail, stale badge, corrupt events line,
  worker-overdue strip, plain-tab fallback).
- **U10 · Deploy + docs** [U1–U9]: install.sh picks up the three
  scripts via the existing glob + installs/enables the service unit
  (verify symlinks + no dangling — repo CLAUDE.md deploy-sweep rule);
  SKILL.md + README sections (launch, keys, env vars, engine note,
  browser notes incl. the Vimium localhost exclusion); `10`
  change-control appendix opened.
- **U11 · Acceptance** [all]: run T-B/T-C/T-D/T-E live, log
  `ui-trials.md`, walk the degradation table, then §6.

Parallelism: U5 alongside U2–U4; U7/U8 alongside U5/U6. Polish
backlog (explicitly deferred, not silently dropped): `proposal
validate` inside the auto-interrupt sequence (carried from the TUI
revision's backlog); pagination/virtual scrolling if a bucket ever
exceeds ~500 rows; dark/light theme via `prefers-color-scheme`
(styling is cheap here — but it is polish, not scope).

## 4. Judgment calls that stay routed

| Situation | Route |
|---|---|
| Any §1 verify-at-build check fails with no §5 playbook covering it | Human |
| The charter callback fails T-B and the 09 §4.3 ladder is exhausted | Human (never loosen the surface) |
| `claude-agent-sdk` minor-pin unavailable/broken for a required fix | Human (bump is a §0 rule-9 decision) |
| Visual styling/layout taste beyond 09 §2's structure | Human, with screenshots — agents may iterate via Playwright/claude-in-chrome toward approved structure, never past it solo |
| Changing pane model/budget/turn defaults | Human (user's cost call — same as worker model pin) |
| Building the `cli` engine (ladder rung 4, 09 §4.1) | Human confirms the trigger fired |
| Binding beyond 127.0.0.1, weakening any security middleware check | Human (06-horizon Stage-2 territory, never a build-time convenience) |
| A keybinding conflict with browser-reserved keys surfacing in practice | Propose remap to human; keymap is UX surface |
| G-3 trigger not fired but build requested | Human (gate discipline) |
| A 09↔corpus or 09↔10 conflict discovered mid-build | Stop; finding; human (authority rule, header) |

## 5. Eventuality playbooks

- **SDK message schema drift** (SDK or CLI update changes shapes):
  the engine logs the raw message, skips unknown types (pinned
  tolerance, §1), and degrades to per-block rendering; if sessions
  become unusable, U5's canned transcripts pin the last-known-good
  SDK+CLI versions — report the delta, hold the minor pin, escalate
  (§4) rather than chase.
- **Streaming granularity degrades** (coarser than probe 1's ~5 Hz):
  per-block fallback is the specced degradation (09 §5); not a
  blocker.
- **Charter callback regression at build** (T-B fails): ladder per
  09 §4.3 — rung 2 `allowed_tools`/`disallowed_tools` path rules,
  rung 3 PreToolUse settings guard (organizer-guard pattern; settings
  JSON lives in the ui package, passed by absolute path), re-run T-B
  each rung; rung 4 = cli engine (§4 human confirm). Never widen the
  allowlist to "make it work".
- **Port in use**: `SELF_LEARN_UI_PORT` override + one-line log;
  recurring collision on the default → propose a new default to the
  human (a pin change, §4).
- **Token file lost/stale**: service restart re-mints; the launcher
  always reads the current token — "403 in an old tab" is solved by
  clicking the notification again (or `self-learn-ui-open`).
- **systemd absent / non-Linux host**: documented foreground
  `self-learn-ui serve`; the launcher skips `systemctl` when absent
  (§1). Notifications/WM focus degrade per 09 §5.
- **SSE buffering trouble**: uvicorn on localhost needs no proxy; the
  pinned implementation flushes per event. If a future proxy appears
  in front (Stage 2), that deployment owns `X-Accel-Buffering` — out
  of v1 scope.
- **watchfiles/inotify limits** (many buckets): the 10 s poll is the
  floor; log a one-line notice, continue.
- **Bulk loop interrupted by machine sleep/crash**:
  committed-but-unpushed records are 08 §5's existing playbook (loud
  sync warning + `self-learn push`); re-opening the bucket shows the
  still-pending remainder; re-running the bulk row is idempotent
  (already-resolved ids vanish from the group).
- **swaync absent / action unsupported / `--wait` hangs**:
  `self-learn-notify` sets `--expire-time` and exits on daemon close;
  worst case the detached helper lingers until notification timeout —
  bounded, invisible; the M2 plain-notify fallback stays intact.
- **Chromium-family browser absent**: launcher falls through to
  `xdg-open` (normal tab); the app is browser-agnostic; only the
  dedicated-window feel degrades.
- **Pane cost anomalies** (subscription reports $0/absent vs API
  reports real): render verbatim, never compute; recurring budget-cap
  errors at the default are a §4 default-change escalation, not a
  silent bump.

## 6. Acceptance & merge

1. §2 complete (T-A CI + four live trials logged + degradation walk).
2. Deploy sweep: `install.sh` rerun; `~/bin/self-learn-ui`,
   `~/bin/self-learn-ui-open`, `~/bin/self-learn-notify` symlinks
   live and non-dangling (repo CLAUDE.md rule); the service unit
   installed + enabled; fresh-shell launch works **through the
   symlink** (the P3-1 failure mode is exactly here).
3. Worktree → master merge per repo convention; autosync publishes.
4. 03's G-3 row gains a dated "shipped" note; README revision-log
   entry; project memory update.
5. Open questions harvested into the change-control appendix (§7),
   not left in chat history.

## 7. Change control

Same discipline as 08 §9: pins here change only with a dated edit +
co-owner pointer (08 for shared pins, 09 for design); new build-time
gaps get dated **Build findings** appendix entries (finding →
disposition) so the next agent inherits answers, not archaeology.
This plan is complete when §6 exits.
