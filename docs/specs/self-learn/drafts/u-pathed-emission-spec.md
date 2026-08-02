# Spec — U-pathed: `paths:` frontmatter emission, union semantics, drift

Status: **DRAFT r1** — awaiting the blind spec gate.
Unit `U-pathed` of the r2 routing campaign
(`forward/r2-routing-campaign.md` §2). Normative parent: **S-23**
(`03-decisions.md`, ruled 2026-08-02) — PATHED is the primary cheap tier
at every scope. Implementation reference: `misc/routing-procedure-r2.md`
B10 (§5 "PATHED — the missing capability"), **which this spec corrects in
four places — see §8.**

**Where prose and acceptance criteria conflict, the criteria (§4) and the
mutation plan (§5) win.** The prose is rationale; the criteria are the
contract.

**Files this unit may touch:** `compilers.py`, `verbs.py`, and the CLI
test suite. `verbs.py` is shared with `U-reach` this wave — the exact
functions touched here are named in §3.5 and nothing is restructured.

---

## 1. The defect

**A "pathed" rules file is an unpathed rules file.** Everything upstream
of emission exists and is tested; the last step was never built.

- A proposal may carry `rules_paths` (`ledger_ops.py:613-623` shape-checks
  it), the route threads it (`verbs.py:1983`), project scope validates it
  against the host tree (`_validate_project_globs`, `verbs.py:675-710`),
  it is persisted into `routing.rules_paths` (`ledger_ops.py:840-841`,
  `verbs.py:2344-2345`), and `selfcheck` re-asserts it for project scope
  (`selfcheck.py:382-399`).
- Then `_apply_target` (`verbs.py:1602`) calls
  `compile_managed_file(spec.target, _compile_set(home, spec))`
  (`verbs.py:1676`) — whose signature (`compilers.py:261-267`) has no
  paths parameter and whose output contains no frontmatter at all.

So the globs are validated, persisted, drift-checked, and **never
written**. This is the same defect shape the campaign exists to fix, and
the r2 audit already named it F1: *"a rules variant that validated globs
it never wrote"*. A green suite has covered every step except the one
that delivers.

**S-23 raises the cost of leaving it.** Before 2026-08-02 PATHED was one
tier among several; the ruling makes it *the* primary cheap tier at every
scope, and makes user-scope pathed rules the entire user-scope cheap
surface. Every lesson routed there today would land in an always-loaded
file wearing a pathed label.

### 1.1 The host measurements this design is built on

Canary test, this host, Claude Code 2.1.220, 2026-07-28; project scope
and then user scope through two fresh headless sessions at different
working directories; canaries removed afterwards (there is no
`~/.claude/rules/` on this host today). **These are measurements. Do not
re-derive them and do not contradict them without new evidence.**

1. **Pathed rules work.** An unpathed control rule loaded at session start
   (positive control passes). A pathed rule stayed out of context;
   reading a non-matching file injected nothing; reading a matching file
   injected it. **The glob discriminates, and injection is lazy on file
   access, not at launch.**
2. **User-level globs are relative to the session's working directory.**
   `**/*.usercanary` fired from both working directories.
   `probe/**/*.usercanary` fired only where cwd made that the relative
   path. **An absolute glob never fired from either directory.**
3. **Two limits.** (a) Only `Read` was exercised. `Edit` is covered in
   practice because Claude Code requires a Read first, but **a
   Grep/Glob-only workflow never triggers injection at all** — §7.1.
   (b) Once injected, a rule persists for the session, so any re-test
   needs a fresh session.

Measurement 2 is why a user-scope pathed rule structurally cannot be
aimed at one repo, and why S-23 scopes user-level pathed rules to
**cross-project file-type conventions**. Measurement 2 is also what makes
§3.4's absolute-glob refusal a delivery guard rather than a style rule.

---

## 2. The one normative register

Everything in this spec that says "the union", "the compile set", "the
expected paths" means exactly this. **It is defined once, here, and every
other site references it by name — including the drift check.**

For a rules target file **T**, resolved by
`(scope, variant="rules", rules_topic)`:

- **C(T) — the compile set.** Exactly `_compile_set(home, spec)`
  (`verbs.py:1313-1379`), which for a rules spec is
  `_routed_to(…, variant="rules", rules_topic=<topic>)`
  (`verbs.py:519-562`), further filtered by the compiler's own
  `_eligible()` (`compilers.py:190-195`: `status == "routed"` and
  `superseded_by is None`).
  **The section and the frontmatter are computed from the SAME C(T).**
  There is no second set and no second query.
