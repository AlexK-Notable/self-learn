# Spec A1 — honest scope-aware `claude-md` labels

Status: DRAFT — for blind Opus spec gate.
Rev: 2026-07-21 — **carved from `claude-md-parameterization-spec.md`**
(the parent Spec A, itself re-anchored to HEAD 97726df). This is **A1** of
the A1/A2 split recommended in that spec's Rev header: the scope-aware
label + always-show-path change that **alone closes F-1** (the user's
actual bug), fast and low-risk. A2 (the `rules`/`local`/glob machinery,
parent §2–§7/§9) is deliberately excluded — see §7 below. Nothing in A1
depends on A2.

Anchors are `file:line` against **HEAD 97726df**. All code anchors below
were re-verified against current source while writing this spec; the
parent spec's A1 claims matched current code with no drift (see §8).

Packages:
- UI — `plugins/self-learn/ui/src/self_learn_ui/` (Python) and
  `plugins/self-learn/ui/templates/` (Jinja templates — a **sibling** of
  `src/`, not under `src/self_learn_ui/`). Bare `templates/…` anchors below
  are relative to `plugins/self-learn/ui/templates/`.
- CLI — `plugins/self-learn/cli/src/self_learn/` (read-only here; the path
  authority only)

---

## 1. Problem (parent F-1) — one label covered three different files

`_GROUP_LABELS["claude-md"] = "Project instructions"`
(`plugins/self-learn/ui/src/self_learn_ui/models.py:182`) is **scope-blind**,
but the `claude-md` destination already resolves to **three distinct
files by scope** in the CLI router
`plugins/self-learn/cli/src/self_learn/verbs.py::_resolve_target`
(claude-md branch `verbs.py:575-603`):

| scope | resolved target | router anchor |
|---|---|---|
| `user` | `~/.claude/CLAUDE.md` | `verbs.py:576-584` (`DEFAULT_USER_CLAUDE_MD = Path("~/.claude/CLAUDE.md")`, `verbs.py:158`) |
| `project` | `<repo>/CLAUDE.md` | `verbs.py:585-590` (`host / "CLAUDE.md"`) |
| `skill` | `<skills root>/CLAUDE.md` | `verbs.py:591-603` (`root / "CLAUDE.md"`) |

A **user-scope** record — correctly headed for the global
`~/.claude/CLAUDE.md` — displayed as **"Project instructions"**. The
routing was never wrong; the gloss was. That mislabel made a working
user-scope destination look absent, and is the defect the user actually
saw.

**The fix (this spec).** Make the display **label** honest per scope, and
show the **resolved path** alongside it so the human sees the actual
file. Labels only — no CLI routing change, no `--dest` grammar change, no
schema change, no chezmoi interaction.

The UI scope tag is the **bare** token `"user"` / `"project"` / `"skill"`
(`ledger.py:225` sets `scope = "skill"`; `"user"`/`"project"` alongside),
the same keys `_SCOPE_DESTINATIONS` already uses (`models.py:95-99`). The
label resolver keys on these bare tags.

---

## 2. The label + path table (parent §8 rows 1–3)

Adopt the docs' own names. A1 covers the three **scope** rows only (no
`variant` — that is A2):

| scope | label | path shown alongside |
|---|---|---|
| `user` | **User instructions** | `~/.claude/CLAUDE.md` |
| `project` | **Project instructions** | `<repo>/CLAUDE.md` |
| `skill` | **Skills repo instructions** | `<skills root>/CLAUDE.md` |

Notes binding the strings:
- `user` label and path are **exact literals** (this is the F-1 case). The
  path string is exactly `~/.claude/CLAUDE.md`, matching
  `DEFAULT_USER_CLAUDE_MD` (`verbs.py:158`).
- `project` / `skill` paths are the **schematic tokens** `<repo>/CLAUDE.md`
  and `<skills root>/CLAUDE.md` — verbatim from parent §8, matching the
  router's `host / "CLAUDE.md"` (`verbs.py:587`) and `root / "CLAUDE.md"`
  (`verbs.py:600`). A1 threads **no** host path into the UI model; the
  schematic token names the file location unambiguously relative to the
  (already-shown) bucket scope, and the only case needing a literal path
  (`user`) is a compile-time constant. Substituting a concrete registered
  host path for `<repo>` is a permitted future nicety, **not** an A1
  obligation.
- The `project` label string is **unchanged** from today
  (`_GROUP_LABELS["claude-md"]`); only `user` and `skill` gain distinct
  labels. This keeps every existing project-scope render byte-identical.
