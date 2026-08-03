# The r2 routing campaign — orchestration playbook

*Authored 2026-07-27. This is the campaign plan for building out the r2
routing procedure end to end. It is **practice, not policy**: normative
authority stays with `03-decisions.md` (S-18 model split, S-21, S-22),
`14-forward-work-map.md` (the FW register and the open decision queue),
and `15-orchestration-runbook.md` (the generic round mechanics).*

*This file exists because a `/goal` loop needs three things the runbook
does not carry: a **completion criterion** for a body of work whose own
author declared parts of it unimplementable, a **wave plan** derived from
which files each unit touches, and a **purpose-conformance check** that
asks whether shipped code actually solved the problem we set out to
solve. Everything else — lifecycle, blindness rules, worktree
discipline, sandbox invariants, the gotcha bank — is `15`, and is not
repeated here.*

**Design sources.** `misc/routing-procedure-r2.md` is the implementation
reference (exact field names, line numbers, sizes).
`misc/routing-procedure-plain.md` is the same design in prose, and is the
better handout for a Fable agent because it states the *problem*.
`research/2026-07-27-routing-monoculture-and-pin-audit.md` is the
evidence base. **Both `misc/` files are git-ignored and local-only** —
agents can read them at absolute paths on this host, but they are not on
the remote and would not survive a fresh clone. Promoting them into the
corpus requires scrubbing `/home/komi` literals first (this is a PUBLIC
repo); until then, treat their absence from git as a known fragility and
keep the backup current.

---

## 1. What "complete" means

The instruction that starts this campaign is: finish r2 *including* its
"still not implementable" list. Taken literally that is not achievable,
and pretending otherwise would produce a loop that never terminates or
one that lies. Four of those nine items are not agent-closable at all:
one needs a manual session test on this host, one needs a fix to the
miner that r2 puts outside its own scope, and two are policy calls that
belong to the human.

So completion is defined as **disposition, not construction**:

> Every r2 build item is either merged behind a CLEAN code gate, or
> carries a recorded disposition. Every "still not implementable" item
> carries a recorded disposition. A disposition is one of four, and each
> names its evidence:
>
> - **BUILT** — shipped, gated CLEAN, tests include the mutation list.
> - **MEASURED** — not eliminable, but instrumented, with the measurement
>   run and its result recorded (this is how the judgment residue closes).
> - **ROUTED** — belongs to the human; the question is asked, in one
>   batch, with options and a recommendation, and is sitting in the
>   decision queue of `14 §4`.
> - **ACCEPTED** — formally accepted as residual, written into
>   `03-decisions.md` with its reasoning, so a later agent cannot
>   re-litigate it as an open bug.
>
> The loop ends when no item lacks a disposition, the suite is green, and
> the final Fable purpose-check returns PASS.

An item that is ROUTED does not block the loop. It blocks *its own*
downstream units, and the loop continues on everything else. **Never
guess a ROUTED answer to keep moving** — that is how the fabricated pin
that started this whole audit came to exist.

---

## 2. The units, and what each one touches

The file column is the scheduling constraint. Two builders may run
concurrently **only if their file sets are disjoint** — worktree
isolation prevents corruption, but it does not prevent two units
diverging on the same function and forcing a hand-merge of semantic
intent. See `15 §5`.

Crosswalk to the existing register is given so nothing gets built twice
under two names.

