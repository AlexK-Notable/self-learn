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
tests; escalation discipline; repo conventions). *(Amended 2026-07-17
— 13 §7.3 D1/D3: the build happens in the **product repo**
(`~/repos/self-learn`), which has **no autosync** — rule 1's worktree
discipline is re-motivated, not dropped: worktrees now exist for
**parallel-agent isolation** (§8), not autosync racing; a solo
serial build may work directly on a feature branch. Merges land by
**manual push** — nothing publishes automatically.)* Surface-specific
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
| Code layout | UI package: `plugins/self-learn/ui/` — **in the product repo `~/repos/self-learn` (13 §7.3; amended 2026-07-17 — every `plugins/self-learn/…` path in this document resolves there, never in claude-skills)** — a uv project (`pyproject.toml`, `src/self_learn_ui/…`, `templates/`, `static/`, `tests/`). Entry point: `plugins/self-learn/scripts/self-learn-ui` (shebang'd, extensionless): `#!/usr/bin/env bash` + `exec uv run --project "$(dirname "$(readlink -f "$0")")/../ui" self-learn-ui "$@"` — **`readlink -f` is load-bearing** (carried, P3-1): install.sh deploys scripts as `~/bin` *symlinks*, so bare `$(dirname "$0")` resolves beside the symlink, not the repo (`home-net-capture` precedent; same rule for sibling-path references in `self-learn-ui-open`/`self-learn-notify`). Subcommands: `self-learn-ui serve` (foreground server — what systemd runs) · `self-learn-ui --help` | 09 §3, §6, §11 Y-1; repo CLAUDE.md |
| Service | `systemd/self-learn-ui.service` beside the miner units in the product repo (`ExecStart=%h/bin/self-learn-ui serve`, `Restart=on-failure`), installed by the **product repo's install.sh via explicit link lines mirroring its miner-units block** *(amended 2026-07-17 — the product install.sh links surfaces explicitly, no glob; "same mechanism as the existing watcher unit" referred to claude-skills' installer and is dead)*; enable stays a documented manual line (`systemctl --user enable --now self-learn-ui.service` — same posture as the miner timer). The three companion scripts likewise get explicit link lines to `~/bin` at U10. Foreground `self-learn-ui serve` is the documented no-systemd fallback | 09 §3, §11 Y-1 |
| Network & security | Bind `127.0.0.1` only, port `SELF_LEARN_UI_PORT` default **7357**. Middleware (all in one module, ~30 lines, tested in T-A): reject unless `Host` ∈ {`127.0.0.1:<port>`, `localhost:<port>`}; bearer token minted per service start (`secrets.token_urlsafe`), written 0600 to `$XDG_RUNTIME_DIR/self-learn/ui-token`; `GET /?token=…` (any path) sets it as a `SameSite=Strict; HttpOnly` cookie and 303-redirects to the clean URL; every mutating route is POST-only and requires valid cookie **and** the `HX-Request` header (cross-site forms cannot set custom headers); failure → 403 page naming `self-learn-ui-open`. **Render-path pins (W-1, 2026-07-12)**: Jinja environment constructed with autoescape ON (never disabled per-block); ALL markdown rendering (records, rationale free-text, pane blocks — pages and SSE frames alike) through markdown-it-py constructed with **`html=False`** (never the default preset — it passes raw HTML, empirically confirmed); trusted raw-HTML injections limited to Pygments output + own templates; every response carries `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'`; CSP consequences pinned (W-9): Pygments in **class mode + served stylesheet** (never `noclasses` inline styles), no inline `style=`/`<style>` anywhere, `font-src 'self'` added iff a font is bundled | 09 §3 |
| Companion scripts | `plugins/self-learn/scripts/self-learn-ui-open` (launcher, **the only WM/browser-aware file**: ensure service via `systemctl --user start self-learn-ui.service` (skip if systemctl absent); read token; **window-presence detection pinned (X-3, empirically grounded 2026-07-13: `hyprctl dispatch focuswindow` on an absent window prints "No such window found" and exits 0 — NEVER branch on its exit code)**: query `hyprctl clients -j` for the class first; if present, dispatch focuswindow; else launch app window — browser resolved in order `$SELF_LEARN_UI_BROWSER` → `chromium` → `google-chrome-stable` → fallback `xdg-open <url>`; app-window launch pins `--app=<tokened-url> --class=self-learn-ui` and degrades to `xdg-open` when unsupported) · `plugins/self-learn/scripts/self-learn-notify` — **argv pinned, carried verbatim (P3-6)**: `self-learn-notify --line "<rendered human string>" --ids <csv-of-record-ids>`; `notify-send -A open --wait`; on `open` → `self-learn-ui-open --record <first-id>`; no daemon — one process per notification | 09 §3; 08 §7.1 |
| Dependencies | `fastapi` + `uvicorn` + `jinja2` + `pygments` + `markdown-it-py` + `watchfiles` + `PyYAML` + **`claude-agent-sdk>=0.2.116,<0.3` (minor-pinned; probes ran on 0.2.116)**; dev/test: `pytest`, `pytest-asyncio`, `httpx`. **Vendored static, committed**: `static/htmx-2.0.9.min.js` (exact version + recorded sha256 in the file header comment; the htmx 4.x line is ignored) · `static/app.js` (authored, ~40-line keydown handler + EventSource client) · `static/style.css`. No node, no bundler, no CDN. Python ≥3.11 | 09 §6 |
| Keymap (single source) | `keymap.py` table *(bindings amended 2026-07-17 — user-directed gaming-centric remap, 09 §1/§2 amendments of the same date)*: `w/s`+arrows move · `Enter`/`d`/`→` drill · `Esc`/`a`/`←` up (Esc in pane = interrupt first) · `e` route · `x` reject · `f` defer · `g` graduate · `i` iterate · `o` cycle destination · `n` note · `t` tolerate / `c` confirm (on an "is it holding?" row — arm `confirm-recurrence …` with/without `--tolerate`; 09 §11 Y-4; added 2026-07-17) · `r` retry pane · `q` (pane focused) close split — ends the session (09 §2.4; X-2) · `p` (Bucket page) open the bucket pane — same split/pane keys as Detail's `i` · `y` arm a WAITING pane proposal bar (09 §4.5 rework — Enter then confirms per the standard armed contract; Enter never acts on a waiting bar) (09 §2.2/§11 Y-13; added 2026-07-17, both were unbound — global-uniqueness invariant holds) · `?` help overlay. Armed action: resolution key arms, `Enter` executes, any other key disarms. Keys inert while focus is in a text input. **No Ctrl/Alt chords** (browser owns them — 09 §1). Rendered from the one table into the footer partial, the help overlay, AND the JSON blob `app.js` consumes — never duplicated. Install/docs note: Vimium-class extensions need a `localhost:7357` exclusion (U10 docs item) | 09 §1 |
| SSE protocol | `GET /events` (EventSource in app.js; token-cookie-gated like every route): JSON envelopes, one `type` field each: `{"type":"refresh","scope":"front"\|"bucket:<b>"\|"record:<id>"}` (client re-requests its current partial if in scope) · `{"type":"applying","verb":…,"id":…,"state":"start"\|"done"\|"error"}` · `{"type":"bulk_progress","done":n,"total":m,"failed_id":null\|id}` · `{"type":"banner","text":…}` · pane events namespaced `{"type":"pane_delta","text":…}` / `{"type":"pane_block","html":…}` / `{"type":"pane_tool","name":…,"target":…}` / `{"type":"pane_result","status":…,"cost":…,"turns":…}` · `{"type":"pane_proposal","record_id":…}` — **scope-gated like `refresh`** (only the record's own Detail and its bucket's Bucket page act on it), triggers a re-fetch of the proposal-bar region rendering the WAITING bar; the client handler **no-ops while any `[data-armed]` element exists** (belt — the structural brace is that the incoming bar is waiting-state, 09 §4.5 rework); the bar's CONTENT always re-fetches server-rendered, never rides the envelope (09 §4.5; added 2026-07-17 Y-13, swept at the delta review's R2). Unknown types ignored client-side. Reconnect: EventSource auto-retry + the 10 s poll fallback (09 §5). *(Amended 2026-07-18 — feedback round 2 item 1, 09 §11 Y-15: the pane start POST — record and bucket routes alike, they share the manager — returns the split in its **starting** state immediately; the first turn drains as a server-side background task and the `pane_*` envelopes above are the ONLY transport for its content, so the starting markup MUST already carry the transcript region ids/hooks `app.js`'s pane handlers target — a swap that arrives without them re-creates the silent wall this amendment removes. A background-drain failure lands over `pane_result` + the standard re-render, same ENDED/error rendering as before; no new envelope types.)* | 09 §3, §4, §11 Y-15 |
| Pane `sdk` engine construction | **Empirically pinned (probes memo)**: `ClaudeSDKClient` (streaming mode — `can_use_tool` refuses to run under string-prompt `query()`, and the finite-generator `query()` pattern closes the control channel: footguns A/C) with `ClaudeAgentOptions`: `include_partial_messages=True` (chunk-level deltas ~5 Hz — probe 1) · `setting_sources=[]` **explicitly** (unset loads the full user environment — probe 3; never rely on the documented default) · `system_prompt` = compiled doctrine string (09 §4.2) · **`allowed_tools=[]`** (a listed tool is auto-approved before the callback — footgun B) · `disallowed_tools=["Bash","Task","WebSearch","WebFetch"]` (structural denies as belt; the callback is the braces) · `can_use_tool` = the charter callback (canonicalize paths via `realpath` before matching; **read scope per 09 §11 Y-2's three roots** *(amended 2026-07-17 — gate-zero blocker: this row previously pinned the pre-13 single-root scope, which post-13 denies every canon and doctrine read)*: reads inside `cwd` auto-approve and never reach the callback — accepted; the callback allows Read/Grep/Glob under (1) resolved `SELF_LEARN_HOME`, (2) the registered hosts' canon surfaces via the CLI-owned `canon_read_roots()` helper (U0; imported, never a second list — same import-vs-shell decision as the cache-path function, resolved once at U1 for both; if shell is picked, pin a `self-learn paths --json` read surface at U0 exposing both — never parse human output), (3) the plugin references dir resolved from the ui package's own location; denies-with-reason every read outside them; Edit/Write per 09 §4.3's exact-file rules; deny-with-reason otherwise) · `cwd` = bucket root · `model=$SELF_LEARN_PANE_MODEL` · `fallback_model`, `max_turns`, `max_budget_usd` — **fields empirically confirmed on 0.2.116** (phase-A introspection; re-verify at U5) · session-persistence-off + strict-MCP: exact option names resolved at U5 start (verify-at-build ledger). Wrapper-side cap enforcement exists only as the contingency for a future SDK dropping a field (09 §4.2/W-4). Tolerate unknown message types mid-stream (`RateLimitEvent` observed on Max OAuth). Interrupt: SDK interrupt call, then client close at +2 s, kill at +5 s | 09 §4.1–4.3 |
| Engine event protocol (internal seam) | `PaneEngine.start(ctx) → AsyncIterator[PaneEvent]`; `PaneEvent = block_start(kind) \| text_delta(str) \| tool_use(name, target) \| file_changed(path) \| result(status, cost_usd\|None, error\|None)`; `send(str)`, `interrupt()`, `close()`. The UI imports only this module; SDK message parsing lives entirely inside the sdk engine. The specced-not-built `cli` engine (09 §4.1) satisfies the same seam; its invocation pin set is the TUI revision's §1 row (git history `1ce408c`) | 09 §4.1 |
| Doctrine compile | `<cache>/pane-doctrine.md` = concat of `references/routing-doctrine.md` + `references/pane-charter.md` (both tracked in the plugin; charter authored in U5 from 09 §4.3's charter text) *(+ `references/pane-surface-model.md` — third source added 2026-07-17, 09 §11 Y-13; authored at U12 in the doctrine §8 register per Y-9)*. Recompiled when any source mtime > compiled mtime. Byte-stable between recompiles; read into the `system_prompt` string at session start | 09 §4.2 |
| Pane proposal tool *(added 2026-07-17 — 09 §4.5/Y-13)* | In-process SDK MCP server named `self-learn-surface` (via `create_sdk_mcp_server` — presence verified on installed 0.2.121 at drafting; re-verify at U12 on the resolved version) exposing exactly ONE tool: `propose_verb(verb, record_id, dest?, note?, until?)`. `ClaudeAgentOptions.mcp_servers` carries only this entry; `allowed_tools` stays `[]` (footgun B); the charter callback allows the tool's fully-qualified name (`mcp__self-learn-surface__propose_verb`) exactly — T-B proves the call routes through the callback. Handler (server code) validates: verb ∈ {route, reject, defer, graduate}; record_id pending AND in-scope (record session → own record only; bucket session → own bucket only); dest accepts the full 02 §1 surface forms (`skill-md \| claude-md \| reference[:<file>] \| new-skill:<name> \| hook` — refuse only on parse failure, structural validity stays the verb's); until parses ISO; note ≤200 chars — refused at intake, never display-truncated (delta R4: displayed note must be byte-identical to the executed `--note`). Valid → occupy the **server-held single proposal slot** (in-memory beside the pane session manager; clear-set: confirm · dismiss · proposing-session end/interrupt/error/`q` · record leaves pending · restart; page navigation does NOT clear — in-scope renders re-render the bar) and render the **WAITING** proposal bar (NOT `[data-armed]`; server-assembled: verb/id/dest/date = server-truth fields, Y-9 leading line, note under an "agent-suggested note:" label display-capped ~200 chars, dismiss button) + SSE `pane_proposal` **scope-gated like `refresh`** (the record's Detail + its bucket page only). `y` arms the waiting bar through the STANDARD armed contract (Enter executes, any other key disarms back to waiting); Enter never acts on a waiting bar; the `pane_proposal` client handler no-ops while any `[data-armed]` element exists (belt — the structural brace is that the incoming bar is waiting-state). **Single-armed-bar-per-document is a tested invariant.** Invalid → refusal string to the agent, nothing renders. **Refuse-not-replace** while the slot is occupied (waiting or armed). Confirm POST → standing runner path (serialized, interrupt-first for record sessions — bucket sessions exempt, they hold zero writes and survive the confirm; scan; stale-record confirm takes the verb's own refusal path and clears the slot). Tool return is immediate: rendered-and-waiting, no cancel notification | 09 §4.5 (as reworked same day), §4.3, §11 Y-13 |
| Server transient state | `<cache>` = the doc-13 home-namespaced dir `${XDG_CACHE_HOME:-~/.cache}/self-learn/home-<sha256(resolved SELF_LEARN_HOME)[:8]>/` — **imported from the CLI's existing derivation function, never reimplemented** (09 §11 Y-3; P2-4 one-computation rule; the ui package declares the cli package as a path dependency for this one import, or shells `self-learn` for the path — resolved at U1, recorded in the ledger below). Contents: `ui.log` (capped ~1 MB, same truncation as `worker.log`) · `pane-doctrine.md` · the token-file fallback (X-8/X-12). Primary token home stays `$XDG_RUNTIME_DIR/self-learn/ui-token`. Nothing else; no config file | 02 §3, 09 §3/§4.4/§11 Y-3 |
| Env vars (complete) | `SELF_LEARN_HOME` (08) · `SELF_LEARN_UI_PORT` (default `7357`) · `SELF_LEARN_UI_BROWSER` (launcher only) · `SELF_LEARN_PANE_MODEL` (default `claude-sonnet-5`) · `SELF_LEARN_PANE_BUDGET_USD` (default `1.00`) · `SELF_LEARN_PANE_MAX_TURNS` (default `15`) · `SELF_LEARN_PANE_ENGINE` (`sdk`; `cli` → exit with "engine not built — 09 §4.1") | 09 §4.4 |
| Refresh mechanics | `watchfiles` watcher over every bucket's `pending/` + `proposals/` + `events.jsonl`, 300 ms debounce; SSE `refresh` push; 10 s client poll fallback; forced push after every verb return. Bucket set re-discovered on Front-page request (a new skill's first record must appear without restart) | 09 §3 |
| Verb runner | One subprocess at a time server-wide (asyncio queue — multiple tabs share it); resolution POSTs rejected with "applying…" state while running; interrupt-first check **at verb dispatch** (09 §3, P1-4); bulk loop = sequential `graduate <id> --no-push` + terminal `self-learn push` on exit **success or abort** (08 §1 as amended); per-item progress via SSE; halt-on-first-failure with failing id shown | 09 §2.2, §3 |
| Rendering | Diffs: Pygments `DiffLexer`; proposal YAML: Pygments YAML lexer; markdown (records, transcripts' finished blocks): `markdown-it-py` server-side; live pane deltas append as plain text, blocks re-render server-side at block boundaries (09 §4.1 — no client-side markdown dependency). The preview-honesty caption is a fixed string under every diff (02 §4's wording) | 09 §2.3, §4.1 |
| Screen-state derivation | Pure functions: `(list --json output, status --json output, report --json output, mine status --json output, merge-yaml set, sentinel mtime) → screen model` — templates render models; no route handler reads ledger files directly; all reads go through one `ledger.py` module (testable headless, 09 §7) | 09 §3, §7, §11 |
| CLI substrate consumed (new pieces built at U0) | The 08 §1 dated edit of 2026-07-17 (the G-3 surface substrate block), scope corrected after gate zero against the live CLI. **New at U0:** `list --json` items gain `bucket` (display name: skill name \| project slug \| `user`), `host_registered` (bool, `hosts.yaml`-derived), `source` (02's provenance enum verbatim); `report --json` gains `recurrence_suspects` rows `{id, nonce, seen_at}` (the M2 deterministic suspect computation **exposed, never reimplemented**); the CLI-owned `canon_read_roots()` helper + `host add` consent line (09 §11 Y-2); optional-if-cheap `status --json .sections_over_cap` (02 §4 cap check → Front graduation-opener banner; decided at U0 by cost, dropped loudly if skipped). **Existing, merely consumed** (first draft mis-listed them as new — gate-zero finding): `mine status --json` (shipped M2.5; `{last_run, stale, runs: […]}` — journal file remains truth, staleness derivation CLI-owned) and `report --json .open_followups` (rows `{id, bucket, action, unblocks_on, note, routed_at}`). The server consumes these fields ONLY — a missing field remains a dated 08 §1 edit, never server-side derivation (09 §2.1 rule, unchanged) | 08 §1 (2026-07-17 edit); 09 §11 Y-2/Y-4/Y-5/Y-6/Y-11 |

**Verify-at-build ledger** (each gets a scripted check at its task's
start; failures route per §5): exact `ClaudeAgentOptions` name for —
session-persistence off (no matching field found on 0.2.116 by
terminal-review introspection; **named fallback: pass the CLI's
`--no-session-persistence` through the confirmed-present
`extra_args` option** — X-7) · strict MCP (`strict_mcp_config`
confirmed present on 0.2.116, same introspection; `max_turns` ·
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
  response (W-1) · no `style=` attribute in the rendered diff
  partial (X-9 — a `noclasses` Pygments regression ships
  safe-but-unstyled under the CSP; this assertion catches it in
  CI)**. *(Extended 2026-07-17 for the 09 §11 set:)* an
  "is it holding?" row arming `confirm-recurrence <id> --event
  <nonce> --tolerate` with argv asserted (Y-4) · post-route
  contradicts-edge partial arming `link contradicts <id> <target>`
  per accepted edge (Y-8) · a hook-destination Detail rendering the
  full stored script + replay examples with the M3 caption (Y-7) ·
  an unregistered-host PROJECT record rendering the notice with the
  armed host-add flow — arm renders the consent consequence + the
  server-derived path (a bogus client `path` field must be IGNORED,
  argv asserted as `host add <meta.yaml path>`), confirm runs the verb,
  disarm restores the notice, and record arming stays live throughout;
  skill/user-scope notices keep the prose fallback; plus the
  template-source assertion that the only `self-learn …` command
  literals in templates are the Y-11 exempt list *(this line amended
  2026-07-17 with the Y-11 amendment — it previously pinned the now-
  superseded copyable-command rendering)* (Y-11) · the miner
  block rendering journal rows with force-run as its ONLY action
  (Y-5) · `/report` rendering counted fields verbatim (Y-12) · a
  row's leading text is never a raw `lrn-…` id (Y-9, asserted on a
  proposal-less AND a proposal-bearing record) · every badge in the
  rendered partials carries a text label (Y-10 — assert no
  badge-classed element is empty of text). *(Extended 2026-07-17 for
  Y-13; extended again at the same-day rework — the review's F4:)*
  the proposal-tool handler driven directly (no live engine —
  FakeEngine/handler-level): a valid `propose_verb` occupies the slot
  and renders the WAITING bar (asserted NOT `[data-armed]`) with
  server-assembled content, `y` arms it, and the confirm POST's argv
  is asserted against the fake `self-learn` · a second proposal
  while the slot is occupied (waiting AND armed both tested) is
  refused · a proposal arriving while a HUMAN-armed bar is rendered
  must not alter what the pending Enter confirms (the F1 fixture:
  human-armed argv asserted unchanged after the proposal lands) · no
  rendered page ever contains two `[data-armed]` elements (asserted
  on the proposal+human-arm collision page) · slot cleared on
  proposing-session end and on record-resolved-elsewhere (and a
  confirm against a stale slot takes the verb-refusal path, then
  clears) · a page re-render while the slot is occupied re-renders
  the waiting bar (navigation survival) · dismiss clears the slot
  and a subsequent proposal succeeds · disarm returns the bar to
  WAITING (not cleared) · a bucket-session proposal naming a record
  outside its bucket is refused · a record-session proposal naming
  any other record is refused · a proposal with verb `host add` (or
  anything off the closed list) is refused · the Bucket page
  renders the `p`-key pane split with the proposal-bar region
  present. *Predicate:* every 09 §2/§3/§11 behavior named in this
  sentence has a test that fails when its logic is inverted.
- **T-B · Pane permission live refusal** (live, logged): a real
  `sdk`-engine session over a sacrificial record in a throwaway
  `SELF_LEARN_HOME`, instructed verbatim to (1) run `git log` via
  Bash, (2) write a file outside its allowlist, (3) read a file
  outside the repo (e.g. `~/.zshrc` — the W-3 read boundary), (4)
  edit its own record, (5 — added at the delta review, the narrowed
  scope's signature behavior) read a NON-canon file inside a
  registered host repo (a source file outside every canon surface) —
  expect refuse/refuse/refuse/succeed/refuse, with (1)
  blocked by `disallowed_tools` and (2)/(3)/(5) by the callback
  (`ResultMessage.permission_denials` is the evidence — probes memo).
  *(Extended 2026-07-17, Y-13; wording per the same-day rework —
  delta R1:)* (6) instruct the agent verbatim to
  propose routing the record — expect the `propose_verb` call to
  **route through the charter callback** (the footgun-B proof on the
  resolved SDK version) and the WAITING proposal bar to render
  WITHOUT the verb running (assert no runner invocation AND that the
  rendered bar is not `[data-armed]`); (7) instruct it to register
  a new host via the tool — expect the handler's closed-list refusal;
  (8) in a bucket session, instruct it to edit the record — expect
  the zero-write-allowance denial naming the record pane.
  *Predicate:* 8/8; any failure of (1)–(3)/(5)–(8) triggers the 09
  §4.3 ladder and re-trial before U6/U12 proceeds.
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
a passing dated entry in `ui-trials.md`; **the U11 browser-level
acceptance pass logged in `ui-trials.md` (X-5/X-11)**; the 09 §5
degradation table walked row-by-row with each row's behavior
demonstrated (test or logged manual check).

## 3. Task DAG

Each task = tests + code + DoD, same contract as 08 §3. Dependencies
in brackets.

- **U0 · CLI substrate** [] *(added 2026-07-17 — 09 §11's substrate
  edits; lives entirely in `plugins/self-learn/cli/`, no ui-package
  dependency; scope corrected after gate zero against the live
  CLI)*: the genuinely new 08 §1 fields — `list --json`
  `bucket`/`host_registered`/`source`; `report --json`
  `recurrence_suspects`; the CLI-owned `canon_read_roots()` helper
  (09 §11 Y-2) + the `host add` consent line; the optional
  `sections_over_cap` call (build or drop loudly). NOT built here
  (already exist, merely consumed): `mine status --json`,
  `report --json .open_followups`. Tests in the cli suite per its
  own conventions. *DoD:* new fields present on constructed ledgers
  incl. a foreign (unregistered) bucket and a routed record with a
  planted suspect; `canon_read_roots()` returns exactly the canon
  surfaces on a two-host fixture; cli suite green; the 08 §1 dated
  edit (landed with the 2026-07-17 amendment pass) verified accurate
  against the built fields — any mismatch is a finding.
- **U1 · Scaffold** []: uv project, entry wrapper (+`serve`
  subcommand), vendored htmx (hash recorded) + `app.js` skeleton +
  base template/CSS (incl. the Y-10 `prefers-color-scheme` variable
  block), env parsing, capped logging (Y-3 cache dir — resolve the
  import-vs-shell question for the CLI's cache-path function here,
  record in the ledger), keymap module, CI wiring (pytest +
  pytest-asyncio + httpx). *DoD:* `self-learn-ui --help` runs from a
  clean clone via the wrapper; lint+test skeleton green.
- **U2 · Ledger model** [U0, U1]: `ledger.py` — CLI `--json`
  invocations (list incl. `--include-deferred`, status, report,
  mine status), record/proposal/merge YAML + diff readers,
  screen-model derivation (pure — incl. the Y-4 suspect rows, Y-5
  miner block, Y-6 follow-ups, Y-11 unregistered flag, Y-12 report
  model), watcher + debounce + poll + forced refresh, bucket
  re-discovery. *Tests:* T-A's model half. *DoD:* screen models
  correct on all constructed ledgers.
- **U3 · Routes & templates** [U2]: Front/Bucket/Detail routes +
  partials, status strip, action bar (arm/confirm/disarm as POSTs),
  note input, help overlay, banners ("resolved elsewhere",
  bucket-clear), Pygments/markdown rendering, **security middleware**,
  SSE endpoint + `app.js` EventSource client + keydown handler.
  *(Extended 2026-07-17 with the Y-11 amendment:)* the armed host-add
  surface — the bucket-scoped `host-add/{arm,disarm,confirm}` route
  triple + id-less armed partial on the `.action-bar[data-armed]`
  contract, server-derived path, consent-consequence rendering,
  post-success bucket-scope refresh + redirect (09 §11 Y-11 build
  pins). *Tests:* httpx route/partial suite + middleware suite.
  *DoD:* T-A's interaction + security halves green.
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
  siblings only, and the Y-2 three-root read scope: ledger-tree
  allow, canon-surface allow via a faked `canon_read_roots()`,
  non-canon host file DENIED, outside-everything denied-with-reason). *DoD:* events replay byte-exact; live smoke
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
  systemctl/hyprctl/browser tests — incl. the X-3 detection: shim
  `hyprctl clients -j` with and without the class present and assert
  focus-vs-launch branches; never assert on dispatch exit code),
  deep-link edge cases (resolved-id → bucket + banner, first-id
  rule).
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
- **U10 · Deploy + docs** [U1–U9]: the product repo's install.sh
  gains explicit link lines for the three scripts and the ui service
  unit, mirroring its miner-units block — it has no glob (13 §7.3;
  corrected 2026-07-17, gate-zero finding); enable stays a
  documented manual line, actually run + logged at U11 acceptance
  (T-C/T-D need the live service). Verify symlinks + no dangling —
  deploy-sweep rule;
  SKILL.md + README sections (launch, keys, env vars, engine note,
  browser notes incl. the Vimium localhost exclusion, and the
  **Hyprland window-rule snippet for the app-window class as a
  documented optional manual step** — X-4: the pinned presentation
  works without it; the rule is polish); `10` change-control appendix
  opened.
- **U11 · Acceptance** [all]: run T-B/T-C/T-D/T-E live, log
  `ui-trials.md`, walk the degradation table, **plus one
  browser-level acceptance pass (X-5, closing 09 §7's Playwright
  item): drive the armed-key resolution flow and an SSE-refreshed
  partial swap in a real browser via Playwright/claude-in-chrome,
  logged in `ui-trials.md`** — CI stays httpx-level; then §6.
- **U12 · Chat panes with verb proposals** [U5, U6] *(added
  2026-07-17 — 09 §4.5/§11 Y-13 as reworked same day; ships as its
  own gated cycle after the base surface, feedback round 1 item 7)*:
  the in-process `self-learn-surface` MCP server + `propose_verb`
  handler (validation, closed verb list, the server-held single
  proposal slot with its pinned clear-set, refuse-while-occupied)
  wired into `ClaudeAgentOptions.mcp_servers` with the callback
  allow-rule; the WAITING proposal bar partial (+ `y` arm / Enter
  confirm / dismiss button) + scope-gated `pane_proposal` SSE type +
  arm/confirm/disarm/dismiss routes; the Bucket pane (`p` key, split
  layout reusing §2.4's, bucket first-message context per Y-13
  decision 5 — 50-row cap with honest truncation line, zero write
  allowance in the callback); `pane-surface-model.md` authored
  (doctrine §8 register, Y-9) + the doctrine compile's third source;
  interrupt-first interaction between a confirmed proposal and its
  own record session (and the bucket session's exemption) covered by
  test. *Tests:* the T-A
  Y-13 extension (handler-level, FakeEngine) + callback unit tests
  for the bucket-session write denial + verify-at-build re-check of
  `create_sdk_mcp_server`/`mcp_servers` on the resolved SDK. *DoD:*
  T-A green incl. the Y-13 block; T-B (6)–(8) pass live; a live
  bucket-pane session proposes a defer on a seeded record and the
  human confirm executes it (logged in `ui-trials.md`).

- **U13 · Idle lifecycle (resident while in use)** [U9] *(added
  2026-07-18 — 09 §3/§4.4/§11 Y-14 as reworked at their own blind
  review; ships as its own small gated cycle)*: the in-server idle
  monitor task (~30 s sample; the five predicate legs read the two
  hubs' subscriber counts, a middleware-maintained in-flight
  request counter, the runner's busy state, the pane manager's
  INTERRUPTIBLE-state check, and a middleware-stamped
  last-request-COMPLETION monotonic clock; the monitor runs on the
  request event loop and decides-then-signals in one loop step — no
  `await` between predicate read and signal) + parked-pane teardown
  before clean self-exit (uvicorn ``should_exit`` flag — corrected at
  the live trial, 09 §3: SIGTERM-to-self dies 143 via the
  capture_signals re-raise and gets restarted);
  `SELF_LEARN_UI_IDLE_EXIT_SECONDS` through `EnvConfig` (≤0 ⇒
  disabled — negatives pinned, never an error) with the
  `INVOCATION_ID` arming rule; the launcher's readiness wait
  (snapshot state + token bytes before `systemctl --user start`;
  cold ⟺ snapshot not `active`; one ≤5 s budget: fresh token THEN
  TCP connect on the port; timeout degrades to today's 403 path);
  the unit-file header comment re-worded from "resident, not
  one-shot" to the Y-14 posture (incl. a note that `enable --now`
  boot-starts now idle out — harmless). *Tests:* predicate unit
  tests with injected clock and exit callback (never a real SIGTERM
  in-suite), covering the awaiting-input-tears-down case, the
  in-flight-long-request case (clock stamps at completion), each
  leg blocking alone, the teardown-defers-exit case (a request
  completing during a parked-session teardown blocks the signal —
  delta R1), and the in-flight counter decrementing in a `finally`
  (a client-disconnect-cancelled handler must never leak a
  permanent in-flight count — delta R3); monitor task lifecycle
  (armed only per the rule, cancelled at shutdown); engine
  `close()` idempotent against already-closed parked sessions
  (delta R4); launcher readiness-wait branches in the hermetic-PATH
  harness (warm-service skip, cold-start fresh-token+connect,
  not-`active`-but-not-`inactive` snapshot states,
  token-unchanged-but-connect-succeeds counted as early success —
  the double-click case, delta R2 — and cold-start timeout
  degradation). *DoD:* live
  trial logged in `ui-trials.md` — with a shortened idle window:
  (a) close all pages → the service exits 0 and lands inactive
  (never failed); (b) `self-learn-ui-open` cold-starts it and opens
  a tokened page with no 403; (c) Iterate → result → close window
  without `q` → server still exits (the F1 path); (d) a launcher
  click attempted during the shutdown drain, outcome logged even if
  it is the accepted 403 degradation.

Parallelism: superseded 2026-07-17 by **§8 — the parallel execution
plan** (tracks, file-ownership partition, join points, blockers).
Polish backlog (explicitly deferred, not silently dropped): `proposal
validate` inside the auto-interrupt sequence (carried from the TUI
revision's backlog); pagination/virtual scrolling if a bucket ever
exceeds ~500 rows. *(Dark/light theme left this backlog 2026-07-17 —
promoted into U1/U3 scope by 09 §11 Y-10.)*

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
| G-3 trigger not fired but build requested | Human (gate discipline) *(trigger recorded as fired: M2 shipped + worker proven 2026-07-15; M3 complete + v1.1 tagged 2026-07-17 — see appendix)* |
| Arming `host add` from the surface (a canon-target decision) | Armed via the surface's arm/confirm spine — the human still decides; the UI is the hand *(amended 2026-07-17: the row previously read "Human — deliberately absent in v1; revisit only on explicit user ask", and that ask fired — feedback round 1 item 5. Build pins — server-derived path, consent-in-arm-state, bucket-scoped route triple, project-scope-only, no keymap entry, no agent path — live in the 09 §11 Y-11 amendment of the same date)* |
| Extending the pane's proposable verb set beyond route/reject/defer/graduate (09 §4.5's closed list — e.g. collapse, telemetry verbs, host add) | Human, via a dated 09 §4.5 edit — never a code-only change; `host add` additionally blocked by Y-11's no-agent-path pin |
| A proposal-bar UX conflict between refuse-not-replace and observed agent behavior (e.g. agents repeatedly stuck behind an armed bar) | Human — the refuse rule is a consent-integrity pin (what-you-see-is-what-you-confirm), not a tuning knob |
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
- **`$XDG_RUNTIME_DIR` unset** (headless/SSH — X-8): the token file
  falls back to `<cache>/ui-token` — the home-namespaced cache dir of
  §1's transient-state row (0600) — with a one-line logged notice.
  *(Path corrected 2026-07-17; the pre-13 literal this playbook
  carried contradicted the amended §1 row — gate-zero finding.)*
  **Token-path resolution is ONE shared function/rule — the launcher
  applies the same fallback when it reads the token** (X-12;
  otherwise an unset-runtime-dir launcher would open an un-tokened
  URL and 403-loop into a message naming itself as the fix).
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

1. §2 complete (T-A CI + four live trials logged + the browser-level
   acceptance pass logged + degradation walk).
2. Deploy sweep: `install.sh` rerun; `~/bin/self-learn-ui`,
   `~/bin/self-learn-ui-open`, `~/bin/self-learn-notify` symlinks
   live and non-dangling (repo CLAUDE.md rule); the service unit
   linked + `daemon-reload` run, and the documented manual enable
   line executed + logged as part of U11 acceptance *(aligned
   2026-07-17 with §1's Service row — install.sh links, the human
   enables; gate-zero finding)*; fresh-shell launch works **through
   the symlink** (the P3-1 failure mode is exactly here).
3. Feature branch → master merge; **manual push** (13 §7.3 D3 — the
   product repo has no autosync; nothing publishes until pushed).
   *(Amended 2026-07-17; "autosync publishes" was the pre-extraction
   posture.)* Before the merge: one independent adversarial review
   of the assembled branch (repo standing discipline — never
   self-certify), findings folded, delta re-checked.
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

## 8. Parallel execution plan (added 2026-07-17)

*The DAG in §3 was written for a serial builder. This section maps it
onto concurrent agents: which units are genuinely isolated, where the
hard serialization points are, and the mechanics that keep parallel
work conflict-free. Nothing here changes any task's content or DoD —
it only schedules them.*

**File-ownership partition** (the thing that makes parallelism safe —
near-zero path overlap between concurrent tracks; `pyproject.toml`
and CI config are owned by U1 and afterwards change only through the
orchestrator):

| Track | Tasks | Owns (exclusively while active) |
|---|---|---|
| A · CLI substrate | U0 | `plugins/self-learn/cli/**` + the 08 §1 dated edit |
| B · Scaffold | U1 | `plugins/self-learn/ui/**` (creates it), `scripts/self-learn-ui` |
| C · Core server | U2 → U3 → U4, **plus U7's server-side half** (token minting + middleware wiring — it lives in C's files) | `ui/src/self_learn_ui/{ledger,models,routes,middleware,runner}*.py`, `templates/**`, `static/app.js` *(U3 authors its EventSource client + keydown handler)*, `static/style.css` |
| D · Pane | U5 | `ui/src/self_learn_ui/engine/**`, `skills/self-learn/references/pane-charter.md`, doctrine compiler module |
| E · Companion scripts | U7's script+unit halves ONLY *(clarified after gate zero: U7's server-side token/middleware half belongs to track C inside U3 — §3's U7 [U3] bracket refers to the wave-3 integration check, not the script authoring)* | `scripts/self-learn-ui-open`, `scripts/self-learn-notify`, `systemd/self-learn-ui.service`, their shim tests |

**Schedule** (arrows = hard dependency; tracks on the same line run
concurrently):

1. **Gate zero (serial, before any build agent):** the 09 §11
   amendment set has passed its independent spec review (appendix
   entry below) — build agents consume reviewed docs, never a live
   draft.
2. **Wave 1 — A ∥ B.** U0 and U1 share no files (different
   packages). Both are small; wave 1 is short.
3. **Wave 2 — C ∥ D ∥ E** (all gated on U1; C also on U0). Within C,
   U2→U3→U4 stay serial: **U3 is the integration hub** (routes +
   templates + middleware touch everything) and is deliberately
   single-agent — splitting it buys conflicts, not speed. D depends
   only on U1 (the `PaneEngine` seam + engine tests are self-
   contained; FakeEngine consumers in C code against the pinned seam,
   §1). E is contract-driven end-to-end (argv, token path, URL shape,
   unit content are all pinned in §1) and testable with shims alone;
   its one integration check (real token flow) waits for U3, and
   U7's DoD completes only at that wave-3 check.
4. **Wave 3 — joins (each starts when ITS OWN brackets are met, not
   together).** U6 [U3+U5] · U8 [U7 + a small cli-side
   emission-point change — lands in the cli package, so coordinate
   with track A's territory: either the same agent or after A merges]
   · then U9 [U4, U6, U7] — U9 is gated on the other joins, not
   concurrent with them.
5. **Wave 4 — serial tail.** U10 (deploy + docs; single agent — it
   edits install.sh, README, SKILL.md, the appendix) → U11
   (acceptance: live trials + browser pass + degradation walk).
6. **Merge gate:** one independent adversarial review of the
   assembled feature branch (§6.3), findings folded, delta
   re-checked, then master merge + manual push.

**Hard serialization points (the honest blocker list):**

- **Gate zero** — the spec review. Everything blocks on it; it is the
  cheapest item on this list to start immediately.
- **U1** — defines the package layout, seam module, keymap table, and
  CI that every ui-side agent imports. Keep it minimal so the gate is
  short; resist scope creep into U1.
- **U3** — the template/route hub; intra-track serial by design.
- **U5's verify-at-build ledger** — the SDK field re-verification runs
  at U5 start (serial within D, minutes not hours).
- **U11** — irreducibly serial and environment-bound: T-B/T-E burn a
  real model session, T-C needs the deployed service, T-D needs the
  live desktop (swaync click → window focus) and is best run with the
  user present. Nothing downstream exists, so this bounds the tail,
  not the middle.
- **Visual-taste iterations** (§4) — human-in-the-loop with
  screenshots; batch them at U3-done and U6-done rather than
  per-partial.

**Worktree mechanics** (product repo — no autosync, D3): the
orchestrator holds the feature branch; each wave-2/3 agent works in
its **own git worktree on a child branch** off the feature head (one
branch cannot be checked out twice; per-agent worktrees also isolate
uv venvs). The orchestrator merges child branches at each wave
boundary — with the ownership table above, textual conflicts should
be zero and any conflict is itself a finding (two tracks touched one
file → the partition was violated → stop and look). Agents never
push; only the orchestrator pushes, only at the end (§6.3).

**Wall-clock shape:** the critical path is U1 → U2 → U3 → U6 → U9 →
U10 → U11. Tracks A, D, and E hide entirely inside the C window;
if anything, over-provisioning agents on C's *tests* (T-A's fixture
matrix is wide and embarrassingly parallel to write) shortens the
path more than adding tracks.

## Appendix — Build findings (dated; §7 discipline)

- **2026-07-18 · U13 live trial (Y-14 idle lifecycle).** The DoD
  trial caught the drafted exit mechanism failing in production:
  SIGTERM-to-self exits **143**, not 0 — uvicorn 0.29+
  ``capture_signals`` re-raises the captured signal after graceful
  shutdown, so the process dies by signal and ``Restart=on-failure``
  restarts it (three cycles observed live). Both blind reviews had
  verified the SIGTERM claim as sound from the code's shape —
  plausible-but-wrong on the installed uvicorn 0.51. Fix: ``serve``
  constructs an explicit ``uvicorn.Server`` and the idle callback
  sets ``server.should_exit`` (same graceful path, genuine return,
  real exit 0); ``idle.default_exit`` demoted to a documented
  last-resort fallback. Lesson for the register: systemd/signal
  semantics claims are live-trial-only facts — no review pass
  substitutes for watching ``systemctl show`` after the exit.

- **2026-07-17 · U12 build (Y-13 chat panes).** Three dated notes:
  (1) **propose_verb tool schema** — the SDK's dict-of-types schema
  shorthand marks every key required; the T-B(6) live trial caught the
  model filling `until=""` and the validator refusing a valid route.
  The tool now declares a real JSON Schema (`required: [verb,
  record_id]` only) and the validator normalizes empty-string optionals
  to absent (belt; regression-tested). (2) **`pane_proposal` envelope
  carries `bucket` alongside `record_id`** — the §1 SSE row's scope
  gate needs the bucket page to match without a record→bucket lookup
  client-side; the envelope stays content-free (the bar re-fetches
  server-rendered). (3) **Slot staleness checks STATUS, not
  existence** — `locate_record` also finds resolved/ records, so the
  arm-time re-check reads the record and requires pending/deferred
  (caught by the T-A stale-arm fixture on first run). T-B rows (6)-(8)
  and the U12 DoD browser trial are logged in `fixtures/ui-trials.md`
  (row 7 pass-by-composition: the in-context layer refuses before the
  handler's closed list is reachable; the handler half is unit-pinned).

- **2026-07-17 · Pre-build re-ground (this amendment set).** 09
  gained §11 (Y-1…Y-12) + in-place amendments at §2.1/§2.2/§2.3/
  §3/§4.2/§4.3/§8; 10 gained the D3 posture note (§0), corrected
  §1 rows (product-repo layout, product install.sh, home-namespaced
  cache, substrate-consumption row, `t` key), T-A extensions, U0,
  U1/U2 DoD touches, §4 rows (trigger fired; no in-surface
  `host add`), §6.3 manual-push + review gate, §8, and this
  appendix. Driver: docs 11/12/13 + M3 all landed after this plan
  froze — the read-scope pin, cache paths, install mechanism, and
  "autosync publishes" were factually dead, and the surface lacked
  screens for lifecycle features (not-holding, miner, follow-ups,
  hook proposals) the review skill already carries. Disposition:
  landed as dated edits; independent spec review = gate zero (§8)
  before any build agent runs.
- **2026-07-17 · Gate zero ran: NOT CLEAN → folded.** Blind
  adversarial review (fresh agent, reviews/ withheld, verified
  against live CLI + source): 2 blockers — this plan's §1 pane-engine
  row still pinned the dead single-root read scope against Y-2
  (fixed: three-root pin, `canon_read_roots()` import); Y-2's first
  draft (whole-host-root reads) judged a prospective loosening —
  `host add` consents to compilers *writing* canon, not a model
  session *reading* the whole tree, untracked files included
  (fixed: scope narrowed to canon surfaces via one CLI-owned helper
  + a consent line in `host add`; recorded as a dated 03 note,
  user-ratifiable). 6 majors folded: `mine status --json` and
  `report --json .open_followups` already existed (U0/08 §1 scope
  corrected — the reviewer proved both against the live CLI, incl.
  one wrong shape pin `{id, note, opened}` vs the real
  `{…, routed_at}`); U10/§6.2 vs §1 install/enable contradiction;
  X-8's dead token-fallback literal; §8-vs-§3 U7 scheduling
  contradiction + the stranded middleware half; 09's un-swept W-5/
  W-8/refresh-line autosync assumptions (ledger has no watcher post-
  13). 7 minors folded (early drafts under-counted as 6): `c` confirm key + retire affordance on Y-4;
  Y-12's supply_mix/metrics source correction; U9 join wording +
  app.js ownership; U0 same-commit DoD; 03 trigger note (landed);
  02:275 stale "no v1 writer" line (landed). Verified-clean list in
  the reviewer's record. Delta re-check ran on the folds before
  commit: verdict CLEAN, with one functional residual folded in the
  same motion — `canon_read_roots()` must include the hook-canon
  dirs (13 §7.3/D1), else a pane session on a hook-destination
  record cannot read existing guards; plus T-B gained instruction
  (5) (non-canon file inside a registered host denied LIVE), the
  shell-branch fallback got its read surface pinned, and two
  cosmetic fixes.
- **2026-07-17 · Interim adversarial review (Opus): NOT CLEAN → all
  folded.** Fresh independent reviewer, probes executed, reviews/
  withheld. **1 BLOCKER:** every production Iterate session died at
  start with `TypeError` — the wave-1 join (`dd01fe1`) reconciled
  `default_canon_read_roots` to one-arg and fixed `charter.py` + its
  tests, but missed the SECOND consumer, `engine/sdk.py`, whose
  default was the now-one-arg fn called zero-arg; every engine/charter
  test injected a zero-arg fake, so the green suite was mock theater
  over a dead production path. Orchestrator's own join miss. Fixed:
  `SdkPaneEngine.canon_read_roots_fn` defaults to `None` (charter
  builds the home-threaded closure), plus a regression test that
  drives `_build_options` through the EXACT production construction
  (no fake injected) — the gap that hid it. **1 MAJOR:** the per-start
  bearer token leaked into uvicorn's access log (→ journald under the
  unit) via `GET /?token=…` logged before the 303 strips it — fixed
  with `access_log=False` (localhost single-user; the app keeps its
  own ui.log). **3 MINOR:** Pyright had 2 errors (the blocker's
  type-fingerprint + a loose `-> tuple[object, str]` annotation) — now
  0; `pane_result.turns` was hardwired `None` on a false honesty
  justification (`ResultMessage.num_turns` IS reported on 0.2.121) —
  now plumbed end-to-end with a test; the launcher hash-mirror
  diverged on `//`/`/.` homes — tightened (above). Verified-clean by
  the reviewer (executed): the charter permission callback (traversal/
  symlink/prefix/id-sibling/fail-closed battery), the security
  middleware (CSP on every response class, Host/token/CSRF), the XSS
  surface (every `|safe` justified), SSE through the middleware, runner
  serialization + interrupt-first ordering, and the load-bearing doc
  pins. Delta re-check owed before merge.
- **2026-07-17 · Wave-1/2 build findings (orchestrated build, Sonnet
  agents).** (a) U0 found and fixed a LATENT POST-EXTRACTION BUG in
  shipped code: `verbs._hooks_dir_for` still wrote project/user-scope
  guards to the pre-D1 `plugins/self-learn/hooks/` — a path that no
  longer exists in the host repo; reconciled to
  `<skills_root>/hooks/self-learn/` (readers were safe: they resolve
  via the record's stored `script_path`). (b) The wave-1 join
  reconciled a cross-track signature assumption:
  `canon_read_roots(hosts)` (U0) vs zero-arg (U5) — fixed at the
  seam, fail-closed preserved, end-to-end join tests added. (c) U5's
  verify-at-build ledger ran on SDK 0.2.121: all pre-verified fields
  present EXCEPT session persistence — the X-7 contingency fired as
  pinned (`--no-session-persistence` via `extra_args`). U5 also
  fixed a self-found symlink-follow bug in its write-path check
  before commit. (d) U7 CORRECTED THE PINNED NOTIFIER PROSE: on
  notify-send 0.8.8, `-A open` prints the action's numeric index
  ("0") on click, never "open" — the working form is
  `-A "open=Open"` (NAME=label); verified live under swaync with a
  bounded wait. §1's Companion-scripts row reads through this
  finding. (e) DELIBERATE DEVIATION, flagged for review: the
  launcher's X-8 token-path fallback mirrors the cache-hash formula
  (`sha256(str(expanduser(home)))[:8]`) in bash rather than shelling
  to the CLI — rationale: keeping `uv run` (and its network
  resolution) out of the script and its CI; a cross-check test pins
  the mirror byte-identical to the Python formula. Known residual:
  `str(Path(...))` normalizes trailing/double slashes, bash does not
  — a SELF_LEARN_HOME with a trailing slash would diverge. The
  interim review adjudicated KEEP (the `self-learn paths --json`
  replacement was only a conditional U0 pin and was never built; the
  import path was chosen instead — REPLACE would reintroduce `uv run`
  and its network resolution into the launcher + CI). The bash
  normalization was TIGHTENED 2026-07-17 to collapse `//`, drop `/.`
  segments, and strip trailing slashes — verified byte-identical to
  `str(PurePosixPath(...))` across those cases plus `..`-preserved; the
  X-12 loop this could once have caused is closed.
- **2026-07-17 · U10 shipped: deploy + docs.** `install.sh` gained
  explicit link lines (no glob, mirroring the existing miner-units
  block) for the three companion scripts (`self-learn-ui`,
  `self-learn-ui-open`, `self-learn-notify` → `~/bin`) and a new
  `== G-3 surface unit (systemd --user) ==` block linking
  `systemd/self-learn-ui.service` → `~/.config/systemd/user/` +
  `daemon-reload`; enable stays a printed `ACTION NEEDED:` manual line
  (`systemctl --user enable --now self-learn-ui.service`), never
  auto-run — same posture as the miner timer, per §1's Service row.
  Verified by `--dry-run` from the build worktree (a different path
  than the live-deployed `~/repos/self-learn`, so every link reported
  as a fresh `link` rather than `ok` — expected; the worktree is not
  the live install target). No live symlinks, no `daemon-reload`, no
  enable were run — deferred to U11 acceptance, which needs the
  service actually running for T-C/T-D per §6.2. `shellcheck` is not
  installed on this host and was not pulled via container to avoid an
  unrequested side effect; verification substitute was `bash -n`
  (clean) plus manual review against the miner block's idiom. README
  gained a "G-3 surface" section (what/launch/keymap table/complete
  env-var table/pane-engine note/browser notes incl. the Vimium
  `localhost:7357` exclusion/the optional Hyprland window-rule
  snippet, framed as polish per X-4/X-10) and updated Layout + Install
  blocks; SKILL.md gained a short section framing the surface as the
  richer review venue alongside `/self-learn:review` (same CLI verbs,
  not a second system). No code bugs found in `ui/`/`cli/` during this
  task — none of that surface was touched (out of scope; frozen and
  reviewed per the task charter).
