/*
 * self-learn-ui — app.js (10 §1 Dependencies row: "authored, ~40-line
 * keydown handler + EventSource client").
 *
 * STRUCTURE ONLY at U1 (10 §3 task U1 is scaffold-only — no routes, no
 * ledger model, no engine). The keymap footer partial, help overlay, and
 * this file's keydown switch all render from the ONE source of truth:
 * self_learn_ui.keymap.KEYMAP, JSON-encoded via keymap_json() and
 * injected into the page (a <script type="application/json"> blob or a
 * data attribute — wiring decided at U3). Real dispatch (arm/confirm/
 * disarm POSTs, SSE-driven partial swaps) lands at U3.
 *
 * Keymap mechanics (09 §1, restated here as the contract this file must
 * honor once wired):
 *   - Keys are inert while focus is in a text input.
 *   - No Ctrl/Alt chords, ever — the browser owns them.
 *   - A resolution key ARMS the action bar; Enter EXECUTES; any other
 *     key DISARMS. Never a modal confirm.
 *   - Esc is context-sensitive: pane focused -> interrupt first;
 *     otherwise -> "up a level" (same as h).
 */

(function () {
  "use strict";

  /**
   * Read the single-source keymap blob the server rendered into the page.
   * Returns [] before U3 wires the actual injection point — callers must
   * tolerate an empty table (no-op keydown handler) rather than throw.
   */
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

  /** True while focus is in a text input — keys are inert there (09 §1). */
  function focusIsTextInput() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable === true;
  }

  const KEYMAP = loadKeymap();

  /**
   * Keydown dispatch skeleton. Real arm/confirm/disarm state machine and
   * per-action handlers land at U3 (routes/templates own the actions this
   * dispatches into); this stub only proves the wiring shape: keymap
   * lookup -> action name -> (no-op placeholder).
   */
  function onKeyDown(event) {
    if (focusIsTextInput()) return;
    if (event.ctrlKey || event.altKey || event.metaKey) return; // no chords, ever

    const entry = KEYMAP.find((row) => row.keys.includes(event.key));
    if (!entry) return;

    // U1 stub: no dispatch table yet. U3 wires `entry.action` to the
    // arm/confirm/disarm state machine and the per-screen handlers.
    void entry;
  }

  document.addEventListener("keydown", onKeyDown);

  /**
   * EventSource client stub for GET /events (09 §3 / 10 §1 SSE protocol
   * row). Connection + envelope dispatch land at U3; this only proves the
   * reconnect-tolerant shape the real client will follow.
   */
  function connectEventSource() {
    if (typeof EventSource === "undefined") return null;
    const source = new EventSource("/events");
    source.onmessage = function (event) {
      let envelope;
      try {
        envelope = JSON.parse(event.data);
      } catch (err) {
        console.error("self-learn-ui: malformed SSE frame", err);
        return;
      }
      // U1 stub: envelope.type dispatch (refresh/applying/bulk_progress/
      // banner/pane_*) lands at U3 alongside the partials it targets.
      void envelope;
    };
    source.onerror = function () {
      // Browser auto-retries; the 10 s poll fallback is U3 scope.
    };
    return source;
  }

  if (document.getElementById("self-learn-ui-keymap")) {
    connectEventSource();
  }
})();
