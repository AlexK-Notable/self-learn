/*
 * self-learn-ui — settings.js (humane lane 4).
 *
 * The settings page's three small behaviours. The page works without this
 * file (a plain form submit filters on the server, Save is always shown);
 * this only makes it quicker:
 *   1. "Find a setting" filters as you type. It reads the same text the
 *      server filter reads (each row's data-find) and applies the same
 *      rule: every typed word must appear.
 *   2. A row's Save button shows once its value has changed.
 *   3. A jump chip or a #group link opens a closed group.
 * No keyboard binding is added (the settings page has none; app.js keeps
 * keys inert while a field has focus).
 */
(function () {
  "use strict";

  var input = document.querySelector("[data-settings-find]");
  var status = document.querySelector("[data-settings-status]");
  var none = document.querySelector("[data-settings-none]");
  var clear = document.querySelector("[data-settings-clear]");
  var groups = Array.prototype.slice.call(document.querySelectorAll("[data-settings-group]"));
  // Folded groups' open state before a search opened them, to restore on clear.
  var wasOpen = new Map();

  function terms(text) {
    return text.toLowerCase().split(/\s+/).filter(Boolean);
  }

  function applyFilter() {
    if (!input) return;
    var typed = input.value.trim();
    var wanted = terms(typed);
    var shown = 0;
    groups.forEach(function (group) {
      var inGroup = 0;
      var rows = group.querySelectorAll("li.setting");
      rows.forEach(function (row) {
        var text = row.getAttribute("data-find") || "";
        var hit = wanted.every(function (t) { return text.indexOf(t) !== -1; });
        row.hidden = !hit;
        if (hit) inGroup += 1;
      });
      var count = group.querySelector("[data-settings-count]");
      if (count) {
        var total = parseInt(count.getAttribute("data-total"), 10);
        count.textContent = "(" + (wanted.length && inGroup < total ? inGroup + " of " : "") + total + ")";
      }
      var classes = group.querySelector("[data-settings-classes]");
      if (classes) {
        classes.hidden = classes.querySelectorAll("li.setting:not([hidden])").length === 0;
      }
      group.hidden = inGroup === 0;
      var chip = document.querySelector('[data-settings-chip="' + group.id.replace(/^group-/, "") + '"]');
      if (chip) chip.hidden = inGroup === 0;
      shown += inGroup;
      if (group.tagName === "DETAILS") {
        if (wanted.length && inGroup > 0) {
          if (!wasOpen.has(group)) wasOpen.set(group, group.open);
          group.open = true;
        } else if (!wanted.length && wasOpen.has(group)) {
          group.open = wasOpen.get(group);
          wasOpen.delete(group);
        }
      }
    });
    if (status) {
      status.textContent = wanted.length
        ? shown + (shown === 1 ? " setting matches" : " settings match") + " “" + typed + "”."
        : "";
    }
    if (none) none.hidden = !(wanted.length && shown === 0);
    if (clear) clear.hidden = !wanted.length;
  }

  if (input) {
    input.addEventListener("input", applyFilter);
    var form = input.closest("form");
    if (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        applyFilter();
      });
    }
    // A page the server already filtered (?q=) must still clear in the page.
    // Its closed groups were opened by the server: remember them as closed.
    if (input.value.trim()) {
      groups.forEach(function (group) {
        if (group.tagName === "DETAILS" && group.classList.contains("settings-group-folded")) {
          wasOpen.set(group, false);
        }
      });
    }
  }

  // ---- Save shows only once a value changed -------------------------------
  // A changed field also marks its form [data-setting-dirty], which holds the
  // page's reload (app.js leg g) so a refresh never throws away what is being
  // typed; taking the edit back releases it.
  function release() {
    document.dispatchEvent(new CustomEvent("self-learn:release-reload"));
  }

  function watchForm(form) {
    if (form.getAttribute("data-watched")) return;
    form.setAttribute("data-watched", "1");
    var save = form.querySelector("[data-setting-save]");
    if (!save) return;
    var li = form.closest("li.setting");
    // After a refused save the field shows the stored value and Save stays.
    var refused = !!(li && li.querySelector("[data-setting-error]"));
    var field = form.querySelector("[name=value]");
    if (!field) return;
    function original() {
      if (field.tagName === "SELECT") {
        var sel = null;
        for (var i = 0; i < field.options.length; i += 1) {
          if (field.options[i].defaultSelected) sel = field.options[i];
        }
        return sel ? sel.value : field.options[0].value;
      }
      return field.defaultValue;
    }
    var start = original();
    if (!refused) save.hidden = true;
    function update() {
      var changed = field.value !== start;
      save.hidden = !changed;
      if (changed) {
        // The row's last message described the previous save; it is stale now.
        var msg = li && li.querySelector("[data-setting-message]");
        if (msg) msg.remove();
        form.setAttribute("data-setting-dirty", "");
      } else if (form.hasAttribute("data-setting-dirty")) {
        form.removeAttribute("data-setting-dirty");
        release();
      }
    }
    field.addEventListener("input", update);
    field.addEventListener("change", update);
  }

  // Dismiss: remove the message (its marker was the hold) and let a held
  // reload fire.
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    var btn = t && t.closest ? t.closest("[data-setting-dismiss]") : null;
    if (!btn) return;
    var msg = btn.closest("[data-setting-message]");
    if (msg) msg.remove();
    release();
  });

  function watchAll(root) {
    root.querySelectorAll("form[data-setting-form]").forEach(watchForm);
  }
  watchAll(document);
  // A saved row is swapped in whole. htmx fires `htmx:load` on the NEW
  // element (afterSettle fires on the replaced, detached one): watch its form.
  document.body.addEventListener("htmx:load", function (ev) {
    var t = ev.target;
    if (t && t.querySelectorAll) watchAll(t);
  });

  // ---- jump chips and #group links open a closed group --------------------
  function openTarget() {
    var id = window.location.hash.replace(/^#/, "");
    if (!id) return;
    var el = document.getElementById(id);
    if (el && el.tagName === "DETAILS") el.open = true;
  }
  window.addEventListener("hashchange", openTarget);
  document.querySelectorAll("[data-settings-chip]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var el = document.getElementById("group-" + chip.getAttribute("data-settings-chip"));
      if (el && el.tagName === "DETAILS") el.open = true;
    });
  });
  openTarget();
})();
