# Is the `claude-md` monoculture a prompt problem?

Source-grounded investigation, 2026-07-26. All claims below are cited to
file:line in `/home/komi/repos/self-learn` or to files under
`/home/komi/.self-learn` (read-only). Nothing was mutated; no analyst run
was spawned.

---

## 0. Verdict, up front

**Partly — but the prompt is the second cause, not the first.**

The primary cause is not persuasion, it is **arithmetic**. At `scope: user`
the destination enum has five members and the CLI accepts **three** of them.
`skill-md` and `reference` are hard-refused by `verbs.py` before any
judgement is exercised:

- `plugins/self-learn/cli/src/self_learn/verbs.py:835-840`
  ```python
  if destination == "skill-md":
      if not scope.startswith("skill:"):
          raise VerbError(
              "skill-md destination needs skill:<name> scope, "
              f"got {scope!r} — use claude-md or reference"
          )
  ```
- `plugins/self-learn/cli/src/self_learn/verbs.py:943-955`
  ```python
  if destination == "reference":
      ...
      else:
          raise VerbError(
              "reference destination needs skill:<name> or project scope — "
              "the user host is the chezmoi-managed CLAUDE.md, it has no "
              "references dir (doc 13 §2)"
          )
  ```

So the real user-scope option space is `{claude-md, new-skill, hook}`.
Of those three, `hook` carries a superlative bar and a `kind: anti-pattern`
gate, and `new-skill` **does not appear in the doctrine's operative decision
procedure at all** (§2, lines 27-39). What is left is `claude-md`. Nine of
nine is not a preference; it is a residual.

The prompt problem is that **the doctrine never states this constraint**, so
the model re-derives it from scratch on every record and phrases the result
as a judgement ("no existing skill owns this"). That is what makes the
output indistinguishable from pattern-matching — and it is also what makes
the bias invisible to the human reading the card, because a forced answer is
being dressed as a considered one.

Second-order prompt causes, in order of leverage:

1. **§7's cost inversion** — the doctrine calls `claude-md` "the cheaper
   surface" in the one place it discusses `new-skill`/`hook`, while §3 calls
   user-scope `claude-md` "the most expensive destination in the system."
   The model consistently invokes §3's *phrase* to justify the destination
   §3 was written to discourage.
2. **`new-skill` is absent from §2's routing map**, has zero worked
   examples, and is the only destination with no test the model can answer.
   0/28 routed, 0/13 proposed.
3. **The prompt supplies claude-md's evidence for free and every other
   destination's evidence at a research cost the model is not asked to pay**
   — `_canon_excerpt` resolves exactly one target, keyed on scope, and there
   is no skills inventory anywhere in the prompt.
4. **Feedback is negative-only.** `_digest` tells the model what was
   *rejected*. Nothing tells it the distribution of what was *routed*.
5. **Doctrine still reads as if M3 is future tense** ("compile at M3"), while
   `commands/review.md:176` had to add a correction saying all five
   destinations compile now. The correction is in the human command file,
   not in the analyst's system prompt.

---

## 1. What actually produced these proposals

Two model passes exist, and it matters which one wrote the artefacts under
examination.

| | analyst (`analyst.py`) | worker (`worker.py`) |
|---|---|---|
| trigger | bare `teach --route` | kick-driven batch, cap 15 |
| system prompt | the doctrine file, via `--append-system-prompt` (`analyst.py:133-145`) | doctrine **inline in the user prompt** (`worker.py:606-607`) |
| tools | `Read,Grep,Glob` (`analyst.py:78`) | `Read,Grep,Glob` + scoped `Edit` under `proposals/` (`worker.py:275, 279-293`) |
| cwd | **unset** — `subprocess.run(argv, …)` at `analyst.py:182` inherits the caller's cwd | `cwd=str(home)` (`worker.py:1330`) |
| canon shown | **none** | one excerpt per record (`worker.py:544-578`) |
| card registry | not loaded | loaded (`worker.py:609-610`) |
| writes | `destination`/`alternates`/`rationale` only (`analyst.py:196-204`) | those + `card`/`lint`/`already_canon`/`contradicts` |
| retries | one parse attempt, no reprompt (`analyst.py:169-170`) | invalid output deleted + logged (`worker.py:918-921`) |

**All 13 sidecars carry a `card:` map ⇒ all 13 are worker output.** The
one-shot analyst's behaviour is therefore *unobserved* in this data. That is
worth flagging: the one-shot analyst is strictly worse-informed than the
worker (no canon excerpt at all, no registry, and an undefined cwd that makes
relative `Glob` meaningless), so if it is ever exercised it should be
expected to be *more* claude-md-biased, not less.

