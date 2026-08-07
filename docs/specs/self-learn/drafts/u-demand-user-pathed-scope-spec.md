# Spec — U-demand-user: user scope's cheap surface is PATHED, and the menu says so

Status: **r3 — GATED SOUND, cleared for build.** Blind spec gate round 1
returned **1 BLOCKER, 5 FOLD, 7 NOTE** (all folded, §11); the delta gate
returned **NOT SOUND on four items** (all closed, §11) and cleared this unit
for build concurrently with `U-table`. The gate's rulings on r1's four open
questions are written in as decisions (§9). Under the 2026-07-26 verdict
repricing neither round cost a fresh spec round. Unit `U-demand-user` of the r2 routing campaign
(`forward/r2-routing-campaign.md` §2, Wave 2; sequenced after `U-pathed`,
which is **merged** — `63f5962`). Register rows **FW-40**, **FW-42**;
this round also takes ownership of **H5** from `U-table`'s §8 (§8A).
Normative parents: **S-23 (2)**, **S-22**, **S-25**, **S-21**, **S-26**
(`03-decisions.md`).

**Where prose and the acceptance criteria conflict, the criteria (§4 and
§8A.4) and the mutation plans (§5 and §8A.5) win.** The prose is rationale; the criteria are the
contract.

**Citations.** Every `file:line` below was re-read against this worktree at
**`83c1d5d`** and is written as *anchor first, line second*
(`verbs.py::_resolve_target`, currently `verbs.py:901`) — the campaign has
a ~208-instance stale-citation defect class, and an anchor survives drift
that a bare number does not. Two citations inherited from other documents
are **already stale on this tree** and are corrected in §10.

**Files this unit may touch.** The campaign row names `verbs.py` and
`ui/models.py` as *primary*. The full set, with the reason each is
unavoidable, is §3.6:

| File | Why |
|---|---|
| `cli/src/self_learn/verbs.py` | the `reference` refusal's message; the explicit-`--dest` rules-paths inheritance |
| `ui/src/self_learn_ui/models.py` | the destination menu, the armed default, the labels and the firing note |
| `ui/src/self_learn_ui/routes.py` | one new function + three changed, plus one kwarg threaded at **eleven** `_unarmed_context` call sites — the `o` cycle and every POST-rendered bar cannot see a per-record topic without them (§3.4, §3.6) |
| `ui/templates/bucket.html` | **one attribute** on line 90 (`model.destination_cycle` → `row.destination_cycle`) |
| `ui/templates/detail.html` | the `recommendation`/`flags` render (§8A) |
| `ui/templates/partials/action_bar.html` | two guards — the qualified-dest path span (`:268`) and the armed bar's raw dest (`:95`), §3.3(e) |
| `cli/tests/`, `ui/tests/` | the tests |

Anything else is out of scope and must be **reported, not edited** (§7.4).

---

## 1. What S-23 (2) requires, and the four things that block it

S-23 (2), ratified 2026-08-02: **user scope gets a cheap surface, and it is
pathed rules only** — explicitly NOT a user-level reference file. S-22 names
the user-scope destination singleton as one of its three worked examples of
a *funnel*: "a constraint that silently removes an option the agent should
have had."

Today the CLI can already route a user-scope pathed rule and `U-pathed`
already emits its `paths:` frontmatter — **but only from a bare
`route <id>` that reads the proposal sibling.** Every route the review
surface issues carries an explicit `--dest`
(`routes.py::build_argv`, currently `routes.py:131-140`; the docstring at
`:124-130` states this as a standing fact), and that path loses the tier.

### 1.1 Four measured findings

Probes run this session in a sandbox (`make_env` pair, `XDG_CACHE_HOME`
and the four `SELF_LEARN_*` vars redirected to a scratch tree, ledger
untouched), against `83c1d5d`. **These are measurements. A builder must
not re-derive them from reading; a reviewer should re-run them.**

**D1 — approving a pathed proposal in the review UI routes it to the
always-loaded file.** Seeded a user record whose proposal sibling carries
`destination: claude-md`, `variant: rules`, `rules_topic: py-conventions`,
`rules_paths: ["**/*.py"]`, then ran the exact argv the UI builds:

| Route | Rules file written? | `routing` block |
|---|---|---|
| `route <id>` (bare) | **yes** — `<user>/rules/py-conventions.md`, frontmatter `paths: ['**/*.py']` | `variant: rules`, `rules_topic`, `rules_paths`, `by: analyst` |
| `route <id> --dest claude-md` | **no** — entry landed in the plain `~/.claude/CLAUDE.md` | `destination: claude-md` only; **no variant, no topic, no paths** |

The second row is what the surface does today. Verified end-to-end on the
UI side in-process: for `list --json`'s item (`destination: "claude-md"` —
`ledger_ops::proposal_info` surfaces the **bare enum**, currently
`ledger_ops.py:1807`), `models.correct_destination("user", "claude-md")`
returns `('claude-md', None)`, the bar's hidden field
(`partials/action_bar.html:210`) carries `claude-md`, and
`build_argv` yields
`['route', '<id>', '--dest', 'claude-md', '--by', 'analyst']`.
**So S-23's primary cheap tier is unreachable through the review surface,
the demotion is silent, and the record then attributes the choice to
`by: analyst`** — whose actual choice was the pathed rule.

**D2 — a qualified `--dest` produces an unpathed "pathed" rule.**
`route <id> --dest claude-md:rules:py-conventions` on the same record
created the rules file but wrote **no `paths:` frontmatter**, and persisted
`variant` + `rules_topic` with **no `rules_paths`**. Cause:
`verbs.py::_resolve_destination`'s `--dest` branch (currently
`verbs.py:542-544`) returns `_Destination(destination, qualifier)` with
`variant`/`rules_topic`/`rules_paths` all left at their `None` defaults
(`verbs.py:530-534`); the topic survives only because
`_decode_claude_md_qualifier` (currently `verbs.py:687-702`) recovers it
from the qualifier string. There is no CLI flag for globs at all
(`cli.py` carries `--allow-empty-glob`, currently `cli.py:220-227`, and
nothing else). This is `U-pathed` §1's own defect — *"a pathed rules file
is an unpathed rules file"* — surviving on the `--dest` path, and it is
also the path the **Iterate pane** uses (`proposals.py`'s `_DEST_RE`,
currently `proposals.py:97-100`, admits `claude-md:rules:<topic>`).

