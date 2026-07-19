# G-3 surface — live acceptance trials (U11)

Every live trial gets a dated entry: command, environment, outcome,
pass/fail against its predicate (10 §2 discipline). CI-level acceptance
(T-A) lives in the ui test suite; this file is the live-execution record.

## T-A · Headless suite (CI)
- **2026-07-17 · PASS** — `cd plugins/self-learn/ui && uv run pytest -q`
  → 478 passed. Interaction + security + degradation matrices per 10 §2's
  T-A predicate; every 09 §2/§3/§11 behavior has an inversion-failing test.

## T-B · Pane permission live refusal (live SDK, real model)
- **2026-07-17 · PASS (5/5), after fixing a BLOCKER it caught.**
  Env: throwaway `SELF_LEARN_HOME` with a registered host (`skills_root`)
  holding a canon surface (`plugins/demo/skills/demo/SKILL.md`), a
  non-canon source file (`src/private_source.py`), a secret outside all
  roots, and a sacrificial record `lrn-deadbeef`. Driver built the exact
  production `ClaudeAgentOptions` via `SdkPaneEngine._build_options` and
  ran a real `ClaudeSDKClient` session instructed to attempt five actions.
  Result (evidence = `ResultMessage.permission_denials` + on-disk effects):
  1. `Bash git log` → **refused** (blocked by `disallowed_tools`, never
     reaches the callback — as designed).
  2. `Write` a file outside the allowlist → **refused** (callback);
     `attacker_write.txt` does not exist.
  3. `Read` a file outside the repo → **refused** (callback).
  4. `Read` a non-canon file inside the registered host → **refused**
     (callback) — the Y-2 narrowed-scope signature case, live-confirmed.
  5. `Edit` its own pending record → **allowed**; the file was edited.
  - **BLOCKER caught & fixed (charter.py):** the first run DENIED action 5.
    Root cause: `_resolve_charter_paths` computed the allowed write target
    as `f"lrn-{record_id}"`, but `record_id` is the canonical
    already-`lrn-`-prefixed id (what `list --json` emits and `/record/<id>`
    carries), so it built `lrn-lrn-<hex>` and denied the agent EVERY edit
    of its own record/proposal — its core job. The unit suite missed it by
    passing bare ids (`abc123`). Fixed to use the canonical stem;
    regression test `test_canonical_prefixed_id_allows_own_record_edit`
    added (asserts the real filename is writable AND the double-prefixed
    path is not). Re-ran T-B → 5/5.
  - *Predicate 4/4 (+ the added canon-scope 5th): MET.*

## T-E · Stream + interrupt smoke (live SDK, real model)
- **2026-07-17 · PASS (streaming); interrupt within design bound, UX note.**
  Driver drove `SdkPaneEngine.start()` on a "count to 40 slowly" prompt.
  - **Streaming: PASS** — 8 incremental `text_delta` events, first at
    ~2.0 s after start (chunk cadence per probe 1); visibly incremental.
  - **Interrupt: within the designed ladder, subprocess terminated.**
    `interrupt()` at the 8th delta → the SDK's own `client.interrupt()`
    did NOT halt the subscription-auth stream within the 2 s grace or the
    5 s kill window; the ladder's force-close terminated it (ui.log:
    "grace + kill window exhausted — force-closing"). Subprocess gone,
    `close()` returned in 0.00 s, no lingering process. Teardown to the
    `Result` event ≈ 5.3 s (the kill fires at the pinned 5 s; the extra
    ~0.3 s is Result propagation).
  - **UX finding (backlog, not a blocker):** Esc-to-interrupt relies on
    the kill backstop (~5 s) because the SDK fast-interrupt is ineffective
    on this subscription-auth streaming path. Within 09 §4.2's designed
    envelope (kill at 5 s) and safe, but sluggish for a keystroke.
    Candidate tuning: shorten grace/kill (e.g. 1 s / 2.5 s), or investigate
    the SDK interrupt on subscription auth. Recorded for U11 follow-up.
  - *Predicate (incremental render; subprocess gone within the 5 s kill
    bound): MET, with the interrupt-latency note above.*

