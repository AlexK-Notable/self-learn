# U-armor — narrow the whole-file pins to the fixtures, and give the behaviour files a property guard

**r7 — SOUND.** Blind spec gate r5 (delta) returned **SOUND (0 blockers,
0 majors, 2 prose nits)**; both nits are folded here. Authored in the
throwaway worktree `.claude/worktrees/u-armor-spec`. **Anchor: `3b8e037`**
(= `fe5a012^1`, per §4.2); every measurement re-run at live master
**`6038eee`**. **42 criteria, 59 mutations.**

**Gate history — five blind rounds, every finding folded:**

| round | subject | verdict |
|---|---|---|
| r1 | spec r2 | NOT SOUND — 1 B / 10 M / 5 N (§3.5) |
| r2 | spec r3 | NOT SOUND — 1 B / 10 M / 7 N (§3.6) |
| r3 | spec r4 | NOT SOUND — 1 B / 6 M / 3 N (§3.7) |
| r4 | spec r5 | NOT SOUND — 0 B / 2 M / 4 N (§3.8) |
| **r5** (delta) | spec r6 | **SOUND — 0 B / 0 M / 2 N** |

Two rulings were **corrected by measurement and the correction adjudicated
right**: `ARM5`'s leg (c) (the count form is red on a correct tree — §3.6)
and `EXM1`'s negative control (the r4 reason string passes the widened
grammar — §3.7). Ten attack probes found across the five rounds are
promoted to mutations, each measured GREEN on the revision it was found
against and RED now.

*(r6 folded gate r4: check-then-write `--remeasure`, the pattern-matching
sweep. r5 folded gate r3: module-level `_Strip`, the date-plus-anchor
exemption grammar. r4 folded gate r2: the node census and
`ANCHOR = 3b8e037`. r3 folded gate r1. r2 folded the six open
questions — §3.4.)*

---

## 0. Reading order and precedence

1. **`03-decisions.md`** — **S-10** (behaviour never changes without a
   decision row), **S-18** (the model split this unit's gate rounds use),
   **S-52** (`U-ancestry`'s whole-file scan, the most recent row whose
   landing re-pinned armor). Where this spec and a row disagree, **the row
   wins**. This unit owes **one new row, `S-55`** (§10.1).
2. **`15-orchestration-runbook.md`** §1 (the round lifecycle — step 2 spec
   gate, step 4 code gate with the mutation mandate) and §8 (prompt
   skeletons). **This is the doc the gate protocol amends** (§4.8, §10.3):
   it is the only doc in the corpus that tells a gate what to check, and
   it says nothing today about a protected file. Measured:

   ```sh
   $ grep -rniE 'guard.amendment|guard amendment' --include='*.md' --include='*.py' . | grep -v '.claude/worktrees'
   (no output)
   ```
   Positive control, same shape, for a term that DOES exist:
   ```sh
   $ grep -c 'mutation verification' docs/specs/self-learn/15-orchestration-runbook.md
   1
   ```
3. **The three armor files themselves**, in the order §2 measures them:
   `plugins/self-learn/cli/tests/test_worker_contract.py`,
   `.../test_u_sdka.py`, `.../test_u_fake.py`.
4. **`test_lock_invariant.py`'s module docstring** (`:12-62`) — the
   fail-closed derived-property pattern this unit copies, stated there in
   its own words. It is **not** modified by this unit (§9).

**Precedence inside this spec.** §5's acceptance criteria are the spec.
Prose is rationale. Where prose and a criterion conflict, the criterion
wins.

---

## 1. Objective, and the non-objectives

**Objective.** Replace a byte-identity pin that fires on every legitimate
edit with a set of **properties** that fire only on the edits that are
actually wrong, and put all of it in **one module with one table**.

Concretely, three moves:

1. **Keep whole-file protection for the FIXTURES** — the files every other
   test stands on — and **derive** which files those are from the import
   graph instead of inheriting the set one unit happened to touch in
   August. That derivation adds `support.py` (62 importers, unprotected
   today) and drops four behaviour files.
2. **Give the BEHAVIOUR test files a property census**: every top-level
   AST node — tests, module constants, helpers, fixtures, classes,
   imports — keyed by name and compared by normalized dump, plus the
   derived exported-fixture surface. A unit may **ADD** nodes freely; it
   may not **DELETE**, **RENAME** or **EDIT** a protected node without a
   dated, anchored exemption entry.
3. **Move every pinned literal to the ANCHOR side.** This is the root
   cause in one sentence: `_ARMOR_SHAS` hashes the WORKING TREE
   (`test_worker_contract.py:781`, `hashlib.sha256(working_tree_path.
   read_bytes())`), so every head-side edit moves the pin and owes a
   re-pin. Every literal in this unit's table is measured against a fixed
   commit instead, so head-side growth never moves one. A re-pin becomes
   an **anchor advance**, done deliberately and once, not a toll every
   unit pays.

**Non-objectives, each a thing a builder might reach for.**

1. **Weakening the protection.** Every property the shipped mechanism
   actually enforces is enforced by the new one, and four are added
   (`support.py`, the derived export surface, the exemption anti-rot rule,
   and the no-shrink rule on the export set). **The proof is the measured
   red controls on each leg, not a coverage table** — `M43`-`M46` are the
   gate's own successful attacks on r2, each of which must now redden.
   *(r3, gate observation: `DEL3` is a coverage-by-assertion table and
   cannot detect that a covering leg is weaker than what it replaced. That
   is exactly how M-2/M-3/M-4 slipped past r2, so `DEL3` is no longer
   cited here.)*
2. **An eighth mechanism beside the seven.** Every existing mechanism gets
   an explicit disposition — MIGRATED, RETIRED, or KEPT AS IS — in §4.7's
   table, and `DEL1`/`DEL2` assert the retired symbols are gone from the
   tree, not merely unused.
3. **Touching `test_lock_invariant.py`.** Its `_LOCKS` / `NOT_REPO_TRUTH`
   walker is a derived property over PRODUCTION code, not over test files.
   It is a different subject with no overlap, and **`U-verbs`' `UN4`
   currently pins it byte-unchanged** (§9). KEPT AS IS, untouched.
4. **Re-litigating any past sanctioned delta.** The new anchor is this
   unit's own merge base, so every delta that landed before it is folded
   in by construction. This unit re-reviews nothing historical.
5. **Extending protection to the UI package.** `plugins/self-learn/ui/
   tests` has its own `conftest.py` and its own litter guard; it has never
   had file armor and does not get any here. Named in §7 OUT.
6. **A general "no test may ever be deleted" rule.** Deletion stays
   legal — it stays *declared*. The exemption record is the whole point.

---

## 2. Census, measured at `3b8e037`

### 2.0 Instruments, named once

Four, all quoted with their output where used:

- `git log` / `git show` / `git diff --numstat` — history and per-commit
  attribution.
- `python3` scripts over `ast` — name censuses, assert censuses, import
  graphs. Every one is pasted with the command that produced it.
- The collector, run from `plugins/self-learn/cli` as
  `env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT
  .venv/bin/python -m pytest --collect-only -q`.
- `grep -c` with an explicitly quoted positive control wherever the number
  is a count of something absent.

**No verb was run against the live ledger.** This unit touches only the
CLI test tree and three docs.

### 2.1 The mechanism as shipped — seven pins, three anchors, ten tables

```sh
$ python3 - <<'PY'
import re,pathlib
s=pathlib.Path("plugins/self-learn/cli/tests/test_worker_contract.py").read_text()
pins=re.findall(r'"(plugins/self-learn/cli/tests/[a-z0-9_/.]+\.py)": "[0-9a-f]{64}"',s)
ex=re.search(r'_SU4B_DIFF_EXEMPT = \{(.*?)\}',s,re.S).group(1)
exempt=set(re.findall(r'"(plugins/self-learn/cli/tests/[a-z0-9_/.]+\.py)"',ex))
print("pins:",len(pins)); print("exempt from the base-diff half:",len(exempt))
print("STILL base-diff checked:",sorted(set(pins)-exempt))
PY
pins: 7
exempt from the base-diff half: 6
STILL base-diff checked: ['plugins/self-learn/cli/tests/backends.py']
```

The three separate base commits the one armor system is anchored to:

```sh
$ grep -nE '^_BASE_SHA|^BASE_COMMIT|^BASE_REF' plugins/self-learn/cli/tests/test_u_sdka.py \
      plugins/self-learn/cli/tests/test_worker_contract.py plugins/self-learn/cli/tests/test_u_fake.py
test_u_sdka.py:71:_BASE_SHA = "442385d"
test_worker_contract.py:74:BASE_COMMIT = "c3b48e7"
test_u_fake.py:363:BASE_REF = "c2669a9"

$ for c in c3b48e7 442385d c2669a9 ; do git log -1 --format="$c  %ad  %s" --date=short $c ; done
c3b48e7  2026-08-19  Merge branch 'worktree-agent-ae03a086eafd87485' (U-sdka — the analyst flip; Wave 2 complete)
442385d  2026-08-19  chore(tests): re-anchor U-sdkw armor to fd694de post-merge
c2669a9  2026-08-09  chore: sync ui/uv.lock metadata for the CLI's new [sdk] extra (U-seam follow-through)
```

**One armor system, three anchors, ten declaration tables** — `_ARMOR_SHAS`
and `_SU4B_DIFF_EXEMPT` and the three `_SU4B_SANCTIONED_*` sets in
`test_worker_contract.py`; `_AR1_SANCTIONED_PIN_LINES`, five `_AR3_*`
tables, `_HY3_SCENARIO_SHAS` and `test_hy5_numstat_bounds_hold`'s inline
`bounds` in `test_u_sdka.py`; `REWRITTEN`, `DS1_ADDED`, `DS1_REMOVED` and
`_DS1_EXPECTED` in `test_u_fake.py`. Their sizes:

```sh
$ python3 - <<'PY'
import ast,pathlib
for f,names in (("test_u_fake.py",("REWRITTEN","DS1_ADDED","DS1_REMOVED")),
                ("test_u_sdka.py",("_AR1_SANCTIONED_PIN_LINES","_HY3_SCENARIO_SHAS"))):
    t=ast.parse(pathlib.Path("plugins/self-learn/cli/tests/"+f).read_text())
    for n in t.body:
        if isinstance(n,ast.Assign) and getattr(n.targets[0],"id","") in names:
            v=n.value; k=v.elts if hasattr(v,"elts") else v.keys
            print(f"{f}::{n.targets[0].id}: {len(k)} entries  (lines {n.lineno}-{n.end_lineno})")
PY
test_u_fake.py::REWRITTEN: 27 entries  (lines 84-140)
test_u_fake.py::DS1_REMOVED: 6 entries  (lines 160-167)
test_u_fake.py::DS1_ADDED: 10 entries  (lines 196-207)
test_u_sdka.py::_AR1_SANCTIONED_PIN_LINES: 396 entries  (lines 1387-1784)
test_u_sdka.py::_HY3_SCENARIO_SHAS: 10 entries  (lines 2353-2364)
```

And the prose that justifies them:

```sh
$ for f in test_worker_contract.py test_u_sdka.py test_u_fake.py ; do
    p=plugins/self-learn/cli/tests/$f
    printf '%-26s %5d lines, %4d comment lines (%d%%)\n' $f \
      "$(wc -l < $p)" "$(grep -c '^\s*#' $p)" \
      "$(( 100 * $(grep -c '^\s*#' $p) / $(wc -l < $p) ))"
  done
test_worker_contract.py     2285 lines,  626 comment lines (27%)
test_u_sdka.py              2556 lines,  627 comment lines (24%)
test_u_fake.py               913 lines,  197 comment lines (21%)
```

The `_ARMOR_SHAS` block alone, prose plus table, walking from the first
`#:` above the assignment to the closing brace of `_SU4B_DIFF_EXEMPT`:

```sh
$ python3 -c "L=open('plugins/self-learn/cli/tests/test_worker_contract.py').read().splitlines()
b=L[501:752]; c=sum(1 for x in b if x.lstrip().startswith('#'))
print(f'lines={len(b)} comment={c} non-comment={len(b)-c}')"
lines=251 comment=233 non-comment=18
```

**251 lines** (`test_worker_contract.py:502-752`), **233 of them comment**
and 18 actual table/code. *(r3, gate M-10b: r2 said 219 + 31, which is both
wrong and arithmetically impossible — it sums to 250.)*

### 2.2 The re-pin history — 41 pin writes across 15 commits

The pickaxe (`-S`) does not find these: it fires only when the *count* of a
string changes, and a re-pin swaps a hash without changing the count. `-G`
(regex over the diff) is the correct instrument, and the difference is not
academic:

```sh
$ git log --format='%h' -S'_ARMOR_SHAS' -- plugins/self-learn/cli/tests/test_worker_contract.py | wc -l
1
$ git log --format='%h' -G'^ +"plugins/self-learn/cli/tests/.*": "[0-9a-f]{64}"' \
      -- plugins/self-learn/cli/tests/test_worker_contract.py | wc -l
15
$ git log -p --format='COMMIT %h %ad %s' --date=short \
      -G'^ +"plugins/self-learn/cli/tests/.*": "[0-9a-f]{64}"' \
      -- plugins/self-learn/cli/tests/test_worker_contract.py \
  | grep -cE '^\+ +"plugins/self-learn/cli/tests/[a-z0-9_]+\.py": "'
41
```

| commit | date | unit | files re-pinned |
|---|---|---|---|
| `d2084d8` | 2026-08-28 | U-hostmode P1 gate r2 fold | conftest, test_u_fake |
| `b652992` | 2026-08-28 | U-hostmode P1 gate r1 fold | conftest |
| `83e9f37` | 2026-08-28 | U-hostmode P1 build | test_u_fake |
| `73e8010` | 2026-08-28 | FW-117 | test_invocation, test_repair, test_u_fake |
| `20773d1` | 2026-08-28 | U-cachelit | conftest |
| `801c746` | 2026-08-28 | (merge repair only) | test_u_fake |
| `0d36f76` | 2026-08-28 | U-ancestry | test_u_fake, test_worker |
| `f4ab20a` | 2026-08-28 | U-kl4 | test_invocation_sdk |
| `638fbe1` | 2026-08-28 | U-servehermetic | conftest |
| `a359229` | 2026-08-25 | U-cleanup phase B | all 6 |
| `d704aeb` | 2026-08-25 | U-cleanup phase A | all 6 |
| `a938365` | 2026-08-23 | U-flip | conftest, test_invocation, test_invocation_sdk |
| `c0a49a9` | 2026-08-19 | U-sdka merge reconciliation | conftest, test_invocation, test_invocation_sdk |
| `442385d` | 2026-08-19 | U-sdkw re-anchor | shims, test_invocation |
| `29f5d67` | 2026-08-19 | U-sdkw (the original 8) | all 8 |

**In the last 30 days: 15 commits, 41 pin writes, 9 distinct units.**
**In the last 7 days (2026-08-21 → 2026-08-28): 12 commits, 28 pin writes**
— U-cleanup A and B, U-flip, U-servehermetic, U-kl4, U-ancestry,
U-cachelit, FW-117, U-hostmode P1 (three of those commits are one unit's
build plus its two gate folds), plus the standalone merge repair `801c746`.
Measured with the same instrument, windowed:

```sh
$ git log --format='%h' --since=2026-08-21 -G'^ +"plugins/self-learn/cli/tests/.*": "[0-9a-f]{64}"' \
      -- plugins/self-learn/cli/tests/test_worker_contract.py | wc -l
12
$ git log -p --format= --since=2026-08-21 -G'^ +"plugins/self-learn/cli/tests/.*": "[0-9a-f]{64}"' \
      -- plugins/self-learn/cli/tests/test_worker_contract.py \
  | grep -cE '^\+ +"plugins/self-learn/cli/tests/[a-z0-9_]+\.py": "'
28
```

*(r3, gate M-6: r2 said 11 / 24, which reproduced under no window and
contradicted r2's own per-commit table — summing its rows dated 08-21 or
later gives 28 across 12 commits.)*

Per-file, counting `+` pin lines:

```
   9  conftest.py          6  test_invocation_sdk.py      2  shims.py (path since deleted)
   8  test_u_fake.py       4  test_repair.py              1  backends.py
   7  test_invocation.py   4  test_worker.py
```

`conftest.py` and `test_u_fake.py` are re-pinned most. `backends.py` — the
one file still covered by the base-diff half — has been re-pinned **once**,
at creation. That is the shape of a pin with a real invariant behind it,
and it is the only one in the table that has one.

### 2.3 The cost of one re-pin, measured on two units

**FW-117** (`73e8010`) deleted one dead function,
`worker.write_repair_settings_file`:

```sh
$ git show --numstat --format= 73e8010 -- plugins/self-learn/cli/src
22	53	plugins/self-learn/cli/src/self_learn/worker.py

$ git show --numstat --format= 73e8010 -- \
    plugins/self-learn/cli/tests/test_worker_contract.py \
    plugins/self-learn/cli/tests/test_u_sdka.py \
    plugins/self-learn/cli/tests/test_u_fake.py
30	4	plugins/self-learn/cli/tests/test_u_fake.py
23	5	plugins/self-learn/cli/tests/test_u_sdka.py
113	16	plugins/self-learn/cli/tests/test_worker_contract.py
```

**166 lines added to the three armor files, against 22 added to the
production file the unit exists to change.** Attributed by line shape (a
`#`-prefixed line is justification prose; a line carrying a 64-hex literal
is a pin value; the rest is table or code):

```
FW-117  test_worker_contract.py   +113 = prose  33 + pin 3 + code/table 77
FW-117  test_u_sdka.py            + 23 = prose  18 + pin 0 + code/table  5
FW-117  test_u_fake.py            + 30 = prose  18 + pin 2 + code/table 10
```

**69 lines of dated justification prose and 5 pin values** is the pure
bookkeeping toll. Stated honestly: `test_worker_contract.py`'s 77
code/table lines are *not* all bookkeeping — FW-117 genuinely added
`test_rp1a_repair_round_writes_no_settings_artifact_under_cache_dir` in
that file. The 69 + 5 figure is the part that is *only* bookkeeping.

**U-hostmode Phase 1** (`ba90ef9..d2084d8`, three commits) paid more:

```sh
$ git diff --numstat ba90ef9..d2084d8 -- \
    plugins/self-learn/cli/tests/test_worker_contract.py \
    plugins/self-learn/cli/tests/test_u_sdka.py plugins/self-learn/cli/tests/test_u_fake.py
30	4	plugins/self-learn/cli/tests/test_u_fake.py
123	12	plugins/self-learn/cli/tests/test_u_sdka.py
25	2	plugins/self-learn/cli/tests/test_worker_contract.py
```

**178 lines added: 73 prose, 5 pin values, 100 table.** The 100 table lines
are almost entirely §2.5's literal.

The surfaces a unit touching one pinned file must edit, in order:
(a) the dated paragraph above `_ARMOR_SHAS`; (b) the sha itself;
(c) `test_u_sdka.py::test_hy5_numstat_bounds_hold`'s `bounds` row for the
same path; (d) if the file is `conftest.py`, every added line pasted into
`_AR1_SANCTIONED_PIN_LINES`; (e) if the file is one of DS1's five, the
`REWRITTEN`/`DS1_ADDED`/`DS1_REMOVED` entry plus `_DS1_EXPECTED`'s count
and sha.

### 2.4 What the pin actually asserts today

`test_su4a_whole_file_armor_shas` (`test_worker_contract.py:757-790`) has
two halves. The first hashes the **working tree**:

```python
actual = hashlib.sha256(working_tree_path.read_bytes()).hexdigest()
assert actual == expected
```

The second diffs against `BASE_COMMIT` — but only over
`diff_checked = [p for p in _ARMOR_SHAS if p not in _SU4B_DIFF_EXEMPT]`,
which §2.1 measures as **one path of seven**.

So for six of the seven pinned files the mechanism reduces to: *the file's
bytes equal whatever the last unit that touched it wrote there.* That is a
change **detector**, not an invariant — it says nothing about the base, and
it is satisfied the instant the next unit updates the literal. §2.2's 41
pin writes are that mechanism running exactly as designed.

### 2.5 The 396-line literal

`test_u_sdka.py::test_ar1_tripwire_byte_unchanged` (`:1787-1805`):

```python
removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
added   = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
assert removed == []
assert added == _AR1_SANCTIONED_PIN_LINES
```

Exact list equality against a literal. Its size:

```sh
$ python3 -c "import ast,pathlib;t=ast.parse(pathlib.Path('plugins/self-learn/cli/tests/test_u_sdka.py').read_text());
print([(len(n.value.elts), n.lineno, n.end_lineno) for n in t.body
       if isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='_AR1_SANCTIONED_PIN_LINES'])"
[(396, 1387, 1784)]
$ git diff 442385d -- plugins/self-learn/cli/tests/conftest.py | grep -c '^+'
397
```
(397 counts the `+++` header line; 396 real additions — the two agree
exactly, which is what the list equality requires.)

**Every line ever added to `conftest.py` since `442385d` is pasted
verbatim, in order, into a list literal in a different file** — 397 lines,
**15.5% of `test_u_sdka.py`'s 2556 lines**. The property being expressed is
one sentence: *nothing is removed from `conftest.py`; additions only.*
§4.3's `F1` expresses that sentence with zero literals.

### 2.6 FIXTURE vs BEHAVIOUR, derived — and the 62-importer hole

The seven pinned paths were never derived. They are the files `U-sdkw`
happened to touch in `29f5d67`. Derived by import graph and content
instead:

```sh
$ python3 - <<'PY'
import re,pathlib,ast
root=pathlib.Path("plugins/self-learn/cli/tests")
for rel in ["support.py","conftest.py","backends.py","fixtures/fake_claude.py",
            "test_invocation.py","test_invocation_sdk.py","test_u_fake.py",
            "test_worker.py","test_repair.py"]:
    p=root/rel; src=p.read_text(); mod=p.stem
    tf=sum(1 for n in ast.walk(ast.parse(src))
           if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith("test_"))
    imp=[q.name for q in root.rglob("*.py") if q!=p and
         re.search(rf'^\s*(from\s+{mod}\s+import|import\s+{mod}\b)', q.read_text(), re.M)]
    print(f"{rel:26} lines={len(src.splitlines()):5}  tests={tf:3}  importers={len(imp):3}")
PY
support.py                 lines=  560  tests=  0  importers= 62
conftest.py                lines=  493  tests=  0  importers=  2
backends.py                lines=   57  tests=  0  importers=  3
fixtures/fake_claude.py    lines=  839  tests=  0  importers=  0
test_invocation.py         lines= 1975  tests= 48  importers=  1
test_invocation_sdk.py     lines= 2365  tests= 86  importers=  7
test_u_fake.py             lines=  913  tests= 17  importers=  0
test_worker.py             lines= 1655  tests= 52  importers=  9
test_repair.py             lines= 2484  tests= 54  importers=  4
```

Read down the `tests` column: **`support.py`, `conftest.py`, `backends.py`
and `fixtures/fake_claude.py` contain zero test functions.** They are pure
ground truth. The other five are behaviour suites that also export a few
helpers.

**And `support.py` — 560 lines, 62 importers, the single most depended-on
module in the CLI test tree — has no armor at all:**

```sh
$ grep -c 'support\.py' plugins/self-learn/cli/tests/test_worker_contract.py \
      plugins/self-learn/cli/tests/test_u_sdka.py plugins/self-learn/cli/tests/test_u_fake.py
plugins/self-learn/cli/tests/test_worker_contract.py:0
plugins/self-learn/cli/tests/test_u_sdka.py:0
plugins/self-learn/cli/tests/test_u_fake.py:0
```
Positive control for that zero — the same grep for a path that IS pinned:
```sh
$ grep -c 'conftest\.py' plugins/self-learn/cli/tests/test_worker_contract.py
16
```
*(r3, gate M-7: r2 printed 9. The control still functions — 16 ≫ 0 — and
the three zeros reproduce exactly, so the conclusion never depended on it;
the printed number was simply wrong.)*

`conftest.py` (2 importers) and `backends.py` (3 importers) are whole-file
pinned; `support.py` (62 importers) is not. That is the clearest possible
statement that the set was inherited, not derived.

`fixtures/fake_claude.py` is the exception that proves the design: it is a
fixture, and it is **already** guarded by properties, not bytes —
`test_su4b_fake_claude_additive_only` (§2.9).

### 2.7 The dodge — the pin makes a new file cheaper than an edit

The mechanism creates a standing incentive: adding a test **inside** a
protected file costs the multi-surface edit of §2.3; adding the same test
in a **new** file costs nothing.

For `_ARMOR_SHAS` the toll is the whole-file sha. For DS1 it is structural,
and worth stating mechanically because the table does not show it:
`_extract_guarded_functions(source, names)` (`test_u_fake.py:266-290`)
extracts **every** top-level function **minus** the declared names, and
`test_ds1` then asserts `len(head_segments) == expected_count` against the
literal in `_DS1_EXPECTED`. A newly added function is extracted on the head
side and not on the base side, so the count moves and the test reddens —
**unless the new function's name is added to `DS1_ADDED`**, which excludes
it from both sides. `DS1_ADDED`'s 10 entries are units paying exactly that
toll.

Test files created since 2026-08-01, and the subset created **after the
armor landed** (`29f5d67`, 2026-08-19):

```sh
$ git log --diff-filter=A --name-only --format= --since=2026-08-01 \
      -- 'plugins/self-learn/cli/tests/test_*.py' | sort -u | wc -l
34
$ git log --diff-filter=A --name-only --format='%h|%ad' --date=short --since=2026-08-19 \
      -- 'plugins/self-learn/cli/tests/test_*.py' \
  | awk '/\|/{c=$0} /^plugins/{split(c,a,"|"); print a[2]" "$0}' \
  | sed 's#plugins/self-learn/cli/tests/##' | sort -u \
  | grep -v 'test_worker_contract\|test_u_sdka\|test_reader_contract\|test_doctor_invocation\|test_provider' \
  | wc -l
17
```

*(The five excluded names are the armor's own cohort — the files `29f5d67`
and its siblings added in that same landing. They are not "created after
the armor"; they are the armor.)*

All **17**, with the production modules each exercises, intersected against
the union the pinned behaviour files themselves exercise (`analyst`,
`backend`, `invocation`, `ledger_ops`, `miner`, `teardown`, `worker`):

| new file | date | tests | modules shared with a pinned behaviour file |
|---|---|---|---|
| `test_u_corrob.py` | 08-28 | 62 | `analyst`, `invocation`, `miner`, `worker` |
| `test_u_ancestry.py` | 08-28 | 34 | `miner`, `worker` |
| `test_serve_hermetic.py` | 08-28 | 4 | `worker` |
| `test_litter_guard_probes.py` | 08-28 | 5 | `worker` |
| `test_hostmode.py` | 08-28 | 124 | — |
| `test_u_engine.py` | 08-27 | 31 | `backend`, `teardown`, `worker` |
| `test_serve.py` | 08-27 | 31 | `miner`, `worker` |
| `test_u_opsfix.py` | 08-26 | 5 | `backend`, `invocation`, `worker` |
| `test_u_fw100.py` | 08-26 | 7 | `miner`, `worker` |
| `test_reachability.py` | 08-24 | 60 | — |
| `test_dismiss_suspect.py` | 08-24 | 27 | — |
| `test_context_budget.py` | 08-24 | 74 | `worker` |
| `test_xscope_enumeration.py` | 08-23 | 27 | — |
| `test_u_glob.py` | 08-23 | 30 | — |
| `test_rescope.py` | 08-23 | 34 | `ledger_ops` |
| `test_refread.py` | 08-23 | 64 | — |
| `test_always_gate.py` | 08-23 | 12 | `worker` |

**11 of 17, carrying 299 tests, overlap the pinned files' subject matter,
and not one of them owed a re-pin.**

*(r3, gate M-8: r2 reported "8 of 9, carrying 179 tests". Those nine rows
and their test counts reproduce exactly — but the filter that produced them
was "since 2026-08-26", not "after the armor landed", which the surrounding
prose claimed. The corrected census over all 17 strengthens the finding:
11 files and 299 tests, not 8 and 179.)*

**What this measurement does and does not prove.** It does *not* prove
intent — a new feature legitimately gets a new file, and several of these
are exactly that. What it proves is that the mechanism has **no rule
connecting a test to the file it belongs in**, so the entire cost of the
armor falls on the one motion (editing a protected file) that is, from the
armor's point of view, indistinguishable from the motion it exists to
prevent. Two of the seventeen are the shape most clearly forced:
`test_litter_guard_probes.py` exists to positive-control a guard that lives
**inside** `conftest.py` (its own docstring: *"guard-of-the-guard for
`conftest.py`'s `_litter_namespace_guard`"*) and cannot live there, because
`conftest.py` is pinned; `test_serve_hermetic.py` was created by
`638fbe1`, the same commit that re-pinned `conftest.py`.

This unit does not propose a placement rule (§7 OUT). It removes the
incentive by making the in-file edit free.

### 2.8 Three measured instances of the armor deciding a product question

Not a hypothetical cost. Three places where the armor's bookkeeping is
recorded, in the tree, as the reason a design went one way:

1. **In production source.** `plugins/self-learn/cli/src/self_learn/
   report.py:701-706`, inside a shipped docstring:

   > *"(conftest.py carries a SEPARATE unit's armor/tripwire pins —
   > U-sdka's `_AR1_SANCTIONED_PIN_LINES` and U-sdkw's whole-file
   > `_ARMOR_SHAS` — that a new global default there would trip; reusing
   > the existing knob avoids that file entirely.)"*

   The armor selected the implementation, and the docstring says so.

2. **In a deferral rationale.** `14-forward-work-map.md` FW-129 (`:183`),
   the WATCH row refusing to surface tool events, lists among its costs:
   *"Reading a written log back additionally requires re-pinning
   `_ARMOR_SHAS["…/test_invocation_sdk.py"]`."*

3. **In a reverted fix.** `14-forward-work-map.md` FW-131 (`:185`): the
   analyst denial-visibility fix *"reverted rather than shipped"* on its
   first attempt (2026-08-27) because `test_hy5_numstat_bounds_hold` pinned
   `analyst.py`'s diff at exactly `(4, 18)` with zero headroom. It took an
   explicit coordinator ruling — quoted in that row — that *"the cap … is
   armor BOOKKEEPING, not a design constraint"* to land it the next day.

### 2.9 The property guards already in the repo — the model

Three, and this unit copies all three techniques rather than inventing one.

**`test_su4b_fake_claude_additive_only`** (`test_worker_contract.py:880-
1005`), four legs over `fixtures/fake_claude.py`: (1) every base function's
**runtime-bound** source is byte-unchanged — resolved through the imported
module, never an ast first match, because the gate's shadowing-redefinition
evasion passed under a first-match reading; (2) the new top-level function
set is exactly the sanctioned set; (3) `SCENARIOS`' key set gained only
sanctioned keys and every base key is still bound to its original function;
(4) the top-level non-`FunctionDef` statement sequence is base's, in order,
with sanctioned insertions filtered out — which catches an appended
module-level rebinding of a pre-existing global that passes legs 1-3.

**DS1** (`test_u_fake.py:695-775`), three legs over five modules: LIVE base
vs LIVE head through one extractor with the count asserted first; both
sides against a build-time `(count, sha)` literal; and a narrowed
single-function check for the one name whose license is narrower than
"excluded wholesale".

**`test_lock_invariant.py`'s walker** (`:12-62`, `_LOCKS`,
`NOT_REPO_TRUTH`) — the doctrine, in its own words:

> *"It is FAIL-CLOSED … the default classification is 'this mutates a
> repo', so new code that writes the ledger and forgets the lock FAILS this
> test. Escaping requires a human to add an explicit entry saying where it
> writes instead — a claim a reviewer can check against the function. A
> missing entry costs a false alarm; a missing surface in a hand-written
> surface list costs a silent data-loss bug."*

and its anti-rot rule, `test_the_exemption_list_cannot_rot` (`:530-538`):
every `NOT_REPO_TRUTH` entry must still name a real function, *"so a rename
or a deletion cannot leave a stale exemption quietly widening the hole."*

Two more derived-property guards exist and are **out of scope**:
`PL1`/`EV4` (`test_invocation_sdk.py:292`, `:2061`) and `BND4`/`POL2`
(`test_u_engine.py:912`, `:932-1007`). Both assert properties of
**production** code (package membership; "nothing reads a log file back";
"zero tool-name literals in the library"), not of test files. Different
subject, no overlap; KEPT AS IS.

### 2.10 The anchor-side census, prototyped

The design turns on one change: **compute every literal on the ANCHOR side,
and compare head against it.**

**The unit of protection is EVERY TOP-LEVEL AST NODE of a `Behaviour`
file** — test functions, module-level constants, unexported helpers,
fixtures, classes, imports — each keyed by name and compared by normalized
dump. Measured at `3b8e037`, what the eight files contain:

```
file                      nodes  tests  helpers  consts  cls  imports  other
test_invocation.py           94     48       19       4    4       19      0
test_invocation_sdk.py      139     86       13      11    1       28      0
test_worker.py               80     52       11       4    1       12      0
test_repair.py               85     54       14       1    0       16      0
test_attrib.py               68     47        4       2    1       14      0
test_route_cli.py            58     30       11       5    1       11      0
test_composer.py             58     32       15       1    0       10      0
test_u_fake.py               45     17        6      12    0       10      0
TOTAL                       627    366       93      40    8      120      0
```

627 = 366 + 93 + 40 + 8 + 120 exactly, and **the `other:` column is 0**
*(r5, gate M-1: r4 measured 635 with 8 `other:` nodes — the eight module
docstrings, which `_key` fell through to a content hash, so rewording one
read as a **deletion**. `_Strip` is now applied at module level before the
body is keyed, so a module docstring is not a node at all.)* r3's census
saw **366 of these 627**; the 40 constants and 93 non-test defs were
unguarded.

**The extractor, the key function and the sha**, quoted in full because a
gate must re-run them:

```python
class _Strip(ast.NodeTransformer):
    # Drop docstrings only. Every other statement is kept.
    def _s(self, node):
        self.generic_visit(node)
        b = node.body
        if (b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)
                and isinstance(b[0].value.value, str)):
            node.body = b[1:] or [ast.Pass()]
        return node
    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = visit_Module = _s

def _norm_dump(node) -> str:
    n = _Strip().visit(copy.deepcopy(node))
    ast.fix_missing_locations(n)
    return ast.dump(n, annotate_fields=False, include_attributes=False)

def _key(node) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): return f"func:{node.name}"
    if isinstance(node, ast.ClassDef):                            return f"class:{node.name}"
    if isinstance(node, ast.Assign):
        ts = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if ts: return "assign:" + ",".join(sorted(ts))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return f"assign:{node.target.id}"
    if isinstance(node, ast.Import):
        return "import:" + ",".join(sorted(a.name for a in node.names))
    if isinstance(node, ast.ImportFrom):
        return f"importfrom:{node.module}:" + ",".join(sorted(a.name for a in node.names))
    return "other:" + hashlib.sha256(_norm_dump(node).encode("utf-8")).hexdigest()[:16]

def _census(source: str) -> dict[str, str]:
    # r5: strip the MODULE docstring FIRST, then key the surviving body.
    mod = _Strip().visit(ast.parse(source))
    ast.fix_missing_locations(mod)
    return {_key(n): _norm_dump(n) for n in mod.body}

def _dump_sha(census: dict[str, str]) -> str:
    # Sort by key; join f"{key}\x00{dump}\x00"; encode utf-8; sha256 hex.
    return hashlib.sha256(
        "".join(f"{k}\x00{v}\x00" for k, v in sorted(census.items())).encode("utf-8")
    ).hexdigest()
```

`_key` is this repo's own `_stmt_key` convention (`test_worker_contract.py`,
`SU4B` leg 4), widened to cover defs and classes — a shape already gated
here, not a new invention.

