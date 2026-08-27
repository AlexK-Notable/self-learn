# U-engine — a shared SDK session library, and the host process that consumes it

**r2 — amended 2026-08-26 per user ruling: host process ADOPTED.**
**r3 — amended 2026-08-26 per spec gate r2 (SOUND, five folds) and the
orthogonal orchestrator ruling: `serve` runs jobs SERIALLY.**
**r4 — amended 2026-08-26 per spec gate r3 (SOUND, seven prose folds);
no structural change. `FW-121` restated: the finding is a SURFACE
MISMATCH between `S-48`’s wording and the symbol the backend branches on,
NOT an untestable contract.**
*(r1, 2026-08-26, ruled the host process out and scoped the extraction to
four small helpers. The user then ran a four-option discussion and a
pros/cons on the daemon and reversed both calls. §3 records the decision;
the census that produced it is carried forward unchanged except for four
corrections the blind spec gate r1 found, each marked CORRECTED-r2.)*

Authored at `a0c67be` in the throwaway worktree
`.claude/worktrees/u-engine-spec` (branch `u-engine-spec`, based on
`origin/master` = `a0c67be`). Uncommitted.

**Spec gate r1 returned SOUND on r1 text**: every census number reproduced
exactly (0/4; all six similarity ratios; the extraction table; 3-of-20;
6 tests reaching `lifecycle` globals with 5 inside the armor-pinned file);
`new_run_id()` collision reproduced; `ARM1` proven achievable by replaying
the five pinned tests against the proposed shape. Its four findings are
folded here.

---

## 0. Reading order and precedence

1. `03-decisions.md` rows **S-32, S-43, S-44, S-45, S-46, S-47, S-48,
   S-49** — the contracts this unit inherits. Where this spec and a row
   disagree, **the row wins**.
2. `13-hosting-and-separation.md` **§5** (producers commit their own
   writes; H-5: no watcher on the ledger repo, ever) and **§8** invariant
   H-5. Phase 2 must preserve it; §5.5 says exactly how.
3. `u-cleanup-cli-path-removal-spec.md` **§13.2 item 1** — the boundary
   left for this unit, verbatim: *"It may not restructure
   `invocation_sdk`, may not touch `ui/`, and may not introduce a shared
   module."* This unit is the one that may.
4. `17-invocation-runbook.md` — §6 (rollback, rewritten 2026-08-25 and
   dry-run-measured 2026-08-26) and §5.2 (the miner-flip burn-in shape).
5. `12-transcript-miner.md` §3 (scheduling and containment).
6. `misc/r2-progress.md:3100-3125` (the decomposition that named this
   unit) and `:875-900` (the measured cgroup-reap finding).
7. The code, in the order §2 measures it.

**Every number below is a command output.** Where something could not be
measured it is said so.

---

## 1. Objective, and the non-objectives

**Objective.** Break the reusable MECHANISM out of the two SDK engines
into one shared library with a policy seam, prove it drives N concurrent
sessions in one process, and then build the long-lived host process
(`self-learn serve`) that consumes it — replacing three systemd units and
a covert any-verb watchdog with one supervisable process that ports to any
machine.

Two phases, two behaviour contracts:

- **Phase 1 — the library.** ZERO behaviour change for the pane and the
  seam. Every operator-visible message byte-pinned WITH its prefix on both
  engines, before the code moves.
- **Phase 2 — the host process.** New behaviour, its own criteria, its own
  docs, its own burn-in observable.

**Non-objectives**

1. **Merging the two charters.** Never (§3, §4.4). The census is the
   evidence and `AGR2` is the detector.
2. **Speculative generality.** "Portable" has an exact meaning here
   (§4.5) and anything beyond it is refused.
3. **SDK behaviour improvements** beyond what multi-session forces
   (§11 row 6).
4. **An SDK version bump** — both packages stay at
   `claude-agent-sdk>=0.2.116,<0.3` (measured: `ui/pyproject.toml:19`,
   `cli/pyproject.toml:13`).
5. **Its own distribution.** The library ships inside the CLI
   distribution; the trigger that would change that is named in §11
   row 9.

---

## 2. Census, measured at `a0c67be`

**The census stands.** The spec gate reproduced every figure. Four
corrections are folded, each marked **CORRECTED-r2**.

### 2.0 The line-counting instrument, stated once (CORRECTED-r2, gate D-4)

The gate got 99 vs 81 code lines and 4.3% vs 5.8% depending on
definition, because r1 never named the instrument. It is named here and
used for **every** line figure in this spec:

> **raw lines** = `len(ast.get_source_segment(node).splitlines())`, or
> `len(path.read_text().splitlines())` for a whole file.
>
> **code lines** = the same segment minus (a) blank lines, (b) lines whose
> stripped form begins with `#`, and (c) every line of the node’s (or
> module’s) own docstring, delimiters included.

Percentages are **code over code**. r1 quoted a code numerator over a raw
denominator, which is why its 4.3% was not reproducible.

### 2.1 The two trees, sized

| Tree | File | raw | code |
|---|---|---|---|
| UI engine | `base.py` | 213 | 93 |
| UI engine | `charter.py` | 277 | 145 |
| UI engine | `sdk.py` | 516 | 308 |
| UI engine | `__init__.py` | 44 | 28 |
| **UI total** | 4 files | **1050** | **574** |
| CLI `invocation_sdk` | `backend.py` | 572 | 377 |
| CLI `invocation_sdk` | `charter.py` | 268 | 140 |
| CLI `invocation_sdk` | `lifecycle.py` | 236 | 127 |
| CLI `invocation_sdk` | `events.py` | 103 | 56 |
| CLI `invocation_sdk` | `provider_env.py` | 48 | 9 |
| CLI `invocation_sdk` | `__init__.py` | 9 | 3 |
| **CLI total** | 6 files | **1236** | **712** |
| **Both** | 10 files | **2286** | **1286** |

### 2.2 Whole-function duplication: ZERO

AST sweep, every top-level symbol body in one tree against every one in
the other, comments/docstrings/blanks stripped:

**`body-identical pairs (>=3 substantive lines): 0`.**

Name-identical symbols excluding `__all__`: **4**, all with different
bodies — `CharterPaths` (disjoint FIELDS: `read_roots`/`record_path`/
`proposal_yaml_path`/`proposal_diff_path` vs `glob_patterns`/
`exact_paths`), `build_can_use_tool`, `_extract_target_path`,
`_log_abandoned_disconnect`.

Similarity of the six candidate pairs (`difflib.SequenceMatcher` over
comment-stripped code lines):

| Pair | UI | CLI | ratio |
|---|---|---|---|
| `_extract_target_path` | 6 | 7 | **0.769** |
| `_log_abandoned_disconnect` | 12 | 12 | 0.417 |
| `close` vs `run_kill_ladder` | 21 | 33 | 0.259 |
| `interrupt` vs `run_kill_ladder` | 35 | 33 | 0.059 |
| `build_can_use_tool` | 90 | 66 | 0.333 |
| `_build_options` vs `options_kwargs` | 72 | 57 | **0.016** |

### 2.2a FRAGMENT-level sweep (NEW in r2 — gate finding M-2)

r1’s instrument compared whole top-level symbols and was therefore blind
to a duplicate living inside two differently-shaped functions. The gate
found one. r2 adds the instrument that finds it and re-ran it over both
trees:

```
python3 -c "<walk every If/Try/For/While/With; unparse; collapse every
            Name/attribute/arg identifier to a single token; hash;
            intersect the two trees; keep fragments of >= 4 lines>"
```

**3 skeleton-identical pairs, which are 2 distinct mechanisms** (pair 1 is
the inner half of pair 3):

| Mechanism | UI | CLI | lines | ratio |
|---|---|---|---|---|
| **The `ResultMessage` error-detail chain** — `errors` joined by `"; "`, else `result`, else `subtype` | `sdk.py:502` (`SdkPaneEngine._map_result`) | `backend.py:318` (`_map_result_message`) | 6 / 6 | **1.000** |
| The target-path key loop | `charter.py:173` | `charter.py:175` | 4 / 4 | **1.000** |

The error-detail chain’s ENTIRE raw difference is two identifier names —
UI writes `error` / `message`, the CLI writes `detail` / `result_message`.
It is the first exact duplicate in the census, and r1 missed it.

**Consequence, and r1’s §3.3 is amended here:** r1 wrote that the two
message-to-event mappings share *"no shared vocabulary ... to extract"*.
That was wrong. **Their shared vocabulary is `str`** — both reduce a
`ResultMessage` to one human-readable error string by the same three-step
rule, and only then diverge (`Result.error` vs `Outcome.detail`). That
reduction goes in the library (§4.2).

### 2.2b What the measured deltas ACTUALLY are (CORRECTED-r2, gate M-1)

**r1 justified the unit with "two copies ... already measurably drifted
(ratio 0.417)". That justification was wrong and is withdrawn.** Read
line by line, the entire delta between the two `_log_abandoned_disconnect`
copies is the intended difference — the log sink and the message prefix:

```
-def _log_abandoned_disconnect(task: "asyncio.Task[None]") -> None:
+def _log_abandoned_disconnect(task: asyncio.Task[Any], log: Callable[[str], None]) -> None:
-uilog.log("pane engine close: abandoned disconnect() was cancelled")
+log("run: sdk backend: abandoned disconnect() was cancelled")
-uilog.log(f"pane engine close: abandoned disconnect() finished with: {exc}")
+log(f"run: sdk backend: abandoned disconnect() finished with: {exc}")
-uilog.log("pane engine close: abandoned disconnect() completed")
+log("run: sdk backend: abandoned disconnect() completed")
```

Every branch and every condition is identical. The gate searched for real
divergence and found none. **The true reason — and it is a better one:
two copies, correct today, UNWATCHED. Nothing pins them to each other, so
the next edit to either one silently diverges the other, and §2.8 measures
that 18 of the 24 messages involved are asserted nowhere at all.**

The same standard applies to the ladders. The 0.259 ratio between
`SdkPaneEngine.close` and `run_kill_ladder` is **not** drift; the delta is
three stated, deliberate differences:

| Difference | Where | Its stated rationale |
|---|---|---|
| The CLI ladder has a **step 1** (bounded `client.interrupt()`) inside the same function; the UI puts that in `interrupt()` | `lifecycle.py` vs `sdk.py` | the CLI runs the ladder unconditionally in `finally`; the pane runs it on a keystroke |
| The CLI ladder has a **step 3** (explicit `kill_child` under a `getpgid` guard); the UI has none | `lifecycle.py` | its docstring: *"`run_sync` drives this coroutine via `asyncio.run`, which closes the event loop on return — any background task ... dies unfinished"* |
| The UI derives every wait from ONE Esc-anchored deadline; the CLI uses two fixed constants | `sdk.py:interrupt` | 09 §4.2: a keystroke gets a bounded worst case |

**No behavioural difference was found that one engine fixed and the other
did not.** Any such claim would need a demonstrated failing case, and this
spec does not have one.

**But difference 2 does not survive Phase 2, and that is a real finding.**
Step 3’s entire justification is that `asyncio.run` closes the loop and
kills the background escalation. Under a host process the loop does NOT
close, the abandoned `disconnect()` runs to completion, and the SDK’s own
SIGTERM/SIGKILL escalation finishes on its own — so an unconditional
`SIGKILL` at step 3 becomes a kill racing a graceful teardown. §4.6 rules
what happens to it.

### 2.3 Option assembly: 3 of 20 keys identical

AST comparison of the UI’s single `ClaudeAgentOptions(...)` call against
the CLI’s `options_kwargs` mapping. Identical: `allowed_tools=[]`,
`setting_sources=[]`, `strict_mcp_config=True`. `can_use_tool` shares a
name only. The other 16 differ, two of them semantically:
`system_prompt` (a bare `str` REPLACES Claude Code’s prompt; the preset
dict APPENDS) and `include_partial_messages` (`True` vs `False`).
Present on one side only: `env`, `permission_mode`, `settings` (CLI);
`fallback_model`, `extra_args`, `resume`, `session_store` (UI).

### 2.4 Consumers

`invocation_sdk` has **one** production consumer —
`invocation/registry.py:69`, a lazy `from ..invocation_sdk import
SdkBackend` — plus `provider.py:622`, which `importlib`-imports the
module and `getattr(module, "orphan_report", None)`-probes it for a doctor
hook **that does not exist** (`__all__ == ["SdkBackend", "SdkOutcome"]`).

The UI engine has **one**: `pane.py` (`:76`, `:77`, `:1605`, `:1616`).

Seam call sites, all four surfaces: `worker._invoke_claude`
(`worker.py:3062-3115`), `miner._invoke_reader` (`miner.py:720-760`),
`analyst.analyze` (`analyst.py:~228-245`).

### 2.5 Tests and armor

Test functions whose own body names a symbol of each wrapper: **CLI 89**
(top: `test_invocation_sdk.py` 41/84, `test_invocation.py` 10/50,
`test_worker_contract.py` 10/39, `test_reader_contract.py` 9/38,
`test_u_sdka.py` 9/37); **UI 134** (top: `test_pane.py` 53/83,
`test_iterate_routes.py` 27/33, `test_engine_sdk.py` 22/22).

`test_worker_contract.py::_ARMOR_SHAS` (`:507-515`) carries **seven**
whole-file sha256 pins checked by `test_su4a_whole_file_armor_shas`
(`:618`): `conftest.py`, `backends.py`, `test_invocation.py`,
`test_invocation_sdk.py`, `test_u_fake.py`, `test_worker.py`,
`test_repair.py`. Six are in `_SU4B_DIFF_EXEMPT` (`:606`); only
`backends.py` is additionally held diff-empty against
`BASE_COMMIT = "c3b48e7"` (`:74`). `test_su4b_fake_claude_additive_only`
(`:741`) pins `cli/tests/fixtures/fake_claude.py` **per function** against
`git show 89f8ef7:...`.

**Six test functions reach `invocation_sdk.lifecycle`’s module globals
directly; five are inside the armor-pinned `test_invocation_sdk.py`:**

| File | Test |
|---|---|
| `test_invocation_sdk.py` (PINNED) | `test_kl1_interrupt_is_bounded_and_the_ladder_stays_within_kill_secs` |
| `test_invocation_sdk.py` (PINNED) | `test_kl2_disconnect_is_shielded_the_task_survives_the_kill_bound` |
| `test_invocation_sdk.py` (PINNED) | `test_kl3_abandoned_task_is_discarded_and_logs_one_outcome_line` |
| `test_invocation_sdk.py` (PINNED) | `test_kl_major1_disconnect_raising_is_distinguished_from_a_timeout` |
| `test_invocation_sdk.py` (PINNED) | `test_kl4_hang_sigterm_ignored_child_is_gone_after_run_sync_returns` |
| `test_reader_contract.py` | `test_to6_kill_ladder_three_rungs_and_pgid_discrimination` |

They `monkeypatch.setattr(lifecycle_mod, "KILL_SECS", ...)` and read
`lifecycle_mod._ABANDONED_DISCONNECTS` by identity. **The gate proved
these five survive unedited if `run_kill_ladder` stays in `lifecycle.py`
and reads the monkeypatched name at CALL time. r2 keeps that property as
a design constraint (§4.7 C-1) even though zero-re-pin is no longer a
criterion.**

The UI side has no whole-file armor over the engine. Its only coupling to
an engine module global is
`test_engine_sdk.py:453 test_default_ladder_constants_match_the_tuned_pin`.

### 2.6 The fake seams

| Seam | Where | Size | Note |
|---|---|---|---|
| UI `FakeEngine` | `engine/base.py:170-213` | 44 raw | scripted-playback `PaneEngine` |
| CLI `FakeBackend` | `invocation/fake.py` | 131 raw | injected by `tests/backends.py::install_fake` (57 raw) |
| CLI fake CLI binary | `cli/tests/fixtures/fake_claude.py` | 844 raw | under `test_su4b`’s per-function byte pin |
| UI fake CLI binary | `ui/tests/fixtures/fake_claude.py` | 235 raw | unpinned |

The two fake binaries share **119 identical lines, ratio 0.221**, 8 shared
def names of 29 (CLI) and 15 (UI). Unifying them re-anchors an armor test
for a fixture — **OUT** (§11 row 8).

### 2.7 The fact that decides where the library lives

