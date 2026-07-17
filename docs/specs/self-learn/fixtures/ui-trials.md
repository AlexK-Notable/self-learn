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
  - **Fix (self-learn-ui-open):** match an existing UI window by its
    stable page-TITLE prefix "self-learn — " in addition to the class,
    and focus by `title:` when the class match misses. Re-tested live:
    a second launcher run FOCUSED the existing window (window count stayed
    1) instead of spawning another. Regression test
    `test_window_present_by_title_focuses_when_class_is_url_derived`.
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
## Degradation walk (09 §5 row-by-row, U9 ledger) — PENDING
