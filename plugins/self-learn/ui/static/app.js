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
 *     (09 §1: "an inline single-line input in the action bar").
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

  function clickAction(action) {
    const el = document.querySelector('[data-key-action="' + action + '"]');
    if (el) {
      el.click();
      return true;
    }
    return false;
  }

  function toggleHelp() {
    const overlay = document.getElementById("self-learn-ui-help");
    if (!overlay) return;
    overlay.hidden = !overlay.hidden;
  }

  function focusNote() {
    const armed = findArmedBar();
    const scope = armed ? document : document; // note input lives in the unarmed bar
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

  function onKeyDown(event) {
    if (focusIsTextInput()) return;
    if (event.ctrlKey || event.altKey || event.metaKey) return; // no chords, ever

    if (event.key === "?") {
      toggleHelp();
      return;
    }

    const armed = findArmedBar();
    if (armed) {
      event.preventDefault();
      if (event.key === "Enter") {
        clickAction("confirm");
      } else {
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
        clickAction(entry.action);
    }
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

  function reload() {
    window.location.reload();
  }

  function showReconnectStrip(show) {
    const strip = document.getElementById("self-learn-ui-reconnect-strip");
    if (strip) strip.hidden = !show;
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
        default:
          // applying / bulk_progress — ignored here (10 §1: unknown
          // types are ignored client-side).
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