- **G(r)** for `r ∈ C(T)` = `tuple(r.routing.get("rules_paths") or ())`.
- **U(T) — the emitted paths**, in order of evaluation:
  1. `C(T)` empty → `()`
  2. **any** `r ∈ C(T)` with `G(r) == ()` → `()` — **the absorbing
     rule**: union with "always" is "always".
  3. otherwise → `tuple(sorted({g for r in C(T) for g in G(r)}))` —
     deduped, sorted, byte-stable.
- **Emission.** `U(T) == ()` ⇒ the file carries **no `paths:` key** (an
  existing one is deleted). `U(T) != ()` ⇒ `paths:` is exactly that list,
  in that order.

Derived reporting values, defined here and computed nowhere else:

- **`unpathed_by(T)`** = sorted ids of `r ∈ C(T)` with `G(r) == ()`, when
  `C(T)` is non-empty. Non-empty ⇒ `U(T) == ()` by rule 2.
- **`widened(T)`** = `U(T) != ()` **and** some `r ∈ C(T)` has
  `G(r) != U(T)` — i.e. at least one lesson's rule now fires on files
  that lesson did not name.

**Agreement, the one comparison.** A file's frontmatter *agrees* with
`C(T)` iff the raw YAML value under the top-level `paths:` key equals
`list(U(T))`, where a **missing** `paths:` key is agreement iff
`U(T) == ()`. Nothing else counts as agreement: a scalar
`paths: "src/**"`, a `paths: []`, or a differently-ordered list all
disagree and are rewritten. This single predicate is what both the writer
and any drift check use (§3.2).

### 2.1 Why the union widens and never splits

Splitting a topic whose records disagree would mean minting a new topic
file — which changes the `(variant, rules_topic) → path` identity that
`_compile_set`, `_target_for` (`selfcheck.py:215-224`) and `recompile`
(`verbs.py:3540-3541`) all key on, and would silently move a human's
routed record to a file they did not choose. **One topic is one file.**
The union widens; the widening is reported (§3.3); which topic a lesson
belongs to stays the analyst's proposal and the human's decision.

### 2.2 Why "any globless record makes the file unpathed"

Carried from r2 B10 verbatim, and it is the fail-safe direction: a lesson
whose author wanted it always-loaded is never demoted into a rule that
might not fire. The cost runs the other way — a globless record silently
converts a whole pathed topic into an always-loaded file, which is
**S-23's monoculture rebuilt through the back door**. It is therefore
kept *and* surfaced loudly (§3.3, criterion **A4**), and the doctrine
consequence — *do not join a globless lesson to a pathed topic; give it
its own topic* — is `U-composer`'s, named in §7.4.

---

## 3. The change

### 3.1 Emission derives from the records, not from `TargetSpec`

**r2 B10 says `compile_managed_file` gains a `rules_paths` parameter.
That design is wrong here, in two independent ways, and both are load
bearing.**

**(a) It would strip the frontmatter on every `recompile`.** `recompile`
deliberately withholds `rules_paths` from `_resolve_target`
(`verbs.py:3535-3539`), and so does `_retirement_preflight`
(`verbs.py:1543-1549`) — both for stated, correct reasons (no glob
re-assertion outside selfcheck). A `spec.rules_paths`-driven emitter
therefore sees `None` at both sites and would rewrite every rules file as
unpathed. A pathed rule would silently become an always-loaded one on the
first repair run. **A builder must not "fix" this by threading
`rules_paths` into `recompile`** — that re-arms the zero-match refusal on
old records at repair time, which is exactly what those two comments
refuse.

**(b) It cannot reach user scope inside this unit's file set.** The
user-scope write goes `_apply_target` → `chezmoi.compile_user_scope`
(`chezmoi.py:270`) → `compile_managed_file` (`chezmoi.py:309-311`,
`:327-329`). Threading a new compiler parameter requires editing
`chezmoi.py`, which is not in this unit's file set. Under S-23 user scope
is the *primary* PATHED consumer, so r2's design would have shipped
user-scope PATHED emitting nothing — silent non-delivery, again.

**Therefore: `U(T)` is computed from `C(T)` (§2), the same records the
section is compiled from.** Both defects vanish — `recompile` and
retirement resolve the same `C(T)` as a fresh route, and no compiler
signature changes, so nothing needs threading through `chezmoi.py`.

### 3.2 New in `compilers.py` — no existing function changes

`compile_managed_text` and `compile_managed_file` are **not modified**.
Their behaviour for every existing caller stays byte-identical (criterion
**A12**). Five additions:

```python
@dataclass(frozen=True)
class PathsResult:
    path: Path
    paths: tuple[str, ...]        # U(T); () = unpathed (no `paths:` key)
    changed: bool                 # the frontmatter region was rewritten
    unpathed_by: tuple[str, ...]  # §2 derived value
    widened: bool                 # §2 derived value
    drift: str | None             # the disagreement this rewrite replaced
    notes: tuple[str, ...]        # human-readable, for the verb warnings channel

def expected_paths(records: Sequence[Record]) -> tuple[str, ...]      # U(T), pure
def read_paths_frontmatter(text: str) -> tuple[str, ...]             # reader, pure
def paths_frontmatter_drift(text: str, records: Sequence[Record]) -> str | None
def apply_paths_frontmatter(path: Path | str, records: Sequence[Record]) -> PathsResult
```

- **`expected_paths`** is §2's `U(T)` and the only place the three rules
  live.
- **`read_paths_frontmatter`** returns the file's `paths:` as a tuple of
  strings; `()` when the file has no leading frontmatter, no `paths:`
  key, or a `paths:` value that is not a list of non-empty strings.
- **`paths_frontmatter_drift`** is §2's *agreement* predicate: `None`
  when the file agrees, otherwise a one-line message naming what was
  found and what is expected. **Both the writer and any drift check call
  this — there is no second definition of "agrees".**
- **`apply_paths_frontmatter`** reads the file, and writes it back **only
  when `paths_frontmatter_drift` is not `None`**. Ownership rule:

  > **The compiler owns exactly the `paths:` key of the file's leading
  > frontmatter block, and nothing else in it.** Other top-level keys,
  > their order, and YAML comments are preserved byte-for-byte by a
  > `ruamel.yaml` round-trip — the same round-trip discipline and for the
  > same reason `records.py:104-117` already uses (`typ="rt"`,
  > `preserve_quotes`, `width=4096`, `indent(mapping=2, sequence=4,
  > offset=2)`). Deleting `paths:` from a block that then has no keys
  > left removes the whole `---…---` block plus one immediately following
  > blank line.

  **Refusals** (`CompileError`, never a guess — the same posture as a
  half-markered target, `compilers.py:244-248`): a missing file; a file
  whose first line is `---` with no terminating `---`/`...`; a leading
  block that does not load as a YAML mapping. `CompileError` is already
  in `_HOST_PHASE_ERRORS` (`verbs.py:1774-1781`) and is already caught by
  `recompile` (`verbs.py:3610`), so a corrupt rules file degrades to the
  existing loud "run `self-learn recompile`" path with the ledger intact.

**Emitted form**, verified this session against the pinned ruamel config:

```
---
paths:
  - '**/*.py'
  - src/**/*.ts
---
```

Quoting is the emitter's, not ours: ruamel single-quotes `**/*.py`
because a bare leading `*` would parse as a YAML alias. A glob that
emitted unquoted would be a syntactically broken rules file — the exact
silent-non-delivery this unit is about — so criterion **A16** re-parses
the emitted bytes with an *independent* loader.

### 3.3 Where it runs, and how it is surfaced

`apply_paths_frontmatter` runs as a **pre-pass inside `_apply_target`**,
in both rules-bearing branches, immediately after that branch's existing
bootstrap and immediately before the section compile:

- **user branch** (`verbs.py:1637-1660`), after the
  `mkdir`/`write_text("")` bootstrap at `:1647-1648`, before
  `compile_user_scope`.
- **project branch** (`verbs.py:1661-1683`), after the bootstrap at
  `:1669-1675`, before `compile_managed_file`.

**The pre-pass is safe against the marker contract, verified this
session:** `compile_managed_text` preserves everything before
`BEGIN_MARKER` byte-exact on regeneration, and on bootstrap appends the
section after the existing text with exactly one blank line. Measured on
a frontmatter-only file, a frontmatter-plus-section file, and an empty
file — all three produce the intended layout.

`_compile_set(home, spec)` is bound **once** per branch and passed to
both the pre-pass and the compile, so the register in §2 cannot be read
twice and diverge.

**Two consequences that must be built, not assumed:**

1. **The `changed` fold.** `_host_phase` stages and commits only when
   `compile_result.changed is not False` (`verbs.py:1826-1836`), and
   `recompile` skips on `not compile_result.changed`
   (`verbs.py:3616-3620`). If only the frontmatter changed — a hand edit
   repaired, or a record's globs edited in the ledger — the section is
   byte-identical and the repair would be **written but never
   committed**, which is drift created by the drift repair. On the
   project branch, when the pre-pass changed the file and the section did
   not, `_apply_target` returns
   `dataclasses.replace(compile_result, changed=True)`. `SectionResult`
   is a frozen dataclass, so this is one expression and no new field.
   (User scope needs no fold: `_apply_target` returns `host_paths = []`
   there and nothing gates on `changed`.)
