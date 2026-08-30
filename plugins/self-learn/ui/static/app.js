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

  /**
   * U-target §4.7 — the three plain-words refusals. Each names the way
   * OUT, per Y-9: a refusal that does not say what to press instead is
   * the same dead key this unit exists to remove, only quieter.
   */
  const MULTI_TARGET_HINT =
    "More than one row here can do that. Move to the row you mean " +
    "(w or s), then press the key again.";
  const MULTI_ARMED_HINT =
    "More than one action is armed. Click Confirm or Cancel on the one " +
    "you mean, or press Esc to leave.";
  const MULTI_NOTE_HINT =
    "More than one note field here. Move to the row you mean (w or s), " +
    "then press n.";

  /**
   * U-target §4.1 — the ONE resolution primitive every keyboard-driven
   * DOM lookup in this file goes through.
   *
   * The defect it replaces: `document.querySelector(selector)` returns
   * the FIRST match in document order, page-wide, and Front, Bucket and
   * an expanded cluster each render one action bar PER ROW inside a
   * `{% for %}` loop. So a keystroke silently acted on a record the
   * operator was not looking at — measured on the wire: with the
   * selection asserted on holding row 2, `t`/`c`/`g`/`k` all POSTed row
   * 1's arm URL carrying row 1's nonce, console empty.
   *
   * The rule, in order:
   *   1. resolve INSIDE the unique `#self-learn-ui-content
   *      [data-row].selected` row — the same container `rows()` walks,
   *      so the two agree on what a row is;
   *   2. if that row has EXACTLY ZERO matches, fall back page-wide and
   *      act only when there is exactly ONE candidate. The fallback is
   *      deliberately NOT scoped to `#self-learn-ui-content` — `up`
   *      lives in the status strip, outside it, and must stay
   *      reachable. It exists because `ensureRowSelected()` selects the
   *      first `[data-row]`, which on Front owns no action, and because
   *      Detail has no `[data-row]` at all: a selection-only rule would
   *      turn a targeting defect into a dead keyboard (§4.2).
   *   3. otherwise REFUSE — `ambiguous`, and every caller turns that
   *      into zero requests plus a visible hint. Picking "the nearest"
   *      or "the last" would be the same defect with better odds.
   *
   * Two `.selected` rows is `ambiguous`, never "pick one".
   * `moveSelection` clears all before setting one, so this is
   * defensive — but it must not silently degrade to first-match.
   *
   * NOTE the exact reach of that first branch (code gate r1 NIT-1): it
   * short-circuits BEFORE querying anything, so with two rows selected
   * this returns `ambiguous` even for a selector that matches NOTHING
   * anywhere on the page. That is deliberate and spec-sanctioned — the
   * caller must refuse, not act — and it is unreachable through
   * `moveSelection`/`ensureRowSelected`, which never leave two rows
   * marked. It is written down because it has one real consequence:
   * an EXISTENCE test built on this primitive (`status !== "none"`)
   * would report "something is armed" on a page with ZERO armed bars.
   * That is precisely why `findArmedBar()` below stays page-wide rather
   * than being re-expressed in terms of this function.
   */
  function resolveScoped(selector) {
    const sels = document.querySelectorAll(
      "#self-learn-ui-content [data-row].selected"
    );
    if (sels.length > 1) return { status: "ambiguous", el: null };
    if (sels.length === 1) {
      const inRow = sels[0].querySelectorAll(selector);
      if (inRow.length === 1) return { status: "one", el: inRow[0] };
      if (inRow.length > 1) return { status: "ambiguous", el: null };
      // exactly 0 in the selected row -> fall through, page-wide
    }
    const all = document.querySelectorAll(selector);
    if (all.length === 1) return { status: "one", el: all[0] };
    if (all.length === 0) return { status: "none", el: null };
    return { status: "ambiguous", el: null };
  }

  /**
   * U-target §4.1/§4.2 — an action's own COMBINED target set: a live
   * control, or a server-marked gated control (the
   * `[data-noop-hint][data-noop-action]` pair `action_bar.html` already
   * uses for the singleton `o` cycle, and that `bucket.html`'s
   * bulk-collapse button gains at §4.5).
   *
   * The gated half is inside the SCOPED query, not only the fallback,
   * and that is the subtlest rule in this unit. With the bulk row
   * SELECTED, a `data-key-action`-only query would find 0 in scope,
   * fall through page-wide, find the single record row in another
   * group, and GRADUATE a record the operator never selected — a new,
   * quieter version of the same bug. Treating the selected row's gated
   * control as a positive, in-scope answer is what stops that (`B2`).
   *
   * Action names are `[a-z_]+` (every `KeymapEntry.action` in
   * keymap.py), so concatenating them into a selector needs no
   * escaping. If a future action name ever contains anything else this
   * becomes a selector injection — noted, not guarded.
   */
  function targetSelector(action) {
    return (
      '[data-key-action="' + action + '"], ' +
      '[data-noop-hint][data-noop-action="' + action + '"]'
    );
  }

  function isGatedTarget(el) {
    return (
      !!el &&
      !el.hasAttribute("data-key-action") &&
      el.hasAttribute("data-noop-hint")
    );
  }

  /**
   * U-target §4.3 — the armed branch's resolution. `ambiguous` here is
   * "two bars are armed and the selection cannot break the tie": the
   * key refuses instead of routing to whichever bar sits first in the
   * DOM. On a bucket page with an expanded cluster, document order puts
   * the cluster ABOVE the record rows (`bucket.html:48` vs `:61`), so
   * first-match meant `Enter` POSTing a cluster member's confirm
   * carrying `collapse=merge-…` — EXECUTING A MERGE the operator never
   * armed (§2.7 c, reproduced on the wire).
   */
  function resolveArmedBar() {
    return resolveScoped('.action-bar[data-armed="true"]');
  }

  /**
   * DELIBERATELY page-wide, and NOT routed through `resolveScoped`.
   * This answers a DIFFERENT question from dispatch: "is anything armed
   * anywhere on this page?", asked by the Y-16 reload-defer legs and the
   * pane-proposal belt below (leg (c), `paneSwapBlocked`,
   * `handlePaneProposal`). Those legs must hold a reload while ANY bar
   * is armed — scoping them would make a page with TWO armed bars
   * resolve `ambiguous` and therefore NOT defer, letting a broadcast
   * refresh wipe both armed bars. That is strictly worse than today.
   * U-target §2.1 lists those call sites as out of scope and untouched;
   * only the KEY DISPATCH lookup is narrowed (`resolveArmedBar`).
   */
  function findArmedBar() {
    return document.querySelector('.action-bar[data-armed="true"]');
  }

  /**
   * U-target §4.4 — "what request would this element actually issue",
   * computed from what the templates already carry.
   *
   * This replaces N10's record-id comparison as the deferred-fire
   * identity check on Front and Bucket, where `[data-record-id]` does
   * not exist at all (§2.4: it is stamped only on the three Detail
   * templates, so `recordNow !== recordAtDefer` is `null !== null` —
   * always false, always passes, never warns).
   *
   * Stamping `data-record-id` on each row is the obvious move and it is
   * REJECTED, for two reasons. Additively, `currentScopes()` reads that
   * attribute to build the SSE scope list, so a Bucket page would
   * suddenly claim `record:<first row's id>` as one of its scopes.
   * Subtractively — the stronger one — `handlePaneProposal()` treats
   * ANY `[data-record-id]` in the document as the record-only branch
   * and RETURNS before the bucket check, so a Bucket page with stamped
   * rows would stop reloading on bucket-scoped `pane_proposal`
   * envelopes entirely. The signature needs no new attribute anywhere.
   *
   * Measured premise: no template uses htmx's `data-hx-*` prefixed form
   * (`SIG1` is the pin that fails first if one ever does), so reading
   * the plain attributes is complete.
   */
  function targetSignature(el) {
    if (!el) return null;
    const host = el.closest("[hx-post],[hx-get],[hx-put],[hx-delete]");
    const verb = host
      ? host.getAttribute("hx-post") ||
        host.getAttribute("hx-get") ||
        host.getAttribute("hx-put") ||
        host.getAttribute("hx-delete")
      : "";
    const bar = el.closest(".action-bar");
    return [
      el.getAttribute("data-key-action") || "",
      verb || "",
      el.getAttribute("hx-vals") ||
        (host ? host.getAttribute("hx-vals") : "") ||
        "",
      el.getAttribute("hx-include") ||
        (host ? host.getAttribute("hx-include") : "") ||
        "",
      el.getAttribute("href") || "",
      bar ? bar.id : "",
    ].join("|");
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
  /**
   * code gate r7 (MAJOR-1 follow-up, the coordinator's ruling): the
   * keyed wait above (waitingIds) proves every swap outstanding AT
   * DEFER TIME resolved or is known unresolvable -- it says nothing
   * about a swap that started AFTER deferral and happens to replace
   * THIS dispatch's own target (a second, later swap for the same
   * element). fire() re-checks the actual precondition right before
   * acting instead of trusting the keyed wait alone: is the LIVE
   * element wired RIGHT NOW? For a `[data-key-action]` target that
   * carries its OWN `hx-*` verb this is exactly what
   * `elt["htmx-internal-data"].firstInitCompleted` answers HONESTLY --
   * unlike Layer 2's forms (r6's MAJOR-1: htmx marks every `<form>`
   * processed regardless of whether anything was ever wired for it), a
   * verb-carrying element's `firstInitCompleted` reading true DOES
   * mean htmx's click listener is attached (kt() wires the verb via
   * wt() strictly before it sets that flag, in the same synchronous
   * call -- see Layer 2's own comment below for the trace).
   *
   * NOT every `[data-key-action]` target carries a verb, though --
   * `data-key-action="up"` is a plain `<a href>` (`bucket.html`,
   * `detail.html`, etc.), never touched by htmx's own node-discovery
   * walk at all (its selector only sweeps an `<a>` in when it carries
   * `hx-boost`/`data-hx-boost` itself or sits under an ancestor that
   * does -- these plain navigation links do neither), and
   * `toggle_brief` is a bare `<summary>` with no hx-* attribute of any
   * kind. For those, `firstInitCompleted` never becomes true -- not a
   * timing gap, a permanent absence -- so checking it unconditionally
   * would deafen EVERY click on them forever, which live full-suite
   * runs caught immediately (`b`, `Escape` with no pane open). Scoped
   * with `formHasOwnHtmxVerb(live)` below (the SAME check Layer 2 uses
   * for a form's own verb, reused here for the click target itself) --
   * only elements this file expects htmx to wire a click for at all
   * are ever subject to this check; anything else fires exactly as it
   * always has, r1 through r6.
   *
   * Read DIRECTLY (never via htmx's own getInternalData(), whose
   * create-on-read side effect would fabricate the object on an
   * element htmx has never touched) -- so an element htmx genuinely
   * has not processed yet reads as absent, not as a freshly-created
   * empty object that would otherwise mask the very case this exists
   * to catch.
   *
   * Fail-closed here is more dangerous than in Layer 2: Layer 2
   * failing closed drops ONE submit; failing closed on a mechanism
   * that vanished ENTIRELY (a future htmx upgrade renaming or
   * dropping the expando) would silently deafen the keyboard forever,
   * every dispatch -- worse than the race this guards against. So
   * this is split into two questions, not one:
   * htmxInternalDataMechanismAlive() asks whether the marker
   * mechanism itself still exists on THIS page at all, using
   * `document.body` as the canary -- htmx's own bootstrap always
   * processes `document.body` as part of loading (kt() runs on it
   * regardless of what markup exists below), so body carries the
   * expando on any page where htmx has run AT ALL, whether or not any
   * SPECIFIC target has been individually processed yet. If body
   * itself never got it, the mechanism is unavailable everywhere (htmx
   * failed to load, or a future version renamed the field), and
   * reading it on any OTHER element would be trusting a signal already
   * shown to be gone -- so this case falls back to firing on the keyed
   * wait alone, exactly the r1-r6 behavior, rather than vetoing blind.
   * Only when the canary confirms the mechanism is alive AND the
   * target carries its own verb does elementLooksWired()'s per-element
   * read get trusted to veto.
   */
  function htmxInternalDataMechanismAlive() {
    const bodyData = document.body && document.body["htmx-internal-data"];
    return !!(bodyData && typeof bodyData === "object");
  }

  function elementLooksWired(el) {
    const data = el && el["htmx-internal-data"];
    return !!(data && data.firstInitCompleted === true);
  }

  /**
   * U-target §4.1/§4.2 — resolve `action`'s target the ONE way this
   * file resolves anything keyboard-driven.
   *
   * `barId` is the armed branch's scope: while a bar is armed, its
   * Confirm/Cancel are THAT BAR'S, looked up inside it rather than
   * page-wide (§4.3). Re-resolution at fire time goes through this same
   * function with the same `barId`, never a closed-over element — the
   * bar is re-found by id, so a swap that replaced it drops the fire
   * instead of clicking a detached node.
   */
  function resolveDispatch(action, barId) {
    const selector = targetSelector(action);
    if (barId) {
      const bar = document.getElementById(barId);
      if (!bar) return { status: "none", el: null };
      const found = bar.querySelectorAll(selector);
      if (found.length === 1) return { status: "one", el: found[0] };
      if (found.length === 0) return { status: "none", el: null };
      return { status: "ambiguous", el: null };
    }
    return resolveScoped(selector);
  }

  /**
   * U-target §4.2 — the return contract, which `goUp()` branches on:
   * `clickAction` reports HANDLED for `one`-that-fired,
   * `one`-that-hinted AND `ambiguous`; only `none` reports NOT handled.
   * A refusal that reported not-handled would refuse AND THEN navigate
   * away (`goUp()` falls through to `window.history.back()`) — the
   * worst of both. Pinned by `R1`.
   */
  function clickAction(action, barId) {
    const resolved = resolveDispatch(action, barId);
    if (resolved.status === "none") return false;
    if (resolved.status === "ambiguous") {
      // Zero requests. The operator moves the selection and presses
      // again; acting on the first match is the defect.
      showNoopHint(MULTI_TARGET_HINT);
      return true;
    }
    const el = resolved.el;
    if (isGatedTarget(el)) {
      // Server-marked gated control (the singleton `o` cycle; the
      // bulk-collapse graduate after §4.5). Nothing to defer or click —
      // say why, and report HANDLED so the caller does not fall through
      // to a page-wide search of its own.
      showNoopHint(el.getAttribute("data-noop-hint"));
      return true;
    }
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
    //
    // U-target §4.4: N10's record-id leg is KEPT, not replaced -- it is
    // the only leg that catches a whole-page record change for an
    // IDENTITY-LESS target (`up` to the same bucket, `toggle_brief`),
    // whose signature is unchanged across records. The signature leg
    // below is what finally works on Front and Bucket, where
    // `currentRecordId()` is `null` on both sides of N10's comparison.
    const recordAtDefer = currentRecordId();
    const sigAtDefer = targetSignature(el);
    function fire() {
      const recordNow = currentRecordId();
      if (recordNow !== recordAtDefer) {
        console.warn(
          'clickAction("' + action + '"): dropped -- record changed from ' +
            recordAtDefer + " to " + recordNow + " before this deferred click fired"
        );
        return;
      }
      // U-target §4.4 step 1: re-resolve by the SAME RULE, never a
      // closed-over element. Step 2: a `none` or `ambiguous`
      // re-resolution DROPS WITH A WARN. Today's code is a bare
      // `if (!live) return;` -- a dropped keystroke indistinguishable
      // from a key that does nothing (`D3`, `D3b`).
      const reResolved = resolveDispatch(action, barId);
      if (reResolved.status !== "one") {
        console.warn(
          'clickAction("' + action + '"): dropped -- target re-resolved to "' +
            reResolved.status + '" at fire time (the document changed ' +
            "under this deferred dispatch); never fired"
        );
        return;
      }
      const live = reResolved.el;
      // U-target §4.4 step 4: the leg that works on all three surfaces.
      // "What request would this element actually issue" -- if that is
      // not what was intended at defer time, the intent is stale even
      // though something matching the selector is still there. Measured
      // without it: a deferred `k` relocated onto a DIFFERENT holding
      // row and POSTed, with zero console output.
      const sigNow = targetSignature(live);
      if (sigNow !== sigAtDefer) {
        console.warn(
          'clickAction("' + action + '"): dropped -- target signature ' +
            "changed from [" + sigAtDefer + "] to [" + sigNow +
            "] before this deferred click fired"
        );
        return;
      }
      // code gate r7 (MAJOR-1 follow-up): the fire-time wired check --
      // see this function's own docblock above for what it proves and
      // why the canary matters.
      if (
        formHasOwnHtmxVerb(live) &&
        htmxInternalDataMechanismAlive() &&
        !elementLooksWired(live)
      ) {
        console.warn(
          'clickAction("' + action + '"): dropped -- record ' +
            recordAtDefer + "'s target was not wired at fire time (a " +
            "later swap likely replaced it after this dispatch's own " +
            "wait already cleared); never fired"
        );
        return;
      }
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
      // N1 / code gate r7 (MAJOR-1): this call is queued into the
      // SHARED pendingDispatches array, keyed to the specific token
      // ids outstanding right now (`waitingIds`, captured once via
      // outstandingIds()) and released ONLY once every one of THOSE
      // ids is known resolved (resolveDispatchesWaitingOnId) or DROPPED
      // the instant any one of them is known unresolvable
      // (dropDispatchesWaitingOnId) -- never a private listener this
      // call alone owns, and never merely "whichever token's removal
      // happened to bring some shared bag to zero" (see
      // pendingDispatches' own comment for the r7 history of getting
      // that release condition right). Measured without a shared,
      // keyed queue: a key pressed FIRST could fire ~499ms AFTER a key
      // pressed later, because the first one's own request failed (an
      // F14 leg) while it sat waiting on an `afterSettle` that was
      // never coming, and nothing told it to stop waiting -- only ITS
      // OWN fallback timer, half a second later, ever released it
      // (`[reject@4ms, route@503ms]`). A shared queue drained on EVERY
      // resolution path (a real settle OR any F14 failure that owns
      // the pending target) is released the instant we know it's safe,
      // never merely when its own private timer happens to expire.
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
      // if it had, this dispatch would already have been released for
      // real (see resolveDispatchesWaitingOnId). The gate reproduced
      // what firing BLIND here actually does: with a real settle delay
      // of 1500ms (CPU starvation stretches a real one just as far),
      // the r3 dispatch fired at its own 500ms mark onto a `<button
      // type="submit">` htmx had not yet finished wiring -- the form's
      // native, un-intercepted submission ran instead, a plain GET to
      // the current URL with its hidden fields as a query string,
      // navigating the page out from under everything. That is the
      // ORIGINAL bug this whole unit exists to fix, re-entering under
      // CPU starvation. This 500ms bound is a LIVENESS guarantee
      // (never wedge a keystroke forever waiting on a swap that will
      // never resolve) -- it is NOT a license to act on a swap that
      // merely hasn't resolved YET. So: never `.click()` a form that
      // has not settled. DROP the dispatch instead -- the entry is
      // discarded (liveness kept: nothing is left pending, so nothing
      // is stuck), the bar is left exactly as it was (nothing was
      // clicked, so nothing changed -- the NEXT keypress dispatches
      // normally, and fires for real once the swap actually does
      // settle), and exactly one `console.warn` names the record and
      // how long it waited, so a dropped keystroke is diagnosable
      // instead of silently absent.
      const deferredAt = performance.now();
      const entry = {
        fire: fire,
        timer: null,
        waitingIds: outstandingIds(), // code gate r7: fixed at defer time, never added to
        action: action,
        recordAtDefer: recordAtDefer,
      };
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
    //
    // U-target §4.2: TWO corrections here, and the second is a defect
    // this unit found rather than inherited.
    //   1. `document.querySelector` is page-wide, so `n` focused the
    //      FIRST row's note field, not the selected row's — the same
    //      targeting defect as `clickAction`, not previously reported.
    //   2. `input[name="note"]` can match a HIDDEN input.
    //      `action_bar.html`'s commit-drift retry branch renders
    //      `<input type="hidden" name="note">` when a FAILED route's
    //      retry carried a note (`:67`, the un-armed branch — the only
    //      one `focusNote` can reach, since an armed bar routes `n`
    //      through the armed branch's own hint). In that state a Bucket
    //      page puts a hidden `note` input AHEAD of every real one and
    //      `n` "focuses" something invisible — a silently dead key, the
    //      exact shape `NOOP_MESSAGES` exists for. The selector must
    //      name the visible one (`F1b`).
    const resolved = resolveScoped('.action-bar input[type="text"][name="note"]');
    if (resolved.status === "one") {
      resolved.el.focus();
      return;
    }
    if (resolved.status === "ambiguous") {
      showNoopHint(MULTI_NOTE_HINT);
      return;
    }
    // `none` -> silent no-op, today's behaviour.
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

    // U-target §4.3: the armed branch resolves the SAME way dispatch
    // does, and acts WITHIN the bar it resolved.
    const armedResolved = resolveArmedBar();
    if (armedResolved.status === "ambiguous") {
      // Two bars armed and the selection cannot break the tie. Refuse —
      // today document order decides, which on a bucket page with an
      // expanded cluster means `Enter` executing a merge (§2.7 c).
      //
      // Escape is EXEMPT and falls through to the ordinary `up` action.
      // Without this the keyboard is TRAPPED until a mouse click: every
      // key refused, no way out. Escape cannot disambiguate WHICH bar
      // to cancel, but leaving the page abandons both harmlessly —
      // arming renders a partial and issues no write, so nothing is
      // lost. `MULTI_ARMED_HINT` says so in words (`A3`).
      if (event.key !== "Escape") {
        event.preventDefault();
        showNoopHint(MULTI_ARMED_HINT);
        return;
      }
    } else if (armedResolved.status === "one") {
      const armed = armedResolved.el;
      const armedBarId = armed.id;
      // KNOWN PRE-EXISTING STATE, recorded so a reader does not have to
      // wonder whether this unit caused it (code gate r1 NIT-2). A bar
      // whose `data-armed="true"` comes from `commit_drift.armed`
      // (action_bar.html:10's second disjunct) carries
      // `commit_drift_confirm`/`commit_drift_disarm`, NOT
      // `confirm`/`disarm` — so both lookups below find nothing in it
      // and the branch is keyboard-INERT there. That was already true
      // before U-target, and scoping makes it strictly SAFER: the old
      // page-wide lookup could resolve `confirm` in a DIFFERENT bar and
      // fire it; a within-bar lookup cannot reach outside the bar the
      // operator is actually in. Binding those two actions is not this
      // unit's business.
      event.preventDefault();
      if (event.key === "Enter") {
        clickAction("confirm", armedBarId);
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
        clickAction("disarm", armedBarId);
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
    // U-target §4.2: leg 1 (present-but-noop) is now FOLDED INTO
    // `clickAction` — the `[data-noop-hint][data-noop-action]` pair is
    // part of `targetSelector`, so it is resolved by the SAME scoped
    // rule as a live control rather than by a second, page-wide
    // `document.querySelector` that would answer a different question
    // (and, with the bulk row selected, the wrong one — see
    // `targetSelector`'s own comment). Only leg 2 (absent-target)
    // remains here.
    if (clickAction(action)) return;
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
   * `htmx:afterSettle` listener of its own.
   *
   * MAJOR-1 (code gate r7): through r6 this was drained "the instant
   * the bag empties" -- and that phrase is exactly the bug, the same
   * shape a SEVENTH time. removeAbandonedSwapSilently's own r6 fix
   * (Minor 1) never drains pendingDispatches itself, correctly -- but
   * it DOES silently empty abandonedSwaps, and nothing stopped some
   * UNRELATED later request's genuine resolution from finding BOTH
   * bags empty at that point and draining a dispatch that was never
   * actually waiting on THAT request -- it was waiting on the key
   * that had just aged out unresolved. Reproduced 9/9 across three
   * sessions: a dispatch queued behind an abandoned key fires the
   * instant an unrelated settle arrives after the ceiling passes,
   * having learned nothing about the key it actually needed. That is
   * r5's Blocker B-2 verbatim, one layer further out, behind the r6
   * ceiling instead of a raw eviction -- releasing a wait because some
   * GLOBAL collection became empty, rather than because the SPECIFIC
   * thing it was waiting for resolved or is now known unresolvable.
   *
   * Fixed by keying the release the same way pendingSwaps itself is
   * keyed. Every token gets a unique numeric `id` at creation
   * (`nextSwapId` below), carried over when a token moves from
   * pendingSwaps into abandonedSwaps (removePendingSwapSilently) so a
   * LATE real resolution can still find it there. Each queued
   * dispatch snapshots the ids of every token outstanding AT THE
   * MOMENT it defers (`outstandingIds()`, clickAction's own comment)
   * into its own `waitingIds` -- a fixed list, never added to later,
   * so a token that starts AFTER this dispatch deferred was never
   * anything this dispatch was waiting on and cannot affect it. A
   * token's REAL resolution (removePendingSwapForKey) removes its id
   * from every dispatch's waitingIds that still has it
   * (resolveDispatchesWaitingOnId); a dispatch whose set empties this
   * way fires -- released because everything IT was gated on
   * resolved, never because some other bag happened to. A token that
   * instead AGES OUT unresolved (removeAbandonedSwapSilently, the r6
   * ceiling) can, by construction, never resolve -- so any dispatch
   * still holding its id is DROPPED right then
   * (dropDispatchesWaitingOnId), fail-closed, rather than left to
   * possibly be released later by something that was never actually
   * evidence of anything for it. There is no path from "an unrelated
   * key resolved" to "this dispatch fires" any more -- not merely no
   * path this bookkeeping currently happens to take.
   *
   * A private per-call listener has no way to learn that a DIFFERENT
   * leg (an F14 failure owning a DIFFERENT request, say) already
   * resolved the wait; measured live under the r1 design: a key
   * pressed FIRST could fire ~499ms AFTER a key pressed later this way
   * (`[reject@4ms, route@503ms]`) -- the first one's own request
   * failed, but with no shared drain, only ITS OWN fallback timer ever
   * released it. Each dispatch ALSO carries its own 500ms fallback
   * (N12, clickAction's own comment) as a second, independent bound
   * alongside the keyed wait -- a continuous stream of overlapping
   * swaps can keep a dispatch's waitingIds non-empty far longer than
   * any one token's own 500ms, and this bound still closes that
   * liveness gap regardless of anything above. */
  let nextSwapId = 1;
  const pendingSwaps = [];
  const pendingDispatches = [];

  // NIT-2 (code gate r7): a test seam for the ceiling below, matching
  // how htmx exposes its OWN `htmx.config` for tests to override live
  // rather than burning 10+ real seconds per ceiling-timing test.
  // Read fresh at every scheduling site (abandonedSwapCeilingMs()
  // below), never cached, so a test can set this any time after page
  // load and before the specific scenario it is testing, exactly like
  // `htmx.config.defaultSettleDelay`.
  window.SELF_LEARN_UI_CONFIG = window.SELF_LEARN_UI_CONFIG || {};
  const DEFAULT_ABANDONED_SWAP_CEILING_MS = 10000; // 20x the 500ms
  // bound, well past the gate's own 1500ms CPU-starvation stress
  // scenario (6.7x), and far past any duration a human would
  // plausibly still be waiting on ONE keypress before assuming
  // something else is wrong.
  function abandonedSwapCeilingMs() {
    return typeof window.SELF_LEARN_UI_CONFIG.ABANDONED_SWAP_CEILING_MS ===
      "number"
      ? window.SELF_LEARN_UI_CONFIG.ABANDONED_SWAP_CEILING_MS
      : DEFAULT_ABANDONED_SWAP_CEILING_MS;
  }

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
  // still gates unresolvedSwapsExist() (clickAction's own defer
  // decision, B-1) identically to pendingSwaps. A key leaves this set
  // either via its OWN real resolution eventually arriving (a late
  // htmx:afterSettle or F14 failure carrying the SAME key, via
  // removePendingSwapForKey below) or (code gate r6, Minor 1) via its
  // own staleness ceiling (below). Layer 2 below (the submit guard) is
  // what makes even a hole in THIS bookkeeping harmless, which is what
  // lets this set stay conservative about WHEN to defer rather than
  // clever about it.
  //
  // Minor 1 (code gate r6): "stay conservative forever" turned out to
  // have a real cost -- measured live: a SINGLE key that never gets a
  // real resolution deafened every later keypress PERMANENTLY
  // (`[False, False, False]` across three separate presses),
  // contradicting r4's own "the NEXT keypress dispatches normally"
  // guarantee. So each entry carries its own staleness ceiling
  // (abandonedSwapCeilingMs(), above), past which it ages out.
  //
  // MAJOR-1 (code gate r7) corrected what "ages out" is allowed to
  // mean. r6 shipped it as pure bookkeeping that "never drains
  // pendingDispatches... a dispatch already queued and waiting on it
  // keeps waiting out its OWN independent fallback and drops there,
  // exactly as if this function did not exist." That sentence is now
  // FALSE, and was the seventh hole -- see the MAJOR-1 paragraph above
  // pendingDispatches' own declaration for the measured proof and the
  // fix. Ageing out still never RESOLVES anything (a timeout is still
  // never a reason to declare a dispatch safe to fire) -- but it now
  // actively finds every dispatch that was waiting on THIS id
  // specifically and drops each one, fail-closed, right then
  // (removeAbandonedSwapSilently below) -- not later, not via whatever
  // bag some UNRELATED resolution happens to empty. A dispatch waiting
  // on a DIFFERENT key that is still genuinely outstanding is
  // untouched by this -- only the ids actually present in its own
  // waitingIds snapshot can ever affect it.
  const abandonedSwaps = []; // array of { key, id, timer }

  // B-1 (code gate r5): the one question clickAction() asks before
  // deciding whether to defer at all -- "is there anything whose
  // outcome we do not yet know for certain?" -- answered by BOTH sets
  // together, never pendingSwaps alone. This governs ONLY the defer
  // decision; the RELEASE decision (code gate r7) is keyed per-id, see
  // resolveDispatchesWaitingOnId/dropDispatchesWaitingOnId below --
  // it never re-reads this boolean.
  function unresolvedSwapsExist() {
    return pendingSwaps.length > 0 || abandonedSwaps.length > 0;
  }

  // code gate r7 (MAJOR-1): every token id currently outstanding, in
  // EITHER set, at the moment this is called -- a queued dispatch
  // snapshots this ONCE, at defer time, into its own waitingIds;
  // nothing added to either set AFTER that moment is ever added to an
  // already-queued dispatch's snapshot.
  function outstandingIds() {
    return pendingSwaps
      .map(function (t) {
        return t.id;
      })
      .concat(
        abandonedSwaps.map(function (t) {
          return t.id;
        })
      );
  }

  // code gate r7 (MAJOR-1): a token's id RESOLVED for real (a genuine
  // htmx:afterSettle or F14 failure owning it, via
  // removePendingSwapForKey below). Removes this id from every queued
  // dispatch's waitingIds that still has it; a dispatch whose set
  // empties this way is released -- fired because everything IT was
  // gated on is now known resolved, never because some other bag
  // emptied.
  function resolveDispatchesWaitingOnId(id) {
    pendingDispatches.slice().forEach(function (entry) {
      const wIdx = entry.waitingIds.indexOf(id);
      if (wIdx === -1) return;
      entry.waitingIds.splice(wIdx, 1);
      if (entry.waitingIds.length === 0) {
        const pIdx = pendingDispatches.indexOf(entry);
        if (pIdx !== -1) pendingDispatches.splice(pIdx, 1);
        clearTimeout(entry.timer); // N12: cancel the dispatch's own fallback, it is being released for real
        entry.fire();
      }
    });
  }

  // code gate r7 (MAJOR-1): a token's id AGED OUT unresolved
  // (removeAbandonedSwapSilently below) -- it can never resolve for
  // real now. Any dispatch still holding this id in its waitingIds is
  // DROPPED here, fail-closed -- not fired, and not left pending on
  // the theory that something else might later look like permission.
  function dropDispatchesWaitingOnId(id) {
    pendingDispatches.slice().forEach(function (entry) {
      if (entry.waitingIds.indexOf(id) === -1) return;
      const pIdx = pendingDispatches.indexOf(entry);
      if (pIdx !== -1) pendingDispatches.splice(pIdx, 1);
      clearTimeout(entry.timer);
      console.warn(
        'clickAction("' + entry.action + '"): dropped -- record ' +
          entry.recordAtDefer + "'s swap it was waiting on aged out " +
          "after " + abandonedSwapCeilingMs() + "ms unresolved (never " +
          "fired; fail-closed, not released by anything else resolving)"
      );
    });
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
  // ONLY -- it must never itself resolve or release a queued dispatch.
  // Only removePendingSwapForKey() below (driven by a REAL
  // htmx:afterSettle or an F14 failure that owns this key) may ever
  // call resolveDispatchesWaitingOnId() -- a timeout is a reason to
  // stop WAITING on this one token, never a reason to declare victory.
  function addPendingSwap(key) {
    const token = { key: key, id: nextSwapId++, timer: null };
    token.timer = setTimeout(function () {
      removePendingSwapSilently(token);
    }, 500);
    pendingSwaps.push(token);
  }

  // Removes at most ONE token owned by `key` (FIFO) and, if a token
  // was actually found, resolves every dispatch waiting on ITS id.
  // Used by afterSettle (which always owns a token for its own
  // request, barring a defect elsewhere) and by an F14 failure leg
  // (which may legitimately own NONE -- see M1/M2 above: a request
  // whose OWN key never swapped has no token to remove, regardless of
  // what target it shares with some other request). This is the ONLY
  // path that may resolve a queued dispatch for real -- see N17's note
  // on addPendingSwap above for why.
  //
  // code gate r5 (B-1/B-2), corrected r7 (MAJOR-1): a matching key can
  // be sitting in EITHER set -- still in pendingSwaps (the common
  // case) or already moved to abandonedSwaps (a LATE resolution,
  // arriving after that eviction but before its own ceiling). Either
  // way this is the one place a key's REAL, definitive outcome becomes
  // known, so either way it is removed from wherever it currently sits
  // and its id is handed to resolveDispatchesWaitingOnId(), which
  // releases only the dispatches that were actually waiting on THIS
  // id -- never a global "both sets empty" check, which is what let an
  // unrelated resolution release a dispatch waiting on a DIFFERENT,
  // still-unresolved key (B-2, and again as MAJOR-1's r7 ceiling
  // variant).
  function removePendingSwapForKey(key) {
    const idx = pendingSwaps.findIndex(function (t) {
      return t.key === key;
    });
    let resolvedId = null;
    if (idx !== -1) {
      resolvedId = pendingSwaps[idx].id;
      clearTimeout(pendingSwaps[idx].timer);
      pendingSwaps.splice(idx, 1);
    } else {
      const aIdx = abandonedSwaps.findIndex(function (t) {
        return t.key === key;
      });
      if (aIdx !== -1) {
        resolvedId = abandonedSwaps[aIdx].id;
        clearTimeout(abandonedSwaps[aIdx].timer);
        abandonedSwaps.splice(aIdx, 1);
      }
    }
    if (resolvedId !== null) resolveDispatchesWaitingOnId(resolvedId);
  }

  // A token's own orphan/timeout removal (N17): bookkeeping only,
  // deliberately never resolves a dispatch -- see addPendingSwap's own
  // comment. The token does not simply vanish -- its `id` (and key)
  // move to abandonedSwaps (code gate r5), which keeps gating exactly
  // like pendingSwaps did until this SAME id's real resolution
  // eventually arrives (removePendingSwapForKey above, matched by key
  // -- the id travels with it), OR (code gate r6/r7) until its own
  // staleness ceiling ages it out (removeAbandonedSwapSilently below).
  // Carrying `id` across this move (not just `key`) is what lets a
  // LATE real resolution still find and release whatever was waiting
  // on this exact token, and what lets the ceiling drop exactly the
  // right dispatches and no others.
  function removePendingSwapSilently(token) {
    const idx = pendingSwaps.indexOf(token);
    if (idx === -1) return; // already removed by a real settle/failure
    clearTimeout(token.timer);
    pendingSwaps.splice(idx, 1);
    const entry = { key: token.key, id: token.id, timer: null };
    entry.timer = setTimeout(function () {
      removeAbandonedSwapSilently(entry);
    }, abandonedSwapCeilingMs());
    abandonedSwaps.push(entry);
  }

  // Minor 1 (code gate r6): an abandoned entry's own staleness
  // ceiling -- this key has outlived any plausible swap and is no
  // longer evidence of anything either way.
  //
  // MAJOR-1 (code gate r7) corrected what happens next. The r6 version
  // stopped here, bookkeeping only, on the theory that a dispatch
  // already waiting on this id would harmlessly keep waiting out its
  // own independent 500ms fallback -- false: the r6 ceiling fires at
  // 10s, long after any dispatch's own 500ms fallback would already
  // have fired FIRST if that fallback were really the only bound in
  // play. A dispatch waiting on an id that ages out is not actually
  // bounded by its own fallback by the time the ceiling fires -- it is
  // sitting there waiting on THIS id specifically, and nothing was
  // telling it that id could never resolve. So this now actively finds
  // every dispatch still holding this id and drops each one,
  // fail-closed, right here (dropDispatchesWaitingOnId) -- the timeout
  // still never RESOLVES anything (it does not fire a click, does not
  // treat absence-of-evidence as evidence), it now correctly ENFORCES
  // its own consequence instead of leaving it to a mechanism (the
  // dispatch's own fallback, or worse, some unrelated bag emptying)
  // that r7 measured does not reliably do the job.
  function removeAbandonedSwapSilently(entry) {
    const idx = abandonedSwaps.indexOf(entry);
    if (idx === -1) return; // already removed by a real, late resolution
    clearTimeout(entry.timer);
    abandonedSwaps.splice(idx, 1);
    dropDispatchesWaitingOnId(entry.id);
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

  // Layer 2 (code gate r5, the durable guard; redesigned code gate r6
  // MAJOR-1). Ruling: every round of bugs this unit has found (r1
  // through r5) caused harm through exactly ONE mechanism -- a native,
  // un-intercepted form submission navigating the page, because htmx
  // had not yet attached its own interception to the form being
  // clicked (the swap/settle gap this whole unit exists to close,
  // entered through one new door each round). That mechanism is
  // narrower than every way the pendingSwaps / pendingDispatches /
  // abandonedSwaps bookkeeping above can be wrong -- and there is no
  // proof B-1/B-2 above are the LAST way. This guard does not depend
  // on any of that bookkeeping at all: a capture-phase `submit`
  // listener on `document` runs before the target form's own
  // listeners (htmx's included), and can veto the native submission
  // directly whenever htmx will not (yet, or ever) handle it --
  // converting a click that lands in the race into NOTHING HAPPENING
  // (a dropped keystroke) instead of a destroyed page.
  //
// MAJOR-1 (code gate r6): the r5 version of this guard asked the
  // wrong question. It read `elt["htmx-internal-data"].
  // firstInitCompleted` -- which tells you htmx has PROCESSED a node,
  // never whether htmx will actually INTERCEPT that node's submit.
  // Those differ, and htmx 2.0.9 makes them differ badly: its own
  // node-discovery selector (`findElementsToProcess` in
  // htmx-2.0.9.min.js) literally includes ", form,", so EVERY `<form>`
  // gets processed and marked `firstInitCompleted = true` -- including
  // the three bare `<form id="form-{{ dom_id }}">` note-input wrapper
  // forms (`action_bar.html:122`, `:142`, `:197`) that carry NO
  // `hx-*` verb of their own at all. Those forms exist purely as
  // `hx-include` scoping containers -- every actual submission from
  // them happens via a SEPARATE sibling `<button hx-post=... hx-
  // include="#form-{{ dom_id }}">` elsewhere, never the form itself --
  // so htmx never attaches anything that would intercept a submit ON
  // THEM, yet the r5 check read `wired === true` for them FOREVER
  // (processed at page load, same as everything else), permitting
  // their native submission unconditionally. Each has exactly one text
  // field and zero submit buttons, so pressing Enter in the note field
  // triggers the browser's OWN implicit-submission rule -- measured
  // live: `/record/lrn-b71e0001` -> `?dest=&note=...`, a real
  // navigation, no guard warning, `defaultPrevented` false at every
  // phase. The exact original failure signature this whole unit exists
  // to close, reproduced on the very build whose own r5 prose claimed
  // "this layer closes the exit."
  //
  // Fixed by asking the real question directly, computed from the DOM
  // this file already controls rather than inferred from a private
  // htmx marker: will htmx EVER intercept THIS form's submit at all?
  // htmx only ever wires a submit-trigger listener for a form that (a)
  // carries an `hx-get`/`hx-post`/`hx-put`/`hx-delete`/`hx-patch` (or
  // `data-hx-*` equivalent) attribute directly, matching exactly the
  // five-verb list htmx's own selector construction uses, or (b) is
  // boosted -- `hx-boost="true"` (or `data-hx-boost`) on the form
  // itself or an ancestor, htmx's OWN `getClosestAttributeValue`
  // inheriting exactly that way. A form with NEITHER is, structurally,
  // never going to be intercepted -- no timing question to ask at all
  // -- so its native submission is blocked UNCONDITIONALLY, not merely
  // until some marker flips. A form with EITHER might simply not be
  // WIRED YET (the original r5 swap/settle race this layer was built
  // for), and for that narrower, correctly-scoped case
  // `firstInitCompleted` remains the right signal: htmx's own `kt()`
  // wires the verb (via `wt()`) or the boost (via `at()`) EARLIER in
  // the SAME synchronous call that sets `firstInitCompleted = true` as
  // its last statement, so by the time that flag reads true, the
  // interception it actually promises for a VERB/BOOST-carrying form
  // has already happened. Reading `elt["htmx-internal-data"]` directly
  // (never htmx's own `getInternalData()`, whose create-on-read side
  // effect would fabricate the object if absent) is still a
  // private-implementation dependency -- if it ever reads as
  // `undefined` (a future htmx upgrade renaming or dropping the
  // field), the check fails CLOSED exactly as before: "unknown" is
  // treated the same as "not yet wired."
  //
  // Determining form intent (code gate r6, ruling item 2): the three
  // note forms above are not missing their `hx-post` by accident --
  // every OTHER form in this app that IS meant to be submitted (the
  // armed/confirm/disarm/commit-drift bars) carries `hx-post` directly
  // on the `<form>`, and these three deliberately do not, because their
  // actual submission always happens through a sibling button's own
  // `hx-include`. Enter silently navigating the page was the bug, not
  // the missing wiring -- so the fix here is to block their implicit
  // submission permanently, not to give them an `hx-post` they were
  // never meant to have.
  //
  // Scope note (code gate r6, softened r7 Minor 3): the Worker/Miner
  // "Force run" buttons (`templates/index.html:117-120`, `:183-190`)
  // carry `hx-post` on the BUTTON rather than the FORM, with an
  // explicit `formmethod`/`formaction` native fallback intended for a
  // client where htmx never loaded at all -- under this check their
  // FORM has no verb/boost of its own either, so it is now ALWAYS
  // blocked, same as the three note forms. Measured with htmx present
  // (the only case actually measured): one POST per click, zero submit
  // events, zero navigations, no double-submit -- SAFER than r5's
  // purely theoretical race window given that assumption. But "safer"
  // is conditional on that assumption, not unconditional: both
  // `<script>` tags (`base.html:41-42`) are same-origin `defer` tags
  // loaded in order, so htmx failing to load while `app.js` still runs
  // is a remote failure mode, not an impossible one -- and in exactly
  // that case, this guard now makes the no-JS fallback these buttons
  // were written for permanently DEAD (blocked here, with no htmx ever
  // coming to intercept it either) where before this whole unit
  // existed it degraded to a working native POST. Scoped claim: safer
  // GIVEN htmx loaded, which is what was actually measured -- not
  // safer in every case these buttons were originally written to
  // survive.
  //
  // MINOR-1 (code gate r7): a 19-row interception matrix (every
  // combination of own-verb, boost, inheritance, and the three cases
  // below) found zero false-BLOCKs, and three false-ALLOWs -- cases
  // where htmxWillInterceptSubmit() below says "will intercept" but
  // htmx 2.0.9 would not actually wire anything, so a submit would go
  // native unblocked. All three are unreachable in this app's shipped
  // markup today (`grep -rn 'hx-trigger=\"[^\"]*\"' 'hx-disinherit'
  // 'method=\"dialog\"' templates/` finds none of the three
  // combinations below anywhere a form also carries a verb or sits
  // under a boosted ancestor), which is why the gate rated this Minor
  // rather than Major -- but documenting a known gap beats leaving it
  // silent, per this unit's own history of "latent" turning real:
  //
  //   1. `hx-trigger` overriding a verb-carrying form's trigger AWAY
  //      from `submit` (e.g. `hx-trigger="click"`). htmx reads the
  //      verb and wires SOME listener, but not on the `submit` event
  //      -- a real submit still goes native. Closed below via
  //      `formEffectiveTriggerIsSubmit()`.
  //   2. `hx-disinherit="hx-boost"` (or `"*"`) on an ancestor BETWEEN
  //      the form and a still-higher `hx-boost="true"` ancestor. htmx's
  //      own inheritance walk (`ne()`/`o()` in htmx-2.0.9.min.js) stops
  //      dead at the FIRST ancestor that disinherits `hx-boost`, before
  //      ever reading a higher one's value -- checked on EVERY ancestor
  //      visited, not just the one carrying the boost. Closed below by
  //      `formHasHtmxBoost()`'s walk checking disinherit at each step.
  //   3. `method="dialog"`. htmx's own boost-eligibility check (`at()`)
  //      explicitly excludes it (`tagName==="FORM" &&
  //      method!=="dialog"`) -- boost never wires it either way. This
  //      one is not a hole to BLOCK closed: native `method="dialog"`
  //      submission does not navigate at all, it closes the nearest
  //      ancestor `<dialog>` and sets its `returnValue`, with no
  //      request ever sent -- there is nothing here for this guard to
  //      prevent. Closed below as an explicit, documented ALLOW that
  //      matches htmx's own exclusion, checked first.
  const HX_VERB_NAMES = ["get", "post", "put", "delete", "patch"];

  function formHasOwnHtmxVerb(form) {
    return HX_VERB_NAMES.some(function (verb) {
      return (
        form.hasAttribute("hx-" + verb) || form.hasAttribute("data-hx-" + verb)
      );
    });
  }

  function formHasHtmxBoost(form) {
    // htmx's own hx-boost inherits from the closest ancestor (or the
    // element itself) that sets it -- walking up here mirrors that.
    //
    // MINOR-1 sub-fix 2 (code gate r7): an element's OWN hx-boost is
    // never subject to ITS OWN hx-disinherit (checked only for
    // `el !== form`, matching htmx's `o(e,t,n)`: the disinherit check
    // only runs when `e!==t`, i.e. only while examining an ancestor of
    // the original starting element, never the starting element
    // itself). For every STRICT ancestor visited, if it declares
    // `hx-disinherit` (or `data-hx-disinherit`) covering `"hx-boost"`
    // or `"*"`, the walk stops here -- that ancestor's OWN boost value
    // (if any) and everything above it are both unreachable from the
    // form, exactly as htmx's own `o()` returns its "unset" sentinel
    // before ever reading `r = a(t,"hx-boost")` in that branch.
    for (let el = form; el; el = el.parentElement) {
      if (el !== form) {
        const disinherit =
          (el.getAttribute && el.getAttribute("hx-disinherit")) ||
          (el.getAttribute && el.getAttribute("data-hx-disinherit"));
        if (
          disinherit &&
          (disinherit === "*" || disinherit.split(" ").indexOf("hx-boost") !== -1)
        ) {
          return false;
        }
      }
      const v =
        (el.getAttribute && el.getAttribute("hx-boost")) ||
        (el.getAttribute && el.getAttribute("data-hx-boost"));
      if (v != null) return v === "true";
    }
    return false;
  }

  // MINOR-1 sub-fix 1 (code gate r7): htmx resolves a form's actual
  // trigger via `st(e)` in htmx-2.0.9.min.js, which reads ONLY the
  // element's own `hx-trigger`/`data-hx-trigger` (never inherited --
  // `st()` uses the plain own-attribute getter, not the ancestor-
  // walking one) and falls back to `submit` for a `<form>` when that
  // attribute is absent OR present-but-empty (`if(t){...} if(n.length
  // >0) return n; else if (h(e,"form")) return [{trigger:"submit"}]`
  // -- an empty string is falsy, so it takes the SAME default path as
  // no attribute at all). Crucially, htmx passes this SAME resolved
  // trigger spec to the BOOST path too (`kt()`: `const e=st(t); const
  // r=wt(t,n,e); if(!r){ if (boosted) at(t,n,e) ... }`) -- so this
  // check applies identically whether interception would come from an
  // own verb or from boost.
  //
  // Deliberately NOT a full trigger-spec parser (htmx's own handles
  // modifiers like `changed`, `once`, `delay:500ms`, `from:`,
  // `consume`, polling intervals, and multiple comma-separated specs)
  // -- this answers only what this guard needs: is `submit` one of the
  // trigger NAMES this form was given. Each comma-separated spec's
  // trigger name is its first whitespace-delimited token.
  function formEffectiveTriggerIsSubmit(form) {
    const raw = form.getAttribute("hx-trigger") || form.getAttribute("data-hx-trigger");
    if (!raw) return true; // absent or empty -- htmx's own default for a form is submit
    return raw.split(",").some(function (spec) {
      const name = spec.trim().split(/\s+/)[0];
      return name === "submit";
    });
  }

  // The real question this guard exists to answer: will htmx EVER
  // intercept this form's submit? Not "has htmx walked past it."
  function htmxWillInterceptSubmit(form) {
    return (
      (formHasOwnHtmxVerb(form) || formHasHtmxBoost(form)) &&
      formEffectiveTriggerIsSubmit(form)
    );
  }

  document.addEventListener(
    "submit",
    function (evt) {
      const form = evt.target;
      // NIT-1 (code gate r7): every OTHER branch below fails CLOSED on
      // an unknown -- "unknown" is treated the same as "not yet
      // wired," never as "must be fine." This early return used to do
      // the opposite: an event whose target this guard cannot even
      // examine (not a form-like Element -- e.g. a synthetic `submit`
      // dispatched directly at `document`, which native form
      // submission never produces) fell through UNBLOCKED. Measured: a
      // bubbling `submit` dispatched at `document` produced no warning
      // at all, against a `<form>` positive control that correctly
      // warns. There is nothing here this guard can verify will be
      // intercepted, so treat it exactly like the unverified case it
      // already is everywhere else in this function.
      if (!form || typeof form.hasAttribute !== "function") {
        evt.preventDefault();
        console.warn(
          "blocked a submit event this guard could not examine -- its " +
            "target was not a recognizable form element, so whether " +
            "htmx will intercept it is unknown and treated as unwired"
        );
        return;
      }
      // MINOR-1 sub-fix 3 (code gate r7): htmx's own boost-eligibility
      // check excludes `method="dialog"` forms entirely (see this
      // block's own comment above) -- native dialog-closing submission
      // does not navigate and sends no request, so there is nothing
      // for this guard to prevent here. Checked first and explicitly,
      // rather than relying on formHasHtmxBoost()/htmxWillInterceptSubmit()
      // to happen to agree with htmx's own exclusion.
      const method = form.getAttribute("method");
      if (method && method.toLowerCase() === "dialog") return;
      if (!htmxWillInterceptSubmit(form)) {
        // MINOR-2 (code gate r8): this branch covers TWO distinct
        // reasons, and the warning used to collapse them into one
        // string that was only accurate for the first -- "this form
        // carries no htmx verb or boost" is false for a form like
        // `<form hx-post hx-trigger="click">`, which the gate measured
        // reaching this exact branch: it DOES carry a verb, it is
        // blocked because hx-trigger routes that verb to click, never
        // submit. Naming the real reason matters because this string
        // is what a developer sees in the console and reasons from.
        evt.preventDefault();
        const hasVerbOrBoost = formHasOwnHtmxVerb(form) || formHasHtmxBoost(form);
        if (!hasVerbOrBoost) {
          // No hx-* verb and no hx-boost (own or inherited) -- htmx
          // will NEVER wire a submit interception for it, so this is
          // not a timing question and there is nothing to wait for.
          // "No request was sent" is accurate here: with no verb and
          // no boost, htmx wires, at most, a no-op trigger handler for
          // it (see the block comment above) -- nothing that could
          // ever issue a request.
          console.warn(
            "blocked a native form submission -- this form carries no " +
              "htmx verb or boost, so htmx will never intercept it " +
              "(no request was sent)"
          );
        } else {
          // Has a verb or boost, but its own hx-trigger names
          // something other than submit -- htmx wires a listener for
          // THAT trigger, never for the submit event, so a native
          // submit still reaches nothing of htmx's. Also accurate to
          // say "no request was sent": nothing submit-driven was ever
          // going to be sent by htmx from a form wired this way.
          console.warn(
            "blocked a native form submission -- this form's hx-trigger " +
              "routes its htmx verb away from submit, so htmx will " +
              "never intercept this submit event (no request was sent)"
          );
        }
        // MINOR-2 (code gate r7): a blocked Enter used to be entirely
        // console-only -- the app's own rationale for showNoopHint()
        // elsewhere (Y-9) is exactly this case: silence "reads as a
        // broken shortcut" once it is reachable deliberately rather
        // than accidentally (the three note forms, always). Give it
        // the same visible surface a no-op key already gets.
        showNoopHint("Enter doesn't submit here -- use the buttons below.");
        return;
      }
      const data = form["htmx-internal-data"];
      const wired = !!(data && data.firstInitCompleted === true);
      if (!wired) {
        evt.preventDefault();
        console.warn(
          "blocked this form's native submission fallback -- htmx did " +
            "not yet appear wired for it (the swap/settle gap); if " +
            "htmx's own listener is already attached despite that, its " +
            "request still goes through regardless of this block, " +
            "since preventDefault() here only stops OTHER listeners' " +
            "default action, never htmx's own already-attached handling"
        );
        // MINOR-2 (code gate r7): same visible-feedback gap as the
        // unconditional block above -- a transient block here still
        // looks, to the user, like nothing happened.
        showNoopHint("Still loading -- try that again in a moment.");
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
