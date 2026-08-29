# U-land — a sanctioned landing runner, the twin of `scripts/suite`

Status: **SOUND — blind spec gate r6, `esWzdtAxVLzi9OvN1mjsH`
(0 Blockers / 0 Majors / 3 Nits; all three folded, no re-gate).** Spec r8.
**Build pending.** The Major count converged 11 → 5 → 3 → 3 → 1 → **0**
across six blind rounds. Unit `U-land` (**T2, full two-gate** — §7.3 says
why, with the measurement).

*(r8 folds gate r6's three nits — §3.10. r7 folded gate r5 — 0 B / 1 M /
2 N, §3.9. r6 folded gate r4 — 0 B / 3 M / 3 N, §3.8. r5 folded gate r3 —
0 B / 3 M / 5 N, §3.7. r4 folded gate r2 — 1 B / 5 M / 6 N, §3.6, and carries the lane's
KEEP adjudication, §3.6a. r3 folded gate r1 — 1 B / 11 M / 8 N, §3.5. r2
folded the six open questions — §3.4.)* Written in the throwaway worktree
`.claude/worktrees/u-land-spec` (branch `u-land-spec`, base
`6038eee`), landed on `master` with this commit.

**Anchor `6038eee`; every measurement re-run at live master `9c7ebdd`.**
*(Master advanced again during r6 — `U-verbs` Phase 1 landed as `9c7ebdd`.
Re-measured there and **unchanged**: `scripts/suite` **55**, `_ARMOR_SHAS`
**7** pins, `test_armor.py` **absent**, home-path files **14** tree-wide /
**0** under `plugins/`, ceilings **S-55 / FW-141**, `S-56`/`FW-142`/`FW-143`
still **0 rows**. Denominators moved only: CLI test files **88 → 89**, UI
**51 → 52**, so §4.6a's walk reads **144** modules / naive **43** /
docstring-inclusive **39** — and its three load-bearing conclusions are
**identical**: strict `src` **0**, strict tests **8**, lane-set union **8**.
None of U-verbs' new modules reads a corpus doc.)*

*(The worktree itself sits at `99d310e`
(since removed — `git worktree list` back to its prior count, production
tree clean, `HEAD` unmoved).** Master advanced by four commits while this was being written:
the **`U-armor` spec** (`7367fbc` + merge `9b9b1a1`; r7, SOUND at spec gate
r5 — its **build has not landed**, so the pre-`U-armor` world is still the
live one), and **`U-scrub`** (`32299bd` + merge `99d310e`; the §9
personal-literals gate becomes a real test). Re-measured at `99d310e` and
**unchanged**: `scripts/suite` **55** lines, the ad-hoc scripts **268**,
`_ARMOR_SHAS` **7** pins, `test_armor.py` **absent**, home-path files **14**
tree-wide / **0** under `plugins/`, UI test files **51**. Three things
*did* change and each is folded where it belongs: the S/FW ceilings (§2.0),
CLI test files **87 → 88** (`U-scrub`'s new module), and **`CHK5` no longer
reimplements the personal-literals grep — it calls `U-scrub`'s shipped
test** (§2.5).

Reserved numbering: **S-56**; **FW-142**, **FW-143**.
*(Measured at live master `9b9b1a1`: `03-decisions.md`'s highest row is
**`S-55`** and `14-forward-work-map.md`'s highest is **`FW-141`** — both
now LIVE rows, landed with the `U-armor` spec at `9b9b1a1`. At the anchor
`6038eee` they were `S-54`/`FW-138` with `S-55` and `FW-140`/`FW-141`
merely reserved; the ceilings moved, this unit's numbers did not. `FW-139`
remains a withdrawn number with no row — see §2.0's control.)*

**Deliverable.** `plugins/self-learn/cli/scripts/land` — one fail-closed,
testable runner that replaces the orchestrator's ad-hoc per-landing shell
chains, plus a resolver package with unit tests and a fixture-repo test
suite covering every refusal path.

---

## 0. Reading order and precedence

**THE CODE BASE FOR EVERY NUMBER IN THIS SPEC IS `6038eee`** — live
`master`, which at the time of writing is byte-identical to
`origin/master`:

```sh
$ git rev-list --left-right --count origin/master...master
0	0
```

**Every number below is a command output**, and the command is quoted
beside it. Where something could not be measured, §12 says so.

**Absence is never asserted by a bare zero.** Where a number counts
something *missing*, a **positive control** is quoted beside it showing
the same command finding the thing when it IS there. §2.4 and §2.5 each
carry one, and §2.5's control is the reason this unit's sanitize gate is
scoped the way it is rather than the way the brief assumed.

**Path convention.** Every pasted command output has had the operator's
literal home prefix replaced by `~`, and nothing else altered (the drafts
convention, `scrub-personal-literals-spec.md` §"Group C"). The runner
itself contains **no absolute home path**, and `SAN1` is the criterion
that says so.

**Nothing in this unit was run against `origin`.** Every git measurement
below is local; the one remote probe is `git ls-remote --exit-code origin
HEAD`, which is read-only.

Precedence, highest first:

1. **`CLAUDE.local.md`** (local-only, in `.git/info/exclude`) — the push
   contract this runner automates. Four clauses are load-bearing and are
   quoted where they bind: *"Push `origin <current branch>` as soon as a
   loop closes cleanly"*; the three closure conditions (committed / suite
   green / gate-CLEAN); *"Never `--force` / `--force-with-lease` without
   asking first"*; and the outgoing-diff scan with its pattern set.
   **Where this spec and that file disagree, that file wins.**
2. **`03-decisions.md`** — **S-10** (behaviour never changes without a
   decision row), **S-17 D3** as amended by the local push rule, and
   **S-55** (`U-armor`'s own decision row — a LIVE row since `9b9b1a1`,
   not a reservation). This
   unit owes **one new row, `S-56`** (§10.1).
3. **`15-orchestration-runbook.md`** §1 (the round lifecycle) — this is
   the doc that describes the two-gate pipeline whose *last* step this
   unit makes a program instead of a shell chain. §10.3 is the owed
   amendment.
4. **`docs/specs/self-learn/drafts/u-armor-narrow-whole-file-pins-spec.md`**
   — **r7, SOUND at blind spec gate r5, merged at `9b9b1a1`**; committed on
   master, no longer a worktree draft. Its **build has not landed**
   (`test_armor.py` is absent — §2.6's measurement, re-run at `9b9b1a1`).
   §4.2's landing chain and its
   six-step check-then-write `--remeasure` contract. **This unit
   re-specifies none of it**; §9.1 records the interface it assumes, and
   §4.11 specifies how the runner detects which of the two worlds it is
   in.
5. **The memory `landing-script-fail-closed`** — the seven-clause "how to
   apply" list distilled from the three incidents. Every clause maps to a
   criterion in §5; §2.1's table is that mapping.
6. **`plugins/self-learn/cli/scripts/suite`** (55 lines) — the house
   style for a sanctioned runner. §2.8 reads it as the model.
7. **`misc/landing-scripts-2026-08-28/`** (git-excluded) — the four
   ad-hoc scripts, 268 lines, the only place the current chain shape is
   written down. §2.2 and §2.3 measure them.

**Precedence inside this spec.** §5's acceptance criteria ARE the spec.
Prose is rationale. Where prose and a criterion conflict, the criterion
wins.

---

## 1. Objective, and the non-objectives

**Objective.** The last step of every unit — *land the branch on master
and push* — is today a shell chain retyped from memory once per landing.
Three times on 2026-08-28 that chain shipped something wrong, each time
caught only after the fact (§2.1). Replace it with **one program in the
repository**: a runner whose every step is fail-closed, whose refusals are
covered by tests against a fixture repo, and whose conflict resolvers are
named, plugged in by argument, and unit-tested on synthetic conflicts —
rather than written fresh, per landing, in `misc/`.

**The property that makes this a unit and not a chore.** A landing chain
is a sequence of preconditions, and the three incidents are three
different ways of *printing a check instead of acting on it* (the
`lrn-ea833a5b` class — a gate whose output is identical whether it passed
or could not see the target). The runner's job is to make every one of
those checks a control-flow decision with a positive control attached.

**Non-objectives**, each a real thing a builder might reach for:

- **It is not a merge-conflict solver.** Named resolvers cover the
  measured corpus (§2.3); anything else **refuses with the conflict list**
  and hands the merge to a human. The runner never guesses.
- **It does not replace `suite`.** `land` *calls* the CLI runner and the
  UI suite; it does not reimplement batching, env scrubbing, or log
  capture (§2.8, `UN1`).
- **It does not decide whether a unit is ready.** The gate verdict is an
  **argument** (`--verdict`), transcribed by the orchestrator into the
  merge commit message. The runner asserts the argument's *shape*, never
  its truth.
- **It does not push anything but `origin master`, and never with
  `--force`.** `PSH3` is the criterion; `M24` is the mutation.
- **It does not touch `~/.self-learn`.** The ledger is severed from this
  repo and stays severed.

---

## 2. Census, measured at `6038eee`

### 2.0 Instruments, named once

Every number in §2 comes from one of these, run from the repo root on
`master` at `6038eee` with a clean tree (`git status --porcelain | wc -l`
→ `0`):

| # | instrument | what it answers |
|---|---|---|
| I-1 | `git show <ref>:<path> \| grep -c <pat>` | what a specific commit shipped |
| I-2 | `git diff A..B \| grep '^+' \| grep -c <pat>` | what a range *added* |
| I-3 | `git grep -l <pat> -- <pathspec> \| wc -l` | the whole-tree surface |

*(Every pasted command writes the operator's home prefix as `"$HOME"`,
which expands to exactly the literal that was searched for. This file
therefore contains no absolute home path, and `SAN1` holds for the spec
as well as for the runner — measured: `git grep -c "$HOME" -- <this file>`
is **0**, against the control of **14** files tree-wide in §2.5. The two
recent T2 specs set the convention: `u-verbs-…` and `u-hostmode-…` each
carry **0** occurrences of the literal.)*
| I-4 | `wc -l` | script and file sizing |
| I-5 | `git merge-tree --write-tree A B` (git 2.55.0) | conflict preview |
| I-6 | `git config [--local\|--global] merge.conflictStyle` | the diff3 dependency |
| I-7 | a throwaway `git init` fixture in `$(mktemp -d)` | conflict-marker shapes |

**Numbering control (absence, with a positive control).** `FW-139` has no
row:

```sh
$ grep -c '^| FW-139 ' docs/specs/self-learn/14-forward-work-map.md || true
0
```
Positive control, same command shape, for a number that DOES have a row —
the current ceiling:
```sh
$ grep -c '^| FW-141 ' docs/specs/self-learn/14-forward-work-map.md
1
```
`FW-139` was withdrawn by `U-verbs` r5 ("no numbered hole is left
behind"), so this unit does not take it.

**The ceilings moved during authoring, and the fold is here.** At the
anchor `6038eee` the highest live rows were `S-54` and `FW-138`, with
`S-55` and `FW-140`/`FW-141` reserved by `U-armor`. At live master
`9b9b1a1` the `U-armor` **spec** has landed and those rows are real:

```sh
$ grep -oE '^\| S-[0-9]+ '  docs/specs/self-learn/03-decisions.md      \
      | grep -oE '[0-9]+' | sort -n | tail -1
55
$ grep -oE '^\| FW-[0-9]+ ' docs/specs/self-learn/14-forward-work-map.md \
      | grep -oE '[0-9]+' | sort -n | tail -1
141
$ grep -c '^| FW-139 ' docs/specs/self-learn/14-forward-work-map.md || true
0                          # still no row; the FW-141 control above reads 1
```

**This unit takes `S-56`, `FW-142` and `FW-143`** — unchanged by the move,
and now backed by live rows rather than by another unit's reservation.

### 2.1 The three incidents — the motivating measurements

All three happened on 2026-08-28 (incident 1's merge landed 2026-08-27
23:50), all three were caught only after the fact, and all three were
fixed forward — which for a **public** repo means the defect is still in
history.

| # | what shipped | mechanism | measured | fix-forward | the criterion that closes it |
|---|---|---|---|---|---|
| **1** | An **unfolded spec carrying six absolute home paths**, merged and pushed | A **newline-chained** script: the `python3` fold aborted on an assertion, wrote nothing, and the following statements ran anyway — commit, merge, push. The sanitize scan's count was **printed, never tested** | `git show 8d716ff:…/u-corrob-tool-events-consumer-spec.md \| grep -c "$HOME"` → **6**; `git diff 0e96a91..8d716ff \| grep '^+' \| grep -c "$HOME"` → **6** | `104f6db` (same file at that commit → **0**). **The six paths remain in history at `8d716ff`, on a public remote** | `SAN2` (the count is an `if`, not an `echo`), `SAN3` (added lines only), `EXC1` (`set -uo pipefail` + an explicit `\|\| die <code>` on every step — **not** `set -e`, which gate B-1 measured incompatible with rc capture) |
| **2** | A **stale armor pin** inside a pushed merge | The pin was re-derived **after** the merge commit. The suites passed — they read the *working tree*, which was correct — so a green suite could not see it. The pushed `HEAD` (`4cdd577`) carried the old sha | `git show 801c746` → 1 file, 1 line: `test_u_fake.py` pin `cf9dc010…` → `136391df…` | `801c746` | `CHK2` (every pin vs live bytes, **inside** the merge, before `git commit`), `WLD1`/`WLD2` (post-`U-armor`: `--remeasure` runs at the same point) |
| **3** | A **docs commit that landed but was never pushed** | `HITS=$(… \| grep -c …) && …` — `grep -c` exits **1** on a zero count, so the `&&` chain broke **exactly when the gate PASSED**, after the commit and before the push | see the fence below | none needed (the push was run by hand afterwards; `master` and `origin/master` are level today) | `SAN2` (`\|\| true`, then test the **value**), `EXC1` |

**Incident 3's mechanism, measured directly** — this is the whole bug in
four lines:

```sh
$ N=$(printf 'a\nb\n' | grep -c 'zzz'); echo "value=$N rc=$?"
value=0 rc=1                       # <-- the gate PASSED and the chain died
$ N=$(printf 'a\nb\n' | grep -c 'a');   echo "value=$N rc=$?"
value=1 rc=0                       # <-- the gate FAILED and the chain continued
$ N=$(printf 'a\nb\n' | grep -c 'zzz' || true); echo "value=$N rc=$?"
value=0 rc=0                       # <-- the fix
```

The middle line is why this is not a style nit: under `&&`-chaining alone,
`grep -c` inverts the gate. The commit that landed unpushed is `6038eee`
(`2026-08-28 13:58:14 -0700`, *"docs(14): collapse the duplicate FW-130
row…"*).

**The `U-armor` spec names this gap explicitly** — *"the landing chain
script is not in this repository"* — and its §4.2 defines the
`test_armor.py --remeasure` step the chain must run **inside** the merge
commit, as a six-step check-then-write. That step has nowhere to live
until this unit ships.

### 2.2 The chain as it exists — four ad-hoc scripts, 268 lines

`misc/landing-scripts-2026-08-28/` is git-excluded and is the only written
record of the current shape:

```sh
$ wc -l misc/landing-scripts-2026-08-28/*.py
   25 misc/landing-scripts-2026-08-28/landing-checks.py
   77 misc/landing-scripts-2026-08-28/resolve-cachelit.py
   97 misc/landing-scripts-2026-08-28/resolve-fw117.py
   69 misc/landing-scripts-2026-08-28/resolve-hostmode.py
  268 total
```

Three of the four are **per-landing** resolvers, written fresh each time.
All four hardcode the repo root as an absolute home path
(`R = pathlib.Path("~/repos/self-learn")`, written literally) — which is
why they can never live in the repo as they stand, and why `SAN1` forbids
that literal in the shipped runner.

The three resolvers share, by copy-paste, an identical **`blocks()`**
diff3 parser (~14 lines each) and an identical **`rewrite()`** driver.
`resolve-cachelit.py` and `resolve-fw117.py` each carry their own copy of
`per_key()`, differing only in `resolve-fw117.py`'s added `both_changed`
re-derive door. **That duplication is the unit's raw material**: one
parser, one driver, a registry of named resolvers.

`landing-checks.py` (25 lines) is the only non-per-landing script, and it
already does four of the six things `CHK1`-`CHK6` require — conflict
markers, `_ARMOR_SHAS` vs live bytes, `S-`row order, landing-state prose
with a quoted-pattern exemption. It is the shipped design's starting
point, not a discard.

### 2.3 The conflict corpus — 13 blocks, and a FOURTH shape

Read off the three resolvers, every conflict block they were written to
handle:

| script | file | block | shape |
|---|---|---|---|
| cachelit | `test_u_sdka.py` | 0 | keep-both **variant** — `o + t[1:]`, asserting the dropped line is the shared prefix |
| cachelit | `test_u_sdka.py` | 1 | **per-key** |
| cachelit | `14-forward-work-map.md` | 0 | **keep-both** (empty base) |
| fw117 | `test_u_fake.py` | 0 | **keep-both** |
| fw117 | `test_u_fake.py` | 1 | **keep-both** |
| fw117 | `test_u_fake.py` | 2 | **per-key** |
| fw117 | `test_u_fake.py` | 3 | **count-line** — `base + (ours-base) + (theirs-base)` |
| fw117 | `test_u_fake.py` | 4 | **keep-both** |
| fw117 | `test_u_fake.py` | 5 | **count-line** |
| fw117 | `test_worker_contract.py` | 0 | **per-key** + both-changed **re-derive** |
| fw117 | `test_worker_contract.py` | 1 | **keep-both** |
| fw117 | `14-forward-work-map.md` | 0 | **keep-both** |
| hostmode | `14-forward-work-map.md` | 0 | **numeric-rows** (`FW-` sort, asserting monotonic + no dupes) |

**Totals: 13 blocks — keep-both 6, keep-both-variant 1, per-key 3,
count-line 2, numeric-rows 1.**

**The finding.** The brief names three resolvers (`keep-both`, `per-key`,
`numeric-rows`). Those cover **10 of 13** measured blocks. The remaining
three are two **`count-line`** blocks and one **keep-both variant**. This
matters because `count-line` is not a niche shape: it resolves an assertion
of the form `assert len(X) == N` where both sides added entries, and it is
the arithmetic that makes an additive union *consistent* with the count
that guards it. A `keep-both` union with an unmerged count is a merge that
imports cleanly and then reddens.

**RULED (Q-1, §3.4): ship four resolvers** — `keep-both`, `per-key`,
`numeric-rows`, `count-line` — and `count-line` is **`[A]`**, not the
`[B]` this section originally recommended. The keep-both **variant** stays
unbuilt: it is treated as an ordinary `keep-both` whose *shared prefix* is
a conflict the resolver refuses, because an overlap means the hunk was not
purely additive, which is exactly when a human should look.

The argument that survives the ruling is this section's own, and it does
not rest on how many landings needed `count-line`: **an additive union
whose guarding count is left unmerged produces a merge that imports
cleanly and then reddens.** Two measured blocks show it
(`resolve-fw117.py` 3 and 5). §3.4 records the one figure in the ruling's
warrant that this spec could not confirm.

### 2.4 The diff3 dependency — a fail-open in the current shape

Every resolver parses `||||||| ` base markers. That marker exists only
under `merge.conflictStyle = diff3`. Measured:

```sh
$ git config --local  merge.conflictStyle || echo '(unset)'
(unset)
$ git config --global merge.conflictStyle
diff3
$ git config --show-origin merge.conflictStyle
file:~/.gitconfig	diff3
```

**The setting lives in the operator's global `~/.gitconfig`, not in the
repository.** Measured in a **fresh** I-7 fixture whose repo-local
`merge.conflictStyle` is confirmed unset, same branches, same merge — the
number is the count of `^|||||||` base-marker lines the merge produced:

```
$ git config --local merge.conflictStyle || echo '(unset)'
(unset)                                  # the confound control, checked FIRST

                                  config reports   base markers produced
  plain                              diff3                 1
  HOME=/nonexistent                 (unset)                0     <-- the dependency
  GIT_CONFIG_GLOBAL=/dev/null       (unset)                0     <-- the dependency
  scrubbed + the runner's own -c     n/a                   1     <-- the fix
```

The last row is the criterion: **with `-c merge.conflictStyle=diff3` on its
own invocation, the runner produces base markers even with the global
config removed.** `PRV3` requires exactly that, and `M10` drives it under
`GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null`.

*(**Instrument note, and it is the reason the confound control is quoted
first.** The first version of this probe re-used a fixture in which
`git config merge.conflictStyle diff3` had been set **locally** during
setup. It reported `diff3` under `HOME=/nonexistent` **and** under
`env -i` — i.e. it reported "no dependency" for all three scrubbing
mechanisms, which is the same answer a working scrub would give and the
same answer a broken probe gives. A fresh repo separates them. This is the
`lrn-ea833a5b` shape appearing inside this spec's own measurement, caught
by asking what the command prints when it cannot see the target.)*

Under `merge` style the `blocks()` parser's inner
`while not lines[i].startswith("||||||| ")` walks off the end of the file
and raises `IndexError` — it does not silently mis-resolve. That is the
lucky half. The unlucky half is that **the correctness of a repository
script would depend on a dotfile outside the repository**, on a public
repo whose whole point is that a second machine can run it. `PRV3` closes
it: the runner passes `-c merge.conflictStyle=diff3` on the `git merge`
invocation itself and **asserts a base marker is present** before any
resolver runs.

### 2.5 The sanitize surface — and why the brief's `plugins/` scoping is vacuous here

The brief asks for *"the §9 personal-literals gate over `plugins/`"*.
Measured, that gate is **green today and would have been green during
incident 1**:

```sh
$ git grep -l "$HOME" -- plugins/ | wc -l
0
```
Positive control, same command, whole tracked tree:
```sh
$ git grep -l "$HOME" -- . | wc -l
14
$ git grep -l "$HOME" -- . | head -3
docs/specs/self-learn/drafts/public-release-spec.md
docs/specs/self-learn/drafts/scrub-personal-literals-spec.md
docs/specs/self-learn/feedback/2026-07-18-ui-feedback-03.md
```

**Incident 1's six paths were in `docs/specs/self-learn/drafts/`.** A gate
scoped to `plugins/` cannot see them. So the personal-literals gate is
kept — `CHK5`, over `plugins/`, where it guards *shipped product* — but it
is **not** the sanitize gate, and the two must not be confused.

**And as of `99d310e` that gate is a shipped test, so `CHK5` calls it
rather than reimplementing it.** `U-scrub` landed
`plugins/self-learn/cli/tests/test_personal_literals.py`, which enumerates
every tracked file under `plugins/` via `git ls-files` resolved from the
file's own repo root, and ships its own non-vacuity control
(`test_positive_control_docs_specs_scanner_is_not_vacuous`). A second
implementation inside `land` would be a second thing to keep correct and a
second place for the two to disagree. `CHK5` therefore invokes the shipped
test at merge time — **before** the commit, which is earlier than the suite
step would reach it — and `M25` mutates the invocation, not a private
copy.

The sanitize gate is scoped by **diff, not by path**, and to **added
lines only**. The discriminating measurement, on the incident's own range:

```sh
$ git diff 0e96a91..8d716ff | grep '^+' | grep -c "$HOME"
6                                   # would have REFUSED
$ git grep -l "$HOME" 8d716ff -- . | wc -l
16                                  # red on a correct tree, useless as a gate
```

Added-lines-only reports **6** on the bad range and **0** on a clean one:

```sh
$ git diff master..u-land-spec | grep '^+' | grep -c "$HOME" || true
0
```

A whole-tree grep reports **16** at that commit and **14** today — it is
red whether or not anything is wrong, which is the same fail-shape as an
`echo`. `SAN3` pins the added-lines scoping; `M20` is the mutation that
widens it back to whole-file and shows the criterion reddening on a
*correct* tree.

### 2.6 The armor pin surface — today, and after `U-armor`

Today the pins are a literal dict in one file:

```sh
$ grep -n '_ARMOR_SHAS = {' plugins/self-learn/cli/tests/test_worker_contract.py
542:_ARMOR_SHAS = {
$ grep -cE '^\s+"plugins/[^"]+": "[0-9a-f]{64}"' plugins/self-learn/cli/tests/test_worker_contract.py
7
```

Seven pins, checked by `test_su4a_whole_file_armor_shas`
(`test_worker_contract.py:775`), with two sibling assertions in
`test_u_sdka.py:236` and `test_u_corrob.py:1319`.

After `U-armor` lands, the mechanism becomes
`plugins/self-learn/cli/tests/test_armor.py` with a `--remeasure` mode
whose contract is that spec's §4.2: **resolve the new anchor, census,
compute the owed set, refuse writing nothing if it is non-empty, then
render the whole module atomically via `os.replace()`, then fail on a
no-op anchor.** It runs *inside* the merge, between the resolver and
`git commit`, which is precisely where incident 2 was not.

**Both worlds must work**, because `U-armor` lands first but a landing may
happen in between. §4.11 specifies the detection; `WLD1`/`WLD2` are the
criteria; `M17`/`M18` are the mutations.

### 2.7 The suites, and the known-failure allowlist

Two suites, run sequentially:

| suite | invocation | size |
|---|---|---|
| CLI | `plugins/self-learn/cli/scripts/suite` | 89 test files (`ls plugins/self-learn/cli/tests/*.py \| wc -l`) |
| UI | `uv run --project . pytest` **run from `plugins/self-learn/ui`** | 52 test files (`ls plugins/self-learn/ui/tests/*.py \| wc -l`) |

**`CLAUDE.local.md:12` quotes the UI command in its rootless form
(`uv run --project plugins/self-learn/ui pytest`), and that form is wrong for
a program** — gate B-2 measured it collecting the CLI tree at rc 2 (§4.6).
Fine for a human who runs it from wherever and reads the mess; fatal for a
runner whose cwd is fixed by `PRE1`. The table above states the form `land`
uses.

The one sanctioned red, from `CLAUDE.local.md`:

```sh
$ grep -n 'def test_both_units_document_manual_registration_via_symlink' \
      plugins/self-learn/ui/tests/test_service_unit.py
121:def test_both_units_document_manual_registration_via_symlink() -> None:
```

Today that allowlist lives **in prose, in a local-only file** — which
means it is neither versioned nor machine-readable, and "any *new* failure
does [block]" is enforced by a human reading two suite outputs. `SUI3`
makes it a file in the repository; `SUI4` makes the file's own accuracy a
test.

### 2.8 `scripts/suite` — the house style this runner copies

55 lines (`wc -l`). Its own header states what each line encodes, and four
of those are directly reusable here:

- **env scrubbing** — `env -u SELF_LEARN_ANALYST_MODEL -u
  SELF_LEARN_ANALYST_TIMEOUT` (host exports distort 8 tests into false
  failures);
- **rc captured unpiped** — `> "$OUT/$name.log" 2>&1` then `echo $? >
  "$OUT/$name.rc"`; the header says *"every batch's exit code is captured
  unpiped (redirect, never a pipe)"*, which is `lrn-ea833a5b`'s rule
  written in the repo's own words;
- **one explicit `uv sync`, then `uv run --no-sync`** so parallel runs
  never race the venv;
- **`set -u`**, `exit 0` iff every batch exited 0, one summary line per
  batch, and the instruction *"Run it in the FOREGROUND from an agent"*.

`land` adopts all four and adds `-e` and `-o pipefail` (§4.10, `EXC1`) —
`suite` can use bare `set -u` because it deliberately tolerates a red
batch long enough to report all three; `land` must not tolerate anything.

### 2.9 Preconditions the current chain never checks

Measured on the live worktree set, these are checks no shipped script
performs today and that `PRE1`-`PRE7` add:

```sh
$ git worktree list
~/repos/self-learn                                6038eee [master]
~/repos/self-learn/.claude/worktrees/u-armor-spec 3b8e037 [u-armor-spec]
~/repos/self-learn/.claude/worktrees/u-jsdom      3b8e037 [u-jsdom]
~/repos/self-learn/.claude/worktrees/u-scrub      37f48c4 [u-scrub]
~/repos/self-learn/.claude/worktrees/u-verbs      43f499b [u-verbs]
$ git -C .claude/worktrees/u-verbs      status --porcelain | wc -l
4
$ git -C .claude/worktrees/u-armor-spec status --porcelain | wc -l
1
```

Two of the four branch worktrees are **dirty right now**. Under today's
chain, `git merge` would merge the *committed* tip and silently leave
those edits behind in the worktree — the builder's last changes never
land, and nothing says so. `PRE4` refuses. (A spec worktree is deliberately
uncommitted until its blind gate closes; **ruling Q-2 settled that this does
not put spec-only landings out of scope** — the orchestrator commits the
spec, then runs `land`, and `PRE4` is unchanged. §3.4, §4.6a.)

`git ls-remote --exit-code origin HEAD` returns **rc 0** here; `PRE6`
makes reachability a precondition rather than something discovered after
the merge commit already exists.

---

## 3. DECISION — the text `03-decisions.md` owes (`S-56`)

### 3.1 The option map

| | option | cost | what it buys | verdict |
|---|---|---|---|---|
| **A** | Status quo — retype the chain per landing, keep resolvers in `misc/` | 268 lines rewritten per landing; three defects in one day | nothing | **rejected** (§3.3) |
| **B** | A checklist in the runbook, still hand-run | one doc edit | a human reads it, then does what they did before | **rejected** |
| **C** | A shell script only — the chain, `&&`-linked, no resolvers | ~120 lines | closes incidents 1 and 3; leaves conflict resolution ad hoc, which is incident 2's neighbourhood | **rejected** |
| **D** | **A shell runner + a resolver package in the repo + a fixture-repo test suite** | ~250 lines of runner and resolvers, ~400 of tests, one decision row, one runbook amendment | every step fail-closed **and covered by a test that has been observed to fail**; resolvers named, versioned, unit-tested | **RECOMMENDED** |
| **E** | D, plus the runner also decides gate readiness (reads gate verdicts, refuses on a missing gate) | a judgement surface inside a mechanical tool | would close the "someone landed without a gate" hole | **rejected** (§3.3) — the verdict is an argument, not an inference |

### 3.2 The recommendation — option D, and the sentence it rests on

**A landing is a chain of preconditions, and the repository — not the
operator's shell history — is where that chain belongs.**

Everything else follows. If the chain is in the repository, it can have
tests; if it has tests, each refusal path can be *observed to fire*; if
each refusal fires, "the gate passed" and "the gate could not see the
target" stop being the same output. The three incidents are three
instances of that one confusion, and no amount of care at the keyboard
fixes a class.

Option D's second half — the resolvers — is what distinguishes this from
option C. §2.3 measured 13 conflict blocks across three landings and
found **four shapes, three of them recurring**. A shape that recurs is a
function; a function that resolves someone's merge deserves a unit test on
a synthetic conflict, not a fresh 77-line script under `misc/` with the
repo root hardcoded as an absolute home path.

### 3.3 Designs rejected, with the measurement that rejected each

- **A (status quo).** Rejected by §2.1: three defects on one day, two of
  them shipped to a public remote and fixed forward (so still in history).
- **B (checklist).** Rejected by incident 3's mechanism: the operator
  *knew* the sanitize rule and still shipped an unpushed commit, because
  the failure was in `grep -c`'s exit status, not in the operator's
  intent. A checklist cannot see a rc-1-on-zero.
- **C (shell only).** Rejected by §2.3: 3 of 13 blocks (`count-line`, and
  the `per_key` both-changed re-derive) require arithmetic and hashing
  over merged bytes. Doing that in shell is how incident 2 happened — the
  re-derive was a separate step, and a separate step can run late.
- **E (the runner judges readiness).** Rejected by `S-29`'s tiered-autonomy
  floor and by the two-gate design itself: the gate verdict is a human-
  routed judgement. A tool that *infers* "this looks gated" would create a
  path where a unit lands because a string matched. The verdict is
  `--verdict`, its **shape** is asserted (`CHK6`), its truth is not.
- **A whole-tree sanitize grep.** Rejected by measurement, §2.5: it reports
  **16** at the offending commit and **14** on today's correct tree — red
  either way.
- **Resolvers selected automatically by heuristic** (e.g. "empty base ⇒
  keep-both"). Rejected: `resolve-cachelit.py`'s block 0 has a non-empty
  overlap and `resolve-fw117.py`'s blocks 3 and 5 have non-empty bases that
  are *not* per-key — an automatic classifier would have picked wrong on 3
  of 13 measured blocks. The resolver is **named by the operator**
  (`--resolver`), per file, and refuses when it does not recognise the
  block (`RES4`).

### 3.4 Rulings — orchestrator, 2026-08-28

All six §11 questions are ruled. §11 is now the index; the reasoning and
the criteria/mutation consequences are here.

| | ruling | consequence in this spec |
|---|---|---|
| **Q-1** | **Four resolvers — ACCEPTED. `count-line` is `[A]`, not `[B]`** | `RES7` `[B]` → **`[A]`**; §4.4's table drops its "(§11 Q-1)" hedge; totals 49 `[A]` / 1 `[B]` before the new criteria below |
| **Q-2** | **OVERRULED — spec-only landings are IN scope for r1** | new §4.6a (the docs-only lane), new **`SUI6`**/**`SUI7`**, new `M47`/`M48`/`M49`; `FW-142` **re-scoped, not withdrawn** (§10.2) |
| **Q-3** | **Re-anchor unconditionally; `--remeasure` decides — ACCEPTED** | §4.11 and `WLD1`/`WLD2` already say this; §4.5's chain gains the explicit "no docs-only exemption" sentence |
| **Q-4** | **Named resolvers only — ACCEPTED; an unnamed conflict refuses with the block list AND the resolver names that would apply** | `PRV2` gains a third leg, `RES4` gains the suggestion surface, new `M50` |
| **Q-5** | **`scripts/land`, not the shipped CLI — ACCEPTED** | already `S-56` corollary (d); no change |
| **Q-6** | **`--sanitize-ack` is content-bound — ACCEPTED; the ack names the exact line AND its adjudication, never a boolean** | `SAN4` rewritten; the ack is a two-field record, not a hash alone |
| **F-1** | **The runner passes `-c merge.conflictStyle=diff3` on its own `git merge` and refuses if the output lacks base markers — never relies on the operator's dotfiles** | `PRV3` says it explicitly; `M10` runs under a scrubbed config (§2.4's corrected probe) |
| **F-2** | **Sanitize scope = the outgoing diff's ADDED lines — ACCEPTED as `SAN3`; and the pattern set becomes a repo file the runner reads** | new **`SAN5`** and `M51`; §4.7a decides where the canonical list lives |

**Q-1, and one number this spec will not transcribe.** The ruling's stated
warrant is that `count-line` "would have needed hand-editing in two of
tonight's five landings". **This spec cannot confirm that count**, and says
so rather than restating it. What is measurable here is narrower: tonight
saw **14** first-parent merges on `master`
(`git log --first-parent --merges --since=2026-08-28T00:00:00`), of which
exactly **three** left a resolver script in `misc/`, and `count-line`
appears in **one** of those three (`resolve-fw117.py`, 2 of its 6 blocks).
The other eleven landings left no script, so whether they merged cleanly or
were hand-resolved is **not recoverable from the repository**. The ruling
is followed regardless — it does not depend on the exact count, and §2.3's
own argument (an additive union whose guarding count is left unmerged
reddens) stands on the two blocks that *are* measured. §12 item 8 records
the gap.

**Q-2, and why the overrule is right.** The recorded recommendation was
"no, not in r1", reasoning that a `--spec-only` mode which commits someone
else's uncommitted work is incident 1's shape. **The overrule separates two
things the recommendation had fused.** Committing the branch is *not* what
Q-2 asks for — `PRE4` still requires the branch committed before `land`
runs, and that is unchanged. What Q-2 asks for is that a landing whose
outgoing diff touches only `docs/` still be *landable by the runner*, with
a test selection proportionate to the change. Incident 1 **was** a
spec-only landing; a runner that refuses the one case that has already
failed leaves the most error-prone path on the scratchpad, which is the
opposite of this unit's objective. The overrule is accepted in full.

### 3.5 Blind spec gate r1 — every finding, and what changed

**VERDICT: NOT SOUND — 1 Blocker, 11 Majors, 8 Nits.** 31 of 36 checked
claims reproduced exactly. The gate's own summary of what to preserve —
§2.4's confound self-report, `M36`'s two-leg note, §2.5's scoping
correction, and the positive-control habit — is honoured: none of those
changed, and r3 adds two more self-reports in the same shape (§3.5a).

| finding | what it measured | what changed in r3 |
|---|---|---|
| **B-1** | `set -euo pipefail` and the rc-capture idiom are **mutually exclusive** — measured: under `-e`, `false > log 2>&1; rc=$?` never reaches `rc=$?` and the `.rc` file is **never written**, so every refusal exits bash's `1` instead of §4.10's 2–7 | §4.10 rewritten to `set -uo pipefail` + explicit `\|\| die <code>`; §4.3/§4.6/§4.8 restated; **`SUI5` rewritten** to pin that form; new **`M53`** drives the `-e` form and shows the collapse |
| **M-1** | The "7 `src/` modules hold a corpus-doc path" claim is **false** under the walk the spec describes: strict (docstrings excluded) = **0** | §4.6a re-derived; the indirect-reader residual **does not exist**; `SUI7` leg (b) becomes a **detector** (the count must stay 0); `M49` re-aimed; `FW-142` re-scoped to the residual that **is** measured (§10.2) |
| **M-2** | 39 / 43 / 4 do not reproduce; they were a **docstring-inclusive** walk presented as a strict one | §4.6a now **quotes the walk verbatim** and restates: 142 modules, naive 41, docstring-inclusive 38, **strict 8** |
| **M-3** | The verbatim pattern file scores **4 hits** on its own added lines; the r2 spec scored **3**. `land` would refuse its own landing | §4.7a takes U-scrub's road: the file stores **fragments**, the loader joins them. Measured: assembled regex **equals** the spec's set, fragment file **0** self-hits. New **`M54`** |
| **M-4** | The denylist detector misses **81** tracked files that are neither `docs/` nor matched — `ui/static/app.js`, `uv.lock`, `pyproject.toml`, `hooks/*.sh`, `plugins/self-learn/scripts/self-learn`, `install.sh`, `tests/fixtures/*` | The detector is now an **allowlist** — the docs lane iff **every** changed path is under `docs/`. Fail-closed by construction. `SUI6` legs and `M47`/`M48` re-aimed |
| **M-5** | §4.5's "armor/five-file tests" step between `--remeasure` and `git commit` makes `U-armor`'s `ARM5` leg (b) **red on every correct landing** | **The step is deleted.** §4.5's chain is now exactly `U-armor` §4.2. New **`CHK8`**: no test runs between `--remeasure` and the commit. New **`M55`** |
| **M-6** | World detection has no stated timing and `CHK2` has no non-vacuity floor — on `U-armor`'s own landing (`DEL1` deletes `_ARMOR_SHAS`) the regex finds **0** pins and prints a pass | Detection runs **post-merge**; asserts **exactly one** mechanism present; `CHK2` gains an **N ≥ 1** floor. New **`M56`** |
| **M-7** | `per-key` silently corrupts a hunk with a duplicate key — executed: `['a: 1','a: 2','b: 10']` → `['a: 2','a: 2','b: 10']`, no refusal | `per-key` refuses duplicate keys on any side and lines that are not `key: value`. `RES2` legs; new **`M57`**, **`M58`** |
| **M-8** | **0** fetches in the spec (control: `origin/master` **12**), yet three gates are scoped by that ref | New **`PRE8`** (`git fetch origin master`, rc unpiped) with the ref-freshness rule stated; new **`M59`** |
| **M-9** | `SAN4` has no partial-ack leg: N hits with one valid ack satisfies all four legs and waves through the rest | Ack coverage is now **exact** — N hits require N acks, keyed `(file, line-number, sha)`; a partial ack refuses; the split is the **first `=` after the hash**. New **`M60`** |
| **M-10** | `--dry-run` invokes `CHK5` against the wrong tree (the test resolves its root from **its own on-disk location**), and `DRY2` excludes it | §4.1 states the **root-resolution rule** for the whole package; the dry run invokes `$TMP`'s copies; `DRY2` gains `CHK5` and `SAN3`. New **`M61`** |
| **M-11** | §12.1's r2 sweep reported `LIVE: 0` with a live hedge at line 531 (§2.9's present-tense "§11 Q-2 asks…") | Folded; the sweep re-run and published (§12.1), with **this miss as the new positive control** |
| **gate flag** | No resume path: codes 5–7 preserve the merge commit, but the only sanctioned recovery discards it; a naive re-run sets `ANCHOR` to the merge commit — the value `U-armor`'s B-1 was about | **RULED**: new §4.10a **`--continue`**, a landing-state file under the cache dir (never in the tree). New **`CNT1`**/**`CNT2`**, **`M62`**/**`M63`** |
| **N-1** | `git rev-parse --git-dir` = `.git` is cwd-dependent — and so is a naive `--git-common-dir` compare (from `plugins/`: `…/self-learn/.git` vs `../.git`) | `PRE1` uses `--path-format=absolute` on **both** and compares. Measured YES at the main root **and** in a subdir, `no` in both linked worktrees |
| **N-2** | `DOC1`-`DOC3` are `[A]` with **no mutation column** | §5.5 gains one: **`M64`**, **`M65`**, **`M66`**; `DOC1`/`DOC2` gain positive controls |
| **N-3** | The chain never `git add`s the resolver output | §4.5 adds it explicitly; `CHK1` reads the **staged** merge |
| **N-4** | `count-line`'s registry signature has no `name`, and the three sides' `NAME` need not agree | `RES7` gains a leg requiring the three `NAME`s to match; new **`M67`** |
| **N-5** | `RES3`'s fixture may already be ascending, leaving `M14` green | `RES3` now **requires** the fixture's two sides to be out of numeric order |
| **N-6** | `CHK6`'s "subject budget" names no number | Measured: the repo's last 40 first-parent subjects top out at **158** chars; the budget is **200**, stated |
| **N-7** | `SUI5` listed after `SUI7` | Reordered |
| **N-8** | `PSH4` runs `git worktree remove` unconditionally after the push | `PSH4` tolerates an absent worktree; the prune is best-effort **after** the push and cannot fail the landing |

### 3.5a Two self-reports r3 owes, in §2.4's shape

The gate singled out §2.4's confound self-report as the best thing in the
spec. r3 owes two more of the same kind, and states them rather than
quietly correcting the numbers:

1. **My `src/` walk and my `tests/` walk were not the same walk, and I
   presented them as one.** The `tests/` figure (39) came from an
   `ast.walk` over **every** `Constant` — which includes docstrings, because
   a docstring *is* an `Expr(Constant)`. The `src/` figure (7) came from the
   same code and so also counted docstrings. I then described both as
   *"a corpus-doc path in a real string constant (not a docstring or
   comment)"*, which is what the code did **not** do. The whole
   indirect-reader argument, `SUI7` leg (b), `M49`'s **MEASURED** label and
   `FW-142`'s residual were built on that. §4.6a now ships the walk as
   runnable code and reports all three columns side by side, so the two can
   never diverge again.
2. **§4.7a reasoned correctly about the wrong gate.** It argued the six
   generic patterns *"are ordinary English words and public prefixes, not
   personal literals"* — true, and the right answer for `CHK5`. It then
   concluded they *"trip nothing"*, which is false for the **sanitize**
   gate, whose whole job is to match those words. The paragraph even named
   U-scrub's fragment precedent and declined it. The failure was applying
   one gate's reasoning to a different gate one sentence later.

### 3.6 Blind spec gate r2 — every finding, and what changed

**VERDICT: NOT SOUND — 1 Blocker, 5 Majors, 6 Nits.** All 20 r1 findings
verified closed, 19 with numbers that reproduce exactly. The gate's list of
what to preserve — the B-1 rebuild, §3.5a's two self-reports, shipping the
walk as runnable code, the allowlist, `CHK8`, the exact-coverage ack — is
untouched.

| finding | what it measured | what changed in r4 |
|---|---|---|
| **B-2** | The UI suite invoked from the repo root **collects the wrong tree**: rc **2**, collection errors, importing the CLI tests' `support.py`. `land` runs from the root *by construction* (`PRE1`), so the full lane would refuse on **every** landing — reported as "ui suite red", which it is not | §4.6 sets **cwd = `plugins/self-learn/ui`** and asserts the run collected **only** `ui/tests`; **rc 2 is a third refusal class** beside rc 1 and rc 124. `SUITE_TIMEOUT` from the measured 243 s / 230 s. New `SUI8`, `M69`/`M70` |
| **M-12** | The allowlist takes the **docs lane on a rename into `docs/`** — measured: `git mv src/verbs.py docs/verbs.py` shows only `docs/verbs.py`, so a `src` module was deleted and 8 test modules ran | The detector uses **`git diff --name-only --no-renames`**; new `SUI6` rename leg; `M71` |
| **M-13** | `--continue` **does not bind the merge sha**: the original merge, an **amended** merge and a **second merge on top** all pass its three conditions | The state file records the merge sha at merge time; a **fourth precondition** compares it and its parents. `CNT2` leg, `M72` |
| **M-14** | `ADDED=$(git diff … \| grep '^+')` is a flat stream — **no file, no line numbers**, so `SAN4`'s ack key is unproducible; and `+++ b/<path>` is scanned, so a path containing a pattern word is a hit | §4.7 parses **`git diff --unified=0`** `@@` headers to `(file, line-number, text)`; headers excluded **by construction**. `SAN3` legs, `M73` |
| **M-15** | `SAN5` leg (d)'s **path exemption list** is a standing, non-content-bound, per-path skip — in `docs/specs/self-learn/drafts/`, the directory incident 1 happened in | **Leg (d) DELETED. No path exemptions, ever.** This spec's three hits are acked through `--sanitize-ack` (§3.6b); fixture files are **generated at test time** from fragments. `M74` |
| **M-16** | `M49` was **stale and measured-false** — still *"7 `src/` modules hold a doc path"*, retracted by §4.6a in the same document, while §12.1's sweep reported `LIVE: 0`. **Fourth surfacing of the `lrn-ea833a5b` class in this document's own tooling** | `M49` re-aimed; the retracted sentence added to §12.1's patterns; **the sweep now covers the MEASURED rows**; and the durable fix — new **`UN4`**, every MEASURED row re-measured at build start. `M75` |
| **`SUI7` leg** | The part-built set is today a **subset** of the direct set, so a dropped union step is invisible | New leg (e): a synthetic part-built module that is **not** a direct hit |
| **N-9** | `M51` still named `sanitize_patterns.txt` | → `sanitize_fragments.txt` |
| **N-10** | `M48`'s prose was still denylist language | Rewritten in allowlist terms |
| **N-11** | §4.7a's *"added lines: 18"* — the block is **8** lines | Corrected to **8** |
| **N-12** | `SAN4`'s line-number frame unstated | The **new-file line number** from the `@@ -old +new` header |
| **N-13** | `CHK8`'s collector would match §4.5's own `git add …/test_armor.py` | Collector matches **process invocations**, not paths; exclusions stated |
| **N-14** | §12 items 2 and 10 are now measured | Both folded with the numbers |

### 3.6a The docs-only lane — adjudicated KEEP, by measurement

| run | wall clock | result |
|---|---|---|
| the 8-module docs lane | **29 s** | 354 passed |
| CLI suite (`scripts/suite`, 3 batches) | **243 s** | rc 0 |
| UI suite (**correct cwd**) | **230 s** | 1173 passed, 1 failed (the allowlisted symlink test), 96 skipped |
| **full lane** (sequential, as §4.6 requires) | **473 s ≈ 7 m 53 s** | |
| **saving** | **444 s — 94 %** | |

Coverage given up: 354 of 3,836 non-skipped tests = **9.2 %**. And **the docs
lane runs zero UI tests** — all eight modules are in `cli/tests`, consistent
with the walk (strict UI-test hits are 0) but stated plainly, because it is
the sharpest thing a reader should know about the lane. `U-jsdom` is a live
UI-only unit, which is exactly why `M-12`'s rename hole mattered.

**KEEP.** r2's own defence retreated from *"28 % is not a dramatic saving"* —
a sentence r3 deleted. The real figure is **94 % of wall clock** on the most
frequent landing kind, and it converts a step that today gets **no** suite at
all into a named, guarded, 29-second one. §12 items 2 and 10 close on these
numbers.

### 3.6b The acks this unit's own landing will carry

`M-15` deletes the path-exemption escape, so this spec's own sanitize hits go
through `--sanitize-ack` — **making this unit's landing the mechanism's first
worked example**, which is the right way for a gate like this to earn trust.
The spec is a **new file**, so every line is an added line and the added-line
number *is* the file line number.

**The count is 23 at r6 — it was 19 at r5, 13 at r4, 3 at r3 — and
reporting the drift is the point of this section.** Nothing was smuggled in:
each revision *adds* sections that quote the pattern words in order to
discuss them. r6 added §3.8 and, in §4.7, the `diff --git` anchor evidence
with **two** parser fixtures side by side. **A count of occurrences in a
document is not a property of the design — it is a property of the draft,
and it moves every time the draft does.** That is why this section states a
rule and a measurement rather than a frozen list, why the runner computes
the keys at landing, and why the number is re-measured every round rather
than carried forward.

| section | hits at r6 | what they are |
|---|---|---|
| §3.6b (this table) | 1 | the row describing §4.7a's result line |
| §3.7 | 1 | gate r3's `M-18` finding row, quoting the fixture's seeded line |
| §4.7 | 16 | the parser evidence — the `--unified=0` fixture, the `secret_fixture.md` path control, the `++ b/evil-path` collision, the deleted-`-- ` variant with both parsers, and the quoted pattern set |
| §4.7a | 2 | the `grep -cEi …` command and its `4` result |
| §5.4 | 1 | `SAN3`'s criterion cell restating the control |
| §6 | 1 | `M73`'s mutation cell |
| §R | 1 | r6's revision row |

**Every one is the gate's own vocabulary being discussed, never a
credential**, and that is the adjudication each ack carries. `CHK6`'s verdict
and the merge body carry all of them, so a reviewer sees exactly what was
waved through and why.

The shas are computed **at landing**, not pinned here: any edit to those
lines must invalidate the ack, and pinning a sha inside the file the sha is
taken from would be circular. **`UN4` is what keeps this table honest** — it
re-measures at build start, so a stale 3 cannot survive into a build the way
it survived into this draft.

*(If 23 acks is judged too many to type, the alternative is not an exemption
— it is writing the pattern words in §4.7/§4.7a in the same fragment form
`sanitize_fragments.txt` uses, which would drop the count to near zero at the
cost of making the evidence harder to read. That is a legibility-versus-
ceremony call for the orchestrator, and it is recorded as §12 item 13 rather
than decided here.)*

### 3.7 Blind spec gate r3 — every finding, and what changed

**VERDICT: NOT SOUND — 0 Blockers, 3 Majors, 5 Nits.** All 12 r2 findings
closed. The gate's recorded held-attacks — ack coverage in both directions,
moved-line key invalidation, the 13-hit count, the scratch-dir-outside-tests
control, and the binary/mode-only/no-newline edge cases — are unchanged.

| finding | what it measured | what changed in r5 |
|---|---|---|
| **M-17** | **`UN4` is unimplementable and passes vacuously.** Measured: **9 of 11** MEASURED cells carry **no command at all**; the other two are prose fragments. And there is no count floor — a parser matching nothing runs zero commands and reports PASS | New **§6.1, the MEASURED ledger**: one fenced ` ```measured M<n> ` block per row with a `measure:` command and an `expect:` value, **all 11 written and run** (§6.1's run table). `UN4` gains the **count floor** `parsed_rows == 11` with its own control — measured: a parser matching nothing parses **0** and now FAILS, and deleting one row parses **10** and FAILS. `M76`, `M77` |
| **M-18** | **The `@@` parser mis-parses an added line whose content begins with `++ b/`.** Reproduced: the line is consumed as a file header, so it is **never scanned**, `collide.md` is lost entirely, and the later hit is attributed to a fabricated path `evil-path` at a reset line number — a `SAN4` ack key naming a file not in the tree | `+++ ` is a header **only when it immediately follows a `--- ` line**. Verified on the same fixture: `('collide.md', 1, '++ b/evil-path')`, `('collide.md', 2, 'SEEDED ghp_…')`, hit correctly attributed. New `SAN3` legs for the collision and all four edge cases. `M76` |
| **M-19** | **`SUI8` leg (b) and `M69` pin numbers that depend on untracked state** — the gate's fresh worktree measured 32 error lines / 2668 cli ids where the production root measured 331 / 3327, differing only by git-excluded `misc/`. `UN4` re-runs MEASURED claims and refuses the build, so two criteria interlock into a deterministic false refusal on any machine whose `misc/` differs | `SUI8` leg (b) and `M69` assert **stable predicates**; the counts move to prose as a dated **OBSERVED** note. `UN4` gains the rule that **a MEASURED claim may not depend on untracked state** — its parser refuses a row whose command reads outside tracked files, or the row is marked OBSERVED. `M78` |
| **N-15** | §4.7's `SAN3` bullet still read *"added lines only (`grep '^+'`)"* — the flat form `M73` exists to reject, two screens from the criterion that replaced it; r4's sweep missed it **in the section the fix landed in** | Folded; the phrase added to §12.1's pattern set |
| **N-16** | `M72` and `M73` were the **only two of 75** mutations unreferenced by any criterion | `CNT2` now names `M72`, `SAN3` names `M73`. Re-verified: **0** unreferenced |
| **N-17** | `SUI8` leg (b)'s prefix check passes with an untracked scratch test **inside** `ui/tests/` — measured 1271 collected, 0 outside the prefix | Leg (b) asserts every collected id maps to a **tracked** file (`git ls-files` membership). `M79` |
| **N-18** | `SAN4` leaves the operator to hand-derive 13 ack keys, and any edit above a hit shifts them | `SAN4` **prints paste-ready `--sanitize-ack` strings** on refusal |
| **N-19** | §4.11's world detection reads two paths **bare and relative** in the runner's own shell, while §4.1's rule is `--root <abs>`; under `--dry-run` those reads hit the main checkout, and `DRY2` did not cover `WLD1`/`WLD2` | Both reads are `--root`-relative; `DRY2` gains `WLD1`/`WLD2`. `M80` |

### 3.8 Blind spec gate r4 — every finding, and what changed

**VERDICT: NOT SOUND — 0 Blockers, 3 Majors, 3 Nits.** All 8 r3 findings
closed. The gate ran §6.1's ledger with **a parser it wrote from the prose
alone** and got 10 of 11; both blind-direction floor controls reproduced;
the ack count 19 reproduced with per-hit line numbers falling in exactly the
sections §3.6b names.

| finding | what it measured | what changed in r6 |
|---|---|---|
| **M-20** | `m73.sh` read `$OLDPWD/misc/u-land-measured/parse.py` — **git-excluded**, so `M73` reproduced only on the author's machine. Worse, no `set -e` and no existence check meant the missing file yielded `flat=1 parsed=` at **rc 0** — a passing-looking line with a silently missing number. `UN4` leg (d) inspects the ledger's *command string*, not the helper's transitive reads, so it could not see this | Every helper resolves siblings via `"$(dirname "$0")"` and calls `need <file>` which **exits 3 loudly**. New `UN4` leg (e): **the whole ledger is run from a clean detached checkout with no `misc/`**, and every block must pass there. `M81`, `M84` |
| **M-21** | The `+++ ` after `--- ` rule **misfires when a DELETED line's content begins `-- `**: git emits `--- old marker line`, which sets `prev_minus`, and the next added line `++ b/evil-path` is eaten as a header. Reproduced: `f.md:1` never scanned, hit attributed to **`evil-path:3`** | The parser **anchors on `diff --git`** and treats header lines as occurring only **before the first `@@` of each file**. Content lines are always prefixed, so `diff --git` cannot be spoofed. Verified on both fixtures; `SAN3` keeps both as legs. `M82` |
| **M-22** | **14 rows labelled MEASURED, 11 ledger blocks, floor a literal `11`.** Three MEASURED claims (`M76`, `M77`, `M78`) sat outside the mechanism built to verify MEASURED claims, and `UN4` passed. `M78` was also **mislabelled** — its claim is the untracked-state comparison that leg (d) says must be OBSERVED | `M76` and `M77` get ledger blocks (both runnable); `M78` is relabelled **OBSERVED**; and **the floor is DERIVED** — `floor.py` compares the *set* of MEASURED mutation ids against the *set* of ledger block ids and reports `missing`/`extra`. `M83` |
| **N-20** | `M69`'s row still quoted the 331/3327 counts §4.6's own OBSERVED table says must not be pinned | The row quotes only the predicate form |
| **N-21** | No r5-round sweep was published; the gate found live drift in exactly r5's new material | §12.1 publishes the r5/r6 sweep over §6.1, the OBSERVED table and `M76`–`M80`, and says what this revision's own re-measurement found |
| **N-22** | Helpers carried no `set -uo pipefail` and no existence checks | All helpers source `_lib.sh` (`set -uo pipefail`, `HERE`, `need`); the ledger runner fails on a **non-zero helper rc** as well as a mismatched `expect:`. `M84` |

### 3.9 Blind spec gate r5 — every finding, and what changed

**VERDICT: NOT SOUND — 0 Blockers, 1 Major, 2 Nits.** All six r4 findings
closed **and verified by execution**, not by reading.

| finding | what it measured | what changed in r7 |
|---|---|---|
| **M-23** | **Shipping the helpers into `cli/tests/measured/` (§8) makes `walk.py` count ITSELF.** `walk.py`'s `CORPUS` regex is the string constant `'(^\|[^\w])docs/'` — a real, non-docstring constant containing `docs/` — so it is a strict hit. Measured at `9c7ebdd`: **144 / 43 / 39 / strict 8** without the directory, **149 / 44 / 40 / strict 9** with it. `SUI7` legs (a) and (c) would redden **on a correct build**, and no ledger row checked the tests column | **Root cause, not an exemption**: the helpers are **measurement instruments, not tests** — 0 collected ids — so they do not belong under `tests/`. They ship at **`plugins/self-learn/cli/scripts/measured/`**, beside `scripts/suite` and `scripts/land`. **Verified first, as ruled**: the walk's roots are `cli/tests`, `ui/tests`, `cli/src`, `ui/src` — **`scripts/` appears 0 times** — and re-measured with the helpers staged there the walk reads **144 / 43 / 39 / strict 8**, identical to baseline. New `SUI7` leg (f) + `M85` |
| **N-24** | `floor.py`'s "against r5's text" control was not reproducible while the spec was still a draft | The control is the **deletion form**: `floor.py --delete-one` drops the first ledger block and reports `missing=M20`. The commit-ref form applies once the spec lands |
| **N-25** | `M77` hardcoded the spec path | `_lib.sh` gains `spec_path()`, a glob over `docs/specs/self-learn/**/u-land-*.md` **asserting exactly one match** and exiting 3 otherwise; `M77` calls it |

**No path exclusion was added to the walk.** The ruling was explicit that if
the walk's roots *had* included `scripts/`, that was to come back for a
decision rather than be silently patched. They do not, and the numbers
above are the evidence.

### 3.10 Blind spec gate r6 — SOUND; the three nits, folded

**VERDICT: SOUND — 0 Blockers, 0 Majors, 3 Nits.** The gate's own
independent sweep found nothing live. The nits are folded here without a
re-gate, as ruled.

| nit | what it found | what changed in r8 |
|---|---|---|
| **N-26** | The totals line's label counts were not checked by anything — a sum check alone cannot catch a mis-labelled row | **`floor.py` now checks all three label counts against the totals line** and reports `MATCH`/`MISMATCH`, plus a **stray-bold** check. Root cause fixed too: a bold `**MEASURED**`/`**OBSERVED**` token may now appear **only in the status column**, because a substring scan of a row whose *evidence* mentions the other label miscounts it |
| **N-27** | `spec_path()`'s `exit 3` inside `$(spec_path)` leaves only the **subshell** — the caller continued with an empty value and rc 1 | The caller tests the substitution: `SPEC=$(spec_path) \|\| exit 3`, plus an empty-value guard. **Verified**: 0 matches ⇒ **rc 3**, 2 matches ⇒ **rc 3**, 1 match ⇒ rc 0 |
| **N-28** | No r7-round sweep was published | §12.1 publishes it |

**One adjudication the gate should see.** N-26 stated the counts were
"5 OBSERVED (M69, M78, M81, M84, M85) and 67 predicted". Measured, they are
**4 OBSERVED and 68 predicted**: `M69`'s *status* cell is
`**MEASURED** (§6.1)` and `M69` **has a ledger block**, so labelling it
OBSERVED would break the floor (`extra=M69`). The bold `**OBSERVED**` the
gate saw was in `M69`'s *evidence* cell, describing the counts behind its
predicates — a substring match, which is the identical trap this spec's own
first classifier fell into at r6 (§12.1). Rather than adjudicate it in
prose, r8 makes it undecidable-by-accident: the stray token is removed, and
`floor.py` now refuses any row carrying a bold label outside the status
column. The check's output is quoted in §6.1.

---

## 4. Design

### 4.1 Shape and layout

```
plugins/self-learn/cli/scripts/land                  # the runner (bash)
plugins/self-learn/cli/scripts/measured/             # the §6.1 ledger's instruments
    _lib.sh  walk.py  parse.py  floor.py  m5*.sh  m6*.sh  m7*.sh  pat.txt
plugins/self-learn/cli/src/self_learn/landing/
    __init__.py
    conflicts.py     # blocks(): the ONE diff3 parser; rewrite(): the ONE driver
    resolvers.py     # keep_both / per_key / numeric_rows / count_line + REGISTRY
    checks.py        # landing checks: markers, pins, row order, prose, literals
    known_failures.txt        # the allowlist, one node-id per line (SUI3)
    sanitize_fragments.txt    # pattern FRAGMENTS; the loader joins them (SAN5)
    doc_reading_set.txt       # the docs-only lane's 8 test modules (SUI6/SUI7)
plugins/self-learn/cli/tests/
    test_landing_resolvers.py    # synthetic conflicts, one per resolver
    test_landing_checks.py       # each check, positive control first
    test_land_runner.py          # fixture repo: every refusal path + happy path
```

The runner is **bash** (like `suite`, and because its subject is git and
process exit codes); the resolvers and checks are **python** (because
their subject is text, arithmetic and sha256). The runner calls
`python3 -m self_learn.landing.<mod>` and branches on the exit code.

**Root resolution — one rule for the whole package** *(gate M-10)*. No
module in `landing/` infers the repo root: **the runner passes `--root
<abs>` and every module requires it.** The runner computes it once as
`git rev-parse --path-format=absolute --show-toplevel` from its own working
tree. This matters because it is externally defined for one check:
`U-scrub`'s `test_personal_literals.py` resolves its root from **its own
on-disk location** — measured at `99d310e`:

```python
# plugins/self-learn/cli/tests/test_personal_literals.py:88
["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"]
```

So *which copy of that test you invoke* decides *which tree it scans*.
Under `--dry-run` the runner must invoke **`$TMP`'s** copy, not the main
checkout's (§4.9, `DRY2`, `M61`).

**Invocation:**

```sh
plugins/self-learn/cli/scripts/land \
    --branch u-something \
    --verdict 'blind Opus code gate CLEAN r3 with mutation verification' \
    [--resolver <path>=<name> ...] \
    [--dry-run]
```

### 4.2 Step 1 — preconditions (`PRE1`-`PRE7`)

Each is a refusal, each prints the value it saw:

1. `PRE1` cwd is the **main checkout**, not a linked worktree. The
   predicate is **both paths resolved absolutely, then compared** *(N-1)*:

   ```sh
   [ "$(git rev-parse --path-format=absolute --git-dir)" \
   = "$(git rev-parse --path-format=absolute --git-common-dir)" ]
   ```

   r2 wrote *"`git rev-parse --git-dir` equals `.git`"*, which is
   cwd-dependent — and a naive `--git-common-dir` compare is too. Measured
   at `99d310e`, all four cases:

   | cwd | equal? |
   |---|---|
   | main checkout, root | **YES** |
   | main checkout, `plugins/` subdir | **YES** (r2's form and the naive compare both say *no* here) |
   | `.claude/worktrees/u-land-spec` | no |
   | a detached `--detach` worktree | no |
2. `PRE2` `HEAD` is `master`: `git symbolic-ref --short HEAD` = `master`.
   A detached HEAD refuses (`CLAUDE.local.md`: *"Never push … a detached
   HEAD"*).
3. `PRE3` master's tree is clean: `git status --porcelain` emits **0**
   lines. Positive control in the test: the same command on a seeded dirty
   tree emits ≥1.
4. `PRE4` the branch exists, is **not** `master`, and **its worktree (if
   one is registered) is clean** — `git -C <wt> status --porcelain` → 0
   lines. §2.9 measured two live worktrees that fail this today.
5. `PRE5` the branch is a descendant of, or a sibling of, `master`:
   `git merge-base --is-ancestor master <branch>` OR
   `git merge-base master <branch>` resolves. An unrelated history refuses.
6. `PRE6` origin is reachable: `git ls-remote --exit-code origin HEAD`,
   rc captured **unpiped**.
6b. `PRE8` **`git fetch origin master`**, rc captured unpiped, **before any
   scope is computed** *(gate M-8)*. Measured on r2: `git fetch` appeared
   **0** times in the spec (positive control: `origin/master` appeared
   **12**), yet `origin/master` is a remote-tracking ref that moves only on
   fetch or push, and it defines `SAN3`'s scan range, §4.6a's lane
   classification and `PSH2`'s `old..new`. **Rule: every one of those three
   is computed against the FETCHED ref**, and if the fetch moves
   `origin/master` at all the runner **refuses** (exit 2) rather than
   proceeding against a base that changed under it — a landing must be
   built on a base the operator saw.

   The concrete bite this closes is the runner's own recovery design: codes
   5–7 leave the merge commit local, so on the next run `origin/master..HEAD`
   spans **both** landings, the sanitize gate re-scans the previous
   landing's added lines, and any `--sanitize-ack` adjudicated for them is
   gone (the ack is content-bound to that run). §4.10a's `--continue` is the
   other half of that fix.
7. `PRE7` **no `--force` anywhere**: the runner has no force flag, and
   `PSH3` asserts the literal `--force` does not appear in the script.

### 4.3 Step 2 — preview (`PRV1`-`PRV4`)

```sh
git merge-tree --write-tree master "$BRANCH" > "$OUT/preview.txt" 2>&1
rc=$?                      # unpiped; safe because §4.10 drops `set -e`
case $rc in
  0) LANE_CLEAN=1 ;;
  1) LANE_CLEAN=0 ;;                       # a conflict is the CENTRAL case
  *) die 3 "merge-tree failed rc=$rc" ;;
esac
```

**rc 1 is not an error here — it is the conflicted preview**, which is why
`set -e` cannot be in force at this line (gate B-1, §4.10).

Measured contract (git 2.55.0, I-5/I-7):

| case | rc | stdout |
|---|---|---|
| clean | **0** | tree oid |
| conflict | **1** | tree oid, then `<mode> <oid> <stage>\t<path>` rows, blank line, `CONFLICT (…)` messages |
| `--name-only` conflict | **1** | tree oid, then the conflicted **paths**, one per line |

- `PRV1` rc 0 ⇒ proceed with no resolver; **if a `--resolver` was named
  anyway, refuse** (a resolver for a conflict that does not exist means
  the operator's model of the merge is wrong).
- `PRV2` rc 1 ⇒ read the conflicted paths from
  `git merge-tree --write-tree --name-only`. **Every conflicted path must
  have a `--resolver` mapping**; any unmapped path refuses, printing the
  full conflict list **and, per block, the resolver names whose
  preconditions that block satisfies** *(ruling Q-4)* — e.g. an empty-base
  block prints `keep-both`, a `key: value` block prints `per-key`. The
  suggestion is a **diagnostic, never a default**: the runner still
  refuses, and the operator must name the resolver on the command line.
  Printing the candidates is what makes "named only" workable for an agent
  without letting it infer one.
- `PRV3` the merge is run as
  `git -c merge.conflictStyle=diff3 merge --no-ff --no-commit` — **the
  `-c` is on the runner's own invocation, so the base markers come from
  the runner and never from the operator's dotfiles** *(ruling F-1)* — and
  the runner then **asserts at least one `^|||||||` line exists** in each
  conflicted file before invoking a resolver. If the assertion fails the
  runner refuses (exit 3); it never parses a conflict it cannot see the
  base of (§2.4).
- `PRV4` the preview runs **before master's working tree is touched**.
  Nothing has been modified when a conflict refusal fires.

### 4.4 Step 2b — the resolvers

**One parser, one driver, N named resolvers.** `conflicts.blocks(text)`
is the single diff3 parser (lifted from the three copies in §2.2);
`conflicts.rewrite(path, resolver)` is the single driver, and it keeps the
existing scripts' final assertion: **no marker may remain** after a
rewrite.

`resolvers.REGISTRY` maps a name to a callable
`(ours, base, theirs) -> list[str] | Refusal`:

| name | precondition it asserts | resolution | refuses when |
|---|---|---|---|
| **`keep-both`** | `base == []` (purely additive) | `ours + theirs` | base is non-empty, or ours and theirs share a line (the §2.3 variant — an overlap is not additive) |
| **`per-key`** | every line is `key: value`; **no side contains a duplicate key**; the key sets of ours, base and theirs are equal | per key, the side that differs from base wins | a key changed on **both** sides to different values **and** no re-derive is registered; the key sets differ; **a duplicate key on any side**; **a line with no `:`** |
| **`numeric-rows`** | every line matches `^\| (S\|FW)-(\d+) ` | union, sorted by the number | a number appears twice, or the result is non-monotonic |
| **`count-line`** | ours, base, theirs are each **one** line matching `assert len\(NAME\) == (\d+)`, **and the three `NAME`s are equal** *(N-4 — the registry signature is `(ours, base, theirs)` with no name argument, so the resolver extracts `NAME` itself and must check it)* | `base + (ours-base) + (theirs-base)`, rewritten with a dated inline justification | any side is not exactly one line, or the arithmetic yields a negative |

**Why `per-key`'s two new refusals are not defensive padding** *(gate M-7,
executed)*. The stated precondition — equal key sets — **cannot see a
duplicate key**, because the dict comprehension collapses it before the
comparison:

```
base    ['a: 1', 'a: 2', 'b: 9']
ours    ['a: 1', 'a: 2', 'b: 10']
theirs  ['a: 1', 'a: 2', 'b: 9']
result  ['a: 2', 'a: 2', 'b: 10']     <- 'a: 1' silently replaced, NO refusal
```

`per-key` is the resolver that writes **armor pins**, so a silently dropped
line here is incident 2's class arriving through a different door.
`numeric-rows` already refuses a duplicate number; the asymmetry was the
defect. The second refusal is its sibling: a line without a colon becomes
its own key (`'no-colon-line'.split(':')[0]` → `'no-colon-line'`), so the
"every line is `key: value`" precondition was stated and never enforced.

**The both-changed door (`per-key`).** When both sides changed a key and
that key names a **pinned file**, the resolver may `re-derive` — compute
the sha256 of the *merged bytes* and write it, **with a dated
justification line**. That is `resolve-fw117.py`'s `REDERIVE` mechanism,
promoted. `RES5` requires the justification: a date (`20\d\d-\d\d-\d\d`)
**and** a reason naming both sides. A re-derive with no justification
refuses — the pin would otherwise be a number nobody can audit.

**Every resolver has a unit test on a synthetic conflict** built by I-7
(a `mktemp -d` git repo, three commits, a real `git merge`), never by
hand-writing marker text — so the tests exercise the same bytes git
actually produces. `RES6`.

### 4.5 Step 3 — merge, landing checks, commit

Order is load-bearing, and it is the order incident 2 got wrong:

```
git -c merge.conflictStyle=diff3 merge --no-ff --no-commit "$BRANCH"
  → resolvers (per --resolver mapping)
  → git add <every path a resolver rewrote>        # N-3: the chain stages it
  → world detection (post-merge, staged)           # M-6
  → landing checks CHK1..CHK7
  → armor: --remeasure --anchor $(git rev-parse --short=7 HEAD)
           (post-U-armor)  OR  the _ARMOR_SHAS check (today)
  → git add plugins/self-learn/cli/tests/test_armor.py     # post-U-armor only
  → git commit          # <-- everything above rides INSIDE this commit
```

**Nothing runs between `--remeasure` and `git commit`** *(gate M-5,
`CHK8`, `M55`)*. r2's chain inserted an "armor/five-file tests" step there.
That step is **deleted**, for a measured reason: `U-armor`'s `ARM5` leg (b)
asserts `ANCHOR == M^1` where `M = git rev-list --first-parent --merges -1
master`. At that insertion point the merge commit **does not exist yet**,
so `M` is the *previous* merge while `ANCHOR` has just been advanced to the
pre-merge tip — leg (b) would be red on **every correct landing**. The
armor tests run after the commit, in the suites, which is exactly what
`U-armor` §4.2's own chain does. The step also had no criterion and no
mutation, so under §0 (*"§5's criteria ARE the spec"*) it was mandated by a
diagram and specified nowhere.

**The re-anchor is unconditional** *(ruling Q-3)*. There is no docs-only
exemption and no "nothing protected moved, skip it" shortcut: `U-armor`
§4.2's leg (b) asserts `ANCHOR == M^1` for the **latest** first-parent
merge, so a landing that skipped the re-anchor would make the *next*
landing red for a reason unrelated to it. `--remeasure` is the thing that
decides whether there is work to do; the runner's job is to call it every
time. When `test_armor.py` is absent — the pre-`U-armor` world, live today
— the runner runs the `_ARMOR_SHAS` check at the same point instead
(§4.11).

The landing checks, each a refusal with a printed count:

- `CHK1` **no conflict markers** in any file the merge touched
  (`git diff --name-only master...HEAD` on the staged merge, plus the
  resolved set) — not a fixed doc list. `landing-checks.py` hardcodes
  three docs plus `drafts/u-*.md`; a marker in a fourth file is invisible
  to it.
- `CHK2` **every armor pin vs live bytes**, printing
  `pins checked: N; mismatches: [...]`, refusing on any. Today N = **7**.
- `CHK3` **`S-` and `FW-` row order** in `03-decisions.md` and
  `14-forward-work-map.md`: monotonic and duplicate-free. (Measured: the
  `FW-` sequence on master is **not** globally monotonic — the file holds
  several tables — so the check is *per contiguous table run*, and its own
  positive control is the duplicate `FW-130` that `6038eee` collapsed.)
- `CHK4` **landing-state prose**: the `landing-checks.py` pattern set,
  with the quoted-pattern exemption preserved. Incident 1's other half.
- `CHK5` **the §9 personal-literals gate over `plugins/`**, run by invoking
  `U-scrub`'s shipped `test_personal_literals.py` — not a private copy of
  the grep (§2.5). 0 hits today, positive control 14 tree-wide.
- `CHK6` the **merge commit message** is built from `--verdict`: subject
  `Merge branch '<branch>' (<unit> — <verdict>)`. The runner asserts the
  verdict's **shape** (non-empty, no newline, within the subject budget)
  and refuses on an empty one. It does not assert its truth.

### 4.6 Step 4 — the suites

Sequentially, never in parallel (they share `uv`), each bounded, each rc
captured unpiped into its own `.rc` file — `suite`'s own pattern:

```sh
SUITE_TIMEOUT=${SUITE_TIMEOUT:-600}   # measured: CLI 243 s, UI 230 s (§3.6a)

run_suite() {                       # $1 = name, $2 = cwd, rest = argv
  local name=$1 dir=$2; shift 2
  ( cd "$dir" && timeout "$SUITE_TIMEOUT" "$@" ) > "$OUT/$name.log" 2>&1
  local rc=$?                       # reached, because §4.10 has no `set -e`
  printf '%s\n' "$rc" > "$OUT/$name.rc"
  return 0                          # never abort here; the caller adjudicates
}
run_suite cli "$ROOT"                       plugins/self-learn/cli/scripts/suite
run_suite ui  "$ROOT/plugins/self-learn/ui" \
              env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT \
              uv run --project . pytest -q          # <-- cwd is the UI project

for n in cli ui; do
  rc=$(cat "$OUT/$n.rc")
  case "$rc" in
    0)   ;;
    124) die 5 "$n suite TIMED OUT after ${SUITE_TIMEOUT}s -- see $OUT/$n.log" ;;
    2)   die 5 "$n suite COLLECTION ERROR (rc 2) -- NOT a test failure; the
                allowlist cannot adjudicate it. See $OUT/$n.log" ;;
    *)   allowlisted_only "$OUT/$n.log" || die 5 "$n suite red -- see $OUT/$n.log" ;;
  esac