2. **The notes channel.** `_apply_target` has no warnings list today.
   It gains one keyword-only parameter, `notes: list[str] | None = None`,
   appended to from `PathsResult.notes`. `_host_phase` passes its
   existing `warnings` list; `recompile` passes `result.warnings`. Both
   lists are already printed by `cli.py:1115` / `cli.py:1441` and carried
   into the JSON envelope at `cli.py:1074`, so **zero changes outside
   this unit's file set are needed to surface any of it.**

**Note wording, fixed here so it lives in one place** (`compilers.py`):

- **Absorption** — emitted **only** when `unpathed_by` is non-empty *and*
  at least one record in `C(T)` carries globs (a plainly unpathed rules
  file is normal and stays silent):
  `"<path>: rules file is UNPATHED (loads at launch) because <ids> carry
  no rules_paths — the pathed lessons in this topic now cost full
  always-loaded attention; route a globless lesson to its own topic"`
- **Widening** — when `widened(T)`:
  `"<path>: paths: is the union of <n> routed lessons — each lesson's
  rule now also fires on files it did not name"`
- **Drift repaired** — when `drift is not None` *and* the file already
  had a leading frontmatter block:
  `"<path>: rewrote the compiler-owned paths: frontmatter (<drift>) — it
  regenerates from the routed records' rules_paths; hand edits do not
  survive a route or a recompile"`

### 3.4 Two route-time refusals, both pre-ledger

Both live in `_resolve_rules_target` (`verbs.py:747-803`), which already
owns every other rules preflight.

**(1) An absolute or `~`-leading glob is refused, at both scopes.**
Measurement 1.2: an absolute glob **never fired** from either working
directory. And this is a live fail-open in shipped code, verified this
session: `glob.glob(pattern, root_dir=host)` **ignores `root_dir` for an
absolute pattern** — `glob.glob("/etc/host*", root_dir="/tmp/globtest")`
returned `/etc/hosts` and friends. So `_validate_project_globs` today
*passes* an absolute pattern that provably can never fire, and would
happily emit it. Refusal text names the pattern and says to make it
relative.

`~`-leading patterns ride the same refusal on a *narrower* justification,
stated so the two are not conflated: absolute is **measured** not to
fire; `~/…` is refused because a relative glob matcher does not expand
`~` (verified: `glob.glob("~/*", root_dir=…)` → `[]`), so it can only
ever match a literal directory named `~`.

This check is **shape-only** — no filesystem, no `check_dirty` gate — so
it is deterministic and covers user scope, which `_validate_project_globs`
never sees. (Its better long-term home is
`ledger_ops._validate_rules_fields` at proposal-validation time; that file
belongs to `U-schema`. Named in §7.3, not built here.)

**(2) A pathed user-scope route is refused when the target is
chezmoi-MANAGED.** The pre-pass writes the target before
`compile_user_scope` runs its `_drift_dirty_guard` (`chezmoi.py:217-233`,
`chezmoi diff <target>`), so on a MANAGED target our own write would be
read as pre-existing drift and `ChezmoiAbort` **after** the ledger commit
— an unrecoverable loop, since `recompile` would hit the same thing. The
refusal is pre-ledger, under the existing `check_dirty` guard, and fires
**only** when `rules_paths` is non-empty. Unpathed user rules under
chezmoi keep working exactly as today (criterion **A11**), because the
pre-pass writes nothing when `U(T) == ()` and the file has no `paths:`.

Chezmoi is retired on this host (`user_scope_capability` returns
ABSENT/UNMANAGED), so this refusal is unreachable in practice — but the
MANAGED path is live code with live tests (`test_a2_rules_local.py`
obligations 11 and 12), and shipping a post-ledger abort into it would be
a real regression.

### 3.5 The exact `verbs.py` footprint

Four functions, no restructuring, nothing renamed or moved:

| Function | Change |
|---|---|
| `_resolve_rules_target` (`:747`) | the two refusals of §3.4 |
| `_apply_target` (`:1602`) | `notes` kwarg; bind `_compile_set` once per branch; the pre-pass call in each of the two rules-bearing branches; the `changed` fold on the project branch; append `PathsResult.notes` |
| `_host_phase` (`:1784`) | one kwarg at the `_apply_target` call (`:1816`): `notes=warnings` |
| `recompile` (`:3416`) | one kwarg at the `_apply_target` call (`:3609`): `notes=result.warnings` |

Plus `from dataclasses import … replace` on the existing import line, and
the new `compilers` imports.

**Nothing else in `verbs.py` is touched.** In particular
`_validate_project_globs`, `_resolve_target`, `route`, `route_direct`,
`_compile_set`, `_routed_to` and `TargetSpec` are unchanged — if a build
finds itself wanting to change any of them, stop and report it (§7.5).

---

## 4. Acceptance