| Unit | What it is | Primary files | FW row | Depends on |
|---|---|---|---|---|
| **U-marker** | Excerpt marker case fix — search the lowercase marker the compiler actually writes | `worker.py` | FW-44 | — |
| **U-marker-ui** | **Added 2026-08-02** — the SAME defect, cloned. `ui/pane.py` re-declares the wrong marker in a hand-copied `_canon_excerpt`, and `ui/tests/test_pane.py` hand-writes that wrong marker into its fixture and passes: **a green test asserting the defect as the contract.** This is the excerpt the HUMAN sees in the review pane, so fixing `worker.py` alone leaves the reviewer reading a head-of-file truncation. Split from `U-marker` per §9 rather than absorbed: different suite, different builder, and the UI is contended | `ui/pane.py`, `ui/tests/test_pane.py` | new | sequence after `U-grad-ui`'s file set is known |
| **U-analyst** | Stop rebuilding proposals from a fixed key set; pin `cwd=home` | `analyst.py` | FW-41 | — |
| **U-schema** | The decision-trace schema, its validator, quote containment, the closed flag set | `ledger_ops.py` | new | — |
| **U-table** | The decision table as a pure module; wire the recompute-and-refuse check | new `gates.py`, `ledger_ops.py` | new | U-schema |
| **U-demand-user** | ~~Open the on-demand shelf at user scope~~ **RE-SCOPED 2026-08-02 by S-23:** give user scope a cheap surface, and it is **PATHED**, not DEMAND. Still in scope: delete the dead chezmoi refusal; widen the UI destination menu. Its spec must settle the boundary with `U-pathed` — `U-pathed` builds the emission machinery (`paths:` frontmatter, union semantics, drift-check), this unit opens the *scope* and the *menu* | `verbs.py`, `ui/models.py` | FW-40, FW-42 | ~~ROUTED decision~~ **unblocked**; sequence after `U-pathed` |
| **U-composer** | Shared prompt composer (skill roster, cluster candidates, path roster) + the doctrine rewrite | `worker.py`, `analyst.py`, `routing-doctrine.md` | FW-43 | U-marker, U-analyst, U-schema, U-table |
| **U-pointer** | Pointer emission, cap-exempt; reference-route triggers an ALWAYS recompile | `compilers.py`, `verbs.py` | FW-40 | U-demand-user |
| **U-reach** | Reachability selftest + the `route` telemetry kind + fix `routing.by` | `selfcheck.py`, `telemetry.py`, `verbs.py` | FW-40, FW-45 | ships **before or with** U-pointer |
| **U-pathed** | `paths:` frontmatter emission, union semantics, drift-check awareness | `compilers.py`, `verbs.py` | new | **manual host test** |
| **U-pairs** | Discriminant-pair harness: a yes-shaped and no-shaped record per judgment gate, run against both execution paths | probe tooling | new | U-composer |
| **U-refresh** | `proposal refresh` verb so stale siblings get re-analyzed | `verbs.py`, `cli.py` | new | U-composer |
| **U-name** | S-21: the analyst names the skill; the review surface lets the human keep/change it | `verbs.py`, UI | FW-46 | 2 ROUTED decisions |
| **U-modelb** | The CLAUDE.md-to-owned-rules-file cutover | `verbs.py` | new | ROUTED (unratified) |
| **U-recur** | A `violated` fire on a routed record raises a recurrence suspect (see §7) | `miner.py` | new | — |
| **U-capture** | Teach-time prompt asks whether the failure announced itself | `teach.py` | new | — (optional) |

### Wave plan

**Wave 1 — five concurrent, fully disjoint.** `U-marker` (worker.py),
`U-analyst` (analyst.py), `U-schema` (ledger_ops.py), `U-reach`
(selfcheck/telemetry), `U-recur` (miner.py). No two share a file. This is
the wave that most rewards parallelism and the one most likely to be run
serially by mistake. It should not be.

**Wave 2.** `U-table` (needs U-schema). `U-demand-user` (needs its
decision answered; touches verbs.py, so it must not overlap `U-pointer`).

**Wave 3.** `U-composer` — the big one; it re-touches worker.py and
analyst.py, so Waves 1's units must be merged first. `U-pointer` (needs
U-demand-user merged, shares verbs.py).

**Wave 4.** `U-pairs`, `U-refresh`.

**Gated queue.** `U-pathed` (after the manual test), `U-name` (after two
decisions), `U-modelb` (after ratification), `U-capture` (anytime, low
value alone).

The minimum for the procedure to run at all is
`U-marker → U-analyst → U-schema → U-table → U-composer`. Everything
before that milestone is scaffolding; nothing routes differently until
`U-composer` lands.

---

## 3. The per-unit loop

