# Spec — U-marker: search the excerpt marker the compiler actually writes

Status: **DRAFT r1**. Unit `U-marker` of the r2 routing campaign (playbook

**Superseded in part by S-52 (2026-08-27)** — `u-ancestry-ancestor-canon-spec.md`
`SCAN1`/`SCAN8`.

**§3 criterion A — only A3 is retired.** `worker.canon_blocks` reads the whole
own-host `CLAUDE.md` under a byte cap, so **A3**'s exact
`lines[begin-20:end+21]` equality has no window to assert. **A0, A1 and A2
survive** and are re-asserted against the whole-file contract by S-52's
`SCAN1`: A0 as the fixture guard that keeps the target *fat* (which `SCAN8`
still needs), A1 as "both imported markers are present", A2 as
"`compilers.entry_line(R)` is present — the payload, not the frame". Nothing
here weakens the requirement that the compiled section reach the analyst; it
strengthens it, from a window to the whole file.

**§3 criterion B is re-homed** to `SCAN8`, guarding the **truncation path**
instead of the branch selector: over the byte cap, the managed region is
reserved first and located case-sensitively, so a case-variant the compiler
never wrote cannot capture the retained window.

**The §3.1 mutation table's disposition, one by one.** `M1` (legacy needle,
begin only) and `M2` (end only) mapped to **A**; under whole-file reading A1
is *vacuously* true — the file contains the markers whatever needle the code
searches for — so both are **carried to `SCAN8`** as its `M35`/`M36`, where an
unlocatable marker means an unreserved managed region. `M3` (case-folded short
token) and `M5` (case-folding the imported constants) mapped to **B** and are
carried as `SCAN8`'s `M37`/`M30`. `M4` (return the whole file instead of the
window) is **retired with A3** — it is the new behaviour. So all five survive
or are retired **deliberately**, none by omission.

**§2's import rule — search the markers the compiler actually writes, never a
hand-typed literal — is unchanged and still binding**, and `SCAN8` is now its
only observable consequence.

The four tests in `cli/tests/test_worker.py` that pinned A and B are rewritten
by S-52's unit, which also re-pins that file's `_ARMOR_SHAS` entry.
§2, Wave 1). Register row **FW-44**. File in scope: `worker.py`, nothing else.

**Where prose and the acceptance criteria conflict, the criteria win.** The
two marker spellings are printed ONCE each, in §1, and referred to below by
name (*the compiler pair* / *the legacy needle*). A second spelling of either
anywhere in this document — or anywhere in **this unit's diff** — is a defect.
(The compilers golden fixtures carry the compiler pair by design; they are not
in scope. §3.1 necessarily quotes the wrong needles it instructs the reviewer
to type, and the near-miss literals it warns the gate to reject — the only
exemption in this document.)

## 1. The defect — re-verified 2026-08-02, not inherited

`compilers.py`'s `BEGIN_MARKER`/`END_MARKER` module constants (currently
`compilers.py:123-124`) are the **sole writer** of a managed section; its pair
is normative per `02-schema.md:479`:

```
BEGIN_MARKER = "<!-- self-learn:begin (do not hand-edit inside; managed by self-learn) -->"
END_MARKER   = "<!-- self-learn:end -->"
```

`worker._canon_excerpt` (its logic now lives in `worker.py::canon_excerpt`,
currently `worker.py:546-588`) searches, at `:581-584`,
`"SELF-LEARN:BEGIN"` and `"SELF-LEARN:END"` — *the legacy needle*: uppercase,
no comment syntax, no parenthetical. It cannot match. Under 200 lines the file
is returned whole (`:579-580`), so the miss stays invisible until a target
grows; at ≥200 lines the function falls to `lines[:60] + "\n… (truncated)"`
(`:586`) and the analyst is shown the top of the file instead of the canon it
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
section `compile_managed_text` will not regenerate (it matches byte-exact via
`.index(BEGIN_MARKER)`/`.index(END_MARKER)`, `compilers.py::compile_managed_text`,
currently `compilers.py:240-297`, byte-exact match at `:273-274`).

