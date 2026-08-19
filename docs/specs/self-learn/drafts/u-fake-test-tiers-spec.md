# Spec — U-fake: test-harness disambiguation and tiering

Status: **r4 — CLEARED FOR BUILD.** Three gate rounds, 27 findings, all
folded (§§12–14 map each to its change). r1 blind gate: **NOT SOUND — 1
BLOCKER / 6 MAJOR / 10 NOTE** (§12). r2 delta gate: **1 BLOCKER / 3
MAJOR / 4 NOTE** (§13), with all 17 r2 folds verified, `MAJOR C`
**conceded to this document** (the gate's own AST recount found three
`not-in` controls, matching `MV-c1`), and `SH-a1`'s byte arithmetic
reproduced exactly. r3 delta gate: **0 BLOCKER / 1 MAJOR / 1 NOTE**
(§14) — `FZ-b1` independently reimplemented and verified, `M32`/`M33`
spot-executed with clean negative controls, and **`CS-b2` settled in this
document's favor**: the gate reproduced both scenarios, confirmed the
equality control is inert in *both* wrong ones, and adopted the
path-anchored control. Both r3 findings were one-clause substitutions, so
the round closed under the **verdict-repricing rule** and **no further
spec gate follows** — the code gate downstream verifies these folds.

**Across all three rounds no measurement in this document was
overturned; every finding was structural.**

**The two rounds have the same shape, one level apart.** r1 specified
what the unit does to the suite and forgot that **the unit is itself an
addition to the suite** — its criterion tests landed in the modules it
froze, falsifying four of its own criteria. r2 fixed that with a separate
home (§3.9) and an equality-shaped count guard, and **each fold created
the next round's defect**: making `FZ-c` an equality exposed that
`FZ-b`'s filter was asymmetric across the rename and **fails `DS1` on a
correct build** (`FZ-b1`); moving the criterion tests out of `GUARDED`
turned `T1b` into a *source read* that its only mutation could no longer
reach (`M33`).

The lesson r3 records is not "check harder." It is that **a guard written
over a renaming is only sound if it is symmetric in the rename**, and
that **a criterion's mutation must act on the artifact the criterion
actually reads** — source, not behavior, when the criterion reads source.

Unit `U-fake`, **Wave 1** of the approved Agent-SDK migration, merging
**third** of three (`U-sdk` → `U-bedrock` → `U-fake`).

**Base commit:** `c2669a9` (master — `chore: sync ui/uv.lock metadata for
the CLI's new [sdk] extra`, the U-seam follow-through). Every symbol,
count and sha quoted here was read or measured at that commit. **None of
them is a constant.** §1.4 states the re-measurement rule that makes them
survive the two units merging first.

**The unit in one sentence.** Give the suite's two same-named,
mutually-incompatible `claude` shim fixtures distinct names, extract the
bash-shim script text into an importable module so a Wave-2 contract test
can parametrize over `["cli", "sdk"]`, put three real consumers onto the
in-process `FakeBackend`, and prove — by node-ID set, by census, and by
source sha — that nothing else in the suite moved.

**This unit changes no product code.** Not one file under `src/`, not
`pyproject.toml`, not the UI package. A builder who finds themselves
fixing a defect they discovered on the way has left this unit's mandate
and must stop and report. §8 names the residuals it deliberately does not
fix.

---

## Files this unit may touch

**Eight paths, and the split between them is load-bearing** (`BL-1`,
§3.9): rows 1–3 are what the unit **adds**; rows 4–8 are `GUARDED`, what
it must not disturb beyond a declared rename.

| # | File | Footprint |
|---|---|---|
| 1 | `plugins/self-learn/cli/tests/test_u_fake.py` | **NEW.** Home of **all 17** of this unit's criterion tests (§3.9). |
| 2 | `plugins/self-learn/cli/tests/shims.py` | **NEW.** The two bash `claude`-shim builders, extracted verbatim (§3.3). |
| 3 | `plugins/self-learn/cli/tests/backends.py` | **NEW.** `FakeBackend` conveniences for T1 consumers (§3.4). |
| 4 | `plugins/self-learn/cli/tests/test_worker.py` | Fixture `claude_shim` → `claude_cli_shim_worker`; the shim's **script blob only** moves to `shims.py` (§3.3.1); `notify_shim`'s parameter renamed; test bodies get the mechanical rename and nothing else. |
| 5 | `plugins/self-learn/cli/tests/test_repair.py` | Import renamed; **one** compatibility-alias line added (§3.2.3); test bodies get the mechanical rename and nothing else. |
| 6 | `plugins/self-learn/cli/tests/test_attrib.py` | Import renamed; test bodies get the mechanical rename and nothing else. |
| 7 | `plugins/self-learn/cli/tests/test_route_cli.py` | Fixture `claude_shim` → `claude_cli_shim_analyst`; the `CLAUDE_SHIM` script constant moves to `shims.py` (§3.3.2); test bodies get the mechanical rename and nothing else. |
| 8 | `plugins/self-learn/cli/tests/test_composer.py` | `_capture_analyst_prompt` rewritten onto `FakeBackend`; the three `Move-1` tests adapted to it (§3.5). **No fixture is imported into this module.** Nothing else changes. |

Plus `docs/specs/self-learn/drafts/u-fake-test-tiers-spec.md` — this
document.

**Explicitly NOT touched, and each for its own reason:**

| Path | Why |
|---|---|
| `plugins/self-learn/cli/tests/test_invocation.py` | U-seam's, **frozen**. It is the reason §3.2.3's alias exists. Criterion `HY1`. |
| `plugins/self-learn/cli/tests/conftest.py` | *Inside* the brief's permitted surface but deliberately unused: registering a shim fixture there would change fixture resolution for all 1716 tests, which is the opposite of this unit's mandate. A builder who believes they need it has left the design — stop and report. Criteria `SU2`, `HY3`. |
| `plugins/self-learn/cli/tests/support.py` | **49** test modules import it (measured); see `R-3`. Criterion `HY3`. |
| `plugins/self-learn/cli/src/**`, `pyproject.toml` | Tests-only unit. Criterion `HY2`. |
| `plugins/self-learn/ui/**` | Criterion `SU5`. |

---

## 0. Reading order and precedence

1. **§5 (acceptance criteria) and §6 (mutation plan) ARE the spec.**
   Everything else is rationale. Where prose and a criterion disagree,
   **the criterion wins** and the prose is the defect.
2. Every set, name and table is defined **once**, in §2 or §3, and
   referenced by name thereafter. A second definition anywhere is a bug
   in this document.
3. Code is located **by symbol plus a distinctive quoted source line**,
   never by bare line number.
4. Read before this document: `docs/specs/self-learn/drafts/u-seam-invocation-seam-spec.md`
   §3.8 (`Fake-1`) and §4 `SU3` — this unit's tier language and its
   census method are both inherited from there.

---

## 1. Why this unit exists

### 1.1 What is true today

Two fixtures named `claude_shim` exist in the CLI suite. They are
**incompatible**, and nothing tells a reader which one they are getting:

| Definition | Shape | Returns |
|---|---|---|
| `test_worker.py`'s, whose docstring begins *"PATH shim, MULTI-INVOCATION-OBSERVABLE (U-repair F5, §9-X7"* | The model **writes proposal files** via `$CLAUDE_SHIM_SCRIPT`; per-invocation argv/stdin/counter capture | `{"log", "prompt", "dir", "argv", "call_prompt", "count"}` |
| `test_route_cli.py`'s, whose docstring begins *"PATH-shimmed fake `claude`: records argv (one arg per line) to CLAUDE_SHIM_LOG"* | The model's **stdout is the result** — `cat "$CLAUDE_SHIM_OUT"` | `{"log", "out", "cwd"}` |

Four modules consume the first, by the import-a-fixture-by-name
convention `test_repair.py`'s own docstring documents:
`test_worker.py` defines it; `test_repair.py` and `test_attrib.py` each
import it **from `test_worker`**; `test_invocation.py` imports it **from
`test_repair`**. One module consumes the second
(`test_route_cli.py`). A test that imported the wrong one gets a fixture
whose dict has none of the keys it reads, so the failure is loud — but
only *after* someone writes it, and the name gives no warning beforehand.

### 1.2 What Wave 2 needs and cannot get today

A Wave-2 contract test parametrized over `["cli", "sdk"]` needs to
install **a bash shim for the `cli` leg and an SDK fake CLI for the `sdk`
leg**, from the same fixture, chosen by `request.param`. The bash shim
script is today a string literal inside a fixture body, reachable only by
requesting that fixture — which is precisely what the parametrized
fixture cannot do, because requesting it commits the `sdk` leg to a bash
shim too. The script has to become a **function a fixture can call**.

That is the whole reason `shims.py` exists. It is not tidying.

### 1.3 The three tiers (NORMATIVE)

`Tiers-1` — the vocabulary the rest of this document and every downstream
unit uses:

| Tier | What it is | Ships in | Status for new tests |
|---|---|---|---|
| **T1** | In-process `FakeBackend` — no process, no PATH, no shim (U-seam §3.8) | U-seam | **The DEFAULT.** A new downstream test picks T1 unless it has a stated reason not to. |
| **T2** | Contract tests parametrized over `["cli", "sdk"]` — the bash shim × the SDK fake CLI, same assertions both legs | **Wave 2** — not this unit | Written only where a criterion must hold *identically* on both backends. |
| **T3** | The existing bash-shim tests, **unchanged except the fixture rename** | shipped | **Frozen.** Byte-identity regression armor until the final cleanup unit deletes the CLI path. |

**`Tier-a`** This unit ships **T1 conveniences** (§3.4), the **T2 shared
fixtures' raw material** (§3.3), and the **T3 freeze machinery** (§3.6).
It ships **no T2 test.** A builder who writes a `["cli", "sdk"]`
parametrized test has left this unit's mandate.

**`Tier-b`** T3's "unchanged" is not an aspiration, it is criterion
`DS1`, and `DS1` is the criterion the whole unit is built to satisfy.

### 1.4 Every number in this document is a measurement, not a constant (NORMATIVE)

`Meas-1` — `U-sdk` and `U-bedrock` merge **before** this unit. Either may
add tests, and `U-sdk` in particular may add shim-coupled ones. So:

> **Every count, every sha and every distribution in this document was
> measured at `c2669a9` and is recorded as PROVENANCE. The binding form
> of each such criterion is a DELTA against the builder's own rebase
> base, measured by the builder with the same command, and the build
> report records BOTH numbers.**

A criterion written as a bare constant would go stale the moment `U-sdk`
lands and would then be satisfied by editing this document, which is no
guard at all. This is U-seam's `HY5` fold, applied to every number here
rather than to one.

Where this document writes *"132 at base"*, read *"whatever the same
command reports at the rebase base; 132 is what it reported at
`c2669a9`."*

---

## 2. What binds this design from outside it

These are shipped, currently-green facts. Each removes an option this
unit might otherwise have taken. A builder who trips one has a red suite,
not a discussion.

**`B-1` — the suite-wide claude-argv guard reaches all three NEW files.**
`test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`
reads `sorted(tests_dir.glob("*.py"))` and asserts, for **every** line in
**every** `.py` file in `tests/` matching `\[\s*"claude"\s*\]`:

```
assert "worker._invoke_claude(" in line, (fname, lineno, line)
```

`tests/shims.py`, `tests/backends.py` **and `tests/test_u_fake.py`** are
all inside that glob. **None may contain a bare one-element `["claude"]`
argv literal.** Criterion `SH3`. (The shim *files* the builders write are
named `claude`; that is a path, not an argv literal, and does not match.)

**`B-2` — the same guard `inspect.getsource`s the worker shim fixture and
requires two path literals to remain IN THE FIXTURE.** It continues:

```
from test_worker import claude_shim as _claude_shim_fixture

shim_src = inspect.getsource(_claude_shim_fixture)
assert "claude-invocation-count" in shim_src
assert "claude-calls" in shim_src
```

Two consequences, both normative:

- The `from test_worker import ... as ...` line is inside a `test_*`
  body and takes the mechanical rename.
- **The two literals must still be in the FIXTURE's source, not in
  `shims.py`.** A builder who moves `counter = tmp_path /
  "claude-invocation-count"` and `calls_dir = tmp_path / "claude-calls"`
  into the builder function breaks this shipped test. §3.3.1 draws the
  extraction boundary to keep them where they are. Criterion `SH2`;
  mutation `M6`.

**`B-3` — `test_repair.py::test_f6_no_test_invokes_a_real_claude`
`inspect.getsource`s the same fixture and pins a whole line of it.**

```
claude_shim_src = inspect.getsource(claude_shim)
assert (
    'monkeypatch.setenv("PATH", _path_without_real_notify_helper(shims))'
    in claude_shim_src
), "the claude_shim fixture no longer prepends its own shim dir to PATH"
```

So the fixture must keep **that exact line, with the local still named
`shims`**. PATH installation does **not** move to `shims.py`. Criterion
`SH2`; mutation `M7`.

`test_f6` additionally asserts the literal
`'monkeypatch.setattr(subprocess_mod, "run", fake_run)'` is present in
its own source (U-seam `B-2`), which the rename does not touch.

**`B-4` — `test_invocation.py` imports the worker shim BY THE OLD NAME,
FROM `test_repair`, and is frozen.** Its import block reads:

```
from test_repair import (  # noqa: F401 -- fixtures resolved by name
    Env,
    claude_shim,
    env,
    seed_pending,
    _defect_script,
    _t4_missing_target,
    _t4_target_fixed,
)
```

`test_repair.py` obtains `claude_shim` from `test_worker.py`. Renaming
the fixture at its definition therefore breaks `test_invocation.py`'s
import — a **collection error**, not a test failure — unless the name
stays resolvable on `test_repair`. §3.2.3 is that provision, and `V-1`
(**RULED**, §10) records why the freeze holds this wave and who owns
lifting it.

**`B-5` — pytest registers a fixture under the name it is BOUND TO, and a
module-level alias creates a SECOND, INDEPENDENT fixture. Measured, not
recalled** (pytest **9.1.1**, CPython 3.13.11; three-module probe):

| Probe | Result |
|---|---|
| `legacy = renamed` at module scope, `renamed` being `@pytest.fixture`-marked | **Both** names resolve as fixtures |
| A third module doing `from mod_b import legacy` | Resolves; the chain in `B-4` survives |
| One test requesting **both** names | **Two separate instances** (`legacy is renamed` → `False`) |
| `--fixtures-per-test` output | Reports the **requested** name; a double-requesting test emits **two** lines |