done
```

**The UI run's cwd is load-bearing, and getting it wrong breaks every
landing** *(gate B-2)*. There is **no root-level pytest config** — measured
at `99d310e`, none of `pytest.ini`, `pyproject.toml`, `conftest.py`,
`setup.cfg`, `tox.ini` exists at the repo root — and `uv run --project X`
sets the **venv**, not the collection root. So `testpaths = ["tests"]`
(`ui/pyproject.toml:56`) resolves against the *cwd*. Measured, same tree,
`--collect-only`:

**The stable predicates** — this is what `SUI8` leg (b) and `M69` assert
*(gate M-19)*:

```
from the repo root          rc == 2   AND  at least one collected id under cli/tests
from plugins/self-learn/ui  rc == 0   AND  zero collected ids outside ui/tests
```

**OBSERVED, 2026-08-28, and deliberately NOT a criterion.** The counts
behind those predicates are **not reproducible across machines**, and the
difference is itself the finding:

| where | rc | error lines | `cli/tests` ids |
|---|---|---|---|
| production root (`misc/` populated) | 2 | 331 | 3327 |
| a fresh detached worktree, same commit (`misc/` absent) | 2 | 32 | 2668 |

Same commit, same command; the gap is **only** git-excluded `misc/`
scratch directories. That is §4.6's blast-radius argument proven twice over
— and it is exactly why the counts may not be pinned: `UN4` re-runs every
MEASURED claim at build start and refuses the build on any that does not
reproduce, so pinning 331/3327 would make the build **deterministically
refuse on every machine but one**, including the code gate's own checkout.
Two correct criteria would interlock into a false refusal. The predicates
hold on both rows; the counts hold on neither.

`SUI8` asserts the run collected only `ui/tests` — and, per `N-17`, that
**every collected id maps to a tracked file**, since an untracked scratch
test *inside* `ui/tests/` satisfies a prefix check (measured: 1271
collected, 0 outside the prefix).

**rc 2 is its own refusal class.** A collection error produces **no failing
node ids**, so `SUI3`'s allowlist-subset test has nothing to compare and
cannot adjudicate it; calling it "ui suite red" names the wrong cause. The
`die 5` message says *collection error* explicitly.

**`SUITE_TIMEOUT` defaults to 600 s**, from the measured 243 s (CLI) and
230 s (UI) — roughly 2.5× the slower suite. Enough headroom that ordinary
variance cannot trip `SUI2`, tight enough that a genuine hang is caught in
ten minutes rather than never.

**`run_suite` returns 0 deliberately.** The rc is *data* written to a file,
never a control-flow abort — that is the whole of gate B-1's fix, and it is
why `SUI5` and `EXC1` can both hold (§4.10).

- `SUI1` a non-zero rc from either suite **refuses**. The merge commit
  **stays local** — the runner never rewinds it — and the refusal prints
  the exact commands to inspect (`less "$OUT/ui.log"`,
  `git log -1 --stat`) and the one command that undoes the landing (a hard
  rewind of `master` back to `origin/master`, printed for the human to run,
  never run by the tool).
- `SUI2` a `timeout` kill is a refusal that says *timeout*, distinct from
  a test failure. (A bare non-zero rc conflates the two; `timeout` exits
  124.)
- `SUI3` the known-failure allowlist is a **file in the repo**,
  `landing/known_failures.txt`, one pytest node id per line. A red run is
  tolerated **iff** the set of failing node ids is a subset of that file.
  Today the file has exactly one line:
  `plugins/self-learn/ui/tests/test_service_unit.py::test_both_units_document_manual_registration_via_symlink`.
- `SUI4` a test asserts every id in that file **resolves to a real test**
  (`pytest --collect-only <id>` succeeds). Without this the allowlist rots:
  an entry whose file was renamed silently stops covering the failure it
  was written for, and the next red run refuses for a reason nobody
  understands.

### 4.6a The docs-only lane *(ruling Q-2; re-derived at r3, gate M-1/M-2/M-4)*

**The detector is an ALLOWLIST** *(gate M-4)*. The docs lane is taken **iff
every changed path is under `docs/`**:

```sh
NONDOC=$(git diff --no-renames --name-only "origin/master..HEAD" \
           | grep -cv '^docs/' || true)