The 13: 3 skill-scope (1 `reference`, 2 `skill-md`), 10 user-scope (10
`claude-md`; one of the ten, `lrn-547d8eb6`, is deferred to 2026-08-24,
which is why the live count is 9).

---

## 2. The doctrine, read as a system prompt

`plugins/self-learn/skills/self-learn/references/routing-doctrine.md`
— 3,662 words, 11 sections.

### 2.1 Word budget per section

```
§1  The destinations                            182
§2  The routing map                             104
§2a claude-md's variant                         306
§3  The narrowest-surface bias                  355
§4  Repo conventions                            145
§5  What a good proposal looks like             701   (of which §5.1 hook ≈ 280)
§6  Write triggers                              142
§7  Your boundaries                             239
§8  Decision-support contract                   394
§9  Proposal-time lint                          326
§10 Contradiction check                         580
```

### 2.2 Word budget per *destination*

Counting only prose that tells the model when/how to choose a destination:

| destination | §1 row | dedicated prose | worked example | in §2 map? |
|---|---|---|---|---|
| `claude-md` | ~60 w | **§2a, 306 w** + the §3 ranking clause (~50 w) | YES — full YAML block, L76-82 | yes, 3 bullets |
| `hook` | ~24 w | **§5.1, ~280 w** | YES — full YAML block w/ replay examples, L198-214 | yes, 1 bullet |
| `skill-md` | ~32 w | none | none | yes, 4 bullets |
| `reference` | ~30 w | §4 bullet, ~40 w | none | yes, 2 bullets |
| `new-skill` | **~20 w** | **§7 clause, ~35 w** — and it is a *warning* | **none** | **NO** |

Backticked mentions across the whole file: `claude-md` 17, `skill-md` 8,
`reference` 5, `hook` 5, `new-skill` **3**.

`new-skill` gets 55 words of guidance in a 3,662-word system prompt — 1.5%
— and two of its three mentions are procedural warnings. It is the only
destination for which the doctrine states no test the model can answer.

### 2.3 §2 is the operative procedure, and `new-skill` is not in it

L27: "Start from the record's `type`, `kind`, and `scope`:" — then five
bullets (L29-39). Those bullets name `hook`, `skill-md`, `claude-md`,
`reference`. **`new-skill` appears in none of them.** A model executing §2
literally cannot arrive at `new-skill`.

And the map is keyed on `scope`, which is frozen at capture time by a
*different* model (`commands/teach.md:40-43`). Once `scope: user` is set:

- `behavior/anti-pattern` → "`hook` candidate or `skill-md` rule" — `skill-md` is refused.
- `behavior/surface-rule` → "`skill-md` rule" — refused.
- `behavior/reasoning-pattern` → "`skill-md` or `claude-md` prose — `claude-md` only when the pattern genuinely applies beyond the skill." At user scope the qualifier is satisfied by definition.
- `knowledge, skill scope` → `reference` or `skill-md` — both refused.
- **L39: `knowledge, project/user scope` → `claude-md` (or project docs).** Deterministic.

`lrn-4ffc006f` is `type: knowledge, scope: user`. §2 line 39 decides it
outright; no judgement is possible or asked for.

### 2.4 The §3/§7 cost inversion — the single most load-bearing defect

§3, L86-88:

> **Prefer the narrowest surface that still fires.** `~/.claude/CLAUDE.md`
> loads in every session of every project — **user scope is the most
> expensive destination in the system.** A lesson that can live with a skill
> or a repo should.

§7, L264-265:

> For both, **always** include a routable alternate (`skill-md` or
> `claude-md`) in `alternates` so the human can choose **the cheaper
> surface**.

These are directly opposed. §3 says user `claude-md` is the most expensive
thing in the system; §7 says `claude-md` is the cheaper surface. The model
resolves the contradiction the same way every time — by treating §3's
*phrase* as the operative rule while dropping its *content*:

- `lrn-4b8c3ec2`: "claude-md (user scope) is the narrowest surface that still fires"
- `lrn-4f89e33a`: "User-scope claude-md is the narrowest surface that still fires for the scope the record itself claims."
- `lrn-4ffc006f`: "user-scope claude-md is the narrowest surface that still fires"
- `lrn-566216a6`: "user-scope claude-md is the narrowest surface that still fires"
- `lrn-9a5d93cb`: "User-scope claude-md is the narrowest surface that still fires"
- `lrn-f2053910`: "claude-md (user scope, loads every session) is the narrowest surface that still fires"
- `lrn-fe16fceb`: "user-scope claude-md is the narrowest surface that still fires"
- `lrn-4323466d`: "claude-md (user scope) stays the narrowest surface that still fires everywhere this recurs"

