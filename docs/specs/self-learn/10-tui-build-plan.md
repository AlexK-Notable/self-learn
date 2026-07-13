# 10 — TUI build plan: durable, orchestrator-agnostic execution of G-3

*Written 2026-07-12 as phase 3 of the G-3 planning directive. Purpose:
identical to 08's — any competent orchestrator or implementation
sub-agent can build the TUI from this document plus the corpus, with
judgment calls that genuinely need a strong reasoner or the human routed
explicitly (§4), never silently absorbed.*

**Authority.** `09-tui-spec.md` is design authority for everything here;
on any conflict, **09 wins and the conflict is a finding** — stop,
record it, surface it; never improvise a reconciliation mid-build.
`08-build-plan.md` remains execution authority for M1–M3 and owner of
every shared pin (resolution verbs, `--json` shapes, `events.jsonl`,
sentinel, doctrine file, `proposal validate`); this plan **consumes**
those pins and never restates them normatively — where a §1 row below
touches one, the row cites 08 and adds only what is TUI-local.
**Execution is gated on G-3's trigger** (03: M2 shipped and the worker
proven). Running this plan before the trigger fires is itself a §4
escalation — ask the human, do not start.

---

## 0. Operating rules (read before any task)

Rules 1–6 of 08 §0 apply verbatim (worktree; autosync hazard on master;
test-first honestly; tests never touch the real ledger or `~/.claude` —
`SELF_LEARN_HOME` always points at a throwaway repo in tests; escalation
discipline; repo conventions). TUI-specific additions:

7. **Tests never talk to the network or a real model.** The pane engine
   is tested against a PATH-shimmed fake `claude` (same technique as
   08 T13's fake) that replays canned stream-json transcripts; the ONLY
   live-model executions in this plan are the §2 live trials, run
   deliberately and logged.
8. **Tests never touch the user's desktop or real cache.**
   `notify-send`, `hyprctl`, and `ghostty` are PATH-shimmed in tests;
   `$XDG_RUNTIME_DIR` **and `$XDG_CACHE_HOME`** are redirected to
   tmpdirs — the TUI resolves its cache home via `XDG_CACHE_HOME`
   (default `~/.cache`, so the pinned literal paths hold in production;
   P3-10b). Live desktop behavior is §2 acceptance, not CI.
9. **The Textual major version is pinned** (§1) and never bumped
   mid-build. A forced bump (security) is a §4 escalation.

## 1. Pinned interface contracts (TUI-local; shared pins live in 08 §1)

| Contract | Pin | Cites |
|---|---|---|
| Code layout | TUI package: `plugins/self-learn/tui/` — a uv project (`pyproject.toml`, `src/self_learn_tui/…`, `tests/`). Entry point: `plugins/self-learn/scripts/self-learn-tui` (shebang'd, extensionless): `#!/usr/bin/env bash` + `exec uv run --project "$(dirname "$(readlink -f "$0")")/../tui" self-learn-tui "$@"` — **`readlink -f` is load-bearing** (P3-1, 2026-07-12): install.sh deploys these scripts as `~/bin` *symlinks*, so a bare `$(dirname "$0")` resolves beside the symlink, not the repo (the in-repo precedent is `home-net-capture`'s `readlink -f` pattern; same rule for any sibling-path reference in `self-learn-tui-open`/`self-learn-notify`). A PEP 723 single file cannot hold a multi-module app; the wrapper keeps the ~/bin convention while uv owns the env. install.sh's existing scripts glob symlinks it to `~/bin` | 09 §6; repo CLAUDE.md |
| Companion scripts | `plugins/self-learn/scripts/self-learn-tui-open` (launcher: socket-forward + `hyprctl dispatch focuswindow class:self-learn-tui`, else `ghostty --class=self-learn-tui -e self-learn-tui …`; **the only WM/terminal-aware file** — degrades to plain `self-learn-tui` exec when `hyprctl`/`ghostty` absent) · `plugins/self-learn/scripts/self-learn-notify` (detached action-capable notifier per 08 §7.1's G-3 pointer: `notify-send -A open --wait`, on `open` → `self-learn-tui-open --record <first-id>`; no daemon — one process per notification, exits on dismiss/timeout/click). **Argv pinned (P3-6):** `self-learn-notify --line "<rendered human string>" --ids <csv-of-record-ids>` — the worker passes the same template output and ids it already logs to events.jsonl; T-D's fixture uses this exact surface, so the fixture and the U8 worker swap cannot diverge | 09 §3 |
| Dependencies | `textual[syntax]>=8,<9` (major pinned — trade study churn risk; the `[syntax]` extra is required by the Diff-rendering row's tree-sitter YAML highlighting — P3-4) · `watchfiles` · `PyYAML` · stdlib elsewhere. **No claude-agent-sdk in v1** (sdk engine is specced-not-built, 09 §4.1). Python ≥3.11 | 09 §6, §4.1 |
| Keymap (single source) | `j/k`+arrows move · `Enter/l` drill · `Esc/h` up (Esc in pane = interrupt first) · `a` route · `d` reject · `f` defer · `g` graduate · `i` iterate · `o` cycle destination · `n` note · `r` retry pane · `?` help overlay · `q` quit (in pane: close split). Armed action: any resolution key arms, `Enter` executes, any other key disarms. Defined once in code (`keymap.py`), rendered into footer + help from that table — never duplicated | 09 §1 |
| Socket protocol | `$XDG_RUNTIME_DIR/self-learn/tui.sock`; one JSON line per connection: `{"navigate": "<record-id>"}` — or `{"navigate": null}` for a bare second invocation (= focus/no-op navigation; P3-5) — → response line `{"ok": true}`; anything unparseable → `{"ok": false}` and ignore. Bind: if connect succeeds on an existing socket, forward + exit 0; if connect fails, unlink + bind (stale takeover). Socket mode 0600. Invocation surface: `self-learn-tui [--record <id>] [--no-socket]` (`--no-socket` = run detached, never bind nor forward — the §5 socket playbook's escape hatch, now part of the pinned surface) | 09 §3 |
| Pane `cli` engine invocation | Literal set, **verified against the live CLI at U5 start** (properties are the pin, exact syntax may track the CLI): `claude -p --input-format stream-json --output-format stream-json --include-partial-messages --verbose --system-prompt-file <cache>/pane-doctrine.md --setting-sources <empty/none — exact syntax verified at U5> --strict-mcp-config --no-session-persistence --model $SELF_LEARN_PANE_MODEL --fallback-model claude-haiku-4-5 --max-budget-usd $SELF_LEARN_PANE_BUDGET_USD --max-turns $SELF_LEARN_PANE_MAX_TURNS --disallowedTools "Bash,Task,WebSearch,WebFetch" --allowedTools "Read,Grep,Glob,Edit(<abs pending/lrn-ID.md>),Write(<abs proposals/lrn-ID.yaml>),Edit(<abs proposals/lrn-ID.yaml>),Write(<abs proposals/lrn-ID.diff>),Edit(<abs proposals/lrn-ID.diff>)"` with cwd = the bucket root. Interrupt = stream-json interrupt control message, then SIGTERM at +2 s, SIGKILL at +5 s. First user message = per-item context (09 §4.2's excerpt rule = 08 §7's worker rule) | 09 §4.2–4.3 |
| Engine event protocol (internal seam) | `PaneEngine.start(ctx) → AsyncIterator[PaneEvent]`; `PaneEvent = block_start(kind) \| text_delta(str) \| tool_use(name, target) \| file_changed(path) \| result(status, cost_usd\|None, error\|None)`; `send(str)`, `interrupt()`, `close()`. The TUI imports only this module; stream-json parsing lives entirely inside the cli engine | 09 §4.1 |
| Doctrine compile | `<cache>/pane-doctrine.md` = concat of `references/routing-doctrine.md` + `references/pane-charter.md` (both tracked in the plugin; charter authored in U5 from 09 §4.3's charter text). Recompiled when either source mtime > compiled mtime. Byte-stable between recompiles | 09 §4.2 |
| TUI transient state | `~/.cache/claude-skills/self-learn/tui.log` (capped ~1 MB, same truncation as `worker.log`) · `<cache>/pane-doctrine.md` · the socket. Nothing else; no config file | 02 §3, 09 §4.4 |
| Env vars (complete) | `SELF_LEARN_HOME` (08) · `SELF_LEARN_PANE_MODEL` (default `claude-sonnet-5`) · `SELF_LEARN_PANE_BUDGET_USD` (default `1.00`) · `SELF_LEARN_PANE_MAX_TURNS` (default `15`) · `SELF_LEARN_PANE_ENGINE` (`cli`; `sdk` → exit with "engine not built — 09 §4.1") | 09 §4.4 |
| Refresh mechanics | `watchfiles` watcher over every bucket's `pending/` + `proposals/` + `events.jsonl`, 300 ms debounce; 10 s fallback poll; forced refresh after every verb return. Bucket set re-discovered on Front-page entry (a new skill's first record must appear without restart) | 09 §3 |
| Verb runner | One subprocess at a time (asyncio queue); resolution keys disabled + "applying…" while running; interrupt-first check **at verb dispatch** (09 §3); bulk loop = sequential `graduate <id> --no-push` + terminal `self-learn push` on exit success or abort (08 §1 as amended); per-item progress; halt-on-first-failure with failing id shown | 09 §2.2, §3 |
| Diff rendering | Rich `Syntax` with Pygments `DiffLexer` for `.diff` siblings; YAML via tree-sitter `[syntax]` extra; the preview-honesty caption is a fixed string under every diff (02 §4's wording) | 09 §2.3 |
| Screen-state derivation | Pure functions: `(list --json output, status --json output, merge-yaml set, sentinel mtime) → screen model` — no widget reads a file directly; all reads go through one `ledger.py` module (testable headless, 09 §7) | 09 §3, §7 |

Verify-at-build ledger (each gets a scripted check at its task's start;
failures route per §5): `--setting-sources` empty-value syntax · exact
`--max-turns` flag name *(pre-verified 2026-07-12 on 2.1.207: accepted
though absent from `--help` — P3-3 review probe; re-verify at build)* ·
stream-json event schema against the live CLI version (record
`claude --version` in the U5 test log) · exact-path `allowedTools`
rules honored (the §2 live refusal trial is the arbiter; fallback
ladder 09 §4.3) · `--include-partial-messages` event shape · **the
input-side interrupt control-message shape** (P3-3; fallback = the
SIGTERM/SIGKILL ladder, already pinned).

## 2. Acceptance fixtures & live trials (defined FIRST, built last)

Trials log: `docs/specs/self-learn/fixtures/tui-trials.md` (same
discipline as 08 §2's `trials.md` — every live trial gets a dated entry:
command, environment, outcome, pass/fail against its predicate).

- **T-A · Headless screen-model suite** (CI): constructed throwaway
  ledgers (empty; mixed buckets; deferred records; stale/fresh/missing
  proposals; merge clusters; homogeneous already-canon group) → assert
  the derived Front/Bucket/Detail models field-by-field, and Pilot-drive
  the full key flow (arm→disarm→confirm, note entry, `o` cycling +
  parameterized-destination skip, bulk-collapse arming `graduate`,
  **cluster expand → survivor select/override → arm `route <survivor>
  --collapse <cluster-id>` with argv asserted against the fake
  `self-learn`** (P3-2), and **advance-to-next after resolution +
  bucket-clear return to Front** (P3-9)).
  *Predicate:* every 09 §2 behavior named in this sentence has a test
  that fails when its logic is inverted.
- **T-B · Pane permission live refusal** (live, logged): a real `cli`
  engine session over a sacrificial record in a throwaway
  `SELF_LEARN_HOME`, instructed verbatim to (1) run `git log` via Bash,
  (2) write a file outside its allowlist, (3) edit its own record —
  expect refuse/refuse/succeed. *Predicate:* 3/3; any failure of (1) or
  (2) triggers the 09 §4.3 ladder and re-trial before U6 proceeds.
- **T-C · End-to-end adjudication** (live, logged): seeded record +
  valid proposal in a throwaway repo with a bare remote → launch TUI →
  approve → *predicate:* route commit exists with pinned message, record
  in `resolved/`, proposals `git rm`'d, push landed on the bare remote,
  sentinel file released, TUI showed the refresh — all verified from the
  filesystem/git, not from TUI output.
- **T-D · Deep-link chain** (live desktop, logged): `self-learn-notify`
  with a fake event (ids + aggregate) → click "open" on the swaync
  notification → *predicate:* focused/launched TUI lands on that
  record's Detail; second invocation with a different id navigates the
  existing instance (socket path proven by pid equality).
- **T-E · Stream + interrupt smoke** (live, logged): Iterate on a
  seeded record; *predicate:* streamed text visibly renders
  incrementally; Esc ends the stream with the subprocess gone within
  5 s; the post-session `proposal validate` call ran and its exit code
  surfaced per the 08 §7.1 pin (0 → stamped fresh; 1/2 → the right
  badge + error strip); interrupted-then-approve completes.

Merge to master requires: T-A green in CI; T-B/T-C/T-D/T-E each with a
passing dated entry in `tui-trials.md`; the 09 §5 degradation table
walked row-by-row with each row's behavior demonstrated (test or logged
manual check).

## 3. Task DAG

Each task = tests + code + DoD, same contract as 08 §3. Dependencies in
brackets.

- **U1 · Scaffold** []: uv project, entry wrapper, env parsing, logging
  (capped), keymap table module, CI wiring (pytest + pytest-asyncio +
  textual dev deps). *DoD:* `self-learn-tui --help` runs from a clean
  clone via the wrapper; lint+test skeleton green.
- **U2 · Ledger model** [U1]: `ledger.py` — CLI `--json` invocations
  (list incl. `--include-deferred`, status), record/proposal/merge YAML
  + diff readers, screen-model derivation (pure), watcher + debounce +
  poll + forced refresh, bucket re-discovery. *Tests:* T-A's model
  half. *DoD:* screen models correct on all constructed ledgers.
- **U3 · Screens** [U2]: Front/Bucket/Detail + status strip + action
  bar (arm/confirm/disarm) + note input + help overlay + banners
  ("resolved elsewhere", bucket-clear) + diff/YAML rendering. *Tests:*
  Pilot flows + snapshot suite. *DoD:* T-A's interaction half green.
- **U4 · Verb runner** [U3]: serialized async subprocess queue,
  disable-during-run, error strip (stderr verbatim), bulk graduate loop
  (`--no-push` + terminal push, halt-on-failure), interrupt-first
  dispatch check (stub pane), post-verb refresh. *Tests:* PATH-shimmed
  fake `self-learn` asserting argv sequences (incl. push-on-abort AND
  `route <survivor> --collapse <cluster-id>` from the cluster flow —
  P3-2); race test: verb during fake-iteration → interrupt called
  first.
- **U5 · Pane engine (cli)** [U1]: PaneEngine interface, stream-json
  client (spawn/parse/partial-messages/send/interrupt ladder/result),
  permission-flag compilation from the charter surface, doctrine
  compiler, pane-charter.md authored, verify-at-build ledger executed
  and logged. *Tests:* canned-transcript fake `claude` (happy path,
  error result, mid-stream kill, malformed line → skip+log). *DoD:*
  events replay byte-exact; live smoke deferred to T-B/T-E.
- **U6 · Iterate split** [U3, U5]: split layout, MarkdownStream
  transcript, input line, session lifecycle (fresh per Iterate, one
  live at a time, budget/turn-cap surfacing, cost footer), Esc
  interrupt, `q` close, post-session `proposal validate <id>` with
  **exit-code discrimination per the 08 §7.1 pin (0 stamped · 1
  schema-invalid · 2 scan hit → "scan-blocked" badge + error strip,
  never stderr parsing)**, stale badge refresh, live-re-render on
  file_changed. *Tests:* Pilot over the fake engine, incl. a fake
  `self-learn` returning each exit code.
- **U7 · Single instance + deep-link** [U3]: socket server/client,
  takeover, navigate routing (incl. resolved-id → bucket + banner,
  first-id rule), `self-learn-tui-open` (shimmed hyprctl/ghostty
  tests). 
- **U8 · Notifier swap** [U7]: `self-learn-notify` helper; the M2
  emission point swap (the 08 §7.1 pointer executes — a change in the
  *worker's* notify call, made in the same PR with its own test:
  headless fallback intact, action degradation intact); events.jsonl
  tail as wake-up source. *Constraint:* M2 notification template,
  payload, and events line byte-unchanged (08 §7.1).
- **U9 · Degradation walk** [U4, U6, U7]: implement + test every 09 §5
  row not already covered (engine spawn fail + retry, per-block
  fallback when no text_delta, no-proposal Detail, stale badge, corrupt
  events line, small terminal, worker-overdue strip).
- **U10 · Deploy + docs** [U1–U9]: install.sh picks up the three
  scripts via the existing glob (verify symlinks + no dangling — repo
  CLAUDE.md deploy-sweep rule); SKILL.md + README sections (launch,
  keys, env vars, engine note); `10` change-control appendix opened.
- **U11 · Acceptance** [all]: run T-B/T-C/T-D/T-E live, log
  `tui-trials.md`, walk the degradation table, then §6.

Parallelism: U5 alongside U2–U4; U7/U8 alongside U5/U6. Polish backlog
(explicitly deferred, not silently dropped): `proposal validate` inside
the auto-interrupt sequence (phase-1 reviewer's note); list
virtualization if a bucket ever exceeds ~500 rows.

## 4. Judgment calls that stay routed

| Situation | Route |
|---|---|
| Any §1 verify-at-build check fails with no §5 playbook covering it | Human |
| Exact-path `allowedTools` fails and the 09 §4.3 ladder is exhausted | Human (never loosen the surface) |
| Textual pinned-major unavailable/broken for a required fix | Human (bump is a 09 §6 risk decision) |
| Visual styling/layout taste beyond 09 §2's structure | Human, with screenshots — never iterate solo past structure |
| Changing pane model/budget/turn defaults | Human (user's cost call — same as worker model pin) |
| Building the sdk engine (either trigger, 09 §4.1) | Human confirms the trigger fired |
| Any keybinding conflict with terminal/Textual reserved keys | Propose remap to human; keymap is UX surface |
| G-3 trigger not fired but build requested | Human (gate discipline) |
| A 09↔corpus or 09↔10 conflict discovered mid-build | Stop; finding; human (authority rule, header) |

## 5. Eventuality playbooks

- **stream-json parse breaks** (CLI update changed an event shape): the
  engine logs the raw line, skips it, and degrades to per-block
  rendering; if the session becomes unusable, U5's canned transcripts
  pin the last-known-good CLI version — report the delta, hold the CLI
  version for the pane (`claude` is versioned by the system; escalate
  rather than pin a private binary).
- **`--include-partial-messages` missing/shape drift**: per-block
  fallback is already the specced degradation (09 §5); not a blocker.
- **Path-scoped allow rules not honored** (T-B fails): ladder per
  09 §4.3 — TUI-owned `--settings` PreToolUse guard (organizer-guard
  pattern; the settings JSON lives in the tui package, passed by
  absolute path), re-run T-B; if still failing, sdk-engine trigger fires
  (§4 human confirm). Never widen the allowlist to "make it work".
- **watchfiles/inotify limits** (many buckets): the 10 s poll is the
  floor; log a one-line notice, continue.
- **Socket path collisions / stale sockets**: takeover semantics (§1);
  two genuinely live instances is prevented by bind-or-forward; if bind
  and forward both fail, run detached (`--no-socket`) with a warning.
- **Pane cost anomalies** (subscription reports $0 vs API reports
  real): render verbatim, never compute; if budget-cap errors recur at
  default, that is a §4 default-change escalation, not a silent bump.
- **Bulk loop interrupted by machine sleep/crash**: committed-but-
  unpushed records are 08 §5's existing playbook (loud sync warning +
  `self-learn push`); the TUI re-launch shows the still-pending
  remainder; re-running the bulk row is idempotent (already-resolved
  ids vanish from the group).
- **swaync absent / action unsupported / --wait hangs forever**:
  `self-learn-notify` sets `--expire-time` and also exits on daemon
  close; worst case the detached helper lingers until notification
  timeout — bounded, invisible, and the M2 fallback path (plain
  notify-send) remains intact on hosts without the helper.
- **Ghostty absent on a future machine**: `self-learn-tui-open` falls
  back to `$TERMINAL`, then to printing the command; the TUI itself is
  terminal-agnostic (Textual).

## 6. Acceptance & merge

1. §2 complete (T-A CI + four live trials logged + degradation walk).
2. Deploy sweep: `install.sh` rerun; `~/bin/self-learn-tui`,
   `~/bin/self-learn-tui-open`, `~/bin/self-learn-notify` symlinks live
   and non-dangling (repo CLAUDE.md rule); fresh-shell launch works
   **through the symlink** (the P3-1 failure mode is exactly here).
3. Worktree → master merge per repo convention; autosync publishes.
4. 03's G-3 row gains a dated "shipped" note; README revision log
   entry; project memory update.
5. Open questions harvested into the change-control appendix (§7), not
   left in chat history.

## 7. Change control

Same discipline as 08 §9: pins here change only with a dated edit +
co-owner pointer (08 for shared pins, 09 for design); new build-time
gaps get dated **Build findings** appendix entries (finding →
disposition) so the next agent inherits answers, not archaeology. This
plan is complete when §6 exits.