Lifecycle is `15 §1`, unchanged: spec → blind spec gate → build → blind
code gate with mutation verification → merge → record. Model split is
`15 §2` / S-18: **Sonnet builds, Opus specs and gates, Fable never gets
inherited — pass `model:` explicitly on every single spawn.**

Four things this campaign adds or changes:

**Push is autonomous now.** `15 §1.7` says "push stays manual (D3)".
That is superseded by `CLAUDE.local.md`: a closed loop pushes without
asking. A loop is closed when the tree is clean, the suite is green, and
the gate returned CLEAN. Report the ref range afterwards.

**Review as soon as a unit is done, not at wave end.** A finished build
goes straight to its code gate while its wave-siblings are still
building. Barriers belong at wave boundaries, not between build and
review. The wall-clock cost of holding a finished unit for its siblings
is pure waste, and a stale build is harder to gate than a fresh one.

**Verdict repricing applies** (S-18 addendum, ratified 2026-07-26): a
gate finding expressible as a bounded text substitution is folded and
verified at the *code* gate — it does not buy a fresh spec round. Only a
contradiction that would force the builder to *choose* triggers one. Do
not run a spec to six rounds over wording again.

**Delta re-checks go back to the same reviewer, by agent id.** A
`SendMessage` to a completed agent re-enters it with its finding context
intact. A fresh reviewer re-litigates instead of verifying folds, and
costs a full re-read.

**Which code-gate folds need a delta, and which merge — added 2026-08-02
after this question came up on all seven units in one wave.** The
verdict-repricing rule above governs the SPEC gate. The code gate needs
its own, because "fold the findings" covers two very different things:

> **A fold that closes a COVERAGE gap merges after re-verification.** The
> shipped code was already correct; only the tests could not see it. The
> orchestrator confirms the new test goes red against the surviving
> mutation, and the unit lands.
>
> **A fold that changes PRODUCTION CODE goes back to the same reviewer.**
> The gate never reviewed that code, so merging on the builder's own
> verification means the changed lines shipped ungated — which is exactly
> the hole the code gate exists to close.

Worked examples from this wave. Merged after coverage folds: a marker
fix whose docstring re-spelled a forbidden literal; an analyst fixture
whose file-mode let a weakened guard pass; a miner whose two *wrong*
implementations passed all 77 tests; a selftest whose derived collector
was vacuously green. In every case the production code was already
right. Sent back: a hand-written glob sanitiser (into a function that
had already had three wrong corners found across three rounds), a new
error path on the resolved-record surface, and four fixes to frontmatter
round-tripping. **The asymmetry is not bureaucracy** — a builder
verifying its own production fix is the same agent that wrote the defect,
and this project's failure mode is a check that passes for the wrong
reason. Note also that a builder's fold can introduce NEW defects a
gate would catch: one fold here fixed a walk and silently added two type
errors, caught only because the orchestrator re-ran the type checker
rather than trusting the suite.

### The builder prompt

Every Sonnet builder prompt carries all of this. A prompt missing any
line has produced a failure in this project before.

```
ROLE + SCOPE
  You are implementing <unit>. Build exactly this and nothing adjacent.
  If you find a defect outside your file set, WRITE IT DOWN in your final
  report — do not fix it. Scope creep is how a 20-line fix became a
  six-round spec here once.

FILES YOU MAY TOUCH
  <explicit list>. Anything else is out of scope and must be reported,
  not edited.

THE GATED SPEC
  <full acceptance criteria, verbatim — not a pointer>
  Where prose and acceptance criteria conflict, the criteria win.

TESTS — THE BAR
  Test-first. For each behaviour the spec pins, write the test that fails
  without your change. Then include this mutation list in your report:
  for each load-bearing test, the one-line edit to production code that
  makes exactly that test fail. The code gate WILL run them.
  A test that passes when the feature is broken is the failure mode this
  project has shipped most often. Ask of every assertion: what does this
  print when the thing it checks is absent? If that equals "pass", the
  assertion is worthless — narrow it.

ENVIRONMENT
  Dev/test ALWAYS redirects SELF_LEARN_HOME, XDG_CACHE_HOME,
  XDG_RUNTIME_DIR, SELF_LEARN_CLAUDE_DIR, SELF_LEARN_TRANSCRIPTS_DIR
  (and HOME where the code reads it) to a scratch tree.
  ~/.self-learn is READ-ONLY to you. Never run a mutating self-learn verb
  against it. Never run `self-learn host add` at all.
  Never sudo — there is no tty and it locks the account for 10 minutes.
  Put .venv/bin first on PATH when running suites in a worktree, or you
  will silently test master's CLI.

DELIVERABLE
  Leave the tree UNCOMMITTED. The code gate reviews working-tree state.
  Report: what you changed, the mutation list, suite + pyright results
  you ran yourself, and anything you touched or noticed outside scope.
```

