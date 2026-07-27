# Is the CLAUDE.md monoculture structural?

Source-grounded investigation, 2026-07-26. Every claim below cites a file
and line that was read, or a command that was run in a sandbox. Anything
unverified is marked **[UNVERIFIED]**.

Sandbox discipline: all live probes ran with `HOME`, `SELF_LEARN_HOME`,
`XDG_CACHE_HOME`, `SELF_LEARN_CLAUDE_DIR`, `SELF_LEARN_TRANSCRIPTS_DIR`,
`XDG_RUNTIME_DIR` redirected to
`/tmp/claude-1000/…/scratchpad/sandbox`. `~/.self-learn` was read only;
`git -C ~/.self-learn status --porcelain` is empty at HEAD `bdd159e`, and
`git status --porcelain` in the repo is empty.

---

## Verdict

**The hypothesis is confirmed in substance and wrong in one of its
premises. The funnel is real, mechanical, and stronger than stated — but
its cause is not "preconditions that are rarely satisfiable." On this
host every precondition for every destination is satisfied. The cause is
that the destination set is a pure function of a scope tag frozen at
capture time, and for the scope that carries 9 of 11 pending records that
function returns a set of size one.**

Three separate mechanisms compose:

1. **Scope→destination is a total function, decided before review.**
   `models.py:98-102` maps user scope to `("claude-md",)` — a
   one-element tuple. The CLI agrees: `verbs.py:950-955` refuses
   `reference` at user scope outright, and `verbs.py:836-840` refuses
   `skill-md` for any non-`skill:` scope. A user-scope record has exactly
   one parameter-free destination, at the CLI *and* at the UI, by
   construction.

2. **Scope is immutable for user and skill buckets.** `rehome` is
   project→project only (`verbs.py:2838-2839`); live sandbox run returns
   rc=1: *"record … lives in a non-project bucket (user) — rehome is
   project→project only (M1); user-scope targets and skill/user-scope
   sources are dated future work, not silent extensions."* A user-scope
   record cannot be moved to a skill bucket even when a skill would fit.
   The only escape is reject-and-recapture.

3. **The two destinations that could open the funnel are unreachable
   from every acceptance surface a reviewer uses.** `new-skill` and
   `hook` are absent from `PARAMETER_FREE_DESTINATIONS`
   (`models.py:88`), so the `o` cycle cannot reach them
   (`routes.py:214-227`). And the Approve button — which sends
   `route <id>` with **no** `--dest` whenever the suggestion is not
   parameter-free (`models.py:300-301` returns `(None, None)`;
   `routes.py:112-115` only appends `--dest` `if dest`) — *fails* on a
   `new-skill` proposal. Verified live, rc=1.

So no amount of good per-record reasoning can diversify the outcome. The
10 live proposals prove it: every one of the 10 user-scope proposals says
`claude-md`, and the three that list `new-skill` as the alternate say so
in prose that explicitly defers to a future the system has no path to
reach (§4 below).

**Where the hypothesis is wrong:** it predicts that `new-skill` never
fires because its preconditions are unsatisfiable. They are satisfiable
here — `/home/komi/repos/claude-skills` is registered as `skills_root`
(`~/.self-learn/hosts.yaml`) and carries
`.claude-plugin/marketplace.json` with 10 plugins. A sandbox route to
`new-skill` with those two conditions met succeeded, rc=0, scaffolding a
plugin. `new-skill` does not fire because **no surface a reviewer touches
can express it**, not because the machinery refuses. That is a cheaper
problem than the hypothesis assumed — see §8.

---

## 1. Per-destination preconditions

The authority is `verbs._resolve_target` (`verbs.py:806-967`), the single
pre-flight resolver that both `route` and the UI's read-only fill probe
call.

