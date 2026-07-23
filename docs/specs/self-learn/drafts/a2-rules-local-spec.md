# Spec A2 — `claude-md` rules, local, and glob validation

Status: DRAFT — for blind Opus gate.
Rev: 2026-07-22 — **carved from
`docs/specs/self-learn/drafts/claude-md-parameterization-spec.md` (the
re-scoped parent Spec A), A2 of the A1/A2 split, re-anchored against
HEAD `4950929` (master).** A1 (scope-aware labels — parent §8 rows 1-3,
P-A11/P-A12) **has shipped**: commits `fe9a084` (spec + re-scope) and
`4950929` (the fix). A2 carries everything else the parent ratified: the
surface×scope taxonomy and the `variant` parameter (parent §2), the
pathed-vs-unpathed discriminator (§3), the `--dest` grammar + proposal
schema + the grammar-sync obligation (§4), glob validation (§5), the
`local`/`CLAUDE.local.md` surface and its privacy refusal (§2/P-A3),
contradiction-domain re-scoping (§7), granularity + caps (§6), and the
skill-scope deferral guard (§9). All parent pins P-A1..P-A13 are carried
here restated with current anchors.

**This spec re-litigates nothing in the parent.** The design is ratified.
A2's job is to make it *buildable against current code* and to fold **two
fresh user rulings** (§0.2) — one of which (the chezmoi-add offer, §10)
**supersedes** the parent's P-A2b. Where the parent's ruling still holds,
it is reproduced verbatim.

**One-spec ruling (user, 2026-07-22).** A2 ships as **one** spec, not a
further split. The pieces are interdependent: rules, local, glob
validation, the offer, and the labels all touch `_resolve_target` /
`_parse_dest` / the proposal schema / the `routing` block. Splitting them
would fork those call sites.

---

## 0. Baseline, rulings, and the correction that survived

### 0.1 What A1 already shipped (do not re-touch)

A1 widened the UI label resolver to *scope*. Present in current code
(`plugins/self-learn/ui/src/self_learn_ui/models.py`):

- `destination_label(value, scope=None)` (`models.py:141`) — the single
  gloss function; `claude-md` + a recognized scope substitutes a
  per-scope label.
- `_CLAUDE_MD_SCOPE_LABELS` (`models.py:120`): `user`→"User instructions",
  `project`→"Project instructions", `skill`→"Skills repo instructions".
- `destination_path(scope)` (`models.py:166`) + `_CLAUDE_MD_SCOPE_PATHS`
  (`models.py:134`): the resolved path shown beside the label (P-A12).
- `_GROUP_LABELS` (`models.py:234`) remains the **single** enum→label map
  (P-A11); the scope dicts above are *scope specializations of the one
  polymorphic destination*, not a second enum→label map.

A2 **additively widens** `destination_label` / `destination_path` to take
a **variant** (§11). It forks nothing A1 shipped.

### 0.2 Rulings folded in

The parent's rulings R-1..R-5 (parent §0) bind unchanged; the load-bearing
ones for A2:

| # | Ruling | Words |
|---|---|---|
| R-2 | `rules` is a **scope parameterization of `claude-md`**, not a new destination | "rules is a scope parameterization of claude-md" |
| R-3 | **Path-scoped rules are in scope** | "yes, we go with path-scoped rules" |
| R-4 | The **analyst proposes** the path/glob; the **human concurs or not** | "agent suggest path, glob, etc. user can concur or not" |

**Two fresh user rulings bind THIS spec:**

- **U-A2-1 (one spec).** A2 ships whole; see the one-spec ruling above.
- **U-A2-2 (P-A2b superseded — offer chezmoi-add when detected).** The
  parent's P-A2b wrote a new, chezmoi-UNMANAGED user-scope rules file
  *directly and silently*. **New ruling:** when chezmoi is **detected
  (present)** and self-learn has just written a **new** user-scope rules
  file that reads UNMANAGED, self-learn **must OFFER** to bring it under
  chezmoi management so it syncs. When chezmoi is **absent**, keep the
  silent write-direct default (C2). Fully specified in §10; it changes
  P-A2b's "silent" clause and nothing else about the C2 capability model.

### 0.3 The corrected fact §3 is built on (parent §0.1, P-A1)

Verified in the parent against `code.claude.com/docs/en/memory`, carried
here as settled: an **unpathed** rules file *"has the same priority as
`.claude/CLAUDE.md`"* and *"loads at launch"*. A **pathed** rules file
(`paths:` frontmatter) *"triggers when Claude reads files matching the
pattern"*.

**Pin (P-A1), carried.** An unpathed rules file costs exactly what the
same text in CLAUDE.md costs. Rules relieve the **entry cap**, never the
**context cost**. Doctrine must say this in terms an analyst cannot
misread, or `rules` becomes a laundering route around the overflow cap.

**Caveat (P-A1b), carried.** A project rule *"is skipped if you exclude
`project` from `--setting-sources`"* — a second silent-non-firing vector
alongside the dead glob (§5), which self-learn can neither control nor
observe at route time. Doctrine must not promise project-scope rules fire
unconditionally.

---

## 1. Scope of A2

**In scope (this spec):**

1. The `variant` parameter on `claude-md` (`rules:<topic>` / `local`),
   with resolution by (variant, scope) — §2.
2. The pathed-vs-unpathed discriminator — §3.
3. `--dest` grammar extension + the parser/prose sync obligation — §4.
4. The proposal-schema fields `variant` / `rules_topic` / `rules_paths`,
   their validation, and their persistence into the `routing` block — §4.3.
5. Route-time glob validation (per-pattern zero-match refusal, the
   `--allow-empty-glob` escape) + selfcheck drift re-assertion — §5.
6. `local` / `CLAUDE.local.md` + the `.gitignore` privacy refusal — §6.
7. Contradiction-domain re-scoping as **doctrine** — §7.
8. Caps: per-topic-file + the >5-topics churn signal — §8.
9. The skill-scope deferral **guard** (a positive scope check) — §9.
10. The chezmoi-add offer (U-A2-2) — §10.
11. The variant-aware **label** widening — §11.

**Out of scope — see §14** (Spec B / `permissions.deny`; backfill of
existing routed `claude-md` entries; the skill-scope rules *leg* itself,
deferred by P-A13; `o`-cycle keyboard work).

---

## 2. The taxonomy: surface × variant × scope

The current enum conflates two axes. `claude-md` silently means "one of
three files, depending on scope." A2 makes the second axis explicit:

- **scope** — *whose, and where* (`user` / `project` / `skill:<name>`).
- **variant** — *what kind of always-loaded surface* (the main file, a
  rules topic file, or the personal per-project file).

`claude-md` gains a **variant** parameter. **The enum stays at five**
(`PROPOSAL_DESTINATIONS`, `ledger_ops.py:73`, is NOT extended — R-2; see
§4.1).

### 2.1 Resolution table

| variant | scope | resolved target | loads |
|---|---|---|---|
| *(none)* | `user` | `~/.claude/CLAUDE.md` | every session, everywhere |
| *(none)* | `project` | `<host repo>/CLAUDE.md` | every session in repo |
| *(none)* | `skill:<n>` | `<skills root>/CLAUDE.md` | every session in canon repo |
| `rules:<topic>` | `user` | `~/.claude/rules/<topic>.md` | every session (unpathed) / on matching file read (pathed) — **this machine only until adopted (§10)** |
| `rules:<topic>` | `project` | `<host repo>/.claude/rules/<topic>.md` | as above, **for every teammate** |
| `rules:<topic>` | `skill:<n>` | **deferred — VerbError (§9)** | — |
| `local` | `project` | `<host repo>/CLAUDE.local.md` | every session in repo, **you only** |
| `local` | `user` / `skill:<n>` | **refused — no such file exists (§6)** | — |

**C2 reconciliation (carried, current anchors).** The user surface is
still exactly `~/.claude/CLAUDE.md` (`DEFAULT_USER_CLAUDE_MD`,
`verbs.py:158`) — one file — but no longer *definitionally* chezmoi-managed.
`compile_user_scope` (`chezmoi.py:242`) is **capability-aware** via
`user_scope_capability` (`chezmoi.py:188` → `USER_SCOPE_ABSENT` /
`USER_SCOPE_UNMANAGED` / `USER_SCOPE_MANAGED`, `chezmoi.py:83-85`): it
writes directly when absent/unmanaged and runs the re-add/commit/push sync
tail only when managed. The file identity and the one-always-loaded-surface
claim are unchanged.