[ "$NONDOC" = "0" ] && LANE=docs || LANE=full
```

**`--no-renames` is not a detail** *(gate M-12)*. Rename detection is on by
default (`diff.renames` unset), and it reports a rename as the **new path
only** — so a file moved *into* `docs/` hides the deletion of its old path.
Measured in a fixture:

```
$ git mv src/verbs.py docs/verbs.py
$ git diff --name-only base..HEAD              ->  docs/verbs.py
      NONDOC=0  =>  DOCS LANE   (a src module was DELETED; 8 test modules ran)
$ git diff --no-renames --name-only base..HEAD ->  docs/verbs.py
                                                   src/verbs.py
      NONDOC=1  =>  FULL LANE   (correct)
```

Only the *into*-`docs/` direction is dangerous. **Control, measured**: a
rename *out* of `docs/` (`docs/spec.md` → `src/spec.md`) reports
`src/spec.md`, giving `NONDOC=1` and the full lane — fail-closed even
without the flag. Note this is an attack r2's denylist happened to survive
(the new path was still `.py`); the r3 allowlist opened it, and
`--no-renames` closes it without giving up the allowlist's other property.

`|| true` for the same reason as §4.7 — `grep -c` exits 1 on a zero count,
and **zero is the docs lane**, so under `&&`-chaining alone the detector
would break exactly on the case it exists to detect. Incident 3's mechanism,
one step earlier in the chain.

**Why an allowlist and not r2's denylist.** r2 matched
`\.py$|^plugins/self-learn/(cli|ui)/(src|scripts)/`. Measured at `99d310e`,
**81 tracked files are neither under `docs/` nor matched by that pattern**:

```
plugins/self-learn/ui/static/app.js            (U-jsdom is a live UI-only unit)
plugins/self-learn/cli/uv.lock,  ui/uv.lock    (a dependency bump)
plugins/self-learn/cli/pyproject.toml, ui/pyproject.toml
plugins/self-learn/hooks/self-learn-pending.sh, hooks/self-learn-refread.sh
plugins/self-learn/scripts/self-learn          (the shipped entry point --
                                                NOT under (cli|ui)/scripts/)
install.sh,  cli/tests/install-commands-test.sh
every golden fixture under cli/tests/fixtures/
```

A landing touching only `app.js` or only `uv.lock` would have taken the docs
lane and skipped both suites. The allowlist sends **all 81** to the full
lane and needs no enumeration of code shapes — fail-closed by construction.

**The walk, stated as runnable code** *(gate M-2 — §0 requires the command,
and r2 quoted none)*:

```python
CORPUS = re.compile(r'(^|[^\w])docs/')      # a corpus doc == a path under docs/

