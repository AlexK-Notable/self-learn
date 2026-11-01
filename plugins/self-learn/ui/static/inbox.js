/*
 * self-learn-ui — inbox.js: the inbox page's keys, its live answer, and
 * its conveniences (attention round, design r2 §3.3 "Streaming to the
 * page", §3.6 "Accessibility and keyboard", §3.7).
 *
 * Loaded only on inbox pages (templates/inbox.html). app.js stays inert
 * there for keys and relays the inbox's SSE envelopes (`ask`,
 * `attention`) as a `self-learn:sse` DOM event; its reload chokepoint sends
 * `self-learn:refresh` instead of reloading, so nothing typed is ever lost
 * to a refresh.
 *
 * The keys come from the page's keymap blob (keymap.py's INBOX_KEYMAP —
 * one source for this file, the footer and the ? overlay). None fires
 * while a text field has focus, except Ctrl+Enter (send the box) and
 * Escape (stop the agent's answer, or leave the field).
 *
 * localStorage holds an unsent reply or question per item: a convenience
 * only, every access in try/catch, and the page works the same without it.
 */
(function () {
  "use strict";

  // ------------------------------------------------------------ helpers

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function currentItem() {
    var ws = $("#ws");
    return ws ? ws.getAttribute("data-item-id") : null;
  }

  function announce(text) {
    var live = $("#inbox-live");
    if (!live) return;
    live.textContent = "";
    window.setTimeout(function () { live.textContent = text; }, 30);
  }

  function store(kind, item, value) {
    if (!item) return;
    try {
      var key = "slu-inbox-" + kind + ":" + item;
      if (value) window.localStorage.setItem(key, value);
      else window.localStorage.removeItem(key);
    } catch (err) { /* a convenience only */ }
  }

  function recall(kind, item) {
    if (!item) return "";
    try { return window.localStorage.getItem("slu-inbox-" + kind + ":" + item) || ""; }
    catch (err) { return ""; }
  }

  function loadKeys() {
    var el = document.getElementById("self-learn-ui-keymap");
    if (!el) return [];
    try { return JSON.parse(el.textContent || "[]"); } catch (err) { return []; }
  }
  var KEYS = loadKeys();

  function inTextField() {
    var el = document.activeElement;
    if (!el) return false;
    return el.tagName === "TEXTAREA" || el.tagName === "INPUT" || el.isContentEditable === true;
  }

  function helpOverlay() { return document.getElementById("self-learn-ui-help"); }

  function toggleHelp() {
    var o = helpOverlay();
    if (o) o.hidden = !o.hidden;
  }

  function clickIfPresent(sel) {
    var el = $(sel);
    if (el && !el.disabled && !el.hidden) { el.click(); return true; }
    return false;
  }

  // ------------------------------------------------------------ the list

  function listLinks() { return $all("#inbox-list [data-inbox-item] a"); }

  function moveInList(step) {
    var links = listLinks();
    if (!links.length) return;
    var idx = links.indexOf(document.activeElement);
    if (idx === -1) {
      var cur = $("#inbox-list [data-inbox-item].selected a");
      idx = cur ? links.indexOf(cur) : -1;
    }
    var next = links[Math.max(0, Math.min(links.length - 1, idx + step))];
    if (next) next.focus();
  }

  function markSelected(id) {
    $all("#inbox-list [data-inbox-item]").forEach(function (li) {
      var on = li.getAttribute("data-inbox-item") === id;
      li.classList.toggle("selected", on);
      var a = li.querySelector("a");
      if (a) { if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }
    });
    var root = $("[data-inbox]");
    if (root) root.setAttribute("data-selected", id || "");
  }

  var refreshTimer = null;
  function refreshList() {
    if (refreshTimer) return;
    refreshTimer = window.setTimeout(function () {
      refreshTimer = null;
      if (typeof htmx === "undefined" || !$("#inbox-list")) return;
      var sel = currentItem() || "";
      htmx.ajax("GET", "/inbox/list?selected=" + encodeURIComponent(sel),
        { target: "#inbox-list", swap: "outerHTML" });
    }, 250);
  }

  // The person's own click on this item (an answer, an undo, a run, a
  // fix, a login check) publishes an `attention` envelope from inside the
  // verb, so the envelope can arrive before or just after the response.
  // An item that left the list because of that click was not "resolved
  // elsewhere" (gate r1 finding 2): while the request is in flight, and
  // for a short grace after it, the banner stays off; after that, the
  // response's own markers (data-answer-closed, data-item-resolved) say
  // the click did it.
  var OWN_GRACE_MS = 3000;
  var ownAction = { item: null, pending: false, until: 0 };
  var OWN_PATH_RE = /^\/inbox\/(att-[0-9a-f]{12})\/(answer|undo|run|fix|check-login)$/;

  function requestPath(detail) {
    if (!detail) return "";
    if (detail.pathInfo && detail.pathInfo.requestPath) return String(detail.pathInfo.requestPath);
    if (detail.requestConfig && detail.requestConfig.path) return String(detail.requestConfig.path);
    return "";
  }

  function ownItem(detail) {
    var m = OWN_PATH_RE.exec(requestPath(detail).split("?")[0]);
    return m ? m[1] : null;
  }

  function resolvedByThisPage(id) {
    if (ownAction.item === id && (ownAction.pending || Date.now() < ownAction.until)) return true;
    return !!$("#ws [data-answer-closed], #ws [data-item-resolved]");
  }

  function noteResolved(ids) {
    var id = currentItem();
    if (!id || !Array.isArray(ids) || ids.indexOf(id) !== -1) return;
    if ($("[data-resolved-banner]")) return;
    if (resolvedByThisPage(id)) return;
    var ws = $("#ws .ws-main");
    if (!ws) return;
    var p = document.createElement("p");
    p.className = "banner banner-notice";
    p.setAttribute("data-resolved-banner", "");
    p.setAttribute("role", "status");
    p.textContent = "This item was resolved elsewhere (answered, withdrawn, or its condition cleared). ";
    var a = document.createElement("a");
    a.href = "/inbox";
    a.textContent = "Go to the next item";
    p.appendChild(a);
    ws.prepend(p);
    announce("This item was resolved elsewhere.");
  }

  // ------------------------------------------------------------ the live answer

  function liveBubble() { return $("#ws-live-bubble"); }

  function setAsking(on) {
    var box = $("#ws-ask-text");
    var send = $("[data-ask-send]");
    var stop = $("[data-ask-stop]");
    var off = !!$("[data-ask-off]");
    if (box) box.disabled = on || off;
    if (send) send.disabled = on || off;
    if (stop) stop.hidden = !on;
  }

  function onAsk(env) {
    if (env.item !== currentItem()) return;
    var bubble = liveBubble();
    var ev = env.ev;
    if (ev === "start") {
      setAsking(true);
      return;
    }
    if (ev === "delta" && bubble) {
      var t = bubble.querySelector("[data-live-text]");
      if (t) t.textContent += env.text || "";
      return;
    }
    if (ev === "tool" && bubble) {
      var tool = bubble.querySelector("[data-live-tool]");
      if (tool) tool.textContent = "looking at " + (env.target || env.name || "");
      return;
    }
    if (ev === "draft" && bubble) {
      var drafts = bubble.querySelector("[data-live-drafts]");
      if (drafts) {
        var d = document.createElement("p");
        d.className = "ws-meta";
        d.textContent = "The agent drafted a reply; it appears below when the answer is finished.";
        drafts.appendChild(d);
      }
      return;
    }
    if (ev === "done" && bubble) {
      var txt = bubble.querySelector("[data-live-text]");
      if (txt && typeof env.text === "string") txt.textContent = env.text;
      return;
    }
    if (ev === "error") {
      var status = $("#ws-ask-status");
      if (status) {
        status.textContent = "";
        var p = document.createElement("p");
        p.className = "ws-ask-note";
        p.setAttribute("role", "alert");
        var why = env.message || "the agent could not answer";
        if (env.code === "login") why = "The agent can't answer while the Claude login is broken. " + (env.fix || "");
        else if (env.code === "money") why = "Asking would bill an API key (or Bedrock) here, so it is off. Nothing was sent.";
        else if (env.code === "timeout") why = "The answer took too long and was stopped. Ask again: the conversation is intact.";
        else if (env.code === "turn-cap") why = "The agent reached its step limit. Ask again: the conversation is intact.";
        else if (env.code === "interrupted") why = (env.message || "Stopped.") + " Ask again when you like.";
        p.textContent = why;
        status.appendChild(p);
      }
      announce("The agent stopped: " + (env.message || env.code || ""));
      return;
    }
    if (ev === "end") {
      setAsking(false);
      if (bubble) bubble.setAttribute("aria-busy", "false");
      if (typeof htmx !== "undefined" && $("#ws-conversation")) {
        htmx.ajax("GET", "/inbox/" + encodeURIComponent(env.item) + "/conversation",
          { target: "#ws-conversation", swap: "innerHTML" }).then(function () {
          var live = $("#ws-ask-live");
          if (live) live.innerHTML = "";
          var box = $("#ws-ask-text");
          if (box && !box.disabled) box.focus();
        });
      }
      if (env.exit === 0) announce("The agent finished answering.");
    }
  }

  document.addEventListener("self-learn:sse", function (e) {
    var env = e.detail || {};
    if (env.type === "ask") onAsk(env);
    else if (env.type === "attention") { refreshList(); noteResolved(env.ids); }
  });
  document.addEventListener("self-learn:refresh", refreshList);

  // ------------------------------------------------------------ drafts, chips, copy

  // A reply that started as the agent's draft keeps the draft's id and
  // option with its text, in the page and in localStorage alike (C6, gate
  // r1 finding 1): restored text without its draft id would reach the
  // answer verb with no --draft, and a short draft would be recorded as
  // the person's own typed words.
  var DRAFT_ID_RE = /^drf-[0-9a-f]{8}$/;
  var OPTION_ID_RE = /^opt-[a-z0-9-]{1,48}$/;

  function applyDraftMeta(id, option) {
    var hidden = $("#ws-reply-draft");
    var form = $("#ws-answer-form");
    var note = $("#ws-reply-draft-note");
    if (hidden) hidden.value = id || "";
    if (form) {
      if (id && option) form.setAttribute("data-draft-option", option);
      else form.removeAttribute("data-draft-option");
    }
    if (note) note.hidden = !id;
  }

  function storeDraftMeta(item, id, option) {
    store("reply-draft", item, id ? JSON.stringify({ id: id, option: option || "" }) : "");
  }

  function recallDraftMeta(item) {
    var raw = recall("reply-draft", item);
    if (!raw) return null;
    try {
      var meta = JSON.parse(raw);
      if (!meta || !DRAFT_ID_RE.test(String(meta.id || ""))) return null;
      var option = String(meta.option || "");
      return { id: String(meta.id), option: OPTION_ID_RE.test(option) ? option : "" };
    } catch (err) { return null; }
  }

  function setDraft(id, text, option) {
    var box = $("#ws-reply-text");
    if (!box || !$("#ws-reply-draft") || !$("#ws-answer-form")) return;
    box.value = text;
    applyDraftMeta(id, option);
    store("reply", currentItem(), text);
    storeDraftMeta(currentItem(), id, option);
    box.focus();
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!(t instanceof Element)) return;
    var use = t.closest("[data-use-draft]");
    if (use) {
      var card = use.closest("[data-draft-card]");
      if (card) {
        var text = (card.querySelector("[data-draft-text]") || {}).textContent || "";
        setDraft(card.getAttribute("data-draft-id"), text, card.getAttribute("data-draft-option"));
      }
      return;
    }
    var chip = t.closest("[data-ask-chip]");
    if (chip && !chip.disabled) {
      var box = $("#ws-ask-text");
      var form = $("#ws-ask-form");
      if (box && form && !box.disabled) {
        box.value = chip.textContent.trim();
        if (typeof form.requestSubmit === "function") form.requestSubmit();
      }
      return;
    }
    var copy = t.closest("[data-copy]");
    if (copy) {
      var src = $(copy.getAttribute("data-copy"));
      if (!src) return;
      var done = function () { copy.textContent = "Copied"; window.setTimeout(function () { copy.textContent = "Copy"; }, 1500); };
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(src.textContent).then(done, function () {});
      } catch (err) { /* the text stays selectable */ }
    }
  });

  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!(t instanceof Element)) return;
    if (t.id === "ws-reply-text") {
      store("reply", currentItem(), t.value);
      if (!t.value) {
        applyDraftMeta("", "");
        storeDraftMeta(currentItem(), "", "");
      }
    } else if (t.id === "ws-ask-text") {
      store("ask", currentItem(), t.value);
    }
  });

  function restoreUnsent() {
    var id = currentItem();
    var reply = $("#ws-reply-text");
    var ask = $("#ws-ask-text");
    if (reply && !reply.value) {
      reply.value = recall("reply", id);
      var hidden = $("#ws-reply-draft");
      var meta = reply.value ? recallDraftMeta(id) : null;
      if (meta && hidden && !hidden.value) applyDraftMeta(meta.id, meta.option);
    }
    if (ask && !ask.value && !ask.disabled) ask.value = recall("ask", id);
  }

  // ------------------------------------------------------------ htmx hooks

  document.addEventListener("htmx:configRequest", function (e) {
    var elt = e.detail.elt;
    var form = elt && elt.closest ? elt.closest("#ws-answer-form") : null;
    if (!form) return;
    var params = e.detail.parameters;
    var draftOption = form.getAttribute("data-draft-option");
    if (draftOption && !params.option) params.option = draftOption;
  });

  document.addEventListener("htmx:beforeRequest", function (e) {
    var elt = e.detail.elt;
    var own = ownItem(e.detail);
    if (own) { ownAction.item = own; ownAction.pending = true; ownAction.until = 0; }
    if (elt && elt.id === "ws-ask-form") {
      setAsking(true);
      var status = $("#ws-ask-status");
      if (status) status.textContent = "";
    }
    if (elt && elt.closest && elt.closest("#ws-answer")) {
      $all("#ws-answer button").forEach(function (b) { b.setAttribute("aria-disabled", "true"); });
      var line = $("#ws-reply-line");
      if (line) line.textContent = "Recording…";
    }
  });

  document.addEventListener("htmx:afterRequest", function (e) {
    var own = ownItem(e.detail);
    if (own && own === ownAction.item) {
      ownAction.pending = false;
      ownAction.until = Date.now() + OWN_GRACE_MS;
    }
  });

  document.addEventListener("htmx:beforeSwap", function (e) {
    var status = e.detail.xhr ? e.detail.xhr.status : 200;
    if (status === 400 || status === 404 || status === 409) {
      e.detail.shouldSwap = true;
      e.detail.isError = false;
      var elt = e.detail.requestConfig ? e.detail.requestConfig.elt : null;
      if (elt && elt.id === "ws-ask-form") {
        e.detail.target = $("#ws-ask-status") || e.detail.target;
        setAsking(status === 409 && !!liveBubble());
      }
    }
  });

  document.addEventListener("htmx:afterSwap", function (e) {
    var target = e.detail.target;
    if (!target) return;
    if (target.id === "inbox-workspace") {
      markSelected(currentItem());
      restoreUnsent();
      var title = $("#ws");
      if (title) document.title = "self-learn — Inbox · " + (title.getAttribute("data-item-title") || "");
    }
    var recorded = $("#ws-answer [data-recorded]");
    if (recorded && (target.id === "ws-answer" || target.closest && target.closest("#ws-answer"))) {
      store("reply", currentItem(), "");
      storeDraftMeta(currentItem(), "", "");
      announce(recorded.textContent.replace(/\s+/g, " ").trim());
    }
    var err = $("#ws-answer [data-answer-error]");
    if (err && target.id === "ws-answer") announce(err.textContent.replace(/\s+/g, " ").trim());
    if (target.id === "ws-ask-live") {
      store("ask", currentItem(), "");
      var box = $("#ws-ask-text");
      if (box) box.value = "";
    }
  });

  // ------------------------------------------------------------ keys

  function entryFor(event) {
    for (var i = 0; i < KEYS.length; i++) {
      if (KEYS[i].keys.indexOf(event.key) !== -1) return KEYS[i];
    }
    return null;
  }

  function sendFocusedBox() {
    var el = document.activeElement;
    if (!el) return false;
    if (el.id === "ws-reply-text") return clickIfPresent("[data-send-reply]");
    if (el.id === "ws-ask-text") return clickIfPresent("[data-ask-send]");
    return false;
  }

  function onKey(event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      if (sendFocusedBox()) event.preventDefault();
      return;
    }
    if (event.key === "Escape") {
      if (clickIfPresent("[data-ask-stop]:not([hidden])")) { event.preventDefault(); return; }
      if (inTextField()) { document.activeElement.blur(); event.preventDefault(); }
      var o = helpOverlay();
      if (o && !o.hidden) o.hidden = true;
      return;
    }
    if (inTextField()) return;
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    var overlay = helpOverlay();
    if (overlay && !overlay.hidden) { overlay.hidden = true; event.preventDefault(); return; }
    var entry = entryFor(event);
    if (!entry) return;
    switch (entry.action) {
      case "inbox_next": moveInList(1); break;
      case "inbox_prev": moveInList(-1); break;
      case "inbox_open": {
        // §3.6: Enter opens from the list. A focused control anywhere
        // else (an option, Copy, an evidence <summary>, a link) does its
        // own thing on Enter, and the selected item is not reloaded over
        // it (gate r1 finding 5); a focused list link opens natively.
        var a = document.activeElement;
        if (a && a !== document.body && a !== document.documentElement) return;
        var sel = $("#inbox-list [data-inbox-item].selected a") || listLinks()[0];
        if (sel) sel.click();
        break;
      }
      case "inbox_option": {
        var armed = $("[data-confirm-armed]");
        if (armed && event.key === "1") { armed.click(); break; }
        clickIfPresent("#ws-answer [data-option-index=\"" + event.key + "\"]");
        break;
      }
      case "inbox_reply": { var r = $("#ws-reply-text"); if (r) r.focus(); break; }
      case "inbox_ask": { var q = $("#ws-ask-text"); if (q && !q.disabled) q.focus(); break; }
      case "inbox_undo": clickIfPresent("#ws-answer [data-undo]"); break;
      case "inbox_seen_all": clickIfPresent("[data-inbox-action=\"seen_all\"]"); break;
      case "help": toggleHelp(); break;
      default: return;
    }
    event.preventDefault();
  }

  document.addEventListener("keydown", onKey);
  document.addEventListener("DOMContentLoaded", function () {
    restoreUnsent();
    if (liveBubble()) setAsking(true);
  });
})();