**Four anchors, measured** against the `fe5a012` CLI tree — byte-identical
at live master `6038eee` (`git diff --numstat fe5a012..6038eee --
plugins/self-learn/cli` is empty):

```
ANCHOR = 3b8e037   <-- THE SHIPPING ANCHOR (= fe5a012^1, per section 4.2)
file                      nodes  missing  edited   dump_sha[:12]
test_invocation.py           94        0       1   604f7537d5c8
test_invocation_sdk.py      139        0       0   2517577cbfc3
test_worker.py               80        0       0   16e45a867ece
test_repair.py               85        0       0   f7d067023480
test_attrib.py               68        0       0   124dcc0dd69f
test_route_cli.py            58        0       0   5bb83e2da3fe
test_composer.py             58        0       0   3c920c0066c5
test_u_fake.py               45        0       0   e8655e2be886
TOTAL                       627        0       1
  edited: func:test_wr7_seam_is_only_called_from_the_three_call_sites
```

**That single `edited` is the mechanism working**, and it is the one entry
the table ships (§4.1, `EXM3`, §9.1): U-hostmode Phase 2's
`assert len(excluded_by_name) == 11` -> `== 10`, detected from the node
dump with no sha to re-pin and no dated paragraph to write.

The other three anchors are the escalating controls:

```
ANCHOR = fe5a012   (the merge itself -- what ARM5 leg (b) REJECTS)
TOTAL                       627        0       0

ANCHOR = 15fb676   (one merge further back -- Phase 1's parent)
TOTAL                       627        0       5
  incl. assign:REWRITTEN, assign:_DS1_EXPECTED (test_u_fake.py) -- CONSTANTS,
  which a test-only census cannot see at all

ANCHOR = c3b48e7   (the retired BASE_COMMIT -- everything since 2026-08-19)
TOTAL                       625       56     190
```

*(r5: the `c3b48e7` control reads **56** missing, not r4's 57 — the eighth
was that anchor's own module-docstring `other:` node, which M-1's fix
removes from the census on both sides. The 190 edited is unchanged.)*

**Module docstrings are free, and that is now measured** — the promise
§2.10, `BEH4` and §4.8 all make:

```
reword test_worker.py's module docstring -> missing=0  edited=0   FREE
reword test_repair.py's module docstring -> missing=0  edited=0   FREE
reword test_u_fake.py's module docstring -> missing=0  edited=0   FREE
   (r4 pre-state, measured by the gate: missing=1 ['other:7f24065de71d55a5'] -- RED,
    and routed through the DELETION clause, which for test_u_fake.py's docstring
    -- it contains the word "guard" -- was a BLOCKER by default)
```

**And none of the four M-1 attacks regressed under the module-level strip:**

```
assign:RECORD_QUOTE   RED      func:_gates_raises    RED
func:_run_sdk         RED      func:_wait_for_file   RED
```


**The derived exported surface** — every top-level def in a behaviour file
that another module in the tests tree imports by name, derived with
`ast.ImportFrom`:

```
file                       defs  exported  names
test_invocation.py           67         4  _clear_backend_env, _clear_config, _write_config, miner_capture
test_invocation_sdk.py       99         5  _containment, _run, _spec, sdk_absent, sdk_cli_path
test_worker.py               63         6  _path_without_real_notify_helper, _proposal_yaml, env,
                                           sdk_fake_worker, seed_pending, shim_writes
test_repair.py               68        10  _defect_script, _dump, _foreign_script, _next_run_scripts,
                                           _record_for, _stamp_sha, _t4_missing_target, _t4_target_fixed,
                                           _valid_trace, _write_script
test_attrib.py               51         0  --
test_route_cli.py            41         4  _skill_gates_yaml, env, sdk_fake_analyst, sole
test_composer.py             47         2  _doctrine_text, _pair_doctrine_examples
test_u_fake.py               23         0  --
TOTAL                       459        31
```

**31 names**, per-file `4/5/6/10/0/4/2/0`. *(r3 fixed this from r2's 20;
the derivation must use `ast.ImportFrom` — a line regex silently skips the
**11** parenthesized multi-line import sites in this tree.)* The set is
derived at the **ANCHOR** and unioned with head; `anchor_set ⊆ head_set` is
asserted separately (`BEH6`) so a shrink reddens — measured, the head-side
derivation r3 replaced shrank 31 → 30 → 25 with nothing reddening.

**Note what `B3` now subsumes.** With the census node-wide, the exported
surface leg is a *narrower* second pin on 31 of the 627 nodes, not the only
thing standing between a helper and a silent rewrite. Both are kept: `B3`
catches the edit, `B5`/`B6` catch an exported name disappearing from the
importable surface without its definition changing.

### 2.11 Live consumers of the tables

```sh
$ grep -rn '_ARMOR_SHAS\|_DS1_EXPECTED\|test_hy5_numstat' --include='*.py' plugins/ \
  | grep -v worktrees | awk -F: '{print $1}' | sort | uniq -c
      1 plugins/self-learn/cli/src/self_learn/report.py
      1 plugins/self-learn/cli/tests/test_invocation_sdk.py
      5 plugins/self-learn/cli/tests/test_u_corrob.py
      6 plugins/self-learn/cli/tests/test_u_fake.py
      1 plugins/self-learn/cli/tests/test_u_opsfix.py
      1 plugins/self-learn/cli/tests/test_u_sdka.py
      9 plugins/self-learn/cli/tests/test_worker_contract.py

$ grep -rn '_ARMOR_SHAS\|_DS1_EXPECTED\|test_hy5_numstat' --include='*.py' plugins/ | wc -l
24
```
*(r3, gate M-9: r2 printed 21 and 9 for the last two rows and its `DEL1`
cell cited "56 hits across 7 files" — three mutually inconsistent totals for
one census. The measurement is 1 / 9, total **24**. Per-token inside
`test_u_sdka.py`: `_ARMOR_SHAS` 0, `_DS1_EXPECTED` 0, `test_hy5_numstat` 1.)*

Classified by reading each hit: **`test_u_corrob.py::test_pin2_armor_sha_
paths_are_byte_unchanged` (`:1320-1340`) is the only executable consumer**
— it parses the `_ARMOR_SHAS` block out of `test_worker_contract.py`'s
source and asserts `len(pins) == 7` plus a live sha per path. It is
**retargeted, not deleted**, by this unit (§8, `DEL4`). Every other hit
outside the three armor files is prose: `report.py:703` (the §2.8
docstring), `test_invocation_sdk.py:1206` (a `#:` comment),
`test_u_opsfix.py:18` and `test_u_corrob.py:7`/`:17`/`:1040` (module
docstrings).

### 2.12 Test baselines

```sh
$ cd plugins/self-learn/cli && env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT \
    .venv/bin/python -m pytest --collect-only -q | tail -1
2666 tests collected in 0.53s
```
Per file, same instrument: `test_invocation` 48, `test_invocation_sdk` 89,
`test_worker` 52, `test_repair` 54, `test_u_fake` 17,
`test_worker_contract` 40; `test_attrib` + `test_route_cli` +
`test_composer` = 115 together.

`test_invocation_sdk` collects **89** while its top-level `def test_*` count
is **86** — three are parametrized or class-nested. The census in §2.10
counts *definitions*, the collector counts *items*; both are correct for
what they measure, and the design uses the definition count (`B5`'s pinned
literal is a definition count, and its own positive control is exactly this
mismatch: an extractor that silently switched to collected items would
print 89 and redden).

The known pre-existing UI failure
(`test_service_unit.py::test_both_units_document_manual_registration_via_symlink`)
is unaffected — this unit touches no UI file.

---

## 3. DECISION — the text `03-decisions.md` owes (`S-55`)

### 3.1 The option map

| # | Option | What it costs | What it buys | Verdict |
|---|---|---|---|---|
| **A** | **Keep the mechanism; raise the anchor periodically** (the `c0a49a9` / `442385d` "re-anchor at the merge train" motion, done on a schedule) | Nothing to build | Amortises the re-pin toll | **REJECTED.** It is what already happens — `442385d` and `c0a49a9` are both re-anchors — and §2.2 measures 24 pin writes in the 7 days *since* the most recent one. Raising the anchor does not change that a head-side sha moves on every edit; it only resets the clock |
| **B** | **Delete the armor** | Nothing to build | The whole toll | **REJECTED.** §2.9's `SU4B` legs 1 and 4 each name a *specific evasion a gate actually attempted and the leg actually caught* (a shadowing redefinition; an appended module-level rebinding of a pre-existing global). The mechanism catches real things. The defect is its granularity, not its existence |
| **C** | **Narrow the pin set to the fixtures and leave the behaviour files unguarded** | Small | Removes ~80% of the toll (§2.2: 25 of 41 pin writes are behaviour files) | **REJECTED.** It drops the one property that matters most on a behaviour file — that a test is not quietly deleted or weakened — and DS1 exists precisely because that property was worth guarding on five modules |
| **D** | **Narrow to fixtures + give behaviour files a property census, all in one module, every literal anchor-side** | One module, ~8 criteria of build, three docs | Keeps every property; removes the toll on additions; closes the `support.py` hole; collapses 3 anchors and 10 tables into 1 and 1 | **RECOMMENDED** — §3.2 |
| **E** | **D, plus a placement rule** ("a test asserting `worker` behaviour must live in `test_worker.py`") | A large, contested derivation over 34+ files | Would close §2.7's dodge directly | **REJECTED for this unit, not refused outright.** §2.7's own honest reading is that the dodge is an *incentive*, not a violation, and D removes the incentive. A placement rule is a separate decision about suite structure and would need its own census. Recorded as a WATCH row (§10.2, `FW-141`) |

### 3.2 The recommendation — option D, and the sentence it rests on

**A pin should assert an invariant, not a snapshot.** The seven whole-file
pins assert a snapshot (§2.4: six of seven compare head against a literal
that the last unit to touch the file wrote), so they fire on every change
— correct and incorrect alike — and the only available response is to
update the literal. `backends.py`, the one pin that still compares against
the base, has been re-pinned once in 30 days; the other six, 40 times.

The invariants actually worth holding are three, and each has a different
correct shape:

1. **A fixture is ground truth: what is there must not change.** Shape:
   **whole-file byte identity against the anchor**, with a dated re-pin as
   the only door (§4.3). `conftest.py` grew 396 lines since `442385d`, and
   under this rule each of those landings owes one sha and one dated line
   in the one table — instead of today's four surfaces, and instead of a
   396-line verbatim literal in a different file. *(r3, gate M-2: an
   earlier revision made this "append-only", which measurably let an
   appended global rebinding through on all three fixtures.)*
2. **A behaviour test is a captured decision: it must not be deleted,
   renamed, or weakened.** Shape: an anchor-side census, subset-checked
   against head. Additions are free by construction, because a superset
   satisfies a subset check.
3. **A fixture that lives inside a behaviour file is still ground truth.**
   Shape: byte-identity, over the **derived** set of names other modules
   import (31 of 459 top-level defs — §2.10), so nobody declares it and a
   new consumer extends the protected set automatically.

`S-55` is the row that records this and the two rules that follow from it:
*every armor literal is measured on the anchor side*, and *advancing the
anchor is an orchestrator motion at a merge train, never a unit's own
edit*.

### 3.3 Designs rejected, with the measurement that rejected each

- **Pin every protected node's source as a literal.** Rejected: §2.10
  measures **627 protected nodes** across the eight files. As literals that
  is a second `_AR1_SANCTIONED_PIN_LINES`, and a far larger one. The
  anchor-side recovery (`git show <ANCHOR>:<path>`) needs zero literals for
  the same discrimination — DS1's leg 1 already proves the technique works.
- **Live-base-vs-live-head only, with no pinned literal at all.** Rejected
  by DS1's own leg-2 rationale (`test_u_fake.py:704-714`): *"An extractor
  that returns nothing (`M17`) cannot silently agree with this pin, because
  the pin does not move merely because the extractor broke."* A live-only
  check passes vacuously when the extractor breaks. `B5` keeps exactly one
  small anchor-side literal per file (a count) for this reason, and §2.12
  names the concrete confusion it would catch (86 definitions vs 89
  collected items).
