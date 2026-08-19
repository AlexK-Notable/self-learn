# Spec — U-sdka: the analyst SDK contract, the hardening, and the first flip

Status: **r3 — CLEARED FOR BUILD.** Delta gate: **SOUND — 0 BLOCKER / 0 MAJOR / 2 NOTE**, both folded (§12). Both dispositions were verified at full-suite level, the `Pin-1` census was re-derived independently, §11.2's two claims were executed, and `M31` was spot-executed — with both instruments silent throughout (zero sessions, tripwire never fired). Prior round: r1 blind gate:
**NOT SOUND — 1 BLOCKER / 5 MAJOR / 10 NOTE**, all folded (§12 maps each
to its change). The mechanism was verified strong and is unchanged; the
BLOCKER was **blast-radius accounting** — the built state breaks **eight**
shipped tests, not six, and `E3`'s rung-1 shadow was structurally blind to
both extras (§3.3 `A-0`, `E12`, `E13`). §10 `V-1` was **RULED — Option A,
as drafted**; no criterion or design decision moved for it.
Unit `U-sdka`, **Wave 2** of
the approved Agent-SDK migration: the first unit that changes which
backend a shipped surface runs on.

**Base commit:** `89f8ef7` (master — the `U-fake` merge, "Wave 1
complete"). Every symbol, count, sha and behavior quoted in this document
was read or measured at that commit, in this worktree. `analyst.py`,
`invocation/contract.py`, `invocation/registry.py` and `provider.py` are
uncontended.

**The unit in one sentence.** Make the analyst's output contract hold
identically on both backends, close the never-lost hole FW-87 names (on
*both* backends, because the sdk leg has its own flavor of it), and then
flip the analyst's default backend to `sdk` — by changing **four data
cells and one branch**, with `SELF_LEARN_BACKEND_ANALYST=cli` as the
instant rollback.

**This unit changes behavior. Deliberately, and in exactly two places.**

1. **The flip.** `analyst.analyze` resolves the `SdkBackend` by default.
   `worker`, `worker-repair` and `miner-reader` keep resolving `cli`, and
   their bytes are untouched.
2. **FW-87.** A transport error that today escapes `analyze` as a raw
   traceback — losing the lesson the user just typed — becomes an
   `AnalystError`, so `teach.py`'s capture-to-pending path catches it and
   exit 4 keeps its promise. This changes the **cli** leg too, and it is
   the one place this unit is not byte-identical under `backend=cli`.

Everything else under `SELF_LEARN_BACKEND_ANALYST=cli` is byte-identical
to `89f8ef7`. A builder who finds themselves fixing a third thing has
left this unit's mandate and must stop and report.

**Why the analyst is first** (from the approved plan, restated so this
document is self-contained): it is *attended* — a human is watching every
`teach --route` — it is the **lowest-volume** surface, and the flip **is
the F3 security fix. The analyst is today the weakest-contained of the
four surfaces**: no settings file at all, no `--disallowedTools`, no
`--strict-mcp-config`, and the whole record body sitting in `argv`. Under
the `SdkBackend` it inherits `setting_sources=[]`, the charter's
deny-by-default `can_use_tool`, `strict_mcp_config=True`, and a prompt
that travels over the client's stdin instead of the process table. §3.5
pins each of those as a criterion; §9 records the measurement.

---

## Files this unit may touch

| File | Footprint |
|---|---|
| `plugins/self-learn/cli/src/self_learn/invocation/contract.py` | **Two data edits, no new logic.** (a) NEW module-level `DEFAULT_BACKEND_FOR_SURFACE` table + its `__all__` entry (`Flip-1`, §3.1). (b) `TRANSPORT["analyst"].catches_os_error` `False`→`True` and `_ANALYST_TEMPLATES.os_error` `None`→one byte-pinned string (`Err-1`, §3.4). **Numstat-bounded**: ≤ **16 insertions / ≤ 3 deletions** — **measured 14/2** for §3.1's and §3.4's quoted forms (11-line table block + 1 `__all__` entry + 1/1 for `catches_os_error` + 1/1 for `os_error`); the **+2/+1 slack is deliberate**, and covers comment rewrapping only. No other table, dataclass, or function in the module changes. |
| `plugins/self-learn/cli/src/self_learn/invocation/registry.py` | Rung 5 only: `return _CLI_BACKEND` becomes a table read (§3.1). **Numstat-bounded**: ≤ **8 insertions / ≤ 1 deletion** — **measured 7/1** for §3.1 `F-b`'s quoted form (6 lines replacing `    return _CLI_BACKEND`, plus one name added to the existing `from .contract import (…)` list), or **3/1** compacted. **No "one hunk" clause**: the import list and the return statement are necessarily separate hunks, so that clause was unachievable regardless of spelling (per the `U-sdkr` precedent the gate cites). **AST-range clause instead**: every changed line lies either inside `backend_for`'s AST range or inside the module's `from .contract import (…)` statement. Nothing else changes — `_resolve`, `KNOWN_BACKENDS`, `_SDK_UNAVAILABLE_MESSAGE` and the four upper rungs are byte-identical. |
| `plugins/self-learn/cli/src/self_learn/provider.py` | Rung 5 of the **second transcription** only: `resolve_backend_name`'s `return "cli", "default"` becomes the same table read, plus the import line (§3.2). **Numstat-bounded**: ≤ **3 insertions / ≤ 2 deletions**. `resolve`, `model_for`, `session_env`, `preflight` and every doctor row builder are untouched. |
| `plugins/self-learn/cli/src/self_learn/analyst.py` | `analyze`'s failure dispatch only: one new `os-error` branch, rendered through `LOG_TEMPLATES["analyst"].os_error` per `W-h` (§3.4). **Numstat-bounded**: ≤ **8 insertions / ≤ 0 deletions**. `build_argv`, `_model`, `_timeout`, `_parse_yaml_map`, `doctrine_path`, the pre-spawn guards, Register R's copy-then-stamp, the roster-sha honesty legs and `validate_proposal` are **untouched** — this unit does not read them, move them, or reorder them. |
| `plugins/self-learn/cli/tests/conftest.py` | **One line** appended to the existing `_worker_test_defaults` fixture: `monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")` (`Armor-1`, §3.3). `_no_real_sdk_spawn_tripwire` is **sha-pinned and byte-unchanged** (`AR1`). **Numstat-bounded**: ≤ **10 insertions / 0 deletions** — **measured 9/0** for the block §3.3 prints verbatim (8 comment lines + 1 `setenv`); +1 slack for comment rewrapping. |
| `plugins/self-learn/cli/tests/fixtures/fake_claude.py` | **Additive only.** Two new scenarios (`analyst_result`, `analyst_blocks`) + their two `SCENARIOS` entries + argv recording (`Fake-3`, §3.6). Every pre-existing scenario function is **sha-pinned** (`HY3`). **Numstat-bounded**: ≤ **40 insertions / ≤ 0 deletions** outside the two `SCENARIOS` dict lines. |
| `plugins/self-learn/cli/tests/test_invocation.py` | **Three bounded edits, exactly three functions.** (a) `test_rg1_five_rung_precedence_resolves_in_isolation`'s default-rung assertion becomes surface-aware (§3.3 `A-c`). (b) `test_tr4_bare_os_error_escapes_analyst_but_not_worker_or_miner` inverts, name included (§3.4 `E-f`). (c) `test_wr6_…`'s final leg gains **one** pin-restoring `setenv`, changing no assertion (§3.3 `A-d`). **Numstat-bounded**: ≤ **22 insertions / ≤ 6 deletions**. No other test in the file is touched — `test_lg7_…` stays **unedited and green** (`E-g`). |
| `plugins/self-learn/cli/tests/test_invocation_sdk.py` | **Three bounded edits, exactly three functions**: `test_ou5_bare_oserror_escapes_worker_miner_caught_analyst_reraised` inverts, name included; `test_ou1_every_row_of_the_map_1_table`'s *"bare OSError — worker (caught) vs analyst (re-raised)"* sub-leg inverts (both §3.4 `E-f`); and `test_rs2_present_returns_sdkbackend_for_every_surface` gains **one** pin-clearing `delenv`, changing no assertion (§3.3 `A-e`). Its sibling `test_rs2_present_resolves_absent_…` is **not** touched. **Numstat-bounded**: ≤ **22 insertions / ≤ 8 deletions**. |
| `plugins/self-learn/cli/tests/test_doctor_invocation.py` | **Two bounded edits**: `test_dc2_…`'s per-surface default expectation, and `test_dc3_…`'s wholly-inert case, which must now pin the analyst to `cli` to *construct* that state (§3.3 `A-c`, measured in §9 `E7`). **Numstat-bounded**: ≤ **10 insertions / ≤ 4 deletions**. |
| `plugins/self-learn/cli/tests/test_u_sdka.py` | **NEW.** Every criterion in §4 lands here unless it says otherwise. |
| `docs/specs/self-learn/14-forward-work-map.md` | **FW-87's disposition note** (§7.4), plus new rows for §7.3's residuals. Lands in the same commit as the build. |
| `docs/specs/self-learn/03-decisions.md` | New rows `S-37`, `S-38` (§7.5). Same commit. |

**No file in `GUARDED` may be edited.** `GUARDED` is `U-fake`'s
`Freeze-1` set — `test_worker.py`, `test_repair.py`, `test_attrib.py`,
`test_route_cli.py`, `test_composer.py` — whose non-`REWRITTEN` top-level
functions are sha-pinned by `test_u_fake.py::test_ds1_…`. That constraint
is **why §3.3 exists at all**, and it is criterion `SU3`. `worker.py`,
`miner.py`, `invocation/cli.py`, `invocation/fake.py`,
`invocation_sdk/**`, `tests/shims.py`, `tests/backends.py`,
`test_lock_invariant.py` and `plugins/self-learn/ui/**` are untouched.

---

## 0. Reading order and precedence

1. **§4 (acceptance criteria) and §5 (mutation plan) ARE the spec.**
   Everything else is rationale. Where prose and a criterion disagree,
   **the criterion wins** and the prose is the defect.
2. Every set, table and name is defined **once**, in §3, and referenced by
   name thereafter. A second definition anywhere is a bug in this
   document.
3. Code is located **by symbol plus a distinctive quoted source line**,
   never by bare line number.
4. **Every number here is a measurement, not a constant** (`U-fake`'s
   `Meas-1`, applied to this unit). Counts, shas and distributions were
   measured at `89f8ef7` and are recorded as **provenance**; the binding
   form is a **delta** against the builder's own rebase base, measured
   with the same command, and the build report records both numbers.
5. Read before this document: `U-seam`'s §3.5–§3.7 and §3.9.3, `U-sdk`'s
   §3.5/§3.6/§3.12, `U-fake`'s §1.3 and §3.6, and `analyst.py` end to
   end. This spec quotes them but does not reproduce them.

---

## 1. Why this unit exists

### 1.1 What is true today

`analyst.analyze` builds a `SessionSpec` with `surface="analyst"`, calls
`invocation.text_session(spec)`, and parses `outcome.stdout` as YAML. The
seam resolves `CliBackend` for it, on every rung, because rung 5 is the
bare statement `return _CLI_BACKEND`. Nothing about the analyst's output
contract has ever been exercised against a second backend, and two of its
error legs cannot be reached at all under `cli`.

### 1.2 What the flip actually buys

The analyst is the **only** shipped surface whose containment is expressed
in nothing but two argv flags. Measured at `89f8ef7` from
`containment_for("analyst", allowed_tools=ANALYST_ALLOWED_TOOLS)`:

```
Containment(allowed_tools='Read,Grep,Glob', disallowed_tools=None,
            write_globs=(), write_exact=(), strict_mcp=False,
            default_mode=None)
```

— no settings file (`X-2`), no `--disallowedTools`, no
`--strict-mcp-config`, and `analyst.build_argv` puts the **entire composed
record prompt in `argv`**, where any process on the host can read it out
of `/proc`. Under the `SdkBackend`, that same containment produces the
option set §9 `E5` measured: `allowed_tools=[]`, `setting_sources=[]`,
`settings=None`, `strict_mcp_config=True`, `mcp_servers={}`,
`permission_mode='default'`, and a `can_use_tool` callback that — §9 `E6`
— **denies `Write`, `Edit`, `NotebookEdit`, `Bash`, `Task` and `WebFetch`
and allows only `Read`, `Grep`, `Glob`**. The prompt goes over the
client's stdin; §9 `E5` confirms it appears **nowhere** in the option
mapping.

That is the F3 fix, and it arrives as a consequence of the flip rather
than as new security code. §3.5 turns each clause into a criterion.

### 1.3 What this unit is not

It is not the worker or miner flip (Wave 3+). It is not a rewrite of
`analyst.analyze`'s parse, stamp, or validate stages — those are
`U-analyst`/`U-composer`/`u-table` territory and are frozen here. It is
not a place to unify the four surfaces' log wording (`R-2`, still open).
It is not permitted to re-baseline any sha-pinned guard: `HY3`, `SU3` and
`AR1` are the three that must stay green **on their existing literals**.

---

## 2. What binds this design from outside it

Shipped, currently-green facts. Each removes an option this unit might
otherwise have taken. A builder who trips one has a red suite, not a
discussion. Every one was **measured**, not read off a prior spec.

**`B-1` — the suite-wide claude-argv guard reaches the new file.**
`test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`
globs `tests/*.py` and asserts, for every line matching
`\[\s*"claude"\s*\]`, that the line also contains
`worker._invoke_claude(`. `test_u_sdka.py` is inside that glob.
Criterion `HY1`.

**`B-2` — the `_find_cli` tripwire is load-bearing and must never fire.**
`conftest.py::_no_real_sdk_spawn_tripwire` (session-scoped, autouse)
replaces `SubprocessCLITransport._find_cli` with a raiser. **Measured**
(§9 `E3`, `E3a`): with the analyst resolving `sdk` and no
`SELF_LEARN_SDK_CLI_PATH`, **21 of the 22** shipped failures came *through
this tripwire*. The twenty-second, `test_wr6_…`, fails **pre-transport**:
it requests `sdk_absent`, so the lazy import is blocked and
`BackendUnavailable` is raised before any `ClaudeSDKClient` exists —
`_find_cli` is never reached. Either way **not one spawned a real
session**, which is the property that matters. Every sdk-leg test in this unit sets
`SELF_LEARN_SDK_CLI_PATH`. The fixture itself is **sha-pinned** by `AR1`;
this unit adds a sibling line to `_worker_test_defaults` and touches the
tripwire not at all.

**`B-3` — `U-fake`'s `Freeze-1` sha-pins five test modules.**
`GUARDED = ("test_worker.py","test_repair.py","test_attrib.py","test_route_cli.py","test_composer.py")`;
for each, `test_u_fake.py::test_ds1_…` sha256s the concatenated source of
every top-level function whose inverse-renamed name is **not** in
`{claude_shim, notify_shim, _capture_analyst_prompt}` plus three `Move-1`
test names. Two consequences, both measured:

- `claude_cli_shim_analyst` (in `test_route_cli.py`) and
  `claude_cli_shim_worker` (in `test_worker.py`) are **excluded** from the
  sha — they inverse-rename to `claude_shim`. Editing those fixture bodies
  would be invisible to `DS1`.
- `test_composer.py::_shim_env` — the helper that installs the PATH
  `claude` for the two composer tests the flip breaks — is a plain
  top-level function and is **not** excluded. **Editing it reddens
  `DS1`.** Re-baselining `DS1`'s literal to accommodate that edit is
  `U-fake`'s `M18`, *"the named catastrophe"*. It is forbidden here.

This pair of facts is the entire reason §3.3 chooses a `conftest.py`
default over per-file edits.

**`B-4` — `provider.resolve_backend_name` is a SECOND, INDEPENDENT
transcription of the five-rung chain**, and `test_provider.py::test_bk1_agrees_with_registry_over_matrix`
compares it against `backend_for` over a matrix that **includes the
default rung for all four surfaces**. A registry-only flip makes the two
disagree for the analyst and reddens `BK1`. That is not a nuisance — it is
the shipped cross-check doing its job, and §3.2 is the response.

**`B-5` — the second transcription is load-bearing for provider
resolution, not just for reporting.** `provider.resolve()` gates its
bedrock refusal on `backend == "sdk"`, and `session_env()`'s row 2 returns
`{}` when `backend != "sdk"`. `invocation_sdk/provider_env.py` calls both.
So a registry-only flip would give the analyst an **sdk session with no
provider environment and no refusal** under `provider=bedrock` — a silent
mis-route to the Anthropic API. §3.2 closes it; `FL5` is the guard.

**`B-6` — `ClaudeSDKError` is not an `OSError`.** Measured (§9 `E8`):
`ClaudeSDKError.__mro__` is `(ClaudeSDKError, Exception, BaseException,
object)`. Therefore a bare `except OSError` inside `analyst.analyze` —
the literal reading of FW-87 — would **not** close the never-lost hole on
the sdk leg. §3.4 explains what does.

**`B-7` — the sdk leg has its own instance of FW-87's defect, and it is
reachable.** Measured (§9 `E9`): pointing `SELF_LEARN_SDK_CLI_PATH` at a
non-executable file makes `SdkBackend.text_session` raise
`CLIConnectionError("Failed to start Claude Code: [Errno 13] Permission
denied: …")` **out of the seam**, because `TRANSPORT["analyst"]
.catches_os_error is False` and `_drive`'s `except ClaudeSDKError` leg
re-raises on that surface. Same class of loss, different exception type.

**`B-8` — `claude_agent_sdk` reaches production through
`[dependency-groups] dev`, not through the `[sdk]` extra.** Measured (§9
`E2`): `uv run --project plugins/self-learn/cli python -c "import
claude_agent_sdk"` succeeds, resolving **0.2.134** from the project venv;
`~/bin/self-learn` is `exec uv run --project …/cli self-learn "$@"` and
`install.sh` runs `uv sync --project "$P/cli"` — both include the `dev`
group by default. The flip therefore lands on a runtime where the SDK is
importable. §10 `V-1` routes the packaging question this exposes; `FL7`
pins what happens when it is *not* importable, so the answer is never a
lost lesson.

**`B-9` — the baseline.** Measured at `89f8ef7` (§9 `E1`): CLI suite
**1873 collected, 1868 passed, 5 skipped, 0 failed**, 251.51 s. The five
skips are `test_lock_invariant.py`'s four *"not a ledger-mutating
surface"* skips and `test_regime_fixes.py`'s *"repo-root suite absent"*.

---

## 3. The change

### 3.1 `Flip-1` — the per-surface default table (NORMATIVE)

Rung 5 of `U-seam`'s precedence chain stops being a constant and becomes a
**table keyed by surface**, defined **once**, in `invocation/contract.py`
beside `SURFACES` and `SELECTOR_FOR_SURFACE`:

```python
#: `Flip-1` (U-sdka) -- rung 5 of the backend precedence chain, per
#: surface. The analyst flips first (attended, lowest volume, and the
#: flip IS the F3 containment fix); worker/worker-repair/miner-reader
#: stay on the cli path until their own wave. Every value must be a
#: member of `registry.KNOWN_BACKENDS`.
DEFAULT_BACKEND_FOR_SURFACE: dict[str, str] = {
    "worker": "cli",
    "worker-repair": "cli",
    "miner-reader": "cli",
    "analyst": "sdk",
}
```

**`F-a` — it lives in `contract.py`, not `registry.py`.** `contract.py` is
where every other per-surface table lives (`SELECTOR_FOR_SURFACE`,
`TRANSPORT`, `LOG_TEMPLATES`), it is stdlib-only (`I-a`), and both
consumers already import from it. Putting it there makes the flip literally
*a data change*, which is what the migration plan asked for. It is added to
`contract.__all__`.

**`F-b` — rung 5 resolves THROUGH `_resolve`, not around it.**
`backend_for`'s final statement becomes:

```python
    return _resolve(
        surface,
        DEFAULT_BACKEND_FOR_SURFACE.get(surface, "cli"),
        source="the built-in default",
        is_config=False,
    )
```

Three properties this buys, each a criterion:

- the lazy `sdk` import, `BackendUnavailable`, and the `cli` fast path all
  keep exactly one implementation (`FL1`, `FL7`);
- the fail-closed rule survives verbatim — a value outside
  `KNOWN_BACKENDS` at *any* rung, including a mistyped table entry, warns
  and falls to `cli` (`FL3`);
- an unknown **surface** falls back to `"cli"` via `.get(...)` rather than
  `KeyError` — `_dispatch` already refuses unknown surfaces upstream
  (`S-c`), and this keeps `backend_for` callable in isolation (`FL1`'s
  last leg).

**`F-c` — the table never warns.** Every value in it is a member of
`KNOWN_BACKENDS`, so `_resolve`'s warn branch is unreachable from rung 5.
A criterion asserts both halves: the containment
`set(DEFAULT_BACKEND_FOR_SURFACE.values()) <= set(KNOWN_BACKENDS)`, and an
empty stderr on a default-rung resolution for all four surfaces (`FL3`).

**`F-d` — the rollback is rung 1 and it is not new machinery.**
`SELF_LEARN_BACKEND_ANALYST=cli` shadows every lower rung, including the
table. `SELF_LEARN_BACKEND=cli` shadows rungs 3–5. `config.yaml`'s
`invocation.backend_analyst: cli` shadows rungs 4–5. All three already
work; `FL2` proves the table did not break them, and `M4` is the negative
control (a build that consults the table *before* the env vars).

### 3.2 `Twin-2` — the second transcription moves with the first (NORMATIVE)

`provider.resolve_backend_name` re-derives the same five rungs (`Rs-a`)
and its rung 5 is the literal `return "cli", "default"`. It reads the
**same table**:

```python
    return DEFAULT_BACKEND_FOR_SURFACE.get(surface, "cli"), "default"
```

reached by extending the module's **existing**
`from .invocation.contract import SELECTOR_FOR_SURFACE, SURFACES` line
with `DEFAULT_BACKEND_FOR_SURFACE`. No new import statement, and no
cycle: `provider.py` already imports from `invocation.contract`, and
`contract.py` imports nothing from `self_learn`.

**`T-a` — one table, two readers, no third transcription.** The point of
`Rs-a`'s independence is that the *chain logic* is transcribed twice so a
divergence is visible; the *default values* are data and must have one
owner, or the two transcriptions can silently disagree about the very
thing this unit changes. `FL5` asserts agreement over the full matrix and
`M5` is the negative control (registry flipped, provider not) — the
mutation `B-4` says the shipped `BK1` already catches, which `M5` must
confirm rather than assume.

**`T-b` — what `B-5` makes this worth.** With both readers on the table,
`provider.resolve("analyst", home).backend == "sdk"` by default, so under
`provider=bedrock` the analyst is a **refusing surface by default** when
no `provider.bedrock.models.analyst` is set: `session_env` raises
`ProviderRefused`, `_drive`'s guarded call converts it to
`Outcome(failure="unavailable")`, `analyze` converts that to
`AnalystError`, and `_route_now` captures to `pending/` with exit 4.
Measured shape in §9 `E7`; pinned by `AC7`'s `refused-config` row and by
`DR2`. The operator's live ledger carries **no `config.yaml`** (§9 `E2`),
so the shipped default provider is `anthropic` and this path is inert
there today — which is exactly why it must be pinned by a test rather than
by the burn-in.

### 3.3 `Armor-1` — how 22 shipped tests keep testing the cli path (NORMATIVE)

**The problem, measured — and the measurement is not the whole problem.**
§9 `E3`: with the analyst resolving `sdk`, **22 shipped tests fail** — 12
in `test_route_cli.py`, 7 in `test_invocation.py`, 2 in
`test_composer.py`, 1 in `test_regime_fixes.py`. Each drives the analyst
through a bash PATH shim (or a monkeypatched `subprocess.run`) and names
no backend, so the flip routes it to an SDK session it never asked for.
That set is `SHADOW_22`, defined once, here, by the command in §9 `E3`.

**`A-0` — `E3` is a rung-1 shadow, and a shadow is not the built state.
Two casualties are structurally invisible to it (`E12`, `E13`).** The
shadow sets `SELF_LEARN_BACKEND_ANALYST=sdk` in the ambient environment;
the built state sets `…=cli` in `conftest.py` and moves the *default* to
`sdk`. Those two differ wherever a test **touches that variable itself**,
and both blind spots are real:

| # | Casualty | Why `E3` could not see it | Measured |
|---|---|---|---|
| 1 | `test_invocation.py::test_wr6_…`'s **final** (template-indirection) leg | The shadow and the built state **diverge inside one test**: `_clear_backend_env` + `delenv("SELF_LEARN_BACKEND")` wipe the ambient shadow *and* the built pin, leaving no backend env — which under the flip is the new **default rung** = `sdk`. With `sdk_absent` active the lazy import fails, so the raised `AnalystError` carries the `BackendUnavailable` install message instead of `"MUTATED NOT FOUND TEXT"`. `wr6` fails in **both** states, for **different reasons**, so its presence in `SHADOW_22` masked a second, independent failure underneath | `E12` |
| 2 | `test_invocation_sdk.py::test_rs2_present_returns_sdkbackend_for_every_surface` | It **passed** under the shadow *because* the shadow set the very value it wants. It sets rung 2 (`SELF_LEARN_BACKEND=sdk`) and asserts all four surfaces resolve `SdkBackend`; the built pin sits at **rung 1**, which shadows rung 2 for the analyst → `CliBackend`. That file has **no** env-clearing fixture | `E13` |

**The corrected accounting.** **24 failure events over 23 distinct
tests** — `test_wr6_…` appears in both sets, for two different reasons.
Two derived sets follow, and they are what the criteria use:

- **`ARMOR_21` = `SHADOW_22` \ {`test_wr6_…`}** — the tests the
  `conftest.py` pin repairs completely, which must keep passing
  **unedited**. These are **T3 byte-identity armor** (`U-fake` `Tier-b`,
  `V-2`): they hold the independent check on the CLI path until
  `U-cleanup` deletes it.
- **`LATENT_2` = {`test_wr6_…`, `test_rs2_present_returns_sdkbackend_for_every_surface`}**
  — the two the pin does **not** repair. Both join `EDITED` (`A-d`,
  `A-e`).

The r1 draft's `ARMOR_22` and its `E-g` promise that `test_wr6_…` "must
pass untouched" were **measured false**. `SU4` now asserts over
`ARMOR_21`, and the disjointness leg is `EDITED ∩ ARMOR_21 == ∅`.

**The mechanism.** `conftest.py`'s existing `_worker_test_defaults`
autouse fixture gains one line:

```python
    # U-sdka `Armor-1`: the analyst's SHIPPED default backend is now
    # `sdk` (invocation/contract.py `DEFAULT_BACKEND_FOR_SURFACE`). Every
    # pre-existing analyst test drives a bash PATH shim or a patched
    # `subprocess.run`, i.e. the cli transport, and names no backend --
    # same convention as SELF_LEARN_WORKER_AUTOKICK and
    # SELF_LEARN_NO_NOTIFY above: the suite opts OUT of real machinery by
    # default and a test that wants it opts back IN. `test_u_sdka.py`'s
    # FL1 asserts the PRODUCT default directly, with this var cleared.
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
```

**`A-a` — why here and not in the fixtures.** Three of the four affected
files could be fixed in a fixture body (`claude_cli_shim_analyst` and
`claude_cli_shim_worker` are `DS1`-excluded, `B-3`). The fourth cannot:
`test_composer.py::_shim_env` is a guarded top-level function, so any edit
there reddens `DS1`, and the only way to make `DS1` green again is to
re-baseline its literal — `U-fake`'s `M18`. One `conftest.py` line fixes
all four files, edits nothing guarded, and states the rule once instead of
four times.

**`Pin-1` — the pin sits at RUNG 1, and a rung-1 pin cannot be overridden
by any test at rungs 2–5 (NORMATIVE).** This is the exact converse of
`M25`: that row records that *weakening* the pin to rung 2 would let any
test's rung-1 setting shadow it; `Pin-1` records that *keeping* it at rung
1 shadows any test that sets rungs 2–5 and expects the analyst to follow.
The pin therefore has exactly one class of casualty, and the class must be
**enumerated mechanically, not discovered**:

> A test is a `Pin-1` casualty iff it sets `SELF_LEARN_BACKEND` (rung 2)
> or writes `invocation.backend` / `invocation.backend_analyst` into a
> `config.yaml` (rungs 3–4), **and** exercises the analyst surface (or all
> of `SURFACES`), **without** first clearing `SELF_LEARN_BACKEND_ANALYST`.

**Measured (`E13`): the class has exactly one member.** **28
`sdk`-VALUED** rung-2 setter sites exist across four files. *(The raw grep
for `setenv("SELF_LEARN_BACKEND", …)` returns **36** — doctor 3 /
invocation 14 / invocation_sdk 6 / provider 13. It reconciles to 28 only
when restricted to `value == "sdk"`: a site setting `cli`, `bogus`, `""`
or `fake` cannot produce the shadow-failure this census hunts, because the
pin and the site then agree, fall through, or fail closed together. A
builder reproducing the number with the unqualified grep gets 36 and
concludes the spec is wrong — hence the qualifier. `AR5`'s criterion text
is unaffected: it already keys on the analyst-reaching condition, not on a
grep count.)* `test_doctor_invocation.py` and
`test_provider.py` are immune — both carry an autouse `_clear_provider_env`
that deletes the rung-1 var. `test_invocation.py`'s sites are each
preceded by `_clear_backend_env`. `test_invocation_sdk.py` has **no**
clearing fixture, and of its six sites five reach only
`backend_for("worker", …)`; the sixth,
`test_rs2_present_returns_sdkbackend_for_every_surface`, loops
`invocation.SURFACES`. That is the one. Criterion **`AR5`** re-runs this
census as a test, so the class stays closed as the suite grows rather than
resting on this enumeration.

**`A-b` — this is a default, not a mask, and the difference is a
criterion.** A suite-wide pin has the fail-open shape: it can make the
shipped default untested everywhere. Two criteria close that:

1. Criterion `FL1` asserts the **product** default directly, with all
   backend env cleared (`monkeypatch.delenv`), for all four surfaces.
2. Criterion `AR2` is the positive control on the pin itself: inside a
   nested `pytest.MonkeyPatch()` it deletes `SELF_LEARN_BACKEND_ANALYST`
   and asserts the analyst resolves `SdkBackend` — so a build that
   "fixed" the flip by only editing `conftest.py` fails loudly.

(Both are **defined** in §4; the lines above are references, not a second
definition.)

**`A-c` — three tests still need their own edit, because they clear the
env themselves.** These are outside `SHADOW_22` (the `E3` run could not
see them) and outside `GUARDED`:

| Test | File | Why it moves |
|---|---|---|
| `test_rg1_five_rung_precedence_resolves_in_isolation` | `test_invocation.py` | Its last statement asserts the default rung yields a `CliBackend` **for every surface**, after `_clear_backend_env`. Under the flip the analyst's default rung yields `BackendUnavailable` (the test requests `sdk_absent`). The assertion becomes surface-aware, reading `DEFAULT_BACKEND_FOR_SURFACE` — **not** a hardcoded second copy of it. |
| `test_dc2_switches_names_all_surfaces_and_changes_with_rung` | `test_doctor_invocation.py` | Its autouse `_clear_provider_env` deletes every backend var; it asserts `f"{surface}: backend=cli (default)"` for all four. The analyst's line becomes `analyst: backend=sdk (default)` — measured, §9 `E7`. |
| `test_dc3_rollout_four_states` | `test_doctor_invocation.py` | Its **wholly-inert** case writes a bedrock config with no backend env and expects a single `FAIL` rollout row. After the flip that state is no longer inert, and `(line,) = _rows_by_name(out, "rollout")` unpacks four rows. The case must **pin** `SELF_LEARN_BACKEND_ANALYST=cli` to construct wholly-inert; the other three cases are unaffected (measured). |

`FLIP_EDITS` is the name of this three-row set.

**`A-d` — `test_wr6_…`'s disposition: RESTORE THE PIN (one line), not
retarget the assertion.** The final leg gains, immediately above its
`monkeypatch.setattr(subprocess, "run", _run_raises(FileNotFoundError()))`:

```python
    # U-sdka `Armor-1`/`A-d`: `_clear_backend_env` above deleted conftest's
    # SELF_LEARN_BACKEND_ANALYST=cli pin, and the analyst's DEFAULT rung is
    # now `sdk` (invocation/contract.py `DEFAULT_BACKEND_FOR_SURFACE`).
    # Restore the pin: the `subprocess.run` patch below is meaningless on
    # any backend but the cli one, so this leg is ABOUT that transport.
    monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")
```

Six insertions, zero deletions, and **every assertion in `wr6` stays byte-
identical**. The alternative — retargeting the leg's expectation to the
flip's new behavior (the `FL7` refusal) — is **rejected on coverage**, and
the reasoning is recorded because the choice was the spec author's:

1. **It trades unique coverage for duplicate coverage.** This leg is the
   *only* thing in the suite proving `not_found` is rendered **through**
   `LOG_TEMPLATES["analyst"]` rather than from a local f-string.
   Retargeting moves that proof onto `unavailable` — whose bytes `wr6`'s
   own leg e4 already pins, and whose never-lost chain `FL7` already
   drives end to end through `teach --route`. Both halves of the
   "arguably a better test" case are **already shipped by this unit**; the
   `not_found` indirection is not.
2. **It matches the leg's intent.** The leg patches `subprocess.run`. That
   patch has meaning on exactly one backend. Restoring the pin converts an
   ambient dependency (legs e1–e3 already rely on the conftest pin) into a
   stated one — a repair, not a mask.
3. **It keeps `wr6` falsifiable.** `M9` and `M14` still redden `HD1`
   through this path, and new row `M31` makes the pin-restore itself
   falsifiable via `AR3`.

**`A-e` — `test_rs2_present_returns_sdkbackend_for_every_surface`'s
disposition: CLEAR THE PIN (one line).** It gains, as its first statement:

```python
    # U-sdka `Pin-1`: conftest pins SELF_LEARN_BACKEND_ANALYST=cli at RUNG
    # 1, which shadows this test's rung-2 SELF_LEARN_BACKEND=sdk for the
    # analyst surface. This test is ABOUT rung 2 reaching every surface,
    # so it clears rung 1 first. The pin's one and only rung-2 casualty
    # (`E13`'s census).
    monkeypatch.delenv("SELF_LEARN_BACKEND_ANALYST", raising=False)
```

Six insertions, zero deletions; no assertion changes. Its sibling
`test_rs2_present_resolves_absent_raises_byte_identical_unavailable` is
**not** touched — it reaches only `backend_for("worker", …)` (`E13`).

**`A-f` — `EDITED`, re-derived.** Eight functions across four files:

```
EDITED = FLIP_EDITS            { test_rg1_…, test_dc2_…, test_dc3_… }     (the flip)
       ∪ FW87_EDITS            { test_tr4_…, test_ou1_…, test_ou5_… }     (§3.4 `E-f`)
       ∪ LATENT_2              { test_wr6_…, test_rs2_present_returns_… } (`A-d`, `A-e`)
```

`SU4` asserts `ARMOR_21` is byte-unchanged **and** `EDITED ∩ ARMOR_21 ==
∅`; `AR3` asserts `EDITED` is exactly these eight and that every other
top-level function in the four files is byte-identical to its base-commit
bytes; `AR5` asserts `Pin-1`'s class stays closed.

### 3.4 `Err-1` — FW-87, closed at the seam rather than at the caller (NORMATIVE)

FW-87 (`14-forward-work-map.md`, row `FW-87`, owner **U-sdka**) says:
*"the error contract must catch into `AnalystError` on BOTH backends so
capture-to-pending holds regardless of the switch."*

**`E-a` — the literal fix does not work, and `B-6`/`B-7` are why.** A
`try: … except OSError: raise AnalystError(...)` around
`invocation.text_session(spec)` inside `analyze` closes the cli leg and
**misses the sdk leg entirely**, because the sdk leg's instance of the
same defect arrives as `CLIConnectionError`, a `ClaudeSDKError`, which is
not an `OSError`. Widening the catch to `except Exception` at that call
site would swallow programming errors — the thing `U-sdk`'s `MAJOR-3`
deliberately refused to do — and `analyst.py` may not import
`claude_agent_sdk` to catch by type (the SDK is optional to this package).

**`E-b` — the fix is two data cells in `contract.py`.** The analyst
surface stops being the one surface whose transport re-raises:

```
TRANSPORT["analyst"].catches_os_error :  False  ->  True
_ANALYST_TEMPLATES.os_error           :  None   ->  "analyst invocation failed ({exc})"
```

Both backends read those cells and need **no edit**:

- `CliBackend._run`'s `except OSError` consults
  `transport.catches_os_error` and now renders the template instead of
  re-raising.
- `SdkBackend._drive`'s `except ClaudeSDKError` and `except OSError` legs
  consult `_CATCHES_OS_ERROR`, which is **derived from `TRANSPORT`** at
  module import, and now render the same template instead of re-raising.

One table edit; two backends fixed; the seam's `S-a`/`S-b` contract
(*"never raises"*) becomes **total**, its one documented exception (`T-c`)
retired. `U-seam` residual `R-1` is closed here, not merely worked around.

**`E-c` — the new template string is byte-pinned and labeled *new*.**
`"analyst invocation failed ({exc})"` — no `run: ` prefix (the analyst
surface has never carried one), the same `({exc})` shape as the worker's
`run: {label}claude invocation failed ({exc})` and the miner's
`run: reader invocation failed ({exc})`. There is no pre-`U-sdka` behavior
for it to match, exactly as `W-i`'s `unavailable` string had none.

**`E-d` — `analyze` gains one branch, rendered through the template
(`W-h`).** Placed **after the `unavailable` branch**, i.e. last among the
five. r1 said "in `FAILURE_KINDS` order", which is wrong — the shipped
order is `not-found`, `timeout`, `exit`, `unavailable`, not the tuple's.
The correction is cosmetic: the five branches test `outcome.failure`
against distinct string literals, so they are mutually exclusive and no
ordering is observable. Recorded so a gate does not read the r1 claim as a
requirement and reorder the shipped branches to satisfy it:

```python
    if outcome.failure == "os-error":
        assert templates.os_error is not None  # Err-1: the analyst now carries this leg
        raise AnalystError(templates.os_error.format(exc=outcome.detail)) from outcome.exc
```

**`E-e` — the branch is about the MESSAGE, not about never-lost, and the
mutation row says so.** Without it, an `os-error` `Outcome` falls through
to `_parse_yaml_map(outcome.stdout)` with `stdout == ""`, which raises
`AnalystError("analyst output is not a YAML mapping (got NoneType)")` —
so the lesson survives either way once `E-b` lands. Deleting the branch
must therefore redden a **byte-exact message** criterion (`HD1`) and must
**not** be creditable against the never-lost criteria (`M13`'s row records
this explicitly). Stating it here stops a gate from crediting the wrong
criterion.

**`E-f` — exactly three shipped assertions invert, and they are named.**
All three assert the *preserved defect* directly and all three carry an
inline comment citing `R-1`/`T-c`; each inverts to assert the
**conversion**, and each keeps a comment naming **FW-87** as the authority
so the next reader does not "restore" the defect.

| Site | What it asserts today | Why it is not in `SHADOW_22` |
|---|---|---|
| `test_invocation.py::test_tr4_bare_os_error_escapes_analyst_but_not_worker_or_miner` | `pytest.raises(OSError)` around `CliBackend().text_session(_spec("analyst"))` | It injects `CliBackend()` **explicitly**, so it never resolves through the registry and `E3` could not see it |
| `test_invocation_sdk.py::test_ou5_bare_oserror_escapes_worker_miner_caught_analyst_reraised` | `pytest.raises(OSError, match="boom-ou5")` around `_run_text(_spec("analyst", …))` | Same — it constructs `SdkBackend()` directly |
| `test_invocation_sdk.py::test_ou1_every_row_of_the_map_1_table`, its *"bare OSError — worker (caught) vs analyst (re-raised)"* sub-leg | `pytest.raises(OSError, match="transport blew up")` | Same |

Each of the three test **names** changes with its body — they name the
old behavior, and a name that lies is worse than no name.

**`E-g` — one look-alike that must NOT be edited, and one that turned
out to be a casualty.** `test_invocation.py::test_lg7_…` drives three arms
(`FileNotFoundError`, `TimeoutExpired`, `rc=1`), none of which is a bare
`OSError`, and it never clears the backend env — so it is repaired by the
`conftest.py` pin alone and must pass **untouched**. `test_wr6_…` was
claimed here in r1 as a second such look-alike; that claim was **measured
false** (§3.3 `A-0`, `E12`). Its `not_found` / `timeout` / `exit` /
`unavailable` legs and its FW-87 exposure are indeed unaffected — it needs
**no** `os-error` row — but its final template-indirection leg is a
`conftest`-pin casualty and is repaired by `A-d`'s one line, which changes
no assertion. A builder who finds themselves adding an `os-error` row to
`test_wr6_…` has mis-scoped `E-b`; `HD1` covers the new leg.

**`E-h` — this section owns `FW87_EDITS`, not `EDITED`.** The three
functions above are `FW87_EDITS`. The complete `EDITED` set — eight
functions, across `test_invocation.py`, `test_invocation_sdk.py`,
`test_doctor_invocation.py` and (via `A-e`) `test_invocation_sdk.py` again
— is assembled **once**, in §3.3 `A-f`, from `FLIP_EDITS` ∪ `FW87_EDITS` ∪
`LATENT_2`. Nothing else in the suite is edited, and
`EDITED ∩ ARMOR_21 == ∅` (`SU4`).

---

### 3.5 `Cont-1` — the analyst's SDK containment, pinned (NORMATIVE)

The flip's security claim (§1.2) is asserted as facts about the option
mapping and the charter callback, not as prose. All values below were
**measured** at `89f8ef7` (§9 `E5`, `E6`) and are the criteria's
literals.

| Property | Pinned value | Criterion |
|---|---|---|
| write tools | `Write` / `Edit` / `NotebookEdit` → `PermissionResultDeny` | `HD5` |
| read tools | `Read` / `Grep` / `Glob` → `PermissionResultAllow` | `HD5` |
| everything else | `Bash` / `Task` / `WebFetch` → `PermissionResultDeny` | `HD5` |
| enforcement hatch | **closed** — `default_mode is None` **and** both write sets empty, so `hatch_open` is `False` | `HD5` |
| strict MCP | `strict_mcp_config is True`, `mcp_servers == {}` | `HD6` |
| settings isolation | `setting_sources == []`, `settings is None` | `HD6` |
| tool shadowing | `allowed_tools == []` (`F-B`) | `HD6` |
| permission mode | `permission_mode == "default"` | `HD6` |
| prompt location | the composed prompt appears in **no** value of `options_kwargs(spec)`, and reaches the child as a stdin `{"type":"user"}` message, never in the child's argv | `HD7` |
| model identity | `provider.model_for("analyst", home=…) == analyst._model()` under `provider=anthropic` | `HD8` |

**`C-a` — `HD5` is driven END TO END, not only as a unit call.** A
`build_can_use_tool` unit test proves the callback's logic; it does not
prove the callback is *wired*. The `ok_write` scenario already emits a
real `can_use_tool` control_request, so `HD5`'s deny leg runs the analyst
surface through the fake with `FAKE_CLAUDE_FORCE_SCENARIO=ok_write` and
asserts the tool result comes back `is_error=True` carrying the charter's
message, **and** that the denial was recorded in `SdkOutcome.denials`
(`C-9`). The unit-level table above is the second, cheaper leg.

**`C-b` — `HD7` needs the fake to record its own argv**, because the
claim is about the **child process's** command line, not ours. §3.6 adds
that. The negative control is explicit: the same assertion run against the
**cli** leg must **fail** to find the prompt absent — on that leg it *is*
in argv (`AV4`), and a criterion that passes on both legs is measuring
nothing.

**`C-c` — what this unit does NOT assert about containment.** That the
SDK's charter matches the CLI's own settings-file rule evaluation
(`U-sdk` §8 row 7, `R-5`, still unmeasured). That reads outside `cwd`
reach `can_use_tool` (`U-sdk` §8 row 6, `UNKNOWN`). Neither binds the
analyst, whose write sets are empty and whose read scope is unscoped by
design (`C-2`).

### 3.6 `Fake-3` — the fake CLI's additive extensions (NORMATIVE)

`tests/fixtures/fake_claude.py` gains **two scenarios and one recorder**.
Nothing existing changes: every pre-existing scenario function is
sha-pinned by `HY3`, and the two new `SCENARIOS` entries are the only
edits to that dict.

**`FK-a` — `analyst_result`.** Emits an `AssistantMessage` carrying a
fixed sentinel, then a `ResultMessage` whose `result` is the contents of
the file named by `FAKE_CLAUDE_OUT`. This is `U-sdk`'s `E-7` **branch 1**
(`ResultMessage.result` wins over the assistant text), and the sentinel
must differ from the file's contents or the branch order is untestable —
the same discipline `_scenario_ok_text` already applies.

**`FK-b` — `analyst_blocks`.** Emits an `AssistantMessage` whose content
is the contents of `FAKE_CLAUDE_OUT` **split across two `TextBlock`s**,
then a `ResultMessage` with **no** `result` key. This is `U-sdk`'s `E-7`
**branch 2**, and the split is what makes the `"".join(...)` observable —
a single block would pass with or without the join.

**`FK-c` — `FAKE_CLAUDE_OUT` is the sdk leg's `CLAUDE_SHIM_OUT`.** One
file, one meaning on both legs: *what the model said*. That symmetry is
the whole point of `U-fake` §1.2, and it is what lets a single T2 body
assert the same proposal on both backends.

**`FK-d` — argv recording.** When `FAKE_CLAUDE_ARGV_LOG` is set, `main()`
writes its own `sys.argv[1:]` to that path, NUL-separated, **before**
reading stdin — the same encoding `write_analyst_claude_shim` uses
(`printf '%s\0'`), so `HD7`'s two legs parse identically. Inert when the
variable is unset, so no existing test changes behavior.

**`FK-e` — still no network, still no model.** `HY3` re-asserts the
shipped scan: no `subprocess`, `socket`, `urllib` or `http` import appears
in the file after this unit's additions.

**`FK-f` — the scenario is selected by force, not by content.** A real
composed analyst prompt can never equal a `SCENARIOS` key, so every sdk
leg in this unit sets `FAKE_CLAUDE_FORCE_SCENARIO` (`MAJOR-2`'s
test-fixture-only knob). No production code reads it; `HY2` re-asserts
that.

### 3.7 `T2-1` — the contract-test harness (NORMATIVE)

`LEGS = ("cli", "sdk")`. One `params=`-parametrized fixture in
`test_u_sdka.py` installs a leg and returns a small handle; every `AC`
criterion is written **once** and runs twice.

```python
@pytest.fixture(params=LEGS)
def leg(request, tmp_path, monkeypatch):
    ...
```

**`H-a` — the cli leg** sets `SELF_LEARN_BACKEND_ANALYST=cli`, creates its
own shim directory, and **calls** `tests/shims.py::write_analyst_claude_shim`
— a plain function precisely so a `params=` fixture body can call it
(`U-fake` `D-8`/`SH4`). It prepends the directory to `PATH` and sets
`CLAUDE_SHIM_LOG` / `CLAUDE_SHIM_CWD` / `CLAUDE_SHIM_OUT`. `shims.py` is
**not edited**.

**`H-b` — the sdk leg** sets `SELF_LEARN_BACKEND_ANALYST=sdk`,
`SELF_LEARN_SDK_CLI_PATH` to `tests/fixtures/fake_claude.py`,
`CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1`, `FAKE_CLAUDE_OUT`,
`FAKE_CLAUDE_ARGV_LOG`, and `FAKE_CLAUDE_FORCE_SCENARIO=analyst_result`.

**`H-c` — the handle is the contract.** `leg.name`; `leg.say(text)`
writes *what the model said* to the leg's output file; `leg.argv()` reads
the child's recorded argv; `leg.fail(kind)` installs one failure. Nothing
in an `AC` body may branch on `leg.name` **except the one declared
asymmetry that lives in the `AC` group — `AC2`'s single-text-channel
collapse on the cli leg.** (r1 pointed at "§3.5 `C-b` and §3.8"; §3.8 is
*What deliberately does not move* and names no asymmetry. The correct pair
is `AC2` and `HD7`, and **`HD7` is in the `HD` group, so it never consumes
the `AC` cap** — leaving the cap at **one**, not two.) A criterion (`AC0`,
folded into `HY2`'s AST scan) asserts it: **at most one** `leg.name ==`
comparison appears in the whole `AC` group, carrying a comment naming the
asymmetry it encodes. **The `AC` group is identified by name** — top-level
functions in `test_u_sdka.py` matching `^test_ac\d+_` — so the scan has a
mechanical population and cannot be widened by moving a test out of the
group without also renaming it. A T2 test that branches per leg is two T1
tests wearing one name.

**`H-d` — `leg.fail(kind)`, per `FAILURE_KINDS` member.** This table is
the definition; `AC7` walks it.

| kind | cli leg | sdk leg |
|---|---|---|
| `exit` | `CLAUDE_SHIM_EXIT=1` | `FAKE_CLAUDE_FORCE_SCENARIO=error_result` |
| `timeout` | a **local** two-line `sleep`-shim written by this test file (the `shims.py` builder is the stdout-shaped fake and has no sleep knob; `test_regime_fixes.py::test_analyst_timeout_captures_to_pending` is the shipped precedent) + `SELF_LEARN_ANALYST_TIMEOUT=0.3` | `FAKE_CLAUDE_FORCE_SCENARIO=hang` + `SELF_LEARN_ANALYST_TIMEOUT=0.5` |
| `not-found` | the shim directory is removed from `PATH` | `SELF_LEARN_SDK_CLI_PATH=/nonexistent/claude-fake` (the shipped `OU`-leg idiom) |
| `os-error` | `monkeypatch.setattr(subprocess, "run", …)` raising `PermissionError` | `SELF_LEARN_SDK_CLI_PATH` pointed at a **non-executable** file — measured to produce `CLIConnectionError` (§9 `E9`) |
| `unavailable` | **not reachable** — declared, not simulated (see `H-e`) | `sdk_absent` (rung-5 default) for the missing-extra case; a refusing bedrock config for the `refused-config` case |

**`H-e` — two legs are asymmetric by construction, and the asymmetry is
itself asserted.** `unavailable` cannot arise on the cli leg (nothing
refuses), and `refused-config` cannot either — `session_env`'s row 2
returns `{}` whenever `backend != "sdk"`. `AC7`'s cli column for those two
rows is therefore a **negative control**: the same refusing bedrock
configuration under `SELF_LEARN_BACKEND_ANALYST=cli` produces a **normal,
successful route**. Without that control the row would read as "not
tested" rather than "structurally impossible".

### 3.8 What deliberately does not move

- **`analyst.build_argv`** keeps its body and its signature. The sdk leg
  still calls it (through `spec.cli_argv_builder`) and still reads
  `--append-system-prompt` out of it (`A-5`); the rest of the list is
  discarded by that backend. Rewriting it to stop emitting a prompt it no
  longer needs would break the cli leg's byte-identity and `AV4`.
- **`analyst._model` / `_timeout`** keep their bodies. `provider.model_for`
  already **calls** `analyst._model()` for this surface, so model identity
  across the flip holds by construction (`HD8`).
- **The charter, the lifecycle, the kill ladder, the event log.** `U-sdk`
  owns those contracts and they are frozen. This unit asserts the
  analyst's *use* of them and changes none of their code.
- **`tests/conftest.py::_no_real_sdk_spawn_tripwire`** — sha-pinned
  (`AR1`).
- **`TRANSPORT["analyst"]`'s other four fields** — `kind="run"`,
  `kills_process_group=False`, `prompt_via_argv=True`,
  `result_stdout="captured"`. Only `catches_os_error` moves.
- **The worker and miner surfaces**, in every respect. `FL6` is the guard.

---

## 4. Acceptance criteria

**These criteria are the spec.** Each is a named test in
`plugins/self-learn/cli/tests/test_u_sdka.py` unless it says otherwise.
**41 criteria**, in seven groups: `SU` 5, `FL` 7, `AC` 8, `HD` 8, `AR` 5,
`DR` 3, `HY` 5.

### SU — the suite (the headline)

- **`SU1` — stated as a DELTA, per §0 rule 4; the absolute numbers are
  provenance only.** The binding form is measured by the builder, in the
  builder's own worktree, with one command run twice:

  | Quantity | Required |
  |---|---|
  | `collected(HEAD) − collected(base)` | `== len(test_u_sdka.py's tests)` |
  | `passed(HEAD) − passed(base)` | `== len(test_u_sdka.py's tests)` |
  | `skipped(HEAD)` | `== skipped(base)` (5 at `89f8ef7`) |
  | `failed(HEAD)` | `== 0` |

  **Absolute counts are neighbor-falsifiable and must not be the
  criterion.** This repo is worked in parallel git worktrees off one
  checkout; a *sibling* worktree's in-flight test file can enter a
  collection run and move the absolute total without anything in this unit
  changing — the wave-record hazard, observed again on this unit's own
  gate. `1873 collected / 1868 passed / 5 skipped` is what `89f8ef7`
  reported **here** (`B-9`, §9 `E1`) and is recorded as provenance so a
  builder can sanity-check their base; a base that differs is a signal to
  find out why, not a reason to edit this document. *Instrument criterion
  — the build report states base and head numbers and the four deltas.*
- **`SU2`** `git diff --name-only <base>..HEAD` names **exactly** the
  files in §"Files this unit may touch" and nothing else. *Instrument
  criterion.*
- **`SU3`** `test_u_fake.py::test_ds1_…` (the `Freeze-1` body-identity
  guard) passes **on its existing five sha literals**, and
  `git diff --name-only <base>..HEAD -- plugins/self-learn/cli/tests/`
  names no member of `GUARDED`. Both halves, or neither is evidence: the
  sha proves the bytes match something, the diff proves nothing guarded
  was touched. *Instrument criterion + the shipped test.*
- **`SU4`** Every member of `ARMOR_21` passes **unedited**: `SHADOW_22` is
  re-derived at the rebase base by §9 `E3`'s command, `ARMOR_21` is that
  set minus `test_wr6_…` (§3.3 `A-0`), and a test asserts each member's
  source segment is byte-identical to its base-commit bytes (recovered
  with `git show <base>:…`, never from the working tree). **Plus the
  disjointness leg**: `EDITED ∩ ARMOR_21 == ∅`, where `EDITED` is §3.3
  `A-f`'s **eight** functions across four files. An `ARMOR_21` member that
  also appears in `EDITED` means the armor and the edit list disagree
  about the same test — resolve the disagreement before the build, do not
  pick a side. A `SHADOW_22` count other than 22 at the rebase base is
  investigated, not absorbed; and because the shadow is a **lower bound**
  (`A-0`), a build report that shows only `SHADOW_22` repaired has not
  demonstrated `SU1`.
- **`SU5`** The UI suite is untouched: `git diff --name-only` names no
  path under `plugins/self-learn/ui/`. *Instrument criterion.*

### FL — the flip

- **`FL1`** With **all four** backend env vars deleted and no
  `config.yaml`, `backend_for(surface, home=…)` returns an `SdkBackend`
  for `"analyst"` and a `CliBackend` for `"worker"`, `"worker-repair"` and
  `"miner-reader"` — asserted by **identity**
  (`type(b) is self_learn.invocation_sdk.SdkBackend`, imported
  independently in the test), not by `isinstance` against a name. Two
  further legs: `DEFAULT_BACKEND_FOR_SURFACE` has exactly the four
  `SURFACES` as keys, and `backend_for("nope", home=…)` returns a
  `CliBackend` rather than raising `KeyError` (`F-b`).
- **`FL2`** Each of the four rungs above the table shadows it, for the
  analyst: `SELF_LEARN_BACKEND_ANALYST=cli` → `CliBackend`;
  `SELF_LEARN_BACKEND=cli` → `CliBackend`; `config.yaml`
  `invocation.backend_analyst: cli` → `CliBackend`; `invocation.backend:
  cli` → `CliBackend`. And the inverse for the three cli surfaces: each of
  the same four rungs set to `sdk` yields an `SdkBackend`, so the table
  did not become a ceiling. **`SELF_LEARN_BACKEND_ANALYST=cli` is the
  documented rollback** and this criterion is its proof.
- **`FL3`** Fail-closed survives the table. (i) An unknown value at each
  of the four configurable rungs still yields `cli` with the byte-exact
  warning of `U-seam` §3.7.2 — including on the **analyst**, where the
  fallback is now a *downgrade* from the default rather than a no-op.
  (ii) A default-rung resolution for all four surfaces writes **nothing**
  to stderr. (iii) `set(DEFAULT_BACKEND_FOR_SURFACE.values()) <=
  set(KNOWN_BACKENDS)`.
- **`FL4`** The flip is **data**: an AST scan of `registry.py` finds no
  string literal `"sdk"` or `"analyst"` inside `backend_for`, and
  `backend_for`'s final return reads `DEFAULT_BACKEND_FOR_SURFACE`. A
  build that hardcodes `if surface == "analyst": return SdkBackend()`
  fails here even though `FL1` would pass.
- **`FL5` — the two transcriptions agree.** For every surface × every rung
  (env selector, env general, config per-surface, config general, **and
  the default**), `provider.resolve_backend_name(home, surface)[0]` equals
  the name `backend_for` actually resolves — where "the name" is derived
  as `test_provider.py::_backend_for_expectation` derives it
  (`BackendUnavailable` ⇔ `"sdk"`; not-a-`CliBackend` ⇔ `"sdk"`). Plus:
  the default rung's `source` is `"default"` for all four surfaces, and
  the shipped `test_provider.py::test_bk1_agrees_with_registry_over_matrix`
  passes unedited.
- **`FL6` — worker and miner are untouched.** A shimmed `worker.run`
  (batch **and** repair round) and a shimmed `miner.run`, with no backend
  env set, still spawn the bash shim — asserted on the shim's own
  invocation counter, which is `0` if an SDK session was used instead.
  And `provider.resolve_backend_name(home, s)[0] == "cli"` for all three.
- **`FL7` — the missing extra never loses a lesson.** Under `sdk_absent`
  (the shipped `sys.modules` import block, never an uninstall), with all
  backend env cleared: `backend_for("analyst", …)` raises
  `BackendUnavailable` whose `str()` is byte-identical to
  `_SDK_UNAVAILABLE_MESSAGE`; `text_session` returns
  `Outcome(failure="unavailable")` **without raising**; `analyze` raises
  `AnalystError` carrying `W-i`'s two-line literal; and `teach --route`
  exits **4** with the composed record in `pending/` and
  `"captured to pending"` on stderr.

### AC — the analyst output contract, on both backends (T2)

Every criterion in this group is parametrized over `LEGS` (§3.7) and runs
twice. Two of them carry the declared per-leg asymmetry (`H-c`).

- **`AC1`** The same YAML said by the model produces the **same validated
  proposal** on both legs: identical key set, identical `destination`,
  `alternates`, `rationale`, and identical CLI-stamped `record_sha`. On
  the sdk leg this is `U-sdk`'s `E-7` **branch 1** (`FAKE_CLAUDE_FORCE_SCENARIO=analyst_result`);
  the assistant sentinel that branch 1 must beat is asserted **absent**
  from the proposal.
- **`AC2`** `U-sdk`'s `E-7` **branch 2**: with `analyst_blocks`, the YAML split
  across two `TextBlock`s and no `ResultMessage.result`, the proposal is
  identical to `AC1`'s — proving the join. *This criterion's cli leg is
  the same single-channel stdout read — **the one declared per-leg branch
  the `AC` group is permitted** (`H-c`): the cli transport has one text
  channel, so branch 1 and branch 2 are the same path there.*
- **`AC3`** `_parse_yaml_map` round-trips identically on both legs for:
  a ` ```yaml ` fence, a bare ` ``` ` fence, and unfenced YAML; and
  refuses identically for unparseable YAML and for a non-mapping — the
  `AnalystError` message is byte-compared against the shipped literals on
  both legs.
- **`AC4`** CLI-stamped fields win on both legs: a model-supplied `model`,
  `analyzed_at` and `record_sha` are **overwritten**, `record_sha` equals
  `sha_anchor(record.body)`, and `script` is stripped **unconditionally**
  (both a `hook` and a `skill-md` destination).
- **`AC5`** Fields the doctrine does not enumerate round-trip verbatim on
  both legs (Register R): a proposal carrying `hook`, `examples` and an
  invented key survives the parse→stamp→validate path with those keys
  intact.
- **`AC6`** The decision-trace shape is unchanged on both legs: a
  `gates.t3.roster_sha` that is well-shaped but wrong raises `AnalystError`
  naming **X3 Leg A**; a `roster_sha: "unavailable"` claim against a
  composed roster raises naming **X3 Leg B**; the run's real sha is
  accepted. Byte-compared messages.
- **`AC7` — the never-lost chain, per failure kind × leg.** For each row of
  `H-d`, drive `teach --route` end to end and assert: `rc == 4`
  (`teach.EXIT_ANALYST`), `resolved/` empty, exactly one record in
  `pending/` with `status: pending` and `routing is None`, and stderr
  carrying `"analysis failed"` and `"captured to pending"`. The
  `unavailable`/`refused-config` rows carry `H-e`'s negative control on
  the cli leg — the same refusing bedrock config routes **successfully**
  there, proving the refusal is a property of the sdk backend and not of
  the configuration alone.
- **`AC8`** The happy path is end-to-end identical on both legs: `rc == 0`,
  the record lands in `resolved/` with `routing["by"] == "analyst"`
  (FW-64) and `routing["destination"]` equal to what the model said, the
  compiled line reaches the host `SKILL.md`, and stdout carries
  `"analyst: destination …"`.

### HD — hardening (FW-87 and the containment the flip buys)

- **`HD1` — FW-87, both backends.** An `os-error` on each leg (`H-d`'s
  row) raises `AnalystError`, **not** a raw `OSError`/`ClaudeSDKError`,
  whose message is byte-identical to
  `"analyst invocation failed ({exc})".format(exc=outcome.detail)` and
  whose `__cause__` is the original exception. Asserted with an inverted
  guard (`try: … except (OSError, Exception-that-is-not-AnalystError):
  pytest.fail(...)`), so a re-raise fails loudly instead of being read as
  a different error.
- **`HD2`** The sdk leg's `ClaudeSDKError` flavor specifically (`B-7`'s
  non-executable `cli_path`) lands on the same leg: `failure == "os-error"`,
  `AnalystError`, and the detail contains `"Permission denied"`. This is
  the criterion that would have stayed green under FW-87's literal
  `except OSError` fix, and its row in §5 says so.
- **`HD3`** The whole FW-87 chain, both legs: `teach --route` under an
  injected os-error exits **4** with the record in `pending/`. Before this
  unit the cli leg exits with a traceback and the sdk leg with a different
  traceback; `M12` is the negative control.
- **`HD4`** The seam is now **total** on the analyst surface: for every
  member of `FAILURE_KINDS`, `invocation.text_session(spec)` **returns an
  `Outcome`** and raises nothing — asserted by driving each failure through
  both backends with an inverted `pytest.raises`. `TRANSPORT["analyst"]
  .catches_os_error is True` and `LOG_TEMPLATES["analyst"].os_error is not
  None` are asserted directly.
- **`HD5` — deny-all-writes, wired.** Two legs. (i) Unit: `build_can_use_tool`
  on the analyst containment returns `PermissionResultDeny` for `Write`,
  `Edit`, `NotebookEdit`, `Bash`, `Task`, `WebFetch` and
  `PermissionResultAllow` for `Read`, `Grep`, `Glob`; the hatch is closed
  (`default_mode is None` **and** both write sets empty). (ii) End to end:
  an analyst session driven with `FAKE_CLAUDE_FORCE_SCENARIO=ok_write`
  against a target inside the ledger home comes back `is_error=True`
  carrying the charter's `"write scope does not include"` message, and the
  denial appears in `SdkOutcome.denials`. Leg (ii) is what proves the
  callback is *reached*; leg (i) alone is satisfiable by dead code.
- **`HD6` — isolation and strict MCP.** For a real analyst `SessionSpec`,
  `options_kwargs(spec)` has `strict_mcp_config is True`,
  `mcp_servers == {}`, `setting_sources == []`, `settings is None`,
  `allowed_tools == []`, `permission_mode == "default"`,
  `include_partial_messages is False`, and `max_turns == 30`. Compared
  against the literals of §9 `E5`, not against a re-derivation.
- **`HD7` — the prompt leaves the process table.** On the sdk leg: the
  composed prompt appears in **no** value of `options_kwargs(spec)`, and
  the child's own recorded argv (`FAKE_CLAUDE_ARGV_LOG`, §3.6 `FK-d`)
  contains no substring of it. On the cli leg the **same** assertion is
  run and must **fail** — the criterion asserts the inversion explicitly
  (the second declared asymmetry — but **this criterion is in the `HD`
  group, so it does not consume the `AC` cap**, `H-c`), because a check
  that passes on both legs is measuring nothing. The shipped `AV4` is the cli leg's positive
  statement and stays green.
- **`HD8` — the flip does not change the model.** Under `provider=anthropic`
  (the default) `provider.model_for("analyst", home=…)` **is**
  `analyst._model()` — asserted by monkeypatching `analyst._model` to a
  sentinel and observing it through `model_for`, and by observing that a
  live sdk-leg session's `options.model` equals the value the cli leg puts
  after `--model` in argv.

### AR — the armor (byte-identity under `backend=cli`)

- **`AR1`** `conftest.py`'s `_no_real_sdk_spawn_tripwire` is byte-unchanged
  — `sha256(inspect.getsource(fn))` compared against a literal taken from
  the **base commit's** bytes (`git show <base>:…`), with the build report
  carrying the diff that shows no hunk touches it. Both, or neither is
  evidence.
- **`AR2` — the suite-wide pin is a default, not the thing under test.**
  A test reads `conftest.py`'s source and asserts the pin line is present,
  inside `_worker_test_defaults`, and sets exactly
  `SELF_LEARN_BACKEND_ANALYST=cli`; then, inside a nested
  `pytest.MonkeyPatch()` context, deletes that variable and asserts the
  analyst resolves an `SdkBackend`. A build that "flipped" by editing only
  `conftest.py` fails here.
- **`AR3` — `EDITED` is exactly eight functions, and nothing else moved.**
  An AST scan compares every other top-level function's source against its
  base-commit bytes (`git show <base>:…`) in each edited test module, and
  asserts the changed set is exactly, **with its reason attached**:

  | File | Function | Reason |
  |---|---|---|
  | `test_invocation.py` | `test_rg1_…` | flip (`A-c`) |
  | `test_invocation.py` | `test_tr4_…` | FW-87 (`E-f`) |
  | `test_invocation.py` | `test_wr6_…` | pin casualty (`A-d`) |
  | `test_invocation_sdk.py` | `test_ou1_…` | FW-87 (`E-f`) |
  | `test_invocation_sdk.py` | `test_ou5_…` | FW-87 (`E-f`) |
  | `test_invocation_sdk.py` | `test_rs2_present_returns_sdkbackend_for_every_surface` | `Pin-1` casualty (`A-e`) |
  | `test_doctor_invocation.py` | `test_dc2_…` | flip (`A-c`) |
  | `test_doctor_invocation.py` | `test_dc3_…` | flip (`A-c`) |

  Carrying the reason per function is what stops a ninth edit being
  absorbed as "one of the FW-87 ones". **Two further legs**, because the
  two pin casualties are one-line edits whose *content* matters: the scan
  asserts `test_wr6_…`'s diff adds exactly one `setenv` of
  `SELF_LEARN_BACKEND_ANALYST` to `"cli"` and **changes no `assert`
  statement** (compared as AST, so a comment rewrap does not redden it),
  and that `test_rs2_present_returns_…`'s diff adds exactly one `delenv`
  of the same variable and likewise changes no `assert`. Mutation `M31`.
- **`AR5` — `Pin-1`'s class is closed by census, not by enumeration.** A
  test re-runs §3.3 `Pin-1`'s rule over the whole suite: every test
  function that sets `SELF_LEARN_BACKEND` (rung 2) or writes
  `invocation.backend` / `invocation.backend_analyst` into a `config.yaml`
  (rungs 3–4) **and** reaches the analyst surface or iterates `SURFACES`
  **and** does not first clear `SELF_LEARN_BACKEND_ANALYST` — either
  directly, or through an autouse fixture in its module — is a casualty.
  The asserted casualty set is **exactly**
  `{test_rs2_present_returns_sdkbackend_for_every_surface}` (`E13`).
  A new such test added by a later unit fails this criterion, which is the
  point: the pin's blast radius must stay enumerated as the suite grows.
  Mutation `M33`.
- **`AR4` — byte-identity under the rollback.** With
  `SELF_LEARN_BACKEND_ANALYST=cli`, a real `analyst.analyze` produces: the
  same argv `analyst.build_argv(prompt, doctrine_text, model)` returns
  (element for element, recomputed in the test), the same `cwd` (`pwd -P`
  from the shim equals the ledger home), the same timeout read from
  `SELF_LEARN_ANALYST_TIMEOUT`, and `AnalystError` messages byte-identical
  to the base commit's for `not-found`, `timeout`, `exit` and
  `unavailable`. The `os-error` leg is **excluded and named** — it is
  FW-87, this unit's one sanctioned cli-leg behavior change.

### DR — doctor and operator reporting

- **`DR1`** `self-learn doctor invocation`'s `switches` row reports
  `analyst: backend=sdk (default)` and `backend=cli (default)` for the
  other three, on a pristine home with no backend env. Under
  `provider=anthropic` **no other row changes** — asserted by comparing
  the full `provider.preflight(home)` row list (name, surface, verdict)
  against the same list with `SELF_LEARN_BACKEND_ANALYST=cli`, which must
  differ in exactly the `switches` row (measured, §9 `E7`).
- **`DR2`** Under `provider=bedrock` with a region and **no**
  `provider.bedrock.models.analyst`, the analyst is a refusing surface by
  default: the `rollout` row becomes per-surface with
  `analyst: backend=sdk provider=bedrock`, a `consistency` row with
  surface `analyst` reports `FAIL` carrying `refused-config: ` and
  `bedrock-model-is-alias`'s wording, `models`/`env` for the analyst report
  `FAIL`, the three cli surfaces stay `INFO`/`SKIP`, and the command exits
  **1**. **Plus the `credentials` row: `SKIP` → `WARN`**, detail *"no
  mechanism found (IMDS not probed — see R-4)"* — it is gated on the
  rollout being non-inert, so the flip is what makes it fire, and r1
  missed it because the r1 probe filtered the row set. Compared against
  §9 `E7`'s measured shape, which is now the **full** row list: twelve
  rows unchanged, and exactly these changed — `consistency/analyst` (new
  `FAIL`), `credentials/-` (`SKIP`→`WARN`), `env/analyst`
  (`SKIP`→`FAIL`), `models/analyst` (`INFO`→`FAIL`), `rollout/-`
  (`FAIL`→replaced by four per-surface `INFO` rows), and `switches/-`
  (detail only).
- **`DR3`** `test_dc3_…`'s wholly-inert state is now **constructed**, not
  assumed: with `SELF_LEARN_BACKEND_ANALYST=cli` and a bedrock config, the
  `rollout` row is a single `FAIL`. Without the pin it is not — asserted
  both ways, so the edited test cannot silently stop testing inertness.

### HY — hygiene

- **`HY1`** `test_u_sdka.py` contains no line matching `\[\s*"claude"\s*\]`
  that does not also contain `worker._invoke_claude(` — `B-1` restated
  where it binds; `test_attrib.py::test_hy1_…` stays green.
- **`HY2`** No test in this unit reaches the network or a real model.
  Three legs: every sdk-driving test sets `SELF_LEARN_SDK_CLI_PATH` (AST
  scan of `test_u_sdka.py`); `_no_real_sdk_spawn_tripwire` never fires
  during the unit's tests; and no production module under
  `src/self_learn/` reads `FAKE_CLAUDE_FORCE_SCENARIO`, `FAKE_CLAUDE_OUT`
  or `FAKE_CLAUDE_ARGV_LOG` (source scan). Folds in `AC0` (§3.7 `H-c`):
  **at most one** `leg.name ==` comparison across the whole `AC` group —
  the group being the top-level functions of `test_u_sdka.py` matching
  `^test_ac\d+_` — and it must carry a comment naming its asymmetry.
- **`HY3`** `fake_claude.py`'s additions are additive: each of the **ten**
  pre-existing scenario functions has a `sha256(inspect.getsource(fn))`
  literal taken from the base commit's bytes and asserted equal;
  `SCENARIOS` gains exactly the two new keys and loses none; and the file
  imports no `subprocess`, `socket`, `urllib` or `http`.
- **`HY4`** pyright is clean over the touched product files, from
  `plugins/self-learn/cli/`:
  `pyright --pythonpath .venv/bin/python src/self_learn/invocation src/self_learn/provider.py src/self_learn/analyst.py`
  — **0 errors** over those paths, and the whole-`src` count's **delta
  against the rebase base is 0**. Both numbers in the build report.
  *Instrument criterion.*
- **`HY5`** Every numstat bound in §"Files this unit may touch" holds, per
  file, measured with `git diff --numstat <base>..HEAD -- <path>`.
  *Instrument criterion.*

---

## 5. Mutation plan

**33 mutations.** Every mutation is applied to the **built** code, the
suite is run, and the named criterion must **redden**. A mutation that
leaves the suite green is a hole in §4 and must be closed before the gate,
not explained away.

| # | Mutation | Must redden |
|---|---|---|
| `M1` | `DEFAULT_BACKEND_FOR_SURFACE["analyst"]` → `"cli"` (the flip undone) | `FL1`, `AR2`, `DR1`. **`AC*` is NOT credited** — the `AC` group names its leg explicitly on both legs, so it is structurally blind to the default |
| `M2` | `DEFAULT_BACKEND_FOR_SURFACE["worker"]` → `"sdk"` | `FL1`, `FL6`, and `test_provider.py::test_bk1_…` (shipped) |
| `M3` | The table is dropped and rung 5 hardcodes `if surface == "analyst": return SdkBackend()` | `FL4`. **`FL1` is NOT credited** — it observes the resolved object, which is unchanged |
| `M4` | Rung 5 consulted **first**, before the env rungs | `FL2` (all four rollback rungs), `AR2`'s pin leg, and every `ARMOR_21` member (`SU4`) |
| `M5` | `provider.resolve_backend_name` keeps its literal `return "cli", "default"` (registry flipped, provider not) | `FL5`, and `test_provider.py::test_bk1_…` (shipped — `B-4`'s measured cross-check). **`FL1` is NOT credited** |
| `M6` | `session_env`'s row-2 guard changed from `backend != "sdk"` to a hardcoded `"cli"` comparison against the surface | `DR2`, `AC7`'s `refused-config` row |
| `M7` | A value outside `KNOWN_BACKENDS` placed in the table (`"sdkk"`) | `FL3` (leg iii and the empty-stderr leg), `FL1` |
| `M8` | Rung 5 bypasses `_resolve` and returns `SdkBackend()` directly for the analyst | `FL7` (no `BackendUnavailable` under `sdk_absent`), `FL4` |
| `M9` | `TRANSPORT["analyst"].catches_os_error` back to `False` | `HD1`, `HD2`, `HD3`, `HD4` |
| `M10` | `_ANALYST_TEMPLATES.os_error` back to `None` | `HD4`, and an `AssertionError` from `analyze`'s new branch — which `HD1` observes as a non-`AnalystError` escape |
| `M11` | FW-87 fixed **the literal way**: `TRANSPORT` untouched, a bare `except OSError` wrapped around `text_session` inside `analyze` | **`HD2` is the guard** (the sdk leg's `ClaudeSDKError` still escapes uncaught), plus `HD4`. **`HD1` is NOT claimed**: its cli leg stays green only if the mutant's hand-written `AnalystError` message happens to be byte-identical to `LOG_TEMPLATES["analyst"].os_error`'s rendering — a mutant that words it differently reddens `HD1` too. The row's value does not depend on which way that falls: `HD2` reddens either way, and this is the demonstration that FW-87's literal text is under-specified (`B-6`) |
| `M12` | `analyze`'s `os-error` branch drops its `from outcome.exc` chaining | `HD1`'s `__cause__` leg **only** — the message bytes are unchanged, so every byte-comparing leg stays green. `W-f`'s rule, restated for the new branch: a dropped `from exc` costs a debugger the cause chain and nothing else observes it |
| `M13` | `analyze`'s `os-error` branch deleted, `TRANSPORT` left fixed | `HD1` (byte-exact message: the fall-through yields *"analyst output is not a YAML mapping (got NoneType)"*). **`AC7` and `HD3` are NOT credited** — the lesson still reaches `pending/` (`E-e`), which is precisely why this row is separate from `M12` |
| `M14` | `analyze`'s `os-error` branch carries its own f-string instead of rendering `LOG_TEMPLATES["analyst"].os_error` | `HD1`'s template-indirection leg (monkeypatch the template set, require the raised message to change) — the bytes are identical, so no byte-comparing criterion can catch it (`W-h`, `R-c`'s shape) |
| `M15` | `options_kwargs` sets `strict_mcp_config` from `containment.strict_mcp` (which is `False` for the analyst) | `HD6`, and `test_invocation_sdk.py::test_op6_…` (shipped) |
| `M16` | `options_kwargs` sets `setting_sources=["user","project"]` | `HD6`, and the shipped `OP3` |
| `M17` | The charter's `hatch_open` second conjunct dropped (open whenever `default_mode is None`) | `HD5` legs (i) **and** (ii) — the analyst's empty write sets would stop closing the hatch and every tool would be allowed |
| `M18` | `build_can_use_tool`'s final `return PermissionResultDeny` → `PermissionResultAllow` | `HD5` leg (i)'s `Bash`/`Task`/`WebFetch` rows |
| `M19` | `analyst.py` builds its `SessionSpec` with `prompt=""` and relies on argv | `HD7`'s sdk leg (the prompt never reaches the child), `AC1`, `AC8` |
| `M20` | `SdkBackend` passes the prompt through `options` instead of `client.query` | `HD7`'s "no value of `options_kwargs` contains the prompt" leg |
| `M21` | `_extract_text` returns `last_assistant_text` unconditionally (branch 1 dropped) | `AC1` (the assistant sentinel would appear in the proposal). **`AC2` is NOT credited** — branch 2 is what the mutant always takes |
| `M22` | `_extract_text` returns `result_message.result or ""` (branch 2 dropped) | `AC2` |
| `M23` | The `analyst_blocks` scenario emits one `TextBlock` instead of two | `AC2`'s join leg — a **fixture** mutation, recorded because `AC2`'s discriminating power lives in the fake, not in the assertion |
| `M24` | `conftest.py`'s pin line deleted | every member of `ARMOR_21` (`SU4`), `AR2`'s presence leg, and — separately — `test_wr6_…`'s first three legs, which rely on the ambient pin (`A-d`) |
| `M25` | `conftest.py`'s pin changed to `SELF_LEARN_BACKEND=cli` (rung 2 instead of rung 1) | `AR2`'s exact-variable leg. Records that the weaker rung would be shadowed by any test setting `SELF_LEARN_BACKEND_ANALYST` and would silently change three other surfaces |
| `M26` | `test_composer.py::_shim_env` edited to pin the backend (the tempting per-file fix) | `SU3` — `DS1`'s sha for `test_composer.py`. The row exists to prove `A-a`'s argument is enforced and not merely asserted |
| `M27` | `AR1`'s tripwire sha literal regenerated from the working tree after an edit to the fixture | `AR1`'s **diff** leg only. Records that a sha alone is not provenance (`FZ-d`, `HY3` of `U-seam`) |
| `M28` | A third transcription of the default added to `provider._model_source` | `FL5`. Records the shape `T-a` forbids |
| `M29` | `fake_claude.py` gains an `import subprocess` | `HY3` |
| `M30` | `test_u_sdka.py`'s `AC` group given a **second** `leg.name ==` branch (the cap is one — `H-c`) | `HY2`'s `AC0` fold — the T2-becomes-two-T1s failure |
| `M31` | An **unauthorized ninth edit**: `test_invocation.py::test_lg7_…` also gains a pin-restoring `setenv` (a change a builder would make by pattern-matching `A-d`) | `AR3` — the base-commit byte comparison over every non-`EDITED` function. Second leg: `test_wr6_…`'s pin-restoring line is replaced by an edit that *also* changes an `assert`, which `AR3`'s AST comparison must catch |
| `M32` | `test_u_sdka.py` gains a line containing a bare `["claude"]` argv literal with no `worker._invoke_claude(` on it | `HY1`, and `test_attrib.py::test_hy1_…` (shipped, un-editable) |
| `M33` | A new test is added that sets rung-2 `SELF_LEARN_BACKEND=sdk`, iterates `SURFACES`, and does not clear rung 1 — `Pin-1`'s casualty shape, one instance wider | `AR5`'s census (the asserted casualty set is no longer the measured singleton). **`SU4` is NOT credited** — a NEW test is in neither `ARMOR_21` nor `EDITED`, which is exactly the hole `AR5` exists to cover |

**`M11` is the mutation this document is most afraid of.** It is the
change a builder makes by reading FW-87's row and doing exactly what it
says. It leaves the cli leg correct, the suite green except for one
criterion, and the sdk leg — *the leg the flip creates* — still losing
lessons to a traceback. `HD2` is the only guard, and a gate that finds
`HD2` weakened or merged into `HD1` should treat the unit as failed.

**`M26` is the second.** It is the "obvious" fix for the two composer
failures and it can only be made green by re-baselining `DS1` — the move
`U-fake` named as the catastrophe. `SU3`'s two halves are the guard.

### 5.1 Criteria with NO mutation row, declared

Silence about coverage is how a mutation plan lies — and the r1 draft told
this exact lie in miniature: its header said **ten**, its list held
**eleven**, its trailing paragraph declared a **twelfth**, and the true
count was **fourteen**. The two it never mentioned were `AR3` and `HY1` —
and `AR3` is precisely the criterion the blocker falsified. Both now carry
rows (`M31`, `M32`), and `AR5` carries `M33`. **Twelve** criteria remain
without one, each declared here; 12 declared + 29 rowed = **41**, which is
§4's count. The arithmetic is stated so it can be checked rather than
trusted.

- **`SU1`, `SU2`, `SU5`, `HY4`, `HY5`** (5) — *instrument criteria*. They
  are measurements (a suite delta, a diff, a pyright delta, a numstat), and
  a code mutation cannot reach a measurement. Their guard is the build
  report, which must carry base **and** head numbers for each.
- **`AC3`, `AC4`, `AC5`, `AC6`** (4) — they assert that **frozen** behavior
  in `analyst.py` (fence stripping, Register R's copy-then-stamp, the
  `script` strip, the X3 roster-sha legs) holds on a **second** backend.
  Mutating that code is outside this unit's file surface, and the units
  that own it (`U-analyst`, `U-composer`, `u-table`) carry their own rows.
  What *this* unit adds is the second leg, and `M19`, `M21`, `M22` are the
  mutations that break the second leg's plumbing — if any of the four
  stays green under all three, the T2 parametrization is not actually
  reaching the sdk backend and the gate should say so.
- **`HD8`** (1) — model identity holds *by construction*:
  `provider.model_for("analyst", …)` **calls** `analyst._model()`.
  Mutating that call is `U-bedrock`'s `MD4`, whose row already exists and
  whose test is unedited here.
- **`DR3`** (1) — the criterion is written as its own control (asserted
  **with and without** the pin), so the mutation is what the criterion
  already performs internally.
- **`AR4`** (1) — every individual byte it pins is already pinned by a
  shipped criterion in `test_invocation.py` / `test_route_cli.py`; its
  value is that it asserts them **together, under the rollback
  environment**, a property no single-line mutation isolates. `M4` is the
  closest approach and is credited there.

---

## 6. Builder decisions, made here rather than left open

- **`D-1`** The default table lives in `contract.py`, not `registry.py`
  (`F-a`). One table, two readers (`T-a`).
- **`D-2`** Rung 5 routes through `_resolve` rather than returning a
  backend directly (`F-b`), so the lazy import, the refusal and the
  fail-closed rule keep one implementation each.
- **`D-3`** FW-87 is fixed at the **transport table**, not at
  `analyst.analyze`'s call site (`E-b`), because `B-6`/`B-7` measured that
  the caller-side fix cannot see the sdk leg's exception class.
- **`D-4`** `analyze` still gains an explicit `os-error` branch, for the
  message rather than for the never-lost property (`E-e`), and `M13`
  records the distinction so a gate credits the right criterion.
- **`D-5`** The T3 armor is kept green by **one `conftest.py` default**,
  not by per-file edits (`A-a`), because `test_composer.py::_shim_env` is
  inside `Freeze-1`'s sha.
- **`D-6`** The suite-wide default is paired with `FL1` (the product
  default, asserted directly) and `AR2` (the pin's positive control), so
  the default can never become the thing under test (`A-b`).
- **`D-7`** The fake CLI is extended **additively** with two scenarios and
  an argv recorder (§3.6), all keyed on env vars that are inert when
  unset, and every pre-existing scenario is sha-pinned (`HY3`).
- **`D-8`** `FAKE_CLAUDE_OUT` mirrors `CLAUDE_SHIM_OUT` (`FK-c`) so a
  single T2 body reads *what the model said* the same way on both legs.
- **`D-9`** Per-leg branching inside `AC` bodies is capped at **one**
  (`AC2`'s single-text-channel collapse), commented, and the cap is a
  criterion. `HD7`'s inversion is the other declared asymmetry but lives
  in the `HD` group and never consumes the cap (`H-c`).
- **`D-10`** The cli leg's `timeout` failure uses a locally-written
  `sleep` shim rather than editing `tests/shims.py` (`H-d`), following
  `test_regime_fixes.py`'s shipped precedent.
- **`D-11`** `analyst.build_argv` keeps emitting the prompt even though
  the sdk leg discards it (§3.8) — changing it would break the cli leg's
  byte-identity for no gain this unit needs.

---

## 7. Out of scope, look-alikes, and residuals

### 7.1 Out-of-scope look-alikes

- **The worker and miner flips.** Wave 3+. This unit changes their table
  entries to `"cli"` explicitly — which is what they resolve to today —
  and `FL6` pins that they still do.
- **`analyst.build_argv`'s prompt-in-argv.** Under the flip the analyst's
  own sessions no longer put the prompt in a process's argv (`HD7`), but
  the *builder* still emits it, and the cli rollback still uses it. The
  argv exposure is not removed from the codebase, only from the default
  path. Recorded as `R-3`.
- **`worker.py`'s `_spawn_window`, `_digest`, `_notify`,
  `_notify_with_ids`; `miner._spawn_run`; every `subprocess` site in
  `gitops.py`, `hosts.py`, `ledger.py`, `ledger_ops.py`, `chezmoi.py`,
  `hook_compiler.py`.** Not model invocations; `U-seam` `WR7`'s written
  exclusion list still governs and is unchanged.

### 7.2 The UI package is untouched

`U-seam` §7.2's no-touch ruling stands. `SU5` enforces it.

### 7.3 Residuals this unit accepts, with owners

- **`R-1` — the analyst's SDK path is not covered by a `--settings`
  witness, because it has none.** `U-seam`'s twin-witness design gives the
  analyst an *absence-asserting* leg (`CN6`), and under the SdkBackend the
  containment is enforced by the charter callback instead. The
  cross-backend agreement between "what the charter denies" and "what the
  CLI's own rule evaluation would deny" is `U-sdk` §8 row 7 / `R-5`, still
  unmeasured. Not reachable for the analyst (empty write sets), so this
  unit does not close it. Owner: a new `FW` row, landing with this build.
- **`R-2` — the four surfaces' log wording still diverges.** `U-seam`
  `R-2`, unchanged. This unit adds a fifth analyst string in the same
  divergent register (`E-c`) rather than unifying, because unification is
  operator-visible and needs its own unit. Owner: `U-seam`'s existing `FW`
  row; this unit adds a note that the analyst now has an `os_error` leg.
- **`R-3` — the cli rollback still puts the record body in `argv`.** The
  flip removes the exposure from the default path; `SELF_LEARN_BACKEND_ANALYST=cli`
  restores it. That is the correct trade for a rollback switch, and it
  means the F3 exposure is *dormant, not deleted*, until `U-cleanup`
  removes the cli path. Owner: a new `FW` row.
- **`R-4` — the burn-in is attended, and this unit ships no automated
  evidence for it.** §11's measurements are operator-run against the real
  ledger and cannot be a test (they need a real model). Owner: the
  operator, per §11's stop rule.
- **`R-5` — the analyst's default backend is delivered by a DEV dependency
  group, and `V-1`'s ruling rests on that.** After the flip, the shipped
  default (`sdk`) is buildable only because `claude-agent-sdk` sits in
  `[dependency-groups] dev` and both entry points resolve it through uv
  (§9 `E11`). `V-1` ruled **Option A (refuse)** on that basis, and the
  refusal is loud and never-lost (`FL7`) — so this is an accepted
  condition, not a defect. It is a residual because the condition is
  **environmental**: it is true of how this host installs, not of the
  code. **Trigger (any one re-opens `V-1`, per `V-1a`):** an entry point
  stops resolving the dev group (`--no-dev`, or a uv default change); the
  CLI starts being installed from a built wheel, where PEP 735
  dependency-groups are absent from the metadata entirely; or a second
  surface flips to `sdk`, widening the failure from "routing stops" to
  "the worker/miner stop". Owner: a new `FW` row carrying the three
  triggers verbatim, landing with this build — `WATCH`, not `BUILD`.
- **`R-6` — a rung-1 env shadow is a LOWER BOUND on a default-rung flip's
  blast radius, and this unit paid for the lesson.** `E3` simulated the
  flip by setting `SELF_LEARN_BACKEND_ANALYST=sdk` ambiently. That is
  exact for every test that never touches the variable — and **wrong in
  both directions** for tests that do: one that clears it mid-test diverges
  from the built state *inside a single test* (`E12`), and one that sets a
  lower rung to the same value is *masked* by the shadow (`E13`). Wave 3+
  flips the worker and miner, whose test surface is far larger than the
  analyst's, and the same instrument will be reached for. **The technique
  is sound as a first pass and must be paired with two census passes**:
  tests that clear the selector, and tests that set rungs 2–4 for the
  flipping surface. Owner: a new `FW` row (`WATCH`), naming the worker and
  miner flips as the trigger.

### 7.4 FW-87's disposition

`14-forward-work-map.md` row `FW-87` moves from **BUILD / Owner: U-sdka**
to **DONE**, with a note recording three things the row did not
anticipate, each measured here:

1. the fix is a **transport-table** change, not a `try/except` in
   `analyze` (`E-b`);
2. the sdk leg carries the **same defect with a different exception
   class** (`CLIConnectionError`, not `OSError` — `B-7`), so the row's
   literal prescription would have left half the hole open (`M11`);
3. it closes `U-seam` residual `R-1` at the same time, and that residual's
   `FW` row is annotated accordingly.

### 7.5 Handed to `03-decisions.md`

- **`S-37`** — backend defaults are **per surface**, and the analyst is
  the first surface whose default is `sdk`. `SELF_LEARN_BACKEND_ANALYST=cli`
  is the operator-facing rollback. Recorded alongside `S-35`'s precedence
  policy.
- **`S-38`** — the invocation seam **never raises**, on any surface, for
  any member of `FAILURE_KINDS`. `U-seam`'s one documented exception
  (`T-c`, the analyst's bare `OSError`) is retired by FW-87.

---

## 8. Verify-at-build ledger

Every row was measured for this spec at `89f8ef7` against
`claude-agent-sdk 0.2.134` / host `claude 2.1.235`, and **every row must be
RE-CONFIRMED at build time** against what the builder actually resolves —
from the installed source or a live probe, never from this document and
never from memory. A row that fails re-confirmation is reported, not
worked around.

| # | Question | Measured | How to re-confirm |
|---|---|---|---|
| 1 | The CLI suite baseline | **1873 collected / 1868 passed / 5 skipped**, 251.51 s | `uv run --project plugins/self-learn/cli pytest plugins/self-learn/cli/tests -q`, rc read unpiped |
| 2 | Is `claude_agent_sdk` importable in the CLI runtime? | **YES — 0.2.134**, from the project venv via `[dependency-groups] dev`. `~/bin/self-learn` and `install.sh` both use `uv run`/`uv sync --project …/cli`, which include `dev` | `uv run --project plugins/self-learn/cli python -c "import claude_agent_sdk, importlib.metadata as m; print(m.version('claude-agent-sdk'))"` |
| 3 | `SHADOW_22`'s membership, and the **two** casualties it cannot show | **22** under the rung-1 shadow — `test_route_cli.py` 12, `test_invocation.py` 7 (3 failed + 4 errored via `analyst_capture`), `test_composer.py` 2, `test_regime_fixes.py` 1. **Plus `LATENT_2`** (`E12`, `E13`): `test_wr6_…`'s final leg and `test_rs2_present_returns_sdkbackend_for_every_surface`. Blast radius **24 events / 23 distinct tests** | §9 `E3`'s command for the 22, re-run at the rebase base; `E12`/`E13`'s reads for the two. **A different count is investigated, not absorbed** — and the shadow is a LOWER BOUND by construction (`A-0`), so a builder who finds only 22 has not finished looking |
| 4 | `DS1`'s `GUARDED` / `REWRITTEN` sets | `GUARDED` = 5 modules; `REWRITTEN` inverse-renames to `{claude_shim, notify_shim, _capture_analyst_prompt}` + 3 `Move-1` names; `_shim_env` is **not** excluded | Read `tests/test_u_fake.py`'s `GUARDED`/`REWRITTEN` literals. **`A-a`'s whole argument rests on this row** |
| 5 | The analyst's SDK option set | `allowed_tools=[]`, `disallowed_tools=[]`, `setting_sources=[]`, `settings=None`, `strict_mcp_config=True`, `mcp_servers={}`, `permission_mode='default'`, `include_partial_messages=False`, `env={}`, `max_turns=30`, `max_budget_usd=None`, `system_prompt={'type':'preset','preset':'claude_code','append':<doctrine>}`; **prompt absent from every value** | Call `options_kwargs` on an analyst `SessionSpec` and print the mapping — `HD6`/`HD7` depend on it |
| 6 | The analyst charter's verdicts | `Write`/`Edit`/`NotebookEdit`/`Bash`/`Task`/`WebFetch` → **Deny**; `Read`/`Grep`/`Glob` → **Allow** | Drive `build_can_use_tool(containment_for("analyst", allowed_tools="Read,Grep,Glob"))` over the nine names — `HD5` leg (i) |
| 7 | The doctor's delta across the flip | **anthropic**: only the `switches` row changes. **bedrock + region, no analyst model**: `rollout` FAIL→4 per-surface INFO rows, new `consistency` FAIL (analyst), `models/analyst` INFO→FAIL, `env/analyst` SKIP→FAIL, **`credentials` SKIP→WARN** (*"no mechanism found (IMDS not probed — see R-4)"*), `switches` detail only; **12 rows unchanged**; exit 1 | `provider.preflight(home)` twice, with and without `SELF_LEARN_BACKEND_ANALYST=sdk`, comparing the **full** (name, surface, verdict, detail) row set — **never a filtered subset**, which is how r1 missed the `credentials` row. `DR1`/`DR2` quote it |
| 8 | `ClaudeSDKError`'s hierarchy | `(ClaudeSDKError, Exception, BaseException, object)` — **not an `OSError`** | `[c.__name__ for c in claude_agent_sdk.ClaudeSDKError.__mro__]`. **`E-a`, `M11` and `HD2` all rest on this row** |
| 9 | What a non-executable `cli_path` raises | `CLIConnectionError("Failed to start Claude Code: [Errno 13] Permission denied: …")`, escaping `text_session` uncaught on the analyst surface | Point `SELF_LEARN_SDK_CLI_PATH` at a `0o644` file and drive `SdkBackend().text_session` on an analyst spec — `B-7`, `HD2`'s injection |
| 10 | Host CLI vs the SDK's bundled CLI | host **2.1.235**, bundled **2.1.226** → the doctor's `sdk` row reports `WARN — versions differ`. Pre-existing and unrelated to this unit; recorded so a builder does not read it as a regression | `claude --version`; `provider.preflight`'s `sdk` row |
| 11 | The operator's live ledger config | `~/.self-learn/config.yaml` **does not exist** → `provider=anthropic` (default) → the flip's doctor delta on the live install is the `switches` row alone | `ls ~/.self-learn/`. Read-only; the ledger is never written by this unit |

---

## 9. What was executed, and against what oracle

Measured in this worktree at base `89f8ef7`. A builder who cannot
reproduce these should stop.

| # | Measurement | Command | Result |
|---|---|---|---|
| `E1` | CLI suite baseline | `uv run --project plugins/self-learn/cli pytest plugins/self-learn/cli/tests -q` | **1868 passed, 5 skipped**, 251.51 s. 1873 collected. |
| `E2` | SDK reachability in the shipped runtime | `uv run --project plugins/self-learn/cli python -c "import claude_agent_sdk"`; `cat ~/bin/self-learn`; `grep 'uv sync' install.sh`; `ls ~/.self-learn/` | Importable, **0.2.134**, from the CLI project venv. Launcher is `exec uv run --project …/cli self-learn "$@"`; installer is `uv sync --project "$P/cli"`. No `config.yaml` in the live ledger. |
| `E3` | **The flip's blast radius, simulated without touching product code** | `SELF_LEARN_BACKEND_ANALYST=sdk uv run --project plugins/self-learn/cli pytest plugins/self-learn/cli/tests -q -p no:randomly --tb=no` | **18 FAILED + 4 ERROR = 22** — `test_route_cli.py` 12, `test_invocation.py` 7, `test_composer.py` 2, `test_regime_fixes.py` 1. Rung 1 shadows every lower rung, so this is what the table's rung 5 does to a test that names no backend. **This defines `SHADOW_22`** — a LOWER BOUND, not the built state's failure set (`A-0`, `E12`, `E13`). |
| `E3a` | The failure signature | same, `--tb=short`, one test | `AssertionError: claude_agent_sdk._find_cli() was called during the test suite` — the `conftest.py` tripwire, for **21 of the 22**. `test_wr6_…` is the exception: it requests `sdk_absent`, so it fails **pre-transport** on `BackendUnavailable` and never reaches `_find_cli`. **No test spawned a real session** either way (`B-2`). |
| `E3b` | What `E3` could **not** see | read of `_clear_backend_env` (`test_invocation.py`) and of `_clear_provider_env` (`test_doctor_invocation.py`, `test_provider.py`) | Both `delenv` the ambient variable, so tests that clear it were measured as unaffected but **will** move under the real table. That set is `FLIP_EDITS` (§3.3 `A-c`): `test_rg1_…`, `test_dc2_…`, `test_dc3_…`. |
| `E4` | The second transcription's rung 5 | read of `provider.resolve_backend_name`; `registry.backend_for("analyst")` and `provider.resolve_backend_name(h,"analyst")` run side by side | Today both answer `cli`/`("cli","default")`. `resolve_backend_name`'s rung 5 is the literal `return "cli", "default"`. With `SELF_LEARN_BACKEND_ANALYST=sdk`, `backend_for` returns a real `self_learn.invocation_sdk.backend.SdkBackend` — **not** a `BackendUnavailable` — because `E2` holds. |
| `E5` | The analyst's SDK option set | `options_kwargs(spec)` on a real analyst `SessionSpec` | §8 row 5's literals. `prompt in options values: False`. |
| `E6` | The analyst charter's verdicts | `build_can_use_tool(containment_for("analyst", allowed_tools="Read,Grep,Glob"))` over nine tool names | §8 row 6. Hatch closed (`default_mode is None` **and** both write sets empty). |
| `E7` | The doctor's delta across the flip, **full row set** | `provider.preflight(home)` with and without `SELF_LEARN_BACKEND_ANALYST=sdk`, under `provider=anthropic` and under `provider=bedrock` + `region: us-east-1`, diffing every (name, surface, verdict, detail) | §8 row 7. Under anthropic, the **only** difference is the `switches` row. Under bedrock: `consistency/analyst` new FAIL, `credentials/-` SKIP→WARN, `env/analyst` SKIP→FAIL, `models/analyst` INFO→FAIL, `rollout/-` FAIL→four per-surface INFO rows, `switches/-` detail; **12 rows unchanged** (`config`, `provider`, `region`, `sdk`, `orphans`, `models/-`, and the three cli surfaces' `models`/`env`). Re-measured for this fold — the r1 probe filtered to five row names and **missed `credentials`**. |
| `E8` | `ClaudeSDKError`'s hierarchy | `[c.__name__ for c in ClaudeSDKError.__mro__]` | `ClaudeSDKError → Exception → BaseException → object`. `CLINotFoundError → CLIConnectionError → ClaudeSDKError`; `ProcessError → ClaudeSDKError`. |
| `E9` | The sdk leg's FW-87 instance | `SELF_LEARN_SDK_CLI_PATH` → a `0o644` file; `SdkBackend().text_session(analyst_spec)` | **RAISED `CLIConnectionError`**, *"Failed to start Claude Code: [Errno 13] Permission denied"*, escaping the seam. |
| `E10` | `Freeze-1`'s reach | read of `test_u_fake.py`'s `GUARDED`/`REWRITTEN`; read of `test_composer.py::_shim_env` | `_shim_env` is a top-level non-`REWRITTEN` function in a `GUARDED` module. Editing it reddens `DS1`. |
| `E11` | **`V-1`'s rationale (c): the dev-group counterfactual** — the one input to §10's ruling that a future packaging change can invalidate | `UV_PROJECT_ENVIRONMENT=<scratch> uv sync --no-dev --project plugins/self-learn/cli -q`, then `<scratch>/bin/python -c "importlib.util.find_spec(...)"` for `claude_agent_sdk` and `ruamel.yaml`. Positive control afterwards: a plain `uv run --project …/cli python -c "import claude_agent_sdk"` on the worktree venv | **Without the dev group: `claude_agent_sdk` ABSENT, `ruamel.yaml` PRESENT** — the un-extra'd install shape `V-1` is about. Worktree venv unchanged (control still imports), so nothing was mutated. **The convenient probe lies:** `uv run --no-dev …` prints `IMPORTABLE`, because `uv run` reuses the already-populated project environment rather than resolving a fresh one — re-confirm with the redirected form only (`V-1b`). |
| `E12` | **Blocker casualty 1** — `test_wr6_…`'s final leg under the BUILT state | read of `test_wr6_…` against `_clear_backend_env` (`test_invocation.py`) and `analyze`'s dispatch | The leg runs after `_clear_backend_env` **and** `delenv("SELF_LEARN_BACKEND")`, so **no** backend env survives — which under the flip is the new default rung `sdk`. With `sdk_absent` active the lazy import fails, and the raised `AnalystError` carries the `BackendUnavailable` install message instead of `"MUTATED NOT FOUND TEXT"`. `wr6` fails in the shadow **and** in the built state, for **different** reasons; r1's `E-g` promise that it "must pass untouched" was measured false. Disposition `A-d`. |
| `E13` | **Blocker casualty 2 + `Pin-1`'s census** — which tests a rung-1 pin can shadow | grep of every **`sdk`-valued** `setenv("SELF_LEARN_BACKEND", "sdk")` site (**28** across 4 files; the unqualified grep returns **36** — doctor 3 / invocation 14 / invocation_sdk 6 / provider 13 — and only the `sdk`-valued subset can shadow-fail), then a read of each unprotected one | `test_doctor_invocation.py` and `test_provider.py` carry an autouse `_clear_provider_env` (immune); `test_invocation.py`'s sites are each preceded by `_clear_backend_env` (immune); `test_invocation_sdk.py` has **no** clearing fixture, and of its six sites five reach only `backend_for("worker", …)`. The sixth, **`test_rs2_present_returns_sdkbackend_for_every_surface`**, loops `invocation.SURFACES` → the pin shadows rung 2 for the analyst → `CliBackend`. **Exactly one casualty.** Disposition `A-e`; criterion `AR5` re-runs this census as a test. |

**Not measured, and therefore not claimed:** that a real Bedrock session
succeeds under the flip; that the charter's matcher agrees with the CLI's
own rule evaluation (`R-1`); that the sdk analyst's *routing quality* is
equal to the cli analyst's — that is §11's burn-in, and it needs a real
model.

---

## 10. Values question — RULED

The flip-default question itself was **already ruled** before this spec was
written (the analyst flips to `sdk` in this unit, per the approved
migration plan's flip order) and is not reopened here. One adjacent
question was routed to the operator in the r1 draft. **It has been ruled.**
This section is the record of the decision and its reasoning, so the next
reader does not reopen it; it is no longer a fork.

### `V-1` — how should the analyst behave when `claude_agent_sdk` is not importable? **RULED: Option A — refuse, one rule for every rung.**

**The ruling:** Option A stands exactly as §3 specs it and `FL7` pins it.
Rung 5 resolves `"sdk"`, the lazy import fails, `backend_for` raises
`BackendUnavailable`, the seam converts it to
`Outcome(failure="unavailable")`, `analyze` raises `AnalystError` carrying
the install command, and `teach --route` **captures the lesson to
`pending/` and exits 4**. No rule changes, no lesson is lost.

**Rationale, as given, recorded in full:**

- **(a) Option B is the silent-inert shape this campaign has eliminated
  three times.** A default-only fallback means the operator believes they
  are running the configured default and is silently running something
  else — and it makes the **default** value behave differently from the
  **same value explicitly configured**: two behaviors for one value. That
  is the defect class, not a tradeoff against it.
- **(b) Option A's failure is loud and never-lost.** Every route →
  capture-to-pending + exit 4 + a refusal naming the install command
  (`FL7`); the doctor names the condition (`DR1`'s `switches` row reports
  `analyst: backend=sdk (default)` while the refusal explains why nothing
  routes); and recovery is one line — `SELF_LEARN_BACKEND_ANALYST=cli`, or
  install the extra.
- **(c) The exposure is edge-of-edge on this host** — see `V-1a` below for
  the measurement and its re-open trigger.
- **(d) Option C contradicts `U-sdk`'s frozen `Dep-2`/`RS7`** and would be
  its own unit, as the r1 draft said.

**The two rejected options, kept for the record.** *Option B* — rung 5
alone falls back to `cli` with a warning while rungs 1–4 keep refusing;
rejected by (a). *Option C* — move `claude-agent-sdk` into the CLI's
runtime `[project] dependencies` so the default is always buildable;
rejected by (d), and out of this unit's file surface regardless.

**Effect on §4: none.** Option A is what the criteria already pin. `FL7` is
the criterion that would have moved under B or C; it does not move.

### `V-1a` — (c) as an environment-specific fact, with its trigger

Rationale (c) is **not** a property of the code — it is a property of *how
this host installs the CLI*, and it is the one input to this ruling that a
future change can invalidate. Recorded so the re-open is mechanical rather
than a rediscovery.

**Measured** (§9 `E11`): `claude-agent-sdk` reaches production through
`[dependency-groups] dev`, and both entry points go through uv, which
resolves that group by default —

- `~/bin/self-learn` is `exec uv run --project "…/cli" self-learn "$@"`;
- `install.sh` runs `uv sync --project "$P/cli"`.

So the SDK is present on **every real install on this host**, and the
un-extra'd case is a hand-rolled minimal install only. The counterfactual
was measured, not assumed: syncing the same project **without** the dev
group into a fresh environment leaves `claude_agent_sdk` **ABSENT** while
`ruamel.yaml` (the sole runtime dependency) stays **PRESENT** — the exact
shape `V-1` is about.

**Re-open trigger (`R-5`'s condition).** This ruling rests on the dev group
being resolved. It must be re-examined if **any** of these becomes true:

1. either entry point stops resolving the dev group — e.g. `install.sh` or
   `~/bin/self-learn` gains `--no-dev`, or uv changes its default;
2. the CLI starts being installed from a **built wheel** (`pip install
   self-learn-cli`, `uv tool install`, a distro package). PEP 735
   dependency-groups are project metadata and are **not** carried in wheel
   metadata at all, so a wheel install can never see the `dev` group — only
   `[project] dependencies` plus whatever extras are named;
3. a second surface flips to `sdk` (Wave 3+), which widens the blast radius
   of the same condition from "routing stops" to "the worker/miner stop".

Under any of those, Option C stops being a packaging preference and becomes
the question again.

**`V-1b` — the measurement gotcha, recorded because it reads as a pass.**
`uv run --no-dev --project …/cli python -c "import claude_agent_sdk"`
prints **IMPORTABLE** on this host. That is **not** evidence the dev group
is unnecessary: `uv run` reuses the project's already-populated
environment, so the probe reads the *previous* sync's contents. The honest
form redirects the environment (`UV_PROJECT_ENVIRONMENT=<scratch> uv sync
--no-dev …`) and inspects the fresh one. A builder or gate re-confirming
`E11` must use the redirected form — the convenient one reports "safe"
when the thing being checked is absent.

---

## 11. §evidence — the attended burn-in (operator-run, not automated)

This section is a **runbook**, not a test. It is the plan's gate on the
flip, and it exists because the one thing the suite cannot check is
whether the SDK-backed analyst *routes as well as* the CLI-backed one —
that needs a real model, and this unit's tripwire guarantees the suite
never gets one.

**Preconditions.** The unit is merged, the suite is green, and
`self-learn doctor invocation` reports `analyst: backend=sdk (default)`
with no `FAIL` row.

### 11.1 Leg 1 — ten clean attended routes

Ten real `self-learn teach … --route` invocations against the **real**
ledger, one per genuine lesson, over normal use. For each, record:

| Field | Where it comes from |
|---|---|
| record id | the `created lrn-… → …` line |
| destination | the `analyst: destination <dest> — <rationale>` line |
| exit code | `echo $?`, read **unpiped** |
| routed or pending | `resolved/` vs `pending/` on disk |
| wall time | `time` on the command |
| cost / turns | the run's event log under the SDK cache dir (`U-sdk` `Ev-1`) |

**Pass:** ten of ten exit `0`, land in `resolved/`, and carry a
destination the operator agrees with. **Any** exit 4, any destination the
operator would have overridden, and the leg stops — record it and report
before continuing.

### 11.2 Leg 2 — the injected timeout lands in pending

**`BI-a` — the scratch ledger must be BOOTSTRAPPED first.** A nonexistent
`SELF_LEARN_HOME` never reaches the analyst at all: `teach`'s write-surface
home gate refuses with **exit 5** (`ledger.EXIT_NO_HOME`) and the line
*"ledger home … does not exist — self-learn cannot see any records … or
bootstrap it with `self-learn init`"*. An un-bootstrapped run therefore
cannot satisfy this leg's exit-4 criterion — it fails for an unrelated
reason that looks like a refusal. `self-learn init` creates the git repo
and the four layout dirs (`skills`, `projects`, `user`, `telemetry`).

**`BI-b` — the flags are the real ones.** `teach`'s scope is
`--skill NAME | --project | --user` (not `--scope`), and a behavior
record's two fields are `--trigger` / `--instruction` (not `--action`).
This leg uses **`--user`**, deliberately: user scope resolves its bucket
from the layout `init` already created, whereas `--skill NAME` additionally
requires a host that registers NAME (`self-learn host add`), which `init`
does not create — an unregistered skill scope fails at bucket resolution,
again for the wrong reason.

```sh
export SELF_LEARN_HOME=/tmp/burnin-ledger
export XDG_CACHE_HOME=/tmp/burnin-xdg
self-learn init                      # BI-a — required; a missing home exits 5

pgrep -f 'claude' | sort > /tmp/burnin-pids-before.txt   # BI-c (sort: see below)

SELF_LEARN_ANALYST_TIMEOUT=1 self-learn teach --user \
  --trigger "a deliberately wedged analyst run" \
  --instruction "burn-in leg 2 — this record must land in pending/, not resolved/" \
  --route
echo "rc=$?"                          # read UNPIPED
```

**Pass:** `rc` is **4**; stderr carries `analyst timed out after 1s` and
`captured to pending`; exactly one record under
`/tmp/burnin-ledger/user/pending/` with `status: pending` and no
`routing:` block; and `BI-c` holds.

**`BI-c` — the orphan check must be scoped, or it indicts the operator's
own session.** A bare `pgrep -f claude` matches **the operator's running
Claude Code processes**, so it can never come back empty and the check
would read as a permanent failure. Compare against the pre-run snapshot
instead, after the kill ladder's window (`U-sdk` `Life-1`):

```sh
pgrep -f 'claude' | sort > /tmp/burnin-pids-after.txt
comm -13 /tmp/burnin-pids-before.txt /tmp/burnin-pids-after.txt
```

**`sort` on BOTH sides is load-bearing, not tidiness.** `comm` requires
**lexically** sorted input; `pgrep` emits **numeric** order, and the two
diverge the moment the pid set spans different digit counts — which it
always does on a real desktop. Verified: with `before = {999, 26000}` and
`after = {999, 1500, 26000}` in pgrep order, `comm` emits
`comm: file 1 is not in sorted order` and exits **1**, so the leg's "prints
nothing" criterion becomes unreadable — it printed something, but the
something is a sort complaint rather than an orphan. With `| sort` on both
sides the same inputs correctly yield exactly `1500`, rc 0. The
`before` capture above carries the same `| sort`.

**Pass:** that `comm` prints nothing **and exits 0** — no `claude` process
that did not exist before the run survives it. A non-zero exit is a broken
check, not a failed one; re-run it rather than reporting an orphan. (In the automated suite the equivalent
check is already scoped to `fake_claude.py`; only the live burn-in has the
operator's own processes in range.)

### 11.3 Leg 3 — trace shape unchanged versus a cli control

**`BI-d` — this leg needs a route that COMPLETES, so it needs a registered
skill.** Legs 1 and 2 do not: leg 1 runs against the real ledger, and leg 2
is expected to fail before routing. Leg 3 compares two *successful*
proposals, so its scratch ledger needs a compile target — a host
registered with `self-learn host add` and a skill under it. Register one
against a throwaway repo before running this leg, and use `--skill <name>`
for both runs; the two runs must use the **same scope and the same record
text**, since `record_sha` is derived from the record body.

```sh
export SELF_LEARN_HOME=/tmp/burnin-ledger
export XDG_CACHE_HOME=/tmp/burnin-xdg
# (host + skill registered per BI-d)

SELF_LEARN_BACKEND_ANALYST=cli self-learn teach --skill <name> \
  --trigger "<one fixed trigger>" --instruction "<one fixed instruction>" --route
SELF_LEARN_BACKEND_ANALYST=sdk self-learn teach --skill <name> \
  --trigger "<the same trigger>"  --instruction "<the same instruction>"  --route
```

Compare the two proposals' **shape**, not their bytes — the model is
non-deterministic and identical prose is not the claim:

- identical **key set** at the top level;
- identical **key set** under `gates`, and the same `gates.outcome` kind;
- `gates.t3.roster_sha` equal to the run's real roster sha on both (or
  `unavailable` on both);
- `routing.by == "analyst"` on both;
- `record_sha` identical on both (it is CLI-stamped from the record body,
  so with identical text a difference is a defect, not model variance);
- `model` identical on both (`HD8`'s claim, observed live).

**Pass:** every bullet holds. A destination that differs between the two
runs is **not** a failure — it is model variance — but it is recorded, and
three or more differing destinations across the burn-in is a signal worth
reporting even though it is not a stop condition.

### 11.4 Stop rule and rollback

At any point: `export SELF_LEARN_BACKEND_ANALYST=cli` restores the
shipped CLI analyst immediately, with no code change and no reinstall
(`FL2`). Persist it in `~/.self-learn/config.yaml` as
`invocation: {backend_analyst: cli}` if the rollback needs to outlive the
shell. Report the leg, the record ids, and the observed behavior.

---

## 12. Revision history

| Rev | Change |
|---|---|
| r1 | Initial draft, written blind against `89f8ef7`. 40 criteria, 30 mutations, 4 residuals, 1 values question routed (§10 `V-1`). The three findings that shaped it, all measured rather than reasoned: `ARMOR_22`'s size and membership (`E3`), `Freeze-1`'s reach over `test_composer.py::_shim_env` (`E10`), and the sdk leg's `CLIConnectionError` flavor of FW-87 (`E9`). |
| r3 | **Delta gate: SOUND — 0 BLOCKER / 0 MAJOR / 2 NOTE.** Both folded, no re-gate. (1) §3.3 `E13`'s setter count qualified as **`sdk`-VALUED** — the unqualified grep returns **36** (doctor 3 / invocation 14 / invocation_sdk 6 / provider 13) and reconciles to 28 only at `value == "sdk"`; reproduced here, and the reconciliation is now written into both §3.3 and §9 `E13` so a builder re-running the grep does not conclude the spec is wrong. `AR5`'s criterion text unaffected. (2) §11.2 `BI-c`'s before/after pid check gains `| sort` on **both** sides — `comm` needs lexical order, `pgrep` emits numeric, and they diverge across digit counts. Reproduced: `before={999,26000}` / `after={999,1500,26000}` in pgrep order makes `comm` emit *"file 1 is not in sorted order"* and exit **1**, so the leg's "prints nothing" criterion is unreadable; sorted, the same inputs yield exactly `1500`, rc 0. The pass criterion now also requires **exit 0**, with a non-zero exit called out as a broken check rather than a failed one. No criterion, mutation, set or bound moved: **41 criteria, 33 mutations, 6 residuals** stand. |
| r2 | **r1 blind gate: NOT SOUND — 1 BLOCKER / 5 MAJOR / 10 NOTE. All folded.** **BLOCKER** (blast-radius accounting; the mechanism was verified strong): two casualties `E3` could not see — `test_wr6_…`'s final leg (`E12`, disposition `A-d`: restore the pin, one line, no assertion changes) and `test_rs2_present_returns_sdkbackend_for_every_surface` (`E13`, disposition `A-e`: clear the pin, one line). The class behind the second is now normative (`Pin-1`) and closed by census (`AR5`). Sets re-derived: `SHADOW_22` (the measurement) / `ARMOR_21` (unedited armor) / `LATENT_2` / `EDITED` (**eight** functions); blast radius **24 events / 23 tests**. **MAJORs**: §5.1 recounted (header said 10, list held 11, prose declared 12, truth was **14** — `AR3` and `HY1` were silently uncovered; both now rowed, 12 declared + 29 rowed = 41); `conftest.py` bound re-derived to ≤10/0 (measured 9/0); `registry.py` bound re-derived to ≤8/≤1 (measured 7/1 quoted, 3/1 compacted), the unachievable "one hunk" clause **dropped** for an AST-range clause; §11.2's `teach` invocation rewritten with the **real** flags (`--user`, `--trigger`, `--instruction`) and an explicit `self-learn init` bootstrap (a missing home exits **5**, never reaching the analyst). **NOTEs**: tripwire is 21-of-22 (`wr6` fails pre-transport); `SU1` restated as a **delta** (absolute counts are neighbor-falsifiable across sibling worktrees); the `credentials` `SKIP`→`WARN` row added to `DR2`/§8 (the r1 probe filtered the row set); `M11` no longer claims `HD1` stays green (it depends on the mutant's spelling — `HD2` is the guard); `H-c`'s pointer corrected to `AC2`/`HD7`, the cap tightened to **one** (`HD7` is `HD`-group and never consumed it) with the `AC` group identified by `^test_ac\d+_`; `E-d`'s `FAILURE_KINDS`-order claim corrected to the shipped branch order (cosmetic — the branches are mutually exclusive); §11's `pgrep` scoped to a before/after diff so it stops indicting the operator's own Claude Code processes; contract.py's slack declared deliberate. New residual `R-6` (the shadow-is-a-lower-bound lesson, owned by the Wave 3+ flips). Counts: **41 criteria** (`AR` 4→5), **33 mutations** (`M31`–`M33`), **6 residuals**. |
| r1a | **§10 `V-1` RULED — Option A (refuse), as drafted.** Bounded edit, dispatched from the coordinator before the blind gate: §10 becomes a ruled disposition carrying the full rationale (a)–(d); rationale (c) is isolated as `V-1a`, an **environment-specific** fact with three named re-open triggers and a new measurement `E11` behind it; `V-1b` records the probe that reads as a pass but is not; residual **`R-5`** (WATCH) carries the triggers forward with an `FW` owner. **No criterion, mutation or design decision changed** — `FL7` already pinned Option A, and the counts in §4/§5 are unmoved. |

Counts live in §4's header and §5's header and are not restated here —
one owner per number.