`ui/pyproject.toml:20` lists `self-learn-cli` in `[project.dependencies]`
and `:53` binds it as `{ path = "../cli", editable = true }`. The
dependency is one-directional:

```
grep -rnE "^\s*(from|import)\s+self_learn_ui" plugins/self-learn/cli/src
```
returns **nothing** — the only two `self_learn_ui` mentions in CLI `src`
are prose (`worker.py:1317`, `verbs.py:280`) — and
`cli/tests/test_a2_rules_local.py:731` states it in the suite’s own voice:
*"this suite cannot import self_learn_ui"*.

Conversely **8** UI modules import `self_learn.` at module scope
(`doctrine`, `uilog`, `ledger`, `proposals`, `routes`, `middleware`,
`models`, `pane`) plus a ninth lazily inside `engine/charter.py:100`.

**Therefore the library lives in the CLI distribution. The other
direction does not compile.**

### 2.8 THE PIN CENSUS — the finding that defines Phase 1 (NEW in r2)

Every operator-visible message that the library will own, and whether any
test asserts it today. Two patterns per message: the full literal
including its prefix, and a distinctive prefix-free tail.

| Group | Messages | pinned WITH prefix | pinned PREFIX-FREE only | asserted NOWHERE |
|---|---|---|---|---|
| CLI teardown ladder | 5 | 2 | 1 | 2 |
| CLI orphan sweep | 6 | 0 | 0 | 6 |
| CLI session (`could not resolve the child pid`) | 1 | 1 | 0 | 0 |
| CLI option-capability | 2 | 2 | 0 | 0 |
| UI close ladder | 5 | 0 | 0 | 5 |
| UI interrupt ladder | 3 | 0 | 0 | 3 |
| UI drain (`session ended abnormally`) | 1 | 0 | 0 | 1 |
| UI SDK log forwarding (`sdk[...]`) — **CLIENT-OWNED, not library-owned** | 1 | 0 | 0 | 1 |
| **LIBRARY-OWNED TOTAL** | **23** | **5** | **1** | **17** |
| **PINNED TOTAL (library + the client-owned row)** | **24** | **5** | **1** | **18** |

**CORRECTED-r2 (gate D-1, D-2):** the CLI ladder has **five** lines, not
four; the UI has **eight** ladder lines, not seven — r1 missed
`"pane engine interrupt: SDK interrupt() failed, escalating: {exc}"`
(`sdk.py:261`). Restricted to the operator-visible SHUTDOWN subset the
gate named (CLI teardown 5 + UI close 5 + UI interrupt 3 = **13**):
**2 pinned with prefix, 1 prefix-free only, 10 asserted nowhere.**

**CORRECTED-r3 (gate N-1) — one of the 24 is client-owned by this
spec’s own design.** The SDK log-forwarding line `sdk[{name}]: {msg}`
is emitted by `_ForwardSdkLogToUiLog`, and G-4 / C-4 keep that handler
UI-side precisely because the library may not install a handler on a
process-global logger. **The library therefore owns 23 messages, not
24.** The 24th is still pinned by `PIN1` — a client must not silently
change it either — but it is not counted against the library, and
`PIN4`’s other-engine-table control does not apply to it.

**Two false positives r1 would have counted and r2 does not:** grepping
for the bare tails `not stale` and `still running at the kill bound`
matches `assert not stale` in `test_lock_invariant.py:518` and
`test_attrib.py:134` (ordinary Python, unrelated), and matches
`test_kl2_and_kl3_end_to_end`’s
`any("still running at the kill bound" in line for line in logs)` —
which is real but **prefix-free**, i.e. blind to exactly the defect an
extraction is most likely to introduce.

**This is the unit’s real product.** The code motion is the cheap half.
Three T1-grade builders could ship the motion and none of the
instruments, and the suite would stay green while every shutdown message
on both engines silently changed.

### 2.9 Single-session assumptions, enumerated by command (NEW in r2)

```
python3 -c "<AST: every module-level Assign/AnnAssign in the five
            invocation_sdk modules and the three UI engine modules>"
```
**21 module-level bindings excluding `__all__`.** **Six** of them carry
state or an environment assumption; the other **15** are frozen constants.

| # | Binding | What it assumes | Phase 1 disposition |
|---|---|---|---|
| G-1 | `lifecycle._PROCESS_START = time.time()` (import time) | "older than this process" == "older than this import" — under a daemon it means "older than the daemon booted", a much weaker staleness test | becomes a parameter of the sweep, defaulted at first call, not at import |
| G-2 | `lifecycle._ABANDONED_DISCONNECTS = set()` | nothing per-session — membership is per TASK, discarded by a done-callback | **KEPT** as a module-level registry in the library; it is a GC-liveness set, not session state |
| G-3 | `sdk._ABANDONED_DISCONNECTS = set()` | the UI’s second copy of G-2 | folded into G-2, same object |
| G-4 | `sdk._forward_handler = _ForwardSdkLogToUiLog(...)` installed on `logging.getLogger("claude_agent_sdk")` at `setLevel(DEBUG)` | one process == one UI; a host process running pane-less sessions would still get every SDK debug line forwarded into `uilog` | stays UI-side; the library must NOT install a process-global logging handler (`HOST3`) |
| G-5 | `backend._DEFAULT_MAX_TURNS = {...}` | nothing — mutable by type, constant by use | left alone; noted so the enumeration is complete |
| **G-6** | `backend._CATCHES_OS_ERROR = dict(TRANSPORT)` — **an IMPORT-TIME SNAPSHOT of a mutable table**, not a frozen constant | that `TRANSPORT` will not change after `invocation_sdk.backend` is imported | **the library must NOT read `TRANSPORT` at all** — see below |

**CORRECTED-r3 (gate N-2): G-6 was miscounted as a frozen constant.**
`dict(TRANSPORT)` evaluated at import is a COPY, so a later mutation of
`TRANSPORT` never reaches the backend. Measured:

```
uv run python -c "from self_learn.invocation import contract as C;
 from self_learn.invocation_sdk import backend as B;
 C.TRANSPORT['analyst'] = False;
 print(C.TRANSPORT['analyst'], B._CATCHES_OS_ERROR['analyst'])"
```
```
False True
```

**Does the library have to read `TRANSPORT` at call time? NO — it must
not read it at all.** The analyst-vs-worker/miner OSError/ClaudeSDKError
split is SEAM policy: it is consumed inside `_drive`’s except ladder
(`backend.py:417`, `:471`, `:479`), which stays in `invocation_sdk`
(§4.4) and is never reached by `sdksession`. Putting a `TRANSPORT` read
in the library would import `invocation.contract`, which `LIB1` forbids
outright. So this unit changes nothing here — but it must not inherit
the assumption silently either, hence the row.

**The finding this exposes, stated accurately — it is a SURFACE
MISMATCH, not an untestable contract (CORRECTED-r4, gate M-1).** An
earlier draft of this paragraph claimed `M11` "holds only for a source
edit, not a runtime mutation". **That is false**, and the counter-example
is in the suite:
`test_u_opsfix.py::test_fw108_no_line_when_surface_does_not_catch_os_error`
does `monkeypatch.setitem(backend_mod._CATCHES_OS_ERROR, "worker",
False)` (`:171`) and drives the **real `SdkBackend`**, asserting the
surface-conditional behaviour. The live control point is fully
monkeypatchable and is already exercised.

**The accurate, narrower finding: `S-48`’s recorded evidence names the
wrong symbol.** It says *"reverting `TRANSPORT["analyst"]` … proving the
contract had to close at the transport-table level"*, but the symbol the
backend actually branches on is `_CATCHES_OS_ERROR`, the import-time
fold. Mutating `TRANSPORT` after import changes nothing the backend
observes (measured above); mutating `_CATCHES_OS_ERROR` changes
everything, and a shipped test does exactly that. The two are the same
values at import and diverge the instant either is touched. Nothing is
untestable — **the decision row and the code point at different
symbols**, which is a documentation defect with a real cost: a
maintainer following `S-48`’s wording monkeypatches `TRANSPORT`,
observes no behaviour change, and concludes the contract is broken.

`test_u_sdka.py:1135 test_m16_transport_table_is_still_a_plain_mutable_dict`
is the test `S-48` implicitly leans on, and it asserts only that the
TABLE supports item assignment (`isinstance(dict)`, not a
`MappingProxyType`, `setitem` visible on the table) — it never asserts,
and does not claim to assert, that the BACKEND observes the change.
That job belongs to `test_fw108_...`, on the other symbol. **Recorded as
FW-121 (§12.2); NOT fixed here** — `contract.py` and the seam’s except
ladder are outside this unit’s files-may-touch table.

Three further single-session assumptions are NOT module-level bindings and
r1 recorded them as future work. **They are now Phase 1 work:**

- **`events.new_run_id()` collides.** Measured:
  ```
  uv run python -c "from self_learn.invocation_sdk.events import new_run_id; a=new_run_id(); b=new_run_id(); print(a, b, a==b)"
  ```
  ```
  20260827T042901Z-2180746  20260827T042901Z-2180746  True
  ```
  It is `strftime("%Y%m%dT%H%M%SZ") + "-" + str(os.getpid())` — one-second
  resolution plus a pid. Two sessions in one process in one second get the
  same id, and `write_event_log` overwrites the first file.
- **The pid sidecar is a per-surface singleton**:
  `_sidecar_path(surface) -> worker.cache_dir() / f"{surface}.sdk-child.pid"`.
  Two concurrent sessions on one surface overwrite each other, and the
  survivor sweeps the wrong pid.
- **`prune_event_logs(surface)` globs `f"{surface}.tool-events.*.jsonl"`
  and unlinks all but the newest N — at the START of every session.** With
  N sessions live on one surface, a starting session can unlink a running
  session’s log file.

**Sync-bridge call sites**, the other multi-session hazard:
```
grep -rn "asyncio\.run(|run_sync(" plugins/self-learn/cli/src --include=*.py
```
```
backend.py:79   def run_sync(...)
backend.py:87       return asyncio.run(factory())
backend.py:101          result_box.append(asyncio.run(factory()))
backend.py:572      return run_sync(lambda: _drive(spec))
```
Exactly **one** call site, and `run_sync`’s second branch already handles
"a loop is already running" by starting a non-daemon thread and
`join()`-ing it **unbounded**. Under a host process that branch becomes
the only branch, so **every session would block a thread**. The UI has
zero `asyncio.run` / `get_event_loop` / `new_event_loop` /
`set_event_loop` call sites in `src` — it is already loop-native.

### 2.10 Baselines, re-measured in this worktree at `a0c67be`

```
SUITE_OUT=<worktree>/misc/suite-baseline plugins/self-learn/cli/scripts/suite
suite A rc=0  175 passed in 94.76s
suite B rc=0  178 passed in 59.36s
suite C rc=0  1992 passed, 6 skipped in 263.88s
suite total rc=0  264s
```
**2345 passed / 6 skipped / 0 failed**, rc captured unpiped.

```
cd plugins/self-learn/ui && uv run pytest -q -p no:cacheprovider
1 failed, 1239 passed, 5 warnings in 175.52s
FAILED tests/test_service_unit.py::test_both_units_document_manual_registration_via_symlink
```
**1239 passed + the one known pre-existing failure**, which must remain
the only failure.

---

## 3. DECISION (2026-08-26) — the text this unit owes `03-decisions.md`

*This section is the decision row, written to be lifted verbatim. §3.1 is
the four-option choice; §3.2 is the host-process adoption.*

### 3.1 Four options were on the table; the user chose the fourth

**S-50 — the two SDK engines share a LIBRARY, not a monolith; the two
charters stay two; and a long-lived host process becomes the library’s
third consumer.**

Four framings were put to the user:

1. **Let the two engines diverge** — they serve different clients (an
   interactive pane, a one-shot seam), so two implementations is not
   obviously wrong.
2. **Force unification on cohesion grounds** — one engine, one code path.
3. **Rebuild it the way it should have been built** — discard both and
   write the thing once.
4. **Break the reusable MECHANISM out of each engine into a shared
   library** — extensible, and eventually portable to other projects —
   rather than a monolith.

**The user chose (4).** The reasoning that carried it, and the
measurement behind each half:

- **The two CHARTERS stay separate.** Measured: their decision tables are
  disjoint. The pane scopes READS by root (ledger tree, registered hosts’
  canon surfaces, the plugin references dir) and writes to three exact
  id-sibling files; the seam scopes no reads at all
  (`invocation_sdk/charter.py`: *"no CLI surface scopes reads by path"*)
  and scopes WRITES by gitignore-flavoured glob. They raise different
  fail-closed exceptions (`CanonReadRootsUnavailable` vs
  `CharterPatternUnsupported`) and emit different message prefixes.
  Merging them would put read-scope logic on the write-security path. The
  measured similarity of the two `build_can_use_tool` bodies is **0.333**,
  and the 31 lines they share are callback signature and
  `PermissionResultDeny` scaffolding, not policy.
- **The MECHANISM under them is where divergence is dangerous** — and the
  honest reason is NOT that it has drifted. Measured: it has not. The
  entire delta between the two `_log_abandoned_disconnect` copies is the
  intended log-sink and message-prefix difference, branch for branch; the
  three differences between the two kill ladders are each stated and
  deliberate. **The danger is that the two copies are correct today and
  UNWATCHED: nothing pins them to each other, and 18 of the 24
  operator-visible messages they emit are asserted by no test at all — 10
  of the 13 shutdown messages included.** The next edit to either engine
  silently diverges the other, and no instrument in either suite would
  notice.
- **What the whole-function census missed, and the fragment census
  found:** the `ResultMessage` error-detail chain (`errors` joined by
  `"; "`, else `result`, else `subtype`) is **skeleton-identical at 1.000
  across the two engines**, differing only in two identifier names. It is
  the clearest single instance of one mechanism written twice.
- **Scale:** the library region measures **405 raw / 287 code lines** of
  **2286 raw / 1286 code** across the two engine trees — **22.3% of code
  lines** (itemised cell by cell in §4.2, which names the four symbols
  deliberately excluded so the total re-derives). This is a library, not
  a helper module.

**Refused, explicitly, so it is not rediscovered:** option 2 (one engine)
and option 3 (rebuild). Measured, the two engines share **zero
body-identical top-level functions or classes** and **3 of 20**
`ClaudeAgentOptions` keys; their session lifetimes are incompatible (the
pane holds one multi-turn `ClaudeSDKClient` across `send()` calls; the
seam does connect-query-drain-teardown once) and two of their shared
option keys are semantically opposed (`system_prompt` replaces vs appends;
`include_partial_messages` `True` vs `False`). A single engine would be a
two-mode branch; a rebuild would discard two byte-pinned, burned-in
implementations to arrive at the same seam this decision draws.

### 3.2 The long-lived host process is ADOPTED

**User ruling, 2026-08-26 22:01, verbatim: *"adopt the host process. amend
the spec accordingly."*** This REVERSES the r1 recommendation of this
spec, which had ruled the daemon out. The reversal is recorded, not
hidden, and the reason it is right is one the r1 analysis under-weighted.

**What r1 got right, and it still stands:** the immediate symptom — the
nightly miner-to-worker handoff never completing — has a small cause and
three cheap remedies. Measured live:
```
systemctl --user show self-learn-miner.service -p KillMode -p Type
Type=oneshot
KillMode=control-group
```
`worker._spawn_window` uses `subprocess.Popen(..., start_new_session=True)`;
`setsid` escapes the process group and session but **not the cgroup**, so
systemd reaps the spawned worker when `ExecStart` returns. The register
recorded the measured history (`misc/r2-progress.md:880-895`): *"WORKER LEG
NEVER RAN ... the unattended mine-to-worker handoff has NEVER once
completed"*, and named three remedies — `KillMode=process`,
`systemd-run --user --scope`, or a chained `self-learn-worker.service`.

**What r1 under-weighted, and what decided it: portability.** self-learn
is going to other users’ machines — that is `U-hostmode`’s whole premise —
and what they trip on first is not the SDK. It is **three systemd units
plus a covert any-verb miner watchdog**: `self-learn-miner.service`,
`self-learn-miner.timer`, `self-learn-ui.service` (all linked by
`install.sh:96-106`, each left for the user to `enable --now`), plus
`miner.maybe_kick`, which every CLI verb except `mine` and `init` ticks
(`cli.py:1992`) and which silently `setsid`-spawns a real mining run when
the last completed mine is over `KICK_AFTER_SECS = 24 * 60 * 60` old.
**That watchdog is invisible until it bites**, and it bit during this
campaign: the FW-116 rollback dry-run’s first `doctor` call landed **five
real commits** in a throwaway ledger copy before anyone noticed
(`17-invocation-runbook.md` §6 item 4, measured 2026-08-26).