8 of 10. The anti-`claude-md` rule has become the pro-`claude-md` formula.
The mechanism is a superlative over a set the model cannot enumerate: once
the other candidates are declared "vacuous," the narrowest surface in a
one-member set is trivially `claude-md`. `lrn-f2053910` even quotes the cost
("loads every session") *inside* the sentence that uses it as justification.

### 2.5 `new-skill` reads as unauthorised

Three signals:

1. **§1 L22** — the only positive criterion: "a lesson cluster that wants to
   be its own skill — no existing surface fits." A *cluster*. The unit of
   analysis is one record ("One record, one proposal" — §5, L182), so the
   criterion is stated in a unit the model is forbidden to work in.
2. **§7 L259-261** — "**`new-skill` and `hook` compile at M3, with extra
   human steps.** … A `new-skill` proposal never names the skill — the name
   is the human's call at route time." Framed as ceremony plus a
   permission the model does not hold.
3. **M3 tense.** L22, L23, L191, L259 all read "M3" as a milestone.
   Nothing in the doctrine says M3 has landed. `commands/review.md:176` had
   to say it explicitly: *"(All five destinations compile as of M3 — the old
   exit-2 'compiler lands at M3' no longer exists for verbs…)"*. That
   correction lives in the human-facing command file, **not** in the
   analyst's system prompt. This is not speculative: `lrn-25968266`'s
   proposal (recovered from git, `516d16b^`) declined `hook` for exactly this
   reason — *"The M3 hook compiler doesn't exist yet, so claude-md is the
   routable alternate today."*

### 2.6 Where the doctrine gives a checkable test, the model uses it

This is the evidence that distinguishes conservatism from pattern-matching
(§5 below). §2a L46-47 poses **one binary question**: "does the lesson have a
file-path firing condition?" The model answers it, states the answer, and
acts on it — including answering "no" and declining the more elaborate
option, which is the *opposite* of ambition-seeking:

- `lrn-566216a6`: "No path trigger exists, so this stays plain claude-md rather than a `rules` variant (doctrine §2a)."
- `lrn-fe16fceb`: identical construction.

So the model is not refusing to engage. It engages precisely where the
doctrine hands it a question it can answer, and defaults where it hands it a
comparative.

---

## 3. The prompts, read as prompts

### 3.1 `analyst.py:85-102` — the one-shot template, in full

```
Choose the routing destination for the lesson record below, following the
routing doctrine in your system prompt (narrowest-surface bias).

Reply with ONLY a YAML mapping — no prose, no explanation outside it:

destination: <one of skill-md | claude-md | reference | new-skill | hook>
alternates: [<zero or more others from the same list>]
rationale: <one sentence>
# claude-md only, optional (A2 §3): a rules topic file, or a personal
# per-project file — omit all three for plain claude-md.
variant: <rules | local, omit for plain claude-md>
rules_topic: <kebab-slug topic — required iff variant is rules>
rules_paths: [<glob>, ...]  # optional; omit for an unpathed rule
```

Four defects:

- **`(narrowest-surface bias)` is the only doctrinal content restated in the
  user turn.** Of eleven sections, the one the model is reminded of is the
  one whose phrase it then misapplies (§2.4). This is the highest-salience
  position in the whole prompt and it is spent on the bias.
- **Four of the seven schema lines are `claude-md`-specific.** The template
  has more real estate for `claude-md`'s optional variants than for the
  destination choice itself. Nothing analogous exists for `new-skill`
  (which also takes a name) or `hook`.
- **`rationale: <one sentence>`.** One sentence is enough to *assert* a
  destination and not enough to *rule out* four. It structurally selects for
  the shortest defensible argument, which is the default.
- **"Choose the routing destination"** — singular, framed as a pick, not as
  an elimination. Contrast with what would force enumeration (§7.8).

`record.to_text()` (`records.py:219-222`) renders **frontmatter + body**, so
the model does see `sightings`, `kind`, `scope`, `generality`, `verified`,
`incident_cost`, `supersedes`. It sees no canon, no skills, no host registry.

### 3.2 `worker.py:581-614` — the batch template

