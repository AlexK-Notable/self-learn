# Spec — U-seam: the invocation seam

**Superseded in part 2026-08-28 by `U-fw117`** (FW-117 CLOSED,
`14-forward-work-map.md`): this spec introduces the twin-witness
registry `SETTINGS_WITNESS` (including its `worker-repair` entry,
`worker.write_repair_settings_file`) and the CN6/CN7 legs built on it —
`worker.write_repair_settings_file` is now DELETED, along with
`SETTINGS_WITNESS`, `test_cn6_witnesses_a_and_b_agree_statically`, and
`test_cn7_repair_leg_over_both_enforce_values` (`test_invocation.py`).
It was a dead write nothing under the sdk backend ever read back
(`options_kwargs()` passes `settings=None` unconditionally). The rest of
this document is left as written below — it is the historical build
record for this unit's own contract at the time it shipped.

Status: **r3 — CLEARED FOR BUILD.** Two gate rounds, 31 findings, all
folded (§10 maps each to its change). r1 blind gate: **NOT SOUND — 2
BLOCKER / 6 MAJOR / 13 NOTE**; r2 delta: **NOT SOUND — 2 MAJOR / 8
NOTE**, with **both r1 BLOCKERs verified CLOSED** and `X-3`'s substitute
design adjudicated **sound, conditional on MAJOR A**. Every r2 finding
was a bounded substitution with its fix specified, so the round closed
under the ratified **verdict-repricing rule** and this is the last spec
round. **The code gate downstream verifies the r3 folds**, including the
four new mutation rows (`M31b`, `M36`, `M37`, and `M25`'s re-attribution)
— no further spec gate follows.

**The shape of both rounds is the same lesson.** r1's two BLOCKERs said
`CN6` could not fail; r2's MAJOR A said `CN9` — the guard written to fix
that — could not fail either, because it matched a syntactic form
(argument-is-a-Call) rather than a property (Witness A is not computed
from Witness B). Each round found the defect in *the machinery the
previous round had just added*. The answer has been the same each time
and it is not a stronger assertion: a **direction rule** (`C-c`, `CN9`
now one-hop taint), a **third independent witness** (`CN10`), and a
**sha** where a substring was (`HY3`). Unit `U-seam`, **Wave 0** of the
approved Agent-SDK migration:
the last unit before any SDK code exists in the CLI package, and the one
that decides what an SDK backend will later be asked to satisfy.

**Base commit:** `83d05c6` (master — the `U-attrib` merge, which rewrote
`worker.py`'s settings writers to grant the staging namespace). Every
symbol quoted in this document was read at that commit. `worker.py`,
`miner.py` and `analyst.py` are uncontended.

**The unit in one sentence.** Introduce one package behind which every
`claude` process spawn in the CLI lives, move today's three spawn sites
behind it **without changing a single observable byte**, and make the
containment each site relies on into *data* a future `SdkBackend` can
consume — while a second, independent witness of that same containment
(the shipped settings-file writers) keeps the data honest.

**This unit changes no behavior.** Not one log line, not one argv
element, not one permission rule, not one exit path. A builder who finds
themselves fixing a defect they discovered on the way has left this
unit's mandate and must stop and report. §7.3 names the two defects
found while writing this spec and deliberately **not** fixed here.

---

## Files this unit may touch

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/invocation/__init__.py` | **NEW.** Re-exports only; the package's public surface. |
| `plugins/self-learn/cli/src/self_learn/invocation/contract.py` | **NEW.** `Surface`, `Containment`, `SessionSpec`, `Outcome`, `Backend`, `BackendUnavailable`, the log-template table, the transport table, `containment_permissions`. |
| `plugins/self-learn/cli/src/self_learn/invocation/cli.py` | **NEW.** `CliBackend` — the only place `subprocess` is called for a model invocation. |
| `plugins/self-learn/cli/src/self_learn/invocation/fake.py` | **NEW.** `FakeBackend`. |
| `plugins/self-learn/cli/src/self_learn/invocation/registry.py` | **NEW.** `backend_for`, the precedence chain, the lazy `sdk` branch. |
| `plugins/self-learn/cli/src/self_learn/worker.py` | `_invoke_claude`'s **body only** (§3.9.1). Its signature gains keyword-only parameters with defaults; the positional prefix is frozen (`B-4`). Two call sites in `run()` gain keyword arguments. Nothing else. |
| `plugins/self-learn/cli/src/self_learn/miner.py` | `_invoke_reader`'s **transport block only** (§3.9.2). The function, its name, its signature, its spool `unlink`, and its stray sweep all survive verbatim. |
| `plugins/self-learn/cli/src/self_learn/analyst.py` | `analyze`'s **subprocess block only** (§3.9.3), from `argv = build_argv(...)` through `raise AnalystError(f"analyst exited ...")`. Everything above and below is untouched. |
| `plugins/self-learn/cli/src/self_learn/config.py` | One new reader, `invocation_backend` (§3.7.3). `one_motion_enabled` is untouched. |
| `plugins/self-learn/cli/pyproject.toml` | One new `[project.optional-dependencies]` table declaring the `sdk` extra (`R-b`, §3.7.4), so `BackendUnavailable`'s install command is true. |
| `plugins/self-learn/cli/tests/test_invocation.py` | **NEW.** Every criterion in §4 lands here. |
| `docs/specs/self-learn/03-decisions.md` | New rows `S-34`, `S-35` (§7.5), landing in the same commit as the build. |
| `docs/specs/self-learn/14-forward-work-map.md` | New rows for the residuals (§7.3 — `R-1`, `R-2`, and fold F7's `R-3`), landing in the same commit. |

**No existing test file may be edited.** That is not a preference, it is
criterion `SU2`, and it is the criterion the whole unit is built to
satisfy. `plugins/self-learn/ui/**` is likewise untouched — see §7.2.

---

## 0. Reading order and precedence

1. **§4 (acceptance criteria) and §5 (mutation plan) ARE the spec.**
   Everything else is rationale. Where prose and a criterion disagree,
   **the criterion wins** and the prose is the defect.
2. Every set, table and name is defined **once**, in §3, and referenced
   by name thereafter. A second definition anywhere is a bug in this
   document.
3. Code is located **by symbol plus a distinctive quoted source line**,
   never by bare line number. `U-attrib` shifted every line in
   `worker.py` and will not be the last unit to do so.
4. Read before this document: `worker.py`'s module docstring region
   around `ALLOWED_TOOLS`, `miner.py`'s `_invoke_reader`, and
   `analyst.py`'s module docstring. This spec quotes them but does not
   reproduce them.

---

## 1. Why this unit exists

### 1.1 What is true today

Three functions spawn `claude`. They are the only three (§7.1 lists the
look-alikes that are not):

| Surface | Symbol | Distinctive line |
|---|---|---|
| worker batch + worker repair | `worker._invoke_claude` | `proc = subprocess.run(` inside the function whose docstring begins *"One model invocation — round 1 (``label=""``) or the repair round"* |
| miner reader | `miner._invoke_reader` | `proc = subprocess.Popen(` inside the function whose docstring begins *"Run the contained reader (prompt on STDIN — audit B1)"* |
| teach-route analyst | `analyst.analyze` | `proc = subprocess.run(` immediately after `argv = build_argv(prompt, doctrine_text, model)` |

Each of the three re-derives, in its own idiom, the same four things: how
the process is started, what the model is allowed to touch, what happens
when it fails, and what the operator sees in a log. Nothing checks that
the three agree, because there is nothing they could be checked against.

### 1.2 What an SDK backend would need, and cannot get today

A `claude_agent_sdk` session takes its permission boundary as **Python
objects** — an allowed-tool list, a `can_use_tool` callback, a set of
roots. The CLI expresses the same boundary as **a JSON file on disk plus
argv flags**. The two are not the same shape, and today the JSON file is
the *only* statement of the boundary that exists. There is no object a
backend could be handed.

So the migration's first move is not "write an SDK backend." It is:
**make the containment into data, and prove the data is right by checking
it against the artifact that is already load-bearing.** That is the
twin-witness idea (§3.10), and it is the whole reason this unit ships
before any SDK code.

### 1.3 What this unit is not

It is not a refactor for tidiness. It is not a behavior fix (§7.3 names
two defects it deliberately preserves). It is not a place to unify the
three surfaces' log wording — §8 records that the three surfaces'
messages **differ**, that the difference is shipped, and that unifying
them is a separate unit with its own risk.

---

## 2. What binds this design from outside it

These are shipped, currently-green facts. Each one removes an option
this unit might otherwise have taken. A builder who trips one of them
has a red suite, not a discussion.

**`B-1` — the suite-wide claude-argv guard.** `test_attrib.py`'s
`test_hy1_no_test_in_the_suite_invokes_a_real_claude` reads
`sorted(tests_dir.glob("*.py"))` and asserts, for **every** line in
**every** test module matching the pattern `\[\s*"claude"\s*\]`:

```
assert "worker._invoke_claude(" in line, (fname, lineno, line)
```

The new `test_invocation.py` is inside that glob. **It may not contain a
bare `["claude"]` argv literal on any line that does not also call
`worker._invoke_claude(`.** Build argv literals for tests some other way
(a helper that assembles the list, a different argv[0] spelling, a
constant). This is criterion `HY1`.

**`B-2` — the same guard, file-local, in `test_repair.py`.**
`test_f6_no_test_invokes_a_real_claude` enforces `B-1` over its own
source *and* additionally asserts the literal string
`'monkeypatch.setattr(subprocess_mod, "run", fake_run)'` is present.
That string must keep meaning what it says: see `B-3`.

**`B-3` — `subprocess.run` must remain the worker surface's transport,
patchable on the `subprocess` module itself.**
`test_repair.py::test_e1_timeouts_read_not_hardcoded` does:

```
import subprocess as subprocess_mod
monkeypatch.setattr(worker, "subprocess", subprocess_mod)
monkeypatch.setattr(subprocess_mod, "run", fake_run)
worker._invoke_claude(["claude"], "prompt", worker.invoke_timeout_secs(), Path("/tmp"), label="")   # :1881
assert captured["timeout"] == 42
worker._invoke_claude(["claude"], "prompt", worker.repair_timeout_secs(), Path("/tmp"), label="repair ")  # :1883
assert captured["timeout"] == 99
```

**Both** call sites are quoted because they are not interchangeable: the
second passes `label="repair "`, so the constraint binds the **repair
surface** as well as the batch one — a rewrite that routed only the batch
surface through `subprocess.run` and the repair surface through anything
else would break at `:1883`, not `:1881`.

with `def fake_run(argv, **kwargs)`. Three consequences, all normative:

- `invocation/cli.py` must reach the transport as `subprocess.run(...)`
  on the module object (`import subprocess` at module scope, call
  through the module attribute) — **not** `from subprocess import run`,
  which would bind the real function at import time and escape the
  patch.
- `argv` must be passed **positionally**; `timeout=` must be passed as
  a keyword. `subprocess.run(args=argv, ...)` breaks `fake_run`'s
  signature.
- `worker.py` must keep its `import subprocess` (it still needs it for
  `_spawn_window`, `_digest` and `_notify` — §7.1).

**`B-3a` — the general rule `B-3` is one instance of (NORMATIVE).** *Any
symbol a criterion monkeypatches must be reached through its module at
call time, never bound into the calling module's namespace at import
time.* A `from X import y` binds `y` before any test can replace it, so
the patch silently misses and the criterion passes without observing
anything — the fail-open shape. Three sites in this unit depend on it,
and each is called out where it lives:

| Site | Required form | Forbidden form |
|---|---|---|
| `TR7` — the transport | `import subprocess` + `subprocess.run(...)` | `from subprocess import run` |
| `RG7` — the warn leg | `from . import config` + `config._warn(...)` | `from .config import _warn` |
| `WR6` — the template leg | read `LOG_TEMPLATES` through the module at call time (or the test uses `monkeypatch.setitem` on the dict) | binding the template set into a module-level local at import |

The third has an escape hatch the other two do not: because
`LOG_TEMPLATES` is a **dict**, `monkeypatch.setitem` mutates the shared
object and works regardless of how it was imported. Either discipline
satisfies `WR6`; the spec does not choose for the builder, it only
forbids the combination that cannot be observed.

**`B-4` — `worker._invoke_claude`'s positional signature prefix is
frozen.** `B-3`'s call passes `argv, prompt, timeout, home` positionally
and `label` by keyword. New parameters may only be **keyword-only with
defaults**. In particular the settings file is written by `run()` and the
argv is built by `run()` — `_invoke_claude` receives an argv that is
already assembled. §3.10 explains what that costs the twin-witness
design and where the agreement is asserted instead.

**`B-5` — `miner._invoke_reader` survives by name, and its arity is
pinned harder than `*a` would pin it.** Seven tests in `test_miner.py`
monkeypatch it by attribute
(`monkeypatch.setattr(miner, "_invoke_reader", ...)`). Four of the seven
are `*a`-shaped lambdas (`lambda *a: called.append(1)` ×2,
`lambda *a: None` ×2), which by themselves would tolerate *any* arity.
**The other three are named functions taking exactly two positionals**,
and those are the binding ones:

| Shim | Signature |
|---|---|
| `spy` (inside the halted-file test) | `def spy(h, prompt):` |
| `fake` (inside the `shim_reader` helper) | `def fake(home, prompt):` |
| `fake` (inside the cursor-freshness test) | `def fake(h, prompt):` |

Two further tests call the real function through a PATH shim
(`test_reader_survives_oversize_prompt`,
`test_artifact_contract_sweeps_strays`). Signature
`(home: Path, prompt: str) -> Path | None` is therefore frozen in both
name and arity: a third parameter without a default breaks all three
named shims, and a *keyword-only* addition is the only extension that
survives. r1 stated this constraint as weaker than it is.

**`B-6` — the fail-closed lock census does NOT see `invocation/`. Measured,
and r1 got this backwards.** `test_lock_invariant.py`'s `NOT_REPO_TRUTH`
is a fail-closed AST census, but its reach is **root-level only**:

```
MODULES = {p.stem for p in SRC.glob("*.py")}          # :78
    for path in sorted(root.glob("*.py")):            # :288
```

`glob("*.py")` — not `rglob` — so a **subpackage is invisible to it**.
Every function in `invocation/` is outside the census by construction,
and no entry would ever be required no matter what the package wrote.

Two consequences, and r1 asserted neither correctly:

- **The reason the spool `unlink` and stray sweep stay in
  `miner._invoke_reader` is `W-c`, not a test.** Moving them into the
  backend changes **timeout-path behavior** — the shipped code returns
  before the sweep on a timeout, and a backend that swept would delete
  spool litter on a path that today preserves it. That is the argument.
  r1's claim that a test would redden was false.
- **`HY4` is a NEW guard closing a real census gap**, not a restatement
  of an existing one. The fail-closed census the project relies on has a
  hole exactly the shape of this unit's new package, and `HY4` is the
  only thing that will look inside it. It is not optional.

**`B-7` — `test_batch_fixes.py` patches `subprocess.Popen` globally, but
it cannot intercept a model invocation. Attribution corrected.** The
patch `monkeypatch.setattr(worker.subprocess, "Popen", fake_popen)` lives
in `test_no_push_env_propagates_to_spawned_child`, whose body is:

```
worker._spawn_window(home, no_push=True)
assert seen.get(worker.NO_PUSH_ENV) == "1"
```

It drives `_spawn_window` **directly** and never calls `worker.run` — so
no model invocation happens inside it at all, and routing the worker
surface through `Popen` would **not** be caught here. `worker.subprocess`
being the real module still means the patch is global *for that test's
duration*, which is why the site is worth naming; but r1's claim that it
covers `M4b` was wrong. `M4b`'s real coverage is `TR1`, `TR6` and
`test_repair.py::test_e1_timeouts_read_not_hardcoded` (`B-3`), whose
`fake_run` is installed on `subprocess.run` and would simply never fire.

**`B-8` — the baseline.** Measured on `83d05c6` (§9): CLI suite **1651
collected, 1646 passed, 5 skipped, 0 failed**, 169.85 s. UI suite **1234
collected** (not run by this unit; §7.2).

---

## 3. The change

### 3.1 The package (NORMATIVE)

`plugins/self-learn/cli/src/self_learn/invocation/`, five modules:

| Module | Contains | May import |
|---|---|---|
| `contract.py` | `Surface`, `Containment`, `SessionSpec`, `Outcome`, `Backend` (protocol), `BackendUnavailable`, `LOG_TEMPLATES`, `TRANSPORT`, `containment_permissions`, `containment_rules` | stdlib only |
| `cli.py` | `CliBackend` | stdlib, `.contract` |
| `fake.py` | `FakeBackend` | stdlib, `.contract` |
| `registry.py` | `backend_for`, `write_session`, `text_session` | stdlib, `.contract`, `.cli`, `..config` |
| `__init__.py` | re-exports only | the four above |

**`I-a`** No module in this package may import `worker`, `miner`,
`analyst`, `verbs`, `teach` or `ledger_ops`. Everything surface-specific
arrives as data or as a caller-supplied closure. This is what makes the
package importable from all three call sites without a cycle, and it is
criterion `HY2`.

**`I-b`** `registry.py` importing `..config` is the single permitted
upward import, and only for the ledger-config rung of the precedence
chain (§3.7). `config.py` imports nothing from `self_learn`, so no cycle
is created.

### 3.2 `Surf-1` — the surfaces and the selector map (NORMATIVE)

```
SURFACES = ("worker", "worker-repair", "miner-reader", "analyst")
```

Four surfaces. **Three** environment selectors, because the repair round
is the worker's second invocation and must never be configurable
independently of it (a run whose two halves used different backends is a
state nobody should have to reason about):

```
SELECTOR_FOR_SURFACE = {
    "worker":       "WORKER",
    "worker-repair":"WORKER",
    "miner-reader": "MINER",
    "analyst":      "ANALYST",
}
```

**`S-a`** Operation assignment is fixed and total:

| Surface | Operation | stdout |
|---|---|---|
| `worker` | `write_session` | never read |
| `worker-repair` | `write_session` | never read |
| `miner-reader` | `write_session` | diagnostic only — the detail line; **never parsed** |
| `analyst` | `text_session` | **is** the result |

**`S-b`** `write_session` and `text_session` never raise — not for a
missing CLI, not for a timeout, not for an unavailable backend, not for
an unknown surface — **with exactly one deliberate exception: on the
`analyst` surface a bare `OSError` is not caught and propagates,
preserving `R-1`** (`T-c`, criterion `TR4`). Every other condition
returns an `Outcome`. `text_session`'s caller maps `ok=False` onto
`AnalystError`.

The exception is stated here, in the contract, rather than only in the
transport table, because a reader who takes "never raises" literally will
write a call site that cannot handle the one case that does — which is
precisely how `R-1` survives into the next unit unnoticed.

**`S-c`** An unknown `spec.surface` is a programming error, not an
operator input, and it must **never** surface as a `KeyError` from a
`LOG_TEMPLATES[...]` or `TRANSPORT[...]` lookup. `write_session` /
`text_session` validate `spec.surface ∈ SURFACES` **before** any table
lookup and return an `Outcome` with `failure="unavailable"` and a detail
naming the surface. Because no template set can be selected for an
unknown surface, **nothing is logged** on this path — the `Outcome` is
the whole report. Covered as a leg of criterion `RG5`.

### 3.3 `Cont-1` — containment as data, and the one place `//` is rendered (NORMATIVE)

```python
@dataclass(frozen=True)
class Containment:
    allowed_tools: str | None       # the --allowedTools value, verbatim; None = flag absent
    disallowed_tools: str | None    # the --disallowedTools value, verbatim; None = flag absent
    write_globs: tuple[str, ...]    # absolute path PATTERNS, no rule syntax
    write_exact: tuple[str, ...]    # absolute FILE paths, no rule syntax
    strict_mcp: bool
    default_mode: str | None        # the settings file's permissions.defaultMode; None = key absent
```

**`C-a` — `default_mode` is a sixth field, added deliberately.** It is
the `GR-a` security hotfix: without `permissions.defaultMode`, a
settings-file scope is decorative on any host whose global
`~/.claude/settings.json` sets `bypassPermissions`. A containment record
that omits it would describe a boundary that does not enforce, which is
the single most dangerous thing this data structure could get wrong. It
also lets the twin witness compare the **whole** `permissions` object
rather than only `allow` (§3.10).

**`C-b` — rule rendering lives in exactly one function.**

```python
def containment_rules(c: Containment) -> list[str]:
    return [f"Edit(/{p})" for p in (*c.write_globs, *sorted(c.write_exact))]

def containment_permissions(c: Containment) -> dict:
    perms: dict[str, object] = {"allow": containment_rules(c)}
    if c.default_mode is not None:
        perms["defaultMode"] = c.default_mode
    return perms
```

Three properties, all normative and all pinned by criteria:

- The `/` in `Edit(/{p})` plus the leading `/` of an absolute `p` is what
  produces the shipped **double slash**: `Edit(//home/<user>/.cache/...)`.
  There is exactly one occurrence of that construction in the package.
  Criterion `CN1`; mutation `M1`.
- `write_exact` is **sorted at render time**, mirroring
  `write_repair_settings_file`'s `rules = [f"Edit(/{p})" for p in sorted(paths)]`.
  `write_globs` is **not** sorted — the three fallback ledger globs ship
  in a hand-chosen order (`skills`, `projects`, `user`) that
  `write_permission_rules` returns literally, and sorting them would
  change the settings file. Criterion `CN4`; mutation `M10`.
- `defaultMode` is **omitted, not set to null**, when absent — matching
  `if _enforce_scope(): permissions["defaultMode"] = "default"`.
  Criterion `CN5`; mutation `M14`.

**`C-c` — the four containments, and the DIRECTION rule that makes them a
witness (NORMATIVE).**

r1 wrote that the containments are *"derivations of the same inputs,
never independent transcriptions."* **That sentence is struck.** It was
the defect the r1 gate's first BLOCKER named, and it inverted the whole
design: **the independent transcription IS the witness.** Two statements
of the same fact are only evidence when neither was computed from the
other. A containment "derived from the same inputs" as the settings file
can be — and, if a builder takes the sentence at its word, *will* be —
derived by calling the settings writer, at which point `CN6` compares a
value with itself and can never fail.

So the direction is now normative, and it runs one way only:

> **`containment_for(...)` receives SCALARS ONLY** — `home`,
> `stage_dir`, `stage_on`, `enforce`, the `write_exact` tuple, the
> `spool_dir`, and the tool strings. It renders **every glob PATTERN from
> string literals inside `contract.py`**. It may not receive, call, or
> otherwise consult **any** rule list, rule string, settings path, or
> settings-file content.

Concretely: `contract.py` contains its own literals
`f"{home}/skills/**/proposals/**"`, `f"{home}/projects/**/proposals/**"`,
`f"{home}/user/proposals/**"`, `f"{stage_dir}/**"`, `f"{spool_dir}/**"`.
Those literals and `worker.write_permission_rules`'s / 
`worker.stage_permission_rules`'s / `miner.write_reader_settings`'s are
**two independent transcriptions of the same intent**, and `CN6` is the
place they are forced to agree. That is the entire value of the
construction; a builder who removes the duplication removes the test.

| Containment | Scalar inputs | `allowed_tools` | `disallowed_tools` | `write_globs` | `write_exact` | `strict_mcp` | `default_mode` |
|---|---|---|---|---|---|---|---|
| `worker` | `home`, `stage_dir`, `stage_on`, `enforce`, tool strings | `allowed_tools` argument | `disallowed_tools` argument | rendered from `contract.py` literals: the stage pattern when `stage_on`, else the three ledger patterns | `()` | `True` | `"default"` when `enforce`, else `None` |
| `worker-repair` | `write_exact` tuple, `enforce`, tool strings | `allowed_tools` argument | `disallowed_tools` argument | `()` | the repair set `E`, as passed | `True` | `"default"` when `enforce`, else `None` |
| `miner-reader` | `spool_dir`, `disallowed_tools` string | `None` | `disallowed_tools` argument | rendered from the `contract.py` spool literal | `()` | `False` | `"default"` |
| `analyst` | `allowed_tools` string | `allowed_tools` argument | `None` | `()` | `()` | `False` | `None` |

**The "Scalar inputs" column is exhaustive** — anything not listed is a
value `containment_for` must not be given.

**`C-c1` — what the call sites pass, resolving r1's analyst-row
contradiction.** r1's table wrote `—` in the analyst's input column while
its prose said the tool strings *"arrive as arguments from the call
sites"*. The two cannot both be true. **Decision: the prose is right and
the `—` was wrong.** Every tool string arrives as an argument, on every
surface including the analyst, because `I-a` forbids `contract.py` from
importing `worker` or `analyst` to read `ALLOWED_TOOLS`,
`DISALLOWED_TOOLS`, `READER_DISALLOWED_TOOLS` or `ANALYST_ALLOWED_TOOLS`.
The analyst's row therefore reads `allowed_tools` string, not `—`. What
each call site is obliged to pass:

| Surface | passes `allowed_tools=` | passes `disallowed_tools=` |
|---|---|---|
| `worker`, `worker-repair` | `worker.ALLOWED_TOOLS` | `worker.DISALLOWED_TOOLS` |
| `miner-reader` | `None` | `miner.READER_DISALLOWED_TOOLS` |
| `analyst` | `analyst.ANALYST_ALLOWED_TOOLS` | `None` |

r1 checked this table by reading `containment_for`'s own defaults, which
proves nothing about the call sites. `CN2` is restated in §4 to observe
the **call site** instead, and `CN10` adds argv as an independent third
witness of the same three fields.

**`C-d` — the analyst's containment is deliberately near-empty, and that
is a true statement.** `analyst.build_argv` emits no `--disallowedTools`,
no `--settings`, no `--strict-mcp-config`. Its restriction is
`--allowedTools Read,Grep,Glob` alone. Recording that faithfully — rather
than filling the fields in by analogy with the worker — is the point:
a future `SdkBackend` reading this record must reproduce the analyst's
*actual* (weaker) boundary, not a boundary the CLI never had. Criterion
`CN3`.

### 3.4 `Spec-1` — `SessionSpec` and `Outcome` (NORMATIVE)

```python
@dataclass(frozen=True)
class SessionSpec:
    surface: str
    prompt: str
    cwd: Path
    timeout: float
    containment: Containment
    log: Callable[[str], None]
    cli_argv_builder: Callable[[Path | None], list[str]]
    cli_settings_writer: Callable[[], Path] | None = None
    label: str = ""
    timeout_display: object | None = None
```

**`SP-a`** `cli_argv_builder` always takes **one** argument: the settings
path, or `None` when the surface has no settings file. Uniform arity;
call sites adapt with a lambda. `CliBackend` calls
`cli_settings_writer()` first when it is not `None`, and passes its
result into `cli_argv_builder`. **Order is pinned**: settings file
written, *then* argv built — matching the shipped
`build_argv(home, write_settings_file(home))` evaluation order.
Criterion `AV3`.

**`SP-b`** `cli_settings_writer` is `None` on `worker`, `worker-repair`
and `analyst`. On the first two that is forced by `B-4` (`run()` already
wrote the file and built the argv before `_invoke_claude` is reached); on
the analyst there is no settings file at all. Only `miner-reader`
supplies a real writer, and it therefore is the one surface that
exercises the writer→builder chain end to end. This is a *known
asymmetry*, not an oversight — see §3.10 and §8/`X-3`.

**`SP-c`** `timeout_display` is the value the `timed_out` template
interpolates; `None` (the default) means "render `spec.timeout`". It
exists because the miner logs the **raw module constant** it was given,
while the transport is handed a number — and those are separately
mutable. `LG3`'s second leg is the criterion that proves the field is
actually read (drive `spec.timeout=900.0` with `spec.timeout_display=900`
and require `"900s"`; a build that ignores the field renders `"900.0s"`),
and `M35` is the mutation that removes it. Without that pair the field
would be unfalsifiable decoration and should not ship at all —
§3.6/`L-c` is the rest of the story.

**`SP-d`** `label` is `""` (worker batch, miner, analyst) or `"repair "`
(worker repair). It is interpolated into the worker's templates only.

```python
FAILURE_KINDS = ("exit", "timeout", "not-found", "os-error", "unavailable")

@dataclass(frozen=True)
class Outcome:
    ok: bool                 # == (failure is None)
    rc: int | None           # None when the process never exited
    stdout: str              # "" unless the surface's transport captures it
    detail: str              # the surface's detail string, UNTRUNCATED, UNSTRIPPED
    failure: str | None      # None or a member of FAILURE_KINDS
    exc: BaseException | None = None
```

**`SP-e`** `ok is (failure is None)` is an invariant, asserted in
`__post_init__`. A `rc != 0` process is `failure="exit"`, `ok=False` —
even on the miner surface, where the caller deliberately continues
anyway (§3.9.2).

**`SP-f`** `detail` is stored raw. Truncation and stripping are
**rendering** decisions and live in the log-template table (§3.6), so a
change to either is a one-field edit that a criterion can pin.

### 3.5 `Trans-1` — the transport table (NORMATIVE)

`CliBackend` branches on `spec.surface` through one table. Nothing else
in the backend is surface-aware.

| Surface | Call | Prompt channel | Streams | Caught | Timeout kill |
|---|---|---|---|---|---|
| `worker` | `subprocess.run` | `input=` (stdin) | `capture_output=True, text=True` | `FileNotFoundError`, `subprocess.TimeoutExpired`, `OSError` | none (run's own) |
| `worker-repair` | `subprocess.run` | `input=` (stdin) | `capture_output=True, text=True` | same | none |
| `miner-reader` | `subprocess.Popen` + `communicate` | `communicate(prompt, timeout=)` | `stdin=PIPE, stdout=PIPE, stderr=STDOUT, text=True, start_new_session=True` | `FileNotFoundError`, `subprocess.TimeoutExpired`, `OSError` | `os.killpg(proc.pid, SIGKILL)` guarded by `(ProcessLookupError, PermissionError)`, then `proc.wait()` |
| `analyst` | `subprocess.run` | **argv** (the builder already embedded it) | `capture_output=True, text=True` | `FileNotFoundError`, `subprocess.TimeoutExpired` — **`OSError` is NOT caught** | none |

**`T-a`** Every call passes `cwd=str(spec.cwd)`. All four surfaces do
today (`cwd=str(home)` in each). Criterion `TR5`; mutation `M19`.

**`T-b`** `start_new_session=True` and the `killpg` are the miner's alone
and are moved **verbatim**. The comment they carry — *"On timeout the
reader's whole process group is killed (a hung node child must not
outlive the 15-minute budget)"* — moves with them. Criteria `TR2`,
`TR3`; mutations `M4`, `M5`, `M23`.

**`T-c`** The analyst's missing `OSError` leg is **preserved on purpose**.
`analyst.analyze` today catches `FileNotFoundError` and
`subprocess.TimeoutExpired` and nothing else; a bare `OSError` (a
`PermissionError` from a non-executable `claude` on PATH, say) escapes
`analyze()` and escapes `teach.py`'s `except analyst.AnalystError`,
losing the record. That is a real shipped defect (§7.3/`R-1`). Fixing it
is a behavior change and belongs to its own unit. **This unit reproduces
it and pins it**, so the fix later is a visible, deliberate act rather
than a silent side effect of a refactor. Criterion `TR4`; mutation `M24`.

**`T-d`** `detail` per surface, computed by the backend:

| Surface | `detail` |
|---|---|
| `worker`, `worker-repair` | `proc.stderr or proc.stdout` |
| `miner-reader` | `output or ""` (the merged stream from `communicate`) |
| `analyst` | `proc.stderr or proc.stdout` |

Stripping and truncation are applied at render (§3.6), not here.
Criterion `LG5`; mutation `M6`.

**`T-e`** `Outcome.stdout` is `proc.stdout` on `analyst`, the merged
`output` on `miner-reader`, and `""` on both worker surfaces. The worker
surfaces' `""` is a contract statement, not an accident: nothing may
parse worker stdout, and returning `""` makes a future attempt to do so
fail loudly. Criterion `WR4`.

### 3.6 `Log-1` — the log templates, per surface, byte-exact (NORMATIVE)

**Register note (`L-0`): this section is AUTHORITATIVE for template
bytes. §8's `X-1` table is PROVENANCE** — it records what master says
today, so a reader can check this section's transcription against the
source. Where the two ever disagree, §3.6 is the specification and §8 is
a stale quotation to be re-read against master.

**No third NORMATIVE statement of these strings may exist in this
document.** Rendered examples elsewhere are *derived* and are labeled as
such — they do not bind, and they go stale if this table changes:

| Elsewhere | Status |
|---|---|
| `LG1`'s sample expectations | **Illustrations** of the criterion's shape. `LG1` binds *"renders byte-identically to the shipped string"*; the samples show what that looks like for one input set. |
| `W-i`'s two-line `unavailable` message | **A derived composition** of this table's `analyst.unavailable` template and §3.7.4's `BackendUnavailable` text. If either changes, `W-i` is stale and must be recomposed — it is not an independent pin. |

The logging **function** comes from the caller (`spec.log` carries
`worker.log` / `miner.log`; the analyst's is a no-op). The **templates**
live in `contract.py`, keyed by surface, because the three surfaces'
wording differs and only a table makes the difference visible:

```python
@dataclass(frozen=True)
class LogTemplates:
    exited: str | None
    timed_out: str | None
    not_found: str | None
    os_error: str | None
    unavailable: str
    detail_cap: int | None      # [:N] before interpolation; None = no truncation
    detail_strip: bool          # .strip() before interpolation
```

`LOG_TEMPLATES: dict[str, LogTemplates]`, with these values — **each one
transcribed from the shipped source and byte-exact**:

| Field | `worker` / `worker-repair` | `miner-reader` | `analyst` |
|---|---|---|---|
| `exited` | `"run: {label}claude exited {rc}: {detail}"` | `"run: claude exited {rc}: {detail}"` | `"analyst exited {rc}: {detail}"` |
| `timed_out` | `"run: {label}claude timed out after {timeout:g}s"` | `"run: claude timed out after {timeout}s"` | `"analyst timed out after {timeout:g}s"` |
| `not_found` | `"run: {label}claude CLI not found on PATH"` | `"run: claude CLI not found on PATH"` | `"claude CLI not found on PATH"` |
| `os_error` | `"run: {label}claude invocation failed ({exc})"` | `"run: reader invocation failed ({exc})"` | `None` (no leg — `T-c`) |
| `unavailable` | `"run: {label}invocation backend unavailable ({exc})"` | `"run: invocation backend unavailable ({exc})"` | `"invocation backend unavailable ({exc})"` |
| `detail_cap` | `400` | `400` | `None` |
| `detail_strip` | `False` | `False` | `True` |

**`L-a` — the templates are NOT uniform, and that is the shipped truth.**
The charter's four-template model is right about the *kinds* and wrong
about the *strings*: the miner carries no `label`, says
`reader invocation failed` rather than `claude invocation failed`, and
does not use the `:g` format; the analyst has no `run: ` prefix, no
truncation, strips its detail, and has no `os_error` leg at all. Every
one of these is quoted from master in §8. Flattening them would change
operator-visible bytes on two of three surfaces — refused.

**`L-b` — `unavailable` is NEW, and it is deliberately not any of the
other four.** When the registry refuses (`sdk` selected pre-U-sdk), the
run degrades *like* a missing CLI — same control flow, same continue-and-
harvest, same "the record stays pending" outcome — but the log must not
**say** the CLI is missing, because it is not. A new line for a new
cause. Criterion `RG5`.

**`L-c` — the timeout value rendered is not always `spec.timeout`.**
The worker renders `{timeout:g}` over a float from `invoke_timeout_secs()`
— `1800.0` renders `1800`. The miner renders `{timeout}` over
`miner.INVOKE_TIMEOUT_SECS`, which is the **int** `15 * 60`; `{900}`
renders `900`. Passing the int through `:g` also renders `900`, so at the
shipped constant the two spellings are indistinguishable. Two separate
things therefore have to be made falsifiable, and `LG3` has one leg for
each:

| Leg | Spec driven | Shipped renders | Mutant renders | Kills |
|---|---|---|---|---|
| `LG3a` worker `:g` | `timeout=1800.0`, `timeout_display=None` | `1800s` | `1800.0s` | `M12` (`:g` dropped) |
| `LG3b` miner no-`:g` | `timeout_display=900.0` (float) | `900.0s` | `900s` | a `:g` added to the miner template |
| `LG3c` field is read | `timeout=900.0`, `timeout_display=900` (int) | `900s` | `900.0s` | `M35` (`timeout_display` removed) |

`LG3c` is the leg that earns the field its place. Without it
`timeout_display` is unfalsifiable decoration — every other criterion
passes whether the backend reads it or silently ignores it — and an
unfalsifiable field in a data structure whose entire purpose is to be
*checked* is worse than no field. The alternative considered and rejected
was deleting `timeout_display` and having the miner call site pass its
int as `spec.timeout` directly; that works today but couples the
transport's argument to the log's argument, so the next unit that needs
a float timeout on the miner silently changes an operator-visible byte.

**`L-d`** Nothing is logged on a clean run (`failure is None`). All four
surfaces are silent on success today. Criterion `LG6`.

**`L-e`** The analyst logs nothing at all, ever — `analyze()` raises
instead. Its `spec.log` is a no-op and criterion `LG7` asserts neither
`worker.log` nor `miner.log` grows during an analyst invocation.

### 3.7 `Reg-1` — the registry (NORMATIVE)

#### 3.7.1 The chain

`backend_for(surface, *, home=None) -> Backend`, resolving in this order,
**first hit wins**:

| Rung | Source | Example |
|---|---|---|
| 1 | `SELF_LEARN_BACKEND_<SELECTOR>` env | `SELF_LEARN_BACKEND_MINER=cli` |
| 2 | `SELF_LEARN_BACKEND` env | `SELF_LEARN_BACKEND=sdk` |
| 3 | `config.yaml` → `invocation.backend_<surface>` | `invocation: {backend_miner-reader: cli}` |
| 4 | `config.yaml` → `invocation.backend` | `invocation: {backend: cli}` |
| 5 | built-in default | `"cli"` |

`<SELECTOR>` is `SELECTOR_FOR_SURFACE[surface]` (§3.2) — so
`worker-repair` reads `SELF_LEARN_BACKEND_WORKER`. Rung 3 keys on the
**surface**, not the selector, because a config file is edited
deliberately and a reader of it benefits from the finer name. Criterion
`RG1` walks all five rungs and `RG2` proves each rung is shadowed by the
one above it.

**`R-a`** An **empty or unset** value at a rung is "no answer" and falls
through. An empty string is not an unknown value and must not warn —
`SELF_LEARN_BACKEND=` in a stray shell export would otherwise print a
warning on every invocation. Criterion `RG6`.

#### 3.7.2 Fail-closed on an unknown value

`KNOWN_BACKENDS = ("cli", "sdk")`. Anything else at any rung:

- **warns once on stderr**, and
- **falls back to `"cli"`** — never to `sdk`, never to the next rung.

Falling to `cli` rather than continuing down the chain is the fail-closed
direction: an operator who typed `SELF_LEARN_BACKEND=slk` should get the
shipped, tested path plus a loud complaint, not a silent promotion of
whatever rung 3 happened to say.

The warning is byte-pinned, and there are two spellings because the
sources are different in kind:

```
self-learn: unknown invocation backend {value!r} in {var} — using "cli"
self-learn: config.yaml ignored — invocation.{key} must be one of cli, sdk; got {value!r} — using "cli"
```

The second reuses `config.py`'s shipped `_warn` prefix
(`print(f"self-learn: config.yaml ignored — {message}", file=sys.stderr)`)
because it *is* a config.yaml rejection and the operator has learned that
prefix. The first must not, because no config file was involved.
Criterion `RG3`; mutation `M11`.

**`R-c` — the registry CALLS `config._warn`; it does not re-spell the
prefix.** `registry.py` emits the config-flavored warning as
`config._warn(f"invocation.{key} must be one of cli, sdk; got {value!r} — using \"cli\"")`.
Reaching for another module's underscore-prefixed helper is normally a
smell, and it is the right call here for one reason: the alternative is a
second literal copy of an **operator-facing prefix** living in a
different file from the first, which is the exact defect class this whole
unit exists to prevent. One register, one owner. `_warn` stays private
(it is **not** added to `config.__all__`); only `invocation_backend` is
exported. Criterion `RG7`'s last leg.

#### 3.7.3 The config reader

`config.py` gains **one** function:

```python
def invocation_backend(home: Path | str, surface: str) -> tuple[str, str] | None
```

returning `(key, value)` for the first present key among rung 3's
`backend_<surface>` and rung 4's `backend`, else `None` — `key` names the
exact key that matched, so the registry's warning names the key the
operator actually wrote — and **added to `config.__all__`** — which currently reads
`["CONFIG_BASENAME", "config_path", "one_motion_enabled"]` and becomes
`["CONFIG_BASENAME", "config_path", "invocation_backend", "one_motion_enabled"]`.

It follows `one_motion_enabled`'s existing discipline case for case:

| Input | Result |
|---|---|
| missing file | `None`, **silent** |
| **empty file** (YAML loads to `None`) | `None`, **silent** — the `if data is None: return False` leg `one_motion_enabled` already has, and the case r1's `RG7` omitted |
| unparseable (`YAMLError`/`OSError`/`UnicodeDecodeError`) | `_warn` + `None` |
| top level not a mapping | `_warn` + `None` |
| `invocation` section present but not a mapping | `_warn` + `None` |
| `invocation` section absent | `None`, silent |
| value present but not a `str` | `_warn` + `None` |

It does **not** validate against `KNOWN_BACKENDS` — that judgement, and
its warning, belong to the registry so there is one place where "unknown
means cli" is decided (`R-c`). Criterion `RG7`.

#### 3.7.4 The lazy `sdk` branch

```python
class BackendUnavailable(RuntimeError): ...
```

Selecting `"sdk"` — at any rung — raises `BackendUnavailable` from
`backend_for`, with this message, byte-pinned:

```
the "sdk" invocation backend is not built yet — install it with:
    pip install 'self-learn-cli[sdk]'
```

`write_session` and `text_session` catch it, render the surface's
`unavailable` template through `spec.log`, and return
`Outcome(ok=False, rc=None, stdout="", detail=str(exc), failure="unavailable")`.
**Neither entry point re-raises** (`S-b`). Criteria `RG4`, `RG5`.

**`R-b`** The `sdk` extra is **declared** in the CLI's `pyproject.toml`
so that install command is true rather than aspirational:

```toml
[project.optional-dependencies]
sdk = ["claude-agent-sdk>=0.2.116,<0.3"]
```

The pin matches the UI package's shipped `claude-agent-sdk>=0.2.116,<0.3`
— one SDK version across the repo, so `FW-15`/`FW-23`'s verify-at-build
gate has one thing to verify. Declaring an extra installs nothing.
Criterion `RG8`.

### 3.8 `Fake-1` — `FakeBackend` (NORMATIVE)

`FakeBackend` is a `Backend` that records and simulates. It ships in this
unit because §4's criteria need it, and because the SDK unit will need
exactly the same recorder.

**`F-a`** It records, in call order: every `SessionSpec` it received
(`.specs`), every prompt (`.prompts`), and every argv it *would* have run
— obtained by calling the spec's own closures, so a test can assert on
argv without spawning anything (`.argvs`).

**`F-b`** It is scripted per call with a list of `FakeStep`s:

| Step | Effect |
|---|---|
| `Writes(files: dict[Path, str])` | writes those files, returns `ok=True, rc=0` |
| `Text(s: str)` | returns `ok=True, rc=0, stdout=s` |
| `Exits(rc: int, detail: str)` | returns `failure="exit"` |
| `TimesOut()` | returns `failure="timeout"` |
| `NotFound()` | returns `failure="not-found"` |
| `Fails(exc: OSError)` | returns `failure="os-error"` |

It renders the surface's log templates through `spec.log` for every
non-`None` failure, exactly as `CliBackend` does — otherwise a test using
the fake would silently stop covering the log surface. Criterion `FK2`.

**`F-c` — `FakeBackend` is NOT reachable from `backend_for`.** There is
no `SELF_LEARN_BACKEND=fake`; `"fake"` is not in `KNOWN_BACKENDS` and
resolves fail-closed to `cli` with the unknown-value warning like any
other typo. Tests inject it explicitly:
`write_session(spec, backend=FakeBackend([...]))`. An env-selectable fake
in a tool that writes a real ledger is a footgun with no upside — the
tests that want it can always pass it. Criterion `FK3`; mutation `M21`.

**`F-d`** `write_session(spec, *, backend=None)` / `text_session(spec, *,
backend=None)`: `None` resolves through `backend_for`. That keyword is
the *only* injection point.

### 3.9 `Wire-1` — the three call sites (NORMATIVE)

#### 3.9.1 `worker._invoke_claude`

Signature becomes:

```python
def _invoke_claude(
    argv: list[str], prompt: str, timeout: float, home: Path, *,
    label: str,
    containment: Containment | None = None,
) -> None:
```

Positional prefix unchanged (`B-4`). Body: build a `SessionSpec` with
`surface = "worker-repair" if label == "repair " else "worker"`,
`cli_argv_builder = lambda _settings: argv`, `cli_settings_writer=None`,
`log=log`, `cwd=home`, `containment=containment or DEGRADED_WORKER_CONTAINMENT`,
call `write_session(spec)`, ignore the returned `Outcome`. Still returns
`None`; still never raises.

**`W-a` — `run()` computes and passes `containment=` at BOTH call sites.
The default is not a fallback anybody uses in production.** r1 wrote
`containment=containment or <the batch default>`, which left the actual
default unspecified and — worse — implied that omitting the argument was
a legitimate mode. It is not. Normatively:

- **Both** of `run()`'s call sites pass an explicit `containment=`. The
  batch site passes `containment_for("worker", ...)`; the repair site
  passes `containment_for("worker-repair", write_exact=tuple(repair_eligible_paths), ...)`.
  Criterion `CN8` drives a repair-producing run and checks both.
- `DEGRADED_WORKER_CONTAINMENT` is a module-level constant in
  `contract.py` describing **nothing** — empty `write_globs`, empty
  `write_exact`, `default_mode=None`. It exists for exactly one reason:
  `test_repair.py::test_e1` calls `_invoke_claude` with five arguments
  and no containment, and that call must stay legal (`B-4`). It is never
  reached from `run()`. Naming it "degraded" rather than "default" is
  deliberate — a builder tempted to route production through it should
  be reading a word that says *this describes no real boundary*.

The two call sites, quoted for location:

- batch: `_invoke_claude(argv, prompt, invoke_timeout_secs(), home, label="")  # S2`
- repair: the call spanning lines beginning `_invoke_claude(` and
  `repair_argv,`

**`W-a1` — the shipped `argv = build_argv(home, write_settings_file(home))`
stays ONE statement.** r1 proposed splitting it so `run()` could hold the
settings path; the gate found nothing needs it, and it is dropped. `CN8`
reads the settings path out of the **captured argv** (`--settings`'s
value), which is a stronger observation anyway — it checks the path the
process was actually told to use, not a path a local variable happened to
hold. The evaluation order (settings written, then argv built) is
unchanged and is what criterion `AV3` pins.

**`W-b`** `label` still selects the surface, and the surface still
selects the template — so `"repair "` still appears in exactly the repair
round's lines and nowhere else. Criterion `LG2`; mutation `M13`.

#### 3.9.2 `miner._invoke_reader`

The function, its name, its signature and its docstring survive
(`B-5`). Only the transport block changes. **The line the change starts
at and the line it ends at are both pinned**:

- Everything **above** `argv = build_reader_argv(write_reader_settings())`
  stays — including `out_path = spool_dir() / OUTPUT_BASENAME` and
  `out_path.unlink(missing_ok=True)`. Those are writes, and `B-6` keeps
  them out of the backend.
- The `try:` block from `proc = subprocess.Popen(` through
  `log(f"run: claude exited {proc.returncode}: {(output or '')[:400]}")`
  and its three `except` clauses is **replaced** by one `write_session`
  call plus a failure dispatch.
- Everything **below** — the stray sweep beginning
  `# Artifact contract: exactly OUTPUT_BASENAME; strays are litter.` and
  the final `return out_path if out_path.is_file() else None` — stays.

The failure dispatch reproduces the shipped control flow exactly:

```
outcome.failure in {"timeout", "not-found", "os-error", "unavailable"}  ->  return None   (before the sweep)
outcome.failure == "exit"                                              ->  fall through   (sweep runs, out_path checked)
outcome.failure is None                                                ->  fall through
```

**`W-c`** The early returns happen **before** the stray sweep, because
they do today (`return None` sits inside the `try`/`except`, above the
sweep loop). A refactor that runs the sweep first would delete spool
litter on a timeout, which is a behavior change. Criterion `WR2`;
mutation `M18`.

**`W-d`** `rc != 0` does **not** short-circuit: the shipped code logs and
continues to the sweep, then returns `out_path` if the model happened to
write it anyway. Preserved. Criterion `WR3`; mutation `M17`.

**`W-e`** `spec.timeout` is read from `miner.INVOKE_TIMEOUT_SECS` **at
call time** (module attribute, not a captured default) — the two shipped
reads are both at call time and a test monkeypatching the module constant
must still take effect. `spec.timeout_display` carries the same value
unconverted (`L-c`). Criterion `LG3`.

#### 3.9.3 `analyst.analyze`

Replaced block: from `argv = build_argv(prompt, doctrine_text, model)`
through `raise AnalystError(f"analyst exited {proc.returncode}: {detail}")`.
Everything above (the doctrine check, the home guard, the
`compose_single_prompt` call) and everything below (`_parse_yaml_map`,
Register R's copy-then-stamp, the roster-sha honesty legs,
`validate_proposal`) is untouched — this unit does not read them, does
not move them, and does not reorder them.

The new block builds a `SessionSpec` with `surface="analyst"`,
`cli_argv_builder = lambda _settings: build_argv(prompt, doctrine_text, model)`,
`cli_settings_writer=None`, `log=<no-op>`, `cwd=home`,
`timeout=_timeout()`, calls `text_session(spec)`, then raises.

**`W-h` — every `AnalystError` message on this path is rendered through
`LOG_TEMPLATES["analyst"]` (NORMATIVE).** The analyst does not *log* its
templates (`L-e`), but its exception text **is** its operator-visible
byte surface, and it is the same four strings. `analyze` therefore
formats `LOG_TEMPLATES["analyst"].exited` / `.timed_out` / `.not_found` /
`.unavailable` — honoring `detail_strip=True` and `detail_cap=None` —
and passes the result to `AnalystError`. It does **not** carry its own
copies of those f-strings. Without this rule the analyst's bytes have two
owners and §3.6 stops being authoritative for a third of the surface.

| `outcome.failure` | Raises `AnalystError(...)` with |
|---|---|
| `"not-found"` | `LOG_TEMPLATES["analyst"].not_found` → `claude CLI not found on PATH` |
| `"timeout"` | `.timed_out` → `analyst timed out after 120s` (at the default timeout) |
| `"exit"` | `.exited` → `analyst exited {rc}: {detail}`, detail stripped, untruncated |
| `"unavailable"` | `.unavailable` → the byte literal below |
| `None` | falls through to `parsed = _parse_yaml_map(outcome.stdout)` |

**`W-i` — the `unavailable` message, as a byte literal.** r1 wrote
`<the BackendUnavailable message>`, which is a placeholder, not a pin.
The analyst's `unavailable` template is
`"invocation backend unavailable ({exc})"` and `{exc}` is the
`BackendUnavailable`'s own `str()`, so the `AnalystError` raised when
`SELF_LEARN_BACKEND=sdk` carries exactly:

```
invocation backend unavailable (the "sdk" invocation backend is not built yet — install it with:
    pip install 'self-learn-cli[sdk]')
```

— a two-line message whose second line is indented four spaces, and
whose closing parenthesis follows `[sdk]'` with no newline between them.
`WR6` quotes this literal. It is a **new** string, not a shipped one:
there is no pre-U-seam behavior to be byte-identical to, because
`BackendUnavailable` did not exist. `WR6`'s row for it is therefore
labeled *new*, not *shipped*.

**`W-f`** The `from exc` chaining on the two shipped raises
(`raise AnalystError(...) from exc`) is preserved: `Outcome.exc` carries
the original exception for exactly this. A dropped `from exc` costs a
debugger the cause chain. Criterion `WR5`.

**`W-g`** `_timeout()` is called **twice** on the timeout path today —
once for `subprocess.run(timeout=...)` and once inside the message. If
`SELF_LEARN_ANALYST_TIMEOUT` changed between them the two would differ;
they never do in practice. The rewrite calls it once for the spec and
renders from `spec.timeout`. This is the **one** place this unit does not
reproduce the shipped code's literal structure, and it cannot change an
observable byte (the env var cannot change mid-call). Recorded here so
the gate does not have to rediscover it.

### 3.10 The twin witnesses, and where the agreement is asserted (NORMATIVE)

**Witness A** is `Containment` plus `containment_permissions` — the
semantic truth, the thing a future `SdkBackend` reads. Its patterns come
from `contract.py`'s **own literals** (`C-c`).

**Witness B** is the shipped settings-file writer for that surface —
`worker.write_settings_file`, `worker.write_repair_settings_file`,
`miner.write_reader_settings`, and for the analyst *the absence of one*.
Its rules come from **those functions' own f-strings**, byte-frozen by
`HY3`.

**Witness C** (new in r2, `CN10`) is the **argv** the process is actually
launched with — `--allowedTools`, `--disallowedTools`,
`--strict-mcp-config`. It is independent of both A and B because it is
built by `worker.build_argv` / `miner.build_reader_argv` /
`analyst.build_argv`, none of which read a containment or a settings
file. It covers the three `Containment` fields that have **no settings-file
counterpart at all** — `allowed_tools`, `disallowed_tools`, `strict_mcp`
— which r1 left witnessed by nothing but `containment_for`'s own
defaults. That was the r1 gate's second BLOCKER.

**Direction is what makes any of them evidence.** A ⟂ B is guaranteed by
`C-c`'s scalars-only rule and enforced by `CN9`; A ⟂ C is guaranteed by
`I-a` (the package cannot import the argv builders) and by the builders
not reading containments.

**`TW-a`** The agreement is asserted as a **static criterion** over a
registry in the test module, not through `SessionSpec` at runtime:

```
SETTINGS_WITNESS = {
    "worker":        worker.write_settings_file,
    "worker-repair": worker.write_repair_settings_file,
    "miner-reader":  miner.write_reader_settings,
    "analyst":       None,
}
```

and for each surface:

```
containment_permissions(containment_for(surface, ...)) == json.loads(witness(...).read_text())["permissions"]
```

with the analyst's leg asserting instead that its witness is `None`, that
`containment_rules(...) == []`, and that `analyst.build_argv(...)`
contains no `--settings`.

**`TW-b` — why static, and what it costs.** The charter's design has
`SessionSpec` carry a `cli_settings_writer` on every surface, so the two
witnesses meet on every real invocation. `B-4` forbids that on the two
worker surfaces: `test_repair.py::test_e1` calls `_invoke_claude` with a
pre-built argv positionally, so by the time the seam is reached the
settings file has already been written by `run()`. Moving the write down
into `_invoke_claude` would edit `test_e1`, violating `SU2` — the
headline criterion. **The agreement is therefore checked once per build,
statically, over all four surfaces, rather than continuously at runtime
over two of them.** That is weaker in one specific way — a call site
could pass a containment that disagrees with the settings file the same
run wrote — and criterion **`CN8`** (not `CN6`, which r1 mis-cited here)
closes exactly that gap on a real repair-producing run, for **both** of
that run's invocations.

**`TW-c`** The worker's containment is **not a constant** — it is a
function of `SELF_LEARN_STAGE` (stage rule vs the three ledger globs) and
`SELF_LEARN_ENFORCE_SCOPE` (`defaultMode` present or absent). The
agreement criterion runs over **all four combinations** of those two
switches for the worker surface, and both `SELF_LEARN_ENFORCE_SCOPE`
values for the repair surface. Criterion `CN7`.

### 3.11 What deliberately does not move

- **The spool `unlink` and the stray sweep** stay in `miner._invoke_reader`
  because moving them changes timeout-path behavior (`W-c`) — **not**
  because a census test would redden; the census cannot see the package
  at all (`B-6`).
- **Prompt composition** — `compose_batch_prompt`, `_compose_repair_prompt`,
  `miner._compose_prompt`, `compose_single_prompt` — is untouched. The
  seam takes a prompt; it never builds one.
- **The sentinel re-assertions** around the worker's two invocations
  (`if not sentinel.heartbeat():`) stay in `run()`, outside the seam.
  They are lock discipline, not invocation.
- **`analyst.build_argv`, `worker.build_argv`, `miner.build_reader_argv`**
  keep their signatures and bodies. The seam calls them; it does not
  absorb them.
- **Every settings writer** keeps its body, **byte for byte, pinned by
  sha256**. They are Witness B; rewriting them to derive from
  `Containment` would collapse the witnesses into one and destroy the
  property this unit exists to establish. This is `HY3`, and it is the
  single most important "do not" in the document. r1 guarded it by
  substring (*"contains no reference to `Containment`"*), which a helper
  with a different name walks straight past — `M34` is that mutation.
  r2's `HY3` stores a **sha256 of each function's source** instead, so
  *any* edit reddens and the guard cannot be routed around by naming.

---

## 4. Acceptance criteria

**These criteria are the spec.** Each is a named test in
`plugins/self-learn/cli/tests/test_invocation.py` unless it says
otherwise. **57 criteria**, in nine groups: `SU` 5, `CN` 10, `AV` 4,
`LG` 7, `TR` 7, `RG` 8, `FK` 4, `WR` 7, `HY` 5.

### SU — the suite (the headline)

- **`SU1`** The CLI suite at `plugins/self-learn/cli` collects **1651**
  tests and reports **1646 passed, 5 skipped, 0 failed** — the `83d05c6`
  baseline (`B-8`) — *plus* the new tests in `test_invocation.py`. A
  collected count below 1651, or any failure, fails this criterion. The
  five skips are the four `test_lock_invariant.py` *"not a
  ledger-mutating surface"* skips and `test_regime_fixes.py`'s *"repo-root
  suite absent"*; a sixth skip fails this criterion too.
- **`SU2`** `git diff --name-only <base>..HEAD -- plugins/self-learn/cli/tests/`
  names **exactly one** path: `plugins/self-learn/cli/tests/test_invocation.py`.
  *Instrument criterion — satisfied by the command's output in the build
  report, not by a test function.*
- **`SU3`** The **125** tests whose pytest fixture closure contains a
  `claude_shim` fixture pass unmodified. **Total**, reproduced with
  `uv run pytest --fixtures-per-test --color=no -q | grep -cE "^claude_shim -- "`
  from `plugins/self-learn/cli`. **Per-module distribution** is obtained
  by re-running the same command with the module appended as a path
  argument (`… -q tests/test_worker.py | grep -cE …`), once per module —
  *not* by parsing the combined output, whose per-test blocks do not
  carry the owning module. At base: `test_worker.py` 32, `test_repair.py`
  45, `test_attrib.py` 32, `test_route_cli.py` 16, everything else 0
  (notably `test_composer.py` 0 — its shims are inline, not
  fixture-backed). A count other than 125 means a test was added, removed
  or re-fixtured — investigate before proceeding. *Instrument criterion.*
- **`SU4`** The **7** `test_miner.py` tests that monkeypatch
  `_invoke_reader` by attribute pass unchanged, and the **2** that call it
  directly through a PATH shim
  (`test_reader_survives_oversize_prompt`, `test_artifact_contract_sweeps_strays`)
  pass unchanged. A test asserts `miner._invoke_reader` is still a
  module-level function whose **positional** parameters are exactly
  `("home", "prompt")` — the arity the three named two-positional shims
  of `B-5` require — and that any parameter beyond them is keyword-only
  with a default.
- **`SU5`** The UI suite is untouched: `git diff --name-only` names no
  path under `plugins/self-learn/ui/`. *Instrument criterion.*

### CN — containment

- **`CN1`** For each of the four containments, every rendered rule starts
  with the literal `Edit(//` — double slash. Asserted on the rendered
  strings, not on a variable. **Guarded by a non-emptiness assertion
  first**: for the three surfaces that have rules, `len(rules) >= 1` is
  asserted *before* the universal, because "every element starts with X"
  is vacuously true of `[]` and would pass a build that rendered nothing
  at all. The analyst's empty case is `CN3`'s business, not this one's.
- **`CN2`** — **restated in r2 to observe the CALL SITE, not
  `containment_for`'s own defaults.** r1 called `containment_for` in the
  test and compared the result to the constants — which proves only that
  the function's defaults match, and stays green if every call site
  passes something else. r2 captures the **real** `SessionSpec` (the
  `CN8` spy on `write_session`/`text_session`) from three real
  invocations — a shimmed `worker.run`, a shimmed `miner.run`, a shimmed
  `analyst.analyze` — and asserts on what the call sites actually sent:

  | Captured surface | Assertions |
  |---|---|
  | `worker`, `worker-repair` | `spec.containment.allowed_tools == worker.ALLOWED_TOOLS`; `... .disallowed_tools == worker.DISALLOWED_TOOLS` |
  | `miner-reader` | `... .allowed_tools is None`; `... .disallowed_tools == miner.READER_DISALLOWED_TOOLS` |
  | `analyst` | `... .allowed_tools == analyst.ANALYST_ALLOWED_TOOLS`; `... .disallowed_tools is None` |

  `strict_mcp` is asserted the same way (`True`, `True`, `False`,
  `False`). This is the `C-c1` table, checked where it can fail.
- **`CN3`** The analyst containment has `disallowed_tools is None`,
  `write_globs == ()`, `write_exact == ()`, `strict_mcp is False`,
  `default_mode is None`, and `containment_rules(...) == []`.
- **`CN4`** `containment_rules` sorts `write_exact` and does **not** sort
  `write_globs`: given a repair set in reverse-sorted order the rendered
  rules come back sorted; given the worker's three fallback globs the
  rendered rules come back in `skills`, `projects`, `user` order,
  identical to `worker.write_permission_rules`'s return.
- **`CN5`** `containment_permissions` **omits** the `defaultMode` key
  when `default_mode is None`, and emits `"defaultMode": "default"` when
  it is `"default"`. `"defaultMode" in perms` is asserted both ways.
- **`CN6`** Witnesses A and B agree, **statically**, for all four
  surfaces:
  `containment_permissions(containment_for(s, ...)) == json.loads(SETTINGS_WITNESS[s](...).read_text())["permissions"]`
  for the three that have a witness; the analyst leg asserts
  `SETTINGS_WITNESS["analyst"] is None`, `containment_rules == []`, and
  `"--settings" not in analyst.build_argv(...)`.

  **The repair leg supplies its `write_exact` REVERSE-SORTED.** Both
  witnesses sort internally (`containment_rules` at render,
  `write_repair_settings_file` via `sorted(paths)`), so a leg fed an
  already-sorted set agrees whether or not either sort survives — and
  `M10`'s credit against `CN6` would be dishonest. Feeding the reverse
  order makes the leg discriminate: drop either sort and the two rule
  lists differ in order.
- **`CN7`** `CN6`'s worker leg runs over all four combinations of
  `SELF_LEARN_STAGE ∈ {unset, "0"}` × `SELF_LEARN_ENFORCE_SCOPE ∈ {unset, "0"}`,
  and its repair leg over both `SELF_LEARN_ENFORCE_SCOPE` values.
- **`CN8`** Twin witnesses agree at **runtime** on a real shimmed worker
  run — **and the run must produce a REPAIR round, so both invocations
  are checked.** r1 drove a plain happy-path run, which exercises the
  batch invocation only; the repair surface — the one whose containment
  is a *narrowed exact-path set* and therefore the one most likely to be
  mismatched — went unobserved, and `M3` (repair given the batch settings
  path) would have slipped through. r2's `CN8`:

  1. Seeds a batch whose shimmed output is refused for a repairable
     reason, so `run()` reaches `write_repair_settings_file` (the same
     construction `test_repair.py`'s repair-round tests use).
  2. Spies on `write_session`, recording `(spec, argv)` for **every**
     call. Asserts exactly two calls, with surfaces `"worker"` then
     `"worker-repair"`.
  3. For **each** captured invocation independently: reads that
     invocation's **own** `--settings` value out of **its own** captured
     argv, loads that file, and asserts
     `containment_permissions(spec.containment) == permissions`.

  A build that hands the repair round the batch settings path fails at
  step 3 for the second invocation, because the batch file's one stage
  glob does not equal the repair containment's exact-path rules.
- **`CN9` — the DIRECTION guard (`C-c`), as a ONE-HOP LOCAL TAINT check.**
  r2 asserted only that no *argument expression* to `containment_for(...)`
  / `Containment(...)` is a `Call` to one of the five forbidden names.
  That form is defeated by a two-line variable:

  ```python
  globs = worker.write_permission_rules(home)          # r2's CN9 sees nothing
  containment_for(..., write_globs=tuple(globs), ...)  # argument is a Name/Call to tuple
  ```

  r3's form, AST-only, no runtime tracing, per function:

  1. Within each function that calls `containment_for` or `Containment`,
     collect the set **T** of assignment targets whose value expression
     contains a `Call` to `write_permission_rules`,
     `stage_permission_rules`, `write_settings_file`,
     `write_repair_settings_file` or `write_reader_settings`.
  2. Assert that no name in **T** appears anywhere inside any argument
     expression of a `containment_for` / `Containment` call in that same
     function — nor is any of the five called directly in one.

  **One hop, deliberately.** A general taint analysis is not written
  here: `ast` gives no scope resolution, and each further hop multiplies
  false positives faster than it catches real collapses. One hop covers
  the realistic accident (assign, then pass) and the review of §3.9's
  three short call sites covers the rest.

  **Explicitly NOT widened to "the enclosing function may not call the
  five at all."** That form would be a false positive on `run()`, which
  legitimately contains **both** `containment_for(...)` **and**
  `argv = build_argv(home, write_settings_file(home))` — the settings
  file still has to be written, by the same function, on the same run
  (`W-a`, `W-a1`). A guard that forbids the co-occurrence forbids the
  design.

  Scanned files: `worker.py`, `miner.py`, `analyst.py` **and
  `test_invocation.py` itself** — specifically its `CN6` and `CN7` legs,
  because the collapse is just as fatal when it happens in the test meant
  to detect it. Without `CN9`, Witness A can be computed from Witness B
  and `CN6` compares a value with itself. Mutations `M31` (direct) and
  `M31b` (via variable) are the negative controls.
- **`CN10` — argv as the THIRD witness (`TW`/Witness C).** For each
  surface, from the argv captured in `CN2`'s real invocations:

  | Field | Argv assertion |
  |---|---|
  | `allowed_tools` | `--allowedTools`'s value `== containment.allowed_tools`; the flag is **absent from argv iff** `allowed_tools is None` |
  | `disallowed_tools` | `--disallowedTools`'s value `== containment.disallowed_tools`; **absent iff** `None` |
  | `strict_mcp` | `--strict-mcp-config` present **iff** `strict_mcp is True` |

  The `iff` in each row is asserted in both directions, so a build that
  emits a flag the containment says is absent fails as loudly as one that
  omits a flag the containment says is present. These three fields have
  **no settings-file counterpart**, so before `CN10` they were witnessed
  only by the thing that produced them. Mutations `M32`, `M33`.

### AV — argv identity

- **`AV1`** For each surface, the argv `CliBackend` hands `subprocess`
  equals the surface's own builder's output for the same inputs:
  `worker.build_argv(home, settings)`, `miner.build_reader_argv(settings)`,
  `analyst.build_argv(prompt, doctrine_text, model)`. Captured from a
  spy on the transport, compared element-for-element, and the comparison
  operand is **recomputed** in the test rather than reused from the
  closure — otherwise the criterion is vacuously true.
- **`AV2`** The worker's argv still ends with `--strict-mcp-config`, still
  contains no `--mcp-config`, and still does not contain the prompt.
- **`AV3`** `cli_settings_writer` is called **before** `cli_argv_builder`,
  and its return value is the argument `cli_argv_builder` receives.
  Asserted on the miner surface (the one that supplies both) with an
  order-recording pair of closures.
- **`AV4`** The analyst's prompt is in **argv**, not stdin: the captured
  transport call has `input` absent from its kwargs and the prompt
  present in `argv`. The inverse for both worker surfaces and the miner:
  prompt present in `input=`/`communicate(...)`, absent from argv.

### LG — log bytes

- **`LG1`** Every non-`None` `exited` / `timed_out` / `not_found` /
  `os_error` template renders **byte-identically** to the shipped string
  for a fixed input, **on the worker, repair and miner surfaces — their
  twelve. The analyst's are pinned by `WR6`**, because on that surface
  the bytes surface as exception text rather than log lines and are
  asserted where they are raised. Twelve assertions: worker batch ×4,
  worker repair ×4, miner ×4. The expected strings are written as
  literals in the test, not derived from `LOG_TEMPLATES` (deriving them
  would make the criterion self-fulfilling). Sample expectations
  (**illustrations of the shape, not the binding statement — `L-0`**):
  `"run: claude exited 7: boom"`, `"run: repair claude exited 7: boom"`,
  `"run: claude timed out after 1800s"` (worker, `timeout=1800.0`),
  `"run: repair claude timed out after 600s"`,
  `"run: claude CLI not found on PATH"`,
  `"run: repair claude invocation failed (nope)"`,
  `"run: reader invocation failed (nope)"`.
- **`LG2`** The `repair ` label appears in the repair surface's four
  lines and in none of the batch surface's.
- **`LG3`** Three legs, each discriminating a different single edit
  (`L-c`'s table):
  - **`LG3a`** worker, `timeout=1800.0`, `timeout_display=None` → the
    line is `"run: claude timed out after 1800s"`. A `:g`-dropping mutant
    renders `1800.0s` (`M12`).
  - **`LG3b`** miner, `timeout_display=900.0` (float) → the line is
    `"run: claude timed out after 900.0s"`. A build that adds `:g` to the
    miner template renders `900s`.
  - **`LG3c`** miner, `timeout=900.0` **and** `timeout_display=900` (int)
    → the line is `"run: claude timed out after 900s"`. A build that
    renders `spec.timeout` and ignores `timeout_display` renders
    `900.0s` (`M35`). **This is the leg that proves the field is read at
    all**; without it `timeout_display` is unfalsifiable.
- **`LG4`** `spec.timeout` for the miner surface reads
  `miner.INVOKE_TIMEOUT_SECS` at call time: monkeypatching the module
  attribute changes both the value handed to the transport and the value
  rendered.
- **`LG5`** Detail rendering per surface: with `stdout="OUT"`,
  `stderr="ERR"`, the worker and analyst render `ERR`; with
  `stderr=""` they render `OUT`. With a 600-character detail the worker
  and miner lines carry exactly 400 characters of it and the analyst's
  carries all 600. With a detail padded by whitespace the analyst's is
  stripped and the worker's and miner's are not.
- **`LG6`** A clean invocation (`rc == 0`) writes **nothing** through
  `spec.log` on any surface.
- **`LG7`** An analyst invocation grows neither `worker.log` nor
  `miner.log`, on the success path and on every failure path.

### TR — transport

- **`TR1`** The two worker surfaces and the analyst reach
  `subprocess.run`; the miner reaches `subprocess.Popen`. Asserted by
  patching both on the `subprocess` module and recording which fired.
- **`TR2`** The miner's `Popen` kwargs include
  `start_new_session=True`, `stdin=PIPE`, `stdout=PIPE`,
  `stderr=STDOUT`, `text=True`.
- **`TR3`** On a miner timeout, `os.killpg` is called with the process's
  own pid and `signal.SIGKILL`, `ProcessLookupError` and
  `PermissionError` from it are swallowed, and `proc.wait()` is called
  afterwards. Three separate assertions.
- **`TR4`** A bare `OSError` (not `FileNotFoundError`) raised by the
  transport **escapes** `analyst.analyze` as an `OSError` — it is *not*
  converted to `AnalystError`. On the worker and miner surfaces the same
  exception is caught and rendered through the `os_error` template. The
  analyst leg carries an inline comment naming this as preserved defect
  `R-1`, so a future reader does not "fix" the test.
- **`TR5`** Every surface's transport call receives `cwd=str(spec.cwd)`.
- **`TR6`** `argv` is passed **positionally** to `subprocess.run` and
  `subprocess.Popen`, and `timeout` as a keyword — the shape
  `test_e1`'s `fake_run(argv, **kwargs)` requires (`B-3`).
- **`TR7`** `invocation/cli.py` calls through the `subprocess` **module
  attribute**: patching `subprocess.run` after import intercepts the
  call. Asserted directly (patch, invoke, observe), which is the same
  mechanism `test_e1` relies on.

### RG — registry

- **`RG1`** The five-rung precedence table resolves correctly for each
  rung in isolation, for all four surfaces.
- **`RG2`** Each rung shadows every rung below it: five stacked cases,
  each setting two or more rungs to conflicting values and asserting the
  higher one wins. Includes the surface→selector mapping —
  `SELF_LEARN_BACKEND_WORKER` governs `worker-repair`, and
  `SELF_LEARN_BACKEND_MINER` does **not**.
- **`RG3`** An unknown value at each of the four configurable rungs
  yields the `cli` backend **and** the rung's byte-exact stderr warning
  (§3.7.2's two spellings). It does **not** fall through to the next
  rung: with `SELF_LEARN_BACKEND=bogus` and `config.yaml` naming `sdk`,
  the result is `cli`.
- **`RG4`** `SELF_LEARN_BACKEND=sdk` makes `backend_for` raise
  `BackendUnavailable` whose `str()` contains the exact substring
  `pip install 'self-learn-cli[sdk]'`.
- **`RG5`** With `SELF_LEARN_BACKEND=sdk`: `write_session` returns
  `Outcome(ok=False, failure="unavailable")` **without raising** and logs
  the surface's `unavailable` template — which is **not** any of the four
  other templates, asserted by substring-absence of
  `"CLI not found on PATH"`. `text_session` likewise returns rather than
  raises, and `analyst.analyze` converts it to `AnalystError`. A shimmed
  `worker.run` under `SELF_LEARN_BACKEND=sdk` completes and reports the
  same status a missing-CLI run reports.

  **Unknown-surface leg (`S-c`).** A `SessionSpec` carrying
  `surface="nope"` returns `Outcome(ok=False, failure="unavailable")`
  from both entry points and **never** raises `KeyError` — asserted with
  `pytest.raises` inverted (`try/except KeyError: pytest.fail(...)`), not
  merely by checking the return, because a `KeyError` from a
  `LOG_TEMPLATES["nope"]` lookup is the specific failure this leg exists
  to exclude. Nothing is logged on this path (no template set exists to
  render).
- **`RG6`** An **empty-string** value at any rung falls through silently:
  no warning on stderr, next rung consulted.
- **`RG7`** `config.invocation_backend` follows `one_motion_enabled`'s
  discipline across every row of §3.7.3's table: missing file → `None`
  silent; **empty file (YAML loads to `None`) → `None` silent**;
  unparseable → `_warn` + `None`; non-mapping top level → `_warn` +
  `None`; absent `invocation` section → `None` silent; non-mapping
  `invocation` section → `_warn` + `None`; non-string value → `_warn` +
  `None`. It does **not** reject an unknown-but-string backend name — the
  registry does. Two further assertions: `"invocation_backend" in
  config.__all__`, and `registry.py`'s config-flavored warning is emitted
  **through `config._warn`** (`R-c`) — asserted by monkeypatching
  `config._warn` and requiring it to have been called, so a duplicated
  prefix literal in `registry.py` fails even though the bytes match.
- **`RG8`** `pyproject.toml` declares `[project.optional-dependencies]`
  with an `sdk` extra, and the extra's requirement string matches the UI
  package's `claude-agent-sdk` pin character-for-character.

### FK — the fake

- **`FK1`** `FakeBackend` records specs, prompts and argvs in call order,
  and the recorded argv equals the spec's own builder's output.
- **`FK2`** Each `FakeStep` produces the documented `Outcome` **and**
  renders the same log line `CliBackend` would for that failure — asserted
  by driving both backends with the same spec and comparing the captured
  log text.
- **`FK3`** `SELF_LEARN_BACKEND=fake` resolves to the **cli** backend
  with the unknown-value warning; `"fake"` is not in `KNOWN_BACKENDS`;
  `backend_for` never returns a `FakeBackend` under any environment.
- **`FK4`** `Writes({...})` actually creates the files, so a worker-shaped
  test can drive the harvest path with no process anywhere.

### WR — wiring

- **`WR1`** `worker._invoke_claude` still returns `None`, still never
  raises for any `FAILURE_KINDS` member, and its first four parameters
  are still positional in the order `argv, prompt, timeout, home` with
  `label` keyword-only. Asserted by `inspect.signature`.
- **`WR2`** On a miner timeout / not-found / os-error / unavailable,
  `_invoke_reader` returns `None` **and the stray sweep has not run** — a
  stray file placed in the spool beforehand still exists afterwards.
- **`WR3`** On a miner `rc != 0`, `_invoke_reader` does **not** return
  early: the stray sweep runs and `out_path` is returned when it exists.
- **`WR4`** `Outcome.stdout` is `""` on both worker surfaces even when
  the process wrote to stdout, and carries the merged stream on the miner
  and `proc.stdout` on the analyst.
- **`WR5`** The `AnalystError`s raised for `not-found` and `timeout`
  carry a `__cause__` — the original exception, threaded through
  `Outcome.exc`.
- **`WR6`** `analyst.analyze`'s five failure mappings produce the exact
  `AnalystError` messages of §3.9.3's table, byte-compared against
  literals, **and every one of them is rendered through
  `LOG_TEMPLATES["analyst"]`** (`W-h`) — asserted by monkeypatching the
  template set and requiring the raised message to change, so a build
  carrying its own copies of the f-strings fails even though the default
  bytes match. Four rows are labeled **shipped** (byte-identical to
  master: `not_found`, `timed_out`, `exited`, and the `None`
  fall-through). The fifth, `unavailable`, is labeled **new** — there is
  no pre-U-seam behavior for it to match, because `BackendUnavailable`
  did not exist; its literal is `W-i`'s two-line string, quoted verbatim
  in the assertion.
- **`WR7`** The three call sites are the **only** users of the seam:
  a source scan of `src/self_learn/` finds `write_session(` and
  `text_session(` called from `worker.py`, `miner.py` and `analyst.py`
  and nowhere else. **The scan carries an explicit exclusion list**, not
  an implicit one: `worker._spawn_window`, `worker._digest`,
  `worker._notify`, `worker._notify_with_ids`, `miner._spawn_run`, and
  every `subprocess` site in `gitops.py`, `hosts.py`, `ledger.py`,
  `ledger_ops.py`, `chezmoi.py` and `hook_compiler.py` are named in the
  test as **deliberately outside the seam** (§7.1). An exclusion list
  that is written down can be reviewed; one that is implied by a regex
  cannot, and the next unit that adds a spawn site will otherwise not
  know whether it was considered or merely missed.

### HY — hygiene

- **`HY1`** `test_invocation.py` contains no line matching
  `\[\s*"claude"\s*\]` that does not also contain
  `worker._invoke_claude(` — i.e. `test_attrib.py::test_hy1_...` stays
  green (`B-1`). Asserted here as well as there, so the constraint is
  visible in the file it constrains.
- **`HY2`** No module under `invocation/` imports `worker`, `miner`,
  `analyst`, `verbs`, `teach` or `ledger_ops`. AST scan of the package.
- **`HY3` — Witness B is sha-pinned, not substring-guarded.** For each of
  the five writer functions — `worker.write_settings_file`,
  `worker.write_repair_settings_file`, `worker.write_permission_rules`,
  `worker.stage_permission_rules`, `miner.write_reader_settings` — the
  test stores a **`sha256(inspect.getsource(fn).encode("utf-8"))` hex
  literal** and asserts equality.

  **Provenance of the five shas is itself verifiable**, which a bare
  literal is not — a wrong sha copied from an already-modified working
  tree would pin the mutation instead of the baseline. Two obligations:

  - The shas are taken from the **base commit's** bytes, extracted with
    `git show 83d05c6:plugins/self-learn/cli/src/self_learn/worker.py`
    and `git show 83d05c6:plugins/self-learn/cli/src/self_learn/miner.py`
    — never from the working tree.
  - **The build report must carry
    `git diff 83d05c6..HEAD -- plugins/self-learn/cli/src/self_learn/worker.py plugins/self-learn/cli/src/self_learn/miner.py`**,
    showing that no hunk touches the five functions' line ranges. The sha
    proves the bytes match *something*; the diff proves that something is
    the baseline. Both, or neither is evidence.

  r1 guarded this by substring (*"contains no reference to
  `Containment`, `containment_rules` or `invocation`"*), which any
  differently-named helper walks straight past: a builder who adds
  `def _rules_for(home)` to `worker.py` and calls it from
  `write_settings_file` collapses the witnesses while every substring
  stays absent. That is `M34`. A sha cannot be routed around by naming.

  The cost is a criterion that reddens on an innocent docstring typo
  fix. That is the correct trade here and the failure message says so:
  *"Witness B changed. If this was deliberate, U-seam is the wrong unit
  for it — see §3.11."* An over-sensitive guard on the one property the
  unit exists to establish is cheap; an under-sensitive one is the whole
  loss.
- **`HY4`** `test_lock_invariant.py`'s `NOT_REPO_TRUTH` is unchanged, and
  no function in `invocation/` writes to the filesystem (AST scan for
  `open(`, `.write_text(`, `.mkdir(`, `.unlink(`, `.touch(`), with
  `FakeBackend`'s `Writes` step the single declared exception, named in
  the assertion message. **This is a NEW guard covering a real gap**, not
  a restatement: the shipped census is root-level-only and cannot see
  inside `invocation/` at all (`B-6`).
- **`HY5`** pyright is clean over the new package. The command is the
  project's own, from `CONTRIBUTING.md:74`, run from
  `plugins/self-learn/cli/` and path-scoped to the package:

  ```
  pyright --pythonpath .venv/bin/python src/self_learn/invocation
  ```

  "Clean" means **0 errors** over that path. It is scoped rather than run
  over `src` because a whole-`src` run cannot distinguish this unit's
  errors from the rest of the tree's pre-existing ones — so it would
  report "unchanged" whether or not the new package type-checks. The
  `10-surface-build-plan.md:1167` figure of 56 (master @ `d0efd44`) has
  drifted since; the gate's own sweep, run at this unit's actual base
  (`83d05c6`), measured **50** whole-`src` errors. F6 (fold round)
  replaces the stale fixed baseline with a **delta** form: the
  requirement is **delta = 0** against the base-commit whole-`src` count,
  not against either fixed number. The build report records both: the
  scoped run's 0, and the whole-`src` run's total, with the delta against
  base `83d05c6` (50) called out explicitly.
  *Instrument criterion — satisfied by the runs recorded in the build
  report.*

---

## 5. Mutation plan

**39 mutations** (`M1`–`M37`, plus `M4b` and `M31b`). Every mutation is
applied to the
**built** code, the suite is run, and the named criterion must **redden**. A mutation that leaves the suite green is
a hole in §4 and must be closed before the gate, not explained away.

| # | Mutation | Must redden |
|---|---|---|
| `M1` | `Edit(/{p})` → `Edit({p})` (single slash) | `CN1`, `CN6` |
| `M2` | Drop `--strict-mcp-config` from the worker's argv | `AV2`, `CN10`, and `test_worker.py::test_run_argv_pins` (shipped). **`AV1` is NOT credited** — it recomputes its comparison operand from the same (now-equally-mutated) builder, so it is structurally blind to a change made INSIDE the builder itself; gate-measured |
| `M3` | Worker repair passes the **batch** settings path (`worker.settings.json`) instead of `worker.repair.settings.json` | `CN8` (the repair-producing run's **second** invocation), and `test_repair.py::test_f2_both_invocations_share_one_argv_builder` (shipped). **`CN6` is NOT credited** — it is static and per-surface, so it never observes which path a *call site* handed to which invocation |
| `M4` | Miner transport `Popen` → `run` (loses the process group and the killpg) | `TR1`, `TR2`, `TR3` |
| `M4b` | **Worker** transport `run` → `Popen` | `TR1`, `TR6`, and `test_repair.py::test_e1_timeouts_read_not_hardcoded` (shipped — its `fake_run` is installed on `subprocess.run` and would simply never fire, so `captured["timeout"]` stays unset and the assertion `KeyError`s). **`test_batch_fixes.py`'s `Popen` fake is NOT credited** — it lives in a test that drives `_spawn_window` directly and never reaches a model invocation (`B-7`) |
| `M5` | Drop `start_new_session=True` from the miner's `Popen` | `TR2` |
| `M6` | Detail inversion: `proc.stdout or proc.stderr` instead of `proc.stderr or proc.stdout` | `LG5` |
| `M7` | `detail_cap` 400 → 200 on the worker; `None` → 400 on the analyst | `LG5`. **`WR6` is NOT credited** — gate-measured: only `LG5` reddened |
| `M8` | Precedence chain reorder: `SELF_LEARN_BACKEND` consulted before `SELF_LEARN_BACKEND_<SELECTOR>` | `RG2` |
| `M9` | `worker._invoke_claude` re-raises the backend's failure instead of logging | `WR1`, `RG5`, and every shipped worker test that survives a failing invocation |
| `M10` | Drop `sorted(...)` from `write_exact`'s rendering | `CN4`, `CN6` |
| `M11` | Registry falls **open**: an unknown value resolves to `sdk` | `RG3` |
| `M12` | Drop `:g` from the worker's `timed_out` template | `LG1`, `LG3` |
| `M13` | Drop the `{label}` interpolation (both worker rounds log identically) | `LG1`, `LG2`, and `test_repair.py`'s `"run: repair claude exited 7:"` assertions (shipped) |
| `M14` | `containment_permissions` always emits `defaultMode` (even when `None`) | `CN5`, `CN7`. **`CN6` is NOT credited** — gate-measured: only `CN5` and `CN7` reddened |
| `M15` | Drop `.strip()` from the analyst's detail rendering | `LG5`, `WR6` |
| `M16` | Analyst prompt moved from argv to `input=` (stdin) | `AV4`, and `test_route_cli.py`'s argv-reading analyst tests (shipped). **`AV1` is NOT credited** — it recomputes its comparison operand from the same (now-equally-mutated) builder, so it is structurally blind to a change made INSIDE the builder itself; gate-measured |
| `M17` | Miner returns `None` on `rc != 0` (short-circuits like a timeout) | `WR3`. **`test_miner.py`'s reader tests are NOT credited** — gate-measured: only `WR3` reddened |
| `M18` | Stray sweep moved **above** the failure dispatch | `WR2` |
| `M19` | Drop `cwd=str(spec.cwd)` from one surface | `TR5`, and `test_route_cli.py::test_analyst_analyze_runs_in_ledger_home` (shipped — the shim records its resolved cwd via `pwd -P` into `CLAUDE_SHIM_CWD`, and the test `chdir`s elsewhere first as its own control). **`test_analyst_analyze_bad_home_refuses_pre_spawn` is NOT credited** — it refuses **pre-spawn**, so no process ever runs and it observes no cwd at all |
| `M20` | `worker-repair` mapped to the `MINER` selector | `RG2` |
| `M21` | `"fake"` added to `KNOWN_BACKENDS` and wired in `backend_for` | `FK3` |
| `M22` | Miner's `os_error` template set to the worker's wording (`claude invocation failed`) | `LG1` |
| `M23` | Drop `proc.wait()` after the miner's `killpg` | `TR3` |
| `M24` | Add an `OSError` leg to the analyst surface (converting to `AnalystError`) | `TR4` |
| `M25` | `containment_for("analyst")` filled in by analogy with the worker (`disallowed_tools` set, `strict_mcp=True`) | `CN2`, `CN3`, `CN10`. **`CN6` is NOT credited** — it is structurally blind to this: its analyst leg checks only the `None` witness, empty rules, and the absence of `--settings`, and **neither `disallowed_tools` nor `strict_mcp` appears in any of those three**. `CN10` is what sees both fields, via argv |
| `M26` | `CliBackend` imports `run` directly (`from subprocess import run`) | `TR7`, and `test_repair.py::test_e1` (shipped) |
| `M27` | `subprocess.run(args=argv, ...)` (argv by keyword) | `TR6`, and `test_repair.py::test_e1` (shipped) |
| `M28` | `cli_argv_builder` called **before** `cli_settings_writer` | `AV3` |
| `M29` | `write_session` re-raises `BackendUnavailable` instead of returning | `RG5` (four legs), `WR2`, `WR6`. **`WR1` is NOT credited** — gate-measured: `RG5`×4, `WR2`, and `WR6` reddened, not `WR1` |
| `M30` | Settings writers rewritten to derive from `Containment` (the witnesses collapsed into one) | `HY3` — and note that **no other criterion catches this**, which is precisely why `HY3` exists |
| `M31` | **The batch call site passes `write_permission_rules(home)` directly as the containment's `write_globs`** — Witness A computed from Witness B, in one expression | `CN9`. **Negative control, and the reason this row exists: `CN6`, `CN7` and `CN8` all stay GREEN.** They compare a value with itself and cannot fail. This mutation is the demonstration that `CN6` alone was never the guard r1 claimed it was |
| `M31b` | **The same collapse via a local variable**: `globs = worker.write_permission_rules(home)` on one line, `containment_for(..., write_globs=tuple(globs), ...)` on the next | `CN9` in its **one-hop taint** form. Row records that `CN9`'s r2 **argument-only** form stays GREEN — the argument expression is a `Call` to `tuple`, not to any forbidden name — which is why the guard was widened. Mirrors `M34`'s row: same defect, different disguise, and the r2 guard could not see it |
| `M32` | `strict_mcp` flipped to `False` on the worker containment while `build_argv` keeps emitting `--strict-mcp-config` | `CN10` (the `iff`, present-but-denied direction) |
| `M33` | Worker containment's `allowed_tools` set to `worker.DISALLOWED_TOOLS` | `CN2` (call-site capture), `CN10` (argv disagreement) |
| `M34` | `write_settings_file` rewritten to call a **new worker-local helper** (`_rules_for(home)`) that returns `containment_rules(...)` | `HY3` in its **sha** form. Row records that `HY3`'s r1 **substring** form stays GREEN — the helper's name contains none of `Containment`, `containment_rules`, `invocation` at the call line — which is why the guard was changed |
| `M35` | `timeout_display` removed; the `timed_out` template renders `spec.timeout` | `LG3c` |
| `M36` | An unknown `spec.surface` reaches `LOG_TEMPLATES[spec.surface]` **before** the `SURFACES` validation, raising `KeyError` | `RG5`'s unknown-surface leg — which is written as an inverted `pytest.raises` precisely so a `KeyError` fails loudly instead of being mistaken for the expected refusal (`S-c`) |
| `M37` | `registry.py` re-spells the config.yaml-ignored prefix as its own string literal instead of calling `config._warn` | `RG7`'s last leg. The emitted **bytes are identical**, so no byte-comparing criterion can catch it — the leg monkeypatches `config._warn` and requires it to have been called (`R-c`, `N-c`) |

**`M30` is the mutation this document is most afraid of.** It is the one
a well-meaning builder performs voluntarily, calling it deduplication. It
leaves every functional criterion green and silently destroys the only
independent check on the containment data. `HY3` is the guard; a gate
that finds `HY3` weakened should treat the unit as failed.

**`M31` and `M34` are `M30`'s two disguises, and both were green in r1.**
`M31` collapses the witnesses at the *call site* (r1 had no direction
rule, so this was not even a violation); `M34` collapses them behind an
*innocent name* (r1's substring guard could not see it). Together with
`M30` they are one defect wearing three faces, which is why r2 answers
with a direction rule (`C-c`/`CN9`), a sha (`HY3`), and a third
independent witness (`CN10`) rather than a stronger assertion of the same
comparison.

---

## 6. Builder decisions, made here rather than left open

- **`D-1`** Four surfaces, three selectors (§3.2). The repair round is not
  independently configurable.
- **`D-2`** `Containment` gets a sixth field, `default_mode` (`C-a`).
- **`D-3`** Rule rendering is one function, `containment_rules`, and the
  double slash occurs once in the package (`C-b`).
- **`D-4`** `write_exact` sorts; `write_globs` does not (`C-b`).
- **`D-5`** Log templates are a per-surface table, not four shared
  constants (`L-a`). The charter's uniform-template model is corrected by
  §8.
- **`D-6`** A fifth template, `unavailable`, is added for the registry's
  refusal — it must not borrow the CLI-not-found wording (`L-b`).
- **`D-7`** `spec.timeout_display` exists so the miner can render the raw
  module constant it renders today (`L-c`).
- **`D-8`** The unknown-value warning has two spellings, one reusing
  `config.py`'s shipped prefix and one not (§3.7.2).
- **`D-9`** An empty value is not an unknown value (`R-a`).
- **`D-10`** `config.invocation_backend` does not validate backend names;
  the registry does (§3.7.3).
- **`D-11`** The `sdk` extra is **declared** in `pyproject.toml` so the
  error message is actionable (`R-b`).
- **`D-12`** `FakeBackend` is not env-selectable (`F-c`); injection is via
  the `backend=` keyword only (`F-d`).
- **`D-13`** The witness agreement is asserted statically over a
  test-module registry, with a runtime leg (`CN8`, on a
  **repair-producing** run so both invocations are observed) closing the
  gap `B-4` forces (`TW-a`, `TW-b`).
- **`D-14`** The miner's spool `unlink` and stray sweep stay outside the
  backend because moving them **changes timeout-path behavior** — the
  shipped code returns before the sweep on a timeout (`W-c`). *(r1 gave
  the reason as `NOT_REPO_TRUTH` needing an entry; that framing was
  retired in r2 — the census cannot see the package at all, `B-6`.)*
- **`D-15`** `analyst.analyze` calls `_timeout()` once instead of twice;
  no observable byte changes (`W-g`).
- **`D-16`** The analyst's `spec.log` is a no-op, and a criterion proves
  the analyst writes to neither log file (`L-e`, `LG7`).
- **`D-17`** *(r2)* Direction is normative: `containment_for` takes
  scalars only and renders patterns from `contract.py`'s own literals
  (`C-c`), enforced by `CN9`. The r1 sentence *"derivations of the same
  inputs, never independent transcriptions"* is struck — the independent
  transcription **is** the witness.
- **`D-18`** *(r2)* A third witness, argv (`CN10`), covers
  `allowed_tools` / `disallowed_tools` / `strict_mcp`, which have no
  settings-file counterpart and were otherwise witnessed only by the
  function that produced them.
- **`D-19`** *(r2)* `HY3` is a sha256 pin, not a substring guard,
  accepting false positives on innocent edits to the five writers
  (`M34`).
- **`D-20`** *(r2)* `timeout_display` is **kept**, not deleted, and made
  falsifiable by `LG3c` + `M35`. Deleting it would couple the
  transport's timeout argument to the log's, so a later float timeout on
  the miner would silently change an operator-visible byte.
- **`D-21`** *(r2)* An unknown `spec.surface` is validated **before** any
  table lookup and returns an `Outcome`; a `KeyError` from
  `LOG_TEMPLATES[...]` is specifically excluded (`S-c`, `RG5`).
- **`D-22`** *(r2)* `registry.py` calls `config._warn` rather than
  re-spelling the operator-facing prefix (`R-c`); `_warn` stays private,
  only `invocation_backend` joins `config.__all__`.
- **`D-23`** *(r2)* `DEGRADED_WORKER_CONTAINMENT` is named for what it
  is. `run()` passes an explicit containment at **both** call sites; the
  default exists solely to keep `test_e1`'s five-argument call legal
  (`W-a`).
- **`D-24`** *(r2)* `WR7`'s exclusion list is written out by name rather
  than implied by a regex, so the next unit that adds a spawn site can
  tell whether it was considered or missed.
- **`D-25`** *(r3)* `CN9` is a **one-hop local taint** check, not an
  argument-only match and not a whole-function prohibition. The first
  misses the variable form (`M31b`); the second is a false positive on
  `run()`, which must legitimately contain both `containment_for` and
  `write_settings_file` (`W-a1`).
- **`D-26`** *(r3)* Any symbol a criterion monkeypatches is reached
  through its module at call time (`B-3a`), naming the three sites
  (`TR7`, `RG7`, `WR6`) where a `from X import y` would make the patch
  silently miss.
- **`D-27`** *(r3)* `HY3`'s shas are extracted with `git show 83d05c6:…`
  and corroborated by a `git diff` in the build report — a sha alone
  proves the bytes match *something*, not that the something is the
  baseline.

---

## 7. Out of scope, look-alikes, and residuals

### 7.1 Out-of-scope look-alikes — Popen and PATH sites this unit must not touch

Each is a process spawn that is **not** a model invocation. Located by
symbol and distinctive line:

| Site | Distinctive line | Why it stays |
|---|---|---|
| `worker._spawn_window` | `[sys.executable, "-m", "self_learn.cli", "worker", "run", "--coalesce"]` | Follow-on window machinery. Spawns *this CLI*, not a model. Carries `NO_PUSH_ENV` and `FOLLOWON_DEPTH_ENV` through the env — a concern the seam knows nothing about. |
| `miner._spawn_run` | inside the function whose docstring says *"only place an env var is legitimate (BLOCKER D)"* | The miner watchdog. Same reasoning. |
| `worker._notify` | `subprocess.run(` guarded by `shutil.which("notify-send")` | Desktop notification. `SELF_LEARN_NO_NOTIFY` and the conftest default govern it. |
| `worker._notify_with_ids` | `subprocess.Popen(` with `stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True` | `self-learn-notify` PATH resolution. Explicitly out of scope; `test_worker.py`'s `notify_shim` and the two `_path_without_real_notify_helper` tests own it. |
| `worker._digest` | `proc = subprocess.run(` in the git-digest helper | A `git` call. |
| `gitops`, `hosts`, `ledger`, `ledger_ops`, `chezmoi`, `hook_compiler` | various `subprocess.run(` | `git`, `chezmoi` and hook replay. None spawn a model. |
| `test_batch_fixes.py` | `monkeypatch.setattr(worker.subprocess, "Popen", fake_popen)` | The **window spawner** mock. It is global for the test's duration (`B-7`) and must never intercept a model invocation. |

**`O-a` — the exclusion is EXPLICIT, by name, in the test (`D-24`).**
Every row of the table above is enumerated as a named exclusion inside
`WR7`, not left to a regex to imply. A full "no other `subprocess` call
has `claude` as argv[0]" scan is **not** written, because
`worker._notify_with_ids` legitimately spawns `self-learn-notify` and the
analyst's argv is built by a function rather than a literal — such a scan
would be a fragile heuristic that fails open. What `WR7` asserts instead
is the positive fact (`write_session`/`text_session` have exactly three
callers) plus the written-down list of what was deliberately left out.
The difference matters for the *next* unit: an implied exclusion tells a
future reader nothing about whether a site was judged and kept or simply
never looked at. `WR7` plus `HY2` is the honest boundary.

### 7.2 The UI package is the Wave-1 port source and is not touched

`plugins/self-learn/ui/src/self_learn_ui/engine/` already contains the
seam this unit is building an analogue of: `base.py` defines `PaneEngine`
(*"the seam"*), `PaneEvent`, `PaneContext` and `FakeEngine`; `sdk.py`
defines `SdkPaneEngine` over `claude_agent_sdk`; `charter.py` defines
`build_can_use_tool`, the permission-surface builder.

**That code is the SOURCE Wave 1 will port from. This unit must not
touch it, import it, or refactor it toward the CLI's shapes.** The two
packages ship independently (`self-learn-cli` and `self-learn-ui` are
separate distributions with separate `pyproject.toml`s), and a shared
abstraction extracted now — before either side's requirements are
settled — would be exactly the premature unification this project has
paid for before. Criterion `SU5` enforces the no-touch; `HY2` enforces
the no-import.

The deliberate echo in naming (`Backend` ↔ `PaneEngine`,
`FakeBackend` ↔ `FakeEngine`, `Containment` ↔ `build_can_use_tool`'s
inputs) is a *reading aid* for whoever does Wave 1, not a contract.

### 7.3 Residuals this unit accepts, with owners

- **`R-1` — the analyst's missing `OSError` leg.** `analyst.analyze`
  catches `FileNotFoundError` and `subprocess.TimeoutExpired`; a bare
  `OSError` (e.g. `PermissionError` from a non-executable `claude` on
  PATH) escapes both `analyze()`'s *"Raises `AnalystError` on ANY
  failure"* contract and `teach.py`'s
  `except analyst.AnalystError` at the `proposal = analyst.analyze(home, record, project_path=project_path)`
  call site — so the record is lost to a traceback instead of captured to
  `pending/`. **Preserved byte-for-byte here** (`T-c`) and pinned by
  `TR4`. Owner: a new `FW` row, landing with this build.
- **`R-2` — the three surfaces' log wording diverges.** Documented in
  §3.6 and §8, preserved. Unifying it is operator-visible and needs its
  own unit and its own operator decision. Owner: a new `FW` row.
- **`R-3` — `CN9`'s one-hop taint scan is blind to a module-level
  collapse.** *(fold F7, gate-measured)* `CN9`'s implementation walks
  `FunctionDef`/`AsyncFunctionDef` bodies only (`D-25`) — a taint chain
  built entirely at MODULE level, outside any function (e.g. a
  module-scope assignment feeding a module-scope `containment_for(...)`
  call, both outside a `def`), never enters that walk and evades the
  scan. This is **spec-conformant**, not a bug in the shipped guard:
  `D-25` scopes `CN9` to a one-hop, PER-FUNCTION check by design, and
  every real call site in `worker.py`/`miner.py`/`analyst.py` builds its
  `SessionSpec`/`Containment` inside a function body, so the gap is
  currently unreachable from shipped code. The gate also probed the
  attribute-qualified form (`module.write_permission_rules(...)` as the
  tainted call) and confirmed `CN9` **does** catch it — only the
  module-level (no enclosing function) collapse escapes. Recorded here
  as a residual, not fixed in this fold (folding is bounded to the seven
  named items). Owner: a new `FW` row.

### 7.4 Not built, with reasons

- **No `SdkBackend`.** That is U-sdk. This unit ships the refusal.
- **No streaming, no partial output, no cost reporting.** The CLI
  surfaces do not have them; adding them here would be inventing a
  contract no backend is asked to satisfy yet.
- **No retry, no backoff.** Not shipped today on any of the three
  surfaces.
- **No unification of the four prompt composers.**
- **No `Containment` enforcement.** `Containment` is *data*. It describes
  what the settings file and argv already enforce; it enforces nothing
  itself, and criterion `HY3` keeps it that way.

### 7.5 Handed to `03-decisions.md`

- **`S-34`** — the invocation seam exists; three call sites, four
  surfaces, two operations; `write_session` never raises.
- **`S-35`** — backend selection precedence and its fail-closed rule
  (§3.7), recorded as operator-facing policy alongside `S-10`'s
  `config.yaml` entry.

---

## 8. Conflicts between the charter and current master

Flagged, not silently resolved. Each is quoted from `83d05c6`.

**`X-1` — "four log templates, byte-identical across backends" is true of
the *kinds*, not the *strings*.** The table below is **provenance, not
specification** (`L-0`): it quotes master at `83d05c6` so §3.6's
transcription can be checked against the source. **§3.6 is authoritative
for what ships.** Master:

| | worker | miner | analyst |
|---|---|---|---|
| exited | `f"run: {label}claude exited {proc.returncode}: "` `f"{(proc.stderr or proc.stdout)[:400]}"` | `f"run: claude exited {proc.returncode}: {(output or '')[:400]}"` | `f"analyst exited {proc.returncode}: {detail}"` where `detail = (proc.stderr or proc.stdout).strip()` |
| timed out | `f"run: {label}claude timed out after {timeout:g}s"` | `f"run: claude timed out after {INVOKE_TIMEOUT_SECS}s"` | `f"analyst timed out after {_timeout():g}s"` |
| not found | `f"run: {label}claude CLI not found on PATH"` | `"run: claude CLI not found on PATH"` | `"claude CLI not found on PATH"` |
| os error | `f"run: {label}claude invocation failed ({exc})"` | `f"run: reader invocation failed ({exc})"` | **absent** |

Resolved by §3.6's per-surface table. The charter's *intent* — that the
bytes are pinned and cannot drift between backends — is honored exactly;
its *assumption* that one template set covers all three is wrong.

**`X-2` — the analyst has no settings writer, and the charter's
`cli_settings_writer` therefore cannot be total.** `analyst.build_argv`
returns `["claude", "-p", prompt, "--append-system-prompt",
doctrine_text, "--model", model, "--allowedTools", ANALYST_ALLOWED_TOOLS]`
— no `--settings`, no `--disallowedTools`, no `--strict-mcp-config`.
Resolved by making the field `| None` and by giving the analyst's
twin-witness leg a different (absence-asserting) shape (`CN6`).

**`X-3` — the twin witnesses cannot both ride `SessionSpec` on the worker
surfaces.** `test_repair.py::test_e1_timeouts_read_not_hardcoded` calls
`worker._invoke_claude(["claude"], "prompt", worker.invoke_timeout_secs(), Path("/tmp"), label="")`
— a pre-built argv, positionally. The settings file is written by
`run()`, upstream. Wiring `cli_settings_writer` through on those surfaces
means moving the write into `_invoke_claude`, which edits `test_e1` and
violates the headline criterion `SU2`. Resolved by `TW-a`/`TW-b`: static
agreement over all four surfaces, plus runtime agreement on the worker
(`CN8`). **This is the one place the charter's design is not implemented
as written, and the substitute is weaker in a named, bounded way.**

**`X-4` — the analyst's prompt is in argv, not stdin.** The charter's
"prompt in, model writes files, stdout never parsed" describes the write
surfaces; the analyst is the inverse on both counts (prompt in argv,
stdout *is* the result). Already anticipated by the charter's two-operation
split; recorded here because it makes `SessionSpec.prompt` **advisory**
on the analyst surface — the closure, not the field, decides where the
prompt goes. Criterion `AV4` pins both directions.

**`X-5` — the miner's timeout is an `int` module constant, not an
env-overridable float.** `INVOKE_TIMEOUT_SECS = 15 * 60` in `miner.py`,
versus `worker.invoke_timeout_secs()` returning a float via
`_timeout_secs`. At the shipped values `{900}` and `{900:g}` render
identically, so a naive criterion cannot tell a `:g` mutant from the
shipped code. Resolved by `LG3`'s forced-float case.

**`X-6` — "the 7 test_miner `_invoke_reader` monkeypatch tests" is
exactly right, and there are 2 more that call it for real.** Counted at
base: seven `monkeypatch.setattr(miner, "_invoke_reader", ...)` sites,
plus `test_reader_survives_oversize_prompt` and
`test_artifact_contract_sweeps_strays` which call it directly through a
PATH shim. Criterion `SU4` covers all nine. Not a conflict — a completion.

---

## 9. What was executed, and against what oracle

Measurements taken while writing this spec, on `83d05c6`, in a clean
worktree. A builder who cannot reproduce these should stop.

| # | Measurement | Command | Result |
|---|---|---|---|
| `E1` | CLI suite baseline | `uv run pytest -q --color=no` in `plugins/self-learn/cli` | **1646 passed, 5 skipped**, 169.85 s. 1651 collected. |
| `E2` | UI suite size | `uv run pytest --collect-only -q --color=no` in `plugins/self-learn/ui` | **1234 collected**. Not run — this unit does not touch it. |
| `E3` | `claude_shim` fixture census | Total: `uv run pytest --fixtures-per-test --color=no -q \| grep -cE "^claude_shim -- "`. Per-module: the **same command with a single module path appended**, run once per module — the combined output's per-test blocks do not name the owning module, so the distribution cannot be derived from one run. | **125** total — `test_worker.py` 32, `test_repair.py` 45, `test_attrib.py` 32, `test_route_cli.py` 16, all others 0 (`test_composer.py` 0: its shims are inline). `--color=no` is required; without it the ANSI-wrapped lines do not match `^claude_shim -- ` and the count reads **0**, a silent false pass. |
| `E4` | `_invoke_reader` monkeypatch census | grep of `test_miner.py` | **7** `monkeypatch.setattr` sites, **2** direct calls through PATH shims. |
| `E5` | Inline `claude` shim sites | grep for a file literally named `claude` written in a test | **13** sites across 10 files; the two fixture-backed ones are `test_worker.py`'s `claude_shim` and `test_route_cli.py`'s `claude_shim`, already counted in `E3`. |
| `E6` | Model-spawn census | `grep -rn "subprocess\.\(run\|Popen\)" src/self_learn/`, then subtract the four **comment/docstring** matches named below | **24 raw matches → 4 comment lines → 20 real call sites** across 9 modules. The four comment lines, named so the subtraction is mechanical and re-checkable: `analyst.py:195` (*"subprocess.run(cwd=...) raises FileNotFoundError"*), `gitops.py:65` (*"before this, ``subprocess.run`` had no timeout"*), `gitops.py:213` (*"One git call, always bounded. ``subprocess.run`` with no timeout"*), `worker.py:784` (*"``subprocess.run(timeout=...)`` expires instantly"*). Of the 20, **3** spawn a model (`worker._invoke_claude`, `miner._invoke_reader`, `analyst.analyze`); the other **17** are §7.1's look-alikes (4 in `worker.py`, 4 in `hosts.py`, 2 each in `ledger.py`, `hook_compiler.py`, `gitops.py`, 1 each in `miner.py`, `chezmoi.py`, `ledger_ops.py`). |
| `E7` | The suite-wide argv guard is real and green | read of `test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude` | It globs `tests/*.py` and asserts `"worker._invoke_claude(" in line` for every `["claude"]` literal. `B-1` is load-bearing on the new test file. |

**Measured for r2**, re-checking the three claims r1 asserted without
measuring. All three were wrong in r1:

| # | Measurement | Command | Result |
|---|---|---|---|
| `E8` | Reach of the fail-closed lock census | `grep -n "MODULES\|glob(" tests/test_lock_invariant.py` | `MODULES = {p.stem for p in SRC.glob("*.py")}` (`:78`) and `for path in sorted(root.glob("*.py")):` (`:288`). **`glob`, not `rglob` — root-level only.** `invocation/` is invisible to the census; r1's `B-6` claimed the opposite. |
| `E9` | Enclosing test of the global `Popen` patch | read of `test_batch_fixes.py` around `monkeypatch.setattr(worker.subprocess, "Popen", fake_popen)` | It sits in `test_no_push_env_propagates_to_spawned_child`, whose body calls `worker._spawn_window(home, no_push=True)` and never `worker.run`. **No model invocation occurs in it**; r1's `M4b` coverage claim was false. |
| `E10` | Arity pinning of `_invoke_reader`'s shims | read of all seven `monkeypatch.setattr(miner, "_invoke_reader", ...)` sites | Four are `*a` lambdas; **three are named two-positional functions** — `def spy(h, prompt)`, `def fake(home, prompt)` (in `shim_reader`), `def fake(h, prompt)`. The arity is pinned **harder** than r1's `*a`-only reading claimed. |
| `E11` | pyright command and its baseline | `CONTRIBUTING.md:74`; gate fold F6 (delta form) | Command: `pyright --pythonpath .venv/bin/python src` from `plugins/self-learn/cli/`. The `10-surface-build-plan.md:1167` figure of 56 @ `d0efd44` is stale (drift since). Baseline is now the **delta** against this unit's actual base commit `83d05c6`, gate-measured at **50** whole-`src` errors. `HY5` is therefore path-scoped, since a whole-`src` run cannot separate this unit's errors from the base commit's pre-existing ones. |

**Not measured, and therefore not claimed:** that a `claude_agent_sdk`
session can reproduce any of these containments. That is U-sdk's
obligation and this unit asserts nothing about it — which is the point of
shipping the seam before the backend.

---

## 10. Revision history

| Rev | Change |
|---|---|
| r1 | Initial draft, written blind against `83d05c6`. 6 charter conflicts flagged (§8), 2 residuals accepted (§7.3). |
| r2 | r1 blind gate: **NOT SOUND — 2 BLOCKER / 6 MAJOR / 13 NOTE**. All 21 findings folded in place; per-finding disposition below. |
| r3 | r2 delta gate: **NOT SOUND — 2 MAJOR / 8 NOTE**, both r1 BLOCKERs **CLOSED**, `X-3` adjudicated **sound, conditional on MAJOR A**. All 10 findings folded. **Closed under the ratified verdict-repricing rule: this is the last spec round, and the unit is CLEARED FOR BUILD.** The **code gate downstream** verifies these folds — in particular the four mutation-table changes (`M31b`, `M36`, `M37` added; `M25` re-attributed), which are claims about what reddens and can only be settled by running them. |

Counts live in §4's header and §5's header and are not restated here —
one register per fact. **Arithmetic checked at r3** (the r2 delta
anticipated 58 criteria): scoped to §4, the total is **57** —
`SU` 5 + `CN` 10 + `AV` 4 + `LG` 7 + `TR` 7 + `RG` 8 + `FK` 4 + `WR` 7 +
`HY` 5. A whole-file grep for the criterion bullet pattern returns 58
because §2's `B-6` contains a prose bullet opening `**\`HY4\` is a NEW
guard…**`, which matches the pattern but is not a criterion. 57 is the
number.

### r2 — per-finding disposition

| Finding | Disposition |
|---|---|
| `BL-1` | `C-c` rewritten: scalars-only direction rule made normative, glob patterns rendered from `contract.py` literals, and r1's *"never independent transcriptions"* **struck** as the defect itself. New `CN9` (AST direction scan over the three modules **and** `test_invocation.py`'s own `CN6`/`CN7` legs). New `M31`, whose row records that `CN6`/`CN7`/`CN8` stay **green** under it — the negative control proving `CN6` was never the guard. |
| `BL-2` | `CN2` restated to observe the **call site** via the `CN8` spy on three real invocations, replacing r1's tautological read of `containment_for`'s own defaults. New `CN10` (argv as third witness: `--allowedTools` / `--disallowedTools` values, `--strict-mcp-config` presence, each asserted as an `iff` in both directions). New `M32`, `M33`. Analyst-row contradiction resolved in `C-c1`: **the prose was right, the `—` was wrong** — every tool string arrives as an argument on every surface, `I-a` forbids the alternative. |
| `MJ-1` | `S-b` amended verbatim: never raises **with exactly one deliberate exception** — the analyst's bare `OSError`, preserving `R-1` (`T-c`, `TR4`). |
| `MJ-2` | (a) New `W-h`: every `AnalystError` message renders through `LOG_TEMPLATES["analyst"]`, normative. (b) New `W-i`: the `unavailable` message written as a two-line byte literal. (c) `WR6` labels four rows **shipped** and the `unavailable` row **new** — there is no pre-U-seam behavior for it to match. |
| `MJ-3` | `HY3` converted to a **sha256 pin** over the five writer functions' sources, with its false-positive cost accepted explicitly and encoded in the failure message. New `M34` (helper with an innocent name), whose row records that r1's substring form stays **green**. |
| `MJ-4` | `CN8` rewritten to drive a **repair-producing** run, assert exactly two invocations with surfaces `worker` then `worker-repair`, and check each against the permissions of the file named by **its own** `--settings`. `M3` repointed to `CN8` + `test_repair.py::test_f2_both_invocations_share_one_argv_builder`; `CN6` **dropped** from that row. `W-a` rewritten: `run()` passes explicit `containment=` at both call sites, and r1's `<the batch default>` placeholder is resolved as the named `DEGRADED_WORKER_CONTAINMENT`, reachable only from `test_e1`'s five-argument call. |
| `MJ-5` | `B-6` restated as **measured** (`E8`): the census globs root-level only, so `invocation/` is invisible to it. The `unlink`/sweep stay in `_invoke_reader` because moving them changes **timeout-path behavior** (`W-c`), not because a test reddens. `HY4` re-labeled a **new** guard closing a real census gap. |
| `MJ-6` | `B-7` corrected (`E9`): the `Popen` patch lives in `test_no_push_env_propagates_to_spawned_child`, which drives `_spawn_window` only. `M4b`'s coverage repointed to `TR1`/`TR6`/`test_e1`. Files-may-touch table's pyproject citation changed `B-7` → `R-b`. |
| `N-1` | **Decision: keep `timeout_display`, make it falsifiable** (the gate's recommendation). `LG3` split into `LG3a`/`LG3b`/`LG3c`; `LG3c` drives `timeout=900.0` + `timeout_display=900` and requires `"900s"`. New `M35` removes the field. Rationale for keeping rather than deleting recorded in `L-c` and `D-20`: deleting couples the transport's argument to the log's. |
| `N-2` | **Decision: unknown surface is an `RG5` leg** (the gate's recommendation). `S-c` rewritten to validate **before** any table lookup; the leg asserts no `KeyError` escapes, via inverted `pytest.raises`, and that nothing is logged. |
| `N-3` | **Interpretation stated:** read as "the seam's exclusions must be explicit, not implied." `WR7` now carries a **written-out exclusion list by name**; `O-a` and `D-24` record why an implied exclusion is worse than a named one for the next unit. Flagged in the report as an interpretation, since the finding was terse. |
| `N-4` | `CN1` gains a non-emptiness guard asserted **before** the universal — `len(rules) >= 1` — so a build rendering nothing cannot pass vacuously. |
| `N-5` | New `L-0`: §3.6 is **authoritative** for template bytes; §8's `X-1` is **provenance**. Both sections now say so. |
| `N-6` | `E6` names all four comment-match lines with quotes. **Discrepancy flagged:** the finding says "22→20" and "the two comment-match lines"; the measured subtraction is **24 raw → 4 comment lines → 20**. r1's stated 20 was correct; the gate's arithmetic was not. `E3`/`SU3` gain the per-module method (one run per module) and a warning that omitting `--color=no` silently reads 0. |
| `N-7` | `B-5` corrected (`E10`): three **named two-positional** shims, not merely `*a`-shaped ones — a stronger constraint than r1 claimed. `SU4` restated to assert positional params are exactly `("home", "prompt")` and any addition is keyword-only. |
| `N-8` | `B-3` now quotes **both** `test_e1` call sites (`:1881`, `:1883`) and states why the second matters: it binds the **repair** surface, not just the batch one. |
| `N-9` | Resolved by `MJ-4` — `<the batch default>` is now `DEGRADED_WORKER_CONTAINMENT`, named and scoped. |
| `N-10` | **Decision: dropped** (the gate's first option). `W-a1` records that the shipped one-statement `argv = build_argv(home, write_settings_file(home))` stays whole, and that `CN8` reading `--settings` out of the captured argv is the stronger observation anyway. |
| `N-11` | `HY5` pins `pyright --pythonpath .venv/bin/python src/self_learn/invocation` from `plugins/self-learn/cli/` (`CONTRIBUTING.md:74`), defines "clean" as **0 errors**, and states path-scoping's reason as a whole-`src` run's inability to separate this unit's errors from the base commit's pre-existing ones. **Fold F6**: the stale fixed baseline of 56 (`10-surface-build-plan.md:1167` @ `d0efd44`) is replaced by a delta form — gate-measured base `83d05c6` = **50** whole-`src` errors, requirement is delta = 0 against that base. |
| `N-12` | `invocation_backend` added to `config.__all__`. **Decision: the registry CALLS `config._warn`** (the gate's recommendation) — recorded as `R-c` with the one-register rationale; `_warn` stays private. `RG7` gains the empty-file (`data is None`) row and a leg asserting `_warn` was actually called. |
| `N-13` | §10's restated counts removed; counts live only in §4's and §5's headers. |

### r3 — per-finding disposition

| Finding | Disposition |
|---|---|
| `MAJOR A` | `CN9` widened from argument-is-a-Call to a **one-hop local taint** check, AST-only, per function: collect assignment targets whose value contains a `Call` to one of the five forbidden names, then assert no such name reaches `containment_for` / `Containment` as an argument. **Explicitly NOT widened** to "the enclosing function may not call the five" — that is a false positive on `run()`, which must legitimately hold both `containment_for` and `build_argv(home, write_settings_file(home))` (`W-a1`). New **`M31b`** (the variable-indirection collapse), whose row records `CN9`'s r2 argument-only form stays **green**, mirroring `M34`. New `D-25`. |
| `MAJOR B` | `M25`'s must-redden list corrected to `CN2`, `CN3`, `CN10`; **`CN6` dropped** with the reason stated in the row — its analyst leg checks the `None` witness, empty rules and absent `--settings`, and **neither `disallowed_tools` nor `strict_mcp` appears in any of the three**, so it is structurally blind to the mutation. `CN10` is what sees both. |
| `N-a` | `M19`'s oracle renamed to `test_route_cli.py::test_analyst_analyze_runs_in_ledger_home` (verified: the shim records resolved cwd via `pwd -P` into `CLAUDE_SHIM_CWD`; the test `chdir`s elsewhere as its own control). `test_analyst_analyze_bad_home_refuses_pre_spawn` explicitly **not** credited — it refuses pre-spawn and observes no cwd. |
| `N-b` | Two mutation rows added: **`M36`** (unknown surface reaches `LOG_TEMPLATES[spec.surface]` before validation → reddens `RG5`'s unknown-surface leg) and **`M37`** (`registry.py` re-spells the config.yaml-ignored prefix instead of calling `config._warn` → reddens `RG7`'s last leg; the row notes the emitted bytes are identical, so only the call-observation leg can catch it). |
| `N-c` | New **`B-3a`**, one normative sentence generalizing `B-3`: any symbol a criterion monkeypatches must be reached through its module at call time. Three sites named in a table — `TR7` (`subprocess.run`), `RG7` (`from . import config` + `config._warn(...)`, never `from .config import _warn`), `WR6` (`LOG_TEMPLATES` read through the module, or `monkeypatch.setitem`, which works regardless because it mutates the shared dict). New `D-26`. |
| `N-d` | `HY3`'s sha provenance made verifiable: shas extracted with `git show 83d05c6:…worker.py` / `…miner.py`, **never from the working tree**, and the **build report must carry** `git diff 83d05c6..HEAD -- <those two files>` showing no hunk touches the five functions' ranges. Stated as "both, or neither is evidence" — a sha alone proves the bytes match *something*. New `D-27`. |
| `N-e` | `L-0` amended to *"no third **NORMATIVE** statement"*, with a table classifying the two derived sites: `LG1`'s samples are **illustrations**; `W-i` is a **derived composition** of §3.6's analyst template and §3.7.4's `BackendUnavailable` text, stale if either changes. |
| `N-f` | `CN6`'s repair leg now supplies `write_exact` **reverse-sorted**, with the reason in the clause: both witnesses sort internally, so a pre-sorted input agrees whether or not either sort survives, and `M10`'s `CN6` credit would be dishonest. |
| `N-g` | `D-14`'s reason updated to match §3.11 (`W-c` timeout-path behavior; the retired `NOT_REPO_TRUTH` framing marked as such). §6 re-ordered: `D-14`–`D-16` restored ahead of the r2 block `D-17`–`D-24`. |
| `N-h` | `LG1`'s scope tightened to *"the worker, repair and miner surfaces' twelve; the analyst's are pinned by `WR6`"*, with the reason — on that surface the bytes surface as exception text, not log lines. |