The third row is the hazard: a test that ended up with both names would
get two shim directories, two counters and two PATH mutations. The fourth
row is why `SU3` catches it — the census sum rises by one per
double-requesting test.

**`B-5a` — `pytest.MonkeyPatch` has NO `addfinalizer`. Measured on
9.1.1.** Its entire public surface is
`chdir, context, delattr, delenv, delitem, setattr, setenv, setitem,
syspath_prepend, undo`. Teardown registration belongs to the `request`
fixture, not to `monkeypatch`. §3.4's `install_fake` therefore takes
`request` as its first parameter; a helper written against
`monkeypatch.addfinalizer` would `AttributeError` at first call.

**`B-6` — `notify_shim` depends on the worker shim by fixture name.**
`test_worker.py`'s `def notify_shim(claude_shim, tmp_path):` writes its
binary into `claude_shim["dir"]`. Its parameter takes the rename. Three
tests request `claude_shim` **and** `notify_shim` together; renaming one
and not the other would hand those tests two different shim directories,
which is `B-5`'s third row in production.

**`B-7` — `FakeBackend` is reachable only two ways, and one of them is a
trap. Measured.** `registry._dispatch` resolves an absent backend with a
**module-global** lookup of `backend_for`, so:

| Injection | Effect | Measured |
|---|---|---|
| `write_session(spec, backend=fake)` / `text_session(spec, backend=fake)` | works | ✔ |
| `monkeypatch.setattr(self_learn.invocation.registry, "backend_for", …)` | works — `_dispatch` reads the module global at call time | ✔ fake recorded 1 call |
| `monkeypatch.setattr(self_learn.invocation, "backend_for", …)` | **silently does nothing** — `invocation/__init__.py` does `from .registry import backend_for`, a separate binding | ✔ fake recorded **0** calls; the real `CliBackend` ran |

The three call sites do not accept a `backend=` keyword, so a test that
drives `worker.run` / `miner.run` / `analyst.analyze` must use row two.
Row three is U-seam `B-3a`'s fail-open shape wearing a test-helper
costume: on a `Text` step whose stdout the test happens not to assert,
and on any `Writes` step, the miss is **silent**. `BK1` pins the target;
`BK2` is the positive control that makes the miss loud. Mutation `M9`.

**`B-7a` — what row three *degrades to* is PATH-dependent, so no
criterion may assert it.** The probe measured `failure="not-found"`
because no `claude` was on PATH; on a host with a real `claude`, or
inside a test whose fixture has already installed a shim, the
fall-through **spawns something**. Two normative consequences:

- `BK1`'s test **sanitizes PATH** (points it at an empty directory)
  before driving the seam, so no mutation run of this suite can spawn a
  real model, and the fall-through is deterministic.
- `M9`'s reddening reason is **not** `not-found`: inside the three
  `Move-1` tests, `_shim_env`'s PATH shim answers with rc 0 and empty
  stdout, so `outcome.failure is None` and the redness arrives from
  `analyst._parse_yaml_map("")`. `T1b` catches it either way; the row
  states the real mechanism.

**`B-8` — the baseline, measured at `c2669a9`** (§9): CLI suite **1716
collected, 1711 passed, 5 skipped, 0 failed**, 175.19 s. The five skips
are the four `test_lock_invariant.py` *"not a ledger-mutating surface"*
skips and `test_regime_fixes.py`'s *"repo-root suite absent"* — the same
five U-seam `B-8` recorded.

**`B-9` — `ast.get_source_segment` on a `FunctionDef` EXCLUDES its
decorators. Measured.** For a function whose decorators sit at lines 2–3
and whose `def` is at line 4, `node.lineno` is **4** and the returned
segment starts at `def`. A guard built on the naive segment is therefore
**blind to decorator changes**, and `@pytest.mark.skip` on a T3 test
leaves `DS1`, `SU1` (the node is still collected), `SU3` and the whole
suite green while the armor is silently disabled. §3.6 `FZ-b` extracts
from `min(d.lineno for d in decorator_list) ∪ {node.lineno}` instead.
Mutation `M21`.

---

## 3. The change

### 3.1 `Sets-1` — the sets this document refers to by name (NORMATIVE)

```
GUARDED       = (test_worker.py, test_repair.py, test_attrib.py,
                 test_route_cli.py, test_composer.py)      # the T3 modules
ADDED         = (test_u_fake.py, shims.py, backends.py)    # what this unit creates
FIXTURE_NAMES = ("claude_cli_shim_worker", "claude_cli_shim_analyst")
LEGACY_NAME   = "claude_shim"
```

`GUARDED` and `ADDED` are **disjoint**, and keeping them so is `BL-1`
(§3.9) — the r1 BLOCKER's whole content.

`REWRITTEN` — the **seven** top-level functions this unit may rewrite,
written as a literal in `DS1`'s test so widening it is a visible diff:

| Module | Function | Why |
|---|---|---|
| `test_worker.py` | `claude_cli_shim_worker` | the renamed fixture, script blob extracted (§3.3.1) |
| `test_worker.py` | `notify_shim` | parameter rename only (`B-6`) |
| `test_route_cli.py` | `claude_cli_shim_analyst` | the renamed fixture, script constant extracted (§3.3.2) |
| `test_composer.py` | `_capture_analyst_prompt` | rewritten onto `FakeBackend` (§3.5) |
| `test_composer.py` | `test_fold5_project_scope_one_shot_resolves_real_targets_when_bucket_exists` | `Move-1` |
| `test_composer.py` | `test_fold5_project_scope_bucket_exists_but_genuinely_has_no_meta` | `Move-1` |
| `test_composer.py` | `test_fold5_honest_sentinel_when_project_path_truly_not_supplied` | `Move-1` |

**`REWRITTEN` is exhaustive.** Any other top-level function in `GUARDED`
that differs from its base bytes after the inverse rename is a `DS1`
failure, not a judgement call.

### 3.2 `Rename-1` — fixture disambiguation (NORMATIVE)

#### 3.2.1 The two renames

| Was | Becomes | Defined in | Consumers after |
|---|---|---|---|
| `claude_shim` (proposal-writing) | **`claude_cli_shim_worker`** | `test_worker.py` | `test_worker.py`, `test_repair.py`, `test_attrib.py`, `test_u_fake.py` — the last **must import `env` alongside it** (`RN-d`) |
| `claude_shim` (stdout-shaped) | **`claude_cli_shim_analyst`** | `test_route_cli.py` | `test_route_cli.py`, `test_u_fake.py` (no extra import — its parameters are `tmp_path, monkeypatch` only) |

**`RN-d` — importing the worker fixture is not enough; `env` must come
with it.** `claude_cli_shim_worker`'s parameters are
`(tmp_path, monkeypatch, env)`, and `env` is defined in `test_worker.py`.
A module that imports only the fixture gets a **fixture-not-found error**
at request time (probe-verified). So `test_u_fake.py` writes
`from test_worker import claude_cli_shim_worker, env  # noqa: F401`.
This is why `MV-b1` keeps the import out of `test_composer.py`: pulling
the shim in there would drag `env` into that module's namespace too.

**`RN-a`** The returned dict shapes are **unchanged** — same keys, same
value types, same semantics. This is a rename, not a redesign. Criterion
`FX2`.

**`RN-b`** Test **bodies** change only where the fixture identifier
appears: the parameter list, the identifier's uses inside the body, and
the `from test_worker import …` / `from test_repair import …` lines. Any
other edit is a `DS1` failure.

**`RN-c` — test FUNCTION NAMES are frozen, and this is not implied by
`RN-b`.** Two shipped tests carry the fixture's old name in their **own**
names:

```
test_worker.py::test_claude_shim_path_never_resolves_a_real_self_learn_notify
test_worker.py::test_claude_shim_default_notify_send_stub_is_present
```

A blunt `sed s/claude_shim/claude_cli_shim_worker/g` — which is exactly
what a builder reaches for — renames both, changing two node IDs. **The
count stays identical** (53 before, 53 after) and **`DS1` stays green**
(the inverse rename reconstructs the base name), so neither obvious guard
sees it. `SU1`'s node-ID **set** leg is the guard that does. Criterion
`FX5`; mutation `M2`, whose negative-control column is the reason the set
leg exists.

#### 3.2.2 What the rename buys