**These criteria are the contract.** Every criterion asserts against
**bytes on disk**, not against a returned object, except where it names
`PathsResult` explicitly. For every assertion the builder must ask: *what
does this print when the thing it checks is absent?* — and where that
answer is "pass", the criterion below already names the pairing that
fixes it.

**A1 — project-scope pathed route emits to disk.** Route a project
record with `rules_paths: ["src/**/*.ts"]` (with the file present so the
zero-match check passes). `<host>/.claude/rules/<topic>.md` exists; its
leading frontmatter, **re-parsed with `ruamel.yaml.YAML(typ="safe")`**,
is `{"paths": ["src/**/*.ts"]}`; the record's `(lrn-…)` marker is inside
the managed section below it.

**A2 — user-scope pathed route emits to disk.** Same, at
`<user rules dir>/<topic>.md`, via a `user_claude_md` override and
`chezmoi_bin="chezmoi-definitely-absent"`. This is S-23's primary user
tier; it must be asserted independently of A1 because it takes a
different write path (`compile_user_scope`).

**A3 — the union is deduped and sorted.** Two records routed to one
topic with `["b/**", "a/**"]` and `["a/**", "c/**"]` yield exactly
`["a/**", "b/**", "c/**"]` on disk, and both record ids appear in the
section.

**A4 — absorption, with its own fail-open control.** A third record with
no `rules_paths` routed into that same topic leaves the file with **no
`paths:` key**; **and in the same test** a second topic that kept its
globs still carries its `paths:` on disk. Without the second assertion,
"no `paths:` key" passes on a build that never emits anything anywhere.
The route's `result.warnings` contains the absorption note naming the
globless record's id.

**A5 — retirement narrows the union.** With two pathed records in one
topic, supersede one; the surviving `paths:` is the survivor's globs
alone. This is what proves emission reads `C(T)` and not
`spec.rules_paths` (§3.1a).

**A6 — `recompile` repairs a hand-edited `paths:` and commits it.**
Hand-edit the emitted `paths:` to a different list, run `recompile`: the
file's `paths:` is back to `U(T)`, the `RecompileEntry` reports
`changed=True`, a commit sha is present, and the host repo's HEAD commit
touches that file. The section is byte-identical across the edit, so this
criterion fails without the §3.3 `changed` fold.

**A7 — foreign frontmatter survives.** A leading block carrying a comment
and a non-`paths` key, plus a stale `paths:`, is rewritten with `paths:`
corrected and the comment and the other key preserved byte-for-byte.

**A8 — a corrupt leading block refuses.** A rules file starting with
`---` and no terminator raises `CompileError`; at route time this becomes
the existing "HOST PHASE FAILED … run `self-learn recompile`" warning and
the ledger record stays `routed`.

**A9 — the dead-glob positive control.** Project scope, glob matching
nothing: without `--allow-empty-glob` the route **refuses**, the record
stays in `pending/`, and **no rules file is created** (the check can
fail). With the flag: the route lands, the dead glob is on disk in
`paths:` verbatim, and `routing["allow_empty_glob"] is True` — so a dead
glob is never indistinguishable from a live one in the record.

**A10 — absolute and `~` globs are refused at both scopes**, pre-ledger
(the record stays pending, nothing is committed), at user scope as well
as project scope. Positive control in the same test: the same route with
the pattern made relative succeeds and emits.

**A11 — chezmoi MANAGED.** With the PATH-shimmed fake chezmoi reporting
MANAGED: a **pathed** user-scope route refuses pre-ledger with a message
naming chezmoi; an **unpathed** user-scope rules route succeeds and its
chezmoi call sequence is unchanged from today's.

**A12 — every non-rules target is byte-identical.** Routing to plain user
`CLAUDE.md`, project `CLAUDE.md`, `SKILL.md`, `CLAUDE.local.md` and a
new-skill target emits no frontmatter and produces the same bytes as
before this unit. **Positive control in the same test:** one rules route
in the same fixture *does* carry frontmatter, so "no frontmatter
anywhere" cannot pass.

**A13 — idempotence.** A second `recompile` immediately after A6 writes
nothing and commits nothing (`changed=False`, no new sha).

**A14 — caps unchanged.** `SectionResult.word_count` and `over_cap` for a
pathed rules file equal those for the byte-identical unpathed file:
frontmatter is never counted as section content.

**A15 — the drift seam.** `paths_frontmatter_drift(text, records)`
returns non-`None` for a hand-edited `paths:`, non-`None` when the
frontmatter is **absent** while records carry globs (the positive control
— an "absent" reader that always returns `()` must not read as clean),
and `None` after the repair.

