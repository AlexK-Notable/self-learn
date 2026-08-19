# Spec — U-sdkw: the worker surfaces' SDK contract tests

Status: **r5 — CLEARED FOR BUILD.** Three gate rounds, 32 findings, all
folded (§10 maps each to its change). The close-out gate verified six of
seven r4 landings **by execution** — both blockers genuinely closed, the
rebased `HY5` legs satisfiable under `Par-1`'s exact recipe with `git`
intact, `M43` reddening leg 1 with everything else green, `BG3`'s
relation in-criterion with no dead literal, strict counts 46/43. One row
remained and the gate **measured the replacement**, so it folds under the
ratified **verdict-repricing rule**: this is the last spec round, and the
**code gate downstream verifies the fold** — in particular `M41`'s new
form and the three declared open items (§5.1), which are claims about
what reddens and can only be settled by running them.

**Every round found the defect in the machinery the previous round had
just added.** r1's `os-error` recipe spawned a real CLI; r3's fix for it
scrubbed `PATH` and killed `git`; r4's fix for *that* replaced a mutation
with one that deleted an assertion instead of breaking the product. The
answer each time was not a stronger assertion but a **change of what is
being policed** — from `PATH` composition to claude-resolution
(`F-c2`), and from mutating the test to mutating the thing tested
(`Mut-a`). Both are now normative rules rather than one-off repairs.

Earlier: r2 delta
gate: **NOT SOUND — 2 BLOCKER / 1 MAJOR / 4 NOTE**, all bounded, all
ratified, all folded (§10). **Eighteen of r3's 21 landings verified
clean, four by re-execution**, and `BLOCKER-2`/`MAJOR-A`/`MAJOR-C`/
`MAJOR-D` are **CLOSED**. Every remaining finding lived inside
`BLOCKER-1`'s *remedy*, not its diagnosis: the fix I wrote — scrub
`PATH` down to `tmp_path` — **cannot work**, because `worker.run()`
shells out to `git` before it ever reaches an invocation, so a scrubbed
`PATH` kills every `cli`-param criterion at setup. The remedy is
re-based from **`PATH` composition** onto **claude-resolution**
(`F-c2`): prepend freely, and guarantee that the only `claude` anyone
can resolve is the shim. `M41` is restated as the property's own mutant
and `M43` added, closing the conditional-credit instance `MAJOR-D3`
caught in my own fold. Earlier: r1 blind gate:
**NOT SOUND — 2 BLOCKER / 4 MAJOR / 15 NOTE**, every fix direction
bounded and ratified wholesale; all 21 findings folded (§10). The two
BLOCKERs were both *this document's own machinery being unsafe or
untrue*: `BLOCKER-1`'s `os-error` recipe **spawned the real CLI** on any
host that has one (`execvp` skips non-executable `PATH` entries and keeps
searching — measured, two real spawns), and `BLOCKER-2`'s `FL2`
byte-identity claim was **false for two failure kinds and structurally
impossible for a third**, one of them contradicting this spec's own
`F-c`. The answer to the first is not a better recipe but a **`cli`-side
control that did not exist** (`HY5`) — `B-2`'s tripwire is sdk-only. The
answer to the second is a scoped claim plus a **routed product finding**
(`R-10`). The gate also **broke `SU4` clause (b)** with an appended
module-level rebinding; leg 4 is the repair, and `M42` makes the evasion
permanent. Earlier: r2 folded four operator rulings (§7.6), of which
`V-2` sanctioned the additive fixture edit. **10 residuals** accepted
(§7.3), 2 findings routed to fold decisions (§7.5). Unit `U-sdkw`,
**Wave 2** of the approved Agent-SDK migration, alongside `U-sdka`
(analyst) and the miner unit.

