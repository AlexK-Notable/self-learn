# U-cleanup — retiring the CLI invocation path

**Status:** draft, round 1 · uncommitted · authored 2026-08-24 against
`self-learn` master `ee0d671`
**Queue:** Lane B, Wave 3 (plan `~/.claude/plans/indexed-kindling-lightning.md`
:219; register `misc/r2-progress.md`)
**Consumed by:** blind spec gate → orchestrator
**Plan definition, verbatim (`:219-220`):** *"**U-cleanup** (delete CLI path +
shims + closures; SDK becomes hard dep; dated decision row)."*

Every number below is a measurement taken at `ee0d671` on 2026-08-24 (r1
measured at `73cd996`; every figure was re-run at `ee0d671` for r2), from
`plugins/self-learn/cli`, under the neutralised environment of §11.0. Code is
located **by symbol first, line second** (plan `:225`). Mutation cells are
marked **measured** or **predicted** — never blended. No code was edited to
produce this document; the one instrument used (§3.3) is a throwaway pytest
plugin outside the repository.

---

## 0. Reading order and precedence

1. **§2 is the spine.** Three findings there change the unit's shape from what
   the plan line implies, and the whole rest of the document follows from
   them. Read §2.2 and §2.3 before anything else.
2. **§3 is the load-bearing section** — the coverage census the user's soak
   waiver puts in the soak's place. It is the go/no-go evidence.
3. §4–§7 are the DECIDE sections (unit shape · what `cli` means after
   deletion · hard dependency · the closures). Each carries the rejected
   alternative.
4. **§8.0 is the reader sweep and it is NORMATIVE.** No symbol may be deleted
   without a row there naming every reader in `src/` and every test that names
   it. r1 asserted one symbol's reader set from memory and was wrong in a way
   that would have reopened `S-48` on the surviving backend; §8.0 exists so
   that cannot recur. Then §8.1–§8.5 are the inventory, §9 the acceptance
   criteria, §10 the mutation plan, §11 the tests and the runbook.
5. §13 is the scope fence, §14 the decision-row text. **§15's four questions
   are all RULED** — a builder starts with no open fork. §9's `[A]`/`[B]` tags
   are normative, because `Q-1` ruled the split.
6. **Every `r1`-attributed retraction in this document is deliberate.** The
   spec records what it got wrong and why, rather than quietly presenting the
   corrected version — the corrections are themselves the evidence that the
   coverage census was audited, and the census is what stands in for the
   waived soak.

Where this spec and `17-invocation-runbook.md` disagree, §3.4 says so
explicitly and the disagreement is a **finding**, not licence to edit canon
silently.

---

## 1. Objective

Delete the `cli` invocation backend so that all four surfaces — `worker`,
`worker-repair`, `miner-reader`, `analyst` — are **sdk-only**, with no second
transport, no second code path, and no environment variable that can select
one. `claude-agent-sdk` becomes a hard dependency of `self-learn-cli`. The
retirement is recorded as a dated row in `03-decisions.md`.

This is the last unit of Lane B's invocation-seam campaign. It is **not**
backend unification: `U-engine` — the shared SDK core extracted from
`ui/src/self_learn_ui/engine/` and `cli/src/self_learn/invocation_sdk/` — is a
separate later unit (§13.3), and U-cleanup must not pre-empt or duplicate it.

**Non-objective:** improving the SDK backend. U-cleanup removes a path; every
line it writes into `invocation_sdk/` beyond the mechanical consequences of
that removal is out of scope.

---

## 2. Current state, verified

### 2.1 The seam today

`plugins/self-learn/cli/src/self_learn/invocation/` — five modules, 810 lines:

| Module | Lines | Role |
|---|---|---|
| `contract.py` | 331 | surfaces, containment, `SessionSpec`, `Outcome`, `Backend`, `BackendUnavailable`, `LOG_TEMPLATES`, `TRANSPORT`, `DEFAULT_BACKEND_FOR_SURFACE` |
| `cli.py` | 149 | `CliBackend` — the only `subprocess` call for a model invocation |
| `fake.py` | 134 | `FakeBackend` + the six `FakeStep` shapes (T1) |
| `registry.py` | 135 | `backend_for`, the five-rung chain, `write_session`/`text_session` |
| `__init__.py` | 61 | re-exports |

`DEFAULT_BACKEND_FOR_SURFACE` (`contract.py:61-66`) is **`"sdk"` for all four
surfaces** already — U-flip landed it on 2026-08-23 after the user cancelled
burn-in. `KNOWN_BACKENDS = ("cli", "sdk")` (`registry.py:31`).

Three fallbacks still name `cli` as the safe answer, and all three are
load-bearing:

- `registry._resolve` (`:47-57`) — an **unknown** value warns and returns
  `_CLI_BACKEND`.
- `registry.backend_for` (`:92-97`) — rung 5 is
  `DEFAULT_BACKEND_FOR_SURFACE.get(surface, "cli")`.
- `provider._fold_backend` (`provider.py:147-148`) — the doctor's re-derived
  name folds an unknown value to `"cli"`.

### 2.2 FINDING — the entire test suite runs on the CLI backend, by an autouse pin

`tests/conftest.py::_worker_test_defaults` is `autouse=True` and sets, for
**every test in the suite**:

```python
monkeypatch.setenv("SELF_LEARN_BACKEND_ANALYST", "cli")   # :106
monkeypatch.setenv("SELF_LEARN_BACKEND_WORKER",  "cli")   # :114
monkeypatch.setenv("SELF_LEARN_BACKEND_MINER",   "cli")   # :115
```

Those three lines are rung 1 of the precedence chain. They mean the shipped
product default (`sdk`, everywhere) is **not** what 2402 of the suite's tests
exercise. The comments at `:100-115` state the rationale honestly — *"the
suite opts OUT of real machinery by default and a test that wants it opts back
IN"* — but the consequence for this unit is severe and is the reason §3.3 is
an empirical measurement rather than a reading exercise:

> **Deleting the CLI backend is not a deletion of `cli.py` and its tests. It
> is the deletion of the transport that 2402 tests are currently pinned to.**

The three lines are themselves part of the deletion inventory (§8), and
removing them is what exposes the true blast radius.

### 2.3 FINDING — the SDK backend consumes the CLI closures; "delete closures" cannot be taken literally

`SessionSpec` carries two CLI-flavoured closures (`contract.py:192-193`):

```python
cli_argv_builder:   Callable[[Path | None], list[str]]
cli_settings_writer: Callable[[], Path] | None = None
```

Three consumers call them, not one:

| Consumer | Site | What it does with the argv |
|---|---|---|
| `CliBackend._run` | `invocation/cli.py:41-44` | spawns it |
| `FakeBackend._step` | `invocation/fake.py:79-82` | records it into `.argvs` |
| **`invocation_sdk.backend.options_kwargs`** | `invocation_sdk/backend.py:167-179` | **builds the whole CLI argv in order to read exactly one flag out of it** |

The SDK line is the one that matters. `options_kwargs` calls the settings
writer, calls the argv builder, then does:

```python
doctrine = _read_argv_flag(argv, "--append-system-prompt")
```

and throws the rest away. Its own comment (`A-5`) says the read set is
**closed at that one flag** — `--model` was removed from it by U-bedrock.

Two consequences:

1. **`cli_argv_builder` is the SDK's doctrine relay — for the ANALYST, and
   only the analyst.** Deleting it without a replacement removes the analyst's
   doctrine from every SDK session — silently, because the absent-flag branch
   renders a valid `{"type": "preset", "preset": "claude_code"}` with no
   append. That is a correctness defect with no exception and no log line.
   *(r1 wrote "and the worker's system-prompt append"; that was **false** and
   is retracted — see §2.3.1.)*
2. **Under `sdk`, `miner.write_reader_settings()` still runs and still writes
   a settings JSON to disk that nothing reads** (`miner.py:546`, wired at
   `:791`; `backend.py:167` calls it, `A-2` then pins `settings=None`). That
   is a live residual today, and this unit is the one that can close it.

#### 2.3.1 Exactly one surface carries a doctrine (r2, measured)

`--append-system-prompt` is emitted by **one** builder in the whole tree:
`analyst.build_argv` (`analyst.py:127`; the module docstring at `:14` states
it). Measured `worker.build_argv(home, settings)`:

```
['claude', '-p', '--model', 'claude-sonnet-5', '--allowedTools',
 'Read,Grep,Glob', '--disallowedTools',
 'Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch', '--settings',
 '<path>', '--strict-mcp-config']
```

No append flag. The worker's SDK `system_prompt` today is therefore the bare
`{"type": "preset", "preset": "claude_code"}`, and **the worker's doctrine
rides the PROMPT**, interpolated at `worker.py:1514`
(`=== ROUTING DOCTRINE ===\n{doctrine}`). `worker.py:1527-1528` says so in the
tree's own voice: *"the doctrine rides `--append-system-prompt` there, so this
prompt never interpolates it a second time"* — "there" being the analyst's
single-record form. `miner.build_reader_argv` likewise emits no append flag.

**Consequence for §7:** the mechanically-correct translation is
`doctrine=None` for **worker, worker-repair and miner-reader**, and
`doctrine=doctrine_text` for the analyst alone. Passing the worker's doctrine
into `SessionSpec.doctrine` would *add* a system prompt that does not exist
today and duplicate text already in the prompt — a silent behaviour change
riding a deletion diff.

§7 decides what replaces the relay.

### 2.4 FINDING — the SDK-side real-process harness already exists

The plan's `fake_claude_cli.py` (`:190`) was **never created under that
name**; `grep -rn fake_claude_cli` over the repository returns nothing. What
U-sdk actually shipped is `tests/fixtures/fake_claude.py` — 488 lines,
executable, driven through `SELF_LEARN_SDK_CLI_PATH` by the `sdk_cli_path`
fixture (`test_invocation_sdk.py:100`).

It is a real process the SDK spawns, and its capability surface is
deliberately modelled on the bash shim's — its own docstring at
`_next_invocation` says so: *"the same `CTR` / `CLAUDE_SHIM_SCRIPT_$N` shape
`shims.py`'s bash worker shim already uses."*

| Capability | bash shim | `fake_claude.py` |
|---|---|---|
| argv capture | per-call, appended (`argv.$N`) | **one file, truncating** (`FAKE_CLAUDE_ARGV_LOG`, `main()`) |
| stdin/prompt capture | per-call (`prompt.$N`) | **absent** |
| invocation counter | `CTR` file | `FAKE_CLAUDE_CALLS` (`_next_invocation`) |
| per-invocation behaviour | `CLAUDE_SHIM_SCRIPT_<n>` (arbitrary bash) | `FAKE_CLAUDE_WRITE_BODY_<n>` (one file body) |
| write a target file | via script | `ok_write` / `ok_write_real`, **gated on the charter's `allow`** |
| exit non-zero | `CLAUDE_SHIM_EXIT_<n>` (any rc) | `hard_exit` (rc 1), `error_result`, `FAKE_CLAUDE_RESULT_IS_ERROR` |
| hang / timeout | `CLAUDE_SHIM_SLEEP_<n>` | `hang`, `hang_sigterm_ignored` |
| malformed output | via script | `malformed_line`, `unknown_message_type`, `no_result` |

14 scenarios (`SCENARIOS`, `fake_claude.py:404-419`). The three gaps —
per-call argv, prompt capture, arbitrary multi-file side effects — are the
concrete replacement obligations §3.5 enumerates.

---

## 3. Coverage — what exists, what deletion removes

**This section replaces the soak.** The plan's U-cleanup preconditions
(`:240`) opened with *"14 consecutive all-sdk days"*. The user waived it on
2026-08-24 (register `:3237-3248`), verbatim: *"As long as we have decent test
coverage, then skip the soak. 2 weeks is crazy-town."* The bar is therefore
**measured test coverage**, and §3.2–§3.5 are that measurement.

### 3.1 Baseline, measured

| Measurement | Command | Result |
|---|---|---|
| Collected | `uv run pytest --collect-only --color=no -q` | **2402 tests**, rc 0, 0.56 s |
| Green baseline | `uv run pytest --color=no -q` | **2394 passed, 8 skipped, 0 failed**, rc 0, **358.73 s** |
| Fixture census | `uv run pytest --fixtures-per-test --color=no -q` | tail `no tests ran in 0.98 s` — the **correct** tail; the wrong-cwd form prints `39 errors` (U-fake `CS-b`), so this run is a valid census |

### 3.2 SDK-path coverage that exists today, measured