A `self-learn serve` process under ANY supervisor — systemd, launchd, or a
terminal window — is the only shape that ports cleanly. Fixing the cgroup
reap with a `KillMode` line fixes this machine and ports nowhere.

**The pros/cons as weighed, in brief:**

| | |
|---|---|
| **FOR** | One thing to supervise instead of three units plus a hidden watchdog. Portable to launchd or a bare terminal — the existing `self-learn-ui.service` already documents exactly that fallback (*"run `self-learn-ui serve` in the foreground"*), so `serve` is the house pattern, not a new one. The miner-to-worker handoff dies **by construction**: both jobs are scheduled by one live process, so there is no detached child for a cgroup to reap. The watchdog stops being covert — a daemon that owns the schedule does not need to ambush verbs. |
| **AGAINST, and how each is answered** | *Daemon state is not crash-safe* — answered by keeping every existing file-plus-flock as the source of truth (§5.4); the daemon schedules, it does not remember. *Daemon-down means nothing runs* — answered by `Restart=`, a heartbeat file, and a staleness alarm that lives OUTSIDE the daemon (§5.6): a dead daemon must be LOUD. *`test_lock_invariant.py` gains an entrypoint* — true, real work, budgeted and named (§5.5). *Portability for non-systemd users* — this is the argument FOR, not against, once `serve` runs under any supervisor. |

**The invariant this must not break, and does not:** `13-hosting-and-
separation.md` §5 / §8 H-5 — *"the ledger repo needs no autosync watcher,
ever: producers commit their own writes"*. **`serve` is a SCHEDULER of
producers, not a watcher.** It starts `miner.run` and `worker.run` as
jobs; each job still takes its own `commit_lock` and commits its own
paths under its own pinned subject, exactly as today. Nothing about `serve`
observes the ledger and commits on someone else’s behalf. §5.5 states the
one doc amendment this requires and the one test change it forces.

---

## 4. Phase 1 — the library

### 4.1 Where it lives

**`plugins/self-learn/cli/src/self_learn/sdksession/`** — a subpackage of
the CLI distribution. Forced by §2.7. It rides the existing wheel
(`[tool.hatch.build.targets.wheel] packages = ["src/self_learn"]`), so no
new distribution, no lockfile entry, no `install.sh` step.

Named `sdksession` rather than r1’s `sdkcore` because what it owns is a
SESSION, not a grab-bag of helpers.

### 4.2 What the library owns — the mechanism, end to end

The library owns one SDK session from connect to teardown. Modules and
their contents, each traceable to a measured source:

| Module | Owns | Sourced from |
|---|---|---|
| `session.py` | `SdkSession` — connect, `query`, drive one turn, yield raw SDK messages, tear down. The transport loop, not the vocabulary | `backend._run_session` (41/36), `sdk.SdkPaneEngine._drain` (12/12) |
| `teardown.py` | The kill ladder: bounded `interrupt()`, SHIELDED `disconnect()` never cancelled, abandoned-task registry with both done-callbacks, the guarded child kill | `lifecycle.run_kill_ladder` (58/22), `lifecycle._log_abandoned_disconnect` (12/9), `lifecycle.kill_child` (17/11), `sdk.close` (31/21), `sdk.interrupt` (48/35), `sdk._log_abandoned_disconnect` (12/9) |
| `children.py` | `child_pid_of` (defensive private-attribute walk, returns `None` on ANY failure), the pid sidecar (write/read/clear), the scoped orphan sweep | `lifecycle.child_pid_of` (10/5), `write_sidecar`/`read_sidecar`/`clear_sidecar`/`_sidecar_path` (25/17), `sweep_orphans` (41/36) |
| `events.py` | `EventLog`, run ids, the JSONL sink, retention | `events.*` (69/48) |
| `result.py` | **The `ResultMessage` error-detail reduction** — `errors` joined by `"; "`, else `result`, else `subtype`; and the capability probe over `ClaudeAgentOptions` fields | §2.2a’s 1.000 pair; `backend._supported_option_fields` (4/2) |
| `toolpaths.py` | `TARGET_PATH_KEYS` + `extract_target_path` | §2.2a’s second 1.000 pair (6/6, 7/6) |
| `policy.py` | The `SessionPolicy` Protocol (§4.3) and the containment-callback adapter that wraps a policy’s `can_use_tool` to record every DENY | `backend.options_kwargs`’s inner `can_use_tool` wrapper |
| `ladder.py` | `INTERRUPT_GRACE_SECS = 1.0`, `KILL_SECS = 2.5` — one definition | `lifecycle` + `sdk`, identical values |

**CORRECTED-r3 (gate D-1).** r2 printed a region subtotal that did not
sum to its own cells: it was measured over a candidate set that still
included four symbols this design then EXCLUDED, so the headline was not
re-derivable from what was printed. The region below is exactly the
moving set named in the table above, itemised so every cell sums.

```
python3 -c "<for each moving symbol: ast.get_source_segment; raw =
            len(splitlines()); code = raw minus blanks, minus #-lines,
            minus the node own docstring lines (§2.0); plus the two
            error-detail chain fragments of §2.2a>"
```

| side | module | symbol | raw | code |
|---|---|---|---|---|
| CLI | `session` | `backend._run_session` | 41 | 36 |
| CLI | `result` | `backend._supported_option_fields` | 4 | 2 |
| CLI | `result` | `_map_result_message` error-detail chain | 6 | 6 |
| CLI | `teardown` | `lifecycle.run_kill_ladder` | 58 | 22 |
| CLI | `teardown` | `lifecycle._log_abandoned_disconnect` | 12 | 9 |
| CLI | `teardown` | `lifecycle.kill_child` | 17 | 11 |
| CLI | `children` | `lifecycle.child_pid_of` | 10 | 5 |
| CLI | `children` | `lifecycle.write_sidecar` | 10 | 6 |
| CLI | `children` | `lifecycle.read_sidecar` | 7 | 7 |
| CLI | `children` | `lifecycle.clear_sidecar` | 6 | 2 |
| CLI | `children` | `lifecycle._sidecar_path` | 2 | 2 |
| CLI | `children` | `lifecycle.sweep_orphans` | 41 | 36 |
| CLI | `events` | `events.EventLog` | 31 | 23 |
| CLI | `events` | `events.new_run_id` | 5 | 2 |
| CLI | `events` | `events.write_event_log` | 14 | 9 |
| CLI | `events` | `events.prune_event_logs` | 17 | 12 |
| CLI | `events` | `events._event_log_path` | 2 | 2 |
| CLI | `toolpaths` | `charter._extract_target_path` | 7 | 6 |
| **CLI subtotal** | | | **290** | **198** |
| UI | `session` | `sdk.SdkPaneEngine._drain` | 12 | 12 |
| UI | `result` | `_map_result` error-detail chain | 6 | 6 |
| UI | `teardown` | `sdk.SdkPaneEngine.close` | 31 | 21 |
| UI | `teardown` | `sdk.SdkPaneEngine.interrupt` | 48 | 35 |
| UI | `teardown` | `sdk._log_abandoned_disconnect` | 12 | 9 |
| UI | `toolpaths` | `charter._extract_target_path` | 6 | 6 |
| **UI subtotal** | | | **115** | **89** |
| **REGION TOTAL** | | | **405** | **287** |

**405 raw / 287 code lines of the two trees’ 2286 raw / 1286 code —
22.3% of code lines**, under §2.0’s instrument.

**Four symbols are DELIBERATELY EXCLUDED, and naming them is what makes
the total re-derivable**. **They total 53 raw / 32 code lines.** *(That
is a different quantity from the r2-to-r3 delta of 41 raw / 20 code:
r2 counted these four AND omitted §2.2a’s two 6/6 error-detail chain
fragments, so the delta is −53 + 12 = −41 raw and −32 + 12 = −20 code.
Both figures are correct; they measure different things, and r3’s first
draft conflated them.)*

| Excluded | raw / code | Why |
|---|---|---|
| `backend.run_sync` | 32 / 18 | §4.6 R-2 — the seam’s sync adapter stays at `invocation_sdk/backend.py`. `MS6`/`HP2` pin it out of the library |
| `sdk._install_log_forwarding` | 5 / 5 | C-4 / G-4 — installs a handler on a process-global logger; stays UI-side |
| `sdk._ForwardSdkLogToUiLog` | 13 / 6 | same |
| `sdk.SdkPaneEngine._wait_until_inactive` | 3 / 3 | reads `self._session_active`, which is UI session state, not library state |

### 4.3 Policy as an object — the one Protocol

The library takes policy as an object; it never contains any.

```
class SessionPolicy(Protocol):
    def can_use_tool(self) -> CanUseTool: ...
    def option_floor(self) -> dict[str, object]: ...
    def messages(self) -> ShutdownMessages: ...
    def env(self) -> dict[str, str]: ...
    def cache_dir(self) -> Path: ...
```

- **`can_use_tool()`** returns the charter callback. **Both charters stay
  with their clients** — `ui/engine/charter.py` and
  `invocation_sdk/charter.py` each implement it, unchanged in substance
  (§3.1). The library wraps the returned callback to append every
  `PermissionResultDeny` to the session’s `EventLog` (today’s `C-9`
  behaviour, moved without change).
- **`option_floor()`** returns the three keys measured identical in §2.3
  (`allowed_tools=[]`, `setting_sources=[]`, `strict_mcp_config=True`) as
  a FRESH dict per call. Each client merges its own 16 keys on top; the
  library never builds a `ClaudeAgentOptions`.
- **`messages()`** returns the shutdown/ladder message set. This is what
  makes §2.8’s 24 strings a client-owned, byte-pinnable table instead of
  literals scattered through a shared module.
- **`env()`** returns the provider environment. `invocation_sdk/
  provider_env.py` stays where it is and implements this — it imports
  `self_learn.provider`, which reads config, which is an UPWARD import the
  library may not have (§4.5).
- **`cache_dir()`** returns where sidecars and event logs go. Today
  `lifecycle` and `events` both `from .. import worker` and call
  `worker.cache_dir()` — another upward import that must not survive into
  the library.

The clients keep everything else: the UI keeps its `PaneEngine` Protocol
seam, `FakeEngine`, `PaneContext`, `PaneEvent`, the propose-tool MCP
server, `session_store`/`resume`; the CLI keeps `SessionSpec`, `Outcome`/
`SdkOutcome`, `FAILURE_KINDS`, `LOG_TEMPLATES`, `TRANSPORT`,
`Containment`, the registry and the never-raises contract (**S-48
unchanged**).

### 4.4 What stays with the clients — and why, per item

| Stays | Where | Why |
|---|---|---|
| Both `build_can_use_tool` decision tables | both `charter.py` | §3.1 — disjoint policies; merging puts read-scope logic on the write-security path |
| Both `CharterPaths` | both `charter.py` | same name, disjoint fields — a collision, not a duplication |
| Option assembly beyond the floor | `sdk._build_options`, `backend.options_kwargs` | §2.3 — 16 of 20 keys differ, two semantically |
| Message-to-EVENT mapping | `sdk._map_*`, `backend._map_result_message` | the vocabularies are disjoint (`PaneEvent` vs `Outcome`). **Only the `str` reduction moves** (§2.2a) |
| `run_sync` | `backend.py` | §4.6 R-2 |
| `provider_env` | `invocation_sdk/` | upward import into `provider`/config |
| `LOG_TEMPLATES` and the four surfaces’ failure wording | `invocation/contract.py` | `test_templates_byte_pinned_ro6` is `S-49`’s replacement oracle; untouchable (§9.3) |
| `SessionSpec` / `Outcome` / `FAILURE_KINDS` / `TRANSPORT` | `invocation/contract.py` | the seam contract; `S-48`’s `M11` evidence depends on `TRANSPORT` staying a mutable table where it is |
| `PaneEngine` + `FakeEngine` | `ui engine/base.py` | register ruling 2026-08-20, verbatim: *"the UI keeps its Protocol seam + FakeEngine"* |
| The SDK log-forwarding handler (G-4) | `ui engine/sdk.py` | it installs a handler on a process-global logger; the library must not (§6 `HOST3`) |
| Both `fake_claude.py` fixtures | both `tests/fixtures/` | §2.6 — armor pin, 0.221 similarity |

### 4.5 "Portable" has an exact meaning — speculative generality REFUSED

The user’s framing says *"eventually portable to other projects"*. That is
a constraint on the API, not a licence to generalise. **Portable means
exactly these four things and nothing else:**

1. **No upward imports.** The library imports stdlib and
   `claude_agent_sdk` only. It may not import `self_learn.worker`,
   `.provider`, `.config`, `.hosts`, `.ledger`, `.verbs`,
   `.invocation`, `.invocation_sdk`, or anything under `self_learn_ui`.
   Every value that today comes from such an import
   (`worker.cache_dir()`, `worker._pid_alive()`, `provider.session_env()`)
   arrives through the policy object or as a parameter.
2. **SDK-only dependencies.** No `ruamel.yaml`, no `fastapi`, nothing from
   either package’s dependency list beyond `claude-agent-sdk`.
3. **A fake tests can drive.** The library ships `FakeSdkClient` — a stub
   satisfying the duck-typed client contract (`connect`, `query`,
   `receive_response`, `interrupt`, `disconnect`, and the private
   attribute chain `child_pid_of` walks) — so the library is testable with
   `claude_agent_sdk` absent. **This is what makes the multi-session
   criterion (§6 `MS1`) runnable at all.**
4. **An API designed for exactly THREE consumers** — the pane, the seam,
   and the host process. No configuration knob, no hook, and no
   abstraction may be added for a fourth, hypothetical consumer.
   `HOST3` pins the public symbol set literally so a "convenience"
   addition reddens.

**What this explicitly refuses:** a plugin system, a registry of session
kinds, a generic middleware chain, transport abstraction over anything but
`claude_agent_sdk`, and any public symbol none of the three consumers
calls (`CO4`).

### 4.6 Multi-session — N sessions, one loop, one process

**The library is async-native.** Every entry point that awaits is
`async def`; the library creates no event loop and calls no
`asyncio.run`. `N` sessions run concurrently on one loop.

The three single-session assumptions of §2.9 are FIXED HERE, not deferred:

| Fix | Shape | Instrument |
|---|---|---|
| **F-1 `new_run_id`** | append a collision-free component (`uuid4().hex[:8]`, or a per-process monotonic counter — the builder picks and states which). The `{surface}.tool-events.{run_id}.jsonl` filename SHAPE is preserved so `test_ev3`/`test_ev5`/`test_ev6` keep passing | `MS2`: 10 000 calls in one process yield 10 000 distinct ids |
| **F-2 the pid sidecar** | keyed by surface **and** the session’s own id, not surface alone; the sweep reads all sidecars for a surface and judges each on its own three corroborating checks | `MS3`: two live sessions on one surface, both sidecars present and distinct, neither sweeps the other |
| **F-3 `prune_event_logs`** | retention runs at session END, not START, and never unlinks a file belonging to a run id currently live in this process | `MS4`: session B starting does not unlink session A’s in-flight log |
| **F-4 `_PROCESS_START` (G-1)** | the staleness anchor becomes a parameter resolved at first sweep, not at module import | `MS5`: two sweeps in one process with different anchors decide differently |

**And the finding from §2.2b that multi-session forces a ruling on:**

> **R-1 — kill-ladder step 3 under a persistent loop.** Step 3’s
> unconditional `SIGKILL` exists because `asyncio.run` closes the loop and
> the abandoned `disconnect()` dies unfinished. Under a host process the
> loop does not close. **Ruling: step 3 becomes CONDITIONAL on the caller
> telling the library that the loop is about to close.** The seam’s
> `run_sync` path passes `loop_closing=True` (today’s behaviour,
> byte-identical); the pane and the host process pass `loop_closing=False`
> and let the SDK’s own shielded escalation finish. **Pinned by `LAD6`:**
> under `loop_closing=True` the child is signalled before the coroutine
> returns (today’s `test_kl4` and `test_to6` behaviour, unchanged); under
> `False` it is not, and the abandoned `disconnect()` is observed to
> complete.