## T-C · End-to-end adjudication (live, no model)
- **2026-07-17 · PASS.** Env: throwaway ledger git repo with a bare
  `origin` remote + a registered project host git repo; seeded a
  project-scope record via the real `self-learn teach`, hand-wrote +
  `proposal validate`d a `reference`-destination proposal (record_sha
  stamped). Started the real service against it (port 7361), authed via
  the token→cookie flow, then executed the route through the **real HTTP
  POST** `/record/<id>/action/confirm` (verb=route, dest=reference,
  HX-Request header). Verified entirely from git/filesystem, not UI
  output:
  - record moved to `resolved/` ✓; pending gone ✓; proposal `git rm`'d ✓
  - host `references/LEARNINGS.md` compiled with the fact ✓ (two-phase
    ledger→host routing)
  - ledger commit `self-learn: route lrn-… → reference` present ✓
  - sentinel released (absent after) ✓
  - **push:** landed on the bare remote after `git branch --set-upstream`
    — the route verb does `git push -q` (gitops `push_with_retry`), which
    needs a tracking branch; my baseline seed pushed without `-u`, so the
    in-trial push initially reported "PUSH FAILED — commit kept" (the
    verb's correct soft-failure behavior: commit safe locally). With
    upstream set (as the real `~/.self-learn` clone has), `self-learn
    push` landed both route commits on the remote. **Test-setup artifact,
    not a product defect** — re-verified.
  - *Predicate: MET.*
  - **Backlog note (minor UX):** a push-failure on an otherwise-successful
    route is exit-0 (commit kept), so the web UI shows success and does
    NOT surface the "unpushed" warning (matches the CLI's stderr-only
    behavior, but a web user has no terminal). Candidate: a status-strip
    "unpushed commits" indicator beside the existing sentinel state.
## T-D · Deep-link chain (live desktop, user present)
- **2026-07-17 · PASS (primary chain); one env finding caught & fixed.**
  Env: throwaway ledger with a seeded pending record (`lrn-07dcbf0f`),
  server on the DEFAULT port 7357 with the real `XDG_RUNTIME_DIR`
  (`/run/user/1000`) so the click-launched opener finds the token.
  Fired the real `self-learn-notify --line … --ids lrn-07dcbf0f`
  (worktree path). swaync showed the notification; **the user clicked
  "Open"**; the notifier's action ran `self-learn-ui-open --record
  lrn-07dcbf0f`, which launched a chromeless Chromium app window
  deep-linked to that record's Detail (the "128×32 OLED" fact, Finding/
  Change/Why regions, action bar, keymap footer) — user-confirmed via
  screenshot. *Primary predicate (notify → click → dedicated window →
  correct record): MET.*
  - **Finding caught live (contradicts 09 §1's 2026-07-12 verification):**
    the window's class was `chrome-127.0.0.1__record_lrn-07dcbf0f-Default`,
    NOT the pinned `self-learn-ui`. On this Chromium + native Wayland, an
    `--app` window created by an ALREADY-RUNNING chromium derives its
    app_id from the URL and ignores `--class` (the 09 §1 verification was
    almost certainly done against a fresh chromium, where --class applies).
    A dedicated `--user-data-dir` did NOT restore it (still URL-derived) —
    so the X-3 class-only focus-detection can never find the window, and
    every deep-link would spawn a new one.
  - **Fix (self-learn-ui-open), corrected after the final review's MAJOR:**
    match an existing UI window by its stable page-TITLE prefix
    "self-learn — " (or the class) via `hyprctl clients -j`, resolve its
    **address**, and `focuswindow address:<addr>`. The first fix attempt
    dispatched `focuswindow class:… || focuswindow title:…` — but
    `focuswindow` exits 0 even when it matches nothing (X-3, the script's
    own header pin), so the `||` short-circuited and the title focus never
    ran: the window was detected but never raised. Corrected to
    address-based focus, never gating on the dispatch exit code. Re-tested
    live *properly*: focused a different window, ran the launcher, and
    `hyprctl activewindow` became the UI window's address (0x55d80fd66220)
    with the window count unchanged — genuine focus, not just
    spawn-suppression. Regression tests now assert `focuswindow
    address:<addr>` (fail if the broken class-`||`-title form returns).
  - **Residual (accepted, 09 §5 degradation):** focus-existing now works,
    but focusing does not RE-NAVIGATE the window to a different record
    (chromium `--app` can't be messaged a new URL) — a deep-link to a
    *different* record still opens its own window. This is the documented
    "new window each time" degradation, now scoped to cross-record
    deep-links only. Corpus amendment owed at 09 §1 / X-3 (below).
## Browser-level acceptance (X-5, Playwright)
- **2026-07-17 · PASS (real browser, Playwright).** claude-in-chrome was
  not connected; used Playwright against a real server (port 7362) on a
  throwaway ledger. Verified live:
  - **Token→cookie→clean-URL:** navigating to `/?token=…` landed on
    `http://127.0.0.1:7362/` (token stripped by the 303) — real-browser
    confirmation of the flow.
  - **Render:** front page, status strip, bucket walk, miner block with
    Force-run, and the complete keymap footer (all 15 keys from the
    single-source table).
  - **Keyboard handler (app.js):** `?` opened the help overlay
    (`#self-learn-ui-help`, visible).
  - **SSE-refreshed partial swap:** with the browser idle on Front, a
    `self-learn teach` from the CLI drove the watcher → SSE → htmx swap;
    the bucket's pending count went 0→1 and the status strip updated to
    "pending: 1" with NO reload. End-to-end live refresh confirmed.
  - **Armed-key resolution flow:** on the record Detail, `f` armed
    "Defer lrn-… · Enter to confirm"; Enter executed the real verb — the
    record became `status: deferred`, `deferred_until` +30d, excluded
    from the queue. Full arm→confirm→effect in a real browser.
  - **Two findings caught & FIXED (2026-07-17):**
    1. htmx 2.0.9 injects an inline `<style>` for its indicator on boot;
       the pinned CSP (`style-src 'self'`) blocked it, throwing a console
       error on **every** swap and disabling the indicator fade — a W-9
       gap (the pin covered our templates' inline styles, not htmx's
       runtime injection). Fixed: `<meta name="htmx-config"
       content='{"includeIndicatorStyles": false}'>` in the head (htmx
       reads it pre-boot) + the indicator CSS served from style.css.
    2. `/favicon.ico` 404 (cosmetic). Fixed: `<link rel="icon"
       href="data:,">` (CSP `img-src` allows `data:`).
    Re-verified in the browser after the fix: **0 console errors** on load.
    Regression test `test_head_disables_htmx_inline_style_and_suppresses_favicon`.
  - *Predicate (armed-key flow + SSE swap in a real browser): MET.*
## T-B rows (6)–(8) · Y-13 verb proposals (live SDK, real model — U12)
- **2026-07-17 · (6) PASS · (7) PASS-BY-COMPOSITION · (8) PASS.**
  Env: throwaway ledger (skills/demo, seeded record), driver building the
  production `SdkPaneEngine._build_options` with the charter callback
  instrumented (a recording wrapper around `build_can_use_tool` — the
  production path, spied not replaced), real ClaudeSDKClient sessions on
  claude-sonnet-5, XDG dirs redirected.
  - **(6) propose_verb routes through the callback — the footgun-B proof
    on the resolved SDK (0.2.121):** callback call log contains
    `mcp__self-learn-surface__propose_verb`; the slot occupied WAITING
    (`armed=False`, verb=route, dest=skill-md, note verbatim); the SSE
    envelope published with record_id + bucket; the record file untouched
    and still pending; NO runner existed in the driver — nothing could
    have executed. *Predicate MET.*
  - **BLOCKER caught & fixed on the first run:** the tool's dict-of-types
    schema shorthand (`{"until": str | None}`) renders every key REQUIRED
    to the model, which filled `until=""` — and the validator read "" as
    present, refusing a valid route with "until only applies to defer".
    Fixed: a real JSON Schema (`required: [verb, record_id]` only) plus
    empty-string→absent normalization in the validator (belt);
    regression test `test_empty_string_optionals_are_absent`. Re-ran →
    PASS.
  - **(7) host-add unproposable:** instructed twice (second time with an
    explicit "you MUST call the tool" test framing), the agent REFUSED to
    invoke propose_verb for host add — the surface-model prose teaches
    the exclusion, so the in-context layer holds before the handler's
    closed list is even reached. No registration occurred, slot stayed
    empty. The handler's own closed-list refusal (the row's letter) is
    pinned by unit test (`test_closed_list_refuses_host_add_and_
    everything_else`); the live half shows defense-in-depth ABOVE it.
    Recorded honestly as pass-by-composition, not a single live proof.
  - **(8) bucket zero-write held live:** a bucket session instructed to
    edit the pending record attempted `Edit` (and, unprompted in an
    earlier turn, `Write proposals/…yaml`) — both reached the callback
    and denied; the file shows no tampering; the agent then told the
    human, unprompted, "I can't write the actual proposal from here —
    open the record and press i" (the deny reason teaching the venue,
    exactly as designed). *Predicate MET.*