### The code-gate prompt

Beyond `15 §4`: the reviewer is blind to `reviews/`, runs the suite and
pyright itself rather than trusting the builder's numbers, and performs
**mutation verification** — break each guarded behaviour, confirm exactly
the claimed test fails, then **revert by inverse Edit, never
`git checkout`**. The tree under review is uncommitted and is the only
copy of the work; a checkout destroys it.

Reviewers are explicitly invited to invent mutations the builder did not
suggest. The most valuable finding of the last cycle came from an
unsuggested one — a guard that used a string-prefix check where a path
containment check was needed, which passed for a sibling directory.

---

## 4. The Fable purpose-check

This is the part that does not exist anywhere else in the corpus, and it
is the reason this campaign needs a playbook at all.

The code gate answers *"does this code do what the spec said?"* Nobody
currently answers *"was that the right spec?"* Every finding in the audit
that started this work was of the second kind: features that passed their
tests, shipped, and delivered nothing — a rules variant that validated
globs it never wrote, a destination that routed lessons into a file with
no path to it. A green suite could not see any of them.

**Role.** A Fable agent, spawned only at the checkpoints below, on the
user's standing instruction that Fable is for deep reasoning and
bird's-eye synthesis. Fable is expensive; three or four runs across the
whole campaign, not one per unit.

**The briefing rule, which is the whole trick:** give Fable the
**problem**, not the spec. Hand it `misc/routing-procedure-plain.md`
§"What we're actually trying to fix", the audit findings, and the
*measured* current state. Do **not** hand it the unit specs as the
primary frame. A Fable agent given a spec will check conformance to the
spec, which is the code gate's job and a waste of the model.

**The question it answers**, in the user's own framing: *X was
successfully implemented — but we set out to solve Y. Did X actually
solve Y?*

**It must return a verdict, not an essay:** `PASS`, `PASS WITH DRIFT`
(names what drifted and what would close it), or `REDIRECT` (the built
thing does not serve the goal; names what to do instead). A REDIRECT
stops the wave and comes to the human with Fable's reasoning attached.
A checkpoint that can only produce commentary is decoration — if it
cannot stop the campaign, it is not a gate.

### Checkpoint A — after the minimal core lands

*Claim under test: the procedure runs, and the analyst is now choosing
rather than reciting.*

Measurement to run first, and hand over as evidence: re-analyze the 12
pending records under the new doctrine and diff the results against their
current proposals — destinations, and the reasoning behind them.

Ask Fable: did the *reasoning* change or only the labels? Is the analyst
now weighing real alternatives, or has the forced choice simply moved?
Do the quote requirements bite, or is every gate coming back with the
same boilerplate quote?

### Checkpoint B — after the on-demand shelf is real

*Claim under test: the cheap shelf exists and lessons on it are
reachable.*

Measurement: the reachability selftest, which must go from 14 failures to
0 — and the 14-failure run must be captured **before** the fix as the
positive control. A check that has never failed has not been shown to
work.

Ask Fable: the pointer now exists — but does a session actually open that
file at the right moment? What would count as evidence that it does?
r2 admits this is unmeasured and calls it the design's soft spot; this
checkpoint is where we decide whether to instrument it or formally
ACCEPT it.

