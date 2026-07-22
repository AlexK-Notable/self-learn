# Spec A — `claude-md` parameterization: rules, local, and honest labels

Status: DRAFT — for blind gate.
Rev: 2026-07-21 — **re-anchored against post-C2 HEAD 97726df**. C2
(commits 027fc7f/97726df) converted chezmoi from a hard dependency into
a *detected capability* for USER-scope routing (`user_scope_capability`
→ ABSENT/UNMANAGED/MANAGED; `compile_user_scope` writes
`~/.claude/CLAUDE.md` directly when absent/unmanaged, syncs only when
managed). This pass: (1) every code anchor re-verified and corrected
against current code; (2) the "user scope = the *chezmoi-managed*
CLAUDE.md" premise reconciled to *capability-aware* in §2.1 / §4 / F-2
(new rider P-A2b); (3) all pins P-A1..P-A13 re-checked — **none
invalidated by C2**; P-A13's unguarded-else fallthrough re-confirmed at
`verbs.py:600`. Build-sequencing recommendation (see re-scope report):
split into **A1** — §8 rows 1-3 + P-A11/P-A12, scope-aware labels +
always-show-path, which alone closes F-1 (the user's actual bug), fast
and low-risk — and **A2** — the rules/local/glob machinery (§2-§7, §9).
The label resolver's signature widens to *scope* in A1 and, additively,
to *variant* in A2; nothing in A1 depends on A2.
Origin: user feedback 2026-07-19, opening on a mislabeled destination
("i think we should have a user scope destination of some kind") and
widening to a full destination audit ("let's enumerate ALL destinations
now. what surfaces can lessons land on currently, and what are we
missing").

Companion: **Spec B** (`permissions.deny` destination) is deliberately
split out — independent, higher risk, its own gate. Nothing here depends
on it.

---

## 0. Rulings folded in

Taken live during the audit; all bind this spec.

| # | Ruling | Words |
|---|---|---|
| R-1 | Labels must be **clear and distinct** per the official Claude Code taxonomy | "i just need it to be clear and distinct. claude.mds can live in different places and have different scope. it's not just project and user level." |
| R-2 | `rules` is a **scope parameterization of `claude-md`**, not a new destination | "rules is a scope parameterization of claude-md" |
| R-3 | **Path-scoped rules are in scope** | "yes, we go with path-scoped rules" |
| R-4 | The **analyst proposes** the path/glob; the **human concurs or not** | "agent suggest path, glob, etc. user can concur or not" |
| R-5 | Auto-memory is a **source, not a destination** — lifecycle already closed by S-13/S-14 | "the auto-memory handling we landed on was using it as a source of lessons during mining, then when a given auto-memory sourced lesson graduates we can clean it out" |

R-5 is a *confirmation* of existing ratified doctrine (S-13, S-14;
O-2/O-5 settled 2026-07-12), verified against `import_memory.py` and the
shipped `self-learn import --memory` / `self-learn prune-memory` verbs.
It removes auto-memory from the open-questions list; **no work in this
spec**. Recorded here so a future reviewer does not re-raise it.

### 0.1 A correction that survived into the design

The R-2 ruling was reasoned from a premise the official docs contradict:
that rules are "a source of `@imports` that the agent can be directed to
when relevant… supporting documentation." Verified against
`code.claude.com/docs/en/memory`:

- *"Rules without `paths` frontmatter are **loaded at launch** with the
  same priority as `.claude/CLAUDE.md`."*
- *"Path-scoped rules trigger when Claude reads files matching the
  pattern"* — automatic on file access, not on agent judgment.
- *"Rules load into context every session or when matching files are
  opened. For task-specific instructions that don't need to be in
  context all the time, **use skills instead**."*
- On imports: *"Imported files are expanded and loaded into context at
  launch"* / *"splitting into `@path` imports helps organization but
  doesn't reduce context."*

**The ruling survives the correction** — the docs independently support
R-2, since an unpathed rules file has *"the same priority as
`.claude/CLAUDE.md`"*, which is precisely what makes it a
parameterization rather than a category. But the *discriminator* changes,
and §3 is built on the corrected facts, not the original premise.

**Pin (P-A1).** An unpathed rules file costs exactly what the same text
in CLAUDE.md costs. Rules relieve the **entry cap**, never the **context
cost**. Doctrine must say this in terms an analyst cannot misread, or
`rules` becomes a laundering route around the overflow cap
(`02-schema.md` §4).

*Provenance:* every quote in this section was independently re-fetched
and verified character-by-character against the live page (2026-07-19,
second pass by a separate agent). Three passages converge on the
unpathed-loads-at-launch fact, so it is not a single-sentence reading:
the "same priority as `.claude/CLAUDE.md`" line, the "every session or
when matching files are opened" Note, and "Rules without a `paths` field
are loaded unconditionally and apply to all files."

**Caveat (P-A1b) — a project rule can be silently excluded.** Project
rules "are skipped if you exclude `project` from `--setting-sources`".
So "loads every session" is conditional on the reader's settings-source
configuration, which self-learn neither controls nor can observe at
route time. This is a **second** silent-non-firing vector alongside the
dead glob (§5): a correctly-written, correctly-globbed project rule can
still never load. Doctrine must not promise project-scope rules fire
unconditionally.

---

## 1. The three findings this spec closes

### F-1 — one label covered three different files

`_GROUP_LABELS["claude-md"] = "Project instructions"` (ui
`models.py:182`) is scope-blind, but `claude-md` already resolves to
three distinct targets by scope
(`plugins/self-learn/cli/src/self_learn/verbs.py:575-603`):

| scope | actual target |
|---|---|
| `user` | `~/.claude/CLAUDE.md` |
| `project` | `<host repo>/CLAUDE.md` |
| `skill:<name>` | `<skills root>/CLAUDE.md` |

A user-scope record — correctly headed for the global file — displayed
as "Project instructions". The routing was never wrong; the gloss was.
This is the defect the user actually saw, and it is what made a working
user-scope destination look absent.

### F-2 — user scope has exactly one always-loaded instruction surface

```python
# plugins/self-learn/ui/src/self_learn_ui/models.py:95-99
_SCOPE_DESTINATIONS: dict[str, tuple[str, ...]] = {
    "skill":   PARAMETER_FREE_DESTINATIONS,   # = ("skill-md","claude-md","reference"), models.py:85
    "project": ("claude-md", "reference"),
    "user":    ("claude-md",),
}
```

*(Anchor note: the `skill` row is now the named constant
`PARAMETER_FREE_DESTINATIONS` (`models.py:85`), not the inline literal
the earlier draft quoted; the value is unchanged.)*

**Attribution pin.** This dict is **UI code**, and by its own docstring
it is the CLI's scope rules "projected onto the parameter-free set" — a
*derivative*, not the authority. The authority is
`plugins/self-learn/cli/src/self_learn/verbs.py::_resolve_target`. A
builder must change the CLI first and let the projection follow.

**Precision on the headline.** "Exactly one destination" is true of the
parameter-free `o`-cycle set only. At the CLI, `_resolve_target`'s
`new-skill` branch (`verbs.py:605-648`) has **no scope gate at all** —
it checks for a name and a registered skills root, nothing else — so a
user-scoped record *can* route to `new-skill`. The claim this spec
actually rests on is narrower and survives: user scope has exactly one
**always-loaded instruction surface**. `new-skill` mints a
load-on-invocation artifact, not an always-loaded one.

`reference` is refused at user scope (`verbs.py:657-662` — "the user
host is the chezmoi-managed CLAUDE.md, it has no references dir"; note
it is the `else` after the `skill:` and `project` branches, not an
explicit user-scope check). So every universal lesson competes for one
capped (`DEFAULT_MAX_ENTRIES = 10` / `DEFAULT_MAX_WORDS = 150`) section
of one file that loads in every session of every project.

**C2 reconciliation.** That refusal message's "chezmoi-managed
CLAUDE.md" clause is now **stale wording in the source itself** — C2 did
not update it. Post-C2 the user host is `~/.claude/CLAUDE.md`, which may
or may not be chezmoi-managed (§2.1). The *refusal* still holds — the
real reason is doc 13 §2: there is no user-scope references dir,
independent of chezmoi — but a builder quoting this comment must not read
it as a live claim that the user file is definitionally chezmoi-managed.

Doctrine §3 makes "prefer the narrowest surface that still fires" the
system's **one standing tiebreak** — and at user scope there is nothing
to tie-break against. This is not a hypothetical: the live record
`lrn-5d0c592a` carries the rationale *"user-scope CLAUDE.md is the
narrowest surface that reliably fires… despite the general bias against
user scope."* The analyst was not hedging; it had correctly identified
that the only user-level surface is also the most expensive one.

### F-3 — surfaces we never modelled

Verified against the official memory documentation:

| Surface | Path | Status here |
|---|---|---|
| User rules | `~/.claude/rules/*.md` | **added** (§2) |
| Project rules | `./.claude/rules/*.md` | **added** (§2) |
| Local instructions | `./CLAUDE.local.md` | **added** (§2) |
| Nested CLAUDE.md | `<subdir>/CLAUDE.md` | **considered and rejected** (§10) |
| Managed policy | `/etc/claude-code/CLAUDE.md` | **explicit non-target** (§10) |

---

## 2. The taxonomy: surface × scope

The current enum conflates two independent axes. `claude-md` silently
means "one of three files, depending on scope." Adding `rules` and
`local` naively deepens that. The honest decomposition:

- **scope** — *whose, and where* (`user` / `project` / `skill:<name>`)
- **variant** — *what kind of always-loaded surface* (the main file, a
  rules topic file, or the personal per-project file)

`claude-md` gains a **variant** parameter. The enum stays at five.

### 2.1 The resolution table (replaces the informal §1 doctrine row)

| variant | scope | resolved target | loads |
|---|---|---|---|
| *(none)* | `user` | `~/.claude/CLAUDE.md` | every session, everywhere |
| *(none)* | `project` | `<host repo>/CLAUDE.md` | every session in repo |
| *(none)* | `skill:<n>` | `<skills root>/CLAUDE.md` | every session in canon repo |
| `rules:<topic>` | `user` | `~/.claude/rules/<topic>.md` | every session (unpathed) / on matching file read (pathed) |
| `rules:<topic>` | `project` | `<host repo>/.claude/rules/<topic>.md` | as above, **for every teammate** |
| `rules:<topic>` | `skill:<n>` | **deferred** — see §9 | — |
| `local` | `project` | `<host repo>/CLAUDE.local.md` | every session in repo, **you only** |
| `local` | `user` / `skill:<n>` | **refused** — no such file exists | — |

**Reconciliation (C2, 2026-07-21).** The user surface is still exactly
`~/.claude/CLAUDE.md` — the same one file — but it is no longer
*definitionally* "the chezmoi-managed CLAUDE.md". `compile_user_scope`
(`chezmoi.py:242`) is now **capability-aware** via `user_scope_capability`
(`chezmoi.py:188` → ABSENT / UNMANAGED / MANAGED): it writes the file
DIRECTLY when chezmoi is absent or the target is unmanaged, and runs the
re-add/commit/push sync tail (surfacing `UserScopeResult.sync_warning`
on failure, threaded out through `verbs.py::_host_phase`) ONLY when the
target is MANAGED. The file *identity* and the one-always-loaded-surface
claim (F-2) are unchanged; only the sync mechanism became conditional.

**Pin (P-A2b) — user-scope `rules` inherits the C2 capability path, and
diverges from CLAUDE.md on a managed setup.** A user-scope `rules:<topic>`
target is `~/.claude/rules/<topic>.md`, a NEW file in the same
`~/.claude` tree. Routed through `compile_user_scope` with that target it
gets capability-aware writing **for free** — the machinery already keys
on the per-target capability, so no bespoke writer is needed, and the
builder MUST reuse it rather than invent one. But `chezmoi source-path`
on a freshly-minted file returns non-zero, so a new user rule reads
**UNMANAGED even when `~/.claude/CLAUDE.md` itself is MANAGED** (chezmoi
does not auto-track new files). Consequence: by default a user rule is
written directly and does **not** propagate across machines until the
human `chezmoi add`s it, whereas its sibling CLAUDE.md syncs. This is a
real coherence gap, not a bug — it follows C2's "write directly when
unmanaged, silently" doctrine (rows 1-2) — but the label/detail (§8) for
an unmanaged user rule should read "loads every session (this machine)"
rather than imply cross-machine reach it does not yet have.

**Pin (P-A2).** `local` at project scope is the only personal
per-project surface in the system. Today such a lesson has two bad
homes: the team-shared `CLAUDE.md` (pollutes others' context) or user
scope (over-fires in every project). Both are wrong; this is the third
option.

**Pin (P-A3).** `CLAUDE.local.md` must be gitignored to be correct. The
compiler MUST verify `.gitignore` covers it and refuse with a plain-words
error naming the fix if not — routing a "personal" lesson into a tracked
file publishes it to the team, which is a silent privacy failure, not a
cosmetic one.

---

## 3. The discriminator: which variant wins

The corrected facts (§0.1) give exactly one real decision.

**Does the lesson have a file-path firing condition?**

- **Yes** → `rules:<topic>` **with** `paths:`. Genuinely narrower —
  loads only when Claude touches matching files. This is the *only* new
  capability in the parameterization.
- **No** → `claude-md` (no variant) vs. unpathed `rules:<topic>` is
  **not a cost decision**; identical tokens either way. Decide on
  organization and cap-relief alone.

**This discriminator already exists in the corpus.** Doctrine §2 routes
`behavior / anti-pattern` to `hook` when the mistake is "mechanical and
tool-detectable (**a file-path pattern**, a command shape)". The same
signal — a trigger that names paths — selects a path-scoped rule. A
trigger that names a *moment* ("about to spawn a subagent") has no glob
and stays in `claude-md`.

Worked negative case, from the live queue: `lrn-5d0c592a` fires at
subagent-spawn time. No file pattern exists, so no glob exists, so a
rules file buys nothing but tidiness. It stays `claude-md` at user
scope. An analyst that proposes `rules` here has misread §3.

**Pin (P-A4).** The narrowest-surface bias (§3 of doctrine) now has a
genuine ranking at user scope, for the first time:

```
pathed rules  <  unpathed rules ≈ CLAUDE.md
```

`≈` is deliberate: equal context cost, differing only in entry-cap
pressure. Doctrine MUST NOT present unpathed rules as narrower.

---

## 4. Grammar and schema

### 4.1 `--dest` grammar

`_parse_dest` (`verbs.py:404`) returns `(destination, qualifier)` — a
**single** qualifier slot, currently serving `reference:<file>` and
`new-skill:<name>`. Extended:

```
claude-md                    → ("claude-md", None)
claude-md:rules:<topic>      → ("claude-md", "rules:<topic>")
claude-md:local              → ("claude-md", "local")
```

`<topic>` reuses `validate_skill_name`'s slug discipline (lowercase,
hyphenated, no traversal) — a topic becomes a filename, so the same
injection surface applies. Empty topic → `VerbError`.

**Caveat:** `validate_skill_name`'s error string reads "new-skill name …
must be kebab-case". Reused verbatim for a rules topic it misnames the
thing the user got wrong (Y-9). Either parameterize the noun or raise a
topic-specific message.

**Build obligation — FOUR enumerations of the destination grammar must
move together.** They agree today and nothing enforces that they keep
agreeing:

| # | Site | Form |
|---|---|---|
| 1 | `cli/.../ledger_ops.py:73` | `PROPOSAL_DESTINATIONS` tuple (canonical) |
| 2 | `cli/.../analyst.py:91` | analyst prompt template |
| 3 | `ui/.../proposals.py:92` | `_DEST_RE` regex |
| 4 | `skills/self-learn/references/routing-doctrine.md:98` | doctrine |

Site 3 is the sharp one: `_DEST_RE` currently matches
`reference(:.+)?|new-skill:.+` but nothing of the form
`claude-md:<variant>`. Ship the new grammar without updating it and
**every proposal using it fails validation** while the CLI accepts the
same string — a split-brain the other three sites would not reveal.

**Pin (P-A5).** Globs do **not** ride in `--dest`. They contain `/`,
`*`, `[`, and `,`; a `:`-delimited value cannot carry them unambiguously.
Globs live in the proposal YAML only.

**Consequence, and it is a feature.** A path-scoped rule **cannot** be
routed by bare `--dest` with no proposal — there is nowhere for the
globs to come from. R-4's "user can concur or not" becomes *structural*
rather than procedural: reaching this destination requires a proposal a
human read. Bare `--dest claude-md:rules:<topic>` with no proposal
yields an **unpathed** rule, which is the honest fallback (it still
loads, just unconditionally).

### 4.2 Proposal schema addition (02 §1)

```yaml
destination: claude-md
variant: rules            # optional: rules | local | (absent)
rules_topic: subagents    # required iff variant == rules
rules_paths:              # optional; absent ⇒ unpathed rule
  - "src/**/*.ts"
  - "lib/**/*.ts"
```

`rules_paths` is the analyst's **proposal** (R-4). The card renders the
globs verbatim so the human concurs on the actual strings, never on a
paraphrase. Editing them is an ordinary Discuss-path edit, which
re-runs `proposal validate`.

**Pin (P-A6).** `variant` absent ⇒ today's behavior, byte-identical.
Every existing proposal on disk stays valid and routes exactly as
before. This spec adds no migration.

*(C2 rider, 2026-07-21.)* "Today's behavior" for a variant-absent
**user** record is now the post-C2 capability-aware path
(`compile_user_scope`: direct write when absent/unmanaged, re-add/commit/
push when managed). Byte-identity is asserted against **that** post-C2
baseline, not the pre-C2 always-chezmoi one — test obligation 1 (§11)
must exercise the ABSENT/UNMANAGED/MANAGED branches. The variant-carrying
user-scope rules route reuses the SAME write path (P-A2b): it adds a
target, never a new write mechanism.

---

## 5. Glob validation — the silent-failure guard

**This is the one real hazard the ruling introduces.** Every existing
destination is verifiable by reading the target file. A path-scoped rule
that never matches is indistinguishable from one that works: no error,
no warning, the lesson simply never loads.

The docs document a sharper version: a pattern with an unparseable `[`
(e.g. `photos [2024/**`) *"is invalid: it matches nothing, and the
rule's other patterns keep working"* — a **partial** silent failure,
where the rule appears to work while one glob is dead.

### 5.1 Route-time validation (blocking)

Before any commit, for each entry in `rules_paths`:

1. **Parse** the glob. Unparseable → `VerbError` naming the pattern and
   the `[`-escaping rule.
2. **Match** it against the resolved host repo. **Zero matches → refuse**
   with a plain-words error (Y-9): which pattern matched nothing, and
   that a rule with a non-matching pattern never fires.

Refusal, not warning. A warning on a silent-failure class is a warning
nobody reads.

**Pin (P-A7).** Validation runs **per pattern**, not per rule. A rule
with three globs where one is dead must fail on that one — this is
exactly the documented partial-failure mode, and a rule-level "did any
match?" check would pass it.

Sanctioned escape: `--allow-empty-glob`, for the legitimate
write-the-rule-before-the-files case. Explicit, logged in the routing
metadata, never the default.

### 5.2 selfcheck re-assertion (drift)

`selfcheck.py` check (d) already verifies every routed record is present
in its canon. Extended for `variant: rules`: the topic file exists, the
`(lrn-…)` marker is inside it, **and** every recorded glob still matches
≥1 file. A glob goes stale when files move — the same class as the
existing drift check, and the same fix path (`self-learn recompile`
surfaces it; the human retargets).

---

## 6. Granularity and caps

**Pin (P-A8).** One topic file holds **many** lessons, in a
marker-bounded managed section, under the existing `DEFAULT_MAX_ENTRIES
= 10` / `DEFAULT_MAX_WORDS = 150` cap — identical to every other
managed section.

Rejected: one file per lesson. `~/.claude/rules/` would grow a file per
routed record, and every unpathed one loads at launch. That is the
auto-memory detritus problem (E-7, the very problem S-13's prune loop
exists to solve) reintroduced at a new surface, with no prune loop.

**Pin (P-A9).** The cap is **per topic file**. Because a topic file is
cheap to create, an analyst can evade the cap by minting topics. The
over-cap graduation card — **`02-schema.md` §4** (the card is specified
there; `models.py:1152` names it "02 §4 over-cap WARNING"), NOT
routing-doctrine §4, whose subject is repo conventions — must therefore
fire on the *scope's total rules footprint*, not per file alone.
(The narrowest-surface cap *doctrine* is routing-doctrine **§3**.) Concretely: the over-cap WARNING
triggers when any single topic file exceeds its cap **or** when a scope's
rules directory exceeds 5 topic files — the second being the
new-topic-churn signal.

---

## 7. Contradiction domain re-scoping

Doctrine §10 is a **destination-bounded** contradiction check (Y-23). It
currently reads "same destination" as "same enum value," which was
sufficient when one enum value meant one file per scope.

**Pin (P-A10).** The contradiction domain is **(scope, always-loaded)**,
not the enum value. At one scope, `claude-md`, unpathed
`claude-md:rules:*`, and `claude-md:local` are all loaded in the same
session simultaneously, so they can contradict each other. They are ONE
domain.

Pathed rules are a **separate** domain per glob-set: two rules that never
co-load cannot contradict in practice. Two rules whose globs *overlap*
share a domain.

Without this, we ship exactly the failure the docs warn about: *"if two
rules contradict each other, Claude may pick one arbitrarily."*

**Refinement (P-A10b) — user↔project rule conflicts are NOT arbitrary.**
The docs pin a defined precedence: *"User-level rules are loaded before
project rules, giving project rules higher priority."* So a
project-scope rule deterministically beats a user-scope rule on the same
subject. Two consequences:

1. The contradiction check should **report the winner** rather than only
   flagging a clash — the outcome is knowable, so telling the human "your
   project rule will override your user rule" is strictly better than
   "these conflict."
2. This is a *routing* signal. A user-scope rule that a common project
   rule already overrides is a rule that will not fire where it matters —
   which is the narrowest-surface bias (§3) operating on precedence
   rather than on load frequency.

Arbitrary resolution remains the case for same-scope conflicts.

---

## 8. Labels — the original request (R-1)

Adopt the docs' own names. The label is no longer a dict lookup on the
destination key, because the key no longer determines the answer.

| variant | scope | label | detail shown |
|---|---|---|---|
| — | `user` | User instructions | `~/.claude/CLAUDE.md` |
| — | `project` | Project instructions | `<repo>/CLAUDE.md` |
| — | `skill:<n>` | Skills repo instructions | `<skills root>/CLAUDE.md` |
| `rules` | `user` | User rule — *<topic>* | `~/.claude/rules/<topic>.md` |
| `rules` | `project` | Project rule — *<topic>* | `<repo>/.claude/rules/<topic>.md` |
| `local` | `project` | Personal project notes | `<repo>/CLAUDE.local.md` |

A pathed rule appends its firing condition in plain words: *"loads when
you touch `src/**/*.ts`"*. An unpathed one says *"loads every session"* —
the honest statement of P-A1, at the point of decision.

**Pin (P-A11).** `_GROUP_LABELS` remains the **single** label map (U19
doctrine, `models.py:112-115`: "no second label map may exist"). The
resolver's *signature* widens to take scope and variant; the map is
extended, never forked. A builder who adds a parallel dict has broken
this pin.

**Pin (P-A12).** The resolved **path** is always shown alongside the
label. The label disambiguates the category; only the path
disambiguates the file. F-1 happened because a category name was asked
to do a file's job.

---

## 9. Deferred: the `skill:<name>` rules leg

The skill-scope rules target is **left unresolved on purpose**. It
depends on whether plugins support a `.claude/rules/` directory.

*Grounding (upgraded 2026-07-19).* This is no longer "probably
extrapolation" — it is a **confirmed documentation gap**. A dedicated
verification pass searched the full memory documentation for any mention
of plugins and found none: that page covers managed/user/project/local
scoping, monorepo excludes, and cross-project symlink sharing, and says
nothing about plugin-shipped rules. The claim originally entered via an
agent sweep that cited it without support. Resolving it requires the
plugins documentation, not this page — a different source, not a closer
reading of the same one.

**Pin (P-A13).** No skill-scope rules leg ships until the plugin rules
surface is verified against primary sources. Until then,
`claude-md:rules:*` is valid for `user` and `project` scope only, and
skill-scope records route as they do today. A `VerbError` names the
deferral rather than silently falling back.

**The deferral needs an explicit guard, not an assumed one.** The
`claude-md` third leg is an **unguarded `else` fallthrough**
(`verbs.py:600` — re-verified post-C2 HEAD 97726df: line 600 is
`target = root / "CLAUDE.md"`, still reached by fallthrough after the
`user` and `project` returns), not the `scope.startswith("skill:")`
check its comment at :591-593 describes — any scope that is not `user`
or `project` lands
in the skills-root leg. So a skill-scope `rules` route would silently
resolve to `<skills root>/CLAUDE.md` instead of raising. The builder MUST
add a positive scope check; inheriting the existing control flow produces
exactly the silent misroute this pin forbids.

---

## 10. Considered and rejected

**Nested `<subdir>/CLAUDE.md`.** Real (verified), and gives subtree
scoping. **Dominated by pathed rules**, which scope by *glob* rather
than by directory — strictly more expressive (extension filters, multiple
patterns, brace expansion) and centrally located rather than scattered
through the tree. Recorded so a future reviewer does not re-raise it.

**Managed policy CLAUDE.md** (`/etc/claude-code/CLAUDE.md`). Permanent
**non-target**: root-owned, and writing it would require sudo, which is
prohibited. An explicit non-target row in doctrine, not a silent
omission.

**`rules` as its own enum value.** Ruled out by R-2, and independently
supported by the docs ("same priority as `.claude/CLAUDE.md`").

**Auto-memory as a destination.** Ruled out by R-5 and by ratified S-13 /
S-14: it is a *source*, with a closed prune loop.

**Deriving globs without human concurrence.** Ruled out by R-4. Inferring
a glob from prose is precisely the inference that misfires, and its
failure mode is silent (§5).

---

## 11. Test obligations

Load-bearing, in the sense the code gate will mutate to verify:

1. `variant` absent routes byte-identically to today (P-A6) — the
   no-migration guarantee.
2. A dead glob **refuses** at route time; a rule with 3 globs where 1 is
   dead refuses on that one (P-A7) — the partial-failure case.
3. `--allow-empty-glob` is the *only* path past it, and is recorded.
4. `CLAUDE.local.md` routing refuses when `.gitignore` does not cover it
   (P-A3) — the privacy failure.
5. Label resolution is scope-and-variant aware, and **no second label
   map exists** (P-A11) — grep-level assertion.
6. The resolved path renders alongside every label (P-A12).
7. Contradiction detection fires across `claude-md` ↔ unpathed
   `rules` ↔ `local` at one scope (P-A10), and does **not** fire across
   non-overlapping pathed rules.
8. Cap enforcement per topic file, plus the >5-topics churn signal
   (P-A9).
9. Skill-scope `rules` raises the deferral error, not a silent fallback
   (P-A13).
10. selfcheck flags a routed rule whose glob has gone stale (§5.2).

---

## 12. Out of scope

- **Spec B** — `permissions.deny` destination.
- **Backfill.** Existing routed `claude-md` entries are not re-examined
  for path-triggered candidates. A graduation-time question, not a
  migration.
- **`o`-cycle reachability.** Pathed rules need a glob, so they fall out
  of `PARAMETER_FREE_DESTINATIONS` alongside `hook` and `new-skill` —
  Iterate/CLI only. This is a *consequence* of R-3/R-4, recorded so the
  keymap owner is not surprised; no keyboard work here.