After `3.2.1`, `LEGACY_NAME` names **one** fixture in the whole suite
(via §3.2.3's alias), not two incompatible ones. The ambiguity is gone
after the *analyst* rename alone; the *worker* rename is what makes the
remaining name self-describing at every use site, and what lets `SU3`'s
per-name census say where each test's shim came from.

#### 3.2.3 `Compat-1` — the one alias, and why it is in `test_repair.py`

`B-4` forbids editing `test_invocation.py`, which imports `claude_shim`
from `test_repair`. So `test_repair.py` gains **exactly one** line:

```python
#: U-fake COMPAT — the ONLY surviving binding of the old fixture name.
#: test_invocation.py is U-seam's and frozen (B-4); it imports
#: `claude_shim` from this module. Delete this line and rename that
#: module's 19 occurrences in U-cleanup (R-1, V-1). Nothing else may
#: request this name — SU3's per-name census is what proves it.
claude_shim = claude_cli_shim_worker
```

**`CP-a`** The alias lives in `test_repair.py`, **not** `test_worker.py`,
because `test_repair` is the module `test_invocation` actually imports
from. Putting it in `test_worker.py` would work too (`B-5` row two) but
would leave the legacy name resolvable in **two** modules instead of one,
doubling the surface `FX4` has to police for no benefit.

**`CP-b`** The alias is **debt, and it is labelled as debt.** `FX4` pins
that it appears exactly once and that exactly one module requests the
name. `R-1` assigns its removal.

**`CP-c`** No test may request both `LEGACY_NAME` and
`claude_cli_shim_worker` — `B-5` row three says that yields two shim
directories. Enforced by `SU3`'s sum (which rises by one per offender)
and by `FX3`'s per-block read. Mutation `M15`.

### 3.3 `Shims-1` — `tests/shims.py` (NORMATIVE)

Public surface, exhaustively:

```python
__all__ = ["write_worker_claude_shim", "write_analyst_claude_shim"]

def write_worker_claude_shim(
    shims_dir: Path, *, counter: Path, log: Path, prompt_log: Path, calls_dir: Path
) -> Path: ...

def write_analyst_claude_shim(shim_dir: Path) -> Path: ...
```

Both **write the executable into an already-existing directory and return
its path**, including the `chmod`. Neither creates its directory (§3.3.1,
§3.3.2). Both are plain functions, **not fixtures** — a
`@pytest.fixture` here could not be called from inside a
`params=["cli","sdk"]` fixture body, which is the entire T2 use case
(§1.2). Criterion `SH4` asserts the not-a-fixture property directly.

**`SH-a`** The script **bytes are unchanged**. Each builder emits, for a
given set of input paths, exactly the bytes the fixture emits today.
Criterion `SH1` pins this with a `sha256` of the **emitted file**, not of
the source constant — so a refactor of how the string is assembled is
free and a change to what it says is not.

**`SH-a1` — the emitted bytes are a FUNCTION OF THE INPUT PATHS, so the
sha is only reproducible under an exactly-named path. Measured.** The
worker script interpolates `tmp_path`-derived absolute paths at six
sites, so the emitted size tracks the path length:

| `tmp_path` | emitted bytes |
|---|---|
| `/tmp/ufake-shim/a` (17 chars) | 802 |
| `/tmp/ufake-shim/fixed` (21 chars) | 826 |
| `/tmp/ufake-shim/a-much-longer-directory-name` (44 chars) | 964 |

`SH1` therefore names its input paths as **literals in the criterion's
own body**, and the build report records them. "A fixed set of input
paths" is not a phrase, it is the difference between a reproducible sha
and a number that means nothing on another machine.

**`SH-b`** `shims.py` imports nothing from `self_learn` and nothing from
any `test_*` module. It is leaf-level; a cycle here would be paid for by
every module in `GUARDED`. Asserted as a leg of `SH4`.

**`SH-c`** Every name in `__all__` has at least one in-suite consumer,
and `__all__` is non-empty. Asserted as a leg of `SH4`. A helper written
for a caller that does not exist yet is unfalsifiable decoration, and T2
is a whole unit away.

#### 3.3.1 The worker extraction boundary (NORMATIVE)

Only the `shim.write_text(...)` blob and its `chmod` move. Everything
`B-2` and `B-3` name **stays in the fixture**:

| Stays in `claude_cli_shim_worker` | Moves to `shims.py` |
|---|---|
| `shims = tmp_path / "shims"` **and its `mkdir`** | the `#!/usr/bin/env bash` script text |
| `counter = tmp_path / "claude-invocation-count"` (`B-2`) | the `chmod` of the `claude` file |
| `calls_dir = tmp_path / "claude-calls"` and its `mkdir` (`B-2`) | — |
| `log`, `prompt_log` assignments | — |
| the inert `notify-send` stub and its `chmod` | — |
| `monkeypatch.setenv("PATH", _path_without_real_notify_helper(shims))` **verbatim** (`B-3`) | — |
| `argv_for` / `prompt_for` / `count` closures and the returned dict | — |

The inert `notify-send` stub stays because it is not a `claude` shim: it
is a PATH-shadowing countermeasure documented in place, and T2 has no use
for it. Criterion `SH2`; mutations `M6`, `M7`.

#### 3.3.2 The analyst extraction boundary (NORMATIVE)

Mirrors §3.3.1 exactly, so the two builders have one contract:

| Stays in `claude_cli_shim_analyst` | Moves to `shims.py` |
|---|---|
| `shim_dir = tmp_path / "shim-bin"` **and its `mkdir()`** | the four-line script text (`printf … > "$CLAUDE_SHIM_LOG"`, `pwd -P > "$CLAUDE_SHIM_CWD"`, `cat "$CLAUDE_SHIM_OUT"`, `exit "${CLAUDE_SHIM_EXIT-0}"`) and its explanatory `pwd -P` / U-analyst A5 comment |
| `log` / `cwd_log` / `out` assignments and `out.write_text("")` | the `chmod` of the `claude` file |
| the three `monkeypatch.setenv("CLAUDE_SHIM_…")` calls and the PATH prepend | — |
| the returned dict | — |

**`SH-d`** Neither builder calls `mkdir`. Directory creation is the
caller's, on both surfaces, because the caller is the one that knows
whether the directory is shared (the worker's `shims` dir also receives
`notify-send` and `self-learn-notify`) — and because a builder that
silently created directories would make `SH1`'s emitted-bytes check
depend on filesystem state it did not declare.

### 3.4 `Backends-1` — `tests/backends.py` (NORMATIVE)

Public surface, exhaustively:

```python
__all__ = ["install_fake", "assert_fake_was_used", "analyst_text"]

def install_fake(request, monkeypatch, steps: list[FakeStep]) -> FakeBackend: ...
def assert_fake_was_used(fake: FakeBackend) -> None: ...
def analyst_text(yaml_body: str) -> Text: ...
```

**`BK-a` — `install_fake` patches `self_learn.invocation.registry.backend_for`
and nothing else.** `B-7` measured why: the package-level re-export is a
separate binding and patching it is a silent no-op. The target module is
named in a criterion so a later refactor of `invocation/__init__.py`
cannot quietly relocate it. Criterion `BK1`; mutation `M9`.

**`BK-b` — `install_fake` installs its own positive control, through
`request`, because `monkeypatch` cannot register one.** `B-5a`: there is
no `monkeypatch.addfinalizer`. So the signature leads with `request`, and
the body ends with `request.addfinalizer(lambda: assert_fake_was_used(fake))`.

`assert_fake_was_used` is **public and separately callable** for exactly
one reason: a finalizer registered inside a helper cannot be observed by
a criterion unless the criterion can invoke it. `BK2` calls it directly
on a `FakeBackend` that recorded nothing and requires it to raise, with a
message naming the fail-open it exists to catch.

Without the control, a test whose step is `Writes(...)` and whose
assertions are all about files on disk passes identically whether the
fake was reached or a real `claude` was spawned and happened to be
absent. Criterion `BK2`; mutation `M10`.

The finalizer, not an inline assertion at the end of each test, because
the point is that **every** consumer gets the control whether or not its
author thought about it.

**`BK-c`** `analyst_text` wraps a YAML map in the ```` ```yaml ```` fence
`analyst._parse_yaml_map` expects and returns a `Text` step. It exists
because all three `Move-1` tests need the identical wrapping, and
inlining it three times is how the wrapping drifts.

**`BK-d`** As `SH-c`: `__all__` non-empty, every name with an in-suite
consumer. Criterion `BK3`. `backends.py` **does** import from
`self_learn.invocation` — that is required, so `SH-b`'s import ban does
not apply here.

### 3.5 `Move-1` — the three T1 conversions (NORMATIVE)

**Exactly three** tests move onto `FakeBackend`, all in
`test_composer.py`, all on the **analyst** surface — named in §3.1's
`REWRITTEN` table.

**`MV-a` — why these three.** They are already faking the transport by
hand: `_capture_analyst_prompt` does
`monkeypatch.setattr(_analyst.subprocess, "run", _fake_run)` and returns
a hand-rolled `_Completed` object with `returncode`/`stdout`/`stderr`.
That is a private re-implementation of exactly what `FakeBackend` is, one
layer too low — it patches the *transport* rather than the *backend*, so
it silently stops covering the seam's failure dispatch and log rendering.
Swapping it is the smallest change that demonstrates T1 serving a real
consumer, and it deletes a duplicate rather than adding a layer.

**`MV-b` — they MOVE ONTO the fake, they do not MOVE FILES.** All three
stay in `test_composer.py`, keep their names and keep their docstrings.
"Move" in the approved plan names the backend, not the location.
Relocating them would change three node IDs and redden `SU1`'s set leg
for no gain.

**`MV-b1` — NO fixture is imported into `test_composer.py`.** The three
tests need only `install_fake`, `analyst_text` and `request` (a pytest
builtin). Importing `claude_cli_shim_worker` here would drag
`test_worker`'s `env` fixture into this module's namespace for no reason,
and `test_composer.py`'s shim census must stay **0** — which is the
independently checkable statement of the same thing (`SU3`).

**`MV-c` — behavior preservation, assertion by assertion.** The rewrite
is a substitution table, not a rewrite:

| Today | After |
|---|---|
| `monkeypatch.setattr(_analyst.subprocess, "run", _fake_run)` | `fake = install_fake(request, monkeypatch, [analyst_text(accepted_yaml)])` |
| `assert argv[0] == "claude" and argv[1] == "-p"` | the same assertion against `fake.argvs[0]` |
| `captured.append(argv[2])` | `fake.argvs[0][2]` |
| `return _Completed(f"```yaml\n{accepted_yaml}```\n")` | the `analyst_text(...)` step |
| `assert len(captured) == 1` | `assert len(fake.argvs) == 1` |
| the **eight** prompt assertions of `MV-c1` | **verbatim, unchanged** |

**`MV-c1` — the eight prompt assertions, enumerated, because r1 wrote
"three" and the five it dropped included every negative control.** Read
from source at `c2669a9`:

| Leg | Assertion | Kind |
|---|---|---|
| 1 | `assert f"ALWAYS target      : {host_str}/CLAUDE.md" in prompt` | positive |
| 1 | `assert f"PATHED rules dir   : {host_str}/.claude/rules" in prompt` | positive |
| 1 | `assert f"DEMAND target      : {host_str}/references/LEARNINGS.md" in prompt` | positive |
| 1 | `assert "unresolvable" not in prompt` | **negative control** |
| 2 | `assert "(unresolvable — project bucket has no meta.yaml)" in prompt` | positive |
| 2 | `assert "record not yet persisted" not in prompt` | **negative control** |
| 3 | `assert "(unresolvable — record not yet persisted; project path not supplied)" in prompt` | positive |
| 3 | `assert "project bucket has no meta.yaml" not in prompt` | **negative control** |

**Three** of the eight are negative controls — the gate's finding said
four; the enumeration above is taken from source and is the binding
statement, so the gate can re-check the count against it. Their job is
structural: legs 2 and 3 assert *complementary* sentinel strings, and
without each leg's `not in` the two collapse into each other — a build
that emitted leg 3's message unconditionally would satisfy both legs'
positive assertions. Dropping them is `M11`.

The argv row of `MV-c` is kept deliberately: it is the assertion that
proves the analyst's prompt rides **argv**, not stdin, and `FakeBackend`
records argv by calling `spec.cli_argv_builder` (U-seam `F-a`), so it
survives the swap with its meaning intact. Criterion `T1c`.

**`MV-d`** `_shim_env` is still called by all three — it builds the
ledger sandbox that `a21`/`a23`/`a24` share, and changing it would reach
outside `REWRITTEN`. Its PATH shim becomes inert for these three, which
is the point: `T1b` asserts the fake was reached, by requiring
`len(fake.argvs) == 1`.

### 3.6 `Freeze-1` — the T3 body-identity guard (NORMATIVE)

**`FZ-a` — the guard is scoped to top-level FUNCTIONS, not to whole
files.** A whole-file sha would redden on `Compat-1`'s alias line and on
the extraction boundary of §3.3.1 — both legitimate — and a builder would
then have to weaken it, which is how a guard dies.

**`FZ-b` — the form.** For each module in `GUARDED`:

1. `ast.parse` the module; collect every top-level `FunctionDef` /
   `AsyncFunctionDef` whose **inverse-renamed name** is not in the
   inverse-renamed `REWRITTEN` set (`FZ-b1`), in source order.
2. For each, take the source from
   **`min([node.lineno] + [d.lineno for d in node.decorator_list])`**
   through `node.end_lineno` — *not* `ast.get_source_segment(source, node)`,
   which **excludes decorators** (`B-9`, measured). Equivalently,
   concatenate the decorators' own segments ahead of the function's.
3. Apply the **inverse rename**: `claude_cli_shim_worker` → `claude_shim`,
   `claude_cli_shim_analyst` → `claude_shim`.
4. `sha256` the concatenation, in order, of those segments.
5. Compare against a per-module hex literal.

Step 2 is the whole of `MAJOR D`: without it, `@pytest.mark.skip` on a T3
test disables the armor while `DS1`, `SU1`, `SU3` and the suite all stay
green. Mutation `M21`.

**`FZ-b1` — the exclusion filter must be applied to the INVERSE-RENAMED
name on BOTH sides, or `DS1` fails on a CORRECT build. Measured.**
`REWRITTEN` holds **post-rename** names. A filter that tests
`node.name ∈ REWRITTEN` is therefore **asymmetric**: at the base commit
the fixture is still called `claude_shim`, so it is *not* excluded and
lands in the extraction; at head it is `claude_cli_shim_worker`, so it
*is* excluded and does not. The two sides then extract different function
sets, and both `FZ-c`'s equality and the sha fail **on a build that did
everything right**:

| Module | total | **extracted under** `node.name ∈ REWRITTEN`, at base | **extracted under** the rule below, at base |
|---|---|---|---|
| `test_worker.py` | 62 | **61** | **60** |
| `test_route_cli.py` | 41 | **41** | **40** |
| `test_repair.py` / `test_attrib.py` | 69 / 48 | 69 / 48 | 69 / 48 |
| `test_composer.py` | 46 | 42 | 42 |

The head-side counts are 60 and 40, so the naive filter is off by exactly
one on each renamed module. The rule:

> Exclude a function iff
> `inverse_rename(node.name) ∈ {inverse_rename(r) for r in REWRITTEN}`
> — i.e. against the set
> `{claude_shim, notify_shim, _capture_analyst_prompt}` plus the three
> `Move-1` test names.

`inverse_rename` is already defined by `FZ-b` step 3; this reuses it, so
there is one rename table in the guard rather than two. `DS2`'s
seven-entry literal is **unchanged** — the inverse is computed, not
stored.

**Why this had to be a normative clause rather than left to the
builder.** A builder who hits the mismatch has exactly three moves, and
**two of them are the failure modes this spec is built to prevent**:
widen `REWRITTEN` until the counts agree (`DS2` reddens — `M22`), or
regenerate the base expectations from the working tree (`M18`, the named
catastrophe). Only the third — this rule — is correct, and nothing in r2
told them which. Mutation `M32`.

**`FZ-c` — the count control comes FIRST, and it is an EQUALITY.** Before
the sha comparison, assert the extracted function count for each module
**equals** its base count. Not "at least": `REWRITTEN` is exhaustive, so
the guarded population is known exactly, and `>=` would tolerate a module
that gained functions — which `M5` is.

An extractor that silently returned `[]` — a filter that stopped
matching, a slice that came back empty — makes every module's sha the sha
of the empty string, and **the guard passes vacuously on a suite that has
been rewritten wholesale.** That is the most dangerous shape a check can
take, and it is the shape this check naturally has.

**`FZ-c1` — and this control's efficacy is PARASITIC ON `DS3`.** If the
extractor is broken *and* the base literals were regenerated with the
same broken extractor, both sides are `sha256(b"")` and both counts are
`0`, and `FZ-c` passes too. The count control catches a *later* breakage;
only `DS3`'s `git show <base>:…` provenance catches a *simultaneous* one.
Neither is sufficient alone. Mutations `M17` (extractor) and `M18`
(provenance) are the two halves.

**`FZ-d` — provenance of the five shas, which a bare literal cannot
carry.** Both obligations, or neither is evidence:

- The shas are computed by running **the same extraction function** over
  the **base commit's** bytes, recovered with
  `git show <base>:plugins/self-learn/cli/tests/<module>` — never over
  the working tree. A sha taken after the edits pins the mutation and
  reports it as the baseline.
- The build report carries
  `git diff <base>..HEAD -- plugins/self-learn/cli/tests/` and the
  reviewer confirms every hunk is either a fixture-identifier rename, the
  §3.3.1/§3.3.2 extraction, `Compat-1`'s one line, a `REWRITTEN`
  function, or an `ADDED` file.

Criterion `DS3`; mutation `M18`. This is U-seam `HY3`'s provenance rule,
which that unit's gate added for exactly this reason.

**`FZ-e` — rejected alternative: a per-function sha map.** ~260 literals
keyed by function name, which would name the drifted function in the
failure message. Rejected: the map is generated, so a builder who
regenerates it after an accidental edit re-pins the accident and the
guard reports green — the same provenance hole as `FZ-d`, but with 260
places to hide instead of five. The concatenated form's worse failure
message is paid for once, by running the `git diff` the message tells you
to run.

### 3.7 `Census-1` — the shim census, delta-shaped (NORMATIVE)

**`CS-a` — the command**, inherited from U-seam `SU3`, run from
`plugins/self-learn/cli`:

```
uv run pytest --fixtures-per-test --color=no -q | grep -cE "^<NAME> -- "
```

once per name in `FIXTURE_NAMES` ∪ `{LEGACY_NAME}`. **Per-module**
distribution is obtained by re-running with the module appended as a path
argument — *not* by parsing the combined output, whose per-fixture lines
do not carry the owning module.

**`CS-b` — the three discriminating checks. r1's version was dead, and
this is what replaces it.** r1 required "read the unpiped rc" and "check
the collected-count line". **Both are useless here, measured:**
`--fixtures-per-test` runs no tests, so it **emits no collected-count
line at all**, and its exit status does not distinguish the two cases.
So, before any count is believed, all three of:

| # | Check | Correct invocation | Non-conforming invocation |
|---|---|---|---|
| 1 | **tail line** of the census run | `no tests ran in <t>s` | an `N errors in <t>s` line where the `no tests ran` line belongs |
| 2 | a **separate** `uv run pytest --collect-only --color=no -q`, run unpiped, its tail and **rc** | `1716 tests collected`, **rc 0** | `<N> tests collected, <E> errors` preceded by `Interrupted: <E> errors during collection`, **rc 2** |
| 3 | a **path-anchored positive control** in the same census output: `grep -cE "^env -- tests/test_worker\.py"` is **> 0** | > 0 | **0** |

Check 2's **rc 2** is the one discriminating exit status in the whole
guard — the census mode's own rc is not. Error and collection **counts**
are environment-dependent and are **not** load-bearing; the *shapes* are.

**`CS-b1` — check 3 must be PATH-ANCHORED, not a bare fixture count, and
this replaces r2's `monkeypatch` control.** A generic-fixture count is
inert: a non-conforming run still collects and still emits fixture
blocks, so `grep -cE "^monkeypatch -- "` reads non-zero on both sides.
The anchor `^env -- tests/test_worker\.py` works because
`--fixtures-per-test` prints each fixture's location **relative to
pytest's rootdir**, and the mandated `cd plugins/self-learn/cli` is
precisely what makes that rootdir the CLI package. Measured: under a
non-conforming invocation the same lines print as
`env -- plugins/self-learn/cli/tests/test_worker.py`, so the anchored
pattern matches **zero** times.

So check 3 is really *"was this the mandated invocation?"*, which is a
stronger question than *"was the cwd right?"* — it also catches the
`uv run --project …` form, which sets the project but **not** the
rootdir and silently collects a different test set.

**And that form is why check 3 is not redundant with check 1. Measured:
`uv run --project <cli> pytest --fixtures-per-test` from the repository
root reports the census as `claude_shim` = 132 — the exactly correct
number — out of a run that collected 1791 tests with 39 errors.** A
wrong-cwd run that reports `0` announces itself; this one hands back the
right answer from the wrong run, so check 1's tail line is the only other
thing that would object and a reader who trusts the number never looks at
it. A guard whose failure mode is *"correct output, invalid run"* needs a
control that observes the **run**, not the output.

**`CS-b2` — a non-reproduction, recorded rather than smoothed over.**
The gate measured a wrong-cwd run collecting **81** tests. That number
could not be reproduced while folding: this drafting harness cannot
`cd`, so its "correct" invocation is emulated with `--project` plus an
absolute path, which leaves rootdir at the repository root — a **third**
scenario, neither the gate's correct run nor its wrong one. In that
emulation the census emitted **1791** blocks against **1791** collected,
i.e. **the equality form of check 3 (`blocks == collected`) was INERT**,
matching on both sides.

The path-anchored form is therefore specified above and the equality form
is **not**. Whether the equality form discriminates under a real `cd`
remains **unverified here**; the gate should re-measure it before any
future revision reinstates it.

This is not hypothetical. **Measured while drafting:** the census command
issued from the repository root instead of `plugins/self-learn/cli`
produced `0` for every fixture name — byte-identical to "no test uses
this fixture." Criterion `SU4`; mutation `M20`.

**`CS-c` — the binding form is the delta.** With `base` = the builder's
rebase base and `head` = the built tree:

```
(worker_count + analyst_count + legacy_count) @ head
  ==  legacy_count @ base  +  2
```

The `+ 2` is **exact and enumerated**: `test_u_fake.py` contains exactly
two census-visible tests, `test_fx2_worker_fixture_shape` (requesting
`claude_cli_shim_worker`) and `test_fx2_analyst_fixture_shape`
(requesting `claude_cli_shim_analyst`). They are **two** tests rather
than one requesting both because `FX3`/`CP-c` forbid a single test
holding two shim fixtures (`B-5` row three).

Separately: `legacy_count @ head == <test_invocation.py's count at base>`
with **all** those lines attributable to `test_invocation.py`, and
`test_composer.py`'s count stays **0** (`MV-b1`).

**`CS-d` — measured at `c2669a9`** (provenance; `Meas-1` governs):

| Name | Module | Count |
|---|---|---|
| `claude_shim` | `test_worker.py` | 32 |
| `claude_shim` | `test_repair.py` | 45 |
| `claude_shim` | `test_attrib.py` | 32 |
| `claude_shim` | `test_route_cli.py` | 16 |
| `claude_shim` | `test_invocation.py` | 7 |
| `claude_shim` | everything else, notably `test_composer.py` | **0** |
| | **total** | **132** |

The same table after this unit, at the same base:

| Name | Modules | Count |
|---|---|---|
| `claude_cli_shim_worker` | `test_worker.py` 32, `test_repair.py` 45, `test_attrib.py` 32, **`test_u_fake.py` 1** | 110 |
| `claude_cli_shim_analyst` | `test_route_cli.py` 16, **`test_u_fake.py` 1** | 17 |
| `claude_shim` (`Compat-1`) | `test_invocation.py` 7 | 7 |
| | **total** | **134 — delta +2** |

### 3.8 `Conserve-1` — suite arithmetic (NORMATIVE)

**`CO-a`** This unit deletes **zero** tests and adds **exactly 17**, all
in `tests/test_u_fake.py` (§3.9). Renames do not change counts; `Move-1`
swaps a backend inside three existing tests. Collected total at
`c2669a9`: **1716**, and after: **1733 — delta exactly +17**.

**`CO-b`** Count equality is **not sufficient**, and `RN-c` is the reason:
a rename keeps the count exactly. The binding assertion is a **node-ID
set relation**, base vs. head, from
`pytest --collect-only --color=no -q`:

```
base ⊆ head                      # nothing deleted, nothing renamed
head ∖ base == the 17 IDs of §3.9, all under tests/test_u_fake.py::
```

Criterion `SU1`. A criterion test homed in a `GUARDED` module puts an ID
into `head ∖ base` that is not under `test_u_fake.py::` and fails this
directly — mutation `M28`.

Per-module collected counts at `c2669a9`, for the report:
`test_worker.py` 53, `test_repair.py` 55, `test_attrib.py` 47,
`test_route_cli.py` 36, `test_composer.py` 31, `test_invocation.py` 65.

### 3.9 `Home-1` — every criterion test lives in `tests/test_u_fake.py` (NORMATIVE)

**`BL-1` — this is the r1 BLOCKER's fold, and it is the reason the unit
is buildable at all.** r1 homed its criterion tests "in the module they
constrain," which meant `test_worker.py`, `test_route_cli.py` and
`test_composer.py` — all `GUARDED`. Every such test **falsifies the
criteria it was written to satisfy**: it puts a new node ID in a guarded
module (`SU1`), raises the collected count off zero-delta (`CO-a`), adds
a top-level `FunctionDef` to a module whose function set is sha-pinned
(`DS1` — r1's own `M5` says so in as many words), and, for any test
requesting a renamed fixture, moves the census.

So: **`GUARDED` and `ADDED` are disjoint, and no test this unit writes
lands in a `GUARDED` module.** The one exception is *assertions added
inside `REWRITTEN` functions* — `T1b`/`T1c`'s assertions live inside the
three `Move-1` tests, which are already declared rewritable; their
**pins** live in `test_u_fake.py`.

**`HM-a` — the cost, stated.** r1 justified two criteria as "visible in
the file it constrains" (`FX5` in `test_worker.py`, `SH2` beside the
extraction). That property is given up. It is worth less than a
self-consistent guard, and `DS1`'s failure message names the file anyway.

**`HM-b` — the 17 tests, enumerated**, because `SU1` and `CO-a` both
quantify over exactly this list:

| # | Test in `tests/test_u_fake.py` | Discharges | Census-visible |
|---|---|---|---|
| 1 | `test_fx1_no_claude_shim_def_statement_anywhere` | `FX1` | |
| 2 | `test_fx2_worker_fixture_shape` | `FX2` | **yes** — requests `claude_cli_shim_worker`; the module must import **`env` alongside it** (`RN-d`) |
| 3 | `test_fx2_analyst_fixture_shape` | `FX2` | **yes** — requests `claude_cli_shim_analyst` |
| 4 | `test_fx4_compat_alias_is_singular` | `FX4` | |
| 5 | `test_fx5_renamed_fixture_did_not_rename_two_tests` | `FX5` | |
| 6 | `test_sh1_emitted_shim_bytes_are_sha_pinned` | `SH1` | |
| 7 | `test_sh2_fixture_retains_the_three_guarded_literals` | `SH2` | |
| 8 | `test_sh3_new_modules_carry_no_bare_claude_argv` | `SH3` | |
| 9 | `test_sh4_shims_public_surface_is_honest` | `SH4` | |
| 10 | `test_bk1_install_fake_patches_the_registry_binding` | `BK1` | |
| 11 | `test_bk2_assert_fake_was_used_fires_on_an_unused_fake` | `BK2` | |
| 12 | `test_bk3_backends_public_surface_is_honest` | `BK3` | |
| 13 | `test_t1a_move1_tests_keep_all_eight_prompt_assertions` | `T1a` | |
| 14 | `test_t1b_move1_tests_assert_the_fake_was_reached` | `T1b` | |
| 15 | `test_t1c_move1_tests_keep_the_argv_shape_assertions` | `T1c` | |
| 16 | `test_ds1_t3_function_bodies_survive_the_inverse_rename` | `DS1` | |
| 17 | `test_ds2_rewritten_set_is_exact_and_every_entry_is_live` | `DS2` | |

Tests 13–15 are **source reads** of `test_composer.py`, not executions of
it, so they add nothing to that module and need none of its fixtures.

**`HM-c`** `test_u_fake.py` is inside `B-1`'s glob, so it too carries no
bare `["claude"]` argv literal — a leg of `SH3`.

---

## 4. Sequencing

**`SQ-1`** Merge order is `U-sdk` → `U-bedrock` → `U-fake`. The builder
rebases onto whatever has landed.

**`SQ-2`** The rebase **should be trivial**: this unit touches no `src/`
file, no `pyproject.toml`, and no UI file, so it cannot conflict with
`U-sdk`'s or `U-bedrock`'s product changes. The realistic conflict
surface is a test module both units edit, and the three `ADDED` files are
new on both sides only if a preceding unit invented the same names —
check before rebasing.

**`SQ-3`** What the rebase **does** invalidate is every number in §3.7 and
§3.8 and every sha in §3.6. `Meas-1` is the standing instruction: measure
at the rebase base, record both, assert the delta. A builder who carries
`c2669a9`'s shas forward without re-measuring has pinned the wrong
baseline and `DS3` fails.

**`SQ-4`** If `U-sdk` has already put its own tests on `FakeBackend` and
written an injection helper, `backends.py` **absorbs** it rather than
competing with it — one injection point, one positive control. Report the
overlap rather than shipping two.

---

## 5. Acceptance criteria

**These criteria are the spec.** **27 criteria** in seven groups: `SU` 5,
`FX` 5, `SH` 4, `BK` 3, `T1` 3, `DS` 3, `HY` 4.

**Every non-instrument criterion is a named test in
`plugins/self-learn/cli/tests/test_u_fake.py` — see §3.9's table for the
mapping.** *Instrument* criteria have no test function and are satisfied
by a command's output recorded in the build report.

### SU — the suite (the headline)

- **`SU1`** The node-ID relation of `CO-b` holds:
  `pytest --collect-only --color=no -q` at the rebase base and at HEAD
  give `base ⊆ head`, and `head ∖ base` is **exactly** the 17 IDs of
  §3.9's table, every one under `tests/test_u_fake.py::`. Both
  directions are reported: `base ∖ head` must be **empty** (nothing
  deleted or renamed) and `head ∖ base` must match the enumeration
  element-for-element. Count alone is insufficient — `RN-c`, mutation
  `M2`. *Instrument criterion.*
- **`SU2`** `git diff --name-only <base>..HEAD -- plugins/self-learn/cli/tests/`
  names **exactly eight** paths: the five `GUARDED` modules plus the
  three `ADDED` files. `conftest.py`, `support.py` and
  `test_invocation.py` are absent. *Instrument criterion.*
- **`SU3`** The census of `CS-c` holds: the three per-name counts sum to
  the base's single `claude_shim` count **plus exactly 2**, those two
  being the enumerated tests 2 and 3 of §3.9; `LEGACY_NAME`'s count
  equals `test_invocation.py`'s base count and is wholly attributable to
  that module; `test_composer.py`'s count is **0**. Attribution comes
  from the per-module re-runs of `CS-a`. The distribution of `CS-d` is
  recorded; a deviation elsewhere is investigated before proceeding.
  *Instrument criterion.*
- **`SU4`** `SU3`'s measurement satisfies all three checks of `CS-b` —
  the census run's tail line, a separate unpiped `--collect-only` run
  with its tail and **rc 2**-vs-**rc 0**, and the **path-anchored control
  `grep -cE "^env -- tests/test_worker\.py"` > 0** (`CS-b1`) — and all
  three are in the build report. A census reported without them is not
  evidence. *Instrument criterion.*
- **`SU5`** `git diff --name-only <base>..HEAD` names no path under
  `plugins/self-learn/ui/`. *Instrument criterion.*

### FX — fixture disambiguation

- **`FX1`** No module in `plugins/self-learn/cli/tests/` contains a
  **`def claude_shim` statement**: an `ast.parse` of every `tests/*.py`
  finds no `FunctionDef`/`AsyncFunctionDef` named `claude_shim`. Stated
  as a *definition* check, not a "no fixture-marked attribute anywhere"
  check, because after `Compat-1` `test_repair.claude_shim` **is** a
  fixture-marked attribute (`B-5` row one) — that binding is legitimate
  and is policed by `FX4` instead.

  **Guarded by a positive control first**: assert both names in
  `FIXTURE_NAMES` resolve to fixture-marked callables on their defining
  modules *before* asserting the absence, because "no function named X"
  is vacuously true of a module list that came back empty.
- **`FX2`** The two fixtures' returned dicts have exactly the base key
  sets — `{"log", "prompt", "dir", "argv", "call_prompt", "count"}` for
  `claude_cli_shim_worker`, `{"log", "out", "cwd"}` for
  `claude_cli_shim_analyst` — and `dir`/`log`/`out`/`cwd` are `Path`s
  while `argv`/`call_prompt`/`count` are callables. Driven by **requesting
  each fixture** (hence two tests, §3.9 rows 2–3), not by reading source.
  Mutation `M23`.
- **`FX3`** No test's fixture closure contains two of
  `FIXTURE_NAMES ∪ {LEGACY_NAME}`. Read from the **raw per-test blocks**
  of the `--fixtures-per-test` output — a block listing two of the three
  names is the failure — **not** from `CS-a`'s aggregate counts, which
  cannot attribute two lines to one test. *Instrument criterion,
  discharged alongside `SU3`.*
- **`FX4`** `Compat-1`'s alias appears **exactly once** in
  `plugins/self-learn/cli/tests/`: an AST scan of all `tests/*.py` finds
  exactly one module-level `Assign` binding the name `claude_shim` to
  the name `claude_cli_shim_worker`, and it is in `test_repair.py`.
  Exactly one module — `test_invocation.py` — imports the name.
- **`FX5`** The two node IDs of `RN-c` are present in the collected set,
  spelled exactly as at base. Asserted by name (the `HM-a` cost: it lives
  in `test_u_fake.py`, not in the module it constrains). Mutation `M2`.

### SH — `shims.py`

- **`SH1`** For the **path literals named in the criterion's own body**
  (`SH-a1`: the emitted bytes are a function of those paths),
  `write_worker_claude_shim` and `write_analyst_claude_shim` each produce
  a file whose `sha256` equals a hex literal, and the file is executable.
  The expectation is generated by the recipe of §9's provenance row —
  driving the **base** fixture function, never the new builder. **No
  other criterion catches a one-byte script change** — `SH-a`, mutation
  `M8`.
- **`SH2`** Two of its three legs are checked on the **AST**, not by a
  source-text search (code-gate fold, `MAJOR 1`): `claude_cli_shim_worker`'s
  body must contain `Assign` nodes whose **value expressions** carry the
  literals `"claude-invocation-count"` and `"claude-calls"` — i.e. the
  CODE computes those paths, not merely a docstring that mentions them
  in prose (the fixture's own docstring names both words, which is what
  made a raw `inspect.getsource(...) ; "..." in src` search vacuous
  against `M6`: moving the computing `Assign` to `shims.py` left the
  docstring behind and 20/20 affected tests stayed green, gate-measured).
  The third leg — `'monkeypatch.setenv("PATH", _path_without_real_notify_helper(shims))'`
  present in `inspect.getsource(claude_cli_shim_worker)` — is unaffected
  and stays a source-text check (`B-2`, `B-3`). Mutations `M6`, `M7`.
  **The shipped `test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`
  has the identical text-search defect on its own two `B-2` legs and is
  NOT fixed by this fold** — it is `GUARDED` and frozen beyond the
  mechanical rename, so this unit cannot reach it; recorded as a residual
  (§8.2, code-gate fold).
- **`SH3`** None of `shims.py`, `backends.py`, `test_u_fake.py` contains
  a line matching `\[\s*"claude"\s*\]` (`B-1`, `HM-c`). Mutation `M16`.
- **`SH4`** `shims.py`'s public surface is honest, four legs: `__all__`
  is non-empty; every name in it has at least one call site in
  `plugins/self-learn/cli/tests/` (`SH-c`); **no name in it is
  `@pytest.fixture`-marked** (`D-8`); and the module's AST contains no
  `Import`/`ImportFrom` naming `self_learn` or any `test_*` module
  (`SH-b`). Mutation `M26`.

### BK — `backends.py`

- **`BK1`** `install_fake` patches `self_learn.invocation.registry`'s
  `backend_for` attribute — asserted **behaviorally**, not by reading
  source: with the fake installed, a `text_session(spec)` call with no
  `backend=` keyword returns the fake's scripted `Outcome` and the fake
  records the call. **The test sanitizes `PATH` first** (`B-7a`), so a
  build that patched the package-level re-export falls through to a
  `CliBackend` that can find no executable — deterministic, and incapable
  of spawning a real model on any host. Mutation `M9`.
- **`BK2`** `assert_fake_was_used` raises when handed a `FakeBackend`
  that recorded nothing, with a message naming the missed-patch
  fail-open, and does not raise when handed one that recorded a call.
  Invoked **directly** — `BK-b` makes it public precisely so this
  criterion can observe the assertion firing rather than merely not
  firing. A second leg asserts `install_fake` registered it, by checking
  that `request.addfinalizer` was called (spy on the request object).
  Mutation `M10`.
- **`BK3`** As `SH4`'s first two legs, for `backends.py`: `__all__`
  non-empty, every name consumed in-suite. The import legs do not apply
  (`BK-d`). Mutation `M19`.

### T1 — the three conversions

- **`T1a`** Each of the three `Move-1` tests, read from source, still
  contains **its own leg's** prompt assertions of `MV-c1` verbatim — the
  criterion's body carries the eight strings as literals, GROUPED BY LEG
  and checked against THAT test's own source span, never the union of
  all three (code-gate fold, `NOTE 1`): a needle satisfied by the wrong
  leg, or a mangled positive whose bare string constant survives even
  though the `assert ... in prompt` wrapping it broke, is not evidence
  that the leg it was pinning still holds. Leg 3's positive needle is
  therefore the CONTIGUOUS text through `in prompt`, not the bare string
  alone. **The "and all three pass" leg is carried by the suite (`SU1`),
  not by this test**, which reads source and never executes them — the
  same split `HY1` makes between its diff leg and its pass leg. Mutation
  `M11`.
- **`T1b`** Each of the three contains `assert len(fake.argvs) == 1`, so
  a fall-through to a real `CliBackend` cannot satisfy them. Mutation
  `M33` — **not `M9`**, which changes `backends.py` and leaves this
  source read green (`MAJOR H`).
- **`T1c`** Each of the three still asserts `fake.argvs[0][0] == "claude"`
  and `fake.argvs[0][1] == "-p"` and reads the prompt from
  `fake.argvs[0][2]` — the analyst's prompt-rides-argv property,
  preserved (`MV-c`). Mutation `M29`.

### DS — diff scope

- **`DS1`** `Freeze-1` holds for all five `GUARDED` modules, checked TWO
  independent ways (code-gate-adjudicated as CONFORMANT AND STRONGER
  than this spec's original single-comparison design): a LIVE
  `git show <base>:...` extraction compared against a LIVE extraction of
  the working tree, both through the same extractor (this is what an
  asymmetric, non-inverse-renamed filter, `M32`, actually breaks — it
  gives different counts on base vs head only when BOTH are freshly
  extracted); and separately, both sides checked against a per-module
  hex literal/count PINNED at build time from `git show <base>:...`
  (this is what catches an extractor that returns nothing, `M17`, which
  the live-only comparison alone cannot: it would agree with itself).
  Either leg alone misses one of `M17`/`M32`; together they also catch
  `M18` alone, which `FZ-c1` did not originally claim. In both, the
  exclusion filter is applied to the **inverse-renamed** name on both
  sides (`FZ-b1`), the extracted-function count for each **equals** its
  base count (`FZ-c`, asserted **first**), and the decorator-inclusive,
  inverse-renamed concatenated `sha256` equals the base literal. The
  failure message names the module and the command to run:
  `git diff <base>..HEAD -- <path>`.
  **A third, separate leg (code-gate fold, `NOTE 3`)** checks
  `notify_shim` specifically: `REWRITTEN` excludes it from the two legs
  above entirely, licensing only its parameter rename — but that left
  its body, beyond the rename, completely unpoliced. The same
  inverse-rename technique, narrowed to just this one function, closes
  it: its head source, inverse-renamed, must equal its base source
  byte-for-byte. Mutation `M34`.
  Mutations `M3`, `M4`, `M5`, `M17`, `M21`, `M32`, `M34`.
  **This design shells out to `git show <base>:...` at TEST RUNTIME
  (code-gate fold, `NOTE 5`, accepted as a residual, no redesign)**: it
  fails loud outside a git checkout with history back to `<base>`, and
  `SQ-3`'s "re-measure at the rebase base" instruction now means editing
  the `BASE_REF` code constant, not just re-measuring numbers into a
  document.
- **`DS2`** The `REWRITTEN` set is a literal in `DS1`'s module,
  contains exactly the **seven functions** named in §3.1's table, and
  every entry names a function that **exists** in its module — so neither
  a stale entry nor an added one can silently widen the exemption.
  Mutation `M22`.
- **`DS3`** `FZ-d`'s two provenance obligations are discharged: the build
  report records the `git show <base>:…`-driven generation of `DS1`'s
  and `SH1`'s expectations, and the
  `git diff <base>..HEAD -- plugins/self-learn/cli/tests/` whose every
  hunk is a rename, an extraction, `Compat-1`'s line, a `REWRITTEN`
  function, or an `ADDED` file. `FZ-c1` states why `DS1` cannot stand
  without this. *Instrument criterion.* Mutation `M18`.

### HY — hygiene

- **`HY1`** `test_invocation.py` is byte-identical to base:
  `git diff --quiet <base>..HEAD -- plugins/self-learn/cli/tests/test_invocation.py`
  exits 0, **and** its 65 tests pass. Both, because the diff alone does
  not prove the module still collects after the rename. *Instrument
  criterion for the diff leg; the pass leg is `SU1`.* Mutation `M25`.
- **`HY2`** `git diff --name-only <base>..HEAD` names no path under
  `plugins/self-learn/cli/src/` and does not name
  `plugins/self-learn/cli/pyproject.toml`. *Instrument criterion.*
  Mutations `M30`, `M31`.
- **`HY3`** `conftest.py` and `support.py` are byte-identical to base
  (`git diff --quiet`, exit 0 for each). *Instrument criterion.*
  Mutation `M24`.
- **`HY4`** `pyright --pythonpath .venv/bin/python src`, run from
  `plugins/self-learn/cli/` (the project's own command,
  `CONTRIBUTING.md`), reports a **delta of 0** errors against the rebase
  base. Both numbers go in the report; a fixed target is refused, because
  U-seam's `HY5` fold measured the shipped figure drifting between two
  units. *Instrument criterion.*

  **This criterion is expected to be trivially satisfied, and that is its
  job.** A tests-only unit touches nothing pyright reads, so a non-zero
  delta means `HY2` was violated and the `git diff --name-only` that was
  supposed to catch it did not. It is a cross-check on another
  criterion's instrument, not an independent guard — split out of r1's
  `HY3` so that one command cannot discharge two different obligations.
  Mutation `M31`.

### 5.1 Coverage, and the one thing a mutation cannot reach

**All 27 criteria have at least one reddening row in §6.** r1 left eight
uncovered (`SU2`, `SU5`, `FX2`, `SH4`, `DS2`, `HY1`, `HY2`, `HY3`) and
the gate was right that this was a hole, not a style choice; `M22`–`M31`
close it. The mapping for the eight, plus the three found while checking
this section's own arithmetic:

| Criterion | Row |
|---|---|
| `SU2` | `M24` (nine paths, not eight), `M28` |
| `SU5` | `M27` |
| `FX2` | `M23` |
| `SH4` | `M26` |
| `DS2` | `M22` |
| `HY1` | `M25` |
| `HY2` | `M30`, `M31` |
| `HY3` | `M24` |
| `HY4` | `M31` |
| `T1c` | `M29` |
| `T1b` | `M33` (r2 credited `M9`, which cannot reach it — `MAJOR H`) |
| `DS1` (correct-build failure) | `M32` |

**`CV-a` — what no mutation can reach: report omission.** **Eleven**
criteria are *instrument* criteria whose subject is **evidence recorded
in the build report** rather than state in the tree: **`SU1`, `SU2`,
`SU3`, `SU4`, `SU5`, `FX3`, `DS3`, `HY1`, `HY2`, `HY3`, `HY4`** — every
criterion in §5 marked *instrument*, which is 11 of 27, not the four r2
counted.

Their mechanical failure modes are mutation-tested — `M20` for `SU4`'s
non-conforming census, `M18` for `DS3`'s provenance, `M30`/`M31` for
`HY2`/`HY4`, `M24` for `SU2`/`HY3`, `M25` for `HY1`, `M27` for `SU5`,
`M2`/`M4`/`M5`/`M28` for `SU1`, `M15` for `SU3`/`FX3` — but every one of
them is discharged by **a command's output pasted into a document**, and
a builder who simply **leaves the section out** produces a green suite
and an unfalsifiable claim. There is nothing to mutate: only something to
omit.

**Forty-one percent of this unit's criteria are enforced by reading the
build report, not by running the suite.** That is a property of a
tests-only unit whose subject is *what the diff touched* — no amount of
test-writing can make a diff-scope criterion self-enforcing — but it has
to be said out loud, because a gate that only re-runs the suite verifies
16 criteria and believes it verified 27. `R-6` gives it an owner.

---

## 6. Mutation plan

**33 mutations at r4; 34 after the code-gate fold (§15) added `M34`.**
Every mutation is applied to the **built** tree, the
suite is run, and the named criteria must **redden**. A mutation that
leaves the suite green is a hole in §5 and must be closed before the
gate, not explained away. The **negative-control** column is not
decoration: where it says a criterion stays GREEN, that is the measured
reason the reddening criterion exists.

| # | Mutation | Must redden | Negative control — what stays GREEN, and why it matters |
|---|---|---|---|
| `M1` | Rename the analyst fixture only; leave `test_worker.py`'s as `claude_shim` | `FX1` | `SU3`'s **sum** stays green. The census counts tests, not names; only a name-level assertion sees a half-done disambiguation |
| `M2` | Blunt `sed s/claude_shim/claude_cli_shim_worker/g` over `test_worker.py`, renaming the two `test_claude_shim_*` tests (`RN-c`) | `FX5`, `SU1`'s `base ∖ head` leg | `SU1`'s **count** delta stays green (+17 either way) and **`DS1` stays green** — the inverse rename reconstructs the base name, so the sha is unchanged. This row is the entire reason `SU1` asserts a set relation and not a number |
| `M3` | Edit one assertion inside a T3 test — e.g. `assert cli.main(["worker", "run"]) == 0` → `!= 1` in `test_repair.py::test_h1_the_exit_code_contract` | `DS1` | `SU1`, `SU3`, `SU4`, `FX*` all stay green — counts, sets and censuses are structurally blind to a body edit. This row is the entire reason `DS1` exists |
| `M4` | Delete one T3 test | `SU1` (`base ∖ head` non-empty), `DS1` (`FZ-c` count) | — |
| `M5` | Add one new test to a T3 module | `SU1` (`head ∖ base` no longer matches §3.9's enumeration), `DS1` (`FZ-c` count) | `SU2` stays green — the file was already in the permitted eight |
| `M6` | Move `counter = tmp_path / "claude-invocation-count"` and `calls_dir = tmp_path / "claude-calls"` into `shims.py` | `SH2` (its AST-based legs; code-gate `MAJOR 1` fold) | `SH1` stays green — the **emitted bytes** are unchanged; only where the paths are computed moved. **The shipped `test_attrib.py::test_hy1_...` does NOT redden** — its own `B-2` legs are the same source-text search over a docstring that mentions both words, and it is `GUARDED`/frozen, out of this unit's reach (gate-measured: 20/20 affected tests stayed green under this mutation before the `SH2` fold; the original text claiming `test_hy1` reddens was wrong) |
| `M7` | Move `monkeypatch.setenv("PATH", _path_without_real_notify_helper(shims))` into `shims.py` | `SH2`, and shipped `test_repair.py::test_f6_no_test_invokes_a_real_claude` (`B-3`) | `SH1` stays green, same reason as `M6` |
| `M8` | One byte of the emitted worker shim script: the argv log's `>>` → `>` (the exact U-repair F5 regression the shim's docstring records) | `SH1` | **Nothing else reddens.** Measured: the legacy `log` path has exactly **two** readers in the whole suite — `test_worker.py`'s single-invocation argv pin and its `assert not claude_shim["log"].exists()` — and neither drives two invocations, while every multi-invocation test reads the per-call `argv.$N` files. Truncate-vs-append is invisible to the suite. `SH1` is this unit's `HY3`-analogue: the guard that exists because no functional criterion can see the change |
| `M9` | `install_fake` patches `self_learn.invocation.backend_for` instead of `…invocation.registry.backend_for` | `BK1`, **and the three `Move-1` tests themselves** | Measured (`B-7`): the fake records **0** calls. **The reddening mechanism inside `Move-1` is NOT `not-found`** (`B-7a`): `_shim_env`'s PATH shim answers with rc 0 and empty stdout, so `outcome.failure is None` and `analyst._parse_yaml_map("")` is what raises. **`T1a`, `T1b` and `T1c` all stay GREEN** — they are *source reads* of `test_composer.py` (§3.9 rows 13–15), and this mutation changes `backends.py`, not the text they read. `M33` is `T1b`'s actual guard |
| `M10` | `install_fake` drops the `request.addfinalizer(...)` registration | `BK2`'s second leg | **Every other criterion stays green.** The control is invisible to the suite until the day a consumer stops reaching the fake, which is the day it is needed |
| `M11` | The three `Move-1` tests keep their positive prompt assertions but drop the three `not in` negative controls of `MV-c1` | `T1a` | `T1b` and `T1c` stay green — the fake was still reached and argv is still right. And **legs 2 and 3 still pass each other's positive assertions**, which is exactly the collapse the negative controls exist to prevent |
| `M12` | One of the three `Move-1` tests deleted rather than converted | `T1a`, `T1b`, `T1c`, `DS2`, `SU1` (`base ∖ head`) (code-gate `NOTE 2` correction, gate-measured) | **`DS1`'s `test_composer.py` count stays 42/42** — the deleted function is `REWRITTEN`-excluded on BOTH sides (it was never counted in the first place, so its absence changes nothing `DS1` looks at). The original row's claim that `DS1` reddens here was wrong; the real killers are the source-read tests that `getattr` the now-missing function (`T1a`/`T1b`/`T1c`, `AttributeError`), `DS2`'s positive-control leg (the `REWRITTEN` entry no longer names a function that exists), and `SU1` (the deleted node ID was present at base) |
| `M13` | `Compat-1`'s alias line removed from `test_repair.py` | `SU1` — `test_invocation.py` raises a **collection error**, so its 65 node IDs vanish from `head`; `FX4` | `HY1`'s diff leg stays green — `test_invocation.py` itself was never edited, which is precisely why the breakage lands somewhere else |
| `M14` | A second alias added in `test_worker.py` as well | `FX4` | Everything else stays green; two legacy bindings behave identically until one is deleted |
| `M15` | One `test_repair.py` test made to request **both** `claude_shim` and `claude_cli_shim_worker` | `SU3` (sum +1 over the permitted +2), `FX3` | The test itself still **passes** — measured (`B-5` row three): it simply gets two shim dirs, and the second shadows nothing it reads. Only the census sees it |
| `M16` | Add a bare `["claude"]` argv literal to `shims.py` | `SH3`, and shipped `test_attrib.py::test_hy1_…` (`B-1`) | — |
| `M17` | `DS1`'s extractor made to return `[]` for every module | `DS1`'s `FZ-c` count leg | Without that leg every module's sha becomes `sha256(b"")`, all five comparisons pass, and **`DS1` reports green over an arbitrarily rewritten suite.** But see `M18`: the count leg alone is not sufficient (`FZ-c1`) |
| `M18` | `DS1`'s and `SH1`'s expectations regenerated from the **working tree** after the edits instead of `git show <base>:…` | `DS3` | `DS1` and `SH1` themselves go green — that is the failure mode. Applied **together with `M17`**, `FZ-c`'s count leg also goes green (0 == 0), which is the concrete demonstration of `FZ-c1`: only provenance catches a simultaneous break |
| `M19` | Add a public helper to `backends.py` with no call site | `BK3` | — |
| `M20` | Run the census from the repository root instead of `plugins/self-learn/cli` | `SU4` | `SU3` would report `0` for every name and a naive reader would record "all three names at zero" as a pass. **Measured:** the run produced `0` for every name, and the census mode emits **no collected-count line**, so r1's rc/count checks would not have caught it either |
| `M21` | Add `@pytest.mark.skip` to one T3 test | `DS1` in its **decorator-inclusive** form (`FZ-b` step 2) | Records that `DS1`'s naive `ast.get_source_segment` form stays **GREEN** — measured (`B-9`): the segment excludes decorators. `SU1` also stays green (the node is still collected), `SU3` stays green, and the suite stays green while the armor is silently disabled. Mirrors `M2`: same defect class, a disguise the obvious guard cannot see |
| `M22` | Widen `REWRITTEN` by one entry — name a T3 test that was not in fact rewritten | `DS2` | **`DS1` goes GREEN for that function**, which is §6's own declared failure mode ("a gate that finds `DS1` weakened should treat the unit as failed") made mechanical. Without `DS2`, widening the exemption is a silent, one-line way to exempt anything |
| `M23` | Drop the `"count"` key from `claude_cli_shim_worker`'s returned dict | `FX2`, and every shipped `test_repair.py` test calling `claude_shim["count"]()` | `DS1` stays green — the fixture is in `REWRITTEN`, so its body is not sha-pinned; the **contract** of what it returns is `FX2`'s job alone |
| `M24` | Edit `conftest.py` (add one env var to `_worker_test_defaults`) | `SU2` (nine paths, not eight), `HY3` | The suite stays green — the conftest edit is behaviorally harmless, which is why a file-set criterion rather than a behavioral one is what guards the surface |
| `M25` | Apply the mechanical rename **inside** `test_invocation.py` — the option `V-1` **rejected**, done here without waiting for `U-cleanup` | `HY1`'s diff leg, `SU2` (nine paths, `test_invocation.py` present), **`FX4`'s importer leg** (after the in-file rename **zero** modules import `claude_shim`; `FX4` requires exactly one) | **Nothing behavioral reddens** — every test still passes; it is a *correct* rename. The cost is **three criteria, one of them a real test**, not one. This row is **`R-1`'s go/no-go evidence for `U-cleanup`**, and r2 understated it: a cleanup unit reading "the entire suite stays green" would have budgeted for a diff criterion and met `FX4` |
| `M26` | Add an uncalled public helper to `shims.py`; separately, mark one `shims.py` export with `@pytest.fixture` | `SH4` (the consumer leg, then the not-a-fixture leg) | `SH1` stays green — the two existing builders still emit the right bytes. A speculative helper is invisible to every behavioral criterion |
| `M27` | Whitespace-only edit to any file under `plugins/self-learn/ui/` | `SU5` | The whole suite stays green, both suites. A path-scope criterion is the only thing that can see an out-of-scope edit that changes no behavior |
| `M28` | Home one criterion test in a `GUARDED` module (`test_worker.py`) instead of `test_u_fake.py` — **the r1 BLOCKER, as a mutation** | `SU1` (`head ∖ base` contains an ID not under `tests/test_u_fake.py::`), `DS1` (`FZ-c` count for that module), `SU2` if `test_u_fake.py` then does not exist at all | `CO-a`'s **total** stays green (+17 either way) and `SU3` stays green unless the test requests a shim fixture. The blast radius is exactly what r1 missed, and only the *enumerated* `head ∖ base` leg sees it |
| `M29` | The three `Move-1` tests drop `fake.argvs[0][0] == "claude"` / `[1] == "-p"` and read the prompt from `fake.specs[0].prompt` instead of `fake.argvs[0][2]` | `T1c` | `T1a` and `T1b` stay green — all eight prompt assertions still hold and the fake was still reached. `T1c` is the **only** thing pinning the analyst's prompt-rides-**argv** property after the swap, and `spec.prompt` is a plausible-looking substitute that silently stops testing it |
| `M30` | Comment-only edit to `src/self_learn/worker.py` | `HY2` | **The entire suite stays green, and `HY4`'s pyright delta stays 0** — a comment introduces no type error. This is the row that shows `HY2` is a path-scope guard `HY4` cannot stand in for, and why r1 folding them into one criterion was wrong |
| `M31` | Edit `src/self_learn/invocation/registry.py` to introduce one pyright error (e.g. return a `str` where `Backend` is annotated) | `HY2`, `HY4` | The **suite** may stay green — pyright errors are not runtime errors. `HY4` earns its separate ID here: it is the leg that observes a `src/` change `HY2` would also catch, confirming the cross-check works rather than substituting for it |
| `M32` | `DS1`'s exclusion filter applied to the **raw** `node.name` instead of the inverse-renamed name (`FZ-b1`) — r2's literal wording | `DS1` — **on a build that is entirely correct** | Measured: base extracts 61 functions from `test_worker.py` and 41 from `test_route_cli.py`; head extracts 60 and 40. Both `FZ-c`'s equality and the sha fail with **nothing wrong**. The row exists because the builder's two intuitive escapes are `M22` (widen `REWRITTEN`) and `M18` (regenerate from the working tree) — a guard that fails on a correct build is not merely noisy, it *drives* the two mutations this spec most fears |
| `M33` | The three `Move-1` tests drop `assert len(fake.argvs) == 1` | `T1b` | `T1a` and `T1c` stay green — all eight prompt assertions and both argv-shape assertions are untouched. Added in r3 because `T1b`'s only r2 row was `M9`, which mutates `backends.py` while `T1b` reads `test_composer.py`'s **source** — so `T1b` was uncovered and coverage was 26/27, not 27/27 |
| `M34` | A behavioral line added inside `notify_shim`'s body (code-gate `NOTE 3`; the gate's `P3`) — e.g. an extra `Path` write unrelated to its declared job | `DS1`'s new `notify_shim` leg | Every other criterion stays green: `notify_shim` is `REWRITTEN`-excluded from `DS1`'s two module-wide legs, `SU1`/`SU2`/`SU3`/`FX*` are structurally blind to a body edit inside an already-collected, already-censused fixture, and no other criterion reads this function's source. This row is the entire reason the third leg exists — before it, `notify_shim`'s body beyond its licensed parameter rename was completely unpoliced |

**`M3` is the mutation this document is most afraid of.** It is the one a
well-meaning builder performs voluntarily, calling it "while I was in
there." It leaves every count, every set and every census green, and it
is the only thing T3 exists to prevent. `DS1` is the guard.

**`M17`, `M18`, `M21` and `M22` are `M3`'s four disguises**, and each was
green under some r1 form of the guard. `M17` makes `DS1` vacuous by
feeding it nothing; `M18` by feeding it the wrong baseline; `M21` by
hiding the change where the extractor does not look; `M22` by declaring
the function out of scope. `FZ-b` step 2, `FZ-c`, `FZ-c1`, `FZ-d` and
`DS2` are one answer each — not a stronger assertion of the same
comparison.

---

## 7. Builder decisions, made here rather than left open

- **`D-1`** `Compat-1` lives in `test_repair.py`, not `test_worker.py`
  (`CP-a`). It is one line and it is labelled debt.
- **`D-2`** The three `Move-1` tests stay in `test_composer.py`; "move"
  names the backend, not the file (`MV-b`).
- **`D-3`** The extraction boundary of §3.3.1 is drawn by two shipped
  `inspect.getsource` guards (`B-2`, `B-3`), not by taste. Only the
  script blob and its `chmod` move; §3.3.2 mirrors it, and neither
  builder calls `mkdir` (`SH-d`).
- **`D-4`** `install_fake(request, monkeypatch, steps)` patches
  `registry.backend_for` and registers its positive control through
  `request`, because `monkeypatch` has no `addfinalizer` (`B-5a`,
  measured). `assert_fake_was_used` is public so `BK2` can observe it
  fire.
- **`D-5`** `DS1` uses per-module concatenated shas, not a per-function
  map (`FZ-e`), and extracts **including decorators** (`FZ-b`, `B-9`).
- **`D-6`** `SU1` asserts a node-ID **set relation** with an enumerated
  `head ∖ base`, not a count (`CO-b`, `RN-c`, `BL-1`).
- **`D-7`** `shims.py` is a new module rather than an addition to
  `support.py`: `support.py` is imported by **49** test modules, so every
  edit to it has suite-wide blast radius, and this unit's entire claim is
  that its blast radius is eight files. See `R-3`.
- **`D-8`** `shims.py` exports **plain functions, not fixtures** (§3.3) —
  a fixture cannot be called from inside the `params=["cli","sdk"]`
  fixture body that is T2's whole shape. Asserted as a leg of `SH4`.
- **`D-9`** The inert `notify-send` stub stays in the worker fixture: it
  is not a `claude` shim and T2 has no use for it (§3.3.1).
- **`D-10`** Every number here is a measurement re-taken at the rebase
  base (`Meas-1`, `SQ-3`).
- **`D-11`** All 17 criterion tests live in `tests/test_u_fake.py`
  (`BL-1`), and the cost — losing "visible in the file it constrains" —
  is accepted and recorded (`HM-a`).

---

## 8. Out of scope, and residuals with owners

### 8.1 Deliberately not fixed

- **The third and fourth `claude` shim scripts.** `test_invocation.py`'s
  `_ANALYST_CLAUDE_SHIM` (frozen, `B-4`) and `test_composer.py`'s
  `_shim_env` inline shim are near-duplicates of what `shims.py` now
  owns. Neither is fixture-backed — `test_composer.py`'s census count is
  **0** — so neither is reachable by this unit's rename, and touching
  `_shim_env` would reach outside `REWRITTEN`.
- **`support.py::failing_git_shim` and `_GIT_SHIM`.** The same *kind* of
  thing as `shims.py`'s builders. Consolidating is a `support.py` edit;
  see `D-7`.
- **The analyst's `--allowedTools`-only containment, the miner's
  timeout-path sweep, and every other U-seam residual.** Not this unit's
  subject.

### 8.2 Residuals this unit accepts, with owners

| # | Residual | Owner |
|---|---|---|
| `R-1` | `Compat-1`'s alias in `test_repair.py`, and `test_invocation.py`'s **19** occurrences (measured) still spelling `claude_shim` | **`U-cleanup`** (`V-1`, RULED) — it deletes the CLI path and the shims together, so the rename lands with the deletion. **Start from `M25`:** it measures the rename as costing `HY1`'s diff leg + `SU2` + **`FX4`'s importer leg**, and nothing behavioral. `U-cleanup` deletes `FX4` with the alias, so of the three only the two instrument criteria remain to be re-baselined |
| `R-2` | Four `claude`-shim scripts in the suite where two would do (§8.1) | **`U-cleanup`** (`V-2`, RULED — a cleanup item, not a migration backlog); or the T2 unit, if it needs `_shim_env`'s variant parametrized |
| `R-3` | `shims.py` and `support.py::failing_git_shim` are two homes for one idea | Forward-work map — no unit currently owns it |
| `R-4` | Three shipped spec drafts (`u-analyst-…`, `u-repair-…`, `u-seam-…`) name `claude_shim` in prose and go stale on merge | A docs sweep, not this unit — the file surface here is `tests/` only, and rewriting a merged spec's prose to match a later rename is how a spec corpus stops being a record |
| `R-5` | `_capture_analyst_prompt` was patching the **transport**, one layer below the seam, so it never covered the seam's failure dispatch or log rendering (`MV-a`). After `Move-1` it covers the backend, but no `test_composer.py` test exercises an analyst **failure** path | **`U-cleanup`** (`V-2`, RULED — a cleanup item); or the Wave-2 T2 unit, which needs failure-leg parity across `["cli","sdk"]` anyway |
| `R-6` | **Eleven** criteria (`SU1`–`SU5`, `FX3`, `DS3`, `HY1`–`HY4`) are instrument criteria discharged by output pasted into the build report; none can be mutation-tested against omission (`CV-a`). A builder who omits a section produces a green suite and an unfalsifiable claim | The code gate, explicitly: **it must read the build report, not only re-run the suite** — re-running verifies 16 of 27 criteria. r2 undercounted this exposure as four criteria |
| `R-7` | (code-gate fold, `MAJOR 1`) The shipped `test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`'s two `B-2` legs are a raw source-text search over `inspect.getsource(...)`, and `claude_cli_shim_worker`'s own docstring mentions both guarded words in prose — so the same `M6` mutation that now reddens `SH2` (post-fold) still leaves this shipped test green. `GUARDED`, frozen beyond the mechanical rename; this unit cannot reach it | **`U-cleanup`** or a dedicated `test_attrib.py` fix — whichever unit next has license to edit that file's test bodies beyond a rename |
| `R-8` | (code-gate fold, `NOTE 5`) `DS1` shells out to `git show c2669a9:...` at TEST RUNTIME (not just at build time) for its live-vs-live leg and its `notify_shim` leg — it fails LOUD outside a git checkout with history back to the base commit, and a future rebase's "re-measure at the rebase base" (`SQ-3`) now means editing the `BASE_REF` code constant in `test_u_fake.py`, not merely re-measuring numbers into this document | Accepted, no redesign (code-gate adjudicated this design CONFORMANT AND STRONGER than the original single-comparison one). Whoever rebases this suite onto a later base owns updating `BASE_REF` |

---

## 9. What was executed, and against what oracle

All measurements at `c2669a9`, from `plugins/self-learn/cli`, CPython
3.13.11, **pytest 9.1.1**, `--color=no`:

| Measurement | Command | Result |
|---|---|---|
| Suite baseline (`B-8`) | `uv run pytest --color=no -q` | 1716 collected, **1711 passed, 5 skipped, 0 failed**, 175.19 s |
| Collected total | `uv run pytest --collect-only --color=no -q` | `1716 tests collected`, rc 0 |
| Census total | `uv run pytest --fixtures-per-test --color=no -q \| grep -cE "^claude_shim -- "` | **132** |
| Census per module | the same, with the module appended as a path argument | worker 32, repair 45, attrib 32, route_cli 16, invocation 7, composer **0** |
| Fixture definition sites | `grep -rn "def claude_shim"` over `tests/` | exactly two: `test_worker.py`, `test_route_cli.py` |
| Fixture-alias semantics (`B-5`) | three-module probe suite run against this repo's venv | alias registers a second fixture; the `B-4` import chain survives; **double request yields two instances**; `--fixtures-per-test` emits one line per requested name |
| `MonkeyPatch` surface (`B-5a`) | `dir(pytest.MonkeyPatch)` | `chdir, context, delattr, delenv, delitem, setattr, setenv, setitem, syspath_prepend, undo` — **no `addfinalizer`** |
| Injection point (`B-7`) | probe driving `text_session` under each patch target | `registry.backend_for` intercepts (1 recorded call); the package re-export **does not** (0 calls); `backend=` kwarg intercepts |
| Decorator blindness (`B-9`) | `ast.get_source_segment` on a decorated `FunctionDef` | `node.lineno` = the `def` line; the segment **starts at `def`** and omits both decorators |
| Census fail-open (`CS-b`, `M20`) | the census command from the repository **root** | every name `0`; census tail `39 errors in 1.56s` (vs `no tests ran in 0.65s` when correct); `--collect-only` tail `1791 tests collected, 39 errors` after `Interrupted` |
| `SH1` provenance recipe | `import test_worker; test_worker.claude_shim.__wrapped__(tmp_path, stub_monkeypatch, None)`, then sha the emitted `<tmp_path>/shims/claude` | works; `__wrapped__` present; params `('tmp_path', 'monkeypatch', 'env')`; a stub exposing `setenv` suffices; file executable; returned keys as `FX2` |
| `SH-a1` path dependence | the same recipe at three `tmp_path` lengths | 17 chars → **802** bytes; 21 → **826**; 44 → **964**. The sha is meaningless without the literal path. The delta gate reproduced the slope independently: **±6 bytes per character** |
| `FZ-b1` rename asymmetry (r3) | `ast` extraction over the base tree under both filters | naive `node.name ∈ REWRITTEN`: `test_worker.py` **61**, `test_route_cli.py` **41**; inverse-renamed filter: **60** and **40** — the head-side counts. Totals 62 / 41; `test_repair.py` 69, `test_attrib.py` 48, `test_composer.py` 46 (42 either way) |
| `CS-b1` path anchoring (r3) | `grep -oE '^env -- [^:]+' \| sort -u` over a non-conforming census run | every location printed as `env -- plugins/self-learn/cli/tests/…`, so `^env -- tests/test_worker\.py` matches **0** times — the control correctly flags the invocation, including this harness's own `--project` emulation |
| `CS-b2` non-reproduction (r3) | the gate's wrong-cwd scenario, attempted without `cd` | **not reproducible here**: 1791 blocks against 1791 collected, so the equality form of check 3 was **inert on both sides**. *Settled at r3:* the gate reproduced both scenarios and found the equality form inert in **both** (81==81 and 1791==1791), and the path-anchored control discriminating in **all three** (146 / 0 / 0) |
| `CS-b1` correct-number-wrong-run (r4) | `uv run --project <cli> pytest --fixtures-per-test` from the repository root, census grep for `claude_shim` | **132** — the exactly correct census — from a run collecting **1791** tests with **39 errors**. The worst shape in the guard: right answer, invalid run |

The probe suites were written under `/tmp`, run against the CLI package's
venv, and are **not** part of the deliverable; they appear here as the
provenance of `B-5`, `B-5a`, `B-7`, `B-9` and `SH-a1`, which are
otherwise recall about pytest and Python semantics rather than facts about
this repository.

---

## 10. Values questions — RULED

Both questions r1 routed to the user were **ruled at gate-dispatch time**.
They are recorded here as settled; neither changed the design, and this
section is the record of *why* the design is what it is rather than an
open fork.

### `V-1` — is `test_invocation.py` frozen? **RULED: Option A, as specified.**

The alternative considered and **rejected** was to apply the mechanical
rename inside `test_invocation.py` (one import line plus its **19**
`claude_shim` occurrences, measured) and ship no alias.

**Ruling and rationale, as given:**

- U-seam's `SU2` ("no existing test file may be edited") was a
  **build-scope criterion satisfied at that unit's merge** — not standing
  corpus law. It does not, by itself, freeze the file forever.
- The freeze **this wave** is **orchestrator disjointness-scoping**:
  three units (`U-sdk`, `U-bedrock`, `U-fake`) are in flight in parallel,
  and keeping each unit's edits disjoint is what makes the merge order of
  §4 trivial. `test_invocation.py` belongs to none of the three.
- The **labelled alias of §3.2.3 is therefore the sanctioned mechanism**,
  not a workaround. `CP-b` calling it "debt" stands; the debt is
  deliberate and scoped.
- The alias **and** the eventual rename of `test_invocation.py`'s 19
  occurrences are owned by **`U-cleanup`** — the final unit, which
  deletes the CLI path and the shims together, so the rename and the
  deletion land as one act rather than two.

**`M25` is the evidence `U-cleanup` will want**, and `R-1` points at it:
renaming inside `test_invocation.py` costs **three criteria — `HY1`'s
diff leg, `SU2`, and `FX4`'s importer leg** (after the in-file rename
**zero** modules import `claude_shim`, and `FX4` requires exactly one) —
and **nothing behavioral**: every test still passes.