> **R-2 — `run_sync` stays out of the library.** Its second branch starts
> a non-daemon thread and joins it unbounded (§2.9); under a host process
> that would block a thread per session. It remains the SEAM’s adapter,
> called from exactly one site (`backend.py:572`), and the host process
> never calls it — it awaits the library directly. `HOST1` pins the
> library free of `asyncio.run`.

### 4.7 Design constraints carried from r1 and the gate

- **C-1 (NORMATIVE, gate-proven).** `run_kill_ladder` **stays in
  `invocation_sdk/lifecycle.py`** as a thin surface function that reads
  its OWN module-level `KILL_SECS` / `INTERRUPT_GRACE_SECS` at CALL time
  and passes them into the library, and `lifecycle._ABANDONED_DISCONNECTS`
  is bound to the library’s registry object by IDENTITY, not copied. The
  gate replayed the five armor-pinned tests against this shape and they
  pass unedited. Zero-re-pin is no longer a criterion (§10.2), but this
  property is still the design, because a monkeypatch that silently stops
  biting is a green-but-blind instrument.
- **C-2.** The library reads no `os.environ`. Every environment-derived
  value arrives through the policy object.
- **C-3.** Sweeps stay scoped — one surface, one session, one pid. No
  sweep-all and no kill-all entry point exists (`HOST3`).
- **C-4.** No process-global logging handler installed by the library
  (G-4 stays UI-side).

### 4.8 Designs rejected, with the measurement that rejected each

| # | Rejected | Why |
|---|---|---|
| R-a | One engine for both clients (option 2) | §3.1 — 0 body-identical functions, 3/20 shared option keys, incompatible session lifetimes, two semantically opposed keys |
| R-b | Rebuild both (option 3) | §3.1 — discards two byte-pinned, burned-in implementations to reach the same seam |
| R-c | Library in the UI package | §2.7 — the CLI cannot import `self_learn_ui`; it does not compile |
| R-d | Its own distribution now | §11 row 9 — new pyproject, lockfile entry, install step and a third version to keep in range, with no non-self-learn consumer yet. Trigger named |
| R-e | Merge the two `build_can_use_tool` | §3.1; `AGR2` is the only detector |
| R-f | Move `run_sync` into the library | §4.6 R-2; `HOST1` |
| R-g | Unify the two `fake_claude.py` | §2.6 — 0.221 similarity, per-function armor pin against `89f8ef7` |
| R-h | A generic session-kind registry / middleware chain | §4.5 — speculative generality, refused by name |

---

## 5. Phase 2 — the host process (`self-learn serve`)

### 5.1 The name, and why it is not new

`self-learn serve`. Measured precedent: the UI already ships
`self-learn-ui serve` (`ui/src/self_learn_ui/cli.py:43`, `:138`), run by
`systemd/self-learn-ui.service` as `ExecStart=%h/bin/self-learn-ui serve`
with `Type=simple`, `Restart=on-failure`, `RestartSec=5`, and a documented
non-systemd fallback in the unit’s own header: *"systemd absent /
non-Linux host (10 §5): the documented fallback is running
`self-learn-ui serve` in the foreground — this unit is a convenience, not
a hard dependency."* `serve` is the house pattern.

Measured: **no `serve` verb exists on the CLI today** — a `grep -c` for
the `add_parser` call with the literal `serve` in
`plugins/self-learn/cli/src/self_learn/cli.py` returns **0**.

**Terminology, fixed here because two units collide on the word "host":**

| Term | Means | Owner |
|---|---|---|
| **canon host** | a registered source repository whose canon surfaces the ledger reads (`self-learn host add/list/rm`, `hosts.yaml`) | `U-hostmode` |
| **host process** / **`serve`** | the long-lived scheduler process this unit builds | `U-engine` Phase 2 |

Neither term may be used bare in any doc this unit touches.

### 5.2 What `serve` owns

| Owns | Replaces | Measured today |
|---|---|---|
| The **miner schedule** | `systemd/self-learn-miner.timer` (`OnCalendar=*-*-* 03:30`, `Persistent=true`, `RandomizedDelaySec=15m`) | linked by `install.sh:98` |
| The **worker follow-on** | `miner.py:2014`’s `worker.kick(home)` into a `setsid` `Popen` | the reap: `Type=oneshot` + `KillMode=control-group`, measured live |
| The **staleness watchdog** | `miner.maybe_kick` (`miner.py:1680-1710`), ticked by every verb but `mine`/`init` (`cli.py:1992`) | `KICK_AFTER_SECS = 24*60*60`, `ATTEMPT_COOLDOWN_SECS = 2*60*60`, a `miner.spawn.lock` `LOCK_EX|LOCK_NB` guard |
| **Per-job timeouts** | nothing — they already exist and are already env-overridable | `SELF_LEARN_INVOKE_TIMEOUT_SECS`, `SELF_LEARN_REPAIR_TIMEOUT_SECS`, `SELF_LEARN_READER_TIMEOUT_SECS`, `SELF_LEARN_ANALYST_TIMEOUT`. **`serve` inherits them unchanged; it does not invent a timeout system** |
| A **journal + heartbeat** | — | the miner already journals per run; the heartbeat is new (§5.6) |

**The #11 handoff dies by construction.** With one live process starting
both jobs, there is no detached child and no `ExecStart` return, so there
is nothing for a cgroup to reap. **Register item #11 (the cgroup patch) is
SUPERSEDED, not fixed** — the three unit-file remedies it named are not
applied; the shape that made them necessary is removed. FW-119 (§12.2)
records that.

### 5.2a Jobs run SERIALLY — ORCHESTRATOR RULING (2026-08-26)

**`serve` runs one job at a time.** It is a scheduler of producers, and
the producers it schedules are already serialised today by their own
locks (`worker.lock` blocking-`flock`, `miner.spawn.lock`
`LOCK_EX|LOCK_NB`). **Serial is therefore the shape that changes nothing
about producer semantics** — the daemon inherits the concurrency the
locks already impose instead of inventing a second, weaker one on top of
them.

**This is a ruling about the DAEMON, not about the library.** The
library stays multi-session by ruling (§4.6, `MS1`-`MS7`): its API takes
no process-wide state, creates no loop, and drives N sessions on one.
`serve` simply chooses to run one.

#### 5.2a.1 Which concurrency fixes survive the serial ruling — each with its evidence

| Fix | Under SERIAL jobs | Evidence |
|---|---|---|
| **F-1 `new_run_id`** | **STILL FORCED** | The id is `strftime("%Y%m%dT%H%M%SZ") + "-" + str(os.getpid())` — one-SECOND resolution plus a pid that no longer changes between jobs. **Two SEQUENTIAL jobs in one long-lived process, started inside the same wall-clock second, collide.** The measurement in §2.9 is itself two SEQUENTIAL calls in one process, not two concurrent ones — it was never a concurrency measurement. `write_event_log` then overwrites the first job’s file |
| **F-3 `prune_event_logs` at session START** | **STILL FORCED, and the reason is CROSS-PROCESS, not serve’s job model** | It globs `worker.cache_dir()` for `f"{surface}.tool-events.*.jsonl"` and unlinks all but the newest N **at the start of a session**. `cache_dir()` is machine-local and namespaced by ledger home, **shared by every self-learn process on the machine** — `serve`, a UI pane, and any verb. Measured: `analyst.analyze` (`analyst.py`) acquires **no lock at all** and is called from `teach.py:683`, i.e. from the operator’s own shell; two `teach --route` shells are two processes both pruning `analyst.tool-events.*`. A starting session can unlink a live session’s log **in another process**, which no job model inside `serve` can prevent |
| **F-2 the pid sidecar** | **DOWNGRADED** — a cleanup-ORDERING requirement, not a concurrency fix | With one job at a time there is never a second live sidecar for a surface. What remains is an ordering obligation between SEQUENTIAL jobs of the SAME surface: job A’s `clear_sidecar` (today in `_drive`’s `finally`) must complete before job B’s `sweep_orphans` reads. If it does not, B reads A’s stale sidecar. **Still specified and still tested — as ordering (`MS1-seq`), not as concurrency (`MS3`)** |
| **F-4 `_PROCESS_START` (G-1)** | **STILL FORCED, and serial makes it WORSE, not better** | The sweep kills a sidecar pid only when `started_at < _process_start()`. Under a verb, `_PROCESS_START` is that verb’s import time, so a child from a previous run is correctly stale. **Under a daemon it is the daemon’s boot time, so a child leaked by job 1 is never `< _PROCESS_START` for job 5 and is never swept** — orphans accumulate for the daemon’s whole lifetime. Serial jobs do not help: every job in the daemon shares the same anchor |

**Net:** three of the four fixes are forced by the daemon regardless of
its job model; one is re-specified as ordering. **None is deferred.**

#### 5.2a.2 Concurrent jobs are OUT, with a named trigger

`serve` running two jobs at once is **OUT of this unit**. **Trigger that
would re-open it: a consumer that needs two live sessions in one
process** — the concrete candidate being the UI pane hosted inside
`serve` (today `self-learn-ui serve` is its own process, so the pane and
the seam never share one). Until such a consumer exists, the library’s
multi-session capability is proven and unused by the daemon, which is
the correct order: capability first, consumer later.

### 5.3 The any-verb watchdog — RULED

**Reduced, not retired.** `miner.maybe_kick` becomes:

1. If `serve` is running (heartbeat fresh, §5.6) — **poke the daemon and
   return `"poked"`**. No spawn from a verb, ever.
2. If `serve` is not running — **today’s behaviour exactly**, including
   the `LOCK_EX|LOCK_NB` spawn guard, the cooldown and the
   `SELF_LEARN_MINER_AUTOKICK=0` / `SELF_LEARN_MINER=0` kill switches.

**Why reduced rather than retired.** Retiring it makes the daemon a hard
dependency for the ledger ever being mined, on machines whose owners have
not adopted `serve` — which is exactly the population `U-hostmode` serves.
**Why reduced rather than left alone.** The covert spawn is a measured
hazard, not a hypothetical: the FW-116 dry-run’s first `doctor` call
landed **five real commits** in a throwaway ledger copy before it was
noticed (`17` §6 item 4, measured 2026-08-26). Under `serve` the covert
path is closed for every adopter, and the runbook’s
`SELF_LEARN_MINER_AUTOKICK=0` instruction stays correct for everyone else.

### 5.4 Daemon state — there is none

Every scheduling fact stays where it is today: a file plus a flock.
`miner.spawn.lock`, `worker.lock`, `worker.window`, the miner run journal,
the cursors. **`serve` reads them and schedules; it remembers nothing
across a restart that is not on disk.** A crashed daemon leaves exactly
the state a crashed verb leaves today, resolved by the same TTLs and
dead-pid checks. This is what answers the crash-safety objection in §3.2
without inventing a persistence layer.

### 5.5 H-5 preserved — `serve` is a SCHEDULER, not a watcher

`13-hosting-and-separation.md` §5: *"the ledger repo needs no autosync
watcher, ever (H-5): producers commit (pinned subjects) and push their own
writes"*, and §8 H-5 adds *"no mutation may precede its `commit_lock`"*.

**`serve` starts producers; producers still commit their own writes, under
their own lock, by their own pathspec, with their own pinned subject.**
`serve` never stages, never commits, never touches the ledger. The
`reconcile` backstop (§5) is unchanged and still runs at the start of
every `mine` and before every `push`.

**The one test change this forces, named.**
`cli/tests/test_lock_invariant.py` derives entrypoints structurally —
`roots = [q for q in analysis.funcs if not callers[q]]` (`:463`), inside
`TestNoMutationPrecedesItsLock::test_no_entrypoint_reaches_a_mutation_without_a_lock`
(`:452`). When `serve` calls `miner.run` and `worker.run`, **those two
stop being roots and `serve`’s own loop becomes one.** Every mutation
reachable from `serve` inherits the lock obligation along a path that did
not exist before. Concretely:

- `serve`’s scheduler loop may appear in `NOT_REPO_TRUTH` **only** if it
  genuinely writes nothing that is a repo’s truth — it writes the
  heartbeat file into `cache_dir()`, which is already the
  `NOT_REPO_TRUTH` category (the XDG cache). Any other write is a
  violation, and the test is fail-closed by design, so it will say so.
- `test_the_exemption_list_cannot_rot` (`:512`) and
  `test_the_analysis_actually_sees_the_code` (`:492`) must both stay
  green, unedited.
- `test_it_catches_a_planted_violation` (`:532`) is the positive control
  and must still fire — `HP7` re-runs it with `serve` present.

### 5.6 Supervision — a dead daemon must be LOUD

Three parts, and the third is the one that matters:

1. **`Restart=on-failure`, `RestartSec=5`** on the reference unit —
   copied from `self-learn-ui.service`, which already ships exactly this.
2. **A heartbeat file** at `cache_dir()/serve.heartbeat`, rewritten on
   every scheduler tick with the tick time, the pid and the next scheduled
   job. In `cache_dir()`, so H-5 and `NOT_REPO_TRUTH` are both satisfied.
3. **The staleness alarm lives OUTSIDE the daemon.** `self-learn doctor`
   grows one `Row(name="serve", ...)` in `provider.py`’s existing row list
   (the shape is `Row(name, verdict, detail)`, verdicts
   `PASS`/`FAIL`/`WARN`/`SKIP`/`INFO`):
   - heartbeat fresh -> `PASS`, naming the next scheduled job;
   - heartbeat present but older than one tick interval -> **`FAIL`**,
     naming the age;
   - no heartbeat and no `serve` configured -> `SKIP` (this machine does
     not use it);
   - no heartbeat but `serve` IS configured -> **`FAIL`**.

   **A daemon that dies silently is the failure mode this whole phase
   would otherwise introduce, and a check that lives inside the daemon
   cannot report the daemon being dead.**

### 5.7 Portability

`serve` runs in the foreground and exits cleanly on `SIGINT`/`SIGTERM`,
so it works under **systemd**, **launchd**, or **a terminal window**, with
no code difference. `systemd/self-learn-host.service` is the REFERENCE
supervisor, not a requirement — the same status
`self-learn-ui.service` already documents for itself.

`install.sh` implications, measured against `install.sh:96-106`:

- links `systemd/self-learn-host.service` next to the existing two units
  and runs `systemctl --user daemon-reload`;
- prints `enable with: systemctl --user enable --now self-learn-host.service`
  and **does not enable it** (the house rule the script states at `:25`);
- prints the non-systemd fallback line, mirroring `:106`;
- **once `serve` is enabled, `self-learn-miner.timer` should not also be
  enabled.** `install.sh` prints that, and `doctor`’s new row reports
  both-enabled as `WARN` — a timer firing a `mine run` alongside a
  daemon-scheduled one is not corruption (`miner.spawn.lock` and
  `worker.lock` still serialise them) but it is double work and it must be
  visible. **A timer MAY survive deliberately as a poke** for an operator
  who wants a belt-and-braces wake-up; that is supported, and the `WARN`
  names it as such rather than calling it broken.

### 5.8 Burn-in

**Coverage is the bar** — the soak-waiver precedent, `S-49`, user ruling
2026-08-24 verbatim: *"as long as we have decent test coverage, then skip
the soak; 2 weeks is crazy-town."*

**Plus exactly one live-behaviour observable**, per the miner-flip
precedent (`17` §5.2, verbatim): ***"Volume within ±1σ of the `cli`
baseline. Candidate counts per night, compared against the preceding
nights. A miner that suddenly finds half as much has changed behavior."***
The same instrument, the same tolerance, applied across the schedule
change: **candidate volume per night within ±1σ of the pre-`serve`
nights.** Nothing else is required, and no orphan-count gate is claimed —
`17` §5.3 records that the scripted-`pgrep`-via-doctor hook *"is not
built"*, and this unit does not build it.

### 5.9 Rollback

**Rollback is a revert** (`17` §6, rewritten 2026-08-25 under `S-49` and
dry-run-measured 2026-08-26 under FW-116). Phase 2 reverts by reverting
its commit and re-enabling `self-learn-miner.timer`; Phase 1 reverts under
Phase 2. **Revert Phase 2 before Phase 1.** Neither phase touches either
`pyproject.toml`, so no dependency reasoning rides the revert.

**The rehearsal trap applies unchanged** (`17` §6 item 4): rehearsing
against a COPY of the ledger requires `SELF_LEARN_MINER_AUTOKICK=0` and a
stripped `origin` first.