def docstring_ids(tree):                    # every Constant that IS a docstring
    o = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = getattr(n, "body", None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
               and isinstance(b[0].value.value, str):
                o.add(id(b[0].value))
    return o

def strict_hits(path):                      # real string constants ONLY
    tree = ast.parse(path.read_text())
    skip = docstring_ids(tree)
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and id(n) not in skip and CORPUS.search(n.value))
```

**The walk's roots are exactly four** — `cli/tests`, `ui/tests`, `cli/src`,
`ui/src`. **`scripts/` is not among them**, which is why §6.1's instruments
ship there *(gate M-23)*: measured at `9c7ebdd`, staging the helpers under
`cli/tests/measured/` takes the tests column from **144 / 43 / 39 / strict
8** to **149 / 44 / 40 / strict 9**, because `walk.py`'s own `CORPUS` regex
is a real string constant containing `docs/`; staging them under
`cli/scripts/measured/` leaves every column **identical to baseline**. No
path exclusion was added to the walk — the roots simply do not reach there.

Run at `9c7ebdd` over `**/*.py` under both test roots and both src roots:

```
pattern        scope  files  naive  docstrings-INCLUDED  STRICT
docs/specs/    tests    144     42                   38       5
docs/specs/    src       77      7                    5       0
docs/ (any)    tests    144     43                   39       8
docs/ (any)    src       77      8                    6       0
```

**r2's 39 / 43 / 4 do not appear anywhere in that table**, and the reason is
§3.5a item 1: r2's walk counted docstrings while its prose said it did not.
The lane uses the `docs/ (any)` row, because the lane's own predicate is
*"every changed path under `docs/`"*.

**The lane set is 8 modules of 144**, and they are listed in
`landing/doc_reading_set.txt`:

```
test_decision_trace.py   test_personal_literals.py   test_pointer.py
test_reader_contract.py  test_u_ancestry.py          test_u_corrob.py
test_u_glob.py           test_u_sdka.py
```

*(144 is the `rglob` count; the top-level count the suites see is **141** —
the three extras are `cli/tests/fixtures/fake_claude.py`,
`ui/tests/fixtures/fake_claude.py`, `ui/tests/fixtures/fake_self_learn.py`.
Both numbers are stated because `SUI7` walks `rglob` and §2.7 quotes the
top-level figure.)*

**The indirect-reader residual r2 claimed DOES NOT EXIST** *(gate M-1)*.
Strict `src/` hits are **0** under both patterns. The seven modules r2 named
carry their doc path in the **module docstring** — a citation of the spec
that motivated the module, not a path the module reads:

```
                   naive  incl  STRICT
corroborate.py         0     0       0
gates.py               1     1       0
scan.py                1     1       0
selfcheck.py           0     0       0     (its real constants are CLAUDE.md /
serve.py               1     1       0      lrn-*.md -- ledger artefacts, not
engine/sdk.py          1     1       0      corpus docs under docs/)
prefetch.py            1     1       0
```

`SUI7` leg (b) therefore becomes a **detector, not a coverage map**: it
asserts the strict `src/` count **stays 0**, and forces the full lane if any
`src/` module ever gains a real doc-path constant. The guard survives; the
false premise does not.

**The residual that IS real, and it is measured.** A module can build a docs
path from **parts**, holding no constant that matches `docs/` at all — and
one already does. `test_reader_contract.py` holds `'docs'` and `'specs'` as
separate string constants. So the derivation is still a lower bound, for a
reason that can be pointed at rather than asserted. Two responses:

- the set is the **union** of the direct-hit modules and the
  part-constant modules (those holding both `'docs'` and `'specs'` as bare
  constants). Measured: direct **8**, part-built **2**, **union 8** — the
  part-built pair is already a subset, so the union costs nothing today and
  catches the next one;
- `FW-142` records what the union still cannot see (§10.2).

### 4.7 Step 5 — sanitize

**The scan parses `git diff --unified=0`, not a flat `grep '^+'` stream**
*(gate M-14)*. r3's form could not produce `SAN4`'s `(file, line-number, sha)`
ack key at all — the criterion and the code it was specified with were
incompatible — and it scanned the `+++ b/<path>` header, so a *path*
containing a pattern word was a hit.

```python
# every ADDED line, carried with its file and its NEW-FILE line number
def added_lines(rng):                      # rng = "origin/master..HEAD"
    out, path, ln = [], None, 0
    in_header = False                      # <-- anchored on `diff --git` (M-21)
    for l in run("git", "diff", "--unified=0", "--no-renames", rng).splitlines():
        if l.startswith("diff --git "):  in_header = True; path = None;  continue
        if in_header:                      # headers live ONLY before the first @@
            if l.startswith("+++ "):
                path = l[6:] if l.startswith("+++ b/") else l[4:];       continue
            if l.startswith("@@"):       in_header = False   # fall through
            else:                                                        continue
        m = re.match(r"^@@ -\S+ \+(\d+)(?:,\d+)? @@", l)
        if m:                            ln = int(m.group(1));           continue
        if l.startswith("\\"):                                           continue
        if l.startswith("+"):            out.append((path, ln, l[1:])); ln += 1
    return out

hits = [(f, n, t) for f, n, t in added_lines(rng) if PATTERN.search(t)]
```

`+++`, `---` and `@@` are excluded **by construction** — consumed by the
branches above, they never reach the `startswith("+")` arm. `SAN3` carries
the leg that proves it.

**Headers are anchored on `diff --git`, not inferred from `---`/`+++`**
*(gate M-21; r5's two-line rule is retired)*. Every file's diff opens with a
`diff --git` line, and header lines occur **only before that file's first
`@@`**. Content lines are always prefixed (`+`/`-`/space), so a content line
can never spoof `diff --git` — the anchor is airtight where a two-line
window is not.

**Why the two-line rule was not enough.** It fixes the original attack but
fails one adversarial line further: when a **deleted** line's content begins
`-- `, git emits `--- old marker line`, which sets `prev_minus`, and the
*next* added line is eaten as a header. Measured on a file whose line 1
(`-- old marker line`) is replaced by `++ b/evil-path`, with a seeded secret
below:

```
r5 ('+++' after '---')   ('collide.md', 1, '++ b/evil-two')
                         ('collide.md', 2, 'SEEDED password123')
                         ('evil-path',  3, 'SEEDED ghp_…')   <- f.md:1 LOST, path fabricated

r6 ('diff --git' anchor) ('collide.md', 1, '++ b/evil-two')
                         ('collide.md', 2, 'SEEDED password123')
                         ('f.md',       1, '++ b/evil-path') <- scanned
                         ('f.md',       3, 'SEEDED ghp_…')   <- attributed correctly
```

`M76`'s ledger block runs exactly this and reports
`r5=evil-path:3 r6=f.md:3` — the fabrication and the fix in one line.

**The original `++ b/` attack, kept as a control** *(gate M-18)*. Both rules
handle it; the r6 anchor changes nothing there, which is what makes the
above a genuine one-line escalation rather than a regression. On a file
`collide.md` containing `++ b/evil-path` then `SEEDED ghp_deadbeefcafe`:

```
r4's rule (any '+++ b/' is a header)      r5's rule ('+++' only after '---')
  ('evil-path', 1, 'SEEDED ghp_…')          ('collide.md', 1, '++ b/evil-path')
                                            ('collide.md', 2, 'SEEDED ghp_…')
  HIT: ('evil-path', 1, …)                  HIT: ('collide.md', 2, …)
```

Three things were wrong at once, and the third is the worst: the `++ b/`
line was **never scanned** (a secret there is invisible); `collide.md`
vanished from the parse entirely; and `SAN4`'s ack key named **`evil-path`,
a file not in the tree**, at a line number that had been reset to 1. Not
hypothetical — this spec quotes diff output *including* `+++ b/…` lines in
fenced blocks, §4.7's own measurement block among them.

**The four edge cases all hold**, verified on one fixture carrying all of
them (`SAN3` legs):

| case | the diff emits | parser result |
|---|---|---|
| no newline at EOF | `\ No newline at end of file` | skipped (leading `\`); the added line is captured as `nonl.txt:1` |
| binary file | `Binary files … differ`, **no** `+++` header, no `+` lines | contributes nothing; `path` not corrupted |
| mode-only change | `old mode` / `new mode`, no `---`/`+++`/`@@` | contributes nothing |
| empty added line | a bare `+` | captured as `('empty.md', 1, '')`; numbering continues |

**Measured, both halves.** A fixture adding a password line and a `ghp_`
line, then separately a file *named* `secret_fixture.md` whose contents are
the word `clean`:

```
r3's flat stream                    the parsed form
  +++ b/docs/f.md                     docs/f.md:2  'SEEDED password here'
  +SEEDED password here               docs/f.md:6  'ghp_deadbeef'
  +ghp_deadbeef
  (no file, no line numbers)

adding docs/x/secret_fixture.md ("clean")
  r3 flat-grep hits: 1   <- the +++ HEADER matched
  parsed hits:       0   <- correct
```

*(`N-12`: the line number is the **new-file line number**, read from the `+`
side of the `@@ -old +new @@` header and incremented per added line — not a
position within the diff.)*

The gate is then r3's shape over `hits` rather than over a line stream:

```sh
HITS=$(python3 -m self_learn.landing.sanitize --root "$ROOT" --range "$RANGE" --count || true)
[ "$HITS" = "0" ] || refuse                       # the VALUE, not the status
```

`|| true` for the reason §2.1 incident 3 gives: a count-printing command
exits non-zero on zero, and **zero is the passing case**.

- `SAN1` the pattern set is `CLAUDE.local.md`'s, verbatim:
  `bearer [A-Za-z0-9_-]{8,}|api[_-]?key|secret|password|PRIVATE KEY|ghp_|<home-prefix>`
  — and the home prefix is **derived at runtime** (`$HOME`), never written
  as a literal in the script. A test asserts the script contains no
  absolute home path.
- `SAN2` the count is captured `|| true` and tested **as a value**.
  Its test has two legs: a seeded hit ⇒ refuse; a clean diff ⇒ proceed —
  the second leg is what incident 3 broke.
- `SAN3` the scan covers **added lines only**, over `origin/master..HEAD`,
  produced by the `--unified=0` parser above — **never a flat `grep '^+'`
  stream**, which is the form `M73` exists to reject *(N-15: r4 left this
  bullet describing the rejected form, two screens from the criterion that
  replaced it)*. §2.5's measurement is the justification for the *scope*;
  `M20` is the mutation.
- `SAN4` a hit refuses **before** the push, with the commit still local
  and the offending lines printed. `CLAUDE.local.md` allows verified
  pattern-only hits (*a spec that names `~/.self-learn`*, a fixture using
  `sandbox@example.invalid`) — the runner does **not** adjudicate those.
  It refuses and prints them; the human adjudicates and re-runs with an
  ack that is **content-bound and two-field** *(ruling Q-6)*:

  ```sh
  --sanitize-ack '<file>:<line-number>:<line-sha256>=<adjudication text>'
  ```

  Three key fields and a reason. **The split is the FIRST `=` after the
  hash** — a sha256 is 64 hex characters and contains no `=`, so the
  adjudication text may contain as many as it likes *(gate M-9)*. The
  **line number** is in the key because a content hash alone cannot
  distinguish two identical added lines in the same file, and one ack must
  never silently cover both.

  **Coverage is EXACT, not "the acks I was given are valid"** *(gate M-9 —
  this was the fail-open one level up)*. Let `H` = the hit set and `A` = the
  ack set, both keyed `(file, line-number, sha)`:

  - `A == H` ⇒ proceed;
  - any hit not in `A` ⇒ **refuse**, naming every unacked line — an
    implementation that validates the acks it received and then proceeds
    would satisfy r2's four legs while waving through every unacked hit;
  - any ack not in `H` ⇒ **refuse** — a stale or invented ack means the
    operator is adjudicating a diff that is not this one.

  **On refusal the runner prints paste-ready ack strings** — one
  `--sanitize-ack '<file>:<line>:<sha>=<reason>'` per hit, reason left
  blank for the operator to fill *(N-18)*. This unit's own landing needs
  **23** as of r6 (§3.6b — the count moves with the draft), and any edit
  above a hit shifts its line number and therefore its key, so hand-deriving them per attempt is not a realistic ask.

  The adjudication text lands in the runner's log and, for a non-empty ack
  set, in the merge commit's body, so a reviewer can see *which* literal was
  waved through and *why*. **There is no boolean form** — no
  `--no-sanitize`, no `--sanitize-ack all`. A flag meaning "skip the gate"
  recreates incident 1 with one extra keystroke; a flag meaning "I looked at
  this line and here is my reason" does not.

### 4.7a Where the canonical pattern list lives *(ruling F-2; rebuilt r3, gate M-3)*

Today the pattern set is prose in `CLAUDE.local.md`, which is
`.git/info/exclude`d — **outside the repository**, so a second machine, a
fresh clone, or a test has no way to read it. The canonical list moves into
the repo at `plugins/self-learn/cli/src/self_learn/landing/`.

**r2 stored the patterns verbatim and claimed they "trip nothing". That is
false, and the gate measured it.** Presenting the file's seven lines as
added lines and running the gate's own scan:

```sh
$ grep -cEi 'bearer [A-Za-z0-9_-]{8,}|api[_-]?key|secret|password|PRIVATE KEY|ghp_' <the file>
4                 # secret, password, PRIVATE KEY, ghp_ each match themselves
```

The r2 spec itself scored **3** by the same test. Since `SAN3` scans the
added lines of `origin/master..HEAD` and both files are new on this unit's
landing, **`land` would have refused to land its own pattern file and its
own spec.** §3.5a item 2 is the post-mortem: the "ordinary English words"
argument is right for `CHK5` and wrong for the sanitize gate.

**r3 takes U-scrub's road** — the precedent §4.7a already named and then
declined. The file stores **fragments that never spell a token**, and the
**loader joins them**:

```
# landing/sanitize_fragments.txt  -- one pattern per line, fields separated by |
bea | rer | " [A-Za-z0-9_-]{8,}"
api | [_-]? | k | ey
sec | ret
pass | word
PRIVATE | " " | K | EY
gh | p_
%HOME%
```

Measured, and this is `SAN5` leg (c)'s proof rather than its assertion:

```
assembled regex == the spec's pattern set : True
fragment file, added lines               : 8
fragment file, self-hits                 : 0
```

The `%HOME%` line stays a placeholder the runner substitutes from `$HOME` at
read time, so no absolute home path is stored either. **One source, zero
self-hits, and the assembled regex proven equal to the set this spec
quotes** — the equality check is the positive control that keeps the
fragments from drifting into a different pattern.

**There is no path exemption list, and there never will be** *(gate M-15 —
r3 shipped one as `SAN5` leg (d); it is deleted)*. Three reasons, the third
decisive:

1. It contradicted its own scope — leg (d) admitted *this spec*, a
   non-fixture path, while promising a leg proving the list "cannot be
   widened to a non-fixture path".
2. A path allowlist is a **standing, non-content-bound, per-path skip**.
   Once this spec's path is exempt, the sanitize gate never scans that file
   again — including for a real absolute home path. §2.5 measured that
   incident 1's six home paths were in `docs/specs/self-learn/drafts/`; the
   exemption carves a permanent hole in exactly that directory.
3. It is the shape this spec's own doctrine rejects one paragraph earlier:
   *"A flag that means 'skip the gate' recreates incident 1 with one extra
   keystroke."* Leg (d) was that flag wearing a path instead.

**The two real cases are handled without an escape hatch:**

- **This spec's own hits** go through `--sanitize-ack` — exact,
  content-bound, per-run, auditable, already `[A]`. §3.6b records them, the
  reasons the merge body will carry, and **why the count is measured at
  landing rather than pinned** (gate r2 measured 3 on r3's text; r4's own
  text measures **13**, because r4 added four sections that quote the
  pattern words as evidence). This unit's landing becomes the ack
  mechanism's first worked example.
- **The seeded-hit fixtures** that `SAN2` and `SAN4` need are **generated at
  test time** from the same fragments, so the literal never exists as a
  tracked byte and there is nothing in the tree for the gate to find. `SAN5`
  leg (d) is now **that** requirement — a grep asserting no tracked fixture
  file contains an assembled pattern, with the generator's runtime output as
  the positive control.

### 4.8 Step 6 — push and prune

- `PSH1` `git push origin master`, rc captured unpiped.
- `PSH2` prints `old..new` from the `git rev-parse origin/master` read
  **before** and **after** — a positive control, not an echo. A push that
  moved nothing prints an identical pair and is reported as such.
- `PSH3` the script contains **no** `--force` and no `--force-with-lease`
  (a grep over the shipped file; `CLAUDE.local.md` makes this a user
  decision, so the tool must not have the capability at all).
- `PSH4` prune runs **only after** a successful push, and is **best-effort
  by construction**: `git worktree remove <wt>` is attempted only if
  `git worktree list --porcelain` names one for the branch, and its failure
  is reported, never fatal *(N-8 — a branch with no registered worktree
  must not fail a landing that has already pushed)*. Then
  `git branch -d <branch>` — `-d`, never `-D`: a branch that is not merged
  must not be deletable by this path. A prune failure exits **0** with a
  printed warning naming what to clean up by hand.

### 4.9 `--dry-run`

`--dry-run` performs **everything up to and including the would-be commit
in a throwaway worktree**, then reports and removes it. Nothing on master
is touched, nothing is pushed.

```sh
git worktree add --detach "$TMP" master     # measured available, git 2.55.0
# every landing module is invoked with --root "$TMP"  (§4.1)
# every test the runner SHELLS OUT to is $TMP's copy, never the main checkout's
python3 -m self_learn.landing.checks --root "$TMP" ...
"$TMP"/plugins/self-learn/cli/scripts/... # CHK5 runs $TMP's test_personal_literals.py
git worktree remove --force "$TMP"
```

**Why the copy matters** *(gate M-10)*: `test_personal_literals.py` resolves
its root from **its own on-disk location** (§4.1's measurement), so
invoking the main checkout's copy would scan the main checkout and report a
clean tree while the merged dry-run tree carried the literal. `DRY2` is
therefore parameterised over **`CHK5` and `SAN3`** as well as `PRE3`,
`PRV2` and `CHK2` — r2 excluded exactly the check whose root resolution is
externally defined.

- `DRY1` after a `--dry-run`, `git rev-parse master` and
  `git status --porcelain` on the main checkout are **byte-identical** to
  their pre-run values, and `git worktree list` has the same line count.
- `DRY2` a `--dry-run` that would refuse **refuses with the same message
  and the same exit code** as the real run. (Otherwise a dry run is a
  different program and proves nothing.)
- `DRY3` `--dry-run` never reaches step 5 or 6 — the sanitize scan is
  reported, the push is not attempted, and the printed summary says
  `DRY RUN — nothing pushed`.

### 4.10 Exit codes and the shell contract *(rebuilt r3, gate B-1)*

**`set -uo pipefail` — NOT `-e` — plus an explicit `|| die <code>` on every
step.** r2 specified `set -euo pipefail` *and* pinned the rc-capture idiom
as a criterion (`SUI5`). The gate measured that these are **mutually
exclusive**, and re-measuring confirms it:

```
form                                                        result
(1) set -euo pipefail; false > log 2>&1; rc=$?              nothing printed, script rc=1
                                                            -- `rc=$?` never runs
(2) set -euo pipefail; timeout 1 false > log 2>&1;
    echo $? > out.rc                                        out.rc NEVER WRITTEN, rc=1
(3) set -uo pipefail;  timeout 1 false > log 2>&1;
    rc=$?; echo "$rc" > out.rc; [ "$rc" = 0 ] || die 5      REACHED rc=1, out.rc=1,
                                                            script rc=5      <-- SHIPS
(4) timeout 1 sleep 5                                       rc=124  (SUI2's premise holds)
(5) set -uo pipefail; false | cat > /dev/null; rc=$?        rc=1 -- pipefail still works
```

Form (2) is exactly what `SUI5` pinned, and it never writes the file `SUI1`
and `SUI2` read. Under `-e` every refusal would exit bash's **1**, not its
own code, so `EXC1`'s table collapsed and `SUI2`'s timeout branch could
never fire — the `.rc` file does not exist to be read.

**Form (3) ships, and it makes `EXC1` and `SUI5` both hold**, which is the
thing r2 could not do:

- `SUI5` holds because the rc is still captured **unpiped, by redirect**
  (`> log 2>&1` then `rc=$?`) and still written to its own `.rc` file —
  `lrn-ea833a5b`'s rule and `suite`'s own idiom, unchanged;
- `EXC1` holds because the *adjudication* is a separate, explicit statement
  (`[ "$rc" = "0" ] || die 5 …`) that exits **its own** §4.10 code;
- form (5) shows `pipefail` survives dropping `-e`, so a masked pipeline
  failure is still caught.

`die()` is one function: it prints the stage, the message and the command
that inspects the state left behind, then `exit "$1"`.

```sh
set -uo pipefail
die() { printf 'land: %s\n  inspect: %s\n' "$2" "$3" >&2; exit "$1"; }
```

**Every stage boundary is an explicit `|| die <code>`.** §2.8's observation
that *"`land` must not tolerate anything"* is preserved — it is enforced by
`die`, not by `-e`, and the difference is that `die` runs **after** the rc
has been captured and classified rather than instead of it.

| code | meaning |
|---|---|
| 0 | landed and pushed (or `--dry-run` completed) |
| 2 | **precondition** refusal (`PRE*`) — nothing was touched |
| 3 | **conflict** refusal (`PRV*`, `RES*`) — merge aborted, tree restored |
| 4 | **landing check** refusal (`CHK*`) — merge aborted, tree restored |
| 5 | **suite** refusal (`SUI*`) — **the merge commit stays local**. Three distinguishable causes, named in the message: a test failure (rc 1), a **timeout** (rc 124), a **collection error** (rc 2 — the allowlist cannot adjudicate it, §4.6) |
| 6 | **sanitize** refusal (`SAN*`) — the merge commit stays local |
| 7 | **push** failure (`PSH*`) — the merge commit stays local |

Codes 2–4 restore the tree with `git merge --abort`; codes 5–7 deliberately
do not, because the commit is correct work and re-running the merge would
discard a resolver's output. **Codes 5–7 are exactly the states `--continue`
resumes from** (§4.10a). Every one of 2–7 prints the single command that
inspects the state it left.

`EXC1` is the criterion: every stage's refusal exits with **its own** code,
and a test drives each. `M53` is the mutation that restores `-e` and shows
every code collapsing to 1.

### 4.10a `--continue` — the resume path *(new r3; the gate's second flag, RULED)*

**The hole.** Codes 5–7 preserve the merge commit *precisely so a resolver's
output is not discarded* — and then the only recovery the runner printed was
a hard rewind, which discards it. Worse, a naive re-run in that state
re-merges and re-anchors: `ANCHOR` would be set to the **merge commit
itself**, which is the exact value `U-armor`'s own gate B-1 rejected.

**The landing-state file.** At `merge --no-commit` time the runner writes a
state file — **never in the tree**, under the repo's cache dir, following
`gitops.py`'s established convention
(`${XDG_CACHE_HOME:-~/.cache}/self-learn/`, measured at `gitops.py:489-504`):

```
${XDG_CACHE_HOME:-~/.cache}/self-learn/landing-<branch>.state
    branch, base sha (the fetched origin/master), the resolver mapping,
    the verdict string, the MERGE SHA and its PARENT SHAS (written the moment
    `git commit` creates the merge), and -- on refusal -- the failing STEP
    and its exit code
```

**`--continue` re-runs from the failing step**, never re-merging and never
re-anchoring. It is accepted **iff** all of:

1. `HEAD` is a **merge commit** (`git rev-parse HEAD^2` resolves);
2. `HEAD` is **not** on `origin/master` (`git merge-base --is-ancestor HEAD origin/master` is false);
3. the state file exists, its branch and base sha match the current state, and it records a refusal at **step ≥ commit** (codes 5, 6 or 7);
4. **`git rev-parse HEAD` equals the merge sha the state file recorded, and
   `HEAD`'s parent list is unchanged** *(gate M-13)*.

**Condition 4 is what makes the other three sound.** Measured in a fixture
from a code-5 refusal at merge `334e4c0`, conditions (1)-(3) alone:

```
                                 (1)   (2)   (3)   verdict under r3
original merge   HEAD=334e4c0    PASS  PASS  PASS  --continue ACCEPTED
amended merge    HEAD=bc05772    PASS  PASS  PASS  --continue ACCEPTED   <- wrong
second merge     HEAD=59ae2c2    PASS  PASS  PASS  --continue ACCEPTED   <- wrong
```

In the third row `--continue` would resume to suites → sanitize → **push** on
a HEAD carrying an extra merge whose branch was never named to `land` and for
which `--remeasure` never ran — so `ANCHOR != M^1` for the new latest
first-parent merge and `U-armor`'s `ARM5` leg (b) is red on the *next*
landing. **That is the value `U-armor`'s own gate B-1 rejected, arriving
through the door `--continue` was opened to close.** `CNT2` asserted only
that `HEAD` was unchanged *by* the resume — true in all three rows — never
that it matched what the refusal recorded.

A mismatch refuses naming `--continue impossible: HEAD is not the merge this
refusal recorded`, and points at the state file and the recorded sha. Binding
the sha also closes the stale-state-file case, since the file is keyed by
branch name alone.

Any of the four failing ⇒ refuse, printing which one. On acceptance the runner
resumes at the recorded step — suites, sanitize, or push — and runs forward
from there.

**A bare re-run in that state REFUSES**, naming `--continue`. That is the
half that makes this safe: without it, the natural thing to type after a red
suite is `land --branch … --verdict …` again, which would re-merge on top of
a merge. `CNT1` pins the refusal, `CNT2` pins the resume, `M62`/`M63` are
the mutations.

### 4.11 The two worlds — pre- and post-`U-armor`

The runner **detects** which world it is in rather than being told — and
**the detection runs AFTER the merge is staged**, over the merged tree, not
before it *(gate M-6)*:

```sh
# post-merge, post-resolver, post-`git add` -- the tree that will be committed.
# BOTH reads are $ROOT-relative (N-19): under --dry-run $ROOT is $TMP, so the
# detection sees the MERGED tree, not the main checkout.
HAS_ARMOR=$(test -f "$ROOT/plugins/self-learn/cli/tests/test_armor.py" && echo 1 || echo 0)
HAS_SHAS=$(grep -cE '^\s+"plugins/[^"]+": "[0-9a-f]{64}"' \
             "$ROOT/plugins/self-learn/cli/tests/test_worker_contract.py" 2>/dev/null || true)
case "$HAS_ARMOR:$(( HAS_SHAS > 0 ))" in
  1:0) ARMOR=remeasure ;;
  0:1) ARMOR=armor_shas ;;
  1:1) die 4 "BOTH armor mechanisms present -- ambiguous" ;;
  0:0) die 4 "NEITHER armor mechanism present -- refusing to land unguarded" ;;
esac
[ "$ARMOR" != "armor_shas" ] || [ "$HAS_SHAS" -ge 1 ] || die 4 "0 pins checked"
```

**Why the timing and the exactly-one assertion are load-bearing, measured.**
Per §9.0 the next landing this runner performs is `U-armor`'s **build**,
which both adds `test_armor.py` and — by its own `DEL1`, which requires
every retired symbol to be *gone from the tree* — **removes `_ARMOR_SHAS`**.
Under r2's pre-merge detection: `ARMOR=armor_shas` is chosen from the
*pre-merge* tree; after the merge `_ARMOR_SHAS` no longer exists;
`CHK2`'s regex finds **0** pins and prints `pins checked: 0; mismatches:
[]` — **a pass** — while `--remeasure` never runs and no anchor is set.

That is §0's own rule (*"Absence is never asserted by a bare zero"*) broken
inside a criterion, on the exact landing this unit is being built for. The
`N >= 1` floor is the fix, and `grep -c`'s zero-count rc is why it is
written `|| true` and tested as a **value** — incident 3's mechanism for a
third time.

- `WLD1` **pre-`U-armor`** (today): the `_ARMOR_SHAS` check (`CHK2`, 7
  pins) runs inside the merge, before `git commit`. This is exactly
  incident 2's missing step.
- `WLD2` **post-`U-armor`**: `python3 plugins/self-learn/cli/tests/test_armor.py
  --remeasure --anchor "$(git rev-parse --short=7 HEAD)"` runs at the same
  point, `git add`s the module, and the re-anchor **rides inside the merge
  commit** — `U-armor` §4.2's chain, verbatim. A non-zero `--remeasure`
  refuses (its check-then-write contract guarantees the file is unchanged,
  so `git merge --abort` is safe).
- Both criteria are driven in the fixture repo by *creating* or *omitting*
  `test_armor.py`, so the detection itself is tested rather than assumed.
  `M17`/`M18`.

---

## 5. Criteria

`[A]` = must hold for this unit to land. `[B]` = should hold; a gate may
accept a recorded deviation.

### 5.1 PRE — preconditions

| id | | statement | test | mutation ⇒ red |
|---|---|---|---|---|
| **PRE1** | [A] | Run from a linked worktree ⇒ refuse, exit **2**, naming the git-dir it saw. The predicate compares `--path-format=absolute --git-dir` with `--path-format=absolute --git-common-dir` *(N-1)* | `test_land_refuses_outside_main_checkout` — four legs, **MEASURED at `99d310e`**: main-checkout root ⇒ equal; main checkout from `plugins/` ⇒ **equal** (r2's `= .git` form and a naive common-dir compare both say *not equal* here, so this leg is the discriminator); `u-land-spec` worktree ⇒ not equal; a `--detach` worktree ⇒ not equal | `M1` (drop the check), `M68` (r2's `= ".git"` form ⇒ the subdir leg reddens) |
| **PRE2** | [A] | `HEAD` not `master` (a branch, or detached) ⇒ refuse, exit 2 | `test_land_refuses_off_master` — two legs (branch, detached); control: on `master` it passes | `M2` |
| **PRE3** | [A] | A dirty main tree ⇒ refuse, exit 2, printing the porcelain line count | `test_land_refuses_dirty_master`; control: clean tree ⇒ 0 lines and it proceeds | `M3` |
| **PRE4** | [A] | The branch's registered worktree is dirty ⇒ refuse, exit 2, naming the worktree path and the count | `test_land_refuses_dirty_branch_worktree` — the §2.9 shape (two live instances exist on master today) | `M4` |
| **PRE5** | [A] | The branch is missing, is `master`, or shares no merge-base ⇒ refuse, exit 2 (three legs, three distinct messages) | `test_land_refuses_bad_branch` | `M5` |
| **PRE6** | [A] | `git ls-remote --exit-code origin HEAD` non-zero ⇒ refuse, exit 2, **before** any merge; rc captured **unpiped** | `test_land_refuses_unreachable_origin` — fixture repo whose `origin` points at a deleted path | `M6` |
| **PRE7** | [A] | Every precondition refusal leaves `git rev-parse HEAD` and `git status --porcelain` **byte-identical** to their pre-run values | asserted as a second leg on PRE1-PRE8 | `M7` |
| **PRE8** | [A] | `git fetch origin master` runs **before any scope is computed**, rc unpiped; a failed fetch refuses (exit 2). If the fetch **moves** `origin/master`, refuse — a landing is built on a base the operator saw. Three legs assert `SAN3`'s range, §4.6a's lane classification and `PSH2`'s `old` are each read from the **fetched** ref *(gate M-8)*. **Absence control**: `git fetch` appeared **0** times in r2 (`origin/master`, **12**) | `test_land_fetches_before_scoping` — a fixture whose bare `origin` gains a commit between runs; the mutation makes all three scopes stale | `M59` |

### 5.2 PRV / RES — preview and resolution

| id | | statement | test | mutation ⇒ red |
|---|---|---|---|---|
| **PRV1** | [A] | Clean preview + a named `--resolver` ⇒ refuse, exit 3 | `test_land_refuses_resolver_without_conflict` | `M8` |
| **PRV2** | [A] | Conflicted preview with **any** unmapped path ⇒ refuse, exit 3, printing the **full** conflict list from `--name-only` | `test_land_refuses_conflict_without_resolver`; control: mapping every path proceeds | `M9` |
| **PRV3** | [A] | The merge is invoked with `-c merge.conflictStyle=diff3` **on the runner's own command line**, so base markers never depend on the operator's dotfiles; and a conflicted file with **no** `^\|\|\|\|\|\|\|` line refuses (exit 3) rather than being parsed *(ruling F-1)* | `test_land_requires_diff3_base`, **three legs**: (a) the full fixture landing under `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null` still produces base markers and lands — **the discriminating leg**; (b) the same run with the runner's `-c` removed produces **0** base markers and refuses; (c) the fixture's repo-local `merge.conflictStyle` is asserted **unset** first, the confound control §2.4 was caught by | `M10` |
| **PRV4** | [A] | A conflict refusal leaves master's tree restored (`git merge --abort` ran; porcelain 0, `HEAD` unmoved) | second leg on PRV1-PRV3 | `M11` |
| **RES1** | [A] | `keep-both` resolves an empty-base additive hunk to `ours + theirs`, and **refuses** on a non-empty base or an overlapping line | `test_resolver_keep_both` — synthetic conflict via I-7, four legs | `M12` |
| **RES2** | [A] | `per-key` picks the side differing from base per key, and **refuses** on: a both-changed key with no re-derive (naming the key); differing key sets; **a duplicate key on any side**; **a line with no `:`** *(gate M-7)* | `test_resolver_per_key` — five legs. The duplicate-key leg is the **executed** case: `base ['a: 1','a: 2','b: 9']` / `ours [… 'b: 10']` / `theirs [… 'b: 9']` resolves to `['a: 2','a: 2','b: 10']` under the r2 rule — `'a: 1'` silently lost, no refusal | `M13`, `M57`, `M58` |
| **RES3** | [A] | `numeric-rows` unions and sorts by number, refusing on a duplicate or a non-monotonic result | `test_resolver_numeric_rows` — the `FW-` shape from §2.3, **with the fixture's two sides REQUIRED to be out of numeric order** *(N-5: if `ours + theirs` is already ascending, `M14` stays green and the test proves nothing; I could not establish from `fe5a012` which side contributed which rows, so the requirement is placed on the fixture rather than claimed of history)* | `M14` |
| **RES4** | [A] | An unknown resolver name refuses (exit 3) listing the registry's keys; the registry's keys and the runner's `--help` text are asserted **equal**. **Second leg** *(ruling Q-4)*: an **unmapped** conflict refuses printing, per block, the resolver names whose preconditions that block satisfies — and the refusal still exits 3, i.e. the suggestion never becomes a default | `test_resolver_registry_is_the_help_text` + `test_unmapped_conflict_suggests_resolvers` (empty-base block ⇒ suggests `keep-both`; `key: value` block ⇒ suggests `per-key`; a block matching none ⇒ suggests nothing and still refuses) | `M15`, `M50` |
| **RES5** | [A] | A `per-key` re-derive writes the sha of the **merged bytes** and a justification carrying a `20\d\d-\d\d-\d\d` date and naming both sides; a missing or undated justification refuses | `test_resolver_rederive_requires_dated_justification` — 3 legs. **This is incident 2's shape**, resolved correctly | `M16` |
| **RES6** | [A] | Every resolver's test builds its conflict by running a **real `git merge`** in an I-7 fixture, never by hand-written marker text | an AST test over `test_landing_resolvers.py`: every test function's body reaches a `git merge` call; **positive control**: a hand-written-marker test added to the file makes it red | `M27` |
| **RES7** | **[A]** | `count-line` resolves `assert len(X) == N` as `base + both deltas`, refusing on a multi-line side, a negative result, **or a `NAME` that differs across the three sides** *(**ruling Q-1** `[B]`→`[A]`; the NAME leg is N-4 — the registry signature is `(ours, base, theirs)` with no name argument, so `assert len(A) == 3` vs `assert len(B) == 5` would merge silently)* | `test_resolver_count_line` — the two measured `resolve-fw117.py` blocks as fixtures, plus three refusal legs | `M28`, `M67` |

### 5.3 CHK — the landing checks, inside the merge

| id | | statement | test | mutation ⇒ red |
|---|---|---|---|---|
| **CHK1** | [A] | Conflict markers anywhere in the **merge-touched set** ⇒ refuse, exit 4. The set is derived from the diff, not a hardcoded doc list | `test_land_refuses_conflict_markers` — the marker is planted in a file *outside* `landing-checks.py`'s hardcoded three, which is the case today's script cannot see | `M19` |
| **CHK2** | [A] | Every armor pin is compared to live bytes **before** `git commit`; a mismatch refuses (exit 4) naming path, expected and actual. Prints `pins checked: N` — today **7** — and **refuses when `N < 1`** *(gate M-6: absence must not read as clean)*. The count is captured `\|\| true` and tested as a **value** | `test_land_refuses_pin_mismatch`; **positive control**: an unmodified fixture reports `pins checked: 7; mismatches: []`. **Second leg**: a fixture with `_ARMOR_SHAS` deleted and no `test_armor.py` ⇒ refuse, not `pins checked: 0`. **This is incident 2** | `M21`, `M56` |
| **CHK3** | [A] | `S-`/`FW-` row order is monotonic and duplicate-free **per contiguous table run**; a violation refuses (exit 4). **Control, MEASURED on real history**: `git show 37f48c4:…/14-forward-work-map.md \| grep -c '^\| FW-130 '` → **2** (the duplicate left by the U-corrob/U-cachelit keep-both merge), and the same command at its child `6038eee` → **1**. So the criterion is red at `37f48c4` and green at `6038eee` — a genuine red/green pair, not a synthetic one | `test_land_refuses_row_disorder` — parameterised over those two real commits | `M22` |
| **CHK4** | [A] | Landing-state prose (`landing-checks.py`'s pattern set) refuses, with the quoted-pattern exemption preserved. Two legs: a live hit refuses; a spec's own **quoted** pattern table does not | `test_land_refuses_landing_state_prose` | `M23` |
| **CHK5** | [A] | The personal-literals gate over `plugins/` refuses on a hit, **by invoking `U-scrub`'s shipped `test_personal_literals.py`** — `land` contains no second copy of the pattern set. Two legs: a seeded literal refuses (exit 4) **before** the commit; and a grep over `land` + the `landing` package finds **no** personal-literal pattern of its own. **Absence control**: 0 hits today, and the same scan tree-wide reports **14** (§2.5) | `test_land_personal_literals_gate` | `M25` |
| **CHK6** | [A] | An empty, newline-bearing, or over-long `--verdict` refuses (exit 4); a valid one appears **verbatim** in the merge commit subject. **The budget is 200 characters** *(N-6 — r2 named no number; measured: the repo's last 40 first-parent subjects top out at **158**, so 200 clears live practice without being unbounded)* | `test_land_verdict_shape` — 4 legs (empty, newline, 201 chars, and a 158-char control that must PASS); the last reads `git log -1 --format=%s` | `M26` |
| **CHK7** | [A] | A `CHK*` refusal leaves master restored — `HEAD` unmoved, porcelain 0, **no merge commit exists** | second leg on CHK1-CHK6 | `M29` |
| **CHK8** | [A] | **No test process runs between `--remeasure` (or the `_ARMOR_SHAS` check) and `git commit`** *(gate M-5)*. The chain is exactly `U-armor` §4.2's: resolve → `git add` → checks → remeasure → `git add` → commit | `test_no_test_runs_before_the_merge_commit` — parse `land`, collect every **process invocation** whose argv names a test runner (`pytest`, `python3 -m …test…`, `scripts/suite`) and assert **none** lies between the remeasure call and the `git commit` call. **Exclusions, stated** *(N-13)*: a `git add` whose *path argument* contains `test` is not an invocation (§4.5's own `git add …/test_armor.py` would otherwise match), and the ordering is resolved over the **call graph**, not file position, so factoring the chain into a function cannot hide a call. **The reason, in the test's own words**: at that point the merge commit does not exist, so `U-armor`'s `ARM5` leg (b) (`ANCHOR == M^1`, `M` = the latest first-parent merge) compares against the **previous** merge and is red on every correct landing | `M55` |

### 5.4 SUI / SAN / PSH / DRY / WLD / EXC / UN

| id | | statement | test | mutation ⇒ red |
|---|---|---|---|---|
| **SUI1** | [A] | A red suite refuses (exit 5), the merge commit **stays local**, and the message names the log path and the undo command | `test_land_refuses_red_suite` — an injected always-failing test file in the fixture repo | `M30` |
| **SUI2** | [A] | A `timeout` kill (rc 124) refuses with a message saying *timeout*, distinct from a test failure | `test_land_refuses_suite_timeout` — a fixture test that sleeps past a 2s bound | `M31` |
| **SUI3** | [A] | A red run is tolerated **iff** the failing node ids are a subset of `landing/known_failures.txt`. Two legs: the allowlisted failure alone ⇒ proceed; allowlisted **plus** one more ⇒ refuse | `test_land_known_failure_allowlist` | `M32` |
| **SUI4** | [A] | Every id in `known_failures.txt` collects (`pytest --collect-only <id>` rc 0). Control: adding a bogus id makes it red | `test_known_failures_all_resolve` | `M33` |
| **SUI5** | [A] | Each suite's rc is captured **unpiped by redirect** (`> log 2>&1` then `rc=$?`), written to its own `.rc` file, and adjudicated by a **separate explicit statement** (`[ "$rc" = "0" ] \|\| die 5 …`) — never by `set -e` *(rewritten r3, gate B-1)*. **`SUI5` and `EXC1` both hold under this form and cannot under r2's.** Three legs: (a) the `.rc` file **exists and holds the real rc** after a red suite — MEASURED: under `set -euo pipefail` it is **never written**; (b) the refusal exits **5**, not bash's 1; (c) no pipeline appears on a line whose `$?` is then read | `test_land_rc_capture_form` — leg (a)'s positive control is the `-e` form, which produces no file at all | `M34`, `M53` |
| **SUI6** | [A] | **The docs-only detector is an ALLOWLIST** *(gate M-4)*: the docs lane is taken **iff every changed path is under `docs/`**; any other path ⇒ full suites. The count is captured `\|\| true` and tested as a value — **zero IS the docs lane**. The landing checks and the sanitize gate are **never** narrowed | `test_land_docs_only_lane`, **seven** legs: (a) docs-only ⇒ docs lane; (b) docs + a `.py` ⇒ full; (c) docs + `ui/static/app.js` ⇒ full; (d) docs + `cli/uv.lock` ⇒ full; (e) docs + `cli/pyproject.toml` ⇒ full; (f) docs + `cli/tests/fixtures/golden/…` ⇒ full; (g) landing checks and sanitize ran in **both** lanes; **(h)** `git mv <a src module> docs/…` ⇒ **full** lane *(gate M-12 — measured: without `--no-renames` this reports only the new `docs/` path and takes the docs lane while a `src` module is deleted)*; **(i)** control, a rename **out** of `docs/` ⇒ full lane even without the flag. Legs (c)-(f) are drawn from the **81** tracked files r2's denylist missed | `M47`, `M48`, `M71` |
| **SUI7** | [A] | **The lane's test set is a checked-in file, and the walk ships as code** *(gate M-1/M-2)*. Six legs: (a) the set equals the union of direct-hit and part-constant modules under §4.6a's quoted walk — **8** of 144 today; (b) **the strict `src/` count is 0 and must STAY 0** — a detector, not a coverage map: any `src/` module gaining a real doc-path constant forces the full lane; (c) the walk's three columns are reported together (naive **43**, docstring-inclusive **39**, strict **8**) so a docstring-inclusive count can never again be presented as strict; (d) `test_reader_contract.py` — which holds `'docs'` and `'specs'` as **separate** constants — is in the set, pinning the part-built route; **(e)** a **synthetic** part-built module that is **not** a direct hit is picked up by the union *(gate r2: today the part-built set is a subset of the direct set, so a dropped union step would be invisible — this leg is the only thing that can see it)*; **(f)** the walk is run **AFTER the §6.1 helpers exist at their shipped path** and still reads **144 / 43 / 39 / strict 8** *(gate M-23 — legs (a) and (c) are otherwise red on a correct build the moment the instruments are installed)* | `test_doc_reading_set` — leg (b)'s positive control: adding a real doc-path constant to any `src/` module flips the lane to full. Leg (f)'s control is the **measured** pair: helpers under `scripts/measured/` ⇒ 144/43/39/8; under `tests/measured/` ⇒ 149/44/40/9 | `M49`, `M85` |
| **SUI8** | [A] | **The UI suite runs with cwd = `plugins/self-learn/ui`, and the run collected only tracked files under `ui/tests`** *(gate B-2, M-19, N-17)*. Five legs: (a) the invocation's cwd is asserted from the shipped script; (b) **the stable predicates** — from the root `rc == 2` and ≥1 collected id under `cli/tests`; from the UI dir `rc == 0` and **0** ids outside `ui/tests`. **Counts are deliberately not asserted** (§4.6's OBSERVED table: 331/3327 on the production root vs 32/2668 in a fresh worktree, differing only by git-excluded `misc/`); (c) **rc 2 is adjudicated as a collection error**, never as "ui suite red", never handed to the allowlist; (d) the absence of a root-level pytest config is asserted, since that is the mechanism; (e) **every collected node id maps to a file in `git ls-files`** — a prefix check alone passes with an untracked scratch test *inside* `ui/tests/` (measured: 1271 collected, 0 outside the prefix) | `test_ui_suite_collection_root` | `M69`, `M70`, `M79` |
| **SAN1** | [A] | The pattern set equals `CLAUDE.local.md`'s, and the home prefix is derived from `$HOME` at runtime — the shipped script contains **no** absolute home path | `test_land_has_no_home_literal` + `test_sanitize_patterns_match_claude_local` | `M35` |
| **SAN2** | [A] | The count is captured `\|\| true` and tested as a **value**. Two legs: a clean diff ⇒ **proceeds to push** (incident 3's leg); a seeded hit ⇒ refuses | `test_land_sanitize_zero_hits_proceeds` + `test_land_refuses_sanitize_hit` | `M36` |
| **SAN3** | [A] | The scan is over **added lines** of `origin/master..HEAD`, produced by parsing **`git diff --unified=0 --no-renames`** `@@` headers into `(file, line-number, text)` *(gate M-14)*. Two added legs: **the `+++`/`---`/`@@` headers are excluded by construction** — a file *named* `secret_fixture.md` is **0** hits under the parser and **1** under r3's flat `grep '^+'` (measured); and the parser yields the exact `(file, line-number)` key `SAN4` requires, which r3's flat stream could not produce at all. **Seven more legs** *(gate M-18, M-21)*: the `++ b/evil-path` collision (the added line is scanned, `collide.md` is not lost, the hit lands on `collide.md:2`, never a fabricated `evil-path:1`); **the deleted-`-- ` variant**, where r5's two-line rule loses `f.md:1` and fabricates `evil-path:3` while the `diff --git` anchor gives `f.md:1` and `f.md:3` (`M76`'s ledger block runs it); and the four edge cases — no-newline-at-EOF, binary, mode-only, and a bare `+` empty line. Control, on real history: the range that shipped incident 1 reports **6**; a whole-file grep at that commit reports **16** and is red on a correct tree | `test_land_sanitize_scans_added_lines_only` | `M20`, `M73`, `M76`, `M82` |
| **SAN4** | [A] | A sanitize refusal (exit 6) prints the offending lines and does **not** push; `origin/master` is unmoved. **`--sanitize-ack` coverage is EXACT** *(gate M-9)*, keyed `(file, line-number, sha)` — the **new-file line number** from the `+` side of the `@@ -old +new @@` header, not a position within the diff *(N-12)* — split at the **first `=` after the 64-hex hash**. Seven legs: N hits + N matching acks ⇒ proceed, reasons in the commit body; **N hits + N−1 acks ⇒ REFUSE naming the unacked line** (r2's four legs all passed while every unacked hit was waved through — the fail-open one level up); an ack matching no hit ⇒ refuse; a stale hash ⇒ refuse; an empty reason ⇒ refuse; **two identical added lines in one file need two acks** (the line number is why); no boolean form exists (grep control: `--sanitize-ack` is present, `--no-sanitize` is not) | `test_land_sanitize_ack` (7 legs) + second leg on SAN2. **Eighth leg** *(N-18)*: on refusal the runner prints one paste-ready `--sanitize-ack '<file>:<line>:<sha>='` per hit | `M37`, `M52`, `M60` |
| **SAN5** | [A] | **The pattern set is a repo file of FRAGMENTS the runner joins** *(gate M-3)* — `landing/sanitize_fragments.txt`, never verbatim patterns. Four legs: (a) the runner holds no inline pattern literal; (b) **the assembled regex equals the set §4.7 quotes** — MEASURED `True`, the control that stops the fragments drifting; (c) **the fragment file scores 0 hits on its own added lines** — MEASURED, against **4** for r2's verbatim form; (d) **no tracked fixture file contains an assembled pattern** — the seeded-hit fixtures `SAN2`/`SAN4` need are **generated at test time** from the fragments, so the literal is never a tracked byte, with the generator's runtime output as the positive control. **There is no path exemption list** *(gate M-15 — r3's leg (d) was one; it is deleted, and this spec's own three hits go through `--sanitize-ack` instead, §3.6b)* | `test_sanitize_fragments_are_the_single_source` | `M51`, `M54`, `M74` |
| **PSH1** | [A] | On success, `git push origin master` runs once, rc unpiped | `test_land_happy_path` (fixture repo with a local bare `origin`) | `M38` |
| **PSH2** | [A] | `old..new` is printed from `origin/master` read **before and after** the push — a real pair, and an unmoved pair is reported as unmoved | `test_land_prints_ref_range` — two legs | `M39` |
| **PSH3** | [A] | `--force` and `--force-with-lease` appear **nowhere** in the shipped script. Absence control: the same grep finds `--no-ff`, which is present | `test_land_never_forces` | `M24` |
| **PSH4** | [A] | Prune runs only after a successful push, uses `git branch -d` never `-D`, and is **best-effort**: `git worktree remove` is attempted only when `git worktree list --porcelain` names one for the branch, and a prune failure exits **0** with a warning *(N-8 — r2 ran it unconditionally, so a branch with no registered worktree failed the run **after** the push had already happened)*. Three legs: push failure (exit 7) leaves branch and worktree intact; a branch **with no worktree** prunes cleanly and exits 0; `-D` is absent from the script | `test_land_prunes_only_after_push` | `M40` |
| **DRY1** | [A] | After `--dry-run`, `master`'s sha, porcelain output, and `git worktree list` line count are identical to pre-run | `test_land_dry_run_touches_nothing` | `M41` |
| **DRY2** | [A] | A `--dry-run` that would refuse produces the **same message and exit code** as the real run, **and every module and shelled-out test is invoked against `$TMP`** *(gate M-10)* | `test_land_dry_run_refusals_match` — parameterised over `PRE3`, `PRV2`, `CHK2`, **`CHK5`**, **`SAN3`** and — *(N-19)* — **`WLD1`/`WLD2`**, whose two path reads are `$ROOT`-relative so the dry run detects the world from `$TMP`'s merged tree. `CHK5` is the discriminating case: `test_personal_literals.py` resolves its root from its own on-disk location, so invoking the main checkout's copy scans the main checkout and reports clean while `$TMP` carries the literal. r2 excluded exactly that check | `M42`, `M61`, `M80` |
| **DRY3** | [A] | `--dry-run` never pushes and prints `DRY RUN — nothing pushed` | leg on DRY1 | `M43` |
| **WLD1** | [A] | With **no** `test_armor.py`: the `_ARMOR_SHAS` check runs inside the merge, before commit. **Detection runs POST-merge on the staged tree**, and asserts **exactly one** mechanism is present — refusing on both and on neither *(gate M-6)* | `test_land_pre_armor_world` — four legs, one per `(has_armor, has_shas)` cell. The `0:0` leg is the one that matters: **`U-armor`'s own build is the case**, since its `DEL1` requires `_ARMOR_SHAS` gone from the tree, so pre-merge detection would pick `armor_shas`, find **0** pins post-merge, and print a pass | `M17`, `M56` |
| **WLD2** | [A] | With `test_armor.py` present: `--remeasure --anchor $(git rev-parse --short=7 HEAD)` runs at the same point, is `git add`ed, and rides inside the merge commit (`git show --stat HEAD` lists it). A non-zero `--remeasure` refuses (exit 4) | `test_land_post_armor_world` — a stub `test_armor.py` in the fixture whose rc is controllable | `M18` |
| **EXC1** | [A] | The script begins **`set -uo pipefail`** — *not* `-e` — and each stage's refusal exits with **its own** §4.10 code via an explicit `\|\| die <code>` *(rewritten r3, gate B-1)*. Two legs: the exit code per refusal family (all six, end to end), and a grep asserting `set -e`/`set -euo` is **absent** while `set -uo pipefail` is present | `test_land_exit_codes` + `test_land_shell_contract` | `M44`, `M53` |
| **CNT1** | [A] | **A bare re-run in a post-commit refusal state REFUSES, naming `--continue`** *(the gate's second flag, RULED)*. The state is: `HEAD` is a merge commit, `HEAD` is not an ancestor of `origin/master`, and the landing-state file records a refusal at step ≥ commit. Refusing here is what stops a re-merge on top of a merge — and stops `ANCHOR` being set to the merge commit itself, the value `U-armor`'s own gate B-1 rejected | `test_land_refuses_bare_rerun_after_commit_refusal` — three legs, one per precondition, plus a control: with **no** state file a bare re-run proceeds normally | `M62` |
| **CNT2** | [A] | **`--continue` resumes from the failing step without re-merging or re-anchoring.** Three legs, one per resumable code: 5 (suites) ⇒ re-runs suites then sanitize then push; 6 (sanitize) ⇒ re-runs sanitize then push; 7 (push) ⇒ re-runs push only. Each asserts `git rev-parse HEAD` is **unchanged** by the resume and that no `git merge` and no `--remeasure` ran. **Fourth leg, the one that makes the rest sound** *(gate M-13)*: an **amended** merge and a **second merge on top** both refuse, naming `--continue impossible` — measured, both pass r3's three conditions and only the recorded-merge-sha comparison separates them. `--continue` with no state file, a mismatched branch, a mismatched base sha, a mismatched merge sha, or a refusal at step < commit ⇒ refuse. The state file lives under `${XDG_CACHE_HOME:-~/.cache}/self-learn/` — **never in the tree** (`gitops.py:489-504`'s convention), asserted by a leg that greps `git status --porcelain` clean after a refusal | `test_land_continue` — 7 legs; the fourth-precondition leg is `M72`'s target | `M63` |
| **UN1** | [A] | `scripts/suite` is **unchanged** (byte-identical to `6038eee`) | `test_suite_script_unchanged` | `M45` |
| **UN2** | [A] | `~/.self-learn` is never read or written: the shipped script and package contain no `SELF_LEARN_HOME` use and no `.self-learn` path | `test_land_never_touches_the_ledger` | `M46` |
| **UN3** | [B] | The CLI and UI suites' pass counts are unchanged by this unit except for the files it adds | recorded in the build report | — |
| **UN4** | [A] | **Every MEASURED row carries a runnable command in §6.1's ledger, the build re-runs all of them at build start, and refuses on any that does not reproduce** *(rewritten r5, gate M-17)*. Four legs. **(a)** Every `` ```measured M<n> `` block parses into exactly one `measure:` line and one `expect:` line. **(b) The floor is DERIVED, never a literal** *(gate M-22)*: `floor.py` compares the **set** of MEASURED mutation ids in §6 against the **set** of ledger block ids in §6.1 and reports `missing`/`extra`; both must be empty. **It also checks all three label counts against the §6 totals line** and reports `MATCH`/`MISMATCH`, and refuses any row carrying a bold label token outside its status cell *(N-26 — a substring scan of a row whose evidence names the other label miscounts it)*. **Positive control, run**: against r5's own text it reports `measured=14 blocks=11 missing=M76,M77,M78` — the defect gate r4 found, which a literal `11` could not see. **Blind-direction controls**: a parser matching nothing parses **0** and FAILS (under r4's `UN4` it ran zero commands and reported PASS); deleting one block FAILS. **(c)** Each command's stdout equals its `expect:` — all 11 written and run (§6.1). **(d) No MEASURED claim may depend on untracked state** *(gate M-19)*: the parser refuses a row whose command reads outside `git ls-files`, and such a claim is recorded as **OBSERVED** in prose instead — §4.6's collection counts and `M78` are the two. **(e) The whole ledger runs from a CLEAN detached checkout with no `misc/`, and every block must pass there** *(gate M-20 — leg (d) inspects the ledger's command string and cannot see a helper's *transitive* reads; only running it somewhere else can)*. Every helper resolves siblings via `"$(dirname "$0")"` and `need`s them, derives the spec path with `spec_path()` (a glob asserting **exactly one** `u-land-*.md`) rather than hardcoding it *(N-25)*, and the runner fails on a **non-zero helper rc** as well as a mismatched `expect:` | `test_measured_rows_reproduce` — leg (b)'s controls are the ones r4 lacked; leg (c)'s per-row control is `M49`'s **r3 text**, whose claim measures 0 against its stated 7; leg (e)'s control is the **first** clean-clone attempt, `pass=4 fail=9` (§6.1) | `M75`, `M77`, `M81`, `M83`, `M84` |

### 5.5 DOC

| id | | statement | test | mutation ⇒ red |
|---|---|---|---|---|
| **DOC1** | [A] | `03-decisions.md` carries `S-56` (§10.1), and the row's claims about the runner (its stages, its exit codes) match the shipped script | `test_s56_matches_the_runner` — parses the row's stage list and its exit-code set and compares both to the script's stage labels and `die` calls. **Positive control** *(N-2)*: the same parse against r2's seven-stage list reports the mismatch, so the test is not vacuous on an unchanged row | `M64` (add a stage to the script, not the row) |
| **DOC2** | [A] | `14-forward-work-map.md` carries `FW-142` and `FW-143` (§10.2), each in a monotonic run | `test_fw_rows_added_and_ordered`. **Positive control** *(N-2)*: the same check at `99d310e` (before the rows exist) reports them missing | `M65` (add the rows out of order) |
| **DOC3** | [A] | `15-orchestration-runbook.md` §1 names `scripts/land` as the landing step, replacing the prose chain | `test_runbook_names_the_runner` — greps the runbook for `scripts/land`; **positive control**: it greps for `scripts/suite`, which is already named | `M66` (name it only in a comment, not in §1) |

**Totals: 59 criteria — 58 `[A]` (the three `DOC` rows among them), 1 `[B]`
(`UN3` alone). Per group: PRE 8, PRV 4, RES 7, CHK 8, SUI 8, SAN 5, PSH 4,
DRY 3, WLD 2, EXC 1, CNT 2, UN 4, DOC 3.**

*(r4 adds **`SUI8`** (the UI collection root, gate B-2) and **`UN4`** (every
MEASURED row re-measured at build start, gate M-16 — the durable fix for a
class that has surfaced four times); and extends `SUI6` with the rename legs
(M-12), `SUI7` with the union leg, `SAN3` with the parser legs (M-14),
`SAN4`/`CNT2`/`CHK8` with one leg each (N-12, M-13, N-13), and rewrites
`SAN5` leg (d) from a path-exemption list to a generated-fixture requirement
(M-15).)*

*(r3 adds **`PRE8`** (fetch, gate M-8), **`CHK8`** (no test between remeasure
and commit, gate M-5), **`CNT1`**/**`CNT2`** (`--continue`, the gate's second
flag); and rewrites **`SUI5`** and **`EXC1`** (gate B-1), **`SUI6`**/**`SUI7`**
(gate M-1/M-2/M-4), **`SAN4`**/**`SAN5`** (gate M-9/M-3), **`CHK2`**/**`WLD1`**
(gate M-6), **`RES2`**/**`RES7`** (gate M-7, N-4), **`DRY2`** (gate M-10),
**`PRE1`**/**`RES3`**/**`CHK6`**/**`PSH4`** (nits N-1/N-5/N-6/N-8) and the
`DOC` rows' missing mutation column (N-2).)*

*(r2 adds **`SUI6`**/**`SUI7`** — ruling Q-2, the docs-only lane and its
completeness guard — and **`SAN5`** — ruling F-2, the canonical pattern
file; and rewrites `PRV3` (three legs, ruling F-1), `RES4` (the resolver
suggestion, Q-4), `SAN4` (the two-field ack, Q-6) and `RES7` (`[B]` →
`[A]`, Q-1).)*