**A16 — the emitted YAML is valid, checked by a different loader.** A
glob beginning with `*` (`**/*.py`) round-trips through
`YAML(typ="safe").load()` back to the identical string. Asserting a
substring of the file text would pass on an unquoted, alias-broken
emission.

---

## 5. Mutation plan

A blind reviewer will run these. Each is a **one-line** edit to
production code that must make **exactly** the named test fail.

| # | Mutation | Test that must fail |
|---|---|---|
| M1 | `expected_paths`: delete the absorbing rule (§2 rule 2) and return the union anyway | A4 |
| M2 | `expected_paths`: replace `tuple(sorted({…}))` with an unsorted, undeduped tuple | A3 |
| M3 | `apply_paths_frontmatter`: return the result without the `path.write_text(...)` | A1 (**the "validated but never written" control**) |
| M4 | `apply_paths_frontmatter`: skip the delete-the-key branch, leaving a stale `paths:` when `U(T) == ()` | A4 |
| M5 | `apply_paths_frontmatter`: build the block from scratch instead of round-tripping the loaded mapping | A7 |
| M6 | `apply_paths_frontmatter`: return `PathsResult(..., notes=())` | A4 (the warnings assertion) |
| M7 | `apply_paths_frontmatter`: return early with `changed=False` instead of raising on an unterminated block | A8 |
| M8 | `_apply_target`: delete the `dataclasses.replace(…, changed=True)` fold | A6 |
| M9 | `_apply_target`: delete the pre-pass call from the **user** branch only | A2 |
| M10 | `_apply_target`: delete the pre-pass call from the **project** branch only | A1 |
| M11 | `_apply_target`: compute the pre-pass from `spec.rules_paths` instead of the compile set | A5 (and A6) |
| M12 | `_resolve_rules_target`: delete the absolute/`~` refusal | A10 |
| M13 | `_resolve_rules_target`: delete the chezmoi-MANAGED refusal | A11 |
| M14 | `read_paths_frontmatter`: `return ()` unconditionally | A15 |
| M15 | `paths_frontmatter_drift`: compare `read_paths_frontmatter(text) == expected` instead of the raw value (§2 *agreement*) | A15 (the `paths: []` / scalar leg) |
| M16 | `_host_phase`: drop `notes=warnings` at the `_apply_target` call | A4 (the warnings assertion) |

**M6 and M16 both map to A4's warnings assertion by design** — A4 asserts
both the disk state and the note, so the note has an owner at each end of
the channel. If a builder splits them into two tests, the mapping must be
updated in the same commit.

**Two mutations that must NOT be proposed** because they pass: adding
`rules_paths` threading to `recompile`'s `_resolve_target` call, and
adding it to `_retirement_preflight`. Both are inert under this design
(§3.1a) and re-arm refusals those sites deliberately disabled.

---

## 6. Builder decisions, made here rather than left open

1. **Union semantics: widen, never split.** §2.1. One topic is one file.
2. **A globless record makes the whole file unpathed.** §2 rule 2, §2.2.
   Kept from r2, surfaced loudly, never silently reversed.
3. **The compiler owns only `paths:`**, not the whole frontmatter block.
   Foreign keys and comments survive via a ruamel round-trip. Rationale:
   the alternative — owning the whole block — silently deletes a human's
   edit, which is the defect class this campaign exists to stop, and
   `records.py:104-117` already made exactly this call once in this
   codebase.
4. **A hand-edited `paths:` is drift, and the repair is the next compile
   (route or `recompile`) — which now also commits it** (§3.3 fold).
   `selftest`'s drift *report* is a named handoff, §7.3 — this unit does
   not claim it.
5. **Emission derives from `C(T)`, never from `TargetSpec.rules_paths`.**
   §3.1. This is the decision that makes `recompile` and retirement
   correct with no change at either site.
6. **Pre-pass, not a compiler parameter.** §3.1b, forced by
   `chezmoi.py` being outside the file set — and better anyway, since it
   leaves `compile_managed_text`/`compile_managed_file` byte-identical
   for every existing caller (A12).
7. **Absolute / `~` globs are refused, at both scopes**, on the measured
   never-fires finding plus the `root_dir`-ignored fail-open. §3.4(1).
8. **A pathed user-scope route refuses on a chezmoi-MANAGED target.**
   §3.4(2). Unpathed user rules are untouched.
9. **Surfacing rides `result.warnings`**, via a `notes` kwarg on
   `_apply_target`. No `cli.py`, `ui/` or `chezmoi.py` change is needed
   or permitted for this unit.
10. **Where the tests live:** `tests/test_a2_rules_local.py` (this is A2's
    surface, and its `Env`/`chezmoi_shim`/`seed_*` fixtures and the
    obligation-numbered class layout already exist), with the pure
    `expected_paths` / `read_paths_frontmatter` /
    `paths_frontmatter_drift` unit tests in `tests/test_compilers.py`.
    Continue the existing "Obligation N" class naming from where
    `test_a2_rules_local.py` stops (19).
