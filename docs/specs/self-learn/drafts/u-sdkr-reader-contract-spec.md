# Spec — U-sdkr: the miner-reader's SDK contract, and its containment holes closed

Status: **r4 — DELTA-GATE FOLD APPLIED (r3 returned 0 BLOCKER / 2 MAJOR
/ 4 NOTE; all remedies folded. r2 had returned NOT SOUND: 0 BLOCKER / 7
MAJOR / 12 NOTE).** §8's four values questions are
**ruled**; `VB-1` is an **operator preflight item**, not a build blocker
(`MAJOR-5` ruling, §8.1). Written against a clean
worktree at the Wave-1 merge. Every symbol quoted here was read at that
commit; every count in §9 was measured by this author, not inherited.

**Base commit:** `89f8ef7` (master — "Merge branch
`worktree-agent-a3427ef09e35fbd9d` (U-fake) — Wave 1 complete"). Wave 1
landed `invocation/` (U-seam), `invocation_sdk/` + `provider.py`
(U-sdk, U-bedrock) and the three-tier test harness (U-fake).
`miner.py`, `invocation/contract.py` and `tests/test_invocation.py` are
uncontended at this commit.

**The unit in one sentence.** Give the miner's reader surface a
`["cli", "sdk"]` contract suite that pins its output contract, its
timeout semantics and its sweep semantics identically on both backends,
close the two containment holes that would otherwise ship silently on
the flip, and leave the reader's default backend **`cli`** so the flip
itself is a later one-line config change.

**This unit does not flip the miner.** The reader stays on `cli` at
every rung. The flip waits on the analyst's burn-in and is `U-sdka`'s
successor's business, not this unit's. A builder who finds themselves
editing `registry.py`'s resolution chain, or setting
`SELF_LEARN_BACKEND_MINER` anywhere outside a test's own `monkeypatch`,
has left this unit's mandate and must stop and report.

**This unit does change one shipped byte on a live path.** That is the
exception, it is deliberate, it is `Fix-1`, and §8 `Q-1` routes it to
the operator **before** the build starts. Everything else this unit does
is additive tests.

---

## Files this unit may touch

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/miner.py` | **`build_reader_argv`'s return list and docstring only** (`Fix-1`, §3.2). **Numstat-bounded**: `git diff --numstat 89f8ef7..HEAD -- …/miner.py` reports at most **9 insertions and 1 deletion**, **entirely inside `build_reader_argv`'s AST range** (`MC5`). **No hunk-count clause** — `MAJOR-2`: the flag and the docstring sentence sit ~9 lines apart, so the change is **two** hunks at the default `-U3` and **one** at `-U5` (`E15`, measured). If a hunk count is wanted, pin `git diff -U5`; the AST-range clause is what carries the real meaning and is the one that binds. `_invoke_reader`, `write_reader_settings`, `READER_DISALLOWED_TOOLS`, `spool_dir`, `OUTPUT_BASENAME` and `INVOKE_TIMEOUT_SECS` are **not** touched. |
| `plugins/self-learn/cli/src/self_learn/invocation/contract.py` | **One word** (`Fix-1`, §3.2): `strict_mcp=False` → `strict_mcp=True` inside `containment_for`'s `if surface == "miner-reader":` block. **Numstat-bounded**: **exactly 1 insertion and 1 deletion**, one hunk (`MC6`). No other line in the module changes — this renegotiates U-sdk `E-1`'s *"`contract.py` stays byte-frozen"* narrowly and only here (§3.2 `F-c`). |
| `plugins/self-learn/cli/tests/test_invocation.py` | **The single enumerated armor site** (§3.2 `F-d`): the line `assert spec_miner.containment.strict_mcp is False` inside `test_cn2_call_site_containment_matches_the_call_site_table`. **Numstat-bounded**: at most **4 insertions and 1 deletion**, one hunk, inside that one function (`MC7`). Nothing else in this 1997-line file changes. This is a **spec-level** freeze (U-fake `V-1`, U-sdk's bounded precedent), not a mechanically enforced one — see `E5`. |
| `plugins/self-learn/cli/tests/shims.py` | **Additive only** — one new builder, `write_reader_claude_shim` (§3.4 `T2-b`). **Numstat-bounded**: at most **70 insertions and 0 deletions**. `write_worker_claude_shim` and `write_analyst_claude_shim` are untouched, so `SH1`'s two pinned shas stay valid (`E9`). |
| `plugins/self-learn/cli/tests/fixtures/fake_claude.py` | **Additive only** — one new scenario function plus its one `SCENARIOS` row (§3.4 `T2-c`). **Numstat-bounded**: at most **55 insertions and 0 deletions**. No existing scenario changes. Free of any pin — `E6`. |
| `plugins/self-learn/cli/tests/test_reader_contract.py` | **NEW.** Every criterion in §4 lands here unless it says otherwise. |
| `docs/specs/self-learn/03-decisions.md` | New rows `S-39`, `S-40` (§7.5), landing in the same commit as the build. **Exactly two rows**, at exactly those ids. |
| `docs/specs/self-learn/14-forward-work-map.md` | **FIVE new rows** (`MAJOR-6`), landing in the same commit, at consecutive ids starting **FW-95** (`E10`): `FW-95` = `R-1` (stale `_miner_argv` mirror), `FW-96` = `R-2` (analyst's identical gap, owner nobody, cites `F3`), `FW-97` = `R-3` (reader budget vs `max_turns`, owner the miner-flip decision), `FW-98` = `R-4` (`strict_mcp` as second witness), `FW-99` = **`Mit-c`'s watch-run carrier** — the row that carries the watched-first-nightly obligation and `Mit-a`'s operator preflight command forward into a home outside this spec (`Mit-c1`). r2 listed only four; the watch row is what keeps `MAJOR-5`'s enforcement from living only in a draft. |

**No other file may be edited.** In particular, and each for its own
reason:

- `invocation/registry.py` — the resolution chain and the `cli` default.
  Not this unit's, at any rung (`Flip-1`). It also carries U-sdk `RS5`'s
  own numstat bound, which this unit must not consume.
- `invocation_sdk/charter.py`, `invocation_sdk/lifecycle.py`,
  `invocation_sdk/backend.py` — the charter and lifecycle internals. This
  unit **observes** them on the reader surface; it changes none of them.
- `worker.py`, `analyst.py`, `provider.py` — other surfaces' product
  paths. The analyst's identical missing flag is `R-2`, not a fix here.
- `tests/conftest.py` — the spawn tripwire and the autouse defaults.
  Untouched, and every SDK-driving test in this unit obeys the tripwire
  by setting `SELF_LEARN_SDK_CLI_PATH` first (`HY3`).
- `tests/test_miner.py` — the seven shipped `_invoke_reader` monkeypatch
  tests live here and survive **byte-identical** (`SU3`). This is a
  criterion, not a preference.
- `tests/test_invocation_sdk.py`, `tests/test_u_fake.py`,
  `tests/test_lock_invariant.py`, `tests/test_attrib.py`, and every T3
  module in U-fake's `GUARDED` set.

---

## 0. Reading order and precedence

1. **§4 (acceptance criteria) and §5 (mutation plan) ARE the spec.**
   Everything else is rationale. Where prose and a criterion disagree,
   **the criterion wins** and the prose is the defect.
2. Every set, table and name is defined **once**, in §3, and referenced
   by name thereafter. A second definition anywhere is a bug in this
   document.
3. Code is located **by symbol plus a distinctive quoted source line**,
   never by bare line number. The one exception is §3.2 `F-d`'s
   enumerated armor site, which is quoted in full precisely so the
   builder does not have to search for it.
4. Read before this document: `miner.py`'s `_invoke_reader`,
   `build_reader_argv` and `write_reader_settings`;
   `invocation/contract.py`'s `containment_for`;
   `invocation_sdk/backend.py`'s `options_kwargs` and `_drive`;
   `invocation_sdk/charter.py`'s `build_can_use_tool`. This spec quotes
   them but does not reproduce them.
5. **Foreign ids carry their unit; bare ids are this document's**
   (`NOTE-5`). Several id namespaces genuinely collide — this spec's
   §3.3 `C-c`/`C-d` are *not* `U-seam`'s `C-c`/`C-d`; its §6 `D-6`/`D-8`
   are not `U-sdk`'s; its `M18`/`M31` are not `U-seam`'s mutations; its
   `SU6` is not `U-sdk`'s; its §2 `B-6` is not `U-fake`'s. **A bare
   backticked id always means this document's own.** Any id belonging to
   another unit is written with that unit's name immediately before it
   (`U-seam` `C-d`, `U-sdk` `O-3`), with one deliberate exception: ids
   appearing inside a **block-quoted source docstring** are reproduced
   verbatim, in the quoted code's own namespace, and are not re-labelled.
6. `U-seam`'s spec is the **older dialect** — no numstat bounds, no
   verify-at-build ledger, no values table. Where its shape and
   `u-sdk-backend-spec.md`'s shape differ, **this document follows
   `u-sdk`'s**, which is the register Wave 2 is written in.

---

## 1. Why this unit exists

### 1.1 What is true today

The reader is the **only** one of the four surfaces that wires a real
`cli_settings_writer` / `cli_argv_builder` pair. `miner._invoke_reader`'s
own docstring says so:

> this is the ONE surface that wires a REAL
> `cli_settings_writer`/`cli_argv_builder` pair (`SP-b`): the other three
> surfaces are forced to close over an already-built argv (`B-4`/no
> settings file at all), so this is the only construction that exercises
> the writer-then-builder chain end to end (`AV3`).

It is also the only surface whose result is a **file**, not a string.
`_invoke_reader` returns a `Path | None`; `Outcome.stdout` is populated
on this surface (`TRANSPORT["miner-reader"].result_stdout == "merged"`)
and **never read by anyone** — `_run_locked` reads
`artifact.read_text(...)`, not `outcome.stdout`. That asymmetry is the
reader's whole contract and nothing currently tests that it survives a
backend swap.

Its containment record, as shipped (`containment_for("miner-reader")`,
measured at `E8`):

```
allowed_tools     = None                       # forced, not caller-supplied
disallowed_tools  = READER_DISALLOWED_TOOLS    # caller-supplied
write_globs       = (f"{spool_dir}/**",)
write_exact       = ()
strict_mcp        = False                      # <-- hole (a)
default_mode      = "default"                  # forced
```

`READER_DISALLOWED_TOOLS` is `worker.DISALLOWED_TOOLS + ",Read,Grep,Glob"`
— nine tools:
`Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch,Read,Grep,Glob`. The
reader gets **no filesystem tools at all**; its entire evidence base
rides in the prompt, because transcript digests are
attacker-influenceable text.

### 1.2 The two holes

**Hole (a) — the reader's CLI argv has no `--strict-mcp-config`.**
`worker.build_argv` emits it and documents why:

> the analyst needs no MCP server, and without the flag it inherits the
> user's, paying startup cost and side effects for tools
> `--allowedTools` will not let it call anyway.

Every word of that applies with **more** force to the reader, which is
allowed *fewer* tools than the worker. `build_reader_argv` omits it
anyway. `U-seam` recorded the omission faithfully as
`Containment.strict_mcp = False` and froze it, because `U-seam` changed
no observable byte by construction. This unit is where that record gets
renegotiated, because this unit is where the reader's byte-armor is
explicitly on the table.

**Precision, because the brief that commissioned this unit had it
slightly wrong (`E11`):** the reader is **not** the only surface without
the flag — `analyst.build_argv` has no `--strict-mcp-config` either. The
true statement is narrower and is the one this spec uses: *of the three
surfaces that write a settings file and carry a write scope
(`worker`, `worker-repair`, `miner-reader`), the reader is the only one
whose argv omits it.* The analyst carries no settings file and no write
scope at all — `U-seam` `C-d` records that as a deliberate, faithful
recording of a genuinely weaker boundary. Fixing the analyst is `R-2`,
**ruled at `Q-2`** (no CLI-side analyst fix, ever — the user's `F3`
ruling), and is not in this unit's footprint.

**Hole (b) — nothing pins what the reader gets under `sdk`.** U-sdk's
own residual `U-sdk` `R-12` admits the gap in writing: two of its mutation rows
claim miner coverage that does not exist —

> `M8`'s "`CH2`'s miner leg" (`CH2` has no miner leg to redden); `M13`'s
> "`OU1`'s miner leg" (`OU1` drives no miner `cli_settings_writer`).

So today, on the `sdk` path, **no test asserts** that the reader's write
scope is exactly its spool, that `Read`/`Grep`/`Glob` are denied to it,
that `strict_mcp_config` is on, that `setting_sources` is `[]`, or that
`max_turns` is the MINER default. Every one of those would flip silently
the day someone sets `SELF_LEARN_BACKEND_MINER=sdk`.

### 1.3 What this unit is not

- **Not the flip.** The default stays `cli`. `Flip-1` proves the flip
  *would work*; it does not perform it.
- **Not a change to the registry's default table.** That table's miner
  row is untouched. `U-sdka` owns the analyst row; nobody owns the miner
  row yet.
- **Not a rewrite of the seven shipped `_invoke_reader` monkeypatch
  tests.** They are the Python-level surface `U-seam` preserved on
  purpose, and this unit's tests are strictly additive to them.
- **Not a unification of the miner's divergent log wording.** `U-seam`
  `R-2` still owns that, and it is still operator-visible.
- **Not a timeout redesign.** The reader's 15-minute budget has no env
  override where the worker's does. That asymmetry is `R-3`, routed at
  `Q-4`, not fixed here.

---

## 2. What binds this design from outside it

These are shipped, currently-green facts. Each one removes an option
this unit might otherwise have taken. A builder who trips one of them
has a red suite, not a discussion.

- **`B-1` — `CN10` is an `iff`, and it is what makes `Fix-1` a matched
  pair.** `test_invocation.py::_assert_argv_matches_containment_iff`
  asserts, in both directions:

  ```python
      if containment.strict_mcp:
          assert "--strict-mcp-config" in argv
      else:
          assert "--strict-mcp-config" not in argv
  ```

  **Measured (`E2`):** changing the argv alone reddens exactly this test
  and nothing else in the 1873-test suite. **Measured (`E3`):** changing
  both together turns `CN10` green again and reddens exactly one
  different test, `CN2`. A builder who lands half of `Fix-1` gets a red
  suite either way. This is a gift, not an obstacle — do not weaken it.

- **`B-2` — `test_invocation.py::test_av1_...` recomputes, it does not
  pin.** `assert ["claude", *argv_miner] == miner.build_reader_argv(settings_miner)`
  compares the shim-observed argv against the builder's own output, so it
  is structurally blind to a change made *inside* the builder. It stays
  green through `Fix-1` and **must not be credited** for catching it.

- **`B-3` — `test_miner.py::test_reader_argv_and_settings` does not
  assert the flag's absence.** It asserts `argv[:2]`, the absence of
  `--allowedTools`, the `--disallowedTools` contents, and the settings
  file's one rule plus `defaultMode`. **Measured (`E2`, `E3`):** it stays
  green through `Fix-1`. This is why `test_miner.py` needs no edit.

- **`B-4` — `backend.py`'s argv read set is closed at ONE flag.**
  `test_invocation_sdk.py::test_op13_argv_read_set_is_closed` asserts
  `literals == {"--append-system-prompt"}` over `backend.py`'s source.
  The SDK backend therefore **cannot** see `--strict-mcp-config`, and
  `Fix-1` changes nothing on the `sdk` leg. It sets
  `strict_mcp_config=True` unconditionally already (`U-sdk` `O-3`).

- **`B-5` — `_invoke_reader`'s signature is frozen at
  `(home, prompt)`.** `test_invocation.py::test_su4_invoke_reader_signature_pinned`
  pins the positional parameters and requires any addition to be
  keyword-only with a default. Three shipped shims depend on the arity.

- **`B-6` — the spawn tripwire is session-scoped and autouse.**
  `conftest.py::_no_real_sdk_spawn_tripwire` makes
  `claude_agent_sdk`'s `_find_cli()` raise for the whole run. Any test
  here that drives an SDK session must set `SELF_LEARN_SDK_CLI_PATH`
  **before** the session runs, and must never call `monkeypatch.undo()`
  on a shared fixture instance.

- **`B-7` — the T1 injection point is `invocation.registry.backend_for`,
  never the package re-export.** `tests/backends.py::install_fake` says
  so and U-fake measured it: patching `self_learn.invocation.backend_for`
  is a **silent no-op** because `_dispatch` never reads that binding.

- **`B-8` — a `params=[...]` fixture body cannot request another
  fixture.** This is why `shims.py` exports plain functions (U-fake
  `D-8`/`SH4`) and why this unit adds a third such function rather than a
  third fixture.

- **`B-9` — `shims.py`'s public surface is audited.**
  `test_u_fake.py::test_sh4_shims_public_surface_is_honest` requires
  `__all__` non-empty, **every export to have an in-suite call site**,
  and no export to be fixture-marked. A new builder with no caller
  reddens it.

- **`B-10` — the reader's charter hatch is permanently closed.**
  `hatch_open` is `containment.default_mode is None and bool(write_globs or write_exact)`;
  `containment_for("miner-reader")` hardcodes `default_mode="default"`.
  `SELF_LEARN_ENFORCE_SCOPE` is therefore **unreachable** on this
  surface, and the charter's write-scope decision always runs.

- **`B-11` — `provider_env`'s only channel to the ledger home is
  `spec.cwd`.** `_invoke_reader` passes `cwd=home`. A test that builds a
  `SessionSpec` with any other `cwd` is testing something else.

---

## 3. The change

### 3.1 `Sets-1` — the sets this document uses (NORMATIVE)

Defined once, here; referenced by name everywhere after.

```
SURFACE          = "miner-reader"                  # the only surface this unit touches
SELECTOR         = "MINER"                         # SELECTOR_FOR_SURFACE[SURFACE]
BACKEND_VAR      = "SELF_LEARN_BACKEND_MINER"      # f"SELF_LEARN_BACKEND_{SELECTOR}"
LEGS             = ("cli", "sdk")                  # the T2 parametrization, in this order
ARTIFACT         = miner.OUTPUT_BASENAME           # "mine-output.json"
EARLY_RETURN     = {"timeout", "not-found", "os-error", "unavailable"}
FALL_THROUGH     = {"exit", None}
TIMEOUT_PATCH    = 1.0     # the ONE value monkeypatched into
                           # miner.INVOKE_TIMEOUT_SECS by every TO criterion
```

**`TIMEOUT_PATCH` is defined here and nowhere else (`NOTE-8`).** `K-a`
and `TO3` both depend on it and r2 spelled the value in both places,
which is exactly the second-definition bug §0.2 forbids. It is `1.0`
because `{timeout}` renders that `"1.0"` while `{timeout:g}` renders it
`"1"` — the discrimination `M29` needs. Any builder tempted to change it
must check that property still holds; the shipped `900` does not have
it.

The **seven shipped `_invoke_reader` monkeypatch sites** (`SU3`'s
subject), all in `plugins/self-learn/cli/tests/test_miner.py`, in **six**
containing functions — **five named tests plus one module-level helper**
(`E7`, corrected at r3 by `MAJOR-1`):

```
test_halt_persists_across_slices                 (1 site)
test_run_held_gate_keeps_cursors                 (1 site)
test_failed_reader_keeps_cursors                 (1 site)
test_first_run_initializes_forward_only          (2 sites)   <- the doubled one
test_watchdog_cooldown_after_failed_attempt      (1 site)
shim_reader(monkeypatch, payload)                (1 site) — MODULE-LEVEL HELPER
```

Six containing functions, **1+1+1+2+1+1 = 7** sites (`NOTE-a`: r3's table
said "(1 site)" six times, summing to six against a stated total of
seven, while its own prose correctly placed the doubled site in
`test_first_run_initializes_forward_only`; the table row is now
corrected). r2, earlier, had mis-attributed the doubled site to
`test_run_held_gate_keeps_cursors`, which carries exactly one.

**`shim_reader` is the correction that matters, and it strengthens the
case rather than complicating it.** It is not a test; it is the
module-level helper (`def shim_reader(monkeypatch, payload)`) that every
end-to-end miner test routes its model pass through — and it is called
from **78 call sites across 68 DISTINCT tests** in `test_miner.py`
(`E17`; eight of those tests call it two or three times, which is why the
two numbers differ — `NOTE-c`). **The blast-radius figure is 68**, the
count of tests that would break, not 78. So the Python-level surface
`U-seam` preserved is **an order of magnitude larger than seven tests**:
changing `_invoke_reader`'s name, arity or return contract breaks one
helper and **68 tests** through it. This is precisely why `SU3` leg (i)
— the byte-identity `git diff --quiet` — is the real guard, and the site
count is only its readable companion.

The **enumerated armor site** (`F-d`'s subject), exactly one, in
`plugins/self-learn/cli/tests/test_invocation.py`, inside
`test_cn2_call_site_containment_matches_the_call_site_table`:

```python
    assert spec_miner.containment.strict_mcp is False
```

### 3.2 `Fix-1` — the strict-MCP hole, closed as a matched pair (NORMATIVE)

**`F-a`** `miner.build_reader_argv` gains `"--strict-mcp-config"` as its
**last** element, matching `worker.build_argv`'s placement. The prompt
stays off argv (audit B1); nothing else in the list moves. The docstring
gains a sentence naming this unit and pointing at `worker.build_argv`'s
own rationale rather than restating it — one register, one owner.

**`F-b`** `containment_for`'s `miner-reader` branch sets
`strict_mcp=True`. This is the **record** catching up to the argv, not a
second decision: `Containment` is a description of what the CLI
invocation is, and after `F-a` the description was false.

**`F-c` (NORMATIVE)** `F-a` and `F-b` are **one change, landed together
or not at all.** They are separable in the diff and inseparable in the
suite: `B-1`'s `iff` reddens on either half alone, in opposite
directions. The build report must show both hunks or neither.

**`F-d` (NORMATIVE)** Exactly **one** shipped assertion contradicts
`F-b`, and it is `Sets-1`'s enumerated armor site. It becomes:

```python
    assert spec_miner.containment.strict_mcp is True
```

and gains a comment naming `U-sdkr` so a future reader does not "restore"
it. **No other line of `test_invocation.py` may change** — `MC7`'s
numstat bound is the mechanical form of that sentence. This is the whole
armor cost of `Fix-1`, and it was **measured, not estimated** (`E3`):
the full suite under both halves of `Fix-1` reddens exactly this one
test and no other.

**`F-e`** `Fix-1` changes **nothing** on the `sdk` leg. `strict_mcp` is
read by no production code — the SDK sets `strict_mcp_config=True`
unconditionally (`O-3`), a divergence U-sdk `D-6` already documented. The
field is a CLI-argv record and this unit makes it an honest one. That
`strict_mcp` is a record no production code consumes is `R-4`, **ruled at
`Q-3`**: it stays, as the second witness, and is never derived.

**`F-f`** `write_reader_settings` is **not** touched, so
`test_invocation.py::_HY3_SHAS["write_reader_settings"]`
(`c3d25da3bb14dd0c92dd9d17515162d6fae1f075faab3a34f20d8181176fc722`)
stays valid and is **not** re-pinned. A builder who finds themselves
re-computing that sha has changed something they may not change.

### 3.3 `Cont-1` — the reader's SDK containment, pinned (NORMATIVE)

The reader's SDK-side boundary is asserted **from the `SessionSpec` the
real call site built**, never from a hand-constructed one. That is
`U-seam` `CN2`'s lesson, and it is the difference between testing
`containment_for`'s defaults and testing what `_invoke_reader` actually
sends.

**`C-a`** The unit ships a capture fixture that drives a real
`miner._invoke_reader(home, prompt)` with a `pytest.MonkeyPatch()`-scoped
spy on `invocation.write_session`, returning the captured `SessionSpec`,
the resolved `options_kwargs(...)` mapping, and the outcome. The local
`MonkeyPatch` is undone before the fixture returns — the shared
`monkeypatch` fixture would keep capturing sibling fixtures' calls
(`test_invocation.py::miner_capture` carries that scar and its comment).

**`C-b`** Pinned on the captured spec's containment: `allowed_tools is
None`; `disallowed_tools == miner.READER_DISALLOWED_TOOLS`;
`write_globs == (f"{miner.spool_dir()}/**",)`; `write_exact == ()`;
`default_mode == "default"`; `strict_mcp is True` (after `Fix-1`).

**`C-c`** Pinned on `options_kwargs(captured_spec)`, the mapping
`U-sdk` `OP14` compares against the live options object:

| key | pinned value | why it matters to the reader |
|---|---|---|
| `strict_mcp_config` | `True` | hole (a)'s SDK-side twin |
| `mcp_servers` | `{}` | with `strict_mcp_config`, no MCP server reaches the reader |
| `setting_sources` | `[]` | isolation: no user/project/local settings inherited |
| `settings` | `None` | the charter is the only authority |
| `permission_mode` | `"default"` | never `bypassPermissions`, whatever the host says |
| `allowed_tools` | `[]` | every allow decision goes through the charter |
| `disallowed_tools` | `miner.READER_DISALLOWED_TOOLS.split(",")` | **split at test time**, never a literal list |
| `cwd` | `str(home)` | `B-11`'s provider channel |
| `max_turns` | `60` | `_DEFAULT_MAX_TURNS["MINER"]` |
| `env` | `{}` | under `provider=anthropic`; a leak test, not a formality |

**`C-d`** The **write scope is exactly the spool**, asserted through the
charter callback, in three legs, and at least one leg must be a genuine
end-to-end session (not a direct callback call), because a callback that
is built correctly and never installed is the fail-open shape:

1. `Write` to `spool_dir()/mine-output.json` → **ALLOW**.
2. `Write` to a path outside the spool (a sibling of the spool, and the
   ledger home) → **DENY**, the message names the tool and the resolved
   target, and **the file does not exist on disk afterwards**.
3. `Read` (and `Grep`, and `Glob`) → **DENY at step 1** of `U-sdk` `C-4`'s
   decision order, with the `is disallowed on this surface` wording —
   not the generic step-5 wording. The two messages are different
   strings and the criterion asserts which one fired.

**`C-e`** The deny in leg 2 is recorded: `SdkOutcome.denials` is
non-empty and its entry names `Write`. A charter that denies silently
would leave an operator with a failed run and no reason.

**`C-f`** `containment_for`'s spool glob is rendered from a
`contract.py` string literal (`U-seam` `C-c`'s scalars-only rule).

**Honest statement of what `CT1` can and cannot see (`NOTE-3`,
correcting r2's overclaim).** r2 said this unit "never re-derives" the
glob. That is **not true** of `CT1`: comparing against
`f"{miner.spool_dir()}/**"` re-spells the `/**` suffix, so a mutation
that changed the suffix in `contract.py` *and* in the test together
would pass. What `CT1` genuinely catches is a changed **base** — `M8`'s
widening to the ledger home — because `miner.spool_dir()` is obtained
from the product, not spelled out.

The **independent oracle** is `CT4`/`CT5`, which spell **no pattern at
all**: they hand a concrete path to the live charter and observe
ALLOW/DENY. Those are the criteria to cite as proof the write boundary
holds; `CT1` is the cheap structural companion. Keeping both is right —
`U-seam` `M31`'s lesson is that a *sole* self-comparing witness is
worthless, not that a structural check alongside a behavioral one is.

### 3.4 `T2-1` — the parametrized contract fixture (NORMATIVE)

**`T2-a`** The contract tests are parametrized over `LEGS` by a single
fixture whose body **branches on `request.param`** and calls plain
functions. It requests no leg-specific fixture, because requesting one
would install it on both legs (`B-8`).

```python
@pytest.fixture(params=LEGS)
def reader_leg(request, tmp_path, monkeypatch):
    ...  # cli: write the bash shim, prepend it to PATH, leave BACKEND_VAR unset
    ...  # sdk: SELF_LEARN_SDK_CLI_PATH + CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK
    ...  #      + BACKEND_VAR="sdk" + FAKE_CLAUDE_FORCE_SCENARIO
    yield <a handle carrying: the leg name, and the knobs both legs honor>
```

**`T2-b`** The `cli` leg's shim script is a **new plain function in
`shims.py`**, whose signature carries a **stdout knob** so both legs can
drive `RC3`/`RC4` symmetrically (`MAJOR-3` — the sdk leg's counterpart is
`T2-c` step 6's `FAKE_CLAUDE_RESULT_TEXT`):

```python
write_reader_claude_shim(
    shims_dir, *, argv_log, prompt_log, out_path, body=None, stdout_text=None, exit_code=0
)
```

where `stdout_text` is what the shim echoes on stdout (the `cli` leg's
`Outcome.stdout`, which arrives merged), `body` is what it writes into
`out_path` (omitted = write nothing, which is `RC6`'s case), and
`exit_code` drives `SW2`'s `rc != 0`. It follows the two existing
builders' contract exactly: it writes into an
**already-existing** directory, does its own `chmod`, returns the path,
and creates no directory of its own (`U-fake` `SH-d`). It imports nothing from
`self_learn` and nothing from any `test_*` module (`U-fake` `SH-b`). It must have
an in-suite call site the moment it exists (`B-9`).

**`T2-c`** The `sdk` leg's artifact is produced by a **new scenario in
`fake_claude.py`**. The existing `ok_write` scenario emits a `Write`
permission round-trip but **never writes the file** — so a reader test
built on it would assert `_invoke_reader(...) is None` on every sdk leg
and pass for the wrong reason. The new scenario:

1. reads its target from `FAKE_CLAUDE_WRITE_TARGET` and its body from a
   new `FAKE_CLAUDE_WRITE_BODY` (defaulting to a minimal valid reader
   artifact);
2. performs the real `can_use_tool` control-request round-trip that
   `ok_write` already performs, so the charter genuinely decides;
3. **writes the file to disk if and only if the response allowed it** —
   this is what makes `C-d` leg 2 observable as a missing file;
4. emits the `tool_use` / `tool_result` pair, with `is_error` set from
   the allow/deny outcome;
5. emits a `ResultMessage` whose `is_error` is driven by a new
   `FAKE_CLAUDE_RESULT_IS_ERROR` knob, default false — this is what
   gives the sdk leg an `rc != 0` without a second scenario;
6. **(`MAJOR-3`)** emits that `ResultMessage` carrying a **`result`
   string** driven by a new `FAKE_CLAUDE_RESULT_TEXT` knob, defaulting
   to a **sentinel** distinct from anything else the scenario emits.
   Without this the sdk leg has **no stdout at all**: `_extract_text`
   branch 1 takes `ResultMessage.result` when it is a non-empty string,
   and branch 2 falls back to the final `AssistantMessage`'s text — which
   in this scenario is the **tool_use-bearing** message and therefore
   `""`. This knob is what makes `RC3` (stdout non-empty on both legs)
   and **both directions of `RC4`** (well-formed stdout with no file;
   garbage stdout with a file) expressible on the sdk leg at all.

   **Gate warning, recorded so a builder does not "fix" it the wrong
   way:** putting a text-bearing `AssistantMessage` **before** the
   tool_use message does **not** work as a substitute —
   `_run_session` overwrites `last_assistant_text` on **every**
   `AssistantMessage`, so the later tool_use message's empty text wins.
   Branch 1 via `result` is the only reliable route.

No existing scenario is edited; `SCENARIOS` gains exactly one row.
`SCENARIOS` is referenced nowhere outside the fixture (`E6`), so this is
free.

**`T2-d` (NORMATIVE)** **Both legs drive the real
`miner._invoke_reader(home, prompt)`.** Neither leg may hand-build a
`SessionSpec`, because the writer-then-builder chain, the containment
construction and the early-return dispatch are exactly what is under
test. Hand-built specs are legitimate only in `Cont-1`'s
callback-level legs and `Kill-1`'s recorder legs, which say so.

**`T2-e`** The `sdk` leg reaches `SdkBackend` **through the registry**,
by setting `BACKEND_VAR` — not by injecting `backend=` and not by
patching `backend_for`. That is what makes the parametrized suite double
as `Flip-1`'s evidence: the sdk leg *is* the flip, performed inside one
test's `monkeypatch` scope and unwound at teardown.

**`T2-f`** `FakeBackend` (T1) is used only where the assertion is about
**pure logic** with no transport at all — the recorded `.argvs` /
`.specs` and the failure-kind dispatch. Where T1 is used, it is
installed through `backends.install_fake` (`B-7`) and `PATH` is
sanitized first, so a missed patch fails deterministically rather than
PATH-dependently (U-fake `B-7a`).

### 3.5 `Read-1` — the reader's output contract, on both backends (NORMATIVE)

**`R-a`** **Exactly one artifact.** After a successful run, `spool_dir()`
contains exactly one file and its name is `ARTIFACT`. Asserted as a
directory listing, not as "the artifact exists" — the latter is true of a
spool full of litter.

**`R-b`** **`_invoke_reader` returns the artifact path**, and it
`.is_file()`. On both legs.

**`R-c` (NORMATIVE)** **stdout is never parsed.** Two legs:
(i) `Outcome.stdout` is non-empty on this surface under both backends
(the CLI merges stderr into it; the SDK extracts the assistant text), and
(ii) `_invoke_reader`'s return value is **independent of it** — a run
whose stdout is well-formed JSON but whose spool file is absent returns
`None`, and a run whose stdout is garbage but whose spool file is present
returns the path. The second leg is the one that has teeth: it is the
mutation "parse stdout when the file is missing" that it kills.

**`R-d`** **The artifact's bytes are the model's, verbatim.** Whatever
the leg wrote is what `_invoke_reader`'s caller reads. Neither backend
re-encodes, truncates, or normalizes it. Asserted with a body containing
non-ASCII and a trailing newline, so an encoding or `.strip()` mutation
is visible.

**`R-e`** **The pre-run unlink happens.** `_invoke_reader` unlinks
`out_path` before invoking. A stale artifact from a previous run,
present at entry, must not be returned by a run whose model wrote
nothing: seed the artifact, drive a leg that writes nothing, assert
`None`. Without the unlink this returns a stale path and the miner
re-lands last night's candidates.

### 3.6 `Kill-1` — timeout semantics and the two kill paths (NORMATIVE)

**`K-a`** **`INVOKE_TIMEOUT_SECS` is read at call time.**
`monkeypatch.setattr(miner, "INVOKE_TIMEOUT_SECS", TIMEOUT_PATCH)`
(`Sets-1`; the value is pinned there and not respelled here) must change both
the value handed to the transport and the value rendered in the log line.
Asserted on both legs, and asserted as **two** facts (the transport
saw it; the log shows it) because a captured default satisfies neither
and a display-only field satisfies only the second.

**`K-b`** **The timeout log line is byte-identical across backends.**
`_MINER_TEMPLATES.timed_out` is `"run: claude timed out after {timeout}s"`
— no `{label}`, and `{timeout}` **not** `{timeout:g}`. Both `CliBackend`
and `SdkBackend` render it through `LOG_TEMPLATES["miner-reader"]`. With
`INVOKE_TIMEOUT_SECS` monkeypatched to `TIMEOUT_PATCH` (`Sets-1`), the
criterion discriminates a `:g` mutant, because that value is chosen to
render differently under the two forms. Choosing a value that renders
identically under both is the vacuous form and is forbidden.

**`K-c`** **The kill paths are asserted through RECORDERS, never real
signals.** This is not a style preference: a test that let an unguarded
mutant actually fire would signal the pytest process, and a redden that
destroys the run reporting it is not a usable signal (U-sdk `K-2a`).

- **cli leg:** with a fake `Popen` whose `communicate` raises
  `subprocess.TimeoutExpired`, and `os.killpg` / `proc.wait` replaced by
  recorders reached **through the module** (`invocation.cli`'s `os`),
  assert: `killpg` called once with `(proc.pid, signal.SIGKILL)`;
  `proc.wait()` called after it; `ProcessLookupError` and
  `PermissionError` from `killpg` are each swallowed (two separate
  assertion legs against **one** `except (ProcessLookupError,
  PermissionError)` clause in `invocation/cli.py`'s `killpg` site —
  `NOTE-d`: there is a **second, independent** clause of the same shape
  in `invocation_sdk/lifecycle.py`'s `kill_child`, a **different
  module** guarding a **different** call, exercised by `TO6`, not this
  criterion); and the returned `Outcome.failure == "timeout"`.
- **sdk leg:** drive `lifecycle.run_kill_ladder` directly with a
  hand-rolled client stub (the task object and `_ABANDONED_DISCONNECTS`
  are not observable from outside), and drive `lifecycle.kill_child` with
  `os.kill` / `os.killpg` / `os.getpgid` / `worker._pid_alive` recorders
  patched on `lifecycle`'s module object. Assert the three rungs in
  order: bounded `interrupt()`, **shielded** `disconnect()` (the task
  survives the kill bound, is not cancelled, and is held in
  `_ABANDONED_DISCONNECTS`), then `kill_child`. And assert the pgid
  discrimination both ways: same pgid → `os.kill`, `killpg` never called;
  different pgid → `os.killpg`.

**`K-d`** **The ladder runs on the success path too.** `_drive`'s
`finally` calls `run_kill_ladder` unconditionally. A criterion asserts
the sidecar is present during the session and absent after, on the
reader surface specifically — the sidecar path is
`worker.cache_dir() / "miner-reader.sdk-child.pid"` and no shipped test
exercises that surface's row.

**`K-e`** No test in this unit sends a real signal to any process it did
not itself spawn, and no test in this unit spawns a real `claude`. The
`sdk` leg's child is always `fake_claude.py` via
`SELF_LEARN_SDK_CLI_PATH`; the `cli` leg's child is always the bash shim.

**`K-f` — what `K-c`'s recorder rule does NOT forbid, said plainly
(`NOTE-13`).** `TO2`'s `sdk` leg induces a **real timeout**, which runs
the **real kill ladder** — `interrupt()`, the shielded `disconnect()`,
and `kill_child` sending a **real `SIGKILL`** — against the **fake CLI
child this test itself spawned**. That is **permitted and deliberate**,
and it does not contradict `K-c`: the rule is *never signal a process
the test did not spawn*, above all never the pytest runner's own group.
Signalling one's own fake child is the only way to observe that the
ladder terminates in a sync frame at all, and U-sdk's `KL4` already
does exactly this (its `hang_sigterm_ignored` scenario). `K-c`'s
recorder-only discipline governs the criteria that assert **which**
syscall fires with **which** arguments (`TO4`/`TO5`/`TO6`), where a
real signal would either kill the runner or be unobservable.

### 3.7 `Sweep-1` — the stray sweep, and the two dispatch behaviors (NORMATIVE)

The shipped dispatch, reproduced here once because every criterion in
this section refers to it:

```
outcome.failure ∈ EARLY_RETURN   ->  return None, BEFORE the sweep
outcome.failure == "exit"        ->  fall through: sweep runs, out_path checked
outcome.failure is None          ->  fall through: sweep runs, out_path checked
```

**`S-a`** (WR2-class) On each of the four `EARLY_RETURN` kinds,
`_invoke_reader` returns `None` **and a stray file placed in the spool
beforehand still exists afterwards.** All four kinds are exercised, and
the stray survives all four. Under `sdk` this is not theoretical: U-bedrock's
`U-bedrock` `In-c` table already names the reader's `unavailable` row as
*"returns `None` **before** the stray sweep, spool preserved."*

**`S-b`** (WR3-class) On `rc != 0`, `_invoke_reader` does **not** return
early: the sweep runs, the stray is deleted, and `out_path` is returned
when the model wrote it anyway. On both legs. The sdk leg reaches this
through `FAKE_CLAUDE_RESULT_IS_ERROR` (`T2-c` step 5), which maps to
`failure="exit"` via `_map_result_message`.

**`S-c`** The sweep's log line is byte-exact:
`f"run: stray spool artifact {path.name} deleted"`, one line per stray,
and the artifact itself is never swept. Asserted with **two** strays and
one artifact, so a sweep that deletes the first thing it sees, or that
deletes everything, is visible.

**`S-d`** The sweep deletes files only. A **directory** in the spool
survives it (`path.is_file()` guards the unlink) and does not raise. This
is the leg that keeps a future `IsADirectoryError` from wedging a
nightly run.

**`S-e`** `S-a` and `S-b` are asserted on the **real** `_invoke_reader`,
never on a re-implementation of its dispatch in the test. A test that
re-derives `EARLY_RETURN` and checks membership proves nothing about the
shipped function.

### 3.8 `Flip-1` — flip readiness, not flip (NORMATIVE)

**`FL-a`** With `BACKEND_VAR="sdk"`, `invocation.backend_for("miner-reader")`
returns an `SdkBackend` instance. With it unset and no config, it returns
the shared `CliBackend` — **the default is `cli` and this unit leaves it
there.**

**`FL-b`** Selector scoping, both directions:
`SELF_LEARN_BACKEND_WORKER="sdk"` does **not** move `miner-reader`, and
`BACKEND_VAR="sdk"` does **not** move `worker` or `analyst`. The negative
control matters more than the positive one — a selector map collapsed to
one variable would pass the positive leg alone.

**`FL-c`** The **entire** `Read-1` / `Sweep-1` / `Kill-1` contract suite
passes on the `sdk` leg. That is not a separate criterion so much as the
parametrization's whole point: `LEGS` is `("cli", "sdk")` and a red sdk
leg is a red suite.

**`FL-d` (NORMATIVE)** No file outside a test's own `monkeypatch` scope
mentions `BACKEND_VAR` with the value `"sdk"` after this unit. Asserted
mechanically: a grep over `src/` and over the repo's shipped config and
systemd units finds no `SELF_LEARN_BACKEND_MINER` assignment at all. This
is the criterion that catches "the builder flipped it while proving the
flip works."

**`FL-e`** `registry.py` is byte-identical to base. `git diff --quiet 89f8ef7..HEAD -- …/invocation/registry.py`
exits 0. *Instrument criterion.*

### 3.9 What deliberately does not move

- `_invoke_reader`'s name, signature, arity, spool `unlink`, dispatch
  order and sweep loop — all verbatim (`B-5`, and `U-seam` `D-14`).
- `write_reader_settings` — untouched, sha unchanged (`F-f`).
- `READER_DISALLOWED_TOOLS`, `spool_dir`, `OUTPUT_BASENAME`,
  `INVOKE_TIMEOUT_SECS`, `miner_model` — untouched.
- The miner's log wording (`U-seam` `R-2`).
- `test_invocation_sdk.py::_miner_argv()` — a test-local literal that
  becomes a **stale mirror** of `build_reader_argv` after `Fix-1`.
  Deliberately not updated: `backend.py` cannot read the flag (`B-4`), so
  nothing asserts on it, and touching U-sdk's file for a cosmetic mirror
  buys footprint this unit does not need. Recorded as `R-1`.

---

## 4. Acceptance criteria

**These criteria are the spec.** Each is a named test in
`plugins/self-learn/cli/tests/test_reader_contract.py` unless it says
otherwise. **51 criteria**, in eight groups: `SU` 7, `MC` 7, `CT` 8,
`RC` 7, `TO` 7, `SW` 6, `FL` 5, `HY` 4.

**Legs are stated PER CRITERION, never by group** (`MAJOR-4`). r2 carried
a blanket claim that "`RC`, `TO` and `SW` are parametrized over `LEGS`",
which is false of several of them — `TO4`/`TO5` are `cli`-only recorder
tests, `TO6`/`TO7` are `sdk`-only, `CT4`–`CT8` are `sdk`-only, and `SW1`
is deliberately **unparametrized** (see below). A blanket header that
overstates parametrization is exactly the hazard §5's closing paragraph
warns about: it invites a reader to believe an sdk leg ran where none
did.

Every criterion in the four **backend-sensitive** groups — `CT`, `RC`,
`TO`, `SW` (28 criteria) — therefore carries its own leg marker:
**[both]**, **[cli]**, **[sdk]**, or **[n/a]**. A **[both]** criterion
is met only when **both** legs pass.

The other four groups are **backend-independent by construction** and are
marked **[n/a]** at the group level rather than per criterion (one
register, one statement): `SU` and `HY` are instrument, diff and AST
criteria that run no session; `MC` calls `build_reader_argv` /
`containment_for` as plain functions; `FL` asserts what
`backend_for` *resolves to*, never what a resolved backend *does*.

**`SW1` is unparametrized, and this is deliberate.** Its four
`EARLY_RETURN` kinds are not symmetrically reachable across backends —
the `unavailable` kind is reachable *only* by making the SDK import fail,
which is what `sdk_absent` does, and which is meaningless on a leg that
is itself trying to drive the SDK. `SW1` therefore drives the **`cli`
backend plus `sdk_absent`**, following the shipped precedent exactly:
`test_invocation.py` imports that fixture across module boundaries with

```python
from test_invocation_sdk import (  # noqa: F401 -- fixture resolved by name
    sdk_absent,
)
```

(`test_invocation.py:46-48`), and this unit's module does the same rather
than defining a second copy — U-sdk `SU6` leg (ii) requires `sdk_absent`
to have **exactly one** definition site.

### SU — the suite and its scope

- **`SU1`** Suite baseline holds: after the build,
  `uv run --project plugins/self-learn/cli pytest -q` reports
  **1868 + N passed, 5 skipped**, rc 0, where N is this unit's own added
  node count and every one of the 1868 pre-existing nodes still passes.
  *Instrument criterion — satisfied by the command's unpiped rc and its
  summary line in the build report (`SU4`).* (`NOTE-6`: r2 pointed this
  at `HY4`, which is the no-real-`claude` criterion and has nothing to do
  with reporting numstats; `SU4` is the instrument row that collects the
  build report's measurements.)
- **`SU2`** `git diff --name-only 89f8ef7..HEAD` names **only** files in
  the may-touch table. *Instrument criterion.*
- **`SU3`** The seven shipped `_invoke_reader` monkeypatch sites survive
  **untouched**, in three legs, each of which fails differently:
  (i) `git diff --quiet 89f8ef7..HEAD -- …/tests/test_miner.py` exits 0;
  (ii) an AST/source scan of `test_miner.py` finds exactly **7**
  `monkeypatch.setattr(miner, "_invoke_reader", …)` sites in exactly the
  **6** containing functions `Sets-1` names — **five tests plus the
  module-level `shim_reader` helper** — and `shim_reader` itself has
  **78** call sites, so the frozen Python surface is far larger than the
  five tests (`MAJOR-1`); (iii) the five named node ids pass, **and** a
  sample of `shim_reader`-driven e2e tests passes. Leg (i) alone is the
  real guard; legs (ii) and (iii) are what make a *deletion* legible
  rather than merely diffable, and leg (ii)'s call-site count is what
  makes the true blast radius visible.
- **`SU4`** Every numstat bound in the may-touch table holds, measured by
  `git diff --numstat 89f8ef7..HEAD -- <path>` per row. *Instrument
  criterion — the per-row numbers go in the build report.*
- **`SU5`** `test_invocation.py`'s diff against base touches **exactly
  one** function, `test_cn2_call_site_containment_matches_the_call_site_table`.
  Asserted by parsing the diff's hunk ranges against the file's AST
  function ranges, not by eyeballing the numstat — a 1/1 numstat is
  equally consistent with a one-line change anywhere in a 1997-line file.
- **`SU6`** **[n/a]** This unit's test module defines **no** `autouse`
  fixture, for the same reason U-sdk `Sim-1a` forbade one: an autouse
  fixture here would reach every test that imports from this module.
- **`SU7`** **[n/a]** **The docs rows actually landed, at the expected
  ids** (`MAJOR-6`). A source scan of `14-forward-work-map.md` finds
  **five** new rows at `FW-95`…`FW-99`, and of `03-decisions.md`
  **two** new rows at `S-39`/`S-40`, each id appearing exactly once and
  each carrying the residual/decision this spec assigns it — with
  `FW-99` specifically naming the watched-first-nightly obligation and
  the operator preflight command. *Instrument criterion.* It exists
  because r2's residual owners and `MAJOR-5`'s entire enforcement
  mechanism are **documentation deliverables**, and a documentation
  deliverable with no criterion is the one kind of promise a green
  suite cannot keep. **Positive control required**: the same scan run
  against the pre-build files must find **zero** of those ids, so a
  scan that silently matches nothing cannot pass as success.

### MC — the strict-MCP hole (`Fix-1`)

- **`MC1`** `miner.build_reader_argv(p)[-1] == "--strict-mcp-config"`,
  and `"--mcp-config" not in` the argv. Both directions, mirroring
  `test_invocation.py::test_av2_worker_argv_shape`.
- **`MC2`** `invocation.containment_for("miner-reader", …).strict_mcp is True`.
- **`MC3`** The pair is consistent at the **real call site**: for the
  captured `SessionSpec` (`C-a`), `spec.containment.strict_mcp is True`
  **and** `"--strict-mcp-config" in spec.cli_argv_builder(spec.cli_settings_writer())`.
  This is `CN10`'s `iff` re-asserted on the reader alone, so that a
  future edit to `_assert_argv_matches_containment_iff` cannot silently
  take the reader's coverage with it.
- **`MC4`** The flag is added and **nothing else in the argv moves**:
  `build_reader_argv(p)[:-1]` equals the base commit's full output for
  the same input, asserted against a literal list written out in the
  test. This is the criterion that catches a "helpful" reordering or an
  `--allowedTools` that sneaks in alongside.
- **`MC5`** `miner.py`'s numstat bound holds: ≤9 insertions, ≤1 deletion,
  **every changed line inside `build_reader_argv`'s AST range**.
  **No hunk-count clause** (`MAJOR-2`): the real change measures **6/1
  across two hunks at `-U3` and one hunk at `-U5`** (`E15`), so a
  "one hunk" requirement would have failed a correct build against the
  default diff context. The AST-range clause carries the meaning the
  hunk count was reaching for, and carries it exactly. *Instrument
  criterion.*
- **`MC6`** `contract.py`'s numstat bound holds: exactly 1 insertion and
  1 deletion, one hunk, inside `containment_for`'s `miner-reader` branch.
  *Instrument criterion.*
- **`MC7`** `test_invocation.py`'s numstat bound holds: ≤4 insertions,
  ≤1 deletion, one hunk. *Instrument criterion.* Paired with `SU5`,
  which is the one that says *where*.

### CT — the reader's containment under `sdk` (hole (b))

- **`CT1`** **[n/a — containment is backend-independent data]** The
  captured spec's containment matches `C-b` field by field, all six
  fields, with `write_globs` compared against the **rendered**
  `f"{miner.spool_dir()}/**"` obtained from `miner.spool_dir()` at test
  time. **This IS a partial re-derivation and `C-f` now says so
  honestly** (`NOTE-3`): it re-spells the `/**` suffix, so it cannot
  catch a mutation that changes the suffix in `contract.py` and in the
  test together. Its real job is to catch a changed **base** (`M8`'s
  home-widening). The **independent oracle** for the write scope is
  `CT4`/`CT5`, which never spell a pattern at all — they present a path
  to the live charter and observe allow/deny. Cite those, not `CT1`, as
  proof the boundary holds.
- **`CT2`** **[sdk]** `options_kwargs(captured_spec)` matches `C-c`'s
  table, every row, **and its key set is asserted by SET EQUALITY**
  against the full **16** keys the miner surface produces (`NOTE-10`):
  the 14 unconditional keys plus `max_turns` and `max_budget_usd` (both
  supported on the pinned SDK; `E16`). Row-wise assertions alone are
  blind to a **new** option appearing — a future SDK field that silently
  widens the session would pass every row and fail set equality, which
  is the whole point. `disallowed_tools` is compared against
  `miner.READER_DISALLOWED_TOOLS.split(",")` computed at test time.
- **`CT3`** **[sdk]** `SELF_LEARN_SDK_MAX_TURNS_MINER` overrides
  `max_turns`, and `SELF_LEARN_SDK_MAX_TURNS_WORKER` does **not** — the
  selector scoping negative control, at the options layer this time.
- **`CT4`** **[sdk]** `C-d` leg 1: a `Write` to `spool_dir()/ARTIFACT`
  is ALLOWED, and — driven end to end through a real session — the file
  lands on disk.
- **`CT5`** **[sdk]** `C-d` leg 2: a `Write` to a path outside the spool
  is DENIED, the deny message names `Write` and the **resolved** target,
  and the file **does not exist** afterwards. Two targets are exercised:
  a sibling directory of the spool, and a path inside the ledger home.
- **`CT6`** **[sdk]** `C-d` leg 3: `Read`, `Grep` and `Glob` are each
  DENIED with the step-1 wording (`… is disallowed on this surface`),
  **not** the step-5 generic wording. The criterion asserts the exact
  message form, because both outcomes are "denied" and only one of them
  proves the `disallowed_tools` belt fired.
- **`CT7`** **[sdk]** `C-e`: the deny of `CT5` appears in
  `SdkOutcome.denials`, and its entry names `Write`. Guarded by a
  non-emptiness assertion first.
- **`CT8`** **[sdk]** The charter hatch is **closed** on this surface and cannot be
  opened: with `SELF_LEARN_ENFORCE_SCOPE=0` set, `CT5`'s deny still
  fires. `B-10` says why this must hold; without the criterion, a future
  change to `containment_for`'s hardcoded `default_mode` would silently
  hand the reader a bypass.

### RC — the output contract

- **`RC1`** **[both]** `R-a`: after a successful run the spool's listing
  is exactly `[ARTIFACT]`. Compared as a sorted list of names, not as a
  membership test.
- **`RC2`** **[both]** `R-b`: `_invoke_reader` returns that path and it
  `.is_file()`.
- **`RC3`** **[both]** `R-c` leg (i): `Outcome.stdout` is non-empty on
  this surface under both backends. Observed on the captured `Outcome`,
  since `_invoke_reader` discards it. The `cli` leg's stdout comes from
  the shim's `stdout_text` knob, the `sdk` leg's from
  `FAKE_CLAUDE_RESULT_TEXT` via `_extract_text` branch 1 (`T2-b`/`T2-c`
  step 6) — **without `MAJOR-3`'s knob the sdk leg's stdout is `""` and
  this criterion is unsatisfiable there**, which is how r2 shipped it.
- **`RC4`** **[both]** `R-c` leg (ii), the one with teeth: a run whose
  stdout is well-formed reader JSON but whose spool file is **absent**
  returns `None`; a run whose stdout is unparseable garbage but whose
  spool file is **present** returns the path. Both directions, both legs
  — and on the `sdk` leg both directions depend on `MAJOR-3`'s knob.
- **`RC5`** **[both]** `R-d`: the artifact's bytes round-trip verbatim,
  asserted with a body containing a non-ASCII character and a trailing
  newline. **Scope, stated honestly:** `_invoke_reader` returns a
  **path** and never opens the file, so on the product side this
  round-trip is guaranteed by construction. This criterion is therefore
  **fixture-pinning, not product coverage** — it proves the two legs'
  harnesses (bash shim redirection; the fake CLI's write) do not mangle
  bytes, which is what makes every *other* `RC` criterion's artifact
  comparison trustworthy. It is retained for that reason and must not be
  cited as evidence that the product preserves encoding.
- **`RC6`** **[both]** `R-e`: a stale artifact present at entry is
  unlinked, so a run that writes nothing returns `None` rather than last
  night's file.
- **`RC7`** **[both]** The prompt reaches the model on **stdin, never argv** — the
  reader's founding constraint (audit B1, E2BIG). On the `cli` leg the
  shim records both `"$@"` and stdin, and the criterion asserts the
  prompt is in the latter and absent from the former, using a prompt
  larger than the 128 KiB argv element cap. On the `sdk` leg the
  equivalent is that the prompt arrives as the session's user message
  and appears in no element of `spec.cli_argv_builder(...)`'s output.

### TO — timeout semantics and the kill paths

- **`TO1`** **[both]** `K-a`, leg 1: with `miner.INVOKE_TIMEOUT_SECS`
  monkeypatched, the value the transport received equals the patched
  value — observed on the captured `SessionSpec.timeout`.
- **`TO2`** **[both]** `K-a`, leg 2: the rendered timeout log line
  carries the patched value.
- **`TO3`** **[both]** `K-b`: the timeout log line is **byte-identical**
  between the two backends, and equals
  `LOG_TEMPLATES["miner-reader"].timed_out.format(label="", timeout=TIMEOUT_PATCH)`,
  where `TIMEOUT_PATCH` is `Sets-1`'s single pinned value. It is
  `1.0` — chosen because `{timeout}` renders it `"1.0"` while
  `{timeout:g}` renders it `"1"`, so `M29`'s format mutant is caught. A
  value that renders identically under both (the shipped `900` is one)
  makes this criterion vacuous and is forbidden.
- **`TO4`** **[cli]** `K-c` cli leg: on `subprocess.TimeoutExpired`,
  `os.killpg` is called once with `(proc.pid, signal.SIGKILL)`,
  `proc.wait()` is called after it, and the outcome is
  `failure="timeout"`. Recorders only, against a fake `Popen`.
- **`TO5`** **[cli]** `K-c` cli leg, swallowing: `ProcessLookupError`
  and `PermissionError` raised by the recorder-`killpg` are each
  swallowed and still yield `failure="timeout"`. **The two types are
  asserted separately, not as one combined leg**, so that a handler
  **narrowed** to either type alone reddens (`M34`). **What this
  criterion cannot see, stated so nobody credits it wrongly
  (`MAJOR-A1`):** it cannot detect a **widened** handler. Both types are
  `OSError` subclasses, so replacing the clause with a bare
  `except Exception` swallows both and leaves both legs green — an
  assertion that something *is* swallowed is structurally blind to
  over-swallowing. Detecting a widened handler would need a different
  criterion shape entirely (asserting an *unrelated* exception type
  propagates), which this unit does not carry.
- **`TO6`** **[sdk]** `K-c` sdk leg: `run_kill_ladder`'s three rungs, in
  order, against a client stub — bounded `interrupt()`; `disconnect()`
  shielded so the task survives the kill bound un-cancelled and lands in
  `_ABANDONED_DISCONNECTS`; then `kill_child`. Plus the pgid
  discrimination both ways via `os.kill` / `os.killpg` / `os.getpgid`
  recorders on `lifecycle`'s module object. **No real signal.**
- **`TO7`** **[sdk]** `K-d`: on the reader surface under `sdk`, the pid
  sidecar at `worker.cache_dir() / "miner-reader.sdk-child.pid"` exists
  **during** the session and is absent **after** `_invoke_reader`
  returns — on the success path, where the ladder runs from `finally`.
  **Observation hook, named (`NOTE-11`):** the "during" half is observed
  by **spying on `lifecycle.clear_sidecar`** — wrap it so the spy reads
  the sidecar's contents at call time, before the real function unlinks
  it. Asserting "during" by racing the live session is not reproducible;
  the spy makes the sidecar's existence-at-teardown a deterministic
  observation. The spy must **call through**, so `M33`'s dropped-unlink
  mutant still reddens the "after" half.

### SW — the sweep and the dispatch

- **`SW1`** **[cli + `sdk_absent`; deliberately UNPARAMETRIZED]** `S-a`:
  for each of the four `EARLY_RETURN` kinds, `_invoke_reader` returns
  `None` and a pre-placed stray **still exists**. Four kinds, four
  assertions, each naming its kind in the failure message. The
  `unavailable` kind is reachable only via `sdk_absent`, which this
  criterion imports from `test_invocation_sdk` rather than redefining
  (§4 header, `MAJOR-4`); `timeout` / `not-found` / `os-error` are
  driven by fake `Popen`s exactly as the shipped
  `test_invocation.py::test_wr2_…` drives them.
- **`SW2`** **[both]** `S-b`: on `rc != 0`, the sweep runs (the stray is
  gone) and `out_path` is returned when present.
- **`SW3`** **[both]** `S-c`: with two strays and one artifact in the
  spool, both strays are deleted, the artifact survives, and exactly two
  log lines are emitted, each byte-equal to
  `f"run: stray spool artifact {name} deleted"`.
- **`SW4`** **[both]** `S-d`: a **directory** in the spool survives the
  sweep and raises nothing.
- **`SW5`** **[n/a]** The sweep never runs before the dispatch: asserted
  as the conjunction of `SW1` and `SW3` on the same spool state, so a
  refactor that hoists the sweep above the early return is caught by
  `SW1` rather than merely by inspection (`U-seam` `M18`'s target).
- **`SW6`** **[n/a]** `S-e`: `SW1` and `SW2` call the real `miner._invoke_reader`.
  Asserted structurally — an AST scan of this unit's test module finds no
  local re-implementation of the dispatch set, and `EARLY_RETURN` is
  imported/derived from one place in the test module rather than spelled
  twice.

### FL — flip readiness

- **`FL1`** `FL-a` positive: with `BACKEND_VAR="sdk"`,
  `invocation.backend_for("miner-reader")` is an `SdkBackend`.
- **`FL2`** `FL-a` negative, **and this is the one that keeps the unit
  honest**: with the environment clean and no config key,
  `invocation.backend_for("miner-reader")` is the shared `CliBackend` —
  the same object identity `registry._CLI_BACKEND` holds. The default is
  `cli` after this unit.
- **`FL3`** `FL-b`: `SELF_LEARN_BACKEND_WORKER="sdk"` leaves
  `miner-reader` on `cli`; `BACKEND_VAR="sdk"` leaves `worker` and
  `analyst` on `cli`. Both directions.
- **`FL4`** `FL-d`: no assignment of `BACKEND_VAR` exists anywhere in
  `plugins/self-learn/cli/src/`, in the shipped `config.yaml` template,
  or in `systemd/`. Grep-based, with a **positive control**: the same
  grep run against a string that is known to be present must find it, so
  a grep that silently matches nothing cannot pass as a clean result.
- **`FL5`** `FL-e`: `git diff --quiet 89f8ef7..HEAD -- …/invocation/registry.py`
  exits 0. *Instrument criterion — rc captured unpiped.*

### HY — hygiene

- **`HY1`** `shims.py`'s new builder satisfies `B-9`: it is in `__all__`,
  it has an in-suite call site, it is not fixture-marked, it creates no
  directory, and it does its own `chmod`. The shipped
  `test_sh4_shims_public_surface_is_honest` enforces most of this
  already; this criterion is the local statement that the builder was
  written to pass it rather than to be exempted from it.
- **`HY2`** `SH1`'s two pinned shim shas are **unchanged** and **not
  re-pinned**. *Instrument criterion — `git diff` shows no change to
  `test_u_fake.py`.*
- **`HY3`** `B-6`: every SDK-driving test in this unit sets
  `SELF_LEARN_SDK_CLI_PATH` before the session runs, and no test in this
  unit calls `monkeypatch.undo()` on a shared fixture instance. Asserted
  by an AST scan of this unit's own module, so the tripwire is a backstop
  and not the only guard.
- **`HY4`** No test in this unit invokes a real `claude`. Asserted the
  way `test_attrib.py::test_hy1_...` does for the shipped suite: the
  `cli` leg's PATH is shim-first and sanitized, and the `sdk` leg's
  `cli_path` is always `FAKE_CLI`.

---

## 5. Mutation plan

**35 mutations** (r3 adds `M32`–`M35`, `MAJOR-7`). Every mutation is applied to the **built** code, the
suite is run, and the named criterion must **redden**. A mutation that
leaves the suite green is a hole in §4 and must be closed before the
gate, not explained away. Rows marked *gate-measured* were run by this
author against master at `89f8ef7`; the rest are the builder's to run.

| # | Mutation | Must redden |
|---|---|---|
| `M1` | Drop `--strict-mcp-config` from `build_reader_argv`, leave `strict_mcp=True` | `MC1`, `MC3`, `MC4`, and `test_invocation.py::test_cn10_argv_is_the_third_witness_iff_both_directions` (shipped). **`MC4` IS credited** (`NOTE-1`, correcting r2): `MC4` compares `build_reader_argv(p)[:-1]` against a literal, and with the flag dropped the slice discards `str(settings_path)` instead — so it reddens too. r2's "NOT credited" annotation was safe (under-crediting never lets a mutant escape) but its *derived design instruction* — write `MC4` so `M4` lands — rested on a false premise and is withdrawn. *gate-measured (`E2`, mirror direction)* |
| `M2` | Leave `strict_mcp=False`, add the argv flag | `MC2`, `MC3`, shipped `CN10`, **and shipped `CN2`** (`NOTE-2`: `CN2` asserts `strict_mcp is False`, which this mutant leaves true — so it reddens against this unit's *edited* `CN2`, which asserts `is True`). **`MC1` is NOT credited.** *gate-measured (`E2`): against the UNEDITED suite this reddens exactly one test; against the edited suite it reddens two* |
| `M3` | Land `Fix-1` fully but "restore" the enumerated armor site to `is False` | `test_invocation.py::test_cn2_call_site_containment_matches_the_call_site_table` (shipped). *gate-measured (`E3`): reddens exactly this one test suite-wide* |
| `M4` | Add `--strict-mcp-config` at index 2 instead of last | `MC1` **and** `MC4` (`NOTE-1`): `MC1` asserts `[-1] == "--strict-mcp-config"`, which a mid-list insertion breaks (the last element becomes `str(settings_path)`); `MC4`'s literal comparison breaks too. r2 claimed `MC1` was blind here — it is not |
| `M5` | Also add `--allowedTools Read,Grep,Glob` to the reader's argv | `MC4`, and `CT2`'s `disallowed`/`allowed` rows only if the containment moved too — the point of the row is that `MC4`'s literal comparison is the guard, not the containment |
| `M6` | `containment_for("miner-reader")` returns `allowed_tools=allowed_tools` (caller-supplied) instead of the forced `None` | `CT1`. **`MC2` is NOT credited** |
| `M7` | `write_globs=(f"{spool_dir}/*",)` — single star instead of `**` | `CT1`, and `CT4` on the sdk leg (a write to `spool/mine-output.json` still matches `*`, so pick the criterion carefully — `CT1`'s literal comparison is the reliable one). **Negative control: `CT5` stays GREEN**, because narrowing the scope cannot allow an outside write |
| `M8` | `write_globs=(f"{home}/**",)` — the scope widened to the ledger home | `CT1` **and** `CT5`'s second target (a path inside the ledger home now ALLOWS). This is the row that proves `CT5` needs two targets, not one |
| `M9` | `options_kwargs` sets `strict_mcp_config=False` | `CT2`. **Negative control: every `RC`/`SW` criterion stays GREEN** — the fake CLI has no MCP servers, so the contract is unaffected. This row is why `CT2` exists as a separate criterion from the behavior suite |
| `M10` | `options_kwargs` sets `setting_sources=["user","project","local"]` | `CT2`. **Negative control: the behavior suite stays GREEN** — same reasoning as `M9`, and the same reason the row exists |
| `M11` | `options_kwargs` sets `permission_mode="bypassPermissions"` | `CT2`, **and** `CT5` (the charter is bypassed, the outside write lands). The two-criterion redden is the point: this is the mutation that actually escapes containment |
| `M12` | `options_kwargs` passes `settings=str(settings_path)` instead of `None` | `CT2` only. Records that the settings file is written but not handed over (`U-sdk` `A-2`) |
| `M13` | `_DEFAULT_MAX_TURNS["MINER"] = 120` | `CT2`'s `max_turns` row. **`CT3` is NOT credited** — it asserts the override, which still works |
| `M14` | `_max_turns_for` reads `SELF_LEARN_SDK_MAX_TURNS_WORKER` for every surface | `CT3`'s negative leg. **`CT2` stays GREEN** when the worker var is unset — which is exactly why `CT3` sets it |
| `M15` | Charter step 1 removed (`disallowed_tools` not consulted) | `CT6` — `Read` now falls to step 5 and is still denied, but with the **generic** wording. This row is the entire justification for `CT6` asserting the message form |
| `M16` | Charter step 3 allows any path whose parent exists | `CT5`. **`CT4` stays GREEN** |
| `M17` | Charter deny in `options_kwargs`'s wrapper is returned without `events.add_denial` | `CT7`. **`CT5` stays GREEN** — the deny still happens, it is just unrecorded |
| `M18` | `hatch_open` drops its `default_mode is None` conjunct | `CT8` |
| `M19` | `_invoke_reader` parses `outcome.stdout` as JSON and writes it to `out_path` when the file is missing | `RC4`'s first direction. **`RC1`, `RC2` stay GREEN** on the happy path — this row is why `RC4` exists |
| `M20` | `_invoke_reader` returns `out_path` unconditionally (drop the `.is_file()` check) | `RC4`'s first direction and `RC6` |
| `M21` | Drop the pre-run `out_path.unlink(missing_ok=True)` | `RC6`. **Every other `RC` criterion stays GREEN** — the artifact is overwritten on the happy path, so only a run that writes nothing exposes it |
| `M22` | `_invoke_reader` returns `None` on `failure == "exit"` (adds it to `EARLY_RETURN`) | `SW2` on both legs, and shipped `test_invocation.py::test_wr3_miner_rc_nonzero_does_not_short_circuit` |
| `M23` | Move the stray sweep **above** the failure dispatch | `SW1` (all four kinds), and shipped `test_invocation.py::test_wr2_miner_early_returns_precede_the_stray_sweep`. **`SW3` stays GREEN** — on the success path the sweep's position is unobservable |
| `M24` | Remove `"unavailable"` from `EARLY_RETURN` | `SW1`'s unavailable leg only. The row exists to prove `SW1` exercises all four kinds rather than the three that share a code path |
| `M25` | The sweep's guard becomes `path.name != OUTPUT_BASENAME` (drop `and path.is_file()`) | `SW4` |
| `M26` | The sweep `break`s after the first deletion | `SW3` |
| `M27` | The sweep deletes the artifact too | `SW3`, `RC1`, `RC2` |
| `M28` | `SessionSpec(timeout=15*60)` — the module constant inlined as a literal | `TO1`, `TO2`, `TO3`. This is `B-3a`'s import-time-binding hazard in its miner form |
| `M29` | `_MINER_TEMPLATES.timed_out` uses `{timeout:g}` | `TO3` **only if** the patched value renders differently under the two forms. The row is the reason `TO3` forbids a value like `900` |
| `M30` | `CliBackend` drops the `killpg` on the miner's timeout path (keeps `proc.wait()`) | `TO4`. **`SW1`'s timeout leg stays GREEN** — the outcome is still `timeout`, the process is just orphaned. This row is why the kill path needs recorder criteria of its own |
| `M31` | `lifecycle.kill_child` drops the `getpgid` guard and always `killpg`s | `TO6`'s same-pgid leg. **Never run without the recorders in place** — the unguarded mutant signals the runner's own process group, which is precisely what `K-c` exists to prevent |
| `M32` | `SELECTOR_FOR_SURFACE` collapsed so every surface maps to `"WORKER"` | **`FL3`** (the backend selector negative control: `SELF_LEARN_BACKEND_WORKER=sdk` would now move `miner-reader`) **and `CT3`** (the options-layer negative control: `SELF_LEARN_SDK_MAX_TURNS_WORKER` would now override the miner's `max_turns`). `MAJOR-7` — the two scoping negative controls exist precisely for this mutant, and r2 never wrote the row that proves they fire |
| `M33` | `lifecycle.clear_sidecar` dropped from `_drive`'s `finally` | **`TO7`**'s "absent after" half. Requires `TO7`'s spy to **call through** (`NOTE-11`); a spy that replaces the function would mask this mutant entirely |
| `M34` | **NARROW** `CliBackend`'s `except (ProcessLookupError, PermissionError)` clause (`invocation/cli.py`, the `killpg` site) to `except ProcessLookupError` alone | **`TO5`**'s **`PermissionError`** leg — the `PermissionError` now propagates out of `_run` instead of being swallowed, so the criterion's second assertion fails. The symmetric mutant (`except PermissionError` alone) reddens the `ProcessLookupError` leg. **This row was inverted in r3 and is corrected here (`MAJOR-A1`):** r3 mutated toward a *bare* `except Exception`, which **widens** the handler — and since both types are `OSError` subclasses, a widened handler swallows both, leaving `TO5` **green**. No assertion that an exception **is swallowed** can detect a widened handler; it can only detect a **narrowed** one. `TO5` must therefore be mutated by narrowing, and this is the row that does it |
| `M35` | `_stdout_for` returns `""` for `miner-reader` (worker-shaped stdout on the reader) | **`RC3`'s `sdk` leg ONLY** (`NOTE-b`, correcting r3's "both legs"): `_stdout_for` lives in `invocation_sdk/backend.py` and is on the **SDK path alone**. The `cli` leg's stdout comes from `invocation/cli.py`'s `stdout = output if transport.result_stdout == "merged"`, which this mutation does not touch. **The symmetric `cli`-side mutant** is `TRANSPORT["miner-reader"].result_stdout = "empty"` in `invocation/contract.py`, which reddens `RC3`'s `cli` leg. **Both are only expressible because of `MAJOR-3`** — before `T2-c` step 6 the sdk leg's stdout was `""` already, so the mutant was indistinguishable from correct behavior there |

**The mutation this document is most afraid of** is not in the table,
because it cannot be expressed as a code edit: it is a builder writing
the `sdk` leg of a parametrized criterion so that it never actually runs
an SDK session — a fixture that silently falls back to the CLI backend
because `BACKEND_VAR` was set after the call, or a leg whose assertions
are all satisfied by `None`. Three things answer it: `T2-e` (the sdk leg
resolves through the registry, so a fallback is a wrong-backend bug, not
a silent pass), `RC3` (stdout is non-empty on both legs — a leg that ran
nothing has empty stdout), and `CT7`'s non-emptiness guard. The builder
must additionally record, in the build report, the **per-leg** node
counts from `pytest --collect-only -q`, so that a parametrization that
silently collapsed to one leg is visible as a number rather than as a
green tick.

---

## 6. Builder decisions, made here rather than left open

- **`D-1`** `Fix-1` is **adopted unconditionally** — `Q-1` is ruled and
  the approved plan charters this unit as *"miner reader contract +
  strict-mcp hole closed."* Closing the hole is the mandate. The
  alternative r1 weighed — recording the reader's missing flag as a
  permanent, faithful inconsistency the way `U-seam` `C-d` records the
  analyst's — is **foreclosed**, and correctly so: the analyst's weaker
  boundary is a *shape* (no settings file, no write scope), whereas the
  reader's is a *gap* (settings file, write scope, and one missing flag
  its two siblings carry). The residual risk is carried by `Mit-a`
  (blocking live verification), `Mit-b` (11 days of production exposure
  for the flag; only the combination is new) and `Mit-c` (the first
  post-merge nightly is watched), **not** by narrowing the change.
- **`D-2`** The fix lands as a **matched pair** (`F-c`), because `B-1`'s
  `iff` makes any other landing a red suite. The builder does not get to
  choose an order.
- **`D-3`** The armor cost is **one line in one function** (`F-d`), and
  it was measured rather than budgeted (`E3`). A builder who finds a
  second contradicting assertion has changed something outside `Fix-1`.
- **`D-4`** `test_invocation_sdk.py::_miner_argv()` is **not** updated
  (§3.9). Recorded as `R-1`.
- **`D-5`** The `sdk` leg's artifact comes from a **new scenario**, not
  from widening `ok_write` (`T2-c`). Editing `ok_write` would change what
  every shipped `CH`-group test drives.
- **`D-6`** The kill paths are **recorder-tested only** (`K-c`), and the
  parametrized behavior suite asserts the *observable* timeout contract
  (returns `None`, stray survives, log bytes) rather than signals. The
  two never mix in one test.
- **`D-7`** `Read`/`Grep`/`Glob` denial is asserted **by message form**
  (`CT6`), not merely by "denied", because both the belt (step 1) and the
  braces (step 5) produce a deny and only one proves the belt fired.
- **`D-8`** `CT5` exercises **two** outside targets, not one, because
  `M8`'s home-widening mutation escapes a single sibling-directory
  target.
- **`D-9`** The patched timeout value is defined **once**, as `Sets-1`'s
  `TIMEOUT_PATCH = 1.0` (`NOTE-8`), and `K-a`/`K-b`/`TO1`/`TO2`/`TO3` all
  reference it by name rather than respelling it. `TO3` forbids a timeout value that renders identically under
  `{timeout}` and `{timeout:g}` — the shipped `900` is exactly such a
  value, and `U-seam` `X-5` already recorded that trap.
- **`D-10`** `FL4`'s grep carries a **positive control**. A grep that
  finds nothing and a grep that cannot see its target print the same
  thing, and this criterion's whole job is to distinguish them.
- **`D-11`** `SU3` has three legs. The `git diff --quiet` leg is the real
  guard; the count leg and the pass leg exist so that a reviewer reading
  the build report can see *what* survived, not just that a diff was
  empty. **Corrected at r3 (`MAJOR-1`):** the count leg asserts **6
  containing functions**, not 5, because the seventh site lives in the
  module-level `shim_reader` helper rather than in a test — and the leg
  additionally reports `shim_reader`'s **78** call sites, because the
  number a reviewer actually needs is the size of the frozen surface, and
  "seven tests" understated it by an order of magnitude.
- **`D-12`** This unit adds a **new** test module rather than extending
  `test_invocation_sdk.py` or `test_miner.py` — both for footprint and
  because U-fake `§3.9`'s lesson (criterion tests homed in the modules
  they constrain falsify the very criteria they exist to satisfy) applies
  directly to `SU3`.

---

## 7. Out of scope, look-alikes, and residuals

### 7.1 Out-of-scope look-alikes

- **`miner._spawn_run` / `maybe_kick`** — the 24-hour autokick watchdog.
  It spawns a **detached `self-learn` process**, not a model session, and
  it goes nowhere near the invocation seam. `conftest.py` already pins
  `SELF_LEARN_MINER_AUTOKICK=0` suite-wide. Not touched, not tested here.
- **`analyst.build_argv`'s identical missing flag** — `R-2`.
- **The worker's `SELF_LEARN_INVOKE_TIMEOUT_SECS`** — the reader has no
  equivalent. `R-3`.
- **`registry.py`'s default table** — `Flip-1` proves resolution works;
  it does not change a row. U-sdka owns the analyst row.

### 7.2 Residuals this unit accepts, with owners

*(`NOTE-7`: §7.2 lists residuals — things this unit **leaves behind**,
each with an owner and an `FW` row. §7.3 lists **non-goals** — things
this unit deliberately does not build, which generate no `FW` row and
need no owner. r2 gave both sections near-identical framing; they are
different registers and are not interchangeable.)*

- **`R-1` — `test_invocation_sdk.py::_miner_argv()` becomes a stale
  mirror.** After `Fix-1` it emits a reader argv without
  `--strict-mcp-config` while the product emits one with it. Nothing
  asserts on the difference (`B-4`: `backend.py` cannot read the flag),
  so it is cosmetic — but a future reader of that file will believe the
  wrong thing. Deliberately not fixed here (`D-4`): touching U-sdk's
  frozen-by-convention file for a cosmetic mirror spends an allowance
  this unit does not need. Owner: a new `FW` row, landing with this
  build; graduates at `U-cleanup`.
- **`R-2` — the analyst's argv omits `--strict-mcp-config` too.** The
  same gap, on a surface this unit may not touch. **Ruled at `Q-2`: no
  CLI-side analyst fix, ever, by the user's `F3` ruling (2026-08-09) —**
  *"wait for the SDK flip — no CLI-side carve-out; the analyst flips
  FIRST and its hardening rides that flip."* `U-sdka` performs that flip
  this wave; the analyst's CLI path becomes **rollback-only**
  thereafter, and the no-carve-out stance covers the rollback path too.
  **Owner: nobody — deliberately accepted, not deferred.** Revisit only
  if the analyst ever **un-flips durably**; a transient rollback is not
  a trigger. Recorded so that a future reader who notices the asymmetry
  finds the ruling instead of re-deriving the question.
- **`R-3` — the reader's timeout has no env override, and under `sdk`
  it is no longer the only bound.** `worker.invoke_timeout_secs()` reads
  `SELF_LEARN_INVOKE_TIMEOUT_SECS`; `miner.INVOKE_TIMEOUT_SECS` is a
  bare module constant. Under `sdk`, `max_turns=60` can end a reader
  session before 900 s elapse, and the two bounds have never been
  reconciled. **Ruled at `Q-4`: owned by the MINER FLIP decision**, not
  by this unit — this unit does not flip, and "does 60 turns bind before
  900 s?" is a **burn-in observable**: the plan's miner gate watches
  candidate volume against ±1σ, which is the signal a turns-starved
  reader would move. Cross-referenced to the runbook's miner-flip
  section **pending that section's existence** (`Mit-c1`, `E14`).
  Owner: **the miner-flip decision**.
- **`R-4` — `Containment.strict_mcp` is read by no production code, and
  that is the design, not a wart.** The SDK sets `strict_mcp_config=True`
  unconditionally (`O-3`); the CLI backend never consults the field
  either — `build_reader_argv` and `worker.build_argv` each decide the
  flag independently. The field's only consumer is `CN2`/`CN10`'s `iff`,
  and **that is precisely its job**: it is the *second witness*, the
  independent record that makes a one-sided argv edit red in both
  directions (`B-1`, measured at `E2`/`E3`). **Ruled at `Q-3`: keep it,
  and do NOT derive it** — deriving the flag from the containment would
  collapse two witnesses into one and re-open the tautology class
  `U-seam`'s negative controls exist to prevent. The `SdkBackend`'s
  unconditional `strict_mcp_config=True` is likewise **deliberate
  narrowing-only discipline** in the `O-2`/`C-4` lineage (the SDK path
  may only ever be *more* contained than the containment record, never
  less), not an oversight to be reconciled away. Owner: **this spec** —
  the invariant is stated here so a future "dead field" cleanup finds
  the reason before deleting the witness.

### 7.3 Not built, with reasons — NON-GOALS, not residuals

*(These generate no `FW` row and have no owner. Contrast §7.2.)*

- **No flip.** That is a successor unit's, after the analyst's burn-in.
  This unit ships the readiness and the refusal.
- **No reader-side retry, backoff, or partial-output streaming.**
- **No change to the reader's prompt, rubric, or spool layout.**
- **No `mcp_servers` allow-list.** `{}` plus `strict_mcp_config` is the
  boundary; a curated list would be a new capability.

### 7.4 Verify-at-build ledger

**Each item below is an open question this spec could not settle. The
builder MUST resolve each against a live artifact at build time, and the
build report MUST carry the source and the answer.** An unresolved item
is a blocked build, not a caveat.

`VB-0` — an answer inferred from a binary's `--help` text is **evidence,
not verification**, where the question is about runtime behavior.

| # | Question | What is already measured | Where it lands |
|---|---|---|---|
| `VB-1` | **NOT a build item — OPERATOR PREFLIGHT (`Mit-a`, `MAJOR-5`).** Does the installed `claude` accept `--strict-mcp-config` **with no `--mcp-config` present**, no usage/flag error, in the reader's exact flag combination (no `--allowedTools`)? | `E12`: the flag exists on CLI **2.1.235** and is documented as *"Only use MCP servers from --mcp-config, ignoring all other MCP configurations."* `worker.py` records a live rc-0 verification at **2.1.226** — nine patch versions stale, and for a **different** flag combination. `E13`: the flag has 11 days of production exposure on the worker surface, but always *with* `--allowedTools`. | **The builder does NOT run this and MUST NOT** — discharging it requires a real credentialed session, which `HY4`/`K-e` and the suite tripwire forbid. It is routed to the **operator**, once, attended, before the **miner flip**; the exact command is in §8.1 `Mit-a`. The build proceeds without it; `Mit-c` is the enforcement |
| `VB-2` | Does `--strict-mcp-config` change the reader's **startup cost** measurably (the stated motive for the flag)? | Nothing. `worker.build_argv`'s docstring asserts the motive but cites no measurement. | The build report's rationale for `Q-1`; a null result does not block, but must be reported rather than assumed |
| `VB-3` | Under `sdk`, what does the reader's session actually do when `max_turns=60` is reached before the model writes the artifact — `ResultMessage.is_error`, or a clean result with no file? | Nothing. `_DEFAULT_MAX_TURNS["MINER"] = 60` is shipped and untested on this surface. | Decides whether `SW2`/`RC2` need a `max_turns`-exhaustion leg, and feeds `R-3` |
| `VB-4` | Is `FAKE_CLAUDE_WRITE_TARGET`'s path handed to the charter **before** or **after** the SDK resolves symlinks, on the sdk leg? | The charter resolves the *requested* path (`Path(raw_target).resolve()`) and leaves its own patterns' leaves verbatim (`P-b`). Whether the fake's emitted path survives that unchanged for a `tmp_path` under `/tmp` (which is a symlink on some hosts, not this one) is unverified. | `CT4`/`CT5`; if `tmp_path` resolves differently, both criteria need `.resolve()` on the expected side |

### 7.5 Handed to `03-decisions.md`

- **`S-39`** — The miner-reader's CLI argv carries `--strict-mcp-config`,
  and `Containment.strict_mcp` is `True` for that surface. The two are
  one decision; `CN10`'s `iff` is what enforces it.
- **`S-40`** — A surface's SDK containment is pinned from the
  `SessionSpec` its real call site builds, never from
  `containment_for`'s defaults. `U-seam` `CN2` established this for the
  CLI path; this unit extends it to `options_kwargs`.

---

## 8. Values questions — RULED

**All four are settled.** They were routed at r1 and ruled by the
coordinator against the approved plan; r2 folded the rulings and r3 folds
the gate's remedies. Nothing in this section is open, and a builder must
not re-litigate any of it. `VB-1` is **not** a build item: `MAJOR-5`
downgraded it from r2's build blocker to a named **operator preflight**
— see §8.1 `Mit-a` and §7.4.

| # | Question | Ruling | Where it lands |
|---|---|---|---|
| `Q-1` | Should the nightly reader's command line change at all? | **YES — and it is not latitude.** The approved plan charters this unit by name as *"U-sdkr (miner reader contract + strict-mcp hole closed)"*. Closing the hole is the mandate, not a judgement call this spec gets to make. The r1 risk analysis stands and is answered by three required mitigations, `Mit-a`/`Mit-b`/`Mit-c` below — not by narrowing the change. | `Fix-1` is **adopted unconditionally**; `D-1` restated |
| `Q-2` | The analyst has the identical gap. Fix it where? | **NO CLI-side analyst fix — the user's own `F3` ruling (2026-08-09) governs**, verbatim: *"wait for the SDK flip — no CLI-side carve-out; the analyst flips FIRST and its hardening rides that flip."* `U-sdka` flips the analyst this wave, after which the analyst's CLI path is **rollback-only**; the no-carve-out stance covers the rollback path too. | `R-2`, owner **nobody** — deliberately accepted |
| `Q-3` | Should `Containment.strict_mcp` survive as a field? | **KEEP — it is the second witness, and that is the twin-witness design's whole point.** The containment DATA and the emitted argv must agree, and `CN2`/`CN10`'s `iff` is the agreement. Deriving the flag from the containment would collapse two witnesses into one and re-open exactly the tautology class `U-seam`'s negative controls exist to prevent. | `R-4`, restated as a design invariant rather than a wart |
| `Q-4` | Should the reader's 15-minute budget become env-overridable before the flip? | **Defer — owned by the MINER FLIP decision, not by this unit.** This unit does not flip, and whether `max_turns=60` binds before 900 s is precisely a **burn-in observable**: the plan's miner gate watches candidate volume against ±1σ, which is what would surface a turns-starved reader. | `R-3`, owner **the miner-flip decision** |

### 8.1 `Q-1`'s three required mitigations (NORMATIVE)

The ruling adopts `Fix-1` *and* the r1 risk analysis. These three are
part of the unit's definition of done, not commentary.

- **`Mit-a` — live verification, as an OPERATOR PREFLIGHT item. NOT a
  build blocker.** (`MAJOR-5` ruling; supersedes r2, which made it
  blocking.)

  **Why r2 was wrong.** As r2 wrote it, `VB-1`'s only possible discharge
  was a **real, credentialed `claude -p` session**, and the only party
  positioned to run it during an autonomous build was a **builder
  agent**. That is forbidden outright by this campaign's tripwire
  doctrine — `conftest.py::_no_real_sdk_spawn_tripwire` exists precisely
  to make a real session an immediate, deterministic failure, and
  `HY4`/`K-e` forbid it in this unit's own criteria. r2 therefore wrote
  a gate that **could only be passed by violating a different, stronger
  rule**. The gate was right to call this the item most in need of
  specification, and right that **it must never be an agent's to run**.

  **The ruling.** `VB-1` is stated as a **named operator preflight**,
  routed to the operator to run **once, attended, before the miner
  flip** — not before this build. The build does **not** block on it.

  **The exact command** — **two lines, both required** (also carried into
  the runbook's miner section via `Mit-c1`'s carrier row):

  ```sh
  printf '{"permissions":{"allow":[],"defaultMode":"default"}}' \
    > /tmp/u-sdkr-preflight.settings.json

  timeout 10 claude -p \
    --disallowedTools 'Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch,Read,Grep,Glob' \
    --settings /tmp/u-sdkr-preflight.settings.json \
    --strict-mcp-config < /dev/null
  ```

  **Corrected at r4 (`MAJOR-A2`) — r3's version could not run.** It had
  two independent defects, and both produced a **usage error**, which is
  *exactly* the symptom this preflight exists to detect — so a failure
  would have been indistinguishable from the CLI rejecting the flag
  combination, and the operator would have reported a false positive:

  1. `--model "$(: the reader's model)"` — `:` is the shell's **no-op
     builtin**, so the substitution expanded to the **empty string** and
     the CLI received `--model ''`.
  2. The `--settings` file was **named but never created**, so the CLI
     was pointed at a nonexistent path.

  **The fixes.** `--model` is **dropped entirely**: it is not the flag
  under test, its value is irrelevant to MCP-config resolution, and
  omitting it lets the CLI use its own default. (If fidelity to the
  reader's argv is preferred, pin the literal `claude-sonnet-5` —
  verified as `miner.DEFAULT_MINER_MODEL` at `E18`; do **not** try to
  interpolate it from a shell expression.) `--settings` is **kept**,
  because a settings file plus `--disallowedTools` plus no
  `--allowedTools` is what makes this the *reader's* combination rather
  than a generic flag check — and it is now **created first**, with the
  minimal contents `write_reader_settings` itself emits.

  **Expected observation: no usage error and no flag error in the
  window.** Note for the operator: this may start **one brief real
  session**, and aborting after first output is fine — the observation is
  *"the CLI accepted the flag combination"*, not *"the session
  completed"*. A `timeout`-killed run that produced no usage error is a
  **pass**.

  **Rationale, recorded because it generalises** (three facts, in
  order): (1) **agents spawn nothing real, ever** — there is no
  exception, and a spec that needs one has mis-specified something;
  (2) **an operator round-trip is not allowed to block an autonomous
  build** — a blocking item that requires a human turns an autonomous
  unit into a stalled one; (3) **the risk window is one watched
  nightly** — see `Mit-c`, which is the binding enforcement.

- **`Mit-b` — the empirical safety base, stated as measured rather than
  as asserted.** The flag is not novel on this host: `worker.build_argv`
  has emitted `--strict-mcp-config` on **every** worker invocation —
  nightly *and* kick-driven — since it landed on **2026-08-08** in
  `9715314` (U-repair, FW-83), i.e. **11 days** of continuous production
  use at r2's writing (`E13`). The flag itself therefore has substantial
  production exposure on this CLI lineage; **only the combination is
  new** — the reader passes no `--allowedTools`, where the worker does —
  and that combination is exactly what `Mit-a` verifies.

  **Discharge (`MAJOR-6`), concretely:** the build report **restates
  `E13`'s figures verbatim** — introducing commit `9715314`, date
  **2026-08-08**, elapsed **11 days** at r2/r3's writing — rather than
  asserting "the flag is well-exercised." A mitigation whose discharge is
  a claim rather than a number is not a mitigation.

  **Correction of record (`E13`):** the ruling attributed this exposure
  to *"the 2026-07-15 containment audit."* That date is real but belongs
  to a **different** change — it is the audit cited by
  `READER_DISALLOWED_TOOLS`'s comment and by `worker.build_argv`'s
  prompt-on-stdin rationale (the E2BIG/tool-restriction work), not the
  strict-MCP flag. `git log -S` places the flag's introduction at
  `9715314`, **2026-08-08**, three weeks later. The safety base is
  therefore ~11 days rather than ~5 weeks. It is still a safety base;
  it is simply a smaller one than the ruling assumed, and a spec that
  quietly inherited the larger number would be overstating its own
  evidence.

- **`Mit-c` — the first post-merge nightly miner run is a WATCHED run.
  This is the BINDING enforcement backstop** (`MAJOR-5`), now that
  `Mit-a` is a preflight rather than a gate. The operator reads
  `miner.log` the following morning and confirms: the run reached the
  reader, the reader produced `mine-output.json`, and no new diagnostic
  line appeared.

  **Why this is sufficient enforcement.** The failure mode `Mit-a` was
  guarding against — the CLI rejecting the reader's flag combination —
  is **loud, immediate and non-destructive**: the reader exits nonzero
  on its very first invocation, `_invoke_reader` returns `None` (the
  `exit` leg falls through, finds no artifact), `run()` journals
  `status: failed` with `reason: reader produced no output`, and the
  cursors are **not advanced** (`test_failed_reader_keeps_cursors` pins
  exactly this). The cost of the whole risk is therefore **one missed
  mine, alarm-detected, with zero data loss** — the next run re-reads the
  same sessions. That is a proportionate window to trade against
  stalling an autonomous build on a human round-trip.

- **`Mit-c1` — where the watch obligation lives, and an honest gap.**
  The ruling names *"the runbook's watch list — U-docs' runbook is the
  home."* **Neither exists yet (`E14`).** The repo's only runbook is
  `docs/specs/self-learn/15-orchestration-runbook.md`, and it is an
  **orchestration** runbook — round lifecycle, worktree discipline,
  reviewer isolation, merging, sandbox invariants — with **no
  operations section, no watch list, and no miner-flip section**. The
  string `U-docs` appears **nowhere** in `docs/specs/self-learn/`. This
  spec therefore does **not** manufacture a citation to a section that
  does not exist. Instead:

  1. `Mit-c` is recorded **here**, in this spec, as the authoritative
     statement of the obligation;
  2. an `FW` row lands with this build carrying `Mit-c` forward, so the
     obligation survives this document;
  3. the row names **U-docs** as the owner of the eventual home (per the
     ruling), and `15-orchestration-runbook.md` as the nearest existing
     document should U-docs not materialise before the flip;
  4. `R-3`'s cross-reference to a *"runbook miner-flip section"* is
     likewise recorded as **pending that section's existence**, not as a
     live pointer.

  A builder who finds a watch list already present when they build
  should put `Mit-c` in it and say so in the build report.

---

## 9. What was executed, and against what oracle

Measurements taken while writing this spec, at `89f8ef7`, in a clean
worktree, with `SELF_LEARN_HOME` / `XDG_CACHE_HOME` left to the suite's
own `tmp_path` redirection. Experiment artifacts are retained under the
git-ignored `misc/u-sdkr/`. **A builder who cannot reproduce `E1`–`E3`
should stop**, because `Fix-1`'s entire armor budget rests on them.

| # | Measurement | Command | Result |
|---|---|---|---|
| `E1` | CLI suite baseline | `uv run --project . pytest -q` in `plugins/self-learn/cli`, rc captured **unpiped** | **1868 passed, 5 skipped**, rc **0**, 256.49 s |
| `E2` | **Variant A** — `--strict-mcp-config` added to `build_reader_argv`, containment left at `strict_mcp=False` | same | **1 failed, 1867 passed, 5 skipped**, 265.44 s. The single failure is `tests/test_invocation.py::test_cn10_argv_is_the_third_witness_iff_both_directions`, at the `assert "--strict-mcp-config" not in argv` branch |
| `E3` | **Variant B** — argv flag **and** `strict_mcp=True` | same | **1 failed, 1867 passed, 5 skipped**, 287.57 s. The single failure is `tests/test_invocation.py::test_cn2_call_site_containment_matches_the_call_site_table`, at `assert spec_miner.containment.strict_mcp is False`. `CN10` is **green** in this variant — the `iff` is satisfied |
| `E4` | Restore verified | `sha256sum` of both edited files + `git status --porcelain` | `miner.py` `daa34e85…`, `contract.py` `a46adbc1…`, both equal to their pre-experiment values; status **empty** |
| `E5` | Is `test_invocation.py` mechanically frozen? | grep of `plugins/self-learn/cli/tests/*.py` for the literal `test_invocation.py` | **No.** Four hits in `test_invocation_sdk.py` (module docstring + `_test_invocation_py_source` + `SU6`'s `ast.parse`) and two in `test_u_fake.py` (the importer-site check). **No sha pin, no `git diff` guard.** The freeze is a spec-level convention, so this unit's allowance must be explicit — and its numstat bound is the only mechanical enforcement |
| `E6` | Is `fake_claude.py`'s scenario set pinned? | grep of `tests/` for `SCENARIOS` | Three hits, **all inside `tests/fixtures/fake_claude.py` itself**. Adding a scenario is free |
| `E7` | The seven monkeypatch sites | grep + `awk` over `tests/test_miner.py`; **re-read at r3** after `MAJOR-1` | **7** `monkeypatch.setattr(miner, "_invoke_reader", …)` sites in **6** containing functions: `test_halt_persists_across_slices`, `test_run_held_gate_keeps_cursors`, `test_failed_reader_keeps_cursors`, `test_first_run_initializes_forward_only` (×2), `test_watchdog_cooldown_after_failed_attempt`, **and the module-level helper `shim_reader` (`def` at `test_miner.py:311`, patch at `:319`)**. **r2 was wrong** on the attribution: it recorded 5 functions and doubled `test_run_held_gate_keeps_cursors`, which carries exactly one site. See `E17` for `shim_reader`'s 78 call sites |
| `E8` | The reader's shipped containment | read of `containment_for`'s `miner-reader` branch | `allowed_tools=None` (forced), `disallowed_tools=` caller's, `write_globs=(f"{spool_dir}/**",)`, `write_exact=()`, `strict_mcp=False`, `default_mode="default"` (forced) |
| `E9` | `shims.py`'s guards | read of `test_u_fake.py::test_sh1_…` / `test_sh4_…` | `SH1` pins **per-builder** emitted bytes for the two existing builders against literal input paths; `SH4` audits `__all__`, call sites and fixture-marking. A **third** builder invalidates neither sha |
| `E10` | Highest existing ids | grep of `14-forward-work-map.md` and `03-decisions.md` | `FW-94`, `S-38`. This unit's rows start at **FW-95** and **S-39** |
| `E11` | Is the reader the only surface without the flag? | grep of `src/` for `--strict-mcp-config` | **No.** Exactly one emitting site, `worker.build_argv` (serving `worker` **and** `worker-repair`). `analyst.build_argv` and `miner.build_reader_argv` both omit it. The commissioning brief's "the ONE surface without it" is false as written; §1.2 states the true, narrower form |
| `E12` | The flag on the installed CLI | `claude --version`; `claude --help \| grep -i strict-mcp` | **2.1.235**. `--strict-mcp-config` present: *"Only use MCP servers from --mcp-config, ignoring all other MCP configurations."* `worker.py`'s recorded live verification is against **2.1.226** — hence `VB-1` |
| `E13` | **When did `--strict-mcp-config` actually enter production?** (`Mit-b`'s safety base) | `git log -S'"--strict-mcp-config"' -- …/worker.py`, then `git log -1 --format='%H %ad %s' --date=short` on the result | **One** introducing commit: `9715314`, **2026-08-08**, *"feat(worker): U-repair — unattended elicitation contract, bounded repair round, provenance, backoff (FW-83)"*. **11 days** of production exposure at r2's writing (2026-08-19), across nightly **and** kick-driven worker runs. **Not** 2026-07-15 — that date belongs to the containment audit cited by `READER_DISALLOWED_TOOLS` and by `build_argv`'s prompt-on-stdin rationale, a different change. `Mit-b` records the corrected figure |
| `E14` | **Does the runbook `Mit-c` is supposed to land in exist?** | `ls docs/specs/self-learn/`; heading scan of `15-orchestration-runbook.md` (157 lines, positive-controlled with `grep -c ""`); `grep -rn "U-docs" docs/specs/self-learn/` | **No.** The only runbook is `15-orchestration-runbook.md`, an **orchestration** document — §1 round lifecycle, §3 worktree discipline, §4 reviewer isolation, §5 merging, §6 sandbox invariants — with **no** operations section, **no** watch list and **no** miner-flip section (a `watch\|miner` grep over it returns nothing, against a positive-controlled 157-line read). **Scope of the `U-docs` claim, qualified (`NOTE-9`):** the string appears nowhere in the **non-draft** `docs/specs/self-learn/` tree that this spec can cite as shipped doctrine; the **approved plan** the coordinator works from is not in this repo, so `U-docs` may well be a real planned unit there. The honest statement is *"no home exists in-repo yet,"* not *"no such unit exists."* Hence `Mit-c1` |
| `E15` | **`Fix-1`'s real diff shape** (`MAJOR-2`) | applied the argv element **and** the `F-a` docstring sentence, then `git diff --numstat`, `git diff -U3 \| grep -c '^@@'`, `git diff -U5 \| grep -c '^@@'`; restored and sha-verified | **6 insertions / 1 deletion; TWO hunks at `-U3`; ONE hunk at `-U5`.** The two edits sit ~9 lines apart, so default-context diffing splits them. r2's "one hunk" bound would have failed a correct build. The deletion is the docstring's closing line, rewritten |
| `E16` | **`options_kwargs`' key count** (`NOTE-10`, `CT2`'s set equality) | AST parse of `backend.py::options_kwargs`' base dict literal | **14** unconditional keys — `cwd, system_prompt, model, allowed_tools, disallowed_tools, can_use_tool, permission_mode, setting_sources, settings, strict_mcp_config, mcp_servers, include_partial_messages, env, cli_path` — plus `max_turns` and `max_budget_usd` added conditionally on `dataclasses.fields(ClaudeAgentOptions)`, giving **16** on the pinned SDK |
| `E17` | **`shim_reader`'s reach** (`MAJOR-1`, refined at r4 by `NOTE-c`) | `grep -cE "^\\s+shim_reader\\(" tests/test_miner.py`; plus an **AST pass** mapping each call site to its enclosing `FunctionDef` | **78 call sites across 68 DISTINCT tests** — all 68 are `test_*` functions; **eight** call the helper more than once (`test_A10_measured_incident_drained_over_consecutive_runs` and `test_recurrence_suspect_idempotent_across_replay_and_backfill` call it 3×, six others 2×). **The blast-radius figure is 68**, not 78: 68 is the number of tests that break. The frozen Python surface behind `_invoke_reader` is one helper plus 68 tests, not "seven tests" |
| `E18` | **The reader's default model** (`MAJOR-A2`) | `grep -n "DEFAULT_MINER_MODEL" src/self_learn/miner.py` | `DEFAULT_MINER_MODEL = "claude-sonnet-5"` (`miner.py:92`), returned by `miner_model()` unless `SELF_LEARN_MINER_MODEL` is set. Confirms the literal offered as the optional pin in `Mit-a`'s command. **Incidental finding reinforcing `R-1`:** `test_invocation_sdk.py::_miner_argv`'s default parameter is `"claude-haiku-4-5"` — a *second* way that test-local literal has drifted from the product, alongside its missing `--strict-mcp-config` |

**Not measured, and therefore not claimed:** that the reader's session
starts faster, or at all differently, with the flag (`VB-2`); that a
`max_turns=60` exhaustion on the reader produces any particular outcome
shape (`VB-3`); that any real nightly run has ever been affected by an
inherited MCP server. This unit changes one flag on the strength of the
worker's stated rationale and the suite's `iff`, and says so.

---

## 10. Revision history

| Rev | Change |
|---|---|
| r1 | First draft. Written at `89f8ef7` against the landed Wave-1 code, not against the Wave-1 specs — §15 of the u-sdk fact-gathering pass found eight places where those specs have gone stale relative to the code, and this document treats the code as ground truth throughout. Three claims in the commissioning brief were checked and one was corrected (`E11`); the armor cost of `Fix-1` was measured rather than estimated (`E2`, `E3`); four values questions are routed and **not** ruled (§8). |
| r4 | **Delta-gate fold** — r3 returned **0 BLOCKER / 2 MAJOR / 4 NOTE**, with all 19 r3 landings independently verified. **`MAJOR-A1`**: `M34` was inverted — it mutated toward a *bare* `except Exception`, which **widens** the handler, and since `ProcessLookupError` and `PermissionError` are both `OSError` subclasses a widened handler swallows both and leaves `TO5` **green**. Restated as the **narrowing** mutant (`except ProcessLookupError` alone → the `PermissionError` leg reddens; symmetric alternative noted), and `TO5`'s own sentence corrected to drop the false "collapsed `except Exception`" claim and to state plainly what the criterion **cannot** see. `NOTE-d` folded into `K-c`: **one** clause catching two types at `invocation/cli.py`'s `killpg` site, with a **separate** clause of the same shape in `invocation_sdk/lifecycle.py`'s `kill_child` — different module, different call, `TO6`'s business. **`MAJOR-A2`**: `Mit-a`'s preflight command **was not runnable** — `--model "$(: …)"` expanded empty (`:` is the shell no-op builtin) and the `--settings` file was named but never created; **both defects produce a usage error, the exact symptom the preflight exists to detect**, so either would have been reported as a false positive. `--model` dropped (with `claude-sonnet-5` offered as an optional literal pin, verified at `E18`), settings-file creation added as a required first line, and the pass condition stated ("a `timeout`-killed run with no usage error is a pass"). **NOTEs**: `Sets-1`'s fenced table row corrected to `(2 sites)` so it sums to seven; `M35` corrected to redden `RC3`'s **sdk leg only**, with the symmetric cli-side mutant (`TRANSPORT["miner-reader"].result_stdout = "empty"`) named; `E17`/`Sets-1` rephrased to **78 call sites across 68 distinct tests**, with **68** identified as the blast-radius figure. New `E18`. **Counts: 51 criteria, 35 mutations (both unchanged), 17 → 18 evidence rows.** |
| r3 | **Gate fold** — r2 returned **NOT SOUND: 0 BLOCKER / 7 MAJOR / 12 NOTE**; all remedies folded. **`MAJOR-5`** (orchestrator ruling): `VB-1`/`Mit-a` downgraded from build blocker to **operator preflight** with an exact command — r2 had written a gate whose only discharge was a real credentialed session by a builder agent, which the campaign's tripwire doctrine forbids outright; `Mit-c`'s watched first nightly is now the binding backstop (failure mode: one missed mine, alarm-detected, zero data loss). **`MAJOR-1`**: `Sets-1`/`SU3`/`D-11` corrected — the 7th monkeypatch site is in the module-level `shim_reader` helper, not a doubled site in `test_run_held_gate_keeps_cursors`; 6 containing functions, and `shim_reader`'s **78** call sites make the frozen surface far larger than seven tests (`E17`). **`MAJOR-2`**: the one-hunk clause dropped from `MC5`/may-touch — measured at **6/1, two hunks at `-U3`, one at `-U5`** (`E15`); the AST-range clause carries the meaning. **`MAJOR-3`**: `T2-c` gains step 6 (`FAKE_CLAUDE_RESULT_TEXT` → `_extract_text` branch 1), without which the sdk leg has no stdout and `RC3`/`RC4` are unsatisfiable there; `T2-b`'s signature gains the matching `stdout_text` knob; the overwritten-`last_assistant_text` trap recorded. **`MAJOR-4`**: §4's blanket parametrization header replaced by **per-criterion leg markers**; `SW1` marked deliberately unparametrized and importing `sdk_absent` from `test_invocation_sdk` per the `test_invocation.py:46-48` precedent. **`MAJOR-6`**: docs may-touch widened to **five** `FW` rows (`FW-95`…`FW-99`, incl. `Mit-c`'s carrier) and new instrument criterion **`SU7`** asserts they landed at the expected ids with a positive control; `Mit-b`'s discharge made concrete. **`MAJOR-7`**: four safety mutations added — `M32` (selector collapse → `FL3`+`CT3`), `M33` (dropped `clear_sidecar` → `TO7`), `M34` (collapsed except clauses → `TO5`), `M35` (`_stdout_for` → `RC3`). **NOTEs 1–12 folded**, incl. `M1`/`M4`'s corrected credit annotations, `C-f`'s honest account of `CT1`'s partial re-derivation (`CT4`/`CT5` are the independent oracle), `RC5` re-scoped as fixture-pinning, `CT2`'s 16-key set equality (`E16`), `TO7`'s named spy hook, `TIMEOUT_PATCH` defined once, the foreign-id prefix convention (§0.5), and `E14`'s letter qualified to the non-draft in-repo tree. New `K-f` states plainly that `TO2`'s sdk leg runs a **real** kill ladder against the fake child it spawned — permitted and deliberate. **Counts: 50 → 51 criteria, 31 → 35 mutations, 14 → 17 evidence rows.** |
| r2 | **§8's four questions folded as RULED** (coordinator, against the approved plan): `Q-1` YES/mandate with three required mitigations (`Mit-a`/`Mit-b`/`Mit-c` + `Mit-c1`); `Q-2` no CLI-side analyst fix per the user's `F3` ruling, owner **nobody**; `Q-3` keep `strict_mcp` as the second witness, do not derive; `Q-4` deferred to the miner-flip decision. `VB-1` promoted from verification item to **build blocker**. `D-1` loses its conditional; `R-2`/`R-3`/`R-4` gain their ruled owners. Two supporting citations in the rulings were checked against the repo rather than restated, and **both needed correcting**: the flag's production exposure dates from **2026-08-08**, not the 2026-07-15 containment audit (`E13`, ~11 days not ~5 weeks), and the runbook watch-list / U-docs home `Mit-c` was to be filed in **does not exist yet** (`E14`) — so `Mit-c1` records the obligation here and carries it by `FW` row instead of citing a phantom section. **Criterion and mutation counts unchanged** — the rulings settled scope questions, not test design. |

Counts live in §4's header and §5's header and are not restated here —
one register per fact.