Richer, and better in three ways: it carries the doctrine and the card
registry inline, it gives cwd = ledger home, and it supplies a canon
excerpt. But:

- **L603-604: the only feedback channel is negative.**
  ```
  Never re-propose the classes below (recently rejected):
  {digest}
  ```
  `_digest` (`worker.py:483-541`) lists rejected records. There is exactly
  one rejected record in the ledger (`lrn-ac015add`, a claude-in-chrome
  availability fact, rejected as a misunderstanding) and it is unrelated to
  routing. So the digest is inert, and there is **no positive-exemplar
  channel at all** — nothing tells the model that its last eight proposals
  were `claude-md`, or that `new-skill` has never been used.

- **L544-578 `_canon_excerpt` resolves exactly ONE target, keyed on scope.**
  For `scope: user` (L563-565) that is `~/.claude/CLAUDE.md`. The model is
  handed the full text of the claude-md destination and **nothing about any
  other destination**. It is not shown the skills root, the skill list, any
  `SKILL.md`, or any `references/` dir. To argue for `claude-md` it reads the
  prompt; to argue for anything else it must go find evidence unprompted.

- **Latent bug in `_canon_excerpt`, L571-573.** The marker search is
  uppercase:
  ```python
  begin = next((i for i, ln in enumerate(lines) if "SELF-LEARN:BEGIN" in ln), None)
  end = next((i for i, ln in enumerate(lines) if "SELF-LEARN:END" in ln), None)
  ```
  The actual markers are lowercase (`compilers.py:84-85`:
  `"<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->"`).
  The match can never succeed, so for any target ≥ 200 lines the managed-
  section window is dead code and the model gets `lines[:60] + "… (truncated)"`.
  Live today for `~/.config/CLAUDE.md` (703 lines; one routed record in that
  bucket). Not live for `~/.claude/CLAUDE.md` (54 lines → whole file) or
  `hypr-doctor/SKILL.md` (194) or `home-assistant/SKILL.md` (171). Consequence
  when it fires: the model sees an *apparently empty* managed section, which
  makes `already_canon` and `contradicts` structurally blind and makes the
  destination look cheap to add to.

- **The CLI already has the enumeration the prompt withholds.**
  `hosts.py:546-567 skill_dir_for` globs `plugins/*/skills/<name>` under
  `hosts.skills_root`. Changing `<name>` to `*` yields the full inventory in
  one line. It is simply never called from `_compose_prompt`.

---

## 4. Taxonomy of decline-arguments

Coded across the 10 user-scope rationales. A rationale can carry several
moves; counts are records exhibiting the move.

| # | move | count | canonical quote |
|---|---|---|---|
| **B** | **Scope-tautology** — user scope ⇒ user `claude-md` *is* the narrowest surface | **8/10** | "user-scope claude-md is the narrowest surface that still fires" (`lrn-fe16fceb`) |
| **A** | **Vacuous alternate** — "no existing skill owns X as a firing/activation surface" | **6/10** | "No existing skill owns 'measurement hygiene under system load' as an activation surface, so skill-md is a vacuous alternate" (`lrn-566216a6`) |
| **C** | **Deferred escalation** — the better destination is conditional on recurrence or on a skill that doesn't exist yet | **5/10** | "escalate to hook only if this recurs" (`lrn-74b8e65a`); "a second fixture-design lesson would justify pulling both into a dedicated testing-methodology skill" (`lrn-4f89e33a`) |
| **D** | **Hook structurally inapplicable** — the trigger is a mental state, not a `tool_input` shape | **3/10** | "an intent a model must recognize in itself, not a file path or command shape a regex could key on, so hook is inapplicable rather than merely weaker" (`lrn-fe16fceb`) |
| **K** | **Named the ideal, then declined it without naming `new-skill`** | **3/10** | "If a dedicated testing/verification skill existed, this would arguably fit better there (progressive disclosure) than in every-session user canon — but no such skill-md surface exists today to route it to." (`lrn-fe16fceb`, discuss) |
| **E** | **Cost-proportionality** — the incident was too cheap to justify the stronger surface | 2/10 | "incident_cost here is 'none' … versus the sibling's 'one wasted retry'" (`lrn-74b8e65a`) |
| **F** | **Over-block** — a deterministic guard would refuse legitimate work | 2/10 | "a regex hook on `${!` would over-block legitimate occurrences" (`lrn-547d8eb6`) |
| **G** | **Precedent inheritance** — routing follows what a related record or a *prior proposal* already got | 2/10 | "Sibling record lrn-547d8eb6 … already tested the hook bar for this exact record shape and found it unmet" (`lrn-74b8e65a`); "The refinement should land in the same destination as what it supersedes." (`lrn-4323466d`) |
| **J** | **Binary test answered honestly** — declined the `rules` variant on §2a's one question | 2/10 | "No path trigger exists, so this stays plain claude-md rather than a `rules` variant (doctrine §2a)." (`lrn-566216a6`) |
| **H** | **Capture-scope deference** — the human already fixed the scope, so re-scoping would under-fire | 1 explicit + 1 partial | "the human already scoped it at capture time as a cross-project practice … Routing it under the self-learn skill would under-fire" (`lrn-4f89e33a`) |
| **I** | **Existing-section affinity** — an already-present claude-md section is "the natural landing spot" | 1/10 | "the existing 'Communication Style' section is the natural landing spot" (`lrn-9a5d93cb`) |