11. **`str` comparison of globs, no normalization.** Globs are stored and
    emitted verbatim; `"src/**"` and `"./src/**"` are two different globs
    in the union. Normalizing would be inventing a matcher semantics we
    have not measured.
12. **Suite baseline for this unit**, measured 2026-08-02 with a scratch
    `XDG_CACHE_HOME`: `cd plugins/self-learn/cli && .venv/bin/python -m
    pytest -q` → **1133 passed, 5 skipped**, rc 0 read unpiped. Any other
    failure is this unit's.

---

## 7. Out of scope, and the residuals this unit accepts

### 7.1 ACCEPTED residual — the Grep/Glob-only delivery hole

**Injection fires on `Read`.** `Edit` is covered in practice because
Claude Code requires a Read first, but **a session that only ever `Grep`s
or `Glob`s a matching file never has the rule injected at all.** A
lesson routed to PATHED is therefore *not* delivered to a
search-only workflow, and nothing in self-learn can observe that.

This is accepted as residual, not deferred, because **no code in this
unit or any other can close it** — injection belongs to Claude Code. It
is recorded here in the same terms as the defect this campaign exists to
fix so that it cannot be re-discovered later as a surprise:

> A PATHED destination looks like delivery and, for a Grep/Glob-only
> workflow, silently is not.

Two things follow, and both are named rather than built:

- **Doctrine, `U-composer`.** The T2 gate must not route a lesson to
  PATHED on "does it only matter for certain files?" alone. S-23's rider
  already adds *"does the trigger fire at or after first contact with
  those files?"*; this adds *"will the work that trips this lesson
  actually **open** one of those files, or only search them?"* A lesson
  about, say, grepping conventions is precisely the case PATHED cannot
  serve.
- **No in-band warning is emitted.** Considered and rejected: writing a
  YAML comment into the frontmatter to carry the caveat would depend on
  Claude Code's frontmatter parser tolerating comments, which **has not
  been measured on this host**, and a rules file that fails to parse is a
  worse outcome than an unstated caveat.

### 7.2 ACCEPTED residual — user-scope globs have no dead-glob guard

Project scope refuses a zero-match glob at route time and re-asserts it
in `selfcheck` (`selfcheck.py:374-399`). User scope has **no canonical
tree** to check against (measurement 1.2: the glob resolves against
whatever repo the session runs in), so `_resolve_rules_target` runs only
the shape check — and S-23 has just made user scope a primary PATHED
tier. A misspelt user-scope glob therefore fires nowhere and reports
nothing.

Mechanical guards that *do* apply, and are all this unit can offer:
the proposal-schema shape check (`ledger_ops.py:613-623`) and §3.4(1)'s
absolute/`~` refusal. Beyond that it is the human's read of the card.
This is a *new* gap created by S-23's promotion, and it belongs in
`03-decisions.md` as an accepted residual with this reasoning.

### 7.3 Handoffs — named, with the change, not silently assumed

- **`selfcheck._check_drift` must learn the frontmatter.** The seam is
  built and tested here (`paths_frontmatter_drift`, criterion A15); the
  wiring is three lines inside the existing
  `if routing.get("variant") == "rules"` block at `selfcheck.py:383`:
  read the target text, call `paths_frontmatter_drift(text, C(T))`,
  append the message to `failures`. It is **not** built here because
  `selfcheck.py` is outside this unit's file set and `U-reach` is already
  in that file this wave. Until it lands, a hand-edited `paths:` is
  repaired at the next route/`recompile` (A6) but is **not reported by
  `self-learn selftest`** — state this plainly wherever the unit is
  recorded as BUILT.
- **The absolute/`~` glob check's better home** is
  `ledger_ops._validate_rules_fields` (proposal-validation time, where
  the human sees the refusal before routing). That file is `U-schema`'s.
  The route-time refusal built here is correct and sufficient; moving it
  later is a simplification, not a fix.

### 7.4 Owned by other units — do not build here

- **When to choose PATHED.** `U-composer`'s doctrine rewrite, including
  S-23's at-or-after-first-contact rider and §7.1's search-only rider.
  This unit builds the mechanism only.
- **The user-scope destination menu**, `ui/models.py`, and deleting the
  dead chezmoi `reference` refusal at `verbs.py:950-955` — `U-demand-user`.
- **Pointer emission and the cap-exempt `pointer_line`** — `U-pointer`
  (`compilers.py` again; sequence, do not overlap).
- **The reachability selftest, the `route` telemetry kind, `routing.by`**
  — `U-reach`.
