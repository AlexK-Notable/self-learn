/*
 * self-learn-ui — app.js (10 §1 Dependencies row: "authored, ~40-line
 * keydown handler + EventSource client"; wired at U3).
 *
 * The keymap footer partial, help overlay, and this file's keydown
 * switch all render from the ONE source of truth:
 * self_learn_ui.keymap.KEYMAP, JSON-encoded via keymap_json() and
 * injected into the page as a <script type="application/json"> blob.
 *
 * Design (09 §1, restated as the contract this file honors):
 *   - Keys are inert while focus is in a text input.
 *   - No Ctrl/Alt/Meta chords, ever — the browser owns them.
 *   - Arm-then-confirm is SERVER-rendered (routes.py's
 *     .../action/arm|disarm|confirm partials) — this file's job is
 *     purely: keymap lookup -> find the matching [data-key-action]
 *     element on the currently visible screen -> click it. It holds no
 *     arm/disarm state of its own; the DOM (an action-bar's
 *     data-armed="true"/"false") is where that state actually lives.
 *   - Esc is context-sensitive: an armed bar treats it (like any other
 *     key) as "disarm"; otherwise it is "up a level" (same as a).
 *   - `n` focuses the note input rather than dispatching a server call
 *     (09 §1: "an inline single-line input in the action bar"). On an
 *     ARMED bar there is no note input to focus, so `n` is a no-op with
 *     a hint — never a cancel, which used to destroy the pending action.
 *   - Keys are inert while focus is in a text input (above) — ONE
 *     exception to "inert", never a second: `?` while focused in a text
 *     input still shows a plain-words hint (never preventDefault, never
 *     stealing the keystroke — the character still reaches the field
 *     exactly as typed). `?` is a UI walk defect fix: it was silently
 *     swallowed with zero feedback, read as a broken shortcut rather
 *     than a field doing its job. No OTHER bound key gets this — every
 *     other one is an ordinary English letter (e/s/w/d/o/…) that
 *     appears constantly in prose, and hinting on each occurrence would
 *     be far noisier than today's silence; `?` is the one bound key
 *     that is both rare in prose and the shortcut a user reaches for
 *     out of habit when unsure what to press.
 */