- These three labels are the honest answer at **every** claude-md render —
  both the per-record surfaces (O-2 a–d) **and** the bucket group heading
  (O-2 e). Because a bucket page is one scope (§4), the heading resolves to
  exactly one of these three; the scope-blind `_GROUP_LABELS["claude-md"] =
  "Project instructions"` currently shown over a **user** or **skill**
  bucket is F-1 on the heading and contradicts this table (it binds
  "Project instructions" to project scope only), which O-2 e fixes.

---

## 3. Obligations

### O-1 — Widen the resolver (parent P-A11)

`destination_label` (`models.py:109-121`) is today a scope-blind lookup
`_GROUP_LABELS.get(value, value)`. Widen its **signature** to accept an
optional scope:

```
def destination_label(value: str | None, scope: str | None = None) -> str:
    if value is None:
        return ""
    if value == "claude-md" and scope in _CLAUDE_MD_SCOPE_LABELS:
        return _CLAUDE_MD_SCOPE_LABELS[scope]
    return _GROUP_LABELS.get(value, value)
```

- `_CLAUDE_MD_SCOPE_LABELS` is a small **scope-keyed** helper:
  `{"user": "User instructions", "project": "Project instructions",
  "skill": "Skills repo instructions"}`. It is keyed by **scope**, not by
  destination-enum value.
- `scope=None` (or an unrecognized scope) → today's behavior byte-for-byte
  (`_GROUP_LABELS.get(value, value)`). Any un-updated caller therefore
  degrades gracefully to the current gloss instead of crashing.
- For every destination value **other than** `claude-md`, the result is
  `_GROUP_LABELS.get(value, value)` exactly as today, at every scope.