| Destination | Precondition | Checked where | Who must satisfy it |
|---|---|---|---|
| `claude-md` (plain) | **user scope: none checked at pre-flight.** `verbs.py:869-877` resolves the path and runs only a chezmoi drift check; it never tests `target.is_file()`. project scope: host registered + sound (`_project_host_or_refuse`, `verbs.py:623-641`). skill scope: `skills_root` registered (`verbs.py:887-891`) | route-time, but *incompletely* | nobody, at user scope |
| `claude-md` `variant: rules` | user or project scope only (`verbs.py:769-774`; skill scope is the P-A13 deferral); a `rules_topic` kebab slug; project scope additionally requires every glob in `rules_paths` to match ≥1 file or `--allow-empty-glob` (`verbs.py:675-693`) | route-time | analyst (must emit `variant`+`rules_topic`) — **or nobody, if the human types `--dest claude-md:rules:<topic>`** |
| `claude-md` `variant: local` | project scope only (`_resolve_local_target`) | route-time | analyst or `--dest claude-md:local` |
| `skill-md` | scope must start `skill:`; `skills_root` registered and sound; **`SKILL.md` must already exist** — *"the compiler never creates target files, only the section inside an existing one"* (`verbs.py:843-847`) | route-time | a human, earlier, who created the skill |
| `reference` | scope must be `skill:*` or `project`. **User scope is refused by name**: *"the user host is the chezmoi-managed CLAUDE.md, it has no references dir (doc 13 §2)"* (`verbs.py:950-955`). A named file must already exist (`compilers.py:353-357`); `GOTCHAS.journal.md` refused by name (`compilers.py:348-352`) | route-time | analyst may pick it only if scope allows |
| `new-skill` | (a) **a name, supplied at route time and nowhere else** (`verbs.py:899-903`); (b) `skills_root` registered (`verbs.py:906-910`); (c) `.claude-plugin/marketplace.json` must already exist — *"the scaffold appends an entry to an EXISTING marketplace (08 §8.1); it never creates one"* (`verbs.py:912-918`); (d) no foreign-plugin collision (`verbs.py:921-934`) | route-time | **the human, typing a CLI flag** |
| `hook` | the on-disk proposal must **be** a hook proposal carrying the full §5.1 block — `hook: {tools, path_regex, deny_message}` plus 2–3 allow + 2–3 deny replay examples (`ledger_ops.py:426-454`, `_HOOK_EXAMPLES_MIN/MAX` at `:412`); behavior records only; `settings.json` registration stays manual afterwards (03 S-10) | proposal-validation time **and** route time | the analyst, at authoring time — not retrofittable |

**Analyst-checkable vs route-time.** The analyst has the record (hence
its scope) and the doctrine, and reads the candidate-target canon excerpt
(`worker.py:544-578`). It can therefore self-check scope validity for
`skill-md`/`reference`/`rules`. It **cannot** check `skills_root`
registration, marketplace presence, host soundness, or `SKILL.md`
existence — those live in `hosts.yaml` and on disk, and the analyst's
tool set is `Read,Grep,Glob` (`analyst.py:78`) with no pointer to the
registry. And it is never told the cap fill: `surface_fill` is computed
only for the UI's Detail render (`routes.py:301-303`,
`verbs.py:1382-1494`) and never reaches the analyst prompt
(`worker.py:581-614`).

**The asymmetry that matters.** `claude-md` at user scope is the only
destination whose *target-existence* precondition is not checked at
pre-flight. Sandbox probe with no `~/.claude/CLAUDE.md`:

```
$ self-learn route lrn-cdff8d21 --dest claude-md --no-push   # rc=0
self-learn: HOST PHASE FAILED after the ledger commit (managed target does not
exist: …/home/.claude/CLAUDE.md — the compiler never creates target files …)
— canon is stale, never lost (H-2); run `self-learn recompile` to repair
route lrn-cdff8d21 → claude-md @ c90480a
```

The record is marked routed, the verb exits 0, and the lesson is not in
canon. Compare `skill-md`, whose identical missing-file condition raises
a `VerbError` *before* the ledger commit (`verbs.py:843-847`). So from
the reviewer's seat `claude-md` never refuses — including when it should.

**Exception worth naming: `variant: rules` bootstraps its own file.**
Sandbox, with `~/.claude/rules/` nonexistent:

```
$ self-learn route lrn-489cc5e2 --dest claude-md:rules:probe-topic --no-push
rc=0 · wrote …/home/.claude/rules/probe-topic.md
```

It is the **only** destination in the system that creates a surface that
did not exist. Load-bearing for §8.

---

## 2. The user-scope funnel, stated mechanically

`models.py:88-102`:

```python
PARAMETER_FREE_DESTINATIONS: tuple[str, ...] = ("skill-md", "claude-md", "reference")
_SCOPE_DESTINATIONS: dict[str, tuple[str, ...]] = {
    "skill": PARAMETER_FREE_DESTINATIONS,
    "project": ("claude-md", "reference"),
    "user": ("claude-md",),
}
```

`destinations_for_scope` (`models.py:278-283`) is the single scope
predicate used by (a) the `o` cycle (`routes.py:223`), (b) the
`correct_destination` default (`models.py:299`), and (c) the budget-row
builder (`models.py:1360`). For a user-scope record it returns a
one-tuple. The template already knows this and apologises for it —
`action_bar.html:196-202` drops `data-key-action` and substitutes
`data-noop-hint="only one destination fits this lesson's scope"` when
`(_cycle | length) == 1`. The monoculture is a **shipped, documented UI
state**, built as a fix for a "silent no-op" bug report (F5-1).

Live distribution, recomputed from `~/.self-learn` (not taken on faith):

| status × destination | count |
|---|---|
| routed → `reference` | 14 (all `skills/home-assistant`) |
| routed → `claude-md` | 10 (5 `user`, 5 across 4 project buckets) |
| routed → `hook` | 3 (1 `user`, 1 `skills/chezmoi`, 1 project) |
| routed → `skill-md` | 1 (`hypr-doctor`) |
| routed → `new-skill` | **0** |
| pending (true) | 11 · deferred 2 |
| pending proposals → `claude-md` | 10 (all user bucket) |
| pending proposals → `skill-md` | 2 (`hypr-doctor`) · `reference` 1 (`home-assistant`) |
| routed with any `variant:` | **0** |

The 14 `reference` routes are a single skill's import backlog, and the
1 `skill-md` route plus 2 `skill-md` proposals are one skill each. Strip
the skill buckets and the picture is: **every user- and project-scope
lesson this system has ever routed went to a CLAUDE.md, except one
hook.**

---

## 3. `new-skill`, traced end to end — the smoking gun

Four doors, three of them closed.

**Door 1 — the UI Approve button.** `correct_destination`
(`models.py:286-307`) returns `(None, None)` for any suggestion not in
`PARAMETER_FREE_DESTINATIONS`, i.e. for `new-skill`. `build_argv`
(`routes.py:112-115`) appends `--dest` only `if dest`. So Approve sends
bare `route <id>`. `_resolve_destination` then reads the proposal and
returns `_Destination(data["destination"], None, …)` — `ref_name`
hard-coded `None` at `verbs.py:512`. `_resolve_target` raises. Live:

```
$ self-learn route lrn-cdabaeec --no-push        # proposal: destination: new-skill
route rc=1
self-learn route: new-skill needs a name — the name slot is the human's call
(08 §8.1): route --dest new-skill:<name>
```

