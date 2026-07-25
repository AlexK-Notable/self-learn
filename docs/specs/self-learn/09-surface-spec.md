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
  keymap; `?` overlays the full reference. *(Amended 2026-07-19 — F5-3,
  feedback round 5, U19 §1.1: this line previously read "a layer, not a
  modal — any action key acts immediately from it", which the shipped
  overlay never honored — Escape fell through to the interrupt/up
  binding and silently cancelled a running Iterate. Corrected doctrine:
  **a layer, not a modal — any key dismisses it and does nothing else;
  keys act on the page only while the overlay is closed.** `?` keeps its
  toggle semantics as a special case of this rule.)* *(Amended 2026-07-18 — U16/§11
  Y-19 item 3, survey P1a: on EVERY list screen, the first actionable
  row carries the `.selected` cursor from load — not only after the
  first `w`/`s` press — and the content region is guaranteed
  programmatic focus on load and after every queue-walk hop, so the key
  contract above is live without a prior click. Both are presentational
  only: no staleness surface, files remain truth, nothing here changes
  what a key DOES, only when it starts working. The mechanism must never
  steal focus from a live pane's send input or fight the U14 armed-bar/
  error-strip focus behaviors — see §11 Y-19 for the full guard.)*
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
- **Worker Force-run** *(added 2026-07-18 — U16/§11 Y-19 item 2, survey
  P2a)*: a button beside the worker's status-strip line, the missing
  symmetric affordance to the miner's own Force-run (§2.1's status strip
  already carries the miner's; the worker — the M2 proposal drafter, the
  thing the whole surface exists to adjudicate — had none). Same
  no-arm-then-confirm pattern as the miner's (idempotent-by-construction
  trigger, not a resolution verb): one click POSTs `self-learn worker
  kick`, forces a front-scope refresh, redirects back to Front. `worker
  kick` is NOT `worker run` — per 08 §7.1 it touches `worker.dirty`,
  takes `worker.spawn.lock`, and `setsid`-spawns the real analysis pass
  DETACHED before returning, so this request's in-flight window is the
  kick's own short runtime, never the whole coalesce+analysis pass —
  Y-14's idle-exit posture is respected by construction (the detached
  worker can keep running, and the server can still idle-exit, after
  this request completes). Double-click safety is the CLI's own
  flock/`worker.window` absorption (`spawned` \| `absorbed-window` \|
  `absorbed-race` \| `disabled`), not a client-side guard — mirroring
  the miner's button, which carries none either.

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
  on the Detail split. *(Amended 2026-07-18 — feedback round 2
  item 1; §11 Y-15: `p` swaps the split in immediately in the same
  starting state as Detail's `i` — the two variants share the pane
  session manager and share §4.2's non-blocking start contract; this
  bullet's "Open bucket chat" button is the exact control the user
  hit the silent 30–90 s wall on.)*
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
   sightings, created, teacher at team scale). *(Amended 2026-07-18 —
   §11 Y-21, UX survey item 5:)* when the record carries a `## Episode
   brief` body section (miner-written, `source: session` only — 02 §1,
   12 §11), the Detail page renders it as a **collapsed, expandable**
   block **below** the decision content (Trigger + Instruction +
   evidence), never inline in the decision text and never above it —
   FB4 principle 3: decision content owns the screen, recognition
   context recedes until summoned; a **longer** brief must not push
   Trigger/Instruction or the diff below the fold. **Build obligation:**
   the Finding region today renders the whole record body as one blob
   (`model.finding.body | markdown`), so the finding model — built in
   **`models.py`** (`_build_finding`, `FindingRegion`; `ledger.py` is
   the I/O module, not the model builder) — must **split the `## Episode
   brief` section out** of `record.body` before it becomes
   `finding.body`, and expose the brief separately (e.g.
   `model.finding.episode_brief`) for the collapsed render. Collapsed by default, one summon to expand (a key or click —
   the exact affordance is a build call, matching the round-4 hotkey-
   legend disclosure pattern); the expand affordance appears **iff** the
   section exists — **absent brief renders nothing**: no block, no
   placeholder, no apology (the generic skip-absent posture). **No
   staleness surface** — the brief describes the past, has no
   `record_sha`, gets no freshness badge (12 §11). **Bucket-page rows
   do not grow** (§2.2): the brief is click-into content by the user's
   own framing, reached only on Detail.
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
   *(Amended 2026-07-18 — §11 **Y-20**, UX-survey item 4:)* the Why
   region is the **single budget surface** (there is no armed-bar
   budget — see the action-bar note below). Beside the suggested
   destination **and each alternate**, render its **loaded-surface
   budget** in plain words (Y-9). For the two **capped** destinations
   (`skill-md`, `claude-md`) the fact comes from the CLI:
   `list --json --surface-fill .surface_fill[<destination>]` (08 §1
   field — the Detail render is the one call-site that passes
   `--surface-fill`) — e.g. "this skill-md section already holds 8 of
   its 10 entries — a route here lands near the cap", and the
   **word**-cap phrasing ("…and is near its word budget") when `words`
   is the binding constraint. For **`reference`** the line is
   **template-static, no CLI datum, no probe** (blind-review F1 —
   `reference` is the cap-free overflow sink; it carries no
   `surface_fill` key): a fixed plain-words note, "reference files have
   no cap — this is the overflow surface entries graduate into." The
   register is decision-support (routing-doctrine §8): it states the
   fact the narrowest-surface bias (RD §3) turns on, so the human
   *decides* with the cost visible rather than discovering it at
   apply-time rejection. For the capped destinations the datum is the
   CLI's counts and the **sentence is the template's** — the same
   division of labor as `proposal_fresh` → "fresh"/"stale" (§5 rule: the
   server renders what the CLI computes, never derives a threshold
   judgment of its own). A capped destination **absent** from
   `surface_fill` (any `VerbError` from the read-only resolver — 08 §1
   F5) shows **no indicator** — never a zero, never a guess. At/over cap
   the indicator states the fill fact only; the escalation is the
   **existing** 02 §4 over-cap WARNING + graduation-opener flow
   (referenced, not duplicated here) — when
   `surface_fill[<destination>].over_cap` is already true, that flow
   owns the "route still applies but flags the section" story.