The two you named map to **A** ("vacuous today") and **C** ("escalate if this
recurs"). The ones you did not name, ranked by how much they matter:

- **B (8/10) is the load-bearing one.** It is not an argument, it is a
  tautology, and it wears §3's language while inverting §3's purpose.
- **K (3/10) is the smoking gun for the `new-skill` zero.** In each case the
  model *articulates the exact §1 criterion for `new-skill`* — "no existing
  surface fits" — and then routes `claude-md` without naming `new-skill` in
  the sentence where it belongs. `lrn-fe16fceb` and `lrn-566216a6` do not
  even list it as an alternate. This is not a model declining `new-skill` on
  the merits; it is a model that does not have `new-skill` in its live option
  set, exactly as §2 (which omits it) would predict.
- **G (2/10) is a self-reinforcing loop and nothing in the design intends
  it.** `lrn-74b8e65a` opens by treating `lrn-547d8eb6`'s *proposal* as
  settled law for "this exact record shape." The model read the sibling
  proposal file off disk under its own initiative — the prompt never supplied
  it. So each `claude-md` proposal becomes precedent for the next, while the
  only prompt-supplied feedback channel (`_digest`) can only ever say "don't
  do that again." Positive feedback with no damping.

### 4.1 The two records that jointly satisfy the `new-skill` criterion

`lrn-4b8c3ec2` (agentic UI-experience walkthrough methodology) and
`lrn-4ffc006f` (Playwright MCP `browser_snapshot` reports invisible elements
as visible) are the same subject. `lrn-4ffc006f`'s own rationale says so:

> "this overlaps with the in-flight 'agentic UI experience' methodology work
> (see the related pending proposal for lrn-4b8c3ec2) — if that becomes a
> dedicated skill, this fact belongs in its reference file instead of here."

That is §1 L22's criterion — "a lesson cluster that wants to be its own
skill — no existing surface fits" — stated by the model, about itself, and
then not acted on. Both list `new-skill` as an *alternate*. Note also that
this is exactly what the doctrine's merge machinery (§5 L182, "merge
proposals are the M2 worker's mechanism") exists for, and the worker *is*
instructed to emit merge proposals (`worker.py:592-601`) — but merges
collapse duplicates into one record, they do not promote a cluster to a new
surface. There is no mechanism, and no instruction, for "these two records
together justify a destination neither justifies alone."

### 4.2 Historical proposals, recovered from git

Proposals are swept at route time, but the deletions are in the ledger's
history. `git show <route-commit>^:<proposal>` recovers 11:

| record | proposed | routed | agreed? |
|---|---|---|---|
| lrn-56e5aa0a | claude-md | claude-md | ✓ |
| lrn-ea833a5b | claude-md (alt hook) | claude-md | ✓ |
| lrn-ca690038 | claude-md (alt hook) | claude-md | ✓ |
| lrn-880ccb70 | claude-md (alt skill-md) | claude-md | ✓ |
| lrn-2fd0cdd7 | claude-md | claude-md | ✓ |
| lrn-5d0c592a | claude-md (alt skill-md) | claude-md | ✓ |
| lrn-b459b8bf | claude-md | claude-md | ✓ |
| lrn-316a5411 | claude-md | claude-md | ✓ |
| **lrn-25968266** | **hook** (alt claude-md) | **claude-md** | ✗ — downgraded |
| lrn-b85a9921 | skill-md | skill-md | ✓ |
| lrn-889241d9 | reference (alt skill-md) | reference | ✓ |

Two findings:

1. **Human agreement is 10/11.** The human is not correcting the bias; the
   adjudication loop the system is built around is not, in practice, applying
   counter-pressure. And because the routed record stores only
   `routing.destination` + `by: human` (e.g.
   `user/resolved/lrn-ea833a5b.md`), agreement is invisible to the next
   analyst even in principle.
2. **The one disagreement went toward `claude-md`, and for a reason the
   analyst supplied itself** — "The M3 hook compiler doesn't exist yet."
   That reason is now false and the doctrine has not been updated (§2.5).

I could **not** recover proposals for the 14 `reference` routes in
`skills/home-assistant` (bulk `source: backlog` import routed 2026-07-14,
before the T13 worker) or for the 3 `hook` routes. So the historical
distribution of 14/10/3/1/0 should **not** be read as 28 independent model
choices; a large plurality of it is one import batch.

---

## 5. Conservative, or pattern-matching? A discriminator

These look identical from the outside. Here is something that separates them,
using only the data on disk.

**The model's behaviour is a function of the *form* of the doctrinal test, not
of the destination's ambition:**

| doctrine gives… | model does… | evidence |
|---|---|---|
| a **binary, checkable question** (§2a L46: "does the lesson have a file-path firing condition?") | answers it, states the answer, acts on it — *including answering no* | 2/10 explicitly decline `variant: rules` with the correct reason (`lrn-566216a6`, `lrn-fe16fceb`) |
| a **comparative/superlative bar** (§1 L23: "advisory text is the weakest enforcement and a deterministic guard is the strongest"; §3 L86: "the narrowest surface that still fires") | constructs an argument that resolves to the residual, every time | 8/10 use the narrowest-surface formula *for* `claude-md`; 2/10 explicitly find the hook bar unmet |
| **no test at all** (`new-skill`) | never selects it, and sometimes omits it from `alternates` even while stating its criterion in prose | 0/13 proposed; 0/28 routed; 3/10 state the criterion and don't name the destination |

That is not risk-aversion; risk-aversion would be uniform. It is
**test-shape sensitivity**, which is a property of the prompt, not of the
model's disposition.

A second, harder discriminator: **the model is capable of research and does
it when the record names a target.** `lrn-4f89e33a` opens:

> "Checked before assuming: the self-learn skill does have a SKILL.md and a
> references/ directory (mining-rubric.md, pane-charter.md,
> pane-surface-model.md, routing-doctrine.md — no LEARNINGS.md yet), so
> skill-md/reference are live surfaces in principle."

Accurate, verified against disk. So the capability is present. But it looked
at exactly the one skill the record's own text mentioned. In the other 6
records that assert "no existing skill owns X," **no enumeration appears
anywhere in the rationale, the card, or the lint block.** And in the one case
where the model names a real skill by name — `lrn-4323466d`'s "skill-md (e.g.
agentic-engineering, which already covers multi-agent design and dispatch)" —
it is the record whose `supersedes:` pointer made the answer trivial.

