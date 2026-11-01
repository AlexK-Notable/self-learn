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
          // Walk fixes gate r1 F5: the turn is sealed now, so the agent's
          // words the paste rule matches against changed; the line under
          // the reply box is asked again, never left more generous than
          // the record.
          recheckProvenance();
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
    else if (env.type === "attention") { refreshList(); noteResolved(env.ids); recheckProvenance(); }
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
    var changed = !!hidden && hidden.value !== (id || "");
    if (hidden) hidden.value = id || "";
    if (form) {
      if (id && option) form.setAttribute("data-draft-option", option);
      else form.removeAttribute("data-draft-option");
    }
    if (changed) askProvenance(true);
  }

  // ------------------------------------------------------------ provenance

  // Walk fixes, item 2 (C6): ONE line under the reply box says how its
  // text would be recorded, and it comes from the answer verb's own rule
  // (POST .../provenance runs the CLI's preview: the draft id, then the
  // 40-character match against the agent's text). While the box changed
  // and the answer is not back, the line claims nothing ("Checking..."), so
  // the page is never more generous than the record. Answers that arrive
  // out of order are dropped.
  var PROVENANCE_CHECKING = "Checking how this would be recorded\u2026";
  var PROVENANCE_UNKNOWN = "How this would be recorded could not be checked; the line under " +
    "your answer says how it was recorded once you send it.";
  var provenanceSeq = 0;
  var provenanceTimer = null;

  function setProvenance(line, origin) {
    var el = $("#ws-reply-line");
    if (!el) return;
    el.textContent = line;
    el.setAttribute("data-origin", origin || "");
  }

  function askProvenance(now) {
    var box = $("#ws-reply-text");
    var el = $("#ws-reply-line");
    var item = currentItem();
    if (!box || !el || !item) return;
    var seq = ++provenanceSeq;
    if (provenanceTimer) { window.clearTimeout(provenanceTimer); provenanceTimer = null; }
    setProvenance(PROVENANCE_CHECKING, "");
    var send = function () {
      provenanceTimer = null;
      var hidden = $("#ws-reply-draft");
      var body = new URLSearchParams();
      body.set("text", box.value || "");
      body.set("draft_id", hidden ? hidden.value || "" : "");
      fetch("/inbox/" + encodeURIComponent(item) + "/provenance", {
        method: "POST", credentials: "same-origin", body: body,
        headers: { "HX-Request": "true" },
      }).then(function (resp) { return resp.ok ? resp.json() : null; })
        .then(function (data) {
          if (seq !== provenanceSeq || currentItem() !== item) return;
          if (data && typeof data.line === "string") setProvenance(data.line, data.origin);
          else setProvenance(PROVENANCE_UNKNOWN, "");
        }, function () {
          if (seq !== provenanceSeq) return;
          setProvenance(PROVENANCE_UNKNOWN, "");
        });
    };
    if (now) send();
    else provenanceTimer = window.setTimeout(send, 300);
  }

  // The agent texts the rule matches against can change under a box that
  // did not (an ask turn sealed, a new draft): ask again when it holds text.
  function recheckProvenance() {
    var reply = $("#ws-reply-text");
    if (reply && reply.value) askProvenance(true);
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
    askProvenance(true);
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

  // Typing over the whole of a draft (select all, then type) is the same
  // act as emptying the box first: what is sent is the person's own words,
  // so the draft id goes (gate r2 NIT C). Only typing counts: a paste or a
  // drop over everything keeps the id, since what lands may be the draft
  // itself. If the draft's text comes back whole (Ctrl+Z, a paste of it),
  // the id comes back with it, so the agent's words are never sent as
  // the person's.
  var TYPED_INPUT = { insertText: 1, insertCompositionText: 1, insertLineBreak: 1, insertParagraph: 1 };
  var detachedDraft = null;

  function draftCardText(id) {
    var cards = $all("[data-draft-card]");
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].getAttribute("data-draft-id") !== id) continue;
      var el = cards[i].querySelector("[data-draft-text]");
      return el ? el.textContent.trim() : "";
    }
    return "";
  }

  document.addEventListener("beforeinput", function (e) {
    var t = e.target;
    if (!(t instanceof HTMLTextAreaElement) || t.id !== "ws-reply-text") return;
    var hidden = $("#ws-reply-draft");
    var form = $("#ws-answer-form");
    if (!hidden || !hidden.value || !TYPED_INPUT[e.inputType]) return;
    if (!t.value || t.selectionStart !== 0 || t.selectionEnd !== t.value.length) return;
    detachedDraft = {
      item: currentItem(), id: hidden.value,
      option: form ? form.getAttribute("data-draft-option") || "" : "",
    };
    applyDraftMeta("", "");
    storeDraftMeta(currentItem(), "", "");
  });

  function reattachDraft(box, inputType) {
    var d = detachedDraft;
    if (!d || d.item !== currentItem()) return;
    // Only the draft's own text, whole and alone, and put back by a paste,
    // a drop or an undo, brings its id back (ui-workspace gate r3 finding
    // 1, at integration). Words the person typed are their own even when
    // they contain, or spell out, a short draft: they must never be sent
    // as the agent's draft with the draft's option.
    if (TYPED_INPUT[inputType]) return;
    var text = draftCardText(d.id);
    if (!text || box.value.trim() !== text) return;
    applyDraftMeta(d.id, d.option);
    storeDraftMeta(d.item, d.id, d.option);
    detachedDraft = null;
  }

  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!(t instanceof Element)) return;
    if (t.id === "ws-reply-text") {
      store("reply", currentItem(), t.value);
      if (!t.value) {
        applyDraftMeta("", "");
        storeDraftMeta(currentItem(), "", "");
      } else {
        reattachDraft(t, e.inputType);
      }
      askProvenance(false);
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
      if (reply.value) askProvenance(true);
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
    if (draftOption && !params.option) {
      // Walk fixes gate r1 F2: the option rides with the agent's draft, not
      // with a click on that option's own button; the route arms it when it
      // approves or registers (Send, Ctrl+Enter alike).
      params.option = draftOption;
      params.from_draft = "1";
    }
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
    // Walk fixes, item 7: "Recording..." and the busy buttons are for a
    // request that redraws the answer bar (an answer, an undo, a stop).
    // Run it now, a fix, a login check or feedback swap only their own
    // result box; they used to leave every button aria-disabled and
    // "Recording..." under the box for good, so the next Send click on a
    // running item was refused as a click on a disabled button.
    if (elt && elt.closest && elt.closest("#ws-answer") && redrawsAnswerBar(e.detail)) {
      $all("#ws-answer button").forEach(function (b) { b.setAttribute("aria-disabled", "true"); });
      var line = $("#ws-reply-line");
      if (line) {
        line.setAttribute("data-before-recording", line.textContent);
        line.textContent = "Recording…";
      }
    }
  });

  var BAR_PATH_RE = /^\/inbox\/att-[0-9a-f]{12}\/(answer|undo|stop)$/;

  function redrawsAnswerBar(detail) {
    return BAR_PATH_RE.test(requestPath(detail).split("?")[0]);
  }

  function dropNewMarks(id) {
    if (currentItem() === id) $all("#ws [data-new-mark]").forEach(function (m) { m.remove(); });
    $all("#inbox-list [data-inbox-item=\"" + id + "\"] .dot-new").forEach(function (m) { m.remove(); });
  }

  document.addEventListener("htmx:afterRequest", function (e) {
    var own = ownItem(e.detail);
    if (own && own === ownAction.item) {
      ownAction.pending = false;
      ownAction.until = Date.now() + OWN_GRACE_MS;
    }
    // Whatever the request was, a bar it did not redraw is live again.
    $all("#ws-answer [aria-disabled=\"true\"]").forEach(function (b) { b.removeAttribute("aria-disabled"); });
    var line = $("#ws-reply-line");
    if (line && line.textContent === "Recording…") {
      line.textContent = line.getAttribute("data-before-recording") || "";
      line.removeAttribute("data-before-recording");
    }
    // Walk fixes, item 8: once the seen click is recorded, the "new" mark
    // goes from the page header and from the item's list row together.
    var seen = /^\/inbox\/(att-[0-9a-f]{12})\/seen$/.exec(requestPath(e.detail).split("?")[0]);
    if (seen && e.detail.xhr && e.detail.xhr.status >= 200 && e.detail.xhr.status < 300) {
      dropNewMarks(seen[1]);
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

  // Walk fixes, item 4: a result that belongs at the top of the page (a
  // login check that worked) is brought into view and announced, so it is
  // never left below the fold while the item quietly leaves the list.
  document.addEventListener("htmx:oobAfterSwap", function (e) {
    var swapped = e.detail && e.detail.target;
    if (!swapped || swapped.id !== "ws-top-result") return;
    var target = $("#ws-top-result");  // the element now in the page
    if (!target || !target.textContent.trim()) return;
    try { target.scrollIntoView({ block: "start" }); } catch (err) { target.scrollIntoView(); }
    announce(target.textContent.replace(/\s+/g, " ").trim());
  });

  document.addEventListener("htmx:afterSwap", function (e) {
    var target = e.detail.target;
    if (!target) return;
    if (target.id === "inbox-workspace") {
      detachedDraft = null;
      markSelected(currentItem());
      restoreUnsent();
      var title = $("#ws");
      if (title) document.title = "self-learn — Inbox · " + (title.getAttribute("data-item-title") || "");
    }
    // Only a recorded send of the reply form itself (an option, Send, or
    // the armed Confirm, all POST .../answer, carrying the box's text)
    // empties the stored reply. Undo, redo, Run it now, a fix or a login
    // check never carried the text: the answer bar they re-render comes
    // back with an empty box, so it is refilled from what was typed
    // (gate r2 finding 1; "nothing typed is ever lost").
    var inAnswer = target.id === "ws-answer" || !!(target.closest && target.closest("#ws-answer"));
    var path = OWN_PATH_RE.exec(requestPath(e.detail).split("?")[0]);
    // A draft card's "Send as is" also posts to .../answer, but it sends
    // the card's text, not the box's (ui-workspace gate r3 NIT A, at
    // integration): the box's own words are cleared only when they are
    // what that card sent.
    var elt = e.detail && e.detail.requestConfig ? e.detail.requestConfig.elt : null;
    var card = elt && elt.closest ? elt.closest("[data-draft-card]") : null;
    // Gate r1 F2: a card's approve option now arms first, so its send can
    // arrive from the armed bar's Confirm: that form carries the text it
    // sends, and the box's words are cleared only when they are that text.
    var armedForm = !card && elt && elt.closest ? elt.closest("[data-armed-answer]") : null;
    var armedText = armedForm ? armedForm.querySelector("input[name=\"text\"]") : null;
    var sentReply = !!path && path[2] === "answer" && (
      card ? recall("reply", currentItem()).trim() === draftCardText(card.getAttribute("data-draft-id"))
        : armedForm ? recall("reply", currentItem()).trim() === (armedText ? armedText.value : "").trim()
          : true
    );
    var recorded = $("#ws-answer [data-recorded]");
    if (recorded && inAnswer) {
      if (sentReply) {
        store("reply", currentItem(), "");
        storeDraftMeta(currentItem(), "", "");
        detachedDraft = null;
      }
      announce(recorded.textContent.replace(/\s+/g, " ").trim());
    }
    if (target.id === "ws-answer" && !(recorded && sentReply)) restoreUnsent();
    // A failed answer re-renders the bar keeping the hidden draft id but
    // not its note or option (ui-workspace gate r3 NIT B, at integration):
    // the page would say "Recorded as your words." while a retry sends
    // --draft. Put the draft's note and option back with its id.
    var keptDraft = $("#ws-reply-draft");
    if (target.id === "ws-answer" && keptDraft && keptDraft.value) {
      var keptMeta = recallDraftMeta(currentItem());
      applyDraftMeta(keptDraft.value, keptMeta && keptMeta.id === keptDraft.value ? keptMeta.option : "");
    }
    var err = $("#ws-answer [data-answer-error]");
    if (err && target.id === "ws-answer") announce(err.textContent.replace(/\s+/g, " ").trim());
    // Walk fixes gate r1 F3 (the orchestrator's ruling): the page never
    // moves focus onto an approve or register button by itself. An armed
    // bar puts it on Cancel, so a stray Enter or Space backs out.
    var cancel = target.id === "ws-answer" ? $("#ws-answer [data-armed-cancel]") : null;
    if (cancel) cancel.focus();
    if (target.id === "ws-answer" || target.id === "inbox-workspace") {
      var kept = $("#ws-reply-text");
      if (kept && kept.value) askProvenance(true);
    }
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
    if (el.id === "ws-reply-text") {
      keyedClick = true;
      try { return clickIfPresent("[data-send-reply]"); } finally { keyedClick = false; }
    }
    if (el.id === "ws-ask-text") return clickIfPresent("[data-ask-send]");
    return false;
  }

  // Walk fixes, item 1: a number key never approves or registers. On an
  // option whose effect is approve or register it ARMS the option (the
  // answer route answers `keyed=1` with the once-more confirmation a
  // confirm option gets); a mouse click on the same button still sends at
  // once (design r2 §0 call 3).
  var keyedClick = false;

  function pressOption(key) {
    var btn = $("#ws-answer [data-option-index=\"" + key + "\"]");
    if (!btn || btn.disabled || btn.hidden) return;
    var effect = btn.getAttribute("data-effect");
    keyedClick = effect === "approve" || effect === "register";
    try { btn.click(); } finally { keyedClick = false; }
  }

  document.addEventListener("htmx:configRequest", function (e) {
    if (!keyedClick) return;
    var path = String(e.detail.path || "").split("?")[0];
    if (/\/answer$/.test(path)) e.detail.parameters.keyed = "1";
  });

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
        // Walk fixes gate r1 F1: a held key's auto-repeat never acts, and
        // while something is armed no number key does anything: only the
        // armed bar's own Confirm button confirms (a click, or Enter/Space
        // with it focused), so a digit can never approve.
        if (event.repeat) break;
        if ($("#ws-answer [data-armed-answer], #ws-answer [data-armed-stop]")) break;
        pressOption(event.key);
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