This adds `worker.py`'s first import from `compilers.py`. No cycle results
(`compilers` imports only `.records`), and both names are in its `__all__`.
`compilers.py` is contended by `U-pointer`/`U-pathed`; neither touches the
marker constants, but a rename there breaks this import.

## 3. Acceptance criteria

Both criteria **must fail against unmodified `worker.py`**. Running them
pre-fix and recording the two failures IS this unit's positive control
(campaign §5): a check that has never failed has not been shown to work.

**A — a fat target's compiled section reaches the excerpt.** Fixture: the
file's own `env` fixture (`env.home` = ledger, `env.host` = host repo); a
routed record `R` (`make_behavior` + `set_routing({routed_at, destination,
by})`/`set_status("routed")`, as `test_compilers.py`'s `routed()` helper,
currently `test_compilers.py:36-39`); the host
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

**B — a case-variant of the compiler's own marker does not match.** Fixture:
300 lines `line 0 … line 299`; index 150 replaced by `BEGIN_MARKER.upper()`,
index 160 by `END_MARKER.upper()` — the compiler pair uppercased, a marker the
compiler never wrote. **Both needles are derived from the imported constants:
no marker spelling is typed in the build at all.** The fixture is red pre-fix
*because* an uppercased begin marker contains the legacy needle as a
substring — the test must carry a comment saying so, or a later editor will
quietly retire the positive control.

- **B1** `excerpt.splitlines() == [f"line {i}" for i in range(60)] + ["… (truncated)"]`,
  exact. Pre-fix this returns the window around line 150, so B is red on
  today's build — and red on **both** case-folded shapes in the table (M3, M5).

### 3.1 Mutation plan

| # | One-line edit to production code | Test that must fail |
|---|---|---|
| M1 | restore the legacy needle on the **begin** line only | A |
| M2 | restore the legacy needle on the **end** line only | A |
| M3 | replace both needles with a case-folded **short token** (`if "self-learn:begin" in ln.lower()`, same for end) | B |
| M4 | when both markers are found, `return "\n".join(lines)` instead of the window | A |
| M5 | case-fold the **imported constants** on both sides (`if BEGIN_MARKER.lower() in ln.lower()`, same for end) — the plausible "defensive" fix | B |

M1/M2 are the two halves of the shipped bug; M3 and M5 are the two plausible
wrong fixes (short-token and whole-marker case folding), and only the
case-swapped fixture in §3B catches M5; M4 the fail-open one (section present,
prompt budget blown); M3 applied to a single needle flips nothing, which is
worth seeing.

**What the criteria cannot see:** no criterion distinguishes an imported
`BEGIN_MARKER` from **any** hand-typed literal that matches the same lines —
byte-identical, a prefix of it (`"<!-- self-learn:begin"`), or the bare token.
All of them pass A and B. §2's import rule is verified by reading the diff at
the code gate: *any* marker literal in `worker.py` fails it, since a
source-scanning assertion would be theatre.

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

- **At spec time, `ui/src/self_learn_ui/pane.py` carried the same wrong
  needle** in the review pane's own copy of this function, and
  `ui/tests/test_pane.py` hand-wrote the legacy needle into its fixture, so it
  was green on the broken behaviour. That was true when this spec was
  written; it is no longer true. Different package, and already claimed:
  campaign unit **`U-marker-ui`** (`forward/r2-routing-campaign.md:83`,
  register row **FW-48**), sequenced after `U-grad-ui` — originally "report
  only, this unit must not touch it." **Shipped same day** (commit
  `f8d8433`): `pane.py` no longer
  hand-copies the search — `target_canon_excerpt` (`pane.py::target_canon_excerpt`,
  currently `pane.py:272`) now imports and delegates to the shared
  `worker.py::canon_excerpt`, and `ui/tests/test_pane.py`'s fixtures
  (`test_over_threshold_excerpts_around_markers` and siblings, currently
  `test_pane.py:696-816`) were rewritten to derive both needles from the
  imported `compilers.BEGIN_MARKER`/`END_MARKER` constants rather than typing
  them. The excerpt the **human** reads in the review pane no longer stays
  head-of-file truncated.
- The `200` / `±20` / `60` constants, target resolution, `analyst.py`
  (U-analyst), the shared-composer factoring (U-composer).