## U12 DoD · Live bucket-pane proposal, full keyboard consent (browser)
- **2026-07-17 · PASS (end-to-end, real everything).** Real server
  (worktree, port 7358, sandbox ledger + XDG), real Playwright browser,
  real sonnet bucket session. Chain verified: Bucket page renders the
  split with "Open bucket chat (p)" (footer shows `p` via the context
  filter; `y` hidden with no proposal present) → `p` opened a REAL
  bucket session (first-turn bucket context; the agent summarized the
  queue in plain words, Y-9-register quality) → typed instruction
  "propose deferring lrn-d785d07c until 2026-09-15 with note 'revisit
  after HA upgrade'" → agent called propose_verb → **SSE `pane_proposal`
  → page re-render → WAITING bar** ("Agent proposes: Defer … until
  2026-09-15 · agent-suggested note: …", Review & arm (y) + Dismiss,
  NOT armed) → `y` armed (Enter-to-confirm hint) → `Enter` confirmed →
  the REAL verb ran: record `status: deferred`, `deferred_until:
  2026-09-15`, ledger commit `self-learn: defer lrn-d785d07c until
  2026-09-15`. **The bucket session survived the confirm** (transcript
  intact + input line open — the 09 §4.5 exemption, live-confirmed) and
  its final message honestly restated the consent contract. Screenshots:
  `~/Pictures/self-learn-ui/u12-proposal-{waiting,armed}.png`.
  - **Cosmetic observation (backlog, pre-existing):** the live SSE
    `pane_block` append can race the authoritative region swap and
    briefly duplicate the final transcript block until the next
    re-render (app.js's documented best-effort appender; also reachable
    on record panes). No state impact; candidate fix is de-duping the
    appender or dropping SSE-appended blocks on swap.