### Checkpoint C — final

*Claim under test: the problem the audit found is fixed.*

Measurement: destination distribution across a full re-analysis, against
the baseline measured 2026-07-27 — user scope 7 CLAUDE.md + 1 hook,
project scope 5 + 1, and 14 unreachable on-demand records.

Ask Fable two things. First: is the monoculture actually broken, in
measured routings and not in available options? Second, and this is the
one to press hardest — **did we build a new monoculture at the other
end?** r2's own honest failure mode is that everything lands on the cheap
shelf with an evidence-gap flag, which would be just as uniform as what
we started with and much easier to mistake for success. If the
distribution has simply moved from one column to another, that is a
REDIRECT, not a PASS.

---

## 4a. Two staging facts every agent prompt must carry

**The documented suite command fails from the repo root.**
`CLAUDE.local.md` gives `uv run --project plugins/self-learn/ui pytest`.
Run from the repo root that collects **both** the CLI and UI suites,
which share basenames (`test_commit_drift.py`, `support.py`) with no
`__init__.py` between them — so `support` resolves to the CLI's copy and
16 UI modules fail to import. The failure looks like broken tests and is
not. Scope it:

```sh
uv run --project plugins/self-learn/ui pytest plugins/self-learn/ui/tests
# or: cd plugins/self-learn/ui && uv run pytest
```

**AMENDED 2026-08-02 — the two suites have DIFFERENT baselines, and the
original text gave only one without saying which.** Every CLI-unit agent
read the UI's numbers as its own, including the tolerated failure. There
is no tolerated failure in the CLI suite.

| Suite | Command | Baseline | Tolerated failure |
|---|---|---|---|
| **UI** | `cd plugins/self-learn/ui && uv run pytest -q` | 1010 passed, 77 skipped, **1 failed** (2026-07-28) | `test_service_unit.py::test_both_units_document_manual_registration_via_symlink` — does not block |
| **CLI** | `cd plugins/self-learn/cli && ./.venv/bin/python -m pytest -q` | **1133 passed, 5 skipped, 0 failed** (2026-08-02, rc captured unpiped) | **none — any red is new** |

Any failure beyond the one UI row above blocks. Always export
`XDG_CACHE_HOME` to a scratch dir first; the UI's 77 skips are an artifact
of that redirect moving Playwright's browser path, not a missing Chromium.

**`ledger_ops.py` is Wave 1's shared dependency.** The files are
disjoint, but `worker.py`, `analyst.py`, `selfcheck.py` and `miner.py`
all *import* `ledger_ops`, which is `U-schema`'s file. `U-schema` only
adds a validator under an absent-is-valid posture, so it should not
disturb them — but merge it and re-run the combined suite before treating
the other four as landed. This is the semantic-join case `15 §5` warns
about; name it in the prompts so both sides build toward the same seam.

## 5. Test obligations specific to this campaign

Beyond the general bar in the builder prompt:

**Every gate-shaped check ships with a positive control.** The
reachability selftest must be demonstrated failing 14 times before the
pointer lands. The quote-containment validator must be tested with a
deliberately fabricated quote. The glob matcher must be tested with a
glob that matches nothing. This project's signature bug is a check that
reports success when it cannot see its target at all.

**Never read an exit code downstream of a pipe.** `cmd | tail` reports
tail's status. Capture rc unpiped, use `PIPESTATUS`, or read the tool's
own pass/fail line.

**A spec that pins an ALGORITHM in prose has pinned an untested claim —
added 2026-08-02, learned the expensive way.** One unit's spec resolved
its blocker by pinning a hand-rolled string matcher, described step by
step and labelled *"pinned so the builder does not re-derive it."* Three
of the four findings in its delta round were defects in that recipe, and
its own author named the cause afterwards: *"I measured to convict the
blocker, then wrote a fix in prose and shipped the prose untested."* The
literal reading of the pinned steps produced a matcher that failed the
spec's own acceptance case — reproducing the exact symptom the blocker
was about — and two more corners were wrong besides. Worse, the
orchestrator's ruling on that blocker was **also** insufficient in the
same way: it said "only `!` negates a character class", which is correct
about the stdlib and still wrong as an instruction, because Python's
`re` negates on `^` unaided, so a literal `^` must be actively escaped.
Nobody catches that by reasoning; you catch it by running it.

