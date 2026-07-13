# 09 — TUI: full design spec (G-3)

*Written 2026-07-12 under the G-3 planning directive, seeded from
`07-review-ui.md` (the recorded vision) and grounded in three research
memos: `research/2026-07-12-agent-sdk-verification.md` (live SDK docs),
`research/2026-07-12-tui-environment-grounding.md` (live host + live CLI
flags), `research/2026-07-12-tui-framework-trade-study.md`. Status:
DRAFT until the Phase-1 gate passes.*

**Authority.** This document is the **design authority for the G-3 TUI**,
sitting beside 00–07 in the corpus family:

- `07-review-ui.md` remains the vision record; this spec refines it. Where
  this spec details something 07 only sketched, this spec wins. Where this
  spec *changes* a 07 position, the change is landed as a dated amendment
  in 07 itself (nothing wins silently) — see §10 for the amendments this
  spec necessitates.
- The six don't-subvert contracts (07 §4), P1/P2/P9, CLI-owns-all-
  resolution-mechanics, and the pane agent having no path to `route` are
  **invariants** here; every mechanism below is designed inside them.
- `08-build-plan.md` remains execution authority for M1–M3 and owner of
  the pins the TUI consumes (`--json` shapes, `events.jsonl`, sentinel,
  routing-doctrine single-sourcing). The TUI **consumes, never redefines**
  those pins; where TUI work needs one extended, the extension lands as a
  dated 08 edit per 08 §9 — never as a 09-local override.
- `10-tui-build-plan.md` (Phase 3 of this effort) is the execution
  authority for building what this spec designs. On conflict between 09
  and 10, **09 wins and the conflict is a finding** (same rule, same
  rationale as the corpus/08 relationship).
- **The build itself stays gated on G-3's trigger** (M2 shipped, worker
  proven). This spec exists so the gate opens onto a plan, not onto a
  design conversation.

---

## 1. Interaction model

Everything in 07 §1 stands: attend-at-convenience, ambient informative
notifications carrying event + aggregate, deep-link to the decision,
ignoring costs nothing. This section pins the mechanics 07 left open.

- **Resident, keyboard-first, modal-free.** One fullscreen (alternate-
  screen) app. Every action is a key; a persistent footer shows the live
  keymap; `?` overlays the full reference (the overlay is a layer, not a
  modal — any action key acts immediately from it).
- **Three screens, one stack**: Front → Bucket → Detail. `Esc`/`h` go up,
  `Enter`/`l` drill in, `j`/`k` (and arrows) move within a list. A
  deep-link entry (`--record <id>`) lands directly on that record's
  Detail with the stack behind it, so `Esc` still walks up sensibly.
- **Action keys on Detail** (also usable on a Bucket row): `a` approve
  (route), `d` deny (reject), `i` iterate (agent pane), `f` defer, `g`
  graduate (offered only when the record qualifies), `o` override
  destination, `n` attach/edit a resolution note.
- **Arm-then-confirm, never modal-confirm.** Resolution keys **arm** the
  action bar: it shows exactly what will run (verb, id, destination, note
  present/absent) and `Enter` executes, any other key disarms. One extra
  keystroke, zero dialogs. Rationale: `route` compiles + commits + pushes
  — a mis-keyed single-stroke apply would demand supersession to unwind;
  an armed bar keeps the flow (arm → Enter) two keystrokes with the
  verb's full effect visible.
- **Flow after resolution**: advance to the next pending record in the
  bucket (queue-clearing rhythm); if the bucket empties, return to Front
  with a one-line "bucket clear" banner.
- **Notes** (`n`): an inline single-line input in the action bar (multi-
  line paste accepted); saved into the armed verb as `--note`. The note
  habit is load-bearing (feeds the M2 rejected-proposal digest), so the
  deny arm-state displays a gentle `n to say why` hint when no note is
  attached. Hint only — never a gate (07: informative, not demanding).