**D3 — a qualified dest cannot survive a re-render.**
`models.correct_destination("user", "claude-md:rules:py-conventions")`
returns `(None, None)`, because the guard at `models.py:305` rejects
anything outside `PARAMETER_FREE_DESTINATIONS` (`models.py:93`).
`routes.py::_scope_corrected_dest` (currently `routes.py:1456-1465`) runs
that function on **every** unarmed re-render — disarm, a failed confirm,
`_pending_dest_override`'s Iterate restore — so a qualified value would be
blanked each time. This is the same defect class `f74c249` and `6519c58`
just closed for the plain case — **FW-68/FW-69**
(`14-forward-work-map.md:108-109`), both still open BUILD. (r1 cited "FW-64"
here; that row is the `routing.by` attribution fix, a different thing —
corrected per the gate's F7.)

**D4 — the cycle is a one-element tuple.**
`_SCOPE_DESTINATIONS["user"] == ("claude-md",)`
(`models.py:103-107`, the `"user"` row at `:106`), so
`cycle_destination` (`routes.py:235-248`) returns `claude-md` forever and
the bar renders the noop hint (`partials/action_bar.html:245-250`). FW-42.

### 1.2 A fifth finding, about the guard on the `reference` refusal

The campaign row's hard constraint is that
`verbs.py::_resolve_target`'s `destination == "reference"` branch keeps
refusing at user scope (currently the `else:` at `verbs.py:1045` and the
`raise VerbError` at `:1046-1050`).

**Measured: the suite can barely see that refusal.** A grep for its message
across `cli/tests/` returns nothing. A mutation — replacing the refusal
with code that resolves a user-level `references/` dir, i.e. building
exactly the file S-23 (2) rejects — was applied, the full CLI suite run
(`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged first), and **exactly
one test failed**:
`test_batch_fixes.py::TestNoPushBindsSpawnedWorker::test_teach_no_push_kicked_worker_does_not_publish`,
with `AssertionError: expected the pending fallback; got 0`
(`test_batch_fixes.py:416`). That test is about `--no-push` propagating to
a spawned worker; it uses the user-scope `reference` refusal only as
**incidental scaffolding** to make a route fail (its comment at
`test_batch_fixes.py:399-400` says so, and gives the dead chezmoi ground:
*"unroutable pair (doc 13 §2)"*). The mutation was reverted by inverse
Edit; `git diff --stat` is empty.

So: **the refusal has one incidental guard and zero intentional ones**, and
the one guard reports a failure that names nothing about `reference`,
nothing about user scope, and nothing about S-23. A future agent reading
FW-43 ("stale premises… the chezmoi ground") could delete the refusal as
dead chezmoi text, see one confusing unrelated failure, adjust that test,
and ship the user-level reference file S-23 rejected. This unit adds the
intentional guard (criterion **A9**).

---

## 2. The boundary with `U-pathed` — settled explicitly

`U-pathed` (merged, `63f5962`; spec `drafts/u-pathed-emission-spec.md`)
stated this boundary from its own side in its §7.5. **This section
restates it from this side, agrees with it, and adds the two things §7.5
did not know about** (D1 and D2 were not visible from `compilers.py`).

### 2.1 The line

| Owned by `U-pathed` (built, do not rebuild) | Owned by this unit |
|---|---|
| What a rules file **contains and is**: `paths:` frontmatter, the union register (its §2), comment/foreign-key ownership, the emitted YAML form | What a human can **pick**: the destination menu, the armed default, the labels/copy, and the refusals that bound the menu |
| `compilers.py`: `PathsResult`, `expected_paths`, `read_paths_frontmatter`, `paths_frontmatter_drift`, `apply_paths_frontmatter` | `ui/models.py`: `_SCOPE_DESTINATIONS` and everything derived from it |
| `verbs.py::_resolve_rules_target`'s **two route-time refusals** (absolute/`~` globs; chezmoi-MANAGED) — currently `verbs.py:826-836` and `:867-876` | `verbs.py::_resolve_target`'s `reference` **user-scope refusal** (currently `:1045-1050`) — message only |
| `verbs.py::_apply_target`'s pre-pass, the `changed` fold, the `notes` channel | `verbs.py::_resolve_destination`'s **input seam** — how `rules_paths` reaches a route at all |
| The drift **seam** (`paths_frontmatter_drift`); `selfcheck` wiring is its named handoff (§7.3) | Nothing in `selfcheck.py` or `compilers.py` |

**Nothing is built twice.** This unit adds no glob validation, no union
logic, no frontmatter reader or writer, and touches neither
`compilers.py` nor `selfcheck.py`. It calls `U-pathed`'s machinery by
routing through the *same* `_resolve_rules_target` every existing
user-scope rules route already uses.

### 2.2 What falls between, and who catches it

`U-pathed` §7.5 asserted **"there is no dependency from this unit to that
one"**, and cited two existing tests that route user-scope rules end to
end. **That assertion is correct; what it could not see is that the two
tests between them never cover the case the review surface actually
produces** — a `--dest` **and** a proposal carrying globs. Read on this
tree:

| Test | `--dest`? | Proposal? | Globs? |
|---|---|---|---|
| `test_a2_rules_local.py::TestObligation2And3ProjectGlobValidation::test_user_scope_glob_is_parse_only_never_zero_match` (`:279-299`) | **no** | yes | yes — but it asserts only that the file exists and holds the id, **never the frontmatter** |
| `…::TestObligation15FirstRouteBootstrap::test_user_leg_creates_dir_and_file` (`:732-745`) | **yes** (`claude-md:rules:subagents`) | **no** | no |
| `…::TestObligation16BareDestOneMotion` (`:764-795`) | yes | impossible (`route_direct`) | no — it **asserts** `"rules_paths" not in routed.routing` (`:783`) |

The cell that is empty in every row is **`--dest` + a proposal with
globs**. That is the review surface's only shape, and it is D2.

This is the seam, stated so the gate can check it:

> `U-pathed` guarantees that **if** a route arrives at
> `_resolve_rules_target` carrying `rules_paths`, the globs land on disk.
> **This unit owns getting them there**, for every entrypoint that is not
> a bare `route <id>`. A build that widens the menu without closing D2
> ships a menu entry whose execution silently under-delivers — the exact
> defect class the campaign exists to fix.

### 2.3 The one thing that must agree (`U-pathed` §7.5's own condition)

> *"`U-demand-user` must not introduce a second definition of the user
> rules path… any new menu entry must reach the file through
> `_resolve_rules_target`, never by constructing `~/.claude/rules/…` a
> second time."*

**Honoured, and made checkable.** This unit constructs no path at all. The
UI composes a *dest string* (`claude-md:rules:<topic>`), which the CLI
resolves through `_parse_dest` → `_decode_claude_md_qualifier` →
`_resolve_rules_target` → `_user_rules_dir` (currently `verbs.py:705-709`)
— the same chain a bare route takes. Criterion **A1** asserts this by
byte-comparing the two routes' output, which is a stronger check than
"no second literal exists". `models.py`'s `_RULES_SCOPE_PATHS["user"]`
(`models.py:163-166`) is display text only and already exists; this unit
adds no path template.

`U-pathed` §7.5 also flags a *pre-existing* second resolution —
`selfcheck.py::_target_for`'s hardcoded `DEFAULT_USER_CLAUDE_MD.expanduser()`
(currently `selfcheck.py:238`). This unit adds no third and does not
touch the second.

---

## 3. The change

### 3.1 `verbs.py` — the `reference` refusal keeps its effect and loses its dead reason

`_resolve_target`'s `destination == "reference"` branch (currently
`verbs.py:1038-1060`). The `else:` at `:1045` and its `raise VerbError` at
`:1046-1050` **stay, with the condition byte-identical.** Only the message
text changes. Today it reads:

```
reference destination needs skill:<name> or project scope — the user host
is the chezmoi-managed CLAUDE.md, it has no references dir (doc 13 §2)
```

Chezmoi was retired 2026-07-24; that ground is dead. The **effect** is
what S-23 (2) mandates. The replacement must carry three things and no
more:

1. the same scope condition, in plain words;
2. **S-23's own reason** — a user-level reference file inherits the
   unreachability problem with no `SKILL.md` to hang a pointer off, so it
   would be unreachable canon;
3. **the surface that replaced it — CONDITIONALLY, and this is F6, a
   cross-unit conflict the gate caught against `U-composer`'s D4.** r1 had
   this name a user rules topic (`--dest claude-md:rules:<topic>`)
   *unconditionally*. That is wrong, and dangerously so: this refusal fires
   exactly on **DEMAND-at-user-scope**, which is D4's no-cheap-surface case
   (*"never a silent upgrade to ALWAYS"*) — and an **unpathed** rules file
   still loads unconditionally (A2's own §4.4B text), i.e. ALWAYS-tier cost
   under a different filename. A lesson that is not file-scoped has no globs
   to offer, so steering it to a rules topic manufactures exactly the silent
   upgrade D4 forbids. **So item 3 is conditional:** name the pathed rules
   topic **when the lesson is file-scoped**; otherwise name **project scope,
   or defer** — never a bare "route it to a rules topic instead".

It must **not** say "chezmoi", and must not suggest the refusal is
temporary or a capability gap. Pinned wording is a builder decision (§6.1),
not fixed here; the criteria pin its properties (**A9**), not its bytes —
but the conditional structure of item 3 **is** pinned, because it is the
part that could re-create a defect in another unit.

`test_batch_fixes.py:399-400`'s comment (the incidental scaffolding of
§1.2) is updated in the same commit to cite S-23 rather than "doc 13 §2".
Its assertions do not change.

### 3.2 `verbs.py` — an explicit rules `--dest` inherits the proposal's globs

`_resolve_destination` (currently `verbs.py:537-558`). Today its two
branches are asymmetric: the proposal branch (`:545-558`) reads the
sibling and carries `variant`/`rules_topic`/`rules_paths`; the `--dest`
branch (`:542-544`) reads nothing.

**The change:** on the `--dest` branch, when the parsed dest is exactly
`("claude-md", "rules:<topic>")` **and** a schema-valid proposal sibling
exists naming exactly `destination: claude-md`, `variant: rules`,
`rules_topic: <topic>` — the same topic — carry that proposal's
`rules_paths` into the returned `_Destination`. In every other case
`rules_paths` stays `None`, unchanged from today.

**The predicate is deliberately narrow, and each clause earns its place:**

- **Same destination and same topic** ⇒ this is the human confirming the
  analyst's proposal, not composing a new one. The globs are part of *that*
  proposal, and the dest string has no slot for them.
- **A bare `--dest claude-md` never inherits**, even when the proposal is
  a rules proposal. That combination means "the human chose the
  always-loaded file", and reading globs into it would silently override
  a human's demotion — the FW-68/FW-69 defect class (silent loss of the
  human's own destination choice; partial fix `f74c249`) in the other
  direction. D1 is closed on the UI side (§3.3), not by widening this
  predicate.
- **A different topic never inherits.** A human who retypes a topic (via
  Iterate) gets an *honestly unpathed* rule, not the previous topic's
  globs aimed at a file they did not name.
- **No sibling, or an unreadable/schema-invalid one** ⇒ no inheritance,
  and no new failure mode: the route proceeds exactly as today. The
  sibling read must not raise where today's `--dest` branch cannot raise
  (criterion **A6**).

**This does not violate P-A5, and the gate must check that claim, not take
it.** The A2 spec (`drafts/a2-rules-local-spec.md`, gated and shipped)
carries **Pin P-A5** at `:316-318`:

> *"Globs do **not** ride in `--dest`. They contain `/`, `*`, `[`, `,`; a
> `:`-delimited value cannot carry them unambiguously. Globs live in the
> proposal YAML only (§4.3)."*

**Nothing here puts a glob in a dest string.** The globs still come from
the proposal YAML and nowhere else — P-A5's own §4.4B sentence,
*"`rules_paths` is a structured param that arrives ONLY from a proposal"*
(`a2-rules-local-spec.md:432-434`), is the rule this change implements on a
branch that was not implementing it. P-A5's stated **safety property** —
*"reaching a pathed rule requires a proposal a human read"* (`:322-323`) —
is preserved exactly: no proposal, or a proposal naming a different target,
means no globs.

**What IS in tension is P-A5's *consequence* paragraph** (`:320-326`) and
obligation 16 (`:976-981`), which state the outcome as
*"Bare `--dest claude-md:rules:<topic>` **with no proposal** yields an
unpathed rule"* and then contract it as *"bare `--dest
claude-md:rules:<topic>` resolves to the unpathed rules target"* — the
second sentence dropping the qualifier the first one carries. Under the
**qualified** reading this change is inside the pin; under the **literal**
reading it contradicts a gated contract. The existing tests do not settle
it: `TestObligation16BareDestOneMotion` (`test_a2_rules_local.py:764-795`)
exercises **`route_direct` only**, where no sibling can exist and §3.2 is
inert by construction (§7.3). **Routed to the gate as §9.1, with a
recommendation and the alternative that avoids the tension entirely.**
Criterion **A15** pins that obligation 16's own behaviour is untouched
either way.

**Considered and rejected — a `--rules-paths` CLI flag.** It would put glob
*authorship* on a keystroke surface — a direct P-A5 violation — and user
scope has **no dead-glob guard and structurally cannot have one** (S-25,
§7.1). A flag that mints unvalidated globs into the one tier with no
zero-match check is a worse trade than an inheritance rule that can only
ever restate globs a proposal already carried and a human already saw on
the card.

### 3.3 `ui/models.py` — the pathed tier becomes pickable and glosses honestly

**(a) The stale reason, again.** `_SCOPE_DESTINATIONS`'s docstring
(`models.py:95-102`) gives the same dead chezmoi ground for excluding
`reference` at user scope — *"the user host is the chezmoi-managed
CLAUDE.md, no references dir"* (`:98-99`). FW-48's row already flags this
site by name. Rewritten to cite S-23 (2), matching §3.1's CLI-side text.

**(b) `_SCOPE_DESTINATIONS["user"]` stays `("claude-md",)` — deliberately.**
This looks like it contradicts FW-42 ("the menu gains the pathed-rules
destination") and does not. The pathed tier is **not** a scope-constant
enum value: it is `claude-md` parameterized by a *topic*, which is
per-record (`ledger_ops::_validate_rules_fields`, currently
`ledger_ops.py:1312-1364`, requires a non-empty kebab `rules_topic`; and
R-2 — a rules variant is a scope parameterization of `claude-md`, never a
fifth destination — is pinned at `ledger_ops.py:1325-1329`). A topic cannot
be supplied by a keystroke, which is precisely why
`PARAMETER_FREE_DESTINATIONS` (`models.py:93`) exists and why
`new-skill`/`hook` are outside it. Keeping `_SCOPE_DESTINATIONS` as the
**one scope predicate** is also what `_budget_rows` (`models.py:1540-1569`)
and `destinations_for_scope` (`:283-288`) rely on; a second scope
definition is the thing `U-pathed` §7.5 warned against.

**(c) Three additions, all pure functions:**

```python
RULES_SCOPES: frozenset[str] = frozenset({"user", "project"})
def rules_dest(scope: str | None, rules_topic: str | None) -> str | None
def destination_cycle_for(scope: str, rules_topic: str | None) -> tuple[str, ...]
```

- `RULES_SCOPES` mirrors the CLI's own guard
  (`_resolve_rules_target`'s `if scope not in ("user", "project")`,
  currently `verbs.py:811-816`) — the UI must never offer what the verb
  refuses. It is a **second declaration of a CLI rule**, which this
  codebase tolerates only under a named agreement test (**A12**).
- `rules_dest` is the **one and only** place `f"claude-md:rules:{topic}"`
  is composed. `None` when the scope is outside `RULES_SCOPES` or the
  topic is falsy.
- `destination_cycle_for` = `destinations_for_scope(scope)` with
  `rules_dest(...)` **appended** when it is not `None`. Appended, not
  prepended: `cycle[0]` is both the cycle's fallback
  (`routes.py:245-246`) and `correct_destination`'s correction target
  (`models.py:309`), and this unit changes neither.

**(d) The armed default gets its own function, separate from the echo
re-validator.** This is the load-bearing design decision of the UI half.

`correct_destination` (`models.py:291-312`) is called from **two kinds of
site with opposite needs**:

- the *initial* armed default, once per page build
  (`build_bucket_model`, `models.py:1221`; `build_detail_model`, `:1627`),
  where the analyst's rules proposal **should** produce the qualified dest;
- the *echo re-validator*, `routes.py::_scope_corrected_dest`, run on
  every later render, where an upgrade would be a **silent override of the
  human's own choice** — a human who cycled to plain `claude-md` would be
  pushed back onto the pathed rule by the next disarm or failed confirm.

Folding both into one function with a `variant=` kwarg would make that
override structural. So:

- **`correct_destination` gains exactly one new leg**, before the
  `PARAMETER_FREE_DESTINATIONS` guard at `:305`: a `suggested` that is
  already a qualified rules dest passes through unchanged **iff** the
  scope is in `RULES_SCOPES`; otherwise it corrects to `cycle[0]` with a
  note, exactly like any other scope-invalid suggestion. It **never**
  upgrades a bare enum. Signature unchanged.
- **A new `proposed_destination(scope, item_destination, proposal)`**
  returns the `(dest, note)` pair the two model builders arm. It is
  `correct_destination` plus one leg: when `item_destination == "claude-md"`,
  the proposal names `variant: rules` with a non-empty `rules_topic`, and
  `rules_dest(...)` is not `None`, it returns that qualified dest with no
  note (the analyst's own choice needs no correction note — see
  `_pending_dest_override`'s reasoning at `routes.py:1489-1493` for the
  same distinction). Otherwise it delegates unchanged.

**(d′) The passthrough must check the TOPIC, not only the scope — F3.**
r1's passthrough leg checked `scope in RULES_SCOPES` and nothing else. That
is not enough, and the reason is structural: **today `models.py:305` blanks
everything outside `PARAMETER_FREE_DESTINATIONS`, so the echo surface cannot
carry a parameterized dest at all.** r1's change is what first makes it
possible — after which `_scope_corrected_dest` (`routes.py:1456-1465`) would
hand `claude-md:rules:anything` straight to the hidden field, contradicting
its own pinned posture at `:1459-1461` (*"never by trusting the echo — review
2026-07-18 F2"*). A hand-crafted POST could name a topic the record never
proposed, and the route would then create that topic file.

**The check belongs in `_scope_corrected_dest`, not in
`correct_destination`** — because the topic's ground truth is the record's
proposal, and `models.py` performs no I/O (§6.5). After correction: if the
value is qualified, require its topic `==
_record_rules_topic(request, record_id)`; otherwise fall back to `cycle[0]`.

**This does not touch the Iterate pane, and that is deliberate.** The pane's
confirm reads `prop.dest` from the slot and passes it straight to
`build_argv` (`routes.py:2631-2643`) without going through
`_scope_corrected_dest`, so a pane-proposed topic the analyst never named
still routes — which is correct: a pane proposal is an *agent's* deliberate
choice recorded in the slot, not a client echo of a rendered field. The two
surfaces have different trust stories and keep them.

**One precision about that path, since r1 overstated it (F13):** the pane
does **not** always send a dest. `routes.py:2631` branches on
`prop.dest is not None` — a bare pane route (the agent deferring to the
stored proposal) sends `dest=None` and is attributed `by: analyst`, exactly
like a bare CLI route. So §3.2's inheritance matters to the pane only on the
branch where the agent *does* name a qualified rules dest. The conclusion is
unchanged — that branch exists, `_DEST_RE` (`proposals.py:97-100`) admits
the form, and today it de-paths.

**Slug validation is not duplicated.** `models.py` decodes a qualified
dest with the existing `parse_variant_qualifier` (`models.py:234-254`) and
requires only a non-empty topic. The authoritative kebab check stays where
it already is — `_parse_dest`'s rules branch (`verbs.py:491-503`), whose
Y-9 wording names *"rules topic"*, and
`ledger_ops::_validate_rules_fields`. A malformed topic that reaches a
confirm takes the existing failed-confirm path and re-renders the bar with
the CLI's own message (criterion **A11**). Adding a fourth copy of the
slug rule — `proposals.py`'s `_DEST_RE` (`proposals.py:97-100`) is already
the third — would be a new drift surface for no gain.

**(e) The labels and the copy.**

- `destination_label` (`models.py:171-209`) learns to gloss a **qualified**
  value: decode via `parse_variant_qualifier`, then take the existing
  `variant == "rules"` leg (`:202-204`) → *"User rule — py-conventions"*.
  **The LABEL PIPE at `partials/action_bar.html:268` is unchanged** —
  that template already pipes the displayed dest through this one
  resolver, so a qualified value glosses correctly with no template edit,
  and `_GROUP_LABELS` remains the only enum-keyed label map (P-A11).
  **The PATH-SPAN GUARD on that same line is not unchanged** — F5 item 1
  below widens it. Naming both halves of `:268` separately matters,
  because r2 claimed the whole line was untouched one paragraph above the
  fix that changes it.
- `rules_firing_note` (`models.py:257-280`) gains **S-23's rider** at user
  scope. Today the pathed leg (`:275-277`) returns
  `"loads when you touch <globs>"`, which at user scope implies a repo it
  cannot mean. S-23 (2)'s measurement 2 is that a user-level glob resolves
  **relative to the session's working directory** and that absolute globs
  never match — so a user-scope pathed rule fires wherever a matching
  *relative* path exists, **in any project**. The user-scope wording must
  say that plainly and must **not invite repo-targeting**: no "in this
  repo", no path-prefix suggestion, no wording that implies the glob can
  be aimed. Project scope is unchanged.
- The globs stay rendered **verbatim** on the surface the human decides
  from (`detail.html:132` already does this through `rules_firing_note`).
  Under S-25 that is the *only* guard user scope has, so it is pinned by a
  criterion (**A10**) rather than left to survive by accident.

**Two commitment-surface sites r1 left rendering the NEW primary tier less
honestly than the tier it replaces — F5, and both are fixed here.** A
destination the human is about to commit to must name its file; that is
P-A12's own scope, and it currently holds for plain `claude-md` and would
have stopped holding for the tier this unit promotes.

1. **The resolved-path span disappears.** `partials/action_bar.html:268`
   guards the path span on `dest == "claude-md"`, which goes false for a
   qualified dest. **Fix:** widen the guard to "the dest is `claude-md` or a
   qualified `claude-md:…`", and feed `destination_path` the decoded
   `(variant, rules_topic)` — the function already accepts both
   (`models.py:212-231`) and `parse_variant_qualifier` already decodes
   (`:234-254`), so this is a guard and two arguments, no new machinery.
   Pinned by an **A4** rendered leg.
2. **The ARMED bar renders `armed.dest` RAW.** `partials/action_bar.html:95`
   prints `{{ armed.dest }}`, so the confirmation step — the last thing the
   human reads before Enter — would show
   `→ claude-md:rules:py-conventions` with no gloss and no firing note,
   while the unarmed bar one keystroke earlier showed *"User rule —
   py-conventions"*. **Decision: gloss it**, through the same
   `destination_label` this unit already teaches to decode qualified values
   (§3.3e). The armed bar deliberately shows raw values today (the F5-9 pin
   at `action_bar.html:265-267` says the armed branch "stays raw verbatim"),
   so this is a **narrow, stated exception** to that pin, taken because
   raw-vs-glossed is now a *tier* difference rather than a formatting one:
   the raw token is the only place a human could mistake the cheap tier for
   the expensive one at the moment of commitment. The firing note is **not**
   added to the armed bar — the Why region carries it two inches above
   (`detail.html:132`), and duplicating it at confirm time is noise.

   **This gloss is NOT buildable as r2 specified it, and the missing piece
   is mandatory (delta-gate D3).** `destination_label` needs a *scope*, and
   **the armed bar has none**: `_armed_context` (`routes.py:1290-1336`)
   returns exactly `kind`, `dom_id`, `evidence`, `armed`, `disarm_vals`,
   and `_base_ctx` (`:428`) adds none either. Glossing with `scope`
   undefined does not degrade to the raw token — it falls through
   `destination_label`'s scope legs to `_GROUP_LABELS["claude-md"]`
   (`models.py:341`) and renders **"Project instructions" on a USER-scope
   record**: a confidently wrong scope at the moment of commitment, which
   is strictly worse than the raw string it replaces.

   **Fully determined fix:** `action_arm` (`routes.py:1412`) computes
   `scope = _record_scope(request, record_id)` — the same ledger-truth
   lookup every unarmed site already uses — and `_armed_context` gains a
   `scope` key. Pinned by **A4**'s armed leg, which asserts the **exact**
   gloss string, and by **M29**.

**(f) The per-record cycle reaches the rows.** `RecordRow`
(`models.py:1012-1027`) gains a `destination_cycle` field;
`build_bucket_model` (`:1183-1289`) fills it per row via
`destination_cycle_for`, and `build_detail_model`'s
`destination_cycle=destinations_for_scope(scope)` (`:1639`) becomes the
per-record form. **`BucketModel.destination_cycle` (`:1143`) is DROPPED —
see §3.5A**, which states why (after §3.5 it has zero readers) and how its
two existing assertions are retargeted rather than deleted. r1 said it
"stays as the scope-level default"; that sentence survived the r2
reconstruction by mistake and contradicted §3.5A and §11.

**(g) `_budget_rows` is unchanged**, still iterating
`destinations_for_scope(scope)` (`models.py:1553`). Stated so its absence
is not read as an omission: the CLI emits `surface_fill` only for
`SURFACE_FILL_CAPPED_DESTINATIONS` (`verbs.py:196` — `skill-md` and
`claude-md`), and there is **no per-topic fill datum**. That phrasing is
precise on purpose (F11): the claude-md entry *does* carry a rules signal —
`rules_topic_count`, plus a `cap_reason: "rules-topics"` when more than five
topic files exist (`verbs.py:1562-1587`) — but it counts topic FILES, it does
not measure the fill of any one of them. F5's rule for that register is
*"the register lists only what it can state a fact about."* A per-topic
budget row would be a placeholder.

### 3.4 `ui/routes.py` — the cycle, the shared bar context, and the re-validator learn the topic

**r1 got this section's most important line wrong, and the gate caught it.**
r1 claimed `routes.py:1274` was "the degraded-Detail context" and left it on
`destinations_for_scope`. It is not. `:1274` sits inside
**`_unarmed_context`** (`routes.py:1207-1287`) — the shared context dict for
**every POST-rendered unarmed action bar**. The degraded surface never reads
it: `detail_degraded.html:59` sets its own `destination_cycle` in a
`{% with %}`.

**What that mislabel would have shipped.** GET renders the two-element cycle
(§3.3f). The human presses `o`. `action_cycle_destination` correctly returns
`dest=claude-md:rules:t` — re-rendered inside a bar whose
`destination_cycle` is the scope singleton `("claude-md",)`, so
`partials/action_bar.html:245-250` drops `data-key-action` and displays
*"only one destination fits this lesson's scope"*. The human is **stranded on
the pathed dest with the surface lying about why**, and the same happens on
disarm and on every failed confirm. That is precisely the "new funnel created
by this unit's own fix, which S-22 forbids" that §3.5 names for
`bucket.html` — one file over, and r1 missed it.

**PUSHBACK, verified: the gate named six call sites; there are eleven, and
all eleven thread `scope`.** Measured with
`grep -n -A9 "ctx = _unarmed_context(" routes.py`: `:1518` (`action_disarm`),
`:1561` (`action_cycle_destination`), `:1692`, `:1793`, `:2052`, `:2092`,
`:2134`, `:2182`, `:2247`, `:2482`, `:2721`. Ten pass
`scope=_record_scope(request, record_id)`; `:1561` passes a local `scope`
already derived from it. The gate's rule — *"every caller that threads scope
from `_record_scope` threads `_record_rules_topic` beside it"* — therefore
selects **all eleven**, not the six it listed. **The gate accepted the
enumeration and corrected my reasoning for it — r2's supporting sentence was
wrong about three of the five.** Of the five r1/r2 missed:

- **Two are correctness-critical:** `:1692` and `:2482` render an unarmed
  bar the human can still cycle, so leaving them on the singleton reproduces
  the blocker through a different door.
- **Three are no-ops by construction, not by luck.** `:1793` and `:2721` sit
  inside `if evidence is not None:`, and the cycle control lives in
  `action_bar.html`'s `{% if not evidence %}` branch (`:208-276`), so it is
  not rendered there at all. `:2247` is the post-**successful**-route retry
  in `commit_drift_confirm`, where the proposal sibling has already been
  deleted by the resolving route — so `_record_rules_topic` returns `None`
  by construction.

**So the correctness-critical set is eight** (`:1518`, `:1561`, `:1692`,
`:2052`, `:2092`, `:2134`, `:2182`, `:2482`) and three are inert. **The
instruction is unchanged: thread all eleven.** A uniform rule cannot drift;
a rule that says "thread the eight where it currently matters" becomes wrong
the first time an evidence guard moves or a retry path stops deleting the
sibling, and the inert three cost one `None` each.

| Function | Change |
|---|---|
| **new** `_record_rules_topic(request, record_id) -> str \| None` | sibling of `_record_scope` (`routes.py:1444-1453`), same "from the ledger, never a client field" posture: `ledger.locate_record` → `ledger.read_proposal_raw(bucket_dir, id)` (`ledger.py:321-332`) → the topic **iff** `destination == "claude-md"` and `variant == "rules"`; `None` on any miss, unreadable file, or unlocatable record |
| **`_unarmed_context`** (`:1207-1287`) | **the blocker fix.** Gains `rules_topic: str \| None = None`; `:1274` becomes `models.destination_cycle_for(scope, rules_topic)`. The default keeps an un-threaded caller on today's exact value, so the degradation direction is the existing conservative one its own comment (`:1270-1273`) already pins |
| `_scope_corrected_dest` (`:1456-1465`) | **changed** (F3): after correction, a qualified value is kept only when its topic equals `_record_rules_topic(request, record_id)`; otherwise it falls back to `cycle[0]`. See §3.3(d′) |
| `cycle_destination` (`:235-248`) | cycles over `models.destination_cycle_for(scope, rules_topic)`; gains `rules_topic: str \| None = None`, defaulted so every existing caller and test is unaffected |
| `action_cycle_destination` (`:1531-1570`) | supplies `rules_topic=_record_rules_topic(...)` beside the existing `scope = _record_scope(...)` at `:1559-1560`. `dest_touched=True` stays unconditional — the FW-64 rule, untouched |
| **`_armed_context`** (`:1290-1336`) | **D3.** Gains a `scope` key. It has none today, and F5 item 2's gloss is unbuildable without it — see §3.3(e) item 2 for what glossing with an undefined scope actually renders |
| **`action_arm`** (`:1412`) | **D3.** Computes `scope = _record_scope(request, record_id)` and passes it to `_armed_context` — the same ledger-truth lookup every unarmed site already performs |

Plus the mechanical kwarg at the **eleven** `_unarmed_context` call sites
listed above.

**The cost, named rather than discovered later.** `_record_rules_topic` does
its own `locate_record`, so a POST-rendered bar now performs two ledger
lookups where it performed one. Same order of cost as the existing one, on a
localhost single-user surface. **The builder may instead introduce a combined
`_record_bar_facts(request, record_id) -> (scope, rules_topic)` doing one
lookup** — that is a permitted simplification, not a required one; the
*contract* is that every `_unarmed_context` render receives the record's own
topic. Whichever shape is chosen, there must be exactly one ledger-truth
source for both facts, never a client field.

### 3.5 `ui/templates/bucket.html` — one attribute

Line 90 passes `destination_cycle=model.destination_cycle` (the
scope-level tuple) into the per-row action bar. It becomes
`row.destination_cycle`.

**This is not tidying.** Without it, a bucket row whose armed dest is the
qualified token renders against a one-element cycle, so
`partials/action_bar.html:245-250` drops `data-key-action` and shows
*"only one destination fits this lesson's scope"* — false, and the human
would be unable to change a destination the page is showing them. That is
a **new** funnel created by this unit's own fix, which S-22 forbids.
`detail.html:183` needs no change (it already passes
`model.destination_cycle`, whose value becomes per-record).

The noop hint's own text is **deliberately not changed**: it renders only
when the cycle is genuinely a singleton, which after this unit means
"user scope, no rules topic proposed" — where it is true. §7.2 records the
residual that sits behind it.

### 3.5A `BucketModel.destination_cycle` becomes dead — drop it (F10)

`models.py:1143` declares it and `:1286` fills it. After §3.5,
**`bucket.html:90` was its only reader** — verified by grep over
`ui/src` + `ui/templates`: `detail.html:183` reads `DetailModel`'s own field
(`models.py:1388`, which stays live and becomes per-record),
`detail_resolved.html:88` passes a literal `()`, and `detail_degraded.html:59`
calls `destinations_for_scope` directly. So the field would have **zero
readers**.

**Decision: drop the field**, rather than keep it with an "unused, retained"
note. This codebase has been bitten repeatedly by state that describes itself
as one thing while nothing reads it (FW-48's own lesson about comments that
enumerate their callers), and a field named `destination_cycle` on the bucket
model would assert it *is* the cycle when the cycle now lives on the row.

**Its two existing assertions are RETARGETED, not deleted** —
`test_models_bucket.py:187` and `:194` assert
`model.destination_cycle == ("skill-md","claude-md","reference")` and
`== ("claude-md",)`. Their intent — *the scope predicate reaches the bucket
surface* — is still live; it just moved. They become assertions on
`model.groups[i].rows[j].destination_cycle` for a record with no rules
proposal, preserving both expected values exactly. **This is not "editing a
test to make a build pass": the assertion's subject moved and the retarget
keeps the same expected values.** Deleting them would be.

### 3.6 Why the file set is seven and not two

The campaign row names two *primary* files. The five additions are each
forced, not chosen:

- **`routes.py`** (one new function, five changed, one kwarg at eleven
  call sites) — the `o` cycle's set is computed there (`:1560`) from `scope`
  alone, and the shared bar context at `:1274` likewise (the blocker, §3.4);
  the armed context needs a scope it does not have (D3, §3.3e item 2).
  A per-record topic cannot reach either without a ledger read in that
  module. Putting the read in `models.py` instead would mean a model
  function performing I/O, which nothing in that module does.
- **`bucket.html`** — one attribute, forced by §3.5.
- **`partials/action_bar.html`** — two guards, forced by F5 (§3.3e): without
  them the tier this unit promotes renders less honestly at the moment of
  commitment than the tier it replaces.
- **`detail.html`** — the `recommendation`/`flags` render, forced by the H5
  assignment (§8A).
- **the two test suites** — the campaign's own bar.

`compilers.py`, `selfcheck.py`, `ledger_ops.py`, `analyst.py`,
`proposals.py`, `pane.py` and `cli.py` are **not** touched. If a build
finds itself wanting any of them, stop and report it (§7.4).

---

## 4. Acceptance criteria

**These are the contract.** Each asserts against bytes on disk or a
rendered response, never against an intermediate the same change produced.
For every criterion, the line in *italics* answers the campaign's required
question: **what does this check report when its target is absent or
broken?** Where that answer would be "pass", the criterion already names
the pairing that fixes it.

---

**A1 — the two roads to a pathed user rule produce identical bytes.** The
headline criterion. Seed one user record with a rules proposal
(`variant: rules`, `rules_topic: t`, `rules_paths: ["**/*.py"]`) in each of
two independent sandboxes. Route sandbox 1 with `verbs.route(home, id)`
(bare) and sandbox 2 with
`verbs.route(home, id, dest="claude-md:rules:t", by="analyst")`. Assert:

- both `<user rules dir>/t.md` files exist and their **full text is equal**;
- the leading frontmatter, re-parsed with an independent
  `ruamel.yaml.YAML(typ="safe")` loader (the `read_frontmatter` helper at
  `test_a2_rules_local.py:140-150`), is `{"paths": ["**/*.py"]}` in both;
- both resolved records' `routing` blocks are equal on
  `variant`, `rules_topic`, `rules_paths`, and both carry `by: "analyst"`.

*Absent/broken:* today sandbox 2 writes a rules file with **no**
frontmatter and a `routing` block with no `rules_paths` (measured, D2), so
both the text equality and the frontmatter assertion fail with a concrete
diff. A build that emits nothing anywhere fails the frontmatter assertion
on sandbox 1 as well, so "no frontmatter" cannot pass.

**A2 — a bare `--dest claude-md` still routes to the always-loaded file,
even when the proposal is a rules proposal.** Same fixture; route with
`dest="claude-md"`. Assert the plain user `CLAUDE.md` carries the entry,
`<user rules dir>/t.md` does **not** exist, and the `routing` block has no
`variant`, no `rules_topic`, no `rules_paths`.

*Absent/broken:* **r1's answer here was wrong, and the correction is
measured (F2).** r1 claimed "any build that widened the predicate to any
claude-md dest would fail all three". Not so — it depends on *what* is
widened. Probed this round, both shapes, on the fixture above:

| Widening | rules file? | plain CLAUDE.md marker? | `routing` |
|---|---|---|---|
| carry **`rules_paths` only** on any claude-md dest | **no** | **yes** | no variant/topic/paths |
| adopt **`variant`+`rules_topic`+`rules_paths` wholesale** | yes | no | all three present |

The first row is byte-identical to A2's asserted *correct* behaviour, so A2
stays green against it — because §3.2 carries `rules_paths` alone, and with
`variant`/`ref_name` still `None` the claude-md branch never reaches
`_resolve_rules_target` at all (`verbs.py:947-991`): the globs are silently
dropped. **A2's real owner is the second shape**, which fails all three
assertions. The first shape's owner is **A3**, whose `paths:` assertion
catches it. §5's M2 is worded to the second shape for exactly this reason.

**A3 — a mismatched topic does not inherit.** Proposal names topic `t`
with globs; route with `dest="claude-md:rules:other"`. Assert
`<user rules dir>/other.md` exists, carries **no** `paths:` key, and the
`routing` block has `rules_topic: other` and no `rules_paths`.

*Absent/broken:* an implementation that inherits on `destination` alone
aims one lesson's globs at a file the human named instead — this fails on
the `paths:` assertion. Without A3, that build passes A1 and A2.

**A4 — the UI arms the qualified dest for a rules proposal, and the plain
one otherwise.** Against `build_detail_model` **and** `build_bucket_model`
(both, because they are separate call sites — `models.py:1627` and
`:1221`), with a `list --json`-shaped item carrying the **bare** enum
`destination: "claude-md"` (what `proposal_info` actually emits,
`ledger_ops.py:1807`):

- proposal with `variant: rules`, `rules_topic: py-conventions` →
  `destination_default == "claude-md:rules:py-conventions"`,
  `destination_note is None`;
- **same item, proposal with no variant** → `destination_default ==
  "claude-md"` (the byte-identical pre-existing behaviour).

**And on the rendered page, not only the model** — a GET of the bucket page
for that record's bucket:

- the row's action bar carries `data-key-action="cycle_destination"` (a
  two-element cycle), **not** the `data-noop-hint` singleton form;
- the displayed destination text is the rules gloss
  (*"User rule — py-conventions"*), **not** the raw
  `claude-md:rules:py-conventions` token;
- the hidden `dest` input carries the qualified token verbatim;
- **(F5)** the resolved-path span renders and reads
  `~/.claude/rules/py-conventions.md` — **not** the plain
  `~/.claude/CLAUDE.md`, and not absent. Positive control in the same
  assertion: a plain-`claude-md` row still renders `~/.claude/CLAUDE.md`, so
  "the span is there" cannot pass on a build that shows the wrong file;
- **(F5 + D3)** after arming that row, the ARMED bar's destination text is
  **exactly** `User rule — py-conventions`. **Assert the exact string, not
  "not the raw token".** The trap this criterion exists to catch is
  `Project instructions` — what an un-scoped `_armed_context` renders for a
  user-scope record (§3.3e item 2), which a loose "the raw token is absent"
  assertion passes while the surface names the wrong tier and the wrong
  scope. Positive control in the same assertion: the same armed bar for a
  **project**-scope pathed record reads `Project rule — py-conventions`, so
  a build that hardcodes the user string fails.

*Absent/broken:* the second model leg is the positive control — without it
a build that qualifies **every** claude-md dest (turning every plain user
lesson into a rules route to a nonexistent topic) passes the first leg
alone. The three rendered legs exist because a model-only assertion cannot
see the template: they are the owners of M16 (the label decode), M18 (the
row-level cycle) and M19 (`bucket.html`'s attribute), each of which a
model-only A4 would let survive, plus M22/M23 (the two F5 guards). Today
every rendered leg fails — the row's cycle is the scope singleton and the
armed dest is bare `claude-md`.

**A5 — a qualified dest survives every re-render, and a plain one is not
upgraded.** Through the HTTP surface, on a record whose proposal is a rules
proposal:

- POST the disarm route with `dest=claude-md:rules:t`; the re-rendered
  bar's hidden `dest` input still carries `claude-md:rules:t`;
- POST the same route with `dest=claude-md`; the re-rendered bar carries
  **`claude-md`**, not the qualified form;
- **(F3) leg 3 — a FOREIGN topic is rejected.** POST with
  `dest=claude-md:rules:not-the-proposed-topic` on that same record; the
  re-rendered bar carries **`claude-md`** (the scope's `cycle[0]`), never the
  echoed topic. Positive control in the same test: the record's *own* topic
  still passes through (leg 1).

*Absent/broken:* leg 1 fails today — `correct_destination` returns `None`
for a qualified value (measured, D3) and the field renders empty. Leg 2 is
the anti-override control: a build that folded the upgrade into
`correct_destination` (the design §3.3d rejects) passes leg 1 and fails
leg 2, silently overriding a human's own demotion. Leg 3 owns M21: without
the topic check the echoed value passes straight through, and the route then
creates a topic file the record never proposed — the exact "never by trusting
the echo" posture `_scope_corrected_dest`'s own docstring pins at
`routes.py:1459-1461`.

**A6 — the inheritance never introduces a new failure.** `route` with
`dest="claude-md:rules:t"` succeeds when (a) there is **no** proposal
sibling, (b) the sibling is unparseable YAML, and (c) the sibling is
schema-invalid. In all three the rules file is created unpathed and the
record resolves.

*Absent/broken:* a naive `read_proposal(...)`/`validate_proposal(...)` in
`_resolve_destination` raises `ProposalError`/`NoProposalError` on legs
(a)–(c), turning three working routes into refusals. Today all three
succeed, so this criterion is red the moment the read is unguarded.

**A7 — the cycle reaches the pathed option and comes back.** With a rules
proposal at user scope, `destination_cycle_for("user", "t")` is
`("claude-md", "claude-md:rules:t")`, and repeated
`cycle_destination(current, "user", "t")` walks
`claude-md → claude-md:rules:t → claude-md`. **And in the same test**,
`destination_cycle_for("user", None)` is `("claude-md",)` — unchanged.

**And through the HTTP surface** — POST
`/record/<id>/action/cycle-destination` with `dest=claude-md` on a record
whose proposal names topic `t`: the re-rendered bar's hidden `dest` input
carries `claude-md:rules:t`, and `dest_touched` is now set.

**And the POST-FRAGMENT leg — this is the blocker's criterion (F1).** That
same response's cycle control carries
`data-key-action="cycle_destination"` and carries **no** `data-noop-hint`,
i.e. the re-rendered bar itself offers a live two-element cycle. **Positive
control in the same test:** the identical POST on a user record with **no**
rules proposal renders the singleton form — `data-noop-hint` present,
`data-key-action` absent. **And the same two-legged assertion is made against
`action_disarm`'s response**, which is a different `_unarmed_context` caller;
without a second caller the test pins one call site rather than the shared
context.

*Why this leg and not a wider sweep:* eleven callers reach
`_unarmed_context` (§3.4). Asserting all eleven would pin the caller list —
the enumeration-drift shape `routes.py:1232-1236`'s own comment warns about.
Two callers plus the default-argument rule in §3.4 is the honest coverage:
it proves the shared context carries the topic, and the default proves an
un-threaded caller degrades rather than crashes.

*Absent/broken:* a build that appends unconditionally produces
`("claude-md", None)` or a malformed token and fails the second leg; a
build that never appends fails the first. Without the second leg,
"the cycle grew" passes on a build that grew it for every record. The HTTP
leg is the **owner of M17** — `_record_rules_topic` returning `None`
unconditionally is invisible to the two function-level legs, because they
pass the topic in directly. Today the HTTP leg returns `claude-md` (a
singleton cycle rotating onto itself), so it can fail. The POST-fragment leg
is the **owner of M20**, the gate's invented mutation, which **survived r1's
entire criterion set**: r1 asserted only the hidden `dest` and
`dest_touched` on this response, and A4's `data-key-action` legs were
GET-only, so nothing looked at the re-rendered fragment's own cycle.

**A8 — the cycle is offered at project scope too, without disturbing its
order.** `destination_cycle_for("project", "t")` is
`("claude-md", "reference", "claude-md:rules:t")` — `cycle[0]` and the
existing order unchanged. `destination_cycle_for("skill", "t")` is
`PARAMETER_FREE_DESTINATIONS`, **unchanged** (skill scope is the P-A13
rules deferral, `verbs.py:811-816`).

*Absent/broken:* a build that prepends changes `cycle[0]`, which silently
changes what `correct_destination` corrects a scope-invalid suggestion to
— this fails on tuple equality. A build that ignores `RULES_SCOPES` offers
the CLI-refused skill-scope rules dest and fails the third leg.

**A9 — the `reference` refusal still fires at user scope, and says why.**
`verbs.route(home, <user record>, dest="reference")` raises `VerbError`;
the record stays in `pending/`; **no** `references/` directory is created
anywhere under the user target's parent. The message mentions **S-23** and
does **not** contain the substring `chezmoi`. **In the same test**, a
`skill:<name>`-scope and a project-scope `reference` route both still
succeed and write their files.

*Absent/broken:* today NO test asserts this refusal (measured, §1.2), so
deleting it costs one confusing failure in an unrelated `--no-push` test.
The positive control (the two scopes that must still work) is what stops
this criterion being satisfied by a build that refuses `reference`
everywhere.

**A10 — the user-scope firing note states the cwd-relative truth and
invites no repo-targeting.** `rules_firing_note("rules", "user",
("**/*.py",))` contains the glob **verbatim**, and states that it matches
relative to wherever the session is running / in any project.
`rules_firing_note("rules", "project", ("src/**",))` is **unchanged from
today's string**. And the rendered Detail page for a user-scope pathed
proposal contains the glob text.

*Absent/broken:* the project-scope leg is the no-regression control; the
rendered-page leg is what makes the note a *surface* fact rather than a
function fact. A build that changes the note but never renders it passes a
function-only assertion. **The reviewer should also read the shipped string
directly** — no assertion can prove copy does not invite repo-targeting;
that is a human read, and it is named here so the gate performs it.

**A11 — a malformed topic refuses at the verb, not silently.**
`verbs.route(..., dest="claude-md:rules:Not_A_Slug")` raises `VerbError`
whose message names *"rules topic"* (the Y-9 wording at `verbs.py:499-503`),
and the record stays pending.

*Absent/broken:* this is the criterion that makes §3.3's
"no fourth copy of the slug rule" honest. If a build adds slug validation
in `models.py` and the CLI's own check regressed, this still catches it.

**A12 — `RULES_SCOPES` agrees with the CLI.** A test asserts
`models.RULES_SCOPES == frozenset({"user", "project"})` **and** carries a
comment naming `verbs.py::_resolve_rules_target`'s guard as its source of
truth, so a future widening of that guard has a place to fail.

*Absent/broken:* an equality-to-a-literal test cannot detect CLI drift on
its own — stated plainly rather than dressed up. What it does provide is a
named tripwire the CLI-side change will collide with. The alternative
(importing the CLI package into the UI package) is rejected: the UI reaches
the CLI by subprocess, not import, and inverting that for one constant
would be a new coupling.

**A13 — `by` attribution survives.** Untouched approve of a rules proposal
→ argv contains `--by analyst` and the resolved record's
`routing.by == "analyst"`. A cycled destination → `--by human` and
`routing.by == "human"`.

*Absent/broken:* FW-64 shipped `4f8817a` and `6519c58` days ago; a
regression here would be invisible to every other criterion. Both legs are
required — asserting only "analyst" passes on a build that hardcodes it.

**A14 — non-rules routes are byte-identical.** Routing to plain user
`CLAUDE.md`, project `CLAUDE.md`, `SKILL.md`, `CLAUDE.local.md`,
`reference` (skill scope) and a `new-skill` target produces the same bytes
and the same `routing` blocks as before this unit. **Positive control in
the same test:** one rules route in the same fixture *does* produce a
pathed file, so "nothing changed anywhere" cannot pass.

*Absent/broken:* without the control, a build whose `_resolve_destination`
change accidentally short-circuits every route passes A14 trivially.

**A15 — P-A5's one-motion contract is untouched.** The two existing tests
in `TestObligation16BareDestOneMotion` (`test_a2_rules_local.py:764-795`)
still pass **unmodified**: `route_direct` with
`dest="claude-md:rules:subagents"` still yields an **unpathed** rules file
at both scopes, still leaves the plain `CLAUDE.md` markerless, and
`:783`'s `assert "rules_paths" not in routed.routing` still holds.

*Absent/broken:* this criterion has **no mutation of its own**, and that is
stated rather than papered over. `route_direct` composes a record that is
not yet on disk, so no proposal sibling can exist and §3.2's inheritance is
unreachable there **by construction** — there is no one-line edit to §3.2
that reaches it. It is a **regression guard on a gated contract**, and the
build that reddens it is one that gives `route_direct` globs from some
*other* source — a default, or the one-shot analyst's own dict (§7.3's
named handoff, which is `U-composer`'s and must not be done here). A
builder must not edit these two tests to make a build pass; if they go red,
the change reached a seam this unit does not own.

---

## 5. Mutation plan

A blind reviewer will run these. **Before any sweep:**
`export PYTHONDONTWRITEBYTECODE=1` and
`find . -name __pycache__ -type d -prune -exec rm -rf {} +` (campaign §3,
FW-61). Revert by **inverse Edit, never `git checkout`**.

Each row's named criterion is its **owner** — the assertion written to
catch that defect. Several are deliberately wide; **what must hold is that
the owner fails.** A mutation whose owner stays green is a real finding.
Reviewers are invited to invent mutations not listed here.

| # | One-line edit to production code | Test that must fail |
|---|---|---|
| M1 | `_resolve_destination`: delete the `rules_paths` inheritance, returning `_Destination(destination, qualifier)` as today | **A1** — owner; the "validated but never written" control for this unit |
| M2 | `_resolve_destination`: on **any** claude-md dest, adopt the proposal's `variant` + `rules_topic` + `rules_paths` **wholesale**, ignoring the parsed qualifier | **A2** — owner (measured: this shape reddens all three of A2's assertions; the narrower "carry `rules_paths` only" shape leaves A2 green and is owned by A3 instead — §4 A2) |
| M3 | `_resolve_destination`: inherit when the topics differ (drop the topic comparison) | **A3** |
| M4 | `_resolve_destination`: read the sibling without guarding a missing/invalid one | **A6** |
| M5 | `_resolve_target`: delete the user-scope `reference` `raise`, falling through to a resolved user `references/` dir | **A9** |
| M6 | `_resolve_target`: keep the refusal, restore the word `chezmoi` in its message | **A9** (the substring leg) |
| M7 | `proposed_destination`: return `correct_destination(...)` unconditionally (never qualify) | **A4** (leg 1) |
| M8 | `proposed_destination`: qualify **every** `claude-md` dest, ignoring the proposal's variant | **A4** (leg 2) |
| M9 | `correct_destination`: drop the qualified-passthrough leg | **A5** (leg 1) |
| M10 | `correct_destination`: add the upgrade leg — qualify a bare `claude-md` echo when the record has a rules proposal | **A5** (leg 2) — the design §3.3d exists to prevent |
| M11 | `destination_cycle_for`: append `rules_dest` unconditionally (ignore `rules_topic is None`) | **A7** (leg 2) |
| M12 | `destination_cycle_for`: prepend instead of append | **A8** |
| M13 | `rules_dest`: drop the `RULES_SCOPES` check | **A8** (the skill-scope leg) |
| M14 | `rules_firing_note`: return today's project wording at user scope | **A10** |
| M15 | `rules_firing_note`: drop the globs from the string (keep the prose) | **A10** (the verbatim-glob leg) |
| M16 | `destination_label`: drop the qualified-value decode | **A4**, rendered leg 2 (the displayed label is the raw token) |
| M17 | `_record_rules_topic`: `return None` unconditionally | **A7**, the HTTP leg |
| M18 | `build_bucket_model`: fill `RecordRow.destination_cycle` from `destinations_for_scope` instead of `destination_cycle_for` | **A4**, rendered leg 1 (the row falls back to the noop-hint form) |
| M19 | `bucket.html:90`: restore `model.destination_cycle` | **A4**, rendered leg 1 — same symptom, different cause |
| M20 | `_unarmed_context` (`routes.py:1274`): keep `models.destinations_for_scope(scope)` | **A7**, POST-fragment leg — *the gate's invented mutation, which survived r1 entirely* |
| M21 | `_scope_corrected_dest`: drop the topic check, keeping only the scope check | **A5** leg 3 |
| M22 | `action_bar.html:268`: restore the bare `dest == "claude-md"` guard on the path span | **A4**, rendered leg (F5 path) |
| M23 | `action_bar.html:95`: restore the raw `{{ armed.dest }}` | **A4**, rendered leg (F5 armed) |
| M29 | `_armed_context`: drop the `scope` key (leaving the gloss to resolve against an undefined scope) | **A4**, armed leg — renders `Project instructions` for a user record, which only the exact-string assertion catches |

**M18 and M19 map to the same assertion by design** — the row-level cycle
can be broken at either end of the model→template hand-off, so the
assertion has an owner at each. A builder splitting them into two tests
must update this table in the same commit.

**If any mutation's owner stays green, that is a coverage gap to close, not
a mutation to withdraw** — add the missing assertion and record it here.

**Five criteria have no row, and r1 implied only one did — F8.**
**A11, A12, A13, A14 and A15** carry no mutation, and each for a different
and stateable reason. r1 singled out A15, which read as though the other four
were covered.

| Criterion | Why no mutation, honestly |
|---|---|
| **A11** (malformed topic refuses) | **The weak one. It passes today, and no one-line edit to THIS unit's code can redden it** — the refusal lives in `_parse_dest` (`verbs.py:491-503`), which this unit does not touch. It is a pure regression guard: it exists so that if a build "helpfully" adds slug handling in `models.py` and the CLI check later regresses, something notices. Do not mistake it for coverage of this unit. |
| **A12** (`RULES_SCOPES` agrees with the CLI) | An equality-to-a-literal tripwire; §4 A12 already says an equality test cannot detect CLI drift on its own. |
| **A13** (`by` attribution) | Guards code this unit does not change (`routes.py:1651`, `:2161`). A mutation would be a mutation of FW-64's shipped work, not of this unit's. |
| **A14** (non-rules byte-identity) | Its owners are the *other* mutations: any of M1–M4 that over-reaches shows up here first. It is a blast-radius net, not a guarded behaviour. |
| **A15** (P-A5's one-motion contract) | Unreachable by construction — §4 A15. |

The reviewer's check for these five is that their tests are green **and
unedited** in the diff. A fabricated mutation row for any of them would be
the theatre this campaign keeps catching.

**One mutation that must NOT be proposed** because it passes by design:
adding a `--rules-paths` flag to `cli.py` and threading it. It is inert
under this design and §3.2 rejects it on P-A5 and S-25 grounds.

**Five further mutations live in §8A.5** (M24-M28), covering the H5
assignment. They are listed there rather than here so each sits beside the
criteria it owns; a reviewer runs both tables.

---

## 6. Builder decisions, made here rather than left open

1. **The refusal's replacement wording is the builder's**, within §3.1's
   three required properties and its two prohibitions. Fixing exact bytes
   here would put a prose string under the code gate for no gain; the
   criteria pin what matters (S-23 named, `chezmoi` absent, effect
   unchanged, and the replacement surface named).
2. **`rules_dest` is the single composition site** for
   `claude-md:rules:<topic>` in `models.py`. A second f-string of that
   shape anywhere in this unit's diff is a defect.
3. **Tests live where their subject already lives.**
   CLI: `cli/tests/test_a2_rules_local.py`, continuing the
   `TestObligation<N>` class naming — the last existing class is
   `TestObligation28NonRulesTargetsByteIdentical` (`:1438`), so this unit
   **starts at 29**. The `reference`-refusal criterion (**A9**) goes in
   `cli/tests/test_verbs.py` beside `TestRouteDestination` (`:205`), which
   is where every other destination-resolution refusal lives.
   UI: `ui/tests/test_models_detail.py` and `test_models_bucket.py` for the
   model functions (A4's model legs, A7's function legs, A12, A16's model
   half, A17, A19); `ui/tests/test_routes.py` for the HTTP legs of A5 and
   A7, A4's rendered legs, the argv leg of A13, and A16/A18. The two
   retargeted `test_models_bucket.py` assertions (§3.5A) stay in place.
4. **`str` comparison of topics, no normalization.** `"t"` and `"T"` are
   different topics; the kebab rule already forbids the second. Consistent
   with `U-pathed` builder decision 11 for globs.
5. **No new I/O in `models.py`.** `_record_rules_topic` lives in
   `routes.py` because that module already reads the ledger per render
   (`_record_scope`, `:1444-1453`).
6. **Suite baselines for this unit**, measured this session at `83c1d5d`
   with a scratch `XDG_CACHE_HOME` and the four `SELF_LEARN_*` redirects,
   rc read **unpiped**:

   | Suite | Command (from the plugin dir) | Result | Tolerated |
   |---|---|---|---|
   | CLI | `./.venv/bin/python -m pytest -q` | **1379 passed, 5 skipped, 0 failed**, rc 0 | none — any red is this unit's |
   | UI | `./.venv/bin/python -m pytest tests -q` | **1149 passed, 1 failed, 0 skipped**, rc 1 | `test_service_unit.py::test_both_units_document_manual_registration_via_symlink` only |

   The UI run **must** export both `XDG_CACHE_HOME=<scratch>` and
   `PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"` (campaign §4a).
   **Zero skips is part of the baseline**: a cache-only redirect hides
   Chromium and reports skips, which a pass-count check cannot distinguish
   from a clean run. Read the FAILED lines and check the skip count is 0.
7. **A fresh worktree has no `.venv`.** Both were created with
   `uv sync` and each was verified to resolve to *this* tree
   (`os.path.realpath(self_learn.__file__)` /
   `self_learn_ui.__file__` both under the worktree) before any measurement
   — the campaign's editable-install and wrong-tree hazards.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 S-25's residual, restated honestly — this unit widens its exposure and closes nothing

**S-25 (ACCEPTED, ratified): user-scope pathed globs have no dead-glob
guard and structurally cannot have one.** This unit does not change that,
and must not be read as having done so. The exact state after this unit:

**Guards that DO apply to a user-scope pathed route:**

1. **The proposal-schema shape check** —
   `ledger_ops::_validate_rules_fields` (currently `ledger_ops.py:1312-1364`):
   `rules_topic` must be a non-empty kebab slug; `rules_paths`, when
   present, must be a **non-empty list of non-empty strings**. Shape only.
2. **The absolute / `~`-leading refusal** — `U-pathed` §3.4(1), in
   `_resolve_rules_target` (currently `verbs.py:826-836`). Shape only, no
   filesystem, and it is the one guard that covers user scope at all.
3. **The topic slug check** at `--dest` parse time (`verbs.py:491-503`) —
   **which guards the TOPIC, not the globs** (F12). It is listed because it
   is a mechanical guard on this route, not because it bears on glob
   correctness at all; S-25's own text names exactly **two** glob guards, and
   they are items 1 and 2. Nothing here adds a third.

**Guards that do NOT apply, and cannot:**

- **No zero-match check.** `_validate_project_globs` (currently
  `verbs.py:717-752`) runs only on the project branch
  (`verbs.py:890-891`). There is no canonical tree for a user-scope glob —
  S-23's measurement 2: it resolves against whatever repo the session
  happens to run in.
- **No `selfcheck` reassertion.** `selfcheck::_check_drift`'s glob
  reassertion is explicitly project-only
  (`selfcheck.py:613`: `if routing.get("variant") == "rules" and
  record.scope == "project"`), with the reason stated in its own comment at
  `:609-610`.

**So a misspelt user-scope glob fires nowhere and reports nothing, and
after this unit that gap sits on a tier the review surface actively
offers.** The only remaining check is the human's read of the card, which
is why **A10** pins the globs being rendered verbatim. This unit claims
nothing beyond that. S-25 is already written into `03-decisions.md`; no new
decision row is needed, and this unit must not add one.

**S-24's residual also rides along unchanged** (`03-decisions.md`): a
PATHED destination looks like delivery and, for a Grep/Glob-only workflow,
silently is not. Nothing here changes it; the doctrine consequence is
`U-composer`'s.

### 7.1A Declared residual — the route-time stale-proposal window (F4)

**§3.2 reads the proposal sibling at ROUTE time, not at render time**, and
r1 never engaged what that means. Verified this round: `route` re-checks
`record_sha` freshness **only** for hook destinations
(`verbs.py:2101-2107` — the comment names it and the `if destination ==
"hook"` branch is the only caller of `_prepare_hook_route`); a claude-md
route performs no such re-check. So a worker re-analysis landing **between
the page render and the human's confirm** that keeps the topic but changes
`rules_paths` would substitute globs the human never saw — while A10's whole
safety argument is that the human read the globs on the card.

**ACCEPTED as residual, with the reason stated so a later agent does not
re-open it as a bug:**

- **It is pre-existing, not created here.** The bare `route <id>` path has
  always read the sibling at route time; §3.2 gives the `--dest` path the
  same semantics rather than a new one. Closing it would mean adding a
  freshness gate to the claude-md path — a change to shipped behaviour on
  every claude-md route, which is neither this unit's file-set question nor
  its ruling to make.
- **The payload is a glob, not an attribution.** The substituted value is
  narrower delivery of the same lesson to the same topic file, not a
  different destination and not a different record. The tier the human
  chose, the file, and the record all still hold. (Contrast FW-64, which
  rejected a proposal comparison for `by` precisely because the *attribution*
  would be wrong; nothing here re-opens that.)
- **It is bounded by the same window that bounds every other verb**, and the
  worker is coalesced, so the window is a review session's length, not a
  standing condition.

Named here rather than in `03-decisions.md`: it is a property of an existing
verb, not a new decision, and S-25/S-24 already carry this unit's
decision-register obligations.

### 7.1B Inherited residual — an SSE refresh still wipes the pending cycle (F7, FW-69)

The two-element cycle this unit creates **inherits a live loss path it does
not create**. `app.js`'s `reloadDeferred()` defers a broadcast reload for an
armed bar, an error strip and a few offer states, but **not** for an
in-progress destination cycle: an SSE broadcast or the 10 s poll fallback
arriving mid-cycle wipes the human's pending choice
(**FW-69**, `14-forward-work-map.md:109`, open BUILD). Its sibling **FW-68**
(`:108`) is the same root cause with a bigger blast radius — an *armed* verb
lost the same way.

This unit makes the loss more consequential without making it more likely:
before, the only thing losable at user scope was a singleton that could not
be cycled at all; after, it is the human's choice of *tier*. **Not fixed
here** — the fix is in `app.js`'s defer list, outside this file set, and
FW-69's own row notes the machinery already exists and already enumerates
what it protects. Named so the two rows are read together with this unit.

**r1 mis-cited this defect class as "FW-64" twice** (§1.1 D3 and §3.2).
FW-64 is the `routing.by` attribution fix; the class meant is FW-68/FW-69,
whose partial fix shipped as `f74c249`. Corrected throughout.

### 7.2 Declared residual — a plain proposal cannot be cycled to pathed

If the analyst proposes plain `claude-md` at user scope with no
`rules_topic`, the cycle stays a singleton and the pathed tier is
unreachable by keystroke. **This is deliberate, not an oversight:** a topic
is a *name*, and S-21's ratified shape is that a name is proposed by the
analyst, validated by the CLI, and confirmed by the human — never minted by
a keystroke. The escape hatch exists and is not new: **Iterate**, whose
pane grammar already admits `claude-md:rules:<topic>`
(`proposals.py:97-100`), and which this unit's §3.2 fix now makes deliver
globs correctly for the first time.

The residual is that the surface does not *say* the escape hatch exists.
The action bar's existing hint —
*"hook / new-skill need Iterate — not cycle-reachable"*
(`partials/action_bar.html:269`) — is the natural place to name a rules
topic too. **This unit declines it (§9.3, gate-upheld), and r1's cost claim
for it was wrong.** It is **not** a "one-string" change: that hint renders at
**every** scope, and rules are unavailable at skill scope (P-A13,
`verbs.py:811-816`), so a correct edit is **scope-conditional** — new
template logic, not a new literal. Combined with the fact that its wording is
`U-composer`'s doctrine question (what *should* be offered) rather than this
unit's menu question (what *can* be), declining is right; but it is declined
on cost-plus-ownership, not on triviality.

**This residual is an S-22 funnel and gets a forward-work row** (§9.5): a
human holding a plainly-proposed user lesson they judge file-scoped has no
in-surface indication that the pathed tier exists at all. That is exactly
"a constraint that silently removes an option the agent should have had".

### 7.3 Named handoffs — the change, not a silent assumption

- **`teach --route --dest claude-md:rules:<topic>` still cannot carry
  globs.** `route_direct` calls `_parse_dest` directly (currently
  `verbs.py:2414`) and has **no proposal sibling to read** — the docstring
  says so — so §3.2's inheritance cannot apply there by construction. The
  one-motion path therefore writes an unpathed rules file. Not fixed here:
  the fix is either a `--rules-paths` flag (rejected, §3.2) or threading
  the one-shot analyst's own proposal dict, which touches `teach.py` and
  `analyst.py` — both `U-composer`'s. **State this plainly wherever this
  unit is recorded as BUILT.**
- **Bucket-page grouping still shows a pathed rule under the plain
  claude-md heading.** `_group_key_for` (`models.py:1161-1167`) keys on the
  bare destination enum, and `_GROUP_LABELS`/`_GROUP_ORDER`
  (`models.py:339-356`) are enum-keyed by P-A11's single-map rule. A rules
  topic is a parameterization, not a sixth destination (R-2,
  `ledger_ops.py:1325-1329`), so splitting the group needs a group-key
  vocabulary this unit does not own. Forward work; not a defect this unit
  introduces.
- **FW-43 overlaps this unit at exactly one site.** FW-43 lists three
  stale-chezmoi grounds: `routing-doctrine.md:124`,
  `verbs.py:950-955` and `fast-lane-spec.md:39` (**FW-43's own numbers;
  the middle one is stale on this tree** — `verbs.py:950-955` is now inside
  `_resolve_target`'s claude-md branch, and the refusal it means is
  `:1045-1050`; see §10 item 1). The middle one is the
  `reference` refusal — **this unit owns it** (§3.1) and adds
  `models.py:98-99` (which FW-48's row already flags). The doctrine and
  fast-lane-spec sites stay FW-43's. Named so neither is done twice nor
  left for the other.

### 7.4 Report, do not fix

- Anything in `compilers.py`, `selfcheck.py`, `ledger_ops.py`,
  `analyst.py`, `worker.py`, `pane.py`, `cli.py`, `teach.py`.
- The `surface_fill` register and its capped-destination set.
- `U-pointer`'s pointer emission — it shares `verbs.py` and
  `compilers.py`; sequence, do not overlap.
- When a lesson *should* be pathed (`U-composer`'s doctrine, including
  S-23's at-or-after-first-contact rider and S-24's search-only rider).

---

## 8. Test obligations carried from the campaign

Campaign §5, applied to this unit:

1. **Every gate-shaped check ships with a positive control.** Twelve, one
   per criterion that could otherwise pass while blind: A1's sandbox-1
   frontmatter assertion (against a build that emits nothing anywhere),
   A4's no-variant leg, A5's leg 2 (anti-override), A7's
   `destination_cycle_for("user", None)` leg **and its POST-fragment
   no-topic control**, A8's skill-scope leg, A9's
   still-works-at-skill-and-project leg, A10's unchanged-project-wording
   leg, and A14's one-rules-route-in-the-same-fixture leg — plus three in
   §8A: A16's absent-fields leg, A17's project-scope leg, and A19's two
   unchanged scopes. Each is named with what it prevents.
2. **Never read an exit code downstream of a pipe.** Both baselines in
   §6.6 were captured unpiped.
3. **A spec that pins an ALGORITHM in prose has pinned an untested claim.**
   This spec pins one predicate precisely enough to transcribe — §3.2's
   inheritance condition. **It was executed, not reasoned:** the three-way
   probe of §1.1 (bare / `--dest claude-md` / `--dest claude-md:rules:t`)
   was run against the real `verbs.route` on this tree, and its measured
   outputs are what A1/A2/A3 assert. The oracle is the CLI itself plus an
   **independent** `ruamel.yaml.YAML(typ="safe")` re-parse of the emitted
   frontmatter — never `compilers.read_paths_frontmatter`, which is the
   writer's own reader. Sandbox configuration is stated in §1.1.
4. **The 51 resolved records are the table's regression fixtures** —
   `U-table`'s obligation, not this unit's. This unit adds no table.
5. **The pair harness** — `U-pairs`. Not this unit's.

---

## 8A. H5 — a `defer` recommendation must not arm a route (assigned from `U-table`)

`U-table`'s §8-H5 obligation was unowned, and this is the only unit on
`ui/models.py`. Taken here.

### 8A.1 The defect, re-measured this round

`U-table`'s gate measured it and this unit reproduced it in-process:

```
correct_destination("user", "reference")
  -> ('claude-md',
      'the analyst suggested reference, which needs a skill or project
       to keep the file in - corrected to claude-md')
WhyRegion fields: already_canon, already_canon_reason, alternates, budgets,
  destination, freshness, freshness_label, rationale, rules_paths,
  rules_topic, variant          # no `recommendation`, no `flags`
```

A grep over `ui/src` + `ui/templates` returns **zero** hits for
`recommendation` or `flags` as proposal fields. So a user-scope DEMAND
proposal — the shape `U-table` will render as `reference` +
`recommendation: defer` + `flags: [no-cheap-surface]` — today:

1. **arms `claude-md`** by default (`models.py:291-312` against
   `_SCOPE_DESTINATIONS["user"] == ("claude-md",)`), i.e. the ALWAYS tier;
2. explains itself with a note that reads as a **routine scope correction**,
   saying nothing about the analyst's actual recommendation; and
3. resolves on one keypress into `~/.claude/CLAUDE.md`.

That is the ALWAYS upgrade `U-table`'s R-SCOPE rule exists to prevent,
recreated one layer up — and H5's own wording names why it is invisible:
*"A proposal whose recommendation is defer because its surface does not
exist at that scope looks, on a card that shows only destination, exactly
like one the analyst chose to defer."*

### 8A.2 The design — three parts, all inside this unit's file set

**(1) Surface the fields.** `WhyRegion` gains
`recommendation: str | None = None` and `flags: tuple[str, ...] = ()`, read
straight off the proposal in `_build_why` (`models.py:1572-1599`) — the same
additive P-A6 posture `variant`/`rules_topic`/`rules_paths` already use at
`:1596-1598`, so every pre-existing proposal yields `None`/`()`.
`detail.html` renders them beside the suggested destination, and **renders
nothing at all when absent** — required, because no live proposal carries
them today and none will until `U-composer`'s flip (S-26).

**(2) A `defer` recommendation arms nothing.** This is the load-bearing
half. When the proposal's `recommendation == "defer"`,
`proposed_destination` (§3.3d) returns `(None, <note>)`.

**That shape already exists and is already tested.** `correct_destination`
returns `(None, None)` today for `hook`/`new-skill`/no-analysis
(`models.py:305-306`); the action bar renders "(analyst suggestion)" for an
empty dest (`partials/action_bar.html:268`) and `build_argv` omits `--dest`
(`routes.py:133-134`). So Approve on such a record does **not** execute a
`claude-md` route — it takes the CLI's own proposal-driven path, which for
`reference`-at-user-scope hits §3.1's refusal and fails **loudly, with the
S-23 message that names project scope or defer**. No new UI machinery, and
the outcome is the honest one.

*The tradeoff, stated:* the human learns this by a refused confirm rather
than a disabled button. Greying out Approve would need new state and a new
template branch; the refusal path is already built, already tested, and
already worded correctly after F6. The note in part (3) makes it predictable
rather than an ambush.

**The `o` cycle still reaches `claude-md` in one press on such a record, and
that is CORRECT — stated here so the code gate does not re-derive it as a
hole.** With `dest` empty, `cycle_destination(None, scope)` returns
`cycle[0]` (`routes.py:245-246`), i.e. `claude-md`. That is not the silent
default H5 kills; it is an **explicit human override**, and the surface
records it as one: `action_cycle_destination` sets `dest_touched=True`
unconditionally (`routes.py:1568`), so the route is attributed
`by: human` (`routes.py:1651`) rather than `by: analyst`. **That is exactly
the distinction FW-64 built `dest_touched` to preserve** — a positive fact
about what the human did, never a comparison against the proposal. H5
removes the ALWAYS tier as the *unattended default*; it does not, and must
not, remove it as a *choice*.

**(3) The note must not lie about why.** `_DEST_CORRECTION_REASONS`
(`models.py:111-114`) currently explains `reference` as *"which needs a
skill or project to keep the file in"* — mechanically true, wrong frame at
user scope, where the answer is not "pick claude-md instead" but **"this
lesson has no cheap surface here"**. The user-scope `reference` reason
becomes the S-23 tier statement, matching §3.1's CLI-side message and
§3.3(a). Keyed on the **situation** (`reference` at user scope), not on the
flag — so it is correct today, before any flag is ever populated.

### 8A.3 Declared dependency, and what is deliberately NOT blocked

**Nothing above waits on `U-table`'s merge.** The fields exist in the schema
since `U-schema`; their *values* arrive with `U-composer`'s flip (S-26).
Reading and rendering them is buildable now, and the behavioural rule keys
on `recommendation == "defer"` — a value H5's own wording pins.

**The one genuine coupling, declared:** `U-table` owns the **flag
vocabulary**, and this unit knows only `no-cheap-surface` by name. So
**`flags` are display-only here**: they render, and they change no
behaviour. An unknown flag therefore renders and does nothing — the
fail-safe direction, and it needs no coordination. **If a flag ever needs to
change behaviour, that is a new coupling with no owner** — carried as the
**`card-flags-are-display-only`** forward-work row (§9.5, numbered by the
builder at landing) with an explicit trigger: the first flag whose meaning
is behavioural.

### 8A.4 Criteria

**A16 — `recommendation` and `flags` reach the card, and their absence
renders nothing.** Rendered Detail page for a proposal carrying
`recommendation: defer` and `flags: [no-cheap-surface]` contains both
values. **Positive control in the same test:** the identical record with a
proposal carrying neither renders a page with no empty label, no `None`, and
no stray punctuation where they would have gone.

*Absent/broken:* the second leg is not decoration — this codebase has
shipped a literal `"None"` at the operator before (`ee005f8`). A build that
renders the fields unconditionally passes leg 1 and fails leg 2.

**A17 — a `defer` recommendation arms no destination, at every scope.** For
a user-scope proposal with `destination: reference`,
`recommendation: defer`, `flags: [no-cheap-surface]`:
`proposed_destination` returns `(None, note)`; the rendered bar's hidden
`dest` input is **empty**; `build_argv` for that record omits `--dest`
entirely. **And the same assertion for a PROJECT-scope proposal carrying
`recommendation: defer`** — the rule is about the recommendation, not about
the scope that happens to expose it.

*Absent/broken:* today the first leg returns `('claude-md', <note>)` and the
hidden input carries `claude-md`, so it fails on every assertion. Without
the project leg, a build that special-cased `reference`-at-user-scope
instead of reading the recommendation passes.

**A18 — a `defer`-armed record's Approve does not write always-loaded
canon.** End to end at user scope: confirm that record; the CLI refuses,
the record stays in `pending/`, the user `CLAUDE.md` gains **no** managed
entry, and the surfaced error names **S-23**.

*Absent/broken:* this is the criterion that makes the whole section worth
building — it is the ALWAYS upgrade itself. Today the confirm **succeeds**
and the entry lands, so it fails loudly. It also pins F6's conditional
refusal wording end to end.

**A19 — the user-scope `reference` correction note states the tier fact.**
`correct_destination("user", "reference")[1]` names the absence of a cheap
surface at user scope and does **not** read as a routine scope correction.
`correct_destination("project", "reference")` is **unchanged** —
`("reference", None)` — and `correct_destination("skill", "reference")`
likewise.

*Absent/broken:* the two unchanged legs are the control; without them a
build that rewrote the reason for every scope passes. As with A10, no
assertion can prove the copy reads honestly — **the reviewer must read the
shipped string**, and it is named here so the gate performs it.

### 8A.5 Mutations

| # | One-line edit to production code | Test that must fail |
|---|---|---|
| M24 | `_build_why`: drop the `recommendation`/`flags` reads (return the r1 field set) | **A16** leg 1 |
| M25 | `detail.html`: render the two fields unconditionally, without the absent-guard | **A16** leg 2 |
| M26 | `proposed_destination`: drop the `recommendation == "defer"` leg | **A17** (both legs), **A18** |
| M27 | `proposed_destination`: fire the defer leg on `destination == "reference"` instead of on the recommendation | **A17**, project leg |
| M28 | `_DEST_CORRECTION_REASONS`: restore the r1 `reference` wording at user scope | **A19** leg 1 |

---

## 9. Decisions — r1's open questions, RULED at the gate

r1 routed four questions to the gate. **All four came back ruled**; they are
written in here as decisions with the gate's own grounds, not left as
questions. Nothing in this section is open.

### 9.1 — The QUALIFIED reading of P-A5 binds. Option A stands. (RULED)

**Decision: §3.2's inheritance is correct and stays.** Option B is
**struck**, along with r1's contingent fallback branch.

**The grounds, which are stronger than r1's own argument.** r1 argued from
P-A5's *rationale* and *safety property*. The gate settled it from the
source instead: **A2's test obligation 16
(`a2-rules-local-spec.md:976-981`) scopes itself to `route_direct`** — which
is *by construction* the no-proposal case (`verbs.py::route_direct`, whose
docstring at `verbs.py:2381-2390` states "there is no proposal sibling to
read"). **No user-facing routing path is covered by the sentence that reads
literally.** So there was never a live contract in conflict; the ambiguity
existed only in prose that never governed a reachable case. §4.4B's own
closing sentence describes Option A's behaviour, P-A5's rationale is about
encoding globs in the dest string (which Option A never does), and its
safety property — *"reaching a pathed rule requires a proposal a human
read"* — is preserved by the same-destination-same-topic predicate.

**Consequence:** §3.2 stays; A1, A3, A6 and M1-M4 stay; **A15 stays** as the
regression guard proving `route_direct`'s side is untouched. **This did not
need the user** — no ratified decision was in tension, only an
under-qualified sentence.

### 9.2 — SCOPE-GENERAL, on a structural ground r1 did not give. (RULED)

**Decision: the mechanism is scope-general.** r1 argued this on
consequences (a user-only fix leaves project-scope proposals downgrading).
The gate supplied the stronger, structural reason, and it is the one to
record:

> **`_resolve_destination` takes no scope parameter** (`verbs.py:537-538`:
> `(bucket_dir, record_id, dest)`). A user-only fix would require threading
> `scope` *into* it — more change, not less, and it would introduce a
> **second scope predicate** of exactly the kind `U-pathed` §7.5 warns
> against.

So scope-general is both the smaller diff and the one that adds no new
scope definition. A8 pins project scope; `RULES_SCOPES` (§3.3c) mirrors the
CLI's single guard rather than duplicating a rule.

### 9.3 — The Iterate hint is NOT changed here. (RULED, upheld - with two corrections)

**Decision: declined**, as r1 proposed. Two corrections ride the ruling:

1. **r1's cost claim was wrong** and is fixed in §7.2: it is not a
   "one-string" change. `partials/action_bar.html:269` renders at **every**
   scope, and rules are unavailable at skill scope (P-A13,
   `verbs.py:811-816`), so a correct edit is **scope-conditional** — new
   template logic. Declined on cost-plus-ownership, not on triviality.
2. **The residual is an S-22 funnel and gets a forward-work row** (§9.5).

### 9.4 — `_group_key_for`'s bucket grouping is DEFERRED. (RULED, upheld)

**Decision: defer**, with the forward-work row r1 promised (§9.5). The
gate's added ground: **the human is not misled at the point of decision** —
`detail.html:132` renders the variant label, the resolved path and the
firing note, and after §3.3(e) the armed bar shows the glossed armed dest.
The bucket-page *group heading* is a navigation label, not the commitment
surface, and Checkpoint C measures `routing` blocks rather than page
headings.

### 9.5 — Forward-work rows this unit must land

Three rows, written into `14-forward-work-map.md` **in the same commit as
the build** (the campaign's disposition rule: an undeclared residual is one
a later agent re-opens as a bug).

**They are named by SLUG, not by number, and the builder allocates the
next free `FW-` numbers at landing time.** r2 pinned them as FW-70/71/72 on
the belief that FW-69 was the highest row. That was wrong on r2's own base
— `83c1d5d` already carries **FW-70** (`14-forward-work-map.md:110`, the
`telemetry.flush()` torn-line residual) — and master has since moved to
**FW-75** (`07d8c08`). All three numbers collide, and **FW-72 collided
twice**, since §8A.3 also cited it by number. A spec that hardcodes a
register number is asserting a fact about a file it does not own and that
several units are appending to concurrently; a slug cannot rot that way.

| Slug | Row |
|---|---|
| **`pathed-tier-unreachable-from-surface`** | **S-22 funnel — a plainly-proposed user lesson cannot reach the pathed tier from the surface.** With no `rules_topic` on the proposal the `o` cycle is a singleton and nothing on the bar says Iterate can supply one. `partials/action_bar.html:269` is the natural site; the edit is scope-conditional, not a one-string change (rules are unavailable at skill scope, P-A13). Wording is `U-composer`'s doctrine question. Source: `U-demand-user` §7.2 / §9.3 |
| **`bucket-grouping-hides-the-tier`** | **Bucket-page grouping files a pathed rule under the plain claude-md heading.** `_group_key_for` (`models.py:1161-1167`) keys on the bare destination enum; `_GROUP_LABELS`/`_GROUP_ORDER` (`:339-356`) are enum-keyed by P-A11. A rules topic is a parameterization, not a sixth destination (R-2, `ledger_ops.py:1325-1329`). Needs a group-key vocabulary no unit currently owns. Source: `U-demand-user` §7.3 / §9.4 |
| **`card-flags-are-display-only`** | **The card's `flags` vocabulary is display-only and unvalidated.** `U-demand-user` §8A renders `recommendation`/`flags` and keys behaviour on `recommendation == "defer"` alone, treating every flag as display text. If `U-table` or `U-composer` later needs a flag to *change* behaviour, that coupling has no owner and no agreed vocabulary. Trigger: the first flag whose meaning is behavioural. Source: `U-demand-user` §8A.3 |

**Landing instruction for the builder:** read the current highest `FW-`
number in `14-forward-work-map.md` at the moment you land the build, and
allocate upward from there. Do not reuse a number from this document.

## 10. What this spec corrects

Recorded because a spec that silently diverges from its sources is how a
fabricated pin gets made.

1. **The campaign row's citation for the `reference` refusal is stale.**
   `forward/r2-routing-campaign.md:87` gives *"then `:950-955`, currently
   `:1009-1021`"*. On this tree at `83c1d5d` the branch is
   `verbs.py:1038-1060` and the refusal is `:1045-1050`; `:1009-1021` is
   now the **new-skill** branch's marketplace and foreign-plugin refusals.
   The row itself warned this might have drifted, and it had.
2. **`U-pathed`'s spec carries the same stale number.** Its §7.4 and §7.5
   both cite `verbs.py:1016-1021` for the refusal. Same correction. (Both
   documents post-date the ~208-citation repair pass; `verbs.py` grew
   afterwards via `4f8817a` and `5fa3fbb`.)
3. **`U-pathed` §7.5's "there is no dependency from this unit to that one"
   is true as stated and incomplete as read.** It verified the *bare*
   route path. §2.2 above records why that verification could not see D1
   or D2, and neither claim contradicts the other.
4. **FW-42's phrasing — "the menu gains the pathed-rules destination" —
   does not mean `_SCOPE_DESTINATIONS["user"]` grows.** §3.3(b) explains
   why the pathed tier cannot be a scope-constant enum member. A builder
   who reads the row literally and appends a string to that dict ships a
   dest the CLI refuses for want of a topic.
5. **A2's obligation 16 states its contract without the qualifier its own
   rationale carries — and the scoping resolves it.**
   `a2-rules-local-spec.md:320-326` says *"Bare
   `--dest claude-md:rules:<topic>` **with no proposal** yields an
   **unpathed** rule"*; `:429-431` and obligation 16 (`:976-981`) then
   restate it as *"the contract is that bare `--dest
   claude-md:rules:<topic>` resolves to the unpathed rules target"*,
   dropping *"with no proposal"*. **r1 declined to resolve this and routed
   it to the gate; the gate resolved it from the source rather than by
   assertion:** obligation 16 **scopes itself to `route_direct`**, which is
   by construction the no-proposal case (`verbs.py:2381-2390` — "there is no
   proposal sibling to read"), and the shipped tests
   (`test_a2_rules_local.py:764-795`) exercise only that path. **No
   user-facing routing case was ever governed by the literal sentence**, so
   the qualified reading binds and §3.2 is inside the pin (§9.1). A2 was
   written before S-23 promoted PATHED to the primary cheap tier and before
   the review UI's always-explicit `--dest` was documented; neither fact was
   available to it.
6. **This spec silently corrected two of S-25's own citations, and says so
   here because §10 is what that is for (F12).** S-25's row in
   `03-decisions.md` cites `ledger_ops.py:613-623` for the proposal-schema
   shape check and `selfcheck.py:374-399` for the project-scope glob
   reassertion. On this tree they are `ledger_ops.py:1312-1364`
   (`_validate_rules_fields`) and `selfcheck.py:613` (inside `_check_drift`).
   §7.1 uses the current numbers. **The decision row itself is not edited by
   this unit** — a settled row's citations are repaired by a citation pass,
   not by a unit that happens to read it.

Nothing here contradicts **S-23**, **S-24** or **S-25**. §3.1, §3.3 and
§7.1 all follow from S-23 (2) and from the measurements it rests on. **After
the gate's ruling on item 5, this spec has no live tension with any gated
document.**

---

## 11. Revision history

- **r2** — 2026-08-06. **Blind spec gate round 1: SOUND — buildable after
  folds; 1 BLOCKER, 5 FOLD, 7 NOTE.** The gate re-executed all three of r1's
  headline measurements exactly — the three-way route probe, `build_argv`
  end to end through the real ASGI app, and the `reference`-refusal deletion
  mutation on a shadow package (control 1379/5/0, mutated 1 failed, the same
  `test_batch_fixes.py` guard with the same message). Both §6.6 baselines
  confirmed; ~45 citations clean except the blocker's. All four campaign-row
  binding constraints ruled HONOURED; the `routes.py`/`bucket.html`
  expansions ruled FORCED. What changed:

  **BLOCKER F1** — r1 mislabeled `routes.py:1274` as "the degraded-Detail
  context". It is `_unarmed_context`, the shared context for **every**
  POST-rendered unarmed bar, so leaving it on `destinations_for_scope` made
  the `o` cycle a **one-way trip**: the human reaches the pathed dest and the
  re-rendered bar tells them only one destination fits. The gate's invented
  **M20 survived r1's entire criterion set**. Fixed in §3.4 — with the count
  **pushed back**: **eleven** `_unarmed_context` call sites, not the six the
  gate listed, and all eleven thread `scope`. Plus A7's POST-fragment leg,
  M20, and §3.6's count.

  **F2** — MEASURED: r1's **M2 killed nothing.** Carrying `rules_paths` alone
  on a bare `--dest claude-md` leaves `variant`/`ref_name` `None`, so the
  claude-md branch never reaches `_resolve_rules_target` and the globs are
  silently dropped — byte-identical to A2's *correct* behaviour. Both shapes
  re-probed this round; M2 reworded to the wholesale-adoption shape (which
  does redden A2), A2's absent/broken paragraph replaced with the measured
  table, the narrow shape's ownership moved to A3.

  **F3** — r1's `correct_destination` passthrough checked the scope but not
  the **topic**, so `_scope_corrected_dest` would have trusted a
  client-echoed topic the record never proposed — against its own pinned
  "never by trusting the echo" posture. The gate's invented **M21 survived**.
  Topic check added in `_scope_corrected_dest` (§3.3d'), A5 leg 3, M21.

  **F4** — §3.2's route-time proposal read reintroduces the stale-proposal
  window; verified that `route` re-checks `record_sha` only for hook
  destinations (`verbs.py:2101-2107`). Declared as §7.1A with its acceptance
  reason.

  **F5** — the commitment surface rendered the new primary tier **less**
  honestly than the tier it replaces: the resolved-path span vanishes for a
  qualified dest (`action_bar.html:268`) and the armed bar prints the raw
  token (`:95`). Both fixed (§3.3e), with A4 rendered legs and M22/M23.

  **F6** — CROSS-UNIT with `U-composer` D4: r1's refusal message named a
  rules topic *unconditionally*, which for a non-file-scoped lesson steers to
  an **unpathed** rules file — ALWAYS-tier cost under a different filename,
  the silent upgrade D4 forbids. Item 3 is now conditional (§3.1).

  **Notes folded:** F7 (r1 mis-cited FW-68/FW-69 as "FW-64" twice; FW-69
  named as an inherited residual, §7.1B), F8 (five criteria lack mutations,
  not one — A11 called out as the weak regression guard), F10
  (`BucketModel.destination_cycle` becomes dead — **dropped**, its two
  assertions retargeted to the row, §3.5A), F11 ("no **per-topic** fill
  datum"), F12 (guard 3 guards the topic, not globs; §10 item 6 discloses
  r1's silent repair of S-25's citations), F13 (the pane does not *always*
  send a dest — `routes.py:2631` branches on `prop.dest is not None`).

  **Rulings written in as decisions (§9):** Q1 the qualified reading binds —
  A2's obligation 16 scopes itself to `route_direct`, so no user-facing case
  was ever governed by the literal sentence; Option B struck. Q2
  scope-general, on the structural ground that `_resolve_destination` takes
  no scope parameter. Q3 upheld, with r1's "one-string" cost claim corrected
  and an S-22 funnel row. Q4 upheld, with its row.

  **New assignment:** **H5** taken over from `U-table`'s gate (§8A) —
  re-measured in-process that `correct_destination("user", "reference")` arms
  `claude-md` today and that the UI reads neither `recommendation` nor
  `flags`. Four criteria (A16-A19), five mutations (M24-M28), one declared
  dependency (the flag vocabulary). Three forward-work rows specified by
  slug (§9.5).

- **r3** — 2026-08-06. **Delta gate: NOT SOUND on exactly four items**, all
  closed here; the gate stated these were the only issues, ruled r2's
  eleven-caller pushback **RIGHT** (conceding its own round-1 six was an
  undercount), and verified the H5 design sound end to end.

  **D1** — the r2 reconstruction lost one edit: §3.3(f) still carried r1's
  "`BucketModel.destination_cycle` stays as the scope-level default" while
  §3.5A and §11 both said it is dropped. Replaced with a pointer to §3.5A.

  **D2** — §3.3(e) claimed `action_bar.html:268` was "unchanged" one
  paragraph above F5 item 1, which changes it. Split: the **label pipe** is
  unchanged, the **path-span guard** is not.

  **D3 — F5 item 2 was not buildable as written.** The armed bar has no
  scope: `_armed_context` (`routes.py:1290-1336`) returns only `kind`,
  `dom_id`, `evidence`, `armed`, `disarm_vals`, and `_base_ctx` adds none.
  Glossing `armed.dest` with an undefined scope does not fall back to the
  raw token — it renders **"Project instructions" on a user-scope record**,
  a confidently wrong tier *and* scope at the moment of commitment, worse
  than what it replaced. Fixed as specified: `action_arm` computes the
  scope, `_armed_context` gains the key, §3.4 gains two rows, §3.6's count
  goes to five changed, **M29** added, and A4's armed leg now asserts the
  **exact** gloss string with `Project instructions` named as the trap so no
  builder writes a loose "not the raw token" assertion.

  **D4** — §9.5's "highest existing row is FW-69" was wrong on this unit's
  own base (`83c1d5d` already carries FW-70) and master has since reached
  FW-75, so all three proposed rows collided — FW-72 twice, since §8A.3
  cited it by number too. All three are now named **by slug**, with the
  builder allocating the next free number at landing.

  **Also folded:** the gate's correction to r2's pushback text. r2 claimed
  all five previously-missed `_unarmed_context` sites "still render the
  cycle control"; verified false for three — `:1793` and `:2721` sit inside
  `if evidence is not None:` and the cycle control lives in
  `action_bar.html`'s `{% if not evidence %}` branch (`:208-276`), and
  `:2247` is the post-successful-route retry where the proposal sibling is
  already deleted, so the topic is `None` by construction. Correct sets:
  **eight correctness-critical, three inert**. The thread-all-eleven
  instruction **stands** — a uniform rule cannot drift, and the inert three
  cost one `None` each.

  **And one line the gate asked for in §8A.2:** on a defer-armed record the
  `o` cycle still reaches `claude-md` in one press
  (`cycle_destination(None, scope)` returns `cycle[0]`). That is **correct**
  — an explicit human override recorded as `dest_touched=True` → `by:
  human`, the exact FW-64 distinction — and not the silent default H5 kills.
  Stated so the code gate does not re-derive it as a hole.

- **r1** — 2026-08-06. Written against this worktree at `83c1d5d`, from a
  full read of `verbs.py` §§440-560, 600-720, 780-1065, 2023-2160,
  2368-2420; `ui/models.py` §§70-360, 1006-1300, 1330-1660; `ui/routes.py`
  §§94-180, 225-250, 1250-1290, 1410-1580, 1600-1680, 2100-2200, 2600-2660;
  `ui/ledger.py` §§216-340; `ledger_ops.py` §§75-90, 1250-1370, 1780-1915;
  `analyst.py` §§60-120; `selfcheck.py` glob sites; and the four templates
  named in §3. **Empirical work run and reported inline:** the three-way
  route probe (§1.1), the UI destination-chain probe (§1.1), the
  `reference`-refusal deletion mutation against the full CLI suite (§1.2,
  reverted by inverse Edit, `git diff --stat` empty), and both suite
  baselines (§6.6).