**Base commit:** `89f8ef7` (master — the `U-fake` merge, *"Wave 1
complete"*). Every symbol quoted in this document was read at that
commit, in a clean worktree (`git status --porcelain` empty, verified
§9 `E0`). `worker.py`, `invocation/` and `invocation_sdk/` are
uncontended.

**The unit in one sentence.** Write the contract the worker's two model
invocations must satisfy **on either backend**, as tests that run twice —
once under `cli`, once under `sdk` — **without flipping the worker to
`sdk`**, so that when the flip finally happens (last, after the analyst
and miner burn-ins) it is a one-line configuration change landing on a
suite that already proved the destination.

**This unit ships no product code.** Not one line under
`plugins/self-learn/cli/src/`. The entire deliverable is one new test
module, **one sanctioned additive extension to the shipped fake CLI's
scenario table** (`V-2`, §3.10), and documentation rows. A builder who
finds themselves fixing a defect they discovered on the way has left this
unit's mandate: §7.5 is where such a finding goes, and it goes there as a
**routed fold decision**, never as a silent repair.

**Why the worker goes last, and why it therefore gets the most armor.**
The worker is the only surface that **commits to the ledger**. The
analyst produces a proposal a human reviews; the miner produces spool
files a later run reads. The worker writes proposal files that
`_install_staged` moves into the ledger under the commit lock and
`gitops` pushes. A containment defect on the analyst costs a bad
suggestion; the same defect on the worker costs a wrong byte in the
canon, pushed to a public remote, on an unattended nightly timer. That
asymmetry is the whole reason this unit exists a wave before the flip it
prepares for.

---

## Files this unit may touch

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/tests/test_worker_contract.py` | **NEW.** Every criterion in §4 lands here. The only new file. |
| `plugins/self-learn/cli/tests/fixtures/fake_claude.py` | **ADDITIVE ONLY, ruling `V-2`.** Exactly one new scenario (`ok_write_real`), its one `SCENARIOS` key, and one small invocation-counter helper (§3.10). **Insertions only; every pre-existing symbol byte-unchanged**, enforced per-function by `SU4` clause (b). |
| `docs/specs/self-learn/14-forward-work-map.md` | New `FW` rows for §7.4's list, landing in the same commit as the build. **Insertions only.** |
| `docs/specs/self-learn/drafts/u-sdkw-worker-contract-spec.md` | This document. |

**Nothing else.** Specifically:

- **No existing test file may be edited.** `tests/fixtures/fake_claude.py`
  is not a test module — it is a fixture binary the SDK spawns, it
  defines no test and no pytest fixture, and its edit is bounded to one
  enumerated additive site. Every file that *collects tests* stays
  byte-identical. That is criterion `SU2`, and `SU4` makes both halves
  mechanical: eight files sha-pinned whole, the fake pinned
  **per-function** so the addition cannot smuggle a change to anything
  that already existed.
- **No product code.** `MT-a` below is the numstat bound.
- **`tests/conftest.py` is untouched** — including the
  `_no_real_sdk_spawn_tripwire` fixture, which `HY3` both sha-pins and
  proves live.
- **`docs/specs/self-learn/03-decisions.md` gains no row.** This unit
  ratifies no new policy: it does not decide when the worker flips, it
  does not change the registry's default, and it introduces no
  operator-facing behavior. The `S-` row belongs to the flip unit, which
  is the unit that actually makes a decision. Recorded as `D-13`.

**`MT-a` — the may-touch bound, as commands with numeric answers
(NORMATIVE).** All four are run from the repo root and recorded in the
build report:

| # | Command | Required output |
|---|---|---|
| 1 | `git diff --numstat 89f8ef7..HEAD -- plugins/self-learn/cli/src/` | **empty** (zero lines) |
| 2 | `git diff --numstat 89f8ef7..HEAD -- plugins/self-learn/ui/` | **empty** (zero lines) |
| 3 | `git diff --numstat 89f8ef7..HEAD -- plugins/self-learn/cli/tests/` | **exactly two rows**, both with **deletions column `0`**: `tests/test_worker_contract.py` and `tests/fixtures/fake_claude.py` |
| 4 | `git diff --numstat 89f8ef7..HEAD -- docs/` | **exactly two rows**, both with **deletions column `0`**: `docs/specs/self-learn/14-forward-work-map.md` and this draft |

Row 3's **deletions column** is the load-bearing half, and it is what
makes `V-2`'s sanction bounded rather than open: a `0` there is the
difference between *added a scenario* and *added a scenario and rewrote
something else*. A non-zero deletions count on `fake_claude.py` fails
`SU3` **and** `SU4` clause (b), independently. Criterion `SU3`.

---

## 0. Reading order and precedence

1. **§4 (acceptance criteria) and §5 (mutation plan) ARE the spec.**
   Everything else is rationale. Where prose and a criterion disagree,
   **the criterion wins** and the prose is the defect.
2. Every set, table and name is defined **once**, in §3, and referenced
   by name thereafter. A second definition anywhere is a bug in this
   document.
3. Code is located **by symbol plus a distinctive quoted source line**,
   never by bare line number. `U-attrib`, `U-seam` and `U-sdk` each
   shifted every line in `worker.py` and will not be the last to do so.
4. Read before this document, in this order:
   `docs/specs/self-learn/drafts/u-seam-invocation-seam-spec.md` (the
   seam contract and the house style this document follows),
   `…/u-sdk-backend-spec.md` (`Charter-1`, `C-10`, `Ev-1`, `Map-1`),
   `…/u-fake-test-tiers-spec.md` (the three tiers), then `worker.py`'s
   `run()` from `argv = build_argv(home, write_settings_file(home))`
   through the repair round's `_invoke_claude(` call.
5. **This document does not restate the seam.** Where `U-seam` or
   `U-sdk` already pinned a fact, this unit **cites** it and adds only
   the worker-surface, both-backends statement that neither made.

---

## 1. Why this unit exists

### 1.1 What is true today

Both worker invocations reach the seam. `worker._invoke_claude` builds a
`SessionSpec` and calls `invocation.write_session(spec)`; the registry
resolves a backend from `SELF_LEARN_BACKEND_WORKER`, then
`SELF_LEARN_BACKEND`, then `config.yaml`, then the built-in `"cli"`.
`SdkBackend` exists, is importable, and is **inert** — nothing selects
it by default.

So a flip is already, mechanically, one environment variable. What does
not exist is any statement of **what would have to stay true across it**.
`test_worker.py` and `test_repair.py` — 108 tests between them, 119 of
whose fixture closures carry the worker `claude` shim (§9 `E3`) — are
written against a bash script on `PATH`. Every one of them is a `cli`
test wearing no label, and not one would notice if the `sdk` leg
diverged.

### 1.2 What the flip would silently change, and what nothing checks

Four things move at once when `SELF_LEARN_BACKEND_WORKER=sdk`:

| What | Under `cli` | Under `sdk` | Checked today by |
|---|---|---|---|
| The write boundary | a JSON settings file's `permissions.allow` rules, enforced by the CLI | a Python `can_use_tool` callback, enforced in-process | **nothing compares them** |
| The prompt channel | `subprocess.run(input=…)` — stdin | a JSON control message to the client | **nothing at worker scale** |
| The failure surface | `FileNotFoundError` / `TimeoutExpired` / `OSError` from `subprocess` | `CLINotFoundError` / `asyncio.TimeoutError` / `ClaudeSDKError` | `U-sdk`'s `OU` group, at hand-built specs — **never through `worker.run()`** |
| What the run leaves behind | a `worker.log` line | a `worker.log` line **plus** a `worker.tool-events.<run_id>.jsonl` | **nothing** |

The third row is the one that reads worst. `U-sdk`'s `OU3` proves
`SdkBackend` renders `LOG_TEMPLATES["worker"]` byte-identically **for a
`SessionSpec` the test built by hand**. It says nothing about the spec
`worker._invoke_claude` actually builds, nor about whether `run()`
survives a failure the same way on both legs. That gap is this unit's
subject.

### 1.3 What this unit is not

It is not the flip (§3.8, `FR3`). It is not a `U-corrob` down-payment —
tool-events are **captured and asserted present**, and building any
consumer is out of scope and guarded by `EV4`. It is not a fix for
anything it finds (§7.5). And it is not a rewrite of the shipped armor:
the 119 shim-driven tests and the 80 `test_invocation_sdk.py` tests stay
**byte-identical**, pinned by sha (`SU4`).

---

## 2. What binds this design from outside it

These are shipped, currently-green facts. Each removes an option this
unit might otherwise have taken. A builder who trips one has a red suite,
not a discussion.

**`B-1` — the suite-wide claude-argv guard.**
`test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`
reads `sorted(tests_dir.glob("*.py"))` and asserts, for every line in
every test module matching `\[\s*"claude"\s*\]`, that the line also
contains `worker._invoke_claude(`. `test_worker_contract.py` is inside
that glob. Note the pattern is **narrow**: it matches a one-element list
literal only, so `["claude", "-p", …]` — the shape `test_invocation_sdk`'s
`_worker_argv` already uses — is legal. Criterion `HY1`.

**`B-2` — the session-scoped spawn tripwire is autouse and has no
opt-out.** `tests/conftest.py::_no_real_sdk_spawn_tripwire` replaces
`claude_agent_sdk._internal.transport.subprocess_cli.SubprocessCLITransport._find_cli`
with a function that unconditionally raises. It is the only thing
standing between a `cli_path=None` and a **real, credentialed** Claude
Code session — the hazard `U-sdk`'s code gate found live. Every
sdk-driving test in this unit must set `SELF_LEARN_SDK_CLI_PATH` before
the session runs; there is no supported way to disable the tripwire, and
this unit does not add one. Criterion `HY3`.

**`B-2a` — the tripwire is SDK-ONLY, and r1 leaned on it as if it were
general (BLOCKER-1).** It patches one method on one SDK transport class.
It has **no reach into `subprocess`**, so a `cli`-leg test that resolves
and executes a real `claude` through `PATH` passes it without a murmur —
which is exactly what r1's `os-error` recipe did when the gate ran it
(`F-c1`: two real spawns, exit 1). The `cli` side needs its own control,
it did not have one, and `HY5` is it. Recorded here, at the tripwire's
definition site, so the next unit does not make the same substitution.

**`B-3` — `worker._invoke_claude`'s positional prefix is frozen, and
`test_repair.py::test_e1_timeouts_read_not_hardcoded` is why.** It calls
`worker._invoke_claude(["claude"], "prompt", worker.invoke_timeout_secs(), Path("/tmp"), label="")`
and again with `label="repair "`, passing four positionals and no
containment. Both calls must stay legal. This unit adds no parameter and
changes no signature, so `B-3` binds only in one direction: **the
containment-less call is a real, reachable shape**, and its behavior on
the `sdk` backend is a contract this unit must state rather than assume
(`DEGRADED_WORKER_CONTAINMENT` grants nothing — `HA3` leg iv).

**`B-4` — NO scenario in the fake at base performs a filesystem write,
and that is the gap ruling `V-2` closes.**
`tests/fixtures/fake_claude.py::_scenario_ok_write` requests permission
for a `Write`, emits a `tool_use` block and a `tool_result` block, and
**never touches the target path**. Read at `89f8ef7`; the function's
whole body is three `emit(...)` calls around one `_request_permission`.
No other scenario writes either. Measured consequences **at base**:

- The `sdk` leg could not land a proposal file in the stage, so a
  `worker.run()` under `sdk` reported `status == "failed"` (§9 `E5`).
- The **repair round was unreachable end-to-end under `sdk`**, because
  `_dry_check_batch` runs over `staged_paths()` and the stage is empty.
  Every probe case logged
  `run: repair round skipped (no eligible refusals)`.

r1 accepted both as residual `R-1` and wrote `RP4` as a trip-wire on the
unreachability. **The operator overruled that trade** (`V-2`): leaving
the repair round's `sdk` path untested until burn-in is the worse risk,
and the fake's armor value survives an addition that is additive and
pinned. §3.10 is the sanctioned extension; `RP4` becomes the end-to-end
`sdk` repair test rather than an assertion that one is impossible.
`B-4` survives as **provenance** — it is why §3.10 exists, and §8 row 5
still requires it to be re-read.

**`B-5` — `FAKE_CLAUDE_FORCE_SCENARIO` is the only way to pick a
scenario from a real prompt.** The fake selects on exact equality of the
first `{"type":"user"}` message's content against `SCENARIOS`' keys. A
real `compose_batch_prompt` output can never match one. The env var
overrides the match unconditionally and is read by no production code.
Every criterion in this unit that drives `worker.run()` under `sdk` sets
it. Defined once here; referenced by name thereafter.

**`B-6` — the fake echoes an unmatched prompt back verbatim.** On a
scenario miss it emits
`result_message(is_error=True, subtype="error_unknown_scenario", errors=[f"fake_claude: no such scenario {content!r}"])`,
which `Map-1` turns into `Outcome.detail = "; ".join(errors)`. **This is
the only oracle in the suite that observes a prompt after it has crossed
the SDK's process boundary**, and `BG3` is built on it. Because nothing
else pinned it, `SU4` sha-pins `fixtures/fake_claude.py` so a later edit
that truncates or drops the echo reddens here rather than silently
hollowing out `BG3`.

**`B-7` — the two `containment_for` rows the worker uses are fixed by
`contract.py`, not by the call sites.** `containment_for("worker", …)`
returns `write_globs=(f"{stage_dir}/**",)` when `stage_on`, else the
three ledger globs, with `write_exact=()`, `strict_mcp=True`, and
`default_mode="default" if enforce else None`.
`containment_for("worker-repair", …)` returns `write_globs=()`,
`write_exact=tuple(write_exact)`, `strict_mcp=True`, same
`default_mode` rule. **`worker-repair`'s write set lives entirely in
`write_exact`** — which is why any charter rule keyed on `write_globs`
alone is blind to the repair surface (`M4`, mirroring `U-sdk`'s `M62`).

**`B-8` — the baseline.** Measured on `89f8ef7` (§9 `E1`): CLI suite
**1873 collected, 1868 passed, 5 skipped, 0 failed**, 264.84 s, **rc 0**
(read unpiped). pyright whole-`src`: **50 errors** (§9 `E2`).

---

## 3. The change

### 3.1 `Mod-1` — the module, and where each tier lands (NORMATIVE)

One new file, `plugins/self-learn/cli/tests/test_worker_contract.py`. It
imports fixtures by name from their canonical homes — the house pattern,
precedent `test_attrib.py`'s and `test_invocation_sdk.py`'s own
`from test_worker import (…)` lines — and **defines no `autouse`
fixture**, for the reason `U-sdk`'s `Sim-1a` gives: importing this module
executes it at collection time in the same session as all 1868 shipped
tests. *(Gate correction, code-gate fold: r5's stated justification
claimed an `autouse` fixture here "would reach every one of them" — the
gate falsified that, positive-controlled, with `--setup-plan`: a
module-level `autouse` fixture is scoped to its own module and does NOT
reach the other 1868 shipped tests; only a `conftest.py`-level `autouse`
fixture reaches sibling modules. `Sim-1a`'s real hazard is narrower than
originally stated — an `autouse` fixture here would silently touch every
one of THIS module's own criteria through a line whose own diff looks
innocent, not the suite at large.)* The exception this rule carries — the
module's one `autouse` fixture, `_step0_real_claude_shadow` (STEP 0) —
stands: it is declared, documented, and (per the correction above)
scoped to this module alone.

| Imported from | Symbols |
|---|---|
| `test_worker.py` | `Env`, `env`, `claude_cli_shim_worker`, `seed_pending`, `shim_writes`, `PROPOSAL_YAML_TEMPLATE` |
| `test_repair.py` | `_defect_script`, `_t4_missing_target`, `_t4_target_fixed` |
| `test_invocation_sdk.py` | `sdk_cli_path`, `sdk_absent`, **`FAKE_CLI`** (the module-level `Path` to `tests/fixtures/fake_claude.py`; imported, never re-derived — a second spelling of that path is a second register, and `Par-1`'s `sdk` param and `HY2`'s scan must agree on one) |
| `backends.py` | `install_fake`, `assert_fake_was_used` |
| `shims.py` | `write_worker_claude_shim` |
| `support.py` | `make_env`, `proposal_dict` |

**`M-a`** Nothing is re-implemented that one of those already provides. A
builder who writes a second worker shim, a second ledger sandbox, or a
second proposal factory has widened the unit's surface without widening
its may-touch.

**`M-b` — tier assignment is fixed and total.** Each criterion in §4
declares its tier; there is no criterion without one.

| Tier | Mechanism | Used for |
|---|---|---|
| **T1** | `install_fake` + `FakeStep`s — in-process, no subprocess | `run()`'s **wiring**: how many invocations, in what order, with what surfaces, containments, argvs and timeouts. The only tier that can drive a real repair round under both backends' *spec shapes*, because `Writes` actually creates the staged file (`U-seam` `FK4`) |
| **T2** | the bash `claude` shim on `PATH` via `claude_cli_shim_worker` / `write_worker_claude_shim` | the `cli` leg's **transport**: stdin delivery, exit codes, timeouts, settings-file bytes |
| **T3** | the fake CLI via `SELF_LEARN_SDK_CLI_PATH`, driven by `B-5` | the `sdk` leg's **transport**: the charter, tool-events, timeouts, `Map-1` failures |

**`M-c1` — THE CAPTURE MECHANISM, defined once (MAJOR-C).** Five
criteria (`WS1`, `CN`-style containment reads, `RP1`, `HA1`, `HA4`,
`BG1`) say *"the captured `SessionSpec`"* or *"the captured options."*
r1 never named how. Normatively, there is **one** spy and it is:

```python
monkeypatch.setattr(invocation, "write_session", recording_wrapper)
```

— patched on the **package-level `self_learn.invocation.write_session`
binding**, because that is the binding `worker._invoke_claude` calls
(`spec = invocation.SessionSpec(...)` … `invocation.write_session(spec)`).
The wrapper records `(spec, spec.cli_argv_builder(None))` and then
delegates to the real function so the run proceeds.

**This is the exact MIRROR of `backends.py`'s `BK-a` trap, and getting it
backwards is silent.** `BK-a` patches `invocation.registry.backend_for`
and warns that patching the package re-export is a no-op, because
`_dispatch` reads the registry's binding. Here the direction is
**reversed**: `worker.py` reads the *package-level* binding, so patching
`invocation.registry.write_session` would be the silent no-op. A builder
who pattern-matches on `BK-a` without reading which module does the
calling will patch the wrong one, the spy will record nothing, and every
criterion that depends on it will assert over an empty list — passing
vacuously. In-suite precedent for the correct form:
`test_invocation_sdk.py`'s `write_session` spy in its worker-run leg.

**`M-c2` — the `sdk` options are read by calling the shipped
builder, not by re-deriving them.** `HA4`'s `sdk` half calls
`invocation_sdk.backend.options_kwargs(spec)` on the **captured** spec
(`U-sdk` `O-0` split `_build_options` in two precisely so the mapping is
observable). It does not construct its own `ClaudeAgentOptions` and does
not re-read the environment. Where a criterion needs the object actually
handed to the client rather than the mapping, it uses `U-sdk` `O-0a`'s
constructor spy instead, and says so.

**`M-c`** T1 is deliberately **not** parametrized over backends. It
patches `registry.backend_for` and therefore says nothing about which
backend would have been chosen — asserting a backend there would be
asserting a value the fixture itself supplied. T1's job is the
*backend-independent* half of the contract: the `SessionSpec`
`_invoke_claude` builds is complete **before** dispatch, so a spec proved
correct once is correct on both legs. `PB1`/`FR1` carry the resolution
half, separately.

### 3.2 `Par-1` — the `["cli", "sdk"]` fixture (NORMATIVE)

One `@pytest.fixture(params=["cli", "sdk"])` — call it `backend` — whose
body, per param:

| Param | Body |
|---|---|
| `"cli"` | `monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "cli")`; build the worker shim by **calling** `shims.write_worker_claude_shim(...)`; **prepend** its directory to the inherited `PATH` (`P-c1`) |
| `"sdk"` | `monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER", "sdk")`; `monkeypatch.setenv("SELF_LEARN_SDK_CLI_PATH", str(FAKE_CLI))`; `monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")` |

It yields a small record carrying the param name, the shim handles (cli)
or the fake path (sdk), and a `prompt_of(n)` accessor — the one shape
both legs can answer.

**`P-a` — this is the fixture `shims.py` was extracted for, and the
mechanism claim is corrected (NOTE-14).** `shims.py`'s docstring names
the intent: *"so a Wave-2 `["cli", "sdk"]` contract test can call them
from inside a `params=` fixture body."* Its stated **reason** — that such
a body *"cannot itself request another fixture"* — is **not accurate**: a
parametrized fixture can reach another through
`request.getfixturevalue(...)`. The design still stands, and this unit
keeps it, on the honest grounds: calling a plain function is
**unconditional**, while `getfixturevalue` on `claude_cli_shim_worker`
would drag that fixture's whole setup into the **`sdk`** param too, where
a bash shim on `PATH` is exactly what must not exist (`HY5`). Calling the
builder for the `cli` param only is the narrower construction, not the
only possible one — and this document says so rather than repeating a
justification that does not hold.

**`P-b` — the fixture must be PROVEN live, not assumed.** A fixture whose
`"sdk"` param silently resolved to `CliBackend` would leave **every other
criterion in this document green** while covering nothing new — the
single most dangerous failure this unit can have. Two independent
positive controls, both required:

1. `PB1` asserts backend **identity** per param —
   `type(backend_for("worker")) is CliBackend` / `is SdkBackend`, with
   the right-hand sides imported independently in the test.
2. `PB2` asserts an **observable asymmetry** that no shared code path can
   fake: on the `sdk` param a driven `Outcome` `isinstance(…, SdkOutcome)`
   and on the `cli` param it does **not**. `SdkOutcome` is a frozen
   subclass `CliBackend` never constructs (`U-sdk` `E-1`).

`M1` is the negative control for both.

**`P-c` — neither leg may reach a real model, and each proves it
positively.** The `cli` leg asserts the shim's own call counter is
**> 0** after every transport-leg criterion (a zero counter means the
shim was never on `PATH` and something else answered). The `sdk` leg
relies on `B-2`'s tripwire plus `HY2`'s source scan. Criteria `PB3`,
`PB4`.

**`P-c1` — the `cli` param PREPENDS to the inherited `PATH`, and that is
correct (delta gate `BLOCKER-D2`).** `worker.run()` shells out to `git`
(`compose_batch_prompt` → `_digest`) long before it reaches an
invocation, so a `PATH` scrubbed down to `tmp_path` kills every
`cli`-param criterion at setup with `FileNotFoundError: 'git'` —
measured. The prepend is therefore not a tolerated weakness; it is what
lets the run happen at all. Safety comes from `F-c2`'s
**claude-resolution** property, policed by `HY5` legs 1 and 2, not from
starving `PATH`. One consistent story: *prepend freely; guarantee that
the only `claude` anyone can resolve is the shim.*

### 3.3 `Scope-1` — the write boundary, and the twin witness at the worker (NORMATIVE)

`U-seam`'s twin-witness construction is **inherited, not restated**:
Witness A is `Containment` + `containment_permissions`; Witness B is
`worker.write_settings_file` / `worker.write_repair_settings_file`;
Witness C is argv. `U-seam` `CN6`–`CN10` pin their agreement.

What no unit has stated is the **third** witness this flip introduces:

> **Witness D — the SDK charter's approve/deny frontier.** For a given
> `Containment`, the set of paths `charter.build_can_use_tool(c)`
> approves a `Write` to must equal the set of paths Witness B's rules
> grant. It is independent of A and B by construction: `charter.py`
> imports neither `worker` nor any settings file, and derives its
> `CharterPaths` from `containment.write_globs` / `.write_exact` alone.

**`S-a` — the frontier is asserted by DECISION, not by comparing
patterns.** Comparing the charter's compiled regexes to the settings
file's rule strings would compare two spellings of the same idea and
prove nothing about what either enforces. The criteria instead drive one
concrete path through both witnesses and require the **same verdict**:

| Path, under the shipped default (`stage_on`) | Witness B (cli) | Witness D (sdk) |
|---|---|---|
| `stage_dir()/lrn-0000aaaa.yaml` | granted by `Edit(/{stage}/**)` | **approved** — measured, `tool_result` content `"ok"`, `denials == ()` |
| `<home>/skills/s/proposals/lrn-0000aaaa.yaml` | **not** granted — the only rule is the stage glob | **denied** — measured, reason `self-learn invocation charter: Write write scope does not include <resolved path>`, one `denial` line with `"source": "charter"` |

Both rows were measured on this worktree at `89f8ef7` (§9 `E5`).
Criteria `WS1`–`WS3`.

**`S-b` — `SELF_LEARN_STAGE=0` moves the frontier on BOTH witnesses
together, and that is the negative control.** With the switch off,
Witness B becomes `worker.write_permission_rules(home)`'s three ledger
globs and Witness D must approve the ledger path and **deny** the stage
path — the exact inversion of the table above. A build that hardcoded the
stage on either side passes `WS1`–`WS3` and fails here. Criterion `WS4`.

**`S-c` — the analyst's and miner's containments are out of scope.**
This unit asserts nothing about `containment_for("analyst")` or
`containment_for("miner-reader")`. `U-sdk`'s `CH` group owns them, and
`U-sdka` owns the analyst flip.

### 3.4 `Attr-1` — attribution, and the one thing no fixture can show (NORMATIVE)

**`A-a` — filesystem-diff attribution is unchanged, because this unit
changes nothing.** `run()` harvests `staged_paths()`, resolves each to
`bucket_dir / "proposals" / path.name` via `_resolve_destination`, and
installs atomically under `gitops.commit_lock`. The criteria **observe**
that this still holds on the `cli` leg (`WS6`) and do not re-derive
`U-attrib`'s own coverage.

**`A-b` — with `Fake-3`, both legs land a file, and `WS6` becomes
symmetric.** r1 could only assert an absence here (`B-4`); ruling `V-2`
replaces it with the real observation:

> On **both** legs, a proposal the charter **approved** lands in the
> stage and is installed to `<bucket>/proposals/<name>`; a write the
> charter **denied** lands nothing. The filesystem state and the
> permission verdict agree, on both backends, in both directions.

That is a strictly stronger statement than r1's, and it is the one the
flip actually needs: the question at flip time is not *"does the sdk leg
behave differently"* but *"does the sdk leg put the same bytes in the
same place under the same permission"*. `WS6` asserts all four cells
(two backends × approved/denied).

**`A-b1` — what still does NOT transfer.** The fake writes the file **in
its own process**, from the scenario body, after the SDK delivered the
permission response. So `WS6` proves *the charter's verdict and the
resulting filesystem state agree*; it does **not** prove that the SDK's
own tool executor honors a verdict, because no real tool executor runs.
That is a live-session property and stays out of reach (`R-2`).
Residual `R-1` now records this narrower gap.

**`A-c` — stdout is never parsed, on either backend.** `U-seam` `T-e`
fixes `Outcome.stdout` to `""` on both worker surfaces; `U-sdk` `O-stdout`
reproduces it. `WS5` adds the worker-side half neither stated: `run()`
never reads the value `write_session` returns — `_invoke_claude` discards
the `Outcome` and returns `None` — so there is no path by which a future
backend's stdout could reach the harvest. Asserted behaviorally (a
session that produces text changes nothing about the run) **and** by an
AST scan of `worker.py` finding no assignment from an
`invocation.write_session(` call.

### 3.5 `Fail-1` — the failure contract, enumerated fail-closed (NORMATIVE)

**`F-a`** `worker._invoke_claude` returns `None` and **never raises**, for
every member of `invocation.FAILURE_KINDS`, on **both** backends. That is
`U-seam` `S-b` and `WR1` restated where the worker actually calls it —
neither existing criterion drives the worker surface on the `sdk` leg.

**`F-b` — the criterion enumerates `FAILURE_KINDS` from the contract
module, never from a local literal.** `FL1` collects the set of kinds it
actually drove and asserts
`driven == set(invocation.FAILURE_KINDS)`. A sixth kind added by a later
unit then **reddens** this criterion instead of being silently
uncovered. A local tuple of five strings would pass forever. `M16` is the
negative control.

**`F-c` — how each kind is reached, per backend.** Defined once:

| Kind | `cli` leg (T2) | `sdk` leg (T3) |
|---|---|---|
| `exit` | `CLAUDE_SHIM_EXIT_1=7` | scenario `error_result` — measured `failure="exit"`, `rc=1`, `detail="boom"` |
| `timeout` | `CLAUDE_SHIM_SLEEP_1` past `SELF_LEARN_INVOKE_TIMEOUT_SECS` | scenario `hang` — measured `failure="timeout"`, `rc=None` |
| `not-found` | `PATH` set to a directory under `tmp_path` containing **no** `claude` at all | `SELF_LEARN_SDK_CLI_PATH` pointed at a **nonexistent** path — measured `failure="not-found"`; the tripwire never fires because `cli_path` stays non-`None` (`B-2`) |
| `os-error` | **`monkeypatch.setattr(subprocess, "run", <raises OSError>)`** — never a non-executable file on `PATH` (`F-c1`) | a `write_glob` containing `[` → `CharterPatternUnsupported` — measured `failure="os-error"` |
| `unavailable` | the `sdk_absent` shim with `SELF_LEARN_BACKEND_WORKER=sdk` | same |

Every `sdk` row was measured on this worktree (§9 `E6`). The `unavailable`
row is identical on both legs by construction — it is the registry
refusing before any backend is built.

**`F-c1` — the `cli` `os-error` recipe is a MONKEYPATCH, and the reason
is a measured near-miss (BLOCKER-1).** r1 specified *"a `claude` on
`PATH` that is not executable."* **That recipe spawns the real CLI.**
`execvp` does not stop at a non-executable match — it **skips the entry
and keeps searching `PATH`** — so on any host that has a real `claude`
further down (this one has `~/.local/bin/claude`), `subprocess.run`
finds and **executes it**. The blind gate reproduced this: two real
spawns, exit 1, no session started — but real spawns nonetheless, and
**invisible to `B-2`'s tripwire**, which patches only the SDK's
`_find_cli` and has no reach into `subprocess`.

Two consequences, both normative:

- The recipe becomes `monkeypatch.setattr(subprocess, "run", …)` raising
  a bare `OSError` — the form `R-8` already named as the fallback, and
  the one `B-3`/`B-3a` guarantee is reachable, since `invocation/cli.py`
  calls through the `subprocess` **module attribute** by construction
  (`U-seam` `TR7`). It is weaker in the sense `R-8` describes — it no
  longer exercises the transport — and that is the correct trade against
  spawning a real credentialed binary.
- **The `cli` leg needs its own no-real-claude control**, because the
  tripwire is sdk-only. `HY5` is that control, and it is new.

**`F-c2` — REBASED on claude-RESOLUTION, not on `PATH` composition
(delta gate `BLOCKER-D1`/`BLOCKER-D2`).** r1's fold said *"no criterion
may prepend a shim directory to the inherited `PATH`; it **replaces**
it."* **That remedy is unachievable**, and the delta gate measured why: a
`PATH` containing only `tmp_path/shims` makes `worker.run()` die with
`FileNotFoundError: 'git'` inside `compose_batch_prompt` → `_digest`,
**before any invocation happens** — so every `cli`-param criterion that
drives a real run would fail unobserving. The shipped
`claude_cli_shim_worker`'s own docstring already records this: *filtering
`PATH` broke git*. Symlinking `git` into the shim dir is not a way out
either — it resolves outside `tmp_path` and defeats the very property
leg 1 asserts.

So the mechanism is **not** the thing to police. The property that
actually closes BLOCKER-1's hazard is about what `claude` resolves to,
and it is stated positively:

> **In any state reachable inside a `cli`-param test,
> `shutil.which("claude")` resolves to the shim under `tmp_path` — and
> to nothing else, ever.**

`PATH` therefore stays **inherited-plus-prepend**, exactly as `Par-1`'s
`cli` row builds it, so `git` and the rest of the toolchain keep
working. The prepend is legal; what is forbidden is any state in which a
`claude` outside `tmp_path` is reachable, or in which the `os-error`
recipe leaves a real binary reachable — and the monkeypatch recipe
(`F-c1`) already guarantees the second by never consulting `PATH` at
all. `HY5` polices **the property, not the mechanism**.

**`F-d` — byte-identity holds for THREE of the five kinds, not all five,
and the gate measured which (BLOCKER-2).** r1 asserted it for all five.
That is false for two and **structurally impossible** for a third:

| Kind | Byte-identical across backends? | Why |
|---|---|---|
| `timeout` | **yes, first line** | both render `run: claude timed out after {t:g}s`. The `sdk` leg then adds up to **two kill-ladder lines** (`U-sdk` `O-quiet` rows 4–5), which are *permitted* and are not the template's line — so the comparison is over the **first** line, not the whole capture (NOTE-6) |
| `not-found` | **yes** | measured on both |
| `unavailable` | **yes** | the registry renders it before any backend is built, so it is the same code on both legs by construction |
| `exit` | **NO — and `F-c` is why** | `rc` is fixture-determined: `F-c`'s `cli` recipe sets `CLAUDE_SHIM_EXIT_1=7`, while the `sdk` leg's `_map_result_message` synthesizes a hardcoded `rc=1` (`U-sdk` `O-rc`). `run: claude exited 7: …` vs `run: claude exited 1: boom` — a **direct contradiction between r1's own `F-c` and `FL2`** |
| `os-error` | **NO — impossible** | on `sdk`, a `CharterPatternUnsupported` failure returns an `Outcome` **without logging anything at all**, while `cli` logs its `os_error` line. There is no fixture choice that makes these match; the divergence is in the product |

So `FL2` is scoped to the three, `exit` asserts **template provenance
and shape** instead of bytes, and the `os-error` divergence is **routed
as a product finding** per §7.5 rather than tested around — it is a real
asymmetry the worker flip inherits (`R-10`).

**`F-d1` — provenance is the stronger half anyway.** For every kind,
including the two that cannot match bytes, `FL2` asserts the line was
rendered **through `LOG_TEMPLATES`** rather than from a copy, via
`monkeypatch.setitem` (`U-seam` `B-3a`'s third site). That is what
catches `M17`, and no byte comparison can.

**`F-e`** `run()` survives every failure on both backends: the run
completes, `RunResult.status` carries the shipped value, and
`worker.last-run` is **not** touched on a failing run. Criterion `FL3`.

### 3.6 `Hatch-1` — `SELF_LEARN_ENFORCE_SCOPE=0`, per backend (NORMATIVE)

The variable's mechanism differs by backend, and the parity the `U-sdk`
spec pinned is what this unit checks **at the worker, through the real
variable**:

| Backend | What `SELF_LEARN_ENFORCE_SCOPE=0` does | Where it is stated |
|---|---|---|
| `cli` | `worker.write_settings_file` / `write_repair_settings_file` **omit** the `defaultMode` key from `permissions`; the host's own `~/.claude/settings.json` then decides, and on this host that is `bypassPermissions` — so the settings scope is voided | `worker.py`'s two writers, `if _enforce_scope(): permissions["defaultMode"] = "default"` |
| `sdk` | `Containment.default_mode` is `None`, so `charter.build_can_use_tool`'s `hatch_open` conjunct fires and the callback **approves everything below step 1** | `U-sdk` `C-10`; `charter.py`'s `hatch_open = containment.default_mode is None and bool(containment.write_globs or containment.write_exact)` |

**`H-a` — both conjuncts of `C-10` are exercised at the worker.** The
first (`default_mode is None`) is what `HA2` drives end-to-end from the
real variable — measured, §9 `E5` case C: with `SELF_LEARN_ENFORCE_SCOPE=0`
a `Write` to a **ledger proposals** path was approved on the same run
whose cli settings file omitted `defaultMode`, where the identical run
with the variable unset denied it. The second
(a non-empty write set) is exercised by `HA3`'s legs (ii)–(iv):
`DEGRADED_WORKER_CONTAINMENT` has empty write sets and must grant
nothing even with the variable set.

**`H-b` — the hatch is fenced on both backends.** `cli`: the settings
file's `allow` list and the argv are byte-identical with and without the
variable — only the `defaultMode` key moves. `sdk`: `permission_mode ==
"default"`, `setting_sources == []`, `strict_mcp_config is True`,
`settings is None`, and `disallowed_tools` byte-identical to the
variable-unset run. Criterion `HA4`.

**`H-c` — silence parity.** Neither backend logs anything attributable to
the hatch. Asserted behaviorally on both legs. This is `U-sdk` `CH13`
restated at the worker; the source-scan half of `CH13` is **not**
duplicated here (one register).

**`H-d` — the repair surface's hatch is checked separately, and must
be.** `containment_for("worker-repair")` returns `write_globs=()`, so a
build whose hatch conjunct reads `write_globs` alone leaves the repair
round's hatch permanently closed while every batch-surface criterion
stays green. `HA2`'s third leg drives the repair surface directly through
`_invoke_claude(…, label="repair ")` with a non-empty `write_exact`.
`M4` is the negative control.

### 3.7 `Big-1` — the >128 KiB prompt (NORMATIVE)

**The risk, sourced.** `worker.build_argv`'s own docstring states it:
*"the prompt is deliberately NOT in argv (audit 2026-07-15, shared with
the miner's B1): Linux caps one argv element at 128 KiB, and a full batch
— 15 records × (record + canon excerpt) + doctrine + registry —
plausibly exceeds it. The prompt rides stdin instead."* The migration
plan carries the same risk as `R14`. A backend that regressed this would
fail only on large batches, i.e. exactly the nightly runs nobody watches.

**`BG-a` — the fixture prompt, defined once.** `BIG_PROMPT` is a
deterministic string with `len(BIG_PROMPT.encode("utf-8")) > 128 * 1024`,
built in the test module and asserted against that threshold **in the
criterion itself** — so a later edit that shrinks it below the cap
reddens rather than silently weakening every leg that uses it. Measured
reference size: **162 000 bytes** (§9 `E4`).

**`BG-b` — three separate claims, three legs.**

| Leg | Claim | Oracle |
|---|---|---|
| `BG1` | the prompt is **not in argv** on either backend | the captured argv contains no element equal to `BIG_PROMPT` and no element whose encoded length exceeds `128 * 1024`; on `sdk`, `options.system_prompt` does not carry it either |
| `BG2` | `cli` — delivered **intact on stdin** | the shim's `cat > "$calls/prompt.$N"` file, read back and compared byte-for-byte |
| `BG3` | `sdk` — delivered **intact to and through the client** | two witnesses: (i) a spy on the client's `query` records the exact string our code handed over; (ii) end-to-end, `repr(BIG_PROMPT) in outcome.detail` via `B-6`'s echo, plus the **length relation** `len(outcome.detail) == 30 + len(repr(BIG_PROMPT))` — 30 being the fixed prefix `"fake_claude: no such scenario "`. The relation is written as an expression, **never as the literal 168 032**, so it survives any change to `BIG_PROMPT`'s size (NOTE-1) |

**`BG-c` — why `BG3` needs both witnesses.** Witness (i) proves *our*
code did not truncate; witness (ii) proves the bytes survived a process
boundary. Neither alone is the claim: a spy-only leg passes while the
transport drops the tail, and an echo-only leg cannot distinguish our
truncation from the SDK's. `M12` and `M13` are the negative controls,
and their rows record which legs stay green under each.

### 3.8 `Flip-1` — readiness, and the line this unit does not cross (NORMATIVE)

**`FL-a`** `SELF_LEARN_BACKEND_WORKER=sdk` resolves **both** worker
surfaces to `SdkBackend`, because `SELECTOR_FOR_SURFACE` maps `"worker"`
and `"worker-repair"` to the same selector `"WORKER"` — the rule `U-seam`
`Surf-1` states and `D-1` justifies (*"a run whose two halves used
different backends is a state nobody should have to reason about"*).
Criterion `FR1`.

**`FL-b` — the default is NOT touched.** `registry.py`'s rung-5 default
stays `"cli"`, `KNOWN_BACKENDS` stays `("cli", "sdk")`, and
`git diff 89f8ef7..HEAD -- …/invocation/registry.py` is **empty**. The
default table is `U-sdka`'s, for the analyst only. Criterion `FR3`;
mutation `M21` proves the guard is live rather than decorative.

**`FL-c` — every criterion DECLARED as `T2 + T3` must run on both legs,
and that is itself checked (NOTE-4).** r1's *"every contract criterion
runs on both legs"* was **too broad and contradicted §4's own tier
declarations** — `RP1` is T1, `RP4`/`WS2`/`EV1`–`EV4` are T3-only,
`WS3`/`BG2`/`EV5`/`HY5` are T2-only, and that asymmetry is deliberate,
not a gap. The property is therefore scoped: **a criterion whose §4 entry
says `(T2 + T3)` must appear under both params.** `FR2` collects this
module's node ids, partitions by param, and asserts the `T2 + T3` set
matches on both sides. Instrument criterion. Its blind spot is recorded
in `R-6`.

**`FL-d` — the sequencing note: what the flip unit is waiting for
(ruling `V-1`).** r1 routed this out as an open question; it was already
answered. The approved migration plan states the burn-in gates
explicitly, and they are **ratified**, so this unit cites them rather
than re-opening them:

| Surface | Gate |
|---|---|
| analyst (`U-sdka`) | **10** clean attended routes; an **injected timeout** landing in `pending/`; trace shape unchanged against a `cli` control |
| miner | **5** clean nightly cycles; **0** orphans at the morning check; volume within **±1σ** |
| **worker (this unit's flip)** | **5** clean unattended mine→worker cycles including **≥1 repair round**; **0** out-of-scope write attempts — `Outcome.denials` empty **and** the filesystem diff agrees; clean commit/push |
| cross-cutting | cost **≤1.5×** the `cli` baseline, against the *isolation-should-be-CHEAPER* prior |

**The gate-keeper is the OPERATOR, attended by design — there is
deliberately no machine gate**, and this unit does not build one. Two
consequences bind this document:

- The worker's gate reads **`Outcome.denials`**, which is precisely what
  `Ev-2` captures and `EV3` pins the shape of (`E-d`). This unit's
  contribution to the flip is not only "the contract is tested" but "the
  evidence the gate reads exists and is well-formed."
- The gate names **≥1 repair round** under the flipped backend. Before
  `V-2` that was unobservable in the suite at all (`B-4`), which is a
  second, independent reason the ruling went the way it did.

`U-docs` (parallel, Wave 2) writes these gates into the operator runbook;
this table is a **citation, not a second register** — where the runbook
and this table ever disagree, the runbook and the plan win and this table
is stale.

### 3.9 `Ev-2` — tool-events capture, and the consumer this unit must not build (NORMATIVE)

**`E-a`** Under `sdk`, a worker run leaves exactly one
`worker.cache_dir() / f"worker.tool-events.{run_id}.jsonl"`, `run_id`
matching `^\d{8}T\d{6}Z-\d+$`. Measured shape (§9 `E5`):

```
{"type":"meta","surface":"worker",…,"session_id":"fake-session-1","failure":null}
{"type":"tool_event","kind":"tool_use","id":"toolu_1","name":"Write","input":{"file_path":"…"}}
{"type":"tool_event","kind":"tool_result","tool_use_id":"toolu_1","is_error":false,"content":"ok"}
```

and, on the denied case, additionally

```
{"type":"denial","source":"charter","tool":"Write","reason":"self-learn invocation charter: Write write scope does not include …"}
```

Criteria `EV1`, `EV2`, `EV3`.

**`E-b` — the `cli` leg writes NO such file, and that is a criterion.**
Without it, a build that wrote an empty events file on both legs would
pass `EV1`–`EV3` while the file carried nothing backend-specific.
Criterion `EV5`; mutation `M26`.

**`E-c` — CAPTURE ONLY. The consumer is `U-corrob`, post-burn-in.** This
unit asserts the file exists and carries the fake session's events. It
builds nothing that reads one. `EV4` widens `U-sdk`'s `EV4` from
`invocation_sdk/` to **all of `src/self_learn/`**, because the consumer
this unit must not build would live in `worker.py`, not in the sdk
package. Mutation `M27` is the only thing that catches it.

**`E-d` — capture is what makes the worker's own burn-in gate
measurable.** The plan's worker gate requires *"0 out-of-scope write
attempts — `Outcome.denials` empty **and** the filesystem diff agrees"*
(`FL-d`). `denials` is exactly what `EV3` pins the shape of. This unit
does not evaluate that gate; it makes the evidence the operator will
read exist and be well-formed.

### 3.10 `Fake-3` — the sanctioned scenario (NORMATIVE, ruling `V-2`)

One new scenario in `tests/fixtures/fake_claude.py`, named
**`ok_write_real`**, plus its `SCENARIOS` key and one counter helper.
Nothing else in that file changes.

**`FK3-a` — it honors the permission verdict.** Like `_scenario_ok_write`
it calls `_request_permission` first. It then writes the target file
**iff the response's `behavior` is `"allow"`**, and emits the matching
`tool_use` / `tool_result` pair either way. Writing unconditionally would
make the file's existence say nothing about the charter — which is the
whole property `WS6` and `RP4` are built to observe. Mutation `M36`.

**`FK3-b` — per-invocation bodies, mirroring the bash shim's own
discipline.** A worker run that reaches a repair round spawns the fake
**twice**, and the two invocations must write **different** bytes (round
1 a refusable proposal, round 2 a fixed one) — otherwise `touched2` is
empty and the repair round's "the file changed" and "the file is now
valid" collapse into one observation, the gate `test_repair.py`'s `B8`
already names. Since each invocation is a fresh process, the fake reads
an invocation counter from a file named by `FAKE_CLAUDE_CALLS`,
increments it, and selects `FAKE_CLAUDE_WRITE_BODY_<N>` falling back to
`FAKE_CLAUDE_WRITE_BODY`. **This is the same `CTR` / `CLAUDE_SHIM_SCRIPT_$N`
shape `shims.py`'s worker shim already uses**, deliberately — the two
fakes' control protocols become parallel, which is what lets one
parametrized fixture drive both legs of `RP4` with one script per round.

**`FK3-c` — the target is `FAKE_CLAUDE_WRITE_TARGET`**, the knob
`_scenario_ok_write` already reads (`B-5`'s neighbour). No new target
knob is introduced.

**`FK3-d` — the addition is enumerable, and `SU4` enumerates it.** The
file's set of top-level names gains **exactly** `_scenario_ok_write_real`
and the counter helper; `SCENARIOS`' key set gains **exactly**
`"ok_write_real"`; and every function that existed at `89f8ef7` has an
**unchanged per-function source sha**. A whole-file sha would have made
the sanctioned addition indistinguishable from an unsanctioned rewrite;
a per-function sha distinguishes them (`U-seam` `HY3`'s form, applied to
a file that is *allowed* to grow).

**`FK3-e` — still no network, still no subprocess.** `U-sdk`'s `HG3`
scans this file for `subprocess`, `socket`, `urllib`, `http` and must
stay green. The new scenario adds a `Path.write_text`, which is a
filesystem call and not one of those — and `U-sdk`'s `EV4`-family scans
are unaffected because this file is a fixture, not a package module.

---

## 4. Acceptance criteria

**These criteria are the spec.** Each is a named test in
`plugins/self-learn/cli/tests/test_worker_contract.py` unless it says
otherwise. **46 criteria**, in eleven groups: `SU` 5, `PB` 4, `WS` 6,
`RP` 4, `TO` 3, `FL` 3, `HA` 4, `BG` 3, `EV` 5, `FR` 4, `HY` 5.
`SU1`, `SU2`, `SU3`, `SU5` and `FR2` are **instrument criteria** —
satisfied by a command's recorded output in the build report, not by a
test function.

**Each criterion declares its tier** (`M-b`), and the declaration is
load-bearing: `FR2` audits *only* the criteria declared `(T2 + T3)`, so
a mis-declaration is a coverage hole `FR2` cannot see (`R-6`).

### SU — the suite (the headline)

- **`SU1`** *(instrument)* The CLI suite at `plugins/self-learn/cli`
  collects **1873** and reports **1868 passed, 5 skipped, 0 failed, rc
  0** — the `89f8ef7` baseline (`B-8`) — *plus* the new tests in
  `test_worker_contract.py`. A collected count below 1873, any failure,
  or a **sixth** skip fails this criterion. The five skips are the four
  `test_lock_invariant.py` *"not a ledger-mutating surface"* skips and
  `test_regime_fixes.py`'s *"repo-root suite absent"*. rc is read
  **unpiped**.

  **Expected wall-time cost: +60–90 s** over the 264.84 s baseline
  (NOTE-13). Every `T3` leg spawns the fake CLI, and the timeout legs
  each burn their bound plus the kill ladder (~3.5 s measured per `sdk`
  timeout, `TO1`). Recorded so a builder reading a ~350 s run does not
  mistake the cost for a hang, and so the suite-budget conversation
  (`FW-28`'s theme) has a number rather than a surprise.
- **`SU2`** *(instrument)*
  `git diff --name-only 89f8ef7..HEAD -- plugins/self-learn/cli/tests/`
  names **exactly two** paths: `tests/test_worker_contract.py` and
  `tests/fixtures/fake_claude.py` (`V-2`). **No file that collects tests
  appears.**
- **`SU3`** *(instrument)* All four rows of `MT-a` produce their required
  output, verbatim, in the build report. Row 1's **empty** output is the
  no-product-code bound; row 3's **`0` deletions** column on both paths
  is the additive-only bound.
- **`SU4`** Two clauses, both required.

  **(a)** The **eight** whole-file armor pins are **byte-identical** to
  base. The test stores a `sha256(path.read_bytes())` hex literal per
  file and asserts equality:

  | File | sha256 (at `89f8ef7`) |
  |---|---|
  | `tests/conftest.py` | `49e0fd2f1c9232d5e9ed6e105e22388aa54bbd53493a7ec7ecc8305ee79224ea` |
  | `tests/shims.py` | `c8f348539263fb71a61026b48f9acac213aa5809b7421c1971ee85639a0f6dcb` |
  | `tests/backends.py` | `a2ba2d74f117a230740d10e3c9fa67bd30f751ce80ec59667c9136557a906dde` |
  | `tests/test_invocation.py` | `e9ee70356d65106848c5857530d43f3bd3ad7244de1a34a4e31aaa200a416c2b` |
  | `tests/test_invocation_sdk.py` | `9a3246318c86eec8b049e655e7ffeee5f370b828134cc9b62a1eef64ced8668a` |
  | `tests/test_u_fake.py` | `72c5010db060a1179a75648ad17a343b8e0bc69e2923f885b3dbe97f3e636a7e` |
  | `tests/test_worker.py` | `39cb1ca0dd6c2dd366c5455da86c875187d884bdee42ac952f558ba3cdbf882a` |
  | `tests/test_repair.py` | `dd0accf9f1315109f93de18adc93d206bea56afc50168a7e1ac7f8d846f91c94` |

  **Provenance is itself an obligation** (`U-seam` `D-27`): the shas are
  extracted with `git show 89f8ef7:plugins/self-learn/cli/<path>`, never
  from a working tree that may already carry an edit, and the build
  report carries `git diff --stat 89f8ef7..HEAD -- <those eight paths>`
  showing **no output**. A sha proves the bytes match *something*; the
  diff proves the something is the baseline. Both, or neither is
  evidence. Failure message: *"Shipped armor changed. If this was
  deliberate, U-sdkw is the wrong unit for it — see §7.5."*

  **(b)** `tests/fixtures/fake_claude.py` — the one file `V-2` lets grow
  — is pinned **per function, not whole-file** (`FK3-d`). **Four**
  assertions, all against the base commit's bytes read with
  `git show 89f8ef7:…`:

  1. For **every** top-level function present at base,
     `sha256(inspect.getsource(fn).encode("utf-8"))` equals the base
     commit's sha for that function. Nothing that already existed moved.
  2. The set of top-level names gained **exactly**
     `{"_scenario_ok_write_real", <the counter helper>}` — enumerated as
     a literal set in the test, so widening it is a visible diff.
  3. `SCENARIOS`' key set gained **exactly** `{"ok_write_real"}`, and the
     base commit's ten keys all survive **bound to their original
     functions** — compared by the registered value's `__name__`, not by
     key presence alone.
  4. **The file's top-level non-`FunctionDef` statements are exactly the
     base commit's** — imports, module constants, the `SCENARIOS` dict
     literal, the `if __name__` guard — compared as a normalized
     `ast.dump` of that statement list, the single permitted delta being
     `SCENARIOS`' one new key. **This leg exists because the blind gate
     BROKE legs 1–3.** Its evasion: append a module-level rebinding of a
     pre-existing global — `SESSION_ID = "attacker-session"` at the end
     of the file. Every function's source sha is unchanged, no new
     top-level *name* appears, the `SCENARIOS` key set is untouched, and
     the numstat is purely additive. It **passed**, and was caught only
     **incidentally** by `EV1`'s hardcoded `"fake-session-1"` literal —
     an accident of another criterion, not a guard.

  **Why legs 1–3 resolve functions through the MODULE, and why that
  choice already earned its keep.** Each function is reached as an
  attribute of the imported module and handed to `inspect.getsource`,
  which reports the source of the object **currently bound** to that name
  — not the first `def` of that name in the file. The gate's other
  evasion attempt was an **appended shadowing redefinition** of
  `_scenario_ok_write`; an `ast.parse`-and-take-first-match
  implementation would have hashed the original `def` and reported no
  change, while the runtime binding hashes the shadow and **reddens**.
  That attempt was **caught**. Keep the runtime-binding form; an
  AST-first-match form is a silent downgrade, and this paragraph is here
  so a later reader does not "simplify" it into one.

  A whole-file sha here would have made the sanctioned addition
  indistinguishable from an unsanctioned rewrite; this four-leg form
  permits exactly the growth `V-2` authorized and nothing else.
  Mutations `M35`, `M38`, `M42`.
- **`SU5`** *(instrument)* The shim-fixture census is unchanged, measured
  with `uv run pytest --fixtures-per-test --color=no -q` and
  `grep -cE "^<name> -- "`: `claude_cli_shim_worker` **112**,
  `claude_shim` **7** (`test_repair.py`'s compat alias),
  `claude_cli_shim_analyst` **17**. `--color=no` is **required** —
  without it the ANSI-wrapped lines do not match and every count reads
  **0**, a silent false pass (`U-seam` `E3`'s measured footgun). A count
  other than these means a test was added, removed or re-fixtured;
  investigate before proceeding.

### PB — the parametrized backend harness

- **`PB1`** The `backend` fixture's params are exactly `["cli", "sdk"]`,
  and under each param **both** `backend_for("worker")` and
  `backend_for("worker-repair")` satisfy
  `type(b) is CliBackend` / `type(b) is SdkBackend`, where the
  right-hand sides are imported independently in the test (identity, not
  `isinstance` — a same-named class reached by another route fails)
  (`P-b` leg 1).
- **`PB2`** The observable asymmetry: a driven `Outcome` on the `sdk`
  param satisfies `isinstance(outcome, SdkOutcome)` and on the `cli`
  param does **not**. `SdkOutcome` is a class `CliBackend` never
  constructs, so no shared code path can fake this (`P-b` leg 2).
- **`PB3`** *(sdk param)* Every session in this module runs against the
  shipped fake: `os.environ["SELF_LEARN_SDK_CLI_PATH"]` equals
  `str(FAKE_CLI)` inside every `sdk`-param test, asserted positively at
  the point of use rather than assumed from the fixture (`P-c`).
- **`PB4`** *(cli param)* The shim was actually reached: after every
  `cli`-param transport-leg criterion the shim's invocation counter is
  **≥ 1**. A zero counter means something other than the shim answered,
  which is the fail-open shape this control exists to exclude (`P-c`).

### WS — the write scope and the twin witness

- **`WS1`** *(T2 + T3)* For a real `worker.run()` under **each** param,
  the batch invocation's captured `SessionSpec.containment` has
  `write_globs == (f"{worker.stage_dir()}/**",)` and `write_exact == ()`,
  and
  `containment_permissions(spec.containment) == json.loads(<the file named by that invocation's own --settings>.read_text())["permissions"]`.
  The settings path is read out of the **captured argv**, not from a
  local variable — the stronger observation (`U-seam` `W-a1`).
- **`WS2`** *(T3)* The `sdk` leg's charter frontier equals `Scope-1`'s
  table, both rows, on one `worker.run()` each with
  `FAKE_CLAUDE_FORCE_SCENARIO=ok_write` (`B-5`): with
  `FAKE_CLAUDE_WRITE_TARGET` a **stage** path the `tool_result` is not an
  error and no `denial` line is written; with it a **ledger
  `proposals/`** path the `tool_result` is an error, one `denial` line
  appears, and its `reason` is the byte-exact charter message naming the
  **resolved** path. **`ok_write`, not `ok_write_real`, is used here on
  purpose**: `WS2` observes the *verdict*, and it must be able to fail
  when the verdict is wrong even if no filesystem consequence follows.
  `WS6` observes the *consequence*, separately, with the writing
  scenario. Splitting them keeps one criterion from covering for the
  other's silence.
- **`WS3`** *(T2)* The `cli` leg's Witness B for the same run is exactly
  `worker.stage_permission_rules(home)` —
  `json.loads(settings)["permissions"]["allow"] == worker.stage_permission_rules(home)` —
  and contains **no** ledger `proposals` glob. The comparison operand is
  **recomputed** in the test from the shipped function, not copied from
  the file just read.
- **`WS4`** *(T2 + T3)* **The negative control for `WS2`/`WS3`.** With
  `SELF_LEARN_STAGE=0`, on both params: Witness B becomes exactly
  `worker.write_permission_rules(home)`'s three globs, in that order
  (`skills`, `projects`, `user` — unsorted, `U-seam` `CN4`), and Witness
  D **approves** the ledger `proposals/` path and **denies** the stage
  path. The full inversion of `Scope-1`'s table (`S-b`).
- **`WS5`** *(T1 + T2 + T3)* stdout is never parsed. Behavioral: a
  session producing text (`sdk`: `ok_text`'s `RESULT-SENTINEL`; `cli`:
  the shim echoing to stdout) leaves `Outcome.stdout == ""` on both
  worker surfaces and changes nothing about `RunResult`. Structural: an
  AST scan of `worker.py` finds **no** assignment target whose value is a
  `Call` to `invocation.write_session` (`A-c`).
- **`WS6`** *(T2 + T3)* Attribution, **four cells, symmetric across the
  two backends** (`A-b`). On each param: (i) a run whose write target is
  **inside** the stage lands the proposal at
  `<bucket>/proposals/<rid>.yaml`, `RunResult.proposed == [rid]`, and the
  installed bytes equal the written bytes; (ii) a run whose write target
  is **outside** the grant lands **nothing** — no file in the stage, no
  file in the bucket — and `RunResult.status` is the shipped failed
  value. The `sdk` legs are driven by `Fake-3`'s `ok_write_real`, which
  writes **iff the charter allowed** (`FK3-a`); the `cli` legs by the
  shim's `CLAUDE_SHIM_SCRIPT_1`. The criterion carries an inline comment
  naming `R-1`'s narrower residual (`A-b1`) so a reader does not mistake
  this for proof that a real tool executor honors a verdict.

### RP — the repair round

- **`RP1`** *(T1)* Driven with
  `install_fake(request, monkeypatch, [Writes({stage/<rid>.yaml: <refusable>}), Writes({stage/<rid>.yaml: <fixed>})])`,
  `run()` produces **exactly two** `SessionSpec`s, with `surface`
  `"worker"` then `"worker-repair"`, in that order. The second's
  `containment.write_exact` equals exactly the eligible staged paths and
  its `write_globs == ()`. The first's captured argv names
  `worker.settings.json` at `--settings`; the second's names
  `worker.repair.settings.json`. Backend-independent by construction
  (`M-c`).
- **`RP2`** *(T2 + T3)* The repair surface reaches the **same** backend as
  the batch surface. Under each param, a `backend_for` spy records both
  lookups and the two resolved classes are identical;
  `SELECTOR_FOR_SURFACE["worker-repair"] == SELECTOR_FOR_SURFACE["worker"] == "WORKER"`
  (`FL-a`).
- **`RP3`** *(T2 + T3)* The repair surface's per-backend handling, driven
  **directly** through
  `worker._invoke_claude(repair_argv, prompt, worker.repair_timeout_secs(), home, label="repair ", containment=containment_for("worker-repair", …, write_exact=(…)))`:
  returns `None`; the log lines carry the `repair ` label in the
  worker-repair templates; and on the `sdk` param the charter approves a
  `Write` to a member of `write_exact` and denies one to a sibling path
  in the same directory that is **not** a member. The sibling is the
  discriminating case — a charter that granted the parent directory
  passes a member-only test.
- **`RP4`** *(T3)* **The end-to-end `sdk` repair round** (ruling `V-2`;
  r1's unreachability trip-wire is struck). Under
  `SELF_LEARN_BACKEND_WORKER=sdk` with
  `FAKE_CLAUDE_FORCE_SCENARIO=ok_write_real`, a `worker.run()` over one
  eligible record: round 1 writes a **refusable** proposal into the stage
  (`FAKE_CLAUDE_WRITE_BODY_1`); `_dry_check_batch` refuses it; the log
  carries `run: repair round — 1 refused, 1 eligible, 0 not repairable`;
  round 2 is driven with `FAKE_CLAUDE_WRITE_BODY_2` and writes a
  **valid** proposal to the same staged path; the repaired file lands and
  installs. Four assertions, in order: (1) **two** invocations occurred
  (the fake's counter reads 2); (2) the second ran under the
  `worker-repair` surface; (3) **the INSTALLED bytes differ from
  `FAKE_CLAUDE_WRITE_BODY_1`** — restated from r1's *"the two rounds'
  bodies differ"*, which was **vacuous**: it compared two values the test
  itself supplied and would have passed against a build where round 2
  never ran. The installed-bytes form is observable only through
  `run()`'s own `touched2` path, so it fails when the counter is ignored,
  when round 2 is skipped, or when the repair output is discarded
  (MAJOR-D); (4) the installed bytes **equal** `FAKE_CLAUDE_WRITE_BODY_2`.
  Assertions 3 and 4 together are what `FK3-b` is for — a byte-identical
  round 2 leaves `touched2` empty and collapses "changed" and "valid"
  into one observation, the trap `test_repair.py`'s `B8` docstring tag
  already names. This is the criterion the plan's worker burn-in gate
  names when it requires **≥1 repair round** under the flipped backend
  (`FL-d`).

### TO — timeout semantics

- **`TO1`** *(T2 + T3)* `worker.invoke_timeout_secs()` bounds the batch
  invocation on both backends: with `SELF_LEARN_INVOKE_TIMEOUT_SECS` set
  to a small float, a hanging call returns `failure="timeout"` and the
  **first** logged line is byte-identically
  `run: claude timed out after {t:g}s` (first line only — the `sdk` leg
  legitimately appends kill-ladder lines, `F-d`). Measured reference on
  `sdk`: `run: claude timed out after 1.5s` (§9 `E6`).

  **The elapsed-time bound is `spec.timeout * 8`, and it is
  MANDATORY** (NOTE-2, NOTE-6). Measured on `sdk`: a 1.5 s spec timeout
  returns in **~5.0 s wall** — the spec bound itself plus **~3.5 s of
  kill ladder** (`INTERRUPT_GRACE_SECS` + `KILL_SECS` + the shielded
  `disconnect`) charged *after* the bound expires. r1's fold recorded the
  3.5 s as the total; it is the **added** cost (delta gate `NOTE-D6`).
  `1.5 × 8 = 12 s` clears 5.0 s comfortably, which is the point: a tight
  margin would be flaky, and **no** margin makes `M31` **hang the runner
  for 30 minutes instead of reddening** — not a redden at all. The bound
  is asserted with a monotonic clock, so a build that ignores
  `spec.timeout` fails it rather than stalling the suite.
- **`TO2`** *(T2 + T3)* `worker.repair_timeout_secs()` bounds the repair
  invocation on both backends, with the label:
  `run: repair claude timed out after {t:g}s`.
- **`TO3`** *(T1 + T2 + T3)* The two timeouts are **independent**. T1: one
  repair-producing run with `SELF_LEARN_INVOKE_TIMEOUT_SECS=X` and
  `SELF_LEARN_REPAIR_TIMEOUT_SECS=Y`, `X != Y`, and the two recorded
  `SessionSpec.timeout` values are `X` then `Y`. T2/T3: the value that
  bounds the transport is the surface's own, not the other's — a build
  that read `invoke_timeout_secs()` on the repair surface times out at
  the wrong bound and reddens.

### FL — the failure legs

- **`FL1`** *(T2 + T3)* `worker._invoke_claude` returns `None` and
  **never raises** for every member of `invocation.FAILURE_KINDS`, on
  both params, reached as `F-c`'s table specifies. The set of kinds
  actually driven is collected and asserted equal to
  `set(invocation.FAILURE_KINDS)` — **the fail-closed enumeration**
  (`F-b`). Ten legs.
- **`FL2`** *(T2 + T3)* Two clauses, per `F-d`'s measured table.
  **(a) Byte-identity, scoped to `timeout`, `not-found` and
  `unavailable`** — driven on both legs with the same `SessionSpec` and
  compared; on `timeout` the comparison is over the **first line only**,
  because the `sdk` leg legitimately appends kill-ladder lines
  (`U-sdk` `O-quiet`). **(b) Provenance and shape, for all five** — each
  emitted line is proved to come from `LOG_TEMPLATES` by
  `monkeypatch.setitem` on the template set, requiring the line to
  change (`F-d1`, `U-seam` `B-3a`); and `exit` additionally asserts the
  **shape** `run: claude exited {rc}: {detail}` with the leg's own `rc`,
  since `rc` is fixture-determined on `cli` and synthesized on `sdk`
  (`U-sdk` `O-rc`) and can never match. The `os-error` kind is
  **excluded from clause (a) by product divergence, not by choice** —
  see `R-10`.
- **`FL3`** *(T2 + T3)* `run()` survives each failure on both backends:
  it returns a `RunResult` (no exception escapes), `status` carries the
  shipped value for that condition, and `worker.last-run` is **not**
  touched on the failing path (`F-e`).

### HA — the enforcement hatch

- **`HA1`** *(T2)* `cli`, hatch open: with `SELF_LEARN_ENFORCE_SCOPE=0`,
  both `worker.settings.json` and `worker.repair.settings.json` **omit**
  the `defaultMode` key — `"defaultMode" not in perms`, asserted as
  key-absence, not as `perms.get("defaultMode") is None` — and the
  captured `SessionSpec.containment.default_mode is None` on both worker
  surfaces.
- **`HA2`** *(T3)* `sdk`, hatch open, driven **end-to-end from the real
  variable** so the whole chain (`_enforce_scope()` →
  `containment_for(enforce=…)` → `default_mode` → `hatch_open`) is
  observed rather than assumed. Three legs: (i) a `Write` to a ledger
  `proposals/` path — outside the stage grant — is **approved**, where
  the identical run with the variable unset denies it (measured, §9 `E5`
  cases B and C); (ii) `Bash` is **still denied**, because the hatch sits
  below the structural deny; (iii) the **repair** surface opens too,
  driven directly with a non-empty `write_exact` (`H-d`).
- **`HA3`** *(T2 + T3)* Hatch closed, the negative-control set. (i)
  Variable unset: the out-of-scope write is denied on `sdk` with the
  byte-exact reason, and the `cli` settings files carry
  `"defaultMode": "default"`. (ii) With the variable **set**, the
  **miner** containment (`default_mode == "default"` unconditionally)
  still denies. (iii) With it set,
  `invocation.DEGRADED_WORKER_CONTAINMENT` — the containment
  `test_repair.py::test_e1`'s five-argument call reaches (`B-3`) —
  grants **nothing**. Legs (ii)–(iii) are what make `C-10`'s second
  conjunct falsifiable at the worker.
- **`HA4`** *(T2 + T3)* The fence, and silence. `cli`: with and without
  the variable, the settings file's `allow` list and the argv are
  **byte-identical**; only the `defaultMode` key moves. `sdk`: on the
  captured options object, `permission_mode == "default"`,
  `setting_sources == []`, `strict_mcp_config is True`, `settings is
  None`, and `disallowed_tools` byte-identical to the variable-unset run.
  Both: **no log line** attributable to the hatch on either path
  (`H-b`, `H-c`).

### BG — the >128 KiB prompt

- **`BG1`** *(T2 + T3)* `len(BIG_PROMPT.encode("utf-8")) > 128 * 1024`
  asserted first, then: the captured argv contains no element equal to
  `BIG_PROMPT` and no element whose encoded length exceeds `128 * 1024`,
  on both params. The `sdk` leg additionally asserts
  `options.system_prompt` does not carry it — **recorded as belt, not
  as the claim**: the worker's `build_argv` emits no
  `--append-system-prompt`, so `system_prompt` is `None` by construction
  and this leg cannot fail today. It is kept because a future unit that
  gave the worker a doctrine string would make it the only leg watching
  that door (NOTE-5).
- **`BG2`** *(T2)* `cli` — delivered intact on stdin: the shim's captured
  prompt file for invocation 1 equals `BIG_PROMPT` **byte-for-byte**
  (`cat > "$calls/prompt.$N"` reads all of stdin — read at `89f8ef7`).
- **`BG3`** *(T3)* `sdk` — delivered intact, **two witnesses** (`BG-c`):
  (i) a spy on the client's `query` records a string equal to
  `BIG_PROMPT`; (ii) end-to-end through the fake with no forced scenario,
  `repr(BIG_PROMPT) in outcome.detail`, **and the length relation**

  ```
  len(outcome.detail) == 30 + len(repr(BIG_PROMPT))
  ```

  where `30` is the fixed prefix `"fake_claude: no such scenario "`
  (`B-6`). **The relation is the criterion; the literal is not.** It is
  written here, in §4, as an expression — never as `168 032` — because
  §0 rule 1 makes the criterion win over prose, so a dead literal sitting
  in a criterion outranks a live relation sitting in rationale, which is
  the exact backwards direction (delta gate `NOTE-D4`). The measured
  `162 000` / `168 032` pair is **provenance only** and lives in §9 `E4`.

### EV — tool-events capture

- **`EV1`** *(T3)* A worker run under `sdk` leaves **exactly one**
  `worker.cache_dir()/worker.tool-events.<run_id>.jsonl`, `run_id`
  matching `^\d{8}T\d{6}Z-\d+$`, whose **first** line is
  `{"type": "meta", …}` carrying `surface == "worker"` and the fake's
  `session_id == "fake-session-1"` (`E-a`).
- **`EV2`** *(T3)* The file carries the fake session's events: one line
  with `type == "tool_event"`, `kind == "tool_use"`, `name == "Write"`
  and an `input.file_path` equal to `FAKE_CLAUDE_WRITE_TARGET`, and one
  with `kind == "tool_result"` (`E-a`).
- **`EV3`** *(T3)* The denial pair, both directions. Denied target: one
  `{"type": "denial", "source": "charter", "tool": "Write", …}` line
  whose `reason` is the byte-exact charter message, and the matching
  `tool_result` has `is_error` true. Approved target: **no** `denial`
  line at all, and `tool_result.content == "ok"`. Asserting only the
  first direction would pass a build that recorded a denial for every
  call.
- **`EV4`** *(source scan)* **Capture only.** The scan walks every `.py`
  under `plugins/self-learn/cli/src/self_learn/` for the substring
  `tool-events` and requires **every hit to be in the single file
  `invocation_sdk/events.py`** — **file-scoped, not function-scoped**
  (NOTE-7). That file is the declared exception, named in the assertion
  message, because `_event_log_path`, `write_event_log` and
  `prune_event_logs` all live there; enumerating the three functions
  instead would let a fourth, *reading* function be added beside them and
  pass. Widened from `U-sdk`'s `EV4`, because the consumer this unit must
  not build would live in `worker.py` (`E-c`).
- **`EV5`** *(T2)* **The negative control for `EV1`.** The same run under
  the `cli` param leaves **no** `worker.tool-events.*.jsonl` in
  `cache_dir()` at all (`E-b`).

### FR — flip readiness, not flip

- **`FR1`** `SELF_LEARN_BACKEND_WORKER=sdk` resolves **both**
  `backend_for("worker")` and `backend_for("worker-repair")` to
  `SdkBackend` by identity against an independently imported
  `self_learn.invocation_sdk.SdkBackend` (`FL-a`).
- **`FR2`** *(instrument)* Every criterion **declared `(T2 + T3)` in
  §4** runs on both legs: the module's collected node ids are
  partitioned by param, and the declared-both set has the **same size**
  and the **same base names** on each side. Criteria declared T1, T2-only
  or T3-only are excluded by declaration, not by omission (`FL-c`).
  Recorded with
  `uv run pytest --collect-only -q tests/test_worker_contract.py`.
- **`FR3`** The default is unchanged: with no `SELF_LEARN_BACKEND*` env
  var set and no `invocation` section in `config.yaml`, both worker
  surfaces resolve to `CliBackend`; `registry.KNOWN_BACKENDS ==
  ("cli", "sdk")`; and — *instrument half* —
  `git diff 89f8ef7..HEAD -- plugins/self-learn/cli/src/self_learn/invocation/registry.py`
  is **empty** (`FL-b`).
- **`FR4`** The selector mapping binds where the flip will use it:
  `SELF_LEARN_BACKEND_MINER` and `SELF_LEARN_BACKEND_ANALYST` do **not**
  govern either worker surface, and `SELF_LEARN_BACKEND_WORKER` governs
  **neither** the miner nor the analyst. Four assertions, each set to a
  value that would be visible if it leaked.

### HY — hygiene

- **`HY1`** `test_worker_contract.py` contains no line matching
  `\[\s*"claude"\s*\]` that does not also contain
  `worker._invoke_claude(` — `B-1` restated where it binds, so the
  constraint is visible in the file it constrains.
- **`HY2`** *(source scan)* No test in this module constructs
  `SdkBackend`, `ClaudeSDKClient` or drives a `worker.run()` on the `sdk`
  param without `SELF_LEARN_SDK_CLI_PATH` pointing at the shipped fake —
  scanned over this module's own source, with the `backend` fixture named
  as the single sanctioned setter (`U-sdk` `HG2` restated).
- **`HY3`** The tripwire is untouched **and live**. Two legs: (i)
  `tests/conftest.py`'s sha is `SU4`'s literal; (ii) a **positive
  control** — calling
  `SubprocessCLITransport._find_cli` inside the test raises
  `AssertionError` with the shipped message. Leg (ii) is what
  distinguishes "the tripwire is present" from "the tripwire still
  fires"; a build that replaced its body with `pass` passes every other
  criterion in this document (`B-2`, mutation `M33`).
- **`HY4`** No test in this module writes outside `tmp_path` or the
  redirected `XDG_CACHE_HOME`. Asserted **positively**: after a driven
  `sdk` run, the events file's resolved path is under `tmp_path`; and a
  source scan finds no `Path.home()` call and no `~/.self-learn` literal
  in this module.
- **`HY5`** *(T2)* **— the `cli`-side no-real-claude control (NEW,
  `BLOCKER-1`; legs re-based at `BLOCKER-D1`).** `B-2`'s tripwire is
  **sdk-only** (`B-2a`), so nothing in the suite stopped a `cli` leg from
  executing a real binary. Three legs, all on the `cli` param, all
  policing **claude-resolution rather than `PATH` composition** (`F-c2`):
  1. **No `claude` outside the sandbox is reachable.** Inside every
     `cli`-param test, `shutil.which("claude")` is either `None` or
     resolves **under `tmp_path`**. Never `~/.local/bin/claude`, never
     anything else. This is the assertion that would have caught
     `BLOCKER-1` the moment it was written.
  2. **The shim is the ONLY `claude` reachable** — leg 1's complement,
     stated positively: `shutil.which("claude") == <the shim path this
     fixture wrote>`. Leg 1 excludes the outside world; leg 2 pins which
     inside-the-sandbox binary wins, so a second stray `claude` anywhere
     on the prepended `PATH` fails here. **`PATH` is inherited-plus-
     prepend and that is correct** — a `tmp_path`-only `PATH` kills
     `worker.run()` at `_digest`'s `git` call before any invocation
     (`F-c2`).
  3. **The `os-error` recipe reaches the monkeypatch, not a process**
     (`F-c1`): on that leg the shim's invocation counter is **0** and the
     patched `subprocess.run` recorded exactly one call.

  Legs 1 and 2 are the general guard — one exclusive, one exhaustive;
  leg 3 pins the specific recipe that went wrong. **One control per leg**
  (`Mut-a`): leg 1 → `M43`, leg 2 → `M41`, leg 3 → the `F-c1`-reversion
  open item (§5.1).

---

## 5. Mutation plan

**43 mutations** (`M1`–`M43`). Every mutation is applied to the **built**
code — product code, shipped test file, or fixture, as the row says — the
suite is run, and the named criteria must **redden**. A mutation that
leaves the suite green is a hole in §4 and must be closed before the
gate, not explained away. Rows that record which criteria stay **GREEN**
are negative controls, and their green half is as load-bearing as the red
half.

**`Mut-a` — a mutation breaks the THING TESTED, never the TEST
(NORMATIVE).** Deleting a criterion's assertion is not a mutation of it:
an assertion that is gone cannot fail, so the criterion stops being
*tested* rather than reddening, and the row proves nothing about whether
the criterion could ever have caught anything. The close-out gate found
exactly this in r4's restated `M41` — the row had moved from
*wrong-mechanism* (`MAJOR-D3`) to *no-mechanism*, leaving `HY5` leg 2
with no control at all and its marginal value over leg 1 unproven. The
replacement is a mutant of the **product state** the leg observes.

The rule generalizes and is worth carrying: for a multi-leg criterion,
**each leg needs its own collectible control** — a mutant that reddens
that leg while the others stay green. Where a leg has none, either the
leg is redundant and should be struck, or the control has not been found
yet and the leg is unproven. `HY5`'s three legs now have three distinct
owners:

| Leg | What it asserts | Its control |
|---|---|---|
| 1 | no `claude` resolvable outside `tmp_path` | **`M43`** — a stray `claude` on the inherited `PATH` |
| 2 | the shim is the `claude` that wins | **`M41`** — a second `claude` inside `tmp_path`, earlier on `PATH` |
| 3 | the `os-error` recipe reaches the monkeypatch, not a process | **reverting `F-c1`'s recipe** to r1's non-executable-`PATH` form |

Leg 3's control is *named but not gate-measured* — it is the reversion
of the very defect `BLOCKER-1` found, and it is carried as an **open item
for the code gate** under §5.1's existing discipline rather than written
as a mutation row asserting an unverified redden. Doing otherwise would
be the conditional-credit class this document has now tripped over twice.
`D-26`.

| # | Mutation | Must redden |
|---|---|---|
| `M1` | The `backend` fixture's `"sdk"` param resolves to `CliBackend` (params list correct, resolution wrong) | `PB1`, `PB2`. **The negative control for the whole unit: every other criterion stays GREEN**, having run twice against `cli`. This is the failure this document is most afraid of, and the reason `P-b` requires two independent controls |
| `M2` | The fixture parametrized `["cli"]` only | `PB1`, `FR2` |
| `M3` | `containment_for("worker")` given `stage_on=False` while `write_settings_file` keeps the stage rule | **`WS1` only** (gate-corrected). **`WS3` is NOT credited** — it recomputes Witness B from the shipped `stage_permission_rules` and never reads the containment. **`WS4` is NOT credited** — it runs under `SELF_LEARN_STAGE=0`, where `stage_on=False` is the *shipped* value, so the mutation is a no-op on that leg |
| `M4` | The charter's hatch conjunct and write scope read `containment.write_globs` **alone**, not the union with `write_exact` | `RP3`, `HA2` leg (iii). **`WS1`–`WS4` and `HA2` legs (i)–(ii) stay GREEN** — the batch surface has non-empty `write_globs`, so every batch-surface criterion is structurally blind. Mirrors `U-sdk`'s `M62` (`H-d`) |
| `M5` | `worker.stage_permission_rules` returns the three ledger globs | `WS1`, `WS3` (its **no-proposals-glob half** only — the equality half recomputes from the same mutated function and is blind), and `test_attrib.py`'s shipped grant tests. **`WS4` is NOT credited** (gate-corrected) — it runs under `SELF_LEARN_STAGE=0`, where `stage_permission_rules` is never called |
| `M6` | `SELF_LEARN_STAGE=0` honored by the settings writer but ignored by `containment_for` | `WS4` **only**. Negative control proving `WS4` discriminates the two witnesses rather than reading one twice |
| `M7` | The hatch keyed on `default_mode is None` **alone**, dropping the write-set conjunct | **`HA3` leg (iii) only** (gate-corrected). **Leg (ii) is NOT credited**: `containment_for("miner-reader")` hardcodes `default_mode="default"` and ignores `enforce` entirely, so the miner's first conjunct is *already* false and dropping the second changes nothing — the miner hatch stays closed under the mutant. `M39` is the row that actually controls leg (ii). **`HA1`, `HA2` legs (i)–(ii) and `HA4` stay GREEN** — the worker's write sets are non-empty either way |
| `M8` | The hatch **also** sets `permission_mode="bypassPermissions"` | `HA4` **only**. `HA2` stays GREEN — the write is approved either way; only the fence sees it |
| `M9` | The hatch placed **above** the structural deny | `HA2` leg (ii) (`Bash` approved) |
| `M10` | `write_settings_file` emits `defaultMode` unconditionally | `HA1`, `HA3` leg (i) |
| `M11` | The prompt moved into argv on the worker surface | `BG1`, `BG2`, and `test_worker.py`'s shipped argv-pin test |
| `M12` | The prompt truncated to 128 KiB inside `worker._invoke_claude`, before the spec is built | `BG2`, `BG3` (both witnesses). **`BG1` stays GREEN** — a truncated prompt is still not in argv, which is why `BG1` alone was never the guard |
| `M13` | The `sdk` leg passes `spec.prompt[:65536]` to the client | `BG3` (both witnesses). **`BG2` stays GREEN** — negative control that `BG3` is genuinely per-backend and not reading the `cli` leg's file |
| `M14` | `worker._invoke_claude` re-raises the backend's failure instead of discarding the `Outcome` | `FL1` (ten legs), `FL3`, **`WS5`'s AST leg** (re-raising means the `Outcome` is bound to a name, which the scan forbids), and every shipped worker test that survives a failing invocation |
| `M15` | `_invoke_claude` swallows four of the five kinds; `unavailable` re-raises | `FL1`'s two `unavailable` legs. Records that a blanket `try/except` is not what `F-a` asks for |
| `M16` | A sixth member appended to `invocation.FAILURE_KINDS` with no leg driving it | `FL1`'s set-equality leg. **The negative control for the fail-closed enumeration** (`F-b`) — proves `FL1` fails when a kind is uncovered rather than passing vacuously |
| `M17` | `SdkBackend` carries its own copies of the worker log f-strings instead of reading `LOG_TEMPLATES` | `FL2`'s `monkeypatch.setitem` leg. The default bytes are identical, so **no byte-comparing leg can catch it** — the same shape as `U-seam`'s `M37` |
| `M18` | The repair round's containment built with `containment_for("worker")` instead of `"worker-repair"` | `RP1`, `RP3`, and `test_repair.py`'s shipped repair-settings tests |
| `M19` | The repair invocation handed the **batch** settings path | `RP1`'s `--settings` leg, and `test_repair.py::test_f2_both_invocations_share_one_argv_builder` (shipped) |
| `M20` | `SELECTOR_FOR_SURFACE["worker-repair"]` mapped to `"MINER"` | `RP2`, `FR4`, and `test_invocation.py`'s shipped `RG2` |
| `M21` | `backend_for`'s built-in default changed to `"sdk"` | `FR3`. **This is the flip this unit must not perform**; the row exists so the guard is proved live rather than assumed |
| `M22` | Rung-1's env name changed to `SELF_LEARN_BACKEND_WORKER_SURFACE` | **`FR1`** and `test_invocation.py`'s shipped `RG1`/`RG2`. **`FR4` is NOT credited** (gate-corrected) — its four assertions are *negatives* ("`SELF_LEARN_BACKEND_MINER` does not govern the worker"), and a rung-1 name nothing sets makes every one of them **vacuously true**. A criterion built from negatives cannot detect a selector that stopped working at all |
| `M23` | `write_event_log` moved out of `_drive`'s `finally` | **No `U-sdkw` criterion observes this row** (gate-corrected) — `EV1` has no timed-out-leg variant among this unit's criteria, so the credit as originally stated does not exist. The property is actually guarded by `U-sdk`'s shipped `tests/test_invocation_sdk.py::test_ev3_jsonl_written_at_the_right_path_with_meta_and_survives_a_timeout` (on master, outside this unit) — the gate verified the redden lives there, and no `U-sdkw` criterion can collect it |
| `M24` | The event log's `meta` line drops `session_id` | `EV1` |
| `M25` | The `backend.py` wrapper that records charter denials removed | `EV3`'s denied direction, and `test_invocation_sdk.py`'s shipped `CH9` |
| `M26` | `CliBackend` also writes a `.tool-events.` file | `EV5`. **`EV1`–`EV3` stay GREEN** — negative control that the file is backend-specific (`E-b`) |
| `M27` | A consumer added: `worker._harvest` reads the newest `.tool-events.` file | `EV4`. **No other criterion catches this** — it is the whole reason `EV4` exists (`E-c`) |
| `M28` | `worker.stage_dir()` changed to a path **inside** the ledger home | **`test_attrib.py`'s shipped stage tests only** (gate-corrected). **`WS1` and `WS3` are NOT credited** — both recompute *both* sides from the same mutated `stage_dir()`, so the two witnesses agree on the wrong path and the comparison is blind. Add `WS6` to this row **only if** build-time verification shows it reddens (the installed destination is resolved from the bucket, not the stage, so it may not). Records that the stage's out-of-repo placement is load-bearing for the attribution claim — and that **this unit's own criteria do not guard it**; the shipped `U-attrib` tests do |
| `M29` | `Outcome.stdout` populated with the session text on the worker surfaces | `WS5`'s behavioral leg, and `test_invocation_sdk.py`'s shipped `OU7` |
| `M30` | The repair surface's timeout reads `invoke_timeout_secs()` | `TO2`, `TO3`, and `test_repair.py::test_e1_timeouts_read_not_hardcoded` (shipped) |
| `M31` | The `sdk` leg's `asyncio.wait_for` timeout hardcoded to `1800` | `TO1`'s `sdk` leg, `TO3`. **The `cli` legs stay GREEN** — negative control that `TO` is genuinely per-backend. **Runner note (NOTE-2): as written this mutation does not redden, it HANGS** — the `hang` scenario sleeps past any test bound, so a 1800 s `wait_for` blocks the suite for 30 minutes. `TO1` must therefore carry its own **outer** bound (an assertion that `run_sync` returned within `spec.timeout * 8`, or a `pytest.fail` from a watchdog), and the mutation is run with that bound in place. A mutation that hangs the runner is not a redden and must not be scored as one |
| `M32` | The `repair ` label dropped from the repair `SessionSpec` | `TO2`'s byte leg, `RP3`, **`RP4` assertion 2** (the second invocation's surface is read from the captured spec, which `label` selects), and `test_repair.py`'s shipped label assertions |
| `M33` | `tests/conftest.py`'s tripwire body replaced with `pass` | `HY3` leg (ii) **and** `SU4`'s sha. **Every SDK criterion in the whole suite stays GREEN** while a real, credentialed session becomes possible again — which is why leg (ii) is a positive control and not a presence check |
| `M34` | A test in this module constructs `SdkBackend` without `SELF_LEARN_SDK_CLI_PATH` | `HY2`; and, if it ran, `HY3`'s tripwire fires |
| `M35` | This unit edits `tests/shims.py` to add a stage-write default | `SU4` clause (a)'s sha, `SU2`, `SU3` row 3's deletions column. Records that the additive bound is mechanical, not honor-system |
| `M36` | `Fake-3`'s `ok_write_real` writes the target file **unconditionally**, ignoring the permission response | `WS6` cells (ii) on the `sdk` param. **`WS2` and `EV3` stay GREEN** — the charter still denies and still records the denial; only the *filesystem consequence* diverges. This is the negative control for `FK3-a`, and the reason the scenario must branch on `behavior` rather than just emit blocks. *(r1's hedged "and `RP4`'s installed-bytes leg once the batch grant is narrowed" is **dropped** — `RP4` drives an approved path throughout, so it is unaffected; a mutation row may not carry a conditional it has not verified.)* |
| `M37` | A test in this module resolves `worker.cache_dir()` without the redirected `XDG_CACHE_HOME` | `HY4` |
| `M38` | The sanctioned fixture edit made **non-additively** — `_scenario_ok_write` rewritten in place to write, and registered under the **existing** `"ok_write"` key, instead of adding `ok_write_real` alongside it | `SU4` clause (b) leg 1 (a pre-existing function's per-function sha moves) and leg 2 (the new-names set is empty), and `SU3` row 3's deletions column. **`RP4` and `WS6` stay GREEN** — they would pass against the rewritten scenario, which is exactly why the bound cannot be left to the criteria that use it (`FK3-d`). *(Ambiguity resolved: this row is the **registered-key** reading — the mutant adds no new `SCENARIOS` key, so leg 3 also reddens. A variant that rewrote the function but still registered a new key would redden legs 1 and 2 alone.)* |
| `M39` | **`charter.build_can_use_tool` reads `SELF_LEARN_ENFORCE_SCOPE` from `os.environ`** instead of deriving the hatch from `containment.default_mode` — the `U-sdk` `D-25` violation | `HA3` leg (ii). **This is the row that actually controls that leg** (MAJOR-A): with the variable set, an environment-reading charter opens the hatch on the **miner** containment, whose `default_mode` is hardcoded `"default"` and which must stay closed. `M7` cannot reach it. Also records the design rule `C-10` states — the hatch is a property of the containment **data**, and `charter.py` never touches `os.environ` |
| `M40` | `ok_write_real` ignores the invocation counter and writes the **same body** on every call | `RP4` assertions 3 and 4 (the installed bytes equal round 1's, not round 2's). **The missing negative control for `FK3-b`** (MAJOR-D): without this row, nothing proves the per-invocation body selection is live, and a fake that silently wrote one body forever would leave the repair round looking tested |
| `M41` | **A second `claude` UNDER `tmp_path` but EARLIER on the prepended `PATH` than the shim** — inside the sandbox, ahead of the fixture's own binary | `HY5` **leg 2 only** (the shim is not the `claude` that wins). **Leg 1 stays GREEN** — resolution is still inside `tmp_path`, so the exclusive half sees nothing wrong — and every other criterion stays green, since the impostor answers as the shim would. Gate-measured. **This row is what earns leg 2 its place**: without a mutant that reddens leg 2 while leg 1 holds, leg 2 is unproven decoration next to leg 1 (`Mut-a`) |
| `M42` | An appended module-level rebinding of a pre-existing global in the fake — `SESSION_ID = "attacker-session"` at end of file | `SU4` clause (b) **leg 4**. **Legs 1, 2 and 3 stay GREEN, and so does the additive numstat** — this is the gate's own successful evasion of r1's three-leg form, reproduced as a permanent control. `EV1` also reddens, but only by accident of its hardcoded session literal, and an accident is not a guard |
| `M43` | **A second `claude` earlier on the prepended `PATH`** — the fixture writes its shim, then a stray executable named `claude` is placed in a directory that precedes it (the shipped `~/.local/bin` shape, reproduced inside the test) | `HY5` leg 1 (resolution lands outside `tmp_path`) and, since the stray wins, leg 2. **Every other criterion stays GREEN** — the stray answers exactly as the shim would for the happy path, which is precisely why the guard has to be positive and separate. This is the row the delta gate specified for leg 1 |

### 5.1 Criteria with no mutation row, declared

`SU1`, `SU2`, `SU3`, `SU5` and `FR2` are **instrument criteria** — a
mutation of a recorded command's output is not a code change, and the
build report is the evidence. `SU4` and `FR3` each carry both an
instrument half and a test half; `M35`/`M38`/`M42` and `M21` cover the
test halves respectively. `PB3` and `PB4` are positive controls whose
mutations are `M34` and `M1`. **`HY5` is per-leg** (`Mut-a`): leg 1 →
`M43`, leg 2 → `M41`, leg 3 → the `F-c1`-reversion open item below. A
single pointer at this criterion would hide that one of its three legs is
still uncontrolled, which is the shape §5.1 exists to surface.

**Three items carry declared conditionals, and they are OPEN ITEMS for
the CODE gate, not for a spec round** (delta gate `NOTE-D7`, accepted):
`M28`'s possible `WS6` credit, `M36`'s narrowed-grant behavior, and
**`HY5` leg 3's `F-c1`-reversion control** (`Mut-a`). None can be settled
by reading — all three are claims about what reddens, which only running
them answers. They are flagged here so the code gate inherits them
explicitly; a conditional that reaches the code gate **unflagged** is the
defect, and one that survives *past* it is a claim nobody checked.

**This class has now been tripped three times in this document, each time
in a different disguise, and that is worth stating plainly**: `MAJOR-D3`
(a mutant aimed at a mechanism the criteria no longer policed), the
close-out gate's `M41` finding (a mutant that deleted the assertion
instead of breaking the product — `Mut-a`), and these three declared
conditionals. The common shape is a row that *looks* like coverage
without anyone having collected it.

---

## 6. Builder decisions, made here rather than left open

- **`D-1`** One new test module, `test_worker_contract.py`; no existing
  test file edited, enforced by sha (`SU4`) and by the numstat bound
  (`MT-a`).
- **`D-2`** Three tiers, assigned per criterion (`M-b`). T1 owns
  `run()`'s wiring; T2 and T3 own the two transports.
- **`D-3`** T1 is **not** parametrized over backends (`M-c`) — asserting a
  backend under `install_fake` would assert a value the fixture supplied.
- **`D-4`** The `["cli", "sdk"]` fixture calls `shims.py`'s builder
  rather than requesting `claude_cli_shim_worker`, because a `params=`
  fixture body cannot request another fixture — the reason `shims.py`
  exists at all (`P-a`).
- **`D-5`** The parametrization is proved live by **two** independent
  positive controls, backend identity and `SdkOutcome` asymmetry
  (`P-b`), because `M1` leaves everything else green.
- **`D-6`** The write-scope agreement is asserted by **decision on a
  concrete path**, not by comparing the charter's regexes to the settings
  file's rule strings (`S-a`).
- **`D-7`** `SELF_LEARN_STAGE=0` is the negative control for the
  write-scope group, not an extra case (`S-b`, `WS4`).
- **`D-8`** `FAILURE_KINDS` is enumerated **from the contract module**, and
  the driven set is asserted equal to it (`F-b`), so a later sixth kind
  reddens instead of hiding.
- **`D-9`** The `>128 KiB` sdk leg uses **two** witnesses — a `query` spy
  and the fake's echo — because neither alone separates our truncation
  from the transport's (`BG-c`).
- **`D-10`** The fake's echo behavior, on which `BG3` rests, is
  **sha-pinned** by `SU4` rather than left implicit — nothing else in the
  suite depended on it, so nothing else would have noticed it changing
  (`B-6`).
- **`D-11`** Tool-events are **captured and asserted present only**; the
  consumer is `U-corrob`, and `EV4` is widened to all of `src/self_learn/`
  to guard the `worker.py` shape a consumer would most naturally take
  (`E-c`).
- **`D-12`** *(superseded by `D-16`)* r1 asserted the `sdk` leg's
  inability to land a staged file rather than omitting it. `V-2` removed
  the inability; the discipline it expressed — an absence nobody wrote
  down is an absence the flip unit rediscovers the hard way — survives in
  `A-b1` and `R-1`'s narrowed form.
- **`D-13`** **No `03-decisions.md` row.** This unit ratifies no policy;
  the flip's `S-` row belongs to the flip unit.
- **`D-14`** The registry's default table is **not touched**, and `FR3`'s
  instrument half (`git diff … registry.py` empty) is how that is
  checked rather than asserted (`FL-b`).
- **`D-15`** Findings are **routed, not fixed** (§7.5). A product-code
  change of any size ends this unit's mandate.
- **`D-16`** *(ruling `V-2`)* The shipped fake gains **one** scenario,
  `ok_write_real`, which writes **iff the charter allowed** (`FK3-a`).
  The trade the operator ruled on: leaving the repair round's `sdk` path
  untested until burn-in is the worse risk, and the fake's armor value
  survives an addition that is additive and pinned. The bound is a
  **per-function** sha rather than a whole-file one (`FK3-d`), so the
  authorized growth and an unauthorized rewrite are distinguishable —
  `M38` is that distinction's negative control.
- **`D-17`** *(ruling `V-2`)* The fake gains a **per-invocation counter**
  mirroring the bash shim's `CTR` / `CLAUDE_SHIM_SCRIPT_$N` discipline
  (`FK3-b`), so one parametrized fixture can script both repair rounds on
  both legs. Two rounds writing identical bytes would collapse "changed"
  and "valid" into one observation.
- **`D-18`** *(ruling `V-1`)* The burn-in gates are **cited, not
  re-derived** (`FL-d`). The gate-keeper is the operator, attended by
  design; this unit builds no machine gate and treats the runbook and the
  plan as the authoritative register.
- **`D-19`** *(rulings `V-3`, `V-4`)* Tool-events privacy obligations
  attach at the **surfacing boundary**, not at capture (`R-4`); the
  denial-count invisibility is a **real finding**, recorded as `R-9` and
  an `FW` row, and is not fixed here because it is product code
  (`D-15`).
- **`D-20`** *(gate `BLOCKER-1`)* The `cli` `os-error` leg is a
  `subprocess.run` monkeypatch, **never** a non-executable file on
  `PATH` — `execvp` skips those and keeps searching, so the r1 recipe
  executed the host's real CLI (`F-c1`). `PATH` inside a `cli`-param test
  is **replaced**, not prepended (`F-c2`), and `HY5` is a **new
  criterion** because `B-2`'s tripwire is sdk-only and nothing guarded
  this side.
- **`D-21`** *(gate `BLOCKER-2`)* Cross-backend log **byte-identity is
  claimed only where it is true** — `timeout` (first line), `not-found`,
  `unavailable`. `exit` asserts template provenance and shape, because
  `rc` is fixture-determined on one leg and synthesized on the other.
  `os-error` cannot match at all, and that divergence is **routed as a
  product finding** (`R-10`) rather than tested around.
- **`D-22`** *(gate `MAJOR-C`)* One capture mechanism, named once
  (`M-c1`): `monkeypatch.setattr` on the **package-level**
  `invocation.write_session`, with the `BK-a` mirror trap spelled out.
  The `sdk` option set is read by calling the shipped `options_kwargs`
  on the captured spec (`M-c2`), never re-derived.
- **`D-23`** *(gate `SU4` evasion)* Clause (b) gains a **fourth leg** over
  the file's top-level non-`FunctionDef` statements, because the gate's
  module-level rebinding passed the first three. Function shas are taken
  from the **runtime binding**, not an AST first match — the choice that
  caught the gate's shadowing attempt, kept deliberately and documented
  so it is not "simplified" away.
- **`D-24`** *(gate `MAJOR-D`)* `RP4`'s third assertion observes the
  **installed** bytes, not two values the test supplied. A mutation row
  (`M40`) covers `FK3-b`'s counter, which nothing checked.
- **`D-25`** *(delta gate `BLOCKER-D1`/`D2`/`MAJOR-D3`)* The `cli`-side
  no-real-claude guarantee is a property of **claude-resolution**, not of
  `PATH` composition (`F-c2`). `PATH` is inherited-plus-prepend because
  `worker.run()` needs `git` before it needs `claude` (`P-c1`); `HY5`
  legs 1 and 2 make the resolution exclusive *and* exhaustive; and the
  mutation rows target the property's own assertions (`M41`, `M43`),
  never the mechanism — a mutant of a mechanism the criteria no longer
  police is a credit nobody can collect.
- **`D-26`** *(close-out gate)* A mutation breaks the **thing tested**,
  never the **test** (`Mut-a`): deleting an assertion stops a criterion
  being tested rather than reddening it. Multi-leg criteria therefore get
  **per-leg** controls, and a leg without one is either redundant or
  unproven — never silently credited. `HY5`'s three legs are owned by
  `M43`, `M41`, and a declared code-gate open item respectively.

---

## 7. Out of scope, look-alikes, and residuals

### 7.1 Out-of-scope look-alikes

| Site | Why it stays out |
|---|---|
| `worker._spawn_window`, `worker._notify`, `worker._notify_with_ids`, `worker._digest` | Not model invocations. `U-seam` §7.1 enumerated them; this unit adds nothing and asserts nothing about them |
| `miner._invoke_reader` | The miner's own Wave-2 unit owns it |
| `analyst.analyze` | `U-sdka` owns it, together with `FW-87`'s bare-`OSError` fix |
| `containment_for("analyst")` / `("miner-reader")` | `S-c` — `U-sdk`'s `CH` group owns them |
| `plugins/self-learn/ui/**` | Untouched; `MT-a` row 2 is the bound |

### 7.2 Not built, with reasons

- **No flip.** `FR3` is the guard. The worker flips last, after the
  analyst and miner burn-ins.
- **No tool-events consumer.** `U-corrob`, post-burn-in. `EV4` is the
  guard.
- **No *second* fixture extension.** `V-2` sanctioned exactly one
  scenario (§3.10). A second scenario, a change to an existing one, or
  any edit to `shims.py` or `backends.py` is outside the sanction and
  fails `SU4`.
- **No product-code fix**, of any size, for anything found on the way
  (§7.5).
- **No retry, no backoff, no streaming, no cost reporting.** None is
  shipped on the worker surfaces on either backend.

### 7.3 Residuals this unit accepts, with owners

**Ten residuals.** `R-1` was narrowed by ruling `V-2` (a coverage hole
became a statement about what a fixture can prove); `R-8` was **rewritten
at the gate** — its hazard model was wrong, not merely incomplete;
`R-9` came from ruling `V-4` and `R-10` from the gate's `BLOCKER-2`
investigation.

- **`R-1` — NARROWED by ruling `V-2`. The write happens in the fake's own
  process, not through a tool executor.** r1's residual — *"the repair
  round is unreachable end-to-end under `sdk`"* — is **CLOSED**: §3.10's
  `ok_write_real` makes it reachable, and `RP4` is now the end-to-end
  test rather than a trip-wire on its absence. What remains is smaller
  and cannot be closed in any suite: `ok_write_real` writes from the
  scenario body **after** reading the permission response, so `WS6`
  proves *the charter's verdict and the resulting filesystem state
  agree*; it does **not** prove that a real SDK tool executor honors a
  verdict, because none runs (`A-b1`). That is a live-session property
  and folds into `R-2`. Owner: a new `FW` row recording the narrowed
  form, so the flip unit reads the current gap and not r1's.
- **`R-2` — no criterion here observes a real model.** Every leg runs
  against a bash shim or the fake CLI. The classes only a live session
  can surface — a model that ignores the charter's deny reason, a
  `ResultMessage` shape the SDK changes, rate limits mid-batch — are
  structurally out of reach, exactly as they are for `U-sdk` (`FW-92`
  records the analogous Bedrock case). The burn-in the flip is gated on
  is the experiment. Owner: a new `FW` row.
- **`R-3` — `BG3`'s end-to-end witness rides an undocumented fixture
  behavior.** The fake's unknown-scenario echo (`B-6`) was never
  specified as an interface; this unit makes it load-bearing and pins its
  bytes (`SU4`) but does not promote it to a documented contract. Owner:
  a new `FW` row — trigger is the first unit that wants to change
  `fake_claude.py`'s error path.
- **`R-4` — tool-events privacy attaches at the SURFACING boundary, not
  at capture (ruled, `V-3`).** `worker.tool-events.<run_id>.jsonl`
  carries tool inputs — file paths today, whatever a future tool's input
  carries tomorrow — written to `cache_dir()` with no scan and a
  retention of 20. **Ruled: no design change.** The cache is local-only,
  never committed and never synced, and it already holds unscrubbed
  `worker.log` and batch prompts — this is existing practice, not a new
  exposure. The scan/scrub obligation attaches **if and when** a consumer
  surfaces events into the ledger or the UI. Owner: **`U-corrob`**
  (post-burn-in), plus an `FW` row carrying the sentence *"privacy
  treatment attaches at the surfacing boundary."*
- **`R-5` — `SU4`'s sha pin is over-sensitive by design.** An innocent
  docstring fix in any of the eight whole-pinned armor files, or in any
  pre-existing function of the fake, reddens it. That is the correct
  trade for a unit whose headline claim is *additive only*, and the
  failure message says so. Owner: none — accepted cost, recorded so a
  gate does not read it as a defect.
- **`R-6` — `FR2` counts node ids; it does not read assertions.** It
  proves the declared-both criteria appear under both params, not that
  each *means* the same thing on both legs: a criterion whose `sdk`
  branch asserted something trivially true satisfies it. Two further
  blind spots, both recorded by the blind gate: `FR2` cannot see a
  criterion that was **never declared** `(T2 + T3)` when it should have
  been (declaration is the input, so it cannot audit itself), and it
  cannot see a leg that runs but is skipped at runtime. The calibration a
  reviewer should read instead is `M1`'s row — the mutation that leaves
  everything else green. Owner: none — a stated limit, not a gap to
  close.
- **`R-7` — `WS2`/`WS4`'s frontier is asserted on ONE path per side, not
  on a set.** The full matcher semantics (`**` at segment boundaries,
  `stage-evil/` near-misses) are `U-sdk`'s `CH6`, already shipped and not
  re-derived here. This unit's frontier legs would not catch a matcher
  that was wrong only at a boundary case. Owner: none — deliberate
  non-duplication, recorded so the boundary is visible.
- **`R-8` — REWRITTEN. The `cli` `os-error` leg cannot exercise the real
  transport, and the reason is a hazard, not a flake.** r1 described this
  as *"depends on filesystem permissions… if the leg proves flaky, fall
  back to a monkeypatch."* **That hazard model was wrong**, and the blind
  gate measured the real one: a non-executable `claude` on `PATH` does
  not produce `PermissionError` at all, because **`execvp` skips
  non-executable entries and keeps searching** — so on any host with a
  real `claude` further down `PATH`, the recipe **executes it** (`F-c1`,
  measured: two real spawns). The monkeypatch is therefore not a fallback
  for flakiness; it is the **only** safe recipe, and `F-c1` makes it
  normative. What remains residual is the coverage cost the r1 text
  already named: the `cli` `os-error` leg now proves the *mapping*
  (`OSError` → `failure="os-error"` → the `os_error` template) and not
  the *transport's* behavior under a real `OSError`. Nothing in a suite
  that may never spawn a real CLI can close that. Owner: none — accepted,
  with `HY5` as the standing guard that the unsafe recipe cannot return.
- **`R-9` — a fully-denied `sdk` run and a wrote-nothing run are
  indistinguishable in the operator-visible log (ruled a REAL finding,
  `V-4`).** Measured (§9 `E5`): probe case B, where **every** write the
  model attempted was denied by the charter, produced exactly the same
  `run: FAILED — 1 eligible, 0 valid proposals (last-run not touched;
  staleness alarm is the detector)` line as a run where the model simply
  wrote nothing. The distinguishing information **exists** — the denial
  is in `worker.tool-events.<run_id>.jsonl` with `"source": "charter"` —
  and nothing reads it. Surfacing a denial count in the run line is a
  one-line **product** change, so it cannot land in this unit
  (`D-15`/`D-19`). Owner: **`U-corrob`** or a small operability unit,
  plus an `FW` row carrying the measured evidence above.
- **`R-10` — on `sdk`, a `CharterPatternUnsupported` failure is SILENT in
  `worker.log`; on `cli` the equivalent `OSError` logs its line.** Found
  by the blind gate while checking `FL2`'s byte-identity claim, and
  routed per §7.5 rather than fixed. `SdkBackend` maps
  `CharterPatternUnsupported` to `Outcome(failure="os-error")` and
  returns **without rendering the `os_error` template** — located by
  symbol at `invocation_sdk/backend.py`'s `CharterPatternUnsupported`
  handler, which builds the `Outcome` directly. `CliBackend` on the same
  failure kind logs `run: {label}claude invocation failed ({exc})`. So an
  operator reading `worker.log` after a flipped run sees **nothing** for
  a class of failure that is loud today, and the only trace is the
  `Outcome` the worker discards. This is exactly the shape `U-sdk`'s
  `O-log` exists to prevent, on a path `O-log`'s own criteria do not
  reach. **Not fixed here** — it is product code (`D-15`), and the fix
  direction (render the template before returning) is a one-line change
  with an operator-visible byte. Owner: **the worker-flip decision** or
  a small operability unit; `FW` row carrying the symbol and both
  behaviors.

### 7.4 Handed to `14-forward-work-map.md`

New `FW` rows for `R-1` (in its **narrowed** post-`V-2` form), `R-2`,
`R-3`, `R-4` (with `V-3`'s *surfacing-boundary* sentence and owner
`U-corrob`), `R-9` (with `V-4`'s measured identical-`FAILED`-line
evidence) and **`R-10`** (the `sdk` `CharterPatternUnsupported` log
silence, with the symbol and both backends' behavior; owner the
worker-flip decision or a small operability unit), landing in the same
commit as the build, following the register's existing shape (statement,
source, disposition, trigger). `R-5`–`R-8` stay on this spec.

### 7.5 The no-fix rule, and how a finding is routed (NORMATIVE)

This unit ships no product code (`MT-a` row 1). A contract test that
exposes a **genuine product gap** — a real divergence between the two
backends, not a test defect — is therefore **not fixed here**. **The rule
has now fired twice**: `R-9` (the denial count invisible in the run line,
found by probe) and `R-10` (the `sdk` `CharterPatternUnsupported` log
silence, found by the blind gate while falsifying `FL2`). Both are
one-line product changes with operator-visible bytes, and both are
routed. A finding is recorded in the build report with:

1. the criterion that exposed it, and the exact assertion text;
2. the reproduction, as a command;
3. whether the criterion is written to the **shipped** behavior (and so
   currently reddens) or to the **intended** behavior (and so is marked
   `xfail` with the finding id);
4. a proposed owner — this unit's own follow-up, `U-sdka`, the miner
   unit, or the flip unit.

**The fold decision is the operator's, not the builder's.** A builder who
fixes a product-code divergence "while they are in there" has left the
mandate and must stop and report — the change would land untested by any
spec, in a unit whose entire value is that its diff contains no product
code.

### 7.6 Operator rulings, folded

r1 routed four values questions out. **All four were ruled**, and each
ruling is folded into the normative register above. This section is the
disposition record; it decides nothing on its own, and where it and the
register ever disagree, the register wins.

| # | Question | Ruling | Where it landed |
|---|---|---|---|
| `V-1` | What closes the analyst and miner burn-ins? | **ALREADY ANSWERED** — the approved plan's gates are explicit and ratified. The gate-keeper is the **operator**, attended by design; there is deliberately **no machine gate**. `U-docs` (parallel, Wave 2) writes them into the runbook | New `FL-d` (the four gates, cited as a table, flagged as a citation not a second register); `E-d`; `D-18`. The open-question framing is **struck** |
| `V-2` | Should the shipped fake gain a real-write scenario? | **SANCTIONED, additive only.** Leaving the repair round's `sdk` path untested until burn-in is the worse risk; the fake's armor value survives an addition that is additive and pinned. `U-sdk`'s own spec anticipated additive scenario-table growth | New §3.10 `Fake-3`; may-touch row + `MT-a` row 3; `SU2`, `SU3`, `SU4` clause (b); `RP4` **rewritten** from trip-wire to end-to-end test; `WS6` **rewritten** symmetric; `A-b`/`A-b1`; `B-4` demoted to provenance; `R-1` narrowed; `M36` rewritten, `M38` new; `D-16`, `D-17` |
| `V-3` | Do the tool-events files need the ledger's privacy treatment? | **RULED, no design change.** The cache is local-only, never committed, never synced, and already holds unscrubbed worker logs and batch prompts — existing practice. Obligations attach at the **surfacing boundary** | `R-4` rewritten with owner **`U-corrob`** and the boundary sentence; `FW` row in §7.4; `D-19` |
| `V-4` | Should an `sdk` run surface its denial count? | **REAL finding, correctly routed.** Not this unit's to fix — it is a one-line product change | New residual `R-9` carrying the measured identical-`FAILED`-line evidence; `FW` row in §7.4; `D-19` |

---

## 8. Verify-at-build ledger

**Every row was measured for this spec on this worktree at `89f8ef7`,
and every row must be RE-CONFIRMED at build time** — from the source or a
live run, never from this document and never from memory. A row that
fails re-confirmation is **reported, not worked around**.

| # | Question | Measured at `89f8ef7` | How to re-confirm |
|---|---|---|---|
| 1 | The suite baseline | 1873 collected, **1868 passed, 5 skipped, 0 failed**, rc 0, 264.84 s | `uv run pytest -q` from `plugins/self-learn/cli`, rc read **unpiped** |
| 2 | pyright whole-`src` | **50 errors, 0 warnings** | `pyright --pythonpath .venv/bin/python src` from `plugins/self-learn/cli`. This unit's required **delta is 0** — trivially, since it ships no product code |
| 3 | Shim-fixture census | `claude_cli_shim_worker` **112**, `claude_shim` **7**, `claude_cli_shim_analyst` **17** | `uv run pytest --fixtures-per-test --color=no -q`, then `grep -cE "^<name> -- "`. **`--color=no` is mandatory** or every count reads 0 |
| 4 | Armor file shas | `SU4` clause (a)'s **eight** whole-file literals; clause (b)'s per-function shas for `fake_claude.py` | `git show 89f8ef7:plugins/self-learn/cli/<path> \| sha256sum` — **from the commit, never the working tree** (`U-seam` `D-27`). Clause (b)'s per-function shas are taken from the same `git show` output, parsed with `ast`, never from the edited working file |
| 5 | **No** scenario in the fake at base writes | **CONFIRMED** — `_scenario_ok_write`'s body is one `_request_permission` and three `emit(...)` calls; no `open`, no `write_text`; no other scenario writes either | Re-read every function in `SCENARIOS`. This row is **why §3.10 exists**; after the build it must still hold for the **ten base scenarios**, with `ok_write_real` the only writer (`FK3-d` leg 3) |
| 6 | >128 KiB round-trip on `sdk` | **CONFIRMED** — 162 000-byte prompt; `outcome.failure == "exit"`, `repr(prompt) in outcome.detail` **True**, `len(detail) == 168 032`; the log line truncated at the template's 400-char `detail_cap` while `Outcome.detail` stayed raw | Re-run the probe of §9 `E4` |
| 7 | The charter frontier at the worker | **CONFIRMED** — stage target approved (`tool_result` `"ok"`, no denial); ledger `proposals/` target denied with `self-learn invocation charter: Write write scope does not include <path>` and one `denial` line `"source": "charter"` | Re-run §9 `E5` cases A and B |
| 8 | The hatch at the worker | **CONFIRMED** — `SELF_LEARN_ENFORCE_SCOPE=0` approved the same ledger write the enforced run denied, and the cli settings file for that run omitted `defaultMode` | Re-run §9 `E5` case C |
| 9 | The events file | **CONFIRMED** — `worker.tool-events.20260819T092929Z-<pid>.jsonl` in `cache_dir()`; meta line carries `surface: worker`, `session_id: fake-session-1`, `failure: null` | Re-run §9 `E5`; re-read `invocation_sdk/events.py`'s `_event_log_path` and `write_event_log` |
| 10 | The four `sdk` failure kinds | **CONFIRMED** — `exit` (`error_result`) rc 1 detail `boom`; `timeout` (`hang`, 1.5 s) rc `None`; `os-error` (`CharterPatternUnsupported`); `not-found` (`SELF_LEARN_SDK_CLI_PATH` at a nonexistent path). Log lines byte-identical to the cli worker templates. **The tripwire never fired on the `not-found` leg** | Re-run §9 `E6`. If the `not-found` leg ever trips the tripwire, the leg is unsafe and must be reported, not re-shaped |
| 11 | `containment_for`'s two worker rows | **CONFIRMED** — `"worker"`: stage glob when `stage_on` else three ledger globs, `write_exact=()`, `strict_mcp=True`; `"worker-repair"`: `write_globs=()`, `write_exact=tuple(write_exact)`, `strict_mcp=True`; both `default_mode="default" if enforce else None` | Re-read `invocation/contract.py::containment_for`. **`M4`'s whole argument rests on this row** |
| 12 | Test counts per module | `test_invocation.py` **61**, `test_invocation_sdk.py` **80**, `test_worker.py` **53**, `test_repair.py` **55**, `test_u_fake.py` **17**, `test_attrib.py` **47** | `grep -cE '^def test_' <file>` |

---

## 9. What was executed, and against what oracle

Measurements taken while writing this spec, on `89f8ef7`, in a clean
worktree. A builder who cannot reproduce these should stop.

| # | Measurement | Command | Result |
|---|---|---|---|
| `E0` | The tree is clean at base | `git status --porcelain`; `git rev-parse HEAD` | **empty**; `89f8ef7e664f973791836e660bc137ab6bd8e937`. Every sha in `SU4` is therefore a base-commit sha |
| `E1` | CLI suite baseline | `uv run pytest -q -p no:randomly` in `plugins/self-learn/cli`, rc read unpiped | **1868 passed, 5 skipped**, 264.84 s, **rc 0**. *(`-p no:randomly` was a **no-op**, measured: `pytest_randomly`, `pytest_random_order` and `xdist` are all absent from the venv. The figure is therefore the project's own `uv run pytest -q` figure, which is the command `SU1` and §8 row 1 name.)* |
| `E2` | pyright baseline | `pyright --pythonpath .venv/bin/python src` | **50 errors, 0 warnings, 0 informations** |
| `E3` | Shim-fixture census | `uv run pytest --fixtures-per-test --color=no -q`, then `grep -cE` per name | `claude_cli_shim_worker` **112**, `claude_shim` **7**, `claude_cli_shim_analyst` **17** — **119** worker-shim consumers in total. *(The mandate's "~190 bash-shim tests" is the wider armor: 119 shim-driven plus `test_invocation_sdk.py`'s 80 fake-CLI tests = 199. Recorded rather than rounded, since `SU5` pins the parts.)* |
| `E4` | >128 KiB prompt over the `sdk` leg | a probe driving `SdkBackend().write_session` with a 162 000-byte prompt against `tests/fixtures/fake_claude.py`, `cli_path` set explicitly | `ok=False`, `failure="exit"`, `rc=1`; `repr(prompt) in outcome.detail` **True**; `len(outcome.detail) == 168032`; the emitted log line truncated at 400 chars while `Outcome.detail` stayed raw — confirming `U-seam` `SP-f` at worker scale |
| `E5` | `worker.run()` under `SELF_LEARN_BACKEND_WORKER=sdk`, three cases | a probe seeding one pending record, `FAKE_CLAUDE_FORCE_SCENARIO=ok_write`, varying `FAKE_CLAUDE_WRITE_TARGET` and `SELF_LEARN_ENFORCE_SCOPE` | **A** (stage target, enforced): approved, `tool_result` `"ok"`, no denial; settings `{"allow": ["Edit(//…/worker.stage/**)"], "defaultMode": "default"}`. **B** (ledger `proposals/` target, enforced): denied, `denial` line `"source": "charter"`, reason `self-learn invocation charter: Write write scope does not include …`. **C** (ledger target, `ENFORCE_SCOPE=0`): **approved**, settings `{"allow": ["Edit(//…/worker.stage/**)"]}` with **no `defaultMode`**. All three: `status == "failed"`, `run: repair round skipped (no eligible refusals)`, one `worker.tool-events.*.jsonl` written. **The `failed` status and the skipped repair round are properties of the BASE fixture** (`E7`) and are the evidence ruling `V-2` acted on; after §3.10 they no longer describe the built suite. The **charter and hatch** results (cases A/B/C) are independent of the fixture's write behavior and stand unchanged |
| `E6` | The four `sdk` failure kinds through `SdkBackend`, with `_find_cli` hard-blocked exactly as `conftest.py` blocks it | a probe over `error_result` / `hang` / a `[`-bearing `write_glob` / a nonexistent `cli_path` | `exit` rc 1 detail `boom`, log `run: claude exited 1: boom`; `timeout` rc `None`, log `run: claude timed out after 1.5s`; `os-error` detail `self-learn invocation charter: unsupported pattern metacharacter …`; `not-found` log `run: claude CLI not found on PATH`. **The tripwire never fired** |
| `E7` | The fake's write scenario performs no write | read of `_scenario_ok_write`, and of every other member of `SCENARIOS` | One `_request_permission`, three `emit(...)`. No filesystem call, in that scenario or any of the other nine. **This measurement is what ruling `V-2` was ruled on**, and §3.10 is the answer; `E5`'s `run: repair round skipped` line is a property of the **base** fixture, not of the built one |
| `E8` | The 128 KiB argv cap is the shipped rationale | read of `worker.build_argv`'s docstring | *"Linux caps one argv element at 128 KiB … The prompt rides stdin instead."* `Big-1`'s risk is sourced from the code, not from the plan alone |

**Measured by the blind gate (r3), not by this author.** Recorded here
because they are now load-bearing and the delta round must be able to
re-check them:

| # | Measurement | Result |
|---|---|---|
| `G1` | r1's `cli` `os-error` recipe, executed | **Two real `claude` spawns** from `~/.local/bin/claude`, exit 1, no session. `execvp` skips the non-executable shim and continues down `PATH`. `B-2`'s tripwire saw nothing. → `BLOCKER-1`, `F-c1`, `HY5` |
| `G2` | Cross-backend log bytes, per failure kind | `timeout` / `not-found` / `unavailable` **match**; `exit` **differs** (fixture `rc=7` vs synthesized `rc=1`); `os-error` **cannot match** — the `sdk` leg logs nothing at all. → `BLOCKER-2`, `F-d`, `R-10` |
| `G3` | `M7` against `HA3` leg (ii) | Leg stays **GREEN**: `containment_for("miner-reader")` hardcodes `default_mode="default"` and ignores `enforce`. → `MAJOR-A`, `M39` |
| `G4` | `SU4` clause (b), two evasion attempts | Attempt 1 (appended shadowing `def`) **CAUGHT** by the runtime-binding `getsource`. Attempt 2 (appended `SESSION_ID` rebinding) **PASSED** all three legs and the additive numstat. → clause (b) leg 4, `M42` |
| `G5` | `MT-a` row 3 achievability | The additive fixture edit lands at **31 insertions / 0 deletions** — row 3's `0`-deletions bound is reachable, not aspirational |
| `G6` | Confirmations of §9's own rows | Baseline, censuses, all eight `SU4` shas, the charter frontier (all three cases **including** the `Bash`-still-denied leg), the >128 KiB oracle premise, the per-function-sha-still-pins-the-echo analysis, `R-9`'s byte-identical `FAILED` line, `WS6`/`WS2` non-covering, `M16`'s fail-closed shape, `M33`'s tripwire controls, and `RP4`'s end-to-end buildability — **all confirmed** |

**Measured by the DELTA gate (r4).** Four of r3's landings were
re-executed rather than read, and one of r3's own fixes was found
unachievable:

| # | Measurement | Result |
|---|---|---|
| `H1` | r3's `PATH`-scrub remedy, executed | `worker.run()` dies at `compose_batch_prompt` → `_digest` with **`FileNotFoundError: 'git'`**, before any invocation — every `cli`-param criterion would fail unobserving. The shipped `claude_cli_shim_worker` docstring already recorded the same thing. → `BLOCKER-D1`, `F-c2` rebased, `P-c1` |
| `H2` | `F-c1`'s monkeypatch recipe | **Genuinely reachable**, with all three of `HY5` leg 3's clauses observed (counter 0, exactly one patched call, `failure="os-error"`) |
| `H3` | `M39` vs `M7` on `HA3` leg (ii) | `M39` **reddens** the leg; `M7` leaves it green — confirming r3's miscredit diagnosis and the new row's necessity |
| `H4` | `SU4` clause (b) leg 4 | **Reddens** the `SESSION_ID` evasion, at **0 deletions** on the sanctioned edit; evasion attempt 1 (append-shadow) still caught by leg 1's runtime binding |
| `H5` | r3's silent repair of the `not-found` recipe | Credited by the gate: r1's `not-found` form was unsafe for the same `execvp` reason and was corrected to a `tmp_path` directory containing no `claude` — same class as `BLOCKER-1`, fixed in the same pass |

**Not measured, and therefore not claimed:** that any of these
containments, prompts or failure legs behaves the same against a **real**
model session. No probe in this document touched one, and none may
(`R-2`).

---

## 10. Revision history

| Rev | Change |
|---|---|
| r1 | Initial draft, written blind against `89f8ef7`. 45 criteria, 37 mutations, 8 residuals (§7.3), 4 values questions routed undecided (§7.6), 1 no-fix routing rule (§7.5). Eight measurements executed (§9), eight of the twelve verify-at-build rows confirmed by probe rather than by reading |
| r2 | **All four operator rulings folded** (§7.6, now a disposition record). `V-1` and `V-3`/`V-4` were bounded edits — a cited gate table (`FL-d`), a rewritten `R-4`, a new `R-9`. **`V-2` was the one that changed the build**: the may-touch gains `tests/fixtures/fake_claude.py` under an additive-only bound, §3.10 `Fake-3` is new, `SU4` splits into a whole-file clause (eight files) and a per-function clause (the fake), and **`RP4` and `WS6` are rewritten** — `RP4` from *"assert the sdk repair round is unreachable"* to *"drive the sdk repair round end to end"*, `WS6` from an asymmetric absence to four symmetric cells. `R-1` narrowed from a coverage hole to a statement about what a fixture can prove. One mutation rewritten (`M36`), one added (`M38`); criteria unchanged at 45, mutations 37 → **38** |

| r3 | **r1 blind gate: NOT SOUND — 2 BLOCKER / 4 MAJOR / 15 NOTE.** All 21 folded; per-finding disposition below. Criteria 45 → **46** (`HY5` new); mutations 38 → **42** (`M39`–`M42`); residuals 9 → **10** (`R-10` new, `R-8` rewritten). Six redden-list corrections (`M3`, `M5`, `M7`, `M22`, `M28`, `M36`) — every one of them a criterion that could not have failed under the mutation it was credited to |

| r4 | **r2 delta gate: NOT SOUND — 2 BLOCKER / 1 MAJOR / 4 NOTE**, all folded; per-finding disposition below. 18 of r3's 21 landings verified clean (4 by re-execution); `BLOCKER-2`, `MAJOR-A`, `MAJOR-C`, `MAJOR-D` **CLOSED**. Every new finding was inside `BLOCKER-1`'s remedy: the `PATH`-scrub was **unachievable** and is re-based on claude-resolution. Criteria unchanged at **46**; mutations 42 → **43** (`M43`); residuals unchanged at **10**; decisions 24 → **25** (`D-25`) |

| r5 | **r4 close-out gate: one row.** 6 of 7 r4 landings verified by execution; both blockers confirmed closed. `M41` replaced with the gate's **measured** discriminating mutant — a second `claude` **under `tmp_path`** but earlier on `PATH` than the shim (leg 1 GREEN, leg 2 REDDENS, all else green), credited to **leg 2 only**. New `Mut-a` (a mutation breaks the thing tested, never the test) and `D-26` (per-leg controls) generalize the finding. §5.1's pointer replaced with the per-leg map; `HY5` leg 3's control declared a code-gate open item rather than credited. **Counts unchanged at 46 / 43 / 10**; decisions 25 → **26**. Folded under the verdict-repricing rule — no further spec gate. **CLEARED FOR BUILD** |

### r5 — per-finding disposition

| Finding | Disposition |
|---|---|
| `M41` has no mechanism | **Replaced** with the gate's measured mutant: a second `claude` under `tmp_path`, earlier on the prepended `PATH` than the shim. Leg 1 stays GREEN (resolution is still inside the sandbox) and leg 2 REDDENS (the shim is not the `claude` that wins) — so the row finally discriminates leg 2 *from* leg 1, which is what earns leg 2 its place. Credited to **leg 2 only**. r4's form deleted leg 2's assertion, and a deleted assertion cannot fail: the row had moved from *wrong-mechanism* (`MAJOR-D3`) to *no-mechanism*, leaving leg 2 untested and its marginal value unproven |
| — generalization | New **`Mut-a`** in §5's preamble: a mutation breaks the **thing tested**, never the **test**; multi-leg criteria get **per-leg** controls; a leg without one is redundant or unproven, never silently credited. New `D-26`. §5.1's one-line `HY5` pointer replaced with the per-leg map (`M43` / `M41` / open item), and §5.1 now names **three** open items and states that this defect class has been tripped three times in three disguises |
| — leg 3 | Its control (reverting `F-c1`'s recipe to r1's non-executable-`PATH` form) is **named but not gate-measured**, so it is carried as a declared **code-gate open item** rather than written as a mutation row claiming an unverified redden — the same discipline `NOTE-D7` established |

### r4 — per-finding disposition

| Finding | Disposition |
|---|---|
| `BLOCKER-D1` | `F-c2` **rebased**: the `PATH`-only-`tmp_path` remedy is struck — it kills `worker.run()` at `compose_batch_prompt` → `_digest`'s `git` call before any invocation, which the shipped `claude_cli_shim_worker` docstring had already recorded (*"filtering PATH broke git"*), and symlinking `git` in would defeat leg 1's own property. Replaced by the **claude-resolution** property, stated positively. `HY5` leg 2 becomes *"`shutil.which("claude") == <the shim path>`"* — leg 1's exhaustive complement. `PATH` stays inherited-plus-prepend. `D-25` |
| `BLOCKER-D2` | The pair resolved coherently in one story: `Par-1`'s `cli` row **keeps** the prepend (now cited as `P-c1`, with the `git` reason); `F-c2`'s prohibition is **replaced**, not weakened; `HY5` polices **the property, not the mechanism**. What stays forbidden: any state where `which("claude")` resolves outside `tmp_path`, or where the `os-error` recipe leaves a real binary reachable — which `F-c1`'s monkeypatch already guarantees by never consulting `PATH` |
| `MAJOR-D3` | `M41` **restated** as the mutant of the *property* (leg 2's which-assertion removed), since r1's `PATH`-composition mutant credited legs that no longer police composition — a fresh instance of the conditional-credit class §5.1 outlaws, caught inside my own fold. **`M43` added** for leg 1: a stray `claude` earlier on the prepended `PATH`, with every other criterion staying green |
| `NOTE-D4` | `BG3`'s length **relation** moved into the §4 criterion as an expression; the `168 032` literal demoted to §9 `E4` provenance. Reason recorded in the criterion: §0 rule 1 makes a criterion outrank prose, so a dead literal in a criterion beats a live relation in rationale — backwards |
| `NOTE-D5` | `HY5`'s bullet corrected to the house id format (`- **\`HY5\`** *(T2)* — …`), so mechanical extraction of §4 counts **46**, not 45. It was the only criterion in the document deviating; verified by grep |
| `NOTE-D6` | `TO1`'s wall-clock note corrected: **~3.5 s is the ADDED kill-ladder cost**, total **~5.0 s** for a 1.5 s spec bound. The `spec.timeout * 8` bound (12 s) clears it |
| `NOTE-D7` | No action, as accepted: `M28`'s and `M36`'s declared conditionals stay **flagged as open items for the code gate**. §5.1 restated to say so explicitly — unflagged is the defect, surviving past the code gate is the failure |

### r3 — per-finding disposition

| Finding | Disposition |
|---|---|
| `BLOCKER-1` | `F-c`'s `cli` `os-error` recipe replaced with a `subprocess.run` monkeypatch; new `F-c1` (the `execvp` fall-through mechanism, measured) and `F-c2` (`PATH` is replaced, not prepended); **new criterion `HY5`** with three legs, since `B-2`'s tripwire cannot see the `cli` side; new `M41`; `R-8` **rewritten** — its hazard model was wrong, not incomplete; `D-20` |
| `BLOCKER-2` | `F-d` replaced with the measured five-kind table; `FL2` split into a byte-identity clause scoped to three kinds (`timeout` first-line only) and a provenance-and-shape clause covering all five; the `os-error` divergence **routed** as `R-10` with an `FW` row; `D-21`. Notes that r1's `F-c` and `FL2` directly contradicted each other on `exit` |
| `MAJOR-A` | `M7`'s credit for `HA3` leg (ii) **struck** — `containment_for("miner-reader")` hardcodes `default_mode="default"` and ignores `enforce`, so the mutant cannot open the miner hatch. New **`M39`** (charter reads `os.environ`, the `U-sdk` `D-25` violation) is the row that controls leg (ii) |
| `MAJOR-B` | Four gate-measured corrections: `M3` → `WS1` only; `M5` drops `WS4` and credits `WS3`'s no-proposals-glob half only; `M28` → shipped `test_attrib` only, with `WS6` to be added **only if** build-time verification shows it reddens; `M22` → `FR1`, not `FR4` (whose negatives go vacuously true) |
| `MAJOR-C` | New `M-c1` names the one capture mechanism — `monkeypatch.setattr` on the **package-level** `invocation.write_session`, with the `BK-a` mirror trap stated explicitly and the in-suite precedent cited. New `M-c2`: the `sdk` option set is read by calling the shipped `options_kwargs(spec)` on the captured spec. `D-22` |
| `MAJOR-D` | `RP4` assertion 3 restated to **installed bytes ≠ `FAKE_CLAUDE_WRITE_BODY_1`** (r1's form compared two test-supplied values and was vacuous); assertion 4 added; new **`M40`** covers `FK3-b`'s invocation counter, which no row reached. `D-24` |
| `SU4` evasion | Clause (b) gains **leg 4** (top-level non-`FunctionDef` statements pinned as a normalized `ast.dump`), because the gate's appended `SESSION_ID` rebinding passed legs 1–3 and the additive numstat. New `M42` makes it permanent. The runtime-binding `getsource` choice is documented with the reason it already earned its keep — it **caught** the gate's shadowing attempt where an AST-first-match form would not. `D-23` |
| `NOTE-1` | `BG3`'s `168 032` replaced by the relation `len(detail) == 30 + len(repr(BIG_PROMPT))` |
| `NOTE-2` | `TO1` gains a **mandatory** `spec.timeout * 8` outer bound; `M31`'s row records that without it the mutation **hangs the runner for 30 minutes** rather than reddening |
| `NOTE-3` | `FAKE_CLI` added to `Mod-1`'s import table, with the one-register reason |
| `NOTE-4` | `FL-c` and `FR2` rescoped from *"every contract criterion"* to *"every criterion declared `(T2 + T3)`"*, matching §4's own tier declarations; `R-6` records the two blind spots that remain |
| `NOTE-5` | `BG1`'s `system_prompt` leg labeled **belt** — unfalsifiable today, kept for the unit that gives the worker a doctrine string |
| `NOTE-6` | `TO1`/`FL2` compare the **first line** on `timeout`; the ~3.5 s measured wall cost is recorded |
| `NOTE-7` | `EV4` restated **file-scoped**, so a fourth reading function cannot be added beside the three writers |
| `NOTE-8` | `B8` spelled as the docstring tag it is (`test_repair.py`'s `B8`), not as a bare identifier |
| `NOTE-9` | `M36`'s hedged, unverified `RP4` entry **dropped** |
| `NOTE-10` | `M38`'s ambiguity resolved to the **registered-key** reading, with the variant reading named |
| `NOTE-11` | `M14` gains `WS5`'s AST leg |
| `NOTE-12` | `M32` gains `RP4` assertion 2 |
| `NOTE-13` | `SU1` records the expected **+60–90 s** wall-time cost |
| `NOTE-14` | `P-a`'s claim that a `params=` fixture cannot request another fixture **corrected** — `request.getfixturevalue` works. The design is kept on the honest ground: `getfixturevalue` would drag a bash shim onto `PATH` in the `sdk` param, which `HY5` forbids |
| `NOTE-15` | Wall-time, tier-declaration and register-consistency wording folded into the sections above; no separate landing |

Counts live in §4's header and §5's header and are not restated here —
one register per fact.