So: **if a spec pins an algorithm precisely enough that a builder is
meant to transcribe it, the author must have EXECUTED it, and the spec
must say what was executed and against what oracle.** State the oracle's
own configuration too — the same unit's "0 mismatches over 13 patterns"
turned out to hold only under two unstated preconditions, and 7 of the
13 mismatched under the oracle's defaults. An equivalence claim without
its preconditions is not a measurement, it is a coincidence someone
wrote down.

**The 51 resolved records are the table's regression fixtures.** The
decision table, run over records whose routing a human already accepted,
should mostly agree with them — and every disagreement is either a table
bug or a routing worth revisiting. Both are findings; neither is noise.

**The pair harness is the campaign's falsifier.** Until it runs, "the
procedure works" is a claim. It must run against both execution paths,
because the audit's open question — whether the nightly worker and the
one-shot analyst behave the same — has never been answered.

---

## 6. The human-blocked queue

Ask these in **one batch**, early, with a recommendation each. Do not
trickle them out one per wave; do not guess an answer to keep a wave
moving.

Already open in `14 §4`, and blocking:

> **AMENDMENT 2026-08-02 — questions 1–4 were put to the user as one
> batch, per this section's own rule, and all four are ANSWERED.** The
> rulings are recorded normatively as **S-23** (questions 1+2, one tier
> model) and as an amendment to **S-21** (questions 3+4) in
> `03-decisions.md` — that register, not this playbook, is where they
> bind. Summarised below in place so this section is not read as still
> open. `U-pointer`, `U-demand-user` and `U-name` all unblock.

1. ~~**What should the on-demand shelf do?**~~ **ANSWERED — pointer, and
   demote DEMAND (S-23 half 1).** `reference` survives and gets its
   pointer, so the 14 already-routed records become reachable; but
   `paths:`-scoped rules become the **primary** cheap tier and DEMAND
   shrinks to lessons that are genuinely not file-scoped. Retiring
   `reference` was rejected (it orphans 14 records); keeping DEMAND as
   the general cheap tier was rejected because its core assumption — a
   session opens the file at the right moment — is unmeasured and r2 §8
   calls it the design's soft spot, whereas pathed injection is automatic
   and was verified working on this host 2026-07-28.
2. ~~**Should user scope get a cheap surface at all?**~~ **ANSWERED —
   yes, pathed rules only (S-23 half 2).** Explicitly NOT a user-level
   reference file, which would inherit the unreachability problem with no
   `SKILL.md` to hang a pointer off. **This re-scopes `U-demand-user`:**
   §2's description of it as "open the on-demand shelf at user scope" is
   superseded — the user-scope cheap surface is PATHED. User-level globs
   resolve relative to the session's working directory and absolute globs
   never match, so user-scope pathed rules serve **cross-project
   file-type conventions**, never project-specific guidance (which
   belongs at project scope anyway).
3. ~~**Is the analyst's proposed skill name trusted, or
   CLI-regenerated?**~~ **ANSWERED — neither: the analyst proposes, the
   CLI validates, the human confirms** (S-21 amendment). Never silently
   rewritten; a rejected name returns with its reason.
4. ~~**Does "change the name" get a text field in the review surface?**~~
   **ANSWERED — yes** (S-21 amendment), costed at ruling time as genuine
   UI work, not a one-liner.

Added by this campaign:

5. ~~The manual path-scoping test.~~ **ANSWERED 2026-07-28** — it works;
   see §7. Two findings ride out of it and change the design rather than
   merely unblocking it:

   **Pathed rules fire on Read, which sharpens what belongs there.** A
   lesson stating a *file-local convention* ("when editing the compiler,
   use this pattern") is served perfectly — the rule arrives exactly when
   the file is opened. A lesson whose trigger fires *before* the work
   ("before choosing a fixture strategy, remember X") is served badly,
   because by the time a matching file is read the decision may already
   be made. r2's T2 gate currently asks only "does it only matter for
   certain files?" It should also ask **whether the lesson's trigger
   fires at or after first contact with those files.** Fold this into the
   `U-composer` doctrine rewrite.

   **This reopens question 2 in a good way.** A pathed rule dodges the
   single biggest unmeasured assumption in the whole design — r2 §8 item
   6, "does a session actually open the on-demand file at the right
   moment?" — because injection is automatic rather than depending on a
   pointer being noticed and followed. For the subset of lessons that are
   genuinely file-scoped, PATHED is strictly better than DEMAND, and the
   cheap-shelf question narrows to: what do we do with lessons that are
   *not* file-scoped?

6. ~~Do `paths:` globs work in USER-level rules?~~ **ANSWERED 2026-07-28.**
   Tested with four canaries in `~/.claude/rules/` observed through two
   fresh headless sessions at different working directories, then removed
   (the host is back to having no `~/.claude/rules/` at all). Results:

   - The unpathed control loaded at session start — **positive control
     passes**, user-level rules are live.
   - `**/*.usercanary` fired from both working directories.
   - `probe/**/*.usercanary` fired when cwd made that the relative path,
     and **did not** fire from a parent directory where the same file was
     `uc-probe/probe/x.usercanary`.
   - An **absolute** glob never fired from either directory.

   So user-level `paths:` globs are **relative to the session's working
   directory**, and absolute patterns silently match nothing. The design
   consequence: a user-scope pathed rule cannot be aimed at one repo — it
   fires wherever a matching *relative* path exists, in any project. That
   is coherent for user scope (which means "everywhere") but it means
   user-level pathed rules suit **cross-project file-type conventions**,
   never project-specific guidance, which belongs at project scope anyway.

   **A doctrine sharpening for `U-composer`, from the recurrence
   diagnosis in §7.** `lrn-ea833a5b` is routed to user CLAUDE.md — the
   most expensive tier there is — and was still violated twice. So the top
   rung of the escalation ladder cannot be "promote it to always-loaded":
   it is already there. When a lesson at the ALWAYS tier keeps recurring,
   the escalation is **a guard, not more prose.** Text that has failed at
   maximum prominence is not fixed by more prominence.
7. **The CLAUDE.md-to-rules-file restructure** — still unratified. The
   campaign is built to be indifferent to it, so it is not urgent, but it
   should not stay open forever.
8. **When do the new trace fields become mandatory?** They start
   optional so nothing in the current queue breaks. Flipping them to
   required is one flag; when to flip is policy.

---

## 7. Disposition ledger for "what this doesn't fix"

Every item from r2 §8 with its target disposition. This table *is* the
completion checklist for the second half of the goal.

| Item | Target | How it closes |
|---|---|---|
| Judgment residue is irreducible | MEASURED | The pair harness quantifies it. Then ACCEPTED in `03` with the measured numbers, so it stops reading as an open bug |
| "Trigger names a literal command" is not machine-checkable | MEASURED → BUILT *or* ACCEPTED | Pair-test whether the hook attempt actually gets skipped. If it does, build the CLI-side lexer; if not, ACCEPT with the measurement |
| The exactly-one-owner rule rests on description quality | MEASURED → ACCEPTED | Softest gate in the design, and known to be. Pairs bound it; the re-home flag bounds the damage |
| Path-scoping unverified on this host | **CLOSED 2026-07-28 — verified working** | Canary test on CC 2.1.220, project scope. Control rule (no `paths`) loaded at startup; pathed rule stayed out of context; reading a non-matching file injected nothing; reading a matching file injected it. So the glob discriminates and injection is **lazy on file access**, not at launch. `U-pathed` is unblocked and the tier stays. **Two limits found:** (a) only `Read` was exercised — `Edit` is covered in practice because Claude Code requires a Read first, but a Grep/Glob-only workflow never triggers injection; (b) once injected the rule persists for the session, so any re-test needs a fresh one |
| The promotion rule has nothing under it | MEASURED → then decide | **r2 overstates this and so did the first draft of this plan.** The write path is not missing: the miner spools a `recurrence-suspect` event (`miner.py:1174-1185`) and a human confirms it with `confirm-recurrence`, the sole caller of `append_recurrence` (`verbs.py:3147`). The miner was never meant to write `recurrences[]`. What is unexplained is one step earlier — **zero `recurrence-suspect` events have ever been emitted** (ledger telemetry: 30 capture, 26 surface-budget, 8 fire, 1 offer-declined). **DIAGNOSED 2026-07-28 — `U-recur`, and it is small.** r2's two stated reasons are both wrong (the miner was never the writer; "no DEMAND routes exist" is false — there are 14, all `status: routed`). The real cause is a **channel split**. The miner prompt offers two ways to report the same phenomenon: a candidate carrying `match: {record, status: "routed"}`, which produces a `recurrence-suspect`; and the separate `fires[]` array with `outcome: complied\|violated`, which produces a `fire` telemetry event. The model uses `fires` — that channel is purpose-built for routed rules ("ROUTED RULES (observe fires against these)"), whereas the match route requires emitting a candidate it knows is a duplicate, which the rubric's "when in doubt, do not emit" actively discourages. **Two `violated` fires exist on `lrn-ea833a5b`** (2026-07-26, 2026-07-27). Those *are* recurrences. The fire handler already confirms `status == "routed"`, already has the origin, already dedupes on `("fire", rid, origin)` — it simply never crosses over. Fix: on `outcome == "violated"`, also raise the suspect. **The safety net was never missing; it was wired to the wrong terminal.** |
| On-demand lookup behaviour is unmeasured | MEASURED *or* ACCEPTED | Checkpoint B decides. Instrumenting it means defining what counts as a "fire" for an index, which is genuinely open |
| Quote containment can be gamed by a true-but-irrelevant quote | ACCEPTED | The validator checks reality, not relevance. Relevance is the human's glance at the card — so the card must surface the quote verbatim, which is a small UI obligation to confirm |
| When to require the trace fields | ROUTED | Question 7 above |
| `misc/` git-ignore status | ROUTED | Local-only exclude today. Durable across clones is the user's call, and promotion needs a home-path scrub first |

---

## 8. State that survives compaction

This campaign will outlive several context windows. Two files carry the
state, and the orchestrator re-reads both after every compaction before
doing anything else:

- **This playbook** — the plan. Amend it in place when the plan changes;
  date the amendment.
- **`misc/r2-progress.md`** — the register. One row per unit: status
  (`not-started` / `spec` / `spec-gated` / `building` / `code-gate` /
  `CLEAN` / `merged`), the agent ids involved, gate verdicts, and the
  commit sha. Plus a dispositions section mirroring §7, and a log of
  Fable verdicts. **Update it at every state transition, not at wave
  end** — a register written only at milestones is exactly the register
  that is stale when the context window ends.

Agent ids matter: a resumable agent is far cheaper than a respawned one,
and both delta re-checks and recovering an agent that died mid-writeup
depend on having the id written down.

---

## 9. How this loop fails, so it can be caught

- **Serial execution of independent units.** The most expensive
  orchestration error made on this project, twice. Wave 1 is four
  concurrent units; if they are running one at a time, something is
  wrong.
- **A unit absorbing an adjacent feature.** If blockers cluster in one
  subsystem, that subsystem is a separate unit — split it rather than
  growing the spec.
- **Guessing a ROUTED answer.** Every fabricated pin in this corpus
  started as a reasonable-sounding assumption that no one marked as one.
- **Fable used as a reviewer.** If a Fable checkpoint returns
  spec-conformance findings, it was briefed wrong — it got the spec
  instead of the problem.
- **Declaring completion on a green suite.** The suite was green
  throughout the period in which half the corpus was unreachable. Green
  is necessary and nowhere near sufficient; the measurements in §4 are
  what completion rests on.