---

## 6. Phase 1 criteria — the library

**`[A]` / `[B]` are sub-phase tags WITHIN a phase. There is no default.**

- **1A** — capture every pin, build the library, migrate the CLI side.
  Gate: CLI suite green; the UI product tree **untouched**.
- **1B** — migrate the UI side. Gate: both suites green; the
  cross-surface pins arm.

**39 criteria — 22 [A], 17 [B].**

**DONE WHEN (builder-visible):** all 24 messages of §2.8 are byte-pinned
with their prefixes on both engines and still render identically; the
library drives two concurrent sessions on the fake with independent
ladders and intact event logs; both charters are byte-unchanged; both
suites are green.

### 6.1 PIN — the unit’s real product

§2.8 measured that **18 of 24** library-owned messages are asserted by no
test, and **10 of the 13** operator-visible shutdown messages. A builder
could ship the entire code motion and none of the instruments, and both
suites would stay green while every shutdown message on both engines
silently changed. These four criteria come FIRST.

- **PIN1** **[A]** All **24** messages of §2.8 are byte-pinned **with
  their prefixes**, on both engines, in two NEW files
  (`cli/tests/test_u_engine.py`, `ui/tests/test_engine_shared_core.py`),
  **captured and green at `a0c67be` before any product edit.**
- **PIN2** **[A]** Each pin reaches its message through the **real
  emission path** — drive `run_kill_ladder` / `sweep_orphans` /
  `SdkPaneEngine.close` / `.interrupt` / the session drain against stub
  clients and read the captured log sink. **A pin that asserts a
  `messages()` table against a literal copy of itself is a tautology and
  fails this criterion**; the gate reads the test body, not the colour.
- **PIN3** **[B]** After migration all 24 render byte-identically, and the
  **6 messages that already had coverage still pass through their
  ORIGINAL tests, unedited** (`test_kl3`, `test_kl_major1`,
  `test_kl2_and_kl3_end_to_end`, and the three `test_invocation_sdk.py`
  option/session legs).
- **PIN4** **[A]** Positive control: substituting the OTHER engine’s
  message table must make the pin suite FAIL, observed, on both sides.
  (Without it, a `messages()` wired to a constant reads identically to a
  correct one.)

### 6.2 LIB — the library

- **LIB1** **[A]** `sdksession/` exists at
  `plugins/self-learn/cli/src/self_learn/sdksession/` and its import set
  is **stdlib plus `claude_agent_sdk` only** — no `self_learn.worker`,
  `.provider`, `.config`, `.hosts`, `.ledger`, `.verbs`, `.invocation`,
  `.invocation_sdk`, no `self_learn_ui`. **Instrument:** AST test over
  every `Import`/`ImportFrom` in the package, asserted against a literal
  allowlist.
- **LIB2** **[A]** No `os.environ` / `os.getenv` read anywhere in the
  package. Same AST instrument.
- **LIB3** **[A]** `FakeSdkClient` ships in the library, and a test drives
  a full session against it with **`claude_agent_sdk` absent from
  `sys.modules`** — proving the library is SDK-free in fact, not only in
  its import list, and that `MS1` is runnable.
- **LIB4** **[B]** No orphan symbol: every name in every `__all__` has at
  least one importer in **both** packages. **Instrument:** a test that
  greps both `src` trees per symbol; zero importers on either side
  reddens. This is what stops the library becoming a parking lot (§4.5).
- **LIB5** **[A]** `cd plugins/self-learn/ui && uv run python -c "import
  self_learn.sdksession"` exits 0, rc captured **unpiped**.
- **LIB6** **[A]** `uv build --project plugins/self-learn/cli` produces a
  wheel containing `self_learn/sdksession/__init__.py`
  (`python -m zipfile -l`), rc unpiped.

### 6.3 POL — policy stays with the clients

- **POL1** **[B]** Both `build_can_use_tool` decision tables are
  **byte-unchanged**: `git diff a0c67be` restricted to those two function
  bodies is empty, as are both `CharterPaths`, both fail-closed exception
  classes, and every deny message.
- **POL2** **[B]** The library contains **zero policy**: no tool-name
  literal (`Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob`,
  `NotebookEdit`, `Task`, `WebSearch`, `WebFetch`), no path-scope logic,
  no operator-visible message literal. **Instrument:** an AST/string sweep
  with a **positive control** — the same sweep run against
  `invocation_sdk/charter.py` must report hits, so an empty result cannot
  be an empty search.
- **POL3** **[B]** `option_floor()` returns **exactly** the three keys
  measured identical in §2.3 and a **fresh dict per call** (two calls,
  mutate one, the other is unaffected). Both surfaces obtain their floor
  from it, checked by a spy counted once per construction, asserted on
  options built by each surface’s **real** call path (`S-46` discipline:
  from a captured real `_invoke_reader(home, prompt)` and a real
  `SdkPaneEngine._build_options(ctx)`, never a hand-built spec).

### 6.4 MS — multi-session

- **MS1** **[B]** **Two sessions, one process, one loop, interleaved**, on
  `FakeSdkClient`: both event logs exist, are distinct and are complete;
  both kill ladders run independently; neither session sweeps the other’s
  child; neither unlinks the other’s log.
  **AMENDED at r3, two ways.**
  *(a) It is a PHASE 1 LIBRARY criterion and no longer gates Phase 2.*
  The library is multi-session by ruling (§4.6); the daemon runs jobs
  SERIALLY by ruling (§5.2a). Phase 2’s gate is **`MS1-seq`** (§7.1)
  instead.
  *(b) **What it proves, stated so it is not over-read (gate M-2):** it
  proves the library’s own per-session BOOKKEEPING is not process-global
  — separate run ids, separate event logs, separate sidecars, separate
  ladders. **It does NOT prove that the real Agent SDK transport
  tolerates two concurrent `ClaudeSDKClient` instances in one process**,
  because it runs against an in-process stub. That is an `FW-104`-class
  gap — *"no criterion drives a session against a real model … the
  classes only a live session can surface are structurally out of
  reach"* — and it is **stated, not tested** (§11 row 14). No criterion
  in this unit claims real-transport concurrency, and none may be
  written to imply it.
- **MS2** **[A]** 10 000 `new_run_id()` calls in one process yield 10 000
  distinct ids **REGARDLESS OF SURFACE** — the assertion holds for any
  mix, **including all 10 000 on the SAME surface**, and the test drives
  at least those two shapes (all-same-surface, and an interleaved mix).
  The `{surface}.tool-events.{run_id}.jsonl` filename shape is preserved
  (`test_ev3`/`test_ev5`/`test_ev6` green, unedited).
  **NORMATIVE:** `new_run_id()` takes no arguments today, so a
  surface-keyed counter cannot be reached through its signature — the
  distinctness property must therefore be stated over the CALL SEQUENCE,
  not over a surface partition. **BOTH legs are required, and the gate
  measured why (r3, 10 000 calls per variant):** a per-surface COUNTER
  passes the all-same-surface leg and **fails the interleaved leg**
  (5000/10000 distinct — two surfaces each counting 1, 2, 3 … while the
  id carries no surface); a per-surface SEED **fails both**. Dropping
  either leg lets one of the two variants through green (`M-10`).
- **MS3** **[B]** *(A LIBRARY criterion. Under the serial daemon ruling
  the DAEMON never reaches this state — §5.2a.1 re-specifies F-2 as an
  ordering obligation tested by `MS1-seq` leg 3. This criterion still
  stands, because the library is multi-session by ruling and `serve` is
  not its only future consumer.)* Two live sessions on ONE surface
  produce two distinct sidecars; the scoped sweep judges each on its own three corroborating
  checks and kills neither.
- **MS4** **[B]** Retention runs at session END, and a starting session
  cannot unlink an in-flight log belonging to a live run id.
- **MS5** **[A]** The staleness anchor (G-1) is a parameter, not an
  import-time constant: two sweeps in one process with different anchors
  decide differently.
- **MS6** **[A]** No `asyncio.run`, `get_event_loop`, `new_event_loop` or
  `set_event_loop` anywhere in `sdksession/`, and no module-level loop or
  task creation. AST test. **Discriminates:** a builder who moves
  `run_sync` in to "finish the job" reddens it (§4.6 R-2).
- **MS7** **[A]** The library’s public symbol set across all modules is
  asserted **literally** against §4.2’s list: no sweep-all, no kill-all,
  no `logging.Handler` installed on any logger the library does not own.

### 6.5 LAD — the ladder

- **LAD1** **[A]** **The call-time-read proof, two legs.**
  *Leg 1 (deterministic):* a spy on the library’s teardown entry point;
  with `monkeypatch.setattr(lifecycle_mod, "KILL_SECS", 0.02)`,
  `run_kill_ladder` must hand the spy `kill_secs == 0.02`.
  *Leg 2 (corroboration):* same patch, a client whose `disconnect()`
  sleeps 3600 s, the call returns in **under 0.5 s** (25x the patched
  bound, 5x under the unpatched 2.5 s).
  **Leg 1 is the real detector** — an import-time default leaves leg 2
  green on a fast machine and the instrument silently blind.
- **LAD2** **[A]** `invocation_sdk.lifecycle._ABANDONED_DISCONNECTS`
  **is** the library’s registry object — identity, not equality. A copy
  passes an equality check and breaks the pinned tests on the next task.
- **LAD3** **[B]** UI side: `engine.sdk._ABANDONED_DISCONNECTS` is the
  same object; `DEFAULT_INTERRUPT_GRACE_SECS` / `DEFAULT_INTERRUPT_KILL_SECS`
  are the library’s objects by identity; and
  `test_engine_sdk.py::test_default_ladder_constants_match_the_tuned_pin`
  passes **unmodified**.
- **LAD4** **[B]** **`R-1`, both directions.** With `loop_closing=True`
  the child is signalled before the coroutine returns —
  `test_kl4_hang_sigterm_ignored_child_is_gone_after_run_sync_returns` and
  `test_to6_kill_ladder_three_rungs_and_pgid_discrimination` green,
  behaviour byte-identical. With `loop_closing=False` it is NOT signalled,
  and the abandoned `disconnect()` is observed to run to completion.
  **Both legs required**: a build that hard-codes either value passes one
  and fails the other.

### 6.6 AGR — cross-surface

- **AGR1** **[B]** **Agreement on target-path extraction.** One table of
  `tool_input` dicts (each key alone, all three present for precedence,
  empty-string values, non-string values, empty dict) drives **both
  surfaces’ real `build_can_use_tool`-produced callbacks**, and the
  resolved target paths are byte-identical (read out of the
  `PermissionResultDeny.message`, which names the target on both sides).
  **NORMATIVE:** the test may NOT call the shared
  `extract_target_path` twice — after unification that is a tautology and
  measures nothing.
- **AGR2** **[B]** **Disagreement, and it must survive.** Two fixed
  inputs: (i) a `Read` under the resolved ledger home is **ALLOW** on the
  UI charter and **DENY** on the CLI charter; (ii) a `Write` matching a
  CLI `write_glob` is **ALLOW** on the CLI charter and **DENY** on the UI
  charter. Both deny messages byte-pinned including their distinct
  prefixes. **This is the only detector for the over-reach of merging the
  two charters** (§3.1, §4.8 R-e).
- **AGR3** **[B]** **Agreement on the error-detail reduction** (§2.2a’s
  1.000 pair). One table of `ResultMessage` shapes — `errors` non-empty,
  `errors` empty with `result` set, both empty with only `subtype`,
  `errors` with one element, `result` an empty string — driven through
  each engine’s **real** mapping (`SdkPaneEngine._map_result` and
  `backend._map_result_message`), producing byte-identical strings.

### 6.7 UN — behaviours that must not move

- **UN1** **[A]** `test_invocation_sdk.py::test_templates_byte_pinned_ro6`
  green, file unedited. It is `S-49`’s replacement for the deleted
  cross-backend oracle; losing it silently would be this unit’s worst
  outcome.
- **UN2** **[A]** `S-48`: `test_ou5_bare_oserror_caught_on_worker_miner_and_analyst`
  and `test_u_sdka.py::test_hd4_seam_is_total_on_the_analyst_surface`
  green, unedited; `TRANSPORT` byte-unchanged in `contract.py`.
- **UN3** **[A]** `S-44`: `test_ev1`, `test_ev2`,
  `test_ev4_nothing_in_the_package_reads_a_tool_events_file` green;
  `SdkOutcome`’s five extra fields byte-unchanged; **the filesystem diff
  remains the attribution authority** — nothing in this unit reads
  `tool_events` or `denials`.
- **UN4** **[B]** The four UI ladder tests
  (`test_hung_sdk_interrupt_call_escalates_to_close_within_grace`,
  `test_hung_disconnect_is_abandoned_within_kill_window`,
  `test_abandoned_disconnect_still_runs_to_completion`,
  `test_hung_interrupt_then_hung_disconnect_still_returns`) green,
  **unedited**.
- **UN5** **[A]** All six tests of §2.5 that reach `lifecycle`’s module
  globals are green. **Under design constraint C-1 they are unedited**; if
  a builder edits any of them, §10.2’s re-pin procedure applies and must
  be discharged in full.

### 6.8 BND — boundaries

- **BND1** **[A]** `invocation_sdk/` keeps its import bounds:
  `charter.py` still does not import `.events`; no module imports
  `self_learn_ui`.
- **BND2** **[B]** `ui/src/self_learn_ui/engine/` gains **exactly one**
  new module-scope import root (`self_learn.sdksession`); the pre-existing
  lazy `from self_learn.hosts import ...` in
  `charter.default_canon_read_roots` is unchanged and still fail-closed.
- **BND3** **[A]** CLI `src` contains **zero** imports of `self_learn_ui`.
  **Positive control in the same command**: the identical grep with a
  pattern known present must return a nonzero count, so an empty result
  cannot be an empty search.
- **BND4** **[A]** `test_ev4`’s "nothing reads a tool-events file" sweep
  **covers `sdksession/`** — verified by reading its path derivation, and
  extended in the NEW file (never by editing the pinned one) if it globs
  `invocation_sdk/` only.

### 6.9 SUITE

- **S1A** **[A]** `plugins/self-learn/cli/scripts/suite` returns **rc=0**
  with **>= 2345 passed, 6 skipped, 0 failed**; and
  `git diff --stat a0c67be -- plugins/self-learn/ui/src` is **empty**
  (1A may not touch the UI product tree).
- **S1B** **[B]** Both suites: CLI rc=0 as above; UI **1239 passed + the
  new pin file**, with `test_service_unit.py::test_both_units_document_manual_registration_via_symlink`
  the ONLY failure.
- **S1C** **[B]** Reconciliation: no pre-existing test deleted or renamed;
  the collected-count delta equals the new tests, named individually.
  **Instrument:** per-file `pytest --collect-only -q` diff against
  `a0c67be`, published in the build report.

---

## 7. Phase 2 criteria — the host process

- **2A** — `serve` exists and runs in SHADOW: it schedules, heartbeats and
  reports, but `self-learn-miner.timer` is still the authority and the
  watchdog is unchanged.
- **2B** — `serve` becomes the schedule: the timer is disabled by the
  runbook, the watchdog is reduced (§5.3), the handoff runs in-process.

**18 criteria — 11 [A], 7 [B].**

**DONE WHEN (builder-visible):** `serve` runs under systemd, under no
supervisor at all, and exits cleanly; a mine job hands off to a worker job
inside the one process with no `Popen` and no `setsid`; killing `serve`
makes `doctor` say **FAIL**; `test_lock_invariant.py` is green with
`serve` in the call graph; both suites are green.

### 7.1 HP — the process