r2 wrote "the entire suite stays green," which was **false and
load-bearing**: a cleanup unit reading it would have budgeted for one
instrument criterion and been met by a failing test. The corrected form
is the one to plan against — the rename is mechanically safe, and its
cost is three criteria, one of which `U-cleanup` must delete along with
the alias.

### `V-2` — is "exactly three" a demonstration or an instalment? **RULED: a demonstration.**

**Ruling and rationale, as given:** the ~129 remaining T3 tests are
**byte-identity regression armor by design**, and they stay that way
until `U-cleanup` deletes the CLI path. Migrating them to T1 wholesale
*before* that point would **spend the armor early** — it would remove the
independent check on the CLI path at precisely the moment the CLI path is
still shipping and still being refactored around.

Two consequences, both already reflected in this document:

- `Tier-a`'s "this unit ships no T2 test" and §3.5's "exactly three"
  stand as written. A builder who migrates a fourth test has left the
  mandate.
- `R-2` and `R-5` are **cleanup items owned by `U-cleanup`**, not the
  head of a migration backlog. The 175 s the suite spends on real
  processes is a known, accepted cost of holding the armor until it is no
  longer needed.

**Nothing in §§1–9 changes as a result of either ruling.** They confirm
the design r1 specified and r2 folded; they are recorded so the next
reader does not reopen them.

