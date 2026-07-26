/* Surface enumerator + perceptual digest for agent-driven UI walks.
 *
 * Inject once per page load with browser_evaluate, then call the two
 * entry points in tiny follow-up calls:
 *
 *     window.__uiProbe.surfaces()   -> everything a human could act on
 *     window.__uiProbe.digest()     -> what CHANGED since the last call
 *
 * Both live in one file because they share the perceptibility helpers,
 * and those helpers are the whole point: the accessibility tree reports
 * an element at `opacity: 0` as present, and `is_visible()` returns true
 * for it. Measured on this UI's own applying-strip. A digest built on
 * DOM presence would reproduce that lie exactly, so everything here is
 * gated on what actually reaches a person's eye.
 *
 * Design notes that matter for cost:
 *   - digest() returns a DELTA, not a snapshot. Nothing changed -> a few
 *     bytes. Since most surfaces in a walk change nothing, total token
 *     cost tracks the number of INTERESTING surfaces, not the number of
 *     surfaces.
 *   - the previous digest is stashed in sessionStorage, so it survives
 *     same-origin navigation (window globals do not).
 */
(function () {
  "use strict";

  var STORE_KEY = "__uiProbe.prev";
  var TEXT_CAP = 90;
  var STALE_MS = 10 * 60 * 1000;

  // ------------------------------------------------------ perceptibility

  /* Opacity is multiplicative down the ancestor chain, and an element's
   * OWN computed opacity stays "1" under a parent at 0 — so reading the
   * element alone reports a fully-visible element that nobody can see. */
  function effectiveOpacity(el) {
    var o = 1;
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
      var v = parseFloat(getComputedStyle(n).opacity);
      if (!isNaN(v)) o *= v;
      if (o === 0) return 0;
    }
    return o;
  }

  function inViewport(r) {
    return (
      r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth
    );
  }

  /* Something painted on top. elementFromPoint returns the topmost node
   * at that point; if it is neither inside nor containing our element,
   * our element is covered there. */
  function occluded(el, r) {
    var x = r.left + r.width / 2;
    var y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;
    var hit = document.elementFromPoint(x, y);
    if (!hit) return true;
    return !(el === hit || el.contains(hit) || hit.contains(el));
  }

  function perceptible(el) {
    var cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    if (!inViewport(r)) return false;
    if (effectiveOpacity(el) < 0.05) return false;
    if (occluded(el, r)) return false;
    return true;
  }

  /* Why an element is not perceptible — the interesting part when a
   * click was supposed to reveal something and did not. */
  function invisibleBecause(el) {
    var cs = getComputedStyle(el);
    if (cs.display === "none") return "display:none";
    if (cs.visibility === "hidden") return "visibility:hidden";
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return "zero-size";
    if (effectiveOpacity(el) < 0.05) return "opacity:" + effectiveOpacity(el);
    if (!inViewport(r)) return "off-viewport";
    if (occluded(el, r)) return "occluded";
    return null;
  }

  // ------------------------------------------------------------ identity

  /* Two normalisations, because identity and change want OPPOSITE
   * things and a single function cannot serve both.
   *
   * normId: for "is this the same surface I already visited?" — record
   * ids and row numbers are stripped so the Graduate button on row 2
   * collapses onto row 1 and coverage counts surface KINDS.
   *
   * normValue: for "did this change?" — digits are PRESERVED, because
   * they are most of what changes in this UI. The first version used
   * normId for both, so a bucket going "7 pending" -> "6 pending"
   * compared "# pending" against "# pending" and reported no change.
   * Measured: a real graduation produced ZERO digest lines, and the only
   * thing reported was a relative clock ticking over.
   */
  function normId(s) {
    return normValue(s)
      .replace(/\blrn-[0-9a-f]{6,}\b/gi, "lrn-*")
      .replace(/\d+/g, "#")
      .slice(0, TEXT_CAP);
  }

  function normValue(s) {
    return (s || "").replace(/\s+/g, " ").trim().slice(0, TEXT_CAP);
  }

  function cssPath(el) {
    if (el.id) return "#" + CSS.escape(el.id);
    var parts = [];
    for (var n = el; n && n.nodeType === 1 && n !== document.body; n = n.parentElement) {
      var tag = n.tagName.toLowerCase();
      var p = n.parentElement;
      if (p) {
        var same = Array.prototype.filter.call(p.children, function (c) {
          return c.tagName === n.tagName;
        });
        if (same.length > 1) tag += ":nth-of-type(" + (same.indexOf(n) + 1) + ")";
      }
      parts.unshift(tag);
      if (n.id) {
        // REPLACE the tag just pushed — an id and its own tag are the
        // same element, and emitting both makes them two levels of the
        // descendant chain, so the selector matches nothing.
        parts[0] = "#" + CSS.escape(n.id);
        break;
      }
    }
    return parts.join(" > ");
  }

  function label(el) {
    var t =
      el.getAttribute("aria-label") ||
      el.getAttribute("title") ||
      el.value ||
      el.textContent ||
      "";
    return normId(t);
  }

  /* Where a thing is, named so that it SURVIVES its neighbours being
   * removed.
   *
   * cssPath counts position ("3rd row > link"). Delete a row and every
   * row below slides up, so position 3 now holds what position 4 held —
   * and a positional diff reports that as the row's TEXT changing.
   * Measured: graduating the 2nd of 6 records produced 8 "changed" lines
   * in which no row's text had changed at all, reading as "graduating a
   * record rewrote the other rows".
   *
   * So the digest keys off the nearest enclosing region that carries a
   * real id — this UI hands us `id="form-action-bar-lrn-96041a9b"` on
   * every row — and describes position only WITHIN that region. A row
   * keeps its name when its siblings vanish.
   */
  function anchorFor(el) {
    for (var n = el; n && n.nodeType === 1 && n !== document.body; n = n.parentElement) {
      if (n.id) return { node: n, id: n.id };
      var withId = n.querySelector("[id]");
      if (withId && withId.id) return { node: n, id: withId.id };
      // Repeating rows that carry NO id anywhere — the Front bucket table
      // is exactly this — get keyed by their own leading text instead of
      // by position. Front re-sorts itself after a resolution, so without
      // this every row reports as having had its text rewritten
      // ("git-hygiene" -> "home-assistant"), which is the same fabricated
      // finding as the positional case this anchoring exists to kill.
      if (n.tagName === "TR" || n.tagName === "LI") {
        var first = n.children.length ? n.children[0] : n;
        var lead = normId(first.textContent);
        if (lead) return { node: n, id: n.tagName.toLowerCase() + "[" + lead + "]" };
      }
    }
    return null;
  }

  function pathFrom(stop, el) {
    var parts = [];
    for (var n = el; n && n.nodeType === 1 && n !== stop && n !== document.body; n = n.parentElement) {
      var tag = n.tagName.toLowerCase();
      var p = n.parentElement;
      if (p) {
        var same = Array.prototype.filter.call(p.children, function (c) {
          return c.tagName === n.tagName;
        });
        if (same.length > 1) tag += ":" + (same.indexOf(n) + 1);
      }
      parts.unshift(tag);
    }
    return parts.join(">");
  }

  function digestKey(el) {
    var a = anchorFor(el);
    if (!a) return "body::" + pathFrom(document.body, el) + "|" + role(el);
    return a.id + "::" + pathFrom(a.node, el) + "|" + role(el);
  }

  /* Where this row SITS among its siblings.
   *
   * Keying rows by their content (above) makes a re-sort produce no diff
   * at all: every key and every value is unchanged, only the order moved,
   * and order was encoded nowhere. Measured on the Front bucket table —
   * clicking a sort header visibly reordered all five rows and the digest
   * reported zero changes. Position therefore belongs in the VALUE, where
   * a move reads as "this row went from 1 to 3" instead of vanishing or
   * (as it did before anchoring) masquerading as a text edit. */
  function rowIndex(el) {
    for (var n = el; n && n.nodeType === 1 && n !== document.body; n = n.parentElement) {
      if (n.tagName === "TR" || n.tagName === "LI" || (n.id && n.parentElement)) {
        var p = n.parentElement;
        if (!p) return "";
        return "#" + (Array.prototype.indexOf.call(p.children, n) + 1);
      }
    }
    return "";
  }

  function role(el) {
    var explicit = el.getAttribute("role");
    if (explicit) return explicit;
    var tag = el.tagName.toLowerCase();
    if (tag === "a") return el.hasAttribute("href") ? "link" : "generic";
    if (tag === "input") return "input:" + (el.type || "text");
    return tag;
  }

  // --------------------------------------------------- surface discovery

  var ACTABLE = [
    "button",
    "a[href]",
    "input",
    "select",
    "textarea",
    "summary",
    "[role=button]",
    "[role=link]",
    "[role=tab]",
    "[role=menuitem]",
    "[onclick]",
    "[hx-get]",
    "[hx-post]",
    "[hx-put]",
    "[hx-patch]",
    "[hx-delete]",
    "[data-key-action]",
  ].join(",");

  /* A key a human was TOLD about. Sources, in the order they matter:
   * an explicit shortcut attribute, and — the one that catches a key
   * whose handler was never wired — a "(x)" suffix printed in the
   * control's own visible label. */
  function advertisedKeys(el) {
    var keys = [];
    var ks = el.getAttribute("aria-keyshortcuts");
    if (ks) keys.push.apply(keys, ks.split(/\s+/));
    var ak = el.getAttribute("accesskey");
    if (ak) keys.push(ak);
    // Letters and ?// only — NOT digits. "near-misses (0)" is a count,
    // and reading it as a shortcut hint invents a surface that was never
    // advertised. Explicit accesskey/aria-keyshortcuts above still carry
    // digits, because there the author said so.
    var m = (el.textContent || "").match(/\(([A-Za-z?/])\)\s*$/);
    if (m) keys.push(m[1]);
    return keys;
  }

  function surfaces() {
    var seen = Object.create(null);
    var out = [];
    var nodes = [];

    Array.prototype.forEach.call(document.querySelectorAll(ACTABLE), function (el) {
      var r = el.getBoundingClientRect();
      var why = invisibleBecause(el);
      var lab = label(el);
      var keys = advertisedKeys(el);
      // Identity deliberately excludes record ids (normalised out of the
      // label) so the same control on row 2 collapses onto row 1 — the
      // walk covers surface KINDS, and a divergence between visits is
      // itself worth seeing.
      var id = [location.pathname, role(el), lab, keys.join("+")].join("|");
      if (seen[id]) {
        seen[id].count++;
        return;
      }
      var rec = {
        id: id,
        role: role(el),
        label: lab,
        selector: cssPath(el),
        count: 1,
        perceptible: why === null,
        disabled: el.disabled === true || el.getAttribute("aria-disabled") === "true",
        rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      };
      if (why) rec.hidden_because = why;
      if (keys.length) rec.keys = keys;
      if (el.hasAttribute("data-key-action"))
        rec.key_action = el.getAttribute("data-key-action");
      var href = el.getAttribute("href");
      if (href && href.indexOf("#") !== 0) rec.href = href;
      var verb = ["get", "post", "put", "patch", "delete"].find(function (v) {
        return el.hasAttribute("hx-" + v);
      });
      if (verb) rec.hx = verb + " " + el.getAttribute("hx-" + verb);
      seen[id] = rec;
      out.push(rec);
      nodes.push(el);
      return;
    });

    // A <form hx-post=...> wrapping its submit <button> is a real surface,
    // but clicking the FORM does nothing — the button is what a person
    // hits. Both enumerate; flag the wrapper so a walk can prefer the
    // leaf. (Found by clicking a form and observing a silent no-op.)
    nodes.forEach(function (el, i) {
      for (var j = 0; j < nodes.length; j++) {
        if (i !== j && el.contains(nodes[j])) {
          out[i].container = true;
          return;
        }
      }
    });

    // Keys printed anywhere on the page (help overlays, legends, <kbd>)
    // that no control above advertises — a key a human has been told
    // exists is a surface whether or not anything is bound to it.
    var bound = Object.create(null);
    out.forEach(function (s) {
      (s.keys || []).forEach(function (k) {
        bound[k] = true;
      });
    });
    var loose = [];
    Array.prototype.forEach.call(document.querySelectorAll("kbd,[data-key]"), function (el) {
      // MUST honour perceptibility. This was the one place in the file
      // that skipped it, in a file whose whole premise is that DOM
      // presence lies — and it lied here: Front listed 17 "advertised"
      // keys of which 12 are display:none, hidden by the footer's
      // data-context rules. A walk would press them, see nothing, and
      // file "advertised key does nothing" — a bug the harness invented.
      // An instrument whose only product is a truthful field report
      // cannot manufacture findings.
      if (!perceptible(el)) return;
      var k = (el.getAttribute("data-key") || el.textContent || "").trim();
      if (k && k.length <= 2 && !bound[k] && loose.indexOf(k) < 0) loose.push(k);
    });

    return {
      url: location.pathname + location.search,
      title: document.title,
      count: out.length,
      surfaces: out,
      unbound_keys_on_page: loose,
    };
  }

  // ---------------------------------------------------------- the digest

  /* One line per perceptible node that carries meaning: interactive, or
   * text-bearing. The VALUE encodes what a person would notice change. */
  function capture() {
    var map = Object.create(null);
    // dt/dd/pre were missing from the first version, which made two whole
    // surfaces invisible: the help overlay renders 19 shortcuts as dt/dd
    // and the digest reported none of them, and /report's entire
    // quantitative content — 23 metric name/value pairs — was absent
    // while chrome like "← Front" came through. Both measured.
    var nodes = document.querySelectorAll(
      "button,a,input,select,textarea,summary,[role]," +
        "h1,h2,h3,h4,p,li,td,th,dt,dd,pre,span,div,strong,em,code,label"
    );
    Array.prototype.forEach.call(nodes, function (el) {
      if (!perceptible(el)) return;
      // Only leaf-ish text: a wrapper repeats its children's text and
      // would make every diff cascade up the tree.
      var own = "";
      Array.prototype.forEach.call(el.childNodes, function (n) {
        if (n.nodeType === 3) own += n.nodeValue;
      });
      own = normValue(own);
      var interactive = el.matches(ACTABLE);

      var r = el.getBoundingClientRect();
      var cs = getComputedStyle(el);

      // A bordered/outlined/shadowed container counts even with no text of
      // its own and no interactivity. This UI marks the SELECTED list row
      // by putting an outline on a wrapper <div class="record-row selected">
      // whose text all lives in children — so the text-or-interactive test
      // alone skipped it, and pressing the move-down key reported zero
      // changes while the screen plainly showed the selection move.
      var chrome =
        cs.outlineStyle !== "none" ||
        cs.boxShadow !== "none" ||
        (cs.borderWidth !== "0px" && cs.borderStyle !== "none");
      if (!own && !interactive && !chrome) return;

      var key = digestKey(el);
      map[key] = [
        own,
        Math.round(r.width) + "x" + Math.round(r.height),
        "op" + effectiveOpacity(el).toFixed(2),
        el.disabled === true ? "disabled" : "",
        cs.color,
        cs.backgroundColor,
        // Border / outline / shadow: this UI signals SELECTION with a card
        // border, and sampling only text+background colour made list
        // navigation invisible — pressing the "move down" key reported zero
        // changes while the screen showed an unmistakable blue border move.
        // A walker trusting the digest alone would have written "this key
        // does nothing".
        cs.borderColor === "rgb(0, 0, 0)" && cs.borderWidth === "0px"
          ? ""
          : "bd:" + cs.borderWidth + " " + cs.borderColor,
        cs.outlineStyle === "none" ? "" : "ol:" + cs.outlineColor,
        cs.boxShadow === "none" ? "" : "sh:" + cs.boxShadow.slice(0, 40),
        rowIndex(el),
      ].join("~");
    });
    return map;
  }

  function readPrev() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function writePrev(run, map) {
    try {
      sessionStorage.setItem(
        STORE_KEY,
        JSON.stringify({ run: run || null, ts: Date.now(), map: map })
      );
    } catch (e) {
      /* quota or disabled storage — the next digest just reports baseline */
    }
  }

  /* Pass `run` — any string that changes when the SERVER's data changes
   * (the sandbox's bearer token does nicely). sessionStorage survives a
   * reseed on the same origin, so without this the first digest of a new
   * run diffs against a ledger that no longer exists: measured at 110
   * phantom changes attributable to nothing the agent did. The age guard
   * is the backstop for when the caller forgets. */
  function digest(opts) {
    opts = opts || {};
    var now = capture();
    var stored = opts.baseline ? null : readPrev();
    var reason = opts.baseline ? "explicit" : null;

    if (!reason && stored) {
      if (opts.run && stored.run && stored.run !== opts.run) reason = "new run";
      else if (stored.ts && Date.now() - stored.ts > STALE_MS) reason = "prior capture is stale";
    }
    if (!reason && !stored) reason = "no prior capture";

    var prev = reason ? null : stored.map;
    writePrev(opts.run || (stored && stored.run) || null, now);

    if (!prev) {
      return {
        baseline: true,
        reason: reason,
        url: location.pathname + location.search,
        nodes: Object.keys(now).length,
      };
    }

    var added = [];
    var removed = [];
    var changed = [];
    Object.keys(now).forEach(function (k) {
      if (!(k in prev)) added.push(k + " => " + now[k]);
      else if (prev[k] !== now[k])
        changed.push(k + "\n    - " + prev[k] + "\n    + " + now[k]);
    });
    Object.keys(prev).forEach(function (k) {
      if (!(k in now)) removed.push(k + " => " + prev[k]);
    });

    return {
      url: location.pathname + location.search,
      changed_count: added.length + removed.length + changed.length,
      added: added,
      removed: removed,
      changed: changed,
    };
  }

  window.__uiProbe = {
    surfaces: surfaces,
    digest: digest,
    // Explicit reset for the ambient-noise baseline: call, wait, call
    // again with no action in between; whatever comes back is the page
    // changing on its own (SSE pushes, relative timestamps) and has to
    // be subtracted before any click-caused diff can be trusted.
    baseline: function (run) {
      return digest({ baseline: true, run: run });
    },
    version: 2,
  };

  return window.__uiProbe.version;
})();