- **MS1-seq** **[A]** **SEQUENTIAL jobs in one process — the criterion
  that replaces `MS1` as Phase 2’s gate (§5.2a).** Driven on
  `FakeSdkClient` inside a real `serve` scheduler loop, **two jobs of the
  SAME surface and two jobs of DIFFERENT surfaces**, run one after the
  other in one long-lived process, with the two same-surface jobs
  **FORCED into the same clock second** — the test **freezes the time
  source `new_run_id` reads** (monkeypatch `events`’s `time.gmtime` to a
  fixed `struct_time` for the duration of both jobs), it does **not**
  rely on the two jobs happening to land in one wall-clock second.
  **NORMATIVE (gate N-2):** left to wall-clock luck, the F-1 condition
  holds only sometimes, so this criterion’s own positive control can
  silently fail to fail — a green run would then mean "the second boundary
  fell between the jobs", not "the fix works". Freezing the clock makes
  the collision condition deterministic in both directions:
  1. **distinct run ids** for every job, and therefore distinct
     `{surface}.tool-events.{run_id}.jsonl` paths;
  2. **both event logs intact and complete** after the second job ends —
     job 1’s file is neither overwritten nor pruned away by job 2
     starting (`MS4`);
  3. **the pid sidecar is cleaned BETWEEN jobs** — job 2’s
     `sweep_orphans` observes no sidecar from job 1, asserted by reading
     the sidecar path between the two jobs, not by inferring it from a
     green sweep;
  4. **the heartbeat advanced** between the two jobs (`SUP1`).
  **Positive control required:** with the run-id fix reverted, leg 1 must
  FAIL — observed, in the same test file — because two sequential jobs in
  one second is exactly the collision §2.9 measured, and a criterion that
  cannot fail on the defect it names is not a criterion.

- **HP1** **[A]** `self-learn serve` exists, runs in the foreground, and
  exits **0** on `SIGTERM` and on `SIGINT` within a stated bound, with no
  job left mid-flight. Driven as a real subprocess in the test.
- **HP2** **[A]** `serve` **awaits the library directly**: zero
  `run_sync` calls and zero `asyncio.run` calls on any path reachable from
  `serve`. AST test over the call graph. (§4.6 R-2 — otherwise every
  session blocks a thread.)
- **HP3** **[A]** `serve` **never stages, commits, pushes or writes into
  the ledger**. It starts `miner.run` / `worker.run` as jobs and writes
  exactly one file, the heartbeat, into `cache_dir()`. **Instrument:** an
  AST/grep sweep of everything reachable from `serve` for
  `gitops.stage`/`gitops.commit`/`git add`/`git commit`/`Record.write`,
  with a **positive control** (the same sweep over `verbs.py` must report
  hits).
- **HP4** **[B]** **The handoff completes in-process.** Driven on the
  fake: a mine job that lands records is followed by a worker job started
  by `serve` in the SAME process — asserted by the absence of any
  `subprocess.Popen` call during the handoff and by both jobs appearing in
  one journal. **This is register item #11, closed by construction.**
- **HP5** **[B]** Per-job timeouts are honoured under `serve` and are
  still env-overridable: `SELF_LEARN_INVOKE_TIMEOUT_SECS`,
  `SELF_LEARN_REPAIR_TIMEOUT_SECS`, `SELF_LEARN_READER_TIMEOUT_SECS`,
  `SELF_LEARN_ANALYST_TIMEOUT` each still bite, asserted through a job
  `serve` scheduled.
- **HP6** **[A]** **The reduced watchdog, both legs.** With a fresh
  heartbeat, `miner.maybe_kick` returns `"poked"` and **spawns nothing**
  (asserted by a `Popen` spy that must record zero calls). With no
  heartbeat, its behaviour is **byte-identical to today**, including the
  `LOCK_EX|LOCK_NB` guard, the cooldown, and `SELF_LEARN_MINER_AUTOKICK=0`
  / `SELF_LEARN_MINER=0` still returning `"disabled"`.
- **HP7** **[A]** `test_lock_invariant.py` is **green with `serve` in the
  call graph** — all four tests, including
  `test_it_catches_a_planted_violation` (`:532`), the positive control
  that proves the walker still fires. Any `NOT_REPO_TRUTH` addition is
  **exactly** the heartbeat write, with its justification stated in-line
  as that list requires (§5.5).

### 7.2 SUP — supervision

- **SUP1** **[A]** The heartbeat is written on every scheduler tick into
  `cache_dir()/serve.heartbeat`, carrying the tick time, the pid and the
  next scheduled job; it is never written into a git repo.
- **SUP2** **[A]** `doctor`’s new `serve` row has **all four verdict legs
  asserted**: fresh -> `PASS` naming the next job; stale -> `FAIL` naming
  the age; absent-and-unconfigured -> `SKIP`; absent-but-configured ->
  `FAIL`.
- **SUP3** **[A]** **The alarm is genuinely outside the daemon.** Start
  `serve`, kill it, run `doctor`, and **observe the `FAIL`** — not merely
  the absence of a `PASS`. A check that lives inside the daemon cannot
  report the daemon being dead, and a test that asserts "not PASS" passes
  when the row is missing entirely.
- **SUP4** **[B]** Timer **and** `serve` both enabled reports **`WARN`**
  (not `FAIL`), and the detail names the deliberate poke configuration
  (§5.7) rather than calling it broken.

### 7.3 PORT — portability

- **PORT1** **[A]** `serve` starts, ticks and exits cleanly **with no
  systemd present** — run as a subprocess in an environment with
  `systemctl` absent from `PATH`. This is the criterion the whole
  portability argument (§3.2) rests on, so it is executed, not asserted in
  prose.
- **PORT2** **[B]** `install.sh` links `systemd/self-learn-host.service`,
  runs `daemon-reload`, **does not enable it**, prints the
  `enable --now` line, prints the non-systemd fallback, and prints the
  timer warning — asserted against the script’s own output, in the style
  `install-commands-test.sh` already uses.
- **PORT3** **[B]** The unit file mirrors `self-learn-ui.service`’s
  conventions: `Type=simple`, `Restart=on-failure`, `RestartSec=5`,
  `Environment=SELF_LEARN_HOME=%h/.self-learn`, a `%h`-relative
  `ExecStart`, and the comment header naming the manual-registration step.
  `ui/tests/test_service_unit.py`’s conventions tests are extended to the
  third unit. *(Note: that file carries the suite’s ONE known
  pre-existing failure,
  `test_both_units_document_manual_registration_via_symlink`. Extending
  the file must not change that failure’s status in either direction —
  it stays the only failure, and it stays failing for its existing
  reason.)*

### 7.4 SUITE

- **S2A** **[A]** Both suites green at 2A, with `self-learn-miner.timer`
  still authoritative and the watchdog unchanged.
- **S2B** **[B]** Both suites green at 2B.
- **S2C** **[B]** The burn-in observable is **named and recorded** in the
  runbook before the phase merges: candidate volume per night within
  **±1σ** of the pre-`serve` nights (§5.8). Recording it is the criterion;
  collecting it is operator work after the merge.

---

## 8. Mutation plans

**No cell may be `measured` for code this unit has not written**
(`U-cleanup` §10’s rule). All rows below are `predicted`. Three
**measured anchors** exist because they are measurements of the CURRENT
tree.

### 8.1 Measured anchors, at `a0c67be`

| # | Measurement | Result |
|---|---|---|
| **A1** | Whole-symbol AST census across both trees | **0 body-identical pairs**; 4 name-identical symbols, all different bodies; 3 of 20 option keys identical |
| **A2** | **Fragment-level** census (normalised control-flow fragments >= 4 lines) — the instrument r1 lacked | **3 skeleton-identical pairs = 2 distinct mechanisms**: the `ResultMessage` error-detail chain (6/6, ratio **1.000**) and the target-path key loop (4/4, **1.000**) |
| **A3** | Pin coverage over all 24 library-owned messages, two patterns each (full-with-prefix, distinctive tail), false positives verified by hand | **5 with prefix, 1 prefix-free only, 18 asserted nowhere.** Shutdown subset (13): **2 / 1 / 10** |

**A3 is why §6.1 comes first.** The most likely defect in this unit is a
wrong or missing message, and today the suites would notice in at most 6
of 24 places — one of those 6 blind to the prefix, which is precisely the
part that becomes a parameter.

### 8.2 Phase 1 mutations — all `predicted`

| # | Mutation | Must fail | Note |
|---|---|---|---|
| **M-1** | The CLI passes `prefix="run: sdk: "` (a plausible shortening) | **PIN1**, **PIN3** | the dominant defect; A3 shows today only 3 of 14 CLI messages would notice |
| **M-2** | The UI is wired with the CLI message table (copy-paste while porting the second surface) | **PIN4**, **PIN1** | invisible to every existing test — A3: 0 of 10 UI messages are asserted |
| **M-3** | `messages()` returns a table, and the pin test asserts that table against a literal copy of itself | the **gate**, reading the test body — `PIN2` | instrument criterion; the suite cannot catch it |
| **M-4** | `shielded_disconnect(kill_secs: float = KILL_SECS)` — an import-time default, called with no argument | **LAD1 leg 1**; **MS7** | `LAD1` leg 2 alone stays green on a fast machine — the green-but-blind shape |
| **M-5** | `lifecycle._ABANDONED_DISCONNECTS = set(library_registry)` (a copy) | **LAD2** | an equality check passes; only identity catches it |
| **M-6** | Merge the two `build_can_use_tool` behind one `policy=` switch | **AGR2** both legs; **POL1** | **nothing else in this spec reddens** |
| **M-7** | `option_floor()` also folds `permission_mode` and `settings` (CLI-only keys) | **POL3**’s exact-key-set clause | without that clause nothing catches it |
| **M-8** | `option_floor()` returns a module-level dict; one surface mutates it | **POL3**’s fresh-dict clause | the shared-mutable-default class |
| **M-9** | The error-detail reduction is moved but the UI keeps its own copy | **LIB4** (the CLI-side symbol has no UI importer) | the "extract and forget to adopt" shape |
| **M-10** | `new_run_id` gains a per-SURFACE counter, or a per-surface seed, rather than a per-process one — reached by threading a surface argument in, or by keying an internal table on the caller | **MS2 — and which LEG kills it depends on the variant, so both are required.** Per-surface COUNTER: passes all-same-surface, **dies on the interleaved leg**. Per-surface SEED: **dies on both** | **measured by the spec gate at r3** (10 000 calls per variant: the counter yields 5000/10000 distinct interleaved and 10000/10000 same-surface; the seed fails both). *r2 wrote this as dying "across two surfaces" and r3 wrote it as dying on the all-same-surface leg — both were wrong for the counter variant, which is the whole reason MS2 keeps two legs* |
| **M-11** | Retention still runs at session start, but skips only files newer than N seconds | **MS4** | a slow live session is still eligible |
| **M-12** | The sidecar is keyed by surface + pid instead of surface + session id | **MS3** | two sessions sharing a pid (the same process) collide again |
| **M-13** | `run_sync` moved into the library "to finish the job" | **MS6** | §4.6 R-2 |
| **M-14** | The library installs the SDK log-forwarding handler (G-4) so both clients get it | **MS7** | process-global logger mutation from a shared library |
| **M-15** | `loop_closing` hard-coded `True` (today’s behaviour everywhere) | **LAD4** second leg | the pane and `serve` would SIGKILL a child mid-graceful-teardown |
| **M-16** | `loop_closing` hard-coded `False` | **LAD4** first leg; `test_kl4`, `test_to6` | the seam would leak a wedged child |
| **M-17** | The library imports `self_learn.worker` for `cache_dir()` | **LIB1** | the upward import §4.5 forbids; it is also what makes the library unportable |
| **M-18** | A message literal is left in the library instead of the policy table | **POL2** (with its positive control) | |
| **M-19** | Phase 1 landed as ONE commit spanning both packages | **S1A**’s empty-UI-diff clause | instrument criterion |
| **M-20** | `AGR3` written against the shared reduction called twice | the **gate**, reading the test body | the `M-3` shape applied to the second agreement pin |

### 8.3 Phase 2 mutations — all `predicted`

| # | Mutation | Must fail | Note |
|---|---|---|---|
| **N-1** | `serve` schedules the worker by calling `worker.kick` (today’s `setsid` `Popen`) instead of running the job in-process | **HP4** | the handoff would still die under a supervisor that reaps the cgroup — the whole point |
| **N-2** | `serve` commits the ledger itself "since it is already running" | **HP3** (with its positive control) | **this is the H-5 violation**; doc 13 §5 is the invariant |
| **N-3** | `serve` drives sessions through `run_sync` | **HP2** | one thread per session |
| **N-4** | The staleness alarm is implemented INSIDE `serve` (it logs when it notices it is late) | **SUP3** | a dead daemon reports nothing; this is the failure mode Phase 2 would otherwise introduce |
| **N-5** | `doctor`’s `serve` row returns `SKIP` when configured-but-absent | **SUP2** fourth leg | a dead configured daemon reads as "not applicable" |
| **N-6** | `SUP3` written as `assert row.verdict != "PASS"` | the **gate**, reading the test body — and a missing row passes it | instrument criterion, the fail-open shape |
| **N-7** | `maybe_kick` retired outright | **HP6** second leg | machines without `serve` would never mine again |
| **N-8** | `maybe_kick` left unchanged | **HP6** first leg | the covert spawn survives for adopters — the FW-116 hazard |
| **N-9** | `serve` writes the heartbeat into the ledger home rather than `cache_dir()` | **HP7** (`NOT_REPO_TRUTH` is fail-closed and will say so), **SUP1** | |
| **N-10** | `serve` added to `NOT_REPO_TRUTH` wholesale to make the walker green | **HP7** — the exemption must be exactly the heartbeat, justified in-line | the "escape the fail-closed list" shape the walker’s own docstring warns about |
| **N-11** | `install.sh` enables the unit | **PORT2** | the house rule at `install.sh:25` |
| **N-12** | `serve` requires systemd (reads `systemctl`, or refuses without it) | **PORT1** | the portability argument was the deciding one |
| **N-13** | Both-enabled reported as `FAIL` | **SUP4** | the deliberate poke configuration is supported, not broken |

---

## 9. Files this unit may touch

Anything not listed is out of bounds.

### 9.1 Phase 1A

| Path | Change |
|---|---|
| `cli/src/self_learn/sdksession/{__init__,session,teardown,children,events,result,toolpaths,policy,ladder}.py` | **NEW** — §4.2 |
| `cli/src/self_learn/sdksession/fake.py` | **NEW** — `FakeSdkClient` (§4.5 item 3) |
| `cli/src/self_learn/invocation_sdk/lifecycle.py` | EDIT — delegates to the library; **`run_kill_ladder` stays here** and reads its own `KILL_SECS`/`INTERRUPT_GRACE_SECS` at call time (C-1); registry bound by identity |
| `cli/src/self_learn/invocation_sdk/events.py` | EDIT — delegates; keeps `worker.cache_dir()` and passes it in |
| `cli/src/self_learn/invocation_sdk/backend.py` | EDIT — `_run_session` delegates; `options_kwargs` splats the floor; `_map_result_message` uses the shared reduction. **`run_sync` unchanged and stays here** |
| `cli/src/self_learn/invocation_sdk/charter.py` | EDIT — `P` / `_extract_target_path` become imports. **Decision table, deny messages, `CharterPaths`, the compilers, the `P-b` comment and `CharterPatternUnsupported` UNCHANGED** |
| `cli/src/self_learn/invocation_sdk/policy_impl.py` *(name at builder discretion)* | **NEW** — the CLI’s `SessionPolicy`: its charter, its floor, its message table, `provider_env`, `worker.cache_dir()` |
| `cli/tests/test_u_engine.py` | **NEW** — PIN (CLI half), LIB, MS, LAD1/LAD2, BND, POL2 |
| `ui/tests/test_engine_shared_core.py` | **NEW, in 1A** — PIN2 captured against the UNCHANGED UI engine |

### 9.2 Phase 1B

| Path | Change |
|---|---|
| `ui/src/self_learn_ui/engine/sdk.py` | EDIT — `close`/`interrupt`/`_drain` delegate; `_log_abandoned_disconnect` and the registry rebound; `DEFAULT_INTERRUPT_*` rebound; `_build_options` splats the floor; `_map_result` uses the shared reduction. **The propose-tool server, `session_store`/`resume`, the PaneEvent mapping and the Esc-anchored deadline arithmetic UNCHANGED** |
| `ui/src/self_learn_ui/engine/charter.py` | EDIT — `_PATH_KEYS` / `_extract_target_path` become imports. **Everything else UNCHANGED** |
| `ui/src/self_learn_ui/engine/policy_impl.py` *(or inside `sdk.py`)* | **NEW/EDIT** — the UI’s `SessionPolicy` |
| `ui/tests/test_engine_shared_core.py` | EDIT — AGR1/2/3, LAD3/LAD4, BND2, MS1 |
| `cli/tests/test_u_engine.py` | EDIT — LIB4, POL1/POL3 |

### 9.3 Phase 2