- **Keep `test_hy5_numstat_bounds_hold`'s insertion ceilings, widened.**
  Rejected on two measurements: the test is fail-open on an untouched row
  by its own admission (`test_u_sdka.py`, the `NIT-8` comment: *"a row
  whose file turns out UNTOUCHED (empty numstat output) SKIPS its bound
  check entirely"*), and §2.8's third instance is a real fix reverted
  because a ceiling had zero headroom. A ceiling on insertions has no
  invariant behind it — "this file may grow by at most N lines" is not a
  property of the system, and every unit that touches the file must
  re-measure it.
- **A separate module per kind** (`armor_fixtures.py`, `armor_behaviour.
  py`). Rejected against the mandate's own words ("one mechanism … not an
  eighth mechanism beside seven") and against §2.1's finding that the
  present cost is precisely three anchors and ten tables in three files.
- **Putting the table in `conftest.py`** so it is loaded once. Rejected:
  `conftest.py` is itself a protected fixture under `F1`, and a table that
  changes when a protected file changes cannot live inside a protected
  file.

---

### 3.4 Rulings — orchestrator, 2026-08-28

All six of r1's open questions are RULED. The reasoning is recorded here
because each ruling now binds a criterion, a doc edit, or the landing
order; §11 is the index.

| # | r1 recommendation | Ruling | What it changed in this spec |
|---|---|---|---|
| **Q-1** | Skip `FW-139` | **ACCEPTED.** The number is a **tombstone** in the U-verbs spec — minted at its r4, withdrawn at its r5, still spent in its text. Say so in the FW table's own ordering note | §10.2's ordering note now calls it a tombstone by name |
| **Q-2** | Keep `test_u_fake.py` as a `Behaviour` row | **ACCEPTED**, unchanged | Nothing; §4.1's table already carries it |
| **Q-3** | Golden fixtures OUT | **ACCEPTED.** The ~15-line anchor-side shape goes in as a one-paragraph *"if ever wanted"* note, **not** a criterion | §4.3 gains the note; §7 OUT 7 unchanged; no criterion added |
| **Q-4** | Manual anchor advance | **ACCEPTED, with one binding addition: the anchor is advanced BY THE LANDING CHAIN, not by a builder.** After every merge to master the orchestrator's landing chain re-anchors, and the merge commit's diff against the previous anchor is the gate's evidence. The exact command is specified, and a stale anchor must be reported loudly **by the census itself** | §4.2 rewritten with the two commands; §4.8's anchor clause rewritten; **new `ARM5`** + **`M36`**; `FW-140` re-scoped to the residual that survives |
| **Q-5** | U-armor before U-hostmode P2 | **OVERRULED, with the measured reason:** Phase 2 is already gate-verified and landing within the hour, and the collision cost r1 measured (the `test_wr7` re-pin: sha + dated paragraph + `hy5` re-measure) has **already been paid on its branch**. Landing U-armor first would idle a finished unit to save a cost already spent | §9 rewritten: **U-armor lands AFTER Phase 2**; the builder's first step is re-running every §2 number against post-Phase-2 master; §9.1's collision is kept, re-framed as the **worked example of what the old armor costs** |
| **Q-6** | Single file `test_armor.py` | **ACCEPTED**, unchanged | Nothing; §4.1 already specifies it |

**One further instruction, folded alongside the six:** the spec must state
explicitly what happens to the two-gate process doc, as an **owed edit with
its own DOC criterion**, and the retired mechanisms' names must appear in a
**"retired names" list** so a future grep finds no live reference. §10.3 is
the owed edit, **§5.9 `DOC1`/`DOC2`** are the criteria, and **§13** is the
list — with today's count as its positive control.

---

### 3.5 Blind spec gate r1 — every finding, and what changed

**Verdict NOT SOUND: 1 blocker, 10 majors, 5 nits, 0 docs.** The gate
re-ran every quoted number in a detached read-only checkout at `3b8e037`.
The central census reproduced **to the digit** — 366/1434/0/0 at `3b8e037`
and 374/1464/35/49 at `c3b48e7`, per-file included — as did the 30-day
history, both cost measurements, the import graph, `ARM5`'s three
predicates and the `ba90ef9` control. The findings are design holes and
instrument errors, not a rejection of the design.

| # | Finding | Ruling and fold |
|---|---|---|
| **B-1** | `ARM5`'s legs (b)+(c) mean *"master's tip is the merge, with nothing after it"* — but r2's chain wrote `test_armor.py` **after** the merge commit, and that rewrite must itself be committed, so leg (c) reads 1. Amending the merge changes its sha and breaks leg (a). **The unit could not land green.** `801c746` is live precedent for the post-merge re-derivation commit | **RULED (orchestrator).** The re-anchor is **not a separate commit**: the chain runs `--remeasure` while the merge is still `--no-commit`, so the advance rides **inside** the merge commit — already this repo's house rule for armor pins. The chicken-and-egg (a commit cannot embed its own sha) is resolved by **defining `ANCHOR` as the first-parent PARENT of the merge**, which exists before the merge does. §4.2 rewritten; `ARM5`'s three legs re-derived and re-measured (§4.2); new red controls `M36`/`M37` |
| **M-1** | The export surface is **31, not 20**; r2's figure reproduces only under a line regex that skips all **11** parenthesized multi-line imports, and `BEH5`'s single-line control could not discriminate | **Accepted.** §2.10 restated at 31 (`4/5/6/10/0/4/2/0`); the derivation is specified as `ast.ImportFrom` and a line regex is forbidden **in the criterion text**; `BEH5`'s control is now a multi-line import |
| **M-2** | `F1`'s ordered-subsequence match lets an **appended module-level rebinding of a pre-existing global** through on all three fixtures — the exact evasion `SU4B` leg 4 was hardened for. `F2` is scoped to `def`/`class` and does not cover it. Falsifies §1 non-objective 1 | **RULED (orchestrator): FIXTURES STAY WHOLE-FILE BYTE-PINNED.** That was the original ruling and it stands. §4.3 rebuilt: `F1` is a whole-file sha against the anchor bytes; a fixture edit costs a re-pin with a dated justification, **which is correct — fixtures are ground truth**. The subsequence idea survives only as `F2`, an **additional diagnostic** that names *what* changed and can never pass something `F1` fails |
| **M-3** | The assert-multiset census is blind to everything that is not an assert. Measured: flipping one setup line in `test_worker.py::test_dead_pid_window_reopens` leaves `B1`/`B3` **green** while the old whole-file sha goes red; and **40** `pytest.raises` blocks across the eight files can be deleted or widened invisibly | **RULED (orchestrator): pin each protected test's NORMALIZED AST DUMP.** Docstrings stripped, line/col dropped. A changed dump is `edited` and needs a named, dated exemption the gate reviews; a vanished name is `missing`. **Assert counting is retired.** Both probes now measured RED (§4.5). Sensitivity over `c3b48e7`: 49 edited → **169** |
| **M-4** | `B4` derives the protected export set **head-side**, so deleting an unprotected importer shrinks protection inside the same diff (31→30, 31→25 measured); nothing reddens. Fail-open on removal | **Accepted.** The set is derived at the **ANCHOR** and unioned with head; `anchor_set ⊆ head_set` is asserted separately (`BEH6`) so a shrink reddens. New mutation `M42` |
| **M-5** | `UN4` has no mutation anywhere and `UN1` has no §6 row; §6's completeness claim is false | **Accepted.** Both get §6 rows (`M40`, `M41`); the total is restated |
| **M-6** | 7-day pin statistics do not reproduce: **12 commits / 28 writes**, not 11 / 24 — and r2's own per-commit table summed to 28 | **Accepted.** Corrected in §2.2 and in `S-55` |
| **M-7** | §2.6's positive control prints 9; measured **16** | **Accepted.** Corrected; the control still functions (16 ≫ 0) and the conclusion never depended on it |
| **M-8** | "the nine created after the armor landed" — the stated filter selects **17** | **Accepted.** §2.7 re-derived over all 17: **11 overlap, 299 tests** (was 8 / 179). The finding is strengthened, not weakened. `FW-141` updated |
| **M-9** | Consumer census: **1 / 9**, total **24** — r2 carried three mutually inconsistent totals (column sum 57, `DEL1` cell 56, measured 24) | **Accepted.** Corrected in §2.11 and in `DEL1` |
| **M-10** | (a) the three `test_u_fake.py` table ranges were hand-filled, not script output; (b) the 251-line block is 233 comment, and r2's "219 + 31" sums to 250 | **Accepted.** Both re-run and pasted |
| **N-1** | §13 says 21 constants and lists 22; `DEL1`'s alternation omits `_FAKE_CLAUDE_RELPATH`, so `DOC2` and `DEL1` could not both be satisfied | **Accepted.** 22 everywhere; `_FAKE_CLAUDE_RELPATH` added to `DEL1` |
| **N-2** | §12 item 3 cites a stale "34 criteria" | **Accepted.** *(r4, gate N-1: this cell said "Now 41", which was itself wrong — r3 shipped 38. r4 ships 41; §5.9 states the count once and is the authority.)* |
| **N-3** | Header says r1 on an r2 document | **Accepted.** Header is r3 |
| **N-4** | Three anchor tests carry no assert at all, so `B3` was vacuous for them | **Accepted, and subsumed:** dump identity covers a body with no asserts exactly as it covers any other. Named in §12 with the three test names |
| **N-5** | The `sed -i` re-anchor has no positive control; a 8-char short sha would leave `OLD_ANCHOR` empty and the `sed` would silently no-op | **Accepted.** `--remeasure` now rewrites the literal itself (it already parses the file) and **exits non-zero if the anchor did not change**; the chain is an `&&`-chain so a no-op aborts the landing |

**One gate observation recorded, not a finding:** `DEL3` is a
coverage-by-assertion table — it checks that each of §4.7's dispositions
*names* a covering test and that the test exists, so it cannot detect that
a covering leg is *weaker* than what it replaced. That is exactly how M-2,
M-3 and M-4 slipped past. §1 non-objective 1 no longer cites `DEL3` as
proof that nothing was dropped; the proof is now the measured red controls
on each rebuilt leg.

**One stale framing corrected:** `S-54` is **already present** in
`03-decisions.md:68` at `3b8e037` (it landed with the U-verbs *spec* merge
`15fb676`), so §9.3's "reserved" column for that row was out of date.
`S-55` is genuinely free and remains correctly claimed.

---

### 3.6 Blind spec gate r2 — every finding, and what changed

**Verdict NOT SOUND: 1 blocker, 10 majors, 7 nits, 0 docs.** The gate
confirmed all three r1 design holes measurably shut — the fixture sha
reddens on all three appended-rebinding controls, both r1 probes go RED
under dump identity, the export set is 31 and cannot shrink — and added two
attacks r3 also survives (an alias rename, and `@pytest.mark.skip` on a
protected test). Nine of ten number clusters reproduced. What blocked it
was new: the `ANCHOR` redefinition that fixed r1's B-1 was never carried
into the table it governs, and one class of change was still invisible.

| # | Finding | Ruling and fold |
|---|---|---|
| **B-1** | §4.1 shipped `ANCHOR = "fe5a012"` — the merge itself — which is verbatim the value §4.2's own third red control declares STALE. Under the correct value (`M^1` = `3b8e037`) the census reports 1 edited, contradicting `EXM3`'s "ships empty", §4.1's "every door shut" and §9.1's "no `edited` entry is owed" | **RULED (orchestrator).** Ship `ANCHOR = "3b8e037"` exactly as §4.2 defines it. **The one `edited` entry is the mechanism working, not a defect** — it is Phase 2's `== 11` -> `== 10`. `EXM3` is rewritten from *"ships empty"* to *"ships with exactly the entries the anchor→HEAD diff owes, each carrying a dated reason"*, with the entry count asserted equal to the census's own edited count. All sixteen literals re-derived at `3b8e037`; §9.1's closing paragraph rewritten to say the opposite of what it said |
| **M-1** | The census walks `test_*` defs only, so everything else in a protected file is unguarded: **40 module-level constants and 62 unexported helpers**. Measured GREEN on `test_repair.py::RECORD_QUOTE` (read by 10 protected tests) and on gutting `test_invocation.py::_run_sdk` (called at 22 sites by 9 tests), `_gates_raises`, `_wait_for_file` — all four RED under the old whole-file sha. §1 non-objective 1 still false | **RULED (orchestrator): protect EVERY top-level AST node**, keyed by name (functions/classes) or target name (assignments), compared by normalized dump. §2.10 re-derived at all four anchors as **635 nodes**, not 366 tests. All four attacks now measured **RED** (§4.5). `B5`/`B6` demoted from "the only guard on a helper" to a narrower second pin |
| **M-2** | `B2` (`missing` cannot rot) and `B4` (`edited` cannot rot) map to **no criterion**; §4.6 claims `BEH2`/`BEH4` enforce them but those test "adding is free" and "a docstring reword is not an edit". `M22` could not redden its named criterion | **Accepted.** Two new criteria, **`BEH8`** and **`BEH9`**, each with a mutation that reddens exactly it (`M51`, `M52`); `M22` re-mapped to `BEH8` |
| **M-3** | The sixteen `dump_sha` literals are unreproducible — no algorithm given, and none of eight plausible conventions matched any value | **Accepted.** `_dump_sha` is quoted beside `_census` in §2.10 (sort by key; join `key\0dump\0`; utf-8; sha256) and **all sixteen literals re-derived under it** |
| **M-4** | `GATE1` greps for `retired` — a keyword r3 renamed away — so a correct build reddens it. Measured over §4.8's own text: `retired` **0**, `weakened` 1, `missing` 2, `edited` 3, `repinned` 1. And it says "five clauses" where §4.8 has **six** | **Accepted.** Keywords are now `missing` / `edited` / `positive control` / `repinned` / `edited_exports` / `ANCHOR`; clause count **six** |
| **M-5** | §4.8's *"Edited fixtures … `Fixture.edited`"* bullet names a field r3 deleted, and that text is inserted **verbatim into the runbook** — every future gate would be told to review a field that never exists | **Accepted.** The dead bullet is deleted; the preceding "Re-pinned fixtures" bullet already covers it. `M8` re-mapped |
| **M-6** | `EXM3` enumerates `edited`/`retired`/`weakened`/`edited_exports` — two of which are retired names — and never checks `Fixture.repinned` or `Behaviour.missing`. Its control cites r2's retired 35 + 49 | **Accepted.** `EXM3` covers the four live doors and, per B-1, asserts the owed-entry rule rather than emptiness. Control re-derived: **57 missing / 190 edited** at `c3b48e7` under the node census (35 / 170 under r3's test-only view) |
| **M-7** | `M6`/`M7` point at `FIX2` but reddens `FIX1`; `M8` names the dead `Fixture.edited` and points at `FIX4`. So `FIX1` had only `M45`, and `FIX2`'s anti-rot leg had no row | **Accepted.** `M6`/`M7` → `FIX1`; `M8` rewritten to a stale `repinned` entry → `FIX2` |
| **M-8** | `DEL1`'s control still says 183; r3's own alternation (with `_FAKE_CLAUDE_RELPATH`) measures **185** | **Accepted.** 185 in `DEL1`, §8's builder note and §13 |
| **M-9** | Three of four anchor blocks were measured against a head one merge stale: `15fb676` is 3 edited not 2, `c3b48e7` is 170 not 169, and the collector is **2666** not 2687 | **Accepted, and superseded by M-1's re-derivation** — all four blocks re-run at one head under the node census (§2.10). Collector **2666**; `UN3` restated |
| **M-10** | §12 item 1 and `FW-141` — which lands in a permanent doc — still say "9 files / 8 of 9 / 179 tests" though §3.5 records them as updated | **Accepted.** Both restate **17 / 11 / 299** |
| **N-1** | §3.5's N-2 cell says "Now 41"; the count was 38 | Corrected (and r4's count is now stated once, in §5.9) |
| **N-2** | §3.2 rule 1 still says fixtures are *"append-only … additions anywhere are free"*; rule 3 still says "20 of 459" | Both corrected to the whole-file ruling and 31 |
| **N-3** | `S-55` — permanent text in `03-decisions.md` — still describes r2's retired design (*"append-only"*, *"assertion multisets"*, *"WEAKEN"*, *"`F1`-`F3`/`B1`-`B5`"*) | **Rewritten wholesale** to r4's design, and made a **criterion**: `DOC4` greps the row for retired vocabulary with r2's text as the positive control |
| **N-4** | `FW-140` names the retired doors and cites `F3`/`B2`/`EXM2` wrongly | Rewritten; also covered by `DOC4` |
| **N-5** | Retired vocabulary residue in §0, §3.3, §4.7 row 4, §12 item 5 | All four corrected |
| **N-6** | §2.7's `test_hostmode.py` cell says 114; measured **124** after Phase 2 | Corrected; the 17-file total is **631**, and `11 / 299` is unaffected (that file shares no module) |
| **N-7** | `FIX4` overclaims — "no code path consults `F3` before `F1`" is checked by a structural proxy; and §6's mutation table is split by a blank line into two Markdown tables | `FIX4`'s statement narrowed to what its instrument proves; the stray blank line removed |

