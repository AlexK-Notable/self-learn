# Spec — U-marker: search the excerpt marker the compiler actually writes

Status: **DRAFT r1**. Unit `U-marker` of the r2 routing campaign (playbook
§2, Wave 1). Register row **FW-44**. File in scope: `worker.py`, nothing else.

**Where prose and the acceptance criteria conflict, the criteria win.** The
two marker spellings are printed ONCE each, in §1, and referred to below by
name (*the compiler pair* / *the legacy needle*). A second spelling of either
anywhere in this document — or anywhere in the build outside the one fixture
§3B names — is a defect.

## 1. The defect — re-verified 2026-08-02, not inherited

`compilers.py:84-85` is the **sole writer** of a managed section; its pair is
normative per `02-schema.md:479`:

```
BEGIN_MARKER = "<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->"
END_MARKER   = "<!-- self-learn:end -->"
```

`worker._canon_excerpt` (`worker.py:544-578`) searches, at `:571-574`,
`"SELF-LEARN:BEGIN"` and `"SELF-LEARN:END"` — *the legacy needle*: uppercase,
no comment syntax, no parenthetical. It cannot match. Under 200 lines the file
is returned whole (`:569-570`), so the miss stays invisible until a target
grows; at ≥200 lines the function falls to `lines[:60] + "\n… (truncated)"`
(`:576`) and the analyst is shown the top of the file instead of the canon it
is being asked to compare against — blinding the already-canon gate and the
bounded contradiction check.

**Measured** (sandbox probe, 2026-08-02): a 284-line project target whose
section the real compiler wrote at indices 251–253 yields a 61-line excerpt —
`lines[:60]` plus the sentinel, carrying neither marker nor the compiled entry
line. **Live:** two registered project hosts are over the threshold and blind
today, `~/.config/CLAUDE.md` (720 lines, section at 718–720) and
`~/repos/keyboards/CLAUDE.md` (223, at 221); the *user*-scope target
`~/.claude/CLAUDE.md` is 55 lines, under the threshold, so the bug does not
show there. (r2 attributes the fat target to user scope; on the measured
registry it is reached at **project** scope.) **Nothing has ever written the
legacy needle** — `git log -S` shows it entering only on reader sides
(`7a53fab` worker, `ccbd0f7` UI pane) while the compiler pair has not moved
since `68e0db8`, so there is no legacy corpus.

## 2. The change

In `_canon_excerpt` only: import `BEGIN_MARKER` / `END_MARKER` from
`.compilers` and use them as the two needles. The <200-line passthrough, the
±20-line window, the truncation degradation and the three scope branches are
untouched. **Import, do not re-spell** — re-spelling is how this drifted: two
readers retyped the needle independently and both got it wrong, while the
writer's constant never moved. **No backward-compatibility clause:** also
matching the legacy needle would reinstate the defect as a feature, framing a
section `compile_managed_text` will not regenerate (it matches byte-exact,
`compilers.py:224-241`).

## 3. Acceptance criteria

Both criteria **must fail against unmodified `worker.py`**. Running them
pre-fix and recording the two failures IS this unit's positive control
(campaign §5): a check that has never failed has not been shown to work.

**A — a fat target's compiled section reaches the excerpt.** Fixture:
`env = make_env(tmp_path)`; a routed record `R` (`make_behavior` +
`set_routing`/`set_status("routed")`, as `test_compilers.py:31-34`); the host
`CLAUDE.md` = 250 padding lines → `compile_managed_text(padding, [R]).text` →
30 more padding lines; a project-scope pending record via
`create_record(..., project_path=env.host)`; `entry` from `queue(bucket)`.
Markers here come from the compiler, never typed.

- **A0 — fixture guard, asserted, not commented:** the target has ≥200 lines
  and its begin index is >60. Without A0, A passes pre-fix whenever the
  section happens to land inside the first 60 lines.
- **A1** both members of the compiler pair appear in the excerpt.
- **A2** `compilers.entry_line(R)` appears in it — the payload, not the frame.
- **A3** `excerpt.splitlines() == lines[begin-20 : end+21]`, exact list
  equality against the fixture's own indices (measured: `lines[231:274]`, 43
  lines, first `authored line 231`, last `trailing line 19`).

**B — the search misses a marker the compiler never wrote.** Fixture: 300
lines `line 0 … line 299`, indices 150 and 160 replaced by the legacy needle.
**This is the only place in the build where the legacy needle may be typed,
and the test must carry a comment saying so.**

- **B1** `excerpt.splitlines() == [f"line {i}" for i in range(60)] + ["… (truncated)"]`,
  exact. Pre-fix this returns the window around line 150, so B is red on
  today's build — and red on any case-folded fix.

### 3.1 Mutation plan

| # | One-line edit to production code | Test that must fail |
|---|---|---|
| M1 | restore the legacy needle on the **begin** line only | A |
| M2 | restore the legacy needle on the **end** line only | A |
| M3 | replace **both** needles with a case-folded token (`if "self-learn:begin" in ln.lower()`, same for end) | B |
| M4 | when both markers are found, `return "\n".join(lines)` instead of the window | A |

M1/M2 are the two halves of the shipped bug, M3 the plausible wrong fix, M4
the fail-open one (section present, prompt budget blown); M3 applied to a
single needle flips nothing, which is worth seeing. **What the criteria cannot
see:** neither A nor B distinguishes an imported `BEGIN_MARKER` from a
byte-identical re-spelled literal — §2's import rule is verified by reading
the diff at the code gate, since a source-scanning assertion would be theatre.

## 4. Builder decisions, made here rather than left open

- **Tests live in `cli/tests/test_worker.py`**, beside
  `test_canon_excerpt_unresolvable_skill_target_never_raises` (`:875`).
- **Project scope, not user scope:** the user branch reads
  `Path("~/.claude/CLAUDE.md").expanduser()` — the real host file unless
  `HOME` is redirected (FW-47 F-4). Project scope resolves through the
  sandbox bucket's `meta.yaml` and needs no redirect.
- **Keep containment (`in ln`)**, the incumbent form.
- **No new prompt-level test** — `_compose_prompt`'s use of the excerpt is
  already covered at `test_worker.py:291`.

## 5. Out of scope — report, do not fix

- **`ui/src/self_learn_ui/pane.py:266-267` carries the same wrong needle** in
  the review pane's copy of this function, and `ui/tests/test_pane.py:696-713`
  hand-writes the legacy needle into its fixture, so it is green on the broken
  behaviour. Different package, claimed by no unit, named in no design source.
- The `200` / `±20` / `60` constants, target resolution, `analyst.py`
  (U-analyst), the shared-composer factoring (U-composer).