| Path | Change |
|---|---|
| `cli/src/self_learn/serve.py` | **NEW** — the scheduler loop, heartbeat, job runner |
| `cli/src/self_learn/cli.py` | EDIT — one `add_parser` for `serve` |
| `cli/src/self_learn/miner.py` | EDIT — `maybe_kick` gains the poke leg (§5.3). **`run` itself unchanged** |
| `cli/src/self_learn/provider.py` | EDIT — one new `doctor` `Row` |
| `systemd/self-learn-host.service` | **NEW** |
| `install.sh` | EDIT — link + daemon-reload + the three printed lines |
| `cli/tests/test_serve.py` | **NEW** — HP, SUP, PORT1 |
| `cli/tests/test_lock_invariant.py` | EDIT **only** if `NOT_REPO_TRUTH` needs the heartbeat entry (§5.5) |
| `ui/tests/test_service_unit.py` | EDIT — extend the conventions tests to the third unit (PORT3) |
| `docs/specs/self-learn/{03,12,13,14,17}` | EDIT — §12 |

### 9.4 Explicitly NOT touchable, either phase

`invocation/contract.py` (any line — `SessionSpec`, `Outcome`,
`FAILURE_KINDS`, `LOG_TEMPLATES`, `TRANSPORT`, `Containment`,
`DEFAULT_BACKEND_FOR_SURFACE`), `invocation/registry.py`,
`invocation/fake.py`, `invocation_sdk/__init__.py` (it is
`getattr`-probed by `provider.py:625`; widening it is a doctor change
wearing an extraction’s clothes), `invocation_sdk/provider_env.py`’s
body, `worker.py`, `analyst.py`, `engine/base.py`, `engine/__init__.py`,
`pane.py`, `runner.py`, either `pyproject.toml`, either
`fake_claude.py`, and — in Phase 1 — all seven `_ARMOR_SHAS` files.

---

## 10. Sequencing, armor, risk

### 10.1 Order

1. **Capture, then move.** PIN1/PIN2/PIN4 green at `a0c67be`, each shown
   to fail under a one-character mutation, **before any product edit**.
   A3 measured that 18 of 24 messages have no pin at all; capturing after
   the move would pin whatever the move produced.
2. **1A**, then **1B**, then **2A**, then **2B**. Each is independently
   revertible; each has its own suite gate.
3. Phase 2 does not start until **`MS1-seq`**’s Phase 1 precondition —
   `MS2` (run-id distinctness), `MS4` (retention at session end) and
   `MS5` (the parameterised staleness anchor) — is green. **`MS1`
   itself no longer gates Phase 2** (§5.2a: the daemon runs jobs
   serially), but it remains a Phase 1 merge criterion, because the
   library is multi-session by ruling and an unproven capability is a
   claim, not a capability.

### 10.2 Armor — which pins each phase re-derives, and the proof for a
rename-only re-pin

**Zero-re-pin is no longer a criterion** (it was `ARM1` in r1). The
enlarged scope makes it a target, not a requirement:

| Phase | Expected re-pins | Basis |
|---|---|---|
| **1A** | **None expected.** The gate replayed the five armor-pinned `test_kl*` tests against the C-1 shape and they pass unedited | design constraint C-1 (§4.7) |
| **1B** | **None** — 1B touches only `plugins/self-learn/ui`, and no UI file is in `_ARMOR_SHAS` | |
| **2** | **None expected** — `serve` adds files; it edits `miner.py`, `cli.py` and `provider.py`, none of which is pinned | |

**If a re-pin becomes unavoidable**, the builder must discharge ALL of:

1. **State which of the seven** (`conftest.py`, `backends.py`,
   `test_invocation.py`, `test_invocation_sdk.py`, `test_u_fake.py`,
   `test_worker.py`, `test_repair.py`) and why C-1 could not be honoured.
2. **The reverse-rename proof, for a rename-only re-pin.** Copy the
   re-pinned file into a scratch path, apply the INVERSE rename
   (`sdksession` -> the old symbol name, and so on), and show
   `sha256` of the result equals the OLD pinned sha **and**
   `git diff --stat` against `a0c67be` for that scratch file is empty.
   That is what makes "rename-only" a measured claim rather than an
   assertion. If the inverse does not reproduce the old sha, the change is
   **not** rename-only and must be justified line by line.
3. **The prior diff footprint**: `git diff a0c67be -- <path>` published in
   the build report, so a reviewer sees exactly what moved.
4. `_ARMOR_SHAS` updated with a dated comment naming this unit, in the
   style the constant already uses for U-flip and U-cleanup-A.
5. `_SU4B_DIFF_EXEMPT` membership **unchanged** — only hashes move.

`test_su4b_fake_claude_additive_only` must pass with
`_SU4B_SANCTIONED_EDITED_FUNCS` / `_SU4B_SANCTIONED_NEW_FUNCS`
byte-unchanged in **both** phases; neither `fake_claude.py` is touched
(§9.4).

### 10.3 Risks

| # | Risk | Mitigation |
|---|---|---|
| K-1 | **A wrong or missing message, silently.** A3: 18 of 24 unpinned | §6.1 as preconditions with positive controls; M-1, M-2, M-3 |
| K-2 | **The over-reach: merging the charters.** The word "unify" invites it | §3.1, §4.8 R-e, **AGR2 is the only detector**, M-6 |
| K-3 | **Speculative generality** — "portable to other projects" read as a licence | §4.5 refuses four named shapes; `LIB4` (no orphan symbol) and `MS7` (literal symbol set) are the instruments; R-h |
| K-4 | **A tautological agreement pin** | `PIN2`, `AGR1`’s NORMATIVE clause, M-3, M-20; the gate reads test bodies |
| K-5 | **`loop_closing` collapses to a constant** | `LAD4` requires BOTH directions; M-15, M-16 |
| K-6 | **H-5 breached by a daemon that "helpfully" commits** | `HP3` with a positive control; N-2; §5.5 |
| K-7 | **A silently dead daemon** | `SUP3` observes the FAIL; N-4, N-6 |
| K-8 | **Timing flake in `LAD1` leg 2 / `HP1`’s exit bound** | leg 1 is the deterministic detector; bounds chosen with a 25x margin; `HP1` asserts exit code and no mid-flight job, not a wall-clock figure |
| K-9 | **Phase 2 built on unproven multi-session** | §10.1 item 3 — `MS1` gates the phase, not just the merge |
| K-10 | **The `host` word collision confusing a reader or a later unit** | §5.1’s terminology table; §11 row 3 |

---

## 11. Scope — OUT, with owners

| # | Item | Why out | Owner |
|---|---|---|---|
| 1 | **Merging the two charters** | §3.1 — disjoint policies; merging puts read-scope logic on the write-security path. **Never**, not "later" | none; permanent |
| 2 | **`U-corrob`** — the `tool_events`/`denials` consumer | `S-44`: capture-now/consume-later, **the filesystem diff stays the authority**. This unit moves the capture and reads neither field. After this unit | `U-corrob` |
| 3 | **`U-hostmode`** — git-optional **canon hosts**, the once-set knob | A different "host" (§5.1’s terminology table). Queued 2026-08-26 16:25 per the user ruling *"other users might find it cumbersome"* | `U-hostmode` |
| 4 | **`U-ancestry`** | Named by the user ruling of 2026-08-26 21:10 as a parallel unit after the engine unit settles | `U-ancestry` |
| 5 | **SDK version bumps** (`>=0.2.116` toward `>=0.2.121`) | `U-cleanup` §13.2 row 3, unchanged: *"a version decision riding a deletion diff is how a version decision goes unreviewed"* | its own gated unit |
| 6 | **Behaviour improvements to the SDK backend beyond what multi-session forces** | Phase 1 is a zero-behaviour-change phase. The four multi-session fixes (F-1..F-4) and the `loop_closing` ruling (R-1) are IN because concurrency forces them; nothing else is | its own gated unit |
| 7 | **The three unit-file cgroup remedies** (`KillMode=process`, `systemd-run --scope`, a chained worker unit) | **Superseded, not applied** — §5.2. The shape that made them necessary is removed | none; superseded |
| 8 | **Unifying the two `fake_claude.py` fixtures** | §2.6 — 0.221 similarity and a per-function armor pin against `89f8ef7`; the cost is an armor re-anchor for a fixture | none; deliberate |
| 9 | **Own-distribution packaging for the library** | §4.8 R-d. **Trigger, named: the first consumer outside this repository.** Until one exists, a new pyproject, lockfile entry, install step and third version-range is cost with no benefit | forward-work map (unowned until the trigger fires) |
| 10 | **Unifying the two `CharterPaths` names** | A name collision with disjoint fields; renaming removes no defect | none; deliberate |
| 11 | **`invocation_sdk.orphan_report`** — the doctor hook `provider.py:625` probes for and nothing exports | A doctor feature. This unit must not accidentally satisfy it (§9.4) | forward-work map (unowned) |
| 12 | **Any `LOG_TEMPLATES` change**, including "fixing" the analyst’s missing `run: ` prefix | `FW-110` owns the divergence; `test_templates_byte_pinned_ro6` is `S-49`’s replacement oracle | `FW-110` |
| 13 | **The scripted-`pgrep`-via-doctor orphan hook** | `17` §5.3 records it as not built; Phase 2 does not build it and claims no orphan gate | forward-work map (unowned) |
| 14 | **CONCURRENT jobs in `serve`** — two jobs running at once | §5.2a: ruled SERIAL. The producers are already serialised by `worker.lock` / `miner.spawn.lock`, so serial changes nothing about producer semantics, and a second concurrency model layered on the locks is a weaker one. **Trigger that re-opens it: a consumer that needs two live sessions in ONE process** — the concrete candidate is the UI pane hosted inside `serve` (today `self-learn-ui serve` is a separate process, so pane and seam never share one) | forward-work map (unowned until the trigger fires) |
| 15 | **Proving the real Agent SDK transport tolerates two concurrent `ClaudeSDKClient`s in one process** | `MS1` runs against an in-process stub and proves per-session BOOKKEEPING only. Real-transport concurrency is an **`FW-104`-class** gap — *"no criterion drives a session against a real model … the classes only a live session can surface are structurally out of reach"*. **Under the serial ruling nothing in this unit needs it**, so it is **STATED, NOT TESTED**: `MS1`’s own text carries the caveat, and no criterion may be worded to imply otherwise | `FW-104` (the live-burn-in row) |

---

## 12. Docs owed at merge

`S-42`’s rule: a unit’s decision rows land in the SAME commit as its
build.

### 12.1 `03-decisions.md` — one new row after `S-49`