**P-A11 invariant.** `_GROUP_LABELS` (`models.py:180-188`) **remains the
single destination-enum → label map** (`models.py:112-115` docstring: "no
second label map may exist"). The resolver's *signature* widens; the map
is **extended, never forked**. `_CLAUDE_MD_SCOPE_LABELS` is a
**scope-keyed** specialization for the one polymorphic destination — it is
**not** a second enum→label map (its keys are scopes, not
`skill-md`/`claude-md`/`reference`/`new-skill`/`hook`/`malformed`/`no-analysis`),
and it is the sanctioned "extension." A builder who adds a **second dict
keyed by destination-enum values** has broken this pin.

### O-2 — Thread scope into every label site

Five render sites gloss a `claude-md` destination and must pass the
governing scope through the widened resolver (O-1). Scope is confirmed in
hand at each:

| # | site | anchor | scope source |
|---|---|---|---|
| a | Detail "Suggested destination" | `templates/detail.html:122` (`model.why.destination \| destination_label`) | `model.scope` (`DetailModel.scope`, `models.py:1019`; already used at `detail.html:15`) |
| b | Detail "Alternates" | `templates/detail.html:124` (each `alt \| destination_label`) | `model.scope` |
| c | Action-bar "Destination" cycle button | `templates/partials/action_bar.html:184` (`dest \| destination_label`) | thread `scope=model.scope` into the `{% with %}` at the two include sites — `detail.html:168` and `bucket.html:88` — both of which carry `model.scope`. Do **not** rely on Jinja context leakage; pass it explicitly. |
| d | Pane proposal one-liner ("route to _<label>_") | `pane.py:611-620` (gloss at `pane.py:618`, `_GROUP_LABELS.get(dest_base, proposal.dest)`) | `proposal.bucket_scope` (`VerbProposal.bucket_scope`, `proposals.py:126`, set to `location.scope` at `proposals.py:390`) — switch this direct index to `destination_label(dest_base, proposal.bucket_scope)` so all label rendering routes through the one resolver |
| e | Bucket group heading (`<h2>`) | `models.py:911` (`DestinationGroup(label=_GROUP_LABELS[key])`), rendered at `bucket.html:63` | `scope` — already a `build_bucket_model` parameter (`models.py:848`). Change `_GROUP_LABELS[key]` → `destination_label(key, scope)`. See §4. |

Sites (a)/(b)/(c) call the resolver via the Jinja filter
`destination_label` (registered `app.py:51`); the filter's second
positional argument is the scope (`{{ x | destination_label(model.scope) }}`).
Sites (d)/(e) call the resolver directly in Python.

**One render legitimately stays raw.** The *genuinely armed* action-bar
branch (`action_bar.html:88-89`) emits the stored `dest` / `target`
**verbatim** — it never calls `destination_label` — so no F-1 mislabel
arises there and it is out of scope. Only the **unarmed** cycle-button
branch at `action_bar.html:184` glosses (site c).

### O-3 — Show the resolved path alongside the label (parent P-A12)

Alongside the record's **own** resolved `claude-md` destination, render the
resolved target path from §2. "Alongside every label" is bound to the two
**identity/decision** surfaces where the human commits to a file:

| surface | anchor | render |
|---|---|---|
| Detail "Suggested destination" | `detail.html:122` | when `model.why.destination == "claude-md"`, append the §2 path for `model.scope` (e.g. user → `User instructions — ~/.claude/CLAUDE.md`) |
| Action-bar "Destination" cycle button | `action_bar.html:184` | when the cycle-button `dest` base is `claude-md`, append the §2 path for the threaded scope |

**Where the path strings live (buildable pin).** The three path strings are
a **static scope-keyed map** — `{"user": "~/.claude/CLAUDE.md", "project":
"<repo>/CLAUDE.md", "skill": "<skills root>/CLAUDE.md"}` — exposed by a
`destination_path(scope)` resolver in `models.py`, alongside
`_CLAUDE_MD_SCOPE_LABELS`. It is keyed by **scope**, not by
destination-enum value, so it is **P-A11-safe** (it is not a second
enum→label map). The user value is string-equal to `DEFAULT_USER_CLAUDE_MD`
(`verbs.py:158`); the other two are the schematic tokens of §2.

**Bound (not gold-plating).** P-A12's "always" is scoped to the record's
**own selected** `claude-md` destination — not read literally as
"every label anywhere." The path is **not** appended to each *Alternate*
(`detail.html:124`) — alternates can be `reference`/`skill-md`, whose path
resolution is outside A1 — nor to the terse pane one-liner (`pane.py:618`);
those carry the scope-aware **label** only. P-A12's purpose ("the label
disambiguates the category; only the path disambiguates the file") is
served at the surfaces where the file is actually chosen.

---

## 4. The two label render paths — both become scope-aware

The `claude-md` label reaches the screen through **two** code paths, and
A1 must make **both** honest, or F-1 survives on one surface:

1. **The resolver** `destination_label` — the per-record sites O-2 a–d
   (Detail Suggested-destination, Alternates, the action-bar cycle button,
   the pane one-liner). Each glosses **one record's** destination with that
   record's scope in hand.
2. **The direct index** `_GROUP_LABELS[key]` at `models.py:911` — the
   bucket group heading (O-2 e), rendered `<h2>` at `bucket.html:63`,
   iterating `_GROUP_ORDER` (`models.py:892`).

**Why the group heading is single-scope, and why that makes it in scope.**
`build_bucket_model` takes **one** `scope` (`models.py:848`) — one bucket
page = one scope ("one page = one bucket", `models.py:816-821`;
`destination_cycle = destinations_for_scope(scope)`, `models.py:934`). An
individual `RecordRow` (`models.py:757-772`) carries no label field; the
label lives on `DestinationGroup` (`models.py:786-791`) over the N records
sharing a destination **enum** — but since the whole page is one scope,
that heading resolves to exactly **one** `(scope, destination)` pair. So
the scope-blind `_GROUP_LABELS["claude-md"] = "Project instructions"`
renders literally over **user** and **skill** buckets too — the exact F-1
symptom on the heading, and internally inconsistent with §2 (which binds
"Project instructions" to project scope only). It is not a harmless
category name; it is the same mislabel, just at the `<h2>`.

**The fix (O-2 e).** Change `models.py:911` `_GROUP_LABELS[key]` →
`destination_label(key, scope)`, reusing A1's own widened resolver (O-1),
with `scope` already a `build_bucket_model` parameter. Effect:
- `project` heading — **byte-identical** ("Project instructions").
- `user` heading — "User instructions"; `skill` heading — "Skills repo
  instructions".
- every non-`claude-md` group key (`skill-md` → "Skill doc", `reference` →
  "Reference file", `new-skill`, `hook`, `malformed`, `no-analysis`) —
  **unchanged** at every scope, because the resolver only specializes
  `claude-md` (O-1). Do **not** use a scope-neutral replacement string: it
  would change the project heading byte and contradict §2.

**Reconciliation for the blind reviewer.** Parent §8's "the label is no
longer a dict lookup on the destination key" describes the **resolver**.
After O-2 e both render paths (the per-record filter *and* the group index)
resolve the `claude-md` label through `destination_label`; the only
surviving `_GROUP_LABELS` lookup is the fallback **inside** that resolver
(O-1) — still the single source (P-A11).

`_group_key_for` (`models.py:824-830`) touches `_GROUP_LABELS` only for a
**membership check** (`if dest in _GROUP_LABELS`) — it selects the *group
key*, never renders a label — so it needs no change; O-2 e changes only the
`label=` argument at `models.py:911`.

---

## 5. Blast radius

A1 modifies **UI-package files only**:
- `models.py` — `destination_label` signature (O-1) + `_CLAUDE_MD_SCOPE_LABELS`
  helper + `destination_path(scope)` static path map (O-3) + the group-heading
  `label=` change at `models.py:911` (O-2 e).
- `templates/detail.html`, `templates/partials/action_bar.html`,
  `templates/bucket.html` (the O-2c include site only) — thread scope, add
  path.
- `pane.py` — `_proposal_clause` routes through the widened resolver with
  `bucket_scope`.

`verbs.py` is **read-only** in A1 — it is consulted solely as the
authority for which path each scope resolves to (§1/§2). No CLI verb,
`--dest` grammar, proposal schema, or chezmoi code changes.

---

## 6. Test obligations

The code gate will mutate/add tests to verify:

1. **Scope-aware label.** `destination_label("claude-md", "user") ==
   "User instructions"`; `("claude-md", "project") == "Project
   instructions"`; `("claude-md", "skill") == "Skills repo instructions"`.
2. **Fallback preserved.** `destination_label("claude-md")` and
   `destination_label("claude-md", None)` and any unknown scope →
   `"Project instructions"` (today's value, unchanged). Non-`claude-md`
   values (e.g. `reference`, `skill-md`) are unaffected by scope.
3. **Path alongside the label (P-A12).** The Detail "Suggested destination"
   line and the action-bar "Destination" cycle button for a `claude-md`
   record render the §2 path for the record's scope; a **user**-scope record
   renders exactly `~/.claude/CLAUDE.md` (string-equal to the router's
   `DEFAULT_USER_CLAUDE_MD`). The path is **not** rendered for alternates
   or the pane one-liner.
4. **Per-record sites are scope-aware end to end.** Rendering a
   user-scope `claude-md` record's Detail (O-2a), action bar (O-2c), and
   pane summary (O-2d) shows "User instructions" (not "Project
   instructions"); a skill-scope record shows "Skills repo instructions".
5. **Group heading is scope-aware (O-2 e).** A **user** bucket page's
   `claude-md` group `<h2>` reads "User instructions"; a **skill** bucket's
   reads "Skills repo instructions"; a **project** bucket's stays "Project
   instructions" (byte-identical). Assert at the `build_bucket_model` level
   (`DestinationGroup.label`) and at the rendered `<h2>` (`bucket.html:63`).
   Non-`claude-md` group headings are unchanged at every scope (existing
   `test_models_bucket.py` header assertions — "No analysis yet" at `:204`,
   the "unanalyzed" absence at `:234` — stay green; the implementer should
   confirm no existing test asserts a **claude-md** `group.label` at a
   non-project scope, which O-2 e would now change).
6. **No second label map (P-A11) — grep-level.** Exactly **one**
   module-level dict maps destination-enum values
   (`skill-md`/`claude-md`/`reference`/`new-skill`/`hook`/`malformed`/`no-analysis`)
   → labels, namely `_GROUP_LABELS`. The scope specialization
   (`_CLAUDE_MD_SCOPE_LABELS`) is keyed by scope, not by any
   destination-enum value, and so does not count as a second label map.
7. **Existing label assertions must be updated for the fixture's actual
   scope** (a naive "switch them all to project" reddens the suite — the
   shared fixtures are skill-scoped and one is parametrized across
   destinations):
   - `test_routes.py:1317-1336` and `:1338-1366` are **parametrized** tests
     sharing a **skill**-scoped fixture (`make_behavior(scope="skill:s")` →
     UI model scope `"skill"`). **Keep skill scope**; change only the
     **claude-md** row's expected label from `"Project instructions"` to
     `"Skills repo instructions"` (`:1321`, `:1342`). The `skill-md`,
     `reference`, `new-skill`, `hook` rows are unaffected (resolver
     specializes only `claude-md`). Switching the shared fixture to project
     scope would make the `skill-md` row — corrected to `claude-md` at
     project scope by `correct_destination` (`models.py:132-153`) — render
     "Project instructions" while asserting "Skill doc", reddening it.
   - `test_alternates_are_glossed_too` (`:1368-1377`, same skill fixture):
     O-2 b makes alternates scope-aware, so the `claude-md` alternate at
     skill scope renders `"Skills repo instructions"`; update `:1377`
     accordingly.
   - `test_pane.py:1608`: the `_route_proposal` helper (`:1349-1354`)
     **hardcodes `bucket_scope="skill"`** with no override, so the
     `dest="claude-md"` one-liner now glosses to `"Skills repo
     instructions"` — update the assertion to `"route to Skills repo
     instructions"`. An in-place project switch is impossible as written;
     to add user/project positives, give `_route_proposal` a `bucket_scope`
     parameter (or add a distinct helper).
   - **Add new positive cases** for the `user` and `project` scopes
     asserting `"User instructions"` / `"Project instructions"` at the
     Detail Suggested-destination, the action-bar cycle button, the group
     heading (O-2 e), and the pane one-liner.
   - The **single-source propagation** tests
     (`test_routes.py:1379-1396`, `test_pane.py:1449-1456`) survive
     unchanged — they monkeypatch the **`skill-md`** entry, which the
     `claude-md` scope-specialization does not touch.

---

## 7. Out of scope — all of A2

Everything below is the parent spec's A2 and is **explicitly excluded**
from A1. A1 is LABELS ONLY.

- The **`variant`** parameter on `claude-md` (parent §2/§4/§8 rows 4–6).
- **`rules:<topic>`** — user/project rules files, the `rules_topic` /
  `rules_paths` schema (parent §2.1/§4.2).
- **`local` / `CLAUDE.local.md`** and its gitignore guard (parent §2/P-A2/P-A3).
- **Glob validation** — route-time refusal, `--allow-empty-glob`,
  per-pattern checks (parent §5, P-A7).
- **Contradiction-domain re-scoping** to `(scope, always-loaded)` (parent
  §7, P-A10/P-A10b).
- **Caps** — per-topic-file cap and the >5-topics churn signal (parent §6,
  P-A8/P-A9).
- **`--dest` grammar change** — `claude-md:rules:<topic>`,
  `claude-md:local`, the `_DEST_RE` update, the four-site grammar sync
  (parent §4.1). A1 changes **no** grammar.
- **Skill-scope `rules` deferral** and the unguarded-`else` fallthrough at
  `verbs.py:600` (parent §9, P-A13). A1 does **not** touch `verbs.py`
  control flow; it only reads the existing resolution.
- **selfcheck glob-drift** re-assertion (parent §5.2).
- Any **schema migration** — none; and any **chezmoi** interaction — none.

---

## 8. Parent-spec fidelity check

Every A1 anchor the parent cited was re-verified against HEAD 97726df and
**matches** current code:
- `_GROUP_LABELS` at `models.py:180-188`, `claude-md → "Project
  instructions"` at `:182`; the "no second label map may exist" docstring
  at `:112-115` — all present as cited.
- Router claude-md branch `verbs.py:575-603` with `user`→`~/.claude/CLAUDE.md`
  (`:576-584`), `project`→`host/CLAUDE.md` (`:587`), skill fallthrough→
  `root/CLAUDE.md` (`:600`) — matches the parent's F-1 table.

No parent A1 claim was found to diverge from current code.

---

## 9. Definition of Done

- [ ] `destination_label` takes `(value, scope=None)`; `claude-md` resolves
      to the §2 label per scope via a **scope-keyed** helper; `scope=None`
      and every non-`claude-md` value return today's gloss unchanged (O-1).
- [ ] `_GROUP_LABELS` remains the **only** destination-enum→label dict; no
      second enum-keyed label map exists (P-A11; test 6).
- [ ] All five label sites (O-2 a–e) render the scope-aware label, with
      scope threaded from the named source at each (tests 4, 5).
- [ ] The Detail "Suggested destination" and the action-bar "Destination"
      cycle button for a `claude-md` record show the §2 resolved path;
      user scope shows exactly `~/.claude/CLAUDE.md` (O-3; test 3).
- [ ] The bucket group heading routes through `destination_label(key,
      scope)` (`models.py:911`): user → "User instructions", skill →
      "Skills repo instructions", project → "Project instructions"
      (byte-identical); non-`claude-md` headings unchanged (O-2 e; test 5).
- [ ] A user-scope `claude-md` record no longer displays "Project
      instructions" on **any** surface, including the bucket group heading
      (F-1 closed).
- [ ] Existing scope-blind label tests are re-pinned to a scope; the full
      UI test suite passes.
- [ ] No change to `verbs.py`, `--dest` grammar, proposal schema, or any
      chezmoi path (§5/§7).
