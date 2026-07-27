# `new-skill` mechanism audit — self-learn

Date: 2026-07-26. All behavioural claims below were produced by running the
real CLI in a sandbox (`HOME`, `SELF_LEARN_HOME`, `XDG_CACHE_HOME`,
`XDG_RUNTIME_DIR`, `SELF_LEARN_CLAUDE_DIR`, `SELF_LEARN_TRANSCRIPTS_DIR` all
redirected under this scratchpad). No real state was touched:
`/home/komi/repos/claude-skills` and `/home/komi/repos/self-learn` both
report a clean `git status --porcelain`, and nothing under
`/home/komi/.claude/skills` was modified.

Sandbox layout:
- ledger home `…/sbx/ledger`
- skills root `…/sbx/skillsrepo` (git repo + `.claude-plugin/marketplace.json`
  + a copy of the *real* `claude-skills/install.sh`, + one hand-authored
  foreign plugin `existing-plugin`)
- project host `…/sbx/projrepo`
- redirected `$HOME` at `…/sbx/home`

---

## Answers up front

**Q1 — "if and when an agent chooses to create a new skill, do we actually
have the mechanisms in place to allow that to happen?"**

**Partly. The compiler works and produces a genuinely loadable skill, but an
agent cannot reach it end-to-end.** Three human-only steps sit in the path:
(a) an agent may not name the skill — the route refuses without a
human-typed `--dest new-skill:<name>`; (b) the route only writes files into
the skills-root repo — a human must run that repo's `install.sh` to make the
skill visible to Claude Code; (c) on a machine whose skills root has no
`.claude-plugin/marketplace.json`, the destination refuses outright and
nothing in self-learn will create one.

**Q2 — "Do we have the mechanisms in place to make it either a user scope or
project scope skill?"**

**No. Scope is not a parameter anywhere in the `new-skill` path.** Every
scaffold lands at `<skills_root>/plugins/<name>/skills/<name>/SKILL.md`, in
the single registered `skills_root`, regardless of the record's scope. There
is no flag, no qualifier grammar, and no proposal field for scope. What you
get *after* `install.sh` is a **user-scope skill** (`~/.claude/skills/<name>`
symlink) — but only because this user's `claude-skills/install.sh` chooses to
deploy that way; self-learn neither knows nor controls it. Project scope
(`<project>/.claude/skills/`) is entirely unimplemented — the string
`.claude/skills` appears in the CLI only inside two post-note prose strings
(`verbs.py:2171`, `verbs.py:2430`).

---

## 1. End to end: does it produce a working skill?

### 1.1 The route

```
$ sl route lrn-0000aaaa --dest new-skill:mouse-firmware
telemetry flush: 1 event → 2026-07.komi-hypr.jsonl
route lrn-0000aaaa → new-skill:mouse-firmware @ 9cd36c7 (ledger not pushed…; host not pushed…)
new skill scaffolded at plugins/mouse-firmware — run ./install.sh to symlink it
into ~/.claude/skills (M3-11); enrich the prose post-hoc whenever you like
rc=0
```

Files written into the skills root (nothing else):

```
plugins/mouse-firmware/.claude-plugin/plugin.json
plugins/mouse-firmware/skills/mouse-firmware/SKILL.md
```

plus an appended entry in `.claude-plugin/marketplace.json`. One host commit,
pinned subject:

```
222e0a6 self-learn: apply lrn-0000aaaa → plugins/mouse-firmware/skills/mouse-firmware/SKILL.md (new-skill)
```

`plugin.json` (exactly the three-key set the build plan pins):

```json
{
  "name": "mouse-firmware",
  "version": "0.1.0",
  "description": "Use when: About to flash the SM809Pro mouse firmware. Scaffolded by self-learn from routed lessons; enrich the prose post-hoc (plugin-dev optional)."
}
```

`SKILL.md` — well-formed frontmatter, authored-prose region, and a managed
section the ordinary compiler owns from then on:

```markdown
---
name: mouse-firmware
description: "Use when: About to flash the SM809Pro mouse firmware. Scaffolded by self-learn…"
---

# mouse-firmware

Scaffolded by self-learn (`route --dest new-skill`). Routed
lessons live in the managed section below; …

<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->
- **When about to flash the SM809Pro mouse firmware:** unplug the dongle first. *(lrn-0000aaaa)*
<!-- self-learn:end -->
```

The description is deterministic and seeded from the **first** routed
lesson's trigger (`skill_scaffold.scaffold_description`, `skill_scaffold.py:52`).
For a real skill this is a mediocre `description:` — it is the activation
signal Claude keys on, and it will read "Use when: <one lesson's trigger>"
until a human rewrites it. That is by design ("enrich the prose post-hoc"),
but it means the scaffold is a *stub that loads*, not a finished skill.

### 1.2 What `install.sh` actually does with it

Verified against the real `/home/komi/repos/claude-skills/install.sh` (copied
into the sandbox, run there with `HOME` redirected and `systemctl` stubbed).

Discovery is exactly as the build plan claims — **marketplace names plus the
skills-path glob, and no manifest validation whatsoever**:

- `install.sh:43` — `PLUGINS="$(jq -r '.plugins[].name' "$REPO/.claude-plugin/marketplace.json")"`
- `install.sh:46-49` — for each name, `if [ -d "$REPO/plugins/$name/skills/$name" ]` → symlink to `$HOME/.claude/skills/$name`, else print `WARN no skill dir`.
- `plugin.json` is **never read by install.sh**. Nothing validates it.

Dry run output (abridged):

```
== skills (live symlinks) ==
  link  ~/.claude/skills/existing-plugin -> …/skillsrepo/plugins/existing-plugin/skills/existing-plugin
  link  ~/.claude/skills/mouse-firmware  -> …/skillsrepo/plugins/mouse-firmware/skills/mouse-firmware
```

Real run, then reading through the symlink:

```
$ find $HOME/.claude/skills -maxdepth 1 -mindepth 1
…/sbx/home/.claude/skills/existing-plugin
…/sbx/home/.claude/skills/mouse-firmware
…/sbx/home/.claude/skills/skill-rules.json
$ head -3 $HOME/.claude/skills/mouse-firmware/SKILL.md
---
name: mouse-firmware
description: "Use when: About to flash the SM809Pro mouse firmware. …"
```

So the scaffolded skill **does** become an available skill — at
`~/.claude/skills/<name>/SKILL.md`, i.e. **user scope**, exactly the shape
every other claude-skills plugin has on this host (`/home/komi/.claude/skills/chezmoi
-> /home/komi/repos/claude-skills/plugins/chezmoi/skills/chezmoi`).

Two caveats found while running it:

- **The scaffold writes no `skill-rules.fragment.json`.** `install.sh:65-74`
  merges those fragments into `~/.claude/skills/skill-rules.json` for the
  `skill-activation-prompt` hook. A scaffolded skill is therefore loadable
  by Claude Code's native skill discovery but is **not registered with this
  host's activation-nudge hook**. (Unverified: whether that materially
  affects how often the skill fires — it is a third-party nudge layer, not
  the loader.)
- Pre-existing install.sh bug, unrelated to the scaffold: with zero fragment
  files, `jq -s 'add // {}'` on an empty glob emits nothing and the
  subsequent `--argjson frag` call errors with `invalid JSON text passed to
  --argjson`. Cosmetic here (the merge no-ops), but the message is alarming.

### 1.3 Is the scaffold a valid plugin?

`claude plugin validate .` in the sandbox skills repo, rc captured unpiped:

```
rc=0
⚠ Found 6 warnings:
  ❯ description: No marketplace description provided…
  ❯ plugins[1..5] plugin.json → author: No author information provided…
✔ Validation passed with warnings
```

