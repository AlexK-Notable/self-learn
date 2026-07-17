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
 *     key) as "disarm"; otherwise it is "up a level" (same as h).
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

  /** j/k move a `.selected` marker among the visible [data-row] elements
   * within #self-learn-ui-content (Front's bucket table, a Bucket page's
   * record rows). Enter/l opens the selected row's link. */
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
   * EventSource client for GET /events (09 §3 / 10 §1 SSE protocol row).
   * `refresh` re-requests the current partial when in scope; `banner`
   * shows a one-line notice; unknown types are ignored (10 §1).
   * Reconnect: EventSource auto-retries; the reconnect strip shows while
   * the connection is down, and a 10s poll covers the gap (09 §5).
   */
  const POLL_FALLBACK_MS = 10000;

  function currentScope() {
    const article = document.querySelector("[data-record-id]");
    if (article) return "record:" + article.getAttribute("data-record-id");
    const body = document.body;
    if (body && body.dataset && body.dataset.bucket) return "bucket:" + body.dataset.bucket;
    return "front";
  }

  function inScope(scope) {
    if (scope === "front") return true;
    return scope === currentScope();
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
        default:
          // applying / bulk_progress / pane_result — pane_result's
          // authoritative footer arrives via the pane POST response's
          // own swap (pane.py's design note); ignored here (10 §1:
          // unknown types are ignored client-side).
          break;
      }
    };
    return source;
  }

  /**
   * Pane transcript SSE appenders (09 §2.4/§4.1; wired at U6). Best-effort
   * only: a browser tab NOT currently viewing this record's split has no
   * #pane-transcript element, and these silently no-op — the authoritative
   * content always arrives via the next full pane-region swap regardless
   * (pane.py's foreground-drain design: the POST response IS the final
   * state). `pane_block`'s html is server-rendered with html=False
   * (rendering.py) — the SAME primitive the page-level swap uses, so
   * inserting it here carries no additional trust.
   */
  function paneTranscript() {
    return document.getElementById("pane-transcript");
  }

  function appendPaneDelta(text) {
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
    const el = paneTranscript();
    if (!el || typeof name !== "string") return;
    const p = document.createElement("p");
    p.className = "pane-tool";
    p.textContent = target ? "tool: " + name + " → " + target : "tool: " + name;
    el.appendChild(p);
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
