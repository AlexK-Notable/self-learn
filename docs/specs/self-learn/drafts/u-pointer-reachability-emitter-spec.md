# Spec — U-pointer: the reachability emitter — proving compiled canon is loadable, per destination, with an explicit "cannot tell"

Status: **r3 — two gate rounds folded, no open questions.** r1: **NOT
SOUND — 3 BLOCKER / 7 MAJOR / 9 NIT**. r2 delta: **NOT SOUND — 1 BLOCKER /
2 MAJOR / 5 NIT**, plus rulings on both remaining questions. Twenty-seven
findings, all folded (§12); **§4's design was never touched across either
round** — every finding lived in §5, §6 or §8.

**Every BLOCKER across both rounds was one kind: a criterion that could
not fire, or a fixture that passed on a decoy** — this project's signature
defect appearing inside the instrument written to prevent it, twice, the
second time *inside the fix for the first*. r1 B3's global quantifier over
`extraKnownMarketplaces` became r2's global quantifier over `source`
shapes; only measuring the live map (28 decidable / 6 undecidable) showed
the row was still permanently true. §5.1A′ is the narrowing, and
T-SKILL-5c is the test that would have caught either version.

Unit `U-pointer` (TaskList #10), the last open finding of the 2026-07-27
routing audit.

**Base commit:** `9912482` (master). Every `file:line` below was read at
that tree. The r1 gate re-verified at `ac9fb33`, where
`git diff 9912482..ac9fb33 -- plugins/self-learn/cli/src
plugins/self-learn/cli/tests` is **empty**, so no citation needed
re-verification across the fold (r1 N9); r2's new citations were read at
that tree.

**Naming note, read first.** An older draft in this directory is also
called `U-pointer`:
`docs/specs/self-learn/drafts/u-pointer-reference-pointer-spec.md`. It is
**SHIPPED and CLOSED** — see §3. This document does not supersede it and
does not re-open it. It reuses the unit name because the TaskList row does.

**Files this unit may touch:**

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/reachability.py` | **new.** The one predicate module: `Verdict`, `Instrument`, `reachability_rows()` (with its `user_claude_md` override, §4.3), the four per-destination predicates, `read_instrument` |
| `plugins/self-learn/cli/src/self_learn/selfcheck.py` | one new check function `_check_surface`, one row in `run_selftest`'s `results` list (`:851-859`), one import. **No edit to `_check_reach`, `_check_drift` or `_check_hooks`** |
| `plugins/self-learn/cli/src/self_learn/report.py` | one new top-level facts key `surface_reach` in `gather` (beside `reference_shelf`, `:668`) and its text render (beside `:785`) |
| `plugins/self-learn/cli/tests/test_reachability.py` | new; the unit's own tests |
| `plugins/self-learn/cli/tests/test_selftest.py` | only where an existing assertion must absorb the new row's presence in `results` |
| `plugins/self-learn/cli/tests/test_new_skill.py`, `plugins/self-learn/cli/tests/test_selftest_hooks.py` | **coordinator amendment (builder round 1 collateral, 2026-08-23), fixture-only.** `test_selftest_drift_covers_new_skill` and `test_selftest_cli_includes_hooks_line` assert `--selftest` returns rc 0 on a "healthy install" sandbox that (pre-amendment) had no personal-skill symlink / no hook registration — exactly the gap this unit's `surface` row exists to report, so the new row correctly flipped rc to 1. Their intent is the healthy-install premise, not the absence of a reachability check; the fix is fixture-only (add the symlink / settings.json registration the sandboxes were missing), never weakening the assertion or special-casing the `surface` row. |

Anything else is out of scope and must be **reported, not edited**.

---

## 0. Reading order and precedence

1. `docs/specs/self-learn/drafts/u-glob-reachability-spec.md` — §4.3 (the
   anchored probe), §6.6 (the drift-side re-probe), and **§8** (the
   `InstructionsLoaded` harness, RATIFIED). This unit consumes §8's method
   in §7 and must not redesign it.
2. `docs/specs/self-learn/drafts/u-readref-instrument-spec.md` — §6.3
   ("not-instrumented is a distinct state, never zero") is the ratified
   shape this unit's `unmeasurable` state copies, deliberately.
3. `docs/specs/self-learn/drafts/u-pointer-reference-pointer-spec.md` —
   SHIPPED; §3 below states exactly what of it survives and what this unit
   is forbidden to touch.
4. `docs/specs/self-learn/03-decisions.md` **S-23** — `reference` survives
   at skill/project scope; user scope REFUSES it and that refusal stays.
5. This document. Where prose and §5/§8 conflict, **§5 and §8 win**.

---

## 1. Objective

After a route lands, self-learn writes bytes into a file and calls it
done. Two checks then ask whether those bytes are *present*
(`_check_drift`) and, for exactly one destination, whether they are
*named by a loaded surface* (`_check_reach`). **Neither asks the question
this unit exists to ask: would a session actually load that file?**

A skill can be switched off in the operator's settings. A rules file can
carry frontmatter that no longer matches the globs the ledger validated. A
hook script can be installed, executable, byte-perfect, symlinked — and
registered nowhere, so it never fires. In every one of those states
`self-learn --selftest` prints green, because nothing looks at the
*loadability* of the compiled surface.

This unit adds one predicate module and one selftest row that report, per
live routed record, whether its compiled surface is **reachable**,
**unreachable**, or **unmeasurable** — with `unmeasurable` a first-class
value that can never be rendered as either of the other two.

**The one-sentence contract:** *a check that cannot see its target must
never print "reachable".* That is `lrn-ea833a5b` (a gate whose
can't-see output is identical to its pass output is worthless) and
`lrn-6d21607e` (a canary pointed at a plausible decoy passes
unconditionally) applied to this repo's delivery layer. Every predicate in
§5 is specified with the fixture that proves it.

---

## 2. What remains unreached after U-glob and U-readref — verified

U-glob and U-readref shipped today. Both are point instruments; together
with the shipped `_check_reach` they cover the `reference` destination
completely and the `rules` variant partially. This section states, with
citations read at `9912482`, exactly what is left.

### 2.1 `_check_reach` covers ONE destination out of five

`selfcheck.py:342` — inside `_check_reach`'s record loop:

```python
if (record.routing or {}).get("destination") != "reference":
    continue
```

`PROPOSAL_DESTINATIONS` is `("skill-md", "claude-md", "reference",
"new-skill", "hook")` (`ledger_ops.py:86`). So four of five destinations
have **no reachability check of any kind**. `_check_reach`'s own docstring
scopes it honestly to "every LIVE reference-routed record"
(`selfcheck.py:288-289`); this is a stated boundary, not a bug in it.

**Live census, read-only, `~/.self-learn`, 2026-08-23** (62 live routed
records — `status == "routed"`, `superseded_by is None`):

| destination | variant | live records | reachability covered today |
|---|---|---|---|
| `claude-md` | — | 29 | **no** |
| `reference` | — | 18 | yes (`_check_reach` + `reference_shelf`) |
| `new-skill` | — | 4 | **no** |
| `hook` | — | 4 | **partial** (§2.4) |
| `skill-md` | — | 4 | **no** |
| `claude-md` | `rules` | 3 | **partial** (§2.3) |

**44 of 62 live records — 71% — sit behind a destination whose
loadability nothing checks.**

### 2.2 A skill can be switched off, and self-learn cannot see it

Skill-index membership is decided outside self-learn, in
`~/.claude/settings.json`. Two keys govern it, and **both were read
read-only on this host on 2026-08-23**:

- `enabledPlugins` — a dict of `"<plugin>@<marketplace>": bool`; 34
  entries, **24 of them `false`**.
- `skillOverrides` — a dict of `"<skill>": "off"`; **4 entries, all
  `"off"`**: `universal-directory-organizer`,
  `qmk-zmk-animation-conversion`, `obsidian-plugin-dev`, `chezmoi`.

**The `skillOverrides` mechanism was confirmed empirically, 4 of 4.** The
authoring session's own available-skills listing contains every other
skill symlinked under `~/.claude/skills/` and contains **none** of those
four. A skill set to `"off"` is absent from the session index while its
`SKILL.md` still sits on disk with its managed section intact.

`~/.self-learn/skills/chezmoi/` holds two records and the skill is
`"off"`. **Correction from r1 (N4):** its `SKILL.md` carries a self-learn
managed section from `lrn-98d42215` (now superseded), but that section is
**EMPTY** — the begin and end markers are adjacent lines
(`plugins/chezmoi/skills/chezmoi/SKILL.md:119-120`). So there is no
unreachable compiled *content* there today; what the case demonstrates is
the mechanism, and that nothing would report it if the section were
populated. The record is superseded, so it is not even in the live domain
— which is luck, not a check.

Discovery routes on this host, verified: `hosts.yaml` names
`skills_root: ~/repos/claude-skills`; no `claude-skills` plugin appears in
`enabledPlugins` at all; every self-learn-hosted skill is visible through
a hand-made `~/.claude/skills/<name>` symlink. **But r1 drew the wrong
boundary from that** (see §5.1A): it gated plugin resolution on
`settings.json`'s `extraKnownMarketplaces`, which lists only
non-built-in marketplaces, and concluded "rule 8 has no live subject".
That is false — 33 of the 34 `enabledPlugins` keys are
`@claude-plugins-official`, absent from `extraKnownMarketplaces`, so r1's
rule would have fired unconditionally and made every plugin verdict
unmeasurable. The correct instrument is
`~/.claude/plugins/known_marketplaces.json`, which carries an
`installLocation` for **every** marketplace, built-in included. §5.1A
specifies the resolution.

### 2.3 U-glob re-probes the LEDGER's globs, never the file's frontmatter

`selfcheck.py:549`, inside `_check_drift`'s U-glob §6.6 block:

```python
paths = routing.get("rules_paths") or []
```

`routing` is the record's stored routing block. The probe that follows
(`glob_reaches(roots, p)`, `:565-566`) therefore validates **the patterns
the ledger remembers**, not the `paths:` frontmatter actually present in
the compiled rules file — and the loader reads only the latter.

The two can diverge: the rules file is a real file a human may edit, and
`compile_managed_file` rewrites only the managed section. U-glob's own §8
evidence proves both directions matter — `canary-unpathed.md` (no
frontmatter) loaded at `load_reason: session_start`, i.e. **always**;
`canary-pathed-nomatch.md` (frontmatter present, glob matching nothing)
**never loaded at all**. So frontmatter that has drifted away from
`rules_paths` puts the rule into a load regime the ledger's own check
cannot see, in either direction.

This is not a criticism of U-glob: its §10.2 explicitly hands "a general
reachability emitter (U-pointer, TaskList #10)" the job of generalising
its point checks. This is that job.

### 2.4 A live hook record is never checked for being *registered*

`_check_hooks` (`selfcheck.py:699-806`) runs two independent loops:

1. **record → script** (`:726-777`): for every live hook-routed record,
   the script exists, is executable, and matches `routing.hook.script`.
2. **registration → symlink** (`:779-794`): for every `self-learn-*`
   command string in `settings.json`, the `~/.claude/hooks/<name>` link
   resolves.

**There is no third loop, and no arrow from a record to a registration.**
A hook record can be routed, its script compiled and executable and
byte-identical to the approved bytes, its symlink perfect — and no entry
in `settings.json` naming it. It fires never. `_check_hooks` prints
`PASS`, counting it in "`N` live hook script(s) intact".

The registration is manual by design: the generated script's own header
says `Register manually in ~/.claude/settings.json (matcher: "Bash"); the
symlink into ~/.claude/hooks/ materializes via ./install.sh` (read from
`routing.hook.script` of `lrn-38514455`). A manual step with no check is
the exact shape of the audit's transferable lesson.

**Matcher coverage is a second, decidable gap.** A hook record carries
`routing.hook.tools` (`ledger_ops.py:543-553`; e.g. `["Bash"]`) and the
registration carries a `matcher`. On this host all four live `self-learn-*`
`PreToolUse` registrations carry `matcher: "Bash"`, which covers them — but
a registration whose matcher is `"Edit"` for a `Bash`-guarding script is
inert, and nothing compares the two.

### 2.5 What U-readref did and did not close

U-readref shipped `report.py::_reference_shelf` (`:291`), keyed into
`gather` at `:668` and rendered at `:785`. It answers *was the reference
file ever opened* — a demand-tier read-rate instrument, for one
destination. Its `instrument_state` enum
(`ok` | `script-missing` | `not-registered` | `settings-unparseable`,
§6.3) covers whether **its own hook** is instrumented. It says nothing
about any other destination, and `settings-unparseable` there describes
the read instrument, not the reachability of anything.

### 2.6 The settings.json incident makes the `unmeasurable` state mandatory

`~/.claude/settings.json` broke on this host on 2026-08-23 (U-readref
§2.8, §9.4). While it was unparseable **every global hook was dead** — and
`_registered_hook_commands` returns `([], problem)` on a parse failure
(`selfcheck.py:681`), with the in-repo rule stated verbatim at `:674`:

> a broken settings.json must FAIL loudly, not read as 'nothing
> registered'

That rule is why this unit cannot use a two-valued verdict. Every
predicate in §5 reads the same file. When it will not parse, "no
registration found" and "the instrument is broken" are different facts
with different remedies, and collapsing them is `lrn-ea833a5b`.

---

## 3. Relationship to the older draft — this spec **EXTENDS**, it does not supersede

`u-pointer-reference-pointer-spec.md` **SHIPPED**. Verified at `9912482`:

- `git log`: `a4e328f feat(routing): U-pointer — reference routes deliver
  a reachable pointer`, merged as `a50a709`.
- `compilers.py:973` defines `apply_pointer`; `:913` defines
  `_POINTER_HEADING = "## Reference material (self-learn)"`;
  `compilers.py:154` exports it.
- `verbs.py:97` imports it; it is called at `verbs.py:2255` (the route
  leg) and `verbs.py:4466` (the recompile/backfill leg).
- `plugins/self-learn/cli/tests/test_pointer.py` exists and exercises it.
- `verbs.py:186` defines `POINTER_LABELS`, cited to "U-pointer §3.5".

**Therefore the memory note `routing-audit-findings.md` is STALE on its
one remaining row.** It says (2026-08-07) that `U-pointer` — the emitter —
"is **not started**". That was true when written and is false now: the
*reference pointer* emitter shipped. What remains open is the *general*
reachability question, which that note's row does not describe. A gate
reviewer comparing this spec to that memory should treat the memory as
superseded on this point and the git history as authoritative.

**What of the older draft survives, and binds this unit:**

| Older draft | Status here |
|---|---|
| §3.1 P-BLOCK, §3.2 T-TOKEN, §3.3 the `compilers.py` API | SHIPPED. **Untouchable.** This unit adds no pointer, changes no marker, and writes nothing into any compiled file. |
| §3.10 "one predicate, one home" | **Adopted as a design rule** (§4.3). It is why this unit puts its logic in one module with two renderers rather than two implementations. |
| §7.3 ACCEPTED residual — "the pointer's *efficacy* stays unmeasured" | **Closed for `reference` by U-readref's `reference_shelf`**, not by this unit. Named here so the gate does not expect it. |
| §7.4 ACCEPTED residual — "a dangling pointer still reads as reachable" | **Still open, and still out of scope** (§9.4). `_surface_names_target` proves the token appears; nothing proves it resolves. Adjacent, real, not this unit. |

**This unit is forbidden to modify `_check_reach`, `apply_pointer`, or any
pointer marker.** `reference` is wholly owned by the shipped pair
(`_check_reach` + `reference_shelf`) and is deliberately **excluded** from
this unit's domain (§9.1) — a second predicate over the same destination
is the "one check masking another" trap `_check_reach`'s own docstring
(`selfcheck.py:288-296`) was built to avoid.

---

## 4. DECISION — the emission surface

### 4.1 The ruling

**A new read-only `selfcheck` row named `surface`, computed by a new
module `reachability.py`, whose same per-record verdict list is rendered
a second time as a `surface_reach` facts block in `report.py::gather`.**

No probe inside `route`. No telemetry event. No live session is ever
started by anything in this unit's default path.

### 4.2 Why — and why not the two alternatives the work order named

**Rejected: a post-route probe inside `route`.** Three reasons, in order
of weight.

1. **It measures the wrong instant.** Reachability is a property of the
   operator's *current* configuration, not of the route. A skill switched
   off next week makes yesterday's route unreachable, and a probe at route
   time would have certified it. The state this unit reports is
   continuously falsifiable, so it belongs on a check that re-runs, not on
   a write that happens once.
2. **It makes routing fail for reasons the router does not control.** A
   route is a human decision already taken. Refusing it because
   `settings.json` is momentarily unparseable converts an audit finding
   into a capture-path outage — and the capture path is the product.
3. **Cost.** The `skill-md`/`new-skill` predicate reads and JSON-parses
   `settings.json` and stats a symlink; the `rules` predicate re-runs an
   anchored glob probe that U-glob measured at **17.95 s cold / 3.7 s
   warm** (U-glob §6.6, M10). Paying that on every route, for a fact that
   can change without a route, is the wrong trade.

**Rejected: a telemetry event.** *(r1 N3: the payload decision is **S-9**
(`03-decisions.md:20`, "record ids in the payload (TUI deep-link
contract)"), not S-7 (`:18`, the storage decision) — and S-9 **permits**
ids rather than restricting payloads to them, so it is not by itself a
bar.)* The closed kind set (`telemetry.py:75`, `EVENT_KINDS`) has no
member for this, and — decisively — **there is no consumer.** U-readref's event exists
because reads are *events* nothing else can observe. Reachability is
*current state*, fully re-derivable by reading the same files again, so an
append-only log of it is strictly worse than reading it on demand.

**Chosen: selfcheck, with a facts block.** `selfcheck` is already the
repo's read-only, on-demand, nightly-runnable audit; it already owns the
sibling questions (present? named? script intact?); it already has the
refusal posture for a missing/not-a-repo home; and it already returns a
non-zero exit code, which is what makes a finding actionable rather than
decorative.

The facts block is **not a second surface** — it is the machine-readable
render of the same verdict list, and §4.3 forbids it from computing
anything. It exists because a selftest row is one prose line, and 44
records across four destinations need per-record structure for the UI and
the nightly report to consume. U-readref set this precedent for the
demand tier; this unit follows it rather than inventing a shape.

### 4.3 One predicate, two renderers — NORMATIVE

`reachability.py` exposes exactly one entry point:

```python
def reachability_rows(
    home: Path,
    claude_dir: Path,
    *,
    user_claude_md: Path | None = None,
) -> list[Verdict]: ...
```

- `selfcheck._check_surface(home, claude_dir)` calls it and renders
  `tuple[bool, str]`.
- `report._surface_reach(home, claude_dir)` calls it and renders the facts
  dict.

**`user_claude_md` — NORMATIVE, and it is BLOCKER-grade (r1 B1).**
`managed_target_for` takes a `user_claude_md` override (`verbs.py:803`,
added by U-xscope today) and **selfcheck has never threaded one** —
`_target_for`'s docstring states it verbatim at `selfcheck.py:216-219`:
*"selfcheck never threads a `user_claude_md` override, so this always
resolves against the operator's real `~/.claude/CLAUDE.md`"*. This unit is
the **first caller that must**, because it is the first check whose
verdict compares a compiled target against a runtime directory.

- **Default:** `user_claude_md or (claude_dir / "CLAUDE.md")`. Never
  `DEFAULT_USER_CLAUDE_MD`, never `Path.home()`, never a second `~`
  expansion. One expression, computed once, at the top of
  `reachability_rows`.
- **Threaded to all three user-scope resolvers:**
  `managed_target_for(home, bucket, record, user_claude_md=<it>)`,
  `_user_rules_dir(<it>)` (`verbs.py:772-777`, which is
  `.parent / "rules"`), and `_user_reachability_roots(home, <it>)`
  (`verbs.py:892-903`, which derives `$HOME` as `.parent.parent`).
- **Why the third matters most:** `_user_reachability_roots` handed
  `DEFAULT_USER_CLAUDE_MD.expanduser()` yields the operator's real `$HOME`
  (`verbs.py:903`), so every user-scope rules test would glob the whole
  home directory — U-glob M10 measured **17.95 s cold** per walk. Threaded
  from `claude_dir`, the sandbox globs the sandbox.
- **`_check_surface` derives it from `claude_runtime_dir()`**
  (`selfcheck.py:664-668`), the same env-overridable resolution
  `_check_hooks` already receives at `selfcheck.py:857`. `report`'s
  renderer receives it the same way (§6 rule 6).
- **Neither renderer may re-derive, re-probe, filter by destination, or
  recompute any field.** Any counting either does must be a count over the
  returned list. A gate reviewer finding a `settings.json` read, a
  `glob_reaches` call, or a `Record.from_path` in either renderer must
  treat it as a defect: two implementations of one predicate is the
  divergence this rule exists to prevent (older draft §3.10).

### 4.4 The row's boolean, and why `unmeasurable` does not fail it

`run_selftest` (`selfcheck.py:851-859`) types every check as
`tuple[bool, str]`. Widening that touches all eight rows and is out of
scope (§9.5). So the **verdict enum is three-valued and the row is
two-valued**, resolved by this rule:

**Refusal posture first — the row cannot be reached without it (r1 M-E).**
`_check_surface` opens exactly as its siblings do, and this is normative,
not stylistic:

1. `state = home_state(home)`; if `state in ("missing", "not-a-repo")`
   return `(False, home_state_message(state, home))` — byte-identical to
   `_check_reach`'s opening (`selfcheck.py:324-326`) and to
   `cli._home_gate`'s refusal set.
2. `if not hosts_path(home).is_file(): return True, "hosts.yaml absent —
   reachability not checked"` (mirrors `selfcheck.py:327-328`).

**Without step 1 a `not-a-repo` home yields zero buckets, and row 4 below
prints `PASS surface — no records in the reachability domain`** — a
ledger nobody can see certifying canon, which is exactly the shape
`_check_drift`'s docstring (`selfcheck.py:431-435`) records as audit
2026-07-16 MAJOR 5. **T-REFUSE** and **M24** pin it.

| # | verdicts present | row | why |
|---|---|---|---|
| 1 | any `unreachable` | **FAIL** | broken canon; a remedy exists and is named |
| 2 | any `unmeasurable` with reason `settings-unparseable` | **FAIL** | the instrument is present and broken (§4.4a) |
| 3 | no `unreachable`, some `unmeasurable` | **PASS**, with the unmeasurable count **and the note line** mandatory | the instrument is absent, not the canon broken |
| 4 | all `reachable`, ≥1 checked | **PASS** with its count | |
| 5 | zero live records in domain | **PASS** — `"no records in the reachability domain"` | reached only past the step-1/2 refusals |

**The message grammar is NORMATIVE (r1 M-B, M-C).** The mandatory count
is the whole of the safety argument, so it is a criterion, not a
convention — and so is the note line, which the orchestrator's §11 Q2
ruling requires and which nothing in r1 asserted. The row's `reason`
string is built from exactly these three parts, in this order:

```
<R> of <N> verified reachable; <U> UNMEASURABLE; <X> UNREACHABLE
  (unmeasurable: <reason>[, <reason>…][ — <resolved claude_dir>])
```

- The head `<R> of <N> verified reachable` is present on **every** run,
  including all-blind ones, where it reads `0 of 44 verified reachable`.
- `; <U> UNMEASURABLE` is present iff `U > 0`; `; <X> UNREACHABLE` iff
  `X > 0`.
- **The parenthetical names the DISTINCT `unmeasurable` reasons actually
  present**, sorted, comma-separated — never a bare directory.
- **The resolved `claude_dir` is appended only when a `claude-dir-absent`
  or `settings-unparseable` reason is among them** — in a sandbox that is
  `tmp_path/"claude-dir-default"`, never the literal `~/.claude`.

**Why the dir is conditional (r2 MAJOR 2).** r2 mandated the note line on
every `U > 0` and always named the runtime dir. But `unmeasurable` has six
reasons with nothing to do with the runtime dir — `target-missing`,
`target-unresolvable`, `host-missing`, `frontmatter-unreadable`,
`glob-budget-exhausted`, `plugin-route-undecidable`. On a healthy host
with one missing compiled file that grammar printed
`43 of 44 verified reachable; 1 UNMEASURABLE (unmeasurable: ~/.claude —
ok)`, naming a perfectly healthy directory and the token `ok` as the
explanation of an unmeasurability it did not cause. The orchestrator's
§11 Q2 ruling required the note line for the **absent-dir** case;
generalising it bought a misleading line for the common case. Naming the
reasons satisfies the ruling and is strictly more informative.

**The r1 assertion was unimplementable and is replaced.** r1 required the
message to "not contain `reachable` as a verdict claim" while §4.4's own
mandated string contains the word `reachable` — a literal
`"reachable" not in msg` fails against the spec's required output. Tests
assert on **exact substrings** instead (§8, T-ROW-BLIND / T-ROW-MIXED):
the head with its two numbers, the `UNMEASURABLE` token with its count,
the resolved dir string, and the absence of the specific
looked-and-found-fine phrasing `"44 record(s) reachable"`.

**The dir string is asserted only in the `claude-dir-absent` /
`settings-unparseable` cases (r3-d NIT, closing this section).** The
previous paragraph's "the resolved dir string" is elliptical and must not
be read as "every test asserts the dir string is present": T-ROW-BLIND
(reason `claude-dir-absent`) asserts its **presence**; T-ROW-MIXED (reason
`target-missing`, no `claude-dir-absent`/`settings-unparseable` among the
distinct reasons) asserts its **absence** — that is the conditional half
of §4.4's grammar (M29), and both directions are load-bearing. A test
asserting the dir string unconditionally, in every fixture regardless of
which unmeasurable reason is present, would be wrong against this spec's
own grammar.

The difference between `0 of 44 verified reachable; 44 UNMEASURABLE (…)`
and `44 record(s) reachable` is the entire lesson of `lrn-ea833a5b`: an
instrument that cannot see its target must not produce the output of one
that looked and found everything fine.

### 4.4a The one reason-specific override

An `unmeasurable` whose reason is `settings-unparseable` **fails the row**
(table row 2). The instrument is present and broken, the remedy is "repair
the JSON", and `selfcheck.py:674` already rules verbatim that this
condition must be loud. This is the only reason-specific override, and
§5.5 pins the reason string.

**It is scoped per record, not globally (r1 M-A).** A settings fault fails
the row only through records whose predicate actually reads a settings
collection — `skill-md`, `new-skill`, `hook`. A `claude-md` or rules
record never consults `settings.json`, so it must not be dragged into
`unmeasurable` by a fault it does not depend on. §5.5 states the
per-facet rule; **T-FACET** proves the 32 live `claude-md` records stay
determined across a settings typo.

---

## 5. Per-destination predicates, the state enum, and the positive controls

### 5.0 The verdict type and the state enum — NORMATIVE

```python
@dataclass(frozen=True)
class Verdict:
    record_id: str          # "lrn-…"
    bucket: str             # bucket path relative to home, e.g. "skills/hypr-doctor"
    scope: str              # record.scope, verbatim
    destination: str        # "skill-md" | "new-skill" | "claude-md" | "hook"
    variant: str | None     # "rules" | "local" | None
    target: str | None      # the compiled file, or None when unresolvable
    state: str              # the enum below
    reason: str             # a stable machine token from the tables in §5.1-5.4
    detail: str             # one line of human text, may name paths
```

`state` is exactly one of:

| `state` | Means | Row effect |
|---|---|---|
| `reachable` | a session that opens this scope loads this file | — |
| `unreachable` | a session **cannot** load this file, and the cause is determined | FAIL |
| `unmeasurable` | the predicate **could not tell** — the instrument was absent, unreadable, or the route is undecidable | PASS + count (except `settings-unparseable`, §4.4) |

There is no fourth value and no `None`. Every code path in every predicate
must terminate in one of the three.

**The three binding rules on `unmeasurable`, each traceable to a lesson:**

- **R1 — "found nothing" from an unread instrument is `unmeasurable`,
  never `unreachable` and never `reachable`.** A predicate must
  *demonstrate* it read the instrument before it may return a determined
  verdict. Concretely: `skillOverrides`/`enabledPlugins`/`hooks` may only
  be consulted after `settings.json` was successfully parsed *or* proven
  absent-with-a-readable-parent. Cites `lrn-6d21607e`: a canary pointed at
  a plausible-but-wrong file reports "unchanged" on the run that destroyed
  the real one.
- **R2 — a missing target file is `unmeasurable`, reason
  `target-missing`, never `unreachable`.** Absence of the compiled file is
  `_check_drift`'s finding (`selfcheck.py:508-513`), already reported
  there with its own remedy (`self-learn recompile`). Re-reporting it as a
  reachability failure would double-count one defect and let a reader fix
  the wrong thing.
- **R3 — the reason token, not the boolean, is what tests assert.** Every
  test in §8 asserts on `state` and `reason`. No test may assert only that
  a row failed: a row that fails for the wrong reason is a check that
  cannot be trusted when it passes.

### 5.1 RP-SKILL — `skill-md` and `new-skill`

**Question:** is the compiled `SKILL.md` in a session's skill index?

**Target:** `managed_target_for(home, bucket, record)` (`verbs.py:798`).
The two legs resolve **differently**, and r1 got this wrong (N5):

- the `skill-md` leg (`verbs.py:842-846`) calls `skill_dir_for`, which
  **globs** `plugins/*/skills/<name>` under the skills root
  (`hosts.py:546-567`, raising on zero or ambiguous matches);
- the `new-skill` leg (`verbs.py:847-855`) uses the fixed formula
  `<skills_root>/plugins/<n>/skills/<n>/SKILL.md`.

They coincide for every live plugin on this host, but **not in the test
sandbox**: `support.py:159-160`'s `make_env` lays skills under
`plugins/<n>-plugin/skills/<n>`, so the glob leg finds them and the
formula leg does not. T-SKILL-6 therefore needs **two fixtures**, one per
leg. The skill name is `target.parent.name` either way, which is correct
for both.

#### 5.1A Plugin-root resolution — NORMATIVE (r1 B3)

r1 asserted "that plugin's `skills/<name>/SKILL.md`" without ever deriving
a plugin root, leaving the builder to invent a formula that would satisfy
a fixture and be wrong in production. It also gated on
`settings.json`'s `extraKnownMarketplaces`, which names only
**non-built-in** marketplaces — so with 33 of 34 `enabledPlugins` keys in
the `@claude-plugins-official` namespace, r1's rule 8 fired
unconditionally and rules 7 and 9 were dead in production. Both are fixed
by reading the right file.

**The instrument is `<claude_dir>/plugins/known_marketplaces.json`**, not
`extraKnownMarketplaces`. Verified on this host, 2026-08-23: it is a dict
keyed by marketplace name, and **every entry — the built-in one
included — carries an `installLocation` absolute path**:

```json
{"claude-plugins-official": {"source": {"source": "github",
   "repo": "anthropics/claude-plugins-official"},
  "installLocation": "<claude-dir>/plugins/marketplaces/claude-plugins-official"},
 "nsys-marketplace": {"source": {"source": "directory",
   "path": "<repos>/nsys-marketplace-local"},
  "installLocation": "<repos>/nsys-marketplace-local"}}
```

**The resolution, for an `enabledPlugins` key `"<plugin>@<marketplace>"`:**

1. `install = known_marketplaces[<marketplace>]["installLocation"]`.
   Missing key, missing field, or a path that is not a directory ⇒
   **undecidable for this record**.
2. Read `install/.claude-plugin/marketplace.json`; find the entry in its
   `plugins` list whose `name == <plugin>`. Unparseable, absent, or no
   matching entry ⇒ **undecidable for this record**.
3. That entry's `source`:
   - a **string** ⇒ a marketplace-root-relative path;
     `plugin_root = (install / source).resolve()`.
   - anything else (a git/github object) ⇒ **undecidable for this
     record**.
4. `plugin_root / "skills" / <name> / "SKILL.md"`.

**One formula covers every shape observed on this host**, which is why it
is specified rather than guessed. `nsys-marketplace` declares
`{"name": "znote", "source": "./"}` — the plugin root **is** the
marketplace root, skills at `<mkt>/skills/<n>`, and there is no `plugins/`
directory at all. The official marketplace declares `"./plugins/<name>"`
for most entries **and `"./external_plugins/<name>"` for 15 of them**
(measured 2026-08-23: 286 plugins, 53 string sources of which 15 are
`external_plugins`, 233 dict sources). The generic
"a string is a marketplace-root-relative path" rule covers all three
literal prefixes without naming any of them; a formula hard-coding
`plugins/` would have satisfied any fixture and been wrong for both
`znote` and every `external_plugins` entry.

#### 5.1A′ Undecidability is scoped to THIS target — NORMATIVE (r2 BLOCKER)

r1 B3 asked for per-record undecidability and r2's §5.1A prose promised
it, but §5.1B row 9 quantified over the **whole** `enabledPlugins` map.
**Measured on this host, 2026-08-23, reproducing the four steps above over
the live files: 28 of 34 entries decidable, 6 undecidable** — every one a
`{"source": "url", …}` dict under `claude-plugins-official`
(`atomic-agents`, `data-engineering`, `firecrawl`, `huggingface-skills`,
`remember`, `superpowers`). So an unnarrowed row 9 is **permanently true
on this host**, row 10 `not-indexed` is dead in production, and the single
failure mode RP-SKILL exists to catch — §2.2 establishes every
self-learn-hosted skill is indexed *purely* by a hand-made
`~/.claude/skills/<name>` symlink, so "the symlink is gone" is the whole
of it — returns `unmeasurable` and **PASSes the row where it must FAIL**.
That inverts §1's one-sentence contract. It is latent rather than live
only because all four live skills currently hit row 6.

**An undecidable entry is counted for a target only if it could plausibly
name that target.** Formally, entry `"<plugin>@<marketplace>"` is *in
scope for* `target` iff:

- `<plugin> == target.parent.name` (the skill name), **or**
- that marketplace's `installLocation` is `target` or one of its
  ancestors.

Entries failing both are ignored entirely by row 9 — not counted, not
reported, not mentioned in `detail`. **Verified this restores row 10 on
the live host:** none of the six undecidable plugin names matches a live
self-learn skill (`hypr-doctor`, `testing-methodology`, `chezmoi`,
`home-assistant`, `bitwarden-cli`), and neither `installLocation` is an
ancestor of the registered skills root.

The same in-scope test governs rows 7 and 8 by construction — a
*decidable* entry only matters when its resolved path equals `target`,
which is already a stronger relation than the two above.

#### 5.1B The algorithm — first row that applies decides

| # | Condition | `state` | `reason` |
|---|---|---|---|
| 1 | `target is None` | `unmeasurable` | `target-unresolvable` |
| 2 | `not target.is_file()` | `unmeasurable` | `target-missing` (R2) |
| 3 | the instrument's **claude-dir facet** is unusable (§5.5) | `unmeasurable` | `claude-dir-absent` |
| 4 | the instrument's **settings facet** is unusable (§5.5) | `unmeasurable` | `settings-unparseable` (fails the row, §4.4a) |
| 5 | `skillOverrides` has an `"off"` entry matching this skill (§5.1C) | **`unreachable`** | `skill-override-off` |
| 6 | `<claude_dir>/skills/<name>/SKILL.md` resolves to `target` | `reachable` | `personal-skill-link` |
| 7 | some `enabledPlugins` entry is `True` and resolves to `target` via §5.1A | `reachable` | `enabled-plugin` |
| 8 | some `enabledPlugins` entry is `False` and resolves to `target` via §5.1A | **`unreachable`** | `plugin-disabled` |
| 9 | ≥1 `enabledPlugins` entry **in scope for this target** (§5.1A′) was undecidable at any §5.1A step | `unmeasurable` | `plugin-route-undecidable` |
| 10 | otherwise | **`unreachable`** | `not-indexed` |

Rows 7–9 iterate the whole `enabledPlugins` map, but **row 9 counts only
in-scope entries (§5.1A′)**. A decidable match at 7 or 8 wins over an
in-scope undecidable entry at 9, because a positive resolution answers the
question regardless of what else was unreadable.

#### 5.1C `skillOverrides` key form (r1 N6)

Keys are **bare names for personal-symlink skills** and
**`<plugin>:<skill>` for plugin-provided ones** — verified on this host:
all four `"off"` entries are bare (`chezmoi`,
`universal-directory-organizer`, `qmk-zmk-animation-conversion`,
`obsidian-plugin-dev`), all four are symlinked personal skills, and the
session's own skill listing shows plugin skills namespaced
(`znote:brainstorming`). Rule 5 therefore matches **either**
`skillOverrides.get(name) == "off"` **or**
`skillOverrides.get(f"{plugin}:{name}") == "off"` when §5.1A resolved a
plugin for this target. **T-SKILL-8** covers the namespaced form.

**Symlink semantics (row 6):** use `Path.exists()` / `.resolve()`, which
follow symlinks, so a **dangling** `<claude_dir>/skills/<name>` reads as
absent → row 10 `not-indexed`, not `reachable`. This mirrors the comment
already in the tree at `selfcheck.py:790-791`. **T-SKILL-3** pins it.

**POSITIVE CONTROL (T-SKILL-BLIND):** a fixture whose `claude_dir` does
not exist, holding a live `skill-md` record with a compiled, present
`SKILL.md`, must yield `unmeasurable` / `claude-dir-absent` — never
`reachable`, and never `not-indexed` (a determined verdict reached without
reading the instrument, an R1 violation). The fixture must additionally
**assert `claude_dir` does not exist**, so the test cannot pass by
accident on a machine where it does.

**Evidence for row 5:** §2.2 — 4 of 4 `skillOverrides: "off"` entries are
absent from the authoring session's available-skills listing while their
symlinks and files are intact.

### 5.2 RP-CMD — `claude-md`, plain and `local` variants

**Question:** is the compiled file at a path the loader scans for the
scope that record belongs to?

**Targets** (`managed_target_for`, `verbs.py:856-887`), all resolved with
the `user_claude_md` override of §4.3: user → `<claude_dir>/CLAUDE.md`;
project → `<host>/CLAUDE.md`; `variant: "local"` →
`<host>/CLAUDE.local.md`; skill-scope → `<skills_root>/CLAUDE.md`.

**r1's rule 4 is DELETED (r1 B2).** It claimed a divergence between
`DEFAULT_USER_CLAUDE_MD` and `claude_runtime_dir()` and called it "a real,
currently-invisible divergence, not a hypothetical". **Measured: it is the
inverse.** `DEFAULT_USER_CLAUDE_MD = Path("~/.claude/CLAUDE.md")`
(`verbs.py:180`) and `claude_runtime_dir()` returns
`$SELF_LEARN_CLAUDE_DIR` or `~/.claude` (`selfcheck.py:664-668`, whose
docstring labels the variable "(tests)"). Absent that variable the two are
**the same expression by construction**, so the check could never fire on
a real host; with it set — every sandboxed test — it always fires. The
only other handle is an internal chezmoi passthrough with no user-facing
flag (`cli.py:895-914`, whose own docstring says "there is no CLI flag for
it"). A criterion that is vacuous in production and tautological in test
is worse than absent.

**And §4.3's B1 fix makes it structurally impossible:** the user-scope
target is now *derived from* `claude_dir`, so target and runtime dir
cannot differ. `user-claude-md-off-runtime-dir`, **T-CMD-2 and M21 are
removed from this spec.** No replacement criterion is invented; the
question r1 was reaching for — "is the operator compiling into a file
their Claude Code does not read?" — has no static handle in this codebase
and is recorded as such in §11 Q5.

| # | Condition | `state` | `reason` |
|---|---|---|---|
| 1 | `target is None` | `unmeasurable` | `target-unresolvable` |
| 2 | **user scope**, claude-dir facet unusable (§5.5) | `unmeasurable` | `claude-dir-absent` |
| 3 | `not target.is_file()` | `unmeasurable` | `target-missing` |
| 4 | **user scope**, target is `<claude_dir>/CLAUDE.md` | `reachable` | `user-memory-file` |
| 5 | **project/skill scope**, target's parent directory does not exist | `unmeasurable` | `host-missing` |
| 6 | **project/skill scope**, `target.parent` is the registered host root and the basename is `CLAUDE.md` | `reachable` | `project-root-memory-file` |
| 7 | **project/skill scope**, basename is `CLAUDE.local.md` at the host root | `reachable` | `project-local-memory-file` |
| 8 | otherwise | **`unreachable`** | `not-on-a-loaded-path` |

**Row ordering changed from r1 (B1 consequence).** The claude-dir facet
check now precedes `target-missing` for user scope. r1 had it the other
way, which meant T-CMD-BLIND passed only because the operator's real
`~/.claude/CLAUDE.md` happens to exist — a decoy making the fixture pass
for the wrong reason, `lrn-6d21607e` inside the control built to exclude
it. With the override threaded, the sandbox target genuinely does not
exist, so the ordering is what makes `claude-dir-absent` reachable at all.

**This predicate reads no settings collection**, so a
`settings-unparseable` fault must not touch it (§5.5, §4.4a). 32 of the 62
live records route here (29 plain + 3 rules); blanking them for a JSON
typo they never read was r1's M-A.

**DISCLOSED residual on rows 6 and 7 — the honest limit of a static
check.** Row 6 proves the file is *where the loader looks*, not that any
session ever opens that project. Whether a registered host is ever a
session's cwd is not statically knowable, and the `detail` string for
`project-root-memory-file` must say so in words. This is deliberately
**not** modelled as `unmeasurable`: the question the predicate asks ("is
it on a loaded path?") *was* answered; a different, unaskable question was
not. Conflating them would make the 8 non-user-scope live `claude-md`
records permanently unmeasurable and destroy the signal. (r1 said "30 of
the 62"; the measured non-user-scope `claude-md` count is **8** — N2.)

Row 7 additionally carries the older draft's §6 finding that
`CLAUDE.local.md` is git-excluded by design and therefore less durable
than the thing it may point at — stated in `detail`, not as a failure.

**POSITIVE CONTROL (T-CMD-BLIND):** live user-scope `claude-md` record,
`claude_dir` a non-existent path. The fixture asserts **both** that
`claude_dir` does not exist **and** that the resolved target does not
exist, then asserts `unmeasurable` / `claude-dir-absent`. Both assertions
are required: without the second, the test would again be passing on a
decoy rather than on the ordering it exists to pin.

### 5.3 RP-RULES — `claude-md`, `variant: "rules"`

**Question:** does the rules file, **as it exists on disk**, load — and
does its frontmatter still say what the ledger thinks it says?

**Targets:** user → `_user_rules_dir(user_claude_md) / f"{topic}.md"`
(`verbs.py:772-777`); project → `<host>/.claude/rules/<topic>.md`
(`verbs.py:779-780`). Both use §4.3's threaded `user_claude_md`, never
`DEFAULT_USER_CLAUDE_MD`.

This predicate is the one that **reads the compiled file**, because §2.3
established that U-glob's drift-side check reads `routing.rules_paths`
(`selfcheck.py:549`) and the loader reads frontmatter.

**Algorithm:**

1. `target is None` ⇒ `unmeasurable` / `target-unresolvable`. For user
   scope, the claude-dir facet is checked **before** file existence, for
   the §5.2 reason ⇒ `unmeasurable` / `claude-dir-absent`. Then
   `not target.is_file()` ⇒ `unmeasurable` / `target-missing`.
2. **Directory identity.** The target's parent must be the rules
   directory the loader scans for that scope — `claude_dir / "rules"` for
   user scope, `<host>/.claude/rules` for project scope. Otherwise
   **`unreachable`** / `rules-dir-off-loaded-path`.
3. **The ratified zero-match bypass — checked here, before any glob
   probe (r1 M-D).** `_check_drift` exempts a record whose
   `routing.glob_bypass_reason == "zero-match"`, and a legacy record with
   `allow_empty_glob is True` and no `glob_bypass_reason` key
   (`selfcheck.py:550-555`). That is the **approved** write-the-rule-first
   route the router deliberately offers (`verbs.py:948-952`). r1 had no branch
   for it, so such a record would have become `unreachable` /
   `globs-match-nothing` ⇒ row FAIL ⇒ `--selftest` rc 1 for a state the
   router approved. **An exempt record short-circuits to `reachable` /
   `bypass-approved`**, with `detail` naming the bypass reason. A
   `"budget"` bypass is **not** exempt — U-glob §6.6's rule, kept
   verbatim: a transient timeout must never buy a permanent exemption.
   Verified no live subject today (all 3 live rules records carry no
   bypass) — exactly the condition under which an omission ships
   unnoticed. **T-RULES-BYPASS** and **M25** pin it.
4. **Read the frontmatter.** `UnicodeDecodeError` or unparseable YAML ⇒
   `unmeasurable` / `frontmatter-unreadable`. Never `reachable`.
5. **No `paths:` key at all** ⇒ `reachable` / `loads-unconditionally`,
   with `detail` noting the rule loads at `session_start` regardless of
   any glob — **evidenced**, not assumed: U-glob §8.1A's recorded log
   shows `canary-unpathed.md` loading with
   `"load_reason":"session_start"`. Over-broad, not unreachable; this unit
   reports it without judging it.
6. **`paths:` present.** Probe **the file's own patterns** with
   `glob_reaches(roots, p)` (`ledger_ops.py:819`), `roots` from
   `_user_reachability_roots(home, user_claude_md)` (`verbs.py:892`) for
   user scope — **the threaded override, so a sandbox globs the sandbox
   and not the operator's `$HOME`** — and `(host,)` for project scope.
   - every pattern `"none"` ⇒ **`unreachable`** / `globs-match-nothing`
   - any pattern returns `"budget"` and none matched ⇒ `unmeasurable` /
     `glob-budget-exhausted`. **U-glob §6.6's ratified asymmetry**: a
     cold-cache timeout (17.95 s cold vs 3.7 s warm) is never a
     determination. U-glob's drift side *skips* it silently; this unit
     *counts* it as unmeasurable — strictly louder, same refusal to
     convict.
   - otherwise ⇒ `reachable` / `globs-match`
7. **Frontmatter drift is reported alongside, never instead.** When the
   file's `paths:` list differs from `routing.rules_paths`, `detail` names
   both lists. The `state` is whatever step 5/6 decided from the **disk**
   patterns. A drifted-but-still-matching rule is `reachable` with a drift
   note; a drifted-and-non-matching rule is `unreachable`. The ledger's
   copy never decides the verdict.

**This predicate reads no settings collection** — same §5.5/§4.4a
exclusion as RP-CMD.

**POSITIVE CONTROL (T-RULES-DISK)** *(the mutation-catcher)*: a record
whose `routing.rules_paths` is `["**/*.md"]` (matches abundantly)
compiled into a file whose frontmatter says
`paths: ["**/no-such-file-zzqx-*.xyz"]` (matches nothing) **must** yield
`unreachable` / `globs-match-nothing`. An implementation that reads the
ledger returns `reachable` and this test is the only thing in the suite
that notices. The nonsense glob is taken deliberately from U-glob §8.1A's
preserved negative control, whose subject-preservation rule this fixture
also honours by writing the file rather than asserting its absence.

**POSITIVE CONTROL (T-RULES-BLIND):** user-scope rules record with
`claude_dir` absent. The fixture asserts `claude_dir` does not exist and
that the resolved rules target does not exist, then asserts
`unmeasurable` / `claude-dir-absent` — **not** `target-missing`, which is
what r1 would actually have produced (its step 1 ordering put file
existence first, and its target resolved to the operator's real
`~/.claude/rules/<topic>.md`, absent for any fixture topic).

### 5.4 RP-HOOK — `hook`

**Question:** is this live hook record's script actually **registered**,
for the right event, with a matcher that covers the tools it guards?

`routing.hook` carries `tools`, `path_regex`, `deny_message`,
`script_path` (`ledger_ops.py:524`, `:543-563`; confirmed against
`lrn-dd9489b2`'s stored block). There is no `event` key: every generated
guard is a `PreToolUse` guard, which its own header states.

**Algorithm:**

| # | Condition | `state` | `reason` |
|---|---|---|---|
| 1 | `routing.hook.script_path` absent, or skills root unresolvable | `unmeasurable` | `target-unresolvable` |
| 2 | the script file is missing | `unmeasurable` | `target-missing` (R2 — `_check_hooks` owns it, `selfcheck.py:754-758`) |
| 3 | claude-dir facet unusable (§5.5) | `unmeasurable` | `claude-dir-absent` |
| 4 | settings facet unusable (§5.5) | `unmeasurable` | `settings-unparseable` — **and this one FAILS the row** (§4.4a) |
| 5 | `settings.json` absent, `claude_dir` present | **`unreachable`** | `no-registrations` |
| 6 | no `PreToolUse` registration whose command basename equals the script's basename | **`unreachable`** | `not-registered` |
| 7 | a registration exists but only under a non-`PreToolUse` event | **`unreachable`** | `wrong-event` |
| 8 | the matcher is not a valid regex | `unmeasurable` | `matcher-unparseable` |
| 9 | the matcher does not cover every tool in `routing.hook.tools` | **`unreachable`** | `matcher-mismatch` |
| 10 | otherwise | `reachable` | `registered` |

**Matcher coverage (rules 8–9), NORMATIVE:** matcher `m` covers tool `t`
iff `m in ("", "*")` or `re.fullmatch(m, t)` matches. `re.error` ⇒ rule 8.
Rule 8 exists because a broken matcher is an unknown, not a mismatch —
R1 again, in the smallest possible place.

**This predicate is the third loop `_check_hooks` does not have** (§2.4).
It must not be added to `_check_hooks`: that function is not in this
unit's footprint, and folding a new fact into an existing row would let
one mask the other — the concern `_check_reach`'s docstring
(`selfcheck.py:288-296`) states explicitly.

**POSITIVE CONTROL (T-HOOK-UNREG):** the live-shaped fixture — a routed
hook record, script present, executable, byte-identical to
`routing.hook.script`, symlinked into `<claude_dir>/hooks/`, and a
`settings.json` that parses and registers **a different** hook. The
assertion is two-sided and both sides are required:

1. `reachability_rows` returns `unreachable` / `not-registered`, **and**
2. `selfcheck._check_hooks(home, claude_dir)` on the same fixture returns
   `(True, …)`.

Assertion 2 is what makes assertion 1 mean something: it demonstrates the
new check catches a state the existing suite calls healthy. Without it the
test proves only that new code runs.

**POSITIVE CONTROL (T-HOOK-BLIND):** same fixture, `claude_dir` absent ⇒
`unmeasurable` / `claude-dir-absent`, row PASSes with the count.

**POSITIVE CONTROL (T-HOOK-BROKEN):** same fixture, `settings.json`
containing `{` ⇒ `unmeasurable` / `settings-unparseable`, and the row
**FAILs**. This is the 2026-08-23 incident (§2.6) turned into a fixture.

### 5.5 The instrument reader — per-facet usability (r1 M-A)

```python
@dataclass(frozen=True)
class Instrument:
    state: str                  # ok | claude-dir-absent | settings-absent | settings-unparseable
    claude_dir_usable: bool     # facet 1: the runtime dir exists and is a directory
    settings_usable: bool       # facet 2: settings.json parsed, or is absent by design
    claude_dir: Path
    enabled_plugins: dict[str, bool]
    skill_overrides: dict[str, str]
    marketplaces: dict[str, str]          # name -> installLocation (§5.1A)
    hook_registrations: tuple[tuple[str, str, str], ...]   # (event, matcher, command)
    problem: str | None         # the exception text, when a facet is unusable

def read_instrument(claude_dir: Path) -> Instrument: ...
```

Called **once** per `reachability_rows` call; predicates receive the
result and never open `settings.json` themselves.

**Two facets, not one blanket flag.** r1 made `settings-unparseable`
globally "unusable" and said any predicate handed an unusable instrument
"may only return `unmeasurable`" — which would blank all **32** live
`claude-md` records (29 plain + 3 rules, measured) for a fault they never
read, and then FAIL the row on that basis via §4.4a. Usability is stated
per facet, and each predicate declares which facets it depends on:

| Predicate | claude-dir facet | settings facet |
|---|---|---|
| RP-SKILL | required | required |
| RP-HOOK | required | required |
| RP-CMD (user scope) | required | **not read** |
| RP-CMD (project/skill scope) | **not read** | **not read** |
| RP-RULES (user scope) | required | **not read** |
| RP-RULES (project scope) | **not read** | **not read** |

A predicate may consult only the collections its declared facets cover. A
gate reviewer finding RP-CMD branch on `settings_usable` must treat it as
a defect.

**The four states and what each facet is:**

| `state` | `claude_dir_usable` | `settings_usable` | Meaning |
|---|---|---|---|
| `ok` | `True` | `True` | dir present, settings parsed |
| `settings-absent` | `True` | `True` | dir present, no settings.json — a **determinable** state: no registrations exist, no skill is overridden off |
| `claude-dir-absent` | `False` | `False` | the runtime dir does not exist or is not a directory |
| `settings-unparseable` | `True` | `False` | present and broken; carries `problem`; fails the row through settings-dependent records only (§4.4a) |

**Rules:**

- A predicate handed an **unusable required facet** may only return
  `unmeasurable` (R1), with the reason naming that facet
  (`claude-dir-absent` / `settings-unparseable`).
- `settings.json` absent while the dir is present ⇒ `settings-absent`,
  collections empty and **usable**. RP-HOOK turns that into a
  *determination* (`no-registrations`, §5.4 row 5), which is why it must
  not be folded into `claude-dir-absent`.
- Any `OSError` or `ValueError` reading `settings.json` ⇒
  `settings-unparseable` with the message. Never an exception out of
  `reachability_rows`: a check that crashes reports nothing.
- `known_marketplaces.json` (§5.1A) sits under
  `<claude_dir>/plugins/`. It is read on the **claude-dir facet**, and a
  read failure there does **not** set `settings-unparseable` — it leaves
  `marketplaces` empty, which §5.1A turns into per-record
  `plugin-route-undecidable`. Two different files, two different
  remedies.
- The existing `_registered_hook_commands` (`selfcheck.py:671-681`)
  discards `matcher` and `event`, which this unit needs, so
  `read_instrument` reads the file itself. It **must not** modify
  `_registered_hook_commands` — out of footprint.

**POSITIVE CONTROL (T-INSTRUMENT):** all four states constructible by
fixture; the facet pair matches the table above for each; no dangling enum
member (the same requirement U-readref §6.3 placed on `instrument_state`).

**POSITIVE CONTROL (T-FACET):** a home with live `claude-md` and rules
records **and** a `settings.json` containing `{`. Every `claude-md` and
rules row must be **determined** (`reachable` / `unreachable`), not
`unmeasurable`; only the settings-dependent destinations go
`settings-unparseable`. This is the test that would have caught r1's
blanket rule.

### 5.6 The domain — which records are in scope

Every bucket `discover_buckets(home)` returns — `skills/*`, `projects/*`,
**and the single one-level `user/` bucket** — never a `<home>/*/*/resolved/`
glob. This is stated verbatim in `_check_reach`'s docstring
(`selfcheck.py:296-302`) as criterion 9a, and the reason is that a
two-level glob silently misses `user/resolved/` while reporting success.
**31 of the 62 live records are in the `user/` bucket** (53 files in
`user/resolved`, 31 of them live routed — r1 said 35, N1; the domain-glob
argument is unaffected), so this unit inherits that trap in full.

In-domain: `status == "routed"`, `superseded_by is None`, and
`destination in ("skill-md", "claude-md", "new-skill", "hook")`.
Explicitly **not** in-domain: `reference` (§3, §9.1).

A resolved record file that fails to parse (`RecordError`,
`UnicodeDecodeError`) is skipped exactly as `_check_reach`
(`selfcheck.py:336-339`) and `_check_drift` skip it — its routing is
unknown, so it can be placed neither in nor out of the domain. **The skip
must be counted and surfaced** in the facts block as `unparseable_records`
so it is never a silent narrowing.

**POSITIVE CONTROL (T-DOMAIN-USER):** a fixture with a live in-domain
record in `user/resolved/` only. If the implementation globs `*/*/resolved`
the list comes back empty and the row prints a PASS over zero records —
the exact fail-open shape. The test asserts the row's count is 1.

---

## 6. Report fields — the `surface_reach` facts block

`report.py::gather` gains one top-level key beside `reference_shelf`
(`:668`):

```json
"surface_reach": {
  "instrument_state": "ok",
  "claude_dir_usable": true,
  "settings_usable": true,
  "checked": 44,
  "reachable": 41,
  "unreachable": 1,
  "unmeasurable": 2,
  "unparseable_records": 0,
  "by_destination": {
    "skill-md":         {"reachable": 4,  "unreachable": 0, "unmeasurable": 0},
    "new-skill":        {"reachable": 4,  "unreachable": 0, "unmeasurable": 0},
    "claude-md":        {"reachable": 27, "unreachable": 0, "unmeasurable": 2},
    "claude-md:local":  {"reachable": 0,  "unreachable": 0, "unmeasurable": 0},
    "claude-md:rules":  {"reachable": 3,  "unreachable": 0, "unmeasurable": 0},
    "hook":             {"reachable": 3,  "unreachable": 1, "unmeasurable": 0}
  },
  "rows": [
    {
      "record_id": "lrn-example1",
      "bucket": "skills/example",
      "scope": "skill:example",
      "destination": "hook",
      "variant": null,
      "target": "<skills-root>/plugins/example/hooks/self-learn-example1-….sh",
      "state": "unreachable",
      "reason": "not-registered",
      "detail": "no PreToolUse registration in settings.json names this script"
    }
  ]
}
```

*(The illustrative row uses a placeholder id — r2 n3. r2 showed
`lrn-38514455` as `not-registered`, but that hook **is** registered live
(`PreToolUse`, `matcher: "Bash"`), which §2.4 itself states. A
counterfactual example must not name a record whose real verdict is the
opposite.)*

**Rules:**

1. **`rows` is ordered `unreachable` first, then `unmeasurable`, then
   `reachable`; within a state, by `destination` then `record_id`.** The
   signal leads; it is never buried. (U-readref §6.2 rule 5, same reason.)
2. **Nulling is PER FACET, never blanket (r2 MAJOR 1).** The block carries
   the §5.5 facet pair — `claude_dir_usable` and `settings_usable` — and
   **not** a single `instrument_usable` flag, which §5.5's facet split
   deleted and which r2 left behind here, defined nowhere. A count is
   `null` (never `0`) exactly when a facet **that count depends on** is
   unusable:

   | Count | Nulled when |
   |---|---|
   | `by_destination["skill-md"]`, `["new-skill"]`, `["hook"]` sub-counts | `claude_dir_usable` **or** `settings_usable` is false |
   | `by_destination["claude-md"]`, `["claude-md:local"]`, `["claude-md:rules"]` sub-counts | `claude_dir_usable` is false (user-scope rows depend on it); **never** on `settings_usable` alone |
   | top-level `reachable` / `unreachable` | either facet is false — they aggregate across destinations, so they inherit the weaker guarantee |

   `checked`, `unmeasurable`, `unparseable_records` and `rows` always
   render: the ledger side is known regardless. **A blanket
   `instrument_usable` would null the 32 live `claude-md` counts on a
   `settings.json` typo** — the exact r1 M-A blanking reappearing one
   layer down in the renderer, with T-RENDER-NULL locking it in. The
   underlying rule is U-readref §6.3's, applied per facet: a `0` in
   `unreachable` on an unmeasured host is indistinguishable from a clean
   bill of health.
3. **The text render says `NOT MEASURED`, in those words**, for each
   nulled group, and names `instrument_state` so the remedy is visible. It
   must never print a bare zero for an unmeasured count.
4. **`rows` carries every in-domain record, including `reachable` ones.**
   A consumer must be able to tell "checked and fine" from "not in the
   list" — a block that lists only failures cannot distinguish a healthy
   ledger from a predicate that returned nothing.
5. **`by_destination` is keyed by destination AND variant (Q3, RULED by
   the gate).** Keys: `skill-md`, `new-skill`, `hook`, `claude-md`,
   `claude-md:local`, `claude-md:rules`. **Rationale, adopted verbatim:**
   the three `claude-md` shapes are answered by **two different
   predicates** (RP-CMD vs RP-RULES) with disjoint reason sets and
   disjoint remedies — a `rules` failure is `globs-match-nothing` (the
   human retargets the glob) or `rules-dir-off-loaded-path`; a plain
   `claude-md` failure is `not-on-a-loaded-path` (a host/compile problem).
   `by_destination` exists to route attention *before* a reader opens
   `rows`, and a merged `claude-md` count is the one number that cannot
   tell those two apart. It costs no new computation and does not touch
   §4.3: `variant` is already a `Verdict` field, so this is a group-by
   over the returned list — exactly the "counting must be a count over the
   returned list" that rule permits. The live shape (29 plain / 3 rules /
   0 local) is not sparse noise. Every key is always present, including
   zero-count ones, so a missing destination never reads as a clean one.
6. `target` is rendered with the skills root and the home elided to
   `<skills-root>` / `<home>` placeholders, matching the elision the older
   draft used for the same reason (this repo is public and the report is
   quotable).
7. `gather`'s signature gains `claude_dir: Path | None = None`,
   defaulting to `selfcheck.claude_runtime_dir()`, and threads it (plus
   the `user_claude_md` derived from it, §4.3) into `_surface_reach`. It
   is **passed in**, never re-derived inside `_surface_reach`, for the
   same reason U-readref passes `flush_state` (`report.py:519-525`): a
   function that silently reaches for the operator's real `~/.claude` from
   inside a sandboxed test aims the check at the wrong machine.
   *(r1 M-G: the default IS a re-derivation, and since
   `claude_runtime_dir()` honours `SELF_LEARN_CLAUDE_DIR` it is a
   sandbox-safe one — so "gather re-derives internally" was never a
   killable mutation. M20 is restated in §10 as the mutation that
   actually breaks: `_surface_reach` **ignoring** the passed value, or
   resolving `Path("~/.claude")` directly.)*

---

## 7. The live-session probe — OPT-IN, operator-only, never run by selfcheck

The static predicates in §5 are a **model of the loader**, not the loader.
U-glob §8 ratified the only instrument that observes the loader directly:
the `InstructionsLoaded` hook, registered for one session via a temp
`--settings` file, whose stdin JSON carries `file_path`, `load_reason`,
`globs`, `trigger_file_path`, `memory_type` (U-glob §8.1A; recorded
evidence at `misc/u-glob-loader-check/probe-full-2026-08-23/EVIDENCE.md`,
with `il.log`, `il-hook.sh`, `settings.json` and the preserved `canaries/`
beside it).

**This unit does not run it, ever, from any default path.** Reasons, in
order: it costs a real model session; it registers a hook; `selfcheck` is
specified read-only and a probe that starts a session is not read-only;
and a nightly job that spawns headless sessions is a surprise the operator
did not ask for.

**What this unit adds instead is a documented operator procedure**, in
this spec only — **no new CLI verb, no new flag** (§9.6):

**PROBE-A — calibrating RP-RULES.** Exactly U-glob §8's harness,
unmodified, run against a rules file this unit reported `reachable` or
`unreachable`. The verdict is `load_reason`: `path_glob_match` confirms a
`globs-match` verdict; absence from the log across a session that read a
matching file contradicts it. U-glob §8.0's binding constraints carry over
verbatim — **the prompt must be the first positional argument** (a
variadic `--allowedTools` swallows it, and the run then dies with an empty
stdout while the hook still writes its `session_start` entries, so the
probe passes on a session that never executed), and **`< /dev/null`** must
close stdin.

**PROBE-B — calibrating RP-SKILL.** `InstructionsLoaded` does **not** fire
for skills; it fires for instruction files. There is no CLI enumeration of
the skill index either — `claude --help`'s command list
(`agents`, `auth`, `auto-mode`, `doctor`, `gateway`, `import`, `install`,
`mcp`, `plugin`, `project`, `setup-token`, `ultrareview`, `update`) has no
skills verb, checked 2026-08-23. So the probe is necessarily
model-mediated: a headless session asked to report whether a named skill
appears in its available-skills listing.

**Because that answer passes through a model, it is worthless without a
negative control in the same session.** The procedure is therefore fixed:
ask about a skill expected present **and** a skill expected absent, in one
prompt, and accept the result only when both match expectation. On this
host the standing negative control is a `skillOverrides: "off"` skill
(§2.2) — present on disk, symlinked, and absent from the index. A run that
reports the off-skill as available has told you the probe is unreliable,
not that the skill is reachable.

**PROBE-C — calibrating RP-HOOK.** No session needed: register the guard,
invoke the guarded tool with input the `path_regex` matches, observe the
deny. Cheapest of the three and the only one with a deterministic oracle.

Whatever an operator runs, the output belongs in `misc/`, not `/tmp` —
`misc/` is git-ignored and durable, and a probe result that survives one
reboot is the difference between evidence and an anecdote
(`lrn-74d0b52b`).

---

## 8. Tests — enumerated

New file `plugins/self-learn/cli/tests/test_reachability.py`. Fixtures
build on `tests/support.py::make_env` (`:147-175`), which lays out a host
repo + a ledger home with `hosts.yaml`. **Every test sets
`SELF_LEARN_CLAUDE_DIR` explicitly** — `tests/conftest.py:94-96` points it at
`tmp_path / "claude-dir-default"`, a directory that is never created, so a
test that forgets is silently testing the `claude-dir-absent` path.

A shared helper builds the instrument:

```python
def make_claude_dir(tmp_path, *, settings: dict | str | None = ...,
                    skills: dict[str, Path] | None = None,
                    hooks: dict[str, Path] | None = None) -> Path
```

`settings=None` writes no file (`settings-absent`); a `str` is written
raw (for the unparseable fixture); a `dict` is JSON-dumped. **The `...`
default (r1 N8) means "write a minimal valid `{}`"** — distinct from
`None`, and the default for fixtures that care about some other facet.
`make_claude_dir` also accepts `marketplaces: dict[str, Path] | None` and
writes `plugins/known_marketplaces.json` from it (§5.1A); omitted ⇒ no
such file ⇒ `marketplaces` empty.

### The blind-fixture set — one per predicate, all four required

**Every blind fixture asserts its own preconditions before its verdict
(r1 B1).** Each must assert that `claude_dir` does not exist **and** that
the resolved target does not exist. Without the second assertion a fixture
can pass on a decoy — r1's T-CMD-BLIND passed only because the operator's
real `~/.claude/CLAUDE.md` exists, which is `lrn-6d21607e` inside the
control built to exclude it.

| ID | Fixture | Asserts |
|---|---|---|
| **T-SKILL-BLIND** | live `skill-md` record, compiled `SKILL.md` present, `claude_dir` a non-existent path | `unmeasurable` / `claude-dir-absent`; never `reachable`, never `not-indexed` |
| **T-CMD-BLIND** | live user `claude-md`, `claude_dir` absent, target derived from it (so absent too) | `unmeasurable` / `claude-dir-absent`; never `target-missing` — the §5.2 row ordering is what this pins |
| **T-RULES-BLIND** | live user rules record, `claude_dir` absent | `unmeasurable` / `claude-dir-absent`; never `target-missing` |
| **T-HOOK-BLIND** | live hook record, script + symlink perfect, `claude_dir` absent | `unmeasurable` / `claude-dir-absent` |
| **T-ROW-BLIND** | all four above in one home, `claude_dir` absent | see the exact-substring assertions below |
| **T-ROW-MIXED** | two `reachable` + two `unmeasurable` in one home | see below |

**T-ROW-BLIND and T-ROW-MIXED assert exact substrings, not word absence
(r1 M-B).** r1 required the message to "not contain `reachable` as a
verdict claim", which is unimplementable against §4.4's own mandated
string. The assertions are:

*T-ROW-BLIND* — `_check_surface` returns `(True, msg)` and:
1. `"0 of 4 verified reachable" in msg`
2. `"4 UNMEASURABLE" in msg`
3. `"claude-dir-absent" in msg` **and** `str(claude_dir) in msg` — the
   reason and the **resolved** sandbox path, which is what makes the
   orchestrator's §11 Q2 note-line ruling testable (r1 M-C: nothing
   asserted it, so it could be dropped with a green suite)
4. `"UNREACHABLE" not in msg`
5. `"4 record(s) reachable" not in msg` — the specific
   looked-and-found-fine phrasing

*T-ROW-MIXED* — the realistic shape r1 never tested, and the reason M3 was
weak: a mutation dropping the count when `reachable > 0` survived r1's
suite because only the all-blind row exercised the count. **The fixture is
pinned to a NON-instrument unmeasurable reason (r2 MAJOR 2)** — a present,
usable `claude_dir` with two `reachable` records and two whose compiled
targets are missing (`target-missing`). Asserts `(True, …)` and:
1. `"2 of 4 verified reachable" in msg`
2. `"2 UNMEASURABLE" in msg`
3. `"target-missing" in msg`
4. `str(claude_dir) not in msg` — the conditional half of the grammar,
   which nothing else in the suite exercises
5. `"claude-dir-absent" not in msg`

T-ROW-BLIND remains the single most important test in the unit: the string
a can't-see run prints must not be the string a looked-and-found-fine run
prints (`lrn-ea833a5b`).

### RP-SKILL

- **T-SKILL-1** `~/.claude/skills/<n>` symlink to the compiled skill dir ⇒
  `reachable` / `personal-skill-link`.
- **T-SKILL-2** `skillOverrides: {"<n>": "off"}` with that symlink intact
  ⇒ `unreachable` / `skill-override-off`. Proves the override wins over a
  working discovery route.
- **T-SKILL-3** `~/.claude/skills/<n>` is a **dangling** symlink ⇒
  `unreachable` / `not-indexed`. Proves `exists()`-follows-symlinks
  semantics.
- **T-SKILL-4** `enabledPlugins: {"<p>@<mkt>": false}`, with a fixture
  `known_marketplaces.json` naming `<mkt>`'s `installLocation` and a
  `marketplace.json` whose entry for `<p>` has `"source": "./plugins/<p>"`
  ⇒ `unreachable` / `plugin-disabled`.
- **T-SKILL-4b** the **`"source": "./"` shape** — plugin root IS the
  marketplace root, skills at `<mkt>/skills/<n>`, no `plugins/` dir. This
  is the live `znote@nsys-marketplace` layout (§5.1A) and the fixture that
  kills a formula hard-coding `plugins/`.
- **T-SKILL-5** an `enabledPlugins` entry whose marketplace has no
  `installLocation`, or whose `source` is a github object, and no personal
  symlink ⇒ `unmeasurable` / `plugin-route-undecidable`. **Not**
  `not-indexed`. Row 9's only exercise.
- **T-SKILL-5b** the same undecidable entry **plus** a working personal
  symlink for the target ⇒ `reachable` / `personal-skill-link`. Proves an
  undecidable entry cannot be hoisted above row 6.
- **T-SKILL-5c** *(r2 BLOCKER — the test r2 lacked)* an undecidable entry
  that is **out of scope for the target** (§5.1A′: its `<plugin>` is not
  the skill name, and its marketplace's `installLocation` is not an
  ancestor of `target`) **and NO personal symlink** ⇒ **`unreachable` /
  `not-indexed`**. This is the live-host shape — 6 of 34 entries are
  `{"source": "url", …}` dicts — and the single failure mode RP-SKILL
  exists to catch (§2.2: every self-learn skill is indexed purely by a
  hand-made symlink). Without the §5.1A′ narrowing this returns
  `unmeasurable` and the row PASSes where it must FAIL. T-SKILL-5b cannot
  substitute: row 6 short-circuits there, so it never reaches row 9/10.
- **T-SKILL-5d** an undecidable entry **in scope** by the name rule
  (`<plugin> == target.parent.name`), no symlink ⇒ `unmeasurable` /
  `plugin-route-undecidable`. The other side of §5.1A′, so the narrowing
  cannot be mutated into "ignore undecidability entirely". **Second leg**
  *(r3-c NIT)*: an undecidable entry whose `<plugin>` name does **not**
  match the skill name, but whose marketplace's `installLocation` **is an
  ancestor of** `target`, no symlink ⇒ `unmeasurable` /
  `plugin-route-undecidable`. §5.1A′ states two disjuncts (name-match OR
  ancestor-installLocation) and leg 1 alone only exercises the first — a
  formula that dropped the ancestor disjunct entirely would still pass leg
  1. M6i is this leg's mutation.
- **T-SKILL-6** `new-skill` record ⇒ same verdicts via the fixed
  `<root>/plugins/<n>/skills/<n>/SKILL.md` formula.
- **T-SKILL-6b** `skill-md` record in a sandbox laid out as
  `support.py:159-160` does it (`plugins/<n>-plugin/skills/<n>`) ⇒
  resolved by `skill_dir_for`'s **glob**, not the formula. Two fixtures
  because the two legs genuinely differ in the sandbox (r1 N5).
- **T-SKILL-8** `skillOverrides` keyed `"<plugin>:<skill>"` for a
  plugin-resolved target ⇒ `unreachable` / `skill-override-off` (r1 N6).
- **T-SKILL-7** compiled `SKILL.md` absent ⇒ `unmeasurable` /
  `target-missing` (R2), **not** `unreachable`.

### RP-CMD

- **T-CMD-1** user `claude-md` with `claude_dir` present and
  `<claude_dir>/CLAUDE.md` written ⇒ `reachable` / `user-memory-file`.
  **Constructible only because of B1's threading** — r1's version could
  never pass, since the target was pinned to the operator's real
  `~/.claude/CLAUDE.md` while `claude_dir` was `tmp_path/...`.
- *(T-CMD-2 REMOVED — r1 B2. `user-claude-md-off-runtime-dir` is deleted
  from §5.2; the divergence it tested cannot occur in production and is
  tautological under the test env var.)*
- **T-CMD-3** project `claude-md` at the host root ⇒ `reachable` /
  `project-root-memory-file`, and `detail` contains the "does not prove a
  session ever opens this project" caveat. Asserting on the caveat text
  keeps the disclosure from being quietly dropped.
- **T-CMD-4** `variant: "local"` ⇒ `reachable` /
  `project-local-memory-file` with the durability caveat in `detail`.
- **T-CMD-5** host directory removed ⇒ `unmeasurable` / `host-missing`.

### RP-RULES

- **T-RULES-1** frontmatter `paths:` matches ≥1 file under the roots ⇒
  `reachable` / `globs-match`.
- **T-RULES-2** frontmatter `paths:` matches nothing ⇒ `unreachable` /
  `globs-match-nothing`.
- **T-RULES-3** no frontmatter at all ⇒ `reachable` /
  `loads-unconditionally`, `detail` naming `session_start`.
- **T-RULES-DISK** *(the mutation-catcher)* `routing.rules_paths =
  ["**/*.md"]`, frontmatter `paths: ["**/no-such-file-zzqx-*.xyz"]` ⇒
  `unreachable` / `globs-match-nothing`. **An implementation that reads the
  ledger returns `reachable` and only this test fails.**
- **T-RULES-4** frontmatter present and matching but different from
  `routing.rules_paths` ⇒ `reachable` / `globs-match`, and `detail`
  contains **both** lists. Drift is reported, never promoted to the
  verdict.
- **T-RULES-5** rules file outside the scanned directory ⇒ `unreachable` /
  `rules-dir-off-loaded-path`.
- **T-RULES-6** undecodable rules file ⇒ `unmeasurable` /
  `frontmatter-unreadable`.
- **T-RULES-7** `glob_reaches` monkeypatched to return `"budget"` for
  every pattern ⇒ `unmeasurable` / `glob-budget-exhausted`, **not**
  `unreachable`. U-glob §6.6's asymmetry, pinned.
- **T-RULES-BYPASS** *(r1 M-D)* a record with
  `routing.glob_bypass_reason == "zero-match"` whose frontmatter globs
  match nothing ⇒ `reachable` / `bypass-approved`, and the row PASSes.
  Second leg: the legacy shape (`allow_empty_glob: true`, no
  `glob_bypass_reason` key) ⇒ same. Third leg: `glob_bypass_reason ==
  "budget"` with globs matching nothing ⇒ `unreachable` /
  `globs-match-nothing` — a transient timeout buys no permanent
  exemption. Without this test the approved write-the-rule-first route
  turns `--selftest` red.
- **T-RULES-ROOTS** user-scope rules record whose frontmatter glob matches
  a file **inside the sandbox** ⇒ `reachable` / `globs-match`, and the
  test asserts the probe roots are under `tmp_path`. Guards B1's third
  threading site: unthreaded, `_user_reachability_roots` walks the
  operator's real `$HOME` (17.95 s cold, U-glob M10).

### RP-HOOK

- **T-HOOK-1** script registered under `PreToolUse` with `matcher: "Bash"`
  and `tools: ["Bash"]` ⇒ `reachable` / `registered`.
- **T-HOOK-UNREG** *(two-sided, §5.4)* perfect script + symlink,
  `settings.json` registering a **different** hook ⇒ `unreachable` /
  `not-registered` **and** `selfcheck._check_hooks` returns `(True, …)` on
  the same fixture. The second half is what demonstrates the gap is real.
- **T-HOOK-2** registered under `PostToolUse` only ⇒ `unreachable` /
  `wrong-event`.
- **T-HOOK-3** `tools: ["Bash", "Edit"]`, `matcher: "Bash"` ⇒
  `unreachable` / `matcher-mismatch`.
- **T-HOOK-4** `matcher: "["` ⇒ `unmeasurable` / `matcher-unparseable`,
  **not** `matcher-mismatch`.
- **T-HOOK-5** `matcher: ""` and `matcher: "*"` ⇒ both `reachable`.
- **T-HOOK-BROKEN** `settings.json` = `"{"` ⇒ `unmeasurable` /
  `settings-unparseable` **and** `_check_surface` returns `(False, …)`.
  The §2.6 incident as a fixture; the only reason that fails the row.
- **T-HOOK-6** `settings.json` absent, `claude_dir` present ⇒
  `unreachable` / `no-registrations`. Distinguishes absent-file (a
  determination) from absent-dir (unmeasurable).

### Domain, instrument, renderers

- **T-DOMAIN-USER** in-domain record in `user/resolved/` only ⇒ `checked
  == 1`. Guards the `*/*/resolved` glob trap (§5.6).
- **T-DOMAIN-EXCLUDE** a live `reference` record present ⇒ absent from
  `rows` and from `checked`. `reference` is `_check_reach`'s (§9.1).
- **T-DOMAIN-SUPERSEDED** a superseded `skill-md` record on an
  `"off"` skill ⇒ absent from `rows`. Live-only.
- **T-DOMAIN-UNPARSEABLE** a resolved file with broken frontmatter ⇒
  skipped, `unparseable_records == 1`, and no exception.
- **T-INSTRUMENT** all four `Instrument.state` values constructible, and
  **the facet PAIR matches §5.5's table for each** (r2 n2): `ok` →
  `(True, True)`; `settings-absent` → `(True, True)`;
  `claude-dir-absent` → `(False, False)`; `settings-unparseable` →
  `(True, False)`. r2 asserted a singular `usable` that §5.5's split had
  already deleted, and got `settings-unparseable` wrong — under the table
  its `claude_dir_usable` is `True`. No dangling enum member.
- **T-RENDER-NULL** *(rewritten, r2 MAJOR 1)* three legs, one per facet
  state, asserting §6 rule 2's table rather than a blanket flag:
  1. `claude_dir_usable is False` ⇒ top-level `reachable`/`unreachable`
     **and every** `by_destination` sub-count are `None`, not `0`.
  2. `settings_usable is False` with `claude_dir_usable is True` ⇒ the
     `skill-md` / `new-skill` / `hook` sub-counts are `None`, **but the
     three `claude-md*` sub-counts are integers**. This leg is what stops
     the renderer re-introducing the r1 M-A blanking; without it
     T-RENDER-NULL locks the blanking in.
  3. both usable ⇒ nothing is `None`.
  Every leg also asserts the text render contains `NOT MEASURED` for
  exactly the nulled groups.
- **T-RENDER-BYVARIANT** *(Q3 ruling)* a home with one live rules record
  and one live plain `claude-md` record ⇒ the rules record is counted
  under `claude-md:rules` and **not** under `claude-md`; both keys are
  present; `claude-md:local` is present with zero counts. Paired with
  M28.
- **T-RENDER-ORDER** a home with one of each state ⇒ `rows[0]["state"] ==
  "unreachable"` and `rows[-1]["state"] == "reachable"`.
- **T-RENDER-ALL** every in-domain record appears in `rows`, including
  `reachable` ones (§6 rule 4).
- **T-FACET** *(r1 M-A)* live `claude-md` + rules records with a
  `settings.json` of `{` ⇒ every `claude-md`/rules row is **determined**,
  not `unmeasurable`; only settings-dependent destinations go
  `settings-unparseable`.
- **T-REFUSE** *(r1 M-E)* `_check_surface` against (a) a missing home and
  (b) a not-a-repo home ⇒ `(False, …)` with `home_state_message`'s text,
  **not** `PASS — no records in the reachability domain`. Third leg: a
  real repo home with no `hosts.yaml` ⇒ `(True, "hosts.yaml absent —
  reachability not checked")`.
- **T-EMPTY-DOMAIN** *(r1 N7)* a healthy home with `hosts.yaml` and zero
  in-domain live records ⇒ `(True, …)` containing
  `"no records in the reachability domain"`. §4.4 row 5 had no test and no
  mutation in r1; **M26** pairs with it.
- **T-ONE-PREDICATE** *(the §4.3 guard, r1 M-F)* the monkeypatch target
  must be the name the caller actually binds. This codebase binds at
  import (`selfcheck.py:98`, `report.py:32-37`), so patching
  `reachability.reachability_rows` leaves `selfcheck`'s and `report`'s
  bound names untouched — the stub never runs and the test passes while
  controlling nothing (the repo's recurring "fixtures that control
  nothing" failure). Patch **`selfcheck.reachability_rows`** and
  **`report.reachability_rows`** — the module attributes the renderers
  read — with a stub returning a fixed two-row list, and assert both
  renderers' counts derive from it. **The positive control comes first:**
  the test asserts the stub was actually called (a call counter) before
  asserting on any number.
- **T-SELFTEST-ROW** `run_selftest` prints a `surface` row and `len(
  results) == 9`; a home with one `unreachable` returns rc **1**.
- **T-NO-WRITES** *(tightened, Q4 RULED)* the unit's **sole** side-effect
  oracle — no `git status` comparison is added (see §11 Q4). Snapshot
  `root.rglob("*")` **including dotfiles** over all three roots (the
  ledger home, the host repo, the claude dir) as
  `(path relative to root, st_mtime_ns, sha256-of-bytes)` triples, run
  `reachability_rows`, snapshot again, and **compare the full sets** — so
  a *created* or *deleted* path fails the test, not only a modified one.
  Including dotfiles is what makes `.git/index` and `.git/ORIG_HEAD`
  covered by construction, which is the only reason a git-specific check
  was ever proposed. Directories are skipped; symlinks are recorded by
  their `lstat` mtime and link target, never followed (a followed link
  would hash a file outside the roots).
- **T-NO-REAL-HOME** `reachability_rows` never touches the real
  `~/.claude` or `~/.self-learn`: **monkeypatch `Path.open` /
  `Path.read_text` and assert every path opened is under the fixture
  roots.** *(r2 n4: the alternative r2 offered — "or assert on the
  resolved `claude_dir`/`home` arguments" — asserts nothing about which
  paths were actually opened, so it is the vacuous half of a disjunction
  and is removed.)* Guards the class `managed_target_for`'s docstring
  warns about at `verbs.py:823-830`.

---

## 9. Out of scope

1. **The `reference` destination.** Wholly owned by the shipped
   `_check_reach` (`selfcheck.py:288-393`) and `report._reference_shelf`
   (`:291`). Not re-implemented, not delegated to, not modified. A second
   predicate over one destination is the masking trap
   `selfcheck.py:288-296` names. If a gate reviewer wants `reference` in
   `surface_reach`'s `rows`, that is a **later** unit that refactors
   `_check_reach` to return per-record verdicts — not an addition here.
2. **Cap rework (TaskList #1).** In flight. This unit emits no budget
   number, reads no cap, and must not touch `surface_fill`,
   `SURFACE_FILL_CAPPED_DESTINATIONS` (`verbs.py:213`) or `over_cap`.
3. **Routing gates.** No refusal, no preflight, no change to
   `_resolve_target`, `_apply_target`, or any `TargetSpec` field. This
   unit does not make any route harder. It is an audit.
4. **S-23's shelf question.** Whether `reference` should keep earning its
   place is a decision U-readref's read-rate data feeds; this unit
   produces no input to it and must not editorialise about it.
5. **The `tuple[bool, str]` check contract.** Widening `run_selftest`'s
   row type to carry a state enum would touch all eight existing checks
   and change the printed format of a surface operators read. §4.4's
   two-valued row plus a mandatory count is the bounded alternative. A
   future unit may revisit it.
6. **A CLI verb or flag for the live probe.** §7 documents a procedure,
   not a feature. No `--probe`, no `self-learn reach`. A verb that starts
   model sessions is a product decision, and it belongs to the user, not
   to a spec author.
7. **Dangling-pointer resolution** (older draft §7.4): proving a pointer
   *token* resolves to a real file, as opposed to appearing in the text.
   Still open, still adjacent, still not this unit.
8. **Repairing anything.** Every verdict names a remedy in `detail`; none
   is applied. No `recompile` change, no auto-registration of hooks, no
   writing to `settings.json`. The instrument this unit reads is the
   operator's live configuration and it stays theirs.
9. **Retro-classifying already-routed records.** Records routed before
   this unit are audited by it on the next run, like everything else. No
   migration, no backfill, no upgrade-time pass.

---

## 10. Mutation plan — what a code gate must be able to break

Each mutation names the single test that must go red. A mutation that
kills no test is a criterion that cannot fail.

**The converse cross-check is part of the code gate's job**, and r3 ran
it: extract every `T-…` id defined in §8 and every id referenced here, and
diff the two sets. The only §10 reference with no §8 definition is
`T-CMD-2`, inside the struck `~~M21~~` row that records its deletion —
correct, not a dangling reference. The reverse direction found the unit's
headline capability unmutated: **T-HOOK-UNREG, T-RULES-5/6, T-SKILL-1,
T-HOOK-2 and T-SELFTEST-ROW had no paired mutation**, so M31–M36 below
close them. A test nobody can break is the same defect as a criterion that
cannot fail, seen from the other side.

**Four tests remain unmutated, empirically confirmed** *(r2 fold, measured
2026-08-24, T-NO-WRITES removed 2026-08-24 micro-fold — supersedes the
"Nine tests" claim this paragraph used to make. Method: every mutation in
the table below was applied to the current code, `test_reachability.py`
run, the failing test-function set recorded, the mutation reverse-`Edit`ed,
60-passed reconfirmed — see the Notes subsection after the table. This
census is {all 60 test functions} minus {the union of every measured red
list}. Six of the old paragraph's nine names turned out to be
measured-covered once actually tested: `T-RULES-1`/`T-RULES-2` (M13,
M27), `T-HOOK-1`/`T-HOOK-5` (M20), `T-SKILL-6` new-skill leg (M35), and
`T-HOOK-BLIND` (M1, M20) — see notes [1], [6]/[8], [10], [12], [16], [17]
for which mutation actually kills each. Only three of the nine survive
measurement, joined at the r2 fold by two names not on the old list at
all (T-NO-WRITES, and the leg-3 half of T-RENDER-NULL). T-NO-WRITES was
then itself removed by the 2026-08-24 micro-fold (NIT-5): M30, restated
as a paired write-introducing + weakened-snapshot mutation (note [21]),
measurably falsifies it, so it is no longer census material — it has a
live must-fail cell instead*: `T-CMD-5`, `T-DOMAIN-SUPERSEDED`,
`T-DOMAIN-UNPARSEABLE`, `T-RENDER-NULL` (leg 3 only — legs 1 and 2 are
covered by M17/M17b). These four remain **positive-path or enumeration**
assertions with no dedicated mutation aimed at them — the same rationale
the retired paragraph gave, now applied to the measured-correct set. The
plan is not padded to reach one-mutation-per-test; a mutation that
duplicates another's kill teaches the gate nothing.

| # | Mutation | Must fail |
|---|---|---|
| **M1** | `read_instrument` returns `claude_dir_usable=True` for `claude-dir-absent` | **T-CMD-BLIND, T-HOOK-BLIND, T-INSTRUMENT, T-RENDER-NULL leg 1, T-ROW-BLIND, T-RULES-BLIND, T-SKILL-BLIND** [1] |
| **M2** | `unmeasurable` renders as the looked-and-found-fine phrasing | **T-ROW-BLIND, T-ROW-MIXED** [2] |
| **M3** | drop the count from the PASS message | **T-ONE-PREDICATE, T-ROW-BLIND, T-ROW-MIXED** [3] |
| **M3b** | emit the count only when `reachable == 0` | **T-ONE-PREDICATE, T-ROW-MIXED** [4] |
| M3c | print the literal `~/.claude` instead of the resolved dir | T-ROW-BLIND (assertion 3) |
| **M4** | RP-RULES reads `routing.rules_paths` instead of frontmatter | **T-RULES-4, T-RULES-DISK** [5] |
| M5 | RP-RULES treats `"budget"` as `"none"` | T-RULES-7 |
| **M6** | RP-SKILL returns `not-indexed` for an undecidable route | **T-SKILL-5, T-SKILL-5d** [6] |
| M6b | undecidability made global instead of per record | T-SKILL-5b |
| M6c | plugin root hard-codes `plugins/<n>` instead of reading `source` | **T-SKILL-4b only** |
| **M6d** | plugin roots read `extraKnownMarketplaces` instead of `known_marketplaces.json` | **T-HOOK-6, T-INSTRUMENT, T-SKILL-4, T-SKILL-4b, T-SKILL-5d leg 2, T-SKILL-8** [7] |
| **M6e** | *(r2 BLOCKER)* row 9 quantifies over the WHOLE `enabledPlugins` map instead of in-scope entries only (§5.1A′) | **T-SKILL-5c only** |
| **M6f** | §5.1A′ narrowed so far that row 9 never fires (undecidability ignored) | **T-SKILL-5, T-SKILL-5d** [8] |
| **M6g** | plugin `source` string treated as `plugins/<name>` rather than marketplace-root-relative, breaking `./external_plugins/<n>` | **T-SKILL-4, T-SKILL-4b, T-SKILL-8** [9] |
| **M6h** | *(r3-a NIT)* the skill-md leg resolves via the new-skill FIXED FORMULA (`<skills_root>/plugins/<n>/skills/<n>/SKILL.md`) instead of `skill_dir_for`'s glob — i.e. `managed_target_for`'s two legs are collapsed into one | **T-FACET, T-RENDER-ORDER, T-SKILL-1, T-SKILL-2, T-SKILL-3, T-SKILL-6b, T-SKILL-BLIND** [10] |
| **M6i** | *(r3-c NIT)* §5.1A′'s in-scope test drops the `installLocation`-is-ancestor disjunct, keeping only the plugin-name-equals-skill-name check | **T-SKILL-5d leg 2 only** |
| M7 | RP-SKILL uses `os.path.lexists` (dangling reads as present) | T-SKILL-3 |
| M8 | RP-SKILL checks `skillOverrides` after the discovery routes | T-SKILL-2 |
| M8b | `skillOverrides` matches only the bare-name form | T-SKILL-8 |
| M9 | RP-HOOK omits the matcher comparison | T-HOOK-3 |
| M10 | RP-HOOK maps `re.error` to `matcher-mismatch` | T-HOOK-4 |
| M11 | `settings-unparseable` stops failing the row | T-HOOK-BROKEN |
| **M11b** | `settings-unparseable` blanks settings-independent records too | **T-CMD-BLIND, T-FACET, T-ROW-BLIND** [11] |
| M12 | `settings-absent` maps to `unmeasurable` | T-HOOK-6 |
| **M13** | domain glob becomes `*/*/resolved` | **T-CMD-1, T-CMD-BLIND, T-DOMAIN-USER, T-FACET, T-RENDER-BYVARIANT, T-ROW-BLIND, T-ROW-MIXED, T-RULES-1, T-RULES-2, T-RULES-3, T-RULES-4, T-RULES-5, T-RULES-6, T-RULES-7, T-RULES-BLIND, T-RULES-BYPASS, T-RULES-DISK, T-RULES-ROOTS** [12] |
| M14 | `reference` included in the domain | T-DOMAIN-EXCLUDE |
| **M15** | `target-missing` mapped to `unreachable` | **T-ROW-MIXED, T-SKILL-7** [13] |
| M16 | `_check_surface` recomputes its counts from the ledger | T-ONE-PREDICATE |
| **M17** | facts block emits `0` instead of `null` when a depended-on facet is unusable | **T-RENDER-NULL leg 1, T-RENDER-NULL leg 2** [14] |
| **M17b** | *(r2 MAJOR 1)* nulling collapsed to a single `instrument_usable` = `claude_dir_usable and settings_usable`, so a settings typo nulls the `claude-md*` counts | **T-RENDER-NULL leg 2 only** |
| **M18** | `rows` filtered to failures only | **T-RENDER-ALL, T-RENDER-ORDER** [15] |
| M19 | ordering changed to `record_id` only | T-RENDER-ORDER |
| **M20** | *(restated, r1 M-G; re-targeted 2026-08-24 fold r2 — see note [16])* `reachability_rows` **ignores** the passed `claude_dir` and resolves `Path("~/.claude")` directly inside its own `read_instrument(claude_dir)` call | **T-CMD-BLIND, T-FACET, T-HOOK-1, T-HOOK-2, T-HOOK-3, T-HOOK-4, T-HOOK-5, T-HOOK-6, T-HOOK-BLIND, T-HOOK-BROKEN, T-NO-REAL-HOME, T-RENDER-NULL leg 1, T-RENDER-NULL leg 2, T-ROW-BLIND, T-RULES-BLIND, T-SKILL-2, T-SKILL-4, T-SKILL-4b, T-SKILL-5, T-SKILL-5d leg 1, T-SKILL-5d leg 2, T-SKILL-8, T-SKILL-BLIND** [16] |
| ~~M21~~ | *(REMOVED — r1 B2; §5.2 rule 4 and T-CMD-2 are deleted)* | — |
| M22 | the `project-root-memory-file` caveat text is dropped | T-CMD-3 |
| **M22b** | *(r3-b NIT)* the `loads-unconditionally` `detail`'s `session_start` evidence text is dropped | **T-RULES-3 only** |
| **M22c** | *(r3-b NIT)* the frontmatter-vs-ledger drift note (both `paths:` lists) is dropped from `detail` | **T-RULES-4 only** |
| **M22d** | *(r3-b NIT)* the `CLAUDE.local.md` durability caveat text is dropped from `project-local-memory-file`'s `detail` | **T-CMD-4 only** |
| M23 | any predicate opens `settings.json` directly | T-INSTRUMENT + T-ONE-PREDICATE |
| **M24** | *(r1 M-E)* drop the `home_state` refusal from `_check_surface` | T-REFUSE (a) and (b) |
| M24b | drop the `hosts.yaml`-absent skip | T-REFUSE (c) |
| **M25** | *(r1 M-D)* drop the `zero-match` / legacy bypass branch | T-RULES-BYPASS legs 1–2 |
| M25b | exempt a `"budget"` bypass as well | T-RULES-BYPASS leg 3 |
| **M26** | *(r1 N7)* zero-domain PASS message changed to a bare `PASS` with no words | T-EMPTY-DOMAIN |
| **M27** | *(r1 B1)* `reachability_rows` ignores `user_claude_md` and falls back to `DEFAULT_USER_CLAUDE_MD` | **T-CMD-1, T-ROW-MIXED, T-RULES-1, T-RULES-2, T-RULES-3, T-RULES-DISK, T-RULES-4, T-RULES-5, T-RULES-6, T-RULES-7, T-RULES-BYPASS, T-RULES-ROOTS, T-RENDER-BYVARIANT, T-FACET** [17] |
| **M27b** | `_user_reachability_roots` fed `DEFAULT_USER_CLAUDE_MD` | **T-FACET, T-RENDER-BYVARIANT, T-RULES-1, T-RULES-4, T-RULES-ROOTS** [18] |
| **M28** | *(Q3)* `by_destination` keyed by `destination` alone, collapsing the three `claude-md` variants | T-RENDER-BYVARIANT |
| **M29** | *(r2 MAJOR 2)* the note line appended unconditionally on `U > 0`, naming `claude_dir` for a `target-missing` unmeasurable | **T-ROW-MIXED assertion 4 only** |
| M29b | the note line prints the raw `Instrument.state` instead of the distinct verdict reasons | T-ROW-MIXED assertion 3 |
| **M30** | *(Q4; restated as a paired mutation, 2026-08-24 micro-fold — see note [21])* `T-NO-WRITES`'s own `_snapshot` helper skips dotfiles, PAIRED WITH a write-introducing mutation in `reachability_rows` (an unconditional dotfile touch under `claude_dir`) — the un-weakened snapshot alone already catches the write; only the pairing demonstrates the hazard | **T-NO-WRITES** [21] |
| **M31** | RP-HOOK drops the record→registration lookup entirely and returns `reachable` once the script is intact — i.e. reverts to what `_check_hooks` already does | **T-HOOK-2, T-HOOK-3, T-HOOK-4, T-HOOK-UNREG** [19] |
| **M32** | RP-HOOK matches a registration under any event, not only `PreToolUse` | T-HOOK-2 |
| **M33** | RP-RULES skips the directory-identity check (§5.3 step 2) | T-RULES-5 |
| **M34** | RP-RULES treats unreadable frontmatter as `loads-unconditionally` instead of `unmeasurable` | T-RULES-6 |
| **M35** | RP-SKILL never consults `<claude_dir>/skills/<name>` (row 6 removed) | **T-SKILL-1, T-SKILL-5b, T-SKILL-6, T-SKILL-6b** [20] |
| **M36** | `run_selftest` computes the row but omits it from `results` | T-SELFTEST-ROW |

### Notes (fold r2, measured 2026-08-24)

Each mutation below was applied to the current code (one file, one
unique-substring `Edit`), `test_reachability.py` run in full, the failing
test-function set recorded, the mutation reverse-`Edit`ed, and a 60-passed
run reconfirmed before moving to the next mutation — the same procedure
r1-fold used for M27. Cell counts below are test **functions**, not spec
test-ids; `T-SKILL-5d` and `T-RENDER-NULL` each span two/three functions
(leg 1/leg 2[/leg 3]) — see §8.

1. **M1** — 7 killed, not the claimed 2. `claude_dir_usable=True` under a
   nonexistent dir feeds every predicate gated on that facet, plus
   `test_instrument_four_states` (calls `read_instrument` directly) and
   `test_render_null_three_legs` (nulls on `claude_dir_usable`).
2. **M2** — 2 killed, not the claimed 1. T-ROW-MIXED also has 2
   unmeasurable rows, so the same "N record(s) reachable" substitution
   breaks its `"2 UNMEASURABLE" in msg` assertion too.
3. **M3** — 3 killed, not the claimed 2. T-ONE-PREDICATE's stub asserts
   `"1 of 2 verified reachable" in msg`; dropping the count breaks that
   too.
4. **M3b** — 2 killed, not the claimed 1. T-ONE-PREDICATE's stub has
   `reachable=1 != 0`, so "emit count only when `reachable == 0`" drops
   the count there as well.
5. **M4** — 2 killed, not the claimed 1. T-RULES-4's fixture frontmatter
   deliberately differs from `routing.rules_paths` (that is the drift
   fixture); reading `ledger_paths` instead of the file changes its
   glob-match outcome too.
6. **M6** — 3 functions killed (T-SKILL-5, T-SKILL-5d both legs), not the
   claimed 1. Disabling the `undecidable_in_scope` branch falls through
   to `not-indexed` for every in-scope-undecidable fixture, not only
   T-SKILL-5.
7. **M6d** — 6 killed, not the claimed 2. Moving marketplace resolution
   from `known_marketplaces.json` onto `data.get("extraKnownMarketplaces")`
   changes `read_instrument`'s parse path (hits T-INSTRUMENT) and empties
   `marketplaces` for every fixture built via `make_claude_dir(...,
   marketplaces=...)` (T-SKILL-5d leg 2, T-HOOK-6, T-SKILL-8 all use it).
8. **M6f** — same 3 functions as M6, not the claimed 1 (T-SKILL-5d alone).
   Same code path.
9. **M6g** — 3 killed, not the claimed 1. Resolving `source` under a
   spurious `plugins/` prefix also breaks every fixture whose `source` is
   already `./plugins/<p>` (T-SKILL-4, T-SKILL-8), not only the
   `"source": "./"` shape (T-SKILL-4b).
10. **M6h** — 7 killed, not the claimed 1. Collapsing the skill-md leg
    onto the new-skill fixed formula changes `managed_target_for`'s
    skill-md target for every fixture using `support.py`'s sandbox
    layout — T-SKILL-1/2/3/BLIND (personal-symlink fixtures) plus
    T-FACET/T-RENDER-ORDER (multi-record fixtures that route a skill-md
    record among others), not only T-SKILL-6b.
11. **M11b** — 3 killed, not the claimed 1. Gating `_rp_cmd` on
    `settings_usable` also fires under `claude-dir-absent` fixtures,
    whose `Instrument` carries `settings_usable=False` too (T-CMD-BLIND,
    T-ROW-BLIND route a user claude-md record through the same branch).
12. **M13** — 18 functions killed, not the claimed 1. Filtering buckets
    to ≥2 path segments (emulating a `*/*/resolved` glob) drops the
    single-level `user/` bucket outright, so every fixture routing a
    user-scope record — cmd, rules, or mixed with skill/hook — loses that
    record from the domain.
13. **M15** — 2 killed, not the claimed 1. T-ROW-MIXED's two
    "missing-target" records are skill-md fixtures with a missing
    compiled file — the same `target-missing` leg T-SKILL-7 pins.
14. **M17** — measured **T-RENDER-NULL leg 1, leg 2**, not the claimed
    "legs 1 and 3". Leg 3 (`test_render_null_leg3_both_usable_nothing_null`)
    only asserts nothing is `None` when both facets ARE usable; the
    nulling-to-`0` mutation only fires when a facet is unusable, so leg 3
    stays green under it. Leg 2 is newly measured because the `0`
    substitution also lands on the `_SETTINGS_DEPENDENT_KEYS` nulling
    path leg 2 exercises. Cell corrected to the measured set; the claimed
    "leg 3" looks like a copy artifact from the neighboring M17b row.
15. **M18** — 2 killed, not the claimed 1. T-RENDER-ORDER seeds one
    reachable + one unreachable + one unmeasurable record and asserts
    `len(rows) == 3`; filtering the reachable row out breaks that count.
16. **M20** — measured 23 functions, not the claimed 1, against the
    RE-TARGETED site: `reachability_rows`'s `read_instrument(claude_dir)`
    call, mutated to `read_instrument(Path("~/.claude").expanduser())`.
    The row's original text (r1 M-G) named `_surface_reach` instead and
    offered two readings; §8's T-NO-REAL-HOME (the claimed victim) calls
    `reachability_rows` directly and never touches `_surface_reach`, so
    NEITHER `_surface_reach` reading can kill T-NO-REAL-HOME — confirmed
    by re-testing both, 2026-08-24 micro-fold: (i) `_surface_reach`
    ignoring `claude_dir` and calling `claude_runtime_dir()` itself is
    INERT (0 fails) — `claude_runtime_dir()` reads `SELF_LEARN_CLAUDE_DIR`,
    the same env var `conftest.py`'s `make_claude_dir`/`missing_claude_dir`
    fixtures already set, so re-deriving it returns the identical
    sandboxed path; (ii) `_surface_reach` resolving `Path("~/.claude")`
    directly (bypassing the env var) kills 3 — `test_render_null_three_legs`,
    `test_render_null_leg2_settings_broken_claude_md_survives`,
    `test_render_byvariant` (T-RENDER-NULL leg 1, T-RENDER-NULL leg 2,
    T-RENDER-BYVARIANT) — the only tests that call `_surface_reach`
    directly. The row text now names the `reachability_rows` site as
    primary so a literal application lands on the 23-item measurement;
    the weaker `_surface_reach` / `Path("~/.claude")` variant (3 kills)
    stays on record here rather than deleted, as a real but narrower
    instance of the same hazard. Reading the real `~/.claude` at the
    `reachability_rows` site also swaps in the operator's actual
    `enabledPlugins` / `skillOverrides` / `hook_registrations` /
    `marketplaces` for every fixture that reaches a predicate consulting
    `Instrument` — hence that site's wider blast radius.
17. **M27** *(rationale relocated out of the cell per NIT-3; content
    unchanged from the r1-fold correction, 2026-08-24)* — the original
    claimed list (T-CMD-1, T-CMD-BLIND, T-RULES-BLIND) was wrong on all
    three counts. T-CMD-BLIND and T-RULES-BLIND are structurally immune:
    both fixtures route through `missing_claude_dir`, and `_rp_cmd` /
    `_rp_rules` check `instrument.claude_dir_usable` before ever touching
    `target`. T-CMD-1 itself was fail-open before the MAJOR-1 test fix
    (it asserted only `row.state`/`row.reason`) — the mutated target,
    `DEFAULT_USER_CLAUDE_MD.expanduser()`, resolves to the operator's
    real `~/.claude/CLAUDE.md`, which exists on this host, so
    `state`/`reason` still matched. The corrected list is this
    mutation's actual blast radius through the shared `user_claude_md`
    threading: RP-RULES roots resolution (the ten `T-RULES-*` legs),
    `by_destination` rules-variant bucketing (T-RENDER-BYVARIANT), and
    the settings-broken facet control (T-FACET).
18. **M27b** — 5 killed, not the claimed 1. Feeding `DEFAULT_USER_CLAUDE_MD`
    only to `_user_reachability_roots` (not `_user_rules_dir`) still
    relocates the probe roots off the sandbox for every user-scope rules
    fixture whose glob match depends on `roots`, not only T-RULES-ROOTS.
19. **M31** — 4 killed, not the claimed 1. Returning `reachable` once the
    script is intact, without checking the registration at all, also
    makes the wrong-event / matcher-mismatch / matcher-unparseable
    fixtures report `reachable` instead of their expected verdict.
20. **M35** — 4 killed, not the claimed 1. Removing row 6 entirely also
    removes the "symlink wins over undecidable" precedence T-SKILL-5b
    pins, and both `new-skill`/`skill-md` fixtures that resolve via a
    personal symlink (T-SKILL-6, T-SKILL-6b) lose their only reachable
    route.
21. **M30** *(restated as a paired mutation, gate-guided, 2026-08-24
    micro-fold — resolves NIT-5: T-NO-WRITES was simultaneously an
    un-widened must-fail cell and census-exempt)* — two configurations
    measured: (1) the write-introducing half ALONE (an unconditional
    `(claude_dir / ".m30_probe").touch()` added to `reachability_rows`,
    guarded `if claude_dir.is_dir()` so BLIND fixtures with no `claude_dir`
    don't crash) — `test_no_writes` goes RED (1 fail), proving the
    CURRENT, un-weakened `_snapshot` helper already catches a real write;
    this is r1's falsifiability proof, reconfirmed. (2) the SAME write
    PAIRED with the weakened snapshot (dotfiles skipped) — `test_no_writes`
    goes GREEN (0 fails, rc=0) despite the write, reproducing M30's
    original hazard: a snapshot that skips dotfiles is fail-open. Because
    config (1) alone already falsifies T-NO-WRITES, the test is not
    exemption material — M30's cell is restated to **T-NO-WRITES** and
    the exemption census below drops it (was 5, now 4).

Three mutations measured **zero** kills against the current suite and are
left as-is (widening only applies to cells whose measured set EXCEEDS the
claim; a zero-measurement is a different defect class, flagged for the
coordinator, not corrected here): **M6b** (the "personal symlink still
wins over undecidable" ordering M6b was meant to test is already
guaranteed by row 6 running before rows 7–9, so the mutation as
implemented — hoisting the undecidable-return above the symlink check —
found no test that isolates JUST that ordering from T-SKILL-5c's
in-scope-narrowing); **M7** (`os.path.lexists` treating a dangling
personal symlink as reachable did not reproduce a T-SKILL-3 failure with
the implementation attempted); **M23** (a redundant, unused direct
`settings.json` read added to RP-HOOK is inert — it changes no return
value any test observes). **M30** was in this group as of the r2 fold —
mutating the TEST's own `_snapshot` helper alone cannot be caught by
`test_reachability.py`, since nothing in the suite writes a dotfile for
the weakened snapshot to miss — but the 2026-08-24 micro-fold restated it
as a paired mutation (note [21]) and it now has a live, measured
must-fail cell instead of sitting in this zero-kill group.

## 11. Questions — all RULED

1. **~~Should `plugin-route-undecidable` be reachable on this host at
   all?~~ REFRAMED (r1 B3), then RESOLVED (r2 BLOCKER).** r1 asked this on
   the false premise that the undecidable row had no live subject; r2
   swapped the instrument to `known_marketplaces.json` but left the
   quantifier global, which made the row **permanently true** — 28 of 34
   entries decidable, 6 `{"source": "url", …}` dicts, measured. §5.1A′
   scopes undecidability to entries that could plausibly name *this*
   target, which restores `not-indexed` on the live host. **Residual
   question, still narrow:** should a dict-sourced plugin be resolvable by
   falling back to `<install>/plugins/<name>`? This spec says **no** —
   guessing a layout is what B3 flagged, and the 15 live
   `./external_plugins/<n>` entries show the guess would have been wrong.
2. **~~Is `PASS`-with-count right for a host with no `~/.claude`?~~
   RULED** by the orchestrator: **not a FAIL** — `unmeasurable`, with the
   count in the PASS string plus a note line; the
   `tests/conftest.py:94-96` fixture stays. §4.4 implements it and
   T-ROW-BLIND assertions 2–3 test it. **Amended at r2 MAJOR 2:** the note
   line names the distinct unmeasurable *reasons*, and appends the
   resolved dir only when `claude-dir-absent` or `settings-unparseable` is
   among them — the ruling's case is preserved, the misleading
   generalisation is not.
3. **~~`by_destination` variant split?~~ RULED (gate): SPLIT.** Keys are
   `skill-md`, `new-skill`, `hook`, `claude-md`, `claude-md:local`,
   `claude-md:rules`. The rationale is recorded at §6 rule 5: the three
   `claude-md` shapes come from two different predicates with disjoint
   reason sets and disjoint remedies, and a merged count is the one number
   that cannot route attention between them. Group-by over `Verdict.
   variant`, so §4.3 is untouched. T-RENDER-BYVARIANT + M28.
4. **~~Should `T-NO-WRITES` cover the host repo's git index?~~ RULED
   (gate): NO — tighten the snapshot instead.** No `git status`
   comparison: it would put a subprocess inside a test whose whole claim
   is that the unit has no side effects, and it flaps against its own
   instrument (a plain `git status` rewrites `.git/index`'s cached stat
   data, so it can report a change the unit did not cause). A second,
   weaker oracle beside a stronger one is how a suite learns to distrust
   the stronger one. §8's `T-NO-WRITES` is therefore the sole oracle and
   is tightened normatively: `rglob("*")` including dotfiles, three roots,
   `(relpath, st_mtime_ns, sha256)` triples, **full-set** comparison so
   creations and deletions fail too. `.git/index` is covered by
   construction. M30 pairs with it.
5. **The question r1's deleted rule 4 was reaching for — and the gate's
   observation about what RP-CMD now is.** "Is the operator compiling user
   canon into a file their running Claude Code does not read?" has **no
   static handle in this codebase**: the compile target and the runtime
   dir are the same expression (§5.2), and §4.3's B1 threading derives one
   from the other.

   **Consequence, recorded because it is honest and not obvious (r2 gate
   observation):** with rule 4 deleted, **user-scope RP-CMD is a presence
   classification, not a reachability test.** It can return only
   `unmeasurable` (rows 1–3) or `reachable` (row 4) — row 4's condition is
   true by construction of the override, and row 8
   `not-on-a-loaded-path` is unreachable for user scope. That is the
   truthful state of what can be checked statically, not a gap left by
   oversight. Project- and skill-scope RP-CMD keep all four outcomes, and
   RP-SKILL / RP-RULES / RP-HOOK are genuine reachability tests. The only
   instrument that could upgrade user-scope RP-CMD is a live
   `InstructionsLoaded` probe (§7 PROBE-A), whose `memory_type: "User"`
   entry names the file the loader *actually* read — opt-in and
   operator-run by §7, deliberately not wired into `selfcheck`.

## 12. Revision history

- **r1 (2026-08-23)** — first draft, written for a blind gate. Base
  `9912482`. The older `u-pointer-reference-pointer-spec.md` verified
  SHIPPED (`a4e328f`, merged `a50a709`) and the project memory
  `routing-audit-findings.md` recorded as STALE on its one remaining row
  (§3).
- **r2 (2026-08-23)** — folded the r1 blind gate: **NOT SOUND — 3 BLOCKER,
  7 MAJOR, 9 NIT**, all nineteen addressed. The design survived; the
  register did not. B1 threaded `user_claude_md`; B2 deleted the inert
  rule 4; B3 replaced `extraKnownMarketplaces` with
  `known_marketplaces.json`; per-facet instrument usability, exact
  substring assertions, the normative note line, the ratified glob bypass,
  the refusal posture, the retargeted monkeypatch, and a killable M20.
- **r3 (2026-08-23)** — folds the r2 delta gate: **NOT SOUND — 1 BLOCKER,
  2 MAJOR, 5 NIT**, plus two rulings. 18 of r1's 19 folds were accepted
  and B1/B2/B3's instruments verified against the live files; **one
  BLOCKER survived its own fix in a new form.**
  - **BLOCKER** — §5.1B row 9 quantified undecidability over the whole
    `enabledPlugins` map, contradicting §5.1A's per-record promise.
    Reproduced independently: **28 of 34 entries decidable, 6 undecidable**
    (`atomic-agents`, `data-engineering`, `firecrawl`,
    `huggingface-skills`, `remember`, `superpowers` — all
    `{"source": "url", …}`), so row 9 was permanently true and row 10
    `not-indexed` dead again. New **§5.1A′** scopes an undecidable entry
    to the target (plugin name equals the skill name, or the marketplace's
    `installLocation` is an ancestor of the target); **verified this
    restores `not-indexed` live** — no name collision with any live skill,
    neither `installLocation` an ancestor of the skills root. New
    T-SKILL-5c (the shape r2 could not catch: out-of-scope undecidable
    entry, no symlink ⇒ `unreachable`) and T-SKILL-5d, with M6e/M6f.
  - **MAJOR 1** — §6 still carried `instrument_usable`, deleted by the
    M-A facet split and defined nowhere; rule 2 nulled every count on it.
    §6 re-derived on the facet pair with a per-count nulling table;
    T-RENDER-NULL rewritten into three legs, **leg 2 being the one that
    stops the renderer re-introducing the r1 M-A blanking**; M17b added.
  - **MAJOR 2** — the note line fired on every `U > 0` and named the
    runtime dir even for unrelated reasons. It now names the distinct
    unmeasurable reasons and appends the dir only for `claude-dir-absent`
    / `settings-unparseable`; T-ROW-MIXED pinned to `target-missing` so
    the conditional half is exercised; M29/M29b.
  - **RULINGS** — Q3: `by_destination` **split by variant** (six keys),
    §6 rule 5, T-RENDER-BYVARIANT + M28. Q4: **no git-index assertion**;
    `T-NO-WRITES` tightened to `rglob("*")` with dotfiles over three
    roots as `(relpath, st_mtime_ns, sha256)` full-set comparison, M30.
  - **NITs** — the stale "Rule 8" reference removed with the paragraph it
    sat in; T-INSTRUMENT now asserts the facet **pair** per §5.5's table
    (r2 had `settings-unparseable` wrong); §6's illustrative row uses a
    placeholder id (`lrn-38514455` **is** registered live); T-NO-REAL-HOME
    keeps only the monkeypatch, dropping the vacuous alternative;
    `conftest.py:94-96` harmonised.
  - **Recorded, not fixed:** user-scope RP-CMD is now a presence
    classification rather than a reachability test (§11 Q5) — a truthful
    consequence of B2, stated so a reader is not misled about what the
    row proves.
  - **Citation status:** the gate re-verified at `ac9fb33`
    (`git diff 9912482..ac9fb33 -- plugins/self-learn/cli/src
    plugins/self-learn/cli/tests` empty). r3's new measurements
    (`enabledPlugins` decidability census, the official marketplace's
    53 string / 233 dict source split and its 15 `external_plugins`
    entries, the §5.1A′ narrowing check) were run read-only against the
    live host on 2026-08-23.
  - **Mutation plan:** 33 → 41 rows. *(Builder's r3-a/r3-b/r3-c NIT fold:
    41 → 46 rows — M6h, M6i, M22b, M22c, M22d added; census of tests
    "unmutated, deliberately and not by omission" 12 → 9, per §10.)*