**Pin (P-A2b′) — user-scope `rules` inherits the C2 capability path
(revised: offer, not silence).** A user-scope `rules:<topic>` target is
`~/.claude/rules/<topic>.md`, a NEW file in the same `~/.claude` tree.
Routed through `compile_user_scope`'s capability-aware write it gets
correct absent/unmanaged/managed handling **for free** — the builder MUST
reuse it, never invent a bespoke writer (the machinery keys on the
per-target capability). **Empirically** (§ Grounding), `chezmoi
source-path` on a freshly-minted file returns rc 1 "not managed", so a new
user rule reads **UNMANAGED even when `~/.claude/CLAUDE.md` itself is
MANAGED** (chezmoi does not auto-track new files). The parent stopped here
and wrote silently. **U-A2-2 revises this:** on the UNMANAGED-and-present
case for a `rules` variant, self-learn OFFERS to adopt the file into
chezmoi (§10). Until adopted, the §11 label reads "loads every session
(this machine)", never implying cross-machine reach it does not have.

**Pin (P-A2), carried.** `local` at project scope is the only personal
per-project surface. Today such a lesson has two bad homes: the
team-shared `CLAUDE.md` (pollutes others' context) or user scope
(over-fires in every project). This is the correct third option.

**Pin (P-A3), carried (mechanism pinned, §6).** `CLAUDE.local.md` must be
gitignored to be correct. The compiler MUST verify the host repo ignores
it and refuse with a plain-words fix if not — routing a "personal" lesson
into a tracked file publishes it to the team: a silent privacy failure.

**New ruling (U-A2-glob-tree) — user-scope pathed globs cannot be
zero-match-validated.** A user-scope `TargetSpec` carries `host_repo=None`
(`verbs.py:584`) and a user bucket has no project path, so **there is no
canonical tree** to match a user-scope glob against — the rule fires
against *whatever repo Claude runs in*, many repos over its life.
Consequence, pinned in §5: the **zero-match refusal and the selfcheck
re-assertion run for PROJECT-scope pathed rules only**; user-scope pathed
globs get **parse-shape validation only** (§5.1). This preserves parent
§2.1 (user+pathed stays valid) while being honest that the silent-failure
guard has different strength by scope.

---

## 3. The discriminator: which variant wins

The corrected fact (§0.3) gives exactly one real decision.

**Does the lesson have a file-path firing condition?**

- **Yes** → `rules:<topic>` **with** `paths:`. Genuinely narrower — loads
  only when Claude touches matching files. The *only* new capability.
- **No** → `claude-md` (no variant) vs. unpathed `rules:<topic>` is **not
  a cost decision**; identical tokens either way. Decide on organization
  and cap-relief alone.

**This discriminator already exists in the corpus.** Routing-doctrine §2
routes `behavior`/`anti-pattern` to `hook` when the mistake is "mechanical
and tool-detectable (**a file-path pattern**, a command shape)". The same
signal — a trigger that names paths — selects a path-scoped rule. A
trigger that names a *moment* ("about to spawn a subagent") has no glob
and stays `claude-md`.

Worked negative case (live queue): `lrn-5d0c592a` fires at subagent-spawn
time. No file pattern → no glob → a rules file buys only tidiness. It
stays `claude-md` at user scope. An analyst that proposes `rules` here has
misread §3.

**Pin (P-A4), carried.** The narrowest-surface bias (routing-doctrine §3)
now has a real ranking at user scope for the first time:

```
pathed rules  <  unpathed rules ≈ CLAUDE.md
```

`≈` is deliberate: equal context cost, differing only in entry-cap
pressure. Doctrine MUST NOT present unpathed rules as narrower.

---

## 4. Grammar and schema

There are **two distinct change-sets**, kept separate so the gate reads
them independently:

- **(A) the destination grammar** — two *parsers* that must agree, plus
  two *prose* sites that describe them (§4.1, §4.2); and
- **(B) the proposal schema fields** — `variant`/`rules_topic`/
  `rules_paths` validated in `validate_proposal` and persisted in the
  `routing` block (§4.3).

`PROPOSAL_DESTINATIONS` (the enum) is in NEITHER — it does not change.

### 4.1 `_parse_dest` extension (verbs.py:404)

`_parse_dest` returns `(destination, qualifier)` — a **single** qualifier
slot already serving `reference:<file>` and `new-skill:<name>` via prefix
branches (`verbs.py:409-419`). Add two more **prefix branches**, ordered
before the `dest not in PROPOSAL_DESTINATIONS` fallback (`verbs.py:420`):

```
claude-md                    → ("claude-md", None)
claude-md:local              → ("claude-md", "local")
claude-md:rules:<topic>      → ("claude-md", "rules:<topic>")
```

Because these are prefix branches (like `reference:` / `new-skill:`), they
**never reach** the `PROPOSAL_DESTINATIONS` membership check — so **site 1
(the enum) stays unchanged**. A builder who adds a `claude-md:...` entry to
`PROPOSAL_DESTINATIONS` has misread R-2.

`<topic>` reuses `validate_skill_name` (`skill_scaffold.py:42`) — lowercase
kebab, `[a-z0-9-]`, no traversal — because a topic becomes a filename, the
same injection surface. Empty topic → `VerbError`.

**Obligation (Y-9 wording).** `validate_skill_name`'s error string reads
"new-skill name … must be kebab-case" (`skill_scaffold.py:45`). Reused
verbatim for a rules topic it misnames what the user got wrong. The topic
slug MUST be validated with a message that names **"rules topic"**, not
"new-skill name" — either by parameterizing the noun in
`validate_skill_name` (a shared helper for both callers) or by catching its
error and re-raising a topic-specific `VerbError` at the rules-parsing
site. A route rejected for a bad topic slug must not surface "new-skill
name … must be kebab-case".

### 4.2 The sync obligation — two parsers + two prose sites

The parent named "FOUR enumerations that must move together." Re-anchored
and re-classified for A2:

| # | Site | Anchor | A2 change |
|---|---|---|---|
| 1 | `PROPOSAL_DESTINATIONS` tuple (the enum) | `ledger_ops.py:73` | **NONE** — variant is not an enum value (R-2) |
| 2 | analyst prompt template | `analyst.py:91` | **CHANGE** — teach the analyst to emit `variant`/`rules_topic`/`rules_paths` |
| 3 | `_DEST_RE` regex (UI dest twin) | `proposals.py:92` | **CHANGE** — add `claude-md:rules:.+` and `claude-md:local` alternatives |
| 4 | routing-doctrine grammar prose | `routing-doctrine.md:98` | **CHANGE** — describe the variant forms |

**The sharp one is site 3.** `_DEST_RE` is currently
`\A(skill-md|claude-md|reference(:.+)?|new-skill:.+|hook)\Z`
(`proposals.py:92`) — it is the **UI-side twin of `_parse_dest`** (the CLI
truth). Ship the §4.1 grammar without extending `_DEST_RE` and **every
proposal carrying `claude-md:rules:<topic>` fails UI validation while the
CLI accepts the same string** — the split-brain the parent flagged. The
two parsers (`_parse_dest`, `verbs.py:404` ↔ `_DEST_RE`, `proposals.py:92`)
MUST land in the same change. Keep `_DEST_RE`'s `\A…\Z` anchors — never
`$` (a trailing-newline bypass; noted in `proposals.py:89-91`) — and
respect `DEST_MAX_CHARS = 100` (`proposals.py:101`).

**Obligation (NIT 1) — the refusal message must enumerate the new forms.**
When `_DEST_RE` rejects a dest, the refusal lists the accepted forms
(`proposals.py:297-299`: "skill-md, claude-md, reference, reference:<file>,
new-skill:<name>, hook"). That list MUST gain `claude-md:rules:<topic>` and
`claude-md:local`, so a mistyped new-form dest gets an accurate error
instead of a list that omits exactly the forms A2 added. This message and
`_DEST_RE` move together (a form accepted by the regex but absent from the
message, or vice versa, is the drift this obligation forbids).

Sites 2 and 4 are prose describing the same grammar; they ride the same
change so the analyst proposes, and the doctrine documents, exactly what
the parsers accept.

**Pin (P-A5), carried.** Globs do **not** ride in `--dest`. They contain
`/`, `*`, `[`, `,`; a `:`-delimited value cannot carry them unambiguously.
Globs live in the proposal YAML only (§4.3).

**Consequence, and it is a feature (carried).** A path-scoped rule
**cannot** be routed by bare `--dest` with no proposal — there is nowhere
for the globs to come from. R-4's "user can concur or not" becomes
*structural*: reaching a pathed rule requires a proposal a human read.
Bare `--dest claude-md:rules:<topic>` with no proposal yields an
**unpathed** rule — the honest fallback (it still loads, just
unconditionally).

### 4.3 Proposal schema (02 §1) + routing persistence

**Schema addition — `validate_proposal` (`ledger_ops.py:517`).** New
optional fields, validated when present:

```yaml
destination: claude-md
variant: rules            # optional: "rules" | "local" | (absent)
rules_topic: subagents    # required iff variant == "rules"; kebab slug
rules_paths:              # optional; absent ⇒ unpathed rule
  - "src/**/*.ts"
  - "lib/**/*.ts"
```

Validation obligations (raise `ProposalError`):

1. `variant`, if present, is `"rules"` or `"local"`; else error.
2. `variant == "rules"` ⇒ `rules_topic` present and passing
   `validate_skill_name`'s slug discipline (the same charset the parser
   enforces, so proposal and `--dest` cannot disagree).
3. `variant == "local"` ⇒ `rules_topic` / `rules_paths` absent (a `local`
   file takes no topic and no globs).
4. `rules_paths`, if present, is a non-empty list of non-empty strings
   (deep glob validation is route-time, §5 — schema validation only checks
   shape, because the target tree is not known at `proposal validate`).
5. `variant` absent ⇒ no new constraint (P-A6).

**Routing persistence.** At route time the qualifier is threaded into the
`routing` block exactly as `reference_file` / `new_skill` / `hook` are
today — additional keys on the same dict, which `Record.set_routing`
(`records.py:404`) accepts (it requires only `routed_at`/`destination`/
`by`). Two write sites carry it:

- `resolve_record` (`ledger_ops.py:693`) gains `variant` / `rules_topic` /
  `rules_paths` kwargs, written into the routing block (mirrors its
  existing `reference_file` / `hook` / `new_skill` kwargs).
- the manual `routing = {…}` construction (`verbs.py:1913`) sets the same
  keys when `destination == "claude-md"` and a variant is present.

Downstream readers that already switch on `routing.get("destination")`
(`_target_for`, `selfcheck.py:183`; `_apply_target`, `verbs.py:1273`) read
`routing.get("variant")` / `"rules_topic"` / `"rules_paths"` to resolve the
concrete file (§2.1) and to re-assert globs (§5.2).

**`TargetSpec` (`verbs.py:477`) gains `variant` / `rules_topic` /
`rules_paths`** so `_resolve_target` can carry the resolved kind through to
`_apply_target` (the write) and so `_apply_target` can compute the offer
gate (§10). `variant=None` ⇒ today's fields, today's behavior.

**Pin (P-A6), carried + C2 rider.** `variant` absent ⇒ today's behavior,
**byte-identical**. Every existing proposal on disk stays valid and routes
exactly as before; this spec adds no migration. "Today's behavior" for a
variant-absent **user** record is the post-C2 capability-aware path
(`compile_user_scope`: direct write when absent/unmanaged, re-add/commit/
push when managed) — byte-identity is asserted against **that** baseline.
Test obligation 1 (§13) exercises ABSENT/UNMANAGED/MANAGED. The
variant-carrying user-scope rules route reuses the **same** write path
(P-A2b′): it adds a target, never a new write mechanism.

### 4.4 Route-time INPUT seam — do not drop the variant (misroute hazard)

§4.3 names the *output/persistence/reader* seams; this names the two
*input* seams by which `variant`/`rules_topic`/`rules_paths` reach
`_resolve_target` and its preflight. Miss either and the route silently
lands on plain `~/.claude/CLAUDE.md` — a **silent misroute**, the worst
class here.

**(A) `_resolve_destination` must not drop the proposal's variant.**
`_resolve_destination` (`verbs.py:428`) returns `(destination, qualifier)`.
Its `--dest` branch (`verbs.py:434`) preserves `_parse_dest`'s qualifier,
but its **proposal branch** (`verbs.py:442`) returns `data["destination"],
None` — **discarding** the proposal's `variant`/`rules_topic`/`rules_paths`.
**Obligation:** widen `_resolve_destination`'s return to carry `variant` +
`rules_topic` + `rules_paths` (read from the proposal `data` on the
proposal branch; from the `_parse_dest` qualifier decomposition on the
`--dest` branch, per (B)). Its **two callers** — `route`
(`verbs.py:1570`, `destination, ref_name = _resolve_destination(...)`) and
the second verb (`verbs.py:2168`, same unpack) — must both thread the new
fields into their `_resolve_target` calls (`verbs.py:1583`,
`verbs.py:2174`). A builder may widen the tuple or return a small
dataclass; the **contract** is that the three fields survive proposal →
resolver, never `None`-dropped.

**(B) Bare `--dest claude-md:rules:<topic>` must reach the rules target,
not plain CLAUDE.md.** `claude-md` is one-motion-allowed
(`ONE_MOTION_UNROUTABLE = {"new-skill","hook"}`, `verbs.py:171`;
`one_motion_allowed`, `verbs.py:182`), so **`route_direct`
(`verbs.py:1781`) REACHES `_resolve_target`** for a bare
`--dest claude-md:rules:<topic>` — it unpacks `_parse_dest` at
`verbs.py:1813` and calls `_resolve_target` at `verbs.py:1882`. Today
`_parse_dest`'s new §4.1 branch drops `"rules:<topic>"` into the qualifier
slot (`ref_name`) and `_resolve_target`'s claude-md branch **ignores
`ref_name`** — a naive build silently writes plain `~/.claude/CLAUDE.md`
with no variant. **Obligation:** the qualifier must be unpacked before the
target resolves — `ref_name == "local"` → `local` variant; `ref_name`
starting `"rules:"` → `rules` variant, topic `ref_name[len("rules:"):]` —
and resolve to the §2.1 variant target. Per the parent §4.1 "Consequence"
(P-A5: globs ride only in a proposal), a **bare-dest** rules route carries
**no globs**, so it yields an **UNPATHED** rule file at
`~/.claude/rules/<topic>.md` (project: `<repo>/.claude/rules/<topic>.md`) —
never plain CLAUDE.md, never pathed. Whether the decomposition happens in
`_resolve_destination` (feeding structured params, per (A)) or inside
`_resolve_target` is the builder's call; the **contract** is that bare
`--dest claude-md:rules:<topic>` resolves to the unpathed rules target.
`rules_paths` is a structured param that arrives ONLY from a proposal
(P-A5), so `_resolve_target`'s glob validation (§5.1) runs only when a
proposal supplied paths.

*Reader/recompile sites unaffected:* the retirement/recompile
`_resolve_target` calls (`verbs.py:1129/1203/2562/3051`) resolve from the
**stored** `routing` block, so they read `routing.get("variant")` /
`"rules_topic"` / `"rules_paths"` — already covered by §4.3. Only the two
*fresh-route* input seams above need the new threading.

### 4.5 Apply-side obligations — gather filtering and file bootstrap

Two apply-side mechanisms the feature silently depends on. Both are the
mirror of the discriminator: because `routing.destination` is **still
`"claude-md"`** for every rules/local record (R-2), the split by variant/
topic that §2.1 draws on the *resolve* side must be redrawn on the
*gather* and *write* sides, or the surfaces cross-contaminate.

**(A) Compile-set filtering — a real cross-contamination hazard.**
`_compile_set` (`verbs.py`, gather) currently calls `_routed_to`
(`verbs.py:445`) with only `destination + scope_pred`
(`verbs.py:445-470`). For **every** rules/local record `destination ==
"claude-md"`, so as written:

- compiling `~/.claude/rules/<topic>.md` would sweep in plain-CLAUDE.md
  records **and every other topic's** records; and
- compiling `~/.claude/CLAUDE.md` would sweep in the rules/local records.

Both directions wrong. **Obligation:** the compile set must partition on
`(variant, rules_topic)`:

- a `rules:<topic>` target gathers only records whose
  `routing.variant == "rules"` **and** `routing.rules_topic == <topic>`;
- a `local` target gathers only `routing.variant == "local"` records at
  that host;
- the plain-`claude-md` set **excludes** `variant in {"rules","local"}`.

This applies to **every** `_compile_set` leg (user, project, and the
project/skill-root **union** leg that already unions scopes into one file
— the variant/topic filter composes with, does not replace, that union).
The natural seam is a `variant`/`topic` predicate threaded into
`_routed_to` (`verbs.py:445`) alongside `scope_pred`, so `_target_for`'s
path disambiguation (selfcheck, §5.2) and the gather stay mirror images.

**(B) First-route file + directory creation.** `compile_managed_file`
(`compilers.py`) **refuses a missing target** ("the compiler never creates
target files, only the section inside an existing one"). Today the **host**
leg bootstraps an empty file first (`verbs.py:1306-1311:
spec.target.write_text("")`), but the **user** leg (`verbs.py:1296-1304`)
does **not** — correct for the pre-existing `~/.claude/CLAUDE.md`, but a
first route to a **new topic** would `CompileError`. **Obligation:** a
first route to a rules topic must, before compiling:

- `mkdir -p` the `rules/` parent (`~/.claude/rules/` or
  `<repo>/.claude/rules/`) — the host leg's bare `write_text` at
  `verbs.py:1311` also fails for a project rule whose `.claude/rules/`
  parent does not yet exist, so **both** legs need the parent mkdir; and
- create the empty `<topic>.md` (user leg) / extend the host bootstrap with
  the mkdir (project leg), so the managed-section compiler has a file to
  own.

*Capability-probe note (why the offer fires on first route):*
`compile_user_scope` probes `user_scope_capability` (`chezmoi source-path`)
**before** the write, so on a first route it probes a **nonexistent**
target. `source-path` keys on *management*, not existence — it returns
UNMANAGED (rc 1) for a path chezmoi does not track, which is exactly what
makes the §10 offer fire on the brand-new file. (The sandbox transcript
tested with the file already present; the first-route case returns the same
UNMANAGED signal for the stronger reason that the file does not exist yet.)

---

## 5. Glob validation — the silent-failure guard

**The one real hazard the parameterization introduces.** Every existing
destination is verifiable by reading the target file. A path-scoped rule
that never matches is indistinguishable from one that works: no error, no
warning, the lesson simply never loads.

### 5.1 Route-time validation (blocking, per-pattern)

Before any commit, for each entry in `rules_paths`:

- **Project scope** (`host_repo` is the resolved project repo,
  `verbs.py:590`): **match the glob against the repo working tree; zero
  matches → refuse** (`VerbError`) naming which pattern matched nothing and
  that a rule with a non-matching pattern never fires (Y-9 plain words).
- **User scope** (`host_repo=None`, no canonical tree — U-A2-glob-tree):
  **parse-shape validation only.** There is no single tree to count
  matches against, so zero-match cannot be asserted; the glob is accepted
  after the shape checks of §4.3(4). The §11 label states the rule fires
  per-repo so the human is not misled into thinking it was tree-verified.

Refusal, not warning, on the project-scope zero-match. A warning on a
silent-failure class is a warning nobody reads.

**Glob-engine fidelity (pinned, empirically grounded).** The documented CC
partial-failure — a pattern with an unparseable `[` (e.g. `photos
[2024/**`) *"is invalid: it matches nothing, and the rule's other patterns
keep working"* — is **caught by the zero-match check, not by a separate
parse step**. Python's `fnmatch.translate` does **not** raise on an
unbalanced `[` (empirically: `fnmatch.translate("photos [2024/**")`
returns a regex that compiles cleanly — see Grounding); it degrades the
bracket to a literal, which then matches nothing, exactly as CC does. So:

- The matcher is stdlib recursive glob over the host working tree
  (`glob.glob(pattern, root_dir=<host>, recursive=True)`, which honors
  `**`), an approximation of CC's gitignore-style matcher. State this
  limitation in the doctrine.
- **Zero-match is the load-bearing check.** There is no separate
  "unparseable → VerbError" step, because the chosen matcher (and CC) both
  render a bad bracket non-matching — the parent's step-1 "unparseable"
  case is subsumed by step-2 zero-match.
- Matching is over the working tree as `glob` sees it; a glob whose only
  matches are `.gitignore`d is a defensible future refinement, not a
  blocker (noted, not built).

**Pin (P-A7), carried + scope rider.** Validation runs **per pattern**,
not per rule. A project-scope rule with three globs where one is dead must
fail on **that one** — the documented partial-failure mode; a rule-level
"did any match?" would pass it. The per-pattern refusal is **project-scope
only** (user scope is parse-only, above).

**Sanctioned escape: `--allow-empty-glob`.** For the legitimate
write-the-rule-before-the-files case. Explicit flag on the route verb;
when set, the project-scope zero-match refusal downgrades to a recorded
note in the routing metadata; **never the default**, and logged so a later
reader knows the rule was routed unverified.

### 5.2 selfcheck re-assertion (drift)

`selfcheck.py` check (d) (`_check_drift`, `selfcheck.py:261`) already
verifies every routed record is present in its canon — the `(lrn-…)` entry
marker inside the target's managed section (`selfcheck.py:344-352`).
Extend for `variant == "rules"`:

1. The topic file exists at its resolved path (§2.1) — `_target_for`
   (`selfcheck.py:183`) gains the rules/local resolution: `user` →
   `~/.claude/rules/<topic>.md`, `project` →
   `<project>/.claude/rules/<topic>.md`, `local`/project →
   `<project>/CLAUDE.local.md`, keyed off `routing.get("variant")` /
   `"rules_topic"`.
2. The `(lrn-…)` marker is inside that file (unchanged marker logic).
3. **For a PROJECT-scope pathed rule only**, every recorded glob still
   matches ≥1 file in the project working tree. A glob goes stale when
   files move — the same drift class, the same repair
   (`self-learn recompile` surfaces it; the human retargets). User-scope
   pathed globs are **not** re-asserted here (no canonical tree —
   U-A2-glob-tree); their presence-in-file check (1,2) still runs.

---

## 6. `local` / `CLAUDE.local.md` and the privacy refusal

`local` at project scope resolves to `<host repo>/CLAUDE.local.md` (§2.1).

**Positive scope guard (mirror of P-A13).** `local` is valid at
**project** scope only. In `_resolve_target`'s `claude-md` branch, a
`variant == "local"` route MUST raise `VerbError` for `user` and
`skill:<name>` scope with an explicit message ("CLAUDE.local.md exists only
per project — route to project scope, or use claude-md/rules"), **not** an
`else` fallthrough (which would misroute a user-scope `local` into
`~/.claude/CLAUDE.md`). This is the same anti-fallthrough discipline §9
requires.

**Pin (P-A3), mechanism pinned.** Before committing a `local` route the
compiler MUST confirm the host repo ignores `CLAUDE.local.md` and refuse
otherwise. The check is **`git check-ignore <host>/CLAUDE.local.md`** run
in the host repo (rc 0 = ignored = proceed; rc 1 = **refuse**). Use
`git check-ignore`, **not** a substring scan of `.gitignore` — it correctly
honors nested `.gitignore` files, negations, and the user's global excludes,
which a substring scan silently misses. The refusal names the fix
("add `CLAUDE.local.md` to .gitignore, then re-route") in plain words —
routing a "personal" lesson into a tracked file publishes it to the team.

---

## 7. Contradiction domain re-scoping — DOCTRINE, not a detector

**Grounding correction (verified this pass).** There is **no automated
contradiction scanner** in the code. `contradicts` is (a) a proposal field
validated in `validate_proposal` (`ledger_ops.py:551-564`), and (b) a
record link the human applies via `link contradicts`
(`records.py:589-602`, `append_contradicts`). Nothing scans loaded canon
for clashes. Therefore the parent's §7 re-scoping is an **edit to the
existing analyst-facing doctrine** — routing-doctrine **§10** already
exists (`routing-doctrine.md:322`, "Destination-bounded contradiction
check (Y-23)") and already emits the `contradicts` field
(`routing-doctrine.md:336-337`). A2 **re-scopes §10's domain** from "same
enum value" to **(scope, always-loaded)**; **emission is already wired**
(the `contradicts` list, the `link contradicts` verb). No analyst-prompt-
template change (`analyst.py:91`) is needed for contradiction — the analyst
reasons from the doctrine loaded into its system prompt, not from the reply
skeleton. The parent's test obligation #7 is recast accordingly (§13).

**Pin (P-A10), carried as doctrine.** The contradiction domain is
**(scope, always-loaded)**, not the enum value. At one scope, `claude-md`,
unpathed `claude-md:rules:*`, and `claude-md:local` all load in the same
session simultaneously, so they can contradict each other — **one domain**.
Pathed rules are a **separate** domain per glob-set (two rules that never
co-load cannot contradict in practice; two whose globs *overlap* share a
domain). Routing-doctrine §10 must state this so the analyst reasons over
the right domain and emits `contradicts` when it applies.

**Refinement (P-A10b), carried as doctrine.** User↔project rule conflicts
are **not** arbitrary: the docs pin *"User-level rules are loaded before
project rules, giving project rules higher priority."* So a project-scope
rule deterministically beats a user-scope rule on the same subject.
Doctrine consequences: (1) when the analyst flags a user↔project clash it
should **name the winner** ("your project rule will override your user
rule"), strictly better than "these conflict"; (2) this is a *routing*
signal — a user-scope rule a common project rule already overrides will not
fire where it matters (narrowest-surface bias on precedence). Arbitrary
resolution remains the case for **same-scope** conflicts (*"if two rules
contradict each other, Claude may pick one arbitrarily"*).

---

## 8. Granularity and caps

**Pin (P-A8), carried.** One topic file holds **many** lessons, in a
marker-bounded managed section, under the existing
`DEFAULT_MAX_ENTRIES = 10` / `DEFAULT_MAX_WORDS = 150` cap
(`compilers.py:88-89`) — identical to every other managed section
(`compile_managed_file` is the same compiler `compile_user_scope` and the
host leg already call). Rejected: one file per lesson — `~/.claude/rules/`
would grow a file per routed record, every unpathed one loading at launch;
that reintroduces the auto-memory detritus problem (E-7) at a new surface
with no prune loop.

**Pin (P-A9), carried.** The cap is **per topic file**. Because a topic
file is cheap to create, an analyst can evade the cap by minting topics.
The over-cap graduation card — **`02-schema.md` §4** (the WARNING is
surfaced through the route verb's own stderr at route time,
`models.py:1213`; the UI budget row template is `_budget_text`,
`models.py:1199`), NOT routing-doctrine §4 — must therefore fire on the
**scope's total rules footprint**, not per file alone. Concretely: the
over-cap WARNING triggers when any single topic file exceeds its cap **OR**
when a scope's rules directory exceeds **5 topic files** (the new-topic-
churn signal). The narrowest-surface cap *doctrine* remains
routing-doctrine §3.

**Computation site — exact threading (DoD-checkable).** The per-file cap
already rides `SectionResult.over_cap` / `cap_reason`
(`compilers.py:122/218-222`), surfaced at route time via
`result.over_cap_note()` (`cli.py:888`, `teach.py:748`) and to the UI
through `verbs.surface_fill` (`verbs.py:1080`), which returns
`dict[str, dict]` keyed by destination over
`SURFACE_FILL_CAPPED_DESTINATIONS = ("skill-md","claude-md")`
(`verbs.py:179`; threaded by `_add_surface_fill`, `cli.py:771-798`). The
**>5-topic-files directory footprint is a new datum with no current
home.** Pin exactly:

1. In `surface_fill` (`verbs.py:1080`), for the **`claude-md`** entry only,
   count the `*.md` files in the **scope's rules directory** per §2.1
   (`~/.claude/rules/` at user scope, `<host repo>/.claude/rules/` at
   project scope — a missing directory counts 0), and attach it to that
   entry's fill dict as `rules_topic_count: <int>`.
2. When `rules_topic_count > 5`, set that same fill dict's **`over_cap`**
   True with a distinct `cap_reason` (e.g. `"rules-topics"`), OR-ed with
   (never replacing) the per-file over-cap already there.
3. Nothing else changes: the existing `over_cap`-reading WARNING path
   (`_budget_text`, `models.py:1199`; `over_cap_note()`, `cli.py:888`)
   fires unmodified. One computation site, feeding the existing WARNING via
   the existing flag — never a second warning surface.

**DoD-checkable:** with 6 topic files in a scope's rules dir,
`surface_fill`'s `claude-md` entry carries `rules_topic_count == 6` and
`over_cap is True`; with ≤5 it carries the count and leaves the per-file
`over_cap` untouched.

---

## 9. Skill-scope deferral — a POSITIVE guard, not the unguarded else

The skill-scope rules target is **left unresolved on purpose** (parent §9):
it depends on whether plugins support a `.claude/rules/` directory, which
is a **confirmed documentation gap** — the memory docs cover
managed/user/project/local scoping and say nothing about plugin-shipped
rules; resolving it needs the *plugins* documentation, a different source.

**Pin (P-A13), carried with re-verified anchor.** No skill-scope rules leg
ships until the plugin rules surface is verified against primary sources.
Until then `claude-md:rules:*` is valid for `user` and `project` scope
only; skill-scope records route as they do today; a `VerbError` names the
deferral rather than silently falling back.

**The deferral needs an explicit guard.** The `claude-md` third leg is an
**unguarded `else` fallthrough** — `verbs.py:600` (`target = root /
"CLAUDE.md"`), re-verified at HEAD `4950929`: it is reached by fallthrough
after the `user` (`verbs.py:576`) and `project` (`verbs.py:585`) returns,
**not** the `scope.startswith("skill:")` check its comment at
`verbs.py:591-593` describes. So a skill-scope `rules` route would silently
resolve to `<skills root>/CLAUDE.md` instead of raising. The builder MUST
add a **positive** check: when `variant == "rules"` and the scope is
neither `user` nor `project` (i.e. `skill:<name>` or anything else), raise
the P-A13 deferral `VerbError`. Inheriting the existing control flow
produces exactly the silent misroute this pin forbids.

---

## 10. The chezmoi-add offer (U-A2-2 — supersedes P-A2b's "silent")

### 10.1 Why offer here but not for CLAUDE.md

C2 stays silent when `~/.claude/CLAUDE.md` reads UNMANAGED because that
file **pre-exists** and its unmanaged state is the **user's prior choice**
— respecting it is correct. A `rules:<topic>` file is **brand-new, created
by self-learn**, so offering to bring it under management is *helpful, not
presumptuous*: self-learn made a file whose whole point ("so it syncs") is
defeated by staying untracked. This distinction is the ruling's principle;
state it in doctrine so the gate reads intent.

### 10.2 Firing gate — two axes, self-extinguishing

The offer fires iff **both**:

1. **capability == UNMANAGED** (present-but-unmanaged). **Never ABSENT**
   (no chezmoi ⇒ nothing to adopt ⇒ the C2 silent write is the whole
   story). **Never MANAGED** (already syncs).
2. **variant == "rules" at user scope** — a file self-learn just created.
   **Never plain CLAUDE.md** (§10.1) and never project/local (those live
   in git, not chezmoi).

**Self-extinguishing (no declined-state to persist).** Accepting runs
`chezmoi add`, which flips the target to MANAGED (empirically: `source-path`
rc 0 after — see Grounding). So on the next recompile the gate's axis 1 is
false and **the offer stops firing by construction**. Declining changes
nothing on disk, so the bare-CLI hint may re-emit on a later recompile —
but it is one honest line, idempotent, never a modal that blocks. No
declined-state file is needed or wanted.

### 10.3 Accept path — reuse C2's sync tail, one new primitive

The accepted offer performs **add + commit + push** (the ruling's intent is
"so it syncs"; add alone does not — empirically the dotfiles repo is left
dirty with the new source file and **no commit**, see Grounding). Reuse C2
machinery; the only genuinely new chezmoi invocation is `chezmoi add`:

1. **Repo-clean guard (porcelain ONLY).** Run the dotfiles-repo-dirty check
   (`chezmoi git -- status --porcelain`) and abort if dirty — so the later
   `add -A` sweeps in **only** our new source file. **Do NOT** run the full
   `_drift_dirty_guard` (`chezmoi.py:207`): its step-1 `chezmoi diff
   <target>` **errors** on an unmanaged target (empirically rc 1 "not
   managed" — see Grounding), and the target is unmanaged by definition
   here. Only the porcelain half of the guard applies.
2. **`chezmoi add <target>`** — the one new primitive. Exit 0; folds the
   file into source state (`dot_claude/rules/<topic>.md`); flips the target
   to MANAGED.
3. **Commit + push** — reuse `commit_all_user_scope(message)`
   (`chezmoi.py:176`: `git -- add -A` + `commit`, returns the sha) then the
   push (the same `chezmoi git -- push` `compile_user_scope` runs at
   `chezmoi.py:298`).
4. **H-2 degradation.** Wrap steps 2-3's commit/push in the SAME
   try/except → warning pattern as `compile_user_scope`'s row-4 handling
   (`chezmoi.py:299-315`): once `chezmoi add` has tracked the file, a
   commit/push failure **must not roll back** — surface a `sync_warning`-
   style message and return. The file is tracked on disk; only the sync
   degraded.

**New helper (chezmoi.py), single-sourced.** A function
`adopt_user_scope(target, *, message, chezmoi, push)` implementing steps
1-4 above, returning a small result (e.g. `AdoptResult(tracked: bool,
synced: bool, warning: str | None)`). It reuses `_run`/`_check`,
`commit_all_user_scope`, and the row-4 warning shape — it reinvents
nothing. A companion `adopt_command(target)` returns the exact
user-facing command string (§10.4) so the bare-CLI hint and the UI accept
name **one** entrypoint.

### 10.4 The two surfaces (both pinned)

**(a) UI-interactive (review flow).** After a user-scope rules route whose
result carries the adopt signal (§10.5), the review UI presents an
interactive choice consistent with its existing affordances: "Wrote
`~/.claude/rules/<topic>.md`, but chezmoi isn't tracking it, so it won't
sync to your other machines. Bring it under chezmoi? [yes/no]". **Yes**
invokes the CLI entrypoint (§10.5); **No** dismisses (no persistence,
§10.2).

**(b) Bare-CLI / `--route` (no interaction).** There is no prompt on this
path. Surface the exact command via the **existing warnings/hint channel**:
`_host_phase` already reads `getattr(compile_result, "sync_warning", None)`
and does `print(f"self-learn: {…}", file=sys.stderr)` + `warnings.append`
(`verbs.py:1473-1476`). The adopt hint rides the **same** channel — one
stderr line: "wrote `~/.claude/rules/<topic>.md` — not tracked by chezmoi,
so it will not sync across machines. To sync it: `self-learn <adopt-verb>
~/.claude/rules/<topic>.md`" (the string from `adopt_command`). It is a
hint, never a blocking prompt (honoring the "never leave unattended
prompts" discipline).

### 10.5 Plumbing (concrete, so the gate can check it)

- **IN (variant awareness):** `compile_user_scope` (`chezmoi.py:242`) gains
  a parameter `offer_adopt: bool = False`. `_apply_target`
  (`verbs.py:1296-1304`, the `scope_kind == "user"` leg) passes
  `offer_adopt=True` **iff** `spec.variant == "rules"`. `compile_user_scope`
  cannot infer variant from the path robustly, so it is threaded, not
  guessed. Inside, when `cap == USER_SCOPE_UNMANAGED and offer_adopt`, set
  the new result field to the hint; on ABSENT or MANAGED, leave it `None`.
- **OUT (structured surfacing):** `UserScopeResult` (`chezmoi.py:114`)
  gains `adopt_hint: str | None = None`. `_host_phase` (`verbs.py:1473`)
  reads it right beside `sync_warning`, printing/appending it on the
  bare-CLI path; the review UI reads the same field to render surface (a)
  and to know a "yes" is offerable.
- **ENTRYPOINT (the "yes"):** a thin CLI verb — recommended name
  `self-learn chezmoi-adopt <path>` (name is the builder's call; the
  **contract** is pinned: it takes the rules-file path and runs
  `adopt_user_scope`). The bare-CLI hint text and the UI-yes invoke this
  **same** verb, whose command string comes from `adopt_command` — one
  source, no split-brain, same discipline as §4.2.

**Pin (P-A2b′-offer).** The offer path adds **no new write mechanism**: the
initial route still writes through `compile_user_scope` (P-A2b′); adoption
is a **separate, user-initiated** follow-up that only tracks-and-syncs an
already-written file. The route's own commit_lock and ledger truth are
untouched by adoption (adoption commits the *dotfiles* repo, never the
ledger).

---

## 11. Labels — variant-aware (widening A1, not forking it)

Adopt the docs' own names. Extend the A1 resolver's *signature* with an
optional variant; the map stays single (P-A11).

| variant | scope | label | detail shown |
|---|---|---|---|
| — | `user` | User instructions | `~/.claude/CLAUDE.md` |
| — | `project` | Project instructions | `<repo>/CLAUDE.md` |
| — | `skill:<n>` | Skills repo instructions | `<skills root>/CLAUDE.md` |
| `rules` | `user` | User rule — *<topic>* | `~/.claude/rules/<topic>.md` |
| `rules` | `project` | Project rule — *<topic>* | `<repo>/.claude/rules/<topic>.md` |
| `local` | `project` | Personal project notes | `<repo>/CLAUDE.local.md` |

A **pathed** rule appends its firing condition in plain words: *"loads when
you touch `src/**/*.ts`"*. An **unpathed** one says *"loads every session"*
— the honest statement of P-A1 at the point of decision. A **user-scope**
rule (unadopted) says *"loads every session (this machine)"* (P-A2b′),
never implying cross-machine reach.

**Pin (P-A11), carried.** `_GROUP_LABELS` (`models.py:234`) remains the
**single** enum→label map (U19 doctrine). `destination_label`
(`models.py:141`) and `destination_path` (`models.py:166`) widen their
*signature* to take `variant` (additive third argument, defaulting to
None), substituting the per-variant label/path from scope-and-variant-keyed
lookups that are **scope specializations of the one polymorphic
destination**, exactly as A1's `_CLAUDE_MD_SCOPE_LABELS` /
`_CLAUDE_MD_SCOPE_PATHS` already are — NOT a second enum→label map. A
builder who adds a parallel enum-keyed dict has broken this pin.

**Pin (P-A12), carried.** The resolved **path** is always shown alongside
the label. The label disambiguates the category; only the path
disambiguates the file. F-1 happened because a category name was asked to
do a file's job.

---

## 12. Invariants A2 must preserve

- **`commit_lock` (host + ledger).** `_host_phase` holds the host repo's
  commit lock across compile→commit (`verbs.py:1439-1466`); the ledger
  holds its own across mutation→commit (`_ledger_write`). Rules/local
  routes compile through the **same** `compile_managed_file` /
  `compile_user_scope` under the **same** lock — A2 adds targets, never a
  lock-free write. Adoption (§10) commits the **dotfiles** repo only, under
  chezmoi's own git, never the ledger or a host lock.
- **C2 capability model (untouched in shape).** `user_scope_capability`'s
  three states and `compile_user_scope`'s write-direct-when-absent/unmanaged
  vs sync-when-managed contract are preserved. A2 adds a fourth *behavior*
  on one state (UNMANAGED + variant==rules ⇒ emit an adopt hint) without
  changing the state machine or the write path (P-A2b′). Absent still
  writes silently; managed still syncs.
- **P-A11 single label map, untouched since A1.** A1 shipped the single-map
  widening; A2 extends the same function's signature, adding no enum-keyed
  dict.
- **P-A6 no-migration.** Variant-absent proposals and records route
  byte-identically to the post-C2 baseline.
- **H-2 (never roll back after a landed write).** The route's host-phase
  failure handling and the adoption's commit/push degradation both warn and
  point at `recompile`, never roll back.

---

## 13. Test obligations

Load-bearing, in the sense the code gate will mutate to verify. Items 1-10
are the parent's list re-anchored (item 7 recast per §7); 11-13 are the
chezmoi-add-offer cases (U-A2-2); 14-15 the apply-side obligations (§4.5);
16-19 the route-time input seam and the two NITs (§4.4, §4.1, §4.2).

1. `variant` absent routes **byte-identically** to today across the C2
   ABSENT/UNMANAGED/MANAGED user-scope branches (P-A6) — the no-migration
   guarantee.
2. A dead **project-scope** glob **refuses** at route time; a project rule
   with 3 globs where 1 is dead refuses on that one (P-A7) — the
   partial-failure case. (User-scope pathed globs get parse-only, item 12
   note.)
3. `--allow-empty-glob` is the **only** path past the project-scope
   zero-match refusal, and the bypass is recorded in routing metadata.
4. `local` routing **refuses** when `git check-ignore` reports
   `CLAUDE.local.md` is not ignored in the host repo (P-A3) — the privacy
   failure; and `local` at user/skill scope refuses via the positive guard
   (§6), not fallthrough.
5. Label resolution is scope-**and-variant** aware, and **no second
   enum→label map exists** (P-A11) — grep-level assertion that
   `_GROUP_LABELS` is the only destination-keyed dict.
6. The resolved path renders alongside every variant label (P-A12).
7. **(recast — doctrine edit, not detector).** Routing-doctrine §10
   (`routing-doctrine.md:322`) is re-scoped to state the **(scope,
   always-loaded)** contradiction domain (P-A10) and the user↔project
   precedence-winner language (P-A10b). Asserted as a **doctrine-text**
   obligation — emission is already wired (the existing `contradicts`
   field / `link contradicts` verb), and there is no runtime contradiction
   scanner to assert against (§7). No `analyst.py` prompt-template change.
8. Cap enforcement per topic file, plus the >5-topics-per-scope churn
   signal on the over-cap WARNING (P-A9).
9. Skill-scope `rules` raises the P-A13 deferral `VerbError` via the
   **positive** guard, not the silent `verbs.py:600` fallback.
10. selfcheck flags a **project-scope** routed rule whose glob has gone
    stale (§5.2); a user-scope rule's presence-in-file is still checked but
    its globs are not re-asserted.
11. **Offer fires exactly on UNMANAGED + variant==rules + user scope.**
    ABSENT ⇒ no hint (silent C2 write); MANAGED ⇒ no hint (already syncs);
    plain-CLAUDE.md user record UNMANAGED ⇒ **no** hint (C2 respect-prior-
    choice, §10.1). Drive `compile_user_scope` with a PATH-shimmed fake
    chezmoi (the existing test pattern, `chezmoi.py` module docstring).
12. **Accept path = add + commit + push, self-extinguishing.** After
    `adopt_user_scope`, `source-path` reads MANAGED and the offer no longer
    fires; a commit/push failure after `chezmoi add` **degrades to a
    warning, never rolls back** (H-2). Assert the porcelain-only guard (not
    the target-diff, which errors on unmanaged).
13. **Bare-CLI hint rides the sync-warning channel** (`_host_phase`,
    `verbs.py:1473-1476`) as one stderr line naming the single adopt verb;
    the UI-accept and the hint name the **same** entrypoint (`adopt_command`
    single source) — grep-level assertion of no second command string.
14. **Compile-set partitions on (variant, rules_topic)** (§4.5A): routing
    two lessons to different topics, and one to plain `claude-md`, at the
    same user scope yields **three** files each holding only its own
    record(s) — the rules record never appears in `~/.claude/CLAUDE.md`,
    nor a plain record in a topic file, nor topic A's record in topic B.
15. **First route to a new topic creates dir + file** (§4.5B): routing to a
    never-seen `rules:<topic>` at user scope `mkdir -p`s `~/.claude/rules/`
    and creates `<topic>.md` before compiling (no `CompileError`); the same
    for a project rule whose `.claude/rules/` parent did not exist.
16. **Bare `--dest claude-md:rules:<topic>` routes to the UNPATHED rules
    file, not plain CLAUDE.md** (§4.4B) — the currently-uncovered
    `route_direct` / one-motion path (`claude-md` is one-motion-allowed).
    Assert the target is `~/.claude/rules/<topic>.md` (user) /
    `<repo>/.claude/rules/<topic>.md` (project), unpathed, with no marker
    landing in the plain CLAUDE.md.
17. **The proposal's variant survives the input seam** (§4.4A): a proposal
    with `variant: rules` + `rules_topic` + `rules_paths` routed with **no
    `--dest`** resolves through `_resolve_destination` to the rules target
    and its globs reach glob validation (§5.1) — i.e. `_resolve_destination`
    does not `None`-drop them (a proposal with a dead glob still refuses,
    proving the paths threaded through).
18. **A bad rules-topic slug reports a topic-specific error** (§4.1, Y-9):
    the refusal names "rules topic", never "new-skill name … must be
    kebab-case".
19. **`_DEST_RE` refusal message enumerates the new forms** (§4.2, NIT 1):
    a mistyped dest's refusal lists `claude-md:rules:<topic>` /
    `claude-md:local` among the accepted forms — grep/text assertion that
    the message and the regex carry the same form set.

---

## 14. Out of scope

- **A1 labels** — shipped (`fe9a084`, `4950929`); not re-touched.
- **Spec B** — the `permissions.deny` destination (independent, its own
  gate).
- **The skill-scope rules leg itself** — deferred by P-A13 until the
  plugin rules surface is verified against primary sources. A2 ships only
  the *guard* that refuses it cleanly (§9).
- **Backfill.** Existing routed `claude-md` entries are **not** re-examined
  for path-triggered candidates — a graduation-time question, not a
  migration.
- **`o`-cycle reachability / keyboard work.** Pathed rules need a glob, so
  they fall out of `PARAMETER_FREE_DESTINATIONS` (`models.py:86`) alongside
  `hook`/`new-skill` — Iterate/CLI only. A consequence of R-3/R-4, recorded
  so the keymap owner is not surprised; no keyboard work here.
- **Nested `<subdir>/CLAUDE.md`** and **`/etc/claude-code/CLAUDE.md`** —
  considered and rejected in the parent (§10 there): dominated by pathed
  rules; a root-owned non-target requiring prohibited sudo, respectively.

---

## 15. Definition of Done (checkable)

1. `_parse_dest` accepts `claude-md:local` and `claude-md:rules:<topic>`
   via prefix branches; `PROPOSAL_DESTINATIONS` is unchanged;
   `validate_skill_name` gates the topic slug. Empty topic → `VerbError`.
   A bad topic slug reports a **"rules topic"**-worded error, never
   "new-skill name … must be kebab-case" (NIT 2, §4.1).
2. `_DEST_RE` (`proposals.py:92`) accepts the same two forms; a proposal
   carrying `claude-md:rules:<topic>` passes UI validation AND CLI parse
   (no split-brain). Its refusal message (`proposals.py:297-299`)
   enumerates `claude-md:rules:<topic>` / `claude-md:local` among the
   accepted forms (NIT 1, §4.2). Analyst prompt (`analyst.py:91`) and
   routing-doctrine grammar (`routing-doctrine.md:98`) describe the variant
   forms.
3. `validate_proposal` validates `variant`/`rules_topic`/`rules_paths` per
   §4.3; variant-absent proposals validate and route unchanged (P-A6).
4. `_resolve_target`'s `claude-md` branch resolves the four new
   (variant,scope) targets of §2.1; a **positive** guard raises the P-A13
   `VerbError` for skill-scope rules (never the `verbs.py:600` fallthrough)
   and refuses user/skill `local` (§6). `TargetSpec` carries `variant` /
   `rules_topic` / `rules_paths`.
4a. `_compile_set` partitions on `(variant, rules_topic)` (§4.5A): a rules
    topic gathers only its own records; the plain-`claude-md` set excludes
    `variant in {rules,local}`; the project/skill-root union leg still
    unions scopes but within one (variant,topic).
4b. First route to a new rules topic `mkdir -p`s the `rules/` parent and
    creates `<topic>.md` before compiling, on **both** the user leg
    (`verbs.py:1296-1304`) and the host leg (`verbs.py:1306-1311`) — no
    `CompileError` from the never-creates-files compiler (§4.5B).
4c. **Input seam (§4.4):** `_resolve_destination` (`verbs.py:428`) carries
    the proposal's `variant`/`rules_topic`/`rules_paths` (never
    `None`-dropped at `verbs.py:442`); both unpackers (`verbs.py:1570`,
    `:2168`) thread them into `_resolve_target`. Bare
    `--dest claude-md:rules:<topic>` via `route_direct` (`verbs.py:1781`,
    `claude-md` one-motion-allowed) resolves to the **unpathed** rules
    target, not plain CLAUDE.md.
5. Project-scope `rules_paths` are per-pattern zero-match-refused at route
   time (`VerbError` naming the dead pattern) unless `--allow-empty-glob`
   (recorded); user-scope globs are parse-only.
6. `local` routes refuse via `git check-ignore` when `CLAUDE.local.md` is
   not ignored (P-A3), with the plain-words fix.
7. selfcheck check (d) resolves rules/local targets, checks the marker, and
   re-asserts project-scope globs (§5.2).
8. The over-cap WARNING fires on per-file cap **or** >5 topic files per
   scope (P-A9): `surface_fill`'s `claude-md` entry carries
   `rules_topic_count` and sets that entry's `over_cap` True when the count
   exceeds 5 (§8), feeding the existing WARNING path unchanged.
9. `destination_label`/`destination_path` are variant-aware off the single
   map (P-A11); the resolved path renders beside every label (P-A12).
10. Routing-doctrine §10 (`routing-doctrine.md:322`) is re-scoped to carry
    the (scope, always-loaded) domain and the precedence-winner language
    (P-A10/P-A10b); no `analyst.py` prompt-template change.
11. **Offer:** `compile_user_scope` emits `adopt_hint` exactly on UNMANAGED
    + variant==rules (threaded `offer_adopt`); `_host_phase` surfaces it on
    the bare-CLI path via the sync-warning channel; the review UI renders
    the interactive choice; both name one `chezmoi-adopt` entrypoint.
12. **Adopt:** `adopt_user_scope` runs porcelain-guard → `chezmoi add` →
    `commit_all_user_scope` + push, degrading commit/push failures to a
    warning without rollback (H-2); after it the target reads MANAGED and
    the offer no longer fires.
13. Invariants §12 hold: host/ledger commit_lock unbroken; C2 state machine
    unchanged in shape; single label map; H-2 no-rollback.
14. Test obligations §13 (1-19) are exercised; the chezmoi paths use a
    PATH-shimmed fake chezmoi (existing pattern), never real `~/.claude` or
    real chezmoi source.

---

## Grounding — empirical verification (this pass, HEAD `4950929`)

### Anchors re-verified post-C2 (all present at cited lines)

| Anchor | Line | Confirmed |
|---|---|---|
| `_parse_dest` | `verbs.py:404` | prefix branches for `reference:`/`new-skill:`; else membership check |
| `_resolve_target` | `verbs.py:543` | pure preflight |
| claude-md branch | `verbs.py:575-603` | user@576, project@585, skill-root fallthrough |
| **unguarded else fallthrough** | `verbs.py:600` | `target = root / "CLAUDE.md"` — reached by fallthrough, NOT a skill check (P-A13) |
| new-skill branch | `verbs.py:605-648` | no scope gate (parent F-2 note holds) |
| reference else-refuse | `verbs.py:657-662` | still the stale "chezmoi-managed CLAUDE.md" wording |
| `TargetSpec` | `verbs.py:477` | gains variant fields |
| `_resolve_destination` (INPUT seam) | `verbs.py:428` | `--dest` branch keeps qualifier (`:434`); **proposal branch drops variant** (`:442` `data["destination"], None`); unpacked at `verbs.py:1570`, `:2168` (§4.4A) |
| `route_direct` / one-motion | `verbs.py:1781`; `ONE_MOTION_UNROUTABLE` `:171`; `one_motion_allowed` `:182` | `claude-md` NOT unroutable → reaches `_resolve_target` (`:1813` parse, `:1882` resolve) (§4.4B) |
| `validate_skill_name` | `skill_scaffold.py:42/45` | "new-skill name … must be kebab-case" misnomer for a rules topic (NIT 2) |
| `_DEST_RE` refusal message | `proposals.py:297-299` | accepted-forms list omits the new variant forms (NIT 1) |
| `SURFACE_FILL_CAPPED_DESTINATIONS` | `verbs.py:179` | `("skill-md","claude-md")` — the `surface_fill` probe set (§8) |
| routing block build | `verbs.py:1913` + `resolve_record` `ledger_ops.py:693` | additional-keys pattern |
| `_apply_target` user leg | `verbs.py:1296-1304` | calls `compile_user_scope`; **no file bootstrap** (host leg bootstraps at 1306-1311) |
| `_compile_set` / `_routed_to` | `verbs.py` gather / `verbs.py:445-470` | filters on `destination`+`scope_pred` only — **no variant/topic filter** (§4.5A gap) |
| `compile_managed_file` | `compilers.py` | **refuses missing target** ("never creates target files") (§4.5B) |
| `surface_fill` computation | `verbs.py:1080` (`verbs.surface_fill`), threaded `cli.py:771-798` | site for the >5-topics datum (§8) |
| `_host_phase` sync surface | `verbs.py:1473-1476` | stderr + `warnings.append` (the hint channel) |
| `PROPOSAL_DESTINATIONS` | `ledger_ops.py:73` | `("skill-md","claude-md","reference","new-skill","hook")` — unchanged |
| `validate_proposal` | `ledger_ops.py:517` | schema seam |
| analyst prompt | `analyst.py:91` | `destination: <one of …>` |
| `_DEST_RE` | `proposals.py:92` | `…reference(:.+)?|new-skill:.+…` |
| routing-doctrine grammar | `routing-doctrine.md:98` | destination enum prose |
| routing-doctrine §10 (contradiction) | `routing-doctrine.md:322` | exists; emits `contradicts` (336-337) — re-scope its domain (§7) |
| labels (A1) | `models.py:141/120/166/134/234` | single-map widening |
| over-cap WARNING | `models.py:1199/1213` | `_budget_text`; stderr at route time |
| selfcheck `_check_drift` / `_target_for` | `selfcheck.py:261/183` | marker + target resolution |
| chezmoi helpers | `chezmoi.py:114/176/188/207/242/298` | `UserScopeResult`, `commit_all_user_scope`, `user_scope_capability`, `_drift_dirty_guard`, `compile_user_scope`, push |
| defaults | `verbs.py:158`, `compilers.py:88-89` | `DEFAULT_USER_CLAUDE_MD`, caps 10/150 |

### chezmoi sandbox transcript (isolated `--source`/`--destination`/`--config`; chezmoi v2.71.0; never real `~/.claude` or real source)

```
# a brand-new, previously-unmanaged file: dest/.claude/rules/subagents.md
$ chezmoi source-path <newfile>      # BEFORE add
  chezmoi: <newfile>: not managed
  rc=1                               # nonzero = UNMANAGED (matches C2's finding)
$ chezmoi managed <newfile>          # BEFORE add
  rc=0                               # rc0 even when unmanaged — NOT a discriminator (C2 note holds)
$ chezmoi add <newfile>
  rc=0                               # exit 0
  # source dir now has: SRC/dot_claude/rules/subagents.md  (chezmoi's dot_ encoding)
  # dotfiles repo status: "?? dot_claude/"  → file copied into source, LEFT UNTRACKED/UNCOMMITTED
$ chezmoi source-path <newfile>      # AFTER add
  rc=0                               # add makes the file MANAGED
$ git -C <source> log --oneline      # AFTER add, BEFORE commit
  fatal: your current branch 'main' does not have any commits yet
                                     # add alone did NOT commit → sync needs commit+push separately
$ git -C <source> add -A && commit && push   # the sync tail
  → remote receives the commit       # only now does it propagate
$ chezmoi diff <UNMANAGED target>    # relevant to the accept-path guard
  chezmoi: <target>: not managed
  rc=1                               # → cannot reuse _drift_dirty_guard step-1 (diff) pre-add; porcelain only
$ chezmoi add <already-managed unchanged file>
  rc=0, no repo change               # idempotent — a re-accept is harmless
$ python3 -c 'import fnmatch,re; re.compile(fnmatch.translate("photos [2024/**"))'
  → compiles cleanly                 # fnmatch does NOT raise on a bad "[" → "unparseable" folds into zero-match
```

**Pinned conclusions:** (1) a new user rules file reads UNMANAGED even when
`~/.claude/CLAUDE.md` is MANAGED; (2) `chezmoi add` exit 0 makes it MANAGED
but does **not** commit/sync — commit+push is separately required; (3) the
accept path uses the **porcelain** dirty check only, never the target-diff
(which errors on an unmanaged target); (4) there is no clean Python
"unparseable glob" mechanism, so **zero-match is the load-bearing guard**.