**`S-50`** — the text is **§3 of this spec, in full** (§3.1 the four-option
choice, §3.2 the host-process adoption with its pros/cons). Provenance
cell: this spec; user rulings 2026-08-26 21:10 (*"we deal with the engine
unit first"*) and 22:01 (*"adopt the host process"*); landed in the same
commit as Phase 1, amended in Phase 2’s commit with the shipped `serve`
surface.

**No amendment to any existing row is owed.** Checked row by row: `S-32`,
`S-43`, `S-44`, `S-45`, `S-46`, `S-47`, `S-48`, `S-49` all survive
verbatim — every symbol their evidence names (`TRANSPORT["analyst"]`,
`SdkOutcome`, `LOG_TEMPLATES`, `containment_for`, `KNOWN_BACKENDS`,
`DEFAULT_BACKEND_FOR_SURFACE`) is in §9.4’s untouchable set.

### 12.2 `14-forward-work-map.md` — four new rows

(FW-121 is not about this unit at all: it is a latent gap in `S-48`’s
evidence chain that this unit’s enumeration surfaced and deliberately did
not fix. It is recorded here because a measured finding with no row is a
finding that gets rediscovered.)

**No FW row exists for `U-engine`, `U-hostmode` or `U-ancestry`** —
verified by grep over `docs/specs/self-learn/*.md`; the only hits are
`S-44`’s and `FW-106`’s mentions of `U-corrob`. The register recorded the
gap on 2026-08-20 (`:3120-3122`, verbatim: *"No FW row exists yet
(verified 20:38) — the row rides the next gated docs touch or U-engine’s
own spec"*). **This spec is that touch.** Highest existing row: `FW-117`.
Table header: `| # | Item | Type | Trigger / when |` (`:54`).

| # | Item | Type | Trigger / when |
|---|---|---|---|
| FW-118 | **The two SDK engines share a session LIBRARY; the two charters stay two.** `sdksession/` owns the session lifecycle end to end and takes policy as an object; both `build_can_use_tool` decision tables stay with their clients, held apart by the `AGR2` disagreement pin. The library is `async`-native and multi-session: `new_run_id` collisions, the per-surface sidecar singleton, start-of-session retention and the import-time staleness anchor are all fixed here (§4.6 F-1..F-4). Kill-ladder step 3 becomes conditional on `loop_closing` (§4.6 R-1). **Measured before the move: 18 of the 24 operator-visible messages the library owns were asserted by no test, 10 of the 13 shutdown messages included; pinning them with their prefixes is the unit’s real product.** | BUILD | Landed by `U-engine` Phase 1 |
| FW-119 | **`self-learn serve` — one long-lived host process replaces three systemd units and a covert any-verb watchdog.** ADOPTED by user ruling 2026-08-26 22:01, decisively on portability. **Register item #11 (the cgroup patch for the miner-to-worker handoff) is SUPERSEDED, not fixed:** `self-learn-miner.service` is `Type=oneshot` with `KillMode=control-group` (measured live 2026-08-26) and `worker._spawn_window`’s `start_new_session=True` escapes the process group but not the cgroup, so the handoff has never once completed (register `:880-895`). With one live process starting both jobs there is no detached child to reap, so the three unit-file remedies that row named are not applied. H-5 is preserved: `serve` is a SCHEDULER of producers, never a watcher — each job still takes its own `commit_lock` and commits its own paths. | BUILD | Landed by `U-engine` Phase 2 |
| FW-120 | **The `sdksession` library is deliberately NOT its own distribution.** It ships inside `self-learn-cli` because the UI already depends on that package (`ui/pyproject.toml:20`, `:53`) and the CLI cannot depend on the UI. **Trigger for revisiting: the first consumer outside this repository.** Until then a separate pyproject, lockfile entry, install step and third version-range is cost with no benefit. `U-engine` spec §4.5 states the four things "portable" is allowed to mean, and §4.8 R-h names the shapes it refuses (plugin systems, session-kind registries, middleware chains, transport abstraction). | WATCH | Trigger: a non-self-learn consumer exists |

| FW-121 | **`S-48`’s recorded `M11` evidence names the wrong symbol — a SURFACE MISMATCH between the decision row and the code.** The row says *"reverting `TRANSPORT["analyst"]` … proving the contract had to close at the transport-table level"*, but `invocation_sdk/backend.py:60` folds the table once at import — `_CATCHES_OS_ERROR = dict(TRANSPORT)` — and the except ladder branches on the FOLD, at `:417`, `:471`, `:479`. Measured 2026-08-26: setting `contract.TRANSPORT["analyst"] = False` after import leaves `backend._CATCHES_OS_ERROR["analyst"] is True`, so the backend observes nothing. **The contract is NOT untestable — the live control point is monkeypatchable and is already exercised**: `test_u_opsfix.py::test_fw108_no_line_when_surface_does_not_catch_os_error` does `monkeypatch.setitem(backend_mod._CATCHES_OS_ERROR, "worker", False)` (`:171`) and drives the real `SdkBackend`, asserting the surface-conditional behaviour. What is missing is only that `S-48` points a reader at `TRANSPORT`, and `test_u_sdka.py::test_m16_transport_table_is_still_a_plain_mutable_dict` (`:1135`) — which asserts only that the TABLE supports item assignment, never that the backend observes a change — is the test a reader following that wording lands on. **The real cost:** a maintainer exercising `M11` as written monkeypatches `TRANSPORT`, sees no behaviour change, and concludes the contract is broken. Found by `U-engine`’s single-session enumeration (spec §2.9, G-6); **NOT fixed there** — `contract.py` and the seam’s except ladder are outside that unit’s files-may-touch table, and the library must not read `TRANSPORT` at all. | BUILD | Not scheduled. Two candidate fixes, and the choice is a ruling not a detail: (a) amend `S-48`’s evidence sentence to name `_CATCHES_OS_ERROR` and cite `test_fw108_...` — a docs-only change that makes the row true as written; or (b) drop the fold and read `TRANSPORT[surface]` at call time in `_drive`, which makes the row’s original wording literally correct but changes the seam’s failure-leg dispatch. Belongs with whoever next touches `S-48`’s evidence |

**`FW-116` is adjacent and is left OPEN, deliberately.** Its subject is the
revert-based rollback path; `17` §6 now records the 2026-08-26 dry-run
that exercised it against a throwaway worktree, so the row’s *"nobody has
yet exercised that revert path for real"* is stale as to the dry-run but
still true as to a live incident. **This unit does not close it** — Phase 2
adds a new thing to revert (§5.9), which is a reason to keep it open, not
to close it. The one FW-116 detail this unit consumes is its measured
incident: the dry-run’s first `doctor` call landing five real commits,
which is §5.3’s evidence for reducing the watchdog.

### 12.3 `13-hosting-and-separation.md` §5 — the scheduler/watcher amendment

One paragraph appended to §5, and one clause added to §8’s `H-5` bullet:

> **`serve` is a scheduler, not a watcher (added by `U-engine` Phase 2).**
> H-5 says the ledger repo needs no autosync watcher, ever. The
> `self-learn serve` host process does not change that and is not one: it
> STARTS producers (`miner.run`, `worker.run`) on a schedule, and each
> producer still takes its own `commit_lock`, commits only its own
> pathspec, and uses its own pinned subject — exactly as when a verb or a
> timer started it. `serve` never stages, never commits, never pushes, and
> writes exactly one file: a heartbeat into `cache_dir()`, which is
> `NOT_REPO_TRUTH` by the same rule as every other cache write. The
> `reconcile` backstop is unchanged and still runs at the start of every
> `mine` and before every `push`. The mechanical consequence is in
> `test_lock_invariant.py`: `serve` becomes a derived ENTRYPOINT and
> `miner.run` / `worker.run` stop being roots, so every mutation reachable
> from `serve` inherits the lock obligation along a new path — which the
> walker checks structurally, without anyone declaring it.

### 12.4 `17-invocation-runbook.md`

- **§6 (Rollback)** — a phase-ordered paragraph: revert Phase 2 before
  Phase 1; re-enable `self-learn-miner.timer` when reverting Phase 2;
  neither phase touches either `pyproject.toml`, so unlike the
  `U-cleanup` revert nothing about `claude-agent-sdk`’s installation
  changes. Test the same way §6 already prescribes
  (`plugins/self-learn/cli/scripts/suite`; UI from **inside**
  `plugins/self-learn/ui`). The rehearsal trap of §6 item 4 is unchanged
  and now matters more, since `serve` is a second thing that can mine a
  ledger copy.
- **A new §10, `serve`** — starting and stopping it; the three supervisor
  shapes (systemd / launchd / a terminal); the heartbeat and the
  `doctor` row’s four verdicts; **do not run the timer and `serve` as
  rival schedulers unless you mean the timer as a poke**; the reduced
  watchdog’s two legs.
- **§5** — Phase 2’s burn-in observable recorded before merge:
  candidate volume per night within ±1σ of the pre-`serve` nights, the
  same instrument §5.2 already prescribes for the miner flip.

### 12.5 `12-transcript-miner.md` §3

§3 currently says the trigger is a nightly timer (`:198`, `:413`,
`:425`) and lists the watchdog at `:435-437`. Phase 2 amends §3 to state
the two supported topologies — **`serve`-scheduled (preferred)** and
**timer-scheduled (unchanged, for machines without a host process)** —
and rewrites the watchdog bullet to the two legs of §5.3. **The kill
switches keep their documented meaning** (`SELF_LEARN_MINER=0`,
`SELF_LEARN_MINER_AUTOKICK=0`) under both topologies.

---

## Q. Questions, all RULED

| # | Question | Ruling |
|---|---|---|
| **Q-1** | Diverge, unify, rebuild, or a shared library? | **RULED by the user: the library (option 4).** §3.1 |
| **Q-2** | Should the long-lived host process exist? | **RULED by the user, 2026-08-26 22:01: ADOPTED.** §3.2. This reverses r1 |
| **Q-3** | Do the two charters merge? | **RULED — no, and not later.** §3.1; `AGR2` is the only detector; §11 row 1 |
| **Q-4** | Where does the library live? | **RULED — the CLI distribution.** §2.7: the other direction does not compile. Own distribution deferred behind a named trigger (§11 row 9, FW-120) |
| **Q-5** | What does "portable" license? | **RULED — exactly four things** (§4.5), and four named shapes are refused (§4.8 R-h) |
| **Q-6** | Is multi-session a criterion or a door? | **RULED — a criterion.** `MS1`-`MS7`, and `MS1` gates Phase 2 (§10.1 item 3) |
| **Q-7** | What happens to kill-ladder step 3 under a persistent loop? | **RULED — conditional on `loop_closing`** (§4.6 R-1), both directions pinned by `LAD4` |
| **Q-8** | Does `run_sync` move into the library? | **RULED — no.** §4.6 R-2; `MS6`/`HP2` |
| **Q-9** | Is the any-verb watchdog retired? | **RULED — reduced, not retired**, with both legs pinned (`HP6`). §5.3 gives the reason in both directions |
| **Q-10** | Does the timer survive? | **RULED — yes, optionally, as a poke.** Both-enabled is `WARN` naming that configuration, never `FAIL` (`SUP4`, §5.7) |
| **Q-11** | Is zero armor re-pin still a criterion? | **RULED — no**, it is a target. §10.2 states the expectation per phase and the full discharge procedure, including the reverse-rename proof, if one becomes unavoidable |
| **Q-12** | Which "host" is which? | **RULED** — §5.1’s terminology table. **canon host** = `U-hostmode`; **host process / `serve`** = this unit. Neither used bare |
| **Q-13** | What is the Phase 2 burn-in bar? | **RULED — coverage** (`S-49`’s soak waiver) **plus exactly one live observable**: candidate volume ±1σ, the miner-flip instrument verbatim (§5.8) |
| **Q-14** | Does `serve` run jobs concurrently or serially? | **RULED (orchestrator, 2026-08-26): SERIALLY**, one job at a time. §5.2a — the producers are already serialised by their own locks, so serial is the shape that changes nothing about producer semantics. **This is a ruling about the DAEMON, not the library**, which stays multi-session by ruling |
| **Q-15** | Which concurrency fixes survive the serial ruling? | **RULED — three of four are still FORCED, one is re-specified.** §5.2a.1, each with its evidence: **F-1** `new_run_id` (two SEQUENTIAL jobs in one second collide; the §2.9 measurement was itself sequential), **F-3** `prune_event_logs` at session start (the hazard is CROSS-PROCESS — `cache_dir()` is shared machine-wide and `analyst.analyze` holds no lock, so two `teach --route` shells prune each other), **F-4** `_PROCESS_START` (a daemon-boot anchor means a child leaked by job 1 is never stale for job 5 — serial makes this WORSE). **F-2** the sidecar becomes a cleanup-ORDERING requirement between sequential same-surface jobs, tested by `MS1-seq` leg 3 rather than by `MS3` |
| **Q-16** | Does `MS1` still gate Phase 2? | **RULED — no.** It stays a Phase 1 merge criterion (the library is multi-session by ruling; an unproven capability is a claim). **Phase 2’s gate is `MS1-seq`** (§7.1). And `MS1` proves BOOKKEEPING on a stub, never real-transport concurrency — §11 row 15 |
| **Q-17** | Does the library read `TRANSPORT` at call time? | **RULED — it must not read it at all.** §2.9 G-6: the OSError split is seam policy consumed in `_drive`’s except ladder (`backend.py:417`, `:471`, `:479`), which stays in `invocation_sdk`; a `TRANSPORT` read would import `invocation.contract`, which `LIB1` forbids. **The related finding is a SURFACE MISMATCH, not an untestable contract:** the backend branches on the import-time fold `_CATCHES_OS_ERROR`, which `test_u_opsfix.py::test_fw108_no_line_when_surface_does_not_catch_os_error` already monkeypatches against the real `SdkBackend` — it is `S-48`’s wording that names `TRANSPORT` instead. Recorded as **FW-121**, not fixed here |

### Q.14 Open for the BUILDER to measure, not for the orchestrator to rule

- The library’s final line count and the net delta per edited file. §4.2
  bounds the region at **405 raw / 287 code** under §2.0’s instrument; what actually moves is a build-time measurement.
- Whether `new_run_id`’s collision-free component is `uuid4().hex[:8]` or
  a per-process monotonic counter. Either satisfies `MS2`; the builder
  states which and why.
- Whether the two `policy_impl` implementations are separate modules or
  live inside the existing engine/backend files. The Protocol is the
  criterion; the file layout is not.
- `serve`’s tick interval, and whether the schedule is expressed as a
  cron-like spec or a simple next-run timestamp. Constrained only by
  `SUP1` (a heartbeat per tick) and `SUP2` (`doctor` compares the
  heartbeat age against one tick interval).
- Whether `run_kill_ladder`’s `K-1a`/`K-1b` docstring splits between the
  surface and the library. Either is fine; **its content must survive
  somewhere**, because it is the only written record of why step 3 exists
  — and §4.6 R-1 now makes that record load-bearing.

### Q.15 What could NOT be measured

- **Whether the cgroup reap still occurs at `a0c67be`.** The finding is
  the register’s, from a live timer run (`:880-895`). The `KillMode` and
  `Type` values were re-verified live; the reap itself was not reproduced
  by this spec and is not claimed as this spec’s measurement.
- **Whether any behavioural difference exists between the two kill
  ladders that one engine fixed and the other did not.** The gate searched
  and found none; §2.2b states the three differences that DO exist and
  their stated rationales. **No bug-in-one-copy claim is made anywhere in
  this spec**, and r1’s "already measurably drifted" justification is
  withdrawn (§2.2b).
- **The live effect of `serve` on candidate volume.** That is Phase 2’s
  burn-in observable (§5.8) and is operator work after the merge.

---

## R. Revision history

- **r1 (2026-08-26)** — first draft. Census measured at `a0c67be`; both
  suite baselines re-measured. Ruled the host process OUT and scoped the
  extraction to four helpers. 35 criteria, 17 mutations, 9 questions.
- **r2 (2026-08-26)** — **amended per user ruling: host process ADOPTED**,
  and the four-option decision recorded (§3). Scope enlarged from four
  helpers to the session lifecycle with policy as an object; multi-session
  promoted from a door to a criterion group; Phase 2 (`self-learn serve`)
  added with its own criteria, mutations, files and docs. **Four spec-gate
  findings folded:** the "already drifted" justification WITHDRAWN and
  replaced with the true and better one (two correct copies, unwatched —
  §2.2b); the fragment-level census added and its 1.000 `ResultMessage`
  error-detail pair adopted into the library (§2.2a), amending r1’s false
  claim that the two mappings share no extractable vocabulary; the ladder
  line counts corrected (CLI 5 not 4; UI 8 not 7 — r1 missed
  `"pane engine interrupt: SDK interrupt() failed, escalating"`); and the
  line-counting instrument stated once and used throughout (§2.0), which
  changes the region figures from r1’s unreproducible 99/4.3% to a stated
  307 code lines of 1286, 23.9% — itself corrected at r3, see below. **The pin census (§2.8) is new and is now
  the unit’s stated product**: 24 library-owned messages, 5 pinned with
  prefix, 1 prefix-free only, 18 asserted nowhere. **56 criteria — Phase 1
  39 (22 [A] / 17 [B]), Phase 2 17 (10 [A] / 7 [B]) — 33 predicted
  mutations, 3 measured anchors, 13 questions ruled.**
- **r3 (2026-08-26)** — **spec gate r2 returned SOUND, no blockers**; its
  five folds applied in place. **`serve` runs jobs SERIALLY**
  (orchestrator ruling, §5.2a), so §5.2a.1 states which concurrency fixes
  survive and why: F-1, F-3 and F-4 are still FORCED (two SEQUENTIAL jobs
  in one second collide; `prune_event_logs` is a CROSS-PROCESS hazard
  over a machine-shared `cache_dir()` with `analyst.analyze` holding no
  lock; a daemon-boot staleness anchor makes orphan sweeping WORSE, not
  better), while F-2 is re-specified as a cleanup-ORDERING obligation.
  **`MS1` stops gating Phase 2** — it stays a Phase 1 library criterion,
  now carrying an explicit statement that it proves per-session
  BOOKKEEPING on a stub and never real-transport concurrency
  (`FW-104`-class, **stated not tested**, §11 row 15) — and Phase 2’s
  gate becomes the new **`MS1-seq`**. Concurrent jobs are OUT with a
  named trigger (§11 row 14). **`MS2` gains its regardless-of-surface
  clause** and `M-10` is restated *(both r2’s and r3’s rationales for it
  were wrong; corrected at r4 below)*. **The region figures are corrected and now
  re-derive**: r2’s 446/307 and 23.9% were measured over a candidate set
  that still included four symbols the design excludes, so the subtotals
  did not sum to the printed cells; the region is **405 raw / 287 code —
  22.3% of 1286 code lines**, itemised per symbol with the four
  exclusions named. **The pin census is re-partitioned**: one of the 24
  messages (`sdk[...]` log forwarding) is CLIENT-owned by this spec’s own
  G-4/C-4 design, so the library owns **23**, of which **17** are
  asserted nowhere. **`G-6` added to the single-session enumeration** —
  `_CATCHES_OS_ERROR = dict(TRANSPORT)` is an import-time SNAPSHOT, not a
  frozen constant (measured: mutating `TRANSPORT` leaves the backend
  reading `True`); the library must not read `TRANSPORT` at all, and the
  latent `S-48`/`M11` evidence gap it exposes is recorded as **FW-121**,
  not fixed here. **57 criteria — Phase 1 39 (22 [A] / 17 [B]), Phase 2
  18 (11 [A] / 7 [B]) — 33 predicted mutations, 3 measured anchors, 17
  questions ruled, 15 OUT rows, 4 FW rows.**
- **r4 (2026-08-26)** — **spec gate r3 returned SOUND, no blockers**
  (it ran both `MS2` mutation variants at 10 000 calls and verified the
  region cell for cell, 24/24). Seven prose corrections, no structural
  change — criteria, mutations, phases and counts are untouched.
  **The consequential one: `FW-121` was WRONG and is restated.** r3
  claimed `S-48`’s `M11` evidence *"holds only for a source edit, not a
  runtime mutation"*. It does not:
  `test_u_opsfix.py::test_fw108_no_line_when_surface_does_not_catch_os_error`
  monkeypatches `backend._CATCHES_OS_ERROR` (`:171`) and drives the real
  `SdkBackend`, so the live control point is monkeypatchable and already
  exercised. **The accurate, narrower finding is a SURFACE MISMATCH:**
  `S-48`’s wording names `TRANSPORT`, the backend branches on the
  import-time fold `_CATCHES_OS_ERROR`, and mutating the former after
  import changes nothing the latter observes — so a maintainer following
  the row as written sees no behaviour change and wrongly concludes the
  contract is broken. FW-121 now offers two candidate fixes (amend the
  row’s wording, or drop the fold) and marks the choice a ruling.
  Applied at the same three sites the claim appeared: §2.9 G-6, `Q-17`,
  and the FW-121 row itself. **`M-10`’s rationale corrected in both
  directions:** r2 said a per-surface counter dies across two surfaces,
  r3 said it dies on the all-same-surface leg — measured by the gate,
  a per-surface COUNTER passes all-same-surface and fails the INTERLEAVED
  leg (5000/10000), while a per-surface SEED fails both, which is exactly
  why `MS2` keeps two legs. **`MS1-seq` now FORCES its same-second
  condition** by freezing the time source `new_run_id` reads
  (monkeypatch `events`’s `time.gmtime`) rather than relying on
  wall-clock luck — otherwise its own positive control can silently fail
  to fail. Also corrected: the test name
  `test_m16_transport_table_is_still_a_plain_mutable_dict`
  (`test_u_sdka.py:1135`; r3 used the U-cleanup tag from its docstring),
  the except-ladder read sites (`backend.py:417`, `:471`, `:479`), §2.9’s
  preamble (**six** stateful bindings of 21, not five of 21), and §4.2’s
  exclusion total (**53 raw / 32 code** — a different quantity from the
  r2-to-r3 delta of 41/20, which r3 conflated).