Action bar at the bottom (armed states per §1 — keymap contract note,
2026-07-19, F5-3: while the `?` help overlay is open, NO key reaches
this bar at all — any key dismisses the overlay first, §1). `o` (override
destination) cycles the destination the armed `route` will pass via
`--dest` — **among the parameter-free values only** (`skill-md`,
`claude-md`, `reference`). `new-skill:<name>` and `hook` need
structure a cycling key cannot supply: reachable via Iterate or the
CLI directly; the cycle skips them with a footer hint saying so
(P1-9a, carried). *(Amended 2026-07-18 — feedback round 2 item 3: the
cycle is additionally **scope-filtered** to what the route verb's own
scope rules (02 §1 destination forms, enforced in the CLI's target
resolver) can accept for THIS record — `skill-md` only for
skill-scoped records, `reference` only for skill/project, `claude-md`
everywhere; and when the analyst's suggested destination is
scope-invalid — the live 2026-07-17 stranding: `skill-md` proposed on
a project record — the bar presents a corrected valid default plus a
plain-words note saying what changed and why. The armed bar always
shows the destination the confirm will execute, byte-identical. No
posture change: this surfaces the CLI's existing refusals as
prevention; the error strip stays stderr-verbatim per §5.)* The
overridden value renders distinctly (analyst's
suggestion vs. override). *(Amended 2026-07-18 — §11 **Y-20**,
UX-survey item 4:)* **the armed action bar carries NO budget datum**
(blind-review F2 — pinned negative). It keeps showing only the
selected destination *name*, exactly as today; `action_cycle_destination`
reads the `dest` field and re-fetches nothing (and the codebase already
documents that cycle round-trips DROP non-echoed context — the
`dest_note`/`already_canon` precedent at routes.py:605-617), so wiring
a per-cross budget through the cycle would need a new, staler datum
path for no gain. The **Why region is the single budget surface**: it
lists **every** scope-valid candidate with its budget at page render
(the granularity decision above), so the narrowest-surface comparison
("skill-md holds 8 of 10, claude-md holds 3 of 10", RD §3) is already
on-screen without the bar carrying a second, drift-prone truth.
**Freshness:** `surface_fill` is computed **at render**, like
`proposal_fresh` — never cached in the server, never derived. Because
fill changes whenever *another* record routes, and a route to record X
moves the fill of any record Y that shares X's target, the U16
next-record prefetch's **invalidation-on-verb-execution rule is
load-bearing here and must be global-on-any-verb-completion, not
per-record**: a warmed Detail partial's `surface_fill` is **not** exempt
from the standing "any verb completion forces an SSE push → re-request
the partial" rule (§3), and a prefetch cache that invalidated only on
the prefetched record's own change would show a stale budget on Y after
X routed. **U16/Y-19 live in a parallel worktree, so Y-20 cannot enforce
this from its branch** — the orchestrator injects this invalidation
obligation into U16's own row at merge (already messaged to the U16
builder mid-build); until then Y-20's field is still correct at every
*fresh* render, only the prefetch-warm case needs U16's coverage. `g` is always available on Detail for a
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
two-keystroke path, whoever suggested the verb.)* *(Amended
2026-07-18 — feedback round 2 item 1; §11 Y-15: the split swaps in
**immediately** on the Iterate POST, rendered in a **starting**
state — a plain-words status line ("Starting the conversation…",
the Y-9 register) where the transcript will appear; the first agent
turn never rides the POST response. The live region then fills over
the existing SSE stream (§3) exactly as any visible pane does, and
the turn's completion — result footer or error strip + `r` — lands
by §4.2's completion swap (the `pane_result`-triggered panel
re-fetch). Normative contract at §4.2's start bullet. The
user-measured failure
this repairs, their words: "there was no indication that anything
was happening after i clicked the button.")*

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
  *(Amended 2026-07-18 — §11 Y-14; reworked same day after its own
  blind spec review, findings folded in place: residency is now
  **resident while in use**, not resident-forever. The server
  self-monitors an idle predicate — ALL of: zero SSE subscribers;
  zero in-flight HTTP requests; the verb runner between verbs; no
  live pane session in an INTERRUPTIBLE state (starting / streaming
  / interrupting — an agent mid-turn is work-in-flight; a session
  parked at awaiting-input does NOT block, see the teardown line
  below); and no HTTP request COMPLETION for
  `SELF_LEARN_UI_IDLE_EXIT_SECONDS` seconds (the request clock
  stamps at completion, never arrival — an in-flight bulk loop or
  long mine run must not age toward idleness while it works; the
  in-flight-zero leg is the belt for the same class) — sampled by
  one in-process task on the SAME event loop as the request
  handlers, which decides and signals in one loop step (no `await`
  between predicate read and signal — nothing can interleave).
  When the predicate holds, the monitor first tears down any parked
  (awaiting-input / ended) pane session through the standard
  teardown (which clears the proposal slot via §4.5's clear-set),
  then exits CLEANLY — by setting uvicorn's own ``should_exit`` flag,
  which drives the standard graceful shutdown and lets the process
  RETURN with exit 0. *(Mechanism corrected 2026-07-18 at the U13
  live trial, which caught the first-drafted SIGTERM-to-self failing
  in production: uvicorn 0.29+ ``capture_signals`` restores default
  handlers and RE-RAISES every captured signal after graceful
  shutdown, so a self-signaled process dies BY SIGNAL — the parent
  reports 143, systemd logs "Failed with result exit-code", and
  ``Restart=on-failure`` RESTARTS the service: the exact opposite of
  stay-down. Three restart cycles observed live before the fix. The
  spec-gate review had verified the SIGTERM claim as sound —
  plausible-but-wrong on the installed uvicorn; the DoD trial is what
  caught it.)* **Teardown and exit never share a step** (delta R1): the
  teardown awaits engine calls, so a sample that finds a parked
  session tears it down and DEFERS the exit decision — the signal
  fires only on a later sample whose full predicate read reaches
  the signal with no `await` in between (a request completing
  during a teardown must be seen before any exit). Under the unit's existing `Restart=on-failure`, a clean
  exit stays down; the launcher's idempotent `systemctl --user
  start` — already step 1 of `self-learn-ui-open` — is the
  resurrection path, and crash-restart behavior is unchanged.
  **Arming rule (systemd-absent playbook preserved by
  construction):** self-exit arms by default ONLY under the unit
  (detected via systemd's `INVOCATION_ID`); a foreground
  `self-learn-ui serve` (10 §5's documented fallback, where no
  launcher resurrection exists) stays resident unless the env var
  is set explicitly. The single-instance invariant is untouched: at
  most one server; there is now legitimately zero. In-memory
  casualties of an idle exit, honestly enumerated: the proposal
  slot and the parked pane snapshot (both already pinned ephemeral
  — 09 §4.2 "closing the split discards it; outcomes live in
  files"), AND the scan-blocked badge map (§4.3 carries the dated
  acceptance: the badge is advisory and does not survive an idle
  exit; the verbs' own full-file scan — P2-7 — is the enforcer).
  With zero SSE clients and no requests for the whole window, no
  page was open to be reading any of them.)*
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
  *(Amended 2026-07-18 — U16/§11 Y-19 item 1, survey P2b: while a
  Detail page is open for record N, a background task warms record
  N+1's own Reads bundle — the exact record the queue-walk would land
  on next (the SAME computation `next_record_url` already makes, one
  shared function) — so the post-confirm `HX-Redirect` hop can skip
  this subprocess-read stall. Zero model cost: this is CLI reads +
  server render only, never a `claude -p` call. CRITICAL staleness
  rule, satisfied by construction, never by a timer: a warmed entry is
  valid ONLY while stamped against the CURRENT generation of the
  **Refresh** bullet's own hub below — the SAME single mechanism every
  refresh push (a watchfiles-detected change OR a verb completion)
  already funnels through, so this adds no second signal path. The
  gate is deliberately GLOBAL, not scoped to the touched record: ANY
  refresh invalidates the ENTIRE (single-slot) warm cache, because the
  survey's §2 Q3 P3a loaded-surface-budget indicator (landing
  separately, tracked as Y-20/U17) means routing one record can change
  what an UNRELATED record's own rendering should show — once that
  datum exists, a per-record invalidation would be unsound for that
  reason alone, so this item builds the coarse rule from the start
  rather than narrowing it later and having to re-derive why. A
  cache miss (never warmed, or warmed-then-invalidated) falls straight
  through to an ordinary fresh read — there is no code path that can
  serve a stale bundle, only a hit-at-the-observed-generation or a
  miss.)*
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
  case — re-derived 2026-07-18 as ladder ≤2.5 s + bounded close
  ≤2.5 s under the tuned constants), then runs the verb — never concurrently (the pane agent holds
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
  *(Amended 2026-07-18 — §11 Y-14; reworked same day at the blind
  spec review: the launcher gains a **readiness wait**, closing the
  cold-start 403 race that idle-exit turns from once-per-boot into
  routine: `systemctl --user start` returns when the process
  spawns, BEFORE the server process mints and writes the new
  per-start token (app build code writes it, then uvicorn binds) —
  a launcher that reads the token file immediately opens a
  stale-token URL and lands on the 403 page. Pinned sequence:
  snapshot service state and current token bytes BEFORE starting;
  if the snapshot state was **anything other than `active`**
  (inactive, failed, activating, deactivating — a click landing in
  an idle-exit shutdown drain is a cold start too) AND the start
  command succeeded, poll inside one ≤5 s budget for BOTH: token
  content that differs from the snapshot (or first appears), THEN a
  successful TCP connect on `127.0.0.1:<port>` (the token is
  written before the bind — freshness alone can release into
  connection-refused). An unchanged token WITH a successful connect
  also counts as ready (delta R2, the double-click case: a second
  launcher snapshots the already-fresh token and would otherwise
  burn the full budget waiting for a change that never comes). On
  timeout, proceed with whatever is
  readable — the existing 403-page-names-the-launcher degradation,
  not a new failure mode. A warm (`active`) service skips the wait
  entirely; systemd-absent hosts never enter it.)*
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
- **Start is non-blocking** *(added 2026-07-18 — feedback round 2
  item 1; §11 Y-15; reworked the same day after the amendment's own
  blind spec review returned NOT SOUND — findings folded in place,
  the register entry carries the tally. The awaited-first-turn shape
  this replaces was a build convention — pane.py's own concurrency
  note, citing the verb runner's POST-awaits-completion pattern —
  never a spec pin; the live trial proved it wrong for a 30–90 s
  first turn: the SSE deltas published the whole time, but the
  client had no pane region to receive them until the POST
  returned)*. The **start POST** returns as soon as the session
  exists: the split renders in a **starting** state carrying a Y-9
  plain-words line ("Starting the conversation…" — written for the
  decision-maker, never a spinner alone), and the first turn drains
  in a **background task** on the server's event loop. **Claim
  before anything slow** (review F5): the live-slot guard and the
  live-slot assignment are ONE synchronous step — no `await` between
  them; context building, engine construction, and the drain all run
  after the claim (the one-live-session invariant must never depend
  on request-arrival luck). For the START POST specifically, the SSE
  pane envelopes (`pane_delta`/`pane_block`/`pane_tool`/
  `pane_result` — §3, 10 §1) are the transport for first-turn
  content — the start response carries the starting markup those
  handlers target, never transcript text; `send`'s existing
  authoritative-swap semantics (its POST response renders the
  post-turn state) are explicitly untouched (review F6). The
  starting line clears at the first streamed frame (review F7).
  **Completion delivery** (review F1, the blocker: every completion
  artifact — result footer, error strip, `r` retry, validate badge —
  is server-rendered swap content that no longer rides the start
  POST; app.js had deliberately ignored `pane_result`, so without
  this pin a failed background first turn is the silent wall
  reborn): on `pane_result`, the client re-fetches the session's own
  **pane panel GET** (`…/pane/panel` — both route families have
  one; the pane region carries its own panel URL as a data attribute
  the handler reads, never scraped from `hx-post` values — delta R3)
  and swaps the pane region; that authoritative server-rendered swap
  IS the completion mechanism, for the clean AND error legs alike,
  and is also the cleanup bound on any append-vs-swap residue,
  including a tab that reloaded mid-drain (F7). The handler
  suppresses (or defers) the swap while the pane region shows the
  armed interrupt prompt or holds a focused non-empty send input —
  the same hazard class §4.5's `[data-armed]` belt covers: never
  clobber a human mid-decision or a half-typed draft (delta R1). To
  make the completion hold on every path, the background drain
  wrapper's exception leg publishes `pane_result` too — an engine
  that dies without emitting its own result still produces at least
  one completion push; the swap is idempotent and side-effect-free,
  so a wrapper-leg publish after a handled Result is harmless
  (delta R2). No new envelope types. **Failure surfacing unchanged in substance**: an exception
  in the background drain lands the session in the SAME ENDED/error
  state the blocking path produced (§5's engine-failure row: error
  strip + `r` retry; cap statuses keep their wording), and the §4.5
  clear-set's proposing-session-error leg stays anchored to drain
  completion — the moment that, in the blocking design, coincided
  with the POST return and now stands alone. **Drain-task hygiene**
  (review F3) — both halves pinned: teardown (verb-dispatch
  interrupt, forced start, `q` close, idle teardown) cancels-or-
  awaits the background drain task BEFORE returning, so no successor
  session can claim the slot while a predecessor's drain can still
  run; AND, belt on that ordering, an **identity guard** — a drain
  whose session object is no longer the manager's current one
  publishes nothing and clears nothing (the `r`-retry same-key
  window must never let an orphaned drain wipe a successor's
  proposal slot or spray stale SSE into the new session's pane).
  **Turn serialization**: a second start POST during the background
  first turn takes the existing state machine's answer — same
  session key = "resumed" no-op re-rendering the current split
  (never a second engine); different key = the standing armed
  interrupt prompt. Mid-turn `send` is a NEW build obligation this
  amendment creates, stated as such (review F2 — the pre-Y-15
  machine had no guard because a blocking start made the window
  structurally unreachable): `send` dispatches an engine turn ONLY
  at awaiting-input; in any other state it re-renders the current
  split without touching the engine — ONE in-flight turn per
  session, ever; named test. **Esc during starting** (review F4): an
  interrupt arriving in the pre-connect window must still terminate
  the turn PROMPTLY once the engine becomes interruptible — the
  build carries an interrupt-requested latch the drain honors at its
  first post-connect boundary, or escalates through teardown; the
  mechanics are the build's, the promptness obligation is this pin;
  named test. **Not changed**: one live session server-wide (below);
  interrupt-first at verb dispatch (§3 P1-4); the Esc ladder
  (below); the Y-14 idle predicate already counts starting/streaming
  as INTERRUPTIBLE work-in-flight, so a background first turn blocks
  idle exit by the existing leg (§3); the ephemeral transcript;
  `send` at awaiting-input; the post-session `proposal validate`
  obligation, which fires when the background drain's clean result
  lands.
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
  call; escalate to terminating the SDK client/subprocess after
  **1 s** grace, kill after **2.5 s** — ONE deadline anchored at the
  keystroke, every wait derived from it). *(Tuned 2026-07-18 from
  2 s/5 s — the T-E follow-up: the SDK fast-interrupt is ineffective
  on the subscription-auth streaming path, so the ladder is the
  COMMON Esc path, not the emergency path. Common-path worst case
  ~2.7 s; arithmetic ceiling = ladder (≤ 2.5 s, deadline-shared) +
  bounded close (≤ 2.5 s) = **5 s** — §3's verb-dispatch "≤ 5 s
  worst case" pin holds by construction. Force-close was live-proven
  non-destructive at T-E — files are truth. Same amendment, caller-
  side bounding pins (honest premises, per the gate review: the
  installed SDK already bounds these internally at ~60 s / ~20 s —
  this tightens them to keystroke scale and fixes the semantics):
  the SDK `interrupt()` ack gets the grace bound (cancel-on-timeout
  is safe there — the abandoned control request is moot once close()
  disconnects); `close()`'s `disconnect()` gets the kill bound as
  **shield-and-abandon, NEVER cancel** — a raw cancellation pierces
  the SDK transport's shielded SIGTERM/SIGKILL escalation (the
  transport's own docstring carries the caveat) and would leak a
  live wedged CLI child while the caller reports "torn down"; the
  shield keeps the caller bounded while the SDK finishes killing the
  subprocess in the background, with completion logged. Bounded-per-
  callee caveat, recorded: `wait_for` waits for the callee's
  cancellation to complete, so a callee that suppressed
  CancelledError could still stall — a per-callee contract the
  installed SDK honors, not a structural guarantee. The Y-14 idle
  monitor awaits this exact path in `teardown_parked`.)*
  Interrupting never discards file changes already written (files
  are truth; the re-render already showed them).
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
  full-file scan regardless (P2-7 — the no-bypass backstop).
  *(Dated acceptance 2026-07-18 — §11 Y-14: the badge map is
  in-memory and does not survive an idle exit, which Y-14 makes
  routine rather than rare; the badge is advisory UI, and P2-7's
  in-verb scan is the enforcer that survives every restart.)* The verb
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
`cli`, default `sdk`; `cli` → exit "engine not built — 09 §4.1") ·
`SELF_LEARN_UI_IDLE_EXIT_SECONDS` *(added 2026-07-18 — §11 Y-14:
idle self-exit window, seconds; default `600` under the systemd
unit, unarmed in a foreground `serve` unless set explicitly; any
value ≤ `0` disables self-exit — pinned at the review, negatives
never error)* · `SELF_LEARN_UI_MONITOR` *(added 2026-07-18 —
feedback round 2 item 6: launcher-only — consumed by
`self-learn-ui-open`, never by the server; the same X-1 posture as
`SELF_LEARN_UI_BROWSER`. Names the monitor the launcher ensures the
app window onto after focus/launch: focuswindow by address, then —
only after `activewindow -j` confirms OUR window actually holds
focus (a JSON read, never an exit-code branch; the review's
stale-address gate: a vanished window must not move whatever the
user has focused) — `movewindow mon:<name>`, skipped when `hyprctl
clients -j`/`monitors -j` already place it there; a fresh window is
polled for ≤5 s. Unset
= compositor placement (today's behavior, zero new dispatches);
hyprctl absent or the window never appearing = silent degrade. The
value is host-specific and wired host-side after merge — never
hardcoded in the product)*.
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
  *(Amended 2026-07-18 — feedback round 3 item 3; §11 Y-18:)* plus
  `rehome` (required `to` — a **registered project**, named by path or
  bucket slug; the confirm rebuilds argv from the slot as
  `rehome <record-id> --to <server-resolved-path>` — 02 §2 pins the
  verb). Y-11 consistency, stated so the exclusion list stays honest:
  `rehome` may only name a target **already in hosts.yaml**, so the
  agent widens no read scope and mints no write target — exactly the
  two things the `host add` exclusion protects; an unregistered
  umbrella project stays a fact the agent tells the human, never a
  registration path.
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
  itself or ask the human) and renders nothing. *(Amended 2026-07-18 —
  feedback round 2 item 3, narrowing the same-day F9 clause below:
  `dest` is also **scope-checked at intake** against the CLI's own
  scope rules — a `skill-md` proposal on a non-skill record refuses
  with a teaching string naming the record's scope and the valid
  alternatives, so an armable-but-impossible proposal never renders.
  Other structural validity — e.g. a hook dest without stored script
  bytes — stays the verb's to enforce.)* *(Amended 2026-07-18 —
  feedback round 3 item 3; §11 Y-18, following the same round-2
  intake-teaching precedent:)* `to` only applies to `rehome` and is
  validated **at intake** against the registered-project set
  (hosts.yaml, the CLI's own authority): an unregistered target
  refuses with a teaching string naming the human's register
  affordance ("the human can register it first — the Register
  control / `self-learn host add <path>`"); `to` naming the record's
  **current** bucket refuses ("already lives there — nothing to
  move"); a non-project-scoped record refuses (M1 is
  project→project only, per 02 §2's verb pin). The resolved target
  is a **server-truth field** on the bar — the handler stores the
  hosts.yaml path it resolved, never the agent's raw string.
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
  clears the slot) · server restart. *(Extended 2026-07-18 — §11
  Y-18; reworked at its own blind-review fold, F2/F5:)* · the record
  leaving its **bucket** (a CLI-side `rehome` while a proposal is
  WAITING **or ARMED**). Detection is the same **render/arm-time
  staleness checks** as resolved-elsewhere — never a watcher hook:
  the ledger watcher does not re-scan bucket sets mid-run, and a
  rehome that CREATES its destination bucket fires only source-side
  file events — **extended to compare the record's current bucket
  (`locate_record`) against the slot's captured bucket**. Both the
  ARM route and the CONFIRM route make that comparison, and on
  mismatch the outcome is **clear the slot + a plain-words notice**
  (the resolved-elsewhere shape) — never a *disarm*, which is pinned
  to mean the bar survives back to WAITING: a surviving waiting bar
  would carry exactly the stale bucket facts this leg exists to
  kill, so the proposal dies and the agent re-proposes against the
  record's new home *(delta fold F10)*. The
  confirm-side check is load-bearing, not belt: the CLI verbs locate
  records across ALL buckets, so without it Enter on a stale armed
  bar would execute the verb against the record in its NEW bucket —
  compiling into a different project's canon than the bar the human
  read. Why this leg is new at all: `rehome` is the FIRST mechanism
  that makes a pending record's bucket facts mutable — every earlier
  staleness check could safely assume a pending record stays where
  it was validated. Page navigation does NOT clear
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
  never pretends otherwise). *(Added 2026-07-18 — §11 Y-18:)* a
  `rehome` bar's target joins the server-truth set (resolved
  against hosts.yaml at intake), and its leading line is Y-9
  domestic — "move this lesson to the *keyboards* project" — with
  the resolved path as trailing metadata beside the id. ⟨name⟩ is
  the registered path's **basename**, pinned (F7): slugs are
  unreadable, and when two registered projects share a basename the
  trailing resolved path is the disambiguator the human reads. The waiting bar is NOT `[data-armed]`:
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
| Verb exits non-zero (dirty target, push failure, scan refusal…) | Error strip with the verb's stderr verbatim; state re-read from files; nothing optimistic. The verb's messages are the contract — the server adds no interpretation. *(Narrow dated exception, 2026-07-18 — feedback round 3 item 1, §11 Y-16: the host-add confirm leg ONLY leads with a plain-words sentence (Y-9) and demotes the stderr to a secondary detail line — still rendered, still verbatim, visually secondary; and its error rendering PERSISTS across refresh re-renders until the user dismisses or re-arms. Every other verb stays verbatim-first.)* |
| `proposal validate` scan hit at session end | Exit-code discrimination (0/1/2); error strip shows the verb's report verbatim; record/proposal stay as written (report-never-delete); "scan-blocked" badge until a re-validate exits 0. |
| Record resolved elsewhere mid-view | SSE fires → "resolved elsewhere" banner → Bucket page; if under active iteration, the pane session is interrupted first (§3/P3-8). |
| Record file fails to read or parse — **any** failure class: I/O error (vanished mid-render, permissions), undecodable bytes, frontmatter parse error, or schema/section validation failure | Detail renders a **degraded record view** with pinned salvage layers: **id and path always; frontmatter fields only when the mapping parses; the raw body text verbatim as preformatted text; never section-parsed decision content** — under a plain-words notice ("This record's file could not be fully read."); **never a 500**. Action bar stays rendered; the verbs remain the enforcers (a verb that cannot parse the record refuses with its own message, surfaced per the verb-error row; builder note: for non-RecordError corruption some verbs today traceback rather than refuse cleanly — accepted under that row's verbatim-stderr posture). Front/Bucket lists skip-and-log the unreadable record and show a one-line count ("1 record could not be read") **sourced from `status --json`'s `unreadable` field (dated 08 §1 edit, same build) — never server-side ledger derivation (§2.1)**. **Catch-set pin (spec-gate fold):** the UI's `read_record` and the CLI's `_load_pending`/`unparseable_pending` today catch only `RecordError`; the build widens both to also catch `OSError`/`UnicodeDecodeError`/YAML parse errors — the CLI half is an 08-owned change riding this row. *(Dated addition 2026-07-18, maintenance round FW-18; blind spec gate NOT SOUND → folded: trigger widened to any read/parse failure (F4), salvage layers pinned (F3), catch-set widening named (F1), count routed through 08 §1 (F2), "always implied" softened — the never-500 posture was implied, the degraded-render behavior is new and specified here (F5).)* |
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

*Amended 2026-07-25 (`drafts/ui-inflight-feedback-spec.md`, §7.1 —
gated SOUND, builder-landed):* **perceptibility moves into CI; taste
stays human.** The ratified split above held CI at the DOM/existence
level and left "is this perceptible at all" to human acceptance
trials — and that is exactly where a shipped defect class lived
(disabled controls with no visible cue, a bulk-progress emitter that
narrated nothing, ten keymap actions no test had ever pressed): no
suite could have caught them because none asserted rendering.
`page.locator("body").aria_snapshot()` inequality is now the CI
oracle for "did the perceptible state change", used alongside
targeted `to_have_css` checks where the oracle's own measured blind
spot (opacity/colour/cursor) applies. **This is narrower than it
sounds:** perceptibility is asserted in CI only for the feedback this
one unit introduced (in-flight disabling, the applying/bulk-progress
strip, the two never-tested banners) — roughly twenty pre-existing
feedback sites (`drafts/ui-inflight-feedback-spec.md` §9.1) remain
unasserted, and colour, opacity, contrast, geometry, occlusion, and
`text-transform` casing stay outside the automated oracle entirely
(measured: `aria_snapshot()` and `is_visible()` are both blind to
`opacity: 0`). Visual polish
proper — "does it look good" — is unchanged and stays a human
acceptance item (`10 §4`). Full reasoning and the rejected
computed-style-digest alternative: `03-decisions.md` S-20.

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
  **Amended 2026-07-18 (feedback round 3 items 1+2):** the confirm's
  error leg and the arm state gain their own pins at Y-16 (persistent,
  plain-words failure rendering — a narrow dated §5 exception scoped
  to this leg) and Y-17 (server-derived `needs_init` banner variant
  arming `host add --init`); the build pins above otherwise stand
  unchanged.
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

- **Y-14 · Idle lifecycle — resident while in use** *(added
  2026-07-18; the queued idle-lifecycle refinement on the ratified
  roadmap: UI-completion → packaging, Go parked. Reworked the same
  day after its own blind spec review returned NOT SOUND — 4 MAJOR
  / 2 MINOR, all folded: the awaiting-input hole, the request-clock
  stamp point, the honest casualty list, the systemd-absent arming
  rule, the not-`active` cold-start condition, the TCP readiness
  probe)*. The user's requirement, near-verbatim: the server should
  "live and die appropriately for users so they don't have to
  manage it themselves". Decisions of record: **(1)** the server
  self-exits cleanly on a five-legged idle predicate (normative
  text at §3's server bullet: no SSE subscribers, no in-flight
  requests, runner between verbs, no INTERRUPTIBLE pane session,
  request-completion clock aged past the window); the window is
  `SELF_LEARN_UI_IDLE_EXIT_SECONDS` (default 600; ≤0 disables —
  §4.4); **(2)** exit mechanism is uvicorn's ``should_exit``
  flag → graceful shutdown → a genuine return → exit 0 — no new
  systemd semantics: `Restart=on-failure` already reads a clean exit
  as "stay down" and crash-restart is unchanged *(corrected
  2026-07-18 at the U13 live trial — the drafted SIGTERM-to-self
  exits 143 via uvicorn's capture_signals re-raise and gets
  RESTARTED; see §3)*; **(3)** the launcher — already
  the only start path a user touches (notification click,
  `.desktop` entry) — is the resurrection path, and gains the
  readiness wait (§3's launcher bullet: fresh token THEN TCP
  connect, cold ⟺ snapshot state not `active`), which also closes
  a PRE-EXISTING cold-boot 403 race the resident posture had been
  masking; **(4)** systemd **socket activation was considered and
  rejected**: it does not fix the token race (the token is written
  by app code, not handed off with a socket), adds unit plumbing to
  a file users install by symlink, and the launcher already owns
  cold-start; **(5 — the review's F1 judgment call, resolved toward
  the user's requirement):** only an INTERRUPTIBLE session
  (starting/streaming/interrupting) blocks exit; a session parked
  at awaiting-input with zero clients for the full window is torn
  down through the standard teardown before exit — 09 §4.2 already
  pins the transcript as ephemeral, and the alternative (any
  non-ENDED session blocks) silently re-creates resident-forever
  for anyone who ever iterates and closes the window without `q`,
  which is the most common walk-away path; **(6)** self-exit arms
  only under the systemd unit (`INVOCATION_ID` detection) —
  foreground `serve` on systemd-absent hosts (10 §5) has no
  resurrection path and stays resident unless the env var is set
  explicitly. Substrate: no CLI changes, no storage changes; one
  env var, one unit-comment re-word, launcher edit, ~60 lines of
  server code (10 §3 U13).

- **Y-15 · Non-blocking pane start** *(added 2026-07-18 — feedback
  round 2 item 1, `feedback/2026-07-18-ui-feedback-02.md`; own spec
  gate before build per the standing discipline. Reworked the same
  day after its own blind spec review returned NOT SOUND — 1
  BLOCKER / 3 MAJOR / 4 MINOR / 1 NIT, all folded in place; the
  review verified the resumed-no-op, armed-prompt, Y-14-leg, and
  validate-timing claims of the first draft as honest — those
  stand)*. The user's words, live-hit on the bucket pane: *"'open
  bucket chat' doesn't seem to do anything … there was no indication
  that anything was happening after i clicked the button. it should
  pop open the interaction window and let it have some kind of
  loading message or stream the response or something."* Root cause,
  verified in code: the pane manager's start awaited the ENTIRE
  first agent turn (30–90 s real model) and the split only rendered
  from the POST response — the `pane_*` SSE frames published the
  whole time into a client with no region to receive them. Decisions
  of record: **(1)** the start POST returns immediately with the
  split in a **starting** state (a Y-9 plain-words line, never a
  bare spinner); the live-slot claim is synchronous — no `await`
  between guard and assignment (F5); **(2)** the first turn drains
  as a server-side background task; the existing SSE stream carries
  first-turn content — no new envelope types, no protocol change —
  scoped to the START POST only; `send`'s authoritative-swap
  semantics untouched (F6); **(3 — the review's F1 BLOCKER,
  resolved):** completion delivery is the `pane_result`-triggered
  re-fetch of the session's pane panel GET, whose server-rendered
  swap is authoritative for clean and error legs alike (app.js had
  deliberately ignored `pane_result`; without this, the error
  strip / `r` retry / result footer / validate badge — all POST-swap
  content — never arrive, and a failed background first turn is the
  silent wall reborn); the drain wrapper's exception leg publishes
  `pane_result` so the swap fires on every completion path; the
  same swap bounds append-vs-swap residue, incl. a mid-drain reload
  (F7); **(4)** a background-drain exception lands the SAME
  ENDED/error state the blocking path produced (§5 row unchanged),
  with the §4.5 clear-set's error leg anchored at drain completion —
  in the blocking design that moment coincided with the POST return;
  it now stands alone; **(5)** drain-task disposal pinned (F3):
  teardown cancels-or-awaits the background drain before returning,
  AND an identity guard keeps a no-longer-current drain from
  publishing or clearing against a successor (the `r`-retry same-key
  window); **(6)** turn serialization: same-key start = "resumed"
  no-op and different-key = armed prompt (the existing machine's
  answer, stated); mid-turn `send` = no engine dispatch — a NEW
  build obligation, stated as such (F2: the old machine had no
  guard; the blocking start merely made the window unreachable) —
  named test; Esc during starting must terminate the turn promptly
  once the engine becomes interruptible (F4) — named test; **(7)**
  explicitly NOT reopened: one live session server-wide,
  interrupt-first, Y-14's INTERRUPTIBLE idle leg (a starting/
  streaming background drain blocks idle exit), awaiting-input
  `send` semantics, the ephemeral transcript. **Re-trial set (F8)**,
  named here for the live gate: **(i)** bucket-chat button → split
  renders < 1 s and the stream fills live (browser); **(ii)** forced
  background-drain failure → error strip + `r` retry render at
  completion; **(iii)** Esc during starting terminates the turn
  promptly. Delta-gate residuals folded same day (SOUND verdict,
  three one-sentence pins now in §4.2's completion block): the
  completion swap defers around an armed prompt or a half-typed
  draft (R1), is idempotent/at-least-once (R2), and reads its panel
  URL from the pane region's own data attribute (R3). Consuming
  sections: §2.2 (bucket pane), §2.4 (iterate split), §4.2
  (normative start contract); 10 §1's SSE row carries the build-plan
  side. Substrate: no CLI change, no SSE-protocol change — server
  code, templates, and app.js's `pane_result` completion handler
  only.

- **Y-16 · Failed registration must be readable — persistent,
  plain-words error** *(added 2026-07-18 — feedback round 3 item 1,
  `feedback/2026-07-18-ui-feedback-03.md`; live-hit: the user's
  keyboards registration — Confirm → a red strip flashed too fast to
  read → the bar cycled back to the unregistered notice. Reworked
  the same day after the amendment's own blind spec review returned
  NOT SOUND — findings folded in place: the reload-chokepoint defer
  (F3), the confirm-in-flight leg + the ordering ruling (F4), the
  armed-bar release rule (F5), the corrected required copy (F2),
  the deliberate staleness pin (F9). The review independently
  CONFIRMED the code-read wipe diagnosis below — that part
  stands. Delta residuals folded same day: the twice-corrected
  copy (F11), the widened staleness pin (F12).)*. Two defects,
  two pins:
  **(1) Persistence.** The failed host-add confirm's error rendering
  PERSISTS until the user dismisses it (an explicit dismiss
  affordance on the error rendering — reusing the existing disarm
  route's notice re-render, no fourth route) or re-arms
  registration. The wipe mechanism must be PINNED EMPIRICALLY at
  build — reproduce the vanish browser-level and log the finding in
  10's appendix BEFORE fixing. The code-read prime suspect: the
  runner's forced post-verb refresh push fires on success AND
  failure (10 §1 "forced push after every verb return"), `host add`
  argv carries no `lrn-` id so the push scope is `front`, and
  app.js treats a front-scoped `refresh` as a broadcast answered
  with a full `window.location.reload()` — re-rendering the bar
  from files and erasing the just-swapped error partial. The second
  candidate — the any-key-disarms keyup — reads as implausible in
  code (the error leg renders `data-armed="false"`), but the brace
  is cheap and one mechanism covers both. **The defer lives at the
  client's single `reload()` CHOKEPOINT** (F3): every
  client-initiated full reload routes through one function and
  defers there, so ALL present and future reload paths are covered
  structurally — at fold time three exist (the SSE `refresh`
  handler, the 10 s poll fallback, and the `pane_proposal`
  handler's reload legs — the host-add bar renders on both pages
  where proposal reloads fire, and the `[data-armed]` belt does
  NOT protect the error leg, which renders unarmed); that
  enumeration is informative, never normative — the chokepoint is
  the pin. The defer predicate has three legs; the reload defers
  while ANY holds: **(a)** a **`[data-verb-error]`** element is in
  the document (the error rendering carries the marker); **(b)** a
  verb-confirm POST is in flight on the page — a client-side flag
  set at form submit, cleared at swap settle — because the runner
  queues the failure push BEFORE the confirm route renders the
  error partial, so the SSE frame can beat the htmx swap and a
  marker-only predicate re-creates the original symptom (F4);
  **(c)** any `[data-armed="true"]` bar exists — releasing on
  re-arm would reload over the fresh armed bar, the exact
  never-clobber-a-human-mid-decision hazard of the Y-15 delta-R1
  precedent this extends (F5). **Deferred, not dropped**: the
  reload fires when no leg holds — on dismiss, or after an armed
  bar resolves. Deliberate staleness pin (F9; widened at the delta
  review, F12 — the pin's scope is the PREDICATE, not just the
  error): legs (b) and (c) defer with no error displayed at all,
  and leg (c) is a page-global behavior change stated here
  explicitly — ANY `[data-armed="true"]` bar, for any verb on the
  page, now defers ALL broadcast reloads (pre-fold, only the pane
  completion swap deferred around armed). While any leg holds, the
  page may go stale against the files — accepted, including the
  abandoned-tab bound: a tab left with an armed bar defers
  indefinitely (nothing times an armed bar out). Acceptable
  because files stay truth, every hold has a user-reachable
  release, and no inter-leg deadlock exists — (b) clears at swap
  settle on its own, dismiss removes (a), disarm-or-resolve
  removes (c); the released reload re-syncs.
  The server-side push itself is
  UNCHANGED — §5's "state re-read from files; nothing optimistic"
  stands; the exemption is the client's render of the error, never
  the push. Honesty pins: the error is render-state, not
  server-held state — navigating away discards it (deliberate; no
  error slot to leak); and every OTHER verb's error strip plausibly
  dies to the same reload path — the chokepoint defer covers them
  for free and is
  encouraged, but only the host-add leg gets fixtures this cycle
  (M1-lean; a broader sweep is its own item if it recurs live).
  Testable: T-A asserts the rendered error partial (marker +
  content + dismiss); the reload-defer is proven at the U14
  browser-level re-trial (the error survives a forced refresh push
  while rendered), and the empirical wipe-pin must rule EXPLICITLY
  on the SSE-frame-vs-swap ordering (the F4 pre-render race)
  before the defense is accepted.
  **(2) Plain words (Y-9) — the NARROW dated §5 exception.** The
  failed-registration leg leads with a human sentence; required
  content: **registration did not complete** (exact copy the
  builder's — the content is binding, the wording is not; twice
  corrected at review: the first draft's "nothing was changed" is
  FALSE in the Y-17 half-init residue and the HalfWrittenError leg
  (F2), and the first fold's "the project was not registered" plus
  its "you can try again" are BOTH false in the HalfWritten leg —
  hosts.yaml on disk already contains the entry, `host_registered`
  reads true on the next render, and the idempotent re-add
  early-returns without repairing the missing commit (F11).
  "Did not complete" is true in every failure leg; the demoted
  stderr detail carries the state facts and the repair —
  HalfWritten's own message already names both). The
  CLI stderr renders BELOW it as a secondary detail line — still
  verbatim, still visible without interaction, visually demoted.
  Why the exception is justified: registration is the surface's
  ONBOARDING moment — the person it renders to has, by
  construction, not yet integrated this project into the system,
  and "canon hosts must be committable (doc 13 §4 two-phase
  routing)" is system vocabulary aimed at spec readers, not at them
  (the Y-9 jargon failure's third live instance). §5's
  verbatim-first pin stands for every other verb: those stderr
  lines name records and verbs the adjudicating user is already
  holding. Scope: the host-add confirm leg ONLY; the §5 row
  carries the dated exception note. Substrate: no CLI change;
  consuming code is routes.py's host-add triple,
  `host_add_bar.html`, and app.js's reload paths. Build unit:
  10 §3 U14.

- **Y-17 · Git init on register, disclosed — `--init` lives in the
  CLI** *(added 2026-07-18 — feedback round 3 item 2; the user's
  ruling verbatim: "make it clear that a git init will be performed
  when a user chooses to register a new project that isn't already
  a repo through the UI". Reworked the same day after the
  amendment's own blind spec review returned NOT SOUND — findings
  folded in place: the F1 consent invariant (BLOCKER), the F6
  refusal ordering, the F7 zero-commit residue, the F8 file-path
  refusal. Delta residuals folded same day: the honest
  client-supplied-bit sentence (F10), the one-directional
  divergence pin (F13))*. The committability invariant stands —
  canon writes are commits; audit, rollback, and recompile all diff
  against git (13 §4) — and the flow absorbs the gap instead of
  refusing at the human. Decisions of record:
  **(1) Where the init lives: the CLI.** `self-learn host add
  --init <path>` — the verb performs `git init` + an empty root
  commit at the exact path BEFORE its existing validation, which
  then runs unchanged. Grounds: the UI stays a thin caller — only
  the verb writes; a server-side `git init` pre-step would mint a
  second repo mutator outside the verb seam and split the edge
  cases across two codebases; terminal users get the same
  affordance for free; validation keeps its single enforcement
  point. Rejected: the UI-side pre-step (above), and a standalone
  init verb (two arms for one human decision).
  **(2) The predicate is "repo ROOT", CLI-owned, imported.** One
  new CLI-owned helper decides both sides of the seam: is the
  exact resolved path itself a git repository root (`git -C <path>
  rev-parse --show-toplevel` resolving to the path itself)? The
  existing is-inside-work-tree check answers TRUE for a path
  swallowed by a PARENT repo's work tree and cannot carry this
  decision. The ui package imports the helper (the
  `canon_read_roots()` posture — P2-4, never a second
  implementation).
  **(3) `--init` semantics — the matrix (each row a named CLI
  test):** ordering first (F6): the pure-argument, read-only
  refusals — kind validity, ledger-home existence — run BEFORE the
  init leg, exactly as they run first today (an invalid kind must
  never leave an initialized repo behind); path validation and the
  already-registered idempotency stay after it · path IS already a
  repo root — a ZERO-COMMIT repo counts as a root (F7) → no-op,
  the add proceeds normally (refusal rejected deliberately: an
  arm→confirm race — the path becoming a repo between the two
  POSTs — must not fail the confirm; no-op also preserves `host
  add`'s idempotency) ·
  path exists as a directory and is NOT a repo root — INCLUDING
  inside another
  repo's work tree → `git init` at the exact path + an empty root
  commit (pinned subject: `self-learn: init for host
  registration`), then normal validation + add; nested repos are
  acceptable and intended (the live case: `~/repos/keyboards`
  around `zmk-config-offsetkey/` — git treats the inner repo as an
  untracked boundary), and init-at-the-exact-path is what makes
  registration mean "THIS path is the committable canon host",
  never the accident of a parent repo · path does not exist OR is
  a regular file → clean refusal in the verb's own words, never a
  fall-through to raw git stderr (F8) — `--init` initializes
  existing directories only; it creates nothing ·
  root-commit failure (unset git identity is the realistic case) →
  non-zero exit with git's stderr and NO hosts.yaml mutation;
  honesty pins: init is not transactional with the add — a failed
  add after a successful init leaves the path initialized, which
  is harmless, and the retry no-ops the init leg; further (F7),
  since a zero-commit repo counts as a root, the root commit is
  **best-effort-ONCE** — after a failed empty commit the retry
  skips the init leg entirely and the pinned subject may never
  exist for that host; tests must not assert its existence on the
  retry path · without
  `--init`: behavior byte-unchanged.
  **(4) UI side (Y-11's posture holds throughout).** The arm route
  derives `needs_init` SERVER-side via the imported repo-root
  helper on the server-derived path — never a client field. When
  `needs_init`: the ARM banner carries, beside the existing consent
  consequence, the disclosure sentence — required content: **a new
  git repository will be created at <path> (`git init`) as part of
  registering** (plain words, Y-9; exact copy the builder's) — and
  the displayed command line shows the real argv
  (`self-learn host add --init <path>`). **Consent invariant (the
  review's F1 BLOCKER, resolved): the executed argv includes
  `--init` only when (a) the ARM rendering actually displayed the
  init disclosure AND (b) the confirm-time re-derivation still
  holds; ANY mismatch in either direction runs PLAIN `host add`.**
  Both race directions pinned: becomes-repo (disclosure was shown,
  path a root by confirm) → `--init` dropped, the plain add
  registers; goes-stale (NO disclosure shown, path a non-root by
  confirm) → the plain add runs, the CLI's committability refusal
  flows into Y-16's error leg, and the user re-arms and NOW sees
  the disclosure — never a silent init, because a confirm-only
  re-derivation would execute an argv the human never read
  (what-you-read-is-what-runs, the same doctrine the proposal
  confirm pins). The becomes-repo direction does run LESS than
  the human read (`--init` displayed, plain add executed) — that
  divergence is deliberate and ONE-directional (delta review
  F13): the executed argv may be WEAKER than the displayed one,
  never stronger; weaker-than-read is the only direction read-run
  divergence is ever permitted. Statelessly operationalized: the
  arm-with-disclosure rendering posts through its own confirm
  variant — a separate confirm route or a server-rendered marker
  field, builder's choice; the path itself stays server-derived
  either way (Y-11 posture), and because the re-derivation gates
  leg (b), a stale or forged marker can never CAUSE an init on a
  repo-root path — the worst mismatch outcome is a clean refusal.
  The argv is
  otherwise unchanged. Client-supplied surface, stated honestly
  (delta review F10 — the previous "nothing but the return-page
  record id" was false under the marker-field choice): the client
  supplies the return-page record id PLUS, on disclosure arms
  only, the one disclosure bit — as the marker field or as the
  disclosure confirm route, whichever operationalization the
  builder picked (the route choice carries the same one bit).
  Bounded: that bit can only ever WEAKEN execution toward plain
  `host add` / a clean refusal, never strengthen it — leg (b)'s
  re-derivation gates every init. When the path is not a repo root
  because a PARENT repo swallows it, `needs_init` is TRUE — the UI
  discloses and inits the exact path rather than silently
  registering a host whose canon commits would land in the parent.
  Substrate: one CLI flag + one CLI helper (cli package, built
  with the U14 cycle; 13 §3 carries the CLI-side dated mirror);
  the consent line is unchanged. Open point, recorded not pinned:
  terminal `host add` WITHOUT `--init` on a path inside a parent
  work tree still passes today's is-inside-work-tree validation
  and registers a host whose commits land in the parent repo —
  tightening that predicate to repo-root is a separate CLI ruling,
  not smuggled in here.

- **Y-18 · Record re-home — verb, pane proposability, and the
  ancestor-project judgment** *(added 2026-07-18 — feedback round 3
  item 3, `feedback/2026-07-18-ui-feedback-03.md`; the round-3
  items-1/2 author's parallel worktree holds Y-16, Y-17, and U14, so
  this entry renumbered Y-17→Y-18 at its blind-review fold; its
  blind review returned NOT SOUND — 1 BLOCKER / 2 MAJOR / 4 MINOR /
  2 NIT, all folded in place same day)*. The user's
  directive, near-verbatim: *"anything that got registered as a
  lesson for zmk-config-offsetkey should have been registered under
  repos/keyboards… i'd like it to be a bit smarter about this and
  make choices the way that I would."* A record's bucket is fixed at
  capture time from the session cwd; until now neither the analyst
  nor the human could move it. Two halves, one dated set:
  **Mechanism (the verb — normative pin at 02 §2):**
  `self-learn rehome <id> --to <path-or-slug>` moves a PENDING
  record between **registered project** buckets. One `git mv` of the
  record file, one ledger commit
  (`self-learn: rehome lrn-… → projects/<slug>`), target bucket dirs
  + `meta.yaml` created if absent (13 §3); the record's bytes —
  including `scope: project` — are untouched. **Proposal siblings
  are swept, never moved** (decision of record): the analyst's
  destination judgment is bucket-relative and `record_sha` staleness
  cannot catch a move (the hash is of record content, which did not
  change), so a carried sibling would render an honest-looking stale
  card; the worker re-proposes in the new home — and the same commit
  sweeps any `merge-*.yaml` in the source bucket naming the record
  (fold F3: partial clusters are invalid, 02 §1; matches the
  resolution sweep). Refusals check
  **status, never existence** (locate/find machinery also sees
  `resolved/`): unknown id · not pending · target unregistered
  (refusal names `host add` as the human's repair) · target ==
  current bucket · id already present in the target bucket, checked
  before any bucket creation (fold F4 — collision guard) ·
  non-project scope (M1 is project→project only;
  user-scope target and cross-scope moves are dated future work).
  **Judgment (doctrine):** routing-doctrine §3 gains the
  ancestor-project clause — when a lesson's firing range extends
  beyond its repo, the nearest registered ANCESTOR project may be
  the narrowest surface that still fires, honestly applied; the
  analyst proposes a re-home naming the evidence (which trigger
  elements live outside the repo). One file teaches all three
  consumers (M2 worker, review skill, pane — the doctrine compile's
  mtime rule picks it up without code changes).
  Surface decisions of record, each dated here: **(1)** `rehome`
  joins the §4.5 closed proposable list with required `to`,
  validated AT INTAKE against hosts.yaml (the round-2
  teach-the-agent-at-proposal-time precedent) — Y-11's no-agent-path
  pin holds because only already-registered targets are nameable;
  **(2)** the waiting → `y` → Enter spine is byte-unchanged; the
  confirm rebuilds argv from the slot (`rehome <id> --to
  <resolved-path>`), target rendered as server truth, leading line
  Y-9 domestic ("move this lesson to the *keyboards* project" —
  ⟨name⟩ pinned as the registered path's basename, the trailing
  resolved path disambiguating shared basenames, fold F7);
  **(3)** **no human-side re-home control in M1** — agent-proposal
  plus the CLI verb are the two hands; a direct picker key would
  spend keymap surface on a rare act (the Y-11 no-affordance-key
  precedent) and needs target-cycling machinery v1 doesn't have.
  Revisit condition, auditable: an explicit user ask or a live
  session where the human wanted a move and no pane was open;
  **(4)** the §4.5 staleness machinery gains the bucket-change leg —
  WAITING and ARMED alike: the arm and confirm routes both
  re-compare the slot's captured bucket against the record's current
  bucket, and on mismatch **clear the slot + render a plain-words
  notice** — never a disarm, whose pinned meaning is
  survives-to-waiting, i.e. a bar still carrying the stale bucket
  facts (delta fold F10) — because rehome is the first mechanism
  that makes a pending record's bucket facts mutable (fold F2;
  detection is render/arm-time checks, never a watcher hook —
  fold F5);
  **(5)** NO proposal-YAML field — a batch-analyst re-home
  recommendation is prose in `rationale`/card, the mechanics are the
  pane path or the CLI (doctrine §5 pins it so M2 workers never
  invent a key). Post-confirm surface behavior: Detail keeps working
  (record lookup is id-based, bucket-independent) and both source
  and destination bucket pages refresh off the standard file events;
  after a confirmed rehome from a record pane, the existing
  `next_record_url` redirect resolves in the record's NEW bucket —
  intended, the human follows the lesson to its new home (fold F8).
  Substrate: no `list --json` change — bucket membership is already
  the pinned `bucket` field; build lands as 10 §3 U15.
- **Y-19 · Queue-walk trio — next-record prefetch, worker Force-run,
  first-row auto-select + focus** *(added 2026-07-18 — U16, sourced from
  `docs/specs/self-learn/research/2026-07-18-ux-enhancement-survey.md`
  §2 Q1/Q2 and §4's ranked shortlist items 1–3; three independent
  friction-only fixes shipped as one unit, none of them touching the
  arm→confirm decision gate)*. The survey's own frame, carried
  verbatim: reduce friction that is NOT the decision — navigation,
  staleness, waiting — never friction that IS the decision. All three
  items are client-presentational or CLI-triggering only; none spend
  model tokens, none change what a verb does, none narrow or widen the
  pane agent's authority.

  **(1) Next-record prefetch (survey P2b, shortlist #1).** Consumed at
  §3's Reads bullet (the mechanism) and §3's Refresh bullet (the
  staleness gate it rides). While Detail is open for record N, a
  background task warms record N+1's own read bundle — the exact
  record `next_record_url` would land on — so the post-confirm
  `HX-Redirect` hop paints without the subprocess-read stall every
  other Detail load pays. Zero model cost (CLI reads + a server render,
  never a `claude -p` turn). **CRITICAL staleness rule**, satisfied
  structurally rather than by any timer: the warm entry is stamped
  against the `RefreshHub`'s own generation counter — the SAME single
  publish point every refresh (a watchfiles-detected file change OR a
  completed verb) already funnels through (09 §3) — and is served ONLY
  when the CURRENT generation still equals the stamped one; any
  mismatch is an ordinary cache miss, never a stale render. Invalidation
  is **GLOBAL, not per-record**: ANY refresh (regardless of scope, and
  regardless of which record a completed verb touched) drops the
  entire warm cache — a single-slot cache, since the queue-walk only
  ever has one live "next" candidate. This is deliberate, not
  merely-simple: the survey's §2 Q3 P3a loaded-surface-budget
  indicator (tracked separately as Y-20/U17) means routing record X can
  change what an unrelated record Y's own rendering should show (a
  shared target surface's fill level), so a narrower per-record
  invalidation would be unsound the moment that datum exists — this
  item is built coarse from day one rather than needing a later
  widening. Y-14 interaction: the background task is one in-flight
  request, so it keeps the idle clock from aging only momentarily; a
  lost/never-completed warm entry on an idle-exit mid-prefetch is an
  ordinary cache miss, the same ephemeral-casualty posture §3 already
  accepts for the pane proposal slot and the scan-blocked badge map —
  never a correctness issue, since the generation gate is what proves
  correctness, not the cache's survival.

  **(2) Worker Force-run (survey P2a, shortlist #2).** Consumed at
  §2.1 (the Front-page button). The missing symmetric affordance to the
  miner's own Force-run — the survey's "single most surprising
  finding" was that the M2 proposal drafter, the thing the entire
  surface exists to adjudicate, had no UI trigger at all. `self-learn
  worker kick` (never `worker run`) is the exact verb: per 08 §7.1 it
  is itself a short-lived trigger that `setsid`-spawns the real
  analysis pass DETACHED before returning, so awaiting it in the verb
  runner never holds the server resident for the whole coalesce+analyze
  window the way `mine run`'s own Force-run genuinely does (12 §"R2":
  `mine run` "executes immediately", i.e. in-process, for its own
  button) — Y-14's idle-exit posture is respected by construction, not
  by a special case in this route. Double-click safety is CLI-owned
  (the kick's own flock + `worker.window` absorption — outcomes
  `spawned` \| `absorbed-window` \| `absorbed-race` \| `disabled`), not
  a client-side guard, mirroring the miner's own button, which carries
  none either.

  **(3) First-row auto-select + guaranteed focus (survey P1a, shortlist
  #3).** Consumed at §1's keyboard-accelerators bullet. On every list
  screen (Front, Bucket), the first actionable row carries the
  `.selected` cursor from load, not only after the first `w`/`s`
  press, and the content region is guaranteed programmatic focus on
  load and after every queue-walk hop — closing the "no visible cursor,
  no signal keys are live" soft dead-end the survey named (Y-9-adjacent:
  orientation, not decision content). Presentational only — no
  staleness surface, nothing here is a file read. The mechanism must
  never steal focus from a live pane's send input, nor fight the U14
  armed-bar/error-strip focus behaviors: it acts only when nothing has
  already, legitimately, taken focus (the untouched document default),
  and a pre-selected row is styled as a neutral cursor, never an
  endorsement — the record is merely oldest, not recommended (the
  survey's own steelman against this item).

  Substrate: no CLI change, no `list --json`/`status --json` shape
  change, no new SSE envelope type. All three items are UI-package-only
  (`plugins/self-learn/ui/`); build lands as 10 §3 U16.

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
- **Y-20 · Loaded-surface budget indicator at the routing decision**
  *(added 2026-07-18 — UX-enhancement survey item 4 / Q3 P3a; 08 §1
  `surface_fill` field; 10 §3 U17; 02 §4 cross-ref)*: at the moment of
  routing, Detail shows **in plain words how full the destination
  managed section already is** — "this skill-md section already holds
  8 of its 10 entries" — so the narrowest-surface bias (routing-doctrine
  §3), the entire basis of the routing decision, is a **visible fact**
  rather than doctrine the human is trusted to remember (RD §8: the card
  equips a human *deciding*). Decisions of record, each dated here:
  **(1) Data** — a new `list --json` **`surface_fill`** field (08 §1),
  CLI-computed at render by the compiler machinery through the read-only
  target resolver; the server displays it and derives nothing (the §2.1
  missing-field rule; the §5 CLI-is-enforcer posture). **(2)
  Granularity — every scope-valid candidate, but only the two CAPPED
  destinations carry a CLI datum.** Steelman for suggested-only: one
  target resolution + read, cheapest. Steelman for the full candidate
  set (chosen): the decision is a *comparison* — "route to the emptier
  surface" — and a budget that only lit the suggested destination would
  go dark exactly when the human weighs an alternative, so the Why
  region lists every candidate. **`skill-md` and `claude-md`** get their
  fill from `surface_fill`; **`reference` is EXCLUDED from the field and
  gets a template-static line** — "reference files have no cap — this is
  the overflow surface entries graduate into" (blind-review F1: reference
  has `target=None`, `compile_reference` is cap-free, and it IS the
  overflow sink the cap graduates into — no fill to probe; no builder may
  invent one). Cost: ≤2 capped targets per record, memoized per
  target-path per invocation (08 §1), no model tokens. Keys mirror the
  §2.3 scope filter, narrowed to the two capped destinations. **(3) Freshness — render-time, coordinated with U16, gated by
  a flag.** Fill is time-varying (it moves when *other* records route),
  so it is computed at render like `proposal_fresh`, never cached
  server-side — and behind the new opt-in **`list --json --surface-fill`**
  flag (default OFF) passed **only by the Detail render path**, so the
  Front/Bucket paints that never show fill pay nothing (blind-review F4:
  `_cmd_list` dumps all items eagerly on every paint). The U16
  next-record-prefetch invalidation-on-verb-execution rule is
  **load-bearing** and must be **global-on-any-verb-completion, not
  per-record** — a route to record X changes the budget shown for any
  record Y sharing X's target. **U16/Y-19 are a parallel worktree**, so
  Y-20 cannot enforce this from its branch; the orchestrator injects the
  obligation into U16's row at merge (blind-review F3, already messaged
  to the U16 builder). Until then the field is correct at every fresh
  render; only the prefetch-warm case needs U16's coverage.
  **(4) Display — the Why region is the single budget surface; the
  armed bar carries NO budget datum** (blind-review F2). The bar keeps
  showing only the selected destination *name* as today —
  `action_cycle_destination` re-fetches nothing and cycle round-trips
  drop non-echoed context (the `dest_note` precedent, routes.py:605-617),
  so a per-cross bar budget would need a new, staler datum path for no
  gain. The Why region lists all candidates' budgets at render, which is
  the whole comparison; plain words (Y-9) beside each — the two capped
  destinations from `surface_fill`, `reference` as the static
  no-cap line.
  **(5) At/over cap — reference, do not duplicate:** the existing 02 §4
  over-cap WARNING + graduation-opener flow owns the "route still
  applies but flags the section" escalation; Y-20 only makes the fill
  *visible before* that boundary, converting an apply-time rejection
  into a decision-time fact (the survey's steelman answer: the human
  should decide with the cost visible, not discover it at rejection).
  **(6) Register of record:** `surface_fill` **supersedes** the U0-
  dropped `status --json .sections_over_cap` — that was a global
  over-cap *count* for a Front banner; this is per-record, per-
  destination fill for the one decision in view (08 §1 correction, 10 §1
  row). No new keymap surface, no proposal-YAML field, no analyst
  tokens: an analyst-written `cost` card section (the survey's rejected
  P3a variant) was **declined** because it would freeze the number at
  proposal time — stale by review time; the render-time CLI field is the
  only shape that keeps the fact true at the decision moment.

- **Y-21 · Miner episode brief on the Detail page** *(added 2026-07-18 —
  UX enhancement survey (`research/2026-07-18-ux-enhancement-survey.md`)
  Q4 / shortlist item 5; parallel round-authors hold Y-19/Y-20)*. The
  user's framing, verbatim: *"should the agent that does the mining also
  write up a longer brief that can be shown when the user clicks into a
  potential lesson within a bucket."* The miner is the only actor that
  reads the full transcript, and transcripts prune before review — so the
  episode story is lost by decision time unless captured at mine time.
  **Mechanism (owned elsewhere):** the miner writes a 100–200-word plain-
  words `## Episode brief` **record-body** section for `source: session`
  records only, at land, from the same digest read — normative pin 12
  §11; body-section + compiler-exclusion pin 02 §1; validator registers
  it optional and **no compiler ever reads it** (compilers select body
  sections by explicit heading name, so the brief is inert to canon by
  construction — 02 §1 obligation + regression test). **It is a record
  body section, never a proposal `card:` section** — cards are the
  analyst's artifact, the record body the capture producer's; the miner
  writes records, not cards (the producer/consumer boundary doc 12 §1's
  "no card-registry change" pin preserved). **Surface decisions of
  record (this entry owns them):** **(1)** §2.3 renders the brief
  **collapsed + expandable, below** the decision content (Trigger +
  Instruction + evidence), never inline/above — FB4 principle 3, a longer
  brief must not push decision content below the fold; the finding model
  in **`models.py`** (`_build_finding`/`FindingRegion`, not `ledger.py`)
  **splits `## Episode brief` out of the whole-body blob** so decision
  content renders as now and the brief renders separately;
  **(2)** **absent brief renders nothing** — no block, no placeholder, no
  apology (no-backfill: pre-amendment records have no brief and their
  transcripts may be pruned); **(3)** **bucket-page rows do not grow**
  (§2.2) — the brief is click-into content by the user's own framing;
  **(4)** **no staleness machinery** — the brief describes the past, has
  no `record_sha` and no freshness badge (12 §11); it is body substance,
  freely editable while pending (02 §2), scanned by the same
  `proposal validate` checkpoint on pane/Discuss edits, frozen at routing
  with the rest. **No `list --json` change** — the brief is a body
  section the Detail render reads from the pending file (like
  Trigger/Instruction), not a JSON field; build lands as 10 §3 U18.

- **Y-22 · Proposal-time lint (analyst rider)** *(added 2026-07-19 — FW-31,
  `drafts/analyst-riders-spec.md` §1)*. The analyst (M1 inline, M2 worker,
  and the G-3 pane — all three producers) forms two judgments on a
  `behavior` record and may write one suggestion: **trigger
  recognizability** (would a fresh session, cold, recognize the firing
  moment from `## Trigger` alone?) and **why-clause presence** (does
  `## Instruction` carry the why on its compiled first line?). Output is a
  structured, optional `lint:` proposal block — `trigger_recognizable`
  (enum `yes`\|`partial`\|`no`), `why_present` (bool), `sharpening`
  (optional non-empty string) — **never a numeric/confidence score**
  (counted-not-modeled, 14 §6). Validated by a new `_validate_lint`
  helper in `ledger_ops.py`, symmetric with `_validate_hook_extension`;
  absence is always valid. Rendered by a new `lint` card section
  (`card-sections.yaml`, order 50, after `discuss`) — the structured
  block is authoritative, the card section its plain-words render (the
  `already_canon`/`already_canon_reason` pattern, moved into the
  registry). **Kind-aware MUST:** a `kind: reasoning-pattern` record's
  inherent trigger softness is never treated as a defect — lint is
  advisory only, never blocks/gates routing, and never auto-edits the
  record. The judgment rules live in `routing-doctrine.md` §9 (the one
  file all three producers load) — the M2 `_PROMPT_TEMPLATE` carries at
  most a one-line pointer to it, never the rules themselves, which is
  what keeps this three-producer rather than M2-only. **No consumer at
  ship time** — the human decides in prose off the card; the block ships
  now as counting substrate for the FW-33 portfolio auditor, an accepted
  named-reader deferral, not an orphan field.

- **Y-23 · Destination-bounded contradiction check (analyst rider)**
  *(added 2026-07-19 — FW-32, `drafts/analyst-riders-spec.md` §2)*. The
  analyst flags a suspected contradiction **only** against the
  destination section's current entries already shown in that record's
  candidate-target canon excerpt (`worker.py` `_canon_excerpt`) — **never**
  a canon-wide scan (canon-wide detection stays G-5-gated). Two edits
  carry the scope: the M2-only `_PROMPT_TEMPLATE` `contradicts:` line is
  **narrowed** from "existing canon" to "an entry in the destination
  section shown in the candidate-target excerpt", and a **new**
  bounded-contradiction subsection (`routing-doctrine.md` §10) makes M1
  inline and the pane emit the same bounded suspicion — the addition that
  first makes front-half contradiction detection three-producer (the
  propose→offer→verb back half, `routes.py`, was already producer-
  agnostic and ships unchanged). Machine output is the **existing**
  `contradicts:` list (11 §2.4, `link contradicts` verb input,
  unchanged); the human-facing triple — target, conflicting span, one-
  line reason — is authored into a **new `conflict` card section**
  (`card-sections.yaml`, order 55, after `discuss`), plain words, no
  jargon ("may clash with a rule you already kept", never
  "canon"/"contradiction"), record id demoted to a footer. **MUSTs:**
  advisory, dismissible, never blocks, never auto-writes the
  `links.contradicts` edge (proposer ≠ approver — the human's accept
  still runs `link contradicts`), and never claims completeness (no "no
  contradictions found" assertion, only positive suspicions). Degrades
  per the Y-20 F5 posture: an unresolvable/bootstrap excerpt omits both
  `contradicts` and the `conflict` card entirely, never a guess.

||||||| 1e830b5
- **Y-24 · Miner near-miss visibility + canary recall checks** *(added
  2026-07-19 — FW-34, `drafts/miner-visibility-spec.md`, gated SOUND;
  build-grade; mirrors the Y-21 episode-brief entry's shape)*. Extends
  the existing Front **Miner** region ONLY — zero new top-level regions
  (the FW-19 tripwire is not tripped). **One-liner** (always visible):
  *"miner: N sessions read, K landed, M near-misses"* + the existing
  `last run <ts> — <stale label>` line, with a `· canaries K/N caught`
  suffix appended only once `planted > 0`. N/K/M are all drawn from the
  **same latest `ok`/`landed-uncommitted` run** — never a cross-run mix.
  **Drill**: a second, default-collapsed `<details summary="near-misses
  (M)">` beside the existing `runs` disclosure (progressive disclosure,
  09 §2.3's posture) — rows from **that one latest run only** (older
  runs' near-misses are never re-surfaced; the charter's "aggregate
  counts with an on-demand drill, never a second queue" rule). A row
  shows the miner-emitted `disposition` badge (Y-10: text always
  present) + the plain-words `reason`; a `promotable` row additionally
  shows the snippet's trigger/instruction (or fact/context) as one
  dimmed draft line; an `already-canon` row links the matched record id;
  every other row shows the reason only. **No dismiss/snooze/seen —
  Promote to pending is the only control**, and only on `promotable`
  rows. **Mechanism (owned by 12 §12, the sibling miner-side amendment):**
  the CLI folds every near-miss outcome to a 5-way `disposition` +
  plain-words `reason` + a CLI-computed `promotable` flag at
  journal-write time — the UI renders every one of these fields
  verbatim, deriving nothing (the no-derivation rule). **Promote**:
  `POST /mine/near-miss/promote` (sibling to `/mine/run`), body = run-id
  + outcome index; the server RE-READS the snippet from a fresh `mine
  status --json` (never trusts the posted body — mirrors the Y-18
  rehome re-resolve) and rejects a non-promotable index; it builds the
  exact `teach` argv from the snippet fields (`--<scope> --type … [--kind
  …] --trigger/--instruction` or `--fact/--context`) plus `--session
  <sid>` parsed from the origin — **never `--quote`** (a near-miss
  carries no journaled evidence span). No arm-then-confirm ceremony —
  matches `/mine/run`/`/worker/kick` (the tap is the confirmation; teach
  is the human-capture writer with its own full scan/cap/pending-gate
  discipline). **Canaries** ride the same one-liner's suffix and no
  other surface — no new page, no new region; `mine status --json`'s
  top-level `canaries` block is absent when nothing has ever been
  planted. **Substrate**: `mine status --json` gains `near_miss_count`
  per run and a top-level `canaries` object (12 §12); each outcome dict
  gains `disposition`/`reason`/`promotable`/`snippet`. No `list --json`
  change; no new keymap surface.