| Suite | Tests | What it covers |
|---|---|---|
| `tests/test_invocation_sdk.py` | **83** | the SDK backend end-to-end. Prefix counts **measured off the collected node ids** (r2 — r1's hand-written breakdown summed to 73 and is retracted): `CH` charter/`can_use_tool` **18** · `OP` options assembly **17** · `KL` kill ladder **11** (10 numbered + `kl_major1`) · `OU` outcome mapping **8** · `RS` registry/lazy-import/packaging **7** · `PL` package-shape **6** · `EV` tool-events **6** · `SY` sync bridge **5** · `HG` hygiene **4** · `SU` **1**. Sum = 83 ✓ |
| `tests/test_u_sdka.py` | **49** (11 `[cli]` / 11 `[sdk]` pairs + 27 unparametrized) | the analyst flip: default resolution, precedence rungs, unknown-value warnings, hardening under sdk |
| `tests/test_worker_contract.py` | **64** (18 `[cli]` / 18 `[sdk]` pairs + 28) | worker + repair T2 contract: containment, stdout-never-parsed, repair round, timeouts, failure legs, hatch, prompt delivery, events, precedence |
| `tests/test_reader_contract.py` | **55** (14 `[cli]` / 14 `[sdk]` pairs + 27) | miner-reader T2 contract: strict-mcp, containment, artifact round-trip, timeout/kill, spool sweep, precedence, hygiene |
| `tests/test_provider.py` | **40** | provider/backend resolution, Bedrock env, doctor rows |
| `tests/test_doctor_invocation.py` | **16** | the doctor's invocation rows |
| `tests/test_u_fake.py` | **17** | U-fake's own criteria (fixture shapes, `shims.py`/`backends.py` surfaces, the T1 conversions, the T3 body-identity guard) |
| `tests/test_invocation.py` | **65** | U-seam's seam suite (contract, precedence, twin-witness, argv identity, log templates, `BackendUnavailable`) |

**T2, the backend-interchangeability proof:** **43 `[cli]` legs and 43 `[sdk]`
legs**, suite-wide, in exactly three files (worker_contract 18, reader_contract
14, u_sdka 11). *The plan `:193` said "16 contract tests" — that number is
stale by a factor of 2.7; the built figure is 43 pairs.*

**This table silently corrects the register, and the correction is recorded
here rather than left implicit** (r2): `misc/r2-progress.md:3241` — the waiver
line itself — cites *"test_invocation_sdk 80, test_u_sdka 38, test_u_fake 17"*.
Measured at `ee0d671`: **83 / 49 / 17**. The waiver row is the register's own
statement of what the coverage bar rests on, so its numbers being 3 and 11 low
matters; §13.3 dispositions the line.

**Real-process SDK driving:** every `test_invocation_sdk.py` session runs the
real `claude-agent-sdk` transport against `tests/fixtures/fake_claude.py`
(§2.4), with a session-scoped `autouse` tripwire in `conftest.py`
(`_no_real_sdk_spawn_tripwire`) that hard-fails if `_find_cli()` is ever
reached — so "SDK coverage" here means a real subprocess and a real control
protocol, not a mock.

**Live evidence, one run.** The first production SDK miner-reader invocation
ran 2026-08-24 19:20:47–19:24:54 PDT: `ok — 7 landed, 0 folded, 0
recurrence(s), 1 fire(s)`, 4 m 07 s wall, 5.4 s CPU, 586 MB peak, **0 orphan
processes**, volume in band with the prior CLI runs (8, 8). The reader ran as
the SDK-bundled `claude` with `--setting-sources=` empty, `--strict-mcp-config`
and `--disallowedTools Bash,Edit,NotebookEdit,Task,WebFetch,WebSearch,Read,Grep,Glob`.
**This is one run.** It is evidence that the SDK miner works in production at
all; it is not a sample, not a distribution, and it cannot stand in for the
suite. It is cited because the register cites it, and it is bounded here so a
later reader cannot inflate it.

### 3.3 What the deletion removes — the blast radius, measured

**Instrument.** A throwaway pytest plugin written to a scratch directory
outside the repository (never committed, never imported by the suite):

```python
@pytest.fixture(autouse=True)
def _unpin_backend(_worker_test_defaults, monkeypatch):
    for var in ("SELF_LEARN_BACKEND", "SELF_LEARN_BACKEND_ANALYST",
                "SELF_LEARN_BACKEND_WORKER", "SELF_LEARN_BACKEND_MINER"):
        monkeypatch.delenv(var, raising=False)
```

It requests `_worker_test_defaults`, so it runs **after** conftest's pin and
after any test-level `setenv` at the same scope. That makes `cli`
**unselectable at every rung** — which is precisely the post-deletion world,
not merely "the pin removed". Run with `PYTHONPATH=<scratch> … -p
unpin_backend --tb=no`, rc captured unpiped.

| Batch | Files | Collected | Failed | Errors | Passed | Wall |
|---|---|---|---|---|---|---|
| **A** | `test_worker` `test_repair` `test_attrib` `test_route_cli` `test_invocation` | 256 | **118** | 6 | 132 | 13.1 s |
| **B** | `test_worker_contract` `test_reader_contract` `test_composer` `test_miner` `test_u_fake` `test_u_sdka` `test_invocation_sdk` `test_provider` `test_doctor_invocation` | **457** | **27** | 1 | 427 | 152.2 s |
| **C** | everything else (14 files ignored) | 1689 | **8** | 0 | 1675 | 344.3 s |
| **Total** | | **2402** | **153** | **7** | **2234** | |

*(r2 arithmetic correction: batch B collects **457**, not 456 — 27 F + 427 P +
2 skipped + 1 E. The totals row now reconciles to the baseline exactly:
256 + 457 + 1689 = **2402** collected, and 132 + 427 + 1675 = **2234** passed
with 8 skipped. r1 printed 2401 and 3234; both were wrong, and §10 `A1`
repeated the 3234. Re-measured at `ee0d671`, all three batches reproduce cell
for cell.)*

> **160 tests — 6.7 % of the suite — stop passing the moment `cli` cannot be
> selected.** A whole-suite unpinned run was attempted first and reached ~89 %
> before hitting the 400 s tool bound; the three-batch decomposition above is
> the complete measurement.
>
> **160 node ids = 156 distinct test functions.** Four are parametrized pairs
> where both the `[cli]` and `[sdk]` leg fail. Every count in this document is
> node ids unless it says "distinct functions"; §8.4's reconciliation is in
> node ids, because that is what a collected count is.

Per module:

| Module | impacted | of collected |
|---|---|---|
| `test_repair.py` | 44 | 55 |
| `test_attrib.py` | 33 | 47 |
| `test_worker.py` | 23 | 53 |
| `test_reader_contract.py` | 16 | 55 |
| `test_route_cli.py` | 12 | 36 |
| `test_invocation.py` | 12 (6 F + 6 E) | 65 |
| `test_worker_contract.py` | 4 | 64 |
| `test_composer.py` | 4 | 31 |
| `test_hosting_fixes.py` | 4 | — |
| `test_miner.py` | 2 | 102 |
| `test_u_sdka.py` | 2 (1 F + 1 E) | 49 |
| `test_batch_fixes.py`, `test_lock_invariant.py`, `test_regime_fixes.py`, `test_round3_fixes.py` | 1 each | — |

**The shim census.** 142 distinct tests request a bash `claude`-shim fixture
(no test requests two — 118 + 17 + 7 = 142 exactly):

| Fixture | Defined at | Distinct tests | Modules |
|---|---|---|---|
| `claude_cli_shim_worker` | `test_worker.py:125` | **118** | repair 45, attrib 32, worker 32, worker_contract 5, invocation_sdk 2, u_fake 1, u_sdka 1 |
| `claude_cli_shim_analyst` | `test_route_cli.py:146` | **17** | route_cli 16, u_fake 1 |
| `claude_shim` (the U-fake `Compat-1` alias) | `test_repair.py:73` | **7** | invocation 7 |

> **The plan's "88 bash-shim tests" (`:195`) is wrong and always was.** U-fake
> measured **132** requests at `c2669a9` (§9 of that spec); the figure at
> `ee0d671` is **142**. A go/no-go that budgets for 88 is budgeting for 62 %
> of the real thing.

### 3.4 What T3 uniquely guarded — the answer

`17-invocation-runbook.md` §5.6 condition 3 describes T3 as *"the existing
bash-shim suite, frozen — byte-identity regression armor for the `cli` path"*,
and reads "T3 caught nothing" as *"the `cli` path never regressed while nobody
was using it."*

**That description is true of T3's purpose and false of T3's content.**

**Method (stated exactly, because r1's figures were not reproducible from
r1's own wording).** AST-walk every `test_*` function in the five T3-core
files; keep those whose **own signature** names `claude_shim`,
`claude_cli_shim_worker` or `claude_cli_shim_analyst`; regex the source
segment for
`argv|--allowedTools|--settings|--append-system-prompt|--strict-mcp-config|settings_path|write_settings_file|permissions|build_argv`;
then **read every matching line** and discard hits whose subject is not the
`claude` argv.

| File | shim-signature tests | regex hits | genuine `claude`-argv/settings tests |
|---|---|---|---|
| `test_worker.py` | 32 | 7 | **1** — `test_run_argv_pins` |
| `test_repair.py` | 45 | 3 | **3** — `d5_the_narrowed_repair_scope_is_real`, `f2_both_invocations_share_one_argv_builder`, `f5_shim_observes_and_drives_two_invocations` |
| `test_attrib.py` | 32 | 2 | **2** — `sw1_…reverts_the_namespace_end_to_end`, `sw2_…reverts_enforcement_and_only_that` |
| `test_route_cli.py` | 10 (+6 requesting indirectly via `env`) | 1 | **1** — `teach_route_analyst_routes_to_shim_destination` |
| `test_invocation.py` | 6 (+1 reaching `claude_shim` indirectly via the `repair_run` fixture, `:274`) | 5 | **5** — `cn8`, `cn10`, `av1`, `av2`, `av4` |
| **Total** | **125** | **18** | **12** |

**Two r1 errors corrected.** (i) The denominators are **125 / 18**, not
126 / 17: r1's helper counted `repair_run` as a shim-fixture signature, which
moved `test_invocation.py` from 6 to 7 — the same indirect-request distinction
r1 *did* draw for `test_route_cli.py` and failed to draw here. (ii) The regex
**over-matches**: of `test_worker.py`'s 7 hits, **6 are `notify_shim` /
`notify_send_log` argv assertions** — `self-learn-notify` and `notify-send`
argv, nothing to do with `claude`. Only `test_run_argv_pins` reads
`claude_cli_shim_worker["log"]`.

**So the true figure is 12 of 125 — ≈ 90 % of the T3 armor is not about the
CLI path**, a *stronger* result than r1's ≈ 87 %, reached by a method that
reproduces. Those 113 tests are about worker staging, repair rounds, producer
attribution and route-to-destination semantics; the bash shim is merely the
*driver* that makes a model turn happen. Their subject survives the deletion
intact.

So the answer to "what did T3 uniquely guard that needs an sdk-side
replacement before deletion" splits cleanly in two:

**(a) Genuinely CLI-path properties — 17 tests, plus the CLI-only tests
outside T3.** Every one of them guards a mechanism that *ceases to exist* with
the code:

| Property | Guarded by | Post-deletion status |
|---|---|---|
| argv shape / flag set reaching the process | `test_invocation.py::test_av2_worker_argv_shape`, `test_cn8_*`, `test_ss1_*`; `test_worker_contract.py::test_ws3_cli_witness_b_is_stage_permission_rules` | **moot** — there is no argv. Replaced by `options_kwargs` (`OP1`–`OP17`, 17 tests) |
| settings-file rendering + `defaultMode` | `test_worker_contract.py::test_ha1_cli_hatch_open_omits_default_mode` | **moot** — `settings=None` under sdk (`A-2`); charter is the only authority (`CH1`–`CH13`, 13 tests) |
| prompt on stdin, never argv, >128 KiB | `test_worker_contract.py::test_bg2_cli_prompt_delivered_intact_on_stdin`, `test_reader_contract.py::test_rc7_[cli]` | **replaced** — `test_bg3_sdk_prompt_delivered_intact`, `test_rc7_[sdk]` |
| `killpg` on miner timeout | `test_reader_contract.py::test_to4_cli_kill_path_killpg_then_wait`, `test_to5_swallows_processlookuperror_and_permissionerror_separately` | **moot** — replaced by the SDK kill ladder (`test_to6_kill_ladder_three_rungs_and_pgid_discrimination`, `test_to7_pid_sidecar_present_during_absent_after`, `KL1`–`KL8`) |
| `FileNotFoundError` → `not-found` leg | `CliBackend._outcome_not_found` legs across `test_invocation.py` | **NOT moot — r1 said "moot" and was wrong.** `backend.py:228` sets `"cli_path": os.environ.get("SELF_LEARN_SDK_CLI_PATH") or None`; the pin exists **only in tests** (the `sdk_cli_path` fixture), so **in production `cli_path` is `None` and the SDK does its own bundled/PATH lookup**. `backend.py:465-469` catches `CLINotFoundError` → `failure="not-found"`. **Already guarded sdk-side:** `test_ou1_every_row_of_the_map_1_table` (`:1473`) points `SELF_LEARN_SDK_CLI_PATH` at `/nonexistent/claude-fake` and asserts `(False, None, "", "", "not-found")` at `:1493-1494` |
| real exit-code propagation | `CLAUDE_SHIM_EXIT` (15 refs, 7 files) | **moot** — `test_ou2_rc_synthetic_one_and_none_by_failure_kind`: rc is synthetic under sdk |
| log-line byte identity across backends — *the test r1 named* | **`test_invocation_sdk.py::test_ou3_…_byte_identical_to_clibackend_…`** | **misidentified.** Its name promises a comparison; its body contains none (`sdk_logs` captured and never asserted; the two model-driven legs exercise different template rows). It is not the oracle — **§3.4.1 names the one that is.** What dies here is a single byte-pin on `LOG_TEMPLATES["worker"].not_found`, and the row above shows `not-found` is still reachable under the SDK, so it is re-asserted there (`T-SDK-NOT-FOUND-WORDING`) |
| **cross-backend renderer agreement — THE one property genuinely lost** | **`test_worker_contract.py::test_fl2_byte_identity_and_provenance[sdk]`** (`:1394`, `:1398`) — it drives a fresh CLI pass from inside the `sdk` leg and asserts `cli_line == sdk_line` on **timeout**, **not-found** and **unavailable** | **LOST — no replacement is possible in kind**, because the property is *two renderers agreeing* and after the deletion there is one. **Replaced in coverage by `RO-6`/`CV3`:** a byte-pin over **every** row of all three `LOG_TEMPLATES` sets, **captured in phase A while the CLI pass still runs**, so the frozen values are the ones this comparison last verified rather than values re-typed afterwards — broader than the three kinds the comparison covered, and independent of a second transport existing. **See §3.4.1 for the line-by-line read and §8.4b for the test's disposition.** |

**`test_ou3` is not an oracle — but the suite has one, and it is what the
deletion actually costs.** This finding took two rounds to land, and both
halves are recorded because a reader who sees only the second would not know
which claim to trust:

- **r2 (correct):** `test_ou3`'s name promises a cross-backend byte-identity
  comparison and its body contains none. The line-by-line read is below.
- **r3 (correct, and the one that governs):** concluding from that "there is
  no differential oracle" was itself wrong.
  **`test_worker_contract.py::test_fl2_byte_identity_and_provenance[sdk]`
  (`:1394`, `:1398`) is one** — and it is the single property in §3.4(a) with
  no in-kind replacement after the deletion. **§3.4.1 is the read; the table
  row above is its entry; `RO-6`/`CV3` is its replacement in coverage.**

`test_ou3` read line by line at `test_invocation_sdk.py:1560-1602`:

1. `sdk_logs = []`; an SDK session runs `prompt="error_result"` — the
   **`exited`** template row — and populates `sdk_logs` (`:1566-1568`).
   **`sdk_logs` is never asserted anywhere in the function.**
2. `CliBackend` is imported at `:1564`, `subprocess.run` is monkeypatched to
   raise `FileNotFoundError`, a `CliBackend().write_session` runs, and the
   assertion is against a **hardcoded literal**:
   `assert cli_logs and cli_logs[0] == "run: claude CLI not found on PATH"`
   (`:1585`) — the **`not_found`** template row.
3. `LOG_TEMPLATES["worker"]` is `setitem`-replaced with a mutated
   `LogTemplates(exited="MUTATED EXIT {rc} {detail}")`, a second SDK session
   runs, and the emitted line is asserted to change (`:1587-1602`). This is
   the **table-authority leg**, and it is a live mutation test.

The two model-driven legs exercise **different template rows** and are never
compared. So what actually dies with `CliBackend` is **one byte-pin on
`LOG_TEMPLATES["worker"].not_found`**, asserted through the CLI transport.

**And even that is recoverable on the surviving backend**, because of the row
above: `not-found` is still reachable under the SDK
(`CLINotFoundError` → `failure="not-found"`, `backend.py:465-469`), and
`test_ou1` already drives it (`:1473`, `:1493-1494`). The byte-pin can simply
be re-asserted through the SDK's own not-found leg.

#### 3.4.1 The differential oracle DOES exist — it is `test_fl2[sdk]` (r3)

r2 concluded "there is no differential oracle" from reading `test_ou3`. That
conclusion was **right about `test_ou3` and wrong about the suite.** Measured
r3 at `test_worker_contract.py:1355-1398`:

```python
if backend.param == "sdk":
    # byte-identity, scoped to timeout (first line) / not-found / unavailable.
    other = _drive_fl2_lines("cli", tmp_path, marker_templates)      # :1394
    for kind in ("timeout", "not-found", "unavailable"):
        assert other[kind][0] == own[kind][0], (kind, ...)            # :1395-1398
```

`test_fl2_byte_identity_and_provenance[sdk]` drives a **fresh CLI pass from
inside the `[sdk]` param leg** and asserts the two backends' rendered log lines
are byte-identical on three failure kinds. The test says so itself, in the `#` comment block
running `:1356-1362` (a comment, not a docstring — `def` is at `:1355` and the
function has no docstring): *"the byte-identity clause needs BOTH sides, so it
rides the `sdk` param leg, which additionally drives a fresh `cli` pass via
`_drive_fl2_lines` to compare against."* **That is a genuine cross-backend oracle, and it dies with
the CLI path.**

Three consequences:

1. **§3.4's headline stands but its evidence changes.** The retraction of
   `test_ou3` was correct and stays; a second, real oracle was simply never
   looked for. `RO-6`'s `LOG_TEMPLATES` byte-pin is now replacing something
   that exists, which makes it *more* load-bearing, not less.
2. **`test_fl2[sdk]` is the worked case for `BLOCKER-B`** — see §8.0a and
   §8.4b's disposition.
3. **What survives the deletion in that test:** the provenance-and-shape
   assertions at `:1377-1390` (every `FAILURE_KINDS` cell emits a
   `MARKER-`-tagged line under `dataclasses.replace`d templates), which are
   per-param and hold on `sdk` alone. **What dies:** the `:1392-1398`
   comparison block, and only it.

**Net: the deletion loses exactly one real assertion — `test_fl2[sdk]`'s
three-kind byte-identity comparison (`:1394`, `:1398`) — and `CV3`/`RO-6`
replace it with a byte-pin over every row of all three `LOG_TEMPLATES` sets,
captured in phase A while the CLI pass still runs.** `test_ou3`'s
table-authority leg survives untouched and is unaffected either way. **§14's
`S-49` row states this loss explicitly**, naming `test_fl2[sdk]` and its
replacement — the permanent record claims a lost oracle because there was one,
and identifies which test it was.

**(b) Behaviour that survives and therefore must MIGRATE, not be deleted —
≈ 109 tests.** `test_repair.py` (44 impacted), `test_attrib.py` (33),
`test_worker.py` (23), `test_route_cli.py` (12). Deleting them to delete a
transport would trade a 149-line module for the worker's repair-round,
attribution and routing regression coverage. **That trade is not on the
table** (orchestrator ruling `Q-2`, 2026-08-24: migrate, never delete), and
refusing it is what makes §4's shape decision necessary.

**(c) A third class r1 missed entirely — tests that name a deleted symbol but
never fail under the §3.3 instrument.** They pass today with `cli`
unselectable because they never *drive* a backend: they read source, assert on
`__all__`, sha a function body, or pin a settings path. Deleting the symbol
breaks them at import or assertion time, not at dispatch time, so the
blast-radius instrument is blind to them by construction. **Measured: 66
distinct test functions** outside the 160. §8.4 partitions them.

### 3.5 Replacement obligations before any deletion lands

Derived from §2.4's capability table and §3.4(b). Each is a precondition on
the migration, not a nice-to-have:

| # | Obligation | Why | Where |
|---|---|---|---|
| **RO-1** | `fake_claude.py` gains **per-invocation** argv capture (`FAKE_CLAUDE_ARGV_LOG` currently opens `"w"` and truncates — `main()`) | the repair-round tests read `argv(1)` and `argv(2)` | `tests/fixtures/fake_claude.py` |
| **RO-2** | `fake_claude.py` gains prompt capture (`FAKE_CLAUDE_PROMPT_LOG`, per invocation) | the bash shim's `prompt.$N`; T1's `FakeBackend.prompts` covers the seam but not the wire | same |
| **RO-3** | `fake_claude.py` gains a multi-target write scenario, or `ok_write_real` accepts a target **list** | `CLAUDE_SHIM_SCRIPT` is used at **180 sites across 9 files**, and its dominant use is writing several proposal files in one turn | same |
| **RO-4** | a per-invocation exit/`is_error` selector (`FAKE_CLAUDE_RESULT_IS_ERROR_<n>`) | `CLAUDE_SHIM_EXIT_<n>` (15 refs) drives round-2-fails-round-1-succeeds tests in `test_repair.py` | same |
| **RO-5** | an sdk-side analyst **failure-leg** test in `test_composer.py` | closes U-fake `R-5` (§13.2) — no composer test exercises an analyst failure path on either backend | `tests/test_composer.py` |
| **RO-6** | `LOG_TEMPLATES` byte-pin over **every row of all three template sets**, captured **while `CliBackend` still exists** | replaces `test_ou3`'s one dying byte-pin (`worker.not_found`, §3.4) with a total one, and freezes the wording at its last CLI-verified value rather than re-typing it from memory | `tests/test_invocation_sdk.py` |
| **RO-7** | an sdk-side `test_rc7` replacement that spies the wire, not the spec object | `BLOCKER-5`/§9 `CV2`: `test_rc7`'s `[sdk]` leg reads `cli_argv_builder`/`cli_settings_writer` and collapses to a tautology without them (§8.4a) | `tests/test_reader_contract.py` |

RO-1…RO-4 are additive to a test fixture; none touches product code. RO-6 and
RO-7 are **[A]** and must land while `CliBackend` still exists — RO-6 because
its whole point is capturing the pre-deletion value, RO-7 because the
`[cli]` leg is its own construction oracle.

### 3.6 The bar, stated so a gate can check it

The soak is waived; the coverage bar that replaces it is:

> **CB-1.** After the deletion, `uv run pytest` from `plugins/self-learn/cli`
> under §11.0's environment is **green with a collected count no lower than
> `2402 − (the enumerated deletion set of §8.4)`**, and every number in §8.4
> is named individually, not aggregated.
>
> **CB-2.** Every one of the four surfaces has at least one test that drives a
> **real SDK subprocess** (`fake_claude.py`) end-to-end from its real call
> site — not a hand-built `SessionSpec`. Today: worker ✅ (`WS6`, `RP4`,
> `CH10`), miner-reader ✅ (`CT4`, `RC1`–`RC7[sdk]`), analyst ✅
> (`test_u_sdka.py`), worker-repair ✅ (`RP4`, `CH10` third leg).
>
> **CB-3.** The 43 `[sdk]` T2 legs all survive the parametrization collapse as
> unparametrized tests with their assertions unchanged — a `[cli]` leg may be
> deleted, an `[sdk]` leg may not be weakened.
>
> **CB-4.** `test_ou3` (§3.4) keeps its surviving table-authority leg intact
> and replaces its dead differential leg with the frozen `LOG_TEMPLATES`
> byte-pin; both still fail under §10 `M-9`.

---

## 4. DECIDE — the unit's shape

**Ruled here as a recommendation; §15 `Q-1` routes the fork upward because it
changes the wave plan, which is the orchestrator's to change.**

§3.3 measured 160 impacted tests and §3.4 showed ≈ 109 of them are behaviour
tests that must be migrated rather than deleted. A single unit that migrates
109 tests *and* deletes the path has one property that should disqualify it:
**while the migration is in flight the suite is red, and the only oracle that
could tell a builder whether a migrated test still asserts the same thing —
the CLI path itself — is the thing being deleted in the same diff.**

**RULED (orchestrator, 2026-08-24): SPLIT into two units, in this order.**
*This section is preserved as the reasoning behind the ruling; see §15 `Q-1`
for the ruling itself and for which of r1's arguments survived the r2 fold.*

| | **U-cleanup-A — migrate the drivers** | **U-cleanup-B — delete the path** |
|---|---|---|
| Deletes | **TEST legs and direct CLI drives only — zero product code.** *(r1/r2 said "nothing"; measured, that is impossible: `AG1` cannot be green while 51 tests still reach `CliBackend._run`. Orchestrator ruling, 2026-08-24 — option 1.)* A collapses the 43 `[cli]` legs (`CV2`), rewrites `test_ou3` to `T-SDK-NOT-FOUND-WORDING`, rewrites the 5 non-parametrized direct drives, and re-bases `test_fl2[sdk]`'s injected CLI pass — so nothing in A's suite reaches `CliBackend` **by any route**. `invocation/cli.py` is untouched and still shipping. | §8's full inventory — product code and the CLI module itself |
| Adds | RO-1…RO-6; sdk-side driver fixtures; migrates the ≈ 109 behaviour tests | the `cli`-selection refusal (§5), the hard dep (§6), the decision row |
| Green gate | **`AG1`–`AG4` (§9)** — full suite green with conftest's three pins deleted **and a session-scoped tripwire making `CliBackend._run` raise on entry**, plus `AG2`'s negative control and `AG4`'s published post-migration count. *(r1 stated this only as prose — "unreferenced by any test" — which is a grep, not a runtime fact, and was not among the numbered criteria.)* | full suite green, collected count = **`AG4`'s anchor** minus §8.4's itemisation |
| Oracle available | **yes** — a migrated test can be run on both backends and compared | not needed; A already proved equivalence |
| Diff shape | additive + edits, ~zero deletions of product code | deletions only |
| Risk if it goes wrong | suite red, nothing shipped, `cli` still works | one revert |

The decisive property is the middle row. U-cleanup-A's completion criterion —
*the suite is green on `sdk` with the CLI backend present but unreached* — is
exactly the evidence the waived soak was supposed to produce, and it is
produced by a suite in minutes rather than by a calendar in fourteen days.
U-cleanup-B then becomes a pure-deletion diff whose gate is arithmetic.

**Rejected: one unit.** It is what the plan line says, and it is cheaper in
orchestration overhead. It is rejected because the 109-test migration and the
deletion have different failure modes, different gates, and — critically —
because performing them in one diff destroys the differential oracle at the
moment it is most needed. If the orchestrator overrules this, §9's criteria
still apply as written; only the merge boundary moves.

**Everything below specifies the full scope.** Criteria are tagged **[A]** or
**[B]** so the split can be applied mechanically, and the tags are inert if
the unit stays whole.

---

## 5. DECIDE — what a `cli` selection does after deletion

**Ruled: a NAMED HARD REFUSAL, at every rung, that never raises out of the
seam.**

`KNOWN_BACKENDS` becomes `("sdk",)`. A `cli` value at any of rungs 1–4 is
**not** folded into the generic unknown-value path, because that path's whole
design is *"unknown means cli"* (`registry._resolve`'s `R-c` docstring) and
that sentence stops being sayable. Instead `cli` gets its own message:

```
the "cli" invocation backend was removed in <VERSION> — every surface now
runs on the Agent SDK. Unset SELF_LEARN_BACKEND[_<SELECTOR>], or remove
invocation.backend[_<surface>] from <ledger-home>/config.yaml.
```

Mechanism: `_resolve` (`registry.py:42`) raises
`BackendUnavailable(_CLI_RETIRED_MESSAGE)`. `registry._dispatch`
(`def` at `:100`; `except BackendUnavailable` at `:116`) already catches it,
logs through `LOG_TEMPLATES[surface].unavailable`, and returns
`Outcome(ok=False, failure="unavailable")` — so the refusal reaches every
surface as an ordinary, never-raising, per-surface failure with a log line, on
all four `LOG_TEMPLATES` rows, with **zero call-site edits**. *(Gate-verified:
`backend_for` is called from exactly one place in `src` — `registry.py:115`,
inside `_dispatch`'s `try`; all three product call sites — `analyst.py:256`,
`miner.py:794`, `worker.py:3155` — pass no `backend=`.)* `S-48`'s "the seam
never raises" survives this mechanism untouched; §8.2 is what must not break
it (see `BLOCKER-1` there).

**Rejected: ignore and run `sdk` anyway** (warn once, proceed). Rejected
because an operator typing `export SELF_LEARN_BACKEND=cli` is attempting a
rollback. Silently running the thing they asked to stop running is the exact
failure shape `known-issues`-style incidents are made of, and the runbook
(§6) currently *promises* that variable as the rollback. Refusing loudly is
the only honest answer once the promise cannot be kept.

**Rejected: fold `cli` into the unknown-value warning.** It produces
`must be one of sdk; got 'cli' — using "sdk"`, which tells an operator their
rollback was ignored, in the tone of a typo correction.

**Consequences that must land in the same commit:**

- `registry._resolve`'s fail-closed fallback returns the SDK backend, not
  `_CLI_BACKEND` (`:57` and `:64`; `_CLI_BACKEND` defined `:33`).
- `registry.backend_for`'s rung 5 (`:94`) becomes
  `DEFAULT_BACKEND_FOR_SURFACE.get(surface, "sdk")`.
- **`provider.py` has its own, independent copy of the whole chain** and needs
  three edits, not one — see `MAJOR-5` in §8.2. `_fold_backend`'s unknown-fold
  (`:148`), `resolve_backend_name`'s rung 5 (`:144`), and the `cli`-refusal
  path the doctor must report.
- `17-invocation-runbook.md` §6 ("Rollback is an environment variable") is
  **rewritten**, not amended (§16). *After this unit there is no rollback but
  a revert.* That is the largest cost of the unit and it must be stated in the
  runbook's own voice, not left implied.

---

## 6. DECIDE — `claude-agent-sdk` becomes a hard dependency

**Ruled: yes, per the plan line — and it supersedes `S-43`, which must be
amended in the same commit.**

`S-43` reads: *"`claude-agent-sdk` ships as an OPTIONAL EXTRA
(`self-learn-cli[sdk]`), never a hard dependency. The bundle is ~252 MB; a
machine that never leaves `backend=cli` pays none of it."* The premise —
that a machine can stay on `backend=cli` — is what this unit removes. `S-43`
is not reversed by opinion; it is **retired by its own stated condition
lapsing**, and the decision row (§14) must say so in those terms.

Today (`plugins/self-learn/cli/pyproject.toml`):

```toml
dependencies = ["ruamel.yaml>=0.18"]                        # :11-13
[project.optional-dependencies]
sdk = ["claude-agent-sdk>=0.2.116,<0.3"]                    # :15-16
```

*(Note for the builder: the plan `:246` specified the range-pin
`>=0.2.121,<0.3`; the shipped pin is `>=0.2.116,<0.3`, matching the UI. The
resolved version is 0.2.134, locked at `cli/uv.lock:150-151` (`name` `:150`, `version` `:151`; the `[sdk]`-extra requirement row is `:764`). Do not silently
"fix" the lower bound while moving the line — that is a separate decision.)*

After: `claude-agent-sdk` moves into `dependencies`; the `[sdk]` extra is
**kept as an empty-but-present alias** so `pip install 'self-learn-cli[sdk]'`
— the exact string three shipped tests and the runbook print at operators —
does not become an error. `install.sh:91`'s `uv sync --project cli` already
installs the dev group and needs no change.

Two shipped tests invert and must be rewritten, not deleted:

- `test_invocation_sdk.py::test_rs7_project_dependencies_unchanged_and_sdk_in_dev_and_extra_only`
  (`:1928-1931`) currently asserts `"claude-agent-sdk" not in` the main
  dependencies block. **Invert.**
- `test_invocation_sdk.py::test_rs8_lockfiles_no_package_added_or_removed_no_version_changed`
  — the lock's *closure* does not change (`RS8`, U-sdk r3: the dev group
  already locks 0.2.134 and its closure), but the dependency **stanza** does.
  Re-baseline, do not widen.

**Keep `BackendUnavailable` and the lazy import.** With the SDK a hard
dependency an `ImportError` stops being an expected state, but it does not
stop being a *reachable* one (a partial install, a broken wheel, a venv
mid-upgrade). The lazy import + `BackendUnavailable` converts that into a
logged per-surface `Outcome` instead of a traceback out of `worker.run`. The
message changes from "install the extra" to "reinstall". `test_rg5`
(`test_invocation.py:1650`) and the `sdk_absent` fixture keep their meaning.

---

## 7. DECIDE — the closures

**Ruled: `cli_argv_builder` and `cli_settings_writer` are DELETED from
`SessionSpec`, and the SDK's doctrine relay is replaced by a first-class
field. This is `[A]` work — it must land before, or with, the migration, and
never after the deletion.**

`SessionSpec` gains:

```python
doctrine: str | None = None   # appended to the claude_code system-prompt preset
```

`options_kwargs` (`invocation_sdk/backend.py:167-186`) drops the argv
construction and the `_read_argv_flag` call, and reads `spec.doctrine`
directly. `_read_argv_flag` and `A-5`'s "read set is closed at one flag"
comment go with it.

Call sites, all three, by symbol:

| Call site | Today | After |
|---|---|---|
| `worker._invoke_claude` (`worker.py:3151-3152`) | `cli_argv_builder=lambda _settings: argv`, `cli_settings_writer=None` | **`doctrine=None`** — the worker emits no `--append-system-prompt` (§2.3.1, measured); its doctrine rides the **prompt** at `worker.py:1514`. *r1 specified `doctrine=<the doctrine text run() already has>` here; that would have ADDED a system prompt that does not exist today and duplicated text already in the prompt* |
| `analyst.analyze` (`analyst.py:253-254`) | `cli_argv_builder=lambda _s: build_argv(prompt, doctrine_text, model)` | `doctrine=doctrine_text` — **the only surface that carries one** |
| `miner._invoke_reader` (`miner.py:790-791`) | `_reader_cli_argv_builder` + `write_reader_settings` | `doctrine=None` |

**This closes §2.3's second finding for free:** `miner.write_reader_settings`
stops being called on every nightly run, so the seam stops writing a settings
JSON that nothing reads.

**`FakeBackend` loses `.argvs`.** `fake.py:79-82` is the only other consumer.
21 assertion sites reference `.argvs` across 4 files (`test_invocation.py`,
`test_composer.py`, `test_u_fake.py`, `test_worker_contract.py`); `.prompts`
has 1. Replacement: `FakeBackend` records `.doctrines` (a list, same shape as
`.prompts`), and every `.argvs` assertion is re-expressed against
`.prompts` / `.doctrines` / `.specs[n].containment` — which is what those
assertions were reaching *through* argv to reach. `test_u_fake.py::test_t1c_move1_tests_keep_the_argv_shape_assertions`
is one of the 21 and is **re-baselined, not deleted** (§13.2, U-fake `R-1`).

**What survives.** `worker.build_argv`, `worker.write_settings_file`,
`analyst.build_argv`, `miner.build_reader_argv`, `miner.write_reader_settings`
and `miner._reader_cli_argv_builder` become **unreferenced product code** the
moment the closures go. They are in the §8 deletion inventory. Their tests are
in §8.4's arithmetic. **Do not leave them as dead exports** — `worker.py:99`,
`worker.py:120`, `analyst.py:76`, `miner.py:77` list them in `__all__`, and a
dead public name is how a later reader concludes the CLI path still exists.

---

## 8. Deletion inventory

Complete as measured at `ee0d671`. Paths are repository-relative.

### 8.0 Reader sweep — every deleted symbol, every reader (NORMATIVE)

**r1 asserted one symbol's reader set from memory and got it wrong
(`BLOCKER-1`). This table exists so that cannot recur, and no symbol may be
added to §8.1/§8.2 without a row here.**

**Method, r3 — TWO columns, because one was not enough.** r2 measured only
*direct* references: AST-walk every `test_*` function, regex its own source
segment. That method produced two wrong cells (`build_argv` 4/7 instead of
**4/9**; `_read_argv_flag` **0/0** for a symbol that has a reader) and, worse,
was blind to an entire route — **a reference that lives in a module-level
helper or fixture rather than in the test body**. r3 adds a second column
measuring exactly that, and §8.0a below is the population it exposes.
`src/` readers by `grep -rn`.

> **A symbol's reader set is the union of both columns.** A builder who greps
> only test bodies will miss `_spec`, `_spec_for`, `_bg_argv`, `_drive_fl2_lines`,
> `_spy_write_session`, `_capture_analyst_prompt`, `_drive_reader_sdk`, and the
> `backend` / `reader_leg` fixtures — which between them carry deleted symbols
> into **more than a hundred** test functions.

| Deleted symbol | `src/` readers | Tests naming it — **impacted / NOT impacted** |
|---|---|---|
| `CliBackend` | `invocation/cli.py:21` (def), `registry.py:17` (import) + `:33`, `invocation/__init__.py:7`/`:48`, doc-mentions `contract.py:291`, `registry.py:127`, `miner.py:602`, `invocation_sdk/backend.py:167` | **0 / 37** — invocation 23, u_sdka 5, reader_contract 3, worker_contract 3, u_fake 2, invocation_sdk 1 |
| **`TRANSPORT` / `TransportSpec`** | `contract.py:290`/`:302` (def), `invocation/__init__.py:13`/`:21`/`:46`/`:47`, **`invocation/cli.py:18`+`:38`**, **`invocation_sdk/backend.py:41` (import) + `:60` (`_CATCHES_OS_ERROR` fold) → consumed `:485`, `:493`** | **0 / 2** — invocation_sdk 1, u_sdka 1 (`test_u_sdka.py:1025` asserts `TRANSPORT["analyst"].catches_os_error is True`) |
| `cli_argv_builder` | `contract.py:192`, `cli.py:44`, `fake.py:82`, **`invocation_sdk/backend.py:168`** | **2 / 6** — reader_contract 2 / 0, u_sdka 0 / 5, invocation_sdk 0 / 1 |
| `cli_settings_writer` | `contract.py:193`, `cli.py:42`, `fake.py:80`, **`invocation_sdk/backend.py:169`**, `miner.py:791` | **2 / 1** — reader_contract 2 / 0, invocation_sdk 0 / 1 |
| `worker.build_argv` (+ `analyst.build_argv`) | `worker.py:992` (def), `:99` (`__all__`), `:3210`, `:3290`; `analyst.py:121`/`:76`/`:253` | **4 / 9** *(r2 said 4/7 and its own sub-counts did not sum to it)* — worker_contract 1/5, invocation 1/**1**, u_sdka 0/**2**, invocation_sdk 0/1, repair 1/0, worker 1/0 |
| `worker.write_settings_file` | `worker.py:918` (def), `:120` (`__all__`), `:3210` | **2 / 7** — attrib 2/4, **`test_hosting.py` 0/2**, invocation 0/1 |
| `miner.write_reader_settings` | `miner.py:546` (def), `:77` (`__all__`), `:791` | **0 / 2** — invocation 0/1, **`test_miner.py` 0/1** |
| `miner.build_reader_argv` / `_reader_cli_argv_builder` | `miner.py:598` (def), `:790` | **1 / 3** — invocation 1/0, reader_contract 0/2, miner 0/1 |
| `FakeBackend.argvs` | `fake.py:66`, `:82` | **0 / 7** — composer 3, u_fake 2, invocation 1, worker_contract 1 |
| `analyst.build_argv` | `analyst.py:121` (def), `:76` (`__all__`), `:253`, docstring `:14` | folded into the `build_argv` row above |
| `_read_argv_flag` | `invocation_sdk/backend.py:116` (def), called `:178` | **0 / 1** *(r2 wrote 0/0 — a symbol asserted to have NO readers that has one is precisely the failure this table exists to prevent; r2 listed the row without measuring it)* — `test_invocation_sdk.py::test_op11_model_from_provider_not_argv_and_append_system_prompt_last_element_edge` names it at `:584` and `:597`. *(The gate cited `test_op13` at `:626`; measured, the naming test is `test_op11`. Both agree the cell is not 0/0.)* **Separately and consequentially: `test_op13_argv_read_set_is_closed` (`:626-631`) asserts `literals == {"--append-system-prompt"}` over `inspect.getsource(backend_mod)`. §7 removes the last `--` literal from that module, so the set becomes empty and the test must be re-baselined — see §8.4b** |
| shim fixtures + `tests/shims.py` | — (test-only) | **122 / 34** — repair 43/3, attrib 32/1, worker 23/9, route_cli 8/2, u_fake 0/9, invocation 5/1, worker_contract 4/2, u_sdka 1/2, miner 2/0, invocation_sdk 0/2, reader_contract 0/2, round3_fixes 1/1, batch_fixes 1/0, composer 1/0, regime_fixes 1/0 |
| `KNOWN_BACKENDS`'s `"cli"` member | `registry.py:31`, `provider.py:148` | **0 / 3** — invocation 1, u_sdka 1, worker_contract 1 |

### 8.0a INDIRECT readers — deleted symbols reached through module-level helpers and fixtures

Measured r3 (same regexes, applied to non-`test_` top-level functions and
class methods, then counting the callers). **Counting rule, stated so the
numbers are reproducible (`R3-N1`):** a test function counts as a caller when
the helper's name matches `\b<name>\b` anywhere in
`ast.get_source_segment(...)` of that test — **which begins at its `def` line**,
so a fixture named in the *signature* (`backend`, `reader_leg`) and a helper
called in the *body* (`_spec`, `_drive_reader_sdk`) are counted the same way,
and a name appearing only in a comment counts too. A stricter rule — signature
names for fixtures, `ast.Call` nodes for helpers — shifts individual cells by
±1 (an independent measurement under a stricter rule got `_spec` 59 and
`_drive_reader_sdk` 9 against the 58 and 10 below). **The cells are within
method margin; the conclusion — that the indirect population is larger than the
direct one — is not sensitive to which rule is used**, and no criterion,
mutation or disposition depends on these numbers.

| Symbol | Helper / fixture | File | Test fns calling it |
|---|---|---|---|
| `cli_argv_builder` + `cli_settings_writer` | `_spec` | `test_invocation_sdk.py` | **35** |
| `cli_argv_builder` + `cli_settings_writer` | `_spec` | `test_invocation.py` | **23** |
| `CliBackend` | `backend` (fixture) | `test_worker_contract.py` | **20** |
| `CliBackend` | `reader_leg` (fixture) | `test_reader_contract.py` | **15** |
| `cli_argv_builder` | `_spy_write_session` | `test_worker_contract.py` | **13** |
| `CliBackend` | `_drive_reader_sdk` | `test_reader_contract.py` | **10** |
| `build_argv` + `.argvs` | `_capture_analyst_prompt` | `test_composer.py` | **3** |
| `build_argv` | `_bg_argv` | `test_worker_contract.py` | **3** |
| `build_argv` + `cli_argv_builder` + `cli_settings_writer` | `_spec_for` | `test_worker_contract.py` | **2** |
| `cli_argv_builder` | `_minimal_session_spec` | `test_u_fake.py` | **2** |
| **`build_argv`** | **`_drive_fl2_lines`** | `test_worker_contract.py` | **1** — `test_fl2`, and this one is `BLOCKER-B`'s worked case (§8.4b) |
| `CliBackend` | `_backend_for_expectation` | `test_provider.py` | **1** |

**This is the fourth blind spot, stated exactly.** `A1` measures *dispatch*;
`A3` measures *symbol-naming inside a test body*. Neither sees a reference that
lives one call-frame away. `test_fl2_byte_identity_and_provenance[sdk]` is
defeated by **both** instruments at once: it names no deleted symbol in its own
body (the `build_argv` call is inside `_drive_fl2_lines`, `:1342`), and it does
not fail under `A1` (its helper re-sets `SELF_LEARN_BACKEND_WORKER` inside the
test body, *after* fixtures run, so the unpin instrument cannot hold). Only the
armed tripwire — instrument **`A4`**, §10 — catches it.

**Three readings this table makes unmissable, all three of which earlier rounds got wrong:**

1. **`TRANSPORT` is read by the surviving backend.** Not "only by
   `CliBackend._run`". See §8.2's redesigned row.
2. **`CliBackend` has 37 direct test readers and ZERO of them are in the 160.**
   The blast-radius instrument cannot see source-reading tests at all — which
   is §3.4(c), and the reason §8.4 gains a fourth partition.
3. **The indirect column is larger than the direct one.** `_spec` alone carries
   the two deleted closures into 58 test functions across two files. Any
   estimate of migration cost built from §8.0's first column alone is low by
   roughly an order of magnitude.

### 8.1 Product code — delete outright

| Path | Symbol | Lines | Note |
|---|---|---|---|
| `plugins/self-learn/cli/src/self_learn/invocation/cli.py` | `CliBackend` (whole module) | 149 | the only `subprocess` model spawn |
| `.../invocation/__init__.py` | `from .cli import CliBackend`; `"CliBackend"` in `__all__` | 2 | `:7`, `:48` |
| `.../invocation/registry.py` | `from .cli import CliBackend`; `_CLI_BACKEND` | 2 | `:17`, `:33` |
| `.../src/self_learn/worker.py` | `build_argv`, `write_settings_file`, `_settings_permissions` helper if unshared | ~90 | `:992`, `:918`; `__all__` rows `:99`, `:120` |
| `.../src/self_learn/analyst.py` | `build_argv` | ~35 | `:121`; `__all__` row `:76` |
| `.../src/self_learn/miner.py` | `write_reader_settings`, `_reader_cli_argv_builder`, `build_reader_argv` | ~80 | `:546`, `:598`; `__all__` row `:77` |
| `.../invocation_sdk/backend.py` | `_read_argv_flag`, the argv construction in `options_kwargs` | ~20 | `:116` (def), called `:178`; argv build `:168-169` |

### 8.2 Product code — edit

| Path | Symbol | Change |
|---|---|---|
| `.../invocation/contract.py` | `SessionSpec` | drop `cli_argv_builder`, `cli_settings_writer`; add `doctrine` (§7) |
| `.../invocation/contract.py` | `TransportSpec`, `TRANSPORT` | **TRIM to the surviving field — do NOT delete the table.** *(r1 said "DELETE the table entirely; its only reader is `CliBackend._run:38`". That was **false**: `invocation_sdk/backend.py:41` imports `TRANSPORT` and `:60` folds `_CATCHES_OS_ERROR = {surface: spec.catches_os_error for surface, spec in TRANSPORT.items()}`, consumed at `:485` and `:493` — the analyst-vs-worker/miner `raise`-vs-catch split on the **surviving** backend.)* Per-field disposition, each by its measured readers: `kind` — reader: `cli.py:47` only → **delete**; `kills_process_group` — reader: `cli.py:60` only → **delete**; `prompt_via_argv` — reader: `cli.py:70` only → **delete**; `result_stdout` — **no reader that SURVIVES** (`R2-N2`: `cli.py` *is* `src`, and it branches on the field inline at `:69`/`:80`/`:92`; those reads die with the module, and nothing outside `cli.py` reads it) and `test_ou7_stdout_per_surface` asserts the behaviour independently → **delete**; **`catches_os_error` — two readers, both in `invocation_sdk` → KEEP.** Shape: keep `TRANSPORT` as a `dict[str, bool]` (or rename to `CATCHES_OS_ERROR` and relocate into `contract.py` beside `LOG_TEMPLATES`), so `03-decisions.md:62`'s recorded `M11` evidence — *"reverting `TRANSPORT[\"analyst\"].catches_os_error` … proving the contract had to close at the transport-table level, not the caller"* — stays a mutable, table-level fact and **§14's "S-48 survives unchanged" becomes true**. `test_u_sdka.py:1025` must be updated to the new spelling, not deleted. *(All four surfaces are `True` today, so the `raise` branches at `:485`/`:493` are currently unreached — that is exactly why the flag must remain **mutable at the table**, or `M11` stops being reproducible and S-48 loses its evidence.)* |
| `.../invocation/contract.py` | `LOG_TEMPLATES`, `LogTemplates` | **KEEP UNCHANGED** — the SDK backend renders through it (`Map-1`), and after §3.4 it is the sole authority for the failure-leg wording. **`not_found` stays REACHABLE under sdk** (`CLINotFoundError` → `backend.py:465-469`; guarded by `test_ou1` `:1473`/`:1493-1494`) — *r1 wrote "becomes unreachable under sdk", which was false* |
| `.../invocation/contract.py` | `DEFAULT_BACKEND_FOR_SURFACE` | keep the table; the `"cli"` string may no longer appear as a value |
| `.../invocation/registry.py` | `KNOWN_BACKENDS`, `_resolve`, `backend_for` | `("sdk",)`; `_CLI_RETIRED_MESSAGE`; fallbacks → sdk (§5) |
| `.../invocation/fake.py` | `FakeBackend._step` | drop the closure calls and `.argvs`; add `.doctrines` (§7) |
| **`.../src/self_learn/provider.py`** | `resolve_backend_name` (`:106-144`), `_fold_backend` (`:147-148`) | **`MAJOR-5`: the doctor has a SECOND, INDEPENDENT transcription of the precedence chain that never calls `registry._resolve` and therefore never sees `BackendUnavailable`** — its own docstring says so (`Rs-a`, `:106-112`: *"Re-derived rather than read from `registry.backend_for`"*). Three sites: `:109` (docstring, *"default `\"cli\"`"*), `:144` (`return DEFAULT_BACKEND_FOR_SURFACE.get(surface, "cli"), "default"`), `:148` (`_fold_backend`: unknown → `"cli"`). With only r1's prescribed `_fold_backend` edit, `SELF_LEARN_BACKEND_WORKER=cli` would make the doctor print `worker: backend=sdk (env:SELF_LEARN_BACKEND_WORKER)` — reporting a **retired selection as accepted**, which is the SEL5-shaped lie §5 exists to prevent. **Required:** `resolve_backend_name` must return a refusal-bearing answer for a `cli` value, and the `switches` row (`:621-623`) must render it. `ProviderResolution.backend`'s documented invariant (*"a member of `registry.KNOWN_BACKENDS`"*, `:156`) blocks simply returning `"cli"`, so the builder picks one of: (a) a third tuple element `refused: str \| None`, or (b) `backend_source` carrying the refusal (e.g. `"env:SELF_LEARN_BACKEND_WORKER (REFUSED: cli retired)"`). **Ruled: (a)** — a source string is for provenance, and overloading it makes the refusal unparseable by the `SEL6` test. Also keep `Rs-b` (silent): the registry already warns |
| `.../src/self_learn/worker.py` | `_invoke_claude` (`:3151`), `run` (`:3210`, `:3290`) | pass `doctrine=`; drop the pre-built argv/settings plumbing |
| `.../src/self_learn/analyst.py` | `analyze` (`:253-254`) | pass `doctrine=doctrine_text` |
| `.../src/self_learn/miner.py` | `_invoke_reader` (`:790-791`) | pass `doctrine=None` |
| `plugins/self-learn/cli/pyproject.toml` | `dependencies`, `[project.optional-dependencies]` | §6 |

### 8.3 Test harness — delete

| Path | What | Size |
|---|---|---|
| `plugins/self-learn/cli/tests/shims.py` | whole module — `write_worker_claude_shim`, `write_analyst_claude_shim`, `write_reader_claude_shim` | 128 lines |
| `tests/test_worker.py:125` | `claude_cli_shim_worker` fixture | ~90 lines |
| `tests/test_route_cli.py:146` | `claude_cli_shim_analyst` fixture | ~30 lines |
| `tests/test_repair.py:73` | `claude_shim = claude_cli_shim_worker` — U-fake `Compat-1`, **R-1 closes here** | 1 line + its 4-line comment |
| `tests/test_invocation.py:74` | `_ANALYST_CLAUDE_SHIM` + its writer (`:87`) — U-fake `R-2`'s third script | ~15 lines |
| `tests/test_composer.py:1120` | `_shim_env`'s inline shim — U-fake `R-2`'s fourth script | ~20 lines |
| `tests/conftest.py:106,114,115` | the three `SELF_LEARN_BACKEND_*=cli` pins (§2.2) | 3 lines + ~18 lines of comment |
| every `import` of `shims` | `test_worker.py:23`, `test_route_cli.py:21`, `test_u_sdka.py:43`, `test_worker_contract.py:54`, `test_reader_contract.py:45` (`import shims`, module-qualified), and **`test_u_fake.py` TWICE — `:303` (`from shims import write_worker_claude_shim, write_analyst_claude_shim`) and `:383` (`import shims`)** | **7 sites in 6 files** — r1 counted 6 and named only `:303` |

`tests/backends.py` (57 lines, `install_fake`) **survives** — it is the T1
injection point onto `FakeBackend` and is backend-agnostic.

### 8.4 Tests — the count that must reconcile

The builder owes an **exact, itemised** reconciliation. From the measurements:

| Class | Count | Disposition |
|---|---|---|
| `[cli]` parametrized legs (worker_contract 18, reader_contract 14, u_sdka 11) | **43** | **delete** the leg; the parametrization collapses to unparametrized (`CB-3`) |
| CLI-only named tests outside the parametrization | **≈ 11** — `ws3_cli_witness_b`, `ws5a_stdout_never_parsed_cli_behavioral`, `ha1_cli_hatch_open_omits_default_mode`, `ev5_cli_leaves_no_events_file`, `fr1_backend_worker_cli_resolves_both_surfaces`, `hy5_cli_side_no_real_claude_control`, `bg2_cli_prompt_delivered_intact_on_stdin`, `pb4_cli_param_shim_actually_reached`, `to4_cli_kill_path_killpg_then_wait`, `to5_swallows_processlookuperror_and_permissionerror_separately`, `fl1_backend_var_cli_resolves_clibackend` | **delete** |
| argv/settings-asserting T3 tests (§3.4 table) | **17** | **delete** — subject removed with the code |
| behaviour T3 tests | **≈ 109** | **MIGRATE** onto `fake_claude.py` or `FakeBackend` (§3.5). Deleting any of these is a criterion failure |
| `test_u_fake.py` instrument criteria that name the rename or `BASE_REF` | **≈ 6** of 17 (`FX1`, `FX4`, `FX5`, `SH1`, `SH2`, `DS1`) | **re-baseline or delete with reasons stated per test** — U-fake `R-8` names whoever rebases as the owner of `BASE_REF` |
| `test_invocation_sdk.py::test_ou3` | 1 | **rewrite** (§3.4, `CB-4`) |
| `test_invocation_sdk.py::test_rs7`, `test_rs8` | 2 | **invert / re-baseline** (§6) |
| **The class r1 missed — tests naming a deleted PRODUCT symbol that are NOT in the 160** | **66 distinct functions** (see §8.4a) | **each needs an individual disposition; none is covered by "migrate"** |

**Predicted final collected count — r1's arithmetic was against the wrong
baseline and is retracted.** r1 wrote `2402 − 43 − 11 − 17 − (0…6)`. Under the
ratified split, **A lands first and ADDS tests** — the 18 of §11.1 plus the
`RO-1`…`RO-4` knob tests (several of the 18 already cover those) — so **B is
measured against a post-A baseline strictly greater than 2402**, and the exact
number is A's to measure, not this spec's to predict. The gate arithmetic is
therefore:

> **B's collected count = (A's measured post-migration collected count) −
> (§8.4's itemised deletions).** A's own post-migration count is a **measured
> anchor A must publish**; B may not be gated against any number A did not
> measure.

A builder reporting a B-side count without naming A's anchor has not satisfied
`CV1`.

### 8.4a The 66 — tests naming a deleted product symbol, outside the 160

Measured by the §8.0 method (regex
`CliBackend|TRANSPORT|TransportSpec|cli_argv_builder|cli_settings_writer|build_argv|write_settings_file|write_reader_settings|build_reader_argv|_reader_cli_argv_builder|\.argvs`
over each `test_*` function's source segment; partitioned against the §3.3
impacted set):

| File | count | Character of the references |
|---|---|---|
| `test_invocation.py` | **26** | U-seam's own seam suite — argv-identity, twin-witness, the `_HY3_SHAS` source-sha table (`:504`, `:519`), the surface→settings-writer map (`:685`), the `__all__` audit (`:808`) |
| `test_u_sdka.py` | **10** | see §8.4b |
| `test_worker_contract.py` | **9** | see §8.4b |
| `test_reader_contract.py` | **5** | see §8.4b |
| `test_attrib.py` | **4** | `write_settings_file` path pins |
| `test_composer.py` | **3** | `.argvs` assertions (§7) |
| `test_invocation_sdk.py` | **3** | incl. `test_ou3`, `test_op12/op13` (the settings-writer-before-argv-builder order) |
| `test_u_fake.py` | **3** | instrument criteria |
| **`test_hosting.py`** | **2** | `write_settings_file` (`:792`, `:822`) — **a file r1 never mentioned anywhere** |
| **`test_miner.py`** | **1** | `write_reader_settings` (`:746`) — **likewise** |

Plus, outside this regex but the same class: **`test_lock_invariant.py:148`**'s
declared-writes row `"miner.write_reader_settings": "XDG cache: the reader's
Claude settings"` — a *string key*, so no symbol regex finds it, and the row
becomes a lie the moment the writer is deleted. **The builder must grep for
deleted symbols as STRINGS as well as identifiers.**

`test_hosting.py`, `test_miner.py:746` and `test_lock_invariant.py:148` cannot
be "migrated": their subject — that a settings file is written to a particular
place — **is deleted**. They are `delete` / `re-baseline`, and saying so is the
point of this table.

*(Method delta, recorded rather than smoothed over: the blind gate measured
**60** here and **26** in §8.4b; this spec's independent re-measure at
`ee0d671` gives **66** and **27**. The regexes differ at the margin — this one
counts `TRANSPORT`/`TransportSpec` and a bare `build_argv` the gate's did not,
which adds `test_worker_contract.py::test_rp1_repair_round_wiring` among
others. Neither figure is "the" answer; the **method is stated so a builder can
re-run it**, and the disposition obligation is per-test, not per-count.)*

### 8.4b The T2 files — per-test disposition (BLOCKER-5)

**27 tests across the three T2 files name a deleted product symbol.**
*(`R2-N1` — why this is 27 while §8.4a's same-three-file rows sum to 24: **§8.4a
counts only tests OUTSIDE the 160**, §8.4b counts **all** of them. The
difference is exactly the 3 impacted ones — `reader_contract` ×2 via
`cli_argv_builder`/`cli_settings_writer`, `worker_contract` ×1 via `build_argv`.
Both figures are measured and correct; they answer different questions.)*

**Plus one test that names no deleted symbol in its own body and belongs here
anyway** — `worker_contract::test_fl2_byte_identity_and_provenance[sdk]`, whose
`build_argv` call lives in `_drive_fl2_lines` (`:1342`). It is the reason this
table cannot be built from a symbol grep alone (§8.0a, `BLOCKER-B`).

`CV2`'s
r1 wording ("assertions unchanged, a body diff showing only the
parametrization removal") is **unsatisfiable** for these and is rewritten in
§9. Dispositions:

| Test | Disposition |
|---|---|
| `reader_contract::test_rc7_prompt_reaches_the_model_on_stdin_never_argv` | **REWRITE — the load-bearing one.** Its `[sdk]` branch does `built_argv = run.spec.cli_argv_builder(run.spec.cli_settings_writer())` and asserts the 200 KiB prompt is in no argv element (`:658-670`). Strip those two lines and all that remains is `assert run.spec.prompt == big_prompt` — **a tautology about the spec object**, and the reader surface loses its >128 KiB wire assertion entirely. **Replacement (`RO-7`), modelled on the genuine wire test `worker_contract::test_bg3_sdk_prompt_delivered_intact` (`:1654-1680`):** spy `ClaudeSDKClient.query`, assert the big prompt arrives on the wire, **and** assert it appears in no element of the child's own recorded argv via `FAKE_CLAUDE_ARGV_LOG`. Both halves of "on stdin, never argv" then hold against the surviving transport |
| `reader_contract::test_fl1_backend_var_cli_resolves_clibackend` | **DELETE** — replaced by `T-CLI-REFUSED-*` |
| `reader_contract::test_mc1`, `test_mc3`, `test_mc4` | **REWRITE** — `--strict-mcp-config` argv-position assertions; the sdk analogue is `options_kwargs["strict_mcp_config"] is True`, already asserted by `test_op6`. Reduce to the `CT2` options-table assertion, do not delete silently |
| `reader_contract::test_fl2_clean_env_resolves_sdkbackend`, `test_fl3_selector_scoping_both_directions` | **RE-BASELINE** — they name `CliBackend` only as the negative pole |
| `worker_contract::test_fr1_backend_worker_cli_resolves_both_surfaces`, `test_hy5_cli_side_no_real_claude_control`, `test_ws5a_stdout_never_parsed_cli_behavioral` | **DELETE** (already in the "CLI-only named tests" class) |
| `worker_contract::test_pb1_backend_identity_per_param`, `test_rp3_repair_surface_direct_drive`, `test_to2_repair_timeout_bounds_both_backends`, `test_fl1_failure_legs_never_raise`, `test_rp1_repair_round_wiring` | **COLLAPSE + RE-BASELINE** — keep the `[sdk]` behaviour, drop the `[cli]` pole and any `build_argv` construction (replace with the `SessionSpec` the real call site builds, per `S-46`) |
| `worker_contract::test_ws5b_stdout_never_parsed_sdk_behavioral`, `test_fr4_selector_mapping_does_not_cross_govern` | **RE-BASELINE** — reference is incidental |
| `u_sdka::test_fl1`, `test_fl2`, `test_fl3`, `test_fl5_the_two_transcriptions_agree_over_the_full_matrix`, `test_fl7_missing_extra_never_loses_a_lesson`, `test_ar4_byte_identity_under_the_rollback` | **REWRITE.** `fl5` is the one that pins `registry` and `provider` agreeing across the full matrix — **it is `MAJOR-5`'s natural home** and must be extended to cover the refusal, not weakened. `ar4` ("byte identity under the rollback") tests a rollback that no longer exists → **DELETE**, and note it in the runbook rewrite (§16 DOC3) |
| `u_sdka::test_hd4`, `test_hd5`, `test_hd6`, `test_hd7` | **RE-BASELINE** — analyst hardening; the `build_argv` reference is construction scaffolding, replaceable with `doctrine=`. (`hd7` is also an `A4` tripper — re-base it onto the SDK process table.) |
| **`worker_contract::test_fl2_byte_identity_and_provenance[sdk]`** | **REWRITE — and this is the one explicit exception to `CV2` clause 4.** Clause 4 promises the 16 non-listed `[sdk]` legs change only by the parametrization removal. **`fl2[sdk]` cannot honour that**, and saying so is the whole point of `BLOCKER-B`. Measured (`:1355-1398`): **what SURVIVES unchanged** is `:1377-1390` — the per-`FAILURE_KINDS` provenance-and-shape loop asserting every cell emits a `MARKER-`-tagged line under `dataclasses.replace`d templates, plus the `exit`-line shape regex (keep the `sdk` branch's `claude exited 1`, delete the `cli` branch's `exited 7`) and the documented `os-error`/`sdk` empty cell (`R-10`). **What is DELETED** is `:1392-1398` — the `other = _drive_fl2_lines("cli", …)` pass and the three-kind `cli_line == sdk_line` comparison, the suite's only genuine cross-backend oracle (§3.4.1). **What REPLACES it:** `RO-6`'s `LOG_TEMPLATES` byte-pin, captured in **A while the CLI pass still runs**, so the pinned values are the ones the comparison last verified rather than values re-typed after it was removed. **`_drive_fl2_lines` itself must lose its `param` argument and its `worker.build_argv` call (`:1342`) — replaced by the `SessionSpec` the real call site builds (`S-46`).** A builder who merely deletes the `if backend.param == "sdk":` block has silently dropped an oracle without landing its replacement |
| **`invocation_sdk::test_op13_argv_read_set_is_closed`** (`:626-631`) | **RE-BASELINE — a §7 consequence no earlier round named.** It asserts `set(re.findall(r'"(--[A-Za-z0-9-]+)"', inspect.getsource(backend_mod))) == {"--append-system-prompt"}`. §7 removes `_read_argv_flag` and the argv relay, so that module contains **no** `--` literal and the set becomes empty. Re-base to `== set()` and re-point the criterion at what it actually guards after §7: that `options_kwargs` reads `spec.doctrine` and **no** argv-derived value. Deleting it instead removes the only structural guard on the read set |

### 8.5 Docs

Inventoried by `grep -c "CliBackend\|SELF_LEARN_BACKEND"` over
`docs/specs/self-learn/*.md`:

| File | Hits | Change |
|---|---|---|
| `17-invocation-runbook.md` | **13** | §1 (two switches → one), §2 (install the extra), §4.2/§4.3 (env + config flips), **§5.6 rewritten to past tense**, **§6 Rollback rewritten (§5)**, §7 traps re-checked |
| `14-forward-work-map.md` | 5 | close the rows the deletion closes; open a row for the loss of env-var rollback |
| `03-decisions.md` | 3 | the new row + the `S-43` amendment (§14) |
| `12-transcript-miner.md` | 1 | one `claude -p` sentence |
| `08-build-plan.md` | — | one hit on the older phrasing; check at build time |

**Two runbook statements are already false at `ee0d671` and must be corrected
whichever way this unit lands:** §5.6's closing line — *"the default at every
rung stays `cli` until a surface passes its burn-in"* — and §6's *"Every
rung's default is `cli`"*. `DEFAULT_BACKEND_FOR_SURFACE` has been all-`sdk`
since U-flip (2026-08-23). This is a docs-truth defect, not a U-cleanup
consequence; it is listed here because this unit is the one holding the file.

---

## 9. Acceptance criteria

**Every criterion carries an explicit [A] or [B] tag. There is no default**
— r1 left 20 of 30 untagged and declared an implicit default of "whichever
unit ships last" (= B), which silently contradicted §3.5/§7's requirement that
`RO-6` be captured *before* the deletion. **38 criteria, all tagged — 10 [A], 28 [B].**

**AG — U-cleanup-A's own completion gate (all [A])**

r1 stated A's completion only as prose in §4's table ("`cli.py` still present
and **unreferenced by any test**"). That is a grep, not a runtime fact, and it
was not among the numbered criteria. The proven instrument is in the file this
spec already cites: `tests/conftest.py:23-24`'s session-scoped autouse
`_no_real_sdk_spawn_tripwire`, which hard-fails if `_find_cli()` is ever
reached. A's gate is its symmetric twin.

- **AG1** **[A]** A ships a session-scoped `autouse` tripwire in
  `tests/conftest.py`, modelled line-for-line on `_no_real_sdk_spawn_tripwire`
  (`:23-24`), that replaces `CliBackend._run` with a function raising
  `AssertionError` for the whole session. **The full suite is green with it
  armed** — every test in `A4`'s measured population (§10, **51** tests) having
  been migrated, collapsed or rewritten first. That — not a grep — is the
  operational meaning of "the CLI path is unreached".
  **Exemption (`R2-N4`):** exactly one test may reach `CliBackend._run` — `AG2`'s
  negative control, which exists to observe the tripwire fire. It reaches the
  patched `_run`, not the real transport, and it must arrange its own expected
  failure (`pytest.raises`) rather than being counted as a suite failure. No
  other exemption exists; a second one is a migration that was not done.
  **The tripwire is NOT to be scoped down to registry-resolved dispatch.**
  Narrowing it so that a test explicitly handing in `backend=CliBackend()` falls
  outside its reach would make `AG1` green while the CLI transport is still
  being exercised — which is the opposite of what A is for (orchestrator ruling,
  2026-08-24).
- **AG2** **[A]** the tripwire's own negative control: a test that calls
  `CliBackend().write_session(...)` directly and asserts the tripwire
  **fires**. (Without it, a tripwire that silently failed to install reads
  identically to a suite that never touches the CLI path — the fail-open shape
  `CV7`'s positive control guards against on the census side.)
- **AG3** **[A]** conftest's three `SELF_LEARN_BACKEND_*=cli` pins are
  **deleted in A**, not B. AG1 is only meaningful once the suite actually
  resolves `sdk` by default.
- **AG4** **[A]** A publishes its **post-migration collected count** as a
  measured anchor; B is gated against that number (§8.4, `MAJOR-4`).

Suggested shape (the builder may improve it; the *properties* are the
criterion):

```python
@pytest.fixture(scope="session", autouse=True)
def _cli_backend_unreached_tripwire():
    """U-cleanup-A AG1. The CLI path still SHIPS in A; nothing may REACH
    it. Symmetric with _no_real_sdk_spawn_tripwire (:23) — same scope,
    same autouse, same hard-fail-on-entry shape. Deleted in B along with
    CliBackend itself."""
    from self_learn.invocation.cli import CliBackend

    original = CliBackend._run

    def _tripped(self, spec):
        raise AssertionError(
            "CliBackend._run was reached during the test suite. U-cleanup-A's "
            "completion criterion is that every surface resolves and drives "
            "the SDK backend; a test that still reaches the subprocess "
            "transport has not been migrated."
        )

    CliBackend._run = _tripped
    try:
        yield
    finally:
        CliBackend._run = original
```

**CL — the deletion is complete**

- **CL1** **[B]** `grep -rn "CliBackend" plugins/self-learn/cli/src` returns
  **0** matches, including in docstrings. (Today: 10, across 5 files.)
- **CL2** **[B]** `plugins/self-learn/cli/src/self_learn/invocation/cli.py`
  does not exist; `git log --diff-filter=D` shows its removal in this commit.
- **CL3** **[B]** `KNOWN_BACKENDS == ("sdk",)`, and — **grep scoped to the
  whole of `src/self_learn`, not just `invocation/`** (`MAJOR-5`: `provider.py`
  carries its own `"cli"` literals at `:109`, `:144`, `:148`, none of which
  r1's `invocation/`-scoped grep reached) — the literal `"cli"` appears only
  inside `_CLI_RETIRED_MESSAGE` and the provider-side refusal it feeds.
- **CL4** **[B]** `grep -rn "subprocess" plugins/self-learn/cli/src/self_learn/invocation/`
  returns **0**.
- **CL5** **[B]** `TransportSpec` is gone; `TRANSPORT` survives **only** as the
  trimmed `catches_os_error` carrier of §8.2, still imported and folded by
  `invocation_sdk/backend.py`, and `test_u_sdka.py:1025`'s assertion is
  updated to the new spelling rather than deleted. *(r1's CL5 demanded both be
  "gone", which would have reopened `S-48` — `BLOCKER-1`.)*
- **CL6** **[B]** `tests/shims.py` does not exist and no test file imports it
  — **7 import sites in 6 files** (§8.3), including `test_u_fake.py` twice.
- **CL7** **[B]** `SessionSpec` has no `cli_`-prefixed field.
- **CL8** **[A]** *(moved from [B]; see AG3)* the three
  `SELF_LEARN_BACKEND_*=cli` lines are gone from `tests/conftest.py`, **and**
  — widened per `M-15` — `grep -rn '"cli"' plugins/self-learn/cli/tests`
  returns matches only inside tests that assert the refusal (SEL1–SEL5). A pin
  relocated from conftest into a module-level `setenv` would otherwise satisfy
  r1's CL8 while defeating its purpose.
- **CL9** **[B]** `grep -rnE "def (build_argv|write_settings_file|write_reader_settings|_reader_cli_argv_builder|build_reader_argv|_read_argv_flag)\b" plugins/self-learn/cli/src`
  returns **0**, and none of those names appears in any `__all__`
  (`worker.py:99`, `:120`; `analyst.py:76`; `miner.py:77`). A dead public
  export is how a later reader concludes the CLI path still exists.
- **CL10** **[B]** deleted symbols are grepped as **strings** as well as
  identifiers — `grep -rn 'write_reader_settings' plugins/self-learn/cli/tests`
  finds `test_lock_invariant.py:148`'s declared-writes **dict key**, which no
  identifier-regex reaches (§8.4a).

**SEL — a `cli` selection refuses, per §5**

- **SEL1** **[B]** `SELF_LEARN_BACKEND_ANALYST=cli` → `text_session` returns
  `Outcome(ok=False, failure="unavailable")`, **does not raise**, and logs
  exactly `invocation backend unavailable (<message>)` — the analyst template,
  byte-for-byte.
- **SEL2** **[B]** the same for all four surfaces through their own
  `LOG_TEMPLATES` rows (worker and worker-repair share one).
- **SEL3** **[B]** `SELF_LEARN_BACKEND=cli` (the coarse rung) refuses
  identically.
- **SEL4** **[B]** `invocation.backend_worker: cli` in `<home>/config.yaml`
  refuses identically, and the message names **that key**, not a per-surface
  key that was never present (the property `config.invocation_backend` already
  guarantees).
- **SEL5** **[B]** the retired-backend message is distinguishable from the
  unknown-value message: `SELF_LEARN_BACKEND=banana` still produces the
  generic warning and **resolves to sdk**, exit 0.
- **SEL6** **[B]** the doctor's `switches` row (`provider.py:621-623`) prints
  `backend=sdk (…)` for all four surfaces on a clean env, **and reports a
  `cli` selection as REFUSED, never as accepted.** *(`MAJOR-5`: not achievable
  from r1's prescribed edits. `resolve_backend_name` (`:106-144`) is an
  independent transcription that never calls `_resolve`, so with only
  `_fold_backend` changed, `SELF_LEARN_BACKEND_WORKER=cli` would print
  `worker: backend=sdk (env:SELF_LEARN_BACKEND_WORKER)` — a retired selection
  reported as honoured. §8.2's provider row specifies the refusal-bearing
  return.)*
- **SEL7** **[B]** `u_sdka::test_fl5_the_two_transcriptions_agree_over_the_full_matrix`
  is **extended, not weakened**, to cover the refusal across the full matrix —
  it is the only test that pins `registry` and `provider` agreeing, and
  `MAJOR-5` is exactly a disagreement between them.

**CV — coverage did not silently shrink**

- **CV1** **[B]** `CB-1`: collected count reconciles against **A's published
  post-migration anchor** minus §8.4's itemisation (`MAJOR-4`), with every
  deleted test named individually.
- **CV2** **[A]** `CB-3` — **rewritten; r1's version was unsatisfiable
  (`BLOCKER-5`).** r1 demanded all 43 `[sdk]` legs survive "with their
  assertions unchanged", a body diff showing "only the parametrization
  removal". Measured: **27 tests in the three T2 files name a symbol this unit
  deletes**, so an unchanged body is impossible for them. The criterion is
  therefore:
  1. every one of the 27 carries an explicit disposition from §8.4b's table,
     and the build report names it per test;
  2. for a test whose disposition is **COLLAPSE + RE-BASELINE**, the body diff
     shows the parametrization removal **plus only** the substitution named in
     §8.4b — nothing else;
  3. **no disposition may reduce an assertion to a statement about a
     `SessionSpec` field.** The worked failure is
     `test_rc7`: stripping its two deleted-symbol lines leaves
     `assert run.spec.prompt == big_prompt`, which asserts that a dataclass
     holds the value the test just put in it. `RO-7` replaces it with a wire
     assertion;
  4. the remaining 16 `[sdk]` legs (43 − 27) survive with bodies changed only
     by the parametrization removal.
- **CV3** **[A]** *(r1 left this untagged, defaulting it to B — which
  contradicted `RO-6`/§3.5/§7, all of which require the capture to happen
  while `CliBackend` still exists. `BLOCKER-3`.)* `CB-4` / `RO-6`:
  `test_ou3`'s table-authority leg
  (`test_invocation_sdk.py:1587-1602`, the `setitem` mutation) is present and
  **unmodified**; its one dying byte-pin (`:1585`,
  `LOG_TEMPLATES["worker"].not_found` asserted through `CliBackend`) is
  replaced by (i) a byte-pin over **every row of all three template sets**,
  captured while `CliBackend` still exists, and (ii) a re-assertion of the
  same `not_found` wording through the SDK's own not-found leg — which stays
  reachable (`test_ou1:1473`, `:1493-1494`). `M-9` reddens the byte-pin.
- **CV4** **[B]** `CB-2`: each of the four surfaces has ≥ 1
  real-SDK-subprocess test driven from its real call site; the build report
  names them.
- **CV5** **[A]** `RO-1`…`RO-4` land in `tests/fixtures/fake_claude.py` and
  each has a test in `test_invocation_sdk.py` that exercises the new knob.
- **CV6** **[A]** `RO-5`: `test_composer.py` has ≥ 1 analyst **failure**-leg
  test (U-fake `R-5` closes).
- **CV7** **[B]** no test in the suite requests a fixture that writes a bash script
  named `claude`: `pytest --fixtures-per-test | grep -cE "^claude_(cli_)?shim"`
  → **0** (today: 142). *Positive control: the same command at the repository
  root prints `39 errors` and every count 0 — run it from
  `plugins/self-learn/cli` and check the tail reads `no tests ran`.*
- **CV8** **[A]** `RO-7`: the reader surface has a **wire** assertion for the
  >128 KiB prompt — the prompt reaches `ClaudeSDKClient.query` and appears in
  no element of the child's recorded argv — modelled on
  `worker_contract::test_bg3_sdk_prompt_delivered_intact` (`:1654-1680`).
  Landing in **A** is what makes it checkable against the surviving `[cli]`
  leg before that leg is deleted.


**DEP — the dependency move**

- **DEP1** **[B]** `claude-agent-sdk` appears in `pyproject.toml`'s `dependencies`.
- **DEP2** **[B]** `pip install 'self-learn-cli[sdk]'` still resolves (the extra is
  retained as an alias, §6).
- **DEP3** **[B]** `test_rs7` is inverted and `test_rs8` re-baselined; neither is
  deleted or widened to a presence-anywhere check.
- **DEP4** **[B]** `uv.lock`'s resolved `claude-agent-sdk` version is **unchanged**
  (0.2.134, `cli/uv.lock:150-151`) and no package is added or removed from the
  closure.
- **DEP5** **[B]** `BackendUnavailable` survives with a reinstall-flavoured message;
  `test_rg5` and the `sdk_absent` fixture still pass.

**DOC — the record**

- **DOC1** **[B]** the §14 decision row lands in `03-decisions.md`, dated.
- **DOC2** **[B]** `S-43` carries a dated amendment naming the lapsed condition (§6).
- **DOC3** **[B]** `17-invocation-runbook.md` §6 states plainly that **rollback is now
  a revert, not an environment variable**, and §5.6 is past tense.
- **DOC4** **[B]** the two already-false runbook statements of §8.5 are corrected.

---

## 10. Mutation plan

No mutation cell can be `measured` for code this unit has not written. Two
**measured anchors** exist because §3.3's instrument is itself a mutation of
the runtime environment rather than of code, applied and removed with no
working-tree change (`git status --porcelain` empty; the plugin lives outside
the repository).

### Measured anchors (2026-08-24, re-run at `ee0d671`)

| # | Mutation | Result |
|---|---|---|
| **A1** | make `cli` unselectable at every rung (§3.3's plugin), whole suite in three batches | **measured, re-run at `ee0d671`** — 153 failed + 7 errors = **160 impacted** node ids (156 distinct functions), **2234 passed**, 8 skipped, 2402 collected. Per-module table in §3.3. *(r1 recorded "3234 passed" here and in §3.3; both were arithmetic errors and are retracted.)* |
| **A2** | the same, restricted to the five T3-core files | **measured** — 118 failed, 6 errors, 132 passed, 12.7 s. The T3 armor is 124/256 dependent on `cli` being selectable |
| **A3** | **the instrument's own blind spot, measured rather than assumed** — AST-sweep every `test_*` function for a to-be-deleted product symbol and partition against A1's impacted set | **measured** — **66 distinct functions name a deleted product symbol and are NOT in the 160** (§8.4a). `CliBackend` alone has **37 test readers, 0 of them impacted**. A1 cannot see source-reading, `__all__`-auditing or sha-pinning tests **by construction**, because they never dispatch |

| **A4** | **the armed-tripwire census (r3).** `AG1`'s skeleton transcribed **verbatim** from §9 into a scratch pytest plugin, run armed **and** with `cli` unselectable, recording `item.nodeid` from a `pytest_runtest_makereport` hook whenever the raised value carries the tripwire sentinel | **measured** — **51 distinct tests reach `CliBackend._run`.** Batch A **18** (all `test_invocation.py`), batch B **33** (27 `[cli]` legs + **1 `[sdk]` leg** + 5 non-parametrized), batch C **0**. Positive control: armed alone on `tests/test_invocation_sdk.py` → **1 failed, 82 passed**, the single failure being `test_ou3` (`:1578` drives a real `CliBackend`), which proves the fixture arms, fires and restores. Full member list in §10.1 |

A1 is the evidence that this unit's blast radius is 160 tests and not 88. A2
is the evidence that it is concentrated in four behaviour files, which is what
§4's shape decision rests on. **A3 is the correction to r1's method:** r1
treated A1 as the complete blast radius, and it is not — it is the *dispatch*
blast radius. Any criterion or count derived from A1 alone under-reports by
the 66.

### The unit's own mutations — all `predicted`

| # | Mutation | Must fail | Basis |
|---|---|---|---|
| **M-1** | `_resolve` treats `"cli"` as an unknown value instead of raising the retired message | **SEL1, SEL5** | *predicted* — SEL5 is the discriminator; without it M-1 is invisible |
| **M-2** | `_resolve` returns the SDK backend for `"cli"` instead of raising (the "ignore it" alternative §5 rejected) | **SEL1, SEL2, SEL3, SEL4** | *predicted* — this is the mutation that must not pass, because it is the plausible shortcut |
| **M-3** | `backend_for` rung 5 keeps `.get(surface, "cli")` | **SEL5** (an unknown surface resolves to a refusal instead of sdk) | *predicted* |
| **M-4** | `provider._fold_backend` keeps folding unknown → `"cli"` | **SEL6** | *predicted* |
| **M-5** | `options_kwargs` reads `spec.doctrine` but the analyst call site still passes `None` | the analyst doctrine test in `test_u_sdka.py` (`build_argv` recomputation, `:1420-1429` today — re-expressed against `doctrine`) | *predicted* — this is §2.3's silent-failure shape and the single most dangerous mutation in the unit |
| **M-6** | `FakeBackend` keeps `.argvs` as an empty list instead of `.doctrines` | the re-expressed `test_t1c` + `test_composer.py::a12b` | *predicted* |
| **M-7** | `miner._invoke_reader` still calls `write_reader_settings` (dead settings write survives) | a new `test_reader_contract.py` test asserting the spool contains **only** the artifact after a run (`RC1` already has the shape) | *predicted* |
| **M-8** | one `[sdk]` leg's assertion weakened during the parametrization collapse (e.g. `assert x == y` → `assert x`) | **CV2**'s body-diff criterion | *predicted* — instrument criterion; a gate must read the diff, not re-run the suite |
| **M-9** | mutate one character of `_ANALYST_TEMPLATES.timed_out` | **CV3** / `test_ou3`'s byte-pin | *predicted* — proves the byte-pin replaced the dead differential leg. *Note: `test_ou3`'s surviving `setitem` leg does NOT catch this — it mutates the table itself, so a mutated shipped table still "changes the emitted line" and stays green. The byte-pin is the only detector, which is exactly why `RO-6` is a precondition and not a nicety* |
| **M-10** | `KNOWN_BACKENDS = ("sdk", "cli")` left as-is while `cli.py` is deleted | **CL3**, and an `ImportError` at first `cli` selection | *predicted* |
| **M-11** | **inverted at r2.** Delete `TRANSPORT` outright — r1's own §8.2 instruction | **`u_sdka::test_hd4_seam_is_total_on_the_analyst_surface` / `invocation_sdk::test_ou5_bare_oserror_caught_on_worker_miner_and_analyst`**, plus an `ImportError` at `invocation_sdk/backend.py:41` | *predicted* — `BLOCKER-1`. This is the mutation r1's spec *prescribed as the design*; it must be RED |
| **M-16** | trim `TRANSPORT` correctly but set `catches_os_error=False` for the analyst — the `M11` edit `03-decisions.md:62` records | **`test_ou5`** (the analyst's bare `OSError` must escape) and `test_u_sdka.py:1025` | *predicted* — **this is S-48's own evidence, and it must stay reproducible after the trim.** If M-16 is green, the trim relocated the flag somewhere unmutable and S-48 lost its proof |
| **M-17** | install `AG1`'s tripwire but never arm it (assign `_tripped` to a local, not to `CliBackend._run`) | **`AG2`** (the negative control) | *predicted* — without `AG2` this mutation is invisible and A's whole gate is fail-open |
| **M-18** | `resolve_backend_name` left folding `cli` → `"sdk"` silently while `registry._resolve` refuses | **`SEL6`, `SEL7`** | *predicted* — `MAJOR-5`. The doctor reporting a refused selection as accepted is the exact defect |
| **M-19** | strip `test_rc7`'s `[sdk]` branch to `assert run.spec.prompt == big_prompt` and delete the `[cli]` leg — the "obvious" collapse | **`CV2` clause 3, `CV8`** | *predicted* — `BLOCKER-5`. Nothing in r1's CV2 would have caught this; the suite stays green and the reader loses its wire assertion |
| **M-12** | `worker.build_argv` left in place and still exported | **CL1** is silent (no `CliBackend` string); needs its own grep criterion | *predicted* — **this mutation exposes a hole: add CL9** |
| **M-13** | delete a migrated behaviour test rather than migrating it | **CV1**'s reconciliation | *predicted* — instrument criterion; the arithmetic is the only detector |
| **M-14** | `pyproject.toml` gains `claude-agent-sdk` in `dependencies` **and** the extra is dropped | **DEP2** | *predicted* |
| **M-15** | conftest's three pins deleted but a module-level `setenv("SELF_LEARN_BACKEND_WORKER", "cli")` added to one test file instead | **SEL1** at that file, and **CV7** stays green — needs `CL8` widened to a repo-wide grep | *predicted* — **exposes a second hole: widen CL8** |

**Holes the mutation pass found, all folded into §9 as written:** `CL9`
(dead-export grep), `CL8` widened to a repo-wide `"cli"` grep, `CL10` (deleted
symbols as **strings**, for `test_lock_invariant.py:148`), `AG2` (the
tripwire's negative control), `SEL7` (`test_fl5` extended rather than
weakened), `CV2` clause 3 (no assertion may collapse to a `SessionSpec`-field
tautology), `CV8` (the reader's wire assertion).

**One r1 mutation inverted (`M-11`).** r1 listed "TRANSPORT left in
`contract.py` (unused)" as a mutation that `CL5` must kill. Measured, the
opposite is true: `TRANSPORT` is read by the surviving backend, so *deleting*
it is the defect and *keeping the trimmed table* is correct. A mutation table
that points a gate at the wrong direction is worse than no row, because a
conscientious builder follows it.

### 10.1 `A4` — the armed-tripwire population A must eliminate (NORMATIVE)

**51 tests.** Every one must be migrated, collapsed or rewritten before `AG1`
can arm green. This list is `A`'s work order; a builder who reduces it to 0 by
any means other than the dispositions below has not satisfied `CV1`.

**Batch A — 18, all `tests/test_invocation.py`** (U-seam's own transport
suite; every one drives `CliBackend` directly, and every one's subject is the
subprocess transport):

`av3_settings_writer_called_before_argv_builder` · `av4_transport_kwargs_input_presence` ·
`fk2_each_fakestep_matches_clibackend_for_the_same_failure` ·
`lg1_twelve_byte_identical_log_lines` · `lg2_repair_label_appears_only_in_repair_lines` ·
`lg3a_worker_g_format` · `lg3b_miner_no_g_format` · `lg3c_timeout_display_is_actually_read` ·
`lg5_detail_rendering_per_surface` · `lg6_clean_invocation_logs_nothing` ·
`tr1_surfaces_reach_the_right_transport` · `tr2_miner_popen_kwargs` ·
`tr3_miner_timeout_killpg_and_wait` · `tr4_bare_os_error_is_caught_on_analyst_worker_and_miner` ·
`tr5_cwd_passed_for_every_surface` · `tr6_argv_positional_timeout_keyword` ·
`tr7_transport_reached_through_the_subprocess_module_attribute` · `wr4_outcome_stdout_per_surface`

*Disposition: the `TR*` and `AV*` rows are transport-mechanics tests whose
subject is deleted → **delete in B, unreached in A**. The `LG*` rows assert
log-line rendering, which survives in `LOG_TEMPLATES` → **re-base onto the SDK
backend in A**; `lg1_twelve_byte_identical_log_lines` is the natural host for
`RO-6`'s byte-pin. `fk2` compares `FakeBackend` against `CliBackend` per
failure kind → **re-base onto `FakeBackend` vs `SdkBackend`**.*

**Batch B — 33** (`tests/test_worker_contract.py`, `tests/test_u_sdka.py`,
`tests/test_invocation_sdk.py`):

- **27 `[cli]` legs** — `u_sdka`: `ac1`–`ac8`, `hd1`, `hd3`, `hd4`;
  `worker_contract`: `bg1`, `fl1`, `fl2`, `fl3`, `ha3`, `ha4`, `pb2`, `pb4`,
  `rp2`, `rp3`, `to1`, `to2`, `to3`, `ws1`, `ws4`, `ws6`. → **collapsed by
  `CV2`** (this is why §4's "deletes nothing" was impossible).
- **1 `[sdk]` leg** — `worker_contract::test_fl2_byte_identity_and_provenance[sdk]`.
  → **`BLOCKER-B`'s worked case; disposition in §8.4b.**
- **5 non-parametrized** — `u_sdka::ar4_byte_identity_under_the_rollback`,
  `u_sdka::hd7_prompt_leaves_the_process_table`,
  `worker_contract::bg2_cli_prompt_delivered_intact_on_stdin`,
  `worker_contract::hy5_cli_side_no_real_claude_control`,
  `invocation_sdk::test_ou3_…`. → `ar4` **delete** (its subject, the env-var
  rollback, ceases to exist — §5); `bg2` **delete** (replaced by `bg3`);
  `hy5` **delete**; `hd7` **re-base onto the SDK process table**; `test_ou3`
  **rewrite to `T-SDK-NOT-FOUND-WORDING`** (`CV3`).

**Batch C — 0.** The population is bounded to batches A and B; the remaining
1689 tests reach `CliBackend` by no route.

---

### 10.2 Unmutated-test census

Partitioning §9's **38** criteria against §10's **19** mutations. The
partition is exhaustive: every criterion appears exactly once below.

**Covered by ≥ 1 mutation — 21 criteria across 19 table rows** *(r2 said 24;
recount: the table holds 19 rows and one of them carries three criteria,
SEL2+SEL3+SEL4, so 18 + 3 = 21)*:

| Criterion | Killing mutation(s) |
|---|---|
| SEL1 | M-1, M-2, M-15 |
| SEL2, SEL3, SEL4 | M-2 |
| SEL5 | M-1, M-3 |
| SEL6 | M-4, **M-18** |
| SEL7 | **M-18** |
| AG1 | **M-17** (via AG2) |
| AG2 | **M-17** |
| CL1 | M-12 (partially — CL9 is its complement) |
| CL3 | M-10, **M-18** |
| CL5 | **M-11**, **M-16** |
| CL8 | M-15 |
| CL9 | M-12 |
| CL10 | M-13 (the arithmetic detector) |
| CV1 | M-13 |
| CV2 | M-8, **M-19** |
| CV3 | M-9 |
| CV6 | M-5 (adjacency) |
| CV8 | **M-19** |
| DEP2 | M-14 |
| — | plus the two `test_reader_contract` additions from M-7 and the doctrine test from M-5 |

**Deliberately unmutated — 17** *(r2 said 14; the list below has always held
17)*. **Per the gate's ruling on this section, every entry now carries either
the literal command whose output goes into the build report, or an explicit
`HUMAN READS THE DIFF` label.** A criterion sentence with no runnable line
cannot be discharged mechanically even in principle, and 10 of these 17 had
none:

1. **CL2, CL4, CL6, CL7** — file-existence and grep criteria. The "mutation"
   is *not doing the deletion*, which every other criterion in the same commit
   already detects. Mutating them teaches a gate nothing it does not learn
   from CL1. **Discharge commands** (run from `plugins/self-learn/cli`, rc
   captured unpiped):

   - `CL2` — `test ! -e src/self_learn/invocation/cli.py; echo rc=$?` **and**
     `git log --diff-filter=D --name-only -1 -- src/self_learn/invocation/cli.py`
   - `CL4` — `grep -rn "subprocess" src/self_learn/invocation/ | wc -l` → `0`
   - `CL6` — `test ! -e tests/shims.py; echo rc=$?` **and**
     `grep -rn "shims" tests/*.py | grep -v __pycache__ | wc -l` → `0`
   - `CL7` — `grep -n "cli_" src/self_learn/invocation/contract.py` → no field
     line; **positive control:** the same grep at `ee0d671` prints `:192` and
     `:193`, so an empty result on a stale checkout is distinguishable from a
     pass
2. **AG3** — **`HUMAN READS THE DIFF`.** Its omission is *also* detected by AG1
   (the tripwire cannot be green while the pins still force `cli`), but the
   ordering claim — that the unpin lands in A and not B — is a diff fact, not a
   command.
   **AG4** — **discharged by a published measurement**: the literal
   `env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT uv run pytest
   --collect-only --color=no -q | tail -1` from `plugins/self-learn/cli` at A's
   merge commit, pasted into A's build report with that commit sha. CV1 cannot
   reconcile without it.
3. **CV4, CV5** — **discharged by a published measurement**: CV4 by naming the
   four real-SDK-subprocess tests (one per surface) with their node ids; CV5 by
   naming the `RO-1`…`RO-4` knob tests and pasting their passing node ids.
   **CV7** — mechanically checkable, command already in the criterion:
   `uv run pytest --fixtures-per-test --color=no -q | grep -cE "^claude_(cli_)?shim"`
   → `0`, valid only if the run's tail reads `no tests ran`.
   **DOC1, DOC2, DOC3, DOC4** — **`HUMAN READS THE DIFF`.** Prose in
   `03-decisions.md` and `17-invocation-runbook.md`; no command can assert that
   §6 of the runbook *means* "rollback is a revert". This is U-fake's `R-6`
   exposure repeating, and the conclusion is the same: **a gate must read the
   build report and the docs diff, not only re-run the suite.**
4. **DEP3, DEP5** — no command needed: shipped tests go red on their own
   (`test_rs7`, `test_rs8`, `test_rg5`). **DEP1** —
   `sed -n '/^dependencies = \[/,/^\]/p' pyproject.toml | grep -c claude-agent-sdk`
   → `1`. **DEP4** —
   `git diff ee0d671 -- uv.lock | grep -E '^[+-]name = |^[+-]version = ' | wc -l`
   → `0`, i.e. no package added/removed and no version changed.

**The exposure this census names, plainly.** Corrected counts:

| Class | Count | How a gate discharges it |
|---|---|---|
| Killed by a mutation | **21 / 38 (55 %)** | re-run the suite under §11.0 |
| Mechanically checkable without pytest | **9 / 38** | CL2, CL4, CL6, CL7, CL9, CL10, CV7, DEP1, DEP4 — every one now carries its literal command |
| Discharged by a published measurement | **3 / 38** | AG4, CV4, CV5 |
| `HUMAN READS THE DIFF` | **5 / 38 (13 %)** | DOC1–DOC4, AG3 — irreducible |

**Re-running the suite verifies 21 of 38 (55 %); the non-suite-falsifiable
residue is 17 of 38 (45 %).** r1 undercounted this at 12/30 and r2 at 14/38.
Only the last row is irreducible — the other 12 are now runnable, which was the
gate's ruling on this section and is the fix, not a redesign.

---

## 11. Tests

### 11.0 Runbook — run every suite under a neutralised environment

**Always, from `plugins/self-learn/cli` (or `plugins/self-learn/ui`):**

```
env -u SELF_LEARN_ANALYST_MODEL -u SELF_LEARN_ANALYST_TIMEOUT \
  uv run pytest --color=no -q
```

An interactive shell on this host exports `SELF_LEARN_ANALYST_MODEL` and
`SELF_LEARN_ANALYST_TIMEOUT`; both leak into
`provider.model_for("analyst", …)`. With them set, **eight tests fail**
(`test_u_sdka.py` ×4, `test_invocation.py` ×2, `test_route_cli.py` ×2) — every
one a test that configured a sentinel model and got the exported value.
**This is host-environment contamination, not a regression in the tree.**
Measured neutralised at `ee0d671`: `2394 passed, 8 skipped`, rc 0, 369.27 s
(358.73 s at `73cd996`).

Capture the exit status **unpiped** — `cmd > out.txt 2>&1; echo rc=$?` — never
`cmd | tail`, which reports `tail`'s status and prints `rc=0` over a red run.
The full suite takes ~6 minutes; a 400 s tool bound will kill it. Batch by
file, or raise the bound.

**Census positive control.** `--fixtures-per-test` run from the wrong
directory prints every count as `0` with a tail of `39 errors` — identical in
shape to a genuine zero. A census run is valid only if its tail reads
`no tests ran in …`.

### 11.1 New tests

| id | File | Assertion |
|---|---|---|
| **T-CLI-REFUSED-ENV** | `tests/test_invocation.py` | `SELF_LEARN_BACKEND_ANALYST=cli` → `text_session` returns `failure="unavailable"`, never raises, logs the analyst template byte-for-byte (SEL1) |
| **T-CLI-REFUSED-ALL-SURFACES** | same | the four surfaces, their three templates (SEL2) |
| **T-CLI-REFUSED-COARSE** | same | `SELF_LEARN_BACKEND=cli` (SEL3) |
| **T-CLI-REFUSED-CONFIG** | same | `invocation.backend_worker: cli` in `config.yaml`; the message names that key (SEL4) |
| **T-UNKNOWN-STILL-SDK** | same | `SELF_LEARN_BACKEND=banana` → generic warning, resolves **sdk**, exit 0 (SEL5) — the discriminator M-1 needs |
| **T-DOCTOR-SWITCHES** | `tests/test_doctor_invocation.py` | the `switches` row on a clean env and under a `cli` selection (SEL6) |
| **T-DOCTRINE-REACHES-SDK** | `tests/test_u_sdka.py` | the analyst's `doctrine_text` arrives as `options.system_prompt["append"]`, driven from `analyst.analyze`'s real call site, not a hand-built spec (M-5) |
| **T-NO-DEAD-SETTINGS-WRITE** | `tests/test_reader_contract.py` | after a reader run the spool holds only the artifact, and no settings JSON was written anywhere under the cache dir (M-7) |
| **T-FAKE-ARGV-PER-CALL** | `tests/test_invocation_sdk.py` | `RO-1` — two invocations, two argv records (CV5) |
| **T-FAKE-PROMPT-LOG** | same | `RO-2` (CV5) |
| **T-FAKE-MULTI-WRITE** | same | `RO-3` (CV5) |
| **T-FAKE-PER-CALL-ERROR** | same | `RO-4` — round 1 clean, round 2 error (CV5) |
| **T-TEMPLATES-BYTE-PINNED** | same | **[A]** `RO-6`: every row of all three `LOG_TEMPLATES` sets byte-pinned, captured while `CliBackend` still exists; `M-9` reddens it (CV3) |
| **T-SDK-NOT-FOUND-WORDING** | same | **[B]** the `not_found` wording `test_ou3:1585` used to pin through `CliBackend` is re-asserted through the SDK's own not-found leg (`CLINotFoundError`, `backend.py:465-469`), extending `test_ou1`'s existing row (`:1473`, `:1493-1494`) from a shape assertion to a wording assertion (CV3) |
| **T-READER-PROMPT-ON-THE-WIRE** | `tests/test_reader_contract.py` | **[A]** `RO-7`/`CV8`: replaces `test_rc7`'s `[sdk]` branch. Spy `ClaudeSDKClient.query` (the `test_bg3` pattern, `worker_contract:1654-1680`); assert the 200 KiB prompt arrives on the wire **and** appears in no element of the child's own argv via `FAKE_CLAUDE_ARGV_LOG`. Both halves of "on stdin, never argv" hold against the surviving transport; **`M-19` must redden it** |
| **T-CLI-BACKEND-TRIPWIRE-FIRES** | `tests/conftest.py` + `tests/test_invocation.py` | **[A]** `AG2`: calling `CliBackend().write_session(...)` directly raises the tripwire's `AssertionError`. Without it, an unarmed tripwire (`M-17`) reads identically to a fully migrated suite |
| **T-TRANSPORT-FLAG-STILL-MUTABLE** | `tests/test_u_sdka.py` | **[B]** `CL5`/`M-16`: the trimmed `catches_os_error` carrier is still readable and mutable at the table (`test_u_sdka.py:1025`'s assertion, re-spelled), so `S-48`'s `M11` evidence stays reproducible |
| **T-COMPOSER-ANALYST-FAILS** | `tests/test_composer.py` | `RO-5` / U-fake `R-5` — an analyst failure leg through the seam's dispatch and log rendering, on `FakeBackend` (CV6) |

### 11.2 Tests rewritten, not deleted

`test_ou3` (§3.4) · `test_rs7`, `test_rs8` (§6) · `test_t1c_move1_tests_keep_the_argv_shape_assertions`
and the other 20 `.argvs` sites (§7) · `test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`
(§13.2, U-fake `R-7`) · every `[sdk]` leg's parametrization collapse (CV2).

---

## 12. Operator-facing surface

No verb is added and no exit code changes. The two operator-visible changes:

| Surface | Before | After |
|---|---|---|
| `SELF_LEARN_BACKEND*=cli` | selects the subprocess transport | logged refusal per surface; the run fails with `failure="unavailable"` and the surface's normal downstream handling (worker: the batch is skipped and logged; analyst: `AnalystError` → capture-to-pending, exit 4) |
| `self-learn doctor` `switches` row | `backend=cli (env:…)` possible | `backend=sdk` always, or a named refusal |
| rollback | `export SELF_LEARN_BACKEND=cli` | **a git revert** — there is no runtime rollback (§5, DOC3) |

---

## 13. Scope

### 13.1 IN

1. Deleting `CliBackend`, the transport table, the argv builders, the settings
   writers and the two `SessionSpec` closures (§7, §8.1, §8.2).
2. The `doctrine` field and its three call sites.
3. The retired-backend refusal and every fallback that named `cli` (§5).
4. `claude-agent-sdk` → hard dependency; the extra retained as an alias (§6).
5. Deleting `tests/shims.py`, both shim fixtures, the `claude_shim` alias, the
   two remaining inline shim scripts, and conftest's three pins (§8.3).
6. Migrating the ≈ 109 behaviour tests (§3.4(b), §8.4) and the `RO-1`…`RO-5`
   fixture work that makes migration possible.
7. **U-fake `R-1`** — the `Compat-1` alias and `test_invocation.py`'s 19
   `claude_shim` occurrences. *Note the register's framing changes:* `R-1`
   anticipated a **rename** costing `HY1`'s diff leg + `SU2` + `FX4`'s
   importer leg (U-fake `M25`, restated at register `:1634` after the gate
   found `M25`'s "suite green" claim false — `FX4` and `SU2` also redden).
   Measured here: only **7** tests request the alias and all 7 are among the
   160 impacted. **The rename never happens** — the alias and its users are
   deleted with the fixture, so `M25`'s three-criterion price is not paid;
   `FX4` is deleted rather than re-baselined, exactly as `R-1` anticipated
   (*"U-cleanup deletes `FX4` with the alias"*).
8. **U-fake `R-2`** — the four `claude`-shim scripts become zero.
9. **U-fake `R-5`** — the analyst failure-leg gap (`RO-5`, `CV6`,
   T-COMPOSER-ANALYST-FAILS).
10. **U-fake `R-7`** — `test_attrib.py::test_hy1_no_test_in_the_suite_invokes_a_real_claude`,
    whose `B-2` legs are a raw source search over `inspect.getsource` that the
    shim's own docstring defeats. The shim is deleted here, so the test's
    subject changes anyway. Rewrite it to guard the SDK-side property that
    `conftest.py::_no_real_sdk_spawn_tripwire` already enforces at runtime.
11. `03-decisions.md`'s new row + the `S-43` amendment; the
    `17-invocation-runbook.md` rewrite (§8.5, §16).

### 13.2 OUT, with reasons

| # | Item | Why out | Owner |
|---|---|---|---|
| 1 | **`U-engine`** — extracting a shared SDK core from `ui/src/self_learn_ui/engine/` and `cli/src/self_learn/invocation_sdk/` | The user's target of record (2026-08-20: *"unify the backend and have all agents operate on top of the sdk"*) decomposes into (a) the flips, (b) U-cleanup, (c) U-engine — and the register (`:3108-3125`) records U-engine as a **separate later unit**, deliberately sequenced after the analyst burn-in because burn-in findings may perturb `invocation_sdk`. **The boundary:** U-cleanup may delete from `invocation/` and edit `invocation_sdk/` only where the closure removal forces it (§8.1's last row, §8.2's `options_kwargs` edit). It may not restructure `invocation_sdk`, may not touch `ui/`, and may not introduce a shared module. Verified 2026-08-24: the UI references the invocation seam **nowhere** (`grep -rn "SELF_LEARN_BACKEND\|CliBackend" plugins/self-learn/ui/src` → 0), so the boundary is clean today and U-cleanup must leave it that way | `U-engine` |
| 2 | Improving the SDK backend's behaviour | §1 non-objective | `U-engine` / its own unit |
| 3 | Raising the `claude-agent-sdk` lower bound from `>=0.2.116` to the plan's `>=0.2.121` | a version decision riding a deletion diff is how a version decision goes unreviewed; the plan itself says *"SDK bumps are their own gated unit"* (`:246`) | its own unit |
| 4 | U-fake `R-3` (`shims.py` vs `support.py::failing_git_shim` are two homes for one idea) | `shims.py` ceases to exist here, so half the residual evaporates; consolidating what remains is a `support.py` edit with no connection to the invocation seam | forward-work map (unowned) |
| 5 | U-fake `R-4` (three merged spec drafts name `claude_shim` in prose) | rewriting a merged spec's prose to match a later rename is how a spec corpus stops being a record — U-fake's own reasoning, unchanged | none; deliberate |
| 6 | U-fake `R-8` (`DS1`'s `BASE_REF` git constant) | this unit deletes or re-baselines `DS1` (§8.4); if it survives, its `BASE_REF` moves to this commit — the residual is discharged, not inherited | discharged here |
| 7 | The `test_batch_fixes.py` Popen mock (window spawner) | a different `Popen`, named out-of-scope in every brief of this campaign. Its 1 impacted test in §3.3 batch C is collateral from the pin removal, not from the transport | none |
| 8 | The compiler-side cross-scope recompile defect (register tail, Route 10 HELD) | deterministic CLI code, backend-independent; not an invocation-seam defect | its own gated unit |
| 9 | Re-enabling `enable_auto_refresh`-style automation, telemetry changes, verb changes | nothing here touches them | — |

### 13.3 Register rows this spec resolves

All **10** `U-cleanup` mentions in `misc/r2-progress.md`, folded:

| Register line | Content | Disposition |
|---|---|---|
| `:1396` | *"alias dies in U-cleanup — the freeze was wave-scoping, not corpus law"* (V-1) | **IN** — §13.1(7); the alias dies by deletion, not rename |
| `:1398` | *"T3 backlog owned by U-cleanup per plan"* (V-2) | **IN** — §3.4/§8.4; the backlog is 142 tests, not 88, and ≈ 109 of them migrate rather than die |
| `:1575` | *"U-cleanup owner of R-1/R-2/R-5; R-1 → M25 as go/no-go evidence"* | **IN** — §13.1(7)(8)(9) |
| `:1634` | *"M25's 'suite green' claim FALSE (FX4 importer leg + SU2 also redden) and it is U-cleanup's quoted go/no-go evidence → restate M25/§10/R-1"* | **RESTATED** — §13.1(7). The correction is honoured and then made moot: the rename M25 priced never happens |
| `:2106`, `:3098` | Wave-3 sequencing behind burn-in | **SUPERSEDED** — the soak is waived (register `:3237`); §3 is the replacement bar |
| `:3108-3125` | U-cleanup deletes the CLI path; U-engine is a NEW separate unit | **BOUNDARY STATED** — §13.2(1) |
| `:2514` | *"R-1's U-cleanup case now two facts"* — `_miner_argv`'s model default also drifted to `"claude-haiku-4-5"` | **FOLDED** — `miner`'s argv builder is deleted entirely (§8.1), so the drifted default is deleted with it. **No separate fix is owed**, and a builder must not "correct" the literal on the way out |
| **`:3241`** | the **waiver line itself** — *"the U-cleanup spec must carry the coverage gap analysis (what T3's 88 bash-shim tests uniquely guarded vs sdk-side coverage: test_invocation_sdk 80, test_u_sdka 38, test_u_fake 17)"* | **DISPOSITIONED at r2 (was missing).** The obligation is discharged by §3. **Its three sdk-side counts are stale** — measured **83 / 49 / 17**, not 80 / 38 / 17 — and its "88" is the plan's wrong T3 figure (actual **142**). §3.2 now records the correction explicitly instead of silently using better numbers. The register row should be amended when it is next touched; this spec does not edit the register |
| **`:3250`** | *"U-cleanup spec author dispatched."* | **DISPOSITIONED at r2 (was missing)** — a dispatch record, no obligation |

*(r1 claimed to disposition "every `U-cleanup` mention" and covered 8 line
numbers across 7 rows. Measured: **10 mentions**. The two it missed are above,
and one of them is the waiver row that defines this unit's bar — the most
consequential line in the register for this spec.)*

---

## 14. The dated decision row

To be added to `docs/specs/self-learn/03-decisions.md` after `S-48`:

> **S-49** | **The `cli` invocation backend is RETIRED: every surface runs on
> the Agent SDK, and there is no second transport.** `CliBackend`,
> `invocation/cli.py`, the CLI-only fields of the `TRANSPORT` table
> (`kind`, `kills_process_group`, `prompt_via_argv`, `result_stdout` — the
> table itself is TRIMMED, not deleted; see below), the three argv builders
> (`worker.build_argv`, `analyst.build_argv`, `miner.build_reader_argv`), the
> two settings writers (`worker.write_settings_file`,
> `miner.write_reader_settings`) and the two `SessionSpec` closures
> (`cli_argv_builder`, `cli_settings_writer`) are deleted; `SessionSpec`
> carries a first-class `doctrine` field in their place.
> `KNOWN_BACKENDS == ("sdk",)`, and a `cli` selection at any rung is a NAMED
> REFUSAL — `BackendUnavailable` carrying a retirement message, surfaced as
> `Outcome(failure="unavailable")` through the surface's own log template,
> never raised. **The precondition changed under this decision and the change
> is recorded, not hidden:** the plan gated retirement on *"14 consecutive
> all-sdk days"*; on **2026-08-24** the user waived the soak — *"as long as we
> have decent test coverage, then skip the soak; 2 weeks is crazy-town"* — and
> the bar became a measured coverage census. That census (spec §3) found the
> plan's own figure for the T3 armor wrong (**142** bash-shim tests, not 88;
> **43** cross-backend contract pairs, not 16), found that **≈ 90 %** of the
> armor tests are worker/repair/attribution behaviour tests rather than
> transport tests — so they were **migrated onto the SDK fake CLI, not
> deleted** — and priced the one real loss, after two
> misidentifications worth recording. The census first named
> `test_ou3_failure_legs_render_byte_identical_to_clibackend…` as the dying
> cross-backend oracle; read line by line, that test **contains no differential
> assertion at all** (its SDK log list is captured and never asserted; its two
> model-driven legs exercise different `LOG_TEMPLATES` rows). Concluding from
> that "there is no oracle" was the second error: **`test_worker_contract.py::
> test_fl2_byte_identity_and_provenance[sdk]` (`:1394`, `:1398`) is one** — it
> drives a fresh CLI pass from inside the `sdk` leg and asserts the two
> backends' log lines are byte-identical on timeout, not-found and unavailable.
> That comparison, and only it, is what the deletion costs; the test's
> provenance-and-shape assertions survive on the `sdk` leg alone. The
> replacement is a byte-pin over **every** row of all three template sets,
> captured while `CliBackend` still exists — broader than the three kinds the
> comparison covered, and independent of a second transport existing to compare
> against.
> **`TRANSPORT` was NOT deleted:** its `catches_os_error` field is folded by
> `invocation_sdk` and is the table-level mutation point `S-48`'s recorded
> `M11` evidence depends on, so the table was trimmed to that one surviving
> field rather than removed. One production datapoint
> stands behind the flip and is not more than that: the first SDK miner run,
> **2026-08-24 19:20–19:24 PDT**, `ok — 7 landed`, 4 m 07 s, 586 MB peak, 0
> orphans, volume in band. **The cost, stated plainly: rollback is no longer
> an environment variable. It is a revert.** `17-invocation-runbook.md` §6
> says so in its own voice. | *Amends `S-43`* — `claude-agent-sdk` moves from
> optional extra to hard dependency; the extra is retained as an empty alias
> so `pip install 'self-learn-cli[sdk]'` keeps working. `S-43`'s premise was
> *"a machine that never leaves `backend=cli` pays none of it"*; there is no
> such machine after this row. *Amends `S-39`* — its first consequence (*"the
> default at every rung stays `cli`"*) lapsed at U-flip (2026-08-23) and is
> now structurally impossible. `S-34`'s seam, `S-35`'s precedence chain,
> `S-47`'s per-surface defaults and `S-48`'s never-raises contract all
> **survive unchanged** — the chain now resolves one backend instead of two.
> **`S-48` survives *because* `TRANSPORT["<surface>"].catches_os_error`
> survives** (in trimmed form): the retired-backend refusal is raised inside
> `registry._resolve` and caught by `_dispatch`, so nothing escapes the seam,
> and the analyst's OSError split remains mutable at the table where `M11`
> measured it.

And, on `S-43`'s own row: *Amended 2026-08-\_\_ (U-cleanup, `S-49`): the
condition this row rests on — that a machine can stay on `backend=cli` — has
lapsed. The SDK is a hard dependency.*

---

## 15. Questions routed upward — ALL RULED (2026-08-24)

The orchestrator ruled all four at gate-dispatch time. They are recorded as
settled; a builder must not reopen them.

**`Q-1` — one unit or two? RULED: SPLIT.** `U-cleanup-A` (migrate the ≈ 109
behaviour tests, unpin conftest, arm `AG1`'s tripwire, land `RO-1`…`RO-7`,
publish the `AG4` anchor) ships first; `U-cleanup-B` (the deletion) ships
second. §9's `[A]`/`[B]` tags are therefore **normative**, not advisory.

*r1's stated rationale for the split partly rested on preserving a
differential oracle across the migration. §3.4 retracts that oracle — it never
existed. **The ruling stands on the surviving reasons**, which are stronger
without it: (i) 27 T2 tests and 66 out-of-blast-radius tests need per-test
dispositions that are reviewable only as their own diff; (ii) `AG1`'s
"green with the CLI path unreachable" is a real, runnable completion gate that
a combined unit could not run, because in a combined unit the path is already
gone; (iii) `RO-6`'s byte-pin and `RO-7`'s wire assertion must be constructed
while the `[cli]` leg still exists to check them against.*

**`Q-2` — may the ≈ 109 behaviour tests be deleted if migration proves
expensive? RULED: NO — migrate, never delete.** `CLAUDE_SHIM_SCRIPT` has 180
use sites across 9 files, so the cost is real and the ruling is made with that
number in view. Deleting them is a `CV1` failure.

**`Q-3` — the `[sdk]` extra after the hard-dependency move? RULED: keep it as
an empty alias**, so `pip install 'self-learn-cli[sdk]'` — printed at
operators by three shipped tests and the runbook — keeps working. `DEP2`.

**`Q-4` — the in-flight analyst burn-in? RULED: let it finish; do not
restart it.** The soak waiver covers the 14-day precondition, not an
in-flight burn-in that has already surfaced one real product finding. Not
spec-blocking.

### 15.1 Open for the builder to measure, not for the orchestrator to rule

- **`RO-3`'s sizing.** 180 `CLAUDE_SHIM_SCRIPT` sites is the upper bound on
  the migration, not an estimate of it; many are repeated knob-sets within one
  test. A builder should measure distinct *script bodies* before choosing
  between extending `ok_write_real` and adding a scenario.
- **§8.2's provider-refusal shape.** Ruled to option (a) — a third tuple
  element — but the exact field name and `Row` rendering are the builder's,
  subject to `SEL6`/`SEL7`.

---

## 16. Docs to update in the same commit

| File | Change |
|---|---|
| `docs/specs/self-learn/03-decisions.md` | `S-49` (§14); dated amendments on `S-43` and `S-39`. **`S-48` (`:62`) gains a one-line dated note** (`N2`): its recorded `M11` evidence names `TRANSPORT["analyst"].catches_os_error`, and U-cleanup trims that table — the note records the new spelling so the evidence stays locatable. **`S-48`'s substance is unamended**; leaving the row silent while renaming the symbol it cites is how a decision record decays into a dead reference |
| `docs/specs/self-learn/17-invocation-runbook.md` | §1 two switches → one · §2 the extra is no longer optional · §4.2/§4.3 flip sections deleted or reduced to the provider switch · **§5.6 rewritten in past tense**, recording the waiver and the coverage census that replaced it · **§6 Rollback rewritten: rollback is a revert** · §7 traps re-verified against a one-backend world · §9 change-control entry |
| `docs/specs/self-learn/14-forward-work-map.md` | close the rows the deletion closes; **open a row for the lost env-var rollback** — the campaign's rollback story ends here and something should own noticing that |
| `docs/specs/self-learn/12-transcript-miner.md` | the one `claude -p` sentence |
| `docs/specs/self-learn/08-build-plan.md` | check and correct at build time |
| `plugins/self-learn/skills/self-learn/SKILL.md`, `plugins/self-learn/commands/*.md` | grep for `SELF_LEARN_BACKEND` before claiming no change is needed |

---

## 17. Revision history

- **r1, 2026-08-24** — first draft, authored against `73cd996`. Baseline
  measured (2402 collected / 2394 passed / 358.73 s, rc 0). Blast radius
  measured in three batches with a scratch pytest plugin that makes `cli`
  unselectable at every rung: **160 impacted tests**. Fixture census
  re-measured: **142** shim tests (plan said 88; U-fake measured 132 at
  `c2669a9`). T2 re-measured: **43** `[cli]`/`[sdk]` pairs (plan said 16).
  T3 subject-classified by AST + regex: **17 of 126** shim-signature tests
  *(corrected at r2 to **12 of 125** — the regex over-matched `notify-send`
  argv and the helper miscounted an indirect fixture request)*
  assert argv/settings at all. Three findings drive the shape — conftest's
  suite-wide `cli` pin (§2.2), the SDK backend's consumption of
  `cli_argv_builder` as its doctrine relay (§2.3), and the pre-existing
  sdk-side real-process harness `tests/fixtures/fake_claude.py` (§2.4). No
  repository file was created or edited to produce this document;
  `~/.self-learn` was never read or written. `Q-1` (one unit or two) is the
  one fork a builder cannot start without.
- **r2, 2026-08-24** — blind-gate fold (**NOT SOUND**: 5 BLOCKER, 5 MAJOR,
  6 DIVERGENCE, 2 NIT). The gate reproduced every headline measurement cell
  for cell (160, the per-module table, 142/118/17/7, 43/43, the conftest pins,
  180 shim sites, the doctrine-drop probe); **every finding was a code-reading
  error, and three were the same shape §2.3 had already discovered — the SDK
  silently consuming a CLI-flavoured artefact — found once and not swept for.**
  §8.0 is the sweep that closes the class.
  **BLOCKER-1:** `TRANSPORT` is read by `invocation_sdk/backend.py:41`/`:60` →
  `:485`/`:493`; r1's "only reader is `CliBackend._run`" was false and its
  "delete the table" instruction would have reopened `S-48` on the surviving
  backend. Redesigned to a per-field trim keeping `catches_os_error`; `CL5`
  rewritten; `M-11` **inverted**; `M-16` added so `S-48`'s `M11` evidence stays
  reproducible; §14 and §16 corrected.
  **BLOCKER-2:** only `analyst.build_argv:127` emits `--append-system-prompt`;
  r1's §7 would have **added** a system prompt to the worker that does not
  exist and duplicated text already in its prompt (`worker.py:1514`). §2.3.1
  added; worker and miner take `doctrine=None`.
  **BLOCKER-3:** 20 of 30 criteria were untagged and defaulted to `[B]`,
  contradicting `RO-6`. Now **38 criteria, all tagged, 10 [A] / 28 [B]**;
  `CV3` and `CL8` moved to `[A]`.
  **BLOCKER-4:** A had no runnable gate. `AG1`–`AG4` added, with a tripwire
  modelled on `conftest.py:23-24` and `AG2` as its negative control (`M-17`).
  **BLOCKER-5:** `CV2` was unsatisfiable — 27 T2 tests name deleted symbols,
  and `test_rc7`'s `[sdk]` leg collapses to a tautology. `CV2` rewritten in
  four clauses, §8.4b added with a per-test disposition, `RO-7`/`CV8`/`M-19`
  added.
  **MAJOR-1:** `test_ou3` has **no differential assertion** — retracted from
  §3.4 and, more importantly, from §14's permanent decision-record text.
  **MAJOR-2:** `not-found` is not moot under sdk (`cli_path` is `None` in
  production; `CLINotFoundError` → `backend.py:465-469`; guarded by
  `test_ou1:1473`).
  **MAJOR-3:** §8.4 did not partition — **66 tests** name a deleted product
  symbol and never fail under the §3.3 instrument, including two files r1
  never mentioned (`test_hosting.py:792`/`:822`, `test_miner.py:746`) and a
  *string*-keyed row (`test_lock_invariant.py:148`). §3.4(c), §8.4a, `A3`,
  `CL10` added.
  **MAJOR-4:** B's count must be gated against A's published anchor, not 2402.
  **MAJOR-5:** `provider.resolve_backend_name` is an independent transcription
  that never sees `BackendUnavailable`; `SEL6` was unachievable. §8.2's
  provider row rewritten, `SEL7` and `M-18` added, `CL3` widened beyond
  `invocation/`.
  **DIVERGENCEs:** batch B collects **457**; totals **2402 / 153 F / 7 E /
  2234 passed** (r1: 2401 / 3234, repeated in `A1`); `test_invocation_sdk`
  breakdown re-measured off node ids (CH 18, OP 17, KL 11, OU 8, RS 7, PL 6,
  EV 6, SY 5, HG 4, SU 1 = 83; r1's summed to 73); the T3 census is **125 / 18**
  by the stated method, and **6 of `test_worker.py`'s 7 hits are `notify-send`
  argv** — the true CLI-path share is **12 / 125 ≈ 10 %**, so the conclusion
  strengthens from ≈ 87 % to **≈ 90 %**; **10** register mentions, not 7 —
  `:3241` (the waiver row, carrying stale 80/38 → **83/49**) and `:3250` added;
  `uv.lock:150-151`, not `:158`; `test_u_fake.py` imports `shims` at **both**
  `:303` and `:383` (7 sites, not 6).
  **NITs:** `registry` line cites corrected (`_dispatch` `:100`, `except`
  `:116`, `_resolve` `:42`, rung 5 `:94`); §16 gains the `S-48` note.
  All measurements re-run at **`ee0d671`** under §11.0's environment, rc
  captured unpiped. Orchestrator rulings on `Q-1`…`Q-4` folded into §15. No
  repository file was created, edited or reverted other than this draft;
  `~/.self-learn` untouched.
- **r3, 2026-08-24** — second gate fold (**NOT SOUND**: 2 BLOCKER, 2 MAJOR,
  2 DIVERGENCE, 4 NIT; all 18 r1 folds verified present and correct, and the
  gate retracted its own r1 `D6` — the spec's "7 sites in 6 files" was right).
  Both new BLOCKERs land on `AG1`, the criterion written to close r1's
  BLOCKER-4, and both were found by **running** it rather than reading it.
  **BLOCKER-A:** the AG1 skeleton was transcribed verbatim and dry-run —
  it arms, fires and restores correctly, but armed over the suite it shows
  **51 tests reach `CliBackend._run`** (batch A 18, batch B 33, batch C 0),
  so §4's "A deletes nothing", `CV2` **[A]** (which collapses the 43 `[cli]`
  legs) and `AG1` **[A]** could not all hold. **Orchestrator ruling: option 1**
  — A deletes test legs and direct CLI drives only, zero product code; §4's
  cell corrected; the tripwire is explicitly **not** to be narrowed to
  registry-resolved dispatch, since that would leave the CLI exercised in A.
  New anchor **`A4`** (the armed-tripwire census) and new **§10.1** naming all
  51 with dispositions.
  **BLOCKER-B:** a fourth blind spot — `A1` measures dispatch, `A3` measures
  symbol-naming *inside a test body*, and neither sees a reference living one
  call-frame away. Worked case
  `worker_contract::test_fl2_byte_identity_and_provenance[sdk]`: its
  `build_argv` call is in `_drive_fl2_lines` (`:1342`) and its backend
  selection is re-set inside the test body after fixtures run, so it is
  invisible to both instruments and trips only the tripwire. New **§8.0a**
  measures the whole indirect population — `_spec` alone carries the two
  deleted closures into **58** test functions across two files; the `backend`
  and `reader_leg` fixtures carry `CliBackend` into 35 more. **The indirect
  column is larger than the direct one**, so any migration estimate built from
  §8.0's first column alone is low by roughly an order of magnitude.
  **A third finding fell out of writing `fl2`'s disposition and is recorded
  against this spec's own earlier conclusion:** r2 read `test_ou3`, found no
  differential assertion, and concluded *"there is no differential oracle"*.
  That was right about `test_ou3` and **wrong about the suite** —
  `test_fl2[sdk]` at `:1392-1398` drives a fresh CLI pass from inside the
  `sdk` leg and asserts byte-identity on three failure kinds. New §3.4.1;
  §14's `S-49` text corrected a second time. `RO-6`'s byte-pin now replaces
  something real.
  **MAJOR-A:** `S-49`'s opening enumeration still listed "the `TRANSPORT`
  table" as deleted while the same row said it was not — the r1 fold's own
  correction contradicted two paragraphs above it. Fixed to name the four
  deleted fields.
  **MAJOR-B:** §10.2's counts were wrong — covered is **21 of 38 (55 %)**, not
  24; unmutated is **17**, not 14. Per the gate's ruling, every unmutated
  criterion now carries either its literal discharge command (12 of 17) or an
  explicit `HUMAN READS THE DIFF` label (5 of 17: DOC1–4, AG3).
  **DIVERGENCES:** §8.0's `build_argv` row is **4 / 9** (its r2 sub-counts did
  not sum to their own total) and `_read_argv_flag` is **0 / 1** — a row r2
  listed without measuring, which is exactly the failure §8.0 exists to
  prevent. *(The gate placed the `_read_argv_flag` reference in `test_op13`;
  measured, it is in `test_op11` at `:584`/`:597`. Both agree the cell is not
  0/0. Re-sweeping also surfaced a §7 consequence no round had named:
  `test_op13_argv_read_set_is_closed` asserts the `--`-literal set of
  `backend.py` equals `{"--append-system-prompt"}`, which §7 empties —
  disposition added to §8.4b.)*
  **NITs:** §8.4a-vs-§8.4b framing (24 vs 27 — different populations, now
  said); §8.2's `result_stdout` cell no longer self-negates ("no reader that
  *survives*"); `CV7` reordered before `CV8`; `AG1` gains its `AG2` exemption
  clause and the no-narrowing rule.
  All r3 measurements at `ee0d671` under §11.0's environment, rc unpiped.
  Instruments (`unpin_backend.py`, `ag1_tripwire.py`, `sweep3.py`) live in the
  session scratchpad, patch in-process and restore in `finally`; no repository
  file other than this draft was created, edited or reverted, and
  `~/.self-learn` was never read or written.
- **r4, 2026-08-24** — third gate fold (1 MAJOR, 2 NIT; every r3 claim
  reproduced by the gate — `A4` = 51 with batch A's 18 test-for-test, §8.0a's
  mechanism, the `fl2` oracle at `:1394`/`:1398`, the `op13` re-baseline; the
  gate also accepted the `op11` correction as its own r2 attribution error).
  **No number, criterion, mutation or disposition changed — this round is text
  placement only, and it matters because the text sits in the section §0 calls
  "the go/no-go evidence".**
  **MAJOR:** three r2 sentences survived the r3 fold and contradicted §3.4.1
  thirty lines below them. (1) The bold *"There is no differential oracle"*
  paragraph is rewritten to carry the corrected finding as a two-bullet r2/r3
  record — `test_ou3` is not an oracle, `test_fl2[sdk]` is, and it is the one
  property genuinely lost. (2) §3.4.1's closing clause said *"claiming a lost
  differential oracle in the permanent record would have been a false entry"* —
  which contradicted its own opening sentence and misdescribed §14, since §14
  now correctly claims one and names it; rewritten. (3) §3.4(a)'s property
  table still read *"there is no such oracle"* with no cross-reference **and had
  no row for the lost property at all** — the row that mattered most was the
  one missing. The `test_ou3` row is now labelled *misidentified* and a new row
  — **cross-backend renderer agreement**, `test_fl2[sdk]` `:1394`/`:1398`,
  **LOST, no in-kind replacement**, replaced in coverage by `RO-6`/`CV3`'s
  phase-A byte-pin — sits beside it, cross-referenced to §3.4.1 and §8.4b.
  **`R3-N1`:** §8.0a now states its counting rule (`\b<name>\b` anywhere in
  `ast.get_source_segment`, which begins at the `def` line, so signature-named
  fixtures and body-called helpers count alike) and records that a stricter
  rule shifts individual cells by ±1 (`_spec` 59 vs 58, `_drive_reader_sdk` 9
  vs 10) without touching the conclusion or any criterion.
  **`R3-N2`:** `fl2`'s explanatory block is a `#` comment at `:1356-1362`, not
  a docstring — `def` is at `:1355` and the function has none. Corrected, and
  the oracle's own cites tightened to `:1394` / `:1398` throughout.
  **Verification:** `no such oracle` and `false entry` now return **0**
  occurrences; all three surviving `no differential oracle` occurrences sit
  inside an explicit retraction (`:426`, `:459`) or §17 history (`:1834`), none
  in live prose. Spec is still the sole untracked file at `ee0d671`; no code
  read or written this round beyond re-measuring the four `test_worker_contract.py`
  line numbers.