So the scaffolded `plugin.json` is structurally acceptable to Claude Code's
own validator; only an `author` warning. (The earlier rc=1 run was my
sandbox marketplace missing a top-level `owner` — my seed's fault, not the
scaffold's.) Also verified: the scaffold's marketplace rewrite **preserves
unknown top-level keys** (`owner` survived) and only appends to `.plugins`.
It does reformat the whole file to 2-space JSON.

### 1.4 The human-only steps

1. **Naming.** `route` refuses a bare `--dest new-skill` and refuses a
   proposal-driven route entirely (§4 below). Only a human-typed
   `new-skill:<name>` gets through today.
2. **Deployment.** `install.sh` is never invoked by self-learn — the route
   just prints prose telling a human to run it.
3. **Prose enrichment.** The `description:` and body are stub text.
4. **(Fresh machine only)** hand-creating `.claude-plugin/marketplace.json`.

**The post-note is unconditional prose, not a check.** Deleting `install.sh`
from the skills root changes nothing:

```
$ git -C sbx/skillsrepo rm -q install.sh && git commit -q -m "no installer"
$ sl route lrn-0000eeee --dest new-skill:no-installer
route lrn-0000eeee → new-skill:no-installer @ a0c28cd …
new skill scaffolded at plugins/no-installer — run ./install.sh to symlink it into ~/.claude/skills (M3-11); …
rc=0
$ test -f sbx/skillsrepo/install.sh && echo YES || echo NO
NO
```

Note also that **self-learn's own `install.sh` does not deploy scaffolded
skills** — `/home/komi/repos/self-learn/install.sh:51-52` hard-links only
`plugins/self-learn/skills/self-learn`. The installer the post-note names is
a property of *this user's* `claude-skills` repo, which self-learn neither
ships nor verifies.

---

## 2. Scope

### 2.1 Scope is not a parameter

- `route --help` has no `--scope` flag. The only qualifier grammar
  (`_parse_dest`, `verbs.py:418-440`) spends `new-skill:`'s single colon slot
  on the **name**; `claude-md:` is the only destination with a
  parameterized-scope grammar (`claude-md:local`, `claude-md:rules:<topic>`).
- `_resolve_target`'s `new-skill` branch (`verbs.py:898-941`) **never reads
  `scope`**. Contrast the `claude-md` branch immediately above it
  (`verbs.py:869-896`), which branches three ways on scope.
- The target path is a literal: `root / "plugins" / name / "skills" / name /
  "SKILL.md"` (`verbs.py:919-920`), where `root` is the single registered
  `hosts.skills_root`.

Empirically — a **project-scope** record routed to `new-skill` lands in the
global skills root, not the project:

```
$ sl route lrn-0000cccc --dest new-skill:proj-thing     # record scope: project
rc=0
$ find sbx/skillsrepo/plugins/proj-thing sbx/projrepo/.claude -type f
…/sbx/skillsrepo/plugins/proj-thing/.claude-plugin/plugin.json
…/sbx/skillsrepo/plugins/proj-thing/skills/proj-thing/SKILL.md
```

(`sbx/projrepo/.claude/skills/` stayed empty.) This missing scope gate is
already a known, deliberately-deferred defect in the project's own specs:
`docs/specs/self-learn/drafts/c1-portability-defects-spec.md:638-639` —
*"`new-skill`'s missing scope gate (`verbs.py:605-648`) — a real latent
defect… Named so a reviewer knows it was seen."* — and
`docs/specs/self-learn/drafts/claude-md-parameterization-spec.md:142-146`.

### 2.2 No path-manipulation workaround gets you a native user skill

Pointing `skills_root` at `~/.claude` itself does **not** produce
`~/.claude/skills/<name>` — the hardcoded `plugins/<n>/skills/<n>` prefix
still applies:

```
$ sl host add $HOME/.claude --skills-root
$ sl route lrn-00003333 --dest new-skill:user-scope-try
rc=0
$ find $HOME/.claude -name SKILL.md -not -path '*/.git/*'
…/sbx/home/.claude/plugins/user-scope-try/skills/user-scope-try/SKILL.md
$ test -e $HOME/.claude/skills/user-scope-try && echo YES || echo NO
NO
```

Constraints on `skills_root` (`hosts.host_path_problem`, `hosts.py:283-315`):
must exist, must be a git repo, must not be the ledger home. Exactly one may
be registered (`hosts.py:359-362` replaces rather than appends).

### 2.3 Where scope would have to become a parameter

Minimum set, if the machinery were to gain user/project scope:

| Site | What it would have to become |
|---|---|
| `verbs.py:418-440` `_parse_dest` | a grammar that carries both a name and a scope (the single `:` slot is spent on the name) |
| `verbs.py:898-941` `_resolve_target` new-skill branch | branch on scope like the `claude-md` branch does; resolve a *non-marketplace* target for user/project scope |
| `verbs.py:919-920` | the `plugins/<n>/skills/<n>` literal is marketplace-shaped; a user-scope target is `~/.claude/skills/<n>/SKILL.md`, a project-scope target is `<host>/.claude/skills/<n>/SKILL.md` |
| `verbs.py:912-918` marketplace precondition | must not apply to non-marketplace scopes (there is no marketplace for `~/.claude/skills`) |
| `_apply_new_skill`, `verbs.py:1720-1770` | `plugin.json` + marketplace append are marketplace-only artifacts; a user/project-scope skill needs neither |
| `verbs.py:2166-2175`, `verbs.py:2430` post-notes | "run ./install.sh" is false for a scope that needs no installer (a user-scope skill written straight into `~/.claude/skills` is live immediately) |
| `verbs.py:2510-2530` commit-drift | dirty-checks `target` AND `marketplace.json`; the second has no analogue off-marketplace |
| `ledger_ops.py:796-806` | `routing.new_skill` would need a companion scope field so recompile/drift find the right target |
| `selfcheck.py:194`, `:326` | drift classification reads the new-skill target off the same assumption |
| `ui/models.py:86-88` `PARAMETER_FREE_DESTINATIONS` | still excludes new-skill; scope makes it *more* parameterized, not less |

A user-scope variant is additionally in tension with the retired-chezmoi
ruling and with `hosts.py`'s "canon hosts must be committable" rule —
`~/.claude` is not a git repo on this machine, so a user-scope skill would be
the first canon surface with no host repo. That is a values question for the
user, not a mechanical one.

---

## 3. Fresh install / no skills root

Both refusals fire cleanly **before any ledger or host commit**; the record
stays pending.

**No skills root registered:**

```
$ sl route lrn-0000aaaa --dest new-skill:mouse-firmware
self-learn route: no skills root registered — the scaffold lands under it;
self-learn host add <path> --skills-root
rc=1
```

**Skills root registered, no `.claude-plugin/marketplace.json`:**

```
$ sl route lrn-0000aaaa --dest new-skill:mouse-firmware
self-learn route: skills root …/sbx/skillsrepo-nomarket has no
.claude-plugin/marketplace.json — the scaffold appends an entry to an
EXISTING marketplace (08 §8.1); it never creates one
rc=1
```

**`host add --skills-root --init` does not close the gap.** The `--init` leg
(`hosts.py:228-270`) does `git init` + an empty root commit and nothing else:

```
$ sl host add …/sbx/freshskills --skills-root --init
$ find …/sbx/freshskills -maxdepth 2 -not -path '*/.git/*'
…/sbx/freshskills
…/sbx/freshskills/.git
$ sl route lrn-00002222 --dest new-skill:fresh-thing
self-learn route: skills root …/sbx/freshskills has no .claude-plugin/marketplace.json … rc=1
```

**Conclusion:** on a brand-new machine, `new-skill` is unreachable until the
user hand-authors a marketplace manifest (and, for deployment, an
`install.sh`). Neither is generated, templated, or documented by the route's
refusal message — the refusal names the *state* but not the *fix*. The
project already records this gap and deliberately declined to close it:
`c1-portability-defects-spec.md:640-660` (§5, "Consequence of Ruling 1 that
this spec does NOT take") — *"on a fresh machine, the `new-skill` destination
is unreachable for exactly the reason the ruling objects to. This spec does
not change that."*

This is a plausible contributor to the 0-of-28 selection rate, alongside the
naming pin.

---

## 4. Collision rule M3-9

Behaves exactly as `08-build-plan.md:469` describes.

**Refuses to inject into a foreign SKILL.md** (a plugin dir with no
self-learn managed section):

```
$ sl route lrn-0000bbbb --dest new-skill:existing-plugin
self-learn route: plugins/existing-plugin already exists and is a foreign
authored plugin (no self-learn managed section in its SKILL.md) — refusing to
inject (M3-9); pick another name or route to its skill-md through review
rc=1
```

Record stayed pending; host `git log` unchanged (still at the pre-route
commit). The check is `target.is_file() and BEGIN_MARKER in target.read_text()`
(`verbs.py:925-934`).

**Appends into a self-learn-scaffolded one**, with the marketplace entry
written exactly once:

```
$ sl route lrn-0000bbbb --dest new-skill:mouse-firmware
rc=0
<!-- self-learn:begin … -->
- **When about to flash the SM809Pro mouse firmware:** unplug the dongle first. *(lrn-0000aaaa)*
- **When about to unpair the mouse dongle:** unplug the dongle first. *(lrn-0000bbbb)*
<!-- self-learn:end -->
$ jq -r '.plugins[].name' .claude-plugin/marketplace.json
existing-plugin
mouse-firmware
```

The second route also correctly suppressed the "new skill scaffolded" post-note
(it is gated on `compile_result.scaffolded`, `verbs.py:2173-2174`).

Also verified: bad names refuse (`validate_skill_name`, `skill_scaffold.py:42-49`),
and the marketplace refusal fires before the ledger commit.

---

## 5. Scoping the naming ruling

> *"the analyst should be able to name the skill for presentation to the user.
> The user gets to decide if they'll keep the name, change the name, or route
> to another surface."*

### 5.1 What already exists (do not rebuild)

Three parts of this are **already built and tested**, and are dead code today:

- **The proposal file already tolerates the field.** Empirically: a proposal
  containing `new_skill: govee-scenes` passes `validate_proposal` and
  round-trips through `write_proposal`/`stamp_proposal` unchanged (keys read
  back: `already_canon, already_canon_reason, alternates, analyzed_at,
  destination, model, new_skill, rationale, record_sha`). `validate_proposal`
  (`ledger_ops.py:518-568`) has no unknown-key rejection.
- **The review UI already renders the name.** `models._build_change`
  (`models.py:1275-1287`) reads `proposal.get("new_skill")`:
  ```
  WITH NAME : new-skill | new skill scaffold: govee-scenes | scaffold_name= govee-scenes
  NO NAME   : new-skill | new skill scaffold (name chosen at route time) | scaffold_name= None
  ```
  With existing tests at `ui/tests/test_models_detail.py:217-233`.
- **The pane already accepts a named dest.** `proposals.py:98-99` `_DEST_RE`
  matches `new-skill:.+`, so an agent in the Iterate pane can *already*
  propose `route <id> --dest new-skill:<name>` for human confirm. The
  "analyst never names it" pin therefore only ever bound the analyst
  *proposal-sibling* path, not the pane path.

**The single load-bearing blocker is `verbs.py:512`** — `_resolve_destination`
hard-drops the qualifier to `None` when the destination comes from a
proposal. Proven:

```
$ sl route lrn-0000dddd          # proposal has destination: new-skill, new_skill: govee-scenes
self-learn route: new-skill needs a name — the name slot is the human's call
(08 §8.1): route --dest new-skill:<name>
rc=1
```

### 5.2 Complete change list (file:line)

**A. Code — required**

| file:line | current | change |
|---|---|---|
| `plugins/self-learn/cli/src/self_learn/verbs.py:510-516` | `_resolve_destination` returns `_Destination(data["destination"], None, …)` — the `None` is the qualifier slot | read `data.get("new_skill")` into the qualifier for `destination == "new-skill"` (mirror the `reference` case if one is added) |
| `verbs.py:898-904` | refuses whenever `ref_name is None` | keep the refusal only when *neither* `--dest` nor the proposal supplies a name; the message must change (it currently asserts the name is the human's call) |
| `verbs.py:418-440` `_parse_dest` docstring | "`new-skill:<name>` names the skill to scaffold (08 §8.1 — the name slot is the human's call)" | drop the pin clause |
| `verbs.py:163-173` `ONE_MOTION_UNROUTABLE` comment | "`new-skill`'s name slot is a route-time human call (08 §8.1)" | re-justify: the one-motion refusal now rests on "creates a new loadable surface", not on the naming pin |
| `verbs.py:2229-2231` (`route_direct` one-motion hint) | "…`--dest new-skill:<name>` — the name is a route-time human call" | reword |
| `plugins/self-learn/cli/src/self_learn/teach.py:373-374` | one-motion refusal ends `"new-skill:<name>\`"` | reword to match |
| `plugins/self-learn/cli/src/self_learn/ledger_ops.py:518-568` `validate_proposal` | no `new_skill` validation | add optional `new_skill`: kebab-validated via `skill_scaffold.validate_skill_name`, meaningful only when `destination == "new-skill"` (mirror `_validate_rules_fields`'s optional-field pattern at `ledger_ops.py:571+`) |
| `plugins/self-learn/cli/src/self_learn/analyst.py:85-101` (`_PROMPT_TEMPLATE`, dest line at `:91`) | no name slot in the emitted YAML shape | add `new_skill: <kebab-slug — required iff destination is new-skill>` |

**B. Code — decide, then possibly change**

| file:line | note |
|---|---|
| `ui/src/self_learn_ui/models.py:293-308` `correct_destination` | returns `(None, None)` for `new-skill`, so the action bar shows no default dest. If the human is to *accept* the analyst's name with one key, this needs to surface `new-skill:<name>` as the armable value. |
| `ui/src/self_learn_ui/models.py:86-88` `PARAMETER_FREE_DESTINATIONS` | `new-skill` excluded because "needs structure a cycling key cannot supply". With a proposal-supplied name the structure now exists — but *changing the name* still needs a text input the cycle key cannot give. This is the ruling's "change the name" leg and it has **no UI today**. |
| `ui/src/self_learn_ui/routes.py:213-222` `cycle_destination` docstring | asserts new-skill is "structurally unreachable from this function" — revisit alongside the above |
| `ui/src/self_learn_ui/proposals.py:305-307` | the refusal message lists accepted dest forms; unchanged in grammar, but worth re-reading once the analyst path also names skills |
| `ui/src/self_learn_ui/models.py:1278-1281` | the `else` branch string "new skill scaffold (name chosen at route time)" becomes the *unnamed-proposal* fallback rather than the norm |

**C. Docs / spec**

| file:line | change |
|---|---|
| `plugins/self-learn/skills/self-learn/references/routing-doctrine.md:262-263` | **the pin itself**: "A `new-skill` proposal never names the skill — the name is the human's call at route time" → reversed |
| `routing-doctrine.md:143-152` (schema block, dest line at `:147`) | add the `new_skill:` field to the emitted-YAML example |
| `routing-doctrine.md:22` | the `new-skill` row of the destination table — optional, may want to mention the name |
| `docs/specs/self-learn/08-build-plan.md:469` | "(the name slot is the confirmed §4 human call)" → reversed |
| `plugins/self-learn/skills/self-learn/references/pane-surface-model.md:59-62` | "The last two need structure a proposal must already carry" — now literally true for new-skill via the analyst path too |
| `plugins/self-learn/skills/self-learn/SKILL.md:99` | "new-skill is `--dest new-skill:<name>`" — still true but no longer the only route |
| `docs/specs/self-learn/drafts/fast-lane-spec.md:54` | rationale for new-skill = FULL lane cites "the human-named skill slot is a judgment"; re-justify (draft) |
| `docs/specs/self-learn/drafts/c1-portability-defects-spec.md:638-639`, `claude-md-parameterization-spec.md:142-146` | reference the naming pin in passing; drafts, informational |

**D. Tests asserting the old behaviour**

| file:line | assertion |
|---|---|
| `cli/tests/test_route_cli.py:379-386` | `test_route_cli_bare_new_skill_exits_1_naming_the_recipe` — asserts rc 1 and `"new-skill:<name>"` in stderr for a bare `--dest new-skill` |
| `cli/tests/test_verbs.py:235-242` | `test_new_skill_without_name_refused` — same, at the verb level; comment cites "the name slot is the human's call (08 §8.1)" |
| `cli/tests/test_new_skill.py:153-158` | `test_bare_new_skill_needs_a_name` — comment "the name slot is the confirmed §4 human call" |
| `cli/tests/test_new_skill.py:177-187` | **`test_proposal_new_skill_without_name_names_the_human_call`** — the direct inverse of the ruling: writes a `destination: new-skill` proposal with no name and asserts the route refuses with `"new-skill:<name>"`. Must become "an *unnamed* proposal still refuses; a *named* one routes." |
| `cli/tests/test_one_motion_config.py:127-131`, `:278-294` | one-motion refusal/enable for `new-skill` — behaviour unchanged, but the refusal *string* is edited by change A, so the matchers may need updating |
| `ui/tests/test_models_detail.py:217-233` | already covers both named and unnamed previews — these become live rather than hypothetical |

**E. New coverage the ruling implies (not currently existing anywhere)**

- A route driven purely by a proposal that carries `new_skill` (today: refuses).
- A `--dest new-skill:<other-name>` **overriding** a proposal's suggested name (the "change the name" leg — the CLI override path already works mechanically; nothing asserts precedence).
- Analyst-emitted `new_skill` surviving `stamp_proposal` (stamping rewrites `record_sha`, and for hooks it *regenerates* `script` from structured input, `ledger_ops.py:668-690` — decide whether the name is model-trusted like `rationale` or CLI-regenerated like `script`. **This is a real design question the ruling does not settle.**)
- `validate_proposal` rejecting a non-kebab `new_skill`, and rejecting `new_skill` on a non-new-skill destination (mirror `ledger_ops.py:796-806`'s `routing.new_skill` rule).

### 5.3 What the ruling does *not* reach

The ruling makes the name proposable. It does not make `new-skill` usable
end-to-end. The other two human-only steps (§1.4) and the fresh-install gap
(§3) are untouched by it, and the "change the name" leg has no UI affordance
today — the review action bar has a destination *cycle key*, not a text
field. If the intent is "the user can retype the name in review", that is a
new UI element, not an edit to an existing one.

---

## 6. Things I could not verify

- Whether a skill deployed *only* as `~/.claude/skills/<n>/SKILL.md` without a
  `skill-rules.json` entry fires as reliably as one with a fragment. The
  activation-prompt hook is a third-party nudge layer; I confirmed the
  scaffold writes no fragment, but not the behavioural consequence.
- Whether a plugin sitting at `~/.claude/plugins/<n>/` (the §2.2 probe result)
  is loadable by Claude Code by any route. I only established it is **not** at
  the documented user-skill path.
- Anything about the real `/home/komi/repos/claude-skills` beyond reading its
  `install.sh` — I never routed into it.