There are eleven skills on this machine (`/home/komi/.claude/skills/` →
`agentic-engineering, bitwarden-cli, chezmoi, cron-claude, home-assistant,
home-network, hypr-doctor, self-learn, solakaka-sm809pro,
universal-directory-organizer, wow-addon-management`). `agentic-engineering`
is a plausible owner for at least `lrn-4b8c3ec2` (how an agent should drive a
UI), `lrn-566216a6` (a subagent manufacturing load and not cleaning up), and
`lrn-4f89e33a` (fixture design for agent-driven testing). It is named in
exactly one rationale, as an alternate.

**Conclusion: "no existing skill owns this" is a forced conclusion from an
unenumerated set, not a judgement.** The model is being conservative about a
question it was never given the data to answer, and the conservatism is
correct *given the prompt*. That is the definition of a prompt problem.

---

## 6. Is `sightings` visible, and can "escalate if this recurs" be honoured?

**Visible: yes.** `record.to_text()` (`records.py:219-222`) emits full
frontmatter; the worker embeds the whole record file (`worker.py:638`). Every
one of the 10 user pendings shows `sightings: 1`.

**Honourable: no.** Three independent reasons:

1. **`sightings` almost never exceeds 1 at analysis time.** It increments in
   exactly two places: the miner folding a duplicate into a *still-pending*
   record (`miner.py:1161`) and merge-collapse (`verbs.py:2044`). A re-teach
   of a routed lesson creates a **new** record at `sightings: 1`.