**A doctrine-compliant `new-skill` proposal is structurally
un-approvable.** Doctrine pins the analyst *must not* name the skill
(`routing-doctrine.md:262-263`: *"A `new-skill` proposal never names the
skill — the name is the human's call at route time"*), and the proposal
schema has no name slot (`ledger_ops.py:518-568`; my sandbox
`proposal validate` on a bare `new-skill` proposal returned rc=0). The
one field that would make it routable is the one doctrine forbids.

**Door 2 — the `o` cycle.** Not in the set (`models.py:88`;
`routes.py:214-218` documents this as *"structurally unreachable from
this function"*). `action_bar.html:221` renders the consolation prize:
`hook / new-skill need Iterate — not cycle-reachable`.

**Door 3 — the agent pane ("Iterate").** The pane's `propose_verb` tool
accepts a `dest` string validated by `_DEST_RE`
(`proposals.py:97-100`), which admits `new-skill:.+` — **a name is
required; bare `new-skill` does not match**. Confirmed by the refusal
text at `proposals.py:304-308`. The pane's dest is passed verbatim to the
CLI (`routes.py:2217-2225` → `build_argv`), so this door *works* — but
only if the pane agent violates `routing-doctrine.md:262` by inventing
the name itself. The pane agent is charter-bound to that same doctrine
(`pane-charter.md:31`: *"You are the routing analyst described in
routing-doctrine.md"*). Doctrine and the UI's own grammar are in direct
contradiction on this one point.

**Door 4 — the CLI.** Works. Verified end to end in the sandbox, with
each precondition failing loudly and in order:

```
$ self-learn route <id> --dest new-skill:sandbox-probe --no-push
rc=1  no skills root registered — the scaffold lands under it; self-learn host add …
# after host add --skills-root:
rc=1  skills root … has no .claude-plugin/marketplace.json — the scaffold appends
      an entry to an EXISTING marketplace (08 §8.1); it never creates one
# after creating marketplace.json:
rc=0  route lrn-cdabaeec → new-skill:sandbox-probe @ b856b52
      new skill scaffolded at plugins/sandbox-probe — run ./install.sh …
```

On the real host both host preconditions are already met. **The scaffold
machinery is fine. The naming ceremony is the whole blocker**, and it
exists in exactly one place a reviewer can perform it: a shell.

**A fifth structural blocker, upstream of all four.** Doctrine's
winning condition for `new-skill` is *"a lesson **cluster** that wants to
be its own skill"* (`routing-doctrine.md:22`), but §5 pins *"One record,
one proposal"* (`:182`). The worker does see a batch
(`worker.py:581-614`) — and it can write a merge proposal — but a merge
proposal's schema (`ledger_ops.py:626-655`) carries `cluster_id`,
`records`, `suggested_survivor`, `rationale`, `model`, `analyzed_at` and
**no destination**. Merges are de-duplication only. There is no artifact
in the system that can say "these three distinct lessons are a skill."
The destination whose trigger is a set property has no set-shaped input.

---

## 4. What the live proposals actually say

Three pending proposals list `new-skill` as the alternate, and each one
describes the escalation as conditional on a future event:

- `lrn-4b8c3ec2`: *"If agent-driven experiential UI walkthroughs recur
  enough to want their own methodology doc, `new-skill` is the natural
  escalation, listed as alternate."*
- `lrn-4f89e33a`: *"new-skill stays a listed alternate: **a second**
  fixture-design lesson would justify pulling both into a dedicated
  testing-methodology skill instead of growing this managed section
  further."*
- `lrn-4ffc006f`: *"if that becomes a dedicated skill, this fact belongs
  in its reference file instead of here."*

These are locally correct and jointly inert. `lrn-4f89e33a` names the
exact trigger — *a second lesson* — and `lrn-4ffc006f` **is** a second
lesson in the same cluster (it cross-references `lrn-4b8c3ec2` by id).
The condition is met in the live queue and nothing fires, because
nothing in the system evaluates a condition across records at routing
time. The analyst notices the cluster in prose and has no field to put
it in.

Two more list `hook` (`lrn-547d8eb6`, `lrn-74b8e65a`) with careful,
well-argued over-block analyses that conclude "escalate to hook only if
this recurs." Same shape: a conditional escalation with no mechanism.

---

## 5. `hook`, traced end to end

`hook` is reachable from the Approve button *if and only if* the on-disk
proposal is already a full hook proposal. `_validate_hook_extension`
(`ledger_ops.py:426-454`) requires `hook: {tools, path_regex,
deny_message}`; live probe with a minimal hook proposal:

```
$ self-learn proposal validate lrn-f0cb0d26     # rc=1
… schema-invalid — a hook proposal carries the structured compile input …
$ self-learn route lrn-f0cb0d26 --no-push       # rc=64
```

**An `alternates: [hook]` entry is not actionable in one motion by any
surface.** The two live examples (`lrn-547d8eb6`, `lrn-74b8e65a`) are
`claude-md` proposals, and a `claude-md` proposal *cannot* carry a hook
block — `ledger_ops.py:435-441` refuses `hook`/`examples`/`script` keys
on a non-hook destination. Taking the alternate therefore requires
re-authoring the YAML. Live:

```
$ self-learn route <id> --dest hook --no-push   # proposal says claude-md, alternates:[hook]
rc=1
self-learn route: proposal for lrn-f0cb0d26 proposes 'claude-md', not hook — a hook
route needs the §5.1 compile input; re-analyze or author a hook proposal
```

`route --help` confirms there is no `--hook-input` on `route` (only
`teach` has one). So the hook alternate's escalation path is: hand-edit a
YAML file, or re-run analysis with a directive. Not one motion, not two.

`ONE_MOTION_UNROUTABLE = frozenset({"new-skill", "hook"})`
(`verbs.py:173`) is a *separate*, config-gated policy on the
`teach --route` path only (`one_motion_allowed`, `verbs.py:184-190`;
03 S-10). It is not what blocks the review path. The review path is
blocked by the three mechanisms above, none of which is configurable.

---

## 6. Graduation: built, fired once, never where the pressure is

Cap pressure is real and measured. The live `~/.claude/CLAUDE.md` managed
section, counted with the compiler's own rule (entry lines between
`compilers.py:84-85` markers, `len(e.split())` per `compilers.py:216`):

```
entries: 5 / 10
words:  506 / 150   → over_cap = True, cap_reason = "words"
per-entry words: 81, 61, 67, 134, 163
```

**337 % of the word cap, at half the entry cap.** The word axis has been
the binding constraint since the third entry (81+61+67 = 209 > 150). The
five user-scope `claude-md` routes are dated `2026-07-14T07:32:27Z` and
then four in a 20-minute burst on `2026-07-25T04:03–04:23`. Every route
after the second printed the over-cap WARNING (`verbs.py:235-245`) and
applied anyway, exactly as `compilers.py:32-36` specifies.

Where does the pressure discharge? Nowhere. Cross-tabbing all resolved
records:

- 19 records carry `superseded_by: canon`. **18 of them have no routing
  destination at all** — they are the backlog importer's bulk-acknowledge
  door (02 §4), records that were never routed.
- **Exactly one** true graduation from a compiled managed section ever
  occurred: `lrn-6883f824`, `skills/hypr-doctor`, `skill-md` → `canon`.
- **Zero graduations from `~/.claude/CLAUDE.md`.** The only two
  user-scope `claude-md` records ever retired (`lrn-ca690038`,
  `lrn-d5f6b31b`) were *corrective* supersessions by successor records
  (`superseded_by: lrn-ea833a5b` / `lrn-dd9489b2`), not graduations.

Is graduation built? Yes — `verbs.graduate` (`verbs.py:2913-2990`) does
the full job including host-side entry removal, and the UI has a Graduate
button (`action_bar.html:182-187`) and a bulk route
(`routes.py:2490`). What is **not** built is the thing that would make a
human press it: the Front-page graduation-opener banner was cut.
`10-surface-build-plan.md:80` records the kill explicitly — *"`status
--json .sections_over_cap` **WAS DROPPED at U0** … It is **superseded**
by U17's new render-time, opt-in `list --json --surface-fill` field."*
And `forward/canon-lifecycle.md:23-41` (FW-6) still lists the open
question: *"does the web surface carry any equivalent of the
review-skill's graduation-pressure card, or does a web-only user simply
never learn the section is over cap beyond the Y-20 line?"* The answer,
from the code, is **no**: the only over-cap signal a web user gets is one
CSS class on one `<li>` on the Detail page of a record they are already
looking at (`detail.html:150`), plus a stderr WARNING at route time that
the UI shows in the evidence panel (`evidence.html:70`).

Nothing has ever pushed back. The pressure discharges into the file.

---

## 7. Is the cap a forcing function or an evictor?

**Neither. It is a passive annotation, and it fails open.**

- It never evicts. `compilers.py:32-36` and `:217-222`: *"At the cap the
  compiler STILL applies the new entry and returns a flagged result …
  nothing is dropped silently."* Empirically confirmed at 337 % fill.
- It never forces. It cannot reach the actor who would respond to it. The
  analyst — the only party that chooses a destination — is never given
  the fill number: `surface_fill` is computed inside `verbs.py:1382-1494`
  and consumed only by the Detail render path (`routes.py:301-303`); the
  worker prompt (`worker.py:581-614`) contains the doctrine, the card
  registry, the rejected-proposal digest and the record text, and no cap
  datum.
- Where it *would* force, the option set is empty. Even if the analyst
  saw "506 of 150 words," `destinations_for_scope("user")` is still
  `("claude-md",)`.
- Its one honest surface is aimed at the wrong axis. `_budget_text`
  (`models.py:1307-1344`) leads with *"this claude-md section already
  holds 5 of its 10 entries"* — the non-binding axis — and appends the
  word clause only as a tail. A reviewer reading "5 of 10" concludes
  there is headroom. There is none.

So the cap is a fail-open check in the shape lrn-ea833a5b already warns
about: it prints the same reassuring thing whether the surface is healthy
or 3.4× blown, because the number it leads with is not the one that
binds.

---

## 8. Smallest structural changes that would open the funnel

Ranked by cost, with the expected effect on distribution.

### Rank 1 — Instruct the analyst to use `variant: rules` at user scope. **Zero code.**

The valve already exists and has never been opened (0 of 28 routed
records carry a variant). It is the only self-bootstrapping destination
in the system — the sandbox proved it creates
`~/.claude/rules/<topic>.md` from nothing — and, critically, it is
**already approvable in one motion from the UI**: a proposal carrying
`variant`/`rules_topic` threads through `_resolve_destination`
(`verbs.py:513-515`) into `_resolve_target` (`verbs.py:1981-1983`) on the
bare `route <id>` the Approve button sends. No `--dest`, no cycle, no
CLI.

The cost is honest and must be stated: doctrine `§2a`/`§3` (lines 54-57,
95-99) correctly pins that an **unpathed** rules file costs exactly what
`claude-md` costs in context — it relieves the *entry* cap, not the token
cost. But the binding constraint here is the **word** cap at 337 %, and
splitting 506 words across topic files does relieve that, per file. Of
the five live entries, at least two name explicit file/tool triggers
(`notify-send`/swaync; the Agent-tool/subagent rule) that could carry
globs and become genuinely narrower.

Change: a paragraph in `routing-doctrine.md §2a` telling the analyst to
*prefer* `variant: rules` at user scope once the target section is over
its word cap — plus the §Rank-2 change so it can know that.

Expected effect: large. It is the only lever that moves the live queue
today without touching code.

### Rank 2 — Put `surface_fill` in the analyst's prompt. **~10 lines.**

`verbs.surface_fill(home, bucket_dir, scope)` already exists, is pure and
read-only, and is memoized per target. Call it in `worker._compose_prompt`
(`worker.py:617-645`) and render one line per record: *"claude-md
(user): 5/10 entries, 506/150 words — OVER CAP (words)."* Today the
analyst reads the raw canon excerpt (`worker.py:544-578`) and must
eyeball the fill, which no prompt asks it to do.

Expected effect: medium alone, large combined with Rank 1 — it supplies
the trigger the Rank-1 rule fires on.

### Rank 3 — Let the analyst name a `new-skill`. **~5 lines + a doctrine edit.**

Add an optional `new_skill: <kebab-name>` key to the proposal schema
(`ledger_ops.validate_proposal`, `:518`), thread it into
`_Destination.ref_name` at `verbs.py:510-516`, and reverse
`routing-doctrine.md:262-263` from "never names the skill" to "proposes a
name the human may overwrite at route time."

This alone converts `new-skill` from unapprovable to one-motion
approvable, and resolves the standing contradiction with
`proposals.py:99`'s `new-skill:.+` grammar (which already demands a
name). The human retains the veto — the name is visible on the card and
`--dest new-skill:<other>` still overrides.

Note the ordering constraint: the current doctrine text is a deliberate
pin ("the name slot is the human's call", 08 §8.1), so this is a **values
question for the user**, not a bug fix. Route it to them before building.

Expected effect: unblocks the three live proposals that already name
`new-skill` as their escalation. Moves 2–3 records out of `claude-md`
immediately.

### Rank 4 — Make the alternate actionable. **~30 lines UI.**

Render `alternates` as buttons that arm `route --dest <alt>` rather than
as inert prose (`detail.html:133-137` currently renders a comma list).
For `new-skill` the button prompts for a name (needs Rank 3 or a text
input); for `hook` it must instead route to Iterate, because
`--dest hook` on a non-hook proposal is refused by design
(`verbs.py:1155-1160`) and `route` has no `--hook-input`.

Expected effect: medium. Turns every "escalate if this recurs" rationale
from a note into a control.

### Rank 5 — Lift `reference` to user scope. **~15 lines + a design call.**

`verbs.py:950-955` refuses `reference` at user scope on a rationale that
is now stale: *"the user host is the chezmoi-managed CLAUDE.md, it has no
references dir."* Chezmoi was retired on this host on 2026-07-24 and
`~/.claude/` is an ordinary directory. A `~/.claude/references/LEARNINGS.md`
is mechanically trivial (`compile_reference` creates its own file,
`compilers.py:360-368`) and would give user scope the cap-free overflow
sink that every other scope has — the thing graduation is supposed to
graduate *into*.

The design call, which must go to the user: a user-scope references file
has **nothing pointing at it**. In a skill, `SKILL.md` gives Claude the
pointer; at user scope the pointer would have to be a line in
`CLAUDE.md`. Without that, "graduating to references" at user scope is
indistinguishable from deletion. Do not build this without deciding the
pointer.

Expected effect: large *if* the pointer question is answered; harmful if
it is not.

### Rank 6 — Widen `rehome`. **Large.**

`verbs.py:2838-2839` calls user/skill rehoming *"dated future work"*.
Widening it would make scope a revisable decision rather than a
capture-time ratchet, which is the deepest fix and the most expensive.
Listed for completeness; the four cheaper changes above should be tried
first, because they may make it unnecessary.

### Explicitly **not** recommended

Making the cap evict. It would silently drop routed lessons, which
violates 02 §4's own "nothing is dropped silently" and the H-2 "canon is
stale, never lost" posture. The cap's problem is that it does not reach
the decider, not that it is too gentle.

---

## 9. Side findings (in scope, not central)

1. **Latent excerpt bug.** `worker._canon_excerpt` (`worker.py:571-574`)
   searches for `"SELF-LEARN:BEGIN"` / `"SELF-LEARN:END"`. The real
   markers (`compilers.py:84-85`) are
   `<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->`
   — lowercase, parenthesised. The uppercase form appears nowhere in the
   file. For any target ≥ 200 lines the excerpt therefore silently falls
   back to `lines[:60] + "… (truncated)"`, i.e. the top of the file, and
   the analyst never sees the managed section it is routing into — which
   would break doctrine §10's contradiction check, whose stated input is
   *"the `*(lrn-…)*` lines already shown to you in the candidate-target
   canon excerpt"*. **Not currently firing**: the live
   `~/.claude/CLAUDE.md` is 54 lines, so the `< 200` whole-file branch is
   taken. It fires the moment the file grows — which the cap failure
   above makes likely.

2. **Dangling id reference in live canon.** The `lrn-ea833a5b` entry in
   `~/.claude/CLAUDE.md` ends *"is covered separately by lrn-ca690038"*,
   but `lrn-ca690038` is `superseded_by: lrn-ea833a5b` and its entry was
   dropped from the section by that supersession. The surviving text
   points at a lesson that no longer loads.

3. **`route` exits 0 on a failed host phase** (§1). Combined with the
   fact that the UI reads success from the exit status, a user-scope
   route whose target file is missing reports success. Real risk is low
   today (the file exists) but the failure mode is the fail-open shape.

---

## 10. What I could not verify

- **[UNVERIFIED]** Whether the M2 worker, given a batch containing
  `lrn-4b8c3ec2` + `lrn-4ffc006f` (which cross-reference each other),
  would in fact emit a merge proposal — I read the prompt
  (`worker.py:592-601`) and the merge schema but did not run a live
  analysis, which would have spent model tokens against the real ledger.
  The structural claim I *do* make is narrower and is verified: a merge
  proposal has no destination field, so even a correct merge cannot route
  to `new-skill`.
- **[UNVERIFIED]** Whether the pane agent, in practice, ever emits
  `new-skill:<name>` in violation of `routing-doctrine.md:262`. I verified
  the grammar admits it (`proposals.py:99`) and the confirm path passes it
  (`routes.py:2217-2225`); I did not run a pane session.
- **[UNVERIFIED]** The 2 `deferred` pending records' proposals — I read
  the 13 proposal files' machine fields but did not correlate deferral
  reasons.
- Rank-1's quantitative claim ("splitting 506 words across topic files
  relieves the word cap per file") follows from `compile_managed_text`
  computing `word_count` per target (`compilers.py:216`), which I read;
  I did not run a multi-topic split to measure it.