- **Quit** (`q`) exits the process. The TUI holds no state worth
  preserving (files are the truth), so there is no background mode; the
  notification → deep-link path relaunches it in one keystroke's cost.

## 2. Surfaces

### 2.1 Front page — the bucket walk

- A table of buckets with pending learnings: bucket name, scope
  (skill/project/user), pending count, oldest pending age, unanalyzed
  count (records with no proposal yet). Sorted oldest-first (the queue's
  health is age, not size — 04's time-to-triage metric).
- A **status strip** (bottom): worker last-run + result, staleness alarm
  (worker overdue per its escalation pins), total pending, sentinel state
  if live (someone is mid-apply somewhere). Data: `status --json` plus
  the sentinel file's mtime read directly (read-only).
- Data source: `self-learn status --json` and `list --json` (08 §1 pinned
  shapes). The Front page never walks the ledger itself — if the pinned
  shapes lack a field the Front page needs (they currently lack
  `unanalyzed`), the field is **added to the CLI's `--json` output via a
  dated 08 §1 edit** (G-3 hardening was anticipated there: "the TUI
  contract hardens them at G-3"). See §10.

### 2.2 Bucket page — grouped pending

- Records grouped by **proposed destination** (proposal.destination:
  hook / skill-update / claude-md / references / new-skill), plus two
  synthetic groups: **unanalyzed** (no proposal yet) and **clusters**
  (merge-proposals). Groups render as sections, not tabs — one scroll.
- Row: id (short), age, title (first Trigger/Fact line — same derivation
  as `list --json .title`), sightings count, deferred badge when
  `deferred_until` is future (rendered dimmed at the bottom, since the
  queue proper excludes them), already-canon flag when set.
- **Cluster rows** (merge-proposals): one row per cluster showing member
  count and the suggested survivor; expanding (`Enter`) lists members;
  the survivor choice is a selection within the expanded view; approve
  arms `route <survivor> --collapse <cluster-id>` (08 §7 pin, consumed
  verbatim).
- **Bulk collapse**: a homogeneous already-canon group (the backlog-
  import case, 01 §3.2) renders as a single collapsible decision row
  ("N already-canon records — reject all"), arming a loop of per-record
  verbs. The TUI loops **individual pinned verbs**; it never invents a
  bulk CLI surface that doesn't exist. Progress renders per item; a
  mid-loop failure stops the loop with the failing id on screen.

### 2.3 Detail page — one decision, fully explained

Three stacked regions (07 §2's finding / change / why), one scroll:

1. **Finding** — record Trigger + Instruction rendered from the pending
   file, evidence quotes with origins, provenance line (source, sightings,
   created, teacher at team scale).
2. **Change** — the diff preview from `proposals/lrn-<id>.diff` when
   present, syntax-highlighted, with the standing preview-honesty caption
   ("compilers regenerate from the record at apply time — this preview is
   advisory"; 02 §4). When the proposal exists but the diff sibling
   doesn't, render the proposal's proposed text; when nothing exists,
   render "no analysis yet — `i` to analyze now".
3. **Why** — proposal rationale, suggested destination (+ alternates),
   already-canon flag reasoning if set, `record_sha` freshness badge:
   **fresh** (hash matches current record body) or **stale** (record
   edited since analysis — Iterate to regenerate). Staleness is computed
   by the CLI (`list --json` gains a `proposal_fresh` boolean — same
   normalization function as everywhere; §10), never by the TUI hashing
   things itself.

Action bar at the bottom (armed states per §1). `o` (override
destination) cycles the destination the armed `route` will pass via
`--dest`; the overridden value renders distinctly so the user sees the
analyst's suggestion vs. their override.

### 2.4 The iterate split

`i` splits Detail horizontally: left = the record/diff (live — it
re-renders when the agent edits files), right = the **agent pane**
(§4): streaming transcript + a single-line input for talking to the
agent. `Esc` in the pane interrupts the stream; `q` in the pane closes
the split (ending the session) and returns to full Detail. Approve/deny
keys stay live during iteration — adjudication never waits for the agent
to finish (interrupting-then-approving is legal and common).

## 3. Process & data architecture

**The files are the only truth; the TUI is a reader and a verb-invoker.**
The TUI process itself never writes ledger files — not records, not
proposals, not canon. Exactly two kinds of writes exist anywhere near it:
the CLI verbs it spawns (which own compile/commit/sentinel/push), and the
pane agent's tool calls (record/proposal edits, legal pre-routing per
S-8, inside the permission surface of §4.3).

- **Reads**: `list --json` / `status --json` for lists and counts; raw
  files (record md, proposal yaml, diff) for Detail; `events.jsonl` only
  as a wake-up signal, never as state (the ledger is authoritative;
  events are machine-local, 08 §7.1).
- **Refresh**: filesystem watch (inotify via the framework's watcher or
  `watchfiles`) on the bucket `pending/` + `proposals/` dirs and
  `events.jsonl`, debounced ~300 ms; a 10 s poll as fallback where inotify
  misses (NFS-style edge cases). Any verb completion forces a refresh.
  External mutations (autosync pull from another machine, a concurrent
  `/self-learn:review` session) surface the same way — the watch fires,
  the view re-reads. If the record currently open in Detail disappears
  (resolved elsewhere), Detail shows a "resolved elsewhere" banner and
  returns to the Bucket page. No locks, no leases: concurrent surfaces
  stay coherent because files are the only truth (07 §3).
- **Verb invocation**: subprocess `self-learn <verb> <id> [--dest …]
  [--note …] [--collapse …]`, exit status + stderr captured. The TUI
  renders outcome from the verb's exit status and the subsequent
  file-state refresh — it never parses human-formatted stdout for state
  (07 §4 contract 2). Sentinel hold/heartbeat/release is entirely inside
  the verb (08 §1); the TUI holds nothing, so a TUI open for days holds
  the autosync pause for zero seconds beyond each verb's own window
  (07 §4 contract 4 by construction).
- **Single instance + deep-link**: a unix socket at
  `$XDG_RUNTIME_DIR/self-learn/tui.sock`. Launch behavior of
  `self-learn-tui [--record <id>]`: if the socket answers, send
  `{"navigate": "<id>"}` and exit 0 (the resident instance navigates);
  else become the instance. Terminal-window focus is the launcher's job,
  not the TUI's: the desktop entry point `self-learn-tui-open` (a tiny
  script) either focuses the existing window (`hyprctl dispatch
  focuswindow` on a pinned window class, set by launching the terminal
  with an explicit class, e.g. `ghostty --class=self-learn-tui -e …`) or
  spawns a new terminal running the TUI. Window-manager specifics live
  ONLY in `self-learn-tui-open` (the one Hyprland-aware file; degraded
  behavior elsewhere is "new terminal each time", which is correct-but-
  unfocused).
- **Notifications** (sender side, G-3 addition): M2's pinned notifier
  (`notify-send` human string + events.jsonl line) is unchanged until
  G-3 lands. At G-3, the emission point swaps to a detached helper
  (`setsid self-learn-notify …`) that adds a click action
  (`notify-send -A open --wait`; blocks in its own detached process —
  verified semantics, environment memo) and on click runs
  `self-learn-tui-open --record <id>`. Worker code passes the same ids
  it already logs; the swap is a dated 08 §7.1 pointer when built. swaync
  (the live daemon) renders actions natively; on hosts without an
  action-capable daemon the helper's `--wait` returns without output and
  nothing else changes (degradation: notification is informative-only,
  exactly M2's behavior).
- **TUI-owned state**: none in the repo. A log at
  `~/.cache/claude-skills/self-learn/tui.log` (size-capped like
  `worker.log`) and the socket. No config file in v1 — env vars only
  (§4.4, `SELF_LEARN_HOME` as everywhere).

## 4. The adjudication pane

### 4.1 Engine abstraction — and the engine decision

07 §3 recorded the pane as "a small Agent SDK session". Empirical
grounding (both memos) sharpened this into a **decision between two
engines that run the same underlying agent loop** — the Agent SDK is a
wrapper that spawns the Claude Code CLI:

| | `cli` engine — `claude -p` stream-json | `sdk` engine — `claude-agent-sdk` (Python) |
|---|---|---|
| Auth / economics | The user's normal CLI auth (subscription) — same as the M2 worker and every `claude -p` worker in this repo | **API-key only per live docs** (SDK memo §2) — per-token billing for every pane session |
| Token-level streaming | `--include-partial-messages` **verified on the live binary** | Not documented as exposed (SDK memo flag 2) |
| Model fallback | `--fallback-model` verified present | No fallback option (SDK memo §6) |
| Permission surface | `--allowedTools` rules (path-scoped rule syntax is the same one 08 §7 pins for the worker) + `--disallowedTools Bash` | Same flags **plus** in-process `canUseTool` callback (exact-file allowlist in code) |
| Interface stability | stream-json protocol, versioned with the CLI | semver'd typed library |
| Uniformity | One engine family across worker + pane (both `claude -p`) | Second dependency + bundled second CLI binary |

**Decision: the `cli` engine is the default; the `sdk` engine is the
recorded alternative behind the same interface.** Grounds (the quality
axes): *economics* — a heavy-daily-use resident tool on API-key billing
converts a subscription workflow into a metered one, and the SDK's
API-key-only stance is source-verified; *capability* — token streaming
and model fallback are verified on the `cli` side and unverified/absent
on the `sdk` side; *architecture* — one engine family across worker and
pane. The SDK alternative is kept specced because `canUseTool` gives
strictly stronger in-process permissioning and because API-key
deployments (team scale, 06-horizon) may prefer it; it must stay
buildable behind the interface. This is a dated amendment to 07 §3
(§10) — the vision's invariants (fresh session per adjudication, stable
doctrine prefix, agent iterates / human routes) are engine-independent
and unchanged.

**`PaneEngine` interface** (the seam both implementations satisfy):
`start(item_context) → session`, `send(text)`, `interrupt()`, `close()`,
plus an async event stream of: `block_start(kind)`,
`text_delta(str)` (absent → per-block fallback), `tool_use(name,
target_path)`, `file_changed(path)`, `result(status, cost_usd | null,
error | null)`. The TUI renders events; it never reaches around the
engine to the transport.

### 4.2 Session lifecycle

- **Fresh session per Iterate** (07 §3, unchanged). No resume across
  Iterates: adjudication context is small and rebuilt from files, and a
  stale session's view of edited files is a liability, not an asset.
  (`--no-session-persistence` — these sessions are ephemeral by design
  and should not pollute `~/.claude/projects` resume lists.)
- **Prompt structure**: system prompt = the **compiled doctrine file**
  passed via `--system-prompt-file` — byte-stable across sessions by
  construction: `routing-doctrine.md` (the single source, 08 §1 — one
  file, *four* consumers after this spec) + the **pane charter** appendix
  (§4.3's rules rendered as prose, a tracked file compiled next to it).
  `--setting-sources` emptied so no CLAUDE.md rides in (context hygiene +
  byte-stability; exact empty-value syntax is a build-time pin).
  Per-item context — record body, proposal + diff if present, target
  canon excerpt (the candidate target's managed section ± 20 lines, or
  the whole file < 200 lines: **the same excerpt rule as the worker
  prompt pin**, 08 §7) — rides in the first user message, never in the
  system prompt.
- **Caching is opportunistic economics, never a dependency** (dated
  amendment to 07 §3's "pays the doctrine's tokens once" — that holds
  only within the API's 5-minute default cache TTL, SDK memo §2). The
  byte-stable prefix maximizes whatever caching the auth path provides;
  the design budget assumes zero cache hits and stays acceptable: the
  doctrine + charter is a few KB, and per-item context dominates.
- **Caps**: `--max-budget-usd` (env `SELF_LEARN_PANE_BUDGET_USD`,
  default 1.00) and a turn cap (env `SELF_LEARN_PANE_MAX_TURNS`, default
  15; exact CLI flag verified at build — `--max-turns` per headless
  docs). Model: `SELF_LEARN_PANE_MODEL`, default `claude-sonnet-5`, with
  `--fallback-model claude-haiku-4-5` (adjudication help is human-gated
  — the same cost-beats-brilliance call as the worker's model pin, and
  the user's to change).
- **Cost honesty**: the pane footer renders the `result` event's
  cost/usage report verbatim when present (subscription auth may report
  0/absent — render what the engine reports, never invent a number),
  plus turn count.
- **Interrupt**: `Esc` → engine.interrupt() (stream-json interrupt
  control message; escalate to SIGTERM after 2 s grace, SIGKILL after 5).
  Interrupting never discards file changes already written by the agent
  (files are truth; the re-render already showed them).
- **One live session at a time.** Iterate on another record while a
  session runs → armed prompt to interrupt the current one first.
- **Session end**: on `result`, the input line stays open for a follow-up
  `send` **only if** the engine supports multi-turn in-place (stream-json
  input does); otherwise the pane shows the result and offers `i` to
  start a fresh session. Either way the pane's transcript is ephemeral —
  closing the split discards it (outcomes live in files; 07 §3).

### 4.3 Pane permission surface (the charter)

The pane agent's job: improve the pending record and its proposal, answer
questions about the target canon. Its **hard surface**, expressed once in
code and compiled to engine config (flags for `cli`, options + callback
for `sdk`):

- **Allowed**: `Read`, `Grep`, `Glob` (corpus + target canon are
  readable); `Edit`/`Write` on **exactly** the item's own files:
  `pending/lrn-<id>.md`, `proposals/lrn-<id>.yaml`,
  `proposals/lrn-<id>.diff` — absolute-path rules, no wildcards beyond
  the id's own siblings.
- **Denied, structurally**: `Bash` (with it, every write restriction is
  void — the worker's own pin, E-18), `Task`, `WebSearch`, `WebFetch`,
  MCP (`--strict-mcp-config` with none configured), everything else not
  allowed above. `cwd` = the bucket root.
- **No path to route** (07 §4, P1): the resolution verbs are not tools,
  the CLI binary is unreachable without Bash, and approval is a TUI
  keystroke calling the verb from TUI code. Proposer ≠ approver, by
  construction — same trust geometry as the worker.
- **Post-iterate stamping**: anything the pane agent writes into a
  proposal is **unstamped by definition** (models cannot compute
  `record_sha` — M2-21). On session end (or file_changed on a proposal),
  the TUI invokes the CLI's validate-and-stamp surface for that id
  (`self-learn proposal validate <id>` — a thin CLI verb exposing the
  exact validation+stamping step the worker already runs internally,
  08 §7 run-sequence step 4). Until stamped, Detail shows the proposal
  as stale — which is true. This verb is a **new 08 §7 pin** (dated
  edit; §10): it adds no new logic, only a callable entry to logic M2
  already builds, and it is what makes pane output equal-citizen with
  worker output instead of a hash-discipline hole.

### 4.4 Configuration (complete list)

`SELF_LEARN_HOME` (existing), `SELF_LEARN_PANE_MODEL`,
`SELF_LEARN_PANE_BUDGET_USD`, `SELF_LEARN_PANE_MAX_TURNS`,
`SELF_LEARN_PANE_ENGINE` (`cli` | `sdk`, default `cli`). Nothing else in
v1; no config file.

## 5. Error handling & degradation

Ordered by blast radius; the invariant throughout: **adjudication never
depends on any optional subsystem.** Approve/deny/defer work when the
worker is dead, the pane is broken, the network is down (push fails
surface from the verb, per its own pins), and notifications are absent.

| Failure | Behavior |
|---|---|
| Pane engine spawn fails / `result: error_*` | Pane renders the error + `r` retry; Detail and all resolution keys unaffected. `error_max_budget_usd`/turn-cap render as "budget/turn cap hit — r to continue in a fresh session". |
| Engine emits no `text_delta` (partial streaming unavailable) | Per-block rendering with an activity spinner — a rendering degradation, not a feature loss (SDK memo flag 2). |
| No proposal for a record | Detail renders record-only; Iterate works from scratch (the agent generates the proposal — the M1 inline-analysis path through a different door). |
| Proposal stale (`record_sha` mismatch) | Badge + hint to Iterate; approve stays available (the verb re-validates authoritatively at apply — the TUI badge is advisory UI, the CLI is the enforcer). |
| Verb exits non-zero (dirty target, push failure, scan refusal…) | Error strip with the verb's stderr verbatim; state re-read from files; nothing optimistic. The verb's own messages are the contract — the TUI adds no interpretation. |
| Record resolved elsewhere mid-view | Watch fires → "resolved elsewhere" banner → Bucket page. |
| `events.jsonl` absent/corrupt line | Skip + log; wake-ups degrade to the poll; ledger walk is truth. |
| Socket stale (dead instance left it) | Connect fails → remove + take over (standard liveness-check-then-bind). |
| swaync/action support absent | Notifications degrade to M2's informative-only behavior. |
| Terminal too small | Framework reflow; below minimum, a "resize to ≥ 80×24" placeholder. |
| Worker overdue / never ran | Status strip alarm (reuses the worker's own escalation thresholds); everything else functions — the TUI is not the worker's supervisor. |

## 6. Framework selection

**Decision: Textual (Python), major version pinned; Ink 7 is the
recorded runner-up with explicit switch conditions.** Full study with
sources: `research/2026-07-12-tui-framework-trade-study.md`. The study's
verdict on closeness was explicit — *not* genuinely close on fit —
so the choice does not route to the user; the one human-values caveat it
isolated is recorded below instead.

- **Why Textual** (study §a/§c): the only candidate where every screen
  in §2 maps to a shipped, documented widget — including the two hardest:
  the token-streamed agent pane (`Markdown.get_stream()`/`MarkdownStream`
  exists specifically for LLM-rate output) and the highlighted diff
  (Pygments `DiffLexer` via Rich, already a core dependency). Best
  testing story in the field (Pilot + `pytest-textual-snapshot`);
  packaging is a PEP 723 `uv run --script` shebang — exactly this repo's
  `~/bin` convention; one language across CLI, TUI, and the `sdk` engine
  (`claude-agent-sdk` is Python). Lowest estimated build effort by a
  wide margin (Ink would hand-build scroll, list windowing, stream
  batching, and diff rendering).
- **Risks accepted, with mitigations**: (1) **bus factor 1** — Textual
  is post-Textualize-shutdown, maintained personally by its author;
  activity is verifiably healthy through 2026-06 but singular. (2)
  **Major-version churn** (v4→v8 in 12 months) — the build pins the
  major version and treats upgrades as deliberate maintenance.
- **The recorded values caveat** (study §d): if the user weights 5-year
  longevity above build cost and widget fit, the ranking flips to Ink.
  The exposure is bounded: the CLI, file formats, engines, and doctrine
  sit behind the UI, so a later switch is a **view-layer rewrite only**.
- **Switch conditions to Ink** (recorded verbatim from the study):
  Textual goes ≥6 months without a release or its maintainer steps back;
  or the codebase must become TypeScript; or the UI simplifies toward a
  chat-first layout. **Watchlist**: OpenTUI at 1.0 with stable Node
  support — re-evaluate early 2027.

Sections 1–5 are framework-agnostic by construction (screens, keys,
regions — not widgets); only `10-tui-build-plan.md` names Textual APIs.

## 7. Testing & acceptance posture (design-level)

Detailed fixtures live in `10-tui-build-plan.md`; the design constrains
them:

- The TUI's logic (state derivation from files, verb arming, engine event
  handling, permission-surface compilation) is testable headless — the
  file-truth architecture means every screen is a pure function of a
  directory tree, which tests construct in throwaway `SELF_LEARN_HOME`
  repos (08 rule 4 applies verbatim).
- The pane's permission surface gets a **live refusal check** mirroring
  the worker's (08 §7.3): a real session instructed to run Bash / write
  outside its allowlist must be refused — flag construction is the cheap
  test, live refusal is the real one.
- Framework-level UI tests use the framework's native test harness
  (§6's study weighs this); visual/manual polish trials are acceptance
  items, not CI items.

## 8. What is deliberately absent

- **No approval bypass** through the pane, however capable it gets
  (07 §5; P1). No batch-approve of heterogeneous items.
- **No serving layer, no database, no daemon** beyond the resident TUI
  process itself; no state that isn't a file.
- **No dashboards/scores** — the status strip is counted facts only
  (worker last-run, pending, ages; counted-not-modeled, 04).
- **No in-TUI capture** (`teach` lives where the lesson happens — in
  session or terminal; the TUI is the adjudication surface, not a fifth
  producer).
- **No notification ownership** — the TUI never sends notifications; it
  is their destination.

## 9. Extensibility posture (team scale, 06-horizon)

Nothing here blocks the staged path: provenance fields already render
(§2.3 shows teacher when present); PR-based routing authority would swap
the verb the action bar arms (`route` → a PR-opening variant) behind the
same armed-bar UX; the `sdk` engine slot is where API-key/team
deployments land; the socket/deep-link protocol is machine-local by
design and needs no change. The one deliberate non-feature: multi-user
presence (who else is reviewing) stays out until Stage 2 exists — the
files+watch architecture makes eventual coherence the default anyway.

## 10. Corpus amendments this spec necessitates

Landed as dated edits when this spec's Phase-1 gate passes (listed here
so the gate reviews the *set*):

1. **07 §3** — "small Agent SDK session" → "agent session behind the
   PaneEngine interface (`cli` default / `sdk` alternative — 09 §4.1)";
   the prompt-cache sentence gains the 5-minute-TTL honesty caveat
   (caching = opportunistic, never a dependency). Both changes cite the
   two research memos.
2. **08 §1 pins table** — `--json` stubs row: add `unanalyzed` (per
   bucket) to `status --json`, add `proposal_fresh` + `destination` to
   `list --json` items (computed by the CLI with the shared
   normalization function; the anticipated "G-3 hardens" clause fires).
   Dated edit noting 09 §2.1/§2.3 as consumer.
3. **08 §7** — new pin: `self-learn proposal validate <id>` — CLI verb
   exposing run-sequence step 4's validate+stamp for one id (consumer:
   pane post-iterate stamping, 09 §4.3). T13's task list gains it.
4. **08 §7.1** — notification emission: dated pointer that at G-3 the
   `notify-send` call moves into `self-learn-notify` (detached, action-
   capable, same payload + events.jsonl line unchanged; 09 §3).
5. **03-decisions G-3 row** — status update: vision spec → full spec
   (09) + build plan (10); trigger unchanged.
6. **02 §3 storage layout** — one line: the TUI's transient state
   (socket, tui.log) lives under the existing
   `~/.cache/claude-skills/self-learn/` home (no new location).

No settled decision's *inputs* change: S-2/S-9 and the 07 §4 contracts
are honored, not amended; the engine decision amends a vision detail
(07 §3), not a register entry. If the Phase-1 reviewer finds otherwise,
that finding reopens the register per P10 before anything lands.