(function () {
  "use strict";

  function loadKeymap() {
    const el = document.getElementById("self-learn-ui-keymap");
    if (!el || !el.textContent) {
      return [];
    }
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      console.error("self-learn-ui: failed to parse keymap blob", err);
      return [];
    }
  }

  function focusIsTextInput() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable === true;
  }

  const KEYMAP = loadKeymap();

  function findArmedBar() {
    return document.querySelector('.action-bar[data-armed="true"]');
  }

  /** N10 (code gate r2): the identity of the record currently on
   * screen, read from the ONE place it is stamped -- the detail
   * page's `<article data-record-id>` (absent on Front, which has no
   * single record). Used to catch a deferred clickAction() intent
   * that has gone stale because the record itself changed underneath
   * it, not just because its target element moved. */
  function currentRecordId() {
    const article = document.querySelector("[data-record-id]");
    return article ? article.getAttribute("data-record-id") : null;
  }

  /**
   * UI-walk defect fix: keyboard `b` (toggle_brief) "did nothing
   * visible" — measured, not assumed. On a Detail page long enough to
   * scroll, the episode-brief `<details>` this action toggles can sit
   * well above the human's current scroll position (Finding, near the
   * top, while they're reading Why/the action bar further down); the
   * DOM toggle was always real (the `<details>` element's own `.open`
   * genuinely flips), but with nothing on screen changing, "the key
   * does nothing" is exactly what it reads as. Confirmed with a
   * scrolled-to-bottom repro: identical before/after screenshots, the
   * toggled element's own `getBoundingClientRect()` landing entirely
   * negative (off-screen above the viewport). `scrollIntoView({block:
   * "nearest"})` is a no-op when the target is already visible (the
   * SAME convention `moveSelection` below already uses for row
   * selection), so this costs nothing for the common case where the
   * dispatched action's target was in view already — it only matters
   * for the off-screen case this defect is about. Applies to every
   * action dispatched through here, not just `b` — the same "the human
   * pressed a key while scrolled away from its target" gap applies
   * to any of them on a long enough page. */
  function clickAction(action) {
    const selector = '[data-key-action="' + action + '"]';
    const el = document.querySelector(selector);
    if (!el) return false;
    // D1 (U-jsdom disposition, 14 §6a, code gate r1): re-resolve BY
    // SELECTOR at fire time, never close over `el` above -- a second
    // overlapping swap landing between defer and fire can detach the
    // element clickAction saw at dispatch time (its container's
    // outerHTML replaced again before the first swap even settled).
    // `.click()` on a detached node is silently inert -- indistinguishable
    // from the outside from "the action just didn't happen" -- so fire()
    // must always act on whatever the LIVE document holds right now,
    // never a reference captured earlier.
    //
    // N10 (code gate r2): re-resolving by selector alone is not
    // enough -- a resolution swap can replace the WHOLE record (A's
    // detail page swapped out for B's) before a deferred click fires,
    // and B's page repeats the same [data-key-action] markup, so the
    // selector would happily find and click INTO B with an intent that
    // was only ever formed against A. The record id is stamped at
    // defer time and re-checked at fire time; a mismatch no-ops
    // (logged, so a dropped fire is diagnosable instead of just
    // silently absent).
    const recordAtDefer = currentRecordId();
    function fire() {
      const recordNow = currentRecordId();
      if (recordNow !== recordAtDefer) {
        console.warn(
          'clickAction("' + action + '"): dropped -- record changed from ' +
            recordAtDefer + " to " + recordNow + " before this deferred click fired"
        );
        return;
      }
      const live = document.querySelector(selector);
      if (!live) return;
      live.click();
      live.scrollIntoView({ block: "nearest" });
    }
    if (unresolvedSwapsExist()) {
      // U-jsdom disposition (14 §6a, code gate r1): this element may
      // have just landed in the DOM via a swap htmx has not finished
      // settling yet, which means htmx has not finished ATTACHING its
      // own hx-post/hx-get listeners to it either — clicking now would
      // click blind into a target that is not htmx-interactive yet.
      // Wait for the settle that finishes that wiring instead of
      // racing it.
      //
      // code gate r2/r3: gated on pendingSwaps -- a BAG of tokens
      // keyed by each request's own identity (M2: its xhr, not merely
      // its target), not a bare counter. See pendingSwaps's own
      // comment for why (M1/M2/N9), and for how it still requires two
      // resolutions for two overlapping swaps sharing the same key.
      //
      // code gate r5 (B-1): gated on unresolvedSwapsExist(), not
      // pendingSwaps alone -- a token silently evicted by its own
      // orphan timeout is UNKNOWN, not resolved (see abandonedSwaps'
      // own comment below). Reproduced without this: a fresh dispatch
      // landing right after such an eviction saw pendingSwaps read
      // empty and took this branch's `else` path, clicking blind into
      // content that had swapped but never actually settled.
      //
      // N1: this call is queued into the SHARED pendingDispatches
      // array, drained together by releasePendingDispatches() —
      // never a private listener this call alone owns. Measured
      // without that: a key pressed FIRST could fire ~499ms AFTER a
      // key pressed later, because the first one's own request failed
      // (an F14 leg) while it sat waiting on an `afterSettle` that was
      // never coming, and nothing told it to stop waiting — only ITS
      // OWN fallback timer, half a second later, ever released it
      // (`[reject@4ms, route@503ms]`). A shared queue drained on
      // EVERY resolution path (a real settle OR any F14 failure that
      // owns the pending target) is released the instant we know it's
      // safe, never merely when its own private timer happens to
      // expire.
      //
      // N12 (code gate r3): each pendingSwaps token bounds ITSELF to
      // 500ms (addPendingSwap's own comment), but that alone does not
      // bound THIS dispatch -- a continuous stream of overlapping
      // swaps (a new token always landing before the bag empties) can
      // keep the bag non-empty far longer than any single token's own
      // 500ms. So this dispatch also gets its OWN independent 500ms
      // fallback timer -- but see N17 below for what that timer does
      // when it actually fires; it is bounded, not a license to fire.
      //
      // N17 (code gate r4, fail-closed): this timer firing at ALL
      // means the bag did NOT empty within 500ms of this dispatch --
      // if it had, releasePendingDispatches() would already have
      // cleared this timer and fired the click for real (see there).
      // The gate reproduced what firing BLIND here actually does:
      // with a real settle delay of 1500ms (CPU starvation stretches
      // a real one just as far), the r3 dispatch fired at its own
      // 500ms mark onto a `<button type="submit">` htmx had not yet
      // finished wiring -- the form's native, un-intercepted
      // submission ran instead, a plain GET to the current URL with
      // its hidden fields as a query string, navigating the page out
      // from under everything. That is the ORIGINAL bug this whole
      // unit exists to fix, re-entering under CPU starvation. This
      // 500ms bound is a LIVENESS guarantee (never wedge a keystroke
      // forever waiting on a swap that will never resolve) -- it is
      // NOT a license to act on a swap that merely hasn't resolved
      // YET. So: never `.click()` a form that has not settled. DROP
      // the dispatch instead -- the entry is discarded (liveness
      // kept: nothing is left pending, so nothing is stuck), the bar
      // is left exactly as it was (nothing was clicked, so nothing
      // changed -- the NEXT keypress dispatches normally, and fires
      // for real once the swap actually does settle), and exactly one
      // `console.warn` names the record and how long it waited, so a
      // dropped keystroke is diagnosable instead of silently absent.
      const deferredAt = performance.now();
      const entry = { fire: fire, timer: null };
      entry.timer = setTimeout(function () {
        const idx = pendingDispatches.indexOf(entry);
        if (idx !== -1) pendingDispatches.splice(idx, 1);
        const elapsed = Math.round(performance.now() - deferredAt);
        console.warn(
          'clickAction("' + action + '"): dropped -- record ' +
            recordAtDefer + "'s swap had not settled after " + elapsed +
            "ms (fallback bound); never fired"
        );
      }, 500);
      pendingDispatches.push(entry);
    } else {
      fire();
    }
    return true;
  }

  function toggleHelp() {
    const overlay = document.getElementById("self-learn-ui-help");
    if (!overlay) return;
    overlay.hidden = !overlay.hidden;
  }

  function focusNote() {
    // The note input lives in the unarmed bar only — there is nothing to
    // focus while a confirm strip is up, which is why the armed branch
    // no-ops `n` with a hint instead of calling this.
    const input = document.querySelector('.action-bar input[name="note"]');
    if (input) input.focus();
  }

  /** w/s (and arrows) move a `.selected` marker among the visible
   * [data-row] elements within #self-learn-ui-content (Front's bucket
   * table, a Bucket page's record rows). Enter/d/ArrowRight opens the
   * selected row's link. */
  function rows() {
    return Array.from(document.querySelectorAll("#self-learn-ui-content [data-row]"));
  }

  function moveSelection(delta) {
    const list = rows();
    if (!list.length) return;
    let idx = list.findIndex((r) => r.classList.contains("selected"));
    list.forEach((r) => r.classList.remove("selected"));
    idx = idx === -1 ? 0 : Math.max(0, Math.min(list.length - 1, idx + delta));
    list[idx].classList.add("selected");
    list[idx].scrollIntoView({ block: "nearest" });
  }

  function drillIntoSelection() {
    const list = rows();
    const current = list.find((r) => r.classList.contains("selected")) || list[0];
    if (!current) return;
    const link = current.querySelector("a[href]");
    if (link) window.location.href = link.getAttribute("href");
  }

  /**
   * 09 §11 Y-19 item 3 (survey P1a): the first actionable row is
   * selected on load, not just on the first w/s press. Every navigation
   * in this app is a full document load (queue-walk hops arrive via
   * HX-Redirect, SSE/poll refreshes go through the reload() chokepoint
   * below — there is no htmx partial swap that
   * changes the row list), so a single DOMContentLoaded hook covers
   * "on load AND every queue-walk hop" without a second wiring point.
   * A no-op when a row is already selected (defensive — nothing in this
   * app currently pre-renders .selected, but a future server-side
   * default per the survey's alternative mechanism must not fight this).
   */
  function ensureRowSelected() {
    const list = rows();
    if (!list.length) return;
    if (list.some((r) => r.classList.contains("selected"))) return;
    list[0].classList.add("selected");
  }

  /**
   * 09 §11 Y-19 item 3: guarantee the keyboard contract is live without
   * a prior click, by making sure nothing UNEXPECTED already holds
   * focus. The keydown handler is document-level and only goes inert
   * inside a text input (focusIsTextInput above), so a fresh document
   * load already works without this — this is the belt for the survey's
   * own robustness framing, not a fix for an observed dead key. It must
   * NEVER steal focus from a pane's send input (a live Iterate/bucket
   * chat session) or from the note field inside an armed/unarmed action
   * bar (the U14/Y-16 armed-bar and error-strip focus behaviors this
   * item must not break) — so it only acts when the active element is
   * still the untouched document default (body/html), never when
   * something has already, legitimately, taken focus.
   */
  function ensureContentFocus() {
    const content = document.getElementById("self-learn-ui-content");
    if (!content || typeof content.focus !== "function") return;
    const active = document.activeElement;
    if (active && active !== document.body && active !== document.documentElement) {
      return; // something already holds focus on purpose — never steal it
    }
    content.focus({ preventScroll: true });
  }

  document.addEventListener("DOMContentLoaded", function () {
    ensureRowSelected();
    ensureContentFocus();
  });

  /** Esc-in-pane interrupts the stream FIRST (keymap.py's "up" row: "Back
   * / up a level (interrupts the pane first, if focused)" — 09 §2.4). The
   * interrupt control (pane.html) only renders while a turn is plausibly
   * in flight (starting/streaming/interrupting — pane.py's
   * INTERRUPTIBLE_STATES), so an idle/ended pane falls straight through
   * to ordinary up-navigation instead of swallowing the keypress. */
  function isPaneInterruptible() {
    const region = document.querySelector(".pane-region[data-pane-state]");
    if (!region) return false;
    const state = region.getAttribute("data-pane-state");
    return state === "starting" || state === "streaming" || state === "interrupting";
  }

  function goUp() {
    if (isPaneInterruptible() && clickAction("interrupt")) return;
    if (clickAction("up")) return;
    window.history.back();
  }

  /**
   * F5-3 (feedback round 5, U19 §1.1 — help-overlay key containment):
   * while the overlay is visible, ANY plain keydown closes it and stops
   * — no key reaches the armed-bar branch, the KEYMAP dispatch, or
   * goUp(). The overlay's own text ("Press ? again, or any other key,
   * to dismiss") is the promise this makes true; before this fix Escape
   * fell through to goUp() -> clickAction("interrupt") and silently
   * cancelled a running Iterate. Ordering (gate n11): runs AFTER the
   * text-input guard and the modifier-chord guard above, BEFORE every
   * dispatch branch below (including the `?` toggle) — `?` keeps its
   * toggle semantics only as a side effect: this branch handles the
   * close half, the toggle's open half is the fallthrough when the
   * overlay is already hidden. No focus trap, no new modal machinery —
   * a visibility check + early return, nothing else.
   */
  function helpOverlayVisible() {
    const overlay = document.getElementById("self-learn-ui-help");
    return !!overlay && !overlay.hidden;
  }

  function onKeyDown(event) {
    if (focusIsTextInput()) {
      // UI-walk defect: `?` was silently swallowed here like every other
      // key while focus is in a text input (that rule is correct and
      // stays, per this file's header contract) — but with NO feedback
      // that it happened, a documented global shortcut just looked
      // broken. NEVER preventDefault and never an early return that
      // skips typing it: the character must still land in the field
      // exactly as if this branch didn't exist. Scoped to `?` alone —
      // see the header contract for why no other bound key gets this.
      if (event.key === "?") {
        showNoopHint("? types into this field — click away, then ? for Help.");
      }
      return;
    }
    if (event.ctrlKey || event.altKey || event.metaKey) return; // no chords, ever

    if (helpOverlayVisible()) {
      hideNoopHint(); // any key also clears a stale hint (F5-1/2 below)
      toggleHelp(); // overlay is visible -> this closes it
      return;
    }

    if (event.key === "?") {
      toggleHelp();
      return;
    }

    hideNoopHint(); // F5-1/2: any key clears a stale no-op hint

    const armed = findArmedBar();
    if (armed) {
      event.preventDefault();
      if (event.key === "Enter") {
        clickAction("confirm");
      } else {
        // The armed strip advertises "n to say why" one line below "any
        // other key cancels", and this branch honoured only the second:
        // pressing the key the UI offered silently threw the pending
        // action away, with no note and no message. Found in a UI walk —
        // the walker followed the on-screen hint and lost the denial it
        // was in the middle of.
        //
        // `n` is now IGNORED here rather than cancelling. The note input
        // exists only on the unarmed bar, so `n` cannot do what the hint
        // implies from this state — but destroying a half-made decision
        // is the worst of the three options. It no-ops and says why,
        // using the same hint channel every other dead key uses, and the
        // strip's own wording now tells you to cancel first.
        if (event.key === "n") {
          showNoopHint("Cancel first (Esc), then n to add a note.");
          return;
        }
        clickAction("disarm");
      }
      return;
    }

    const entry = KEYMAP.find((row) => row.keys.includes(event.key));
    if (!entry) return;

    switch (entry.action) {
      case "move_down":
        moveSelection(1);
        break;
      case "move_up":
        moveSelection(-1);
        break;
      case "drill_in":
        drillIntoSelection();
        break;
      case "up":
        goUp();
        break;
      case "note":
        focusNote();
        break;
      case "help":
        toggleHelp();
        break;
      default:
        dispatchOrHint(entry.action);
    }
  }

  /**
   * F5-1/F5-2 (feedback round 5, U19 §1.2 — silent no-op key feedback).
   * Two reported-dead keys (`o` on a single-element destination cycle,
   * `b` on a record without an episode brief) turned out to work, but
   * no-op silently when gated — this gives every such gate a plain-words
   * hint instead of nothing. ONE dispatch-site hook for BOTH shapes the
   * server can signal (gate M1: the client never derives a no-op on its
   * own, it only reads what's rendered):
   *   1. present-but-noop — the control renders but is server-marked
   *      gated via [data-noop-hint][data-noop-action="<action>"] (the
   *      singleton-cycle `o` case: action_bar.html omits data-key-action
   *      and adds this pair instead).
   *   2. absent-target — nothing rendered for the action at all (no
   *      [data-key-action], no [data-noop-hint]) — a static per-action
   *      message from NOOP_MESSAGES (the briefless `b` case: the whole
   *      <details class="episode-brief"> block is simply absent).
   * A pane-proposal bar that has REPLACED the action bar hits leg 2 with
   * no NOOP_MESSAGES entry for cycle_destination — deliberately silent,
   * no scope message (it would be wrong there, gate M1's replaced-bar
   * pin). The next gated key joins by adding a message here or a
   * data-noop-hint attribute server-side — never a new mechanism.
   */
  const NOOP_MESSAGES = {
    toggle_brief: "no episode brief on this record",
  };

  function dispatchOrHint(action) {
    if (clickAction(action)) return;
    const noop = document.querySelector(
      '[data-noop-hint][data-noop-action="' + action + '"]'
    );
    if (noop) {
      showNoopHint(noop.getAttribute("data-noop-hint"));
      return;
    }
    const message = NOOP_MESSAGES[action];
    if (message) showNoopHint(message);
  }

  /**
   * Y-9 plain words, transient — auto-clears on the next keypress (see
   * onKeyDown's hideNoopHint() calls above) or after NOOP_HINT_MS,
   * whichever comes first. A NEW element (gate m5), never the
   * persistent showBanner register (no auto-clear there, and a banner
   * is meant to survive/stack — this is a single, self-clearing line).
   *
   * UI-walk defect fix (same root cause as clickAction's own comment
   * above): this always PREPENDS to `#self-learn-ui-content`, so on a
   * page long enough to scroll, a human who is not already at the very
   * top never sees it — measured with a scrolled-to-bottom repro
   * (`b` on a record with no episode brief): the inserted hint's own
   * `getBoundingClientRect()` landed entirely negative, off-screen
   * above the viewport, for the full 3s it takes to auto-clear. Same
   * `scrollIntoView({block: "nearest"})` fix, same no-op-when-already-
   * visible property.
   */
  const NOOP_HINT_MS = 3000;
  var noopHintTimer = null;

  function showNoopHint(text) {
    const main = document.getElementById("self-learn-ui-content");
    if (!main) return;
    hideNoopHint();
    const p = document.createElement("p");
    p.className = "noop-hint";
    p.setAttribute("data-noop-hint-active", "true");
    p.textContent = text;
    main.prepend(p);
    p.scrollIntoView({ block: "nearest" });
    noopHintTimer = window.setTimeout(hideNoopHint, NOOP_HINT_MS);
  }

  function hideNoopHint() {
    if (noopHintTimer) {
      window.clearTimeout(noopHintTimer);
      noopHintTimer = null;
    }
    const el = document.querySelector("[data-noop-hint-active]");
    if (el) el.remove();
  }

  document.addEventListener("keydown", onKeyDown);

  /**
   * Front bucket-table column sort (feedback round 1 item 1). Click a
   * header to sort by that column; click again to flip direction. Sorting
   * reorders the ACTUAL tbody rows, so w/s selection (rows() reads DOM
   * order) follows the sort with no extra state. Cells carry
   * data-sort-value so "—" and "12d" render text never feeds the compare.
   */
  function sortValue(row, key, type) {
    const cell = row.querySelector('td[data-sort-key="' + key + '"]');
    const raw = cell ? cell.getAttribute("data-sort-value") : "";
    return type === "number" ? parseFloat(raw || "0") : (raw || "");
  }

  function sortBucketTable(button) {
    const key = button.getAttribute("data-sort-key");
    const type = button.getAttribute("data-sort-type") || "text";
    const table = button.closest("table");
    const tbody = table && table.querySelector("tbody");
    if (!key || !tbody) return;

    const th = button.closest("th");
    const ascending = th.getAttribute("aria-sort") !== "ascending";
    table.querySelectorAll("th[aria-sort]").forEach(function (other) {
      other.setAttribute("aria-sort", "none");
    });
    th.setAttribute("aria-sort", ascending ? "ascending" : "descending");

    Array.from(tbody.querySelectorAll("tr"))
      .sort(function (a, b) {
        const va = sortValue(a, key, type);
        const vb = sortValue(b, key, type);
        const cmp = type === "number" ? va - vb : String(va).localeCompare(String(vb));
        return ascending ? cmp : -cmp;
      })
      .forEach(function (row) {
        tbody.appendChild(row);
      });
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest && event.target.closest("button[data-sort-key]");
    if (button) sortBucketTable(button);
  });

  /**
   * EventSource client for GET /events (09 §3 / 10 §1 SSE protocol row).
   * `refresh` re-requests the current partial when in scope; `banner`
   * shows a one-line notice; unknown types are ignored (10 §1).
   * Reconnect: EventSource auto-retries; the reconnect strip shows while
   * the connection is down, and a 10s poll covers the gap (09 §5).
   */
  const POLL_FALLBACK_MS = 10000;

  /**
   * The scope(s) THIS page currently cares about. The watcher
   * (ledger.py's _scope_for_path) only ever emits "front" or
   * "bucket:<name>" for filesystem changes — it has no per-record
   * granularity, since a directory-level watch event doesn't know which
   * file within it changed. Explicit post-action pushes (a resolution
   * verb, a pane session's file_changed/result) DO push "record:<id>"
   * for the exact record acted on. Detail therefore must watch BOTH its
   * own record scope (explicit pushes) AND its own bucket scope
   * (watcher-driven changes, including an EXTERNAL resolution via a
   * concurrent CLI verb this server never sees a POST for — 09 §3/§5
   * "resolved elsewhere"/P3-8). Front has no [data-record-id]/data-bucket
   * of its own; "front" is its only scope, but see inScope() below for
   * why that still catches bucket-scoped events too (Front aggregates
   * every bucket's counts, so any bucket change is relevant to it).
   */
  function currentScopes() {
    const scopes = [];
    const article = document.querySelector("[data-record-id]");
    if (article) scopes.push("record:" + article.getAttribute("data-record-id"));
    const body = document.body;
    if (body && body.dataset && body.dataset.bucket) scopes.push("bucket:" + body.dataset.bucket);
    if (scopes.length === 0) scopes.push("front");
    return scopes;
  }

  function inScope(scope) {
    if (scope === "front") return true; // a front-scoped event is a broadcast
    const mine = currentScopes();
    if (mine.indexOf("front") !== -1) return true; // the Front page matches every scope
    return mine.indexOf(scope) !== -1;
  }

  /**
   * Y-16 (09 §11, U14): the client's single reload() CHOKEPOINT. Every
   * client-initiated full reload — the SSE `refresh` handler, the 10s
   * poll fallback, the `pane_proposal` handler's legs, and any future
   * path — routes through here, so the defer is structural, not
   * per-caller (F3). Reloads DEFER (never drop) while ANY leg holds:
   *   (a) a [data-verb-error] element is in the document — the
   *       persistent error rendering a broadcast reload would erase
   *       (the empirically pinned wipe: the runner's post-verb
   *       front-scope push, see tests/test_registration_wipe.py and
   *       10's appendix U14 entry). FW-76 adds a SECOND producer of
   *       this SAME marker: the applying/bulk-progress strip's own
   *       renderInflight (§2.1, below) — a failed Force run holds
   *       this leg exactly like a failed verb-confirm does;
   *   (b) a verb-confirm POST is in flight — flag set at submit,
   *       cleared at swap settle on success and on error/abort
   *       regardless (F4/F14: the runner queues the failure push
   *       BEFORE the confirm route renders the error partial, so the
   *       SSE frame can beat the htmx swap; a marker-only predicate
   *       re-creates the original symptom);
   *   (c) any [data-armed="true"] bar exists — releasing on re-arm
   *       would reload over the fresh armed bar (F5, the Y-15
   *       delta-R1 never-clobber-a-human-mid-decision hazard).
   *   (d) a [data-contradicts-offer] element is in the document (U-C3,
   *       09 §11 Y-8): the post-route contradicts offer renders every
   *       edge UNARMED (leg (c) alone does not hold it), yet the SAME
   *       action that swapped it in also fires the routine post-verb
   *       forced-refresh push (09 §3) — often arriving while this very
   *       response is still settling. Without this leg that refresh
   *       reloads the page out from under the human before they can
   *       arm a single edge, silently discarding the offer exactly the
   *       way the pre-fix server bug did, just one layer up. No
   *       explicit release exists for this leg (unlike (a)/(c)) — the
   *       pinned resolution is always a full page navigation (arming
   *       and confirming an edge redirects away; leaving by any other
   *       route loads a fresh document with no marker at all), so
   *       "stale until the human leaves" is the intended, permanent
   *       hold for this leg specifically.
   *   (e) retired — U-hostmode Phase 2 (2026-08-28) deleted the adopt
   *       offer this leg deferred for (§10.4(a) is gone: no route ever
   *       renders a [data-adopt-offer] element any more), so there is
   *       nothing left for a leg here to hold. Letter kept as a gap,
   *       never reused, so history stays legible.
   *   (f) a [data-verb-success] element is in the document
   *       (resolution-evidence unit, §3.5 ruling): the success leg is
   *       the error leg's sibling (§2.2 "one surface, two legs") —
   *       SAME hazard as leg (a), same fix. action_bar.html's own note
   *       above records the mechanism this leg exists to close: a
   *       FakeRunner test never pushes the post-subprocess refresh, so
   *       a persistent strip with no defer marker looks fine under test
   *       and gets reload-wiped by the very next broadcast SSE refresh
   *       in production — this project's signature bug, landing again
   *       at the exact file being extended. Release is navigation-only
   *       (§3.5: "persistent, no auto-dismiss") — same shape as leg (d),
   *       never an explicit dismiss like (a)/(e).
   * Deferred-not-dropped: the pending reload fires when no leg holds
   * (dismiss removes (a), completion/error/abort clears (b),
   * disarm-or-resolve removes (c), navigating away is (d)'s only
   * release, (e) retired, navigating away is (f)'s only release); the
   * release re-checks the whole predicate.
   * Deliberate staleness (F9/F12): while any leg holds the page may go
   * stale against the files — accepted; files stay truth and every hold
   * has a user-reachable release. The server-side push is UNCHANGED —
   * this defers only the client's render of it.
   */
  var reloadPending = false;
  var confirmInFlight = false;
  /** U-jsdom disposition (14 §6a): htmx does not finish "hydrating"
   * swapped-in content (attaching its own hx-post/hx-get listeners to
   * it) at SWAP time -- only at SETTLE time, a short
   * (htmx.config.defaultSettleDelay, 20ms by default) delay later. A
   * DOM attribute a caller waits on (e.g. an armed bar's
   * `data-armed="true"`) appears at swap time, not settle time, so a
   * key-driven clickAction() dispatched in that gap can target a
   * `<button>` htmx has not wired up yet. For a plain `hx-post`
   * button that is a silent no-op (nothing intercepts the click, and
   * a `type="button"` has no native fallback action of its own); for
   * a `<button type="submit">` inside a `<form>` (the armed bar's
   * confirm/disarm pair) it is worse -- the click's native
   * form-submission default action runs completely un-intercepted:
   * the form (no `method`/`action` of its own) submits as a plain GET
   * to the current URL with its hidden fields serialized as a query
   * string, discarding the intended POST and navigating the page out
   * from under whatever was mid-flight (Page.query_selector:
   * "Execution context was destroyed" is that navigation, observed
   * from the test side). Measured directly: a synthetic `submit`
   * event dispatched on a just-swapped form only came back
   * `defaultPrevented` once `htmx:afterSettle` had fired for that
   * swap -- never before, across 20 samples; waiting for that same
   * event before dispatching a synthetic click made 20/20 samples
   * `defaultPrevented`.
   *
   * pendingSwaps (code gate r2/r3): a BAG of tokens, one per
   * outstanding (swapped, not yet settled-or-failed) request, each
   * carrying a KEY that identifies the ONE request it belongs to.
   * Replaces an r1 plain counter that counted resolutions without
   * asking whose they were.
   *
   * M1 (code gate r2, reproduced end-to-end): the r1 counter's own
   * defect. htmx maps a failing (4xx/5xx) request to `swap:false,
   * error:true` -- NO `htmx:afterSwap` ever fires for it, so that
   * request was never counted in. But the r1 counter's F14 failure
   * legs decremented UNCONDITIONALLY on ANY failure, so an unrelated
   * request's failure could still consume the decrement a genuinely
   * pending, DIFFERENT swap owned -- draining queued clicks into
   * content that was never wired (a native GET navigation where the
   * fixed build should have POSTed).
   *
   * M2 (code gate r3): the r2 fix above scoped removal by TARGET
   * (`evt.detail.target`), which closes M1 but is still only an
   * APPROXIMATE key -- every arm/confirm/disarm request on one action
   * bar targets the SAME element, so a failing request aimed at that
   * element could still remove a token a DIFFERENT, genuinely live
   * request on the SAME element owned, reproducing the identical
   * native-GET failure M1 fixed, just narrowed to same-target
   * collisions. Keyed instead by `evt.detail.xhr` -- the actual
   * request object htmx attaches, unique PER REQUEST rather than per
   * element -- falling back to `evt.detail.target` only when no xhr
   * is present at all (a synthetic event with no real request behind
   * it; htmx's own events always carry one). `pendingSwapKey()` below
   * computes it once, used identically by the add leg and both
   * removal legs. Per-request identity, not target, is what an F14
   * failure leg's removal must be scoped to: a failure whose OWN
   * request never swapped -- whatever its target -- removes nothing.
   *
   * N9 (code gate r2): each token carries its OWN 500ms fallback
   * timer (addPendingSwap below), not a queue-level one -- so a swap
   * that never settles and never fails (an orphaned afterSwap)
   * self-evicts after 500ms regardless of any other token's state.
   * Under the r1 counter this never healed: an orphaned increment
   * permanently occupied the counter, so even a LATER, fully balanced
   * afterSwap/afterSettle cycle could only bring it from 2 back to 1
   * -- never to 0 -- leaving every subsequent keystroke ~503ms late
   * forever, not just the one racing the orphan itself.
   *
   * Two swaps overlapping in flight for the SAME request key still
   * require TWO resolutions: each `htmx:afterSwap` pushes its own
   * token, so a single `htmx:afterSettle` only removes one, leaving
   * the bag non-empty -- the double-swap guarantee N3 established,
   * preserved here per-key rather than via a shared count.
   *
   * pendingDispatches (N1, code gate r1; N12, code gate r3): every
   * clickAction() call deferred while the bag is non-empty is queued
   * HERE, as a shared array, rather than each call owning a private
   * `htmx:afterSettle` listener of its own. Drained together by
   * releasePendingDispatches() the instant the bag empties -- from
   * WHICHEVER token's removal got it there, including a token's own
   * N9 fallback. A private per-call listener has no way to learn that
   * a DIFFERENT leg (an F14 failure owning a DIFFERENT request, say)
   * already resolved the wait; measured live under the r1 design: a
   * key pressed FIRST could fire ~499ms AFTER a key pressed later
   * this way (`[reject@4ms, route@503ms]`) -- the first one's own
   * request failed, but with no shared drain, only ITS OWN fallback
   * timer ever released it. Each dispatch ALSO carries its own 500ms
   * fallback (N12, clickAction's own comment) as a second, independent
   * bound alongside the bag -- a continuous stream of overlapping
   * swaps can keep the bag non-empty far longer than any one token's
   * own 500ms. */
  const pendingSwaps = [];
  const pendingDispatches = [];

  // B-1/B-2 (code gate r5): pendingSwaps.length === 0 was being read
  // as a POSITIVE signal that clicking is safe -- but a token's own
  // 500ms orphan timeout (addPendingSwap's N9/N17 self-eviction) only
  // ever means "we gave up WAITING on this one," never "it resolved."
  // Before this set existed, a silently-evicted token just vanished,
  // so the bag could read "empty" while the swap it represented was
  // genuinely still unsettled -- reproduced two ways: (B-1) a FRESH
  // clickAction() landing right after such an eviction took the
  // un-gated `else { fire(); }` path and clicked blind; (B-2) an
  // UNRELATED request's own real settle brought pendingSwaps to zero
  // and drained a DIFFERENT, already-queued dispatch that was
  // actually waiting on the evicted swap, never the one that just
  // resolved.
  //
  // abandonedSwaps holds exactly the keys self-eviction has moved out
  // of pendingSwaps -- their fate is UNKNOWN, not resolved -- and it
  // gates identically to pendingSwaps everywhere that matters:
  // unresolvedSwapsExist() (clickAction's own check, B-1) and
  // removePendingSwapForKey()'s drain condition (B-2) both require
  // THIS to be empty too, not just pendingSwaps. A key leaves this
  // set only when its OWN real resolution eventually arrives -- a
  // late htmx:afterSettle or F14 failure carrying the SAME key, via
  // removePendingSwapForKey below -- there is no second timeout of
  // its own. A key that never gets a real resolution stays here, and
  // every future dispatch keeps deferring (then dropping, per its own
  // N12/N17 bound) until it does. That is a liveness cost, not a
  // correctness one: Layer 2 below (the submit guard) is what makes
  // even a hole in THIS bookkeeping harmless, which is what lets this
  // set stay conservative rather than clever about when to give up.
  const abandonedSwaps = [];

  // B-1 (code gate r5): the one gating question clickAction() and
  // removePendingSwapForKey()'s drain condition both ask -- "is there
  // anything whose outcome we do not yet know for certain?" --
  // answered by BOTH sets together, never pendingSwaps alone.
  function unresolvedSwapsExist() {
    return pendingSwaps.length > 0 || abandonedSwaps.length > 0;
  }

  // M2 (code gate r3): the request's own key, shared by the add leg
  // and both removal legs below. Prefers `evt.detail.xhr` (unique per
  // REQUEST); falls back to `evt.detail.target` only when no xhr is
  // present (a synthetic event with no real request behind it); falls
  // back to `undefined` (itself a valid, stable key, compared with
  // `===`) when neither is present.
  function pendingSwapKey(evt) {
    const d = evt && evt.detail;
    if (!d) return undefined;
    if (d.xhr) return d.xhr;
    return d.target;
  }

  // Bounded regardless (htmx's own default settle delay is 20ms; 500ms
  // is a generous multiple, chosen to stay invisible to a human while
  // still being a real bound) so a swap that somehow never settles and
  // never fails can't wedge key dispatch permanently — defense in
  // depth under the bag/queue above, not the primary guard.
  //
  // N17 (code gate r4, fail-closed): this timer firing means the swap
  // did NOT settle or fail within the bound -- it does NOT mean the
  // swap is done; it may still be genuinely in flight (a real settle
  // delay stretched by CPU starvation, exactly what the gate
  // reproduced at 1500ms). Removing the token here is bookkeeping
  // ONLY -- it must never itself drain pendingDispatches. Measured
  // live: without this split, an orphaned token's own timeout could
  // bring the bag to zero and releasePendingDispatches() would fire a
  // QUEUED click for real onto a swap that had only TIMED OUT, never
  // actually settled -- the exact native-GET bug N17 exists to close,
  // reached through this second door instead of the dispatch's own
  // fallback. Only removePendingSwapForKey() below (driven by a REAL
  // htmx:afterSettle or an F14 failure that owns this key) may ever
  // call releasePendingDispatches() -- a timeout is a reason to stop
  // WAITING on this one token, never a reason to declare victory.
  function addPendingSwap(key) {
    const token = { key: key, timer: null };
    token.timer = setTimeout(function () {
      removePendingSwapSilently(token);
    }, 500);
    pendingSwaps.push(token);
  }

  // Removes at most ONE token owned by `key` (FIFO) and drains if
  // nothing is left unresolved. Used by afterSettle (which always
  // owns a token for its own request, barring a defect elsewhere) and
  // by an F14 failure leg (which may legitimately own NONE -- see
  // M1/M2 above: a request whose OWN key never swapped has no token
  // to remove, regardless of what target it shares with some other
  // request). This is the ONLY path that may drain pendingDispatches
  // -- see N17's note on addPendingSwap above for why.
  //
  // code gate r5 (B-1/B-2): a matching key can be sitting in EITHER
  // set -- still in pendingSwaps (the common case: its own real
  // resolution arrived before its 500ms self-eviction did) or already
  // moved to abandonedSwaps (a LATE resolution, arriving AFTER that
  // eviction -- the only thing that ever clears an abandoned entry;
  // see abandonedSwaps' own comment). Either way this is the one
  // place a key's REAL, definitive outcome becomes known, so either
  // way it is removed from wherever it currently sits. The drain
  // condition checks BOTH sets: an unrelated key's resolution
  // emptying pendingSwaps while a DIFFERENT key still sits in
  // abandonedSwaps must not release a dispatch that is actually
  // waiting on the abandoned one (B-2) -- draining requires nothing
  // outstanding ANYWHERE, not merely that pendingSwaps itself is
  // empty.
  function removePendingSwapForKey(key) {
    const idx = pendingSwaps.findIndex(function (t) {
      return t.key === key;
    });
    if (idx !== -1) {
      clearTimeout(pendingSwaps[idx].timer);
      pendingSwaps.splice(idx, 1);
    } else {
      const aIdx = abandonedSwaps.indexOf(key);
      if (aIdx !== -1) abandonedSwaps.splice(aIdx, 1);
    }
    if (pendingSwaps.length === 0 && abandonedSwaps.length === 0) {
      releasePendingDispatches();
    }
  }

  // A token's own orphan/timeout removal (N17): bookkeeping only,
  // deliberately never drains pendingDispatches -- see addPendingSwap's
  // own comment.
  //
  // code gate r5 (B-1/B-2): the token does not simply vanish -- its
  // key moves to abandonedSwaps, which keeps gating exactly like
  // pendingSwaps did until this SAME key's real resolution eventually
  // arrives (removePendingSwapForKey above). Before this: a vanished
  // token left pendingSwaps.length reading "safe" while the swap it
  // represented was still genuinely in flight -- see abandonedSwaps'
  // own comment for both ways that lied (B-1/B-2).
  function removePendingSwapSilently(token) {
    const idx = pendingSwaps.indexOf(token);
    if (idx === -1) return; // already removed by a real settle/failure
    clearTimeout(token.timer);
    pendingSwaps.splice(idx, 1);
    abandonedSwaps.push(token.key);
  }

  function releasePendingDispatches() {
    const toRun = pendingDispatches.splice(0, pendingDispatches.length);
    toRun.forEach(function (entry) {
      clearTimeout(entry.timer); // N12: cancel the dispatch's own fallback, it already fired
      entry.fire();
    });
  }

  function reloadDeferred() {
    if (document.querySelector("[data-verb-error]")) return true; // leg (a)
    if (confirmInFlight) return true; // leg (b)
    if (findArmedBar()) return true; // leg (c)
    if (document.querySelector("[data-contradicts-offer]")) return true; // leg (d)
    // leg (e) retired — see the docblock above.
    if (document.querySelector("[data-verb-success]")) return true; // leg (f)
    return false;
  }

  function reload() {
    if (reloadDeferred()) {
      reloadPending = true; // deferred, never dropped
      return;
    }
    window.location.reload();
  }

  function releaseReload() {
    if (reloadPending) {
      reloadPending = false;
      reload(); // re-checks the predicate; re-defers if a leg still holds
    }
  }

  /** Leg (b)'s flag: a verb-confirm POST (any .../confirm route) in
   * flight. Set at htmx's request start; cleared unconditionally on
   * completion (swap settle), error, or abort (the F14 fold) — a
   * confirm that dies without a response must never leave the tab
   * deferring reloads until a manual refresh. */
  function isConfirmRequest(evt) {
    var d = evt.detail || {};
    var path =
      (d.requestConfig && d.requestConfig.path) ||
      (d.pathInfo && (d.pathInfo.finalRequestPath || d.pathInfo.requestPath)) ||
      "";
    return typeof path === "string" && /\/confirm$/.test(path);
  }

  document.addEventListener("htmx:beforeRequest", function (evt) {
    if (isConfirmRequest(evt)) confirmInFlight = true;
  });
  // pendingSwaps' own add leg: a swap just landed new content for
  // this request's OWN key (M2: its xhr, not merely its target) — one
  // more resolution (its OWN settle or an F14 failure that owns it)
  // now owed, bounded by its own N9 fallback regardless.
  document.addEventListener("htmx:afterSwap", function (evt) {
    addPendingSwap(pendingSwapKey(evt));
  });
  // Success leg: cleared at swap SETTLE (never earlier — the error
  // marker must be in the DOM before leg (b) lets go, else the raced
  // SSE frame wipes it in the settle gap). Every settle also attempts
  // release: dismiss/disarm swaps are what remove legs (a)/(c).
  document.addEventListener("htmx:afterSettle", function (evt) {
    if (isConfirmRequest(evt)) confirmInFlight = false;
    removePendingSwapForKey(pendingSwapKey(evt)); // N1, drains at zero
    releaseReload();
  });
  // Failure legs (F14, extended to pendingSwaps/pendingDispatches,
  // M1/M2/N1): no swap will come for THIS request — remove ONLY the
  // token this request's OWN key owns (M1/M2: a request whose OWN key
  // never swapped owns no token, regardless of what TARGET it shares
  // with some other, genuinely live request — an UNRELATED failure
  // must never release a DIFFERENT request's pending swap, even one
  // aimed at the identical element). Draining happens immediately
  // once nothing is left pending; this is what stops a deferred click
  // from waiting out its own fallback timer once its OWN failure
  // already tells us it's safe to fire now.
  ["htmx:responseError", "htmx:swapError", "htmx:sendError", "htmx:sendAbort", "htmx:timeout"].forEach(
    function (name) {
      document.addEventListener(name, function (evt) {
        if (isConfirmRequest(evt)) confirmInFlight = false;
        removePendingSwapForKey(pendingSwapKey(evt));
        releaseReload();
      });
    }
  );

  // Layer 2 (code gate r5, the durable guard). Ruling: every round of
  // bugs this unit has found (r1 through r5) caused harm through
  // exactly ONE mechanism -- a native, un-intercepted form submission
  // navigating the page, because htmx had not yet attached its own
  // interception to the form being clicked (the swap/settle gap this
  // whole unit exists to close, entered through one new door each
  // round). That mechanism is narrower than every way the pendingSwaps
  // / pendingDispatches / abandonedSwaps bookkeeping above can be
  // wrong -- and there is no proof B-1/B-2 above are the LAST way.
  // This guard does not depend on any of that bookkeeping at all: a
  // capture-phase `submit` listener on `document` runs before the
  // target form's own listeners (htmx's included), and can veto the
  // native submission directly whenever htmx has not finished wiring
  // THIS specific form -- converting a click that lands in the race
  // into NOTHING HAPPENING (a dropped keystroke) instead of a
  // destroyed page.
  //
  // The check asks htmx directly, not this file's own bag: htmx marks
  // an element's own internal bookkeeping object (a private expando,
  // `elt["htmx-internal-data"]`) with `firstInitCompleted = true` the
  // instant its own per-node processing -- including attaching this
  // exact submit trigger listener, for the `<form hx-post=...>` shape
  // every armed/commit-drift bar uses -- has finished
  // (htmx-2.0.9.min.js, function `kt`, the last statement before it
  // fires its own `htmx:afterProcessNode`). Reading the property
  // directly, rather than calling htmx's own `getInternalData()`,
  // avoids that function's create-on-read side effect (it lazily
  // creates the object if absent). No public htmx API exposes this
  // marker, so this is a private-implementation dependency -- if it
  // ever reads as `undefined` (a future htmx upgrade renaming or
  // dropping the field), the check below fails CLOSED: "unknown" is
  // treated the same as "not yet wired," and the native submit is
  // blocked rather than assumed safe.
  //
  // Scope note: some forms in this app (the Worker/Miner "Force run"
  // buttons, index.html) carry `hx-post` on the BUTTON rather than the
  // FORM, with an explicit `formmethod`/`formaction` native fallback
  // for genuinely no-JS clients. htmx's default trigger for such a
  // button is "click", not "submit" (getTriggerSpecs' fallback case),
  // so a WIRED click never reaches a native submit at all -- htmx
  // preventDefault()s the click itself before the browser would ever
  // dispatch one. This guard is therefore unreachable for that button
  // in the wired case regardless, and those buttons are never
  // re-swapped by htmx after initial load (Front only ever refreshes
  // via a full, whole-page browser reload -- see the ONE reload()
  // chokepoint below, never a partial swap of that section), so their
  // own race window closes before any human could physically click --
  // this guard cannot regress their no-JS fallback in practice.
  document.addEventListener(
    "submit",
    function (evt) {
      const form = evt.target;
      const data = form && form["htmx-internal-data"];
      const wired = !!(data && data.firstInitCompleted === true);
      if (!wired) {
        evt.preventDefault();
        console.warn(
          "blocked a native form submission -- htmx had not finished " +
            "wiring this form yet (the swap/settle gap); no request was sent"
        );
      }
      // else: htmx has already attached its own submit interception to
      // THIS form -- let it run untouched. It calls preventDefault()
      // itself once it takes over; this listener's job here is done
      // either way.
    },
    true // capture: runs before htmx's own listener has a chance to
    // act, so this can veto BEFORE any AJAX/native path proceeds --
    // irrelevant when htmx has not attached anything yet (there is
    // nothing else to race), and harmless when it has (this branch
    // does nothing).
  );

  function showReconnectStrip(show) {
    const strip = document.getElementById("self-learn-ui-reconnect-strip");
    if (strip) strip.hidden = !show;
  }

  /**
   * §4.3/§5.1: the applying/bulk-progress strip's backing state — a
   * keyed Map of in-flight verb work, NOT a counter+flag (five
   * consecutive spec-gate rounds each found a defect in that shape; see
   * the spec's §4.3 table for why the Map dissolves all of them
   * structurally). Four operations over ONE variable (FW-76 §2.1 adds
   * the fourth):
   *   - `set(key, {badge, detail, failed: false})` — idempotent, so a
   *     duplicate open frame is a no-op by construction.
   *   - `delete(key)` — a no-op on an absent key, so an unmatched
   *     `done` frame can never disturb an entry it doesn't own; also
   *     what releases a failed entry (no producer publishes a terminal
   *     twice for one key, so this can never erase an unseen failure).
   *   - `set(key, {badge: "failed", detail, failed: true})` on `error`
   *     — replaces an applying entry at the same key, or CREATES one
   *     when the key is absent (an error for a key this page never saw
   *     `start` is still a real failure, criterion E1). FW-76's whole
   *     fix: before this, `error` and `done` were the SAME `delete`
   *     branch, so a failed Force run rendered identically to a
   *     succeeded one — strip appears, strip disappears either way.
   *   - `clear()` — SSE connection loss; see connectEventSource's
   *     onerror below.
   * Re-rendered (renderInflight) after EVERY operation so the strip's
   * text can never lag the Map's own contents (R4-m2).
   */
  var inflight = new Map();

  /** Hide-or-render from the Map (§4.3, extended FW-76 §2.1): hidden
   * when empty; otherwise picks, in order, the "bulk" entry if present
   * (it always wins the render while a bulk run is genuinely open —
   * checked BEFORE any failed-entry logic, so a failure never displaces
   * a live bulk run, criterion E2), else the first entry in insertion
   * order that is not failed (live work outranks a failure notice —
   * without this a persisted failed entry sitting first in insertion
   * order would mask a later in-flight verb, S-20's founding defect
   * class re-introduced), else the first entry (an all-failed Map still
   * renders something). Toggles the `hidden` ATTRIBUTE (never inline
   * style) — style.css's `.applying-strip[hidden] { display: none }` is
   * what makes that effective against the two-child `display: flex`
   * layout (§5.3).
   *
   * Two attributes, keyed DIFFERENTLY on purpose (§2.1 — the split is
   * normative, criteria B3/D3 pin both halves):
   *   - `data-verb-error` — Map-scoped: present whenever ANY entry is
   *     failed, even one masked by live work currently rendering. This
   *     is a deliberate reuse of `reloadDeferred()` leg (a) (`:550`,
   *     `[data-verb-error]` document-wide) — keying it on Map contents
   *     rather than on what renders is what stops a failure that is
   *     momentarily masked by live work from being reload-erased before
   *     a human ever sees it (D3; mutation M8 is the rendered-entry
   *     keying).
   *   - `role="alert"` — render-scoped: present only while the RENDERED
   *     entry is the failed one. Parity with this app's other error
   *     surfaces (`action_bar.html`, `host_add_bar.html`), but scoped to
   *     what the strip currently says rather than to the Map (M13 is
   *     the Map-scoped mutation).
   * The marker's absent→present transition scrolls the strip into view
   * (`scrollIntoView({block: "nearest"})`, the idiom this file already
   * uses at `:92`/`:127`/`:378` — a no-op when already visible, so the
   * common case costs nothing); its present→absent transition calls
   * `releaseReload()` — the leg's release, so an unconditional call
   * would give the pre-existing applying path a reload timing it does
   * not have today. */
  function renderInflight() {
    const strip = document.getElementById("self-learn-ui-applying-strip");
    if (!strip) return;
    // Transition detection is done ONCE, at the bottom, over whichever
    // branch below ran — never duplicated per-branch. A Map going empty
    // and a Map losing its last failed entry while still non-empty are
    // the SAME "marker present -> absent" transition from this
    // function's own contract (§2.1), and a builder edit that drops
    // releaseReload() must drop it for BOTH, which a single call site
    // guarantees structurally rather than by convention.
    const hadMarker = strip.hasAttribute("data-verb-error");

    if (inflight.size === 0) {
      strip.hidden = true;
      strip.removeAttribute("data-verb-error");
      strip.removeAttribute("role");
    } else {
      let entry;
      if (inflight.has("bulk")) {
        entry = inflight.get("bulk");
      } else {
        entry = undefined;
        for (const candidate of inflight.values()) {
          if (!candidate.failed) {
            entry = candidate;
            break;
          }
        }
        if (entry === undefined) entry = inflight.values().next().value;
      }
      const badge = document.getElementById("self-learn-ui-applying-badge");
      const text = document.getElementById("self-learn-ui-applying-text");
      if (badge) badge.textContent = entry.badge;
      if (text) text.textContent = entry.detail;
      strip.hidden = false;

      let anyFailed = false;
      for (const candidate of inflight.values()) {
        if (candidate.failed) {
          anyFailed = true;
          break;
        }
      }
      if (anyFailed) {
        strip.setAttribute("data-verb-error", "true");
      } else {
        strip.removeAttribute("data-verb-error");
      }

      if (entry.failed) {
        strip.setAttribute("role", "alert");
      } else {
        strip.removeAttribute("role");
      }
    }

    const hasMarkerNow = strip.hasAttribute("data-verb-error");
    if (!hadMarker && hasMarkerNow) {
      strip.scrollIntoView({ block: "nearest" });
    } else if (hadMarker && !hasMarkerNow) {
      releaseReload();
    }
  }

  function connectEventSource() {
    if (typeof EventSource === "undefined") return null;
    const source = new EventSource("/events");
    let pollTimer = null;

    function startPoll() {
      if (pollTimer) return;
      pollTimer = window.setInterval(reload, POLL_FALLBACK_MS);
    }
    function stopPoll() {
      if (pollTimer) {
        window.clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    source.onopen = function () {
      showReconnectStrip(false);
      stopPoll();
    };
    source.onerror = function () {
      showReconnectStrip(true);
      // §4.3/§5.1 (R5-M1): we have lost the channel that would report
      // completion, so we stop ASSERTING work is running rather than
      // guess with a timer — clear() needs no magic number and is
      // testable through the SSE machinery this client already drives.
      // A late frame arriving after reconnect re-populates the Map and
      // the strip resumes, which is the correct recovery.
      inflight.clear();
      renderInflight();
      startPoll(); // browser auto-retries the SSE connection itself
    };
    source.onmessage = function (event) {
      let envelope;
      try {
        envelope = JSON.parse(event.data);
      } catch (err) {
        console.error("self-learn-ui: malformed SSE frame", err);
        return;
      }
      switch (envelope.type) {
        case "refresh":
          if (inScope(envelope.scope)) reload();
          break;
        case "banner":
          showBanner(envelope.text);
          break;
        case "pane_delta":
          appendPaneDelta(envelope.text);
          break;
        case "pane_block":
          appendPaneBlock(envelope.html);
          break;
        case "pane_tool":
          appendPaneTool(envelope.name, envelope.target);
          break;
        case "pane_proposal":
          handlePaneProposal(envelope);
          break;
        case "pane_result":
          // Y-15 (09 §4.2 / 10 §1 SSE row): the turn's completion. The
          // authoritative completion swap is a re-fetch of the pane
          // panel GET — under the non-blocking start, the result
          // footer / error strip / r retry / validate badge no longer
          // ride any POST response.
          schedulePaneCompletion();
          break;
        case "applying":
          // §4.3/§5.1's per-envelope contract, pinned here (R3-B1): the
          // key is "applying:<verb>:<id>" so two concurrent verbs never
          // collide (test 8) — `set` on "start" is idempotent, `delete`
          // on "done" is a no-op if the key was never set. FW-76 §2.1:
          // `error` is a FOURTH rule, not folded into `done`'s bare
          // delete — it SETS a failed entry (replacing an applying one
          // at the same key, or creating one when the key is absent) so
          // a failed Force run renders differently from a succeeded
          // one, rather than both collapsing to the same
          // strip-appears-then-disappears terminal (the defect this
          // unit fixes — see the spec's §1.1).
          {
            const key = "applying:" + envelope.verb + ":" + envelope.id;
            if (envelope.state === "start") {
              inflight.set(key, {
                badge: "applying",
                detail: envelope.verb + " → " + envelope.id,
                failed: false,
              });
            } else if (envelope.state === "error") {
              inflight.set(key, {
                badge: "failed",
                detail: envelope.verb + " → " + envelope.id,
                failed: true,
              });
            } else {
              inflight.delete(key);
            }
          }
          renderInflight();
          break;
        case "bulk_progress":
          // Terminal iff done==total or a failure was carried (§4.3);
          // total because §5.6 publishes BEFORE each item, so every
          // progress frame has done < total and the only (N,N) is the
          // success terminal. `<done + 1>` for the same reason: a frame
          // carrying done=0 means item 1 is now running.
          if (envelope.failed_id !== null || envelope.done === envelope.total) {
            inflight.delete("bulk");
          } else {
            inflight.set("bulk", {
              badge: "graduating",
              detail: (envelope.done + 1) + " of " + envelope.total,
            });
          }
          renderInflight();
          break;
        default:
          // Unknown types (and anything future) are ignored client-side
          // (10 §1) — never a throw.
          break;
      }
    };
    return source;
  }

  /**
   * Pane transcript SSE appenders (09 §2.4/§4.1; wired at U6, Y-15 makes
   * them the first turn's ONLY content transport — the start POST returns
   * starting-state markup, never transcript text). Best-effort per frame:
   * a browser tab NOT currently viewing this record's split has no
   * #pane-transcript element, and these silently no-op — the
   * authoritative content always arrives via the next full pane-region
   * swap regardless (the pane_result completion swap below, or any pane
   * POST's own response). `pane_block`'s html is server-rendered with
   * html=False (rendering.py) — the SAME primitive the page-level swap
   * uses, so inserting it here carries no additional trust.
   */
  function paneTranscript() {
    return document.getElementById("pane-transcript");
  }

  /** Y-15/F7: the "Starting the conversation…" line clears at the FIRST
   * streamed frame; the pane_result completion swap is the authoritative
   * cleanup bounding any residue (a mid-drain reload re-renders it
   * server-side, and the swap replaces the whole region). */
  function clearStartingLine() {
    const line = document.getElementById("pane-starting-line");
    if (line) line.remove();
  }

  function appendPaneDelta(text) {
    clearStartingLine();
    const el = paneTranscript();
    if (!el || typeof text !== "string") return;
    let live = el.querySelector(".pane-block-live-delta");
    if (!live) {
      live = document.createElement("div");
      live.className = "pane-block pane-block-live-delta";
      el.appendChild(live);
    }
    live.appendChild(document.createTextNode(text));
  }

  function appendPaneBlock(html) {
    clearStartingLine();
    const el = paneTranscript();
    if (!el || typeof html !== "string") return;
    const live = el.querySelector(".pane-block-live-delta");
    if (live) live.remove(); // the finalized block below supersedes it
    const wrapper = document.createElement("div");
    wrapper.className = "pane-block";
    wrapper.innerHTML = html;
    el.appendChild(wrapper);
  }

  function appendPaneTool(name, target) {
    clearStartingLine();
    const el = paneTranscript();
    if (!el || typeof name !== "string") return;
    const p = document.createElement("p");
    p.className = "pane-tool";
    p.textContent = target ? "tool: " + name + " → " + target : "tool: " + name;
    el.appendChild(p);
  }

  /**
   * Y-15 completion swap (09 §4.2 / 10 §1 SSE row): on pane_result,
   * re-fetch the pane region's OWN panel GET (data-pane-panel-url —
   * delta R3, never scraped from hx-post values) and swap it in. The
   * server-rendered panel is the authoritative completion for clean and
   * error legs alike; the swap is idempotent and side-effect-free, so
   * at-least-once delivery is fine (delta R2). Deferred — never fired —
   * while the region shows the armed interrupt prompt or a focused
   * non-empty send input (delta R1: same hazard class as the
   * pane_proposal [data-armed] belt — never clobber a human
   * mid-decision or a half-typed draft).
   */
  var paneCompletionTimer = null;
  var PANE_COMPLETION_RETRY_MS = 1500;

  function paneSwapBlocked(region) {
    // Page-wide armed check — intentionally WIDER than the R1 pin
    // (which names only the pane region's own armed prompt/input):
    // deferral-only, so the failure direction is a late swap, never a
    // clobbered decision (code-review NIT-3, acknowledged).
    if (findArmedBar()) return true;
    if (region.classList.contains("pane-armed")) return true; // armed interrupt prompt
    var input = region.querySelector('#pane-input-form input[name="text"]');
    return !!(input && document.activeElement === input && input.value.trim() !== "");
  }

  function schedulePaneCompletion() {
    var region = document.querySelector(".pane-region[data-pane-panel-url]");
    if (!region) return; // no pane region on this page — nothing to complete
    if (paneSwapBlocked(region)) {
      if (!paneCompletionTimer) {
        paneCompletionTimer = window.setTimeout(function () {
          paneCompletionTimer = null;
          schedulePaneCompletion();
        }, PANE_COMPLETION_RETRY_MS);
      }
      return;
    }
    var url = region.getAttribute("data-pane-panel-url");
    if (!url || typeof window.htmx === "undefined") return;
    window.htmx.ajax("GET", url, { target: "#pane-region-wrapper", swap: "outerHTML" });
  }

  /**
   * Y-13 (09 §4.5 / 10 §1 SSE row): a pane proposal landed in the
   * server-held slot. Scope-gated like `refresh` — only the record's
   * own Detail and its bucket's Bucket page act — and the handler
   * no-ops while ANY [data-armed] bar exists (the belt; the structural
   * brace is that the incoming bar renders WAITING, so even a missed
   * suppression cannot redirect a pending Enter). Content never rides
   * the envelope: a full reload re-renders the bar server-side from
   * the slot, the same re-render path `refresh` uses.
   */
  function handlePaneProposal(envelope) {
    if (findArmedBar()) return;
    var scopes = currentScopes();
    var recordMatch =
      typeof envelope.record_id === "string" &&
      scopes.indexOf("record:" + envelope.record_id) !== -1;
    // A page WITH a record identity honors only its own record — a
    // sibling record's Detail in the same bucket must NOT react
    // (review F7: the pinned gate is the record's own Detail plus its
    // bucket's Bucket page, nothing wider).
    if (document.querySelector("[data-record-id]")) {
      if (recordMatch) reload();
      return;
    }
    var bucketMatch =
      typeof envelope.bucket === "string" &&
      scopes.indexOf("bucket:" + envelope.bucket) !== -1;
    if (recordMatch || bucketMatch) reload();
  }

  function showBanner(text) {
    const main = document.getElementById("self-learn-ui-content");
    if (!main) return;
    const p = document.createElement("p");
    p.className = "banner banner-notice";
    p.textContent = text;
    main.prepend(p);
  }

  if (document.getElementById("self-learn-ui-keymap")) {
    connectEventSource();
  }
})();