---

## 6. Mutation plan

Every row names the **exact edit** and the test that must go RED.
`predicted` rows are the builder's obligation to verify and record.

| # | mutation | RED test | status |
|---|---|---|---|
| M1 | Delete the `git rev-parse --git-dir` check | `PRE1` | predicted |
| M2 | Accept any `HEAD` (drop the `symbolic-ref` compare) | `PRE2` | predicted |
| M3 | `git status --porcelain` result printed, not tested (the incident-1 shape) | `PRE3` | predicted |
| M4 | Skip the branch-worktree porcelain check | `PRE4` | predicted |
| M5 | Drop the `merge-base` check | `PRE5` | predicted |
| M6 | Read `ls-remote`'s status through a pipe (`ls-remote \| tail -1`) | `PRE6` **and** `SUI5` | predicted |
| M7 | On a precondition refusal, run `git merge --abort` unconditionally (mutating a tree nothing merged) | `PRE7` | predicted |
| M8 | Ignore a `--resolver` given with a clean preview | `PRV1` | predicted |
| M9 | Require a resolver for the **first** conflicted path only | `PRV2` | predicted |
| M10 | Drop `-c merge.conflictStyle=diff3` and the base-marker assertion | `PRV3` — measured: under `merge` style the base-marker count is **0**, control **1** (§2.4) | predicted |
| M11 | Skip `git merge --abort` on a conflict refusal | `PRV4` | predicted |
| M12 | `keep-both` returns `ours + theirs` without checking `base == []` | `RES1` | predicted |
| M13 | `per-key` takes `theirs` on a both-changed key instead of refusing | `RES2` | predicted |
| M14 | `numeric-rows` unions without sorting | `RES3` | predicted |
| M15 | Unknown resolver name falls back to `keep-both` | `RES4` | predicted |
| M16 | Re-derive writes the sha with no justification line | `RES5` | predicted |
| M17 | Always take the `--remeasure` path (no world detection) | `WLD1` | predicted |
| M18 | Run `--remeasure` **after** `git commit` — **incident 2, exactly** | `WLD2` (the module is not in `git show --stat HEAD`) **and** `CHK2` | predicted |
| M19 | `CHK1` scans `landing-checks.py`'s hardcoded three docs instead of the merge-touched set | `CHK1` | predicted |
| M20 | `SAN3` scans whole files instead of added lines | `SAN3` — measured: **16** at `8d716ff`, **14** on today's correct tree; the criterion reddens on a correct tree, which is the point | **MEASURED** (§2.5) |
| M21 | Pin check moved after `git commit` | `CHK2` | predicted |
| M22 | Row-order check compares the whole file rather than contiguous runs | `CHK3` — master's raw `FW-` sequence has 10 descending pairs, so this reddens on a correct tree | **MEASURED** (§2.0, §12 item 5) |
| M23 | Drop the quoted-pattern exemption | `CHK4` leg 2 | predicted |
| M24 | Add `--force-with-lease` to the push | `PSH3` | predicted |
| M25 | Replace the call to `test_personal_literals.py` with a private in-runner grep scoped to `docs/` | `CHK5` — **both** legs: the seeded literal is missed, and the second-copy leg reddens on the reintroduced pattern set | predicted |
| M26 | Accept an empty `--verdict` | `CHK6` | predicted |
| M27 | Replace one resolver test's fixture with hand-written marker text | `RES6` | predicted |
| M28 | `count-line` returns `ours` | `RES7` | predicted |
| M29 | On a `CHK*` refusal, commit anyway | `CHK7` | predicted |
| M30 | Treat a non-zero suite rc as a warning | `SUI1` | predicted |
| M31 | Map rc 124 onto the ordinary test-failure message | `SUI2` | predicted |
| M32 | Tolerate **any** red run when the allowlist is non-empty | `SUI3` leg 2 | predicted |
| M33 | Skip the collect check | `SUI4` | predicted |
| M34 | `rc=$(… \| tail -1)` for a suite | `SUI5` | predicted |
| M35 | Hardcode the home prefix as a literal | `SAN1` | predicted |
| M36 | `HITS=$(… \| grep -c …) && …` — **incident 3, exactly** | `SAN2` **leg 1** (the clean-diff leg; the seeded-hit leg stays green, which is why the criterion needs both) | predicted |
| M37 | Push before the sanitize gate | `SAN4` | predicted |
| M38 | Push twice / push `HEAD` instead of `master` | `PSH1` | predicted |
| M39 | Print a hardcoded `old..new` string | `PSH2` | predicted |
| M40 | Prune before the push; `-D` instead of `-d` | `PSH4` (two legs) | predicted |
| M41 | `--dry-run` merges into the main checkout | `DRY1` | predicted |
| M42 | `--dry-run` skips the landing checks | `DRY2` | predicted |
| M43 | `--dry-run` pushes | `DRY3` | predicted |
| M44 | Every refusal exits `1` | `EXC1` | predicted |
| M45 | Edit `scripts/suite` (add a flag) | `UN1` | predicted |
| M46 | Read `$SELF_LEARN_HOME` for a log path | `UN2` | predicted |
| M47 | Docs-only detector inverted — a `.py` in the diff takes the **docs** lane | `SUI6` leg (b) | predicted |
| M48 | Replace the allowlist with a `\.py$`-only test — i.e. take the docs lane unless a changed path ends `.py` *(rewritten r4, N-10: r3's row still described the r2 denylist the spec no longer has)* | `SUI6` leg (c) — `ui/static/app.js` goes to the docs lane, skipping the UI suite with `U-jsdom` live | predicted |
| M49 | Replace `SUI7` leg (b)'s **strict** `src/` count with a naive or docstring-inclusive one | `SUI7` leg (b) — the detector stops being a detector: under `docs/ (any)` the src columns read naive **8** / docstring-inclusive **6** / **strict 0**, so a non-strict count is non-zero on a correct tree and the leg can never fire *(re-aimed r4, gate M-16 — r3's row claimed "7 `src/` modules hold a doc path", a sentence §4.6a retracts in the same document; it was labelled MEASURED and was measured **false**)* | **MEASURED** (§4.6a) |
| M50 | Unmapped-conflict refusal prints the conflict list but not the candidate resolver names | `RES4` leg 2 | predicted |
| M51 | Inline the pattern set in `land` instead of reading `sanitize_fragments.txt` *(N-9: r3's row named the pre-rename file)* | `SAN5` legs (a) and (b) | predicted |
| M52 | Add a boolean `--no-sanitize`; or accept `--sanitize-ack` with an empty reason | `SAN4` — its no-boolean leg and its empty-reason leg respectively | predicted |

| M53 | Restore `set -euo pipefail` | `EXC1` (every code collapses to bash's 1) **and** `SUI5` leg (a) (the `.rc` file is never written) | **MEASURED** (§4.10) |
| M54 | Store the six patterns verbatim in `sanitize_fragments.txt` instead of as fragments | `SAN5` leg (c) — **4** self-hits, and `land` refuses its own landing | **MEASURED** (§4.7a) |
| M55 | Re-insert the "armor/five-file tests" step between `--remeasure` and `git commit` | `CHK8` — and, post-`U-armor`, `ARM5` leg (b) red on a correct landing | predicted |
| M56 | Run world detection **pre-merge** | `WLD1`'s `0:0` leg and `CHK2`'s `N < 1` floor — **`U-armor`'s own build is the case** | predicted |
| M57 | `per-key` accepts a duplicate key on one side | `RES2` — the executed case: `'a: 1'` silently lost | **MEASURED** (§4.4) |
| M58 | `per-key` accepts a line with no `:` | `RES2` — the line becomes its own key | predicted |
| M59 | Drop `PRE8`'s fetch | `PRE8` — all three scopes computed against a stale ref | predicted |
| M60 | Validate the acks given, then proceed (r2's behaviour) | `SAN4`'s N−1 leg — **and it stays green on all four of r2's legs**, which is why the leg had to be added | predicted |
| M61 | `--dry-run` invokes the **main checkout's** `test_personal_literals.py` | `DRY2`'s `CHK5` leg — scans the wrong tree and reports clean | predicted |
| M62 | Allow a bare re-run in a post-commit refusal state | `CNT1` — re-merges on top of a merge; `ANCHOR` becomes the merge commit | predicted |
| M63 | `--continue` re-runs the merge and the re-anchor | `CNT2` — `HEAD` changes across the resume | predicted |
| M64 | Add a stage to the runner without adding it to `S-56` | `DOC1` | predicted |
| M65 | Add `FW-142`/`FW-143` out of numeric order | `DOC2` | predicted |
| M66 | Name `scripts/land` only in a runbook comment, not §1 | `DOC3` | predicted |
| M67 | `count-line` ignores a `NAME` mismatch across the three sides | `RES7` | predicted |
| M68 | `PRE1` uses r2's `git rev-parse --git-dir` = `.git` form | `PRE1`'s `plugins/` subdir leg — falsely refuses from any subdirectory | **MEASURED** (§4.2) |

| M69 | Run the UI suite from the repo root (r3's form) | `SUI8` legs (b) and (c) — **measured, predicates only** *(N-20)*: from the root `rc == 2` and ≥1 collected id under `cli/tests`; from the UI dir `rc == 0` and 0 ids outside `ui/tests`. the counts behind them are not pinned — they live in §4.6's observed-only table | **MEASURED** (§6.1) |
| M70 | Adjudicate rc 2 as an ordinary red suite (hand it to the allowlist) | `SUI8` leg (c) — a collection error yields no failing node ids, so the allowlist subset test passes vacuously | predicted |
| M71 | Drop `--no-renames` from the lane detector | `SUI6` leg (h) — **measured**: a `src` module renamed into `docs/` reports one path, `NONDOC=0`, docs lane | **MEASURED** (§4.6a) |
| M72 | Drop `--continue`'s fourth precondition (the recorded merge sha) | `CNT2`'s fourth leg — **measured**: amended and second-merge HEADs both pass conditions (1)-(3) | **MEASURED** (§4.10a) |
| M73 | Scan the flat `git diff \| grep '^+'` stream instead of parsing `--unified=0` | `SAN3`'s two added legs — **measured**: a file named `secret_fixture.md` is 1 hit under the flat form, 0 under the parser; and the ack key cannot be produced at all | **MEASURED** (§4.7) |
| M74 | Reintroduce a path exemption list covering this spec | `SAN5` leg (d) — and the hole lands in `docs/specs/self-learn/drafts/`, incident 1's own directory | predicted |
| M75 | Skip the MEASURED-row re-measurement at build start | `UN4` — its positive control is `M49`'s r3 text, whose claim measures 0 against a stated 7 | predicted |

| M76 | Treat any `+++ b/` line as a file header (drop the `--- ` state gate) | `SAN3`'s collision leg — **measured**: `collide.md` vanishes, the `++ b/` line is never scanned, and the hit is attributed to `evil-path:1`, a file not in the tree | **MEASURED** (§4.7) |
| M77 | Drop `UN4`'s count floor | `UN4` leg (b) — **measured**: a parser matching nothing parses **0** and reports PASS without it | **MEASURED** (§6.1) |
| M78 | Let a MEASURED row pin `SUI8`'s collection **counts** rather than its predicates | `UN4` leg (d) and `SUI8` leg (b) — 331/3327 on the production root vs 32/2668 in a fresh worktree at the same commit; the build would refuse everywhere but one machine | **OBSERVED** *(relabelled r6, gate M-22: this row's own claim is the untracked-state comparison leg (d) says must be OBSERVED — it carried `MEASURED` while describing the rule forbidding it)* |
| M79 | `SUI8` leg (e) checks the node-id **prefix** only, not `git ls-files` membership | `SUI8` leg (e) — **measured**: an untracked scratch test inside `ui/tests/` collects 1271 with 0 outside the prefix | predicted |
| M80 | `WLD1`/`WLD2`'s two path reads are bare and relative, not `$ROOT`-relative | `DRY2`'s `WLD1`/`WLD2` legs — the dry run detects the world from the main checkout, not `$TMP` | predicted |

| M81 | A helper resolves a sibling through `$OLDPWD` or a `misc/` path instead of `"$(dirname "$0")"` | `UN4` leg (e) — the clean-clone run; **measured**: r5's `m73.sh` gave `flat=1 parsed=` at rc 0 on any tree without `misc/`, and the first clean-clone attempt scored `pass=4 fail=9` | **OBSERVED** (§6.1) |
| M82 | Restore r5's `+++`-after-`---` header rule | `SAN3`'s deleted-`-- ` leg — the measurement is `M76`'s ledger block (`r5=evil-path:3 r6=f.md:3`) | predicted |
| M83 | `floor.py` compares counts against a literal instead of the two **sets** | `UN4` leg (b) — the measurement is `M77`'s ledger block; against r5's text the set form reports `missing=M76,M77,M78` where a literal `11` reported PASS | predicted |
| M84 | Drop a helper's `need`/`set -uo pipefail`, letting a missing dependency yield an empty value | `UN4` leg (e) — **measured**: `M54` with `pat.txt` absent matched **all 7** lines at rc **0** instead of 4 | **OBSERVED** (§6.1) |

| M85 | Ship the §6.1 helpers under `cli/tests/measured/` instead of `cli/scripts/measured/` | `SUI7` legs (a), (c) and (f) — **measured**: the tests column goes 144/43/39/**8** → 149/44/40/**9**, because `walk.py`'s `CORPUS` regex is itself a strict hit; the criteria redden on a correct build | **OBSERVED** (§4.6a) |

**Totals: 85 mutations — 13 MEASURED (each with a §6.1 ledger block), 4 OBSERVED, 68 predicted.**

*(**The MEASURED label now means exactly one thing** *(gate M-22)*: the row
has a runnable ledger block, and `M77`'s floor asserts the two sets are
equal. A claim that is real but machine-dependent, or whose measurement
lives in another row's block, is **OBSERVED** — `M78`, `M81`, `M84`, and
§4.6's collection counts.)*

### 6.1 The MEASURED ledger — one runnable command per row

**`UN4` reads this section.** Each block's fence info-string is
`measured M<n>`; the parser takes one `measure:` line and one `expect:`
line, runs the command from the repo root, and compares the **last line**
of stdout. Helper scripts ship at **`plugins/self-learn/cli/scripts/measured/`** —
beside `scripts/suite` and `scripts/land`, **not** under `tests/`. They are
measurement instruments, not tests: they collect **0** pytest ids, and
`walk.py` staged under `tests/` becomes a strict hit on its own `CORPUS`
regex, taking §4.6a's tests column from **144 / 43 / 39 / 8** to
**149 / 44 / 40 / 9** and reddening `SUI7` on a correct build *(gate
M-23)*.

**Every helper is hardened** *(gate M-20, N-22)*: each sources `_lib.sh`,
which sets `set -uo pipefail` (**not** `-e` — §4.10's B-1 rule), resolves
`HERE="$(cd "$(dirname "$0")" && pwd)"`, and provides `need <file>` which
**exits 3 loudly** on a missing sibling. r5's `m73.sh` read
`$OLDPWD/misc/u-land-measured/parse.py` — git-excluded — and produced
`flat=1 parsed=` at **rc 0**: a passing-looking line with a silently missing
number, which the ledger caught only because `expect:` happened to be exact.
**The ledger runner now fails on a non-zero helper rc as well as on a
mismatched `expect:`.**

The run table below is the **clean-clone** run required by `UN4` leg (e).

````
```measured M20
measure: git grep -l "$HOME" 8d716ff -- . | wc -l
expect: 16
```
```measured M22
measure: grep -oE '^\| FW-[0-9]+ ' docs/specs/self-learn/14-forward-work-map.md | grep -oE '[0-9]+' | awk 'NR>1&&$1<=p{n++}{p=$1}END{print n+0}'
expect: 10
```
```measured M49
measure: python3 plugins/self-learn/cli/scripts/measured/walk.py src strict
expect: 0
```
```measured M53
measure: bash plugins/self-learn/cli/scripts/measured/m53.sh
expect: absent
```
```measured M54
measure: bash plugins/self-learn/cli/scripts/measured/m54.sh
expect: 4
```
```measured M57
measure: python3 plugins/self-learn/cli/scripts/measured/m57.py
expect: ['a: 2', 'a: 2', 'b: 10']
```
```measured M68
measure: cd plugins && [ "$(git rev-parse --git-dir)" = "$(git rev-parse --git-common-dir)" ] && echo equal || echo unequal
expect: unequal
```
```measured M69
measure: bash plugins/self-learn/cli/scripts/measured/m69.sh
expect: root_rc=2 root_cli_ids_ge1=yes ui_rc=0 ui_outside=0
```
```measured M71
measure: bash plugins/self-learn/cli/scripts/measured/m71.sh
expect: default=0 no-renames=1
```
```measured M72
measure: bash plugins/self-learn/cli/scripts/measured/m72.sh
expect: pass123=3 pass1234=1
```
```measured M73
measure: bash plugins/self-learn/cli/scripts/measured/m73.sh
expect: flat=1 parsed=0
```
```measured M76
measure: bash plugins/self-learn/cli/scripts/measured/m76.sh
expect: r5=evil-path:3 r6=f.md:3
```
```measured M77
measure: bash plugins/self-learn/cli/scripts/measured/m77.sh
expect: measured=13 blocks=13 missing=none extra=none
```
````

**The clean-clone run, 2026-08-28 at `9c7ebdd`** — a fresh detached
checkout with **no `misc/`**, helpers staged at the shipped
`cli/scripts/measured/`. This is `UN4` leg (e)'s control *(gate M-20)*,
re-run at r7 after the move *(gate M-23)*:

```
cwd=…/.claude/worktrees/u-land-clean   misc/ present? no
parsed rows: 13
  M20  OK rc=0  16                    M71  OK rc=0  default=0 no-renames=1
  M22  OK rc=0  10                    M72  OK rc=0  pass123=3 pass1234=1
  M49  OK rc=0  0                     M73  OK rc=0  flat=1 parsed=0
  M53  OK rc=0  absent                M76  OK rc=0  r5=evil-path:3 r6=f.md:3
  M54  OK rc=0  4                     M77  OK rc=0  measured=13 blocks=13 missing=none extra=none
  (deletion control)                  floor.py --delete-one -> blocks=12 missing=M20  FAILS, as it must
  M57  OK rc=0  ['a: 2', 'a: 2', 'b: 10']
  M68  OK rc=0  unequal
  M69  OK rc=0  root_rc=2 root_cli_ids_ge1=yes ui_rc=0 ui_outside=0
pass=13 fail=0
```

**What that run cost to get right, stated because it IS the finding.** The
first clean-clone attempt was **`pass=4 fail=9`**. Two distinct causes, both
the class this ledger exists to catch:

- **Nine blocks still pointed at `misc/u-land-measured/`** — the shipped
  paths had been written into §6.1's prose but not into the working ledger
  the run reads. Those failed **loudly** (rc 127 / rc 2).
- **`M77` failed on the r7 re-run too**, and loudly: `_lib.sh`'s first
  `ROOT` derivation climbed four directory levels from
  `scripts/measured/` and landed on `plugins/`, so `spec_path()`'s `find`
  had nothing to search. `need`/`spec_path` reported `FATAL` at **rc 1**
  rather than returning an empty string, which is the N-22 hardening doing
  its job. `ROOT` now comes from `git -C "$HERE" rev-parse --show-toplevel`
  with an assertion that `docs/specs/self-learn` exists beneath it —
  depth-independent, so a future move of the directory cannot repeat this.
- **`M54` failed OPEN.** Its command was an inline
  `grep -cEi "$(cat …/pat.txt)"`; with `pat.txt` missing the pattern was
  **empty**, so `grep -c ''` matched **all 7** printed lines and exited
  **0** — a wrong number at a passing rc, M-20's exact shape one row over.
  `M54` is now a helper with `need pat.txt` and an explicit empty-pattern
  guard.

**`M77` is the floor, and it is DERIVED** *(gate M-22)*. `floor.py` compares
the **set** of MEASURED mutation ids in §6 against the **set** of
` ```measured ` block ids in §6.1 and prints `missing`/`extra`. It finds the
spec by `spec_path()` — a glob over `docs/specs/self-learn/**/u-land-*.md`
asserting **exactly one** match, exiting 3 otherwise — rather than a
hardcoded path *(N-25)*.

**Its blind-direction control is the deletion form** *(N-24 — a
"against r5's text" control is not reproducible while this spec is
a draft; the commit-ref form applies from this commit onward)*:

```
$ bash …/m77.sh                          # the shipped row
measured=13 blocks=13 missing=none extra=none
$ python3 …/floor.py --delete-one "$(…)" # drop the first block
measured=13 blocks=12 missing=M20 extra=none      <- FAILS, as it must
```

**`floor.py`'s full output at r8** — the three label counts are now checked
against the §6 totals line, and a bold label token outside the status
column is refused *(N-26)*:

```
$ bash …/m77.sh
measured=13 blocks=13 missing=none extra=none
labels total=85 MEASURED=13 OBSERVED=4 predicted=68 unlabelled=0
totals-line MATCH stray-bold=none
```

**And the guard now exits from the SCRIPT, not the subshell** *(N-27)*.
`spec_path()`'s `exit 3` inside `$(spec_path)` ended only the command
substitution; the caller carried on with an empty value and rc 1 plus a
traceback. It now reads `SPEC=$(spec_path) || exit 3` with an empty-value
guard. Verified on all three arities:

```
0 matches  ->  rc 3   FATAL: expected exactly 1 u-land-*.md, found 0
2 matches  ->  rc 3   FATAL: expected exactly 1 u-land-*.md, found 2
1 match    ->  rc 0
```

A literal `11` could see neither direction. When this spec was at r5 the
same checker reported `measured=14 blocks=11 missing=M76,M77,M78` — the
defect gate r4 found — which is the historical record of why the derived
form exists.

**The count floor's controls, run:**

```
correct parser                     parsed=11   floor(11): PASS
broken parser (matches nothing)    parsed= 0   floor(11): FAIL   <- r4 reported PASS here
after deleting one block           parsed=10   floor(11): FAIL
```

**Note on `M36`.** The mutation is green on the seeded-hit leg and red only
on the clean-diff leg — which is the whole reason incident 3 escaped: the
broken form fails **when the gate passes**. A criterion with only a
"refuses on a hit" leg would not have caught it. This is stated because a
gate reading `SAN2` should check that both legs exist.

---

## 7. Scope

### 7.1 IN

- `plugins/self-learn/cli/scripts/land` and the `self_learn.landing`
  package (`conflicts.py`, `resolvers.py`, `checks.py`,
  `known_failures.txt`, `sanitize_fragments.txt`, `doc_reading_set.txt`).
- **Spec-only / docs-only landings** *(ruling Q-2)* — the §4.6a lane, its
  detector and its completeness guard.
- Three test modules (§4.1) including the fixture-repo harness.
- `S-56`; `FW-142`, `FW-143`; the `15-orchestration-runbook.md` §1
  amendment.
- Retiring `misc/landing-scripts-2026-08-28/` in favour of the shipped
  runner — the directory is git-excluded, so "retiring" means the runbook
  stops pointing at it. **`FW-143`** records that the four scripts stay on
  disk as the historical record until the runner has landed a unit.

### 7.2 OUT — each a real thing a builder might reach for

- **Automatic resolver selection.** §3.3: an automatic classifier picks
  wrong on 3 of 13 measured blocks.
- **A resolver for any shape not in §2.3.** Refuse and print the conflict
  list. New shapes arrive with a new resolver, a unit test and a review.
- **Reading or writing `~/.self-learn`.** `UN2`.
- **`--force` in any form.** `PSH3`. `CLAUDE.local.md` makes it a user
  decision, so the tool does not have the capability.
- **Pushing any branch but `master`.** `CLAUDE.local.md`: *"Never push
  someone else's branch or a detached HEAD."*
- **Deciding gate readiness.** §3.3 option E.
- **Changing `scripts/suite`.** `UN1`.
- **A CI integration.** The runner is operator-invoked; nothing schedules
  it.
- **Auto-adjudicating sanitize hits.** `SAN4` refuses and prints;
  `--sanitize-ack` is content-bound, not a skip flag.
- **Rewinding a landed merge.** Codes 5-7 leave the commit local and print
  the undo for a human to run; the tool never rewinds a branch itself.

### 7.3 Sizing — T2, and the measurement that says so

**T2 (full two-gate).** Three reasons, each measured:

1. **Size.** The shipped runner must reproduce the behaviour of **268
   lines** of ad-hoc python (§2.2) plus the preconditions, suite calls,
   sanitize and push that live only in an operator's shell history —
   against `scripts/suite`'s **55** lines, the T1-shaped comparator. The
   test surface (a fixture repo driving **seven** refusal families plus a
   happy path plus four resolvers) is larger than the runner.
2. **A decision row.** The unit owes `S-56` — it changes how every future
   unit lands, which is `S-10` territory ("behaviour never changes without
   a decision row").
3. **The blast radius is the push.** Every other unit's mistakes are
   local until a landing; this unit *is* the landing, and its failure mode
   is *"something wrong reached a public remote and can only be fixed
   forward"* — twice on 2026-08-28 (§2.1). A blind spec gate before the
   build and a blind code gate with mutation verification after it are
   proportionate to that.

---

## 8. Files this unit may touch

| path | why |
|---|---|
| `plugins/self-learn/cli/scripts/land` | **new** — the runner |
| `plugins/self-learn/cli/src/self_learn/landing/__init__.py` | **new** |
| `plugins/self-learn/cli/src/self_learn/landing/conflicts.py` | **new** — the one diff3 parser + driver |
| `plugins/self-learn/cli/src/self_learn/landing/resolvers.py` | **new** — the registry |
| `plugins/self-learn/cli/src/self_learn/landing/checks.py` | **new** — `landing-checks.py` promoted |
| `plugins/self-learn/cli/src/self_learn/landing/known_failures.txt` | **new** — `SUI3` |
| `plugins/self-learn/cli/src/self_learn/landing/sanitize_fragments.txt` | **new** — `SAN5`, the canonical pattern set as **fragments** (ruling F-2, gate M-3) |
| `plugins/self-learn/cli/src/self_learn/landing/doc_reading_set.txt` | **new** — `SUI6`/`SUI7`, the docs-only lane's **8** modules |
| `plugins/self-learn/cli/tests/test_landing_resolvers.py` | **new** |
| `plugins/self-learn/cli/tests/test_landing_checks.py` | **new** |
| `plugins/self-learn/cli/tests/test_land_runner.py` | **new** |
| `plugins/self-learn/cli/scripts/measured/` | **new** — the §6.1 ledger's helper scripts (`_lib.sh`, `walk.py`, `pat.txt`, `m53.sh`, `m54.sh`, `m57.py`, `m69.sh`, `m71.sh`, `m72.sh`, `m73.sh`, `m76.sh`, `m77.sh`, `parse.py`, `parse_r5.py`, `floor.py`), read by `UN4`. **Under `scripts/`, beside `suite` and `land` — NOT under `tests/`** *(gate M-23: they are measurement instruments, not tests — 0 collected ids — and `walk.py` staged under `tests/` counts itself, taking the walk from 144/43/39/**8** to 149/44/40/**9**)* |
| `docs/specs/self-learn/03-decisions.md` | `S-56` |
| `docs/specs/self-learn/14-forward-work-map.md` | `FW-142`, `FW-143` |
| `docs/specs/self-learn/15-orchestration-runbook.md` | §1 amendment |
| `docs/specs/self-learn/drafts/u-land-landing-runner-spec.md` | this file |

**Not touched:** `scripts/suite` (`UN1`), `test_worker_contract.py`,
`test_u_sdka.py`, `test_u_fake.py` (the armor files — `U-armor`'s
subject), anything under `plugins/self-learn/ui/src/`.

**A note on the armor pins.** Every new file this unit adds under
`plugins/self-learn/cli/tests/` is a candidate for `_ARMOR_SHAS`'s
exhaustiveness assertions. The builder's first step is to re-measure §2.6
against the master it actually lands on, because whether these three test
modules must be pinned is a property of the armor as it stands **then**,
not now. §12 item 3.

---

## 9. Parallel units

### 9.0 Landing order — **`U-armor` lands FIRST**

**Status at `9b9b1a1`: `U-armor`'s SPEC has landed (r7, SOUND at spec gate
r5, merge `9b9b1a1`); its BUILD has not.** `test_armor.py` is absent and
`_ARMOR_SHAS` still holds **7** pins, so the world this runner will first
run in is `WLD1`'s. That is measured, not assumed, and it is why `WLD1`
is `[A]` rather than a legacy path.

`U-armor`'s `--remeasure` is the step this runner must call inside the
merge. Ordering:

- **`U-armor` first**, because `--remeasure` is its deliverable. This
  runner calls it **only when present** (§4.11), with the `_ARMOR_SHAS`
  check as the pre-`U-armor` path.
- **`WLD1`/`WLD2` are the criteria that make the order not matter for
  correctness** — the runner detects which world it is in and both paths
  are tested. If `U-land` somehow lands first, `WLD1` is exercised in
  production and `WLD2` waits; nothing breaks and nothing is silently
  skipped.
- Neither unit may land the other's files. `U-armor` owns
  `test_armor.py`; `U-land` owns `scripts/land` and the `landing`
  package.

### 9.1 The interface `U-land` assumes from `U-armor`

Recorded, not re-specified (`U-armor` §4.2):

| assumption | consequence if it changes |
|---|---|
| the entry point is `python3 plugins/self-learn/cli/tests/test_armor.py --remeasure --anchor <short7>` | `WLD2`'s invocation string changes; one line |
| it is **check-then-write**: a refusal leaves the file byte-identical | `WLD2`'s `git merge --abort` on refusal becomes unsafe; the runner would need a restore |
| it exits non-zero on a no-op anchor | a second `land` run on an already-landed branch would be silently green |
| exemption entries are **never** written by `--remeasure` | the runner would have to adjudicate a reason string, which §3.3 option E rejects |

### 9.2 The shared-surface table

| unit | branch | overlaps `U-land`? | why |
|---|---|---|---|
| `U-armor` | *(spec landed at `9b9b1a1`; build pending)* | **yes, by interface only** (§9.1) — no shared file | `test_armor.py` is `U-armor`'s; `scripts/land` is `U-land`'s |
| `U-verbs` | `u-verbs` | no | `verbs.py`, `batch.py`, `cli.py`; owns `S-54` / `FW-133`-`138`, all already on master |
| `U-scrub` | *(landed `99d310e`)* | **adjacent, and now a dependency** — it owns `test_personal_literals.py`, which `CHK5` **calls**. `U-land` adds no pattern and changes no scrub code | code gate CLEAN r2, merged `99d310e` |
| `U-jsdom` | `u-jsdom` | no | UI-only |

**`U-land` is the only unit that touches `scripts/`**, and the only one
that adds a `landing` package. Its doc rows (`S-56`, `FW-142`/`143`) sit
above every reserved number (§2.0), so its own landing has no numeric
conflict with `U-armor`'s.

---

## 10. Docs owed at merge

### 10.1 `03-decisions.md` — one new row after `S-55`

> **`S-56` | Landing is a program in the repository, not a shell chain.**
> Every merge to `master` runs `plugins/self-learn/cli/scripts/land`:
> preconditions → `merge-tree` preview → `merge --no-ff --no-commit` →
> a **named** resolver (never an inferred one) → landing checks and the
> armor re-measure, **inside** the merge commit → CLI suite → UI suite →
> a sanitize scan of the outgoing diff's **added lines** → `push origin
> master` → prune. Each stage is fail-closed with its own exit code, and
> each refusal path has a test that has been observed to fire.
> *Rationale:* on 2026-08-28 three hand-typed chains shipped three
> defects — an unfolded spec with six absolute home paths on a public
> remote (`8d716ff`, fixed forward at `104f6db`; **still in history**), a
> stale armor pin re-derived after the merge commit (`801c746`), and a
> `grep -c` that exits 1 on a zero count and broke an `&&` chain
> *between the commit and the push*. All three are the same class: a
> check whose output is identical whether it passed or could not see its
> target. A program can be tested; a chain typed from memory cannot.
> *Corollaries:* (a) conflict resolvers are named by the operator and
> unit-tested on synthetic conflicts — the runner never infers one;
> (b) the gate verdict is an **argument**, never an inference — the
> runner asserts its shape, not its truth; (c) the runner has no
> `--force` capability at all; (d) `land` is operator tooling under
> `scripts/`, not a product surface under the CLI (§11 Q-5).

### 10.2 `14-forward-work-map.md` — two new rows

> **`FW-142` | The docs-only lane's test set cannot see a docs path built
> from PARTS.** *(Re-scoped again at r3 — gate M-1 measured r2's stated
> residual out of existence, and this is the one that survives, so the
> number is kept and no hole is left behind.)* §4.6a's walk finds a module
> that holds a real string constant matching `docs/`. Measured at
> `9c7ebdd`: **8** of 144 test modules, and the strict `src/` count is
> **0** — so the indirect-reader route r2 claimed (7 `src/` modules) **does
> not exist**; those seven carry their doc path in a module *docstring*, a
> citation rather than a read. What does exist is the part-built route:
> `test_reader_contract.py` holds `'docs'` and `'specs'` as **separate**
> constants and would match no `docs/` literal at all. `SUI7` covers it by
> unioning the part-constant modules into the set (measured: direct 8,
> part-built 2, **union 8** — today a subset, tomorrow maybe not), and
> `SUI7` leg (b) keeps the `src/` count pinned at 0 as a **detector**. The
> residual is what neither catches: a path assembled from fragments no
> single constant reveals (`"do" + "cs"`, an f-string, a `Path(*parts)` from
> a list). Revisit if a docs-only landing ever ships a defect the full
> suites would have caught; the fallback stays §12 item 10's — delete the
> lane, always run the full suites.

> **`FW-143` | `misc/landing-scripts-2026-08-28/` stays until the runner
> has landed a unit.** The four ad-hoc scripts (268 lines, git-excluded)
> are the only record of the pre-runner shape. Retire them once `land`
> has completed one real landing, and record which landing that was.

### 10.3 `15-orchestration-runbook.md` — the §1 amendment

§1's round lifecycle ends at *"code gate CLEAN ⇒ commit"* and then says
nothing about how the branch reaches `master`. One insertion after that
step:

> **Step 5 — land.** `plugins/self-learn/cli/scripts/land --branch <b>
> --verdict '<the gate's verdict line>'`. Run it in the **foreground**
> (a backgrounded run dies with the turn — `scripts/suite`'s own rule).
> It refuses rather than proceeding at every stage; each refusal prints
> the one command that inspects the state it left. Nothing about a
> landing is done by hand, and no landing chain is retyped.

`DOC3` is the criterion, with `scripts/suite` — already named in the
runbook — as its positive control.

---

## 11. Questions — all RULED

**§3.4 is the ruling table and carries the reasoning.** This section is the
index: what was asked, what was recommended, and what the orchestrator
decided. Two recommendations were **not** followed, and both are recorded
here rather than quietly rewritten.

| | question | recommended | **RULED** |
|---|---|---|---|
| **Q-1** | Three resolvers or four? | four; `count-line` `[B]` | **ACCEPTED, and strengthened** — `count-line` is **`[A]`**. §3.4 records the one number in the ruling's warrant this spec could not confirm |
| **Q-2** | Spec-only landings in scope? | **no, not in r1** | **OVERRULED — they are IN.** §3.4 says why the recommendation was wrong (it fused "commit the branch" with "land a docs-only diff"; only the first was ever the hazard) |
| **Q-3** | Re-anchor on docs-only merges? | yes, unconditionally | **ACCEPTED** |
| **Q-4** | May an agent invoke a resolver? | yes, named only | **ACCEPTED, and extended** — the refusal must also print the candidate resolver names |
| **Q-5** | `scripts/` or the CLI? | `scripts/land` | **ACCEPTED** |
| **Q-6** | Is a sanitize ack allowed? | yes, content-bound | **ACCEPTED, and tightened** — two fields (hash **and** adjudication text), never a boolean |
| **F-1** | The diff3 dependency | (finding) | **RULED**: the runner supplies `-c` itself and refuses without base markers; tested under a scrubbed config |
| **F-2** | Sanitize scoping | (finding) | **RULED**: added lines only, **and** the pattern set becomes a repo file the runner reads |

<details><summary>The original recommendations, kept for the record</summary>

| | question | recommendation |
|---|---|---|
| **Q-1** | **Three resolvers or four?** The brief names `keep-both`, `per-key`, `numeric-rows`; §2.3 measured a fourth recurring shape, `count-line` (2 of 13 blocks), and a `keep-both` variant (1 of 13). | **Ship four.** `count-line` is the arithmetic that keeps an additive union consistent with the assertion guarding it — without it, `keep-both` on a `DS1_ADDED` hunk produces a merge that imports cleanly and then reddens, and the operator writes the fourth resolver ad hoc anyway, which is the thing this unit exists to stop. `RES7` is `[B]` so a gate may defer it, but the recommendation is to build it. The keep-both **variant** stays unbuilt: an overlapping hunk is not additive, and refusing is the honest answer. |
| **Q-2** | **Does the runner handle spec-only landings?** `PRE4` refuses a dirty branch worktree, and a spec worktree is deliberately dirty until the gate closes (§2.9 measured two live). | **No, not in r1.** Recommend the orchestrator commits the spec, then runs `land`. A `--spec-only` mode that commits someone else's uncommitted work is precisely the shape that shipped incident 1. Recorded as `FW-142`. |
| **Q-3** | **Should the runner re-anchor on docs-only merges?** `U-armor`'s anchor advances inside every first-parent merge; a docs-only merge moves no protected file. | **Yes — unconditionally, and let `--remeasure` decide.** `U-armor` §4.2's leg (b) asserts `ANCHOR == M^1` for the **latest** merge, so a merge that skipped the re-anchor makes the *next* landing red for a reason unrelated to it. Uniformity is cheaper than a special case, and `--remeasure`'s empty-owed-set path is a no-op census plus the anchor line. |
| **Q-4** | **May an agent invoke a resolver non-interactively?** | **Yes, and that is the point** — but only with the resolver **named on the command line**. An agent may not pick one. The `RES4` refusal (unknown name ⇒ list the registry) and `PRV2` (every conflicted path must be mapped) together mean an agent that does not already know the merge's shape cannot proceed. The judgement moves to *choosing the name*, which is a reviewable argument in the transcript, not a hidden inference. |
| **Q-5** | **Where does `land` live — `scripts/` or the CLI?** It could be `self-learn land`. | **`scripts/land`, beside `suite`.** It is operator tooling for *this repository*, not a product surface: it hardcodes `master`, `origin`, this repo's doc conventions and this repo's armor. Putting it in the shipped CLI would ship repo-development machinery to every user. `S-56` corollary (d) says so. |
| **Q-6** | **Should a sanitize refusal be acknowledgeable at all (`--sanitize-ack`)?** `CLAUDE.local.md` permits verified pattern-only hits. | **Yes, but content-bound.** `--sanitize-ack <sha256-of-the-hit-lines>` acknowledges *those exact lines*; any change to the diff invalidates it. A boolean `--no-sanitize` would recreate incident 1 with one extra keystroke. If the orchestrator prefers no escape hatch at all, drop the flag and require the human to edit the diff — that is also defensible, and it is a values call the orchestrator should make rather than the spec. |

</details>

---

## 12. What could NOT be measured

1. **The runner's own line count.** Estimated ~250 for the runner plus
   resolvers and ~400 for tests, from the 268 lines it subsumes plus the
   preconditions and suite calls that exist only in shell history. **Not a
   measurement** — the build re-measures and the report records the real
   number.
2. **CLOSED at r4** *(gate r2 measured it; N-14)*. Suite wall-clock is
   **CLI 243 s, UI 230 s** on this machine, full lane **473 s** sequential.
   `SUITE_TIMEOUT` defaults to **600 s** — ~2.5× the slower suite, enough
   that ordinary variance cannot trip `SUI2` and tight enough that a hang is
   caught in ten minutes. The builder re-measures on the landing machine and
   records any change; the *basis* is no longer a guess.
3. **Whether this unit's three new test modules must join `_ARMOR_SHAS`.**
   That is a property of the armor **as it stands when this lands** —
   today's exhaustiveness assertion over the tests tree, or `U-armor`'s
   table. §8's note; the builder re-measures §2.6 first.
4. **`git merge-tree`'s behaviour on a rename/rename or add/add
   conflict.** Only content conflicts were exercised (I-7). The measured
   contract in §4.3 covers rc and stdout shape for content conflicts; the
   builder should extend the fixture to at least one add/add case before
   trusting `--name-only` to enumerate every conflicted path.
5. **Whether the `FW-` table's non-monotonicity is deliberate.** The raw
   sequence in `14-forward-work-map.md` has **10 descending pairs** —
   re-measured at `9b9b1a1` over **141** rows:
   `[(53,52), (52,49), (70,62), (67,57), (61,54), (56,50), (127,120),
   (132,128), (131,122), (141,30)]` — because the file holds several
   tables. `CHK3` is specified per contiguous run on that
   basis, but nobody has confirmed the table boundaries are intentional
   rather than accreted. If they are accreted, `CHK3` should eventually
   assert one global run — recorded here rather than assumed either way.
6. **Anything about `origin` beyond reachability.** `git ls-remote` was
   the only remote call; no push, no fetch, no branch listing. Whether
   `origin/master` can move under the runner between the sanitize scan
   and the push (a second machine pushing concurrently) is unmeasured —
   the push would be rejected non-fast-forward, exit 7, and the commit
   would stay local, which is the correct outcome, but it has not been
   exercised.
7. **Whether `--remeasure` and the runner agree on the anchor under a
   `--dry-run`.** `DRY1` merges in a detached throwaway worktree, where
   `git rev-parse --short=7 HEAD` is the *worktree's* HEAD. `U-armor`
   §4.2 defines the anchor as the pre-merge tip of `master`, which is the
   same commit in the dry-run worktree — but this was reasoned, not run.
   The builder must exercise `WLD2` under `--dry-run` explicitly.
8. **The ruling's "two of tonight's five landings" figure for
   `count-line`.** Not confirmable from the repository (§3.4). Tonight had
   **14** first-parent merges; **3** left a resolver script in `misc/`;
   `count-line` appears in **1** of those 3 (2 of its 6 blocks). The other
   11 landings left no script, so whether they merged cleanly or were
   hand-resolved is unrecoverable. The ruling is followed on §2.3's own
   argument, which does not depend on the count.
9. **`CLAUDE.local.md` should point at `sanitize_fragments.txt` instead of
   carrying the patterns as prose** (§4.7a). That edit is **owed but not
   this unit's to make** — the file is local-only, deliberately
   `.git/info/exclude`d, and this spec does not touch it. Flagged for the
   orchestrator; until it happens the repo file is canonical and the prose
   is a stale duplicate.
10. **CLOSED at r4 — KEEP** *(gate r2 adjudicated it by measurement; §3.6a,
   N-14)*. Docs lane **29 s / 354 tests**; full lane **473 s**; saving
   **444 s = 94 %**. Coverage given up: 354 of 3,836 non-skipped tests =
   **9.2 %**, and **the lane runs zero UI tests**. The open question that
   remains is narrower and is `FW-142`'s: whether the *set* is complete, not
   whether the lane earns its place. What has still never been run is a real
   docs-only landing end to end.
11. **Which side contributed which `FW-` rows at `fe5a012`.** `RES3`'s
   fixture requirement (`N-5`) is stated as a requirement *on the fixture*
   precisely because this could not be recovered: at `3b8e037` and at
   `fe5a012^2` the tail of the `FW-` sequence is identical, so the conflict
   block's two sides cannot be separated from the merge commit alone. The
   builder must construct an out-of-order fixture rather than reproduce
   history.
13. **Whether this spec should write the pattern words in fragment form to
   cut its own ack count.** Measured: **13** sanitize hits on r4's text,
   across six sections, every one the gate's own vocabulary quoted as
   evidence (§3.6b). Writing them as fragments would drop the count to near
   zero and make §4.7/§4.7a materially harder to read. Not decided here —
   it trades legibility against landing ceremony, and the ack mechanism
   handles either choice.
12. **Whether `--continue`'s state file can go stale in a way the four
   preconditions miss.** §4.10a checks branch, base sha and step. It does
   **not** detect an operator hand-editing the working tree between the
   refusal and the resume. Stated rather than guarded: the resume re-runs
   the suites and the sanitize gate over whatever is there, so a hand-edit
   is caught by those, but a hand-edit that *fixes* the tree silently
   changes what was landed relative to what the gate reviewed.


### 12.1 The stale-statement sweep — run, because master moved mid-authoring

Master advanced by two commits while this was being written (the `U-armor`
spec, `9b9b1a1`), which moved the S/FW ceilings and changed `U-armor`'s
status from *worktree draft* to *landed spec*. Rather than trust the folds,
six patterns were swept mechanically and every hit classified as
**historical** (inside a fold or `§R`, where quoting the superseded value is
the point), **cited** (the term is the subject of its own line — a quoted
grep command, a positive control, another unit's true ownership), or
**live** (everywhere else — this must be zero).

**The run that matters is the one before the fix**, because it is a real
failure the instrument caught on this document:

```
########## PRE-FIX (line-scoped classifier) ##########
patterns swept: 6    raw matches: 9
  historical: 6   cited: 1   LIVE: 2
  classifier control: 6+1+2 == 9 raw  OK
LIVE hits:
  line   74: §0 precedence still called S-55 "reserved by U-armor"  [REAL]
  line  177: the FW-138 positive-control command                    [FALSE POSITIVE]
  line  185: a wrapped fold sentence, second line                   [FALSE POSITIVE]
```

Line 74 was **genuinely stale** — `S-55` is a live row since `9b9b1a1`, not
a reservation — and it was fixed. The other two exposed a defect in the
*instrument*: the classifier read one line at a time, so a wrapped sentence
and a `$ grep` control both fell outside their own markers. The classifier
now reads a three-line window and treats a quoted command as *cited*.

Two real defects surfaced alongside them, both in §2.0 and both fixed: the
fold's fence cross-referenced *"control above: FW-141"* while the control
above actually used `FW-138`, and two ceiling commands were elided as
`python3 -c "…"` rather than written out — which would have made two
numbers unreproducible, against §0's rule.

```
########## POST-FIX (this revision) ##########
patterns swept: 6    raw matches: 8
  historical: 7   cited: 1   LIVE: 0
  classifier control: 7+1+0 == 8 raw  OK
```

**r4's sweep — and the admission that a sweep was the wrong instrument.**
Gate r2 found `M49` still reading *"7 `src/` modules hold a doc path"* — a
sentence §4.6a **retracts in the same document**, on a row labelled
**MEASURED**, while r3's ten-pattern sweep reported `LIVE: 0`. That is the
**fourth** surfacing of the `lrn-ea833a5b` class in this document's own
tooling, and **three of the four were a sweep failing to see a stale
claim**:

| # | instrument | what it missed |
|---|---|---|
| 1 | §2.4's diff3 probe | a repo-local config confound — reported "no dependency" under every scrubbing mechanism |
| 2 | r2's classifier | line-scoped, so a wrapped sentence fell outside its own markers |
| 3 | r2's sweep | pattern was `(§11 Q-2)` in parentheses; line 531 wrote `§11 Q-2 asks` |
| 4 | r3's sweep | had no pattern for the single most consequential sentence the gate retired |

r4 does two things about it. The **narrow** fix: the retracted sentence
joins the pattern set, and the sweep now **also walks the mutation table's
MEASURED rows**. The **durable** fix is `UN4` — every MEASURED row's claim
is re-measured at build start, and the build refuses on any that does not
reproduce. **A sweep can only match patterns someone thought of;
re-running the measurement cannot miss one.** That is the lesson the fourth
surfacing finally paid for, and it is why `UN4` is `[A]` rather than
another pattern in this list.

Thirteen patterns are swept at r4, aimed at what gate r2 retired. The set
evolved during the round (a `MEASURED-row` pattern was replaced by a
`three-hit claim` pattern once the count drift below was found), so the
numbers recorded here are the **final** set's, run twice:

```
########## PRE-FIX (r4 folds applied, sweep not yet run) ##########
patterns swept: 13    raw matches: 30
  historical: 26   cited: 2   LIVE: 2

########## POST-FIX ##########
patterns swept: 13    raw matches: 30
  historical: 28   cited: 2   LIVE: 0
  classifier control: 28+2+0 == 30 raw  OK
```

**Three real defects were found in r4's own text this round, and only one of
them by the sweep:**

1. **§2.7's suite table still quoted the ROOTLESS ui command** (found by the
   sweep). Same shape as r3's line-225 hit: `B-2` changed the invocation in
   §4.6, and a census table four hundred lines away still carried the old
   one — the exact form gate r2 measured collecting the CLI tree at rc 2.
2. **A duplicate criteria id** (found by the **count check**, not the
   sweep). §3.6's fold table had a row labelled `**SUI7**` — a heading, not
   a criterion, but indistinguishable from one to any id-based check, so the
   criteria count read **60 with a duplicate**. Renamed to `**`SUI7` leg**`.
   No pattern would have found that.
3. **"This spec's three hits" was stale by a factor of four** (found by
   **re-measuring**, not the sweep). Gate r2 measured 3 on r3's text; r4
   added four sections that quote the pattern words as evidence, and the
   real count is **13** (§3.6b). The sentence was true when written and
   false by the end of the same revision.

Findings 2 and 3 are the argument for `UN4` restated as evidence: **a sweep
can only match patterns someone thought of.** A structural count found one;
re-running a measurement found the other. Neither is a pattern.

**r5, and the fifth surfacing — the first inside the criterion built to end
the class.** Gate r3 found `UN4` itself unimplementable and vacuous: **9 of
11** MEASURED cells carried no command, and with no count floor a parser
matching nothing ran zero commands and reported **PASS**. §12.1's r4 text
argued *"a sweep can only match patterns someone thought of; re-running the
measurement cannot miss one"* — correct, and the hole was one level up: **a
re-measurement that parses nothing to re-measure.**

| # | instrument | what it missed |
|---|---|---|
| 1 | §2.4's diff3 probe | a repo-local config confound |
| 2 | r2's classifier | line-scoped; a wrapped sentence fell outside its markers |
| 3 | r2's sweep | matched `(§11 Q-2)`; the text said `§11 Q-2 asks` |
| 4 | r3's sweep | no pattern for the sentence the gate most squarely retired |
| **5** | **r4's `UN4`** | **no command to run and no floor to notice** |

The escalation r5 makes is not another instrument — it is **making the
instrument's own input a checked artefact**: §6.1's ledger is parsed, its
row count is asserted against the totals line, and both failure directions
have run controls (a parser matching nothing → 0 → FAIL; a deleted row →
10 → FAIL). Four of the five surfacings were an instrument that could not
see; the fix each time was a control that fails when the instrument is
blind, and `UN4` leg (b) is that control for `UN4`.

**r6, and what this revision's own re-measurement found** *(gate N-21; the
r5 round published no sweep, and the gate found live drift in exactly r5's
new material)*. Twelve patterns aimed at what gate r4 retired — the floor
literal, the `+++`-after-`---` rule, `$OLDPWD` helper paths, `M78`'s
MEASURED label, `M69`'s pinned counts, `misc/` ledger paths:

```
patterns swept: 12    raw matches: 31
  historical: 29   cited: 2   LIVE: 0
  classifier control: 29+2+0 == 31 raw  OK
```

**But the sweep is not what found this round's defects — running the ledger
was.** Stated plainly, because four rounds of small residuals have earned
the scepticism:

| what found it | what it found |
|---|---|
| **the clean-clone run** (`UN4` leg (e), new this round) | **`pass=4 fail=9` on the first attempt.** Nine blocks still pointed at `misc/u-land-measured/` — the shipped paths had been written into §6.1's prose but not into the ledger the run reads. Loud (rc 127/2). |
| **the clean-clone run, again** | **`M54` failed OPEN**: `grep -cEi "$(cat …/pat.txt)"` with `pat.txt` absent gave an **empty pattern**, matching **all 7** lines at rc **0**. A wrong number at a passing rc — M-20's shape, one row over, in a block written the same hour as the fix for M-20. |
| **`floor.py`, run against r5's text** | `measured=14 blocks=11 missing=M76,M77,M78` — gate r4's M-22, reproduced by the checker built to prevent it. |
| **the sweep** | nothing this round. |

Three of the four came from **executing** something; the sweep found none.
That is the same distribution as r5's round (sweep 1 of 3, count check 1,
re-measurement 1) and it is now the pattern, not an anecdote: **on this
document, running the artefact finds what reading it does not.** `UN4`
leg (e) is the generalisation — not "sweep for the mistake we just made"
but "run the whole ledger somewhere the author's machine cannot help it".

**r8's sweep** *(N-28 — the r7 round published none, and gate r6's own
independent sweep found nothing live)*. Thirteen patterns aimed at what
gates r5 and r6 retired, including a structural one for the N-26 defect
(**a row carrying a bold label token in two cells**):

```
patterns swept: 13    raw matches: 22
  historical: 20   cited: 2   LIVE: 0
  classifier control: 20+2+0 == 22 raw  OK
```

**Mine agrees with the gate's: nothing live.** The one defect this round
did surface — N-26's mis-labelled count — was found by **neither** sweep.
It was found by *counting the labels and comparing them to the stated
total*, which is the sixth entry in this section's ledger of what found
what, and the fourth time the answer has been "not the sweep". `floor.py`
now performs that count on every run, so this particular blindness is
closed by construction rather than by a pattern.

**The zero rests on the instrument having caught a real, live failure on
this document** — not on a matcher finding nothing in regions it was told
to ignore.

**r2's sweep, over the strings the rulings retired.** Eight patterns
(the r1 criteria/mutation totals, `RES7`'s `[B]`, the `§11 Q-N` hedges
left in design sections, the old §11 heading, "not in r1", and the
one-field ack form):

```
########## PRE-FIX (r2 folds applied, sweep not yet run) ##########
patterns swept: 8    raw matches: 17
  historical: 13   cited: 2   LIVE: 2
  classifier control: 13+2+2 == 17 raw  OK
LIVE hits:
  line 315: §2.3 still ended "§11 Q-1", framing a RULED question as open  [REAL]
  line 625: §3.4's own quotation of the superseded recommendation         [FALSE POSITIVE]

########## POST-FIX ##########
patterns swept: 8    raw matches: 16
  historical: 14   cited: 2   LIVE: 0
  classifier control: 14+2+0 == 16 raw  OK
```

Line 315 was real: §2.3 carried its original recommendation verbatim and
pointed at an open question that no longer exists — the exact class this
sweep is for, caught on the first revision that could produce it. It is
now written as the ruling, keeping the *argument* (which survives) and
dropping the *recommendation framing* (which does not). Line 625 was the
instrument again: the classifier's marker was `recommended` and §3.4
writes `recommendation`. Widened, as in r1.

**r3's sweep — and the gate's own catch is its positive control.** The r2
sweep reported `LIVE: 0` while §2.9 line 531 still read *"§11 Q-2 **asks**
whether spec-only landings … are in this runner's scope at all"* — present
tense, framing as open a question §3.4 records as OVERRULED. **The gate found
it; my sweep did not**, and it was the same defect class, in the same section
class, as the line-315 hit the r2 sweep *did* catch. The r2 §12.1 text then
elevated that zero to evidence. **A sweep reporting zero with a live hit
present is the `lrn-ea833a5b` shape inside the instrument built to prevent
it** — the third time this class has surfaced in this document's own tooling
(§2.4's confound, r2's classifier, now this).

The miss was scope, not classification: the r2 sweep's pattern was
`§11 Q-1|\(§11 Q-2\)|\(§11 Q-6\)` — bare `Q-N` in parentheses — and line 531
writes `§11 Q-2 asks` with no parentheses. r3 sweeps ten patterns aimed at
what the *gate* retired, matches `§11 Q-\d asks` directly, and widens the
window to four lines each side:

```
########## PRE-FIX (r3 folds applied, sweep not yet run) ##########
patterns swept: 10    raw matches: 23
  historical: 20   cited: 0   LIVE: 3
  classifier control: 20+0+3 == 23 raw  OK
LIVE hits:
  line  225: §2.1's incident table still credited EXC1 with `set -euo pipefail` [REAL]
  line 1320: §4.10's measurement table, the broken form as its own subject      [FALSE POSITIVE]
  line 1322: §4.10's measurement table, second broken form                      [FALSE POSITIVE]

########## POST-FIX ##########
patterns swept: 10    raw matches: 22
  historical: 20   cited: 2   LIVE: 0
  classifier control: 20+2+0 == 22 raw  OK
```

Line 225 was real and is exactly the kind the gate warned about: B-1 changed
the shell contract in §4.10 and `EXC1`, and the **incident table's criterion
cell** — four hundred lines away — still named the retired form. The two
false positives are §4.10's own measurement table quoting the broken forms it
exists to reject; the classifier now treats a measurement-table row as cited.

*(Master moved twice more after the r1 sweep — `U-scrub` at `99d310e`. That
landing changed a **design** decision rather than a number: the §9 gate is
now a shipped test, so `CHK5` calls it instead of reimplementing it
(§2.5, `M25`). Every load-bearing count was re-run at `99d310e` and only
the CLI test-file count moved, 87 → 88.)*

---

## R. Revision history

| r | date | change |
|---|---|---|
| r8 | 2026-08-28 | **Blind spec gate r6 → SOUND (0 B / 0 M / 3 N); all three nits folded, no re-gate** (§3.10). The Major count converged **11 → 5 → 3 → 3 → 1 → 0** across six blind rounds. **`N-26`**: `floor.py` now checks **all three label counts** against the §6 totals line (`MATCH`/`MISMATCH`) and refuses any row carrying a bold label token outside its status cell. Root cause fixed: `M69`'s evidence cell carried a bold `**OBSERVED**` describing the counts behind its predicates while its *status* is `**MEASURED**` — a substring scan therefore miscounted it, which is why the gate reported 5 OBSERVED / 67 predicted. **Measured: 13 MEASURED / 4 OBSERVED / 68 predicted, totals-line MATCH, stray-bold none** — and `M69` **has a ledger block**, so labelling it OBSERVED would have broken the floor with `extra=M69`. The adjudication is recorded in §3.10. **`N-27`**: `spec_path()`'s `exit 3` inside `$(spec_path)` left only the subshell; the caller now tests the substitution (`SPEC=$(spec_path) \|\| exit 3`) with an empty-value guard — **verified: 0 matches ⇒ rc 3, 2 matches ⇒ rc 3, 1 match ⇒ rc 0**. **`N-28`**: §12.1 publishes the sweep — 13 patterns, 22 raw, 20 historical, 2 cited, **0 LIVE**, agreeing with the gate's own. Ack count **23, unchanged** (no pattern line was added or removed). Criteria **59**; mutations **85** (13 MEASURED / 4 OBSERVED / 68 predicted). **Status: SOUND; build pending.** |
| r7 | 2026-08-28 | **Blind spec gate r5 → NOT SOUND (0 B / 1 M / 2 N); all 3 findings folded** (§3.9) — **three rounds with no Blocker**, and the Major count is converging 11 → 5 → 3 → 3 → **1**. The gate closed all six r4 findings **by execution**: its own clean-clone ledger run 13/13, `M84` in both directions, `need` on a genuinely missing helper, the `diff --git` anchor against five more attacks, and the ack count 23 matching §3.6b. **`M-23`**: shipping the helpers into `cli/tests/measured/` (§8) made **`walk.py` count itself** — its `CORPUS` regex is a real string constant containing `docs/`. Measured at `9c7ebdd`: **144 / 43 / 39 / strict 8** without the directory, **149 / 44 / 40 / strict 9** with it, so `SUI7` legs (a) and (c) would redden **on a correct build** and no ledger row checked the tests column. **Fixed at the root, not by exemption**: the helpers are measurement instruments, not tests (0 collected ids), so they ship at **`plugins/self-learn/cli/scripts/measured/`** beside `suite` and `land`. **Verified first, as ruled** — the walk's roots are `cli/tests`, `ui/tests`, `cli/src`, `ui/src`, and **`scripts/` appears 0 times in them**; re-measured with the helpers installed there the walk reads **144 / 43 / 39 / 8**, identical to baseline. **No path exclusion was added to the walk.** New `SUI7` leg (f) (the walk run *after* the instruments exist) and `M85`. **`N-24`**: `floor.py` gains `--delete-one`, a control that needs no commit ref — measured `measured=13 blocks=12 missing=M20`, failing as it must; the commit-ref form applies once this spec lands. **`N-25`**: `_lib.sh` gains `spec_path()`, a glob over `docs/specs/self-learn/**/u-land-*.md` asserting **exactly one** match; `M77` calls it instead of hardcoding the path. **The r7 clean-clone re-run found one more defect of its own**: `_lib.sh`'s first `ROOT` derivation climbed four levels and landed on `plugins/`, so `spec_path()` searched nothing — it failed **loudly at rc 1** (the N-22 hardening working), and `ROOT` now derives from `git rev-parse --show-toplevel` with an existence assertion, which is depth-independent. Final clean-clone run at the new path: **`pass=13 fail=0`**. Also folded: `src` denominator **76 → 77** (U-verbs added `batch.py`). Criteria **59** (unchanged; `SUI7` gains leg (f), now six); mutations **84 → 85** (13 MEASURED, 4 OBSERVED, 68 predicted). Gate r6 returned **SOUND** (0 B / 0 M / 3 N). |
| r6 | 2026-08-28 | **Blind spec gate r4 → NOT SOUND (0 B / 3 M / 3 N); all 6 findings folded** (§3.8) — **two rounds running with no Blocker**. The gate verified all 8 r3 findings closed and reproduced **10 of 11** ledger blocks with **its own independent parser**, both floor controls, and the ack count 19. **`M-20`**: `m73.sh` read `$OLDPWD/misc/u-land-measured/parse.py` — git-excluded — so `M73` reproduced only on the author's machine, and with no existence check it printed `flat=1 parsed=` at **rc 0**. Every helper now sources `_lib.sh` (`set -uo pipefail`, `HERE="$(dirname "$0")"`, `need` exiting 3 loudly) and the runner fails on a non-zero helper rc; new **`UN4` leg (e)** runs the **whole ledger from a clean detached checkout with no `misc/`**. `M81`, `M84`. **`M-21`**: the `+++`-after-`---` rule misfires when a **deleted** line's content begins `-- ` — reproduced: `f.md:1` never scanned and the hit attributed to **`evil-path:3`**. The parser now **anchors on `diff --git`**, headers only before each file's first `@@`; both fixtures kept as `SAN3` legs; `M76`'s block runs it and reports `r5=evil-path:3 r6=f.md:3`. `M82`. **`M-22`**: 14 rows were labelled MEASURED against 11 blocks with the floor a **literal**. `M76`/`M77` get blocks, **`M78` is relabelled OBSERVED** (its own claim is the untracked-state comparison leg (d) forbids), and the floor is **DERIVED** — `floor.py` compares the *sets* and reports `missing`/`extra`; against r5's text it prints `missing=M76,M77,M78`, the defect a literal could not see. `M83`. **Nits**: `N-20` `M69`'s row quotes only the predicate form; `N-21` §12.1 publishes the r5/r6 sweep **and says what this revision's own re-measurement found** — the clean-clone run scored **`pass=4 fail=9`** first (nine stale `misc/` paths, and `M54` failing **open** at rc 0 by matching all 7 lines on an empty pattern), while the sweep found nothing; `N-22` helpers hardened. **The MEASURED label now means exactly one thing**: the row has a runnable ledger block, and `M77` asserts the two sets are equal. Final clean-clone run: **`pass=13 fail=0`**. Criteria **59** (unchanged; `UN4` gains leg (e)); mutations **80 → 84** (13 MEASURED, 4 OBSERVED). Gate r5 returned NOT SOUND (0 B / 1 M / 2 N). |
| r5 | 2026-08-28 | **Blind spec gate r3 → NOT SOUND (0 B / 3 M / 5 N); all 8 findings folded** (§3.7) — **the first round with no Blocker**. All 12 r2 findings verified closed; the gate's held attacks (ack coverage both directions, moved-line key invalidation, the 13-hit count, binary/mode-only/no-newline edge cases) unchanged. **`M-17`**: `UN4` was **unimplementable and vacuous** — measured, **9 of 11** MEASURED cells carried no command at all and there was no count floor, so a parser matching nothing reported PASS. New **§6.1, the MEASURED ledger**: one fenced ` ```measured M<n> ` block per row, `measure:` + `expect:`, **all eleven written and run** (`pass=11 fail=0`); `UN4` rewritten to four legs with the **count floor** `parsed_rows == 11` and both controls run (nothing-parser → **0** → FAIL; deleted row → **10** → FAIL). `M77`. **`M-18`**: the `@@` parser ate an added line beginning `++ b/` as a header — reproduced: `collide.md` vanished, the line was never scanned, and the hit was attributed to **`evil-path:1`, a file not in the tree**, fabricating a `SAN4` ack key. `+++ ` is now a header **only after a `--- ` line**; verified on the same fixture; six new `SAN3` legs (the collision plus the four edge cases, all of which hold). `M76`. **`M-19`**: `SUI8` leg (b) and `M69` pinned counts that depend on **untracked state** — 331/3327 on the production root vs **32/2668** in a fresh worktree at the same commit, differing only by git-excluded `misc/` — and `UN4` re-runs MEASURED claims and refuses the build, so two correct criteria interlocked into a **deterministic false refusal on every machine but one**. Both now assert **stable predicates**; the counts are demoted to a dated **OBSERVED** table; `UN4` gains the rule that a MEASURED claim may not depend on untracked state. `M78`. **Nits**: `N-15` the stale flat-`grep` bullet folded (and added to the sweep); `N-16` `M72`/`M73` — the only two of 75 unreferenced — now named by `CNT2`/`SAN3`, re-verified **0** unreferenced; `N-17` `SUI8` gains a `git ls-files` membership leg (a prefix check passes with an untracked scratch test *inside* `ui/tests/`: 1271 collected, 0 outside), `M79`; `N-18` `SAN4` prints paste-ready ack strings (this landing needs 19, and any edit above a hit shifts its key); `N-19` `WLD1`/`WLD2`'s reads are `$ROOT`-relative and `DRY2` covers them, `M80`. §12.1 records this as the **fifth surfacing** of the `lrn-ea833a5b` class and the **first inside the criterion meant to end it**. Criteria **59** (unchanged; `UN4` rewritten); mutations **75 → 80** (14 MEASURED). Gate r4 returned NOT SOUND (0 B / 3 M / 3 N). |
| r4 | 2026-08-28 | **Blind spec gate r2 → NOT SOUND (1 B / 5 M / 6 N); all 12 findings folded** (§3.6). The gate verified **all 20 r1 findings closed**, 19 with numbers reproducing exactly, and **adjudicated the docs-only lane KEEP by measurement** — docs lane **29 s / 354 tests**, full lane **473 s**, saving **444 s = 94 %**, coverage given up **9.2 %**, and **the lane runs zero UI tests** (§3.6a; §12 items 2 and 10 close on these numbers). **`B-2`**: the UI suite invoked from the repo root **collects the wrong tree** — no root-level pytest config exists, and `uv run --project` sets the venv, not the collection root, so `testpaths` resolves against the cwd. Measured: from the root **rc 2**, 331 error lines, **3327** `cli/tests` ids, the first from a git-excluded `misc/` checkout copy; from `plugins/self-learn/ui` **rc 0, 1270 tests, 0** cli ids. §4.6 sets the cwd, **rc 2 becomes a third refusal class** (the allowlist cannot adjudicate a collection error), `SUITE_TIMEOUT` = **600 s** from the measured 243/230; new **`SUI8`**, `M69`/`M70`. **`M-12`**: the allowlist took the docs lane on a **rename into `docs/`** (measured: `git mv src/verbs.py docs/verbs.py` reports one path, `NONDOC=0`, a `src` module deleted) — the detector now uses **`--no-renames`**; control measured that a rename *out* of `docs/` was already fail-closed; `SUI6` legs (h)/(i), `M71`. **`M-13`**: `--continue` did not bind the merge sha — measured, the original, an **amended**, and a **second** merge all passed its three conditions, and the third would push a merge for which `--remeasure` never ran, reddening `ARM5` (b) on the *next* landing. Fourth precondition added; `CNT2` leg, `M72`. **`M-14`**: the flat `grep '^+'` stream cannot produce `SAN4`'s `(file, line-number, sha)` key **at all**, and scans the `+++` header — measured, a file named `secret_fixture.md` is 1 hit flat / **0** parsed. §4.7 parses `git diff --unified=0` `@@` headers; headers excluded by construction; `SAN3` legs, `M73`. **`M-15`**: `SAN5` leg (d)'s **path exemption list is DELETED** — a standing, non-content-bound skip in `docs/specs/self-learn/drafts/`, incident 1's own directory, and the shape this spec's doctrine rejects one paragraph earlier. This spec's **three** hits are acked through `--sanitize-ack` (§3.6b — this unit's landing becomes the mechanism's first worked example); seeded fixtures are **generated at test time**; `M74`. **`M-16`**: `M49` was stale **and measured-false**, labelled MEASURED — re-aimed at the detector form, the retracted sentence added to §12.1's patterns, the sweep extended over the MEASURED rows, and the durable fix shipped as new **`UN4`**: every MEASURED row re-measured at build start (`M75`). §12.1 now records that **three of the four** `lrn-ea833a5b` surfacings in this document's tooling were a *sweep* failing — which is why `UN4` is a re-measurement, not another pattern. **Nits N-9…N-14** folded (`M51`'s filename, `M48`'s denylist language, the fragment block's **8** lines, `SAN4`'s new-file line-number frame, `CHK8`'s collector exclusions, §12 items 2/10). Criteria **57 → 59** (58 `[A]` / 1 `[B]`); mutations **68 → 75** (11 MEASURED). Gate r3 returned NOT SOUND (0 B / 3 M / 5 N). |
| r3 | 2026-08-28 | **Blind spec gate r1 → NOT SOUND (1 B / 11 M / 8 N); all 20 findings folded** (§3.5), plus the orchestrator's ruling on the gate's second flag. Re-measured in a detached read-only checkout at `99d310e`, since removed. The gate reproduced **31 of 36** claims; **four of the five it broke were my numbers, not my reasoning**, and §3.5a states both root causes in §2.4's shape. **`B-1`**: `set -euo pipefail` and rc capture are **mutually exclusive** — measured, under `-e` the `.rc` file is **never written** and every refusal exits bash's `1`. §4.10 rebuilt as `set -uo pipefail` + explicit `\|\| die <code>`; **`SUI5` and `EXC1` rewritten and shown to both hold**; new `M53`. **`M-1`**: the "7 `src/` modules read a corpus doc" claim is **false** — strict count **0**; all seven carry the path in a module *docstring*. The indirect-reader residual **does not exist**; `SUI7` leg (b) becomes a **detector** (the count must stay 0). **`M-2`**: 39/43/4 were a **docstring-inclusive** walk described as strict — §3.5a item 1. §4.6a now ships the walk as runnable code and reports all three columns: 142 modules, naive **42**, docstring-inclusive **38**, **strict 8**. The lane set is **8**, and `FW-142` is re-scoped a second time to the residual that *is* measured — the **part-built** path (`test_reader_contract.py` holds `'docs'` and `'specs'` separately). **`M-3`**: the verbatim pattern file scores **4** self-hits and the r2 spec **3** — `land` would have refused its own landing. §4.7a takes U-scrub's fragment road; measured: assembled regex **equals** the spec's set, fragment file **0** self-hits; new `M54`. §3.5a item 2 is the post-mortem — the "ordinary English words" argument was right for `CHK5` and applied to the wrong gate. **`M-4`**: the detector becomes an **allowlist** (docs lane iff every path is under `docs/`); **81** tracked files escaped r2's denylist, incl. `ui/static/app.js`, `uv.lock`, `pyproject.toml`, `plugins/self-learn/scripts/self-learn`. **`M-5`**: the armor/five-file step between `--remeasure` and `git commit` is **deleted** — it made `U-armor`'s `ARM5` leg (b) red on every correct landing; new **`CHK8`**, `M55`. **`M-6`**: world detection moves **post-merge**, asserts **exactly one** mechanism, and `CHK2` gains an **N ≥ 1** floor — `U-armor`'s own build is the vacuity case; `M56`. **`M-7`**: `per-key` refuses duplicate keys and colon-less lines (executed: `'a: 1'` silently lost); `M57`/`M58`. **`M-8`**: new **`PRE8`** `git fetch origin master` (r2 had **0** fetches against **12** `origin/master` uses); `M59`. **`M-9`**: ack coverage is **exact**, keyed `(file, line-number, sha)`, split at the first `=` after the hash; `M60`. **`M-10`**: §4.1 states the package's **root-resolution rule**; `DRY2` gains `CHK5`/`SAN3`; `M61`. **`M-11`**: line 531 folded and the sweep re-run — **the gate's catch is the new positive control** (§12.1). **Gate flag RULED**: new §4.10a **`--continue`** with a landing-state file under `${XDG_CACHE_HOME:-~/.cache}/self-learn/` (never in the tree); new `CNT1`/`CNT2`, `M62`/`M63`. **Nits N-1…N-8** all folded, incl. `PRE1`'s `--path-format=absolute` predicate (r2's form falsely refuses from any subdirectory — measured) and `CHK6`'s budget **200** (measured max subject **158**). Criteria **53 → 57** (56 `[A]` / 1 `[B]`); mutations **52 → 68** (7 MEASURED). Gate r2 returned NOT SOUND (1 B / 5 M / 6 N). |
| r2 | 2026-08-28 | **All six open questions RULED by the orchestrator and folded** (new §3.4; §11 becomes the index, the original recommendations kept in a `<details>` block). Worktree fast-forwarded to live master **`99d310e`**; every load-bearing number re-run there and unchanged. **`Q-2` OVERRULED** — spec-only/docs-only landings are **IN** scope: new §4.6a lane whose detector is measured (`grep -c … \|\| true`, because a **zero** code-file count IS the docs lane — incident 3's mechanism one step earlier in the chain), its test set derived by AST walk at **39 of 139** modules (naive grep 43; the 4-file difference is docstring-only mentions), and — the finding that keeps the residual alive — **7 `src/` modules also hold a corpus-doc path**, so a file-level derivation over `tests/` is provably a **lower bound**. New **`SUI6`** (the detector, 4 legs) and **`SUI7`** (the derivation plus a `src/`-coverage guard, 3 legs); **`FW-142` re-scoped, not withdrawn** (no numbered hole left behind). **`Q-1`**: `count-line` `[B]` → **`[A]`**; §3.4 records that the ruling's *"two of tonight's five landings"* warrant is **not confirmable from the repository** — 14 first-parent merges tonight, 3 left a resolver script, `count-line` in **1** of those 3 (§12 item 8). **`Q-4`**: an unmapped conflict now prints the **candidate resolver names** per block, a diagnostic that never becomes a default (`RES4` leg 2, `M50`). **`Q-6`**: `--sanitize-ack` is **two-field** — `<file>:<line-sha256>=<reason>` — with **no boolean form** (`SAN4`, 4 legs, `M52`). **`F-1`**: `PRV3` rewritten to three legs run under `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null`; §2.4's probe **re-run after the first one was found confounded** — it had `conflictStyle` set repo-locally and so reported "no dependency" under every scrubbing mechanism, the `lrn-ea833a5b` shape inside this spec's own instrument. Corrected and discriminating: plain **1** base marker, `HOME=/nonexistent` **0**, `GIT_CONFIG_GLOBAL=/dev/null` **0**, scrubbed **plus the runner's own `-c`** **1**. **`F-2`**: new §4.7a — the canonical pattern set moves into the repo as `landing/sanitize_patterns.txt`, the home prefix stored **only** as a `%HOME%` placeholder so the list cannot trip the gate it feeds (new **`SAN5`**, `M51`); `CLAUDE.local.md`'s prose should point at it, an **owed edit this unit may not make** (§12 item 9). Criteria **50 → 53** (52 `[A]` / 1 `[B]`); mutations **46 → 52** (3 MEASURED). Gate r1 returned NOT SOUND (1 B / 11 M / 8 N). |
| r1 | 2026-08-28 | First draft, authored at `6038eee` in `.claude/worktrees/u-land-spec`, **every load-bearing number re-run at live master `99d310e`** after four commits landed mid-authoring — the `U-armor` spec (`9b9b1a1`) and `U-scrub` (`99d310e`). Suite 55, ad-hoc 268, pins 7, `test_armor.py` absent, home files 14/0, UI 51: unchanged. Three folds: the S/FW **ceilings** moved `S-54`/`FW-138` → `S-55`/`FW-141` (§2.0; this unit's own numbers unchanged), CLI test files 87 → 88, and **`CHK5` now CALLS `U-scrub`'s shipped `test_personal_literals.py` rather than reimplementing the grep** (§2.5, `M25` re-aimed). §12.1 is the swept fold, with its pre-fix run as the positive control. **50 criteria** (48 `[A]`, 2 `[B]`), **46 mutations** (2 MEASURED, 44 predicted), `S-56` + `FW-142`/`FW-143` reserved. Six open questions, each with a recommendation. **Three findings the brief did not anticipate, all measured: (i)** the diff3 base marker every existing resolver parses is supplied by the operator's **global** `~/.gitconfig`, not the repository — under git's compiled default the marker count is **0** against a control of **1**, and the parser raises (§2.4, `PRV3`, `M10`); **(ii)** the `plugins/`-scoped personal-literals gate is **vacuous** against incident 1, whose six paths were in `docs/…/drafts/` — `git grep -l "$HOME" -- plugins/` is **0** while the same command tree-wide is **14**, so the sanitize gate is scoped by *diff and added lines*, not by path (§2.5, `SAN3`, `M20`); **(iii)** §2.3's conflict corpus has **four** recurring shapes, not three — `count-line` resolves 2 of 13 measured blocks and the three named resolvers cover only 10 of 13 (§11 Q-1, `RES7`). Superseded by r2 (the orchestrator's rulings) before the first gate; gate r1 reviewed r2. |