- **Per-topic splitting / a size flag on a rules file** — r2 §5's
  deferred human decision.

### 7.5 The boundary with `U-demand-user`, stated from this side

`U-demand-user` was re-scoped by S-23 to give user scope a cheap surface,
and that surface is PATHED — the same tier this unit builds. The line:

- **This unit owns everything that decides what a rules file *contains*
  and *is*:** the `paths:` frontmatter and its ownership rules, the union
  register §2, the two route-time glob refusals, the compile-time
  surfacing, and the drift seam. In files: all of `compilers.py`'s
  additions, plus the four `verbs.py` functions in §3.5.
- **`U-demand-user` owns everything that decides what a human can *pick*:**
  the destination menu (`_SCOPE_DESTINATIONS`, `ui/models.py:98-102`,
  where `"user"` is the one-element `("claude-md",)`), the dead
  `reference`-at-user-scope refusal (`verbs.py:950-955`), and any
  proposal/card surface that offers user-scope cheap destinations.
- **There is no dependency from this unit to that one.** Verified: a
  user-scope rules route already resolves and lands today —
  `_resolve_rules_target`'s user branch (`verbs.py:776-791`) is complete,
  and two existing tests route user-scope rules end to end
  (`test_a2_rules_local.py::TestObligation15FirstRouteBootstrap::
  test_user_leg_creates_dir_and_file` and
  `test_user_scope_glob_is_parse_only_never_zero_match`). **U-pathed can
  ship before U-demand-user**, which matches the campaign's "sequence
  U-demand-user after U-pathed".
- **The one thing that must agree.** `U-demand-user` must not introduce a
  second definition of the user rules path. `_user_rules_dir`
  (`verbs.py:663-667`) resolves off the same possibly-test-overridden
  `user_claude_md` target every other user-scope call site uses; any new
  menu entry must reach the file through `_resolve_rules_target`, never
  by constructing `~/.claude/rules/…` a second time. `selfcheck.py:220`
  already hardcodes `DEFAULT_USER_CLAUDE_MD.expanduser()` for this
  resolution — a pre-existing second path that is correct only because
  the default is correct; neither unit should add a third.

---

## 8. What this spec contradicts

Recorded because r2 was authored 2026-07-27 and several of its claims
have since been found false, and because a spec that silently diverges
from its reference is how a fabricated pin gets made.

1. **r2 B10: "`compile_managed_file` gains `rules_paths: tuple[str, ...] |
   None`."** Rejected. It strips the frontmatter on every `recompile`
   (`verbs.py:3535-3539`) and on retirement (`verbs.py:1543-1549`), and
   it cannot reach user scope without editing `chezmoi.py`. §3.1.
2. **r2 B10: "the compiler flags this on the route result."** There is no
   such channel — `_apply_target` has no warnings list. Built here as a
   `notes` kwarg on three call sites. §3.3.
3. **r2 §5 / A2 §5.1: `_validate_project_globs` is the zero-match guard.**
   It fails open on absolute patterns: `glob.glob` **ignores `root_dir`**
   when the pattern is absolute (verified this session —
   `glob.glob("/etc/host*", root_dir="/tmp/globtest")` returned `/etc`
   entries), so a pattern that the 2026-07-28 canary measured as *never
   firing* passes the guard today. §3.4(1).
4. **r2 §8 item 4: "PATHED load semantics remain empirically
   unverified."** Closed 2026-07-28 — verified working at both scopes.
   The campaign playbook §7 already records this; r2's own §8 does not,
   and a reader of `misc/routing-procedure-r2.md` alone would still
   believe B10 is gated.
5. **Campaign §2's unit title says "drift-check awareness."** Not fully
   deliverable in this file set: the drift check is `selfcheck.py`. What
   ships is the seam plus repair-on-compile; the `selftest` report is a
   named handoff. §7.3. This is a scope statement, not a scope cut — the
   alternative is a unit that claims a check it did not build.

Nothing here contradicts **S-23**. §2.2, §3.4(1) and §7.2 all follow from
its two halves and from the measurements they rest on.

---

## 9. Revision history

- **r1** — this document, 2026-08-02. Written against the code read this
  session (`compilers.py` in full; `verbs.py` §§215-280, 477-620,
  645-970, 1313-1380, 1500-1700, 1774-1870, 1955-2115, 2310-2350,
  3416-3640; `selfcheck.py` §§180-470; `chezmoi.py` §§150-360;
  `ledger_ops.py` §§566-625). Four empirical checks run in the sandbox
  and reported inline: marker-contract preservation of leading
  frontmatter, ruamel quoting and round-trip, `glob` ignoring `root_dir`
  for absolute patterns, and the CLI suite baseline.