2. **Recurrence lives on the routed record, not on the new one.**
   `_recurrence_suspects` (`worker.py:969-1016`) compares pending records
   against *resolved/routed* ones and spools telemetry. `confirm_recurrence`
   (`verbs.py:3148-3192`) refuses unless `record.status == "routed"` and
   appends to that record's `recurrences:` list. Nothing writes back to a
   pending record, and nothing puts recurrence in the analyst's prompt.
3. **The only surface that sees recurrence is human.** `commands/review.md:151-166`
   ("Not holding" cards) reads `self-learn report --json`. The analyst never
   does.

So the next analyst, faced with the recurrence the current one is deferring
to, will see a fresh record at `sightings: 1`, the same prompt, the same
canon excerpt, and the same structural constraint — and will reach the same
conclusion, and defer again. **"Escalate if this recurs" is addressed to a
reader the system never re-invokes with the information required to act on
it.** Five of ten rationales make this promise.

---

## 7. Changes to test, each with a falsifier

Ordered by expected effect size. Each is stated so the empirical agent can
run it and get a discriminating answer.

### 7.1 Inject the scope→eligibility table (highest leverage, cheapest)

Add to both `_PROMPT_TEMPLATE`s a computed line per record:

```
For scope: user, the CLI REFUSES skill-md (verbs.py:836) and reference
(verbs.py:944). Eligible destinations: claude-md, new-skill, hook.
```

**Expect:** the "vacuous alternate" move (A, 6/10) disappears from
rationales, and the reasoning budget shifts to `claude-md` vs `new-skill` vs
`hook`.
**Falsifier / discriminator:** if `claude-md` still wins 9/9 *but rationales
now argue against `new-skill` and `hook` explicitly and on the merits*, the
constraint was not the cause and the bar heights are (→ go to 7.3/7.4). If
the rate moves, it was.

### 7.2 Inject a skills inventory

`_compose_prompt` already has `load_hosts`; add
`hosts.skills_root.glob("plugins/*/skills/*")` plus each `SKILL.md`'s
frontmatter `description`.

**Expect:** "no existing skill owns X" either vanishes or becomes a checked
claim ("checked agentic-engineering, home-network, …; none owns X").
Predicted movers to `skill-md`: `lrn-4b8c3ec2`, `lrn-566216a6`,
`lrn-4f89e33a` → `agentic-engineering`.
**Falsifier:** if the inventory changes nothing, the phrase was never
load-bearing and A is decorative rather than causal.
**Caveat:** at user scope `skill-md` is refused (7.1), so this test should be
run *with* 7.1 or the model will reach for a destination the CLI rejects.
Combined, the honest outcome may be "this record's scope was wrong at capture
time" — which is a `rehome` recommendation (§3 L102-120), and the model has
never once made one.

### 7.3 Give `new-skill` a §2 entry and a checkable test

Mirror §2a's "one question" form:

> **Does this lesson share a subject with one or more other pending or routed
> records that no existing skill owns?** Yes → propose `new-skill`; name the
> candidate skill in `rationale` (never in the enum — §7).

**Expect:** `lrn-4b8c3ec2` + `lrn-4ffc006f` flip to `new-skill`, since the
model already identified them as a cluster in prose (§4.1).
**Falsifier:** if they still don't, the blocker is §7's ceremony framing, not
§2's silence — go to 7.4.

### 7.4 Fix the §3/§7 cost inversion and the M3 tense

- L264-265: replace "so the human can choose the cheaper surface" with "so
  the human can choose the lower-ceremony surface — note that at user scope
  `claude-md` is the *most expensive* standing context (§3)."
- L22, L23, L259: state that M3 has landed and all five destinations compile
  (port `commands/review.md:176` into the doctrine).

**Expect:** the narrowest-surface formula (B, 8/10) stops appearing as a
pro-`claude-md` argument. `hook` proposals become possible again for
anti-pattern records with a real `tool_input` shape.
**Falsifier:** if B persists verbatim, the phrase is being pattern-matched
from §3's heading rather than reasoned from, and the fix is to delete the
superlative from §3 entirely rather than to reword §7.

### 7.5 Require a per-destination verdict instead of a choice