---

## 11. Revision history

- **r1** — first draft against `c2669a9`. Census, suite baseline,
  fixture-alias semantics and the `FakeBackend` injection point measured
  rather than inherited; U-seam's 125-at-`83d05c6` re-measured as **132
  at `c2669a9`**.
- **r2** — fold round. 1 BLOCKER / 6 MAJOR / 10 NOTE, all folded (§12).
  No r1 measurement was overturned. Criteria 26 → **27**; mutations
  20 → **31**; new files 2 → **3**; tests/ diff surface 7 → **8 paths**;
  collected delta 0 → **+17**; census delta 0 → **+2**. Four new
  measurements were taken to fold MAJOR A, MAJOR B, MAJOR D and NOTE 3
  (§9's last five rows).

  **`V-1` and `V-2` were ruled at gate-dispatch time and are recorded in
  §10 as settled** — Option A and "a demonstration" respectively, both
  confirming the specified design. `U-cleanup` is named as the owner of
  `R-1`, `R-2` and `R-5`. `test_invocation.py` carries **19 lines and 19
  occurrences** of `claude_shim`; **18** of them are non-import use sites
  and one is the `from test_repair import` line — r1's "~18" was counting
  use sites, and was right about those. **No criterion or mutation
  changed as a result of the rulings** — they are bounded edits to §2
  `B-4`'s pointer, §3.2.3's comment, `M25`'s framing, §8.2's owners, and
  §10 itself.
- **r3** — second fold round. Delta gate: **1 BLOCKER / 3 MAJOR / 4 NOTE**,
  all folded (§13). The gate verified all 17 r2 folds and **conceded
  MAJOR C** — its own AST recount found **three** `not-in` controls, so
  `MV-c1`'s enumeration stands verbatim — and reproduced `SH-a1`'s byte
  arithmetic exactly (±6 bytes per `tmp_path` character, so both the
  gate's 796 and this document's 826 are correct at their own paths).
  Most findings were **surfaced by the r2 folds themselves**: the
  equality fold exposed `FZ-b`'s rename asymmetry, and the new-module
  fold made `T1b`'s guard a source read that `M9` can no longer reach.
  Mutations 31 → **33**; criteria unchanged at **27**; coverage restored
  to 27/27 from an actual 26/27.
- **r4** — final fold, **CLEARED FOR BUILD**. Delta gate 2: **0 BLOCKER /
  1 MAJOR / 1 NOTE** (§14), both one-clause substitutions, closed under
  the verdict-repricing rule with no further spec gate. `SU4`'s text
  stopped mandating the superseded control; `FZ-b1`'s table headers
  corrected; `CS-b1` gained the measured *correct-number-wrong-run*
  paragraph. **Counts unchanged: 27 criteria, 33 mutations, 17 new tests,
  8 paths.** `CS-b2`'s open non-reproduction is now **settled** — the
  gate reproduced both scenarios and confirmed this document's decline of
  the equality control was right.

---

## 12. r2 — per-finding disposition

| Finding | Fold |
|---|---|
| **BLOCKER 1** — the spec never accounts for the tests it adds | §3.9 `Home-1`/`BL-1` (new); `ADDED` in §3.1; may-touch table now **8 paths** + `test_u_fake.py` row; `SU1` restated as `base ⊆ head` with `head ∖ base` = the **17 enumerated** IDs (`CO-b`); `CO-a` = delta **+17**; `SU2` seven → **eight**; `SU3`/`CS-c` = base **+ 2**, the two named in `HM-b`; `MV-b1` forbids any fixture import into `test_composer.py`; new mutation `M28` makes the BLOCKER itself a tested failure mode |
| **MAJOR A** — `MonkeyPatch` has no `addfinalizer` | `B-5a` (measured, 9.1.1); §3.4 surface is now `install_fake(request, monkeypatch, steps)` + public `assert_fake_was_used`; `BK-b` rewritten; `BK2` gained a second leg (registration spy); `D-4` updated; `M10` retargeted |
| **MAJOR B** — the fail-open guard did not discriminate | `CS-b` replaced with the **three** measured checks (tail line, separate unpiped `--collect-only`, a positive control); `SU4` restated; `M20`'s row records that r1's rc/count legs were dead because the census mode emits no collected-count line. **SUPERSEDED BY r3**: this fold's check 3 was the `monkeypatch` count, which r3's `MAJOR G` found **inert**. The current text of check 3 is the path-anchored control of `CS-b1` — read §13, not this row |
| **MAJOR C** — "three prompt assertions" was a miscount | `MV-c1` enumerates all **eight** from source, marking the **three** `not in` negative controls (the gate said four; the enumeration is the binding statement and is checkable); `T1a` carries the eight as literals; `M11` retargeted to dropping the negative controls, with the leg-2/leg-3 collapse as its rationale |
| **MAJOR D** — `DS1` was decorator-blind | `B-9` (measured); `FZ-b` step 2 extracts from `min(decorator linenos ∪ {node.lineno})`; new mutation `M21` (skip-mark a T3 test) with the naive form's greenness as its negative control; `D-5` updated |
| **MAJOR E** — `FX1` contradicted `Compat-1` | `FX1` restated as an AST scan for a `def claude_shim` **statement** across `tests/*.py`; the alias is the one permitted **binding**, policed by `FX4` (also restated as an AST `Assign` scan) |
| **MAJOR F** — 8 criteria had no reddening mutation | New rows `M22` (widen `REWRITTEN` → `DS2`), `M23` (drop `"count"` → `FX2`), `M24` (edit `conftest.py` → `SU2`+`HY3`), `M25` (rename inside `test_invocation.py` → `HY1`), `M26` (uncalled helper + fixture-marked export → `SH4`), `M27` (UI edit → `SU5`), `M28` (the BLOCKER itself → `SU1`/`DS1`/`SU2`); `FX5` was already covered by `M2`. **Checking §5.1's own arithmetic mechanically then found three MORE gaps the gate had not listed** — `T1c`, `HY2` and `HY4` — closed by `M29`, `M30`, `M31`. Coverage is now **27/27**, and §5.1 records the one failure mode no mutation can reach (report omission, `CV-a`), with `R-6` as its owner |
| **NOTE 1** — pytest version | §9 header and `B-5` now say **9.1.1**, measured |
| **NOTE 2** — `B-7` row 3 is PATH-dependent | New `B-7a`: `BK1`'s test sanitizes `PATH`; `M9`'s reddening mechanism corrected to `_parse_yaml_map("")` via `_shim_env`'s shim, not `not-found` |
| **NOTE 3** — `SH1` provenance recipe | §9 provenance row states the recipe (`claude_shim.__wrapped__(tmp_path, stub, None)`); new **`SH-a1`** records the measured path-length dependence (802/826/964 bytes) and makes the literal input paths part of `SH1` itself |
| **NOTE 4** — `DS2` "six entries" | `REWRITTEN` table now lists the three `Move-1` tests explicitly; `DS2` says **"exactly the seven functions named in §3.1"** |
| **NOTE 5** — `FZ-c` | strengthened from "at least" to **equality**; new **`FZ-c1`** states its parasitism on `DS3`, and `M18`'s row now specifies applying it together with `M17` as the demonstration |
| **NOTE 6** — analyst `mkdir` placement | new §3.3.2 "stays / moves" table mirroring §3.3.1, plus **`SH-d`**: neither builder calls `mkdir` |
| **NOTE 7** — `SH-b`, `SH-c`, `D-8` unasserted | folded into `SH4` as four named legs (`__all__` non-empty, consumers, not-a-fixture, no `self_learn`/`test_*` imports); `BK3` carries the two that apply to `backends.py` |
| **NOTE 8** — `M11`'s parenthetical | moved out of the "must redden" column; that column now names only criteria |
| **NOTE 9** — `FX3`'s instrument | restated to read the **raw per-test blocks** of `--fixtures-per-test`, not `CS-a`'s aggregate counts |
| **NOTE 10** — `HY3` did double duty | split into `HY3` (byte-identity of `conftest.py`/`support.py`) and **`HY4`** (pyright delta); criteria count 26 → 27 |
| **Loose parenthetical** — `test_attrib.py`'s import source | §1.1 corrected: `test_repair.py` and `test_attrib.py` each import from **`test_worker`**; only `test_invocation.py` imports from `test_repair` |

---

## 13. r3 — per-finding disposition

The delta gate verified all 17 r2 folds. It **conceded MAJOR C**: its own
AST recount found **three** `not-in` negative controls, so `MV-c1`'s
enumeration stands verbatim and no edit was needed. It also reproduced
`SH-a1` exactly — ±6 bytes per `tmp_path` character, confirming both its
796 and this document's 826 at their respective paths.

| Finding | Fold |
|---|---|
| **BLOCKER 2** — `DS1` fails on a **correct** build; the r2 equality fold exposed it | New **`FZ-b1`** (measured: `test_worker.py` 61→60, `test_route_cli.py` 41→40 at base) makes `FZ-b` step 1 test membership on the **inverse-renamed** name against the inverse-renamed `REWRITTEN`, symmetric on both sides. `DS2`'s seven-entry literal untouched (the inverse is computed). `DS1`'s body updated; new mutation **`M32`** (naive filter → `DS1` red on a correct build), whose row records why this could not be left to the builder: two of their three escapes are `M22` and `M18` |
| **MAJOR G** — `CS-b` check 3 was inert | Check 3 replaced with the **path-anchored** control `grep -cE "^env -- tests/test_worker\.py" > 0`, plus new **`CS-b1`** explaining that `--fixtures-per-test` prints locations **relative to rootdir**, so the control really asks *"was this the mandated invocation?"* — catching the `--project`+absolute-path form as well as a wrong cwd. Check 2's row now states **rc 2** explicitly as the guard's one discriminating exit status |
| **MAJOR G (non-reproduction)** — recorded, not smoothed | New **`CS-b2`**: the gate's wrong-cwd figure of 81 could **not** be reproduced here — this harness cannot `cd`, so its "correct" run is a third scenario with rootdir at the repo root. In that emulation the census emitted **1791 blocks against 1791 collected**, making the **equality form of check 3 inert on both sides**. The equality form is therefore **not** specified, and the gate is asked to re-measure it under a real `cd` before any revision reinstates it |
| **MAJOR H** — coverage was 26/27 | New mutation **`M33`** (the three `Move-1` tests drop `assert len(fake.argvs) == 1`) → `T1b`. `M9`'s must-redden column corrected to `BK1` + **the three `Move-1` tests themselves**; `T1a`/`T1b`/`T1c` moved to its negative-control cell with the reason: they are **source reads** of `test_composer.py` and `M9` mutates `backends.py`. `T1b`'s body now names `M33`, "**not `M9`**" |
| **MAJOR I** — `M25`'s "entire suite green" was false and load-bearing | Restated **identically in three places** (`M25`'s row, §10's `V-1` rationale, `R-1`): the rename costs `HY1`'s diff leg + `SU2` + **`FX4`'s importer leg** (zero importers where `FX4` requires one), and **nothing behavioral**. §10 says outright that r2's claim would have led `U-cleanup` to budget for one instrument criterion and be met by a failing test; `R-1` notes `U-cleanup` deletes `FX4` with the alias, leaving two |
| **NOTE (a)** — the `env` dependency | New **`RN-d`**: `claude_cli_shim_worker`'s parameters are `(tmp_path, monkeypatch, env)`, so `test_u_fake.py` writes `from test_worker import claude_cli_shim_worker, env`. Recorded in §3.2.1's consumer column and `HM-b` row 2, and tied to `MV-b1`'s reason for keeping the import out of `test_composer.py` |
| **NOTE (b)** — `T1a`'s pass leg | Split explicitly, in `HY1`'s idiom: the source-reading test carries the eight literals; **`SU1` carries "and all three pass"** |
| **NOTE (c)** — `CV-a` undercounted | Restated from four criteria to **eleven** (`SU1`–`SU5`, `FX3`, `DS3`, `HY1`–`HY4`), with the consequence stated plainly: **a gate that only re-runs the suite verifies 16 of 27**. `R-6` widened to match and to record that r2 undercounted |
| **NOTE (d)** — the 19/18 correction | §11 corrected: **19 lines AND 19 occurrences**; **18** are non-import use sites and one is the import line — so r1's "~18" was counting use sites and was right about those. r2's "counted lines" explanation was wrong |
| **NOTE (e)** — `M9`'s mechanism | No action; the gate confirmed the `_parse_yaml_map("")` mechanism as measured-correct |

---

## 14. r4 — per-finding disposition (final)

Delta gate 2: **0 BLOCKER / 1 MAJOR / 1 NOTE**, both one-clause
substitutions, folded under the **verdict-repricing rule** without a
further gate. What the gate verified rather than found: `FZ-b1`
independently reimplemented (`DS1` red under the naive filter, green on
all five modules under the specified one, exclusion counts reproducing
exactly); `M32` and `M33` spot-executed with clean negative controls;
`M9` confirmed leaving **all three** `T1` criteria green, validating r3's
corrected cell; the three-way `M25` restatement consistent; `CV-a`'s
eleven confirmed by an independent marker scan.

| Finding | Fold |
|---|---|
| **MAJOR (FOLD 1)** — `SU4`'s criterion text still mandated the **dead** `monkeypatch` control, and §0.1 makes the criterion beat `CS-b`/`CS-b1`'s corrected prose — reinstating `MAJOR G`'s fail-open **in the one binding place** | `SU4`'s third clause replaced with the path-anchored control `grep -cE "^env -- tests/test_worker\.py"` > 0 (`CS-b1`), and its second clause now names **rc 2 vs rc 0** explicitly. §12's `MAJOR B` row — which still described check 3 as the `monkeypatch` control and read as current — carries a **SUPERSEDED BY r3** marker pointing at §13 |
| **NOTE (FOLD 2)** — `FZ-b1`'s table columns said "excluded by" while the numbers are the counts **remaining after** exclusion, inviting a builder to compute the complement and conclude the table was wrong | Column headers now read **"extracted under"** |
| **Gate strengthening (FOLD 3)** — from the `CS-b2` settlement | New paragraph in `CS-b1`, **verified before writing**: `uv run --project <cli>` from the repository root reports the census as **132 — the exactly correct number — from a run collecting 1791 tests with 39 errors**. A wrong-cwd run reporting `0` announces itself; this one returns the right answer from the wrong run, so check 1's tail line is the only other objector and a reader who trusts the number never reads it. **That is why check 3 is not redundant with check 1**: a guard whose failure mode is *"correct output, invalid run"* needs a control that observes the **run**, not the output. Recorded in §9 as the `CS-b1` provenance row |

**The register this closes on.** Every one of the three rounds found the
defect in *the machinery the previous round had just added* — r1's
criterion tests broke r1's own criteria; r2's equality fold exposed r2's
rename asymmetry; r3's corrected prose left the superseded clause live in
the one place §0.1 says wins. The answer each time was not a stronger
assertion but a **structural** one: disjoint file sets (`BL-1`), symmetry
under the rename (`FZ-b1`), and a control that observes the run rather
than its output (`CS-b1`).

---

## 15. Code-gate fold (post-build delta)

The blind code gate, after independently re-executing the entire
33-mutation sweep (32 reddened as specified) and re-deriving all five
`DS1` pins and both `SH1` shas from `c2669a9` directly, returned
**NOT CLEAN: 0 BLOCKER / 1 MAJOR / 6 NOTE**. The gate additionally
**adjudicated the builder's `DS1` two-leg redesign as CONFORMANT AND
STRONGER** than this document's original single-comparison design:
`M32` breaks only the live-vs-live leg, `M17` only the pinned-literal
leg — either shape alone misses one of the two rows — and the two-leg
form also catches `M18` alone, which `FZ-c1` never claimed. All findings
below are folded; none reopened a settled measurement.

| Finding | Fold |
|---|---|
| **MAJOR 1** — `M6` does not redden: `SH2`'s two `B-2` legs asserted only that the literals `"claude-invocation-count"`/`"claude-calls"` appear SOMEWHERE in the fixture's source text, and the fixture's own DOCSTRING mentions both in prose — so after moving the computing `Assign`s to `shims.py`, 20/20 affected tests stayed green (gate-measured, code-only positive control) | `SH2` rewritten to check the **AST**: the fixture's body must contain `Assign` nodes whose VALUE expressions carry the two literals, not a raw text search. `M6` re-run: confirmed reddening on the corrected `SH2`, `SH1` stays green (negative control), restored zero-diff. **Residual, not fixed**: the shipped `test_attrib.py::test_hy1_...` has the identical defect on its own `B-2` legs and is `GUARDED`/frozen — out of this unit's reach (`R-7`) |
| **NOTE 1** — `T1a`'s union-check had two weaknesses: P5 (a mangled positive assertion's bare string constant still matched even with the wrapping `assert ... in prompt` broken) and P6 (a needle satisfied by the WRONG leg, since all three tests' source was concatenated before matching) | `PROMPT_ASSERTIONS` restructured into `PROMPT_ASSERTIONS_BY_LEG`, checked per-test rather than against the union; needle #7 (leg 3's positive) widened to the CONTIGUOUS text through `in prompt`, not the bare string alone. `M11` re-run: confirmed `T1a` still reddens, with a more precise (name, needle) failure |
| **NOTE 2** — the `M12` row's claim that `DS1`'s `test_composer.py` count leg reddens when a `Move-1` test is deleted was FALSE: the deleted function is `REWRITTEN`-excluded on both sides, so `DS1` never counted it in the first place and stays 42/42 (gate-measured) | `M12`'s row corrected: `DS1` moved to the negative-control cell with the reason stated; the real killers are `T1a`/`T1b`/`T1c` (`AttributeError` on the missing function), `DS2` (a `REWRITTEN` entry naming a function that no longer exists), and `SU1` (`base ∖ head`). Re-run and verified: `DS1` stayed green, all five named criteria reddened, `SU1`'s node-ID absence confirmed via `--collect-only` |
| **NOTE 3** — `notify_shim`'s `REWRITTEN` exemption licenses its parameter rename only, but `DS1`'s exclusion is wholesale — nothing polices the REST of its body (the gate's `P3`: a behavioral line added there is invisible to every shipped criterion) | New `DS1` Leg 3, same inverse-rename technique narrowed to just `notify_shim`: head source, inverse-renamed, must equal base source byte-for-byte. New mutation `M34` (a behavioral line added to `notify_shim`). Re-run: confirmed the new leg reddens on `M34`, restored zero-diff |
| **NOTE 4** — dead `import stat` in `test_route_cli.py`; its only consumer (the shim's `chmod`) moved to `shims.py` in §3.3.2's extraction | Removed. No functional effect — `DS1` still passes for `test_route_cli.py` (import statements are outside any function's extracted segment) |
| **NOTE 5** — `DS1`'s runtime `git show c2669a9:...` coupling: fails loud outside a git checkout with history to the base commit; a future rebase's "re-measure" now means editing a code constant | Accepted, documented as `R-8` (§8.2) and in `DS1`'s own criterion text (§5). No redesign — this is the same design property the gate just adjudicated as stronger than the alternative |
| **NOTE 6** — the gate lacked the build report when it first graded and compensated by re-deriving everything independently | No action; this report (and its delta) now accompanies the gate |

**Numbers after the fold.** Criteria: still **27** (no criterion added
or removed; `SH2`, `T1a`, `DS1` had their CHECKS strengthened, not their
IDs). Mutations: **33 → 34** (`M34`). New tests: **0** (the `notify_shim`
guard is a third leg of the existing `DS1` function, not a new
`test_u_fake.py::` node — `SU1`'s enumeration and `CO-a`'s `+17` are
therefore unchanged). Suite: unchanged shape, **1728 passed / 5 skipped
/ 1733 collected** (re-verified after the fold).