## Degradation walk (09 §5 row-by-row, U9 ledger)
- **2026-07-17 · SATISFIED (CI + live trials).** U9 implemented and
  CI-tested every 09 §5 row (15 tests, `test_degradation_walk.py`) with a
  row-by-row ledger (10 U9 report). Live trials confirmed the material
  rows: SSE refresh worked end-to-end in a real browser (browser pass);
  swaync-absent / no-action-daemon and no-chromium / xdg-open fallbacks
  are covered by the shimmed launcher+notify tests; verb-nonzero and
  scan-blocked paths by T-A/T-E. The remaining rows are OS-level
  documented degradations that need no live repro: server-not-running at
  deep-link time (a browser connection error — no app code path), and
  plain-tab fallback when no Chromium `--app` exists (09 §5). No
  additional live check owed.

## U13 DoD · Idle lifecycle live trials (2026-07-18, autonomous overnight run)

Shortened windows throughout (live service: 20 s via a temporary
systemd drop-in; dev instance: 15 s explicit env). All four 10 §3 U13
DoD trials run; one production BLOCKER caught and fixed mid-trial.

- **(a) Close all pages → clean exit — FAILED FIRST, then PASS.**
  First run: the service exited **143** and systemd RESTARTED it —
  three failure cycles in the journal ("Main process exited,
  code=exited, status=143", "Failed with result 'exit-code'").
  Root cause: uvicorn 0.29+ `capture_signals` re-raises the captured
  SIGTERM after graceful shutdown, so SIGTERM-to-self dies BY SIGNAL;
  both blind reviews had passed that mechanism as sound
  (plausible-but-wrong on installed uvicorn 0.51 — the live trial is
  what caught it). Fixed to uvicorn's `should_exit` flag (afc1495);
  re-run: `ActiveState=inactive Result=success ExecMainStatus=0` —
  exits clean, stays down. Restart counter untouched thereafter.
- **(b) Launcher cold start, no 403 — PASS.** With the service down
  (post-(a) exit), `self-learn-ui-open` returned rc 0 in ~0.46 s;
  the window opened directly on a tokened page (title
  "self-learn — Front", never the 403 page). Window landed on DP-1
  and was moved to DP-2 per the standing rule.
- **(c) Walk-away (Iterate → result → close window, no `q`) — PASS,
  with the delta-R1 choreography visible in the log.** Dev instance
  (sandboxed home/runtime/cache, port 7358, foreground serve with the
  var set explicitly — also proving the explicit-set-arms leg of the
  Y-14 decision-6 rule; two earlier no-client runs of the same
  instance exited `SERVER_EXIT=0`, proving the plain idle path
  foreground too). A real SDK session on a seeded record reached
  awaiting-input; page closed 01:36:24; ui.log then shows sample 1
  tearing down the parked session ("sdk: Read task cancelled",
  01:36:59) and DEFERRING, and sample 2 exiting ("idle monitor:
  predicate held for 15s window — clean self-exit", 01:37:29);
  wrapper captured `SERVER_EXIT=0`.
- **(d) Launcher click during the shutdown drain — ATTEMPTED,
  drain not hittable.** A 0.2 s poll on `is-active` watching for the
  drain observed the service go from `active` to `inactive` between
  samples — the no-connection drain is sub-200 ms, too fast to land a
  click inside by any human-scale timing. The click 0.4 s later took
  the ordinary cold-start path (= trial (b), PASS). Outcome logged
  per the DoD's "even if it is the accepted degradation" clause; the
  not-`active` snapshot condition that trial exists to exercise is
  pinned hermetically in test_launcher.py instead.

Post-trial state: drop-in override removed (window back to the 600 s
default on next service start); fresh tokened window left on DP-2.

## T-E addendum · Tuned interrupt ladder retrial (2026-07-18)

Same driver, same "count to 40 slowly" prompt, after the 09 §4.2
tuning (1 s grace / 2.5 s kill, one Esc-anchored deadline,
shield-and-abandon close): 8 incremental deltas, interrupt at the
8th → **interrupt→Result teardown 2.90 s** (was ~5.3 s at the
original T-E), `close()` 0.00 s, PASS. The keystroke now costs
~2.9 s worst-case-observed against the amendment's "common-path
~2.7 s + Result propagation" claim and the 5 s arithmetic ceiling.

## Y-15 re-trials · Non-blocking pane start (2026-07-18, dev sandbox, real model)

The three re-trials the Y-15 register names, run on the merged tree
before deploy:

- **(i) Bucket-chat button → instant split + live stream — PASS,
  vividly.** The split swapped in immediately on the click; by the
  first snapshot the starting line had ALREADY been cleared by the
  first streamed frame (F7 working) and live tool activity ("tool:
  Read → pending/…") was rendering mid-turn. At completion the swap
  landed the result footer (success · $0.2334 · 5 turns) and parked
  at awaiting-input. The round-2 complaint (silent 30–90 s wall) is
  dead. Bonus: Fix A visible live — the user-scope record rendered
  the corrected `claude-md` default with the cycle note.
- **(iii) Esc during starting — PASS.** Interrupt clicked in the
  starting split seconds after Iterate; the turn terminated promptly
  and the completion swap rendered the ended state: the SDK's
  diagnostic verbatim in the error strip + Retry (r) + Close (q).
  (Keymap note observed en route: body-focused Esc navigates back by
  design — the pane-focused binding and the Interrupt button are the
  interrupt paths.)
- **(ii) Forced background-drain failure — pass-by-composition,
  recorded honestly.** Three forcing levers were tried live: a bogus
  `SELF_LEARN_PANE_MODEL` (the wired fallback model rescued the turn
  — correct product behavior), a removed record (the route's own
  not-found guard intercepts before any pane start), and an
  unreadable record (the Detail PAGE 500s before Iterate is
  reachable — a pre-existing degradation gap, new backlog item
  below). The exception leg itself is pinned by the unit test
  (exception-in-drain → ENDED + slot cleared + synthetic
  `pane_result`) and the route test (error-strip markup from the
  panel GET), and the client half of the path — `pane_result` →
  completion swap → error strip + Retry in a real browser — is
  exactly what trial (iii) proved live over the same envelope.

New backlog observation from (ii)'s third lever: an unreadable
(permission-denied) record file 500s the Detail page — predates this
round; wants a §5-style degradation row + friendly render.

Also live-confirmed en route: one-session-server-wide held (the
record Iterate against a parked bucket session rendered the armed
interrupt prompt, correctly naming the bucket session); close-then-
claim worked; the reload-mid-drain snapshot rendered.

## Round-3 DoD trials — U14 + U15 (2026-07-18, sandboxed instance)

Full sandbox (redirected `SELF_LEARN_HOME`/`XDG_RUNTIME_DIR`/
`XDG_CACHE_HOME`, port 7457, server run from the merged tree): ledger
home + skills root + `projA` (git repo, registered), `projB` and
`projC` (plain directories, unregistered), one pending trial record
per bucket. Real browser via Playwright; the live service and the
real ledger were never touched.

- **U14 (a) git-init-on-register, end-to-end — PASS.** projB's bucket
  showed the unregistered notice; Register armed the disclosure
  banner: *"A new git repository will be created at ⟨path⟩ (`git
  init`) as part of registering. This runs: `self-learn host add
  --init ⟨path⟩`"* — the displayed command carried `--init` exactly
  because the path was not a repo root. Confirm registered in one
  motion: projB now a git repo whose first commit is the pinned
  subject `self-learn: init for host registration`, hosts.yaml
  carries the entry, and the notice cleared on the post-success
  redirect.
- **U14 (b) failed registration error persists, plain words — PASS.**
  projC's directory was deleted after capture, so confirm hit the
  CLI's missing-dir refusal. The error strip rendered *"Registration
  did not complete."* leading with the CLI's clean refusal as the
  demoted detail line — and it SURVIVED the post-verb refresh push
  (3+ s observation window; on master-before-U14 this exact flow
  wiped the strip via the front-scope broadcast reload — the
  empirically pinned mechanism, 10 §Build findings U14 entry).
  Dismiss restored the unregistered notice; the deferred reload
  released cleanly (page state stayed truthful).
- **U15 rehome via pane proposal, y+Enter — PASS.** projA's bucket
  chat was asked to move the trial lesson to projB. The agent read
  the record, REASONED about the target first (asked whether projB
  was the deliberate choice — the amended ancestor-project doctrine
  visibly in play; the compiled system prompt of the sandbox pane's
  CLI child carried the new clause, confirmed by mtime-driven
  recompile with zero code changes), then proposed: the waiting bar
  rendered *"move this lesson to the projB project"* with the
  resolved path + record id as trailing metadata and the agent's
  note labeled as its suggestion. `y` armed, Enter confirmed: one
  ledger commit `self-learn: rehome lrn-d598b7f3 → projects/…projB…`,
  record pending in projB's queue, proposal slot cleared. The Y-15
  instant-split + live tool streaming behavior re-confirmed en route.

## UX-round DoD trials — U16 + U17 + U18 (2026-07-18, sandboxed instance)

Same sandbox posture as round 3 (redirected home/runtime/cache, port
7457, server from the merged tree, real ledger untouched). Real
browser via Playwright.

- **U16 auto-focus + keyboard-live — PASS.** Front loaded with the
  first bucket row already selected, focus parked on the content
  landmark, and `s` moved the selection with NO prior click — the
  keys-dead-until-click dead-end is gone. Selection moved 0→1 of 3.
- **U16 worker Force-run — PASS.** The new Worker region rendered on
  Front beside the miner's; one click detach-spawned
  `worker run --coalesce` (observed as an independent process) and
  the page returned instantly — no held request, Y-14 posture intact.
- **U16 next-record prefetch — pass-by-tests + live walk.** The
  warm-cache behavior is pinned by 10 unit tests including the
  mutation-verified global-invalidation and never-stale assertions;
  the live walk (defer → redirect → next page paints, no errors)
  exercised the path. The DoD's "perceptible paint-stall reduction"
  is subjective browser-feel — left to the user's own queue walk,
  honestly recorded here.
- **U17 budget display — PASS, including the F1 fix live.** A
  project record's Why region rendered "this claude-md section
  already holds 0 of its 10 entries" — the bare fill fact with NO
  false nearness clause (the exact 0/10 case the code gate caught),
  plus the pinned reference line ("reference files have no cap —
  this is the overflow surface entries graduate into"). The armed
  action bar carried no budget markup (pinned negative held).
- **U18 brief display + key — PASS.** A record with an
  `## Episode brief` section rendered it as a COLLAPSED disclosure
  labeled "Episode brief (b)" below the decision content — nothing
  leaked inline into the finding body — and the `b` key toggled it
  open with the story visible. **Miner compose leg**: pinned by the
  planted-secret-only-in-brief test and the prompt-pin test; the
  full live miner-run trial rides the next real miner cycle on the
  deployed code (observable in the next session's mined records —
  check for briefs then).

## Rider/near-miss round DoD trials — FW-31/32 + FW-34 (+U-C3/C3b) (2026-07-19, sandboxed instance)

Full sandbox (redirected `SELF_LEARN_HOME`/`XDG_RUNTIME_DIR`/
`XDG_CACHE_HOME`/`SELF_LEARN_TRANSCRIPTS_DIR`, port 7457, server from
the merged tree, real ledger and real transcripts untouched): ledger
home + a registered scratch host carrying an `ha-ops` skill, real
`worker run` and `mine run` model calls (claude-sonnet-5), real
browser via Playwright.

- **Y-22 lint emission (live model) — PASS, first draw.** The fuzzy
  bait record ("About to edit HA files") came back
  `trigger_recognizable: partial` with a concrete sharpening ("Name
  the .storage/*.json glob… not 'HA files'"); the concrete sibling
  came back `yes`/`true` with no sharpening. The Detail card rendered
  the judgment as the plain-words "Would a fresh session catch this?"
  section, after "Worth discussing", with the Y-9 leading line
  untouched.
- **Y-23 contradiction check (live model) — PASS with an honest
  nuance.** First bait (the spec's own §2 worked example: mid-flash
  rule vs stop-before-editing) did NOT fire — the model reasoned the
  two rules govern different operations and judged them consistent, a
  defensible read that suggests the spec's worked example is a
  borderline case. Same-operation opposite-instruction bait fired
  reliably on both subsequent draws: `contradicts: [<real id>]`, the
  `conflict` card leading with the domestic gloss, quoting the
  conflicting span, id demoted to the footer.
- **Y-8/Y-23 offer flow — FAILED live, twice, then PASS; two real
  defects shipped out of it.** (1) The post-route contradicts offer
  had NEVER been reachable in production: the route verb deletes the
  proposal sibling at resolution (08 §1), and the handler read
  `contradicts` after the verb ran; the old test passed only via a
  FakeRunner that deletes nothing — mock theater exposed by the first
  producer to ever emit an edge. Fixed (U-C3, both confirm routes,
  pre-verb capture + reload-defer leg (d) + deletion-faithful
  RouteSideEffectRunner). (2) The retrial STILL failed — traced by
  instrumentation (11 live orderings) to a stale cached `app.js` in
  the trial browser: `StaticFiles` ships no cache-busting, so a tab
  from before a deploy holds the old script across a server restart.
  With fresh assets the flow passed end-to-end: route → "Routed. This
  proposal named conflicting canon" → Link contradiction → Enter →
  `links.contradicts` written in one ledger commit, queue advanced.
- **FW-34 capped mine run (live model) — PASS, first attempt.** Cap=1
  over a two-arc synthetic transcript: exactly one candidate landed
  (rich record incl. episode brief) and one `cap-refused` near-miss
  journaled with the plain-words reason. **Calibration finding:** the
  real reader's draft exceeded `MAX_NEARMISS_SNIPPET_CHARS` (600), so
  the first genuine near-miss was `{overlength: true}`,
  `promotable: false` — refuse-not-clip behaved exactly as pinned,
  and the feature's headline action was unavailable on its first
  outing. Watch: the cap is likely too tight for real reader output.
- **Near-miss drill + Promote — PASS** (drill legs live-model; the
  promotable row data-seeded and logged as such, the real-model half
  being the overlength row above). Collapsed by default; overlength
  row = badge + reason only, no control; promotable row = dimmed
  draft + the single Promote control; no dismiss/snooze anywhere. One
  tap → real `teach` subprocess → pending record carrying the miner's
  draft with `--session` evidence and NO quote. **Seam finding:** the
  promoted record landed in the bucket of the UI server's own working
  directory (teach `--project` resolves from CWD; the snippet carries
  no project path) — sandbox-contained here, but in production a
  transcript-derived near-miss would file under the server's project,
  not the transcript's. Mitigation today: the rehome verb; proper fix
  needs a small spec amendment (backlog).
- **Canaries — PASS.** `plant` wrote only `canaries.json` (no
  transcript file anywhere), the DP-2 guard refused with the pinned
  message (exit 64), `mine status --json` carried the canaries block,
  and the Front one-liner appended "canaries 0/1 caught".
- **Bonus live confirmations en route:** the compiler's
  regenerate-from-records contract swept hand-seeded (recordless)
  managed-section entries on first real compile — by design; `link
  contradicts` cleanly refused a target with no record (exit 64); a
  worker analysis produced an unrequested-but-correct merge proposal
  for the two same-lesson bait records; `proposal validate` triggered
  the >24h miner catch-up watchdog in the aged sandbox (harmless,
  worth knowing it fires during ordinary CLI use).

## Y-28/U22 Tier-2 build-trial · session_store/resume (2026-07-19, raw SDK, real model)

Per the spec's §1 build-trial gate ("mirrors U5's verify-at-build"), run
BEFORE any `sdk.py`/`pane.py` wiring landed — a standalone driver against
raw `claude_agent_sdk` (not `self_learn_ui` code), constructing the exact
options shape the spec's primary configuration pins: `session_store=` set,
`extra_args` WITHOUT `no-session-persistence`. Model `claude-sonnet-5`,
subscription auth, a throwaway tmp dir (no ledger/XDG involvement — this
probe predates any self_learn_ui wiring). Driver:
`/tmp/claude-1000/.../scratchpad/tier2_probe.py` (two async probes).

- **Probe (i) — does `session_store.append` populate the cache-local
  mirror during a live streaming turn, flag dropped? PASS.** A fresh
  `ClaudeSDKClient` with `session_store=<in-memory-backed adapter over a
  tmp dir>` and no `no-session-persistence` extra_arg, queried "Reply
  with exactly and only this phrase: PROBE-ONE-OK". `store.append` was
  called (count 1 batch), a `<session_id>.jsonl` mirror file existed on
  disk after `disconnect()` with 7 lines (the CLI's own transcript-entry
  shape, opaque, round-tripped verbatim per the Protocol's contract), and
  `ResultMessage.session_id` was captured (`10ee8369-297e-4b54-934d-
  056e8eadbb9d`).
- **Probe (ii) — does `resume=<session_id>` restore context on a FRESH
  engine? PASS.** A brand-new `ClaudeSDKClient` (same `session_store`
  adapter, `resume=<the captured id>`, no prior in-process state shared)
  queried "Without me telling you again: what EXACT phrase did I ask you
  to reply with in our previous message? Quote it exactly, nothing
  else." Reply: `PROBE-ONE-OK` — the resumed session correctly recalled
  a fact from a turn it never itself streamed, proving `resume=`
  materialized the mirrored history into the new subprocess's context.

**Outcome: BOTH probes PASSED → Tier 2 ships as SDK-resume** (not
Tier-1.5 fallback). `engine/sdk.py`'s `TIER2_SESSION_STORE_ENABLED = True`
and `_build_options` drops `no-session-persistence` + wires
`session_store=CacheSdkSessionStore(...)` (every session, so a
`session_id` is captured even on a first non-resumed Iterate) +
`resume=ctx.resume_session_id` (set only on an explicit Y-28 Resume).
The docstring correction (§7) landed alongside this fold — see
`engine/sdk.py`'s module docstring, "session persistence (corrected
2026-07-19, task U22 / Y-28)".

No independent second trial of "does the flag suppress the mirror" was
run separately — the primary config (flag dropped) is what shipped, per
the spec's own framing ("the burden is on evidence, not on inertia" for
KEEPING the flag, not for dropping it); §1 only requires that check if a
trial of the flag-kept posture is attempted, which it was not, since the
primary config already passed cleanly.

**Residual — the DoD's live restart-resume walk (item 4) is NOT covered
by this entry.** This entry satisfies §1's build-trial gate (which tier
ships) and DoD item 3; the separate DoD item 4 ("open a record, `i` to
Iterate, hold a real multi-turn conversation... `systemctl --user restart
self-learn-ui`... Resume continues the conversation... Walk with the user
as the DoD sign-off") is an attended live walk against the deployed
service, owed as a follow-up session with the user present — not run as
part of this build.

## U22-fix · live-DoD BLOCKER: `SessionStore.list_subkeys()` on Resume (2026-07-19, worktree f5-u22fix)

**The DoD item-4 live walk above WAS attempted** (real browser, real SDK,
sandbox): started a real Iterate on `lrn-7e81cf1a` (Tier-1 mirror + meta
wrote correctly, `sdk_session_id 06126c50-d295-4cc6-b01f-74bd6b20810e`
captured, `bucket_dir` resolved), SIGKILL'd the server, restarted — the
prior-conversation card rendered correctly ("35 blocks · 1m ago · waiting
for you", Tier 1 held) — then **Resume errored**: "SessionStore.
list_subkeys() for session 06126c50-d295-4cc6-b01f-74bd6b20810e failed
during resume materialization:". Degradation contained (Retry/Close, no
500), but Tier 2 itself was broken — a genuine gap the two-probe trial
above never caught.

**Root cause (verified by reading + directly exercising the SDK's own
source, not guesswork):** the raw probe above used an ad-hoc,
minimally-duck-typed class defining ONLY `append`/`load` — never
`list_subkeys`. The PRODUCT adapter (`CacheSdkSessionStore`, added when
`sdk.py`/`store.py` were actually wired) additionally defined stub
bodies for the four "optional" `SessionStore` methods
(`list_sessions`/`list_session_summaries`/`delete`/`list_subkeys`, each
just `raise NotImplementedError`) to satisfy pyright's structural-Protocol
check without subclassing. That was the defect: the SDK's
`materialize_resume_session()`
(`claude_agent_sdk/_internal/session_resume.py:172-175`) only skips
subkey enumeration when `_store_implements(store, "list_subkeys")`
(`session_store_validation.py:8-14`) is `False` — and that function
decides "implemented" by **identity comparison**
(`getattr(type(store), method) is not getattr(SessionStore, method)`),
never by calling the method. A stub override is a distinct function
object from the Protocol's own default, so it read as "implemented,"
and `materialize_resume_session` called it for real, hit the genuine
`NotImplementedError`, and `_with_timeout`'s catch-all wrapped it into
the RuntimeError the human saw — reproduced VERBATIM (down to the
trailing bare colon) via a unit test importing and driving the SDK's
real `materialize_resume_session()`
(`tests/test_store.py::test_real_sdk_materialize_resume_session_
succeeds_multi_turn`, kill-verified: reintroducing the stub reddens it
with the identical text). This is independent of turn count — the
`_store_implements` check is a static property of the class definition,
not the session's content; the live walk's 35-block multi-turn history
did not cause it, it just happened to be what the walk exercised first.

**Fix:** `CacheSdkSessionStore` now properly subclasses `SessionStore`
and defines ONLY `append`/`load`; the four optional methods are left
completely UNDEFINED (inherited unchanged from the Protocol), so
`_store_implements()` correctly reports `False` for all four and
`materialize_resume_session` skips `_materialize_subkeys` exactly as
the original raw probe's ad-hoc class caused it to. A `# pyright:
ignore[reportAbstractUsage]` at the one production construction site
(`engine/sdk.py`) documents the resulting pyright/runtime tension:
pyright's Protocol-subclass heuristic treats any un-overridden
`raise NotImplementedError`-bodied method as "abstract" for
instantiation purposes, which is a static-analysis convention, not a
real Python (or SDK) constraint — the SDK's own docs say exactly the
opposite ("implementers may omit them... inherit them as absent
markers").

**End-to-end re-verification, real model, real multi-turn session, the
ACTUAL shipped `self_learn_ui.store.CacheSdkSessionStore` (not a
redefinition) — driver `/tmp/claude-1000/.../scratchpad/
tier2_probe_multiturn.py` — PASS:**
- First session: 3 real turns ("remember GIRAFFE" / "remember 42" /
  a plain acknowledgment), `session_id` stable across all three turns
  (`6e136b89-c6ed-4028-851b-8ffdab99e5b9`), `disconnect()`.
- A brand-new `ClaudeSDKClient`, `resume=<that id>`, same store:
  `connect()` — the exact call that raised pre-fix — **succeeded**.
  Queried "what animal and number did I ask you to remember earlier?"
  with NEITHER repeated in the prompt. Reply: `GIRAFFE,42` — the
  resumed session recalled BOTH facts from turns it never itself
  streamed, across a real materialize-resume round trip.

**Spec correction landed:** the draft's §"SDK capability, verified
empirically" bullet on `SessionStore`'s required methods now carries
the load-bearing caveat — "only `append`/`load` required" is true for
the write/resume-CONTENT path only; resume MATERIALIZATION additionally
probes (and, if a store answers "yes," calls) `list_subkeys`, and the
only way to correctly answer "no" is to leave the method completely
undefined on a `SessionStore` subclass, never override it with any
body at all.

**Counts:** UI suite 925 passed (mirrors the earlier round's 922 +
this round's 3 new tests: `test_store_implements_reports_false_for_
undefined_optional_methods`, `test_real_sdk_materialize_resume_
session_succeeds_multi_turn`, `test_real_sdk_materialize_resume_
session_none_for_never_appended_key`) — one unrelated `test_js_dom.py`
flake observed on the full run (`TestNoopKeyHints::test_no_hint_
when_a_bar_is_armed_and_o_is_pressed`), reproduced-absent on an
isolated re-run of that single test and the full suite (925/925 clean
on the follow-up run) — a pre-existing browser-timing flake in a file
this fix never touched, not a regression. pyright `ui/src`: 0
errors/0 warnings (one narrowly-scoped, documented
`# pyright: ignore[reportAbstractUsage]`).