Change `analyst.py:85-102` (and the worker's equivalent) from "Choose the
routing destination" to:

```
For EACH of the five destinations, give one line: eligible | ineligible,
and why. THEN name `destination`. `rationale` must cite the eliminations,
not restate the winner.
```

Also relax `rationale: <one sentence>` — one sentence cannot rule out four
options, and the doctrine (§5 L171-172) already says "one or two tight
sentences."

**Expect:** forces enumeration; converts A's hand-waves into checkable
claims; surfaces the `verbs.py` refusals as a discovery rather than an
inference.
**This is the single strongest test of "does it have the information",**
because a model asked to rule out `skill-md` explicitly will either go look
or admit it cannot.

### 7.6 Add a positive-exemplar / base-rate line

Alongside `_digest`'s rejection list, add:

```
Routed destinations, last 20: claude-md 10, reference 14, hook 3,
skill-md 1, new-skill 0.
```

**Expect:** if the model is calibration-sensitive, the `claude-md` rate
drops.
**Falsifier:** if it doesn't move at all, the model is not reasoning about
base rates and the fix must be structural (7.1/7.3), not informational.
**Secondary benefit:** damps the precedent loop (G) by making the precedent
visible as a *distribution* rather than as a single sibling proposal the
model happened to read off disk.

### 7.7 Carry recurrence into the analyst prompt

Include the record's `sightings` explicitly (it is in the frontmatter but
never called out) plus any `recurrence-suspect` telemetry matching this
record's tokens against routed records.

**Expect:** "escalate if this recurs" (C, 5/10) becomes actionable.
**Falsifier — runnable today, in a sandbox home only:** clone a pending
record into a scratch ledger, forge `sightings: 3` and a matching recurrence
line, and re-run. If the destination does not move, the escalation clause is
rhetorical rather than conditional, and should be deleted from the rationales
rather than made keepable.

### 7.8 Fix `_canon_excerpt`'s marker case (bug, not a bias fix)

`worker.py:571-573` searches `"SELF-LEARN:BEGIN"`/`"SELF-LEARN:END"`;
`compilers.py:84-85` writes `<!-- self-learn:begin … -->`/`<!-- self-learn:end -->`.
The window path is unreachable; targets ≥ 200 lines get `lines[:60]`.
Live for `~/.config/CLAUDE.md` (703 lines). Fix: case-insensitive match, or
import the marker constants.

**Expect:** `already_canon` and `contradicts` start firing on large targets.
Not a routing-bias fix, but it removes a false "the section looks empty"
signal that makes any destination look cheap.

---

## 8. What I could not verify

- **The one-shot analyst's actual behaviour.** All 13 sidecars carry `card:`
  ⇒ all are worker output. Everything said about `analyst.py` above is read
  from code (including the missing `cwd` at `analyst.py:182` and the absent
  canon excerpt), not observed in output.
- **Whether the 14 `reference` routes reflect model judgement.** They are
  `source: backlog`, routed 2026-07-14 in one batch, and their proposals are
  not in the git history I could recover. The historical 14/10/3/1/0 is
  therefore not 28 independent choices.
- **Whether `route --dest new-skill:<name>` succeeds on this machine.** The
  code path exists (`verbs.py:898-940`, `skill_scaffold.py`) and requires
  `<skills_root>/.claude-plugin/marketplace.json`. That file exists at
  `/home/komi/repos/claude-skills/.claude-plugin/` per directory listing, but
  I did not read it or attempt a dry run (mutating verbs are out of scope).
  If it is malformed, `new-skill` would be unroutable in practice as well as
  in effect — worth one read by the empirical agent.
- **Whether the human would accept a `new-skill` proposal.** Zero have ever
  been made, so there is no evidence either way. The 10/11 agreement rate
  (§4.2) is consistent with either "the human agrees with claude-md" or "the
  human has never been offered anything else."
- **`_digest`'s effect.** With one unrelated rejection in the ledger, the
  negative-exemplar channel has never carried a routing signal. Its influence
  is untested rather than absent.

---

## 9. One-paragraph answer

Yes, it is a prompt problem — but the prompt's contribution is to *conceal a
structural one*. At user scope the CLI accepts three of five destinations,
the doctrine's operative decision procedure (§2) reaches four of five and
omits `new-skill` entirely, and the prompt hands the model the full text of
the `claude-md` target while telling it nothing about any other surface. What
is left is `claude-md`, and the model — asked for one sentence, given a
superlative instead of a test, and reminded of exactly one doctrinal
principle in the user turn, the one it then inverts — writes a fluent
justification for the only answer available. The tell is that where the
doctrine hands it a binary question it answers honestly in both directions
(§2a, 2/10 declining the fancier option), and where the doctrine hands it a
comparative it resolves to the residual every time (8/10). The fix is not to
tell the model to be braver; it is to give `new-skill` a test it can answer,
tell it which destinations its scope actually permits, and show it the skills
it is asserting the non-existence of.
