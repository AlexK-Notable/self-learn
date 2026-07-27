# Spec — a key that does nothing should say why

Status: **DRAFT, ungated.** Split out of `ring-targeting-spec.md` at its
revision 7 (user ruling, 2026-07-26).

**§3 is the normative register**; §1–§2 are rationale. Every set is
defined once and referenced by name — the parent document's fifteen
blockers were, without exception, a ruling contradicting a criterion
enumerated somewhere else.

---

## 0. Why this is its own unit

This surface consumed **four consecutive spec-gate rounds** inside the
ring-targeting spec while the targeting fix — a ~20-line change — did not
move. The blockers were not repetitions; each was a different, measured
defect in the previous round's repair. That is the signature of a
separate unit wearing another unit's clothes.

The parent shipped with **a row-scoped miss being silent**, ruled
explicitly rather than defaulted. This spec's job is to decide whether
that silence is acceptable, and if not, to end it without repeating any
of the four failures below.

**The standing objection it answers:** W4-F4 — advertised-key-bound-to-
nothing has shipped four times in this UI (`c`, `h`, `v`, and `b`'s
half-dead variant). A silent miss has the same shape from the user's
seat: a key the UI advertises, pressed, producing nothing.

---

## 1. Four measured failures any design must survive

Carried forward from the parent's gate rounds. **Each killed a proposal
that looked correct in prose.**

### 1.1 `NOOP_MESSAGES` cannot express cause

`dispatchOrHint` (`app.js:270-281`) emits only for a
`[data-noop-hint][data-noop-action]` element — one render site,
`action_bar.html:196-202` — or a `NOOP_MESSAGES` entry, and
`NOOP_MESSAGES` (`app.js:266-268`) holds exactly one key,
`toggle_brief`.

It is keyed **by action alone**. One verb misses for at least three
distinct causes: the ringed row is an evidence leg; a proposal bar has
replaced the action bar; the verb does not apply to this row type. A
static string per action cannot be honest across all three.

Worse, adding entries **reverses a ratified pin** recorded verbatim in
the code (`app.js:259-264`): a proposal-replaced bar is *"deliberately
silent, no scope message (it would be wrong there, gate M1's replaced-bar
pin)"* — and turns
`test_o_on_proposal_replaced_bar_shows_no_hint`
(`test_js_dom.py:1528-1537`) red.

### 1.2 Server-rendered carriers change record detail pages

`evidence.html` is reached from three sites, two of which render
standalone on `/record/<id>`. A detail page has **zero** `[data-row]`, so
a document-wide hint lookup finds carriers rendered there. Measured
today: on a resolved detail page the row-scoped verbs are silent,
`noop_hint_elements: 0`.

Not fatal — silence becoming an honest explanation is the *good*
direction — but it must be **stated**, or an acceptance criterion
promising "detail pages behave exactly as before" is false.

### 1.3 "Already resolved" is a lie on the `defer` leg

`evidence.action` takes four values (`evidence.html:29` route, `:59`
graduate, `:63-65` defer, `:66` reject). **A deferred record is not
resolved** — it is snoozed and returns, which is precisely why
`_evidence_ctx` sets `record_url` only for `defer`.

Any wording asserting resolution breaks the project's Y-9 honesty pin,
recorded in that same template (`evidence.html:19-21`): "a stopping
session must never claim to be starting."

**Derivable at no cost:** `_EVIDENCE_VERBS` (`routes.py:1058`) is closed
over exactly those four and both `_evidence_ctx` call sites gate on it,
so a four-word map is total. The past-tense words already exist in
`evidence.html`'s own branches — factor once, or they drift.

### 1.4 An absence carries no cause — the root of all four

This is the diagnosis the parent's gate reached, and the thing this spec
exists to fix properly:

> The hint is required to **name a cause**. It is triggered by an
> **absence**. An absence has many causes and carries none of them, so
> every round patched the cause it could see and the next surfaced
> another.

The server-rendered carriers escaped this *by accident* — a carrier
exists only where the server already has a cause to state. Nobody wrote
that down as the principle, so `focusNote`, exempted from carriers,
inherited the bare absence-trigger and fired **where no record exists at
all**. Measured on the front page: no action bars, no evidence, and the
proposed literal would still have announced "this record has already been
acted on."

**The principle, stated once:** *speak only where the server has rendered
a reason; otherwise stay silent.* It subsumes 1.1, 1.2 and 1.3, and it is
testable as one invariant rather than an enumerable list of states that
keeps growing.

---

## 2. Open design questions — for the gate, not decided here

1. **Is silence actually wrong?** The parent ships it. A walk may find it
   acceptable. Deciding this from a walk is cheaper than deciding it from
   argument — see §4.
2. **Does `focusNote` share the mechanism or get its own?** It bypasses
   `dispatchOrHint` entirely and takes a client-side literal via
   `showNoopHint` (`app.js:293-303`), so it cannot interpolate what the
   server knows.
3. **Scope of the hint lookup.** `dispatchOrHint` resolves
   `[data-noop-hint]` document-wide (`app.js:272-274`). Today that is
   invisible — one render site, one string — but any per-row carrier makes
   an unscoped lookup able to source an explanation from **the wrong
   row**, which is the parent's own defect wearing a different hat.
4. **Where carriers may live.** If they go in `evidence.html`, they
   inherit a closed code-gate MAJOR's protection for free:
   `contradicts_offer.html` includes that partial **once**, because
   threading it per-edge rendered the success leg twice and violated
   `data-key-action` uniqueness. Putting them in `action_bar.html`
   silently re-opens it, and a one-edge offer looks identical.

---

## 3. Acceptance — to be written with the design

Placeholders are deliberate; this spec is not buildable yet and should
not pretend to be. What is already pinned:

- **The M1 replaced-bar pin survives.** `test_js_dom.py:1528-1537` stays
  green **unmodified**.
- **`NOOP_MESSAGES["toggle_brief"]` is not removed** —
  `test_js_dom.py:1539` asserts that exact string.
- **No wording asserts resolution on a `defer` leg** (§1.3).
- **No hint fires where no record is in scope** (§1.4).
- Any acceptance criterion naming detail-page behaviour must state the
  §1.2 exception explicitly rather than promising "exactly as before".

---

## 4. Recommended first step: measure, don't argue

The cheapest way to settle §2.1 is a walk, not a round of review. The
instrument now reports a control it could not before — probe `version: 4`
fixed the front-page selection blind spot — and a source-blind walker
driven keyboard-first will hit row-scoped misses naturally on an
evidence-leg row.

**If a walker does not notice the silence, this unit may not be worth
building.** If one files it as a defect unprompted, that is the
requirement, written by the user rather than by us — which is how W3-F1
and W4-F1 were both found.