**One deviation from the ruling, with the measurement that forced it.**
The B-1 ruling specified leg (c) as `git rev-list --count ANCHOR..master^ == 0`.
**That is RED on live master right now**, because `37f48c4` (the landing
chain's own docs-only scrub) sits on top of the merge, so `master^` is the
merge rather than its parent:

```sh
$ git rev-list --count 3b8e037..37f48c4^     # master^ = fe5a012 = the merge M
4                                            # RED -- and nothing is actually wrong
$ git rev-list --count 3b8e037..fe5a012^     # the same predicate when the tip IS the merge
0                                            # GREEN
```

Shipping that form would reproduce B-1 exactly one round later: a criterion
red on a correct tree. §4.2's leg (c) is therefore the predicate the ruling
was reaching for — **no protected file moves after the anchor merge** —
which is satisfiable, expresses the actual invariant, and still
discriminates (§4.2's controls). Routed here rather than decided silently.

---

### 3.7 Blind spec gate r3 — every finding, and what changed

**Verdict NOT SOUND: 1 blocker, 6 majors, 3 nits, 0 docs** — and the gate
calls it *"the strongest revision by a wide margin"*. Both r2 blockers are
gone; the node census reproduces **to the digit at all four anchors**; for
the first time **all sixteen `dump_sha` literals recompute exactly** under
the quoted algorithm; six previously-GREEN attack probes are RED; and four
new attacks the gate ran against r4 (decorator argument, nested function,
class body, import-source swap) are all caught. **The `ARM5` leg-(c)
deviation is adjudicated SOUND and ships.** What remained was one internal
contradiction, one real misclassification, and four rows that did not
travel with their rulings.

| # | Finding | Ruling and fold |
|---|---|---|
| **B-1** | The one exemption entry the design must ship **fails `EXM1`**, the criterion governing it: `EXM1` requires `§\d` or `FW-\d+`, and `_P2` writes *"section 9.1"*. Systematic — every Python block writes "section N" where prose writes "§N". And it recurs at every landing, since §4.2 said `--remeasure` writes *"every owed exemption entry"* and a tool cannot invent a citation | **RULED (orchestrator), two parts.** (1) **Exemption entries are written ONLY by humans/builders — never by `--remeasure`.** The tool's job on an owed-but-unexempted node is to **refuse**: exit non-zero naming the nodes, which is the loud path. §4.2 states this and §4.1's `--remeasure` contract drops the "writes entries" clause. (2) `EXM1`'s grammar becomes **a date AND an anchor**: `20\d\d-\d\d-\d\d` plus at least one of `§\d`, `FW-\d+`, `S-\d+`, or a 7–40-hex sha. `_P2` rewritten to satisfy it |
| **M-1** | A **module-docstring reword is classified as a deletion**. `_census` iterated `ast.parse(source).body` directly, so the module docstring survived as its own node and fell through `_key` to `other:<hash of itself>` — the key *is* the content, so a reword changes it. Measured `missing=1` on `test_worker.py` and `test_repair.py`. Worse: a `missing` key routes through §4.8's *"Deleted or renamed nodes"* clause, and `test_u_fake.py`'s module docstring contains the word `guard` — a **BLOCKER by default**. This contradicts §2.10, `BEH4` and §4.8, all three of which promise a docstring reword is free | **RULED (orchestrator).** `_Strip` is applied **at module level** before the body is keyed, so the module docstring is not a node at all. Re-measured: the `other:` column falls to **0** across all eight files and the census is **627 nodes** (was 635 — exactly the eight docstrings). All four anchors restated. `BEH4`'s control extended to module scope; §4.8's guard-in-docstring BLOCKER rule now says **test bodies only** |
| **M-2** | `M47` asserts a post-merge commit reddens leg (c). Measured at its own cited tip (`801c746`, merge `8d3d5bc`): **0 protected files moved**, so leg (c) stays GREEN — which is precisely what the §3.6 deviation exists to guarantee. As written it would force the census back to the count form the deviation rejects | **Accepted.** `M47` re-framed as a **third inverted-shape row**: a commit that touches nothing protected must redden **nothing**. Its cited evidence is now `801c746`'s own numstat (one file, `test_worker_contract.py`, which is not protected) |
| **M-3** | `M36` claims legs (b) **and** (c) at `ANCHOR=ac2161a` with "count 4". Measured: **(a) rc=0, (b) STALE, (c) = 0** — only (b) fires; `ac2161a` is itself a merge (2 parents), not a merge's parent; and "count 4" is the retired leg-(c) form. §6's summary sentence depended on it | **Accepted.** `M36` re-pointed at **`15fb676`** (a genuine merge's parent), states **leg (b) only**, and the count cell is dropped. §6's summary sentence rewritten: `M36` isolates (b), `M55` isolates (c) |
| **M-4** | `M2` says `ARMOR["test_worker.py"].tests: 52 → 51` — the field is `nodes` and the value is **80**; `M25` cites `35 + 169`, the retired assert-census figures | **Accepted.** `M2` → `.nodes` **80 → 79**; `M25` → **56 + 190** |
| **M-5** | Two §4.6 paragraphs contradict folds already made: *"All eleven rows ship with every door shut"* (the B-1 fold says one entry ships) and *"`FIX2`/`BEH2`/`BEH4` require that each entry's subject still exists"* (the anti-rot criteria are `FIX2`/`BEH8`/`BEH9`, which `FW-140` states correctly) | **Accepted.** Both paragraphs rewritten to the `EXM3` truth and the correct criterion mapping |
| **M-6** | `DOC4` **reddens on the very rows it governs**. Measured: `S-55` has `append-only` = 1 (legitimate prose naming the *rejected* shape) and `repinned` = 0; `FW-140` has `node` = 0 and `dump` = 0. And the criterion never says whether the positive greps are per-row or over the union | **Accepted.** The greps are **per row**, stated. `S-55` reworded to drop the literal `append-only` and to name `repinned`; `FW-140` gains `node` and `dump`. Re-measured: both rows now pass every leg |
| **N-1** | §4.8's first two bullets still say *"tests"* where `GATE1` calls them nodes, and the positive-controls bullet says *"weakened"* — retired vocabulary in text inserted verbatim into the runbook | Corrected to **nodes**; `weakened` dropped |
| **N-2** | `other:` keys are content hashes, so an edit to such a node reads as a delete. After M-1's fix the class is **empty** (measured: 0 `other:` nodes, and 0 top-level `Assign` nodes with a non-`Name` target), but a future tuple-unpack assignment would inherit it | Recorded in §12 as a **latent** class with the measured zero |
| **N-3** | §12 item 3 says "38 criteria" (41), item 4 says the census dumps "366 test functions" (627 nodes), item 5 says the `c3b48e7` control shows "49 tests changed assertions" (190 edited) | All three corrected |

**One correction to a ruling, measured.** The B-1 ruling asked that
`EXM1`'s positive control be *"the r4 reason text must FAIL the grammar"*.
**It passes.** The widened grammar accepts a 7–40-hex sha as an anchor, and
the r4 string contains `fe5a012` and `2026-08-28`:

```
r4 reason: date=True  anchor=True  ->  PASS
```

The r4 string's actual defect was narrower than the ruling assumed — it
wrote `section 9.1` where the *old* `§\d|FW-\d+` grammar demanded a `§`,
and widening the grammar is exactly what fixes it. So `EXM1`'s controls are
five strings that genuinely fail, each isolating one half (§5.5), rather
than a string that now passes.

---

### 3.8 Blind spec gate r4 — every finding, and what changed

**Verdict NOT SOUND: 0 blockers, 2 majors, 4 nits, 0 docs** — the first
round with no blocker. The gate verified **every r3 finding folded**: the
module-level `_Strip` lands as specified (627 nodes, `other:` = 0,
docstring rewording free on all three probes, none of the four M-1 attacks
regressed), all eight `dump_sha` literals recompute exactly, all four
anchors reproduce to the digit, `EXM1`'s grammar behaves across all eight
controls, `M2`/`M25`/`M36`/`M47` are correctly re-pointed, `DOC4` passes
per-row, and `--remeasure` no longer writes exemptions. **The r5 correction
to the B-1 ruling is adjudicated right and accepted.**

| # | Finding | Ruling and fold |
|---|---|---|
| **M-1** | The retired **635** survives in two live places — one of them `S-55`, which lands permanently in `03-decisions.md` and whose own breakdown (366+93+40+8+120) sums to **627** — and `BEH7`'s MEASURED cell. **And §12.1's sweep, built to catch exactly this, reported `LIVE = 0`.** The defence ("the same instrument finds 14 hits in the legitimate regions") is a control for the **matcher**, not the **classifier** | **Accepted, and the diagnosis sharpened by measurement.** Both numbers corrected. The sweep's failure was **matcher narrowness**, not misfiling: its terms were exact literals (`"635 nodes"`) and the live text says `"635 top-level nodes"` and `"(635 vs 366)"`, neither of which contains that substring — and it carried no term for `49` at all. r6 sweeps **regex patterns**, and adds the classifier control the gate asked for: `historical + cited + live == raw match count`, asserted, so a hit cannot vanish by being filed. Re-run pre-fix it reports **5 LIVE** (the gate's three plus two the gate did not find); post-fix, **0**. §12.1 carries both runs |
| **M-2** | `--remeasure`'s ordering and atomicity are unspecified, and under the write-then-refuse ordering **the landing chain deadlocks**: the literals are already advanced when the refusal fires, so the post-fix re-run trips the no-op guard instead, and the only escape is the hand-edit `ARM2` exists to catch | **RULED (orchestrator): check-then-write, never write-then-refuse.** §4.2 now fixes the order in six steps — resolve, census, compute the owed set, **refuse writing nothing**, then render the whole module to a temp file and `os.replace()` it atomically, then the no-op guard. **New `ARM6`**: a refusing `--remeasure` leaves `test_armor.py` byte-identical, `sha256` before == after. **New `M57`**: move the write above the check ⇒ RED. §4.2 states why the re-run then succeeds — the anchor literal genuinely changes in *that* run |
| **N-1** | §12 item 5 still cites r2's retired **49 tests changed assertions** | Corrected to **190 nodes edited and 56 missing**. (It was the third live hit the sweep missed.) |
| **N-2** | `EXM1` accepts an unresolvable anchor — measured, `"2026-08-28 deadbee: sanctioned by a commit that does not exist."` passes. Grammar only, never resolved | **Closed, not merely stated** *(my call, per the ruling's latitude)*. `EXM1` gains a second leg: any 7–40-hex anchor must satisfy `git cat-file -e <sha>^{commit}`. Measured: `deadbee` does **not** resolve; `fe5a012` and `3b8e037` do. **New `M58`**. The residual is named: a sha that resolves but is irrelevant still passes, and that is §4.8's human review, not a grep's job |
| **N-3** | A protected file **deleted outright** is unspecified. Against an empty head the census is correct (58 missing of 58, RED), but a real deletion makes `open()` raise `FileNotFoundError` — fail-closed, but a traceback rather than a message | **Accepted.** `BEH1` gains a leg: a missing protected path is caught and reported as `protected file <path> missing — every node missing; refuse`, naming the path. **New `M59`** |
| **N-4** | "live master" names `37f48c4`; master is `6038eee`. Every census number still reproduces (the CLI tree is byte-identical), but the count-form figure the deviation cites now reads **5**, not 4 | Corrected throughout; §4.2 and §3.6 already carried both readings, and the head is now named `6038eee` |

---

## 4. Design

### 4.1 One module, one table

**New file: `plugins/self-learn/cli/tests/test_armor.py`.** It carries the
anchor, the single table, the extractors, and every enforcing test. There
is no second file: the table is not imported by anything else, so splitting
it into `armor.py` + `test_armor.py` would buy nothing and would cost the
reader a second place to look. (This is the mandate's "one module, one
table", with the name chosen so the collector picks it up directly.)

```python
ANCHOR = "3b8e037"   # the first-parent PARENT of the latest first-parent
                     # merge (fe5a012^1), per section 4.2. The landing
                     # chain rewrites this via --remeasure, never a human.

@dataclass(frozen=True)
class Fixture:      # whole-file byte pin, anchored (section 4.3)
    repinned: tuple[str, str] | None = None   # (sha256, dated reason) -- the ONLY door

@dataclass(frozen=True)
class Additive:     # fake_claude.py -- SU4B's four legs, migrated verbatim (section 4.4)
    edited_funcs: Mapping[str, tuple[str, str]]   # name -> (sha256, reason)
    new_funcs: frozenset[str]
    new_scenario_keys: frozenset[str]
    new_stmt_keys: frozenset[tuple]

@dataclass(frozen=True)
class Behaviour:    # anchor-side NODE census (section 4.5)
    nodes: int                                                 # B7 literal
    dump_sha: str                                              # B7 literal
    missing: Mapping[str, str] = field(default_factory=dict)   # key -> dated reason
    edited: Mapping[str, str] = field(default_factory=dict)    # key -> dated reason
    edited_exports: Mapping[str, str] = field(default_factory=dict)

# Written BY A HUMAN, never by --remeasure (section 4.2). Satisfies EXM1's
# grammar: a date AND an anchor (here both a sha and a section).
_P2 = ("2026-08-28 U-hostmode Phase 2, fe5a012: test_wr7's exclusion tuple "
       "loses chezmoi.py and its count assertion moves 11 -> 10. See section 9.1.")

ARMOR: dict[str, Fixture | Additive | Behaviour] = {
    # --- FIXTURES: ground truth, whole-file byte-pinned (section 4.3) ---
    "support.py":              Fixture(),   # 62 importers  (NEW under this unit)
    "conftest.py":             Fixture(),   #  2 importers
    "backends.py":             Fixture(),   #  3 importers
    # --- ADDITIVE: the one fixture V-2 lets grow (section 4.4) ---------
    "fixtures/fake_claude.py": Additive(...),
    # --- BEHAVIOUR: every top-level node (section 4.5) -----------------
    "test_invocation.py":      Behaviour(nodes=94,  dump_sha="604f7537d5c8037c...",
                                         edited={"func:test_wr7_seam_is_only_called_"
                                                 "from_the_three_call_sites": _P2}),
    "test_invocation_sdk.py":  Behaviour(nodes=139, dump_sha="2517577cbfc38547..."),
    "test_worker.py":          Behaviour(nodes=80,  dump_sha="16e45a867ecebd64..."),
    "test_repair.py":          Behaviour(nodes=85,  dump_sha="f7d0670234803960..."),
    "test_attrib.py":          Behaviour(nodes=68,  dump_sha="124dcc0dd69f9868..."),
    "test_route_cli.py":       Behaviour(nodes=58,  dump_sha="5bb83e2da3fe5e85..."),
    "test_composer.py":        Behaviour(nodes=58,  dump_sha="3c920c0066c5f9db..."),
    "test_u_fake.py":          Behaviour(nodes=45,  dump_sha="e8655e2be8863fc8..."),
}
```

Keys are relative to `plugins/self-learn/cli/tests/`. Every literal is
§2.10's anchor-side measurement at **`3b8e037`**.

**Every door ships shut except one, and that one is the mechanism working**
*(r4, gate B-1)*. `repinned is None` on all three fixtures; `missing` and
`edited_exports` are `{}` on all eight behaviour rows; `edited` is `{}` on
seven of eight. The eighth carries exactly the entry the anchor→HEAD diff
owes: `test_invocation.py`'s `func:test_wr7_…`, U-hostmode Phase 2's
`== 11` → `== 10`. `EXM3` asserts the entry count **equals the census's own
edited count**, so shipping one fewer or one more both redden. §2.10's
`c3b48e7` run (56 missing / 190 edited) is the control that these small
numbers are measured and not blind.

**The table's own protection.** `ARMOR` is a literal, so widening it is a
visible diff — the same trust model `REWRITTEN` uses (`test_u_fake.py:41-
43`: *"as a literal so widening it is a visible diff"*) and
`NOT_REPO_TRUTH` uses. §4.8's gate protocol is what reviews that diff.
`ARM3` additionally asserts the table is exhaustive over the tests tree:
every non-`test_*` module and every DS1-or-`_ARMOR_SHAS` path is a key, so
silently dropping a row reddens.

### 4.2 The anchor — what it is, and who advances it

**One literal, one place.** `ANCHOR` replaces `BASE_COMMIT` (`c3b48e7`),
`_BASE_SHA` (`442385d`) and `BASE_REF` (`c2669a9`).

**Definition.** `ANCHOR` is the **first-parent PARENT of the most recent
first-parent merge on `master`** — master's tip immediately *before* that
merge landed. Not the merge itself. Measured, and this is the value the
table ships:

```sh
$ M=$(git rev-list --first-parent --merges -1 master)
$ git rev-parse --short=7 "$M" ; git rev-parse --short=7 "$M^1"
fe5a012
3b8e037                     # <-- ANCHOR
```

Why the parent: the chain re-anchors **inside** the merge commit (below),
and a commit cannot embed its own sha. The parent already exists while the
merge is being built. The merge's own diff against `ANCHOR` is then exactly
the gate's evidence for the next round.

*(r4, gate B-1: r3 defined it correctly here and then shipped `fe5a012` —
the merge — in §4.1, which is the value control (iii) below rejects.)*

**The landing chain, in order.** The re-anchor is not a follow-up commit:

```sh
git merge-tree HEAD "$BRANCH"                      # 1. preview
git merge --no-ff --no-commit "$BRANCH"            # 2. merge, NOT committed
#    ... resolve conflicts by hand ...             # 3. resolve
python3 plugins/self-learn/cli/tests/test_armor.py --remeasure \
        --anchor "$(git rev-parse --short=7 HEAD)" \
&& git add plugins/self-learn/cli/tests/test_armor.py \
&& git commit --no-edit                            # 4. re-anchor RIDES INSIDE the merge
```

At step 4 `HEAD` is still the pre-merge tip — precisely the `ANCHOR` the
definition names. **`--remeasure` computes everything before it writes anything** *(r6, gate
M-2)*. The order is fixed, and it matters:

1. Resolve the new anchor (`HEAD`, which at step 4 is still the pre-merge
   tip) and read the current `ANCHOR` literal.
2. Run the full census of every `Behaviour` row against the new anchor, and
   the whole-file sha of every `Fixture` row.
3. Compute the **owed set**: every `edited` or `missing` key that no
   exemption entry covers.
4. **If the owed set is non-empty, exit non-zero naming the keys and write
   NOTHING.**
5. Only on an empty owed set: render the whole updated module — the
   `ANCHOR` literal and all sixteen `Behaviour` literals together — into a
   temp file beside `test_armor.py` and `os.replace()` it over the
   original, so the file is never observed half-updated.
6. Exit non-zero if the `ANCHOR` literal did not change (the no-op guard,
   `M48`).

**Why the order is load-bearing, not a style preference.** Under the
opposite ordering — write, then check — the sixteen literals and `ANCHOR`
are already advanced on disk when the refusal fires. The `&&`-chain aborts
mid-merge with a dirty tree; the human writes the owed exemption entry and
re-runs; and now **step 6 fires instead**, because the anchor literal was
already advanced by the first run and does not change on the second. The
chain aborts again, and the only escape is to hand-revert `test_armor.py`
— which is precisely the hand-edit `ARM2` exists to catch. **The landing
chain would deadlock on its own guard.**

Under check-then-write the same sequence terminates: the first run refuses
and leaves the file byte-identical, so the second run — after the human has
written the entry — still sees the **old** `ANCHOR` literal, finds an empty
owed set, writes, and step 6 passes because the literal genuinely changed
in that run. `ARM6` is the criterion that pins the byte-identity half, and
`M57` is the mutation that reddens only under the write-first ordering.

**`--remeasure` never writes an exemption entry.** Exemption reasons are
written **only by a human or a builder**, because a reason is a citation and
a claim — a tool cannot invent one, and a machine-written placeholder would
satisfy `EXM1`'s grammar while saying nothing a gate could check. Refusing
and naming the owed keys is the loud path; a silent map edit is the failure
this unit exists to prevent.


**Why the chain and not the builder.** A builder advancing the anchor moves
the baseline it is judged against — the census would assert "head equals
head", which is §2.4's finding wearing a new hat. The chain runs after the
gate has passed.

**Staleness must be loud, and the census says so itself.** Three legs, all
measured at live master (`6038eee`), where `M` = the latest first-parent
merge:

- **(a)** `ANCHOR` is an ancestor of `HEAD`.
- **(b)** `ANCHOR` **equals** `M^1`.
- **(c)** **No protected file has moved since the anchor merge**:
  `git diff --name-only M..master -- <the 12 protected paths>` is **empty**.

```sh
$ git merge-base --is-ancestor 3b8e037 master ; echo "(a) rc=$?"
(a) rc=0
$ M=$(git rev-list --first-parent --merges -1 master)
$ [ 3b8e037 = "$(git rev-parse --short=7 "$M^1")" ] && echo "(b) SAME"
(b) SAME
$ git diff --name-only "$M"..master -- <the 12 protected paths> | wc -l
0                                                              # (c)
```

**Leg (c) is not `rev-list --count ANCHOR..master^ == 0`, and the
difference is measured, not stylistic** *(§3.6, the recorded deviation;
adjudicated SOUND by gate r3)*. That count form is **RED on live master**,
and has grown more so while this spec was being written: two docs-only
commits now sit on top of the merge (`37f48c4`, the home-path scrub;
`6038eee`, a duplicate-row collapse in `14-forward-work-map.md`), so
`master^` is the merge rather than its parent:

```sh
$ git rev-list --count 3b8e037..37f48c4^     # one docs-only commit above the merge
4
$ git rev-list --count 3b8e037..6038eee^     # two -- and still nothing is wrong
5
```

Leg (c), on the same two heads, reads **0** both times, because neither
commit touched a protected path. The count form's number drifts with
unrelated documentation work; leg (c)'s does not.
Shipping it would put a criterion in the tree that is red on a correct
tree, which is the exact shape of the blocker it was meant to fix. Leg (c)
as written asks the question that actually matters — *has anything the
census protects moved since the anchor merge?* — and answers **0** on that
same live master.

**Three red controls, all real history:**

```
                                                       (a)   (b)                       (c)
chain ran; re-anchor inside the merge; TWO docs-only commits on top
  ANCHOR=3b8e037   tip=6038eee (live master)           rc=0  SAME                      0    GREEN
  ANCHOR=3b8e037   tip=37f48c4                         rc=0  SAME                      0    GREEN

a post-merge commit that TOUCHED a protected file
  (tip 1251552, "pin defaultMode=default in analyst settings files",
   sitting on merge c8dcaf3; ANCHOR=5803a36)
  ANCHOR=5803a36   tip=1251552                         rc=0  SAME                      1    RED (c)
      -> plugins/self-learn/cli/tests/test_repair.py

chain not run for the latest merge (anchor left one merge stale)
  ANCHOR=15fb676   tip=37f48c4                         rc=0  STALE (expected 3b8e037)  -    RED (b)

r3's shipped value: the merge itself, not its parent
  ANCHOR=fe5a012   tip=37f48c4                         rc=0  STALE (expected 3b8e037)  -    RED (b)
```

The second control is the one leg (c) exists for, and legs (a) and (b) both
**pass** there — only (c) discriminates, exactly as in r3. The fourth is
r3's own shipped literal, which is why B-1 was a blocker.

`ARM5` asserts all three and, on failure, names the landing chain and its
`--remeasure` step. It does not warn and it does not skip: a silently stale
anchor would make every other leg vacuous, because the census would compare
head against an ancestor of itself and call the difference sanctioned.

### 4.3 Kind FIXTURE — whole-file byte pin, anchored

**Ruling (r3, gate M-2): fixtures stay whole-file byte-pinned.** That was
the orchestrator's original ruling and it stands. A fixture edit costs a
re-pin with a dated justification, and that is **correct**: fixtures are
the ground truth every test in the suite stands on, and there is no
"additive" reading of ground truth.

What the gate measured, appending `<existing_global> = "PWNED"` to each
fixture:

```
conftest.py   global `_cache_env`  ->  r2's F1 PASS | r2's F2 PASS | whole-file sha RED
support.py    global `_GIT_SHIM`   ->  r2's F1 PASS | r2's F2 PASS | whole-file sha RED
backends.py   global `__all__`     ->  r2's F1 PASS | r2's F2 PASS | whole-file sha RED
```

r2's ordered-subsequence match let all three through. It is the exact
evasion class `SU4B` leg 4 was hardened for, and `F2` did not cover it
either — a rebound non-function global is neither a `def` nor a `class`.

Three legs, all against `git show ANCHOR:<path>`:

- **`F1` — WHOLE-FILE BYTE IDENTITY.** `sha256(head bytes)` equals
  `sha256(git show ANCHOR:<path>)`. No subsequence, no exemption by
  default. A fixture that changes at all reddens.
- **`F2` — the re-pin exemption.** A `Fixture.repinned = (sha, reason)`
  entry lets the head bytes differ from the anchor, and **only** to the
  named sha. The reason must cite a spec section and carry a date, exactly
  as the shipped `_ARMOR_SHAS` comments do — the cost r2 tried to remove
  here is the cost that belongs here. All three rows ship with `repinned =
  None` (`EXM3`).
- **`F3` — the DIAGNOSTIC, and it is only a diagnostic.** When `F1`
  reddens, name what moved: added / removed / edited top-level statements
  and defs, resolved through the imported module rather than an ast
  first-match. It makes the failure actionable and gives the
  guard-amendment review (§4.8) something to read. **It can never pass
  something `F1` fails** — `FIX4` asserts exactly that, so the r2 mistake
  (a diagnostic promoted to the check) cannot recur.

What this costs, honestly: `conftest.py` grew 396 lines since `442385d`
(§2.5). Under `F1` each of those landings would owe a `repinned` entry —
one sha and one dated line in the one table, instead of r2's zero and
instead of today's four surfaces (§2.3: the dated paragraph, the sha, the
`hy5` row, and 396 verbatim lines pasted into `_AR1_SANCTIONED_PIN_LINES`).
That is the trade the ruling makes, and it is the right one: the whole
argument of §3.2 is that a pin should assert an invariant, and *"this
fixture's bytes are what the last gate reviewed"* is a genuine invariant
for ground truth even though it is a snapshot for a behaviour suite.

**If the golden fixtures are ever wanted — the honest shape, recorded and
not built.** Ruling Q-3 (§3.4) keeps `fixtures/golden/*` OUT (§7 OUT 7):
four Markdown files, two consumers, no `ast`. Under r3's fixture kind they
would need no new machinery at all — they are `F1` verbatim, anchor-side
sha with a `repinned` door. Roughly 15 lines and one criterion. Not
specified here and not a criterion; recorded so a later unit does not
re-derive it and so a gate does not read its absence as an oversight.

### 4.4 Kind ADDITIVE — `fixtures/fake_claude.py`

`test_su4b_fake_claude_additive_only`'s four legs move into `test_armor.py`
**verbatim**, reading their sanctioned sets from the `Additive` record
instead of from three module-level constants. Nothing about the checks
changes; only where they live and where they read their tables from.

`_HY3_SCENARIO_SHAS` + `test_hy3_fake_claude_additions_are_additive`
(`test_u_sdka.py:2353-2395`) is **9/10 redundant** with `SU4B` leg 1, which
byte-checks every anchor function's runtime-bound source. The one
non-redundant row is `_scenario_error_result`, which `SU4B` **exempts** via
`_SU4B_SANCTIONED_EDITED_FUNCS` while HY3 pins it with a literal sha. So:
the 9 redundant rows are RETIRED; `_scenario_error_result`'s sha moves into
`Additive.edited_funcs` as a `(reason, sha)` pair so the exemption still
carries a value rather than a blanket pass; and HY3's one unique
assertion — `for banned in ("subprocess","socket","urllib","http"): assert
f"import {banned}" not in text` — MIGRATES as a fifth `Additive` leg.

### 4.5 Kind BEHAVIOUR — the node census

**Every top-level AST node is protected** *(r4, gate M-1)*, keyed by
`_key` and compared by `_norm_dump` (both quoted in §2.10). A changed node
is an `edited` entry; a vanished key is a `missing` entry; new keys are
free.

What that closes, measured on the real tree — r3's test-only census was
GREEN on all four, the retired whole-file sha was RED on all four:

```
A1  test_repair.py::RECORD_QUOTE (:82, "status: pending"), read by 10 protected tests
      r3: missing=0 edited=0  GREEN        r4: edited=1 ['assign:RECORD_QUOTE']        RED

A2  test_invocation.py::_run_sdk (:922-941), called at 22 sites by 9 protected tests
      r3: GREEN (not imported anywhere, so B5 never saw it)
      r4: edited includes ['func:_run_sdk']                                            RED
    test_repair.py::_gates_raises  (:174-177)   r4: ['func:_gates_raises']             RED
    test_worker.py::_wait_for_file (:238-245)   r4: ['func:_wait_for_file']            RED
```

Nine legs.

- **`B1` — NODE CENSUS.** Every anchor key still exists at head. Additions
  are free (subset, not equality). A key may be absent only via
  `Behaviour.missing` with a dated reason naming a spec section. A rename
  is one `missing` plus one free addition — the honest reading, since the
  old decision is gone.
- **`B2` — `missing` CANNOT ROT.** Every `Behaviour.missing` key must be
  **absent** at head. A stale entry reddens. *(Criterion `BEH8`, r4 gate
  M-2: r3 stated this leg and enforced it with nothing.)*
- **`B3` — DUMP IDENTITY, NODE-WIDE.** For every surviving anchor key,
  `_norm_dump(head) == _norm_dump(anchor)` unless in `Behaviour.edited`
  with a dated reason. This carries test bodies (setup lines,
  `pytest.raises` blocks, decorators, loops) **and** module constants,
  helpers, fixtures, classes and imports.
  **Docstrings are invisible at every level** — `_Strip` runs over the
  Module before the body is keyed and over each def/class as it is dumped,
  so rewording a module docstring or a test docstring is free *(r5, gate
  M-1: before this, a module docstring survived as its own `other:` node
  keyed by its own content, so a reword read as a **deletion** — and
  `test_u_fake.py`'s contains the word `guard`, which §4.8 makes a BLOCKER
  by default)*.
- **`B4` — `edited` CANNOT ROT.** Every `Behaviour.edited` key must exist
  at head **and** its dump must genuinely differ from the anchor's. An
  exemption that outlived its subject reddens. *(Criterion `BEH9`, same
  finding.)*
- **`B5` — EXPORTED SURFACE, DERIVED ANCHOR-SIDE.** Every top-level def
  another module imports by name (§2.10: **31**), derived with
  `ast.ImportFrom` — **a line regex is forbidden**, it skips the 11
  parenthesized sites. Protected set = `anchor_set ∪ head_set`; each name's
  source byte-identical to its anchor source unless in
  `Behaviour.edited_exports`.
- **`B6` — THE SURFACE CANNOT SHRINK.** `anchor_set ⊆ head_set`, so
  deleting the last importer of a protected export reddens.
- **`B7` — EXTRACTOR POSITIVE CONTROL.** The anchor-side census yields
  exactly `Behaviour.nodes` keys and a `_dump_sha` equal to
  `Behaviour.dump_sha`. A broken or empty extractor returns 0 and reddens.
  Both literals are anchor-side; head growth never moves them.

**Why additions stay free.** Adding a node adds a head-side key `B1` does
not iterate and `B3` does not compare; `B5`/`B6` compare sets the anchor
fixed; `B7`'s literals are measured at the anchor. So the edit that costs
69 lines of prose and 5 pin values today (§2.3) costs **zero**. What is no
longer free is *touching an existing node* — that costs one `edited` line
with a dated reason, which is the ruling.

**Note on false positives, accepted deliberately.** A semantically
equivalent rewrite — renaming a local, reordering independent statements —
changes the dump and is reported as `edited`. That is the intended
direction: it costs one reviewed line, and §4.8 tells the gate what to do
with it. The alternative (semantic equivalence checking) is not a thing
this repo can build.

### 4.6 The exemption records

Four doors, one discipline. `Fixture.repinned` is a `(sha, reason)` pair;
`Behaviour.missing`, `Behaviour.edited` and `Behaviour.edited_exports` are
`{key: "dated reason with an anchor"}` maps. **Every door ships shut except
the entries the anchor→HEAD diff genuinely owes** — at `3b8e037` that is
exactly one, `test_invocation.py`'s `func:test_wr7_…` (`EXM3`, §9.1).
*(r5, gate M-5: an earlier draft said "all eleven rows ship with every door
shut", which the B-1 fold had already made false.)*

*(r3: r2 called these `edited` / `retired` / `weakened`. The names now
match what the legs actually test — a fixture is **re-pinned**, a test is
**missing** or **edited** — and `weakened` is gone with the assert census
that gave it meaning.)*

Two rules bind every one of them:

1. **A reason must name a spec section** — `EXM1` asserts the string
   matches `§\d` or `FW-\d`. An exemption without a citable authority is
   the failure mode the whole design exists to prevent.
2. **An exemption cannot rot** — `FIX2`/`BEH8`/`BEH9` require that each
   entry's subject still exists in the state the entry claims *(r5, gate
   M-5: an earlier draft named `BEH2`/`BEH4`, which test that adding is
   free and that a docstring reword is not an edit — the mapping gate r2
   had already rejected as unenforced)*: a `repinned`
   file must actually differ from its anchor and match the pinned sha; a
   `missing` name must actually be absent; an `edited` test must exist and
   its dump must actually differ. This is the rule
   `NOT_REPO_TRUTH` states in its own docstring and the rule the shipped
   `_AR3_*` tables lack: `_AR3_REASONS` carries 21+ entries with no check
   that any still names a live function. (`test_lock_invariant.py:530`'s
   `test_the_exemption_list_cannot_rot` is the shape being copied.)

### 4.7 Disposition of every existing mechanism

| # | Mechanism | Where | Disposition | Reason |
|---|---|---|---|---|
| 1 | `_ARMOR_SHAS` — 2 fixture rows | `test_worker_contract.py:542-564` | **MIGRATED, SHAPE KEPT** → `Fixture` (`conftest.py`, `backends.py`, **+ `support.py`**) | The invariant is real **and so is the byte pin** — *(r3, gate M-2)* fixtures stay whole-file; what changes is that the pin is anchor-side, lives in one table, and gains the file with 62 importers |
| 2 | `_ARMOR_SHAS` — 5 behaviour rows | same | **RETIRED as whole-file**, replaced by `Behaviour` | §2.4: head-side sha is a change detector; 25 of 41 pin writes are these five |
| 3 | `_SU4B_DIFF_EXEMPT` | `test_worker_contract.py:745-752` | **RETIRED** | It exists only to switch off the base-diff half for 6 of 7 pins. Anchor-side comparison has nothing to exempt |
| 4 | `test_su4a_whole_file_armor_shas` | `:757-790` | **RETIRED**, superseded by `F1`-`F3`/`B1`-`B7` | |
| 5 | `test_su4b_fake_claude_additive_only` (4 legs) | `:880-1005` | **MIGRATED verbatim** → `Additive` | Already a property guard; it is the model, not the problem (§2.9) |
| 6 | `_SU4B_SANCTIONED_EDITED_FUNCS` / `_NEW_FUNCS` / `_NEW_SCENARIO_KEYS` / `_NEW_STMT_KEYS` | `:833-877` | **MIGRATED** → the `Additive` record's four fields | Same content, one home |
| 7 | `_AR1_SANCTIONED_PIN_LINES` (396 literal lines) + `test_ar1_tripwire_byte_unchanged` | `test_u_sdka.py:1387-1805` | **RETIRED** | Its property is `F1`'s whole-file sha — **one sha, not 396 verbatim lines**. *(r3: r2 claimed `F1` carried AR1's property with zero literals. The gate showed list-equality was strictly stronger than a subsequence match, so `F1` is now the sha and the literal count is one.)* |
| 8 | `_AR1_TRIPWIRE_SHA256` (the `_no_real_sdk_spawn_tripwire` sha) | `test_u_sdka.py` | **MIGRATED** → subsumed by `F1`, which byte-checks the whole file, not one function | Strictly wider |
| 9 | `_AR3_REASONS`/`_RENAMED`/`_REMOVED`/`_ADDED`/`_ONE_LINE_ONLY` + `test_ar3_edited_is_exactly_21_functions_with_reasons` | `test_u_sdka.py:1825-2118` | **MIGRATED** → `Behaviour.missing` + `.edited` (two maps, not five), and gains the anti-rot rule it lacks | AR3 is the same census as DS1 on a different anchor; five exemption shapes for one concept |
| 10 | `_HY3_SCENARIO_SHAS` + `test_hy3_...` | `test_u_sdka.py:2353-2395` | **9 rows RETIRED as redundant** with `SU4B` leg 1; `_scenario_error_result`'s sha **MIGRATED** into `Additive.edited_funcs`; the banned-import leg **MIGRATED** as a fifth `Additive` leg | Measured redundancy: `SU4B` leg 1 byte-checks every anchor function except the two it exempts, and only one HY3 row is in that exempt set |
| 11 | `test_hy5_numstat_bounds_hold` (9 insertion/deletion ceilings) | `test_u_sdka.py:2396-2556` | **RETIRED** | A growth ceiling is not an invariant; fail-open on an untouched row by its own `NIT-8` comment; measured to have reverted a real fix (§2.8 instance 3) |
| 12 | `REWRITTEN` / `DS1_ADDED` / `DS1_REMOVED` / `_DS1_EXPECTED` + `test_ds1` / `ds1b` / `ds1c` / `ds2` | `test_u_fake.py:84-337, 695-913` | **MIGRATED** → `Behaviour` (`B1`-`B4`, `B7`) for its five modules, three of which the whole-file pins never covered | The right idea with a head-side count (§2.7); the migration keeps the idea, moves the count anchor-side (which is what removes `DS1_ADDED`) and upgrades the comparison from a filtered source concat to a normalized dump per test |
| 13 | `test_ar5_pin1_class_is_closed_by_census` | `test_u_sdka.py:2121+` | **KEPT AS IS** | A suite-wide census of env-pin casualties. Different subject (env resolution), no file armor in it |
| 14 | `PL1` / `EV4` | `test_invocation_sdk.py:292, :2061` | **KEPT AS IS** | Derived properties of PRODUCTION code |
| 15 | `BND4` / `POL2` | `test_u_engine.py:912, :932-1007` | **KEPT AS IS** | Same |
| 16 | `_LOCKS` / `NOT_REPO_TRUTH` walker | `test_lock_invariant.py` | **KEPT AS IS, UNTOUCHED** | Derived property of production code; and `U-verbs`' `UN4` pins `_LOCKS`/`NOT_REPO_TRUTH` byte-unchanged (§9) |
| 17 | `test_pin2_armor_sha_paths_are_byte_unchanged` | `test_u_corrob.py:1320-1340` | **RETARGETED** | The only executable consumer of `_ARMOR_SHAS` (§2.11). It re-points at `ARMOR`'s `Fixture` rows and its `len(pins) == 7` becomes `len(fixture_rows) == 3` |

**Net:** 3 anchors → 1. Ten declaration tables → one table with four
uniform exemption maps. Three files carrying armor → one.

### 4.8 The gate protocol — the guard-amendment review

`15-orchestration-runbook.md` §1 step 4 tells a code gate to run mutation
verification. It says nothing about a change to a protected file, and
§0 measures that "guard-amendment" appears nowhere in the corpus. This unit
adds it, as a **new §1.4a and one line in §8**:

> **4a. Guard-amendment review (when the diff touches a protected file).**
> A file is protected if it is a key in `cli/tests/test_armor.py::ARMOR`.
> If the diff touches one, the code gate additionally checks, **against the
> unit's gated spec**, and reports each as its own finding:
>
> - **Deleted or renamed nodes.** Every key added to
>   `Behaviour.missing` must be named in the spec, with the section that
>   authorises it. A test that vanished without a `missing` entry is a
>   BLOCKER regardless of whether the suite is green — `B1` should have
>   caught it, and if it did not, the guard itself is the finding.
> - **Edited nodes.** Every entry added to `Behaviour.edited` must be
>   reviewed as a diff of the test's **body**, anchor beside head, and the
>   gate must say which failure the anchor version could see that the head
>   version cannot. "Refactored" is not a reason. Note the edit may be
>   anywhere in the body — a setup line, a `with pytest.raises(...)` block,
>   a loop bound — not only in an assertion *(r3, gate M-3)*.
> - **Re-pinned fixtures.** Every `Fixture.repinned` entry is reviewed as
>   production code: the gate diffs the fixture against its anchor bytes
>   and mutates the new body to confirm a test reddens.
> - **Removed positive controls.** If a deleted or edited node's name, or
>   the docstring of a **test function** (never the module docstring —
>   §2.10 makes a module-docstring reword free), contains `positive
>   control`, `negative control`, `tripwire`, or `guard`, the finding is a
>   BLOCKER by default. These are the tests that prove the other tests can
>   fail.
> - **Edited exports.** Every entry added to `Behaviour.edited_exports` is
>   reviewed as production code: the gate mutates the new body and confirms
>   a test reddens. *(r4, gate M-5: r3's bullet also named `Fixture.edited`,
>   a field r3 itself had deleted — and this text is inserted verbatim into
>   the runbook, so it would have told every future gate to review a field
>   that never exists. `Fixture.repinned` is covered by the bullet above.)*
>
> - **Anchor advance.** A diff that changes `ANCHOR` is **refused**. The
>   anchor is advanced by the landing chain after the merge, never inside a
>   reviewed diff (§4.2). Conversely, the gate's own starting evidence IS
>   the previous chain run's `git diff --stat <old> <new> --
>   plugins/self-learn/cli/tests` output: read it first, and treat anything
>   in this diff that it does not explain as unaccounted for.
>
> The blindness rules (§4) are unchanged: the reviewer sees the diff and
> the gated spec, never `reviews/`.

And in §8's reviewer skeleton, one line: *"if the diff touches a key of
`cli/tests/test_armor.py::ARMOR`, run §1.4a's guard-amendment review and
report each clause separately."*

---

## 5. Criteria

Each criterion: **ID · phase · statement · check · mutation.** **[A]** =
the single phase — see §5.0 for why there is no split. Mutation cells are
`predicted` unless marked **MEASURED** (read off, or applied to, shipped
code during this spec's census).

Every new test lives in the new `cli/tests/test_armor.py`. The only edits
to existing test files are deletions of the retired mechanisms (§4.7) and
the one retarget in `test_u_corrob.py` — enumerated in §8.

### 5.0 One phase, and why

`U-hostmode` and `U-verbs` split because each had a Phase 2 that touched a
different subsystem (chezmoi deletion; the UI verb surface). This unit
touches one directory and three docs, and its halves are not separable:
the retirements (§4.7) cannot land before the replacements, and the
replacements cannot land beside the retirements without the suite carrying
two armor systems over the same files at once — which is the *"eighth
mechanism beside seven"* the mandate forbids. **Criteria are all [A].**

### 5.1 ARM — the module and the table

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **ARM1** | [A] | `cli/tests/test_armor.py` exists and carries **exactly one** module-level table named `ARMOR` and **exactly one** anchor literal named `ANCHOR`. No other module in `cli/tests` defines a whole-file sha table | `pytest -k test_arm1_one_table_one_anchor`: walk every `cli/tests/**/*.py` with `ast`; assert exactly one module assigns `ARMOR`, exactly one assigns `ANCHOR`, and **zero** modules outside `test_armor.py` contain a dict literal whose values include a 64-hex string keyed by a `.py` path. **Positive control, asserted first**: the same walk over `git show 3b8e037:` bytes of `test_worker_contract.py` finds **1** such dict (`_ARMOR_SHAS`, 7 entries) | re-introduce a second sha table in any test module ⇒ ARM1 red · **MEASURED** pre-state (§2.1: 7 entries) |
| **ARM2** | [A] | Every `Behaviour.nodes` / `.dump_sha` literal equals the census measured at `ANCHOR`, and every `Fixture` sha likewise. Only `--remeasure` may move one | `pytest -k test_arm2_literals_match_the_anchor`: run `_census`/`_dump_sha` over `git show ANCHOR:<path>` for all 8 behaviour rows and `sha256(git show ANCHOR:<path>)` for the 3 fixture rows. **MEASURED at `3b8e037`**: **627 nodes** across 8 files with the 8 `dump_sha` values in §2.10 | change any one literal ⇒ ARM2 red naming the file; hand-edit instead of `--remeasure` ⇒ same · `predicted` |
| **ARM3** | [A] | The table is **exhaustive**: every non-`test_*.py` module under `cli/tests` (excluding `__init__`/`__pycache__`) is a key, and every path that `3b8e037`'s `_ARMOR_SHAS` or `_DS1_EXPECTED` named is a key | `pytest -k test_arm3_table_is_exhaustive`: derive both sets live and assert `⊆ set(ARMOR)`. **Positive control**: deleting the `support.py` row makes the first half red; deleting `test_composer.py` makes the second half red — both asserted by a fixture copy of the table, not by editing the real one | drop any row ⇒ ARM3 red · `predicted` |
| **ARM4** | [A] | `ANCHOR` is a real commit **reachable from `master`**, and is not one of the three retired anchors | `pytest -k test_arm4_anchor_is_real`: `git merge-base --is-ancestor ANCHOR HEAD` returns 0, `git cat-file -t ANCHOR` is `commit`, and `ANCHOR` ∉ {`c3b48e7`, `442385d`, `c2669a9`} | set `ANCHOR` to a nonexistent sha ⇒ ARM4 red (not a silent skip) · `predicted` |
| **ARM5** | [A] | **A stale anchor is reported loudly by the census itself.** `ANCHOR` (= `M^1`, the first parent of the latest first-parent merge `M`) must satisfy: (a) it is an ancestor of `HEAD`; (b) it **equals** `M^1`; (c) **no protected file has moved since the anchor merge** — `git diff --name-only M..master -- <the 12 protected paths>` is empty. Failure names the landing chain and `--remeasure`; never a warn, never a skip | `pytest -k test_arm5_anchor_is_not_stale`, the commands in §4.2. **MEASURED at live master `6038eee`**: `rc=0` / `SAME` / **0**. **Three red controls, all real history, asserted first**: (i) tip `1251552` (a post-merge commit that touched `test_repair.py`, on merge `c8dcaf3`, `ANCHOR=5803a36`) — (a) and (b) both PASS, **only (c) discriminates at 1**; (ii) `ANCHOR=15fb676` — (b) `STALE`; (iii) `ANCHOR=fe5a012`, r3's own shipped value — (b) `STALE`. **Leg (c) is deliberately not `rev-list --count ANCHOR..master^`**: that form reads **4** on live master because of the landing chain's own docs-only scrub, i.e. red on a correct tree (§3.6) | land a commit touching a protected file after the anchor merge ⇒ ARM5 red on (c); leave `ANCHOR` one merge stale ⇒ red on (b) · **MEASURED** predicates |
| **ARM6** | [A] | **A refusing `--remeasure` leaves `test_armor.py` byte-identical.** It computes the anchor, the census and the owed set BEFORE writing anything; on a non-empty owed set it exits non-zero naming the keys and writes nothing; on an empty one it renders the whole module to a temp file and `os.replace()`s it, so the file is never half-updated *(r6, gate M-2: the ordering was unspecified, and write-then-refuse **deadlocks the landing chain** — the literals are already advanced when the refusal fires, so the post-fix re-run trips the no-op guard instead and the only escape is the hand-edit `ARM2` exists to catch)* | `pytest -k test_arm6_refusal_writes_nothing`: on a tree with one owed-but-unexempted key, capture `sha256(test_armor.py)` before, run `--remeasure`, assert rc != 0, the owed key is named in stderr, and `sha256` after **==** before. **Second leg, the deadlock itself**: write the owed entry, re-run, assert rc == 0 **and** the `ANCHOR` literal changed in that run. **Positive control**: on a clean census the same harness rewrites the file (sha differs) and exits 0 | move the write above the check ⇒ leg 1 red (sha differs) and leg 2 red (the second run trips the no-op guard) · `predicted` |

### 5.2 FIX — the fixtures

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **FIX1** | [A] | **`F1` — WHOLE-FILE BYTE IDENTITY.** For each `Fixture` row, `sha256(head bytes)` equals `sha256(git show ANCHOR:<path>)`. No subsequence match, no default exemption | `pytest -k test_fix1_fixtures_are_byte_identical`. **Positive control, asserted first**: three `tmp_path` copies, one per fixture, each with a module-level rebinding of a pre-existing global appended (`conftest.py::_cache_env`, `support.py::_GIT_SHIM`, `backends.py::__all__`) — **all three must redden** | append the rebinding to any fixture ⇒ FIX1 red; delete an exported helper from `support.py` ⇒ FIX1 red · **MEASURED**: r2's legs PASS on all three, the whole-file sha reddens on all three |
| **FIX2** | [A] | **`F2` — the re-pin door, and it cannot rot.** A `Fixture.repinned = (sha, reason)` entry lets head differ from the anchor and **only** to that sha; the reason cites a spec section and carries a date. Every entry's file must actually differ from its anchor bytes **and** match the pinned sha | `pytest -k test_fix2_repin_door_is_exact_and_cannot_rot`, driven over a **fixture table** with three bad entries — a sha that does not match head; an entry on a file identical to its anchor (the anti-rot leg); a reason with no `§`/`FW-` citation — all three must redden. The shipped `repinned is None` on all three rows is asserted by `EXM3` | point `repinned` at the anchor sha while head differs ⇒ FIX2 red; leave a `repinned` entry on a file that reverted to its anchor ⇒ FIX2 red on the anti-rot leg · `predicted` |
| **FIX3** | [A] | **`support.py` is protected** — the 62-importer hole is closed | `pytest -k test_fix3_support_is_protected`: `"support.py" in ARMOR`, and `F1` reports a nonzero anchor byte length. **Positive control for the "nonzero"**: the same assertion over an empty file reports 0 and reddens | drop the row ⇒ FIX3 and ARM3 red · **MEASURED** hole (§2.6: grep 0, control 16) |
| **FIX4** | [A] | **`F3` is a DIAGNOSTIC ONLY.** When `F1` reddens, `F3` names what moved (added / removed / edited top-level statements and defs, resolved through the imported module). **Its verdict is never consulted: `F3` is called only inside `F1`'s failure branch and its return value never reaches an assertion** *(r4, gate N-7: r3 claimed to prove "no code path lets F3 decide", which its structural instrument cannot show; the criterion now states exactly what the instrument proves)* | `pytest -k test_fix4_diagnostic_is_report_only`: `ast`-walk `test_armor.py` and assert (i) every `F3` call site is lexically inside an `if`/`assert`-failure branch guarded by `F1`, and (ii) no `F3` return value is bound to a name used in any `assert`. Over the three FIX1 control copies, assert `F1` is red **and** `F3` names the rebound global | let `F3`'s verdict short-circuit `F1` ⇒ FIX4 red on leg (ii) · **MEASURED** as r2's own defect |

### 5.3 ADD — `fixtures/fake_claude.py`

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **ADD1** | [A] | `SU4B`'s four legs are present and behave identically, reading their sets from `ARMOR["fixtures/fake_claude.py"]` | `pytest -k test_add1_fake_claude_additive_only`. **Positive control**: the two evasions `SU4B`'s own comments name — a shadowing redefinition (leg 1) and an appended module-level rebinding of a pre-existing global (leg 4) — each applied to a `tmp_path` copy, each must redden its leg | delete leg 4's filtered-sequence comparison ⇒ the rebinding control passes ⇒ ADD1 red · **MEASURED** as live evasions |
| **ADD2** | [A] | HY3's unique leg survives: `fake_claude.py` imports none of `subprocess`, `socket`, `urllib`, `http` | `pytest -k test_add2_fake_claude_imports_nothing_live`. **Positive control**: a copy with `import socket` appended reddens | drop the leg ⇒ ADD2 red on the control · **MEASURED** |
| **ADD3** | [A] | `_scenario_error_result`'s sha survives the HY3 retirement — the one HY3 row `SU4B` leg 1 exempts is carried as a value on its `edited_funcs` entry | `pytest -k test_add3_edited_scenario_still_pinned`: the entry carries a 64-hex sha and the live function matches it. **Positive control**: `SU4B` leg 1 is confirmed to SKIP this function, so ADD3 is the only thing covering it | edit `_scenario_error_result` ⇒ ADD3 red while `SU4B` leg 1 stays green · **MEASURED** redundancy (§4.4) |

### 5.4 BEH — the behaviour files

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **BEH1** | [A] | **`B1`** — every anchor **node key** still exists at head, for all 8 rows, unless in `Behaviour.missing`. Additions are free | `pytest -k test_beh1_no_node_is_deleted_or_renamed`. **Positive control, asserted first**: `ANCHOR = c3b48e7` reports **56** missing keys. **Second leg, a protected file DELETED outright** *(r6, gate N-3)*: the head read is guarded, and an absent path fails with `protected file <path> missing — every node missing; refuse`, naming the path — never a bare `FileNotFoundError` traceback. **MEASURED** against an empty head: `test_composer.py` reports 58 missing of 58 nodes, RED | delete `test_worker.py::test_run_idle_when_nothing_eligible` ⇒ BEH1 red naming `func:…`; delete a module constant ⇒ red naming `assign:…`; delete a whole protected file ⇒ red with the named message, not a traceback · **MEASURED** control |
| **BEH2** | [A] | **Adding to a protected file costs nothing** — no table edit, no re-pin, suite green | `pytest -k test_beh2_adding_is_free`: append a new `def test_zz_probe(): assert True` **and** a new `ZZ_CONST = 1` to a `tmp_path` copy of `test_worker.py`; every leg stays green. **Positive control**: the same harness deleting either reddens BEH1 | make `B1` an equality check ⇒ BEH2 red · `predicted` |
| **BEH3** | [A] | **`B3` — DUMP IDENTITY, NODE-WIDE.** For every surviving anchor key, `_norm_dump(head) == _norm_dump(anchor)` unless in `Behaviour.edited` | `pytest -k test_beh3_no_protected_node_is_edited`. **Four positive controls, all MEASURED on the real tree, asserted first**: (i) `test_repair.py::RECORD_QUOTE` mutated ⇒ `edited=['assign:RECORD_QUOTE']`; (ii) `test_invocation.py::_run_sdk` gutted ⇒ `['func:_run_sdk']`; (iii) `test_repair.py::_gates_raises` gutted ⇒ RED; (iv) `test_worker.py::_wait_for_file` gutted ⇒ RED. **All four were GREEN under r3.** Plus r3's two probes (setup-line flip; `pytest.raises` deletion), still RED. Fifth control: `ANCHOR = c3b48e7` reports **190** edited | mutate any constant, helper, fixture, class or test body ⇒ BEH3 red naming the key · **MEASURED** (six controls) |
| **BEH4** | [A] | **A docstring reword or a reflow is NOT an edit** | `pytest -k test_beh4_docstring_reword_is_not_an_edit`: a copy with one protected test's docstring rewritten and its body reflowed stays green; the same copy with one **statement** changed reddens. Control first | stop stripping docstrings, or set `include_attributes=True` ⇒ BEH4 red on the reword leg · `predicted` |
| **BEH5** | [A] | **`B5` — EXPORTED SURFACE, ANCHOR-SIDE, `ast.ImportFrom`.** Protected set = `anchor_set ∪ head_set`; each name byte-identical to its anchor source unless in `edited_exports`. **A line regex is forbidden** | `pytest -k test_beh5_exported_fixtures_are_byte_pinned`. **MEASURED**: **31** names, `4/5/6/10/0/4/2/0`. **Positive control — a MULTI-LINE parenthesized import** must make its name join the derived set; a single-line control passes under both the correct and the broken derivation and does not discriminate | implement with a line regex ⇒ the set falls to 20 and the multi-line control fails ⇒ BEH5 red · **MEASURED** (20 vs 31; 11 sites) |
| **BEH6** | [A] | **`B6` — THE SURFACE CANNOT SHRINK.** `anchor_set ⊆ head_set` | `pytest -k test_beh6_export_surface_cannot_shrink`. **MEASURED**: dropping `test_u_corrob.py` takes it 31 → 30 (losing `test_route_cli.py::_skill_gates_yaml`); dropping five unprotected importers, 31 → 25. Under r2's head-side rule none of the criteria reddened | delete the last importer of a protected export ⇒ BEH6 red naming the lost name · **MEASURED** |
| **BEH7** | [A] | **`B7` — EXTRACTOR POSITIVE CONTROL.** The anchor-side census yields exactly `Behaviour.nodes` keys and a `_dump_sha` equal to `Behaviour.dump_sha`, per file, **under the algorithm quoted in §2.10** | `pytest -k test_beh7_extractor_positive_control`: monkeypatch `_census` to `{}` and assert BEH1/BEH3/BEH7 all redden. **MEASURED literals at `3b8e037`**: nodes `94/139/80/85/68/58/58/45` (**627**) with `dump_sha` prefixes `604f7537d5c8 / 2517577cbfc3 / 16e45a867ece / f7d067023480 / 124dcc0dd69f / 5bb83e2da3fe / 3c920c0066c5 / e8655e2be886` | narrow `_census` back to `test_*` defs ⇒ 627 → 366 ⇒ BEH7 red · **MEASURED** (627 vs 366) |
| **BEH8** | [A] | **`B2` — `missing` CANNOT ROT.** Every `Behaviour.missing` key is **absent** at head *(r4, gate M-2: r3 stated this leg and no criterion enforced it)* | `pytest -k test_beh8_missing_set_cannot_rot`, driven over a fixture table with an entry naming a key that still exists — must redden. The shipped `missing == {}` on all eight rows is asserted by `EXM3` | re-add a deleted test without removing its `missing` entry ⇒ BEH8 red · `predicted` |
| **BEH9** | [A] | **`B4` — `edited` CANNOT ROT.** Every `Behaviour.edited` key exists at head **and** its dump genuinely differs from the anchor's | `pytest -k test_beh9_edited_set_cannot_rot`, over a fixture table with two bad entries: one naming a key absent at head, one naming a key whose dump is unchanged — both must redden. **Positive control on the shipped table**: the one live entry (`func:test_wr7_…`) must PASS both halves, which is what proves the leg is not vacuously green | revert `test_wr7` to its anchor body while leaving the `edited` entry ⇒ BEH9 red · **MEASURED** (the shipped entry is a real diff) |

### 5.5 EXM — the exemption discipline

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **EXM1** | [A] | **Every exemption reason carries a DATE and an ANCHOR**: it matches `20\d\d-\d\d-\d\d` **and** at least one of `§\d`, `FW-\d+`, `S-\d+`, or a 7–40-hex commit sha *(r5, gate B-1: the old `§\d\|FW-\d+` grammar rejected the one entry the design must ship, because Python comments in this spec write "section N" where prose writes "§N")*. An exemption without a date is unauditable; one without an anchor cites no authority. **Second leg** *(r6, gate N-2)*: any 7–40-hex anchor must RESOLVE — `git cat-file -e <sha>^{commit}` returns 0 — so a fabricated citation is refused, not merely well-formed | `pytest -k test_exm1_every_reason_carries_a_date_and_an_anchor`. **Five negative controls, each isolating one half, all MEASURED**: (a) `"2026-08-28 refactored for clarity."` — date ✓, anchor ✗ ⇒ FAIL; (b) `"§9.1 -- U-hostmode Phase 2 deleted chezmoi.py."` — anchor ✓, date ✗ ⇒ FAIL; (c) `"refactored"` ⇒ FAIL both; (d) `"2026-8-2 §9.1 cleanup"` — a date-shaped string that is not a date ⇒ FAIL; (e) `"2026-08-28 fe5a01: cleanup"` — 6 hex, below the floor ⇒ FAIL. **Sixth control, the resolution leg**: (f) `"2026-08-28 deadbee: sanctioned by a commit that does not exist."` — grammar ✓ but `deadbee` does not resolve ⇒ FAIL. **Positive**: the shipped `_P2`, plus `"2026-08-28 per S-55."` and `"2026-08-28 per FW-140."` ⇒ PASS. **The residual is named**: a sha that resolves but is irrelevant still passes — that is §4.8's human review, not a grep's job. *(The r4 reason string PASSES this grammar — its `fe5a012` satisfies the anchor half — so it is **not** usable as a control; see §3.7.)* | accept a bare string ⇒ EXM1 red on (c); drop the date half ⇒ red on (b); drop the anchor half ⇒ red on (a); drop the resolution leg ⇒ red on (f) · **MEASURED** (8 strings, 0 mismatches; `deadbee` does not resolve, `fe5a012` and `3b8e037` do) |
| **EXM2** | [A] | The four exemption maps are the **only** escape hatches: no leg has a hardcoded name skip | `pytest -k test_exm2_no_hardcoded_skips`: `ast`-walk `test_armor.py`; assert no string literal that equals a live test name or def name appears outside `ARMOR`. **Positive control**: the same walk over a copy with `if name == "test_run_idle_when_nothing_eligible": continue` inserted reddens | add a hardcoded skip ⇒ EXM2 red · `predicted` |
| **EXM3** | [A] | **Every door ships shut except the entries the anchor→HEAD diff genuinely owes, each carrying a dated reason** *(r4, gate B-1/M-6: r3 said "ships empty", which is unsatisfiable at the correct anchor)*. Concretely: `Fixture.repinned is None` on all 3 fixture rows; `Behaviour.missing == {}` and `edited_exports == {}` on all 8; `Additive.edited_funcs` is exactly `{"main", "_scenario_error_result"}`; and **the total number of `Behaviour.edited` entries equals the census's own edited count** | `pytest -k test_exm3_doors_match_what_the_anchor_owes`: run the census at `ANCHOR` and assert `sum(len(r.edited) for r in behaviour_rows) == census_edited_total`, then assert each entry's key is one the census reports. **MEASURED at `3b8e037`**: census edited = **1**, shipped entries = **1**, the key `func:test_wr7_seam_is_only_called_from_the_three_call_sites`. **Positive control**: the same code at `c3b48e7` reports **56 missing / 190 edited**, so the rule is not vacuous on a small number | remove the shipped `test_wr7` entry ⇒ EXM3 red (1 ≠ 0); add an unowed entry ⇒ EXM3 red (2 ≠ 1); grandfather `c3b48e7`'s 56 + 190 ⇒ red · **MEASURED** both counts |

### 5.6 DEL — the retirement is real

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **DEL1** | [A] | Every retired symbol is **gone from the tree**, not merely unused: `_ARMOR_SHAS`, `_SU4B_DIFF_EXEMPT`, `_SU4B_SANCTIONED_EDITED_FUNCS`, `_SU4B_SANCTIONED_NEW_FUNCS`, `_SU4B_SANCTIONED_NEW_SCENARIO_KEYS`, `_SU4B_SANCTIONED_NEW_STMT_KEYS`, `_AR1_SANCTIONED_PIN_LINES`, `_AR1_TRIPWIRE_SHA256`, `_AR3_REASONS`, `_AR3_RENAMED`, `_AR3_REMOVED`, `_AR3_ADDED`, `_AR3_ONE_LINE_ONLY`, `_HY3_SCENARIO_SHAS`, `REWRITTEN`, `DS1_ADDED`, `DS1_REMOVED`, `_DS1_EXPECTED`, `BASE_COMMIT`, `_BASE_SHA`, `BASE_REF`, **`_FAKE_CLAUDE_RELPATH`** *(r3, gate N-1: omitted in r2, so `DEL1` would have passed with it left behind while `DOC2` required §13's list — the two could not both be satisfied)* | `grep -rnE '\b(_ARMOR_SHAS\|_SU4B_[A-Z_]+\|_AR1_[A-Z_]+\|_AR3_[A-Z_]+\|_HY3_SCENARIO_SHAS\|REWRITTEN\|DS1_ADDED\|DS1_REMOVED\|_DS1_EXPECTED\|BASE_COMMIT\|_BASE_SHA\|BASE_REF\|_FAKE_CLAUDE_RELPATH)\b' plugins/self-learn/cli --include='*.py'` returns **0**, `rc` captured **UNPIPED** (`rc=${PIPESTATUS[0]}`). **Positive control**: the same grep at `3b8e037` returns **185** | leave any one symbol behind ⇒ DEL1 red naming it · **MEASURED** pre-state (§2.11: 24 hits across 7 files) |
| **DEL2** | [A] | Every retired **test function** is gone: `test_su4a_whole_file_armor_shas`, `test_su4b_fake_claude_additive_only`, `test_ar1_tripwire_byte_unchanged`, `test_ar3_edited_is_exactly_21_functions_with_reasons`, `test_hy3_fake_claude_additions_are_additive`, `test_hy5_numstat_bounds_hold`, `test_ds1_t3_function_bodies_survive_the_inverse_rename`, `test_ds1b_removed_set_is_exact_and_every_entry_is_base_only`, `test_ds1c_added_set_is_exact_and_every_entry_is_head_only`, `test_ds2_rewritten_set_is_exact_and_every_entry_is_live` | `pytest --collect-only -q` names none of the ten. **Positive control**: the same collector at `3b8e037` names all ten | leave one behind ⇒ DEL2 red · `predicted` |
| **DEL3** | [A] | **Nothing was quietly dropped.** For each of the 17 rows of §4.7's disposition table, a named `test_armor.py` test (or a named KEPT-AS-IS location) covers the property | `pytest -k test_del3_every_disposition_is_covered`: a literal in-test table maps each of the 17 dispositions to the criterion ID or file:line that now carries it, and asserts every named test exists in `test_armor.py` and every named KEPT file still contains its symbol. **Positive control**: renaming one covering test reddens | drop `B4` and claim row 12 is covered ⇒ DEL3 red (`test_beh5_...` missing) · `predicted` |
| **DEL4** | [A] | `test_u_corrob.py::test_pin2_armor_sha_paths_are_byte_unchanged` is **retargeted, not deleted** — it reads `ARMOR` and asserts the three `Fixture` rows' live bytes are consistent with `F1`/`F2` | `pytest -k test_pin2` green; `grep -c '_ARMOR_SHAS' plugins/self-learn/cli/tests/test_u_corrob.py` = 0 (comments included), `rc` unpiped; and the test's own `len(...) == 3` replaces `len(pins) == 7`. The grep is `ast`-scoped like `DEL1`'s: `test_u_corrob.py`'s three historical docstring mentions (`:7`, `:17`, `:1040`) are history and stay | delete the test instead of retargeting ⇒ DEL4 red · **MEASURED** as the only executable consumer (§2.11) |
| **DEL5** | [A] | The three armor files **shrink**: `test_worker_contract.py`, `test_u_sdka.py` and `test_u_fake.py` each lose more lines than `test_armor.py` gains, and their combined comment-line count drops by **≥ 700** | `wc -l` and `grep -c '^\s*#'` before/after, quoted in the build report. **MEASURED baseline** (§2.1): 2285 / 2556 / 913 lines; 626 / 627 / 197 comment lines = **1450** comment lines total. §2.1 and §2.5 account for ≥ 470 of them in the `_ARMOR_SHAS` block and `_AR1_SANCTIONED_PIN_LINES` alone | a build that copies the prose across instead of retiring it ⇒ DEL5 red · **MEASURED** baseline |

### 5.7 GATE — the process amendment

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **GATE1** | [A] | `15-orchestration-runbook.md` gains **§1.4a**, with all **six** clauses of §4.8 (deleted/renamed nodes; edited nodes; removed positive controls; re-pinned fixtures; edited exports; anchor advance) | `grep -c 'guard-amendment'` ≥ 2, and one `grep -c` per clause keyword — **`missing`, `edited`, `positive control`, `repinned`, `edited_exports`, `ANCHOR`** — each ≥ 1. **MEASURED over §4.8's own inserted text**: `missing` 2, `edited` 3, `positive control` 2, `repinned` 1, `edited_exports` 1, `ANCHOR` 1, six blockquote bullets. **Positive control**: every one returns **0** in the runbook at pre-state, against `mutation verification` = 1 *(r4, gate M-4: r3 grepped for `retired`, a keyword r3 itself renamed away — measured **0** in its own §4.8 text, so a correct build reddened it)* | ship five clauses of six ⇒ GATE1 red on the missing keyword · **MEASURED** pre-state |
| **GATE2** | [A] | §1.4a names its trigger **mechanically** — "a key in `cli/tests/test_armor.py::ARMOR`" — so a gate can evaluate it without judgement, and §8's reviewer skeleton carries the pointer | `grep -c 'test_armor.py::ARMOR' docs/specs/self-learn/15-orchestration-runbook.md` = **2** (§1.4a and §8) | write the trigger as "a protected file" with no definition ⇒ GATE2 red · `predicted` |
| **GATE3** | [A] | The runbook's **existing** §1 numbering and §4 blindness rules are byte-unchanged apart from the insertion | `git diff -- docs/specs/self-learn/15-orchestration-runbook.md` shows insertions only inside §1 (after step 4) and one line in §8; `git diff --numstat` deletions on that file = **0**. **Positive control**: the same numstat on a copy with step 5 reworded shows a nonzero deletion count | reword step 4 while inserting 4a ⇒ GATE3 red · `predicted` |

### 5.8 UN — the unaffected group

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **UN1** | [A] | **No production source file changes.** `plugins/self-learn/cli/src` and `plugins/self-learn/ui` are byte-identical | `git diff --numstat <build base> -- plugins/self-learn/cli/src plugins/self-learn/ui` is **empty**, `rc` unpiped. **Positive control**: the same command scoped to `plugins/self-learn/cli/tests` is non-empty | touch any `src/` file ⇒ UN1 red · `predicted` |
| **UN2** | [A] | **`test_lock_invariant.py` is byte-unchanged** — `_LOCKS`, `NOT_REPO_TRUTH` and `_ARGV_FOR` all untouched (§9: `U-verbs`' `UN4` depends on it) | `git diff --numstat <build base> -- plugins/self-learn/cli/tests/test_lock_invariant.py` is empty | add a row to `NOT_REPO_TRUTH` ⇒ UN2 red · **MEASURED** as an in-flight sibling's pin (`u-verbs` spec `UN4`) |
| **UN3** | [A] | The suite grows by exactly the new armor tests and shrinks by exactly the ten retired ones: **2666 → 2666 − 10 + N**, with N stated in the build report and matching the count of `test_*` functions in `test_armor.py` | the collector, quoted, before and after. **MEASURED baseline**: 2666 (§2.12), re-measured after U-hostmode Phase 2 (`test_chezmoi.py` deleted, `test_hostmode.py` +10) | a build that leaves a retired test collected ⇒ UN3 red and DEL2 red · **MEASURED** baseline |
| **UN4** | [A] | `pyright` on `cli/src` is unchanged at its documented baseline (56 pre-existing errors, `15-orchestration-runbook.md` §7: *"cli src carries 56 pre-existing — new code adds zero"*), and `test_armor.py` adds none | `pyright` before/after, quoted | `predicted` |
| **UN5** | [A] | The eight protected behaviour files and the four fixture files are **byte-unchanged by this unit** — U-armor protects them, it does not edit them | `git diff --numstat <build base>` over the twelve paths is **empty**. **Positive control**: the same command over the three retired-mechanism files is non-empty | edit a protected file to "make the census come out even" ⇒ UN5 red · `predicted` |

### 5.9 DOC — the owed doc edits, and the retired-names list

Ruling addendum (§3.4): the two-gate process doc's amendment is an **owed
edit with its own criterion**, and the retired names get an explicit list
so a future grep finds no live reference.

| ID | Ph | Criterion | Check | Mutation |
|---|---|---|---|---|
| **DOC1** | [A] | **All three owed doc edits land**, each verified independently: `15-orchestration-runbook.md` gains §1.4a + the §8 line **and** the landing-chain re-anchor step of §4.2 (§10.3); `03-decisions.md` gains `S-55`; `14-forward-work-map.md` gains `FW-140` and `FW-141` | one `grep -cE` per edit, `rc` captured **unpiped**: `'guard-amendment'` ≥ 2, `'--remeasure'` ≥ 1, `'^\| S-55'` = 1, `'^\| FW-140'` = 1, `'^\| FW-141'` = 1. **Positive control**: every one of the five returns **0** at `3b8e037` (§0 and §10.1/§10.2 measure this), while the same greps for `'mutation verification'` / `'^\| S-54'` / `'^\| FW-138'` return **1 / 1 / 1** | land the code and skip any one doc edit ⇒ DOC1 red naming it · **MEASURED** pre-state (all five = 0) |
| **DOC2** | [A] | **§13's retired-names list is complete and live-checked**: every name in it is absent from the three owner files (`test_worker_contract.py`, `test_u_sdka.py`, `test_u_fake.py`) as an **`ast`-visible binding or definition** — `ast.Assign`, **`ast.AnnAssign`**, `FunctionDef`, `AsyncFunctionDef` — and the list in §13 equals the set the test checks, so the doc and the code cannot drift | `pytest -k test_doc2_retired_names_are_gone`. **MEASURED at `3b8e037`, owner-scoped**: **32** ast-visible occurrences across the three owner files (9 + 13 + 10); a walk that handles only `ast.Assign` finds **30** and silently misses **2** — `_AR3_REMOVED` and `_AR3_ADDED` are `AnnAssign` (`_AR3_REMOVED: dict[str, frozenset[str]] = {...}`). Repo-wide the same two numbers are **33** and **31**, the extra one being `DOC3`'s collision. **Positive control, asserted first**: the same walk over `git show 3b8e037:` bytes of the three owner files reports **32** — the leg finds them when they are there | omit `AnnAssign` from the walk ⇒ the positive control reports 30, not 32 ⇒ DOC2 red · **MEASURED** (33 / 31 / 2) |
| **DOC3** | [A] | **The retired-names check is scoped to the three owner files, not to bare names** — a same-named constant elsewhere is not this unit's to delete | `pytest -k test_doc3_retired_check_is_owner_scoped`. **MEASURED**: `test_u_corrob.py:65` binds its **own** unrelated `_BASE_SHA`; a bare-name check over `cli/` would demand deleting it. The test asserts that file is untouched **and** that the check still reports the owner files clean | scope the check to `cli/` by bare name ⇒ DOC3 red (it would flag `test_u_corrob.py:65`) · **MEASURED** collision |

| **DOC4** | [A] | **The two rows that land PERMANENTLY in the corpus describe r5's design.** `S-55` (§10.1) and `FW-140` (§10.2) must each name whole-file byte-pinned fixtures with a dated re-pin door, the anchor-side **node** census compared by normalized **dump**, and the four doors `repinned` / `missing` / `edited` / `edited_exports`. **The greps are evaluated PER ROW, not over the union** *(r5, gate M-6: r4 left this unstated and the criterion reddened on the very rows it governs — `S-55` had `append-only` = 1 and `repinned` = 0, `FW-140` had `node` = 0 and `dump` = 0)* | `pytest -k test_doc4_permanent_rows_describe_the_shipped_design`: for **each** row independently, `grep -c` for `append-only`, `assertion multiset`, `weakened`, `retired` returns **0**, and `grep -c` for `node`, `repinned`, `missing`, `dump` returns **≥ 1**. **MEASURED on the shipped rows**: `S-55` NEG 0/0/0/0, POS 4/1/1/2; `FW-140` NEG 0/0/0/0, POS 2/1/1/1 — both PASS every leg. **Positive control**: the same per-row greps over r4's text of those two rows fail four legs | ship r4's `S-55` wording ⇒ DOC4 red on `append-only` and `repinned` · **MEASURED** pre-state |

**Criteria total: 42, all [A]** — ARM **6**, FIX 4, ADD 3, BEH 9, EXM 3,
DEL 5, GATE 3, UN 5, DOC 4. *(r6 adds `ARM6`, the refusal-writes-nothing
leg gate r4's M-2 found unspecified.)* *(r4: `BEH8`/`BEH9` restore the two anti-rot
legs gate M-2 found unenforced; `DOC4` makes the accuracy of the two
permanent rows a criterion. Rebuilt in r4: `ARM2`, `ARM5`, `BEH1`, `BEH3`,
`BEH7`, `EXM3`, `GATE1`, `FIX4`.)*

---

## 6. Mutation plan

Each row names the **exact edit** and the criterion whose named test must
go **RED**. Cells are `predicted` unless marked **MEASURED** (a pre-state
read off `3b8e037` during this spec's census, so the "before" half is fact
and only the "after" half is a prediction).

| # | Mutation (the exact edit) | Criteria that redden | Cell |
|---|---|---|---|
| M1 | `test_armor.py`: add a second module-level sha table to `test_worker_contract.py` | ARM1 | **MEASURED** pre-state (one such table exists today) |
| M2 | `ARMOR["test_worker.py"].nodes`: `80` → `79` | ARM2 | **MEASURED** anchor value **80** (§2.10) *(r5, gate M-4: the field was renamed to `nodes` and the value is 80, not 52)* |
| M3 | delete the `"support.py"` row from `ARMOR` | ARM3, FIX3 | `predicted` |
| M4 | `ANCHOR = "deadbeef"` (nonexistent) | ARM4 | `predicted` |
| M5 | `conftest.py` (tmp copy): delete one line from inside an anchor-era statement | FIX1 | `predicted` |
| M6 | `conftest.py` (tmp copy): append `def _no_real_sdk_spawn_tripwire(): pass` — a shadowing redefinition | **FIX1** *(r4, gate M-7: r3 mapped this to FIX2, which is now the re-pin door; the bytes change, so FIX1 is what reddens)* | **MEASURED** |
| M7 | `support.py` (tmp copy): delete an exported helper | **FIX1** (on the `support.py` row) *(r4, gate M-7)* | `predicted` |
| M8 | `Fixture.repinned` (fixture table): leave an entry on a file that is byte-identical to its anchor | **FIX2**'s anti-rot leg *(r4, gate M-7: r3 named the dead field `Fixture.edited` and mapped it to FIX4, which is the diagnostic leg)* | `predicted` |
| M9 | `fake_claude.py` (tmp copy): append a module-level rebinding of a pre-existing global | ADD1 (leg 4) | **MEASURED** as a live evasion (`test_worker_contract.py:960-975`) |
| M10 | `fake_claude.py` (tmp copy): append `import socket` | ADD2 | **MEASURED** as the shipped HY3 leg |
| M11 | `fake_claude.py`: edit `_scenario_error_result`'s body | ADD3 — and **NOT** ADD1 (proving ADD3 is load-bearing, since `SU4B` leg 1 exempts it) | **MEASURED** exemption (`_SU4B_SANCTIONED_EDITED_FUNCS`) |
| M12 | `test_worker.py` (tmp copy): delete `test_run_idle_when_nothing_eligible` | BEH1 | **MEASURED** as an anchor name (§2.10) |
| M13 | `test_worker.py` (tmp copy): rename that same test | BEH1 (as one deletion) | `predicted` |
| M14 | `_census`/`B1`: make the name check an equality instead of a subset | BEH2 | `predicted` |
| M15 | `test_repair.py` (tmp copy): change one `assert x == n` to `assert x >= n` | BEH3 (the dump changes) | `predicted` |
| M16 | `test_repair.py` (tmp copy): delete one of two identical asserts in one test | BEH3 | `predicted` |
| M17 | `test_worker.py` (tmp copy): reword one protected test's DOCSTRING and reflow its body | **nothing** must redden; if anything does, BEH4 red | `predicted` |
| M18 | `_norm_dump`: stop stripping docstrings, or set `include_attributes=True` | BEH4 | `predicted` |
| M19 | `test_worker.py` (tmp copy): edit `sdk_fake_worker`'s body | BEH5 | `predicted` |
| M20 | `B5`: implement the export derivation with a **line regex** instead of `ast.ImportFrom` | BEH5 — the set falls 31 → 20 and the multi-line control fails | **MEASURED** (11 skipped multi-line sites) |
| M21 | `_census`: return `{}` | BEH1, BEH3, BEH7 | `predicted` |
| M22 | `Behaviour.missing` (fixture table): add an entry naming a key that still exists | **BEH8** *(r4, gate M-2: r3 pointed this at BEH2, which tests that adding is free and could not redden)* | `predicted` |
| M23 | `Behaviour.edited` (fixture table): reason `"refactored"`, no `§`/`FW-` citation | EXM1 | `predicted` |
| M24 | `test_armor.py`: insert `if name == "<a live test name>": continue` into `B1`'s loop | EXM2 | `predicted` |
| M25 | ship `Behaviour.missing`/`edited` pre-populated with `c3b48e7`'s **56 + 190** entries (grandfathering) | EXM3 | **MEASURED** counts (§2.10) *(r5, gate M-4: r4 cited 35 + 169, the retired assert-census figures)* |
| M26 | leave `_AR1_SANCTIONED_PIN_LINES` in `test_u_sdka.py` | DEL1 | **MEASURED** pre-state |
| M27 | leave `test_hy5_numstat_bounds_hold` collected | DEL2, UN3 | **MEASURED** pre-state |
| M28 | drop `B4` entirely and claim §4.7 row 12 is covered | DEL3 | `predicted` |
| M29 | delete `test_pin2_armor_sha_paths_are_byte_unchanged` instead of retargeting it | DEL4 | **MEASURED** as the only executable consumer |
| M30 | copy the retired justification prose into `test_armor.py` instead of retiring it | DEL5 | **MEASURED** baseline (1450 comment lines) |
| M31 | omit the "removed positive controls" clause from §1.4a | GATE1 | **MEASURED** pre-state (0 hits today) |
| M32 | write §1.4a's trigger as "a protected file" with no definition | GATE2 | `predicted` |
| M33 | reword runbook §1 step 4 while inserting 4a | GATE3 | `predicted` |
| M34 | add a row to `test_lock_invariant.py::NOT_REPO_TRUTH` | UN2 | `predicted` |
| M35 | edit `test_worker.py` to make a census count come out even | UN5 | `predicted` |
| M36 | leave `ANCHOR` at an older merge's parent — **`15fb676`** — i.e. the chain was not run for the latest merge | **ARM5 leg (b) ONLY**; (a) and (c) both still pass | **MEASURED** at tip `37f48c4`: (a) rc=0, (b) `STALE` (expected `3b8e037`), (c) 0 *(r5, gate M-3: r4 named `ac2161a`, which is itself a merge with 2 parents — not a merge's parent — claimed legs (b) **and** (c), and cited the retired count form)* |
| M37 | land the code and skip the `15-orchestration-runbook.md` edit | DOC1, GATE1 | **MEASURED** pre-state (all five greps = 0) |
| M38 | implement DOC2's walk with `ast.Assign` only, omitting `AnnAssign` | DOC2 (its positive control reports 30, not 32) | **MEASURED** (`_AR3_REMOVED`/`_AR3_ADDED` are `AnnAssign`) |
| M39 | scope the retired-names check to `cli/` by bare name instead of to the three owner files | DOC3 (it flags `test_u_corrob.py:65`'s own `_BASE_SHA`) | **MEASURED** collision |
| M40 | touch any file under `plugins/self-learn/cli/src` | UN1 | `predicted` |
| M41 | give `test_armor.py::_census` an unannotated container return so pyright's `cli` error count moves off 56 | UN4 | **MEASURED** baseline (runbook `:131`) |
| M42 | delete `test_u_corrob.py` (the last importer of `test_route_cli.py::_skill_gates_yaml`) and edit that helper in the same diff | BEH6 | **MEASURED** (31 → 30, the named loss) |
| M43 | `test_worker.py` (tmp copy): flip one `True`→`False` on a **setup** line of `test_dead_pid_window_reopens` | BEH3 | **MEASURED** — RED under dump identity, GREEN under r2's assert census |
| M44 | `test_invocation.py` (tmp copy): delete the `with pytest.raises(...)` block at `:1186-1187` | BEH3 | **MEASURED** — RED (`test_rg1_...`), invisible to r2 |
| M45 | append `_cache_env = "PWNED"` (a rebinding of a pre-existing global) to a `conftest.py` copy; likewise `_GIT_SHIM` on `support.py` and `__all__` on `backends.py` | FIX1 (all three) | **MEASURED** — all three PASS r2's `F1`/`F2`, all three redden the whole-file sha |
| M46 | let `F3`'s "additive" diagnostic short-circuit `F1` | FIX4 | **MEASURED** as r2's own defect |
| M47 | land a post-merge commit that touches **nothing protected** (real history: `801c746`, whose whole diff is `1 1 test_worker_contract.py` — not a protected path — on merge `8d3d5bc`) | **nothing** must redden; if `ARM5` fires, M47 red | **MEASURED**: protected files moved since `8d3d5bc` = **0**, leg (c) GREEN *(r5, gate M-2: r4 asserted this reddens leg (c), which would force the census back to the count form §3.6 rejects — a commit touching nothing protected staying green is the guarantee, not a defect)* |
| M48 | make `--remeasure` a no-op (leave the `ANCHOR` literal unchanged) while still exiting 0 | the landing chain's `&&` aborts; `ARM5` red on the next round | **MEASURED** as r2's `sed -i` failure mode (gate N-5) |

| M49 | `test_repair.py` (tmp copy): mutate the module-level constant `RECORD_QUOTE` (`:82`), read by 10 protected tests | BEH3 | **MEASURED** — `edited=['assign:RECORD_QUOTE']` RED; **GREEN under r3** |
| M50 | `test_invocation.py` (tmp copy): replace `_run_sdk`'s body with `return None` (22 call sites, 9 tests); likewise `test_repair.py::_gates_raises` and `test_worker.py::_wait_for_file` | BEH3 | **MEASURED** — all three RED; **all three GREEN under r3** |
| M51 | `Behaviour.missing` (fixture table): entry naming a key that still exists at head | BEH8 | `predicted` |
| M52 | `Behaviour.edited` (fixture table): entry naming a key whose dump is unchanged from the anchor | BEH9 | `predicted` |
| M53 | delete the shipped `func:test_wr7_…` `edited` entry | EXM3 (1 ≠ 0) | **MEASURED** census edited = 1 |
| M54 | add a second, unowed `edited` entry | EXM3 (2 ≠ 1) | **MEASURED** |
| M55 | land a commit touching a protected file after the anchor merge | ARM5 leg (c) only — (a) and (b) still pass | **MEASURED** (tip `1251552`, count 1) |
| M56 | ship r3's `S-55` wording (append-only fixtures, "assertion multisets", "WEAKEN") | DOC4 | **MEASURED** pre-state |

| M57 | implement `--remeasure` **write-then-refuse**: run it on a tree with one owed-but-unexempted key, write the entry, re-run | ARM6 both legs — leg 1 (the file's sha changed on a refusal) and leg 2 (the second run trips the no-op guard instead of succeeding) | `predicted` |
| M58 | an exemption reason citing a sha that does not resolve (`"2026-08-28 deadbee: …"`) | EXM1's resolution leg — **not** its grammar legs, which it satisfies | **MEASURED**: `deadbee` fails `git cat-file -e`; `fe5a012`/`3b8e037` pass |
| M59 | delete a protected file outright (`test_composer.py`) | BEH1's deleted-file leg, with the named message | **MEASURED**: 58 missing of 58 nodes against an empty head |

**Mutations total: 59.** Every one of the 42 criteria has at least one row.
Four rows are the inverted shape — two that must redden **nothing** (M17,
proving BEH4's permissive leg is permissive; **M47**, proving a post-merge
commit touching nothing protected stays green, which is what the §3.6
deviation guarantees) and two that must redden **part** of a criterion but
not all of it (**M36** isolates `ARM5` leg (b); **M55** isolates leg (c) —
between them they prove each leg carries weight the other does not). **M43-M46 and M49-M50 are the two gates' own successful attacks,
promoted to mutations**: every one was measured GREEN on the revision it
was found against and must be RED now. That is what makes "strictly
stronger than the whole-file sha it retires" a measurement rather than a
claim — six attacks, six measured colour changes.

---

## 7. Scope

### IN

1. One new file, `plugins/self-learn/cli/tests/test_armor.py` — the
   anchor, the `ARMOR` table, the extractors, the `--remeasure` `__main__`
   block the landing chain calls (§4.2), and the enforcing tests for all 38
   criteria.
2. Deletion of the retired mechanisms from `test_worker_contract.py`,
   `test_u_sdka.py`, `test_u_fake.py` — the 21 constants and 10 tests
   listed in **§13**, with their justification prose (`DEL1`/`DEL2`/`DOC2`).
3. Retargeting `test_u_corrob.py::test_pin2_armor_sha_paths_are_byte_
   unchanged` (`DEL4`). Its own unrelated `_BASE_SHA` (`:65`) stays
   (`DOC3`).
4. **`15-orchestration-runbook.md` — three insertions** (§10.3): §1.4a's
   guard-amendment review, the §8 reviewer line, and §5's landing-chain
   re-anchor step (`GATE1`-`GATE3`, `DOC1`).
5. `03-decisions.md` — one new row, `S-55` (§10.1).
6. `14-forward-work-map.md` — two new rows, `FW-140` and `FW-141` (§10.2).
7. **§13's retired-names list**, in this spec, as `DOC2`'s single source of
   truth.

### OUT — each a real thing a builder might reach for

1. **A test-placement rule** ("a test asserting `worker` behaviour must
   live in `test_worker.py`"). §3.1 option E. Recorded as `FW-141`.
2. **Touching `test_lock_invariant.py`** — `UN2` pins it byte-unchanged.
3. **The UI package.** `plugins/self-learn/ui/tests` gets no armor.
4. **Any production source file.** `UN1`.
5. **Editing any protected file.** `UN5`. If the census does not come out
   even, the count literal is wrong, not the file.
6. **Advancing `ANCHOR` past the build base**, or folding any historical
   delta into an exemption map. `EXM3` ships eleven empty maps.
7. **Golden fixture files** (`fixtures/golden/*`, 4 files, 2 consumers).
   They are data, not code, and `ast`-based legs do not apply. Raised as
   Q-3 (§11).
8. **Renaming or moving any protected file.** A path change would need a
   table edit under the very gate protocol this unit is writing; it is not
   this unit's motion.

---

## 8. Files this unit may touch

| Path | What |
|---|---|
| `plugins/self-learn/cli/tests/test_armor.py` | **NEW.** The whole mechanism |
| `plugins/self-learn/cli/tests/test_worker_contract.py` | DELETE `_ARMOR_SHAS`, `_SU4B_DIFF_EXEMPT`, the three `_SU4B_SANCTIONED_*` sets, `_FAKE_CLAUDE_RELPATH`, `BASE_COMMIT`, `test_su4a_*`, `test_su4b_*`, `_stmt_key`, `_load_module_from_path`, `_load_fake_claude_module`, and their ~470 lines of prose. Its other ~38 tests are untouched |
| `plugins/self-learn/cli/tests/test_u_sdka.py` | DELETE `_BASE_SHA`, `_AR1_*`, the five `_AR3_*`, `_HY3_SCENARIO_SHAS`, `test_ar1_*`, `test_ar3_*`, `test_hy3_*`, `test_hy5_*` and their prose. `test_ar5_*` and everything else stays (§4.7 row 13) |
| `plugins/self-learn/cli/tests/test_u_fake.py` | DELETE `REWRITTEN`, `DS1_ADDED`, `DS1_REMOVED`, `_DS1_EXPECTED`, `BASE_REF`, `_git_show_base`, `_extract_guarded_functions`, `_extract_named_function`, `_inverse_rename*`, `test_ds1*`, `test_ds2*`. Its `FX`/`T1` tests stay — and the file becomes a `Behaviour` key, protected by the mechanism it used to be |
| `plugins/self-learn/cli/tests/test_u_corrob.py` | RETARGET `test_pin2_*` only (`DEL4`). No other test in that file is touched |
| `docs/specs/self-learn/15-orchestration-runbook.md` | INSERT §1.4a, one §8 line, **and** §5's landing-chain re-anchor step (§10.3). Deletions **0** (`GATE3`) |
| `docs/specs/self-learn/03-decisions.md` | APPEND row `S-55` |
| `docs/specs/self-learn/14-forward-work-map.md` | APPEND rows `FW-140`, `FW-141` |
| `docs/specs/self-learn/drafts/u-armor-narrow-whole-file-pins-spec.md` | This file |

**Explicitly NOT touched**, and asserted: the 12 protected files (`UN5`),
`test_lock_invariant.py` (`UN2`), all of `cli/src` and `ui/` (`UN1`).

**A note the builder must not miss.** Three files carry *prose references*
to the retired symbols that are not code and do not break: `report.py:703`,
`test_invocation_sdk.py:1206`, `test_u_opsfix.py:18`,
`test_u_corrob.py:7/:17/:1040`. `DEL1`'s grep would flag them. **Resolve
this by scoping `DEL1`'s grep to `ast`-visible names, not raw text** — a
docstring mentioning `_ARMOR_SHAS` is history, and rewriting six historical
docstrings is exactly the kind of churn this unit exists to stop. `DEL1`'s
check statement above says "symbol", and the builder implements it with
`ast`, with a positive control proving the `ast` walk finds the real
assignments at `3b8e037` and ignores the docstrings.

```sh
$ grep -rnE '\b(_ARMOR_SHAS|_SU4B_[A-Z_]+|_AR1_[A-Z_]+|_AR3_[A-Z_]+|_HY3_SCENARIO_SHAS|REWRITTEN|DS1_ADDED|DS1_REMOVED|_DS1_EXPECTED|BASE_COMMIT|_BASE_SHA|BASE_REF)\b' \
      plugins/self-learn/cli --include='*.py' | wc -l
183
```
Raw-text hits at `3b8e037`: **185** *(r4, gate M-8: r3 added `_FAKE_CLAUDE_RELPATH` to the alternation but left the control at 183, which is the count WITHOUT it — measured 183 / **185**)*. The `ast`-scoped form must return
**0** after the build while this raw form still returns the handful of
historical docstring mentions — a build that drives the RAW count to 0
has rewritten six historical docstrings and is over-scoped.

---

## 9. Parallel units

Two T2 units are in flight in worktrees alongside this one:
`u-hostmode-p2` and `u-verbs`. Neither worktree was read (orchestrator
constraint); every claim below is measured against **master's** copy of the
sibling's own committed spec text and against master's code.

### 9.0 Landing order — RULED: **U-armor lands AFTER U-hostmode Phase 2**

Ruling Q-5 (§3.4) **overruled** r1's recommendation, with the measured
reason: Phase 2 is already gate-verified and landing within the hour, and
the collision cost §9.1 measures — the `test_wr7` re-pin (sha + dated
paragraph + `hy5` re-measure) — **has already been paid on its branch**.
Landing U-armor first would idle a finished unit to save a cost already
spent.

Two consequences, both binding:

1. **The builder's FIRST step, before writing any code**, is to re-run every
   number in §2 against post-Phase-2 master and record the re-measurement in
   the build report. `ARM2` (counts match the anchor) and `ARM5` (the anchor
   is the latest first-parent merge) are what make a skipped re-measurement
   RED rather than silently wrong.
2. **Which numbers moved, and which did not.** Phase 2 edited
   `test_invocation.py` (§9.1) and deleted `chezmoi.py`. The prediction was
   that `ARMOR["test_invocation.py"]`'s **`dump_sha`** would move — the
   `== 11` assertion becoming `== 10` changes
   `test_wr7_seam_is_only_called_from_the_three_call_sites`'s normalized
   dump — and that its `tests` literal would not, since a tuple edit adds
   and removes no test. **Both confirmed** (§2.10): `dump_sha` moved
   `9551b489ab53` → `6cf96b790678`, `tests` stayed **48**, and **all seven
   other rows are byte-identical**. The 31-name export surface and §2.6's
   import graph are unchanged. A row that moves unexpectedly is a finding
   for the builder to report, not a number to quietly update.

§9.1 is kept in full, re-framed: it is no longer a scheduling argument but
**the worked example of what the old armor costs**, priced both ways, on a
real collision that actually happened.

### 9.1 `U-hostmode` Phase 2 — **a real collision, measured**

Phase 2 deletes `chezmoi.py` wholesale (`u-hostmode-git-optional-hosts-
spec.md` §4.8, §5.11 `CHEZ`; `14-forward-work-map.md` FW-122: *"Phase 2
(the `chezmoi.py` deletion and adopt-surface removal) not yet landed"*).
Does that touch a protected file?

```sh
$ for f in conftest.py backends.py support.py test_invocation.py test_invocation_sdk.py \
           test_u_fake.py test_worker.py test_repair.py test_attrib.py test_route_cli.py \
           test_composer.py fixtures/fake_claude.py ; do
    printf '%-26s %s\n' $f "$(grep -ci chezmoi plugins/self-learn/cli/tests/$f)" ; done
conftest.py                0
backends.py                0
support.py                 0
test_invocation.py         1
test_invocation_sdk.py     0
test_u_fake.py             0
test_worker.py             0
test_repair.py             0
test_attrib.py             0
test_route_cli.py          0
test_composer.py           1
fixtures/fake_claude.py    0
```

**Yes — one hit, and it is load-bearing.** `test_invocation.py:1951`, inside
`test_wr7_seam_is_only_called_from_the_three_call_sites`:

```python
excluded_by_name = ( ..., "ledger_ops.py", "chezmoi.py", "hook_compiler.py" )
assert len(excluded_by_name) == 11
...
for entry in excluded_by_name:
    if entry.endswith(".py"):
        assert (src_dir / entry).is_file(), f"excluded file {entry} does not exist under {src_dir}"
```

The `is_file()` leg (added by that test's own `F3` fold, `:1963-1968`; the
count assertion is at `:1954`) means
**deleting `chezmoi.py` makes this test RED until the tuple is edited.**
U-hostmode Phase 2 must touch `test_invocation.py`, which is protected
under both mechanisms. What it costs, each way:

| | today | after U-armor |
|---|---|---|
| edit | remove one tuple entry, `11` → `10` | same |
| armor toll | re-pin `_ARMOR_SHAS["…/test_invocation.py"]` + a dated paragraph above it + re-measure `test_hy5_numstat_bounds_hold`'s `(737, 760)` row | **one** `Behaviour.edited` entry: `{"test_wr7_seam_is_only_called_from_the_three_call_sites": "U-hostmode P2 §4.8 — chezmoi.py deleted; the exclusion tuple loses one entry"}` |

The `11 → 10` edit changes the assertion's ast dump, so `BEH3` reddens and
the exemption is genuinely owed — the mechanism is doing its job, and the
gate reviews one line instead of three surfaces.

`test_composer.py`'s hit is `assert "chezmoi" not in text` (`:1095`) — a
negative over the doctrine text. It stays true after the deletion, and its
assertion expression does not change. **No exemption owed there.**

**What actually happens, given the ruling.** Phase 2 lands first and pays
the **left-hand column** — it already has, on its branch. U-armor then
lands on top, and the right-hand column describes what the *next* unit in
this position will pay instead. The table is therefore not a proposal; it
is a before/after with the "before" already banked as fact.

**Phase 2's edit is the first real exemption, and it ships in the table.**
*(r4, gate B-1: r3 argued the opposite here — that the edit was "inside the
anchor" and no entry was owed. That is true only for `ANCHOR = fe5a012`,
the merge itself, which is the value §4.2's own control (iii) rejects.
Under the correct `ANCHOR = M^1 = 3b8e037`, the merge's delta sits
*between* the anchor and head, which is exactly what makes it the gate's
evidence.)*

Concretely, `ARMOR["test_invocation.py"]` ships:

```python
Behaviour(nodes=94, dump_sha="604f7537d5c8037c...",
          edited={"func:test_wr7_seam_is_only_called_from_the_three_call_sites":
                  "2026-08-28 U-hostmode Phase 2, fe5a012: test_wr7's exclusion "
                  "tuple loses chezmoi.py and its count assertion moves "
                  "11 -> 10. See section 9.1."})
```

One key, one dated reason, reviewed by §4.8's guard-amendment clause. That
is the whole cost, against the sha + dated paragraph + `hy5` re-measure the
old mechanism charged for the same edit (the left-hand column above).
`EXM3` asserts the shipped entry count **equals** the census's own edited
count, so this entry cannot be dropped and a second one cannot be smuggled
in beside it.

### 9.2 `U-verbs` — **its no-collision claim, independently verified**

`u-verbs-ledger-verb-completion-spec.md` §2.9 (*"Armor and lock-invariant
collision — MEASURED ZERO"*) and `UN5` (*"No `_ARMOR_SHAS` entry moves. All
seven pinned files are byte-unchanged"*). Re-measured here rather than
inherited, with that spec's own three-verb pattern:

```sh
$ for f in conftest.py backends.py test_invocation.py test_invocation_sdk.py \
           test_u_fake.py test_worker.py test_repair.py ; do
    printf '%-24s %s\n' $f "$(grep -cE '\brehome\b|\brescope\b|\breopen\b' plugins/self-learn/cli/tests/$f)" ; done
conftest.py              1
backends.py              0
test_invocation.py       0
test_invocation_sdk.py   0
test_u_fake.py           0
test_worker.py           0
test_repair.py           0
```

**Verified.** The single hit is `conftest.py:156` — *"…cannot reopen"*, the
English word in a comment, exactly as that spec states. Positive control
for the zeros, same command shape on a file where the verbs really appear:
```sh
$ grep -cE '\brehome\b|\brescope\b|\breopen\b' plugins/self-learn/cli/tests/test_rescope.py
50
```

**But U-verbs does touch something this unit must not.** `UN4` requires
`test_lock_invariant.py`'s `_LOCKS` and `NOT_REPO_TRUTH` byte-unchanged and
adds exactly two `_ARGV_FOR` rows. That is why §1 non-objective 3 and `UN2`
forbid this unit from touching that file at all — a migration of the lock
walker into `ARMOR` would collide head-on with a criterion of a unit
already in flight.

### 9.3 The shared-surface table

| Shared surface | U-armor (this unit) | U-hostmode P2 | U-verbs | Assumption this spec makes |
|---|---|---|---|---|
| `test_worker_contract.py::_ARMOR_SHAS` | **DELETES it** | Re-pins `test_invocation.py` (already paid on its branch) | **Touches nothing** (`UN5`, verified §9.2) | **P2 lands first (RULED, §9.0).** Its re-pin is inside U-armor's anchor, so U-armor re-measures `ARM2`/`ARM5` at the new tip and owes no exemption |
| `test_invocation.py` | **Protects, never edits** (`UN5`) | **Must edit** (§9.1, the `is_file()` leg) | Untouched | The one measured collision; §9.1 prices it both ways and is now the worked example, not a scheduling argument |
| `test_lock_invariant.py` | **UNTOUCHED** (`UN2`) | Untouched | `_LOCKS`/`NOT_REPO_TRUTH` pinned byte-unchanged; `_ARGV_FOR` +2 rows | Disjoint by construction — this unit's `UN2` is the guarantee |
| New test files | `test_armor.py` | — | `cli/tests/test_u_verbs.py`, `ui/tests/test_u_verbs.py` | Distinct names; no collision |
| `15-orchestration-runbook.md` | INSERTS §1.4a + one §8 line | Not in its docs-owed list | Not in its docs-owed list (`§11` names 03, 14, 02, `review.md`, `routing-doctrine.md`, `11`) | This unit is the only claimant on that file |
| `03-decisions.md` | `S-55` | `S-51` | `S-54` | Reserved, disjoint; ceiling re-derived in §10.1 |

**Two further units, both disjoint, named for completeness** *(r5)*:
**U-scrub** has already landed — it *is* `37f48c4`, this spec's measurement
head (`docs(13)`, 3/3 lines in `13-hosting-and-separation.md`, no CLI
change; verified `git diff --numstat fe5a012..37f48c4 -- plugins/self-learn/cli`
is empty), so it touches no path this unit touches. **U-jsdom** (at
`3b8e037`) is UI-only, and `UN1` pins `plugins/self-learn/ui`
byte-identical.
| `14-forward-work-map.md` | `FW-140`, `FW-141` | `FW-122`-`124` | `FW-133`-`138` (+ `FW-139` minted then **withdrawn** at its r5) | §10.2 deliberately skips `FW-139` |

---

## 10. Docs owed at merge

**Two merges, two footprints** — the convention the `S-54` / `FW-133`-`138`
landing set. The **reservation rows below land with the SPEC merge** and
are written already: `S-55` in `03-decisions.md`, `FW-140`/`FW-141` in
`14-forward-work-map.md`'s FW register, and one dated entry in that file's
§6a. The **runbook amendment (§10.3) is owed at the BUILD merge**, with the
code — `DOC1` is the criterion that makes skipping it RED.

### 10.1 `03-decisions.md` — one new row after `S-54`

**Ceiling re-derived:**

```sh
$ grep -oE '^\| S-[0-9]+' docs/specs/self-learn/03-decisions.md | sort -t- -k2 -n | tail -3
| S-52
| S-53
| S-54
$ grep -rn 'S-55' docs/specs/self-learn --include='*.md' | grep -v worktrees | wc -l
0
```
Positive control for that zero: the same command for `S-54` returns **26**.
**`S-55` is free and is reserved by this unit.**

> **S-55** | **A test-file guard pins an INVARIANT, not a snapshot: every
> armor literal is measured on the ANCHOR side, fixtures are protected
> whole-file with a dated re-pin door, behaviour files are protected by an
> anchor-side census of EVERY top-level AST node compared by normalized
> dump, and advancing the anchor is the landing chain's motion, never a
> builder's.** Measured before the build (code at `3b8e037`): the shipped
> `_ARMOR_SHAS` hashes the WORKING TREE, so **6 of its 7 pins are exempt
> from the base-diff half entirely** and assert only "unchanged since the
> last unit re-pinned it" — producing **41 pin writes across 15 commits and
> 9 units in 30 days**, of which **28 writes across 12 commits fell in the
> last 7 days**. The toll per unit is measured: **FW-117** added **166
> lines to three armor files** to delete one dead function whose own
> production diff was 22 lines, and **U-hostmode Phase 1** added **178**.
> `_AR1_SANCTIONED_PIN_LINES` is a **396-entry literal holding a verbatim
> copy of every line ever added to `conftest.py`** — 15.5% of
> `test_u_sdka.py`. The pin set was never derived: `support.py` (**62
> importers**, the most depended-on module in the CLI test tree) has **no
> armor**, while `conftest.py` (2) and `backends.py` (3) are whole-file
> pinned. And the bookkeeping has decided product questions three times,
> each recorded in the tree: a shipped `report.py` docstring naming the
> armor as the reason for an implementation choice; FW-129 listing a re-pin
> among a deferral's costs; and FW-131's analyst fix *"reverted rather than
> shipped"* against a zero-headroom `hy5` ceiling, landed only after a
> coordinator ruling that *"the cap … is armor BOOKKEEPING, not a design
> constraint"*. **The decision:** one module (`cli/tests/test_armor.py`),
> one table (`ARMOR`), one anchor (the first-parent PARENT of the latest
> first-parent merge). **Fixtures** — derived by import graph, including
> `support.py` — are byte-identical to the anchor, with a single
> `repinned` door carrying a sha and a dated reason; an earlier draft let
> them grow additively instead, and that was **measured** to admit an
> appended module-level rebinding on all three. **Behaviour files** are protected
> node-wide: **627 top-level nodes** across eight files — 366 tests, 93
> non-test defs, 40 module constants, 8 classes, 120 imports — each keyed
> by name and compared by normalized AST dump, because a census of test
> functions alone was **measured** to miss a mutated constant read by 10
> tests and a gutted helper called at 22 sites. A unit may ADD nodes freely
> and may not DELETE or EDIT one without an entry in `missing` / `edited` /
> `edited_exports` whose reason cites a spec section and carries a date, and
> which cannot outlive its subject. **Deletion stays legal; it stops being
> silent.** | `U-armor` spec §2 (the census), §3.2 (the recommendation),
> §4.7 (the disposition of all 17 existing mechanisms), §3.5/§3.6 (two
> blind spec gates, 2 blockers and 20 majors folded). Reopens if a fourth
> armor mechanism is proposed outside `ARMOR`, or if a measured evasion
> passes all of `F1`-`F3` / `B1`-`B7`. |

### 10.2 `14-forward-work-map.md` — two new rows

**Ceiling re-derived:**

```sh
$ grep -ohE '\bFW-[0-9]{1,3}\b' docs/specs/self-learn/14-forward-work-map.md | sed 's/FW-//' | sort -n | tail -1
138
$ grep -rn 'FW-140\|FW-141' docs/specs/self-learn --include='*.md' | grep -v worktrees | wc -l
0
```
**Ordering note — `FW-139` is a TOMBSTONE, not a free number** (ruling Q-1,
§3.4). It exists **only** inside `u-verbs-ledger-verb-completion-spec.md`,
minted at that spec's r4 and withdrawn at its r5 (*"FW-139 is WITHDRAWN …
the FW ceiling stays at FW-138 with no numbered hole"*, `:1093`). The number
is still **spent** in that document's text — a reader who greps `FW-139`
finds a withdrawal, not a vacancy — and U-verbs is in flight, so a later
revision could re-mint it. **This unit therefore skips `FW-139` by ruling
and reserves `FW-140` and `FW-141`.** Anyone re-deriving the ceiling should
read `FW-139` as a headstone: the number is used, the row is not.

>
> **FW-140** | **The anchor advance is automated; the EXEMPTION FOLD it
> implies is not, and nothing verifies the fold was correct.** The
> mechanical half is settled: the landing chain re-anchors inside the merge
> commit (`merge --no-commit` → `--remeasure` → `commit`), and `ARM5` fails
> loudly on a stale anchor, and `--remeasure` re-derives every node count
> and `dump_sha` from the new anchor. What survives is the judgement half.
> When the anchor advances, every accumulated `repinned` / `missing` /
> `edited` /
> `edited_exports` entry whose subject node is now **inside** the new
> anchor becomes vacuous and must be dropped — `FIX2`/`BEH8`/`BEH9`'s anti-rot
> legs will fail on the stale ones, which is the right direction (loud, not
> silent), but they fail **after** the chain has already pushed, and
> nothing checks that the human who emptied the doors did so for the right
> reason rather than to get the suite green. `--remeasure` deliberately
> re-derives the *owed* entries but never silently deletes an existing one,
> because a tool that quietly drops an exemption is a tool that quietly
> forgets why it existed. | WATCH | Trigger: the first landing where an
> anti-rot leg goes red *after* a chain run, or the first merge train where
> any single door exceeds ~5 entries. Whoever takes it writes the fold
> procedure into `15-orchestration-runbook.md` §5, beside the existing
> merge rules, and rules on whether a dropped exemption owes a line in the
> review record |

> **FW-141** | **Nothing connects a test to the file it belongs in, so the
> suite fragments by unit rather than by subject.** Measured 2026-08-28:
> **34** test files created since 2026-08-01; of the **17** created after
> the armor landed (`29f5d67`, 2026-08-19), **11 — carrying 299 tests** —
> exercise a production module that a pinned behaviour file also exercises,
> and none owed a re-pin. U-armor
> removes the *incentive* (an in-file addition is now free) but adds no
> *rule*. Two of the seventeen are the shape most clearly forced by the old
> pin:
> `test_litter_guard_probes.py` (a guard-of-the-guard for a fixture inside
> the pinned `conftest.py`) and `test_serve_hermetic.py` (created by the
> same commit that re-pinned `conftest.py`). Source: `U-armor` spec §2.7,
> §3.1 option E. | WATCH | Trigger: a third file appears whose whole
> subject duplicates a protected file's, or a reviewer cannot find where a
> behaviour is tested. Building it means deriving a subject→file map over
> 34+ files and ruling on what "belongs" means — a design round, not an
> addition. **Do not conflate it with U-armor**: the armor's job is to stop
> silent weakening, not to organise the suite |

### 10.3 `15-orchestration-runbook.md` — the two-gate process doc

**This is the doc that governs the two-gate process, and it is the only one
in the corpus that tells a gate what to check** (§0 item 2). It says nothing
today about a protected file — measured: `guard-amendment` returns **0**
across every `.md` and `.py` in the repo, against a control of **1** for
`mutation verification` in this same file. The amendment is an **owed edit
with its own criterion** (`DOC1`), not a nice-to-have, because the whole
design of §4.5 rests on a human reviewing one exemption line: if the gate
is never told to look at it, the exemption maps become an unreviewed
escape hatch and the mechanism is weaker than the byte pin it replaced.

**Three insertions, zero deletions** (`GATE3`):

1. **§1.4a — the guard-amendment review.** Full text in §4.8: five clauses
   (deleted or renamed tests; weakened assertions; removed positive
   controls; edited fixtures; anchor advance), each reported as its own
   finding, with a mechanical trigger (`GATE2`: *"a key in
   `cli/tests/test_armor.py::ARMOR`"*) so a gate evaluates it without
   judgement.
2. **§8 — one line in the reviewer half of "Prompt skeletons":** *"if the
   diff touches a key of `cli/tests/test_armor.py::ARMOR`, run §1.4a's
   guard-amendment review and report each clause separately."*
3. **§5 — the landing chain's re-anchor step** (ruling Q-4, §3.4), beside
   the existing merge rules: the two commands of §4.2 verbatim, the
   statement that a builder never advances the anchor, and the pointer that
   the resulting `git diff --stat <old> <new>` is the **next** gate's
   starting evidence. `DOC1` greps `--remeasure` for this one.

**Where the landing chain itself lives is out of this unit's reach** — see
§12 item 7. The runbook is the normative statement; whoever maintains the
chain script implements it against that text.

---

## 11. Questions — all RULED

r1 raised six open questions. **All six were ruled by the orchestrator on
2026-08-28**; the rulings, their reasoning, and what each changed are in
**§3.4**. This section is the index, kept so a gate can check that no
question was quietly dropped.

| # | Question | Ruling | Lands in |
|---|---|---|---|
| **Q-1** | `FW-139` — skip it or claim it? | **SKIP** — it is a tombstone in the U-verbs spec, not a vacancy | §10.2's ordering note |
| **Q-2** | Is `test_u_fake.py` a `Behaviour` row, or retired outright? | **KEEP as a `Behaviour` row** | §4.1's table |
| **Q-3** | Do the golden fixtures get protection? | **OUT.** The honest anchor-side shape is recorded as a note, not a criterion | §4.3's closing paragraph; §7 OUT 7 |
| **Q-4** | Should `ANCHOR` advance automatically at merge? | **Manual in judgement, automated in mechanics: the LANDING CHAIN advances it, never a builder**, with the exact commands specified and staleness reported loudly by the census | §4.2 (rewritten), §4.8's anchor clause, **`ARM5`**, **`M36`**, `FW-140`, §10.3 item 3 |
| **Q-5** | U-armor before or after U-hostmode Phase 2? | **OVERRULED — U-armor lands AFTER Phase 2.** Phase 2 is gate-verified and landing; its collision cost is already paid, so landing U-armor first would idle a finished unit to save a spent cost | §9.0 (new), §9.1 (re-framed), §9.3 |
| **Q-6** | One file or two? | **One file, `test_armor.py`** | §4.1 |

**Nothing in this spec is now awaiting a decision.** A gate finding a
genuine fork should raise it as a finding, not assume it was deferred here.

---

## 12. What could NOT be measured

1. **Whether any of §2.7's seventeen new files was created *in order to*
   avoid a re-pin.** The overlap is measurable (**11 of 17, 299 tests**);
   intent is not. §2.7 states this explicitly and the spec's argument does not rest
   on intent — it rests on the cost asymmetry, which is measured in §2.3.
   `FW-141` records the open half.
2. **The two sibling worktrees' current contents.** `u-hostmode-p2` and
   `u-verbs` were not read (orchestrator constraint). §9's claims are
   measured against master's copies of their committed spec text and
   master's code. If either worktree has since changed its own spec, §9.1's
   collision and §9.2's verification must be re-run at merge.
3. **The exact post-build suite count.** `UN3` states the shape
   (2666 − 10 + N) but N depends on how many `test_*` functions the builder
   writes for 41 criteria; the spec does not prescribe a one-test-per-
   criterion mapping. The build report must quote the collector.
4. **Whether the dump census is fast enough.** It parses and dumps **627
   top-level nodes** on the anchor side and 627 on the head side, per
   session.
   Not measured — no implementation exists. If it is slow, the builder
   caches the anchor dumps per session; flagged here so a gate does not
   treat a performance fold as scope creep. *(r3: r2's version of this item
   worried about `F1`'s subsequence match, which no longer exists —
   fixtures are a single sha now.)*

4a. **Three anchor tests carry no `assert` at all** —
   `test_invocation_sdk.py::test_sy3_exception_propagates_with_original_type_both_branches`,
   `::test_rs4_non_import_error_from_claude_agent_sdk_propagates`, and
   `::test_hg1_no_bare_claude_list_literal_outside_the_worker_invoke_claude_pattern`
   (measured; they assert through `pytest.raises` and structural walks
   instead). Under r2's assert census `B3` was **vacuous** for all three.
   Under r3's dump identity they are covered exactly as any other body is —
   the disposition is "subsumed, no special case needed" *(gate N-4)*, and
   it is recorded here rather than left for a builder to rediscover.
5. **Whether any *existing* protected test is already weaker than the
   anchor version it replaced.** The census compares head to a single
   anchor; it cannot see a weakening that happened *before* the anchor.
   `EXM3`'s zero-exemption start is honest about this: it means "nothing
   from before is grandfathered in," not "nothing before was wrong." The
   `c3b48e7` positive-control run (§2.10) shows **190 nodes edited and 56
   missing**
   since 2026-08-19 — every one of them gated and sanctioned at the time,
   and none re-reviewed here (§1 non-objective 4).
5a. **The `other:` key class is content-hashed, and is empty today.** Any
   top-level node that is not a def, class, assignment or import falls
   through `_key` to `other:<hash of its own dump>` — so an *edit* to such
   a node would read as a *delete*. After M-1's module-docstring fix the
   class is **measured empty**: 0 `other:` nodes across all eight files at
   every anchor, and 0 top-level `Assign` nodes with a non-`Name` target (a
   tuple-unpack assignment would be the first). Latent, not live; recorded
   so a future unit adding one is not surprised by the misclassification.

6. **Where the landing chain script actually lives.** Ruling Q-4 binds the
   re-anchor to the chain, and §4.2 specifies the exact commands — but the
   chain is **orchestrator-side and not in this repository**. Measured:
   there is no `scripts/` directory, and `misc/` holds only gate logs and
   measurement artifacts, no landing script. So this unit can specify the
   normative text (`15-orchestration-runbook.md` §5, `DOC1`) and the
   callable half (`test_armor.py --remeasure`, in-repo and testable), but
   **it cannot test that the chain calls it.** `ARM5` is the compensating
   control: if the chain is never wired up, the very next round's armor
   suite fails on a stale anchor and names the chain in the message. That
   is a detection, not a prevention, and the difference is stated here so a
   gate does not read `ARM5` as proof the automation exists.

7. ~~**Whether §9.0's "which numbers move" prediction is right.**~~
   **RESOLVED — measured.** Phase 2 landed as `fe5a012` while this revision
   was being written, and the prediction held exactly: one protected file
   touched (`test_invocation.py`, +1/−2), one test edited
   (`test_wr7_seam_is_only_called_from_the_three_call_sites`), `dump_sha`
   moved, `tests` did not, seven rows byte-identical, and one `_ARMOR_SHAS`
   re-pin paid under the old mechanism — the cost §9.1 priced. §2.10 and
   §9.0 carry the numbers. Retained here rather than deleted so a gate can
   see that a stated unmeasurable was closed, not dropped.

8. **`pyright`'s post-build number.** `UN4` quotes the documented baseline
   (56 pre-existing in `cli/src`) from the runbook; the build must
   re-measure, since this unit adds a new module with `dataclass` and `ast`
   usage that has not been type-checked.

### 12.1 The stale-statement sweep — a fix for the CLASS, not a finding

Six revisions have retired vocabulary and numbers. Every gate has found at
least one place a fold did not reach, so r5 swept the whole document
mechanically rather than trusting the folds — **and the sweep itself was
wrong**. It matched exact literals (`"635 nodes"`), the live text said
`"635 top-level nodes"` and `"(635 vs 366)"`, and it carried no term for
`49` at all, so it reported `LIVE = 0` on a document with three stale
values — one of them in `S-55`, which lands permanently in the corpus.

**r6 fixes both halves.** The sweep matches **regex patterns**, not
literals; and it asserts a **classifier control** — every raw match must
land in exactly one bucket:

```python
assert len(hist) + len(cited) + len(live) == raw, "a hit was lost in classification"
```

Seventeen patterns are swept — r2/r3 vocabulary, r3 field names, r4's node
totals and all eight of its `dump_sha` prefixes, the pre-Phase-2 collector,
and the retired count-form figure. Each hit is filed as:

- **historical** — inside §3.4-§3.8's gate-fold tables, §R, or this
  subsection, where quoting what was corrected is the point;
- **cited** — the term is the *subject* of its own line (a criterion naming
  the string it greps, a mutation row naming the wrong thing it ships, an
  inline `(rN, gate X: …)` annotation), detected by markers on the line;
- **live** — everywhere else. **This must be zero.**

**The run that matters is the one before the fix** — this is the positive
control, and it is a control for the *classifier and the matcher together*,
because it is a real failure the instrument caught on its own document:

```
########## PRE-FIX (r5's text, r6's sweep) ##########
patterns swept: 17    raw matches: 30
  historical: 19   cited: 6   LIVE: 5
  classifier control: 19+6+5 == 30 raw  OK

LIVE hits (must be 0):
   line  1634: '635'               [r4 node total (now 627)]
   line  2091: '635'               [r4 node total (now 627)]
   line  2263: '49 tests changed'  [r2 assert-census figure (now 190 edited)]
   line   568: '183'               [FALSE POSITIVE -- a line citation, FW-129 (:183)]
   line  1850: '183'               [FALSE POSITIVE -- the legitimate 183-vs-185 contrast]
```

It found **the gate's three, plus two false positives of its own** — the
honest cost of a broad pattern, and the reason the sweep prints every
classified line for a human rather than just a count. Five LIVE lines,
matching the block above and its `19 + 6 + 5 == 30` arithmetic. The bare `\b183\b` pattern was narrowed to the claim form
(`control **183**`); the three real hits were fixed.

```
########## POST-FIX (this revision) ##########
patterns swept: 17    raw matches: 34
  historical: 30   cited: 4   LIVE: 0
  classifier control: 30+4+0 == 34 raw  OK
```

*(The raw count rises from 30 to 34 between the two runs because r6 adds
§3.8's fold table and §R's r6 row, both of which quote the corrected values
by design — they land in `historical`, which is what that bucket is for.)*

**The zero rests on the instrument having caught a real, live failure on
this document** — not on the matcher finding hits in regions it was told to
ignore. That was r5's mistake: a control that could not see the failure
mode that actually occurred.

---

## 13. Retired names — the list a future grep must find nothing for

Ruling addendum (§3.4): the retired mechanisms' names are listed here so a
future reader greps once and is done, and so `DOC2` has a single source it
can compare itself against (the test asserts its own checked set **equals**
this list, so the doc and the code cannot drift apart).

**Scope: the three owner files only** — `test_worker_contract.py`,
`test_u_sdka.py`, `test_u_fake.py`. This scoping is load-bearing, not
tidiness: `test_u_corrob.py:65` binds its **own**, unrelated `_BASE_SHA`,
and a bare-name check across `cli/` would demand deleting it (`DOC3`,
`M39`).

**Constants (22)** — `ast.Assign` *or* `ast.AnnAssign`; two of them are
annotated, which is why `DOC2`'s walk must handle both (`M38`). *(r3, gate
N-1: r2's heading said 21 while the list carried 22.)*

`_ARMOR_SHAS` · `_SU4B_DIFF_EXEMPT` · `_SU4B_SANCTIONED_EDITED_FUNCS` ·
`_SU4B_SANCTIONED_NEW_FUNCS` · `_SU4B_SANCTIONED_NEW_SCENARIO_KEYS` ·
`_SU4B_SANCTIONED_NEW_STMT_KEYS` · `_FAKE_CLAUDE_RELPATH` · `BASE_COMMIT` ·
`_AR1_TRIPWIRE_SHA256` · `_AR1_SANCTIONED_PIN_LINES` · `_AR3_REASONS` ·
`_AR3_RENAMED` · **`_AR3_REMOVED`** *(AnnAssign)* · **`_AR3_ADDED`**
*(AnnAssign)* · `_AR3_ONE_LINE_ONLY` · `_HY3_SCENARIO_SHAS` · `_BASE_SHA` ·
`REWRITTEN` · `DS1_REMOVED` · `DS1_ADDED` · `_DS1_EXPECTED` · `BASE_REF`

**Test functions (10):**

`test_su4a_whole_file_armor_shas` · `test_su4b_fake_claude_additive_only` ·
`test_ar1_tripwire_byte_unchanged` ·
`test_ar3_edited_is_exactly_21_functions_with_reasons` ·
`test_hy3_fake_claude_additions_are_additive` ·
`test_hy5_numstat_bounds_hold` ·
`test_ds1_t3_function_bodies_survive_the_inverse_rename` ·
`test_ds1b_removed_set_is_exact_and_every_entry_is_base_only` ·
`test_ds1c_added_set_is_exact_and_every_entry_is_head_only` ·
`test_ds2_rewritten_set_is_exact_and_every_entry_is_live`

**Helpers deleted with them** (not separately listed above because each is
unreachable once its caller is gone, and `DEL2`'s collector check covers
the observable effect): `_stmt_key`, `_load_module_from_path`,
`_load_fake_claude_module` (`test_worker_contract.py`); `_git_show_base`,
`_extract_guarded_functions`, `_extract_named_function`, `_inverse_rename`,
`_inverse_rename_text` (`test_u_fake.py`).

**Positive control — the count today.** The `ast` walk `DOC2` runs, over
the three owner files at `3b8e037`:

```
test_u_fake.py             9
test_u_sdka.py            13
test_worker_contract.py   10
                      ------
                          32   ast-visible occurrences
```

An `ast.Assign`-only walk over the same three files finds **30** and
silently misses `_AR3_REMOVED` and `_AR3_ADDED`. Repo-wide the two figures
are **33** and **31**, the extra occurrence being `DOC3`'s collision.
**After the build the owner-scoped number must be 0**, and the positive
control is that the same walk over `git show 3b8e037:<path>` still reports
32 — absence proven by an instrument shown to find them.

*(Raw-text greps are a different and much larger number — **185** at
`3b8e037` — because six historical docstrings mention these names. Those
are history and stay; see §8's note. Never use the raw count as the gate.)*

---

## R. Revision history

| r | date | change |
|---|---|---|
| r1 | 2026-08-28 | First draft, authored at `3b8e037` in `.claude/worktrees/u-armor-spec`. 34 criteria (all [A]), 35 mutations, `S-55` + `FW-140`/`FW-141` reserved. Six open questions. Not yet gated. |
| r7 | 2026-08-28 | **Blind spec gate r5 (delta) → SOUND (0 B / 0 M / 2 N); both prose nits folded.** The gate verified the check-then-write ordering and its two-leg criterion, both `627` fixes, and re-ran the sweep independently — its own `LIVE = 0` reproduced under an independent classifier control. **`N-1`**: §2.10's census header and §4.2's leg preamble still named `37f48c4` as live master; both now name **`6038eee`** (§2.10 reworded to "measured against the `fe5a012` CLI tree — byte-identical at live master `6038eee`"). **`N-2`**: §12.1's summary sentence over-counted its own five-line LIVE block (the "two the gate did not report" and the "two false positives" were the same two `183` lines); restated to "the gate's three, plus two false positives of its own", matching the block's `19 + 6 + 5 == 30`. **Reservation rows written** per the `S-54` convention: `S-55` into `03-decisions.md`, `FW-140`/`FW-141` into `14-forward-work-map.md`, one dated entry into its §6a. Criteria **42**, mutations **59** (unchanged). |
| r6 | 2026-08-28 | **Blind spec gate r4 → NOT SOUND (0 B / 2 M / 4 N) — the first round with no blocker; all 6 findings folded** (§3.8). The gate verified every r3 finding folded and **adjudicated the r5 ruling correction right**. **`M-2`**: `--remeasure`'s ordering was unspecified, and write-then-refuse **deadlocks the landing chain** — the literals are already advanced when the refusal fires, so the post-fix re-run trips the no-op guard and the only escape is the hand-edit `ARM2` catches. §4.2 now fixes six steps: resolve, census, compute the owed set, **refuse writing nothing**, render the whole module to a temp file and `os.replace()` it atomically, then the no-op guard. **New `ARM6`** (a refusal leaves the file byte-identical, `sha256` before == after; second leg proves the re-run then succeeds) and **`M57`**. **`M-1`**: the retired `635` survived in `BEH7`'s cell and in **`S-55`**, whose own breakdown sums to 627 — and §12.1's sweep reported clean. Diagnosis sharpened by measurement: the failure was **matcher narrowness**, not misfiling — its terms were exact literals (`"635 nodes"`) and the text says `"635 top-level nodes"` and `"(635 vs 366)"`. r6 sweeps **regex patterns** and asserts the classifier control `historical + cited + live == raw`; re-run on r5's text it reports **5 LIVE** (the gate's three, two more, and two of its own false positives), post-fix **0**. **`N-1`** §12 item 5 → 190 edited + 56 missing. **`N-2`**: `EXM1` gains a **resolution leg** — a 7–40-hex anchor must satisfy `git cat-file -e` (measured: `deadbee` does not resolve, `fe5a012`/`3b8e037` do); **new `M58`**; the residual (a sha that resolves but is irrelevant) named as §4.8's job. **`N-3`**: `BEH1` gains a deleted-file leg with the named message *protected file &lt;path&gt; missing — every node missing; refuse*; **new `M59`**. **`N-4`**: live master is `6038eee`; the retired count form now reads **5**. Criteria **41 → 42**; mutations **56 → 59**. |
| r5 | 2026-08-28 | **Blind spec gate r3 → NOT SOUND (1 B / 6 M / 3 N); all 10 findings folded** (§3.7). The gate called r4 *"the strongest revision by a wide margin"* — census exact at all four anchors, **all sixteen `dump_sha` literals recomputed**, six previously-GREEN attacks RED, four new attacks (decorator argument, nested function, class body, import-source swap) caught, and **the `ARM5` leg-(c) deviation adjudicated SOUND**. **`B-1`**: the one exemption entry the design ships **failed `EXM1`** (Python comments write "section N" where prose writes "§N"). Ruled two ways: exemption entries are written **only by humans/builders — `--remeasure` never writes one and instead REFUSES**, exiting non-zero naming the owed keys; and `EXM1`'s grammar becomes **a date AND an anchor** (`20\d\d-\d\d-\d\d` plus `§\d` / `FW-\d+` / `S-\d+` / a 7–40-hex sha), with five measured negative controls isolating each half. **`M-1`**: a module-docstring reword was classified as a **deletion** (the docstring survived as its own content-keyed `other:` node) — and `test_u_fake.py`'s contains `guard`, a §4.8 BLOCKER by default. `_Strip` now runs **at module level**: the `other:` column falls to **0**, the census is **627 nodes** (was 635 — exactly the eight docstrings), all four anchors restated (`3b8e037` 0/1, `fe5a012` 0/0, `15fb676` 0/5, `c3b48e7` **56**/190), and all sixteen literals re-derived. All four M-1 attacks re-verified RED. **`M-2`/`M-3`**: `M47` re-framed as an inverted-shape row (measured: `801c746` moves **0** protected files, so leg (c) correctly stays green) and `M36` re-pointed at `15fb676`, **leg (b) only** (`ac2161a` is itself a merge). **`M-4`**: `M2` → `.nodes` 80; `M25` → 56 + 190. **`M-5`**: §4.6's "every door shut" and its `BEH2`/`BEH4` anti-rot mapping corrected to `FIX2`/`BEH8`/`BEH9`. **`M-6`**: `DOC4`'s greps are **per row**, and both shipped rows now pass every leg (measured). **Nits**: §4.8 says *nodes*, drops *weakened*, and scopes the guard-in-docstring BLOCKER to **test bodies only**; the `other:` class recorded as latent with its measured zero; §12 items 3/4/5 → 41 / 627 nodes / 190+56. §9.3 names **U-scrub** (landed as `37f48c4`) and **U-jsdom** (UI-only) as disjoint. **One correction to a ruling, measured**: the r4 reason string **passes** the widened grammar (its `fe5a012` is a valid anchor), so it cannot be `EXM1`'s negative control — five strings that genuinely fail take its place. Criteria **41** (unchanged); mutations **56** (unchanged; four rows corrected). Not yet re-gated. |
| r4 | 2026-08-28 | **Blind spec gate r2 → NOT SOUND (1 B / 10 M / 7 N); all 18 findings folded** (§3.6). Every changed number re-measured in a detached checkout at `fe5a012` (head byte-identical to live master `37f48c4`, a docs-only scrub). **`B-1`**: r3 shipped `ANCHOR = "fe5a012"` — the merge itself, the value its own control (iii) rejects. Ships **`ANCHOR = "3b8e037"`** (`= fe5a012^1`), all sixteen literals re-derived there, and **one `edited` entry** (`func:test_wr7_…`, Phase 2's `== 11` → `== 10`) — the mechanism working, not a defect. `EXM3` rewritten from "ships empty" to "ships exactly what the anchor→HEAD diff owes", entry count asserted equal to the census's edited count; §9.1's closing paragraph now says the opposite of what it said. **`M-1`**: the census is **node-wide** — every top-level AST node keyed by name and compared by normalized dump. **635 nodes**, not 366 tests: 93 non-test defs, 40 module constants, 8 classes, 120 imports were all unguarded. Four measured attacks now RED that were GREEN under r3 (`RECORD_QUOTE`; `_run_sdk`, `_gates_raises`, `_wait_for_file`). **`M-2`**: **new `BEH8`/`BEH9`** restore the two anti-rot legs r3 stated and enforced with nothing; `M22` re-mapped. **`M-3`**: `_dump_sha` quoted (sort by key; join `key\0dump\0`; utf-8; sha256) and all sixteen literals re-derived under it. **`M-4`-`M-8`**: `GATE1`'s keywords (`retired` measured 0 in r3's own §4.8 text) and clause count six; §4.8's dead `Fixture.edited` bullet deleted; `EXM3`'s doors and control; `M6`/`M7` → `FIX1` and `M8` → `FIX2`; `DEL1`'s control 183 → **185**. **`M-9`**: all four anchor blocks re-run at one head under the node census (`3b8e037` 0/1, `fe5a012` 0/0, `15fb676` 0/5, `c3b48e7` 57/190); collector **2666**. **`M-10`** + nits: §12.1 and `FW-141` restate **17 / 11 / 299**; `test_hostmode.py` **124**; `S-55` and `FW-140` **rewritten wholesale** to r4's design and their accuracy made a criterion (**new `DOC4`**). **One deviation from a ruling, recorded in §3.6**: `ARM5` leg (c) is *"no protected file moves after the anchor merge"*, not `rev-list --count ANCHOR..master^ == 0` — the count form measures **4** on live master and would ship a criterion red on a correct tree. Criteria **38 → 41**; mutations **48 → 56**. Not yet re-gated. |
| r3 | 2026-08-28 | **Blind spec gate r1 → NOT SOUND (1 B / 10 M / 5 N); all 16 findings folded** (§3.5 is the finding-by-finding table). Every changed number re-measured in a detached read-only checkout at `3b8e037`. **`B-1`**: `ARM5` was unsatisfiable — r2's chain committed the re-anchor *after* the merge, forcing leg (c) to 1. **`ANCHOR` is redefined as the first-parent PARENT of the merge**, the chain re-anchors *inside* the merge (`--no-commit` → `--remeasure` → `commit`), and `--remeasure` now rewrites the literal itself and exits non-zero on a no-op (gate N-5). Three red controls added, all real history. **`M-2`**: **fixtures stay WHOLE-FILE byte-pinned** — r2's subsequence match let an appended global rebinding through on all three fixtures (measured); `F1` is a sha, `F2` is the dated re-pin door, `F3` is a diagnostic that can never override `F1` (`FIX4`). **`M-3`**: the behaviour census now pins each test's **normalized AST dump**; assert counting is retired. Both gate probes measured RED (setup-line flip; `pytest.raises` deletion). Sensitivity over `c3b48e7`: 49 → **169** edited. **`M-4`**: the export surface is derived **anchor-side** and cannot shrink (`BEH6`). **`M-1`**: the surface is **31**, not 20 — r2's figure came from a line regex that skipped 11 multi-line imports; `BEH5` now forbids the regex and its control is multi-line. **`M-5`**: `UN1`/`UN4` get mutation rows. **`M-6`-`M-10`, `N-1`-`N-4`**: 7-day figures **12 / 28**; conftest control **16**; the dodge census re-derived over the true **17** files (**11 overlap, 299 tests**, was 8 / 179); consumer census **1 / 9, total 24**; the three `test_u_fake.py` ranges and the 251-line block (**233** comment); §13 says **22** constants and `_FAKE_CLAUDE_RELPATH` joins `DEL1`; the three zero-assert tests get a stated disposition. Criteria **38** (five rebuilt); mutations **39 → 48**. Not yet re-gated. |
| r2 | 2026-08-28 | **All six open questions RULED by the orchestrator and folded** (new §3.4; §11 becomes the index). **Q-4** binds the anchor advance to the **landing chain** with two specified commands (§4.2 rewritten), a rewritten §4.8 anchor clause, **new `ARM5`** (stale anchor is loud — three measured predicates, positive control against `ba90ef9`: ancestor-yes but `STALE`, count **9**) and **`M36`**; `FW-140` re-scoped from "the procedure is unwritten" to the **exemption fold** that survives automation. **Q-5 OVERRULED**: U-armor lands **after** U-hostmode Phase 2 (new §9.0; the builder's first step is re-measuring §2 against post-Phase-2 master; §9.1 re-framed as the worked example of the old armor's cost, no longer a scheduling argument). **Q-1** records `FW-139` as a **tombstone**. **Q-3**'s golden-fixture shape lands as an "if ever wanted" note in §4.3, not a criterion. Folded alongside: the two-gate process doc's amendment is now an explicit owed edit with **three insertions** (§10.3) and its own criteria — **new `DOC1`/`DOC2`/`DOC3`** and **`M37`-`M39`** — plus a **new §13 retired-names list**, whose measured positive control is **32** ast-visible occurrences owner-scoped (an `Assign`-only walk finds **30**, missing two `AnnAssign` constants; a bare-name walk across `cli/` falsely flags `test_u_corrob.py:65`'s own `_BASE_SHA`). Criteria **34 → 38**; mutations **35 → 39**. Not yet gated. |
